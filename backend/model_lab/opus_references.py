"""
OPUS_REFERENCE_SET_V1: exactly one saved Opus comparison per benchmark
question (Q01-Q15), versioned, verified and read-only once used.

Three concepts stay apart:
- the INDEPENDENT ORACLE decides correctness;
- the SAVED OPUS REFERENCE is what a candidate's answer is compared with
  (agreement, never truth, never latency);
- a LIVE comparator child is not used by the benchmark at all.

This module never calls a model. It searches the lab store, verifies each
candidate reference (exact question text, same data snapshot, same frozen
source, Opus child completed, a compatible evaluation, intact records) and
persists the set. Building a MISSING reference is a separate, explicit,
spend-gated operator step (scripts/model_lab/opus_reference_set.py build).

Immutability: an entry that is READY is never replaced silently. If it
later fails verification it becomes INVALID with the reason, and only an
explicit operator flag rebuilds it.

Credentials: nothing here reads, prints or stores a provider key. The key
check reports presence only.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from backend.model_lab import EVALUATOR_VERSION, FROZEN_COMMIT
from backend.model_lab import benchmark_questions as bq

ROOT = Path(__file__).resolve().parents[2]
SET_ID = "OPUS_REFERENCE_SET_V1"
SET_SCHEMA = 1
DEFAULT_DIR = ROOT / "artifacts" / "model_comparison" / "reference_sets"
REFERENCE_PROFILE = "opus-frozen"
KEY_ENV = "COCKPIT_ANTHROPIC_API_KEY"
APPROVAL_KEY = "opus_spend"
#: Prior Opus evidence known to exist outside this store (the Mac runtime).
#: A hint for the operator only; it is reused solely after it verifies here.
KNOWN_PRIOR = {"Q01": "cmp-f364d8b6901a"}

READY, MISSING, INVALID = "READY", "MISSING", "INVALID"
REFERENCE_FAILED = "REFERENCE_FAILED"


def set_path(directory: Path | None = None) -> Path:
    return (directory or DEFAULT_DIR) / f"{SET_ID}.json"


def snapshot_dir(directory: Path | None = None) -> Path:
    return (directory or DEFAULT_DIR) / SET_ID


def _h(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str)
                          .encode()).hexdigest()


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def current_snapshot_id() -> str:
    from backend.model_lab.child_runtime import snapshot_identity
    return snapshot_identity(bq.DOMAIN)["data_snapshot_id"]


def oracle_version() -> dict[str, str]:
    from backend.model_lab import benchmark_oracles as bo
    return {"oracle_version": bo.ORACLE_SUITE_VERSION,
            "code_sha256": bo.code_sha256()}


def empty_set() -> dict[str, Any]:
    return {"set_id": SET_ID, "schema": SET_SCHEMA,
            "suite_version": bq.SUITE_VERSION,
            "profile_id": REFERENCE_PROFILE,
            "frozen_source_id": FROZEN_COMMIT,
            "evaluator_version": EVALUATOR_VERSION,
            "created_at": time.time(), "updated_at": time.time(),
            "semantics": "agreement reference only: Opus Match is agreement, "
                         "never truth; correctness is the independent "
                         "oracle; never latency or SLA",
            "questions": {q.qid: {"question_id": q.qid,
                                  "question_text": q.text, "state": MISSING}
                          for q in bq.QUESTIONS},
            "spend_ledger": []}


def load(path: Path | None = None) -> dict[str, Any]:
    p = path or set_path()
    if p.exists():
        return json.loads(p.read_text())
    return empty_set()


def save(doc: dict[str, Any], path: Path | None = None) -> Path:
    p = path or set_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, default=str))
    tmp.replace(p)
    return p


# ---- verification (read-only) ------------------------------------------------

def _opus_row(rows: list[dict]) -> dict | None:
    from backend.model_lab.evaluate import _is_opus_child
    return next((r for r in rows if _is_opus_child(r)), None)


def verify_comparison(coord, cid: str, qid: str, *,
                      snapshot_id: str | None = None,
                      allow_fixture: bool = False) -> dict[str, Any]:
    """Can saved comparison `cid` serve as the Opus reference for `qid`?

    Reads the lab index and the frozen run store; writes nothing. Returns
    {"ok": bool, "status": ..., "reason": ..., "facts": {...}}."""
    from backend.model_lab.evaluate import _REFERENCE_CHILD_KEYS, COMPATIBLE_REFERENCE_VERSIONS

    q = bq.get(qid)
    tenant = coord.cfg.tenant_id
    facts: dict[str, Any] = {"reference_comparison_id": cid}

    def no(status: str, reason: str) -> dict[str, Any]:
        return {"ok": False, "status": status, "reason": reason,
                "facts": facts}

    row = coord.store.get_comparison(cid, tenant)
    if row is None:
        return no("REFERENCE_COMPARISON_UNAVAILABLE",
                  f"{cid} is not saved in this lab store (owner scope "
                  f"{tenant})")
    try:
        spec = json.loads(row["spec_json"])
    except ValueError:
        return no("REFERENCE_CORRUPT", "the stored spec does not parse")
    recomputed = _h({k: v for k, v in spec.items()
                     if k not in ("created_at", "preflight",
                                  "comparison_id")})
    facts |= {"created_at": row["created_at"],
              "data_snapshot_id": spec.get("data_snapshot_id"),
              "frozen_source_id": spec.get("frozen_source_id"),
              "question_text": spec.get("question_text"),
              "spec_hash": row["spec_hash"]}
    if recomputed != row["spec_hash"]:
        return no("REFERENCE_CORRUPT", "spec_hash does not match the stored "
                  "spec (checksum mismatch)")
    if spec.get("question_text") != q.text:
        return no("REFERENCE_NOT_COMPARABLE", "the question text is not "
                  "exactly the benchmark question")
    snap = snapshot_id or current_snapshot_id()
    if spec.get("data_snapshot_id") != snap:
        return no("REFERENCE_NOT_COMPARABLE", f"data snapshot "
                  f"{spec.get('data_snapshot_id')} != {snap}")
    if spec.get("frozen_source_id") != FROZEN_COMMIT:
        return no("REFERENCE_NOT_COMPARABLE", f"frozen source "
                  f"{spec.get('frozen_source_id')} != {FROZEN_COMMIT}")
    if (spec.get("lane") or "FROZEN_BASELINE") != "FROZEN_BASELINE":
        return no("REFERENCE_NOT_COMPARABLE", "an Opus reference must run "
                  "the unchanged frozen request (FROZEN_BASELINE)")
    opus = _opus_row(coord.store.children(cid))
    if opus is None:
        return no("REFERENCE_HAS_NO_OPUS_CHILD", "no opus-frozen child")
    prof = json.loads(opus.get("profile_json") or "{}")
    is_fixture = prof.get("role") == "fixture" or prof.get("route") == \
        "fixture"
    facts |= {"opus_child_run_id": opus["child_run_id"],
              "profile_id": opus["profile_id"],
              "model_id": (prof.get("endpoint") or {}).get("model") or
              prof.get("registry_id") or prof.get("profile_id"),
              "route": prof.get("route"), "reference_is_fixture": is_fixture}
    if is_fixture and not allow_fixture:
        return no("REFERENCE_IS_FIXTURE", "a fixture stands in for Opus; "
                  "not a real Opus reference")
    if opus["state"] != "COMPLETED":
        return no("REFERENCE_OPUS_NOT_COMPLETED",
                  f"the Opus child is {opus['state']}")
    runs = coord.store.child_runs(opus["child_run_id"])
    if not runs or any(coord.runs.get_run(r["run_id"]) is None
                       for r in runs):
        return no("REFERENCE_CORRUPT", "a frozen engine run record of the "
                  "Opus child is missing")
    cur = coord.store.current_evaluation(cid, tenant)
    if cur is None:
        return no("REFERENCE_NOT_EVALUATED", "no current evaluation; re-score "
                  f"offline: scripts/model_lab/reevaluate.py --comparison "
                  f"{cid}")
    body = cur["body"]
    ref_child = next((c for c in body.get("children") or []
                      if c.get("child_run_id") == opus["child_run_id"]), None)
    facts |= {"evaluation_revision": cur.get("revision"),
              "evaluation_id": cur.get("evaluation_id"),
              "evaluator_version": body.get("evaluator_version"),
              "evaluation_sha256": _h(body)}
    suite_q = qid != "Q01"
    if body.get("evaluator_version") not in COMPATIBLE_REFERENCE_VERSIONS \
            or ref_child is None \
            or any(k not in ref_child for k in _REFERENCE_CHILD_KEYS) \
            or (suite_q and "suite_values" not in
                (ref_child.get("facts") or {})):
        return no("REFERENCE_EVALUATION_INCOMPATIBLE",
                  f"evaluation r{cur.get('revision')} "
                  f"({body.get('evaluator_version')}) lacks what agreement "
                  f"needs; re-score offline (no model call): "
                  f"scripts/model_lab/reevaluate.py --comparison {cid}")
    if ref_child.get("execution_state") != "COMPLETED":
        return no("REFERENCE_OPUS_NOT_COMPLETED", "the evaluated Opus child "
                  f"is {ref_child.get('execution_state')}")
    return {"ok": True, "status": READY, "reason": "", "facts": facts,
            "child": ref_child, "spec": spec}


def search(coord, qid: str, *, snapshot_id: str | None = None,
           allow_fixture: bool = False) -> dict[str, Any]:
    """Every saved comparison in the store that asked this exact question
    and has an Opus child, verified. The earliest valid one wins, so the
    choice is stable; the others are listed, never merged."""
    q = bq.get(qid)
    tenant = coord.cfg.tenant_id
    rows = coord.store._q(
        "SELECT comparison_id, spec_json FROM comparisons WHERE "
        "owner_scope=? ORDER BY created_at", (tenant,))
    tried = []
    for r in rows:
        try:
            spec = json.loads(r["spec_json"])
        except ValueError:
            continue
        if spec.get("question_text") != q.text:
            continue
        if _opus_row(coord.store.children(r["comparison_id"])) is None:
            continue
        v = verify_comparison(coord, r["comparison_id"], qid,
                              snapshot_id=snapshot_id,
                              allow_fixture=allow_fixture)
        tried.append({"comparison_id": r["comparison_id"],
                      "status": v["status"], "reason": v["reason"]})
        if v["ok"]:
            return {"found": v, "considered": tried}
    return {"found": None, "considered": tried}


# ---- the per-question record and its answer snapshot ---------------------------

def _trace_availability(coord, cid: str, child_id: str) -> dict[str, Any]:
    from backend.model_lab import model_io
    try:
        tr = model_io.build(coord, cid, include_bodies=False)
    except Exception as exc:  # noqa: BLE001
        return {"status": "NOT_AVAILABLE", "reason": f"{type(exc).__name__}"}
    ch = next((c for c in tr.get("children") or []
               if c.get("child_run_id") == child_id), None)
    n = (ch or {}).get("traced_calls") or 0
    return ({"status": "FULL", "traced_calls": n,
             "endpoint": f"/api/v1/model-lab/comparisons/{cid}/model-io"}
            if n else {"status": "NOT_AVAILABLE", "traced_calls": 0,
                       "reason": "this run predates the Full Model I/O "
                                 "Trace; its answer, evaluation and frozen "
                                 "run records remain available"})


def _code(coord, cid: str, child_id: str) -> list[dict[str, Any]]:
    from backend.model_lab import model_io
    try:
        tr = model_io.build(coord, cid, include_bodies=True)
    except Exception:  # noqa: BLE001
        return []
    ch = next((c for c in tr.get("children") or []
               if c.get("child_run_id") == child_id), None)
    out = []
    for it in (ch or {}).get("timeline") or []:
        call = it.get("model_tool_call") or {}
        if it.get("kind") == "tool" and call.get("name") == \
                "execute_analysis":
            out.append({"tool_roundtrip": it.get("n"),
                        "steps": (call.get("input") or {}).get("steps"),
                        "validation": [v.get("status") for v in
                                       it.get("validation") or []]})
    return out


def snapshot_answer(coord, qid: str, v: dict[str, Any],
                    directory: Path | None = None) -> dict[str, Any]:
    """Write the reference's answer, evaluation child, result tables and
    code into the set's own directory (read from the store; the reference
    comparison itself is not touched) and return path -> sha256."""
    from backend.model_lab.evaluate import _artifact_rows

    ch, spec = v["child"], v["spec"]
    tenant = coord.data_tenant(spec.get("domain") or bq.DOMAIN)
    out = snapshot_dir(directory) / qid
    out.mkdir(parents=True, exist_ok=True)
    arts = {}
    for aid in (ch.get("facts") or {}).get("artifact_ids") or []:
        rows = _artifact_rows(coord.runs, aid, tenant)
        if rows:
            arts[aid] = rows
    files = {
        "answer.json": ch.get("answer"),
        "evaluation_child.json": {k: ch.get(k) for k in (
            "child_run_id", "profile_id", "execution_state", "stages",
            "checks", "claims", "facts", "repair", "answer", "lane",
            "benchmark_question_id")},
        "result_tables.json": arts,
        "code.json": _code(coord, v["facts"]["reference_comparison_id"],
                           ch["child_run_id"]),
    }
    shas = {}
    for name, body in files.items():
        p = out / name
        p.write_text(json.dumps(body, indent=1, sort_keys=True, default=str))
        shas[str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p)] = \
            _sha_file(p)
    return shas


def record(coord, qid: str, v: dict[str, Any], *, reused: bool,
           directory: Path | None = None) -> dict[str, Any]:
    f = v["facts"]
    cid = f["reference_comparison_id"]
    return {
        "question_id": qid, "question_text": bq.get(qid).text,
        "state": READY, "reference_comparison_id": cid,
        "opus_child_run_id": f["opus_child_run_id"],
        "profile_id": f["profile_id"], "model_id": f["model_id"],
        "reference_is_fixture": f["reference_is_fixture"],
        "data_snapshot_id": f["data_snapshot_id"],
        "frozen_source_id": f["frozen_source_id"],
        "spec_hash": f["spec_hash"],
        "evaluator_version": f["evaluator_version"],
        "evaluation_revision": f["evaluation_revision"],
        "evaluation_id": f["evaluation_id"],
        "evaluation_sha256": f["evaluation_sha256"],
        "oracle": oracle_version(),
        "created_at": f["created_at"], "recorded_at": time.time(),
        "provenance": "REUSED_EXISTING" if reused else "BUILT_BY_SET",
        "model_io_trace": _trace_availability(coord, cid,
                                              f["opus_child_run_id"]),
        "answer_artifacts": snapshot_answer(coord, qid, v, directory),
    }


# ---- resolution: verify the set against the store --------------------------------

def resolve(coord, doc: dict[str, Any], *, directory: Path | None = None,
            allow_fixture: bool = False, write_snapshots: bool = True
            ) -> dict[str, Any]:
    """Bring the set up to date WITHOUT any model call:
    - a READY entry is re-verified; if it no longer verifies it becomes
      INVALID (never silently replaced);
    - a MISSING entry is filled from the store when a valid Opus comparison
      for that exact question already exists (reuse, zero calls);
    - INVALID / REFERENCE_FAILED entries stay until the operator acts."""
    snap = current_snapshot_id()
    for q in bq.QUESTIONS:
        e = doc["questions"].setdefault(q.qid, {
            "question_id": q.qid, "question_text": q.text,
            "state": MISSING})
        if e["state"] == READY:
            v = verify_comparison(coord, e["reference_comparison_id"], q.qid,
                                  snapshot_id=snap,
                                  allow_fixture=allow_fixture)
            drift = v["ok"] and (
                v["facts"]["evaluation_sha256"] != e.get("evaluation_sha256")
                or v["facts"]["evaluation_id"] != e.get("evaluation_id")
                or v["facts"]["spec_hash"] != e.get("spec_hash"))
            if not v["ok"] or drift:
                e.update(state=INVALID, invalid_status=(
                    v["status"] if not v["ok"] else "REFERENCE_CHANGED"),
                    invalid_reason=(v["reason"] if not v["ok"] else
                                    "the reference's evaluation or spec "
                                    "changed after it entered the set"),
                    invalidated_at=time.time())
            elif not all((ROOT / p if not Path(p).is_absolute() else Path(p)
                          ).exists() and _sha_file(
                              ROOT / p if not Path(p).is_absolute()
                              else Path(p)) == s
                         for p, s in (e.get("answer_artifacts") or {})
                         .items()):
                e.update(state=INVALID, invalid_status="SNAPSHOT_CORRUPT",
                         invalid_reason="an answer artifact is missing or its "
                                        "sha256 changed",
                         invalidated_at=time.time())
            continue
        if e["state"] != MISSING:
            continue
        s = search(coord, q.qid, snapshot_id=snap,
                   allow_fixture=allow_fixture)
        e["search"] = s["considered"]
        if s["found"] and write_snapshots:
            doc["questions"][q.qid] = record(
                coord, q.qid, s["found"], reused=True, directory=directory
            ) | {"search": s["considered"]}
    return doc


def status_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"question_id": q.qid,
             "state": doc["questions"].get(q.qid, {}).get("state", MISSING),
             "reference_comparison_id": doc["questions"].get(
                 q.qid, {}).get("reference_comparison_id"),
             "reason": doc["questions"].get(q.qid, {}).get(
                 "invalid_reason") or doc["questions"].get(q.qid, {}).get(
                 "failure") or ""}
            for q in bq.QUESTIONS]


def ready_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {qid: e for qid, e in doc["questions"].items()
            if e.get("state") == READY}


# ---- spend preflight ------------------------------------------------------------

def spend_preflight(doc: dict[str, Any], approvals: dict[str, Any], *,
                    env: dict[str, str] | None = None,
                    reserve_usd: float | None = None) -> dict[str, Any]:
    """What building the missing references would need. No call, no key
    value: the key is reported as present or absent only."""
    from backend.model_lab.coordinator import PER_CHILD_RESERVE_USD

    reserve = PER_CHILD_RESERVE_USD if reserve_usd is None else reserve_usd
    env = os.environ if env is None else env
    states = {qid: e.get("state") for qid, e in doc["questions"].items()}
    valid = sorted(q for q, s in states.items() if s == READY)
    missing = sorted(q for q, s in states.items() if s == MISSING)
    blocked = sorted(q for q, s in states.items()
                     if s in (INVALID, REFERENCE_FAILED))
    grant = approvals.get(APPROVAL_KEY)
    cap = float(grant["cap_usd"]) if grant and grant.get("cap_usd") \
        is not None else None
    spent = sum(float(x.get("spend_usd") or 0) for x in
                doc.get("spend_ledger") or []
                if grant and x.get("approval_granted_at") ==
                grant.get("granted_at"))
    available = None if cap is None else round(cap - spent, 4)
    required = round(len(missing) * reserve, 2)
    return {"existing_valid": valid, "missing": missing,
            "blocked_needs_operator": blocked,
            "current_cap_usd": cap, "spent_under_current_approval_usd":
            round(spent, 4), "available_usd": available,
            "reserve_per_reference_usd": reserve,
            "required_cap_usd": required,
            "approval_sufficient": bool(missing) and available is not None
            and available + 1e-9 >= required,
            "key_env": KEY_ENV, "key_present": bool(env.get(KEY_ENV)),
            "known_prior": {q: c for q, c in KNOWN_PRIOR.items()
                            if q in missing},
            "all_ready": len(valid) == len(bq.QUESTIONS)}
