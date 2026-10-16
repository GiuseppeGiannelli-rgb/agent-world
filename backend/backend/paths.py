"""N16: the one rule for a path an agent or a URL names inside a root folder,
the same on every system, so a project is built the same way everywhere and can
be copied from one system to another.

- "\\" separates, as on Windows: "a\\b.md" is "a/b.md" on Linux too.
- Leading separators are dropped: "/etc/passwd" is "etc/passwd" inside the root
  (the Node contract of the workspace tools).
- ":" is refused everywhere. As a drive ("C:/x", "c:x") it leaves the root on
  Windows; anywhere else ("notes:secret.md") Windows writes it to a hidden NTFS
  data stream, and a name holding it cannot be copied to Windows.
- A NUL byte is refused (pathlib raised a bare ValueError: a 500 on the static routes).
- What leaves the root once resolved (".." or a link) is refused.

Before, each caller left it to pathlib, that is to the OS: nothing escaped the
root on either system, but the same input meant two different things."""

import re
from pathlib import Path

DRIVE_RE = re.compile(r"^[A-Za-z]:")


class PathRefused(ValueError):
    """A path that does not name a place inside the root. A ValueError, so the
    callers that catch ValueError keep working."""


def inside(root: Path, rel) -> Path:
    """`rel` resolved inside `root` (already resolved), or PathRefused."""
    raw = str(rel) if rel is not None else ""
    clean = raw.strip().replace("\\", "/").lstrip("/")
    if "\x00" in clean:
        raise PathRefused(f"Path not allowed, it holds a NUL byte: {raw!r}")
    if DRIVE_RE.match(clean):
        raise PathRefused(f"Path outside the project folder: {raw}")
    if ":" in clean:
        raise PathRefused(f"Path not allowed, ':' names a hidden data stream on Windows: {raw}. Use a name without ':'.")
    full = (root / (clean or ".")).resolve()
    if full != root and not full.is_relative_to(root):
        raise PathRefused(f"Path outside the project folder: {raw}")
    return full
