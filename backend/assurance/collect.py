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
from backend.assurance import signals as sg
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


def checks_for(investigation: Any, answered: Any, *, officer: Any = None,
               project_id: str = "", proactive: bool = False
               ) -> list[rc.Check]:
    """One check for every subcomponent. Ninety-five, every time.

    The collector no longer decides WHICH checks to emit — it emits all of
    them, and the outcome of each says what happened:

        a reader exists and judged        PASS / WARNING / FAIL
        a reader exists and found nothing SKIPPED
        a reader exists and it does not
          apply, with a stated reason     NOT_APPLICABLE
        no reader exists                  NOT_AVAILABLE

    That last line is the whole of §19. Before this, an unwired check was
    simply absent from the record, and absent checks are invisible: the
    coverage number quietly excluded them and nobody could tell an
    uninstrumented product from a well-behaved one. Now every gap is a row
    that says which system was supposed to produce the signal, and a
    critical gap blocks.
    """
    ctx = sg.Ctx.of(investigation, answered, officer=officer,
                    project_id=project_id, proactive=proactive)
    flow = flow_of(ctx)
    applies = _applicable(flow)
    checks: list[rc.Check] = []
    for name in dm.all_subcomponents():
        if name not in applies:
            # §21's applicability, established deterministically from the
            # flow class rather than from the question's wording. A
            # clarification has no result to reconcile, and counting the
            # result checks against it would report every clarification as
            # a broken analysis.
            checks.append(rc.check(
                name, rc.NOT_APPLICABLE,
                because=f"this check does not apply to a "
                        f"{flow.replace('_', ' ').lower()} turn"))
            continue
        checks.append(_check_for(name, ctx))
    return checks


def flow_of(ctx: sg.Ctx) -> str:
    """Which flow class this turn belongs to. §21."""
    try:
        from backend.proof import flows as fl

        return fl.classify(
            answer_type=ctx.status, executed=ctx.executed,
            datasets=len(ctx.datasets),
            agentic_run=ctx.outcome is not None,
            specialists=len(list(getattr(getattr(ctx.outcome, "plan", None),
                                         "agents", None) or [])),
            proactive=ctx.proactive, project_id=ctx.project_id)
    except Exception as e:  # noqa: BLE001 - classification is not the answer
        logger.warning("Could not classify the flow: %s", e)
        return ""


def _applicable(flow: str) -> frozenset[str]:
    """What applies to this flow, widest set where the flow is unknown.

    Unknown resolves to everything, so a turn nobody classified is harder
    to claim coverage for rather than easier.
    """
    try:
        from backend.proof import flows as fl

        return fl.applicable(flow) if flow else frozenset(
            dm.all_subcomponents())
    except Exception:  # pragma: no cover
        return frozenset(dm.all_subcomponents())


def _check_for(name: str, ctx: sg.Ctx) -> rc.Check:
    """One subcomponent, judged or honestly unjudged."""
    if name not in sg.READERS:
        return rc.Check(subcomponent=name, outcome=rc.NOT_AVAILABLE,
                        detail=_no_signal_detail(name))
    signal = sg.read(name, ctx)
    if signal is None:
        return rc.Check(
            subcomponent=name, outcome=rc.SKIPPED,
            detail="The signal for this check was absent on this turn.")
    if signal.outcome == rc.NOT_APPLICABLE:
        # §183 refuses an unreasoned NOT_APPLICABLE, and a reader that
        # returned one without a reason is a bug in the reader — reported as
        # SKIPPED rather than allowed through.
        if not signal.because.strip():
            return rc.Check(
                subcomponent=name, outcome=rc.SKIPPED,
                detail="This check reported not-applicable with no reason, "
                       "so it is recorded as skipped.")
        return rc.check(name, rc.NOT_APPLICABLE, because=signal.because)
    return rc.Check(subcomponent=name, outcome=signal.outcome,
                    detail=signal.detail, evidence=list(signal.evidence))


def _no_signal_detail(name: str) -> str:
    """Why a subcomponent has no reader, quoting the Coverage Map.

    Names the system that owes the signal, so the record itself is the work
    list. "No signal exists" is unactionable; "the judgment drivers engine
    does not emit drivers.decomposition" is a ticket.
    """
    try:
        from backend.proof import coverage as cvg

        entry = cvg.MAP.get(name)
    except Exception:  # pragma: no cover - the map is optional at runtime
        entry = None
    if entry is None:
        return ("No signal exists for this check and it is not in the "
                "Coverage Map.")
    if entry.state == cvg.OUT_OF_BAND:
        return (f"This check is verified outside the backend record "
                f"({entry.source_system}"
                + (f"; see {entry.test}" if entry.test else "") + ").")
    return (f"Not yet instrumented: {entry.source_system} does not emit "
            f"{entry.source_field}. Owner: {entry.owner or 'unassigned'}.")


def build(investigation: Any, answered: Any, *,
          investigation_id: str = "", answer_id: str = "",
          user_id: int | None = None, project_id: str = "",
          turn_index: int = 0, officer: Any = None,
          proactive: bool = False) -> rc.Record:
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
        made.checks = checks_for(investigation, answered, officer=officer,
                                 project_id=project_id, proactive=proactive)
    except Exception as e:  # noqa: BLE001 - the record is not the answer
        logger.warning("Could not collect assurance checks: %s", e)
        made.checks = []

    try:
        from backend.build_info import build_info

        info = build_info()
        made.build_sha = info.sha or ""
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
                     "turn_index", "officer", "proactive")})
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
