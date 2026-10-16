"""Mirrors server/engine/media.js: generative media for the AI team, with
the same fallback idea as the text router. With no key, the demo provider
draws a real PNG (or SVG) and a short WAV, so files and previews always
exist. The drawing algorithm is ported line by line, so demo art looks the
same on both backends (the PNG bytes may differ: Node's deflateSync and
Python's zlib.compress pick different zlib streams for identical pixels)."""

import base64
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
import zlib
from pathlib import Path

import httpx

from backend.router.providers import ProviderError, _classify

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
        # spec 08: the same reading of the error as the text router (quota, auth, model...)
        raise _classify(res.status_code, res.text)
    return {"bytes": res.content, "type": res.headers.get("content-type", "")}


async def _fetch_json(client: httpx.AsyncClient, url: str, **kwargs):
    out = await _fetch_bytes(client, url, **kwargs)
    return __import__("json").loads(out["bytes"].decode("utf-8"))


# ---------- spec 08: the system's own speech engine, and audio formats ----------

CULTURES = {"en": "en-US", "it": "it-IT", "es": "es-ES", "fr": "fr-FR", "de": "de-DE"}
EDGE_VOICES = {"en": "en-US-AriaNeural", "it": "it-IT-ElsaNeural", "es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural", "de": "de-DE-KatjaNeural"}
SAPI_SCRIPT = (
    "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
    "Add-Type -AssemblyName System.Speech; "
    "$text = [Console]::In.ReadToEnd(); "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "try { $s.SelectVoiceByHints('NotSet', 'NotSet', 0, [System.Globalization.CultureInfo]$env:AW_TTS_CULTURE) } catch {}; "
    "$s.SetOutputToWaveFile($env:AW_TTS_OUT); $s.Speak($text); $s.Dispose()"
)
# used only in live runs, after every provider of the list. edge-tts needs no
# activation there (a live run already sends its prompts out): it ships with the
# backend (pyproject.toml) and speaks unless media.providers.edgetts.enabled is false.
FALLBACK_KINDS = {"edgetts", "system"}
AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a")
QUOTA_COOLDOWN_MS = 6 * 3600 * 1000


def system_tts_engine() -> str | None:
    """The speech engine of this system: SAPI (Windows), say (macOS), espeak-ng or espeak (Linux)."""
    if sys.platform == "win32":
        return "sapi" if (shutil.which("powershell") or shutil.which("pwsh")) else None
    if sys.platform == "darwin":
        return "say" if shutil.which("say") else None
    return next((exe for exe in ("espeak-ng", "espeak") if shutil.which(exe)), None)


def system_tts(text: str, lang: str | None = None) -> bytes:
    """A real voice, offline and free: WAV bytes, as long as the text. The text
    goes on stdin, never on the command line."""
    engine = system_tts_engine()
    if engine is None:
        raise RuntimeError("no speech engine on this system")
    data = str(text)[:4000].encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="aw-tts-") as d:
        out = os.path.join(d, "speech.wav")
        env = dict(os.environ)
        if engine == "sapi":
            cmd = [shutil.which("powershell") or shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", SAPI_SCRIPT]
            env.update(AW_TTS_OUT=out, AW_TTS_CULTURE=CULTURES.get(lang or "", "en-US"))
        elif engine == "say":
            cmd = [shutil.which("say"), "--file-format=WAVE", "--data-format=LEI16@22050", "-o", out, "-f", "-"]
        else:
            cmd = [shutil.which(engine), "-v", (lang or "en"), "-w", out, "--stdin"]
        r = subprocess.run(cmd, input=data, capture_output=True, timeout=120, env=env)
        if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) <= 44:
            raise RuntimeError(f"{engine} failed: {(r.stderr or b'').decode('utf-8', 'replace')[:200]}")
        with open(out, "rb") as f:
            return f.read()


def to_audio(data: bytes, ext: str) -> bytes | None:
    """The same sound in another format (WAV -> MP3 or OGG) with ffmpeg, or None
    when there is no ffmpeg or it fails: the caller then keeps the real format."""
    ffmpeg = shutil.which("ffmpeg")
    fmt = {"mp3": ["-f", "mp3"], "ogg": ["-f", "ogg"], "m4a": ["-f", "ipod"], "wav": ["-f", "wav"]}.get(ext.lower().lstrip("."))
    if not ffmpeg or not fmt:
        return None
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *fmt, "pipe:1"], input=data, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout else None


# Layer III bitrates (kbps) by MPEG version: MPEG-1, then MPEG-2 and 2.5 (22 kHz and below)
MP3_BITRATES = {
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}


def media_info(path) -> str:
    """What QA can know of a generated file without hearing or seeing it: the
    length of an audio file, the size of an image."""
    try:
        head = Path(path).read_bytes()[:4096]
        size = Path(path).stat().st_size
        if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
            with wave.open(str(path)) as w:
                return f"audio WAV, {w.getnframes() / w.getframerate():.1f} s"
        start = 0
        if head[:3] == b"ID3":
            start = 10 + ((head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14 | (head[8] & 0x7F) << 7 | (head[9] & 0x7F))
            head = Path(path).read_bytes()[start : start + 4]
        if len(head) >= 4 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:
            version = 1 if (head[1] >> 3) & 0b11 == 0b11 else 2
            kbps = MP3_BITRATES[version][head[2] >> 4]
            if kbps:
                return f"audio MP3, about {(size - start) * 8 / (kbps * 1000):.1f} s"
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return f"image PNG {w}x{h}"
    except (OSError, wave.Error, struct.error, IndexError, EOFError):
        pass
    return ""


class Media:
    def __init__(self, *, config, bus=None, client: httpx.AsyncClient | None = None):
        self.config = config
        self.bus = bus
        self.client = client or httpx.AsyncClient(timeout=TIMEOUT_S, headers={"user-agent": "AgentWorld/0.2"})
        self.bench: dict[str, dict] = {}  # spec 08: provider id -> {until, reason}: credit gone, key refused

    @property
    def cfg(self) -> dict:
        return self.config.get()["media"]

    def ready(self, id: str) -> bool:
        p = self.cfg["providers"].get(id)
        if not p or p.get("enabled") is False:
            return False
        if p.get("kind") == "edgetts":
            try:
                import edge_tts  # noqa: F401 -- a dependency; missing only in an environment built without it
            except ImportError:
                return False
            return True
        if p.get("kind") == "system":
            return system_tts_engine() is not None
        if p.get("kind") == "mock" or p.get("keyless"):
            return True
        return bool(p.get("keyEnv") and os.environ.get(p["keyEnv"]))

    def benched(self, id: str) -> str | None:
        b = self.bench.get(id)
        return b["reason"] if b and b["until"] > time.time() * 1000 else None

    def _bench(self, id: str, err: Exception) -> None:
        kind = getattr(err, "kind", None)
        if kind not in ("quota", "auth"):
            return
        router = (self.config.get() or {}).get("router") or {}
        wait = router.get("quotaCooldownMs", QUOTA_COOLDOWN_MS) if kind == "quota" else router.get("authCooldownMs", 600000)
        self.bench[id] = {"until": time.time() * 1000 + wait, "reason": "quota_exhausted" if kind == "quota" else "auth"}

    def _listed(self, kind: str) -> list[dict]:
        out = []
        for t in self.cfg.get(kind) or []:
            slash = t.find("/")
            provider, model = t[:slash], t[slash + 1 :]
            if self.ready(provider):
                out.append({"provider": provider, "model": model})
        return out

    def targets(self, kind: str) -> list[dict]:
        """The providers of a demo run (and of the status): the ready ones of the
        list, or the demo generator. The fallbacks of a live run are in chain()."""
        out = [t for t in self._listed(kind) if self.cfg["providers"][t["provider"]].get("kind") not in FALLBACK_KINDS]
        return out or [{"provider": "mock", "model": "demo", "demo": True}]

    def chain(self, kind: str, live: bool) -> list[dict]:
        """Spec 08: a live run always ends with a real file. The ready providers
        not benched, then the fallbacks (edge-tts's natural voice,
        the system voice), then the local generator."""
        if not live:
            return self.targets(kind)
        listed = [t for t in self._listed(kind) if not self.benched(t["provider"])]
        first = [t for t in listed if self.cfg["providers"][t["provider"]].get("kind") not in FALLBACK_KINDS]
        last = [t for t in listed if self.cfg["providers"][t["provider"]].get("kind") in FALLBACK_KINDS]
        return [*first, *last, {"provider": "mock", "model": "demo", "demo": True}]

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

    async def run(self, kind: str, fn, *, live: bool = False) -> dict:
        errors = []
        for t in self.chain(kind, live):
            if self.benched(t["provider"]):
                continue
            p = self.cfg["providers"][t["provider"]]
            key = os.environ.get(p["keyEnv"], "") if p.get("keyEnv") else ""
            try:
                out = await fn(t, p, key)
                return {**out, "target": f"{t['provider']}/{t['model']}", "demo": bool(t.get("demo"))}
            except Exception as err:
                self._bench(t["provider"], err)
                errors.append(f"{t['provider']}/{t['model']}: {err}")
        raise Exception("Generation failed:\n" + "\n".join(errors))

    # Returns { bytes, ext, target, demo } -- the caller decides the file name.
    async def image(self, args: dict, client=None, *, live: bool = False) -> dict:
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

        return await self.run("image", go, live=live)

    async def speech(self, args: dict, client=None, *, live: bool = False) -> dict:
        import asyncio

        text = str(args.get("text") or "")
        voice = args.get("voice")
        lang = args.get("lang")

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
            if p["kind"] == "edgetts":
                import edge_tts

                audio = bytearray()
                async for chunk in edge_tts.Communicate(text[:4000], EDGE_VOICES.get(lang or "", EDGE_VOICES["en"])).stream():
                    if chunk.get("type") == "audio":
                        audio += chunk["data"]
                if not audio:
                    raise Exception("edge-tts returned no audio")
                return {"bytes": bytes(audio), "ext": "mp3"}
            if p["kind"] == "system":
                return {"bytes": await asyncio.to_thread(system_tts, text, lang), "ext": "wav"}
            raise Exception(f"Unknown speech provider kind {p['kind']}")

        return await self.run("speech", go, live=live)
