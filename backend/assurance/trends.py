"""
Component performance by dimension, trends and contribution. §201-§203.

What §201 actually changes
----------------------------
    §201: "Do not show 25 equal-weight top-level cards."

The old Overview was a wall. Twenty-five cards, each with a percentage, each
the same size, is a screen that answers no question — a reader cannot tell
which of the twenty-five matters, so they read the lowest number and worry
about whatever it happens to be. Six tiles that each answer a question a
person actually arrived with, drilling into the twenty-five, is the same
information arranged so it can be used.

Why the trend carries its sample size
---------------------------------------
    §202: "confidence/sample evidence"

A dimension at 94% over four Investigations and a dimension at 94% over four
hundred are not the same fact, and a trend line drawn through the first is
a picture of nothing. Every cohort here reports its n, and a cohort below
the floor reports UNDERPOWERED instead of a score — the same discipline the
evaluation suites use, for the same reason.

Why contribution is not a percentage each
-------------------------------------------
    §203: "Do not imply equal contribution where gates/weights differ."

Computation & Evidence is a gate before it is a weight: if its critical
checks fail, the record is FAILED regardless of the other five. Rendering
that as "Computation contributed 25%" would be arithmetic about a number
that was never computed. So contribution is reported as a ROLE — gate,
weighted contributor, or unmeasured — with the weight shown only where a
weight is what actually applied.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from backend.assurance import dimensions as dm
from backend.assurance import record as rc
from backend.assurance import store as st

TRENDS_VERSION = "1.0.0"

#: Below this many records a cohort reports UNDERPOWERED rather than a
#: score. Twelve is not a statistical result; it is the point below which a
#: single bad Investigation moves the number by more than eight points.
MIN_SAMPLE = 12

UNDERPOWERED = "UNDERPOWERED"

#: §202's cohorts. Each is (id, the attribute on a stored record, label).
COHORTS: tuple[tuple[str, str, str], ...] = (
    ("release", "intelligence_release_id", "Intelligence Release"),
    ("teaching_release", "teaching_release_id", "Teaching Release"),
    ("model_route", "model_route", "Model configuration"),
    ("scope", "portfolio_scope", "Portfolio scope"),
    ("language", "language", "Language"),
    ("case_family", "case_family", "Case family"),
    ("officer_level", "officer_level", "Officer level"),
    ("build", "build_sha", "Build"),
)

COHORT_FIELDS: dict[str, str] = {name: attr for name, attr, _ in COHORTS}


# ------------------------------------------------------ §201 the six tiles


@dataclass
class DimensionTile:
    """One of §201's six top-level tiles.

    Carries what a reader needs to decide whether to drill in: how it is
    doing, over how many records, how much of it was actually measured, and
    how many times it was the thing that failed.
    """

    dimension: str
    records: int = 0
    measured_records: int = 0
    scored: list[float] = field(default_factory=list)
    coverage: list[float] = field(default_factory=list)
    failures: int = 0
    warnings: int = 0
    critical_failures: int = 0
    #: Which subcomponents underneath it failed, and how often. §201's
    #: drill-down, precomputed so the tile can name the actual problem
    #: rather than sending the reader looking.
    subcomponent_failures: dict[str, int] = field(
        default_factory=lambda: defaultdict(int))

    @property
    def underpowered(self) -> bool:
        return len(self.scored) < MIN_SAMPLE

    @property
    def score(self) -> float | None:
        """None below the sample floor. §202's "confidence/sample evidence"
        as a refusal rather than a caveat: a number with a footnote gets
        read as a number."""
        if self.underpowered or not self.scored:
            return None
        return round(sum(self.scored) / len(self.scored), 1)

    @property
    def coverage_pct(self) -> float:
        return (round(sum(self.coverage) / len(self.coverage), 1)
                if self.coverage else 0.0)

    @property
    def state(self) -> str:
        if self.critical_failures:
            return "CRITICAL_FAILURES"
        if self.underpowered:
            return UNDERPOWERED
        if self.failures:
            return "FAILING"
        if self.warnings:
            return "WARNING"
        return "HEALTHY"

    def to_dict(self) -> dict[str, Any]:
        worst = sorted(self.subcomponent_failures.items(),
                       key=lambda kv: (-kv[1], kv[0]))[:5]
        return {
            "dimension": self.dimension,
            "label": dm.LABELS[self.dimension],
            "answers": dm.ANSWERS[self.dimension],
            "short": dm.SHORT[self.dimension],
            "weight": dm.WEIGHTS[self.dimension],
            "is_gate": bool(set(dm.SUBCOMPONENTS[self.dimension])
                            & set(dm.CRITICAL)),
            "records": self.records,
            "measured_records": self.measured_records,
            "sample": len(self.scored),
            "min_sample": MIN_SAMPLE,
            "underpowered": self.underpowered,
            "score": self.score,
            "score_label": rc.ASSURANCE_LABEL,
            "coverage_pct": self.coverage_pct,
            "failures": self.failures,
            "warnings": self.warnings,
            "critical_failures": self.critical_failures,
            "state": self.state,
            "subcomponents": len(dm.SUBCOMPONENTS[self.dimension]),
            "worst_subcomponents": [{"subcomponent": name, "failures": n}
                                    for name, n in worst],
        }


def tiles(records: list[st.StoredRecord]) -> list[dict[str, Any]]:
    """§201's six, in §178's order. Always six, even where nothing ran."""
    built = {d: DimensionTile(dimension=d) for d in dm.DIMENSIONS}
    for row in records:
        for name in dm.DIMENSIONS:
            tile = built[name]
            tile.records += 1
            stored = row.dimension_results.get(name)
            if not isinstance(stored, dict) or not stored.get("measured"):
                continue
            tile.measured_records += 1
            score = stored.get("score")
            if isinstance(score, int | float):
                tile.scored.append(float(score))
            coverage = stored.get("coverage_pct")
            if isinstance(coverage, int | float):
                tile.coverage.append(float(coverage))
            tile.failures += int(stored.get("failures") or 0)
            tile.warnings += int(stored.get("warnings") or 0)
        for check in row.checks:
            if check.get("outcome") != rc.FAIL:
                continue
            name = dm.dimension_of(check.get("subcomponent", ""))
            if not name:
                continue
            built[name].subcomponent_failures[
                check.get("subcomponent", "")] += 1
            if check.get("critical"):
                built[name].critical_failures += 1
    return [built[d].to_dict() for d in dm.DIMENSIONS]


# ------------------------------------------------------------ §202 trends


def _bucket_key(row: st.StoredRecord, attribute: str) -> str:
    return str(getattr(row, attribute, "") or "(none recorded)")


def trend(records: list[st.StoredRecord], cohort: str) -> dict[str, Any]:
    """§202's trend, cut by one cohort.

    Every bucket carries its own count, its own coverage, its own critical
    failures and its own staleness. A bucket that cannot support a score
    says so; it is not folded into a neighbour to make the line continuous.
    """
    attribute = COHORT_FIELDS.get(cohort)
    if attribute is None:
        return {"cohort": cohort, "known": False, "buckets": [],
                "cohorts": [{"id": c, "label": label}
                            for c, _, label in COHORTS],
                "note": f"{cohort!r} is not one of §202's cohorts."}

    grouped: dict[str, list[st.StoredRecord]] = defaultdict(list)
    for row in records:
        grouped[_bucket_key(row, attribute)].append(row)

    buckets: list[dict[str, Any]] = []
    for key in sorted(grouped):
        rows = grouped[key]
        scored = [r.operational_assurance for r in rows
                  if r.operational_assurance is not None]
        stale = len([r for r in rows if r.stale])
        buckets.append({
            "bucket": key,
            "records": len(rows),
            "scored": len(scored),
            "sample_sufficient": len(scored) >= MIN_SAMPLE,
            "min_sample": MIN_SAMPLE,
            # None rather than a comforting average over four records.
            "score": (round(sum(scored) / len(scored), 1)
                      if len(scored) >= MIN_SAMPLE else None),
            "score_label": rc.ASSURANCE_LABEL,
            "coverage_pct": (round(sum(r.coverage_pct for r in rows)
                                   / len(rows), 1) if rows else 0.0),
            "critical_failures": sum(r.critical_failure_count for r in rows),
            "failed_records": len([r for r in rows
                                   if r.overall_status == rc.FAILED]),
            "needs_review": len([r for r in rows
                                 if r.overall_status == rc.NEEDS_REVIEW]),
            "good_feedback": sum(r.good_feedback_count for r in rows),
            "bad_feedback": sum(r.bad_feedback_count for r in rows),
            "open_reruns": len([r for r in rows if r.superseded_by]),
            "stale_records": stale,
            "dimensions": tiles(rows),
        })
    return {"cohort": cohort, "known": True,
            "label": next(label for c, _, label in COHORTS if c == cohort),
            "cohorts": [{"id": c, "label": label} for c, _, label in COHORTS],
            "buckets": buckets, "min_sample": MIN_SAMPLE}


# ------------------------------------------------------- §203 contribution

GATE = "GATE"
WEIGHTED = "WEIGHTED"
UNMEASURED = "UNMEASURED"

ROLE_MEANS: dict[str, str] = {
    GATE: "This dimension can decide the overall status on its own: if its "
          "critical checks fail, the record fails whatever the other five "
          "say.",
    WEIGHTED: "This dimension contributes its weight to the score, once the "
              "gates have passed.",
    UNMEASURED: "Nothing in this dimension was measured, so it neither "
                "helped nor hurt. It is not a pass.",
}


def contribution(row: st.StoredRecord) -> dict[str, Any]:
    """§203. How each dimension affected THIS record's overall status.

    Reported as a role and a sentence rather than as six percentages. Where
    a gate decided the outcome the weights never ran, and printing them
    would describe an arithmetic that did not happen.
    """
    gated = bool(row.critical_failure_count)
    lines: list[dict[str, Any]] = []
    for name in dm.DIMENSIONS:
        stored = row.dimension_results.get(name) or {}
        measured = bool(stored.get("measured"))
        is_gate = bool(set(dm.SUBCOMPONENTS[name]) & set(dm.CRITICAL))
        failures = int(stored.get("failures") or 0)
        warnings = int(stored.get("warnings") or 0)

        if not measured:
            role, effect = UNMEASURED, "nothing measured"
        elif is_gate and failures:
            role, effect = GATE, "critical — failed, and that decided it"
        elif is_gate:
            role, effect = GATE, "critical — passed"
        elif failures:
            role, effect = WEIGHTED, "failed"
        elif warnings:
            role, effect = WEIGHTED, "warning"
        else:
            role, effect = WEIGHTED, "passed"

        detail = ""
        if warnings:
            detail = f"{warnings} warning(s)"
        if failures:
            detail = (f"{failures} failure(s)"
                      + (f", {warnings} warning(s)" if warnings else ""))

        lines.append({
            "dimension": name,
            "label": dm.LABELS[name],
            "role": role,
            "role_means": ROLE_MEANS[role],
            "effect": effect,
            "detail": detail,
            # Shown only where the weight is what actually applied. A gated
            # record never reached the weighted step.
            "weight_applied": (dm.WEIGHTS[name]
                               if role == WEIGHTED and not gated else None),
            "score": stored.get("score"),
            "measured": measured,
        })

    return {
        "assurance_record_id": row.assurance_record_id,
        "overall_status": row.overall_status,
        "status_means": rc.MEANS.get(row.overall_status, ""),
        "decided_by_gate": gated,
        "how": ("A critical check failed, so the overall status was decided "
                "by the gate. The weighted score was never computed."
                if gated else
                "No gate fired, so the overall status came from the weighted "
                "score over the measured dimensions."),
        "lines": lines,
        "equal_contribution": False,
        "weights_version": row.weights_version,
    }


def overview(records: list[st.StoredRecord] | None = None,
             limit: int = 500) -> dict[str, Any]:
    """§201's replacement for the flat wall, as one payload."""
    rows = records if records is not None else st.recent(limit=limit)
    scored = [r.operational_assurance for r in rows
              if r.operational_assurance is not None]
    return {
        "version": TRENDS_VERSION,
        "records": len(rows),
        "scored": len(scored),
        "dimensions": tiles(rows),
        # Deliberately no headline percentage. §201's point is that the
        # first thing on the screen should not be a number that averages
        # away the dimension that failed.
        "headline_score": None,
        "headline_note": ("The Overview leads with the six dimensions rather "
                          "than one number, because one number is what hides "
                          "the dimension that failed."),
        "failed_records": len([r for r in rows
                               if r.overall_status == rc.FAILED]),
        "needs_review_records": len([r for r in rows
                                     if r.overall_status == rc.NEEDS_REVIEW]),
        "stale_records": len([r for r in rows if r.stale]),
        "cohorts": [{"id": c, "label": label} for c, _, label in COHORTS],
        "min_sample": MIN_SAMPLE,
    }
