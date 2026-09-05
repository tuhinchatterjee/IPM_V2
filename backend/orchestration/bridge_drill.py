"""Drilling into one step of the ECL bridge, without losing the bridge.

Why this exists
---------------
"Give me an ECL decomposition" returns six portfolio steps. The next question a
credit officer asks is always the same one: *which borrowers did that?* Without
this module that follow-up was read as a fresh request — "which borrowers drove
the stage migration?" composed a ranking of `stage_moved` over the whole book,
which is a different question with a plausible-looking answer and no connection
to the six numbers on the screen above it.

What it does
------------
Reads a follow-up asked immediately after a bridge and decides whether it is a
drill into one of that bridge's steps. If it is, the bridge is re-run over the
SAME population and period and returns its own borrower-level contributions for
that step — the rows that already sum to the step impact — rather than a new
analysis that happens to share a subject.

The step is named the way a person names it, not by its key: "stage migration",
"SICR", "the macro step", "collateral", "the overlay". Where the question drills
without naming a step, the bridge's largest step is taken, because that is the
one the reader was just looking at.

What it deliberately does NOT do
--------------------------------
Fire on anything but a follow-up to a bridge. There is no standing rule that
"which borrowers…" means the decomposition; it means the decomposition only
when a decomposition is what the thread is holding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.ifrs9 import decomposition as bridge

#: The analysis a drill-down can drill into.
ANALYSIS = "ecl_decomposition"

#: The parameter the certified analysis takes to return borrowers for a step.
PARAMETER = "contributors_for"

#: How a person names each step. Ordered: the first match wins, so the more
#: specific phrasings come first.
_NAMED: tuple[tuple[str, str], ...] = (
    (r"\b(?:sicr|stage\s*migration|staging|stage\s*(?:1|2|3)|migration)\b",
     bridge.STAGE),
    (r"\b(?:collateral|lgd|loss\s*given\s*default|security|mitigation)\b",
     bridge.COLLATERAL),
    (r"\b(?:overlay|management\s*overlay|post[- ]model)\b", bridge.OVERLAY),
    (r"\b(?:macro|point[- ]in[- ]time|pit|forward[- ]looking|scenario)\b",
     bridge.MACRO),
    (r"\b(?:rating|grade|notch)\w*\b", bridge.RATING),
    (r"\b(?:baseline|through[- ]the[- ]cycle|ttc)\b", bridge.BASELINE),
)

_COMPILED = tuple((re.compile(p, re.I), key) for p, key in _NAMED)

#: The question has to be asking about the rows behind a figure. "Which
#: borrowers", "who", "show me the names", "break that down by borrower".
_DRILLS = re.compile(
    r"\b(?:which|what|who|show|list|name|give)\b[^?.!]{0,60}"
    r"\b(?:borrowers?|customers?|names?|obligors?|counterpart\w*|clients?)\b"
    r"|\bborrower[- ]level\b|\bby borrower\b|\bwho\s+(?:drove|caused|is|are)\b",
    re.I)

#: A step must be named, or the question must point back at the bridge itself.
_POINTS_BACK = re.compile(
    r"\b(?:that|this|it|those|the\s+(?:step|bridge|decomposition|move|movement|"
    r"impact))\b", re.I)


#: What the analysis is asked for when the question drills without naming a
#: step. Resolved against the bridge that runs, not guessed here.
LARGEST = "largest"


@dataclass(frozen=True)
class Drill:
    """A follow-up that drills into one step of the bridge on screen."""

    #: A step key, or LARGEST where the question pointed back without naming
    #: one. Never empty: the analysis is asked for a step either way.
    step: str
    named: bool

    @property
    def label(self) -> str:
        if self.step == LARGEST:
            return "largest"
        return bridge.STEP_LABELS[self.step][0]

    @property
    def because(self) -> str:
        which = ("the largest step of" if self.step == LARGEST
                 else f"the “{self.label}” step of")
        return (f"The question drills into {which} the ECL decomposition "
                "already on screen, so CreditProbe read the borrowers behind "
                "that step's own figure rather than running a separate "
                "analysis.")

    def parameters(self) -> dict[str, str]:
        return {PARAMETER: self.step}


def read(question: str, previous_analysis: str) -> Drill | None:
    """The step this follow-up drills into, if it drills into one.

    `previous_analysis` is what the thread last ran. Anything other than the
    bridge and this returns None immediately — a drill-down is a relationship
    between two turns, not a property of a sentence.
    """
    if previous_analysis != ANALYSIS:
        return None
    text = question or ""
    if not _DRILLS.search(text):
        return None

    for pattern, key in _COMPILED:
        if pattern.search(text):
            return Drill(step=key, named=True)
    # No step named, but the question points back at what is on screen. The
    # bridge's own largest step is the one the reader is looking at.
    if _POINTS_BACK.search(text):
        return Drill(step=LARGEST, named=False)
    return None


__all__ = ["ANALYSIS", "LARGEST", "PARAMETER", "Drill", "read"]
