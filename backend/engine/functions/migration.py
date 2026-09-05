"""
Movement analyses: stage migration, DPD migration, rating transition, ECL
movement, and top deteriorating borrowers.

All of these work by joining the same facility to itself across two reporting
periods. That is only possible because the source data carries a stable
`account_id` in every period — so migration here is genuinely *measured*, not
inferred from a single snapshot's "previous rating" column.

Facilities present in only one of the two periods are reported separately as
entries and exits rather than being silently dropped. A migration matrix that
quietly excludes new business overstates stability.
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
    DPD_BUCKETS,
    FACILITY,
    dpd_bucket,
    order_ratings,
    rating_sort_key,
    resolve_periods,
    rounded,
    safe_ratio,
)
from backend.engine.registry import AnalysisResult, register
from backend.trace.model import NodeType

OWNER = "Credit Risk Analytics"

FROM_PARAM = Parameter(
    "from_period", ParamType.PERIOD,
    "Opening period. Accepts a period label, or 'earliest' / 'previous'.",
    default="previous",
)
TO_PARAM = Parameter(
    "to_period", ParamType.PERIOD,
    "Closing period. Accepts a period label, or 'latest'.",
    default="latest",
)
BASIS_PARAM = Parameter(
    "basis", ParamType.ENUM,
    "Whether the matrix is measured by exposure or by number of facilities.",
    default="ead", allowed_values=["ead", "count"],
)


def _read_pair(ctx: ExecutionContext, fields: list[str], from_period: str, to_period: str
               ) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Read the same dataset at two periods, as two branches of the trace."""
    root = ctx.cursor
    opening, opening_node = ctx.read(FACILITY, fields=fields, period=from_period,
                                     label=f"Opening · {from_period}", parents=[root])
    closing, closing_node = ctx.read(FACILITY, fields=fields, period=to_period,
                                     label=f"Closing · {to_period}", parents=[root])
    return opening, closing, [opening_node, closing_node]


def _join_periods(ctx: ExecutionContext, opening: pd.DataFrame, closing: pd.DataFrame,
                  branches: list[str], key: str = "account_id") -> tuple[pd.DataFrame, dict]:
    """Inner-join two periods on the facility key, reporting what did not match."""
    merged = opening.merge(closing, on=key, suffixes=("_from", "_to"), how="inner")
    coverage = {
        "opening_rows": int(len(opening)),
        "closing_rows": int(len(closing)),
        "matched": int(len(merged)),
        "exits": int(len(opening) - len(merged)),
        "entries": int(len(closing) - len(merged)),
    }
    ctx.step(NodeType.TRANSFORMATION, f"Join on {key}", parents=branches,
             config={"join_key": key, "join_type": "inner",
                     "note": "Unmatched facilities are reported as entries and exits, not dropped silently."},
             rows_in=coverage["opening_rows"] + coverage["closing_rows"],
             rows_out=coverage["matched"], summary=coverage)
    if coverage["matched"] == 0:
        ctx.warn("No facilities are present in both periods — a migration matrix cannot be produced.")
    return merged, coverage


def _matrix(merged: pd.DataFrame, from_col: str, to_col: str, categories: list,
            basis: str) -> tuple[list[dict], dict]:
    """Build a transition matrix with row percentages.

    Row percentages, not whole-matrix percentages: the question a credit officer
    asks is "of what started in stage 1, where did it go?", which is a
    conditional distribution across each row.
    """
    weight = (
        pd.to_numeric(merged["ead_from"], errors="coerce").fillna(0)
        if basis == "ead" and "ead_from" in merged.columns
        else pd.Series(1.0, index=merged.index)
    )
    rows: list[dict] = []
    totals: dict = {}
    for origin in categories:
        mask_from = merged[from_col].astype(str) == str(origin)
        row_total = float(weight[mask_from].sum())
        totals[str(origin)] = rounded(row_total, 3)
        for destination in categories:
            mask = mask_from & (merged[to_col].astype(str) == str(destination))
            value = float(weight[mask].sum())
            rows.append({
                "from": str(origin),
                "to": str(destination),
                "value": rounded(value, 3),
                "row_pct": rounded(safe_ratio(value, row_total), 3),
                "facility_count": int(mask.sum()),
            })
    return rows, totals


def _movement_split(rows: list[dict], order: dict[str, int]) -> dict[str, float]:
    """Split a matrix into improved / stable / deteriorated, by exposure."""
    improved = stable = deteriorated = 0.0
    for r in rows:
        a, b = order.get(r["from"], 0), order.get(r["to"], 0)
        if b > a:
            deteriorated += r["value"]
        elif b < a:
            improved += r["value"]
        else:
            stable += r["value"]
    total = improved + stable + deteriorated
    return {
        "improved": rounded(improved, 3),
        "stable": rounded(stable, 3),
        "deteriorated": rounded(deteriorated, 3),
        "improved_pct": rounded(safe_ratio(improved, total), 3),
        "stable_pct": rounded(safe_ratio(stable, total), 3),
        "deteriorated_pct": rounded(safe_ratio(deteriorated, total), 3),
    }


# ============================================================= stage migration

STAGE_MIG_FIELDS = ["account_id", "customer_id", "ead", "total_ecl", "ifrs9_stage", "sector"]


@register(AnalysisContract(
    id="stage_migration",
    period_requirement=PeriodRequirement.TWO_PERIOD,
    governed_default_period=False,
    answer_shape=AnswerShape.MOVEMENT,
    when_to_use=(
        "Use when the question is which exposure moved between IFRS 9 stages, and in which direction, between two dates."
    ),
    trigger_questions=[
        "What moved into Stage 2?",
        "Show stage migration.",
        "How much exposure deteriorated a stage?",
    ],
    limitations=(
        "Measures gross movement between stages for facilities present in both periods. Facilities that entered or left the book are excluded and reported separately."
    ),
    required_domains=[FACILITY_POSITION],
    name="Stage Migration",
    description=(
        "What moved between IFRS 9 stages between two reporting periods, measured "
        "by exposure or facility count, with the improved / stable / deteriorated "
        "split and the exposure entering and leaving the book."
    ),
    category=Category.INVESTIGATE,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=STAGE_MIG_FIELDS,
    parameters=[FROM_PARAM, TO_PARAM, BASIS_PARAM],
    outputs=[
        OutputField("from", "Opening IFRS 9 stage.", "string"),
        OutputField("to", "Closing IFRS 9 stage.", "string"),
        OutputField("value", "Exposure (or facility count) that made the move.", "number", unit="SAR mn", precision=2),
        OutputField("row_pct", "Share of the opening stage that moved this way.", "number", unit="%", precision=2),
        OutputField("facility_count", "Number of facilities that made the move.", "integer"),
    ],
    validation_rules=[
        ValidationRule("rows_sum_to_100", "Each opening stage's destinations must sum to 100%."),
        ValidationRule("matched_population", "Only facilities present in both periods are in the matrix.",
                       severity="warning"),
    ],
    supported_visualizations=[VisualizationType.MATRIX, VisualizationType.HEATMAP,
                              VisualizationType.TABLE],
    calculation_description=(
        "Joins the facility population at the opening and closing periods on "
        "account_id, then cross-tabulates opening stage against closing stage. "
        "Cells are weighted by OPENING exposure, so the matrix answers 'where did "
        "the exposure that started here end up?' rather than mixing opening and "
        "closing balances. Row percentages are conditional on the opening stage. "
        "Facilities in only one period are excluded from the matrix and reported "
        "separately as entries and exits."
    ),
))
def stage_migration(ctx: ExecutionContext) -> AnalysisResult:
    to_period, from_period, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("to_period"), ctx.params.get("from_period")
    )
    basis = ctx.params.get("basis") or "ead"
    if from_period == to_period:
        raise ValueError("The opening and closing periods must be different.")

    opening, closing, branches = _read_pair(ctx, STAGE_MIG_FIELDS, from_period, to_period)
    merged, coverage = _join_periods(ctx, opening, closing, branches)

    stages = ["1", "2", "3"]
    rows, totals = _matrix(merged, "ifrs9_stage_from", "ifrs9_stage_to", stages, basis)
    ctx.step(NodeType.AGGREGATION, "Cross-tabulate opening against closing stage",
             config={"basis": basis, "weighting": "opening exposure" if basis == "ead" else "facility count",
                     "categories": stages},
             rows_in=coverage["matched"], rows_out=len(rows), preview=pd.DataFrame(rows))

    split = _movement_split(rows, {"1": 0, "2": 1, "3": 2})
    ctx.step(NodeType.CALCULATION, "Improved / stable / deteriorated split",
             config={"rule": "a higher closing stage is deterioration"}, summary=split)

    return AnalysisResult(
        rows=rows,
        values={"from_period": from_period, "to_period": to_period, "basis": basis,
                "opening_totals": totals, "coverage": coverage, "movement": split,
                "periods_available": available},
        units={"value": "SAR mn" if basis == "ead" else "facilities", "row_pct": "%"},
        input_row_count=coverage["matched"],
        warnings=ctx.warnings,
        meta={"grain": "One row per (opening stage, closing stage) pair.",
              "weighting": "Opening exposure." if basis == "ead" else "Facility count."},
    )


# =============================================================== DPD migration

DPD_FIELDS = ["account_id", "customer_id", "ead", "dpd_days", "ifrs9_stage"]


@register(AnalysisContract(
    id="dpd_migration",
    period_requirement=PeriodRequirement.TWO_PERIOD,
    governed_default_period=False,
    answer_shape=AnswerShape.MOVEMENT,
    when_to_use=(
        "Use when the question is about arrears — what moved between days-past-due buckets, and what cured."
    ),
    trigger_questions=[
        "How have arrears moved?",
        "Show DPD migration.",
        "What cured this period?",
    ],
    limitations=(
        "Bucket-to-bucket movement only. A facility can improve its bucket while its credit quality deteriorates on other measures."
    ),
    required_domains=[FACILITY_POSITION],
    name="DPD Migration",
    description=(
        "Movement between delinquency buckets (Current, 1-29, 30-59, 60-89, "
        "90-179, 180+) between two reporting periods."
    ),
    category=Category.DETECT,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=DPD_FIELDS,
    parameters=[FROM_PARAM, TO_PARAM, BASIS_PARAM],
    outputs=[
        OutputField("from", "Opening delinquency bucket.", "string"),
        OutputField("to", "Closing delinquency bucket.", "string"),
        OutputField("value", "Exposure (or facility count) that made the move.", "number", unit="SAR mn", precision=2),
        OutputField("row_pct", "Share of the opening bucket that moved this way.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("rows_sum_to_100", "Each opening bucket's destinations must sum to 100%."),
        ValidationRule("buckets_ordered", "Buckets must be returned in delinquency order."),
    ],
    supported_visualizations=[VisualizationType.MATRIX, VisualizationType.HEATMAP,
                              VisualizationType.TABLE],
    calculation_description=(
        "Buckets days-past-due into the standard reporting bands (0 = Current, "
        "then 1-29, 30-59, 60-89, 90-179, 180+), joins the two periods on "
        "account_id and cross-tabulates. Weighted by opening exposure. The "
        "cure rate is the share of exposure that was delinquent at the opening "
        "and is Current at the closing."
    ),
))
def dpd_migration(ctx: ExecutionContext) -> AnalysisResult:
    to_period, from_period, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("to_period"), ctx.params.get("from_period")
    )
    basis = ctx.params.get("basis") or "ead"
    if from_period == to_period:
        raise ValueError("The opening and closing periods must be different.")

    opening, closing, branches = _read_pair(ctx, DPD_FIELDS, from_period, to_period)
    opening = opening.assign(dpd_bucket=dpd_bucket(opening["dpd_days"]))
    closing = closing.assign(dpd_bucket=dpd_bucket(closing["dpd_days"]))
    ctx.step(NodeType.TRANSFORMATION, "Bucket days past due", parents=branches,
             config={"buckets": DPD_BUCKETS,
                     "rule": "0 = Current; then 1-29, 30-59, 60-89, 90-179, 180+"},
             rows_out=int(len(opening) + len(closing)), advance=False)

    merged, coverage = _join_periods(ctx, opening, closing, branches)
    rows, totals = _matrix(merged, "dpd_bucket_from", "dpd_bucket_to", DPD_BUCKETS, basis)
    ctx.step(NodeType.AGGREGATION, "Cross-tabulate delinquency buckets",
             config={"basis": basis, "categories": DPD_BUCKETS},
             rows_in=coverage["matched"], rows_out=len(rows), preview=pd.DataFrame(rows))

    order = {b: i for i, b in enumerate(DPD_BUCKETS)}
    split = _movement_split(rows, order)
    cured = sum(r["value"] for r in rows if r["from"] != "Current" and r["to"] == "Current")
    delinquent_opening = sum(v for k, v in totals.items() if k != "Current")
    split["cured"] = rounded(cured, 3)
    split["cure_rate_pct"] = rounded(safe_ratio(cured, delinquent_opening), 3)
    ctx.step(NodeType.CALCULATION, "Cure rate and movement split",
             config={"cure_rate": "delinquent at opening and Current at closing, over delinquent at opening"},
             summary=split)

    return AnalysisResult(
        rows=rows,
        values={"from_period": from_period, "to_period": to_period, "basis": basis,
                "buckets": DPD_BUCKETS, "opening_totals": totals,
                "coverage": coverage, "movement": split, "periods_available": available},
        units={"value": "SAR mn" if basis == "ead" else "facilities", "row_pct": "%"},
        input_row_count=coverage["matched"],
        warnings=ctx.warnings,
        meta={"grain": "One row per (opening bucket, closing bucket) pair.",
              "weighting": "Opening exposure." if basis == "ead" else "Facility count."},
    )


# ==================================================== rating transition matrix

RATING_FIELDS = ["account_id", "customer_id", "ead", "risk_rating", "rating_bucket", "ifrs9_stage"]


@register(AnalysisContract(
    id="rating_transition_matrix",
    period_requirement=PeriodRequirement.TWO_PERIOD,
    governed_default_period=False,
    answer_shape=AnswerShape.MATRIX,
    when_to_use=(
        "Use when the question asks for empirical rating transitions — the probability of moving from one grade to another over an interval."
    ),
    trigger_questions=[
        "Show the rating transition matrix.",
        "What is the downgrade rate?",
        "How did ratings migrate?",
    ],
    limitations=(
        "An empirical matrix over one interval, not a through-the-cycle estimate. Short intervals and small grades give unstable probabilities."
    ),
    required_domains=[FACILITY_POSITION],
    name="Rating Transition Matrix",
    description=(
        "How internal risk ratings migrated between two reporting periods, as a "
        "matrix of row-conditional probabilities, with upgrade, downgrade and "
        "stability rates."
    ),
    category=Category.INVESTIGATE,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=RATING_FIELDS,
    parameters=[FROM_PARAM, TO_PARAM, BASIS_PARAM],
    outputs=[
        OutputField("from", "Opening rating grade.", "string"),
        OutputField("to", "Closing rating grade.", "string"),
        OutputField("value", "Exposure (or facility count) that made the move.", "number", unit="SAR mn", precision=2),
        OutputField("row_pct", "Transition probability from the opening grade.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("rows_sum_to_100",
                       "Each opening grade's transition probabilities must sum to 100%."),
        ValidationRule("grades_ordered", "Grades must be ordered best to worst, not alphabetically."),
    ],
    supported_visualizations=[VisualizationType.MATRIX, VisualizationType.HEATMAP,
                              VisualizationType.TABLE],
    calculation_description=(
        "Joins the facility population at both periods on account_id and "
        "cross-tabulates opening rating against closing rating. Each row is "
        "normalised to its own opening total, giving the empirical transition "
        "probability from that grade over the interval. Grades are ordered by "
        "credit quality (AAA best) rather than alphabetically — alphabetical "
        "ordering would put CCC above B and make the diagonal meaningless. "
        "The interval is whatever separates the two periods chosen; it is "
        "reported alongside the matrix and is NOT annualised."
    ),
))
def rating_transition_matrix(ctx: ExecutionContext) -> AnalysisResult:
    to_period, from_period, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("to_period"), ctx.params.get("from_period")
    )
    basis = ctx.params.get("basis") or "ead"
    if from_period == to_period:
        raise ValueError("The opening and closing periods must be different.")

    opening, closing, branches = _read_pair(ctx, RATING_FIELDS, from_period, to_period)
    merged, coverage = _join_periods(ctx, opening, closing, branches)

    grades = order_ratings(
        list(merged["risk_rating_from"].dropna()) + list(merged["risk_rating_to"].dropna())
    )
    merged = merged.assign(
        risk_rating_from=merged["risk_rating_from"].astype(str).str.strip().str.upper(),
        risk_rating_to=merged["risk_rating_to"].astype(str).str.strip().str.upper(),
    )
    rows, totals = _matrix(merged, "risk_rating_from", "risk_rating_to", grades, basis)
    ctx.step(NodeType.AGGREGATION, "Cross-tabulate rating grades",
             config={"basis": basis, "grades": grades,
                     "ordering": "by credit quality, best first"},
             rows_in=coverage["matched"], rows_out=len(rows), preview=pd.DataFrame(rows))

    order = {g: rating_sort_key(g) for g in grades}
    split = _movement_split(rows, order)
    # In a rating matrix the vocabulary is upgrade/downgrade rather than
    # improved/deteriorated, so both namings are returned.
    split["upgraded_pct"] = split["improved_pct"]
    split["downgraded_pct"] = split["deteriorated_pct"]
    interval = f"{from_period} to {to_period} ({available.index(to_period) - available.index(from_period)} periods)"
    ctx.step(NodeType.CALCULATION, "Upgrade / stable / downgrade rates",
             config={"interval": interval, "annualised": False}, summary=split)

    return AnalysisResult(
        rows=rows,
        values={"from_period": from_period, "to_period": to_period, "basis": basis,
                "grades": grades, "opening_totals": totals, "coverage": coverage,
                "movement": split, "interval": interval, "annualised": False,
                "periods_available": available},
        units={"value": "SAR mn" if basis == "ead" else "facilities", "row_pct": "%"},
        input_row_count=coverage["matched"],
        warnings=ctx.warnings,
        meta={"grain": "One row per (opening grade, closing grade) pair.",
              "weighting": "Opening exposure." if basis == "ead" else "Facility count."},
    )


# ================================================================ ECL movement

ECL_FIELDS = ["account_id", "customer_id", "borrower_name", "ead", "total_ecl", "model_ecl",
              "macro_overlay", "ifrs9_stage", "dpd_days", "sector"]


@register(AnalysisContract(
    id="ecl_movement",
    period_requirement=PeriodRequirement.TWO_PERIOD,
    governed_default_period=False,
    answer_shape=AnswerShape.MOVEMENT,
    when_to_use=(
        "Use when the question is how impairment changed and which groups the change sits in."
    ),
    trigger_questions=[
        "How has ECL changed?",
        "How has ECL moved?",
        "How has the impairment moved?",
        "Which sectors deteriorated the most?",
        "What drove the impairment charge?",
    ],
    limitations=(
        "Attributes the movement to groups by arithmetic decomposition. Where a group's ECL rose, that is where the change sits — not evidence that the group caused it."
    ),
    required_domains=[FACILITY_POSITION],
    name="ECL Movement",
    description=(
        "Why total ECL changed between two periods, attributed to stage migration, "
        "new stage 3, macro overlay, exposure change, new business, exits and "
        "remeasurement of existing facilities."
    ),
    category=Category.INVESTIGATE,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=ECL_FIELDS,
    parameters=[
        FROM_PARAM, TO_PARAM,
        Parameter("group_by", ParamType.ENUM, "Optional dimension to attribute the movement by.",
                  default="none", allowed_values=["none", "sector", "region", "segment", "ifrs9_stage"]),
    ],
    outputs=[
        OutputField("component", "Movement component.", "string"),
        OutputField("value", "Contribution to the change in ECL.", "number", unit="SAR mn", precision=3),
    ],
    validation_rules=[
        ValidationRule("bridge_reconciles",
                       "Opening plus every component must equal closing exactly."),
    ],
    supported_visualizations=[VisualizationType.WATERFALL, VisualizationType.BAR,
                              VisualizationType.TABLE],
    calculation_description=(
        "Builds a bridge from opening to closing ECL. Facilities present in both "
        "periods are attributed to: new stage 3 (moved into stage 3), other stage "
        "migration (changed stage but not into stage 3), macro overlay change, and "
        "remeasurement (everything else on unchanged-stage facilities). Facilities "
        "present in only one period become new business or exits. The components "
        "are computed as a partition of the matched population, so opening plus "
        "all components equals closing exactly — there is no residual term "
        "absorbing an unexplained difference."
    ),
))
def ecl_movement(ctx: ExecutionContext) -> AnalysisResult:
    to_period, from_period, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("to_period"), ctx.params.get("from_period")
    )
    group_by = ctx.params.get("group_by") or "none"
    if from_period == to_period:
        raise ValueError("The opening and closing periods must be different.")

    opening, closing, branches = _read_pair(ctx, ECL_FIELDS, from_period, to_period)

    opening_ecl = float(pd.to_numeric(opening["total_ecl"], errors="coerce").fillna(0).sum())
    closing_ecl = float(pd.to_numeric(closing["total_ecl"], errors="coerce").fillna(0).sum())

    merged = opening.merge(closing, on="account_id", suffixes=("_from", "_to"), how="inner")
    matched_ids = set(merged["account_id"])
    exits = opening[~opening["account_id"].isin(matched_ids)]
    entries = closing[~closing["account_id"].isin(matched_ids)]

    ctx.step(NodeType.TRANSFORMATION, "Partition into matched, entries and exits",
             parents=branches,
             config={"join_key": "account_id",
                     "note": "Every facility falls in exactly one partition, so the bridge reconciles."},
             rows_in=int(len(opening) + len(closing)), rows_out=int(len(merged)),
             summary={"matched": int(len(merged)), "entries": int(len(entries)),
                      "exits": int(len(exits))})

    ecl_from = pd.to_numeric(merged["total_ecl_from"], errors="coerce").fillna(0)
    ecl_to = pd.to_numeric(merged["total_ecl_to"], errors="coerce").fillna(0)
    delta = ecl_to - ecl_from
    stage_from = pd.to_numeric(merged["ifrs9_stage_from"], errors="coerce")
    stage_to = pd.to_numeric(merged["ifrs9_stage_to"], errors="coerce")
    overlay_delta = (
        pd.to_numeric(merged["macro_overlay_to"], errors="coerce").fillna(0)
        - pd.to_numeric(merged["macro_overlay_from"], errors="coerce").fillna(0)
    )

    into_s3 = (stage_to == 3) & (stage_from != 3)
    other_migration = (stage_from != stage_to) & ~into_s3
    unchanged = stage_from == stage_to

    # The overlay is stripped out of the stage components and reported on its own,
    # so a management overlay is never hidden inside "migration".
    new_stage3 = float((delta[into_s3] - overlay_delta[into_s3]).sum())
    migration = float((delta[other_migration] - overlay_delta[other_migration]).sum())
    remeasurement = float((delta[unchanged] - overlay_delta[unchanged]).sum())
    overlay = float(overlay_delta.sum())
    new_business = float(pd.to_numeric(entries["total_ecl"], errors="coerce").fillna(0).sum())
    exited = -float(pd.to_numeric(exits["total_ecl"], errors="coerce").fillna(0).sum())

    components = [
        {"component": "Opening ECL", "value": rounded(opening_ecl, 3), "kind": "total"},
        {"component": "New stage 3", "value": rounded(new_stage3, 3), "kind": "movement"},
        {"component": "Other stage migration", "value": rounded(migration, 3), "kind": "movement"},
        {"component": "Macro overlay", "value": rounded(overlay, 3), "kind": "movement"},
        {"component": "Remeasurement", "value": rounded(remeasurement, 3), "kind": "movement"},
        {"component": "New business", "value": rounded(new_business, 3), "kind": "movement"},
        {"component": "Exits", "value": rounded(exited, 3), "kind": "movement"},
        {"component": "Closing ECL", "value": rounded(closing_ecl, 3), "kind": "total"},
    ]
    ctx.step(NodeType.AGGREGATION, "Attribute the ECL change",
             config={"components": [c["component"] for c in components if c["kind"] == "movement"],
                     "overlay_treatment": "stripped out of stage components and shown separately"},
             rows_in=int(len(merged)), rows_out=len(components), preview=pd.DataFrame(components))

    # Declared validation rule: the bridge must reconcile.
    reconciled = opening_ecl + new_stage3 + migration + overlay + remeasurement + new_business + exited
    difference = closing_ecl - reconciled
    if abs(difference) > 0.01:
        ctx.warn(f"ECL bridge does not reconcile: off by {difference:,.4f} SAR mn.")
    ctx.step(NodeType.CALCULATION, "Reconcile the bridge",
             config={"check": "opening + components == closing"},
             summary={"opening": rounded(opening_ecl, 3), "closing": rounded(closing_ecl, 3),
                      "reconciled": rounded(reconciled, 3), "difference": rounded(difference, 4)})

    breakdown: list[dict] = []
    if group_by != "none":
        key = f"{group_by}_to" if f"{group_by}_to" in merged.columns else group_by
        if key in merged.columns:
            grouped = merged.assign(_delta=delta).groupby(key, observed=True)["_delta"].sum()
            breakdown = [{group_by: str(k), "ecl_change": rounded(float(v), 3)}
                         for k, v in grouped.sort_values(ascending=False).items()]
            ctx.step(NodeType.AGGREGATION, f"Attribute by {group_by}",
                     config={"group_by": [group_by]}, rows_out=len(breakdown))

    # The rows follow the grain the request asked for. A question naming
    # sectors — "which sectors deteriorated most this quarter?" — was answered
    # with the portfolio bridge in the table and the sectors only in the
    # sentence, so the reader's eye landed on an opening balance under a
    # heading about seventeen sectors. The arithmetic is untouched: this is
    # the same attribution, already computed above, put where the answer is.
    reported = breakdown if breakdown else components
    grain = (f"One row per {group_by}." if breakdown
             else "One row per bridge component.")
    return AnalysisResult(
        rows=reported,
        values={"from_period": from_period, "to_period": to_period,
                "opening_ecl": rounded(opening_ecl, 3), "closing_ecl": rounded(closing_ecl, 3),
                "net_change": rounded(closing_ecl - opening_ecl, 3),
                "reconciliation_difference": rounded(difference, 4),
                "breakdown": breakdown, "group_by": group_by,
                # The bridge itself, kept whatever the rows are reporting, so
                # the reconciliation is inspectable from either shape.
                "components": components,
                "periods_available": available},
        units={"value": "SAR mn", "ecl_change": "SAR mn"},
        input_row_count=int(len(opening) + len(closing)),
        warnings=ctx.warnings,
        meta={"grain": grain,
              "weighting": "Absolute ECL amounts; no weighting applied."},
    )


# ================================================== top deteriorating borrowers

DETERIORATION_FIELDS = [
    "account_id", "customer_id", "borrower_name", "sector", "region", "ead", "total_ecl",
    "ifrs9_stage", "risk_rating", "dpd_days", "pd_12m_pct", "watchlist",
]


@register(AnalysisContract(
    id="top_deteriorating_borrowers",
    period_requirement=PeriodRequirement.TWO_PERIOD,
    governed_default_period=False,
    answer_shape=AnswerShape.LIST,
    when_to_use=(
        "Use when the question asks for names — which individual borrowers worsened, and why."
    ),
    trigger_questions=[
        "Which borrowers deteriorated?",
        "Show the top ten deteriorating names.",
        "Who requires attention?",
    ],
    limitations=(
        "Ranks by a composite severity score combining stage, rating, PD, DPD and ECL movement. The score is a triage ordering, not a credit opinion."
    ),
    required_domains=[FACILITY_POSITION],
    name="Top Deteriorating Borrowers",
    description=(
        "Borrowers whose credit position worsened most between two periods, ranked "
        "by a composite of ECL increase, stage migration, rating downgrade, PD "
        "increase and delinquency, with the reason for each."
    ),
    category=Category.DETECT,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=DETERIORATION_FIELDS,
    parameters=[
        FROM_PARAM, TO_PARAM,
        Parameter("top_n", ParamType.INTEGER, "How many borrowers to return.",
                  default=10, minimum=1, maximum=100),
        Parameter("min_ead", ParamType.NUMBER,
                  "Ignore borrowers whose closing exposure is below this, in SAR mn.",
                  default=0.0, minimum=0.0),
    ],
    outputs=[
        OutputField("customer_id", "Borrower identifier.", "string"),
        OutputField("borrower_name", "Borrower name.", "string"),
        OutputField("ead", "Closing exposure at default.", "number", unit="SAR mn", precision=1),
        OutputField("ecl_change", "Increase in ECL over the interval.", "number", unit="SAR mn", precision=3),
        OutputField("stage_change", "Change in IFRS 9 stage (positive is worse).", "integer"),
        OutputField("notch_change", "Rating notches moved (positive is worse).", "integer"),
        OutputField("reasons", "Why this borrower is flagged.", "string"),
    ],
    validation_rules=[
        ValidationRule("only_deteriorated",
                       "Every returned borrower must show at least one worsening indicator."),
    ],
    supported_visualizations=[VisualizationType.TABLE, VisualizationType.BAR],
    calculation_description=(
        "Aggregates facilities to borrower level at both periods (EAD and ECL "
        "summed; stage, rating and DPD taken at their worst across the borrower's "
        "facilities, because one deteriorating facility is what matters). Ranks by "
        "a composite score: ECL increase scaled by exposure, plus weighted "
        "contributions from stage migration, rating downgrade, PD increase and "
        "days past due. Borrowers with no worsening indicator are excluded rather "
        "than padding the list to top_n."
    ),
))
def top_deteriorating_borrowers(ctx: ExecutionContext) -> AnalysisResult:
    to_period, from_period, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("to_period"), ctx.params.get("from_period")
    )
    top_n = int(ctx.params.get("top_n") or 10)
    min_ead = float(ctx.params.get("min_ead") or 0.0)
    if from_period == to_period:
        raise ValueError("The opening and closing periods must be different.")

    opening, closing, branches = _read_pair(ctx, DETERIORATION_FIELDS, from_period, to_period)

    open_b = _by_borrower(opening)
    close_b = _by_borrower(closing)
    ctx.step(NodeType.AGGREGATION, "Aggregate facilities to borrower level", parents=branches,
             config={"group_by": ["customer_id"],
                     "rule": "EAD and ECL summed; stage, rating and DPD taken at their worst"},
             rows_in=int(len(opening) + len(closing)),
             rows_out=int(len(open_b) + len(close_b)))

    merged = open_b.merge(close_b, on="customer_id", suffixes=("_from", "_to"), how="inner")
    if min_ead > 0:
        before = len(merged)
        merged = merged[merged["ead_to"] >= min_ead]
        ctx.step(NodeType.FILTER, f"Closing exposure at least {min_ead} SAR mn",
                 config={"field": "ead", "operator": ">=", "value": min_ead},
                 rows_in=before, rows_out=int(len(merged)))

    scored = _score_deterioration(merged)
    ctx.step(NodeType.CALCULATION, "Composite deterioration score",
             config={"weights": {"ecl_increase_scaled": 1.0, "stage_change": 25.0,
                                 "notch_change": 10.0, "pd_increase": 5.0, "dpd_increase": 0.05},
                     "note": "Borrowers with no worsening indicator are excluded."},
             rows_in=int(len(merged)), rows_out=int(len(scored)),
             preview=scored.head())

    rows = scored.head(top_n).to_dict(orient="records")
    if len(scored) < top_n:
        ctx.warn(
            f"Only {len(scored)} borrowers deteriorated between {from_period} and {to_period}; "
            f"{top_n} were requested."
        )

    return AnalysisResult(
        rows=rows,
        values={"from_period": from_period, "to_period": to_period,
                "deteriorated_count": int(len(scored)),
                "borrowers_compared": int(len(merged)),
                "total_ecl_increase": rounded(float(scored["ecl_change"].sum()) if len(scored) else 0.0, 3),
                "periods_available": available},
        units={"ead": "SAR mn", "ecl_change": "SAR mn", "pd_change": "%"},
        input_row_count=int(len(opening) + len(closing)),
        warnings=ctx.warnings,
        meta={"grain": "One row per borrower.",
              "weighting": "Composite score; ECL increase scaled by exposure."},
    )


def _by_borrower(df: pd.DataFrame) -> pd.DataFrame:
    """Roll facilities up to the borrower.

    Stage, rating and DPD are taken at their WORST across the borrower's
    facilities rather than averaged: a borrower with one facility in stage 3 is a
    stage 3 relationship, and averaging would hide exactly the case that matters.
    """
    work = df.copy()
    work["ead"] = pd.to_numeric(work["ead"], errors="coerce").fillna(0)
    work["total_ecl"] = pd.to_numeric(work["total_ecl"], errors="coerce").fillna(0)
    work["ifrs9_stage"] = pd.to_numeric(work["ifrs9_stage"], errors="coerce").fillna(1)
    work["dpd_days"] = pd.to_numeric(work["dpd_days"], errors="coerce").fillna(0)
    work["pd_12m_pct"] = pd.to_numeric(work["pd_12m_pct"], errors="coerce").fillna(0)
    work["rating_rank"] = work["risk_rating"].map(rating_sort_key)

    grouped = work.groupby("customer_id", observed=True).agg(
        borrower_name=("borrower_name", "first"),
        sector=("sector", "first"),
        region=("region", "first"),
        ead=("ead", "sum"),
        total_ecl=("total_ecl", "sum"),
        ifrs9_stage=("ifrs9_stage", "max"),
        dpd_days=("dpd_days", "max"),
        rating_rank=("rating_rank", "max"),
        risk_rating=("risk_rating", "last"),
        facility_count=("account_id", "count"),
    ).reset_index()
    # PD is exposure-weighted across the borrower's facilities.
    weighted_pd = work.groupby("customer_id", observed=True).apply(
        lambda g: (g["pd_12m_pct"] * g["ead"]).sum() / g["ead"].sum() if g["ead"].sum() else 0.0,
        include_groups=False,
    )
    grouped["pd_12m_pct"] = grouped["customer_id"].map(weighted_pd).fillna(0.0)
    return grouped


def _score_deterioration(merged: pd.DataFrame) -> pd.DataFrame:
    out = merged.copy()
    out["ecl_change"] = out["total_ecl_to"] - out["total_ecl_from"]
    out["ead_change"] = out["ead_to"] - out["ead_from"]
    out["stage_change"] = (out["ifrs9_stage_to"] - out["ifrs9_stage_from"]).astype(int)
    out["notch_change"] = (out["rating_rank_to"] - out["rating_rank_from"]).astype(int)
    out["pd_change"] = out["pd_12m_pct_to"] - out["pd_12m_pct_from"]
    out["dpd_change"] = (out["dpd_days_to"] - out["dpd_days_from"]).astype(int)

    total_ead = float(out["ead_to"].sum()) or 1.0
    out["score"] = (
        (out["ecl_change"] / total_ead * 1000).clip(lower=0)
        + out["stage_change"].clip(lower=0) * 25.0
        + out["notch_change"].clip(lower=0) * 10.0
        + out["pd_change"].clip(lower=0) * 5.0
        + out["dpd_change"].clip(lower=0) * 0.05
    )

    # Only genuine deterioration. Padding the list with stable borrowers would
    # make a "top deteriorating" table quietly untrue.
    deteriorated = out[
        (out["ecl_change"] > 0) | (out["stage_change"] > 0)
        | (out["notch_change"] > 0) | (out["dpd_change"] > 0)
    ].copy()

    deteriorated["reasons"] = deteriorated.apply(_reasons, axis=1)
    result = deteriorated.sort_values("score", ascending=False)[[
        "customer_id", "borrower_name_to", "sector_to", "region_to",
        "ead_to", "ecl_change", "stage_change", "notch_change", "pd_change",
        "dpd_change", "ifrs9_stage_from", "ifrs9_stage_to",
        "risk_rating_from", "risk_rating_to", "score", "reasons",
    ]].rename(columns={
        "borrower_name_to": "borrower_name", "sector_to": "sector",
        "region_to": "region", "ead_to": "ead",
    })
    for column in ("ead", "ecl_change", "pd_change", "score"):
        result[column] = result[column].map(lambda v: rounded(float(v), 3))
    return result


def _reasons(row) -> str:
    reasons = []
    if row["stage_change"] > 0:
        reasons.append(f"Stage {int(row['ifrs9_stage_from'])} to {int(row['ifrs9_stage_to'])}")
    if row["notch_change"] > 0:
        reasons.append(f"Downgraded {row['risk_rating_from']} to {row['risk_rating_to']}")
    if row["ecl_change"] > 0:
        reasons.append(f"ECL up {row['ecl_change']:.2f} SAR mn")
    if row["dpd_change"] > 0:
        reasons.append(f"DPD up {int(row['dpd_change'])} days")
    if row["pd_change"] > 0.01:
        reasons.append(f"PD up {row['pd_change']:.2f}pp")
    return "; ".join(reasons) or "Composite deterioration"


__all__ = [
    "stage_migration", "dpd_migration", "rating_transition_matrix",
    "ecl_movement", "top_deteriorating_borrowers",
]
