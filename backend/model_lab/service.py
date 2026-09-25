"""
The lab service: one coordinator, evaluation + export on settle, reviews,
re-evaluation without inference, and the training-readiness worksheet.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.model_lab import EVALUATOR_VERSION, evaluate, export
from backend.model_lab.coordinator import Coordinator, LabConfig

REVIEW_DECISIONS = ("CONFIRM", "OVERTURN_TO_SUPPORTED",
                    "OVERTURN_TO_CONTRADICTED", "OVERTURN_TO_UNSUPPORTED",
                    "NEEDS_MORE_EVIDENCE", "CLARIFICATION_APPROPRIATE",
                    "CLARIFICATION_UNNECESSARY", "CLARIFICATION_MISSED")

#: Training-readiness gates. Proposed diagnostic defaults, NOT scientific
#: guarantees; the user can tighten them, and the change is recorded.
READINESS_GATES = {"min_distinct_tasks": 20, "min_recurrence": 5,
                   "version": "readiness-gates-1"}


class LabService:
    def __init__(self, cfg: LabConfig, **kw: Any) -> None:
        self.cfg = cfg
        self.coord = Coordinator(cfg, on_settled=self._after_settle, **kw)
        self.exports_dir = cfg.runtime_dir / "exports"

    # -- lifecycle hooks ---------------------------------------------------
    def _after_settle(self, cid: str) -> None:
        self.evaluate(cid)
        self.export(cid)

    def evaluate(self, cid: str) -> dict[str, Any]:
        body = evaluate.evaluate_comparison(self.coord, cid)
        body = self._apply_reviews(cid, body)
        rec = self.coord.store.add_evaluation(cid, self.cfg.tenant_id,
                                              EVALUATOR_VERSION, body)
        self.coord.emit(cid, "evaluation.completed",
                        payload={"evaluation_id": rec["evaluation_id"],
                                 "revision": rec["revision"]})
        return body | {"evaluation_id": rec["evaluation_id"],
                       "revision": rec["revision"]}

    def export(self, cid: str, *, partial: bool = False) -> dict[str, Any]:
        cur = self.coord.store.current_evaluation(cid, self.cfg.tenant_id)
        ev = cur["body"] if cur else self.evaluate(cid)
        res = export.build(self.coord, cid, ev, self.exports_dir,
                           partial=partial)
        self.coord.emit(cid, "export." + ("ready" if res["state"] == "READY"
                                          else "failed"),
                        payload={k: res.get(k) for k in
                                 ("state", "sha256", "revision", "error")})
        return {k: v for k, v in res.items() if k not in ("tables",)}

    # -- reviews (append-only; overturn re-evaluates without inference) --------
    def add_review(self, cid: str, *, reviewer: str, target: str,
                   decision: str, reason: str) -> dict[str, Any]:
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"decision must be one of {REVIEW_DECISIONS}")
        if not reason.strip():
            raise ValueError("a review needs a reason")
        cur = self.coord.store.current_evaluation(cid, self.cfg.tenant_id)
        prior = _find_target(cur["body"] if cur else {}, target)
        if prior is None:
            raise KeyError(f"no claim/check {target!r} in this comparison")
        rid = self.coord.store.add_review(cid, self.cfg.tenant_id, reviewer,
                                          target, decision, reason, prior)
        self.coord.emit(cid, "review.added", payload={
            "review_id": rid, "target": target, "decision": decision})
        body = self.evaluate(cid)
        return {"review_id": rid, "evaluation_revision": body["revision"]}

    def _apply_reviews(self, cid: str, body: dict[str, Any]
                       ) -> dict[str, Any]:
        reviews = self.coord.store.reviews(cid, self.cfg.tenant_id)
        latest: dict[str, dict] = {}
        for r in reviews:
            latest[r["target"]] = r
        for k in body["children"]:
            for c in k["claims"]:
                key = f"{k['child_run_id']}:{c['claim_id']}"
                r = latest.get(key)
                if not r:
                    continue
                c["reviewer_status"] = "REVIEWED"
                c["review"] = {"review_id": r["review_id"],
                               "decision": r["decision"],
                               "reason": r["reason"],
                               "reviewer": r["reviewer"],
                               "automatic_status":
                               c["verification_status"]}
                if r["decision"].startswith("OVERTURN_TO_"):
                    c["verification_status"] = r["decision"][len(
                        "OVERTURN_TO_"):]
            for c in k["checks"]:
                r = latest.get(f"{k['child_run_id']}:{c['check_id']}")
                if r:
                    c["review"] = {"review_id": r["review_id"],
                                   "decision": r["decision"],
                                   "reason": r["reason"]}
                    c["status"] = "REVIEWED"
            k["claim_rates"] = evaluate._claim_rates(
                k["claims"], None, k.get("facts") or {}) | {
                "required_output_coverage":
                k["claim_rates"]["required_output_coverage"]}
        body["reviews_applied"] = len(latest)
        return body

    # -- training readiness (across saved comparisons) ---------------------------
    def training_readiness(self, gates: dict[str, Any] | None = None
                           ) -> dict[str, Any]:
        g = dict(READINESS_GATES, **(gates or {}))
        per: dict[str, dict[str, Any]] = {}
        for row in self.coord.store.list_comparisons(self.cfg.tenant_id,
                                                     1000):
            cur = self.coord.store.current_evaluation(
                row["comparison_id"], self.cfg.tenant_id)
            if not cur:
                continue
            body = cur["body"]
            spec = json.loads(row["spec_json"])
            task_key = (body.get("task") or {}).get("task_id") or \
                "q:" + hashlib.sha256(spec["question_text"].lower().encode()
                                      ).hexdigest()[:12]
            split = spec.get("evaluation_split") or "diagnostic"
            for k in body["children"]:
                p = per.setdefault(k["profile_id"], {
                    "profile_id": k["profile_id"], "fixture": k["fixture"],
                    "tasks": set(), "runs": 0, "by_category": {},
                    "integration_failures": 0, "resource_failures": 0,
                    "splits": {}})
                if not k.get("turns"):
                    continue
                p["runs"] += 1
                p["tasks"].add(task_key)
                p["splits"].setdefault(task_key, set()).add(split)
                for f in k.get("failures") or []:
                    cat = f["primary_category"]
                    p["by_category"].setdefault(cat, set()).add(task_key)
                    if cat in ("ADAPTER_OR_PROTOCOL", "RUNTIME_CAPABILITY"):
                        p["integration_failures"] += 1
                    if cat == "RESOURCE_OR_CONTEXT":
                        p["resource_failures"] += 1
        out = []
        not_run = [p["profile_id"] for p in per.values() if not p["runs"]]
        for p in per.values():
            if not p["runs"]:
                continue
            distinct = len(p["tasks"])
            recurring = {c: len(t) for c, t in p["by_category"].items()}
            model_cats = {c: n for c, n in recurring.items() if c.startswith(
                ("S1_", "S2_", "S3_", "S4_"))}
            if p["integration_failures"]:
                status = "FIX_INTEGRATION_FIRST"
            elif p["resource_failures"]:
                status = "FIX_RESOURCE_PROFILE_FIRST"
            elif "CATALOGUE_OR_REFERENCE" in recurring:
                status = "NEEDS_REFERENCE_OR_CONTEXT"
            elif distinct < g["min_distinct_tasks"]:
                status = "COLLECT_MORE_EVIDENCE"
            elif not model_cats:
                status = "NO_TRAINING_NEEDED_FOR_OBSERVED_SET"
            elif max(model_cats.values()) >= g["min_recurrence"]:
                status = ("TRY_ALTERNATIVE_MODEL" if len(model_cats) >= 3
                          else "TARGETED_TRAINING_CANDIDATE")
            else:
                status = "PROMPT_DIAGNOSTIC_CANDIDATE"
            # Split hygiene (Q15): a task used for tuning a profile is not
            # untouched evidence for that profile's holdout.
            contaminated = sorted(t for t, sp in p["splits"].items()
                                  if "tuning" in sp and "holdout" in sp)
            out.append({
                "profile_id": p["profile_id"], "fixture": p["fixture"],
                "distinct_tasks": distinct, "runs": p["runs"],
                "split_ledger": {t: sorted(sp) for t, sp in
                                 p["splits"].items()},
                "contaminated_holdout_tasks": contaminated,
                "recurring_categories_by_distinct_task": recurring,
                "status": status, "tentative": distinct <
                g["min_distinct_tasks"],
                "note": ("insufficient sample for a training decision"
                         if distinct < g["min_distinct_tasks"] else
                         "provisional; no uplift is forecast"),
                "smallest_next_intervention": _next_step(status)})
        return {"gates": g, "profiles": out, "never_ran": not_run,
                "disclaimer": "No training is authorised or performed. "
                              "Statuses are not production readiness."}


def _next_step(status: str) -> str:
    return {
        "FIX_INTEGRATION_FIRST": "repair the adapter/route and rerun the "
                                 "unchanged tasks",
        "FIX_RESOURCE_PROFILE_FIRST": "same model on approved faster "
                                      "hardware (deployment diagnostic)",
        "NEEDS_REFERENCE_OR_CONTEXT": "add an approved reference/metadata "
                                      "variant",
        "COLLECT_MORE_EVIDENCE": "run more distinct saved UAT tasks",
        "NO_TRAINING_NEEDED_FOR_OBSERVED_SET": "keep monitoring",
        "PROMPT_DIAGNOSTIC_CANDIDATE": "test a governed prompt/definition "
                                       "variant as a new profile",
        "TARGETED_TRAINING_CANDIDATE": "curate approved examples for review "
                                       "(no training job here)",
        "TRY_ALTERNATIVE_MODEL": "benchmark a stronger/different model on "
                                 "the same tasks",
    }.get(status, "")


def _find_target(body: dict[str, Any], target: str) -> dict | None:
    child_id, _, item = target.partition(":")
    for k in body.get("children") or []:
        if k["child_run_id"] != child_id:
            continue
        for c in k["claims"]:
            if c["claim_id"] == item:
                return {"kind": "claim", "verification_status":
                        c["verification_status"]}
        for c in k["checks"]:
            if c["check_id"] == item:
                return {"kind": "check", "outcome": c["outcome"]}
    return None


def default_config(runtime_dir: str | Path) -> LabConfig:
    return LabConfig(runtime_dir=Path(runtime_dir))
