"""
Paraphrases, typos and conversational variants of a curriculum case.

Why generate rather than write
-------------------------------
A curriculum written by one person tests one person's phrasing. Real users
abbreviate, mistype, hedge, and put the verb in a different place — and the
failures that reach a demo are almost never the sentence somebody wrote down.
Generating variants from a reviewed case keeps the specification (what a
correct answer must do) while varying the only thing that should not matter
(how it was asked).

Deterministic
-------------
Every variant is produced by a rule, from a seed derived from the case id. The
same curriculum produces the same variants on every machine, which is what
makes a score comparable between two runs of the factory. Nothing here uses a
model: a model asked for paraphrases produces its own distribution, and tuning
a prompt against a model's idea of how people talk optimises for the wrong
thing.

What is NOT generated
---------------------
The expectation. A variant inherits its case's specification unchanged — if a
paraphrase would make the correct answer different, it is not a paraphrase, and
the rules here are deliberately conservative enough that this cannot happen.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, replace
from typing import Any

from intelligence_factory.curriculum import Case

#: How many variants each case produces. Enough to matter statistically,
#: bounded so a development evaluation stays affordable.
VARIANTS_PER_CASE = 4


@dataclass(frozen=True)
class Variant:
    """One rephrasing of a case, and what changed."""

    case: Case
    kind: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.case.id, "kind": self.kind, "detail": self.detail,
                "questions": [t.question for t in self.case.turns]}


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

#: Substitutions a credit officer would make without changing the question.
_SYNONYMS: tuple[tuple[str, str], ...] = (
    (r"\bShow me\b", "Give me"),
    (r"\bShow\b", "List"),
    (r"\bWhich\b", "What"),
    (r"\bcustomers\b", "borrowers"),
    (r"\bexposure at default\b", "EAD"),
    (r"\bexpected credit loss\b", "ECL"),
    (r"\bthe latest quarter\b", "the most recent quarter"),
    (r"\bthe latest year\b", "the past year"),
    (r"\bincrease in\b", "rise in"),
    (r"\bworsening\b", "deteriorating"),
    (r"\blargest\b", "biggest"),
    (r"\bfields\b", "columns"),
)

#: Openings people put in front of a question. They carry no meaning and they
#: change the sentence a reader has to parse, which is exactly the point.
_PREFIXES = ("Can you ", "Please ", "I need to know ", "Quick one — ",
             "Could you ")

#: How people soften or trail off. Same reason.
_SUFFIXES = (" please", " if you can", " — thanks", "?")

#: Keys that are adjacent on a QWERTY keyboard, for a realistic typo rather
#: than a random character.
_ADJACENT = {"a": "s", "e": "r", "i": "o", "o": "p", "t": "y", "n": "m",
             "s": "d", "r": "t", "c": "v", "l": "k", "d": "f", "u": "i"}


def _synonymise(text: str, rng: random.Random) -> tuple[str, str]:
    applicable = [(pattern, word) for pattern, word in _SYNONYMS
                  if re.search(pattern, text)]
    if not applicable:
        return text, ""
    pattern, word = rng.choice(applicable)
    return re.sub(pattern, word, text, count=1), f"{pattern} → {word}"


def _politeness(text: str, rng: random.Random) -> tuple[str, str]:
    stripped = text.rstrip("?. ")
    if rng.random() < 0.5:
        prefix = rng.choice(_PREFIXES)
        lowered = stripped[:1].lower() + stripped[1:]
        return f"{prefix}{lowered}?", f"prefixed with {prefix.strip()!r}"
    suffix = rng.choice(_SUFFIXES)
    return f"{stripped}{suffix}", f"suffixed with {suffix.strip()!r}"


def _typo(text: str, rng: random.Random) -> tuple[str, str]:
    """One adjacent-key slip in a word long enough to survive it.

    One, not several. A sentence with four typos tests whether a model can
    decode noise; a sentence with one tests whether a real mistype loses an
    answer, which is the thing that happens.
    """
    words = [(i, w) for i, w in enumerate(text.split()) if len(w) > 5]
    if not words:
        return text, ""
    index, word = rng.choice(words)
    position = rng.randrange(1, len(word) - 1)
    letter = word[position].lower()
    if letter not in _ADJACENT:
        return text, ""
    mistyped = word[:position] + _ADJACENT[letter] + word[position + 1:]
    parts = text.split()
    parts[index] = mistyped
    return " ".join(parts), f"{word!r} mistyped as {mistyped!r}"


def _terse(text: str, rng: random.Random) -> tuple[str, str]:
    """The way somebody types when they are in a hurry."""
    del rng
    stripped = re.sub(
        r"^(?:Can you |Could you |Please |What is |Which |Show me |Show |"
        r"List |Give me )", "", text, flags=re.I).rstrip("?. ")
    if stripped == text.rstrip("?. ") or len(stripped) < 8:
        return text, ""
    return stripped, "reduced to the noun phrase"


_RULES = (("synonym", _synonymise), ("politeness", _politeness),
          ("typo", _typo), ("terse", _terse))


# ---------------------------------------------------------------------------
# Producing them
# ---------------------------------------------------------------------------


def variants(case: Case, *, count: int = VARIANTS_PER_CASE) -> list[Variant]:
    """`count` rephrasings of one case, deterministically.

    Only the FIRST turn is varied. A follow-up's phrasing is what the referent
    machinery is being tested on, and rewording it would change what is being
    measured rather than how it was asked.
    """
    rng = random.Random(f"{case.id}:{len(case.turns)}")
    out: list[Variant] = []
    seen = {case.turns[0].question} if case.turns else set()

    for index in range(count):
        kind, rule = _RULES[index % len(_RULES)]
        if not case.turns:
            break
        rewritten, detail = rule(case.turns[0].question, rng)
        if not detail or rewritten in seen:
            continue
        seen.add(rewritten)
        turns = [replace(case.turns[0], question=rewritten), *case.turns[1:]]
        out.append(Variant(
            case=Case(id=f"{case.id}-v{index + 1}", family=case.family,
                      title=f"{case.title} ({kind})", turns=turns),
            kind=kind, detail=detail))
    return out


def expand(cases: list[Case], *, count: int = VARIANTS_PER_CASE) -> list[Case]:
    """Every case, plus its variants, as one list to evaluate."""
    out: list[Case] = []
    for case in cases:
        out.append(case)
        out.extend(v.case for v in variants(case, count=count))
    return out


def describe(cases: list[Case], *, count: int = VARIANTS_PER_CASE
             ) -> dict[str, Any]:
    """What generation would produce, for the release manifest."""
    produced = expand(cases, count=count)
    return {"cases": len(cases), "with_variants": len(produced),
            "variants_per_case": count,
            "turns": sum(len(c.turns) for c in produced)}


__all__ = ["VARIANTS_PER_CASE", "Variant", "describe", "expand", "variants"]
