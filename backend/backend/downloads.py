"""External downloads for the Skiller (Spec 05, section 5).

Only the Skiller calls this module: it is NOT an agent tool (tools.py), so no
model can download code on its own. It fetches one GitHub repository at a pinned
commit, as an archive, and extracts only the folders that hold a SKILL.md (plus
the top-level license) into CUSTOM_DOWNLOAD_PATH.

Defenses, in order:
1. the download root: opt-in (no default), absolute, not a link or junction on
   the way, not a drive root, the home folder, a system folder, the app itself
   or its data folder (resolve_download_root);
2. the source: https://github.com/<owner>/<repo> only, the branch pinned to a
   commit SHA, hosts api.github.com and codeload.github.com only, HTTPS only,
   redirects only inside that allowlist, size counted while streaming;
3. staging in <root>/.incoming/<random>, final name built here, atomic rename;
4. every entry validated before anything is written (fail closed): no absolute
   paths, drives, UNC, '..', ':' (drives, alternate data streams), NUL, reserved
   device names, trailing dots/spaces, overlong paths; only regular files and
   folders (no symlinks, hard links, devices, FIFOs, encrypted zip entries);
   tarfile's "data" filter (PEP 706) as a second layer; containment checked on
   resolved, case-folded paths, never with a string prefix;
5. limits against bombs: entries, size per file, total size, compression ratio,
   counted on the bytes actually written, never trusted from headers alone;
6. files written with exclusive create ("xb"), no permissions kept; nothing is
   ever executed.
"""

import asyncio
import hashlib
import os
import re
import shutil
import stat
import sys
import tarfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

MB = 1024 * 1024
CHUNK = 64 * 1024
MAX_PATH = 240
ALLOWED_HOSTS = {"api.github.com", "codeload.github.com"}
GITHUB_URL = re.compile(r"^https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
LICENSE_RE = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)([.-][A-Za-z0-9.-]+)?$", re.IGNORECASE)


class DownloadError(Exception):
    pass


@dataclass(frozen=True)
class Limits:
    max_archive: int = 50 * MB
    max_total: int = 200 * MB
    max_file: int = 20 * MB
    max_entries: int = 5000
    max_ratio: int = 100


# ---------- paths ----------


def _norm(path) -> Path:
    return Path(os.path.normcase(str(Path(path).resolve(strict=False))))


def _inside_or_equal(path, base) -> bool:
    p, b = _norm(path), _norm(base)
    return p == b or p.is_relative_to(b)


def contained(path, root) -> bool:
    """True if `path`, resolved, is strictly inside `root`, resolved. Compares path
    parts after normcase: "/dl/foo-evil" is not inside "/dl/foo"."""
    p, r = _norm(path), _norm(root)
    return p != r and p.is_relative_to(r)


def safe_relpath(name) -> PurePosixPath:
    """The relative path an archive entry may be written to, or DownloadError."""
    if not isinstance(name, str) or "\x00" in name:
        raise DownloadError(f"NUL byte in entry name: {name!r}")
    n = name.replace("\\", "/")
    if n.startswith("/"):
        raise DownloadError(f"absolute path in archive: {name!r}")
    if ":" in n:
        raise DownloadError(f"':' in entry name (drive or alternate data stream): {name!r}")
    if len(n) > MAX_PATH:
        raise DownloadError(f"entry path longer than {MAX_PATH}: {name[:60]!r}...")
    parts = []
    for comp in n.split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            raise DownloadError(f"'..' in entry name: {name!r}")
        if comp.endswith((".", " ")):
            raise DownloadError(f"name ending with a dot or a space: {name!r}")
        if comp.split(".")[0].rstrip(" ").upper() in RESERVED:
            raise DownloadError(f"reserved device name: {name!r}")
        parts.append(comp)
    return PurePosixPath(*parts)


def _system_dirs() -> list[Path]:
    if sys.platform == "win32":
        keys = ["SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"]
        return [Path(os.environ[k]) for k in keys if os.environ.get(k)]
    return [Path(p) for p in ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/root", "/sbin", "/sys", "/usr", "/System", "/Library", "/Applications")]


def _is_link(p: Path) -> bool:
    return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())


def resolve_download_root(raw, *, app_root, data_dir) -> Path | None:
    """CUSTOM_DOWNLOAD_PATH -> the folder downloads go to, created if missing.
    None when not set: downloads are off (D4). Refuses dangerous places."""
    if raw is None or not str(raw).strip():
        return None
    p = Path(os.path.expanduser(str(raw).strip()))
    if not p.is_absolute():
        raise DownloadError(f"CUSTOM_DOWNLOAD_PATH must be an absolute path: {raw}")
    for anc in [p, *p.parents]:
        if _is_link(anc):
            raise DownloadError(f"CUSTOM_DOWNLOAD_PATH goes through a link or junction: {anc}")
    resolved = p.resolve(strict=False)
    if resolved.parent == resolved:
        raise DownloadError("CUSTOM_DOWNLOAD_PATH cannot be a drive root")
    if _norm(resolved) == _norm(Path.home()):
        raise DownloadError("CUSTOM_DOWNLOAD_PATH cannot be the home folder itself")
    for system in _system_dirs():
        if _inside_or_equal(resolved, system):
            raise DownloadError(f"CUSTOM_DOWNLOAD_PATH cannot be inside a system folder: {system}")
    for base, what in ((app_root, "the app folder"), (data_dir, "the data folder")):
        if _inside_or_equal(resolved, base):
            raise DownloadError(f"CUSTOM_DOWNLOAD_PATH cannot be inside {what}: {base}")
    resolved.mkdir(parents=True, exist_ok=True)
    if _is_link(resolved) or not resolved.is_dir():
        raise DownloadError(f"CUSTOM_DOWNLOAD_PATH is not a plain folder: {resolved}")
    return resolved


# ---------- archives ----------


@dataclass
class _Entry:
    name: str
    is_dir: bool
    size: int  # declared
    compressed: int | None  # per-entry compressed size (zip); None for tar
    open: object


def _zip_entries(z: zipfile.ZipFile, limits: Limits) -> list[_Entry]:
    out = []
    for info in z.infolist():
        if len(out) >= limits.max_entries:
            raise DownloadError(f"too many entries (> {limits.max_entries})")
        if info.flag_bits & 0x1:
            raise DownloadError(f"encrypted zip entry: {info.filename!r}")
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)  # many zips carry permissions only (no type bits): that is a plain file
        if kind == stat.S_IFLNK:
            raise DownloadError(f"link entry in zip: {info.filename!r}")
        if kind and kind not in (stat.S_IFREG, stat.S_IFDIR):
            raise DownloadError(f"special file in zip: {info.filename!r}")
        out.append(_Entry(info.filename, info.is_dir(), info.file_size, info.compress_size, lambda i=info: z.open(i)))
    return out


def _tar_entries(t: tarfile.TarFile, limits: Limits, probe_dest: Path) -> list[_Entry]:
    out = []
    for m in t:  # lazily: a bomb stops at the first limit, not after full decompression
        if len(out) >= limits.max_entries:
            raise DownloadError(f"too many entries (> {limits.max_entries})")
        if m.issym() or m.islnk():
            raise DownloadError(f"link entry in tar: {m.name!r} -> {m.linkname!r}")
        if not (m.isfile() or m.isdir()):
            raise DownloadError(f"special file in tar: {m.name!r}")
        safe_relpath(m.name)  # before the data filter, so the reason stays ours
        try:
            tarfile.data_filter(m, str(probe_dest))  # PEP 706, second layer
        except tarfile.FilterError as err:
            raise DownloadError(f"tar entry refused by the data filter: {m.name!r} ({err})") from err
        out.append(_Entry(m.name, m.isdir(), m.size, None, lambda mm=m: t.extractfile(mm)))
    return out


def _strip_top(rels: list[tuple[_Entry, PurePosixPath]]) -> list[tuple[_Entry, PurePosixPath]]:
    """GitHub archives wrap everything in "<repo>-<sha>/": drop that level."""
    firsts = {r.parts[0] for _, r in rels if r.parts}
    files = [r for e, r in rels if not e.is_dir and r.parts]
    if len(firsts) != 1 or not files or any(len(r.parts) == 1 for r in files):
        return rels  # no single wrapper folder
    return [(e, PurePosixPath(*r.parts[1:])) for e, r in rels]


def _mkdirs(root: Path, folder: Path) -> None:
    rel = folder.relative_to(root)
    cur = root
    for part in rel.parts:
        cur = cur / part
        if _is_link(cur):
            raise DownloadError(f"link on the way to {folder}")
        if not cur.exists():
            cur.mkdir()
        elif not cur.is_dir():
            raise DownloadError(f"not a folder: {cur}")


def extract_archive(archive, dest, *, limits: Limits = Limits(), skills_only: bool = True) -> dict:
    """Extracts `archive` (zip or tar, any compression) into `dest`, which must not
    exist yet. Only folders holding a SKILL.md (and top-level license files) when
    skills_only. On any error `dest` is removed and DownloadError raised."""
    archive, dest = Path(archive), Path(dest)
    if dest.exists() or dest.is_symlink():
        raise DownloadError(f"destination exists: {dest}")
    size = archive.stat().st_size
    if size > limits.max_archive:
        raise DownloadError(f"archive too large: {size} bytes > {limits.max_archive}")
    if zipfile.is_zipfile(archive):
        handle = zipfile.ZipFile(archive)
        entries = lambda: _zip_entries(handle, limits)  # noqa: E731
    elif tarfile.is_tarfile(archive):
        handle = tarfile.open(archive, "r:*")
        entries = lambda: _tar_entries(handle, limits, dest)  # noqa: E731
    else:
        raise DownloadError("unsupported archive format")
    try:
        listed = entries()
        rels = _strip_top([(e, safe_relpath(e.name)) for e in listed])
        files = [(e, r) for e, r in rels if not e.is_dir and r.parts]
        # declared sizes: early refusal, before writing anything
        declared = 0
        for e, r in files:
            if e.size > limits.max_file:
                raise DownloadError(f"file too large: {r} ({e.size} bytes)")
            if e.compressed is not None and e.size > limits.max_ratio * max(e.compressed, 1024):
                raise DownloadError(f"compression ratio over {limits.max_ratio}:1: {r}")
            declared += e.size
        if declared > limits.max_total:
            raise DownloadError(f"total size over the limit: {declared} bytes")
        if declared > limits.max_ratio * max(size, 1024):
            raise DownloadError(f"compression ratio of the archive over {limits.max_ratio}:1")
        skill_dirs = {r.parent for _, r in files if r.name.lower() == "skill.md"}
        if not skill_dirs:
            raise DownloadError("no SKILL.md in the archive")

        def wanted(r: PurePosixPath) -> bool:
            if not skills_only:
                return True
            if len(r.parts) == 1 and LICENSE_RE.match(r.name):
                return True
            return any(r.parent == d or d in r.parents for d in skill_dirs)

        selected = [(e, r) for e, r in files if wanted(r)]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir()
        try:
            total = written_files = 0
            for e, r in selected:
                target = dest.joinpath(*r.parts)
                if not contained(target, dest):
                    raise DownloadError(f"entry escapes the destination: {r}")
                _mkdirs(dest, target.parent)
                written = 0
                try:
                    out = open(target, "xb")
                except FileExistsError as err:
                    raise DownloadError(f"duplicate entry (or case clash): {r}") from err
                with out, e.open() as src:
                    while chunk := src.read(CHUNK):
                        written += len(chunk)
                        total += len(chunk)
                        if written > limits.max_file:
                            raise DownloadError(f"file too large: {r}")
                        if total > limits.max_total:
                            raise DownloadError("total size over the limit")
                        if e.compressed is not None and written > limits.max_ratio * max(e.compressed, 1024):
                            raise DownloadError(f"compression ratio over {limits.max_ratio}:1: {r}")
                        if total > limits.max_ratio * max(size, 1024):
                            raise DownloadError(f"compression ratio of the archive over {limits.max_ratio}:1")
                        out.write(chunk)
                if os.name == "posix":
                    os.chmod(target, 0o644)
                written_files += 1
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        return {"files": written_files, "bytes": total, "skipped": len(files) - len(selected)}
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as err:
        raise DownloadError(f"broken archive: {err}") from err
    finally:
        handle.close()


# ---------- source and transfer ----------


def parse_github(url) -> tuple[str, str]:
    m = GITHUB_URL.match(str(url or "").strip())
    if not m or m.group(2) in (".", ".."):
        raise DownloadError(f"only https://github.com/<owner>/<repo> is accepted: {url}")
    return m.group(1), m.group(2)


def _check_url(url) -> httpx.URL:
    u = httpx.URL(str(url))
    if u.scheme != "https":
        raise DownloadError(f"HTTPS only: {url}")
    if u.host not in ALLOWED_HOSTS:
        raise DownloadError(f"host not allowed: {u.host}")
    return u


async def _get_json(client, url, headers):
    res = await client.get(str(_check_url(url)), headers=headers or {}, follow_redirects=False, timeout=20)
    if res.status_code != 200:
        raise DownloadError(f"GitHub {httpx.URL(url).path}: HTTP {res.status_code}")
    return res.json()


async def resolve_sha(client, owner: str, repo: str, *, headers=None) -> str:
    meta = await _get_json(client, f"https://api.github.com/repos/{owner}/{repo}", headers)
    branch = str(meta.get("default_branch") or "")
    if not BRANCH_RE.match(branch):
        raise DownloadError(f"unexpected default branch: {branch!r}")
    commit = await _get_json(client, f"https://api.github.com/repos/{owner}/{repo}/commits/{quote(branch, safe='')}", headers)
    sha = str(commit.get("sha") or "")
    if not SHA_RE.match(sha):
        raise DownloadError(f"bad commit sha from GitHub: {sha[:50]!r}")
    return sha


async def fetch_archive(client, owner: str, repo: str, sha: str, to: Path, *, max_bytes: int, headers=None) -> str:
    """Streams the tar.gz of `sha` to `to` (created exclusively). sha256 hex."""
    if not SHA_RE.match(sha):
        raise DownloadError("bad commit sha")
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{sha}"
    for _ in range(4):
        _check_url(url)
        async with client.stream("GET", url, headers=headers or {}, follow_redirects=False, timeout=60) as res:
            if res.status_code in (301, 302, 303, 307, 308):
                url = str(httpx.URL(url).join(res.headers.get("location", "")))
                continue
            if res.status_code != 200:
                raise DownloadError(f"download failed: HTTP {res.status_code}")
            declared = res.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise DownloadError(f"archive too large: {declared} bytes declared > {max_bytes}")
            digest, n = hashlib.sha256(), 0
            try:
                with open(to, "xb") as f:
                    async for chunk in res.aiter_bytes(CHUNK):
                        n += len(chunk)
                        if n > max_bytes:
                            raise DownloadError(f"archive too large: over {max_bytes} bytes while downloading")
                        digest.update(chunk)
                        f.write(chunk)
            except BaseException:
                Path(to).unlink(missing_ok=True)
                raise
            return digest.hexdigest()
    raise DownloadError("too many redirects")


def clean_incoming(root: Path) -> None:
    incoming = Path(root) / ".incoming"
    if incoming.is_dir() and not _is_link(incoming):
        for child in incoming.iterdir():
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() and not _is_link(child) else child.unlink(missing_ok=True)


def dir_size(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


async def install_repo(client, url: str, root: Path, *, limits: Limits = Limits(), headers=None) -> dict:
    """Downloads and extracts one repository into root/<owner>-<repo>@<sha7>.
    Idempotent: an existing install of the same commit is not downloaded again."""
    owner, repo = parse_github(url)
    root = Path(root)
    sha = await resolve_sha(client, owner, repo, headers=headers)
    name = re.sub(r"[^A-Za-z0-9._@-]", "_", f"{owner}-{repo}@{sha[:7]}")
    final = root / name
    slug = f"{owner}/{repo}"
    if not contained(final, root):
        raise DownloadError(f"refusing to install outside the download root: {final}")
    if final.exists():
        return {"slug": slug, "sha": sha, "dir": str(final), "already": True}
    incoming = root / ".incoming"
    incoming.mkdir(exist_ok=True)
    stage = incoming / uuid.uuid4().hex
    stage.mkdir()
    try:
        archive = stage / "archive"
        digest = await fetch_archive(client, owner, repo, sha, archive, max_bytes=limits.max_archive, headers=headers)
        unpacked = stage / "x"
        stats = await asyncio.to_thread(extract_archive, archive, unpacked, limits=limits)
        os.rename(unpacked, final)  # same volume: atomic; fails if `final` appeared meanwhile
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {"slug": slug, "sha": sha, "dir": str(final), "files": stats["files"], "bytes": stats["bytes"], "archiveSha256": digest, "already": False}
