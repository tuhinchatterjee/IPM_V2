"""
Rating-history and macroeconomic analyses.

The facility book is quarterly and the rating cycle is annual, so these read
their own governed datasets rather than trying to reconstruct a rating history
from quarterly snapshots. `customer_ratings` records what grade each customer
was awarded each year and why; `macro_saudi` records the economy it was awarded
in.

Every function is deterministic and takes no input from a language model except
parameters the contract has already validated.
"""

from __future__ import annotations

import pandas as pd

from backend.data_access.catalog import (
    CUSTOMER_RATING_HISTORY,
    MACROECONOMIC_SERIES,
)
from backend.engine.contracts import (
    AnalysisContract,
    AnswerShape,
    Category,
    Certification,
    OutputField,
    Parameter,
    ParamType,
    PeriodRequirement,
    ValidationRule,
    VisualizationType,
)
from backend.engine.execution import ExecutionContext
from backend.engine.helpers import (
    MACRO,
    RATINGS,
    frame_to_rows,
    resolve_periods,
    rounded,
    safe_ratio,
)
from backend.engine.registry import AnalysisResult, register
from backend.trace.model import NodeType

OWNER = "Credit Risk Analytics"

YEAR_PARAM = Parameter(
    "period", ParamType.PERIOD,
    "Rating year to analyse. Accepts a year, or 'latest' / 'earliest'.",
    default="latest",
)


# ================================================== rating actions in a year

ACTION_FIELDS = [
    "customer_id", "borrower_name", "sector", "segment", "internal_grade",
    "prior_internal_grade", "notches_moved", "rating_action", "risk_rating",
    "rating_bucket", "pd_12m_pct", "net_leverage", "interest_coverage",
]


@register(AnalysisContract(
    id="rating_actions",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is what the rating committee did in a cycle — how "
        "many upgrades, how many downgrades, and how far."
    ),
    trigger_questions=[
        "How many downgrades were there last year?",
        "What did the rating committee do this cycle?",
        "Show me the upgrades and downgrades.",
        "Which sectors were downgraded most?",
    ],
    limitations=(
        "One annual cycle. A customer rated for the first time has no prior grade "
        "and is reported as an initial rating rather than as an affirmation."
    ),
    required_domains=[CUSTOMER_RATING_HISTORY],
    name="Rating Actions",
    description=(
        "Upgrades, downgrades, affirmations and initial ratings in one annual "
        "cycle, by count and by notches moved, broken down by sector."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[RATINGS],
    required_fields=ACTION_FIELDS,
    parameters=[YEAR_PARAM],
    outputs=[
        OutputField("customers_rated", "Customers rated in the cycle.", "integer"),
        OutputField("downgrades", "Customers downgraded.", "integer"),
        OutputField("upgrades", "Customers upgraded.", "integer"),
        OutputField("downgrade_ratio", "Downgrades per upgrade.", "number", unit="x", precision=2),
        OutputField("net_notches", "Notches downgraded less notches upgraded.", "integer"),
    ],
    validation_rules=[
        ValidationRule("actions_are_exhaustive",
                       "Every rated customer must carry exactly one action."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Counts each rating action in the cycle and sums the notches moved. A "
        "positive notch move is a downgrade. The downgrade ratio is downgrades "
        "divided by upgrades — above one means the committee moved the book down "
        "on balance."
    ),
))
def rating_actions(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, RATINGS, ctx.params.get("period"), None
    )
    df, _ = ctx.read(RATINGS, fields=ACTION_FIELDS, period=period,
                     label=f"Customer ratings · {period}")

    df["notches_moved"] = pd.to_numeric(df["notches_moved"], errors="coerce").fillna(0)

    by_action = (
        df.groupby("rating_action", dropna=False)
        .agg(customers=("customer_id", "count"), notches=("notches_moved", "sum"))
        .reset_index()
        .sort_values("customers", ascending=False)
    )
    by_sector = (
        df[df["rating_action"] == "Downgrade"]
        .groupby("sector", dropna=False)
        .agg(downgrades=("customer_id", "count"), notches=("notches_moved", "sum"))
        .reset_index()
        .sort_values("downgrades", ascending=False)
    )

    ctx.step(NodeType.AGGREGATION, f"Group {len(df):,} rated customers by action",
             config={"group_by": ["rating_action"], "measures": ["customers", "notches"]},
             rows_in=int(len(df)), rows_out=int(len(by_action)))

    downgrades = int((df["rating_action"] == "Downgrade").sum())
    upgrades = int((df["rating_action"] == "Upgrade").sum())
    unaccounted = int(df["rating_action"].isna().sum())
    if unaccounted:
        ctx.warn(f"{unaccounted:,} customers have no rating action recorded.")

    return AnalysisResult(
        rows=frame_to_rows(by_action),
        values={
            "period": period,
            "customers_rated": int(len(df)),
            "downgrades": downgrades,
            "upgrades": upgrades,
            "affirmations": int((df["rating_action"] == "Affirmed").sum()),
            "initial_ratings": int((df["rating_action"] == "Initial rating").sum()),
            "downgrade_ratio": rounded(downgrades / upgrades, 2) if upgrades else 0.0,
            "net_notches": int(df["notches_moved"].sum()),
            "downgrades_by_sector": frame_to_rows(by_sector.head(10)),
            "periods_available": available,
        },
        units={"notches": "notches"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per rating action."},
    )


# ================================================== rating grade distribution

GRADE_FIELDS = [
    "customer_id", "sector", "segment", "internal_grade", "risk_rating",
    "rating_bucket", "pd_12m_pct", "revenue_usd_mn", "net_leverage",
    "interest_coverage", "ebitda_margin_pct",
]


@register(AnalysisContract(
    id="rating_grade_distribution",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is the shape of the rating book — how many "
        "customers sit at each grade and what their financials look like."
    ),
    trigger_questions=[
        "What does our rating distribution look like?",
        "How many customers are sub-investment grade?",
        "Show me the grade distribution.",
        "What is the average leverage by grade?",
    ],
    limitations=(
        "Counts customers, not exposure. A grade with few customers can still "
        "carry most of the book, and this analysis will not show that."
    ),
    required_domains=[CUSTOMER_RATING_HISTORY],
    name="Rating Grade Distribution",
    description=(
        "How the rated customer base distributes across internal grades in one "
        "cycle, with the financial ratios that sit behind each grade."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[RATINGS],
    required_fields=GRADE_FIELDS,
    parameters=[YEAR_PARAM],
    outputs=[
        OutputField("customers", "Customers rated.", "integer"),
        OutputField("sub_investment_pct", "Share of customers below investment grade.", "number", unit="%", precision=2),
        OutputField("mean_grade", "Average internal grade.", "number", unit="grade", precision=2),
        OutputField("impaired_customers", "Customers at grade 9 or 10.", "integer"),
    ],
    validation_rules=[
        ValidationRule("grades_within_scale", "Every grade must be between 1 and 10."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Counts customers at each internal grade and reports the median of each "
        "financial ratio within the grade. Medians rather than means, because one "
        "borrower with a leverage of forty would otherwise make a whole grade look "
        "distressed."
    ),
))
def rating_grade_distribution(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, RATINGS, ctx.params.get("period"), None
    )
    df, _ = ctx.read(RATINGS, fields=GRADE_FIELDS, period=period,
                     label=f"Customer ratings · {period}")

    df["internal_grade"] = pd.to_numeric(df["internal_grade"], errors="coerce")
    out_of_scale = int(((df["internal_grade"] < 1) | (df["internal_grade"] > 10)).sum())
    if out_of_scale:
        ctx.warn(f"{out_of_scale:,} customers carry a grade outside the 1-10 scale.")

    grouped = (
        df.groupby("internal_grade", dropna=True)
        .agg(
            customers=("customer_id", "count"),
            risk_rating=("risk_rating", "first"),
            rating_bucket=("rating_bucket", "first"),
            median_pd_pct=("pd_12m_pct", "median"),
            median_leverage=("net_leverage", "median"),
            median_coverage=("interest_coverage", "median"),
            median_margin_pct=("ebitda_margin_pct", "median"),
        )
        .reset_index()
        .sort_values("internal_grade")
    )
    for column in ("median_pd_pct", "median_leverage", "median_coverage",
                   "median_margin_pct"):
        grouped[column] = grouped[column].round(3)

    ctx.step(NodeType.AGGREGATION, f"Group {len(df):,} customers by internal grade",
             config={"group_by": ["internal_grade"],
                     "central_tendency": "median, so one extreme borrower cannot "
                                         "distort a whole grade"},
             rows_in=int(len(df)), rows_out=int(len(grouped)))

    sub_investment = int((df["rating_bucket"] != "Investment grade").sum())

    return AnalysisResult(
        rows=frame_to_rows(grouped),
        values={
            "period": period,
            "customers": int(len(df)),
            "sub_investment_pct": rounded(safe_ratio(sub_investment, len(df)), 2),
            "mean_grade": rounded(float(df["internal_grade"].mean()), 2),
            "impaired_customers": int((df["internal_grade"] >= 9).sum()),
            "periods_available": available,
        },
        units={"median_pd_pct": "%", "median_leverage": "x",
               "median_coverage": "x", "median_margin_pct": "%"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per internal grade.",
              "note": "Counts customers, not exposure."},
    )


# ====================================================== macroeconomic context

MACRO_FIELDS = [
    "period", "real_gdp_growth_pct", "non_oil_gdp_growth_pct",
    "oil_gdp_growth_pct", "brent_usd_bbl", "sama_policy_rate_pct",
    "inflation_pct", "pmi_index", "unemployment_pct",
    "real_estate_price_index", "credit_cycle_factor",
]


@register(AnalysisContract(
    id="macroeconomic_context",
    period_requirement=PeriodRequirement.TIME_SERIES,
    governed_default_period=True,
    answer_shape=AnswerShape.TREND,
    when_to_use=(
        "Use when the question is about the economy the book lends into rather "
        "than the book itself — where the cycle is, and which way it is turning."
    ),
    trigger_questions=[
        "What is the macroeconomic backdrop?",
        "Where are we in the credit cycle?",
        "How has the oil price moved?",
        "What are the macro conditions?",
    ],
    limitations=(
        "Reports the published series. It contains no forecast, and the credit "
        "cycle factor is derived from the series rather than observed anywhere."
    ),
    required_domains=[MACROECONOMIC_SERIES],
    name="Macroeconomic Context",
    description=(
        "The published macroeconomic series across every quarter, with the credit "
        "cycle factor derived from them and the direction it is currently moving."
    ),
    category=Category.REFERENCE,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[MACRO],
    required_fields=MACRO_FIELDS,
    parameters=[
        Parameter("periods", ParamType.INTEGER,
                  "How many of the most recent quarters to return.",
                  default=16, minimum=2, maximum=60),
    ],
    outputs=[
        OutputField("latest_period", "The most recent quarter in the series.", "string"),
        OutputField("credit_cycle_factor", "The cycle factor in that quarter.", "number", unit="z", precision=3),
        OutputField("cycle_direction", "Whether conditions are improving or deteriorating.", "string"),
        OutputField("brent_usd_bbl", "Brent crude in that quarter.", "number", unit="USD/bbl", precision=2),
    ],
    validation_rules=[
        ValidationRule("series_is_ordered",
                       "The series must be returned in chronological order."),
    ],
    supported_visualizations=[VisualizationType.LINE, VisualizationType.TABLE],
    calculation_description=(
        "Reads every published quarter of the macroeconomic series, orders it "
        "chronologically, and takes the most recent N. The direction is the sign "
        "of the change in the credit cycle factor over the last four quarters — a "
        "year, so one soft quarter does not read as a turn."
    ),
))
def macroeconomic_context(ctx: ExecutionContext) -> AnalysisResult:
    wanted = int(ctx.params.get("periods", 16))
    available = ctx.source.periods(MACRO)
    if not available:
        raise ValueError("No macroeconomic series is published.")

    frames = []
    for period in available:
        chunk, _ = ctx.read(MACRO, fields=MACRO_FIELDS, period=period,
                            label=f"Macroeconomic series · {period}")
        frames.append(chunk)
    series = pd.concat(frames, ignore_index=True)

    order = {p: i for i, p in enumerate(available)}
    series["__order"] = series["period"].map(order)
    series = series.sort_values("__order").drop(columns="__order").tail(wanted)

    ctx.step(NodeType.AGGREGATION,
             f"Assemble {len(series)} quarters of macroeconomic series",
             config={"ordering": "chronological, by published period",
                     "requested": wanted, "available": len(available)},
             rows_in=int(len(available)), rows_out=int(len(series)))

    factor = pd.to_numeric(series["credit_cycle_factor"], errors="coerce")
    latest = float(factor.iloc[-1])
    # A year, not a quarter: one soft quarter is noise, four is a direction.
    year_ago = float(factor.iloc[-5]) if len(factor) >= 5 else float(factor.iloc[0])
    change = latest - year_ago
    direction = (
        "Improving" if change > 0.15
        else "Deteriorating" if change < -0.15
        else "Broadly flat"
    )

    return AnalysisResult(
        rows=frame_to_rows(series),
        values={
            "latest_period": str(series["period"].iloc[-1]),
            "credit_cycle_factor": rounded(latest, 3),
            "cycle_change_year": rounded(change, 3),
            "cycle_direction": direction,
            "brent_usd_bbl": rounded(
                float(pd.to_numeric(series["brent_usd_bbl"], errors="coerce").iloc[-1]), 2
            ),
            "policy_rate_pct": rounded(
                float(pd.to_numeric(series["sama_policy_rate_pct"], errors="coerce").iloc[-1]), 2
            ),
            "periods_available": available,
        },
        units={"real_gdp_growth_pct": "%", "non_oil_gdp_growth_pct": "%",
               "oil_gdp_growth_pct": "%", "brent_usd_bbl": "USD/bbl",
               "sama_policy_rate_pct": "%", "inflation_pct": "%",
               "unemployment_pct": "%", "credit_cycle_factor": "z"},
        input_row_count=int(len(series)),
        warnings=ctx.warnings,
        meta={"grain": "One row per calendar quarter.",
              "note": "Published series only. Contains no forecast."},
    )
