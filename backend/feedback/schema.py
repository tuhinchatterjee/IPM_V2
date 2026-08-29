"""
The Feedback object, its reasons and its privacy rules. §148, §149, §150,
§151, §152.

    §149: "Do not claim immediate learning."
    §152: "Do not store: API keys; authorization headers; hidden
           chain-of-thought; sealed-holdout answers; unrestricted raw client
           rows; cross-tenant data."

Why the "thank you" wording is in the code
--------------------------------------------
Because "thanks, I'll learn from that" is what every product says and it is
almost always false. Nothing here changes production until a person has
reviewed it, and telling a user otherwise buys a moment of goodwill with a
claim that will be contradicted the next time they ask the same question and
get the same wrong answer. `THANKS` is a constant, and a test asserts it does
not promise learning.

Why a BAD rating without a reason is discouraged rather than refused
----------------------------------------------------------------------
§150 says "require or strongly encourage". Refusing outright loses the signal
from the user who is annoyed and about to close the tab — and that user's
annoyance is data. So the reason is strongly encouraged, its absence is
recorded as `reason_missing`, and triage treats a reasonless BAD as lower
confidence rather than as nothing.

The forty-two fields
--------------------
§151 lists them and every one is here, because the point of most of them is
reproduction: a feedback item that records the rating and not the build, the
release, the retrieved cases and the served model is an opinion. With them it
is a bug report somebody can reproduce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

FEEDBACK_VERSION = "1.0.0"

GOOD = "GOOD"
BAD = "BAD"
RATINGS: tuple[str, ...] = (GOOD, BAD)

# ------------------------------------------------------- §149's good reasons
GOOD_REASONS: tuple[str, ...] = (
    "correct", "clear", "useful_interpretation", "good_analysis",
    "good_visualization", "good_trace", "good_follow_ups", "other",
)

# --------------------------------------------------------- §150's bad reasons
BAD_REASONS: tuple[str, ...] = (
    "misunderstood_my_question", "missed_part_of_the_question",
    "wrong_population", "wrong_period", "wrong_data",
    "wrong_relationship_or_join", "wrong_calculation", "wrong_numbers",
    "incomplete_answer", "weak_interpretation", "unsupported_claim",
    "wrong_chart", "trace_unclear_or_inconsistent", "too_much_information",
    "not_enough_detail", "slow", "error_or_failed_request", "other",
)

REASONS: dict[str, tuple[str, ...]] = {GOOD: GOOD_REASONS, BAD: BAD_REASONS}

#: On screen. Underscores are a storage format, not a sentence.
LABELS: dict[str, str] = {
    "correct": "Correct", "clear": "Clear",
    "useful_interpretation": "Useful interpretation",
    "good_analysis": "Good analysis",
    "good_visualization": "Good visualization", "good_trace": "Good Trace",
    "good_follow_ups": "Good follow-up suggestions", "other": "Other",
    "misunderstood_my_question": "Misunderstood my question",
    "missed_part_of_the_question": "Missed part of the question",
    "wrong_population": "Wrong population", "wrong_period": "Wrong period",
    "wrong_data": "Wrong data",
    "wrong_relationship_or_join": "Wrong relationship or join",
    "wrong_calculation": "Wrong calculation",
    "wrong_numbers": "Wrong numbers",
    "incomplete_answer": "Incomplete answer",
    "weak_interpretation": "Weak interpretation",
    "unsupported_claim": "Unsupported claim", "wrong_chart": "Wrong chart",
    "trace_unclear_or_inconsistent": "Trace unclear or inconsistent",
    "too_much_information": "Too much information",
    "not_enough_detail": "Not enough detail", "slow": "Slow",
    "error_or_failed_request": "Error or failed request",
}

#: §149's wording. A constant because it is a promise, and a promise typed
#: freshly in three places becomes three different promises.
THANKS = ("Thank you. This feedback will be reviewed to improve CreditProbe.")

# --------------------------------------------------------------- §151 status
NEW = "NEW"
TRIAGED = "TRIAGED"
UNDER_REVIEW = "UNDER_REVIEW"
ADJUDICATED = "ADJUDICATED"
DISMISSED = "DISMISSED"
REGRESSION_CREATED = "REGRESSION_CREATED"
FIXED = "FIXED"
RELEASED = "RELEASED"

STATUSES: tuple[str, ...] = (NEW, TRIAGED, UNDER_REVIEW, ADJUDICATED,
                             DISMISSED, REGRESSION_CREATED, FIXED, RELEASED)

#: §155's loop, as the only permitted transitions. A feedback item that could
#: jump from NEW to RELEASED is a feedback item that changed production
#: without being reviewed.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    NEW: (TRIAGED, DISMISSED),
    TRIAGED: (UNDER_REVIEW, DISMISSED),
    UNDER_REVIEW: (ADJUDICATED, DISMISSED),
    ADJUDICATED: (REGRESSION_CREATED, DISMISSED),
    REGRESSION_CREATED: (FIXED, DISMISSED),
    FIXED: (RELEASED,),
    RELEASED: (),
    DISMISSED: (),
}

#: Statuses where a reviewer has actually adjudicated. Only from here may
#: anything change what CreditProbe believes.
ADJUDICATED_STATES: frozenset[str] = frozenset({
    ADJUDICATED, REGRESSION_CREATED, FIXED, RELEASED})


# ---------------------------------------------------------------- §152 privacy
#: Patterns that must never be stored. Checked on the way IN rather than on
#: the way out: a secret in the database is a secret in the backups, and no
#: amount of careful rendering undoes that.
FORBIDDEN = re.compile(
    r"sk-ant-[\w-]+"
    r"|\bauthorization\s*:\s*\S+"
    r"|\bbearer\s+[\w.\-]{10,}"
    r"|\b(?:api[_-]?key|secret[_-]?key|access[_-]?token)\b\s*[:=]\s*\S+",
    re.IGNORECASE)

#: Field names a feedback payload may never carry, whatever their content.
FORBIDDEN_FIELDS: tuple[str, ...] = (
    "api_key", "authorization", "chain_of_thought", "reasoning_trace",
    "gold_answer", "holdout_answer", "raw_rows", "client_rows",
)


class WouldStoreSecret(Exception):
    """A feedback payload carrying something §152 forbids.

    Raised rather than redacted. A redaction leaves the caller believing the
    field was accepted, and the next payload assembled the same way reaches a
    surface where this check does not run.
    """


def scrub(text: str) -> str:
    """Refuse a comment carrying a credential.

    Users paste. The most common way a key reaches a database is somebody
    pasting a failing curl command into a free-text box to explain what went
    wrong, and the box accepting it.
    """
    if FORBIDDEN.search(text or ""):
        raise WouldStoreSecret(
            "the comment appears to contain a credential, which §152 forbids "
            "storing. Remove it and describe what went wrong instead.")
    return text


@dataclass
class Feedback:
    """§151's versioned Feedback object. Every field it names."""

    feedback_id: str = ""
    user_id: int | None = None
    tenant_id: str = ""
    #: What was rated. All four together, because an answer id alone does not
    #: locate the run, and the run is what gets reproduced.
    answer_id: str = ""
    message_id: str = ""
    investigation_id: str = ""
    analysis_run_id: str = ""
    trace_id: str = ""
    agentic_run_id: str = ""
    project_id: str = ""
    scope: str = ""
    language: str = "en"

    rating: str = GOOD
    reason_codes: list[str] = field(default_factory=list)
    comment: str = ""
    expected_behavior: str = ""
    selected_fact_ids: list[str] = field(default_factory=list)
    selected_chart_element: str = ""
    selected_trace_node: str = ""

    created_at: str = ""
    updated_at: str = ""
    status: str = NEW

    # ---- what was running when it happened. The half that makes this a bug
    # report rather than an opinion.
    build_sha: str = ""
    app_version: str = ""
    intelligence_release_id: str = ""
    teaching_release_id: str = ""
    ontology_version: str = ""
    prompt_versions: dict[str, str] = field(default_factory=dict)
    routing_policy_version: str = ""
    model_roles: dict[str, str] = field(default_factory=dict)
    served_models: dict[str, str] = field(default_factory=dict)
    retrieved_case_ids: list[str] = field(default_factory=list)
    blueprint_id: str = ""
    officer_level: int = 0
    agent_roles: list[str] = field(default_factory=list)
    objective_coverage: dict[str, Any] = field(default_factory=dict)
    failure_category: str = ""

    # ---- what was done about it
    reviewer: str = ""
    adjudication: str = ""
    component_attribution: list[str] = field(default_factory=list)
    regression_ids: list[str] = field(default_factory=list)
    target_release: str = ""
    released_at: str = ""

    @property
    def reason_missing(self) -> bool:
        """A BAD rating with no reason.

        Recorded rather than refused. §150 says require or strongly
        encourage, and refusing loses the signal from the user who is annoyed
        and about to close the tab — whose annoyance is itself data.
        """
        return self.rating == BAD and not self.reason_codes

    @property
    def reproducible(self) -> bool:
        """Whether somebody could reproduce this.

        A feedback item with a rating and no build, release or run is an
        opinion. With them it is a bug report.
        """
        return bool(self.analysis_run_id or self.agentic_run_id) and bool(
            self.build_sha)

    @property
    def adjudicated(self) -> bool:
        return self.status in ADJUDICATED_STATES and bool(self.reviewer)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return {**asdict(self), "version": FEEDBACK_VERSION,
                "reason_missing": self.reason_missing,
                "reproducible": self.reproducible,
                "adjudicated": self.adjudicated,
                "reason_labels": [LABELS.get(r, r)
                                  for r in self.reason_codes]}


def create(*, rating: str, answer_id: str, reasons: list[str] | None = None,
           comment: str = "", expected: str = "",
           **context: Any) -> Feedback:
    """One piece of feedback, validated on the way in.

    Unknown reason codes are refused rather than stored: a reason nobody
    defined cannot be aggregated, and a distribution with an unbounded tail of
    one-off strings is not a distribution.
    """
    if rating not in RATINGS:
        raise ValueError(f"{rating!r} is not GOOD or BAD")
    codes = list(reasons or [])
    unknown = [c for c in codes if c not in REASONS[rating]]
    if unknown:
        raise ValueError(
            f"{unknown[0]!r} is not a {rating} reason. A reason nobody "
            "defined cannot be aggregated.")
    present = [f for f in FORBIDDEN_FIELDS if f in context]
    if present:
        raise WouldStoreSecret(
            f"a feedback payload may not carry {', '.join(present)} (§152)")

    now = datetime.now(UTC).isoformat(timespec="seconds")
    allowed = {f for f in Feedback.__dataclass_fields__}
    return Feedback(
        rating=rating, answer_id=answer_id, reason_codes=codes,
        comment=scrub(comment), expected_behavior=scrub(expected),
        created_at=now, updated_at=now, status=NEW,
        **{k: v for k, v in context.items() if k in allowed})


def may_move(current: str, to: str) -> bool:
    """§155's loop as the only permitted path.

    An item that could jump from NEW to RELEASED is an item that changed
    production without being reviewed, which is the one thing this whole
    mechanism exists to prevent.
    """
    return to in TRANSITIONS.get(current, ())


def acknowledgement(rating: str) -> str:
    """What the user is told. §149.

    The same sentence for GOOD and BAD, because the promise is the same and
    the promise is deliberately modest: reviewed, not learned from.
    """
    _ = rating
    return THANKS


__all__ = ["ADJUDICATED", "ADJUDICATED_STATES", "BAD", "BAD_REASONS",
           "DISMISSED", "FEEDBACK_VERSION", "FIXED", "FORBIDDEN",
           "FORBIDDEN_FIELDS", "Feedback", "GOOD", "GOOD_REASONS", "LABELS",
           "NEW", "RATINGS", "REASONS", "REGRESSION_CREATED", "RELEASED",
           "STATUSES", "THANKS", "TRANSITIONS", "TRIAGED", "UNDER_REVIEW",
           "WouldStoreSecret", "acknowledgement", "create", "may_move",
           "scrub"]
