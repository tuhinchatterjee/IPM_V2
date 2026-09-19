"""
The declared mapping: one canonical concept, one source column, one lineage.

Why the engine's own column names are kept
------------------------------------------
The engine is frozen. Three of its parts address this book's columns BY NAME:
`ecl.py` sums `ead_sar_mn` and `ecl_sar_mn` over `retail_account_month`;
`semantics.py` resolves "exposure at default", "ECL", "stage", "days past
due" and the rest to those same ids and carries them in the starting packet;
and `catalog.JOINS` states how the four relations join, keyed on their names.

So the projection speaks the engine's vocabulary. A concept the retail book
publishes under a different name is RENAMED here, once, with its origin
recorded; a concept it does not publish at all is a GAP and is absent from
the release, which is what makes the engine say "this book does not carry
that" instead of answering from a column of nulls.

Why every amount is published TWICE, in two denominations
---------------------------------------------------------
The retail book is denominated in riyals. The engine is frozen and it is
denominated in `SAR million`, in places a release cannot reach: `ecl.py` sums
`ead_sar_mn` and `ecl_sar_mn` and labels the result with the release's scale;
`attention_v2.py` carries the literal unit "SAR million" on two retail
families; `semantics.py` tells the analyst "in SAR million" in the compact
starting packet; and `export.py` writes "million" into the footer when a
release declares no scale at all. So the release-level `amount_scale` is not
a free choice -- it has to agree with what that hard-coded SQL sums, and that
SQL sums `*_sar_mn`.

Publishing ONLY millions is what the first revision did, and it is wrong for
a retail book: at the frozen zero-decimal money policy a facility balance of
about a hundred thousand riyals publishes as `SAR 0 million`. Every
account-level and customer-level monetary answer collapses to zero.

Publishing ONLY riyals is worse. It would either put riyals under names and
prose that say millions, or rename the columns -- and a rename takes the ECL
panel and the attention feed down with a DuckDB binder error, silently empties
the canonical measure table, and can only be repaired by editing seven frozen
modules.

So both are published, and each one is true about itself:

* `*_sar_mn` -- genuinely millions, declared `unit="rcy"`, which the engine
  resolves to the release's own `SAR million`. Every frozen consumer reads
  these and every one of them is correct.
* `*_sar` -- the same quantity in riyals, undivided, declared `unit="SAR"`
  explicitly. `display.unit_for_field` returns a declared unit verbatim
  unless it is `rcy`, so these render at zero decimals IN RIYALS regardless
  of the release scale, and a facility balance reads `SAR 102,340`.

Both carry the cross-reference in their own definition, so the analyst is
told which one to use at which grain and told never to sum the pair.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Riyals to the engine's declared scale. One place, named.
SAR_PER_MILLION = 1_000_000.0

#: What the published release declares itself to be denominated in. Forced by
#: the frozen engine, not chosen: `ecl.py` and `attention_v2.py` sum the
#: `*_sar_mn` columns and label the result with this scale, so the scale has
#: to be the one those columns are actually in.
CURRENCY = "SAR"
AMOUNT_SCALE = "million"

#: The unit declared on the riyal twin of every money column. NOT "rcy":
#: `display.unit_for_field` resolves `rcy` to the release's own denomination
#: and returns anything else verbatim, so an explicit "SAR" is what lets one
#: release hold both denominations and render each one correctly.
#: `display.classify("SAR")` matches its money pattern, so a riyal figure is
#: still governed by the same zero-decimal money policy.
UNIT_SAR = "SAR"

#: The source book every mapping below reads from, named once so lineage and
#: findings quote the same thing.
SOURCE_RELATION = "retail_facility_month"

# The engine's relation names. Keeping them is what keeps `catalog.JOINS`,
# `schema.domain_of_relation` and the retail semantic table pointing at real
# things.
ACCOUNT = "retail_account_month"
#: A fifth relation, at the grain the application scorecard actually records
#: at: ONE ROW PER FACILITY, not one per facility-month.
#:
#: The eighty-one application-model columns are frozen when the facility is
#: written and are then repeated, identically, on every month it stays on the
#: book. Published monthly they are 1.35 million copies of 85,476 facts and
#: about a gigabyte of a session's memory; published at their own grain they
#: are 85,476 rows and about seventy megabytes, and they say exactly the same
#: thing.
#:
#: The engine's join graph does not carry a warning for this relation, because
#: it is not one of the four the engine's own retail book has. So the warning
#: is written into the relation's own description and into every field of it:
#: joining it to the monthly book repeats each value once per month the
#: facility is live, and a sum across that join counts one origination many
#: times.
ORIGINATION = "retail_origination_facility"
CUSTOMER = "retail_customer_month"
BEHAVIOUR = "retail_behaviour_month"
COLLATERAL = "retail_collateral_month"

#: The engine's unit vocabulary, keyed by the retail contract's own unit. The
#: engine reads a unit to decide how a figure is written and whether it may be
#: added up (`display.CATALOG_UNITS`, `schema.ADDITIVE_UNITS`), so a unit
#: spelled inventively is a figure published wrong.
UNIT_FROM_CONTRACT: dict[str, str] = {
    "SAR": "rcy",
    "SAR/month": "rcy",
    "probability": "probability_0_1",
    "ratio": "ratio",
    "percentage points": "percentage points",
    "days": "days",
    "months": "months",
    "count": "count",
    "points": "index",
    "WoE": "index",
    "x": "times",
    "": "",
}


def engine_unit(contract_unit: str | None) -> str:
    """The engine's word for what the retail contract declared."""
    return UNIT_FROM_CONTRACT[str(contract_unit or "")]


# ---- derivations -------------------------------------------------------
#
# Every derivation is a pure function of columns this snapshot publishes, and
# each one carries the sentence that says so into the release. There is no
# derivation here that invents a concept: each is a restatement of a
# published column in the unit or the vocabulary the engine expects.

SECURED_PRODUCTS = ("AUTO_LOAN", "HOME_LOAN")

#: Non-overlapping fine arrears bins, derived from the published day count.
#: The coarse `dpd_bucket` the book publishes stops at 1-29; a question about
#: WHERE inside 1-29 a movement sits needs the split, and `dpd` is an exact
#: integer day count, so the split is a restatement rather than an estimate.
FINE_BINS: tuple[tuple[int, int, str], ...] = (
    (0, 0, "Current"), (1, 9, "1-9"), (10, 19, "10-19"), (20, 29, "20-29"),
    (30, 59, "30-59"), (60, 89, "60-89"), (90, 179, "90-179"),
    (180, 10_000, "180+"),
)


def _money(series: Any) -> Any:
    return series.astype("float64") / SAR_PER_MILLION


def _to_percent(series: Any) -> Any:
    return series.astype("float64") * 100.0


def _secured_flag(frame: Any) -> Any:
    return frame["product_code"].isin(SECURED_PRODUCTS).astype("int64")


def _vintage_year(frame: Any) -> Any:
    return frame["origination_vintage"].astype("string").str.slice(0, 4).astype(
        "Int64")


def _fine_bucket(frame: Any) -> Any:
    import pandas as pd

    days = pd.to_numeric(frame["dpd"], errors="coerce")
    out = pd.Series(pd.NA, index=frame.index, dtype="string")
    for low, high, label in FINE_BINS:
        out = out.mask(days.between(low, high), label)
    return out


def _limit_sar(frame: Any) -> Any:
    """The sanctioned limit, or the original advance where there is no limit.

    A card has a credit limit; an amortising facility has an original
    finance amount and no revolving limit. The book publishes both columns
    and leaves the inapplicable one null, so the rule is a coalesce and it is
    published as one. In riyals, which is how the book records both columns.
    """
    return frame["current_credit_limit_sar"].fillna(
        frame["original_finance_amount_sar"]).astype("float64")


def _limit(frame: Any) -> Any:
    """`_limit_sar` in millions. One rule, stated once, divided once."""
    return _money(_limit_sar(frame))


# ---- the map -----------------------------------------------------------


@dataclass(frozen=True)
class Mapping:
    """One published column of one projected relation."""

    relation: str
    column: str
    #: The retail column this comes from, or "" when `derive` builds it.
    source: str = ""
    #: Overrides the unit read from the retail contract. Set where the
    #: projection changes the unit (a ratio published as a percentage).
    unit: str = ""
    label: str = ""
    definition: str = ""
    group: str = ""
    #: Overrules the unit's own verdict on whether the column may be summed.
    #: Used where a CUSTOMER-grain value rides on a facility row: income is
    #: money, and money is additive, but adding one customer's income once per
    #: facility they hold is the defect the retail catalogue warns about.
    aggregation: str = ""
    #: The sentence recorded in the release for this field.
    lineage: str = ""
    derive: Callable[[Any], Any] | None = field(default=None, compare=False)
    #: Columns the derivation reads. Checked against the snapshot before use.
    needs: tuple[str, ...] = ()

    @property
    def is_derived(self) -> bool:
        return self.derive is not None

    @property
    def reads(self) -> tuple[str, ...]:
        return self.needs if self.is_derived else ((self.source,)
                                                   if self.source else ())


def _m(relation: str, column: str, source: str = "", **kw: Any) -> Mapping:
    return Mapping(relation=relation, column=column, source=source, **kw)


# ---- the riyal twin ----------------------------------------------------
#
# Every money column is published twice. The `*_sar_mn` mapping is authored
# by hand, because it is the one the frozen engine reads by name; its riyal
# twin is GENERATED from it, so the pair can never drift apart in source,
# label, group or additivity. Only the division differs.

#: The undivided derivation for a money column that is computed rather than
#: read. A derived money mapping with no entry here is refused at import
#: rather than published as a copy of its own millions form.
RIYAL_DERIVE: dict[str, Callable[[Any], Any]] = {"limit_sar_mn": _limit_sar}

_DIVISION = re.compile(r",?\s*÷\s*1,000,000")

#: Appended to the definition of a millions column, and to its twin's. The
#: analyst is told which one belongs at which grain, in the release itself,
#: because the catalogue is the only place a frozen engine will read it from.
MILLIONS_NOTE = (
    " Millions of riyals. A monetary figure is published with no decimal "
    "places, so at facility or customer grain read `{twin}` instead: it is "
    "the same quantity in riyals, and one facility is a small fraction of a "
    "million and publishes here as SAR 0 million.")

RIYALS_NOTE = (
    " In riyals, exactly as the source book records it, for facility- and "
    "customer-level figures. The same quantity as `{base}` x 1,000,000 -- "
    "report one or the other and never the sum of the pair.")


def riyal_name(column: str) -> str:
    """The riyal twin's name. `ead_sar_mn` -> `ead_sar`."""
    if not column.endswith("_sar_mn"):
        raise ValueError(f"{column!r} is denominated in the reporting "
                         f"currency but is not named `*_sar_mn`, so its "
                         f"riyal twin cannot be named without guessing.")
    return column[:-3]


def millions_name(column: str) -> str:
    """The millions column a riyal twin restates. `ead_sar` -> `ead_sar_mn`."""
    return column + "_mn"


def riyal_lineage(text: str) -> str:
    """The twin's lineage: its base's, with the division taken back out."""
    return (_DIVISION.sub("", text).strip() + " Riyals, undivided.").strip()


def riyal_twin(base: Mapping) -> Mapping:
    """The riyal twin of one millions mapping. Same source, no division."""
    derive = RIYAL_DERIVE.get(base.column)
    if base.is_derived and derive is None:
        raise ValueError(
            f"{base.column!r} is a DERIVED money column and no undivided "
            f"derivation is declared for it in RIYAL_DERIVE, so its riyal "
            f"twin would silently repeat the millions figure.")
    return Mapping(
        relation=base.relation, column=riyal_name(base.column),
        source=base.source, unit=UNIT_SAR, label=base.label,
        definition=base.definition, group=base.group,
        aggregation=base.aggregation,
        lineage=riyal_lineage(base.lineage),
        derive=derive, needs=base.needs)


def with_riyals(mappings: tuple[Mapping, ...]) -> tuple[Mapping, ...]:
    """Every money mapping followed immediately by its riyal twin."""
    out: list[Mapping] = []
    for mapping in mappings:
        out.append(mapping)
        if mapping.unit == "rcy":
            out.append(riyal_twin(mapping))
    return tuple(out)


#: Concepts the engine's retail book declares that THIS book does not carry.
#: Absent from the release on purpose: the engine drops a canonical term whose
#: field a release does not hold, which is how "we do not publish that" gets
#: said instead of answered.
GAPS: tuple[tuple[str, str], ...] = (
    ("retail_account_month.ecl_12m_sar_mn",
     "This book publishes one measured allowance, `ecl_final_sar`, and states "
     "its horizon in `ecl_horizon_type`. A separate 12-month figure is not "
     "published, so none is projected."),
    ("retail_account_month.ecl_lifetime_sar_mn",
     "As above: the lifetime allowance is not published as its own column."),
    ("retail_customer_month.behaviour_score",
     "The behavioural score is published at FACILITY grain and this book "
     "records no customer-level score. Aggregating one would be authoring a "
     "score, not reading one, so the customer relation carries none."),
    ("retail_customer_month.accounts_held",
     "Projected as `facilities_held`: this book's entity is a facility, and "
     "calling it an account in a customer roll-up would name a thing the "
     "book does not have."),
)


ACCOUNT_MAP: tuple[Mapping, ...] = (
    _m(ACCOUNT, "account_id", "facility_id", group="Identity",
       label="Facility id",
       definition="Stable facility identifier. One facility is one row in "
                  "this month.",
       lineage="retail_facility_month.facility_id, renamed. The engine's "
               "retail book calls its entity an account; this book's entity "
               "is a facility and the id is the facility's."),
    _m(ACCOUNT, "customer_id", "customer_id", group="Identity",
       label="Customer id", lineage="retail_facility_month.customer_id"),
    _m(ACCOUNT, "reporting_month", "reporting_month", group="Period",
       label="Reporting month",
       definition="Reporting month as YYYY-MM. The month-end this row "
                  "describes.",
       lineage="retail_facility_month.reporting_month"),
    _m(ACCOUNT, "product", "product_label", group="Product", label="Product",
       definition="Credit Card, Personal Finance, Auto Finance or Home "
                  "Finance.",
       lineage="retail_facility_month.product_label, the governed display "
               "label of product_code."),
    _m(ACCOUNT, "sub_product", "product_subsegment", group="Product",
       label="Sub-product",
       lineage="retail_facility_month.product_subsegment"),
    _m(ACCOUNT, "secured_flag", unit="count", group="Product",
       label="Secured", derive=_secured_flag, needs=("product_code",),
       definition="1 when the product is secured.",
       lineage="Derived: 1 where product_code is AUTO_LOAN or HOME_LOAN, "
               "which are this book's secured products."),
    _m(ACCOUNT, "origination_month", "origination_vintage", group="Vintage",
       label="Origination month",
       lineage="retail_facility_month.origination_vintage"),
    _m(ACCOUNT, "vintage_year", unit="count", group="Vintage",
       label="Origination vintage year", derive=_vintage_year,
       needs=("origination_vintage",),
       definition="The calendar year the facility was written.",
       lineage="Derived: the year part of origination_vintage."),
    _m(ACCOUNT, "months_on_book", "months_on_book", group="Vintage",
       label="Months on book",
       lineage="retail_facility_month.months_on_book"),
    _m(ACCOUNT, "origination_channel", "origination_channel",
       group="Origination", label="Origination channel",
       lineage="retail_facility_month.origination_channel"),
    _m(ACCOUNT, "customer_segment", "customer_segment", group="Segmentation",
       label="Customer segment",
       lineage="retail_facility_month.customer_segment"),
    _m(ACCOUNT, "employment_type", "employment_status", group="Segmentation",
       label="Employment status",
       definition="How the customer is paid: GOVERNMENT, "
                  "GOVERNMENT_RELATED, PRIVATE_SECTOR, SELF_EMPLOYED or "
                  "RETIRED. These are this book's governed values.",
       lineage="retail_facility_month.employment_status, renamed to the "
               "engine's column name. The VALUES are this book's own and are "
               "not mapped onto another book's wording."),
    _m(ACCOUNT, "salary_transfer_flag", "salary_transfer_flag",
       group="Segmentation", label="Salary transferred to the bank",
       lineage="retail_facility_month.salary_transfer_flag"),
    _m(ACCOUNT, "region", "region_label", group="Segmentation",
       label="Region", lineage="retail_facility_month.region_label"),
    _m(ACCOUNT, "limit_sar_mn", unit="rcy", group="Exposure", label="Limit",
       derive=_limit,
       needs=("current_credit_limit_sar", "original_finance_amount_sar"),
       definition="Sanctioned credit limit where the product revolves, and "
                  "the original finance amount where it does not.",
       lineage="Derived: current_credit_limit_sar, falling back to "
               "original_finance_amount_sar where it is null, "
               "÷ 1,000,000."),
    _m(ACCOUNT, "balance_sar_mn", "gross_carrying_amount_sar", unit="rcy",
       group="Exposure", label="Gross carrying amount",
       definition="Outstanding principal plus accrued profit: the exposure "
                  "the loss allowance is measured against. A month-end "
                  "level, not a flow.",
       lineage="retail_facility_month.gross_carrying_amount_sar ÷ 1,000,000."),
    _m(ACCOUNT, "ead_sar_mn", "ead_base_sar", unit="rcy", group="Exposure",
       label="Exposure at default",
       definition="Exposure at default on the BASE scenario. The book "
                  "publishes an upturn and a downturn EAD as well; this "
                  "column is the base one and the others are beside it.",
       lineage="retail_facility_month.ead_base_sar ÷ 1,000,000."),
    _m(ACCOUNT, "undrawn_sar_mn", "undrawn_commitment_sar", unit="rcy",
       group="Exposure", label="Undrawn commitment",
       lineage="retail_facility_month.undrawn_commitment_sar ÷ 1,000,000."),
    _m(ACCOUNT, "overdue_amount_sar_mn", "overdue_amount_sar", unit="rcy",
       group="Delinquency", label="Amount overdue",
       lineage="retail_facility_month.overdue_amount_sar ÷ 1,000,000."),
    _m(ACCOUNT, "utilisation_pct", "utilisation_ratio", unit="percent",
       group="Exposure", label="Utilisation",
       definition="Balance as a percentage of limit. Published for revolving "
                  "products only; null for every other product, which is not "
                  "the same as zero.",
       lineage="retail_facility_month.utilisation_ratio × 100."),
    _m(ACCOUNT, "stage", "ifrs9_stage", unit="count", group="IFRS 9",
       label="IFRS 9 stage",
       definition="IFRS 9 stage: 1, 2 or 3, as recorded by the staging "
                  "policy, not derived from days past due.",
       lineage="retail_facility_month.ifrs9_stage"),
    _m(ACCOUNT, "previous_stage", "previous_month_stage", unit="count",
       group="IFRS 9", label="Stage last month",
       lineage="retail_facility_month.previous_month_stage"),
    _m(ACCOUNT, "sicr_flag", "sicr_flag", unit="count", group="IFRS 9",
       label="SICR", lineage="retail_facility_month.sicr_flag"),
    _m(ACCOUNT, "sicr_quantitative_flag", "sicr_quantitative_flag",
       unit="count", group="IFRS 9", label="SICR: quantitative trigger",
       lineage="retail_facility_month.sicr_quantitative_flag"),
    _m(ACCOUNT, "sicr_qualitative_flag", "sicr_qualitative_flag",
       unit="count", group="IFRS 9", label="SICR: qualitative trigger",
       lineage="retail_facility_month.sicr_qualitative_flag"),
    _m(ACCOUNT, "sicr_dpd_backstop_flag", "sicr_dpd_backstop_flag",
       unit="count", group="IFRS 9", label="SICR: days-past-due backstop",
       lineage="retail_facility_month.sicr_dpd_backstop_flag"),
    _m(ACCOUNT, "default_flag", "current_default_flag", unit="count",
       group="IFRS 9", label="In default",
       lineage="retail_facility_month.current_default_flag"),
    _m(ACCOUNT, "credit_impaired_flag", "credit_impaired_flag", unit="count",
       group="IFRS 9", label="Credit impaired",
       lineage="retail_facility_month.credit_impaired_flag"),
    _m(ACCOUNT, "dpd_days", "dpd", group="Delinquency", label="Days past due",
       definition="Days past due at this month-end, from the oldest unpaid "
                  "due date. An exact day count, not a band.",
       lineage="retail_facility_month.dpd"),
    _m(ACCOUNT, "previous_dpd_days", "previous_month_dpd",
       group="Delinquency", label="Days past due last month",
       lineage="retail_facility_month.previous_month_dpd"),
    _m(ACCOUNT, "delinquency_bucket", "dpd_bucket", group="Delinquency",
       label="Arrears bucket",
       definition="CURRENT, 1-29, 30-59, 60-89, 90-179 or 180+. This book's "
                  "own governed bands.",
       lineage="retail_facility_month.dpd_bucket"),
    _m(ACCOUNT, "delinquency_bucket_fine", group="Delinquency",
       label="Arrears bucket, collections grain", derive=_fine_bucket,
       needs=("dpd",),
       definition="The same arrears split finely: Current, 1-9, 10-19, "
                  "20-29, 30-59, 60-89, 90-179, 180+. Non-overlapping, and "
                  "it reconciles to the published bucket exactly.",
       lineage="Derived from retail_facility_month.dpd, which is an exact "
               "integer day count. No estimate is involved."),
    _m(ACCOUNT, "collections_stage", "collections_stage", group="Delinquency",
       label="Collections stage",
       lineage="retail_facility_month.collections_stage"),
    _m(ACCOUNT, "forbearance_flag", "forbearance_flag", unit="count",
       group="Delinquency", label="Forbearance granted",
       lineage="retail_facility_month.forbearance_flag"),
    _m(ACCOUNT, "restructured_flag", "restructured_flag", unit="count",
       group="Delinquency", label="Restructured",
       lineage="retail_facility_month.restructured_flag"),
    _m(ACCOUNT, "cure_flag", "cure_flag", unit="count", group="Delinquency",
       label="Cured this month",
       lineage="retail_facility_month.cure_flag"),
    _m(ACCOUNT, "writeoff_flag", "writeoff_flag", unit="count",
       group="IFRS 9", label="Written off",
       lineage="retail_facility_month.writeoff_flag"),
    _m(ACCOUNT, "pd_pit_12m", "pd_pit_12m_base", group="IFRS 9",
       label="Point-in-time 12-month PD",
       definition="Point-in-time 12-month probability of default on the base "
                  "scenario. A decimal between 0 and 1.",
       lineage="retail_facility_month.pd_pit_12m_base"),
    _m(ACCOUNT, "pd_lifetime", "pd_pit_lifetime_base", group="IFRS 9",
       label="Lifetime PD",
       lineage="retail_facility_month.pd_pit_lifetime_base"),
    _m(ACCOUNT, "pd_ttc_12m", "pd_ttc_12m", group="IFRS 9",
       label="Through-the-cycle 12-month PD",
       lineage="retail_facility_month.pd_ttc_12m"),
    _m(ACCOUNT, "lgd_pct", "lgd_base", unit="percent", group="IFRS 9",
       label="LGD",
       definition="Loss given default on the base scenario.",
       lineage="retail_facility_month.lgd_base × 100."),
    _m(ACCOUNT, "ecl_sar_mn", "ecl_final_sar", unit="rcy", group="IFRS 9",
       label="Recognised ECL",
       definition="The allowance this book recognises: the scenario-weighted "
                  "expected credit loss plus any management overlay. It is "
                  "the booked figure.",
       lineage="retail_facility_month.ecl_final_sar ÷ 1,000,000."),
    _m(ACCOUNT, "ecl_weighted_sar_mn", "ecl_weighted_sar", unit="rcy",
       group="IFRS 9", label="Scenario-weighted ECL, before overlay",
       lineage="retail_facility_month.ecl_weighted_sar ÷ 1,000,000."),
    _m(ACCOUNT, "ecl_overlay_sar_mn", "management_overlay_sar", unit="rcy",
       group="IFRS 9", label="Management overlay",
       lineage="retail_facility_month.management_overlay_sar ÷ 1,000,000."),
    _m(ACCOUNT, "ecl_base_sar_mn", "ecl_base_sar", unit="rcy", group="IFRS 9",
       label="ECL, base scenario",
       lineage="retail_facility_month.ecl_base_sar ÷ 1,000,000."),
    _m(ACCOUNT, "ecl_upturn_sar_mn", "ecl_upturn_sar", unit="rcy",
       group="IFRS 9", label="ECL, upturn scenario",
       lineage="retail_facility_month.ecl_upturn_sar ÷ 1,000,000."),
    _m(ACCOUNT, "ecl_downturn_sar_mn", "ecl_downturn_sar", unit="rcy",
       group="IFRS 9", label="ECL, downturn scenario",
       lineage="retail_facility_month.ecl_downturn_sar ÷ 1,000,000."),
    _m(ACCOUNT, "ecl_horizon_type", "ecl_horizon_type", group="IFRS 9",
       label="ECL horizon",
       definition="Whether the recognised allowance is measured over twelve "
                  "months or over the lifetime. This book records the "
                  "horizon rather than publishing the two figures side by "
                  "side.",
       lineage="retail_facility_month.ecl_horizon_type"),
    _m(ACCOUNT, "ecl_coverage_ratio", "ecl_coverage_ratio", group="IFRS 9",
       label="ECL coverage", aggregation="not_additive",
       definition="Recognised ECL over gross carrying amount, as recorded "
                  "per facility. A portfolio coverage is the summed ECL over "
                  "the summed exposure, never the average of this column.",
       lineage="retail_facility_month.ecl_coverage_ratio"),
    _m(ACCOUNT, "write_off_sar_mn", "writeoff_amount_month_sar", unit="rcy",
       group="IFRS 9", label="Written off this month",
       lineage="retail_facility_month.writeoff_amount_month_sar "
               "÷ 1,000,000."),
    _m(ACCOUNT, "recovery_sar_mn", "recovery_amount_month_sar", unit="rcy",
       group="IFRS 9", label="Recovered this month",
       lineage="retail_facility_month.recovery_amount_month_sar "
               "÷ 1,000,000."),
    _m(ACCOUNT, "behaviour_score", "behavioural_score", group="Behaviour "
       "score", label="Behavioural score",
       definition="The behavioural score at this month-end, 300 (weak) to "
                  "900 (strong). Higher is safer.",
       lineage="retail_facility_month.behavioural_score"),
    _m(ACCOUNT, "behaviour_score_previous", "behavioural_score_previous_month",
       group="Behaviour score", label="Behavioural score last month",
       lineage="retail_facility_month.behavioural_score_previous_month"),
    _m(ACCOUNT, "score_band", "behavioural_score_band",
       group="Behaviour score", label="Behavioural score band",
       definition="Band of the behavioural score: E (weakest) to A+ "
                  "(strongest), at the governed band edges.",
       lineage="retail_facility_month.behavioural_score_band"),
    _m(ACCOUNT, "application_score", "application_score_at_origination",
       group="Application score", label="Application score at origination",
       definition="The application score the facility was written at. Frozen "
                  "at origination and unchanged on later month-ends.",
       lineage="retail_facility_month.application_score_at_origination"),
    _m(ACCOUNT, "application_score_band", "application_score_band",
       group="Application score", label="Application score band",
       lineage="retail_facility_month.application_score_band"),
    _m(ACCOUNT, "facility_status", "facility_status", group="Identity",
       label="Facility status",
       lineage="retail_facility_month.facility_status"),
    _m(ACCOUNT, "closure_reason", "closure_reason", group="Identity",
       label="Closure reason",
       lineage="retail_facility_month.closure_reason"),
    # CUSTOMER-grain values riding on a facility row. Carried because an
    # affordability question is a real one, and marked NOT ADDITIVE because
    # adding one customer's income once per facility is the defect this
    # book's own catalogue warns about.
    _m(ACCOUNT, "customer_income_sar_mn", "verified_total_monthly_income_sar",
       unit="rcy", aggregation="not_additive", group="Affordability",
       label="Verified monthly income (customer)",
       definition="Verified monthly salary plus other income, for the "
                  "CUSTOMER. It repeats on each facility that customer "
                  "holds: de-duplicate on customer_id before summing it.",
       lineage="retail_facility_month.verified_total_monthly_income_sar "
               "÷ 1,000,000. Customer grain."),
    _m(ACCOUNT, "debt_burden_ratio", "debt_burden_ratio",
       aggregation="not_additive", group="Affordability",
       label="Debt burden ratio (customer)",
       definition="Total monthly credit obligations over verified monthly "
                  "income, for the CUSTOMER. Repeats across that customer's "
                  "facilities.",
       lineage="retail_facility_month.debt_burden_ratio. Customer grain."),
)


CUSTOMER_MAP: tuple[Mapping, ...] = (
    _m(CUSTOMER, "customer_id", "customer_id", group="Identity",
       label="Customer id", lineage="retail_facility_month.customer_id"),
    _m(CUSTOMER, "reporting_month", "reporting_month", group="Period",
       label="Reporting month",
       lineage="retail_facility_month.reporting_month"),
    _m(CUSTOMER, "customer_segment", "customer_segment", group="Segmentation",
       label="Customer segment",
       lineage="One value per customer-month, taken from that customer's "
               "facility rows, which all carry the same value."),
    _m(CUSTOMER, "employment_type", "employment_status", group="Segmentation",
       label="Employment status",
       lineage="One value per customer-month, from that customer's facility "
               "rows."),
    _m(CUSTOMER, "region", "region_label", group="Segmentation",
       label="Region",
       lineage="One value per customer-month, from that customer's facility "
               "rows."),
    _m(CUSTOMER, "salary_transfer_flag", "salary_transfer_flag",
       group="Segmentation", label="Salary transferred to the bank",
       lineage="One value per customer-month."),
    _m(CUSTOMER, "tenure_months", "customer_tenure_months", group="Segmentation",
       label="Months since the relationship opened",
       lineage="retail_facility_month.customer_tenure_months, one value per "
               "customer-month."),
    _m(CUSTOMER, "facilities_held", unit="count", group="Segmentation",
       label="Facilities held this month",
       definition="How many facilities this customer holds at this "
                  "month-end.",
       lineage="Derived: count of that customer's rows in the month."),
    _m(CUSTOMER, "income_sar_mn", "verified_total_monthly_income_sar",
       unit="rcy", group="Affordability",
       label="Verified monthly income",
       lineage="retail_facility_month.verified_total_monthly_income_sar "
               "÷ 1,000,000, one value per customer-month. Additive ACROSS "
               "customers here, because this relation holds one row each."),
    _m(CUSTOMER, "obligations_sar_mn", "monthly_total_credit_obligations_sar",
       unit="rcy", group="Affordability",
       label="Monthly credit obligations",
       lineage="retail_facility_month.monthly_total_credit_obligations_sar "
               "÷ 1,000,000, one value per customer-month."),
    _m(CUSTOMER, "disposable_income_sar_mn", "disposable_income_sar",
       unit="rcy", group="Affordability", label="Disposable income",
       lineage="retail_facility_month.disposable_income_sar ÷ 1,000,000, "
               "one value per customer-month."),
    _m(CUSTOMER, "debt_burden_ratio", "debt_burden_ratio",
       aggregation="not_additive", group="Affordability",
       label="Debt burden ratio",
       lineage="retail_facility_month.debt_burden_ratio, one value per "
               "customer-month."),
    _m(CUSTOMER, "total_ead_sar_mn", "ead_base_sar", unit="rcy",
       group="Exposure", label="Exposure at default, all facilities",
       definition="This customer's base-scenario exposure at default, summed "
                  "over the facilities they hold this month.",
       lineage="Sum of retail_facility_month.ead_base_sar over the "
               "customer's facilities in the month, ÷ 1,000,000."),
    _m(CUSTOMER, "total_ecl_sar_mn", "ecl_final_sar", unit="rcy",
       group="IFRS 9", label="Recognised ECL, all facilities",
       lineage="Sum of retail_facility_month.ecl_final_sar over the "
               "customer's facilities in the month, ÷ 1,000,000."),
    _m(CUSTOMER, "worst_stage", "ifrs9_stage", unit="count", group="IFRS 9",
       label="Worst IFRS 9 stage",
       lineage="Maximum of retail_facility_month.ifrs9_stage over the "
               "customer's facilities in the month."),
    _m(CUSTOMER, "worst_dpd_days", "dpd", group="Delinquency",
       label="Worst days past due",
       lineage="Maximum of retail_facility_month.dpd over the customer's "
               "facilities in the month."),
)


#: The behavioural relation. Account-grain, one row per facility-month, and
#: the place the scorecard inputs live: a question about WHY a score moved is
#: a question about these columns, and they are published raw, transformed,
#: binned and weighted exactly as the book records them.
BEHAVIOUR_MAP: tuple[Mapping, ...] = (
    _m(BEHAVIOUR, "account_id", "facility_id", group="Identity",
       label="Facility id", lineage="retail_facility_month.facility_id"),
    _m(BEHAVIOUR, "reporting_month", "reporting_month", group="Period",
       label="Reporting month",
       lineage="retail_facility_month.reporting_month"),
    _m(BEHAVIOUR, "utilisation_pct", "utilisation_ratio", unit="percent",
       group="Behaviour variables", label="Utilisation",
       definition="Balance as a percentage of limit. Revolving products "
                  "only; null elsewhere.",
       lineage="retail_facility_month.utilisation_ratio × 100."),
    _m(BEHAVIOUR, "utilisation_change_3m_pp", "utilisation_change_3m_pp",
       group="Behaviour variables", label="Utilisation change over 3 months",
       definition="Change in utilisation over THREE months, in percentage "
                  "points. This book publishes a three-month change and no "
                  "one-month change.",
       lineage="retail_facility_month.utilisation_change_3m_pp"),
    _m(BEHAVIOUR, "payment_ratio_1m_pct", "payment_to_due_ratio_1m",
       unit="percent", group="Behaviour variables",
       label="Payment against amount due, this month",
       lineage="retail_facility_month.payment_to_due_ratio_1m × 100."),
    _m(BEHAVIOUR, "payment_ratio_3m_pct", "payment_to_due_ratio_3m",
       unit="percent", group="Behaviour variables",
       label="Payment against amount due, three months",
       lineage="retail_facility_month.payment_to_due_ratio_3m × 100."),
    _m(BEHAVIOUR, "missed_payments_3m", "missed_payment_count_3m",
       unit="count", group="Behaviour variables",
       label="Payments missed, three months",
       lineage="retail_facility_month.missed_payment_count_3m"),
    _m(BEHAVIOUR, "missed_payments_6m", "missed_payment_count_6m",
       unit="count", group="Behaviour variables",
       label="Payments missed, six months",
       lineage="retail_facility_month.missed_payment_count_6m"),
    _m(BEHAVIOUR, "months_30plus_12m", "months_30plus_count_12m",
       unit="count", group="Behaviour variables",
       label="Months 30+ past due, twelve months",
       lineage="retail_facility_month.months_30plus_count_12m"),
    _m(BEHAVIOUR, "max_dpd_3m", "max_dpd_3m", group="Behaviour variables",
       label="Worst days past due, three months",
       lineage="retail_facility_month.max_dpd_3m"),
    _m(BEHAVIOUR, "max_dpd_6m", "max_dpd_6m", group="Behaviour variables",
       label="Worst days past due, six months",
       lineage="retail_facility_month.max_dpd_6m"),
    _m(BEHAVIOUR, "max_dpd_12m", "max_dpd_12m", group="Behaviour variables",
       label="Worst days past due, twelve months",
       lineage="retail_facility_month.max_dpd_12m"),
    _m(BEHAVIOUR, "overlimit_days_3m", "overlimit_days_3m",
       group="Behaviour variables", label="Days over limit, three months",
       lineage="retail_facility_month.overlimit_days_3m"),
    _m(BEHAVIOUR, "cash_advance_share_3m", "cash_advance_share_3m",
       group="Behaviour variables", label="Cash advance share, three months",
       lineage="retail_facility_month.cash_advance_share_3m"),
    _m(BEHAVIOUR, "salary_delay_days", "salary_delay_days",
       group="Salary", label="Salary credited late by",
       lineage="retail_facility_month.salary_delay_days"),
    _m(BEHAVIOUR, "salary_missed_cycles_3m", "salary_missed_cycle_count_3m",
       unit="count", group="Salary", label="Salary cycles missed, three months",
       lineage="retail_facility_month.salary_missed_cycle_count_3m"),
    _m(BEHAVIOUR, "salary_change_3m_ratio", "salary_change_3m_ratio",
       group="Salary", label="Salary change over three months",
       lineage="retail_facility_month.salary_change_3m_ratio"),
    _m(BEHAVIOUR, "balance_buffer_months", "balance_buffer_months",
       group="Salary", label="Months of buffer in the account",
       lineage="retail_facility_month.balance_buffer_months"),
    _m(BEHAVIOUR, "bureau_score_current", "bureau_score_current",
       group="Bureau", label="Bureau score now",
       lineage="retail_facility_month.bureau_score_current"),
    _m(BEHAVIOUR, "bureau_score_change_3m", "bureau_score_change_3m",
       group="Bureau", label="Bureau score change, three months",
       lineage="retail_facility_month.bureau_score_change_3m"),
    _m(BEHAVIOUR, "bureau_external_dpd_max", "bureau_external_dpd_max",
       group="Bureau", label="Worst days past due elsewhere",
       lineage="retail_facility_month.bureau_external_dpd_max"),
    _m(BEHAVIOUR, "bureau_enquiries_3m", "bureau_enquiries_3m", unit="count",
       group="Bureau", label="Bureau enquiries, three months",
       lineage="retail_facility_month.bureau_enquiries_3m"),
    _m(BEHAVIOUR, "bureau_enquiries_6m", "bureau_enquiries_6m", unit="count",
       group="Bureau", label="Bureau enquiries, six months",
       lineage="retail_facility_month.bureau_enquiries_6m"),
)


COLLATERAL_MAP: tuple[Mapping, ...] = (
    _m(COLLATERAL, "account_id", "facility_id", group="Identity",
       label="Facility id", lineage="retail_facility_month.facility_id"),
    _m(COLLATERAL, "customer_id", "customer_id", group="Identity",
       label="Customer id", lineage="retail_facility_month.customer_id"),
    _m(COLLATERAL, "reporting_month", "reporting_month", group="Period",
       label="Reporting month",
       lineage="retail_facility_month.reporting_month"),
    _m(COLLATERAL, "product", "product_label", group="Product",
       label="Product", lineage="retail_facility_month.product_label"),
    _m(COLLATERAL, "collateral_value_sar_mn", "collateral_value_current_sar",
       unit="rcy", group="Collateral", label="Collateral value",
       lineage="retail_facility_month.collateral_value_current_sar "
               "÷ 1,000,000."),
    _m(COLLATERAL, "collateral_value_origination_sar_mn",
       "collateral_value_origination_sar", unit="rcy", group="Collateral",
       label="Collateral value at origination",
       lineage="retail_facility_month.collateral_value_origination_sar "
               "÷ 1,000,000."),
    _m(COLLATERAL, "ltv_pct", "ltv_current_ratio", unit="percent",
       group="Collateral", label="Loan to value",
       lineage="retail_facility_month.ltv_current_ratio × 100."),
    _m(COLLATERAL, "ltv_origination_pct", "ltv_origination_ratio",
       unit="percent", group="Collateral",
       label="Loan to value at origination",
       lineage="retail_facility_month.ltv_origination_ratio × 100."),
)



# ---- the scorecard inputs, carried verbatim ---------------------------
#
# One hundred and ninety-two columns publish each configured model input four
# ways -- the raw value, its weight-of-evidence transform, the bin it fell in
# and the points it contributed -- plus a missing flag. A question about WHY a
# score moved is a question about exactly these, and the raw/transformed/
# weighted distinction is the thing that must not be blurred.
#
# They are carried under their own names with the book's own definitions and
# units rather than remapped: there is no engine name to rename them to, and
# inventing one would make a reader hunt for the column the catalogue showed
# them. The RULE is declared here and the mappings are generated from the
# snapshot's own contract, so a book that gains or loses a model input is
# projected as it actually is rather than as this file remembers it.

FEATURE_PATTERN = re.compile(r"^beh_.+_(raw|transformed|missing_flag|"
                             r"points)$")

#: The application model's inputs, at origination grain.
ORIGINATION_FEATURE_PATTERN = re.compile(
    r"^app_.+_(raw|transformed|missing_flag|points)$")

ORIGINATION_COMPONENT_PATTERN = re.compile(
    r"^app_score_(logit|base_points|points_total|unclipped|value|band_value)$")

#: The published score components: logit, base points, total points, the
#: unclipped and clipped values and the band ordinal, for both models.
SCORE_COMPONENT_PATTERN = re.compile(r"^beh_score_"
                                     r"(logit|base_points|points_total|"
                                     r"unclipped|value|band_value)$")

FEATURE_GROUPS = {"app": "Application scorecard inputs",
                  "beh": "Behavioural scorecard inputs"}

#: Said on every column of the origination relation, because the fan-out is
#: the one thing a reader of it has to know.
ORIGINATION_CAVEAT = (
    " Recorded once, when the facility was written. This relation holds one "
    "row per facility: joined to the monthly book it repeats once per month "
    "the facility is live, so de-duplicate on account_id before summing "
    "anything from it.")


def feature_mappings(columns: dict[str, dict[str, Any]]) -> tuple[Mapping, ...]:
    """Every scorecard input and score component the snapshot publishes.

    Generated from the snapshot's own contract, carried verbatim, at the
    behavioural relation's grain -- which is the grain the book records them
    at: one facility, one month.

    The `_bin` label of each input is deliberately not among them. It names
    the interval the raw value fell in, and the raw value, its
    weight-of-evidence transform and the points it contributed are all
    published beside it -- so the bin is the one part of the quintuple that
    says nothing the other three do not, at the cost of forty-seven text
    columns on one and a third million rows. A question that needs the bin
    edges reads them from the model registry, which owns them.
    """
    out: list[Mapping] = []
    for name in sorted(columns):
        match = FEATURE_PATTERN.match(name) or SCORE_COMPONENT_PATTERN.match(
            name)
        if not match:
            continue
        spec = columns[name]
        out.append(Mapping(
            relation=BEHAVIOUR, column=name, source=name,
            label=str(spec.get("business_name") or ""),
            definition=str(spec.get("definition") or ""),
            group=FEATURE_GROUPS["beh"],
            lineage=f"retail_facility_month.{name}, carried verbatim."))
    return with_riyals(tuple(out))


def origination_mappings(columns: dict[str, dict[str, Any]]
                         ) -> tuple[Mapping, ...]:
    """The application model's inputs and score components, at their grain."""
    out: list[Mapping] = [
        Mapping(relation=ORIGINATION, column="account_id",
                source="facility_id", group="Identity", label="Facility id",
                definition="The facility these origination values were "
                           "recorded for." + ORIGINATION_CAVEAT,
                lineage="retail_facility_month.facility_id"),
        Mapping(relation=ORIGINATION, column="customer_id",
                source="customer_id", group="Identity", label="Customer id",
                definition="The customer the facility was written to."
                           + ORIGINATION_CAVEAT,
                lineage="retail_facility_month.customer_id"),
        Mapping(relation=ORIGINATION, column="origination_month",
                source="origination_vintage", group="Period",
                label="Origination month",
                definition="The month the facility was written, as YYYY-MM. "
                           "This relation's period column.",
                lineage="retail_facility_month.origination_vintage"),
        Mapping(relation=ORIGINATION, column="product",
                source="product_label", group="Product", label="Product",
                definition="The product the facility was written as."
                           + ORIGINATION_CAVEAT,
                lineage="retail_facility_month.product_label"),
    ]
    for name in sorted(columns):
        if not (ORIGINATION_FEATURE_PATTERN.match(name)
                or ORIGINATION_COMPONENT_PATTERN.match(name)):
            continue
        spec = columns[name]
        out.append(Mapping(
            relation=ORIGINATION, column=name, source=name,
            label=str(spec.get("business_name") or ""),
            definition=str(spec.get("definition") or "")
            + ORIGINATION_CAVEAT,
            group=FEATURE_GROUPS["app"],
            lineage=f"retail_facility_month.{name}, carried verbatim from "
                    f"the facility's first published month."))
    return with_riyals(tuple(out))

ORIGINATION_MAP: tuple[Mapping, ...] = ()

# Each money mapping above is authored once, in millions, because that is the
# name and the denomination the frozen engine reads. The riyal twin is added
# here, generated from it, so the two can never disagree about anything but
# the division. A relation with no money column passes through unchanged.
ACCOUNT_MAP = with_riyals(ACCOUNT_MAP)
CUSTOMER_MAP = with_riyals(CUSTOMER_MAP)
BEHAVIOUR_MAP = with_riyals(BEHAVIOUR_MAP)
COLLATERAL_MAP = with_riyals(COLLATERAL_MAP)
ORIGINATION_MAP = with_riyals(ORIGINATION_MAP)

MAPS: dict[str, tuple[Mapping, ...]] = {
    ACCOUNT: ACCOUNT_MAP,
    ORIGINATION: ORIGINATION_MAP,
    CUSTOMER: CUSTOMER_MAP,
    BEHAVIOUR: BEHAVIOUR_MAP,
    COLLATERAL: COLLATERAL_MAP,
}

#: Every money column of the release, as (millions column, riyal column)
#: pairs. Read by the gates, the oracles and the contract document, so none
#: of them has to re-derive which columns are the pair.
MONEY_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    relation: tuple((m.column, riyal_name(m.column))
                    for m in mappings if m.unit == "rcy")
    for relation, mappings in MAPS.items()
}

#: Grain, keys and period column per projected relation, in the engine's own
#: vocabulary. `catalog.JOINS` states how these four join; keeping the names
#: and the key columns is what keeps its repetition warnings true here.
RELATION_SPEC: dict[str, dict[str, Any]] = {
    ACCOUNT: {
        "grain": "one row per retail facility per reporting month",
        "key_columns": ("account_id", "reporting_month"),
        "description": ("The retail facility as at a month end: product, "
                        "balances, IFRS 9 position, delinquency and score. "
                        "Projected read-only from the Cockpit Data domain."),
    },
    CUSTOMER: {
        "grain": "one row per retail customer per reporting month",
        "key_columns": ("customer_id", "reporting_month"),
        "description": ("The customer as at a month end: segment, "
                        "affordability, and their facilities rolled up. "
                        "De-duplicated from the facility book, which repeats "
                        "customer values on every facility row."),
    },
    BEHAVIOUR: {
        "grain": "one row per retail facility per reporting month",
        "key_columns": ("account_id", "reporting_month"),
        "description": ("The behavioural variables behind the score: how the "
                        "facility is used and repaid, and what the bureau "
                        "says."),
    },
    ORIGINATION: {
        "grain": "one row per retail facility, as it was written",
        "key_columns": ("account_id",),
        "description": ("What the application scorecard recorded when the "
                        "facility was written: every configured input raw, "
                        "transformed and weighted, and the score it "
                        "produced. ONE ROW PER FACILITY -- joining it to a "
                        "monthly relation repeats each value once per month "
                        "the facility is live."),
    },
    COLLATERAL: {
        "grain": "one row per secured retail facility per reporting month",
        "key_columns": ("account_id", "reporting_month"),
        "description": ("Security on secured retail lending. An unsecured "
                        "facility has no row here at all, rather than a row "
                        "of zeroes."),
    },
}


def source_columns(relation: str) -> tuple[str, ...]:
    """Every retail column this relation's projection reads."""
    seen: list[str] = []
    for mapping in MAPS[relation]:
        for name in mapping.reads:
            if name and name not in seen:
                seen.append(name)
    return tuple(seen)


def all_source_columns() -> tuple[str, ...]:
    seen: list[str] = []
    for relation in MAPS:
        for name in source_columns(relation):
            if name not in seen:
                seen.append(name)
    return tuple(seen)


__all__ = ["ACCOUNT", "ACCOUNT_MAP", "ORIGINATION", "ORIGINATION_MAP",
           "ORIGINATION_CAVEAT", "origination_mappings", "AMOUNT_SCALE", "BEHAVIOUR",
           "BEHAVIOUR_MAP", "COLLATERAL", "COLLATERAL_MAP", "CURRENCY",
           "FEATURE_PATTERN", "SCORE_COMPONENT_PATTERN", "feature_mappings",
           "CUSTOMER", "CUSTOMER_MAP", "FINE_BINS", "GAPS", "MAPS",
           "Mapping", "RELATION_SPEC", "SAR_PER_MILLION", "SECURED_PRODUCTS",
           "UNIT_FROM_CONTRACT", "UNIT_SAR", "MONEY_PAIRS", "RIYAL_DERIVE",
           "SOURCE_RELATION", "MILLIONS_NOTE", "RIYALS_NOTE",
           "all_source_columns",
           "engine_unit", "millions_name", "riyal_lineage", "riyal_name",
           "riyal_twin", "source_columns", "with_riyals"]
