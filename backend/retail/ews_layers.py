"""The six early-warning layers, and what sits under each of them.

The existing rulebook has eleven FAMILIES — REPAYMENT, CARD_BEHAVIOUR, INCOME,
AFFORDABILITY, SCORE, BUREAU, COLLECTIONS, FORBEARANCE, PRODUCT_STRUCTURE,
COLLATERAL and DATA_QUALITY. Eleven is the right number for somebody writing a
rule; it is the wrong number for somebody being shown a portfolio, because
"collections" and "repayment" are one story to a Head of Retail Risk and
"forbearance", "collateral" and "product structure" are another.

So the eleven families roll up into the six layers the business talks in. The
rules are untouched: this is a grouping over them, and every layer names the
families and the rules underneath it so a reader can get back down to the
signal that actually fired.

Cycle sensitivity
-----------------
The sixth layer has **no rules in this rulebook**, and that is said on the
screen rather than hidden by quietly showing five layers. Cycle sensitivity
would be scored from macroeconomic scenario sensitivity, and the retail book
carries scenario-weighted ECL but no per-customer cycle signal, so there is
nothing honest to put in it yet.

Everything here is synthetic demonstration material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Bumped when a layer's family membership or weight changes.
EWS_LAYERS_VERSION = "1.0.0"


@dataclass(frozen=True)
class Layer:
    """One of the six layers a portfolio view is organised by."""

    key: str
    name: str
    purpose: str
    #: The rulebook families that roll up into this layer.
    families: tuple[str, ...]
    #: Internal / External / Derived — what the layer's inputs actually are.
    source_class: str
    #: Share of the overall score. They sum to 1 across the layers that have
    #: rules; a layer with no rules carries no weight and says so.
    weight: float
    #: Why this layer is weighted the way it is.
    weight_because: str
    refresh: str = "Monthly, with the retail book."
    #: Empty means the rulebook has nothing under it yet.
    absent_because: str = ""

    @property
    def has_rules(self) -> bool:
        return not self.absent_because

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "purpose": self.purpose,
            "families": list(self.families), "source_class": self.source_class,
            "weight": self.weight, "weight_because": self.weight_because,
            "refresh": self.refresh, "has_rules": self.has_rules,
            "absent_because": self.absent_because,
        }


REPAYMENT = Layer(
    key="repayment",
    name="Repayment behaviour",
    purpose=(
        "Whether the customer is paying: arrears moving, payments missed, "
        "instalments part-paid, direct debits failing, promises broken. The "
        "layer that moves last and matters most."),
    families=("REPAYMENT", "COLLECTIONS"),
    source_class="Internal",
    weight=0.30,
    weight_because=(
        "Weighted highest because a missed payment is the least ambiguous "
        "signal in the book: it is an outcome rather than a proxy for one."),
)

AFFORDABILITY = Layer(
    key="affordability",
    name="Affordability & income",
    purpose=(
        "Whether the customer can still afford the facility: salary arriving "
        "on time and in full, verified income, debt burden, disposable income "
        "and the buffer behind it, and obligations taken on elsewhere."),
    families=("INCOME", "AFFORDABILITY"),
    source_class="Internal",
    weight=0.25,
    weight_because=(
        "Weighted second because salary interruption and affordability "
        "deterioration lead arrears by months on this book."),
)

SCORE_DYNAMICS = Layer(
    key="score",
    name="Score dynamics",
    purpose=(
        "What the behavioural scorecard says and, more importantly, which way "
        "it is moving. A level is a position; a fall is a warning."),
    families=("SCORE",),
    source_class="Derived",
    weight=0.20,
    weight_because=(
        "Weighted third: the behavioural score already summarises much of the "
        "two layers above, so weighting it equally would count the same "
        "evidence twice."),
)

FACILITY_STRUCTURE = Layer(
    key="structure",
    name="Facility structure",
    purpose=(
        "How the facility itself is built and used: card utilisation and cash "
        "advances, minimum-payment behaviour, collateral cover, balloon "
        "payments, and whether forbearance is already in place."),
    families=("CARD_BEHAVIOUR", "PRODUCT_STRUCTURE", "COLLATERAL",
              "FORBEARANCE"),
    source_class="Internal",
    weight=0.15,
    weight_because=(
        "Weighted fourth: structure changes how hard a deterioration lands "
        "rather than saying one is under way."),
)

BUREAU = Layer(
    key="bureau",
    name="Bureau & external signals",
    purpose=(
        "What is happening to the customer away from this bank: external "
        "arrears, enquiries, facilities elsewhere and the bureau score."),
    families=("BUREAU",),
    source_class="External",
    weight=0.10,
    weight_because=(
        "Weighted lowest of the scored layers because the bureau feed in this "
        "deployment is a synthetic proxy, not a live bureau connection."),
)

CYCLE = Layer(
    key="cycle",
    name="Cycle sensitivity",
    purpose=(
        "How exposed the customer is to the macroeconomic cycle — employment "
        "sector, income stability and scenario sensitivity."),
    families=(),
    source_class="Derived",
    weight=0.0,
    weight_because="Carries no weight, because it carries no rules.",
    absent_because=(
        "No rule in retail-ews-rulebook-1.0.0 scores cycle sensitivity. The "
        "book carries scenario-weighted ECL at facility level but no "
        "per-customer cycle signal, so there is nothing to score it from. The "
        "layer is shown empty rather than omitted, so the reader can see that "
        "six layers were intended and five are populated."),
)

LAYERS: tuple[Layer, ...] = (REPAYMENT, AFFORDABILITY, SCORE_DYNAMICS,
                             FACILITY_STRUCTURE, BUREAU, CYCLE)

#: Which layer each rulebook family rolls up into.
FAMILY_TO_LAYER: dict[str, str] = {
    family: layer.key for layer in LAYERS for family in layer.families
}

#: DATA_QUALITY is deliberately not a risk layer. A missing input is a
#: statement about the FILE, not about the customer, and folding it into a
#: risk score would let a broken feed read as a deteriorating borrower.
NOT_A_RISK_LAYER: tuple[str, ...] = ("DATA_QUALITY",)

#: Severity bands on the 0-100 overall score. Synthetic demonstration
#: thresholds, bank-configurable, not a policy.
BANDS: tuple[tuple[float, str], ...] = (
    (60.0, "CRITICAL"),
    (40.0, "HIGH"),
    (20.0, "MEDIUM"),
    (0.0, "LOW"),
)

#: Severity bands for a POPULATION — a product, a subsegment, the book.
#:
#: A population score and a customer score are different objects and cannot
#: share a band table. A customer at 60 has a CRITICAL signal firing on them.
#: A product at 60 would mean its average warned customer has a critical
#: signal, which no real book ever reaches: the four products on this book run
#: between 9 and 19, so against the customer bands all four read LOW for ever
#: and the severity badge says nothing at all.
#:
#: These bands are set where the arithmetic means something: a population at
#: 20 is one whose average warned customer carries about one HIGH signal, and
#: at 10 about one MEDIUM. Synthetic demonstration thresholds,
#: bank-configurable, not a policy.
POPULATION_BANDS: tuple[tuple[float, str], ...] = (
    (30.0, "CRITICAL"),
    (20.0, "HIGH"),
    (10.0, "MEDIUM"),
    (0.0, "LOW"),
)

#: What each rule's severity contributes to its layer's score before scaling.
SEVERITY_POINTS: dict[str, float] = {
    "CRITICAL": 100.0, "HIGH": 60.0, "MEDIUM": 30.0, "LOW": 10.0,
}

THRESHOLD_SOURCE = (
    "Synthetic demo threshold — bank-configurable, not an ANB or regulatory "
    "limit")


def band_of(score: float) -> str:
    """The severity band a CUSTOMER's 0-100 score falls in."""
    value = float(score or 0.0)
    return next(name for floor, name in BANDS if value >= floor)


def population_band_of(score: float) -> str:
    """The severity band a POPULATION's 0-100 score falls in.

    See POPULATION_BANDS: the customer scale is the wrong ruler for a product.
    """
    value = float(score or 0.0)
    return next(name for floor, name in POPULATION_BANDS if value >= floor)


def layer_of(family: str) -> str:
    """Which layer a rulebook family belongs to, or "" for none."""
    return FAMILY_TO_LAYER.get(str(family or "").upper(), "")


def get(key: str) -> Layer | None:
    return next((layer for layer in LAYERS if layer.key == key), None)


def scored() -> tuple[Layer, ...]:
    """The layers that actually carry rules."""
    return tuple(layer for layer in LAYERS if layer.has_rules)


# ------------------------------------------------------------- the glossary

@dataclass(frozen=True)
class Term:
    """One abbreviation or piece of shorthand, and what it means here."""

    term: str
    meaning: str
    #: Where the meaning comes from. An abbreviation nobody can source is
    #: replaced by its full label rather than given an invented expansion.
    authority: str


GLOSSARY: tuple[Term, ...] = (
    Term("DPD", "Days past due — how many days the oldest unpaid amount on "
                "the facility has been outstanding.",
         "backend/retail/schema.py, column `dpd`."),
    Term("EWS", "Early Warning Signal. In this deployment it means the "
                "governed rulebook `retail-ews-rulebook-1.0.0` and the layer "
                "scores rolled up from it.",
         "backend/retail/ews.py, RULEBOOK_VERSION."),
    Term("SICR", "Significant Increase in Credit Risk — the IFRS 9 test that "
                 "moves a facility from Stage 1 to Stage 2.",
         "backend/retail/schema.py, column `sicr_flag`."),
    Term("Stage 1 / 2 / 3",
         "IFRS 9 impairment stages: performing, significant increase in "
         "credit risk, and credit-impaired.",
         "backend/retail/schema.py, column `ifrs9_stage`."),
    Term("Current bad",
         "A customer who is ALREADY in trouble at this month-end: 30 or more "
         "days past due, or flagged in default, or in Stage 3. Not a "
         "prediction.",
         "Defined in backend/retail/ews_portfolio.py; stated on every screen "
         "that uses it."),
    Term("Forward risk",
         "A customer who is NOT currently bad and whose overall EWS score is "
         "in the HIGH or CRITICAL band. A prediction, from signals that have "
         "fired, about a customer who is still paying.",
         "Defined in backend/retail/ews_portfolio.py."),
    Term("Layer score",
         "0-100 for one layer for one customer: the severity-weighted sum of "
         "that layer's rules that fired, divided by the severity-weighted sum "
         "of every rule in that layer that COULD have fired for the "
         "customer's product, times 100.",
         "backend/retail/ews_portfolio.py."),
    Term("Overall EWS score",
         "0-100: the weight-weighted mean of the five scored layer scores. "
         "The weights are on the methodology page and sum to one.",
         "backend/retail/ews_layers.py, Layer.weight."),
    Term("Rulebook",
         "The versioned set of governed rules that produce alerts. This "
         "deployment runs retail-ews-rulebook-1.0.0.",
         "backend/retail/ews.py."),
    Term("Scope: facility / customer",
         "Whether a rule is evaluated on one facility's row or across all of "
         "a customer's facilities and collapsed to one alert.",
         "backend/retail/ews.py, FACILITY_SCOPE and CUSTOMER_SCOPE."),
)

#: Shorthand that appears in the product and MUST NOT be given an invented
#: expansion. Checked by a test: if any of these ever appear as a bare
#: one-letter label on an EWS screen, the screen is wrong.
#:
#: The overnight brief asked what "T", "A" and "C" mean. They were searched
#: for across the retail early-warning implementation — the rulebook, the
#: taxonomy, the schema, the forward signal and the screens — and they do not
#: exist as governed abbreviations anywhere in it. There is therefore no
#: authoritative meaning to show, and none has been invented. Every label in
#: the rebuilt EWS is written out in full.
UNSOURCED_SHORTHAND: tuple[str, ...] = ("T", "A", "C")

NO_SUCH_SHORTHAND = (
    "T, A and C are not governed abbreviations in this deployment's early "
    "warning implementation. They appear nowhere in the rulebook, the "
    "taxonomy, the retail schema or the forward-risk signal, so no meaning is "
    "shown for them and none has been invented. Every layer, rule and "
    "variable label in Early Warning is written out in full.")


def glossary() -> list[dict[str, str]]:
    return [{"term": t.term, "meaning": t.meaning, "authority": t.authority}
            for t in GLOSSARY]


def check() -> list[str]:
    """Every problem with the layer definitions, as sentences. Run by a test."""
    from backend.retail import ews

    problems: list[str] = []
    families = {r.family for r in ews.RULES}
    mapped = set(FAMILY_TO_LAYER) | set(NOT_A_RISK_LAYER)
    for family in sorted(families - mapped):
        problems.append(
            f"rulebook family {family!r} belongs to no layer, so its rules "
            "would be invisible on the portfolio view")
    for family in sorted(mapped - families - set(NOT_A_RISK_LAYER)):
        problems.append(
            f"layer family {family!r} is not a family any rule declares")
    total = round(sum(layer.weight for layer in scored()), 6)
    if total != 1.0:
        problems.append(f"the scored layer weights sum to {total}, not 1.0")
    for layer in LAYERS:
        if layer.has_rules and not layer.families:
            problems.append(f"{layer.name} claims rules but names no family")
        if not layer.has_rules and layer.weight:
            problems.append(
                f"{layer.name} has no rules but carries weight {layer.weight}")
    for name in sorted({f for r in ews.RULES for f in r.features}):
        if name not in VARIABLE_NOTES:
            problems.append(
                f"rule input {name!r} has no entry in VARIABLE_NOTES, so the "
                "methodology page would show it with no transformation and no "
                "direction of risk")
    return problems


# --------------------------------------------------------------------------
# The variable dictionary
#
# A methodology page that lists rules and stops there tells a credit officer
# WHAT fired and never WHAT IT READ. Every rule in the rulebook names its
# inputs, and each of those inputs is a column of the published book (or, in
# exactly one case, computed at evaluation time). What follows is the
# sentence the book itself cannot carry: how the raw column becomes the
# number the rule tests, and which way is worse.
#
# `business meaning`, the unit and the applicable products are NOT repeated
# here. They are read from `backend.retail.schema.spec_for`, so this file can
# never drift away from the dictionary the rest of the product uses.
# --------------------------------------------------------------------------

#: variable -> (source class, transformation, direction of risk)
#:
#: "As published" means the rule reads the column exactly as the book carries
#: it. Anything else names the arithmetic.
VARIABLE_NOTES: dict[str, tuple[str, str, str]] = {
    # --- repayment behaviour
    "dpd": ("Internal", "As published. Derived in the book from the oldest "
            "unpaid due date.", "Higher is worse."),
    "previous_month_dpd": ("Internal", "As published — the same measure at the "
            "previous month-end, carried on the row so a movement can be read "
            "without joining the book to itself.",
            "Read as a comparator: the rule tests the RISE against it."),
    "missed_payment_count_3m": ("Internal", "As published. A count over a "
            "three-month window ending at this month-end.", "Higher is worse."),
    "months_on_book": ("Internal", "As published. Whole months from "
            "origination.", "Lower is worse when a payment has been missed: an "
            "early-life failure says the underwriting was wrong, not that "
            "circumstances changed."),
    "broken_promise_count_3m": ("Internal", "As published. A count over three "
            "months of promises made to collections and not kept.",
            "Higher is worse."),
    "autopay_failure_count_3m": ("Internal", "As published. A count over three "
            "months of direct-debit attempts that were returned.",
            "Higher is worse."),
    # --- affordability and income
    "debt_burden_ratio": ("Derived", "Total monthly credit obligations over "
            "verified total monthly income, at this month-end.",
            "Higher is worse."),
    "previous_month_debt_burden_ratio": ("Derived", "The same ratio one month "
            "earlier. NOT a published column: it is computed at evaluation "
            "from the previous month's partition by "
            "`backend.retail.ews.with_prior_month`, and is null in the first "
            "published month.",
            "Read as a comparator: the rule tests the RISE against it."),
    "balance_buffer_months": ("Derived", "Average account balance over the "
            "scheduled monthly instalment.", "Lower is worse."),
    "salary_change_3m_ratio": ("Derived", "The latest salary credit over the "
            "mean of the three before it.",
            "Lower is worse. Below 1 means income fell."),
    "salary_missed_cycle_count_3m": ("Internal", "As published. Salary cycles "
            "in the last three months with no credit at all.",
            "Higher is worse."),
    "salary_credit_last_date": ("Internal", "As published. Compared against "
            "the scoring month-end to give months since the last credit.",
            "Further in the past is worse."),
    "external_obligations_change_3m_sar": ("Internal", "Change over three "
            "months in verified monthly obligations to OTHER lenders. Already "
            "a difference; do not difference it again.",
            "Higher is worse: the customer is borrowing elsewhere."),
    # --- score dynamics
    "beh_score_value": ("Derived", "The behavioural scorecard's output at this "
            "month-end, after clipping to the scorecard's range.",
            "Lower is worse."),
    "behavioural_score_previous_month": ("Derived", "The same score one month "
            "earlier, carried on the row.",
            "Read as a comparator: the rule tests the FALL against it."),
    # --- facility structure
    "utilisation_ratio": ("Internal", "Drawn balance over current credit "
            "limit. Card only — an amortising loan has no utilisation, and the "
            "column is null rather than zero for every other product.",
            "Higher is worse."),
    "utilisation_change_3m_pp": ("Derived", "Change in utilisation over three "
            "months, in percentage points. Already a difference.",
            "Higher is worse."),
    "overlimit_days_3m": ("Internal", "As published. Days spent above the "
            "credit limit in the last three months.", "Higher is worse."),
    "cash_advance_share_3m": ("Derived", "Cash advances over total card spend "
            "across three months.",
            "Higher is worse: cash advance on a card is expensive money taken "
            "by someone who has run out of cheaper money."),
    "minimum_payment_only_months_3m": ("Internal", "As published. Months in "
            "the last three where only the contractual minimum was paid.",
            "Higher is worse."),
    "forbearance_flag": ("Internal", "As published. True where a concession "
            "has been granted because of financial difficulty.",
            "True is worse — and worse again alongside arrears, which is what "
            "the rule tests."),
    "months_to_balloon": ("Derived", "Months from this month-end to the date "
            "the balloon instalment falls due.",
            "Fewer is worse when the buffer is thin."),
    "ltv_current_ratio": ("Derived", "Current balance over the collateral's "
            "value at origination.", "Higher is worse."),
    "ltv_origination_ratio": ("Derived", "Amount financed over collateral "
            "value at origination. Fixed for the life of the facility.",
            "Read as a comparator: the rule tests whether the CURRENT ratio "
            "has failed to fall away from it."),
    # --- bureau and external
    "bureau_score_current": ("External", "As supplied. In this deployment the "
            "bureau inputs are a SYNTHETIC PROXY generated with the rest of "
            "the demonstration book — there is no live bureau connection.",
            "Lower is worse."),
    "bureau_score_change_3m": ("External", "Change in the bureau score over "
            "three months. Already a difference. Same synthetic proxy as "
            "above.", "Lower is worse: a falling bureau score."),
    # --- data quality. Not a risk layer: see NOT_A_RISK_LAYER above.
    "beh_input_missing_count": ("Derived", "A count of the behavioural "
            "scorecard's inputs that were null for this facility this month.",
            "Higher means the FILE is worse, not the customer. It carries no "
            "risk weight and rolls up into no layer."),
}

#: How often each source class is refreshed in this deployment.
REFRESH: dict[str, str] = {
    "Internal": "Monthly, with the publication of the retail book.",
    "External": "Monthly, with the retail book. The bureau proxy is generated "
                "alongside it; there is no independent bureau refresh.",
    "Derived": "Monthly, recomputed from that month's book at evaluation.",
}


def variables() -> list[dict[str, object]]:
    """Every input the rulebook reads, with the ten facts §9 asks for.

    Built by walking the rules rather than by hand, so a rule that starts
    reading a new column cannot leave the methodology page behind. The
    business meaning, unit and applicable products come from
    `schema.spec_for`; only the transformation, the direction of risk and the
    source class are stated here.
    """
    from backend.retail import ews, schema

    used: dict[str, list[Any]] = {}
    for rule in ews.RULES:
        for name in rule.features:
            used.setdefault(name, []).append(rule)

    out: list[dict[str, object]] = []
    for name in sorted(used):
        rules = used[name]
        spec = schema.spec_for(name)
        source, transformation, direction = VARIABLE_NOTES.get(
            name, ("Derived", "Not documented.", "Not documented."))
        layers = sorted({layer_of(r.family) for r in rules} - {""})
        products = sorted({p for r in rules for p in r.products})
        # Each layer's own weight, not their sum. `dpd` feeds two layers, and
        # "45% of the overall score" reads as though reading one column
        # accounted for nearly half of it. It accounts for part of 30% and
        # part of 15%, which is what the two numbers say.
        per_layer = [{"layer": key,
                      "name": get(key).name if get(key) else key,
                      "weight": get(key).weight if get(key) else 0.0}
                     for key in layers]
        weight = round(sum(one["weight"] for one in per_layer), 4)
        out.append({
            "name": name,
            "label": spec.business_name,
            "meaning": spec.definition,
            "unit": spec.unit,
            "source_class": source,
            "raw_input": (
                "Computed at evaluation, not a column of the published book."
                if name in ews.DERIVED_FEATURES
                else f"`{name}` in the published retail book "
                     f"(`retail_facility_month`)."),
            "transformation": transformation,
            "direction": direction,
            "refresh": REFRESH.get(source, REFRESH["Derived"]),
            "products": products,
            "layers": layers,
            "layer_names": [get(k).name for k in layers if get(k)],
            "layer_weights": per_layer,
            "layer_weight": weight,
            "rules": [r.rule_id for r in rules],
            "rule_names": [r.name for r in rules],
            "reason_codes": sorted({r.rule_id for r in rules}),
        })
    return out
