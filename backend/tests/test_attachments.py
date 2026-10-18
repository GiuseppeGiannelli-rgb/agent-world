"""Spec 09 §3: the owner's own files (photos, logo, PDF, texts, audio).

attachments.py checks a file before it reaches a run: the extension is on
the list of the spec, the bytes are what the extension says (a renamed .exe
is not a .png), the name is a plain file name (no folders, drives or
streams), the size is under limits.maxUploadMB. Then it reads what an agent
needs: the size and shape of an image, the text of a PDF, DOCX, CSV or web
file. A PDF is read up to MAX_PDF_PAGES, a DOCX without trusting its zip
(the document is read up to a fixed size, never inflated whole)."""

import io
import struct
import wave
import zipfile
import zlib

import pytest

from backend import attachments as A

# ---------- sample files, built by hand ----------


def png(w=1600, h=900) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\xc0\x39\x2b" * w for _ in range(2))  # two rows are enough for the header test
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg(w=1200, h=800) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def gif(w=320, h=240) -> bytes:
    return b"GIF89a" + struct.pack("<HH", w, h) + b"\x00\x00\x00;"


def webp(w=800, h=600) -> bytes:
    vp8x = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(vp8x)) + b"WEBP" + vp8x


SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="150" viewBox="0 0 300 150"><rect width="300" height="150" fill="#c0392b"/><circle cx="50" cy="50" r="20" fill="#F1C40F"/></svg>'


def pdf(lines=("Menu della pizzeria", "Margherita 7 euro", "Diavola 9 euro"), pages=1) -> bytes:
    objs = []
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(pages))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    font_id = 3 + pages * 2
    for i in range(pages):
        text = " ".join(f"({line}) Tj 0 -20 Td" for line in lines).encode()
        stream = b"BT /F1 14 Tf 72 720 Td " + text + b" ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + i * 2} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def docx(paragraphs=("Ciao mondo", "La pizzeria apre alle 19")) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def wav(seconds=1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buf.getvalue()


MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x64" + b"\x00" * 400

# ---------- what may come in ----------


@pytest.mark.parametrize(
    "name,kind",
    [("hero.png", "image"), ("Foto.JPG", "image"), ("a.jpeg", "image"), ("b.webp", "image"), ("logo.svg", "image"), ("c.gif", "image"),
     ("menu.pdf", "document"), ("testi.docx", "document"), ("note.txt", "document"), ("x.md", "document"), ("prezzi.csv", "document"),
     ("d.json", "document"), ("e.html", "document"), ("f.css", "document"), ("g.js", "document"),
     ("voce.mp3", "audio"), ("v.wav", "audio"), ("v.ogg", "audio")],
)
def test_the_kinds_of_the_spec(name, kind):
    assert A.kind_of(name) == kind


@pytest.mark.parametrize("name", ["setup.exe", "run.sh", "x.py", "archive.zip", "doc.doc", "noext", "movie.mp4", ".png"])
def test_anything_else_is_refused(name):
    assert A.kind_of(name) is None
    with pytest.raises(A.AttachmentError):
        A.check(name, b"x", max_mb=25)


@pytest.mark.parametrize(
    "raw,safe",
    [
        ("../../etc/passwd.png", "passwd.png"),
        ("D:\\Foto\\2026\\Foto Pizza.JPG", "foto-pizza.jpg"),
        ("con:secret.png", "con-secret.png"),
        ("évènement été.webp", "evenement-ete.webp"),
        ("!!!.png", "file.png"),
        ("a" * 200 + ".pdf", "a" * 60 + ".pdf"),
    ],
)
def test_names_become_plain_file_names(raw, safe):
    assert A.safe_name(raw) == safe


def _short_id(v):
    """The file name, and the bytes by their size: pytest puts the test id in
    PYTEST_CURRENT_TEST, and a WAV written out byte by byte is over the 32767
    characters a Windows environment variable can hold."""
    return v if isinstance(v, str) else f"{len(v)}B"


@pytest.mark.parametrize(
    "name,data",
    [("photo.png", b"MZ\x90\x00 not an image"), ("photo.jpg", png()), ("menu.pdf", b"hello"), ("t.docx", b"PK\x03\x04 not a docx"),
     ("v.mp3", b"just text"), ("v.wav", b"RIFF\x00\x00\x00\x00AVI "), ("notes.txt", b"bin\x00ary"), ("logo.svg", b"<html>no svg</html>")],
    ids=_short_id,
)
def test_the_bytes_must_be_what_the_name_says(name, data):
    with pytest.raises(A.AttachmentError):
        A.check(name, data, max_mb=25)


@pytest.mark.parametrize(
    "name,data",
    [("hero.png", png()), ("f.jpg", jpeg()), ("g.gif", gif()), ("w.webp", webp()), ("logo.svg", SVG), ("menu.pdf", pdf()), ("t.docx", docx()),
     ("p.csv", b"piatto,prezzo\nMargherita,7\n"), ("v.wav", wav()), ("v.mp3", MP3), ("x.html", b"<!doctype html><p>ciao</p>"), ("n.md", "# Menù\n".encode())],
    ids=_short_id,
)
def test_real_files_pass(name, data):
    assert A.check(name, data, max_mb=25) in ("image", "document", "audio")


def test_the_size_limit():
    with pytest.raises(A.AttachmentError, match="25 MB"):
        A.check("big.png", png(), max_mb=25, size=26 * 1024 * 1024)
    assert A.check("ok.png", png(), max_mb=25, size=1024)


# ---------- what an agent learns from a file ----------


@pytest.mark.parametrize(
    "name,data,w,h,orientation",
    [("a.png", png(1600, 900), 1600, 900, "landscape"), ("b.jpg", jpeg(800, 1200), 800, 1200, "portrait"), ("c.gif", gif(320, 320), 320, 320, "square"),
     ("d.webp", webp(800, 600), 800, 600, "landscape"), ("e.svg", SVG, 300, 150, "landscape")],
)
def test_image_size_and_shape(name, data, w, h, orientation):
    info = A.image_info(data, name)
    assert (info["width"], info["height"], info["orientation"]) == (w, h, orientation)
    assert info["format"] == name.rsplit(".", 1)[1].replace("jpg", "jpeg")


def test_svg_colours_are_read():
    assert A.image_info(SVG, "logo.svg")["colors"] == ["#c0392b", "#f1c40f"]


def test_pdf_text():
    text = A.extract_text(pdf(), "menu.pdf")
    assert "Margherita 7 euro" in text and "Diavola" in text


def test_a_long_pdf_is_read_only_up_to_the_page_limit(monkeypatch):
    monkeypatch.setattr(A, "MAX_PDF_PAGES", 2)
    text = A.extract_text(pdf(lines=("pagina",), pages=5), "lungo.pdf")
    assert text.count("pagina") == 2


def test_docx_text_keeps_paragraphs():
    assert A.extract_text(docx(), "t.docx").splitlines() == ["Ciao mondo", "La pizzeria apre alle 19"]


def test_a_docx_bomb_is_read_only_up_to_a_fixed_size(monkeypatch):
    monkeypatch.setattr(A, "MAX_XML_BYTES", 4000)
    huge = docx(paragraphs=["x" * 100] * 2000)  # ~240 KB of XML, deflated to almost nothing
    text = A.extract_text(huge, "bomb.docx")
    assert 0 < len(text) < 4000


@pytest.mark.parametrize(
    "name,data,expect,absent",
    [("p.csv", b"piatto,prezzo\nMargherita,7\n", "Margherita,7", None),
     ("x.html", b"<html><style>p{color:red}</style><body><h1>Pizzeria</h1><script>alert(1)</script><p>Da Mario</p></body></html>", "Pizzeria", "alert"),
     ("d.json", b'{"orari": "19-23"}', '"orari": "19-23"', None),
     ("n.txt", "caffè\n".encode("utf-8"), "caffè", None)],
)
def test_text_files(name, data, expect, absent):
    text = A.extract_text(data, name)
    assert expect in text
    if absent:
        assert absent not in text


def test_images_and_audio_have_no_text():
    assert A.extract_text(png(), "a.png") == ""
    assert A.extract_text(wav(), "v.wav") == ""


def test_chunks_for_the_run_memory():
    text = "\n\n".join(f"Paragrafo {i}: " + "parola " * 60 for i in range(30))
    chunks = A.chunks(text, max_chars=600)
    assert all(len(c) <= 600 for c in chunks)
    assert len(chunks) <= A.MAX_CHUNKS
    assert chunks[0].startswith("Paragrafo 0")


# ---------- a run takes the owner's files ----------

import asyncio  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from backend.brain import Brain
    from backend.bus import Bus
    from backend.config import Config
    from backend.media import Media
    from backend.router.index import Router
    from backend.store import Store
    from backend.team import Team

    monkeypatch.setenv("AGENT_WORLD_FAST", "1")
    default = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    for section in (default["providers"], default["media"]["providers"]):
        for p in section.values():
            for k in ("keyEnv", "baseUrlEnv"):
                if p.get(k):
                    monkeypatch.delenv(p[k], raising=False)
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "default.json", tmp_path / "config" / "default.json")
    config = Config(tmp_path / "config")
    cfg = config.get()
    cfg["router"]["logCalls"] = False
    cfg["providers"]["mock"]["latencyMs"] = [1, 3]
    bus = Bus()
    events = []
    bus.emit = lambda t, p=None, _e=bus.emit: (events.append((t, p)), _e(t, p))[1]
    team = Team(bus)
    team.load(cfg["staff"])
    skills = types.SimpleNamespace(skills=[], search=lambda *a, **k: [], summary=lambda: {"count": 0, "sources": []})
    return types.SimpleNamespace(
        config=config, bus=bus, store=Store(tmp_path / "data"), router=Router(config, tmp_path / "data", bus), team=team,
        brain=Brain(tmp_path / "data" / "brain.json", bus), skills=skills, media=Media(config=config, bus=bus),
        workspace_root=str(tmp_path / "workspace"), events=events,
    )


@pytest.mark.asyncio
async def test_a_run_saves_the_owner_files_in_its_folder(ctx):
    from backend.run import Run

    run = Run(goal="Il sito della pizzeria", ctx=ctx)
    a = await run.add_attachment("Foto Hero.JPG", jpeg(1600, 900), note="per la hero")
    b = await run.add_attachment("foto hero.jpg", jpeg(800, 800))
    assert a["path"] == "attachments/foto-hero.jpg" and b["path"] == "attachments/foto-hero-2.jpg"
    assert a["kind"] == "image" and a["name"] == "Foto Hero.JPG" and a["note"] == "per la hero"
    assert a["info"]["width"] == 1600 and a["info"]["orientation"] == "landscape"
    assert (Path(run.data["workspace"]) / a["path"]).read_bytes()[:3] == b"\xff\xd8\xff"
    assert [x["id"] for x in run.data["attachments"]] == [a["id"], b["id"]]
    assert ("attachment", {"runId": run.data["id"], "attachment": a}) in ctx.events


@pytest.mark.asyncio
async def test_a_document_is_indexed_for_every_agent_and_in_the_brain(ctx):
    from backend.run import Run

    run = Run(goal="Il sito della pizzeria", ctx=ctx)
    rec = await run.add_attachment("menu.pdf", pdf())
    assert "Margherita" in rec["excerpt"]
    hits = run.memory.search("prezzo della margherita", 3, kinds=("document",))
    assert hits and hits[0]["path"] == "attachments/menu.pdf" and "Margherita 7 euro" in hits[0]["text"]
    notes = [n for n in ctx.brain.list(50) if n["kind"] == "document"]
    assert notes and "Margherita" in notes[0]["text"] and notes[0]["runId"] == run.data["id"]


@pytest.mark.asyncio
async def test_a_run_takes_at_most_max_attachments(ctx):
    from backend.attachments import AttachmentError
    from backend.run import Run

    ctx.config.get()["limits"]["maxAttachments"] = 2
    run = Run(goal="Il sito della pizzeria", ctx=ctx)
    await run.add_attachment("a.png", png())
    await run.add_attachment("b.png", png())
    with pytest.raises(AttachmentError):
        await run.add_attachment("c.png", png())


# ---------- over HTTP ----------


@pytest.fixture
def app(ctx, tmp_path, monkeypatch):
    from backend.app import create_app

    monkeypatch.setenv("AGENT_WORLD_HOME", str(tmp_path / "home"))
    return create_app(config=ctx.config, store=ctx.store, bus=ctx.bus, router=ctx.router, team=ctx.team, brain=ctx.brain, media=ctx.media, skills=types.SimpleNamespace(skills=[], search=lambda *a, **k: [], summary=lambda: {"count": 0, "sources": []}, extra_sources=[]))


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


async def _until_idle(app, timeout=60):
    for _ in range(int(timeout * 20)):
        if not app.state.live:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the run did not finish")


@pytest.mark.asyncio
async def test_uploads_are_checked(app):
    async with client(app) as c:
        ok = await c.post("/api/uploads", params={"name": "../../Foto Hero.png"}, content=png())
        assert ok.status_code == 201
        body = ok.json()
        assert body["name"] == "Foto Hero.png" and body["kind"] == "image" and len(body["id"]) == 12
        assert (await c.post("/api/uploads", params={"name": "virus.exe"}, content=b"MZ")).status_code == 400
        assert (await c.post("/api/uploads", params={"name": "fake.png"}, content=b"MZ\x90")).status_code == 400
        assert (await c.post("/api/uploads", params={"name": "empty.png"}, content=b"")).status_code == 400
        assert (await c.post("/api/uploads", content=png())).status_code == 400  # no name


@pytest.mark.asyncio
async def test_an_upload_too_big_is_refused_while_it_arrives(app, ctx):
    ctx.config.get()["limits"]["maxUploadMB"] = 0.001  # ~1 KB
    async with client(app) as c:
        res = await c.post("/api/uploads", params={"name": "big.png"}, content=png(1600, 900) + b"\x00" * 4096)
        assert res.status_code == 413


@pytest.mark.asyncio
async def test_a_mission_starts_with_the_files_of_the_composer(app, ctx):
    async with client(app) as c:
        up = (await c.post("/api/uploads", params={"name": "logo.svg"}, content=SVG)).json()
        doc = (await c.post("/api/uploads", params={"name": "menu.pdf"}, content=pdf())).json()
        res = await c.post("/api/runs", json={"goal": "Il sito della pizzeria", "attachments": [up["id"], doc["id"]]})
        assert res.status_code == 201
        run = app.state.live[res.json()["id"]]
        assert [a["path"] for a in run.data["attachments"]] == ["attachments/logo.svg", "attachments/menu.pdf"]
        assert (await c.post("/api/runs", json={"goal": "Un altro sito", "attachments": ["nope"]})).status_code in (400, 409)
        await _until_idle(app)
    # a used upload leaves the staging folder
    assert not any((Path(app.state.uploads_dir) / up["id"]).exists() for _ in [0])


@pytest.mark.asyncio
async def test_an_unknown_upload_is_refused(app):
    async with client(app) as c:
        res = await c.post("/api/runs", json={"goal": "Il sito della pizzeria", "attachments": ["0123456789ab"]})
        assert res.status_code == 400
        assert not app.state.live


@pytest.mark.asyncio
async def test_files_reach_a_stored_run_too(app, ctx):
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": "Una nota breve per il bar"})).json()["id"]
        await _until_idle(app)
        before = len(ctx.events)
        res = await c.post(f"/api/runs/{rid}/attachments", params={"name": "voce.wav", "note": "lo spot"}, content=wav())
        assert res.status_code == 201
        # a stored run never passes for the live one in the UI
        types_after = [t for t, p in ctx.events[before:]]
        assert "run.view" in types_after and "run" not in types_after and "message" not in types_after
        rec = res.json()
        assert rec["path"] == "attachments/voce.wav" and rec["kind"] == "audio" and "1.0 s" in rec["info"]["text"]
        stored = ctx.store.get(rid)
        assert stored["attachments"][-1]["id"] == rec["id"]
        assert (Path(stored["workspace"]) / "attachments" / "voce.wav").exists()
        assert (await c.post("/api/runs/nope/attachments", params={"name": "a.png"}, content=png())).status_code == 404


@pytest.mark.asyncio
async def test_a_streamed_upload_with_no_length_is_cut_too(app, ctx):
    """No Content-Length (chunked): the limit holds while the bytes arrive."""
    ctx.config.get()["limits"]["maxUploadMB"] = 0.001

    async def body():
        yield png()
        for _ in range(8):
            yield b"\x00" * 512

    async with client(app) as c:
        res = await c.post("/api/uploads", params={"name": "big.png"}, content=body())
        assert res.status_code == 413
