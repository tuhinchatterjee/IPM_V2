"""
Which route answers a request, and which model serves it.

The two things these guard are cost and honesty. A product that sends every
catalogue lookup to a planning model is expensive for no benefit; one that
sends a compound multi-domain request to a routing model is cheap and wrong.
And a request whose route nobody can see is a request nobody can reproduce, so
the decision is recorded on every turn — including the turns where no model was
called at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.llm import roles
from backend.orchestration import routing as rt


@dataclass
class FakeReading:
    datasets: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    periods: tuple[str, ...] = ()
    period_requirement: str = "none"
    confidence: float = 0.9
    clarification: str = ""


@dataclass
class FakeContinuation:
    carries_context: bool = False


@dataclass
class FakeMemory:
    empty: bool = True
    outstanding: list[str] = field(default_factory=list)


# ------------------------------------------------------------------- routing


def test_a_simple_question_takes_the_routine_model():
    decision = rt.decide("What is total EAD by sector in the latest quarter?",
                         reading=FakeReading(datasets=("portfolio_facility",)))

    assert decision.route == rt.ROUTINE
    assert decision.role == "router"
    assert decision.uses_model is True


def test_a_compound_multi_domain_request_escalates():
    decision = rt.decide(
        "For each sector, calculate Stage 2 EAD divided by total sector EAD, "
        "and rank sectors by the largest increase.",
        reading=FakeReading(
            datasets=("portfolio_facility", "ifrs9_staging"),
            concepts=("stage", "ead", "sector"),
            period_requirement="two_period"))

    assert decision.route == rt.COMPLEX
    assert decision.role == "planner"
    assert decision.score >= rt.COMPLEX_AT
    assert any(s.id == "nested" for s in decision.signals)


def test_a_broad_investigation_escalates():
    decision = rt.decide("Something seems wrong with Contracting. Investigate it.",
                         reading=FakeReading(confidence=0.45))

    assert decision.route == rt.COMPLEX
    assert {"broad", "low_confidence"} <= {s.id for s in decision.signals}


def test_methodology_work_escalates():
    decision = rt.decide("How should we define our watchlist trigger?",
                         reading=FakeReading())

    assert decision.route == rt.COMPLEX
    assert any(s.id == "methodology" for s in decision.signals)


def test_a_predictive_request_escalates():
    """Not because CreditProbe will do it — because it must not pretend to."""
    decision = rt.decide("Forecast ECL for the next four quarters.",
                         reading=FakeReading())

    assert decision.route == rt.COMPLEX
    assert any(s.id == "predictive" for s in decision.signals)


def test_demo_safe_mode_makes_a_borderline_request_complex():
    question = "Which customers had a rating downgrade?"
    reading = FakeReading(datasets=("customer_ratings", "ifrs9_staging"),
                          period_requirement="two_period")

    ordinary = rt.decide(question, reading=reading)
    guarded = rt.decide(question, reading=reading, demo_safe=True)

    assert guarded.score > ordinary.score
    assert guarded.route == rt.COMPLEX
    assert any(s.id == "demo_safe" for s in guarded.signals)


def test_a_deterministic_route_calls_no_model():
    decision = rt.decide("Show it as a graph.", deterministic=True)

    assert decision.route == rt.DETERMINISTIC
    assert decision.uses_model is False
    assert decision.model == ""
    assert "could only agree or be wrong" in decision.reason


def test_an_escalation_carries_the_reason_and_never_an_answer():
    """The repair prompt may contain what failed. Nothing else.

    A repair prompt carrying an expected answer would be teaching to the test,
    and the score afterwards would measure the prompt rather than the product.
    """
    first = rt.decide("Rank sectors by Stage 2 share.", reading=FakeReading())
    second = rt.escalate(first, "totals: 'ifrs9_stage' is not a column here")

    assert second.route == rt.COMPLEX
    assert second.escalated_from == first.route
    assert second.repairs == 1
    assert "not a column" in second.reason


def test_the_decision_is_stable_for_the_same_request():
    """Deterministic by construction, so a Trace can be reproduced."""
    reading = FakeReading(datasets=("a", "b"), concepts=("x", "y", "z"))
    first = rt.decide("Compare a and b.", reading=reading)
    second = rt.decide("Compare a and b.", reading=reading)

    assert first.to_dict() == second.to_dict()


# --------------------------------------------------------------------- roles


def test_every_role_has_a_purpose_a_person_can_read():
    for name in roles.ROLES:
        assert roles.PURPOSE[name].endswith(".")
        assert len(roles.PURPOSE[name]) > 30


def test_a_role_inherits_the_shared_model_when_it_has_none(monkeypatch):
    monkeypatch.delenv("AI_PLANNER_MODEL", raising=False)

    planner = roles.role(roles.PLANNER)

    assert planner.inherited is True


def test_a_configured_role_is_used_and_marked_as_configured(monkeypatch):
    monkeypatch.setenv("AI_PLANNER_MODEL", "a-configured-model-id")

    planner = roles.role(roles.PLANNER)

    assert planner.model == "a-configured-model-id"
    assert planner.inherited is False


def test_no_model_id_is_hard_coded_anywhere_in_the_roles():
    """The roles module must not name a model.

    A model id in code is one nobody can change without a release, and one
    that will be wrong by the time somebody reads it.
    """
    import inspect

    source = inspect.getsource(roles)
    assert "claude-" not in source
    assert "gpt-" not in source


def test_an_effort_that_is_not_a_level_is_ignored(monkeypatch):
    monkeypatch.setenv("AI_PLANNER_EFFORT", "maximum-overdrive")

    assert roles.role(roles.PLANNER).effort == ""


def test_a_model_the_provider_does_not_list_is_reported_not_substituted(monkeypatch):
    """Silently answering with a different model makes a certification void."""
    monkeypatch.setenv("AI_CRITIC_MODEL", "not-a-model-this-provider-has")

    class FakeProvider:
        name = "anthropic"
        supported_models = ("a-real-one",)

    problems = roles.verify(FakeProvider())

    assert problems
    assert "AI_CRITIC_MODEL" in problems[0]
    assert "will not silently use a different model" in problems[0]


def test_describe_never_carries_a_key(monkeypatch):
    monkeypatch.setenv("AI_PLANNER_MODEL", "a-model")

    import json

    raw = json.dumps(roles.describe())

    assert "sk-" not in raw
    assert "key" not in raw.lower()


# ----------------------------------------------------------- through the path


@pytest.fixture(scope="module")
def require_data():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


def test_every_answer_records_the_route_it_took(require_data):
    from backend.orchestration.executor import answer_investigation

    investigation, answered = answer_investigation(
        "What is total EAD by sector in the latest quarter?", persist=False)

    assert answered.decision is not None
    recorded = investigation.conversation.get("routing") or {}
    assert recorded.get("route") in rt.ROUTES
    assert recorded.get("label")
    assert "signals" in recorded


def test_a_metadata_follow_up_answered_from_memory_calls_no_model(require_data):
    """The route that matters most: the one that costs nothing."""
    from backend.orchestration import conversation as cv
    from backend.orchestration import memory as wm
    from backend.orchestration.executor import answer_investigation
    from backend.orchestration.orchestrator import remember as advance

    context: dict = {}
    for question in ("What fields are available in the ratings data?",
                     "Which of those fields are financial ratios?"):
        state, memory = cv.load(context), wm.load(context)
        investigation, answered = answer_investigation(
            question, persist=False, state=state, memory=memory)
        context = cv.save(context, advance(state, answered, headline="",
                                           run_id=None))
        context = wm.save(context, wm.observe(wm.load(context), answered,
                                              investigation))

    assert answered.from_memory is True
    assert answered.decision.route == rt.DETERMINISTIC
    assert answered.decision.uses_model is False
