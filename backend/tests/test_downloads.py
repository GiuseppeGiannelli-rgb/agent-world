"""Spec 05 §5: external downloads. Every attack is a real archive or path built
here; each must be refused WITHOUT writing anything outside the staging area,
and a failed extraction must leave no destination behind."""

import gzip
import io
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest

from backend.downloads import (
    DownloadError,
    Limits,
    contained,
    extract_archive,
    fetch_archive,
    install_repo,
    parse_github,
    resolve_download_root,
    resolve_sha,
    safe_relpath,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
SMALL = Limits(max_archive=2_000_000, max_total=3_000_000, max_file=1_000_000, max_entries=50, max_ratio=100)


# ---------- archive builders ----------


def make_zip(path: Path, entries) -> Path:
    """entries: (name, data) or (ZipInfo, data)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return path


def make_tar(path: Path, members) -> Path:
    """members: (TarInfo, data) pairs; data is None for non-regular entries."""
    path.write_bytes(tar_bytes(members))
    return path


def tar_file(name, data=b"x"):
    return tarfile.TarInfo(name), data


def tar_link(name, target, kind=tarfile.SYMTYPE):
    m = tarfile.TarInfo(name)
    m.type = kind
    m.linkname = target
    return m, None


def snapshot(root: Path) -> set:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


@pytest.fixture()
def place(tmp_path):
    """dest (must not exist yet) + a sibling 'outside' folder that must stay empty."""
    (tmp_path / "outside").mkdir()
    return tmp_path / "dl" / "acme-skills@0123456", tmp_path / "outside"


def assert_refused(archive, dest, outside, match=None):
    before = snapshot(outside.parent)
    with pytest.raises(DownloadError, match=match):
        extract_archive(archive, dest, limits=SMALL)
    assert not dest.exists(), "a failed extraction must leave no destination"
    assert snapshot(outside) == set(), "nothing may be written outside"
    assert snapshot(outside.parent) - before <= {"dl"}, "only the (empty) parent of dest may appear"


# ---------- entry names ----------


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "skills/../../evil.txt",
        "..\\evil.txt",
        "skills\\..\\..\\evil.txt",
        "/etc/passwd",
        "\\Windows\\evil.dll",
        "C:\\Windows\\evil.dll",
        "C:evil.txt",
        "\\\\server\\share\\evil.txt",
        "//server/share/evil.txt",
        "skills/a/SKILL.md:hidden",
        "skills/CON",
        "skills/con.txt",
        "skills/a/NUL.md",
        "skills/a/com1.md",
        "skills/a/LPT9",
        "skills/a./SKILL.md",
        "skills/a /SKILL.md",
        "skills/a\x00/SKILL.md",
        "skills/" + "x" * 250 + "/SKILL.md",
    ],
)
def test_unsafe_names_are_refused(name):
    with pytest.raises(DownloadError):
        safe_relpath(name)


@pytest.mark.parametrize(
    "name, want",
    [
        ("skills/a/SKILL.md", "skills/a/SKILL.md"),
        ("./skills//a/./SKILL.md", "skills/a/SKILL.md"),
        ("skills\\a\\SKILL.md", "skills/a/SKILL.md"),
        ("skills/console.md", "skills/console.md"),  # CON only as a whole name
        ("skills/a.b/notes.md", "skills/a.b/notes.md"),
    ],
)
def test_safe_names_are_normalized(name, want):
    assert safe_relpath(name).as_posix() == want


def test_containment_is_checked_on_resolved_paths_not_string_prefixes(tmp_path):
    root = tmp_path / "foo"
    root.mkdir()
    assert contained(root / "a" / "b.md", root)
    assert not contained(tmp_path / "foo-evil" / "x", root)  # same string prefix, other folder
    assert not contained(root / ".." / "foo-evil" / "x", root)
    assert not contained(root, root)  # the root itself is not an entry
    if sys.platform == "win32":
        assert contained(Path(str(root).upper()) / "a.md", root)  # case-insensitive volume


# ---------- traversal and links inside real archives ----------


def test_zip_slip_is_refused(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "a.zip", [("repo/skills/a/SKILL.md", "ok"), ("repo/../../outside/pwned.txt", "x")])
    assert_refused(archive, dest, outside)


def test_tar_traversal_is_refused(tmp_path, place):
    dest, outside = place
    archive = make_tar(tmp_path / "a.tar.gz", [tar_file("repo/skills/a/SKILL.md"), tar_file("repo/skills/..\\..\\..\\outside\\pwned.txt")])
    assert_refused(archive, dest, outside)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_tar_links_are_refused(tmp_path, place, kind):
    dest, outside = place
    archive = make_tar(tmp_path / "a.tar.gz", [tar_link("repo/skills/a", "../../outside", kind), tar_file("repo/skills/a/SKILL.md")])
    assert_refused(archive, dest, outside, match="link")


def test_symlink_spoofing_through_a_linked_folder_is_refused(tmp_path, place):
    # classic two-step attack: a symlink folder, then a file "inside" it
    dest, outside = place
    archive = make_tar(tmp_path / "a.tar.gz", [tar_link("repo/skills", str(outside)), tar_file("repo/skills/a/SKILL.md", b"pwned")])
    assert_refused(archive, dest, outside, match="link")


@pytest.mark.parametrize("kind", [tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE])
def test_tar_devices_and_fifos_are_refused(tmp_path, place, kind):
    dest, outside = place
    dev = tarfile.TarInfo("repo/skills/a/dev")
    dev.type = kind
    archive = make_tar(tmp_path / "a.tar.gz", [tar_file("repo/skills/a/SKILL.md"), (dev, None)])
    assert_refused(archive, dest, outside)


def test_zip_symlink_entry_is_refused(tmp_path, place):
    dest, outside = place
    link = zipfile.ZipInfo("repo/skills/a/notes")  # a neutral name: "link" must come from the reason
    link.external_attr = (0o120777 << 16)  # S_IFLNK
    archive = make_zip(tmp_path / "a.zip", [("repo/skills/a/SKILL.md", "ok"), (link, "../../../outside")])
    assert_refused(archive, dest, outside, match="link")


def set_encrypted_flag(path: Path, name: str) -> None:
    # zipfile resets flag_bits on write: set bit 0 in the local and central headers by hand
    raw = bytearray(path.read_bytes())
    fname = name.encode()
    for sig, flag_at, name_at in ((b"PK", 6, 30), (b"PK", 8, 46)):
        i = raw.find(sig)
        while i >= 0:
            if raw[i + name_at : i + name_at + len(fname)] == fname:
                raw[i + flag_at] |= 0x1
            i = raw.find(sig, i + 4)
    path.write_bytes(bytes(raw))


def test_encrypted_zip_entry_is_refused(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "a.zip", [("repo/skills/a/SKILL.md", "ok"), ("repo/skills/a/secret.md", "x")])
    set_encrypted_flag(archive, "repo/skills/a/secret.md")
    assert zipfile.ZipFile(archive).getinfo("repo/skills/a/secret.md").flag_bits & 0x1
    assert_refused(archive, dest, outside, match="encrypted")


def test_one_unsafe_entry_outside_the_skills_still_refuses_everything(tmp_path, place):
    # fail closed: the archive is suspicious even if the bad entry would be skipped
    dest, outside = place
    archive = make_zip(tmp_path / "a.zip", [("repo/skills/a/SKILL.md", "ok"), ("repo/src/../../../x", "x")])
    assert_refused(archive, dest, outside)


# ---------- bombs and limits ----------


def test_zip_bomb_ratio_is_refused(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "bomb.zip", [("repo/skills/a/SKILL.md", "ok"), ("repo/skills/a/zeros.bin", b"\0" * 900_000)])
    assert (tmp_path / "bomb.zip").stat().st_size < 9_000  # > 100:1
    assert_refused(archive, dest, outside, match="ratio")


def test_gzip_bomb_ratio_is_refused(tmp_path, place):
    dest, outside = place
    archive = make_tar(tmp_path / "bomb.tar.gz", [tar_file("repo/skills/a/SKILL.md"), tar_file("repo/skills/a/zeros.bin", b"\0" * 900_000)])
    assert_refused(archive, dest, outside, match="ratio")


def test_file_size_limit(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "big.zip", [("repo/skills/a/SKILL.md", "ok"), ("repo/skills/a/big.bin", os.urandom(1_200_000))])
    assert_refused(archive, dest, outside, match="file")


def test_total_size_limit(tmp_path, place):
    dest, outside = place
    entries = [("repo/skills/a/SKILL.md", "ok")] + [(f"repo/skills/a/p{i}.bin", os.urandom(900_000)) for i in range(4)]
    archive = make_zip(tmp_path / "total.zip", entries)
    roomy = Limits(max_archive=10_000_000, max_total=3_000_000, max_file=1_000_000, max_entries=50, max_ratio=100)
    with pytest.raises(DownloadError, match="total"):
        extract_archive(archive, dest, limits=roomy)
    assert not dest.exists() and snapshot(outside) == set()


def test_entry_count_limit(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "many.zip", [("repo/skills/a/SKILL.md", "ok")] + [(f"repo/skills/a/f{i}.md", "x") for i in range(60)])
    assert_refused(archive, dest, outside, match="entries")


def test_archive_size_limit(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "huge.zip", [("repo/skills/a/SKILL.md", "ok"), ("repo/skills/a/r.bin", os.urandom(2_100_000))])
    assert_refused(archive, dest, outside, match="archive")


def test_not_an_archive_is_refused(tmp_path, place):
    dest, outside = place
    (tmp_path / "x.bin").write_bytes(b"MZ\x90\x00 not an archive")
    assert_refused(tmp_path / "x.bin", dest, outside, match="format")


# ---------- the happy path ----------


GOOD = [
    ("acme-skills-0123456/README.md", "# Acme"),
    ("acme-skills-0123456/LICENSE", "MIT"),
    ("acme-skills-0123456/src/app.js", "console.log(1)"),
    ("acme-skills-0123456/scripts/install.sh", "rm -rf /"),
    ("acme-skills-0123456/skills/a/SKILL.md", "---\nname: a\n---\n# A"),
    ("acme-skills-0123456/skills/a/ref/notes.md", "notes"),
    ("acme-skills-0123456/skills/b/SKILL.md", "---\nname: b\n---\n# B"),
]


@pytest.mark.parametrize("fmt", ["zip", "tar"])
def test_only_skill_folders_and_license_are_extracted(tmp_path, place, fmt):
    dest, outside = place
    if fmt == "zip":
        archive = make_zip(tmp_path / "good.zip", GOOD)
    else:
        archive = make_tar(tmp_path / "good.tar.gz", [tar_file(n, d.encode()) for n, d in GOOD])
    out = extract_archive(archive, dest, limits=SMALL)
    assert snapshot(dest) == {"LICENSE", "skills", os.path.join("skills", "a"), os.path.join("skills", "a", "SKILL.md"), os.path.join("skills", "a", "ref"), os.path.join("skills", "a", "ref", "notes.md"), os.path.join("skills", "b"), os.path.join("skills", "b", "SKILL.md")}
    assert out == {"files": 4, "bytes": sum(len(d) for n, d in GOOD if "/skills/" in n or n.endswith("LICENSE")), "skipped": 3}
    assert snapshot(outside) == set()
    if os.name == "posix":
        assert not any(os.stat(p).st_mode & 0o111 for p in dest.rglob("*") if p.is_file())


def test_archive_without_skills_is_refused(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "none.zip", [("repo/README.md", "x"), ("repo/src/a.js", "x")])
    assert_refused(archive, dest, outside, match="SKILL.md")


def test_existing_destination_is_never_overwritten(tmp_path, place):
    dest, outside = place
    dest.mkdir(parents=True)
    (dest / "keep.txt").write_text("mine")
    with pytest.raises(DownloadError, match="exists"):
        extract_archive(make_zip(tmp_path / "good.zip", GOOD), dest, limits=SMALL)
    assert (dest / "keep.txt").read_text() == "mine"


# ---------- the download root (D4) ----------


def test_download_root_is_off_by_default(tmp_path):
    assert resolve_download_root(None, app_root=tmp_path / "app", data_dir=tmp_path / "data") is None
    assert resolve_download_root("  ", app_root=tmp_path / "app", data_dir=tmp_path / "data") is None


def test_download_root_is_created_and_resolved(tmp_path):
    root = resolve_download_root(str(tmp_path / "dl" / "skills"), app_root=tmp_path / "app", data_dir=tmp_path / "data")
    assert root == (tmp_path / "dl" / "skills").resolve() and root.is_dir()


def _bad_roots(tmp_path):
    app = tmp_path / "app"
    (app / ".git").mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir()
    bad = {
        "relative": "downloads",
        "drive root": tmp_path.anchor,
        "home": str(Path.home()),
        "inside the repo": str(app / "vendor"),
        "inside .git": str(app / ".git" / "dl"),
        "the repo itself": str(app),
        "inside data": str(data / "dl"),
    }
    if sys.platform == "win32":
        bad["windows dir"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "dl")
        bad["program files"] = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "dl")
    else:
        bad["system dir"] = "/usr/local/agent-world-dl"
    return app, data, bad


def test_dangerous_download_roots_are_refused(tmp_path):
    app, data, bad = _bad_roots(tmp_path)
    for why, raw in bad.items():
        with pytest.raises(DownloadError):
            resolve_download_root(raw, app_root=app, data_dir=data)
        assert not (app / "vendor").exists() and not (data / "dl").exists(), why


def test_a_junction_or_symlink_root_is_refused(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    if sys.platform == "win32":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if r.returncode != 0:
            pytest.skip("cannot create a junction here")
    else:
        os.symlink(target, link, target_is_directory=True)
    with pytest.raises(DownloadError, match="link"):
        resolve_download_root(str(link), app_root=tmp_path / "app", data_dir=tmp_path / "data")
    with pytest.raises(DownloadError, match="link"):
        resolve_download_root(str(link / "sub"), app_root=tmp_path / "app", data_dir=tmp_path / "data")


# ---------- source and transfer ----------


@pytest.mark.parametrize("url", ["https://github.com/acme/skills", "https://github.com/acme/skills/", "https://github.com/acme/skills.git"])
def test_parse_github_accepts_repo_urls(url):
    assert parse_github(url) == ("acme", "skills")


@pytest.mark.parametrize(
    "url",
    ["http://github.com/acme/skills", "https://github.com.evil.io/acme/skills", "https://github.com/acme/skills/archive/main.zip",
     "https://github.com/acme/..", "https://github.com/-acme/skills", "git@github.com:acme/skills.git", "https://gitlab.com/acme/skills"],
)
def test_parse_github_refuses_everything_else(url):
    with pytest.raises(DownloadError):
        parse_github(url)


def tar_bytes(members) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for m, data in members:
            if data is None:
                t.addfile(m)
            else:
                m.size = len(data)
                t.addfile(m, io.BytesIO(data))
    return buf.getvalue()


def github(requests, *, archive=b"", redirect=None, length=None, sha=SHA, chunked=False):
    def handler(request: httpx.Request):
        requests.append(str(request.url))
        host, path = request.url.host, request.url.path
        if host == "api.github.com" and path == "/repos/acme/skills":
            return httpx.Response(200, json={"default_branch": "main"})
        if host == "api.github.com" and path == "/repos/acme/skills/commits/main":
            return httpx.Response(200, json={"sha": sha})
        if host == "codeload.github.com":
            if redirect:
                return httpx.Response(302, headers={"location": redirect})
            if chunked:
                async def stream():
                    for i in range(0, len(archive), 1000):
                        yield archive[i : i + 1000]

                return httpx.Response(200, content=stream())
            headers = {"content-length": str(length if length is not None else len(archive))}
            return httpx.Response(200, content=archive, headers=headers)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_resolve_sha_pins_a_commit():
    requests = []
    async with github(requests) as c:
        assert await resolve_sha(c, "acme", "skills") == SHA
    async with github(requests, sha="not-a-sha") as c:
        with pytest.raises(DownloadError, match="sha"):
            await resolve_sha(c, "acme", "skills")


async def test_fetch_refuses_redirects_off_the_allowlist(tmp_path):
    requests = []
    async with github(requests, redirect="https://evil.example/payload.tar.gz") as c:
        with pytest.raises(DownloadError, match="host"):
            await fetch_archive(c, "acme", "skills", SHA, tmp_path / "a.tar.gz", max_bytes=1_000_000)
    assert not any("evil.example" in u for u in requests) and not (tmp_path / "a.tar.gz").exists()


async def test_fetch_refuses_oversized_archives(tmp_path):
    requests = []
    async with github(requests, archive=b"x" * 10, length=5_000_000) as c:  # declared too big
        with pytest.raises(DownloadError, match="archive"):
            await fetch_archive(c, "acme", "skills", SHA, tmp_path / "a.tar.gz", max_bytes=1_000_000)
    async with github(requests, archive=os.urandom(1_500_000), chunked=True) as c:  # no length, too big while streaming
        with pytest.raises(DownloadError, match="archive"):
            await fetch_archive(c, "acme", "skills", SHA, tmp_path / "b.tar.gz", max_bytes=1_000_000)
    assert not (tmp_path / "a.tar.gz").exists() and not (tmp_path / "b.tar.gz").exists()


async def test_install_repo_end_to_end_is_idempotent(tmp_path):
    root = tmp_path / "dl"
    root.mkdir()
    archive = tar_bytes([tar_file(n, d.encode()) for n, d in GOOD])
    requests = []
    async with github(requests, archive=archive) as c:
        out = await install_repo(c, "https://github.com/acme/skills", root, limits=SMALL)
        assert out["dir"] == str(root / "acme-skills@0123456")
        assert out["sha"] == SHA and out["files"] == 4 and len(out["archiveSha256"]) == 64
        assert (root / "acme-skills@0123456" / "skills" / "a" / "SKILL.md").is_file()
        assert sorted(p.name for p in root.iterdir()) == [".incoming", "acme-skills@0123456"]
        assert list((root / ".incoming").iterdir()) == []  # staging cleaned
        downloads = sum("codeload" in u for u in requests)
        again = await install_repo(c, "https://github.com/acme/skills", root, limits=SMALL)
        assert again["already"] is True and sum("codeload" in u for u in requests) == downloads
    assert {httpx.URL(u).host for u in requests} <= {"api.github.com", "codeload.github.com"}


async def test_install_repo_cleans_up_after_a_malicious_archive(tmp_path):
    root = tmp_path / "dl"
    root.mkdir()
    archive = tar_bytes([tar_file("acme-skills-0123456/skills/a/SKILL.md"), tar_link("acme-skills-0123456/skills/x", "../../..")])
    requests = []
    async with github(requests, archive=archive) as c:
        with pytest.raises(DownloadError):
            await install_repo(c, "https://github.com/acme/skills", root, limits=SMALL)
    assert [p.name for p in root.iterdir()] == [".incoming"] and list((root / ".incoming").iterdir()) == []


def test_gzip_module_is_what_tar_uses():  # guard: the tar bomb test relies on gzip compression
    assert gzip.compress(b"\0" * 100_000)[:2] == b"\x1f\x8b"


def test_duplicate_entries_are_refused_not_overwritten(tmp_path, place):
    dest, outside = place
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile warns about the duplicate name: that is the point
        archive = make_zip(tmp_path / "dup.zip", [("repo/skills/a/SKILL.md", "first"), ("repo/skills/a/SKILL.md", "second, overwriting")])
    assert_refused(archive, dest, outside, match="duplicate")


@pytest.mark.skipif(sys.platform != "win32", reason="case clashes only exist on case-insensitive volumes")
def test_case_clash_is_refused_on_windows(tmp_path, place):
    dest, outside = place
    archive = make_zip(tmp_path / "case.zip", [("repo/skills/a/SKILL.md", "first"), ("repo/skills/a/skill.md", "second")])
    assert_refused(archive, dest, outside, match="duplicate")
