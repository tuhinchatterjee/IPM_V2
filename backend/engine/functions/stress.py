"""
Stress testing, and one deliberately non-certified example.

The stress function here is a *management* scenario: the shocks are applied
directly to PD, LGD and exposure, and the ECL is recomputed from them. It is
transparent and arguable in a committee, which is what a management scenario is
for. It is explicitly NOT a regulatory or IFRS 9 lifetime model — that would need
forward-looking macro paths and lifetime PD term structures, and pretending
otherwise would be the kind of overclaim that discredits everything around it.
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
    resolve_periods,
    rounded,
    safe_ratio,
    weighted_average,
)
from backend.engine.registry import AnalysisResult, register
from backend.trace.model import NodeType

OWNER = "Credit Risk Analytics"

STRESS_FIELDS = ["account_id", "customer_id", "ead", "exposure", "undrawn", "total_ecl",
                 "model_ecl", "pd_12m_pct", "lgd_pct", "ifrs9_stage", "sector", "region",
                 "collateral_value"]

# Named presets a committee can argue with, each with its calibration stated.
PRESETS: dict[str, dict] = {
    "base": {
        "label": "Base (no shock)",
        "pd_multiplier": 1.0, "lgd_uplift_pp": 0.0, "ead_uplift_pct": 0.0,
        "stage2_migration_pct": 0.0,
        "rationale": "The reported position, for comparison.",
    },
    "mild": {
        "label": "Mild slowdown",
        "pd_multiplier": 1.25, "lgd_uplift_pp": 2.0, "ead_uplift_pct": 1.0,
        "stage2_migration_pct": 2.0,
        "rationale": "A shallow downturn: PD up a quarter, modest collateral erosion.",
    },
    "moderate": {
        "label": "Moderate downturn",
        "pd_multiplier": 1.75, "lgd_uplift_pp": 5.0, "ead_uplift_pct": 3.0,
        "stage2_migration_pct": 5.0,
        "rationale": "The central management scenario: PD up three quarters, LGD up 5pp, undrawn commitments partly drawn.",
    },
    "severe": {
        "label": "Severe stress",
        "pd_multiplier": 2.5, "lgd_uplift_pp": 10.0, "ead_uplift_pct": 6.0,
        "stage2_migration_pct": 10.0,
        "rationale": "A sharp recession with property-price falls: PD two and a half times, LGD up 10pp.",
    },
}


def _ratio(stressed: pd.Series, base: pd.Series) -> pd.Series:
    """stressed / base, with a factor of 1 where the base is zero.

    A facility with a reported PD of zero cannot be scaled; leaving it unchanged
    is correct and is the only option that does not produce infinity.
    """
    return (stressed / base.replace(0, pd.NA)).fillna(1.0).astype(float)


@register(AnalysisContract(
    id="stress_scenario_basic",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.SCENARIO,
    when_to_use=(
        "Use when the question is what a downturn would do to impairment, applied to the position as reported."
    ),
    trigger_questions=[
        "Stress the portfolio.",
        "What happens under a severe downturn?",
        "Size the impact on Real Estate.",
    ],
    limitations=(
        "A management scenario, not regulatory stress testing. Each facility's reported ECL is scaled by the shock; there is no forward-looking macro path and no lifetime PD term structure."
    ),
    required_domains=[FACILITY_POSITION],
    name="Basic Management Stress Scenario",
    description=(
        "Applies a named or custom shock to PD, LGD and exposure, migrates part of "
        "stage 1 into stage 2, and recomputes ECL and coverage against the reported "
        "position."
    ),
    category=Category.STRESS,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=STRESS_FIELDS,
    parameters=[
        Parameter("period", ParamType.PERIOD, "Reporting period to stress.", default="latest"),
        Parameter("scenario", ParamType.ENUM, "Named preset, or 'custom' to supply your own shocks.",
                  default="moderate", allowed_values=[*PRESETS, "custom"]),
        Parameter("pd_multiplier", ParamType.NUMBER,
                  "Multiply every PD by this. Only used when scenario is 'custom'.",
                  default=1.0, minimum=0.1, maximum=10.0),
        Parameter("lgd_uplift_pp", ParamType.NUMBER,
                  "Add this many percentage points to LGD. Only used when scenario is 'custom'.",
                  default=0.0, minimum=0.0, maximum=60.0),
        Parameter("ead_uplift_pct", ParamType.NUMBER,
                  "Increase exposure by this percentage (undrawn being drawn). Custom only.",
                  default=0.0, minimum=0.0, maximum=50.0),
        Parameter("stage2_migration_pct", ParamType.NUMBER,
                  "Percentage of stage 1 exposure migrated to stage 2. Custom only.",
                  default=0.0, minimum=0.0, maximum=100.0),
        Parameter("sector", ParamType.STRING,
                  "Apply the shock to one sector only. Leave unset for the whole book.",
                  default=None),
    ],
    outputs=[
        OutputField("metric", "Metric name.", "string"),
        OutputField("base", "Reported value before the shock.", "number", unit="SAR mn", precision=2),
        OutputField("stressed", "Value after the shock.", "number", unit="SAR mn", precision=2),
        OutputField("change", "Absolute change.", "number", unit="SAR mn", precision=2),
        OutputField("change_pct", "Percentage change.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("base_matches_reported",
                       "The base ECL must equal the reported ECL for the period."),
        ValidationRule("stress_increases_loss",
                       "A non-zero shock must not reduce ECL.", severity="warning"),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.WATERFALL,
                              VisualizationType.TABLE, VisualizationType.KPI],
    calculation_description=(
        "Each facility's REPORTED ECL is scaled by the severity of the shock:\n"
        "  stressed_ECL = reported_ECL x (stressed_PD / base_PD) "
        "x (stressed_LGD / base_LGD) x (stressed_EAD / base_EAD)\n"
        "where stressed_PD is the reported 12-month PD multiplied by the scenario "
        "factor (capped at 100%), stressed_LGD is the reported LGD plus the uplift "
        "(capped at 100%), and stressed_EAD is exposure grown by the uplift.\n\n"
        "Scaling the booked ECL rather than recomputing it from PD x LGD x EAD is "
        "deliberate. Stage 2 and stage 3 exposures are measured on a LIFETIME "
        "basis, so a 12-month PD x LGD x EAD product would be far below what is "
        "actually provided for, and a mild stress would appear to REDUCE the "
        "impairment. Scaling preserves each facility's own measurement basis and "
        "makes the base scenario reproduce the reported ECL exactly.\n\n"
        "A share of stage 1 exposure is migrated to stage 2 and, moving to a "
        "lifetime basis, carries a higher loss; this is approximated by applying "
        "the PD multiplier a second time to the migrated portion.\n\n"
        "This is a MANAGEMENT scenario, not a regulatory or IFRS 9 lifetime "
        "calculation: it has no forward-looking macro paths and no lifetime PD "
        "term structure."
    ),
))
def stress_scenario_basic(ctx: ExecutionContext) -> AnalysisResult:
    period, _, _ = resolve_periods(ctx.source, FACILITY, ctx.params.get("period"), None)
    scenario = ctx.params.get("scenario") or "moderate"

    if scenario == "custom":
        shocks = {
            "label": "Custom scenario",
            "pd_multiplier": float(ctx.params.get("pd_multiplier") or 1.0),
            "lgd_uplift_pp": float(ctx.params.get("lgd_uplift_pp") or 0.0),
            "ead_uplift_pct": float(ctx.params.get("ead_uplift_pct") or 0.0),
            "stage2_migration_pct": float(ctx.params.get("stage2_migration_pct") or 0.0),
            "rationale": "Shocks supplied directly by the user.",
        }
    else:
        shocks = dict(PRESETS[scenario])

    sector = ctx.params.get("sector")
    if sector:
        ctx.context = ctx.context.with_filters(sector=sector)

    df, _ = ctx.read(FACILITY, fields=STRESS_FIELDS, period=period,
                     label=f"Portfolio facilities · {period}")
    if df.empty:
        raise ValueError(
            f"No facilities to stress for {period}"
            + (f" in sector '{sector}'." if sector else ".")
        )

    work = df.copy()
    for column in ("ead", "pd_12m_pct", "lgd_pct", "total_ecl", "undrawn"):
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0)
    work["ifrs9_stage"] = pd.to_numeric(work["ifrs9_stage"], errors="coerce").fillna(1)

    base_ead = float(work["ead"].sum())
    base_ecl = float(work["total_ecl"].sum())

    ctx.step(NodeType.AGGREGATION, "Reported position",
             config={"measures": ["ead", "total_ecl"], "note": "Base is the ECL actually booked."},
             rows_in=int(len(work)), rows_out=1,
             summary={"base_ead": rounded(base_ead, 2), "base_ecl": rounded(base_ecl, 3)})

    # PD and LGD are percentages in the source data, so they are capped at 100.
    work["stressed_pd"] = (work["pd_12m_pct"] * shocks["pd_multiplier"]).clip(upper=100.0)
    work["stressed_lgd"] = (work["lgd_pct"] + shocks["lgd_uplift_pp"]).clip(upper=100.0)
    work["stressed_ead"] = work["ead"] * (1 + shocks["ead_uplift_pct"] / 100.0)

    # Scale the REPORTED ECL by how much worse each driver got, rather than
    # recomputing ECL from PD x LGD x EAD. Stage 2 and 3 are measured on a
    # lifetime basis; a 12-month product would sit far below what is booked and a
    # mild stress would look like a release. Scaling keeps each facility on its
    # own measurement basis, and a null shock reproduces the reported ECL exactly.
    pd_factor = _ratio(work["stressed_pd"], work["pd_12m_pct"])
    lgd_factor = _ratio(work["stressed_lgd"], work["lgd_pct"])
    ead_factor = _ratio(work["stressed_ead"], work["ead"])
    work["stressed_ecl"] = work["total_ecl"] * pd_factor * lgd_factor * ead_factor

    ctx.step(NodeType.CALCULATION, f"Apply {shocks['label']}",
             config={k: shocks[k] for k in
                     ("pd_multiplier", "lgd_uplift_pp", "ead_uplift_pct", "stage2_migration_pct")}
             | {"formula": "stressed_ECL = reported_ECL x PD factor x LGD factor x EAD factor",
                "basis": "scales the booked ECL, preserving each facility's lifetime or "
                         "12-month measurement basis",
                "rationale": shocks["rationale"]},
             rows_in=int(len(work)), rows_out=int(len(work)),
             summary={"mean_pd_factor": rounded(float(pd_factor.mean()), 4),
                      "mean_lgd_factor": rounded(float(lgd_factor.mean()), 4),
                      "mean_ead_factor": rounded(float(ead_factor.mean()), 4)})

    stage1_mask = work["ifrs9_stage"] == 1
    stage1_ead = float(work.loc[stage1_mask, "stressed_ead"].sum())
    migrated_ead = stage1_ead * shocks["stage2_migration_pct"] / 100.0
    # Migrated exposure moves to a lifetime measurement basis; the PD multiplier
    # is applied a second time to that portion as a transparent approximation.
    migrated_extra_ecl = 0.0
    if migrated_ead > 0 and stage1_ead > 0:
        stage1_ecl = float(work.loc[stage1_mask, "stressed_ecl"].sum())
        share = migrated_ead / stage1_ead
        migrated_extra_ecl = stage1_ecl * share * (shocks["pd_multiplier"] - 1.0)
        ctx.step(NodeType.CALCULATION, "Stage 1 to stage 2 migration",
                 config={"migrated_pct": shocks["stage2_migration_pct"],
                         "basis": "PD multiplier applied a second time to the migrated portion"},
                 summary={"migrated_ead": rounded(migrated_ead, 2),
                          "additional_ecl": rounded(migrated_extra_ecl, 3)})

    stressed_ead = float(work["stressed_ead"].sum())
    stressed_ecl = float(work["stressed_ecl"].sum()) + migrated_extra_ecl

    def line(metric: str, base: float, stressed: float, unit: str = "SAR mn") -> dict:
        return {
            "metric": metric, "base": rounded(base, 3), "stressed": rounded(stressed, 3),
            "change": rounded(stressed - base, 3),
            "change_pct": rounded(safe_ratio(stressed - base, base) if base else 0.0, 2),
            "unit": unit,
        }

    base_coverage = safe_ratio(base_ecl, base_ead)
    stressed_coverage = safe_ratio(stressed_ecl, stressed_ead)
    rows = [
        line("Total EAD", base_ead, stressed_ead),
        line("Total ECL", base_ecl, stressed_ecl),
        line("ECL coverage", base_coverage, stressed_coverage, unit="%"),
        line("Weighted PD", weighted_average(work["pd_12m_pct"], work["ead"]),
             weighted_average(work["stressed_pd"], work["stressed_ead"]), unit="%"),
        line("Weighted LGD", weighted_average(work["lgd_pct"], work["ead"]),
             weighted_average(work["stressed_lgd"], work["stressed_ead"]), unit="%"),
        line("Stage 2 exposure",
             float(work.loc[work["ifrs9_stage"] == 2, "ead"].sum()),
             float(work.loc[work["ifrs9_stage"] == 2, "stressed_ead"].sum()) + migrated_ead),
    ]

    by_sector = (
        work.assign(ecl_increase=work["stressed_ecl"] - work["total_ecl"])
        .groupby("sector", observed=True)
        .agg(ead=("ead", "sum"), base_ecl=("total_ecl", "sum"),
             stressed_ecl=("stressed_ecl", "sum"), ecl_increase=("ecl_increase", "sum"))
        .sort_values("ecl_increase", ascending=False)
        .reset_index()
    )
    sector_rows = [
        {"sector": str(r["sector"]), "ead": rounded(float(r["ead"]), 2),
         "base_ecl": rounded(float(r["base_ecl"]), 3),
         "stressed_ecl": rounded(float(r["stressed_ecl"]), 3),
         "ecl_increase": rounded(float(r["ecl_increase"]), 3)}
        for _, r in by_sector.iterrows()
    ]

    ctx.step(NodeType.RESULT, "Stressed position",
             config={"scenario": scenario, "sector": sector or "all"},
             rows_out=len(rows), preview=pd.DataFrame(rows),
             summary={"base_ecl": rounded(base_ecl, 3), "stressed_ecl": rounded(stressed_ecl, 3),
                      "ecl_increase_pct": rounded(safe_ratio(stressed_ecl - base_ecl, base_ecl), 2)})

    if shocks["pd_multiplier"] > 1.0 and stressed_ecl < base_ecl:
        ctx.warn("The scenario reduced ECL despite an upward PD shock — check the calibration.")

    return AnalysisResult(
        rows=rows,
        values={"period": period, "scenario": scenario, "scenario_label": shocks["label"],
                "rationale": shocks["rationale"], "shocks": shocks, "sector": sector,
                "base_ecl": rounded(base_ecl, 3), "stressed_ecl": rounded(stressed_ecl, 3),
                "ecl_increase": rounded(stressed_ecl - base_ecl, 3),
                "ecl_increase_pct": rounded(safe_ratio(stressed_ecl - base_ecl, base_ecl), 2),
                "base_coverage_pct": rounded(base_coverage, 3),
                "stressed_coverage_pct": rounded(stressed_coverage, 3),
                "by_sector": sector_rows,
                "basis": "Management scenario. Not a regulatory or IFRS 9 lifetime calculation."},
        units={"base": "SAR mn", "stressed": "SAR mn", "change": "SAR mn", "change_pct": "%"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per metric; sector detail in values.by_sector.",
              "weighting": "EAD-weighted PD and LGD; ECL recomputed facility by facility."},
    )


# ============================================================ user-defined example


@register(AnalysisContract(
    id="high_utilisation_watchlist",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.LIST,
    when_to_use=(
        "Use when the question is which facilities are drawing unusually heavily on their committed limits."
    ),
    trigger_questions=[
        "Which facilities are near their limit?",
        "Show high utilisation.",
        "What is fully drawn?",
    ],
    limitations=(
        "Built by a user and not validated by the bank. High utilisation is an early-warning signal, not a default indicator."
    ),
    required_domains=[FACILITY_POSITION],
    name="High Utilisation Watchlist",
    description=(
        "Facilities drawn above a utilisation threshold that are not already on "
        "the watchlist. Built by a user in Engine Builder as an example of a "
        "custom analysis."
    ),
    category=Category.DETECT,
    version="0.1.0",
    owner="Wholesale Credit — Portfolio Team",
    # Deliberately NOT certified: it demonstrates that a user-built analysis runs
    # and is visible in the library, but carries no verification tick until the
    # bank has validated it.
    certification=Certification.USER_DEFINED,
    required_datasets=[FACILITY],
    required_fields=["account_id", "customer_id", "borrower_name", "sector", "ead",
                     "limit_amount", "utilisation_pct", "prev_utilisation_pct",
                     "ifrs9_stage", "watchlist"],
    parameters=[
        Parameter("period", ParamType.PERIOD, "Reporting period.", default="latest"),
        Parameter("threshold_pct", ParamType.NUMBER, "Utilisation threshold, in percent.",
                  default=90.0, minimum=0.0, maximum=100.0),
        Parameter("top_n", ParamType.INTEGER, "How many facilities to return.",
                  default=20, minimum=1, maximum=200),
    ],
    outputs=[
        OutputField("account_id", "Facility identifier.", "string"),
        OutputField("borrower_name", "Borrower name.", "string"),
        OutputField("utilisation_pct", "Current utilisation.", "number", unit="%", precision=1),
        OutputField("utilisation_change_pp", "Change since the prior period.", "number", unit="pp", precision=1),
        OutputField("ead", "Exposure at default.", "number", unit="SAR mn", precision=1),
    ],
    validation_rules=[
        ValidationRule("above_threshold", "Every returned facility must exceed the threshold."),
    ],
    supported_visualizations=[VisualizationType.TABLE, VisualizationType.BAR],
    calculation_description=(
        "Filters to facilities whose utilisation exceeds the threshold and which "
        "are not already flagged on the watchlist, then ranks by exposure. Uses "
        "the prior-period utilisation carried on each row to show the change. "
        "This is a USER DEFINED analysis: it has not been validated or certified "
        "by the bank and carries no verification tick."
    ),
))
def high_utilisation_watchlist(ctx: ExecutionContext) -> AnalysisResult:
    period, _, _ = resolve_periods(ctx.source, FACILITY, ctx.params.get("period"), None)
    threshold = float(ctx.params.get("threshold_pct") or 90.0)
    top_n = int(ctx.params.get("top_n") or 20)

    fields = ["account_id", "customer_id", "borrower_name", "sector", "ead",
              "limit_amount", "utilisation_pct", "prev_utilisation_pct",
              "ifrs9_stage", "watchlist"]
    df, _ = ctx.read(FACILITY, fields=fields, period=period, label=f"Facilities · {period}")

    work = df.copy()
    work["utilisation_pct"] = pd.to_numeric(work["utilisation_pct"], errors="coerce").fillna(0)
    work["prev_utilisation_pct"] = pd.to_numeric(work["prev_utilisation_pct"], errors="coerce").fillna(0)
    work["ead"] = pd.to_numeric(work["ead"], errors="coerce").fillna(0)

    before = len(work)
    selected = work[
        (work["utilisation_pct"] > threshold)
        & (~work["watchlist"].fillna(False).astype(bool))
    ].copy()
    ctx.step(NodeType.FILTER, f"Utilisation above {threshold}% and not on the watchlist",
             config={"threshold_pct": threshold, "exclude": "watchlist"},
             rows_in=before, rows_out=int(len(selected)))

    selected["utilisation_change_pp"] = (
        selected["utilisation_pct"] - selected["prev_utilisation_pct"]
    )
    selected = selected.sort_values("ead", ascending=False).head(top_n)
    ctx.step(NodeType.AGGREGATION, "Rank by exposure",
             config={"sort": "ead descending", "limit": top_n},
             rows_out=int(len(selected)), preview=selected)

    rows = [
        {"account_id": r["account_id"], "customer_id": r["customer_id"],
         "borrower_name": r["borrower_name"], "sector": r["sector"],
         "ead": rounded(float(r["ead"]), 2),
         "limit_amount": rounded(float(pd.to_numeric(r["limit_amount"], errors="coerce") or 0), 2),
         "utilisation_pct": rounded(float(r["utilisation_pct"]), 2),
         "utilisation_change_pp": rounded(float(r["utilisation_change_pp"]), 2),
         "ifrs9_stage": int(pd.to_numeric(r["ifrs9_stage"], errors="coerce") or 0)}
        for _, r in selected.iterrows()
    ]

    return AnalysisResult(
        rows=rows,
        values={"period": period, "threshold_pct": threshold,
                "matched": int(len(selected)),
                "total_ead": rounded(float(selected["ead"].sum()), 2)},
        units={"ead": "SAR mn", "utilisation_pct": "%", "utilisation_change_pp": "pp"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per facility.",
              "certification": "User defined — not validated by the bank."},
    )


__all__ = ["stress_scenario_basic", "high_utilisation_watchlist", "PRESETS"]
