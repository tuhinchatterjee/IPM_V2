"""
The deterministic Observation Engine. §77.

    "Do not generate free prose at this stage."

An Observation is a structured claim: a type, the facts behind it, a
materiality band, a priority, and a TEMPLATE for how it could be said. Not the
sentence — the sentence is the interpretation layer's job, and the separation
is what makes the claim checkable. A template with named slots can be verified
against the facts it cites; a paragraph cannot.

Why the sentence is a template rather than a string
----------------------------------------------------
Two reasons, and the second is the one that matters. The first is mechanical: a
template renders in any language and any register, so §49's Arabic work later
does not have to re-derive the observations. The second is that a template
cannot say more than its slots. "ECL rose {change} in {entity}" can only ever
assert a change and an entity, both of which are facts. A model handed the same
inputs will write "ECL rose sharply in Contracting, driven by deterioration in
the construction sector" — and three of those five claims have no fact behind
them.

Priority is not materiality
----------------------------
Materiality is how much a finding matters. Priority is where it goes in the
answer. They diverge constantly: a LIMITATION is rarely material and frequently
belongs near the top, because a reader who does not know the data is incomplete
will misread everything under it. So priority is derived from type and
materiality together, and the ordering is stated.

Confidence comes from evidence, never from a model
---------------------------------------------------
§70 says it and §77 repeats it. `confidence_from_evidence` is computed from how
many of the cited facts are validated, how complete they are, and whether the
observation's own type needs corroboration. A model's self-reported confidence
is not an input and there is nowhere to put one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.judgment import evidence as ev
from backend.judgment import materiality as mt

OBSERVATION_VERSION = "1.0.0"

# ------------------------------------------------------- §77's nineteen types
LEVEL = "LEVEL"
CHANGE = "CHANGE"
RANK = "RANK"
TREND = "TREND"
PERSISTENCE = "PERSISTENCE"
CONCENTRATION = "CONCENTRATION"
BREADTH = "BREADTH"
DRIVER = "DRIVER"
OFFSET = "OFFSET"
EXCEPTION = "EXCEPTION"
THRESHOLD_BREACH = "THRESHOLD_BREACH"
MIGRATION = "MIGRATION"
ASSOCIATION = "ASSOCIATION"
CONTRADICTION = "CONTRADICTION"
UNCERTAINTY = "UNCERTAINTY"
LIMITATION = "LIMITATION"
NEXT_STEP = "NEXT_STEP"
NO_MATCH = "NO_MATCH"
UNAVAILABLE = "UNAVAILABLE"

TYPES: tuple[str, ...] = (
    LEVEL, CHANGE, RANK, TREND, PERSISTENCE, CONCENTRATION, BREADTH, DRIVER,
    OFFSET, EXCEPTION, THRESHOLD_BREACH, MIGRATION, ASSOCIATION,
    CONTRADICTION, UNCERTAINTY, LIMITATION, NEXT_STEP, NO_MATCH, UNAVAILABLE,
)

#: Types that assert something about the data and therefore need facts. The
#: rest are about the ANALYSIS — what it could not do, what to do next — and a
#: fact requirement on those would force somebody to invent one.
NEEDS_FACTS: frozenset[str] = frozenset({
    LEVEL, CHANGE, RANK, TREND, PERSISTENCE, CONCENTRATION, BREADTH, DRIVER,
    OFFSET, EXCEPTION, THRESHOLD_BREACH, MIGRATION, ASSOCIATION,
    CONTRADICTION,
})

#: Types that need MORE than one fact by their nature. A contradiction between
#: one fact is not a contradiction; an offset needs both sides; an association
#: needs the two things being associated.
NEEDS_TWO: frozenset[str] = frozenset({CONTRADICTION, OFFSET, ASSOCIATION})

# --------------------------------------------------------------- status
STATED = "STATED"
#: Computed but held back — the presentability gate or a limitation suppressed
#: it. Kept rather than dropped: an observation that was found and withheld is
#: a different thing from one that was never found.
WITHHELD = "WITHHELD"
SUPERSEDED = "SUPERSEDED"

STATUSES: tuple[str, ...] = (STATED, WITHHELD, SUPERSEDED)

#: Where each type belongs in an answer, lowest first. Not materiality: a
#: LIMITATION is rarely material and frequently belongs near the top, because
#: a reader who does not know the data is incomplete will misread everything
#: under it.
ORDER: dict[str, int] = {
    CHANGE: 0, LEVEL: 1, DRIVER: 2, BREADTH: 3, CONCENTRATION: 3,
    PERSISTENCE: 4, TREND: 4, MIGRATION: 5, RANK: 6, THRESHOLD_BREACH: 7,
    EXCEPTION: 8, OFFSET: 9, CONTRADICTION: 10, ASSOCIATION: 11,
    UNCERTAINTY: 12, LIMITATION: 13, NO_MATCH: 14, UNAVAILABLE: 15,
    NEXT_STEP: 16,
}

#: Types that go near the top whatever their materiality, because reading the
#: rest without them produces a wrong impression.
ALWAYS_EARLY: frozenset[str] = frozenset({CONTRADICTION, LIMITATION,
                                          UNAVAILABLE})

_SLOT = re.compile(r"\{([a-z_]+)\}")


@dataclass
class Observation:
    """One structured claim. §77."""

    observation_id: str = ""
    type: str = LEVEL
    #: How it could be said, with named slots. Never a finished sentence: a
    #: template cannot assert more than its slots, and a paragraph can.
    statement_template: str = ""
    #: The values the slots take. Every one must trace to a cited fact or to a
    #: governed engine's output.
    slots: dict[str, Any] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    materiality: str = mt.IMMATERIAL
    priority: int = 99
    status: str = STATED
    #: Computed, never supplied. §70 and §77 both forbid model self-confidence.
    confidence_from_evidence: float = 0.0
    limitations: list[str] = field(default_factory=list)
    recommended_visual: str = ""
    recommended_follow_up: str = ""

    def slot_names(self) -> list[str]:
        return _SLOT.findall(self.statement_template or "")

    def render(self) -> str:
        """The template with its slots filled.

        Deliberately the only way an Observation becomes words, and
        deliberately incapable of adding any: a missing slot renders as a
        visible placeholder rather than being quietly dropped, because a
        sentence with a hole in it is better than a sentence that reads
        smoothly and means something else.
        """
        text = self.statement_template or ""
        for name in self.slot_names():
            value = self.slots.get(name)
            text = text.replace("{" + name + "}",
                                str(value) if value is not None
                                else f"[{name} unavailable]")
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id, "type": self.type,
            "statement_template": self.statement_template,
            "slots": dict(self.slots), "statement": self.render(),
            "fact_ids": list(self.fact_ids), "materiality": self.materiality,
            "priority": self.priority, "status": self.status,
            "confidence_from_evidence": round(self.confidence_from_evidence,
                                              3),
            "limitations": list(self.limitations),
            "recommended_visual": self.recommended_visual,
            "recommended_follow_up": self.recommended_follow_up,
        }


@dataclass(frozen=True)
class Problem:
    field: str
    detail: str

    def __str__(self) -> str:
        return f"{self.field}: {self.detail}"


def validate(observation: Observation, graph: ev.Graph) -> list[Problem]:
    """Whether this observation may be made at all.

    Checked against the graph rather than in isolation, because every question
    worth asking is about the relationship between the claim and its evidence.
    """
    problems: list[Problem] = []

    if observation.type not in TYPES:
        problems.append(Problem("type", f"{observation.type!r} is not an "
                                        "observation type"))
    if not observation.statement_template:
        problems.append(Problem("statement_template", "is required"))
    if observation.status not in STATUSES:
        problems.append(Problem("status", f"{observation.status!r} is not a "
                                          "status"))

    if observation.type in NEEDS_FACTS and not observation.fact_ids:
        problems.append(Problem(
            "fact_ids",
            f"a {observation.type} observation asserts something about the "
            "data and must cite the facts that say it"))
    if observation.type in NEEDS_TWO and len(observation.fact_ids) < 2:
        problems.append(Problem(
            "fact_ids",
            f"a {observation.type} is a relationship between facts; one fact "
            "cannot be one"))

    for fact_id in observation.fact_ids:
        try:
            fact = graph.get(fact_id)
        except ev.NotRegistered:
            problems.append(Problem("fact_ids", f"{fact_id} is not in the "
                                                "evidence graph"))
            continue
        if not fact.usable:
            problems.append(Problem(
                "fact_ids",
                f"{fact_id} is {fact.validation_status}; nothing may be said "
                "from it"))

    missing = [name for name in observation.slot_names()
               if name not in observation.slots]
    if missing:
        problems.append(Problem("slots", f"{', '.join(missing)} has no value"))

    return problems


def confidence(observation: Observation, graph: ev.Graph) -> float:
    """How much the EVIDENCE supports this. Never a model's opinion.

    Three inputs, all about the facts: how many are validated, how complete
    they are, and whether the type needs corroboration it does not have. An
    observation citing one thin fact for a claim that needs two lands low, and
    that is the number a reader should see.
    """
    if observation.type not in NEEDS_FACTS:
        # An observation about the analysis rather than the data. Its
        # confidence is not an evidence question, and inventing one would make
        # a limitation look uncertain when it is the most certain thing on
        # the page.
        return 1.0
    if not observation.fact_ids:
        return 0.0

    cited: list[ev.Fact] = []
    for fact_id in observation.fact_ids:
        try:
            cited.append(graph.get(fact_id))
        except ev.NotRegistered:
            return 0.0

    validated = sum(1 for f in cited if f.usable) / len(cited)
    quality = sum({ev.COMPLETE: 1.0, ev.PARTIAL: 0.65,
                   ev.THIN: 0.3}.get(f.evidence_quality, 0.3)
                  for f in cited) / len(cited)
    corroborated = 1.0
    if observation.type in NEEDS_TWO and len(cited) < 2:
        corroborated = 0.4
    return round(validated * quality * corroborated, 3)


def prioritise(observation: Observation) -> int:
    """Where this goes in the answer.

    Materiality shifts an observation within its type's band rather than
    across bands, so a CRITICAL rank observation still comes after the change
    it is ranking — a reader needs the movement before the league table, even
    when the league table is the alarming part.
    """
    base = ORDER.get(observation.type, 50) * 10
    if observation.type in ALWAYS_EARLY:
        base = min(base, 25)
    shift = {mt.CRITICAL: -4, mt.HIGH: -3, mt.MODERATE: -1,
             mt.LOW: 1, mt.IMMATERIAL: 3}.get(observation.materiality, 0)
    return base + shift


@dataclass
class Set:
    """Every observation one investigation produced."""

    observations: list[Observation] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)

    def add(self, observation: Observation, graph: ev.Graph) -> Observation:
        problems = validate(observation, graph)
        if problems:
            self.refused.append((observation.observation_id or "?",
                                 "; ".join(str(p) for p in problems)))
            return observation
        observation.confidence_from_evidence = confidence(observation, graph)
        observation.priority = prioritise(observation)
        self.observations.append(observation)
        return observation

    def ordered(self) -> list[Observation]:
        return sorted((o for o in self.observations if o.status == STATED),
                      key=lambda o: (o.priority, o.observation_id))

    def by_type(self, kind: str) -> list[Observation]:
        return [o for o in self.observations if o.type == kind]

    def material(self, at_least: str = mt.MODERATE) -> list[Observation]:
        floor = mt.BANDS.index(at_least)
        return [o for o in self.ordered()
                if mt.BANDS.index(o.materiality) >= floor]

    def facts_used(self) -> set[str]:
        return {f for o in self.observations for f in o.fact_ids}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": OBSERVATION_VERSION,
            "observations": [o.to_dict() for o in self.ordered()],
            "withheld": [o.to_dict() for o in self.observations
                         if o.status == WITHHELD],
            "refused": [{"observation_id": i, "why": w}
                        for i, w in self.refused],
            "counts": {kind: len(self.by_type(kind)) for kind in TYPES
                       if self.by_type(kind)},
            "facts_used": sorted(self.facts_used()),
        }


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
#
# Reviewed once, here, rather than written per observation. Each says exactly
# what its type may assert and no more — which is the mechanism, not a
# convenience.

TEMPLATES: dict[str, str] = {
    LEVEL: "{metric} for {entity} in {period} is {value}.",
    CHANGE: "{metric} for {entity} moved {change} between {opening} and "
            "{closing}.",
    RANK: "{entity} ranks {rank} of {total} by {metric}.",
    TREND: "{metric} for {entity} has moved {direction} over {periods} "
           "periods.",
    PERSISTENCE: "{verdict} {detail}",
    CONCENTRATION: "The top {n} entities account for {share} of the movement.",
    BREADTH: "{verdict} {detail}",
    DRIVER: "{entity} contributed {contribution} of the {metric} movement.",
    OFFSET: "A gross adverse movement of {adverse} is offset by {favourable} "
            "favourable, leaving {net}.",
    EXCEPTION: "{entity} does not follow the pattern: {detail}.",
    THRESHOLD_BREACH: "{entity} is {severity} past {limit}.",
    MIGRATION: "{count} entities moved from {origin} to {destination} between "
               "{opening} and {closing}.",
    ASSOCIATION: "{first} and {second} moved together over {periods} periods. "
                 "This is an association; nothing here establishes cause.",
    CONTRADICTION: "{first} and {second} point in opposite directions.",
    UNCERTAINTY: "{detail}",
    LIMITATION: "{detail}",
    NEXT_STEP: "{detail}",
    NO_MATCH: "No {subject} matched {criteria}.",
    UNAVAILABLE: "{subject} could not be examined: {detail}.",
}


def make(observation_id: str, kind: str, *, facts: list[str] | None = None,
         slots: dict[str, Any] | None = None,
         materiality: str = mt.IMMATERIAL,
         template: str = "", **extra: Any) -> Observation:
    """One observation, from the reviewed template for its type."""
    return Observation(
        observation_id=observation_id, type=kind,
        statement_template=template or TEMPLATES.get(kind, "{detail}"),
        slots=dict(slots or {}), fact_ids=list(facts or []),
        materiality=materiality,
        limitations=list(extra.get("limitations") or []),
        recommended_visual=str(extra.get("visual") or ""),
        recommended_follow_up=str(extra.get("follow_up") or ""),
        status=str(extra.get("status") or STATED))


__all__ = ["ALWAYS_EARLY", "ASSOCIATION", "BREADTH", "CHANGE",
           "CONCENTRATION", "CONTRADICTION", "DRIVER", "EXCEPTION", "LEVEL",
           "LIMITATION", "MIGRATION", "NEEDS_FACTS", "NEEDS_TWO", "NEXT_STEP",
           "NO_MATCH", "OBSERVATION_VERSION", "OFFSET", "ORDER",
           "Observation", "PERSISTENCE", "Problem", "RANK", "STATED",
           "STATUSES", "SUPERSEDED", "Set", "TEMPLATES", "THRESHOLD_BREACH",
           "TREND", "TYPES", "UNAVAILABLE", "UNCERTAINTY", "WITHHELD",
           "confidence", "make", "prioritise", "validate"]
