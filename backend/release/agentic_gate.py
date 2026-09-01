"""
The agentic release gate. §134.

    "Do not report the complete master phase ready unless: …"

Eleven conditions, and the reason they are separate from §128's thirteen
-------------------------------------------------------------------------
§128 gates an INTELLIGENCE RELEASE: is the intelligence correct enough to
promote? This gates the AGENTIC LAYER: does it actually run? They fail for
unrelated reasons and a release can pass one and fail the other — a product
with excellent judgement and a dead worker answers every question well and
never notices a deteriorating portfolio, which is precisely the failure Part E
was written after.

So they are two gates, and this one is release-blocking on its own.

Why "the worker is healthy" is not enough
-------------------------------------------
A healthy worker that has never picked up a job has not been shown to execute
anything. §134's first three conditions are about execution actually having
happened: a manual review completed, a scheduled review completed, and the
results were evidence-backed. A gate satisfied by a heartbeat would pass on
the day the queue stopped being drained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENTIC_GATE_VERSION = "1.0.0"

# ------------------------------------------------------- §134's eleven
WORKER_HEALTHY = "agent_worker_healthy"
MANUAL_REVIEW = "manual_portfolio_review_completes"
SCHEDULED_REVIEW = "scheduled_or_new_period_review_completes"
EVIDENCE_BACKED = "review_results_evidence_backed"
IDEMPOTENT = "cases_created_idempotently"
TRUTHFUL_ATTENTION = "requires_attention_reflects_the_latest_review"
RETRYABLE = "failed_runs_visible_and_retryable"
TRACE_AGREES = "agentic_trace_agrees_with_tasks_and_results"
APPROVAL = "no_material_side_effect_bypasses_approval"
FEEDBACK_STORED = "feedback_stored_reviewable_and_linked"
GOVERNED_SCORES = "scores_update_only_through_governed_adjudication"

CONDITIONS: tuple[str, ...] = (
    WORKER_HEALTHY, MANUAL_REVIEW, SCHEDULED_REVIEW, EVIDENCE_BACKED,
    IDEMPOTENT, TRUTHFUL_ATTENTION, RETRYABLE, TRACE_AGREES, APPROVAL,
    FEEDBACK_STORED, GOVERNED_SCORES,
)

ASKS: dict[str, str] = {
    WORKER_HEALTHY: "Is the agent worker beating, and is the queue moving?",
    MANUAL_REVIEW: "Did a manually started portfolio review complete?",
    SCHEDULED_REVIEW: "Did a scheduled or new-period review complete?",
    EVIDENCE_BACKED: "Does every case the review created cite the evidence "
                     "that produced it?",
    IDEMPOTENT: "Does running the same review twice produce one set of "
                "cases?",
    TRUTHFUL_ATTENTION: "Does Requires Attention reflect the latest review "
                        "rather than the case table?",
    RETRYABLE: "Is a failed run visible, with a safe reason and a retry?",
    TRACE_AGREES: "Does the agentic Trace match the tasks that actually ran?",
    APPROVAL: "Does every material side effect pass an approval gate?",
    FEEDBACK_STORED: "Is feedback stored, reviewable, and linked to the exact "
                     "answer?",
    GOVERNED_SCORES: "Do component scores move only through adjudication and "
                     "evaluation?",
}

#: The three that are about EXECUTION having happened rather than about a
#: component being correct. A gate satisfied by a heartbeat would pass on the
#: day the queue stopped being drained.
EXECUTION: frozenset[str] = frozenset({MANUAL_REVIEW, SCHEDULED_REVIEW,
                                        EVIDENCE_BACKED})

PASS = "PASS"
FAIL = "FAIL"
UNCHECKED = "UNCHECKED"

OUTCOMES: tuple[str, ...] = (PASS, FAIL, UNCHECKED)


@dataclass
class Finding:
    condition: str
    outcome: str = UNCHECKED
    detail: str = ""

    @property
    def asks(self) -> str:
        return ASKS.get(self.condition, "")

    @property
    def blocks(self) -> bool:
        return self.outcome != PASS

    def to_dict(self) -> dict[str, Any]:
        return {"condition": self.condition, "asks": self.asks,
                "outcome": self.outcome, "detail": self.detail,
                "about_execution": self.condition in EXECUTION,
                "blocks": self.blocks}


@dataclass
class Gate:
    """§134, and whether the master phase may be reported ready."""

    findings: list[Finding] = field(default_factory=list)

    def get(self, condition: str) -> Finding | None:
        return next((f for f in self.findings if f.condition == condition),
                    None)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.blocks]

    @property
    def ready(self) -> bool:
        return bool(self.findings) and not self.blocking

    def sentence(self) -> str:
        if self.ready:
            return ("All eleven agentic conditions pass. The agentic layer "
                    "genuinely executes and reports truthfully.")
        failed = [f for f in self.blocking if f.outcome == FAIL]
        unchecked = [f for f in self.blocking if f.outcome == UNCHECKED]
        parts: list[str] = []
        if failed:
            parts.append("failing: " + "; ".join(
                f.detail or f.condition for f in failed))
        if unchecked:
            parts.append("not checked: " + ", ".join(
                f.condition for f in unchecked))
        return ("The agentic layer is not ready to be reported complete — "
                + "; ".join(parts) + ".")

    def to_dict(self) -> dict[str, Any]:
        return {"version": AGENTIC_GATE_VERSION,
                "conditions": [f.to_dict() for f in self.findings],
                "ready": self.ready,
                "blocking": [f.condition for f in self.blocking],
                "sentence": self.sentence()}


def gate(outcomes: dict[str, str],
         details: dict[str, str] | None = None) -> Gate:
    """§134's eleven. Anything not supplied is UNCHECKED, never PASS."""
    details = details or {}
    result = Gate()
    for condition in CONDITIONS:
        outcome = outcomes.get(condition, UNCHECKED)
        if outcome not in OUTCOMES:
            raise ValueError(
                f"{outcome!r} is not an agentic gate outcome for {condition}")
        result.findings.append(Finding(condition=condition, outcome=outcome,
                                       detail=details.get(condition, "")))
    return result


def from_health(health: Any, *, manual_completed: bool = False,
                scheduled_completed: bool = False,
                cases_cite_evidence: bool = False,
                duplicate_cases: int = 0,
                failed_runs_retryable: bool = False,
                trace_consistent: bool = False,
                approvals_enforced: bool = False,
                feedback_linked: bool = False,
                scores_governed: bool = False) -> Gate:
    """The gate, from an AgenticHealth and the facts nothing else records.

    Reads the health object for the first condition rather than re-deriving
    it, and takes the rest as claims the caller has to establish — because
    "a manual review completed" is not visible in a heartbeat.
    """
    from backend.agentic import health as ah

    outcomes: dict[str, str] = {}
    details: dict[str, str] = {}

    operating = bool(getattr(health, "operating", False))
    outcomes[WORKER_HEALTHY] = PASS if operating else FAIL
    if not operating:
        details[WORKER_HEALTHY] = (
            str(getattr(health, "worst", "")) or "the worker is not executing")

    for condition, claim, why in (
            (MANUAL_REVIEW, manual_completed,
             "no manually started portfolio review has completed"),
            (SCHEDULED_REVIEW, scheduled_completed,
             "no scheduled or new-period review has completed"),
            (EVIDENCE_BACKED, cases_cite_evidence,
             "not every case cites the evidence that produced it"),
            (RETRYABLE, failed_runs_retryable,
             "a failed run is not visible with a safe reason and a retry"),
            (TRACE_AGREES, trace_consistent,
             "the agentic Trace does not match the tasks that ran"),
            (APPROVAL, approvals_enforced,
             "a material side effect can bypass approval"),
            (FEEDBACK_STORED, feedback_linked,
             "feedback is not linked to the exact answer"),
            (GOVERNED_SCORES, scores_governed,
             "a component score can move without adjudication")):
        outcomes[condition] = PASS if claim else FAIL
        if not claim:
            details[condition] = why

    outcomes[IDEMPOTENT] = PASS if not duplicate_cases else FAIL
    if duplicate_cases:
        details[IDEMPOTENT] = (
            f"{duplicate_cases} duplicate case(s) from repeated reviews")

    # Requires Attention is truthful when a validated review stands behind
    # what it says — which is exactly what `reviewed` means, and is false for
    # an empty case table with no run behind it.
    reviewed = bool(getattr(health, "reviewed", False))
    state = str(getattr(health, "latest_review_state", ""))
    outcomes[TRUTHFUL_ATTENTION] = (
        PASS if reviewed or state in (ah.NOT_RUN, ah.RUNNING, ah.QUEUED,
                                      ah.VALIDATING, ah.REVIEW_FAILED,
                                      ah.STALE, ah.CANCELLED)
        else FAIL)
    if outcomes[TRUTHFUL_ATTENTION] == FAIL:
        details[TRUTHFUL_ATTENTION] = (
            f"the latest review state is {state}, which does not stand behind "
            "what Requires Attention says")

    return gate(outcomes, details)


__all__ = ["AGENTIC_GATE_VERSION", "APPROVAL", "ASKS", "CONDITIONS",
           "EVIDENCE_BACKED", "EXECUTION", "FAIL", "FEEDBACK_STORED",
           "Finding", "GOVERNED_SCORES", "Gate", "IDEMPOTENT",
           "MANUAL_REVIEW", "OUTCOMES", "PASS", "RETRYABLE",
           "SCHEDULED_REVIEW", "TRACE_AGREES", "TRUTHFUL_ATTENTION",
           "UNCHECKED", "WORKER_HEALTHY", "from_health", "gate"]
