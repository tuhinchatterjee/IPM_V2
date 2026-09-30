"""
OPUS_REFERENCE_SET_V1: preflight, build, verify, import. One saved Opus
comparison per benchmark question Q01-Q15; candidates are compared with it
(agreement only) and never trigger an Opus call themselves.

    python scripts/model_lab/opus_reference_set.py preflight   # default
    python scripts/model_lab/opus_reference_set.py verify
    python scripts/model_lab/opus_reference_set.py build --confirm-paid-opus-calls
    python scripts/model_lab/opus_reference_set.py import-runtime --from DIR

preflight / verify make NO model call. They search the lab store, reuse a
valid existing Opus comparison (exact question, same data snapshot, same
frozen source, Opus completed, compatible evaluation, intact records),
persist the set and print what is still missing and the spend a build would
reserve. build makes AT MOST one frozen-provider Opus run per missing
question, only with --confirm-paid-opus-calls, only when the operator's
opus_spend approval covers the full reserve for every missing question, and
only when COCKPIT_ANTHROPIC_API_KEY is present in the runtime environment
(presence is checked; the value is never read into output, the set or the
trace). It never raises the approval.

Exit codes: 0 all 15 READY; 3 references missing (nothing called);
4 OPUS_SPEND_APPROVAL_REQUIRED; 5 key or profile not ready; 6 build ended
with references still not READY; 2 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"


def _svc(runtime: Path, svc=None):
    if svc is not None:
        return svc
    from backend.model_lab.service import LabService, default_config
    return LabService(default_config(runtime))


def _money(x: float | None) -> str:
    return "none" if x is None else f"${x:.2f}"


def print_status(doc: dict[str, Any], pre: dict[str, Any], path: Path
                 ) -> None:
    from backend.model_lab import opus_references as orf
    print(f"{orf.SET_ID}  ({path})")
    for r in orf.status_rows(doc):
        print(f"  {r['question_id']}  {r['state']:17} "
              f"{r['reference_comparison_id'] or '-':18} {r['reason'][:90]}")
    print(f"existing_valid: {len(pre['existing_valid'])} "
          f"{','.join(pre['existing_valid']) or '-'}")
    print(f"missing: {len(pre['missing'])} {','.join(pre['missing']) or '-'}")
    if pre["blocked_needs_operator"]:
        print(f"invalid_or_failed (operator decision): "
              f"{','.join(pre['blocked_needs_operator'])}")
    print(f"current_approval_cap: {_money(pre['current_cap_usd'])} "
          f"({orf.APPROVAL_KEY})")
    print(f"spent_under_current_approval: "
          f"{_money(pre['spent_under_current_approval_usd'])}")
    print(f"available_approved_spend: {_money(pre['available_usd'])}")
    print(f"estimated_required_cap: {_money(pre['required_cap_usd'])} "
          f"({len(pre['missing'])} x {_money(pre['reserve_per_reference_usd'])}"
          f" reserved maximum per reference)")
    print(f"{pre['key_env']}: {'present' if pre['key_present'] else 'absent'}"
          f" (value never printed)")
    for q, c in pre["known_prior"].items():
        print(f"  note: prior Opus evidence for {q} is {c} on another "
              f"runtime; import that runtime (import-runtime --from DIR) "
              f"and it is reused iff it verifies here "
              f"(then {_money(pre['required_cap_usd'] - pre['reserve_per_reference_usd'])} "
              f"would be required)")


def approval_required(pre: dict[str, Any], targets: list[str],
                      required: float) -> None:
    print("OPUS_SPEND_APPROVAL_REQUIRED")
    print(f"required_cap_usd: {required:.2f}")
    cap, avail = pre["current_cap_usd"], pre["available_usd"]
    print(f"current_cap_usd: {'none' if cap is None else f'{cap:.2f}'}")
    print(f"available_usd: {'none' if avail is None else f'{avail:.2f}'}")
    print(f"missing_questions: {','.join(targets)}")
    print("No Opus call was made. Grant a cap that covers every missing "
          "reference, then build:")
    print(f"  python scripts/model_lab/approve.py grant opus_spend "
          f"--cap-usd {required:.2f}")


def cmd_resolve(args, svc, *, write: bool = True) -> tuple[dict, dict, Path]:
    from backend.model_lab import opus_references as orf
    from backend.model_lab import registry

    directory = Path(args.set_dir) if args.set_dir else None
    path = orf.set_path(directory)
    doc = orf.load(path)
    if args.allow_fixture_reference:
        doc["fixture_references_allowed"] = True
    orf.resolve(svc.coord, doc, directory=directory,
                allow_fixture=args.allow_fixture_reference)
    if write:
        orf.save(doc, path)
    pre = orf.spend_preflight(doc, registry.load_approvals(
        svc.cfg.runtime_dir), env=args.env)
    return doc, pre, path


def cmd_build(args, svc) -> int:
    from backend.model_lab import opus_references as orf
    from backend.model_lab import registry

    doc, pre, path = cmd_resolve(args, svc)
    print_status(doc, pre, path)
    states = {q: e.get("state") for q, e in doc["questions"].items()}
    targets = [q for q, s in sorted(states.items())
               if s == orf.MISSING
               or (s == orf.REFERENCE_FAILED and args.retry_failed)
               or (s == orf.INVALID and args.replace_invalid)]
    if args.question:
        targets = [q for q in targets if q in args.question]
    if not targets:
        print("nothing to build: no Opus call made")
        return 0 if pre["all_ready"] else 6
    if not args.confirm_paid_opus_calls:
        print("refusing: build makes paid Opus calls; pass "
              "--confirm-paid-opus-calls (no call made)")
        return 2
    reserve = pre["reserve_per_reference_usd"]
    required = round(len(targets) * reserve, 2)
    if pre["available_usd"] is None or \
            pre["available_usd"] + 1e-9 < required:
        approval_required(pre, targets, required)
        return 4
    prof = svc.coord.profiles.get(orf.REFERENCE_PROFILE)
    if prof is None:
        print(f"refusing: profile {orf.REFERENCE_PROFILE} is not registered")
        return 5
    if prof.route == "anthropic" and not pre["key_present"]:
        print(f"OPUS_KEY_REQUIRED: {orf.KEY_ENV} is not present in the "
              f"runtime environment (inject it as a secret; never on the "
              f"command line). No Opus call was made.")
        return 5
    ready = registry.readiness(prof, approvals=registry.load_approvals(
        svc.cfg.runtime_dir), env=args.env)
    if ready.status not in registry.RUNNABLE:
        print(f"refusing: {orf.REFERENCE_PROFILE} is {ready.status}: "
              f"{'; '.join(ready.reasons)} (no Opus call made)")
        return 5
    grant = registry.load_approvals(svc.cfg.runtime_dir)[orf.APPROVAL_KEY]
    directory = Path(args.set_dir) if args.set_dir else None
    from backend.model_lab.coordinator import PER_CHILD_RESERVE_USD
    for qid in targets:
        pre = orf.spend_preflight(doc, registry.load_approvals(
            svc.cfg.runtime_dir), env=args.env)
        if pre["available_usd"] is None or \
                pre["available_usd"] + 1e-9 < reserve:
            left = [q for q in targets
                    if doc["questions"][q].get("state") != orf.READY]
            approval_required(pre, left, round(len(left) * reserve, 2))
            orf.save(doc, path)
            return 4
        e = doc["questions"][qid]
        q = orf.bq.get(qid)
        cid = e.get("pending_comparison_id")
        if not cid:
            attempt = len(e.get("attempts") or []) + 1
            req = {"question": q.text,
                   "profile_ids": [orf.REFERENCE_PROFILE],
                   "comparator_id": orf.REFERENCE_PROFILE,
                   "lane": "FROZEN_BASELINE", "benchmark_question_id": qid,
                   "group_spend_cap_usd": PER_CHILD_RESERVE_USD,
                   "group_wall_clock_s": 3600,
                   "label": f"{orf.SET_ID} {qid} (Opus reference)"}
            st = svc.coord.create(
                req, idempotency_key=f"{orf.SET_ID}:{qid}:attempt-{attempt}")
            cid = st["comparison_id"]
            e["pending_comparison_id"] = cid
            e.setdefault("attempts", []).append(
                {"attempt": attempt, "comparison_id": cid,
                 "started_at": time.time()})
            orf.save(doc, path)           # a crash resumes this comparison
            print(f"  {qid}: Opus reference run {cid} started")
        svc.coord.wait(cid, timeout=3900)
        spend = svc.coord._group_spend(cid)
        doc.setdefault("spend_ledger", []).append({
            "question_id": qid, "comparison_id": cid,
            "spend_usd": round(float(spend["committed_usd"]) +
                               float(spend["pending_usd"]), 6),
            "uncertain": spend["uncertain"],
            "approval_granted_at": grant.get("granted_at"),
            "recorded_at": time.time()})
        if svc.coord.store.current_evaluation(cid, svc.cfg.tenant_id) is None:
            svc.evaluate(cid)
        v = orf.verify_comparison(svc.coord, cid, qid,
                                  allow_fixture=args.allow_fixture_reference)
        e.pop("pending_comparison_id", None)
        if v["ok"]:
            rec = orf.record(svc.coord, qid, v, reused=False,
                             directory=directory)
            exp = svc.coord.store.latest_export(cid, svc.cfg.tenant_id)
            if exp and exp.get("path"):
                rec["export_pack"] = {"path": exp["path"],
                                      "sha256": exp.get("sha256")}
            rec["attempts"] = e.get("attempts")
            doc["questions"][qid] = rec
            print(f"  {qid}: READY {cid}")
        else:
            e.update(state=orf.REFERENCE_FAILED, reference_comparison_id=cid,
                     failure=f"{v['status']}: {v['reason']}")
            print(f"  {qid}: REFERENCE_FAILED {cid} {v['status']} "
                  f"(no automatic retry; --retry-failed is an explicit "
                  f"operator decision)")
        orf.save(doc, path)
    pre = orf.spend_preflight(doc, registry.load_approvals(
        svc.cfg.runtime_dir), env=args.env)
    print_status(doc, pre, path)
    return 0 if pre["all_ready"] else 6


def cmd_import(args, runtime: Path) -> int:
    """Seed an EMPTY runtime with another runtime's saved comparisons (for
    example the Mac runtime holding the Q01 Opus run), so that they can be
    verified and reused. Approvals, probes, pins, logs and process files
    are never copied."""
    src = Path(args.from_dir).expanduser().resolve()
    if not (src / "lab_index.sqlite3").exists():
        print(f"refusing: {src} has no lab_index.sqlite3")
        return 2
    runtime.mkdir(parents=True, exist_ok=True)
    idx = runtime / "lab_index.sqlite3"
    if idx.exists():
        n = sqlite3.connect(idx).execute(
            "SELECT COUNT(*) FROM comparisons").fetchone()[0]
        if n:
            print(f"refusing: {runtime} already holds {n} comparisons; "
                  f"import only into an empty runtime")
            return 2
    for name in ("lab_index.sqlite3", "lab_runs.sqlite3"):
        if (src / name).exists():
            s, d = sqlite3.connect(src / name), sqlite3.connect(
                runtime / name)
            s.backup(d)
            s.close()
            d.close()
    for name in ("blobs", "frozen", "exports"):
        if (src / name).is_dir():
            shutil.copytree(src / name, runtime / name, dirs_exist_ok=True)
    print(f"imported comparisons from {src} into {runtime} (approvals, "
          f"probes, pins and logs NOT copied). Next: preflight")
    return 0


def main(argv: list[str] | None = None, *, svc=None,
         env: dict[str, str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("command", nargs="?", default="preflight",
                    choices=("preflight", "verify", "build",
                             "import-runtime"))
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    ap.add_argument("--set-dir", help="directory holding the set "
                    "(default artifacts/model_comparison/reference_sets)")
    ap.add_argument("--confirm-paid-opus-calls", action="store_true")
    ap.add_argument("--question", action="append",
                    help="build only these question ids")
    ap.add_argument("--retry-failed", action="store_true",
                    help="operator decision: rebuild REFERENCE_FAILED ones")
    ap.add_argument("--replace-invalid", action="store_true",
                    help="operator decision: rebuild INVALID ones")
    ap.add_argument("--from", dest="from_dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow-fixture-reference", action="store_true",
                    help=argparse.SUPPRESS)      # offline tests only
    args = ap.parse_args(argv)
    args.env = os.environ if env is None else env
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
    runtime = Path(args.runtime_dir).expanduser().resolve()
    if args.command == "import-runtime":
        if not args.from_dir:
            ap.error("import-runtime needs --from DIR")
        return cmd_import(args, runtime)
    svc = _svc(runtime, svc)
    if args.command == "build":
        return cmd_build(args, svc)
    print("OPUS REFERENCE PREFLIGHT (no model call)")
    doc, pre, path = cmd_resolve(args, svc)
    if args.json:
        print(json.dumps({"set": doc, "preflight": pre}, indent=1,
                         default=str))
    print_status(doc, pre, path)
    if pre["all_ready"]:
        print(f"OPUS REFERENCE SET READY: {len(pre['existing_valid'])}/15")
        return 0
    if pre["missing"]:
        req = pre["required_cap_usd"]
        if not pre["approval_sufficient"]:
            approval_required(pre, pre["missing"], req)
        elif not pre["key_present"]:
            print(f"OPUS_KEY_REQUIRED: inject {pre['key_env']} into the "
                  f"runtime environment before building")
        else:
            print("approved spend and key are available; build explicitly "
                  "(paid, one Opus run per missing question):")
            print(f"  python scripts/model_lab/opus_reference_set.py build "
                  f"--runtime-dir {runtime} --confirm-paid-opus-calls")
    return 3


if __name__ == "__main__":
    sys.exit(main())
