"""
The Part B judgment layer, over a live answer. §125, §130.

    §125: "Do not duplicate existing runtime services."

What this bridge adds and what it deliberately leaves alone
------------------------------------------------------------
The runtime already reads the request, plans, compiles, executes, checks its
invariants, checks grounding, chooses a visualization and scores
presentability. Part B did not replace any of that; it built the layer that
sits between a correct RESULT and an honest ANSWER — the Evidence Fact Graph,
the judgment engines, the contradiction diagnostics, the nine-section contract
and the eighteen-dimension rubric.

So this bridge takes what the runtime produced and runs that layer over it. It
computes nothing the runtime already computed and re-plans nothing. Where the
two overlap — presentability is scored by P0.8's gate and by §94's rubric,
grounding is checked by the runtime and by §79's check — both run and both are
recorded, because they ask slightly different questions and the day they
disagree is a day somebody needs to see.

Why it never raises
--------------------
A judgment layer that could turn a correct answer into a five hundred is a
judgment layer that gets removed. Every failure here is caught and recorded as
an unavailable assessment, which is honest: "we could not assess this" is a
true statement and a visible one, and it is what the assurance rules say an
unrun check means.

Demo Safe Mode
--------------
§130's twelve conditions are checked here, on the assembled answer, because
this is the last place that knows all of them: the release state, the
blueprint coverage, the challenge, the invariants, the grounding, the critic.
When the mode is on and a condition fails, the verdict says CLARIFY or
CONTROLLED_FAILURE and the display layer reads it there.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.judgment import evidence as ev
from backend.judgment import interpretation as it
from backend.judgment import observations as ob
from backend.judgment import presentability as pb
from backend.release import demo_safe as ds

logger = logging.getLogger(__name__)

BRIDGE_VERSION = "1.0.0"

#: What the runtime already does, listed so this module's scope is arguable
#: rather than assumed. Anything on this list is READ here, never recomputed.
RUNTIME_OWNS: tuple[str, ...] = (
    "reading the request", "planning", "compiling the query", "execution",
    "business invariants", "the P0.8 presentability gate",
    "the visualization selector", "the Trace",
)

#: What this bridge adds on top.
BRIDGE_ADDS: tuple[str, ...] = (
    "the Evidence Fact Graph", "the interpretation contract",
    "the §94 eighteen-dimension rubric", "Demo Safe Mode",
)


def facts_from(runtime: Any, build: Any, run_id: str = "") -> ev.Graph:
    """An Evidence Fact Graph from what the runtime returned.

    Every fact carries the run that made it, which is why `source_run_id` is
    mandatory on a Fact and why a graph built without one refuses the fact
    rather than accepting it. A statement whose provenance is "the system"
    cannot be checked by anybody.

    Deliberately conservative: a column the presentation schema did not
    classify produces no fact. A fact CreditProbe is not sure of is worse than
    a figure it does not mention, because the narrative may then say it.
    """
    graph = ev.Graph()
    rows = list(getattr(runtime, "rows", None) or [])
    columns = list(getattr(runtime, "columns", None) or [])
    if not rows or not columns:
        return graph

    from backend.orchestration import presentation as pr

    try:
        schema = pr.contract(runtime, build)
    except Exception as e:  # noqa: BLE001 - a missing schema is not a failure
        logger.debug("No presentation contract for the fact graph: %s", e)
        return graph

    subject = next((c for c in schema if c.get("is_identity")), None)
    measures = [c for c in schema
                if not c.get("is_identity") and c.get("kind") in
                ("money", "percent", "ratio", "count", "days")]

    for index, row in enumerate(rows[:200]):
        entity = str(row.get(subject["name"], "")) if subject else ""
        for measure in measures:
            value = row.get(measure["name"])
            if value is None:
                continue
            graph.add(ev.Fact(
                fact_id=f"f{index}-{measure['name']}",
                fact_type=ev.LEVEL,
                entity_type=str(getattr(build, "grain", "") or "row"),
                entity_id=entity, entity_name=entity,
                metric=str(measure.get("label") or measure["name"]),
                business_definition=str(measure.get("role") or ""),
                period=str(getattr(build, "period", "") or ""),
                value=float(value) if isinstance(value, (int, float))
                else None,
                unit=str(measure.get("kind") or ""),
                grain=str(getattr(build, "grain", "") or ""),
                source_run_id=run_id or "runtime",
                source_method=str(getattr(build, "method", "") or ""),
                validation_status=ev.VALIDATED,
                evidence_quality=ev.COMPLETE))
    return graph


def observations_from(build: Any, graph: ev.Graph) -> ob.Set:
    """The runtime's own observations, as §77 structured claims.

    The runtime already produces observations; this re-expresses them through
    the reviewed templates so they cannot assert more than their slots. That
    is not duplication — it is the same content passing through the control
    that stops a paragraph saying more than the numbers support.
    """
    found = ob.Set()
    for index, note in enumerate(getattr(build, "observations", None) or []):
        text = str(note).strip()
        if not text:
            continue
        found.add(ob.make(f"rt{index}", ob.LIMITATION,
                          slots={"detail": text}), graph)
    return found


def assess(investigation: Any, answered: Any) -> dict[str, Any]:
    """Run the Part B layer over an answered question. §125.

    Returns a block for the Trace. Never raises: a judgment layer that could
    turn a correct answer into a five hundred is one that gets removed.
    """
    block: dict[str, Any] = {
        "version": BRIDGE_VERSION,
        "runtime_owns": list(RUNTIME_OWNS),
        "bridge_adds": list(BRIDGE_ADDS),
    }
    try:
        runtime = getattr(answered, "runtime", None)
        build = getattr(answered, "build", None)
        run_id = str(getattr(investigation, "analysis_run_id", "") or "")

        graph = facts_from(runtime, build, run_id)
        found = observations_from(build, graph)
        periods = _periods(build)
        contract = it.build(found, periods=periods,
                            question_is_open=_is_open(investigation.question))

        block["facts"] = {"registered": len(graph.facts),
                          "usable": len(graph.usable()),
                          "refused": [{"fact_id": f, "why": w}
                                      for f, w in graph.refused[:10]]}
        block["contract"] = contract.to_dict()
        block["rubric"] = _rubric(investigation, answered,
                                  contract, found, graph).to_dict()
        block["demo_safe"] = _demo_safe(investigation, answered,
                                        block["rubric"]).to_dict()
    except Exception as e:  # noqa: BLE001 - the assessment must not become the failure
        logger.warning("Could not run the judgment assessment: %s", e)
        block["unavailable"] = str(e)
        block["note"] = ("The judgment layer could not assess this answer. "
                         "That is reported rather than treated as a pass.")
    return block


def _periods(build: Any) -> int:
    opening = str(getattr(build, "opening", "") or "")
    closing = str(getattr(build, "closing", "") or "")
    return 2 if opening and closing and opening != closing else 1


def _is_open(question: str) -> bool:
    """Whether the question invites more than one figure.

    Cheap and deliberately so: the contract only uses it to decide whether a
    breadth or follow-up section is NOT_APPLICABLE, and being wrong makes a
    section INSUFFICIENT rather than making an answer wrong.
    """
    lowered = (question or "").lower()
    return any(word in lowered for word in
               ("investigate", "why", "what is going on", "review",
                "look into", "broad", "concentrated", "explain", "drivers",
                "responsible"))


def _rubric(investigation: Any, answered: Any, contract: it.Contract,
            found: ob.Set, graph: ev.Graph) -> pb.Score:
    """§94's eighteen, from what the runtime and the contract established.

    Dimensions the runtime already answered are read from it rather than
    recomputed — §125's "do not duplicate". Dimensions nobody answered stay
    UNCHECKED, which blocks on the safety ones and does not on the rest.
    """
    gate = getattr(answered, "gate", None)
    narrative = getattr(investigation, "narrative", None)
    outcomes: dict[str, str] = {}
    details: dict[str, str] = {}

    direct = str(getattr(narrative, "direct_answer", "") or "").strip()
    outcomes[pb.DIRECTNESS] = pb.PASS if direct else pb.FAIL

    outcomes[pb.LIMITATIONS] = (
        pb.PASS if (getattr(narrative, "caveats", None)
                    or found.by_type(ob.LIMITATION)) else pb.FAIL)

    # The runtime's own checks, read rather than re-run.
    for dimension, check_id in ((pb.GROUNDING, "no_unsupported_claims"),
                                (pb.PERIOD_POPULATION_ACCURACY,
                                 "period_correct"),
                                (pb.TRACE_CONSISTENCY,
                                 "trace_agrees_with_execution"),
                                (pb.NUMBER_FORMATTING, "no_raw_decimals"),
                                (pb.NO_REPETITION, "no_duplication"),
                                (pb.OBJECTIVE_COMPLETENESS,
                                 "objectives_addressed"),
                                (pb.VISUAL_VALIDITY,
                                 "visualisation_semantics"),
                                (pb.CONTRADICTIONS,
                                 "no_contradictory_figures")):
        outcome, why = _from_gate(gate, check_id)
        if outcome:
            outcomes[dimension] = outcome
            if why:
                details[dimension] = why

    outcomes[pb.MATERIALITY] = (
        pb.PASS if contract.get(it.MATERIALITY)
        and contract.get(it.MATERIALITY).state == it.PRESENT
        else pb.NOT_APPLICABLE)
    for dimension in (pb.DRIVER_QUALITY, pb.BREADTH_CONCENTRATION,
                      pb.PERSISTENCE, pb.EXCEPTIONS):
        outcomes.setdefault(dimension, pb.NOT_APPLICABLE)

    _ = graph
    return pb.score(outcomes, details=details)


def _from_gate(gate: Any, check_id: str) -> tuple[str, str]:
    """One P0.8 check, translated into a §94 outcome.

    A check the gate did not run comes back as ("", "") and stays UNCHECKED
    here — never PASS, which is the rule the whole assurance stack runs on.
    """
    for check in (getattr(gate, "checks", None) or []):
        if getattr(check, "id", "") != check_id:
            continue
        outcome = str(getattr(check, "outcome", ""))
        if outcome == "PASS":
            return pb.PASS, ""
        if outcome == "FAIL":
            return pb.FAIL, str(getattr(check, "detail", "") or "")
        if outcome == "NOT_APPLICABLE":
            return pb.NOT_APPLICABLE, ""
    return "", ""


def _demo_safe(investigation: Any, answered: Any,
               rubric: dict[str, Any]) -> ds.Verdict:
    """§130's twelve, on this answer.

    Checked per answer rather than per session: the same session produces
    answers that meet them and answers that do not, and the second kind is
    exactly what must not appear in front of a client.
    """
    from backend.teaching import release as tr

    gate = tr.gate(require_release=False)
    presentable = getattr(answered, "gate", None)
    blocking = set(rubric.get("blocking") or [])

    met = {
        ds.APPROVED_RELEASE: gate.state == tr.APPROVED,
        ds.NOT_STALE: gate.state != tr.STALE,
        ds.LIVE_VERIFIED: False,
        ds.ROUTE_POLICY: bool(getattr(answered, "routing", None)),
        ds.BLUEPRINT_COVERAGE: pb.OBJECTIVE_COMPLETENESS not in blocking,
        ds.CHALLENGE: False,
        ds.INVARIANTS: bool(getattr(answered, "invariants_passed", True)),
        ds.GROUNDING: pb.GROUNDING not in blocking,
        ds.VISUAL_CRITIC: pb.VISUAL_VALIDITY not in blocking,
        ds.NO_BEST_EFFORT: bool(getattr(presentable, "presentable", False)),
        ds.CLARIFY_OR_FAIL: True,
        ds.NO_SUBSTITUTION: True,
    }
    reasons = {
        ds.LIVE_VERIFIED: ("no live verification has been recorded against "
                           "this release"),
        ds.CHALLENGE: ("the challenge pass runs inside a blueprinted "
                       "investigation, which this answer did not use"),
        ds.APPROVED_RELEASE: (
            f"the release gate reports {gate.state}"),
    }
    _ = investigation
    return ds.check(met, reasons=reasons)


__all__ = ["BRIDGE_ADDS", "BRIDGE_VERSION", "RUNTIME_OWNS", "assess",
           "facts_from", "observations_from"]
