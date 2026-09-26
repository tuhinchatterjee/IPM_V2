#!/usr/bin/env python3
"""Run the LIVE-PROVIDER UAT, or refuse and say why.

The mock journeys (`browser_evidence.py`) prove the path: a typed question
reaches the engine and its result comes back. They cannot prove the
translation, because the analyst's tool calls are written rather than
generated. This runs the same product with a REAL provider and asks the one
question the mock journeys cannot: does arbitrary natural language become the
correct governed deterministic scenario contract?

IT REFUSES RATHER THAN SUBSTITUTES. Without a credential this exits non-zero
and prints what is missing. It never falls back to the stub server, because
evidence labelled "live" over journeys that were not is worse than no evidence
at all.

THE KEY IS NEVER PRINTED, LOGGED OR WRITTEN. Only
`service.credential_status()`'s PRESENT / MISSING reaches the output or the
evidence file.

    export COCKPIT_ANTHROPIC_API_KEY='...'        # in your shell, not here
    .venv-whatif/bin/python scripts/whatif/live_uat.py

Measured on GENERATED books. Nothing it produces is bank output, an accounting
figure, or a bank-validated model.
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
from scripts.cockpit_v4.browser_evidence import CHROME, stop  # noqa: E402
from scripts.cockpit_v4.start import ui_environment  # noqa: E402

CANDIDATE_PYTHON = ROOT / ".venv-whatif" / "bin" / "python"


def credential_present() -> bool:
    from backend.cockpit_v4 import service

    return service.credential_status() == "PRESENT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="",
                        help="a regex over journey ids, e.g. 'L5|L6'")
    parser.add_argument("--keep-up", action="store_true")
    args = parser.parse_args()

    heading("LIVE-PROVIDER UAT · L1-L8")
    from backend.cockpit_v4 import config as config_mod

    if not CANDIDATE_PYTHON.exists():
        print(bad(f"{CANDIDATE_PYTHON} is absent. Build the candidate "
                  f"environment first."))
        return 1
    if not credential_present():
        print(bad(
            f"NO PROVIDER CREDENTIAL. {config_mod.CREDENTIAL_VAR} is not set "
            f"in this environment, so there is no live model to drive.\n\n"
            f"This gate is BLOCKED, not failed, and it is not run against a "
            f"stub: a suite that quietly substituted a scripted analyst "
            f"would write evidence saying LIVE over journeys that were not.\n\n"
            f"To run it:\n"
            f"    export {config_mod.CREDENTIAL_VAR}='...'\n"
            f"    .venv-whatif/bin/python scripts/whatif/live_uat.py\n\n"
            f"See docs/whatif/LIVE_PROVIDER_UAT.md."))
        return 2
    print(ok(f"provider credential PRESENT ({config_mod.CREDENTIAL_VAR}); "
             f"the key itself is not read by this script"))

    api_port, api_notes = pick_port(8434)
    ui_port, ui_notes = pick_port(5434)
    for note in (*api_notes, *ui_notes):
        print(warn(note))

    logs = ROOT / "docs" / "whatif" / "evidence" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    api_log = (logs / "live-api.log").open("w", encoding="utf-8")
    ui_log = (logs / "live-ui.log").open("w", encoding="utf-8")
    api_proc = ui_proc = None

    # THE REAL APP, not the stub. `backend.main:app` resolves a real provider
    # through `service.resolve_provider`, so the analyst here is a model.
    child = {**os.environ,
             "COCKPIT_V4_WHATIF_CORPORATE": "1",
             "COCKPIT_V4_WHATIF_RETAIL": "1",
             "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4",
             "COCKPIT_V4_DB": str(ROOT / ".cockpit_v4_live_uat.db"),
             "PYTHONPATH": str(ROOT)}
    try:
        api_proc = subprocess.Popen(
            [str(CANDIDATE_PYTHON), "-m", "uvicorn", "backend.main:app",
             "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=str(ROOT), env=child, stdout=api_log,
            stderr=subprocess.STDOUT, start_new_session=True)
        ready, detail = wait_for_json_health(
            f"http://127.0.0.1:{api_port}/api/v1/cockpit-v4/domains",
            timeout_seconds=240)
        if not ready:
            print(bad(f"the live API did not come up: {detail}"))
            print((logs / "live-api.log").read_text()[-3000:])
            return 1
        print(ok(f"API on http://127.0.0.1:{api_port} (REAL PROVIDER)"))

        ui_env = ui_environment({**child}, api_port=api_port, ui_port=ui_port)
        ui_proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(ui_port),
             "--hostname", "127.0.0.1"],
            cwd=str(ROOT / "frontend"), env=ui_env, stdout=ui_log,
            stderr=subprocess.STDOUT, start_new_session=True)
        ready, detail = wait_for_ui_ready(f"http://127.0.0.1:{ui_port}/",
                                          timeout_seconds=300)
        if not ready:
            print(bad(f"the UI did not become ready: {detail}"))
            return 1
        print(ok(f"UI on http://127.0.0.1:{ui_port} ({detail})"))
        for note in warm_routes(f"http://127.0.0.1:{ui_port}",
                                ("/", "/cockpit/thread/warmup")):
            print(f"  warmed {note}")

        heading("L1-L8 · REAL PROVIDER")
        suite = subprocess.run(
            ["node", "tests/cockpit_v4/browser/whatif.live.mjs"],
            cwd=str(ROOT),
            env={**os.environ,
                 "WHATIF_LIVE": "1",
                 "WHATIF_UI_URL": f"http://127.0.0.1:{ui_port}",
                 "WHATIF_API_URL": f"http://127.0.0.1:{api_port}",
                 "WHATIF_ONLY": args.only,
                 "WHATIF_SHOTS": str(
                     ROOT / "docs" / "whatif" / "evidence" / "live"),
                 "V4_CHROME": CHROME})
        if args.keep_up:
            print(f"\n  left running: UI http://127.0.0.1:{ui_port} · "
                  f"API http://127.0.0.1:{api_port}")
            api_proc = ui_proc = None
        return suite.returncode
    finally:
        stop(ui_proc, "live UI")
        stop(api_proc, "live API")
        api_log.close()
        ui_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
