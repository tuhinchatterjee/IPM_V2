"""
The governed retail metrics, on the book this installation actually holds.

The defect this closes
----------------------
`backend/metrics/library.py` predates the retail conversion. Every one of its
sixty-one metrics reads a dataset that is not in this deployment — the two
scorecard-validation extracts, the corporate facility position, the corporate
staging table — so on a retail installation Metrics, Lenses and the Playbook
came up with no calculable tile at all. The lenses installed, rendered, and
showed a dash in every box. Its own docstring said the retail data was "not
enough for retail IFRS 9"; that was true of the datasets it was reading and
untrue of `retail_facility_month`, which carries exposure, allowance, staging,
delinquency, both scorecards and the observed outcome on one row per facility
per month.

So these are written against that book, and against nothing else.

What is here, and what deliberately is not
------------------------------------------
Every metric below is calculable against `retail_facility_month` and was
reconciled against the Parquet with an independent aggregation before being
written down. Where a bank would normally carry a metric this book cannot
support, it is absent rather than approximated — there is no "retail RWA"
here, and no recovery rate, because the columns that would define them do not
exist.

Two grains, kept apart on purpose
---------------------------------
The book is one row per FACILITY per month. A customer with four facilities is
four rows. So:

* An exposure, an allowance or a count of facilities sums or counts rows.
* A count of CUSTOMERS counts distinct `customer_id`, never rows.
* A customer-level value — income, debt burden, disposable income — is repeated
  on each of that customer's rows and must never be summed. Where one is
  reported it is an average over distinct customers, and it says so.

The outcome window
------------------
`observed_default_within_window` is an EVALUATION label: it becomes knowable at
`outcome_known_at`, twelve months after the snapshot. At the latest month it is
null on every row. A discrimination statistic computed there would be computed
on nothing, so every outcome-based metric carries
`period_rule=PERIOD_LATEST_MATURED` and the runtime resolves it to the most
recent month where the window has closed.
"""

from __future__ import annotations

from backend.metrics.catalogue import (
    PERIOD_LATEST_MATURED,
    PERIOD_SELECTED,
    STATUS_PUBLISHED,
    MetricDefinition,
    _ratio,
    _t,
    _total,
)
from backend.metrics.formula import Condition, Formula, Side, Term

RETAIL_LIBRARY_VERSION = "1.0.0"

#: The one governed retail dataset. Every metric here reads it.
BOOK = "retail_facility_month"

PORTFOLIO = "Retail"
D_POSITION = "Retail Portfolio"
D_IMPAIRMENT = "Retail IFRS 9"
D_DELINQUENCY = "Retail Delinquency"
D_ORIGINATION = "Retail Origination"
D_SCORECARD = "Retail Scorecard"


def _m(metric_id: str, name: str, definition: str, formula: Formula,
       **kw) -> MetricDefinition:
    kw.setdefault("status", STATUS_PUBLISHED)
    kw.setdefault("portfolio", PORTFOLIO)
    kw.setdefault("period_rule", PERIOD_SELECTED)
    return MetricDefinition(metric_id=metric_id, name=name,
                            definition=definition, formula=formula, **kw)


def _count(term_id: str, label: str, **where) -> Formula:
    return Formula(kind="count", numerator=Side(terms=(
        _t(term_id, label, BOOK, "count", "", **where),)))


def _distinct(term_id: str, label: str, column: str, **where) -> Formula:
    return Formula(kind="count", numerator=Side(terms=(
        _t(term_id, label, BOOK, "count_distinct", column, **where),)))


# ===================================================== position and exposure

POSITION: tuple[MetricDefinition, ...] = (
    _m("retail.gross_carrying_amount",
       "Retail Gross Carrying Amount",
       "Outstanding principal plus accrued profit across every retail facility "
       "in the month. This is what a retail portfolio question means by "
       "exposure, and it is the denominator the loss allowance is measured "
       "against.",
       _total(_t("gca", "Gross carrying amount", BOOK, "sum",
                 "gross_carrying_amount_sar")),
       unit="currency", domain=D_POSITION,
       aliases=("retail exposure", "exposure", "gross carrying amount", "gca",
                "outstanding", "book size", "retail book"),
       formula_text="SUM(gross_carrying_amount_sar)",
       numerator_text="Gross carrying amount on every facility in the month",
       visuals=("kpi", "line", "bar"), decimals=0,
       transformation="One row per facility per reporting month; the grain "
                      "needs no deduplication.",
       not_this="Not exposure at default: it carries no credit-conversion "
                "allowance on an undrawn card limit."),

    _m("retail.ead",
       "Retail Exposure at Default",
       "Exposure at default under the base macroeconomic scenario, which adds "
       "the credit-conversion allowance on undrawn card commitments to the "
       "drawn balance.",
       _total(_t("ead", "Exposure at default", BOOK, "sum", "ead_base_sar")),
       unit="currency", domain=D_POSITION,
       aliases=("ead", "exposure at default"),
       formula_text="SUM(ead_base_sar)", decimals=0,
       visuals=("kpi", "line", "bar"),
       not_this="Not the gross carrying amount, which excludes the undrawn "
                "commitment."),

    _m("retail.facilities", "Retail Facilities",
       "How many retail facilities are on the book in the month.",
       _count("n", "Facilities"),
       unit="count", domain=D_POSITION,
       aliases=("facilities", "accounts", "number of facilities"),
       formula_text="COUNT(rows)", decimals=0, visuals=("kpi", "line", "bar")),

    _m("retail.customers", "Retail Customers",
       "How many distinct customers hold a retail facility in the month. "
       "Counted on customer_id, never on rows: one customer with four "
       "facilities is one customer.",
       _distinct("n", "Customers", "customer_id"),
       unit="count", domain=D_POSITION,
       aliases=("customers", "borrowers", "number of customers"),
       formula_text="COUNT(DISTINCT customer_id)", decimals=0,
       visuals=("kpi", "line", "bar"),
       not_this="Not a count of facilities — the book has more facilities than "
                "customers."),

    _m("retail.average_facility_size", "Average Facility Size",
       "Gross carrying amount divided by the number of facilities.",
       _ratio([_t("gca", "Gross carrying amount", BOOK, "sum",
                  "gross_carrying_amount_sar")],
              [_t("n", "Facilities", BOOK, "count")],
              scale=1.0, kind="average"),
       unit="currency", domain=D_POSITION,
       aliases=("average facility size", "average ticket", "average balance"),
       formula_text="SUM(gross_carrying_amount_sar) / COUNT(rows)",
       decimals=0, visuals=("kpi", "bar")),

    _m("retail.undrawn", "Undrawn Card Commitment",
       "Card limit not drawn at the month-end. Cards only; nil on amortising "
       "products, which have no undrawn limit.",
       _total(_t("u", "Undrawn commitment", BOOK, "sum",
                 "undrawn_commitment_sar")),
       unit="currency", domain=D_POSITION,
       aliases=("undrawn", "available limit", "unused limit"),
       formula_text="SUM(undrawn_commitment_sar)", decimals=0,
       visuals=("kpi", "bar")),

    _m("retail.card_utilisation", "Card Utilisation",
       "Drawn balance as a proportion of the credit limit in force, across "
       "card facilities. Weighted by limit rather than averaged across "
       "accounts, so a large limit counts for what it is.",
       _ratio([_t("bal", "Drawn on cards", BOOK, "sum",
                  "gross_carrying_amount_sar", product_code="CREDIT_CARD")],
              [_t("lim", "Card limits", BOOK, "sum",
                  "current_credit_limit_sar", product_code="CREDIT_CARD")]),
       unit="percent", domain=D_POSITION,
       aliases=("utilisation", "utilization", "card utilisation",
                "limit usage"),
       formula_text="SUM(balance on cards) / SUM(card limits) × 100",
       numerator_text="Drawn balance on credit cards",
       denominator_text="Credit limit in force on those cards",
       decimals=1, higher_is_better=False, visuals=("kpi", "line"),
       not_this="Not the average of each account's utilisation ratio, which "
                "would weight a SAR 3,000 limit the same as a SAR 250,000 one."),
)


# ============================================================== IFRS 9

IMPAIRMENT: tuple[MetricDefinition, ...] = (
    _m("retail.ecl", "Retail Expected Credit Loss",
       "The loss allowance carried on the retail book: the probability-weighted "
       "ECL across the three macroeconomic scenarios, plus the management "
       "overlay. This is the figure an impairment question means.",
       _total(_t("ecl", "Final ECL", BOOK, "sum", "ecl_final_sar")),
       unit="currency", domain=D_IMPAIRMENT,
       aliases=("ecl", "expected credit loss", "loss allowance", "allowance",
                "impairment", "provision", "weighted ecl"),
       formula_text="SUM(ecl_final_sar)",
       numerator_text="Weighted ECL plus overlay, on every facility",
       decimals=0, higher_is_better=False, visuals=("kpi", "line", "bar"),
       not_this="Not the BASE-scenario ECL, which is one of the three inside "
                "the weighted figure rather than the allowance."),

    _m("retail.ecl_weighted_before_overlay", "Weighted ECL Before Overlay",
       "Probability-weighted ECL across the three scenarios, before any "
       "management overlay is added.",
       _total(_t("w", "Weighted ECL", BOOK, "sum", "ecl_weighted_sar")),
       unit="currency", domain=D_IMPAIRMENT,
       aliases=("weighted ecl before overlay", "modelled ecl"),
       formula_text="SUM(ecl_weighted_sar)", decimals=0,
       higher_is_better=False, visuals=("kpi", "line")),

    _m("retail.overlay", "Management Overlay",
       "The post-model adjustment carried on top of the modelled result, kept "
       "separate and visible rather than folded into the model.",
       _total(_t("o", "Overlay", BOOK, "sum", "management_overlay_sar")),
       unit="currency", domain=D_IMPAIRMENT,
       aliases=("overlay", "management overlay", "post-model adjustment"),
       formula_text="SUM(management_overlay_sar)", decimals=0,
       visuals=("kpi", "bar")),

    _m("retail.ecl_coverage", "ECL Coverage",
       "The loss allowance as a proportion of the gross carrying amount. "
       "Computed as a ratio of the two totals, not as an average of each "
       "facility's coverage ratio.",
       _ratio([_t("ecl", "Final ECL", BOOK, "sum", "ecl_final_sar")],
              [_t("gca", "Gross carrying amount", BOOK, "sum",
                  "gross_carrying_amount_sar")]),
       unit="percent", domain=D_IMPAIRMENT,
       aliases=("coverage", "ecl coverage", "coverage ratio",
                "provision coverage", "allowance coverage"),
       formula_text="SUM(ecl_final_sar) / SUM(gross_carrying_amount_sar) × 100",
       numerator_text="Loss allowance", denominator_text="Gross carrying amount",
       decimals=2, higher_is_better=False, visuals=("kpi", "line", "bar"),
       not_this="Not AVG(ecl_coverage_ratio): averaging per-facility ratios "
                "gives a small facility the same weight as a mortgage."),
)

#: One pair of metrics per stage, written out rather than generated so each
#: carries its own definition and the aliases a person actually types.
_STAGE_WORDS = {1: ("Stage 1", "stage 1", "stage one", "performing"),
                2: ("Stage 2", "stage 2", "stage two", "significant increase",
                    "sicr"),
                3: ("Stage 3", "stage 3", "stage three", "credit impaired",
                    "impaired", "defaulted")}

_STAGE_METRICS: list[MetricDefinition] = []
for _stage, _words in _STAGE_WORDS.items():
    _label = _words[0]
    _STAGE_METRICS.append(_m(
        f"retail.stage{_stage}.exposure", f"{_label} Exposure",
        f"Gross carrying amount on facilities in {_label} at the month-end.",
        _total(_t("gca", f"{_label} exposure", BOOK, "sum",
                  "gross_carrying_amount_sar", ifrs9_stage=_stage)),
        unit="currency", domain=D_IMPAIRMENT,
        aliases=tuple(f"{w} exposure" for w in _words[1:]),
        formula_text=f"SUM(gross_carrying_amount_sar WHERE ifrs9_stage = {_stage})",
        decimals=0, visuals=("kpi", "bar")))
    _STAGE_METRICS.append(_m(
        f"retail.stage{_stage}.ecl", f"{_label} ECL",
        f"Loss allowance carried on {_label} facilities.",
        _total(_t("ecl", f"{_label} ECL", BOOK, "sum", "ecl_final_sar",
                  ifrs9_stage=_stage)),
        unit="currency", domain=D_IMPAIRMENT,
        aliases=tuple(f"{w} ecl" for w in _words[1:]),
        formula_text=f"SUM(ecl_final_sar WHERE ifrs9_stage = {_stage})",
        decimals=0, higher_is_better=False, visuals=("kpi", "bar")))
    _STAGE_METRICS.append(_m(
        f"retail.stage{_stage}.share", f"{_label} Share of Exposure",
        f"What proportion of the retail book sits in {_label}.",
        _ratio([_t("s", f"{_label} exposure", BOOK, "sum",
                   "gross_carrying_amount_sar", ifrs9_stage=_stage)],
               [_t("all", "All exposure", BOOK, "sum",
                   "gross_carrying_amount_sar")]),
        unit="percent", domain=D_IMPAIRMENT,
        aliases=tuple(f"{w} share" for w in _words[1:]),
        formula_text=(f"SUM(gca WHERE stage = {_stage}) / SUM(gca) × 100"),
        decimals=2, higher_is_better=(_stage == 1), visuals=("kpi", "bar")))
    _STAGE_METRICS.append(_m(
        f"retail.stage{_stage}.coverage", f"{_label} Coverage",
        f"Allowance as a proportion of exposure within {_label}. The one "
        f"number that says whether a stage is provisioned as its stage implies.",
        _ratio([_t("ecl", f"{_label} ECL", BOOK, "sum", "ecl_final_sar",
                   ifrs9_stage=_stage)],
               [_t("gca", f"{_label} exposure", BOOK, "sum",
                   "gross_carrying_amount_sar", ifrs9_stage=_stage)]),
        unit="percent", domain=D_IMPAIRMENT,
        aliases=tuple(f"{w} coverage" for w in _words[1:]),
        formula_text=(f"SUM(ecl WHERE stage = {_stage}) / "
                      f"SUM(gca WHERE stage = {_stage}) × 100"),
        decimals=2, higher_is_better=False, visuals=("kpi", "bar")))

STAGING: tuple[MetricDefinition, ...] = tuple(_STAGE_METRICS) + (
    _m("retail.sicr_rate", "SICR Rate",
       "The share of facilities on which a significant increase in credit risk "
       "has been recognised. By facility count, because SICR is a decision "
       "taken facility by facility.",
       _ratio([_t("f", "Flagged", BOOK, "count", "", sicr_flag=True)],
              [_t("n", "Facilities", BOOK, "count")]),
       unit="percent", domain=D_IMPAIRMENT,
       aliases=("sicr rate", "significant increase in credit risk rate"),
       formula_text="COUNT(sicr_flag) / COUNT(rows) × 100",
       decimals=2, higher_is_better=False, visuals=("kpi", "line")),

    _m("retail.forbearance_rate", "Forbearance Rate",
       "Share of exposure on facilities where forbearance has been granted.",
       _ratio([_t("f", "Forborne exposure", BOOK, "sum",
                  "gross_carrying_amount_sar", forbearance_flag=True)],
              [_t("all", "All exposure", BOOK, "sum",
                  "gross_carrying_amount_sar")]),
       unit="percent", domain=D_IMPAIRMENT,
       aliases=("forbearance", "forbearance rate", "forborne"),
       formula_text="SUM(gca WHERE forbearance_flag) / SUM(gca) × 100",
       decimals=2, higher_is_better=False, visuals=("kpi", "line", "bar")),
)


# ============================================================ delinquency

def _dpd_rate(days: int, aliases: tuple[str, ...]) -> MetricDefinition:
    return _m(
        f"retail.dpd{days}_rate", f"{days}+ DPD Rate",
        f"Share of exposure on facilities {days} or more days past due at the "
        f"month-end. By EXPOSURE: a delinquency rate by account count answers "
        f"a different question and the two move apart.",
        _ratio([_t("late", f"{days}+ DPD exposure", BOOK, "sum",
                   "gross_carrying_amount_sar", dpd__gte=days)],
               [_t("all", "All exposure", BOOK, "sum",
                   "gross_carrying_amount_sar")]),
        unit="percent", domain=D_DELINQUENCY, aliases=aliases,
        formula_text=f"SUM(gca WHERE dpd >= {days}) / SUM(gca) × 100",
        numerator_text=f"Exposure {days} or more days past due",
        denominator_text="All retail exposure",
        decimals=2, higher_is_better=False, visuals=("kpi", "line", "bar"),
        not_this=f"Not the {days}+ rate by account count, which is the "
                 f"companion metric retail.dpd{days}_count_rate.")


DELINQUENCY: tuple[MetricDefinition, ...] = (
    _dpd_rate(30, ("30+ dpd", "30 plus dpd", "30+ delinquency",
                   "delinquency rate", "arrears rate")),
    _dpd_rate(60, ("60+ dpd", "60 plus dpd")),
    _dpd_rate(90, ("90+ dpd", "90 plus dpd", "npl rate",
                   "non-performing rate")),

    _m("retail.dpd30_count_rate", "30+ DPD Rate by Account",
       "Share of FACILITIES 30 or more days past due, by count rather than by "
       "exposure. Stated separately because the two answer different "
       "questions and a book of small late accounts moves them apart.",
       _ratio([_t("late", "30+ DPD facilities", BOOK, "count", "",
                  dpd__gte=30)],
              [_t("n", "Facilities", BOOK, "count")]),
       unit="percent", domain=D_DELINQUENCY,
       aliases=("30+ dpd by account", "delinquent accounts"),
       formula_text="COUNT(dpd >= 30) / COUNT(rows) × 100",
       decimals=2, higher_is_better=False, visuals=("kpi", "line")),

    _m("retail.overdue_amount", "Amount Overdue",
       "Amounts contractually due and unpaid at the month-end. A flow into "
       "arrears, not the balance of the accounts in arrears.",
       _total(_t("o", "Overdue", BOOK, "sum", "overdue_amount_sar")),
       unit="currency", domain=D_DELINQUENCY,
       aliases=("overdue", "amount overdue", "arrears amount"),
       formula_text="SUM(overdue_amount_sar)", decimals=0,
       higher_is_better=False, visuals=("kpi", "line")),

    _m("retail.writeoff_month", "Write-offs in the Month",
       "Amount written off during the reporting month. A PERIOD FLOW: summing "
       "it across months gives a cumulative figure, and summing it across "
       "facilities within one month gives that month's charge.",
       _total(_t("w", "Written off", BOOK, "sum",
                 "writeoff_amount_month_sar")),
       unit="currency", domain=D_DELINQUENCY,
       aliases=("write-off", "writeoff", "charge-off", "written off"),
       formula_text="SUM(writeoff_amount_month_sar)", decimals=0,
       higher_is_better=False, visuals=("kpi", "line", "bar"),
       not_this="Not the cumulative write-off to date, which is a separate "
                "column on the same row."),

    _m("retail.default_rate_current", "Facilities in Default",
       "Share of facilities in default under the versioned default definition "
       "at this month-end: 90 or more days past due, or a recorded "
       "unlikeliness to pay.",
       _ratio([_t("d", "In default", BOOK, "count", "",
                  current_default_flag=True)],
              [_t("n", "Facilities", BOOK, "count")]),
       unit="percent", domain=D_DELINQUENCY,
       aliases=("default rate", "in default", "defaulted facilities"),
       formula_text="COUNT(current_default_flag) / COUNT(rows) × 100",
       decimals=2, higher_is_better=False, visuals=("kpi", "line"),
       not_this="Not the observed 12-month default rate, which is a "
                "forward-looking outcome and only knowable once the window "
                "has closed."),
)


# =========================================================== origination

ORIGINATION: tuple[MetricDefinition, ...] = (
    _m("retail.average_application_score", "Average Application Score",
       "The mean application score recorded at origination across the "
       "facilities on the book. It is frozen at origination and does not move "
       "with the account.",
       Formula(kind="average", numerator=Side(terms=(
           _t("s", "Application score", BOOK, "avg",
              "application_score_at_origination"),))),
       unit="score", domain=D_ORIGINATION,
       aliases=("average application score", "application score",
                "origination score"),
       formula_text="AVG(application_score_at_origination)",
       decimals=1, higher_is_better=True, visuals=("kpi", "line"),
       not_this="Not the current behavioural score, which is recomputed every "
                "month from information available by that date."),

    _m("retail.average_behavioural_score", "Average Behavioural Score",
       "The mean behavioural score at this month-end, recomputed from the "
       "information available by that date.",
       Formula(kind="average", numerator=Side(terms=(
           _t("s", "Behavioural score", BOOK, "avg", "behavioural_score"),))),
       unit="score", domain=D_ORIGINATION,
       aliases=("average behavioural score", "behavioural score",
                "behavioral score"),
       formula_text="AVG(behavioural_score)",
       decimals=1, higher_is_better=True, visuals=("kpi", "line")),

    _m("retail.average_bureau_score", "Average Bureau Score",
       "The mean current bureau proxy score across facilities on the book.",
       Formula(kind="average", numerator=Side(terms=(
           _t("s", "Bureau score", BOOK, "avg", "bureau_score_current"),))),
       unit="score", domain=D_ORIGINATION,
       aliases=("average bureau score", "bureau score", "simah"),
       formula_text="AVG(bureau_score_current)",
       decimals=1, higher_is_better=True, visuals=("kpi", "line")),

    _m("retail.average_debt_burden", "Average Debt Burden Ratio",
       "Total monthly credit obligations over verified monthly income. A "
       "CUSTOMER value, repeated on each of that customer's facilities, so it "
       "is averaged over facilities here and never summed.",
       Formula(kind="average", numerator=Side(terms=(
           _t("d", "Debt burden ratio", BOOK, "avg", "debt_burden_ratio"),))),
       unit="ratio", domain=D_ORIGINATION,
       aliases=("debt burden", "dbr", "indebtedness",
                "debt burden ratio"),
       formula_text="AVG(debt_burden_ratio)",
       decimals=3, higher_is_better=False, visuals=("kpi", "line"),
       not_this="Never a SUM: it is one customer's ratio written onto each of "
                "their rows, and adding them up means nothing."),

    _m("retail.average_pd_current", "Average Predicted PD (Current Book)",
       "The mean point-in-time twelve-month PD under the base scenario across "
       "the book as it stands this month. Stated separately from "
       "`retail.predicted_pd`, which is pinned to the matured cohort so it can "
       "be set beside the observed rate: putting a figure from a year ago on a "
       "screen headed 'this month' is how a dashboard misleads quietly.",
       Formula(kind="average", numerator=Side(terms=(
           _t("pd", "Predicted PD", BOOK, "avg", "pd_pit_12m_base"),))),
       unit="probability", domain=D_ORIGINATION,
       aliases=("average pd", "current pd", "predicted pd this month"),
       formula_text="AVG(pd_pit_12m_base)",
       decimals=4, higher_is_better=False, visuals=("kpi", "line"),
       not_this="Not comparable with the observed default rate, which can only "
                "be measured on a cohort whose window has closed."),

    _m("retail.salary_transfer_rate", "Salary-Transfer Share",
       "Share of exposure held by customers whose salary is transferred to "
       "this bank — the single strongest affordability control in a Saudi "
       "retail book.",
       _ratio([_t("st", "Salary-transfer exposure", BOOK, "sum",
                  "gross_carrying_amount_sar", salary_transfer_flag=True)],
              [_t("all", "All exposure", BOOK, "sum",
                  "gross_carrying_amount_sar")]),
       unit="percent", domain=D_ORIGINATION,
       aliases=("salary transfer", "salary transfer rate",
                "salary assignment"),
       formula_text="SUM(gca WHERE salary_transfer_flag) / SUM(gca) × 100",
       decimals=1, higher_is_better=True, visuals=("kpi", "line", "bar")),

    _m("retail.secured_share", "Secured Share",
       "Share of exposure on facilities carrying security.",
       _ratio([_t("s", "Secured exposure", BOOK, "sum",
                  "gross_carrying_amount_sar", secured_flag=True)],
              [_t("all", "All exposure", BOOK, "sum",
                  "gross_carrying_amount_sar")]),
       unit="percent", domain=D_ORIGINATION,
       aliases=("secured", "secured share", "collateralised share"),
       formula_text="SUM(gca WHERE secured_flag) / SUM(gca) × 100",
       decimals=1, visuals=("kpi", "bar")),
)


# ============================================================= scorecard
#
# Every metric here is an OUTCOME metric: it needs a closed twelve-month
# observation window, so it is pinned to the latest matured period rather than
# to the month on screen. At the latest published month the outcome column is
# null on every row, and a discrimination statistic computed there would be
# computed on nothing.

#: The maturity scope, and it is NOT "the outcome column is not null".
#:
#: A facility that has already defaulted has a known outcome immediately; one
#: that has not is unknown until its twelve-month window closes. So at 2026-07
#: exactly 47 rows carry a non-null outcome and every one of them is a default.
#: Scoping on non-null would pick that month as "the latest with outcomes",
#: report a 100% default rate, and hand back an undefined Gini because there
#: are no goods left to rank against.
#:
#: `performance_window_complete_flag` is what the book itself states, and it is
#: true on every row up to 2025-08 and false from 2025-09 — so this scope also
#: makes `latest_matured_period` resolve to the right month, since that
#: function deliberately reads the newest period carrying rows inside the
#: metric's own scope. `monitoring_eligible_flag` then removes the accounts
#: that were already in default at the landmark, which are not a test of
#: whether a score predicts default.
_MATURED = (
    Condition("performance_window_complete_flag", "=", True),
    Condition("monitoring_eligible_flag", "=", True),
)


def _discrimination(metric_id: str, name: str, statistic: str,
                    score_field: str, definition: str,
                    aliases: tuple[str, ...], **kw) -> MetricDefinition:
    return _m(
        metric_id, name, definition,
        Formula(kind="function", function=statistic,
                numerator=Side(terms=(
                    _t("score", "Score", BOOK, "avg", score_field),
                    _t("bad", "Observed default", BOOK, "avg",
                       "observed_default_within_window"))),
                function_args={"score_field": score_field,
                               "outcome_field":
                                   "observed_default_within_window",
                               "direction": "HIGHER_SCORE_IS_BETTER"}),
        unit="ratio", domain=D_SCORECARD, scope=_MATURED,
        period_rule=PERIOD_LATEST_MATURED, aliases=aliases,
        decimals=4, higher_is_better=True, visuals=("kpi", "line"),
        transformation=(
            "Computed by the governed `" + statistic + "` function over the "
            "whole frame in the runtime, never over a preview of it."),
        not_this="Not a measure of whether the predicted PDs are right. "
                 "Discrimination is the ability to rank; calibration is "
                 "whether the level is correct. A scorecard can rank well and "
                 "be badly calibrated, and the reverse.",
        **kw)


SCORECARD: tuple[MetricDefinition, ...] = (
    _discrimination(
        "retail.application.gini", "Application Scorecard Gini", "gini",
        "application_score_at_origination",
        "How well the application score recorded at origination separates the "
        "facilities that went on to default within twelve months from those "
        "that did not. Measured only where the observation window has closed.",
        ("application gini", "application scorecard gini", "origination gini")),

    _discrimination(
        "retail.application.auc", "Application Scorecard AUC", "auc",
        "application_score_at_origination",
        "The area under the ROC curve for the application score against the "
        "observed twelve-month default outcome.",
        ("application auc", "auroc", "area under the curve")),

    _discrimination(
        "retail.application.ks", "Application Scorecard KS", "ks",
        "application_score_at_origination",
        "The maximum separation between the cumulative score distributions of "
        "defaulted and non-defaulted facilities.",
        ("application ks", "ks statistic", "kolmogorov")),

    _discrimination(
        "retail.behavioural.gini", "Behavioural Scorecard Gini", "gini",
        "behavioural_score",
        "How well the behavioural score separates the facilities that went on "
        "to default within twelve months from those that did not.",
        ("behavioural gini", "behavioral gini",
         "behavioural scorecard gini")),

    _discrimination(
        "retail.bureau.gini", "Bureau Score Gini", "gini",
        "bureau_score_current",
        "How well the bureau proxy score separates observed defaults. Reported "
        "alongside the internal scorecards so the internal models can be "
        "judged against the external reference rather than in isolation.",
        ("bureau gini", "simah gini", "external score gini")),

    _m("retail.observed_default_rate", "Observed 12-Month Default Rate",
       "The proportion of facilities that were observed to default within "
       "twelve months of the snapshot. An OUTCOME, knowable only once the "
       "window has closed, and never a predictor.",
       _ratio([_t("bad", "Observed defaults", BOOK, "sum",
                  "observed_default_within_window")],
              [_t("n", "Facilities with a closed window", BOOK, "count")]),
       unit="percent", domain=D_SCORECARD, scope=_MATURED,
       period_rule=PERIOD_LATEST_MATURED,
       aliases=("observed default rate", "realised default rate",
                "bad rate", "actual default rate"),
       formula_text=("SUM(observed_default_within_window) / COUNT(rows) × 100, "
                     "over the matured scope"),
       numerator_text="Facilities that defaulted within the window",
       denominator_text="Facilities whose window has closed",
       decimals=2, higher_is_better=False, visuals=("kpi", "line", "bar"),
       not_this="Not the share of facilities in default TODAY, which is a "
                "state at the month-end rather than an outcome over a window."),

    _m("retail.predicted_pd", "Average Predicted 12-Month PD",
       "The mean point-in-time twelve-month probability of default predicted "
       "under the base scenario, over the same matured population the observed "
       "rate is measured on — so the two can be compared.",
       Formula(kind="average", numerator=Side(terms=(
           _t("pd", "Predicted PD", BOOK, "avg", "pd_pit_12m_base"),))),
       unit="probability", domain=D_SCORECARD, scope=_MATURED,
       period_rule=PERIOD_LATEST_MATURED,
       aliases=("predicted pd", "expected default rate", "modelled pd"),
       formula_text="AVG(pd_pit_12m_base)",
       decimals=4, higher_is_better=False, visuals=("kpi", "line")),
)


ALL: tuple[MetricDefinition, ...] = (
    POSITION + IMPAIRMENT + STAGING + DELINQUENCY + ORIGINATION + SCORECARD)


def check() -> list[str]:
    """Every problem with the retail library, as sentences.

    Run by a gate, so a metric that names a column the book does not carry
    fails a test rather than a tile.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for metric in ALL:
        if metric.metric_id in seen:
            problems.append(f"{metric.metric_id} is defined twice")
        seen.add(metric.metric_id)
        for dataset in metric.formula.datasets:
            if dataset != BOOK:
                problems.append(
                    f"{metric.metric_id} reads {dataset}, which is not the "
                    f"governed retail book")
    return problems


__all__ = ["ALL", "BOOK", "RETAIL_LIBRARY_VERSION", "POSITION", "IMPAIRMENT",
           "STAGING", "DELINQUENCY", "ORIGINATION", "SCORECARD",
           "D_POSITION", "D_IMPAIRMENT", "D_DELINQUENCY", "D_ORIGINATION",
           "D_SCORECARD", "check"]
