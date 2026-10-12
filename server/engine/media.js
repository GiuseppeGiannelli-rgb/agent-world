import { deflateSync } from 'node:zlib';
import { ProviderError } from '../router/providers.js';

// Generative media for the AI team: images and speech, with the same
// fallback idea as the text router. With no key, the demo provider draws a
// real PNG (or SVG) and a short WAV, so files and previews always exist.

function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return h >>> 0;
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}

function hsl(h, s, l) {
  const a = s * Math.min(l, 1 - l);
  const f = (n) => {
    const k = (n + h / 30) % 12;
    return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
  };
  return [f(0), f(8), f(4)];
}

// A soft abstract artwork seeded by the prompt: gradient sky, sun, hills.
export function demoPng(prompt, size = 512) {
  const seed = hash(prompt);
  const hue = seed % 360;
  const top = hsl(hue, 0.65, 0.72);
  const bottom = hsl((hue + 40) % 360, 0.7, 0.9);
  const sun = hsl((hue + 180) % 360, 0.8, 0.62);
  const hill1 = hsl((hue + 200) % 360, 0.35, 0.45);
  const hill2 = hsl((hue + 220) % 360, 0.3, 0.32);
  const sx = 0.3 + ((seed >> 8) % 40) / 100;
  const raw = Buffer.alloc((size * 3 + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (size * 3 + 1)] = 0;
    for (let x = 0; x < size; x++) {
      const u = x / size;
      const v = y / size;
      let c = top.map((t, i) => Math.round(t + (bottom[i] - t) * v));
      if (Math.hypot(u - sx, v - 0.38) < 0.13) c = sun;
      const h1 = 0.62 + Math.sin(u * 6 + (seed % 7)) * 0.05;
      const h2 = 0.74 + Math.sin(u * 4.3 + (seed % 5) + 1) * 0.06;
      if (v > h1) c = hill1;
      if (v > h2) c = hill2;
      const o = y * (size * 3 + 1) + 1 + x * 3;
      raw[o] = c[0];
      raw[o + 1] = c[1];
      raw[o + 2] = c[2];
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}

export function demoSvg(prompt) {
  const seed = hash(prompt);
  const hue = seed % 360;
  const safe = String(prompt).replace(/[<>&"]/g, '').slice(0, 60);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="hsl(${hue},65%,72%)"/><stop offset="1" stop-color="hsl(${(hue + 40) % 360},70%,90%)"/></linearGradient></defs>
  <rect width="512" height="512" fill="url(#g)"/>
  <circle cx="${160 + (seed % 200)}" cy="190" r="66" fill="hsl(${(hue + 180) % 360},80%,62%)"/>
  <path d="M0 330 Q128 280 256 320 T512 310 V512 H0Z" fill="hsl(${(hue + 200) % 360},35%,45%)"/>
  <path d="M0 400 Q160 360 300 390 T512 380 V512 H0Z" fill="hsl(${(hue + 220) % 360},30%,32%)"/>
  <text x="256" y="480" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#fff" opacity=".85">${safe}</text>
</svg>`;
}

// 1.6 s two-note chime, 16-bit mono WAV.
export function demoWav(text) {
  const rate = 22050;
  const n = Math.round(rate * 1.6);
  const data = Buffer.alloc(n * 2);
  const f1 = 440 + (hash(text) % 6) * 40;
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const f = t < 0.7 ? f1 : f1 * 1.5;
    const env = Math.exp(-((t % 0.8) * 4));
    data.writeInt16LE(Math.round(Math.sin(2 * Math.PI * f * t) * env * 9000), i * 2);
  }
  const h = Buffer.alloc(44);
  h.write('RIFF', 0);
  h.writeUInt32LE(36 + data.length, 4);
  h.write('WAVEfmt ', 8);
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20);
  h.writeUInt16LE(1, 22);
  h.writeUInt32LE(rate, 24);
  h.writeUInt32LE(rate * 2, 28);
  h.writeUInt16LE(2, 32);
  h.writeUInt16LE(16, 34);
  h.write('data', 36);
  h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

async function fetchBytes(url, init, signal) {
  let res;
  try {
    res = await fetch(url, { ...init, signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(180000)]) : AbortSignal.timeout(180000) });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ProviderError(`Network error: ${err.cause?.message ?? err.message}`, { retryable: true });
  }
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ProviderError(`HTTP ${res.status}: ${body.slice(0, 300)}`, { status: res.status, retryable: res.status === 429 || res.status >= 500, auth: res.status === 401 || res.status === 403 });
  }
  return { bytes: Buffer.from(await res.arrayBuffer()), type: res.headers.get('content-type') ?? '' };
}

async function fetchJson(url, init, signal) {
  const { bytes } = await fetchBytes(url, init, signal);
  return JSON.parse(bytes.toString('utf8'));
}

export class Media {
  constructor({ config, bus }) {
    this.config = config;
    this.bus = bus;
  }

  get cfg() {
    return this.config.get().media;
  }

  ready(id) {
    const p = this.cfg.providers[id];
    if (!p || p.enabled === false) return false;
    if (p.kind === 'mock' || p.keyless) return true;
    return Boolean(p.keyEnv && process.env[p.keyEnv]);
  }

  targets(kind) {
    const list = (this.cfg[kind] ?? []).map((t) => ({ provider: t.slice(0, t.indexOf('/')), model: t.slice(t.indexOf('/') + 1) })).filter((t) => this.ready(t.provider));
    return list.length ? list : [{ provider: 'mock', model: 'demo', demo: true }];
  }

  status() {
    return {
      image: this.targets('image').map((t) => `${t.provider}/${t.model}`),
      speech: this.targets('speech').map((t) => `${t.provider}/${t.model}`),
      providers: Object.entries(this.cfg.providers).filter(([id]) => id !== 'mock').map(([id, p]) => ({ id, keyEnv: p.keyEnv ?? null, ready: this.ready(id), enabled: p.enabled !== false })),
    };
  }

  async run(kind, fn) {
    const errors = [];
    for (const t of this.targets(kind)) {
      const p = this.cfg.providers[t.provider];
      const key = p.keyEnv ? process.env[p.keyEnv] : '';
      try {
        const out = await fn(t, p, key);
        return { ...out, target: `${t.provider}/${t.model}`, demo: Boolean(t.demo) };
      } catch (err) {
        errors.push(`${t.provider}/${t.model}: ${err.message}`);
      }
    }
    throw new Error(`Generation failed:\n${errors.join('\n')}`);
  }

  // Returns { bytes, ext } — the caller decides the file name.
  image({ prompt, size = '1024x1024', ext = 'png' }, signal) {
    return this.run('image', async (t, p, key) => {
      if (p.kind === 'mock') return ext === 'svg' ? { bytes: Buffer.from(demoSvg(prompt)), ext: 'svg' } : { bytes: demoPng(prompt), ext: 'png' };
      if (p.kind === 'openai') {
        const data = await fetchJson(`${p.baseUrl}/images/generations`, { method: 'POST', headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` }, body: JSON.stringify({ model: t.model, prompt, size, n: 1 }) }, signal);
        const item = data.data?.[0];
        if (item?.b64_json) return { bytes: Buffer.from(item.b64_json, 'base64'), ext: 'png' };
        if (item?.url) return { bytes: (await fetchBytes(item.url, {}, signal)).bytes, ext: 'png' };
        throw new Error('No image in the answer');
      }
      if (p.kind === 'fal') {
        const data = await fetchJson(`https://fal.run/${t.model}`, { method: 'POST', headers: { 'content-type': 'application/json', authorization: `Key ${key}` }, body: JSON.stringify({ prompt, image_size: 'square_hd' }) }, signal);
        const url = data.images?.[0]?.url;
        if (!url) throw new Error('No image in the answer');
        const img = await fetchBytes(url, {}, signal);
        return { bytes: img.bytes, ext: img.type.includes('jpeg') ? 'jpg' : 'png' };
      }
      if (p.kind === 'pollinations') {
        const [w, h] = size.split('x');
        const img = await fetchBytes(`https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=${w}&height=${h}&nologo=true&model=${encodeURIComponent(t.model)}`, {}, signal);
        return { bytes: img.bytes, ext: img.type.includes('png') ? 'png' : 'jpg' };
      }
      throw new Error(`Unknown image provider kind ${p.kind}`);
    });
  }

  speech({ text, voice }, signal) {
    return this.run('speech', async (t, p, key) => {
      if (p.kind === 'mock') return { bytes: demoWav(text), ext: 'wav' };
      if (p.kind === 'openai') {
        const { bytes } = await fetchBytes(`${p.baseUrl}/audio/speech`, { method: 'POST', headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` }, body: JSON.stringify({ model: t.model, voice: voice || 'alloy', input: String(text).slice(0, 4000), response_format: 'mp3' }) }, signal);
        return { bytes, ext: 'mp3' };
      }
      if (p.kind === 'elevenlabs') {
        const { bytes } = await fetchBytes(`https://api.elevenlabs.io/v1/text-to-speech/${p.voiceId}?output_format=mp3_44100_128`, { method: 'POST', headers: { 'content-type': 'application/json', 'xi-api-key': key }, body: JSON.stringify({ text: String(text).slice(0, 4000), model_id: t.model }) }, signal);
        return { bytes, ext: 'mp3' };
      }
      throw new Error(`Unknown speech provider kind ${p.kind}`);
    });
  }
}
