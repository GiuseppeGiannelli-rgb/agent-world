import asyncio
import os
import socket
import stat
import sys
import threading

import uvicorn

from backend.app import ROOT, create_app, env_file
from backend.config import Config
from backend.env import load_env
from backend.i18n import tr, ui_language


# N16: set by spawnBackend() (scripts/lib/backend-launcher.js) for the test servers.
# A test script killed from outside runs no handler and nothing tied its server to
# it: the server kept its port and wrote into a folder the next test removes. With
# this flag the server stops when its stdin closes, which the OS does on every
# system when the parent dies, however it is killed. npm start does not set it.
EXIT_WITH_PARENT = "AGENT_WORLD_EXIT_WITH_PARENT"


def _stdin_is_a_pipe() -> bool:
    try:
        mode = os.fstat(0).st_mode
    except OSError:
        return False
    # os.pipe() is a FIFO; Node's stdio pipes are a socketpair on POSIX and a named
    # pipe on Windows, which fstat reports as a FIFO too. The null device is neither.
    return stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)


def _exit_with_parent(server: uvicorn.Server) -> None:
    loop = asyncio.get_running_loop()

    def watch():
        try:
            while sys.stdin.buffer.read(4096):
                pass  # the parent writes nothing: only the end of the pipe matters
        except (OSError, ValueError):
            pass
        try:
            loop.call_soon_threadsafe(setattr, server, "should_exit", True)
        except RuntimeError:
            pass  # the loop is closed: the server has already stopped

    threading.Thread(target=watch, name="exit-with-parent", daemon=True).start()


async def _serve(app, host: str, port: int) -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    if os.environ.get(EXIT_WITH_PARENT) == "1":
        _exit_with_parent(server)
    task = asyncio.create_task(server.serve())
    # Print the ready line only once the socket is actually bound: the Node
    # server printed after listen(), and the test scripts fetch immediately
    # after seeing the marker (smoke.js raced the bind and got ECONNREFUSED).
    while not server.started:
        await asyncio.sleep(0.02)
    print(f"Agent World  →  http://{host}:{port}   (backend: python)", flush=True)
    await task


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Probe the way uvicorn binds. On POSIX that means SO_REUSEADDR, or the
        # TIME_WAIT connections of a server that just stopped read as "busy"
        # while uvicorn would bind fine. On Windows SO_REUSEADDR would let the
        # probe bind over a live listener (port stealing), so it stays off;
        # Windows does not block a bind on TIME_WAIT anyway.
        if os.name != "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return True
    return False


def main() -> None:
    # Windows' default console codepage (cp1252) chokes on "→"; stdout is
    # piped for tests anyway, so force UTF-8 regardless of the console.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if os.environ.get(EXIT_WITH_PARENT) == "1" and not _stdin_is_a_pipe():
        # without a pipe the server could not see its parent die: refuse, instead of
        # quietly bringing the orphan servers back
        print(f"{EXIT_WITH_PARENT}=1 needs stdin to be a pipe from the script that starts the server (spawnBackend in scripts/lib/backend-launcher.js).", file=sys.stderr, flush=True)
        sys.exit(1)
    load_env(env_file())  # ROOT/.env, or AGENT_WORLD_ENV_FILE (spec 09: the test servers read none)
    cfg = Config(ROOT / "config").get()
    host, port = cfg["server"]["host"], cfg["server"]["port"]
    if _port_in_use(host, port):
        # uvicorn would only print a traceback (WinError 10048): say what it
        # means, in the language of the app (N17). On stderr and without the
        # "Agent World  →" prefix: the test scripts read that prefix on stdout
        # as the ready line.
        print(tr(ui_language(cfg), "port_busy", port=port), file=sys.stderr, flush=True)
        sys.exit(1)
    app = create_app()
    asyncio.run(_serve(app, host, port))


if __name__ == "__main__":
    main()
