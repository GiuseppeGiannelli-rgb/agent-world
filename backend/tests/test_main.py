"""`python -m backend` (what `npm start` runs): a busy port is explained in plain
words, not with a uvicorn traceback."""

import os
import socket
import subprocess
import sys
from pathlib import Path

from backend.i18n import tr

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
    assert tr("en", "port_busy", port=port) in r.stderr  # N17: the app language, English by default
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


# ---------- N16: a test server ends with the script that started it ----------
# A test script killed from outside (a shell time limit, taskkill /F, SIGKILL) runs
# no handler, and nothing tied its server to it: the server kept its port and wrote
# into a folder the next test removes. With AGENT_WORLD_EXIT_WITH_PARENT=1 (set by
# spawnBackend() in scripts/lib/backend-launcher.js, with a stdin pipe) the server
# exits when its stdin closes, which the OS does on every system when the parent dies.


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(tmp_path, *, tied: bool, stdin=subprocess.PIPE) -> tuple[subprocess.Popen, int, "queue.Queue[str]"]:
    import queue
    import threading

    port = _free_port()
    env = {**os.environ, "PORT": str(port), "AGENT_WORLD_HOME": str(tmp_path / "home"), "AGENT_WORLD_FAST": "1", "PYTHONIOENCODING": "utf-8"}
    env.pop("AGENT_WORLD_EXIT_WITH_PARENT", None)
    if tied:
        env["AGENT_WORLD_EXIT_WITH_PARENT"] = "1"
    p = subprocess.Popen([sys.executable, "-m", "backend"], cwd=BACKEND, env=env, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in p.stdout], daemon=True).start()
    return p, port, lines


def _ready(p, lines, timeout=60) -> bool:
    import queue
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end and p.poll() is None:
        try:
            if "Agent World" in lines.get(timeout=0.5):
                return True
        except queue.Empty:
            pass
    return False


def _answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _stop(p):
    if p.poll() is None:
        p.kill()
        p.wait(timeout=10)


def test_a_tied_server_exits_when_its_stdin_closes(tmp_path):
    p, port, lines = _start(tmp_path, tied=True)
    try:
        assert _ready(p, lines), p.stderr.read() if p.poll() is not None else "not ready"
        p.stdin.close()  # what the OS does when the parent dies
        assert p.wait(timeout=15) == 0  # a clean shutdown, lifespan included
        assert not _answers(port)
    finally:
        _stop(p)


def test_without_the_flag_closing_stdin_changes_nothing(tmp_path):
    """`npm start` and a server started by hand do not depend on their stdin."""
    import time

    p, port, lines = _start(tmp_path, tied=False)
    try:
        assert _ready(p, lines)
        p.stdin.close()
        time.sleep(2)
        assert p.poll() is None and _answers(port)
    finally:
        _stop(p)


def test_the_flag_without_a_pipe_is_refused(tmp_path):
    """With no pipe (stdin ignored) the server could not see its parent die: it
    says so and does not start, instead of silently bringing back the orphans."""
    p, port, lines = _start(tmp_path, tied=True, stdin=subprocess.DEVNULL)
    try:
        assert p.wait(timeout=60) == 1
        err = p.stderr.read()
        assert "AGENT_WORLD_EXIT_WITH_PARENT" in err and "pipe" in err
        assert "Traceback" not in err
        assert not _answers(port)
    finally:
        _stop(p)
