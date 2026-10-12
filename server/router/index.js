import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { callProvider, ProviderError } from './providers.js';

const clip = (s, n) => (typeof s === 'string' && s.length > n ? `${s.slice(0, n)}… [${s.length - n} more chars]` : s);

// The router is the app's own gateway: a request names a combo ("smart"),
// a role ("builder", which maps to a combo) or one model ("groq/llama-…").
// A combo is an ordered list of provider/model targets; the router walks it,
// skipping providers with no key and targets cooling down after errors.
export class Router {
  constructor({ config, dataDir, bus }) {
    this.config = config;
    this.dataDir = dataDir;
    this.bus = bus;
    this.cooldowns = new Map(); // target -> { until, failures, reason }
    this.stats = new Map(); // target -> counters
    this.rrCursor = new Map(); // combo -> next start index
    this.recent = [];
  }

  get cfg() {
    return this.config.get();
  }

  providerReady(id) {
    const p = this.cfg.providers[id];
    if (!p || p.enabled === false) return false;
    if (p.kind === 'mock' || p.keyless) return true;
    return Boolean(p.keyEnv && process.env[p.keyEnv]);
  }

  // "live" as soon as one real provider can be called, "demo" otherwise.
  mode() {
    const live = Object.entries(this.cfg.providers).some(([id, p]) => p.kind !== 'mock' && this.providerReady(id));
    return live ? 'live' : 'demo';
  }

  parseTarget(target) {
    const slash = target.indexOf('/');
    if (slash < 1) return null;
    return { provider: target.slice(0, slash), model: target.slice(slash + 1), key: target };
  }

  // Turns "combo:smart" / "smart" / "groq/model" into an ordered plan.
  expand(spec) {
    const name = spec.startsWith('combo:') ? spec.slice(6) : spec;
    const combo = this.cfg.combos[name];
    if (combo) {
      return { combo: name, strategy: combo.strategy ?? 'fallback', targets: combo.models.map((t) => this.parseTarget(t)).filter(Boolean) };
    }
    const single = this.parseTarget(spec);
    if (!single) throw new Error(`Unknown combo or model "${spec}"`);
    return { combo: null, strategy: 'fallback', targets: [single] };
  }

  // A role is "ceo" or a team id; each one names the combo it runs on.
  specForRole(role) {
    if (role === 'ceo') return this.cfg.ceo?.combo ?? this.cfg.router.defaultCombo;
    return this.cfg.teams?.[role]?.combo ?? this.cfg.router.defaultCombo;
  }

  plan(spec, role) {
    const { combo, strategy, targets } = this.expand(spec);
    let ready = targets.filter((t) => this.providerReady(t.provider));
    let demo = false;
    if (ready.length === 0) {
      if (!this.cfg.router.demoFallback) throw new Error(`No provider with a key in "${spec}"`);
      ready = [{ provider: 'mock', model: `mock-${role ?? 'any'}`, key: `mock/mock-${role ?? 'any'}` }];
      demo = true;
    }
    if (strategy === 'round-robin' && ready.length > 1 && combo) {
      const start = (this.rrCursor.get(combo) ?? 0) % ready.length;
      this.rrCursor.set(combo, start + 1);
      ready = [...ready.slice(start), ...ready.slice(0, start)];
    }
    // Cooling targets go last instead of disappearing: better a slow answer than none.
    const now = Date.now();
    const warm = ready.filter((t) => !(this.cooldowns.get(t.key)?.until > now));
    const cold = ready.filter((t) => this.cooldowns.get(t.key)?.until > now).sort((a, b) => this.cooldowns.get(a.key).until - this.cooldowns.get(b.key).until);
    return { combo, strategy, demo, order: [...warm, ...cold] };
  }

  async chat({ role, use, messages, json = false, maxTokens, temperature, signal, meta = {} }) {
    const spec = use ?? this.specForRole(role);
    const { combo, demo, order } = this.plan(spec, role);
    const errors = [];
    for (const target of order) {
      if (signal?.aborted) throw signal.reason ?? new Error('aborted');
      const provider = this.cfg.providers[target.provider];
      const started = Date.now();
      try {
        const res = await callProvider(provider, target.provider, target.model, { messages, json, maxTokens, temperature, role }, signal);
        const ms = Date.now() - started;
        this.cooldowns.delete(target.key);
        this.record(target, { ok: true, ms, usage: res.usage });
        const summary = this.log({ target, combo, role, meta, ms, ok: true, usage: res.usage, messages, text: res.text, demo });
        return { text: res.text, provider: target.provider, model: res.model, target: target.key, usage: res.usage, ms, callId: summary.id, demo };
      } catch (err) {
        if (signal?.aborted) throw err;
        const ms = Date.now() - started;
        this.cool(target, err);
        this.record(target, { ok: false, ms, error: err.message });
        this.log({ target, combo, role, meta, ms, ok: false, error: err.message, messages, demo });
        errors.push(`${target.key}: ${err.message}`);
      }
    }
    throw new ProviderError(`Every target failed for "${spec}":\n${errors.join('\n')}`);
  }

  cool(target, err) {
    const r = this.cfg.router;
    if (err instanceof ProviderError && err.auth) {
      // A refused key fails the same way for every model of that provider.
      for (const t of Object.values(this.cfg.combos).flatMap((c) => c.models)) {
        if (t.startsWith(`${target.provider}/`)) this.cooldowns.set(t, { until: Date.now() + r.authCooldownMs, failures: 1, reason: 'auth' });
      }
      return;
    }
    if (err instanceof ProviderError && !err.retryable) return;
    const prev = this.cooldowns.get(target.key);
    const failures = (prev?.failures ?? 0) + 1;
    const wait = Math.min(r.cooldownBaseMs * 2 ** (failures - 1), r.cooldownMaxMs);
    this.cooldowns.set(target.key, { until: Date.now() + wait, failures, reason: err.message.slice(0, 120) });
  }

  record(target, { ok, ms, usage, error }) {
    const s = this.stats.get(target.key) ?? { calls: 0, ok: 0, fail: 0, tokensIn: 0, tokensOut: 0, totalMs: 0, lastError: null };
    s.calls += 1;
    s.totalMs += ms;
    if (ok) {
      s.ok += 1;
      s.tokensIn += usage?.in ?? 0;
      s.tokensOut += usage?.out ?? 0;
    } else {
      s.fail += 1;
      s.lastError = error;
    }
    s.lastAt = Date.now();
    this.stats.set(target.key, s);
  }

  log({ target, combo, role, meta, ms, ok, usage, error, messages, text, demo }) {
    const summary = {
      id: randomUUID(),
      at: new Date().toISOString(),
      target: target.key,
      provider: target.provider,
      model: target.model,
      combo,
      role: role ?? null,
      runId: meta.runId ?? null,
      taskId: meta.taskId ?? null,
      agentId: meta.agentId ?? null,
      ms,
      ok,
      demo,
      tokens: { in: usage?.in ?? 0, out: usage?.out ?? 0 },
      error: error ?? null,
    };
    this.recent.unshift(summary);
    this.recent.length = Math.min(this.recent.length, 200);
    this.bus.emit('router.call', summary);
    if (this.cfg.router.logCalls) {
      const day = summary.at.slice(0, 10);
      const dir = join(this.dataDir, 'calls', day);
      const file = join(dir, `${summary.at.replace(/[:.]/g, '-')}_${summary.id}.json`);
      const record = {
        summary,
        request: messages.map((m) => ({ role: m.role, content: clip(String(m.content), 6000) })),
        response: clip(text ?? null, 12000),
      };
      mkdir(dir, { recursive: true })
        .then(() => writeFile(file, JSON.stringify(record, null, 1)))
        .catch(() => {});
    }
    return summary;
  }

  snapshot() {
    const now = Date.now();
    const cfg = this.cfg;
    return {
      mode: this.mode(),
      providers: Object.entries(cfg.providers).map(([id, p]) => ({
        id,
        kind: p.kind,
        baseUrl: p.baseUrl ?? null,
        keyEnv: p.keyEnv ?? null,
        enabled: p.enabled !== false,
        ready: this.providerReady(id),
      })),
      combos: Object.entries(cfg.combos).map(([name, c]) => ({
        name,
        strategy: c.strategy ?? 'fallback',
        targets: c.models.map((key) => {
          const t = this.parseTarget(key);
          const cd = this.cooldowns.get(key);
          return {
            key,
            ready: t ? this.providerReady(t.provider) : false,
            coolingMs: cd && cd.until > now ? cd.until - now : 0,
            reason: cd && cd.until > now ? cd.reason : null,
            stats: this.stats.get(key) ?? null,
          };
        }),
      })),
      recent: this.recent.slice(0, 60),
    };
  }
}
