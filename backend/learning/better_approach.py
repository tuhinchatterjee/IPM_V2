"""Thumbs, and what a thumbs-down is allowed to become. §39-§45.

The sentence that shapes this module
-------------------------------------
§40's own explanation to the user: **"You do not need to provide the
numerical answer."**

That is not politeness. A user who is asked for the right number will supply
one, it will be wrong about as often as the system was, and it will arrive
carrying the authority of having been typed by a person. What a user actually
knows — and what nobody else does — is what they MEANT: which population,
which period, which concept, what the answer should have been shaped like.
So every field here is about the approach, and none of them is a figure.

Immediate versus governed
--------------------------
§42 draws a line and this module enforces it. A preference about how an
answer LOOKS takes effect at once, because getting it wrong costs a user one
badly-shaped table. A correction about what an answer MEANS goes through
observation, triage, reproduction, review, regression, evaluation and
release, because getting that wrong costs a bank a wrong number in a credit
paper with an audit trail saying a user asked for it.

`immediate()` returns only the presentation half, and there is no argument
that widens it.

Good feedback is not gold
--------------------------
§41 says so directly, and `Thumbs.gold` does not exist. A thumbs-up records
that one person liked one answer. It becomes a positive teaching case only
after the same validation any other candidate goes through — otherwise the
library fills with answers that were popular.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

BETTER_APPROACH_VERSION = "1.0.0"

# ----------------------------------------------------- §39 every answer kind
#
# §39 lists them, and the list is here rather than in the front end because
# "does this answer type carry a feedback control?" must be answerable
# server-side. A control that exists on eight surfaces and is forgotten on
# the ninth produces a corpus that is silent about the ninth, and nobody
# notices, because absence of complaint reads as absence of problem.

METADATA = "metadata"
ANALYSIS = "analysis"
CLARIFICATION = "clarification"
UNSUPPORTED = "unsupported"
CONTROLLED_FAILURE = "controlled_failure"
AGENTIC = "agentic"
REGULATORY = "regulatory"
PROJECT_PLANNER = "project_planner"

ANSWER_KINDS: tuple[str, ...] = (
    METADATA, ANALYSIS, CLARIFICATION, UNSUPPORTED, CONTROLLED_FAILURE,
    AGENTIC, REGULATORY, PROJECT_PLANNER,
)

#: What each kind is, so a report can group by it and mean something.
KIND_MEANS: dict[str, str] = {
    METADATA: "An answer about the product itself — which datasets exist, "
              "what a method does. No portfolio figure was computed.",
    ANALYSIS: "A computed answer over governed data.",
    CLARIFICATION: "CreditProbe asked rather than guessed. Feedback here is "
                   "often 'you should have known' — which is the most "
                   "useful correction in the system and the easiest to lose.",
    UNSUPPORTED: "CreditProbe said it could not do this. A thumbs-down here "
                 "is a capability request, and it is worth separating from "
                 "a wrong answer.",
    CONTROLLED_FAILURE: "Something went wrong and was reported honestly "
                        "rather than hidden.",
    AGENTIC: "Produced by the governed agentic layer rather than a single "
             "analysis.",
    REGULATORY: "An answer grounded in a regulatory source.",
    PROJECT_PLANNER: "A planned sequence of work rather than one answer.",
}

#: §39 also names Arabic. Not a kind — the same eight kinds in another
#: language — so it travels as a field. A thumbs-down that is really "this
#: sentence is wrong in Arabic" is a different finding from "the analysis is
#: wrong", and folding them together loses both.
LANGUAGES: tuple[str, ...] = ("en", "ar")


UP = "UP"
DOWN = "DOWN"
DIRECTIONS: tuple[str, ...] = (UP, DOWN)


class FeedbackError(Exception):
    """Something feedback may not be, or may not do."""


# -------------------------------------------------------- §41 thumbs-up


#: §41's nine. Reasons rather than a score: "4 out of 5" tells nobody which
#: part was good, and the whole point of asking is to learn which part.
UP_REASONS: tuple[tuple[str, str], ...] = (
    ("correct", "The figures were right."),
    ("clear", "I could follow it."),
    ("complete", "It answered everything I asked."),
    ("good_analysis", "The approach was the one I would have taken."),
    ("good_interpretation", "What it said about the numbers was right."),
    ("good_visualization", "The picture suited the shape of the answer."),
    ("good_trace", "I could see how it got there."),
    ("good_followups", "The suggested next questions were the right ones."),
    ("other", "Something else."),
)

UP_REASON_IDS: tuple[str, ...] = tuple(r for r, _ in UP_REASONS)

EXPECTED_UP_REASONS = 9
if len(UP_REASONS) != EXPECTED_UP_REASONS:
    raise AssertionError(
        f"§41 names {EXPECTED_UP_REASONS} thumbs-up reasons; this module "
        f"has {len(UP_REASONS)}.")


# ------------------------------------------------------ §40 thumbs-down


#: §40's eleven fields. Every one asks what the user MEANT; none asks for a
#: number. A user who supplies the right figure supplies it with the
#: authority of having been typed by a person, and it is wrong about as
#: often as the system was.
FIELDS: tuple[tuple[str, str, str], ...] = (
    ("reason_category", "What went wrong",
     "The earliest thing that went wrong, not the most visible one."),
    ("better_interpretation", "How it should have been understood",
     "What you were actually asking for."),
    ("missing_objectives", "What it did not answer",
     "Parts of your question the answer skipped."),
    ("correct_population", "Which population",
     "Which facilities, borrowers or accounts should have been in scope."),
    ("correct_period", "Which period",
     "The reporting period or window that was meant."),
    ("correct_concept", "Which concept",
     "The measure that was meant — exposure, EAD, ECL, coverage."),
    ("correct_data", "Which data or relationship",
     "The governed dataset or join that should have been used."),
    ("preferred_method", "Which method or formula",
     "How the figure should have been computed."),
    ("preferred_visualization", "How it should have been drawn",
     "The chart or table that would have suited the answer."),
    ("better_structure", "How it should have been organised",
     "The order the answer should have been in."),
    ("additional_comment", "Anything else", "In your own words."),
)

FIELD_IDS: tuple[str, ...] = tuple(f for f, _, _ in FIELDS)

EXPECTED_FIELDS = 11
if len(FIELDS) != EXPECTED_FIELDS:
    raise AssertionError(
        f"§40 names {EXPECTED_FIELDS} correction fields; this module has "
        f"{len(FIELDS)}.")

#: §40's six selectable anchors. What part of the answer the user is
#: pointing at, so a correction attaches to something rather than floating
#: beside the whole response.
ANCHORS: tuple[tuple[str, str], ...] = (
    ("sentence", "A sentence in the written answer."),
    ("figure", "One number."),
    ("row", "One row of the result."),
    ("chart_element", "A bar, a point or a slice."),
    ("trace_node", "A step in how the answer was produced."),
    ("objective", "One of the things you asked for."),
)

ANCHOR_IDS: tuple[str, ...] = tuple(a for a, _ in ANCHORS)

EXPECTED_ANCHORS = 6
if len(ANCHORS) != EXPECTED_ANCHORS:
    raise AssertionError(
        f"§40 names {EXPECTED_ANCHORS} selectable anchors; this module has "
        f"{len(ANCHORS)}.")


# ------------------------------------------- §42 immediate vs governed


#: The only settings a thumbs-down may change at once. §42's six, mapped
#: onto the preference names that already exist. Getting one of these wrong
#: costs a user a badly-shaped table; getting an analytical correction wrong
#: costs a bank a wrong number in a credit paper.
IMMEDIATE_FIELDS: dict[str, str] = {
    "preferred_visualization": "result_form",
    "better_structure": "answer_length",
}

#: §42's pipeline, as data. Shown to the user who left the correction, so
#: "what happened to my feedback?" has an answer that is not "it went
#: somewhere".
GOVERNED_PATH: tuple[str, ...] = (
    "FEEDBACK", "LEARNING OBSERVATION", "TRIAGE", "REPRODUCE",
    "SME / GOVERNANCE REVIEW", "CANDIDATE TEACHING CASE / POLICY / METHOD",
    "REGRESSION", "EVALUATION", "APPROVED RELEASE", "ACTIVATION",
)


def immediate(correction: dict[str, Any]) -> dict[str, str]:
    """The presentation preferences this correction may change right now.

    Returns at most two things, and never anything analytical. There is no
    argument that widens this: §42's line between "how an answer looks" and
    "what an answer means" is the one place in the learning system where a
    user's word takes effect without review, and a function that could be
    persuaded to cross it would be the whole safeguard.
    """
    changes: dict[str, str] = {}
    drawn = str(correction.get("preferred_visualization", "")).strip().lower()
    if drawn in ("table", "chart"):
        changes["result_form"] = drawn
    structure = str(correction.get("better_structure", "")).strip().lower()
    if structure in ("brief", "standard", "full"):
        changes["answer_length"] = structure
    return changes


def governed(correction: dict[str, Any]) -> list[str]:
    """The fields in this correction that may NOT take effect immediately.

    Named individually rather than counted, because the user is told what
    happens next to each one and "eight things are under review" is not that.
    """
    analytical = [f for f in FIELD_IDS if f not in IMMEDIATE_FIELDS]
    return [f for f in analytical if str(correction.get(f, "")).strip()]


# --------------------------------------------------------------- the record


@dataclass
class Thumbs:
    """One thumbs-up or thumbs-down on one answer.

    There is deliberately no `gold` field and no `weight`. §41: good feedback
    is not automatically gold. A thumbs-up records that one person liked one
    answer, and it becomes a teaching case only through the same validation
    every other candidate goes through.
    """

    feedback_id: str = ""
    answer_id: str = ""
    direction: str = UP
    answer_kind: str = ANALYSIS
    language: str = "en"

    #: Thumbs-up only: which of §41's nine.
    reasons: tuple[str, ...] = ()
    #: Thumbs-down only: §40's eleven fields, whichever were filled.
    correction: dict[str, Any] = field(default_factory=dict)
    #: What part of the answer the user pointed at.
    anchor_kind: str = ""
    anchor_ref: str = ""

    user_id: str = ""
    tenant: str = ""
    #: What the answer was produced under, so it can be reproduced.
    build_sha: str = ""
    plan_fingerprint: str = ""
    teaching_release_id: str = ""

    status: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        self.feedback_id = self.feedback_id or f"fb_{uuid.uuid4().hex[:16]}"
        self.created_at = self.created_at or datetime.now(UTC).isoformat()
        self.status = self.status or RECEIVED

    @property
    def immediate_changes(self) -> dict[str, str]:
        return immediate(self.correction) if self.direction == DOWN else {}

    @property
    def governed_fields(self) -> list[str]:
        return governed(self.correction) if self.direction == DOWN else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "answer_id": self.answer_id,
            "direction": self.direction,
            "answer_kind": self.answer_kind,
            "kind_means": KIND_MEANS.get(self.answer_kind, ""),
            "language": self.language,
            "reasons": list(self.reasons),
            "correction": dict(self.correction),
            "anchor": {"kind": self.anchor_kind, "ref": self.anchor_ref},
            "status": self.status,
            "status_means": STATUS_MEANS.get(self.status, ""),
            "immediate_changes": self.immediate_changes,
            "under_review": self.governed_fields,
            "created_at": self.created_at,
            "changes_no_score": True,
            "governed_path": list(GOVERNED_PATH),
        }


def record(*, answer_id: str, direction: str, answer_kind: str = ANALYSIS,
           reasons: tuple[str, ...] = (),
           correction: dict[str, Any] | None = None, anchor_kind: str = "",
           anchor_ref: str = "", user_id: str = "", language: str = "en",
           **provenance: Any) -> Thumbs:
    """Validate and build one piece of feedback. Changes no score.

    §44: raw thumbs do not change validation scores. Nothing in this
    function touches one, and `to_dict` says so out loud on every record so
    a screen rendering it cannot imply otherwise.
    """
    if direction not in DIRECTIONS:
        raise FeedbackError(f"{direction!r} is not UP or DOWN")
    if answer_kind not in ANSWER_KINDS:
        raise FeedbackError(
            f"{answer_kind!r} is not one of §39's answer kinds; expected one "
            f"of {', '.join(ANSWER_KINDS)}")
    if language not in LANGUAGES:
        raise FeedbackError(f"{language!r} is not a supported language")
    if not answer_id.strip():
        raise FeedbackError(
            "feedback with no answer cannot be reproduced, and a correction "
            "nobody can reproduce cannot be acted on")

    unknown = [r for r in reasons if r not in UP_REASON_IDS]
    if unknown:
        raise FeedbackError(
            f"{', '.join(unknown)} — not among §41's nine reasons")
    if direction == UP and correction:
        raise FeedbackError(
            "a thumbs-up carries reasons, not a correction. If the answer "
            "needed correcting it was not a thumbs-up")
    if direction == DOWN and reasons:
        raise FeedbackError(
            "a thumbs-down carries a correction, not approval reasons")
    if anchor_kind and anchor_kind not in ANCHOR_IDS:
        raise FeedbackError(
            f"{anchor_kind!r} is not one of §40's six anchors")

    body = correction or {}
    stray = [k for k in body if k not in FIELD_IDS]
    if stray:
        raise FeedbackError(
            f"{', '.join(stray)} — not among §40's eleven fields. A field "
            "nobody named is a field nobody reviews")

    return Thumbs(
        answer_id=answer_id.strip(), direction=direction,
        answer_kind=answer_kind, language=language,
        reasons=tuple(reasons), correction=dict(body),
        anchor_kind=anchor_kind, anchor_ref=anchor_ref, user_id=user_id,
        build_sha=str(provenance.get("build_sha", "")),
        plan_fingerprint=str(provenance.get("plan_fingerprint", "")),
        teaching_release_id=str(provenance.get("teaching_release_id", "")),
        tenant=str(provenance.get("tenant", "")),
    )


# ---------------------------------------------------------- §45 the status


RECEIVED = "RECEIVED"
UNDER_REVIEW = "UNDER_REVIEW"
FIXED = "FIXED"
RELEASED = "RELEASED"
#: Not one of §45's four, and necessary. A correction somebody looked at and
#: disagreed with has an outcome, and leaving it at UNDER_REVIEW forever is
#: how a user learns that giving feedback achieves nothing.
NOT_CHANGING = "REVIEWED_NOT_CHANGING"

STATUSES: tuple[str, ...] = (RECEIVED, UNDER_REVIEW, FIXED, RELEASED,
                             NOT_CHANGING)

STATUS_MEANS: dict[str, str] = {
    RECEIVED: "Recorded. Nobody has looked at it yet.",
    UNDER_REVIEW: "Somebody is working out whether this is a defect and "
                  "what it would take to fix.",
    FIXED: "The change has been made and has passed regression. It is not "
           "in production yet — approval is permission to release, not a "
           "release.",
    RELEASED: "Live. Answers produced from now on reflect it.",
    NOT_CHANGING: "Reviewed, and we are not making the change. The reason "
                  "is recorded, because a correction that vanishes teaches "
                  "the user that feedback achieves nothing.",
}

#: The permitted moves. A correction cannot jump from RECEIVED to RELEASED:
#: §42's path exists precisely so nothing skips review and regression.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    RECEIVED: (UNDER_REVIEW, NOT_CHANGING),
    UNDER_REVIEW: (FIXED, NOT_CHANGING),
    FIXED: (RELEASED,),
    RELEASED: (),
    NOT_CHANGING: (UNDER_REVIEW,),   # reopened when somebody disagrees
}


def advance_status(current: str, to: str, *, reason: str = "") -> str:
    """Move one piece of feedback along §45's states, or refuse."""
    if current not in STATUSES:
        raise FeedbackError(f"{current!r} is not a feedback status")
    if to not in STATUSES:
        raise FeedbackError(f"{to!r} is not a feedback status")
    if to not in TRANSITIONS[current]:
        allowed = TRANSITIONS[current] or ("nothing",)
        raise FeedbackError(
            f"{current} does not move to {to}; the next steps are "
            f"{', '.join(allowed)}. §42's path exists so nothing reaches "
            "production without review and regression")
    if to == NOT_CHANGING and not reason.strip():
        raise FeedbackError(
            "declining a correction needs a reason. A correction that "
            "vanishes teaches the user that feedback achieves nothing, and "
            "they stop giving it")
    return to


# --------------------------------------------------- §44 the score contract


def score_impact(*, before: dict[str, float], after: dict[str, float],
                 cases_before: int, cases_after: int,
                 critical_fixed: tuple[str, ...] = (),
                 critical_introduced: tuple[str, ...] = (),
                 release_id: str = "", reason: str = "") -> dict[str, Any]:
    """§44's before-and-after, once a correction has actually been evaluated.

    Reached only after an approved correction and an evaluation. Raw thumbs
    never call this: a validation score that moved because somebody clicked
    a thumb would be a popularity measure wearing an accuracy label.
    """
    dimensions = sorted(set(before) | set(after))
    return {
        "raw_thumbs_changed_nothing": True,
        "dimensions": [{
            "dimension": name,
            "before": round(before.get(name, 0.0), 4),
            "after": round(after.get(name, 0.0), 4),
            "points": round((after.get(name, 0.0)
                             - before.get(name, 0.0)) * 100, 2),
        } for name in dimensions],
        "cases_before": cases_before,
        "cases_after": cases_after,
        "case_set_changed": cases_before != cases_after,
        "critical_failures_fixed": list(critical_fixed),
        "critical_failures_introduced": list(critical_introduced),
        "confidence": _confidence(cases_after, critical_introduced),
        "release": release_id,
        "reason": reason,
        "note": (
            "The case set changed as well as the scores."
            if cases_before != cases_after else
            "Measured over the same case set before and after."
        ),
    }


#: Below this, a score change is not evidence of anything. Same number the
#: Lift Lab uses, and for the same reason: thirty cases is where a
#: difference stops being noise.
MINIMUM_CASES = 30


def _confidence(cases: int, critical_introduced: tuple[str, ...]) -> str:
    if critical_introduced:
        return ("NOT ESTABLISHED — a critical failure was introduced, and no "
                "average settles that")
    if cases < MINIMUM_CASES:
        return (f"NOT ESTABLISHED — {cases} case(s). Below {MINIMUM_CASES} a "
                "difference is not distinguishable from noise")
    return "MEASURED"


# ------------------------------------------------------------ §39 the prompt


def prompt(*, answer_kind: str, language: str = "en",
           already_given: bool = False) -> dict[str, Any]:
    """What to render under one answer. §39.

    Every kind gets the control, including the ones where feedback is
    awkward. An UNSUPPORTED answer with no thumbs collects no capability
    requests, and the absence reads as nobody wanting the capability.
    """
    if answer_kind not in ANSWER_KINDS:
        raise FeedbackError(f"{answer_kind!r} is not one of §39's kinds")
    return {
        "show": not already_given,
        "answer_kind": answer_kind,
        "kind_means": KIND_MEANS[answer_kind],
        "language": language,
        "up": {"label": "Good answer",
               "reasons": [{"id": r, "label": label}
                           for r, label in UP_REASONS]},
        "down": {
            "label": "Not a good answer",
            "question": "What would have been a better approach?",
            "explain": ("Describe how CreditProbe should have understood or "
                        "analysed the request. You do not need to provide "
                        "the numerical answer."),
            "fields": [{"id": f, "label": label, "help": help_}
                       for f, label, help_ in FIELDS],
            "anchors": [{"id": a, "means": means} for a, means in ANCHORS],
        },
        "what_happens_next": {
            "immediately": sorted(IMMEDIATE_FIELDS),
            "through_review": [f for f in FIELD_IDS
                               if f not in IMMEDIATE_FIELDS],
            "path": list(GOVERNED_PATH),
            "note": ("A preference about how an answer looks takes effect at "
                     "once. A correction about what an answer means goes "
                     "through review, regression and release — because "
                     "getting that wrong puts a wrong number in a credit "
                     "paper with an audit trail saying a user asked for it."),
        },
    }
