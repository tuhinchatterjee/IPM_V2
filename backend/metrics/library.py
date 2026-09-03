"""The governed metrics, written down once.

Every entry here is calculable against a dataset this deployment actually has.
Where a metric a retail risk lens would normally carry is NOT calculable — and
several are, because there is no retail impairment dataset in this
deployment — it appears as an `Unsupported` entry naming what is missing,
rather than as a tile with a dash in it.

Three domains:

* **Retail** — built on the retail behavioural and application scorecard
  datasets, which are account-level and application-level, monthly, and carry
  balance, limit, utilisation, days past due, default outcome, bureau score
  and model score. That is enough for portfolio, delinquency, risk quality and
  scorecard validation, and not enough for retail IFRS 9.
* **Corporate IFRS 9** — built on the impairment staging dataset and the
  facility position, quarterly.
* **Corporate portfolio** — the credit book the CRO lens already reads.

The numbers below were reconciled against the raw parquet with an independent
query before being written down. Where a definition is one a bank might state
differently — 90+ DPD by count or by balance, for instance — both exist, and
each says which it is in its name.
"""

from __future__ import annotations

from backend.metrics.catalogue import (
    PERIOD_LATEST_MATURED,
    PERIOD_SELECTED,
    STATUS_PUBLISHED,
    MetricDefinition,
    Unsupported,
    _ratio,
    _t,
    _total,
)
from backend.metrics.formula import Condition, Formula, Side, Term

LIBRARY_VERSION = "1.0.0"

RETAIL = "Retail Credit Risk"
RETAIL_ANALYTICS = "Retail Analytics"
CORPORATE_IFRS9 = "Corporate IFRS 9"
CORPORATE = "Corporate Portfolio"

BEHAVIOURAL = "retail_behavioral_scorecard_monthly_validation"
APPLICATIONS = "retail_application_scorecard_monthly_validation"
FACILITIES = "portfolio_facility"
STAGING = "ifrs9_staging"
DELINQUENCY = "facility_delinquency"


def _m(metric_id: str, name: str, definition: str, formula, **kw
       ) -> MetricDefinition:
    kw.setdefault("period_rule", PERIOD_SELECTED)
    kw.setdefault("status", STATUS_PUBLISHED)
    return MetricDefinition(metric_id=metric_id, name=name,
                            definition=definition, formula=formula, **kw)


# ===================================================== retail — portfolio

RETAIL_PORTFOLIO: tuple[MetricDefinition, ...] = (
    _m("retail.balance", "Retail Outstanding Balance",
       "The total current balance across every open retail account in the "
       "month.",
       _total(_t("bal", "Current balance", BEHAVIOURAL, "sum",
                 "current_balance")),
       unit="currency", domain=RETAIL, portfolio="Retail",
       aliases=("retail exposure", "outstanding balance", "retail book",
                "balance"),
       formula_text="SUM(current_balance)",
       numerator_text="Current balance on every account in the month",
       visuals=("kpi", "line", "bar"), decimals=0,
       transformation="One row per account per observation month; no "
                      "deduplication is required at that grain.",
       not_this="Not exposure at default: it carries no undrawn limit and no "
                "credit conversion factor."),

    _m("retail.accounts", "Retail Accounts",
       "How many retail accounts are in the book in the month.",
       Formula(kind="count", numerator=Side(terms=(
           Term(id="n", label="Accounts", dataset=BEHAVIOURAL,
                aggregate="count"),))),
       unit="count", domain=RETAIL, portfolio="Retail",
       aliases=("accounts", "number of accounts", "account count"),
       formula_text="COUNT(rows)", visuals=("kpi", "line", "bar"), decimals=0),

    _m("retail.average_balance", "Average Retail Balance",
       "The mean current balance per account.",
       Formula(kind="average", numerator=Side(terms=(
           _t("avg", "Average balance", BEHAVIOURAL, "avg",
              "current_balance"),))),
       unit="currency", domain=RETAIL, portfolio="Retail",
       aliases=("average balance", "mean balance"),
       formula_text="AVG(current_balance)", decimals=0,
       not_this="Not a median. A small number of very large balances move it."),

    _m("retail.credit_limit", "Retail Credit Limit",
       "The total approved credit limit across the retail book.",
       _total(_t("lim", "Credit limit", BEHAVIOURAL, "sum", "credit_limit")),
       unit="currency", domain=RETAIL, portfolio="Retail",
       aliases=("limit", "approved limit", "credit limit"),
       formula_text="SUM(credit_limit)", decimals=0),

    _m("retail.utilisation", "Retail Utilisation",
       "Balance drawn as a share of the approved limit, across the book.",
       _ratio([_t("bal", "Balance", BEHAVIOURAL, "sum", "current_balance")],
              [_t("lim", "Credit limit", BEHAVIOURAL, "sum", "credit_limit")]),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("utilisation", "utilization", "drawn percentage"),
       formula_text="SUM(current_balance) / SUM(credit_limit) × 100",
       numerator_text="Current balance",
       denominator_text="Approved credit limit",
       visuals=("kpi", "line"), higher_is_better=None,
       not_this="A book-level ratio, not the average of each account's "
                "utilisation — those differ whenever balances differ in size."),
)


# =================================================== retail — delinquency

def _dpd_rate(bucket: int, by: str) -> MetricDefinition:
    """One delinquency rate. Two versions of each, and each says which.

    By count and by balance answer different questions — "how many customers
    are behind" and "how much money is behind" — and a dashboard that shows
    one labelled simply "90+ DPD" is a dashboard two people will read two ways.
    """
    if by == "count":
        top = [_t("late", f"{bucket}+ DPD accounts", BEHAVIOURAL, "count",
                  "current_dpd", current_dpd__gte=bucket)]
        bottom = [Term(id="all", label="All accounts", dataset=BEHAVIOURAL,
                       aggregate="count")]
        text = (f"COUNT(accounts where current_dpd >= {bucket}) / "
                "COUNT(accounts) × 100")
        name = f"{bucket}+ DPD Account Rate"
        alias = (f"{bucket}+ dpd", f"{bucket} plus dpd",
                 f"{bucket}+ dpd accounts", f"{bucket} dpd rate",
                 f"{bucket} day delinquency", f"delinquency {bucket} accounts")
    else:
        top = [_t("late", f"{bucket}+ DPD balance", BEHAVIOURAL, "sum",
                  "current_balance", current_dpd__gte=bucket)]
        bottom = [_t("all", "Total balance", BEHAVIOURAL, "sum",
                     "current_balance")]
        text = (f"SUM(current_balance where current_dpd >= {bucket}) / "
                "SUM(current_balance) × 100")
        name = f"{bucket}+ DPD Exposure Rate"
        alias = (f"{bucket}+ dpd exposure", f"{bucket}+ dpd balance",
                 f"delinquent balance {bucket}",
                 f"{bucket} day delinquency", f"delinquency {bucket} exposure")
    return _m(f"retail.dpd_{bucket}_{by}", name,
              f"The share of the retail book {bucket} or more days past due, "
              f"measured by {'account count' if by == 'count' else 'balance'}.",
              _ratio(top, bottom),
              unit="percent", domain=RETAIL, portfolio="Retail",
              aliases=alias, formula_text=text,
              numerator_text=f"Accounts at {bucket}+ days past due"
              if by == "count" else f"Balance on accounts at {bucket}+ DPD",
              denominator_text="All accounts in the month" if by == "count"
              else "Total current balance",
              visuals=("kpi", "line", "bar"), higher_is_better=False,
              transformation="Days past due is the account's status at the "
                             "observation month; it is not a maximum over a "
                             "window.",
              not_this="Not a roll rate. This is a level at a point in time, "
                       "not a movement between two.")


RETAIL_DELINQUENCY: tuple[MetricDefinition, ...] = tuple(
    _dpd_rate(bucket, by)
    for bucket in (1, 30, 60, 90)
    for by in ("count", "balance")
) + (
    _m("retail.delinquent_balance", "Delinquent Retail Balance",
       "The balance on retail accounts that are behind at all.",
       _total(_t("late", "Balance 1+ DPD", BEHAVIOURAL, "sum",
                 "current_balance", current_dpd__gte=1)),
       unit="currency", domain=RETAIL, portfolio="Retail",
       aliases=("delinquent balance", "arrears balance", "balance in arrears"),
       formula_text="SUM(current_balance where current_dpd >= 1)",
       decimals=0, higher_is_better=False),

    _m("retail.default_rate", "Retail Default Rate",
       "The share of accounts that defaulted over the performance window "
       "recorded for the cohort.",
       _ratio([_t("bad", "Defaulted accounts", BEHAVIOURAL, "count",
                  "actual_default", actual_default=1)],
              [Term(id="all", label="Accounts", dataset=BEHAVIOURAL,
                    aggregate="count")]),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("default rate", "bad rate", "npl rate", "observed bad rate"),
       formula_text="COUNT(actual_default = 1) / COUNT(accounts) × 100",
       numerator_text="Accounts flagged as defaulted",
       denominator_text="All accounts observed",
       visuals=("kpi", "line", "bar"), higher_is_better=False,
       period_rule=PERIOD_SELECTED,
       transformation="The default flag is the outcome over the performance "
                      "horizon recorded on the row, not a status at the "
                      "observation month.",
       exclusions="Rows whose performance window has not matured carry no "
                  "outcome and are still counted in the denominator, which "
                  "understates the rate on the most recent months.",
       not_this="Not a 90+ DPD rate. A default is the recorded outcome over "
                "the performance window; DPD is a state today."),

    _m("retail.restructured_rate", "Restructured Account Rate",
       "The share of accounts carrying a restructure flag.",
       _ratio([_t("r", "Restructured", BEHAVIOURAL, "count",
                  "restructure_flag", restructure_flag=1)],
              [Term(id="all", label="Accounts", dataset=BEHAVIOURAL,
                    aggregate="count")]),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("restructured", "forbearance rate", "restructure rate"),
       formula_text="COUNT(restructure_flag = 1) / COUNT(accounts) × 100",
       higher_is_better=False),

    _m("retail.missed_payments", "Accounts With A Missed Payment (6m)",
       "The share of accounts with at least one missed payment in the last "
       "six months.",
       _ratio([_t("m", "Missed at least once", BEHAVIOURAL, "count",
                  "missed_payment_count_6m", missed_payment_count_6m__gte=1)],
              [Term(id="all", label="Accounts", dataset=BEHAVIOURAL,
                    aggregate="count")]),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("missed payments", "payment misses"),
       formula_text="COUNT(missed_payment_count_6m >= 1) / COUNT(accounts) × 100",
       higher_is_better=False),
)


# ================================================= retail — risk quality

RETAIL_QUALITY: tuple[MetricDefinition, ...] = (
    _m("retail.average_score", "Average Behavioural Score",
       "The mean behavioural score across the book.",
       Formula(kind="average", numerator=Side(terms=(
           _t("s", "Behavioural score", BEHAVIOURAL, "avg",
              "score_incumbent"),))),
       unit="score", domain=RETAIL, portfolio="Retail",
       aliases=("average score", "mean score", "behavioural score"),
       formula_text="AVG(score_incumbent)", decimals=1,
       higher_is_better=True,
       not_this="The score in production, not the redeveloped challenger."),

    _m("retail.average_bureau_score", "Average Bureau Score",
       "The mean latest bureau score across the book.",
       Formula(kind="average", numerator=Side(terms=(
           _t("s", "Bureau score", BEHAVIOURAL, "avg",
              "bureau_score_latest"),))),
       unit="score", domain=RETAIL, portfolio="Retail",
       aliases=("bureau score", "average bureau score"),
       formula_text="AVG(bureau_score_latest)", decimals=1,
       higher_is_better=True),

    _m("retail.average_pd", "Average Predicted PD",
       "The mean probability of default the production model assigns.",
       Formula(kind="average", numerator=Side(terms=(
           _t("pd", "Predicted PD", BEHAVIOURAL, "avg", "pd_incumbent"),))),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("average pd", "predicted pd", "model pd"),
       formula_text="AVG(pd_incumbent) × 100", decimals=2,
       higher_is_better=False,
       not_this="An unweighted mean across accounts, not an exposure-weighted "
                "portfolio PD."),

    _m("retail.high_utilisation_rate", "Accounts Above 90% Utilised",
       "The share of accounts drawn above ninety per cent of their limit.",
       _ratio([_t("hi", "Above 90% utilised", BEHAVIOURAL, "count",
                  "utilisation_pct", utilisation_pct__gte=90)],
              [Term(id="all", label="Accounts", dataset=BEHAVIOURAL,
                    aggregate="count")]),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("high utilisation", "overlimit risk", "near limit"),
       formula_text="COUNT(utilisation_pct >= 90) / COUNT(accounts) × 100",
       higher_is_better=False),
)


# ============================================= retail — scorecard validation

RETAIL_VALIDATION: tuple[MetricDefinition, ...] = (
    _m("retail.scorecard.gini", "Scorecard Gini",
       "How well the production behavioural score separates the accounts that "
       "defaulted from those that did not, over the observed window.",
       Formula(kind="function", function="gini",
               numerator=Side(terms=(
                   _t("score", "Score", BEHAVIOURAL, "avg", "score_incumbent"),
                   _t("bad", "Default outcome", BEHAVIOURAL, "avg",
                      "actual_default"))),
               function_args={"score_field": "score_incumbent",
                              "outcome_field": "actual_default",
                              "direction": "HIGHER_SCORE_IS_BETTER"}),
       unit="ratio", domain=RETAIL, portfolio="Retail",
       scope=(Condition("matured_flag", "=", True),),
       period_rule=PERIOD_LATEST_MATURED,
       aliases=("gini", "gini coefficient", "discriminatory power", "auroc",
                "accuracy ratio"),
       formula_text="Gini = 2 × AUROC − 1, over (score_incumbent, "
                    "actual_default)",
       numerator_text="Ranked by score; outcome is the recorded default flag",
       denominator_text="",
       decimals=4, higher_is_better=True,
       visuals=("kpi", "line"),
       transformation="Computed by the governed `gini` function over the "
                      "rows in scope, ranking on the score and reading the "
                      "outcome. It is not a ratio of two sums, and is not "
                      "presented as one.",
       exclusions="Rows whose performance window has not matured carry no "
                  "outcome and are excluded from the calculation.",
       not_this="Not a measure of calibration. A scorecard can rank perfectly "
                "and still predict the wrong level."),

    _m("retail.scorecard.ks", "Scorecard KS",
       "The largest gap between the cumulative distributions of defaulted and "
       "non-defaulted accounts across the score range.",
       Formula(kind="function", function="ks",
               numerator=Side(terms=(
                   _t("score", "Score", BEHAVIOURAL, "avg", "score_incumbent"),
                   _t("bad", "Default outcome", BEHAVIOURAL, "avg",
                      "actual_default"))),
               function_args={"score_field": "score_incumbent",
                              "outcome_field": "actual_default",
                              "direction": "HIGHER_SCORE_IS_BETTER"}),
       unit="ratio", domain=RETAIL, portfolio="Retail",
       scope=(Condition("matured_flag", "=", True),),
       period_rule=PERIOD_LATEST_MATURED,
       aliases=("ks", "ks statistic", "kolmogorov smirnov", "separation"),
       formula_text="KS = max |F_bad(s) − F_good(s)|",
       decimals=4, higher_is_better=True,
       not_this="Not comparable across score scales with different ranges."),

    _m("retail.scorecard.calibration", "Predicted Versus Observed Default",
       "The production model's average predicted probability of default "
       "against the default rate actually observed.",
       _ratio([_t("pred", "Average predicted PD", BEHAVIOURAL, "avg",
                  "pd_incumbent")],
              [_t("obs", "Observed default rate", BEHAVIOURAL, "avg",
                  "actual_default")], scale=1.0, kind="ratio"),
       unit="ratio", domain=RETAIL, portfolio="Retail",
       scope=(Condition("matured_flag", "=", True),),
       period_rule=PERIOD_LATEST_MATURED,
       aliases=("calibration", "predicted versus observed",
                "calibration ratio", "observed versus expected"),
       formula_text="AVG(pd_incumbent) / AVG(actual_default)",
       numerator_text="What the model predicted, on average",
       denominator_text="What actually happened, on average",
       decimals=3, higher_is_better=None,
       transformation="A ratio of one, exactly, is a perfectly calibrated "
                      "model. Above one is conservative; below one "
                      "under-predicts.",
       not_this="Not discriminatory power. Calibration says whether the level "
                "is right, not whether the ranking is."),

    _m("retail.scorecard.matured", "Matured Performance Rows",
       "How many rows have a performance window that has run its course, and "
       "therefore carry a usable outcome.",
       Formula(kind="count", numerator=Side(terms=(
           Term(id="m", label="Matured rows", dataset=BEHAVIOURAL,
                aggregate="count"),))),
       unit="count", domain=RETAIL, portfolio="Retail",
       # The maturity condition is the metric's scope rather than a filter on
       # its one term, so that it is the same restriction the discrimination
       # metrics carry — and so "the latest period" means the latest period
       # this metric has rows in. Asked for the newest month in the lake it
       # would answer nothing, correctly and uselessly: those accounts have
       # not had time to mature, which is the whole reason the rule exists.
       scope=(Condition("matured_flag", "=", True),),
       period_rule=PERIOD_LATEST_MATURED,
       aliases=("matured", "usable outcomes", "performance window complete"),
       formula_text="COUNT(matured_flag = 1)", decimals=0,
       not_this="Not a performance metric. It is the sample size behind "
                "every other one on this panel, and a validation read on a "
                "small one should be read carefully."),
)


# ================================================= retail — analytics

RETAIL_ORIGINATION: tuple[MetricDefinition, ...] = (
    _m("retail.applications", "Retail Applications",
       "How many retail credit applications were received in the month.",
       Formula(kind="count", numerator=Side(terms=(
           Term(id="n", label="Applications", dataset=APPLICATIONS,
                aggregate="count"),))),
       unit="count", domain=RETAIL_ANALYTICS, portfolio="Retail",
       aliases=("applications", "application volume", "originations"),
       formula_text="COUNT(applications)", decimals=0,
       visuals=("kpi", "line", "bar")),

    _m("retail.requested_amount", "Requested Amount",
       "The total amount applied for in the month.",
       _total(_t("amt", "Requested amount", APPLICATIONS, "sum",
                 "requested_amount")),
       unit="currency", domain=RETAIL_ANALYTICS, portfolio="Retail",
       aliases=("requested amount", "applied amount", "demand"),
       formula_text="SUM(requested_amount)", decimals=0),

    _m("retail.average_ticket", "Average Requested Ticket",
       "The mean amount applied for.",
       Formula(kind="average", numerator=Side(terms=(
           _t("t", "Average ticket", APPLICATIONS, "avg",
              "requested_amount"),))),
       unit="currency", domain=RETAIL_ANALYTICS, portfolio="Retail",
       aliases=("average ticket", "ticket size", "average loan size"),
       formula_text="AVG(requested_amount)", decimals=0),

    _m("retail.application_bad_rate", "Application Cohort Bad Rate",
       "The share of applications in the month that went on to default over "
       "the performance window.",
       _ratio([_t("bad", "Defaulted", APPLICATIONS, "count", "actual_default",
                  actual_default=1)],
              [Term(id="all", label="Applications", dataset=APPLICATIONS,
                    aggregate="count")]),
       unit="percent", domain=RETAIL_ANALYTICS, portfolio="Retail",
       aliases=("application bad rate", "cohort bad rate", "vintage bad rate"),
       formula_text="COUNT(actual_default = 1) / COUNT(applications) × 100",
       higher_is_better=False,
       transformation="Grouped by application month, which is what makes it "
                      "a vintage rather than a snapshot.",
       exclusions="Immature cohorts understate the rate, because their "
                  "performance window has not finished."),

    _m("retail.average_loan_to_income", "Average Loan To Income",
       "The mean ratio of the amount applied for to the applicant's income.",
       Formula(kind="average", numerator=Side(terms=(
           _t("lti", "Loan to income", APPLICATIONS, "avg",
              "loan_to_income"),))),
       unit="ratio", domain=RETAIL_ANALYTICS, portfolio="Retail",
       aliases=("loan to income", "lti", "leverage"),
       formula_text="AVG(loan_to_income)", decimals=2,
       higher_is_better=False),

    _m("retail.average_debt_burden", "Average Debt Burden Ratio",
       "The mean share of income already committed to debt service.",
       Formula(kind="average", numerator=Side(terms=(
           _t("dbr", "Debt burden ratio", APPLICATIONS, "avg",
              "debt_burden_ratio"),))),
       unit="percent", domain=RETAIL_ANALYTICS, portfolio="Retail",
       aliases=("debt burden", "dbr", "debt service ratio"),
       formula_text="AVG(debt_burden_ratio)", decimals=1,
       higher_is_better=False),

    _m("retail.salary_transfer_rate", "Salary Transfer Rate",
       "The share of applications from customers whose salary is credited to "
       "the bank.",
       _ratio([_t("st", "Salary transfer", APPLICATIONS, "count",
                  "salary_transfer_flag", salary_transfer_flag=1)],
              [Term(id="all", label="Applications", dataset=APPLICATIONS,
                    aggregate="count")]),
       unit="percent", domain=RETAIL_ANALYTICS, portfolio="Retail",
       aliases=("salary transfer", "salary assignment"),
       formula_text="COUNT(salary_transfer_flag = 1) / COUNT(applications) × 100",
       higher_is_better=True),

    _m("retail.application_gini", "Application Scorecard Gini",
       "How well the production application score separates the applications "
       "that went on to default.",
       Formula(kind="function", function="gini",
               numerator=Side(terms=(
                   _t("score", "Score", APPLICATIONS, "avg",
                      "score_incumbent"),
                   _t("bad", "Default outcome", APPLICATIONS, "avg",
                      "actual_default"))),
               function_args={"score_field": "score_incumbent",
                              "outcome_field": "actual_default",
                              "direction": "HIGHER_SCORE_IS_BETTER"}),
       unit="ratio", domain=RETAIL_ANALYTICS, portfolio="Retail",
       scope=(Condition("matured_flag", "=", True),),
       period_rule=PERIOD_LATEST_MATURED,
       aliases=("application gini", "origination gini"),
       formula_text="Gini = 2 × AUROC − 1, over (score_incumbent, "
                    "actual_default)",
       decimals=4, higher_is_better=True),
)


# ================================================ corporate IFRS 9

def _stage_exposure(stage: int) -> MetricDefinition:
    return _m(f"corporate.ifrs9.stage{stage}_ead", f"Stage {stage} Exposure",
              f"Exposure at default carried in Stage {stage}.",
              _total(_t("e", f"Stage {stage} EAD", STAGING, "sum", "ead",
                        ifrs9_stage=stage)),
              unit="currency", domain=CORPORATE_IFRS9, portfolio="Corporate",
              aliases=(f"stage {stage} exposure", f"stage {stage} ead",
                       f"stage{stage} ead"),
              formula_text=f"SUM(ead where ifrs9_stage = {stage})",
              decimals=0, visuals=("kpi", "bar", "line"))


def _stage_share(stage: int) -> MetricDefinition:
    return _m(f"corporate.ifrs9.stage{stage}_share", f"Stage {stage} Ratio",
              f"Stage {stage} exposure as a share of total exposure.",
              _ratio([_t("s", f"Stage {stage} EAD", STAGING, "sum", "ead",
                         ifrs9_stage=stage)],
                     [_t("all", "Total EAD", STAGING, "sum", "ead")]),
              unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
              aliases=(f"stage {stage} ratio", f"stage {stage} %",
                       f"stage {stage} share", f"stage {stage} percentage",
                       # "IFRS 9 staging" and "the staging profile" are what
                       # people ask for when they mean these three shares.
                       f"ifrs 9 staging stage {stage}",
                       f"staging profile stage {stage}"),
              formula_text=(f"SUM(ead where ifrs9_stage = {stage}) / "
                            "SUM(ead) × 100"),
              numerator_text=f"Exposure at default in Stage {stage}",
              denominator_text="Total exposure at default across all stages",
              higher_is_better=False if stage > 1 else True,
              visuals=("kpi", "line", "stacked_bar"))


def _stage_ecl(stage: int) -> MetricDefinition:
    return _m(f"corporate.ifrs9.stage{stage}_ecl", f"Stage {stage} ECL",
              f"Expected credit loss carried in Stage {stage}.",
              _total(_t("e", f"Stage {stage} ECL", STAGING, "sum", "total_ecl",
                        ifrs9_stage=stage)),
              unit="currency", domain=CORPORATE_IFRS9, portfolio="Corporate",
              aliases=(f"stage {stage} ecl", f"stage {stage} provision"),
              formula_text=f"SUM(total_ecl where ifrs9_stage = {stage})",
              decimals=0)


def _stage_coverage(stage: int) -> MetricDefinition:
    return _m(f"corporate.ifrs9.stage{stage}_coverage",
              f"Stage {stage} ECL Coverage",
              f"Expected credit loss as a share of exposure, within Stage "
              f"{stage}.",
              _ratio([_t("ecl", f"Stage {stage} ECL", STAGING, "sum",
                         "total_ecl", ifrs9_stage=stage)],
                     [_t("ead", f"Stage {stage} EAD", STAGING, "sum", "ead",
                         ifrs9_stage=stage)]),
              unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
              aliases=(f"stage {stage} coverage", f"coverage stage {stage}"),
              formula_text=(f"SUM(total_ecl where stage = {stage}) / "
                            f"SUM(ead where stage = {stage}) × 100"),
              decimals=2, higher_is_better=False)


CORPORATE_IFRS9_METRICS: tuple[MetricDefinition, ...] = tuple(
    fn(stage) for stage in (1, 2, 3)
    for fn in (_stage_exposure, _stage_share, _stage_ecl, _stage_coverage)
) + (
    _m("corporate.ifrs9.total_ead", "Total Exposure At Default",
       "Exposure at default across the corporate book.",
       _total(_t("ead", "EAD", STAGING, "sum", "ead")),
       unit="currency", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("total ead", "exposure at default", "total exposure", "ead"),
       formula_text="SUM(ead)", decimals=0),

    _m("corporate.ifrs9.total_ecl", "Total ECL",
       "Expected credit loss across the corporate book.",
       _total(_t("ecl", "ECL", STAGING, "sum", "total_ecl")),
       unit="currency", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("total ecl", "ecl", "provision", "impairment"),
       formula_text="SUM(total_ecl)", decimals=0,
       visuals=("kpi", "line", "bar")),

    _m("corporate.ifrs9.coverage", "ECL Coverage",
       "Expected credit loss as a share of exposure at default.",
       _ratio([_t("ecl", "Total ECL", STAGING, "sum", "total_ecl")],
              [_t("ead", "Total EAD", STAGING, "sum", "ead")]),
       unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("coverage", "ecl coverage", "provision coverage",
                "coverage ratio"),
       formula_text="SUM(total_ecl) / SUM(ead) × 100",
       numerator_text="Total expected credit loss",
       denominator_text="Total exposure at default",
       decimals=2, higher_is_better=False,
       not_this="Not a Stage 3 coverage ratio. This is the whole book, "
                "including Stage 1, whose coverage is small by design."),

    _m("corporate.ifrs9.macro_overlay", "Management Overlay",
       "Expected credit loss added by management judgement beyond the model.",
       _total(_t("ov", "Overlay", STAGING, "sum", "macro_overlay")),
       unit="currency", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("overlay", "management overlay", "post model adjustment",
                "pma"),
       formula_text="SUM(macro_overlay)", decimals=0),

    _m("corporate.ifrs9.overlay_share", "Overlay As A Share Of ECL",
       "How much of the total expected credit loss comes from management "
       "overlay rather than from the model.",
       _ratio([_t("ov", "Overlay", STAGING, "sum", "macro_overlay")],
              [_t("ecl", "Total ECL", STAGING, "sum", "total_ecl")]),
       unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("overlay share", "overlay percentage", "judgement share"),
       formula_text="SUM(macro_overlay) / SUM(total_ecl) × 100",
       decimals=1, higher_is_better=None,
       not_this="Not a measure of prudence. A high overlay share may mean "
                "the model is not trusted, which is a different problem."),

    _m("corporate.ifrs9.sicr_rate", "SICR Trigger Rate",
       "The share of exposure on which at least one significant-increase "
       "trigger has fired.",
       _ratio([_t("s", "Triggered EAD", STAGING, "sum", "ead",
                  sicr_any_trigger=True)],
              [_t("all", "Total EAD", STAGING, "sum", "ead")]),
       unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("sicr", "sicr rate", "significant increase", "sicr triggered"),
       formula_text="SUM(ead where sicr_any_trigger) / SUM(ead) × 100",
       higher_is_better=False,
       not_this="Not the Stage 2 ratio. A trigger can fire on exposure that "
                "is already in Stage 3."),

    _m("corporate.ifrs9.stage_moved", "Exposure That Changed Stage",
       "The share of exposure that moved stage this period.",
       _ratio([_t("m", "Moved", STAGING, "sum", "ead", stage_moved=True)],
              [_t("all", "Total EAD", STAGING, "sum", "ead")]),
       unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("stage movement", "stage transfer", "migration"),
       formula_text="SUM(ead where stage_moved) / SUM(ead) × 100",
       higher_is_better=False),

    _m("corporate.ifrs9.weighted_pd", "Exposure-Weighted 12-Month PD",
       "The average twelve-month probability of default, weighted by exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="pd", label="12-month PD", dataset=STAGING,
                aggregate="weighted_avg", field="pd_12m_pct",
                weight_field="ead"),))),
       unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("weighted pd", "average pd", "portfolio pd", "12 month pd"),
       formula_text="Σ(pd_12m_pct × ead) / Σ(ead)",
       decimals=2, higher_is_better=False,
       transformation="Weighted by exposure, because an unweighted mean "
                      "treats a small facility and a very large one as "
                      "equally important.",
       not_this="Not a lifetime PD."),

    _m("corporate.ifrs9.weighted_lgd", "Exposure-Weighted LGD",
       "The average loss given default, weighted by exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="lgd", label="LGD", dataset=STAGING,
                aggregate="weighted_avg", field="lgd_pct",
                weight_field="ead"),))),
       unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("weighted lgd", "average lgd", "loss given default"),
       formula_text="Σ(lgd_pct × ead) / Σ(ead)",
       decimals=2, higher_is_better=False),
)


# ============================================== corporate — portfolio

CORPORATE_PORTFOLIO: tuple[MetricDefinition, ...] = (
    _m("corporate.exposure", "Corporate Exposure",
       "Total on-book exposure across the corporate facility position.",
       _total(_t("e", "Exposure", FACILITIES, "sum", "exposure")),
       unit="currency", domain=CORPORATE, portfolio="Corporate",
       aliases=("exposure", "corporate exposure", "book size"),
       formula_text="SUM(exposure)", decimals=0),

    _m("corporate.facilities", "Corporate Facilities",
       "How many facilities are in the book.",
       Formula(kind="count", numerator=Side(terms=(
           Term(id="n", label="Facilities", dataset=FACILITIES,
                aggregate="count"),))),
       unit="count", domain=CORPORATE, portfolio="Corporate",
       aliases=("facilities", "accounts", "number of facilities"),
       formula_text="COUNT(rows)", decimals=0),

    _m("corporate.customers", "Corporate Customers",
       "How many distinct borrowers are in the book.",
       Formula(kind="distinct_count", numerator=Side(terms=(
           _t("c", "Customers", FACILITIES, "count_distinct", "customer_id"),))),
       unit="count", domain=CORPORATE, portfolio="Corporate",
       aliases=("customers", "borrowers", "obligors"),
       formula_text="COUNT(DISTINCT customer_id)", decimals=0),

    _m("corporate.npl_rate", "NPL Rate",
       "Non-performing exposure as a share of total exposure.",
       _ratio([_t("npl", "Non-performing exposure", FACILITIES, "sum",
                  "exposure", npl=True)],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("npl", "npl rate", "non performing", "npl ratio"),
       formula_text="SUM(exposure where npl) / SUM(exposure) × 100",
       numerator_text="Exposure flagged non-performing",
       denominator_text="Total exposure",
       higher_is_better=False),

    _m("corporate.watchlist_rate", "Watchlist Exposure Rate",
       "The share of exposure on the watchlist.",
       _ratio([_t("w", "Watchlist exposure", FACILITIES, "sum", "exposure",
                  watchlist=True)],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("watchlist", "watchlist rate"),
       formula_text="SUM(exposure where watchlist) / SUM(exposure) × 100",
       higher_is_better=False),

    _m("corporate.utilisation", "Corporate Utilisation",
       "Drawn exposure as a share of the approved limit.",
       _ratio([_t("e", "Exposure", FACILITIES, "sum", "exposure")],
              [_t("l", "Limit", FACILITIES, "sum", "limit_amount")]),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("utilisation", "corporate utilisation", "drawn"),
       formula_text="SUM(exposure) / SUM(limit_amount) × 100",
       higher_is_better=None),

    _m("corporate.delinquent_rate", "30+ DPD Corporate Exposure Rate",
       "The share of corporate exposure thirty or more days past due.",
       _ratio([_t("d", "30+ DPD exposure", DELINQUENCY, "sum",
                  "exposure_at_risk", days_past_due__gte=30)],
              [_t("all", "Exposure at risk", DELINQUENCY, "sum",
                  "exposure_at_risk")]),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("corporate 30+ dpd", "corporate delinquency"),
       formula_text=("SUM(exposure_at_risk where days_past_due >= 30) / "
                     "SUM(exposure_at_risk) × 100"),
       higher_is_better=False),
)


# ================================================ what is NOT available

UNSUPPORTED: tuple[Unsupported, ...] = (
    Unsupported(
        "retail.ifrs9.stage_exposure", "Retail Stage 1/2/3 Exposure", RETAIL,
        "This deployment has no retail impairment dataset. IFRS 9 staging, "
        "ECL and coverage exist for the corporate book only, and a retail "
        "stage ratio computed from corporate data would be a number about a "
        "different portfolio.",
        needs=("a retail IFRS 9 staging dataset carrying stage, EAD and ECL "
               "at account level",)),
    Unsupported(
        "retail.ifrs9.ecl", "Retail ECL", RETAIL,
        "There is no retail expected-credit-loss field in any governed "
        "dataset in this deployment.",
        needs=("a retail impairment dataset with ECL per account",)),
    Unsupported(
        "retail.approval_rate", "Approval Rate", RETAIL_ANALYTICS,
        "The application dataset records what was applied for and what "
        "happened afterwards, but not the accept/decline decision. An "
        "approval rate cannot be derived from it without assuming that every "
        "application with an outcome was approved, which is not true.",
        needs=("a decision outcome field on the application dataset",)),
    Unsupported(
        "retail.scorecard.psi", "Score Population Stability Index", RETAIL,
        "PSI compares this period's score distribution against the reference "
        "distribution the model was built on. That is a comparison of two "
        "populations, and the metric engine computes one period at a time. "
        "CreditProbe does report PSI: the scorecard validation module "
        "computes it against each model's declared reference window, where "
        "the reference is part of the model rather than a parameter of a "
        "dashboard tile.",
        needs=("the scorecard validation module's stability report, surfaced "
               "as a lens panel",)),
    Unsupported(
        "retail.roll_rate", "Delinquency Roll Rate", RETAIL,
        "A roll rate is a movement between two consecutive months for the "
        "same account. The behavioural dataset supports it structurally, but "
        "a period-over-period metric needs a comparison period the metric "
        "engine does not yet carry — it computes one period at a time.",
        needs=("period-over-period comparison in the metric engine",)),
    Unsupported(
        "retail.cure_rate", "Cure Rate", RETAIL,
        "Same reason as the roll rate: curing is a movement between periods, "
        "not a level within one.",
        needs=("period-over-period comparison in the metric engine",)),
    Unsupported(
        "corporate.ifrs9.ecl_movement", "ECL Movement Attribution",
        CORPORATE_IFRS9,
        "The opening-to-closing bridge — new business, repayments, stage "
        "migration, parameter movement, macro, overlays — is a decomposition "
        "across two periods with an attribution rule, not a metric. "
        "CreditProbe computes it in the IFRS 9 decomposition, and a tile here "
        "would be a second implementation of it.",
        needs=("the existing ECL decomposition, surfaced as a lens panel",)),
    Unsupported(
        "corporate.ifrs9.scenario_ecl", "Scenario-Weighted ECL",
        CORPORATE_IFRS9,
        "Scenario definitions and weights exist as a separate dataset, but "
        "the staging dataset carries one already-weighted ECL rather than one "
        "per scenario, so base, upside and downside cannot be separated from "
        "it.",
        needs=("per-scenario ECL on the staging dataset",)),
)


ALL: tuple[MetricDefinition, ...] = (
    RETAIL_PORTFOLIO + RETAIL_DELINQUENCY + RETAIL_QUALITY
    + RETAIL_VALIDATION + RETAIL_ORIGINATION
    + CORPORATE_IFRS9_METRICS + CORPORATE_PORTFOLIO
)


__all__ = [
    "LIBRARY_VERSION", "ALL", "UNSUPPORTED",
    "RETAIL", "RETAIL_ANALYTICS", "CORPORATE_IFRS9", "CORPORATE",
    "RETAIL_PORTFOLIO", "RETAIL_DELINQUENCY", "RETAIL_QUALITY",
    "RETAIL_VALIDATION", "RETAIL_ORIGINATION",
    "CORPORATE_IFRS9_METRICS", "CORPORATE_PORTFOLIO",
]
