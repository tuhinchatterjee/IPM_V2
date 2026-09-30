#!/usr/bin/env python3
"""Bring up the Guided Workspace stack and run its browser journeys in real Chromium.

MODEL MOCK: the analyst is scripted (`gw_stub_server.py`); UI, API, stores,
worker, engine and books are real. Reuses the accepted runner's helpers so the
UI is brought up the same way the accepted and What-If suites bring it up.

Usage:
    python3 scripts/guided_workspace/browser_evidence.py [--only REGEX] [--keep-up]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.cockpit_v4._common import (  # noqa: E402
    bad,
    heading,
    ok,
    pick_port,
    wait_for_json_health,
    wait_for_ui_ready,
    warm_routes,
    warn,
)
from scripts.cockpit_v4.browser_evidence import CHROME, stale_next_dev, stop  # noqa: E402
from scripts.cockpit_v4.start import ui_environment  # noqa: E402

CANDIDATE_PYTHON = ROOT / ".venv-whatif" / "bin" / "python"
EVIDENCE = ROOT / "docs" / "guided_workspace" / "evidence"
WARM = ("/", "/cockpit/thread/warmup", "/cockpit/trace/warmup",
        "/trace/llm-exchange/warmup", "/ai-model-lab", "/what-if",
        "/lenses", "/monitoring", "/metrics", "/messages", "/early-warning")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="")
    parser.add_argument("--keep-up", action="store_true")
    args = parser.parse_args()
    heading("Guided Risk Workspace journeys · MODEL MOCK")
    api_port, notes_a = pick_port(8444)
    ui_port, notes_u = pick_port(5444)
    for note in (*notes_a, *notes_u):
        print(warn(note))
    logs = EVIDENCE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    runtime = Path("/tmp") / f"cockpit_v4_gw_{api_port}"
    runtime.mkdir(parents=True, exist_ok=True)
    api_log = (logs / "api.log").open("w", encoding="utf-8")
    ui_log = (logs / "ui.log").open("w", encoding="utf-8")
    api_proc = ui_proc = None
    try:
        api_proc = subprocess.Popen(
            [str(CANDIDATE_PYTHON), "scripts/guided_workspace/gw_stub_server.py",
             "--port", str(api_port), "--ui-port", str(ui_port),
             "--runtime-dir", str(runtime)],
            cwd=str(ROOT), stdout=api_log, stderr=subprocess.STDOUT,
            start_new_session=True)
        ready, detail = wait_for_json_health(
            f"http://127.0.0.1:{api_port}/api/v1/cockpit-v4/domains",
            timeout_seconds=240)
        if not ready:
            print(bad(f"the API did not come up: {detail}"))
            print((logs / "api.log").read_text()[-3000:])
            return 1
        print(ok(f"API on http://127.0.0.1:{api_port}"))
        ui_env = ui_environment({**os.environ}, api_port=api_port,
                                ui_port=ui_port)
        ui_env["NEXT_PUBLIC_GUIDED_WORKSPACE"] = "1"

        def start_ui():
            return subprocess.Popen(
                ["npm", "run", "dev", "--", "--port", str(ui_port),
                 "--hostname", "127.0.0.1"],
                cwd=str(ROOT / "frontend"), env=ui_env, stdout=ui_log,
                stderr=subprocess.STDOUT, start_new_session=True)

        ui_proc = start_ui()
        ready, detail = wait_for_ui_ready(f"http://127.0.0.1:{ui_port}/",
                                          timeout_seconds=300)
        if not ready:
            stale = stale_next_dev(ROOT / "frontend")
            if stale:
                print(warn(f"a leftover next dev (pid {stale}) held the tree; "
                           f"stopping it and retrying once"))
                stop(None, "leftover next dev", pid=stale)
                ui_proc = start_ui()
                ready, detail = wait_for_ui_ready(
                    f"http://127.0.0.1:{ui_port}/", timeout_seconds=300)
        if not ready:
            print(bad(f"the UI did not become ready: {detail}"))
            print((logs / "ui.log").read_text()[-3000:])
            return 1
        print(ok(f"UI on http://127.0.0.1:{ui_port}"))
        for note in warm_routes(f"http://127.0.0.1:{ui_port}", WARM):
            print(f"  warmed {note}")
        suite = subprocess.run(
            ["node", "tests/guided_workspace/browser/gw.browser.mjs"],
            cwd=str(ROOT),
            env={**os.environ,
                 "GW_UI_URL": f"http://127.0.0.1:{ui_port}",
                 "GW_API_URL": f"http://127.0.0.1:{api_port}",
                 "GW_SHOTS": str(EVIDENCE / "journeys"),
                 "GW_EVIDENCE": str(EVIDENCE / "journeys.json"),
                 "GW_ONLY": args.only, "V4_CHROME": CHROME})
        if args.keep_up:
            print(f"\n  left running: UI http://127.0.0.1:{ui_port} · API "
                  f"http://127.0.0.1:{api_port}")
            api_proc = ui_proc = None
        return suite.returncode
    finally:
        stop(ui_proc, "UI")
        stop(api_proc, "guided-workspace stub API")
        api_log.close()
        ui_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
