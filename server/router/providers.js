import { mockChat } from './mock.js';

export class ProviderError extends Error {
  constructor(message, { status = 0, retryable = false, auth = false } = {}) {
    super(message);
    this.name = 'ProviderError';
    this.status = status;
    this.retryable = retryable;
    this.auth = auth;
  }
}

const DEFAULT_TIMEOUT_MS = 180_000;

function classify(status, body) {
  const text = String(body).slice(0, 400);
  return new ProviderError(`HTTP ${status}: ${text}`, {
    status,
    retryable: status === 408 || status === 409 || status === 429 || status >= 500,
    auth: status === 401 || status === 403,
  });
}

function withTimeout(signal, ms) {
  const timeout = AbortSignal.timeout(ms);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

async function post(url, headers, body, signal, timeoutMs) {
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...headers },
      body: JSON.stringify(body),
      signal: withTimeout(signal, timeoutMs),
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ProviderError(`Network error: ${err.cause?.message ?? err.message}`, { retryable: true });
  }
  const raw = await res.text();
  if (!res.ok) throw classify(res.status, raw);
  try {
    return JSON.parse(raw);
  } catch {
    throw new ProviderError(`Invalid JSON from provider: ${raw.slice(0, 200)}`, { retryable: true });
  }
}

// Reasoning models sometimes inline their scratchpad; agents only want the answer.
const stripThinking = (text) => String(text ?? '').replace(/<think>[\s\S]*?<\/think>/gi, '').trim();

function partsToText(content) {
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) return content.map((p) => (typeof p === 'string' ? p : p?.text ?? '')).join('');
  return '';
}

async function openaiChat(provider, providerId, model, req, signal) {
  const key = provider.keyEnv ? process.env[provider.keyEnv] : '';
  const headers = key ? { authorization: `Bearer ${key}` } : {};
  if (providerId === 'openrouter') {
    headers['http-referer'] = 'http://localhost/agent-world';
    headers['x-title'] = 'Agent World';
  }
  const body = {
    model,
    messages: req.messages,
    max_tokens: req.maxTokens ?? 4096,
    ...(req.temperature !== undefined ? { temperature: req.temperature } : {}),
  };
  const wantJson = req.json && provider.jsonMode !== false;
  if (wantJson) body.response_format = { type: 'json_object' };

  const url = `${provider.baseUrl.replace(/\/$/, '')}/chat/completions`;
  const timeout = provider.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  let data;
  try {
    data = await post(url, headers, body, signal, timeout);
  } catch (err) {
    // Some OpenAI-compatible servers reject response_format: retry once without it.
    if (!(wantJson && err instanceof ProviderError && err.status === 400)) throw err;
    delete body.response_format;
    data = await post(url, headers, body, signal, timeout);
  }
  const choice = data.choices?.[0];
  const text = stripThinking(partsToText(choice?.message?.content));
  if (!text) throw new ProviderError('Empty answer from provider', { retryable: true });
  return {
    text,
    model: data.model ?? model,
    usage: { in: data.usage?.prompt_tokens ?? 0, out: data.usage?.completion_tokens ?? 0 },
  };
}

// Anthropic Messages API: system goes apart, roles must alternate starting with user.
function toAnthropicMessages(messages) {
  const system = [];
  const out = [];
  for (const m of messages) {
    const text = partsToText(m.content);
    if (m.role === 'system') {
      system.push(text);
      continue;
    }
    const role = m.role === 'assistant' ? 'assistant' : 'user';
    const last = out.at(-1);
    if (last && last.role === role) last.content += `\n\n${text}`;
    else out.push({ role, content: text });
  }
  if (out[0]?.role !== 'user') out.unshift({ role: 'user', content: '(start)' });
  return { system: system.join('\n\n'), messages: out };
}

async function anthropicChat(provider, model, req, signal) {
  const key = process.env[provider.keyEnv];
  const { system, messages } = toAnthropicMessages(req.messages);
  const body = { model, max_tokens: req.maxTokens ?? 4096, messages };
  if (system) body.system = system;
  if (req.temperature !== undefined) body.temperature = req.temperature;
  const data = await post(
    `${provider.baseUrl.replace(/\/$/, '')}/messages`,
    { 'x-api-key': key, 'anthropic-version': '2023-06-01' },
    body,
    signal,
    provider.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );
  const text = stripThinking((data.content ?? []).filter((b) => b.type === 'text').map((b) => b.text).join(''));
  if (!text) throw new ProviderError('Empty answer from provider', { retryable: true });
  return {
    text,
    model: data.model ?? model,
    usage: { in: data.usage?.input_tokens ?? 0, out: data.usage?.output_tokens ?? 0 },
  };
}

export function callProvider(provider, providerId, model, req, signal) {
  switch (provider.kind) {
    case 'mock':
      return mockChat(provider, model, req, signal);
    case 'anthropic':
      return anthropicChat(provider, model, req, signal);
    case 'openai':
      return openaiChat(provider, providerId, model, req, signal);
    default:
      throw new ProviderError(`Unknown provider kind "${provider.kind}"`);
  }
}
