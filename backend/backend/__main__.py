import asyncio
import sys

import uvicorn

from backend.app import ROOT, create_app
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


def main() -> None:
    # Windows' default console codepage (cp1252) chokes on "→"; stdout is
    # piped for tests anyway, so force UTF-8 regardless of the console.
    sys.stdout.reconfigure(encoding="utf-8")
    load_env(ROOT / ".env")
    app = create_app()
    server = app.state.config.get()["server"]
    host, port = server["host"], server["port"]
    asyncio.run(_serve(app, host, port))


if __name__ == "__main__":
    main()
