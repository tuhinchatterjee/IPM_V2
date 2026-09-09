"""
Whether a plan a real Opus writes actually gets used.

The defect this suite exists for
--------------------------------
A live `claude-opus-5` call for "Why has Contracting deteriorated over six
months, and is it concentrated in a handful of names?" produced a plan, and the
seam discarded it with `the reply did not conform to the schema`. The plan was
fine. The schema required `domain` and `rationale` on every step and
`output_grain` at the top — three fields a model has no reason to repeat when
one has a single legal value and the others are for the audit trail — so a
usable plan became a deterministic fallback and four Opus tokens' worth of
planning went in the bin.

The fix is not a looser governed contract. `Step`, `Plan` and
`conversation.validate` are untouched, and they are what decides whether a plan
may run. What changed is that the JSON schema now requires only what a plan
cannot exist without, and the housekeeping a model gets wrong — a number as a
string, one item where a list was asked for, a synonym for an analysis this
product has — is corrected into the schema's own vocabulary before validation
rather than being a reason to throw the plan away.

So the cases here are in two halves: plans a real model plausibly returns,
which must be ACCEPTED; and replies that are genuinely unusable, which must
still fall back.
"""

from __future__ import annotations

import copy

import pytest

from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import planner as planner_mod
from backend.early_warning.conversation import seam as seam_mod
from backend.llm.base import LLMError
from tests.early_warning.stub_provider import StubProvider, install

QUESTION = ("Why has Contracting deteriorated over six months, and is it "
            "concentrated in a handful of names?")

#: What the live model returned, in shape: every field spelled out. The
#: baseline the rest of this suite varies from.
FULL_PLAN = {
    "intent": "diagnosis",
    "output_grain": "population_month",
    "steps": [
        {"analysis": "population", "domain": "early_warning",
         "period": "2026-06", "filters": {"sector": "Contracting"},
         "measures": ["ews_score", "ews_band", "exposure", "high_plus"],
         "order_by": "ews_score", "descending": True, "limit": 25,
         "rationale": "The current position of the Contracting population."},
        {"analysis": "movement", "domain": "early_warning",
         "period": "2026-06", "comparison_period": "2025-12",
         "filters": {"sector": "Contracting"},
         "measures": ["ews_score", "anchor_score"],
         "rationale": "Whether it has deteriorated over six months."},
        {"analysis": "concentration", "domain": "early_warning",
         "period": "2026-06", "filters": {"sector": "Contracting"},
         "measures": ["exposure", "high_plus"], "limit": 10,
         "rationale": "Whether the weakness sits in a handful of names."},
    ],
    "notes": ["Read the movement with the anchor: a notch-driven fall is not "
              "an improvement."],
}


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


def _turn(monkeypatch, reply):
    """One turn whose planner returns exactly `reply`."""
    install(monkeypatch, StubProvider(replies={"plan_the_analysis": reply}))
    return pipe.answer(QUESTION)


def _plan_event(turn):
    return next(e for e in turn.events if e.stage == pipe.PLAN_CREATED)


def _accepted(turn) -> bool:
    return _plan_event(turn).detail["engine"] == seam_mod.MODEL


def _why_not(turn) -> str:
    call = _plan_event(turn).detail["model_call"]
    return (f"{call.get('fallback_reason', '')} "
            f"{call.get('schema_errors', '')}").strip()


# ------------------------------------------------- plans that must be used


def test_the_plan_a_live_model_returns_is_accepted(monkeypatch):
    """The baseline. If this fails, nothing below is meaningful."""
    turn = _turn(monkeypatch, copy.deepcopy(FULL_PLAN))
    assert _accepted(turn), _why_not(turn)
    assert (turn.packet.plan or {})["engine"] == seam_mod.MODEL
    ran = {step["analysis"] for step in turn.packet.steps}
    assert {"population", "movement", "concentration"} <= ran


def test_a_step_that_omits_the_constant_domain_is_still_a_plan(monkeypatch):
    """THE defect.

    `domain` has exactly one legal value, and the prompt says so. A model
    that saw no reason to repeat a constant on every step has not written a
    bad plan, and requiring it turned a good one into a fallback.
    """
    reply = copy.deepcopy(FULL_PLAN)
    for step in reply["steps"]:
        step.pop("domain")
    turn = _turn(monkeypatch, reply)
    assert _accepted(turn), _why_not(turn)
    assert all(step["domain"] == "early_warning"
               for step in (turn.packet.plan or {})["steps"])


def test_a_step_without_a_rationale_is_still_a_plan(monkeypatch):
    reply = copy.deepcopy(FULL_PLAN)
    for step in reply["steps"]:
        step.pop("rationale")
    turn = _turn(monkeypatch, reply)
    assert _accepted(turn), _why_not(turn)


def test_a_plan_without_an_output_grain_is_still_a_plan(monkeypatch):
    reply = copy.deepcopy(FULL_PLAN)
    reply.pop("output_grain")
    turn = _turn(monkeypatch, reply)
    assert _accepted(turn), _why_not(turn)
    assert (turn.packet.plan or {})["output_grain"]


@pytest.mark.parametrize("mutate,description", [
    (lambda r: r["steps"][0].update({"limit": "25"}), "a number as a string"),
    (lambda r: r["steps"][0].update({"measures": "ews_score"}),
     "one measure where a list was asked for"),
    (lambda r: r["steps"][0].update({"descending": "true"}),
     "a boolean as a string"),
    (lambda r: r["steps"][1].update({"group_by": None}),
     "an explicit null for an optional field"),
    (lambda r: r.update({"notes": "one note"}),
     "a note where a list was asked for"),
    (lambda r: r["steps"][2].update({"limit": 5000}),
     "a limit above the bound"),
    (lambda r: r["steps"][0].update(
        {"filters": [{"field": "sector", "value": "Contracting"}]}),
     "filters as a list of field/value pairs"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_housekeeping_a_model_gets_wrong_does_not_cost_the_plan(
        monkeypatch, mutate, description):
    """Each of these is a correct plan with its bookkeeping off by one.

    Rejecting a sound analysis over `"limit": "25"` is not a control. It is a
    papercut that costs the whole stage and reads, in the trace, exactly like
    a model that cannot plan.
    """
    reply = copy.deepcopy(FULL_PLAN)
    mutate(reply)
    turn = _turn(monkeypatch, reply)
    assert _accepted(turn), f"{description}: {_why_not(turn)}"


def test_the_bound_on_rows_is_applied_rather_than_argued_with(monkeypatch):
    reply = copy.deepcopy(FULL_PLAN)
    reply["steps"][0]["limit"] = 5000
    turn = _turn(monkeypatch, reply)
    limits = [s["limit"] for s in (turn.packet.plan or {})["steps"]]
    assert max(limits) <= 500, limits


@pytest.mark.parametrize("written,means", [
    ("trend", plan_mod.MOVEMENT),
    ("Movement", plan_mod.MOVEMENT),
    ("top_n", plan_mod.RANKING),
    ("group-by", plan_mod.GROUPING),
    ("root_cause", plan_mod.DIAGNOSIS),
    ("portfolio", plan_mod.POPULATION),
])
def test_a_synonym_for_an_analysis_this_product_has_is_mapped(written, means):
    """Mapped into the vocabulary the schema already declares, never a new one."""
    tidied = planner_mod.tidy({"steps": [{"analysis": written}]})
    assert tidied["steps"][0]["analysis"] == means


def test_an_analysis_this_product_does_not_have_is_left_alone():
    """So the step is dropped and the trace says which one.

    Guessing at it would be the failure mode this whole seam exists to
    prevent: a plan that runs something nobody asked for, reported as though
    it ran what they did.
    """
    tidied = planner_mod.tidy({"steps": [{"analysis": "monte_carlo"}]})
    assert tidied["steps"][0]["analysis"] == "monte_carlo"
    assert planner_mod._steps(tidied) == []


def test_tidying_never_adds_a_value():
    """The one property that makes this safe rather than lenient."""
    before = {"steps": [{"analysis": "population"}]}
    after = planner_mod.tidy(copy.deepcopy(before))
    assert set(after["steps"][0]) == {"analysis"}
    assert "output_grain" not in after
    assert "intent" not in after


def test_a_grain_this_product_does_not_deliver_at_is_dropped_not_guessed():
    tidied = planner_mod.tidy(
        {"steps": [{"analysis": "population"}], "output_grain": "facility_day"})
    assert "output_grain" not in tidied


# ------------------------------------------------ replies that must fall back


@pytest.mark.parametrize("reply,why", [
    ({"nonsense": True}, "no steps at all"),
    ({"steps": "population"}, "steps that are not steps"),
    ({}, "an empty document"),
], ids=["no_steps", "steps_not_a_list", "empty"])
def test_a_reply_that_is_not_a_plan_still_falls_back(monkeypatch, reply, why):
    turn = _turn(monkeypatch, reply)
    assert not _accepted(turn), why
    assert turn.answer["answered"] is True, (
        "the deterministic plan must still answer")


def test_a_plan_of_steps_this_product_cannot_run_falls_back(monkeypatch):
    """And the refusal names the value, not just the field.

    The enum catches it before `_steps` does, which is the better of the two:
    "'monte_carlo' is not one of [...]" tells a reader what the model asked
    for and what it could have asked for instead.
    """
    turn = _turn(monkeypatch, {
        "steps": [{"analysis": "monte_carlo", "domain": "early_warning"}],
        "output_grain": "population_month"})
    assert not _accepted(turn)
    assert "monte_carlo" in _why_not(turn)
    assert "population" in _why_not(turn), (
        "the refusal does not say what it could have been")
    assert turn.answer["answered"] is True


def test_a_plan_naming_another_dataset_reaches_the_validator(monkeypatch):
    """Defence in depth. The schema permits it so the refusal is real."""
    reply = copy.deepcopy(FULL_PLAN)
    reply["steps"][0]["domain"] = "ifrs9_staging"
    turn = _turn(monkeypatch, reply)

    failures = [e for e in turn.events if e.stage == pipe.VALIDATION_FAILED]
    assert failures, "a plan against ifrs9_staging passed validation"
    assert "out_of_domain" in failures[0].detail["codes"]
    assert all(step["domain"] == "early_warning"
               for step in (turn.packet.plan or {})["steps"])


def test_a_failed_plan_says_what_came_back(monkeypatch):
    """"Did not conform" without saying what did not is not a diagnosis."""
    turn = _turn(monkeypatch, {"plan": [], "reasoning": "..."})
    call = _plan_event(turn).detail["model_call"]
    assert call["fallback_reason"] == "the reply did not conform to the schema"
    assert call["schema_errors"]
    assert call["returned_keys"] == ["plan", "reasoning"]


def test_a_provider_error_on_the_plan_costs_the_plan_and_not_the_turn(
        monkeypatch):
    turn = _turn(monkeypatch, LLMError("the model did not answer"))
    assert not _accepted(turn)
    assert turn.answer["answered"] is True
    assert turn.budget["model_calls_failed"] >= 1


# --------------------------------------------------------------- truncation


def test_a_truncated_tool_call_is_reported_as_truncation(monkeypatch):
    """Not as a malformed reply.

    A plan cut off at max_tokens arrives as a partial object, and every layer
    downstream calls that "did not conform to the schema" — which sends
    whoever is debugging it to look at a schema that is fine.
    """
    from backend.llm import anthropic_provider as provider_mod

    class _Truncated:
        stop_reason = "max_tokens"
        content: list = []

    with pytest.raises(LLMError) as raised:
        provider_mod._refuse_if_truncated(_Truncated(), "plan_the_analysis",
                                          4000)
    assert "cut off" in str(raised.value)
    assert "4000" in str(raised.value)


def test_a_truncated_reply_is_not_retried():
    """It would be cut off again in exactly the same place."""
    from backend.llm import anthropic_provider as provider_mod

    truncated = LLMError("The plan_the_analysis reply was cut off at the "
                         "4000-token limit before it finished")
    prose = LLMError("The orchestrator answered in prose rather than calling "
                     "plan_the_analysis")
    assert not provider_mod._worth_retrying(truncated)
    assert provider_mod._worth_retrying(prose)


def test_the_plan_stage_has_room_for_the_document_it_asks_for():
    """Eight steps with filters, measures and a rationale each.

    The allowance is not a style preference: at 2000 tokens a four-step plan
    with real rationales was landing on the boundary, and a plan truncated at
    the boundary is a plan discarded.
    """
    assert seam_mod.STAGES[seam_mod.PLAN].max_tokens >= 4000
