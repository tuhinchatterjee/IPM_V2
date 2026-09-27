"""
Re-evaluate a SAVED comparison over its stored evidence, and show before vs
after. Calls no model and opens no network connection: it reads the lab
store and the lab-owned frozen-format run store, writes a new evaluation
revision (the old one is kept as SUPERSEDED), and prints the differences.

    python scripts/model_lab/reevaluate.py --comparison cmp-f364d8b6901a
    python scripts/model_lab/reevaluate.py --comparison ID --runtime-dir DIR
    python scripts/model_lab/reevaluate.py --comparison ID --export

A saved agreement reference (the spec's `reference_comparison_id`, or
`--reference` as an operator override) is resolved READ-ONLY: the reference
comparison's evaluations, events and runs are checked unchanged afterwards.
`--export` rebuilds the evidence pack from the new evaluation, offline.
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


def ref_state(body: dict | None) -> dict:
    if not body:
        return {}
    r = body.get("saved_reference")
    if r is None and body.get("reference_baseline"):
        old = body["reference_baseline"]
        r = {"reference_comparison_id": old.get("comparison_id"),
             "reference_status": f"LEGACY_{old.get('status')}",
             "reference_profile_id": old.get("profile_id"),
             "reference_evaluation_revision": old.get("saved_revision")}
    r = r or {"reference_status": "NO_REFERENCE"}
    return {"status": r.get("reference_status"),
            "comparison": r.get("reference_comparison_id"),
            "profile": r.get("reference_profile_id"),
            "revision": r.get("reference_evaluation_revision"),
            "remedy": r.get("remedy") or ""}


def ref_match(body: dict | None) -> dict[str, dict]:
    out = {}
    for k in (body or {}).get("children") or []:
        m = k.get("reference_match") or {}
        out[k["child_run_id"]] = {s: v.get("display") for s, v in m.items()}
    return out


def _counts(svc, cid: str, tenant: str) -> dict:
    st = svc.coord.store
    return {"evaluations": len(st.evaluation_history(cid, tenant)),
            "events": len(st.events(cid, tenant, 0, 10 ** 7)),
            "child_runs": sum(len(st.child_runs(c["child_run_id"]))
                              for c in st.children(cid))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--comparison", required=True)
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    ap.add_argument("--tenant", default="",
                    help="owner scope; defaults to the scope the comparison "
                         "was saved under")
    ap.add_argument("--reference", default=None,
                    help="saved comparison to use as the agreement reference "
                         "when the spec names none (recorded as an operator "
                         "override; read-only)")
    ap.add_argument("--export", action="store_true",
                    help="rebuild the evidence pack from the new evaluation "
                         "(offline)")
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
    spec = svc.coord._spec(args.comparison)
    ref_id = args.reference or spec.get("reference_comparison_id")
    ref_before = (_counts(svc, ref_id, cfg.tenant_id)
                  if ref_id and svc.coord.store.get_comparison(
                      ref_id, cfg.tenant_id) else None)
    cand_runs = _counts(svc, args.comparison, cfg.tenant_id)["child_runs"]
    after = svc.evaluate(args.comparison, reference_override=args.reference)
    runs_after = svc.coord.runs._connect().execute(
        "SELECT COUNT(*) FROM runs").fetchone()[0]
    ref_after = (_counts(svc, ref_id, cfg.tenant_id)
                 if ref_before is not None else None)
    cand_runs_after = _counts(svc, args.comparison,
                              cfg.tenant_id)["child_runs"]
    b = summary(before["body"]) if before else {}
    a = summary(after)
    print(f"comparison {args.comparison}: evaluation r"
          f"{before['revision'] if before else '-'} -> r{after['revision']}"
          f" ({after['evaluator_version']}); model/engine runs before "
          f"{runs_before}, after {runs_after} (no inference)")
    rb, ra = ref_state(before["body"] if before else None), ref_state(after)
    print(f"live comparator: {after['comparator']['profile_id'] or 'none'} "
          f"({after['comparator']['status']})")
    print(f"saved reference: {rb.get('status')} -> {ra['status']} "
          f"({ra['comparison']}, {ra['profile']}, evaluation "
          f"r{ra['revision']})" + (f"  remedy: {ra['remedy']}"
                                   if ra["remedy"] else ""))
    mb, ma = ref_match(before["body"] if before else None), ref_match(after)
    for cid, now in ma.items():
        print(f"  reference_match {cid}: before {json.dumps(mb.get(cid))}"
              f"  after {json.dumps(now)}")
    unchanged = (ref_before == ref_after
                 and cand_runs == cand_runs_after)
    if ref_before is not None:
        print(f"reference {ref_id} untouched: {ref_before == ref_after} "
              f"({ref_after})")
    for cid, now in a.items():
        was = b.get(cid, {})
        print(f"\n== {now['model']} ({cid})")
        for key in ("stages", "claims", "claim_references",
                    "calls_without_tools", "failures"):
            mark = "" if was.get(key) == now[key] else "   <- changed"
            print(f"  {key:20} before {json.dumps(was.get(key))}")
            print(f"  {'':20} after  {json.dumps(now[key])}{mark}")
    if args.export:
        res = svc.export(args.comparison)
        print(f"\nexport {res['state']}: {res.get('path')} "
              f"sha256={res.get('sha256')} (export r{res.get('revision')})")
    return 0 if runs_before == runs_after and unchanged else 1


if __name__ == "__main__":
    sys.exit(main())
