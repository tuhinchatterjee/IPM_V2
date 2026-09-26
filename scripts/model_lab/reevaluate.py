"""
Re-evaluate a SAVED comparison over its stored evidence, and show before vs
after. Calls no model and opens no network connection: it reads the lab
store and the lab-owned frozen-format run store, writes a new evaluation
revision (the old one is kept as SUPERSEDED), and prints the differences.

    python scripts/model_lab/reevaluate.py --comparison cmp-f364d8b6901a
    python scripts/model_lab/reevaluate.py --comparison ID --runtime-dir DIR
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"


def summary(body: dict) -> dict[str, dict]:
    out = {}
    for k in body.get("children") or []:
        out[k["child_run_id"]] = {
            "model": k.get("display_name") or k["profile_id"],
            "stages": {s: v["status"] for s, v in
                       (k.get("stages") or {}).items()},
            "claims": dict(Counter(c["verification_status"]
                                   for c in k.get("claims") or [])),
            "claim_references": {
                c["claim_id"]: [c["verification_status"],
                                c.get("reference_metric")]
                for c in k.get("claims") or []
                if c.get("claim_type") in ("numeric", "numeric_derived")},
            "calls_without_tools": sum(1 for c in k.get("calls") or []
                                       if c.get("stop_reason") == "tool_use"
                                       and not c.get("tool_names")),
            "failures": [f["primary_category"]
                         for f in k.get("failures") or []],
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--comparison", required=True)
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    ap.add_argument("--tenant", default="",
                    help="owner scope; defaults to the scope the comparison "
                         "was saved under")
    args = ap.parse_args(argv)
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")

    from backend.model_lab.service import LabService, default_config
    from backend.model_lab.store import LabStore

    runtime = Path(args.runtime_dir).expanduser().resolve()
    store = LabStore(runtime)
    rows = store._q("SELECT owner_scope FROM comparisons WHERE "
                    "comparison_id=?", (args.comparison,))
    if not rows:
        print(f"{args.comparison}: not found under {runtime}")
        return 2
    cfg = default_config(runtime)
    cfg.tenant_id = args.tenant or rows[0]["owner_scope"]
    # recover=False: re-evaluation must not touch any child's state.
    svc = LabService(cfg, recover=False)
    before = svc.coord.store.current_evaluation(args.comparison,
                                                cfg.tenant_id)
    runs_before = svc.coord.runs._connect().execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0]
    after = svc.evaluate(args.comparison)
    runs_after = svc.coord.runs._connect().execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0]
    b = summary(before["body"]) if before else {}
    a = summary(after)
    print(f"comparison {args.comparison}: evaluation r"
          f"{before['revision'] if before else '-'} -> r{after['revision']}"
          f" ({after['evaluator_version']}); model/engine runs before "
          f"{runs_before}, after {runs_after} (no inference)")
    for cid, now in a.items():
        was = b.get(cid, {})
        print(f"\n== {now['model']} ({cid})")
        for key in ("stages", "claims", "claim_references",
                    "calls_without_tools", "failures"):
            mark = "" if was.get(key) == now[key] else "   <- changed"
            print(f"  {key:20} before {json.dumps(was.get(key))}")
            print(f"  {'':20} after  {json.dumps(now[key])}{mark}")
    return 0 if runs_before == runs_after else 1


if __name__ == "__main__":
    sys.exit(main())
