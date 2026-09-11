#!/usr/bin/env python3
"""
Bring up the V4 stack and run the real browser suite against it.

Starts the stub V4 API and the real Next.js UI on free ports, waits for both
using the checks that match what each actually serves, runs Playwright, writes
the evidence, and stops only the processes it started.

Usage:
    python3 scripts/cockpit_v4/browser_evidence.py
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

from scripts.cockpit_v4._common import (  # noqa: E402
    bad, heading, ok, pick_port, wait_for_json_health, wait_for_ui_ready, warn)
from scripts.cockpit_v4.start import ui_environment  # noqa: E402

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def stop(process: subprocess.Popen | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=10)
    except Exception:  # noqa: BLE001
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass
    print(f"  stopped {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8471)
    parser.add_argument("--ui-port", type=int, default=5471)
    parser.add_argument("--keep-up", action="store_true",
                        help="leave both running after the suite")
    args = parser.parse_args()

    api_port, notes = pick_port(args.api_port)
    ui_port, ui_notes = pick_port(args.ui_port)
    for note in notes + ui_notes:
        print(warn(note))
    if not api_port or not ui_port:
        print(bad("no free ports"))
        return 1

    logs = Path("/tmp/cockpit_v4_browser_logs")
    logs.mkdir(parents=True, exist_ok=True)
    api_proc = ui_proc = None

    try:
        heading("V4 stub API")
        api_log = (logs / "api.log").open("w", encoding="utf-8")
        api_proc = subprocess.Popen(
            [sys.executable, "scripts/cockpit_v4/stub_server.py",
             "--port", str(api_port), "--ui-port", str(ui_port)],
            cwd=str(ROOT),
            env={**os.environ, "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4",
                 "PYTHONPATH": str(ROOT)},
            stdout=api_log, stderr=subprocess.STDOUT, start_new_session=True)
        healthy, detail = wait_for_json_health(
            f"http://127.0.0.1:{api_port}/health", timeout_seconds=90)
        if not healthy:
            print(bad(f"the stub API did not start: {detail}"))
            print((logs / "api.log").read_text()[-2000:])
            return 1
        print(ok(f"stub API on http://127.0.0.1:{api_port}"))

        heading("V4 UI")
        ui_log = (logs / "ui.log").open("w", encoding="utf-8")
        # Exactly the environment the launcher gives the real UI process.
        ui_env = ui_environment({**os.environ}, api_port=api_port,
                                ui_port=ui_port)
        ui_proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(ui_port),
             "--hostname", "127.0.0.1"],
            cwd=str(ROOT / "frontend"), env=ui_env,
            stdout=ui_log, stderr=subprocess.STDOUT, start_new_session=True)
        ready, detail = wait_for_ui_ready(f"http://127.0.0.1:{ui_port}/",
                                          timeout_seconds=240)
        if not ready:
            print(bad(f"the UI did not become ready: {detail}"))
            print((logs / "ui.log").read_text()[-3000:])
            return 1
        print(ok(f"UI on http://127.0.0.1:{ui_port} ({detail})"))
        print(f"  NEXT_PUBLIC_COCKPIT_V4_API="
              f"{ui_env['NEXT_PUBLIC_COCKPIT_V4_API']}")
        print(f"  NEXT_PUBLIC_API_URL={ui_env['NEXT_PUBLIC_API_URL']}")

        heading("Browser suite")
        evidence = ROOT / "docs" / "cockpit_v4" / "evidence" / "browser.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        suite = subprocess.run(
            ["node", "tests/cockpit_v4/browser/cockpit_v4.browser.mjs"],
            cwd=str(ROOT),
            env={**os.environ,
                 "V4_UI_URL": f"http://127.0.0.1:{ui_port}",
                 "V4_API_URL": f"http://127.0.0.1:{api_port}",
                 "V4_CHROME": CHROME,
                 "V4_BROWSER_EVIDENCE": str(evidence),
                 "V4_BROWSER_SCREENSHOT": str(
                     evidence.parent / "cockpit_v4_answer.png")})
        if args.keep_up:
            print(f"\n  left running: UI http://127.0.0.1:{ui_port} · "
                  f"API http://127.0.0.1:{api_port}")
            api_proc = ui_proc = None
        return suite.returncode
    finally:
        stop(ui_proc, "UI")
        stop(api_proc, "stub API")


if __name__ == "__main__":
    raise SystemExit(main())
