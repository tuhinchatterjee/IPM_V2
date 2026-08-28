"""
The Chief Orchestrator. §15, §16, §24, §25.

    EVENT OR USER QUESTION → ROUTER → OFFICER LEVEL → ORCHESTRATOR OR
    SPECIALIST → PLAN → TASK DAG → SPECIALISTS → GOVERNED TOOLS →
    DETERMINISTIC RESULTS → VALIDATION → SYNTHESIS → GROUNDED INTERPRETATION
    → RESULT / ATTENTION ITEM / DRAFT ACTION → TRACE

What this module does and does not do
-------------------------------------
It **decomposes, delegates, coordinates and synthesises**. It does not compute.
Every figure any of its tasks produces comes out of `run_investigation` — the
same governed path a user's own question takes — so an agentic answer and a
directly-asked answer are the same kind of object, carry the same Trace, and
reconcile the same way.

The specialist's work is a governed question
--------------------------------------------
A "specialist agent" here is not a prompt with a persona. It is a scope
restriction plus a bounded question put through the governed runtime. The IFRS 9
agent asking "how did Stage 2 share move in Contracting between Q1 and Q2 2026"
produces an AnalysisRun anybody can open. That is the entire reason the design
survives audit: there is no privileged path where an agent computes something
nobody else could.

Nothing here calls a model directly
------------------------------------
`answer_one` is injected. In production it is `run_investigation`, which decides
for itself whether a model is needed (most turns need none — see
`orchestration/routing.py` route A). In tests it is a fake, so §83's "use
fake/stub providers for all agentic tests" is structural: there is no code path
from this module to a provider.

Termination
-----------
Three independent stops, because one is not enough:

- the plan is validated before anything runs and cannot contain a cycle;
- every task is charged to a budget before it starts;
- the cancellation check runs between tasks.

A run that hits any of them stops, records what it completed, and says what it
did not do.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.agentic import (
    assurance as au,
)
from backend.agentic import (
    budgets as bg,
)
from backend.agentic import (
    dag,
    handoff,
    officers,
    registry,
    stages,
)
from backend.agentic import (
    tools as tool_registry,
)

logger = logging.getLogger(__name__)

#: How the specialist's question is put. A template rather than free text so
#: two runs over the same scope ask the same question, and so the question can
#: be read on the Trace beside the answer.
_ASK = "{objective} for {scope} between {before} and {now}."
_ASK_POINT = "{objective} for {scope} at {now}."


@dataclass
class Outcome:
    """What a coordinated run produced."""

    plan: dag.Plan
    findings: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[handoff.Conflict] = field(default_factory=list)
    handoffs: list[handoff.Handoff] = field(default_factory=list)
    assurance: au.Assurance | None = None
    synthesis: str = ""
    limitations: list[str] = field(default_factory=list)
    #: The AnalysisRun the primary task produced, where there was one.
    analysis_run_id: int | None = None
    stopped: str = ""
    stopped_detail: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return bool(self.findings) and not self.stopped

    @property
    def partial(self) -> bool:
        """Some of it worked. §55: what completed is preserved and reported."""
        return bool(self.findings) and bool(
            self.limitations or self.stopped or self.plan.failures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "findings": list(self.findings),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "handoffs": [h.to_dict() for h in self.handoffs],
            "assurance": self.assurance.to_dict() if self.assurance else {},
            "synthesis": self.synthesis,
            "limitations": list(self.limitations),
            "analysis_run_id": self.analysis_run_id,
            "stopped": self.stopped,
            "stopped_detail": dict(self.stopped_detail),
            "summary": dag.summarise(self.plan),
        }


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_for(objective: str, *, concepts: list[str] | None = None,
             scope: dict[str, Any] | None = None, period: str = "",
             prior_period: str = "", specialists: list[Any] | None = None,
             include_validation: bool = True) -> dag.Plan:
    """Decompose an objective into bounded specialist tasks.

    One task per specialist, all in layer 0 because they are independent — §16's
    own example — and one Validation & Assurance task depending on all of them.
    That shape is not a simplification: a specialist that needed another
    specialist's ANSWER would be a handoff, and handoffs are explicit (§24)
    rather than smuggled in as a dependency.
    """
    chosen = list(specialists or registry.agents_for(concepts or ()))
    if not chosen:
        chosen = [registry.CREDIT_ANALYST]

    plan = dag.Plan(
        objective=objective,
        scope=dict(scope or {}),
        rationale=_rationale(chosen, concepts or [], scope or {}))

    for agent in chosen:
        plan.add(dag.Task(
            task_key=agent.agent_id,
            agent_id=agent.agent_id,
            purpose=_purpose_for(agent, objective, scope or {}),
            tool=tool_registry.PLAN_ANALYSIS,
            domains=_domains_for(agent, concepts or []),
            parameters={"question": _question_for(
                agent, objective, scope or {}, period, prior_period)},
            optional=True))

    if include_validation and plan.tasks:
        plan.add(dag.Task(
            task_key="assurance",
            agent_id=registry.VALIDATION.agent_id,
            purpose=("Check every calculation against its invariants, "
                     "reconcile the totals, and challenge what the "
                     "specialists concluded."),
            depends_on=tuple(t.task_key for t in plan.tasks),
            tool=tool_registry.VALIDATE_INVARIANTS,
            # The results do not exist when the plan is written, so the
            # reference is a placeholder that `_bind_validation` replaces with
            # the real analysis run ids the moment the task becomes runnable.
            # Leaving it out entirely would make the permission check refuse
            # the task for a missing required parameter — which it did, and
            # the run reported "Validation & Assurance did not run" on a plan
            # that had always intended to run it.
            parameters={"result_ref": "upstream"},
            domains=()))

    plan.layers()
    return plan


def _rationale(chosen: list[Any], concepts: list[str],
               scope: dict[str, Any]) -> str:
    """Why this decomposition. Built from the structure, not written."""
    where = scope.get("segment") or scope.get("entity") or "the portfolio"
    if len(chosen) == 1:
        return (f"{chosen[0].business_name} covers every governed concept this "
                f"question needs, so nothing is delegated.")
    names = ", ".join(a.business_name for a in chosen[:-1])
    return (f"The question spans {len(chosen)} governed domains over {where}, "
            f"so it is split between {names} and {chosen[-1].business_name}, "
            f"whose findings are then reconciled.")


def _purpose_for(agent: Any, objective: str, scope: dict[str, Any]) -> str:
    where = scope.get("segment") or scope.get("entity") or "the portfolio"
    return f"{agent.purpose.split('.')[0]} — for {where}."


def _domains_for(agent: Any, concepts: list[str]) -> tuple[str, ...]:
    """The domains this task will actually read.

    The intersection of what the question needs and what the agent may read,
    so a plan never asks a specialist for something outside its own definition
    — `dag.validate` would reject it, which is correct but late.
    """
    wanted = {registry.domain_of(c) for c in concepts}
    wanted.discard("")
    allowed = set(agent.allowed_data_domains)
    found = tuple(sorted(wanted & allowed))
    return found or tuple(sorted(allowed))[:1]


def _question_for(agent: Any, objective: str, scope: dict[str, Any],
                  period: str, prior_period: str) -> str:
    """The governed question this specialist asks.

    A sentence the product could have been asked directly, which is the point:
    the answer comes back with a Trace, a plan fingerprint and an invariant
    check, exactly as if a person had typed it.
    """
    where = scope.get("segment") or scope.get("entity") or "the portfolio"
    focus = _focus_of(agent)
    template = _ASK if prior_period else _ASK_POINT
    return template.format(objective=focus, scope=where,
                           before=prior_period, now=period or "the latest "
                           "published period").strip()


#: What each specialist asks about, in the product's own vocabulary. Kept here
#: rather than on the Agent so the registry stays a permissions document.
_FOCUS: dict[str, str] = {
    "data_steward": "Show which datasets and periods are published",
    "credit_analyst": "Show exposure at default",
    "ratings_financials": "Show the rating distribution and downgrades",
    "ifrs9": "Show expected credit loss and Stage 2 share",
    "delinquency": "Show days past due and the NPL ratio",
    "covenants": "Show covenant headroom and breaches",
    "portfolio_risk": "Show exposure at default and expected credit loss",
    "early_warning": "Show the borrowers with deteriorating signals",
    "stress": "Show the scenario outcome",
    "validation": "Check the figures",
}


def _focus_of(agent: Any) -> str:
    return _FOCUS.get(getattr(agent, "agent_id", ""), "Show the position")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute(plan: dag.Plan, *, answer_one: Callable[..., Any],
            budget: bg.Budget, actor: Any = None,
            should_stop: Callable[[], bool] | None = None,
            on_task: Callable[[dag.Task], None] | None = None,
            on_stage: Callable[[str, str], None] | None = None) -> Outcome:
    """Run the plan, layer by layer.

    `answer_one(question, user_id=...)` is the governed runtime. `should_stop`
    is asked BETWEEN tasks, never during one — a task interrupted half-way
    would leave a partial analysis attributed to a specialist that never
    finished it.

    Every failure is contained. A specialist that raises marks its own task
    failed with a category, blocks whatever depended on it, and the run
    continues with what is left. §55: the completed tasks are preserved and the
    answer says which component is missing.
    """
    outcome = Outcome(plan=plan)
    stop = should_stop or (lambda: False)
    say = on_stage or (lambda _stage, _detail: None)

    problems = dag.validate(plan, max_tasks=budget.limits.tasks)
    if problems:
        outcome.stopped = "plan_rejected"
        outcome.stopped_detail = {"reasons": problems}
        for task in plan.tasks:
            task.status = dag.CANCELLED
            task.error_category = "plan_rejected"
        return outcome

    say(stages.COORDINATING, _coordinating_line(plan))

    for depth, layer in enumerate(plan.layers()):
        if stop():
            outcome.stopped = "cancelled"
            plan.cancel_pending(reason="Stopped at your request.")
            return outcome

        try:
            budget.check_clock(completed=_completed_line(plan),
                               remaining=_remaining_line(plan))
        except bg.Exhausted as exhausted:
            return _stop_on_budget(outcome, plan, exhausted)

        runnable = [t for t in layer if t.status == dag.PENDING]
        if not runnable:
            continue

        if depth == 0:
            say(stages.CALCULATING, _calculating_line(runnable))
        elif any(t.agent_id == registry.VALIDATION.agent_id for t in runnable):
            say(stages.VALIDATING, _validating_line(plan))

        for task in runnable:
            if stop():
                outcome.stopped = "cancelled"
                plan.cancel_pending(reason="Stopped at your request.")
                return outcome
            try:
                budget.spend(bg.TASKS, completed=_completed_line(plan),
                             remaining=_remaining_line(plan))
            except bg.Exhausted as exhausted:
                return _stop_on_budget(outcome, plan, exhausted)

            try:
                _run_task(task, plan, answer_one=answer_one, budget=budget,
                          actor=actor, outcome=outcome)
            except bg.Exhausted as exhausted:
                # A meter charged inside the task itself — a scan, a model
                # call. Without this the exception leaves `execute` entirely,
                # and §20's "stop, say what was completed, say what remains"
                # becomes an uncaught error in whatever called us, with this
                # task still marked RUNNING forever.
                task.status = dag.CANCELLED
                task.error_category = "budget"
                task.error = exhausted.sentence()
                return _stop_on_budget(outcome, plan, exhausted)
            if on_task is not None:
                on_task(task)

    outcome.conflicts = _reconcile(plan)
    outcome.limitations = _limitations(plan)
    return outcome


def _run_task(task: dag.Task, plan: dag.Plan, *,
              answer_one: Callable[..., Any], budget: bg.Budget,
              actor: Any, outcome: Outcome) -> None:
    """One specialist's work, with everything it produced recorded on it."""
    agent = registry.agent(task.agent_id)
    if agent is None:
        task.status = dag.FAILED
        task.error_category = "unknown_agent"
        task.error = f"'{task.agent_id}' is not a registered agent."
        plan.block_downstream(task.task_key, reason=task.error)
        return

    task.status = dag.RUNNING
    started = time.perf_counter()

    if task.agent_id == registry.VALIDATION.agent_id:
        _bind_validation(task, plan)

    # The permission check happens whether or not the tool is reached, and its
    # result is recorded — a refusal nobody can see afterwards is not a control.
    call = tool_registry.check(agent, task.tool or tool_registry.PLAN_ANALYSIS,
                               task.parameters, domains=task.domains)
    task.tool_calls.append(call.to_dict())
    if not call.allowed:
        task.status = dag.FAILED
        task.error_category = "not_permitted"
        task.error = call.reason
        task.duration_ms = int((time.perf_counter() - started) * 1000)
        plan.block_downstream(task.task_key, reason=call.reason)
        logger.warning("task %s refused: %s", task.task_key, call.reason)
        return

    if task.agent_id == registry.VALIDATION.agent_id:
        _validate_task(task, plan)
        task.duration_ms = int((time.perf_counter() - started) * 1000)
        return

    question = str(task.parameters.get("question") or "")
    try:
        # Carries the same two lines the task meter does: a run that stops
        # here has to be able to say what it finished and what it owes, and
        # §20 makes no exception for the meters charged inside a task.
        budget.spend(bg.SCANS, completed=_completed_line(plan),
                     remaining=_remaining_line(plan))
        answered = answer_one(
            question, user_id=getattr(actor, "user_id", None))
    except bg.Exhausted:
        raise
    except Exception as exc:  # noqa: BLE001 - contained, recorded, reported
        task.status = dag.FAILED
        task.error_category = _category(exc)
        task.error = f"{type(exc).__name__}: {exc}"
        task.duration_ms = int((time.perf_counter() - started) * 1000)
        plan.block_downstream(
            task.task_key,
            reason=f"{agent.business_name} could not complete its analysis.")
        logger.warning("task %s failed: %s", task.task_key, task.error)
        return

    _absorb(task, answered, agent)
    task.duration_ms = int((time.perf_counter() - started) * 1000)

    if task.status == dag.COMPLETE:
        outcome.findings.append({
            "agent_id": agent.agent_id,
            "agent_name": agent.business_name,
            "task": task.task_key,
            "question": question,
            "finding": task.finding,
            "analysis_run_id": task.analysis_run_id,
            "evidence": dict(task.evidence),
        })
        if outcome.analysis_run_id is None and task.analysis_run_id:
            outcome.analysis_run_id = task.analysis_run_id
    else:
        plan.block_downstream(
            task.task_key,
            reason=task.error or f"{agent.business_name} returned no finding.")


def _absorb(task: dag.Task, answered: Any, agent: Any) -> None:
    """Read what the governed runtime returned onto the task.

    The output contract is checked (§24): a specialist that returns prose with
    no analysis behind it has not met a contract asking for evidence, and
    accepting it is how an unsupported sentence reaches the synthesis.
    """
    status = str(getattr(answered, "status", "") or "")
    narrative = getattr(answered, "narrative", None)
    finding = ""
    for attribute in ("direct_answer", "summary", "headline"):
        value = getattr(narrative, attribute, "") if narrative else ""
        if value:
            finding = str(value)
            break

    task.analysis_run_id = getattr(answered, "analysis_run_id", None)
    task.result = {"status": status,
                   "duration_ms": getattr(answered, "duration_ms", 0)}
    task.finding = finding
    task.evidence = _evidence_of(answered)
    task.data_versions = _versions_of(answered)

    returned = {"finding": finding, "evidence": task.evidence,
                "confidence": status}
    missing = [p for p in agent.output_contract if not returned.get(p)]

    if status in {"failed", "rejected"}:
        task.status = dag.FAILED
        task.error_category = status
        task.error = (getattr(narrative, "summary", "")
                      or "The governed runtime could not answer this.")
        return
    if status == "needs_clarification":
        task.status = dag.FAILED
        task.error_category = "needs_input"
        task.error = str(getattr(answered, "clarification", "")
                         or "CreditProbe needs more detail to answer this.")
        return
    if missing:
        task.status = dag.FAILED
        task.error_category = "contract_unmet"
        task.error = (f"{agent.business_name} returned no "
                      f"{', '.join(missing)}, which its output contract "
                      f"requires.")
        return

    task.status = dag.COMPLETE


def _evidence_of(answered: Any) -> dict[str, Any]:
    """The figures behind a specialist's finding, by reference.

    Figures and a run id, never rows. An evidence document holding the result
    would put client data into the agentic layer for no reason — the run is
    there, and it is the authority.
    """
    narrative = getattr(answered, "narrative", None)
    metrics = list(getattr(narrative, "metrics", ()) or ()) if narrative else []
    found: dict[str, Any] = {
        "analysis_run_id": getattr(answered, "analysis_run_id", None),
        "figures": [],
    }
    for metric in metrics[:8]:
        found["figures"].append({
            "label": str(getattr(metric, "label", "") or ""),
            "value": getattr(metric, "value", None),
            "unit": str(getattr(metric, "unit", "") or ""),
        })
    plan = getattr(answered, "plan", None)
    if plan is not None:
        found["datasets"] = sorted({
            str(d) for d in (getattr(plan, "datasets", ()) or ())})
    # Nothing measured and nothing to open. The empty document rather than a
    # dict of empty keys, because §24's output-contract check reads this for
    # truth: `{"analysis_run_id": None, "figures": []}` is a truthy dict, and a
    # contract requiring evidence would be satisfied by a specialist that
    # produced a sentence and no analysis at all.
    if found["analysis_run_id"] is None and not found["figures"]:
        return {}
    return found


def _versions_of(answered: Any) -> dict[str, Any]:
    plan = getattr(answered, "plan", None)
    return {"plan_fingerprint": str(getattr(plan, "fingerprint", "") or ""),
            "mode": dict(getattr(answered, "mode", {}) or {})}


def _category(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, LookupError):
        return "not_found"
    return type(exc).__name__[:48]


# ---------------------------------------------------------------------------
# Validation & Assurance
# ---------------------------------------------------------------------------


def _bind_validation(task: dag.Task, plan: dag.Plan) -> None:
    """Point the assurance task at what actually got produced.

    Written at run time rather than at plan time because the analysis runs do
    not exist until the specialists have finished. The reference is a list of
    run ids and task keys — never the results themselves, which stay where the
    runtime put them.
    """
    upstream = [plan.task(k) for k in task.depends_on]
    done = [t for t in upstream if t is not None and t.succeeded]
    task.parameters = {
        "result_ref": ",".join(
            str(t.analysis_run_id or t.task_key) for t in done) or "none",
    }
    task.inputs = {
        "checking": [t.task_key for t in done],
        "analysis_runs": [t.analysis_run_id for t in done
                          if t.analysis_run_id],
    }


def _validate_task(task: dag.Task, plan: dag.Plan) -> None:
    """The Validation & Assurance agent's own work.

    It checks what the OTHER tasks produced, which is why it has no question of
    its own. Its findings are recorded as challenges rather than as answers:
    §25 requires a disagreement to be preserved, and an agent that quietly
    corrected another agent's finding would preserve nothing.
    """
    upstream = [plan.task(k) for k in task.depends_on]
    done = [t for t in upstream if t is not None and t.succeeded]
    failed = [t for t in upstream if t is not None and not t.succeeded]

    checks: list[dict[str, Any]] = []
    for other in done:
        grounded = bool(other.evidence.get("analysis_run_id"))
        checks.append({
            "task": other.task_key,
            "agent": other.agent_id,
            "grounded": grounded,
            "detail": ("The finding is backed by a governed analysis run."
                       if grounded else
                       "The finding has no analysis run behind it."),
        })

    ungrounded = [c for c in checks if not c["grounded"]]
    task.validation = {
        "checked": len(checks),
        "grounded": len(checks) - len(ungrounded),
        "ungrounded": [c["task"] for c in ungrounded],
        "not_run": [t.task_key for t in failed],
        "checks": checks,
    }
    task.validation_state = "failed" if ungrounded else "passed"
    task.status = dag.COMPLETE
    task.finding = _assurance_finding(len(checks), len(ungrounded),
                                      len(failed))
    task.evidence = {"analysis_run_id": None, "figures": [],
                     "checks": len(checks)}

    for other in done:
        other.validation_state = ("passed" if other.evidence.get(
            "analysis_run_id") else "failed")


def _assurance_finding(checked: int, ungrounded: int, not_run: int) -> str:
    if not checked:
        return "There was nothing to check: no specialist produced a result."
    parts = [f"{checked} finding(s) checked"]
    if ungrounded:
        parts.append(f"{ungrounded} not backed by a governed analysis")
    else:
        parts.append("every one backed by a governed analysis run")
    if not_run:
        parts.append(f"{not_run} component(s) did not run")
    return "; ".join(parts) + "."


def _reconcile(plan: dag.Plan) -> list[handoff.Conflict]:
    """Settle disagreements against the deterministic evidence. §25.

    A disagreement here is specific: two specialists whose findings the
    Validation agent could not both ground. The general case — two agents
    reaching contradictory conclusions about the same measure — is settled by
    `handoff.resolve`, which compares what backs each claim rather than how
    confidently it was stated.
    """
    validation = next((t for t in plan.tasks
                       if t.agent_id == registry.VALIDATION.agent_id), None)
    if validation is None or not validation.validation:
        return []

    ungrounded = set(validation.validation.get("ungrounded") or ())
    if not ungrounded:
        return []

    found: list[handoff.Conflict] = []
    for key in ungrounded:
        task = plan.task(key)
        if task is None or not task.finding:
            continue
        claims = [
            handoff.Claim(agent_id=task.agent_id, statement=task.finding,
                          analyses=[], coverage_rows=0, validated=False),
            handoff.Claim(agent_id=registry.VALIDATION.agent_id,
                          statement=("This finding is not backed by a "
                                     "governed analysis run."),
                          analyses=[], coverage_rows=0, validated=True),
        ]
        found.append(handoff.resolve(
            f"whether {task.agent_id}'s finding is evidenced", claims))
    return found


def _limitations(plan: dag.Plan) -> list[str]:
    """What this run could not do, in a reader's terms. §55."""
    found: list[str] = []
    for task in plan.tasks:
        agent = registry.agent(task.agent_id)
        name = agent.business_name if agent else task.agent_id
        if task.status == dag.FAILED:
            found.append(f"{name}: {task.error or 'the component failed'}")
        elif task.status == dag.BLOCKED:
            found.append(f"{name} did not run because an earlier component "
                         f"could not complete.")
        elif task.status == dag.CANCELLED:
            found.append(f"{name} was not run.")
    return found


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def synthesise(outcome: Outcome, *, objective: str = "",
               scope: dict[str, Any] | None = None) -> str:
    """One answer from several findings.

    Assembled from the findings rather than written, and deliberately so: every
    sentence here is a specialist's own grounded finding, quoted. A synthesis
    that paraphrased them would introduce a claim nothing computed, and the
    grounding check would have nothing to check it against.

    Where a model IS used for interpretation, it happens downstream on this
    text — §36's "use the LLM only to synthesise validated findings" — and it
    can only rephrase what is already here.
    """
    if not outcome.findings:
        return ("No specialist produced a validated finding, so CreditProbe "
                "has nothing to report.")

    where = (scope or {}).get("segment") or (scope or {}).get("entity") or ""
    opening = (f"Across {len(outcome.findings)} governed "
               f"{'analysis' if len(outcome.findings) == 1 else 'analyses'}"
               + (f" of {where}" if where else "") + ":")

    lines = [opening]
    for found in outcome.findings:
        text = str(found.get("finding") or "").strip()
        if text:
            lines.append(f"{found.get('agent_name') or found['agent_id']}: "
                         f"{text}")

    for conflict in outcome.conflicts:
        lines.append(conflict.sentence())

    if outcome.limitations:
        lines.append("Not covered: " + "; ".join(outcome.limitations) + ".")

    if outcome.stopped == "budget":
        lines.append(outcome.stopped_detail.get("message", ""))

    return "\n".join(line for line in lines if line)


def assess(outcome: Outcome, *, periods_expected: int = 0,
           periods_found: int = 0) -> au.Assurance:
    """The Answer Assurance view for a coordinated run. §54."""
    validation = next(
        (t for t in outcome.plan.tasks
         if t.agent_id == registry.VALIDATION.agent_id), None)

    class _Invariants:
        checks = tuple(range(int((validation.validation or {}).get(
            "checked", 0)))) if validation else ()
        failures = tuple((validation.validation or {}).get("ungrounded", ())
                         ) if validation else ()

    class _Grounding:
        ungrounded = tuple((validation.validation or {}).get("ungrounded", ())
                           ) if validation else ()

    return au.assess(
        plan=outcome.plan, tasks=outcome.plan.tasks,
        invariants=_Invariants() if validation else None,
        grounding=_Grounding() if validation else None,
        conflicts=outcome.conflicts,
        periods_expected=periods_expected, periods_found=periods_found,
        limitations=list(outcome.limitations))


# ---------------------------------------------------------------------------
# Escalation and stage captions
# ---------------------------------------------------------------------------


def escalation_for(selection: Any, plan: dag.Plan) -> Any:
    """Re-read the officer level once the plan is known. §9.

    The first selection saw only the sentence. This one sees how many
    specialists the work actually needs, which is the signal §5 cares most
    about — and an escalation from it is a legitimate transition, not a
    correction of a mistake.
    """
    return officers.escalate(
        selection, to=officers.CHIEF_ORCHESTRATOR,
        why=(f"The plan needs {len(plan.agents)} specialists across "
             f"{len(plan.tasks)} tasks, which is coordinated work.")
    ) if len(plan.agents) >= officers.COORDINATED_AT else selection


def _coordinating_line(plan: dag.Plan) -> str:
    """§8's example: "Coordinating 4 specialists / Ratings · IFRS 9 · DPD"."""
    names = [registry.agent(a).business_name for a in plan.agents
             if registry.agent(a)]
    if len(names) <= 1:
        return ""
    return (f"Coordinating {len(names)} specialists — "
            f"{' · '.join(names)}")


def _calculating_line(tasks: list[dag.Task]) -> str:
    return (f"Running {len(tasks)} governed "
            f"{'calculation' if len(tasks) == 1 else 'calculations'}")


def _validating_line(plan: dag.Plan) -> str:
    done = sum(1 for t in plan.tasks if t.succeeded)
    return (f"Validating {done} "
            f"{'calculation' if done == 1 else 'calculations'}")


def _completed_line(plan: dag.Plan) -> str:
    done = [t for t in plan.tasks if t.succeeded]
    if not done:
        return "nothing yet"
    return f"{len(done)} of {len(plan.tasks)} tasks"


def _remaining_line(plan: dag.Plan) -> str:
    left = [t for t in plan.tasks if t.status in (dag.PENDING, dag.READY)]
    if not left:
        return "nothing"
    agents = {registry.agent(t.agent_id).business_name
              for t in left if registry.agent(t.agent_id)}
    return ", ".join(sorted(agents))


def _stop_on_budget(outcome: Outcome, plan: dag.Plan,
                    exhausted: bg.Exhausted) -> Outcome:
    outcome.stopped = "budget"
    outcome.stopped_detail = exhausted.to_dict()
    plan.cancel_pending(reason=exhausted.sentence())
    outcome.limitations = _limitations(plan)
    return outcome


__all__ = [
    "Outcome",
    "assess",
    "escalation_for",
    "execute",
    "plan_for",
    "synthesise",
]
