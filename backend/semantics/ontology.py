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
#
# 2.0.0 — P0.5. A MAJOR move, and by this module's own rule it has to be: "PD"
# used to resolve silently to the twelve-month figure and now asks which
# horizon, and "LGD" now asks modelled or realised. Every certification earned
# before this was earned on a different understanding of those words.
ONTOLOGY_VERSION = "2.0.0"

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

#: Every operation the product knows about, so a contract can state what it
#: REFUSES as well as what it permits.
ALL_OPS: tuple[str, ...] = (SUM, AVERAGE, COUNT, RANK, COMPARE, DISTRIBUTION,
                            RATIO, WORST, MOVEMENT)

# ---------------------------------------------------------------------------
# Period behaviour
# ---------------------------------------------------------------------------

#: A position at a date. The latest observation is the answer, and adding two
#: quarters of it double-counts the same balance.
SNAPSHOT = "snapshot"
#: Something that HAPPENED during a period — a default, a write-off, a cure.
#: Periods add up, and "the latest" is a quarter's worth rather than a level.
FLOW = "flow"
#: Measured since an origin. Differences between dates are meaningful; the
#: level on its own is only meaningful against that origin.
CUMULATIVE = "cumulative"

PERIOD_BEHAVIOURS: tuple[str, ...] = (SNAPSHOT, FLOW, CUMULATIVE)


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
    #: Aggregations that are WRONG for this concept, each with the reason.
    #: P0.5 asks for invalid aggregations as well as valid ones, and the
    #: reason is the half that matters: "you may not sum DSCR" is a rule
    #: somebody will route around, and "the sum of ten coverage ratios is
    #: neither a ratio nor a total" is an explanation they will not.
    #:
    #: Derived from `operations` where it is not stated, so a contract that
    #: lists only what it permits still refuses the rest — but a contract that
    #: says WHY teaches, and this is where that goes.
    forbidden: tuple[tuple[str, str], ...] = ()
    #: How this concept behaves across periods:
    #:   snapshot   a position at a date; the latest is the answer
    #:   flow       something that happened DURING a period; periods add up
    #:   cumulative measured since an origin; differences, never levels
    period_behaviour: str = SNAPSHOT
    #: How many periods a question about this concept needs to be answerable.
    #: A movement question about a concept published annually cannot be
    #: answered over one quarter.
    required_periods: int = 1
    #: Datasets that must be reachable for this concept to be computed at a
    #: grain other than its own.
    required_relationships: tuple[str, ...] = ()
    #: The canonical field(s), where the concept registry does not carry them.
    #: A contract without a registry concept still has to name its data, or it
    #: is a definition wearing the clothes of an implementation.
    canonical_fields: tuple[str, ...] = ()
    #: Arabic names for this concept. Empty until the Arabic scope lands; the
    #: field exists now so the contract is the one place a translator edits,
    #: rather than a parallel dictionary that drifts from it.
    arabic_aliases: tuple[str, ...] = ()
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
            return tuple(self.canonical_fields)
        return tuple(f"{c.dataset}.{c.field}" for c in found.candidates)

    def permits(self, operation: str) -> bool:
        return (operation or "").lower() in self.operations

    def refusal(self, operation: str) -> str:
        """Why this operation is wrong for this concept, or empty if it is not.

        A refusal without a reason gets routed around. This is the sentence a
        user sees when they ask for the average of a stage or the sum of a
        coverage ratio, and it has to be about the concept rather than about
        the rule.
        """
        wanted = (operation or "").lower()
        if wanted in self.operations:
            return ""
        for name, reason in self.forbidden:
            if name == wanted:
                return reason
        return (f"{self.business_name} does not support {wanted}. The governed "
                f"operations are: {', '.join(self.operations)}.")

    @property
    def invalid_operations(self) -> tuple[str, ...]:
        """Every operation this concept refuses. Stated, not left implied —
        P0.5 asks for invalid aggregations alongside the valid ones."""
        return tuple(op for op in ALL_OPS if op not in self.operations)

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
            "invalid_operations": list(self.invalid_operations),
            "forbidden": [{"operation": op, "reason": why}
                          for op, why in self.forbidden],
            "period_behaviour": self.period_behaviour,
            "arabic_aliases": list(self.arabic_aliases),
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
        unit="SAR mn",
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
        unit="SAR mn",
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
        unit="SAR mn",
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
        # The registry calls this `covenant_headroom`. Naming it "headroom"
        # here meant the contract resolved to no concept, so it carried no
        # fields — a governed contract with nothing behind it, and nothing said
        # so until the ontology was checked against its own promises.
        concept_id="covenant_headroom",
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
        # Higher coverage is MORE provision held against the same exposure,
    # which is the prudent direction. The concept registry has always said so;
    # this contract said the opposite, and two records of which way is worse is
    # one too many — the disagreement inverts the answer, and nothing on screen
    # would have shown which one won.
    higher_is_worse=False,
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
    # Derived rather than stored, so there is no registry concept to inherit
    # fields from and the contract has to name the columns it is computed out
    # of. Without them it is a definition with no data behind it.
    canonical_fields=("ifrs9_staging.ead", "ifrs9_staging.ifrs9_stage"),
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

# ---------------------------------------------------------------------------
# Ontology v2 — P0.5
# ---------------------------------------------------------------------------
#
# Twenty-five further concepts a credit officer says out loud and CreditProbe
# previously had no governed meaning for. Each carries what P0.5 asks: aliases,
# canonical fields, a definition, the direction of deterioration, units, the
# aggregations that are valid AND the ones that are not with the reason, the
# natural grain, how it behaves across periods, the joins it needs, an
# ambiguity policy where a bare mention does not resolve, and the arithmetic
# that must hold of any result reporting it.
#
# The invalid aggregations are the half that was missing. "You may not sum
# DSCR" is a rule somebody routes around; "the sum of ten coverage ratios is
# neither a ratio nor a total" is an explanation they do not.

CONTRACTS_V2: tuple[SemanticContract, ...] = (
    SemanticContract(
        concept_id="pd_12m",
        business_name="Twelve-month PD",
        definition=(
            "The probability that a borrower defaults within the next twelve "
            "months. The horizon IFRS 9 uses in Stage 1, and the one an "
            "unqualified 'PD' most often means on a performing book."),
        aliases=("12-month PD", "twelve-month PD", "one-year PD", "PD12"),
        natural_grain="facility", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Probabilities do not add. The sum of ten twelve-month PDs "
                  "is not the chance of anything happening; to size the risk, "
                  "weight them by exposure or ask for expected loss."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="pd_12m_pct, as the impairment run recorded it",
        invariants=(
            Invariant("share_bounds",
                      "A probability lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="pd_lifetime",
        business_name="Lifetime PD",
        definition=(
            "The probability of default over the remaining life of the "
            "exposure. What IFRS 9 uses once a significant increase in credit "
            "risk has moved an account out of Stage 1 — so a rise in lifetime "
            "PD at the portfolio level can be a staging effect rather than a "
            "deterioration in any borrower."),
        aliases=("lifetime PD", "full-life PD", "remaining-life PD"),
        natural_grain="facility", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Probabilities do not add, and lifetime PDs over different "
                  "remaining maturities are not even the same horizon."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="pd_lifetime_pct, as the impairment run recorded it",
        invariants=(
            Invariant("share_bounds",
                      "A probability lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="pd",
        business_name="Probability of default",
        definition=(
            "How likely a borrower is to default. Over what horizon is the "
            "whole question, and the two governed answers differ by a factor "
            "of three on this book."),
        aliases=("PD", "probability of default", "default probability"),
        ambiguity=Ambiguity(
            question=(
                "Over which horizon? Twelve-month and lifetime PD are "
                "different measures, and IFRS 9 uses each in different stages."),
            options=(
                _option("Twelve-month PD", "ifrs9_staging.pd_12m_pct",
                        "The chance of default within a year. Used in Stage 1, "
                        "and the usual reading on a performing book."),
                _option("Lifetime PD", "ifrs9_staging.pd_lifetime_pct",
                        "The chance of default over the remaining life. Used "
                        "once SICR has moved an account to Stage 2 or 3."),
                _option("PD at origination",
                        "ifrs9_staging.pd_at_origination_pct",
                        "The PD when the exposure was first recognised. The "
                        "reference point SICR is measured against, not a "
                        "current risk measure."),
            ),
            resolvers=("12-month", "12 month", "twelve-month", "twelve month",
                       "one-year", "one year", "lifetime", "life-time",
                       "origination", "pd12")),
        natural_grain="facility", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Probabilities do not add. The sum of ten PDs is not the "
                  "chance of anything; weight them by exposure, or ask for "
                  "expected loss, which is the figure that does add."),
        ),
        period_behaviour=SNAPSHOT,
        invariants=(
            Invariant("share_bounds",
                      "A probability lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="pd_origination",
        business_name="PD at origination",
        definition=(
            "The probability of default recorded when the exposure was first "
            "recognised. Not a view of current risk — it is the fixed "
            "reference point that current PD is compared against to decide "
            "whether credit risk has increased significantly."),
        aliases=("origination PD", "initial PD", "PD at inception"),
        natural_grain="facility", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Probabilities do not add; weight them by exposure."),
            (MOVEMENT, "This is a fixed reference recorded at origination. A "
                       "movement in it between two reporting dates would mean "
                       "the book changed, not that any borrower did."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="pd_at_origination_pct",
        invariants=(
            Invariant("share_bounds",
                      "A probability lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="lgd",
        business_name="Loss given default",
        definition=(
            "The share of exposure the bank expects NOT to recover if the "
            "borrower defaults. A modelled assumption on a performing book and "
            "an observed outcome on a closed default, and those are different "
            "numbers about different populations."),
        aliases=("LGD", "loss given default", "loss severity"),
        ambiguity=Ambiguity(
            question=(
                "Modelled LGD or realised LGD? One is the assumption used to "
                "compute impairment; the other is what recoveries actually "
                "produced on the defaults that have closed."),
            options=(
                _option("Modelled LGD", "ifrs9_staging.lgd_pct",
                        "The assumption the impairment calculation used. "
                        "Available for the whole book."),
                _option("Realised LGD", "recoveries.realised_lgd_pct",
                        "The loss actually taken once recoveries were in. Only "
                        "exists for defaults that have run their course, which "
                        "is a much smaller and later population."),
            ),
            resolvers=("modelled", "modeled", "model", "realised", "realized",
                       "actual", "observed", "recovery", "recovered")),
        natural_grain="facility", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "LGD is a rate, not an amount. To size the loss, multiply by "
                  "exposure at default rather than adding rates together."),
        ),
        period_behaviour=SNAPSHOT,
        invariants=(
            Invariant("share_bounds",
                      "A loss rate lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="realised_lgd",
        business_name="Realised loss given default",
        definition=(
            "The loss actually taken on a defaulted exposure once recoveries "
            "were collected. Backward-looking and survivorship-prone: it "
            "exists only for defaults that have run their course, so recent "
            "vintages are systematically absent."),
        aliases=("realised LGD", "actual LGD", "observed LGD"),
        natural_grain="facility", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "A loss rate is not an amount. To size the realised loss, "
                  "multiply by exposure at default rather than adding rates."),
        ),
        period_behaviour=FLOW,
        required_relationships=("recoveries -> portfolio_facility",),
        calculation="realised_lgd_pct = 1 - (cash_recovered + "
                    "collateral_realised) / ead_at_default",
        invariants=(
            Invariant("share_bounds",
                      "A realised loss rate lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="sicr",
        business_name="Significant increase in credit risk",
        definition=(
            "Whether an exposure has deteriorated enough since origination to "
            "move from a twelve-month to a lifetime loss horizon. Five "
            "governed triggers are recorded separately, and a facility can "
            "fire several at once."),
        aliases=("SICR", "significant increase in credit risk",
                 "staging trigger", "Stage 2 trigger"),
        natural_grain="facility", is_categorical=True,
        operations=CATEGORY_OPS,
        forbidden=(
            (SUM, "A trigger is a flag, not a quantity. Count the facilities "
                  "firing it, or sum the exposure behind them."),
            (AVERAGE, "The average of a set of flags is a proportion wearing "
                      "the units of nothing. Ask for the share instead."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="sicr_any_trigger, or the five triggers separately",
        invariants=(
            Invariant("triggered_implies_stage",
                      "A facility with any SICR trigger active must not be in "
                      "Stage 1.",
                      {"flag": "sicr_any_trigger", "stage": "ifrs9_stage"}),
        )),
    SemanticContract(
        concept_id="overlay",
        business_name="Management and macro overlay",
        definition=(
            "The amount added to modelled ECL by judgement rather than by the "
            "model — for risks the model does not capture, or for a "
            "forward-looking view the calibration does not yet reflect. An "
            "overlay is an opinion with a number on it."),
        aliases=("overlay", "management adjustment", "post-model adjustment",
                 "PMA"),
        natural_grain="facility", unit="SAR mn", higher_is_worse=True,
        operations=MONEY_OPS,
        forbidden=(
            (RATIO, "An overlay divided by anything is not a governed measure. "
                    "If the question is how much of ECL is judgement, ask for "
                    "the overlay and modelled ECL side by side."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="macro_overlay = total_ecl - model_ecl",
        invariants=(
            Invariant("overlay_reconciles",
                      "Modelled ECL plus overlay equals total ECL.",
                      {"parts": ["model_ecl", "macro_overlay"],
                       "total": "total_ecl"}),
        )),
    SemanticContract(
        concept_id="model_ecl",
        business_name="Modelled ECL",
        definition=(
            "Expected credit loss as the impairment model computed it, before "
            "any management or macro overlay. The part of the charge that is "
            "reproducible from the model's inputs."),
        aliases=("modelled ECL", "model ECL", "pre-overlay ECL"),
        natural_grain="facility", unit="SAR mn", higher_is_worse=True,
        operations=MONEY_OPS, period_behaviour=SNAPSHOT,
        calculation="model_ecl",
        invariants=(
            Invariant("non_negative", "Modelled ECL cannot be negative.",
                      {"field": "model_ecl"}),
        )),
    SemanticContract(
        concept_id="external_rating",
        business_name="External rating",
        definition=(
            "The rating a credit agency has assigned. A different scale from "
            "the internal grade and not interchangeable with it: the notch gap "
            "between the two is itself a governed signal."),
        aliases=("external rating", "agency rating", "S&P", "Moody's",
                 "Fitch"),
        natural_grain="customer", is_categorical=True,
        operations=CATEGORY_OPS,
        forbidden=(
            (AVERAGE, "An agency rating is a label on an ordered scale, not a "
                      "number. The average of BBB and B is not a rating."),
            (SUM, "Ratings do not add. A grade is a position on an ordered "
                  "scale; to size the risk behind them, sum the exposure."),
        ),
        period_behaviour=SNAPSHOT,
        required_relationships=("customer_ratings -> portfolio_facility",),
        calculation="external_rating, as recorded at the rating cycle"),
    SemanticContract(
        concept_id="npl",
        business_name="Non-performing",
        definition=(
            "Whether an exposure is non-performing — typically ninety days "
            "past due or in Stage 3. The bank's own definition governs, and it "
            "is recorded rather than derived at read time."),
        aliases=("NPL", "non-performing", "NPE", "bad book"),
        natural_grain="facility", is_categorical=True,
        operations=CATEGORY_OPS,
        forbidden=(
            (SUM, "A status is not an amount. Count the facilities, or sum the "
                  "exposure behind them."),
            (AVERAGE, "The average of a flag is a share wearing no units."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="npl, as the book recorded it",
        invariants=(
            Invariant("npl_implies_stage",
                      "A non-performing facility should not be in Stage 1.",
                      {"flag": "npl", "stage": "ifrs9_stage"}),
        )),
    SemanticContract(
        concept_id="arrears",
        business_name="Arrears",
        definition=(
            "The amount currently overdue on a facility. Distinct from the "
            "exposure of accounts in arrears, which is the whole balance "
            "rather than the missed part — and those two differ by an order of "
            "magnitude."),
        aliases=("arrears", "amount overdue", "past due amount"),
        natural_grain="facility", unit="SAR mn", higher_is_worse=True,
        operations=MONEY_OPS, period_behaviour=SNAPSHOT,
        required_relationships=("facility_delinquency -> portfolio_facility",),
        calculation="arrears_amount",
        invariants=(
            Invariant("non_negative", "Arrears cannot be negative.",
                      {"field": "arrears_amount"}),
        )),
    SemanticContract(
        concept_id="dpd_bucket",
        business_name="Delinquency bucket",
        definition=(
            "The ordered band of days past due an account sits in. An ordinal "
            "scale: buckets are compared and counted, and the worst one "
            "governs a roll-up."),
        aliases=("DPD bucket", "delinquency bucket", "ageing bucket",
                 "arrears bucket"),
        natural_grain="facility", is_ordinal=True, operations=ORDINAL_OPS,
        forbidden=(
            (SUM, "Buckets are bands, not quantities. Count the accounts in "
                  "each, or sum the exposure sitting in them."),
            (AVERAGE, "The average of '31-60' and '90+' is not a bucket. Take "
                      "the worst, or report the distribution."),
        ),
        period_behaviour=SNAPSHOT,
        required_relationships=("facility_delinquency -> portfolio_facility",),
        calculation="dpd_bucket"),
    SemanticContract(
        concept_id="cure",
        business_name="Cure",
        definition=(
            "An account returning to performing after a period of "
            "deterioration. A cure achieved by payment and a cure achieved by "
            "restructuring are not the same event, and the forbearance flag is "
            "what separates them."),
        aliases=("cure", "cured", "returned to performing", "rehabilitation"),
        natural_grain="facility", higher_is_worse=False, is_categorical=True,
        operations=CATEGORY_OPS, period_behaviour=FLOW, required_periods=2,
        required_relationships=("facility_delinquency -> portfolio_facility",),
        calculation="cured_this_period",
        invariants=(
            Invariant("cure_needs_prior_delinquency",
                      "An account cannot cure without having been delinquent.",
                      {"flag": "cured_this_period"}),
        )),
    SemanticContract(
        concept_id="forbearance",
        business_name="Forbearance",
        definition=(
            "A concession granted because the borrower is in financial "
            "difficulty — rescheduling, a payment holiday, a covenant waiver. "
            "Forbearance changes what a performing status means, which is why "
            "it is recorded separately from it."),
        aliases=("forbearance", "restructuring", "concession", "rescheduling"),
        natural_grain="facility", is_categorical=True,
        operations=CATEGORY_OPS,
        forbidden=(
            (SUM, "A concession type is a label, not a quantity. Count the "
                  "facilities carrying one, or sum the exposure behind them."),
            (AVERAGE, "There is no average concession. Report the distribution "
                      "of concession types instead."),
        ),
        period_behaviour=SNAPSHOT,
        required_relationships=("facility_delinquency -> portfolio_facility",),
        calculation="forbearance_type, restructured_flag"),
    SemanticContract(
        concept_id="collateral",
        business_name="Collateral value",
        definition=(
            "What the bank holds as security. Market value and net realisable "
            "value differ by the governed haircut, and using the wrong one "
            "overstates coverage by exactly that margin."),
        aliases=("collateral", "security", "collateral value"),
        ambiguity=Ambiguity(
            question=(
                "Market value or net realisable value? They differ by the "
                "governed haircut, and coverage computed on the wrong one is "
                "overstated."),
            options=(
                _option("Net realisable value",
                        "collateral_register.net_realisable_value",
                        "Market value less the haircut — what the bank would "
                        "expect to realise. The figure a coverage ratio "
                        "should use."),
                _option("Market value", "collateral_register.market_value",
                        "The valuer's figure before any haircut."),
                _option("Carried collateral value",
                        "portfolio_facility.collateral_value",
                        "The collateral value carried on the facility "
                        "position."),
            ),
            resolvers=("net realisable", "realisable", "haircut", "market "
                       "value", "gross", "carried")),
        natural_grain="facility", unit="SAR mn", higher_is_worse=False,
        operations=MONEY_OPS, period_behaviour=SNAPSHOT,
        required_relationships=("collateral_register -> portfolio_facility",),
        invariants=(
            Invariant("non_negative", "Collateral value cannot be negative.",
                      {"field": "collateral_value"}),
        )),
    SemanticContract(
        concept_id="limit",
        business_name="Approved limit",
        definition=(
            "The facility amount approved by the bank, drawn or not. The "
            "denominator of utilisation, and the exposure a concentration "
            "limit is measured against — not the same thing as the balance "
            "outstanding."),
        aliases=("limit", "approved limit", "facility size",
                 "committed amount"),
        natural_grain="facility", unit="SAR mn", higher_is_worse=True,
        operations=MONEY_OPS, period_behaviour=SNAPSHOT,
        calculation="limit_amount",
        invariants=(
            Invariant("non_negative", "An approved limit cannot be negative.",
                      {"field": "limit_amount"}),
            Invariant("drawn_within_limit",
                      "Drawn exposure should not exceed the approved limit "
                      "except where an excess is recorded.",
                      {"drawn": "exposure", "limit": "limit_amount"}),
        )),
    SemanticContract(
        concept_id="undrawn",
        business_name="Undrawn commitment",
        definition=(
            "The approved amount not yet drawn. Contingent exposure: it "
            "carries no balance today and converts into one at the credit "
            "conversion factor, which is why EAD exceeds drawn exposure."),
        aliases=("undrawn", "unutilised", "unused limit"),
        natural_grain="facility", unit="SAR mn", higher_is_worse=True,
        operations=MONEY_OPS, period_behaviour=SNAPSHOT,
        calculation="undrawn = limit_amount - exposure",
        invariants=(
            Invariant("non_negative",
                      "An undrawn commitment cannot be negative.",
                      {"field": "undrawn"}),
        )),
    SemanticContract(
        concept_id="default_rate",
        business_name="Observed default rate",
        definition=(
            "The share of a segment that actually defaulted over a period. "
            "The realised outcome PD models are calibrated against, and a "
            "backward-looking measure — it says what happened, never what "
            "will."),
        aliases=("observed default rate", "ODR", "default rate",
                 "realised default rate"),
        natural_grain="portfolio", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Rates over segments do not add; weight them by the "
                  "facilities behind them."),
        ),
        period_behaviour=FLOW, required_periods=1,
        calculation="observed_default_rate_pct, by segment and period",
        invariants=(
            Invariant("share_bounds",
                      "A default rate lies between 0 and 100%.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="notches_moved",
        business_name="Rating migration",
        definition=(
            "How far a borrower's grade moved at its rating cycle, in notches. "
            "A count of steps on an ordered scale, and a movement measure "
            "rather than a level — it needs a from and a to."),
        aliases=("notches moved", "rating migration", "notch movement"),
        natural_grain="customer", unit="notches", higher_is_worse=True,
        operations=(SUM, AVERAGE, COUNT, RANK, COMPARE, DISTRIBUTION,
                    MOVEMENT),
        period_behaviour=FLOW, required_periods=2,
        required_relationships=("customer_ratings -> portfolio_facility",),
        calculation="notches_moved = to_grade - from_grade"),
    SemanticContract(
        concept_id="stage_moved",
        business_name="Stage migration",
        definition=(
            "Whether an account changed IFRS 9 stage this period, and which "
            "way. A flow between two states — the count of accounts that moved "
            "is not the count of accounts in a stage."),
        aliases=("stage migration", "stage move", "staging movement"),
        natural_grain="facility", is_categorical=True,
        operations=CATEGORY_OPS, period_behaviour=FLOW, required_periods=2,
        forbidden=(
            (SUM, "A migration is an event, not a quantity. Count the accounts "
                  "that moved, or sum the exposure that moved with them."),
        ),
        calculation="stage_moved, from prior_stage to ifrs9_stage",
        invariants=(
            Invariant("stage_move_needs_two_stages",
                      "A recorded migration requires a prior stage that "
                      "differs from the current one.",
                      {"from": "prior_stage", "to": "ifrs9_stage"}),
        )),
    SemanticContract(
        concept_id="appetite",
        business_name="Risk appetite utilisation",
        definition=(
            "How much of a sector's approved concentration limit the book "
            "currently uses. A governance measure rather than a risk measure: "
            "being inside appetite says the exposure was authorised, not that "
            "it is safe."),
        aliases=("risk appetite", "appetite utilisation", "appetite breach",
                 "concentration limit"),
        natural_grain="sector", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Utilisations of different limits do not add — the "
                  "denominators differ. Compare them, or weight by the "
                  "exposure behind each limit."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="utilisation_of_limit_pct = actual_pct_of_book / "
                    "limit_pct_of_book",
        invariants=(
            Invariant("non_negative",
                      "Appetite utilisation cannot be negative.",
                      {"field": "utilisation_of_limit_pct"}),
        )),
    SemanticContract(
        concept_id="raroc",
        business_name="Risk-adjusted return on capital",
        definition=(
            "Net profit after the expected loss charge, over the regulatory "
            "capital the facility consumes. A return measure that already has "
            "credit risk priced into its numerator, so it must not be adjusted "
            "for risk a second time."),
        aliases=("RAROC", "risk-adjusted return", "return on capital"),
        natural_grain="facility", unit="%", higher_is_worse=False,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Returns on different capital bases do not add. Weight by "
                  "regulatory capital."),
        ),
        period_behaviour=SNAPSHOT,
        required_relationships=("facility_profitability -> portfolio_facility",),
        calculation="raroc_pct = net_profit / regulatory_capital"),
    SemanticContract(
        concept_id="interest_cover",
        business_name="Interest coverage",
        definition=(
            "How many times earnings cover the interest bill. A borrower-level "
            "affordability measure read from the financial record, so it is as "
            "old as the last set of accounts rather than as fresh as the "
            "book."),
        aliases=("interest coverage", "interest cover", "ICR",
                 "times interest earned"),
        natural_grain="customer", unit="x", higher_is_worse=False,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Coverage multiples do not add. The sum of ten ratios is "
                  "neither a ratio nor a total."),
        ),
        period_behaviour=SNAPSHOT,
        required_relationships=("customer_ratings -> portfolio_facility",),
        calculation="interest_coverage = EBITDA / interest expense"),
    SemanticContract(
        concept_id="margin",
        business_name="EBITDA margin",
        definition=(
            "Earnings before interest, tax, depreciation and amortisation as a "
            "share of revenue. A profitability measure from the borrower's "
            "accounts, not from the bank's book."),
        aliases=("EBITDA margin", "operating margin", "margin"),
        natural_grain="customer", unit="%", higher_is_worse=False,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Margins do not add. A portfolio margin is total EBITDA over "
                  "total revenue, never the sum of the borrowers' margins."),
        ),
        period_behaviour=SNAPSHOT,
        required_relationships=("customer_ratings -> portfolio_facility",),
        calculation="ebitda_margin_pct"),
)


# ------------------------------------------------ the corporate graph. B44.
#
# These exist for the FORBIDDEN clauses more than for the definitions. Every
# one of these measures reads like something a credit officer already knows -
# a score between 0 and 100, a fraction that rises with distress, a group -
# and each one is a different quantity from the thing it resembles. The
# contract is where "you may not add these" and "this is not a probability"
# live in a form the runtime can enforce rather than in a paragraph a reader
# may or may not have seen.
CONTRACTS_GRAPH: tuple[SemanticContract, ...] = (
    SemanticContract(
        concept_id="network_risk_score",
        business_name="Network Risk Score",
        definition=(
            "A RELATIVE RANKING of a borrower's structural position in the "
            "relationship graph, as 100 x (0.45 x normalised DebtRank + 0.35 "
            "x normalised forward PageRank + 0.20 x normalised betweenness). "
            "It is NOT a probability, NOT a probability of default, NOT a "
            "rating, NOT an IFRS 9 stage and NOT an expected credit loss. It "
            "ranks borrowers against each other in this population and "
            "carries no meaning outside it."),
        aliases=("network risk score", "network score", "NRS",
                 "structural risk score"),
        natural_grain="customer", unit="index", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Rankings do not add. The sum of ten Network Risk Scores "
                  "is not a portfolio's network risk and is not a quantity "
                  "of anything."),
        ),
        period_behaviour=SNAPSHOT,
        calculation=("network_risk_score, from the derived graph. A relative "
                     "ranking within the scored population, not a "
                     "probability"),
        invariants=(
            Invariant("share_bounds",
                      "The score is normalised onto 0-100 within the scored "
                      "population.",
                      {"minimum": 0.0, "maximum": 100.0}),
        )),
    SemanticContract(
        concept_id="debtrank",
        business_name="DebtRank impact",
        definition=(
            "How much of the network's value is impaired when this borrower "
            "is shocked, as a fraction. Network analytics and early warning: "
            "it is NOT an expected credit loss, NOT a capital methodology and "
            "NOT a regulatory measure of anything. It reads like a loss rate "
            "- it is a fraction, and it rises with distress - which is "
            "exactly why it must never be presented as one."),
        aliases=("DebtRank", "debt rank", "debtrank impact",
                 "network impact", "contagion impact"),
        natural_grain="customer", unit="ratio", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Impacts do not add. Two borrowers' DebtRank impacts "
                  "overlap wherever their networks do, so the sum "
                  "double-counts the shared neighbours."),
        ),
        period_behaviour=SNAPSHOT,
        calculation=("debtrank_impact, from W[i,j] = min(1, X[i,j]/C[i]) "
                     "with each node propagating exactly once"),
        invariants=(
            Invariant("share_bounds",
                      "A fraction of the network lies between 0 and 1.",
                      {"minimum": 0.0, "maximum": 1.0}),
        )),
    SemanticContract(
        concept_id="group_utilisation",
        business_name="Group limit utilisation",
        definition=(
            "A connected counterparty group's total exposure at default as a "
            "share of the eligible capital reference. The threshold it is "
            "compared against is an UNVERIFIED REGULATORY PARAMETER carried "
            "from a framework document, not confirmed as currently binding "
            "law, and a breach here is a candidate for assessment rather "
            "than a regulatory finding."),
        aliases=("group utilisation", "group limit utilisation",
                 "large exposure", "group concentration"),
        natural_grain="customer", unit="%", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Group utilisations do not add across borrowers: every "
                  "member of a group carries the SAME group figure, so "
                  "summing them multiplies one group's exposure by its "
                  "member count."),
        ),
        period_behaviour=SNAPSHOT,
        calculation=("group_utilisation_pct = group EAD / eligible capital "
                     "reference x 100")),
    SemanticContract(
        concept_id="ubo",
        business_name="Ultimate beneficial owners",
        definition=(
            "The number of natural persons whose INTEGRATED ownership of a "
            "borrower reaches 25%. Counted through the whole chain rather "
            "than from direct shareholdings, which is the entire reason a "
            "pyramid structure is built. A borrower whose ownership "
            "component was rejected by a data-quality check has no count at "
            "all - which is different from having no owner."),
        aliases=("UBO", "ubo count", "ultimate beneficial owner",
                 "beneficial owner", "ultimate owner"),
        natural_grain="customer", unit="count", higher_is_worse=False,
        operations=(COUNT, RANK, COMPARE, DISTRIBUTION, MOVEMENT),
        forbidden=(
            (AVERAGE, "An average number of beneficial owners is not a "
                      "quantity anybody acts on. Ask how many borrowers have "
                      "none, or which have more than one."),
        ),
        period_behaviour=SNAPSHOT,
        calculation=("natural persons with an integrated stake at or above "
                     "25%, from A(I-A)^-1")),
    SemanticContract(
        concept_id="group_size",
        business_name="Connected group size",
        definition=(
            "The number of borrowers in a connected counterparty CANDIDATE "
            "group. Graph connectivity is not regulatory connectedness: the "
            "group is formed from effective control and validated economic "
            "interdependence, and is a candidate for assessment under the "
            "institution's own approved criteria rather than a "
            "determination."),
        aliases=("group size", "connected group size", "obligor group size"),
        natural_grain="customer", unit="count", higher_is_worse=True,
        operations=(COUNT, RANK, COMPARE, DISTRIBUTION, MOVEMENT, WORST),
        forbidden=(
            (SUM, "Every member of a group carries the same size, so summing "
                  "over borrowers squares the group rather than counting "
                  "it."),
        ),
        period_behaviour=SNAPSHOT,
        calculation=("members of the weakly connected component over the "
                     "CONTROL graph, plus validated interdependence merges")),
    SemanticContract(
        concept_id="graph_confidence",
        business_name="Graph evidence confidence",
        definition=(
            "The confidence of the WEAKEST assertion on the evidence path "
            "behind a derived relationship. Not the average, which lets a "
            "long chain of registry filings hide one relationship manager's "
            "note, and not the product, which punishes length rather than "
            "weakness. A conclusion is exactly as good as the worst "
            "assertion it depends on."),
        aliases=("graph confidence", "evidence confidence",
                 "weakest evidence", "relationship confidence"),
        natural_grain="customer", unit="ratio", higher_is_worse=False,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "Confidences do not add. Two assertions each believed "
                  "70% do not make a relationship believed 140%, and the "
                  "total is not a quantity of evidence."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="min(confidence) over the evidence path",
        invariants=(
            Invariant("share_bounds",
                      "A confidence lies between 0 and 1.",
                      {"minimum": 0.0, "maximum": 1.0}),
        )),
    SemanticContract(
        concept_id="centrality",
        business_name="Network centrality",
        definition=(
            "A borrower's position in the exposure network. Forward PageRank "
            "ranks TRANSMITTERS - who others are exposed to; reverse "
            "PageRank ranks the exposed; betweenness ranks conduits. The "
            "three answer different questions and the direction is the thing "
            "most easily got backwards: a measure where forward and reverse "
            "agree has lost it. Centrality is structural position and "
            "nothing else - a central borrower is not thereby a large one, "
            "a weak one, or one whose default is more likely."),
        aliases=("centrality", "PageRank", "betweenness",
                 "network centrality", "network position"),
        natural_grain="customer", unit="ratio", higher_is_worse=True,
        is_ratio=True, operations=RATIO_OPS,
        forbidden=(
            (SUM, "PageRank over the whole population already sums to one. "
                  "Summing a subset is a share of the network, not a "
                  "quantity of risk."),
        ),
        period_behaviour=SNAPSHOT,
        calculation=("pagerank_transmits / pagerank_hurt / betweenness, from "
                     "the derived graph")),
    SemanticContract(
        concept_id="network_community",
        business_name="Network community",
        definition=(
            "A community found by modularity optimisation over the exposure "
            "network. Descriptive only: it is NOT a group in any legal, "
            "economic or regulatory sense and carries no claim about the "
            "borrowers in it. Its label is an arbitrary integer that is "
            "stable between runs and means nothing between quarters."),
        aliases=("network community", "cluster", "Louvain community"),
        natural_grain="customer", unit="", higher_is_worse=False,
        is_categorical=True, operations=CATEGORY_OPS,
        forbidden=(
            (SUM, "A community label is an identifier, not a quantity. "
                  "Adding two of them is a type error."),
            (AVERAGE, "The average of two community labels names a third "
                      "community that has nothing to do with either."),
        ),
        period_behaviour=SNAPSHOT,
        calculation="louvain_community, a label rather than a measure"),
)

_ALL: tuple[SemanticContract, ...] = (
    CONTRACTS + CONTRACTS_V2 + CONTRACTS_GRAPH + (STAGE_SHARE,))


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
    "CONTRACTS_GRAPH",
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
