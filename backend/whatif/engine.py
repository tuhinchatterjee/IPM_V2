"""
The What-If calculation: one borrower at a time, then added up.

The order matters
-----------------
Every scenario is computed borrower by borrower and only then aggregated. That
is not a style preference. Computing a portfolio ECL and allocating it down
produces a number that no borrower in the book can be shown to have caused, and
the first question anyone asks about a stressed ECL is "which names?". If the
answer has to be reverse-engineered it is not an answer.

So the shape is always:

    baseline per borrower
      -> apply the shocks to that borrower's own PD, LGD, EAD and collateral
      -> re-read the governed SICR triggers against the STRESSED PD
      -> re-stage
      -> re-measure ECL on the Stage's own basis
      -> delta per borrower
      -> aggregate

The base reproduces the book exactly
------------------------------------
The recomputed baseline ECL agrees with the reported ECL to rounding, but "to
rounding" is not good enough for a committee table where the base column has to
tie to the accounts. So the stressed ECL is carried onto the REPORTED basis:

    stressed_ecl = reported_ecl x (measured_stressed / measured_baseline)

The base column is then the reported figure, exactly, and the ratio is entirely
governed — PD, LGD, EAD and the Stage's measurement basis, nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.ifrs9 import policy
from backend.whatif import masterscale as ms
from backend.whatif import scenarios as sc
from backend.whatif import sensitivity as sv

#: What the engine reads. Everything else in the answer is derived from these.
FIELDS: tuple[str, ...] = (
    "borrower_id", "display_name", "legal_name", "sector", "segment",
    "group_id", "group_name", "period",
    "internal_rating", "internal_rating_numeric", "watchlist_flag",
    "stage", "pd_12m", "pd_lifetime", "lgd", "ead", "final_ecl",
    "ecl_12m", "ecl_lifetime", "management_overlay", "ecl_coverage",
    "current_dpd", "default_flag",
    "collateral_market_value", "collateral_coverage_pct",
    "collateral_shortfall", "secured_exposure", "unsecured_exposure",
    "undrawn_commitment", "total_limit", "drawn_exposure",
    "covenants_breached", "minimum_headroom_pct", "covenant_count",
    "revenue", "ebitda", "ebitda_margin", "dscr", "interest_coverage",
    "leverage", "net_leverage", "free_cash_flow", "working_capital",
    "cash_conversion_cycle_days",
)

#: The origination PD is not on the 360 snapshot; it is on the IFRS 9 dataset,
#: and re-evaluating the relative SICR trigger is impossible without it.
IFRS9_FIELDS: tuple[str, ...] = (
    "borrower_id", "period", "pd_at_origination_pct",
    "sicr_trigger_pd", "sicr_trigger_dpd", "sicr_trigger_watchlist",
)

CURRENCY = "SAR"


@dataclass
class Result:
    """A scenario run: the borrower table, the aggregates and the assumptions."""

    scenario: sc.Scenario
    period: str
    borrowers: pd.DataFrame
    summary: dict[str, Any] = field(default_factory=dict)
    by_sector: pd.DataFrame = field(default_factory=pd.DataFrame)
    by_rating: pd.DataFrame = field(default_factory=pd.DataFrame)
    by_stage: pd.DataFrame = field(default_factory=pd.DataFrame)
    sensitivity_rows: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: The full working frame — every reported and stressed column, before the
    #: presentation layer narrows it. Kept so a SECOND ECL methodology can be
    #: applied to exactly the same shocked book rather than re-deriving it,
    #: which is how the Delta and ML answers stay comparable.
    frame: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def population_size(self) -> int:
        return int(len(self.borrowers))

    def top_contributors(self, count: int = 10) -> pd.DataFrame:
        if self.borrowers.empty:
            return self.borrowers
        return self.borrowers.nlargest(count, "ecl_increase")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.to_dict(),
            "period": self.period,
            "currency": CURRENCY,
            "summary": dict(self.summary),
            "population": self.population_size,
            "steps": list(self.steps),
            "sensitivity": list(self.sensitivity_rows),
            "warnings": list(self.warnings),
        }


# ------------------------------------------------------------------ reading


BORROWER_SNAPSHOT = "corporate_borrower_360"
IFRS9_DATASET = "corporate_ifrs9"


def latest_period(source: Any = None) -> str:
    """The most recent period the borrower snapshot publishes."""
    from backend.data_access.duckdb_source import DuckDBSource

    reader = source or DuckDBSource()
    periods = reader.periods(BORROWER_SNAPSHOT)
    if not periods:  # pragma: no cover - an empty lake
        raise ValueError("The corporate borrower snapshot publishes no periods.")
    return str(periods[-1])


def _read(period: str, source: Any = None) -> tuple[pd.DataFrame, str]:
    """The book for one period, joined to the IFRS 9 origination PD.

    The origination PD lives on the IFRS 9 dataset rather than on the snapshot,
    and without it the RELATIVE SICR trigger cannot be re-evaluated — which
    would silently turn "which borrowers become Stage 2" into a question about
    the absolute PD threshold alone.
    """
    from backend.data_access.context import AnalysisContext
    from backend.data_access.duckdb_source import DuckDBSource

    reader = source or DuckDBSource()
    settled = str(period or "").strip() or latest_period(reader)
    context = AnalysisContext(period=settled)
    available = set(reader.fields(BORROWER_SNAPSHOT))
    frame = reader.fetch(BORROWER_SNAPSHOT, context=context,
                         fields=[f for f in FIELDS if f in available],
                         period=settled)
    if frame.empty:
        raise ValueError(f"No corporate borrower data for {settled}.")
    ifrs9_available = set(reader.fields(IFRS9_DATASET))
    keep = [f for f in IFRS9_FIELDS if f in ifrs9_available]
    if keep:
        ifrs9 = reader.fetch(IFRS9_DATASET, context=context, fields=keep,
                             period=settled)
        join_on = [c for c in ("borrower_id", "period") if c in ifrs9.columns
                   and c in frame.columns]
        if join_on:
            frame = frame.merge(ifrs9, on=join_on, how="left",
                                suffixes=("", "_ifrs9"))
    return frame, settled


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def select(frame: pd.DataFrame, population: sc.Population) -> pd.DataFrame:
    """Narrow the book to the scenario's population."""
    work = frame
    if population.sectors:
        wanted = {s.strip().lower() for s in population.sectors}
        work = work[work["sector"].astype(str).str.strip().str.lower().isin(wanted)]
    if population.rating_bands:
        grades: set[str] = set()
        for band in population.rating_bands:
            grades.update(ms.grades_in(band))
        if grades:
            work = work[work["internal_rating"].astype(str).str.upper().isin(grades)]
    if population.stages:
        work = work[pd.to_numeric(work["stage"], errors="coerce").isin(
            list(population.stages))]
    if population.borrower_ids:
        wanted_ids = {str(b).strip().upper() for b in population.borrower_ids}
        work = work[work["borrower_id"].astype(str).str.upper().isin(wanted_ids)]
    if population.watchlist_only and "watchlist_flag" in work.columns:
        work = work[work["watchlist_flag"].astype(bool)]
    return work.copy()


# ------------------------------------------------------------------ shocks


def _apply_rating(work: pd.DataFrame, notches: int,
                  steps: list[dict[str, Any]]) -> None:
    """Rating shock, through the governed masterscale rather than a multiplier."""
    moves = ms.factors(work["internal_rating"], notches)
    for column in moves.columns:
        work[column] = moves[column].to_numpy()
    work["pd_stressed"] = work["pd_stressed"] * work["rating_pd_factor"]
    steps.append({
        "step": "Rating shock",
        "detail": f"{notches:+d} notch(es) applied through the governed rating "
                  f"masterscale ({ms.MASTERSCALE_VERSION}). Each borrower's own "
                  "PD is scaled by the ratio between the two grades' "
                  "masterscale PDs, so within-grade calibration is preserved.",
        "affected": int((work["notches_moved"] != 0).sum()),
    })


def _apply_pd(work: pd.DataFrame, shock: sc.Shock,
              steps: list[dict[str, Any]]) -> None:
    if shock.unit == sc.RELATIVE:
        work["pd_stressed"] = work["pd_stressed"] * (1.0 + shock.magnitude / 100.0)
        detail = f"12-month PD scaled by {1.0 + shock.magnitude / 100.0:.2f}."
    elif shock.unit == sc.ABSOLUTE_PP:
        work["pd_stressed"] = work["pd_stressed"] + shock.magnitude
        detail = f"{shock.magnitude:+g} percentage points added to 12-month PD."
    elif shock.unit == sc.BASIS_POINTS:
        work["pd_stressed"] = work["pd_stressed"] + shock.magnitude / 100.0
        detail = f"{shock.magnitude:+g} basis points added to 12-month PD."
    else:  # pragma: no cover - the parser never produces another unit
        return
    steps.append({"step": "PD shock", "detail": detail, "affected": len(work)})


def _apply_lgd(work: pd.DataFrame, shock: sc.Shock,
               steps: list[dict[str, Any]]) -> None:
    if shock.unit == sc.RELATIVE:
        work["lgd_stressed"] = work["lgd_stressed"] * (1.0 + shock.magnitude / 100.0)
        detail = f"LGD scaled by {1.0 + shock.magnitude / 100.0:.2f}."
    else:
        work["lgd_stressed"] = work["lgd_stressed"] + shock.magnitude
        detail = f"{shock.magnitude:+g} percentage points added to LGD."
    steps.append({"step": "LGD shock", "detail": detail, "affected": len(work)})


def _apply_ead(work: pd.DataFrame, shock: sc.Shock,
               steps: list[dict[str, Any]]) -> None:
    """Exposure shock, capped at the committed limit.

    Drawing more than the committed limit is not a scenario, it is a breach —
    so undrawn commitment is the ceiling on a utilisation shock rather than an
    unbounded percentage.
    """
    uplift = work["ead_stressed"] * (shock.magnitude / 100.0)
    headroom = work.get("undrawn_commitment")
    if headroom is not None:
        uplift = np.minimum(uplift, pd.to_numeric(headroom, errors="coerce").fillna(0.0))
    work["ead_stressed"] = work["ead_stressed"] + uplift.clip(lower=0)
    steps.append({
        "step": "Exposure shock",
        "detail": f"Exposure at default raised by {shock.magnitude:g}%, capped "
                  "at each borrower's undrawn committed limit.",
        "affected": int((uplift > 0).sum()),
    })


def _apply_collateral(work: pd.DataFrame, shock: sc.Shock,
                      assumptions: sc.Assumptions,
                      steps: list[dict[str, Any]]) -> None:
    """Collateral haircut, and its structural transmission into LGD.

    A security value that falls recovers less. The transmission is applied only
    to the SECURED share of the exposure, because an unsecured borrower's LGD
    does not move when property prices do.
    """
    factor = 1.0 + shock.magnitude / 100.0
    work["collateral_stressed"] = work["collateral_market_value"] * factor
    work["collateral_coverage_stressed"] = np.where(
        work["ead_stressed"] > 0,
        work["collateral_stressed"] / work["ead_stressed"] * 100.0, 0.0)
    work["collateral_shortfall_stressed"] = np.maximum(
        work["ead_stressed"] - work["collateral_stressed"], 0.0)

    affected = 0
    if assumptions.collateral_to_lgd:
        exposure = work["ead_stressed"].replace(0, np.nan)
        secured_share = (work["collateral_market_value"] / exposure).clip(0, 1).fillna(0.0)
        # The recovery lost is the fall in security value over the exposure it
        # was covering, and only up to the share it actually covered.
        lost = secured_share * (-shock.magnitude / 100.0)
        work["lgd_stressed"] = (work["lgd_stressed"]
                                + (lost * 100.0).clip(lower=0)).clip(upper=95.0)
        affected = int((lost > 0).sum())
    steps.append({
        "step": "Collateral shock",
        "detail": f"Security values moved {shock.magnitude:+g}%."
                  + (" The lost recovery is added to LGD on the secured share "
                     "of each exposure." if assumptions.collateral_to_lgd else ""),
        "affected": affected or len(work),
    })


#: Which stressed financial column each sensitivity effect writes to.
_FINANCIAL_COLUMNS: tuple[str, ...] = (
    "revenue", "ebitda", "ebitda_margin", "dscr", "interest_coverage",
    "free_cash_flow", "working_capital", "cash_conversion_cycle_days",
)


def _apply_financial(work: pd.DataFrame, shock: sc.Shock,
                     steps: list[dict[str, Any]]) -> None:
    """A direct shock to a financial measure, and what it does to PD.

    Earnings are not an ECL input, so a shock to them has to reach the answer
    through something that is. The transmission used here is the borrower's own
    debt-service capacity: a fall in EBITDA lowers DSCR and interest coverage
    proportionally, and the PD effect is the configured sensitivity to that
    fall rather than a second free parameter.
    """
    target = shock.target or "ebitda"
    column = f"{target}_stressed"
    if column not in work.columns:
        return
    factor = (1.0 + shock.magnitude / 100.0) if shock.unit == sc.RELATIVE else 1.0
    work[column] = work[column] * factor
    if target in ("ebitda", "revenue", "free_cash_flow"):
        for linked in ("dscr_stressed", "interest_coverage_stressed"):
            if linked in work.columns:
                work[linked] = work[linked] * factor
    # A proportional earnings fall raises PD by the configured elasticity.
    elasticity = sv.BY_KEY["sector_stress"].pd_effect / 0.05
    if shock.magnitude < 0:
        work["pd_stressed"] = work["pd_stressed"] * (
            1.0 + elasticity * (-shock.magnitude / 100.0))
    steps.append({
        "step": f"{target.replace('_', ' ').title()} shock",
        "detail": f"{target.replace('_', ' ')} moved {shock.magnitude:+g}%. "
                  "Debt-service ratios move with it, and the configured "
                  "earnings elasticity carries it into PD.",
        "affected": len(work),
    })


def _apply_ccf(work: pd.DataFrame, shock: sc.Shock,
                steps: list[dict[str, Any]]) -> None:
    """Move the credit conversion factor, and let EAD follow.

        EAD = drawn + CCF x undrawn

    A CCF change is NOT an EAD change of the same size, because the drawn
    balance does not move at all. A borrower half-drawn on a 50% CCF sees a
    20% rise in CCF turn into under 7% of EAD. Converting properly is the
    whole point of offering CCF as a shock rather than telling somebody to
    work out the exposure themselves.
    """
    if "undrawn_commitment" not in work.columns:
        return
    undrawn = pd.to_numeric(work["undrawn_commitment"], errors="coerce").fillna(0.0)
    drawn = (pd.to_numeric(work["drawn_exposure"], errors="coerce").fillna(0.0)
             if "drawn_exposure" in work.columns
             else (work["ead_stressed"] - undrawn).clip(lower=0.0))
    base = pd.to_numeric(work.get("ccf"), errors="coerce") if "ccf" in work.columns \
        else pd.Series(np.nan, index=work.index)
    # Where no CCF is carried, imply it from the borrower's own EAD rather
    # than assuming a number the book never stated.
    implied = ((work["ead_stressed"] - drawn) / undrawn.replace(0, np.nan)).clip(0.0, 1.0)
    current = base.fillna(implied).fillna(0.0)

    if shock.unit == sc.RELATIVE:
        moved = current * (1.0 + shock.magnitude / 100.0)
    elif shock.unit == sc.ABSOLUTE_PP:
        moved = current + shock.magnitude / 100.0
    elif shock.unit == sc.BASIS_POINTS:
        moved = current + shock.magnitude / 10_000.0
    else:
        moved = current
    moved = moved.clip(lower=0.0, upper=1.0)
    work["ccf_stressed"] = moved
    before = float(work["ead_stressed"].sum())
    work["ead_stressed"] = (drawn + moved * undrawn).clip(lower=0.0)
    after = float(work["ead_stressed"].sum())
    steps.append({
        "step": f"CCF {shock.describe()}",
        "detail": (f"The conversion factor moved from a weighted "
                   f"{float((current * undrawn).sum() / undrawn.sum()) * 100 if undrawn.sum() else 0:.1f}% "
                   f"to {float((moved * undrawn).sum() / undrawn.sum()) * 100 if undrawn.sum() else 0:.1f}%. "
                   f"EAD follows through drawn + CCF x undrawn, moving "
                   f"{(after / before - 1) * 100 if before else 0:+.2f}% — not "
                   "by the CCF's own percentage."),
        "affected": int((moved != current).sum()),
    })


def _apply_haircut(work: pd.DataFrame, shock: sc.Shock,
                   assumptions: sc.Assumptions,
                   steps: list[dict[str, Any]]) -> None:
    """Move the haircut on collateral, and let LGD follow.

    A haircut is applied to the collateral value, so a rise in the haircut is
    a fall in the covered share, which raises loss given default on exactly
    the secured part of the exposure and leaves the unsecured part alone.
    """
    if not assumptions.collateral_to_lgd or "collateral_market_value" not in work.columns:
        return
    exposure = work["ead_stressed"].replace(0, np.nan)
    collateral = pd.to_numeric(work["collateral_market_value"], errors="coerce").fillna(0.0)
    secured_share = (collateral / exposure).clip(0, 1).fillna(0.0)
    if shock.unit == sc.RELATIVE:
        change = secured_share * (shock.magnitude / 100.0)
    else:
        change = secured_share * (shock.magnitude / 100.0)
    before = float(work["lgd_stressed"].mean())
    work["lgd_stressed"] = (work["lgd_stressed"] + (change * 100.0)).clip(0.0, 95.0)
    steps.append({
        "step": f"Haircut {shock.describe()}",
        "detail": ("The haircut moved, so the covered share of each secured "
                   "exposure moved with it. LGD went from an average "
                   f"{before:.2f}% to {float(work['lgd_stressed'].mean()):.2f}%. "
                   "Unsecured exposure is untouched."),
        "affected": int((secured_share > 0).sum()),
    })


def _apply_stage(work: pd.DataFrame, shock: sc.Shock,
                 steps: list[dict[str, Any]]) -> None:
    """Move a share of one Stage into another, because somebody asked.

    This is a DIRECT migration — "move half the Stage 1 BBB borrowers to Stage
    2" — as distinct from a Stage change triggered by a PD move. Both exist:
    one is an assumption about staging, the other a consequence of a shock.

    Who moves is decided by PD, worst first for a deterioration and best first
    for a cure, rather than at random. A random half would make the same
    instruction produce a different answer every time it was run, and "the
    weakest names deteriorate first" is the assumption a credit officer would
    make if asked. It is stated in the step so nobody has to guess.
    """
    target = str(shock.target or "1->2")
    try:
        start, end = (int(x) for x in target.replace(">", "").split("-")[:2]) \
            if "-" in target else (int(target[0]), int(target[-1]))
    except (ValueError, IndexError):
        raise ValueError(
            f"'{shock.target}' is not a Stage movement this engine reads. "
            "Use a form like '1->2', '2->3', '2->1' or '3->2'.") from None
    if start not in (1, 2, 3) or end not in (1, 2, 3) or start == end:
        raise ValueError(
            f"Stage {start} to Stage {end} is not a movement this engine "
            "applies. Stages are 1, 2 and 3, and a movement needs two "
            "different ones.")

    pool = work.index[work["stage_stressed_direct"] == start] \
        if "stage_stressed_direct" in work.columns \
        else work.index[work["stage_baseline"] == start]
    if not len(pool):
        steps.append({"step": f"Stage {start} to Stage {end}",
                      "detail": f"No borrower is in Stage {start}, so nothing moved.",
                      "affected": 0})
        return

    share = float(shock.magnitude)
    if shock.unit in (sc.RELATIVE, sc.ABSOLUTE_PP):
        wanted = int(round(len(pool) * min(max(share, 0.0), 100.0) / 100.0))
    else:
        wanted = int(min(max(share, 0), len(pool)))

    worsening = end > start
    ranked = work.loc[pool, "pd_stressed"].sort_values(ascending=not worsening)
    chosen = ranked.index[:wanted]
    if "stage_stressed_direct" not in work.columns:
        work["stage_stressed_direct"] = work["stage_baseline"]
    work.loc[chosen, "stage_stressed_direct"] = end

    steps.append({
        "step": f"Stage {start} to Stage {end}",
        "detail": (f"{len(chosen):,} of {len(pool):,} Stage {start} borrowers "
                   f"moved to Stage {end} — "
                   f"{'the highest' if worsening else 'the lowest'}-PD names "
                   "first, so the same instruction always selects the same "
                   "borrowers. Their ECL is now measured on "
                   f"{'lifetime' if end >= 2 else 'twelve-month'} PD."),
        "affected": int(len(chosen)),
    })


def _observed_level(variable: Any) -> float | None:
    """The latest published level of a macro variable, where the book has one.

    Needed only to size a RELATIVE move of a variable quoted in points —
    "increase unemployment by 30%" is meaningless without knowing it is at 5%.
    Returns None rather than a guess when the book does not publish it, and the
    caller refuses instead of inventing a level.
    """
    if not getattr(variable, "column", ""):
        return None
    try:
        from backend.whatif import domain as wf_domain
        from backend.whatif import macro as mc

        return mc.levels(wf_domain.macro()).get(variable.key)
    except Exception:  # noqa: BLE001 - an unbuilt lake is not this function's job
        return None


def _apply_macro(work: pd.DataFrame, shock: sc.Shock,
                 steps: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    """Move a macro variable, and let PD and LGD follow its declared sensitivity.

    The governed ten (`backend.whatif.macro`) are tried first: those are the
    CreditProbe V1 variables the product configures, each with a declared PD
    multiplier and LGD change per adverse unit. The older eight-variable
    sensitivity matrix is still consulted for targets only it carries, so
    scenarios written against it keep working.

    Nothing here is fitted. The sensitivities are declared assumptions and the
    step says so, because a screen that showed "unemployment +1pp raises PD by
    12%" without saying where that came from would invite a committee to
    believe a coefficient nobody measured.
    """
    from backend.whatif import macro as mc

    governed = mc.variable(shock.target)
    if governed is not None:
        unit = {sc.RELATIVE: mc.RELATIVE, sc.ABSOLUTE_PP: mc.ABSOLUTE_PP,
                sc.BASIS_POINTS: mc.BASIS_POINTS}.get(shock.unit, mc.ABSOLUTE_PP)
        level = None
        if unit == mc.RELATIVE and governed.unit != "percent":
            level = _observed_level(governed)
        try:
            applied = mc.applied(governed.key, shock.magnitude, unit, level=level)
        except mc.MacroError as e:
            steps.append({"step": f"{governed.name} — not applied",
                          "detail": str(e), "affected": 0})
            return
        work["pd_stressed"] = mc.apply_pd(work["pd_stressed"], applied.pd_factor)
        if applied.lgd_delta_pp:
            work["lgd_stressed"] = mc.apply_lgd(work["lgd_stressed"],
                                                applied.lgd_delta_pp)
        rows.append(applied.to_dict())
        steps.append({
            "step": governed.name,
            "detail": (f"{applied.describe()}. This is a declared CreditProbe "
                       f"What-If sensitivity (v{mc.MACRO_VERSION}), not an "
                       "IFRS 9 coefficient and not an estimate fitted to this "
                       "book."),
            "affected": int(len(work)),
        })
        return

    _apply_macro_legacy(work, shock, steps, rows)


def _apply_macro_legacy(work: pd.DataFrame, shock: sc.Shock,
                 steps: list[dict[str, Any]],
                 rows: list[dict[str, Any]]) -> None:
    """A macro shock, through the versioned sensitivity matrix."""
    found = sv.variable(shock.target)
    if found is None:
        return
    if shock.unit == sc.BASIS_POINTS:
        size = shock.magnitude / abs(found.step) if found.unit == "basis points" else shock.magnitude
    else:
        size = shock.magnitude / found.step if found.step else shock.magnitude
    size = abs(size) if found.step < 0 else size
    steps_taken = float(size)

    sector = work["sector"].astype(str)
    multiplier = sector.map(lambda s: found.sector_pd_multipliers.get(s, 1.0))
    pd_uplift = found.pd_effect * steps_taken * multiplier
    work["pd_stressed"] = work["pd_stressed"] * (1.0 + pd_uplift)
    if found.lgd_effect_pp:
        work["lgd_stressed"] = (work["lgd_stressed"]
                                + found.lgd_effect_pp * steps_taken).clip(upper=95.0)
    for measure, effect in found.financial_effects.items():
        column = f"{measure}_stressed"
        if column in work.columns:
            work[column] = work[column] * (1.0 + effect * steps_taken)

    steps.append({
        "step": f"Macro shock — {found.name}",
        "detail": f"{shock.magnitude:+g} {found.unit} = {steps_taken:.2f} "
                  f"{found.step_label.replace('per ', '')} steps, applied "
                  f"through sensitivity matrix {sv.MATRIX_VERSION}. "
                  f"{found.basis}",
        "affected": len(work),
    })
    for name in sorted(sector.unique()):
        mask = sector == name
        if not mask.any():
            continue
        rows.append({
            "variable": found.name,
            "shock": f"{shock.magnitude:+g} {found.unit}",
            "scope": name,
            "sector_sensitivity": round(found.sector_pd_multipliers.get(name, 1.0), 2),
            "pd_effect_pct": round(float(pd_uplift[mask].mean()) * 100, 2),
            "lgd_effect_pp": round(found.lgd_effect_pp * steps_taken, 2),
            "borrowers": int(mask.sum()),
        })


# ------------------------------------------------------------------- the run


def run(scenario: sc.Scenario, *, period: str = "", source: Any = None,
        staging: Any = None) -> Result:
    """Run one scenario over the book, borrower by borrower.

    `staging` is the thread's staging criteria. Left as None it is the
    governed corporate policy, which is what produced the reported book, so an
    unmodified thread reproduces it exactly.
    """
    frame, settled = _read(period or scenario.period, source)
    work = select(frame, scenario.population)
    steps: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    if work.empty:
        raise ValueError(
            f"No borrowers match {scenario.population.describe()} in {settled}.")

    _numeric(work, ("pd_12m", "pd_lifetime", "lgd", "ead", "final_ecl",
                    "management_overlay", "current_dpd", "stage",
                    "collateral_market_value", "collateral_shortfall",
                    "undrawn_commitment", "pd_at_origination_pct",
                    *_FINANCIAL_COLUMNS))
    if "default_flag" in work.columns:
        work["default_flag"] = work["default_flag"].astype(bool)
    else:  # pragma: no cover - the snapshot always carries it
        work["default_flag"] = False
    if "pd_at_origination_pct" not in work.columns:
        work["pd_at_origination_pct"] = work["pd_12m"]
        warnings.append(
            "Origination PD was unavailable, so the relative SICR trigger "
            "could not be re-evaluated. Stage changes below come from the "
            "absolute PD and days-past-due triggers only.")

    steps.append({
        "step": "Baseline",
        "detail": f"{len(work):,} borrowers in {settled}: "
                  f"{scenario.population.describe()}. Every figure below is "
                  "the reported position.",
        "affected": len(work),
    })

    # ---- baseline, on the governed measurement basis
    work["stage_baseline"] = pd.to_numeric(work["stage"], errors="coerce").fillna(1).astype(int)
    measured_base = policy.measured_ecl(
        work["stage_baseline"], work["pd_12m"], work["lgd"], work["ead"])

    # ---- the stressed position starts as a copy of the baseline
    work["pd_stressed"] = work["pd_12m"]
    work["lgd_stressed"] = work["lgd"]
    work["ead_stressed"] = work["ead"]
    for measure in _FINANCIAL_COLUMNS:
        if measure in work.columns:
            work[f"{measure}_stressed"] = work[measure]

    # ---- apply every shock, in a fixed order so a scenario is reproducible
    order = (sc.RATING, sc.MACRO, sc.FINANCIAL, sc.STAGE, sc.PD, sc.LGD,
             sc.CCF, sc.COLLATERAL, sc.HAIRCUT, sc.EAD)
    for kind in order:
        for shock in scenario.shocks_of(kind):
            if kind == sc.RATING:
                _apply_rating(work, int(shock.magnitude), steps)
            elif kind == sc.MACRO:
                _apply_macro(work, shock, steps, rows)
            elif kind == sc.FINANCIAL:
                _apply_financial(work, shock, steps)
            elif kind == sc.PD:
                _apply_pd(work, shock, steps)
            elif kind == sc.LGD:
                _apply_lgd(work, shock, steps)
            elif kind == sc.COLLATERAL:
                _apply_collateral(work, shock, scenario.assumptions, steps)
            elif kind == sc.CCF:
                _apply_ccf(work, shock, steps)
            elif kind == sc.HAIRCUT:
                _apply_haircut(work, shock, scenario.assumptions, steps)
            elif kind == sc.STAGE:
                _apply_stage(work, shock, steps)
            elif kind == sc.EAD:
                _apply_ead(work, shock, steps)

    work["pd_stressed"] = work["pd_stressed"].clip(lower=0.0, upper=99.0)
    work["lgd_stressed"] = work["lgd_stressed"].clip(lower=0.0, upper=95.0)
    work["ead_stressed"] = work["ead_stressed"].clip(lower=0.0)

    # ---- re-stage against the STRESSED PD, using the thread's criteria
    #
    # The criteria default to the governed corporate policy, so a thread that
    # has changed nothing reproduces the reported book. A thread that has
    # edited them is running its own assumption, and says so on every result.
    work["pd_12m_baseline"] = work["pd_12m"]
    criteria = staging
    if criteria is None:
        stressed_stage = (
            policy.stage_of(work["pd_stressed"], work["pd_at_origination_pct"],
                            work["current_dpd"], work["default_flag"])
            if scenario.assumptions.reevaluate_sicr
            else work["stage_baseline"].to_numpy())
    else:
        # The criteria read `pd_12m`, and the thing being staged is the
        # STRESSED PD. Assigning over a copy rather than renaming, because a
        # rename would leave two columns called `pd_12m` and the rule would
        # read whichever came first.
        evaluated = work.copy()
        evaluated["pd_12m"] = work["pd_stressed"]
        stressed_stage = (criteria.stage(evaluated)
                          if scenario.assumptions.reevaluate_sicr
                          else work["stage_baseline"].to_numpy())

    if scenario.assumptions.rating_deterioration_sicr and "notches_moved" in work.columns:
        deteriorated = (work["notches_moved"]
                        >= scenario.assumptions.rating_sicr_notches).to_numpy()
        stressed_stage = np.where((stressed_stage == 1) & deteriorated, 2,
                                  stressed_stage)

    # A SHOCK never improves a Stage. Curing is a credit event and a
    # negotiation, not an arithmetic consequence of a PD move.
    stressed_stage = np.maximum(stressed_stage, work["stage_baseline"].to_numpy())

    # A Stage migration somebody ASKED for is a different thing: the person is
    # asserting the movement rather than deriving it, and the product supports
    # curing as well as deterioration because a book cures. So a direct
    # migration overrides the derived Stage in both directions.
    held = 0
    if "stage_stressed_direct" in work.columns:
        asked = pd.to_numeric(work["stage_stressed_direct"],
                              errors="coerce").fillna(0).astype(int).to_numpy()
        requested = np.where(asked > 0, asked, stressed_stage)
        # The default presumption is not a staging opinion. A borrower with a
        # recorded default, or 90+ days past due, stays in Stage 3 whatever
        # the instruction said, and the instruction is told how many.
        presumed = (work["default_flag"].to_numpy()
                    | (pd.to_numeric(work["current_dpd"], errors="coerce")
                       .fillna(0) >= policy.DEFAULT_DPD_DAYS).to_numpy())
        held = int(((requested < 3) & presumed).sum())
        stressed_stage = np.where(presumed, 3, requested)
        if held:
            warnings.append(
                f"{held:,} borrower(s) were asked to leave Stage 3 but carry a "
                "recorded default or 90+ days past due, so they stayed. The "
                "default presumption is not a staging assumption.")

    work["stage_stressed"] = stressed_stage
    moved = int((work["stage_stressed"] != work["stage_baseline"]).sum())
    steps.append({
        "step": "SICR re-evaluation",
        "detail": ("The governed SICR triggers were re-read against the "
                   f"stressed PD ({policy.POLICY_VERSION}): PD at least "
                   f"{policy.SICR_PD_RATIO:g}x origination and "
                   f"{policy.SICR_PD_ABSOLUTE:.2f}pp higher, PD at or above "
                   f"{policy.SICR_ABSOLUTE_PD:.0f}%, or "
                   f"{policy.SICR_DPD_DAYS}+ days past due."
                   if scenario.assumptions.reevaluate_sicr
                   else "Staging was held at the reported Stage."),
        "affected": moved,
    })

    # ---- re-measure, and carry onto the reported basis
    measured_stress = policy.measured_ecl(
        work["stage_stressed"], work["pd_stressed"],
        work["lgd_stressed"], work["ead_stressed"])
    ratio = np.where(measured_base > 0, measured_stress / np.where(
        measured_base > 0, measured_base, 1.0), 1.0)
    work["ecl_baseline"] = work["final_ecl"]
    work["ecl_stressed"] = work["final_ecl"] * ratio
    # A borrower with a reported ECL of zero cannot be scaled. Its stressed ECL
    # is the measured one, which is the only figure available and is honest.
    zero_base = work["final_ecl"] <= 0
    work.loc[zero_base, "ecl_stressed"] = measured_stress[zero_base.to_numpy()]
    work["ecl_increase"] = work["ecl_stressed"] - work["ecl_baseline"]
    work["ecl_increase_pct"] = np.where(
        work["ecl_baseline"] > 0,
        work["ecl_increase"] / work["ecl_baseline"].replace(0, np.nan) * 100.0, 0.0)
    steps.append({
        "step": "ECL re-measurement",
        "detail": ("Each borrower's ECL is re-measured on its stressed Stage's "
                   "own basis — 12-month for Stage 1, lifetime for Stages 2 "
                   "and 3 — and carried onto the reported figure by the ratio "
                   "of the two measurements, so the base column ties to the "
                   "book exactly."),
        "affected": int((work["ecl_increase"].abs() > 0).sum()),
    })

    work["primary_driver"] = _drivers(work, scenario)
    result = Result(scenario=scenario, period=settled,
                    borrowers=_present(work), steps=steps,
                    sensitivity_rows=rows, warnings=warnings,
                    frame=work.copy())
    result.summary = _summarise(work, scenario, settled)
    result.by_sector = _group(work, "sector")
    result.by_rating = _group(work, "internal_rating")
    result.by_stage = _group(work, "stage_baseline", label="Opening stage")
    return result


def _drivers(work: pd.DataFrame, scenario: sc.Scenario) -> pd.Series:
    """What moved this borrower's ECL most, per borrower."""
    stage_moved = work["stage_stressed"] > work["stage_baseline"]
    rating_moved = (work["notches_moved"] > 0 if "notches_moved" in work.columns
                    else pd.Series(False, index=work.index))
    pd_moved = work["pd_stressed"] > work["pd_12m"] * 1.001
    lgd_moved = work["lgd_stressed"] > work["lgd"] + 0.01
    ead_moved = work["ead_stressed"] > work["ead"] * 1.001
    return pd.Series(
        np.select(
            [stage_moved, rating_moved & pd_moved, pd_moved, lgd_moved, ead_moved],
            ["Stage 1 to Stage 2 — lifetime measurement",
             "Rating downgrade raising PD",
             "PD deterioration",
             "Higher loss given default",
             "Higher exposure at default"],
            default="No material change"),
        index=work.index)


PRESENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("borrower_id", "Borrower ID"),
    ("display_name", "Borrower"),
    ("sector", "Sector"),
    ("group_name", "Group"),
    ("ead", "Exposure (SAR)"),
    ("opening_rating", "Opening rating"),
    ("stressed_rating", "Stressed rating"),
    ("stage_baseline", "Opening stage"),
    ("stage_stressed", "Stressed stage"),
    ("pd_12m", "Opening 12m PD (%)"),
    ("pd_stressed", "Stressed 12m PD (%)"),
    ("lgd", "Opening LGD (%)"),
    ("lgd_stressed", "Stressed LGD (%)"),
    ("ead_stressed", "Stressed EAD (SAR)"),
    ("ecl_baseline", "Opening ECL (SAR)"),
    ("ecl_stressed", "Stressed ECL (SAR)"),
    ("ecl_increase", "ECL increase (SAR)"),
    ("ecl_increase_pct", "ECL increase (%)"),
    ("primary_driver", "Primary driver"),
)


def _present(work: pd.DataFrame) -> pd.DataFrame:
    out = work.copy()
    if "opening_rating" not in out.columns:
        out["opening_rating"] = out["internal_rating"]
        out["stressed_rating"] = out["internal_rating"]
    keep = [c for c, _ in PRESENT_COLUMNS if c in out.columns]
    table = out[keep].copy()
    for column in ("ead", "ead_stressed", "ecl_baseline", "ecl_stressed",
                   "ecl_increase"):
        if column in table.columns:
            table[column] = table[column].round(2)
    # Two decimal places on a percentage a person reads. The engine holds four
    # and the presentability gate rejects a raw float on the screen, which is
    # the right way round: precision is kept in the calculation and spent in
    # the presentation.
    for column in ("pd_12m", "pd_stressed", "lgd", "lgd_stressed",
                   "ecl_increase_pct"):
        if column in table.columns:
            table[column] = table[column].round(2)
    return table.sort_values("ecl_increase", ascending=False).reset_index(drop=True)


def _summarise(work: pd.DataFrame, scenario: sc.Scenario,
               period: str) -> dict[str, Any]:
    base_ecl = float(work["ecl_baseline"].sum())
    stressed_ecl = float(work["ecl_stressed"].sum())
    moved_2 = int(((work["stage_baseline"] == 1) & (work["stage_stressed"] == 2)).sum())
    moved_3 = int(((work["stage_baseline"] < 3) & (work["stage_stressed"] == 3)).sum())
    return {
        "scenario": scenario.name,
        "population": scenario.population.describe(),
        "borrowers": int(len(work)),
        "period": period,
        "currency": CURRENCY,
        "baseline_ead": round(float(work["ead"].sum()), 2),
        "stressed_ead": round(float(work["ead_stressed"].sum()), 2),
        "baseline_ecl": round(base_ecl, 2),
        "stressed_ecl": round(stressed_ecl, 2),
        "incremental_ecl": round(stressed_ecl - base_ecl, 2),
        "incremental_ecl_pct": round(
            (stressed_ecl - base_ecl) / base_ecl * 100, 2) if base_ecl else 0.0,
        "baseline_coverage_pct": round(
            base_ecl / float(work["ead"].sum()) * 100, 4) if work["ead"].sum() else 0.0,
        "stressed_coverage_pct": round(
            stressed_ecl / float(work["ead_stressed"].sum()) * 100, 4)
        if work["ead_stressed"].sum() else 0.0,
        "stage_2_migrations": moved_2,
        "stage_3_migrations": moved_3,
        "stage_2_baseline": int((work["stage_baseline"] == 2).sum()),
        "stage_2_stressed": int((work["stage_stressed"] == 2).sum()),
        "borrowers_with_higher_ecl": int((work["ecl_increase"] > 0).sum()),
        "material_borrowers": int((work["ecl_increase"] > 0).sum()),
        "downgraded": int(work["notches_moved"].gt(0).sum())
        if "notches_moved" in work.columns else 0,
        "collateral_shortfalls": int(
            work["collateral_shortfall_stressed"].gt(0).sum())
        if "collateral_shortfall_stressed" in work.columns
        else int(work.get("collateral_shortfall", pd.Series(dtype=float)).gt(0).sum()),
        "covenant_breaches": int(
            pd.to_numeric(work.get("covenants_breached", 0),
                          errors="coerce").fillna(0).gt(0).sum()),
    }


def _group(work: pd.DataFrame, column: str, *, label: str = "") -> pd.DataFrame:
    if column not in work.columns:
        return pd.DataFrame()
    grouped = work.groupby(column, dropna=False).agg(
        borrowers=("borrower_id", "count"),
        baseline_ead=("ead", "sum"),
        stressed_ead=("ead_stressed", "sum"),
        baseline_ecl=("ecl_baseline", "sum"),
        stressed_ecl=("ecl_stressed", "sum"),
        ecl_increase=("ecl_increase", "sum"),
    ).reset_index()
    grouped["ecl_increase_pct"] = np.where(
        grouped["baseline_ecl"] > 0,
        grouped["ecl_increase"] / grouped["baseline_ecl"] * 100.0, 0.0)
    grouped = grouped.rename(columns={column: label or column})
    return grouped.sort_values("ecl_increase", ascending=False).reset_index(drop=True)


def compare(results: list[Result]) -> pd.DataFrame:
    """Several scenarios beside each other, on the same population."""
    rows = []
    for found in results:
        summary = found.summary
        rows.append({
            "Scenario": found.scenario.name,
            "Severity": found.scenario.severity,
            "Borrowers": summary["borrowers"],
            "Baseline ECL (SAR)": summary["baseline_ecl"],
            "Stressed ECL (SAR)": summary["stressed_ecl"],
            "Incremental ECL (SAR)": summary["incremental_ecl"],
            "Incremental ECL (%)": summary["incremental_ecl_pct"],
            "Stage 2 migrations": summary["stage_2_migrations"],
            "Stressed coverage (%)": summary["stressed_coverage_pct"],
        })
    return pd.DataFrame(rows)


__all__ = ["BORROWER_SNAPSHOT", "CURRENCY", "FIELDS", "IFRS9_DATASET",
           "PRESENT_COLUMNS", "Result", "compare", "latest_period", "run",
           "select"]
