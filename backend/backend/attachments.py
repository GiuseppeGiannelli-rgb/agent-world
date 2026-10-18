"""Spec 09 §3: the owner's own files -- photos of the client, a logo, a PDF
menu, texts, a voice-over -- given to a run so the agents use them instead
of generating them (when the generative APIs have no credit, or simply
because the owner has the real thing).

Before a file reaches a run:
- its extension is on the spec's list (KINDS), and its bytes are what the
  extension says (sniff): a renamed .exe is not a .png, a binary is not a .txt;
- its name is a plain file name (safe_name): no folders, drives, ":" streams
  or ".." -- the same rule as every path an agent writes (paths.py);
- it is under limits.maxUploadMB.

Then this module reads what an agent needs, without any model: the size and
shape of an image (image_info, from its header only), the text of a PDF (pypdf,
up to MAX_PDF_PAGES), a DOCX (its document.xml, read up to MAX_XML_BYTES: a
zip bomb is never inflated whole) or a text file, cut into chunks for the run
memory. What a photo shows is for inspect_image (a vision model)."""

import html as htmllib
import io
import math
import posixpath
import re
import unicodedata
import zipfile

KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"},
    "document": {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".html", ".htm", ".css", ".js"},
    "audio": {".mp3", ".wav", ".ogg"},
}
EXT_KIND = {ext: kind for kind, exts in KINDS.items() for ext in exts}
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".css", ".js", ".svg"}
MAX_NAME = 60
MAX_PDF_PAGES = 60
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
MAX_CHUNKS = 40
BINARY_MAGIC = (b"MZ", b"\x7fELF", b"PK\x03\x04", b"%PDF", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe")


class AttachmentError(ValueError):
    """A file that may not enter a run; the message is for the owner (Italian, like every HTTP error: N13)."""


def _ext(name: str) -> str:
    base = re.split(r"[\\/]", str(name or ""))[-1]
    return posixpath.splitext(base)[1].lower()


def kind_of(name: str) -> str | None:
    """image, document or audio; None for anything else (and for ".png", a name with no name)."""
    return EXT_KIND.get(_ext(name))


def safe_name(raw: str) -> str:
    """'D:\\Foto\\2026\\Foto Pizza.JPG' -> 'foto-pizza.jpg': the last part only, ASCII,
    lower case, words joined by '-', at most MAX_NAME characters before the extension."""
    base = re.split(r"[\\/]", str(raw or ""))[-1]
    stem, ext = posixpath.splitext(base)
    if not ext and stem.startswith("."):
        stem, ext = "", stem
    stem = unicodedata.normalize("NFD", stem.lower())
    stem = "".join(c for c in stem if not unicodedata.combining(c))
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:MAX_NAME].strip("-") or "file"
    return f"{stem}{ext.lower()}"


def _is_text(data: bytes) -> bool:
    head = data[:65536]
    return b"\x00" not in head and not head.startswith(BINARY_MAGIC)


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "word/document.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False


def sniff(ext: str, data: bytes) -> bool:
    """True when the first bytes are those of a file of this extension."""
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if ext == ".svg":
        return _is_text(data) and re.search(rb"<svg[\s>]", data[:65536], re.IGNORECASE) is not None
    if ext == ".pdf":
        return b"%PDF-" in data[:1024]
    if ext == ".docx":
        return data.startswith(b"PK\x03\x04") and _is_docx(data)
    if ext == ".mp3":
        return data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    if ext == ".wav":
        return data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if ext == ".ogg":
        return data.startswith(b"OggS")
    return _is_text(data)


def check(name: str, data: bytes, *, max_mb: float, size: int | None = None) -> str:
    """The kind of a file the owner may give a run, or AttachmentError."""
    kind = kind_of(name)
    if kind is None:
        allowed = ", ".join(sorted(EXT_KIND))
        raise AttachmentError(f"Tipo di file non ammesso: {name!r}. Ammessi: {allowed}.")
    size = len(data) if size is None else size
    if size > max_mb * 1024 * 1024:
        raise AttachmentError(f"Il file {name!r} supera i {max_mb:g} MB.")
    if size == 0:
        raise AttachmentError(f"Il file {name!r} è vuoto.")
    if not sniff(_ext(name), data):
        raise AttachmentError(f"Il contenuto di {name!r} non è un file {_ext(name)}.")
    return kind


# ---------- images: size and shape from the header ----------


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(data[i + 5 : i + 7], "big")
            w = int.from_bytes(data[i + 7 : i + 9], "big")
            return w, h
        i += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if chunk == b"VP8 ":
        return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    if chunk == b"VP8L":
        b = int.from_bytes(data[21:25], "little")
        return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    return None


def _number(v: str | None) -> float | None:
    m = re.match(r"\s*([\d.]+)\s*(px)?\s*$", v or "")
    return float(m.group(1)) if m else None


def _svg_size(text: str) -> tuple[int, int] | None:
    tag = re.search(r"<svg\b[^>]*>", text, re.IGNORECASE)
    if not tag:
        return None
    attrs = dict((k.lower(), v) for k, v in re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', tag.group(0)))
    w, h = _number(attrs.get("width")), _number(attrs.get("height"))
    if w and h:
        return round(w), round(h)
    box = re.split(r"[\s,]+", attrs.get("viewbox", "").strip())
    if len(box) == 4:
        try:
            return round(float(box[2])), round(float(box[3]))
        except ValueError:
            return None
    return None


def _aspect(w: int, h: int) -> str:
    g = math.gcd(w, h) or 1
    a, b = w // g, h // g
    return f"{a}:{b}" if a <= 32 and b <= 32 else f"{w / h:.2f}:1"


def image_info(data: bytes, name: str) -> dict:
    ext = _ext(name)
    fmt = "jpeg" if ext in (".jpg", ".jpeg") else ext[1:]
    size = None
    colors: list[str] = []
    if ext == ".png" and len(data) >= 24:
        size = (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))
    elif ext == ".gif" and len(data) >= 10:
        size = (int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little"))
    elif ext in (".jpg", ".jpeg"):
        size = _jpeg_size(data)
    elif ext == ".webp":
        size = _webp_size(data)
    elif ext == ".svg":
        text = data[:262144].decode("utf-8", errors="replace")
        size = _svg_size(text)
        for c in re.findall(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", text):
            c = c.lower()
            if c not in colors:
                colors.append(c)
    info: dict = {"format": fmt, "bytes": len(data)}
    if size and size[0] > 0 and size[1] > 0:
        w, h = size
        info.update(width=w, height=h, orientation="landscape" if w > h else "portrait" if h > w else "square", aspect=_aspect(w, h))
    if colors:
        info["colors"] = colors[:8]
    return info


def describe_image(info: dict) -> str:
    """One line for a brief: 'image png 1600x900, landscape 16:9'."""
    if "width" not in info:
        return f"image {info.get('format', '?')}"
    colors = f", colours {' '.join(info['colors'])}" if info.get("colors") else ""
    return f"image {info['format']} {info['width']}x{info['height']}, {info['orientation']} {info['aspect']}{colors}"


# ---------- documents: their text ----------


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")  # an Excel CSV saved on Windows


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            parts.append((page.extract_text() or "").strip())
        return "\n\n".join(p for p in parts if p)
    except Exception:  # noqa: BLE001 -- an encrypted or broken PDF has no text to give, it is not an error
        return ""


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z, z.open("word/document.xml") as f:
            xml = f.read(MAX_XML_BYTES).decode("utf-8", errors="ignore")  # inflated only up to the limit
    except (KeyError, zipfile.BadZipFile, OSError, ValueError):
        return ""
    lines = []
    for para in re.split(r"</w:p>", xml):
        para = re.sub(r"<w:tab\s*/>", "\t", para)
        para = re.sub(r"<w:br\s*/>", "\n", para)
        text = "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", para))
        if text.strip():
            lines.append(htmllib.unescape(text))
    return "\n".join(lines)


def _html_text(text: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>|</(p|div|h[1-6]|li|tr|section|article)>", "\n", text, flags=re.IGNORECASE)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", text))
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip())


def extract_text(data: bytes, name: str) -> str:
    """The text of a document the agents can read and search; "" for images and audio."""
    ext = _ext(name)
    if EXT_KIND.get(ext) != "document":
        return ""
    if ext == ".pdf":
        text = _pdf_text(data)
    elif ext == ".docx":
        text = _docx_text(data)
    elif ext in (".html", ".htm"):
        text = _html_text(decode_text(data))
    else:
        text = decode_text(data)
    return text[:MAX_TEXT_CHARS]


def chunks(text: str, max_chars: int = 1200) -> list[str]:
    """Paragraphs packed up to max_chars (a longer paragraph is cut), at most MAX_CHUNKS."""
    out: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        while len(para) > max_chars:
            if current:
                out.append(current)
                current = ""
            out.append(para[:max_chars])
            para = para[max_chars:]
        if not para:
            continue
        if current and len(current) + 2 + len(para) > max_chars:
            out.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
        if len(out) >= MAX_CHUNKS:
            break
    if current and len(out) < MAX_CHUNKS:
        out.append(current)
    return out[:MAX_CHUNKS]
