"""
Collateral intelligence. §33.

Two numbers on every piece of security and they are not the same number.
Market value is what somebody thinks the asset is worth; eligible value is
what is left after the regulatory haircut, and it is the only one that counts
toward covering an exposure. A screen that shows "collateral: 340" without
saying which of the two it means is a screen somebody will read as the larger
figure, because that is the one they would rather see.

So this reader always reports both, always names which is which, and never
computes coverage from market value.

The second thing it refuses to do is treat an old valuation as a valuation. A
property carried at a number nobody has revisited in three years is not
security worth that number; it is security worth an unknown amount, and the
difference is the whole point of a revaluation policy. The dataset records the
policy interval per asset, so staleness is measured against the policy for
THAT asset rather than against one global rule.
"""

from __future__ import annotations

from typing import Any

from backend.intelligence import (
    COLLATERAL,
    CONCERN,
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

DATASET = "corporate_collateral"

#: The share of eligible value a haircut has to remove before it is worth
#: saying out loud. Seeded default owned by Credit Risk Analytics.
HEAVY_HAIRCUT_PCT = 50.0

#: A valuation this far past its own policy interval is stale enough to
#: report on its own rather than as part of a count.
BADLY_OVERDUE_DAYS = 365


def read(borrower_id: str, period: str = "") -> Reading:
    """One borrower's security, asset by asset."""
    frame = rd.load(DATASET)
    if frame is None:
        return Reading(domain=COLLATERAL, borrower_id=borrower_id,
                       period=period,
                       missing=[Missing(
                           "Collateral",
                           "This deployment does not carry the collateral "
                           "dataset, so no security can be valued.")])

    chosen, prior = rd.resolve(frame, period)
    if not chosen:
        return Reading(domain=COLLATERAL, borrower_id=borrower_id,
                       period=period,
                       missing=[Missing(
                           "Collateral",
                           f"{period or 'That period'} is not a reporting "
                           "date this dataset holds.")])

    rows = rd.rows_for(frame, borrower_id, chosen)
    if not rows:
        return Reading(domain=COLLATERAL, borrower_id=borrower_id,
                       period=chosen,
                       missing=[Missing(
                           "Collateral",
                           f"No collateral is recorded against {borrower_id} "
                           f"at {chosen}. The exposure may be unsecured, or "
                           "the security may simply not be on file - this "
                           "dataset cannot tell those apart, and reading it "
                           "as 'unsecured' would be reading in something "
                           "that is not there.")])

    reading = Reading(domain=COLLATERAL, borrower_id=borrower_id,
                      period=chosen)
    reading.measured = _measured(rows, prior)

    overdue = [r for r in rows if truthy(r.get("valuation_overdue"))]
    if overdue:
        eligible = sum(number(r.get("collateral_eligible_value")) or 0.0
                       for r in overdue)
        total = reading.measured["eligible_value"] or 0.0
        share = eligible / total if total else 0.0
        reading.findings.append(Finding(
            key="valuations_overdue",
            label=(f"{len(overdue)} of {len(rows)} valuations are past their "
                   "revaluation date"),
            means=(f"{share:.0%} of the post-haircut security on this "
                   "borrower is carried at a value nobody has revisited "
                   "within its own revaluation policy. A stale value is not "
                   "a value. Each asset is measured against the interval set "
                   "for that asset, not one global rule."),
            severity=CONCERN if share < 0.5 else SEVERE,
            value=round(eligible, 4), threshold="its own policy interval",
            test="valuation_overdue is true", dataset=DATASET,
            field_name="valuation_overdue", period=chosen))

    badly = [r for r in rows
             if (number(r.get("valuation_age_days")) or 0)
             - (number(r.get("revaluation_interval_days")) or 0)
             > BADLY_OVERDUE_DAYS]
    if badly:
        worst = max(int(number(r.get("valuation_age_days")) or 0)
                    for r in badly)
        reading.findings.append(Finding(
            key="valuation_badly_overdue",
            label=(f"A valuation is {worst} days old, more than a year past "
                   "its policy"),
            means=("This is not a valuation running slightly late. The asset "
                   "is being carried at a figure that predates its own "
                   "revaluation policy by more than a year."),
            severity=SEVERE, value=worst, threshold=BADLY_OVERDUE_DAYS,
            test="days past the policy interval above", dataset=DATASET,
            field_name="valuation_age_days", period=chosen))

    heavy = [r for r in rows
             if (number(r.get("regulatory_haircut_pct")) or 0)
             >= HEAVY_HAIRCUT_PCT]
    if heavy:
        types = and_list(sorted({str(r.get("collateral_type") or "")
                                 for r in heavy} - {""}))
        reading.findings.append(Finding(
            key="heavy_haircuts",
            label=f"Half or more of the market value is cut on {types}",
            means=("The regulatory haircut removes at least half of what "
                   "these assets are marked at, so the market value on the "
                   "file substantially overstates what the security is worth "
                   "against the exposure. Both figures are reported here "
                   "precisely so the larger one is not read as the answer."),
            severity=WATCH,
            value=max(number(r.get("regulatory_haircut_pct")) or 0
                      for r in heavy),
            threshold=HEAVY_HAIRCUT_PCT,
            test="regulatory_haircut_pct at or above", dataset=DATASET,
            field_name="regulatory_haircut_pct", period=chosen))

    concentration = _concentration(rows, reading.measured)
    if concentration:
        reading.findings.append(concentration)

    return reading


def _concentration(rows: list[dict[str, Any]],
                   measured: dict[str, Any]) -> Finding | None:
    """Security that is really one asset wearing several rows.

    Four charges over the same kind of asset in the same market is one bet,
    and a borrower whose security is one bet is differently secured from one
    whose security is spread - even where the totals match exactly.
    """
    total = measured.get("eligible_value") or 0.0
    if not total or len(rows) < 2:
        return None
    by_type: dict[str, float] = {}
    for row in rows:
        kind = str(row.get("collateral_type") or "Unclassified")
        by_type[kind] = by_type.get(kind, 0.0) + (
            number(row.get("collateral_eligible_value")) or 0.0)
    kind, value = max(by_type.items(), key=lambda item: (item[1], item[0]))
    share = value / total
    if share < 0.8:
        return None
    return Finding(
        key="collateral_concentrated",
        label=f"{share:.0%} of the eligible security is {kind}",
        means=("Several charges over one kind of asset are one bet, not "
               "several. If that market moves, the whole security position "
               "moves with it."),
        severity=WATCH, value=round(share * 100, 2), threshold=80.0,
        test="largest collateral type share at or above", dataset=DATASET,
        field_name="collateral_type", period=str(rows[0].get("period") or ""))


def _measured(rows: list[dict[str, Any]], prior: str) -> dict[str, Any]:
    market = sum(number(r.get("collateral_market_value")) or 0.0
                 for r in rows)
    eligible = sum(number(r.get("collateral_eligible_value")) or 0.0
                   for r in rows)
    ages = [a for a in (number(r.get("valuation_age_days")) for r in rows)
            if a is not None]
    return {
        "pieces": len(rows),
        "types": sorted({str(r.get("collateral_type") or "") for r in rows}
                        - {""}),
        "market_value": round(market, 4),
        "eligible_value": round(eligible, 4),
        "haircut_removed": round(market - eligible, 4),
        "oldest_valuation_days": int(max(ages)) if ages else None,
        "overdue_valuations": sum(1 for r in rows
                                  if truthy(r.get("valuation_overdue"))),
        "prior_period": prior,
        "means": {
            "market_value":
                "What the assets are marked at. NOT what they are worth "
                "against the exposure.",
            "eligible_value":
                "What is left after the regulatory haircut. This is the "
                "figure that covers exposure; the market value does not.",
            "haircut_removed":
                "The difference between the two, said out loud so neither "
                "figure can be mistaken for the other.",
        },
    }


__all__ = ["BADLY_OVERDUE_DAYS", "DATASET", "HEAVY_HAIRCUT_PCT", "read"]
