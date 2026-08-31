"""
Covenant intelligence. §32.

A covenant is a promise with a number attached, and the number is only
meaningful next to three others: what was promised, what was observed, and how
old the statements the observation came from are.

That last one is the reason this reader exists rather than a column on a
screen. A borrower comfortably inside every covenant, tested on financials
eighteen months old, is not a borrower comfortably inside every covenant - it
is a borrower nobody has tested recently, and the headroom shown is
historical. A reading that reports the headroom without the statement age is
reporting a reassurance it has not earned.

Each covenant is read individually and named. A borrower's covenant position
is not one number; collapsing four tests into "minimum headroom 8%" hides
which promise is tight and what it was about.
"""

from __future__ import annotations

from typing import Any

from backend.intelligence import (
    CONCERN,
    COVENANT,
    SEVERE,
    WATCH,
    Finding,
    Missing,
    Reading,
    and_list,
    number,
    truthy,
)
from backend.intelligence import reader as rd

DATASET = "corporate_covenants"

#: Headroom below which a covenant is worth a sentence. Seeded defaults owned
#: by Credit Risk Analytics, said to be so wherever they are shown.
TIGHT_HEADROOM_PCT = 10.0
NARROW_HEADROOM_PCT = 25.0

#: Statements older than this make a test historical rather than current. A
#: year: two quarterly tests will have been run on the same accounts by then.
STALE_STATEMENT_DAYS = 365


def read(borrower_id: str, period: str = "") -> Reading:
    """One borrower's covenant position, test by test."""
    frame = rd.load(DATASET)
    if frame is None:
        return Reading(domain=COVENANT, borrower_id=borrower_id, period=period,
                       missing=[Missing(
                           "Covenant tests",
                           "This deployment does not carry the covenant "
                           "dataset, so no promise can be tested.")])

    chosen, prior = rd.resolve(frame, period)
    if not chosen:
        return Reading(domain=COVENANT, borrower_id=borrower_id, period=period,
                       missing=[Missing(
                           "Covenant tests",
                           f"{period or 'That period'} is not a reporting "
                           "date this dataset holds.")])

    rows = rd.rows_for(frame, borrower_id, chosen)
    if not rows:
        return Reading(domain=COVENANT, borrower_id=borrower_id, period=chosen,
                       missing=[Missing(
                           "Covenant tests",
                           f"No covenant is recorded against {borrower_id} at "
                           f"{chosen}. That means no promise is on file, not "
                           "that every promise is being kept.")])

    before = {str(r.get("covenant_id") or r.get("covenant_name")): r
              for r in rd.rows_for(frame, borrower_id, prior)}
    reading = Reading(domain=COVENANT, borrower_id=borrower_id, period=chosen)
    reading.measured = _measured(rows, prior)

    for row in sorted(rows, key=lambda r: str(r.get("covenant_name") or "")):
        reading.findings.extend(_one(row, before, chosen))

    stale = [r for r in rows
             if (number(r.get("statement_age_days")) or 0)
             > STALE_STATEMENT_DAYS]
    if stale:
        oldest = max(number(r.get("statement_age_days")) or 0 for r in stale)
        reading.findings.append(Finding(
            key="tested_on_old_statements",
            label=f"{len(stale)} of {len(rows)} tests run on statements over "
                  f"a year old",
            means=("The headroom shown for these covenants was measured "
                   "against financials that are now historical. Comfortable "
                   "headroom on stale accounts is not comfortable headroom. "
                   "The one-year threshold is a seeded default owned by "
                   "Credit Risk Analytics."),
            severity=CONCERN, value=int(oldest),
            threshold=STALE_STATEMENT_DAYS,
            test="statement_age_days above", dataset=DATASET,
            field_name="statement_age_days", period=chosen))

    return reading


def _one(row: dict[str, Any], before: dict[str, dict[str, Any]],
         period: str) -> list[Finding]:
    """One covenant, read on its own terms."""
    name = str(row.get("covenant_name") or row.get("covenant_id") or
               "A covenant")
    key = str(row.get("covenant_id") or name).lower().replace(" ", "_")
    headroom = number(row.get("headroom_pct"))
    prior_row = before.get(str(row.get("covenant_id") or name)) or {}
    was = number(prior_row.get("headroom_pct"))
    direction = str(row.get("direction") or "").upper()
    limit = number(row.get("threshold"))
    observed = number(row.get("observed_value"))
    found: list[Finding] = []

    if truthy(row.get("breach_flag")):
        waived = truthy(row.get("waiver_granted"))
        found.append(Finding(
            key=f"breach_{key}",
            label=f"{name} breached" + (" (waived)" if waived else ""),
            means=(
                f"The {direction.lower() or 'tested'} limit is {limit} and "
                f"the observed value is {observed}. "
                + ("A waiver is recorded, so the breach is acknowledged "
                   "rather than outstanding - a waiver removes the "
                   "consequence, not the fact."
                   if waived else
                   "No waiver is recorded against it.")),
            severity=CONCERN if waived else SEVERE,
            value=observed, previous=number(prior_row.get("observed_value")),
            threshold=limit, test=f"observed value past the {direction} limit",
            dataset=DATASET, field_name="breach_flag", period=period))
        return found

    if headroom is None:
        found.append(Finding(
            key=f"untested_{key}",
            label=f"{name} has no headroom recorded",
            means=("The covenant is on file and no headroom is recorded "
                   "against it at this reporting date, so it cannot be said "
                   "to be met or breached."),
            severity=WATCH, value=None, threshold=limit,
            test="headroom_pct is absent", dataset=DATASET,
            field_name="headroom_pct", period=period))
        return found

    if headroom < TIGHT_HEADROOM_PCT:
        found.append(Finding(
            key=f"tight_{key}",
            label=f"{name} has {headroom:.1f}% headroom",
            means=(f"Less than a tenth of the room this covenant allows is "
                   f"left. The limit is {limit} and the observed value is "
                   f"{observed}. The threshold for calling headroom tight is "
                   "a seeded default owned by Credit Risk Analytics."),
            severity=CONCERN, value=headroom, previous=was,
            threshold=TIGHT_HEADROOM_PCT, test="headroom_pct below",
            dataset=DATASET, field_name="headroom_pct", period=period))
    elif headroom < NARROW_HEADROOM_PCT:
        found.append(Finding(
            key=f"narrow_{key}",
            label=f"{name} has {headroom:.1f}% headroom",
            means=(f"Under a quarter of the room this covenant allows is "
                   f"left. The limit is {limit} and the observed value is "
                   f"{observed}."),
            severity=WATCH, value=headroom, previous=was,
            threshold=NARROW_HEADROOM_PCT, test="headroom_pct below",
            dataset=DATASET, field_name="headroom_pct", period=period))

    if was is not None and headroom is not None and was - headroom >= 5.0:
        found.append(Finding(
            key=f"narrowed_{key}",
            label=f"{name} headroom fell {was - headroom:.1f} points",
            means=("The room under this covenant narrowed materially between "
                   "the two reporting dates. A covenant with wide headroom "
                   "that is closing fast is a different situation from one "
                   "that has always been wide."),
            severity=CONCERN, value=headroom, previous=was, threshold=5.0,
            test="headroom_pct fell by at least", dataset=DATASET,
            field_name="headroom_pct", period=period))

    return found


def _measured(rows: list[dict[str, Any]], prior: str) -> dict[str, Any]:
    headrooms = [h for h in (number(r.get("headroom_pct")) for r in rows)
                 if h is not None]
    ages = [a for a in (number(r.get("statement_age_days")) for r in rows)
            if a is not None]
    return {
        "covenants_on_file": len(rows),
        "names": and_list(sorted(
            {str(r.get("covenant_name") or "") for r in rows} - {""})),
        "breached": sum(1 for r in rows if truthy(r.get("breach_flag"))),
        "waived": sum(1 for r in rows if truthy(r.get("waiver_granted"))),
        "minimum_headroom_pct": min(headrooms) if headrooms else None,
        "average_headroom_pct": (round(sum(headrooms) / len(headrooms), 4)
                                 if headrooms else None),
        "oldest_statement_days": int(max(ages)) if ages else None,
        "prior_period": prior,
        "next_test_dates": sorted(
            {str(r.get("next_test_date") or "") for r in rows} - {""}),
        "means": {
            "minimum_headroom_pct":
                "The tightest single covenant, not an average. An average "
                "across four covenants hides the one that is about to go.",
            "oldest_statement_days":
                "How old the financials behind the oldest test are. Headroom "
                "measured on stale accounts is historical.",
        },
    }


__all__ = ["DATASET", "NARROW_HEADROOM_PCT", "STALE_STATEMENT_DAYS",
           "TIGHT_HEADROOM_PCT", "read"]
