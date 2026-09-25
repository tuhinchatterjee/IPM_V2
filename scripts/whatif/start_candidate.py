#!/usr/bin/env python3
"""Start the What-If CANDIDATE. Beside the accepted Cockpit, never over it.

    .venv-whatif/bin/python scripts/whatif/start_candidate.py

Everything here exists to make one sentence true: **running this cannot
disturb an accepted Cockpit that is already running.** Four separations, and
each is checked rather than assumed:

1. **A different interpreter.** The candidate runs from `.venv-whatif`,
   built from `requirements-whatif.txt`. Started with the accepted
   interpreter it refuses, naming the libraries it cannot import, rather
   than running with Method 2 quietly unavailable.
2. **Different ports, discovered at runtime.** The accepted launcher's
   defaults are 8414 and 5414 and this one's are 8424 and 5424 -- but the
   defaults are only a starting point. `pick_port` walks upward from them,
   and **an occupied port is never taken**: the holder is reported and a
   free port is chosen. Nothing is ever killed to obtain one.
3. **A different state database.** The accepted runs are not this one's to
   read or to settle.
4. **The flags are set for this process only.** They are passed in the
   child's environment, not written to a `.env` and not exported to a
   shell that outlives the run. An accepted process started afterwards has
   them off, because they were never anywhere it would look.

`--stop` stops only what this script started, by the pids it recorded. It
does not search for processes that look like a Cockpit, because one of them
might be the accepted one.

**The accepted launchers are not modified and the accepted default source is
not changed.** `scripts/cockpit_v4/start.py` and
`START_COCKPIT_V4.command` are untouched at the baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

#: Ten above the accepted defaults, so a reader comparing two terminals can
#: tell at a glance which is which. Only a starting point: see `pick_port`.
DEFAULT_API_PORT = 8424
DEFAULT_UI_PORT = 5424

#: Where this script records what it started, so `--stop` stops only that.
STATE = ROOT / ".whatif-candidate.json"

#: The candidate's own interpreter and its own state database.
VENV = ROOT / ".venv-whatif"
CANDIDATE_DB = ROOT / "data" / "whatif_candidate_runs.sqlite3"

REQUIRED = ("xgboost", "lightgbm", "sklearn")


def missing_libraries() -> list[str]:
    import importlib.util

    return [name for name in REQUIRED
            if importlib.util.find_spec(name) is None]


def wrong_interpreter() -> str:
    """Why this interpreter cannot run the candidate, or an empty string."""
    absent = missing_libraries()
    if not absent:
        return ""
    return (
        f"This interpreter ({sys.executable}) cannot import "
        f"{', '.join(absent)}.\n"
        f"The candidate runs in its own environment:\n"
        f"    python3 -m venv --system-site-packages .venv-whatif\n"
        f"    .venv-whatif/bin/pip install --ignore-installed "
        f"-r requirements-whatif.txt\n"
        f"    .venv-whatif/bin/python scripts/whatif/start_candidate.py\n"
        f"Starting anyway would bring the candidate up with Method 2 "
        f"permanently unavailable and nothing on screen saying why.")


def occupied(port: int) -> str:
    """Who holds this port, or an empty string. Never kills anything."""
    probe = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                           capture_output=True, text=True)
    if probe.returncode != 0 or not probe.stdout.strip():
        return ""
    lines = probe.stdout.strip().splitlines()
    return lines[1] if len(lines) > 1 else lines[0]


def pick_port(start: int, *, span: int = 40) -> tuple[int, list[str]]:
    """The first free port at or above `start`, and who held the rest.

    An occupied port is reported and stepped over. The accepted Cockpit may
    be one of the holders, and taking its port would be exactly the thing
    this script exists not to do.
    """
    import socket

    held: list[str] = []
    for port in range(start, start + span):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                who = occupied(port)
                held.append(f"{port}: {who or 'in use'}")
                continue
        return port, held
    raise SystemExit(
        f"no free port between {start} and {start + span}. Nothing was "
        f"stopped to make one:\n  " + "\n  ".join(held))


def record(body: dict[str, object]) -> None:
    STATE.write_text(json.dumps(body, indent=2, sort_keys=True),
                     encoding="utf-8")


def stop() -> int:
    """Stop only what this script recorded starting."""
    if not STATE.exists():
        print("Nothing recorded as started by this script. Nothing stopped: "
              "a process that looks like a Cockpit might be the accepted "
              "one.")
        return 0
    body = json.loads(STATE.read_text(encoding="utf-8"))
    for name in ("api_pid", "ui_pid"):
        pid = int(body.get(name) or 0)
        if not pid:
            continue
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            print(f"stopped {name.split('_')[0]} (pid {pid})")
        except (ProcessLookupError, PermissionError) as exc:
            print(f"{name} {pid} was already gone ({exc})")
    STATE.unlink()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    parser.add_argument("--ui-port", type=int, default=DEFAULT_UI_PORT)
    parser.add_argument("--corporate", action="store_true", default=True)
    parser.add_argument("--no-corporate", dest="corporate",
                        action="store_false")
    parser.add_argument("--retail", action="store_true", default=True)
    parser.add_argument("--no-retail", dest="retail", action="store_false")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()

    if args.stop:
        return stop()

    problem = wrong_interpreter()
    if problem:
        print(problem)
        return 2

    if STATE.exists():
        print(f"{STATE.name} already exists, so a candidate may still be "
              f"running. Stop it first:\n"
              f"    .venv-whatif/bin/python "
              f"scripts/whatif/start_candidate.py --stop")
        return 2

    api_port, api_held = pick_port(args.api_port)
    ui_port, ui_held = pick_port(args.ui_port)
    for line in api_held + ui_held:
        print(f"  port in use, stepped over: {line}")

    # The flags live in the CHILD's environment and nowhere else. Not a
    # .env, not an export: an accepted process started later must not
    # inherit them.
    child = dict(os.environ)
    if args.corporate:
        child["COCKPIT_V4_WHATIF_CORPORATE"] = "1"
    if args.retail:
        child["COCKPIT_V4_WHATIF_RETAIL"] = "1"
    child["COCKPIT_AGENTIC_V3_NAMESPACE"] = "cockpit_v4"
    child["COCKPIT_V4_DB"] = str(CANDIDATE_DB)
    child["PYTHONPATH"] = str(ROOT)

    print("\nWhat-If candidate")
    print(f"  interpreter  {sys.executable}")
    print(f"  Corporate    {'ON' if args.corporate else 'off'}")
    print(f"  Retail       {'ON' if args.retail else 'off'}")
    print(f"  state db     {CANDIDATE_DB}")
    print(f"  API          http://127.0.0.1:{api_port}")
    print(f"  UI           http://127.0.0.1:{ui_port}")

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=str(ROOT), env=child, start_new_session=True)

    ui_env = dict(child)
    ui_env["NEXT_PUBLIC_COCKPIT_V4_API"] = f"http://127.0.0.1:{api_port}"
    ui_env["NEXT_PUBLIC_API_URL"] = f"http://127.0.0.1:{api_port}"
    ui_env["PORT"] = str(ui_port)
    ui = subprocess.Popen(
        ["npm", "--prefix", "frontend", "run", "dev", "--",
         "--port", str(ui_port)],
        cwd=str(ROOT), env=ui_env, start_new_session=True)

    record({
        "api_pid": api.pid, "ui_pid": ui.pid,
        "api_port": api_port, "ui_port": ui_port,
        "corporate": args.corporate, "retail": args.retail,
        "interpreter": sys.executable,
        "state_db": str(CANDIDATE_DB),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": ("Started by scripts/whatif/start_candidate.py. --stop "
                 "stops these pids and nothing else."),
    })
    print(f"\nrecorded in {STATE.name}. Stop with:")
    print("    .venv-whatif/bin/python scripts/whatif/start_candidate.py "
          "--stop")
    print("\nThe accepted Cockpit, if it is running, was not touched: "
          "different ports, a different interpreter and a different state "
          "database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
