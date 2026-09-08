"""
Which driver moved the provision, and by how much.

Why this module exists
----------------------
A What-If answers "the ECL rises by SAR 5.7bn". The next question is always
"because of what?", and a scenario that shocked four things at once cannot
answer it by naming the last thing it did. Order matters to arithmetic: apply
the rating move first and the PD shock is measured on a higher base, apply it
last and it is measured on a lower one. Any attribution that depends on the
order in which the engine happened to run is a presentational artefact.

The repository already owns the answer to that problem —
`backend.orchestration.decomposition` computes an EXACT Shapley value, the
unique attribution that is order-neutral, sums to the total, and gives a driver
that never moved an effect of zero. This module hands it the What-If's own
game rather than building a second, weaker attribution beside it.

The game
--------
`engine.run` records each driver's BEFORE and AFTER on the three risk
parameters as it applies the shocks. Those ratios telescope: multiply every
driver's factor together and you get the whole measurement movement, exactly,
with nothing left over. So the coalitional game is

    V(S) = the book's ECL when exactly the drivers in S have moved
         = sum over borrowers of  reported ECL x product of factors in S

with V({}) the reported book and V(everything) the What-If. Shapley over that
game splits the total movement across drivers, exactly.

Two things are deliberately kept out of it:

  * The PD factor is measured on the APPLICABLE PD — twelve-month for a Stage 1
    borrower, lifetime for a Stage 2 one — so that the drivers telescope
    through the lifetime transform rather than leaving a nonlinear residual
    that would have to be swept somewhere.
  * The change of measurement BASIS is its own driver. "Your provision tripled"
    reads very differently from "your provision tripled because the borrower
    moved to lifetime measurement", and the two are separate facts.

And what this is not
--------------------
This is not SHAP. SHAP explains one XGBoost PREDICTION in terms of the
borrower's features; this explains the SCENARIO's ECL movement in terms of the
things the scenario changed. They answer different questions about different
objects and are never mixed. Where the ML methodology is chosen, the
difference between the model's answer and the governed measurement is reported
as its own labelled line rather than smuggled into a driver.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from backend.ifrs9 import policy
from backend.orchestration import decomposition as dc

ATTRIBUTION_VERSION = "1.1.0"
ATTRIBUTION_METHOD = "Exact Shapley (order-neutral, sums to the total)"

#: Below this share of the movement, the difference between the engine's own
#: measurement and the priced figure is arithmetic, not a finding.
#:
#: The two are summed over thousands of rows from figures the lake stores to
#: two decimal places, so they agree to about six significant figures and no
#: further. Reporting that last part as a line on the bridge put "ML model
#: adjustment: 0.009" on a Delta run — an ML attribution on a result no model
#: touched. A residual is disclosed when it is large enough to change a
#: reading, and always shown in the reconciliation whatever its size.
RESIDUAL_MATERIALITY = 1e-4

#: Below this a factor is treated as "did not move". A driver that did not move
#: gets an effect of exactly zero from Shapley anyway; dropping it first keeps
#: the number of coalitions down and keeps the table honest.
MOVED = 1e-9

#: Reader-facing names, in the order a credit officer would read them.
#:
#: `basis` and `stage` are deliberately two different drivers. A Stage 1 name
#: moving to Stage 2 is measured on its LIFETIME PD instead of its twelve-month
#: one, and that change of measurement basis is usually the whole of the
#: movement. Collapsing it into an opaque "Stage effect" is what produced a
#: result reading "PD EFFECT 0.00%, STAGE EFFECT +243.97%", which is
#: arithmetically true and analytically useless: the reader cannot see that the
#: applicable PD went from 1.2% to 4.9% because the basis changed, not because
#: any PD moved.
LABELS: dict[str, str] = {
    "rating": "Rating migration",
    "macro": "Macroeconomic shock",
    "financial": "Financial deterioration",
    "pd": "Probability of default (same measurement basis)",
    "lgd": "Loss given default",
    "collateral": "Collateral and security",
    "ccf": "Credit conversion factor",
    "ead": "Exposure at default",
    "basis": "Measurement basis: 12-month PD to lifetime PD",
    "stage": "Stage migration, residual mechanics",
    "limits": "Clamped to policy limits",
}
ORDER: tuple[str, ...] = (
    "rating", "macro", "financial", "pd", "basis", "stage", "lgd",
    "collateral", "ccf", "ead", "limits",
)

#: More than this many moving drivers and the exact game stops being cheap:
#: it is 2^n coalitions. Ten is every driver this engine has, so the cap is a
#: guard rather than a limit anybody meets.
MAX_DRIVERS = 12


class AttributionError(ValueError):
    """An attribution that cannot be computed, said rather than approximated."""


def _applicable(pd_pct: np.ndarray, stage: np.ndarray,
                ttc_pct: np.ndarray | None = None) -> np.ndarray:
    """The PD the measurement actually uses, per borrower.

    Twelve-month below Stage 2, lifetime at or above it. Taking the ratio on
    THIS scale is what makes the drivers telescope: the lifetime transform is
    applied to each driver's before and after, so the products cancel instead
    of leaving a nonlinear remainder.

    The anchor matters. The lifetime PD reverts towards the grade's
    through-the-cycle level, so a driver that moves the grade moves the anchor
    with it, and each driver's before and after must be read against the
    anchor in force on that side of it. Without that the chain does not
    telescope and the attribution stops adding up to the movement it claims to
    explain.
    """
    anchor = np.asarray(pd_pct) if ttc_pct is None else np.asarray(ttc_pct)
    lifetime = np.asarray(policy.lifetime_pd(
        np.asarray(pd_pct) / 100.0, anchor / 100.0)) * 100.0
    return np.where(np.asarray(stage) <= 1, np.asarray(pd_pct), lifetime)


def _ratio(after: np.ndarray, before: np.ndarray) -> np.ndarray:
    """after / before, with a zero denominator meaning "did not move"."""
    before = np.asarray(before, dtype=float)
    after = np.asarray(after, dtype=float)
    out = np.ones_like(before)
    live = np.abs(before) > 1e-12
    out[live] = after[live] / before[live]
    return np.nan_to_num(out, nan=1.0, posinf=1.0, neginf=1.0)


def driver_factors(frame: pd.DataFrame,
                   tracked: dict[str, dict[str, Any]]) -> dict[str, np.ndarray]:
    """One multiplicative factor per driver, per borrower.

    The product across drivers is the borrower's whole measurement movement.
    """
    stage_baseline = pd.to_numeric(frame["stage_baseline"],
                                   errors="coerce").fillna(1).to_numpy()
    factors: dict[str, np.ndarray] = {}
    for driver, entry in tracked.items():
        if not entry:
            continue
        # Every driver's PD move is read on the basis the borrower OPENED on,
        # so that the basis change itself stays with the stage driver — and
        # against the through-the-cycle anchor in force on each side, so a
        # rating driver that moved the grade is read against both grades.
        pd_before = _applicable(entry["pd_before"], stage_baseline,
                                entry.get("ttc_before"))
        pd_after = _applicable(entry["pd_after"], stage_baseline,
                               entry.get("ttc_after"))
        factor = (_ratio(pd_after, pd_before)
                  * _ratio(entry["lgd_after"], entry["lgd_before"])
                  * _ratio(entry["ead_after"], entry["ead_before"]))
        factors[driver] = factor

    # The change of MEASUREMENT BASIS. When a borrower crosses from Stage 1 to
    # Stage 2 the same PD is read off a different curve — twelve-month becomes
    # lifetime — and on this book that is worth roughly four times. It is its
    # own driver because it is its own fact: nothing about the borrower's
    # riskiness changed, only what the standard says to measure.
    stage_stressed = pd.to_numeric(frame["stage_stressed"],
                                   errors="coerce").fillna(1).to_numpy()
    final_pd = pd.to_numeric(frame["pd_stressed"], errors="coerce").fillna(0.0).to_numpy()
    final_ttc = (pd.to_numeric(frame["ttc_stressed"], errors="coerce")
                 .fillna(0.0).to_numpy() if "ttc_stressed" in frame.columns
                 else None)
    on_opening_basis = _applicable(final_pd, stage_baseline, final_ttc)
    on_closing_basis = _applicable(final_pd, stage_stressed, final_ttc)
    factors["basis"] = _ratio(on_closing_basis, on_opening_basis)

    # Whatever a Stage instruction did that the change of basis does not
    # already explain. On a plain Stage 1 to Stage 2 migration this is exactly
    # one and gets an effect of zero, which is the honest answer: the
    # migration's cost IS the basis change.
    factors["stage"] = factors.get("stage", np.ones(len(frame)))
    return factors


def basis_movement(frame: pd.DataFrame) -> dict[str, Any]:
    """What the change of measurement basis did, in the terms a lender uses.

    Answers "how much of this is because lifetime PD replaced twelve-month
    PD?" with the borrowers, the exposure and the two PDs, rather than only
    with a percentage.
    """
    stage_before = pd.to_numeric(frame.get("stage_baseline"),
                                 errors="coerce").fillna(1).to_numpy()
    stage_after = pd.to_numeric(frame.get("stage_stressed"),
                                errors="coerce").fillna(1).to_numpy()
    crossed = (stage_before <= 1) & (stage_after >= 2)
    if not crossed.any():
        return {"moved": 0,
                "note": "No borrower changed measurement basis in this "
                        "scenario, so the applicable PD is read off the same "
                        "curve before and after."}
    twelve = pd.to_numeric(frame.get("pd_stressed"),
                           errors="coerce").fillna(0.0).to_numpy()[crossed]
    lifetime = _applicable(
        pd.to_numeric(frame.get("pd_stressed"),
                      errors="coerce").fillna(0.0).to_numpy(),
        np.full(len(frame), 2))[crossed]
    exposure = pd.to_numeric(frame.get("ead"),
                             errors="coerce").fillna(0.0).to_numpy()[crossed]
    weight = exposure if exposure.sum() > 0 else np.ones(len(exposure))
    before = float(np.average(twelve, weights=weight))
    after = float(np.average(lifetime, weights=weight))
    return {
        "moved": int(crossed.sum()),
        "exposure": float(exposure.sum()),
        "average_12m_pd_before": round(before, 4),
        "average_lifetime_pd_after": round(after, 4),
        "applicable_pd_ratio": round(after / before, 4) if before else None,
        "note": (
            f"{int(crossed.sum()):,} borrower(s) carrying "
            f"{exposure.sum():,.0f} of exposure moved from Stage 1 to "
            f"Stage 2. Their expected credit loss is now measured on the "
            f"LIFETIME probability of default rather than the twelve-month "
            f"one: on exposure-weighted average {before:.2f}% becomes "
            f"{after:.2f}%, a factor of "
            f"{(after / before) if before else float('nan'):.2f}. Nothing "
            "about the borrowers' riskiness changed — the standard changed "
            "what is measured."),
    }


def attribute(frame: pd.DataFrame, tracked: dict[str, dict[str, Any]], *,
              baseline: str = "ecl_baseline",
              stressed: str = "ecl_stressed",
              currency: str = "SAR",
              methodology: str = "") -> dict[str, Any]:
    """Split the ECL movement across the drivers that caused it.

    The result reconciles by construction: the effects sum to the movement,
    and the reconciliation is reported rather than asserted, so a reader can
    see that it does.
    """
    if frame.empty:
        return {"available": False,
                "why": "There are no borrowers to attribute."}
    reported = pd.to_numeric(frame[baseline], errors="coerce").fillna(0.0).to_numpy()
    actual = pd.to_numeric(frame[stressed], errors="coerce").fillna(0.0).to_numpy()

    factors = driver_factors(frame, tracked)
    moving = [name for name in ORDER
              if name in factors and np.abs(factors[name] - 1.0).max() > MOVED]
    still = [name for name in factors if name not in moving]

    if not moving:
        return {"available": True, "version": ATTRIBUTION_VERSION,
                "method": ATTRIBUTION_METHOD, "currency": currency,
                "drivers": [], "total": 0.0,
                "note": "Nothing in this scenario moved the provision."}
    if len(moving) > MAX_DRIVERS:
        raise AttributionError(
            f"{len(moving)} drivers is more than the exact attribution will "
            f"compute ({MAX_DRIVERS}). An exact Shapley over more than that is "
            "2^n coalitions, and an approximation here would be worse than "
            "saying so.")

    # V(S): the book's ECL with exactly the drivers in S moved. Vectorised over
    # borrowers, so each coalition costs one pass over the book rather than one
    # pass per borrower.
    value: dict[frozenset[int], float] = {}
    for subset in dc.subsets(len(moving)):
        product = np.ones(len(frame))
        for index in subset:
            product = product * factors[moving[index]]
        value[subset] = float((reported * product).sum())

    effects = dc.shapley_of(value, len(moving))

    opening = value[frozenset()]
    closing = value[frozenset(range(len(moving)))]
    measured_total = closing - opening
    drivers = [{
        "key": name,
        "label": LABELS.get(name, name),
        "effect": float(effect),
        "share_pct": float(effect / measured_total * 100.0) if measured_total else 0.0,
        "mean_factor": float(np.average(factors[name], weights=np.maximum(reported, 0.0))
                             if reported.sum() > 0 else np.mean(factors[name])),
        "borrowers_moved": int((np.abs(factors[name] - 1.0) > MOVED).sum()),
    } for name, effect in zip(moving, effects, strict=True)]

    body: dict[str, Any] = {
        "available": True,
        "version": ATTRIBUTION_VERSION,
        "method": ATTRIBUTION_METHOD,
        "currency": currency,
        "drivers": drivers,
        "baseline_ecl": float(reported.sum()),
        "measured_whatif_ecl": closing,
        "measured_total": measured_total,
        "attributed_total": float(sum(effects)),
        "unmoved": [LABELS.get(name, name) for name in still],
        # The measurement-basis change, spelled out in the terms a lender
        # asks about: how many names, how much exposure, and what the
        # applicable PD became.
        "measurement_basis": basis_movement(frame),
        "note": ("Every driver's effect is its average marginal contribution "
                 "across every order in which the drivers could have moved. "
                 "That is the only attribution that is order-neutral, sums to "
                 "the total, and gives a driver that did not move an effect of "
                 "exactly zero."),
    }

    # Where the ML methodology priced the scenario, its answer differs from the
    # governed measurement. That difference is not a scenario driver and is
    # never folded into one.
    actual_total = float(actual.sum() - reported.sum())
    model_gap = actual_total - measured_total
    body["whatif_ecl"] = float(actual.sum())
    body["total"] = actual_total
    # A relative tolerance, not an absolute one: on a Delta run the two are the
    # same calculation and the gap is floating-point noise on a nine-figure
    # number. Anything above this is a real difference between the two
    # methodologies and has to be shown.
    if abs(model_gap) > max(abs(actual_total), 1.0) * 1e-12:
        # WHY the two differ decides what this line is called. A cap that
        # bounded a provision at the exposure it provides against is not a
        # model disagreement, and labelling it one would credit a methodology
        # with an effect a policy limit had.
        bounded = bool((pd.to_numeric(frame.get("ecl_stressed"),
                                      errors="coerce").fillna(0.0)
                        >= pd.to_numeric(frame.get("ead_stressed",
                                                   frame.get("ead")),
                                         errors="coerce").fillna(0.0) - 1e-6
                        ).any()) if "ecl_stressed" in frame.columns else False
        capped = bounded and model_gap < 0
        # A model can only be credited with a difference on a run that used
        # one. Naming the line after the methodology that actually priced the
        # book is what stops a Delta result carrying an ML label.
        modelled = str(methodology or "").lower() == "ml"
        if capped:
            key, label = "limits", "Bounded by exposure at default"
            note = (
                "The drivers above attribute the GOVERNED measurement "
                "movement. Some borrowers reached an expected credit loss "
                "above their own exposure and were capped at it; the part the "
                "cap removed is shown here rather than taken off a driver "
                "that did not cause it.")
        elif modelled:
            key, label = "model", "ML model adjustment"
            note = (
                "The drivers above attribute the GOVERNED measurement "
                "movement. The ML methodology priced the same shocked book "
                "differently, and the difference is shown here rather than "
                "attributed to a driver that did not cause it.")
        else:
            key, label = "residual", "Pricing residual"
            note = (
                "The drivers above attribute the GOVERNED measurement "
                "movement. Carrying it onto the reported book left this much "
                "unexplained. It is disclosed rather than spread across the "
                "drivers, which would credit them with an effect they did not "
                "have.")
        body["model_adjustment"] = {
            "key": key, "label": label, "effect": float(model_gap),
            "note": note,
            # The bridge always reconciles through this figure, so it is
            # always here for a caller adding the drivers back up. Whether it
            # is worth a LINE is a separate question, and the answer is no
            # when it is the last digit of a nine-figure sum.
            "material": bool(abs(model_gap) > max(abs(actual_total), 1.0)
                             * RESIDUAL_MATERIALITY),
        }

    body["reconciliation"] = {
        "attributed": float(sum(effects)),
        "measured_movement": measured_total,
        "model_adjustment": float(model_gap),
        "reported_movement": actual_total,
        "difference": float(sum(effects) + model_gap - actual_total),
        "reconciles": bool(
            abs(sum(effects) + model_gap - actual_total)
            <= max(abs(actual_total), 1.0) * 1e-6),
        "materiality": RESIDUAL_MATERIALITY,
        "note": ("The reconciliation always carries the residual, and so does "
                 "the adjustment line, so the bridge always adds up. The line "
                 "is only SHOWN when it exceeds "
                 f"{RESIDUAL_MATERIALITY:.4%} of the movement, below which it "
                 "is the arithmetic of summing thousands of two-decimal "
                 "figures rather than a difference in method."),
    }
    return body


def describe() -> dict[str, Any]:
    """What the attribution is, for the configuration screen."""
    return {
        "version": ATTRIBUTION_VERSION,
        "method": ATTRIBUTION_METHOD,
        "owner": "Credit Risk Analytics",
        "drivers": [{"key": key, "label": LABELS[key]} for key in ORDER],
        "statement": (
            "The ECL movement is split across the drivers of the scenario by "
            "an exact Shapley value, computed by the same governed function "
            "the ECL attribution bridge uses. It is order-neutral: the answer "
            "does not depend on the sequence the engine applied the shocks in."),
        "not_shap": (
            "This is not SHAP. SHAP explains one ML prediction from a "
            "borrower's features; this explains the scenario's ECL movement "
            "from the things the scenario changed. Both exist and neither "
            "stands in for the other."),
    }


__all__ = [
    "ATTRIBUTION_METHOD", "ATTRIBUTION_VERSION", "LABELS", "MAX_DRIVERS",
    "ORDER", "AttributionError", "attribute", "describe", "driver_factors",
]
