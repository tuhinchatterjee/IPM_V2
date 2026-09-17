"""What each measure in a retail investigation means, before anybody quotes it.

The defect this exists for
--------------------------
Four numbers in these stories are routinely mistaken for each other:

* the *share of the book* sitting in 1-29 DPD this month,
* the *rate at which facilities rolled* from current into 1-29 this month,
* the *observed default rate* of a vintage over a named matured window,
* and the model's *probability of default* over the next twelve months.

They answer different questions, they have different denominators, and three
of them cannot be derived from the others. A reader who is shown one and told
it is another has been misled even when every digit is right, so each measure
here carries its grain, its denominator, its window and — explicitly — the
inference it does not support.

Nothing in this module computes anything. It is the dictionary the computing
modules cite, so that a chart, a drawer figure, an exported column and a
thread answer that all claim to be "the 1-29 rate" are provably the same
definition rather than four sentences that happen to agree today.

The prohibitions are not decoration. They are the specification's own
"Do not" column, kept beside the definition so that removing the caveat means
editing the definition it belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Bumped when a definition below changes meaning. A snapshot records the
#: version it was measured under, so a figure quoted from an old snapshot can
#: never be silently re-read under a newer definition.
VERSION = "retail-metric-contract-1.0.0"


@dataclass(frozen=True)
class Metric:
    """One measure, with everything needed to quote it honestly."""

    metric_id: str
    label: str
    #: What is counted, one row at a time.
    grain: str
    #: What it is divided by. The single most common way these go wrong.
    denominator: str
    #: The period or observation window it is measured over.
    window: str
    definition: str
    #: The inference this measure does NOT support, in the reader's words.
    prohibited: str
    unit: str = "ratio"
    #: Lower is worse, higher is worse, or neither.
    direction: str = "higher_is_worse"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "label": self.label,
            "grain": self.grain,
            "denominator": self.denominator,
            "window": self.window,
            "definition": self.definition,
            "prohibited_inference": self.prohibited,
            "unit": self.unit,
            "direction": self.direction,
            "contract_version": VERSION,
        }


AFFECTED_POPULATION = Metric(
    metric_id="affected_population",
    label="Affected population",
    grain="facility or distinct customer, per the case's declared grain",
    denominator="eligible observations at the declared date",
    window="point in time, the declared as-of month",
    definition=(
        "The case predicate evaluated at the declared date. The eligible "
        "count is shown as the denominator, never implied."),
    prohibited=(
        "Stock is not migration. A rise in the share of the book sitting in a "
        "bucket cannot identify which facilities flowed into it."),
    unit="count",
)

ROLL_RATE = Metric(
    metric_id="roll_rate",
    label="Roll rate",
    grain="same facility, beginning bucket to ending bucket",
    denominator="eligible facilities in the beginning bucket at the start date",
    window="one month, start bucket to end bucket",
    definition=(
        "Facilities that began the period in the start bucket and ended it in "
        "the end bucket, divided by the facilities that began in the start "
        "bucket. Closures, write-offs, cures and new entrants are excluded "
        "from the numerator and labelled rather than dropped silently."),
    prohibited=(
        "Never inferred from the difference between two stock percentages. "
        "Two stock rates can move without a single facility rolling."),
)

ODR = Metric(
    metric_id="observed_default_rate",
    label="Observed default rate",
    grain="first default event per originally at-risk facility",
    denominator="the original at-risk population, including those later closed "
                "or paid off",
    window="a named matured window — C02 uses MOB6 cumulative first default, "
           "C10 uses six-month redefault after the arrangement",
    definition=(
        "Observed first default events inside a named matured window, over the "
        "population that was at risk when the window opened. Immature "
        "observations are excluded from the numerator AND the denominator."),
    prohibited=(
        "This is not PD, not an EWS band and not a 1-29 stock rate. Windows "
        "are not interchangeable: a MOB6 rate and a six-month redefault rate "
        "cannot be compared to each other."),
)

PD12 = Metric(
    metric_id="pd_12m",
    label="12-month probability of default",
    grain="facility, from the approved model",
    denominator="the eligible non-impaired cohort, preferably EAD-weighted",
    window="the next twelve months from the as-of date",
    definition=(
        "The approved model's forward probability, with horizon, "
        "point-in-time or through-cycle basis and scenario weighting stated. "
        "Compared only across the same eligible non-impaired cohort."),
    prohibited=(
        "Already-impaired accounts are not new forward-risk predictions. "
        "Where a comparable forward PD does not apply, the answer is N/A with "
        "stage shown separately — never a number."),
)

PD_LIFETIME = Metric(
    metric_id="pd_lifetime",
    label="Lifetime probability of default",
    grain="facility, from the approved model",
    denominator="the eligible non-impaired cohort, preferably EAD-weighted",
    window="the remaining contractual or behavioural life",
    definition=(
        "The approved model's lifetime term structure over the remaining "
        "horizon, on the same scenario basis as the 12-month figure."),
    prohibited=(
        "A lifetime figure is not twelve times a 12-month figure and is not "
        "comparable to it."),
)

APPLICATION_SCORE = Metric(
    metric_id="application_score",
    label="Original application score",
    grain="facility, at its own decision date",
    denominator="not applicable — an immutable per-decision value",
    window="fixed at origination",
    definition=(
        "The score the decision was actually taken on, with its input "
        "features, the model and policy version in force then, and the "
        "original decision date. It never changes."),
    prohibited=(
        "A change in the portfolio average is a change in the population "
        "mix. It is not the same customer's original score deteriorating, "
        "and no customer is ever rescored backwards."),
    direction="lower_is_worse",
    unit="points",
)

BEHAVIOUR_SCORE = Metric(
    metric_id="behaviour_score",
    label="Behavioural score",
    grain="facility, monthly observation",
    denominator="not applicable — a per-facility level",
    window="monthly, longitudinal on the same customers",
    definition=(
        "Same-customer observations through time under comparable model "
        "versions. Lower is worse. Where the model version changed, either a "
        "validated bridge is used or the series is shown as non-comparable."),
    prohibited=(
        "The arrears input must be separated from the other drivers before "
        "the fall is called evidence of anything beyond the arrears, and the "
        "temporal order must be verified rather than assumed."),
    direction="lower_is_worse",
    unit="points",
)

EWS = Metric(
    metric_id="ews_band",
    label="Early warning score and band",
    grain="customer and product, monthly",
    denominator="covered customer-products; coverage stated",
    window="the declared as-of month",
    definition=(
        "The governed score, band and reasons at customer-product grain, with "
        "model coverage and — where validated — the risk horizon exposed."),
    prohibited=(
        "High is elevated risk, not certainty of default, and says nothing "
        "about whether the customer is at 0 DPD today."),
)

CURRENT_BAD = Metric(
    metric_id="current_bad",
    label="Current bad",
    grain="facility",
    denominator="eligible facilities",
    window="the declared as-of month",
    definition=(
        "The approved current-bad rule. This fixture uses 30+ DPD."),
    prohibited=(
        "Do not subtract inconsistent card counts and call the remainder "
        "customers at DPD 0."),
)

FORWARD_RISK = Metric(
    metric_id="forward_risk",
    label="Forward risk",
    grain="customer-product",
    denominator="eligible customer-products not already current bad",
    window="the declared as-of month",
    definition=(
        "High or Critical EWS on a customer-product that is NOT currently "
        "bad. Forward risk and current bad are disjoint by construction."),
    prohibited=(
        "A forward-risk count is not a predicted number of defaults."),
)

ECL = Metric(
    metric_id="ecl",
    label="Expected credit loss",
    grain="facility",
    denominator="not applicable — a currency total",
    window="12-month for stage 1, lifetime for stages 2 and 3",
    definition=(
        "The approved stage-aware, probability-weighted, discounted loss on "
        "the governed term and cash-flow data, including overlays and "
        "approved modifications."),
    prohibited=(
        "A three-factor one-period PD x LGD x EAD display explains a "
        "component. It is not an IFRS 9 calculation and may not be presented "
        "as one."),
    unit="SAR",
)

EAD = Metric(
    metric_id="ead",
    label="Exposure at default",
    grain="facility",
    denominator="not applicable — a currency total",
    window="the declared as-of month",
    definition=(
        "Drawn exposure plus eligible expected future drawings under the CCF "
        "or behavioural exposure assumption."),
    prohibited=(
        "A limit cut does not repay drawn principal. Only the lawful "
        "remaining undrawn headroom can move."),
    unit="SAR",
)

CONCENTRATION = Metric(
    metric_id="concentration",
    label="Pocket concentration",
    grain="the named pocket against the rest of the eligible book",
    denominator="eligible observations, inside and outside the pocket "
                "separately",
    window="the declared as-of month",
    definition=(
        "Share of the eligible book, share of the cases, incidence inside the "
        "pocket and incidence outside it, each with its sample size, and the "
        "ratio between the two incidences."),
    prohibited=(
        "A large population count alone does not imply high risk. Vintage age "
        "and risk mix must be controlled before a pocket is blamed."),
)

SEVERITY = Metric(
    metric_id="severity",
    label="Case severity",
    grain="risk case occurrence",
    denominator="not applicable — a governed score",
    window="the case's own period and its persistence lookback",
    definition=(
        "The installed governed materiality arithmetic plus persistence, "
        "excess risk and evidence confidence. The arithmetic is retained in "
        "Trace so the band can be recomputed from the case's own figures."),
    prohibited=(
        "No threshold is moved to turn a demonstration card red, and no "
        "occurrence is duplicated to reach a target number of cards."),
    unit="score",
)

RECENT_CARD_ODR = Metric(
    metric_id="recent_card_odr",
    label="Saved-investigation observed default rate",
    grain="the saved cohort",
    denominator="the saved cohort's original at-risk count",
    window="the window named on the saved card",
    definition=(
        "Stored on the saved investigation with its value, numerator, "
        "denominator, horizon and source snapshot, so the card shows what was "
        "true when it was saved."),
    prohibited=(
        "Where the outcome window has not completed, the card reads "
        "'Not yet observed'. It never shows a fabricated rate."),
)

MISSINGNESS = Metric(
    metric_id="missingness",
    label="Coverage and missing data",
    grain="whatever the measure's own grain is",
    denominator="the eligible population for that measure",
    window="the declared as-of month",
    definition=(
        "A covered count and an explicit reason for every observation that is "
        "unavailable, stale, unverified or inapplicable. Those four are "
        "different states and are reported as different states."),
    prohibited=(
        "Missing income, EWS or PD is never filled with zero and never "
        "replaced by a figure from an unrelated cohort."),
)


ALL: tuple[Metric, ...] = (
    AFFECTED_POPULATION, ROLL_RATE, ODR, PD12, PD_LIFETIME,
    APPLICATION_SCORE, BEHAVIOUR_SCORE, EWS, CURRENT_BAD, FORWARD_RISK,
    ECL, EAD, CONCENTRATION, SEVERITY, RECENT_CARD_ODR, MISSINGNESS,
)

BY_ID: dict[str, Metric] = {m.metric_id: m for m in ALL}


def definition(metric_id: str) -> dict[str, Any]:
    """The dictionary entry a surface must cite when it shows a figure."""
    metric = BY_ID.get(metric_id)
    if metric is None:
        raise KeyError(
            f"{metric_id!r} is not a defined retail metric. A figure with no "
            f"definition may not be displayed; add it to "
            f"backend/retail/metrics_contract.py first.")
    return metric.to_dict()


def definitions(*metric_ids: str) -> list[dict[str, Any]]:
    return [definition(m) for m in metric_ids]


# ---------------------------------------------------------------------------
# Missing-data states
# ---------------------------------------------------------------------------
#
# Four states, deliberately not one. "We have no figure" and "the figure is
# zero" are opposite claims, and a chart that renders them identically is the
# specific way a coverage gap becomes an assertion that nothing is wrong.

UNAVAILABLE = "unavailable"      #: Never observed for this subject.
STALE = "stale"                  #: Observed, but older than the as-of date.
UNVERIFIED = "unverified"        #: Reported, but no authority has confirmed it.
INAPPLICABLE = "inapplicable"    #: The measure does not apply to this subject.
COVERED = "covered"              #: Present and current.

MISSING_STATES = (UNAVAILABLE, STALE, UNVERIFIED, INAPPLICABLE)

MISSING_REASONS = {
    UNAVAILABLE: "No observation exists for this subject at this date.",
    STALE: "The most recent observation predates the reporting date.",
    UNVERIFIED: "Reported but not confirmed by an authorised source.",
    INAPPLICABLE: "The measure does not apply to this subject.",
}


def coverage(*, covered: int, eligible: int,
             missing: dict[str, int] | None = None) -> dict[str, Any]:
    """A coverage statement that cannot be read as a zero."""
    missing = {k: int(v) for k, v in (missing or {}).items() if v}
    unknown = set(missing) - set(MISSING_STATES)
    if unknown:
        raise ValueError(
            f"{sorted(unknown)} are not missing-data states. Use one of "
            f"{list(MISSING_STATES)} so the reader is told WHY a figure is "
            f"absent rather than being shown a blank.")
    return {
        "covered": int(covered),
        "eligible": int(eligible),
        "coverage_pct": (round(covered / eligible * 100, 2)
                         if eligible else None),
        "missing": missing,
        "missing_reasons": {k: MISSING_REASONS[k] for k in missing},
        "complete": bool(eligible) and covered == eligible,
    }
