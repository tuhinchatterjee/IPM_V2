"""
Which kind of question this is, decided before anything is spent. R2 §16.

Three classes, and they are about the ANSWER, not the wording
--------------------------------------------------------------
**A — data and metadata.** "How many datasets are in the liquidity domain?"
"What does `dscr` mean?" "Which periods do we hold?" "Rank the twenty
borrowers with the highest 12-month PD." These have exact answers that the
governed catalogue and the governed runtime already know. A model asked for
one can only agree with the answer or be wrong about it, so §16 is right that
it must not reach a frontier model at all.

**B — evidence gathering.** Several governed calls whose results have to be
assembled: a comparison across sectors, a borrower's position across four
domains, a follow-up that narrows an earlier population. Real orchestration,
and the work is choosing and sequencing the calls rather than judging what
they mean.

**C — credit judgement.** "Why did Shipping deteriorate this quarter?" "Which
of those worry you, and why?" "Should this borrower move to Stage 2?" The
evidence does not contain the answer; forming one is the job, and it is the
job worth paying for.

Deterministic, and it says when it is unsure
---------------------------------------------
No model decides the class — a call to decide whether to make a call is the
thing §16 is trying to remove. The reading is a closed vocabulary over verbs
and nouns, and every decision carries the sentence that explains it, so a
misclassification is arguable rather than mysterious.

Where the reading is ambiguous the class comes out B, never A: the failure
mode of routing a judgement question to a deterministic answer is a shallow
answer to a serious question, and the failure mode of routing a lookup to the
analyst is a few thousand tokens. Those are not symmetric, so neither is the
default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.analyst import cost

CLASSIFY_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# What makes a question a judgement
# ---------------------------------------------------------------------------

#: Asking for a cause, a view, a recommendation or a comparison of meaning.
#: "Why" is the clearest of them and is deliberately first: a question that
#: asks why is asking for an explanation, and an explanation is a judgement
#: however short the sentence is.
_JUDGEMENT = re.compile(
    r"\bwhy\b|\bwhat(?:'s| is) driving\b|\bwhat happened\b|\bexplain\b"
    r"|\bassess\b|\bassessment\b|\bjudge\b|\bin your view\b|\bdo you think\b"
    r"|\bworr(?:y|ies|ied|ying)\b|\bconcern(?:s|ed|ing)?\b"
    r"|\bshould (?:we|i|the bank|it|they)\b|\brecommend\b|\badvice\b"
    r"|\bwhat would you\b|\bhow serious\b|\bhow bad\b|\bmaterial\b"
    r"|\bimplication\b|\bconsequence\b|\bso what\b|\bwhat does (?:this|that|it) mean\b"
    r"|\bhypothes(?:is|es|ise)\b|\bplausib\w*\b|\blikel(?:y|ihood)\b"
    r"|\bearly warning\b|\bdeteriorat\w+\b|\bstress\b|\bscenario\b"
    r"|\breal issue\b|\bthe real\b|\bhow exposed\b|\bwhat should\b",
    re.IGNORECASE)

#: Open-ended work: an investigation rather than a question.
_BROAD = re.compile(
    r"\binvestigate\b|\blook into\b|\bdig into\b|\breview the\b"
    r"|\bwhat(?:'s| is) going on\b|\banything (?:worrying|concerning)\b"
    r"|\btell me about\b|\bwalk me through\b|\bsummar(?:ise|ize)\b",
    re.IGNORECASE)

#: Several things asked at once. A compound request needs a plan even when
#: each clause on its own would be a lookup.
_COMPOUND = re.compile(
    r"\band (?:also|then)\b|\bas well as\b|;\s|\balong with\b"
    r"|\bcompare\b.{0,40}\b(?:with|to|against)\b|\bversus\b|\bvs\.?\b",
    re.IGNORECASE)

# ---------------------------------------------------------------------------
# What makes a question a lookup
# ---------------------------------------------------------------------------

#: A request for a governed figure or a governed ordering, and nothing more.
#: These are class A when nothing above fires: the runtime computes them, and
#: an answer assembled by a model from the same table is the same answer with
#: a chance of being different.
_LOOKUP = re.compile(
    r"\bhow many\b|\bhow much\b|\bcount of\b|\bnumber of\b|\btotal\b"
    r"|\blist\b|\bshow (?:me )?(?:the |all )?\b|\bwhich borrowers? (?:have|has|are)\b"
    r"|\btop \d+\b|\bbottom \d+\b|\bhighest\b|\blowest\b|\bworst\b|\bbest\b"
    r"|\brank\b|\bsort(?:ed)? by\b|\bbreakdown by\b|\bby sector\b|\bby stage\b"
    r"|\baverage\b|\bmean\b|\bmedian\b|\bsum of\b|\bwhat is the\b",
    re.IGNORECASE)

#: Words whose SUBJECT is the deployment's data rather than the bank's book.
#: A second net under `backend.metadata.questions`, which reads a question to
#: ANSWER it and returns None the moment it is not confident. Confidence is
#: the right bar for answering and the wrong one for pricing: "how do
#: covenants join to facilities" is a question about the catalogue whether or
#: not the catalogue reader can name the two datasets, and paying a
#: frontier model four times over to discover that is the waste §16 names.
_CATALOGUE_NOUN = re.compile(
    r"\bdata ?sets?\b|\bdata domains?\b|\bbusiness domains?\b|\bcatalogue\b"
    r"|\bschema\b|\bfields?\b|\bcolumns?\b|\bgrain\b|\brow counts?\b"
    r"|\breporting periods?\b|\bperiods? (?:do we|are|does the)\b"
    r"|\bhow much history\b|\bwhat data\b|\bwhich data\b"
    r"|\bjoins? to\b|\bjoined to\b|\brelates? to\b|\brelationships? between\b"
    r"|\bwhat does\b.{0,40}\bmean\b|\bdefinition of\b|\bdefined as\b",
    re.IGNORECASE)

#: Several measures asked for at once. A list of three across three domains is
#: an assembly job even though every clause of it is a lookup, and the comma
#: that separates them is the only thing in the sentence that says so.
_MEASURE = re.compile(
    r"\bexposure\b|\bead\b|\bpd\b|\blgd\b|\becl\b|\bstage\b|\brating\b"
    r"|\bcovenant\b|\bcollateral\b|\bheadroom\b|\butilisation\b|\butilization\b"
    r"|\bdelinquenc\w+\b|\bdpd\b|\barrears\b|\bliquidity\b|\bleverage\b"
    r"|\bdscr\b|\bcoverage\b|\bprovision\b|\blimit\b",
    re.IGNORECASE)

#: A follow-up that narrows a population the conversation already has. Cheap
#: to serve and common in a working thread — "which of those have liquidity
#: pressure" is a filter over an existing result, not a new investigation.
_NARROWING = re.compile(
    r"\b(?:which|any) of (?:those|these|them)\b|\bof (?:those|these)\b"
    r"|\bnarrow (?:that|this|it)\b|\bjust the\b|\bonly the\b"
    r"|\bfilter (?:that|this|it)\b|\bsame (?:but|for)\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class Reading:
    """What class this question is, and the sentence that says why."""

    question_class: str
    why: str
    #: True when the catalogue can answer it outright with no runtime query.
    catalogue: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"question_class": self.question_class,
                "class_label": cost.CLASS_LABELS.get(self.question_class,
                                                     self.question_class),
                "why": self.why, "catalogue": self.catalogue}


def _is_catalogue(question: str) -> bool:
    """Whether the governed metadata service can answer this outright.

    Delegated rather than re-implemented: `backend.metadata.questions` already
    owns the distinction between a question about the bank's DATA and one
    about the bank's BORROWERS, and a second reading of the same sentence in
    a second module is a second thing to keep in agreement.
    """
    try:
        from backend.metadata import questions as mdq

        return mdq.read(question) is not None
    except Exception:  # noqa: BLE001 - an unreadable catalogue is not class A
        return False


def read(question: str, *, continuation: bool = False) -> Reading:
    """Classify one question. Deterministic, and cheap enough to always run."""
    text = " ".join((question or "").split())
    if not text:
        return Reading(cost.CLASS_B, "the question is empty")

    if _is_catalogue(text):
        return Reading(cost.CLASS_A,
                       "this asks about the data itself, which the governed "
                       "catalogue answers exactly",
                       catalogue=True)

    # Judgement is checked before lookup, and the order is the decision: "why
    # are the top ten borrowers the top ten" contains "top 10" and is not a
    # ranking request. A sentence that asks for both a figure and a view is a
    # question about the view.
    if _JUDGEMENT.search(text):
        return Reading(cost.CLASS_C,
                       "this asks for an explanation or a view, which the "
                       "evidence does not contain")
    if _BROAD.search(text):
        return Reading(cost.CLASS_C,
                       "this is open-ended, so what to look at is part of "
                       "the question")

    if _CATALOGUE_NOUN.search(text):
        return Reading(cost.CLASS_A,
                       "the subject of this question is the data itself, "
                       "not the book",
                       catalogue=True)

    if _COMPOUND.search(text) or len(set(
            m.group(0).lower() for m in _MEASURE.finditer(text))) >= 3:
        return Reading(cost.CLASS_B,
                       "this asks for more than one thing, so the evidence "
                       "has to be gathered and assembled")

    if _NARROWING.search(text) and continuation:
        return Reading(cost.CLASS_A,
                       "this narrows a population the conversation already "
                       "holds")

    if _LOOKUP.search(text):
        return Reading(cost.CLASS_A,
                       "this asks for a governed figure or ordering, which "
                       "the runtime computes exactly")

    return Reading(cost.CLASS_B,
                   "the request needs governed evidence gathered before it "
                   "can be answered")


__all__ = ["CLASSIFY_VERSION", "Reading", "read"]
