"""`python -m backend` (what `npm start` runs): a busy port is explained in plain
words, not with a uvicorn traceback."""

import os
import socket
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_busy_port_is_explained_without_a_traceback():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        env = {**os.environ, "PORT": str(port), "AGENT_WORLD_SKILLER": "0", "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run([sys.executable, "-m", "backend"], cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert f"porta {port} è già in uso" in out
    assert "PORT=" in out  # how to pick another port
    assert "Traceback" not in out
