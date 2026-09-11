"""
The conceptual questions a validator is asked, and the governed answer to each.

The failure this exists for
----------------------------
    "Gini has fallen. Does that mean the predicted PDs are wrong?"

is question four of the assurance set, and the expected answer is written into
the brief: *no, not necessarily — discrimination and calibration must be
separated.* The module replied "Which scorecard?"

    "Your Gini is acceptable, so why are you concerned?"

is question nineteen, asked in the auditor's voice, and it got the same reply.

Neither question names a scorecard, because neither is about one. They are
about what a statistic MEANS, and a module that can compute forty-eight of
them and cannot say what any of them means is a calculator with a chat box.

Why a written register rather than a model
--------------------------------------------
These are the sentences somebody repeats in a committee. A paraphrase
generated per request is a sentence nobody reviewed, delivered in the one
place where being subtly wrong is most expensive — and this module's whole
design principle is that it does not write prose about numbers.

So each principle is written here, once, in the open, and every one of them
names the tests that would SETTLE the question rather than leaving the reader
with an aphorism. A conceptual answer that ends "and here is how you would
check" is a different thing from an opinion.

What is deliberately not here
-------------------------------
Nothing about a particular model, a particular month or a particular figure. A
principle is true before the data is read; the moment an answer depends on a
number it belongs to a test, and the register says which one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PRINCIPLES_VERSION = "1.0.0"


@dataclass(frozen=True)
class Principle:
    """One thing a validator has to be able to say, and how to check it."""

    principle_id: str
    question: str
    #: The answer, in the words it should be repeated in.
    answer: str
    #: Tests that would settle the question on a particular model.
    settled_by: tuple[str, ...]
    #: What the reader must not take the answer to mean.
    caution: str = ""
    #: How the question is recognised. Every pattern must be specific enough
    #: that it cannot fire on a request for a figure.
    patterns: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        from backend.scorecard.validation import registry as test_registry

        return {
            "principles_version": PRINCIPLES_VERSION,
            "principle_id": self.principle_id,
            "question": self.question,
            "answer": self.answer,
            "caution": self.caution,
            "settled_by": [
                {"test_id": t,
                 "name": test_registry.BY_ID[t].name,
                 "purpose": test_registry.BY_ID[t].purpose}
                for t in self.settled_by if t in test_registry.BY_ID],
            "this_is_not_a_figure": (
                "This is a statement about what the statistics mean. It is "
                "true before any data is read, and it is not a result about "
                "any model. The tests named beside it are what would settle "
                "the question for a particular scorecard."),
        }


PRINCIPLES: tuple[Principle, ...] = (
    Principle(
        "DISCRIMINATION-IS-NOT-CALIBRATION",
        "Gini has fallen. Does that mean the predicted PDs are wrong?",
        "No, not necessarily, and the two questions have to be kept apart. "
        "Discrimination — Gini, AUC, KS — asks whether the score puts the "
        "accounts that defaulted below the accounts that did not. Calibration "
        "asks whether the probability attached to each score is the rate "
        "those accounts actually defaulted at. A model can rank perfectly and "
        "be calibrated to the wrong level, and a model can be calibrated on "
        "average while ranking no better than chance. A fall in Gini says the "
        "ORDERING has weakened. Whether the probabilities are wrong is "
        "answered by observed against expected, by the band-level comparison, "
        "and by the calibration slope — and it is entirely possible for those "
        "to be sound in the same period in which Gini fell.",
        ("DISC-GINI", "CAL-OE", "CAL-BAND", "CAL-SLOPE", "CAL-BRIER"),
        caution="A fall in Gini between two cohorts is not automatically a "
                "deterioration either: on a few hundred events the statistic "
                "moves several points on sampling alone, which is what the "
                "confidence interval and the rolling window are for.",
        patterns=(
            r"gini.{0,60}\bfall\w*|gini.{0,60}\bfell\b|gini.{0,60}\bdrop\w*",
            r"(?:discriminat\w+|auc|gini|ks).{0,80}"
            r"(?:mean|imply|means).{0,60}(?:pd|probabilit|calibrat)",
            r"(?:pd|probabilit)\w*.{0,40}wrong",
        )),
    Principle(
        "DISCRIMINATION-IS-NOT-ENOUGH",
        "The Gini is acceptable, so why be concerned?",
        "Because ranking is one of several things a scorecard has to do, and "
        "it is the only one Gini speaks to. An acceptable Gini is consistent "
        "with predicted default rates that are materially too low, with a "
        "population that has moved away from the one the model was fitted "
        "on, with a characteristic whose risk ordering has reversed, with a "
        "production implementation that is not the approved specification, "
        "and with a model that ranks well in aggregate and not at all inside "
        "the segment most decisions are taken in. Each of those is a separate "
        "test, each has its own limit, and none of them is implied by the "
        "Gini being above its floor.",
        ("CAL-OE", "STAB-PSI", "STAB-CSI", "VAR-WOE", "IMPL-REPLICATE",
         "SEG-DISCRIMINATION"),
        caution="Nor does an acceptable Gini say the model is fit for its "
                "use. Fitness for use is a judgement about the decision the "
                "score is taken into, and no statistic settles it.",
        patterns=(
            r"gini is (?:acceptable|fine|ok|okay|good)",
            r"(?:acceptable|fine|good).{0,30}gini.{0,40}(?:why|so what)",
            r"why.{0,40}(?:concerned|worried|worry)",
            r"(?:is|isn't|is not) (?:the )?gini enough",
        )),
    Principle(
        "A-SHIFT-IS-NOT-A-FAILURE",
        "The population has shifted. Has the model failed?",
        "Not by itself. Population stability measures whether the book being "
        "scored looks like the book the model was fitted on. A shift is a "
        "statement about the portfolio — a new channel, a new segment, a "
        "changed appetite — and it is a reason to look at performance sooner, "
        "not a finding about performance. What makes a shift matter is "
        "whether discrimination or calibration moved with it, and that is "
        "measured directly rather than inferred.",
        ("STAB-PSI", "STAB-CSI", "DISC-GINI", "CAL-OE", "DATA-REPRESENTATIVE"),
        caution="The conventional PSI cut-offs are scorecard practice, not a "
                "regulatory threshold, and this deployment labels them as "
                "demonstration policy wherever they are shown.",
        patterns=(
            r"(?:population|score distribution).{0,40}shift\w*.{0,60}"
            r"(?:fail|broken|wrong|problem)",
            r"(?:psi|population stability).{0,60}(?:mean|imply).{0,40}fail",
            r"does a (?:shift|drift) mean",
        )),
    Principle(
        "AN-OPEN-WINDOW-IS-NOT-A-LOW-DEFAULT-RATE",
        "The recent months show almost no defaults. Is the book improving?",
        "Almost certainly not — those months have not matured. A twelve-month "
        "outcome is not known until twelve months have passed, so the most "
        "recent cohorts carry the defaults that have happened so far and none "
        "of the ones that have not happened yet. Reading them as a rate "
        "reports a partial count over a complete denominator, which falls "
        "monotonically towards the present whatever the book is doing. Every "
        "outcome test in this module refuses an immature cohort by name "
        "rather than measuring it.",
        ("DATA-MATURITY", "DATA-ROWS", "DISC-TREND", "CAL-DRIFT"),
        caution="The opposite error is as common: scoping a cohort on rows "
                "that HAVE a recorded outcome selects the accounts that have "
                "already defaulted, and reports a default rate near 100%.",
        patterns=(
            r"(?:recent|latest|last).{0,30}months?.{0,60}"
            r"(?:no|few|fewer|lower).{0,20}default",
            r"(?:book|portfolio).{0,30}improv\w*",
            r"why.{0,40}(?:immature|not matured|window.{0,20}open)",
        )),
    Principle(
        "A-LIMIT-IS-NOT-A-REGULATION",
        "Is the threshold this breached a regulatory requirement?",
        "No. Every limit seeded in this deployment is labelled DEMO POLICY "
        "and is a conventional scorecard-practice cut-off — an AUC floor, a "
        "PSI ceiling, an observed-over-expected band. A deployment governs "
        "and versions its own limits, and a breach here is a breach of the "
        "limit recorded on the model, not of any published rule. The "
        "exceptions are the structural tests, where the tolerance is zero "
        "because there is no defensible non-zero one: a duplicated key, a "
        "production score that does not reproduce from its own "
        "specification, a term scored against its own credit sense.",
        ("DISC-AUC", "STAB-PSI", "CAL-OE", "DATA-DUPLICATES",
         "IMPL-REPLICATE", "VAR-SIGN"),
        caution="This installation carries no approved Regulatory Knowledge "
                "Release, so nothing in this module cites a supervisor's "
                "text at all.",
        patterns=(
            r"(?:is|are) (?:the |this |that )?(?:limit|threshold|cut.?off)s?"
            r".{0,40}(?:regulat|require|mandat|law|sama|rule)",
            r"regulatory (?:requirement|threshold|limit)",
            r"who set (?:the )?(?:limit|threshold)",
        )),
)

BY_ID: dict[str, Principle] = {p.principle_id: p for p in PRINCIPLES}

#: Words that mean the sentence is asking for a FIGURE. A principle must not
#: answer one of those: "what is the Gini" and "does a fallen Gini mean the
#: PDs are wrong" are different requests and only the second is conceptual.
#: Anchored at the front, deliberately. A verb like "show" is a request for a
#: figure when it governs the sentence — "show me the Gini" — and is not one
#: when it merely appears in it: "the recent months SHOW almost no defaults.
#: Is the book improving?" is a conceptual question, and an unanchored word
#: list read it as a request for a number and refused to answer it.
_WANTS_A_FIGURE = re.compile(
    r"^(?:please\s+|can you\s+|could you\s+|i'd like you to\s+)?"
    r"(?:show|give|run|calculate|compute|list|display|produce)\b"
    r"|\bwhat is the (?:value|number|figure)\b|\bhow much\b",
    re.IGNORECASE)


def read(question: str) -> Principle | None:
    """The principle this question asks about, or `None`.

    `None` is the ordinary outcome. A conceptual route that fires on a request
    for a number would answer "what is the Gini?" with an essay.
    """
    text = " ".join(str(question or "").lower().split())
    if not text:
        return None
    if _WANTS_A_FIGURE.search(text):
        return None
    for principle in PRINCIPLES:
        for pattern in principle.patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return principle
    return None


def summary() -> dict[str, Any]:
    return {"principles_version": PRINCIPLES_VERSION,
            "principles": [p.to_dict() for p in PRINCIPLES],
            "count": len(PRINCIPLES)}


__all__ = ["BY_ID", "PRINCIPLES", "PRINCIPLES_VERSION", "Principle", "read",
           "summary"]
