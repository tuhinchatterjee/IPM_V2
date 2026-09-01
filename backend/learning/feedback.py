"""
The question CreditProbe asks after an answer, and what it does with the
reply. §7-§11.

The exact question
-------------------
    Was this answer accurate and useful?

Not a thumb. A thumb collects a mood; this collects a claim, and the two words
are load-bearing in different directions. ACCURATE is about the figures and
belongs to the analyst who can check them. USEFUL is about the answer and
belongs to whoever asked. An answer can be perfectly accurate and useless, and
the product needs to hear that separately from "wrong", because the two lead
to completely different work.

PARTLY and NOT SURE are not padding
-------------------------------------
PARTLY is the most common honest answer to a long analytical response and the
one a binary control destroys: forced to choose, a user who thinks three of
four numbers are right picks YES, and the fourth number is never reported.

NOT SURE is the answer of somebody who cannot check. It is the single most
useful signal in the set, because it says the answer was not verifiable by the
person reading it — which is a product failure that no accuracy measurement
will ever find.

SKIP is recorded
-----------------
A skipped prompt is data: it says the user saw the question and declined. It
is not the same as never being asked, and collapsing the two would make the
response rate meaningless.

Raw feedback changes nothing
------------------------------
§11 is the rule the rest of this package exists to keep. A `FeedbackEvent` is
immutable, is linked to everything needed to reproduce the answer it is about,
and cannot modify an Assurance status, a score, a plan, a result, a
certification, a release, a prompt, a routing policy, a model selection, the
ontology or a method. `backend/learning/guard.py` proves that structurally,
and there are runtime tests as well, because a rule that only holds by
convention holds until somebody is in a hurry.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

FEEDBACK_EVENT_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

#: §7's exact wording. A constant, and a test asserts it, because a question
#: that drifts makes a satisfaction series uncomparable across the quarters it
#: exists to be compared over.
QUESTION = "Was this answer accurate and useful?"

YES = "YES"
PARTLY = "PARTLY"
NO = "NO"
NOT_SURE = "NOT_SURE"
SKIP = "SKIP"

ANSWERS: tuple[str, ...] = (YES, PARTLY, NO, NOT_SURE, SKIP)

ANSWER_LABELS: dict[str, str] = {
    YES: "Yes",
    PARTLY: "Partly",
    NO: "No",
    NOT_SURE: "Not sure",
    SKIP: "Skip",
}

ANSWER_MEANS: dict[str, str] = {
    YES: "The figures are right and the answer was worth having.",
    PARTLY: "Some of it holds and some of it does not.",
    NO: "Wrong, or wrong enough that it could not be used.",
    NOT_SURE: "The reader could not tell — which is a finding about the "
              "answer, not about the reader.",
    SKIP: "Seen and declined. Recorded, because a skipped prompt is not the "
          "same as one that was never shown.",
}

#: The answers that open the detail panel. §8.
WANTS_DETAIL: frozenset[str] = frozenset({PARTLY, NO})

#: The answers that count as a response for the response-rate metric. SKIP is
#: a response to the prompt and not a rating, so it is counted separately.
RATED: frozenset[str] = frozenset({YES, PARTLY, NO, NOT_SURE})

# ---------------------------------------------------------------------------
# Where the prompt may and may not appear. §7.
# ---------------------------------------------------------------------------

COCKPIT = "COCKPIT"
PROJECT = "PROJECT"
RISK_CASE = "RISK_CASE"
SAVED_ANALYSIS = "SAVED_ANALYSIS"

SURFACES: tuple[str, ...] = (COCKPIT, PROJECT, RISK_CASE, SAVED_ANALYSIS)

#: Reasons the prompt is suppressed, each one a state it must not appear in.
RUNNING = "the answer is still running"
SKELETON = "this is a loading skeleton, not an answer"
SYSTEM_ERROR = "an error was shown before any answer existed"
DISMISSED = "the user dismissed the prompt for this answer"
THREAD_OFF = "the user turned the prompt off for this thread"
USER_OFF = "the user turned feedback prompts off"
ALREADY_GIVEN = "feedback has already been given on this answer"

SUPPRESSIONS: tuple[str, ...] = (RUNNING, SKELETON, SYSTEM_ERROR, DISMISSED,
                                 THREAD_OFF, USER_OFF, ALREADY_GIVEN)


@dataclass(frozen=True)
class Placement:
    """Whether to show the prompt on one answer, and why not when not."""

    show: bool
    because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"show": self.show, "because": self.because,
                "question": QUESTION if self.show else "",
                "answers": [{"value": a, "label": ANSWER_LABELS[a],
                             "means": ANSWER_MEANS[a]}
                            for a in ANSWERS] if self.show else []}


def placement(*, complete: bool, is_error: bool = False,
              is_skeleton: bool = False, already_answered: bool = False,
              dismissed: bool = False, thread_muted: bool = False,
              user_muted: bool = False) -> Placement:
    """§7's rules, in the order that makes the reason useful.

    The order matters: a user who has turned prompts off should be told that,
    not told the answer is still running. The most specific state the caller
    is in wins.
    """
    if user_muted:
        return Placement(False, USER_OFF)
    if thread_muted:
        return Placement(False, THREAD_OFF)
    if already_answered:
        return Placement(False, ALREADY_GIVEN)
    if dismissed:
        return Placement(False, DISMISSED)
    if is_skeleton:
        return Placement(False, SKELETON)
    if is_error:
        return Placement(False, SYSTEM_ERROR)
    if not complete:
        return Placement(False, RUNNING)
    return Placement(True)


# ---------------------------------------------------------------------------
# §8's issue categories. Twenty-three.
# ---------------------------------------------------------------------------

#: (id, label, what it means). Ordered the way the pipeline runs, so a user
#: scanning the list finds the earliest thing that went wrong rather than the
#: most visible one — "wrong period" is above "wrong result" because a wrong
#: period PRODUCES a wrong result, and reporting the symptom loses the cause.
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("wrong_intent", "Wrong question or intent",
     "CreditProbe answered a different question."),
    ("wrong_officer", "Wrong officer or agent",
     "The wrong level of seniority, or the wrong specialists."),
    ("wrong_dataset", "Wrong dataset",
     "It read the wrong governed source."),
    ("wrong_field", "Wrong field or definition",
     "The right dataset, the wrong column or the wrong definition of it."),
    ("wrong_exposure", "Wrong exposure concept",
     "Limit, drawn, EAD and net exposure are different amounts."),
    ("wrong_period", "Wrong period",
     "The wrong quarter, the wrong window, or the wrong as-of date."),
    ("wrong_population", "Wrong population",
     "The filters selected the wrong set of borrowers or facilities."),
    ("wrong_grain", "Wrong grain",
     "One row should have been a portfolio, a segment, a customer or a "
     "facility, and was not."),
    ("wrong_join", "Wrong join or relationship",
     "The wrong path between datasets, or a join that multiplied rows."),
    ("wrong_calculation", "Wrong calculation",
     "The arithmetic itself."),
    ("wrong_method", "Wrong method",
     "A different governed method should have been used."),
    ("wrong_result", "Wrong result",
     "The figures do not match what the reader can verify."),
    ("wrong_interpretation", "Wrong interpretation",
     "The numbers are right and what CreditProbe said about them is not."),
    ("incomplete", "Incomplete answer",
     "Part of the question was not answered."),
    ("unsupported_claim", "Unsupported claim",
     "It asserted something the evidence does not carry."),
    ("missed_exception", "Missed exception",
     "A carve-out, an exclusion or a special case was not applied."),
    ("wrong_visual", "Wrong chart or table",
     "The right figures, shown in a form that misleads."),
    ("too_much_detail", "Too much detail",
     "The answer buried what mattered."),
    ("too_little_detail", "Too little detail",
     "The answer needed working shown."),
    ("broken_navigation", "Broken link or navigation",
     "Something did not open, or came back to the wrong place."),
    ("slow", "Slow response",
     "It was right and it took too long to be useful."),
    ("regulatory_source", "Regulatory source or citation issue",
     "A wrong source, an outdated circular, a wrong effective date, a "
     "missing exception, or a claim with no citation behind it."),
    ("other", "Something else",
     "Say what, in your own words."),
)

CATEGORY_IDS: tuple[str, ...] = tuple(c for c, _, _ in CATEGORIES)
CATEGORY_LABELS: dict[str, str] = {c: label for c, label, _ in CATEGORIES}
CATEGORY_MEANS: dict[str, str] = {c: means for c, _, means in CATEGORIES}

#: Categories that route to a regulatory SME rather than to the analytical
#: review queue. §28.
REGULATORY_CATEGORIES: frozenset[str] = frozenset({"regulatory_source",
                                                   "missed_exception"})

#: Categories that are a presentation preference rather than a claim about
#: correctness. §13's channel A may act on these immediately, per user; §13's
#: channel B may not act on anything without review.
PRESENTATION_CATEGORIES: frozenset[str] = frozenset({
    "too_much_detail", "too_little_detail", "wrong_visual"})

#: Categories that are a product defect rather than an analytical error. They
#: go to engineering, not to a teaching case.
PRODUCT_CATEGORIES: frozenset[str] = frozenset({"broken_navigation", "slow"})

# ---------------------------------------------------------------------------
# §29's consent
# ---------------------------------------------------------------------------

#: The exact sentence a user is shown. Quoted from §29.
CONSENT_QUESTION = "Use this feedback to improve this bank's CreditProbe"

CONSENT_GRANTED = "GRANTED"
CONSENT_REFUSED = "REFUSED"
CONSENT_UNSET = "UNSET"

CONSENTS: tuple[str, ...] = (CONSENT_GRANTED, CONSENT_REFUSED, CONSENT_UNSET)

CONSENT_MEANS: dict[str, str] = {
    CONSENT_GRANTED: "This feedback may become a candidate learning case for "
                     "this bank, subject to review. It never leaves this "
                     "tenant.",
    CONSENT_REFUSED: "Recorded as a satisfaction signal and as a bug report. "
                     "It will not become a learning candidate.",
    CONSENT_UNSET: "The bank's configured default applies. Where that default "
                   "is unknown, the feedback is treated as REFUSED.",
}


def may_learn_from(consent: str, *, default: str = CONSENT_REFUSED) -> bool:
    """Whether this feedback may become a learning candidate.

    Fail-closed on an unknown default. A deployment that has not configured
    one does not thereby consent on its users' behalf.
    """
    if consent == CONSENT_GRANTED:
        return True
    if consent == CONSENT_REFUSED:
        return False
    return default == CONSENT_GRANTED


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

#: What must never be stored in a feedback comment. The same list the Part E
#: feedback schema refuses on, for the same reason: a comment box is the one
#: place a user can paste anything.
FORBIDDEN = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9]{20,}|"
    r"Bearer\s+[A-Za-z0-9._\-]{16,}|"
    r"authorization:\s*\S+|api[_-]?key\s*[:=]\s*\S+|"
    r"password\s*[:=]\s*\S+)", re.IGNORECASE)

REDACTED = "[redacted]"


class WouldStoreSecret(Exception):
    """A comment that cannot be stored as written."""


def scrub(text: str) -> str:
    """Remove what must not be kept, and say that something was removed."""
    return FORBIDDEN.sub(REDACTED, str(text or ""))


# ---------------------------------------------------------------------------
# The event
# ---------------------------------------------------------------------------


@dataclass
class Correction:
    """What the user says the answer should have been. §8.

    Never treated as true. A correction is a claim by one person about one
    answer, and the pipeline's whole job is to find out whether it holds —
    which is why every field here is what the user SAID rather than what is
    the case.
    """

    conclusion: str = ""
    value: str = ""
    preferred_dataset: str = ""
    preferred_period: str = ""
    preferred_method: str = ""
    expected_visualization: str = ""
    reference: str = ""

    @property
    def empty(self) -> bool:
        return not any((self.conclusion, self.value, self.preferred_dataset,
                        self.preferred_period, self.preferred_method,
                        self.expected_visualization, self.reference))

    def to_dict(self) -> dict[str, Any]:
        return {"conclusion": self.conclusion, "value": self.value,
                "preferred_dataset": self.preferred_dataset,
                "preferred_period": self.preferred_period,
                "preferred_method": self.preferred_method,
                "expected_visualization": self.expected_visualization,
                "reference": self.reference, "empty": self.empty}


@dataclass
class Satisfaction:
    """§9's positive-feedback fields.

    Collected on YES and never used to raise anything. A satisfaction rating
    is not proof of analytical correctness, and §9 says so in as many words;
    these exist so a product metric can be measured, and are kept in their own
    object so that no code path can confuse them with an accuracy score.
    """

    reason: str = ""
    satisfaction: int | None = None
    helpfulness: int | None = None
    clarity: int | None = None
    trust: int | None = None
    #: What the user did with it — saved, shared, exported, sent to workflow,
    #: added to a Project. The strongest positive signal there is, because it
    #: is behaviour rather than opinion.
    used_as: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "satisfaction": self.satisfaction,
                "helpfulness": self.helpfulness, "clarity": self.clarity,
                "trust": self.trust, "used_as": list(self.used_as)}


@dataclass
class FeedbackEvent:
    """§10's immutable event. Twenty-four links, and every one earns its place.

    The links are what separate a bug report from an opinion. "The ECL number
    was wrong" is unactionable; the same sentence beside the run, the plan
    fingerprint, the datasets, the versions and the build is something a
    person can reproduce next Tuesday.

    Immutability is by construction: `revise` returns a NEW event that points
    at the one it supersedes. Nothing overwrites historical feedback, because
    a user who changes their mind has said two things and the sequence is part
    of what they said.
    """

    # ---- identity
    event_id: str = field(
        default_factory=lambda: f"fb-{uuid.uuid4().hex[:16]}")
    version: int = 1
    supersedes: str = ""

    # ---- who and where (§10, links 1-5)
    tenant: str = ""
    user_id: str = ""
    project_id: str = ""
    investigation_id: str = ""
    message_id: str = ""

    # ---- what was answered (links 6-12)
    question: str = ""
    answer_id: str = ""
    answer_text: str = ""
    analysis_run_ids: list[str] = field(default_factory=list)
    trace_version: str = ""
    agentic_run_id: str = ""
    result_fingerprint: str = ""

    # ---- how it was produced (links 13-20)
    officer_level: int | None = None
    officer_title: str = ""
    agents: list[str] = field(default_factory=list)
    model_roles: dict[str, str] = field(default_factory=dict)
    build_sha: str = ""
    data_versions: dict[str, str] = field(default_factory=dict)
    method_versions: dict[str, str] = field(default_factory=dict)
    plan_fingerprint: str = ""

    # ---- what was checked (link 21)
    assurance_record_id: str = ""

    # ---- the feedback itself (links 22-24)
    rating: str = SKIP
    categories: list[str] = field(default_factory=list)
    comment: str = ""
    correction: Correction = field(default_factory=Correction)
    satisfaction: Satisfaction = field(default_factory=Satisfaction)
    consent: str = CONSENT_UNSET
    surface: str = COCKPIT
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = FEEDBACK_EVENT_VERSION

    @property
    def reproducible(self) -> bool:
        """Whether somebody could reproduce the answer this is about.

        Not a judgement about the feedback's value — a reasonless NO on an
        unreproducible answer is still a signal that somebody was unhappy.
        It decides what the item can be USED for: an irreproducible item can
        feed satisfaction metrics and can never become a candidate learning
        case, because there is nothing to replay.
        """
        return bool(self.answer_id and self.build_sha
                    and (self.plan_fingerprint or self.agentic_run_id))

    @property
    def regulatory(self) -> bool:
        return bool(set(self.categories) & REGULATORY_CATEGORIES)

    @property
    def presentation_only(self) -> bool:
        """Whether everything reported is a presentation preference.

        §13's channel A may act on these per user immediately. A mixture is
        not: an answer that was too detailed AND used the wrong period is a
        correctness report, and treating it as a preference loses the period.
        """
        chosen = set(self.categories)
        return bool(chosen) and chosen <= PRESENTATION_CATEGORIES

    def links(self) -> dict[str, Any]:
        """§10's link set, named, for the audit surface."""
        return {
            "tenant": self.tenant, "user": self.user_id,
            "project": self.project_id, "investigation": self.investigation_id,
            "message": self.message_id, "question": self.question,
            "answer": self.answer_id,
            "analysis_runs": list(self.analysis_run_ids),
            "trace_version": self.trace_version,
            "agentic_run": self.agentic_run_id,
            "result_fingerprint": self.result_fingerprint,
            "officer_level": self.officer_level,
            "officer": self.officer_title,
            "agents": list(self.agents),
            "model_roles": dict(self.model_roles),
            "build_sha": self.build_sha,
            "data_versions": dict(self.data_versions),
            "method_versions": dict(self.method_versions),
            "plan_fingerprint": self.plan_fingerprint,
            "assurance_record": self.assurance_record_id,
            "rating": self.rating,
            "categories": list(self.categories),
            "consent": self.consent,
            "at": self.at.isoformat(),
        }

    def fingerprint(self) -> str:
        body = json.dumps({**self.links(), "comment": self.comment,
                           "correction": self.correction.to_dict()},
                          sort_keys=True, separators=(",", ":"),
                          default=str)
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "version": self.version,
            "supersedes": self.supersedes,
            **self.links(),
            "answer_text": self.answer_text,
            "comment": self.comment,
            "correction": self.correction.to_dict(),
            "satisfaction": self.satisfaction.to_dict(),
            "surface": self.surface,
            "reproducible": self.reproducible,
            "regulatory": self.regulatory,
            "presentation_only": self.presentation_only,
            "may_learn": may_learn_from(self.consent),
            "fingerprint": self.fingerprint(),
            "schema_version": self.schema_version,
        }


class FeedbackError(Exception):
    """Feedback that cannot be recorded as given."""


def create(*, rating: str, answer_id: str, categories: list[str] | None = None,
           comment: str = "", correction: Correction | None = None,
           satisfaction: Satisfaction | None = None,
           consent: str = CONSENT_UNSET, surface: str = COCKPIT,
           **links: Any) -> FeedbackEvent:
    """One immutable feedback event, validated on the way in."""
    if rating not in ANSWERS:
        raise FeedbackError(
            f"{rating!r} is not an answer to {QUESTION!r}: "
            + ", ".join(ANSWERS))
    if not str(answer_id).strip():
        raise FeedbackError(
            "feedback needs the answer it is about; without one it is an "
            "opinion rather than a report")
    if surface not in SURFACES:
        raise FeedbackError(f"{surface!r} is not a surface: "
                            + ", ".join(SURFACES))
    if consent not in CONSENTS:
        raise FeedbackError(f"{consent!r} is not a consent state")

    chosen = [c for c in (categories or [])]
    unknown = [c for c in chosen if c not in CATEGORY_IDS]
    if unknown:
        raise FeedbackError(
            f"unknown issue categor{'y' if len(unknown) == 1 else 'ies'}: "
            + ", ".join(unknown))
    if rating in (YES, NOT_SURE, SKIP) and chosen:
        raise FeedbackError(
            f"issue categories belong to {PARTLY} or {NO}; a {rating} with a "
            "list of what went wrong is two different answers")

    cleaned = scrub(comment)
    known = {k: v for k, v in links.items()
             if k in FeedbackEvent.__dataclass_fields__}
    return FeedbackEvent(
        rating=rating, answer_id=str(answer_id).strip(), categories=chosen,
        comment=cleaned, correction=correction or Correction(),
        satisfaction=satisfaction or Satisfaction(), consent=consent,
        surface=surface, **known)


def revise(previous: FeedbackEvent, **changes: Any) -> FeedbackEvent:
    """A new event that supersedes an earlier one. Nothing is overwritten.

    §10: "A subsequent edit creates a new version/event. Do not overwrite
    historical feedback." A user who changes their mind has said two things,
    and which they said first is part of what they said.
    """
    fields = {name: getattr(previous, name)
              for name in FeedbackEvent.__dataclass_fields__
              if name not in ("event_id", "version", "supersedes", "at")}
    fields.update({k: v for k, v in changes.items() if k in fields})
    if "comment" in changes:
        fields["comment"] = scrub(str(changes["comment"]))
    return FeedbackEvent(version=previous.version + 1,
                         supersedes=previous.event_id, **fields)


def acknowledgement(rating: str) -> str:
    """What the user is told. §25.

    Never "CreditProbe has learned this." It has not, it will not until a
    person reviews it, and a product that says otherwise buys a moment of
    goodwill against the next time the same question gets the same answer.
    """
    if rating == SKIP:
        return "No problem."
    if rating == YES:
        return "Thank you. Recorded."
    return ("Thank you. This is recorded against the exact run, and goes to "
            "review. Nothing changes automatically.")


__all__ = [
    "ANSWERS", "ANSWER_LABELS", "ANSWER_MEANS", "CATEGORIES", "CATEGORY_IDS",
    "CATEGORY_LABELS", "CATEGORY_MEANS", "COCKPIT", "CONSENTS",
    "CONSENT_GRANTED", "CONSENT_MEANS", "CONSENT_QUESTION", "CONSENT_REFUSED",
    "CONSENT_UNSET", "Correction", "FEEDBACK_EVENT_VERSION", "FeedbackError",
    "FeedbackEvent", "NO", "NOT_SURE", "PARTLY", "PRESENTATION_CATEGORIES",
    "PRODUCT_CATEGORIES", "PROJECT", "Placement", "QUESTION", "RATED",
    "REGULATORY_CATEGORIES", "RISK_CASE", "SAVED_ANALYSIS", "SKIP",
    "SURFACES", "SUPPRESSIONS", "Satisfaction", "WANTS_DETAIL",
    "WouldStoreSecret", "YES", "acknowledgement", "create", "may_learn_from",
    "placement", "revise", "scrub",
]
