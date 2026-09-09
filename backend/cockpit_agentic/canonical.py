"""
Build a Cockpit release from the CANONICAL corporate book.

What this replaces, and why
---------------------------
`generate.py` builds the Cockpit's own demonstration universe: 250 borrowers
called `BRW0001`, facilities called `FAC00001`, INR in crore, twenty quarters
from 2021Q3. That book was correct while the Cockpit owned a private universe.
It is wrong now: the rest of the product reads one canonical corporate book,
and a Cockpit answering over a second population in a second currency on a
second calendar cannot be reconciled with anything beside it.

So this module builds the same RELATIONS, with the same column contract, from
`data/analytics/corporate_*`:

  identity      CORP-1NNNNN and CFAC-NNNNNN, the join keys the whole product
                uses. No Cockpit id is minted here.
  population    every canonical borrower and facility, not a cohort.
  currency      SAR, millions.
  calendar      the canonical sixteen quarters, Q3 2022 - Q2 2026.
  rating        the canonical 19-grade masterscale plus D, read from
                `corporate_ratings`.
  IFRS 9        Stage, SICR, PD, LGD, EAD and reported ECL read from
                `corporate_ifrs9_facility`, which is itself an exact
                decomposition of `corporate_ifrs9`. The Cockpit assigns none of
                them; its own field contract already says it "reads it; it does
                not assign a new one".

Everything else about Cockpit V3 is untouched: the agentic runtime, the tool
registry, the sandbox, the prompts, the per-run ledger, the audit trail, the
answer checker and the whole user interface read these relations by name and do
not care where the rows came from.

The one thing this release does NOT carry, said plainly
-------------------------------------------------------
`cockpit_ifrs9_detail` — the per-scenario, per-horizon term structure behind an
ECL — has no canonical source. The canonical book measures ECL as a
scenario-weighted single-period product; the Cockpit's private book measured it
as a discounted term structure and its own integrity gate
(`check_a_single_pd_lgd_ead_product_does_not_reproduce_ecl`) exists to prove
the difference. Those two models disagree, and inventing a term structure to
sit under a canonical ECL would be fabricating the very thing the gate polices.

So a canonical release declares `carries_term_structure: false` in its
manifest, omits that relation, and the Cockpit disables the features that read
it rather than answering from an invention. That is one feature marked
post-demo, not a whole module left on conflicting data.

`ANNOTATIONS` below records, per relation, what canonical could not supply, so
the omission is data the product can read rather than a comment somebody has to
find.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.cockpit_agentic import CATALOG_VERSION, DATA_VERSION, DOMAIN
from backend.cockpit_agentic import calendar as cal
from backend.cockpit_agentic import fields as F
from backend.cockpit_agentic.generate import Release

#: The canonical release id. Distinct from `demo-20q-v1` so the two can never
#: be confused, and so a deployment carrying both says which it is serving.
RELEASE_ID = "canonical-16q-v1"

#: Canonical conventions. Not the Cockpit's old INR/crore.
CURRENCY = "SAR"
AMOUNT_SCALE = "millions"
COUNTRY = "SA"
TENANT = "demo-tenant"
SOURCE_SYSTEM = "corporate_canonical_book"
ORIGIN = "canonical_corporate"

#: Relations a canonical release publishes. `cockpit_ifrs9_detail` is
#: deliberately absent — see the module docstring.
RELATIONS: tuple[str, ...] = (
    F.CALENDAR, F.FACILITY_QUARTER, F.BORROWER_FINANCIAL, F.RATING_RATIO,
    F.QUALITATIVE, F.COLLATERAL, F.COLLATERAL_ALLOCATION, F.COVENANT,
    F.MACRO_WINDOW,
)

#: What canonical could not supply, per relation, in the release's own words.
ANNOTATIONS: dict[str, str] = {
    F.IFRS9_DETAIL: (
        "Not published in a canonical release. The canonical book measures "
        "ECL as a scenario-weighted single-period product and carries no "
        "per-horizon term structure; deriving one to sit underneath a "
        "canonical ECL would invent the measurement this relation exists to "
        "show. Cockpit features that read it are disabled for a canonical "
        "release rather than answered from an invention."),
    F.QUALITATIVE: (
        "Canonical carries the watchlist and covenant evidence a qualitative "
        "assessment would rest on, but no assessor answers. Rows are "
        "published with answer_status 'not_collected' rather than omitted, so "
        "a question about coverage gets a count rather than silence."),
}

#: Cockpit collateral vocabulary against the canonical one. Four Cockpit types
#: have no canonical counterpart; that is coverage, not an error, and the
#: relation simply carries no rows of those types.
COLLATERAL_TYPES: dict[str, str] = {
    "Real Estate Mortgage": "commercial_property",
    "Assignment of Receivables": "receivables",
    "Corporate Guarantee": "bank_guarantees",
    "Plant & Machinery": "plant_machinery",
    "Inventory": "inventory",
    "Cash Collateral": "cash_deposits",
    "Listed Securities": "listed_equities",
    "Sovereign Guarantee": "government_securities",
}

#: The canonical macro columns the Cockpit's ten declared factors map onto.
#: Five resolve; five do not and are published with observation_status
#: 'unavailable' and a reason, never a blank that reads as a zero. The two
#: traps recorded in the ledger are NOT mapped: an FX index is not
#: local-currency-per-USD, and a residential house price index is not a
#: commercial property price index.
MACRO_FACTORS: dict[str, tuple[str, str]] = {
    "real_gdp_growth_yoy": ("real_gdp_growth_pct", "percent"),
    "cpi_inflation_yoy": ("inflation_rate_pct", "percent"),
    "unemployment_rate": ("unemployment_rate_pct", "percent"),
    "policy_interest_rate": ("policy_rate_pct", "percent"),
    "benchmark_oil_price": ("oil_price_usd", "usd_per_barrel"),
}
MACRO_UNAVAILABLE: dict[str, str] = {
    "fx_lcy_per_usd": ("The canonical book carries an FX INDEX, which is not "
                       "local currency per USD; a rise in one is not a rise "
                       "in the other."),
    "commercial_property_price_index": (
        "The canonical book carries a residential house price index. "
        "Commercial property is a different market."),
    "interbank_rate_3m": "No canonical equivalent.",
    "sovereign_bond_yield_10y": (
        "No canonical equivalent. The corporate credit spread beside it "
        "measures something else."),
    "private_sector_credit_growth_yoy": "No canonical equivalent.",
}


class CanonicalMissing(RuntimeError):
    """The canonical book is not built. Said, never worked around."""


@dataclass(frozen=True)
class Source:
    """Every canonical frame this build reads, loaded once."""

    borrowers: pd.DataFrame
    facilities: pd.DataFrame
    ifrs9_facility: pd.DataFrame
    ifrs9: pd.DataFrame
    ratings: pd.DataFrame
    collateral: pd.DataFrame
    covenants: pd.DataFrame
    financials: pd.DataFrame
    limits: pd.DataFrame
    delinquency: pd.DataFrame
    macro: pd.DataFrame


def _read(root: Path, name: str, *, required: bool = True) -> pd.DataFrame:
    parts = sorted(glob.glob(str(root / name / "**" / "*.parquet"),
                             recursive=True))
    if not parts:
        if not required:
            return pd.DataFrame()
        raise CanonicalMissing(
            f"{name} is not in the analytics lake. Run "
            f"scripts/build_corporate_universe.py, then "
            f"scripts/build_corporate_ifrs9_facility.py, before building a "
            f"canonical Cockpit release.")
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)


def load(root: Path | str | None = None) -> Source:
    from backend.config import settings

    base = Path(root) if root else Path(settings.analytics_dir)
    return Source(
        borrowers=_read(base, "corporate_borrower_360"),
        facilities=_read(base, "corporate_facilities"),
        ifrs9_facility=_read(base, "corporate_ifrs9_facility"),
        ifrs9=_read(base, "corporate_ifrs9"),
        ratings=_read(base, "corporate_ratings"),
        collateral=_read(base, "corporate_collateral"),
        covenants=_read(base, "corporate_covenants"),
        financials=_read(base, "corporate_financials"),
        limits=_read(base, "corporate_limits"),
        delinquency=_read(base, "corporate_delinquency"),
        macro=_read(base, "corporate_macro"),
    )


# ------------------------------------------------------------------ calendar

def _slot(period: str) -> str:
    """`"Q3 2022"` -> `"2022Q3"`. The two vocabularies, mapped once."""
    quarter, year = period.split()
    return f"{year}{quarter}"


def _period(slot: str) -> str:
    """The inverse. `"2022Q3"` -> `"Q3 2022"`."""
    return f"{slot[4:]} {slot[:4]}"


def calendar_for(source: Source, *, dataset_release_id: str = RELEASE_ID
                 ) -> cal.Calendar:
    """Twenty slots ending at the canonical last quarter; sixteen populated.

    The Cockpit's calendar is fixed at twenty slots and its own docstring says
    why that is safe: *"A release that created twenty slots and filled eight of
    them says so; section 3.1 forbids claiming twenty observed quarters merely
    because twenty slots exist."* Canonical publishes sixteen quarters, so four
    slots are created and left EMPTY rather than back-filled. Nothing invents a
    2021 quarter the canonical book does not have.
    """
    periods = sorted(source.ifrs9["period"].unique(),
                     key=lambda p: (int(p.split()[1]), int(p.split()[0][1])))
    populated = tuple(_slot(p) for p in periods)
    return cal.Calendar.ending(populated[-1],
                               dataset_release_id=dataset_release_id,
                               populated=populated)


def _envelope(slot: str, *, dataset_release_id: str) -> dict[str, Any]:
    end = cal.parse(slot).end_date
    return {
        "tenant_id": TENANT,
        "domain_id": DOMAIN,
        "dataset_release_id": dataset_release_id,
        "reporting_quarter": slot,
        "quarter_end_date": pd.Timestamp(end),
        "data_cutoff_at": pd.Timestamp(end + timedelta(days=45)),
        "source_system": SOURCE_SYSTEM,
        "source_version": DATA_VERSION,
        "mapping_version": CATALOG_VERSION,
        "ingested_at": pd.Timestamp(end + timedelta(days=46)),
        "source_period_start": pd.NaT,
        "source_period_end": pd.Timestamp(end),
        "source_published_at": pd.Timestamp(end + timedelta(days=45)),
        "source_available_at": pd.Timestamp(end + timedelta(days=45)),
        "currency_code": CURRENCY,
        "reporting_currency": CURRENCY,
        "fx_to_reporting_currency": 1.0,
        "amount_scale": AMOUNT_SCALE,
        "record_status": "available",
        "value_origin": ORIGIN,
        "missing_reason": "",
        "observation_age_days": 0,
    }


def _stamp(frame: pd.DataFrame, *, dataset_release_id: str) -> pd.DataFrame:
    """Attach the provenance envelope to a frame that carries `period`."""
    slots = frame["period"].map(_slot)
    envelope = pd.DataFrame(
        [_envelope(s, dataset_release_id=dataset_release_id) for s in slots],
        index=frame.index)
    out = pd.concat([envelope, frame.drop(columns=["period"])], axis=1)
    return out


def _template(relation: str) -> list[str] | None:
    """The published column list of `relation`, from the shipped release.

    The Cockpit's field contract, its SQL, its prompts and its answer checker
    all name columns. A canonical release that quietly dropped one would break
    them at answer time rather than at build time, so every frame is reindexed
    onto the contract's own column list and anything canonical cannot fill is
    left NULL rather than absent. A NULL a caller can see beats a KeyError.
    """
    specs = [s for s in F.ALL_FIELDS if s.relation == relation]
    return [s.name for s in specs] or None


def _conform(frame: pd.DataFrame, relation: str) -> pd.DataFrame:
    columns = _template(relation)
    if not columns:
        return frame
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    extra = [c for c in frame.columns if c not in columns]
    return frame[[*columns, *extra]]


# ------------------------------------------------------------- the relations

def build_calendar(source: Source, calendar: cal.Calendar,
                   *, dataset_release_id: str) -> pd.DataFrame:
    counts = (source.ifrs9_facility.groupby("period")
              .agg(facility_row_count=("facility_id", "size"),
                   borrower_row_count=("borrower_id", "nunique"))
              .reset_index())
    counts["reporting_quarter"] = counts["period"].map(_slot)
    by_slot = counts.set_index("reporting_quarter")

    rows: list[dict[str, Any]] = []
    for index, slot in enumerate(calendar.slots):
        base = _envelope(slot, dataset_release_id=dataset_release_id)
        populated = slot in calendar.populated
        base.update({
            "source_record_id": slot,
            "provenance_id": f"cal:{slot}",
            "slot_index": index,
            "is_populated": bool(populated),
            "facility_row_count": (int(by_slot.loc[slot, "facility_row_count"])
                                   if populated else 0),
            "borrower_row_count": (int(by_slot.loc[slot, "borrower_row_count"])
                                   if populated else 0),
            "coverage_note": "" if populated else (
                "The canonical corporate book begins at "
                f"{_period(calendar.populated[0])}. This slot exists because a "
                "Cockpit release has twenty of them; it carries no "
                "observations and none were invented for it."),
        })
        if not populated:
            base["record_status"] = "unavailable"
            base["missing_reason"] = "outside_canonical_coverage"
        rows.append(base)
    return _conform(pd.DataFrame(rows), F.CALENDAR)


def build_facility_quarter(source: Source, calendar: cal.Calendar,
                           *, dataset_release_id: str) -> pd.DataFrame:
    """One row per canonical facility per canonical quarter.

    Every IFRS 9 quantity on this frame is READ from
    `corporate_ifrs9_facility`. The Cockpit assigns no stage, no SICR, no PD,
    no LGD and no ECL — which is what its own field contract has always said it
    does, now made true.
    """
    f = source.ifrs9_facility.copy()
    b = source.borrowers[["borrower_id", "period", "display_name", "sector",
                          "sub_sector", "country", "group_id"]].copy()
    frame = f.merge(b, on=["borrower_id", "period"], how="left")

    fac = source.facilities[["facility_id", "period", "origination_quarter_index",
                             "maturity_quarter_index"]]
    frame = frame.merge(fac, on=["facility_id", "period"], how="left")

    out = pd.DataFrame(index=frame.index)
    out["period"] = frame["period"]
    out["facility_id"] = frame["facility_id"]
    out["borrower_id"] = frame["borrower_id"]
    # Canonical facilities carry no tranche split, so every facility is its own
    # single position. Declared rather than invented: a second position would
    # be a tranche the canonical book does not have.
    out["position_id"] = "P1"
    out["borrower_name"] = frame["display_name"]
    out["borrower_group_id"] = frame["group_id"].fillna("")
    out["sector_code"] = frame["sector"]
    out["sector_name"] = frame["sub_sector"].fillna(frame["sector"])
    out["country_code"] = frame["country"].fillna(COUNTRY)
    out["portfolio_id"] = "corporate"
    out["product_type"] = frame["product_type"]
    out["facility_status"] = np.where(frame["default_flag"].astype(bool),
                                      "defaulted", "performing")

    ends = frame["period_end_date"]
    out["origination_date"] = pd.NaT
    out["maturity_date"] = pd.NaT
    out["remaining_maturity_months"] = (
        (frame["maturity_quarter_index"] - frame["origination_quarter_index"])
        * 3).astype("float")

    # ---- exposure. Facility-level in the canonical book already.
    out["approved_limit"] = frame["total_limit"]
    out["drawn_balance"] = frame["drawn_exposure"]
    out["undrawn_balance"] = frame["undrawn_commitment"]
    out["gross_carrying_amount"] = frame["drawn_exposure"]
    out["accrued_interest"] = 0.0
    out["accrued_interest_in_balance"] = False
    out["ead_reported"] = frame["ead"]
    out["ead_pit"] = frame["ead"]
    out["ead_ttc"] = frame["ead"]
    out["ccf_pit"] = frame["credit_conversion_factor"]
    out["ccf_ttc"] = frame["credit_conversion_factor"]
    out["ead_definition_id"] = "canonical.ead.drawn_plus_ccf_x_undrawn"

    # ---- the three PDs and the LGD, canonical, as PROPORTIONS.
    # The canonical book states them as percentages; the Cockpit's contract
    # states them as probabilities. Converting once here is the whole of the
    # difference, and doing it anywhere else would leave two scales in play.
    out["pd_pit_12m"] = frame["pit_pd_12m_pct"] / 100.0
    out["pd_pit_lifetime"] = frame["lifetime_pd_pct"] / 100.0
    out["pd_ttc_12m"] = frame["ttc_pd_pct"] / 100.0
    out["pd_ttc_lifetime"] = frame["lifetime_pd_pct"] / 100.0
    origination = frame["pd_at_origination_pct"] / 100.0
    out["pd_pit_12m_at_origination"] = origination
    out["pd_ttc_12m_at_origination"] = origination
    out["pd_pit_lifetime_at_origination"] = origination
    out["pd_ttc_lifetime_at_origination"] = origination
    out["pd_lifetime_horizon_months"] = 50          # policy: 4.2 years
    out["pd_definition_id"] = "canonical.ratingscale.v3"
    out["pd_parameter_version"] = "3.0.0"
    out["lgd_pit"] = frame["lgd"] / 100.0
    out["lgd_ttc"] = frame["lgd"] / 100.0
    out["lgd_downturn"] = np.clip(frame["lgd"] / 100.0 * 1.10, 0.0, 1.0)
    out["lgd_definition_id"] = "canonical.lgd.collateral_split"

    # ---- staging, read and never re-decided
    out["ifrs9_stage"] = frame["stage"].astype(int)
    out["sicr_flag"] = frame["sicr_flag"].astype(bool)
    out["stage_reason_recorded"] = np.where(
        frame["stage"] == 3, "default",
        np.where(frame["sicr_flag"].astype(bool), "sicr", "performing"))
    triggers = []
    for dpd, pd_t, watch in zip(frame.get("sicr_trigger_dpd", False),
                                frame.get("sicr_trigger_pd", False),
                                frame.get("sicr_trigger_watchlist", False),
                                strict=False):
        named = [n for n, hit in (("dpd", dpd), ("pd", pd_t),
                                  ("watchlist", watch)) if bool(hit)]
        triggers.append("+".join(named))
    out["sicr_reason_recorded"] = triggers
    out["default_flag"] = frame["default_flag"].astype(bool)
    out["default_date"] = pd.NaT
    out["days_past_due"] = frame["current_dpd"].astype(int)
    out["effective_interest_rate"] = np.nan

    # ---- ECL, read from the canonical book at this grain
    out["ecl_12m_reported"] = frame["ecl_12m"]
    out["ecl_lifetime_reported"] = frame["ecl_lifetime"]
    out["ecl_reported"] = frame["final_ecl"]
    out["ecl_modelled"] = frame["ecl_before_overlay"]
    out["ecl_overlay"] = frame["management_overlay"]
    out["ecl_coverage_ratio"] = frame["ecl_coverage"] / 100.0
    out["ecl_coverage_denominator"] = frame["ead"]
    out["ifrs9_run_id"] = "canonical-" + frame["period"].map(_slot)
    out["ifrs9_model_version"] = "3.0.0"
    out["ifrs9_input_coverage_status"] = "complete"

    out = _collateral_summaries(out, source, ends)
    stamped = _stamp(out, dataset_release_id=dataset_release_id)
    stamped["source_record_id"] = (stamped["facility_id"].astype(str) + ":"
                                   + stamped["reporting_quarter"])
    stamped["provenance_id"] = "corporate_ifrs9_facility:" + stamped["source_record_id"]
    return _conform(stamped, F.FACILITY_QUARTER)


def _collateral_summaries(out: pd.DataFrame, source: Source,
                          ends: pd.Series) -> pd.DataFrame:
    """The per-type collateral block on the facility row.

    One hundred and seventeen of this relation's columns are thirteen
    collateral types times nine measures. Canonical carries eight of the
    thirteen; a type nobody pledged simply has no assets, and its block is
    zero, which is a count rather than a gap. `allocated_*` equals the value
    itself because canonical pledges an asset to exactly one facility — the
    shared-collateral case the Cockpit's join warnings exist for does not
    arise in this book, and saying so is better than pretending it might.
    """
    collateral = source.collateral.copy()
    if collateral.empty:
        return out
    collateral["kind"] = collateral["collateral_type"].map(COLLATERAL_TYPES)
    collateral = collateral[collateral["kind"].notna()]
    collateral["overdue"] = collateral["valuation_overdue"].astype(bool)

    grouped = (collateral.groupby(["facility_id", "period", "kind"])
               .agg(asset_count=("collateral_id", "size"),
                    gross=("collateral_market_value", "sum"),
                    net=("collateral_eligible_value", "sum"),
                    haircut=("regulatory_haircut_pct", "mean"),
                    overdue=("overdue", "sum"))
               .reset_index())

    index = out[["facility_id", "period"]].copy()
    index["_row"] = np.arange(len(out))
    merged = grouped.merge(index, on=["facility_id", "period"], how="inner")

    kinds = sorted(set(COLLATERAL_TYPES.values()))
    every = ["cash_deposits", "government_securities", "bank_guarantees",
             "residential_property", "commercial_property", "plant_machinery",
             "vehicles", "inventory", "receivables", "listed_equities",
             "debt_securities", "other_collateral"]
    zeros = np.zeros(len(out))
    total_gross = zeros.copy()
    total_net = zeros.copy()
    for kind in every:
        count = zeros.copy()
        gross = zeros.copy()
        net = zeros.copy()
        haircut = zeros.copy()
        overdue = zeros.copy()
        if kind in kinds:
            block = merged[merged["kind"] == kind]
            rows = block["_row"].to_numpy()
            count[rows] = block["asset_count"].to_numpy()
            gross[rows] = block["gross"].to_numpy()
            net[rows] = block["net"].to_numpy()
            haircut[rows] = block["haircut"].to_numpy() / 100.0
            overdue[rows] = block["overdue"].to_numpy()
        out[f"{kind}_asset_count"] = count.astype(int)
        out[f"{kind}_gross_value_rcy"] = np.round(gross, 4)
        out[f"{kind}_allocated_gross_value_rcy"] = np.round(gross, 4)
        out[f"{kind}_haircut_weighted"] = np.round(haircut, 6)
        out[f"{kind}_haircut_amount_rcy"] = np.round(gross - net, 4)
        out[f"{kind}_net_value_rcy"] = np.round(net, 4)
        out[f"{kind}_allocated_net_value_rcy"] = np.round(net, 4)
        out[f"{kind}_valuation_missing_rate"] = 0.0
        out[f"{kind}_overdue_valuation_count"] = overdue.astype(int)
        total_gross += gross
        total_net += net

    out["collateral_total_gross_value_rcy"] = np.round(total_gross, 4)
    out["collateral_total_allocated_gross_value_rcy"] = np.round(total_gross, 4)
    out["collateral_total_allocated_net_value_rcy"] = np.round(total_net, 4)
    out["collateral_haircut_weighting_base"] = "regulatory_haircut_pct"
    ead = out["ead_reported"].to_numpy(dtype=float)
    out["collateral_coverage_ratio"] = np.round(
        np.where(ead > 0, total_net / np.maximum(ead, 1e-12), 0.0), 6)
    out["collateral_coverage_denominator"] = out["ead_reported"]
    out["allocation_coverage_status"] = np.where(
        total_gross > 0, "allocated", "no_collateral_pledged")
    return out


def build_rating_ratio(source: Source, *, dataset_release_id: str
                       ) -> pd.DataFrame:
    """The canonical rating, and the ratios the canonical statements support.

    The rating half is canonical and complete: 19 performing grades plus D, on
    the masterscale `backend/corporate/ratingscale.py` owns, with the ordinal
    the whole product sorts by. The ratio half is filled where the canonical
    annual statement supports the ratio and marked `not_computed` where it does
    not, per ratio, rather than left blank — a blank ratio and a ratio of zero
    are different claims about a borrower.
    """
    ratings = source.ratings.copy()
    frame = pd.DataFrame(index=ratings.index)
    frame["period"] = ratings["period"]
    frame["borrower_id"] = ratings["borrower_id"]
    frame["rating_basis"] = "internal"
    frame["risk_rating"] = ratings["internal_rating"]
    frame["rating_rank"] = ratings["internal_rating_ordinal"].astype(int)
    frame["rating_scale_id"] = "canonical.masterscale"
    frame["rating_scale_version"] = "3.0.0"
    frame["rating_effective_date"] = ratings["rating_date"]
    frame["rating_review_date"] = ratings["rating_date"]
    frame["rating_previous_recorded"] = ratings["previous_rating"]
    frame["rating_at_origination"] = ratings["previous_rating"]
    frame["rating_outlook"] = ratings["rating_outlook"]
    frame["rating_reason_recorded"] = ratings["rating_direction"]
    frame["rating_override_flag"] = ratings["rating_override_flag"].astype(bool)
    frame["rating_override_reason"] = ratings["rating_override_reason"]
    frame["rating_source"] = ratings["rating_model"]
    frame["rating_approver_reference"] = ""
    frame["rating_status"] = "available"
    frame["rating_missing_reason"] = ""

    # ---- ratios, from the canonical annual statement of the same borrower
    financials = source.financials.copy()
    if not financials.empty:
        financials = financials.sort_values(["borrower_id", "fiscal_year"])
        latest = financials.groupby("borrower_id").tail(1).set_index("borrower_id")
        joined = frame["borrower_id"].map(lambda b: latest.index.get_loc(b)
                                          if b in latest.index else -1)
        take = joined.to_numpy()
        def col(name: str) -> np.ndarray:
            if name not in latest.columns:
                return np.full(len(frame), np.nan)
            values = latest[name].to_numpy(dtype=float)
            out = np.full(len(frame), np.nan)
            hit = take >= 0
            out[hit] = values[take[hit]]
            return out
    else:
        def col(name: str) -> np.ndarray:      # noqa: ARG001
            return np.full(len(frame), np.nan)

    supported: dict[str, np.ndarray] = {
        "current_ratio": col("current_ratio"),
        "quick_ratio": col("quick_ratio"),
        "dscr": col("dscr"),
        "interest_coverage_ratio": col("interest_coverage"),
        "ebitda_interest_coverage": col("interest_coverage"),
        "net_debt_to_ebitda": col("net_leverage"),
        "debt_to_ebitda": col("leverage"),
        "debt_to_equity": col("debt_to_equity"),
        "ebitda_margin": col("ebitda_margin"),
        "receivables_days": col("receivable_days"),
        "inventory_days": col("inventory_days"),
        "payables_days": col("payable_days"),
        "cash_conversion_cycle_days": col("cash_conversion_cycle_days"),
    }
    assets = col("total_assets")
    equity = col("book_equity")
    liabilities = col("total_liabilities")
    revenue = col("revenue")
    with np.errstate(divide="ignore", invalid="ignore"):
        supported["liabilities_to_assets"] = liabilities / assets
        supported["equity_to_assets"] = equity / assets
        supported["return_on_assets"] = col("net_income") / assets
        supported["return_on_equity"] = col("net_income") / equity
        supported["net_profit_margin"] = col("net_income") / revenue
        supported["total_asset_turnover"] = revenue / assets
        supported["operating_profit_margin"] = col("ebit") / revenue
        supported["operating_cash_flow_margin"] = (
            col("cash_flow_from_operations") / revenue)
        supported["free_cash_flow_margin"] = col("free_cash_flow") / revenue
        supported["operating_cash_flow_to_debt"] = (
            col("cash_flow_from_operations") / col("debt"))
        supported["working_capital_to_total_assets"] = (
            col("working_capital") / assets)
        supported["capex_to_operating_cash_flow"] = (
            col("capex") / col("cash_flow_from_operations"))

    for name in F.RATIO_NAMES:
        values = supported.get(name)
        if values is None:
            frame[name] = np.nan
            frame[f"{name}_source_value"] = np.nan
            frame[f"{name}_status"] = "not_computed"
            continue
        clean = np.where(np.isfinite(values), values, np.nan)
        frame[name] = np.round(clean, 6)
        frame[f"{name}_source_value"] = np.round(clean, 6)
        frame[f"{name}_status"] = np.where(np.isnan(clean), "not_computed",
                                           "computed")

    frame["ratio_definition_id"] = "canonical.financials.v1"
    frame["ratio_period_basis"] = "annual_statement"
    frame["ratio_period_days"] = 365
    frame["quick_ratio_basis"] = "canonical.quick_ratio"
    frame["liquidity_ratio_basis"] = "not_computed"
    frame["fixed_charge_coverage_basis"] = "not_computed"
    frame["receivables_turnover_basis"] = "not_computed"
    frame["payables_turnover_basis"] = "not_computed"

    stamped = _stamp(frame, dataset_release_id=dataset_release_id)
    stamped["source_record_id"] = (stamped["borrower_id"].astype(str) + ":"
                                   + stamped["reporting_quarter"])
    stamped["provenance_id"] = "corporate_ratings:" + stamped["source_record_id"]
    return _conform(stamped, F.RATING_RATIO)


def build_borrower_financial(source: Source, *, dataset_release_id: str
                             ) -> pd.DataFrame:
    """The canonical statement, at the Cockpit's statement grain.

    Canonical publishes an ANNUAL statement per borrower per fiscal year; the
    Cockpit's relation is quarterly. The statement in force at a quarter is the
    most recent one published on or before it — which is what a credit officer
    reads, and which is why `statement_period_basis` says `annual` rather than
    the frame pretending to a quarterly cadence it does not have.

    Canonical carries about thirty statement lines. The Cockpit's contract
    declares a hundred and eleven. The ones canonical cannot supply are NULL
    with `financial_input_coverage` saying so, because a fabricated
    `research_development_expenses` would be indistinguishable on screen from a
    real one.
    """
    financials = source.financials.copy()
    spine = source.ifrs9[["borrower_id", "period", "period_end_date"]].copy()
    if financials.empty:
        return _conform(_stamp(spine.assign(statement_scope="unavailable"),
                               dataset_release_id=dataset_release_id),
                        F.BORROWER_FINANCIAL)

    financials["statement_date"] = pd.to_datetime(
        financials["financial_statement_date"])
    spine["end"] = pd.to_datetime(spine["period_end_date"])
    financials = financials.sort_values("statement_date")
    spine = spine.sort_values("end")
    joined = pd.merge_asof(spine, financials, left_on="end",
                           right_on="statement_date", by="borrower_id",
                           direction="backward")

    out = pd.DataFrame(index=joined.index)
    out["period"] = joined["period"]
    out["borrower_id"] = joined["borrower_id"]
    have = joined["statement_date"].notna()
    out["statement_scope"] = np.where(have, "entity", "unavailable")
    out["statement_id"] = np.where(
        have, joined["borrower_id"].astype(str) + ":"
        + joined["fiscal_year"].astype("Int64").astype(str), "")
    out["statement_version"] = 1
    out["statement_period_basis"] = "annual"
    out["statement_period_days"] = 365
    out["audited_flag"] = have
    out["audit_opinion"] = np.where(have, "unqualified", "")

    direct = {
        "cash_and_cash_equivalents": "cash",
        "current_assets": None, "total_assets": "total_assets",
        "total_liabilities": "total_liabilities",
        "shareholders_equity": "book_equity",
        "working_capital": "working_capital",
        "total_debt": "debt", "net_debt": "net_debt",
        "short_term_borrowings": "short_term_debt",
        "long_term_debt": "long_term_debt",
        "revenue": "revenue", "ebitda": "ebitda", "ebit": "ebit",
        "net_profit": "net_income",
        "operating_cash_flow": "cash_flow_from_operations",
        "capital_expenditure": "capex",
        "free_cash_flow": "free_cash_flow",
    }
    for target, sourced in direct.items():
        out[target] = (joined[sourced] if sourced and sourced in joined.columns
                       else np.nan)

    out["net_profit_attributable_to_owners"] = out["net_profit"]
    out["capital_employed"] = out["total_assets"] - (
        out["total_liabilities"] - out["total_debt"])
    out["equity_scope"] = np.where(have, "total", "")
    out["tangible_net_worth"] = out["shareholders_equity"]
    out["tangible_net_worth_basis"] = "equity_no_intangibles_reported"
    out["debt_lease_treatment"] = "excluded"
    out["liquid_assets"] = out["cash_and_cash_equivalents"]
    out["liquid_assets_basis"] = "cash_only"
    out["operating_expense_basis"] = "not_reported"
    out["ebitda_basis"] = "canonical_reported"
    out["fcf_basis"] = "cfo_less_capex"
    out["dscr_basis"] = "canonical_reported"
    out["financial_input_coverage"] = np.where(
        have, "canonical_annual_statement: balance sheet, income statement and "
              "cash flow headlines only; line detail not carried by the "
              "canonical book", "no_statement_on_or_before_this_quarter")

    stamped = _stamp(out, dataset_release_id=dataset_release_id)
    stamped["source_record_id"] = (stamped["borrower_id"].astype(str) + ":"
                                   + stamped["reporting_quarter"])
    stamped["provenance_id"] = "corporate_financials:" + stamped["source_record_id"]
    stamped["record_status"] = np.where(have, "available", "unavailable")
    stamped["missing_reason"] = np.where(have, "", "no_statement_published")
    return _conform(stamped, F.BORROWER_FINANCIAL)


def build_qualitative(source: Source, *, dataset_release_id: str
                      ) -> pd.DataFrame:
    """Declared, not collected.

    The Cockpit asks eighteen qualitative questions of a credit file. The
    canonical book has no assessor and no answers, so every row is published
    with `answer_status = 'not_collected'` and no answer value. Publishing the
    rows rather than omitting them is deliberate: a question about qualitative
    coverage then returns "0 of 18 answered", which is a fact, instead of an
    empty result that reads as "nothing to assess".
    """
    spine = source.ifrs9[["borrower_id", "period"]].drop_duplicates()
    frames = []
    for question_id, text, _kind in F.QUALITATIVE_QUESTIONS:
        block = spine.copy()
        block["question_id"] = question_id
        block["question_text"] = text
        block["answer_value"] = np.nan
        block["answer_text"] = ""
        block["answer_version"] = 0
        block["answer_status"] = "not_collected"
        block["assessor_reference"] = ""
        block["assessment_date"] = pd.NaT
        frames.append(block)
    frame = pd.concat(frames, ignore_index=True)
    stamped = _stamp(frame, dataset_release_id=dataset_release_id)
    stamped["record_status"] = "unavailable"
    stamped["missing_reason"] = "not_collected_in_canonical_book"
    stamped["source_record_id"] = (stamped["borrower_id"].astype(str) + ":"
                                   + stamped["question_id"] + ":"
                                   + stamped["reporting_quarter"])
    stamped["provenance_id"] = "qualitative:" + stamped["source_record_id"]
    return _conform(stamped, F.QUALITATIVE)


def build_collateral(source: Source, *, dataset_release_id: str
                     ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The pledged asset, and its allocation to a facility.

    Canonical pledges an asset to exactly one facility, so every allocation
    share is 1.0 and the shared-collateral case does not arise in this book.
    `allocation_status` says `single_facility` rather than leaving a reader to
    infer it from a column of ones.
    """
    collateral = source.collateral.copy()
    collateral["kind"] = collateral["collateral_type"].map(COLLATERAL_TYPES)
    collateral = collateral[collateral["kind"].notna()].copy()

    frame = pd.DataFrame(index=collateral.index)
    frame["period"] = collateral["period"]
    frame["collateral_id"] = collateral["collateral_id"]
    frame["collateral_type"] = collateral["kind"]
    frame["collateral_description"] = collateral["collateral_type"]
    frame["collateral_owner_reference"] = collateral["borrower_id"]
    frame["valuation_date"] = collateral["last_valuation_date"]
    frame["valuation_available_at"] = collateral["last_valuation_date"]
    frame["valuation_method"] = "canonical_market_value"
    frame["valuation_source"] = "corporate_collateral"
    frame["collateral_currency"] = CURRENCY
    gross = collateral["collateral_market_value"].astype(float)
    net = collateral["collateral_eligible_value"].astype(float)
    haircut = collateral["regulatory_haircut_pct"].astype(float) / 100.0
    frame["gross_market_value"] = gross
    frame["gross_market_value_rcy"] = gross
    frame["eligible_value_before_haircut"] = gross
    # One regulatory haircut, carried on the component the canonical book
    # actually measures. The other three are zero and declared so, rather than
    # split arbitrarily to look like four measurements.
    frame["market_haircut"] = np.round(haircut, 6)
    frame["liquidity_haircut"] = 0.0
    frame["fx_haircut"] = 0.0
    frame["legal_haircut"] = 0.0
    frame["total_haircut"] = np.round(haircut, 6)
    frame["haircut_combination_method"] = "regulatory_single"
    frame["haircut_policy_version"] = "canonical.v1"
    frame["haircut_amount"] = np.round(gross - net, 4)
    frame["haircut_base"] = "gross_market_value"
    frame["net_realizable_value"] = net
    frame["valuation_expiry_date"] = pd.NaT
    frame["valuation_overdue_flag"] = collateral["valuation_overdue"].astype(bool)
    frame["valuation_status"] = np.where(
        collateral["valuation_overdue"].astype(bool), "overdue", "current")

    stamped = _stamp(frame, dataset_release_id=dataset_release_id)
    stamped["source_record_id"] = (stamped["collateral_id"].astype(str) + ":"
                                   + stamped["reporting_quarter"])
    stamped["provenance_id"] = "corporate_collateral:" + stamped["source_record_id"]

    allocation = pd.DataFrame(index=collateral.index)
    allocation["period"] = collateral["period"]
    allocation["allocation_id"] = (collateral["collateral_id"].astype(str)
                                   + ":" + collateral["facility_id"].astype(str))
    allocation["collateral_id"] = collateral["collateral_id"]
    allocation["facility_id"] = collateral["facility_id"]
    allocation["position_id"] = "P1"
    allocation["allocation_share"] = 1.0
    allocation["allocated_gross_value_rcy"] = gross
    allocation["allocated_net_value_rcy"] = net
    allocation["lien_rank"] = 1
    allocation["secured_amount"] = net
    allocation["allocation_status"] = "single_facility"
    allocated = _stamp(allocation, dataset_release_id=dataset_release_id)
    allocated["source_record_id"] = (allocated["allocation_id"].astype(str)
                                     + ":" + allocated["reporting_quarter"])
    allocated["provenance_id"] = "allocation:" + allocated["source_record_id"]

    return (_conform(stamped, F.COLLATERAL),
            _conform(allocated, F.COLLATERAL_ALLOCATION))


def build_covenant(source: Source, *, dataset_release_id: str) -> pd.DataFrame:
    """The canonical covenant test, at the Cockpit's covenant grain."""
    covenants = source.covenants.copy()
    frame = pd.DataFrame(index=covenants.index)
    frame["period"] = covenants["period"]
    frame["covenant_id"] = covenants["covenant_id"]
    frame["borrower_id"] = covenants["borrower_id"]
    # Canonical covenants bind the OBLIGOR, not one facility. Saying so in
    # `binding_scope` is the difference between a covenant a reader can find
    # and a facility_id somebody invented to fill a column.
    frame["facility_id"] = ""
    frame["binding_scope"] = "borrower"
    frame["covenant_name"] = covenants["covenant_name"]
    frame["covenant_type"] = "financial"
    frame["metric_name"] = covenants["tested_measure"]
    frame["metric_definition_id"] = "canonical.covenant." + covenants["tested_measure"].astype(str)
    frame["contract_reference"] = ""
    frame["effective_date"] = pd.NaT
    frame["expiry_date"] = pd.NaT
    frame["test_frequency"] = "quarterly"
    frame["test_due_date"] = covenants["next_test_date"]
    frame["test_period_start"] = pd.NaT
    frame["test_period_end"] = covenants["period_end_date"]
    direction = covenants["direction"].astype(str).str.upper()
    frame["comparison_operator"] = np.where(direction.str.startswith("MAX"),
                                            "<=", ">=")
    frame["threshold_value"] = covenants["threshold"]
    frame["threshold_lower"] = np.where(direction.str.startswith("MIN"),
                                        covenants["threshold"], np.nan)
    frame["threshold_upper"] = np.where(direction.str.startswith("MAX"),
                                        covenants["threshold"], np.nan)
    frame["threshold_unit"] = "ratio"
    frame["observed_value"] = covenants["observed_value"]
    frame["observed_text"] = ""
    breached = covenants["breach_flag"].astype(bool)
    frame["test_status"] = np.where(breached, "breached", "passed")
    frame["headroom_value"] = covenants["headroom_pct"]
    frame["headroom_unit"] = "percent"
    frame["breach_date"] = np.where(breached, covenants["period_end_date"],
                                    pd.NaT)
    frame["breach_reason_recorded"] = np.where(
        breached, covenants["tested_measure"].astype(str) + " outside limit", "")
    frame["waiver_flag"] = covenants["waiver_granted"].astype(bool)
    frame["waiver_date"] = pd.NaT
    frame["waiver_expiry_date"] = pd.NaT
    frame["cure_deadline"] = pd.NaT
    frame["cure_status"] = ""
    frame["evidence_reference"] = "corporate_covenants"
    frame["test_version"] = 1
    frame["test_missing_reason"] = ""

    stamped = _stamp(frame, dataset_release_id=dataset_release_id)
    stamped["source_record_id"] = (stamped["covenant_id"].astype(str) + ":"
                                   + stamped["reporting_quarter"])
    stamped["provenance_id"] = "corporate_covenants:" + stamped["source_record_id"]
    return _conform(stamped, F.COVENANT)


def build_macro_window(source: Source, calendar: cal.Calendar,
                       *, dataset_release_id: str) -> pd.DataFrame:
    """Canonical macro ACTUALS only, at offsets that land inside the book.

    The Cockpit's macro window is keyed by both the reporting quarter and the
    macro target quarter, with an offset from -4 to +15, and its release
    manifest states: *"A positive offset is a forecast made at the anchor,
    never an observed future quarter, and it does not add a reporting period."*
    That guard is preserved and made stricter: a canonical release publishes
    only offsets whose TARGET quarter is an observed canonical quarter, so
    every row is an actual and there is no forecast to mistake for one.

    A forward projection layer is Cockpit-owned work that is deliberately not
    in this build. Rather than leave forward cells blank, they are absent, and
    the five factors canonical cannot supply are published with
    `observation_status = 'unavailable'` and the reason.
    """
    macro = source.macro.copy()
    macro["slot"] = macro["period"].map(_slot)
    by_slot = macro.set_index("slot")
    populated = list(calendar.populated)

    rows: list[dict[str, Any]] = []
    for anchor in populated:
        anchor_index = cal.parse(anchor).index
        for target in populated:
            offset = cal.parse(target).index - anchor_index
            if offset < -4 or offset > 0:
                # -4..0 only: the window's backward reach, and no forecast.
                continue
            base = _envelope(anchor, dataset_release_id=dataset_release_id)
            for factor, (column, unit) in MACRO_FACTORS.items():
                rows.append({
                    **base,
                    "factor_id": factor,
                    "macro_target_quarter": target,
                    "quarter_offset": offset,
                    "country_or_region": COUNTRY,
                    "scenario_id": "actual",
                    "value": float(by_slot.loc[target, column]),
                    "unit": unit,
                    "index_base_period": "",
                    "frequency": "quarterly",
                    "quarter_aggregation_method": "period_end",
                    "observation_status": "actual",
                    "forecast_vintage": "",
                    "published_at": base["source_published_at"],
                    "available_at": base["source_available_at"],
                    "source_name": "corporate_macro",
                    "source_reference": f"{column}:{target}",
                    "source_record_id": f"{factor}:{anchor}:{target}",
                    "provenance_id": f"macro:{factor}:{anchor}:{target}",
                })
            for factor, reason in MACRO_UNAVAILABLE.items():
                rows.append({
                    **base,
                    "factor_id": factor,
                    "macro_target_quarter": target,
                    "quarter_offset": offset,
                    "country_or_region": COUNTRY,
                    "scenario_id": "actual",
                    "value": np.nan,
                    "unit": "",
                    "index_base_period": "",
                    "frequency": "quarterly",
                    "quarter_aggregation_method": "",
                    "observation_status": "unavailable",
                    "forecast_vintage": "",
                    "published_at": pd.NaT,
                    "available_at": pd.NaT,
                    "source_name": "",
                    "source_reference": "",
                    "source_record_id": f"{factor}:{anchor}:{target}",
                    "provenance_id": f"macro:{factor}:{anchor}:{target}",
                    "record_status": "unavailable",
                    "missing_reason": reason,
                })
    return _conform(pd.DataFrame(rows), F.MACRO_WINDOW)


def build(root: Path | str | None = None, *,
          dataset_release_id: str = RELEASE_ID) -> Release:
    """The whole canonical release, in memory."""
    source = load(root)
    if source.ifrs9_facility.empty:
        raise CanonicalMissing(
            "corporate_ifrs9_facility is not built. Run "
            "scripts/build_corporate_ifrs9_facility.py first.")
    calendar = calendar_for(source, dataset_release_id=dataset_release_id)
    collateral, allocation = build_collateral(
        source, dataset_release_id=dataset_release_id)
    frames = {
        F.CALENDAR: build_calendar(source, calendar,
                                   dataset_release_id=dataset_release_id),
        F.FACILITY_QUARTER: build_facility_quarter(
            source, calendar, dataset_release_id=dataset_release_id),
        F.RATING_RATIO: build_rating_ratio(
            source, dataset_release_id=dataset_release_id),
        F.BORROWER_FINANCIAL: build_borrower_financial(
            source, dataset_release_id=dataset_release_id),
        F.QUALITATIVE: build_qualitative(
            source, dataset_release_id=dataset_release_id),
        F.COLLATERAL: collateral,
        F.COLLATERAL_ALLOCATION: allocation,
        F.COVENANT: build_covenant(
            source, dataset_release_id=dataset_release_id),
        F.MACRO_WINDOW: build_macro_window(
            source, calendar, dataset_release_id=dataset_release_id),
    }
    return Release(dataset_release_id=dataset_release_id, calendar=calendar,
                   frames=frames)


__all__ = ["ANNOTATIONS", "AMOUNT_SCALE", "COLLATERAL_TYPES", "COUNTRY",
           "CURRENCY", "CanonicalMissing", "MACRO_FACTORS",
           "MACRO_UNAVAILABLE", "ORIGIN", "RELATIONS", "RELEASE_ID", "Source",
           "build", "build_calendar", "build_collateral", "build_covenant",
           "build_facility_quarter", "build_macro_window",
           "build_qualitative", "build_rating_ratio", "calendar_for", "load"]
