import asyncio
import os
import socket
import sys

import uvicorn

from backend.app import ROOT, create_app
from backend.config import Config
from backend.env import load_env


async def _serve(app, host: str, port: int) -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
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
    load_env(ROOT / ".env")
    server = Config(ROOT / "config").get()["server"]
    host, port = server["host"], server["port"]
    if _port_in_use(host, port):
        # uvicorn would only print a traceback (WinError 10048): say what it
        # means. On stderr and without the "Agent World  →" prefix: the test
        # scripts read that prefix on stdout as the ready line.
        print(
            f"La porta {port} è già in uso: probabilmente Agent World (o un altro server) è già avviato.\n"
            f"Chiudilo (Ctrl+C nella sua finestra), oppure scegli un'altra porta: PORT=4301 nel file .env.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    app = create_app()
    asyncio.run(_serve(app, host, port))


if __name__ == "__main__":
    main()
