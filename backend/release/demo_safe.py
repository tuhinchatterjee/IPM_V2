"""
Client-demo safe mode. §130.

    "no best-effort incomplete answer"

That is the line the whole mode turns on. Everything else in this product
degrades gracefully — a missing dataset produces a stated limitation, an
unavailable model produces a visible downgrade, an incomplete investigation
produces findings. In front of a client, "gracefully" is the wrong instinct:
an answer that is 80% right and looks 100% right is worse than no answer,
because nobody in the room can tell which 20% to disbelieve, and the person
who acts on it is not in the room.

So in Demo Safe Mode the twelve conditions are ALL required, and an answer
that fails any one of them is replaced with a clarification or a controlled
failure. Not a shorter answer, not a caveated one — those still read as
answers.

Why this is per-answer and not per-session
--------------------------------------------
A session-level switch says "we are demonstrating", which is a claim about
intent. These are claims about a specific answer: that its release is
approved, that its blueprint's objectives were covered, that its challenge
pass ran, that its figures are grounded. The same session produces answers
that satisfy them and answers that do not, and the second kind is exactly what
must not appear.

Turning it on is not a promise
-------------------------------
`enabled` is a setting; `check` is the enforcement. A product where switching
the mode on changed a label rather than a behaviour would be worse than not
having the mode, because the label would be believed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEMO_SAFE_VERSION = "1.0.0"

#: The environment switch. Off by default: a mode that refuses answers should
#: be turned on deliberately.
ENV = "AI_DEMO_SAFE_MODE"

# ---------------------------------------------------------- §130's twelve
APPROVED_RELEASE = "approved_current_intelligence_release"
LIVE_VERIFIED = "current_live_provider_verification"
ROUTE_POLICY = "complex_and_high_risk_route_policy"
BLUEPRINT_COVERAGE = "mandatory_blueprint_and_objective_coverage"
CHALLENGE = "mandatory_challenge_pass"
INVARIANTS = "all_invariants"
GROUNDING = "all_grounding"
VISUAL_CRITIC = "visual_critic"
NO_BEST_EFFORT = "no_best_effort_incomplete_answer"
CLARIFY_OR_FAIL = "clarification_or_controlled_failure"
NO_SUBSTITUTION = "no_silent_model_substitution"
NOT_STALE = "no_stale_release"

CONDITIONS: tuple[str, ...] = (
    APPROVED_RELEASE, LIVE_VERIFIED, ROUTE_POLICY, BLUEPRINT_COVERAGE,
    CHALLENGE, INVARIANTS, GROUNDING, VISUAL_CRITIC, NO_BEST_EFFORT,
    CLARIFY_OR_FAIL, NO_SUBSTITUTION, NOT_STALE,
)

ASKS: dict[str, str] = {
    APPROVED_RELEASE: "Is an approved Intelligence Release in force?",
    LIVE_VERIFIED: "Has the provider been verified against it?",
    ROUTE_POLICY: "Did the high-risk route policy apply?",
    BLUEPRINT_COVERAGE: "Were every mandatory objective and the blueprint "
                        "covered?",
    CHALLENGE: "Did the challenge pass run?",
    INVARIANTS: "Did every invariant hold?",
    GROUNDING: "Does every figure trace to a validated fact?",
    VISUAL_CRITIC: "Did the chart pass the critic?",
    NO_BEST_EFFORT: "Is this a complete answer rather than the part that "
                    "worked?",
    CLARIFY_OR_FAIL: "If it could not be answered, was that said plainly?",
    NO_SUBSTITUTION: "Did every model role serve from its configured model?",
    NOT_STALE: "Is the release current against what is running?",
}

# ----------------------------------------------------------- what happens
SHOW = "SHOW"
#: Ask one question that would let the answer be given. Better than a caveated
#: answer, because a question is obviously a question.
CLARIFY = "CLARIFY"
#: Say what could not be established and why. A controlled failure is an
#: answer to a different question — "can you tell me this?" — answered
#: honestly.
CONTROLLED_FAILURE = "CONTROLLED_FAILURE"

OUTCOMES: tuple[str, ...] = (SHOW, CLARIFY, CONTROLLED_FAILURE)

#: Conditions where a clarification would help — the answer could be given if
#: the reader narrowed the question. Everything else is a controlled failure,
#: because no rephrasing fixes a stale release.
CLARIFIABLE: frozenset[str] = frozenset({BLUEPRINT_COVERAGE, NO_BEST_EFFORT})


def enabled() -> bool:
    """Whether Demo Safe Mode is on.

    Off by default. A mode that refuses answers should be turned on
    deliberately, and one that defaults on would be turned off by the first
    person it inconvenienced.
    """
    return os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes",
                                                       "on")


@dataclass
class Verdict:
    """Whether this answer may be shown in a demo, and what to do instead."""

    outcome: str = CONTROLLED_FAILURE
    unmet: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    active: bool = True

    @property
    def may_show(self) -> bool:
        return self.outcome == SHOW

    def sentence(self) -> str:
        if not self.active:
            return ("Demo Safe Mode is off. Answers are shown under the "
                    "ordinary rules, which permit a stated limitation.")
        if self.may_show:
            return ("Every Demo Safe Mode condition is met. This answer may "
                    "be shown to a client.")
        detail = "; ".join(self.reasons.get(c) or ASKS[c] for c in self.unmet)
        if self.outcome == CLARIFY:
            return ("This cannot be answered completely as asked, so "
                    f"CreditProbe asks rather than answering partly: {detail}")
        return ("CreditProbe cannot answer this to the standard a client "
                f"demonstration requires, and says so rather than showing the "
                f"part that worked: {detail}")

    def to_dict(self) -> dict[str, Any]:
        return {"version": DEMO_SAFE_VERSION, "active": self.active,
                "outcome": self.outcome, "may_show": self.may_show,
                "unmet": list(self.unmet),
                "reasons": dict(self.reasons),
                "conditions": [{"id": c, "asks": ASKS[c],
                                "met": c not in self.unmet}
                               for c in CONDITIONS],
                "sentence": self.sentence()}


def check(met: dict[str, bool], *, reasons: dict[str, str] | None = None,
          active: bool | None = None) -> Verdict:
    """§130's twelve, all required.

    A condition not supplied is UNMET, not met. The permissive default would
    make an answer safe for a client demonstration by virtue of nobody having
    checked it.
    """
    running = enabled() if active is None else bool(active)
    result = Verdict(active=running, reasons=dict(reasons or {}))

    if not running:
        # Off: the ordinary rules apply and this does not gate anything. Still
        # reports which conditions would have been unmet, so somebody can see
        # what turning it on would change.
        result.outcome = SHOW
        result.unmet = [c for c in CONDITIONS if not met.get(c)]
        return result

    result.unmet = [c for c in CONDITIONS if not met.get(c)]
    if not result.unmet:
        result.outcome = SHOW
    elif all(c in CLARIFIABLE for c in result.unmet):
        result.outcome = CLARIFY
    else:
        result.outcome = CONTROLLED_FAILURE
    return result


__all__ = ["APPROVED_RELEASE", "ASKS", "BLUEPRINT_COVERAGE", "CHALLENGE",
           "CLARIFIABLE", "CLARIFY", "CLARIFY_OR_FAIL", "CONDITIONS",
           "CONTROLLED_FAILURE", "DEMO_SAFE_VERSION", "ENV", "GROUNDING",
           "INVARIANTS", "LIVE_VERIFIED", "NOT_STALE", "NO_BEST_EFFORT",
           "NO_SUBSTITUTION", "OUTCOMES", "ROUTE_POLICY", "SHOW",
           "VISUAL_CRITIC", "Verdict", "check", "enabled"]
