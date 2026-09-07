"""
Running a What-If, and the context every answer has to carry with it.

One engine, two methodologies
------------------------------
There is exactly one place a scenario is applied to the book:
`engine.run()`. It shocks the borrowers, re-reads the staging criteria against
the stressed PD, re-measures, and hands back the working frame.

The methodology decides only how the REPORTED ECL is moved from there — by the
Delta factors read out of that measurement, or by the ratio of two model
predictions over the same frame. Both start from the same shocked book, so the
two answers are genuinely comparable, and there is no second engine to drift
away from the first.

Why the result is so wordy
--------------------------
An ECL figure with no context is unusable in a credit committee. "Provisions
rise 38%" invites "on what book, over what population, under whose staging
rules, using which model?" — and if the screen cannot answer, the number does
not survive the meeting. So every result carries the period, the scenario, the
population, the staging criteria and their version, the methodology and its
version, the reported baseline, the What-If figure, and both the absolute and
percentage change. That is not decoration; it is the difference between an
answer and a rumour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.whatif import attribution as at
from backend.whatif import delta as dl
from backend.whatif import domain as dm
from backend.whatif import engine as wf
from backend.whatif import macro as mc
from backend.whatif import methodology as me
from backend.whatif import staging as st
from backend.whatif import steps as sp

RUN_VERSION = "1.0.0"


class RunError(ValueError):
    """A What-If that cannot be run, said rather than approximated."""


@dataclass
class WhatIfResult:
    """One executed scenario, with everything needed to defend it."""

    period: str
    state: sp.ScenarioState
    choice: me.Choice
    borrowers: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)
    factors: dl.Factors | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    by_sector: pd.DataFrame = field(default_factory=pd.DataFrame)
    by_rating: pd.DataFrame = field(default_factory=pd.DataFrame)
    by_stage: pd.DataFrame = field(default_factory=pd.DataFrame)
    stage_movement: dict[str, Any] = field(default_factory=dict)
    rating_movement: dict[str, Any] = field(default_factory=dict)
    #: The ECL movement split across the drivers that caused it, by an exact
    #: order-neutral Shapley value.
    attribution: dict[str, Any] = field(default_factory=dict)
    ml: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: About the installation, not about this result. Shown quietly.
    notes: list[str] = field(default_factory=list)

    @property
    def population(self) -> int:
        return int(len(self.borrowers))

    def context(self) -> dict[str, Any]:
        """The provenance line the product shows above every result."""
        return {
            "domain": dm.DOMAIN_NAME,
            "dataset": dm.IFRS9,
            "period": self.period,
            "grain": dm.GRAIN,
            "currency": dm.CURRENCY,
            "scenario": self.state.describe(),
            "steps": [s.to_dict() for s in self.state.active],
            "population": self.summary.get("population_description", ""),
            "population_count": self.population,
            # Two rule sets, named separately, because a reader has to know
            # which one produced which column.
            "staging_criteria": self.state.staging.describe(),
            "staging_version": self.state.staging.version,
            "reported_staging": st.reported().describe(),
            "reported_staging_version": st.reported().version,
            "whatif_staging": self.state.staging.describe(),
            "whatif_staging_version": self.state.staging.version,
            "staging_note": (
                "The baseline column is the reported book, staged by the "
                "governed corporate policy. The What-If column is staged by "
                "this thread's rule set. No What-If rule changes the reported "
                "book."),
            "ecl_methodology": self.choice.label,
            "ecl_methodology_version": self.choice.version,
            "methodology_stamp": self.choice.stamp,
            "macro_version": mc.MACRO_VERSION,
            "baseline_ecl": self.summary.get("baseline_ecl", 0.0),
            "whatif_ecl": self.summary.get("stressed_ecl", 0.0),
            "absolute_change": self.summary.get("incremental_ecl", 0.0),
            "percentage_change": self.summary.get("incremental_ecl_pct", 0.0),
        }

    def to_dict(self, *, limit: int = 200) -> dict[str, Any]:
        table = self.borrowers.head(limit)
        return {
            "run_version": RUN_VERSION,
            "context": self.context(),
            "summary": dict(self.summary),
            "factors": self.factors.to_dict() if self.factors else None,
            "steps": list(self.steps),
            "stage_movement": dict(self.stage_movement),
            "rating_movement": dict(self.rating_movement),
            "attribution": dict(self.attribution),
            "ml": dict(self.ml),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
            "borrowers": {
                "columns": list(table.columns),
                "rows": table.to_dict(orient="records"),
                "shown": int(len(table)),
                "total": self.population,
            },
            "by_sector": self.by_sector.to_dict(orient="records")
            if not self.by_sector.empty else [],
            "by_rating": self.by_rating.to_dict(orient="records")
            if not self.by_rating.empty else [],
            "by_stage": self.by_stage.to_dict(orient="records")
            if not self.by_stage.empty else [],
        }


def _attribution(work: pd.DataFrame, engine_result: Any) -> dict[str, Any]:
    """The driver split, or a stated reason there is not one.

    An attribution that cannot be computed says so on the result. It never
    comes back as an empty table, because an empty table reads as "nothing
    caused this".
    """
    try:
        return at.attribute(work, getattr(engine_result, "tracked", {}) or {},
                            currency=dm.CURRENCY)
    except at.AttributionError as e:
        return {"available": False, "why": str(e)}


def _movement(frame: pd.DataFrame) -> dict[str, Any]:
    """How Stages moved under the scenario, as a small matrix."""
    if "stage_baseline" not in frame.columns or "stage_stressed" not in frame.columns:
        return {}
    opening = pd.to_numeric(frame["stage_baseline"], errors="coerce").fillna(0).astype(int)
    closing = pd.to_numeric(frame["stage_stressed"], errors="coerce").fillna(0).astype(int)
    ead = pd.to_numeric(frame.get("ead"), errors="coerce").fillna(0.0)
    ecl_before = pd.to_numeric(frame.get("ecl_baseline"), errors="coerce").fillna(0.0)
    ecl_after = pd.to_numeric(frame.get("ecl_stressed"), errors="coerce").fillna(0.0)
    cells = []
    for start in (1, 2, 3):
        for end in (1, 2, 3):
            mask = (opening == start) & (closing == end)
            if not mask.any():
                continue
            cells.append({"from": start, "to": end, "count": int(mask.sum()),
                          "exposure": float(ead[mask].sum()),
                          "ecl_before": float(ecl_before[mask].sum()),
                          "ecl_after": float(ecl_after[mask].sum())})
    rows = []
    for number in (1, 2, 3):
        before = opening == number
        after = closing == number
        rows.append({"stage": number,
                     "count_before": int(before.sum()),
                     "count_after": int(after.sum()),
                     "exposure_before": float(ead[before].sum()),
                     "exposure_after": float(ead[after].sum()),
                     "ecl_before": float(ecl_before[before].sum()),
                     "ecl_after": float(ecl_after[after].sum())})
    moved = int((opening != closing).sum())
    return {"cells": cells, "stages": rows, "moved": moved,
            "deteriorated": int((closing > opening).sum()),
            "cured": int((closing < opening).sum())}


def _rating_movement(frame: pd.DataFrame) -> dict[str, Any]:
    """Source and destination reconciliation for a rating scenario."""
    if "opening_rating" not in frame.columns or "stressed_rating" not in frame.columns:
        return {}
    ead = pd.to_numeric(frame.get("ead"), errors="coerce").fillna(0.0)
    ecl_before = pd.to_numeric(frame.get("ecl_baseline"), errors="coerce").fillna(0.0)
    ecl_after = pd.to_numeric(frame.get("ecl_stressed"), errors="coerce").fillna(0.0)
    opening = frame["opening_rating"].astype(str)
    closing = frame["stressed_rating"].astype(str)
    grades = sorted(set(opening) | set(closing))
    rows = []
    for grade in grades:
        was = opening == grade
        now = closing == grade
        leaving = was & (closing != grade)
        arriving = now & (opening != grade)
        rows.append({
            "grade": grade,
            "count_before": int(was.sum()), "count_after": int(now.sum()),
            "exposure_before": float(ead[was].sum()),
            "exposure_after": float(ead[now].sum()),
            "ecl_before": float(ecl_before[was].sum()),
            "ecl_after": float(ecl_after[now].sum()),
            "ecl_leaving": float(ecl_before[leaving].sum()),
            "ecl_arriving": float(ecl_after[arriving].sum()),
            "left": int(leaving.sum()), "arrived": int(arriving.sum()),
        })
    moved = int((opening != closing).sum())
    return {"rows": [r for r in rows if r["count_before"] or r["count_after"]],
            "moved": moved,
            "note": ("Exposure leaving a grade reduces its ECL; exposure "
                     "arriving raises the destination's. The two reconcile "
                     "to the book total.")}


def execute(state: sp.ScenarioState, *, requested: str = "",
            instruction: str = "", source: Any = None,
            limit: int = 200) -> WhatIfResult:
    """Run the thread's scenario on the methodology it has settled on.

    Raises if the methodology gate has not been answered. That is deliberate:
    the caller is expected to ask first, and a default here would be the silent
    choice the product exists to avoid.
    """
    from backend.whatif.ml import predict as mp
    from backend.whatif.ml import registry as rg

    period = dm.resolve_period(state.period, source)
    available = rg.active_version()
    choice = me.resolve(requested=requested, instruction=instruction,
                        active=state.methodology, model_version=available)
    if choice is None:
        raise RunError(
            "No ECL methodology has been chosen for this What-If. Ask which "
            "one to use before calculating.")
    if choice.method == me.ML and not available:
        raise RunError(
            "The ML methodology was chosen but no model has been activated. "
            "Train and activate one, or use the Delta Model.")

    scenario = state.scenario()
    # The thread's rule set is ALWAYS what stages the scenario — including the
    # default one, which is the governed three plus Rule A and Rule B. Passing
    # None here when it happened to be the default was how the two scenario
    # rules got quietly switched off.
    engine_result = wf.run(scenario, period=period, source=source,
                           staging=state.staging)
    frame = engine_result.frame
    warnings = list(engine_result.warnings)
    warnings.extend(state.staging.unread(frame))
    notes = list(getattr(engine_result, "notes", []))

    delta_frame = dl.apply(frame)
    ml_body: dict[str, Any] = {}

    if choice.method == me.ML:
        delta_factor = delta_frame["ecl_factor"]
        moved, outcome = mp.apply(frame, version=available,
                                  delta_factors=delta_factor)
        ml_body = outcome.to_dict()
        warnings.extend(outcome.warnings)
        priced = moved
    else:
        priced = delta_frame

    work = frame.copy()
    for column in ("ecl_baseline", "ecl_stressed", "ecl_increase",
                   "ecl_increase_pct"):
        work[column] = priced[column]
    for column in ("pd_factor", "stage_factor", "lgd_factor", "ead_factor",
                   "ecl_factor"):
        if column in delta_frame.columns:
            work[column] = delta_frame[column]
    if choice.method == me.ML and "ml_factor" in priced.columns:
        work["ml_factor"] = priced["ml_factor"]

    summary = wf._summarise(work, scenario, period)
    summary["population_description"] = scenario.population.describe()
    summary["methodology"] = choice.method
    summary["methodology_label"] = choice.label
    summary["methodology_version"] = choice.version
    summary["baseline_ecl"] = float(work["ecl_baseline"].sum())
    summary["stressed_ecl"] = float(work["ecl_stressed"].sum())
    summary["incremental_ecl"] = summary["stressed_ecl"] - summary["baseline_ecl"]
    summary["incremental_ecl_pct"] = (
        summary["incremental_ecl"] / summary["baseline_ecl"] * 100.0
        if summary["baseline_ecl"] else 0.0)

    return WhatIfResult(
        period=period, state=state.with_methodology(choice.method, choice.version),
        choice=choice, borrowers=wf._present(work), summary=summary,
        factors=dl.aggregate(work), steps=list(engine_result.steps),
        by_sector=wf._group(work, "sector"),
        by_rating=wf._group(work, "opening_rating", label="Opening rating")
        if "opening_rating" in work.columns else wf._group(work, "internal_rating"),
        by_stage=wf._group(work, "stage_baseline", label="Opening stage"),
        stage_movement=_movement(work), rating_movement=_rating_movement(work),
        attribution=_attribution(work, engine_result),
        ml=ml_body, warnings=warnings, notes=notes)


def _materiality(pct: float) -> str:
    """How large a movement is, in the words a credit committee uses."""
    size = abs(float(pct))
    if size < 1.0:
        return "immaterial"
    if size < 5.0:
        return "modest"
    if size < 15.0:
        return "material"
    if size < 40.0:
        return "severe"
    return "extreme"


def interpret(result: WhatIfResult) -> dict[str, Any]:
    """What the result MEANS, written from the result's own figures.

    A number with no reading is where a scenario tool stops being useful. The
    person on the screen is going to have to say, out loud, whether this
    matters — so the product says what moved, by how much, what caused most of
    it, and what would be worth asking next. Every figure here is taken from
    the result; none is estimated and none is rounded into a different answer.
    """
    summary = result.summary
    baseline = float(summary.get("baseline_ecl", 0.0) or 0.0)
    whatif = float(summary.get("stressed_ecl", 0.0) or 0.0)
    change = float(summary.get("incremental_ecl", 0.0) or 0.0)
    pct = float(summary.get("incremental_ecl_pct", 0.0) or 0.0)
    materiality = _materiality(pct)
    direction = "increases" if change > 0 else ("decreases" if change < 0
                                                else "does not move")

    drivers = list((result.attribution or {}).get("drivers", []) or [])
    leading = drivers[0] if drivers else None
    movement = result.stage_movement or {}
    deteriorated = int(movement.get("deteriorated", 0) or 0)

    findings: list[str] = []
    findings.append(
        f"Expected credit loss {direction} from {dm.CURRENCY} {baseline:,.1f}m "
        f"to {dm.CURRENCY} {whatif:,.1f}m — a movement of {dm.CURRENCY} "
        f"{change:,.1f}m, or {pct:,.1f}%, which is {materiality} on this book.")
    if leading:
        findings.append(
            f"The largest single cause is {leading.get('label', 'unnamed')}, "
            f"at {float(leading.get('share_pct', 0.0)):,.1f}% of the movement.")
    if deteriorated:
        findings.append(
            f"{deteriorated:,} borrowers moved to a worse stage, which changes "
            "what their provision is measured on, not only how much it is.")
    basis = (result.attribution or {}).get("measurement_basis") or {}
    if basis.get("note"):
        findings.append(str(basis["note"]))

    return {
        "materiality": materiality,
        "direction": direction,
        "headline": findings[0],
        "findings": findings,
        "next_questions": [
            "Which borrowers contributed most to this movement?",
            "Show this by sector.",
            "How much of the increase is the measurement basis changing?",
            "Why did Stage 3 move?" if (result.stage_movement or {})
            .get("moved") else "Which sectors are most exposed to this shock?",
        ],
        "statement": (
            "This reading is composed from the figures above. It states what "
            "moved and what caused it; it does not add a view the numbers do "
            "not carry."),
    }


def compare_methodologies(state: sp.ScenarioState, *, source: Any = None
                          ) -> dict[str, Any]:
    """The same scenario under both methodologies, side by side.

    Offered wherever the ML answer is uncertain, because "the two agree" and
    "the two disagree by nine per cent" are both useful and neither is visible
    from one number.
    """
    out: dict[str, Any] = {"scenario": state.describe(), "rows": []}
    for method in me.METHODS:
        try:
            result = execute(state, requested=method, source=source)
        except (RunError, ValueError) as e:
            out["rows"].append({"method": method, "label": me.LABELS[method],
                                "available": False, "because": str(e)})
            continue
        out["rows"].append({
            "method": method, "label": me.LABELS[method], "available": True,
            "version": result.choice.version,
            "baseline_ecl": result.summary["baseline_ecl"],
            "whatif_ecl": result.summary["stressed_ecl"],
            "absolute_change": result.summary["incremental_ecl"],
            "percentage_change": result.summary["incremental_ecl_pct"]})
    usable = [r for r in out["rows"] if r.get("available")]
    if len(usable) == 2:
        left, right = usable
        spread = right["whatif_ecl"] - left["whatif_ecl"]
        out["spread"] = spread
        out["spread_pct"] = (spread / left["whatif_ecl"] * 100.0
                             if left["whatif_ecl"] else 0.0)
    return out


def informational(question: str) -> bool:
    """Whether a question needs no ECL calculation, and so no methodology gate.

    Conservative on purpose. Something that only READS the book — a
    distribution, a count, a breakdown — is informational; anything that states
    a change is not, and will be asked which methodology to use.
    """
    said = str(question or "").lower()
    asks_change = any(word in said for word in (
        "what if", "what happens", "increase", "decrease", "raise", "reduce",
        "downgrade", "upgrade", "shock", "stress", "move ", "migrate",
        "fall", "rise", "worsen", "improve", "simulate", "scenario"))
    return not asks_change


__all__ = [
    "RUN_VERSION", "RunError", "WhatIfResult", "compare_methodologies",
    "execute", "informational", "interpret",
]
