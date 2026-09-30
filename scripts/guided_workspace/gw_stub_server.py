#!/usr/bin/env python3
"""The real V4 stack with every Guided Workspace flag on, and a scripted analyst.

MODEL MOCK, labelled as such wherever its results are reported. Everything but
`converse` is the product: routes, workspace routes, durable stores, worker,
supervisor, event stream, DuckDB over the published CANDIDATE books, the
scenario engine and the Full LLM Exchange recorder.

Flags set here, in this process only (never exported, never in a .env):

    COCKPIT_V4_WHATIF_CORPORATE=1  COCKPIT_V4_WHATIF_RETAIL=1
    COCKPIT_V4_GUIDED_WORKSPACE=1  COCKPIT_V4_LLM_EXCHANGE_TRACE=1

The scripted analyst is the What-If round's (`scripts/whatif/whatif_stub_server`)
extended by `guided_script.py`, so the accepted and What-If journey files are
untouched.

Usage:
    .venv-whatif/bin/python scripts/guided_workspace/gw_stub_server.py --port 8444
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "whatif"))
sys.path.insert(0, str(ROOT / "tests" / "cockpit_v4"))

os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
for flag in ("COCKPIT_V4_WHATIF_CORPORATE", "COCKPIT_V4_WHATIF_RETAIL",
             "COCKPIT_V4_GUIDED_WORKSPACE", "COCKPIT_V4_LLM_EXCHANGE_TRACE"):
    os.environ[flag] = "1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8444)
    parser.add_argument("--ui-port", type=int, default=0)
    parser.add_argument("--runtime-dir", default="")
    args = parser.parse_args()

    import uvicorn

    import whatif_stub_server as base

    runtime_dir = Path(args.runtime_dir or f"/tmp/cockpit_v4_gw_{args.port}")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    app = base.build_app(args.port, runtime_dir, domain_id="corporate",
                         ui_port=args.ui_port)
    print(f"guided-workspace stub V4 API on http://127.0.0.1:{args.port}",
          flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
