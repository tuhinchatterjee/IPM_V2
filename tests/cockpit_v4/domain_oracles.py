"""
Independent pandas oracles for the two books.

Independent means: these read the published Parquet directly with pandas and
compute the figure from the column definitions, in a different engine and a
different code path. Nothing here imports the catalogue, opens the DuckDB
session, or runs any SQL the product generates. An oracle that calls the code
under test proves the code is self-consistent, which is exactly what a wrong
answer also is.
"""

from __future__ import annotations

import pandas as pd

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake


def frame(domain_id: str, relation: str) -> pd.DataFrame:
    return pd.read_parquet(
        lake.relation_path(dom.DEFAULT_RELEASES[domain_id], relation))


def months(domain_id: str, relation: str) -> list[str]:
    return sorted(frame(domain_id, relation)["reporting_month"].unique())


def latest_month(domain_id: str) -> str:
    relation = ("corp_facility_month" if domain_id == dom.CORPORATE
                else "retail_account_month")
    return months(domain_id, relation)[-1]


def previous_month(domain_id: str) -> str:
    relation = ("corp_facility_month" if domain_id == dom.CORPORATE
                else "retail_account_month")
    return months(domain_id, relation)[-2]


def _month(domain_id: str, relation: str, month: str) -> pd.DataFrame:
    data = frame(domain_id, relation)
    return data[data["reporting_month"] == month]


# ---- shared shapes -----------------------------------------------------

def sum_by(domain_id: str, relation: str, month: str, dimension: str,
           measure: str) -> dict[str, float]:
    rows = _month(domain_id, relation, month)
    return {str(k): float(v) for k, v in
            rows.groupby(dimension, observed=True)[measure].sum().items()}


def total(domain_id: str, relation: str, month: str,
          measure: str) -> float:
    return float(_month(domain_id, relation, month)[measure].sum())


def share_by(domain_id: str, relation: str, month: str, dimension: str, *,
             measure: str, condition) -> dict[str, float]:
    """The measure meeting a row condition, over the measure. Per dimension."""
    rows = _month(domain_id, relation, month)
    out: dict[str, float] = {}
    for key, group in rows.groupby(dimension, observed=True):
        base = float(group[measure].sum())
        if base <= 0:
            continue
        hit = float(group.loc[condition(group), measure].sum())
        out[str(key)] = hit / base
    return out


# ---- corporate ---------------------------------------------------------

def corp_ead_by_sector(month: str) -> dict[str, float]:
    return sum_by(dom.CORPORATE, "corp_facility_month", month, "sector",
                  "ead_sar_mn")


def corp_stage2_share_by_sector(month: str) -> dict[str, float]:
    return share_by(dom.CORPORATE, "corp_facility_month", month, "sector",
                    measure="ead_sar_mn", condition=lambda g: g["stage"] >= 2)


def corp_ecl_by_facility_type(month: str) -> dict[str, float]:
    return sum_by(dom.CORPORATE, "corp_facility_month", month,
                  "facility_type", "ecl_sar_mn")


def corp_ead_movement(latest: str, previous: str) -> float:
    return (total(dom.CORPORATE, "corp_facility_month", latest, "ead_sar_mn")
            - total(dom.CORPORATE, "corp_facility_month", previous,
                    "ead_sar_mn"))


def corp_ead_by_borrower(month: str) -> dict[str, float]:
    """Facility EAD summed to the borrower, then named.

    The borrower relation is joined for its NAME only. Its own money columns
    are never summed across this join: one borrower holds several facilities,
    so revenue would be counted once per facility.
    """
    facilities = _month(dom.CORPORATE, "corp_facility_month", month)
    borrowers = _month(dom.CORPORATE, "corp_borrower_month", month)
    names = dict(zip(borrowers["borrower_id"], borrowers["borrower_name"]))
    summed = facilities.groupby("borrower_id", observed=True)[
        "ead_sar_mn"].sum()
    return {str(names.get(k, k)): float(v) for k, v in summed.items()}


# ---- retail ------------------------------------------------------------

def retail_ead_by_product(month: str) -> dict[str, float]:
    return sum_by(dom.RETAIL, "retail_account_month", month, "product",
                  "ead_sar_mn")


def retail_stage2_share_by_product(month: str) -> dict[str, float]:
    return share_by(dom.RETAIL, "retail_account_month", month, "product",
                    measure="ead_sar_mn", condition=lambda g: g["stage"] >= 2)


def retail_ecl_by_score_band(month: str) -> dict[str, float]:
    return sum_by(dom.RETAIL, "retail_account_month", month, "score_band",
                  "ecl_sar_mn")


def retail_delinquent_share_by_product(month: str) -> dict[str, float]:
    return share_by(dom.RETAIL, "retail_account_month", month, "product",
                    measure="ead_sar_mn",
                    condition=lambda g: g["dpd_days"] > 0)


def retail_write_off_by_product(month: str) -> dict[str, float]:
    return sum_by(dom.RETAIL, "retail_account_month", month, "product",
                  "write_off_sar_mn")


def retail_ead_by_vintage(month: str) -> dict[str, float]:
    rows = _month(dom.RETAIL, "retail_account_month", month)
    return {str(int(k)): float(v) for k, v in
            rows.groupby("vintage_year", observed=True)["ead_sar_mn"]
            .sum().items()}


def retail_ecl_coverage(month: str) -> float:
    rows = _month(dom.RETAIL, "retail_account_month", month)
    return float(rows["ecl_sar_mn"].sum()) / float(rows["ead_sar_mn"].sum())


__all__ = ["corp_ead_by_borrower", "corp_ead_by_sector",
           "corp_ead_movement", "corp_ecl_by_facility_type",
           "corp_stage2_share_by_sector", "frame", "latest_month", "months",
           "previous_month", "retail_delinquent_share_by_product",
           "retail_ead_by_product", "retail_ead_by_vintage",
           "retail_ecl_by_score_band", "retail_ecl_coverage",
           "retail_stage2_share_by_product", "retail_write_off_by_product",
           "share_by", "sum_by", "total"]
