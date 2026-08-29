"""
Rerun and version comparison. §200.

The instruction that shapes this module
-----------------------------------------
    §200: "Do not compare different populations/periods without stating the
           difference."

Which is really a warning about the most useful-looking and most misleading
screen in the product. Two runs of "what moved in Contracting?", one before a
fix and one after, invite exactly one question — did it get better? — and the
honest answer is frequently "we cannot tell, because the second run also saw
three months of new data".

So this module's first job is not comparing. It is deciding whether a
comparison is legitimate at all, and saying so out loud when it is not:

    IMPROVED             the same question, the same data, and it got better.
    REGRESSED            the same question, the same data, and it got worse.
    UNCHANGED            the same question, the same data, no material move.
    CHANGED_DUE_TO_DATA  something underneath moved. The difference in the
                         answer is not evidence about the code.
    NOT_COMPARABLE       different question, scope, period or population.
                         Reported with the axis that differs, rather than as
                         a refusal a reader has to investigate.

Neither record is edited
-------------------------
The original keeps its verdict, its checks and its fingerprint. That is what
makes the comparison worth anything: a "fix" that improved a record by
rewriting it would produce a screen showing improvement in every case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.assurance import dimensions as dm
from backend.assurance import record as rc
from backend.assurance import store as st

COMPARISON_VERSION = "1.0.0"

IMPROVED = "IMPROVED"
REGRESSED = "REGRESSED"
UNCHANGED = "UNCHANGED"
CHANGED_DUE_TO_DATA = "CHANGED_DUE_TO_DATA"
NOT_COMPARABLE = "NOT_COMPARABLE"

VERDICTS: tuple[str, ...] = (IMPROVED, REGRESSED, UNCHANGED,
                             CHANGED_DUE_TO_DATA, NOT_COMPARABLE)

VERDICT_MEANS: dict[str, str] = {
    IMPROVED: "The same question over the same data, and the assurance "
              "improved.",
    REGRESSED: "The same question over the same data, and the assurance got "
               "worse. This is the one to act on.",
    UNCHANGED: "The same question over the same data, and nothing material "
               "moved.",
    CHANGED_DUE_TO_DATA: "The data underneath changed between the two runs, "
                         "so a difference in the answer is not evidence "
                         "about the change that was made.",
    NOT_COMPARABLE: "The two runs did not ask the same thing of the same "
                    "population, so comparing their scores would be "
                    "comparing two different analyses.",
}

#: The axes that have to match before a comparison means anything. §200's
#: "populations/periods" is the second and third of these; the first is the
#: one people forget, because a re-run after an edited question looks
#: identical on a list.
COMPARABILITY_AXES: tuple[tuple[str, str], ...] = (
    ("question", "the question asked"),
    ("portfolio_scope", "the portfolio scope"),
    ("language", "the language"),
)

#: A move smaller than this is noise, not a result. Assurance is computed
#: from counts of checks, so it moves in steps; anything under a point is a
#: rounding difference dressed as a finding.
MATERIAL_POINTS = 1.0


@dataclass
class Difference:
    """One axis, before and after."""

    axis: str
    before: Any
    after: Any
    changed: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"axis": self.axis, "before": self.before, "after": self.after,
                "changed": self.changed, "note": self.note}


def _data_moved(before: st.StoredRecord, after: st.StoredRecord) -> bool:
    """Did anything underneath the two runs change?

    Data versions first, then result fingerprints. A result fingerprint that
    differs while every data version matches is a genuine behavioural change,
    which is the case worth reporting; a data version that differs makes the
    result fingerprint uninformative.
    """
    was = before.context.get("data_versions") or {}
    now = after.context.get("data_versions") or {}
    if was and now and was != now:
        return True
    # Neither run recorded a data version: we cannot establish that the data
    # held still, and §200 says not to compare without stating the
    # difference. Unknown is not "the same".
    return not (was or now)


def comparable(before: st.StoredRecord,
               after: st.StoredRecord) -> tuple[bool, list[str]]:
    """Whether these two runs are asking the same thing. §200's guard."""
    problems: list[str] = []
    for axis, label in COMPARABILITY_AXES:
        was = str(getattr(before, axis, "") or "").strip()
        now = str(getattr(after, axis, "") or "").strip()
        if was != now:
            problems.append(f"{label} differs: {was or '(none)'} → "
                            f"{now or '(none)'}")
    return (not problems), problems


def _status_rank(status: str) -> int:
    """Worst to best. Used only for direction, never shown as a number."""
    order = (rc.FAILED, rc.UNVERIFIED, rc.NEEDS_REVIEW,
             rc.VALIDATED_WITH_LIMITATIONS, rc.VALIDATED, rc.HIGH_ASSURANCE)
    return order.index(status) if status in order else 0


def dimension_diff(before: st.StoredRecord,
                   after: st.StoredRecord) -> list[dict[str, Any]]:
    """The six, side by side. §200's "six dimensions"."""
    rows: list[dict[str, Any]] = []
    for name in dm.DIMENSIONS:
        was = before.dimension_results.get(name) or {}
        now = after.dimension_results.get(name) or {}
        was_score = was.get("score")
        now_score = now.get("score")
        move: float | None = None
        if isinstance(was_score, int | float) and isinstance(now_score,
                                                             int | float):
            move = round(float(now_score) - float(was_score), 1)
        rows.append({
            "dimension": name,
            "label": dm.LABELS[name],
            "before": {"score": was_score,
                       "failures": was.get("failures", 0),
                       "warnings": was.get("warnings", 0),
                       "measured": bool(was.get("measured", False))},
            "after": {"score": now_score,
                      "failures": now.get("failures", 0),
                      "warnings": now.get("warnings", 0),
                      "measured": bool(now.get("measured", False))},
            "move": move,
            # A dimension that was measured before and is not now has not
            # improved by going quiet. Saying so stops a screen that reads
            # like progress from describing a lost check.
            "lost_coverage": bool(was.get("measured") and
                                  not now.get("measured")),
        })
    return rows


@dataclass
class Comparison:
    """§200's comparison, assembled."""

    before: st.StoredRecord
    after: st.StoredRecord
    verdict: str = NOT_COMPARABLE
    reasons: list[str] = field(default_factory=list)
    differences: list[Difference] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "verdict_means": VERDICT_MEANS.get(self.verdict, ""),
            "verdicts": [{"id": v, "means": VERDICT_MEANS[v]}
                         for v in VERDICTS],
            "reasons": list(self.reasons),
            "before": {
                "assurance_record_id": self.before.assurance_record_id,
                "at": self.before.created_at,
                "question": self.before.question,
                "overall_status": self.before.overall_status,
                "operational_assurance": self.before.operational_assurance,
                "coverage_pct": round(self.before.coverage_pct, 1),
                "critical_failures": self.before.critical_failure_count,
                "duration_ms": self.before.duration_ms,
                "cost_usd": round(self.before.cost_usd, 4),
                "model_route": self.before.model_route,
                "teaching_release_id": self.before.teaching_release_id,
                "build_sha": self.before.build_sha,
                "good_feedback": self.before.good_feedback_count,
                "bad_feedback": self.before.bad_feedback_count,
            },
            "after": {
                "assurance_record_id": self.after.assurance_record_id,
                "at": self.after.created_at,
                "question": self.after.question,
                "overall_status": self.after.overall_status,
                "operational_assurance": self.after.operational_assurance,
                "coverage_pct": round(self.after.coverage_pct, 1),
                "critical_failures": self.after.critical_failure_count,
                "duration_ms": self.after.duration_ms,
                "cost_usd": round(self.after.cost_usd, 4),
                "model_route": self.after.model_route,
                "teaching_release_id": self.after.teaching_release_id,
                "build_sha": self.after.build_sha,
                "good_feedback": self.after.good_feedback_count,
                "bad_feedback": self.after.bad_feedback_count,
            },
            "dimensions": dimension_diff(self.before, self.after),
            "differences": [d.to_dict() for d in self.differences],
            "objectives": {
                "before": dict(self.before.objective_coverage),
                "after": dict(self.after.objective_coverage),
            },
            # §184 survives the comparison too: two operational assurance
            # figures compared with each other are still not an accuracy.
            "operational_assurance_label": rc.ASSURANCE_LABEL,
        }


def _differences(before: st.StoredRecord,
                 after: st.StoredRecord) -> list[Difference]:
    axes: list[Difference] = []
    for axis, label in (("build_sha", "build"),
                        ("teaching_release_id", "Teaching Release"),
                        ("intelligence_release_id", "Intelligence Release"),
                        ("model_route", "model route"),
                        ("officer_level", "officer level"),
                        ("blueprint_id", "blueprint")):
        was = getattr(before, axis)
        now = getattr(after, axis)
        axes.append(Difference(axis=label, before=was, after=now,
                               changed=was != now))
    was_data = before.context.get("data_versions") or {}
    now_data = after.context.get("data_versions") or {}
    axes.append(Difference(
        axis="data versions", before=was_data, after=now_data,
        changed=was_data != now_data,
        note=("Neither run recorded a data version, so it cannot be "
              "established that the data held still."
              if not (was_data or now_data) else "")))
    for axis, label in COMPARABILITY_AXES:
        was = getattr(before, axis)
        now = getattr(after, axis)
        if was != now:
            axes.append(Difference(axis=label, before=was, after=now,
                                   changed=True,
                                   note="This axis makes the two runs "
                                        "incomparable."))
    return axes


def compare(before: st.StoredRecord, after: st.StoredRecord) -> Comparison:
    """§200's five verdicts, in the order that keeps them honest.

    Comparability first, then whether the ground moved, and only then
    whether the number went up. Any other order produces a screen that says
    IMPROVED about two runs that analysed different portfolios.
    """
    result = Comparison(before=before, after=after,
                        differences=_differences(before, after))

    ok, problems = comparable(before, after)
    if not ok:
        result.verdict = NOT_COMPARABLE
        result.reasons = problems
        return result

    if _data_moved(before, after):
        result.verdict = CHANGED_DUE_TO_DATA
        was = before.context.get("data_versions") or {}
        now = after.context.get("data_versions") or {}
        result.reasons = (
            [f"Data versions changed: {sorted(was.items())} → "
             f"{sorted(now.items())}"] if (was or now) else
            ["Neither run recorded which data version it read, so a "
             "difference between them cannot be attributed to the change "
             "that was made."])
        return result

    # A critical failure appearing or clearing outranks any movement in the
    # score, because it is the thing the score is not allowed to average away.
    if after.critical_failure_count > before.critical_failure_count:
        result.verdict = REGRESSED
        result.reasons = [
            f"Critical failures rose from {before.critical_failure_count} to "
            f"{after.critical_failure_count}."]
        return result
    if after.critical_failure_count < before.critical_failure_count:
        result.verdict = IMPROVED
        result.reasons = [
            f"Critical failures fell from {before.critical_failure_count} to "
            f"{after.critical_failure_count}."]
        return result

    was_rank = _status_rank(before.overall_status)
    now_rank = _status_rank(after.overall_status)
    if now_rank != was_rank:
        result.verdict = IMPROVED if now_rank > was_rank else REGRESSED
        result.reasons = [f"Status moved from {before.overall_status} to "
                          f"{after.overall_status}."]
        return result

    was_score = before.operational_assurance
    now_score = after.operational_assurance
    if was_score is None or now_score is None:
        # One side has no number. That is not "unchanged" — it is a state
        # where the gates refused to score at least one of the two runs.
        result.verdict = UNCHANGED
        result.reasons = [
            "Neither run's status changed. At least one of them was not "
            "scored, so there is no numeric movement to report."]
        return result

    move = round(now_score - was_score, 1)
    if abs(move) < MATERIAL_POINTS:
        result.verdict = UNCHANGED
        result.reasons = [f"Operational assurance moved by {move:+.1f} "
                          "points, which is below the material threshold."]
    else:
        result.verdict = IMPROVED if move > 0 else REGRESSED
        result.reasons = [f"Operational assurance moved by {move:+.1f} "
                          "points."]
    return result


def compare_ids(before_id: str, after_id: str) -> Comparison | None:
    """The two records by id, or None where either is missing."""
    before = st.get(before_id)
    after = st.get(after_id)
    if before is None or after is None:
        return None
    return compare(before, after)
