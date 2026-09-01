"""
Whether an interpretation is any good, decided by arithmetic.

Why a rubric rather than a reviewer
-----------------------------------
"Unimpressive, generic, indirect or incomplete" is a fair description of prose
and a useless test result. Somebody has to be able to run this on every answer
and get the same verdict twice, which rules out asking a model whether the
writing is good — a grader that disagrees with itself cannot say whether a
change improved anything.

So every criterion here is decided from the text and the result together, with
no judgement and no second model. A live reviewer may be added later for style;
it may never be the thing that decides correctness, because a model marking
another model's homework is a closed loop with no ground in it.

The ten criteria
----------------
Four are safety: no figure the result does not carry, no name it does not
contain, no binary debris, no asserted cause. Those are pass-or-the-answer-is-
withheld.

Six are quality: does the first sentence answer the question, is it short
enough to read, does it name the largest contributor, does it name the rows
that do not fit, does it say what limits the conclusion, and does it leave
somewhere to go next. Those are scored and reported.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Safety — a failure here means the answer should not have been shown as it is.
GROUNDED_FIGURES = "grounded_figures"
GROUNDED_ENTITIES = "grounded_entities"
NO_DEBRIS = "no_debris"
NON_CAUSAL = "non_causal"

# Quality — a failure here means the answer is worse than it could be.
DIRECTNESS = "directness"
CONCISION = "concision"
DRIVERS = "drivers"
EXCEPTIONS = "exceptions"
LIMITATION = "limitation"
NEXT_STEP = "next_step"

SAFETY = (GROUNDED_FIGURES, GROUNDED_ENTITIES, NO_DEBRIS, NON_CAUSAL)
QUALITY = (DIRECTNESS, CONCISION, DRIVERS, EXCEPTIONS, LIMITATION, NEXT_STEP)

#: A first sentence longer than this is a paragraph pretending to be an answer.
MAX_DIRECT_WORDS = 45

#: And a reading longer than this is a report. The figures are directly beneath
#: it; the reading is the thing you read INSTEAD of the table.
MAX_READING_WORDS = 120


@dataclass
class Score:
    """One criterion, and why it went the way it did."""

    criterion: str
    passed: bool
    detail: str = ""
    #: False where the criterion does not apply to this answer — a result with
    #: three rows has no exceptions to name.
    applicable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"criterion": self.criterion, "passed": self.passed,
                "detail": self.detail, "applicable": self.applicable}


@dataclass
class Assessment:
    """How one answer scored, and on what."""

    scores: list[Score] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return all(s.passed for s in self.scores
                   if s.criterion in SAFETY and s.applicable)

    @property
    def failures(self) -> list[Score]:
        return [s for s in self.scores if s.applicable and not s.passed]

    @property
    def quality(self) -> float:
        """The share of applicable quality criteria that were met."""
        relevant = [s for s in self.scores
                    if s.criterion in QUALITY and s.applicable]
        if not relevant:
            return 1.0
        return round(sum(1 for s in relevant if s.passed) / len(relevant), 3)

    def to_dict(self) -> dict[str, Any]:
        return {"safe": self.safe, "quality": self.quality,
                "scores": [s.to_dict() for s in self.scores],
                "failed": [s.criterion for s in self.failures]}


_WORD = re.compile(r"[A-Za-z0-9%.,'-]+")
_FIRST_SENTENCE = re.compile(r"^.*?[.!?](?:\s|$)", re.S)


def assess(narrative: Any, runtime: Any = None, build: Any = None, *,
           question: str = "", suggestions: list[str] | None = None,
           association: dict[str, Any] | None = None,
           values: dict[str, Any] | None = None) -> Assessment:
    """Score one answer against the ten criteria.

    `values` is the step's headline figures — totals, shares, coefficients, the
    figures the analyst pass derived. They are part of the result and a reading
    is entitled to quote them; omitting them here reported every derived
    percentage as ungrounded, which is the check calling correct prose a
    defect.
    """
    try:
        return _assess(narrative, runtime, build, question=question,
                       suggestions=suggestions or [],
                       association=association or {},
                       values=values or {})
    except Exception as e:  # noqa: BLE001 - a score must not lose an answer
        logger.warning("The rubric could not be applied: %s", e)
        return Assessment()


def _assess(narrative: Any, runtime: Any, build: Any, *, question: str,
            suggestions: list[str], association: dict[str, Any],
            values: dict[str, Any]) -> Assessment:
    from backend.orchestration import assembly, evidence, figures

    direct = str(getattr(narrative, "direct_answer", "") or "")
    reading = str(getattr(narrative, "interpretation", "") or "")
    findings = [str(getattr(f, "text", "")) for f in
                (getattr(narrative, "findings", None) or [])]
    caveats = [str(c) for c in (getattr(narrative, "caveats", None) or [])]
    everything = " ".join(x for x in [direct, reading, *findings] if x)

    out: list[Score] = []

    # ---- safety --------------------------------------------------------
    allowed = assembly.grounded_values(
        runtime, values, asked=question) if runtime is not None else set()
    loose = assembly.ungrounded(everything, allowed) if allowed else []
    out.append(Score(GROUNDED_FIGURES, not loose,
                     f"figures the result does not carry: {loose[:4]}" if loose
                     else "every figure appears in the result",
                     applicable=runtime is not None))

    package = (evidence.build(runtime, build) if runtime is not None
               else evidence.Package())
    grounding = evidence.check(everything, package, allow_causal=True)
    out.append(Score(GROUNDED_ENTITIES, not grounding.unknown_entities,
                     f"names not in the result: {grounding.unknown_entities[:3]}"
                     if grounding.unknown_entities else
                     "every name appears in the result",
                     applicable=bool(package.entities)))

    debris = [t for t in (direct, reading, *findings, *caveats)
              if figures.has_debris(t)]
    out.append(Score(NO_DEBRIS, not debris,
                     "binary floating-point debris in the prose" if debris
                     else "no figure written to sixteen decimal places"))

    # An association answer discusses relationships and carries the caveat that
    # says they are not causes; anything else may not assert one at all.
    causal = evidence.check(everything, package).causal_claims
    excused = bool(association.get("caveat"))
    out.append(Score(NON_CAUSAL, not causal or excused,
                     f"asserts a cause: {causal[:1]}" if causal and not excused
                     else "no cause is asserted"))

    # ---- quality -------------------------------------------------------
    first = (_FIRST_SENTENCE.match(direct) or [None])
    opening = (first.group(0) if hasattr(first, "group") else direct).strip()
    words = len(_WORD.findall(opening))
    answers = bool(re.search(r"\d", opening)) or bool(
        re.search(r"\bnone\b|\bno\b|\bnothing\b|\bcannot\b", opening, re.I))
    out.append(Score(DIRECTNESS, bool(opening) and answers and words <= MAX_DIRECT_WORDS,
                     f"first sentence is {words} words and "
                     f"{'carries' if answers else 'carries no'} an answer"))

    reading_words = len(_WORD.findall(reading))
    out.append(Score(CONCISION, reading_words <= MAX_READING_WORDS,
                     f"the reading is {reading_words} words",
                     applicable=bool(reading)))

    observations = list(getattr(build, "observations", None) or [])
    out.append(_names(observations, everything, "driver", DRIVERS,
                      ("leader", "top")))
    out.append(_names(observations, everything, "exception", EXCEPTIONS,
                      ("exceptions",)))

    limits = [o for o in observations
              if str(getattr(o, "kind", "")) == "limitation"]
    out.append(Score(LIMITATION,
                     any(o.text in everything or o.text in " ".join(caveats)
                         for o in limits),
                     "the limitation the result carries is stated",
                     applicable=bool(limits)))

    out.append(Score(NEXT_STEP, bool(suggestions),
                     f"{len(suggestions)} suggestions offered"))
    return Assessment(scores=out)


def _names(observations: list[Any], text: str, kind: str, criterion: str,
           keys: tuple[str, ...]) -> Score:
    """Whether the reading names what the analyst pass found."""
    found = [o for o in observations if str(getattr(o, "kind", "")) == kind]
    if not found:
        return Score(criterion, True, f"no {kind} to name", applicable=False)

    wanted: list[str] = []
    for observation in found:
        facts = getattr(observation, "facts", None) or {}
        for key in keys:
            value = facts.get(key)
            if isinstance(value, str) and value.strip():
                wanted.append(value.strip())
            elif isinstance(value, list):
                wanted.extend(str(v) for v in value if str(v).strip())
    if not wanted:
        return Score(criterion, True, f"the {kind} has no name",
                     applicable=False)

    named = [w for w in wanted if w.lower() in text.lower()]
    return Score(criterion, bool(named),
                 f"names {named[0]}" if named
                 else f"does not name {wanted[0]}, which the result singles out")


__all__ = ["CONCISION", "DIRECTNESS", "DRIVERS", "EXCEPTIONS",
           "GROUNDED_ENTITIES", "GROUNDED_FIGURES", "LIMITATION",
           "MAX_DIRECT_WORDS", "MAX_READING_WORDS", "NEXT_STEP", "NON_CAUSAL",
           "NO_DEBRIS", "QUALITY", "SAFETY", "Assessment", "Score", "assess"]
