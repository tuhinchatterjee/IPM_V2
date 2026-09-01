"""Where every Borrower 360 field comes from. B5.

B2's rule is that the snapshot must not become authoritative over the domain
it copied from. A rule like that is not kept by intention; it is kept by
making the copy carry its origin everywhere it goes. So every field in the
Borrower 360 has an entry here naming:

    source_domain      the governed domain that owns it
    source_dataset     the physical dataset inside it
    source_field       the column, under the name that dataset uses
    source_period      which period's row was read - not always the snapshot's
    transformation     what was done to it between there and here
    authority          AUTHORITATIVE, COPY or DERIVED
    validation_status  whether the source passed its own checks

`AUTHORITATIVE` appears exactly nowhere in this table. That is deliberate and
is the point of B2: the snapshot is a fast denormalised READ, and every field
in it is a copy or a derivation. A field marked authoritative here would be a
field the snapshot had quietly taken ownership of.

`source_period` is the field people get wrong. A borrower's leverage in
Q2 2025 comes from the FY2024 statement, which is a different period from the
snapshot's; showing it as a Q2 2025 number without saying so is how a
year-old ratio gets quoted as current.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.corporate import domains as domains_mod

LINEAGE_VERSION = "1.0.0"

COPY = "COPY"
DERIVED = "DERIVED"
#: Never used. Present so the vocabulary is complete and a reader can see the
#: value that is deliberately absent.
AUTHORITATIVE = "AUTHORITATIVE"

AUTHORITY_KINDS: tuple[str, ...] = (AUTHORITATIVE, COPY, DERIVED)

#: How the period of the source row relates to the snapshot's own period.
SAME_QUARTER = "same quarter"
LATEST_PUBLISHED = "latest statement published on or before the quarter end"
AS_OF_QUARTER_END = "graph as at the quarter end, on the B16 predicate"
NOT_PERIODIC = "not periodic - a standing attribute"


@dataclass(frozen=True)
class Field:
    """One Borrower 360 field and its provenance."""

    name: str
    group: str
    source_domain: str
    source_dataset: str
    source_field: str
    source_period: str
    transformation: str
    authority: str = COPY
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.name,
            "group": self.group,
            "source_domain": self.source_domain,
            "source_dataset": self.source_dataset,
            "source_field": self.source_field,
            "source_period": self.source_period,
            "transformation": self.transformation,
            "authority": self.authority,
            "unit": self.unit,
            #: What VIEW SOURCE opens. B5: a metric click has to land on the
            #: exact Data Builder object, not on a domain landing page.
            "view_source": {
                "dataset": self.source_dataset,
                "field": self.source_field,
                "domain": self.source_domain,
            },
        }


def _identity(name: str, source_field: str = "",
              transformation: str = "copied unchanged") -> Field:
    return Field(name, "IDENTITY", "CORPORATE CUSTOMER MASTER",
                 "corporate_customer_master", source_field or name,
                 SAME_QUARTER, transformation)


def _rating(name: str, source_field: str = "", unit: str = "",
            transformation: str = "copied unchanged") -> Field:
    return Field(name, "RATING", "CORPORATE RATINGS", "corporate_ratings",
                 source_field or name, SAME_QUARTER, transformation,
                 unit=unit)


def _financial(name: str, source_field: str = "", unit: str = "SAR millions",
               transformation: str = "copied unchanged") -> Field:
    return Field(name, "FINANCIALS", "CORPORATE FINANCIALS",
                 "corporate_financials", source_field or name,
                 LATEST_PUBLISHED, transformation, unit=unit)


def _exposure(name: str, source_field: str, transformation: str,
              unit: str = "SAR millions",
              authority: str = DERIVED) -> Field:
    return Field(name, "EXPOSURE", "CORPORATE FACILITIES / EXPOSURE",
                 "corporate_facilities", source_field, SAME_QUARTER,
                 transformation, authority, unit)


def _ifrs9(name: str, source_field: str = "", unit: str = "",
           transformation: str = "copied unchanged") -> Field:
    return Field(name, "IFRS9", "CORPORATE IFRS 9", "corporate_ifrs9",
                 source_field or name, SAME_QUARTER, transformation,
                 unit=unit)


def _delinquency(name: str, source_field: str = "", unit: str = "",
                 transformation: str = "copied unchanged") -> Field:
    return Field(name, "DELINQUENCY", "CORPORATE DPD / DELINQUENCY",
                 "corporate_delinquency", source_field or name, SAME_QUARTER,
                 transformation, unit=unit)


def _graph(name: str, dataset: str, source_field: str,
           transformation: str) -> Field:
    return Field(name, "GRAPH SUMMARY",
                 domains_mod.DATASET_DOMAIN.get(dataset, "CORPORATE GRAPH"),
                 dataset, source_field, AS_OF_QUARTER_END, transformation,
                 DERIVED)


FIELDS: tuple[Field, ...] = (
    # ---- identity --------------------------------------------------------
    _identity("borrower_id"),
    _identity("customer_number"),
    _identity("legal_name"),
    _identity("display_name"),
    _identity("alias"),
    _identity("arabic_name"),
    _identity("segment"),
    _identity("sub_segment"),
    _identity("sector"),
    _identity("sub_sector"),
    _identity("region"),
    _identity("city"),
    _identity("country"),
    _identity("legal_form"),
    _identity("incorporation_date"),
    _identity("relationship_start_date"),
    _identity("relationship_manager"),
    _identity("business_unit"),
    _identity("status"),
    Field("group_id", "IDENTITY", "CORPORATE CONNECTED COUNTERPARTY GRAPH",
          "corporate_connected_groups", "connected_group_id",
          AS_OF_QUARTER_END,
          "the connected group this borrower was placed in, as at the "
          "quarter end", DERIVED),
    Field("group_name", "IDENTITY", "CORPORATE CONNECTED COUNTERPARTY GRAPH",
          "corporate_connected_groups", "group_name", AS_OF_QUARTER_END,
          "the label of that group", DERIVED),

    # ---- rating ----------------------------------------------------------
    _rating("internal_rating"),
    _rating("internal_rating_numeric"),
    _rating("previous_rating"),
    _rating("rating_change_notches", unit="notches"),
    _rating("rating_direction"),
    _rating("rating_date"),
    _rating("rating_model"),
    _rating("rating_override_flag"),
    _rating("watchlist_flag"),
    _rating("external_rating"),
    _rating("rating_outlook"),

    # ---- financials ------------------------------------------------------
    _financial("revenue"),
    _financial("revenue_growth", unit="%"),
    _financial("ebitda"),
    _financial("ebitda_margin", unit="%"),
    _financial("ebit"),
    _financial("net_income"),
    _financial("total_assets"),
    _financial("total_liabilities"),
    _financial("book_equity"),
    _financial("cash"),
    _financial("working_capital"),
    _financial("capex"),
    _financial("receivable_days", unit="days"),
    _financial("inventory_days", unit="days"),
    _financial("payable_days", unit="days"),
    _financial("cash_conversion_cycle_days", unit="days"),
    _financial("short_term_debt"),
    _financial("long_term_debt"),
    _financial("debt"),
    _financial("net_debt"),
    _financial("leverage", unit="x"),
    _financial("net_leverage", unit="x"),
    _financial("dscr", unit="x"),
    _financial("interest_coverage", unit="x"),
    _financial("current_ratio", unit="x"),
    _financial("quick_ratio", unit="x"),
    _financial("debt_to_equity", unit="x"),
    _financial("cash_flow_from_operations"),
    _financial("free_cash_flow"),
    _financial("financial_statement_date", unit=""),
    Field("financial_statement_age_days", "FINANCIALS",
          "CORPORATE FINANCIALS", "corporate_financials",
          "financial_statement_date", LATEST_PUBLISHED,
          "quarter end minus the statement date, in days", DERIVED, "days"),

    # ---- exposure --------------------------------------------------------
    _exposure("total_limit", "limit_amount",
              "sum of limit_amount over the borrower's facilities"),
    _exposure("total_outstanding", "drawn_exposure",
              "sum of drawn_exposure over the borrower's facilities"),
    _exposure("drawn_exposure", "drawn_exposure", "sum over facilities"),
    _exposure("committed_limit", "committed_limit",
              "Summed across the borrower's facilities."),
    _exposure("undrawn_committed", "undrawn_committed",
              "Summed across the borrower's facilities."),
    _exposure("maturing_0_3m", "maturing_0_3m",
              "Summed across the borrower's facilities."),
    _exposure("maturing_3_6m", "maturing_3_6m",
              "Summed across the borrower's facilities."),
    _exposure("maturing_6_12m", "maturing_6_12m",
              "Summed across the borrower's facilities."),
    _exposure("maturing_within_12m", "maturing_within_12m",
              "Summed across the borrower's facilities."),
    _exposure("undrawn_commitment", "undrawn_commitment",
              "sum over facilities"),
    _exposure("ifrs9_ead", "ifrs9_ead",
              "sum of drawn plus undrawn at the facility's credit "
              "conversion factor"),
    _exposure("funded_exposure", "funded_exposure", "sum over facilities"),
    _exposure("unfunded_exposure", "unfunded_exposure", "sum over facilities"),
    _exposure("trade_finance_exposure", "trade_finance_exposure",
              "sum over facilities"),
    _exposure("guarantee_exposure", "guarantee_exposure",
              "sum over facilities"),
    _exposure("secured_exposure", "secured_exposure", "sum over facilities"),
    _exposure("unsecured_exposure", "unsecured_exposure",
              "sum over facilities"),
    _exposure("largest_facility", "limit_amount",
              "maximum limit_amount over the borrower's facilities"),
    _exposure("facility_count", "facility_id",
              "count of the borrower's facilities", unit="count"),
    _exposure("currency", "currency",
              "currency of the largest facility", unit=""),

    # ---- IFRS 9 ----------------------------------------------------------
    _ifrs9("stage"),
    _ifrs9("sicr_flag"),
    _ifrs9("pd_12m", unit="%"),
    _ifrs9("pd_lifetime", unit="%"),
    _ifrs9("lgd", unit="%"),
    _ifrs9("ead", unit="SAR millions"),
    _ifrs9("ecl_12m", unit="SAR millions"),
    _ifrs9("ecl_lifetime", unit="SAR millions"),
    _ifrs9("final_ecl", unit="SAR millions"),
    _ifrs9("ecl_coverage", unit="%"),
    _ifrs9("management_overlay", unit="SAR millions"),
    _ifrs9("default_flag"),
    Field("scenario_weight", "IFRS9", "CORPORATE IFRS 9", "corporate_ifrs9",
          "scenario_weight_base", SAME_QUARTER,
          "the base-scenario weight; the upside and downside weights are "
          "separate fields in the source", COPY),
    Field("restructure_flag", "IFRS9", "CORPORATE RESTRUCTURING / FORBEARANCE",
          "corporate_restructuring", "restructure_flag", SAME_QUARTER,
          "true if any concession is recorded for this borrower-quarter",
          DERIVED),
    Field("forbearance_flag", "IFRS9",
          "CORPORATE RESTRUCTURING / FORBEARANCE", "corporate_restructuring",
          "forbearance_flag", SAME_QUARTER,
          "true if any concession was granted for credit reasons", DERIVED),

    # ---- delinquency -----------------------------------------------------
    _delinquency("current_dpd", unit="days"),
    _delinquency("max_dpd_3m", unit="days"),
    _delinquency("max_dpd_12m", unit="days"),
    _delinquency("days_since_last_payment", unit="days"),
    _delinquency("arrears_amount", unit="SAR millions"),
    _delinquency("delinquency_bucket"),
    _delinquency("number_of_missed_payments_12m", unit="count"),
    _delinquency("collections_flag"),

    # ---- covenants -------------------------------------------------------
    Field("covenant_count", "COVENANTS", "CORPORATE COVENANTS",
          "corporate_covenants", "covenant_id", SAME_QUARTER,
          "count of covenants the borrower is subject to", DERIVED, "count"),
    Field("covenants_tested", "COVENANTS", "CORPORATE COVENANTS",
          "corporate_covenants", "covenant_id", SAME_QUARTER,
          "count of covenants with a test in this quarter", DERIVED, "count"),
    Field("covenants_breached", "COVENANTS", "CORPORATE COVENANTS",
          "corporate_covenants", "breach_flag", SAME_QUARTER,
          "count of tests where headroom_pct is negative", DERIVED, "count"),
    Field("minimum_headroom_pct", "COVENANTS", "CORPORATE COVENANTS",
          "corporate_covenants", "headroom_pct", SAME_QUARTER,
          "smallest headroom across the borrower's tests", DERIVED, "%"),
    Field("average_headroom_pct", "COVENANTS", "CORPORATE COVENANTS",
          "corporate_covenants", "headroom_pct", SAME_QUARTER,
          "mean headroom across the borrower's tests", DERIVED, "%"),
    Field("next_test_date", "COVENANTS", "CORPORATE COVENANTS",
          "corporate_covenants", "next_test_date", SAME_QUARTER,
          "earliest next test date across the borrower's covenants", DERIVED),
    Field("breach_flag", "COVENANTS", "CORPORATE COVENANTS",
          "corporate_covenants", "breach_flag", SAME_QUARTER,
          "true if any test breached", DERIVED),

    # ---- collateral ------------------------------------------------------
    Field("collateral_count", "COLLATERAL", "CORPORATE COLLATERAL",
          "corporate_collateral", "collateral_id", SAME_QUARTER,
          "count of collateral items held", DERIVED, "count"),
    Field("collateral_market_value", "COLLATERAL", "CORPORATE COLLATERAL",
          "corporate_collateral", "collateral_market_value", SAME_QUARTER,
          "sum over the borrower's collateral", DERIVED, "SAR millions"),
    Field("collateral_eligible_value", "COLLATERAL", "CORPORATE COLLATERAL",
          "corporate_collateral", "collateral_eligible_value", SAME_QUARTER,
          "sum of market value after the regulatory haircut for each type",
          DERIVED, "SAR millions"),
    Field("collateral_coverage_pct", "COLLATERAL", "CORPORATE COLLATERAL",
          "corporate_collateral", "collateral_eligible_value", SAME_QUARTER,
          "eligible collateral over secured exposure - the ELIGIBLE value, "
          "not the market value", DERIVED, "%"),
    Field("collateral_shortfall", "COLLATERAL", "CORPORATE COLLATERAL",
          "corporate_collateral", "collateral_eligible_value", SAME_QUARTER,
          "secured exposure less eligible collateral, floored at zero",
          DERIVED, "SAR millions"),
    Field("last_valuation_date", "COLLATERAL", "CORPORATE COLLATERAL",
          "corporate_collateral", "last_valuation_date", SAME_QUARTER,
          "most recent valuation date across the borrower's collateral",
          DERIVED),
    Field("valuation_age_days", "COLLATERAL", "CORPORATE COLLATERAL",
          "corporate_collateral", "valuation_age_days", SAME_QUARTER,
          "the OLDEST valuation age, not the newest - the stalest piece of "
          "security is the one that matters", DERIVED, "days"),

    # ---- limits ----------------------------------------------------------
    Field("single_name_utilisation_pct", "LIMIT",
          "CORPORATE LIMITS / LARGE EXPOSURES", "corporate_limits",
          "single_name_utilisation_pct", SAME_QUARTER, "copied unchanged",
          COPY, "%"),
    Field("group_utilisation_pct", "LIMIT",
          "CORPORATE LIMITS / LARGE EXPOSURES", "corporate_limits",
          "group_utilisation_pct", AS_OF_QUARTER_END,
          "sum of the connected group's exposure over the eligible capital "
          "reference; needs the graph, so it is empty until the group has "
          "been formed", DERIVED, "%"),
    Field("eligible_capital_reference", "LIMIT",
          "CORPORATE LIMITS / LARGE EXPOSURES", "corporate_limits",
          "eligible_capital_reference", NOT_PERIODIC,
          'a seeded value, not a verified regulatory figure - B55',
          COPY, "SAR millions"),
    Field("limit_status", "LIMIT", "CORPORATE LIMITS / LARGE EXPOSURES",
          "corporate_limits", "limit_status", SAME_QUARTER,
          "copied unchanged", COPY),
    Field("investigation_trigger", "LIMIT",
          "CORPORATE LIMITS / LARGE EXPOSURES", "corporate_limits",
          "investigation_trigger", SAME_QUARTER, "copied unchanged", COPY),
    Field("sector_concentration_share", "LIMIT",
          "CORPORATE FACILITIES / EXPOSURE", "corporate_facilities",
          "ifrs9_ead", SAME_QUARTER,
          "the borrower's exposure as a share of its sector's exposure in "
          "the same quarter", DERIVED, "%"),

    # ---- graph summary ---------------------------------------------------
    _graph("effective_ownership_group_id", "corporate_connected_groups",
           "effective_ownership_group_id",
           "the group formed by effective ownership above the threshold"),
    _graph("control_group_id", "corporate_connected_groups",
           "control_group_id",
           "the group formed by control closure, which is not the same set "
           "as proportional ownership - B54"),
    _graph("connected_group_id", "corporate_connected_groups",
           "connected_group_id", "the connected-counterparty group"),
    _graph("connected_group_size", "corporate_connected_groups",
           "connected_group_size", "member count of that group"),
    _graph("group_role", "corporate_connected_groups", "group_role",
           "PARENT, SUBSIDIARY, AFFILIATE or STANDALONE"),
    _graph("ubo_count", "corporate_ownership_edges", "from_node",
           "distinct natural persons whose effective ownership clears the "
           "beneficial-ownership threshold"),
    _graph("director_count", "corporate_ownership_edges", "from_node",
           "count of DIRECTOR_OF edges valid as at the quarter end"),
    _graph("supplier_count", "corporate_supply_chain", "from_node",
           "count of SUPPLIES_TO edges into this borrower"),
    _graph("customer_count", "corporate_supply_chain", "to_node",
           "count of SUPPLIES_TO edges out of this borrower"),
    _graph("guarantee_links", "corporate_guarantees", "guarantee_id",
           "guarantees given or received"),
    _graph("exposure_network_links", "corporate_exposure_network",
           "edge_id", "financial claims to or from this borrower"),
    _graph("network_risk_score", "corporate_connected_groups",
           "network_risk_score",
           "a weighted rank of DebtRank, PageRank and betweenness. A "
           "RANKING, not a probability - B54"),
    _graph("pagerank_transmits", "corporate_connected_groups",
           "pagerank_transmits", "PageRank on the outgoing direction"),
    _graph("pagerank_hurt", "corporate_connected_groups", "pagerank_hurt",
           "PageRank on the reversed graph"),
    _graph("betweenness", "corporate_connected_groups", "betweenness",
           "normalised betweenness centrality"),
    _graph("debtrank_impact", "corporate_connected_groups",
           "debtrank_impact",
           "DebtRank impact. Not a capital or ECL methodology - B54"),
    _graph("louvain_community", "corporate_connected_groups",
           "louvain_community", "community label from modularity "
           "optimisation"),
    _graph("graph_confidence", "corporate_graph_dq", "graph_confidence",
           "the weakest confidence on the evidence chain that placed this "
           "borrower in its group"),
    _graph("graph_dq_status", "corporate_graph_dq", "graph_dq_status",
           "OK, DEGRADED or INSUFFICIENT"),

    # ---- data quality ----------------------------------------------------
    Field("source_completeness", "DATA QUALITY",
          "CORPORATE GRAPH DATA QUALITY", "corporate_graph_dq",
          "source_completeness", SAME_QUARTER,
          "share of the Borrower 360 fields that resolved to a source row",
          DERIVED, "%"),
    Field("relationship_confidence", "DATA QUALITY",
          "CORPORATE GRAPH DATA QUALITY", "corporate_graph_dq",
          "relationship_confidence", AS_OF_QUARTER_END,
          "mean confidence of the graph edges touching this borrower",
          DERIVED),
    Field("stale_data_flag", "DATA QUALITY", "CORPORATE FINANCIALS",
          "corporate_financials", "financial_statement_date",
          LATEST_PUBLISHED,
          "true when the latest statement is more than 540 days old or the "
          "oldest collateral valuation is past its revaluation interval",
          DERIVED),
    Field("dq_issue_count", "DATA QUALITY", "CORPORATE GRAPH DATA QUALITY",
          "corporate_graph_dq", "dq_issue_count", SAME_QUARTER,
          "count of open data-quality issues against this borrower",
          DERIVED, "count"),
    Field("snapshot_validation_status", "DATA QUALITY",
          "CORPORATE GRAPH DATA QUALITY", "corporate_graph_dq",
          "snapshot_validation_status", SAME_QUARTER,
          "PASSED, PASSED WITH ISSUES or FAILED", DERIVED),
)

BY_NAME: dict[str, Field] = {f.name: f for f in FIELDS}

GROUPS: tuple[str, ...] = (
    "IDENTITY", "RATING", "FINANCIALS", "EXPOSURE", "IFRS9", "DELINQUENCY",
    "COVENANTS", "COLLATERAL", "LIMIT", "GRAPH SUMMARY", "DATA QUALITY",
)


def get(name: str) -> Field:
    try:
        return BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"'{name}' is not a Borrower 360 field. The snapshot carries "
            f"{len(FIELDS)} fields; nothing may appear on the screen that is "
            "not one of them, because a field with no lineage entry has no "
            "provenance to show.") from None


def by_group() -> dict[str, list[Field]]:
    out: dict[str, list[Field]] = {group: [] for group in GROUPS}
    for entry in FIELDS:
        out[entry.group].append(entry)
    return out


def catalogue() -> dict[str, Any]:
    """B5, for the screen and for a report."""
    counts = {group: len(items) for group, items in by_group().items()}
    return {
        "lineage_version": LINEAGE_VERSION,
        "field_count": len(FIELDS),
        "groups": list(GROUPS),
        "fields_per_group": counts,
        "by_authority": {
            kind: sum(1 for f in FIELDS if f.authority == kind)
            for kind in AUTHORITY_KINDS},
        "authoritative_field_count": sum(
            1 for f in FIELDS if f.authority == AUTHORITATIVE),
        "why_no_authoritative_fields": (
            "B2. The Borrower 360 snapshot is a denormalised READ. Every "
            "field in it is a copy of, or a derivation from, a field some "
            "other domain owns. A field marked AUTHORITATIVE here would be a "
            "field the snapshot had taken ownership of, and the domain that "
            "owns it would no longer be the last word on its own number."),
        "source_domains": sorted({f.source_domain for f in FIELDS}),
        "source_datasets": sorted({f.source_dataset for f in FIELDS}),
        "fields": [f.to_dict() for f in FIELDS],
    }
