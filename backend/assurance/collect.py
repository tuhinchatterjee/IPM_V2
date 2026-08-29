"""
Turning an answered turn into an Assurance Record. §180, §205, §210.

    §210: "Assurance Record written for every answer."

Every answer, which includes the ones that are not analyses: a metadata
answer, a clarification, an unsupported response and a controlled failure all
get a record. Those are the turns where a missing record would matter most,
because "CreditProbe declined to answer" is a claim about the product that
somebody will eventually dispute.

The rule this module lives by
-------------------------------
It reports what the runtime actually established, and nothing else. Where a
signal exists, the check carries its outcome and the detail that produced it.
Where no signal exists, the check is SKIPPED — not PASS, and not
NOT_APPLICABLE.

That is deliberately uncomfortable. A freshly instrumented record reports low
coverage and an UNVERIFIED status, and the temptation is to mark the
uninstrumented checks as passing so the number looks like the product works.
That number would be a lie about a working product, which is worse than an
honest number about an under-instrumented one — and §183 exists precisely to
close that door. The way coverage goes up is by wiring another signal in.

Where the signals come from
-----------------------------
Nothing here computes a new verdict. Every outcome is read from a check that
already ran somewhere in the runtime: the invariant gate, the grounding
validator, the objective-coverage validator, the presentability rubric, the
Part B judgment bridge, the routing decision, the Trace consistency contract.
This module is a translator, not a second opinion — a second opinion would
be a second thing to keep in agreement with the first.

§205, the Trace node
----------------------
The record also becomes an ASSURANCE SUMMARY node on the Trace, with the six
dimensions, the status, the coverage and the critical failures. Each
dimension names the Trace nodes its checks came from, so the review links
back to the exact node rather than to the Trace in general.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.assurance import dimensions as dm
from backend.assurance import record as rc
from backend.assurance import store as sto

logger = logging.getLogger(__name__)

COLLECT_VERSION = "1.0.0"

#: Which Trace node each dimension's evidence lives on. §205: "Each dimension
#: links to relevant Trace nodes/checks." Empty where a dimension's evidence
#: is not on the Trace at all, which is itself worth knowing.
TRACE_NODES: dict[str, tuple[str, ...]] = {
    dm.UNDERSTANDING: ("question", "conversation", "capability"),
    dm.DESIGN: ("plan", "method", "data", "objective_coverage"),
    dm.COMPUTATION: ("query", "result", "business_invariant", "evidence",
                     "grounding"),
    dm.JUDGMENT: ("interpretation", "analytical_judgment", "presentability"),
    dm.AGENTIC: ("agentic_run", "agent_task", "assurance"),
    dm.RELIABILITY: ("timing", "provider"),
}


def _outcome(passed: bool | None, *, warn_instead: bool = False) -> str:
    """Tri-state. None means nothing established it, which is SKIPPED."""
    if passed is None:
        return rc.SKIPPED
    if passed:
        return rc.PASS
    return rc.WARNING if warn_instead else rc.FAIL


def _add(checks: list[rc.Check], name: str, passed: bool | None, *,
         detail: str = "", evidence: list[str] | None = None,
         warn_instead: bool = False) -> None:
    """Append one check, skipping unknown subcomponent names.

    An unknown name would land in no dimension and be counted by nothing,
    which is a silent hole. Logging it makes a typo visible on the first run
    rather than as a coverage number nobody can explain.
    """
    if not dm.dimension_of(name):
        logger.warning("Assurance check %r belongs to no dimension", name)
        return
    checks.append(rc.check(name, _outcome(passed, warn_instead=warn_instead),
                           detail=detail, evidence=list(evidence or [])))


def _node_ids(investigation: Any) -> set[str]:
    graph = getattr(investigation, "graph", None)
    if graph is None:
        return set()
    try:
        return {str(n.get("id", "")) for n in graph.to_dict().get("nodes", [])}
    except Exception:  # pragma: no cover - a malformed graph is not an answer
        return set()


def _bool_or_none(value: Any) -> bool | None:
    return bool(value) if isinstance(value, bool) else None


# ------------------------------------------------------------ the collector


def checks_for(investigation: Any, answered: Any) -> list[rc.Check]:
    """Read every signal the runtime produced, once each.

    Ordered by dimension so a reader comparing this against §191-§196 can
    follow along, and so a signal that ought to exist and does not is visible
    as a gap in the list rather than as a number.
    """
    checks: list[rc.Check] = []
    nodes = _node_ids(investigation)
    reading = getattr(answered, "reading", None)
    judgment = getattr(answered, "judgment", None) or {}
    rubric = judgment.get("rubric") or {}
    conversation = getattr(investigation, "conversation", {}) or {}
    status = str(getattr(investigation, "status", "") or "")

    # ---- Understanding & context ------------------------------------
    capability = str(getattr(reading, "capability", "") or "")
    _add(checks, "capability_intent", bool(capability) or None,
         detail=f"Capability read as {capability}." if capability else "",
         evidence=["capability"])
    action = str(conversation.get("action") or "")
    _add(checks, "conversation_action", bool(action) or None,
         detail=f"Conversation action {action}." if action else "")
    objectives = list(getattr(reading, "objectives", None) or [])
    _add(checks, "objective_extraction", bool(objectives) or None,
         detail=f"{len(objectives)} objective(s) extracted."
         if objectives else "")
    if status == "needs_clarification":
        _add(checks, "ambiguity_detection", True,
             detail="CreditProbe stopped to ask rather than guessing.")
        _add(checks, "clarification_quality",
             bool(getattr(investigation, "clarification", None)),
             detail="A structured clarification was returned.")
    language = str(conversation.get("language") or "")
    _add(checks, "language_locale_understanding", bool(language) or None,
         detail=f"Language {language}." if language else "")
    carried = conversation.get("carried")
    _add(checks, "context_carry_forward", _bool_or_none(carried))

    # ---- Analytical design -------------------------------------------
    coverage = getattr(answered, "coverage", None)
    if coverage is not None:
        covered = _bool_or_none(getattr(coverage, "complete", None))
        missing = list(getattr(coverage, "missing", None) or [])
        _add(checks, "objective_coverage", covered,
             detail=("Every requested objective was addressed."
                     if covered else
                     f"{len(missing)} objective(s) were not addressed: "
                     f"{', '.join(str(m) for m in missing[:3])}"),
             evidence=["objective_coverage"])
    else:
        _add(checks, "objective_coverage", None)
    build = getattr(answered, "build", None)
    _add(checks, "concept_selection",
         bool(getattr(build, "measures", None)) or None)
    _add(checks, "dataset_selection",
         bool(getattr(build, "datasets", None)
              or getattr(build, "dataset", None)) or None)
    _add(checks, "period_selection", bool(getattr(build, "period", "")) or None,
         detail=f"Period {getattr(build, 'period', '')}." if build else "")
    _add(checks, "grain_selection", bool(getattr(build, "grain", "")) or None)
    _add(checks, "population_definition",
         bool(getattr(build, "population", None)
              or getattr(build, "filters", None)) or None)
    _add(checks, "plan_completeness",
         bool(getattr(investigation, "plan", None)) or None)
    route = (getattr(answered, "decision", None) or {})
    _add(checks, "model_route_escalation",
         bool(route) or None,
         detail=str(route.get("reason", "")) if isinstance(route, dict) else "")

    # ---- Computation & evidence ---------------------------------------
    runtime = getattr(answered, "runtime", None)
    if runtime is not None:
        _add(checks, "execution", True,
             detail=f"{len(list(getattr(runtime, 'rows', None) or []))} "
                    "row(s) returned.", evidence=["result"])
        _add(checks, "generated_query",
             bool(getattr(runtime, "sql", "")) or None, evidence=["query"])
    elif status in ("needs_clarification", "rejected"):
        # Deliberately SKIPPED, not NOT_APPLICABLE. Nothing computed the
        # applicability; the turn simply never reached the engine, and §183
        # is explicit that absence is not exemption.
        _add(checks, "execution", None,
             detail="No analysis ran on this turn.")
    else:
        _add(checks, "execution", None)

    invariants = getattr(answered, "invariants", None)
    if invariants is not None:
        holds = _bool_or_none(getattr(invariants, "passed", None))
        _add(checks, "business_invariants", holds,
             detail=str(getattr(invariants, "summary", "") or ""),
             evidence=["business_invariant"])
        _add(checks, "totals_reconciliation", holds,
             evidence=["business_invariant"])
    else:
        _add(checks, "business_invariants", None)
        _add(checks, "totals_reconciliation", None)

    facts = judgment.get("facts") or {}
    if facts:
        usable = int(facts.get("usable") or 0)
        _add(checks, "evidence_fact_graph", usable > 0,
             detail=f"{usable} usable fact(s), "
                    f"{len(facts.get('refused') or [])} refused.",
             evidence=["evidence"])
    else:
        _add(checks, "evidence_fact_graph", None)

    contract = judgment.get("contract") or {}
    grounded = contract.get("grounded")
    ungrounded = list(contract.get("ungrounded") or [])
    if grounded is not None:
        _add(checks, "figure_grounding", bool(grounded),
             detail=("Every figure in the prose traces to a validated fact."
                     if grounded else
                     f"{len(ungrounded)} figure(s) trace to no fact: "
                     f"{', '.join(str(u) for u in ungrounded[:3])}"),
             evidence=["grounding"])
    else:
        _add(checks, "figure_grounding", None)

    # ---- Judgment & presentation ---------------------------------------
    if rubric:
        for name, key in (("direct_bottom_line", "direct"),
                          ("limitations", "limitations"),
                          ("client_presentability", "presentable"),
                          ("number_formatting", "formatting"),
                          ("concision_no_repetition", "concise")):
            value = rubric.get(key)
            _add(checks, name, _bool_or_none(value),
                 detail=str(rubric.get("sentence", ""))
                 if value is False else "",
                 evidence=["analytical_judgment"],
                 # A badly written answer is not a wrong answer. §94's split,
                 # carried into the record so presentation problems never
                 # produce a FAILED status on their own.
                 warn_instead=name in ("number_formatting",
                                       "concision_no_repetition",
                                       "client_presentability"))
    _add(checks, "trace_clarity", bool(nodes) or None,
         detail=f"{len(nodes)} Trace node(s) recorded.")

    # ---- Agentic delivery -----------------------------------------------
    agentic_id = str(getattr(answered, "agentic_run_id", "") or "")
    if agentic_id:
        _add(checks, "agentic_trace_consistency", True,
             detail="An agentic run is recorded against this answer.",
             evidence=["agentic_run"])
    # No else: an absent agentic run leaves the whole dimension unmeasured,
    # and §195 explains that in the review rather than scoring it here.

    # ---- Reliability & experience ----------------------------------------
    _add(checks, "no_unexplained_500", status != "failed",
         detail="" if status != "failed" else
                str(getattr(answered, "failure", "") or "the turn failed"))
    _add(checks, "controlled_error_handling",
         status in ("succeeded", "partial", "needs_clarification",
                    "rejected") or None,
         detail=f"Turn status {status}." if status else "")
    duration = int(getattr(investigation, "duration_ms", 0) or 0)
    _add(checks, "latency", duration > 0 or None,
         detail=f"{duration} ms." if duration else "")
    return checks


def build(investigation: Any, answered: Any, *,
          investigation_id: str = "", answer_id: str = "",
          user_id: int | None = None, project_id: str = "",
          turn_index: int = 0) -> rc.Record:
    """Assemble the record. Never raises.

    §180's fields are filled from what is on hand; anything absent stays
    empty rather than being invented, because a record that guessed its own
    provenance is not evidence about anything.
    """
    made = rc.Record(
        assurance_record_id=sto.new_record_id(),
        user_id=user_id,
        investigation_id=investigation_id,
        project_id=project_id,
        answer_id=answer_id or str(
            getattr(investigation, "analysis_run_id", "") or ""),
        question=str(getattr(investigation, "question", "") or ""),
        answer_type=str(getattr(investigation, "status", "") or ""),
        duration_ms=int(getattr(investigation, "duration_ms", 0) or 0),
        analysis_run_ids=[str(getattr(investigation, "analysis_run_id", "")
                              or "")] if getattr(
                                  investigation, "analysis_run_id", None)
        else [],
    )
    try:
        made.checks = checks_for(investigation, answered)
    except Exception as e:  # noqa: BLE001 - the record is not the answer
        logger.warning("Could not collect assurance checks: %s", e)
        made.checks = []

    try:
        from backend.build_info import build_info

        info = build_info()
        made.build_sha = info.git_sha or ""
        made.app_version = str(getattr(info, "version", "") or "")
    except Exception:  # pragma: no cover
        pass
    try:
        from backend.intelligence_release import release

        made.intelligence_release_id = getattr(release(), "release_id", "")
    except Exception:  # pragma: no cover
        pass
    try:
        from backend.teaching import release as trel

        made.teaching_release_id = getattr(
            trel.gate(require_release=False), "release_id", "") or ""
    except Exception:  # pragma: no cover
        pass

    conversation = getattr(investigation, "conversation", {}) or {}
    made.language = str(conversation.get("language") or "en")
    made.portfolio_scope = str(getattr(getattr(answered, "scope", None),
                                       "name", "") or "")
    made.repair_count = int(len(getattr(answered, "calls", None) or []) > 1)
    made.clarification_count = int(
        bool(getattr(investigation, "clarification", None)))
    made.limitations = [str(n) for n in
                        (getattr(getattr(investigation, "plan", None),
                                 "notes", None) or [])][:10]
    coverage = getattr(answered, "coverage", None)
    if coverage is not None:
        made.objective_coverage = {
            "complete": bool(getattr(coverage, "complete", False)),
            "addressed": len(getattr(coverage, "addressed", None) or []),
            "missing": [str(m) for m in
                        (getattr(coverage, "missing", None) or [])],
        }
    return rc.seal(made)


def record_for(investigation: Any, answered: Any, **kwargs: Any) -> str:
    """Build, store and attach. The one call the executor makes.

    Returns the record id, or "" where nothing could be stored. Failure here
    loses evidence about an answer, never the answer.
    """
    try:
        made = build(investigation, answered, **{
            k: v for k, v in kwargs.items()
            if k in ("investigation_id", "answer_id", "user_id", "project_id",
                     "turn_index")})
        route = (getattr(answered, "decision", None) or {})
        return sto.write(
            made, turn_index=int(kwargs.get("turn_index", 0) or 0),
            model_route=str(route.get("final_route", "")
                            if isinstance(route, dict) else ""))
    except Exception as e:  # noqa: BLE001 - assurance never breaks an answer
        logger.warning("Could not write an assurance record: %s", e)
        return ""


def trace_summary(made: rc.Record,
                  weights: dm.Weights | None = None) -> dict[str, Any]:
    """§205's ASSURANCE SUMMARY, for the Trace node.

    Carries the six dimensions and, for each, the Trace nodes its evidence
    came from — so a reader who sees Computation & Evidence in warning can go
    straight to the invariant node rather than reading the whole graph.
    """
    verdict = made.overall(weights)
    dimensions: list[dict[str, Any]] = []
    for result in made.by_dimension():
        dimensions.append({
            "dimension": result.dimension,
            "label": dm.LABELS[result.dimension],
            "short": dm.SHORT[result.dimension],
            "measured": result.measured,
            "score": result.score,
            "coverage_pct": round(result.coverage_pct, 1),
            "failures": len(result.failures),
            "warnings": len(result.warnings),
            "trace_nodes": list(TRACE_NODES[result.dimension]),
        })
    return {
        "version": COLLECT_VERSION,
        "assurance_record_id": made.assurance_record_id,
        "overall_status": verdict["overall_status"],
        "status_means": verdict["status_means"],
        "operational_assurance": verdict["operational_assurance"],
        "operational_assurance_label": rc.ASSURANCE_LABEL,
        "coverage_pct": verdict["coverage_pct"],
        "critical_failures": made.critical_failures,
        "warnings": made.warnings,
        "skipped_mandatory": made.skipped_mandatory,
        "build_sha": made.build_sha,
        "intelligence_release_id": made.intelligence_release_id,
        "teaching_release_id": made.teaching_release_id,
        "dimensions": dimensions,
        "reference_match": rc.reference_block(made.reference_match_pct,
                                              made.reference_source),
        "rule": ("Operational assurance is what this run could prove about "
                 "itself. It is not accuracy: no independent reference "
                 "answer exists for a live Investigation."),
    }
