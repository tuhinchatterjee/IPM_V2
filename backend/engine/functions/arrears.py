"""
Arrears, collections and what the credit file says.

Two capabilities over the two datasets a credit function actually works from
day to day and which the facility snapshot does not carry:

    Arrears Position     how much is overdue, in which bucket, and how far
                         recovery action has escalated
    Credit File Signals  what the notes on the file raised — covenant
                         breaches, liquidity, management changes,
                         going-concern language

Both are deliberately descriptive. Neither predicts anything, neither scores
anybody, and neither claims that a memo mentioning liquidity means a default is
coming — the delinquency data records what happened and the memo data records
what was written, and inferring one from the other is a modelling exercise this
product has not done.
"""

from __future__ import annotations

import pandas as pd

from backend.data_access.catalog import CREDIT_FILE_COMMENTARY, FACILITY_DELINQUENCY
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
    DELINQUENCY,
    MEMOS,
    resolve_periods,
    rounded,
    safe_ratio,
)
from backend.engine.registry import AnalysisResult, register
from backend.trace.model import NodeType

OWNER = "Credit Risk Operations"

#: The arrears buckets in the order a collections committee reads them —
#: worsening, left to right. Sorting these alphabetically puts "1-29 days"
#: after "180+ days", which reverses the story.
BUCKET_ORDER = [
    "Current", "1-29 days", "30-59 days", "60-89 days", "90-179 days", "180+ days",
]

#: Buckets that count as delinquent for the headline figures. "Current" is
#: everything else.
DELINQUENT_BUCKETS = BUCKET_ORDER[1:]

ARREARS_FIELDS = [
    "account_id", "customer_id", "borrower_name", "sector", "region", "segment",
    "days_past_due", "dpd_bucket", "arrears_amount", "instalments_missed",
    "forbearance_type", "restructured_flag", "collections_stage",
    "cured_this_period", "newly_delinquent", "exposure_at_risk",
]

PERIOD_PARAM = Parameter(
    "period", ParamType.PERIOD,
    "Reporting period. Defaults to the latest published period.",
    default="latest",
)

GROUP_BY = ["none", "sector", "region", "segment", "collections_stage",
            "forbearance_type"]


@register(AnalysisContract(
    id="arrears_position",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is about arrears: who is behind, by how much, "
        "in which bucket, and what collections is doing about it."
    ),
    trigger_questions=[
        "How much is in arrears?",
        "Show me the delinquency buckets.",
        "What is 90 days past due?",
        "How much has been forborne?",
        "Who cured this quarter?",
    ],
    limitations=(
        "A position at one quarter end, not a forecast. It reports what is "
        "overdue and where collections has got to; it does not estimate what "
        "will be recovered."
    ),
    required_domains=[FACILITY_DELINQUENCY],
    name="Arrears Position",
    description=(
        "Delinquency at a reporting date: the split across arrears buckets by "
        "amount overdue and facility count, exposure on facilities 90 or more "
        "days past due, forbearance granted, and how many facilities cured or "
        "newly fell behind in the period."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[DELINQUENCY],
    required_fields=ARREARS_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("group_by", ParamType.ENUM,
                  "Optional dimension to break the arrears down by.",
                  default="none", allowed_values=GROUP_BY),
    ],
    outputs=[
        OutputField("dpd_bucket", "Arrears bucket.", "string"),
        OutputField("facility_count", "Facilities in the bucket.", "integer"),
        OutputField("arrears_amount", "Amount overdue in the bucket.", "number",
                    unit="USD mn", precision=2),
        OutputField("exposure_at_risk", "Exposure at default on facilities 90 or "
                    "more days past due.", "number", unit="USD mn", precision=2),
        OutputField("share_of_facilities_pct", "Bucket as a share of all "
                    "facilities.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("buckets_reconcile",
                       "Bucket facility counts must sum to the facilities read."),
        ValidationRule("buckets_known",
                       "Every row must fall in one of the six governed buckets."),
    ],
    supported_visualizations=[VisualizationType.STACKED_BAR, VisualizationType.TABLE,
                              VisualizationType.KPI],
    calculation_description=(
        "Counts facilities and sums the amount overdue within each arrears "
        "bucket, using the bucket recorded in the governed data rather than "
        "re-deriving it from days past due — so this analysis and the source "
        "cannot disagree. Exposure at risk is the exposure at default of "
        "facilities 90 or more days past due. Cures and new delinquencies are "
        "the flags the data records for the period, which are measured against "
        "the previous quarter end rather than inferred from this one."
    ),
))
def arrears_position(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, DELINQUENCY, ctx.params.get("period"), None,
    )
    group_by = str(ctx.params.get("group_by") or "none")

    frame, _ = ctx.read(DELINQUENCY, fields=ARREARS_FIELDS, period=period,
                        label=f"Facility arrears · {period}")

    delinquent = frame[frame["dpd_bucket"].isin(DELINQUENT_BUCKETS)]
    overdue = pd.to_numeric(frame["arrears_amount"], errors="coerce").fillna(0)
    at_risk = pd.to_numeric(frame["exposure_at_risk"], errors="coerce").fillna(0)
    forborne = frame["forbearance_type"].fillna("None") != "None"

    headline = {
        "facilities_read": float(len(frame)),
        "facilities_in_arrears": float(len(delinquent)),
        "arrears_rate_pct": rounded(safe_ratio(len(delinquent), len(frame)), 3),
        "total_arrears_amount": rounded(float(overdue.sum()), 3),
        "exposure_at_risk": rounded(float(at_risk.sum()), 3),
        "facilities_90_plus": float(
            int(frame["dpd_bucket"].isin(["90-179 days", "180+ days"]).sum())),
        "forborne_facilities": float(int(forborne.sum())),
        "restructured_facilities": float(
            int(frame["restructured_flag"].fillna(False).astype(bool).sum())),
        "cured_this_period": float(
            int(frame["cured_this_period"].fillna(False).astype(bool).sum())),
        "newly_delinquent": float(
            int(frame["newly_delinquent"].fillna(False).astype(bool).sum())),
        "borrowers_in_arrears": float(delinquent["customer_id"].nunique()),
    }
    ctx.step(NodeType.AGGREGATION, f"Aggregate {len(frame):,} facilities",
             config={"measures": list(headline),
                     "delinquent_buckets": DELINQUENT_BUCKETS},
             rows_in=int(len(frame)), rows_out=1, summary=headline)

    rows = _by_bucket(frame, group_by)
    ctx.step(NodeType.AGGREGATION,
             f"Split by arrears bucket{'' if group_by == 'none' else f' and {group_by}'}",
             config={"group_by": group_by, "bucket_order": BUCKET_ORDER},
             rows_in=int(len(frame)), rows_out=len(rows))

    # Declared validation rule: the buckets must account for every facility read.
    counted = sum(int(row["facility_count"]) for row in rows)
    if counted != len(frame):
        ctx.warn(
            f"Arrears buckets account for {counted:,} facilities but "
            f"{len(frame):,} were read — some rows carry a bucket the product "
            "does not govern."
        )

    unknown = sorted(set(frame["dpd_bucket"].dropna()) - set(BUCKET_ORDER))
    if unknown:
        ctx.warn(f"Ungoverned arrears buckets in the data: {', '.join(unknown)}.")

    return AnalysisResult(
        rows=rows,
        values={**headline, "period": period, "group_by": group_by,
                "periods_available": available},
        units={"total_arrears_amount": "USD mn", "exposure_at_risk": "USD mn",
               "arrears_rate_pct": "%"},
        input_row_count=int(len(frame)),
        warnings=ctx.warnings,
        meta={"grain": "One row per facility per reporting period.",
              "bucket_order": BUCKET_ORDER,
              "bucket_source": "Recorded in the governed data, not re-derived."},
    )


def _by_bucket(frame: pd.DataFrame, group_by: str) -> list[dict]:
    """Facility counts and amounts per arrears bucket, worst last."""
    keys = ["dpd_bucket"] if group_by == "none" else ["dpd_bucket", group_by]
    grouped = frame.groupby(keys, observed=True).agg(
        facility_count=("account_id", "count"),
        arrears_amount=("arrears_amount", "sum"),
        exposure_at_risk=("exposure_at_risk", "sum"),
        instalments_missed=("instalments_missed", "sum"),
    ).reset_index()

    total = len(frame)
    order = {label: i for i, label in enumerate(BUCKET_ORDER)}
    grouped["_order"] = grouped["dpd_bucket"].map(lambda b: order.get(b, len(order)))
    grouped = grouped.sort_values(
        ["_order", *([group_by] if group_by != "none" else [])], kind="mergesort")

    rows = []
    for record in grouped.to_dict(orient="records"):
        record.pop("_order")
        record["arrears_amount"] = rounded(float(record["arrears_amount"]), 3)
        record["exposure_at_risk"] = rounded(float(record["exposure_at_risk"]), 3)
        record["facility_count"] = int(record["facility_count"])
        record["instalments_missed"] = int(record["instalments_missed"])
        record["share_of_facilities_pct"] = rounded(
            safe_ratio(record["facility_count"], total), 3)
        rows.append(record)
    return rows


# ==================================================== credit file signals


#: The concerns the credit file records, with the column each is carried in.
#: Named here rather than discovered from the data so a new column cannot
#: silently change what this analysis reports.
SIGNALS: list[tuple[str, str]] = [
    ("covenant_breach_mentioned", "Covenant breach"),
    ("liquidity_concern_mentioned", "Liquidity concern"),
    ("going_concern_mentioned", "Going concern"),
    ("management_change_mentioned", "Management change"),
    ("sector_headwind_mentioned", "Sector headwind"),
    ("receivables_stretch_mentioned", "Receivables stretch"),
]

MEMO_FIELDS = [
    "memo_id", "customer_id", "borrower_name", "sector", "region", "memo_type",
    "author_role", "sentiment", "concerns_raised", "recommendation",
    *[column for column, _ in SIGNALS],
]


@register(AnalysisContract(
    id="credit_file_signals",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is what the credit file says rather than what "
        "the numbers say — which concerns the notes raised in a period, and "
        "how often."
    ),
    trigger_questions=[
        "What are the credit memos flagging?",
        "How many covenant breaches were written up?",
        "What is the tone of the credit file this quarter?",
        "Which sectors are the notes worried about?",
    ],
    limitations=(
        "Counts what the notes say, not whether they were right. This is "
        "commentary, and a concern raised is not evidence of a loss — no "
        "predictive relationship between these signals and outcomes has been "
        "established or is claimed."
    ),
    required_domains=[CREDIT_FILE_COMMENTARY],
    name="Credit File Signals",
    description=(
        "What the credit file raised in a period: how many notes were written, "
        "the balance of sentiment, and how often each tracked concern — "
        "covenant breach, liquidity, going concern, management change, sector "
        "headwind, receivables — was mentioned."
    ),
    category=Category.INVESTIGATE,
    version="1.0.0",
    owner="Credit Risk Analytics",
    certification=Certification.CERTIFIED,
    required_datasets=[MEMOS],
    required_fields=MEMO_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("group_by", ParamType.ENUM,
                  "Optional dimension to break the signals down by.",
                  default="none",
                  allowed_values=["none", "sector", "region", "memo_type"]),
    ],
    outputs=[
        OutputField("signal", "The concern raised.", "string"),
        OutputField("mentions", "Notes mentioning it.", "integer"),
        OutputField("borrowers", "Distinct borrowers it was raised against.",
                    "integer"),
        OutputField("share_of_notes_pct", "Mentions as a share of notes written.",
                    "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("mentions_within_notes",
                       "A signal cannot be mentioned more times than there are "
                       "notes."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Counts the notes written in the period and, for each of the six "
        "tracked concerns, how many of them mention it and how many distinct "
        "borrowers it was raised against. Sentiment is taken from the data "
        "rather than re-derived. No weighting, no scoring, and no inference "
        "from a concern to an outcome."
    ),
))
def credit_file_signals(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, MEMOS, ctx.params.get("period"), None,
    )
    group_by = str(ctx.params.get("group_by") or "none")

    frame, _ = ctx.read(MEMOS, fields=MEMO_FIELDS, period=period,
                        label=f"Credit file notes · {period}")

    notes = len(frame)
    sentiment = frame["sentiment"].value_counts().to_dict()
    headline = {
        "notes_written": float(notes),
        "borrowers_reviewed": float(frame["customer_id"].nunique()),
        "negative_notes": float(int(sentiment.get("negative", 0))),
        "mixed_notes": float(int(sentiment.get("mixed", 0))),
        "positive_notes": float(int(sentiment.get("positive", 0))),
        "negative_share_pct": rounded(
            safe_ratio(int(sentiment.get("negative", 0)), notes), 3),
        "mean_concerns_per_note": rounded(
            float(pd.to_numeric(frame["concerns_raised"], errors="coerce").fillna(0).mean()), 3),
    }
    ctx.step(NodeType.AGGREGATION, f"Aggregate {notes:,} credit file notes",
             config={"measures": list(headline)},
             rows_in=notes, rows_out=1, summary=headline)

    rows = []
    for column, label in SIGNALS:
        flagged = frame[frame[column].fillna(False).astype(bool)]
        row = {
            "signal": label,
            "mentions": int(len(flagged)),
            "borrowers": int(flagged["customer_id"].nunique()),
            "share_of_notes_pct": rounded(safe_ratio(len(flagged), notes), 3),
        }
        if group_by != "none" and len(flagged):
            top = flagged[group_by].value_counts()
            row["most_in"] = str(top.index[0])
            row["most_in_count"] = int(top.iloc[0])
        rows.append(row)

        if len(flagged) > notes:  # pragma: no cover - arithmetic guard
            ctx.warn(f"{label} counted {len(flagged)} times across {notes} notes.")

    rows.sort(key=lambda r: r["mentions"], reverse=True)
    ctx.step(NodeType.AGGREGATION, "Count each tracked concern",
             config={"signals": [label for _, label in SIGNALS],
                     "group_by": group_by},
             rows_in=notes, rows_out=len(rows))

    return AnalysisResult(
        rows=rows,
        values={**headline, "period": period, "group_by": group_by,
                "periods_available": available},
        units={"negative_share_pct": "%"},
        input_row_count=notes,
        warnings=ctx.warnings,
        meta={"grain": "One row per credit file note.",
              "text_origin": "Extracts are synthetic, assembled from a fixed "
                             "sentence bank.",
              "claims": "Descriptive only. No predictive relationship between "
                        "these signals and credit outcomes is established or "
                        "claimed."},
    )
