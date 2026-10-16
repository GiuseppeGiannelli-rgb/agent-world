"""Mirrors server/engine/tools.js: one shared folder per run, every path an
agent gives is resolved inside it, plus the shell command runner.

Filesystem work goes through asyncio.to_thread so a slow disk never blocks
the event loop (same principle as the bus, spec 04 B1-B2). Node sorts
directory entries with localeCompare; Python sorts by code points -- the
two orders differ only for non-ASCII names."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from backend.paths import inside

SKIP = {"node_modules", ".git", ".next", "dist", "__pycache__"}


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def resolve(self, p=".") -> Path:
        # N16: the same rule on every system (paths.py); a refusal is a ValueError
        return inside(self.root, p)

    def rel(self, full) -> str:
        return str(Path(full).relative_to(self.root)).replace(os.sep, "/")

    async def ensure(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)

    def _list_sync(self, p: str, limit: int) -> list[dict]:
        start = self.resolve(p)
        out: list[dict] = []
        queue = [start]
        while queue and len(out) < limit:
            dir_ = queue.pop(0)
            try:
                entries = sorted(dir_.iterdir(), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                if e.name in SKIP:
                    continue
                if e.is_dir():
                    queue.append(e)
                else:
                    try:
                        size = e.stat().st_size
                    except OSError:
                        size = 0
                    out.append({"path": self.rel(e), "size": size})
                if len(out) >= limit:
                    break
        return out

    async def list(self, p: str = ".", limit: int = 300) -> list[dict]:
        return await asyncio.to_thread(self._list_sync, p, limit)

    async def list_text(self, p: str = ".") -> str:
        files = await self.list(p)
        return "\n".join(f"{f['path']} ({f['size']} B)" for f in files)

    async def read(self, p: str, max: int = 12000) -> str:
        text = await asyncio.to_thread(self.resolve(p).read_text, encoding="utf-8")
        return f"{text[:max]}\n… [truncated, {len(text) - max} more chars]" if len(text) > max else text

    async def write(self, p: str, content) -> dict:
        full = self.resolve(p)
        text = content if isinstance(content, str) else __import__("json").dumps(content, indent=2)

        def write():
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(text, encoding="utf-8")

        await asyncio.to_thread(write)
        return {"path": self.rel(full), "bytes": len(text.encode("utf-8"))}

    async def write_bytes(self, p: str, data: bytes) -> dict:
        full = self.resolve(p)

        def write():
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(data)

        await asyncio.to_thread(write)
        return {"path": self.rel(full), "bytes": len(data)}

    async def size(self, p: str) -> int:
        def stat():
            try:
                s = self.resolve(p).stat()
                return s.st_size if self.resolve(p).is_file() else -1
            except OSError:
                return -1

        return await asyncio.to_thread(stat)


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _kill_tree(proc) -> None:
    """Node kills the whole tree on Windows (taskkill /T): a shell command
    may have spawned children that would otherwise survive the timeout."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                ["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


async def run_command(cmd: str, cwd, timeout_ms: int, stop_event: asyncio.Event | None = None) -> dict:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=_NO_WINDOW,
        )
    except OSError as err:
        return {"code": -1, "output": str(err)}

    output = ""

    async def pump() -> None:
        nonlocal output
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            output += chunk.decode("utf-8", errors="replace")
            if len(output) > 20000:
                output = output[-20000:]

    pump_task = asyncio.ensure_future(pump())
    watcher = None
    if stop_event is not None:

        async def watch() -> None:
            await stop_event.wait()
            _kill_tree(proc)

        watcher = asyncio.ensure_future(watch())

    try:
        await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        output += f"\n[killed after {timeout_ms} ms]"
        _kill_tree(proc)
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=10)
        except asyncio.TimeoutError:
            pass
    finally:
        if watcher is not None:
            watcher.cancel()
    try:
        await asyncio.wait_for(pump_task, timeout=10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pump_task.cancel()
    return {"code": proc.returncode if proc.returncode is not None else -1, "output": output[-5000:]}
