"""The Borrower 360 semantic snapshot. B2, B4.

A fast denormalised read of 137 fields per borrower per quarter, assembled
from the domains that own them. B2's constraint is the whole design: the
snapshot may be quick, it may be wide, and it may not be authoritative.

How that is enforced rather than asserted
------------------------------------------
Every field is built from a `lineage.Field`, and the assembler REFUSES to
write a column that has no lineage entry. That is the mechanism: a field
cannot get onto the screen without declaring where it came from, so there is
no path by which a number invented here can be mistaken for a number the IFRS
9 domain published. `assemble()` raises if the two disagree in either
direction - a lineage entry with no column, or a column with no entry.

Fields the graph has not computed yet
--------------------------------------
The nineteen GRAPH SUMMARY fields and three of the DATA QUALITY fields depend
on the derived graph. Until it has run they are filled with the sentinel
`NOT_COMPUTED` rather than zero. Zero is a value; a network risk score of zero
means "measured, and it is nothing", and a screen cannot tell that apart from
"not measured". The sentinel can.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import NOT_CLIENT_DATA, ORIGIN
from backend.corporate import lineage as lineage_mod
from backend.corporate.universe import Universe, latest_statement

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = "1.0.0"

#: Written into a field the derived graph has not produced yet. Never zero,
#: never blank - both of those read as measurements.
NOT_COMPUTED = "NOT COMPUTED"

#: A statement older than this is stale enough to say so on the screen.
STALE_STATEMENT_DAYS = 540

#: Which lineage groups this module fills from the credit domains, and which
#: wait for the graph.
GRAPH_GROUPS: frozenset[str] = frozenset({"GRAPH SUMMARY"})
GRAPH_DEPENDENT_FIELDS: frozenset[str] = frozenset({
    "group_id", "group_name", "group_utilisation_pct",
    "relationship_confidence", "dq_issue_count",
    "snapshot_validation_status",
})


class SnapshotContractError(RuntimeError):
    """The assembled snapshot and the lineage table disagree."""


def assemble(universe: Universe,
             graph: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per borrower per quarter, carrying every B4 field.

    Built by joining the authoritative domains at their own grain and
    aggregating to borrower-quarter where the domain is finer. The
    aggregations are named in the lineage table, not chosen here, so a reader
    can see that `valuation_age_days` is the OLDEST valuation and not the
    newest without reading this code.

    `graph` is `corporate_connected_groups` from `graphsummary.build`. Where
    it is given, the twenty graph fields carry real values or one of the
    three sentinels that say WHICH kind of absent they are. Where it is not
    given - or for a quarter it does not cover - they stay NOT COMPUTED,
    which is the fourth and different statement: the derivation did not run
    at all in this build.
    """
    master = universe["corporate_customer_master"]
    keys = ["borrower_id", "period"]
    frame = master.copy()

    frame = _join_ratings(frame, universe)
    frame = _join_financials(frame, universe)
    frame = _join_exposure(frame, universe)
    frame = _join_ifrs9(frame, universe)
    frame = _join_delinquency(frame, universe)
    frame = _join_covenants(frame, universe)
    frame = _join_collateral(frame, universe)
    frame = _join_limits(frame, universe)
    frame = _join_graph(frame, graph)
    frame = _fill_pending_graph_fields(frame)
    frame = _data_quality(frame, universe)

    ordered = [f.name for f in lineage_mod.FIELDS]
    _check_contract(frame, ordered)

    out = frame[["period_end_date", *ordered]].copy()
    out.insert(0, "period", frame["period"])
    out["origin"] = ORIGIN
    out["not_client_data"] = NOT_CLIENT_DATA
    return out.sort_values(keys).reset_index(drop=True)


def _check_contract(frame: pd.DataFrame, ordered: list[str]) -> None:
    """The snapshot and the lineage table must name exactly the same fields."""
    have = set(frame.columns)
    declared = set(ordered)
    missing = declared - have
    if missing:
        raise SnapshotContractError(
            f"{len(missing)} field(s) have a lineage entry but were not "
            f"assembled: {', '.join(sorted(missing))}. Either the assembler "
            "is incomplete or the lineage entry is aspirational; both are "
            "defects, and a snapshot that silently drops a declared field "
            "shows a blank column with no explanation.")
    # The reverse check is deliberately NOT an error: the assembler carries
    # working columns (entity_index, cr_number and so on) that the snapshot
    # does not publish. What matters is that nothing PUBLISHED lacks lineage,
    # and the projection below guarantees that by construction.


def _join_ratings(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    ratings = universe["corporate_ratings"][[
        "borrower_id", "period", "internal_rating", "internal_rating_numeric",
        "previous_rating", "rating_change_notches", "rating_direction",
        "rating_date", "rating_model", "rating_override_flag",
        "watchlist_flag", "external_rating", "rating_outlook"]]
    return frame.merge(ratings, on=["borrower_id", "period"], how="left")


def _join_financials(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    """The latest statement PUBLISHED by the quarter end, and its age.

    Not the fiscal year matching the quarter. A statement the borrower had not
    filed yet is not information the bank had, and joining on fiscal year
    would give every ratio on this screen a few months of foresight.
    """
    latest = latest_statement(
        frame[["borrower_id", "period", "period_end_date"]].assign(
            entity_index=0, quarter_index=0),
        universe["corporate_financials"])
    columns = [f.name for f in lineage_mod.FIELDS if f.group == "FINANCIALS"]
    keep = [c for c in columns if c in latest.columns]
    return frame.merge(
        latest[["borrower_id", "period", *keep]],
        on=["borrower_id", "period"], how="left")


def _join_exposure(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    facilities = universe["corporate_facilities"]
    grouped = facilities.groupby(["borrower_id", "period"], as_index=False).agg(
        total_limit=("limit_amount", "sum"),
        total_outstanding=("drawn_exposure", "sum"),
        drawn_exposure=("drawn_exposure", "sum"),
        undrawn_commitment=("undrawn_commitment", "sum"),
        ifrs9_ead=("ifrs9_ead", "sum"),
        funded_exposure=("funded_exposure", "sum"),
        unfunded_exposure=("unfunded_exposure", "sum"),
        trade_finance_exposure=("trade_finance_exposure", "sum"),
        guarantee_exposure=("guarantee_exposure", "sum"),
        secured_exposure=("secured_exposure", "sum"),
        unsecured_exposure=("unsecured_exposure", "sum"),
        largest_facility=("limit_amount", "max"),
        facility_count=("facility_id", "size"))

    # The currency of the LARGEST facility, which is what a single-currency
    # label on a multi-currency borrower can honestly mean.
    largest = (facilities.sort_values("limit_amount")
               .groupby(["borrower_id", "period"], as_index=False)
               .last()[["borrower_id", "period", "currency"]])
    grouped = grouped.merge(largest, on=["borrower_id", "period"], how="left")

    frame = frame.merge(grouped, on=["borrower_id", "period"], how="left")
    for column in ("total_limit", "total_outstanding", "drawn_exposure",
                   "undrawn_commitment", "ifrs9_ead", "funded_exposure",
                   "unfunded_exposure", "trade_finance_exposure",
                   "guarantee_exposure", "secured_exposure",
                   "unsecured_exposure", "largest_facility"):
        frame[column] = frame[column].fillna(0.0)
    frame["facility_count"] = frame["facility_count"].fillna(0).astype(int)
    frame["currency"] = frame["currency"].fillna("")

    # Sector concentration: this borrower's share of its sector, same quarter.
    sector_total = frame.groupby(["period", "sector"])["ifrs9_ead"].transform(
        "sum")
    frame["sector_concentration_share"] = np.round(
        np.where(sector_total > 0,
                 frame["ifrs9_ead"] / sector_total.replace(0, np.nan) * 100,
                 0.0), 4)
    return frame


def _join_ifrs9(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    ifrs9 = universe["corporate_ifrs9"].rename(
        columns={"scenario_weight_base": "scenario_weight"})
    columns = ["stage", "sicr_flag", "pd_12m", "pd_lifetime", "lgd", "ead",
               "ecl_12m", "ecl_lifetime", "final_ecl", "ecl_coverage",
               "management_overlay", "default_flag", "scenario_weight"]
    frame = frame.merge(ifrs9[["borrower_id", "period", *columns]],
                        on=["borrower_id", "period"], how="left")

    restructuring = universe["corporate_restructuring"]
    if len(restructuring):
        flags = restructuring.groupby(["borrower_id", "period"]).agg(
            restructure_flag=("restructure_flag", "any"),
            forbearance_flag=("forbearance_flag", "any"))
        keys = frame.set_index(["borrower_id", "period"]).index
        frame["restructure_flag"] = pd.Series(
            keys.map(flags["restructure_flag"])).fillna(False).to_numpy()
        frame["forbearance_flag"] = pd.Series(
            keys.map(flags["forbearance_flag"])).fillna(False).to_numpy()
    else:  # pragma: no cover - the generator always grants some
        frame["restructure_flag"] = False
        frame["forbearance_flag"] = False
    return frame


def _join_delinquency(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    columns = ["current_dpd", "max_dpd_3m", "max_dpd_12m",
               "days_since_last_payment", "arrears_amount",
               "delinquency_bucket", "number_of_missed_payments_12m",
               "collections_flag"]
    return frame.merge(
        universe["corporate_delinquency"][["borrower_id", "period", *columns]],
        on=["borrower_id", "period"], how="left")


def _join_covenants(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    covenants = universe["corporate_covenants"]
    grouped = covenants.groupby(["borrower_id", "period"], as_index=False).agg(
        covenant_count=("covenant_id", "nunique"),
        covenants_tested=("covenant_id", "size"),
        covenants_breached=("breach_flag", "sum"),
        minimum_headroom_pct=("headroom_pct", "min"),
        average_headroom_pct=("headroom_pct", "mean"),
        next_test_date=("next_test_date", "min"),
        breach_flag=("breach_flag", "any"))
    frame = frame.merge(grouped, on=["borrower_id", "period"], how="left")
    for column, default in (("covenant_count", 0), ("covenants_tested", 0),
                            ("covenants_breached", 0)):
        frame[column] = frame[column].fillna(default).astype(int)
    frame["breach_flag"] = frame["breach_flag"].fillna(False)
    frame["next_test_date"] = frame["next_test_date"].fillna("")
    frame["average_headroom_pct"] = np.round(
        frame["average_headroom_pct"].astype(float), 2)
    return frame


def _join_collateral(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    collateral = universe["corporate_collateral"]
    grouped = collateral.groupby(["borrower_id", "period"], as_index=False).agg(
        collateral_count=("collateral_id", "size"),
        collateral_market_value=("collateral_market_value", "sum"),
        collateral_eligible_value=("collateral_eligible_value", "sum"),
        last_valuation_date=("last_valuation_date", "max"),
        # The OLDEST valuation, not the newest. The stalest piece of security
        # is the one a credit officer needs told about; a maximum over the
        # dates and a maximum over the ages are different questions and this
        # is the second one.
        valuation_age_days=("valuation_age_days", "max"))
    frame = frame.merge(grouped, on=["borrower_id", "period"], how="left")
    frame["collateral_count"] = frame["collateral_count"].fillna(0).astype(int)
    for column in ("collateral_market_value", "collateral_eligible_value"):
        frame[column] = frame[column].fillna(0.0)
    frame["last_valuation_date"] = frame["last_valuation_date"].fillna("")
    frame["valuation_age_days"] = frame["valuation_age_days"].fillna(
        0).astype(int)

    secured = frame["secured_exposure"].to_numpy()
    eligible = frame["collateral_eligible_value"].to_numpy()
    safe = np.where(secured > 0, secured, 1.0)
    frame["collateral_coverage_pct"] = np.round(
        np.where(secured > 0, eligible / safe * 100, 0.0), 2)
    frame["collateral_shortfall"] = np.round(
        np.maximum(secured - eligible, 0.0), 2)
    return frame


def _join_limits(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    columns = ["single_name_utilisation_pct", "eligible_capital_reference",
               "limit_status", "investigation_trigger"]
    return frame.merge(
        universe["corporate_limits"][["borrower_id", "period", *columns]],
        on=["borrower_id", "period"], how="left")


#: Snapshot field <- column in `corporate_connected_groups`, where the two
#: names differ. Everything else joins on its own name.
GRAPH_FIELD_SOURCE: dict[str, str] = {
    "group_id": "connected_group_id",
}


def _join_graph(frame: pd.DataFrame,
                graph: pd.DataFrame | None) -> pd.DataFrame:
    """Bring the derived graph fields onto the snapshot, per quarter.

    Joined on (borrower_id, period), never forward-filled. A borrower's group
    is a fact about a date; carrying Q2's group into Q1 because Q1 was not
    derived would put a structure on the screen that did not exist yet, which
    is the same class of error as reading a statement before it was filed.
    """
    if graph is None or graph.empty:
        return frame

    from backend.corporate import graphsummary as graphsummary_mod

    wanted = [f.name for f in lineage_mod.FIELDS
              if f.group in GRAPH_GROUPS or f.name in GRAPH_DEPENDENT_FIELDS]
    keyed = graph.set_index(["borrower_id", "period"])
    index = pd.MultiIndex.from_arrays(
        [frame["borrower_id"].astype(str), frame["period"].astype(str)])

    for name in wanted:
        column = GRAPH_FIELD_SOURCE.get(name, name)
        if column not in keyed.columns:
            continue
        values = pd.Series(index.map(keyed[column]), index=frame.index)

        # `corporate_connected_groups` keeps its measures numeric and null
        # where absent, so that they can be averaged and ranked. The snapshot
        # is a read for a screen, and a screen must never show a blank cell
        # where a number would go - so the number and its status are folded
        # back into one displayable value here, and nowhere else.
        status_column = graphsummary_mod.MEASURE_STATUS.get(column)
        if status_column and status_column in keyed.columns:
            status = pd.Series(index.map(keyed[status_column]),
                               index=frame.index)
            absent = status.notna() & (status != graphsummary_mod.AVAILABLE)
            frame[name] = values.map(_render).where(~absent, status)
        else:
            frame[name] = values.map(_render)
    return frame


def _render(value: Any) -> Any:
    """A graph cell, as text, at the precision it was computed to.

    Every graph column on the snapshot is a STRING. A cell may hold a number
    or one of four sentinels, and a column that holds both cannot be written
    to Parquet at all - the build failed on exactly that, with
    `Could not convert 'NOT_APPLICABLE' with type str: tried to convert to
    double`. Making the column numeric instead would mean dropping the
    sentinels, which is the one thing this module exists to prevent, so the
    column is text and `corporate_connected_groups` carries the numbers for
    anything that needs to aggregate them.

    No precision is created here. The values arrive already rounded to their
    published precision, and this only turns them into their own decimal
    representation - `113.0` prints as `113` because a community label is not
    a quantity with a fractional part.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if number.is_integer():
            return str(int(number))
        # Positional, never scientific. A DebtRank impact of 5e-05 on a
        # screen reads as an error message, not as a number.
        return format(Decimal(str(number)), "f")
    return value


def _fill_pending_graph_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """Every graph-derived field, marked as not yet computed. B2.

    Filled with a sentinel and not with zero. A network risk score of zero is
    a measurement; "no graph has run" is not, and a screen that cannot tell
    them apart will present the second as the first.

    Runs AFTER `_join_graph`, and fills only what is still missing - per CELL,
    not per column. A build that derived the graph for the last four quarters
    must keep those four and mark the other twelve, and the whole-column test
    that was here before would have thrown all sixteen away.

    An EMPTY STRING counts as missing, not as a value. `build_customer_master`
    writes `group_id = ""` and `group_name = ""` because the group is derived
    and it cannot know it; the previous version tested only for null, so those
    two fields left the assembler blank rather than sentinelled - the exact
    "blank reads as a measurement" failure the rest of this module exists to
    prevent, hiding in the one place nobody looked.
    """
    for entry in lineage_mod.FIELDS:
        if entry.group not in GRAPH_GROUPS and (
                entry.name not in GRAPH_DEPENDENT_FIELDS):
            continue
        if entry.name not in frame.columns:
            frame[entry.name] = NOT_COMPUTED
            continue
        column = frame[entry.name]
        blank = column.isna() | (column.astype("string").fillna("").str.strip()
                                 == "")
        frame[entry.name] = column.where(~blank, NOT_COMPUTED)
    return frame


def _data_quality(frame: pd.DataFrame, universe: Universe) -> pd.DataFrame:
    """The two data-quality fields that do NOT need the graph.

    `source_completeness` counts the fields that actually resolved to a source
    row for this borrower-quarter, over the fields that could have. It is
    computed from the assembled frame rather than declared, so a domain that
    stops producing rows shows up here as a falling number rather than as a
    silent column of nulls.
    """
    checked = [f.name for f in lineage_mod.FIELDS
               if f.group not in GRAPH_GROUPS
               and f.name not in GRAPH_DEPENDENT_FIELDS
               and f.name in frame.columns]
    present = frame[checked].notna().sum(axis=1)
    frame["source_completeness"] = np.round(
        present / max(len(checked), 1) * 100, 2)

    statement_age = pd.to_numeric(
        frame.get("financial_statement_age_days"), errors="coerce")
    valuation_age = pd.to_numeric(
        frame.get("valuation_age_days"), errors="coerce")
    frame["stale_data_flag"] = (
        (statement_age.fillna(9_999) > STALE_STATEMENT_DAYS)
        | (valuation_age.fillna(0) > 730))
    return frame


def summary(snapshot: pd.DataFrame) -> dict[str, Any]:
    """B2/B4, for a report."""
    graph_fields = [f.name for f in lineage_mod.FIELDS
                    if f.group in GRAPH_GROUPS
                    or f.name in GRAPH_DEPENDENT_FIELDS]
    pending = [name for name in graph_fields
               if name in snapshot.columns
               and (snapshot[name] == NOT_COMPUTED).all()]
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "rows": len(snapshot),
        "borrowers": int(snapshot["borrower_id"].nunique()),
        "quarters": int(snapshot["period"].nunique()),
        "fields": len(lineage_mod.FIELDS),
        "authoritative_fields": 0,
        "authority_note": (
            "B2. Every field here is a copy of, or a derivation from, a "
            "field another domain owns. The snapshot is authoritative over "
            "nothing."),
        "graph_fields_pending": len(pending),
        "graph_fields_pending_names": sorted(pending),
        "mean_source_completeness_pct": round(
            float(snapshot["source_completeness"].mean()), 2),
        "stale_rows": int(snapshot["stale_data_flag"].sum()),
        "origin": ORIGIN,
        "not_client_data": NOT_CLIENT_DATA,
    }
