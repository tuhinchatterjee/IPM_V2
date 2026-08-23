"""
The planner and the wall in front of it.

These tests exist for one reason: the planner is the only component that reads
free text, and the validator is the only thing standing between what it produced
and the engine. If either drifts, IPM can answer a question it did not
understand, or run something nobody registered.
"""

from __future__ import annotations

import pytest

from backend.engine.registry import get_registry
from backend.orchestration.planner import DemoPlanner, get_planner, planner_mode
from backend.orchestration.schema import MAX_PLAN_STEPS, AnalysisPlan, PlanRejected, PlanStep
from backend.orchestration.validator import validate_plan, validate_step
from backend.orchestration.vocabulary import get_vocabulary


@pytest.fixture(scope="module")
def vocab():
    return get_vocabulary()


@pytest.fixture(scope="module")
def planner():
    return DemoPlanner()


# The questions the demonstration is built around. Each names the analysis that
# must appear in the plan for the answer to be the right one.
DEMO_QUESTIONS = [
    ("What deteriorated this period?", "portfolio_summary"),
    ("Why has Stage 2 increased?", "stage_migration"),
    ("Which sectors deteriorated the most?", "ecl_movement"),
    ("Show me the rating transition matrix.", "rating_transition_matrix"),
    ("Show me the top ten deteriorating borrowers.", "top_deteriorating_borrowers"),
    ("Stress the Real Estate portfolio.", "stress_scenario_basic"),
    ("How has ECL changed?", "ecl_movement"),
]


@pytest.mark.parametrize("question,expected", DEMO_QUESTIONS)
def test_demo_planner_selects_the_right_analysis(planner, vocab, question, expected):
    plan = planner.plan(question, vocab)
    assert not plan.unmatched, f"{question!r} was not recognised"
    assert expected in [s.analysis_id for s in plan.steps]
    assert plan.intent


@pytest.mark.parametrize("question,_expected", DEMO_QUESTIONS)
def test_every_demo_plan_passes_the_validator(planner, vocab, question, _expected):
    validate_plan(planner.plan(question, vocab), vocab)


def test_a_sector_named_in_the_question_is_resolved_against_real_data(planner, vocab):
    plan = planner.plan("Stress the Real Estate portfolio.", vocab)
    stress = next(s for s in plan.steps if s.analysis_id == "stress_scenario_basic")
    assert stress.params.get("sector") == "Real Estate"
    assert "Real Estate" in vocab.dimensions["sector"]


def test_a_stage_mentioned_in_a_question_is_not_read_as_a_filter(planner, vocab):
    """"Why has Stage 2 increased?" asks *about* Stage 2 — it does not ask for
    every other stage to be discarded before answering."""
    plan = planner.plan("Why has Stage 2 increased?", vocab)
    assert all("ifrs9_stage" not in s.filters for s in plan.steps)


def test_an_unrecognised_question_is_reported_rather_than_guessed(planner, vocab):
    plan = planner.plan("What is the weather in Dubai?", vocab)
    assert plan.unmatched
    assert plan.notes and "did not recognise" in plan.notes[0]
    # It still runs something useful, and every step is still a real analysis.
    assert plan.steps
    validate_plan(plan, vocab)


def test_plans_never_exceed_the_step_limit(planner, vocab):
    for question, _ in DEMO_QUESTIONS:
        assert len(planner.plan(question, vocab).steps) <= MAX_PLAN_STEPS


# ------------------------------------------------------------- the validator


def _plan(step: PlanStep) -> AnalysisPlan:
    return AnalysisPlan(question="q", intent="i", steps=[step])


def test_an_unregistered_analysis_is_refused(vocab):
    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(_plan(PlanStep("calculate_ecl_directly")), vocab)
    assert "not a registered IPM analysis" in str(excinfo.value)


def test_an_unknown_parameter_is_refused(vocab):
    problems = validate_step(
        PlanStep("portfolio_summary", params={"drop_table": "facilities"}), vocab
    )
    assert problems and "does not accept" in problems[0]


def test_a_parameter_outside_its_allowed_values_is_refused(vocab):
    problems = validate_step(
        PlanStep("stage_migration", params={"basis": "vibes"}), vocab
    )
    assert problems and "must be one of" in problems[0]


def test_a_period_the_bank_has_no_data_for_is_refused(vocab):
    problems = validate_step(PlanStep("portfolio_summary", params={"period": "Q9 2099"}), vocab)
    assert problems and "not a reporting period" in problems[0]


def test_period_aliases_are_accepted(vocab):
    assert validate_step(PlanStep("portfolio_summary", params={"period": "latest"}), vocab) == []


def test_an_ungoverned_filter_dimension_is_refused(vocab):
    problems = validate_step(
        PlanStep("portfolio_summary", filters={"account_id": "ACC000001"}), vocab
    )
    assert problems and "not a dimension IPM allows filtering on" in problems[0]


def test_a_filter_value_absent_from_the_data_is_refused(vocab):
    problems = validate_step(
        PlanStep("portfolio_summary", filters={"sector": "Interstellar Freight"}), vocab
    )
    assert problems and "not present in the governed data" in problems[0]


def test_an_empty_plan_is_refused(vocab):
    with pytest.raises(PlanRejected):
        validate_plan(AnalysisPlan(question="q", intent="i", steps=[]), vocab)


def test_a_plan_longer_than_the_limit_is_refused(vocab):
    steps = [PlanStep("portfolio_summary") for _ in range(MAX_PLAN_STEPS + 1)]
    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(AnalysisPlan(question="q", intent="i", steps=steps), vocab)
    assert "runs at most" in str(excinfo.value)


def test_every_analysis_the_planner_can_name_is_runnable(planner, vocab):
    runnable = {a.contract.id for a in get_registry().runnable()}
    for question, _ in DEMO_QUESTIONS:
        for step in planner.plan(question, vocab).steps:
            assert step.analysis_id in runnable


# ------------------------------------------------------------- planner choice


def test_the_planner_is_chosen_by_whether_a_key_is_configured(monkeypatch):
    from dataclasses import replace

    import backend.orchestration.planner as planner_module
    from backend.config import settings

    monkeypatch.setattr(planner_module, "settings", replace(settings, anthropic_api_key=""))
    assert isinstance(get_planner(), DemoPlanner)
    assert planner_mode()["mode"] == "demo"

    monkeypatch.setattr(
        planner_module, "settings", replace(settings, anthropic_api_key="sk-ant-not-real")
    )
    assert planner_mode()["mode"] == "model"
