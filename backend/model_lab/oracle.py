"""
Independent references for known-answer UAT tasks.

Expected results are computed with pandas straight from the published Parquet
files: NOT through DuckDB, the catalog, the validator, or any candidate's
query. Tolerances are declared here, versioned, BEFORE any output is
evaluated. An Opus answer is never an oracle.

A task registered here states what it supports and what it does not; a
question that matches no task gets NEEDS_REVIEW, never an invented score.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

ORACLE_VERSION = "lab-oracle-2"


@dataclass(frozen=True)
class Task:
    task_id: str
    family: str
    domain: str
    question_patterns: tuple[str, ...]
    description: str
    required_outputs: tuple[str, ...]
    clarification_policy: str        # required | optional | not_required
    abs_tolerance: float
    rel_tolerance: float
    materiality: str
    permissible_alternatives: tuple[str, ...]
    provenance: str
    split: str = "diagnostic"
    extra: dict[str, Any] = field(default_factory=dict)

    def matches(self, question: str) -> bool:
        q = question.lower()
        return any(re.search(p, q) for p in self.question_patterns)

    def spec(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "task_id", "family", "domain", "description", "required_outputs",
            "clarification_policy", "abs_tolerance", "rel_tolerance",
            "materiality", "permissible_alternatives", "provenance",
            "split")} | {"oracle_version": ORACLE_VERSION}


TASKS: tuple[Task, ...] = (
    Task(
        task_id="corp-stage2-ead-by-sector-latest",
        family="stage_exposure_by_segment", domain="corporate",
        question_patterns=(r"stage\s*2.*(exposure|ead).*sector",
                           r"sector.*stage\s*2.*(exposure|ead)"),
        description="IFRS 9 Stage 2 EAD (SAR million) by sector, latest "
                    "reporting quarter, facility-quarter grain, all Stage 2 "
                    "facilities in the corporate book.",
        required_outputs=("per_sector_stage2_values", "largest_sector"),
        clarification_policy="not_required",
        abs_tolerance=0.01, rel_tolerance=1e-9,
        materiality="any sector off by > 0.01 SAR million is material",
        permissible_alternatives=(
            "a CTE or subquery for the latest quarter",
            "naming the latest quarter literally (2026Q2)",
            "ordering by value or by sector name",
            "including a total row in addition to sectors"),
        provenance="pandas over corp_facility_quarter.parquet; independent "
                   "of the engine; reviewed by the lab author (not a user "
                   "sign-off)"),
)


def _frame(release_id: str, relation: str):
    import pandas as pd
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
    from backend.cockpit_v4 import lake  # path resolution only, read-only

    return pd.read_parquet(lake.relation_path(release_id, relation))


def find_task(question: str, task_id: str = "") -> Task | None:
    if task_id:
        return next((t for t in TASKS if t.task_id == task_id), None)
    return next((t for t in TASKS if t.matches(question)), None)


#: Unit classes. A claim may only be compared with a reference of the SAME
#: class: money is never compared with a count, and a count of facilities is
#: never compared with a count of borrowers.
_MONEY = re.compile(r"\b(sar|usd|inr|eur|gbp|aed|million|mn|bn|billion|"
                    r"thousand|crore|lakh)\b", re.I)
_ENTITY = {"facility": re.compile(r"\bfacilit(y|ies)\b", re.I),
           "borrower": re.compile(r"\bborrowers?\b", re.I),
           "account": re.compile(r"\baccounts?\b", re.I)}


def unit_class(unit: str | None) -> str | None:
    """`money`, `count:<entity>`, or None when the unit says neither."""
    text = str(unit or "")
    for entity, rx in _ENTITY.items():
        if rx.search(text):
            return f"count:{entity}"
    if _MONEY.search(text):
        return "money"
    return None


def expected(task: Task, release_id: str) -> dict[str, Any]:
    """The independent references, one per METRIC, plus a deliberate
    WRONG-POPULATION reference so a whole-book answer is recognised.

    Each metric carries its unit and unit class and the column-name hints
    that identify it; `match_metric` uses them so a claim is only ever
    compared with a reference for the same metric. The top-level `values`
    / `largest` / `total` keys are the primary metric (Stage 2 EAD), kept
    for the population check."""
    if task.task_id == "corp-stage2-ead-by-sector-latest":
        f = _frame(release_id, "corp_facility_quarter")
        latest = str(sorted(f["reporting_quarter"].dropna().unique())[-1])
        q = f[f["reporting_quarter"] == latest]
        s2 = q[q["stage"] == 2]
        ead = {str(k): float(v) for k, v in
               s2.groupby("sector")["ead_sar_mn"].sum().items()}
        facilities = {str(k): float(v) for k, v in
                      s2.groupby("sector")["facility_id"].nunique().items()}
        whole = q.groupby("sector")["ead_sar_mn"].sum()
        metrics = {
            "stage2_ead": {
                "values": ead, "unit": "SAR million", "unit_class": "money",
                "column_hints": ("ead", "exposure"),
                "definition": "SUM(ead_sar_mn), stage 2, latest quarter",
                "exact": False,
                "largest": max(ead, key=ead.get) if ead else None},
            "stage2_facility_count": {
                "values": facilities, "unit": "facilities",
                "unit_class": "count:facility",
                "column_hints": ("facilit",),
                "definition": "COUNT(DISTINCT facility_id), stage 2, latest "
                              "quarter",
                "exact": True,
                "largest": max(facilities, key=facilities.get)
                if facilities else None},
        }
        return {"task_id": task.task_id, "release_id": release_id,
                "period": latest, "unit": "SAR million",
                "primary_metric": "stage2_ead", "metrics": metrics,
                "values": ead,
                "largest": metrics["stage2_ead"]["largest"],
                "total": float(sum(ead.values())),
                "population": "stage == 2, reporting_quarter == latest",
                "wrong_population_values": {str(k): float(v)
                                            for k, v in whole.items()},
                "wrong_population_label": "all stages (whole book)",
                "oracle_version": ORACLE_VERSION,
                "digest": hashlib.sha256(json.dumps(
                    metrics, sort_keys=True, default=str).encode()
                ).hexdigest()}
    raise KeyError(task.task_id)


def match_metric(reference: dict[str, Any] | None, column_id: str | None,
                 unit: str | None, column_unit: str | None = None
                 ) -> str | None:
    """The ONE reference metric this claim/column is about, or None.

    Both must agree: the claim's unit class (money vs a count of a named
    entity) equals the metric's, AND the column name carries one of the
    metric's hints. Ambiguity or no match returns None -- no oracle is
    applied, and nothing is compared across metrics."""
    if not reference or not reference.get("metrics"):
        return None
    klass = unit_class(unit) or unit_class(column_unit)
    col = str(column_id or "").lower()
    hits = [mid for mid, m in reference["metrics"].items()
            if klass == m["unit_class"] and
            any(h in col for h in m["column_hints"])]
    return hits[0] if len(hits) == 1 else None


def compare(reference: dict[str, Any], metric_id: str, row_label: str,
            value: float, task: Task) -> tuple[bool, float] | None:
    """(agrees, reference_value) for the same metric, or None when the
    reference has no value for that row."""
    m = reference["metrics"][metric_id]
    if row_label not in m["values"]:
        return None
    ref = m["values"][row_label]
    ok = (float(value) == ref) if m.get("exact") else \
        within(float(value), ref, task)
    return ok, ref


def within(a: float, b: float, task: Task) -> bool:
    return abs(a - b) <= max(task.abs_tolerance,
                             task.rel_tolerance * max(abs(a), abs(b)))
