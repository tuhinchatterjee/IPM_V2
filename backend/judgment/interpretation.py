"""
The analyst interpretation contract and the pipeline that fills it.
§78, §79, §80.

    "Every section maps to facts/observations.
     Do not force a section when evidence is insufficient; state insufficient
     evidence."

Nine sections, and the second sentence is the one that makes them honest. A
contract with nine required sections and no way to say "not enough evidence"
produces nine sections every time, three of which are invented. So a section
can be PRESENT, INSUFFICIENT or NOT_APPLICABLE, and the difference between the
last two matters: INSUFFICIENT means we looked and could not tell,
NOT_APPLICABLE means the question does not have that shape.

What the narrative model receives, and what it does not
--------------------------------------------------------
§79 lists it: the question, objective coverage, approved facts, approved
observations, limitations, the answer contract, a length cap and a locale. Not
the result tables — "unless necessary", and the necessary case is rarer than
it feels. A model given a thousand rows will find a pattern in them, and the
pattern will not have been computed by anything.

`pack()` builds exactly that, and it builds it from OBSERVATIONS rather than
from facts directly. The observations are already ordered, already prioritised,
already carry their materiality and their evidence-based confidence. Handing a
model the facts instead would ask it to redo the work the engines did, and it
would do it differently.

The grounding check
-------------------
Every sentence in the narrative has to trace to a cited observation. §79 puts
the check after the model and before display, which is the only place it can
be: a check inside the prompt is a request, and a request is not a control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.judgment import evidence as ev
from backend.judgment import materiality as mt
from backend.judgment import observations as ob

INTERPRETATION_VERSION = "1.0.0"

# --------------------------------------------------------- §78's nine sections
BOTTOM_LINE = "BOTTOM_LINE"
MATERIALITY = "MATERIALITY"
DRIVERS = "DRIVERS"
BREADTH = "BREADTH_CONCENTRATION"
PERSISTENCE = "PERSISTENCE_NOISE"
EXCEPTIONS = "EXCEPTIONS_CONTRADICTIONS"
CREDIT_RISK = "CREDIT_RISK_INTERPRETATION"
LIMITATIONS = "LIMITATIONS"
NEXT_BEST = "NEXT_BEST_ANALYSES"

SECTIONS: tuple[str, ...] = (BOTTOM_LINE, MATERIALITY, DRIVERS, BREADTH,
                             PERSISTENCE, EXCEPTIONS, CREDIT_RISK,
                             LIMITATIONS, NEXT_BEST)

#: What each section is for, in the words the contract would be explained in.
PURPOSE: dict[str, str] = {
    BOTTOM_LINE: "The direct answer to what was asked.",
    MATERIALITY: "How large this is and why it matters.",
    DRIVERS: "What explains it.",
    BREADTH: "How the movement is distributed.",
    PERSISTENCE: "Whether it is sustained.",
    EXCEPTIONS: "What does not fit.",
    CREDIT_RISK: "Why the pattern is economically plausible, in governed "
                 "terms.",
    LIMITATIONS: "What is missing or not proven.",
    NEXT_BEST: "The most useful follow-ups.",
}

#: Which observation types feed each section. A section with no observations of
#: its kinds is INSUFFICIENT, and that is computed rather than judged.
FEEDS: dict[str, tuple[str, ...]] = {
    BOTTOM_LINE: (ob.CHANGE, ob.LEVEL, ob.RANK, ob.MIGRATION, ob.NO_MATCH),
    MATERIALITY: (ob.CHANGE, ob.LEVEL, ob.THRESHOLD_BREACH),
    DRIVERS: (ob.DRIVER, ob.OFFSET),
    BREADTH: (ob.BREADTH, ob.CONCENTRATION),
    PERSISTENCE: (ob.PERSISTENCE, ob.TREND),
    EXCEPTIONS: (ob.EXCEPTION, ob.CONTRADICTION, ob.OFFSET),
    CREDIT_RISK: (ob.CHANGE, ob.MIGRATION, ob.ASSOCIATION, ob.DRIVER),
    LIMITATIONS: (ob.LIMITATION, ob.UNCERTAINTY, ob.UNAVAILABLE),
    NEXT_BEST: (ob.NEXT_STEP,),
}

#: Sections that must always be attempted. BOTTOM_LINE is not in this set and
#: not optional either — it is handled separately, because there is no sentence
#: that stands in for a missing answer and "insufficient evidence for a bottom
#: line" is an abstention, not a section.
ALWAYS: frozenset[str] = frozenset({MATERIALITY, LIMITATIONS})

# ------------------------------------------------------------ section state
PRESENT = "PRESENT"
#: We looked and could not tell.
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
#: The question does not have this shape. A single-period level question has
#: no persistence section and saying "insufficient evidence" about it would be
#: reporting a gap that is not one.
NOT_APPLICABLE = "NOT_APPLICABLE"

STATES: tuple[str, ...] = (PRESENT, INSUFFICIENT, NOT_APPLICABLE)


@dataclass
class Section:
    """One of §78's nine, and what backs it."""

    id: str
    state: str = INSUFFICIENT
    #: The observations this section may draw on. §78: every section maps to
    #: facts or observations.
    observation_ids: list[str] = field(default_factory=list)
    #: Why it is not PRESENT.
    note: str = ""

    @property
    def purpose(self) -> str:
        return PURPOSE.get(self.id, "")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "purpose": self.purpose, "state": self.state,
                "observation_ids": list(self.observation_ids),
                "note": self.note}


@dataclass
class Contract:
    """§78's contract for one answer."""

    sections: list[Section] = field(default_factory=list)
    #: The answer may not be shown at all — no bottom line is available.
    abstain: bool = False
    abstain_reason: str = ""

    def get(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    @property
    def present(self) -> list[Section]:
        return [s for s in self.sections if s.state == PRESENT]

    @property
    def insufficient(self) -> list[Section]:
        return [s for s in self.sections if s.state == INSUFFICIENT]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": INTERPRETATION_VERSION,
            "sections": [s.to_dict() for s in self.sections],
            "present": [s.id for s in self.present],
            "insufficient": [s.id for s in self.insufficient],
            "abstain": self.abstain,
            "abstain_reason": self.abstain_reason,
        }


def build(found: ob.Set, *, periods: int = 1,
          question_is_open: bool = True) -> Contract:
    """The contract, from the observations that exist.

    Computed rather than judged. A section is PRESENT when observations of its
    kinds exist, NOT_APPLICABLE when the question cannot have that shape, and
    INSUFFICIENT otherwise — and the caller cannot talk it into PRESENT,
    because the section's content is the observation ids and there are none.
    """
    contract = Contract()
    available = {o.type for o in found.ordered()}

    for section_id in SECTIONS:
        kinds = FEEDS[section_id]
        backing = [o.observation_id for o in found.ordered()
                   if o.type in kinds]
        section = Section(id=section_id, observation_ids=backing)

        if backing:
            section.state = PRESENT
        elif section_id == PERSISTENCE and periods < 2:
            section.state = NOT_APPLICABLE
            section.note = ("a single period cannot show whether anything "
                            "persists")
        elif section_id == BREADTH and not question_is_open:
            section.state = NOT_APPLICABLE
            section.note = ("the question asks for one figure, which has no "
                            "distribution")
        elif section_id == NEXT_BEST and not question_is_open:
            section.state = NOT_APPLICABLE
            section.note = "a direct question does not need a follow-up list"
        else:
            section.state = INSUFFICIENT
            section.note = (
                f"no {', '.join(k.lower() for k in kinds)} observation was "
                "produced")
        contract.sections.append(section)

    # BOTTOM LINE is handled apart from the others because there is no
    # sentence that stands in for a missing answer. A contract with no bottom
    # line is an abstention, and calling it "insufficient evidence for the
    # bottom line" would let an answer be shown with a hole where the answer
    # goes.
    bottom = contract.get(BOTTOM_LINE)
    if bottom and bottom.state != PRESENT:
        contract.abstain = True
        contract.abstain_reason = (
            "No observation answers the question directly, so there is no "
            "bottom line to state. CreditProbe says what it could not "
            "establish rather than showing the surrounding analysis as though "
            "it were an answer.")
    _ = available
    return contract


# ---------------------------------------------------------------------------
# §79 — the interpretation pack
# ---------------------------------------------------------------------------

#: What §79 says the narrative model receives. A whitelist, and the absence of
#: "result rows" from it is the point.
PACK_FIELDS: tuple[str, ...] = (
    "question", "objective_coverage", "facts", "observations", "limitations",
    "answer_contract", "max_words", "locale",
)

#: Default length cap. A cap rather than a target: an answer that could be said
#: in forty words should be forty words, and a target makes it three hundred.
MAX_WORDS = 320


@dataclass
class Pack:
    """§79's interpretation pack — everything the narrative model gets."""

    question: str = ""
    objective_coverage: dict[str, Any] = field(default_factory=dict)
    facts: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    answer_contract: dict[str, Any] = field(default_factory=dict)
    max_words: int = MAX_WORDS
    locale: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in PACK_FIELDS}


def pack(question: str, found: ob.Set, graph: ev.Graph, contract: Contract, *,
         coverage: dict[str, Any] | None = None, locale: str = "en",
         max_words: int = MAX_WORDS,
         result_rows: list[dict[str, Any]] | None = None) -> Pack:
    """What the narrative model receives. §79.

    Built from OBSERVATIONS, not from facts directly. The observations are
    already ordered, prioritised, and carry their materiality and their
    evidence-based confidence; handing a model the facts instead asks it to
    redo the work the engines did, and it will do it differently.

    `result_rows` exists and is deliberately awkward to use: §79 permits raw
    tables "unless necessary", and a model given a thousand rows will find a
    pattern in them that nothing computed.
    """
    shown = found.ordered()
    cited = {f for o in shown for f in o.fact_ids}

    built = Pack(
        question=question,
        objective_coverage=dict(coverage or {}),
        facts=[graph.get(f).to_dict() for f in sorted(cited)
               if f in graph.facts],
        observations=[o.to_dict() for o in shown],
        limitations=[o.render() for o in found.by_type(ob.LIMITATION)],
        answer_contract=contract.to_dict(),
        max_words=int(max_words), locale=locale)

    if result_rows:
        # Recorded on the pack rather than folded into `facts`, so a Trace can
        # show that raw rows were included and somebody can ask why.
        built.answer_contract = {**built.answer_contract,
                                 "raw_rows_included": len(result_rows)}
    return built


# ---------------------------------------------------------------------------
# The grounding check
# ---------------------------------------------------------------------------

#: Numbers a narrative may use without citing anything: small integers that are
#: almost always counts of things the reader can see ("all three sectors"), and
#: years. Everything else has to trace to a fact.
#: A figure preceded by a letter is part of a label — Q2, H1, FY24, IFRS 9 —
#: not a claim. Without the word-boundary lookbehind, "between Q1 and Q2."
#: reported "2." as an ungrounded figure, which is the kind of false positive
#: that gets a grounding check switched off.
#:
#: The decimal part requires a digit AFTER the point for the same reason: a
#: sentence ending "…and Q2 2026." otherwise yields "2026.", which no longer
#: looks like a year to the harmless test below and is reported as an
#: uncited figure. Every honest sentence ends in a full stop, so that false
#: positive would have fired on almost every narrative there is.
_FIGURE = re.compile(r"(?<![\w.,])\d[\d,]*(?:\.\d+)?%?")
_HARMLESS = re.compile(r"^(?:19|20)\d{2}$|^[0-9]$|^10$")


@dataclass
class Grounding:
    """Whether every claim in a narrative traces to something computed."""

    ok: bool = True
    #: Figures in the prose with no matching fact.
    ungrounded: list[str] = field(default_factory=list)
    #: Observations the narrative was given and did not use. Not a failure —
    #: an answer is allowed to be shorter than its evidence — but worth
    #: seeing, because a narrative that ignores the contradiction it was
    #: handed is a narrative with a problem.
    unused: list[str] = field(default_factory=list)
    over_length: bool = False
    words: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "ungrounded": list(self.ungrounded),
                "unused": list(self.unused), "over_length": self.over_length,
                "words": self.words}


def _figures(text: str) -> list[str]:
    return [f for f in _FIGURE.findall(text or "")
            if not _HARMLESS.match(f.rstrip("%").replace(",", ""))]


def check(narrative: str, built: Pack) -> Grounding:
    """§79's grounding check, after the model and before display.

    The only place it can be. A check inside the prompt is a request, and a
    request is not a control.

    Compares the figures in the prose against the values the pack carried. A
    figure the pack does not contain was either computed by the model — which
    it must not do — or copied wrongly, and both are the same defect from the
    reader's side.
    """
    result = Grounding()
    words = len((narrative or "").split())
    result.words = words
    result.over_length = words > built.max_words

    allowed: set[str] = set()
    for fact in built.facts:
        for key in ("value", "opening_value", "closing_value", "change",
                    "change_pct", "change_pp"):
            value = fact.get(key)
            if value is None:
                continue
            allowed.add(_normalise(value))
    for observation in built.observations:
        for value in (observation.get("slots") or {}).values():
            allowed.add(_normalise(value))

    for figure in _figures(narrative):
        if _normalise(figure) not in allowed:
            result.ungrounded.append(figure)

    # An observation counts as used when something distinctive from it
    # appears in the prose. Matching on observation ids would be neater and
    # wrong: narratives do not cite ids, and a check that required them would
    # report every answer as ignoring all its evidence.
    lowered = (narrative or "").lower()
    result.unused = [
        o["observation_id"] for o in built.observations
        if o.get("materiality") in (mt.HIGH, mt.CRITICAL)
        and not _mentioned(o, lowered)]

    result.ok = not result.ungrounded and not result.over_length
    return result


#: Observation types that are RELATIONSHIPS between two things. For these,
#: mentioning one side is not using the observation — it is the specific
#: failure of reporting only the reassuring direction, which is what a
#: contradiction observation exists to prevent.
_BOTH_SIDES: frozenset[str] = frozenset({ob.CONTRADICTION, ob.OFFSET,
                                          ob.ASSOCIATION})


def _mentioned(observation: dict[str, Any], lowered: str) -> bool:
    """Whether the prose used this observation.

    "Used" is deliberately loose for most types — a narrative may paraphrase —
    and deliberately strict for the relationship types, where using half of it
    is the failure.
    """
    values = [str(v).strip() for v in
              (observation.get("slots") or {}).values()]
    figures = {_normalise(f) for f in _figures(lowered)}

    def hit(text: str) -> bool:
        return ((len(text) >= 3 and text.lower() in lowered)
                or _normalise(text) in figures)

    if observation.get("type") in _BOTH_SIDES:
        distinctive = [v for v in values if len(v) >= 3]
        return bool(distinctive) and all(hit(v) for v in distinctive)
    return any(hit(v) for v in values)


def _normalise(value: Any) -> str:
    """A figure as a comparable string.

    Compares by the digits, so "40", "40.0", "+40" and "40%" all match a fact
    whose change is 40. Deliberately loose: the check is for figures that
    appeared from nowhere, and a stricter comparison would fail on formatting
    and teach everybody to disable it.
    """
    text = str(value).strip().replace(",", "").replace("%", "")
    text = text.lstrip("+")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return str(value).strip().lower()
    if number == int(number):
        return str(int(number))
    return f"{number:.6g}"


__all__ = ["ALWAYS", "BOTTOM_LINE", "BREADTH", "CREDIT_RISK", "Contract",
           "DRIVERS", "EXCEPTIONS", "FEEDS", "Grounding", "INSUFFICIENT",
           "INTERPRETATION_VERSION", "LIMITATIONS", "MATERIALITY",
           "MAX_WORDS", "NEXT_BEST", "NOT_APPLICABLE", "PACK_FIELDS",
           "PERSISTENCE", "PRESENT", "PURPOSE", "Pack", "SECTIONS",
           "STATES", "Section", "build", "check", "pack"]
