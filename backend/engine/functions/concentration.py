"""
Concentration, security and behaviour analyses.

The questions a credit committee asks that are not about staging: who are we
most exposed to, what is standing behind that exposure, how is each year's
lending performing, and what moved onto the watchlist since last time.

Every function is deterministic and takes no input from a language model except
parameters the contract has already validated.
"""

from __future__ import annotations

import numpy as np
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


# ==================================================== obligor concentration

OBLIGOR_FIELDS = [
    "customer_id", "borrower_name", "obligor_group", "sector", "segment",
    "region", "ead", "total_ecl", "ifrs9_stage", "internal_grade",
]


@register(AnalysisContract(
    id="obligor_concentration",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.RANKING,
    when_to_use=(
        "Use when the question is single-name concentration — who the bank is most "
        "exposed to, and how much of the book the largest names account for."
    ),
    trigger_questions=[
        "Who are our largest exposures?",
        "How concentrated is the book by borrower?",
        "What share do the top twenty names carry?",
        "Show me single-name concentration.",
    ],
    limitations=(
        "Aggregates by customer, and by obligor group where one is recorded. "
        "Economic connections that were never recorded as a group are invisible "
        "to it, which is a data question rather than an analytical one."
    ),
    required_domains=[FACILITY_POSITION],
    name="Obligor Concentration",
    description=(
        "The largest exposures by borrower and by obligor group, with the share "
        "of the book they carry and the Herfindahl index of the whole "
        "distribution."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=OBLIGOR_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("top_n", ParamType.INTEGER,
                  "How many names to return.", default=20, minimum=1, maximum=200),
    ],
    outputs=[
        OutputField("total_ead", "Total exposure at default.", "number", unit="USD mn", precision=2),
        OutputField("top_20_share_pct", "Share of exposure carried by the twenty largest borrowers.", "number", unit="%", precision=2),
        OutputField("hhi", "Herfindahl-Hirschman index of the borrower distribution.", "number", unit="index", precision=1),
        OutputField("borrowers", "Distinct borrowers.", "integer"),
    ],
    validation_rules=[
        ValidationRule("shares_sum_to_one",
                       "Borrower shares must sum to the whole book."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Sums exposure per customer and ranks them. The Herfindahl index is the "
        "sum of squared percentage shares across ALL borrowers, not only the ones "
        "displayed — a concentration measure computed on a top-twenty list would "
        "always look concentrated."
    ),
))
def obligor_concentration(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("period"), None
    )
    top_n = int(ctx.params.get("top_n", 20))
    df, _ = ctx.read(FACILITY, fields=OBLIGOR_FIELDS, period=period,
                     label=f"Portfolio facilities · {period}")

    df["ead"] = pd.to_numeric(df["ead"], errors="coerce").fillna(0.0)
    df["total_ecl"] = pd.to_numeric(df["total_ecl"], errors="coerce").fillna(0.0)
    total_ead = float(df["ead"].sum())

    by_customer = (
        df.groupby(["customer_id", "borrower_name"], dropna=False)
        .agg(ead=("ead", "sum"), total_ecl=("total_ecl", "sum"),
             facilities=("customer_id", "count"), sector=("sector", "first"),
             segment=("segment", "first"), region=("region", "first"),
             worst_grade=("internal_grade", "max"))
        .reset_index()
        .sort_values("ead", ascending=False)
    )
    by_customer["share_pct"] = (100.0 * by_customer["ead"] / total_ead).round(4)
    by_customer["cumulative_share_pct"] = by_customer["share_pct"].cumsum().round(3)
    by_customer["ead"] = by_customer["ead"].round(2)
    by_customer["total_ecl"] = by_customer["total_ecl"].round(3)

    ctx.step(NodeType.AGGREGATION,
             f"Aggregate {len(df):,} facilities into {len(by_customer):,} borrowers",
             config={"group_by": ["customer_id"], "measures": ["ead", "total_ecl"]},
             rows_in=int(len(df)), rows_out=int(len(by_customer)))

    # HHI on the FULL distribution. Computing it on the displayed rows only would
    # report the same high number for any book.
    hhi = float((by_customer["share_pct"] ** 2).sum())
    ctx.step(NodeType.CALCULATION, "Herfindahl-Hirschman index",
             config={"basis": "sum of squared percentage shares across all "
                              f"{len(by_customer):,} borrowers, not the displayed rows"},
             summary={"hhi": rounded(hhi, 1)})

    groups = df[df["obligor_group"].astype(str).str.len() > 0]
    by_group = (
        groups.groupby("obligor_group", dropna=False)
        .agg(ead=("ead", "sum"), borrowers=("customer_id", "nunique"))
        .reset_index()
        .sort_values("ead", ascending=False)
        .head(10)
    )
    by_group["ead"] = by_group["ead"].round(2)
    by_group["share_pct"] = (100.0 * by_group["ead"] / total_ead).round(3)

    share_total = float(by_customer["share_pct"].sum())
    if abs(share_total - 100.0) > 0.5:
        ctx.warn(
            f"Borrower shares sum to {share_total:.2f}% rather than 100%. Some "
            "facilities carry no customer identifier."
        )

    return AnalysisResult(
        rows=frame_to_rows(by_customer.head(top_n)[[
            "borrower_name", "sector", "segment", "region", "facilities",
            "ead", "share_pct", "cumulative_share_pct", "total_ecl", "worst_grade",
        ]]),
        values={
            "period": period,
            "total_ead": rounded(total_ead, 2),
            "borrowers": int(len(by_customer)),
            "top_10_share_pct": rounded(float(by_customer["share_pct"].head(10).sum()), 3),
            "top_20_share_pct": rounded(float(by_customer["share_pct"].head(20).sum()), 3),
            "largest_borrower": str(by_customer["borrower_name"].iloc[0]) if len(by_customer) else "",
            "largest_borrower_ead": float(by_customer["ead"].iloc[0]) if len(by_customer) else 0.0,
            "hhi": rounded(hhi, 1),
            "obligor_groups": frame_to_rows(by_group),
            "periods_available": available,
        },
        units={"ead": "USD mn", "total_ecl": "USD mn", "share_pct": "%",
               "cumulative_share_pct": "%", "hhi": "index"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per borrower.",
              "hhi": "Computed on every borrower, not on the displayed rows."},
    )


# ====================================================== collateral coverage

COLLATERAL_FIELDS = [
    "account_id", "ead", "collateral_value", "collateral_type", "lgd_pct",
    "ifrs9_stage", "total_ecl", "sector", "segment",
]


@register(AnalysisContract(
    id="collateral_coverage",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is what stands behind the exposure — how much is "
        "secured, by what, and where the unsecured shortfall sits."
    ),
    trigger_questions=[
        "How much of the book is secured?",
        "What is our collateral coverage?",
        "Where is the unsecured exposure?",
        "Which collateral types are we relying on?",
    ],
    limitations=(
        "Uses the recorded collateral value at the reporting date. It applies no "
        "haircut and makes no judgement about whether that valuation is current."
    ),
    required_domains=[FACILITY_POSITION],
    name="Collateral Coverage",
    description=(
        "Exposure against recorded collateral by security type, with the "
        "unsecured shortfall and the loss given default that goes with it."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=COLLATERAL_FIELDS,
    parameters=[PERIOD_PARAM],
    outputs=[
        OutputField("coverage_pct", "Collateral value as a percentage of exposure.", "number", unit="%", precision=2),
        OutputField("unsecured_ead", "Exposure with no collateral against it.", "number", unit="USD mn", precision=2),
        OutputField("shortfall_ead", "Exposure in excess of collateral value.", "number", unit="USD mn", precision=2),
        OutputField("weighted_lgd_pct", "EAD-weighted loss given default.", "number", unit="%", precision=2),
    ],
    validation_rules=[
        ValidationRule("collateral_non_negative", "Collateral value cannot be negative."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Groups facilities by collateral type and sums exposure and collateral. "
        "Coverage is summed collateral over summed exposure. The shortfall is "
        "computed per facility and then summed, never as total exposure less "
        "total collateral — netting an over-secured facility against an "
        "under-secured one would hide the exposure that is actually at risk."
    ),
))
def collateral_coverage(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("period"), None
    )
    df, _ = ctx.read(FACILITY, fields=COLLATERAL_FIELDS, period=period,
                     label=f"Portfolio facilities · {period}")

    df["ead"] = pd.to_numeric(df["ead"], errors="coerce").fillna(0.0)
    df["collateral_value"] = pd.to_numeric(
        df["collateral_value"], errors="coerce"
    ).fillna(0.0)
    negative = int((df["collateral_value"] < 0).sum())
    if negative:
        ctx.warn(f"{negative:,} facilities record a negative collateral value.")

    # Per facility, then summed. Netting first would let a heavily over-secured
    # facility cancel out an unsecured one and report no shortfall at all.
    df["shortfall"] = (df["ead"] - df["collateral_value"]).clip(lower=0.0)
    ctx.step(NodeType.CALCULATION, "Shortfall per facility, then summed",
             config={"formula": "max(EAD - collateral, 0) per facility",
                     "why": "netting across facilities would hide unsecured exposure"},
             rows_in=int(len(df)), rows_out=int(len(df)))

    grouped = (
        df.groupby("collateral_type", dropna=False)
        .agg(facilities=("account_id", "count"), ead=("ead", "sum"),
             collateral=("collateral_value", "sum"), shortfall=("shortfall", "sum"),
             total_ecl=("total_ecl", "sum"))
        .reset_index()
        .sort_values("ead", ascending=False)
    )
    grouped["coverage_pct"] = grouped.apply(
        lambda r: rounded(safe_ratio(r["collateral"], r["ead"]), 2), axis=1
    )
    for column in ("ead", "collateral", "shortfall", "total_ecl"):
        grouped[column] = pd.to_numeric(grouped[column], errors="coerce").round(2)

    ctx.step(NodeType.AGGREGATION, f"Group {len(df):,} facilities by collateral type",
             config={"group_by": ["collateral_type"]},
             rows_in=int(len(df)), rows_out=int(len(grouped)))

    total_ead = float(df["ead"].sum())
    unsecured = float(df.loc[df["collateral_value"] <= 0, "ead"].sum())

    return AnalysisResult(
        rows=frame_to_rows(grouped),
        values={
            "period": period,
            "total_ead": rounded(total_ead, 2),
            "total_collateral": rounded(float(df["collateral_value"].sum()), 2),
            "coverage_pct": rounded(
                safe_ratio(float(df["collateral_value"].sum()), total_ead), 2
            ),
            "unsecured_ead": rounded(unsecured, 2),
            "unsecured_pct": rounded(safe_ratio(unsecured, total_ead), 2),
            "shortfall_ead": rounded(float(df["shortfall"].sum()), 2),
            "weighted_lgd_pct": rounded(weighted_average(df["lgd_pct"], df["ead"]), 2),
            "periods_available": available,
        },
        units={"ead": "USD mn", "collateral": "USD mn", "shortfall": "USD mn",
               "total_ecl": "USD mn", "coverage_pct": "%"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per collateral type.",
              "note": "Recorded valuations, with no haircut applied."},
    )


# ======================================================= watchlist movement

WATCHLIST_FIELDS = [
    "account_id", "customer_id", "borrower_name", "sector", "segment", "ead",
    "watchlist", "ifrs9_stage", "internal_grade", "severity", "trigger_type",
    "total_ecl",
]


@register(AnalysisContract(
    id="watchlist_movement",
    period_requirement=PeriodRequirement.TWO_PERIOD,
    governed_default_period=False,
    answer_shape=AnswerShape.MOVEMENT,
    when_to_use=(
        "Use when the question is what joined or left the watchlist between two "
        "reporting dates, rather than how big the watchlist is."
    ),
    trigger_questions=[
        "What went on the watchlist this quarter?",
        "Who came off the watchlist?",
        "How has the watchlist changed?",
        "What are the new watchlist additions?",
    ],
    limitations=(
        "Compares two published snapshots. A facility that joined and left "
        "between them is invisible, and a facility not present in both periods "
        "cannot be classified as either an addition or a removal."
    ),
    required_domains=[FACILITY_POSITION],
    name="Watchlist Movement",
    description=(
        "Facilities that joined the watchlist, left it, or stayed on it between "
        "two reporting periods, with the exposure moving in each direction."
    ),
    category=Category.DETECT,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=WATCHLIST_FIELDS,
    parameters=[
        Parameter("from_period", ParamType.PERIOD,
                  "The earlier reporting period.", default="previous"),
        Parameter("to_period", ParamType.PERIOD,
                  "The later reporting period.", default="latest"),
        Parameter("top_n", ParamType.INTEGER,
                  "How many additions to list.", default=20, minimum=1, maximum=200),
    ],
    outputs=[
        OutputField("additions", "Facilities that joined the watchlist.", "integer"),
        OutputField("removals", "Facilities that came off it.", "integer"),
        OutputField("additions_ead", "Exposure that joined.", "number", unit="USD mn", precision=2),
        OutputField("net_ead", "Exposure joining less exposure leaving.", "number", unit="USD mn", precision=2),
    ],
    validation_rules=[
        ValidationRule("both_periods_present",
                       "A facility must appear in both periods to be classified."),
    ],
    supported_visualizations=[VisualizationType.TABLE, VisualizationType.BAR],
    calculation_description=(
        "Joins the two periods on facility identifier and classifies each "
        "facility present in both: on the watchlist now but not before is an "
        "addition; before but not now is a removal. Facilities present in only "
        "one period are counted separately and never classified, because there is "
        "no movement to observe."
    ),
))
def watchlist_movement(ctx: ExecutionContext) -> AnalysisResult:
    from_period, to_period, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("to_period"),
        ctx.params.get("from_period"),
    )
    top_n = int(ctx.params.get("top_n", 20))
    if not from_period or from_period == to_period:
        raise ValueError(
            "Watchlist movement needs two different reporting periods. "
            f"Available: {', '.join(available)}."
        )

    later, later_node = ctx.read(FACILITY, fields=WATCHLIST_FIELDS, period=to_period,
                                 label=f"Portfolio facilities · {to_period}")
    earlier, earlier_node = ctx.read(FACILITY, fields=WATCHLIST_FIELDS,
                                     period=from_period,
                                     label=f"Portfolio facilities · {from_period}",
                                     parents=[later_node])

    later = later.set_index("account_id")
    earlier = earlier.set_index("account_id")
    common = later.index.intersection(earlier.index)
    ctx.step(NodeType.TRANSFORMATION, f"Match facilities across {from_period} and {to_period}",
             parents=[later_node, earlier_node],
             config={"key": "account_id",
                     "unmatched": "counted but never classified — there is no "
                                  "movement to observe"},
             rows_in=int(len(later) + len(earlier)), rows_out=int(len(common)))

    now = later.loc[common, "watchlist"].fillna(False).astype(bool)
    before = earlier.loc[common, "watchlist"].fillna(False).astype(bool)
    ead = pd.to_numeric(later.loc[common, "ead"], errors="coerce").fillna(0.0)

    added = common[np.asarray(now & ~before)]
    removed = common[np.asarray(~now & before)]
    stayed = common[np.asarray(now & before)]

    additions = later.loc[added].reset_index().assign(
        ead=lambda d: pd.to_numeric(d["ead"], errors="coerce").fillna(0.0).round(2)
    ).sort_values("ead", ascending=False)

    return AnalysisResult(
        rows=frame_to_rows(additions.head(top_n)[[
            "account_id", "borrower_name", "sector", "segment", "ead",
            "ifrs9_stage", "internal_grade", "severity", "trigger_type",
        ]]),
        values={
            "from_period": from_period,
            "to_period": to_period,
            "additions": int(len(added)),
            "removals": int(len(removed)),
            "remained": int(len(stayed)),
            "additions_ead": rounded(float(ead[np.asarray(now & ~before)].sum()), 2),
            "removals_ead": rounded(
                float(pd.to_numeric(earlier.loc[removed, "ead"], errors="coerce")
                      .fillna(0.0).sum()), 2
            ),
            "net_ead": rounded(
                float(ead[np.asarray(now & ~before)].sum())
                - float(pd.to_numeric(earlier.loc[removed, "ead"], errors="coerce")
                        .fillna(0.0).sum()), 2
            ),
            "facilities_compared": int(len(common)),
            "new_facilities": int(len(later.index.difference(earlier.index))),
            "departed_facilities": int(len(earlier.index.difference(later.index))),
            "periods_available": available,
        },
        units={"ead": "USD mn"},
        input_row_count=int(len(common)),
        warnings=ctx.warnings,
        meta={"grain": "One row per watchlist addition.",
              "note": "Only facilities present in both periods are classified."},
    )


# ======================================================== utilisation drift

DRIFT_FIELDS = [
    "account_id", "customer_id", "borrower_name", "sector", "segment",
    "ead", "limit_amount", "utilisation_pct", "prev_utilisation_pct",
    "ifrs9_stage", "internal_grade", "dscr",
]


@register(AnalysisContract(
    id="utilisation_drift",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.RANKING,
    when_to_use=(
        "Use when the question is who is drawing down — the earliest behavioural "
        "sign of a borrower running short of cash."
    ),
    trigger_questions=[
        "Who is drawing down their facilities?",
        "Where has utilisation jumped?",
        "Show me the biggest utilisation increases.",
        "Which borrowers are using more of their limits?",
    ],
    limitations=(
        "Utilisation rises for ordinary commercial reasons as well as distressed "
        "ones. This ranks the movement; it does not establish a cause."
    ),
    required_domains=[FACILITY_POSITION],
    name="Utilisation Drift",
    description=(
        "Facilities ranked by the increase in utilisation since the previous "
        "reporting date, with the undrawn headroom that remains."
    ),
    category=Category.DETECT,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[FACILITY],
    required_fields=DRIFT_FIELDS,
    parameters=[
        PERIOD_PARAM,
        Parameter("top_n", ParamType.INTEGER,
                  "How many facilities to return.", default=20, minimum=1, maximum=200),
        Parameter("minimum_move_pp", ParamType.NUMBER,
                  "Ignore movements smaller than this, in percentage points.",
                  default=5.0, minimum=0.0, maximum=100.0),
    ],
    outputs=[
        OutputField("facilities_drawing", "Facilities whose utilisation rose by at least the minimum.", "integer"),
        OutputField("drawing_ead", "Exposure of those facilities.", "number", unit="USD mn", precision=2),
        OutputField("largest_move_pp", "The largest single increase.", "number", unit="pp", precision=2),
        OutputField("remaining_headroom", "Undrawn limit still available to them.", "number", unit="USD mn", precision=2),
    ],
    validation_rules=[
        ValidationRule("previous_utilisation_present",
                       "A facility needs a previous utilisation to have a movement."),
    ],
    supported_visualizations=[VisualizationType.TABLE, VisualizationType.BAR],
    calculation_description=(
        "Subtracts the previous reporting date's utilisation from the current "
        "one, in percentage points, and ranks facilities whose increase clears "
        "the minimum. The remaining headroom is limit less exposure — how much "
        "more the borrower could still draw."
    ),
))
def utilisation_drift(ctx: ExecutionContext) -> AnalysisResult:
    period, _, available = resolve_periods(
        ctx.source, FACILITY, ctx.params.get("period"), None
    )
    top_n = int(ctx.params.get("top_n", 20))
    minimum = float(ctx.params.get("minimum_move_pp", 5.0))

    df, _ = ctx.read(FACILITY, fields=DRIFT_FIELDS, period=period,
                     label=f"Portfolio facilities · {period}")

    current = pd.to_numeric(df["utilisation_pct"], errors="coerce")
    previous = pd.to_numeric(df["prev_utilisation_pct"], errors="coerce")
    missing = int(previous.isna().sum())
    if missing:
        ctx.warn(
            f"{missing:,} facilities have no previous utilisation recorded and "
            "cannot show a movement."
        )

    df = df.assign(
        utilisation_move_pp=(current - previous).round(3),
        ead=pd.to_numeric(df["ead"], errors="coerce").fillna(0.0),
        headroom=(
            pd.to_numeric(df["limit_amount"], errors="coerce").fillna(0.0)
            - pd.to_numeric(df["ead"], errors="coerce").fillna(0.0)
        ).clip(lower=0.0).round(3),
    )
    ctx.step(NodeType.CALCULATION, "Utilisation movement since the previous date",
             config={"formula": "current utilisation - previous utilisation",
                     "unit": "percentage points"},
             rows_in=int(len(df)), rows_out=int(len(df)))

    drawing = df[df["utilisation_move_pp"] >= minimum].copy()
    ctx.step(NodeType.FILTER, f"Movements of at least {minimum:g}pp",
             config={"minimum_move_pp": minimum},
             rows_in=int(len(df)), rows_out=int(len(drawing)))

    ranked = drawing.sort_values(
        ["utilisation_move_pp", "ead"], ascending=[False, False]
    ).head(top_n)

    return AnalysisResult(
        rows=frame_to_rows(ranked[[
            "account_id", "borrower_name", "sector", "segment", "ead",
            "prev_utilisation_pct", "utilisation_pct", "utilisation_move_pp",
            "headroom", "ifrs9_stage", "internal_grade", "dscr",
        ]]),
        values={
            "period": period,
            "minimum_move_pp": minimum,
            "facilities_drawing": int(len(drawing)),
            "drawing_ead": rounded(float(drawing["ead"].sum()), 2),
            "largest_move_pp": rounded(
                float(drawing["utilisation_move_pp"].max()) if len(drawing) else 0.0, 2
            ),
            "remaining_headroom": rounded(float(drawing["headroom"].sum()), 2),
            "periods_available": available,
        },
        units={"ead": "USD mn", "utilisation_pct": "%", "prev_utilisation_pct": "%",
               "utilisation_move_pp": "pp", "headroom": "USD mn", "dscr": "x"},
        input_row_count=int(len(df)),
        warnings=ctx.warnings,
        meta={"grain": "One row per facility drawing down.",
              "note": "Ranks the movement. It does not establish a cause."},
    )
