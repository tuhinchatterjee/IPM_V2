"""
§15, §16, §20-§26, §54, §73 — orchestration, budgets, handoffs, assurance.

Every test here passes a fake `answer_one`. §83 forbids live Anthropic calls in
this phase, and the guarantee is structural rather than by discipline: the
orchestrator takes the governed runtime as a parameter, so there is no code path
from this file to a provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.agentic import assurance as au
from backend.agentic import budgets as bg
from backend.agentic import dag, handoff, memory, orchestrator, registry, stages

# --------------------------------------------------------------- a fake runtime


@dataclass
class _Metric:
    label: str = "Stage 2 share"
    value: float = 6.39
    unit: str = "%"


@dataclass
class _Narrative:
    direct_answer: str = "Stage 2 share rose to 6.39%."
    summary: str = ""
    metrics: tuple = (_Metric(),)


@dataclass
class _Plan:
    datasets: tuple = ("portfolio_facility",)
    fingerprint: str = "fp_test"


@dataclass
class _Investigation:
    status: str = "succeeded"
    narrative: _Narrative = field(default_factory=_Narrative)
    analysis_run_id: int = 901
    plan: _Plan = field(default_factory=_Plan)
    duration_ms: int = 90
    mode: dict = field(default_factory=dict)
    steps: tuple = ()


def _answers(**overrides: Any):
    def answer_one(_question: str, **_kw: Any) -> Any:
        return _Investigation(**overrides)

    return answer_one


def _plan(concepts=("ecl", "rating", "dpd")) -> dag.Plan:
    return orchestrator.plan_for(
        "review", concepts=list(concepts), scope={"segment": "Contracting"},
        period="Q2 2026", prior_period="Q1 2026")


# ------------------------------------------------------------------ §16 the DAG


def test_independent_specialists_share_a_layer():
    """§16's own example: Portfolio Risk and IFRS 9 may run at the same time,
    and Validation & Assurance waits for both."""
    plan = _plan()
    layers = plan.layers()
    assert len(layers) == 2
    assert len(layers[0]) == 3
    assert layers[1][0].agent_id == registry.VALIDATION.agent_id


def test_the_assurance_task_depends_on_every_specialist():
    plan = _plan()
    assurance_task = plan.task("assurance")
    assert set(assurance_task.depends_on) == {
        t.task_key for t in plan.tasks if t.task_key != "assurance"}


def test_a_composed_plan_validates():
    assert dag.validate(_plan()) == []


def test_ready_only_returns_tasks_whose_dependencies_succeeded():
    plan = _plan(concepts=("ecl",))
    assert [t.task_key for t in plan.ready()] == ["ifrs9"]
    plan.task("ifrs9").status = dag.COMPLETE
    assert [t.task_key for t in plan.ready()] == ["assurance"]


def test_a_failed_task_blocks_what_depended_on_it_rather_than_failing_it():
    """Blocked, not failed. §55: nobody tried it."""
    plan = _plan(concepts=("ecl",))
    plan.task("ifrs9").status = dag.FAILED
    blocked = plan.block_downstream("ifrs9", reason="the source timed out")
    assert [t.task_key for t in blocked] == ["assurance"]
    assert plan.task("assurance").status == dag.BLOCKED


# ------------------------------------------------------------- §15 execution


def test_a_coordinated_run_produces_one_finding_per_specialist():
    plan = _plan()
    outcome = orchestrator.execute(plan, answer_one=_answers(),
                                   budget=bg.Budget())
    assert len(outcome.findings) == 3
    assert outcome.analysis_run_id == 901
    assert plan.task("assurance").validation_state == "passed"


def test_the_stages_a_run_passes_through_are_reported():
    seen: list[str] = []
    orchestrator.execute(_plan(), answer_one=_answers(), budget=bg.Budget(),
                         on_stage=lambda stage, _detail: seen.append(stage))
    assert stages.COORDINATING in seen
    assert stages.CALCULATING in seen
    assert stages.VALIDATING in seen


def test_a_failing_specialist_is_contained_and_reported():
    """§55: preserve what completed, state what did not."""
    plan = _plan(concepts=("ecl", "rating"))
    calls = {"n": 0}

    def flaky(_question: str, **_kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("the source did not respond")
        return _Investigation()

    outcome = orchestrator.execute(plan, answer_one=flaky, budget=bg.Budget())
    assert len(outcome.findings) == 1
    assert any("did not respond" in limit for limit in outcome.limitations)
    assert plan.task("assurance").status == dag.BLOCKED


def test_a_specialist_that_returns_no_evidence_has_not_met_its_contract():
    """§24: prose with no analysis behind it is how an unsupported sentence
    reaches the synthesis."""
    plan = _plan(concepts=("ecl",))
    outcome = orchestrator.execute(
        plan,
        # A sentence, and behind it: no analysis run, no figures, no dataset.
        answer_one=_answers(analysis_run_id=None, plan=_Plan(datasets=()),
                            narrative=_Narrative(metrics=())),
        budget=bg.Budget())
    task = plan.task("ifrs9")
    assert task.status == dag.FAILED
    assert task.error_category == "contract_unmet"
    assert not outcome.findings


def test_a_run_stops_when_asked():
    plan = _plan()
    outcome = orchestrator.execute(plan, answer_one=_answers(),
                                   budget=bg.Budget(),
                                   should_stop=lambda: True)
    assert outcome.stopped == "cancelled"
    assert all(t.status == dag.CANCELLED for t in plan.tasks)


def test_a_rejected_plan_never_executes_anything():
    reached: list[str] = []
    plan = dag.Plan()
    plan.add(dag.Task("a", "ifrs9", "x", depends_on=("b",)))
    plan.add(dag.Task("b", "ifrs9", "y", depends_on=("a",)))
    outcome = orchestrator.execute(
        plan, answer_one=lambda q, **kw: reached.append(q),
        budget=bg.Budget())
    assert outcome.stopped == "plan_rejected"
    assert reached == []


def test_a_task_using_a_tool_its_agent_lacks_is_refused_at_run_time_too():
    """The plan validator catches it first; this proves the executor would too,
    which matters because a plan can be built by something other than
    `plan_for`."""
    plan = dag.Plan()
    plan.add(dag.Task("v", "validation", "x", tool="run_analysis",
                      parameters={"plan": {}}))
    outcome = orchestrator.execute(plan, answer_one=_answers(),
                                   budget=bg.Budget())
    assert outcome.stopped == "plan_rejected"


# ---------------------------------------------------------------- §20 budgets


def test_a_plan_larger_than_its_task_budget_is_refused_before_it_runs():
    """The cheapest place to stop is before the first scan. A four-task plan
    against a budget of one is knowable without running anything."""
    plan = _plan()
    budget = bg.Budget(limits=bg.Limits(tasks=1))
    outcome = orchestrator.execute(plan, answer_one=_answers(), budget=budget)
    assert outcome.stopped == "plan_rejected"
    assert all(t.status == dag.CANCELLED for t in plan.tasks)


def test_a_run_stops_at_a_mid_run_meter_and_says_what_remains():
    """§20: the meters that can only run out part-way through. The plan is
    valid — three specialists, three tasks allowed — but the second scan is one
    more than this budget permits, and that is discovered with one specialist's
    work already done and two still owed."""
    plan = _plan()
    budget = bg.Budget(limits=bg.Limits(scans=1))
    outcome = orchestrator.execute(plan, answer_one=_answers(), budget=budget)
    assert outcome.stopped == "budget"
    assert outcome.stopped_detail["meter"] == bg.SCANS
    assert "Not done" in outcome.stopped_detail["message"]
    assert len(outcome.findings) == 1
    assert not any(t.status == dag.RUNNING for t in plan.tasks)


def test_a_zero_budget_means_zero_not_unlimited():
    budget = bg.Budget(limits=bg.Limits(model_calls=0))
    with pytest.raises(bg.Exhausted):
        budget.spend(bg.MODEL_CALLS)


def test_the_clock_stops_a_run_that_never_finishes():
    budget = bg.Budget(limits=bg.Limits(runtime_seconds=0))
    with pytest.raises(bg.Exhausted) as raised:
        budget.check_clock()
    assert raised.value.meter == bg.RUNTIME


# --------------------------------------------------------------- §25 conflict


def test_an_ungrounded_finding_becomes_a_recorded_conflict():
    plan = _plan(concepts=("ecl",))
    orchestrator.execute(
        plan,
        answer_one=_answers(analysis_run_id=0),
        budget=bg.Budget())
    # The finding has no analysis run, so Assurance challenges it and the
    # disagreement is preserved rather than deleted.
    assert plan.task("assurance").validation_state == "failed"


def test_a_conflict_is_settled_by_evidence_not_by_seniority():
    settled = handoff.resolve("whether deterioration is broad", [
        handoff.Claim("chief_orchestrator", "Broad.", analyses=[1],
                      coverage_rows=900_000, validated=False),
        handoff.Claim("credit_analyst", "Concentrated.", analyses=[2],
                      coverage_rows=9_000, validated=True)])
    assert settled.accepted == "credit_analyst"


# -------------------------------------------------------------- §54 assurance


def test_assurance_is_the_weakest_link():
    class _Inv:
        checks = (1, 2, 3)
        failures = ("ECL exceeds EAD",)

    class _Grounded:
        ungrounded = ()

    found = au.assess(invariants=_Inv(), grounding=_Grounded(),
                      reconciliation={"difference": 0.0},
                      periods_expected=1, periods_found=1)
    assert found.status == au.NEEDS_REVIEW
    assert found.weakest == "business_invariants"


def test_a_clean_coordinated_run_is_at_least_validated():
    plan = _plan()
    outcome = orchestrator.execute(plan, answer_one=_answers(),
                                   budget=bg.Budget())
    found = orchestrator.assess(outcome, periods_expected=2, periods_found=2)
    assert found.status in {au.HIGH, au.VALIDATED}


def test_assurance_names_the_limitations_a_run_recorded():
    plan = _plan(concepts=("ecl", "rating"))

    def boom(_q: str, **_kw: Any) -> Any:
        raise TimeoutError("no")

    outcome = orchestrator.execute(plan, answer_one=boom, budget=bg.Budget())
    found = orchestrator.assess(outcome)
    limitations = found.component("known_limitations")
    assert limitations is not None
    assert limitations.state == au.PARTIAL


# ------------------------------------------------------------- §11 synthesis


def test_the_synthesis_quotes_findings_rather_than_paraphrasing_them():
    plan = _plan(concepts=("ecl",))
    outcome = orchestrator.execute(plan, answer_one=_answers(),
                                   budget=bg.Budget())
    said = orchestrator.synthesise(outcome, scope={"segment": "Contracting"})
    assert "Stage 2 share rose to 6.39%." in said
    assert "IFRS 9" in said


def test_no_findings_produces_no_answer():
    outcome = orchestrator.Outcome(plan=dag.Plan())
    assert "nothing to report" in orchestrator.synthesise(outcome).lower()


def test_the_completion_summary_counts_what_actually_ran():
    plan = _plan()
    orchestrator.execute(plan, answer_one=_answers(), budget=bg.Budget())
    said = dag.summarise(plan)
    assert "4 specialists" in said
    assert "3 analyses" in said
    assert "all checks passed" in said


# ------------------------------------------------------------------ §23 memory


def test_agentic_memory_does_not_travel_between_investigations():
    """§23: no hidden cross-client memory. A context document copied elsewhere
    carries nothing into a place it does not belong."""
    here = memory.Scope(tenant="t1", investigation_id=5)
    there = memory.Scope(tenant="t1", investigation_id=6)
    mine = memory.AgenticMemory(scope=here)
    mine.add_finding("ifrs9", "Stage 2 rose", analyses=[7])
    context = memory.save({}, mine)

    assert not memory.load(context, here).empty
    assert memory.load(context, there).empty


def test_agentic_memory_does_not_travel_between_tenants():
    here = memory.Scope(tenant="bank-a", investigation_id=5)
    mine = memory.AgenticMemory(scope=here)
    mine.add_finding("ifrs9", "Stage 2 rose")
    context = memory.save({}, mine)
    other = memory.Scope(tenant="bank-b", investigation_id=5)
    assert memory.load(context, other).empty


def test_memory_versions_on_each_save():
    scope = memory.Scope(investigation_id=1)
    mine = memory.AgenticMemory(scope=scope)
    context = memory.save({}, mine)
    context = memory.save(context, memory.load(context, scope))
    assert memory.load(context, scope).version == 2


def test_memory_is_bounded():
    mine = memory.AgenticMemory()
    for index in range(40):
        mine.add_finding("ifrs9", f"finding {index}")
    assert len(mine.agent_findings) == memory.KEEP_FINDINGS


# -------------------------------------------------------------- §7 the stages


def test_a_run_cannot_move_backwards_through_the_stages():
    assert stages.can_move(stages.SCOPING, stages.CALCULATING)
    assert not stages.can_move(stages.VALIDATING, stages.SCOPING)


def test_a_run_can_always_fail_or_be_cancelled():
    assert stages.can_move(stages.CALCULATING, stages.FAILED)
    assert stages.can_move(stages.QUEUED, stages.CANCELLED)
    assert not stages.can_move(stages.COMPLETE, stages.FAILED)


def test_every_stage_has_the_caption_section_seven_specifies():
    for stage in stages.SEQUENCE:
        assert stages.CAPTIONS[stage]
        assert stages.SHORT[stage]


def test_a_scope_detail_replaces_the_generic_caption():
    """§8's example: "Validating 6 calculations" says more than "Validating
    results and reconciliation"."""
    assert stages.caption(stages.VALIDATING,
                          detail="Validating 6 calculations") == (
        "Validating 6 calculations")
