"""
The retail IFRS 9 demonstration engine.

A transparent monthly-hazard formulation, written so that every number it
produces can be re-derived from the inputs stored beside it. It is a
DEMONSTRATION engine: it is not ANB's approved accounting model, it has not
been independently validated, and nothing it prints is an audit conclusion.

The quantities kept deliberately separate, because conflating them is the
commonest way an ECL number stops meaning anything:

* `pd_ttc_12m` — a through-the-cycle 12-month reference probability.
* `pd_pit_12m_<scenario>` — point-in-time, conditioned on one scenario.
* `pd_pit_lifetime_<scenario>` — cumulative over the applicable remaining life.
* the application and behavioural models' PDs, which answer their own targets
  and reach IFRS 9 only through an explicit, versioned mapping.

Horizon rules, stated once:

* **Stage 1** counts DEFAULT EVENTS in the next 12 months (or the shorter
  remaining life). It does *not* truncate the loss from those defaults: LGD
  already embeds recoveries discounted back to the default date, so a default in
  month 11 whose recovery arrives in month 35 is fully costed.
* **Stage 2** counts default events over the applicable remaining expected life.
* **Stage 3** is not a hazard calculation at all. The facility has defaulted;
  the loss is the shortfall between the gross carrying amount and the present
  value of what is expected to be recovered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Lifetime curves are evaluated to this many months. A 300-month home finance
#: contract is not truncated silently: the cap is recorded on every row as
#: `ecl_horizon_months`, and the discounted tail beyond it is immaterial at the
#: profit rates used here (measured in tests/retail/test_ecl_engine.py).
LIFETIME_HORIZON_CAP_MONTHS = 120

ECL_MODEL_VERSION = "retail-ecl-1.0.0"
PD_MODEL_VERSION = "retail-pd-1.0.0"
LGD_MODEL_VERSION = "retail-lgd-1.0.0"
EAD_MODEL_VERSION = "retail-ead-1.0.0"

SCENARIOS: tuple[str, ...] = ("base", "upturn", "downturn")


# --------------------------------------------------------------------------
# PD curves
# --------------------------------------------------------------------------

def constant_hazard_from_pd12(pd12: np.ndarray | float) -> np.ndarray:
    """The monthly hazard whose twelve marginal probabilities sum to `pd12`.

    `h = 1 - (1 - pd12) ** (1/12)`, so `sum(marginal_pd(1..12)) == pd12`
    exactly. That identity is what the golden fixture leans on.
    """
    p = np.clip(np.asarray(pd12, dtype="float64"), 0.0, 1.0 - 1e-12)
    return 1.0 - np.power(1.0 - p, 1.0 / 12.0)


def survival_and_marginal(hazard: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`S(t)` and `marginal_pd(t)` from a monthly hazard path.

    `hazard` is shaped (n_rows, n_months). Returns survival BEFORE each month
    (i.e. `S(t-1)`) and the marginal default probability in each month, so that
    `marginal[:, t] == S_before[:, t] * hazard[:, t]` and survival is never
    double-counted.
    """
    h = np.clip(np.asarray(hazard, dtype="float64"), 0.0, 1.0)
    surv_before = np.cumprod(np.concatenate(
        [np.ones((h.shape[0], 1)), 1.0 - h[:, :-1]], axis=1), axis=1)
    marginal = surv_before * h
    return surv_before, marginal


def cumulative_pd(marginal: np.ndarray, horizon: np.ndarray | int | None = None) -> np.ndarray:
    """Cumulative default probability to a per-row horizon (months, 1-based)."""
    if horizon is None:
        return marginal.sum(axis=1)
    n_months = marginal.shape[1]
    t_index = np.arange(1, n_months + 1)[None, :]
    h = np.asarray(horizon).reshape(-1, 1)
    return np.where(t_index <= h, marginal, 0.0).sum(axis=1)


def seasoned_hazard_path(
    pd12: np.ndarray,
    months_on_book: np.ndarray,
    n_months: int,
    *,
    seasoning_peak_month: float = 14.0,
    seasoning_strength: float = 0.45,
) -> np.ndarray:
    """A hazard path with a documented seasoning shape.

    Retail default hazard is not flat over a contract's life: it rises through
    the first year or so on book and then declines. The shape below is a
    SYNTHETIC demonstration curve, normalised so that the first twelve months
    still sum to `pd12` for a freshly originated facility — the calibration
    anchor stays where the tests can see it.
    """
    base_h = constant_hazard_from_pd12(pd12)[:, None]
    age = months_on_book.reshape(-1, 1) + np.arange(1, n_months + 1)[None, :]
    shape = 1.0 + seasoning_strength * np.exp(
        -0.5 * ((age - seasoning_peak_month) / 9.0) ** 2
    ) - seasoning_strength * 0.35
    return np.clip(base_h * shape, 0.0, 1.0)


# --------------------------------------------------------------------------
# LGD from recovery inputs — one definition, used by every stage
# --------------------------------------------------------------------------

def lgd_from_recovery(
    recovery_rate_nominal: np.ndarray,
    delay_months: np.ndarray,
    monthly_rate: np.ndarray,
    *,
    floor: float = 0.03,
    cap: float = 0.95,
) -> np.ndarray:
    """LGD as the loss remaining once expected recoveries are discounted.

    Discounting here runs from the month the recovery is expected back to the
    DEFAULT date. ECL then discounts from the default month back to the
    reporting date. Each cash flow is therefore discounted across each interval
    exactly once.
    """
    rr = np.clip(np.asarray(recovery_rate_nominal, dtype="float64"), 0.0, 1.0)
    d = np.maximum(np.asarray(delay_months, dtype="float64"), 0.0)
    disc = np.power(1.0 + np.asarray(monthly_rate, dtype="float64"), -d)
    return np.clip(1.0 - rr * disc, floor, cap)


# --------------------------------------------------------------------------
# ECL
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EclInputs:
    """One scenario's inputs for a batch of facilities.

    Arrays are per-row unless named `_path`, which are (n_rows, n_months).
    """

    stage: np.ndarray                 # 1 | 2 | 3
    ead_path: np.ndarray              # exposure at default if default occurs in month t
    hazard_path: np.ndarray
    lgd: np.ndarray
    monthly_discount_rate: np.ndarray
    remaining_life_months: np.ndarray  # applicable expected life, >= 1
    gross_carrying_amount: np.ndarray  # used by Stage 3
    stage3_recovery_rate_nominal: np.ndarray
    stage3_delay_months: np.ndarray

    def n_months(self) -> int:
        return self.hazard_path.shape[1]


@dataclass
class EclResult:
    ecl: np.ndarray
    horizon_months: np.ndarray
    horizon_type: np.ndarray
    pd_12m: np.ndarray
    pd_lifetime: np.ndarray
    lgd: np.ndarray
    ead: np.ndarray
    extras: dict[str, Any] = field(default_factory=dict)


def compute_ecl(inp: EclInputs) -> EclResult:
    """Scenario ECL for a batch, stage by stage.

    Stage 1 and 2 share one formula and differ only in the horizon over which
    default events are counted:

        ECL = sum_t  marginal_pd(t) * EAD(t) * LGD * discount(t)

    Stage 3 uses the cash-shortfall form instead, because a facility that has
    already defaulted does not have a probability of defaulting.
    """
    n_rows, n_months = inp.hazard_path.shape
    t_index = np.arange(1, n_months + 1)[None, :]

    _, marginal = survival_and_marginal(inp.hazard_path)
    disc = np.power(1.0 + inp.monthly_discount_rate.reshape(-1, 1), -t_index.astype("float64"))

    life = np.clip(inp.remaining_life_months, 1, n_months).astype("int64")
    stage1_horizon = np.minimum(life, 12)
    horizon = np.where(inp.stage == 1, stage1_horizon, life)
    within = t_index <= horizon.reshape(-1, 1)

    loss_path = marginal * inp.ead_path * inp.lgd.reshape(-1, 1) * disc
    ecl_hazard = np.where(within, loss_path, 0.0).sum(axis=1)

    # Stage 3: gross carrying amount less the present value of expected recoveries.
    disc_delay = np.power(
        1.0 + inp.monthly_discount_rate,
        -np.maximum(inp.stage3_delay_months.astype("float64"), 0.0),
    )
    pv_recovery = (
        inp.gross_carrying_amount
        * np.clip(inp.stage3_recovery_rate_nominal, 0.0, 1.0)
        * disc_delay
    )
    ecl_stage3 = np.maximum(inp.gross_carrying_amount - pv_recovery, 0.0)

    is_s3 = inp.stage == 3
    ecl = np.where(is_s3, ecl_stage3, ecl_hazard)

    pd_12m = cumulative_pd(marginal, np.minimum(life, 12))
    pd_life = cumulative_pd(marginal, life)

    horizon_type = np.where(
        is_s3, "STAGE3_RECOVERY",
        np.where(inp.stage == 1, "TWELVE_MONTH_OR_SHORTER_LIFE", "REMAINING_LIFETIME"),
    )
    eff_horizon = np.where(is_s3, inp.stage3_delay_months, horizon)

    # A defaulted facility's PD is one by reporting convention. That convention
    # does not do the loss modelling; the Stage 3 branch above does.
    pd_12m = np.where(is_s3, 1.0, pd_12m)
    pd_life = np.where(is_s3, 1.0, pd_life)
    lgd_out = np.where(
        is_s3,
        np.where(inp.gross_carrying_amount > 0,
                 ecl_stage3 / np.where(inp.gross_carrying_amount > 0, inp.gross_carrying_amount, 1.0),
                 inp.lgd),
        inp.lgd,
    )
    ead_out = np.where(is_s3, inp.gross_carrying_amount, inp.ead_path[:, 0])

    return EclResult(
        ecl=ecl, horizon_months=eff_horizon, horizon_type=horizon_type,
        pd_12m=pd_12m, pd_lifetime=pd_life, lgd=lgd_out, ead=ead_out,
        extras={"marginal_sum_all_months": marginal.sum(axis=1)},
    )


def weighted_ecl(
    scenario_ecl: dict[str, np.ndarray],
    weights: dict[str, float],
    *,
    tolerance: float = 1e-9,
) -> np.ndarray:
    """Probability-weight the complete scenario ECLs.

    Deliberately not "average the PDs, average the LGDs, then multiply": that
    throws away exactly the non-linearity multiple scenarios exist to capture.
    """
    missing = [s for s in SCENARIOS if s not in scenario_ecl]
    if missing:
        raise ValueError(f"no ECL supplied for scenario(s): {missing}")
    total = sum(weights[s] for s in SCENARIOS)
    if abs(total - 1.0) > tolerance:
        raise ValueError(
            f"scenario weights sum to {total!r}, not 1.0 within {tolerance}. "
            "Weights are validated, not silently normalised."
        )
    out = np.zeros_like(np.asarray(scenario_ecl["base"], dtype="float64"))
    for s in SCENARIOS:
        out = out + float(weights[s]) * np.asarray(scenario_ecl[s], dtype="float64")
    return out


def final_ecl(weighted: np.ndarray, overlay: np.ndarray | float) -> np.ndarray:
    """`ecl_final = ecl_weighted + management_overlay`. Overlay stays visible."""
    return np.asarray(weighted, dtype="float64") + np.asarray(overlay, dtype="float64")


def coverage_ratio(ecl: np.ndarray, gross_carrying_amount: np.ndarray) -> np.ndarray:
    """ECL over GCA, with a defined unavailable state instead of infinity."""
    gca = np.asarray(gross_carrying_amount, dtype="float64")
    return np.where(gca > 0, np.asarray(ecl, dtype="float64") / np.where(gca > 0, gca, 1.0), np.nan)


def monthly_rate(annual_rate: np.ndarray | float) -> np.ndarray:
    """Effective monthly rate from an effective annual rate."""
    return np.power(1.0 + np.asarray(annual_rate, dtype="float64"), 1.0 / 12.0) - 1.0
