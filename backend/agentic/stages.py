"""
The structured stages a run passes through. §7.

Eleven states, each with the sentence the user sees beside the pulse. They are
here rather than in the frontend because they are an **audit record** as well as
a caption: `agent_runs.stage_history` records when each one began, and a run
that spent four minutes in CALCULATING and one second in VALIDATING is a run
somebody should look at.

Why these and not chain-of-thought
----------------------------------
§7 ends with "Do not show hidden chain-of-thought. Show only structured
auditable stages." The distinction matters and is easy to blur. A stage is a
*phase of governed work* — the population is being defined, the runtime is
executing, the invariants are being checked — and every one of them corresponds
to something the Trace can show afterwards. A model's intermediate reasoning is
none of those things: it cannot be reproduced, cannot be audited, and reveals
prompt content that is not the user's to see.

So the stage vocabulary is closed. There is no `stage("thinking about...")`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

QUEUED = "QUEUED"
UNDERSTANDING = "UNDERSTANDING"
SCOPING = "SCOPING"
SELECTING_DATA = "SELECTING_DATA"
COORDINATING = "COORDINATING"
CALCULATING = "CALCULATING"
VALIDATING = "VALIDATING"
INTERPRETING = "INTERPRETING"
COMPLETE = "COMPLETE"
NEEDS_INPUT = "NEEDS_INPUT"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

#: The order work normally moves through. Used to render completed stages and
#: to refuse a backwards transition — a run that shows VALIDATING and then
#: SCOPING again is telling the user something untrue about what it is doing.
SEQUENCE: tuple[str, ...] = (
    QUEUED, UNDERSTANDING, SCOPING, SELECTING_DATA, COORDINATING,
    CALCULATING, VALIDATING, INTERPRETING, COMPLETE,
)

TERMINAL: frozenset[str] = frozenset({COMPLETE, NEEDS_INPUT, FAILED, CANCELLED})

#: §7's own wording, verbatim.
CAPTIONS: dict[str, str] = {
    QUEUED: "CreditProbe is preparing the request.",
    UNDERSTANDING: "Understanding your question.",
    SCOPING: "Defining the population and period.",
    SELECTING_DATA: "Selecting governed data.",
    COORDINATING: "Coordinating specialist agents.",
    CALCULATING: "Running governed calculations.",
    VALIDATING: "Validating results and reconciliation.",
    INTERPRETING: "Preparing the CreditProbe reading.",
    COMPLETE: "Completed — validated.",
    NEEDS_INPUT: "CreditProbe needs your input.",
    FAILED: "CreditProbe could not complete the request.",
    CANCELLED: "Stopped at your request.",
}

#: The short label under the officer title, where the caption is too long.
SHORT: dict[str, str] = {
    QUEUED: "Preparing",
    UNDERSTANDING: "Understanding",
    SCOPING: "Scoping",
    SELECTING_DATA: "Selecting data",
    COORDINATING: "Coordinating",
    CALCULATING: "Calculating",
    VALIDATING: "Validating",
    INTERPRETING: "Interpreting",
    COMPLETE: "Complete",
    NEEDS_INPUT: "Needs input",
    FAILED: "Failed",
    CANCELLED: "Cancelled",
}


def caption(stage: str, *, detail: str = "") -> str:
    """The sentence beside the pulse, with a scope note where there is one.

    "Validating 6 calculations" rather than "Validating results and
    reconciliation" when the run knows the number — §8's example. The detail
    replaces the generic caption rather than being appended to it, because two
    sentences under a spinner is a paragraph.
    """
    return detail.strip() or CAPTIONS.get(stage, stage)


def index(stage: str) -> int:
    """Where a stage sits in the sequence, or -1 for a terminal one."""
    try:
        return SEQUENCE.index(stage)
    except ValueError:
        return -1


def can_move(current: str, target: str) -> bool:
    """Whether a transition is allowed.

    Forward through the sequence, or to any terminal state at any time. A run
    can always fail, always need input, and always be cancelled; it cannot go
    back to scoping once it is validating.
    """
    if target in TERMINAL:
        return current not in TERMINAL
    if current in TERMINAL:
        return False
    return index(target) >= index(current)


def completed(current: str) -> list[str]:
    """Every stage this run has passed, for §8's compact completed list."""
    here = index(current)
    if here < 0:
        return list(SEQUENCE[:-1])
    return list(SEQUENCE[:here])


@dataclass
class Step:
    """One stage, and when it began."""

    stage: str
    at: str
    detail: str = ""
    #: How many specialists were active when it began, where relevant.
    agents: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "at": self.at, "detail": self.detail,
                "agents": self.agents,
                "caption": caption(self.stage, detail=self.detail),
                "label": SHORT.get(self.stage, self.stage)}


def step(stage: str, *, detail: str = "", agents: int = 0) -> Step:
    return Step(stage=stage,
                at=datetime.now(UTC).isoformat(timespec="seconds"),
                detail=detail, agents=agents)


def view(stage: str, *, history: list[dict[str, Any]] | None = None,
         detail: str = "", agents: int = 0,
         officer: str = "", specialists: list[str] | None = None,
         elapsed_ms: int = 0) -> dict[str, Any]:
    """Everything the working indicator needs, in one document. §8.

    Assembled here rather than in the frontend so the API, the Trace and the
    Agent Operations screen all show the same thing, and so the caption a user
    saw is the caption recorded in the run.
    """
    return {
        "stage": stage,
        "label": SHORT.get(stage, stage),
        "caption": caption(stage, detail=detail),
        "detail": detail,
        "officer_title": officer,
        "status_line": f"{officer} is working" if officer and
                       stage not in TERMINAL else "",
        "specialists": list(specialists or []),
        "agent_count": agents or len(specialists or []),
        "elapsed_ms": elapsed_ms,
        "active": stage not in TERMINAL,
        "terminal": stage in TERMINAL,
        "completed": completed(stage),
        "history": list(history or []),
        "sequence": list(SEQUENCE),
    }


__all__ = [
    "CALCULATING",
    "CANCELLED",
    "CAPTIONS",
    "COMPLETE",
    "COORDINATING",
    "FAILED",
    "INTERPRETING",
    "NEEDS_INPUT",
    "QUEUED",
    "SCOPING",
    "SELECTING_DATA",
    "SEQUENCE",
    "SHORT",
    "TERMINAL",
    "UNDERSTANDING",
    "VALIDATING",
    "Step",
    "can_move",
    "caption",
    "completed",
    "index",
    "step",
    "view",
]
