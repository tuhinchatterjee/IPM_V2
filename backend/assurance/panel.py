"""
"HOW CREDITPROBE PERFORMED". §188-§200.

    §197: "Why points were lost"

That heading is the one that makes the panel worth building. A score without
it is a grade; with it, it is a review. Every point this panel does not award
has a named reason attached to a named check, and a reader who disagrees can
disagree with the check rather than with the number.

What it shows, in the order §189 asks for
-------------------------------------------
The header first — what was asked, by whom, under which build and release,
with what overall assurance and coverage. Then the six dimension panels, each
with its status, its score, its coverage, what passed, what warned, what
failed and why points went. Then the turn-by-turn timeline, and then the
things a reader will look for next: what could not be established, what to do
about it, and how this compares with the last time the same question was run.

The two numbers stay apart
----------------------------
§184, enforced in `record.py` and repeated here: the header carries
OPERATIONAL ASSURANCE, and REFERENCE MATCH appears only where a reference
exists — as its own line, never folded into the first. A reader who sees one
number learns one thing; a reader who sees them merged learns something false.

Thread level as well as turn level
------------------------------------
§185. A thread's assurance is not the average of its turns: a thread with one
FAILED turn is a thread with a failure in it, and averaging that against nine
good turns produces a comfortable number describing a conversation that
contained a wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.assurance import dimensions as dm
from backend.assurance import record as rc

PANEL_VERSION = "1.0.0"

#: The button. §188 — one name everywhere, because two names for the same
#: thing is two things as far as a user is concerned.
BUTTON = "How CreditProbe performed"
TAB = "Validation"

#: Where it appears. Listed so a surface that forgot it is a visible gap.
PLACEMENTS: tuple[str, ...] = (
    "investigation_header", "answer_action_area",
    "studio_recent_investigations", "project_investigation_detail",
    "agentic_risk_case_investigation",
)


def why_points_were_lost(result: rc.DimensionResult) -> list[dict[str, Any]]:
    """§197. Every point not awarded, with the check that took it.

    A score without this is a grade. With it, it is a review — and a reader
    who disagrees can disagree with the check rather than with the number.
    """
    lost: list[dict[str, Any]] = []
    for check in result.checks:
        if check.outcome == rc.FAIL:
            lost.append({
                "subcomponent": check.subcomponent,
                "cost": "the whole check",
                "critical": check.critical,
                "why": check.detail or "the check failed",
                "evidence": list(check.evidence)})
        elif check.outcome == rc.WARNING:
            lost.append({
                "subcomponent": check.subcomponent,
                "cost": "half the check",
                "critical": False,
                "why": check.detail or "the check warned",
                "evidence": list(check.evidence)})
        elif check.outcome == rc.SKIPPED:
            lost.append({
                "subcomponent": check.subcomponent,
                # A skipped check does not cost points; it costs COVERAGE,
                # which is a different and often worse thing. Saying so stops
                # a reader assuming the score already accounts for it.
                "cost": "coverage, not points",
                "critical": check.subcomponent in dm.CRITICAL,
                "why": check.detail or "this check did not run",
                "evidence": []})
    return lost


def recommended(record: rc.Record) -> list[str]:
    """§198. What would move this record up a status.

    Written from what actually failed rather than from a generic list,
    because "improve grounding" is advice nobody can act on and "the figure
    17.4% in the second paragraph traces to no fact" is a task.
    """
    steps: list[str] = []
    if record.stale_reasons:
        steps.append("Re-run this Investigation: "
                     + "; ".join(record.stale_reasons))
    for name in record.critical_failures:
        steps.append(f"Fix {name.replace('_', ' ')} — a critical failure "
                     "blocks the whole record whatever else passed.")
    missing = record.skipped_mandatory
    if missing:
        steps.append(
            f"Run the {len(missing)} mandatory check(s) that did not: "
            + ", ".join(missing[:5]))
    if record.warnings and not steps:
        steps.append(
            f"Clear the {len(record.warnings)} warning(s) to move from "
            "validated-with-limitations to validated.")
    if not steps:
        steps.append("Nothing is outstanding on this record.")
    return steps


@dataclass
class Panel:
    """§189's review, assembled."""

    record: rc.Record
    weights: dm.Weights = field(default_factory=dm.Weights)

    def header(self) -> dict[str, Any]:
        """§189's top section. What was asked, under what, with what result."""
        verdict = self.record.overall(self.weights)
        return {
            "question": self.record.question,
            "scope": self.record.portfolio_scope,
            "user_id": self.record.user_id,
            "project_id": self.record.project_id,
            "at": self.record.created_at,
            "build_sha": self.record.build_sha,
            "intelligence_release_id": self.record.intelligence_release_id,
            "teaching_release_id": self.record.teaching_release_id,
            "model_roles": dict(self.record.model_roles),
            "served_models": dict(self.record.served_models),
            "officer_level": self.record.officer_level,
            "agent_roles": list(self.record.agent_roles),
            # §184: one line for what the runtime proved, a separate line for
            # a reference where one exists, and never the two merged.
            "operational_assurance": verdict["operational_assurance"],
            "operational_assurance_label":
                verdict["operational_assurance_label"],
            "overall_status": verdict["overall_status"],
            "status_means": verdict["status_means"],
            "coverage_pct": verdict["coverage_pct"],
            "critical_issues": self.record.critical_failures,
            "user_feedback": dict(self.record.user_feedback_summary),
            "reference_match": rc.reference_block(self.record.reference_match_pct,
                                             self.record.reference_source),
        }

    def dimensions(self) -> list[dict[str, Any]]:
        """§189's six panels, each with why its points went."""
        panels: list[dict[str, Any]] = []
        for result in self.record.by_dimension():
            body = result.to_dict()
            body["top_passed"] = [c.subcomponent for c in result.passed[:5]]
            body["warnings_detail"] = [
                {"subcomponent": c.subcomponent, "why": c.detail}
                for c in result.warnings]
            body["failures_detail"] = [
                {"subcomponent": c.subcomponent, "why": c.detail,
                 "critical": c.critical} for c in result.failures]
            body["why_points_were_lost"] = why_points_were_lost(result)
            body["status"] = _dimension_status(result)
            panels.append(body)
        return panels

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PANEL_VERSION,
            "button": BUTTON, "tab": TAB,
            "placements": list(PLACEMENTS),
            "header": self.header(),
            "dimensions": self.dimensions(),
            "limitations": list(self.record.limitations),
            "repairs": self.record.repair_count,
            "clarifications": self.record.clarification_count,
            "recommended_improvements": recommended(self.record),
            "record": self.record.to_dict(self.weights),
        }


def _dimension_status(result: rc.DimensionResult) -> str:
    """One dimension's own status. §203.

    A critical failure in a dimension makes that dimension FAILED whatever
    its score, for the same reason it makes the record FAILED: the dimension
    contains a check that says the answer asserts something untrue.
    """
    if result.critical_failures:
        return rc.FAILED
    if not result.counted:
        return rc.UNVERIFIED
    if result.failures:
        return rc.NEEDS_REVIEW
    if result.warnings:
        return rc.VALIDATED_WITH_LIMITATIONS
    score = result.score
    if score is not None and score >= rc.HIGH_ASSURANCE_AT \
            and result.coverage_pct >= 90.0:
        return rc.HIGH_ASSURANCE
    return rc.VALIDATED


# ---------------------------------------------------------------------------
# §185 — thread level
# ---------------------------------------------------------------------------

#: Worst-first. A thread is as good as its worst turn, because a conversation
#: containing a wrong answer is a conversation containing a wrong answer.
SEVERITY: tuple[str, ...] = (
    rc.FAILED, rc.STALE, rc.UNVERIFIED, rc.NEEDS_REVIEW,
    rc.VALIDATED_WITH_LIMITATIONS, rc.VALIDATED, rc.HIGH_ASSURANCE)


@dataclass
class Summary:
    """§185's thread-level assurance. Not an average."""

    investigation_id: str = ""
    records: list[rc.Record] = field(default_factory=list)
    weights: dm.Weights = field(default_factory=dm.Weights)

    @property
    def statuses(self) -> list[str]:
        return [r.overall(self.weights)["overall_status"]
                for r in self.records]

    @property
    def status(self) -> str:
        """The worst turn's status.

        Averaging one FAILED turn against nine good ones produces a
        comfortable number describing a conversation that contained a wrong
        answer.
        """
        found = set(self.statuses)
        for status in SEVERITY:
            if status in found:
                return status
        return rc.UNVERIFIED

    @property
    def critical_failures(self) -> list[str]:
        return sorted({name for r in self.records
                       for name in r.critical_failures})

    def to_dict(self) -> dict[str, Any]:
        turns = [
            {"turn": index + 1, "answer_id": r.answer_id,
             "question": r.question,
             **{k: r.overall(self.weights)[k]
                for k in ("overall_status", "operational_assurance",
                          "coverage_pct")},
             "critical_failures": r.critical_failures,
             "at": r.created_at}
            for index, r in enumerate(self.records)]
        return {
            "version": PANEL_VERSION,
            "investigation_id": self.investigation_id,
            "turns": turns,
            "turn_count": len(self.records),
            "status": self.status,
            "status_means": rc.MEANS.get(self.status, ""),
            "critical_failures": self.critical_failures,
            # Named so nobody wires an average in later.
            "averaged": False,
            "note": ("A thread is as good as its worst turn. A conversation "
                     "containing a wrong answer is a conversation containing "
                     "a wrong answer, whatever the other turns did."),
        }


__all__ = ["BUTTON", "PANEL_VERSION", "PLACEMENTS", "Panel", "SEVERITY",
           "Summary", "TAB", "recommended", "why_points_were_lost"]
