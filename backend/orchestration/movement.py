"""«moved» is «changed». Phase 0B.

The defect
----------
    "How has ECL changed?"   →  the certified ECL movement, Q1 2026 → Q2 2026
    "How has ECL moved?"     →  5,313 SAR mn of expected credit loss at Q2 2026

Two spellings of one question, and the second silently became a different
question. Not a clarification, not a warning — a level where a movement was
asked for, presented with the same confidence as the right answer. A reader
who did not already know the number has no way to tell.

Why it happened
---------------
Every layer that has to decide "is this about a change or about a level?"
carried its own list of words, and the lists had drifted:

    router._period_requirement   movement ✓   moved ✗
    router._OPERATIONS           movement ✓   moved ✗
    certified._CHANGE            movement ✓   moved ✓
    fidelity._WANTS_MOVEMENT     movement ✓   moved ✓

So the routing layer read "movement" and not "moved", the layer that picks a
certified methodology read both, and which answer came back depended on which
list the sentence happened to land in. Adding "moved" to one list would fix
the reported sentence and leave the next one to be found by a user.

The rule
--------
One vocabulary, in one place, read by every layer that asks the question.
Where a layer needs a wider or narrower reading it says so by naming the tier
it reads, not by keeping a private copy.

Two tiers, because they are not equally safe
--------------------------------------------
`CHANGE` is a word that says a change outright — "moved", "rose", "worsened".
It carries the reading on its own.

`WEAK` is a word that names a change only when something else already implies
one — "between", "since", "compared to". "The relationship between PD and LGD"
is one date and two measures; reading "between" as a comparison there turns a
correlation into a time series. So `WEAK` is offered separately and read only
by callers that are already choosing between two comparable methodologies.

What it does not do
-------------------
It reads whether a change was asked for. It does not read the DIRECTION of the
change — that is `semantics.DIRECTIONS`, and direction is a property of the
measure rather than of the word — and it does not decide which two periods the
comparison runs between, which is `periods`.
"""

from __future__ import annotations

import re

MOVEMENT_VERSION = "1.0.0"

#: Words that assert a change in a measure between two dates.
#:
#: "moved" and "movement" are the same claim; so are "shifted" and "shift". The
#: bare imperatives are deliberately absent: "move this to the project" and
#: "drop the chart" are things done to a result, not things a measure did, and
#: a 12-month moving average is a single figure at one date.
CHANGE = (
    r"chang\w*|mov(?:ed|es|ement|ements)|shift(?:ed|s)"
    # "How did it move?" — bare, and intransitive. Admitted only at the end of
    # the sentence, which is what separates it from the imperative: a measure
    # that moved has nothing after the verb, and "move this to the Contracting
    # sector" has its object there.
    r"|move(?=\s*[?.!]*\s*$)"
    r"|increas\w*|decreas\w*|ris(?:e|es|en|ing)|rose|risen"
    r"|fell|fall(?:s|en|ing)|dropped|grew|grow(?:th|n)"
    r"|declin\w*|worsen\w*|improv\w*|deteriorat\w*"
    r"|downgrad\w*|upgrad\w*|trend\w*"
    r"|compar\w*|versus|vs"
)

#: Phrases that name two dates without naming a change. "Over the latest year"
#: is a window, and a measure asked for over a window is asked for at both ends
#: of it.
SPAN = (
    r"over the (?:latest|last|past)"
    r"|year[- ]on[- ]year|year[- ]over[- ]year"
    r"|quarter[- ]on[- ]quarter|qoq|yoy"
)

#: Words that name a comparison only where one is already in view. Read by a
#: caller choosing between two methodologies it has already matched — never by
#: a caller deciding, from nothing, whether a question is about a change.
WEAK = r"since|between|compared|against"

#: "moved to Stage 3" is a MIGRATION between named states, and it is not this
#: module's question. A measure movement asks how big a number got; a migration
#: asks which accounts crossed a boundary, and the two have different answers,
#: different grains and different governed methodologies.
#:
#: Read as a measure movement, "which of these moved to Stage 3?" came back as
#: "Stage migration was unchanged from 1.00 to 1.00 between Q2 2025 and Q2 2026"
#: — the stage column averaged across two dates and presented as a finding.
#: That is worse than not reading the movement at all, so the destination
#: phrasing is masked out before the vocabulary is searched.
#:
#: "to" and "into" only. "ECL moved from 5,248 to 5,313" names the endpoints of
#: a measure movement with the same preposition, and masking that would lose a
#: reading the module exists to make.
_MIGRATION = re.compile(
    r"\b(?:mov(?:ed|es|ement|ements)|shift(?:ed|s)|transition\w*)\s+"
    r"(?:in)?to\s+(?!date\b)",
    re.IGNORECASE)


def without_migration(text: str) -> str:
    """The sentence with migration phrasing blanked, not removed.

    Blanked so the rest still reads: "PD rose and three names moved to stage 3"
    keeps its "rose" and stays a movement question.
    """
    return _MIGRATION.sub(lambda m: " " * len(m.group(0)), text)


_CHANGE = re.compile(rf"\b(?:{CHANGE})\b|\b(?:{SPAN})", re.IGNORECASE)
_WITH_WEAK = re.compile(
    rf"\b(?:{CHANGE})\b|\b(?:{SPAN})|\b(?:{WEAK})\b", re.IGNORECASE)

#: A change question whose whole content is the change — "What moved?", "What
#: has changed?". The measure is not missing from it; the measure is the one
#: the conversation is already about, and asking which figure to measure is
#: asking the reader to repeat themselves.
#:
#: Anchored at both ends on purpose. "What changed in Real Estate?" names a
#: population of its own and is a fresh request; only a sentence with nothing
#: else in it can safely borrow the previous turn's subject.
SUBJECTLESS = re.compile(
    r"^\s*(?:(?:and|so|ok|okay|right)[,.]?\s+)*"
    r"what(?:'s|’s|\s+has|\s+have|\s+had)?\s+"
    r"(?:chang\w*|mov(?:ed|es)|shift(?:ed|s))"
    r"\s*[?.!]*\s*$",
    re.IGNORECASE)


def asks_for_change(text: str, *, weak: bool = False) -> bool:
    """Whether this question is about a change rather than about a level.

    `weak=True` additionally reads the comparison words that are ambiguous on
    their own. Only for a caller that is choosing between two methodologies it
    has already matched by name.
    """
    said = str(text or "")
    if not said:
        return False
    said = without_migration(said)
    return bool((_WITH_WEAK if weak else _CHANGE).search(said))


def subjectless(text: str) -> bool:
    """Whether the whole question is a change question with no subject."""
    return bool(SUBJECTLESS.match(str(text or "")))


__all__ = ["CHANGE", "MOVEMENT_VERSION", "SPAN", "SUBJECTLESS", "WEAK",
           "asks_for_change", "subjectless", "without_migration"]
