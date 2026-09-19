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

import pandas as pd

from backend.retail import scorecards as _sc
from backend.retail_cockpit_adapter import semantic_map as sm
from backend.retail_cockpit_adapter.source import Snapshot

#: Money is compared in the projection's own scale, so the tolerance is in
#: SAR million. A tenth of a riyal.
MONEY_TOLERANCE = 1e-7

#: The same tolerance, expressed in riyals, for the riyal columns the release
#: publishes beside the millions ones. A tenth of a riyal either way,
#: whichever denomination the column is written in.
RIYAL_TOLERANCE = MONEY_TOLERANCE * sm.SAR_PER_MILLION

#: Counts are exact. A tolerance on a count would hide a row.
COUNT_TOLERANCE = 0

#: The governed behavioural band scale, worst to best. Read from the
#: target's own scorecards rather than restated, because a band order
#: written twice is a band order that will disagree with itself, and
#: sorting these alphabetically puts A+ before A.
BAND_ORDER = tuple(_sc.SCORE_BAND_LABELS)


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
    """Latest-month exposure at default by product, in BOTH denominations."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=["product_label", "ead_base_sar",
                                                "facility_id"])
    grouped = book.groupby("product_label")
    rows = [{"product": product,
             "ead_sar": float(grouped["ead_base_sar"].sum()[product]),
             "ead_sar_mn": _million(grouped["ead_base_sar"].sum()[product]),
             "facilities": int(grouped.size()[product])}
            for product in sorted(grouped.groups)]
    total = float(book["ead_base_sar"].sum())
    return Expected(
        question="Latest-month EAD by product",
        period=period, grain="one row per facility per month",
        unit="SAR million and SAR",
        denominator=f"all {len(book):,} facilities published in {period}",
        rows=rows + [{"product": "TOTAL", "ead_sar": total,
                      "ead_sar_mn": _million(total),
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
                     "ecl_sar": ecl, "balance_sar": gca,
                     "ecl_sar_mn": _million(ecl),
                     "gca_sar_mn": _million(gca),
                     "coverage": (ecl / gca) if gca else 0.0,
                     "facilities": int(len(part))})
    rows.sort(key=lambda r: (r["product"], r["stage"]))
    return Expected(
        question="ECL and coverage by product and IFRS 9 stage",
        period=period, grain="one row per facility per month",
        unit="SAR million and SAR; coverage is a fraction",
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
    # Named as the ECL PANEL names them. The engine's retail grain noun is
    # "account"; this book's entity is a facility, which is exactly why the
    # projection renames it -- but this case checks the panel, and an oracle
    # that checked the panel under different words would fail on vocabulary
    # while agreeing on every number.
    components = [("New accounts", new, int(is_new.sum())),
                  ("Closed accounts", closed, int(is_closed.sum())),
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




# ---- the expansion: seventeen more, one per analytical concept ----------
#
# Every one reads the SOURCE book with pandas and nothing else. None of them
# imports the catalogue, opens a DuckDB session, or calls a helper the
# product uses to build SQL -- an oracle that calls the code under test
# proves the code is self-consistent, which is exactly what a wrong answer
# also is.


def _both(book: Any, column: str) -> dict[str, float]:
    """One money total, in both denominations. Stated, never inferred."""
    total = float(pd.to_numeric(book[column], errors="coerce").sum())
    return {f"{column}__sar": total, f"{column}__sar_mn": _million(total)}


def q04_balance_by_product(snapshot: Snapshot, period: str = "") -> Expected:
    """Gross carrying amount by product, in both denominations."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=["product_label",
                                                "gross_carrying_amount_sar"])
    grouped = book.groupby("product_label")["gross_carrying_amount_sar"]
    rows = [{"product": p, "balance_sar": float(grouped.sum()[p]),
             "balance_sar_mn": _million(float(grouped.sum()[p]))}
            for p in sorted(grouped.groups)]
    return Expected(
        question="Gross carrying amount by product",
        period=period, grain="one row per facility per month",
        unit="SAR and SAR million",
        denominator=f"all {len(book):,} facilities published in {period}",
        rows=rows,
        note="A month-end level, not a flow.", source=_stamp(snapshot))


def q07_stage_distribution(snapshot: Snapshot, period: str = "") -> Expected:
    """How the book is split across IFRS 9 stages, by count and exposure."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=["ifrs9_stage", "ead_base_sar",
                                                "facility_id"])
    total_ead = float(book["ead_base_sar"].sum())
    rows = []
    for stage, part in book.groupby("ifrs9_stage"):
        ead = float(part["ead_base_sar"].sum())
        rows.append({"stage": int(stage), "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ead_share": ead / total_ead if total_ead else 0.0})
    rows.sort(key=lambda r: r["stage"])
    return Expected(
        question="Stage distribution by count and exposure",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; share is a fraction",
        denominator=f"total EAD of {total_ead:,.2f} SAR in {period}",
        rows=rows,
        note="The share is exposure over exposure, not facilities over "
             "facilities: the two answer different questions and only one "
             "of them is about risk.",
        source=_stamp(snapshot))


def q08_sicr(snapshot: Snapshot, period: str = "") -> Expected:
    """What drove SICR, by trigger, without double counting a facility."""
    period = period or snapshot.latest_period
    columns = ["sicr_flag", "sicr_quantitative_flag", "sicr_qualitative_flag",
               "sicr_dpd_backstop_flag", "ead_base_sar", "facility_id"]
    book = snapshot.read_month(period, columns=columns)
    flagged = book[book["sicr_flag"].astype("boolean").fillna(False)]
    rows = []
    for trigger in ("sicr_quantitative_flag", "sicr_qualitative_flag",
                    "sicr_dpd_backstop_flag"):
        hit = flagged[flagged[trigger].astype("boolean").fillna(False)]
        ead = float(hit["ead_base_sar"].sum())
        rows.append({"trigger": trigger, "facilities": int(len(hit)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead)})
    ead_all = float(flagged["ead_base_sar"].sum())
    rows.append({"trigger": "ANY", "facilities": int(len(flagged)),
                 "ead_sar": ead_all, "ead_sar_mn": _million(ead_all)})
    return Expected(
        question="SICR by trigger",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million",
        denominator=f"the {len(flagged):,} facilities flagged in {period}",
        rows=rows, tolerance=MONEY_TOLERANCE,
        note="The triggers OVERLAP: a facility may fire more than one, so "
             "the trigger rows sum to more than ANY. ANY is the "
             "de-duplicated population and is the only one that may be "
             "compared with the book.",
        source=_stamp(snapshot))


def q09_default(snapshot: Snapshot, period: str = "") -> Expected:
    """The defaulted population, and what it is worth."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "current_default_flag", "product_label", "ead_base_sar",
        "ecl_final_sar", "facility_id"])
    hit = book[book["current_default_flag"].astype("boolean").fillna(False)]
    rows = []
    for product, part in hit.groupby("product_label"):
        ead = float(part["ead_base_sar"].sum())
        ecl = float(part["ecl_final_sar"].sum())
        rows.append({"product": product, "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ecl_sar": ecl, "ecl_sar_mn": _million(ecl),
                     "coverage": (ecl / ead) if ead else 0.0})
    rows.sort(key=lambda r: r["product"])
    return Expected(
        question="Defaulted facilities by product",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; coverage is a fraction",
        denominator="the defaulted population of the same product",
        rows=rows,
        note="Coverage is summed ECL over summed EAD. The average of the "
             "per-facility ratio is a different number and answers nothing.",
        source=_stamp(snapshot))


def q10_dpd_buckets(snapshot: Snapshot, period: str = "") -> Expected:
    """The delinquency profile on the book's own published buckets."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=["dpd_bucket", "ead_base_sar",
                                                "facility_id"])
    total = float(book["ead_base_sar"].sum())
    rows = []
    for bucket, part in book.groupby("dpd_bucket"):
        ead = float(part["ead_base_sar"].sum())
        rows.append({"bucket": str(bucket), "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ead_share": ead / total if total else 0.0})
    rows.sort(key=lambda r: r["bucket"])
    return Expected(
        question="Delinquency profile by published DPD bucket",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; share is a fraction",
        denominator=f"total EAD of {total:,.2f} SAR in {period}",
        rows=rows,
        note="The book's own six labels, not an invented 90+ bucket.",
        source=_stamp(snapshot))


def q11_arrears_movement_90(snapshot: Snapshot, period: str = "",
                            comparison: str = "") -> Expected:
    """Movement in each of 30-59, 60-89 and 90+, month on month."""
    periods = snapshot.periods
    period = period or snapshot.latest_period
    comparison = comparison or periods[periods.index(period) - 1]
    bands = (("30-59", 30, 59), ("60-89", 60, 89), ("90+", 90, 10_000))
    counts: dict[str, dict[str, Any]] = {}
    for label, month in (("current", period), ("prior", comparison)):
        book = snapshot.read_month(month, columns=["dpd", "ead_base_sar"])
        days = pd.to_numeric(book["dpd"], errors="coerce")
        counts[label] = {}
        for name, low, high in bands:
            part = book[days.between(low, high)]
            counts[label][name] = {
                "facilities": int(len(part)),
                "ead_sar": float(part["ead_base_sar"].sum())}
    rows = []
    for name, _low, _high in bands:
        now = counts["current"][name]
        before = counts["prior"][name]
        rows.append({
            "band": name,
            "current": now["facilities"], "prior": before["facilities"],
            "movement": now["facilities"] - before["facilities"],
            "current_ead_sar": now["ead_sar"],
            "prior_ead_sar": before["ead_sar"],
            "current_ead_sar_mn": _million(now["ead_sar"]),
            "prior_ead_sar_mn": _million(before["ead_sar"])})
    return Expected(
        question="Movement in 30-59, 60-89 and 90+ arrears",
        period=f"{period} against {comparison}",
        grain="one row per facility per month",
        unit="count, SAR and SAR million",
        denominator="the live facility population of each month",
        rows=rows, tolerance=MONEY_TOLERANCE,
        note="Taken from the exact day count. 90+ is derived here because "
             "the book publishes 90-179 and 180+ separately; the two are "
             "added rather than a new bucket being invented.",
        source=_stamp(snapshot))


def q12_sub_product(snapshot: Snapshot, period: str = "") -> Expected:
    """Exposure and ECL by product sub-segment."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "product_label", "product_subsegment", "ead_base_sar",
        "ecl_final_sar", "facility_id"])
    rows = []
    for (product, sub), part in book.groupby(["product_label",
                                              "product_subsegment"]):
        ead = float(part["ead_base_sar"].sum())
        ecl = float(part["ecl_final_sar"].sum())
        rows.append({"product": product, "sub_product": str(sub),
                     "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ecl_sar": ecl, "ecl_sar_mn": _million(ecl)})
    rows.sort(key=lambda r: (r["product"], r["sub_product"]))
    return Expected(
        question="Exposure and ECL by product sub-segment",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million",
        denominator=f"all {len(book):,} facilities published in {period}",
        rows=rows, source=_stamp(snapshot))


def q13_region(snapshot: Snapshot, period: str = "") -> Expected:
    """Exposure, ECL and coverage by region."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "region_label", "ead_base_sar", "ecl_final_sar",
        "gross_carrying_amount_sar", "facility_id"])
    rows = []
    for region, part in book.groupby("region_label"):
        ead = float(part["ead_base_sar"].sum())
        ecl = float(part["ecl_final_sar"].sum())
        gca = float(part["gross_carrying_amount_sar"].sum())
        rows.append({"region": str(region), "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ecl_sar": ecl, "ecl_sar_mn": _million(ecl),
                     "coverage": (ecl / gca) if gca else 0.0})
    rows.sort(key=lambda r: r["region"])
    return Expected(
        question="Exposure, ECL and coverage by region",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; coverage is a fraction",
        denominator="gross carrying amount of the same region",
        rows=rows, source=_stamp(snapshot))


def q14_employment(snapshot: Snapshot, period: str = "") -> Expected:
    """Exposure and delinquency by employment status."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "employment_status", "ead_base_sar", "dpd", "facility_id"])
    days = pd.to_numeric(book["dpd"], errors="coerce")
    rows = []
    for status, part in book.assign(_d=days).groupby("employment_status"):
        ead = float(part["ead_base_sar"].sum())
        overdue = part[part["_d"] > 0]
        rows.append({"employment": str(status), "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "past_due_facilities": int(len(overdue)),
                     "past_due_share": (len(overdue) / len(part))
                     if len(part) else 0.0})
    rows.sort(key=lambda r: r["employment"])
    return Expected(
        question="Exposure and delinquency by employment status",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; share is a fraction",
        denominator="the facilities of the same employment status",
        rows=rows,
        note="The book's five governed statuses. Salaried versus "
             "non-salaried is a different cut and is asked separately, "
             "because salary_transfer_flag is not employment.",
        source=_stamp(snapshot))


def q15_salary_transfer(snapshot: Snapshot, period: str = "") -> Expected:
    """Whether salary transfer separates the book, by arrears and ECL."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "salary_transfer_flag", "ead_base_sar", "ecl_final_sar", "dpd",
        "facility_id"])
    flag = book["salary_transfer_flag"].astype("boolean").fillna(False)
    days = pd.to_numeric(book["dpd"], errors="coerce")
    rows = []
    for label, part in (("SALARY_TRANSFERRED", book[flag]),
                        ("NOT_TRANSFERRED", book[~flag])):
        ead = float(part["ead_base_sar"].sum())
        ecl = float(part["ecl_final_sar"].sum())
        overdue = int((days.loc[part.index] > 0).sum())
        rows.append({"population": label, "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ecl_sar": ecl, "ecl_sar_mn": _million(ecl),
                     "coverage": (ecl / ead) if ead else 0.0,
                     "past_due_share": (overdue / len(part))
                     if len(part) else 0.0})
    return Expected(
        question="Salary transfer against arrears and ECL",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; shares are fractions",
        denominator="the facilities in the same population",
        rows=rows, source=_stamp(snapshot))


def q17_score_band(snapshot: Snapshot, period: str = "") -> Expected:
    """Exposure and coverage by behavioural score band, in band order."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "behavioural_score_band", "ead_base_sar", "ecl_final_sar",
        "facility_id"])
    order = {label: i for i, label in enumerate(BAND_ORDER)}
    rows = []
    for band, part in book.groupby("behavioural_score_band"):
        ead = float(part["ead_base_sar"].sum())
        ecl = float(part["ecl_final_sar"].sum())
        rows.append({"score_band": str(band), "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ecl_sar": ecl, "ecl_sar_mn": _million(ecl),
                     "coverage": (ecl / ead) if ead else 0.0})
    rows.sort(key=lambda r: order.get(r["score_band"], 99))
    return Expected(
        question="Exposure and coverage by behavioural score band",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; coverage is a fraction",
        denominator="the facilities in the same band",
        rows=rows,
        note="Ordered by the governed band scale E to A+, never "
             "alphabetically: A+ sorts before A as text and after it as a "
             "grade.",
        source=_stamp(snapshot))


def q18_score_movement(snapshot: Snapshot, period: str = "") -> Expected:
    """How behavioural scores moved, on the book's own prior-month column."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "behavioural_score", "behavioural_score_previous_month",
        "ead_base_sar", "facility_id"])
    now = pd.to_numeric(book["behavioural_score"], errors="coerce")
    before = pd.to_numeric(book["behavioural_score_previous_month"],
                           errors="coerce")
    change = now - before
    scored = change.notna()
    rows = [
        {"movement": "DETERIORATED",
         "facilities": int((change < -2).sum()),
         "ead_sar": float(book.loc[change < -2, "ead_base_sar"].sum())},
        {"movement": "STABLE",
         "facilities": int((scored & change.between(-2, 2)).sum()),
         "ead_sar": float(
             book.loc[scored & change.between(-2, 2), "ead_base_sar"].sum())},
        {"movement": "IMPROVED",
         "facilities": int((change > 2).sum()),
         "ead_sar": float(book.loc[change > 2, "ead_base_sar"].sum())},
        {"movement": "NOT_SCORED",
         "facilities": int((~scored).sum()),
         "ead_sar": float(book.loc[~scored, "ead_base_sar"].sum())},
    ]
    for row in rows:
        row["ead_sar_mn"] = _million(row["ead_sar"])
    return Expected(
        question="Behavioural score movement at facility grain",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million",
        denominator=f"all {len(book):,} facilities published in {period}",
        rows=rows, tolerance=MONEY_TOLERANCE,
        note="A dead band of two score points either way, on the book's own "
             "prior-month column. NOT_SCORED is carried as its own row: a "
             "facility the book has not scored has not been stable.",
        source=_stamp(snapshot))


def q19_customer_vs_facility(snapshot: Snapshot, period: str = "") -> Expected:
    """The de-duplication test: customer-grain values must not be multiplied."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "customer_id", "facility_id", "verified_total_monthly_income_sar",
        "ead_base_sar"])
    naive = float(book["verified_total_monthly_income_sar"].sum())
    once = float(book.groupby("customer_id")
                 ["verified_total_monthly_income_sar"].first().sum())
    return Expected(
        question="Customer income summed once per customer, not per facility",
        period=period, grain="one row per customer per month",
        unit="SAR and SAR million",
        denominator=f"{book['customer_id'].nunique():,} distinct customers "
                    f"holding {len(book):,} facilities",
        rows=[{"basis": "PER_CUSTOMER", "income_sar": once,
               "income_sar_mn": _million(once),
               "customers": int(book["customer_id"].nunique())},
              {"basis": "PER_FACILITY_ROW", "income_sar": naive,
               "income_sar_mn": _million(naive),
               "customers": int(len(book))}],
        note="PER_FACILITY_ROW is the DEFECT, carried deliberately so the "
             "gap is visible. A customer holding three facilities has their "
             "income counted three times in it. Only PER_CUSTOMER is an "
             "answer.",
        source=_stamp(snapshot))


def q20_vintage(snapshot: Snapshot, period: str = "") -> Expected:
    """Exposure and coverage by origination vintage year."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "origination_vintage", "ead_base_sar", "ecl_final_sar",
        "facility_id"])
    year = book["origination_vintage"].astype("string").str.slice(0, 4)
    rows = []
    for vintage, part in book.assign(_y=year).groupby("_y"):
        ead = float(part["ead_base_sar"].sum())
        ecl = float(part["ecl_final_sar"].sum())
        rows.append({"vintage_year": str(vintage),
                     "facilities": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ecl_sar": ecl, "ecl_sar_mn": _million(ecl),
                     "coverage": (ecl / ead) if ead else 0.0})
    rows.sort(key=lambda r: r["vintage_year"])
    return Expected(
        question="Exposure and coverage by origination vintage",
        period=period, grain="one row per facility per month",
        unit="count, SAR and SAR million; coverage is a fraction",
        denominator="the facilities written in the same year",
        rows=rows, source=_stamp(snapshot))


def q22_affordability(snapshot: Snapshot, period: str = "") -> Expected:
    """Debt burden, at CUSTOMER grain, banded."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "customer_id", "debt_burden_ratio", "disposable_income_sar",
        "ead_base_sar"])
    per_customer = book.groupby("customer_id").agg(
        dbr=("debt_burden_ratio", "first"),
        disposable=("disposable_income_sar", "first"),
        ead=("ead_base_sar", "sum"))
    dbr = pd.to_numeric(per_customer["dbr"], errors="coerce")
    bands = (("<=0.35", -1e9, 0.35), ("0.35-0.50", 0.35, 0.50),
             ("0.50-0.65", 0.50, 0.65), (">0.65", 0.65, 1e9))
    rows = []
    for name, low, high in bands:
        part = per_customer[(dbr > low) & (dbr <= high)]
        ead = float(part["ead"].sum())
        rows.append({"band": name, "customers": int(len(part)),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "negative_disposable": int(
                         (part["disposable"] < 0).sum())})
    return Expected(
        question="Debt burden ratio bands at customer grain",
        period=period, grain="one row per customer per month",
        unit="count, SAR and SAR million",
        denominator=f"{len(per_customer):,} distinct customers in {period}",
        rows=rows, tolerance=MONEY_TOLERANCE,
        note="De-duplicated on customer_id FIRST. The ratio repeats on every "
             "facility row, so banding the facility rows would weight a "
             "customer by how many facilities they hold.",
        source=_stamp(snapshot))


def q23_collateral(snapshot: Snapshot, period: str = "") -> Expected:
    """Secured lending: collateral value and LTV, secured population only."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "product_code", "product_label", "collateral_value_current_sar",
        "ltv_current_ratio", "ead_base_sar", "facility_id"])
    secured = book[book["product_code"].isin(("AUTO_LOAN", "HOME_LOAN"))]
    held = secured[secured["collateral_value_current_sar"].notna()]
    rows = []
    for product, part in held.groupby("product_label"):
        value = float(part["collateral_value_current_sar"].sum())
        ead = float(part["ead_base_sar"].sum())
        rows.append({"product": product, "facilities": int(len(part)),
                     "collateral_value_sar": value,
                     "collateral_value_sar_mn": _million(value),
                     "ead_sar": ead, "ead_sar_mn": _million(ead),
                     "ltv_of_sums": (ead / value) if value else 0.0})
    rows.sort(key=lambda r: r["product"])
    return Expected(
        question="Collateral value and loan-to-value on secured lending",
        period=period, grain="one row per secured facility per month",
        unit="count, SAR and SAR million; LTV is a fraction",
        denominator=f"the {len(held):,} secured facilities carrying a "
                    f"valuation in {period}",
        rows=rows,
        note="Secured products only, and only where a valuation exists. An "
             "unsecured facility has no row here at all, so this population "
             "must never be compared with the whole book.",
        source=_stamp(snapshot))


def q24_write_offs_recoveries(snapshot: Snapshot, period: str = "") -> Expected:
    """Write-offs, recoveries and cures in the month. Flows, not levels."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "product_label", "writeoff_amount_month_sar",
        "recovery_amount_month_sar", "cure_flag", "facility_id"])
    cured = book["cure_flag"].astype("boolean").fillna(False)
    rows = []
    for product, part in book.assign(_c=cured).groupby("product_label"):
        wo = float(part["writeoff_amount_month_sar"].sum())
        rec = float(part["recovery_amount_month_sar"].sum())
        rows.append({"product": product,
                     "write_off_sar": wo, "write_off_sar_mn": _million(wo),
                     "recovery_sar": rec, "recovery_sar_mn": _million(rec),
                     "cures": int(part["_c"].sum())})
    rows.sort(key=lambda r: r["product"])
    return Expected(
        question="Write-offs, recoveries and cures in the month",
        period=period, grain="one row per facility per month",
        unit="SAR and SAR million; cures are a count",
        denominator=f"the month of {period} alone",
        rows=rows,
        note="FLOWS. These are what happened during the month and must "
             "never be added to a month-end level such as balance or EAD.",
        source=_stamp(snapshot))


def q25_scenarios(snapshot: Snapshot, period: str = "") -> Expected:
    """The three ECL scenarios and the weighted figure they produce."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "ecl_base_sar", "ecl_upturn_sar", "ecl_downturn_sar",
        "ecl_weighted_sar", "management_overlay_sar", "ecl_final_sar"])
    rows = []
    for column, label in (("ecl_base_sar", "BASE"),
                          ("ecl_upturn_sar", "UPTURN"),
                          ("ecl_downturn_sar", "DOWNTURN"),
                          ("ecl_weighted_sar", "WEIGHTED"),
                          ("management_overlay_sar", "OVERLAY"),
                          ("ecl_final_sar", "RECOGNISED")):
        total = float(pd.to_numeric(book[column], errors="coerce").sum())
        rows.append({"scenario": label, "ecl_sar": total,
                     "ecl_sar_mn": _million(total)})
    return Expected(
        question="ECL by scenario, and the recognised figure",
        period=period, grain="one row per facility per month",
        unit="SAR and SAR million",
        denominator=f"all facilities published in {period}",
        rows=rows,
        note="RECOGNISED is WEIGHTED plus OVERLAY and is the booked figure. "
             "The three scenarios are columns of this book, not rows: none "
             "of them multiplies the grain.",
        source=_stamp(snapshot))


def q26_ecl_trend(snapshot: Snapshot, period: str = "") -> Expected:
    """Recognised ECL and coverage over the last twelve months."""
    periods = snapshot.periods
    end = periods.index(period or snapshot.latest_period)
    window = periods[max(0, end - 11):end + 1]
    rows = []
    for month in window:
        book = snapshot.read_month(month, columns=[
            "ecl_final_sar", "gross_carrying_amount_sar", "facility_id"])
        ecl = float(book["ecl_final_sar"].sum())
        gca = float(book["gross_carrying_amount_sar"].sum())
        rows.append({"reporting_month": month, "facilities": int(len(book)),
                     "ecl_sar": ecl, "ecl_sar_mn": _million(ecl),
                     "coverage": (ecl / gca) if gca else 0.0})
    return Expected(
        question="Recognised ECL and coverage over twelve months",
        period=f"{window[0]}..{window[-1]}",
        grain="one row per month",
        unit="SAR and SAR million; coverage is a fraction",
        denominator="gross carrying amount of the same month",
        rows=rows,
        note="Coverage is recomputed from the sums in each month. Averaging "
             "the published per-facility ratio, or averaging the monthly "
             "coverages, are both different numbers.",
        source=_stamp(snapshot))


def q27_concentration(snapshot: Snapshot, period: str = "") -> Expected:
    """How much of the book the largest customers carry."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=["customer_id",
                                                "ead_base_sar"])
    per_customer = book.groupby("customer_id")["ead_base_sar"].sum()
    total = float(per_customer.sum())
    ordered = per_customer.sort_values(ascending=False)
    rows = []
    for n in (10, 100, 1000):
        top = float(ordered.head(n).sum())
        rows.append({"top_n": n, "ead_sar": top,
                     "ead_sar_mn": _million(top),
                     "share": top / total if total else 0.0})
    return Expected(
        question="Exposure concentration in the largest customers",
        period=period, grain="one row per customer per month",
        unit="SAR and SAR million; share is a fraction",
        denominator=f"total customer EAD of {total:,.2f} SAR across "
                    f"{len(per_customer):,} customers",
        rows=rows, tolerance=MONEY_TOLERANCE,
        note="Ranked at CUSTOMER grain, after summing each customer's "
             "facilities. Ranking facility rows would answer a different "
             "question and would call one customer several borrowers.",
        source=_stamp(snapshot))


def q28_utilisation(snapshot: Snapshot, period: str = "") -> Expected:
    """Utilisation on revolving products, and where it is published at all."""
    period = period or snapshot.latest_period
    book = snapshot.read_month(period, columns=[
        "product_label", "utilisation_ratio", "current_credit_limit_sar",
        "gross_carrying_amount_sar", "facility_id"])
    rows = []
    for product, part in book.groupby("product_label"):
        published = part[part["utilisation_ratio"].notna()]
        limit = float(pd.to_numeric(published["current_credit_limit_sar"],
                                    errors="coerce").sum())
        balance = float(pd.to_numeric(published["gross_carrying_amount_sar"],
                                      errors="coerce").sum())
        rows.append({"product": product, "facilities": int(len(part)),
                     "with_utilisation": int(len(published)),
                     "limit_sar": limit, "balance_sar": balance,
                     # NULL, not zero. A product that publishes no
                     # utilisation has no utilisation, and zero would read
                     # as "fully undrawn" -- which is a number somebody
                     # might act on. The engine's own SQL says NULL here and
                     # it is right to.
                     "utilisation_of_sums": (balance / limit)
                     if limit else None})
    rows.sort(key=lambda r: r["product"])
    return Expected(
        question="Utilisation on the products that publish it",
        period=period, grain="one row per facility per month",
        unit="count and SAR; utilisation is a fraction",
        denominator="the facilities of the same product that publish a "
                    "utilisation",
        rows=rows,
        note="Null for non-revolving products, which is not zero. "
             "`with_utilisation` is carried so an average is never taken "
             "over facilities the book says nothing about.",
        source=_stamp(snapshot))


ORACLES = {
    "Q01": q01_ead_by_product,
    "Q02": q02_entities_by_product,
    "Q03": q03_ecl_coverage,
    "Q04": q04_balance_by_product,
    "Q05": q05_early_arrears_movement,
    "Q06": q06_fine_arrears,
    "Q07": q07_stage_distribution,
    "Q08": q08_sicr,
    "Q09": q09_default,
    "Q10": q10_dpd_buckets,
    "Q11": q11_arrears_movement_90,
    "Q12": q12_sub_product,
    "Q13": q13_region,
    "Q14": q14_employment,
    "Q15": q15_salary_transfer,
    "Q16": q16_stage_migration,
    "Q17": q17_score_band,
    "Q18": q18_score_movement,
    "Q19": q19_customer_vs_facility,
    "Q20": q20_vintage,
    "Q21": q21_ecl_movement,
    "Q22": q22_affordability,
    "Q23": q23_collateral,
    "Q24": q24_write_offs_recoveries,
    "Q25": q25_scenarios,
    "Q26": q26_ecl_trend,
    "Q27": q27_concentration,
    "Q28": q28_utilisation,
}
