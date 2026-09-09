"""
The deterministic longitudinal generator behind the Cockpit demo. Brief §3, §4.1.

What makes this a credit MODEL rather than a table of random numbers
---------------------------------------------------------------------
Borrowers have histories. A borrower's revenue, EBITDA, working capital and
debt follow one trajectory across the eight quarters; the annual and interim
statements are AGGREGATED FROM that trajectory rather than drawn independently,
so the income statement, the balance sheet and the cash flow reconcile with
each other and the ratios are computed from those components rather than being
separate random draws. The rating comes out of the demo rating model applied to
those ratios. The stage comes out of the demo SICR policy applied to that
rating and the days past due. The scenario PD comes out of the macro transform
applied to that rating's PD. The ECL comes out of the governed calculator
applied to those parameters. Nothing in that chain is written down twice.

Determinism
-----------
Every random draw is taken from a `numpy.random.Generator` seeded from the
master seed and the entity's own id, so a borrower's history does not change
when the population size does, and regenerating produces byte-identical
Parquet. `DATA_VERSION` changes whenever the shape or content changes.

No information leaks backwards
------------------------------
A quarterly snapshot carries the latest statement whose AVAILABILITY date is on
or before the reporting date, and the latest macro forecast whose ISSUE date is
on or before it. Business effective dates and knowledge dates are separate
fields throughout, and the integrity gates check the rule rather than trusting
this docstring.

Everything generated here is synthetic and says so on every row.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from backend.cockpit_v2 import (DATA_VERSION, MODEL_VERSION, NOT_CLIENT_DATA,
                                ORIGIN, POLICY_VERSION)
from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import ecl as ecl_mod
from backend.cockpit_v2 import policy
from backend.cockpit_v2 import stories as stories_mod

logger = logging.getLogger(__name__)

MASTER_SEED = 20260908

#: Reporting currency for the demo book. Figures are in crore.
REPORTING_CURRENCY = "INR"
AMOUNT_UNIT = "INR crore"

SECTORS: tuple[str, ...] = (
    "Construction", "Manufacturing", "Retail Trade",
    "Transport and Logistics", "Hospitality", "Healthcare",
    "Information Technology", "Real Estate",
)

SUBSECTORS: dict[str, tuple[str, ...]] = {
    "Construction": ("Civil engineering", "Building contracting", "Specialist trades"),
    "Manufacturing": ("Chemicals", "Auto components", "Textiles", "Capital goods"),
    "Retail Trade": ("Food retail", "Apparel", "Consumer durables"),
    "Transport and Logistics": ("Road freight", "Warehousing", "Shipping services"),
    "Hospitality": ("Hotels", "Restaurants", "Leisure"),
    "Healthcare": ("Hospitals", "Diagnostics", "Pharmaceutical distribution"),
    "Information Technology": ("Software services", "Data centres", "Hardware"),
    "Real Estate": ("Commercial leasing", "Residential development", "Industrial parks"),
}

GEOGRAPHIES: tuple[str, ...] = ("West", "North", "South", "East")
SEGMENTS: tuple[str, ...] = ("Large Corporate", "Mid Corporate", "SME")
PRODUCTS: tuple[str, ...] = tuple(policy.CCF)
BUSINESS_UNITS: tuple[str, ...] = ("Corporate Banking", "Commercial Banking",
                                   "Structured Finance")

#: Fictional name parts. Combined into names that are obviously invented.
_NAME_HEAD = ("Aravali", "Bhavani", "Chandrika", "Deccan", "Eastwind",
              "Falcon", "Girnar", "Harbour", "Indus", "Jalpari", "Konkan",
              "Lumen", "Meridian", "Nilgiri", "Orbit", "Pallava", "Quartz",
              "Rohini", "Sahyadri", "Tarangini", "Ujjain", "Vindhya",
              "Westgate", "Xylem", "Yamuna", "Zenith")
_NAME_TAIL = ("Industries", "Enterprises", "Infratech", "Logistics", "Retail",
              "Healthcare", "Systems", "Estates", "Ventures", "Works",
              "Traders", "Projects", "Holdings", "Fabricators", "Foods")


def _rng(*parts: Any) -> np.random.Generator:
    """A generator seeded from the master seed and a stable key.

    Hashing the key rather than using a counter is what makes a borrower's
    history independent of how many borrowers exist, so the pilot's twelve and
    the full demo's five hundred agree on the twelve they share.
    """
    key = "|".join(str(p) for p in parts).encode()
    digest = hashlib.blake2b(key, digest_size=8, person=b"ckpt-v2").digest()
    return np.random.default_rng((MASTER_SEED + int.from_bytes(digest, "big"))
                                 % (2 ** 63))


# ------------------------------------------------------------------ entities


@dataclass
class Borrower:
    borrower_id: str
    borrower_name: str
    group_id: str
    group_name: str
    sector: str
    subsector: str
    geography: str
    segment: str
    borrower_type: str
    business_unit: str
    relationship_manager: str
    story_id: str
    #: Quarterly underlying trajectory, index-aligned to the quarters generated.
    scale: float = 1.0


@dataclass
class Facility:
    facility_id: str
    borrower_id: str
    product: str
    origination_date: date
    maturity_date: date
    limit: float
    contractual_rate: float
    effective_rate: float
    currency: str
    #: Quarter index at which the facility first appears, and last appears.
    enters_at: int = 0
    exits_at: int | None = None
    written_off_at: int | None = None


@dataclass
class CollateralAsset:
    collateral_id: str
    borrower_id: str
    asset_type: str
    base_value: float
    valuation_quarter_offset: int
    lien_rank: int
    legal_status: str
    #: Facilities the asset secures, in allocation priority order.
    facilities: list[str] = field(default_factory=list)


# ------------------------------------------------------------ the population


def _pick(rng: np.random.Generator, options: Sequence[Any]) -> Any:
    return options[int(rng.integers(0, len(options)))]


def build_population(*, borrowers: int, facilities_target: int,
                     quarters: Sequence[str]) -> tuple[
        list[Borrower], list[Facility], list[CollateralAsset], dict[str, str]]:
    """Borrowers, their facilities and their collateral, plus the story map."""
    story_ids = [s.story_id for s in stories_mod.STORIES]
    people = ["R. Iyer", "S. Mehta", "A. Banerjee", "K. Nair", "P. Sharma",
              "M. D'Souza", "T. Rao", "N. Kulkarni"]

    out: list[Borrower] = []
    assignments: dict[str, str] = {}

    # The first borrowers carry the named stories, one each, so the pilot's
    # twelve always contain the mechanics the checkpoint needs. The rest are
    # drawn from the same distributions but carry no story.
    for i in range(borrowers):
        bid = f"CKB-{i + 1:04d}"
        rng = _rng("borrower", bid)
        story = story_ids[i] if i < len(story_ids) else ""
        if story:
            assignments[bid] = story

        # A story that is about a sector needs that sector.
        if story == "STORY_COLLATERAL_WEAKENING":
            sector = "Real Estate"
        elif story in ("STORY_OFFSETTING_SEGMENTS", "STORY_BREACH_WITH_WAIVER"):
            sector = "Construction"
        elif story == "STORY_OFFSETTING_SEGMENTS_MIRROR":
            sector = "Information Technology"
        else:
            sector = _pick(rng, SECTORS)

        head = _NAME_HEAD[int(rng.integers(0, len(_NAME_HEAD)))]
        tail = _NAME_TAIL[int(rng.integers(0, len(_NAME_TAIL)))]
        segment = ("Large Corporate" if story == "STORY_GROUP_CONCENTRATION"
                   else _pick(rng, SEGMENTS))
        # A handful of borrowers sit in one connected group, which is what
        # makes "which groups dominate" a real question rather than a formality.
        group_index = 1 if story == "STORY_GROUP_CONCENTRATION" or (i % 37 == 0) else (i // 7) + 2
        out.append(Borrower(
            borrower_id=bid,
            borrower_name=f"{head} {tail} {i + 1:04d} (synthetic)",
            group_id=f"CKG-{group_index:03d}",
            group_name=f"{_NAME_HEAD[group_index % len(_NAME_HEAD)]} Group "
                       f"{group_index:03d} (synthetic)",
            sector=sector,
            subsector=_pick(rng, SUBSECTORS[sector]),
            geography=_pick(rng, GEOGRAPHIES),
            segment=segment,
            borrower_type="Corporate" if segment != "SME" else "SME",
            business_unit=_pick(rng, BUSINESS_UNITS),
            relationship_manager=_pick(rng, people),
            story_id=story,
            scale=float(np.exp(rng.normal(0.0, 0.55))) * (
                6.0 if segment == "Large Corporate"
                else 2.2 if segment == "Mid Corporate" else 0.8),
        ))

    facs: list[Facility] = []
    per_borrower = max(1, round(facilities_target / max(1, borrowers)))
    n_quarters = len(quarters)
    for b in out:
        rng = _rng("facilities", b.borrower_id)
        count = per_borrower
        if b.story_id == "STORY_SHARED_COLLATERAL":
            count = max(count, 3)
        elif b.story_id in ("STORY_NEW_LENDING", "STORY_REPAYMENT"):
            count = max(count, 2)
        elif count > 1 and rng.random() < 0.35:
            count -= 1
        for j in range(count):
            fid = f"{b.borrower_id}-F{j + 1}"
            frng = _rng("facility", fid)
            product = _pick(frng, PRODUCTS)
            origination = (cal.reporting_date(quarters[0])
                           - timedelta(days=int(frng.integers(200, 2600))))
            term_days = int(frng.integers(500, 3200))
            maturity = cal.reporting_date(quarters[-1]) + timedelta(
                days=max(120, term_days))
            rate = float(0.075 + frng.normal(0.0, 0.014))
            enters = 0
            exits = None
            written = None
            # Stories that need a population change get one, deterministically,
            # on their last facility so the borrower does not vanish entirely.
            if j == count - 1 and n_quarters > 1:
                if b.story_id == "STORY_NEW_LENDING":
                    enters = n_quarters - 1
                elif b.story_id == "STORY_REPAYMENT":
                    exits = n_quarters - 2
                elif b.story_id == "STORY_WRITE_OFF":
                    written = n_quarters - 1
            facs.append(Facility(
                facility_id=fid, borrower_id=b.borrower_id, product=product,
                origination_date=origination, maturity_date=maturity,
                limit=float(max(3.0, b.scale * 22.0 * np.exp(frng.normal(0, 0.4)))),
                contractual_rate=max(0.045, rate),
                effective_rate=max(0.045, rate + 0.004),
                currency=REPORTING_CURRENCY,
                enters_at=enters, exits_at=exits, written_off_at=written))

    assets: list[CollateralAsset] = []
    by_borrower: dict[str, list[Facility]] = {}
    for f in facs:
        by_borrower.setdefault(f.borrower_id, []).append(f)

    for b in out:
        rng = _rng("collateral", b.borrower_id)
        mine = by_borrower.get(b.borrower_id, [])
        if not mine:
            continue
        n_assets = 1 if rng.random() < 0.45 else 2
        if b.story_id == "STORY_SHARED_COLLATERAL":
            n_assets = 1
        elif b.story_id == "STORY_COLLATERAL_WEAKENING":
            n_assets = 2
        for k in range(n_assets):
            cid = f"{b.borrower_id}-C{k + 1}"
            crng = _rng("asset", cid)
            asset_type = _pick(crng, tuple(policy.COLLATERAL_POLICY))
            if b.story_id in ("STORY_COLLATERAL_WEAKENING", "STORY_SHARED_COLLATERAL"):
                asset_type = "Commercial property"
            secured = ([f.facility_id for f in mine]
                       if b.story_id == "STORY_SHARED_COLLATERAL"
                       else [mine[k % len(mine)].facility_id])
            total_limit = sum(f.limit for f in mine
                              if f.facility_id in secured)
            assets.append(CollateralAsset(
                collateral_id=cid, borrower_id=b.borrower_id,
                asset_type=asset_type,
                base_value=float(total_limit
                                 * (0.45 + 0.75 * crng.random())),
                valuation_quarter_offset=int(crng.integers(0, 7)),
                lien_rank=1 if k == 0 else 2,
                legal_status=("Perfected first charge" if k == 0
                              else "Perfected second charge"),
                facilities=secured))

    return out, facs, assets, assignments


# ------------------------------------------------------------------- macro


#: Vintages generated BEFORE the first published quarter. A forecast issued 25
#: days after a quarter ends is not knowable at that quarter end, so the
#: vintage a snapshot actually reads is the previous one. Without this warm-up
#: the earliest published quarter would have no usable vintage at all and every
#: scenario PD would silently collapse back to the rating-linked base — which
#: is exactly what the first pilot build did before this was added.
MACRO_WARMUP_VINTAGES = 4


def macro_paths(quarters: Sequence[str]) -> pd.DataFrame:
    """Actual and forecast macro paths by geography, vintage and scenario.

    One row per geography x predictor x forecast vintage x scenario x forecast
    period. The vintage is the quarter the forecast was ISSUED; the forecast
    period is the quarter it describes. A snapshot may only read a vintage
    issued on or before its own reporting date, which is what question A8.39 —
    "do not use data published after the quarter end" — is asking about.
    """
    first = cal.parse(quarters[0])
    warmup = [first.shift(-n).label
              for n in range(MACRO_WARMUP_VINTAGES, 0, -1)]
    span = [*warmup, *quarters]
    #: Long-run level and volatility per predictor. Demonstration assumptions.
    shape = {
        "real_gdp_growth": (6.4, 0.55), "inflation": (5.1, 0.6),
        "unemployment": (7.2, 0.35), "policy_rate": (6.3, 0.4),
        "government_bond_yield": (7.0, 0.35),
        "exchange_rate_move": (-1.2, 2.4),
        "commercial_property_prices": (3.5, 3.2),
        "oil_price_move": (1.5, 8.0), "industrial_production": (4.8, 1.3),
        "real_household_income": (3.6, 0.9),
    }
    #: How each scenario shifts a predictor, in standard deviations.
    tilt = {"base": 0.0, "upturn": 0.9, "downturn": -1.35}
    #: Predictors where "up" is bad, so the tilt has to flip.
    inverted = {"unemployment", "policy_rate", "government_bond_yield",
                "inflation"}

    rows: list[dict[str, Any]] = []
    horizon = 12  # quarters of forecast beyond each vintage
    for geo in GEOGRAPHIES:
        for predictor, (level, sd) in shape.items():
            grng = _rng("macro", geo, predictor)
            # One underlying actual path, shared by every vintage, so two
            # vintages agree about the past and differ only about the future.
            actual = {}
            value = level + grng.normal(0.0, sd * 0.6)
            for q in span:
                value = 0.72 * value + 0.28 * level + grng.normal(0.0, sd * 0.5)
                actual[q] = value

            for vintage in span:
                v = cal.parse(vintage)
                issue = v.end_date + timedelta(days=25)
                for step in range(-1, horizon):
                    fq = v.shift(step)
                    is_actual = step < 0
                    label = fq.label
                    for scenario in policy.SCENARIO_IDS:
                        if is_actual:
                            val = actual.get(label, level)
                            if label not in actual:
                                continue
                        else:
                            base = actual.get(vintage, level)
                            pull = min(1.0, (step + 1) / 8.0)
                            val = base * (1 - pull) + level * pull
                            direction = -1.0 if predictor in inverted else 1.0
                            val += direction * tilt[scenario] * sd * (
                                0.5 + 0.5 * pull)
                            val += grng.normal(0.0, sd * 0.08)
                        rows.append({
                            "geography": geo, "predictor": predictor,
                            "forecast_vintage": vintage,
                            "forecast_issue_date": issue.isoformat(),
                            "forecast_period": label,
                            "forecast_period_date": fq.end_date.isoformat(),
                            "scenario_id": ("actual" if is_actual else scenario),
                            "is_actual": bool(is_actual),
                            "value": round(float(val), 4),
                            "unit": next(m["unit"] for m in policy.MACRO_PREDICTORS
                                         if m["predictor"] == predictor),
                            "long_run_level": level,
                            "standard_deviation": sd,
                            "model_version": policy.MACRO_MODEL_ID,
                            "policy_version": POLICY_VERSION,
                            "data_version": DATA_VERSION,
                            "origin": ORIGIN, "is_synthetic": True,
                        })
                        if is_actual:
                            break  # an actual has no scenario variants
    return pd.DataFrame(rows)


def _standardised(macro: pd.DataFrame, *, geography: str, quarter: str,
                  scenario: str) -> dict[str, float]:
    """Standardised, lag-applied predictor values usable AT `quarter`.

    The vintage is the latest issued on or before the reporting date, which for
    a quarter-end snapshot is the previous quarter's vintage: this quarter's
    own forecast is issued 25 days after the quarter ends and is therefore not
    knowable at it. That is the leak guard, applied rather than described.
    """
    as_at = cal.reporting_date(quarter)
    usable = macro[(macro["geography"] == geography)
                   & (pd.to_datetime(macro["forecast_issue_date"]).dt.date <= as_at)]
    if usable.empty:
        return {}
    vintage = sorted(usable["forecast_vintage"].unique())[-1]
    out: dict[str, float] = {}
    for sensitivity in policy.active_sensitivities():
        lagged = cal.parse(quarter).shift(-int(sensitivity.lag_quarters)).label
        rows = usable[(usable["predictor"] == sensitivity.predictor)
                      & (usable["forecast_vintage"] == vintage)
                      & (usable["forecast_period"] == lagged)
                      & (usable["scenario_id"].isin([scenario, "actual"]))]
        if rows.empty:
            continue
        # Prefer the scenario path; fall back to the actual where the lagged
        # period is already history.
        pick = rows[rows["scenario_id"] == scenario]
        if pick.empty:
            pick = rows
        row = pick.iloc[0]
        sd = float(row["standard_deviation"]) or 1.0
        out[sensitivity.predictor] = float(
            (float(row["value"]) - float(row["long_run_level"])) / sd)
    return out


# ------------------------------------------------- borrower financial history


def _trajectory(borrower: Borrower, quarters: Sequence[str]) -> pd.DataFrame:
    """The quarterly underlying trajectory every statement is aggregated from.

    Generated once per borrower and then SUMMED into annual and interim
    statements, which is what makes the statements reconcile with each other
    instead of being three independent draws.
    """
    rng = _rng("trajectory", borrower.borrower_id)
    story = stories_mod.STORY_BY_ID.get(borrower.story_id)
    knobs = story.knobs if story else {}
    ebitda_growth = float(knobs.get("ebitda_growth", rng.normal(0.012, 0.035)))

    revenue = borrower.scale * 60.0 * float(np.exp(rng.normal(0.0, 0.25)))
    margin = float(np.clip(rng.normal(0.155, 0.05), 0.02, 0.34))
    # Sector shifts the margin so a sector comparison is not noise.
    margin *= {"Information Technology": 1.35, "Healthcare": 1.2,
               "Real Estate": 1.25, "Retail Trade": 0.72,
               "Construction": 0.85, "Transport and Logistics": 0.9,
               "Hospitality": 1.05, "Manufacturing": 1.0}[borrower.sector]
    margin = float(np.clip(margin, 0.02, 0.42))

    total_debt = revenue * float(np.clip(rng.normal(0.75, 0.28), 0.15, 2.1))
    fixed_assets = revenue * float(np.clip(rng.normal(0.85, 0.3), 0.2, 2.4))

    rows: list[dict[str, Any]] = []
    for i, q in enumerate(quarters):
        drift = (1.0 + ebitda_growth) ** i
        seasonal = 1.0 + 0.05 * np.sin((cal.parse(q).quarter - 1) * np.pi / 2)
        rev = revenue * drift * seasonal * (1.0 + rng.normal(0.0, 0.018))
        m = float(np.clip(margin * (1.0 + ebitda_growth * i * 0.55), 0.005, 0.45))
        ebitda = rev * m

        cost_of_sales = rev * float(np.clip(rng.normal(0.66, 0.05), 0.35, 0.88))
        gross_profit = rev - cost_of_sales
        operating_expenses = max(0.0, gross_profit - ebitda)
        depreciation = fixed_assets * 0.028
        ebit = ebitda - depreciation
        debt = total_debt * (1.0 + 0.25 * ebitda_growth * i)
        interest_expense = debt * 0.021
        tax = max(0.0, (ebit - interest_expense) * 0.25)
        net_profit = ebit - interest_expense - tax

        receivables = rev * float(np.clip(rng.normal(0.58, 0.14), 0.12, 1.3))
        inventory = cost_of_sales * float(np.clip(rng.normal(0.42, 0.16), 0.02, 1.2))
        payables = cost_of_sales * float(np.clip(rng.normal(0.38, 0.12), 0.05, 1.0))
        cash = rev * float(np.clip(rng.normal(0.12, 0.07), 0.005, 0.6))
        other_current_assets = rev * 0.06
        working_capital_change = (
            0.0 if i == 0 else
            (receivables + inventory - payables)
            - (rows[-1]["receivables"] + rows[-1]["inventory"]
               - rows[-1]["payables"]))

        capex = rev * float(np.clip(rng.normal(0.055, 0.025), 0.0, 0.2))
        operating_cash_flow = ebitda - tax - working_capital_change
        scheduled_principal = debt * 0.035
        cash_interest = interest_expense
        cash_available_for_debt_service = operating_cash_flow
        free_cash_flow = (operating_cash_flow - capex - cash_interest
                          - scheduled_principal)

        short_term_debt = debt * 0.38
        long_term_debt = debt - short_term_debt
        other_liabilities = rev * 0.07
        current_liabilities = payables + short_term_debt + rev * 0.05
        total_current_assets = (cash + receivables + inventory
                                + other_current_assets)
        other_non_current_assets = rev * 0.09
        total_assets = (total_current_assets + fixed_assets
                        + other_non_current_assets)
        total_liabilities = current_liabilities + long_term_debt + other_liabilities
        # Equity is the residual. That is what makes the balance sheet balance,
        # and it is stated rather than achieved by a fudge column.
        equity = total_assets - total_liabilities

        rows.append({
            "period": q, "period_end": cal.iso(q),
            "revenue": rev, "cost_of_sales": cost_of_sales,
            "gross_profit": gross_profit,
            "operating_expenses": operating_expenses, "ebitda": ebitda,
            "depreciation_amortisation": depreciation, "ebit": ebit,
            "interest_expense": interest_expense, "tax_expense": tax,
            "net_profit": net_profit,
            "cash": cash, "receivables": receivables, "inventory": inventory,
            "other_current_assets": other_current_assets,
            "total_current_assets": total_current_assets,
            "fixed_assets": fixed_assets,
            "other_non_current_assets": other_non_current_assets,
            "total_assets": total_assets,
            "payables": payables,
            "current_liabilities": current_liabilities,
            "short_term_debt": short_term_debt,
            "long_term_debt": long_term_debt,
            "other_liabilities": other_liabilities,
            "total_liabilities": total_liabilities,
            "total_equity": equity, "total_debt": debt,
            "operating_cash_flow": operating_cash_flow,
            "capital_expenditure": capex,
            "cash_available_for_debt_service": cash_available_for_debt_service,
            "scheduled_principal": scheduled_principal,
            "cash_interest": cash_interest,
            "free_cash_flow": free_cash_flow,
            "working_capital_change": working_capital_change,
        })
    return pd.DataFrame(rows)


#: Flow items are summed over the statement period; stock items are taken at
#: its close. Keeping the two lists explicit is what stops a balance sheet
#: being added up four times.
_FLOW = ("revenue", "cost_of_sales", "gross_profit", "operating_expenses",
         "ebitda", "depreciation_amortisation", "ebit", "interest_expense",
         "tax_expense", "net_profit", "operating_cash_flow",
         "capital_expenditure", "cash_available_for_debt_service",
         "scheduled_principal", "cash_interest", "free_cash_flow",
         "working_capital_change")
_STOCK = ("cash", "receivables", "inventory", "other_current_assets",
          "total_current_assets", "fixed_assets", "other_non_current_assets",
          "total_assets", "payables", "current_liabilities",
          "short_term_debt", "long_term_debt", "other_liabilities",
          "total_liabilities", "total_equity", "total_debt")


def _statements(borrower: Borrower, trajectory: pd.DataFrame,
                quarters: Sequence[str]) -> list[dict[str, Any]]:
    """Annual and interim statements, aggregated from the trajectory.

    Brief §3.3: a quarterly snapshot carries the latest available annual or
    interim statement. Fresh quarterly reporting is NOT fabricated to fill
    cells, so a borrower whose statements are stale simply has stale ones and
    the ratios computed from them are marked with their age.
    """
    story = stories_mod.STORY_BY_ID.get(borrower.story_id)
    if story and story.knobs.get("suppress_statements"):
        # One genuinely stale borrower: only the earliest statement exists.
        windows = [(quarters[:2], "INTERIM", False)]
    else:
        windows = []
        for start in range(0, len(quarters) - 1, 4):
            block = quarters[start:start + 4]
            if len(block) == 4:
                windows.append((block, "ANNUAL", True))
        for start in range(0, len(quarters) - 1, 2):
            block = quarters[start:start + 2]
            if len(block) == 2:
                windows.append((block, "INTERIM", False))

    out: list[dict[str, Any]] = []
    for block, kind, audited in windows:
        rows = trajectory[trajectory["period"].isin(block)]
        if rows.empty:
            continue
        last = rows.iloc[-1]
        record: dict[str, Any] = {
            "statement_id": f"{borrower.borrower_id}-{kind}-{block[-1]}",
            "borrower_id": borrower.borrower_id,
            "statement_type": kind,
            "statement_scope": "CONSOLIDATED",
            "statement_start": cal.parse(block[0]).start_date.isoformat(),
            "statement_end": cal.iso(block[-1]),
            "months_covered": len(block) * 3,
            "audited": bool(audited),
            "audit_status": "AUDITED" if audited else "MANAGEMENT",
            "availability_date": cal.available_by(
                cal.reporting_date(block[-1]), audited=audited).isoformat(),
            "currency": REPORTING_CURRENCY, "units": AMOUNT_UNIT,
            "source_system": "COCKPIT_DEMO_SPREADING",
            "statement_version": 1,
        }
        for name in _FLOW:
            record[name] = float(rows[name].sum())
        for name in _STOCK:
            record[name] = float(last[name])
        out.append(record)
    return out


def _annualise(record: dict[str, Any]) -> dict[str, float]:
    """Flow items on a twelve-month basis, so ratios compare like with like."""
    months = float(record.get("months_covered") or 12.0)
    factor = 12.0 / months if months else 1.0
    return {name: float(record[name]) * factor for name in _FLOW}


def _ratios(record: dict[str, Any]) -> dict[str, float | None]:
    """Financial ratios from the statement's own components.

    Every ratio is derived from fields that are also published, so a reader can
    reconstruct it. Zero and negative denominators return None — marked not
    available — rather than infinity or a silently flipped sign.
    """
    annual = _annualise(record)
    ebitda = annual["ebitda"]
    ebit = annual["ebit"]
    interest = annual["interest_expense"]
    cfads = annual["cash_available_for_debt_service"]
    debt_service = annual["scheduled_principal"] + annual["cash_interest"]
    revenue = annual["revenue"]

    debt = float(record["total_debt"])
    cash = float(record["cash"])
    equity = float(record["total_equity"])
    current_assets = float(record["total_current_assets"])
    current_liabilities = float(record["current_liabilities"])
    inventory = float(record["inventory"])

    def safe(numerator: float, denominator: float,
             *, positive_denominator: bool = True) -> float | None:
        if denominator == 0:
            return None
        if positive_denominator and denominator < 0:
            return None
        return numerator / denominator

    return {
        "dscr": safe(cfads, debt_service),
        "interest_coverage": safe(ebit, interest),
        "current_ratio": safe(current_assets, current_liabilities),
        "quick_ratio": safe(current_assets - inventory, current_liabilities),
        # A negative EBITDA makes a leverage multiple meaningless rather than
        # very negative, so it is reported as not available and flagged.
        "gross_debt_to_ebitda": safe(debt, ebitda),
        "net_debt_to_ebitda": safe(debt - cash, ebitda),
        "debt_to_equity": safe(debt, equity),
        "gross_margin": safe(annual["gross_profit"], revenue),
        "ebitda_margin": safe(ebitda, revenue),
        "net_margin": safe(annual["net_profit"], revenue),
        "return_on_equity": safe(annual["net_profit"], equity),
        "receivable_days": safe(float(record["receivables"]) * 365.0, revenue),
        "inventory_days": safe(inventory * 365.0, annual["cost_of_sales"]),
        "payable_days": safe(float(record["payables"]) * 365.0,
                             annual["cost_of_sales"]),
    }


def _ratio_notes(record: dict[str, Any],
                 ratios: dict[str, float | None]) -> list[str]:
    notes: list[str] = []
    if _annualise(record)["ebitda"] <= 0:
        notes.append(
            "EBITDA is zero or negative, so the leverage multiples are not "
            "meaningful and are reported as not available rather than as a "
            "negative multiple.")
    if float(record["total_equity"]) <= 0:
        notes.append(
            "Equity is zero or negative, so gearing and return on equity are "
            "not meaningful and are reported as not available.")
    return notes


__all__ = ["AMOUNT_UNIT", "Borrower", "CollateralAsset", "Facility",
           "GEOGRAPHIES", "MASTER_SEED", "PRODUCTS", "REPORTING_CURRENCY",
           "SECTORS", "SEGMENTS", "SUBSECTORS", "build_population",
           "macro_paths"]


# ------------------------------------------------------- collateral at a date


def _valuation(asset: CollateralAsset, quarters: Sequence[str],
               index: int) -> dict[str, Any]:
    """One asset's valuation as at a quarter, with the valuation's own age.

    An asset is revalued periodically, not every quarter, so valuation age is a
    real property of the book rather than always zero — which is what makes
    "separate collateral price deterioration from an old valuation" (question
    A5.25) a question with an answer.
    """
    borrower_story = asset.collateral_id
    rng = _rng("valuation", asset.collateral_id)
    quarter = quarters[index]
    # Revalued every third quarter, offset per asset.
    since = (index + asset.valuation_quarter_offset) % 3
    valued_index = max(0, index - since)
    valued_quarter = quarters[valued_index]

    drift = 1.0
    for step in range(valued_index + 1):
        drift *= 1.0 + float(rng.normal(0.006, 0.02))
    value = asset.base_value * drift

    valuation_date = cal.reporting_date(valued_quarter)
    as_at = cal.reporting_date(quarter)
    return {
        "value": float(value),
        "valuation_date": valuation_date.isoformat(),
        "valuation_age_days": int((as_at - valuation_date).days),
        "valuation_version": valued_index + 1,
        "valued_quarter": valued_quarter,
    }


def _collateral_rows(assets: Sequence[CollateralAsset],
                     facilities_by_id: dict[str, Facility],
                     exposures: dict[str, float],
                     quarters: Sequence[str], index: int,
                     story_by_borrower: dict[str, str]) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, float]]]:
    """Asset valuations, facility allocations, and per-facility coverage.

    Allocation rule, enforced rather than assumed: an asset's RECOGNISED amount
    (valuation less its policy haircut) is allocated across the facilities it
    secures in proportion to their exposure, and the allocations sum to at most
    the recognised amount. A property securing three facilities is therefore
    counted once, and the integrity gates assert it.
    """
    quarter = quarters[index]
    as_at = cal.iso(quarter)
    asset_rows: list[dict[str, Any]] = []
    allocation_rows: list[dict[str, Any]] = []
    coverage: dict[str, dict[str, float]] = {}

    for asset in assets:
        story = story_by_borrower.get(asset.borrower_id, "")
        valuation = _valuation(asset, quarters, index)
        value = valuation["value"]
        knobs = stories_mod.STORY_BY_ID.get(story).knobs if story else {}
        shock = float(knobs.get("collateral_shock", 0.0))
        if shock and index >= len(quarters) - 1:
            # The shock lands as ONE step in the final generated quarter rather
            # than compounding across the whole history. Compounding it wiped
            # the security out entirely several quarters before the pilot
            # window, so the very movement the story exists to demonstrate had
            # already finished happening before the two dates being compared.
            value *= (1.0 + shock)

        rules = policy.COLLATERAL_POLICY[asset.asset_type]
        haircut = float(rules["haircut"])
        recognised = value * (1.0 - haircut)
        stale = valuation["valuation_age_days"] > policy.STALE_VALUATION_DAYS
        if stale:
            # A stale valuation is not trusted at face value; the policy adds a
            # further haircut and the row says why.
            recognised *= 0.85

        live = [f for f in asset.facilities
                if f in facilities_by_id and exposures.get(f, 0.0) > 0]
        total_exposure = sum(exposures.get(f, 0.0) for f in live)

        asset_rows.append({
            "collateral_id": asset.collateral_id,
            "borrower_id": asset.borrower_id,
            "reporting_date": as_at, "period": quarter,
            "asset_type": asset.asset_type,
            "market_value": round(value, 6),
            "valuation_date": valuation["valuation_date"],
            "valuation_version": valuation["valuation_version"],
            "valuation_age_days": valuation["valuation_age_days"],
            "valuation_is_stale": bool(stale),
            "stale_valuation_threshold_days": policy.STALE_VALUATION_DAYS,
            "currency": REPORTING_CURRENCY, "fx_rate_to_reporting": 1.0,
            "eligible": True,
            "haircut": haircut,
            "recognised_value": round(recognised, 6),
            "lien_rank": asset.lien_rank,
            "legal_status": asset.legal_status,
            "facilities_sharing_asset": len(asset.facilities),
            "expected_realisation_cost_rate": round(
                float(policy.SECURED_LGD.get("Mid Corporate", 0.22)), 4),
            "expected_recovery_lag_years": float(rules["recovery_lag_years"]),
            "enforceability_note": (
                "Legal status is recorded as a status, not as a guarantee. A "
                "recognised value is what policy permits to be counted, not a "
                "prediction that the security will be realised."),
            "data_version": DATA_VERSION, "origin": ORIGIN,
            "is_synthetic": True,
        })

        for fid in live:
            share = (exposures.get(fid, 0.0) / total_exposure
                     if total_exposure > 0 else 0.0)
            allocated = recognised * share
            allocation_rows.append({
                "collateral_id": asset.collateral_id,
                "facility_id": fid, "borrower_id": asset.borrower_id,
                "reporting_date": as_at, "period": quarter,
                "asset_type": asset.asset_type,
                "allocation_basis": "pro rata to facility exposure",
                "allocation_share": round(share, 8),
                "allocated_recognised_amount": round(allocated, 6),
                "asset_recognised_value": round(recognised, 6),
                "lien_rank": asset.lien_rank,
                "data_version": DATA_VERSION, "origin": ORIGIN,
                "is_synthetic": True,
            })
            bucket = coverage.setdefault(
                fid, {"allocated": 0.0, "assets": 0, "oldest_valuation_days": 0,
                      "stale_assets": 0, "shared_assets": 0,
                      "recovery_lag_years": 0.0, "lag_weight": 0.0})
            bucket["allocated"] += allocated
            bucket["assets"] += 1
            bucket["oldest_valuation_days"] = max(
                bucket["oldest_valuation_days"],
                valuation["valuation_age_days"])
            bucket["stale_assets"] += int(stale)
            bucket["shared_assets"] += int(len(asset.facilities) > 1)
            bucket["recovery_lag_years"] += (
                float(rules["recovery_lag_years"]) * allocated)
            bucket["lag_weight"] += allocated

    for bucket in coverage.values():
        bucket["recovery_lag_years"] = (
            bucket["recovery_lag_years"] / bucket["lag_weight"]
            if bucket["lag_weight"] > 0 else 0.0)
    return asset_rows, allocation_rows, coverage


# ----------------------------------------------------------- one facility's ECL


def _remaining_periods(facility: Facility, quarter: str) -> int:
    days = (facility.maturity_date - cal.reporting_date(quarter)).days
    return int(max(1, min(round(days / 91.3125), ecl_mod.MAX_LIFETIME_PERIODS)))


def _ead_path(facility: Facility, drawn: float, undrawn: float,
              periods: int) -> tuple[float, list[float]]:
    """EAD at the reporting date and its path. Exposure and EAD stay distinct.

    EAD is drawn plus the credit conversion factor applied to the undrawn
    commitment. Exposure is drawn plus the whole undrawn commitment. They are
    different numbers, they are stored in different fields, and nothing in this
    package uses one where it means the other.
    """
    ccf = policy.CCF[facility.product]
    ead0 = drawn + ccf * undrawn
    if policy.AMORTISING.get(facility.product, False):
        path = [ead0 * max(0.0, 1.0 - t / max(periods, 1)) for t in range(periods)]
        # Never amortise the first period away: EAD at t=1 is essentially today's.
        path[0] = ead0
    else:
        path = [ead0] * periods
    return ead0, path


def _facility_state(borrower: Borrower, facility: Facility,
                    quarters: Sequence[str], index: int,
                    trajectory: pd.DataFrame) -> dict[str, Any]:
    """Drawn, undrawn, limit, days past due and status at one quarter."""
    quarter = quarters[index]
    rng = _rng("state", facility.facility_id, quarter)
    story = stories_mod.STORY_BY_ID.get(borrower.story_id)
    knobs = story.knobs if story else {}

    growth = float(knobs.get("exposure_growth", 0.0))
    limit = facility.limit * (1.0 + growth) ** index
    # A story whose mechanic is "only this one thing moved" needs the other
    # things genuinely held, not merely intended to be held. Drawing the
    # utilisation from a fixed reference quarter is what makes the exposure
    # path identical at both dates, so the attribution has nothing spurious to
    # allocate to EAD.
    state_rng = (_rng("state", facility.facility_id, quarters[0])
                 if knobs.get("hold_utilisation") else rng)
    utilisation = float(np.clip(state_rng.normal(0.71, 0.16), 0.05, 1.0))
    if policy.AMORTISING.get(facility.product, False):
        utilisation = float(np.clip(0.94 - 0.03 * index, 0.05, 1.0))
    drawn = limit * utilisation
    undrawn = max(0.0, limit - drawn)

    # A held story holds ALL of its state, not only the utilisation draw: the
    # debt-service strain that decides whether an account goes past due is read
    # from the reference quarter too. Without this an "only the overlay moved"
    # borrower silently migrated to Stage 2 on a past-due flag.
    state_index = 0 if knobs.get("hold_utilisation") else index
    row = trajectory.iloc[min(state_index, len(trajectory) - 1)]
    strain = 0.0
    if row["cash_available_for_debt_service"] < (
            row["scheduled_principal"] + row["cash_interest"]):
        strain = 1.0
    dpd = 0
    if knobs.get("start_stage_3"):
        dpd = 120 + 30 * index
    elif strain and state_rng.random() < 0.4:
        dpd = int(state_rng.integers(31, 89))
    elif state_rng.random() < 0.05:
        dpd = int(state_rng.integers(1, 29))

    return {"limit": limit, "drawn": drawn, "undrawn": undrawn,
            "utilisation": utilisation, "days_past_due": dpd}


# ------------------------------------------------------------ the snapshot


def build_quarter(*, quarter: str, index: int, quarters: Sequence[str],
                  borrowers: Sequence[Borrower], facilities: Sequence[Facility],
                  assets: Sequence[CollateralAsset],
                  trajectories: dict[str, pd.DataFrame],
                  statements: dict[str, list[dict[str, Any]]],
                  macro: pd.DataFrame,
                  perturbations: dict[str, dict[str, float]] | None = None
                  ) -> dict[str, pd.DataFrame]:
    """Every frame of one quarterly package.

    Returns the wide facility snapshot plus the detail tables that back it.
    The snapshot carries PRE-AGGREGATED summaries at facility grain — collateral
    coverage, covenant counts, the borrower's latest available financials — so
    a question like "break ECL down by stage and sector" needs no join at all,
    while the detail tables keep the real rows for drill-down.
    """
    as_at = cal.iso(quarter)
    as_at_date = cal.reporting_date(quarter)
    by_borrower = {b.borrower_id: b for b in borrowers}
    story_by_borrower = {b.borrower_id: b.story_id for b in borrowers}
    facilities_by_id = {f.facility_id: f for f in facilities}

    live_facilities = [
        f for f in facilities
        if f.enters_at <= index
        and (f.exits_at is None or index <= f.exits_at)
        and (f.written_off_at is None or index < f.written_off_at)
    ]

    states = {f.facility_id: _facility_state(
        by_borrower[f.borrower_id], f, quarters, index,
        trajectories[f.borrower_id]) for f in live_facilities}
    exposures = {fid: s["drawn"] + s["undrawn"] for fid, s in states.items()}

    asset_rows, allocation_rows, coverage = _collateral_rows(
        assets, facilities_by_id, exposures, quarters, index, story_by_borrower)

    # ---- the borrower layer: latest AVAILABLE statement, ratios, rating
    borrower_view: dict[str, dict[str, Any]] = {}
    financial_rows: list[dict[str, Any]] = []
    for b in borrowers:
        available = [s for s in statements[b.borrower_id]
                     if date.fromisoformat(s["availability_date"]) <= as_at_date]
        latest_statement = available[-1] if available else None
        if latest_statement is None:
            borrower_view[b.borrower_id] = {
                "statement": None, "ratios": {}, "rating": None,
                "notes": ["No financial statement has become available for "
                          "this borrower at this reporting date, so no ratio "
                          "and no model grade are reported."]}
            continue
        ratios = _ratios(latest_statement)
        rating = policy.rate_borrower(ratios)
        age = (as_at_date
               - date.fromisoformat(latest_statement["statement_end"])).days
        borrower_view[b.borrower_id] = {
            "statement": latest_statement, "ratios": ratios, "rating": rating,
            "statement_age_days": age,
            "notes": _ratio_notes(latest_statement, ratios),
        }
        financial_rows.append({
            **{k: v for k, v in latest_statement.items()},
            **{f"ratio_{k}": v for k, v in ratios.items()},
            "reporting_date": as_at, "period": quarter,
            "statement_age_days": age,
            "statement_is_stale": age > policy.STALE_STATEMENT_DAYS,
            "sector": b.sector, "segment": b.segment,
            "geography": b.geography, "group_id": b.group_id,
            "borrower_name": b.borrower_name,
            "rating_model_grade": rating["grade"],
            "rating_weighted_score": rating["weighted_score"],
            "rating_missing_inputs": ",".join(rating["missing_inputs"]),
            "ratio_notes": " ".join(borrower_view[b.borrower_id]["notes"]),
            "data_version": DATA_VERSION, "policy_version": POLICY_VERSION,
            "origin": ORIGIN, "is_synthetic": True,
        })

    # ---- covenants
    covenant_rows: list[dict[str, Any]] = []
    covenant_summary: dict[str, dict[str, Any]] = {}
    for b in borrowers:
        view = borrower_view[b.borrower_id]
        rng = _rng("covenants", b.borrower_id)
        story = stories_mod.STORY_BY_ID.get(b.story_id)
        knobs = story.knobs if story else {}
        chosen = [c for c in policy.COVENANT_DEFINITIONS
                  if rng.random() < 0.6] or [policy.COVENANT_DEFINITIONS[0]]
        summary = {"tested": 0, "breached": 0, "near_breach": 0, "waived": 0,
                   "worst_headroom": None, "worst_covenant": "",
                   "untested": 0}
        for definition in chosen:
            observed = view["ratios"].get(definition["metric"])
            base = {"dscr": 1.25, "net_debt_to_ebitda": 4.0,
                    "interest_coverage": 2.0, "current_ratio": 1.10,
                    "debt_to_equity": 2.2}[definition["metric"]]
            threshold = base * float(np.clip(rng.normal(1.0, 0.08), 0.8, 1.2))
            if knobs.get("waiver") and definition["covenant_id"] == "DSCR_MIN":
                threshold = max(threshold, (observed or 1.0) * 1.12)
            result = policy.test_covenant(definition, observed, threshold)

            waiver = knobs.get("waiver", "")
            waiver_valid_to = ""
            waiver_status = "NONE"
            if result.get("breached") and waiver:
                if waiver == "valid":
                    waiver_valid_to = (as_at_date + timedelta(days=200)).isoformat()
                    waiver_status = "VALID"
                else:
                    waiver_valid_to = (as_at_date + timedelta(days=48)).isoformat()
                    waiver_status = "EXPIRING"
            elif result.get("breached") and rng.random() < 0.35:
                waiver_valid_to = (as_at_date + timedelta(
                    days=int(rng.integers(20, 260)))).isoformat()
                waiver_status = ("EXPIRING"
                                 if date.fromisoformat(waiver_valid_to)
                                 <= as_at_date + timedelta(days=92) else "VALID")

            summary["tested"] += int(bool(result.get("tested")))
            summary["untested"] += int(not result.get("tested"))
            summary["breached"] += int(bool(result.get("breached")))
            summary["near_breach"] += int(bool(result.get("near_breach")))
            summary["waived"] += int(waiver_status in ("VALID", "EXPIRING"))
            headroom = result.get("headroom")
            if headroom is not None and (summary["worst_headroom"] is None
                                         or headroom < summary["worst_headroom"]):
                summary["worst_headroom"] = headroom
                summary["worst_covenant"] = definition["covenant_id"]

            covenant_rows.append({
                "obligation_id": f"{b.borrower_id}-{definition['covenant_id']}",
                "covenant_id": definition["covenant_id"],
                "borrower_id": b.borrower_id, "facility_id": "",
                "scope": "borrower",
                "reporting_date": as_at, "period": quarter,
                "metric": definition["metric"],
                "label": definition["label"],
                "contractual_formula": definition["formula"],
                "operator": definition["operator"],
                "threshold": round(threshold, 6),
                "tolerance": definition["tolerance"],
                "observed_value": (None if observed is None
                                   else round(float(observed), 6)),
                "test_date": as_at,
                "test_frequency": definition["frequency"],
                "next_test_due": (as_at_date + timedelta(days=91)).isoformat(),
                "headroom": (None if result.get("headroom") is None
                             else round(float(result["headroom"]), 6)),
                "breached": result.get("breached"),
                "near_breach": result.get("near_breach"),
                "tested": result.get("tested"),
                "not_tested_reason": result.get("reason", ""),
                "materiality": definition["materiality"],
                "waiver_status": waiver_status,
                "waiver_valid_to": waiver_valid_to,
                "cure_period_days": policy.COVENANT_CURE_DAYS,
                "outstanding_action": (
                    "Obtain revised forecasts and confirm the cure plan"
                    if result.get("breached") and waiver_status != "VALID"
                    else "Monitor at the next test date"),
                "responsible_role": "Relationship Manager",
                "policy_id": policy.COVENANT_POLICY_ID,
                "policy_version": POLICY_VERSION,
                "data_version": DATA_VERSION, "origin": ORIGIN,
                "is_synthetic": True,
            })
        covenant_summary[b.borrower_id] = summary

    # ---- the facility layer: staging, scenario parameters, ECL
    snapshot_rows: list[dict[str, Any]] = []
    scenario_rows: list[dict[str, Any]] = []
    curve_rows: list[dict[str, Any]] = []
    measurements: dict[str, ecl_mod.FacilityMeasurement] = {}

    standardised_by_scenario = {
        (geo, scenario): _standardised(macro, geography=geo, quarter=quarter,
                                       scenario=scenario)
        for geo in GEOGRAPHIES for scenario in policy.SCENARIO_IDS}
    #: The reference vector for stories that hold their macro inputs fixed.
    held_macro = {
        (geo, scenario): _standardised(macro, geography=geo,
                                       quarter=quarters[0], scenario=scenario)
        for geo in GEOGRAPHIES for scenario in policy.SCENARIO_IDS}

    for facility in live_facilities:
        b = by_borrower[facility.borrower_id]
        view = borrower_view[b.borrower_id]
        state = states[facility.facility_id]
        story = stories_mod.STORY_BY_ID.get(b.story_id)
        knobs = story.knobs if story else {}

        # ---- rating: the model grade, then any approved override
        if view["rating"] is None:
            model_rank = 8  # a stated fallback grade for an unrated borrower
            model_grade = policy.grade_for_rank(model_rank)
            rating_date = ""
            rating_note = ("No statement is available, so the model grade "
                           "could not be produced and the policy fallback "
                           "grade is used. This is recorded, not hidden.")
        else:
            model_rank = int(view["rating"]["rank"])
            model_grade = view["rating"]["grade"]
            rating_date = view["statement"]["availability_date"]
            rating_note = ""

        # Gradual drift accumulates across the history; a step story applies
        # its whole movement in the final generated quarter, so the migration
        # falls INSIDE any two consecutive published quarters instead of having
        # finished several quarters before the comparison window opens.
        if knobs.get("sicr_step_at_end"):
            drift = (float(knobs.get("sicr_step_notches", 4.0))
                     if index >= len(quarters) - 1 else 0.0)
        else:
            drift = float(knobs.get("rating_drift", 0.0)) * index
        approved_rank = int(np.clip(round(model_rank + drift), 1,
                                    policy.WORST_PERFORMING_RANK))
        override = approved_rank != model_rank
        approved_grade = policy.grade_for_rank(approved_rank)

        # Most facilities originated a notch or two stronger than they stand
        # today. A migration story pins origination to the current grade so the
        # notch count at the opening date is exactly zero, and the step at the
        # closing date is the only thing that can cross the SICR threshold.
        origination_gap = (0 if knobs.get("origination_equals_current")
                           else int(_rng("orig", facility.facility_id)
                                    .integers(0, 3)))
        origination_rank = int(np.clip(model_rank - origination_gap, 1,
                                       policy.WORST_PERFORMING_RANK))

        # ---- exposure and EAD
        periods = _remaining_periods(facility, quarter)
        ead0, ead_path = _ead_path(facility, state["drawn"], state["undrawn"],
                                   periods)
        exposure = state["drawn"] + state["undrawn"]
        gross_carrying = state["drawn"]

        # ---- collateral coverage for this facility
        cover = coverage.get(facility.facility_id,
                             {"allocated": 0.0, "assets": 0,
                              "oldest_valuation_days": 0, "stale_assets": 0,
                              "shared_assets": 0, "recovery_lag_years": 0.0})
        coverage_ratio = (min(cover["allocated"] / exposure, 1.0)
                          if exposure > 0 else 0.0)

        # ---- staging, from the stated policy
        base_pd = policy.rating_pd(approved_grade)
        origination_pd = policy.rating_pd(policy.grade_for_rank(origination_rank))
        lifetime_now = ecl_mod.cumulative_pd(
            [ecl_mod.annual_pd_to_hazard(base_pd)] * periods, periods)
        lifetime_origination = ecl_mod.cumulative_pd(
            [ecl_mod.annual_pd_to_hazard(origination_pd)] * periods, periods)
        sicr = policy.assess_sicr(
            origination_rank=origination_rank, current_rank=approved_rank,
            origination_lifetime_pd=lifetime_origination,
            current_lifetime_pd=lifetime_now,
            days_past_due=state["days_past_due"],
            watchlist=bool(covenant_summary[b.borrower_id]["breached"]
                           and covenant_summary[b.borrower_id]["waived"] == 0))
        stage = int(sicr["stage"])

        # ---- a deliberate perturbation of ONE stored input, for the
        # anti-canned-answer checks of brief §6.2. It multiplies the
        # rating-linked PD or the collateral coverage this borrower's
        # measurement is built from, so the whole chain below recomputes. It is
        # applied to the DATA, never to the narrative.
        shift = (perturbations or {}).get(b.borrower_id, {})
        if shift.get("pd_multiplier"):
            base_pd = float(np.clip(base_pd * float(shift["pd_multiplier"]),
                                    policy.PD_FLOOR, policy.PD_CAP))
        if shift.get("coverage_multiplier"):
            coverage_ratio = float(np.clip(
                coverage_ratio * float(shift["coverage_multiplier"]), 0.0, 1.0))

        # ---- per-scenario parameters, through the declared macro model
        scenario_parameters: list[dict[str, Any]] = []
        scenario_detail: list[dict[str, Any]] = []
        weights = dict(policy.SCENARIO_WEIGHT)
        if shift.get("downturn_weight"):
            downturn = float(shift["downturn_weight"])
            weights = {"base": round(1.0 - downturn - 0.20, 10),
                       "upturn": 0.20, "downturn": downturn}
        if knobs.get("weights_only") and index >= len(quarters) - 1:
            # Only the weights move, and only in the FINAL generated quarter,
            # so that any two consecutive published quarters see a change on
            # this account rather than the same altered weights at both dates.
            # Everything else is held, giving the attribution exactly one place
            # to put the movement.
            weights = {"base": 0.50, "upturn": 0.15, "downturn": 0.35}

        for scenario in policy.SCENARIO_IDS:
            # Same reason as hold_utilisation above: a "stable PD" story is only
            # a stable PD if the macro inputs behind it are the same at both
            # dates. Held stories read the reference quarter's vector.
            standardised = (held_macro[(b.geography, scenario)]
                            if knobs.get("hold_macro")
                            else standardised_by_scenario[(b.geography, scenario)])
            pd_model = policy.macro_adjusted_pd(
                base_pd=base_pd, sector=b.sector, standardised=standardised)
            unsecured = policy.UNSECURED_LGD[b.segment]
            lgd_model = policy.macro_adjusted_lgd(
                base_lgd=unsecured, sector=b.sector, standardised=standardised)
            effective_lgd = ecl_mod.severity_from_recovery(
                unsecured_lgd=lgd_model["adjusted_lgd"],
                secured_lgd=policy.SECURED_LGD[b.segment],
                collateral_coverage=coverage_ratio,
                recovery_lag_years=cover["recovery_lag_years"],
                effective_rate=facility.effective_rate)
            scenario_parameters.append({
                "scenario_id": scenario, "weight": weights[scenario],
                "twelve_month_pd": pd_model["adjusted_pd"],
                "lgd": effective_lgd, "ead": ead0,
                "hazard_shape": [1.0 + 0.02 * t for t in range(periods)],
            })
            scenario_detail.append({
                "scenario": scenario, "pd_model": pd_model,
                "unsecured_lgd": lgd_model["adjusted_lgd"],
                "secured_lgd": policy.SECURED_LGD[b.segment],
                "effective_lgd": effective_lgd,
            })

        if stage == ecl_mod.STAGE_3:
            base_recovery = policy.IMPAIRED_BASE_RECOVERY[b.segment]
            # One step in the final generated quarter, not a shift compounded
            # over the whole history. Compounding it drove expected recovery to
            # the policy floor and left a single Stage 3 borrower carrying 94%
            # of the demo's allowance, which made every portfolio answer a
            # statement about that one account.
            recovery_shift = float(knobs.get("recovery_shift", 0.0))
            shift = recovery_shift if index >= len(quarters) - 1 else 0.0
            impaired_parameters = [
                {"scenario_id": s, "weight": weights[s],
                 "recovery_rate": float(np.clip(
                     base_recovery + shift
                     + coverage_ratio * 0.35
                     + {"base": 0.0, "upturn": 0.06, "downturn": -0.08}[s],
                     0.02, 0.95)),
                 "recovery_lag_years": policy.IMPAIRED_RECOVERY_LAG_YEARS}
                for s in policy.SCENARIO_IDS]
            measurement = ecl_mod.impaired_measurement(
                facility_id=facility.facility_id, borrower_id=b.borrower_id,
                reporting_date=as_at,
                gross_carrying_amount=gross_carrying,
                effective_rate=facility.effective_rate,
                scenario_parameters=impaired_parameters,
                currency=facility.currency, fx_rate=1.0)
        else:
            measurement = ecl_mod.performing_measurement(
                facility_id=facility.facility_id, borrower_id=b.borrower_id,
                reporting_date=as_at, stage=stage,
                remaining_periods=periods,
                effective_rate=facility.effective_rate,
                scenario_parameters=scenario_parameters,
                ead_path_factor=[e / ead0 if ead0 else 1.0 for e in ead_path],
                currency=facility.currency, fx_rate=1.0)

        # ---- overlay, separately identified at both dates
        overlay = 0.0
        overlay_id = ""
        modelled = ecl_mod.measure(measurement).weighted_model_ecl
        if b.sector == "Construction":
            rate = 0.08 + (float(knobs.get("overlay_step", 0.0)) * index * 0.10)
            overlay = modelled * rate
            overlay_id = "OVL_CONSTRUCTION_CYCLE"
        elif b.segment == "SME" and view["statement"] is None:
            overlay = modelled * 0.12
            overlay_id = "OVL_SME_DATA_QUALITY"
        elif knobs.get("overlay_step"):
            overlay = modelled * float(knobs["overlay_step"]) * index * 0.10
            overlay_id = "OVL_CONSTRUCTION_CYCLE"

        measurement = ecl_mod.FacilityMeasurement(
            facility_id=measurement.facility_id,
            borrower_id=measurement.borrower_id,
            reporting_date=measurement.reporting_date,
            stage=measurement.stage,
            horizon_periods=measurement.horizon_periods,
            scenarios=measurement.scenarios, overlay=overlay,
            currency=measurement.currency, fx_rate=measurement.fx_rate,
            method=measurement.method, limitations=measurement.limitations)
        measurements[facility.facility_id] = measurement
        result = ecl_mod.measure(measurement)

        # ---- rows
        for detail, scenario_result in zip(scenario_detail, result.scenarios):
            scenario_rows.append({
                "facility_id": facility.facility_id,
                "borrower_id": b.borrower_id,
                "reporting_date": as_at, "period": quarter,
                "scenario_id": scenario_result.scenario_id,
                "scenario_weight": scenario_result.weight,
                "twelve_month_pd": round(scenario_result.twelve_month_pd, 10),
                "lifetime_pd": round(scenario_result.cumulative_pd, 10),
                "secured_lgd": round(detail["secured_lgd"], 10),
                "unsecured_lgd": round(detail["unsecured_lgd"], 10),
                "effective_lgd": round(scenario_result.exposure_weighted_lgd, 10),
                "ccf": policy.CCF[facility.product],
                "ead": round(scenario_result.ead_at_reporting_date, 6),
                "scenario_ecl": round(scenario_result.ecl, 10),
                "periods_measured": scenario_result.periods_measured,
                "macro_log_odds_shift": round(
                    float(detail["pd_model"]["log_odds_shift"]), 10),
                "macro_predictors_used": ",".join(
                    p["predictor"] for p in detail["pd_model"]["predictors_used"]),
                "model_version": MODEL_VERSION,
                "policy_version": POLICY_VERSION,
                "forecast_vintage": quarter,
                "data_version": DATA_VERSION, "origin": ORIGIN,
                "is_synthetic": True,
            })
            # The curve carries the WHOLE per-period input set — hazard,
            # severity, exposure at default and discount factor — not only the
            # probabilities. Brief §4.2 requires every scenario PD/LGD/EAD/ECL
            # to be reproducible from the stored inputs, and the request-time
            # reader rebuilds the measurement from exactly these rows, so a
            # curve missing its severity path would leave the Cockpit
            # re-deriving a number instead of reading it.
            scenario_input = measurement.scenarios[
                [s.scenario_id for s in measurement.scenarios]
                .index(scenario_result.scenario_id)]
            for t, (marginal, survival) in enumerate(
                    zip(scenario_result.marginal_pd, scenario_result.survival)):
                curve_rows.append({
                    "facility_id": facility.facility_id,
                    "borrower_id": b.borrower_id,
                    "reporting_date": as_at, "period": quarter,
                    "scenario_id": scenario_result.scenario_id,
                    "future_period": t + 1,
                    "conditional_hazard": float(scenario_input.hazard[t]),
                    "survival": float(survival),
                    "marginal_default_probability": float(marginal),
                    "loss_severity": float(scenario_input.lgd[t]),
                    "ead_at_default": float(scenario_input.ead[t]),
                    "discount_factor": float(scenario_input.discount[t]),
                    "scenario_weight": float(scenario_input.weight),
                    "model_version": MODEL_VERSION,
                    "data_version": DATA_VERSION, "origin": ORIGIN,
                    "is_synthetic": True,
                })

        statement = view["statement"]
        ratios = view["ratios"]
        summary = covenant_summary[b.borrower_id]
        snapshot_rows.append({
            # ---- identity
            "dataset_version": DATA_VERSION,
            "facility_id": facility.facility_id,
            "borrower_id": b.borrower_id, "borrower_name": b.borrower_name,
            "group_id": b.group_id, "group_name": b.group_name,
            "reporting_date": as_at, "period": quarter,
            "period_label": cal.display(quarter),
            "sector": b.sector, "subsector": b.subsector,
            "geography": b.geography, "segment": b.segment,
            "borrower_type": b.borrower_type, "product": facility.product,
            "business_unit": b.business_unit,
            "relationship_manager": b.relationship_manager,
            # ---- facility
            "origination_date": facility.origination_date.isoformat(),
            "maturity_date": facility.maturity_date.isoformat(),
            "repayment_type": ("Amortising"
                               if policy.AMORTISING.get(facility.product)
                               else "Bullet or revolving"),
            "remaining_periods": periods,
            "reporting_currency": REPORTING_CURRENCY,
            "original_currency": facility.currency,
            "fx_rate": 1.0, "fx_rate_date": as_at,
            "limit": round(state["limit"], 6),
            "drawn_amount": round(state["drawn"], 6),
            "undrawn_commitment": round(state["undrawn"], 6),
            "gross_carrying_amount": round(gross_carrying, 6),
            "exposure": round(exposure, 6),
            "ead": round(ead0, 6),
            "ccf": policy.CCF[facility.product],
            "utilisation": round(state["utilisation"], 8),
            "contractual_rate": round(facility.contractual_rate, 8),
            "effective_rate": round(facility.effective_rate, 8),
            "is_new_this_period": bool(facility.enters_at == index and index > 0),
            "is_closed_this_period": bool(facility.exits_at == index),
            "is_written_off": bool(facility.written_off_at is not None
                                   and index >= facility.written_off_at),
            # ---- staging and default
            "stage": stage, "stage_trigger": sicr["trigger"],
            "sicr_reason": sicr["reason"],
            "sicr_policy_id": sicr["policy_id"],
            "stage_policy_version": POLICY_VERSION,
            "days_past_due": state["days_past_due"],
            "default_definition_dpd": policy.DEFAULT_DPD,
            "is_defaulted": bool(stage == 3),
            "is_npl": bool(stage == 3) if policy.NPL_EQUALS_STAGE_3 else None,
            "npl_policy_note": policy.NPL_POLICY_NOTE,
            "manual_override": bool(sicr.get("overridden")),
            # ---- ratings
            "rating_model_grade": model_grade,
            "rating_approved_grade": approved_grade,
            "rating_rank": approved_rank,
            "rating_origination_grade": policy.grade_for_rank(origination_rank),
            "rating_origination_rank": origination_rank,
            "rating_notches_since_origination": approved_rank - origination_rank,
            "rating_override": bool(override),
            "rating_override_reason": (
                "Approved grade differs from the model grade under the demo "
                "override policy." if override else ""),
            "rating_date": rating_date,
            "rating_scale": policy.RATING_SCALE_ID,
            "rating_model_version": policy.RATING_MODEL_VERSION,
            "rating_is_stale": bool(
                rating_date and (as_at_date - date.fromisoformat(rating_date)).days
                > policy.STALE_RATING_DAYS),
            "rating_note": rating_note,
            "rating_linked_twelve_month_pd": round(base_pd, 10),
            # ---- scenario summaries and ECL
            "scenario_weight_base": weights["base"],
            "scenario_weight_upturn": weights["upturn"],
            "scenario_weight_downturn": weights["downturn"],
            **{f"ecl_{s.scenario_id}": round(s.ecl, 10) for s in result.scenarios},
            **{f"twelve_month_pd_{s.scenario_id}": round(s.twelve_month_pd, 10)
               for s in result.scenarios},
            **{f"lifetime_pd_{s.scenario_id}": round(s.cumulative_pd, 10)
               for s in result.scenarios},
            **{f"effective_lgd_{s.scenario_id}":
               round(s.exposure_weighted_lgd, 10) for s in result.scenarios},
            "weighted_twelve_month_pd": round(result.weighted_twelve_month_pd, 10),
            "weighted_lifetime_pd": round(result.weighted_lifetime_pd, 10),
            "weighted_lgd": round(result.weighted_lgd, 10),
            "weighted_ead": round(result.weighted_ead, 6),
            "weighted_model_ecl": round(result.weighted_model_ecl, 10),
            "overlay": round(result.overlay, 10),
            "overlay_id": overlay_id,
            "reported_ecl": round(result.reported_ecl, 10),
            "measurement_method": result.method,
            "measurement_horizon_periods": result.horizon_periods,
            "coverage_ratio": round(
                result.reported_ecl / exposure if exposure else 0.0, 10),
            "model_version": MODEL_VERSION,
            "policy_version": POLICY_VERSION,
            # ---- collateral summary, pre-aggregated to facility grain
            "collateral_assets": int(cover["assets"]),
            "collateral_recognised_allocated": round(cover["allocated"], 6),
            "collateral_coverage_ratio": round(coverage_ratio, 8),
            "secured_amount": round(min(cover["allocated"], exposure), 6),
            "unsecured_amount": round(
                max(0.0, exposure - cover["allocated"]), 6),
            "collateral_oldest_valuation_days": int(
                cover["oldest_valuation_days"]),
            "collateral_stale_valuations": int(cover["stale_assets"]),
            "collateral_shared_assets": int(cover["shared_assets"]),
            "collateral_expected_recovery_lag_years": round(
                float(cover["recovery_lag_years"]), 4),
            # ---- covenant summary, pre-aggregated to facility grain
            "covenants_tested": summary["tested"],
            "covenants_untested": summary["untested"],
            "covenants_breached": summary["breached"],
            "covenants_near_breach": summary["near_breach"],
            "covenants_waived": summary["waived"],
            "covenant_worst_headroom": (
                None if summary["worst_headroom"] is None
                else round(float(summary["worst_headroom"]), 6)),
            "covenant_worst_id": summary["worst_covenant"],
            # ---- borrower financial summary, pre-aggregated
            "statement_available": statement is not None,
            "statement_end": statement["statement_end"] if statement else None,
            "statement_availability_date": (
                statement["availability_date"] if statement else None),
            "statement_audited": statement["audited"] if statement else None,
            "statement_scope": statement["statement_scope"] if statement else None,
            "statement_age_days": view.get("statement_age_days"),
            "statement_is_stale": bool(
                (view.get("statement_age_days") or 0) > policy.STALE_STATEMENT_DAYS),
            "revenue": round(statement["revenue"], 6) if statement else None,
            "ebitda": round(statement["ebitda"], 6) if statement else None,
            "net_profit": round(statement["net_profit"], 6) if statement else None,
            "total_debt": round(statement["total_debt"], 6) if statement else None,
            "total_equity": round(statement["total_equity"], 6) if statement else None,
            **{f"ratio_{k}": (None if v is None else round(float(v), 8))
               for k, v in (ratios or {}).items()},
            "ratio_note": " ".join(view["notes"]),
            # ---- provenance
            "data_version": DATA_VERSION, "origin": ORIGIN,
            "is_synthetic": True, "not_client_data": NOT_CLIENT_DATA,
            "load_timestamp": f"{as_at}T23:59:59Z",
            "amount_unit": AMOUNT_UNIT,
        })

    return {
        "snapshot": pd.DataFrame(snapshot_rows),
        "financials": pd.DataFrame(financial_rows),
        "collateral": pd.DataFrame(asset_rows),
        "collateral_allocation": pd.DataFrame(allocation_rows),
        "covenants": pd.DataFrame(covenant_rows),
        "scenarios": pd.DataFrame(scenario_rows),
        "curves": pd.DataFrame(curve_rows),
        "_measurements": measurements,
    }


# ---------------------------------------------------------------- the build


@dataclass
class Build:
    """One generated demo, ready to be written and registered."""

    quarters: list[str]
    published: list[str]
    frames: dict[str, pd.DataFrame]
    per_quarter: dict[str, pd.DataFrame]
    measurements: dict[str, dict[str, ecl_mod.FacilityMeasurement]]
    assignments: dict[str, str]
    manifest: dict[str, Any]


def build_demo(*, publish: Sequence[str] | None = None,
               borrowers: int = 500, facilities_target: int = 1100,
               history: Sequence[str] = cal.QUARTERS,
               perturbations: dict[str, dict[str, float]] | None = None,
               perturb_from: str = "") -> Build:
    """Generate the whole demo, and publish the requested quarters.

    `history` is always the full calendar even when only two quarters are
    published. A pilot that generated its statements from its own two quarters
    would have no statement available at its opening date at all — every
    borrower would fall back to the policy's unrated grade, every rating would
    be identical and the ECL movement would carry no rating signal. The first
    pilot build did exactly that, which is why the history and the published
    set are separate arguments.
    """
    published = list(publish or history)
    unknown = [q for q in published if q not in history]
    if unknown:
        raise ValueError(
            f"cannot publish {unknown}: they are outside the generated "
            f"history {list(history)}")

    quarters = list(history)
    borrowers_list, facilities, assets, assignments = build_population(
        borrowers=borrowers, facilities_target=facilities_target,
        quarters=quarters)
    macro = macro_paths(quarters)
    trajectories = {b.borrower_id: _trajectory(b, quarters)
                    for b in borrowers_list}
    statements = {b.borrower_id: _statements(b, trajectories[b.borrower_id],
                                             quarters)
                  for b in borrowers_list}

    per_quarter: dict[str, pd.DataFrame] = {}
    measurements: dict[str, dict[str, ecl_mod.FacilityMeasurement]] = {}
    collected: dict[str, list[pd.DataFrame]] = {
        "financials": [], "collateral": [], "collateral_allocation": [],
        "covenants": [], "scenarios": [], "curves": []}

    for label in published:
        index = quarters.index(label)
        # A perturbation applied from a named quarter onward changes the
        # CLOSING date's inputs only, so the anti-canned-answer check sees a
        # movement rather than two equally shifted endpoints.
        applies = (not perturb_from
                   or quarters.index(label) >= quarters.index(perturb_from))
        built = build_quarter(
            quarter=label, index=index, quarters=quarters,
            borrowers=borrowers_list, facilities=facilities, assets=assets,
            trajectories=trajectories, statements=statements, macro=macro,
            perturbations=perturbations if applies else None)
        per_quarter[label] = built["snapshot"]
        measurements[label] = built["_measurements"]
        for name in collected:
            collected[name].append(built[name])

    history_frame = (pd.concat(list(per_quarter.values()), ignore_index=True)
                     if per_quarter else pd.DataFrame())
    frames: dict[str, pd.DataFrame] = {
        "cockpit_credit_history": history_frame,
        "cockpit_borrower_financials": _concat(collected["financials"]),
        "cockpit_collateral_assets": _concat(collected["collateral"]),
        "cockpit_collateral_allocation": _concat(
            collected["collateral_allocation"]),
        "cockpit_covenant_tests": _concat(collected["covenants"]),
        "cockpit_scenario_parameters": _concat(collected["scenarios"]),
        "cockpit_risk_curves": _concat(collected["curves"]),
        "cockpit_macro_paths": macro,
    }
    frames["cockpit_movements"] = derived_movements(per_quarter, published)

    manifest = source_manifest(published, frames, per_quarter)
    manifest["perturbations"] = {k: dict(v)
                                 for k, v in (perturbations or {}).items()}
    manifest["perturb_from"] = perturb_from
    return Build(quarters=quarters, published=published, frames=frames,
                 per_quarter=per_quarter, measurements=measurements,
                 assignments=assignments, manifest=manifest)


def _concat(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    live = [f for f in frames if not f.empty]
    return pd.concat(live, ignore_index=True) if live else pd.DataFrame()


def derived_movements(per_quarter: dict[str, pd.DataFrame],
                      published: Sequence[str]) -> pd.DataFrame:
    """Matched-prior movements. Brief §3.3.

    A VERSIONED CACHED DERIVATIVE of the snapshots, not another source of
    truth: every column here is recomputable from the two snapshots it names,
    and it carries their data version so a regenerated book invalidates it.

    New and exited facilities are marked as such and carry a null comparator
    rather than a manufactured zero, because a facility that did not exist last
    quarter did not have an ECL of nought.
    """
    rows: list[dict[str, Any]] = []
    for i, label in enumerate(published):
        prior_label = published[i - 1] if i > 0 else None
        current = per_quarter[label]
        if prior_label is None:
            continue
        prior = per_quarter[prior_label].set_index("facility_id")
        for _, row in current.iterrows():
            fid = row["facility_id"]
            was = prior.loc[fid] if fid in prior.index else None
            entry = {
                "facility_id": fid, "borrower_id": row["borrower_id"],
                "reporting_date": row["reporting_date"], "period": label,
                "comparison_period": prior_label,
                "sector": row["sector"], "segment": row["segment"],
                "geography": row["geography"], "group_id": row["group_id"],
                "membership": "continuing" if was is not None else "new",
                "data_version": DATA_VERSION, "origin": ORIGIN,
                "is_synthetic": True,
            }
            for field_name, unit in (("reported_ecl", AMOUNT_UNIT),
                                     ("exposure", AMOUNT_UNIT),
                                     ("ead", AMOUNT_UNIT),
                                     ("utilisation", "ratio"),
                                     ("coverage_ratio", "ratio"),
                                     ("collateral_coverage_ratio", "ratio")):
                now = float(row[field_name])
                before = None if was is None else float(was[field_name])
                entry[f"{field_name}_now"] = now
                entry[f"{field_name}_prior"] = before
                entry[f"{field_name}_change"] = (
                    None if before is None else now - before)
                entry[f"{field_name}_unit"] = unit
            # PD and LGD movements are in PERCENTAGE POINTS, stated as such.
            # A currency movement never gets a basis-point unit anywhere here.
            for field_name in ("weighted_twelve_month_pd", "weighted_lgd"):
                now = float(row[field_name])
                before = None if was is None else float(was[field_name])
                entry[f"{field_name}_now"] = now
                entry[f"{field_name}_prior"] = before
                entry[f"{field_name}_change_pp"] = (
                    None if before is None else (now - before) * 100.0)
                entry[f"{field_name}_change_bps"] = (
                    None if before is None else (now - before) * 10_000.0)
            entry["rating_notch_change"] = (
                None if was is None
                else int(row["rating_rank"]) - int(was["rating_rank"]))
            entry["stage_now"] = int(row["stage"])
            entry["stage_prior"] = None if was is None else int(was["stage"])
            entry["stage_transition"] = (
                None if was is None
                else f"{int(was['stage'])}->{int(row['stage'])}")
            entry["covenant_breach_change"] = (
                None if was is None
                else int(row["covenants_breached"]) - int(was["covenants_breached"]))
            rows.append(entry)

        # Facilities present last quarter and gone this one.
        gone = set(prior.index) - set(current["facility_id"])
        for fid in sorted(gone):
            was = prior.loc[fid]
            rows.append({
                "facility_id": fid, "borrower_id": was["borrower_id"],
                "reporting_date": cal.iso(label), "period": label,
                "comparison_period": prior_label,
                "sector": was["sector"], "segment": was["segment"],
                "geography": was["geography"], "group_id": was["group_id"],
                "membership": "exited",
                "reported_ecl_now": None,
                "reported_ecl_prior": float(was["reported_ecl"]),
                "reported_ecl_change": None,
                "reported_ecl_unit": AMOUNT_UNIT,
                "exposure_now": None,
                "exposure_prior": float(was["exposure"]),
                "exposure_change": None, "exposure_unit": AMOUNT_UNIT,
                "stage_now": None, "stage_prior": int(was["stage"]),
                "stage_transition": None,
                "data_version": DATA_VERSION, "origin": ORIGIN,
                "is_synthetic": True,
            })
    return pd.DataFrame(rows)


def source_manifest(published: Sequence[str], frames: dict[str, pd.DataFrame],
                    per_quarter: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Seed, versions, checksums, coverage and currency. Brief §3.2."""
    def checksum(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "empty"
        payload = pd.util.hash_pandas_object(
            frame.reset_index(drop=True), index=False).values.tobytes()
        return hashlib.blake2b(payload, digest_size=16).hexdigest()

    return {
        "generator": "backend.cockpit_v2.generate",
        "data_version": DATA_VERSION,
        "model_version": MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "master_seed": MASTER_SEED,
        "deterministic": True,
        "origin": ORIGIN,
        "is_synthetic": True,
        "not_client_data": NOT_CLIENT_DATA,
        "reporting_currency": REPORTING_CURRENCY,
        "amount_unit": AMOUNT_UNIT,
        "quarter_semantics": cal.QUARTER_SEMANTICS,
        "published_quarters": list(published),
        "latest_published_quarter": published[-1] if published else None,
        "coverage": {
            "quarters": len(published),
            "borrowers": int(frames["cockpit_credit_history"]["borrower_id"]
                             .nunique()) if not frames[
                                 "cockpit_credit_history"].empty else 0,
            "facilities": int(frames["cockpit_credit_history"]["facility_id"]
                              .nunique()) if not frames[
                                  "cockpit_credit_history"].empty else 0,
            "rows_per_quarter": {q: int(len(f)) for q, f in per_quarter.items()},
        },
        "checksums": {name: checksum(frame) for name, frame in frames.items()},
        "quarter_checksums": {q: checksum(f) for q, f in per_quarter.items()},
    }
