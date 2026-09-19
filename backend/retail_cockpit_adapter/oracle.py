"""
Expected results, computed independently of the thing they are checking.

Why this exists rather than a fixture
-------------------------------------
An expected value copied from a previous answer proves that the answer has
not changed. It does not prove that it was ever right. So every figure here
is computed from the PUBLISHED RETAIL BOOK -- the Parquet the Cockpit Data
domain ships -- with pandas, by a different implementation from the one under
test: the engine reads the projection through DuckDB, this reads the source
through pandas, and the two meet only in the number.

That is also why the oracles read `retail_facility_month` and not the
projection. An oracle computed from the projection would check that the
engine reads the projection correctly and would be silent about the
projection itself, which is the half this integration actually adds.

Each result carries what it means
---------------------------------
A figure without its period, its grain, its unit and its denominator is not
checkable. `Expected` carries all four, plus the tolerance it is compared at,
so a mismatch reads as a disagreement about a stated quantity rather than as
two numbers that differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.retail_cockpit_adapter import semantic_map as sm
from backend.retail_cockpit_adapter.source import Snapshot

#: Money is compared in the projection's own scale, so the tolerance is in
#: SAR million. A tenth of a riyal.
MONEY_TOLERANCE = 1e-7

#: Counts are exact. A tolerance on a count would hide a row.
COUNT_TOLERANCE = 0


@dataclass(frozen=True)
class Expected:
    """One expected result, and everything needed to check it."""

    question: str
    period: str
    grain: str
    unit: str
    denominator: str
    rows: list[dict[str, Any]]
    tolerance: float = MONEY_TOLERANCE
    note: str = ""
    source: dict[str, str] = field(default_factory=dict)

    def key(self, row: dict[str, Any], keys: tuple[str, ...]) -> tuple:
        return tuple(row[k] for k in keys)


def _stamp(snapshot: Snapshot) -> dict[str, str]:
    return {"dataset": "retail_facility_month",
            "dataset_version": snapshot.dataset_version,
            "manifest_hash": snapshot.manifest_hash}


def _million(value: float) -> float:
    return float(value) / sm.SAR_PER_MILLION


def q01_ead_by_product(snapshot: Snapshot, period: str = "") -> Expected:
    """Latest-month exposure at default by product."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=["product_label", "ead_base_sar",
                                                "facility_id"])
    grouped = book.groupby("product_label")
    rows = [{"product": product,
             "ead_sar_mn": _million(grouped["ead_base_sar"].sum()[product]),
             "facilities": int(grouped.size()[product])}
            for product in sorted(grouped.groups)]
    total = _million(book["ead_base_sar"].sum())
    return Expected(
        question="Latest-month EAD by product",
        period=period, grain="one row per facility per month",
        unit="SAR million",
        denominator=f"all {len(book):,} facilities published in {period}",
        rows=rows + [{"product": "TOTAL", "ead_sar_mn": total,
                      "facilities": int(len(book))}],
        note="Base-scenario EAD. The product totals reconcile to the whole "
             "book because every facility carries exactly one product and "
             "exactly one row in the month.",
        source=_stamp(snapshot))


def q02_entities_by_product(snapshot: Snapshot, period: str = "") -> Expected:
    """Distinct customers and facilities by product, and the overlap."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=["product_label", "customer_id",
                                                "facility_id"])
    rows = []
    for product in sorted(book["product_label"].unique()):
        part = book[book["product_label"] == product]
        rows.append({"product": product,
                     "customers": int(part["customer_id"].nunique()),
                     "facilities": int(part["facility_id"].nunique())})
    total_customers = int(book["customer_id"].nunique())
    holdings = book.groupby("customer_id")["product_label"].nunique()
    return Expected(
        question="Customer count and facility count by product",
        period=period, grain="distinct entities within the month",
        unit="count",
        denominator=f"{total_customers:,} distinct customers, "
                    f"{int(book['facility_id'].nunique()):,} facilities",
        rows=rows + [{"product": "TOTAL DISTINCT",
                      "customers": total_customers,
                      "facilities": int(book["facility_id"].nunique())}],
        tolerance=COUNT_TOLERANCE,
        note=(f"The product customer counts sum to more than the distinct "
              f"total because {int((holdings > 1).sum()):,} customers hold "
              f"facilities in more than one product. Summing the product "
              f"column counts those customers once per product."),
        source=_stamp(snapshot))


def q03_ecl_coverage(snapshot: Snapshot, period: str = "") -> Expected:
    """Booked ECL and coverage by product and IFRS 9 stage."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "product_label", "ifrs9_stage", "ecl_final_sar",
        "gross_carrying_amount_sar", "facility_id"])
    rows = []
    for (product, stage), part in book.groupby(["product_label",
                                                "ifrs9_stage"]):
        ecl = float(part["ecl_final_sar"].sum())
        gca = float(part["gross_carrying_amount_sar"].sum())
        rows.append({"product": product, "stage": int(stage),
                     "ecl_sar_mn": _million(ecl),
                     "gca_sar_mn": _million(gca),
                     "coverage": (ecl / gca) if gca else 0.0,
                     "facilities": int(len(part))})
    rows.sort(key=lambda r: (r["product"], r["stage"]))
    return Expected(
        question="ECL and coverage by product and IFRS 9 stage",
        period=period, grain="one row per facility per month",
        unit="SAR million; coverage is a fraction",
        denominator="gross carrying amount of the same population",
        rows=rows,
        note="Coverage is the summed ECL over the summed gross carrying "
             "amount, never the average of the per-facility ratio.",
        source=_stamp(snapshot))


def q05_early_arrears_movement(snapshot: Snapshot, period: str = "",
                               comparison: str = "") -> Expected:
    """Where the 1-29 days past due population moved, month on month."""
    periods = snapshot.periods
    period = period or snapshot.latest_period
    comparison = comparison or periods[periods.index(period) - 1]
    rows = []
    populations = {}
    for label, month in (("current", period), ("prior", comparison)):
        book = snapshot.read_month(month, columns=["product_label", "dpd",
                                                   "facility_id"])
        early = book[(book["dpd"] >= 1) & (book["dpd"] <= 29)]
        populations[label] = {
            "month": month,
            "book": int(len(book)),
            "early": int(len(early)),
            "by_product": early.groupby("product_label").size().to_dict(),
            "book_by_product": book.groupby("product_label").size().to_dict()}
    for product in sorted(set(populations["current"]["book_by_product"])
                          | set(populations["prior"]["book_by_product"])):
        now = int(populations["current"]["by_product"].get(product, 0))
        before = int(populations["prior"]["by_product"].get(product, 0))
        now_book = int(populations["current"]["book_by_product"].get(
            product, 0))
        before_book = int(populations["prior"]["book_by_product"].get(
            product, 0))
        rows.append({
            "product": product, "current": now, "prior": before,
            "movement": now - before,
            "current_share": (now / now_book) if now_book else 0.0,
            "prior_share": (before / before_book) if before_book else 0.0,
            "current_population": now_book, "prior_population": before_book})
    return Expected(
        question="Where the 1-29 DPD population increased since last month",
        period=f"{period} against {comparison}",
        grain="one row per facility per month",
        unit="count; share is a fraction",
        denominator="the live facility population of the same product and "
                    "month",
        rows=rows, tolerance=COUNT_TOLERANCE,
        note="1-29 is taken from the exact day count, not the bucket label. "
             "The book population of each month is carried so a movement in "
             "the count can be told apart from a movement in the share.",
        source=_stamp(snapshot))


def q06_fine_arrears(snapshot: Snapshot, period: str = "",
                     comparison: str = "") -> Expected:
    """The 1-29 movement split into 1-9, 10-19 and 20-29."""
    periods = snapshot.periods
    period = period or snapshot.latest_period
    comparison = comparison or periods[periods.index(period) - 1]
    bins = (("1-9", 1, 9), ("10-19", 10, 19), ("20-29", 20, 29))
    counts: dict[str, dict[str, int]] = {}
    for label, month in (("current", period), ("prior", comparison)):
        book = snapshot.read_month(month, columns=["dpd"])
        counts[label] = {name: int(((book["dpd"] >= low)
                                    & (book["dpd"] <= high)).sum())
                         for name, low, high in bins}
        counts[label]["1-29"] = int(((book["dpd"] >= 1)
                                     & (book["dpd"] <= 29)).sum())
    rows = [{"bucket": name,
             "current": counts["current"][name],
             "prior": counts["prior"][name],
             "movement": counts["current"][name] - counts["prior"][name]}
            for name, _, _ in bins]
    rows.append({"bucket": "1-29 (sum of the three)",
                 "current": sum(r["current"] for r in rows),
                 "prior": sum(r["prior"] for r in rows),
                 "movement": sum(r["movement"] for r in rows)})
    rows.append({"bucket": "1-29 (counted directly)",
                 "current": counts["current"]["1-29"],
                 "prior": counts["prior"]["1-29"],
                 "movement": counts["current"]["1-29"]
                 - counts["prior"]["1-29"]})
    return Expected(
        question="The 1-29 movement split into 1-9, 10-19 and 20-29",
        period=f"{period} against {comparison}",
        grain="one row per facility per month", unit="count",
        denominator="the whole live book of the month",
        rows=rows, tolerance=COUNT_TOLERANCE,
        note="The three sub-buckets are non-overlapping and must reconcile "
             "to the 1-29 population counted directly. Both are computed "
             "here so the check is a reconciliation rather than an "
             "assertion.",
        source=_stamp(snapshot))


def q16_stage_migration(snapshot: Snapshot, period: str = "",
                        comparison: str = "") -> Expected:
    """Stage 1/2/3 migration as a count matrix, with entrants and exits."""

    periods = snapshot.periods
    period = period or snapshot.latest_period
    comparison = comparison or periods[periods.index(period) - 1]
    now = snapshot.read_month(period, columns=["facility_id", "ifrs9_stage"])
    before = snapshot.read_month(comparison,
                                 columns=["facility_id", "ifrs9_stage"])
    merged = before.merge(now, on="facility_id", how="outer",
                          suffixes=("_before", "_now"), indicator=True)
    both = merged[merged["_merge"] == "both"]
    rows = []
    for (prior_stage, current_stage), part in both.groupby(
            ["ifrs9_stage_before", "ifrs9_stage_now"]):
        rows.append({"from_stage": int(prior_stage),
                     "to_stage": int(current_stage),
                     "facilities": int(len(part))})
    rows.sort(key=lambda r: (r["from_stage"], r["to_stage"]))
    entrants = int((merged["_merge"] == "right_only").sum())
    exits = int((merged["_merge"] == "left_only").sum())
    return Expected(
        question="Stage 1/2/3 migration as a count matrix",
        period=f"{comparison} to {period}",
        grain="facilities present in BOTH months", unit="count",
        denominator=f"{len(both):,} facilities present in both months; "
                    f"{entrants:,} entered and {exits:,} left",
        rows=rows + [{"from_stage": "ENTERED", "to_stage": "-",
                      "facilities": entrants},
                     {"from_stage": "-", "to_stage": "LEFT",
                      "facilities": exits}],
        tolerance=COUNT_TOLERANCE,
        note="A migration is the same facility in two months. Facilities "
             "that entered or left the book are counted separately and are "
             "not a migration in either direction.",
        source=_stamp(snapshot))


def q21_ecl_movement(snapshot: Snapshot, period: str = "",
                     comparison: str = "") -> Expected:
    """The recorded ECL movement, decomposed the way the engine decomposes it.

    New, closed and retained partition the book exactly; the retained part
    splits into the stage-migration effect, the exposure effect priced at
    last month's coverage, and the remainder. The components sum to the
    movement with no residual, and the residual is published so a reader can
    see that they do.
    """
    periods = snapshot.periods
    period = period or snapshot.latest_period
    comparison = comparison or periods[periods.index(period) - 1]
    columns = ["facility_id", "ifrs9_stage", "ead_base_sar", "ecl_final_sar"]
    now = snapshot.read_month(period, columns=columns).set_index("facility_id")
    before = snapshot.read_month(comparison,
                                 columns=columns).set_index("facility_id")
    joined = now.join(before, how="outer", lsuffix="_now", rsuffix="_before")
    is_new = joined["ecl_final_sar_before"].isna()
    is_closed = joined["ecl_final_sar_now"].isna()
    retained = ~(is_new | is_closed)
    moved = retained & (joined["ifrs9_stage_now"]
                        != joined["ifrs9_stage_before"])
    same = retained & ~moved

    ecl_now = joined["ecl_final_sar_now"].fillna(0.0)
    ecl_before = joined["ecl_final_sar_before"].fillna(0.0)
    coverage_before = (joined["ecl_final_sar_before"]
                       / joined["ead_base_sar_before"].replace(0.0, float("nan"))
                       ).fillna(0.0)
    exposure_effect = ((joined["ead_base_sar_now"]
                        - joined["ead_base_sar_before"])
                       * coverage_before)

    new = float(ecl_now[is_new].sum())
    closed = float(-ecl_before[is_closed].sum())
    migration = float((ecl_now[moved] - ecl_before[moved]).sum())
    exposure = float(exposure_effect[same].fillna(0.0).sum())
    retained_total = float((ecl_now[same] - ecl_before[same]).sum())
    risk = retained_total - exposure

    opening = float(before["ecl_final_sar"].sum())
    closing = float(now["ecl_final_sar"].sum())
    components = [("New facilities", new, int(is_new.sum())),
                  ("Closed facilities", closed, int(is_closed.sum())),
                  ("Stage migration", migration, int(moved.sum())),
                  ("Exposure change", exposure, int(same.sum())),
                  ("Risk and overlay change", risk, int(same.sum()))]
    rows = [{"component": name, "amount_sar_mn": _million(amount),
             "facilities": n} for name, amount, n in components]
    movement = closing - opening
    rows += [{"component": "OPENING", "amount_sar_mn": _million(opening),
              "facilities": int(len(before))},
             {"component": "CLOSING", "amount_sar_mn": _million(closing),
              "facilities": int(len(now))},
             {"component": "MOVEMENT", "amount_sar_mn": _million(movement),
              "facilities": 0},
             {"component": "RESIDUAL",
              "amount_sar_mn": _million(
                  movement - sum(a for _, a, _ in components)),
              "facilities": 0}]
    return Expected(
        question="Decompose the ECL movement",
        period=f"{comparison} to {period}",
        grain="one row per facility per month", unit="SAR million",
        denominator="the recorded allowance of both months",
        rows=rows,
        note="Recorded movement, not a modelled attribution. Risk and "
             "overlay change is a remainder by construction and is reported "
             "as one.",
        source=_stamp(snapshot))


ORACLES = {
    "Q01": q01_ead_by_product,
    "Q02": q02_entities_by_product,
    "Q03": q03_ecl_coverage,
    "Q05": q05_early_arrears_movement,
    "Q06": q06_fine_arrears,
    "Q16": q16_stage_migration,
    "Q21": q21_ecl_movement,
}

__all__ = ["COUNT_TOLERANCE", "Expected", "MONEY_TOLERANCE", "ORACLES",
           "q01_ead_by_product", "q02_entities_by_product", "q03_ecl_coverage",
           "q05_early_arrears_movement", "q06_fine_arrears",
           "q16_stage_migration", "q21_ecl_movement"]
