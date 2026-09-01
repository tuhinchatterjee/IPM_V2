"""
IFRS 9 intelligence. §30.

What the book SAYS about a borrower's impairment position, and why it says it.

The one rule that matters more than the rest: a stage is an accounting
classification that has already happened. "This borrower is in stage 2" and
"this borrower will move to stage 2" are different claims, and only the first
one is in this dataset. Every finding here is flagged ``booked_accounting`` so
that a screen, a case or an answer built on it cannot describe it as a
forecast without going out of its way.

The second rule: a SICR trigger is the REASON a stage moved, and reporting the
stage without the trigger is reporting a conclusion with the argument removed.
So the triggers are read individually - PD, days past due, watchlist - and
named.
"""

from __future__ import annotations

from typing import Any

from backend.intelligence import (
    CONCERN,
    IFRS9,
    SEVERE,
    WATCH,
    Finding,
    Missing,
    Reading,
    number,
    truthy,
)
from backend.intelligence import reader as rd

DATASET = "corporate_ifrs9"

#: Coverage above which the impairment on a name is worth a sentence of its
#: own. A seeded default owned by Credit Risk Analytics, not a regulatory
#: figure, and said to be one wherever it is shown.
HEAVY_COVERAGE_PCT = 5.0

#: An overlay is management judgement sitting on top of a model, so ANY
#: overlay is worth naming - a reader entitled to know how much of a number
#: is modelled and how much is decided. This is the share above which the
#: judgement stops being a small adjustment and becomes a material part of the
#: impairment.
#:
#: Set at a sixth rather than a fifth after checking what this book can
#: actually produce: the generator caps overlays just under 20% of final ECL,
#: so a threshold at 20% is a rule that can never fire - and a rule that never
#: fires reads on a screen exactly like a clean book.
MATERIAL_OVERLAY_SHARE = 0.15

STAGE_MEANS: dict[int, str] = {
    1: "Performing. Impairment is measured on twelve-month expected losses.",
    2: "A significant increase in credit risk has been recognised since "
       "origination, so impairment is measured over the lifetime of the "
       "exposure. This is the booked position, not a prediction.",
    3: "Credit-impaired. This is the booked position at this reporting date.",
}


def read(borrower_id: str, period: str = "") -> Reading:
    """One borrower's booked IFRS 9 position, with its reasons."""
    frame = rd.load(DATASET)
    if frame is None:
        return Reading(domain=IFRS9, borrower_id=borrower_id, period=period,
                       missing=[Missing(
                           "IFRS 9 position",
                           "This deployment does not carry the IFRS 9 "
                           "dataset, so no stage or ECL can be read.")])

    chosen, prior = rd.resolve(frame, period)
    if not chosen:
        return Reading(domain=IFRS9, borrower_id=borrower_id, period=period,
                       missing=[Missing(
                           "IFRS 9 position",
                           f"{period or 'That period'} is not a reporting "
                           "date this dataset holds.")])

    rows = rd.rows_for(frame, borrower_id, chosen)
    if not rows:
        return Reading(domain=IFRS9, borrower_id=borrower_id, period=chosen,
                       missing=[Missing(
                           "IFRS 9 position",
                           f"No IFRS 9 row is recorded for {borrower_id} at "
                           f"{chosen}. That is an absence of data, not an "
                           "absence of impairment.")])

    row = rows[0]
    before = (rd.rows_for(frame, borrower_id, prior) or [{}])[0]
    reading = Reading(domain=IFRS9, borrower_id=borrower_id, period=chosen)
    reading.measured = _measured(row, before, prior)

    stage = int(number(row.get("stage")) or 0)
    was = int(number(before.get("stage")) or 0) if before else 0

    if stage in (2, 3):
        reading.findings.append(Finding(
            key=f"stage_{stage}",
            label=f"Booked in stage {stage}",
            means=STAGE_MEANS.get(stage, ""),
            severity=SEVERE if stage == 3 else CONCERN,
            value=stage, previous=was or None, threshold=1,
            test="stage above 1", dataset=DATASET, field_name="stage",
            period=chosen, booked_accounting=True))

    if was and stage > was:
        reading.findings.append(Finding(
            key="stage_deteriorated",
            label=f"Moved from stage {was} to stage {stage}",
            means=("The classification worsened between the two reporting "
                   "dates. This records a move that has happened."),
            severity=SEVERE if stage == 3 else CONCERN,
            value=stage, previous=was, threshold=was,
            test="stage higher than the prior period", dataset=DATASET,
            field_name="stage", period=chosen, booked_accounting=True))
    elif was and stage < was:
        reading.findings.append(Finding(
            key="stage_improved",
            label=f"Moved back from stage {was} to stage {stage}",
            means=("The classification improved between the two reporting "
                   "dates. Named because a reading that shows only "
                   "deterioration is a reading somebody acts on wrongly."),
            severity=WATCH, value=stage, previous=was, threshold=was,
            test="stage lower than the prior period", dataset=DATASET,
            field_name="stage", period=chosen, booked_accounting=True))

    reading.findings.extend(_triggers(row, chosen))

    coverage = number(row.get("ecl_coverage"))
    if coverage is not None and coverage >= HEAVY_COVERAGE_PCT:
        reading.findings.append(Finding(
            key="heavy_coverage",
            label=f"ECL coverage at {coverage:.2f}%",
            means=("Impairment held against this exposure is heavy relative "
                   "to the book. The threshold is a seeded default owned by "
                   "Credit Risk Analytics, not a regulatory requirement."),
            severity=CONCERN, value=coverage,
            previous=number(before.get("ecl_coverage")) if before else None,
            threshold=HEAVY_COVERAGE_PCT, test="ecl_coverage at or above",
            dataset=DATASET, field_name="ecl_coverage", period=chosen,
            booked_accounting=True))

    overlay = number(row.get("management_overlay")) or 0.0
    final = number(row.get("final_ecl")) or 0.0
    if overlay > 0 and final > 0:
        share = overlay / final
        material = share >= MATERIAL_OVERLAY_SHARE
        reading.findings.append(Finding(
            key="overlay_material" if material else "overlay_applied",
            label=f"Management overlay is {share:.0%} of the ECL held",
            means=(
                ("A material part of the impairment on this name is judgement "
                 "applied on top of the model rather than the model's own "
                 "output. "
                 if material else
                 "Part of the impairment on this name is judgement applied on "
                 "top of the model rather than the model's own output. ")
                + "That is a legitimate position and it is one somebody "
                  "should know they are looking at. The materiality "
                  "threshold is a seeded default owned by Credit Risk "
                  "Analytics."),
            severity=CONCERN if material else WATCH,
            value=round(overlay, 4), previous=None,
            threshold=f"{MATERIAL_OVERLAY_SHARE:.0%} of final ECL",
            test="management_overlay over final_ecl at or above",
            dataset=DATASET, field_name="management_overlay",
            period=chosen, booked_accounting=True))

    if truthy(row.get("default_flag")):
        reading.findings.append(Finding(
            key="in_default",
            label="Flagged as in default",
            means="The borrower is recorded as in default at this reporting "
                  "date.",
            severity=SEVERE, value=True, threshold=True, test="is true",
            dataset=DATASET, field_name="default_flag", period=chosen,
            booked_accounting=True))

    return reading


def _triggers(row: dict[str, Any], period: str) -> list[Finding]:
    """Which SICR trigger moved this borrower, named individually.

    Reporting `sicr_flag` alone is reporting a conclusion with the argument
    removed - and the three triggers lead to three different conversations:
    a PD trigger is a model view, a days-past-due trigger is a fact about
    payments, a watchlist trigger is somebody's judgement.
    """
    if not truthy(row.get("sicr_flag")):
        return []
    named = [
        ("sicr_trigger_pd", "probability of default",
         "The model's PD has moved far enough from origination to signal a "
         "significant increase in credit risk."),
        ("sicr_trigger_dpd", "days past due",
         "Payments are far enough behind to trigger the test. This is a "
         "fact about the account, not a model view."),
        ("sicr_trigger_watchlist", "watchlist",
         "Somebody placed this borrower on the watchlist, and that placement "
         "is itself a trigger."),
    ]
    found = [(field, label, means) for field, label, means in named
             if truthy(row.get(field))]
    if not found:
        # The flag is set and no trigger explains it. Said, never smoothed
        # over: a conclusion with no argument behind it is exactly the thing
        # a reader needs to be told about.
        return [Finding(
            key="sicr_unexplained",
            label="SICR is flagged with no trigger recorded",
            means=("The significant-increase test is set for this borrower "
                   "but none of the three recorded triggers is. The "
                   "classification cannot be explained from this dataset."),
            severity=CONCERN, value=True, threshold=True,
            test="sicr_flag true with no trigger true", dataset=DATASET,
            field_name="sicr_flag", period=period, booked_accounting=True)]
    return [Finding(
        key=field,
        label=f"SICR triggered by {label}",
        means=means, severity=CONCERN, value=True, threshold=True,
        test="is true", dataset=DATASET, field_name=field, period=period,
        booked_accounting=True)
        for field, label, means in found]


def _measured(row: dict[str, Any], before: dict[str, Any],
              prior: str) -> dict[str, Any]:
    """The figures a reader wants in front of them either way."""
    return {
        "stage": number(row.get("stage")),
        "prior_stage": number(before.get("stage")) if before else None,
        "prior_period": prior,
        "pd_12m": number(row.get("pd_12m")),
        "pd_lifetime": number(row.get("pd_lifetime")),
        "lgd": number(row.get("lgd")),
        "ead": number(row.get("ead")),
        "ecl_12m": number(row.get("ecl_12m")),
        "ecl_lifetime": number(row.get("ecl_lifetime")),
        "management_overlay": number(row.get("management_overlay")),
        "final_ecl": number(row.get("final_ecl")),
        "ecl_coverage": number(row.get("ecl_coverage")),
        "current_dpd": number(row.get("current_dpd")),
        "scenario_weights": {
            "base": number(row.get("scenario_weight_base")),
            "upside": number(row.get("scenario_weight_upside")),
            "downside": number(row.get("scenario_weight_downside")),
        },
        "means": {
            "final_ecl": "The impairment held, after any management overlay.",
            "ecl_coverage": "Impairment held as a percentage of exposure.",
            "stage": "The BOOKED accounting classification at this reporting "
                     "date. Not a forecast.",
        },
    }


__all__ = ["DATASET", "HEAVY_COVERAGE_PCT", "MATERIAL_OVERLAY_SHARE",
           "STAGE_MEANS", "read"]
