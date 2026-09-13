"""
The Retail Early Warning Score model, configured in exactly one place.

What this replaces
------------------
The previous implementation carried SIX layers over the rulebook's eleven
families, and the methodology text lived partly here, partly in the router and
partly in three frontend files. The agreed model has FOUR layers, a classifier
/ trigger separation inside each of them, and six action dimensions on every
dynamic trigger. Nothing about that can be expressed as a family name, so the
family roll-up is replaced rather than renamed.

    Retail Early Warning Score
      ├── Behavioural Intelligence
      ├── Affordability & Cash Flow Intelligence
      ├── Bureau & External Credit Intelligence
      └── Facility & Exposure Intelligence

Everything the product says about the model comes from this module: layer and
sublayer names, classifier and trigger variables, weights, the product weight
matrix, the score scale, the warning cutoff, the severity thresholds, the hard
triggers, the sub-product taxonomy and the bureau observation rule. The API
serves it, the scoring engine reads it, and the screens render what the API
served. There is no second copy to drift.

Classifier, trigger, action
---------------------------
A CLASSIFIER is stable context: what kind of facility this is, which segment
the customer sits in, what their baseline looks like. It sets the interpretation
and, on its own, raises nothing.

A TRIGGER is a live deterioration event measured against this month's book.

Every dynamic trigger carries six ACTION DIMENSIONS, computed over the history
rather than asserted: direction, magnitude, velocity, momentum, persistence and
recency. They are what turn "this fired" into "this is getting worse, quickly,
and has been for four months".

Bureau
------
The bank does not receive a bureau file every month. The demonstration book
stamps `bureau_score_current_date` with each month-end, which would let a naive
reader plot a monthly bureau trend that no bank could produce. The rule below
replaces that with dated observations — origination, a per-customer cadence,
and a pull on entry to delinquency — and between them the last observed value
is carried forward unchanged. Bureau is therefore a CLASSIFIER layer with a
recency sublayer, and its triggers fire only in a month that actually holds a
new observation.

Everything here is SYNTHETIC demonstration configuration. No weight, threshold,
band or cadence below is an ANB policy, an ANB model or a SAMA requirement, and
none of it has been independently validated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Bumped when any layer, sublayer, trigger, weight or threshold changes.
EWS_MODEL_VERSION = "2.0.0"

MODEL_NAME = "Retail Early Warning Score"

PURPOSE = (
    "To identify retail customers whose position is deteriorating before it "
    "reaches arrears, and to separate those who are already in trouble from "
    "those who are still paying and are likely to deteriorate.")

TARGET = (
    "Deterioration in the customer's credit position over the next reporting "
    "months, evidenced by governed triggers rather than by a fitted "
    "probability. The score ranks and explains; it does not claim a "
    "calibrated default probability.")

HORIZON = (
    "One to three reporting months. Every trigger is evaluated at a month-end "
    "against that month's book and the months behind it.")

ELIGIBLE_POPULATION = (
    "Every open retail facility in the published book at the scoring month, "
    "and every customer holding one.")

SCORING_FREQUENCY = "Monthly, at each published month-end."

DISCLAIMER = (
    "Synthetic Saudi retail demonstration model and data. Not an ANB model, "
    "not an ANB policy, not a SAMA requirement, and not independently "
    "validated. No credit decision should rest on it.")


# ---------------------------------------------------------------- the scale

@dataclass(frozen=True)
class Scale:
    """The score's range and what its direction MEANS.

    Written down because a score whose direction is assumed is a score two
    screens will eventually read opposite ways.
    """

    minimum: float = 0.0
    maximum: float = 100.0
    direction: str = "Higher is worse. 0 is a customer with nothing firing."
    #: At or above this, the customer carries a warning.
    warning_cutoff: float = 20.0


SCALE = Scale()

#: Customer severity bands, worst first. Synthetic demonstration thresholds,
#: bank-configurable, not a policy.
SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (70.0, "CRITICAL"),
    (45.0, "HIGH"),
    (20.0, "MEDIUM"),
    (0.0, "LOW"),
)

#: Population severity bands — a product, a sub-product, the book.
#:
#: A population score and a customer score are different objects and cannot
#: share a band table. A customer at 70 has several critical triggers firing.
#: A product at 70 would mean its average warned customer does, which no real
#: book reaches. These are set where the arithmetic means something.
#: Set where this book's arithmetic actually lands. A population score is the
#: exposure-weighted mean over EVERY customer in the population, so it carries
#: both how many are warned and how badly; on this book the four products run
#: between 14.0 and 17.1 and the twelve sub-products between 11.7 and 17.6.
#: Bands set on the customer table would put all sixteen in the bottom one and
#: the badge would say nothing at all.
POPULATION_BANDS: tuple[tuple[float, str], ...] = (
    (30.0, "CRITICAL"),
    (22.0, "HIGH"),
    (15.0, "MEDIUM"),
    (0.0, "LOW"),
)

#: What a trigger's severity contributes before the action dimensions scale it.
#:
#: CRITICAL is 85 rather than 100 deliberately, and no single trigger may
#: contribute more than TRIGGER_CONTRIBUTION_CAP. With CRITICAL at 100 a lone
#: early-life payment failure carried a customer to exactly 100.0 — the top of
#: the scale — and 126 customers sat pinned there with no ordering between
#: them. The top of the scale has to be reachable only by a customer with
#: several things wrong.
SEVERITY_POINTS: dict[str, float] = {
    "CRITICAL": 85.0, "HIGH": 60.0, "MEDIUM": 35.0, "LOW": 12.0,
}

#: The most any ONE trigger can contribute to its sublayer, after the action
#: dimensions have scaled it.
TRIGGER_CONTRIBUTION_CAP = 90.0

THRESHOLD_SOURCE = (
    "Synthetic demo threshold — bank-configurable, not an ANB or regulatory "
    "limit")


@dataclass(frozen=True)
class HardTrigger:
    """A condition that floors the score regardless of the weighted roll-up.

    A customer ninety days down is not a MEDIUM because their other three
    layers are quiet. These are the only places where the arithmetic is
    overridden, and each one says so on the customer's own page.
    """

    key: str
    name: str
    condition: str
    floor_score: float
    band: str
    because: str


HARD_TRIGGERS: tuple[HardTrigger, ...] = (
    # The two severity floors come first so that a stronger override below
    # takes the label when both apply.
    HardTrigger(
        key="high_trigger_floor",
        name="A high-severity trigger fired",
        condition="any trigger of severity HIGH fired",
        floor_score=SCALE.warning_cutoff,
        band="MEDIUM",
        because="The Bureau and Facility layers carry fifteen per cent each, "
                "so a lone trigger inside either one cannot arithmetically "
                "reach the warning cutoff however serious it is. A new "
                "external delinquency scored thirteen and never appeared on "
                "a warning list. A high-severity trigger means the customer "
                "is to be looked at, and the score has to say so."),
    HardTrigger(
        key="critical_trigger_floor",
        name="A critical trigger fired",
        condition="any trigger of severity CRITICAL fired",
        floor_score=45.0,
        band="HIGH",
        because="Same arithmetic, one band higher: a critical observation in "
                "a lightly weighted layer is still a critical observation."),
    HardTrigger(
        key="dpd_90",
        name="Ninety or more days past due",
        condition="dpd >= 90",
        floor_score=85.0,
        band="CRITICAL",
        because="At ninety days the deterioration has already happened. No "
                "combination of quiet layers should be able to report it as "
                "anything but critical."),
    HardTrigger(
        key="stage_3",
        name="IFRS 9 Stage 3",
        condition="ifrs9_stage >= 3",
        floor_score=80.0,
        band="CRITICAL",
        because="Credit-impaired under the bank's own impairment policy."),
    HardTrigger(
        key="default_entry",
        name="Entered default this month",
        condition="default_entry_this_month",
        floor_score=80.0,
        band="CRITICAL",
        because="The event the whole system exists to anticipate has "
                "occurred; the score must not read below it."),
    HardTrigger(
        key="forbearance_arrears",
        name="Forbearance with arrears",
        condition="forbearance_flag AND dpd >= 30",
        floor_score=70.0,
        band="CRITICAL",
        because="A concession was granted and the customer fell behind "
                "anyway, which is the clearest evidence a restructure has "
                "not worked."),
)


# ------------------------------------------------------- action dimensions

@dataclass(frozen=True)
class ActionDimension:
    key: str
    name: str
    meaning: str
    computed: str
    values: str


ACTION_DIMENSIONS: tuple[ActionDimension, ...] = (
    ActionDimension(
        key="direction", name="Direction",
        meaning="Whether the underlying measure is improving, stable or "
                "deteriorating.",
        computed="The sign of this month's value against last month's, on the "
                 "trigger's own direction of risk. A measure where lower is "
                 "worse deteriorates when it falls.",
        values="IMPROVING | STABLE | DETERIORATING"),
    ActionDimension(
        key="magnitude", name="Magnitude",
        meaning="How big this month's move is, relative to the trigger's "
                "threshold.",
        computed="The absolute one-month change over the trigger's threshold, "
                 "capped at 3. A move of exactly the threshold is 1.0.",
        values="0.0 – 3.0"),
    ActionDimension(
        key="velocity", name="Velocity",
        meaning="How fast the measure is moving.",
        computed="The mean monthly change over the last three months, in the "
                 "measure's own unit.",
        values="Signed, in the variable's unit per month"),
    ActionDimension(
        key="momentum", name="Momentum",
        meaning="Whether the deterioration is accelerating or slowing.",
        computed="This month's change less the mean change of the two months "
                 "before it. Positive on a worsening measure means it is "
                 "getting worse faster.",
        values="ACCELERATING | STEADY | DECELERATING"),
    ActionDimension(
        key="persistence", name="Persistence",
        meaning="How long the trigger has been firing without a break.",
        computed="Consecutive months the trigger has fired, counting back "
                 "from this month.",
        values="0 – 20 months"),
    ActionDimension(
        key="recency", name="Recency",
        meaning="How recently the relevant observation was made.",
        computed="Months since the observation the trigger reads. Zero for a "
                 "measure refreshed with this month's book; for bureau it is "
                 "months since the last dated pull.",
        values="0 – 24 months"),
)

#: How the action dimensions scale a fired trigger's severity points.
#:
#: A trigger that fired once, mildly, and is already improving is not the same
#: finding as one that has fired for six months and is accelerating. The
#: multiplier is bounded so a single dimension cannot dominate, and it can
#: only ever reduce a fired trigger to half its severity or raise it to
#: one and a half times.
ACTION_WEIGHTS: dict[str, float] = {
    "direction": 0.20,
    "magnitude": 0.20,
    "velocity": 0.10,
    "momentum": 0.15,
    "persistence": 0.25,
    "recency": 0.10,
}

ACTION_MULTIPLIER_FLOOR = 0.5
ACTION_MULTIPLIER_CEILING = 1.5


# -------------------------------------------------- classifiers and triggers

@dataclass(frozen=True)
class Classifier:
    """Stable context. It interprets triggers; it does not fire."""

    key: str
    name: str
    column: str
    meaning: str
    source_class: str = "Internal"
    products: tuple[str, ...] = ()
    #: Set where the book does not carry the field and the model says so
    #: rather than inventing it.
    absent_because: str = ""


@dataclass(frozen=True)
class Trigger:
    """A live deterioration event, with its own threshold and reason code."""

    key: str
    name: str
    #: The column the trigger measures, and the one it compares against.
    column: str
    comparator: str
    #: "rise" | "fall" | "level" | "flag" | "ratio_fall"
    test: str
    threshold: float
    unit: str
    severity: str
    meaning: str
    reason_code: str
    reason_template: str
    recommended_review: str
    products: tuple[str, ...] = ()
    source_class: str = "Internal"
    #: Non-empty where this trigger continues a governed rulebook rule, so the
    #: two can never drift apart and the rule detail screen still resolves.
    rule_id: str = ""
    #: A trigger the book cannot support says so instead of being dropped.
    absent_because: str = ""
    #: False for the bureau triggers, which fire only in an observation month.
    needs_new_observation: bool = False

    @property
    def dynamic(self) -> bool:
        return not self.absent_because


@dataclass(frozen=True)
class Sublayer:
    key: str
    name: str
    purpose: str
    weight: float
    classifiers: tuple[Classifier, ...] = ()
    triggers: tuple[Trigger, ...] = ()

    @property
    def score_column(self) -> str:
        return f"sub_{self.key}_score"


@dataclass(frozen=True)
class Layer:
    key: str
    name: str
    purpose: str
    kind: str  # "dynamic" | "classifier"
    weight: float
    weight_because: str
    refresh: str
    sublayers: tuple[Sublayer, ...] = ()

    @property
    def score_column(self) -> str:
        # Prefixed. Unprefixed, the behavioural LAYER score is
        # `behavioural_score` — which is the name the published book already
        # uses for the behavioural SCORECARD's output, so the layer silently
        # overwrote it and every customer card showed their layer score where
        # their behavioural score belonged.
        return f"layer_{self.key}_score"

    def to_dict(self, *, deep: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "key": self.key,
            "name": self.name,
            "purpose": self.purpose,
            "kind": self.kind,
            "weight": self.weight,
            "weight_because": self.weight_because,
            "refresh": self.refresh,
            "score_column": self.score_column,
            "sublayer_count": len(self.sublayers),
            "classifier_count": sum(len(s.classifiers) for s in self.sublayers),
            "trigger_count": sum(len(s.triggers) for s in self.sublayers),
        }
        if deep:
            out["sublayers"] = [_sublayer_dict(s) for s in self.sublayers]
        return out


def _classifier_dict(one: Classifier) -> dict[str, Any]:
    return {
        "key": one.key, "name": one.name, "column": one.column,
        "meaning": one.meaning, "source_class": one.source_class,
        "products": list(one.products) or list(ALL_PRODUCTS),
        "absent_because": one.absent_because,
        "available": not one.absent_because,
    }


def _trigger_dict(one: Trigger) -> dict[str, Any]:
    return {
        "key": one.key, "name": one.name, "column": one.column,
        "comparator": one.comparator, "test": one.test,
        "threshold": one.threshold, "unit": one.unit,
        "severity": one.severity, "meaning": one.meaning,
        "reason_code": one.reason_code,
        "reason_template": one.reason_template,
        "recommended_review": one.recommended_review,
        "products": list(one.products) or list(ALL_PRODUCTS),
        "source_class": one.source_class,
        "rule_id": one.rule_id,
        "threshold_source": THRESHOLD_SOURCE,
        "absent_because": one.absent_because,
        "available": not one.absent_because,
        "needs_new_observation": one.needs_new_observation,
        "expression": _expression(one),
    }


def _sublayer_dict(one: Sublayer) -> dict[str, Any]:
    return {
        "key": one.key, "name": one.name, "purpose": one.purpose,
        "weight": one.weight, "score_column": one.score_column,
        "classifiers": [_classifier_dict(c) for c in one.classifiers],
        "triggers": [_trigger_dict(t) for t in one.triggers],
    }


def _expression(one: Trigger) -> str:
    """The trigger as a readable condition, generated from its own fields."""
    if one.absent_because:
        return "not evaluated"
    if one.test == "flag":
        return f"{one.column} is true"
    if one.test == "rise":
        return (f"{one.column} - {one.comparator} >= {one.threshold:g}"
                if one.comparator else f"{one.column} >= {one.threshold:g}")
    if one.test == "fall":
        return (f"{one.comparator} - {one.column} >= {one.threshold:g}"
                if one.comparator else f"{one.column} <= {one.threshold:g}")
    if one.test == "ratio_fall":
        return f"{one.column} <= {one.threshold:g}"
    if one.test == "below":
        return f"{one.column} <= {one.threshold:g}"
    return f"{one.column} >= {one.threshold:g}"


CREDIT_CARD = "CREDIT_CARD"
PERSONAL_LOAN = "PERSONAL_LOAN"
AUTO_LOAN = "AUTO_LOAN"
HOME_LOAN = "HOME_LOAN"
ALL_PRODUCTS: tuple[str, ...] = (CREDIT_CARD, PERSONAL_LOAN, AUTO_LOAN,
                                 HOME_LOAN)
SECURED: tuple[str, ...] = (AUTO_LOAN, HOME_LOAN)


# ================================================================= LAYER 1
# Behavioural Intelligence
# =========================================================================

BEHAVIOURAL = Layer(
    key="behavioural",
    name="Behavioural Intelligence",
    purpose=(
        "Whether the customer is paying, and how they are using the facility: "
        "arrears moving, payments missed, direct debits failing, promises "
        "broken, a card revolving harder, a behavioural score falling. The "
        "layer that speaks last and matters most, because a missed payment is "
        "an outcome rather than a proxy for one."),
    kind="dynamic",
    weight=0.40,
    weight_because=(
        "Weighted highest because its triggers are the least ambiguous "
        "evidence in the book: the customer either paid or did not."),
    refresh="Monthly, with the retail book.",
    sublayers=(
        Sublayer(
            key="delinquency",
            name="Delinquency",
            purpose="Where the arrears are now and which way they are going.",
            weight=0.40,
            classifiers=(
                Classifier("dpd_bucket", "Delinquency bucket", "dpd_bucket",
                           "The customer's arrears band at this month-end, as "
                           "the book publishes it."),
                Classifier("months_on_book", "Months on book",
                           "months_on_book",
                           "Whole months since origination. An early-life "
                           "failure is read differently from a failure in "
                           "year four."),
                Classifier("vintage", "Origination vintage",
                           "origination_vintage",
                           "The cohort the facility was written in."),
            ),
            triggers=(
                Trigger(
                    key="dpd_worsening", name="Delinquency bucket worsening",
                    column="dpd", comparator="previous_month_dpd",
                    test="rise", threshold=25.0, unit="days", severity="HIGH",
                    meaning="Days past due rose materially in one month and "
                            "the facility is now thirty days down or worse.",
                    reason_code="RET-EWS-001",
                    reason_template="Days past due rose from {comparator:.0f} "
                                    "to {value:.0f} in one month.",
                    recommended_review="Confirm the arrears position and the "
                                       "collections action already taken.",
                    rule_id="RET-EWS-001"),
                Trigger(
                    key="early_life_failure", name="Early-life payment failure",
                    column="missed_payment_count_3m",
                    comparator="months_on_book",
                    test="level", threshold=1.0, unit="count",
                    severity="CRITICAL",
                    meaning="A payment was missed within the first six months "
                            "on book, which says the underwriting was wrong "
                            "rather than that circumstances changed.",
                    reason_code="RET-EWS-003",
                    reason_template="A payment was missed within the first "
                                    "six months on book ({comparator:.0f} "
                                    "months on book, {value:.0f} missed).",
                    recommended_review="Check the origination file: "
                                       "affordability evidence, income "
                                       "verification and any exception.",
                    rule_id="RET-EWS-003"),
                Trigger(
                    key="delinquency_recurrence",
                    name="Delinquency recurrence",
                    column="max_dpd_6m", comparator="dpd",
                    test="level", threshold=30.0, unit="days",
                    severity="MEDIUM",
                    meaning="The facility has been thirty days down inside "
                            "six months and is current again: a cure that "
                            "may not hold.",
                    reason_code="RET-EWS-021",
                    reason_template="Reached {value:.0f} days past due within "
                                    "six months and is current again.",
                    recommended_review="Check whether the cure was a payment "
                                       "or a concession."),
            )),
        Sublayer(
            key="payment_performance",
            name="Payment Performance",
            purpose="Whether the scheduled payment is arriving at all.",
            weight=0.30,
            classifiers=(
                Classifier("payment_to_due", "Payment to amount due",
                           "payment_to_due_ratio_1m",
                           "What share of the amount due was actually paid "
                           "this month. One is paid in full; a part-payment "
                           "is read differently from a miss."),
                Classifier("full_payment_months", "Months paid in full",
                           "full_payment_months_6m",
                           "How many of the last six months were settled in "
                           "full. The baseline a missed payment is read "
                           "against."),
            ),
            triggers=(
                Trigger(
                    key="missed_payments", name="Consecutive missed payments",
                    column="missed_payment_count_3m", comparator="",
                    test="level", threshold=2.0, unit="count", severity="HIGH",
                    meaning="Two or more scheduled payments missed in three "
                            "months.",
                    reason_code="RET-EWS-002",
                    reason_template="{value:.0f} scheduled payments missed in "
                                    "the last three months.",
                    recommended_review="Review affordability and whether a "
                                       "restructure is warranted.",
                    rule_id="RET-EWS-002"),
                Trigger(
                    key="broken_promises", name="Broken promises to pay",
                    column="broken_promise_count_3m", comparator="",
                    test="level", threshold=2.0, unit="count", severity="HIGH",
                    meaning="Promises made to collections and not kept. The "
                            "customer engaged and still did not pay.",
                    reason_code="RET-EWS-016",
                    reason_template="{value:.0f} promises to pay were not "
                                    "honoured in three months.",
                    recommended_review="Escalate the collections approach; "
                                       "repeated broken promises rarely "
                                       "self-correct.",
                    rule_id="RET-EWS-016"),
                Trigger(
                    key="autopay_failure", name="Repeated direct-debit failure",
                    column="autopay_failure_count_3m", comparator="",
                    test="level", threshold=2.0, unit="count",
                    severity="MEDIUM",
                    meaning="Automatic payment attempts returned unpaid, "
                            "which usually means the account is empty on the "
                            "due date.",
                    reason_code="RET-EWS-017",
                    reason_template="{value:.0f} direct-debit attempts were "
                                    "returned in three months.",
                    recommended_review="Check the funding account and the "
                                       "salary credit date against the "
                                       "instalment date.",
                    rule_id="RET-EWS-017"),
                Trigger(
                    key="returned_payments", name="Returned payments",
                    column="returned_payment_count_3m", comparator="",
                    test="level", threshold=2.0, unit="count",
                    severity="MEDIUM",
                    meaning="Payments presented and returned unpaid.",
                    reason_code="RET-EWS-022",
                    reason_template="{value:.0f} payments were returned "
                                    "unpaid in three months.",
                    recommended_review="Check the funding arrangement."),
                Trigger(
                    key="partial_payments", name="Partial payments",
                    column="partial_payment_count_3m", comparator="",
                    test="level", threshold=2.0, unit="count",
                    severity="MEDIUM",
                    meaning="Instalments part-paid rather than missed.",
                    reason_code="RET-EWS-023",
                    reason_template="{value:.0f} instalments part-paid in "
                                    "three months.",
                    recommended_review="Review affordability.",
                    absent_because=(
                        "The published book records missed and returned "
                        "payments but not part-payments, so this trigger is "
                        "declared and never evaluated rather than approximated "
                        "from another column.")),
            )),
        Sublayer(
            key="utilisation",
            name="Utilisation and Usage",
            purpose="How hard a revolving facility is being used, and on what.",
            weight=0.15,
            classifiers=(
                Classifier("card_segment", "Card behaviour segment",
                           "card_behaviour_segment",
                           "Transactor, revolver or inactive. A revolver at "
                           "eighty per cent utilisation is normal; a "
                           "transactor at eighty per cent is not.",
                           products=(CREDIT_CARD,)),
                Classifier("utilisation_band", "Utilisation band",
                           "utilisation_band",
                           "The facility's drawn share of its limit, banded.",
                           products=(CREDIT_CARD,)),
                Classifier("revolving", "Revolving or amortising",
                           "product_code",
                           "Whether the facility revolves. An amortising loan "
                           "has no utilisation and this sublayer scores zero "
                           "for it."),
            ),
            triggers=(
                Trigger(
                    key="minimum_payment", name="Persistent minimum payment",
                    column="minimum_payment_only_months_3m", comparator="",
                    test="level", threshold=3.0, unit="count",
                    severity="MEDIUM",
                    meaning="Only the contractual minimum paid, every month, "
                            "for three months.",
                    reason_code="RET-EWS-004",
                    reason_template="Only the minimum payment was made in "
                                    "{value:.0f} of the last three months.",
                    recommended_review="Review the customer's wider "
                                       "affordability.",
                    products=(CREDIT_CARD,), rule_id="RET-EWS-004"),
                Trigger(
                    key="utilisation_spike", name="Rising card utilisation",
                    column="utilisation_change_3m_pp", comparator="",
                    test="level", threshold=20.0, unit="percentage points",
                    severity="MEDIUM",
                    meaning="Utilisation climbed sharply over three months.",
                    reason_code="RET-EWS-005",
                    reason_template="Utilisation rose {value:.0f} percentage "
                                    "points over three months.",
                    recommended_review="Check what the balance was spent on "
                                       "and whether the limit is still "
                                       "appropriate.",
                    products=(CREDIT_CARD,), rule_id="RET-EWS-005"),
                Trigger(
                    key="overlimit", name="Over-limit activity",
                    column="overlimit_days_3m", comparator="",
                    test="level", threshold=1.0, unit="days",
                    severity="MEDIUM",
                    meaning="Days spent above the credit limit.",
                    reason_code="RET-EWS-006",
                    reason_template="{value:.0f} day(s) above the credit "
                                    "limit in three months.",
                    recommended_review="Confirm the limit and the excess "
                                       "authorisation.",
                    products=(CREDIT_CARD,), rule_id="RET-EWS-006"),
                Trigger(
                    key="cash_advance", name="Rising cash advances",
                    column="cash_advance_share_3m", comparator="",
                    test="level", threshold=0.25, unit="ratio",
                    severity="MEDIUM",
                    meaning="Cash advance is expensive money taken by "
                            "somebody who has run out of cheaper money.",
                    reason_code="RET-EWS-007",
                    reason_template="Cash advances were "
                                    "{value:.0%} of card spend over three "
                                    "months.",
                    recommended_review="Review the customer's liquidity.",
                    products=(CREDIT_CARD,), rule_id="RET-EWS-007"),
            )),
        Sublayer(
            key="behavioural_dynamics",
            name="Behavioural Score Dynamics",
            purpose="What the bank's own behavioural scorecard is saying.",
            weight=0.15,
            classifiers=(
                Classifier("behavioural_band", "Behavioural score band",
                           "behavioural_score_band",
                           "The customer's behavioural grade this month."),
                Classifier("application_band", "Application score band",
                           "application_score_band",
                           "What the customer scored at origination. The "
                           "baseline a behavioural move is read against."),
            ),
            triggers=(
                Trigger(
                    key="behavioural_fall",
                    name="Behavioural score deterioration",
                    column="behavioural_score",
                    comparator="behavioural_score_previous_month",
                    test="fall", threshold=40.0, unit="points",
                    severity="MEDIUM",
                    meaning="The bank's own behavioural score fell materially "
                            "in one month.",
                    reason_code="RET-EWS-013",
                    reason_template="Behavioural score fell from "
                                    "{comparator:.0f} to {value:.0f}.",
                    recommended_review="Read the scorecard's own reason codes "
                                       "beside this.",
                    source_class="Derived", rule_id="RET-EWS-013"),
                Trigger(
                    key="band_migration", name="Score-band migration",
                    column="behavioural_score_band",
                    comparator="behavioural_score_band_previous",
                    test="flag", threshold=1.0, unit="band",
                    severity="MEDIUM",
                    meaning="The customer moved down a behavioural grade.",
                    reason_code="RET-EWS-024",
                    reason_template="Behavioural grade moved down from "
                                    "{comparator} to {value}.",
                    recommended_review="Check which inputs moved the grade.",
                    source_class="Derived"),
            )),
    ),
)


# ================================================================= LAYER 2
# Affordability & Cash Flow Intelligence
# =========================================================================

AFFORDABILITY = Layer(
    key="affordability",
    name="Affordability & Cash Flow Intelligence",
    purpose=(
        "Whether the customer can still afford what they owe: salary arriving "
        "on time and in full, obligations rising, the buffer between income "
        "and instalment thinning. It moves before the repayment layer does, "
        "which is what makes it worth watching."),
    kind="dynamic",
    weight=0.30,
    weight_because=(
        "Weighted second because it is the earliest honest evidence in the "
        "book: a salary that stops arriving precedes a missed instalment by a "
        "month or two."),
    refresh="Monthly, with the retail book.",
    sublayers=(
        Sublayer(
            key="income_stability",
            name="Income Stability",
            purpose="Whether verified income is holding up.",
            weight=0.25,
            classifiers=(
                Classifier("employment_status", "Employment status",
                           "employment_status",
                           "Salaried, self-employed or otherwise. The shape "
                           "of an income interruption differs between them."),
                Classifier("employer_sector", "Employer sector",
                           "employer_sector",
                           "Where the customer works. Not their industry as a "
                           "borrower."),
                Classifier("income_band", "Verified income",
                           "verified_total_monthly_income_sar",
                           "Verified monthly salary plus verified other "
                           "income. A customer property, counted once."),
            ),
            triggers=(
                Trigger(
                    key="income_decline", name="Material income decline",
                    column="salary_change_3m_ratio", comparator="",
                    test="ratio_fall", threshold=0.80, unit="ratio",
                    severity="HIGH",
                    meaning="The latest salary credit is materially below the "
                            "average of the three before it.",
                    reason_code="RET-EWS-009",
                    reason_template="The latest salary credit is {value:.0%} "
                                    "of the recent average.",
                    recommended_review="Confirm the income position before "
                                       "any further lending.",
                    rule_id="RET-EWS-009"),
                Trigger(
                    key="salary_volatility", name="Salary volatility",
                    column="salary_volatility_6m", comparator="",
                    test="level", threshold=0.35, unit="ratio",
                    severity="MEDIUM",
                    meaning="Salary credits swinging month to month.",
                    reason_code="RET-EWS-025",
                    reason_template="Salary credits vary by {value:.0%} "
                                    "around their six-month mean.",
                    recommended_review="Check whether income is variable by "
                                       "arrangement or by disruption.",
                    source_class="Derived"),
            )),
        Sublayer(
            key="salary_behaviour",
            name="Salary Behaviour",
            purpose="Whether the salary is arriving at all.",
            weight=0.25,
            classifiers=(
                Classifier("salary_transfer", "Salary transfer",
                           "salary_transfer_flag",
                           "Whether salary is mandated to this bank. Without "
                           "it the absence of a credit says nothing."),
                Classifier("expected_credit_date", "Expected credit date",
                           "expected_salary_credit_date",
                           "When the salary is due, so a late credit can be "
                           "told from an absent one."),
            ),
            triggers=(
                Trigger(
                    key="salary_interruption", name="Salary credit interruption",
                    column="salary_missed_cycle_count_3m", comparator="",
                    test="level", threshold=1.0, unit="count", severity="HIGH",
                    meaning="A salary cycle passed with no credit at all.",
                    reason_code="RET-EWS-008",
                    reason_template="{value:.0f} salary cycles with no credit "
                                    "in the last three months.",
                    recommended_review="Confirm employment before the next "
                                       "instalment falls due.",
                    rule_id="RET-EWS-008"),
                Trigger(
                    key="consecutive_salary_missing",
                    name="Consecutive salary-missing months",
                    column="salary_missed_cycle_count_3m", comparator="",
                    test="level", threshold=2.0, unit="count",
                    severity="CRITICAL",
                    meaning="Two or more consecutive cycles with no salary "
                            "credit. Employment has probably ended.",
                    reason_code="RET-EWS-026",
                    reason_template="{value:.0f} consecutive salary cycles "
                                    "with no credit.",
                    recommended_review="Treat as an employment event, not a "
                                       "payment event."),
            )),
        Sublayer(
            key="debt_burden",
            name="Debt Burden",
            purpose="What share of income the customer's obligations take.",
            weight=0.25,
            classifiers=(
                Classifier("origination_dbr", "Debt burden at origination",
                           "origination_debt_burden_ratio",
                           "The ratio the facility was underwritten at. The "
                           "baseline a movement is read against."),
            ),
            triggers=(
                Trigger(
                    key="dbr_increase", name="Affordability deterioration",
                    column="debt_burden_ratio",
                    comparator="previous_month_debt_burden_ratio",
                    test="rise", threshold=0.05, unit="ratio",
                    severity="HIGH",
                    meaning="The share of income taken by credit obligations "
                            "rose materially in one month.",
                    reason_code="RET-EWS-011",
                    reason_template="Debt burden rose from {comparator:.0%} "
                                    "to {value:.0%}.",
                    recommended_review="Identify the new obligation and "
                                       "whether it was disclosed.",
                    source_class="Derived", rule_id="RET-EWS-011"),
                Trigger(
                    key="external_obligations", name="New external obligations",
                    column="external_obligations_change_3m_sar", comparator="",
                    test="level", threshold=1500.0, unit="SAR",
                    severity="MEDIUM",
                    meaning="Monthly obligations to other lenders rose. The "
                            "customer is borrowing elsewhere.",
                    reason_code="RET-EWS-012",
                    reason_template="Monthly obligations to other lenders rose "
                                    "by SAR {value:,.0f} over three months.",
                    recommended_review="Review the customer's total "
                                       "indebtedness.",
                    rule_id="RET-EWS-012"),
            )),
        Sublayer(
            key="disposable_income",
            name="Disposable Income and Affordability",
            purpose="What is left after everything is paid.",
            weight=0.15,
            classifiers=(
                Classifier("indebtedness_band", "Indebtedness band",
                           "indebtedness_band",
                           "Where the customer's debt burden sits, banded."),
            ),
            triggers=(
                Trigger(
                    key="disposable_fall", name="Disposable income decline",
                    column="disposable_income_sar",
                    comparator="previous_month_disposable_income_sar",
                    test="fall", threshold=1000.0, unit="SAR",
                    severity="MEDIUM",
                    meaning="Income less household expenses less obligations "
                            "fell materially.",
                    reason_code="RET-EWS-027",
                    reason_template="Disposable income fell by SAR "
                                    "{magnitude:,.0f} in one month.",
                    recommended_review="Check which side of the calculation "
                                       "moved.",
                    source_class="Derived"),
            )),
        Sublayer(
            key="cashflow_stress",
            name="Cash-Flow Stress",
            purpose="Whether there is money in the account when it is needed.",
            weight=0.10,
            classifiers=(),
            triggers=(
                Trigger(
                    key="buffer_exhausted",
                    name="Personal cash buffer exhausted",
                    column="balance_buffer_months", comparator="",
                    test="below", threshold=0.5, unit="months",
                    severity="MEDIUM",
                    meaning="The average account balance no longer covers half "
                            "a monthly instalment.",
                    reason_code="RET-EWS-010",
                    reason_template="Average balance covers {value:.1f} months "
                                    "of the instalment.",
                    recommended_review="Check the salary credit date against "
                                       "the instalment date.",
                    rule_id="RET-EWS-010"),
                Trigger(
                    key="inflow_decline", name="Account inflow decline",
                    column="account_inflows_1m_sar",
                    comparator="account_inflows_3m_average_sar",
                    test="fall", threshold=2000.0, unit="SAR",
                    severity="MEDIUM",
                    meaning="Money arriving in the account fell against its "
                            "own recent average.",
                    reason_code="RET-EWS-028",
                    reason_template="Account inflows fell SAR "
                                    "{magnitude:,.0f} below their three-month "
                                    "average.",
                    recommended_review="Read beside the salary triggers: an "
                                       "inflow fall with salary intact is a "
                                       "different story.",
                    source_class="Derived"),
            )),
    ),
)


# ================================================================= LAYER 3
# Bureau & External Credit Intelligence
# =========================================================================

BUREAU = Layer(
    key="bureau",
    name="Bureau & External Credit Intelligence",
    purpose=(
        "What the customer looks like to lenders other than this one. Primarily "
        "a CLASSIFIER layer: the bank does not receive a bureau file every "
        "month, so between dated pulls the last observed position is carried "
        "forward unchanged and the layer reports how old it is."),
    kind="classifier",
    weight=0.15,
    weight_because=(
        "Weighted lowest of the four because most months carry no new bureau "
        "observation at all. A layer that cannot move most of the time must "
        "not be able to move the overall score much when it does."),
    refresh=(
        "On a dated pull only: at origination, on the customer's own re-pull "
        "cadence, and on entry to thirty days past due. Never monthly."),
    sublayers=(
        Sublayer(
            key="bureau_profile",
            name="Bureau Risk Profile",
            purpose="Where the customer sits with the bureau, as last seen.",
            weight=0.30,
            classifiers=(
                Classifier("latest_bureau_score", "Last observed bureau score",
                           "latest_bureau_score",
                           "The bureau score at the last dated pull, carried "
                           "forward unchanged until the next one.",
                           source_class="External"),
                Classifier("bureau_at_origination", "Bureau score at origination",
                           "bureau_score_at_origination",
                           "What the bureau said when the facility was "
                           "written.", source_class="External"),
                Classifier("bureau_risk_band", "Bureau risk band",
                           "bureau_risk_band",
                           "The last observed score, banded.",
                           source_class="External"),
            ),
            triggers=(
                Trigger(
                    key="bureau_deterioration", name="Bureau deterioration",
                    column="latest_bureau_score",
                    comparator="previous_observed_bureau_score",
                    test="fall", threshold=40.0, unit="points",
                    severity="MEDIUM",
                    meaning="The bureau score fell between two DATED pulls. It "
                            "cannot fire in a month with no new observation.",
                    reason_code="RET-EWS-015",
                    reason_template="Bureau score fell from {comparator:.0f} "
                                    "to {value:.0f} between observations.",
                    recommended_review="Check what the bureau saw that this "
                                       "bank has not.",
                    source_class="External", rule_id="RET-EWS-015",
                    needs_new_observation=True),
            )),
        Sublayer(
            key="external_delinquency",
            name="External Delinquency",
            purpose="Whether the customer is behind with somebody else.",
            weight=0.25,
            classifiers=(
                Classifier("external_dpd", "Worst external days past due",
                           "bureau_external_dpd_max",
                           "The worst arrears with any other lender at the "
                           "last pull.", source_class="External"),
            ),
            triggers=(
                Trigger(
                    key="new_external_delinquency",
                    name="New external delinquency",
                    column="bureau_external_dpd_max",
                    comparator="previous_observed_external_dpd",
                    test="rise", threshold=30.0, unit="days", severity="HIGH",
                    meaning="A new arrears position with another lender, "
                            "observed at a dated pull.",
                    reason_code="RET-EWS-029",
                    reason_template="External arrears rose from "
                                    "{comparator:.0f} to {value:.0f} days at "
                                    "the latest bureau observation.",
                    recommended_review="A customer paying this bank and not "
                                       "another is choosing; find out why.",
                    source_class="External", needs_new_observation=True),
            )),
        Sublayer(
            key="external_leverage",
            name="External Leverage",
            purpose="How much the customer owes elsewhere.",
            weight=0.20,
            classifiers=(
                Classifier("bureau_monthly_obligations",
                           "External monthly obligations",
                           "monthly_external_credit_obligations_sar",
                           "Monthly obligations to other lenders at the last "
                           "pull.", source_class="External"),
                Classifier("bureau_exposure", "Total bureau exposure",
                           "bureau_total_exposure_sar",
                           "Everything the bureau shows outstanding.",
                           source_class="External"),
            ),
            triggers=(
                Trigger(
                    key="external_leverage_rise",
                    name="External leverage increase",
                    column="bureau_total_exposure_sar",
                    comparator="previous_observed_bureau_exposure",
                    test="rise", threshold=25000.0, unit="SAR",
                    severity="MEDIUM",
                    meaning="Total borrowing elsewhere rose between pulls.",
                    reason_code="RET-EWS-030",
                    reason_template="Bureau exposure rose SAR "
                                    "{magnitude:,.0f} between observations.",
                    recommended_review="Reassess total indebtedness.",
                    source_class="External", needs_new_observation=True),
            )),
        Sublayer(
            key="credit_seeking",
            name="Credit Seeking and Enquiries",
            purpose="Whether the customer is shopping for credit.",
            weight=0.10,
            classifiers=(
                Classifier("enquiries", "Bureau enquiries",
                           "bureau_enquiries_3m",
                           "Searches recorded against the customer at the "
                           "last pull.", source_class="External"),
            ),
            triggers=(
                Trigger(
                    key="new_enquiries", name="New credit enquiries",
                    column="bureau_enquiries_3m",
                    comparator="previous_observed_enquiries",
                    test="rise", threshold=2.0, unit="count",
                    severity="MEDIUM",
                    meaning="More searches than at the last pull. Somebody "
                            "looking hard for credit is often about to need "
                            "it.",
                    reason_code="RET-EWS-031",
                    reason_template="{value:.0f} bureau enquiries at the "
                                    "latest observation, against "
                                    "{comparator:.0f} before.",
                    recommended_review="Read beside the affordability layer.",
                    source_class="External", needs_new_observation=True),
            )),
        Sublayer(
            key="bureau_recency",
            name="Data Recency",
            purpose=(
                "How old the external picture is. The one sublayer here that "
                "moves every month, because staleness accrues whether or not "
                "anything else happens."),
            weight=0.15,
            classifiers=(
                Classifier("last_pull", "Last bureau observation date",
                           "bureau_last_observed_date",
                           "The month-end of the last dated bureau pull.",
                           source_class="External"),
            ),
            triggers=(
                Trigger(
                    key="stale_bureau", name="Bureau information is stale",
                    column="bureau_recency_months", comparator="",
                    test="level", threshold=12.0, unit="months",
                    severity="LOW",
                    meaning="A year or more since the last dated bureau "
                            "observation. Not a statement about the customer; "
                            "a statement about what is known about them.",
                    reason_code="RET-EWS-032",
                    reason_template="The bureau position is {value:.0f} "
                                    "months old.",
                    recommended_review="Order a refreshed bureau report "
                                       "before acting on the external layer.",
                    source_class="External"),
            )),
    ),
)


# ================================================================= LAYER 4
# Facility & Exposure Intelligence
# =========================================================================

FACILITY = Layer(
    key="facility",
    name="Facility & Exposure Intelligence",
    purpose=(
        "What the facility itself is doing: a balance building, a limit under "
        "pressure, a concession already granted, security that no longer "
        "covers the debt, a balloon instalment approaching."),
    kind="dynamic",
    weight=0.15,
    weight_because=(
        "Weighted lowest of the three dynamic layers because a structural "
        "signal describes the contract rather than the customer, and is "
        "strongest when read beside the other three."),
    refresh="Monthly, with the retail book.",
    sublayers=(
        Sublayer(
            key="exposure_buildup",
            name="Exposure Build-up",
            purpose="Whether what is owed is growing.",
            weight=0.25,
            classifiers=(
                Classifier("original_amount", "Amount financed",
                           "original_finance_amount_sar",
                           "What was lent at origination."),
                Classifier("repayment_structure", "Contract structure",
                           "contract_structure",
                           "How the facility repays. A balance that grows on "
                           "an amortising contract is a different event from "
                           "one that grows on a revolving line."),
            ),
            triggers=(
                Trigger(
                    key="balance_build", name="Rapid balance build",
                    column="gross_carrying_amount_sar",
                    comparator="previous_month_gross_carrying_amount_sar",
                    test="rise", threshold=0.20, unit="ratio",
                    severity="MEDIUM",
                    meaning="Outstanding balance grew more than a fifth in "
                            "one month on an amortising facility, which "
                            "should be shrinking. Revolving facilities are "
                            "out of scope: a card balance that grows is a "
                            "card being used.",
                    reason_code="RET-EWS-033",
                    reason_template="Balance rose {value:.0%} in one month.",
                    recommended_review="Identify the draw or the top-up "
                                       "behind it.",
                    products=(PERSONAL_LOAN, AUTO_LOAN, HOME_LOAN),
                    source_class="Derived",
                    absent_because=(
                        "Not observable in this book. A top-up here is "
                        "written as a NEW facility rather than added to an "
                        "existing one, so an amortising balance never grows: "
                        "the largest one-month rise across twenty months is "
                        "one per cent, which is interest accrual. The "
                        "trigger is declared and never evaluated rather than "
                        "having its threshold lowered until ordinary accrual "
                        "reads as a warning.")),
            )),
        Sublayer(
            key="limit_utilisation",
            name="Limit and Utilisation",
            purpose="Whether the facility is pressed against its own limit.",
            weight=0.20,
            classifiers=(
                Classifier("current_limit", "Current credit limit",
                           "current_credit_limit_sar",
                           "The limit in force at this month-end.",
                           products=(CREDIT_CARD,)),
                Classifier("original_limit", "Original credit limit",
                           "original_credit_limit_sar",
                           "The limit sanctioned at origination.",
                           products=(CREDIT_CARD,)),
            ),
            triggers=(
                Trigger(
                    key="limit_excess", name="Limit excess",
                    column="utilisation_ratio", comparator="",
                    test="level", threshold=1.0, unit="ratio",
                    severity="HIGH",
                    meaning="Drawn balance above the sanctioned limit.",
                    reason_code="RET-EWS-034",
                    reason_template="Drawn balance is {value:.0%} of the "
                                    "limit.",
                    recommended_review="Confirm the excess was authorised.",
                    products=(CREDIT_CARD,)),
            )),
        Sublayer(
            key="restructure_forbearance",
            name="Restructure and Forbearance",
            purpose="Whether a concession has already been granted.",
            weight=0.25,
            classifiers=(
                Classifier("forbearance", "Forbearance flag",
                           "forbearance_flag",
                           "Whether a concession has been granted because of "
                           "financial difficulty."),
                Classifier("restructured", "Restructured flag",
                           "restructured_flag",
                           "Whether the contract has been rewritten."),
            ),
            triggers=(
                Trigger(
                    key="forbearance_strain", name="Forbearance under strain",
                    column="dpd", comparator="forbearance_flag",
                    test="level", threshold=1.0, unit="days", severity="HIGH",
                    meaning="A concession was granted and the customer fell "
                            "behind anyway.",
                    reason_code="RET-EWS-018",
                    reason_template="Forborne and {value:.0f} days past due.",
                    recommended_review="The restructure has not worked; "
                                       "review the arrangement rather than "
                                       "extending it.",
                    rule_id="RET-EWS-018"),
                Trigger(
                    key="repeat_restructure", name="Repeated restructure",
                    column="restructure_count_lifetime", comparator="",
                    test="level", threshold=2.0, unit="count", severity="HIGH",
                    meaning="The contract has been rewritten more than once.",
                    reason_code="RET-EWS-035",
                    reason_template="The facility has been restructured "
                                    "{value:.0f} times.",
                    recommended_review="Repeated restructuring usually defers "
                                       "a loss rather than preventing one.",
                    absent_because=(
                        "The published book carries a restructure date and "
                        "flag but not a lifetime count, so this trigger is "
                        "declared and never evaluated rather than inferred "
                        "from a single date.")),
            )),
        Sublayer(
            key="collateral_coverage",
            name="Collateral and Coverage",
            purpose="Whether the security still covers the debt.",
            weight=0.15,
            classifiers=(
                Classifier("secured", "Secured or unsecured", "secured_flag",
                           "Whether anything stands behind the facility."),
                Classifier("collateral_type", "Collateral type",
                           "collateral_type",
                           "What the security is.", products=SECURED),
                Classifier("ltv_origination", "LTV at origination",
                           "ltv_origination_ratio",
                           "Amount financed over collateral value when the "
                           "facility was written.", products=SECURED),
            ),
            triggers=(
                Trigger(
                    key="ltv_deterioration",
                    name="Collateral cover deterioration",
                    column="ltv_current_ratio",
                    comparator="ltv_origination_ratio",
                    test="rise", threshold=0.40, unit="ratio",
                    severity="MEDIUM",
                    meaning="Loan-to-value is forty points or more above "
                            "where the facility was written: the balance has "
                            "not fallen away from the collateral's value as "
                            "the schedule intended, or the collateral is "
                            "worth less than it was.",
                    reason_code="RET-EWS-020",
                    reason_template="Loan-to-value is {value:.0%} against "
                                    "{comparator:.0%} at origination.",
                    recommended_review="Confirm the valuation date before "
                                       "relying on the security.",
                    products=SECURED, source_class="Derived",
                    rule_id="RET-EWS-020"),
            )),
        Sublayer(
            key="maturity_balloon",
            name="Maturity and Balloon Risk",
            purpose="Whether a large instalment is about to fall due.",
            weight=0.15,
            classifiers=(
                Classifier("balloon_band", "Balloon band", "balloon_band",
                           "How large the final instalment is against the "
                           "rest.", products=(AUTO_LOAN,)),
                Classifier("remaining_tenor", "Remaining tenor",
                           "remaining_contractual_tenor_months",
                           "Months left to contractual maturity."),
            ),
            triggers=(
                Trigger(
                    key="balloon_proximity", name="Balloon payment approaching",
                    column="months_to_balloon", comparator="",
                    test="below", threshold=6.0, unit="months",
                    severity="HIGH",
                    meaning="A balloon instalment falls due within six months "
                            "and the customer's buffer is thin.",
                    reason_code="RET-EWS-019",
                    reason_template="A balloon payment falls due in "
                                    "{value:.0f} months.",
                    recommended_review="Agree the refinancing or the "
                                       "settlement now, not in month five.",
                    products=(AUTO_LOAN,), rule_id="RET-EWS-019"),
            )),
    ),
)


LAYERS: tuple[Layer, ...] = (BEHAVIOURAL, AFFORDABILITY, BUREAU, FACILITY)


# ------------------------------------------------ product weight matrix

#: Per-product layer weights. Synthetic demonstration configuration.
#:
#: Kept HERE rather than in the frontend, because a weight a screen carries is
#: a weight nobody can audit. Each row sums to one and a test proves it.
PRODUCT_WEIGHTS: dict[str, dict[str, float]] = {
    # A card tells you everything through behaviour and utilisation.
    CREDIT_CARD: {"behavioural": 0.45, "affordability": 0.22,
                  "bureau": 0.13, "facility": 0.20},
    # An unsecured instalment loan is an affordability product.
    PERSONAL_LOAN: {"behavioural": 0.40, "affordability": 0.35,
                    "bureau": 0.15, "facility": 0.10},
    # A car loan adds a depreciating asset to the same question.
    AUTO_LOAN: {"behavioural": 0.36, "affordability": 0.28,
                "bureau": 0.14, "facility": 0.22},
    # A mortgage is an affordability product with security behind it.
    HOME_LOAN: {"behavioural": 0.30, "affordability": 0.36,
                "bureau": 0.14, "facility": 0.20},
}

PRODUCT_EMPHASIS: dict[str, str] = {
    CREDIT_CARD: "Behavioural and facility/utilisation weighted strongest: a "
                 "card reports distress through how it is used long before an "
                 "instalment is missed.",
    PERSONAL_LOAN: "Behavioural and affordability weighted strongest: an "
                   "unsecured instalment loan fails when income does.",
    AUTO_LOAN: "Behavioural, affordability and facility/collateral all carry "
               "weight: the asset depreciates faster than the balance "
               "amortises early in the term.",
    HOME_LOAN: "Affordability weighted strongest, then behavioural and "
               "facility/collateral: a mortgage is a twenty-year "
               "affordability position.",
}


# ------------------------------------------------------ sub-product taxonomy

@dataclass(frozen=True)
class SubProduct:
    code: str
    label: str
    product: str
    meaning: str
    #: The governed derivation from the published book. Deterministic, so the
    #: same customer lands in the same sub-product on every rebuild.
    derivation: str


#: Governed synthetic sub-products.
#:
#: The published book does not carry a card tier or a sub-portfolio name, so
#: these are DERIVED deterministically from columns it does carry and the rule
#: is written down beside the label. Nothing is randomised: the same facility
#: lands in the same sub-product every time the panel is built.
SUB_PRODUCTS: tuple[SubProduct, ...] = (
    SubProduct("CC_ULTRA", "Ultra Card", CREDIT_CARD,
               "The top card tier, held by private and affluent customers on "
               "the largest limits.",
               "customer_segment in (PRIVATE, AFFLUENT) and current credit "
               "limit >= SAR 60,000"),
    SubProduct("CC_PRIVILEGE", "Privilege Card", CREDIT_CARD,
               "The affluent tier.",
               "customer_segment in (PRIVATE, AFFLUENT), or MASS_AFFLUENT on a "
               "limit >= SAR 50,000"),
    SubProduct("CC_PLATINUM", "Platinum Card", CREDIT_CARD,
               "The mass-affluent tier.",
               "customer_segment == MASS_AFFLUENT, or MASS on a limit >= SAR "
               "25,000"),
    SubProduct("CC_SILVER", "Silver Card", CREDIT_CARD,
               "The mass tier, and the largest card population.",
               "everything else on the card book"),
    SubProduct("PF_NEW", "New Personal Finance", PERSONAL_LOAN,
               "Personal finance written as new money.",
               "product_subsegment == NEW_FINANCE"),
    SubProduct("PF_TOPUP", "Personal Finance Top-up", PERSONAL_LOAN,
               "An existing customer borrowing more on an existing facility.",
               "product_subsegment == TOP_UP"),
    SubProduct("PF_BUYOUT", "Personal Finance Buyout", PERSONAL_LOAN,
               "A balance taken over from another lender.",
               "product_subsegment == REFINANCE_BUYOUT"),
    SubProduct("AL_NEW", "New Auto Finance", AUTO_LOAN,
               "A new vehicle.", "product_subsegment == NEW"),
    SubProduct("AL_USED", "Used Auto Finance", AUTO_LOAN,
               "A used vehicle, which depreciates on a different curve.",
               "product_subsegment == USED"),
    SubProduct("HL_FIRST", "First Home", HOME_LOAN,
               "A first residential purchase.",
               "product_subsegment == FIRST_HOME"),
    SubProduct("HL_SECOND", "Second Property", HOME_LOAN,
               "An additional property.",
               "product_subsegment == SECOND_PROPERTY"),
    SubProduct("HL_REFINANCE", "Home Refinance", HOME_LOAN,
               "A mortgage taken over from another lender.",
               "product_subsegment == REFINANCE"),
)

SUB_PRODUCT_LABELS: dict[str, str] = {s.code: s.label for s in SUB_PRODUCTS}


def sub_products_of(product: str) -> tuple[SubProduct, ...]:
    return tuple(s for s in SUB_PRODUCTS if s.product == product)


# ------------------------------------------------------ the bureau pull rule

@dataclass(frozen=True)
class BureauRule:
    """When a genuine bureau observation exists, and what happens between them.

    The demonstration book stamps a bureau score AND a bureau date on every
    month-end, which would let a reader plot a monthly bureau trend that no
    retail bank could produce. Rather than delete the column or pretend the
    date means something it does not, the model declares when a pull actually
    happened and reads bureau only on those dates.
    """

    statement: str = (
        "The bank does not receive a bureau file every month. A bureau "
        "observation exists at origination, on the customer's own re-pull "
        "cadence, and on entry to thirty days past due. Between observations "
        "the last observed values are carried forward unchanged, with the "
        "observation date and its age shown beside them. No monthly bureau "
        "movement is generated, and the bureau triggers cannot fire in a "
        "month that holds no new observation.")
    #: Re-pull cadence in months, chosen per customer from a stable hash of
    #: their id so it does not change between builds.
    cadence_months: tuple[int, ...] = (6, 9, 12, 18)
    delinquency_pull_at_dpd: float = 30.0
    proxy_label: str = "Synthetic bureau proxy — not a live bureau feed."
    no_agreement: str = (
        "There is no live bureau connection and no bureau agreement behind "
        "these values. They are generated with the rest of the demonstration "
        "book.")


BUREAU_RULE = BureauRule()


# --------------------------------------------------------------- lookups

def layer(key: str) -> Layer | None:
    return next((one for one in LAYERS if one.key == key), None)


def sublayer(key: str) -> Sublayer | None:
    for one in LAYERS:
        for sub in one.sublayers:
            if sub.key == key:
                return sub
    return None


def all_sublayers() -> tuple[Sublayer, ...]:
    return tuple(sub for one in LAYERS for sub in one.sublayers)


def all_triggers() -> tuple[Trigger, ...]:
    return tuple(t for one in LAYERS for sub in one.sublayers
                 for t in sub.triggers)


def evaluated_triggers() -> tuple[Trigger, ...]:
    """Triggers the book can actually support."""
    return tuple(t for t in all_triggers() if not t.absent_because)


def all_classifiers() -> tuple[Classifier, ...]:
    return tuple(c for one in LAYERS for sub in one.sublayers
                 for c in sub.classifiers)


def trigger(key: str) -> Trigger | None:
    return next((t for t in all_triggers() if t.key == key), None)


def trigger_by_reason(code: str) -> Trigger | None:
    return next((t for t in all_triggers() if t.reason_code == code), None)


def layer_of_sublayer(key: str) -> Layer | None:
    for one in LAYERS:
        if any(sub.key == key for sub in one.sublayers):
            return one
    return None


def layer_of_trigger(key: str) -> Layer | None:
    for one in LAYERS:
        for sub in one.sublayers:
            if any(t.key == key for t in sub.triggers):
                return one
    return None


def sublayer_of_trigger(key: str) -> Sublayer | None:
    for one in LAYERS:
        for sub in one.sublayers:
            if any(t.key == key for t in sub.triggers):
                return sub
    return None


def band_of(score: float) -> str:
    """A CUSTOMER's severity."""
    for floor, name in SEVERITY_BANDS:
        if score >= floor:
            return name
    return SEVERITY_BANDS[-1][1]


def population_band_of(score: float) -> str:
    """A PRODUCT's, a sub-product's or the book's severity."""
    for floor, name in POPULATION_BANDS:
        if score >= floor:
            return name
    return POPULATION_BANDS[-1][1]


def weights_for(product: str) -> dict[str, float]:
    """The layer weights this product is scored with."""
    return dict(PRODUCT_WEIGHTS.get(str(product).upper(),
                                    {one.key: one.weight for one in LAYERS}))


# ------------------------------------------------------------- the glossary

@dataclass(frozen=True)
class Term:
    term: str
    meaning: str
    authority: str


GLOSSARY: tuple[Term, ...] = (
    Term("EWS", "Early Warning Score. In this deployment it means the model "
                "configured in backend/retail/ews_model.py: four layers, "
                "eighteen sublayers, and the triggers under them.",
         "backend/retail/ews_model.py, EWS_MODEL_VERSION."),
    Term("Classifier", "Stable context that sets how a trigger should be "
                       "read. A classifier never fires on its own.",
         "backend/retail/ews_model.py, class Classifier."),
    Term("Trigger", "A live deterioration event measured against this month's "
                    "book and the months behind it.",
         "backend/retail/ews_model.py, class Trigger."),
    Term("Direction", "Whether the measure behind a trigger is improving, "
                      "stable or deteriorating.",
         "backend/retail/ews_model.py, ACTION_DIMENSIONS."),
    Term("Magnitude", "How large this month's move is against the trigger's "
                      "own threshold.",
         "backend/retail/ews_model.py, ACTION_DIMENSIONS."),
    Term("Velocity", "The mean monthly change over the last three months.",
         "backend/retail/ews_model.py, ACTION_DIMENSIONS."),
    Term("Momentum", "Whether the deterioration is accelerating or slowing.",
         "backend/retail/ews_model.py, ACTION_DIMENSIONS."),
    Term("Persistence", "Consecutive months a trigger has fired.",
         "backend/retail/ews_model.py, ACTION_DIMENSIONS."),
    Term("Recency", "Months since the observation the trigger reads. Zero for "
                    "anything refreshed with the monthly book; for bureau it "
                    "is months since the last dated pull.",
         "backend/retail/ews_model.py, ACTION_DIMENSIONS."),
    Term("DPD", "Days past due — how many days the oldest unpaid amount on "
                "the facility has been outstanding.",
         "backend/retail/schema.py, column `dpd`."),
    Term("ODR", "Observed default rate. A PORTFOLIO measure: facilities "
                "entering default in the month over facilities eligible to "
                "at its start. It is never a property of one customer.",
         "backend/retail/ews_score.py, default_entry_this_month."),
    Term("DBR", "Debt burden ratio — monthly credit obligations over verified "
                "monthly income.",
         "backend/retail/schema.py, column `debt_burden_ratio`."),
    Term("SICR", "Significant Increase in Credit Risk — the IFRS 9 test that "
                 "moves a facility from Stage 1 to Stage 2.",
         "backend/retail/schema.py, column `sicr_flag`."),
    Term("LTV", "Loan to value — balance over the collateral's value.",
         "backend/retail/schema.py, column `ltv_current_ratio`."),
    Term("Stage 1 / 2 / 3", "IFRS 9 impairment stages: performing, "
                            "significant increase in credit risk, and "
                            "credit-impaired.",
         "backend/retail/schema.py, column `ifrs9_stage`."),
    Term("Current bad", "A customer who is ALREADY in trouble at this "
                        "month-end: thirty or more days past due, flagged in "
                        "default, or in Stage 3. Not a prediction.",
         "backend/retail/ews_score.py, CURRENT_BAD_RULE."),
    Term("Forward risk", "A customer who is NOT currently bad and whose Early "
                         "Warning Score is in the HIGH or CRITICAL band. A "
                         "prediction about somebody who is still paying.",
         "backend/retail/ews_score.py, FORWARD_RISK_RULE."),
)


#: Shorthand that must never be given an invented expansion.
#:
#: T, A and C were searched for across the rulebook, the taxonomy, the retail
#: schema, the forward-risk signal and the screens. They do not exist as
#: governed abbreviations anywhere in this deployment, so no meaning is shown
#: and none has been invented. Every label in the Early Warning Score is
#: written out in full.
UNSOURCED_SHORTHAND: tuple[str, ...] = ("T", "A", "C")

NO_SUCH_SHORTHAND = (
    "T, A and C are not governed abbreviations in this deployment's Early "
    "Warning implementation. They appear nowhere in the model configuration, "
    "the rulebook, the taxonomy, the retail schema or the forward-risk "
    "signal, so no meaning is shown for them and none has been invented. "
    "Every layer, sublayer, classifier, trigger and variable label in the "
    "Early Warning Score is written out in full.")


# ---------------------------------------------------------------- the check

def check() -> list[str]:
    """Every problem with the model configuration, as sentences.

    Run by a test rather than trusted. A weight that stops summing to one is a
    score that silently changes meaning, and there is no way to see that on a
    screen.
    """
    problems: list[str] = []

    total = round(sum(one.weight for one in LAYERS), 6)
    if total != 1.0:
        problems.append(f"the four layer weights sum to {total}, not 1.0")

    for one in LAYERS:
        inner = round(sum(sub.weight for sub in one.sublayers), 6)
        if inner != 1.0:
            problems.append(
                f"{one.name}: its sublayer weights sum to {inner}, not 1.0")
        if not one.sublayers:
            problems.append(f"{one.name} has no sublayers")

    for product, weights in PRODUCT_WEIGHTS.items():
        total = round(sum(weights.values()), 6)
        if total != 1.0:
            problems.append(
                f"{product}: its layer weights sum to {total}, not 1.0")
        unknown = set(weights) - {one.key for one in LAYERS}
        if unknown:
            problems.append(
                f"{product}: weights name layers that do not exist: "
                f"{sorted(unknown)}")
        missing = {one.key for one in LAYERS} - set(weights)
        if missing:
            problems.append(
                f"{product}: no weight for {sorted(missing)}")

    seen_keys: set[str] = set()
    seen_codes: set[str] = set()
    for one in all_triggers():
        if one.key in seen_keys:
            problems.append(f"trigger key {one.key!r} is used twice")
        seen_keys.add(one.key)
        if one.reason_code in seen_codes:
            problems.append(
                f"reason code {one.reason_code!r} is used by two triggers")
        seen_codes.add(one.reason_code)
        if one.severity not in SEVERITY_POINTS:
            problems.append(
                f"{one.key}: severity {one.severity!r} has no point value")

    shared = ({one.key for one in all_classifiers()}
              & {one.key for one in all_triggers()})
    if shared:
        problems.append(
            "these keys are used by both a classifier and a trigger, so "
            f"their columns collide: {sorted(shared)}")

    action_total = round(sum(ACTION_WEIGHTS.values()), 6)
    if action_total != 1.0:
        problems.append(
            f"the action-dimension weights sum to {action_total}, not 1.0")
    if set(ACTION_WEIGHTS) != {d.key for d in ACTION_DIMENSIONS}:
        problems.append(
            "the action-dimension weights and the declared dimensions differ")

    products_covered = {s.product for s in SUB_PRODUCTS}
    if products_covered != set(ALL_PRODUCTS):
        problems.append(
            "every product must have sub-products; missing "
            f"{sorted(set(ALL_PRODUCTS) - products_covered)}")

    # Every rulebook rule that carries risk must survive into a trigger, so
    # the rebuild cannot quietly drop a governed signal.
    try:
        from backend.retail import ews as rulebook

        carried = {t.rule_id for t in all_triggers() if t.rule_id}
        governed = {r.rule_id for r in rulebook.RULES
                    if r.family != "DATA_QUALITY"}
        lost = governed - carried
        if lost:
            problems.append(
                "governed rulebook rules dropped by the four-layer model: "
                f"{sorted(lost)}")
    except Exception as problem:  # noqa: BLE001
        problems.append(f"the rulebook could not be read: {problem}")

    return problems


def to_dict(*, deep: bool = True) -> dict[str, Any]:
    """The whole model, as the API serves it. One source, one shape."""
    return {
        "name": MODEL_NAME,
        "model_version": EWS_MODEL_VERSION,
        "purpose": PURPOSE,
        "target": TARGET,
        "horizon": HORIZON,
        "eligible_population": ELIGIBLE_POPULATION,
        "scoring_frequency": SCORING_FREQUENCY,
        "scale": {
            "minimum": SCALE.minimum,
            "maximum": SCALE.maximum,
            "direction": SCALE.direction,
            "warning_cutoff": SCALE.warning_cutoff,
        },
        "severity_bands": [{"from": floor, "band": name}
                           for floor, name in SEVERITY_BANDS],
        "population_bands": [{"from": floor, "band": name}
                             for floor, name in POPULATION_BANDS],
        "severity_points": dict(SEVERITY_POINTS),
        "trigger_contribution_cap": TRIGGER_CONTRIBUTION_CAP,
        "threshold_source": THRESHOLD_SOURCE,
        "hard_triggers": [
            {"key": h.key, "name": h.name, "condition": h.condition,
             "floor_score": h.floor_score, "band": h.band,
             "because": h.because}
            for h in HARD_TRIGGERS],
        "action_dimensions": [
            {"key": d.key, "name": d.name, "meaning": d.meaning,
             "computed": d.computed, "values": d.values,
             "weight": ACTION_WEIGHTS[d.key]}
            for d in ACTION_DIMENSIONS],
        "action_multiplier": {
            "floor": ACTION_MULTIPLIER_FLOOR,
            "ceiling": ACTION_MULTIPLIER_CEILING,
            "meaning": (
                "The action dimensions scale a fired trigger's severity "
                "points between half and one and a half times. A trigger that "
                "fired once, mildly, and is already improving is not the same "
                "finding as one that has fired for six months and is "
                "accelerating."),
        },
        "layers": [one.to_dict(deep=deep) for one in LAYERS],
        "product_weights": {code: dict(w)
                            for code, w in PRODUCT_WEIGHTS.items()},
        "product_emphasis": dict(PRODUCT_EMPHASIS),
        "sub_products": [
            {"code": s.code, "label": s.label, "product": s.product,
             "meaning": s.meaning, "derivation": s.derivation}
            for s in SUB_PRODUCTS],
        "bureau_rule": {
            "statement": BUREAU_RULE.statement,
            "cadence_months": list(BUREAU_RULE.cadence_months),
            "delinquency_pull_at_dpd": BUREAU_RULE.delinquency_pull_at_dpd,
            "proxy_label": BUREAU_RULE.proxy_label,
            "no_agreement": BUREAU_RULE.no_agreement,
        },
        "glossary": [{"term": t.term, "meaning": t.meaning,
                      "authority": t.authority} for t in GLOSSARY],
        "unsourced_shorthand": NO_SUCH_SHORTHAND,
        "counts": {
            "layers": len(LAYERS),
            "sublayers": len(all_sublayers()),
            "classifiers": len(all_classifiers()),
            "triggers": len(all_triggers()),
            "triggers_evaluated": len(evaluated_triggers()),
            "sub_products": len(SUB_PRODUCTS),
        },
        "synthetic": True,
        "disclaimer": DISCLAIMER,
    }
