"""
The Evidence Fact Graph. §76.

    "The final narrative may use only registered validated facts."

That sentence is the whole architecture. Everything downstream — observations,
materiality, contradictions, the interpretation, the chart — reads Facts, and
a Fact only exists because a governed run produced it and a validator passed
it. Prose that wants to say something has to find a Fact that says it, and if
there is no such Fact the prose cannot say it.

What that buys, concretely
--------------------------
The grounding failure this prevents is not a model inventing a number. It is
subtler and far more common: a model taking two true numbers and asserting a
relationship between them that nobody computed. "ECL rose while coverage fell"
is two facts and one claim, and the claim is the part that needs its own Fact.
So a Fact may REFERENCE other Facts, and a derived Fact records what it was
derived from.

Why every fact carries its own provenance
------------------------------------------
`source_run_id`, `source_result_path`, `source_method`, `source_datasets`,
`source_relationships`. Five fields, and the temptation is to keep one run id
and look the rest up. The reason not to: a Trace is read months later, by
somebody deciding whether an answer can be relied on, and a lookup that has to
succeed at read time is a lookup that will eventually fail at read time.

Validation is a state, not a boolean
-------------------------------------
A fact can be VALIDATED, UNVALIDATED, or FAILED, and the third is not the same
as the second. A fact whose invariant failed is evidence that something is
wrong; a fact nothing has checked is evidence of nothing. Both are unusable in
a narrative, and they are unusable for different reasons that a reader needs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any

EVIDENCE_VERSION = "1.0.0"

# ------------------------------------------------------------- fact types
LEVEL = "LEVEL"
CHANGE = "CHANGE"
SHARE = "SHARE"
RANK = "RANK"
COUNT = "COUNT"
RATIO = "RATIO"
DISTRIBUTION = "DISTRIBUTION"
MIGRATION = "MIGRATION"
#: A fact computed from other facts rather than from data. Recorded as its own
#: type because "ECL rose while coverage fell" is a claim, not a measurement,
#: and the difference is what grounding is about.
DERIVED = "DERIVED"

FACT_TYPES: tuple[str, ...] = (LEVEL, CHANGE, SHARE, RANK, COUNT, RATIO,
                               DISTRIBUTION, MIGRATION, DERIVED)

# --------------------------------------------------------- validation state
VALIDATED = "VALIDATED"
UNVALIDATED = "UNVALIDATED"
FAILED = "FAILED"

VALIDATION_STATES: tuple[str, ...] = (VALIDATED, UNVALIDATED, FAILED)

# ------------------------------------------------------------- direction
#: What the movement means for credit risk, which is not the same as its sign.
#: A falling DSCR and a rising ECL are both deterioration.
WORSE = "WORSE"
BETTER = "BETTER"
FLAT = "FLAT"
UNKNOWN_DIRECTION = "UNKNOWN"

DIRECTIONS: tuple[str, ...] = (WORSE, BETTER, FLAT, UNKNOWN_DIRECTION)

#: How good the evidence behind a fact is. Not confidence — this is about the
#: DATA, and a model's opinion of it does not enter.
COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
THIN = "THIN"

QUALITIES: tuple[str, ...] = (COMPLETE, PARTIAL, THIN)


@dataclass
class Fact:
    """One permissible statement, with everything needed to defend it. §76."""

    fact_id: str = ""
    fact_type: str = LEVEL
    #: portfolio | segment | sector | borrower | facility | account | dataset
    entity_type: str = ""
    entity_id: str = ""
    entity_name: str = ""
    metric: str = ""
    #: The governed definition, copied rather than referenced. A Trace read in
    #: six months must not depend on the ontology still saying the same thing.
    business_definition: str = ""

    opening_period: str = ""
    closing_period: str = ""
    period: str = ""
    opening_value: float | None = None
    closing_value: float | None = None
    value: float | None = None
    change: float | None = None
    change_pct: float | None = None
    #: Percentage POINTS, for a measure that is already a percentage. Kept
    #: apart from `change_pct` because conflating them is how "coverage rose
    #: 2%" comes to mean two different things in one paragraph.
    change_pp: float | None = None
    unit: str = ""
    direction: str = UNKNOWN_DIRECTION
    #: What the movement means in credit terms, in one clause.
    risk_meaning: str = ""
    materiality: str = ""

    grain: str = ""
    population: dict[str, Any] = field(default_factory=dict)
    filters: list[dict[str, Any]] = field(default_factory=list)

    source_run_id: str = ""
    source_result_path: str = ""
    source_method: str = ""
    source_datasets: list[str] = field(default_factory=list)
    source_relationships: list[str] = field(default_factory=list)

    validation_status: str = UNVALIDATED
    invariant_status: str = ""
    evidence_quality: str = PARTIAL
    limitations: list[str] = field(default_factory=list)
    scope: str = ""
    fingerprint: str = ""
    #: Facts this one was derived from. §76: facts may reference other facts.
    derived_from: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether the narrative may say this.

        Validated only. An unvalidated fact is evidence of nothing and a
        failed one is evidence that something is wrong; neither is a sentence
        anybody may put in front of a client.
        """
        return self.validation_status == VALIDATED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> Fact:
        raw = dict(raw) if isinstance(raw, dict) else {}
        allowed = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in allowed})


#: What a fingerprint is computed over: what the fact SAYS. Deliberately
#: excludes validation state and limitations — a fact that has since been
#: validated is the same fact, and two runs producing the same measurement
#: must fingerprint alike so a Trace can show they agree.
FINGERPRINTED: tuple[str, ...] = (
    "fact_type", "entity_type", "entity_id", "metric", "period",
    "opening_period", "closing_period", "opening_value", "closing_value",
    "value", "change", "grain", "unit", "scope",
)


def fingerprint(fact: Fact) -> str:
    body = fact.to_dict()
    payload = {name: body.get(name) for name in FINGERPRINTED}
    payload["filters"] = sorted(json.dumps(f, sort_keys=True, default=str)
                                for f in fact.filters)
    blob = json.dumps(payload, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class Problem:
    field: str
    detail: str

    def __str__(self) -> str:
        return f"{self.field}: {self.detail}"


def validate(fact: Fact) -> list[Problem]:
    """Everything wrong with a fact, before anything is allowed to cite it."""
    problems: list[Problem] = []

    if not fact.fact_id:
        problems.append(Problem("fact_id", "is required"))
    if fact.fact_type not in FACT_TYPES:
        problems.append(Problem("fact_type",
                                f"{fact.fact_type!r} is not a fact type"))
    if not fact.metric:
        problems.append(Problem("metric", "a fact is about something"))
    if fact.validation_status not in VALIDATION_STATES:
        problems.append(Problem("validation_status",
                                f"{fact.validation_status!r} is not a state"))
    if fact.direction not in DIRECTIONS:
        problems.append(Problem("direction",
                                f"{fact.direction!r} is not a direction"))
    if fact.evidence_quality not in QUALITIES:
        problems.append(Problem("evidence_quality",
                                f"{fact.evidence_quality!r} is not a quality"))

    # A CHANGE fact needs two periods and a change. Without them it is a level
    # fact claiming to be a movement, which is the shape a spurious trend takes.
    if fact.fact_type == CHANGE:
        if not (fact.opening_period and fact.closing_period):
            problems.append(Problem("opening_period",
                                    "a change is between two named periods"))
        if fact.change is None and fact.change_pct is None and \
                fact.change_pp is None:
            problems.append(Problem("change", "a change fact has no change"))
    if fact.fact_type in (LEVEL, COUNT, RATIO, SHARE) and fact.value is None:
        problems.append(Problem("value", f"a {fact.fact_type} fact needs one"))

    # A percentage measure moves in percentage POINTS. Reporting it as a
    # percentage change is how "coverage rose 2%" comes to mean two things.
    if fact.unit in ("%", "pct", "percent") and fact.change_pct is not None \
            and fact.change_pp is None:
        problems.append(Problem(
            "change_pp",
            "a percentage measure moves in percentage points; record "
            "change_pp as well as change_pct or the sentence is ambiguous"))

    if not fact.source_run_id and fact.fact_type != DERIVED:
        problems.append(Problem("source_run_id",
                                "a measured fact names the run that made it"))
    if fact.fact_type == DERIVED and not fact.derived_from:
        problems.append(Problem("derived_from",
                                "a derived fact names what it came from"))
    if fact.fingerprint and fact.fingerprint != fingerprint(fact):
        problems.append(Problem("fingerprint", "does not match the content"))

    return problems


def sealed(fact: Fact) -> Fact:
    fact.fingerprint = fingerprint(fact)
    return fact


class NotRegistered(LookupError):
    """Something tried to cite a fact the graph does not hold."""


@dataclass
class Graph:
    """Every fact one investigation produced, and what may be said from it.

    Deliberately per-investigation rather than global. A graph that outlived
    its investigation would let a narrative cite a fact from a different run,
    different period or different population — which is the failure mode
    hardest to see and hardest to argue with afterwards, because every
    individual number is true.
    """

    facts: dict[str, Fact] = field(default_factory=dict)
    #: Facts refused on the way in, with why. Kept because a graph that
    #: silently dropped a malformed fact would produce a narrative missing a
    #: point nobody can find the absence of.
    refused: list[tuple[str, str]] = field(default_factory=list)

    def add(self, fact: Fact) -> Fact:
        """Register a fact, or record why it could not be."""
        problems = validate(fact)
        if problems:
            self.refused.append((fact.fact_id or "?",
                                 "; ".join(str(p) for p in problems)))
            return fact
        missing = [f for f in fact.derived_from if f not in self.facts]
        if missing:
            self.refused.append(
                (fact.fact_id,
                 f"derives from facts the graph does not hold: "
                 f"{', '.join(missing)}"))
            return fact
        sealed(fact)
        self.facts[fact.fact_id] = fact
        return fact

    def get(self, fact_id: str) -> Fact:
        found = self.facts.get(str(fact_id or ""))
        if found is None:
            raise NotRegistered(
                f"{fact_id!r} is not a registered fact. The narrative may use "
                "only registered validated facts (§76).")
        return found

    def cite(self, fact_ids: list[str]) -> list[Fact]:
        """The facts behind a statement, refusing anything unusable.

        Raises rather than filtering. A sentence built on four facts of which
        one is unvalidated is a sentence that should not be written, and
        quietly writing it from the other three changes what it says.
        """
        out: list[Fact] = []
        for fact_id in fact_ids:
            found = self.get(fact_id)
            if not found.usable:
                raise NotRegistered(
                    f"{fact_id} is {found.validation_status}, so nothing may "
                    "be said from it.")
            out.append(found)
        return out

    def usable(self) -> list[Fact]:
        return [f for f in self.facts.values() if f.usable]

    def by_entity(self, entity_id: str) -> list[Fact]:
        return [f for f in self.facts.values() if f.entity_id == entity_id]

    def by_metric(self, metric: str) -> list[Fact]:
        return [f for f in self.facts.values() if f.metric == metric]

    def duplicates(self) -> dict[str, list[str]]:
        """Facts that say the same thing.

        Not an error — two runs measuring the same quantity is corroboration —
        but worth seeing, because a narrative citing both is citing one fact
        twice and calling it two pieces of evidence.
        """
        by_print: dict[str, list[str]] = {}
        for fact in self.facts.values():
            by_print.setdefault(fact.fingerprint, []).append(fact.fact_id)
        return {k: v for k, v in by_print.items() if len(v) > 1}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": EVIDENCE_VERSION,
            "facts": [f.to_dict() for f in self.facts.values()],
            "usable": len(self.usable()),
            "registered": len(self.facts),
            "refused": [{"fact_id": i, "why": w} for i, w in self.refused],
            "duplicates": self.duplicates(),
        }


def direction_of(metric_worse_when_higher: bool | None,
                 change: float | None) -> str:
    """What a movement MEANS, from the concept's own direction.

    Takes the concept's direction as an argument rather than reading the
    ontology, because this module must stay usable over facts whose metric is
    a method output rather than a governed concept. A caller who does not know
    the direction passes None and gets UNKNOWN, which is honest and is what a
    Trace should show.
    """
    if change is None or metric_worse_when_higher is None:
        return UNKNOWN_DIRECTION
    if abs(change) < 1e-12:
        return FLAT
    rose = change > 0
    return WORSE if rose == bool(metric_worse_when_higher) else BETTER


__all__ = ["CHANGE", "COMPLETE", "COUNT", "DERIVED", "DIRECTIONS",
           "DISTRIBUTION", "EVIDENCE_VERSION", "FACT_TYPES", "FAILED",
           "FINGERPRINTED", "FLAT", "Fact", "Graph", "LEVEL", "MIGRATION",
           "NotRegistered", "PARTIAL", "Problem", "QUALITIES", "RANK",
           "RATIO", "SHARE", "THIN", "UNKNOWN_DIRECTION", "UNVALIDATED",
           "VALIDATED", "VALIDATION_STATES", "WORSE", "BETTER",
           "direction_of", "fingerprint", "sealed", "validate"]
