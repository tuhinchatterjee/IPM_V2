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

ORACLE_VERSION = "lab-oracle-1"


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
    from backend.cockpit_v4 import lake   # path resolution only, read-only

    return pd.read_parquet(lake.relation_path(release_id, relation))


def find_task(question: str, task_id: str = "") -> Task | None:
    if task_id:
        return next((t for t in TASKS if t.task_id == task_id), None)
    return next((t for t in TASKS if t.matches(question)), None)


def expected(task: Task, release_id: str) -> dict[str, Any]:
    """The independent reference, plus a deliberate WRONG-POPULATION
    reference so a whole-book answer is recognised for what it is."""
    if task.task_id == "corp-stage2-ead-by-sector-latest":
        f = _frame(release_id, "corp_facility_quarter")
        latest = str(sorted(f["reporting_quarter"].dropna().unique())[-1])
        q = f[f["reporting_quarter"] == latest]
        s2 = q[q["stage"] == 2].groupby("sector")["ead_sar_mn"].sum()
        whole = q.groupby("sector")["ead_sar_mn"].sum()
        values = {str(k): float(v) for k, v in s2.items()}
        return {"task_id": task.task_id, "release_id": release_id,
                "period": latest, "unit": "SAR million",
                "values": values,
                "largest": max(values, key=values.get) if values else None,
                "total": float(sum(values.values())),
                "population": "stage == 2, reporting_quarter == latest",
                "wrong_population_values": {str(k): float(v)
                                            for k, v in whole.items()},
                "wrong_population_label": "all stages (whole book)",
                "oracle_version": ORACLE_VERSION,
                "digest": hashlib.sha256(json.dumps(
                    values, sort_keys=True).encode()).hexdigest()}
    raise KeyError(task.task_id)


def within(a: float, b: float, task: Task) -> bool:
    return abs(a - b) <= max(task.abs_tolerance,
                             task.rel_tolerance * max(abs(a), abs(b)))
