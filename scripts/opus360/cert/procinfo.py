"""Process identity, read the same way by the owner and by STOP."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime


def ps_field(pid: int, field: str) -> str:
    out = subprocess.run(["ps", "-p", str(pid), "-o", f"{field}="], capture_output=True, text=True)
    return out.stdout.strip()


def start_time(pid: int) -> float | None:
    """The OS-recorded start time of `pid` (seconds since the epoch), or None."""
    text = " ".join(ps_field(pid, "lstart").split())
    if not text:
        return None
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Y").timestamp()
    except ValueError:
        return None


def cwd(pid: int) -> str:
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            return ""
    out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""
