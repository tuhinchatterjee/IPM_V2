"""
The officer experience on a user's own question. §4–§11, §52–§55.

Every Ask gets an officer
-------------------------
§4 asks for one officer level on *every* user-requested analysis, and this is
where that happens. It wraps the existing governed path rather than replacing
it: `answer_investigation` still does the reading, the planning, the execution,
the invariants and the narrative, exactly as before. What is added around it is

    a run row created BEFORE the analysis, so the stage is observable while
    the work happens rather than described after it;

    an officer level selected from the routing signals, re-read once the
    reading exists, and escalated (never demoted) if the work turned out
    wider than the sentence;

    coordination, for the questions that genuinely need it.

Why the officer is chosen twice
-------------------------------
The first selection sees only the sentence, and it has to be immediate — the
indicator appears the moment the user presses Ask. The second sees how many
datasets, concepts and periods the reading actually needs, which is where most
of the difficulty lives. §9 calls the difference an escalation and asks for it
to be shown as a transition rather than as a correction, which is exactly what
it is: the request grew.

When coordination actually happens
-----------------------------------
Not on every question, and that restraint is the design. A question needing one
governed domain is one specialist's work, and putting a Chief Orchestrator in
front of it would add a title, a plan, an assurance pass and no information.
Coordination happens when the reading spans three or more governed domains — at
which point several specialists genuinely have to agree, and the reconciliation
is worth its cost.

No model is called here
-----------------------
`answer_one` is injected and defaults to the governed runtime, which decides for
itself whether a model is needed. Nothing in this module talks to a provider.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.agentic import (
    budgets as bg,
)
from backend.agentic import (
    dag,
    officers,
    orchestrator,
    principals,
    registry,
    runs,
    stages,
)
from backend.orchestration import routing as rt

logger = logging.getLogger(__name__)

#: How many governed domains make a question coordinated work. Three, matching
#: `officers.COORDINATED_AT`: two specialists is a comparison, three is a
#: reconciliation.
COORDINATE_AT = officers.COORDINATED_AT


@dataclass
class Answered:
    """One question, answered, with the officer record around it."""

    run_id: int | None = None
    run_key: str = ""
    selection: officers.Selection | None = None
    investigation: Any = None
    outcome: orchestrator.Outcome | None = None
    assurance: Any = None
    coordinated: bool = False
    escalated: bool = False

    def agentic(self) -> dict[str, Any]:
        """The block the response carries, for §11's completion line and §53's
        Coordinated Review."""
        chosen = self.selection.to_dict() if self.selection else {}
        found: dict[str, Any] = {
            "run_id": self.run_id,
            "run_key": self.run_key,
            "coordinated": self.coordinated,
            "escalated": self.escalated,
            **chosen,
        }
        if self.outcome is not None:
            found["specialists"] = [
                registry.agent(a).business_name for a in self.outcome.plan.agents
                if registry.agent(a)]
            found["summary"] = dag.summarise(self.outcome.plan)
            found["findings"] = list(self.outcome.findings)
            found["conflicts"] = [c.to_dict() for c in self.outcome.conflicts]
            found["limitations"] = list(self.outcome.limitations)
        if self.assurance is not None:
            found["assurance"] = self.assurance.to_dict()
        found["completion_line"] = self.completion_line()
        return found

    def completion_line(self) -> str:
        """§11's compact completion summary.

        Built from what actually ran. "Completed by Senior Credit Officer — 2
        datasets · 1 join · 4 calculations · all checks passed" is only worth
        showing if every part of it is true, so each part comes from a count.
        """
        title = self.selection.title if self.selection else "CreditProbe"
        if self.outcome is not None and self.coordinated:
            return (f"Coordinated by {title} — "
                    f"{dag.summarise(self.outcome.plan)}")
        parts = _investigation_parts(self.investigation)
        return (f"Completed by {title}" + (f" — {' · '.join(parts)}"
                                           if parts else ""))


def _investigation_parts(investigation: Any) -> list[str]:
    """The counts behind a single-specialist completion line."""
    if investigation is None:
        return []
    plan = getattr(investigation, "plan", None)
    datasets = sorted({str(d) for d in (getattr(plan, "datasets", ()) or ())})
    steps = list(getattr(investigation, "steps", ()) or ())
    found: list[str] = []
    if datasets:
        found.append(f"{len(datasets)} "
                     f"{'dataset' if len(datasets) == 1 else 'datasets'}")
    if steps:
        found.append(f"{len(steps)} "
                     f"{'calculation' if len(steps) == 1 else 'calculations'}")
    status = str(getattr(investigation, "status", "") or "")
    if status == "succeeded":
        found.append("all checks passed")
    return found


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def run(session: Any, *, question: str, user_id: int | None = None,
        role: str = "", project_id: int | None = None,
        investigation_id: int | None = None, run_id: int | None = None,
        period: tuple[str, str] | None = None,
        state: Any = None, memory: Any = None,
        answer_one: Callable[..., Any] | None = None,
        should_stop: Callable[[], bool] | None = None) -> Answered:
    """Answer one question, with the officer record around it.

    Returns an `Answered` carrying the Investigation the caller already expects
    plus the agentic block. Nothing about the Investigation is changed by
    passing through here — a caller that ignores `.agentic()` gets exactly what
    it got before.
    """
    from backend.orchestration.executor import answer_investigation

    stop = should_stop or (lambda: False)
    actor = principals.for_user(_principal(user_id, role))

    # §9's first reading: from the sentence alone, so the indicator can appear
    # the instant the user presses Ask.
    first = rt.decide(question)
    selection = officers.select(question, decision=first)

    budget = bg.Budget(limits=bg.INTERACTIVE)
    run_row = (runs.load(session, run_id) if run_id else None) or runs.start(
        session, trigger=runs.USER_QUESTION, question=question,
        user_id=user_id, role=role or actor.role,
        project_id=project_id, investigation_id=investigation_id,
        selection=selection, budget=budget)
    session.flush()

    found = Answered(run_id=run_row.id, run_key=run_row.run_key,
                     selection=selection)

    runs.advance(session, run_row, stages.UNDERSTANDING)
    session.flush()

    ask = answer_one or (lambda q, **kw: answer_investigation(
        q, user_id=user_id, project_id=project_id,
        investigation_id=investigation_id, persist=True, period=period,
        state=state, memory=memory)[0])

    try:
        runs.advance(session, run_row, stages.CALCULATING)
        session.flush()
        investigation = ask(question, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 - recorded on the run and re-raised
        runs.fail(session, run_row, reason=f"{type(exc).__name__}: {exc}",
                  kind="analysis_failed", budget=budget)
        raise

    found.investigation = investigation

    # §9's second reading: now that the reading exists, re-score. This is the
    # only place the level can move, and it can only move up.
    reading = _reading_of(investigation)
    specialists = registry.agents_for(_concepts_of(reading))
    second = rt.decide(question, reading=reading)
    later = officers.select(question, decision=second, reading=reading,
                            agents=len(specialists))
    if later.level > selection.level:
        selection = officers.escalate(
            selection, to=later.level, why=later.selection_reason)
        found.escalated = True
        found.selection = selection

    if _should_coordinate(specialists, investigation) and not stop():
        _coordinate(session, run_row, found, question, specialists, reading,
                    budget, actor, ask, stop)

    runs.advance(session, run_row, stages.INTERPRETING)
    found.assurance = _assurance(found, investigation)
    runs.finish(
        session, run_row,
        plan=found.outcome.plan if found.outcome else None,
        findings=found.outcome.findings if found.outcome else [],
        conflicts=found.outcome.conflicts if found.outcome else [],
        assurance=found.assurance,
        synthesis=(orchestrator.synthesise(found.outcome)
                   if found.outcome else ""),
        budget=budget,
        analysis_run_id=getattr(investigation, "analysis_run_id", None))

    # The escalation line is stored where `runs.live` reads it, so a client
    # polling the run sees the transition §9 asks for without a second call.
    plan_doc = dict(run_row.plan or {})
    plan_doc["escalation_line"] = selection.escalation_line()
    plan_doc["officer"] = selection.to_dict()
    run_row.plan = plan_doc
    run_row.officer_level = selection.level
    run_row.officer_title = selection.title
    run_row.selection_reason = selection.selection_reason
    session.flush()

    return found


def _coordinate(session: Any, run_row: Any, found: Answered, question: str,
                specialists: list[Any], reading: Any, budget: bg.Budget,
                actor: Any, ask: Callable[..., Any],
                stop: Callable[[], bool]) -> None:
    """Delegate to several specialists and reconcile what they find. §15."""
    periods = list(getattr(reading, "periods", ()) or ())
    plan = orchestrator.plan_for(
        question, concepts=_concepts_of(reading),
        scope=_scope_of(reading), specialists=specialists,
        period=periods[-1] if periods else "",
        prior_period=periods[0] if len(periods) >= 2 else "")

    found.selection = orchestrator.escalation_for(found.selection, plan)
    found.escalated = found.escalated or bool(found.selection.escalated_from)
    found.coordinated = True

    runs.record_plan(session, run_row, plan,
                     orchestrator=registry.CHIEF_ORCHESTRATOR.agent_id,
                     selection=found.selection)
    session.flush()

    found.outcome = orchestrator.execute(
        plan, answer_one=lambda q, **kw: ask(q, user_id=actor.user_id),
        budget=budget, actor=actor, should_stop=stop,
        on_task=lambda t: runs.update_task(session, run_row.id, t),
        on_stage=lambda s, d: runs.advance(session, run_row, s, detail=d,
                                           agents=len(plan.agents)))


def _should_coordinate(specialists: list[Any], investigation: Any) -> bool:
    """Is this genuinely coordinated work?

    Three governed domains, and an answer that actually computed something. A
    clarification or an unsupported request has nothing to coordinate, and
    putting a Chief Orchestrator in front of "which quarter did you mean" would
    be theatre.
    """
    if len(specialists) < COORDINATE_AT:
        return False
    return str(getattr(investigation, "status", "")) == "succeeded"


def _assurance(found: Answered, investigation: Any) -> Any:
    """The Answer Assurance view. §54.

    For a coordinated run it comes from the plan. For a single analysis it
    comes from what the runtime recorded — the invariants it checked and
    whether the written answer was grounded — never from anything a model said
    about its own confidence.
    """
    from backend.agentic import assurance as au

    if found.outcome is not None:
        return orchestrator.assess(found.outcome)

    narrative = getattr(investigation, "narrative", None)
    status = str(getattr(investigation, "status", "") or "")
    plan = getattr(investigation, "plan", None)
    datasets = list(getattr(plan, "datasets", ()) or ())

    class _Invariants:
        checks = tuple(getattr(narrative, "checks", ()) or ()) if narrative else ()
        failures = tuple(getattr(narrative, "warnings", ()) or ()) if narrative else ()

    class _Grounding:
        ungrounded = tuple(getattr(narrative, "ungrounded", ()) or ()) if narrative else ()

    return au.assess(
        plan=plan, tasks=[],
        invariants=_Invariants() if narrative else None,
        grounding=_Grounding() if narrative else None,
        relationships_used=max(0, len(datasets) - 1),
        relationships_governed=max(0, len(datasets) - 1),
        limitations=([] if status == "succeeded"
                     else [f"The analysis finished as '{status}'."]))


# ---------------------------------------------------------------------------
# Reading what the runtime produced
# ---------------------------------------------------------------------------


def _reading_of(investigation: Any) -> Any:
    """A reading-shaped view of what the analysis actually used.

    The Investigation carries a plan rather than the Reading the router
    produced, so this reconstructs what the officer selection needs from it.
    Duck-typed on purpose: `officers` reads attributes, and constructing a real
    `capability.Reading` here would couple the agentic layer to a class it has
    no other reason to know.
    """
    plan = getattr(investigation, "plan", None)

    class _Reading:
        datasets = tuple(getattr(plan, "datasets", ()) or ())
        concepts = tuple(_concept_names(plan))
        metrics = concepts
        periods = tuple(_periods_of(plan))
        period_requirement = "two_period" if len(periods) >= 2 else "point_in_time"
        grain = str(getattr(getattr(plan, "scope", None), "grain", "") or "")
        dimensions = ()
        operation_count = len(list(getattr(investigation, "steps", ()) or ()))
        confidence = 1.0
        clarification = ""

    return _Reading()


def _concept_names(plan: Any) -> list[str]:
    """Governed concept ids the plan measured.

    Read from the plan's own measures where it has them, falling back to the
    ontology's vocabulary against the plan's intent. A concept this cannot
    resolve simply does not add a specialist, which is the safe direction: a
    missing specialist is a narrower plan, an invented one is a task nothing
    can answer.
    """
    from backend.agentic import registry as reg

    found: list[str] = []
    for attribute in ("concepts", "measures", "metrics"):
        for value in (getattr(plan, attribute, ()) or ()):
            name = str(getattr(value, "concept_id", None)
                       or getattr(value, "id", None) or value).lower()
            if reg.domain_of(name) and name not in found:
                found.append(name)
    return found


def _periods_of(plan: Any) -> list[str]:
    scope = getattr(plan, "scope", None)
    found = [str(getattr(scope, "period", "") or ""),
             str(getattr(scope, "compare_period", "") or "")]
    return [p for p in found if p]


def _concepts_of(reading: Any) -> list[str]:
    return [str(c) for c in (getattr(reading, "concepts", ()) or ())]


def _scope_of(reading: Any) -> dict[str, Any]:
    grain = str(getattr(reading, "grain", "") or "")
    if grain in {"sector", "segment"}:
        return {"segment": "the portfolio"}
    return {"entity": "the portfolio"}


def _principal(user_id: int | None, role: str) -> Any:
    from backend.api.permissions import Principal, Role

    try:
        chosen = Role(str(role).upper()) if role else Role.ANALYST
    except ValueError:
        chosen = Role.ANALYST
    return Principal(user_id=user_id, role=chosen)


__all__ = ["COORDINATE_AT", "Answered", "run"]
