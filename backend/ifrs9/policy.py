"""
The governed IFRS 9 policy: what makes a Stage, and how ECL is measured.

Why this module exists
----------------------
These rules were written once, inside the universe generator, and read by
nothing else. That was survivable while the only thing that staged a borrower
was the thing that created it. It stopped being survivable the moment What-If
had to answer "which Stage 1 borrowers become Stage 2 if their ratings fall two
notches?" — because answering that means RE-EVALUATING the staging rules
against a hypothetical PD, and a second copy of the rules is a second answer
waiting to disagree with the first.

So the policy lives here, the generator imports it, and What-If imports it. A
test asserts the recomputed ECL reproduces the reported ECL on the live book,
which is the only check that actually proves there is one rule rather than two.

What is policy and what is data
-------------------------------
Policy: the SICR triggers, the default presumption, the scenario weights, the
lifetime horizon, and the measurement basis for each Stage.

Data: every borrower's PD, LGD, EAD, origination PD, days past due and reported
ECL. None of that is invented here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

POLICY_OWNER = "Credit Risk Analytics"
POLICY_VERSION = "1.0.0"

# ------------------------------------------------------------------- SICR
#
# The four governed triggers. A borrower trips Stage 2 if ANY of them fires.

#: Relative PD increase that counts as a significant increase in credit risk.
SICR_PD_RATIO = 2.0
#: And the absolute increase it must also clear, so a move from 0.03% to 0.07%
#: does not trip a trigger on its own. Two hundred basis points is a movement a
#: credit officer would want to look at, and leaves a Stage 2 population
#: somebody could actually work through.
SICR_PD_ABSOLUTE = 2.00
#: A twelve-month PD this high is a significant increase on its own, whatever
#: the borrower was graded at origination. Roughly the CCC band.
SICR_ABSOLUTE_PD = 13.0
#: Days past due at which a facility is presumed to have suffered a SICR.
SICR_DPD_DAYS = 30
#: Days past due at which default is presumed.
DEFAULT_DPD_DAYS = 90

#: Scenario probability weights, and the ECL multiplier each scenario carries.
#: The reported ECL is the probability-weighted one, so every measurement here
#: carries the same factor and the base reproduces the book.
SCENARIO_WEIGHTS: tuple[tuple[str, float, float], ...] = (
    ("Base", 0.50, 1.00),
    ("Upside", 0.20, 0.72),
    ("Downside", 0.30, 1.46),
)

#: The probability-weighted multiplier applied to every measured ECL.
WEIGHTED_SCENARIO_FACTOR = sum(w * m for _, w, m in SCENARIO_WEIGHTS)

#: Lifetime horizon, in years, used to extend a twelve-month PD. Behavioural
#: rather than contractual: the average corporate facility here reprices or
#: matures inside five years, and 4.2 is the exposure-weighted mean life.
LIFETIME_HORIZON_YEARS = 4.2


def lifetime_pd(pd_12m: np.ndarray | pd.Series) -> np.ndarray:
    """Lifetime PD from a twelve-month PD, both as decimals.

    A constant-hazard extension over the behavioural life, floored at the
    twelve-month rate (a lifetime probability can never be lower) and capped
    below one.
    """
    twelve = np.asarray(pd_12m, dtype=float)
    return np.clip(1.0 - (1.0 - twelve) ** LIFETIME_HORIZON_YEARS, twelve, 0.999)


@dataclass(frozen=True)
class Triggers:
    """Which SICR triggers fired, per borrower."""

    relative_pd: np.ndarray
    absolute_pd: np.ndarray
    days_past_due: np.ndarray
    any_fired: np.ndarray

    def named(self, index: int) -> tuple[str, ...]:
        """The triggers that fired for one row, as reader-facing names."""
        out = []
        if bool(self.relative_pd[index]):
            out.append("PD more than doubled since origination")
        if bool(self.absolute_pd[index]):
            out.append(f"12-month PD above {SICR_ABSOLUTE_PD:.0f}%")
        if bool(self.days_past_due[index]):
            out.append(f"{SICR_DPD_DAYS}+ days past due")
        return tuple(out)


def sicr(pd_12m_pct: pd.Series, origination_pd_pct: pd.Series,
         days_past_due: pd.Series) -> Triggers:
    """Evaluate the governed SICR triggers against a PD, hypothetical or not.

    This is the function What-If calls with a STRESSED PD. Nothing about it
    knows or cares whether the PD it is given was reported or modelled, which
    is exactly why a scenario answer can be defended: the same rule decided
    both sides of the comparison.
    """
    current = pd.to_numeric(pd_12m_pct, errors="coerce").fillna(0.0)
    origination = pd.to_numeric(origination_pd_pct, errors="coerce")
    dpd = pd.to_numeric(days_past_due, errors="coerce").fillna(0.0)

    ratio = current / origination.replace(0, np.nan)
    absolute = current - origination
    relative = ((ratio >= SICR_PD_RATIO)
                & (absolute >= SICR_PD_ABSOLUTE)).fillna(False).to_numpy()
    outright = (current >= SICR_ABSOLUTE_PD).to_numpy()
    late = (dpd >= SICR_DPD_DAYS).to_numpy()
    return Triggers(relative_pd=relative, absolute_pd=outright,
                    days_past_due=late,
                    any_fired=relative | outright | late)


def stage_of(pd_12m_pct: pd.Series, origination_pd_pct: pd.Series,
             days_past_due: pd.Series, default_flag: pd.Series) -> np.ndarray:
    """The governed Stage for a PD, hypothetical or not.

    Stage 3 is a fact about the borrower rather than about its PD: a scenario
    does not cure a default, and does not create one either. A borrower already
    in Stage 3 stays there under every scenario.
    """
    defaulted = (pd.to_numeric(default_flag, errors="coerce").fillna(0) > 0)
    late = pd.to_numeric(days_past_due, errors="coerce").fillna(0) >= DEFAULT_DPD_DAYS
    triggers = sicr(pd_12m_pct, origination_pd_pct, days_past_due)
    return np.where(defaulted | late, 3, np.where(triggers.any_fired, 2, 1))


def measured_ecl(stage: np.ndarray | pd.Series, pd_12m_pct: pd.Series,
                 lgd_pct: pd.Series, ead: pd.Series,
                 *, lifetime_pd_pct: pd.Series | None = None) -> np.ndarray:
    """ECL on the governed measurement basis, before any overlay.

    Stage 1 is measured on the twelve-month PD; Stages 2 and 3 on the lifetime
    PD. That single line is why a Stage 1 to Stage 2 migration increases the
    provision even when nothing else about the borrower moved, and it is the
    mechanism a scenario answer has to get right to be worth anything.
    """
    twelve = pd.to_numeric(pd_12m_pct, errors="coerce").fillna(0.0) / 100.0
    if lifetime_pd_pct is None:
        life = lifetime_pd(twelve)
    else:
        life = pd.to_numeric(lifetime_pd_pct, errors="coerce").fillna(0.0) / 100.0
    loss = pd.to_numeric(lgd_pct, errors="coerce").fillna(0.0) / 100.0
    exposure = pd.to_numeric(ead, errors="coerce").fillna(0.0)
    staged = np.asarray(stage, dtype=float)
    applied = np.where(staged <= 1, twelve, life)
    return applied * loss * exposure * WEIGHTED_SCENARIO_FACTOR


def describe() -> dict[str, object]:
    """The policy as a reader can check it."""
    return {
        "owner": POLICY_OWNER,
        "version": POLICY_VERSION,
        "sicr_triggers": [
            {"trigger": "Relative PD increase",
             "rule": f"12-month PD at least {SICR_PD_RATIO:g}x its level at "
                     f"origination AND at least {SICR_PD_ABSOLUTE:.2f} "
                     "percentage points higher"},
            {"trigger": "Absolute PD level",
             "rule": f"12-month PD at or above {SICR_ABSOLUTE_PD:.0f}%"},
            {"trigger": "Days past due",
             "rule": f"{SICR_DPD_DAYS} or more days past due"},
        ],
        "default_presumption": f"{DEFAULT_DPD_DAYS} or more days past due, or a "
                               "recorded default event",
        "measurement": {
            "Stage 1": "12-month expected credit loss",
            "Stage 2": "Lifetime expected credit loss",
            "Stage 3": "Lifetime expected credit loss",
        },
        "lifetime_horizon_years": LIFETIME_HORIZON_YEARS,
        "scenario_weights": [
            {"scenario": name, "weight": weight, "ecl_multiplier": multiplier}
            for name, weight, multiplier in SCENARIO_WEIGHTS],
        "weighted_factor": round(WEIGHTED_SCENARIO_FACTOR, 6),
    }


__all__ = [
    "DEFAULT_DPD_DAYS", "LIFETIME_HORIZON_YEARS", "POLICY_OWNER",
    "POLICY_VERSION", "SCENARIO_WEIGHTS", "SICR_ABSOLUTE_PD",
    "SICR_DPD_DAYS", "SICR_PD_ABSOLUTE", "SICR_PD_RATIO", "Triggers",
    "WEIGHTED_SCENARIO_FACTOR", "describe", "lifetime_pd", "measured_ecl",
    "sicr", "stage_of",
]
