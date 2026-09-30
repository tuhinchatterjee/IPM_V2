"""
The governed latest-period portfolio view: one row per exposure, every field
useful for scenario definition, filtering, reconciliation or ECL
interpretation (§8.3), served page by page from the server.

Grain is never mixed silently: Corporate is one row per FACILITY at a
quarter; Retail one row per ACCOUNT at a month. Owner-level fields (borrower
rating, customer score movement, application score) are joined onto the
exposure row for the same period, and prior-period fields come from the same
relation one period earlier. Nothing is synthesised: a column whose source
relation the release does not publish is simply not offered.

The view is SQL this module writes, over relations the book's own catalogue
session holds. Filters arrive as typed filters (`predicates.py`) and are bound
as parameters; the period is one of the release's declared periods; a sort
column is one of the declared column keys. A request cannot name a relation,
a release, a tenant or an expression.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from backend.workspace import ews, predicates
from backend.workspace.access import Book

PAGE_MAX = 500
EXPORT_MAX = 250_000


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    expr: str
    dtype: str          # string | number | integer | flag
    unit: str           # SAR_mn | fraction | pct_points | count | days | months | notches | score | text | period
    filter: str         # text | category | range | boolean
    group: str
    description: str
    needs: str = ""     # relation alias this column requires
    visible: bool = True


def _c(key, label, expr, dtype, unit, flt, group, desc, needs="", visible=True):
    return Column(key, label, expr, dtype, unit, flt, group, desc, needs,
                  visible)


CORPORATE: tuple[Column, ...] = (
    _c("facility_id", "Facility", "f.facility_id", "string", "text", "text", "Identity", "Governed facility identifier."),
    _c("borrower_id", "Borrower ID", "f.borrower_id", "string", "text", "text", "Identity", "Governed borrower identifier."),
    _c("borrower_name", "Borrower", "f.borrower_name", "string", "text", "text", "Identity", "Borrower name (fictional, synthetic book)."),
    _c("group_name", "Group", "b.group_name", "string", "text", "category", "Identity", "Borrower group.", "b"),
    _c("sector", "Sector", "f.sector", "string", "text", "category", "Segment", "Governed sector."),
    _c("sub_sector", "Sub-sector", "f.sub_sector", "string", "text", "category", "Segment", "Governed sub-sector."),
    _c("region", "Region", "f.region", "string", "text", "category", "Segment", "Booking region."),
    _c("product_type", "Product", "f.product_type", "string", "text", "category", "Segment", "Facility product."),
    _c("facility_class", "Facility class", "f.facility_class", "string", "text", "category", "Segment", "Funded or contingent."),
    _c("relationship_tier", "Tier", "f.relationship_tier", "string", "text", "category", "Segment", "Relationship tier."),
    _c("rating_current", "Rating", "b.rating_current", "string", "text", "category", "Risk", "Borrower rating this quarter.", "b"),
    _c("rating_previous", "Prior rating", "b.rating_previous", "string", "text", "category", "Risk", "Borrower rating last quarter.", "b"),
    _c("rating_notches_moved", "Notches moved", "b.rating_notches_moved", "integer", "notches", "range", "Risk", "Positive = downgrade this quarter.", "b"),
    _c("watchlist_flag", "Watchlist", "b.watchlist_flag", "flag", "count", "boolean", "Risk", "Borrower on watchlist.", "b"),
    _c("stage", "Stage", "f.stage", "integer", "count", "category", "Stage", "IFRS 9 stage."),
    _c("prior_stage", "Prior stage", "p.stage", "integer", "count", "category", "Stage", "Stage in the previous quarter.", "p"),
    _c("sicr_flag", "SICR", "f.sicr_flag", "flag", "count", "boolean", "Stage", "Significant increase in credit risk."),
    _c("default_flag", "Default", "f.default_flag", "flag", "count", "boolean", "Stage", "In default."),
    _c("dpd_days", "DPD", "f.dpd_days", "integer", "days", "range", "Stage", "Days past due."),
    _c("limit_sar_mn", "Limit", "f.limit_sar_mn", "number", "SAR_mn", "range", "Exposure", "Approved limit."),
    _c("drawn_sar_mn", "Drawn", "f.drawn_sar_mn", "number", "SAR_mn", "range", "Exposure", "Drawn balance."),
    _c("undrawn_sar_mn", "Undrawn", "f.undrawn_sar_mn", "number", "SAR_mn", "range", "Exposure", "Undrawn commitment."),
    _c("utilisation_pct", "Utilisation", "f.utilisation_pct", "number", "pct_points", "range", "Exposure", "Drawn / limit, percent."),
    _c("ccf", "CCF", "COALESCE(i.ccf_pit, CASE WHEN f.undrawn_sar_mn > 0 THEN (f.ead_sar_mn - f.drawn_sar_mn) / f.undrawn_sar_mn END)", "number", "fraction", "range", "Risk", "Credit conversion factor (published CCF where present, else derived (EAD − drawn) / undrawn)."),
    _c("ead_sar_mn", "EAD", "f.ead_sar_mn", "number", "SAR_mn", "range", "Exposure", "Exposure at default."),
    _c("pd_pit_12m", "PD 12m", "f.pd_pit_12m", "number", "fraction", "range", "Risk", "Point-in-time 12-month PD."),
    _c("pd_lifetime", "PD lifetime", "f.pd_lifetime", "number", "fraction", "range", "Risk", "Lifetime PD."),
    _c("lgd_pct", "LGD", "f.lgd_pct", "number", "pct_points", "range", "Risk", "Loss given default, percent."),
    _c("ltv_pct", "LTV", "c.ltv_pct", "number", "pct_points", "range", "Collateral", "Loan-to-value of allocated collateral.", "c"),
    _c("collateral_value_sar_mn", "Collateral", "c.collateral_value_sar_mn", "number", "SAR_mn", "range", "Collateral", "Allocated collateral value.", "c"),
    _c("remaining_maturity_months", "Remaining maturity", "i.remaining_maturity_months", "number", "months", "range", "Risk", "Months to maturity.", "i"),
    _c("covenant_breaches", "Covenant breaches", "cov.covenant_breaches", "integer", "count", "range", "Risk", "Covenant tests in breach this quarter.", "cov"),
    _c("ecl_sar_mn", "Reported ECL", "f.ecl_sar_mn", "number", "SAR_mn", "range", "ECL", "Booked ECL."),
    _c("prior_ecl_sar_mn", "Prior ECL", "p.ecl_sar_mn", "number", "SAR_mn", "range", "ECL", "Booked ECL last quarter.", "p"),
    _c("ecl_overlay_sar_mn", "Overlay", "i.ecl_overlay_sar_mn", "number", "SAR_mn", "range", "ECL", "Management overlay within ECL.", "i", False),
)

RETAIL: tuple[Column, ...] = (
    _c("account_id", "Account", "a.account_id", "string", "text", "text", "Identity", "Governed account identifier."),
    _c("customer_id", "Customer", "a.customer_id", "string", "text", "text", "Identity", "Governed customer identifier."),
    _c("product", "Product", "a.product", "string", "text", "category", "Segment", "Retail product."),
    _c("sub_product", "Sub-product", "a.sub_product", "string", "text", "category", "Segment", "Retail sub-product."),
    _c("region", "Region", "a.region", "string", "text", "category", "Segment", "Customer region."),
    _c("customer_segment", "Segment", "a.customer_segment", "string", "text", "category", "Segment", "Customer segment."),
    _c("employment_type", "Employment", "a.employment_type", "string", "text", "category", "Segment", "Employment type."),
    _c("employer_sector_group", "Employer sector", "pr.employer_sector_group", "string", "text", "category", "Segment", "Employer sector group.", "pr"),
    _c("origination_channel", "Channel", "a.origination_channel", "string", "text", "category", "Segment", "Origination channel.", "", False),
    _c("vintage_year", "Vintage", "a.vintage_year", "integer", "count", "category", "Segment", "Origination year."),
    _c("origination_month", "Originated", "a.origination_month", "string", "period", "category", "Segment", "Origination month.", "", False),
    _c("months_on_book", "Months on book", "a.months_on_book", "integer", "months", "range", "Segment", "Months since origination."),
    _c("secured_flag", "Secured", "a.secured_flag", "flag", "count", "boolean", "Segment", "Secured product."),
    _c("application_score", "Application score", "pr.application_score", "number", "score", "range", "Scores", "Score at application.", "pr"),
    _c("behaviour_score", "Behaviour score", "a.behaviour_score", "number", "score", "range", "Scores", "Current behaviour score (higher is safer)."),
    _c("behaviour_score_change", "Score change", "cm.behaviour_score_change", "number", "score", "range", "Scores", "Change in behaviour score since last month.", "cm"),
    _c("score_band", "Score band", "a.score_band", "string", "text", "category", "Scores", "Behaviour score band (A best, E worst)."),
    _c("score_band_previous", "Prior band", "cm.score_band_previous", "string", "text", "category", "Scores", "Score band last month.", "cm"),
    _c("score_migration", "Score migration", "cm.score_migration", "string", "text", "category", "Scores", "Improved / Stable / Deteriorated.", "cm"),
    _c("delinquency_bucket", "DPD bucket", "a.delinquency_bucket", "string", "text", "category", "Stage", "Delinquency bucket."),
    _c("dpd_days", "DPD", "a.dpd_days", "integer", "days", "range", "Stage", "Days past due."),
    _c("stage", "Stage", "a.stage", "integer", "count", "category", "Stage", "IFRS 9 stage."),
    _c("prior_stage", "Prior stage", "p.stage", "integer", "count", "category", "Stage", "Stage last month.", "p"),
    _c("sicr_flag", "SICR", "a.sicr_flag", "flag", "count", "boolean", "Stage", "Significant increase in credit risk."),
    _c("default_flag", "Default", "a.default_flag", "flag", "count", "boolean", "Stage", "In default."),
    _c("limit_sar_mn", "Limit", "a.limit_sar_mn", "number", "SAR_mn", "range", "Exposure", "Approved limit."),
    _c("balance_sar_mn", "Balance", "a.balance_sar_mn", "number", "SAR_mn", "range", "Exposure", "Outstanding balance."),
    _c("utilisation_pct", "Utilisation", "a.utilisation_pct", "number", "pct_points", "range", "Exposure", "Balance / limit, percent."),
    _c("ead_sar_mn", "EAD", "a.ead_sar_mn", "number", "SAR_mn", "range", "Exposure", "Exposure at default."),
    _c("pd_pit_12m", "PD 12m", "a.pd_pit_12m", "number", "fraction", "range", "Risk", "Point-in-time 12-month PD."),
    _c("pd_lifetime", "PD lifetime", "a.pd_lifetime", "number", "fraction", "range", "Risk", "Lifetime PD."),
    _c("lgd_pct", "LGD", "a.lgd_pct", "number", "pct_points", "range", "Risk", "Loss given default, percent."),
    _c("ltv_pct", "LTV", "col.ltv_pct", "number", "pct_points", "range", "Collateral", "Loan-to-value.", "col"),
    _c("collateral_value_sar_mn", "Collateral", "col.collateral_value_sar_mn", "number", "SAR_mn", "range", "Collateral", "Collateral value.", "col"),
    _c("payment_ratio_pct", "Payment ratio", "bh.payment_ratio_pct", "number", "pct_points", "range", "Behaviour", "Payment / amount due, percent.", "bh"),
    _c("missed_payments_12m", "Missed payments 12m", "bh.missed_payments_12m", "integer", "count", "range", "Behaviour", "Missed payments over 12 months.", "bh"),
    _c("utilisation_change_pp", "Utilisation change", "bh.utilisation_change_pp", "number", "pct_points", "range", "Behaviour", "Change in utilisation, points.", "bh", False),
    _c("remaining_maturity_months", "Remaining maturity", "i.remaining_maturity_months", "number", "months", "range", "Risk", "Months to maturity.", "i", False),
    _c("ecl_sar_mn", "Reported ECL", "a.ecl_sar_mn", "number", "SAR_mn", "range", "ECL", "Booked ECL."),
    _c("prior_ecl_sar_mn", "Prior ECL", "p.ecl_sar_mn", "number", "SAR_mn", "range", "ECL", "Booked ECL last month.", "p"),
    _c("ecl_overlay_sar_mn", "Overlay", "i.ecl_overlay_sar_mn", "number", "SAR_mn", "range", "ECL", "Management overlay within ECL.", "i", False),
)

#: The derived EWS columns every grid carries (governed rule set, ews.py).
EWS_COLUMNS = (
    Column("ews_score", "EWS score", "", "integer", "score", "range", "Early warning",
           f"Sum of triggered rule weights ({ews.RULESET_VERSION})."),
    Column("ews_band", "EWS severity", "", "string", "text", "category", "Early warning",
           "none / low / moderate / high / critical."),
    Column("ews_reasons", "EWS reasons", "", "string", "text", "text", "Early warning",
           "Rules this exposure trips.", "", False),
)

SPEC = {
    "corporate": {"columns": CORPORATE, "key": "facility_id",
                  "owner": "borrower_id", "relation": "corp_facility_quarter",
                  "noun": "facility", "plural": "facilities",
                  "owner_plural": "borrowers", "period_col": "reporting_quarter"},
    "retail": {"columns": RETAIL, "key": "account_id", "owner": "customer_id",
               "relation": "retail_account_month", "noun": "account",
               "plural": "accounts", "owner_plural": "customers",
               "period_col": "reporting_month"},
}

_PERIOD = re.compile(r"^[0-9A-Za-z\-]{4,10}$")


def _period(book: Book, period: str = "") -> tuple[str, str]:
    periods = book.periods
    chosen = period or book.latest_period
    if chosen not in periods or not _PERIOD.match(chosen):
        raise HTTPException(422, {"error_code": "UNKNOWN_PERIOD",
                                  "message": f"{chosen!r} is not a reporting "
                                             f"period of this release."})
    index = periods.index(chosen)
    return chosen, periods[index - 1] if index > 0 else ""


def _joins(domain_id: str, period: str, prev: str,
           relations: set[str]) -> tuple[str, set[str]]:
    """The FROM clause and the aliases it could honour."""
    have: set[str] = set()
    if domain_id == "corporate":
        sql = "FROM corp_facility_quarter f"
        if "corp_borrower_quarter" in relations:
            sql += (" LEFT JOIN corp_borrower_quarter b ON b.borrower_id = "
                    "f.borrower_id AND b.reporting_quarter = f.reporting_quarter")
            have.add("b")
        if prev:
            sql += (f" LEFT JOIN corp_facility_quarter p ON p.facility_id = "
                    f"f.facility_id AND p.reporting_quarter = '{prev}'")
            have.add("p")
        if "corp_collateral_quarter" in relations:
            sql += (" LEFT JOIN (SELECT facility_id, SUM(allocated_value_sar_mn)"
                    " AS collateral_value_sar_mn, AVG(ltv_pct) AS ltv_pct FROM "
                    f"corp_collateral_quarter WHERE reporting_quarter = '{period}'"
                    " GROUP BY 1) c ON c.facility_id = f.facility_id")
            have.add("c")
        if "corp_covenant_quarter" in relations:
            sql += (" LEFT JOIN (SELECT facility_id, SUM(breach_flag) AS "
                    "covenant_breaches FROM corp_covenant_quarter WHERE "
                    f"reporting_quarter = '{period}' GROUP BY 1) cov ON "
                    "cov.facility_id = f.facility_id")
            have.add("cov")
        if "whatif_corp_ifrs9" in relations:
            sql += (" LEFT JOIN whatif_corp_ifrs9 i ON i.facility_id = "
                    "f.facility_id AND i.reporting_quarter = f.reporting_quarter")
            have.add("i")
        return sql + f" WHERE f.reporting_quarter = '{period}'", have
    sql = "FROM retail_account_month a"
    if "retail_customer_month" in relations:
        sql += (" LEFT JOIN retail_customer_month cm ON cm.customer_id = "
                "a.customer_id AND cm.reporting_month = a.reporting_month")
        have.add("cm")
    if prev:
        sql += (f" LEFT JOIN retail_account_month p ON p.account_id = "
                f"a.account_id AND p.reporting_month = '{prev}'")
        have.add("p")
    if "retail_behaviour_month" in relations:
        sql += (" LEFT JOIN retail_behaviour_month bh ON bh.account_id = "
                "a.account_id AND bh.reporting_month = a.reporting_month")
        have.add("bh")
    if "retail_collateral_month" in relations:
        sql += (" LEFT JOIN (SELECT account_id, SUM(collateral_value_sar_mn) AS"
                " collateral_value_sar_mn, AVG(ltv_pct) AS ltv_pct FROM "
                f"retail_collateral_month WHERE reporting_month = '{period}' "
                "GROUP BY 1) col ON col.account_id = a.account_id")
        have.add("col")
    if "whatif_retail_profile" in relations:
        sql += (" LEFT JOIN whatif_retail_profile pr ON pr.customer_id = "
                "a.customer_id AND pr.reporting_month = a.reporting_month")
        have.add("pr")
    if "whatif_retail_ifrs9" in relations:
        sql += (" LEFT JOIN whatif_retail_ifrs9 i ON i.account_id = "
                "a.account_id AND i.reporting_month = a.reporting_month")
        have.add("i")
    return sql + f" WHERE a.reporting_month = '{period}'", have


@dataclass(frozen=True)
class View:
    domain_id: str
    period: str
    prior_period: str
    sql: str
    columns: tuple[Column, ...]
    key: str
    owner: str

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(c.key for c in self.columns)


def view(book: Book, period: str = "") -> View:
    spec = SPEC[book.domain_id]
    chosen, prev = _period(book, period)
    relations = set(getattr(book.session, "relations", ()) or ())
    from_sql, have = _joins(book.domain_id, chosen, prev, relations)
    base_cols = tuple(c for c in spec["columns"]
                      if not c.needs or c.needs in have)
    select = ", ".join(f"{c.expr} AS {c.key}" for c in base_cols)
    base = f"SELECT {select} {from_sql}"
    available = {c.key for c in base_cols}
    score, reasons = ews.score_sql(book.domain_id, available)
    with_ews = (f"SELECT g0.*, ({score}) AS ews_score, {reasons} AS ews_reasons "
                f"FROM ({base}) g0")
    full = (f"SELECT g1.*, {ews.band_sql('g1.ews_score')} AS ews_band "
            f"FROM ({with_ews}) g1")
    return View(domain_id=book.domain_id, period=chosen, prior_period=prev,
                sql=full, columns=base_cols + EWS_COLUMNS, key=spec["key"],
                owner=spec["owner"])


def schema(book: Book, period: str = "") -> dict[str, Any]:
    v = view(book, period)
    spec = SPEC[book.domain_id]
    return {
        "domain_id": book.domain_id, "release_id": book.release_id,
        "fingerprint": book.fingerprint, "period": v.period,
        "prior_period": v.prior_period, "periods": book.periods,
        "grain": spec["noun"], "grain_plural": spec["plural"],
        "owner_plural": spec["owner_plural"], "key": v.key, "owner": v.owner,
        "ews_ruleset": ews.RULESET_VERSION,
        "ews_rules": ews.describe(book.domain_id),
        "columns": [{"key": c.key, "label": c.label, "type": c.dtype,
                     "unit": c.unit, "filter": c.filter, "group": c.group,
                     "description": c.description, "visible": c.visible}
                    for c in v.columns],
    }


def _where(v: View, filters: Any) -> tuple[str, list[Any], list[dict[str, Any]]]:
    checked = predicates.normalise(filters, columns=v.keys)
    sql, params = predicates.bound(checked)
    return (f"WHERE {sql}" if sql else ""), params, checked


def _num(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def query(book: Book, *, filters: Any = None, sort: str = "", desc: bool = True,
          offset: int = 0, limit: int = 50, period: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    v = view(book, period)
    where, params, checked = _where(v, filters)
    sort_key = sort if sort in v.keys else "ecl_sar_mn"
    limit = max(1, min(int(limit), PAGE_MAX))
    offset = max(0, int(offset))
    order = f"ORDER BY {sort_key} {'DESC' if desc else 'ASC'} NULLS LAST, {v.key}"
    rows = book.rows(f"SELECT * FROM ({v.sql}) g {where} {order} LIMIT ? OFFSET ?",
                     params + [limit, offset])
    agg = summary(book, v=v, where=where, params=params)
    return {
        "domain_id": book.domain_id, "release_id": book.release_id,
        "fingerprint": book.fingerprint, "period": v.period,
        "filters": checked, "filter_description": predicates.describe(checked),
        "sort": sort_key, "desc": desc, "offset": offset, "limit": limit,
        "rows": [{k: _num(val) for k, val in r.items()} for r in rows],
        "total": agg["entities"], "summary": agg,
        "server_ms": int((time.perf_counter() - started) * 1000),
    }


def summary(book: Book, *, v: View, where: str, params: list[Any]
            ) -> dict[str, Any]:
    head = book.rows(
        f"SELECT COUNT(*) AS entities, COUNT(DISTINCT {v.owner}) AS owners, "
        f"COALESCE(SUM(ead_sar_mn), 0) AS ead, COALESCE(SUM(ecl_sar_mn), 0) "
        f"AS ecl FROM ({v.sql}) g {where}", params)[0]
    stages = book.rows(
        f"SELECT stage, COUNT(*) AS n, SUM(ead_sar_mn) AS ead, "
        f"SUM(ecl_sar_mn) AS ecl FROM ({v.sql}) g {where} GROUP BY 1 "
        f"ORDER BY 1", params)
    band_col = "rating_current" if book.domain_id == "corporate" else "score_band"
    bands = []
    if band_col in v.keys:
        bands = book.rows(
            f"SELECT {band_col} AS band, COUNT(*) AS n, SUM(ead_sar_mn) AS ead"
            f" FROM ({v.sql}) g {where} GROUP BY 1 ORDER BY 1", params)
    return {"entities": int(head["entities"] or 0),
            "owners": int(head["owners"] or 0),
            "ead": float(head["ead"] or 0), "ecl": float(head["ecl"] or 0),
            "stage_mix": [{k: _num(x) for k, x in s.items()} for s in stages],
            "band_dimension": band_col,
            "band_mix": [{k: _num(x) for k, x in s.items()} for s in bands],
            "period": v.period}


def distinct(book: Book, column: str, *, search: str = "", limit: int = 200,
             period: str = "") -> dict[str, Any]:
    v = view(book, period)
    if column not in v.keys:
        raise HTTPException(422, {"error_code": "INVALID_FILTER",
                                  "message": f"{column!r} is not a grid column."})
    params: list[Any] = []
    where = ""
    if search:
        checked = predicates.normalise(
            [{"column": column, "op": "contains", "value": search}],
            columns=v.keys)
        where, params = predicates.bound(checked)
        where = f"WHERE {where}"
    rows = book.rows(
        f"SELECT {column} AS value, COUNT(*) AS n FROM ({v.sql}) g {where} "
        f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?",
        params + [max(1, min(int(limit), 1000))])
    return {"column": column, "values": [{"value": _num(r["value"]),
                                          "count": int(r["n"])} for r in rows]}


def rows_for(book: Book, *, filters: Any = None, period: str = "",
             columns: list[str] | None = None, limit: int = EXPORT_MAX
             ) -> tuple[View, list[dict[str, Any]], list[dict[str, Any]]]:
    v = view(book, period)
    where, params, checked = _where(v, filters)
    wanted = [c for c in (columns or list(v.keys)) if c in v.keys]
    rows = book.rows(
        f"SELECT {', '.join(wanted)} FROM ({v.sql}) g {where} "
        f"ORDER BY {v.key} LIMIT ?", params + [int(limit)])
    return v, checked, [{k: _num(x) for k, x in r.items()} for r in rows]


def grouped(book: Book, *, dimension: str, filters: Any = None,
            period: str = "", measures: tuple[str, ...] = ("ead_sar_mn",
                                                          "ecl_sar_mn")
            ) -> list[dict[str, Any]]:
    """Aggregates by one governed dimension, for charts and drill-downs."""
    v = view(book, period)
    if dimension not in v.keys:
        raise HTTPException(422, {"error_code": "INVALID_FILTER",
                                  "message": f"{dimension!r} is not a grid "
                                             f"column."})
    where, params, _ = _where(v, filters)
    sums = ", ".join(f"SUM({m}) AS {m}" for m in measures if m in v.keys)
    rows = book.rows(
        f"SELECT {dimension} AS value, COUNT(*) AS n, {sums} FROM ({v.sql}) g "
        f"{where} GROUP BY 1 ORDER BY 1", params)
    return [{k: _num(x) for k, x in r.items()} for r in rows]


__all__ = ["CORPORATE", "Column", "EWS_COLUMNS", "RETAIL", "SPEC", "View",
           "distinct", "grouped", "query", "rows_for", "schema", "summary",
           "view"]
