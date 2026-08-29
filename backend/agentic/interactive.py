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
    #: What the orchestration layer reported about the turn — the reading, the
    #: route, the conversation state. Carried through so `threads.ask` can
    #: write memory back exactly as it did before this wrapper existed.
    answered: Any = None

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
        parts = _investigation_parts(self.investigation, self.answered)
        return (f"Completed by {title}" + (f" — {' · '.join(parts)}"
                                           if parts else ""))


def _investigation_parts(investigation: Any, answered: Any = None
                         ) -> list[str]:
    """The counts behind a single-specialist completion line.

    Derived from what the run left behind (P0.9), not from its status word.
    This line used to end with "all checks passed" whenever the run finished —
    `if status == "succeeded"` — so a catalogue lookup that succeeded at
    computing nothing reported that its checks had passed. There were no
    checks, and the same line called the lookup "1 calculation".
    """
    if investigation is None:
        return []
    from backend.agentic import consistency as cy

    plan = getattr(investigation, "plan", None)
    datasets = sorted({str(d) for d in (getattr(plan, "datasets", ()) or ())})
    found: list[str] = []
    if datasets:
        found.append(f"{len(datasets)} "
                     f"{'dataset' if len(datasets) == 1 else 'datasets'}")
    found.extend(cy.parts(cy.of_investigation(investigation, answered)))
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

    if answer_one is not None:
        ask = answer_one
    else:
        def ask(q: str, **_kw: Any) -> Any:
            # `answer_investigation` returns the Investigation AND what the
            # orchestration layer made of the turn. The caller needs both —
            # `threads.ask` writes conversation memory from the second — so it
            # is kept rather than discarded at the tuple unpack.
            #
            # Only the USER'S turn is kept. This same closure answers every
            # specialist sub-question during coordination, and assigning
            # unconditionally left `found.answered` holding the LAST
            # specialist's result — so conversation memory, and the assurance
            # record built from it, described a sub-analysis the user never
            # asked for rather than the question they did.
            investigation, orchestrated = answer_investigation(
                q, user_id=user_id, project_id=project_id,
                investigation_id=investigation_id, persist=True,
                period=period, state=state, memory=memory)
            if q == question and found.answered is None:
                found.answered = orchestrated
            return investigation

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
    reading = _reading_of(investigation, found.answered)
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
        # `nested`: these come from inside COORDINATING. A specialist
        # calculating is part of coordination, not a step back to it.
        on_stage=lambda s, d: runs.advance(session, run_row, s, detail=d,
                                           agents=len(plan.agents),
                                           nested=True))


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

    status = str(getattr(investigation, "status", "") or "")
    plan = getattr(investigation, "plan", None)
    datasets = list(getattr(plan, "datasets", ()) or ())

    # The invariant and grounding reports live on the ANSWERED object, which is
    # where the runtime records them. They were being read off the narrative,
    # which has no such fields and never had — so `checks` was always empty and
    # the single-analysis path counted no invariant it had actually run.
    answered = found.answered
    invariants = getattr(answered, "invariants", None)
    # Grounding is recorded on the written interpretation — what the prose
    # claimed and whether every figure in it came from the result.
    grounding = getattr(answered, "written", None)
    assessed = au.assess(
        plan=plan, tasks=[],
        invariants=invariants,
        grounding=grounding,
        relationships_used=max(0, len(datasets) - 1),
        relationships_governed=max(0, len(datasets) - 1),
        limitations=([] if status == "succeeded"
                     else [f"The analysis finished as '{status}'."]))

    # P0.9. The assurance status is a claim about evidence, so the evidence
    # gets the last word. A run that computed nothing and checked nothing was
    # reporting VALIDATED; `permit` is a ceiling and can only lower a status,
    # so a run that genuinely validated is unaffected.
    from backend.agentic import consistency as cy

    evidence = cy.of_investigation(investigation)
    allowed, because = cy.permit(assessed.status, evidence)
    if allowed != assessed.status:
        assessed.status = allowed
        assessed.components.append(au.Component(
            "trace_consistency", au.NOT_CHECKED, because))
        assessed.weakest = assessed.weakest or "trace_consistency"
    return assessed


# ---------------------------------------------------------------------------
# Reading what the runtime produced
# ---------------------------------------------------------------------------


def _reading_of(investigation: Any, orchestrated: Any = None) -> Any:
    """A reading-shaped view of what the analysis actually used.

    Three sources, merged, in order of how directly each one knows:

    1. **The orchestration layer's own Reading**, when it has one. That is the
       real thing — what the router understood — and nothing reconstructs it
       better.
    2. **The executed steps**, where the runtime records what it really read:
       `result["datasets"]` and `result["plan"]["meta"]["concepts"]`. Needed
       because the offline route produces an empty Reading, and reading it off
       the AnalysisPlan finds nothing at all — the plan carries steps and a
       scope, not measures. Without this the second officer selection saw a
       question with no concepts, `agents_for()` returned nothing, and
       coordination could never fire on ANY question, leaving the level to be
       decided entirely by the sentence — which is what §5 forbids.
    3. **The broad-investigation summary**, when the turn ran one. Six governed
       checks over a named sector is segment-level work whatever the sentence
       looked like, and `subject_kind` plus the probe count say so exactly.

    Duck-typed on purpose: `officers` reads attributes, and constructing a real
    `capability.Reading` here would couple the agentic layer to a class it has
    no other reason to know.
    """
    steps = list(getattr(investigation, "steps", ()) or ())
    datasets: list[str] = []
    concepts: list[str] = []
    periods: list[str] = []
    grain = ""

    for step in steps:
        result = getattr(step, "result", None)
        if not isinstance(result, dict):
            continue
        for name in (result.get("datasets") or ()):
            if str(name) and str(name) not in datasets:
                datasets.append(str(name))
        meta = (result.get("plan") or {}).get("meta") or {}
        grain = grain or str(meta.get("grain") or "")
        for entry in (meta.get("concepts") or ()):
            name = str(entry.get("concept") if isinstance(entry, dict)
                       else entry).lower()
            if name and name not in concepts:
                concepts.append(name)
        for key in ("period", "compare_period", "prior_period"):
            value = str(meta.get(key) or "")
            if value and value not in periods:
                periods.append(value)
        at = str(getattr(step, "period", "") or "")
        if at and at not in periods:
            periods.append(at)

    # (1) The router's own Reading wins where it has anything.
    router = getattr(orchestrated, "reading", None)
    for name in ("datasets", "concepts", "periods"):
        for value in (getattr(router, name, ()) or ()):
            target = {"datasets": datasets, "concepts": concepts,
                      "periods": periods}[name]
            if str(value) and str(value) not in target:
                target.append(str(value))
    for value in (getattr(router, "metrics", ()) or ()):
        if str(value) and str(value) not in concepts:
            concepts.append(str(value))
    grain = str(getattr(router, "grain", "") or "") or grain

    # (3) A broad investigation is segment- or portfolio-level work by
    # construction, and the probe count is the operation count.
    #
    # Looked for in two places, because it is written to only one of them.
    # `orchestrated.investigation` is empty on the path the Cockpit actually
    # takes; the summary lives inside the step result, under
    # `detail.investigation`. Reading only the first meant every broad
    # investigation arrived here with no concepts and no grain — so
    # `agents_for()` returned nothing, `_should_coordinate` could never be
    # true, and the Chief Orchestrator badge sat on top of zero specialists
    # and zero tasks. That is the same failure source (2) was added to fix,
    # reappearing on the broad path.
    probes = 0
    summary = _broad_summary(investigation, orchestrated)
    if summary:
        # `probes` is a count on one assembly path and the list itself on
        # another. Both mean "how many governed checks ran".
        counted = summary.get("probes") or 0
        probes = len(counted) if isinstance(counted, (list, tuple)) else int(counted)
        kind = str(summary.get("subject_kind") or "").lower()
        if kind in {"sector", "segment", "region", "product", "portfolio"}:
            grain = grain or ("portfolio" if kind == "portfolio" else "sector")
        # Each probe names the governed concept it checked. Those concepts
        # are what select the specialists, and they were being thrown away.
        if isinstance(counted, (list, tuple)):
            for probe in counted:
                name = str((probe or {}).get("concept")
                           if isinstance(probe, dict) else probe or "").lower()
                if name and name not in concepts:
                    concepts.append(name)

    reading = _Reading()
    reading.datasets = tuple(datasets)
    reading.concepts = tuple(concepts)
    reading.metrics = tuple(concepts)
    reading.periods = tuple(periods)
    reading.period_requirement = (
        str(getattr(router, "period_requirement", "") or "")
        or ("two_period" if len(periods) >= 2 else "point_in_time"))
    reading.grain = grain
    reading.operation_count = max(len(steps), probes)
    return reading


def _broad_summary(investigation: Any, orchestrated: Any) -> dict[str, Any]:
    """The broad-investigation summary, from wherever it was written.

    Two places, checked in order of directness. The orchestration layer
    carries it on some paths; on the path the Cockpit takes it is nested in
    the executed step's result. A reader that knew only one of them saw
    nothing on every real run.
    """
    direct = getattr(orchestrated, "investigation", None)
    if isinstance(direct, dict) and direct:
        return direct
    for step in (getattr(investigation, "steps", ()) or ()):
        result = getattr(step, "result", None)
        if not isinstance(result, dict):
            continue
        found = (result.get("detail") or {}).get("investigation")
        if isinstance(found, dict) and found:
            return found
    return {}


class _Reading:
    """What `officers` and `routing` read off a reading, and nothing else."""

    datasets: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    periods: tuple[str, ...] = ()
    period_requirement: str = "point_in_time"
    grain: str = ""
    dimensions: tuple[str, ...] = ()
    operation_count: int = 0
    confidence: float = 1.0
    clarification: str = ""


def _concepts_of(reading: Any) -> list[str]:
    return [str(c) for c in (getattr(reading, "concepts", ()) or ())]


def _scope_of(reading: Any) -> dict[str, Any]:
    grain = str(getattr(reading, "grain", "") or "")
    if grain in {"sector", "segment", "portfolio"}:
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
