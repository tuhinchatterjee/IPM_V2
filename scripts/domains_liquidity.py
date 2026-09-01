"""Liquidity, treasury and cash flow: the domain the Early Warning module needed.

Why this exists
---------------
The Early Warning screen carried a box headed "What this deployment cannot
watch for", and everything in it was liquidity: cash balances, working-capital
movement, short-term debt, upcoming maturities. A credit officer reading that
box is being told the product knows what matters and has not been given it.

Liquidity is also where a corporate credit actually fails. A borrower does not
default because its leverage ratio drifted; it defaults because a payment fell
due and the cash was not there. Every deterioration story this platform tells —
utilisation climbing, receivables stretching, a facility rolled rather than
repaid, a maturity wall inside twelve months — is a liquidity story that the
book could only see the shadow of.

How it is built
---------------
DERIVED from the facility book, never generated beside it. A borrower whose
facilities are drawn to the limit has a thin liquidity buffer here; one whose
DSCR is under 1.2x has operating cash flow that does not cover its debt
service; one in arrears has receivables that stretched first. A demonstration
where the liquidity domain disagrees with the facility book is a demonstration
of nothing, so the two are computed from the same underlying stress.

Fourteen datasets, one shared frame
-----------------------------------
The mandate names fourteen datasets and one field list. They are views of one
quarterly treasury position per borrower — `_position()` computes it once, and
each dataset is the slice of it that answers its own question. Computing them
independently would let the receivable days in `receivables_ageing` disagree
with the receivable days in `working_capital_position`, which is the class of
defect that makes a data platform untrustworthy.

Everything here is SYNTHETIC and marked as such on every dataset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: SAR millions. The facility book carries exposure in the same unit, and the
#: cash-flow figures are scaled off it so the two can be read side by side.
UNIT = "SAR millions"


def _stress(facility: pd.DataFrame) -> np.ndarray:
    """How hard this facility-quarter is being squeezed, from 0 to about 1.

    Read off the book rather than drawn: utilisation, debt-service coverage,
    covenant headroom, arrears and stage. A borrower the facility book already
    says is struggling must not come back here with comfortable cash.
    """
    used = np.clip(facility["utilisation_pct"].to_numpy(dtype=float) / 100.0, 0, 1.2)
    dscr = facility["dscr"].to_numpy(dtype=float)
    thin = np.clip((1.5 - np.nan_to_num(dscr, nan=1.5)) / 1.2, 0, 1)
    headroom = facility["covenant_headroom_pct"].to_numpy(dtype=float)
    tight = np.clip((20.0 - np.nan_to_num(headroom, nan=20.0)) / 40.0, 0, 1)
    late = np.clip(facility["dpd_days"].to_numpy(dtype=float) / 180.0, 0, 1)
    stage = (facility["ifrs9_stage"].to_numpy(dtype=float) - 1.0) / 2.0
    return np.clip(
        0.30 * used + 0.24 * thin + 0.18 * tight + 0.16 * late + 0.12 * stage,
        0.0, 1.0)


def _position(facility: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """One treasury position per borrower per quarter.

    Aggregated to the BORROWER, because that is the level a treasury operates
    at: cash sits in the company, not in the facility. Facility-grain fields —
    committed limits, drawn amounts, the debt-service schedule — keep their
    account_id and are built from the un-aggregated book below.
    """
    keep = ["customer_id", "period", "sector", "region", "segment", "ead",
            "exposure", "limit_amount", "undrawn", "utilisation_pct", "dscr",
            "covenant_headroom_pct", "dpd_days", "ifrs9_stage"]
    book = facility[[c for c in keep if c in facility.columns]].copy()
    book["stress"] = _stress(facility)

    by = book.groupby(["customer_id", "period"], observed=True)
    at = by.agg(
        sector=("sector", "first"),
        region=("region", "first"),
        segment=("segment", "first"),
        exposure=("exposure", "sum"),
        limit_amount=("limit_amount", "sum"),
        undrawn=("undrawn", "sum"),
        utilisation_pct=("utilisation_pct", "mean"),
        dscr=("dscr", "mean"),
        stress=("stress", "max"),
    ).reset_index()

    n = len(at)
    stress = at["stress"].to_numpy()
    exposure = at["exposure"].to_numpy(dtype=float)

    # Turnover scales with how much the borrower has borrowed, with a wide
    # spread: a trading company turns over many times its facility, a project
    # company a fraction of it.
    turn = np.exp(rng.normal(0.55, 0.55, n))
    at["revenue"] = np.round(exposure * turn, 3)

    # Operating cash flow as a margin on revenue, thinning under stress.
    margin = np.clip(rng.normal(0.115, 0.045, n) - 0.075 * stress, -0.06, 0.30)
    at["operating_cash_flow"] = np.round(at["revenue"] * margin, 3)

    # Capex is cut first when cash is short. That is what makes a falling
    # capex line an early warning rather than a sign of discipline.
    at["capex"] = np.round(
        at["revenue"] * np.clip(rng.normal(0.055, 0.028, n) * (1 - 0.55 * stress),
                                0.0, 0.25), 3)
    at["free_cash_flow"] = np.round(
        at["operating_cash_flow"] - at["capex"], 3)

    # Working capital. Receivables stretch and payables stretch further —
    # a borrower short of cash pays its suppliers late before it tells its bank.
    at["receivable_days"] = np.round(
        np.clip(rng.normal(62, 18, n) + 46 * stress, 8, 240), 1)
    at["inventory_days"] = np.round(
        np.clip(rng.normal(48, 22, n) + 26 * stress, 0, 220), 1)
    at["payable_days"] = np.round(
        np.clip(rng.normal(52, 16, n) + 58 * stress, 8, 260), 1)
    daily = at["revenue"] / 365.0
    at["receivables"] = np.round(daily * at["receivable_days"], 3)
    at["inventory"] = np.round(daily * at["inventory_days"] * 0.72, 3)
    at["payables"] = np.round(daily * at["payable_days"] * 0.68, 3)
    at["working_capital"] = np.round(
        at["receivables"] + at["inventory"] - at["payables"], 3)
    at["cash_conversion_cycle_days"] = np.round(
        at["receivable_days"] + at["inventory_days"] - at["payable_days"], 1)

    # Cash. The single number the Early Warning box said it could not see.
    months = np.clip(rng.normal(2.6, 1.1, n) * (1 - 0.62 * stress), 0.05, 9.0)
    monthly_cost = np.maximum(at["revenue"] / 12.0 * 0.86, 0.01)
    at["cash"] = np.round(monthly_cost * months, 3)
    at["cash_months_of_cost"] = np.round(months, 2)

    # Debt. Short-term debt is what makes a liquidity position urgent.
    short_share = np.clip(rng.normal(0.34, 0.13, n) + 0.20 * stress, 0.05, 0.92)
    at["short_term_debt"] = np.round(exposure * short_share, 3)
    at["long_term_debt"] = np.round(exposure - at["short_term_debt"], 3)

    # The maturity ladder, front-loaded under stress: a borrower in trouble is
    # a borrower whose lenders have stopped lending long.
    front = np.clip(0.16 + 0.30 * stress + rng.normal(0, 0.05, n), 0.03, 0.72)
    at["maturity_0_3m"] = np.round(exposure * front * 0.34, 3)
    at["maturity_3_6m"] = np.round(exposure * front * 0.30, 3)
    at["maturity_6_12m"] = np.round(exposure * front * 0.36, 3)
    rest = exposure - (at["maturity_0_3m"] + at["maturity_3_6m"]
                       + at["maturity_6_12m"])
    at["maturity_1_2y"] = np.round(np.maximum(rest * 0.46, 0.0), 3)
    at["maturity_beyond_2y"] = np.round(np.maximum(rest * 0.54, 0.0), 3)

    # Debt service due in the quarter.
    at["interest_due"] = np.round(exposure * rng.uniform(0.011, 0.021, n), 3)
    at["principal_due"] = np.round(at["maturity_0_3m"] * 0.62, 3)
    at["debt_service_due"] = np.round(
        at["interest_due"] + at["principal_due"], 3)

    # Committed and undrawn. `undrawn` from the book is the facility headroom;
    # only part of it is contractually committed, and the uncommitted part is
    # exactly what disappears when a borrower needs it.
    committed_share = np.clip(rng.normal(0.72, 0.14, n) - 0.22 * stress,
                              0.12, 0.98)
    at["committed_limit"] = np.round(
        at["limit_amount"].to_numpy(dtype=float) * committed_share, 3)
    at["drawn_amount"] = np.round(exposure, 3)
    at["undrawn_committed_amount"] = np.round(
        np.maximum(at["committed_limit"] - at["drawn_amount"], 0.0), 3)
    at["undrawn_uncommitted_amount"] = np.round(
        np.maximum(at["undrawn"].to_numpy(dtype=float)
                   - at["undrawn_committed_amount"], 0.0), 3)

    # The buffer, and how long it lasts. This is the headline figure of the
    # whole domain: cash plus committed headroom against what is due.
    at["liquidity_buffer"] = np.round(
        at["cash"] + at["undrawn_committed_amount"], 3)
    quarterly_need = np.maximum(
        at["debt_service_due"] + np.maximum(-at["free_cash_flow"], 0.0), 0.01)
    at["liquidity_coverage_months"] = np.round(
        np.clip(at["liquidity_buffer"] / quarterly_need * 3.0, 0.0, 60.0), 2)

    # What has to be refinanced inside a year and cannot be met from cash.
    due_12m = (at["maturity_0_3m"] + at["maturity_3_6m"]
               + at["maturity_6_12m"])
    at["refinancing_requirement"] = np.round(
        np.maximum(due_12m - at["cash"]
                   - np.maximum(at["free_cash_flow"], 0.0) * 4.0, 0.0), 3)
    at["refinancing_risk_band"] = pd.cut(
        at["refinancing_requirement"] / np.maximum(exposure, 0.01),
        bins=[-0.01, 0.05, 0.20, 0.40, 10.0],
        labels=["Low", "Moderate", "Elevated", "High"]).astype(str)
    return at


def _facility_level(facility: pd.DataFrame, position: pd.DataFrame,
                    rng: np.random.Generator) -> pd.DataFrame:
    """The account-grain view, allocated from the borrower's position.

    Allocated by share of exposure rather than drawn independently, so the
    facility rows sum back to the borrower row. A domain whose parts do not
    add up to its own total is worse than no domain.
    """
    keep = ["customer_id", "account_id", "period", "product_type", "exposure",
            "limit_amount", "undrawn", "utilisation_pct"]
    book = facility[[c for c in keep if c in facility.columns]].copy()
    total = book.groupby(["customer_id", "period"], observed=True)[
        "exposure"].transform("sum")
    book["share"] = book["exposure"] / total.replace(0, np.nan)
    book["share"] = book["share"].fillna(0.0)

    merged = book.merge(
        position[["customer_id", "period", "committed_limit",
                  "undrawn_committed_amount", "maturity_0_3m",
                  "maturity_3_6m", "maturity_6_12m", "maturity_1_2y",
                  "maturity_beyond_2y", "interest_due", "principal_due",
                  "short_term_debt", "long_term_debt"]],
        on=["customer_id", "period"], how="left")
    for column in ("committed_limit", "undrawn_committed_amount",
                   "maturity_0_3m", "maturity_3_6m", "maturity_6_12m",
                   "maturity_1_2y", "maturity_beyond_2y", "interest_due",
                   "principal_due", "short_term_debt", "long_term_debt"):
        merged[column] = np.round(
            merged[column].fillna(0.0) * merged["share"], 3)
    merged["drawn_amount"] = np.round(merged["exposure"], 3)
    merged["committed_flag"] = merged["committed_limit"] > 0
    merged["facility_type"] = merged.get(
        "product_type", pd.Series(["Term Loan"] * len(merged)))
    del rng
    return merged


# ------------------------------------------------------------ the datasets


def build(facility: pd.DataFrame,
          rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    """The fourteen liquidity datasets, all from one position."""
    position = _position(facility, rng)
    accounts = _facility_level(facility, position, rng)

    def take(*columns: str, frame: pd.DataFrame | None = None) -> pd.DataFrame:
        source = position if frame is None else frame
        wanted = [c for c in columns if c in source.columns]
        return source[wanted].copy()

    return {
        "borrower_cash_flow": take(
            "customer_id", "period", "sector", "region", "revenue",
            "operating_cash_flow", "capex", "free_cash_flow", "cash",
            "cash_months_of_cost"),
        "working_capital_position": take(
            "customer_id", "period", "sector", "receivables", "inventory",
            "payables", "working_capital", "receivable_days",
            "inventory_days", "payable_days", "cash_conversion_cycle_days"),
        "receivables_ageing": _ageing(position, rng),
        "inventory_position": take(
            "customer_id", "period", "sector", "inventory", "inventory_days",
            "revenue"),
        "payables_position": take(
            "customer_id", "period", "sector", "payables", "payable_days",
            "revenue"),
        "capital_expenditure": take(
            "customer_id", "period", "sector", "capex", "revenue",
            "operating_cash_flow", "free_cash_flow"),
        "debt_maturity_schedule": take(
            "customer_id", "account_id", "period", "facility_type",
            "maturity_0_3m", "maturity_3_6m", "maturity_6_12m",
            "maturity_1_2y", "maturity_beyond_2y", "drawn_amount",
            frame=accounts),
        "refinancing_profile": take(
            "customer_id", "period", "sector", "refinancing_requirement",
            "refinancing_risk_band", "maturity_0_3m", "maturity_3_6m",
            "maturity_6_12m", "cash", "free_cash_flow"),
        "committed_facilities": take(
            "customer_id", "account_id", "period", "facility_type",
            "committed_limit", "drawn_amount", "undrawn_committed_amount",
            "committed_flag", frame=accounts),
        "undrawn_availability": take(
            "customer_id", "period", "sector", "committed_limit",
            "drawn_amount", "undrawn_committed_amount",
            "undrawn_uncommitted_amount"),
        "liquidity_buffer": take(
            "customer_id", "period", "sector", "cash",
            "undrawn_committed_amount", "liquidity_buffer",
            "liquidity_coverage_months", "debt_service_due"),
        "cash_balance_history": take(
            "customer_id", "period", "sector", "cash", "cash_months_of_cost",
            "operating_cash_flow"),
        "short_term_debt": take(
            "customer_id", "period", "sector", "short_term_debt",
            "long_term_debt", "cash", "maturity_0_3m", "maturity_3_6m",
            "maturity_6_12m"),
        "debt_service_schedule": take(
            "customer_id", "account_id", "period", "facility_type",
            "interest_due", "principal_due", "drawn_amount", frame=accounts),
    }


def _ageing(position: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Receivables split into ageing buckets that sum to the balance.

    The split is driven by the borrower's own receivable days, so a company
    collecting in forty days has almost nothing past ninety and one collecting
    in a hundred and eighty has most of its book there. Drawing the buckets
    independently would let the ageing contradict the days.
    """
    out = position[["customer_id", "period", "sector", "receivables",
                    "receivable_days"]].copy()
    days = out["receivable_days"].to_numpy(dtype=float)
    lateness = np.clip((days - 45.0) / 150.0, 0.0, 1.0)
    jitter = rng.normal(0, 0.03, len(out))
    current = np.clip(0.74 - 0.58 * lateness + jitter, 0.04, 0.97)
    b30 = np.clip((1 - current) * 0.42, 0.0, 1.0)
    b60 = np.clip((1 - current) * 0.27, 0.0, 1.0)
    b90 = np.clip((1 - current) * 0.17, 0.0, 1.0)
    over = np.clip(1 - current - b30 - b60 - b90, 0.0, 1.0)
    balance = out["receivables"].to_numpy(dtype=float)
    out["current_amount"] = np.round(balance * current, 3)
    out["past_due_1_30"] = np.round(balance * b30, 3)
    out["past_due_31_60"] = np.round(balance * b60, 3)
    out["past_due_61_90"] = np.round(balance * b90, 3)
    out["past_due_over_90"] = np.round(balance * over, 3)
    out["past_due_share_pct"] = np.round((1 - current) * 100.0, 2)
    return out


#: What each dataset IS, in the terms the catalogue uses:
#: (catalogue domain, business name, purpose, grain, primary keys, owner).
DOMAINS: dict[str, tuple[str, str, str, str, list[str], str]] = {
    "borrower_cash_flow": (
        "Liquidity and Cash Flow", "Borrower Cash Flow",
        "Revenue, operating cash flow, capital expenditure and the free cash "
        "left over, per borrower per quarter, with the cash balance and how "
        "many months of operating cost it covers.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Treasury and Credit Risk"),
    "working_capital_position": (
        "Liquidity and Cash Flow", "Working Capital Position",
        "Receivables, inventory and payables with the days behind each, and "
        "the cash conversion cycle they add up to. A stretching cycle is the "
        "earliest liquidity signal a lender can see.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Credit Risk Analytics"),
    "receivables_ageing": (
        "Liquidity and Cash Flow", "Receivables Ageing",
        "The receivables balance split into current and past-due buckets, "
        "summing exactly to the balance in the working-capital position.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Credit Risk Analytics"),
    "inventory_position": (
        "Liquidity and Cash Flow", "Inventory Position",
        "Inventory held and the days it represents against revenue.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Credit Risk Analytics"),
    "payables_position": (
        "Liquidity and Cash Flow", "Payables Position",
        "Trade payables and the days behind them. A borrower short of cash "
        "pays its suppliers late before it tells its bank.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Credit Risk Analytics"),
    "capital_expenditure": (
        "Liquidity and Cash Flow", "Capital Expenditure",
        "Capex against revenue and operating cash flow. Capex is cut first "
        "when cash is short, which is what makes a falling line a warning "
        "rather than a sign of discipline.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Treasury and Credit Risk"),
    "debt_maturity_schedule": (
        "Liquidity and Cash Flow", "Debt Maturity Schedule",
        "What falls due and when, per facility: inside three months, three to "
        "six, six to twelve, one to two years, and beyond.",
        "One row per facility per reporting period.",
        ["period", "account_id"], "Treasury"),
    "refinancing_profile": (
        "Liquidity and Cash Flow", "Refinancing Profile",
        "What has to be refinanced inside twelve months and cannot be met "
        "from cash or free cash flow, with the risk band it falls into.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Treasury"),
    "committed_facilities": (
        "Liquidity and Cash Flow", "Committed Facilities",
        "The contractually committed limit behind each facility, what is "
        "drawn against it, and what committed headroom remains.",
        "One row per facility per reporting period.",
        ["period", "account_id"], "Credit Administration"),
    "undrawn_availability": (
        "Liquidity and Cash Flow", "Undrawn Availability",
        "Committed and uncommitted headroom, kept apart. Uncommitted "
        "headroom is exactly what disappears when a borrower needs it.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Treasury"),
    "liquidity_buffer": (
        "Liquidity and Cash Flow", "Liquidity Buffer",
        "Cash plus committed headroom against what is due — the headline "
        "figure of the domain — and how many months it covers.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Treasury and Credit Risk"),
    "cash_balance_history": (
        "Liquidity and Cash Flow", "Cash Balance History",
        "The cash balance quarter by quarter, with the operating cash flow "
        "that moved it.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Treasury"),
    "short_term_debt": (
        "Liquidity and Cash Flow", "Short-Term Debt",
        "Debt splitting short from long, against cash and the near maturity "
        "ladder. Short-term debt is what makes a liquidity position urgent.",
        "One row per borrower per reporting period.",
        ["period", "customer_id"], "Treasury"),
    "debt_service_schedule": (
        "Liquidity and Cash Flow", "Debt Service Schedule",
        "Interest and principal falling due in the quarter, per facility.",
        "One row per facility per reporting period.",
        ["period", "account_id"], "Treasury"),
}


__all__ = ["DOMAINS", "UNIT", "build"]
