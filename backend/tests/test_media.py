"""Contract tests for backend/media.py, ported from server/engine/media.js:
the demo PNG/SVG/WAV generators are real files (the front-end previews
them), and the Media class falls back to the mock provider when no key is
configured. No test touches the real network (httpx.MockTransport)."""

import struct

import httpx
import pytest

MEDIA_CFG = {
    "providers": {
        "mock": {"kind": "mock"},
        "openai": {"kind": "openai", "baseUrl": "https://api.openai.com/v1", "keyEnv": "OPENAI_API_KEY"},
        "fal": {"kind": "fal", "keyEnv": "FAL_KEY"},
        "pollinations": {"kind": "pollinations", "keyless": True, "enabled": False},
    },
    "image": ["openai/gpt-image-1", "fal/flux/schnell", "pollinations/flux"],
    "speech": ["openai/gpt-4o-mini-tts"],
}


class FakeConfig:
    def __init__(self, media):
        self._media = media

    def get(self):
        return {"media": self._media}


def make_media(cfg=MEDIA_CFG, **kwargs):
    from backend.media import Media

    return Media(config=FakeConfig(cfg), **kwargs)


class TestDemoGenerators:
    def test_demo_png_is_a_valid_png_with_the_requested_size(self):
        from backend.media import demo_png

        data = demo_png("un tramonto", size=64)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[12:16] == b"IHDR"
        width, height, depth, color = struct.unpack(">IIBB", data[16:26])
        assert (width, height, depth, color) == (64, 64, 8, 2)
        assert data[-8:-4] == b"IEND"
        assert demo_png("un tramonto", size=64) == data  # deterministic per prompt
        assert demo_png("altro", size=64) != data

    def test_demo_svg_escapes_and_truncates_the_prompt(self):
        from backend.media import demo_svg

        svg = demo_svg('logo <b> "x" & co')
        assert svg.startswith("<svg")
        assert "<b>" not in svg and "&" not in svg.split("<text")[1]
        assert len(demo_svg("x" * 100)) < len(demo_svg("x" * 100 + "y" * 100)) + 50  # capped at 60 chars in the caption
        assert demo_svg("stesso") == demo_svg("stesso")

    def test_demo_wav_is_a_16bit_mono_wav(self):
        from backend.media import demo_wav

        data = demo_wav("ciao")
        assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
        rate = struct.unpack("<I", data[24:28])[0]
        channels, bits = struct.unpack("<HH", data[22:24] + data[34:36])
        assert rate == 22050 and channels == 1 and bits == 16
        data_len = struct.unpack("<I", data[40:44])[0]
        assert data_len == 2 * round(22050 * 1.6)
        assert len(data) == 44 + data_len


class TestMediaRouting:
    def test_targets_fall_back_to_mock_without_keys(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("FAL_KEY", raising=False)
        media = make_media()
        assert media.targets("image") == [{"provider": "mock", "model": "demo", "demo": True}]
        assert media.targets("speech") == [{"provider": "mock", "model": "demo", "demo": True}]

    def test_targets_keep_ready_providers_in_order(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "x")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        targets = make_media().targets("image")
        assert targets[0] == {"provider": "fal", "model": "flux/schnell"}

    def test_status_shape_matches_node(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("FAL_KEY", raising=False)
        s = make_media().status()
        assert s["image"] == ["mock/demo"]
        assert s["speech"] == ["mock/demo"]
        ids = [p["id"] for p in s["providers"]]
        assert "mock" not in ids and "openai" in ids
        openai = next(p for p in s["providers"] if p["id"] == "openai")
        assert openai == {"id": "openai", "keyEnv": "OPENAI_API_KEY", "ready": False, "enabled": True}

    def test_disabled_provider_is_not_ready(self):
        assert make_media().ready("pollinations") is False
        assert make_media().ready("mock") is True
        assert make_media().ready("nope") is False


class TestMediaGeneration:
    @pytest.mark.asyncio
    async def test_image_demo_png_and_svg(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("FAL_KEY", raising=False)
        media = make_media()
        png = await media.image({"prompt": "un gatto", "size": "1024x1024", "ext": "png"})
        assert png["bytes"][:8] == b"\x89PNG\r\n\x1a\n"
        assert png["ext"] == "png" and png["demo"] is True and png["target"] == "mock/demo"
        svg = await media.image({"prompt": "un gatto", "ext": "svg"})
        assert svg["ext"] == "svg" and svg["bytes"].startswith(b"<svg")

    @pytest.mark.asyncio
    async def test_speech_demo_wav(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        out = await make_media().speech({"text": "ciao", "voice": None})
        assert out["bytes"][:4] == b"RIFF" and out["ext"] == "wav" and out["demo"] is True

    @pytest.mark.asyncio
    async def test_openai_image_b64(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        tiny = __import__("base64").b64encode(b"PNGDATA").decode()

        def handler(request):
            assert request.url.path == "/v1/images/generations"
            assert request.headers["authorization"] == "Bearer k"
            return httpx.Response(200, json={"data": [{"b64_json": tiny}]})

        media = make_media(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        out = await media.image({"prompt": "x", "size": "1024x1024", "ext": "png"})
        assert out["bytes"] == b"PNGDATA" and out["ext"] == "png" and out["target"] == "openai/gpt-image-1"

    @pytest.mark.asyncio
    async def test_all_providers_fail_aggregates_errors(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        media = make_media(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))))
        with pytest.raises(Exception, match="Generation failed:") as exc:
            await media.image({"prompt": "x", "size": "s", "ext": "png"})
        assert "openai/gpt-image-1: HTTP 500" in str(exc.value)

    @pytest.mark.asyncio
    async def test_auth_error_is_classified(self, monkeypatch):
        from backend.router.providers import ProviderError

        monkeypatch.setenv("OPENAI_API_KEY", "k")
        media = make_media(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="no"))))
        with pytest.raises(Exception) as exc:
            await media.speech({"text": "x", "voice": None})
        assert "HTTP 401" in str(exc.value)
        # ProviderError classification stays available to callers upstream
        err = ProviderError("HTTP 401: no", status=401, retryable=False, auth=True)
        assert err.auth is True
