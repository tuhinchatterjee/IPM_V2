"""
Reading the published demo back, and rebuilding measurements from it.

Every figure the Cockpit reports at request time comes from the PUBLISHED
data — the Parquet lake through the governed Data Access Layer — not from the
generator. That distinction matters: if the answer path could call the
generator it would be answering from the model that made the data rather than
from the data, and a corrupted or stale publish would go unnoticed.

`measurements_for` rebuilds a `FacilityMeasurement` for every facility in a
quarter out of the stored risk curves and snapshot columns, so the attribution
engine evaluates the SAME inputs a reader can see in the dataset. Brief §4.2
asks for exactly that reproducibility.

Every read goes through `scope.permit`.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import pandas as pd

from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import catalogue as catalogue_mod
from backend.cockpit_v2 import ecl as ecl_mod
from backend.cockpit_v2 import scope as scope_mod

logger = logging.getLogger(__name__)


class NotPublished(LookupError):
    """The requested quarter is not in the lake. Said, never substituted."""


def _read(dataset: str, principal: Any = None,
          where: dict[str, Any] | None = None) -> pd.DataFrame:
    """One governed dataset, or the part of it matching `where`."""
    from pathlib import Path

    from backend.config import settings

    name = scope_mod.permit(dataset, principal)
    directory = Path(settings.analytics_dir) / name
    if not directory.exists():
        raise NotPublished(
            f"{name!r} has not been published in this runtime. Run "
            f"scripts/build_cockpit_v2_demo.py to build the Cockpit demo.")
    frame = pd.read_parquet(directory)
    for column, value in (where or {}).items():
        if column in frame.columns:
            frame = (frame[frame[column].isin(value)]
                     if isinstance(value, (list, tuple, set))
                     else frame[frame[column] == value])
    return frame.reset_index(drop=True)


def published_quarters(principal: Any = None) -> list[str]:
    """The quarters actually in the lake, newest last."""
    from pathlib import Path

    from backend.config import settings

    root = Path(settings.analytics_dir)
    out = [q for q in cal.QUARTERS
           if (root / cal.dataset_name(q)).exists()
           and scope_mod.is_allowed(cal.dataset_name(q))]
    if principal is not None:
        allowed = scope_mod.permitted_for(principal).datasets
        out = [q for q in out if cal.dataset_name(q) in allowed]
    return out


def latest_quarter(principal: Any = None) -> str:
    """The latest COMPLETED published quarter — the Cockpit's default scope."""
    quarters = published_quarters(principal)
    if not quarters:
        raise NotPublished(
            "No Cockpit demo quarter has been published in this runtime.")
    return quarters[-1]


def resolve_period_pair(*, to_period: str = "", from_period: str = "",
                        principal: Any = None) -> dict[str, Any]:
    """Which two quarters a movement question is about, and why.

    Defaults to the latest completed quarter against the one before it, and
    SAYS SO. When the prior quarter is not published it reports that rather
    than reaching for an arbitrary other dataset — brief §3.1's rule.
    """
    quarters = published_quarters(principal)
    if not quarters:
        raise NotPublished(
            "No Cockpit demo quarter has been published in this runtime.")

    closing = ""
    if to_period:
        try:
            candidate = cal.parse(to_period).label
        except ValueError:
            candidate = ""
        if candidate and candidate in quarters:
            closing = candidate
        elif candidate:
            return {"available": False, "closing": candidate, "opening": "",
                    "published": quarters,
                    "reason": (f"{cal.display(candidate)} is not loaded in "
                               f"this runtime. Published quarters are "
                               f"{', '.join(cal.display(q) for q in quarters)}.")}
    closing = closing or quarters[-1]

    opening = ""
    if from_period:
        try:
            candidate = cal.parse(from_period).label
        except ValueError:
            candidate = ""
        if candidate and candidate in quarters:
            opening = candidate
        elif candidate:
            return {"available": False, "closing": closing, "opening": candidate,
                    "published": quarters,
                    "reason": (f"{cal.display(candidate)} is not loaded, so it "
                               f"cannot be the comparison period. Published "
                               f"quarters are "
                               f"{', '.join(cal.display(q) for q in quarters)}.")}
    if not opening:
        index = quarters.index(closing)
        if index == 0:
            return {"available": False, "closing": closing, "opening": "",
                    "published": quarters,
                    "reason": (f"{cal.display(closing)} is the earliest "
                               f"published quarter, so there is no prior "
                               f"period to compare it with. No other dataset "
                               f"was substituted.")}
        opening = quarters[index - 1]

    return {"available": True, "opening": opening, "closing": closing,
            "opening_date": cal.iso(opening), "closing_date": cal.iso(closing),
            "opening_label": cal.display(opening),
            "closing_label": cal.display(closing),
            "published": quarters,
            "chosen_because": (
                "The closing period is the selected quarter and the opening "
                "period is the published quarter immediately before it."
                if not from_period else
                "Both periods were named in the request.")}


def snapshot(quarter: str, principal: Any = None) -> pd.DataFrame:
    """One quarter's facility snapshot."""
    return _read(cal.dataset_name(cal.parse(quarter).label), principal)


def history(principal: Any = None, quarters: Sequence[str] | None = None
            ) -> pd.DataFrame:
    """The authorised history interface across published quarters."""
    where = {"period": [cal.parse(q).label for q in quarters]} if quarters else None
    return _read(catalogue_mod.HISTORY_DATASET, principal, where)


def detail(dataset: str, quarter: str = "", principal: Any = None
           ) -> pd.DataFrame:
    where = {"period": cal.parse(quarter).label} if quarter else None
    return _read(dataset, principal, where)


def measurements_for(quarter: str, principal: Any = None,
                     facility_ids: Sequence[str] | None = None
                     ) -> dict[str, ecl_mod.FacilityMeasurement]:
    """Rebuild every facility's measurement from the PUBLISHED rows.

    The curves carry the whole per-period input set — hazard, severity, EAD and
    discount factor — and the snapshot carries the measurement window, the
    overlay, the method and the FX rate. That is everything the calculator
    needs, so the measurement reconstructed here is the one the published
    scenario ECL came from, and `verify_reconstruction` proves it rather than
    asserting it.
    """
    label = cal.parse(quarter).label
    snap = snapshot(label, principal)
    curves = detail("cockpit_risk_curves", label, principal)
    if facility_ids is not None:
        wanted = set(facility_ids)
        snap = snap[snap["facility_id"].isin(wanted)]
        curves = curves[curves["facility_id"].isin(wanted)]

    by_facility = {fid: group for fid, group in curves.groupby("facility_id")}
    out: dict[str, ecl_mod.FacilityMeasurement] = {}
    for _, row in snap.iterrows():
        fid = row["facility_id"]
        group = by_facility.get(fid)
        if group is None:
            continue
        scenarios: list[ecl_mod.ScenarioInput] = []
        for scenario_id, rows in group.groupby("scenario_id"):
            rows = rows.sort_values("future_period")
            scenarios.append(ecl_mod.ScenarioInput(
                scenario_id=str(scenario_id),
                weight=float(rows["scenario_weight"].iloc[0]),
                hazard=tuple(float(x) for x in rows["conditional_hazard"]),
                lgd=tuple(float(x) for x in rows["loss_severity"]),
                ead=tuple(float(x) for x in rows["ead_at_default"]),
                discount=tuple(float(x) for x in rows["discount_factor"])))
        if not scenarios:
            continue
        out[fid] = ecl_mod.FacilityMeasurement(
            facility_id=str(fid), borrower_id=str(row["borrower_id"]),
            reporting_date=str(row["reporting_date"]),
            stage=int(row["stage"]),
            horizon_periods=int(row["measurement_horizon_periods"]),
            scenarios=tuple(scenarios), overlay=float(row["overlay"]),
            currency=str(row["reporting_currency"]),
            fx_rate=float(row["fx_rate"]),
            method=str(row["measurement_method"]))
    return out


def verify_reconstruction(quarter: str, principal: Any = None,
                          tolerance: float = 1e-8) -> dict[str, Any]:
    """Check that the rebuilt measurements reproduce the published ECL.

    Run on every request that uses the attribution engine. If the lake and the
    stored ECL ever disagreed, the Cockpit would report a bridge over numbers
    the dataset does not contain, and the honest response is to say so rather
    than to produce a confident reconciliation of the wrong thing.
    """
    label = cal.parse(quarter).label
    snap = snapshot(label, principal).set_index("facility_id")
    rebuilt = measurements_for(label, principal)
    worst = 0.0
    worst_facility = ""
    for fid, measurement in rebuilt.items():
        if fid not in snap.index:
            continue
        recomputed = ecl_mod.measure(measurement).reported_ecl
        published = float(snap.loc[fid, "reported_ecl"])
        gap = abs(recomputed - published)
        if gap > worst:
            worst, worst_facility = gap, fid
    return {"quarter": label, "facilities": len(rebuilt),
            "worst_discrepancy": worst, "worst_facility": worst_facility,
            "tolerance": tolerance, "matches": worst <= tolerance}


__all__ = ["NotPublished", "detail", "history", "latest_quarter",
           "measurements_for", "published_quarters", "resolve_period_pair",
           "snapshot", "verify_reconstruction"]
