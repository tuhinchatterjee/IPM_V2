"""
The server-owned state machine. Specification section 11.

The model requests transitions; this module alone approves them. A response
cannot set its own attempts remaining, bypass a prior refusal, reopen a
stopped request or acquire another module's data — because none of those are
expressible here. `Machine.advance` is the only way a request changes state,
it checks the edge against `TRANSITIONS`, and a terminal state has no
outgoing edges at all.

Why an explicit table rather than flags
---------------------------------------
Cockpit V2 had `executor.STAGES`, a list of names for progress display. Names
are not a machine: nothing stopped a stage running twice or out of order. The
guardrails in section 9 are only real if the states they attach to are real,
so the edges are enumerated and a violation raises rather than logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---- working states ---------------------------------------------------

RECEIVED = "RECEIVED"
NORMALIZING_1 = "NORMALIZING_1"
NORMALIZING_2 = "NORMALIZING_2"
BUILDING_CONTEXT = "BUILDING_CONTEXT"
FUNCTIONALITY_ASSESSMENT = "FUNCTIONALITY_ASSESSMENT"
PLANNING = "PLANNING"
VALIDATING = "VALIDATING"
EXECUTING = "EXECUTING"
REVIEWING = "REVIEWING"
ANSWERING = "ANSWERING"
SUMMARIZING = "SUMMARIZING"

WORKING: tuple[str, ...] = (
    RECEIVED, NORMALIZING_1, NORMALIZING_2, BUILDING_CONTEXT,
    FUNCTIONALITY_ASSESSMENT, PLANNING, VALIDATING, EXECUTING, REVIEWING,
    ANSWERING, SUMMARIZING)

# ---- terminal statuses ------------------------------------------------

COMPLETED = "COMPLETED"
REDIRECTED = "REDIRECTED"
CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
EXECUTION_FAILED = "EXECUTION_FAILED"
UNSUPPORTED = "UNSUPPORTED"
PARTIAL = "PARTIAL"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"
TIMED_OUT = "TIMED_OUT"
CANCELLED = "CANCELLED"
PROVIDER_ERROR = "PROVIDER_ERROR"
#: The Cockpit's model roles are not configured, or the provider will not
#: serve what they name. Distinct from PROVIDER_ERROR because the remedy is
#: different: PROVIDER_ERROR is "the provider did not answer", these two are
#: "nobody has said which model should answer" and "the model named does not
#: exist here". An operator needs to be told which.
MODEL_CONFIGURATION_MISSING = "MODEL_CONFIGURATION_MISSING"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"

TERMINAL: tuple[str, ...] = (
    COMPLETED, REDIRECTED, CLARIFICATION_REQUIRED, INSUFFICIENT_DATA,
    EXECUTION_FAILED, UNSUPPORTED, PARTIAL, BUDGET_EXCEEDED,
    CONTEXT_TOO_LARGE, TIMED_OUT, CANCELLED, PROVIDER_ERROR,
    MODEL_CONFIGURATION_MISSING, MODEL_UNAVAILABLE)

ALL_STATES: tuple[str, ...] = WORKING + TERMINAL

#: A stop that happened before any analysis was possible, versus one that
#: happened with findings in hand. The renderer says different things.
STOPPED_WITHOUT_ANSWER = frozenset({
    REDIRECTED, CLARIFICATION_REQUIRED, INSUFFICIENT_DATA, EXECUTION_FAILED,
    UNSUPPORTED, BUDGET_EXCEEDED, CONTEXT_TOO_LARGE, TIMED_OUT, CANCELLED,
    PROVIDER_ERROR, MODEL_CONFIGURATION_MISSING, MODEL_UNAVAILABLE})

#: Every state may stop for one of these, because every one of them can happen
#: at any point: the deadline expires, the user cancels, the provider fails,
#: or a budget preflight refuses the next call.
_ALWAYS = (BUDGET_EXCEEDED, TIMED_OUT, CANCELLED, PROVIDER_ERROR,
           CONTEXT_TOO_LARGE, MODEL_CONFIGURATION_MISSING, MODEL_UNAVAILABLE)

#: The permitted edges. Read this as the specification's section 11 diagram.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    RECEIVED: (NORMALIZING_1,) + _ALWAYS,
    # A failed pass 1 does not silently rewrite intent: it proceeds on the
    # preserved raw text with the failure flagged, so pass 2 still runs.
    NORMALIZING_1: (NORMALIZING_2,) + _ALWAYS,
    NORMALIZING_2: (BUILDING_CONTEXT,) + _ALWAYS,
    BUILDING_CONTEXT: (FUNCTIONALITY_ASSESSMENT,) + _ALWAYS,
    # The gate is first and it is a real fork. A referral goes straight to
    # SUMMARIZING: zero analytical execution, by construction rather than by
    # discipline.
    FUNCTIONALITY_ASSESSMENT: (PLANNING, SUMMARIZING, REDIRECTED,
                               CLARIFICATION_REQUIRED, UNSUPPORTED) + _ALWAYS,
    PLANNING: (VALIDATING, ANSWERING, SUMMARIZING, CLARIFICATION_REQUIRED,
               INSUFFICIENT_DATA) + _ALWAYS,
    # Validation failure does not go to EXECUTING. It goes back to PLANNING,
    # because only Opus may author the next candidate.
    VALIDATING: (EXECUTING, PLANNING, EXECUTION_FAILED,
                 INSUFFICIENT_DATA) + _ALWAYS,
    EXECUTING: (REVIEWING, PLANNING, EXECUTION_FAILED) + _ALWAYS,
    REVIEWING: (PLANNING, ANSWERING, CLARIFICATION_REQUIRED,
                INSUFFICIENT_DATA, PARTIAL) + _ALWAYS,
    ANSWERING: (SUMMARIZING, COMPLETED, PARTIAL) + _ALWAYS,
    # A failed summary never erases a completed answer.
    SUMMARIZING: (COMPLETED, PARTIAL, REDIRECTED, CLARIFICATION_REQUIRED,
                  INSUFFICIENT_DATA, EXECUTION_FAILED, UNSUPPORTED,
                  BUDGET_EXCEEDED, TIMED_OUT, CANCELLED, PROVIDER_ERROR,
                  CONTEXT_TOO_LARGE),
}
for _terminal in TERMINAL:
    TRANSITIONS.setdefault(_terminal, ())


class IllegalTransition(RuntimeError):
    """A transition the server does not permit. Raised, never logged past."""


@dataclass
class Machine:
    """One request's state, and the only thing that may change it."""

    state: str = RECEIVED
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state not in ALL_STATES:
            raise IllegalTransition(f"{self.state!r} is not a state")
        if not self.history:
            self.history.append({"state": self.state, "why": "request received"})

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL

    def may(self, target: str) -> bool:
        return target in TRANSITIONS.get(self.state, ())

    def advance(self, target: str, why: str = "") -> str:
        """Move to `target`, or refuse. The single write path."""
        if target not in ALL_STATES:
            raise IllegalTransition(f"{target!r} is not a state")
        if self.finished:
            raise IllegalTransition(
                f"the request is already {self.state}; a stopped request is "
                f"not reopened by a further transition to {target}")
        if not self.may(target):
            raise IllegalTransition(
                f"{self.state} -> {target} is not a permitted transition")
        self.state = target
        self.history.append({"state": target, "why": why})
        return target

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "finished": self.finished,
                "history": list(self.history)}


#: What the user is told each state is doing. Section 11: progress messages
#: identify actual work, and never claim completion while work is pending.
PROGRESS: dict[str, str] = {
    RECEIVED: "Received your question",
    NORMALIZING_1: "Reading the question",
    NORMALIZING_2: "Understanding what is being asked",
    BUILDING_CONTEXT: "Gathering the Cockpit data catalogue",
    FUNCTIONALITY_ASSESSMENT: "Checking this is a Cockpit question",
    PLANNING: "Planning the analysis",
    VALIDATING: "Checking the analysis against the data",
    EXECUTING: "Executing submission {submission} of {submission_max}",
    REVIEWING: "Reviewing the results, round {round} of {round_max}",
    ANSWERING: "Preparing the answer",
    SUMMARIZING: "Saving the thread summary",
}


def progress(state: str, **counters: Any) -> str:
    template = PROGRESS.get(state, state.replace("_", " ").capitalize())
    try:
        return template.format(**counters)
    except (KeyError, IndexError):
        return template


__all__ = ["ALL_STATES", "ANSWERING", "BUDGET_EXCEEDED", "BUILDING_CONTEXT",
           "CANCELLED", "CLARIFICATION_REQUIRED", "COMPLETED",
           "CONTEXT_TOO_LARGE", "EXECUTING", "EXECUTION_FAILED",
           "FUNCTIONALITY_ASSESSMENT", "INSUFFICIENT_DATA",
           "IllegalTransition", "MODEL_CONFIGURATION_MISSING",
           "MODEL_UNAVAILABLE", "Machine", "NORMALIZING_1", "NORMALIZING_2",
           "PARTIAL", "PLANNING", "PROGRESS", "PROVIDER_ERROR", "RECEIVED",
           "REDIRECTED", "REVIEWING", "STOPPED_WITHOUT_ANSWER", "SUMMARIZING",
           "TERMINAL", "TIMED_OUT", "TRANSITIONS", "UNSUPPORTED", "VALIDATING",
           "WORKING", "progress"]
