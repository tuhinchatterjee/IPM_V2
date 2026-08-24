"""
Portfolio-level analyses: summary, stage distribution, sector concentration, trend.

Every function here is deterministic: same inputs, same dataset version, same
numbers. None of them takes any input from a language model except validated
parameters that the contract has already checked.

Weighting: portfolio averages are EAD-weighted (see engine/helpers.py). Where a
count view is also meaningful, both are returned explicitly so nobody has to
guess which one they are reading.
"""

from __future__ import annotations

import pandas as pd

from backend.data_access.catalog import FACILITY_POSITION
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
    FACILITY,
    frame_to_rows,
    resolve_periods,
    rounded,
    safe_ratio,
    weighted_average,
)
from backend.engine.registry import AnalysisResult, register
from backend.trace.model import NodeType

OWNER = "Credit Risk Analytics"

PERIOD_PARAM = Parameter(
    "period", ParamType.PERIOD,
    "Reporting period to analyse. Accepts a period label, or 'latest' / 'earliest'.",
    default="latest",
)
GROUP_BY_DIMENSIONS = ["sector", "region", "segment", "product_type", "rating_bucket", "country"]


# ============================================================ portfolio summary

PORTFOLIO_SUMMARY_FIELDS = [
    "account_id", "customer_id", "ead", "exposure", "limit_amount", "undrawn",
    "total_ecl", "model_ecl", "macro_overlay", "collateral_value",
    "ifrs9_stage", "pd_12m_pct", "lgd_pct", "dpd_days", "npl", "watchlist",
    "appetite_breach", "utilisation_pct",
]


@register(AnalysisContract(
    id="portfolio_summary",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.LEVEL,
    when_to_use=(
        "Use when the question is where the book stands right now — its size, its staging, its coverage — rather than what changed."
    ),
    trigger_questions=[
        "What is our current NPL ratio?",
        "Where does the portfolio stand?",
        "What is total exposure and coverage?",
        "Give me the headline position.",
    ],
    limitations=(
        "A position, not an explanation. It reports the movement against the prior period but does not attribute it to any cause."
    ),
    required_domains=[FACILITY_POSITION],
    name="Portfolio Summary",
    description=(
        "Headline position of the book for one reporting period: exposure, limits, "
        "utilisation, ECL and coverage, NPL, stage 2 and 3 share, watchlist and "
        "appetite breaches — with the movement against a comparison period."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=PORTFOLIO_SUMMARY_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("compare_period", ParamType.PERIOD,
                  "Period to compare against. Defaults to the immediately preceding period.",
                  default="previous"),
    ],
    outputs=[
        OutputField("total_ead", "Total exposure at default.", "number", unit="USD mn", precision=1),
        OutputField("total_ecl", "Total expected credit loss.", "number", unit="USD mn", precision=2),
        OutputField("ecl_coverage_pct", "Total ECL as a percentage of EAD.", "number", unit="%", precision=2),
        OutputField("npl_ratio_pct", "Non-performing exposure as a percentage of EAD.", "number", unit="%", precision=2),
        OutputField("stage2_pct", "Stage 2 exposure as a percentage of EAD.", "number", unit="%", precision=2),
        OutputField("stage3_pct", "Stage 3 exposure as a percentage of EAD.", "number", unit="%", precision=2),
        OutputField("weighted_pd_pct", "EAD-weighted 12-month PD.", "number", unit="%", precision=3),
        OutputField("weighted_lgd_pct", "EAD-weighted LGD.", "number", unit="%", precision=2),
        OutputField("facility_count", "Number of facilities.", "integer"),
        OutputField("borrower_count", "Number of distinct borrowers.", "integer"),
    ],
    validation_rules=[
        ValidationRule("stages_reconcile",
                       "Stage 1 + 2 + 3 exposure must equal total EAD."),
        ValidationRule("coverage_non_negative", "ECL coverage cannot be negative."),
    ],
    supported_visualizations=[VisualizationType.KPI, VisualizationType.TABLE],
    calculation_description=(
        "Sums EAD, ECL and limits across all facilities in the period. Coverage is "
        "total ECL / total EAD. PD and LGD are EAD-weighted averages, not simple "
        "means — an unweighted mean would treat a small facility and a very large "
        "one as equally important. Movement is the difference against the "
        "comparison period on the same basis."
    ),
))
def portfolio_summary(ctx: ExecutionContext) -> AnalysisResult:
    period, compare, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("period"), ctx.params.get("compare_period")
    )

    current, _ = ctx.read(FACILITY, fields=PORTFOLIO_SUMMARY_FIELDS, period=period,
                          label=f"Portfolio facilities · {period}")
    metrics = _summarise(current)
    ctx.step(NodeType.AGGREGATION, f"Aggregate {len(current):,} facilities",
             config={"measures": list(metrics), "weighting": "EAD-weighted for PD and LGD"},
             rows_in=int(len(current)), rows_out=1, summary=metrics)

    movement: dict[str, float] = {}
    if compare and compare != period:
        prior, prior_node = ctx.read(FACILITY, fields=PORTFOLIO_SUMMARY_FIELDS, period=compare,
                                     label=f"Portfolio facilities · {compare}",
                                     parents=[ctx.graph.roots()[0] if ctx.graph.roots() else ctx.cursor])
        prior_metrics = _summarise(prior)
        movement = {k: rounded(metrics[k] - prior_metrics.get(k, 0.0), 3) for k in metrics}
        ctx.step(NodeType.CALCULATION, f"Movement {compare} to {period}",
                 parents=[ctx.cursor, prior_node],
                 config={"basis": "current minus comparison, same measures"},
                 summary=movement)
    else:
        ctx.warn(f"No comparison period available before {period}; movement not computed.")

    # Declared validation rule: the stage split must reconcile to the total.
    stage_total = metrics["stage1_ead"] + metrics["stage2_ead"] + metrics["stage3_ead"]
    if abs(stage_total - metrics["total_ead"]) > 0.01:
        ctx.warn(
            f"Stage exposures sum to {stage_total:,.2f} but total EAD is "
            f"{metrics['total_ead']:,.2f} — some facilities have no valid IFRS 9 stage."
        )

    return AnalysisResult(
        rows=[{"metric": k, "value": v, "movement": movement.get(k)} for k, v in metrics.items()],
        values={**metrics, "period": period, "compare_period": compare,
                "movement": movement, "periods_available": available},
        units={"total_ead": "USD mn", "total_ecl": "USD mn", "ecl_coverage_pct": "%",
               "npl_ratio_pct": "%", "stage2_pct": "%", "stage3_pct": "%",
               "weighted_pd_pct": "%", "weighted_lgd_pct": "%"},
        input_row_count=int(len(current)),
        warnings=ctx.warnings,
        meta={"grain": "One row per facility per reporting period.",
              "weighting": "EAD-weighted averages for PD and LGD."},
    )


def _summarise(df: pd.DataFrame) -> dict[str, float]:
    ead = pd.to_numeric(df["ead"], errors="coerce").fillna(0)
    total_ead = float(ead.sum())
    stage = pd.to_numeric(df["ifrs9_stage"], errors="coerce")
    stage_ead = {s: float(ead[stage == s].sum()) for s in (1, 2, 3)}
    npl_ead = float(ead[df["npl"].fillna(False).astype(bool)].sum())
    total_ecl = float(pd.to_numeric(df["total_ecl"], errors="coerce").fillna(0).sum())

    return {
        "total_ead": rounded(total_ead, 2),
        "total_exposure": rounded(float(pd.to_numeric(df["exposure"], errors="coerce").fillna(0).sum()), 2),
        "total_limit": rounded(float(pd.to_numeric(df["limit_amount"], errors="coerce").fillna(0).sum()), 2),
        "total_undrawn": rounded(float(pd.to_numeric(df["undrawn"], errors="coerce").fillna(0).sum()), 2),
        "total_collateral": rounded(float(pd.to_numeric(df["collateral_value"], errors="coerce").fillna(0).sum()), 2),
        "total_ecl": rounded(total_ecl, 3),
        "model_ecl": rounded(float(pd.to_numeric(df["model_ecl"], errors="coerce").fillna(0).sum()), 3),
        "macro_overlay": rounded(float(pd.to_numeric(df["macro_overlay"], errors="coerce").fillna(0).sum()), 3),
        "ecl_coverage_pct": rounded(safe_ratio(total_ecl, total_ead), 3),
        "stage1_ead": rounded(stage_ead[1], 2),
        "stage2_ead": rounded(stage_ead[2], 2),
        "stage3_ead": rounded(stage_ead[3], 2),
        "stage2_pct": rounded(safe_ratio(stage_ead[2], total_ead), 3),
        "stage3_pct": rounded(safe_ratio(stage_ead[3], total_ead), 3),
        "npl_ratio_pct": rounded(safe_ratio(npl_ead, total_ead), 3),
        "weighted_pd_pct": rounded(weighted_average(df["pd_12m_pct"], ead), 4),
        "weighted_lgd_pct": rounded(weighted_average(df["lgd_pct"], ead), 3),
        "weighted_utilisation_pct": rounded(weighted_average(df["utilisation_pct"], ead), 3),
        "watchlist_ead": rounded(float(ead[df["watchlist"].fillna(False).astype(bool)].sum()), 2),
        "appetite_breach_count": float(int(df["appetite_breach"].fillna(False).astype(bool).sum())),
        "facility_count": float(int(len(df))),
        "borrower_count": float(int(df["customer_id"].nunique())),
    }


# =========================================================== stage distribution

STAGE_FIELDS = ["account_id", "customer_id", "ead", "total_ecl", "ifrs9_stage",
                "pd_12m_pct", "lgd_pct"] + GROUP_BY_DIMENSIONS


@register(AnalysisContract(
    id="stage_distribution",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is how exposure and impairment split across IFRS 9 stages, optionally within a dimension."
    ),
    trigger_questions=[
        "How is exposure split across stages?",
        "What is in Stage 2 by sector?",
        "Show the IFRS 9 staging.",
    ],
    limitations=(
        "A snapshot of where exposure sits. It does not show what moved between stages — Stage Migration does that."
    ),
    required_domains=[FACILITY_POSITION],
    name="Stage Distribution",
    description=(
        "How exposure and ECL are split across IFRS 9 stages 1, 2 and 3, both "
        "portfolio-wide and optionally broken down by a dimension such as sector."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=STAGE_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("group_by", ParamType.ENUM,
                  "Optional dimension to break the stage split down by.",
                  default="none", allowed_values=["none", *GROUP_BY_DIMENSIONS]),
    ],
    outputs=[
        OutputField("ifrs9_stage", "IFRS 9 stage (1, 2 or 3).", "integer"),
        OutputField("ead", "Exposure at default in the stage.", "number", unit="USD mn", precision=1),
        OutputField("ead_pct", "Share of total exposure.", "number", unit="%", precision=2),
        OutputField("total_ecl", "ECL held against the stage.", "number", unit="USD mn", precision=2),
        OutputField("coverage_pct", "ECL as a percentage of the stage's EAD.", "number", unit="%", precision=2),
        OutputField("facility_count", "Facilities in the stage.", "integer"),
    ],
    validation_rules=[
        ValidationRule("shares_sum_to_100", "Stage shares must sum to 100%."),
        ValidationRule("stages_valid", "Every row must be stage 1, 2 or 3."),
    ],
    supported_visualizations=[VisualizationType.STACKED_BAR, VisualizationType.PIE,
                              VisualizationType.TABLE],
    calculation_description=(
        "Groups facilities by IFRS 9 stage and sums EAD and ECL. Coverage within a "
        "stage is that stage's ECL divided by its own EAD, not by the portfolio "
        "total — stage 3 coverage of 40% means 40% of stage 3 exposure is provided "
        "for. PD and LGD are EAD-weighted within each stage."
    ),
))
def stage_distribution(ctx: ExecutionContext) -> AnalysisResult:
    period, _, _ = resolve_periods(ctx.source, FACILITY, ctx.params.get("period"), None)
    group_by = ctx.params.get("group_by") or "none"

    df, _ = ctx.read(FACILITY, fields=STAGE_FIELDS, period=period,
                     label=f"Portfolio facilities · {period}")

    total_ead = float(pd.to_numeric(df["ead"], errors="coerce").fillna(0).sum())
    stage_rows = _stage_table(df, total_ead)
    ctx.step(NodeType.AGGREGATION, "Group by IFRS 9 stage",
             config={"group_by": ["ifrs9_stage"], "measures": ["ead", "total_ecl", "count"]},
             rows_in=int(len(df)), rows_out=len(stage_rows),
             preview=pd.DataFrame(stage_rows))

    breakdown: list[dict] = []
    if group_by != "none":
        for value, chunk in df.groupby(group_by, observed=True, dropna=False):
            for row in _stage_table(chunk, float(pd.to_numeric(chunk["ead"], errors="coerce").fillna(0).sum())):
                breakdown.append({group_by: str(value), **row})
        ctx.step(NodeType.AGGREGATION, f"Break down by {group_by}",
                 config={"group_by": [group_by, "ifrs9_stage"]},
                 rows_in=int(len(df)), rows_out=len(breakdown))

    share_total = sum(r["ead_pct"] for r in stage_rows)
    if stage_rows and abs(share_total - 100.0) > 0.1:
        ctx.warn(f"Stage shares sum to {share_total:.2f}% rather than 100% — check for unstaged facilities.")

    return AnalysisResult(
        rows=stage_rows,
        values={"period": period, "total_ead": rounded(total_ead, 2),
                "group_by": group_by, "breakdown": breakdown},
        units={"ead": "USD mn", "total_ecl": "USD mn", "ead_pct": "%", "coverage_pct": "%"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per IFRS 9 stage.", "weighting": "EAD-weighted PD and LGD."},
    )


def _stage_table(df: pd.DataFrame, total_ead: float) -> list[dict]:
    ead = pd.to_numeric(df["ead"], errors="coerce").fillna(0)
    stage = pd.to_numeric(df["ifrs9_stage"], errors="coerce")
    out = []
    for s in (1, 2, 3):
        mask = stage == s
        stage_ead = float(ead[mask].sum())
        stage_ecl = float(pd.to_numeric(df.loc[mask, "total_ecl"], errors="coerce").fillna(0).sum())
        out.append({
            "ifrs9_stage": s,
            "ead": rounded(stage_ead, 2),
            "ead_pct": rounded(safe_ratio(stage_ead, total_ead), 3),
            "total_ecl": rounded(stage_ecl, 3),
            "coverage_pct": rounded(safe_ratio(stage_ecl, stage_ead), 3),
            "weighted_pd_pct": rounded(weighted_average(df.loc[mask, "pd_12m_pct"], ead[mask]), 4),
            "weighted_lgd_pct": rounded(weighted_average(df.loc[mask, "lgd_pct"], ead[mask]), 3),
            "facility_count": int(mask.sum()),
            "borrower_count": int(df.loc[mask, "customer_id"].nunique()),
        })
    return out


# ========================================================= sector concentration

CONCENTRATION_FIELDS = ["account_id", "customer_id", "ead", "total_ecl", "ifrs9_stage",
                        "npl", "sector", "region", "segment", "obligor_group"]


@register(AnalysisContract(
    id="sector_concentration",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.RANKING,
    when_to_use=(
        "Use when the question is where exposure is concentrated, and how good or bad the largest concentrations are."
    ),
    trigger_questions=[
        "Where is the book most concentrated?",
        "What are our largest sectors?",
        "Show exposure by region.",
    ],
    limitations=(
        "Measures size and quality of concentration at a point in time. It says nothing about whether a concentration is getting worse."
    ),
    required_domains=[FACILITY_POSITION],
    name="Sector Concentration",
    description=(
        "Where the book is concentrated: exposure, share, ECL coverage and NPL by "
        "sector, with a Herfindahl-Hirschman index and the largest single-name "
        "exposure inside each sector."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=CONCENTRATION_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("dimension", ParamType.ENUM, "Dimension to measure concentration on.",
                  default="sector", allowed_values=GROUP_BY_DIMENSIONS),
        Parameter("top_n", ParamType.INTEGER, "How many groups to return, largest first.",
                  default=15, minimum=1, maximum=100),
    ],
    outputs=[
        OutputField("sector", "The dimension value.", "string"),
        OutputField("ead", "Exposure at default.", "number", unit="USD mn", precision=1),
        OutputField("ead_pct", "Share of total exposure.", "number", unit="%", precision=2),
        OutputField("coverage_pct", "ECL as a percentage of the group's EAD.", "number", unit="%", precision=2),
        OutputField("npl_pct", "Non-performing share of the group's EAD.", "number", unit="%", precision=2),
        OutputField("largest_obligor_pct", "Largest single borrower as a share of the group.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("shares_sum_to_100", "Group shares must sum to 100% before truncation."),
        ValidationRule("hhi_range", "HHI must lie between 0 and 10,000."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TREEMAP,
                              VisualizationType.TABLE],
    calculation_description=(
        "Sums EAD by the chosen dimension and expresses each group as a share of "
        "the total. The Herfindahl-Hirschman index is the sum of squared "
        "percentage shares across ALL groups (computed before any top-N "
        "truncation, so the index describes the whole book): below 1,500 is "
        "generally read as unconcentrated, above 2,500 as concentrated. The "
        "largest-obligor share shows single-name risk hiding inside a "
        "sector that looks diversified in aggregate."
    ),
))
def sector_concentration(ctx: ExecutionContext) -> AnalysisResult:
    period, _, _ = resolve_periods(ctx.source, FACILITY, ctx.params.get("period"), None)
    dimension = ctx.params.get("dimension") or "sector"
    top_n = int(ctx.params.get("top_n") or 15)

    df, _ = ctx.read(FACILITY, fields=CONCENTRATION_FIELDS, period=period,
                     label=f"Portfolio facilities · {period}")

    df = df.copy()
    df["ead"] = pd.to_numeric(df["ead"], errors="coerce").fillna(0)
    df["total_ecl"] = pd.to_numeric(df["total_ecl"], errors="coerce").fillna(0)
    total_ead = float(df["ead"].sum())

    rows = []
    for value, chunk in df.groupby(dimension, observed=True, dropna=False):
        group_ead = float(chunk["ead"].sum())
        group_ecl = float(chunk["total_ecl"].sum())
        by_obligor = chunk.groupby("customer_id", observed=True)["ead"].sum()
        rows.append({
            dimension: str(value),
            "ead": rounded(group_ead, 2),
            "ead_pct": rounded(safe_ratio(group_ead, total_ead), 3),
            "total_ecl": rounded(group_ecl, 3),
            "coverage_pct": rounded(safe_ratio(group_ecl, group_ead), 3),
            "npl_pct": rounded(safe_ratio(
                float(chunk.loc[chunk["npl"].fillna(False).astype(bool), "ead"].sum()), group_ead), 3),
            "stage3_pct": rounded(safe_ratio(
                float(chunk.loc[pd.to_numeric(chunk["ifrs9_stage"], errors="coerce") == 3, "ead"].sum()),
                group_ead), 3),
            "facility_count": int(len(chunk)),
            "borrower_count": int(chunk["customer_id"].nunique()),
            "largest_obligor_ead": rounded(float(by_obligor.max()) if len(by_obligor) else 0.0, 2),
            "largest_obligor_pct": rounded(
                safe_ratio(float(by_obligor.max()) if len(by_obligor) else 0.0, group_ead), 3),
        })

    rows.sort(key=lambda r: r["ead"], reverse=True)
    # HHI is computed over every group, before truncation — an index describing
    # only the top 15 would understate concentration.
    hhi = rounded(sum(r["ead_pct"] ** 2 for r in rows), 1)
    top_5_pct = rounded(sum(r["ead_pct"] for r in rows[:5]), 3)

    ctx.step(NodeType.AGGREGATION, f"Group by {dimension}",
             config={"group_by": [dimension], "measures": ["ead", "total_ecl", "npl"]},
             rows_in=int(len(df)), rows_out=len(rows), preview=pd.DataFrame(rows))
    ctx.step(NodeType.CALCULATION, "Concentration indices",
             config={"hhi": "sum of squared percentage shares, all groups",
                     "interpretation": "<1500 unconcentrated, >2500 concentrated"},
             summary={"hhi": hhi, "top_5_pct": top_5_pct, "group_count": len(rows)})

    return AnalysisResult(
        rows=rows[:top_n],
        values={"period": period, "dimension": dimension, "total_ead": rounded(total_ead, 2),
                "hhi": hhi, "top_5_pct": top_5_pct, "group_count": len(rows),
                "truncated_to": min(top_n, len(rows))},
        units={"ead": "USD mn", "ead_pct": "%", "coverage_pct": "%", "npl_pct": "%"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": f"One row per {dimension}.",
              "weighting": "Exposure-weighted; counts shown alongside."},
    )


# ============================================================== portfolio trend

TREND_FIELDS = ["account_id", "customer_id", "ead", "total_ecl", "ifrs9_stage", "npl",
                "pd_12m_pct", "lgd_pct", "dpd_days"]


@register(AnalysisContract(
    id="portfolio_trend",
    period_requirement=PeriodRequirement.TIME_SERIES,
    governed_default_period=True,
    answer_shape=AnswerShape.TREND,
    when_to_use=(
        "Use when the question is about direction of travel across several reporting periods rather than a single comparison."
    ),
    trigger_questions=[
        "How has coverage moved over time?",
        "Show the trend in Stage 2.",
        "What has happened over the last few quarters?",
    ],
    limitations=(
        "Shows the path, not the cause. Each point is a portfolio total; it cannot attribute a movement to a sector or a name."
    ),
    required_domains=[FACILITY_POSITION],
    name="Portfolio Trend",
    description=(
        "How the headline metrics have moved across every available reporting "
        "period: exposure, ECL, coverage, stage 2 and 3 shares, NPL and weighted PD."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=TREND_FIELDS,
    parameters=[
        Parameter("n_periods", ParamType.INTEGER,
                  "How many trailing periods to include. 0 means every available period.",
                  default=0, minimum=0, maximum=60),
    ],
    outputs=[
        OutputField("period", "Reporting period.", "string"),
        OutputField("total_ead", "Total exposure at default.", "number", unit="USD mn", precision=1),
        OutputField("total_ecl", "Total expected credit loss.", "number", unit="USD mn", precision=2),
        OutputField("ecl_coverage_pct", "ECL as a percentage of EAD.", "number", unit="%", precision=2),
        OutputField("stage2_pct", "Stage 2 share of EAD.", "number", unit="%", precision=2),
        OutputField("stage3_pct", "Stage 3 share of EAD.", "number", unit="%", precision=2),
        OutputField("npl_ratio_pct", "NPL share of EAD.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("chronological", "Periods must be returned oldest first."),
        ValidationRule("all_periods_present", "Every requested period must produce a row."),
    ],
    supported_visualizations=[VisualizationType.LINE, VisualizationType.AREA,
                              VisualizationType.TABLE],
    calculation_description=(
        "Recomputes the headline metrics independently for each reporting period "
        "and returns them oldest first. Each period is measured on its own "
        "population, so a change reflects both re-measurement of existing "
        "facilities and additions or removals from the book."
    ),
))
def portfolio_trend(ctx: ExecutionContext) -> AnalysisResult:
    _, _, available = resolve_periods(ctx.source, FACILITY, "latest", None)
    n = int(ctx.params.get("n_periods") or 0)
    periods = available[-n:] if n else available

    rows = []
    read_nodes = []
    root = ctx.cursor
    for period in periods:
        df, node = ctx.read(FACILITY, fields=TREND_FIELDS, period=period,
                            label=f"{period}", parents=[root])
        read_nodes.append(node)
        ead = pd.to_numeric(df["ead"], errors="coerce").fillna(0)
        total_ead = float(ead.sum())
        stage = pd.to_numeric(df["ifrs9_stage"], errors="coerce")
        total_ecl = float(pd.to_numeric(df["total_ecl"], errors="coerce").fillna(0).sum())
        rows.append({
            "period": period,
            "total_ead": rounded(total_ead, 2),
            "total_ecl": rounded(total_ecl, 3),
            "ecl_coverage_pct": rounded(safe_ratio(total_ecl, total_ead), 3),
            "stage2_pct": rounded(safe_ratio(float(ead[stage == 2].sum()), total_ead), 3),
            "stage3_pct": rounded(safe_ratio(float(ead[stage == 3].sum()), total_ead), 3),
            "npl_ratio_pct": rounded(safe_ratio(
                float(ead[df["npl"].fillna(False).astype(bool)].sum()), total_ead), 3),
            "weighted_pd_pct": rounded(weighted_average(df["pd_12m_pct"], ead), 4),
            "facility_count": int(len(df)),
            "borrower_count": int(df["customer_id"].nunique()),
        })

    ctx.step(NodeType.AGGREGATION, f"Combine {len(periods)} periods",
             parents=read_nodes,
             config={"periods": periods, "measures": ["total_ead", "total_ecl", "coverage", "stages"]},
             rows_out=len(rows), preview=pd.DataFrame(rows))

    first, last = (rows[0], rows[-1]) if rows else ({}, {})
    change = {
        k: rounded(last.get(k, 0) - first.get(k, 0), 3)
        for k in ("total_ead", "total_ecl", "ecl_coverage_pct", "stage2_pct", "stage3_pct", "npl_ratio_pct")
    } if rows else {}
    if rows:
        ctx.step(NodeType.CALCULATION, f"Change {first['period']} to {last['period']}",
                 config={"basis": "last period minus first period"}, summary=change)

    return AnalysisResult(
        rows=rows,
        values={"periods": periods, "first_period": periods[0] if periods else None,
                "last_period": periods[-1] if periods else None, "change": change},
        units={"total_ead": "USD mn", "total_ecl": "USD mn", "ecl_coverage_pct": "%",
               "stage2_pct": "%", "stage3_pct": "%", "npl_ratio_pct": "%"},
        input_row_count=sum(r["facility_count"] for r in rows),
        warnings=ctx.warnings,
        meta={"grain": "One row per reporting period.",
              "weighting": "EAD-weighted PD; totals are simple sums."},
    )


__all__ = ["portfolio_summary", "stage_distribution", "sector_concentration", "portfolio_trend",
           "frame_to_rows"]
