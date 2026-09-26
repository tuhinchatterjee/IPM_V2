#!/usr/bin/env python3
"""Bring up the What-If stack and run J01-J14 against real Chromium.

One book per run, because a thread is pinned to its book and a scenario is a
statement about one of them. `--domain all` runs both in sequence and writes
each book's evidence to its own file.

Reuses the accepted runner's helpers -- `pick_port`, `wait_for_ui_ready`,
`warm_routes`, `stale_next_dev`, `ui_environment` -- so the two suites bring
the UI up the same way and the lessons those functions encode (a leftover
`next dev` holds the working tree rather than the port; a cold bundler looks
exactly like a product timeout) are not learned twice.

It does NOT reuse the accepted stub server. Threading a second release and two
feature flags through the file the accepted 76 journeys depend on would put
the What-If work inside the evidence that the accepted application is
unchanged.

Usage:
    python3 scripts/whatif/browser_evidence.py --domain all
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

#: The candidate interpreter. The engine's ML half needs xgboost, lightgbm and
#: pandas, and the accepted environment has none of them and must not.
CANDIDATE_PYTHON = ROOT / ".venv-whatif" / "bin" / "python"

BOOKS = ("corporate", "retail")


def run_one(domain_id: str, *, keep_up: bool) -> int:
    heading(f"What-If journeys: {domain_id}")
    if not CANDIDATE_PYTHON.exists():
        print(bad(f"{CANDIDATE_PYTHON} is absent. Build it first:\n"
                  f"    python3 -m venv --system-site-packages .venv-whatif\n"
                  f"    .venv-whatif/bin/pip install --ignore-installed "
                  f"-r requirements-whatif.txt"))
        return 1

    # `pick_port` returns `(port, notes)`. The notes matter: the preferred
    # port is never freed, so a port already held by another CreditProbe is
    # stepped over and said so rather than taken.
    api_port, api_notes = pick_port(8424)
    ui_port, ui_notes = pick_port(5424)
    for note in (*api_notes, *ui_notes):
        print(warn(note))
    logs = ROOT / "docs" / "whatif" / "evidence" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    runtime = Path("/tmp") / f"cockpit_v4_whatif_{api_port}"
    runtime.mkdir(parents=True, exist_ok=True)

    api_log = (logs / f"api-{domain_id}.log").open("w", encoding="utf-8")
    ui_log = (logs / f"ui-{domain_id}.log").open("w", encoding="utf-8")
    api_proc = ui_proc = None
    try:
        api_proc = subprocess.Popen(
            [str(CANDIDATE_PYTHON), "scripts/whatif/whatif_stub_server.py",
             "--port", str(api_port), "--ui-port", str(ui_port),
             "--domain", domain_id, "--runtime-dir", str(runtime)],
            cwd=str(ROOT), stdout=api_log, stderr=subprocess.STDOUT,
            start_new_session=True)
        ready, detail = wait_for_json_health(
            f"http://127.0.0.1:{api_port}/api/v1/cockpit-v4/domains",
            timeout_seconds=180)
        if not ready:
            print(bad(f"the What-If API did not come up: {detail}"))
            print((logs / f"api-{domain_id}.log").read_text()[-3000:])
            return 1
        print(ok(f"API on http://127.0.0.1:{api_port} ({domain_id})"))

        ui_env = ui_environment({**os.environ}, api_port=api_port,
                                ui_port=ui_port)

        def start_ui():
            return subprocess.Popen(
                ["npm", "run", "dev", "--", "--port", str(ui_port),
                 "--hostname", "127.0.0.1"],
                cwd=str(ROOT / "frontend"), env=ui_env,
                stdout=ui_log, stderr=subprocess.STDOUT,
                start_new_session=True)

        ui_proc = start_ui()
        ready, detail = wait_for_ui_ready(f"http://127.0.0.1:{ui_port}/",
                                          timeout_seconds=300)
        if not ready:
            stale = stale_next_dev(ROOT / "frontend")
            if stale:
                print(warn(f"a leftover next dev (pid {stale}) held this "
                           f"working tree; stopping it and retrying once"))
                stop(None, "leftover next dev", pid=stale)
                ui_proc = start_ui()
                ready, detail = wait_for_ui_ready(
                    f"http://127.0.0.1:{ui_port}/", timeout_seconds=300)
        if not ready:
            print(bad(f"the UI did not become ready: {detail}"))
            print((logs / f"ui-{domain_id}.log").read_text()[-3000:])
            return 1
        print(ok(f"UI on http://127.0.0.1:{ui_port} ({detail})"))
        # Compiled before anything is asserted: a cold `next dev` bundler
        # looks exactly like a product that will not answer.
        for note in warm_routes(f"http://127.0.0.1:{ui_port}",
                                ("/", "/cockpit/thread/warmup",
                                 "/cockpit/trace/warmup")):
            print(f"  warmed {note}")

        heading(f"J01-J14 · {domain_id} · MODEL MOCK")
        shots = ROOT / "docs" / "whatif" / "evidence" / "journeys" / domain_id
        suite = subprocess.run(
            ["node", "tests/cockpit_v4/browser/whatif.browser.mjs"],
            cwd=str(ROOT),
            env={**os.environ,
                 "WHATIF_UI_URL": f"http://127.0.0.1:{ui_port}",
                 "WHATIF_API_URL": f"http://127.0.0.1:{api_port}",
                 "WHATIF_DOMAIN": domain_id,
                 "WHATIF_SHOTS": str(shots),
                 "V4_CHROME": CHROME})
        if keep_up:
            print(f"\n  left running: UI http://127.0.0.1:{ui_port} · "
                  f"API http://127.0.0.1:{api_port}")
            api_proc = ui_proc = None
        return suite.returncode
    finally:
        stop(ui_proc, "UI")
        stop(api_proc, "what-if stub API")
        api_log.close()
        ui_log.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="all",
                       choices=[*BOOKS, "all"])
    parser.add_argument("--keep-up", action="store_true")
    args = parser.parse_args()
    books = BOOKS if args.domain == "all" else (args.domain,)
    worst = 0
    for domain_id in books:
        code = run_one(domain_id, keep_up=args.keep_up)
        worst = worst or code
        if code:
            print(bad(f"{domain_id} journeys did not all pass"))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
