"""Minimal .env loader, mirroring server/env.js: KEY=VALUE lines, # comments,
optional quotes. Values already present in the real environment win."""

import os
from pathlib import Path


def load_env(file: Path) -> None:
    if not file.exists():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eq = line.find("=")
        if eq < 1:
            continue
        key = line[:eq].strip()
        value = line[eq + 1 :].strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
