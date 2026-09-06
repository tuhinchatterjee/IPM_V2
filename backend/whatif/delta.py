"""
The Delta Model: what a scenario does to ECL, in factors a reader can check.

The reconciliation this module exists to make
---------------------------------------------
The product describes the Delta Model as

    What-If ECL = Official Baseline ECL x PD factor x LGD factor x EAD factor

and the governed engine measures ECL as

    ECL = PD_applicable x LGD x EAD x WEIGHTED_SCENARIO_FACTOR

with `PD_applicable` being the twelve-month PD in Stage 1 and the lifetime PD
in Stages 2 and 3. Those are the same statement, and it matters that they are:

    measured_stressed     PD_applicable_s   LGD_s   EAD_s
    ----------------- =   --------------- x ----- x -----
    measured_baseline     PD_applicable_b   LGD_b   EAD_b

because `WEIGHTED_SCENARIO_FACTOR` is on both sides and cancels. So the ratio
the engine already computes IS the product of the three factors the product
promises, and this module reports the factors separately rather than computing
the answer a second way. Two implementations of one number is how a screen ends
up disagreeing with the table underneath it.

Where a stage moves, the PD factor carries the stage effect too — the numerator
switches from the twelve-month PD to the lifetime PD — which is exactly why a
Stage 1 to Stage 2 migration raises the provision even when nothing else about
the borrower moved. That component is reported on its own so nobody mistakes it
for a PD deterioration.

Why the official ECL stays the anchor
-------------------------------------
The book's reported `final_ecl` includes a management overlay and whatever else
the bank booked. Re-deriving ECL from PD x LGD x EAD would silently discard
that and produce a "baseline" that does not tie to the accounts. So the
baseline column is the reported number untouched, and the scenario moves it by
the ratio. `measured_*` is used only to form the ratio, never to replace the
book.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.ifrs9 import policy

DELTA_MODEL = "delta"
DELTA_NAME = "Delta Model"
DELTA_VERSION = "1.0.0"
DELTA_OWNER = "Credit Risk Analytics"

#: Below this, a baseline measurement is treated as zero and the ratio is not
#: formed. A borrower with no measurable baseline has no percentage to move.
NEAR_ZERO = 1e-12


def _series(values: Any, index: pd.Index) -> pd.Series:
    return pd.to_numeric(pd.Series(values, index=index), errors="coerce").fillna(0.0)


def applicable_pd(stage: Any, pd_12m: Any, pd_lifetime: Any,
                  index: pd.Index) -> pd.Series:
    """The PD a borrower is measured on, given its Stage."""
    staged = _series(stage, index)
    twelve = _series(pd_12m, index)
    life = _series(pd_lifetime, index)
    return pd.Series(np.where(staged <= 1, twelve, life), index=index)


def ead_from_ccf(drawn: Any, undrawn: Any, ccf: Any, index: pd.Index) -> pd.Series:
    """EAD the way a CCF change actually reaches it.

        EAD = drawn + CCF x undrawn

    A CCF that rises from 50% to 60% is a 20% rise in the CCF and a very much
    smaller rise in EAD, because the drawn balance does not move at all. The
    product is explicit that these must not be equated, so the conversion is
    written out here rather than approximated by a percentage.
    """
    return (_series(drawn, index)
            + _series(ccf, index) * _series(undrawn, index)).clip(lower=0.0)


@dataclass(frozen=True)
class Factors:
    """The three factors, and the stage effect folded into the first."""

    pd_factor: float
    lgd_factor: float
    ead_factor: float
    stage_factor: float
    combined: float

    def to_dict(self) -> dict[str, Any]:
        return {"pd_factor": round(self.pd_factor, 6),
                "lgd_factor": round(self.lgd_factor, 6),
                "ead_factor": round(self.ead_factor, 6),
                "stage_factor": round(self.stage_factor, 6),
                "combined_factor": round(self.combined, 6),
                "rule": ("ECL factor = PD factor x LGD factor x EAD factor. "
                         "The stage factor is the part of the PD factor caused "
                         "by a change of measurement basis rather than by PD "
                         "deterioration."),
                }


def _ratio(after: pd.Series, before: pd.Series) -> pd.Series:
    """After over before, with a zero baseline left at 1.0 rather than infinite."""
    safe = before.where(before.abs() > NEAR_ZERO)
    return (after / safe).fillna(1.0).replace([np.inf, -np.inf], 1.0)


def factors(frame: pd.DataFrame, *,
            stage_baseline: str = "stage_baseline",
            stage_stressed: str = "stage_stressed",
            pd_baseline: str = "pd_12m",
            pd_stressed: str = "pd_stressed",
            lifetime_baseline: str = "pd_lifetime",
            lifetime_stressed: str = "pd_lifetime_stressed",
            lgd_baseline: str = "lgd",
            lgd_stressed: str = "lgd_stressed",
            ead_baseline: str = "ead",
            ead_stressed: str = "ead_stressed") -> pd.DataFrame:
    """Per-borrower factors, each one a number somebody can divide by hand.

    The stage factor is isolated by asking what the PD factor WOULD have been
    had the borrower stayed on its opening measurement basis. The remainder is
    the change of basis. Reported separately because "your ECL tripled" reads
    very differently from "your ECL tripled because the borrower moved to
    lifetime measurement".
    """
    index = frame.index
    base_stage = _series(frame.get(stage_baseline), index)
    stressed_stage = _series(frame.get(stage_stressed, frame.get(stage_baseline)), index)

    base_twelve = _series(frame.get(pd_baseline), index)
    base_life = _series(frame.get(lifetime_baseline), index)
    stress_twelve = _series(frame.get(pd_stressed, frame.get(pd_baseline)), index)
    stress_life = (_series(frame.get(lifetime_stressed), index)
                   if lifetime_stressed in frame.columns
                   else pd.Series(
                       policy.lifetime_pd(stress_twelve / 100.0) * 100.0, index=index))

    base_applicable = pd.Series(
        np.where(base_stage <= 1, base_twelve, base_life), index=index)
    stressed_applicable = pd.Series(
        np.where(stressed_stage <= 1, stress_twelve, stress_life), index=index)
    #: What the PD factor would have been on the OPENING basis.
    same_basis = pd.Series(
        np.where(base_stage <= 1, stress_twelve, stress_life), index=index)

    pd_only = _ratio(same_basis, base_applicable)
    total_pd = _ratio(stressed_applicable, base_applicable)
    stage_only = _ratio(total_pd, pd_only)

    lgd_factor = _ratio(_series(frame.get(lgd_stressed, frame.get(lgd_baseline)), index),
                        _series(frame.get(lgd_baseline), index))
    ead_factor = _ratio(_series(frame.get(ead_stressed, frame.get(ead_baseline)), index),
                        _series(frame.get(ead_baseline), index))

    out = pd.DataFrame({
        "pd_factor": pd_only,
        "stage_factor": stage_only,
        "pd_factor_total": total_pd,
        "lgd_factor": lgd_factor,
        "ead_factor": ead_factor,
    }, index=index)
    out["ecl_factor"] = out["pd_factor_total"] * out["lgd_factor"] * out["ead_factor"]
    return out


def apply(frame: pd.DataFrame, *, reported: str = "final_ecl",
          **columns: str) -> pd.DataFrame:
    """The Delta Model applied: baseline, factors, and the What-If ECL.

    The baseline column is the REPORTED ECL, carried through untouched, so the
    base of every comparison ties to the accounts including any management
    overlay the bank booked. The stressed column is that number moved by the
    factor — never a fresh derivation from PD x LGD x EAD, which would quietly
    drop the overlay.
    """
    computed = factors(frame, **columns)
    baseline = _series(frame.get(reported), frame.index)
    out = frame.join(computed, how="left") if not computed.empty else frame.copy()
    out["ecl_baseline"] = baseline
    out["ecl_stressed"] = baseline * computed["ecl_factor"]
    out["ecl_increase"] = out["ecl_stressed"] - out["ecl_baseline"]
    out["ecl_increase_pct"] = (
        _ratio(out["ecl_stressed"], out["ecl_baseline"]) - 1.0) * 100.0
    return out


def aggregate(frame: pd.DataFrame) -> Factors:
    """The book-level factors, exposure-weighted the only way that reconciles.

    Each factor is the ratio of two totals rather than an average of ratios: a
    borrower with SAR 5m of provision does not carry the same weight in the
    book's PD factor as one with SAR 5bn. Built this way, the combined factor
    multiplied by total baseline ECL reproduces total What-If ECL exactly.
    """
    if frame.empty:
        return Factors(1.0, 1.0, 1.0, 1.0, 1.0)
    baseline = _series(frame.get("ecl_baseline"), frame.index)
    total = float(baseline.sum())
    if total <= NEAR_ZERO:
        return Factors(1.0, 1.0, 1.0, 1.0, 1.0)

    def weighted(column: str) -> float:
        values = _series(frame.get(column, 1.0), frame.index)
        return float((values * baseline).sum() / total)

    combined = float(_series(frame.get("ecl_stressed"), frame.index).sum() / total)
    return Factors(pd_factor=weighted("pd_factor"),
                   lgd_factor=weighted("lgd_factor"),
                   ead_factor=weighted("ead_factor"),
                   stage_factor=weighted("stage_factor"),
                   combined=combined)


def describe() -> dict[str, Any]:
    """The Delta Model as the configuration page explains it."""
    return {
        "key": DELTA_MODEL,
        "name": DELTA_NAME,
        "version": DELTA_VERSION,
        "owner": DELTA_OWNER,
        "purpose": (
            "A transparent, deterministic sensitivity. It takes the ECL the "
            "bank actually reported and moves it by the ratio the scenario "
            "implies, so every number on the screen can be reproduced with a "
            "calculator."),
        "anchor": (
            "The baseline column is the reported ECL, including any management "
            "overlay, carried through untouched. The model never re-derives "
            "the baseline from PD x LGD x EAD, because that would silently "
            "discard the overlay and produce a base that does not tie to the "
            "accounts."),
        "formula": ("What-If ECL = Official Baseline ECL x PD factor "
                    "x LGD factor x EAD factor"),
        "as_built": (
            "The engine measures both states on the governed basis "
            "(ECL = PD_applicable x LGD x EAD x "
            f"{policy.WEIGHTED_SCENARIO_FACTOR:.3f}) and forms their ratio. "
            "The scenario weighting cancels, so the ratio equals the product "
            "of the three factors above. They are reported separately rather "
            "than computed a second way."),
        "mechanics": {
            "PD": ("PD factor = stressed applicable PD / opening applicable "
                   "PD. Stage 1 is measured on the twelve-month PD and Stages "
                   "2 and 3 on the lifetime PD."),
            "Stage": ("A Stage 1 to Stage 2 migration changes the measurement "
                      "basis from twelve-month to lifetime PD. That part of "
                      "the movement is reported as the stage factor so it is "
                      "not mistaken for PD deterioration."),
            "LGD": "LGD factor = stressed LGD / opening LGD.",
            "CCF and EAD": (
                "EAD = drawn + CCF x undrawn. A CCF change is converted into "
                "an EAD change before any factor is formed; the CCF's own "
                "percentage movement is never used as the ECL movement."),
            "Collateral and haircut": (
                "A collateral or haircut change moves the covered share of the "
                "exposure, which moves LGD. It reaches ECL through the LGD "
                "factor rather than directly."),
            "Rating": (
                "A notch moves the borrower onto the masterscale PD of the "
                "grade it lands on, applied as the RATIO between the two "
                "grades' masterscale PDs so a borrower keeps its position "
                "inside the band."),
        },
        "caps": {
            "PD": "0% to 99%",
            "LGD": "0% to 95%",
            "EAD": "not below zero; an undrawn drawdown is capped at the "
                   "undrawn commitment",
            "Stage": "never improves under a scenario, and never reaches or "
                     "leaves Stage 3",
        },
        "worked_example": {
            "pd": "2.00% to 2.40% is a factor of 1.20",
            "lgd": "40% to 44% is a factor of 1.10",
            "ead": "a 5% rise is a factor of 1.05",
            "combined": "1.20 x 1.10 x 1.05 = 1.386, so ECL rises 38.6%",
            "warning": "The factors multiply. They are never added.",
        },
        "limitations": [
            "It is a sensitivity, not a re-measurement. There is no "
            "contractual cash-flow projection, no lifetime PD term structure "
            "and no effective-interest discounting.",
            "A borrower whose reported ECL is zero has no ratio to move, and "
            "is reported as unchanged rather than given a manufactured figure.",
            "It applies the shock the scenario states. It does not infer "
            "second-round effects between borrowers.",
        ],
        "near_zero_rule": (
            "Where a baseline measurement is below "
            f"{NEAR_ZERO:g} the ratio is not formed and the factor is 1.0. "
            "A borrower with no measurable baseline has no percentage to move."),
    }


__all__ = [
    "DELTA_MODEL", "DELTA_NAME", "DELTA_OWNER", "DELTA_VERSION", "Factors",
    "NEAR_ZERO", "aggregate", "applicable_pd", "apply", "describe",
    "ead_from_ccf", "factors",
]
