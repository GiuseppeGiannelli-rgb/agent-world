"""N16: one rule for the paths an agent or a URL names, the same on every system.

Before, Workspace.resolve() and the static routes left it to the OS: on Windows
"\\" separates and "C:" is a drive, elsewhere both are plain filename characters.
Nothing escaped the root on either, but the same agent output built different
folders ("a\\b.md" nested on Windows, one odd file name on Linux), a project made
on Linux could not be copied to Windows, and on Windows "notes:secret.md" wrote
an NTFS alternate data stream, data the folder does not show.

The rule (D1, D2 option b): "\\" is a separator everywhere, leading separators
are dropped (the Node contract: "/etc/passwd" stays inside), and ":" is refused
everywhere: as a drive it would leave the project, anywhere else it is a hidden
data stream on Windows and a name Windows cannot hold. The table below is run as
is on every system: the expectations do not depend on the platform."""

import pytest

from backend.routes.static import _resolve
from backend.tools import Workspace


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    return r.resolve()


INSIDE = {
    "a/b.md": "a/b.md",
    "a\\b.md": "a/b.md",
    "a\\b\\c.md": "a/b/c.md",
    "": ".",
    ".": ".",
    "/etc/passwd": "etc/passwd",
    "\\etc\\passwd": "etc/passwd",
    "\\\\server\\share\\x": "server/share/x",
    "a/../b.md": "b.md",
    "a\\..\\b.md": "b.md",
}

ESCAPES = ["../x", "..\\x", "..\\..\\x", "a/../../x", "a\\..\\..\\x", "/..\\..\\server\\index.js"]
DRIVES = ["C:/Windows/x", "C:\\Windows\\x", "c:x", "/C:/x", "D:"]
STREAMS = ["notes:secret.md", "a/b:c.txt", "file.txt::$DATA", "a\\b:c"]


@pytest.mark.parametrize("given,expected", INSIDE.items())
def test_a_path_inside_lands_in_the_same_place_on_every_system(root, given, expected):
    want = root if expected == "." else root.joinpath(*expected.split("/"))
    assert Workspace(root).resolve(given) == want
    assert _resolve(root, given) == want


@pytest.mark.parametrize("given", ESCAPES + DRIVES)
def test_a_path_that_leaves_the_project_is_refused_on_every_system(root, given):
    with pytest.raises(ValueError, match="outside the project folder"):
        Workspace(root).resolve(given)
    assert _resolve(root, given) is None


@pytest.mark.parametrize("given", STREAMS)
def test_a_colon_is_refused_on_every_system(root, given):
    """The agent reads the message (tool errors go back as "ERROR: ..."): it says what to change."""
    with pytest.raises(ValueError, match="':'"):
        Workspace(root).resolve(given)
    assert _resolve(root, given) is None


@pytest.mark.asyncio
async def test_a_file_written_with_backslashes_is_nested_and_listed_with_slashes(root):
    ws = Workspace(root)
    r = await ws.write("docs\\notes\\a.md", "x")
    assert r["path"] == "docs/notes/a.md"
    assert (root / "docs" / "notes" / "a.md").read_text(encoding="utf-8") == "x"
    assert [e["path"] for e in await ws.list(".")] == ["docs/notes/a.md"]
