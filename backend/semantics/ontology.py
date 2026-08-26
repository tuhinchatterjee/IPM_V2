"""
The CreditProbe semantic ontology — one governed contract per credit concept.

Why this exists
---------------
A language model knows what leverage is. It does not know what *this bank*
means by exposure, and it has no way to find out: "exposure" is drawn balance
to a relationship manager, EAD to an impairment team, and the committed limit
to a concentration report. Those are three different numbers about the same
borrower, and a product that silently picks one is wrong two thirds of the time
while sounding certain every time.

So the ambiguity is written down, and a bare mention of an ambiguous concept is
a question CreditProbe asks rather than a guess it makes.

What a contract carries
-----------------------
Identity and language — id, business name, aliases, definition.
Ambiguity — whether a bare mention resolves, and what the alternatives are.
Data — the canonical field(s), from the concept registry.
Semantics — grain, unit, which direction is deterioration, whether it is
ordinal or categorical.
Governance — which operations are legitimate, how much history is needed, and
the arithmetic that must hold of any result claiming to report it.

Versioned
---------
`ONTOLOGY_VERSION` moves whenever a contract changes meaning. A certification
earned against one version says nothing about another, so the release manifest
records it and a stale score says which version it was earned on.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import concepts as cx

#: Moves when a contract changes meaning. Adding a contract for a concept that
#: had none is a minor move; changing what an existing concept resolves to is a
#: major one, because every certified score before it was earned on a different
#: understanding of the same word.
ONTOLOGY_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

SUM = "sum"
AVERAGE = "average"
COUNT = "count"
RANK = "rank"
COMPARE = "compare"
DISTRIBUTION = "distribution"
RATIO = "ratio"
WORST = "worst"
MOVEMENT = "movement"

#: What may legitimately be done to a plain additive money measure.
MONEY_OPS = (SUM, AVERAGE, RANK, COMPARE, DISTRIBUTION, RATIO, MOVEMENT)
#: A ratio is not additive. Summing DSCR across a portfolio is a type error
#: that produces a number, which is the worst kind.
RATIO_OPS = (AVERAGE, RANK, COMPARE, DISTRIBUTION, MOVEMENT)
#: An ordinal scale is counted in steps and rolled up by its worst value.
ORDINAL_OPS = (COUNT, RANK, COMPARE, DISTRIBUTION, WORST, MOVEMENT)
CATEGORY_OPS = (COUNT, DISTRIBUTION, COMPARE)


# ---------------------------------------------------------------------------
# Ambiguity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ambiguity:
    """Why a bare mention of this concept cannot be resolved, and the choices.

    `resolvers` are the words that settle it. They are checked against the
    question before the ambiguity is raised, so "exposure at default" answers
    while "exposure" asks.
    """

    question: str
    options: tuple[dict[str, str], ...]
    #: Phrases anywhere in the request that make the mention unambiguous.
    resolvers: tuple[str, ...] = ()

    def resolved_by(self, text: str) -> str:
        lowered = (text or "").lower()
        for phrase in self.resolvers:
            if phrase and phrase in lowered:
                return phrase
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question,
                "options": [dict(o) for o in self.options]}


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Invariant:
    """One arithmetic fact that must hold of a result reporting this concept.

    Stated as a rule name plus parameters rather than a lambda, because these
    are compiled into a check the Trace can print. A user reading "0 <= Stage 2
    EAD <= total EAD" understands what was verified; a user reading
    "<function <lambda>>" does not.
    """

    rule: str
    detail: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "detail": self.detail,
                "params": dict(self.params)}


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticContract:
    """Everything governed about one credit concept."""

    concept_id: str
    business_name: str
    definition: str
    aliases: tuple[str, ...] = ()
    #: None when a bare mention resolves.
    ambiguity: Ambiguity | None = None
    #: customer | facility | sector | portfolio — the grain the concept is
    #: naturally reported at, before a question asks for another.
    natural_grain: str = "facility"
    unit: str = ""
    #: True where a HIGHER number is worse.
    higher_is_worse: bool = True
    is_ordinal: bool = False
    is_categorical: bool = False
    #: Not additive: averaging is legitimate, summing is not.
    is_ratio: bool = False
    operations: tuple[str, ...] = MONEY_OPS
    #: How many periods a question about this concept needs to be answerable.
    #: A movement question about a concept published annually cannot be
    #: answered over one quarter.
    required_periods: int = 1
    #: Datasets that must be reachable for this concept to be computed at a
    #: grain other than its own.
    required_relationships: tuple[str, ...] = ()
    calculation: str = ""
    invariants: tuple[Invariant, ...] = ()

    # ---- derived ----------------------------------------------------------

    @property
    def concept(self) -> cx.Concept | None:
        return _BY_ID.get(self.concept_id)

    @property
    def fields(self) -> tuple[str, ...]:
        found = self.concept
        if found is None:
            return ()
        return tuple(f"{c.dataset}.{c.field}" for c in found.candidates)

    def permits(self, operation: str) -> bool:
        return (operation or "").lower() in self.operations

    def deterioration_word(self) -> str:
        if self.is_ordinal:
            return "downgraded"
        return "rose" if self.higher_is_worse else "fell"

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "business_name": self.business_name,
            "definition": self.definition,
            "aliases": list(self.aliases),
            "ambiguous": self.ambiguity is not None,
            "ambiguity": self.ambiguity.to_dict() if self.ambiguity else None,
            "natural_grain": self.natural_grain,
            "unit": self.unit,
            "higher_is_worse": self.higher_is_worse,
            "is_ordinal": self.is_ordinal,
            "is_categorical": self.is_categorical,
            "is_ratio": self.is_ratio,
            "operations": list(self.operations),
            "required_periods": self.required_periods,
            "required_relationships": list(self.required_relationships),
            "calculation": self.calculation,
            "fields": list(self.fields),
            "invariants": [i.to_dict() for i in self.invariants],
        }


_BY_ID: dict[str, cx.Concept] = {c.id: c for c in cx.CONCEPTS}


def _option(label: str, field_: str, note: str) -> dict[str, str]:
    return {"label": label, "field": field_, "note": note}


# ---------------------------------------------------------------------------
# The contracts themselves
# ---------------------------------------------------------------------------

CONTRACTS: tuple[SemanticContract, ...] = (
    SemanticContract(
        concept_id="exposure",
        business_name="Exposure",
        definition=(
            "How much of the bank's money is at risk to a borrower. Which "
            "measure that is depends on the question being asked, and the "
            "three governed answers differ by material amounts."),
        aliases=("exposure", "outstanding", "balance", "drawn"),
        ambiguity=Ambiguity(
            question=(
                "Which exposure figure should CreditProbe use? The three "
                "governed measures are materially different amounts."),
            options=(
                _option("Drawn exposure",
                        "portfolio_facility.exposure",
                        "The outstanding balance actually lent. What a "
                        "relationship manager usually means."),
                _option("Exposure at default (EAD)",
                        "portfolio_facility.ead",
                        "Drawn balance plus a credit-conversion allowance for "
                        "undrawn commitments. What impairment and capital use."),
                _option("Committed limit",
                        "portfolio_facility.limit_amount",
                        "The full facility limit, drawn or not. What "
                        "concentration and appetite reporting use."),
            ),
            resolvers=("drawn", "outstanding", "at default", "ead", "ccf",
                       "committed", "limit", "regulatory", "ifrs 9", "ifrs9"),
        ),
        natural_grain="facility",
        unit="USD mn",
        higher_is_worse=True,
        operations=MONEY_OPS,
        invariants=(
            Invariant("non_negative",
                      "Exposure cannot be negative.",
                      {"field_role": "measure"}),
        ),
    ),
    SemanticContract(
        concept_id="ead",
        business_name="Exposure at default",
        definition=(
            "Drawn balance plus a credit-conversion allowance for undrawn "
            "commitments. The exposure measure impairment and capital use."),
        aliases=("ead", "exposure at default"),
        natural_grain="facility",
        unit="USD mn",
        higher_is_worse=True,
        operations=MONEY_OPS,
        calculation="SUM(ead)",
        invariants=(
            Invariant("non_negative", "EAD cannot be negative.",
                      {"field_role": "measure"}),
        ),
    ),
    SemanticContract(
        concept_id="ecl",
        business_name="Expected credit loss",
        definition=(
            "The IFRS 9 provision carried against a facility — the loss the "
            "bank expects, not the loss it has taken."),
        aliases=("ecl", "expected credit loss", "provision", "impairment"),
        natural_grain="facility",
        unit="USD mn",
        higher_is_worse=True,
        operations=MONEY_OPS,
        calculation="SUM(total_ecl)",
        invariants=(
            Invariant("non_negative", "ECL cannot be negative.",
                      {"field_role": "measure"}),
        ),
    ),
    SemanticContract(
        concept_id="rating",
        business_name="Internal rating",
        definition=(
            "The grade awarded at the customer's annual rating cycle, one to "
            "ten, ten being default. An ordinal scale, not a quantity."),
        aliases=("rating", "grade", "notch", "downgrade", "upgrade"),
        natural_grain="customer",
        unit="notches",
        higher_is_worse=True,
        is_ordinal=True,
        operations=ORDINAL_OPS,
        required_periods=2,
        invariants=(
            Invariant("ordinal_range",
                      "An internal grade is between 1 and 10.",
                      {"minimum": 1, "maximum": 10}),
        ),
    ),
    SemanticContract(
        concept_id="stage",
        business_name="IFRS 9 stage",
        definition=(
            "The impairment stage a facility sits in: 1 performing, 2 "
            "significant increase in credit risk, 3 credit-impaired."),
        aliases=("stage", "staging", "sicr"),
        natural_grain="facility",
        higher_is_worse=True,
        is_ordinal=True,
        operations=ORDINAL_OPS,
        invariants=(
            Invariant("ordinal_range", "An IFRS 9 stage is 1, 2 or 3.",
                      {"minimum": 1, "maximum": 3}),
        ),
    ),
    SemanticContract(
        concept_id="dpd",
        business_name="Days past due",
        definition="How many days a facility's payment has been overdue.",
        aliases=("dpd", "days past due", "arrears", "delinquency", "overdue"),
        natural_grain="facility",
        unit="days",
        higher_is_worse=True,
        operations=(AVERAGE, RANK, COMPARE, DISTRIBUTION, WORST, MOVEMENT),
        invariants=(
            Invariant("non_negative", "Days past due cannot be negative.",
                      {"field_role": "measure"}),
        ),
    ),
    SemanticContract(
        concept_id="dscr",
        business_name="Debt service coverage ratio",
        definition=(
            "Cash available for debt service divided by debt service due. "
            "Below one means the borrower cannot service its debt from "
            "operations."),
        aliases=("dscr", "debt service coverage", "coverage ratio"),
        natural_grain="customer",
        unit="x",
        higher_is_worse=False,
        is_ratio=True,
        operations=RATIO_OPS,
        invariants=(
            Invariant("not_summed",
                      "DSCR is a ratio; a portfolio total is not a meaningful "
                      "figure.",
                      {"forbidden": "sum"}),
        ),
    ),
    SemanticContract(
        concept_id="leverage",
        business_name="Net leverage",
        definition=(
            "Net debt divided by EBITDA. How many years of earnings the "
            "borrower's debt represents."),
        aliases=("leverage", "gearing", "net debt to ebitda"),
        natural_grain="customer",
        unit="x",
        higher_is_worse=True,
        is_ratio=True,
        operations=RATIO_OPS,
        invariants=(
            Invariant("not_summed",
                      "Leverage is a ratio; a portfolio total is not a "
                      "meaningful figure.",
                      {"forbidden": "sum"}),
        ),
    ),
    SemanticContract(
        concept_id="headroom",
        business_name="Covenant headroom",
        definition=(
            "How much room a borrower has before it breaches a financial "
            "covenant, as a percentage of the tested level. Negative headroom "
            "is a breach."),
        aliases=("headroom", "covenant headroom", "covenant cushion"),
        natural_grain="facility",
        unit="%",
        higher_is_worse=False,
        is_ratio=True,
        operations=RATIO_OPS,
        required_relationships=("covenant_tests",),
    ),
    SemanticContract(
        concept_id="utilisation",
        business_name="Limit utilisation",
        definition=(
            "Drawn exposure as a percentage of the committed limit."),
        aliases=("utilisation", "utilization", "drawdown"),
        natural_grain="facility",
        unit="%",
        higher_is_worse=True,
        is_ratio=True,
        operations=RATIO_OPS,
        calculation="SUM(exposure) / SUM(limit_amount)",
        invariants=(
            Invariant("share_bounds",
                      "Utilisation is a share of a limit and lies between 0 "
                      "and 100%, unless the facility is over-limit.",
                      {"minimum": 0.0}),
        ),
    ),
    SemanticContract(
        concept_id="ecl_coverage",
        business_name="ECL coverage",
        definition=(
            "Expected credit loss as a percentage of exposure at default. How "
            "much of the exposure the bank has already provided against."),
        aliases=("ecl coverage", "coverage", "provision coverage"),
        natural_grain="facility",
        unit="%",
        higher_is_worse=True,
        is_ratio=True,
        operations=RATIO_OPS,
        calculation="SUM(total_ecl) / SUM(ead)",
        invariants=(
            Invariant("share_bounds",
                      "A coverage ratio lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        ),
    ),
)

#: A derived contract for the one composite the product computes by name.
STAGE_SHARE = SemanticContract(
    concept_id="stage_share",
    business_name="Stage 2 EAD share",
    definition=(
        "Exposure at default in IFRS 9 Stage 2, as a percentage of total "
        "exposure at default for the same population and period."),
    aliases=("stage 2 share", "stage 2 ead ratio", "stage 2 proportion"),
    natural_grain="sector",
    unit="%",
    higher_is_worse=True,
    is_ratio=True,
    operations=RATIO_OPS,
    calculation="SUM(ead WHERE ifrs9_stage = 2) / SUM(ead)",
    invariants=(
        Invariant("numerator_within_denominator",
                  "Stage 2 EAD cannot exceed total EAD.",
                  {"numerator": "stage2_ead", "denominator": "total_ead"}),
        Invariant("share_bounds",
                  "A share lies between 0 and 100%.",
                  {"minimum": 0.0, "maximum": 100.0}),
    ),
)

_ALL: tuple[SemanticContract, ...] = CONTRACTS + (STAGE_SHARE,)


def _index() -> dict[str, SemanticContract]:
    """Contracts by every name they answer to.

    A reading carries whichever name the reader had to hand — the concept id
    from the registry, the label a credit officer used, or one of the aliases.
    Indexing only by id meant "drawn exposure" found no contract and the
    ambiguity check silently passed, which is the failure this file exists to
    prevent, one level up.
    """
    out: dict[str, SemanticContract] = {}
    for found in _ALL:
        names = [found.concept_id, found.business_name, *found.aliases]
        concept = _BY_ID.get(found.concept_id)
        if concept is not None:
            names.append(concept.label)
        for name in names:
            key = (name or "").strip().lower()
            # First contract wins: an alias shared by two concepts belongs to
            # the one that declared it as its own name.
            if key and key not in out:
                out[key] = found
    return out


_INDEX: dict[str, SemanticContract] = _index()


# ---------------------------------------------------------------------------
# Reading the ontology
# ---------------------------------------------------------------------------


def contracts() -> tuple[SemanticContract, ...]:
    return _ALL


def contract(concept_id: str) -> SemanticContract | None:
    return _INDEX.get((concept_id or "").strip().lower())


def deterioration(concept_id: str) -> bool | None:
    """Whether a HIGHER value of this concept is worse. None if unknown.

    Returned rather than defaulted, because defaulting this to True inverts
    every DSCR and headroom answer, and the answer still reads fluently.
    """
    found = contract(concept_id)
    return None if found is None else found.higher_is_worse


def invariants_for(concept_ids: list[str] | tuple[str, ...]) -> list[Invariant]:
    out: list[Invariant] = []
    for cid in concept_ids or ():
        found = contract(cid)
        if found is not None:
            out.extend(found.invariants)
    return out


_WORD = re.compile(r"[a-z0-9]+")


def ambiguity_for(concept_ids: list[str] | tuple[str, ...],
                  question: str) -> tuple[SemanticContract, Ambiguity] | None:
    """The first materially ambiguous concept this request does not settle.

    Returns None when every concept named either has no ambiguity or is
    resolved by something the request already said.
    """
    text = (question or "").lower()
    for cid in concept_ids or ():
        found = contract(cid)
        if found is None or found.ambiguity is None:
            continue
        if found.ambiguity.resolved_by(text):
            continue
        return found, found.ambiguity
    return None


def fingerprint() -> str:
    """A stable hash of the whole ontology, for the release manifest.

    The version says what humans changed; this says whether anything changed
    at all, which is what a certification gate has to compare.
    """
    payload = json.dumps([c.to_dict() for c in _ALL], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


__all__ = [
    "CONTRACTS",
    "ONTOLOGY_VERSION",
    "Ambiguity",
    "Invariant",
    "SemanticContract",
    "ambiguity_for",
    "contract",
    "contracts",
    "deterioration",
    "fingerprint",
    "invariants_for",
]
