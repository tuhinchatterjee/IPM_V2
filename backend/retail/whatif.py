"""
Retail What-If: the same snapshot, the same engine, a changed assumption.

A scenario here does not multiply a total by a percentage. It rebuilds each
facility's hazard curve, exposure path and loss given default from the inputs
the canonical row already carries, applies the requested shock to those inputs,
and runs the identical ECL engine that produced the published figure. That is
why a neutral scenario reproduces the baseline exactly rather than nearly, and
why a shock to lifetime PD changes lifetime ECL rather than only a number on a
card.

The distinctions the engine refuses to blur:

* **Relative and absolute are different operations.** +20% relative on a PD of
  0.02 is 0.024. +2 percentage points is 0.04. A card utilisation move from 40%
  to 60% is +20 percentage points, not a 20% relative increase.
* **The BASELINE is the snapshot's weighted, final ECL.** The scenario "base"
  ECL is one of the three macroeconomic scenarios inside it. Two different
  quantities, two different field names.
* **An assumption is not an observation.** A shock to current income does not
  reach the application score, the origination inputs or the bureau score at
  origination. Those were facts on a date that has passed.
* **A defaulted facility has no performing PD to shock.** Stage 3 responds to
  recovery and delay assumptions; a PD multiplier on it is refused, not
  silently clipped at one.

Canonical data is never mutated. A scenario is a copy with its own run identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.retail import ecl as ecl_mod
from backend.retail.config import RetailDemoConfig
from backend.retail.policy import RECOVERY_POLICY, STAGING_POLICY

METHODOLOGY_VERSION = "retail-whatif-1.0.0"

#: Every methodology this engine actually implements. An unsupported request is
#: answered with this list, not by falling through to something else.
SUPPORTED_METHODOLOGIES: dict[str, str] = {
    "pd_relative": "Multiply the point-in-time PD anchor by (1 + shock). +20% on 0.02 gives 0.024.",
    "pd_absolute_pp": "Add a number of percentage points to the PD anchor. +2pp on 0.02 gives 0.04.",
    "lgd_relative": "Multiply loss given default by (1 + shock), inside its declared bounds.",
    "collateral_value_pct": "Move current collateral values, which flows through LGD for secured products.",
    "recovery_delay_months": "Add months to the expected recovery delay, discounting recoveries further.",
    "utilisation_pp": "Move card utilisation by percentage points, changing drawn balance and undrawn commitment.",
    "ccf_absolute": "Set the credit conversion factor applied to undrawn card commitments.",
    "scenario_weights": "Reweight the three macroeconomic scenarios and recompute the weighted identity.",
    "income_pct": "Move verified current income, which flows through affordability and the behavioural score.",
    "behavioural_score_points": "Shift the behavioural score, which reaches PD through the versioned score-to-PD mapping.",
    "staging_mode": "frozen_stage keeps each facility's published stage; reevaluate_stage re-runs the staging policy.",
    "cutoff_replay": "Replay a different application-score cutoff over the BOOKED originations only.",
}

#: What a NEUTRAL scenario — no shocks, published weights — must reproduce.
#:
#: Zero, on every row, and that is a claim about arithmetic rather than about
#: materiality. The build publishes each SCENARIO ECL rounded to the halala and
#: then carries the weighted and final allowance as the exact weighted
#: combination of those published values. This rebuild does the same, so a
#: neutral scenario returns the published figure itself.
#:
#: It did not always. The rebuild used to round the weighted and final values a
#: second time to the halala, which the build never does. With weights
#: 0.6/0.2/0.2 over per-scenario values on a 0.01 grid, the published allowance
#: sits on a 0.002 grid — gcd(0.6, 0.2, 0.2) × 0.01 — and snapping that to 0.01
#: displaces every row by up to 0.004. Across the personal-finance book at
#: 2026-08 the row displacements summed to |SAR 17.86| and netted to SAR −0.52
#: on SAR 8,994,011.87. The net was small and the per-row error was not, which
#: is why "six parts in a hundred million" was never evidence of the cause.
#:
#: The bound below is kept as a GUARD, not as an allowance: it is what a run is
#: checked against so a future regression is reported rather than absorbed.
PARITY_PER_FACILITY_SAR = 0.01
PARITY_RELATIVE_TOTAL = 1e-6

FROZEN_STAGE = "frozen_stage"
REEVALUATE_STAGE = "reevaluate_stage"


class UnsupportedShock(ValueError):
    """Raised with the list of methodologies that are actually implemented."""

    def __init__(self, name: str):
        super().__init__(
            f"'{name}' is not a supported retail What-If methodology. "
            f"Supported: {', '.join(sorted(SUPPORTED_METHODOLOGIES))}."
        )
        self.name = name


@dataclass
class Scenario:
    """A scenario's complete, reproducible definition."""

    name: str
    dataset_version: str
    snapshot_date: str
    filters: dict[str, Any] = field(default_factory=dict)
    shocks: dict[str, Any] = field(default_factory=dict)
    staging_mode: str = FROZEN_STAGE
    scenario_weights: dict[str, float] | None = None
    methodology_version: str = METHODOLOGY_VERSION
    notes: str = ""

    def validate(self) -> None:
        for name in self.shocks:
            if name not in SUPPORTED_METHODOLOGIES:
                raise UnsupportedShock(name)
        if self.staging_mode not in (FROZEN_STAGE, REEVALUATE_STAGE):
            raise ValueError(
                f"staging_mode must be '{FROZEN_STAGE}' or '{REEVALUATE_STAGE}', "
                f"not {self.staging_mode!r}. The difference matters: one is a parameter "
                "sensitivity at fixed stages, the other re-runs the staging policy."
            )
        if self.scenario_weights is not None:
            total = sum(self.scenario_weights.get(s, 0.0) for s in ecl_mod.SCENARIOS)
            for s, w in self.scenario_weights.items():
                if not 0.0 <= float(w) <= 1.0:
                    raise ValueError(f"scenario weight for '{s}' is {w}, outside [0, 1]")
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"scenario weights sum to {total}, not 1.0. They are validated, not "
                    "normalised behind your back — say what the three weights should be."
                )

    def run_id(self) -> str:
        payload = json.dumps({
            "name": self.name, "dataset_version": self.dataset_version,
            "snapshot_date": self.snapshot_date, "filters": self.filters,
            "shocks": self.shocks, "staging_mode": self.staging_mode,
            "scenario_weights": self.scenario_weights,
            "methodology_version": self.methodology_version,
        }, sort_keys=True, default=str)
        return "WIF-" + hashlib.sha256(payload.encode()).hexdigest()[:20]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id(), "name": self.name,
            "dataset_version": self.dataset_version, "snapshot_date": self.snapshot_date,
            "filters": dict(self.filters), "shocks": dict(self.shocks),
            "staging_mode": self.staging_mode,
            "scenario_weights": dict(self.scenario_weights) if self.scenario_weights else None,
            "methodology_version": self.methodology_version, "notes": self.notes,
        }


def select(frame: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    """The scenario population. An empty result is an honest empty result."""
    out = frame
    for column, wanted in (filters or {}).items():
        if column not in out.columns:
            raise KeyError(
                f"cannot filter on '{column}': the canonical dataset has no such column"
            )
        values = wanted if isinstance(wanted, (list, tuple, set)) else [wanted]
        out = out.loc[out[column].isin(list(values))]
    return out


def _recompute(
    frame: pd.DataFrame, scenario: Scenario, weights: dict[str, float],
) -> dict[str, np.ndarray]:
    """Rebuild every facility's ECL from its stored inputs, with shocks applied."""
    n = len(frame)
    shocks = scenario.shocks
    num = lambda c: pd.to_numeric(frame[c], errors="coerce").to_numpy(dtype="float64")  # noqa: E731

    stage = frame["ifrs9_stage"].to_numpy(dtype="int64")
    gca = num("gross_carrying_amount_sar")
    mrate = num("monthly_discount_rate")
    months_on_book = num("months_on_book")
    remaining_life = num("ecl_remaining_life_months").astype("int64")
    contractual_remaining = num("ecl_contractual_remaining_months")
    drawn = num("ecl_drawn_balance_sar")
    undrawn = np.nan_to_num(num("ecl_undrawn_commitment_sar"), nan=0.0)
    is_card = (frame["product_code"] == "CREDIT_CARD").to_numpy()
    recovery_rate = num("recovery_rate_nominal")
    delay = num("recovery_delay_months")
    pd_anchor = num("pd_pit_12m_anchor")

    # --- PD shocks. Relative and absolute are different operations. --------
    if "pd_relative" in shocks:
        pd_anchor = pd_anchor * (1.0 + float(shocks["pd_relative"]))
    if "pd_absolute_pp" in shocks:
        pd_anchor = pd_anchor + float(shocks["pd_absolute_pp"]) / 100.0

    # --- Behavioural score shift reaches PD only through the mapping -------
    if "behavioural_score_points" in shocks:
        from backend.retail.generate import IFRS9_PD_MAP_B
        from backend.retail.scorecards import FACTOR
        # A score change of `points` is a logit change of -points / FACTOR on the
        # model's own scale; the versioned mapping's slope carries it into the
        # IFRS 9 PD.
        delta_logit = -float(shocks["behavioural_score_points"]) / FACTOR * IFRS9_PD_MAP_B
        logit = np.log(np.clip(pd_anchor, 1e-9, 1 - 1e-9) / (1 - np.clip(pd_anchor, 1e-9, 1 - 1e-9)))
        pd_anchor = 1.0 / (1.0 + np.exp(-(logit + delta_logit)))

    # --- Income shock: affordability first, then the score, then PD --------
    income_effect = np.zeros(n)
    if "income_pct" in shocks:
        pct = float(shocks["income_pct"])
        income = num("verified_total_monthly_income_sar") * (1.0 + pct)
        obligations = num("monthly_total_credit_obligations_sar")
        new_dbr = np.where(income > 0, obligations / np.where(income > 0, income, 1.0), np.nan)
        old_dbr = num("debt_burden_ratio")
        # Only the dependency the configured model actually carries: a worse
        # debt burden lowers the behavioural score's affordability evidence and
        # therefore raises PD. Nothing here touches origination inputs.
        income_effect = np.nan_to_num(new_dbr - old_dbr, nan=0.0)
        logit = np.log(np.clip(pd_anchor, 1e-9, 1 - 1e-9) / (1 - np.clip(pd_anchor, 1e-9, 1 - 1e-9)))
        pd_anchor = 1.0 / (1.0 + np.exp(-(logit + 1.15 * income_effect)))

    pd_anchor = np.clip(pd_anchor, 0.0, 1.0)

    # --- Utilisation and CCF change exposure, not probability --------------
    if "utilisation_pp" in shocks:
        move = float(shocks["utilisation_pp"]) / 100.0
        limit = drawn + undrawn
        new_drawn = np.where(is_card, np.clip(drawn + move * limit, 0.0, limit), drawn)
        undrawn = np.where(is_card, np.maximum(limit - new_drawn, 0.0), undrawn)
        drawn = new_drawn
        gca = np.where(is_card, new_drawn, gca)
    ccf = float(shocks.get("ccf_absolute", 0.45))

    # --- LGD and recovery ---------------------------------------------------
    if "collateral_value_pct" in shocks:
        secured = (frame["secured_flag"].fillna(False).to_numpy(dtype=bool)
                   if "secured_flag" in frame.columns
                   else np.zeros(len(frame), dtype=bool))
        recovery_rate = np.where(
            secured, np.clip(recovery_rate * (1.0 + float(shocks["collateral_value_pct"])), 0.0, 1.0),
            recovery_rate)
    if "recovery_delay_months" in shocks:
        delay = np.maximum(delay + float(shocks["recovery_delay_months"]), 0.0)

    base_lgd = ecl_mod.lgd_from_recovery(
        recovery_rate, delay, mrate,
        floor=RECOVERY_POLICY.lgd_floor, cap=RECOVERY_POLICY.lgd_cap)
    if "lgd_relative" in shocks:
        base_lgd = np.clip(base_lgd * (1.0 + float(shocks["lgd_relative"])),
                           RECOVERY_POLICY.lgd_floor, RECOVERY_POLICY.lgd_cap)

    n_months = max(int(remaining_life.max()) if n else 12, 12)
    k = np.arange(1, n_months + 1)[None, :].astype("float64")
    from backend.retail.generate import _amortised_balance
    amort = _amortised_balance(
        gca[:, None] * np.ones((1, n_months)),
        mrate[:, None] * np.ones((1, n_months)),
        np.maximum(contractual_remaining, 1)[:, None] * np.ones((1, n_months)),
        k * np.ones((n, 1)))
    card = (drawn + ccf * undrawn)[:, None] * np.ones((1, n_months))
    ead_path_base = np.where(is_card[:, None], card, amort)

    hazard_base = ecl_mod.seasoned_hazard_path(pd_anchor, months_on_book, n_months)

    # --- Staging ------------------------------------------------------------
    if scenario.staging_mode == REEVALUATE_STAGE:
        _, marg = ecl_mod.survival_and_marginal(hazard_base)
        pd_life = ecl_mod.cumulative_pd(marg, remaining_life)
        reference = num("pd_origination_curve_remaining_life")
        ratio = np.where(reference > 0, pd_life / np.where(reference > 0, reference, 1.0), np.nan)
        quant = ((~np.isnan(ratio)) & (ratio >= STAGING_POLICY.sicr_pd_ratio_threshold)) | (
            (pd_life - reference) >= STAGING_POLICY.sicr_pd_absolute_threshold)
        backstop = num("dpd") >= STAGING_POLICY.stage2_dpd_backstop
        defaulted = (frame["current_default_flag"].fillna(False).to_numpy(dtype=bool)
                     if "current_default_flag" in frame.columns
                     else np.zeros(len(frame), dtype=bool))
        stage = np.where(defaulted, 3, np.where(quant | backstop, 2, 1)).astype("int64")

    scenario_ecl: dict[str, np.ndarray] = {}
    from backend.retail.config import load_config
    scen = load_config().scenarios
    for s in ecl_mod.SCENARIOS:
        res = ecl_mod.compute_ecl(ecl_mod.EclInputs(
            stage=stage,
            ead_path=ead_path_base * scen.ead_multiplier[s],
            hazard_path=np.clip(hazard_base * scen.hazard_multiplier[s], 0.0, 1.0),
            lgd=np.clip(base_lgd * scen.lgd_multiplier[s],
                        RECOVERY_POLICY.lgd_floor, RECOVERY_POLICY.lgd_cap),
            monthly_discount_rate=mrate,
            remaining_life_months=remaining_life,
            gross_carrying_amount=gca,
            stage3_recovery_rate_nominal=recovery_rate,
            stage3_delay_months=np.maximum(delay + scen.recovery_delay_add_months[s], 0.0),
        ))
        scenario_ecl[s] = np.round(res.ecl, 2)

    # NOT rounded, and that is the whole of the parity story.
    #
    # The build publishes each SCENARIO ECL rounded to the halala — that is the
    # figure a reader quotes — and then carries the weighted and final
    # allowance as the EXACT weighted combination of those published values, so
    # the identity on screen holds rather than nearly holding. This rebuild
    # rounded the weighted and final values a second time, to the halala, which
    # the build never does. With weights 0.6/0.2/0.2 over values on a 0.01
    # grid, the published allowance lands on a 0.002 grid; snapping it to 0.01
    # moved every row by up to 0.004 and left SAR 0.52 across the
    # personal-finance book. Doing the same arithmetic as the build reproduces
    # the published figure exactly, on every row.
    weighted = ecl_mod.weighted_ecl(scenario_ecl, weights)
    overlay = np.nan_to_num(num("management_overlay_sar"), nan=0.0)
    return {
        "stage": stage,
        "gca": gca,
        "ecl_base": scenario_ecl["base"],
        "ecl_upturn": scenario_ecl["upturn"],
        "ecl_downturn": scenario_ecl["downturn"],
        "ecl_weighted": weighted,
        "ecl_final": ecl_mod.final_ecl(weighted, overlay),
    }


def _pct_change(new: float, old: float) -> float | None:
    """None, not infinity, when the baseline denominator is zero."""
    if old == 0:
        return None
    return (new - old) / old


def run(frame: pd.DataFrame, scenario: Scenario, cfg: RetailDemoConfig) -> dict[str, Any]:
    """Run a scenario and return baseline, scenario, deltas, drivers and limits."""
    scenario.validate()
    population = select(frame, scenario.filters)

    weights = {s: float((scenario.scenario_weights or cfg.scenarios.weights)[s])
               for s in ecl_mod.SCENARIOS}

    baseline = {
        "facilities": int(len(population)),
        "customers": int(population["customer_id"].nunique()) if len(population) else 0,
        "gross_carrying_amount_sar": float(population["gross_carrying_amount_sar"].sum()),
        "ecl_base_sar": float(population["ecl_base_sar"].sum()),
        "ecl_upturn_sar": float(population["ecl_upturn_sar"].sum()),
        "ecl_downturn_sar": float(population["ecl_downturn_sar"].sum()),
        "ecl_weighted_sar": float(population["ecl_weighted_sar"].sum()),
        "ecl_final_sar": float(population["ecl_final_sar"].sum()),
        "stage_counts": population["ifrs9_stage"].value_counts().sort_index().to_dict(),
    }

    if population.empty:
        return {
            "scenario": scenario.to_dict(),
            "population_empty": True,
            "baseline": baseline,
            "scenario_result": baseline,
            "delta": {"ecl_final_sar": 0.0, "ecl_final_pct": None},
            "limitations": [
                "The selected filters match no facility at this snapshot. This is an empty "
                "result, not a zero: there is nothing to shock."
            ],
            "assumptions": [],
            "drivers": [],
        }

    result = _recompute(population, scenario, weights)
    scen_totals = {
        "facilities": int(len(population)),
        "customers": int(population["customer_id"].nunique()),
        "gross_carrying_amount_sar": float(result["gca"].sum()),
        "ecl_base_sar": float(result["ecl_base"].sum()),
        "ecl_upturn_sar": float(result["ecl_upturn"].sum()),
        "ecl_downturn_sar": float(result["ecl_downturn"].sum()),
        "ecl_weighted_sar": float(result["ecl_weighted"].sum()),
        "ecl_final_sar": float(result["ecl_final"].sum()),
        "stage_counts": pd.Series(result["stage"]).value_counts().sort_index().to_dict(),
    }

    contributions = (
        pd.DataFrame({
            "product_code": population["product_code"].to_numpy(),
            "baseline": population["ecl_final_sar"].to_numpy(dtype="float64"),
            "scenario": result["ecl_final"],
        })
        .groupby("product_code", as_index=False)
        .sum(numeric_only=True)
    )
    contributions["delta_sar"] = contributions["scenario"] - contributions["baseline"]
    contributions = contributions.sort_values("delta_sar", ascending=False)

    limitations = _limitations(population, scenario)
    neutral = not scenario.shocks and scenario.scenario_weights is None
    return {
        "scenario": scenario.to_dict(),
        "parity": _parity(population, result) if neutral else None,
        "population_empty": False,
        "baseline": baseline,
        "scenario_result": scen_totals,
        "delta": {
            "ecl_final_sar": round(scen_totals["ecl_final_sar"] - baseline["ecl_final_sar"], 2),
            "ecl_final_pct": _pct_change(scen_totals["ecl_final_sar"], baseline["ecl_final_sar"]),
            "gross_carrying_amount_sar": round(
                scen_totals["gross_carrying_amount_sar"] - baseline["gross_carrying_amount_sar"], 2),
        },
        "drivers": contributions.to_dict("records"),
        "assumptions": [
            f"Baseline is the snapshot's weighted, final ECL for the selected population, "
            f"not its BASE macroeconomic scenario ECL "
            f"(SAR {baseline['ecl_final_sar']:,.0f} against SAR {baseline['ecl_base_sar']:,.0f}).",
            f"Scenario weights base/upturn/downturn = "
            f"{weights['base']}/{weights['upturn']}/{weights['downturn']}.",
            f"Staging mode: {scenario.staging_mode}.",
            "Synthetic demonstration engine and synthetic data. Not an approved model.",
        ],
        "limitations": limitations,
        "evidence": {
            "dataset_version": scenario.dataset_version,
            "snapshot_date": scenario.snapshot_date,
            "facility_count": int(len(population)),
            "run_id": scenario.run_id(),
            "methodology_version": scenario.methodology_version,
        },
    }


def _parity(population: pd.DataFrame, result: dict[str, np.ndarray]) -> dict[str, Any]:
    """How exactly a neutral run reproduces the published book, checked row by row.

    A scenario that changes nothing must return what the book already says. It
    does not land on it exactly, and that is a fact about the data rather than
    about the engine: the published figures sit on a 0.002 SAR grid and the
    recomputation is continuous. Reported, with the tolerance it is measured
    against, so nobody has to decide for themselves whether half a riyal on
    nine million is a defect.
    """
    published = population["ecl_final_sar"].to_numpy(dtype="float64")
    rebuilt = np.asarray(result["ecl_final"], dtype="float64")
    residual = rebuilt - published
    total = float(published.sum())
    total_residual = float(residual.sum())
    relative = abs(total_residual) / total if total else 0.0
    worst = float(np.max(np.abs(residual))) if len(residual) else 0.0
    outside = int(np.sum(np.abs(residual) > PARITY_PER_FACILITY_SAR))
    return {
        "published_ecl_final_sar": round(total, 2),
        "rebuilt_ecl_final_sar": round(float(rebuilt.sum()), 2),
        "total_residual_sar": round(total_residual, 4),
        "relative_residual": relative,
        "max_facility_residual_sar": round(worst, 4),
        "facilities_outside_tolerance": outside,
        "tolerance": {
            "per_facility_sar": PARITY_PER_FACILITY_SAR,
            "relative_total": PARITY_RELATIVE_TOTAL,
        },
        "within_tolerance": bool(outside == 0
                                 and relative <= PARITY_RELATIVE_TOTAL),
        "explanation": (
            "A neutral scenario rebuilds every facility's ECL from its stored "
            "inputs and compares it with the published figure. The published "
            "book holds money on a 0.002 SAR grid and the rebuild is "
            "continuous, so the two differ by a fraction of a halala per "
            "facility. The difference is reported rather than removed: "
            "rounding the rebuild onto the published grid would hide a real "
            "engine error the day there is one."),
    }


def _limitations(population: pd.DataFrame, scenario: Scenario) -> list[str]:
    out: list[str] = []
    defaulted = int((population["ifrs9_stage"] == 3).sum())
    if defaulted and ({"pd_relative", "pd_absolute_pp"} & set(scenario.shocks)):
        out.append(
            f"{defaulted:,} facilities are already credit-impaired. A PD shock does not apply to "
            "them: their loss is measured from expected recoveries, so their ECL responds to the "
            "collateral and recovery-delay shocks instead and is unchanged by this one."
        )
    if "income_pct" in scenario.shocks:
        out.append(
            "The income shock reaches affordability, the behavioural evidence and the mapped "
            "IFRS 9 PD. It does NOT change the application score, the origination inputs or the "
            "bureau score at origination: those were observed facts on a past date."
        )
    if "utilisation_pp" in scenario.shocks:
        out.append(
            "Utilisation moves are in percentage points and apply to revolving facilities only. "
            "Amortising loans have no utilisation and are unaffected."
        )
    if scenario.staging_mode == FROZEN_STAGE:
        out.append(
            "Stages are held at their published values, so this is a parameter sensitivity at "
            "fixed stages. Re-run with staging_mode='reevaluate_stage' to let facilities migrate."
        )
    return out


def cutoff_replay(
    frame: pd.DataFrame, new_cutoff: dict[str, float],
) -> dict[str, Any]:
    """Replay a different application-score cutoff over the BOOKED originations.

    What this can say: which historically funded accounts a tighter cutoff would
    have excluded, and — where the outcome window has closed — what those
    accounts actually went on to do.

    What it cannot say, and does not pretend to: the bank's future approval
    rate, the loss a tighter policy would have avoided, or anything at all about
    customers who were declined. This dataset contains booked facilities. The
    declined applications and their outcomes are not in it, and no row is
    invented to fill the gap.

    Three things this deliberately refuses to do
    --------------------------------------------
    **It does not count products the cutoff was not asked about.** A cutoff
    named for personal finance is replayed on personal finance. Leaving the
    other products in the denominator turned "one in five personal-finance
    accounts" into "one in five accounts", which is a different and smaller
    number about a different book.

    **It does not report an unknown outcome as a zero.** At the latest month no
    facility's outcome window has closed yet, so every default count would be
    0 — indistinguishable, on the page, from a clean book. The counts are
    omitted and their absence is stated instead.

    **It does not treat a cutoff below the policy in force as an insight.** Such
    a cutoff excludes nobody; the accounts it would have ADDED were never
    booked, so this data cannot speak to it at all.
    """
    booked = frame.drop_duplicates("facility_id").copy()

    # Only the products the cutoff was asked about. Anything else is not in
    # this question, and must not sit in its denominator.
    asked = [str(code) for code in new_cutoff]
    booked = booked[booked["product_code"].astype(str).isin(asked)]

    score = pd.to_numeric(booked["application_score_at_origination"], errors="coerce")
    cutoff = booked["product_code"].astype(str).map(
        {str(k): float(v) for k, v in new_cutoff.items()})
    excluded = (score < cutoff).fillna(False)

    outcome = booked["observed_default_within_window"]
    known = outcome.notna()

    # The lowest score that WAS booked, per product. Without it a reader cannot
    # tell whether the cutoff they asked about was already below the policy in
    # force — in which case the replay excludes nobody and the honest answer is
    # that this data cannot speak to it, not a tidy row of zeros.
    floors = {
        str(code): float(group.min())
        for code, group in score.groupby(booked["product_code"].astype(str))
        if group.notna().any()
    }
    inert = sorted(code for code, level in new_cutoff.items()
                   if str(code) in floors and float(level) <= floors[str(code)])

    limitations = [
        "This is a retrospective replay over accounts that WERE booked. It is not the bank's "
        "future approval rate.",
        "It is descriptive, not causal: the excluded accounts differ from the retained ones in "
        "more than their score.",
        "It says nothing about applicants who were declined. Their applications and outcomes "
        "are not in this dataset, and none has been manufactured.",
        "A LOWER cutoff cannot be evaluated at all from this data: the accounts it would have "
        "approved were never booked, so their outcomes do not exist.",
    ]
    if inert:
        limitations.insert(0, (
            "A cutoff at or below the lowest score actually booked excludes nobody, so this "
            "replay says nothing about " + ", ".join(inert) + ". The lowest booked score there is "
            + ", ".join(f"{code} {floors[code]:.0f}" for code in inert) + "."))

    out: dict[str, Any] = {
        "methodology": "cutoff_replay",
        "population": "BOOKED_ORIGINATIONS_ONLY",
        "products": sorted(asked),
        "new_cutoff": {str(k): float(v) for k, v in new_cutoff.items()},
        "booked_facilities": int(len(booked)),
        "would_be_excluded": int(excluded.sum()),
        "would_be_excluded_pct": float(excluded.mean()) if len(booked) else None,
        "excluded_exposure_sar": float(
            booked.loc[excluded, "gross_carrying_amount_sar"].sum()),
        "lowest_booked_score": floors,
        "cutoffs_below_the_policy_in_force": inert,
        "outcome_known_facilities": int(known.sum()),
        "outcomes_available": bool(known.any()),
    }

    if known.any():
        out.update({
            "excluded_with_known_outcome": int((excluded & known).sum()),
            "excluded_observed_defaults": int(
                booked.loc[excluded & known, "observed_default_within_window"].astype(bool).sum()),
            "retained_with_known_outcome": int((~excluded & known).sum()),
            "retained_observed_defaults": int(
                booked.loc[~excluded & known, "observed_default_within_window"].astype(bool).sum()),
        })
    else:
        # Not zero defaults — no closed outcome window. Reporting 0 here would
        # read on the page as a book that never defaulted.
        limitations.insert(0, (
            "No facility in this population has a closed outcome window at this month, so what "
            "the excluded accounts went on to do is NOT KNOWN here — it is not zero. Ask the "
            "same question at an earlier reporting month, where the window has closed."))

    out["limitations"] = limitations
    return out
