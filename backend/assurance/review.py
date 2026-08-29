"""
The Investigation Assurance Review, over stored records. §189-§199.

Why this is separate from `panel.py`
--------------------------------------
`panel.py` renders a record that is still in memory — the turn that has just
finished. This module renders records that came back out of the database,
which is a different job in one important way: a stored record's verdict was
computed under the weights and gates in force when it was written, and
§208 says that verdict is not recomputed. So nothing here calls `overall()`.
The status, the score and the coverage are values read from the row, and the
only thing computed at read time is staleness — which is a statement about
the runtime, not about the record.

The six sections §191-§196 ask for
------------------------------------
Each dimension gets a section listing what it examined, drawn from the
checks that ran and the context the record captured. The sections do not
invent content: a fact the record did not capture is reported as not
captured, because "not recorded" and "did not happen" are different, and a
review that conflates them is worse than no review.

§195's exception, made explicit
---------------------------------
    §195: "If no agentic work was required, mark NOT_APPLICABLE with
           deterministic reason."

Which is the one place in Part F where NOT_APPLICABLE is the right answer
rather than the dangerous one, and it is safe here precisely because the
reason is deterministic: there is no agentic run id on the record. §183's
rule is not "never say not-applicable" — it is "never say it without
establishing it", and an absent run id establishes it.

§199, and the line it will not cross
--------------------------------------
    §199: "Raw feedback does not alter the assurance score or component
           validation score."

Feedback appears in this review in its own section, with RAW USER FEEDBACK
and ADJUDICATED FINDING kept apart. Nothing in the feedback section is read
by anything that produces a score. That is not a policy here; it is the
shape of the code — the score fields are read from the stored row, and no
function in this module writes to them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.assurance import access as ac
from backend.assurance import dimensions as dm
from backend.assurance import panel as pn
from backend.assurance import record as rc
from backend.assurance import store as st

REVIEW_VERSION = "1.0.0"

# --------------------------------------------------- §191-§196 the sections

#: What each dimension's section examines, in the words §191-§196 use. The
#: list is the section's contract: an item present with no value recorded is
#: shown as "not recorded", which is how a reviewer discovers that a check
#: they assumed was running is not.
EXAMINES: dict[str, tuple[str, ...]] = {
    dm.UNDERSTANDING: (
        "detected capability", "conversation action", "same-turn referents",
        "prior-turn referents", "objectives extracted", "ambiguity decisions",
        "scope and language", "entities and cohorts",
        "context carried or reset", "validation results",
        "failures and repairs"),
    dm.DESIGN: (
        "objective coverage", "selected blueprint or method",
        "selected concepts", "datasets", "relationships", "periods", "grain",
        "population", "filters", "plan and task DAG",
        "teaching cases retrieved", "model route", "validation",
        "unavailable or omitted objectives"),
    dm.COMPUTATION: (
        "query, IR and kernel", "execution status",
        "row, customer and account counts", "joins and reconciliation",
        "result reconciliation", "business invariants",
        "mathematical invariants", "evidence facts",
        "grounded entities and figures", "scope and permission checks",
        "cached or reused result proof", "failed and skipped checks"),
    dm.JUDGMENT: (
        "bottom line directness", "materiality", "drivers",
        "breadth and concentration", "persistence and noise", "exceptions",
        "contradiction diagnosis", "causal-language check", "limitations",
        "next analyses", "visualization selected and rejected",
        "number formatting", "table ordering", "trace clarity",
        "client-presentability rubric"),
    dm.AGENTIC: (
        "officer selection", "selected agents", "orchestration plan", "tasks",
        "handoffs", "challenges", "assurance-agent result",
        "budgets and limits", "worker and queue state",
        "proactive review and case creation", "human approvals",
        "workflow actions", "agentic trace consistency"),
    dm.RELIABILITY: (
        "provider and worker health", "error handling", "retries", "latency",
        "tokens and cost", "navigation and back", "exports",
        "UI performance", "accessibility", "locale and RTL",
        "feedback capture", "audit completeness", "stale status",
        "known operational limitations"),
}

#: §191: "Do not expose hidden chain-of-thought." Named here so the rule
#: travels with the surface that would be tempted to break it.
NEVER_SHOWN: tuple[str, ...] = (
    "hidden chain of thought", "raw model reasoning", "system prompt text",
    "sealed holdout answers",
)

#: §190's actions on a turn.
TURN_ACTIONS: tuple[str, ...] = (
    "OPEN_ANSWER", "OPEN_TRACE", "OPEN_PLAN", "OPEN_RESULT", "OPEN_FEEDBACK",
    "COMPARE_WITH_RERUN",
)


def _check_rows(row: st.StoredRecord, dimension: str) -> list[dict[str, Any]]:
    """Every check in one dimension, as stored."""
    rows: list[dict[str, Any]] = []
    for check in row.checks:
        if dm.dimension_of(check.get("subcomponent", "")) != dimension:
            continue
        rows.append({
            "subcomponent": check.get("subcomponent", ""),
            "outcome": check.get("outcome", ""),
            "detail": check.get("detail", ""),
            "critical": bool(check.get("critical")),
            "evidence": list(check.get("evidence") or []),
            "not_applicable_because": check.get("not_applicable_because", ""),
        })
    # Mandatory checks this record never carried. §183: absent is skipped,
    # and a section that silently omitted them would hide exactly that.
    seen = {c["subcomponent"] for c in rows}
    for name in dm.SUBCOMPONENTS[dimension]:
        if name in seen or name not in dm.MANDATORY:
            continue
        rows.append({"subcomponent": name, "outcome": rc.SKIPPED,
                     "detail": "This check did not run.", "critical":
                         name in dm.CRITICAL, "evidence": [],
                     "not_applicable_because": ""})
    return sorted(rows, key=lambda r: r["subcomponent"])


def _agentic_applicability(row: st.StoredRecord) -> dict[str, Any]:
    """§195's deterministic exception.

    Not applicable is established by the ABSENCE OF AN AGENTIC RUN, which is
    a fact on the record rather than a judgement about the question. Where a
    run id IS present, the section is applicable whatever its checks say.
    """
    if row.agentic_run_id or (row.context.get("agent_roles") or []):
        return {"applicable": True, "reason": ""}
    return {
        "applicable": False,
        "outcome": rc.NOT_APPLICABLE,
        "reason": ("No agentic run is recorded against this answer and no "
                   "agent roles were engaged, so there was no agentic work "
                   "to assess. This is established from the record rather "
                   "than assumed."),
    }


def dimension_section(row: st.StoredRecord, dimension: str) -> dict[str, Any]:
    """One of §191-§196, from what the record actually captured."""
    stored = row.dimension_results.get(dimension) or {}
    checks = _check_rows(row, dimension)
    section: dict[str, Any] = {
        "dimension": dimension,
        "label": dm.LABELS[dimension],
        "answers": dm.ANSWERS[dimension],
        "short": dm.SHORT[dimension],
        "weight": dm.WEIGHTS[dimension],
        "measured": bool(stored.get("measured", False)),
        "status": stored.get("status") or _stored_status(stored),
        "score": stored.get("score"),
        "score_label": rc.ASSURANCE_LABEL,
        "coverage_pct": stored.get("coverage_pct", 0.0),
        "examines": list(EXAMINES[dimension]),
        "checks": checks,
        "passed": [c["subcomponent"] for c in checks
                   if c["outcome"] == rc.PASS][:8],
        "warnings": [{"subcomponent": c["subcomponent"], "why": c["detail"]}
                     for c in checks if c["outcome"] == rc.WARNING],
        "failures": [{"subcomponent": c["subcomponent"], "why": c["detail"],
                      "critical": c["critical"]}
                     for c in checks if c["outcome"] == rc.FAIL],
        "skipped": [c["subcomponent"] for c in checks
                    if c["outcome"] == rc.SKIPPED],
        "never_shown": list(NEVER_SHOWN),
    }
    section["why_points_were_lost"] = _lost_from_stored(checks)
    if dimension == dm.AGENTIC:
        section["applicability"] = _agentic_applicability(row)
    if dimension == dm.DESIGN:
        section["objective_coverage"] = dict(row.objective_coverage)
    if dimension == dm.RELIABILITY:
        section["latency_ms"] = row.duration_ms
        section["tokens"] = {"in": row.tokens_in, "out": row.tokens_out}
        section["cost_usd"] = round(row.cost_usd, 4)
        section["stale"] = row.stale
        section["stale_reasons"] = list(row.stale_reasons)
        section["known_limitations"] = list(row.limitations)
    return section


def _stored_status(stored: dict[str, Any]) -> str:
    if not stored.get("measured"):
        return rc.UNVERIFIED
    if stored.get("failures"):
        return rc.NEEDS_REVIEW
    if stored.get("warnings"):
        return rc.VALIDATED_WITH_LIMITATIONS
    return rc.VALIDATED


def _lost_from_stored(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """§197 over stored checks. Same wording as `panel.why_points_were_lost`
    so a reader sees one vocabulary whether they opened a live turn or a
    record from last month."""
    lost: list[dict[str, Any]] = []
    for check in checks:
        outcome = check["outcome"]
        if outcome == rc.FAIL:
            cost = "the whole check"
        elif outcome == rc.WARNING:
            cost = "half the check"
        elif outcome == rc.SKIPPED:
            cost = "coverage, not points"
        else:
            continue
        lost.append({"subcomponent": check["subcomponent"], "cost": cost,
                     "critical": check["critical"],
                     "why": check["detail"] or f"the check was {outcome}",
                     "evidence": check["evidence"]})
    return lost


# ------------------------------------------------------------ §198 advice

#: §198's twelve. Mapped from the subcomponent that failed, so the advice
#: names a next action rather than a category. Anything unmapped falls back
#: to a generic line that still says WHICH check failed.
IMPROVEMENTS: dict[str, str] = {
    "capability_intent": "Add or edit a Teaching Case covering this phrasing.",
    "objective_extraction": "Add a Teaching Case with this clause structure.",
    "referent_resolution": "Add a Teaching Case for this follow-up shape.",
    "ontology_term_match": "Add an ontology alias for the term that missed.",
    "relationship_match": "Fix or add the relationship this analysis needed.",
    "blueprint_selection": "Improve the Investigation Blueprint for this "
                           "question family.",
    "method_selection": "Add or correct the analysis method.",
    "model_route_fit": "Adjust the routing threshold for this complexity.",
    "figure_grounding": "Add a regression for this answer and review the "
                        "interpretation contract.",
    "business_invariants": "Inspect data quality: the components did not "
                           "reconcile to the total.",
    "chart_selection": "Change the visualization rule for this result shape.",
    "agent_selection": "Review agent selection for this officer level.",
    "prompt_contract": "Improve the prompt for this capability.",
}


def improvements(row: st.StoredRecord) -> list[dict[str, str]]:
    """§198. Recommendations, explicitly not automatic changes."""
    steps: list[dict[str, str]] = []
    for check in row.checks:
        if check.get("outcome") not in (rc.FAIL, rc.WARNING):
            continue
        name = check.get("subcomponent", "")
        steps.append({
            "subcomponent": name,
            "because": check.get("detail", "") or "the check did not pass",
            "suggestion": IMPROVEMENTS.get(
                name, f"Review {name.replace('_', ' ')} and add a regression "
                      "covering it."),
        })
    if row.stale:
        steps.append({"subcomponent": "release",
                      "because": "; ".join(row.stale_reasons),
                      "suggestion": "Re-run this Investigation on the "
                                    "current release and compare."})
    return steps


# ------------------------------------------------------- §199 the feedback


def feedback_section(row: st.StoredRecord,
                     adjudications: list[dict[str, Any]] | None = None
                     ) -> dict[str, Any]:
    """§199. The two kinds of feedback, kept apart.

    RAW USER FEEDBACK is what somebody pressed. ADJUDICATED FINDING is what
    a reviewer concluded after looking. Merging them turns an opinion into a
    finding, which is the single most common way a feedback loop poisons the
    thing it was built to improve.
    """
    return {
        "raw_user_feedback": {
            "good": row.good_feedback_count,
            "bad": row.bad_feedback_count,
            "changes_score": False,
            "note": ("Raw feedback is recorded against this answer and "
                     "changes no assurance or component validation score. It "
                     "changes where a reviewer looks."),
        },
        "adjudicated_findings": list(adjudications or []),
        "adjudication_note": ("A finding appears here only after a reviewer "
                             "has assessed the feedback. Until then the "
                             "feedback is an opinion about the answer, not "
                             "evidence about the system."),
    }


# ------------------------------------------------------------ the assembly


@dataclass
class InvestigationReview:
    """§189's review of one turn, plus §190's timeline of the thread."""

    record: st.StoredRecord
    thread: list[st.StoredRecord] = field(default_factory=list)
    decision: ac.Decision = field(
        default_factory=lambda: ac.Decision(ac.SUMMARY, "not evaluated"))
    adjudications: list[dict[str, Any]] = field(default_factory=list)

    def header(self) -> dict[str, Any]:
        """§189's top section, from the stored verdict rather than a fresh
        computation."""
        row = self.record
        return {
            "assurance_record_id": row.assurance_record_id,
            "investigation_id": row.investigation_id,
            "title": row.question or "(no question recorded)",
            "scope": row.portfolio_scope,
            "language": row.language,
            "user_id": row.user_id,
            "project_id": row.project_id,
            "at": row.created_at,
            "build_sha": row.build_sha,
            "intelligence_release_id": row.intelligence_release_id,
            "teaching_release_id": row.teaching_release_id,
            "model_roles": row.context.get("model_roles", {}),
            "served_models": row.context.get("served_models", {}),
            "officer_level": row.officer_level,
            "agent_roles": row.context.get("agent_roles", []),
            "overall_status": row.overall_status,
            "status_now": row.status_now,
            "status_means": rc.MEANS.get(row.overall_status, ""),
            # §184, once more, at the surface a reader is most likely to
            # screenshot.
            "operational_assurance": row.operational_assurance,
            "operational_assurance_label": rc.ASSURANCE_LABEL,
            "coverage_pct": round(row.coverage_pct, 1),
            "reference_match": rc.reference_block(row.reference_match_pct,
                                                  row.reference_source),
            "critical_issues": row.critical_failure_count,
            "warnings": row.warning_count,
            "user_feedback": {"good": row.good_feedback_count,
                              "bad": row.bad_feedback_count},
            "stale": row.stale,
            "stale_reasons": list(row.stale_reasons),
            "weights_version": row.weights_version,
        }

    def dimensions(self) -> list[dict[str, Any]]:
        return [dimension_section(self.record, d) for d in dm.DIMENSIONS]

    def timeline(self) -> list[dict[str, Any]]:
        """§190's turn-by-turn timeline over the whole thread."""
        turns: list[dict[str, Any]] = []
        for row in sorted(self.thread or [self.record],
                          key=lambda r: (r.turn_index, r.created_at)):
            turns.append({
                "turn": row.turn_index + 1,
                "assurance_record_id": row.assurance_record_id,
                "question": row.question,
                "answer_type": row.answer_type,
                "answer_id": row.answer_id,
                "at": row.created_at,
                "scope": row.portfolio_scope,
                "officer_level": row.officer_level,
                "model_route": row.model_route,
                "analyses": row.context.get("analysis_run_ids", []),
                "dimensions": [
                    {"dimension": d, "short": dm.SHORT[d],
                     "state": _compact_state(row.dimension_results.get(d))}
                    for d in dm.DIMENSIONS],
                "objective_coverage": dict(row.objective_coverage),
                "overall_status": row.overall_status,
                "operational_assurance": row.operational_assurance,
                "coverage_pct": round(row.coverage_pct, 1),
                "repairs": row.repair_count,
                "clarifications": row.clarification_count,
                "limitations": list(row.limitations),
                "feedback": {"good": row.good_feedback_count,
                             "bad": row.bad_feedback_count},
                "trace_id": row.trace_id,
                "run_ids": row.context.get("analysis_run_ids", []),
                "is_current": row.assurance_record_id ==
                self.record.assurance_record_id,
                "superseded_by": row.superseded_by,
                "rerun_of": row.rerun_of,
                "actions": [a for a in TURN_ACTIONS
                            if a != "COMPARE_WITH_RERUN"
                            or bool(row.superseded_by or row.rerun_of)],
            })
        return turns

    def thread_status(self) -> dict[str, Any]:
        """§185 over stored records: the worst turn, never the mean.

        A failed turn later corrected still counts. §210 asks for exactly
        this: "failed earlier turn retained".
        """
        rows = self.thread or [self.record]
        found = {r.status_now for r in rows}
        status = next((s for s in pn.SEVERITY if s in found), rc.UNVERIFIED)
        return {
            "status": status,
            "status_means": rc.MEANS.get(status, ""),
            "turns": len(rows),
            "failed_turns": [r.assurance_record_id for r in rows
                             if r.overall_status == rc.FAILED],
            "averaged": False,
            "note": ("A thread is as good as its worst turn, and a turn that "
                     "failed and was later re-run still failed."),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "version": REVIEW_VERSION,
            "button": pn.BUTTON,
            "tab": pn.TAB,
            "header": self.header(),
            "dimensions": self.dimensions(),
            "timeline": self.timeline(),
            "thread": self.thread_status(),
            "recommended_improvements": improvements(self.record),
            "feedback": feedback_section(self.record, self.adjudications),
            "limitations": list(self.record.limitations),
            "integrity": st.verify(self.record),
            "access": self.decision.to_dict(),
            "prompt_versions": self.record.context.get("prompt_versions", {}),
            "retrieved_teaching_case_ids": self.record.context.get(
                "retrieved_teaching_case_ids", []),
            "served_models": self.record.context.get("served_models", {}),
            "method_versions": self.record.context.get("method_versions", {}),
            "relationship_versions": self.record.context.get(
                "relationship_versions", {}),
            "result_fingerprints": self.record.context.get(
                "result_fingerprints", []),
            "routing_policy_version": self.record.routing_policy_version,
            "agentic_run_id": self.record.agentic_run_id,
        }
        return ac.redact(payload, self.decision)


def _compact_state(stored: Any) -> str:
    if not isinstance(stored, dict) or not stored.get("measured"):
        return "UNMEASURED"
    if stored.get("failures"):
        return "FAILED"
    if stored.get("warnings"):
        return "WARNING"
    return "PASSED"


def build(viewer: ac.Viewer, record_id: str) -> InvestigationReview | None:
    """Load one review, refusing where the viewer may not see it.

    Returns None both for "no such record" and for "not yours". A caller
    that could tell them apart could enumerate the estate's Investigation
    ids by watching which refusals were 403 and which were 404.
    """
    row = st.get(record_id)
    if row is None:
        return None
    decision = ac.may_read(viewer, ac.Subject(
        assurance_record_id=row.assurance_record_id,
        investigation_id=row.investigation_id,
        project_id=row.project_id, owner_user_id=row.user_id,
        tenant_id=row.tenant_id))
    if not decision.allowed:
        return None
    thread = st.for_investigation(row.investigation_id)
    return InvestigationReview(record=row, thread=thread, decision=decision)
