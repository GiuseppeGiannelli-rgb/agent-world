"""Mirrors server/engine/media.js: generative media for the AI team, with
the same fallback idea as the text router. With no key, the demo provider
draws a real PNG (or SVG) and a short WAV, so files and previews always
exist. The drawing algorithm is ported line by line, so demo art looks the
same on both backends (the PNG bytes may differ: Node's deflateSync and
Python's zlib.compress pick different zlib streams for identical pixels)."""

import base64
import math
import struct
import zlib

import httpx

from backend.router.providers import ProviderError

TIMEOUT_S = 180


def _hash(s: str) -> int:
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def _chunk(type_: bytes, data: bytes) -> bytes:
    td = type_ + data
    return struct.pack(">I", len(data)) + td + struct.pack(">I", zlib.crc32(td) & 0xFFFFFFFF)


def _hsl(h: float, s: float, l: float) -> list[int]:
    a = s * min(l, 1 - l)

    def f(n: int) -> int:
        k = (n + h / 30) % 12
        return round(255 * (l - a * max(-1, min(k - 3, 9 - k, 1))))

    return [f(0), f(8), f(4)]


def demo_png(prompt: str, size: int = 512) -> bytes:
    """A soft abstract artwork seeded by the prompt: gradient sky, sun, hills."""
    seed = _hash(prompt)
    hue = seed % 360
    top = _hsl(hue, 0.65, 0.72)
    bottom = _hsl((hue + 40) % 360, 0.7, 0.9)
    sun = _hsl((hue + 180) % 360, 0.8, 0.62)
    hill1 = _hsl((hue + 200) % 360, 0.35, 0.45)
    hill2 = _hsl((hue + 220) % 360, 0.3, 0.32)
    sx = 0.3 + ((seed >> 8) % 40) / 100
    stride = size * 3 + 1
    raw = bytearray(stride * size)
    for y in range(size):
        for x in range(size):
            u, v = x / size, y / size
            c = [round(t + (bottom[i] - t) * v) for i, t in enumerate(top)]
            if math.hypot(u - sx, v - 0.38) < 0.13:
                c = sun
            h1 = 0.62 + math.sin(u * 6 + (seed % 7)) * 0.05
            h2 = 0.74 + math.sin(u * 4.3 + (seed % 5) + 1) * 0.06
            if v > h1:
                c = hill1
            if v > h2:
                c = hill2
            o = y * stride + 1 + x * 3
            raw[o : o + 3] = bytes(c)
    ihdr = struct.pack(">IIBB", size, size, 8, 2) + b"\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw))) + _chunk(b"IEND", b"")


def demo_svg(prompt: str) -> str:
    seed = _hash(prompt)
    hue = seed % 360
    safe = "".join(ch for ch in str(prompt) if ch not in '<>&"')[:60]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="hsl({hue},65%,72%)"/><stop offset="1" stop-color="hsl({(hue + 40) % 360},70%,90%)"/></linearGradient></defs>
  <rect width="512" height="512" fill="url(#g)"/>
  <circle cx="{160 + (seed % 200)}" cy="190" r="66" fill="hsl({(hue + 180) % 360},80%,62%)"/>
  <path d="M0 330 Q128 280 256 320 T512 310 V512 H0Z" fill="hsl({(hue + 200) % 360},35%,45%)"/>
  <path d="M0 400 Q160 360 300 390 T512 380 V512 H0Z" fill="hsl({(hue + 220) % 360},30%,32%)"/>
  <text x="256" y="480" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#fff" opacity=".85">{safe}</text>
</svg>"""


def demo_wav(text: str) -> bytes:
    """1.6 s two-note chime, 16-bit mono WAV."""
    rate = 22050
    n = round(rate * 1.6)
    f1 = 440 + (_hash(text) % 6) * 40
    frames = bytearray(n * 2)
    for i in range(n):
        t = i / rate
        f = f1 if t < 0.7 else f1 * 1.5
        env = math.exp(-((t % 0.8) * 4))
        struct.pack_into("<h", frames, i * 2, round(math.sin(2 * math.pi * f * t) * env * 9000))
    header = b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(frames))
    return header + bytes(frames)


async def _fetch_bytes(client: httpx.AsyncClient, url: str, *, method: str = "GET", headers: dict | None = None, body: bytes | None = None) -> dict:
    try:
        res = await client.request(method, url, headers=headers, content=body)
    except httpx.HTTPError as err:
        raise ProviderError(f"Network error: {err}", retryable=True) from err
    if res.status_code >= 400:
        raise ProviderError(
            f"HTTP {res.status_code}: {res.text[:300]}",
            status=res.status_code,
            retryable=res.status_code in (408, 409, 429) or res.status_code >= 500,
            auth=res.status_code in (401, 403),
        )
    return {"bytes": res.content, "type": res.headers.get("content-type", "")}


async def _fetch_json(client: httpx.AsyncClient, url: str, **kwargs):
    out = await _fetch_bytes(client, url, **kwargs)
    return __import__("json").loads(out["bytes"].decode("utf-8"))


class Media:
    def __init__(self, *, config, bus=None, client: httpx.AsyncClient | None = None):
        self.config = config
        self.bus = bus
        self.client = client or httpx.AsyncClient(timeout=TIMEOUT_S, headers={"user-agent": "AgentWorld/0.2"})

    @property
    def cfg(self) -> dict:
        return self.config.get()["media"]

    def ready(self, id: str) -> bool:
        p = self.cfg["providers"].get(id)
        if not p or p.get("enabled") is False:
            return False
        if p.get("kind") == "mock" or p.get("keyless"):
            return True
        import os

        return bool(p.get("keyEnv") and os.environ.get(p["keyEnv"]))

    def targets(self, kind: str) -> list[dict]:
        out = []
        for t in self.cfg.get(kind) or []:
            slash = t.find("/")
            provider, model = t[:slash], t[slash + 1 :]
            if self.ready(provider):
                out.append({"provider": provider, "model": model})
        return out or [{"provider": "mock", "model": "demo", "demo": True}]

    def status(self) -> dict:
        return {
            "image": [f"{t['provider']}/{t['model']}" for t in self.targets("image")],
            "speech": [f"{t['provider']}/{t['model']}" for t in self.targets("speech")],
            "providers": [
                {"id": id, "keyEnv": p.get("keyEnv"), "ready": self.ready(id), "enabled": p.get("enabled") is not False}
                for id, p in self.cfg["providers"].items()
                if id != "mock"
            ],
        }

    async def run(self, kind: str, fn) -> dict:
        import os

        errors = []
        for t in self.targets(kind):
            p = self.cfg["providers"][t["provider"]]
            key = os.environ.get(p["keyEnv"], "") if p.get("keyEnv") else ""
            try:
                out = await fn(t, p, key)
                return {**out, "target": f"{t['provider']}/{t['model']}", "demo": bool(t.get("demo"))}
            except Exception as err:
                errors.append(f"{t['provider']}/{t['model']}: {err}")
        raise Exception("Generation failed:\n" + "\n".join(errors))

    # Returns { bytes, ext, target, demo } -- the caller decides the file name.
    async def image(self, args: dict, client=None) -> dict:
        prompt = str(args.get("prompt") or "")
        size = str(args.get("size") or "1024x1024")
        ext = str(args.get("ext") or "png")

        async def go(t, p, key):
            c = client or self.client
            if p["kind"] == "mock":
                return {"bytes": demo_svg(prompt).encode(), "ext": "svg"} if ext == "svg" else {"bytes": demo_png(prompt), "ext": "png"}
            if p["kind"] == "openai":
                import json

                data = await _fetch_json(
                    c,
                    f"{p['baseUrl']}/images/generations",
                    method="POST",
                    headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
                    body=json.dumps({"model": t["model"], "prompt": prompt, "size": size, "n": 1}).encode(),
                )
                item = (data.get("data") or [{}])[0]
                if item.get("b64_json"):
                    return {"bytes": base64.b64decode(item["b64_json"]), "ext": "png"}
                if item.get("url"):
                    img = await _fetch_bytes(c, item["url"])
                    return {"bytes": img["bytes"], "ext": "png"}
                raise Exception("No image in the answer")
            if p["kind"] == "fal":
                import json

                data = await _fetch_json(
                    c,
                    f"https://fal.run/{t['model']}",
                    method="POST",
                    headers={"content-type": "application/json", "authorization": f"Key {key}"},
                    body=json.dumps({"prompt": prompt, "image_size": "square_hd"}).encode(),
                )
                url = ((data.get("images") or [{}])[0]).get("url")
                if not url:
                    raise Exception("No image in the answer")
                img = await _fetch_bytes(c, url)
                return {"bytes": img["bytes"], "ext": "jpg" if "jpeg" in img["type"] else "png"}
            if p["kind"] == "pollinations":
                from urllib.parse import quote

                w, _, h = size.partition("x")
                img = await _fetch_bytes(c, f"https://image.pollinations.ai/prompt/{quote(prompt)}?width={w}&height={h}&nologo=true&model={quote(t['model'])}")
                return {"bytes": img["bytes"], "ext": "png" if "png" in img["type"] else "jpg"}
            raise Exception(f"Unknown image provider kind {p['kind']}")

        return await self.run("image", go)

    async def speech(self, args: dict, client=None) -> dict:
        text = str(args.get("text") or "")
        voice = args.get("voice")

        async def go(t, p, key):
            import json

            c = client or self.client
            if p["kind"] == "mock":
                return {"bytes": demo_wav(text), "ext": "wav"}
            if p["kind"] == "openai":
                out = await _fetch_bytes(
                    c,
                    f"{p['baseUrl']}/audio/speech",
                    method="POST",
                    headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
                    body=json.dumps({"model": t["model"], "voice": voice or "alloy", "input": text[:4000], "response_format": "mp3"}).encode(),
                )
                return {"bytes": out["bytes"], "ext": "mp3"}
            if p["kind"] == "elevenlabs":
                out = await _fetch_bytes(
                    c,
                    f"https://api.elevenlabs.io/v1/text-to-speech/{p['voiceId']}?output_format=mp3_44100_128",
                    method="POST",
                    headers={"content-type": "application/json", "xi-api-key": key},
                    body=json.dumps({"text": text[:4000], "model_id": t["model"]}).encode(),
                )
                return {"bytes": out["bytes"], "ext": "mp3"}
            raise Exception(f"Unknown speech provider kind {p['kind']}")

        return await self.run("speech", go)
