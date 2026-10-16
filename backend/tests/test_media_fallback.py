"""Spec 08 §5: in a live run a media task always ends with a real file.

A failed run showed why: OpenAI TTS had no credit, ElevenLabs wanted a paid
plan, and the agent wrote a fake 133-byte .mp3 that QA rejected.

- A provider out of credit (402, 429 insufficient_quota) or with a refused
  key (401) is benched for the session, like in the text router.
- Speech, in a live run: the cloud providers, then edge-tts if installed and
  enabled (opt-in: it sends the text to Microsoft), then the system's own
  speech engine (SAPI on Windows, say on macOS, espeak-ng on Linux: offline,
  free, a real voice whose length follows the text), then the demo chime.
- Images, in a live run: the cloud providers, Pollinations only if enabled
  (opt-in: it sends the prompt out), then the local generator.
- The file gets the format it really has: a WAV asked as .mp3 is converted
  with ffmpeg when there is one, otherwise saved as .wav (and the task's
  expected .mp3 counts as delivered). write_file refuses media files: they
  come from generate_image and generate_speech only.
- Demo runs (live=False) are unchanged."""

import io
import json
import sys
import types
import wave

import httpx
import pytest

QUOTA = {"error": {"message": "You exceeded your current quota, please check your plan and billing details.", "code": "insufficient_quota"}}

CFG = {
    "router": {"quotaCooldownMs": 6 * 3600 * 1000, "authCooldownMs": 600000},
    "media": {
        "providers": {
            "mock": {"kind": "mock"},
            "openai": {"kind": "openai", "baseUrl": "http://up/openai/v1", "keyEnv": "M_KEY"},
            "fal": {"kind": "fal", "keyEnv": "M_KEY"},
            "elevenlabs": {"kind": "elevenlabs", "keyEnv": "M_KEY", "voiceId": "v"},
            "pollinations": {"kind": "pollinations", "keyless": True, "enabled": False},
            "edgetts": {"kind": "edgetts", "keyless": True, "enabled": False},
            "system": {"kind": "system", "keyless": True},
        },
        "image": ["openai/gpt-image-1", "fal/fal-ai/flux/schnell", "pollinations/flux"],
        "speech": ["openai/gpt-4o-mini-tts", "elevenlabs/eleven_multilingual_v2", "edgetts/neural", "system/tts"],
    },
}


class FakeConfig:
    def __init__(self, value):
        self.value = json.loads(json.dumps(value))

    def get(self):
        return self.value


def _wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def media(calls, monkeypatch):
    from backend.media import Media

    monkeypatch.setenv("M_KEY", "k")

    def handler(request):
        calls.append(f"{request.url.host}{request.url.path}")
        if "openai" in request.url.path:
            return httpx.Response(429, json=QUOTA)
        if request.url.host == "fal.run":
            return httpx.Response(402, json={"detail": "credit_balance_exhausted"})
        if request.url.host == "api.elevenlabs.io":
            return httpx.Response(401, json={"detail": "paid plan required"})
        return httpx.Response(500)

    m = Media(config=FakeConfig(CFG), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return m


@pytest.fixture
def system_engine(monkeypatch):
    """A system speech engine that answers with a real WAV, its length from the text."""
    from backend import media as media_mod

    spoken = []

    def fake_tts(text, lang=None):
        spoken.append((text, lang))
        return _wav(max(0.5, len(text) / 15))

    monkeypatch.setattr(media_mod, "system_tts_engine", lambda: "fake")
    monkeypatch.setattr(media_mod, "system_tts", fake_tts)
    return spoken


@pytest.mark.asyncio
async def test_speech_falls_back_to_the_system_voice_and_benches_the_dead_providers(media, calls, system_engine):
    out = await media.speech({"text": "Discover our new bakery, open every morning from seven.", "lang": "en"}, live=True)
    assert out["target"] == "system/tts" and out["ext"] == "wav" and out["demo"] is False
    with wave.open(io.BytesIO(out["bytes"])) as w:
        assert w.getnframes() / w.getframerate() > 3  # a real voice, as long as the text
    assert system_engine == [("Discover our new bakery, open every morning from seven.", "en")]
    assert media.benched("openai") == "quota_exhausted" and media.benched("elevenlabs") == "auth"
    calls.clear()
    await media.speech({"text": "Again.", "lang": "en"}, live=True)
    assert calls == []  # the benched providers are not called again


@pytest.mark.asyncio
async def test_with_no_speech_engine_the_chime_is_the_last_resort(media, monkeypatch):
    from backend import media as media_mod

    monkeypatch.setattr(media_mod, "system_tts_engine", lambda: None)
    out = await media.speech({"text": "x"}, live=True)
    assert out["target"] == "mock/demo" and out["demo"] is True


@pytest.mark.asyncio
async def test_edge_tts_only_when_installed_and_enabled(media, monkeypatch, system_engine):
    saved = []

    class Communicate:
        def __init__(self, text, voice):
            saved.append(voice)

        async def stream(self):
            yield {"type": "audio", "data": b"ID3edge-mp3"}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    out = await media.speech({"text": "Ciao", "lang": "it"}, live=True)
    assert out["target"] == "system/tts"  # installed but not enabled: the text stays on this machine
    media.cfg["providers"]["edgetts"]["enabled"] = True
    out = await media.speech({"text": "Ciao", "lang": "it"}, live=True)
    assert out["target"] == "edgetts/neural" and out["ext"] == "mp3" and out["bytes"] == b"ID3edge-mp3"
    assert saved == ["it-IT-ElsaNeural"]


@pytest.mark.asyncio
async def test_images_fall_back_to_the_local_generator_not_to_pollinations(media, calls):
    out = await media.image({"prompt": "a bakery at dawn", "ext": "png"}, live=True)
    assert out["target"] == "mock/demo" and out["bytes"][:8] == b"\x89PNG\r\n\x1a\n"
    assert not any("pollinations" in c for c in calls)  # opt-in: off, so the prompt stays here
    assert media.benched("openai") == "quota_exhausted" and media.benched("fal") == "quota_exhausted"


@pytest.mark.asyncio
async def test_demo_runs_are_unchanged(media, system_engine):
    with pytest.raises(Exception, match="Generation failed"):
        await media.image({"prompt": "x", "ext": "png"})  # live=False: no invented fallback
    assert system_engine == []


def test_the_system_engine_gets_the_text_on_stdin_never_on_the_command_line(monkeypatch, tmp_path):
    from backend import media as media_mod

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        out = next((a for a in cmd if str(a).endswith(".wav")), None) or kw["env"]["AW_TTS_OUT"]
        open(out, "wb").write(_wav(1.0))
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(media_mod.subprocess, "run", fake_run)
    secret = 'Hello"; rm -rf / ; echo "'
    for platform, exe in (("win32", "powershell"), ("darwin", "say"), ("linux", "espeak-ng")):
        monkeypatch.setattr(media_mod.sys, "platform", platform)
        monkeypatch.setattr(media_mod.shutil, "which", lambda name, exe=exe: f"/bin/{name}" if name == exe else None)
        data = media_mod.system_tts(secret, "de")
        assert data[:4] == b"RIFF"
        assert all(secret not in str(a) for a in seen["cmd"]), platform
        assert seen["input"] == secret.encode("utf-8"), platform
    assert "de" in " ".join(seen["cmd"])  # espeak-ng speaks the run's language


# ---------- the run side ----------


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


@pytest.fixture
def run_ctx(tmp_path):
    """The smallest ctx a Run needs to write files and check them."""
    from backend.store import Store

    cfg = {"limits": {"approvePlan": False, "maxParallel": 8, "maxSteps": 4, "maxRevisions": 3, "escalateAfter": 2, "maxWorkstreams": 8, "maxSubtasks": 5, "askUserTimeoutMs": 300000, "commandTimeoutMs": 60000}, "pacing": {}, "router": {}, "combos": {}, "teams": {}}
    return types.SimpleNamespace(config=types.SimpleNamespace(get=lambda: cfg), bus=_Bus(), store=Store(tmp_path / "data"), router=types.SimpleNamespace(mode=lambda: "demo"), skills=None, brain=None, workspace_root=str(tmp_path / "workspace"))


@pytest.mark.asyncio
async def test_a_wav_asked_as_mp3_is_converted_or_saved_as_wav(tmp_path, monkeypatch):
    from backend import run as run_mod

    class Ctx:
        pass

    run = types.SimpleNamespace()
    run.data = {"id": "r", "mode": "live", "language": "en"}
    from backend.tools import Workspace

    run.ws = Workspace(tmp_path)
    await run.ws.ensure()
    emitted = []
    run.ctx = types.SimpleNamespace(bus=types.SimpleNamespace(emit=lambda *a: emitted.append(a)), media=types.SimpleNamespace())
    run.remember_event = lambda *a, **k: None
    run.lang = "en"

    async def speech(args, live=False):
        assert live is True and args["lang"] == "en"
        return {"bytes": _wav(2.0), "ext": "wav", "target": "system/tts", "demo": False}

    run.ctx.media.speech = speech
    task, agent = {"id": "w5.1", "title": "Voice", "wsId": "w5", "team": "genai", "outputs": ["audio/voiceover.mp3"]}, {"id": "dario", "name": "Dario"}

    monkeypatch.setattr(run_mod, "to_audio", lambda data, ext: b"ID3converted" if ext == "mp3" else None)
    msg = await run_mod.Run.write_media(run, task, agent, "speech", {"text": "hi", "path": "audio/voiceover.mp3"})
    assert (tmp_path / "audio" / "voiceover.mp3").read_bytes() == b"ID3converted"
    assert "audio/voiceover.mp3" in msg

    monkeypatch.setattr(run_mod, "to_audio", lambda data, ext: None)  # no ffmpeg
    msg = await run_mod.Run.write_media(run, task, agent, "speech", {"text": "hi", "path": "audio/other.mp3"})
    assert (tmp_path / "audio" / "other.wav").read_bytes()[:4] == b"RIFF"
    assert not (tmp_path / "audio" / "other.mp3").exists()
    assert "saved as audio/other.wav" in msg


@pytest.mark.asyncio
async def test_an_expected_mp3_delivered_as_wav_counts(run_ctx):
    from backend.run import Run

    run = Run(goal="g", ctx=run_ctx)
    await run.ws.write_bytes("audio/voiceover.wav", _wav(1.0))
    assert await run.missing_outputs({"outputs": ["audio/voiceover.mp3", "audio/missing.mp3"]}) == ["audio/missing.mp3"]


@pytest.mark.asyncio
async def test_write_file_refuses_media_files(run_ctx):
    from backend.run import Run

    run = Run(goal="g", ctx=run_ctx)
    out = await run.exec_tool({"id": "w5.1", "wsId": "w5", "team": "genai", "title": "Voice"}, {"id": "dario", "name": "Dario"}, {"tool": "write_file", "args": {"path": "audio/spot.mp3", "content": "ID3 fake mp3"}})
    assert out.startswith("ERROR") and "generate_speech" in out
    assert await run.ws.size("audio/spot.mp3") == -1


@pytest.mark.asyncio
async def test_qa_sees_the_length_of_an_audio_file(run_ctx):
    from backend.run import Run

    run = Run(goal="g", ctx=run_ctx)
    await run.ws.write_bytes("audio/voiceover.wav", _wav(2.5))
    dump = await run.file_dump({"outputs": ["audio/voiceover.wav"], "files": []})
    assert "2.5 s" in dump


# ---------- embeddings ----------


@pytest.mark.asyncio
async def test_embeddings_move_on_when_the_credit_is_gone(tmp_path, monkeypatch):
    from backend.embed import Embedder
    from backend.router.index import Router

    monkeypatch.setenv("M_KEY", "k")
    asked = []

    def handler(request):
        asked.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path.startswith("/oa"):
            return httpx.Response(429, json=QUOTA)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 0.0, 0.5]} for i, _ in enumerate(body["input"])]})

    value = {
        "router": {"quotaCooldownMs": 6 * 3600 * 1000, "authCooldownMs": 1, "cooldownBaseMs": 1, "cooldownMaxMs": 1},
        "providers": {"openai": {"kind": "openai", "baseUrl": "http://up/oa/v1", "keyEnv": "M_KEY"}, "gemini": {"kind": "openai", "baseUrl": "http://up/ge/v1", "keyEnv": "M_KEY"}},
        "combos": {},
        "rag": {"embeddings": ["openai/text-embedding-3-small", "gemini/gemini-embedding-001", "local/ngram"]},
    }
    cfg = FakeConfig(value)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    router = Router(cfg, tmp_path, client=client)
    emb = Embedder(cfg, router=router, client=client)
    model, vectors = await emb.embed(["a", "b"])
    assert model == "gemini/gemini-embedding-001" and len(vectors) == 2
    assert router.provider_cooldown("openai")["reason"] == "quota_exhausted"
    asked.clear()
    await emb.embed(["c"])
    assert not any(p.startswith("/oa") for p in asked)  # the benched provider is skipped
    assert emb.candidates()[0] == "gemini/gemini-embedding-001"


def test_the_embedding_order_follows_the_spec():
    from pathlib import Path

    cfg = json.loads((Path(__file__).resolve().parents[2] / "config" / "default.json").read_text(encoding="utf-8"))
    assert cfg["rag"]["embeddings"] == ["openai/text-embedding-3-small", "gemini/gemini-embedding-001", "mistral/mistral-embed", "ollama/nomic-embed-text"]
    speech = cfg["media"]["speech"]
    assert speech[-2:] == ["edgetts/neural", "system/tts"]
    assert cfg["media"]["providers"]["edgetts"]["enabled"] is False and cfg["media"]["providers"]["pollinations"]["enabled"] is False


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="no ffmpeg on this machine")
def test_a_real_conversion_keeps_the_length(tmp_path):
    from backend.media import demo_wav, media_info, to_audio

    mp3 = to_audio(demo_wav("ciao"), "mp3")
    assert mp3 and (mp3[:3] == b"ID3" or (mp3[0] == 0xFF and mp3[1] & 0xE0 == 0xE0))
    f = tmp_path / "x.mp3"
    f.write_bytes(mp3)
    seconds = float(media_info(f).split("about ")[1].split(" s")[0])
    assert 1.2 <= seconds <= 2.2  # the demo chime lasts 1.6 s
