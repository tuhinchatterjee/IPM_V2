"""Governed analyses over the derived corporate graph. Phase 4.

The rule this module exists to enforce: **a graph question is answered by an
analysis, not by prose.** Asking "which connected groups are closest to the
group limit" must run a registered, versioned, deterministic function over a
governed dataset and produce a Trace - not a paragraph a language model
composed from a retrieved summary. Every figure on this page can be pointed
at a row.

Each analysis reads `corporate_connected_groups`, which the derivation
produced at build time. Nothing here recomputes DebtRank or a control
closure: a screen that recomputes an analytic disagrees with the export
beside it, and the disagreement is found by a client rather than by a test.

What every one of them refuses to do
------------------------------------
None of these presents a network measure as a credit measure. The Network
Risk Score carries its banner into the result metadata, DebtRank carries its
caveat, and the group figures carry UNVERIFIED REGULATORY PARAMETER. A number
that travels without its caveat is a number that will be quoted without it.
"""

from __future__ import annotations

import pandas as pd

from backend.corporate import graphsummary as gs
from backend.corporate import network as net
from backend.data_access import catalog as catalog_mod
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
from backend.engine.helpers import frame_to_rows, resolve_periods, rounded
from backend.engine.registry import AnalysisResult, register
from backend.trace.model import NodeType

OWNER = "Group Risk"
GROUPS = gs.GROUPS_DATASET
DQ = gs.DQ_DATASET
GRAPH_DOMAIN = catalog_mod.CORPORATE_CONNECTED_GROUP
QUALITY_DOMAIN = catalog_mod.CORPORATE_GRAPH_QUALITY

PERIOD_PARAM = Parameter(
    "period", ParamType.PERIOD,
    "Reporting quarter. Accepts a quarter label, or 'latest' / 'earliest'.",
    default="latest",
)
TOP_N = Parameter(
    "top_n", ParamType.INTEGER, "How many rows to return.",
    default=20, minimum=1, maximum=200,
)

#: Said on every result carrying a network measure. B54.
NETWORK_CAVEAT = f"{net.NRS_LABEL} {net.DEBTRANK_CAVEAT}"
GROUP_CAVEAT = (
    "A connected-counterparty CANDIDATE group. Graph connectivity is not "
    "regulatory connectedness: these are candidates for assessment under the "
    "institution's own approved criteria, not a determination. The group "
    "limit threshold is an UNVERIFIED REGULATORY PARAMETER."
)


def _read_groups(ctx: ExecutionContext, fields: list[str],
                 period: str | None) -> tuple[pd.DataFrame, str]:
    resolved, _, _ = resolve_periods(ctx.source, GROUPS, period, None)
    frame, node = ctx.read(
        GROUPS, fields=fields, period=resolved,
        label=f"Derived corporate graph · {resolved}")
    return frame, resolved


def _blocked_note(frame: pd.DataFrame, status_column: str) -> str:
    """What was excluded, and why - never silently dropped."""
    if status_column not in frame.columns:
        return ""
    counts = frame[status_column].value_counts().to_dict()
    absent = {k: int(v) for k, v in counts.items() if k != gs.AVAILABLE}
    if not absent:
        return ""
    parts = ", ".join(f"{count} {status}" for status, count
                      in sorted(absent.items()))
    return (f"{sum(absent.values())} borrower(s) carry no value for this "
            f"measure and are not ranked: {parts}. They are excluded because "
            "they have no measurement, which is different from measuring "
            "zero.")


# ============================================== connected group exposure

GROUP_FIELDS = [
    "borrower_id", "connected_group_id", "group_name", "connected_group_size",
    "group_role", "group_exposure", "group_utilisation_pct",
    "group_limit_pct", "group_utilisation_status", "group_status",
]


@register(AnalysisContract(
    id="connected_group_exposure",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.RANKING,
    when_to_use=(
        "Use when the question is about exposure to a GROUP rather than to a "
        "single borrower: which connected counterparty groups carry the most "
        "exposure, and which are closest to the group limit."
    ),
    trigger_questions=[
        "Which connected groups carry the most exposure?",
        "Which groups are closest to the group limit?",
        "Show me group concentration.",
        "Are any connected counterparty groups in breach?",
    ],
    limitations=(
        "The groups are CANDIDATES derived from control and validated "
        "economic interdependence. Graph connectivity is not regulatory "
        "connectedness, and the limit threshold is an unverified parameter "
        "carried from a framework document rather than confirmed law."
    ),
    required_domains=[GRAPH_DOMAIN],
    name="Connected Group Exposure",
    description=(
        "Connected counterparty groups ranked by total exposure, with their "
        "utilisation of the eligible capital reference and their position "
        "against the group limit."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[GROUPS],
    required_fields=GROUP_FIELDS,
    parameters=[PERIOD_PARAM, TOP_N],
    outputs=[
        OutputField("groups", "Distinct connected groups.", "integer"),
        OutputField("largest_group_size", "Members in the largest group.",
                    "integer"),
        OutputField("breaching", "Groups at or above the group limit.",
                    "integer"),
        OutputField("investigating",
                    "Groups above the investigation trigger.", "integer"),
        OutputField("standalone_borrowers",
                    "Borrowers in no derived group.", "integer"),
    ],
    validation_rules=[
        ValidationRule("group_is_a_candidate",
                       "Every group figure carries B54's caveat."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Reads the derived groups for the quarter, takes one row per group "
        "(every member carries the same group totals by construction) and "
        "ranks by group exposure. Borrowers in no group are counted "
        "separately rather than shown as a group of one."
    ),
))
def connected_group_exposure(ctx: ExecutionContext) -> AnalysisResult:
    frame, period = _read_groups(ctx, GROUP_FIELDS, ctx.params.get("period"))
    top_n = int(ctx.params.get("top_n", 20))

    grouped = frame[frame["group_status"] == gs.AVAILABLE]
    standalone = int(len(frame) - len(grouped))

    per_group = (grouped
                 .sort_values("borrower_id")
                 .groupby("connected_group_id", as_index=False)
                 .first()[["connected_group_id", "group_name",
                           "connected_group_size", "group_exposure",
                           "group_utilisation_pct", "group_limit_pct",
                           "group_utilisation_status"]])
    ctx.step(NodeType.AGGREGATION,
             f"One row per group from {len(grouped):,} member rows",
             config={"group_by": ["connected_group_id"],
                     "note": "every member carries the same group totals by "
                             "construction, so the first row is the group"},
             rows_in=int(len(grouped)), rows_out=int(len(per_group)))

    per_group = per_group.sort_values("group_exposure", ascending=False)
    per_group["group_exposure"] = per_group["group_exposure"].round(2)
    per_group["group_utilisation_pct"] = (
        per_group["group_utilisation_pct"].round(4))

    breaching = int((per_group["group_utilisation_status"] == "BREACH").sum())
    investigating = int(
        (per_group["group_utilisation_status"] == "INVESTIGATE").sum())

    ctx.step(NodeType.CALCULATION, "Position against the group limit",
             config={"thresholds": "UNVERIFIED REGULATORY PARAMETER"},
             summary={"breaching": breaching,
                      "investigating": investigating})

    return AnalysisResult(
        rows=frame_to_rows(per_group.head(top_n)),
        values={
            "groups": int(len(per_group)),
            "largest_group_size": int(per_group["connected_group_size"].max())
            if len(per_group) else 0,
            "breaching": breaching,
            "investigating": investigating,
            "standalone_borrowers": standalone,
        },
        input_row_count=int(len(frame)),
        meta={"period": period,
              "caveat": GROUP_CAVEAT,
              "derivation": "control closure, then validated economic "
                            "interdependence - never weak components over "
                            "raw shareholdings"},
    )


# ================================================== network centrality

CENTRALITY_FIELDS = [
    "borrower_id", "network_risk_score", "network_risk_score_status",
    "debtrank_impact", "debtrank_status", "pagerank_transmits",
    "pagerank_hurt", "betweenness", "centrality_status",
    "exposure_network_links", "connected_group_id",
]


@register(AnalysisContract(
    id="network_risk_ranking",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.RANKING,
    when_to_use=(
        "Use when the question is about a borrower's POSITION in the "
        "relationship network - who transmits, who is exposed to "
        "transmission, who sits on the paths between others."
    ),
    trigger_questions=[
        "Which borrowers are most central in the network?",
        "Who would take the most of the network down with them?",
        "Rank borrowers by network risk score.",
        "Which borrowers transmit the most distress?",
    ],
    limitations=(
        "A RELATIVE RANKING within this population, not a probability. It is "
        "not a PD, not a rating, not an IFRS 9 stage and not an expected "
        "credit loss. Borrowers with no financial claims have no measurement "
        "and are excluded rather than ranked at zero."
    ),
    required_domains=[GRAPH_DOMAIN],
    name="Network Risk Ranking",
    description=(
        "Borrowers ranked by Network Risk Score, with the three measures "
        "behind it: DebtRank impact, forward PageRank and betweenness."
    ),
    category=Category.DETECT,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[GROUPS],
    required_fields=CENTRALITY_FIELDS,
    parameters=[PERIOD_PARAM, TOP_N],
    outputs=[
        OutputField("ranked", "Borrowers with a network measurement.",
                    "integer"),
        OutputField("unmeasured",
                    "Borrowers with no network measurement.", "integer"),
        OutputField("highest_score", "The top Network Risk Score.", "number",
                    unit="index", precision=2),
        OutputField("mean_score", "Mean score across the ranked population.",
                    "number", unit="index", precision=2),
    ],
    validation_rules=[
        ValidationRule("ranking_not_probability",
                       "The score carries its banner into the result."),
        ValidationRule("unmeasured_excluded",
                       "A borrower with no measurement is not ranked at "
                       "zero."),
    ],
    supported_visualizations=[VisualizationType.BAR, VisualizationType.TABLE],
    calculation_description=(
        "Reads the derived network measures for the quarter and ranks by "
        "Network Risk Score, which is 100 x (0.45 x normalised DebtRank + "
        "0.35 x normalised forward PageRank + 0.20 x normalised "
        "betweenness). The components are returned alongside the score "
        "because a borrower can be high on one and low on the others."
    ),
))
def network_risk_ranking(ctx: ExecutionContext) -> AnalysisResult:
    frame, period = _read_groups(ctx, CENTRALITY_FIELDS,
                                 ctx.params.get("period"))
    top_n = int(ctx.params.get("top_n", 20))

    note = _blocked_note(frame, "network_risk_score_status")
    ranked = frame[frame["network_risk_score_status"] == gs.AVAILABLE].copy()
    if note:
        ctx.warn(note)
    ctx.step(NodeType.FILTER,
             "Exclude borrowers with no network measurement",
             config={"rule": "a borrower outside the exposure network has no "
                             "score; ranking it at zero would read as 'no "
                             "network risk' rather than 'no network'"},
             rows_in=int(len(frame)), rows_out=int(len(ranked)))

    ranked = ranked.sort_values(
        ["network_risk_score", "borrower_id"], ascending=[False, True])
    for column in ("network_risk_score",):
        ranked[column] = ranked[column].round(2)
    for column in ("debtrank_impact", "pagerank_transmits", "pagerank_hurt",
                   "betweenness"):
        ranked[column] = ranked[column].round(6)

    return AnalysisResult(
        rows=frame_to_rows(ranked.head(top_n)[[
            "borrower_id", "network_risk_score", "debtrank_impact",
            "pagerank_transmits", "pagerank_hurt", "betweenness",
            "exposure_network_links", "connected_group_id"]]),
        values={
            "ranked": int(len(ranked)),
            "unmeasured": int(len(frame) - len(ranked)),
            "highest_score": rounded(
                float(ranked["network_risk_score"].max()), 2)
            if len(ranked) else None,
            "mean_score": rounded(
                float(ranked["network_risk_score"].mean()), 2)
            if len(ranked) else None,
        },
        input_row_count=int(len(frame)),
        warnings=[note] if note else [],
        meta={"period": period,
              "caveat": NETWORK_CAVEAT,
              "weights": dict(net.NRS_WEIGHTS),
              "excluded": note},
    )


# =================================================== ownership and control

OWNERSHIP_FIELDS = [
    "borrower_id", "effective_ownership_group_id", "control_group_id",
    "group_role", "ubo_count", "director_count", "ownership_status",
    "graph_confidence", "relationship_confidence", "graph_dq_status",
]


@register(AnalysisContract(
    id="ownership_and_control_structure",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.DISTRIBUTION,
    when_to_use=(
        "Use when the question is about who owns and who controls: how the "
        "book splits by group role, how many borrowers have an identified "
        "ultimate beneficial owner, and how well evidenced that is."
    ),
    trigger_questions=[
        "How many borrowers have an identified ultimate beneficial owner?",
        "How does the book split between parents, subsidiaries and "
        "standalone companies?",
        "Which borrowers have no identified owner?",
        "How well evidenced is our ownership data?",
    ],
    limitations=(
        "Control is computed over VOTING rights and is binary, absorptive "
        "and transitive. It is NOT proportional ownership and the two give "
        "different sets by design. Borrowers whose ownership component was "
        "rejected by a data-quality check are reported as blocked, not as "
        "having no owner."
    ),
    required_domains=[GRAPH_DOMAIN],
    name="Ownership and Control Structure",
    description=(
        "How the book divides by group role, how many borrowers have an "
        "identified beneficial owner, and the confidence of the evidence "
        "underneath."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[GROUPS],
    required_fields=OWNERSHIP_FIELDS,
    parameters=[PERIOD_PARAM],
    outputs=[
        OutputField("borrowers", "Borrowers in the quarter.", "integer"),
        OutputField("with_identified_ubo",
                    "Borrowers with at least one beneficial owner above the "
                    "threshold.", "integer"),
        OutputField("no_identified_ubo",
                    "Borrowers with no owner above the threshold.",
                    "integer"),
        OutputField("ownership_blocked",
                    "Borrowers whose ownership was refused by a "
                    "data-quality check.", "integer"),
        OutputField("mean_weakest_confidence",
                    "Mean of the weakest evidence confidence.", "number",
                    unit="ratio", precision=4),
    ],
    validation_rules=[
        ValidationRule("blocked_is_not_absent",
                       "A refused computation is counted separately from an "
                       "absent owner."),
    ],
    supported_visualizations=[VisualizationType.PIE, VisualizationType.BAR,
                              VisualizationType.TABLE],
    calculation_description=(
        "Counts borrowers by group role and by whether a beneficial owner "
        "above the 25% integrated-ownership threshold was identified. "
        "Borrowers whose ownership component was REJECTED are a third "
        "category: the computation did not run, which is not the same as "
        "running and finding nobody."
    ),
))
def ownership_and_control_structure(ctx: ExecutionContext) -> AnalysisResult:
    frame, period = _read_groups(ctx, OWNERSHIP_FIELDS,
                                 ctx.params.get("period"))

    blocked = frame[frame["ownership_status"] != gs.AVAILABLE]
    measured = frame[frame["ownership_status"] == gs.AVAILABLE]
    with_ubo = measured[measured["ubo_count"] > 0]

    ctx.step(NodeType.CALCULATION,
             "Split identified, not identified, and refused",
             config={"rule": "a refused ownership computation is a third "
                             "category; counting it as 'no owner' would "
                             "report a data-quality defect as a fact about "
                             "the borrower"},
             summary={"identified": int(len(with_ubo)),
                      "not_identified": int(len(measured) - len(with_ubo)),
                      "refused": int(len(blocked))})

    by_role = (frame.groupby("group_role", as_index=False)
               .agg(borrowers=("borrower_id", "count"),
                    mean_directors=("director_count", "mean"))
               .sort_values("borrowers", ascending=False))
    by_role["mean_directors"] = by_role["mean_directors"].round(2)
    by_role["share_pct"] = (
        100.0 * by_role["borrowers"] / max(len(frame), 1)).round(2)

    by_quality = (frame.groupby("graph_dq_status", as_index=False)
                  .agg(borrowers=("borrower_id", "count"))
                  .sort_values("borrowers", ascending=False))
    by_quality["share_pct"] = (
        100.0 * by_quality["borrowers"] / max(len(frame), 1)).round(2)

    return AnalysisResult(
        rows=frame_to_rows(by_role),
        values={
            "borrowers": int(len(frame)),
            "with_identified_ubo": int(len(with_ubo)),
            "no_identified_ubo": int(len(measured) - len(with_ubo)),
            "ownership_blocked": int(len(blocked)),
            "mean_weakest_confidence": rounded(
                float(frame["graph_confidence"].mean()), 4),
        },
        input_row_count=int(len(frame)),
        meta={
            "period": period,
            "by_evidence_quality": frame_to_rows(by_quality),
            "caveat": (
                "Control is binary, absorptive and transitive, and is "
                "computed over VOTING rights. It is NOT proportional "
                "ownership: 51% of 51% is 26% of the economics and 100% of "
                "the control."),
            "ubo_threshold_pct": gs.OWNERSHIP_GROUP_THRESHOLD_PCT,
        },
    )


# ==================================================== graph data quality

DQ_FIELDS = ["issue_id", "check_id", "check", "status", "observed",
             "threshold", "scope", "affected_entities", "blocks"]


@register(AnalysisContract(
    id="graph_data_quality",
    period_requirement=PeriodRequirement.POINT_IN_TIME,
    governed_default_period=True,
    answer_shape=AnswerShape.LIST,
    when_to_use=(
        "Use when the question is whether the relationship graph can be "
        "trusted this quarter, or which derived figures were blocked by a "
        "data-quality refusal."
    ),
    trigger_questions=[
        "Can we trust the relationship graph this quarter?",
        "What data-quality checks failed on the graph?",
        "Which network figures were blocked?",
        "Show me the graph data-quality register.",
    ],
    limitations=(
        "Reports the checks as they ran. A PASS means the check found "
        "nothing it tests for, not that the data is correct."
    ),
    required_domains=[QUALITY_DOMAIN],
    name="Graph Data Quality",
    description=(
        "The fifteen graph data-quality checks for the quarter, what each "
        "observed, and which derived computations a REJECT blocked."
    ),
    category=Category.MONITOR,
    version="1.0.0",
    owner=OWNER,
    certification=Certification.CERTIFIED,
    required_datasets=[DQ],
    required_fields=DQ_FIELDS,
    parameters=[PERIOD_PARAM],
    outputs=[
        OutputField("checks_run", "Checks that ran.", "integer"),
        OutputField("passed", "Checks that found nothing.", "integer"),
        OutputField("flagged", "Checks a reviewer should see.", "integer"),
        OutputField("rejected", "Checks that blocked a computation.",
                    "integer"),
        OutputField("overall_status", "PASS, FLAG or REJECT.", "string"),
    ],
    validation_rules=[
        ValidationRule("reject_blocks",
                       "A REJECT names the computations it stopped."),
    ],
    supported_visualizations=[VisualizationType.TABLE],
    calculation_description=(
        "Reads the persisted quality register for the quarter. The register "
        "is written by the derivation, so the checks reported here are the "
        "ones that were actually running when the figures were produced."
    ),
))
def graph_data_quality(ctx: ExecutionContext) -> AnalysisResult:
    resolved, _, _ = resolve_periods(ctx.source, DQ,
                                     ctx.params.get("period"), None)
    frame, _ = ctx.read(DQ, fields=DQ_FIELDS, period=resolved,
                        label=f"Graph data-quality register · {resolved}")
    frame = frame.sort_values("check_id")

    counts = frame["status"].value_counts().to_dict()
    rejected = int(counts.get("REJECT", 0))
    flagged = int(counts.get("FLAG", 0))

    ctx.step(NodeType.CALCULATION, "Overall verdict",
             config={"rule": "REJECT if any check rejected, else FLAG if any "
                             "flagged, else PASS"},
             summary={"rejected": rejected, "flagged": flagged})

    return AnalysisResult(
        rows=frame_to_rows(frame),
        values={
            "checks_run": int(len(frame)),
            "passed": int(counts.get("PASS", 0)),
            "flagged": flagged,
            "rejected": rejected,
            "overall_status": ("REJECT" if rejected else
                               "FLAG" if flagged else "PASS"),
        },
        input_row_count=int(len(frame)),
        meta={"period": resolved,
              "blocking_rule": (
            "A REJECT blocks the derived computation that depends on it. "
            "Borrower fields elsewhere reading DATA_QUALITY_BLOCKED were not "
            "computed, and the reason is in this register.")},
    )
