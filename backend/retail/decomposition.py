"""Why a delinquency rate moved: the stock that moved, then the loss it caused.

The failure this exists for
---------------------------
Asked "what is the reason of this rise?" inside an investigation opened from
the case *Credit Card 30+ DPD has risen for five consecutive months*, the
product answered:

    Gross carrying amount rose from 5,085,320,995 to 6,388,268,769 SAR
    between 2025-08 and 2026-08 — a change of 1,302,947,774 SAR (25.62%).

Three things are wrong with that and none of them is the arithmetic. The
product scope is gone, the metric is not the one the case is about, and the
window is a year rather than the month the case moved in. It answers a
question nobody asked, confidently.

What a real answer has to do
----------------------------
**Explain the stock before discussing the model.** A delinquency rate is a
count of facilities in a state at a date. It moves because facilities changed
state, because the denominator changed, or because the population changed —
and those are observable. A PD is none of those things: a model can revise its
expectation without a single customer missing a payment, so a rise in PD is
never the *reason* an arrears rate rose. It is a separate consequence.

**Show the improvements.** A book can worsen in aggregate while thousands of
accounts cure. Reporting only the flows into arrears makes the deterioration
look one-directional when it is not, and the cures are the part a collections
head is being judged on.

**Reconcile.** The bridge adds to the observed change in the rate, or it is
decoration. Every term here is a difference between two quantities that were
each computed from the data, and the residual is published rather than
absorbed.

The mix / within-rate bridge
----------------------------
For mutually exclusive segments with rates r and weights w, the symmetric
decomposition the contract names:

    change = Σ (w1 − w0)(r0 + r1)/2   +   Σ (r1 − r0)(w0 + w1)/2
             └──── mix ────────────┘      └──── within ───────┘

It is exact for any two periods — the two halves sum to r1·w1 − r0·w0 term by
term — and symmetric, so it does not depend on which period is called the
base. That matters because an asymmetric version quietly attributes the
interaction to whichever side the author happened to expand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.retail import metric_registry as MR
from backend.retail import periods as P

METHOD_VERSION = "retail-delinquency-decomposition-1.0.0"

#: The governed taxonomy, worst last. The order is the analysis: "worse" and
#: "better" are positions in this list, not opinions.
BUCKETS: tuple[str, ...] = ("CURRENT", "1-29", "30-59", "60-89", "90-179", "180+")
BUCKET_RANK: dict[str, int] = {name: n for n, name in enumerate(BUCKETS)}

#: Buckets that count toward a 30+ rate.
THIRTY_PLUS: tuple[str, ...] = ("30-59", "60-89", "90-179", "180+")

ENTERED = "entered the book"
LEFT = "left the book"


def _bucket(frame: pd.DataFrame) -> pd.Series:
    """The governed bucket label, normalised, with anything unknown named."""
    held = frame["dpd_bucket"].astype(str).str.upper().str.strip()
    return held.where(held.isin([one.upper() for one in BUCKETS]), "UNKNOWN")


def _canonical(label: str) -> str:
    for one in BUCKETS:
        if one.upper() == str(label).upper():
            return one
    return str(label)


@dataclass
class Transitions:
    """Where every facility went between two months, and what it carried."""

    month: str
    prior: str
    scope: dict[str, Any]
    matrix: list[dict[str, Any]] = field(default_factory=list)
    entrants: dict[str, Any] = field(default_factory=dict)
    exits: dict[str, Any] = field(default_factory=dict)
    matched_facilities: int = 0
    worsened: dict[str, Any] = field(default_factory=dict)
    cured: dict[str, Any] = field(default_factory=dict)
    held: dict[str, Any] = field(default_factory=dict)
    into_thirty_plus: dict[str, Any] = field(default_factory=dict)
    out_of_thirty_plus: dict[str, Any] = field(default_factory=dict)
    method_version: str = METHOD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "month": self.month, "prior": self.prior, "scope": self.scope,
            "buckets": list(BUCKETS), "matrix": self.matrix,
            "entrants": self.entrants, "exits": self.exits,
            "matched_facilities": self.matched_facilities,
            "worsened": self.worsened, "cured": self.cured, "held": self.held,
            "into_thirty_plus": self.into_thirty_plus,
            "out_of_thirty_plus": self.out_of_thirty_plus,
            "method_version": self.method_version,
            "definition": (
                "Facilities matched on facility_id across the two months. A "
                "facility present in only one of them is an entrant or an "
                "exit and is reported separately; neither is allowed to "
                "appear as a migration."),
        }


def _side(frame: pd.DataFrame, carry: tuple[str, ...] = ()) -> pd.DataFrame:
    """The columns a transition needs, and any the caller adds.

    `carry` exists because the two dimensions a reader most wants to cut by —
    salaried / non-salaried and the Saudi sub-product tier — are DERIVED and
    are attached to the frame by the caller. A fixed keep-list dropped them
    silently, so a mix bridge asked for by sub-product answered by product and
    said nothing about it.
    """
    keep = ["facility_id", "customer_id", "dpd_bucket",
            "gross_carrying_amount_sar"]
    for maybe in ("dpd", "product_code", "ifrs9_stage", "current_default_flag",
                  "writeoff_flag", "writeoff_amount_month_sar",
                  "ecl_weighted_sar", "ecl_final_sar", *carry):
        if maybe in frame.columns and maybe not in keep:
            keep.append(maybe)
    out = frame[[c for c in keep if c in frame.columns]].copy()
    out["facility_id"] = out["facility_id"].astype(str)
    out["bucket"] = _bucket(out)
    out["gca"] = pd.to_numeric(out["gross_carrying_amount_sar"],
                               errors="coerce").fillna(0.0)
    return out


def transitions(opening: pd.DataFrame, closing: pd.DataFrame, *,
                month: str = "", prior: str = "",
                scope: dict[str, Any] | None = None) -> Transitions:
    """The observed DPD transition matrix on matched facilities."""
    left, right = _side(opening), _side(closing)
    joined = left.merge(right, on="facility_id", how="outer",
                        suffixes=("_open", "_close"), indicator=True)

    both = joined[joined["_merge"] == "both"]
    only_open = joined[joined["_merge"] == "left_only"]
    only_close = joined[joined["_merge"] == "right_only"]

    out = Transitions(month=month, prior=prior, scope=dict(scope or {}))
    out.matched_facilities = int(len(both))

    rows: list[dict[str, Any]] = []
    for source in BUCKETS:
        from_here = both[both["bucket_open"].str.upper() == source.upper()]
        source_count = int(len(from_here))
        source_open_gca = float(from_here["gca_open"].sum())
        for target in BUCKETS:
            cell = from_here[from_here["bucket_close"].str.upper()
                             == target.upper()]
            if not len(cell) and source_count == 0:
                continue
            rows.append({
                "from": source, "to": target,
                "facilities": int(len(cell)),
                "customers": int(cell["customer_id_open"].nunique())
                             if "customer_id_open" in cell else 0,
                "opening_exposure_sar": round(float(cell["gca_open"].sum()), 2),
                "closing_exposure_sar": round(float(cell["gca_close"].sum()), 2),
                "row_share_pct": round(len(cell) / source_count * 100, 4)
                                 if source_count else None,
                "row_exposure_share_pct": round(
                    float(cell["gca_open"].sum()) / source_open_gca * 100, 4)
                    if source_open_gca else None,
                "direction": ("worse" if BUCKET_RANK.get(target, 0)
                              > BUCKET_RANK.get(source, 0)
                              else "better" if BUCKET_RANK.get(target, 0)
                              < BUCKET_RANK.get(source, 0) else "held"),
            })
    out.matrix = rows

    worse = both[both.apply(
        lambda r: BUCKET_RANK.get(_canonical(r["bucket_close"]), -1)
        > BUCKET_RANK.get(_canonical(r["bucket_open"]), -1), axis=1)] \
        if len(both) else both
    better = both[both.apply(
        lambda r: BUCKET_RANK.get(_canonical(r["bucket_close"]), -1)
        < BUCKET_RANK.get(_canonical(r["bucket_open"]), -1), axis=1)] \
        if len(both) else both
    same = both[both["bucket_open"].str.upper()
                == both["bucket_close"].str.upper()]

    def _sum(frame: pd.DataFrame, opening_side: bool = True) -> dict[str, Any]:
        column = "gca_open" if opening_side else "gca_close"
        return {"facilities": int(len(frame)),
                "customers": int(frame["customer_id_open"].nunique())
                             if "customer_id_open" in frame and len(frame) else 0,
                "exposure_sar": round(float(frame[column].sum()), 2)
                                if len(frame) else 0.0}

    out.worsened = _sum(worse)
    out.cured = _sum(better)
    out.held = _sum(same)
    out.entrants = {
        "facilities": int(len(only_close)),
        "customers": int(only_close["customer_id_close"].nunique())
                     if len(only_close) else 0,
        "exposure_sar": round(float(only_close["gca_close"].sum()), 2)
                        if len(only_close) else 0.0,
        "in_thirty_plus": int((only_close["bucket_close"].str.upper()
                               .isin([one.upper() for one in THIRTY_PLUS])).sum())
                          if len(only_close) else 0,
    }
    out.exits = {
        "facilities": int(len(only_open)),
        "customers": int(only_open["customer_id_open"].nunique())
                     if len(only_open) else 0,
        "exposure_sar": round(float(only_open["gca_open"].sum()), 2)
                        if len(only_open) else 0.0,
        "from_thirty_plus": int((only_open["bucket_open"].str.upper()
                                 .isin([one.upper() for one in THIRTY_PLUS])).sum())
                            if len(only_open) else 0,
    }

    into = both[(~both["bucket_open"].str.upper()
                 .isin([one.upper() for one in THIRTY_PLUS]))
                & (both["bucket_close"].str.upper()
                   .isin([one.upper() for one in THIRTY_PLUS]))]
    outof = both[(both["bucket_open"].str.upper()
                  .isin([one.upper() for one in THIRTY_PLUS]))
                 & (~both["bucket_close"].str.upper()
                    .isin([one.upper() for one in THIRTY_PLUS]))]
    out.into_thirty_plus = _sum(into, opening_side=False)
    out.out_of_thirty_plus = _sum(outof, opening_side=False)
    return out


# ------------------------------------------------------- the rate bridge

def rate_bridge(opening: pd.DataFrame, closing: pd.DataFrame, *,
                weighting: str = "exposure") -> dict[str, Any]:
    """Reconcile the change in the 30+ rate to the flows that caused it.

    The rate is numerator/denominator, and both move. So the bridge is built
    on the identity

        r1 − r0 = (N1 − N0)/D1  +  N0 (1/D1 − 1/D0)

    — the numerator effect measured at the closing denominator, and the
    denominator effect measured on the opening numerator. It is exact, and
    each half is then split into the flows that produced it, which are
    observable rather than inferred.
    """
    left, right = _side(opening), _side(closing)
    late = [one.upper() for one in THIRTY_PLUS]

    def _num_den(frame: pd.DataFrame) -> tuple[float, float]:
        mask = frame["bucket"].str.upper().isin(late)
        if weighting == "exposure":
            return float(frame.loc[mask, "gca"].sum()), float(frame["gca"].sum())
        return float(mask.sum()), float(len(frame))

    n0, d0 = _num_den(left)
    n1, d1 = _num_den(right)
    r0 = n0 / d0 if d0 else 0.0
    r1 = n1 / d1 if d1 else 0.0

    numerator_effect = (n1 - n0) / d1 if d1 else 0.0
    denominator_effect = n0 * ((1 / d1 if d1 else 0.0) - (1 / d0 if d0 else 0.0))

    # The numerator's own movement, split by observable flow.
    joined = left.merge(right, on="facility_id", how="outer",
                        suffixes=("_open", "_close"), indicator=True)
    both = joined[joined["_merge"] == "both"]
    only_open = joined[joined["_merge"] == "left_only"]
    only_close = joined[joined["_merge"] == "right_only"]

    def _weight(frame: pd.DataFrame, column: str) -> float:
        if not len(frame):
            return 0.0
        return (float(frame[column].sum()) if weighting == "exposure"
                else float(len(frame)))

    open_late = both["bucket_open"].str.upper().isin(late)
    close_late = both["bucket_close"].str.upper().isin(late)

    new_arrears = both[~open_late & close_late]
    cures = both[open_late & ~close_late]
    stayed = both[open_late & close_late]
    entrant_late = only_close[only_close["bucket_close"].str.upper().isin(late)]
    exit_late = only_open[only_open["bucket_open"].str.upper().isin(late)]

    flows = [
        {"flow": "New arrears",
         "detail": "facilities that were not 30+ last month and are now",
         "facilities": int(len(new_arrears)),
         "amount": round(_weight(new_arrears, "gca_close"), 2),
         "sign": "+"},
        {"flow": "Cures",
         "detail": "facilities that were 30+ last month and are not now",
         "facilities": int(len(cures)),
         "amount": round(-_weight(cures, "gca_open"), 2),
         "sign": "−"},
        {"flow": "Balance movement on accounts that stayed 30+",
         "detail": "no state change; the exposure behind it moved",
         "facilities": int(len(stayed)),
         "amount": round(_weight(stayed, "gca_close")
                         - _weight(stayed, "gca_open"), 2)
                   if weighting == "exposure" else 0.0,
         "sign": "±"},
        {"flow": "Entrants already 30+",
         "detail": "facilities new to the book that arrived in arrears",
         "facilities": int(len(entrant_late)),
         "amount": round(_weight(entrant_late, "gca_close"), 2),
         "sign": "+"},
        {"flow": "Exits that were 30+",
         "detail": "written off, closed or sold while in arrears",
         "facilities": int(len(exit_late)),
         "amount": round(-_weight(exit_late, "gca_open"), 2),
         "sign": "−"},
    ]

    flow_total = sum(one["amount"] for one in flows)
    residual = (n1 - n0) - flow_total

    return {
        "weighting": weighting,
        "metric_id": ("ret.dpd30.exposure" if weighting == "exposure"
                      else "ret.dpd30.accounts"),
        "opening": {"numerator": round(n0, 2), "denominator": round(d0, 2),
                    "rate_pct": round(r0 * 100, 4)},
        "closing": {"numerator": round(n1, 2), "denominator": round(d1, 2),
                    "rate_pct": round(r1 * 100, 4)},
        "change_pp": round((r1 - r0) * 100, 4),
        "change_relative_pct": round((r1 / r0 - 1) * 100, 4) if r0 else None,
        "parts": [
            {"part": "Arrears moved",
             "detail": "the change in the numerator, measured at this "
                       "month's denominator",
             "contribution_pp": round(numerator_effect * 100, 4)},
            {"part": "The book moved",
             "detail": "the change in the denominator, measured on last "
                       "month's numerator",
             "contribution_pp": round(denominator_effect * 100, 4)},
        ],
        "numerator_flows": flows,
        "numerator_change": round(n1 - n0, 2),
        "flow_residual": round(residual, 2),
        "reconciles": abs((numerator_effect + denominator_effect)
                          - (r1 - r0)) < 1e-9 and abs(residual) < 0.5,
        "identity": "r1 − r0 = (N1 − N0)/D1 + N0(1/D1 − 1/D0)",
        "method_version": METHOD_VERSION,
        "caution": (
            "These are observed state changes. A change in modelled PD is not "
            "among them: a model may revise its expectation without any "
            "customer missing a payment, so it cannot be a reason an arrears "
            "rate moved. Its effect on the loss allowance is the separate "
            "ECL bridge."),
    }


# ------------------------------------------------------ the mix bridge

def mix_bridge(opening: pd.DataFrame, closing: pd.DataFrame, *,
               by: str = "product_code",
               weighting: str = "exposure") -> dict[str, Any]:
    """Symmetric mix / within-rate split of a rate change across segments."""
    left, right = _side(opening, (by,)), _side(closing, (by,))
    if by not in left.columns or by not in right.columns:
        return {"available": False,
                "because": f"the book does not carry {by!r}"}
    late = [one.upper() for one in THIRTY_PLUS]

    def _profile(frame: pd.DataFrame) -> dict[str, tuple[float, float]]:
        out: dict[str, tuple[float, float]] = {}
        weight_total = (float(frame["gca"].sum()) if weighting == "exposure"
                        else float(len(frame)))
        for name, part in frame.groupby(frame[by].astype(str)):
            mask = part["bucket"].str.upper().isin(late)
            if weighting == "exposure":
                weight = float(part["gca"].sum())
                rate = (float(part.loc[mask, "gca"].sum()) / weight
                        if weight else 0.0)
            else:
                weight = float(len(part))
                rate = float(mask.sum()) / weight if weight else 0.0
            out[name] = (rate, weight / weight_total if weight_total else 0.0)
        return out

    before, after = _profile(left), _profile(right)
    names = sorted(set(before) | set(after))
    rows, mix_total, within_total = [], 0.0, 0.0
    for name in names:
        r0, w0 = before.get(name, (0.0, 0.0))
        r1, w1 = after.get(name, (0.0, 0.0))
        mix = (w1 - w0) * (r0 + r1) / 2
        within = (r1 - r0) * (w0 + w1) / 2
        mix_total += mix
        within_total += within
        rows.append({
            "segment": name,
            "rate_before_pct": round(r0 * 100, 4),
            "rate_after_pct": round(r1 * 100, 4),
            "weight_before_pct": round(w0 * 100, 4),
            "weight_after_pct": round(w1 * 100, 4),
            "mix_pp": round(mix * 100, 4),
            "within_pp": round(within * 100, 4),
            "total_pp": round((mix + within) * 100, 4),
        })

    overall_before = sum(r * w for r, w in before.values())
    overall_after = sum(r * w for r, w in after.values())
    observed = overall_after - overall_before
    return {
        "available": True,
        "by": by, "weighting": weighting,
        "segments": sorted(rows, key=lambda one: -abs(one["total_pp"])),
        "mix_pp": round(mix_total * 100, 4),
        "within_pp": round(within_total * 100, 4),
        "total_pp": round((mix_total + within_total) * 100, 4),
        "observed_change_pp": round(observed * 100, 4),
        "residual_pp": round((observed - (mix_total + within_total)) * 100, 6),
        "reconciles": abs(observed - (mix_total + within_total)) < 1e-9,
        "formula": "Σ(w1−w0)(r0+r1)/2 + Σ(r1−r0)(w0+w1)/2",
        "note": ("Symmetric, so it does not depend on which period is taken "
                 "as the base. Entrants and exits are inside their segment's "
                 "weight and rate; the transition matrix separates them."),
        "method_version": METHOD_VERSION,
    }
