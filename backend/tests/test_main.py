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
    assert f"porta {port} è già in uso" in r.stderr
    assert "PORT=" in r.stderr  # how to pick another port
    assert "Traceback" not in out
    # The test scripts take "Agent World" on stdout as the ready line: an error
    # there made them fetch a server that never started ("fetch failed").
    assert "Agent World" not in r.stdout


def test_a_port_left_in_time_wait_is_free():
    """A server that just stopped leaves its connections in TIME_WAIT. uvicorn
    binds such a port (SO_REUSEADDR on POSIX), so the probe must too: on Linux
    flows-test.js found 4398 "busy" right after backend-boot-test.js used it."""
    from backend.__main__ import _port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        if os.name != "nt":
            # as uvicorn's listener (asyncio.create_server, reuse_address on
            # POSIX): Linux lets a bind pass a TIME_WAIT connection only when
            # both sockets have SO_REUSEADDR
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)):
            conn, _ = srv.accept()
            conn.close()  # the server side closes first: its port goes to TIME_WAIT
    assert _port_in_use("127.0.0.1", port) is False


def test_a_listening_port_is_still_busy():
    from backend.__main__ import _port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        assert _port_in_use("127.0.0.1", taken.getsockname()[1]) is True
