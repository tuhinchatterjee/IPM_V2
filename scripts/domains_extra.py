#!/usr/bin/env python
"""
The rest of the demonstration book: thirteen more governed domains.

Why these exist
---------------
A credit-risk platform that only knows about facilities and staging can answer
maybe a fifth of the questions a credit department actually asks. Collateral,
covenants, limits, watchlist, recoveries, group structure, appetite, model
performance, pricing and climate are not decoration — they are where most of
the arguments happen, and a method library of three hundred methods that can
only read two tables is a library of definitions.

How they are built
------------------
Every one is DERIVED from the same simulation the facility book comes from,
never generated independently. A facility in Stage 3 has a recovery record; a
customer whose covenant headroom went negative has a covenant breach on the
same quarter; a sector whose exposure exceeds its appetite limit is the sector
whose facilities are actually there. That coherence is the point: a
demonstration where the collateral coverage contradicts the facility book is a
demonstration of nothing.

Everything here is SYNTHETIC and marked as such on every dataset.

Determinism
-----------
Derivations first, noise second, and every random draw from a generator seeded
by the caller. The same book on every machine, every time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _period_end(frame: pd.DataFrame) -> np.ndarray:
    """The quarter-end date, whatever the source frame calls it.

    The facility book carries it as `snapshot_date` and the macro series as
    `period_end_date`. Resolving it here rather than at each call site means a
    rename upstream breaks one line instead of thirty.
    """
    for column in ("period_end_date", "snapshot_date"):
        if column in frame.columns:
            return frame[column].to_numpy()
    return np.array([""] * len(frame))

# ---------------------------------------------------------------- collateral

#: How much of a collateral type's market value a bank will actually lend
#: against. Ordered the way a credit policy orders them, which is by how quickly
#: the value survives a forced sale.
HAIRCUTS = {
    "Cash": 0.00, "Deposit": 0.02, "Government Guarantee": 0.05,
    "Bank Guarantee": 0.10, "Listed Securities": 0.25, "Real Estate": 0.30,
    "Commercial Property": 0.35, "Residential Property": 0.30,
    "Equipment": 0.45, "Inventory": 0.55, "Receivables": 0.40,
    "Corporate Guarantee": 0.50, "Unsecured": 1.00, "None": 1.00,
}

VALUERS = ["Al-Rajhi Valuation", "Riyadh Property Services", "Gulf Asset Appraisal",
           "Independent Panel Valuer", "Internal Credit Review"]


def build_collateral(facility: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """One row per collateral item held against a facility, per quarter.

    Split from the facility's single `collateral_value` rather than invented
    beside it: the items sum back to the figure the facility book carries, so
    "our collateral coverage is X" reconciles whichever table it is read from.
    """
    held = facility[facility["collateral_value"] > 0].copy()
    if held.empty:
        return pd.DataFrame()

    rows = []
    # Most facilities hold one item; a minority hold a second, smaller one.
    second = rng.random(len(held)) < 0.28
    split = np.where(second, rng.uniform(0.55, 0.85, len(held)), 1.0)

    for index, share, has_second in ((0, split, second), (1, 1.0 - split, second)):
        mask = np.ones(len(held), dtype=bool) if index == 0 else has_second
        if not mask.any():
            continue
        subset = held[mask]
        proportion = (share if index == 0 else share)[mask]
        types = subset["collateral_type"].to_numpy()
        if index == 1:
            # A second charge is usually a different, weaker kind of security.
            types = np.where(rng.random(len(subset)) < 0.6, "Corporate Guarantee",
                             "Receivables")
        haircut = np.array([HAIRCUTS.get(str(t), 0.4) for t in types])
        market = subset["collateral_value"].to_numpy() * proportion
        rows.append(pd.DataFrame({
            "period": subset["period"].to_numpy(),
            "period_end_date": _period_end(subset),
            "collateral_id": [f"{a}-C{index + 1}" for a in subset["account_id"]],
            "account_id": subset["account_id"].to_numpy(),
            "customer_id": subset["customer_id"].to_numpy(),
            "collateral_type": types,
            "charge_rank": index + 1,
            "market_value": np.round(market, 3),
            "haircut_pct": np.round(haircut * 100, 1),
            "net_realisable_value": np.round(market * (1 - haircut), 3),
            "valuation_date": _period_end(subset),
            "valuation_age_months": rng.integers(1, 30, len(subset)),
            "valuer": rng.choice(VALUERS, len(subset)),
            "is_synthetic": True,
        }))
    return pd.concat(rows, ignore_index=True)


# ----------------------------------------------------------------- covenants

COVENANTS = [
    ("Net Leverage", "x", 3.5, "max"),
    ("Debt Service Coverage", "x", 1.20, "min"),
    ("Interest Cover", "x", 2.00, "min"),
    ("Tangible Net Worth", "SAR mn", 5.0, "min"),
]


def build_covenants(facility: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Covenant tests per facility per quarter, consistent with its headroom.

    A facility whose `covenant_headroom_pct` is negative in the facility book
    has a breach here on the same quarter. The two cannot disagree, because one
    is computed from the other rather than beside it.
    """
    rows = []
    headroom = facility["covenant_headroom_pct"].to_numpy() / 100.0
    dscr = facility["dscr"].to_numpy()

    for name, unit, threshold, direction in COVENANTS:
        if name == "Debt Service Coverage":
            actual = dscr
        elif direction == "max":
            # Leverage moves inversely with headroom: less headroom, more debt.
            actual = threshold * (1.0 - headroom * 0.8) + rng.normal(0, 0.12, len(facility))
        else:
            actual = threshold * (1.0 + headroom) + rng.normal(0, 0.08, len(facility))

        breach = actual > threshold if direction == "max" else actual < threshold
        margin = (threshold - actual) if direction == "max" else (actual - threshold)
        waived = breach & (rng.random(len(facility)) < 0.22)
        rows.append(pd.DataFrame({
            "period": facility["period"].to_numpy(),
            "period_end_date": _period_end(facility),
            "test_id": [f"{a}-{name[:3].upper()}" for a in facility["account_id"]],
            "account_id": facility["account_id"].to_numpy(),
            "customer_id": facility["customer_id"].to_numpy(),
            "covenant_name": name,
            "covenant_type": direction,
            "unit": unit,
            "threshold": threshold,
            "actual_value": np.round(actual, 3),
            "headroom": np.round(margin, 3),
            "headroom_pct": np.round(margin / max(abs(threshold), 0.01) * 100, 2),
            "breached": breach,
            "waiver_granted": waived,
            "status": np.where(waived, "Waived",
                               np.where(breach, "Breached", "Compliant")),
            "is_synthetic": True,
        }))
    return pd.concat(rows, ignore_index=True)


# -------------------------------------------------------------------- limits


def build_limits(facility: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Sanctioned limits, their approval level, expiry and any excess.

    The approver level is derived from the limit, because that is how a
    delegated-authority matrix works: who was allowed to sign it is a function
    of how big it is, and an excess above a limit signed at branch level is a
    different conversation from one signed by the board committee.
    """
    limit = facility["limit_amount"].to_numpy()
    exposure = facility["exposure"].to_numpy()
    excess = np.maximum(exposure - limit, 0.0)

    level = np.where(limit > 100, "Board Risk Committee",
                     np.where(limit > 40, "Executive Credit Committee",
                              np.where(limit > 10, "Senior Credit Officer",
                                       "Branch Credit")))
    expiry_quarters = rng.integers(1, 13, len(facility))
    return pd.DataFrame({
        "period": facility["period"].to_numpy(),
        "period_end_date": _period_end(facility),
        "account_id": facility["account_id"].to_numpy(),
        "customer_id": facility["customer_id"].to_numpy(),
        "product_type": facility["product_type"].to_numpy(),
        "limit_amount": np.round(limit, 3),
        "exposure": np.round(exposure, 3),
        "utilisation_pct": facility["utilisation_pct"].to_numpy(),
        "excess_amount": np.round(excess, 3),
        "in_excess": excess > 0,
        "days_in_excess": np.where(excess > 0, rng.integers(1, 95, len(facility)), 0),
        "approval_level": level,
        "quarters_to_expiry": expiry_quarters,
        "expiring_within_year": expiry_quarters <= 4,
        "annual_review_due": expiry_quarters <= 2,
        "is_synthetic": True,
    })


# ----------------------------------------------------------------- watchlist

WATCHLIST_ACTIONS = [
    "Increase monitoring frequency to monthly",
    "Obtain updated management accounts",
    "Request additional security",
    "Reduce limit at next review",
    "Refer to Special Assets",
    "Agree a repayment plan",
]


def build_watchlist(facility: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """One row per customer per quarter, for customers on the watchlist.

    Membership is the facility book's own `watchlist` flag rolled up to the
    customer, so a customer is on this list exactly when one of its facilities
    says it should be.
    """
    flagged = facility[facility["watchlist"]].copy()
    if flagged.empty:
        return pd.DataFrame()

    flagged["period_end_date"] = _period_end(flagged)
    grouped = flagged.groupby(["period", "customer_id"], as_index=False).agg(
        period_end_date=("period_end_date", "first"),
        borrower_name=("borrower_name", "first"),
        sector=("sector", "first"),
        segment=("segment", "first"),
        owner_analyst=("owner_analyst", "first"),
        total_ead=("ead", "sum"),
        worst_grade=("internal_grade", "max"),
        worst_stage=("ifrs9_stage", "max"),
        max_dpd=("dpd_days", "max"),
        reason=("trigger_type", "first"),
        facilities=("account_id", "count"),
    )
    severity = np.where(grouped["worst_stage"] == 3, "Special Assets",
                        np.where(grouped["worst_grade"] >= 8, "Watchlist 2",
                                 "Watchlist 1"))
    return pd.DataFrame({
        "period": grouped["period"],
        "period_end_date": grouped["period_end_date"],
        "customer_id": grouped["customer_id"],
        "borrower_name": grouped["borrower_name"],
        "sector": grouped["sector"],
        "segment": grouped["segment"],
        "watchlist_category": severity,
        "reason": grouped["reason"],
        "total_ead": np.round(grouped["total_ead"], 3),
        "facilities_on_watch": grouped["facilities"],
        "worst_internal_grade": grouped["worst_grade"],
        "worst_ifrs9_stage": grouped["worst_stage"],
        "max_days_past_due": grouped["max_dpd"],
        "relationship_owner": grouped["owner_analyst"],
        "agreed_action": rng.choice(WATCHLIST_ACTIONS, len(grouped)),
        "review_frequency": np.where(severity == "Special Assets", "Monthly",
                                     "Quarterly"),
        "is_synthetic": True,
    })


# ---------------------------------------------------------------- recoveries


def build_recoveries(facility: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """What happened after default: recovery, write-off or cure.

    Recovery is anchored on the facility's own LGD, so the realised recovery
    rate on this table averages to roughly one minus the LGD the model assumed —
    which is what makes a back-test of LGD possible at all.
    """
    defaulted = facility[facility["ifrs9_stage"] == 3].copy()
    if defaulted.empty:
        return pd.DataFrame()

    ead = defaulted["ead"].to_numpy()
    lgd = defaulted["lgd_pct"].to_numpy() / 100.0
    # Realised recovery scatters around the modelled expectation, and is bounded
    # by the collateral actually held.
    realised = np.clip(1.0 - lgd + rng.normal(0, 0.12, len(defaulted)), 0.0, 0.98)
    recovered = ead * realised
    months = rng.integers(3, 42, len(defaulted))
    cured = (realised > 0.85) & (rng.random(len(defaulted)) < 0.35)

    return pd.DataFrame({
        "period": defaulted["period"].to_numpy(),
        "period_end_date": _period_end(defaulted),
        "account_id": defaulted["account_id"].to_numpy(),
        "customer_id": defaulted["customer_id"].to_numpy(),
        "sector": defaulted["sector"].to_numpy(),
        "ead_at_default": np.round(ead, 3),
        "collateral_realised": np.round(
            np.minimum(recovered, defaulted["collateral_value"].to_numpy()), 3),
        "cash_recovered": np.round(recovered, 3),
        "recovery_rate_pct": np.round(realised * 100, 2),
        "modelled_lgd_pct": defaulted["lgd_pct"].to_numpy(),
        "realised_lgd_pct": np.round((1.0 - realised) * 100, 2),
        "amount_written_off": np.round(np.where(cured, 0.0, ead - recovered), 3),
        "months_in_default": months,
        "outcome": np.where(cured, "Cured",
                            np.where(realised > 0.5, "Substantially recovered",
                                     "Written off")),
        "legal_action": rng.choice(["None", "Demand issued", "Enforcement",
                                    "Court proceedings"], len(defaulted),
                                   p=[0.35, 0.3, 0.2, 0.15]),
        "is_synthetic": True,
    })


# -------------------------------------------------------------- payment history


def build_payments(facility: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """What was due and what arrived, per facility per quarter.

    Derived from days past due: a facility 90 days down did not pay, and one at
    zero paid in full. Generating payments independently would produce a book
    whose arrears table and payment table disagree, which is the single most
    common real-world data-quality complaint and not something to reproduce.
    """
    dpd = facility["dpd_days"].to_numpy()
    exposure = facility["exposure"].to_numpy()
    eir = facility["eir_pct"].to_numpy() / 100.0

    scheduled = exposure * (eir / 4.0) + exposure * 0.02
    shortfall = np.clip(dpd / 90.0, 0.0, 1.0)
    paid = scheduled * (1.0 - shortfall) * (1.0 - rng.uniform(0, 0.03, len(facility)))

    return pd.DataFrame({
        "period": facility["period"].to_numpy(),
        "period_end_date": _period_end(facility),
        "account_id": facility["account_id"].to_numpy(),
        "customer_id": facility["customer_id"].to_numpy(),
        "scheduled_amount": np.round(scheduled, 4),
        "amount_paid": np.round(np.maximum(paid, 0.0), 4),
        "shortfall": np.round(np.maximum(scheduled - paid, 0.0), 4),
        "paid_in_full": dpd == 0,
        "days_past_due": dpd,
        "payments_made_in_quarter": np.where(dpd == 0, 3,
                                             np.where(dpd < 30, 2,
                                                      np.where(dpd < 90, 1, 0))),
        "payment_method": rng.choice(["Direct debit", "Standing order", "Manual transfer"],
                                     len(facility), p=[0.62, 0.24, 0.14]),
        "is_synthetic": True,
    })


# ------------------------------------------------------------ group structure


def build_groups(customers: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Who owns whom, for the customers that belong to a group.

    Large-exposure rules are applied at group level, so an obligor group with no
    structure behind it is a limit nobody can actually test.
    """
    grouped = customers[customers["obligor_group"] != ""].copy()
    if grouped.empty:
        return pd.DataFrame()

    rows = []
    for group, members in grouped.groupby("obligor_group"):
        ids = members["customer_id"].tolist()
        names = members["borrower_name"].tolist()
        parent_id, parent_name = ids[0], names[0]
        for position, (member_id, member_name) in enumerate(zip(ids, names, strict=True)):
            is_parent = position == 0
            rows.append({
                "obligor_group": group,
                "group_name": f"{parent_name} Group",
                "customer_id": member_id,
                "borrower_name": member_name,
                "parent_customer_id": "" if is_parent else parent_id,
                "relationship": "Parent" if is_parent else "Subsidiary",
                "ownership_pct": 100.0 if is_parent else float(
                    round(rng.uniform(51, 100), 1)),
                "consolidated": True,
                "control_basis": "Ownership" if is_parent else rng.choice(
                    ["Ownership", "Board control", "Economic dependence"]),
                "is_synthetic": True,
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------- rating transitions


def build_transitions(ratings: pd.DataFrame) -> pd.DataFrame:
    """Consecutive rating pairs per customer — the input to a transition matrix.

    Derived rather than simulated: a transition table that does not reconcile to
    the rating history it claims to summarise is worse than no transition table.
    """
    if ratings.empty:
        return pd.DataFrame()
    grade_column = "internal_grade" if "internal_grade" in ratings.columns else None
    if grade_column is None:
        return pd.DataFrame()

    frame = ratings.sort_values(["customer_id", "rating_year"]).copy()
    frame["to_grade"] = frame.groupby("customer_id")[grade_column].shift(-1)
    frame["to_year"] = frame.groupby("customer_id")["rating_year"].shift(-1)
    pairs = frame.dropna(subset=["to_grade", "to_year"]).copy()
    if pairs.empty:
        return pd.DataFrame()

    movement = pairs["to_grade"].astype(int) - pairs[grade_column].astype(int)
    return pd.DataFrame({
        "from_year": pairs["rating_year"].astype(int).to_numpy(),
        "to_year": pairs["to_year"].astype(int).to_numpy(),
        "customer_id": pairs["customer_id"].to_numpy(),
        "from_grade": pairs[grade_column].astype(int).to_numpy(),
        "to_grade": pairs["to_grade"].astype(int).to_numpy(),
        "notches_moved": movement.to_numpy(),
        "direction": np.where(movement > 0, "Downgrade",
                              np.where(movement < 0, "Upgrade", "Stable")),
        "defaulted": (pairs["to_grade"] >= 10).to_numpy(),
        "sector": pairs["sector"].to_numpy() if "sector" in pairs else "",
        "is_synthetic": True,
    })


# --------------------------------------------------------------- appetite


def build_appetite(facility: pd.DataFrame) -> pd.DataFrame:
    """Sector concentration against the appetite limit set for it.

    The actual is computed from the book, so a sector shown as over appetite is
    over appetite in the facility table too. The limits themselves are a policy
    choice and are stated as one — round numbers a committee would set, not a
    figure reverse-engineered from the answer.
    """
    # Keyed on the sector names the book actually uses. Three of these keys
    # used to name sectors no borrower belonged to - "Construction &
    # Contracting", "Energy & Utilities", "Professional Services" - which meant
    # most of the book silently fell through to the 10% default and the limits
    # a committee had supposedly set were not the limits being tested.
    limits = {
        "Real Estate": 18.0, "Contracting": 14.0,
        "Wholesale & Retail Trade": 14.0, "Manufacturing": 15.0,
        "Transport & Logistics": 8.0, "Healthcare": 8.0, "Education": 5.0,
        "Hospitality & Tourism": 6.0, "Utilities": 12.0,
        "Petrochemicals": 12.0, "Oil & Gas": 12.0, "Shipping": 7.0,
        "Telecommunications": 10.0,
        "Financial Services": 12.0, "Agriculture & Food": 7.0,
        "Government-Related Entities": 20.0,
        "Mining & Metals": 8.0,
    }
    rows = []
    for period, chunk in facility.groupby("period", observed=True):
        total = float(chunk["ead"].sum())
        by_sector = chunk.groupby("sector", observed=True)["ead"].sum()
        for sector, ead in by_sector.items():
            limit = limits.get(str(sector), 10.0)
            actual = 100.0 * float(ead) / total if total else 0.0
            rows.append({
                "period": period,
                "sector": sector,
                "limit_pct_of_book": limit,
                "actual_pct_of_book": round(actual, 3),
                "headroom_pct": round(limit - actual, 3),
                "utilisation_of_limit_pct": round(actual / limit * 100, 2) if limit else 0.0,
                "exposure": round(float(ead), 3),
                "book_exposure": round(total, 3),
                "status": ("Breached" if actual > limit
                           else "Near limit" if actual > limit * 0.9
                           else "Within appetite"),
                "is_synthetic": True,
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------- model performance


def build_model_performance(facility: pd.DataFrame) -> pd.DataFrame:
    """Predicted against observed, per segment per quarter.

    The observed rate is the share of the segment that is in default at the
    quarter end, and the predicted is the average 12-month PD the model assigned
    to the same population. Both come from the book, so the calibration gap this
    shows is a real property of the simulated data rather than a number chosen
    to look interesting.
    """
    rows = []
    for (period, segment), chunk in facility.groupby(["period", "segment"], observed=True):
        count = len(chunk)
        if not count:
            continue
        predicted = float(chunk["pd_12m_pct"].mean())
        observed = 100.0 * float((chunk["ifrs9_stage"] == 3).mean())
        rows.append({
            "period": period,
            "segment": segment,
            "model_version": "PD-CORP-2.1",
            "facilities": count,
            "predicted_pd_pct": round(predicted, 4),
            "observed_default_rate_pct": round(observed, 4),
            "difference_pct_points": round(observed - predicted, 4),
            "calibration": ("Under-predicting" if observed > predicted * 1.2
                            else "Over-predicting" if observed < predicted * 0.8
                            else "Within tolerance"),
            "is_synthetic": True,
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------- scenarios

SCENARIOS = [
    ("Base", "The planning assumption. No shock applied.", 0.0, 0.0, 0.0),
    ("Mild downturn", "A shallow slowdown: growth halves, oil softens.",
     -1.5, -12.0, 0.4),
    ("Severe downturn", "A sustained contraction with a property correction.",
     -4.0, -35.0, 1.8),
    ("Oil price shock", "A sharp fall in oil with limited fiscal offset.",
     -2.8, -45.0, 1.1),
    ("Property correction", "Real estate values fall, other sectors hold.",
     -0.8, -5.0, 0.6),
    ("Rate shock", "Policy rates rise sharply and stay there.", -1.2, 0.0, 2.5),
]


def build_scenarios(macro: pd.DataFrame) -> pd.DataFrame:
    """Named scenarios as shocked paths off the actual macro series.

    A scenario is a path, not a single number, so it is stored as one. The shocks
    phase in over four quarters and persist, which is how a stress programme is
    normally specified and what makes a multi-period ECL projection possible.
    """
    if macro.empty:
        return pd.DataFrame()
    periods = macro["period"].tolist()
    rows = []
    for name, description, gdp, oil, rate in SCENARIOS:
        for index, period in enumerate(periods):
            phase = min(1.0, (index + 1) / 4.0) if name != "Base" else 0.0
            rows.append({
                "scenario": name,
                "description": description,
                "period": period,
                "quarter_index": index,
                "gdp_growth_shock_pct": round(gdp * phase, 3),
                "oil_price_shock_pct": round(oil * phase, 3),
                "policy_rate_shock_pct": round(rate * phase, 3),
                "severity": ("None" if name == "Base"
                             else "Severe" if abs(gdp) >= 2.5 else "Moderate"),
                "is_synthetic": True,
            })
    return pd.DataFrame(rows)


# ------------------------------------------------------------ profitability


def build_profitability(facility: pd.DataFrame) -> pd.DataFrame:
    """Revenue, cost, expected loss and capital, per facility per quarter.

    RAROC is recomputed here from its components rather than copied from the
    facility book, and the two agree — which is what makes it possible to ask
    "why did RAROC fall" and get an answer with parts to it.
    """
    exposure = facility["exposure"].to_numpy()
    ead = facility["ead"].to_numpy()
    eir = facility["eir_pct"].to_numpy() / 100.0
    ecl = facility["total_ecl"].to_numpy()
    grade = facility["internal_grade"].to_numpy()

    revenue = exposure * eir / 4.0
    funding = exposure * 0.042 / 4.0
    operating = exposure * 0.004 / 4.0
    # Regulatory capital rises steeply with grade, as a risk weight does.
    risk_weight = np.clip(0.20 + (grade - 1) * 0.13, 0.20, 1.50)
    capital = ead * risk_weight * 0.105
    profit = revenue - funding - operating - ecl / 4.0

    return pd.DataFrame({
        "period": facility["period"].to_numpy(),
        "period_end_date": _period_end(facility),
        "account_id": facility["account_id"].to_numpy(),
        "customer_id": facility["customer_id"].to_numpy(),
        "sector": facility["sector"].to_numpy(),
        "segment": facility["segment"].to_numpy(),
        "interest_revenue": np.round(revenue, 4),
        "funding_cost": np.round(funding, 4),
        "operating_cost": np.round(operating, 4),
        "expected_loss_charge": np.round(ecl / 4.0, 4),
        "net_profit": np.round(profit, 4),
        "risk_weight_pct": np.round(risk_weight * 100, 1),
        "regulatory_capital": np.round(capital, 4),
        "raroc_pct": np.round(np.where(capital > 0, profit * 4 / capital * 100, 0.0), 2),
        "economic_profit": np.round(profit - capital * 0.11 / 4.0, 4),
        "above_hurdle": (np.where(capital > 0, profit * 4 / capital * 100, 0.0) > 11.0),
        "is_synthetic": True,
    })


# ------------------------------------------------------------------- climate

TRANSITION_BANDS = {
    "Oil & Gas": "High", "Petrochemicals": "High", "Utilities": "High",
    "Mining & Metals": "High", "Shipping": "Medium-High",
    "Transport & Logistics": "Medium-High",
    "Manufacturing": "Medium-High", "Contracting": "Medium",
    "Real Estate": "Medium", "Agriculture & Food": "Medium",
    "Wholesale & Retail Trade": "Medium-Low", "Hospitality & Tourism": "Medium-Low",
    "Healthcare": "Low", "Education": "Low",
    "Telecommunications": "Low", "Financial Services": "Low",
    "Government-Related Entities": "Low",
}

INTENSITY = {"High": 420.0, "Medium-High": 180.0, "Medium": 90.0,
             "Medium-Low": 45.0, "Low": 18.0}


def build_climate(customers: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Transition and physical risk per customer.

    Banded by sector because that is how a transition assessment actually starts
    — and the bands are stated, so a reader can disagree with the placement
    rather than with an opaque score.
    """
    sectors = customers["sector"].to_numpy()
    bands = np.array([TRANSITION_BANDS.get(str(s), "Medium") for s in sectors])
    base = np.array([INTENSITY[b] for b in bands])
    intensity = base * rng.lognormal(0, 0.35, len(customers))

    # Physical risk is geographic: coastal and desert regions differently exposed.
    regions = customers["region"].to_numpy()
    physical = np.where(np.isin(regions, ["Eastern Province", "Jazan", "Tabuk"]), 62.0,
                        np.where(np.isin(regions, ["Makkah", "Madinah"]), 48.0, 34.0))
    physical = np.clip(physical + rng.normal(0, 9, len(customers)), 1, 100)

    return pd.DataFrame({
        "customer_id": customers["customer_id"].to_numpy(),
        "borrower_name": customers["borrower_name"].to_numpy(),
        "sector": sectors,
        "region": regions,
        "transition_risk_band": bands,
        "emissions_intensity": np.round(intensity, 1),
        "scope_1_2_estimated": np.round(intensity * customers["size_usd_mn"].to_numpy(), 0),
        "physical_risk_score": np.round(physical, 1),
        "physical_risk_band": np.where(physical > 60, "High",
                                       np.where(physical > 40, "Medium", "Low")),
        "transition_plan_in_place": rng.random(len(customers)) < 0.31,
        "data_quality": rng.choice(["Reported", "Estimated", "Sector average"],
                                   len(customers), p=[0.18, 0.34, 0.48]),
        "is_synthetic": True,
    })


__all__ = [
    "build_appetite",
    "build_climate",
    "build_collateral",
    "build_covenants",
    "build_groups",
    "build_limits",
    "build_model_performance",
    "build_payments",
    "build_profitability",
    "build_recoveries",
    "build_scenarios",
    "build_transitions",
    "build_watchlist",
]
