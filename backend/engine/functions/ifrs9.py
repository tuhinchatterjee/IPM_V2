"""
IFRS 9 impairment analyses, read from the staging table.

The facility book records what stage each facility is IN. The staging table
records WHY — the PD it was written at, each significant-increase trigger
separately, the stage before and after, and the expected credit loss that
follows. These analyses read that, because "Stage 2 rose by 4 points" is a fact
and "Stage 2 rose because covenant breaches doubled" is the answer somebody
actually needs.

Every function is deterministic and takes no input from a language model except
parameters the contract has already validated.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.data_access.catalog import FACILITY_POSITION, IFRS9_STAGING
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
    STAGING,
    frame_to_rows,
    resolve_periods,
    rounded,
    safe_ratio,
)
from backend.engine.registry import AnalysisResult, register
from backend.ifrs9 import decomposition as bridge
from backend.trace.model import NodeType

OWNER = "Credit Risk Analytics"

PERIOD_PARAM = Parameter(
    "period", ParamType.PERIOD,
    "Reporting period to analyse. Accepts a period label, or 'latest' / 'earliest'.",
    default="latest",
)

#: The five triggers the staging table records separately. Named here once so
#: the analyses below and the screens that read them cannot drift apart.
TRIGGERS: list[tuple[str, str]] = [
    ("sicr_pd_trigger", "PD deterioration"),
    ("sicr_dpd_trigger", "Days past due"),
    ("sicr_covenant_trigger", "Covenant breach"),
    ("sicr_rating_trigger", "Rating downgrade"),
    ("sicr_watchlist_trigger", "Watchlist"),
]


# ================================================== what triggered Stage 2

TRIGGER_FIELDS = [
    "account_id", "ead", "ifrs9_stage", "prior_stage", "sector", "segment",
    *[t[0] for t in TRIGGERS], "sicr_any_trigger",
]


@register(AnalysisContract(
    id="sicr_trigger_breakdown",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is WHY facilities are in Stage 2 rather than how many are."
    ),
    trigger_questions=[
        "Why are facilities in Stage 2?",
        "What is driving our significant increase in credit risk?",
        "Which SICR trigger is firing most?",
        "What put these loans on the watchlist?",
    ],
    limitations=(
        "A facility can fire several triggers at once, so the trigger counts sum "
        "to more than the number of facilities. The exposure column is the "
        "exposure of every facility firing that trigger, not a partition of it."
    ),
    required_domains=[IFRS9_STAGING],
    name="SICR Trigger Breakdown",
    description=(
        "Which significant-increase-in-credit-risk triggers are firing across the "
        "book, by count and by exposure, with the share of Stage 2 each accounts "
        "for."
    ),
    category=Category.INVESTIGATE,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[STAGING],
    required_fields=TRIGGER_FIELDS,
    parameters=[PERIOD_PARAM],
    outputs=[
        OutputField("stage2_facilities", "Facilities in Stage 2.", "integer"),
        OutputField("stage2_ead", "Exposure in Stage 2.", "number", unit="SAR mn", precision=2),
        OutputField("leading_trigger", "The trigger firing on the most exposure.", "string"),
        OutputField("multi_trigger_facilities", "Facilities firing more than one trigger.", "integer"),
    ],
    validation_rules=[
        ValidationRule("triggered_implies_stage",
                       "A facility with any trigger active must not be in Stage 1."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Counts each of the five recorded SICR triggers separately and sums the "
        "exposure of the facilities firing it. Because triggers overlap, the "
        "shares are of Stage 2 exposure rather than of one another, and the "
        "number of facilities firing more than one is reported alongside."
    ),
))
def sicr_trigger_breakdown(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, STAGING, ctx.params.get("period"), None
    )
    df, _ = ctx.read(STAGING, fields=TRIGGER_FIELDS, period=period,
                     label=f"IFRS 9 staging · {period}")

    ead = pd.to_numeric(df["ead"], errors="coerce").fillna(0.0)
    stage = pd.to_numeric(df["ifrs9_stage"], errors="coerce")
    stage2 = stage == 2
    stage2_ead = float(ead[stage2].sum())

    fired = pd.DataFrame({label: df[column].fillna(False).astype(bool)
                          for column, label in TRIGGERS})
    rows = []
    for _, label in TRIGGERS:
        mask = fired[label]
        rows.append({
            "trigger": label,
            "facilities": int(mask.sum()),
            "ead": rounded(float(ead[mask].sum()), 2),
            "share_of_stage2_pct": rounded(safe_ratio(float(ead[mask].sum()), stage2_ead), 2),
        })
    rows.sort(key=lambda r: -r["ead"])

    trigger_count = fired.sum(axis=1)
    multi = int((trigger_count > 1).sum())

    ctx.step(NodeType.AGGREGATION, f"Count {len(TRIGGERS)} triggers across {len(df):,} facilities",
             config={"triggers": [label for _, label in TRIGGERS],
                     "overlap": "a facility may fire several; shares are of Stage 2 exposure"},
             rows_in=int(len(df)), rows_out=len(rows),
             summary={"stage2_ead": rounded(stage2_ead, 2), "multi_trigger": multi})

    # Declared rule: anything triggered should have left Stage 1.
    inconsistent = int((df["sicr_any_trigger"].fillna(False).astype(bool) & (stage == 1)).sum())
    if inconsistent:
        ctx.warn(
            f"{inconsistent:,} facilities have a trigger active but are still in "
            "Stage 1. Staging and triggers disagree for those rows."
        )

    return AnalysisResult(
        rows=rows,
        values={
            "period": period,
            "stage2_facilities": int(stage2.sum()),
            "stage2_ead": rounded(stage2_ead, 2),
            "leading_trigger": rows[0]["trigger"] if rows else "",
            "multi_trigger_facilities": multi,
            "periods_available": available,
        },
        units={"ead": "SAR mn", "share_of_stage2_pct": "%"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per SICR trigger.",
              "overlap": "Triggers overlap; counts do not partition the book."},
    )


# =================================================== stage migration flow

FLOW_FIELDS = [
    "account_id", "ead", "ifrs9_stage", "prior_stage", "stage_moved",
    "total_ecl", "sector",
]


@register(AnalysisContract(
    id="stage_migration_flow",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.MATRIX,
    when_to_use=(
        "Use when the question is which way facilities moved between stages in one "
        "quarter, and what that movement cost."
    ),
    trigger_questions=[
        "How many loans moved from Stage 1 to Stage 2?",
        "What migrated into default this quarter?",
        "Show me the stage migration flows.",
        "How much cured back to Stage 1?",
    ],
    limitations=(
        "One quarter's movement, read from the staging record rather than by "
        "comparing two snapshots. Facilities that left the book entirely are not "
        "here, because the staging table has no row for them."
    ),
    required_domains=[IFRS9_STAGING],
    name="Stage Migration Flow",
    description=(
        "Every stage-to-stage movement in one reporting period, by facility count, "
        "exposure and expected credit loss — deteriorations and cures separately."
    ),
    category=Category.INVESTIGATE,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[STAGING],
    required_fields=FLOW_FIELDS,
    parameters=[PERIOD_PARAM],
    outputs=[
        OutputField("moved_facilities", "Facilities that changed stage.", "integer"),
        OutputField("deteriorated_ead", "Exposure that moved to a worse stage.", "number", unit="SAR mn", precision=2),
        OutputField("cured_ead", "Exposure that moved to a better stage.", "number", unit="SAR mn", precision=2),
        OutputField("net_deterioration_ead", "Deteriorated less cured.", "number", unit="SAR mn", precision=2),
    ],
    validation_rules=[
        ValidationRule("flows_reconcile",
                       "Every moved facility must appear in exactly one flow."),
    ],
    supported_visualizations=[VisualizationType.MATRIX, VisualizationType.TABLE],
    calculation_description=(
        "Groups facilities by the stage they held at the previous reporting date "
        "and the stage they hold now, summing exposure and ECL for each pair. A "
        "movement to a higher stage number is a deterioration; a movement to a "
        "lower one is a cure. The net is the difference between the two, which is "
        "the figure that tells you whether the book improved."
    ),
))
def stage_migration_flow(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, STAGING, ctx.params.get("period"), None
    )
    df, _ = ctx.read(STAGING, fields=FLOW_FIELDS, period=period,
                     label=f"IFRS 9 staging · {period}")

    df = df.assign(
        ead=pd.to_numeric(df["ead"], errors="coerce").fillna(0.0),
        total_ecl=pd.to_numeric(df["total_ecl"], errors="coerce").fillna(0.0),
        prior_stage=pd.to_numeric(df["prior_stage"], errors="coerce"),
        ifrs9_stage=pd.to_numeric(df["ifrs9_stage"], errors="coerce"),
    )

    grouped = (
        df.groupby(["prior_stage", "ifrs9_stage"], dropna=True)
        .agg(facilities=("account_id", "count"), ead=("ead", "sum"),
             total_ecl=("total_ecl", "sum"))
        .reset_index()
    )
    grouped["direction"] = grouped.apply(
        lambda r: "Deteriorated" if r["ifrs9_stage"] > r["prior_stage"]
        else "Cured" if r["ifrs9_stage"] < r["prior_stage"] else "Held",
        axis=1,
    )
    grouped["flow"] = grouped.apply(
        lambda r: f"Stage {int(r['prior_stage'])} to Stage {int(r['ifrs9_stage'])}",
        axis=1,
    )
    grouped["ead"] = grouped["ead"].round(2)
    grouped["total_ecl"] = grouped["total_ecl"].round(3)

    ctx.step(NodeType.AGGREGATION, f"Group {len(df):,} facilities by stage before and after",
             config={"group_by": ["prior_stage", "ifrs9_stage"],
                     "measures": ["facilities", "ead", "total_ecl"]},
             rows_in=int(len(df)), rows_out=int(len(grouped)))

    deteriorated = float(grouped.loc[grouped["direction"] == "Deteriorated", "ead"].sum())
    cured = float(grouped.loc[grouped["direction"] == "Cured", "ead"].sum())
    moved = int(grouped.loc[grouped["direction"] != "Held", "facilities"].sum())

    recorded_moves = int(df["stage_moved"].fillna(False).astype(bool).sum())
    if moved != recorded_moves:
        ctx.warn(
            f"The flows account for {moved:,} movements but {recorded_moves:,} "
            "rows are marked as moved. Some rows have no prior stage recorded."
        )

    return AnalysisResult(
        rows=frame_to_rows(
            grouped[["flow", "direction", "facilities", "ead", "total_ecl"]]
            .sort_values(["direction", "ead"], ascending=[True, False])
        ),
        values={
            "period": period,
            "moved_facilities": moved,
            "deteriorated_ead": rounded(deteriorated, 2),
            "cured_ead": rounded(cured, 2),
            "net_deterioration_ead": rounded(deteriorated - cured, 2),
            "periods_available": available,
        },
        units={"ead": "SAR mn", "total_ecl": "SAR mn"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per stage-to-stage flow."},
    )


# ==================================================== coverage adequacy

COVERAGE_FIELDS = [
    "account_id", "ead", "ifrs9_stage", "total_ecl", "model_ecl",
    "macro_overlay", "ecl_coverage_pct", "sector", "segment",
]


@register(AnalysisContract(
    id="ecl_coverage_by_stage",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is whether the provision is adequate for the staging, "
        "or how much of it is management overlay rather than model output."
    ),
    trigger_questions=[
        "What is our ECL coverage by stage?",
        "How much of the provision is overlay?",
        "Is the Stage 3 coverage adequate?",
        "Where is the expected credit loss concentrated?",
    ],
    limitations=(
        "Reports coverage as it stands. It does not judge adequacy: that needs a "
        "loss-given-default view and a recovery assumption this analysis has no "
        "access to."
    ),
    required_domains=[IFRS9_STAGING],
    name="ECL Coverage by Stage",
    description=(
        "Expected credit loss and coverage for each IFRS 9 stage, splitting model "
        "output from management overlay so it is clear how much of the provision "
        "is judgement."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[STAGING],
    required_fields=COVERAGE_FIELDS,
    parameters=[PERIOD_PARAM],
    outputs=[
        OutputField("total_ecl", "Total expected credit loss.", "number", unit="SAR mn", precision=2),
        OutputField("overlay_share_pct", "Management overlay as a share of total ECL.", "number", unit="%", precision=2),
        OutputField("stage3_coverage_pct", "Stage 3 ECL as a percentage of Stage 3 exposure.", "number", unit="%", precision=2),
        OutputField("coverage_pct", "Total ECL as a percentage of total exposure.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("overlay_within_total",
                       "Model ECL plus overlay must equal total ECL."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Sums exposure, model ECL and overlay for each stage, and divides the ECL "
        "by the exposure to give coverage. Coverage is computed on the summed "
        "figures, never as an average of facility-level coverage — averaging "
        "ratios would give a small facility the same weight as a very large one."
    ),
))
def ecl_coverage_by_stage(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, STAGING, ctx.params.get("period"), None
    )
    df, _ = ctx.read(STAGING, fields=COVERAGE_FIELDS, period=period,
                     label=f"IFRS 9 staging · {period}")

    for column in ("ead", "total_ecl", "model_ecl", "macro_overlay"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df["ifrs9_stage"] = pd.to_numeric(df["ifrs9_stage"], errors="coerce")

    grouped = (
        df.groupby("ifrs9_stage", dropna=True)
        .agg(facilities=("account_id", "count"), ead=("ead", "sum"),
             total_ecl=("total_ecl", "sum"), model_ecl=("model_ecl", "sum"),
             macro_overlay=("macro_overlay", "sum"))
        .reset_index()
        .sort_values("ifrs9_stage")
    )
    grouped["coverage_pct"] = grouped.apply(
        lambda r: rounded(safe_ratio(r["total_ecl"], r["ead"]), 3), axis=1
    )
    grouped["overlay_share_pct"] = grouped.apply(
        lambda r: rounded(safe_ratio(r["macro_overlay"], r["total_ecl"]), 3), axis=1
    )
    grouped["stage"] = grouped["ifrs9_stage"].astype(int).map(
        {1: "Stage 1 — performing", 2: "Stage 2 — significant increase",
         3: "Stage 3 — credit impaired"}
    )
    for column in ("ead", "total_ecl", "model_ecl", "macro_overlay"):
        grouped[column] = grouped[column].round(3)

    ctx.step(NodeType.AGGREGATION, f"Aggregate {len(df):,} facilities by stage",
             config={"group_by": ["ifrs9_stage"],
                     "coverage": "summed ECL / summed EAD, never an average of ratios"},
             rows_in=int(len(df)), rows_out=int(len(grouped)))

    total_ecl = float(df["total_ecl"].sum())
    total_ead = float(df["ead"].sum())
    overlay = float(df["macro_overlay"].sum())
    stage3 = grouped[grouped["ifrs9_stage"] == 3]

    reconciliation = float(df["model_ecl"].sum()) + overlay - total_ecl
    if abs(reconciliation) > 0.5:
        ctx.warn(
            f"Model ECL plus overlay differs from total ECL by "
            f"{reconciliation:,.2f} SAR mn."
        )

    return AnalysisResult(
        rows=frame_to_rows(grouped[[
            "stage", "facilities", "ead", "model_ecl", "macro_overlay",
            "total_ecl", "coverage_pct", "overlay_share_pct",
        ]]),
        values={
            "period": period,
            "total_ecl": rounded(total_ecl, 3),
            "total_ead": rounded(total_ead, 2),
            "coverage_pct": rounded(safe_ratio(total_ecl, total_ead), 3),
            "overlay_share_pct": rounded(safe_ratio(overlay, total_ecl), 3),
            "stage3_coverage_pct": (
                float(stage3["coverage_pct"].iloc[0]) if len(stage3) else 0.0
            ),
            "periods_available": available,
        },
        units={"ead": "SAR mn", "total_ecl": "SAR mn", "model_ecl": "SAR mn",
               "macro_overlay": "SAR mn", "coverage_pct": "%",
               "overlay_share_pct": "%"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per IFRS 9 stage."},
    )


# ============================================ approaching the SICR threshold

APPROACHING_FIELDS = [
    "account_id", "customer_id", "sector", "segment", "ead", "ifrs9_stage",
    "pd_at_origination_pct", "pd_12m_pct", "pd_ratio_to_origination",
    "notches_since_origination", "dpd_days",
]


@register(AnalysisContract(
    id="approaching_sicr_threshold",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.RANKING,
    when_to_use=(
        "Use when the question is which performing facilities are closest to "
        "tripping into Stage 2 — before they do, not after."
    ),
    trigger_questions=[
        "Which loans are about to move to Stage 2?",
        "Who is closest to the SICR threshold?",
        "Show me the facilities on the edge of Stage 2.",
        "What is about to trip the significant increase test?",
    ],
    limitations=(
        "Measures distance to the PD-based trigger only. A facility can enter "
        "Stage 2 through days past due, a covenant breach or a rating downgrade "
        "without its PD ratio moving at all."
    ),
    required_domains=[IFRS9_STAGING],
    name="Approaching the SICR Threshold",
    description=(
        "Performing facilities ranked by how close their PD deterioration is to "
        "the significant-increase threshold, with the exposure at stake."
    ),
    category=Category.DETECT,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[STAGING],
    required_fields=APPROACHING_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("top_n", ParamType.INTEGER,
                  "How many facilities to return.", default=20, minimum=1, maximum=200),
        Parameter("threshold", ParamType.NUMBER,
                  "The PD ratio that counts as a significant increase.",
                  default=2.0, minimum=1.1, maximum=10.0),
    ],
    outputs=[
        OutputField("at_risk_facilities", "Performing facilities within reach of the threshold.", "integer"),
        OutputField("at_risk_ead", "Exposure of those facilities.", "number", unit="SAR mn", precision=2),
        OutputField("closest_ratio", "The highest PD ratio still below the threshold.", "number", unit="x", precision=3),
    ],
    validation_rules=[
        ValidationRule("performing_only",
                       "Only Stage 1 facilities may appear; anything above has "
                       "already crossed."),
    ],
    supported_visualizations=[VisualizationType.TABLE, VisualizationType.BAR],
    calculation_description=(
        "Takes performing (Stage 1) facilities only, computes each one's PD "
        "divided by its PD at origination, and ranks those below the threshold by "
        "how close they are to it. 'Within reach' means at least three-quarters of "
        "the way there."
    ),
))
def approaching_sicr_threshold(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, STAGING, ctx.params.get("period"), None
    )
    top_n = int(ctx.params.get("top_n", 20))
    threshold = float(ctx.params.get("threshold", 2.0))

    df, _ = ctx.read(STAGING, fields=APPROACHING_FIELDS, period=period,
                     label=f"IFRS 9 staging · {period}")

    performing = df[pd.to_numeric(df["ifrs9_stage"], errors="coerce") == 1].copy()
    ctx.step(NodeType.FILTER, "Performing facilities only",
             config={"filter": "ifrs9_stage = 1",
                     "reason": "anything above has already crossed the threshold"},
             rows_in=int(len(df)), rows_out=int(len(performing)))

    performing["pd_ratio_to_origination"] = pd.to_numeric(
        performing["pd_ratio_to_origination"], errors="coerce"
    ).fillna(0.0)
    performing["ead"] = pd.to_numeric(performing["ead"], errors="coerce").fillna(0.0)
    performing["distance_to_threshold"] = (
        threshold - performing["pd_ratio_to_origination"]
    ).round(4)

    #: Three-quarters of the way to the threshold. A round fraction, published
    #: rather than tuned, so "within reach" means the same thing every quarter.
    reach = 0.75 * threshold
    at_risk = performing[
        (performing["pd_ratio_to_origination"] >= reach)
        & (performing["pd_ratio_to_origination"] < threshold)
    ].copy()
    ctx.step(NodeType.CALCULATION,
             f"Distance to a PD ratio of {threshold:g}",
             config={"threshold": threshold, "within_reach_from": rounded(reach, 3),
                     "formula": "threshold - (current PD / PD at origination)"},
             rows_in=int(len(performing)), rows_out=int(len(at_risk)),
             summary={"at_risk": int(len(at_risk))})

    ranked = at_risk.sort_values(
        ["distance_to_threshold", "ead"], ascending=[True, False]
    ).head(top_n)

    return AnalysisResult(
        rows=frame_to_rows(ranked[[
            "account_id", "customer_id", "sector", "segment", "ead",
            "pd_at_origination_pct", "pd_12m_pct", "pd_ratio_to_origination",
            "distance_to_threshold", "notches_since_origination", "dpd_days",
        ]]),
        values={
            "period": period,
            "threshold": threshold,
            "at_risk_facilities": int(len(at_risk)),
            "at_risk_ead": rounded(float(at_risk["ead"].sum()), 2),
            "closest_ratio": rounded(
                float(at_risk["pd_ratio_to_origination"].max()) if len(at_risk) else 0.0, 3
            ),
            "performing_facilities": int(len(performing)),
            "periods_available": available,
        },
        units={"ead": "SAR mn", "pd_at_origination_pct": "%", "pd_12m_pct": "%",
               "pd_ratio_to_origination": "x", "distance_to_threshold": "x"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per performing facility approaching the threshold.",
              "note": "Distance to the PD trigger only; other triggers are not measured here."},
    )


# ============================================ ECL change decomposition (P0.4)

DECOMPOSITION_FIELDS = [
    "account_id", "customer_id", "sector", "ifrs9_stage", "ead",
    "pd_12m_pct", "pd_lifetime_pct", "lgd_pct", "model_ecl", "total_ecl",
]


@register(AnalysisContract(
    id="ecl_change_decomposition",
    period_requirement=PeriodRequirement.TWO_PERIOD,
    governed_default_period=True,
    answer_shape=AnswerShape.MOVEMENT,
    when_to_use=(
        "Use when the question is WHAT MOVED the impairment charge, not where "
        "the movement landed. An ECL movement by sector answers a different "
        "question with a similar shape: it reports the result of the change "
        "rather than its drivers."
    ),
    trigger_questions=[
        "Decompose the change in total ECL into exposure, stage migration, PD, "
        "LGD and portfolio mix.",
        "What drove the increase in ECL?",
        "Show me an ECL waterfall.",
        "Bridge the movement in impairment between these two quarters.",
    ],
    limitations=(
        "It does not establish cause: a PD effect says the PDs used in the "
        "calculation changed, not why, and a model recalibration looks "
        "identical to a deteriorating book. The model residual is not split "
        "into discounting, lifetime profile and effective interest rate — "
        "those move together and are reported as one driver. The overlay is "
        "attributed rather than explained, an overlay being a judgement. "
        "Accounts present in only one period are their own components and are "
        "not given driver effects, because an account with one PD has no PD "
        "change."
    ),
    required_domains=[IFRS9_STAGING],
    name="ECL Change Decomposition",
    description=(
        "Opening ECL to closing ECL through exposure, portfolio mix, stage "
        "migration, PD, LGD, the model residual and the overlay — attributed "
        "by Shapley value, so the result does not depend on the order the "
        "drivers are considered in, and reconciling exactly to the movement."
    ),
    category=Category.INVESTIGATE,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[STAGING],
    required_fields=DECOMPOSITION_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("compare_period", ParamType.PERIOD,
                  "The opening period the movement is measured from.",
                  default="earliest"),
    ],
    outputs=[
        OutputField("opening_total", "Total ECL at the opening period.",
                    "number", unit="SAR mn", precision=2),
        OutputField("closing_total", "Total ECL at the closing period.",
                    "number", unit="SAR mn", precision=2),
        OutputField("movement", "Closing ECL less opening ECL.", "number",
                    unit="SAR mn", precision=2),
        OutputField("attributed", "The component effects, summed.", "number",
                    unit="SAR mn", precision=2),
        OutputField("reconciles",
                    "Whether the components sum to the movement.", "boolean"),
        OutputField("largest_driver", "The component with the largest effect.",
                    "string"),
    ],
    validation_rules=[
        ValidationRule("components_reconcile",
                       "The component effects must sum to closing ECL less "
                       "opening ECL, within tolerance."),
        ValidationRule("order_neutral",
                       "The attribution must not depend on the order the "
                       "drivers are considered in."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Per account, over the population present in both periods, modelled "
        "ECL is factorised as T x w x R x PD12 x LGD x K — total exposure, the "
        "account's share of it, the lifetime multiple its stage applies, the "
        "twelve-month PD, loss given default, and a residual carrying "
        "everything else the model does. The change is attributed across those "
        "six by Shapley value: each effect is the factor's average marginal "
        "contribution over every ordering. The overlay is additive and "
        "attributed directly, and accounts present in only one period are "
        "their own components."
    ),
))
def ecl_change_decomposition(ctx: ExecutionContext) -> AnalysisResult:
    from backend.orchestration import decomposition as dc

    closing, opening, available = resolve_periods(
        ctx.source, STAGING, ctx.params.get("period"),
        ctx.params.get("compare_period"))
    if not opening or opening == closing:
        raise ValueError(
            "An ECL decomposition compares two periods. Name the opening "
            "period as well as the closing one.")

    before, _ = ctx.read(STAGING, fields=DECOMPOSITION_FIELDS, period=opening,
                         label=f"IFRS 9 staging · {opening}")
    after, _ = ctx.read(STAGING, fields=DECOMPOSITION_FIELDS, period=closing,
                        label=f"IFRS 9 staging · {closing}")

    found = dc.decompose(
        [dc.account_from(r) for r in before.to_dict("records")],
        [dc.account_from(r) for r in after.to_dict("records")],
        opening_period=opening, closing_period=closing)
    if found.unavailable:
        raise ValueError(f"The ECL movement could not be attributed: "
                         f"{found.unavailable}.")

    ctx.step(NodeType.CALCULATION,
             f"Shapley attribution across {len(dc.FACTORS)} factors",
             config={"factors": list(dc.FACTORS),
                     "formulas": dc.formulas(),
                     "rule": ("Each effect is the factor's average marginal "
                              "contribution over every ordering, so no "
                              "interaction term is handed to whichever factor "
                              "moved last.")},
             rows_in=int(len(before) + len(after)),
             rows_out=len(found.components),
             summary={"matched": found.matched, "arrived": found.arrived,
                      "departed": found.departed})

    # The declared rule, checked rather than asserted. An attribution that
    # stopped reconciling would otherwise be a table of plausible numbers.
    if not found.reconciles:
        ctx.warn(
            f"The components do not reconcile: they sum to "
            f"{found.attributed:,.4f} against a movement of "
            f"{found.movement:,.4f}. This result is NOT a complete "
            "decomposition of the change.")

    rows = [{"component": c.label,
             "effect": rounded(c.effect, 4),
             "share_of_movement_pct": rounded(c.share_of(found.movement), 2),
             "direction": "adverse" if c.adverse else "favourable"}
            for c in sorted(found.components, key=lambda x: -abs(x.effect))]

    largest = found.material[0].label if found.material else ""
    published_opening = rounded(found.opening_total, 2)
    published_closing = rounded(found.closing_total, 2)
    return AnalysisResult(
        rows=rows,
        values={
            "period": closing, "compare_period": opening,
            # Publish first, then subtract. Rounding the two totals and the
            # movement independently left the three figures on the screen
            # disagreeing with each other by a cent — 12,411.65 less 5,313.07
            # shown beside a movement of -7,098.57 — and a reader who checks
            # the arithmetic in front of them is right to stop trusting the
            # table. `attributed` and `reconciles` stay on the unrounded
            # basis: they are a claim about the METHOD, not the presentation.
            "opening_total": published_opening,
            "closing_total": published_closing,
            "movement": rounded(published_closing - published_opening, 2),
            "attributed": rounded(found.attributed, 4),
            "reconciles": found.reconciles,
            "largest_driver": largest,
            "matched_accounts": found.matched,
            "new_accounts": found.arrived,
            "exited_accounts": found.departed,
            "periods_available": available,
        },
        units={"effect": "SAR mn", "share_of_movement_pct": "%"},
        input_row_count=int(len(before) + len(after)),
        warnings=ctx.warnings,
        meta={"grain": "One row per driver of the movement.",
              "waterfall": found.waterfall(),
              "sectors": [c.to_dict() for c in found.sectors],
              "customers": [c.to_dict() for c in found.customers],
              "proves": found.proves(),
              "does_not_prove": found.does_not_prove()},
    )


# ============================================ the IFRS 9 ECL step bridge

#: The facility and staging columns the bridge reads. Declared here as the
#: contract's required fields; the engine module owns the authoritative list.
BRIDGE_FACILITY_FIELDS = list(bridge.FACILITY_FIELDS)
BRIDGE_STAGING_FIELDS = list(bridge.STAGING_FIELDS)


@register(AnalysisContract(
    id="ecl_decomposition",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.MOVEMENT,
    when_to_use=(
        "Use when the question is HOW the reported provision is built up from "
        "its governed inputs at one reporting date — a bridge from a flat "
        "through-the-cycle baseline to the reported ECL, one input replaced at "
        "a time. This is not the ECL total, not a split of ECL by sector or "
        "stage, and not the movement between two quarters: 'what drove the "
        "CHANGE in ECL since Q1' is the two-period ECL Change Decomposition."
    ),
    trigger_questions=[
        "Give me an ECL decomposition.",
        "Show me the ECL bridge.",
        "Show me the ECL waterfall.",
        "Decompose ECL into its components.",
        "What drives our expected credit loss?",
        "What drove ECL this quarter?",
        "How is our ECL built up?",
        "Break down how ECL is built up.",
        "Walk me through the ECL build-up from PD, staging and collateral.",
    ],
    limitations=(
        "A build-up at one reporting date, not a movement between two. Each "
        "step is the effect of replacing one governed input while everything "
        "before it stays as the previous step left it, so the steps are "
        "ORDER-DEPENDENT by construction — that is what makes them a bridge "
        "rather than an attribution, and a different order would give "
        "different step sizes with the same start and end. It does not "
        "establish cause: a large point-in-time step says the current PDs sit "
        "above the through-the-cycle ones, not why. This installation governs "
        "no PD calibration artefact and no separately treated non-calibrated "
        "portfolio, so those two steps are omitted rather than estimated, and "
        "the omission is reported."
    ),
    required_domains=[FACILITY_POSITION, IFRS9_STAGING],
    name="ECL Decomposition",
    description=(
        "The reported expected credit loss built up in six governed steps — a "
        "flat through-the-cycle baseline, the rating distribution, the "
        "point-in-time and forward-looking view, IFRS 9 staging, collateral "
        "and loss given default, and the management overlay — each step "
        "re-measuring every facility, reconciling to the reported provision."
    ),
    category=Category.INVESTIGATE,
    version=bridge.DECOMPOSITION_VERSION,
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY, STAGING],
    required_fields=sorted({*BRIDGE_FACILITY_FIELDS, *BRIDGE_STAGING_FIELDS}),
    parameters=[
        PERIOD_PARAM,
        Parameter("segment", ParamType.STRING,
                  "Restrict the bridge to one configured segment."),
        Parameter("sector", ParamType.STRING,
                  "Restrict the bridge to one sector."),
        Parameter("contributors_for", ParamType.ENUM,
                  "Return the borrowers behind one step instead of the six "
                  "portfolio steps. The bridge is computed identically; only "
                  "what is published changes, so the rows sum to that step's "
                  "impact exactly. 'largest' takes the step with the biggest "
                  "absolute impact.",
                  allowed_values=[*bridge.STEP_ORDER, "largest"]),
        Parameter("limit", ParamType.INTEGER,
                  "How many borrowers a drill-down returns.",
                  default=15, minimum=1, maximum=200),
    ],
    outputs=[
        OutputField("baseline_ecl",
                    "ECL at the flat through-the-cycle baseline.", "number",
                    unit="SAR mn", precision=2),
        OutputField("final_ecl", "ECL after the final step.", "number",
                    unit="SAR mn", precision=2),
        OutputField("reported_ecl", "The reported provision for the period.",
                    "number", unit="SAR mn", precision=2),
        OutputField("residual", "Reported less the final step.", "number",
                    unit="SAR mn", precision=4),
        OutputField("reconciles",
                    "Whether the bridge lands on the reported provision.",
                    "boolean"),
        OutputField("largest_step",
                    "The step with the largest absolute impact.", "string"),
        OutputField("overlay_impact", "The management overlay, on its own.",
                    "number", unit="SAR mn", precision=2),
    ],
    validation_rules=[
        ValidationRule("bridge_reconciles",
                       "The final step must equal the reported provision "
                       "within the governed tolerance."),
        ValidationRule("steps_are_additive",
                       "Each step impact must equal that step's ECL less the "
                       "previous step's, and the impacts must sum to the "
                       "final ECL less the baseline."),
        ValidationRule("borrower_contributions_sum",
                       "Every step impact must equal the sum of its "
                       "borrower-level contributions."),
    ],
    supported_visualizations=[VisualizationType.WATERFALL,
                              VisualizationType.TABLE],
    calculation_description=(
        "Every facility is measured six times with the same arithmetic — "
        "exposure x loss rate x the applicable probability of default — with "
        "exactly one governed input replaced at each step. Step 1 holds every "
        "facility at one through-the-cycle PD (the unweighted mean, the "
        "average credit quality of the book) and the exposure-weighted "
        "portfolio LGD. Step 2 replaces the flat PD with each facility's "
        "rating-grade through-the-cycle PD, exposure-weighted within the "
        "grade. Step 3 replaces through-the-cycle with the governed "
        "point-in-time PD, which carries the forward-looking and "
        "scenario-weighted view. Step 4 applies the IFRS 9 measurement basis: "
        "twelve-month PD in Stage 1, lifetime PD in Stage 2, the "
        "credit-impaired treatment in Stage 3. Step 5 replaces the portfolio "
        "LGD with each facility's own, which carries its collateral. Step 6 "
        "adds the governed management overlay. Because only one term moves "
        "per step, the difference between two steps is attributable to that "
        "term and to nothing else, and the bridge adds up without a plug."
    ),
))
def ecl_decomposition(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("period"), None)

    facility, facility_node = ctx.read(
        FACILITY, fields=BRIDGE_FACILITY_FIELDS, period=period,
        label=f"Facility book · {period}")
    staging, staging_node = ctx.read(
        STAGING, fields=BRIDGE_STAGING_FIELDS, period=period,
        label=f"IFRS 9 staging · {period}")

    filters = {name: str(value)
               for name in ("segment", "sector")
               if (value := ctx.params.get(name))}
    book = bridge.join_book(facility, staging, filters=filters)

    ctx.step(NodeType.JOIN,
             "Join the facility book to its staging record on account_id",
             parents=[facility_node, staging_node],
             config={"key": "account_id", "how": "inner",
                     "ttc_source": bridge.TTC_COLUMN,
                     "pit_source": bridge.PIT_COLUMN,
                     "filters": filters or "none",
                     "why": ("The through-the-cycle anchor lives on the "
                             "staging record and the measurement inputs on "
                             "the facility, so the bridge needs both.")},
             rows_in=int(len(facility) + len(staging)), rows_out=int(len(book)))

    if book.empty:
        raise ValueError(
            "No facilities match that population, so there is nothing to "
            "decompose.")

    built = bridge.build(book, period=period, filters=filters)

    ctx.step(NodeType.CALCULATION,
             f"Measure {built.facilities:,} facilities at each of "
             f"{len(built.steps)} governed steps",
             config={
                 "steps": [{"step": s.number, "name": s.name,
                            "changes": s.description} for s in built.steps],
                 "formula": ("ECL = EAD x LGD x PD, with exactly one input "
                             "replaced per step"),
                 "flat_ttc_pd_pct": rounded(
                     built.assumptions["flat_ttc_pd_pct"], 4),
                 "flat_lgd_pct": rounded(built.assumptions["flat_lgd_pct"], 4),
                 "staging_basis": {
                     "Stage 1": "12-month PD",
                     "Stage 2": "Lifetime PD",
                     "Stage 3": "credit-impaired treatment"},
                 "omitted": [dict(o) for o in built.omitted],
                 "order": ("The steps are order-dependent by construction: "
                           "each measures the effect of one input given "
                           "everything before it."),
             },
             rows_in=int(len(book)), rows_out=len(built.steps),
             summary={s.name: rounded(s.ecl, 3) for s in built.steps})

    ctx.step(NodeType.AGGREGATION,
             f"Roll {built.borrowers:,} borrowers up to the portfolio bridge",
             config={"grain_in": "facility", "grain_out": "bridge step",
                     "borrower_rows": int(len(built.contributions)),
                     "why": ("Every step is computed per facility first, so a "
                             "step impact can be traced to the borrowers that "
                             "produced it.")},
             rows_in=int(len(book)), rows_out=len(built.steps))

    reconciliation = built.reconciliation
    ctx.step(NodeType.RECONCILIATION,
             "Reconcile the final step to the reported provision",
             config={"rule": "bridge_reconciles",
                     "tolerance_pct": reconciliation.tolerance_pct,
                     "reported_source": "portfolio_facility.total_ecl"},
             summary=reconciliation.to_dict())

    if not reconciliation.reconciles:
        ctx.warn(
            f"The bridge does not reconcile: the final step is "
            f"{reconciliation.final_step_ecl:,.3f} against a reported "
            f"provision of {reconciliation.reported_ecl:,.3f}, a residual of "
            f"{reconciliation.residual:,.4f}. This result is NOT a complete "
            "decomposition of the reported ECL.")

    impacts = [s for s in built.steps if s.number > 1]
    largest = max(impacts, key=lambda s: abs(s.impact)) if impacts else None
    overlay = built.step(bridge.OVERLAY)

    # A drill-down publishes the borrowers behind ONE step. The bridge above
    # was computed identically either way, so the rows on screen come out of
    # the same calculation as the portfolio figure they explain — which is the
    # whole reason a drill-down is worth having rather than a fresh ranking
    # that happens to share a subject.
    drilled = _drill_step(built, ctx.params.get("contributors_for"), largest)
    if drilled is not None:
        return _contributor_result(ctx, built, drilled,
                                   limit=int(ctx.params.get("limit") or 15),
                                   period=period, available=available,
                                   read_rows=int(len(book)))

    rows = built.rows()

    units = {"ecl": built.unit, "step_impact": built.unit, "change_pct": "%"}
    units.update({key: built.unit for key in rows[0]
                  if key.endswith("_ecl")} if rows else {})

    return AnalysisResult(
        rows=rows,
        values={
            "period": period,
            "baseline_ecl": rounded(built.steps[0].ecl, 2),
            "final_ecl": rounded(built.final.ecl, 2),
            "reported_ecl": rounded(reconciliation.reported_ecl, 2),
            "residual": rounded(reconciliation.residual, 4),
            "reconciles": reconciliation.reconciles,
            "largest_step": largest.name if largest else "",
            "largest_step_impact": rounded(largest.impact, 2) if largest else 0.0,
            "overlay_impact": rounded(overlay.impact, 2) if overlay else 0.0,
            "facilities": built.facilities,
            "borrowers": built.borrowers,
            "segments": list(built.segments),
            "periods_available": available,
        },
        units=units,
        input_row_count=int(len(book)),
        warnings=ctx.warnings,
        meta={
            "grain": "One row per step of the ECL bridge.",
            "decomposition": built.to_dict(),
            "waterfall": _bridge_waterfall(built),
            "contributors": {
                key: frame_to_rows(bridge.contributors(built, key, limit=10))
                for key in bridge.STEP_ORDER[1:]},
            "omitted_steps": [dict(o) for o in built.omitted],
            "reconciliation": reconciliation.to_dict(),
            "assumptions": {k: rounded(v, 4)
                            for k, v in built.assumptions.items()},
        },
    )


def _drill_step(built: bridge.Bridge, requested: Any,
                largest: bridge.Step | None) -> bridge.Step | None:
    """Which step a drill-down was asked for, or None if it was not a drill.

    "largest" is resolved against the bridge that has just run rather than
    against a remembered answer, so the step the reading names is the step
    whose borrowers are listed.
    """
    if not requested:
        return None
    if str(requested) == "largest":
        return largest
    return built.step(str(requested))


def _contributor_result(ctx: ExecutionContext, built: bridge.Bridge,
                        step: bridge.Step, *, limit: int, period: str,
                        available: list[str],
                        read_rows: int) -> AnalysisResult:
    """The borrowers behind one step, out of the bridge's own calculation."""
    frame = bridge.contributors(built, step.key, limit=limit)
    rows = frame_to_rows(frame)
    total = float(built.contributions[f"impact_{step.key}"].sum())
    shown = float(frame[f"impact_{step.key}"].sum()) if len(frame) else 0.0

    ctx.step(NodeType.AGGREGATION,
             f"Read the borrowers behind step {step.number}: {step.name}",
             config={"step": step.key, "step_number": step.number,
                     "grain": "one row per borrower",
                     "ordered_by": f"|impact_{step.key}| descending",
                     "population": f"{built.borrowers:,} borrowers, "
                                   f"{built.facilities:,} facilities",
                     "period": period,
                     "filters": built.filters or "none",
                     "rule": ("These are the same per-facility measurements "
                              "the portfolio step was summed from, so the "
                              "borrower impacts sum to the step impact "
                              "exactly.")},
             rows_in=int(len(built.contributions)), rows_out=len(rows),
             summary={"step_impact": rounded(step.impact, 3),
                      "shown_impact": rounded(shown, 3)})

    if abs(total - step.impact) > 1e-6:
        ctx.warn(
            f"The borrower contributions for {step.name} sum to "
            f"{total:,.4f} against a step impact of {step.impact:,.4f}. This "
            "drill-down does not account for the step.")

    return AnalysisResult(
        rows=rows,
        values={
            "period": period,
            "step": step.number,
            "step_key": step.key,
            "step_name": step.name,
            "step_impact": rounded(step.impact, 3),
            "step_ecl": rounded(step.ecl, 3),
            "shown_impact": rounded(shown, 3),
            "shown_share_pct": rounded(safe_ratio(shown, step.impact), 2),
            "borrowers": built.borrowers,
            "facilities": built.facilities,
            "reported_ecl": rounded(built.reconciliation.reported_ecl, 2),
            "periods_available": available,
        },
        units={f"impact_{step.key}": built.unit, f"ecl_{step.key}": built.unit,
               "ead": built.unit, "reported_ecl": built.unit,
               "shown_share_pct": "%"},
        input_row_count=read_rows,
        warnings=ctx.warnings,
        meta={"grain": "One row per borrower.",
              "drilled_into": {"step": step.number, "key": step.key,
                               "name": step.name, "detail": step.description,
                               "impact": rounded(step.impact, 3)},
              "decomposition": built.to_dict(),
              "reconciliation": built.reconciliation.to_dict()},
    )


def _bridge_waterfall(built: bridge.Bridge) -> list[dict[str, object]]:
    """The chart, read off the same step values the table publishes.

    Built here rather than in the frontend so the two cannot disagree: a chart
    that recomputes its own bars is a second answer.
    """
    bars: list[dict[str, object]] = []
    running = 0.0
    for step in built.steps:
        first_or_last = step.number in (1, len(built.steps))
        value = step.ecl if first_or_last else step.impact
        bars.append({
            "label": step.name,
            "step": step.number,
            "kind": "total" if first_or_last else "delta",
            "value": rounded(value, 3),
            "start": rounded(0.0 if first_or_last else running, 3),
            "end": rounded(step.ecl, 3),
        })
        running = step.ecl
    return bars
