import sys

import uvicorn

from backend.app import ROOT, create_app
from backend.env import load_env


def main() -> None:
    # Windows' default console codepage (cp1252) chokes on "→"; stdout is
    # piped for tests anyway, so force UTF-8 regardless of the console.
    sys.stdout.reconfigure(encoding="utf-8")
    load_env(ROOT / ".env")
    app = create_app()
    server = app.state.config.get()["server"]
    host, port = server["host"], server["port"]
    print(f"Agent World  →  http://{host}:{port}   (backend: python)", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
