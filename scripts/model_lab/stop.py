"""
Stop ONLY the processes this lab started (recorded under <runtime>/pids and
re-verified by start time, command and cwd). Never kills by name, never
touches a shared model daemon or another CreditProbe instance.

    python scripts/model_lab/stop.py [--runtime-dir DIR]
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cockpit_v4"))

import _common as cm  # noqa: E402

DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    args = ap.parse_args(argv)
    runtime = Path(args.runtime_dir).expanduser().resolve()
    stopped = 0
    for owned in cm.records(runtime):
        ours, why = cm.still_ours(owned)
        if not ours:
            print(cm.warn(f"{owned.name}: {why}; record removed, nothing "
                          f"stopped"))
            cm.forget(runtime, owned.name)
            continue
        try:
            os.killpg(owned.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(50):
            if not cm.still_ours(owned)[0]:
                break
            time.sleep(0.2)
        else:
            try:
                os.killpg(owned.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        cm.forget(runtime, owned.name)
        stopped += 1
        print(cm.ok(f"stopped lab {owned.name} (pid {owned.pid})"))
    if not stopped:
        print("no lab process of ours was running")
    return 0


if __name__ == "__main__":
    sys.exit(main())
