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
#: Two more corporate domains, so the Metric Library has categories a person
#: navigates by rather than one bucket with forty things in it. They read the
#: same dataset as `CORPORATE`; what differs is the question being asked of
#: it, which is what a category is for.
CORPORATE_EW = "Corporate Early Warning"
CORPORATE_CONC = "Corporate Concentration"

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
       # Scoped and dated the way every other outcome metric on this dataset
       # already is (Gini, KS, predicted-versus-observed). Without it the
       # newest month — where nobody's performance window has closed — read
       # 0.0%, which is not a low default rate, it is no default rate. A zero
       # on a retail lens is a claim about the book; this one was a claim
       # about the calendar.
       scope=(Condition("matured_flag", "=", True),),
       period_rule=PERIOD_LATEST_MATURED,
       transformation="The default flag is the outcome over the performance "
                      "horizon recorded on the row, not a status at the "
                      "observation month. Only accounts whose window has "
                      "closed are counted, in the numerator and the "
                      "denominator alike.",
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


# ================================== retail — movement within the book

#: A roll rate compares two consecutive months for the same account, and the
#: metric engine computes one period at a time — so a true roll rate is still
#: unsupported, and says so below.
#:
#: These two are not that, and are named so they cannot be mistaken for it.
#: The behavioural dataset carries a trailing window ON EACH ROW —
#: `max_dpd_3m` is the worst arrears that account reached over the last three
#: months, `times_dpd_30plus_6m` is how often it went behind over the last
#: six. That is a comparison across time held within one row, which the engine
#: measures in one pass, and it answers the two questions a head of retail
#: risk actually asks about movement: how many of the accounts that went
#: behind have come back, and how many keep going behind.

RETAIL_MOVEMENT: tuple[MetricDefinition, ...] = (
    _m("retail.cure_rate_3m", "Cure Rate (3-Month Look-Back)",
       "Of the accounts that reached 30 or more days past due at any point in "
       "the last three months, the share that are fully up to date now.",
       _ratio([_t("cured", "Reached 30+ DPD and is now current", BEHAVIOURAL,
                  "count", "current_dpd", max_dpd_3m__gte=30,
                  current_dpd=0)],
              [_t("behind", "Reached 30+ DPD in the window", BEHAVIOURAL,
                  "count", "current_dpd", max_dpd_3m__gte=30)]),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("cure rate", "cures", "cured accounts", "recovery rate",
                "back to current", "rehabilitation rate"),
       formula_text=("COUNT(max_dpd_3m >= 30 and current_dpd = 0) / "
                     "COUNT(max_dpd_3m >= 30) × 100"),
       numerator_text="Accounts that went 30+ days behind in the last three "
                      "months and owe nothing overdue now",
       denominator_text="Accounts that went 30+ days behind in the last three "
                        "months",
       decimals=2, higher_is_better=True,
       transformation=(
           "Both sides read `max_dpd_3m`, the worst arrears the account "
           "reached over the trailing three months, which the behavioural "
           "dataset carries on the account's own row. The comparison across "
           "time is therefore held within one row and measured in one pass."),
       exclusions=("Accounts with fewer than three months on book have no "
                   "full trailing window; they carry whatever window exists "
                   "and are neither excluded nor extrapolated."),
       not_this=(
           "Not a roll rate, and not a month-on-month cure. This is a "
           "look-back over a three-month window on one reporting date, so an "
           "account that went behind and cured twice inside the window is "
           "counted once, as cured.")),

    _m("retail.repeat_delinquency_rate", "Repeat Delinquency Rate",
       "The share of accounts that have gone 30 or more days past due more "
       "than once in the last six months.",
       _ratio([_t("repeat", "Behind more than once", BEHAVIOURAL, "count",
                  "times_dpd_30plus_6m", times_dpd_30plus_6m__gte=2)],
              [Term(id="all", label="Accounts", dataset=BEHAVIOURAL,
                    aggregate="count")]),
       unit="percent", domain=RETAIL, portfolio="Retail",
       aliases=("repeat delinquency", "repeat arrears", "chronic delinquency",
                "serial delinquency", "recurring arrears",
                # It is a 30+ DPD metric and says so, because a search for
                # "delinq 30" reaches it through its definition either way,
                # and a suggestion whose name does not mention 30 days looks
                # like the picker widening rather than narrowing.
                "repeat 30 dpd", "30 dpd more than once",
                "30+ dpd repeat rate"),
       formula_text=("COUNT(times_dpd_30plus_6m >= 2) / COUNT(accounts) "
                     "× 100"),
       numerator_text="Accounts that went 30+ days behind twice or more in "
                      "the last six months",
       denominator_text="Every open account in the month",
       decimals=2, higher_is_better=False,
       transformation=(
           "Reads `times_dpd_30plus_6m`, the count of separate 30+ episodes "
           "over the trailing six months, carried on the account's own row."),
       not_this=(
           "Not the 30+ DPD rate. An account can be 30+ today having never "
           "been behind before, and an account can be current today having "
           "been behind three times since January. This measures the second "
           "kind, which the arrears buckets do not see.")),
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
       # The `exclusions` line below was already true and already written,
       # and the metric displayed 0.0% for the newest cohort anyway. A caveat
       # in an info panel a reader may never open is not the same as not
       # showing a fabricated zero, so the immature cohorts are now excluded
       # rather than described.
       scope=(Condition("matured_flag", "=", True),),
       period_rule=PERIOD_LATEST_MATURED,
       transformation="Grouped by application month, which is what makes it "
                      "a vintage rather than a snapshot.",
       exclusions="Cohorts whose performance window has not finished are "
                  "excluded entirely rather than counted as good. Including "
                  "them would understate the rate towards zero."),

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


# ==================================== corporate IFRS 9 — stage migration

#: Where a facility sat last period, and where it sits now. The staging
#: dataset carries `prior_stage` on every row, so a transition is a property
#: of one row rather than a comparison of two periods — which is why these can
#: be metrics at all, and why the ECL movement bridge below them still cannot.
#:
#: Named by the transition rather than by "migration", because "migration" on
#: its own is read as deterioration and half of these are the opposite.


def _transition(metric_id: str, name: str, definition: str, *,
                frm: Condition, to: Condition, aliases: tuple[str, ...],
                reads: str) -> MetricDefinition:
    """Exposure that moved between two stages this period."""
    return _m(metric_id, name, definition,
              _total(Term(id="moved", label=name, dataset=STAGING,
                          aggregate="sum", field="ead", where=(frm, to))),
              unit="currency", domain=CORPORATE_IFRS9, portfolio="Corporate",
              aliases=aliases,
              formula_text=f"SUM(ead where {reads})",
              decimals=0, higher_is_better=None,
              period_rule=PERIOD_SELECTED,
              transformation=(
                  "Read from `prior_stage` and `ifrs9_stage` on the same row. "
                  "The staging dataset records where each facility sat at the "
                  "previous reporting date, so a transition is a property of "
                  "one row and is measured in one pass."),
              exclusions=(
                  "A facility with no prior stage — one that entered the book "
                  "this period — matches no transition and is counted in "
                  "none of them."),
              not_this=(
                  "Not a balance. This is the exposure that moved, not the "
                  "exposure now sitting in the destination stage."),
              visuals=("kpi", "bar"))


def _transition_rate(metric_id: str, name: str, definition: str, *,
                     frm: Condition, to: Condition,
                     aliases: tuple[str, ...], reads: str,
                     base: str) -> MetricDefinition:
    """A transition as a share of the population that could have made it.

    The denominator is the exposure that started the period where the
    transition starts — not the whole book. A new-default rate over total
    exposure would fall whenever the book grew, which is the opposite of what
    the reader takes from it.
    """
    return _m(metric_id, name, definition,
              _ratio([Term(id="moved", label="Exposure that moved",
                           dataset=STAGING, aggregate="sum", field="ead",
                           where=(frm, to))],
                     [Term(id="base", label=base, dataset=STAGING,
                           aggregate="sum", field="ead", where=(frm,))]),
              unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
              aliases=aliases,
              formula_text=f"SUM(ead where {reads}) / "
                           f"SUM(ead where {frm.describe()}) × 100",
              numerator_text="Exposure that made this transition",
              denominator_text=base,
              decimals=2,
              period_rule=PERIOD_SELECTED,
              transformation=(
                  "Both sides are measured over the same scan of the same "
                  "period, so the share is of the population that could have "
                  "made the move rather than of the whole book."),
              not_this=(
                  "Not a share of total exposure. The denominator is the "
                  "exposure that started the period in the origin stage, "
                  "which is what makes the rate comparable between periods "
                  "when the book grows."))


CORPORATE_IFRS9_MIGRATION: tuple[MetricDefinition, ...] = (
    _transition(
        "corporate.ifrs9.stage_1_to_2_ead", "Stage 1 To Stage 2 Exposure",
        "Exposure that was performing at the last reporting date and has "
        "since been assessed as significantly deteriorated.",
        frm=Condition("prior_stage", "=", 1),
        to=Condition("ifrs9_stage", "=", 2),
        aliases=("stage 1 to 2", "stage 1 to stage 2", "sicr transfers",
                 "transfers to stage 2", "stage 2 inflow"),
        reads="prior_stage = 1 and ifrs9_stage = 2"),

    _transition(
        "corporate.ifrs9.stage_2_to_1_ead", "Stage 2 To Stage 1 Exposure",
        "Exposure that has recovered from significant deterioration back to "
        "twelve-month expected loss.",
        frm=Condition("prior_stage", "=", 2),
        to=Condition("ifrs9_stage", "=", 1),
        aliases=("stage 2 to 1", "stage 2 to stage 1", "transfers to stage 1",
                 "stage 2 cures", "recoveries to performing"),
        reads="prior_stage = 2 and ifrs9_stage = 1"),

    _transition(
        "corporate.ifrs9.stage_2_to_3_ead", "Stage 2 To Stage 3 Exposure",
        "Exposure that was already deteriorated at the last reporting date "
        "and has since defaulted.",
        frm=Condition("prior_stage", "=", 2),
        to=Condition("ifrs9_stage", "=", 3),
        aliases=("stage 2 to 3", "stage 2 to stage 3", "transfers to stage 3",
                 "defaults from stage 2"),
        reads="prior_stage = 2 and ifrs9_stage = 3"),

    _transition(
        "corporate.ifrs9.new_default_ead", "Newly Defaulted Exposure",
        "Exposure that entered Stage 3 this period, from wherever it was "
        "before.",
        frm=Condition("prior_stage", "!=", 3),
        to=Condition("ifrs9_stage", "=", 3),
        aliases=("new defaults", "newly defaulted", "defaults", "new npl",
                 "entries to stage 3", "default inflow"),
        reads="prior_stage != 3 and ifrs9_stage = 3"),

    _transition(
        "corporate.ifrs9.cured_ead", "Cured Exposure",
        "Exposure that was in default at the last reporting date and is no "
        "longer.",
        frm=Condition("prior_stage", "=", 3),
        to=Condition("ifrs9_stage", "!=", 3),
        aliases=("cured", "cured exposure", "exits from stage 3",
                 "default outflow", "exposure that cured"),
        reads="prior_stage = 3 and ifrs9_stage != 3"),

    _transition_rate(
        "corporate.ifrs9.stage_2_inflow_rate", "Stage 2 Inflow Rate",
        "The share of last period's performing exposure that has been "
        "assessed as significantly deteriorated this period.",
        frm=Condition("prior_stage", "=", 1),
        to=Condition("ifrs9_stage", "=", 2),
        aliases=("stage 2 inflow rate", "sicr transfer rate",
                 "deterioration rate", "stage 1 to 2 rate"),
        reads="prior_stage = 1 and ifrs9_stage = 2",
        base="Exposure that started the period in Stage 1"),

    _transition_rate(
        "corporate.ifrs9.new_default_rate", "New Default Rate",
        "The share of last period's non-defaulted exposure that has defaulted "
        "this period.",
        frm=Condition("prior_stage", "!=", 3),
        to=Condition("ifrs9_stage", "=", 3),
        # Not the bare "default rate", which the retail book's own default
        # rate answers to.
        aliases=("new default rate", "default emergence",
                 "inflow to default", "corporate default rate",
                 "rate of new defaults"),
        reads="prior_stage != 3 and ifrs9_stage = 3",
        base="Exposure that started the period outside Stage 3"),

    _transition_rate(
        "corporate.ifrs9.cure_rate", "Cure Rate",
        "The share of last period's defaulted exposure that is no longer in "
        "default.",
        frm=Condition("prior_stage", "=", 3),
        to=Condition("ifrs9_stage", "!=", 3),
        # Deliberately not the bare "cure rate": the retail book's cure
        # rate owns that phrasing, and an alias claimed twice makes a
        # typeahead answer one of them by alphabetical accident.
        aliases=("corporate cure rate", "stage 3 exit rate",
                 "exit rate from default", "default cure rate"),
        reads="prior_stage = 3 and ifrs9_stage != 3",
        base="Exposure that started the period in Stage 3"),
)


# ============================== corporate IFRS 9 — what fired the trigger

#: SICR is one rule with five ways of firing, and a committee asked "why is
#: Stage 2 up" needs to know which. `corporate.ifrs9.sicr_rate` answers
#: whether ANY fired; these five answer which, and they overlap on purpose —
#: one facility can breach a covenant and be downgraded in the same quarter,
#: so these do not sum to the SICR rate and each says so.


def _sicr_trigger(suffix: str, name: str, field: str, definition: str,
                  aliases: tuple[str, ...]) -> MetricDefinition:
    return _m(f"corporate.ifrs9.sicr_{suffix}", name, definition,
              _ratio([_t("fired", f"{name} EAD", STAGING, "sum", "ead",
                         **{field: True})],
                     [_t("all", "Total EAD", STAGING, "sum", "ead")]),
              unit="percent", domain=CORPORATE_IFRS9, portfolio="Corporate",
              aliases=aliases,
              formula_text=f"SUM(ead where {field}) / SUM(ead) × 100",
              numerator_text=f"Exposure on which the {name.lower()} fired",
              denominator_text="Total exposure at default across all stages",
              decimals=2, higher_is_better=False,
              period_rule=PERIOD_SELECTED,
              not_this=(
                  "Not a share of the SICR rate. A facility can fire more "
                  "than one trigger in a period, so the five trigger rates "
                  "overlap and do not sum to the rate at which any trigger "
                  "fired."))


CORPORATE_IFRS9_TRIGGERS: tuple[MetricDefinition, ...] = (
    _sicr_trigger("dpd", "SICR: Days Past Due", "sicr_dpd_trigger",
                  "The share of exposure where the significant-increase "
                  "assessment was triggered by arrears.",
                  ("sicr dpd", "sicr days past due", "dpd trigger",
                   "arrears trigger")),
    _sicr_trigger("pd", "SICR: PD Deterioration", "sicr_pd_trigger",
                  "The share of exposure where the significant-increase "
                  "assessment was triggered by the probability of default "
                  "moving against its level at origination.",
                  ("sicr pd", "pd trigger", "pd deterioration trigger")),
    _sicr_trigger("rating", "SICR: Rating Downgrade", "sicr_rating_trigger",
                  "The share of exposure where the significant-increase "
                  "assessment was triggered by an internal rating downgrade.",
                  ("sicr rating", "rating trigger", "downgrade trigger")),
    _sicr_trigger("watchlist", "SICR: Watchlist", "sicr_watchlist_trigger",
                  "The share of exposure where the significant-increase "
                  "assessment was triggered by the name being placed on the "
                  "watchlist.",
                  ("sicr watchlist", "watchlist trigger")),
    _sicr_trigger("covenant", "SICR: Covenant Breach",
                  "sicr_covenant_trigger",
                  "The share of exposure where the significant-increase "
                  "assessment was triggered by a covenant breach.",
                  ("sicr covenant", "covenant trigger", "covenant breach "
                   "trigger")),

    _m("corporate.ifrs9.pd_drift", "PD Drift Since Origination",
       "How far the twelve-month probability of default has moved from where "
       "it was when the facility was written, weighted by exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="drift", label="PD relative to origination",
                dataset=STAGING, aggregate="weighted_avg",
                field="pd_ratio_to_origination", weight_field="ead"),))),
       unit="ratio", domain=CORPORATE_IFRS9, portfolio="Corporate",
       aliases=("pd drift", "pd deterioration", "pd versus origination",
                "pd ratio to origination"),
       formula_text="Σ(pd_ratio_to_origination × ead) / Σ(ead)",
       decimals=2, higher_is_better=False,
       period_rule=PERIOD_SELECTED,
       transformation="Weighted by exposure, so a large facility whose PD has "
                      "doubled counts for more than a small one.",
       not_this="Not a PD. It is a multiple: 1.0 means the book is priced "
                "where it was written, 2.0 means twice the risk it was "
                "written at."),
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


# ====================================== corporate — portfolio quality

#: The corporate book read as a credit portfolio rather than as an impairment
#: calculation. `portfolio_facility` carries the internal grade, the rating
#: bucket, the return and the trend on every facility row, so these are all
#: single-pass measures over the same scan the exposure total uses.
#:
#: Exposure-weighted wherever a weighting is possible, and each says so. An
#: unweighted mean internal grade treats a two-million riyal facility and a
#: two-hundred-million one as equally important, which is not what anybody
#: means by "the average grade of the book".

CORPORATE_QUALITY: tuple[MetricDefinition, ...] = (
    _m("corporate.limit_amount", "Corporate Approved Limits",
       "The total approved limit across the corporate book, drawn or not.",
       _total(_t("l", "Approved limit", FACILITIES, "sum", "limit_amount")),
       unit="currency", domain=CORPORATE, portfolio="Corporate",
       aliases=("limits", "approved limits", "total limit", "sanctioned"),
       formula_text="SUM(limit_amount)", decimals=0,
       not_this="Not exposure. A limit is what the bank has committed to "
                "lend; exposure is what has been drawn."),

    _m("corporate.undrawn", "Undrawn Commitment",
       "The part of the approved limit that has not been drawn.",
       _total(_t("u", "Undrawn", FACILITIES, "sum", "undrawn")),
       unit="currency", domain=CORPORATE, portfolio="Corporate",
       aliases=("undrawn", "undrawn commitment", "available headroom",
                "unutilised"),
       formula_text="SUM(undrawn)", decimals=0, higher_is_better=None,
       not_this="Not spare capacity in a risk sense. Undrawn commitment is "
                "still an exposure the bank is obliged to fund, which is why "
                "IFRS 9 measures it with a credit conversion factor."),

    _m("corporate.weighted_internal_grade", "Exposure-Weighted Internal Grade",
       "The average internal risk grade across the book, weighted by "
       "exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="g", label="Internal grade", dataset=FACILITIES,
                aggregate="weighted_avg", field="internal_grade",
                weight_field="exposure"),))),
       unit="score", domain=CORPORATE, portfolio="Corporate",
       aliases=("average grade", "internal grade", "weighted grade",
                "portfolio grade", "average rating"),
       formula_text="Σ(internal_grade × exposure) / Σ(exposure)",
       decimals=2, higher_is_better=False,
       transformation="Weighted by exposure, because an unweighted mean "
                      "treats a small facility and a very large one as "
                      "equally important.",
       not_this="Not an external rating. The internal grade runs 1 to 10 on "
                "CreditProbe's own scale, where a higher number is worse."),

    _m("corporate.investment_grade_rate", "Investment Grade Exposure Rate",
       "The share of exposure rated investment grade internally.",
       _ratio([_t("ig", "Investment grade EAD", FACILITIES, "sum", "exposure",
                  rating_bucket="Investment grade")],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("investment grade", "investment grade share", "ig share",
                "quality mix"),
       formula_text=("SUM(exposure where rating_bucket = 'Investment grade') "
                     "/ SUM(exposure) × 100"),
       higher_is_better=True,
       not_this="Not an agency rating. This is CreditProbe's own rating "
                "bucket, mapped from the internal grade."),

    _m("corporate.impaired_rate", "Impaired Exposure Rate",
       "The share of exposure in the impaired rating bucket.",
       _ratio([_t("im", "Impaired EAD", FACILITIES, "sum", "exposure",
                  rating_bucket="Impaired")],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("impaired", "impaired share", "impaired exposure"),
       formula_text=("SUM(exposure where rating_bucket = 'Impaired') / "
                     "SUM(exposure) × 100"),
       higher_is_better=False,
       not_this="Close to the NPL rate and not identical to it: the rating "
                "bucket is a grade, and the NPL flag is a status."),

    _m("corporate.weighted_raroc", "Exposure-Weighted RAROC",
       "Risk-adjusted return on capital across the book, weighted by "
       "exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="r", label="RAROC", dataset=FACILITIES,
                aggregate="weighted_avg", field="raroc_pct",
                weight_field="exposure"),))),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("raroc", "risk adjusted return", "return on capital"),
       formula_text="Σ(raroc_pct × exposure) / Σ(exposure)",
       decimals=2, higher_is_better=True,
       not_this="Not a profit figure. RAROC is a return on the capital the "
                "facility consumes, and can be negative on a facility that "
                "is still making money."),

    _m("corporate.portfolio_weighted_pd", "Book-Weighted 12-Month PD",
       "The average twelve-month probability of default across the facility "
       "book, weighted by exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="pd", label="12-month PD", dataset=FACILITIES,
                aggregate="weighted_avg", field="pd_12m_pct",
                weight_field="exposure"),))),
       unit="percent", domain=CORPORATE, portfolio="Corporate",
       aliases=("book pd", "portfolio pd", "facility pd"),
       formula_text="Σ(pd_12m_pct × exposure) / Σ(exposure)",
       decimals=2, higher_is_better=False,
       not_this="Read from the facility book. The IFRS 9 staging dataset "
                "carries its own exposure-weighted PD, and the two are "
                "measured over different populations."),
)


# ====================================== corporate — early warning

CORPORATE_EARLY_WARNING: tuple[MetricDefinition, ...] = (
    _m("corporate.watchlist_exposure", "Watchlist Exposure",
       "Exposure to customers the bank has placed on the watchlist.",
       _total(_t("w", "Watchlist EAD", FACILITIES, "sum", "exposure",
                 watchlist=True)),
       unit="currency", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("watchlist", "watchlist exposure", "on watch",
                "names on watch"),
       formula_text="SUM(exposure where watchlist)", decimals=0,
       higher_is_better=False,
       not_this="Not defaulted exposure. A watchlist name is one the bank is "
                "watching, which is the point of watching it."),

    _m("corporate.downgrade_probability", "Exposure-Weighted Downgrade Risk",
       "The modelled probability of a rating downgrade over the next twelve "
       "months, weighted by exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="d", label="Downgrade probability", dataset=FACILITIES,
                aggregate="weighted_avg", field="downgrade_prob_pct",
                weight_field="exposure"),))),
       unit="percent", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("downgrade probability", "downgrade risk",
                "probability of downgrade", "migration risk"),
       formula_text="Σ(downgrade_prob_pct × exposure) / Σ(exposure)",
       decimals=2, higher_is_better=False,
       not_this="Not a probability of default. A downgrade is a move in "
                "grade, and most downgrades never reach default."),

    _m("corporate.covenant_headroom", "Exposure-Weighted Covenant Headroom",
       "How much room borrowers have before their covenants bite, weighted "
       "by exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="h", label="Covenant headroom", dataset=FACILITIES,
                aggregate="weighted_avg", field="covenant_headroom_pct",
                weight_field="exposure"),))),
       unit="percent", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("covenant headroom", "headroom", "covenant cushion"),
       formula_text="Σ(covenant_headroom_pct × exposure) / Σ(exposure)",
       decimals=2, higher_is_better=True,
       not_this="An average, so it hides the tail. The breach rate beside it "
                "is what says how much of the book has already run out."),

    _m("corporate.covenant_breach_rate", "Covenant Breach Exposure Rate",
       "The share of exposure where covenant headroom has gone negative.",
       _ratio([_t("b", "Breached EAD", FACILITIES, "sum", "exposure",
                  covenant_headroom_pct__lt=0)],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("covenant breach", "breach rate", "covenants breached"),
       formula_text=("SUM(exposure where covenant_headroom_pct < 0) / "
                     "SUM(exposure) × 100"),
       higher_is_better=False,
       not_this="A breach on the reported headroom, not a waiver decision. "
                "Whether the bank has waived it is a separate record."),

    # The AMOUNTS behind the two rates above. See the note on
    # `corporate.high_severity_exposure`: a share cannot be the numerator of
    # another ratio, and "covenant breach exposure over corporate exposure" is
    # a request for an amount.
    _m("corporate.covenant_breach_exposure", "Covenant Breach Exposure",
       "Exposure to facilities whose covenant headroom has gone negative.",
       _total(_t("cb", "Breached EAD", FACILITIES, "sum", "exposure",
                 covenant_headroom_pct__lt=0)),
       unit="currency", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("covenant breach exposure", "breached exposure",
                "exposure in covenant breach", "covenant breach ead"),
       formula_text="SUM(exposure where covenant_headroom_pct < 0)",
       decimals=0, higher_is_better=False,
       not_this="Not the covenant breach RATE beside it. This is the amount; "
                "that is the share of the book it represents."),

    _m("corporate.watchlist_exposure_amount", "Watchlist Exposure Amount",
       "Exposure to customers the bank has placed on the watchlist, as an "
       "amount rather than a share.",
       _total(_t("w", "Watchlist EAD", FACILITIES, "sum", "exposure",
                 watchlist=True)),
       unit="currency", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("watchlist exposure amount", "watchlisted exposure",
                "exposure on watch"),
       formula_text="SUM(exposure where watchlist)", decimals=0,
       higher_is_better=False,
       not_this="The same figure as Watchlist Exposure, kept under a second "
                "name so a formula asking for an amount finds one."),

    _m("corporate.weighted_dscr", "Exposure-Weighted DSCR",
       "Debt service coverage across the book, weighted by exposure.",
       Formula(kind="weighted_average", numerator=Side(terms=(
           Term(id="d", label="DSCR", dataset=FACILITIES,
                aggregate="weighted_avg", field="dscr",
                weight_field="exposure"),))),
       unit="ratio", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("dscr", "debt service coverage", "coverage ratio"),
       formula_text="Σ(dscr × exposure) / Σ(exposure)",
       decimals=2, higher_is_better=True,
       not_this="Not ECL coverage. This is cash flow over debt service; ECL "
                "coverage is provision over exposure."),

    _m("corporate.dscr_below_one_rate", "Exposure Not Covering Debt Service",
       "The share of exposure to borrowers whose cash flow does not cover "
       "their debt service.",
       _ratio([_t("b", "DSCR below 1", FACILITIES, "sum", "exposure",
                  dscr__lt=1.0)],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("dscr below 1", "cannot service debt", "negative coverage"),
       formula_text="SUM(exposure where dscr < 1) / SUM(exposure) × 100",
       higher_is_better=False,
       not_this="Not a default rate. A borrower below one is funding debt "
                "service from somewhere other than operating cash flow, "
                "which many do for a year without defaulting."),

    _m("corporate.deteriorating_rate", "Deteriorating Exposure Rate",
       "The share of exposure whose credit trend is assessed as "
       "deteriorating.",
       _ratio([_t("d", "Deteriorating EAD", FACILITIES, "sum", "exposure",
                  trend="Deteriorating")],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("deteriorating", "worsening", "negative trend",
                "trend deteriorating"),
       formula_text=("SUM(exposure where trend = 'Deteriorating') / "
                     "SUM(exposure) × 100"),
       higher_is_better=False),

    _m("corporate.critical_severity_rate", "Critical Severity Exposure Rate",
       "The share of exposure carrying a critical early-warning severity.",
       _ratio([_t("c", "Critical EAD", FACILITIES, "sum", "exposure",
                  severity="Critical")],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("critical severity", "critical", "highest severity"),
       formula_text=("SUM(exposure where severity = 'Critical') / "
                     "SUM(exposure) × 100"),
       higher_is_better=False),

    _m("corporate.ai_risk_score", "Average AI Risk Score",
       "The mean forward-looking risk score CreditProbe assigns each "
       "facility.",
       Formula(kind="average", numerator=Side(terms=(
           _t("s", "AI risk score", FACILITIES, "avg", "ai_risk_score"),))),
       unit="index", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("ai risk score", "risk score", "forward risk signal"),
       formula_text="AVG(ai_risk_score)", decimals=3,
       higher_is_better=False,
       not_this="An unweighted mean across facilities, not an exposure "
                "weighting: the score is a property of the name rather than "
                "of the amount lent to it."),

    # The AMOUNT, beside the rates above. Every early-warning metric here was
    # a share of the book, and a share cannot be the numerator of another
    # ratio — "high-severity EWS exposure over total corporate exposure" needs
    # an exposure, and until this entry existed the only thing the catalogue
    # could offer for it was a percentage, which would have produced a
    # plausible number a hundred times too small.
    _m("corporate.high_severity_exposure", "High-Severity EWS Exposure",
       "Exposure to facilities carrying a high or critical early-warning "
       "severity.",
       _total(_t("hs", "High-severity EAD", FACILITIES, "sum", "exposure",
                 severity__in=("High", "Critical"))),
       unit="currency", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("high severity exposure", "high ews exposure",
                "high-severity ews exposure", "ews exposure",
                "high severity ead", "severe exposure",
                "high and critical severity exposure"),
       formula_text="SUM(exposure where severity in ('High', 'Critical'))",
       decimals=0, higher_is_better=False,
       not_this="Not the critical-severity rate beside it. This is the "
                "amount; that is the share, and dividing one ratio by another "
                "is how a number ends up a hundred times too small."),

    _m("corporate.high_severity_rate", "High-Severity EWS Exposure Rate",
       "The share of exposure carrying a high or critical early-warning "
       "severity.",
       _ratio([_t("hs", "High-severity EAD", FACILITIES, "sum", "exposure",
                  severity__in=("High", "Critical"))],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE_EW, portfolio="Corporate",
       aliases=("high severity rate", "high severity share",
                "high and critical severity rate"),
       formula_text=("SUM(exposure where severity in ('High', 'Critical')) / "
                     "SUM(exposure) × 100"),
       higher_is_better=False,
       not_this="Wider than the critical-severity rate beside it, which "
                "counts only the worst band."),
)


# ================================ corporate — concentration and limits

CORPORATE_CONCENTRATION: tuple[MetricDefinition, ...] = (
    _m("corporate.obligor_groups", "Obligor Groups",
       "How many connected borrower groups the book is spread across.",
       Formula(kind="distinct_count", numerator=Side(terms=(
           _t("g", "Obligor groups", FACILITIES, "count_distinct",
              "obligor_group"),))),
       unit="count", domain=CORPORATE_CONC, portfolio="Corporate",
       aliases=("obligor groups", "connected groups", "borrower groups",
                "counterparty groups"),
       formula_text="COUNT(DISTINCT obligor_group)", decimals=0,
       higher_is_better=True,
       not_this="Not a count of customers. A group is several customers the "
                "bank treats as one credit risk, which is the unit a large "
                "exposure limit applies to."),

    _m("corporate.average_group_exposure", "Average Exposure Per Group",
       "Total exposure divided by the number of connected borrower groups.",
       Formula(kind="ratio",
               numerator=Side(terms=(
                   _t("e", "Total exposure", FACILITIES, "sum", "exposure"),)),
               denominator=Side(terms=(
                   _t("g", "Obligor groups", FACILITIES, "count_distinct",
                      "obligor_group"),)),
               scale=1.0),
       unit="currency", domain=CORPORATE_CONC, portfolio="Corporate",
       aliases=("average group exposure", "exposure per group",
                "average obligor size"),
       formula_text="SUM(exposure) / COUNT(DISTINCT obligor_group)",
       numerator_text="Total exposure across the book",
       denominator_text="Connected borrower groups in it",
       decimals=0, higher_is_better=None,
       not_this="A mean, so it says nothing about the largest group. The "
                "concentration charts beside it are where a single name "
                "shows."),

    _m("corporate.appetite_breach_exposure", "Exposure Breaching Appetite",
       "Exposure on facilities that breach the bank's stated risk appetite.",
       _total(_t("b", "Breaching EAD", FACILITIES, "sum", "exposure",
                 appetite_breach=True)),
       unit="currency", domain=CORPORATE_CONC, portfolio="Corporate",
       aliases=("appetite breach", "over appetite", "breaching appetite",
                "limit breach"),
       formula_text="SUM(exposure where appetite_breach)", decimals=0,
       higher_is_better=False),

    _m("corporate.appetite_breach_rate", "Appetite Breach Exposure Rate",
       "The share of exposure that breaches the bank's stated risk appetite.",
       _ratio([_t("b", "Breaching EAD", FACILITIES, "sum", "exposure",
                  appetite_breach=True)],
              [_t("all", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE_CONC, portfolio="Corporate",
       aliases=("appetite breach rate", "over appetite share",
                "breach of appetite"),
       formula_text=("SUM(exposure where appetite_breach) / SUM(exposure) "
                     "× 100"),
       higher_is_better=False,
       not_this="Appetite, not regulatory limit. A breach here is against "
                "the bank's own stated appetite for the sector."),

    _m("corporate.collateral_coverage", "Collateral Coverage",
       "Registered collateral value as a share of exposure.",
       _ratio([_t("c", "Collateral value", FACILITIES, "sum",
                  "collateral_value")],
              [_t("e", "Total exposure", FACILITIES, "sum", "exposure")]),
       unit="percent", domain=CORPORATE_CONC, portfolio="Corporate",
       aliases=("collateral coverage", "security coverage", "collateral",
                "secured share"),
       formula_text="SUM(collateral_value) / SUM(exposure) × 100",
       decimals=1, higher_is_better=True,
       not_this="Registered value, not realisable value. Recovery depends on "
                "enforceability and on what the collateral is worth when it "
                "is needed, which is not when it was valued."),

    _m("corporate.utilisation_of_limits", "Limit Utilisation",
       "Drawn exposure as a share of the approved limit.",
       _ratio([_t("e", "Exposure", FACILITIES, "sum", "exposure")],
              [_t("l", "Approved limit", FACILITIES, "sum", "limit_amount")]),
       unit="percent", domain=CORPORATE_CONC, portfolio="Corporate",
       aliases=("limit utilisation", "utilisation of limits", "drawn share"),
       formula_text="SUM(exposure) / SUM(limit_amount) × 100",
       decimals=1, higher_is_better=None,
       not_this="The same arithmetic as Corporate Utilisation, kept in this "
                "domain so a concentration lens can carry it without "
                "reaching into another. Both read the same fields and always "
                "agree."),
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
        "same account: the share of one arrears bucket that moves into the "
        "next. The "
        "behavioural dataset supports it structurally, but a "
        "period-over-period metric needs a comparison period the metric "
        "engine does not yet carry — it computes one period at a time. "
        "Repeat Delinquency Rate is the nearest thing this deployment can "
        "measure honestly: it reads the trailing six-month episode count "
        "carried on each account's own row, and says how many accounts keep "
        "going behind rather than how much of one bucket rolled into the "
        "next.",
        needs=("period-over-period comparison in the metric engine",)),
    Unsupported(
        "retail.cure_rate", "Cure Rate (Month On Month)", RETAIL,
        "A month-on-month cure — the share of accounts behind last month that "
        "are current this month — is a comparison of two periods, and the "
        "metric engine computes one at a time. Cure Rate (3-Month Look-Back) "
        "is on this lens instead and is a different measurement, not a "
        "substitute: it reads `max_dpd_3m` from the account's own row, so it "
        "asks how many of the accounts that went behind at any point in the "
        "trailing three months are up to date now.",
        needs=("period-over-period comparison in the metric engine",)),
    Unsupported(
        "corporate.ifrs9.ecl_movement", "ECL Movement Attribution",
        CORPORATE_IFRS9,
        "The opening-to-closing bridge — new business, repayments, stage "
        "migration, parameter movement, macro, overlays — is a decomposition "
        "across two periods with an attribution rule, not a metric. "
        "CreditProbe computes it in the IFRS 9 decomposition, and a tile here "
        "would be a second implementation of it. The stage migration band on "
        "this lens covers the one component of the bridge the staging dataset "
        "can answer on its own, because `prior_stage` is carried on each "
        "row; the parameter, macro and overlay legs are not derivable that "
        "way.",
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
    + RETAIL_MOVEMENT + RETAIL_VALIDATION + RETAIL_ORIGINATION
    + CORPORATE_IFRS9_METRICS + CORPORATE_IFRS9_MIGRATION
    + CORPORATE_IFRS9_TRIGGERS + CORPORATE_PORTFOLIO
    + CORPORATE_QUALITY + CORPORATE_EARLY_WARNING + CORPORATE_CONCENTRATION
)


__all__ = [
    "LIBRARY_VERSION", "ALL", "UNSUPPORTED",
    "RETAIL", "RETAIL_ANALYTICS", "CORPORATE_IFRS9", "CORPORATE",
    "CORPORATE_EW", "CORPORATE_CONC",
    "RETAIL_PORTFOLIO", "RETAIL_DELINQUENCY", "RETAIL_QUALITY",
    "RETAIL_MOVEMENT", "RETAIL_VALIDATION", "RETAIL_ORIGINATION",
    "CORPORATE_IFRS9_METRICS", "CORPORATE_IFRS9_MIGRATION",
    "CORPORATE_IFRS9_TRIGGERS", "CORPORATE_PORTFOLIO",
    "CORPORATE_QUALITY", "CORPORATE_EARLY_WARNING",
    "CORPORATE_CONCENTRATION",
]
