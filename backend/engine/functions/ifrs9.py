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

import pandas as pd

from backend.data_access.catalog import IFRS9_STAGING
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
    STAGING,
    frame_to_rows,
    resolve_periods,
    rounded,
    safe_ratio,
)
from backend.engine.registry import AnalysisResult, register
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
        OutputField("stage2_ead", "Exposure in Stage 2.", "number", unit="USD mn", precision=2),
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
        units={"ead": "USD mn", "share_of_stage2_pct": "%"},
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
        OutputField("deteriorated_ead", "Exposure that moved to a worse stage.", "number", unit="USD mn", precision=2),
        OutputField("cured_ead", "Exposure that moved to a better stage.", "number", unit="USD mn", precision=2),
        OutputField("net_deterioration_ead", "Deteriorated less cured.", "number", unit="USD mn", precision=2),
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
        units={"ead": "USD mn", "total_ecl": "USD mn"},
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
        OutputField("total_ecl", "Total expected credit loss.", "number", unit="USD mn", precision=2),
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
            f"{reconciliation:,.2f} USD mn."
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
        units={"ead": "USD mn", "total_ecl": "USD mn", "model_ecl": "USD mn",
               "macro_overlay": "USD mn", "coverage_pct": "%",
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
        OutputField("at_risk_ead", "Exposure of those facilities.", "number", unit="USD mn", precision=2),
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
        units={"ead": "USD mn", "pd_at_origination_pct": "%", "pd_12m_pct": "%",
               "pd_ratio_to_origination": "x", "distance_to_threshold": "x"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per performing facility approaching the threshold.",
              "note": "Distance to the PD trigger only; other triggers are not measured here."},
    )
