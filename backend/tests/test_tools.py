"""Contract tests for backend/tools.py (Workspace + run_command), ported
from server/engine/tools.js."""

import asyncio
import sys

import pytest

from backend.tools import Workspace, run_command


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "proj")


class TestWorkspace:
    @pytest.mark.asyncio
    async def test_resolve_keeps_paths_inside_the_root(self, ws, tmp_path):
        await ws.ensure()
        assert ws.resolve("a/b.md") == ws.root / "a" / "b.md"
        assert ws.resolve("") == ws.root
        assert ws.resolve(".") == ws.root
        # Node strips leading slashes, so these stay INSIDE the root
        assert ws.resolve("/etc/passwd") == ws.root / "etc" / "passwd"
        for evil in ("../outside.txt", "..\\..\\x", "C:/Windows/x"):
            with pytest.raises(ValueError, match="outside the project folder"):
                ws.resolve(evil)

    @pytest.mark.asyncio
    async def test_write_read_roundtrip_and_bytes(self, ws):
        await ws.ensure()
        r = await ws.write("docs/hello.md", "# Ciao\n")
        assert r == {"path": "docs/hello.md", "bytes": len("# Ciao\n".encode())}
        assert await ws.read("docs/hello.md") == "# Ciao\n"
        # content that is not a string is serialized as indented JSON
        r2 = await ws.write("data.json", {"a": 1})
        assert (await ws.read("data.json")) == '{\n  "a": 1\n}'
        assert r2["bytes"] == len('{\n  "a": 1\n}'.encode())

    @pytest.mark.asyncio
    async def test_read_truncates_with_node_message(self, ws):
        await ws.ensure()
        await ws.write("big.txt", "x" * 100)
        out = await ws.read("big.txt", max=10)
        assert out == "x" * 10 + "\n… [truncated, 90 more chars]"

    @pytest.mark.asyncio
    async def test_size_missing_and_directory(self, ws):
        await ws.ensure()
        assert await ws.size("nope.txt") == -1
        await ws.write("d/f.txt", "abc")
        assert await ws.size("d/f.txt") == 3
        assert await ws.size("d") == -1  # directories report -1, like Node

    @pytest.mark.asyncio
    async def test_list_skips_noise_and_sorts(self, ws):
        await ws.ensure()
        await ws.write("b/z.txt", "z")
        await ws.write("a.txt", "a")
        await ws.write("node_modules/pkg/i.js", "x")
        await ws.write(".git/head", "x")
        await ws.write("__pycache__/m.pyc", "x")
        files = await ws.list(".")
        paths = [f["path"] for f in files]
        assert paths == ["a.txt", "b/z.txt"]
        assert all("node_modules" not in p and ".git" not in p for p in paths)
        text = await ws.list_text(".")
        assert text == "a.txt (1 B)\nb/z.txt (1 B)"

    @pytest.mark.asyncio
    async def test_write_bytes(self, ws):
        await ws.ensure()
        r = await ws.write_bytes("img/p.png", b"\x89PNG\r\n")
        assert r == {"path": "img/p.png", "bytes": 6}
        assert (ws.root / "img" / "p.png").read_bytes() == b"\x89PNG\r\n"


class TestRunCommand:
    @pytest.mark.asyncio
    async def test_captures_output_and_exit_code(self, tmp_path):
        r = await run_command(f'"{sys.executable}" -c "print(\'hello\')"', tmp_path, 10000)
        assert r["code"] == 0
        assert "hello" in r["output"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self, tmp_path):
        r = await run_command(f'"{sys.executable}" -c "import sys; sys.exit(3)"', tmp_path, 10000)
        assert r["code"] == 3

    @pytest.mark.asyncio
    async def test_timeout_kills_the_process(self, tmp_path):
        r = await run_command(f'"{sys.executable}" -c "import time; time.sleep(30)"', tmp_path, 400)
        assert r["code"] != 0
        assert "[killed after 400 ms]" in r["output"]

    @pytest.mark.asyncio
    async def test_output_is_capped_to_the_tail(self, tmp_path):
        r = await run_command(f'"{sys.executable}" -c "print(\'y\' * 30000)"', tmp_path, 10000)
        assert len(r["output"]) <= 5100

    @pytest.mark.asyncio
    async def test_stop_event_kills_the_process(self, tmp_path):
        stop = asyncio.Event()
        task = asyncio.ensure_future(run_command(f'"{sys.executable}" -c "import time; time.sleep(30)"', tmp_path, 60000, stop))
        await asyncio.sleep(0.2)
        stop.set()
        r = await asyncio.wait_for(task, timeout=10)
        assert r["code"] != 0
