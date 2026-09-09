"""
Whether the stages named after models actually run them.

What this suite is for
----------------------
The pipeline emits `sonnet_pass_1`, `opus_analysis_plan`,
`opus_final_interpretation`. For a while those were labels on deterministic
code and every turn reported `model_calls: 0`. A stage named after a model that
never runs is a diagram, and a reader cannot tell the difference from the
outside — which is exactly why it has to be a test rather than a convention.

So every case here asserts one of two things: that a configured provider is
really reached, counted and attributed; or that when it is not reached, the
turn says so and answers anyway.
"""

from __future__ import annotations

import pytest

from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import seam as seam_mod
from tests.early_warning.stub_provider import StubProvider, install

QUESTION = "Why has Contracting deteriorated over six months?"

#: What a differentiated deployment configures. The families are what the
#: architecture routes between; the ids are only ever read from configuration.
MODELS = {
    "AI_ROUTER_MODEL": "claude-sonnet-5",
    "AI_PLANNER_MODEL": "claude-sonnet-5",
    "AI_COMPLEX_PLANNER_MODEL": "claude-opus-5",
    "AI_ANALYST_MODEL": "claude-opus-5",
    "AI_CRITIC_MODEL": "claude-opus-5",
    "AI_INTERPRETATION_MODEL": "claude-sonnet-5",
}


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture
def configured(monkeypatch):
    """A deployment with a provider and four differentiated models."""
    for name, model in MODELS.items():
        monkeypatch.setenv(name, model)
    return install(monkeypatch, StubProvider())


@pytest.fixture
def offline(monkeypatch):
    """A deployment with no provider at all — the supported configuration."""
    return install(monkeypatch, StubProvider(configured_flag=False))


# ------------------------------------------------------- 1. calls happen


def test_a_configured_provider_is_actually_called(configured):
    """The requirement this whole suite exists for."""
    turn = pipe.answer(QUESTION)

    assert turn.budget["spent"]["model_calls"] > 0, (
        "the stages are named after models and none of them ran")
    assert configured.calls, "the provider was never reached"
    assert len(turn.model_calls) == turn.budget["spent"]["model_calls"], (
        "the ledger and the recorded calls disagree about how many were made")


def test_every_stage_that_can_reach_a_model_does(configured):
    """All seven seams, in one turn."""
    turn = pipe.answer(QUESTION)
    reached = {call["stage"] for call in turn.model_calls}
    assert reached == {
        pipe.SONNET_PASS_1, pipe.SONNET_PASS_2, pipe.FUNCTIONALITY_SELECTED,
        pipe.PLAN_CREATED, pipe.SUFFICIENCY_COMPLETE, pipe.FINAL_ANSWER,
        pipe.SUMMARY_UPDATED}, f"only {sorted(reached)} reached a model"
    for stage, engine in turn.engines.items():
        assert engine == seam_mod.MODEL, f"{stage} fell back: {engine}"


def test_each_call_records_what_actually_served_it(configured):
    """Provider, model, role and latency come off the call that happened."""
    turn = pipe.answer(QUESTION)
    for call in turn.model_calls:
        assert call["provider"] == "stub"
        assert call["model"], f"{call['stage']} recorded no model"
        assert call["role"], f"{call['stage']} recorded no role"
        assert call["request_id"] == "stub-request"
        assert call["input_tokens"] > 0


# --------------------------------------------------- 2. the right family


def test_each_stage_is_served_by_the_family_the_architecture_names(configured):
    """Sonnet reads and summarises; Opus decides, plans, reviews and judges."""
    turn = pipe.answer(QUESTION)
    served = {call["stage"]: call for call in turn.model_calls}

    sonnet = {pipe.SONNET_PASS_1, pipe.SONNET_PASS_2, pipe.SUMMARY_UPDATED}
    opus = {pipe.FUNCTIONALITY_SELECTED, pipe.PLAN_CREATED,
            pipe.SUFFICIENCY_COMPLETE, pipe.FINAL_ANSWER}

    for stage in sonnet:
        call = served[stage]
        assert call["family"] == seam_mod.SONNET
        assert seam_mod.family_of(call["model"]) == seam_mod.SONNET, (
            f"{stage} asked for Sonnet and {call['model']} answered")
    for stage in opus:
        call = served[stage]
        assert call["family"] == seam_mod.OPUS
        assert seam_mod.family_of(call["model"]) == seam_mod.OPUS, (
            f"{stage} asked for Opus and {call['model']} answered")


def test_the_ledger_counts_the_families_separately(configured):
    turn = pipe.answer(QUESTION)
    spent = turn.budget["spent"]
    assert spent["sonnet_calls"] == 3, spent
    assert spent["opus_calls"] == 4, spent
    assert spent["sonnet_calls"] + spent["opus_calls"] == spent["model_calls"]


def test_the_routing_table_reports_the_configuration_it_resolves(configured):
    """What Settings shows. Read from the roles, never asserted."""
    rows = {row["stage"]: row for row in seam_mod.routing()}
    assert rows[pipe.PLAN_CREATED]["model"] == "claude-opus-5"
    assert rows[pipe.SONNET_PASS_2]["model"] == "claude-sonnet-5"
    assert all(row["matches_intent"] for row in rows.values())


def test_an_undifferentiated_deployment_says_so_rather_than_claiming_routing(
        monkeypatch):
    """One shared model is a supported configuration, honestly reported.

    The stages still route — the decision is made and recorded — but the
    model that serves an Opus stage is whatever was configured, and a table
    claiming otherwise would be a table with no evidential value.
    """
    for name in MODELS:
        monkeypatch.setenv(name, "claude-sonnet-5")

    rows = {row["stage"]: row for row in seam_mod.routing()}
    assert rows[pipe.PLAN_CREATED]["intended_family"] == seam_mod.OPUS
    assert rows[pipe.PLAN_CREATED]["served_family"] == seam_mod.SONNET
    assert not rows[pipe.PLAN_CREATED]["matches_intent"]


# ------------------------------------------------- 3. deterministic fallback


def test_with_no_provider_every_stage_falls_back_and_says_why(offline):
    turn = pipe.answer(QUESTION)

    assert turn.budget["spent"]["model_calls"] == 0
    assert turn.model_calls == []
    assert set(turn.engines.values()) == {seam_mod.DETERMINISTIC}
    assert turn.answer["answered"] is True, (
        "the deterministic path must still answer, not degrade to nothing")
    reasons = {e.detail["model_call"]["fallback_reason"]
               for e in turn.events if e.detail.get("model_call")}
    assert reasons == {"no AI provider is configured"}
    assert offline.calls == [], "an unconfigured provider was called anyway"


def test_a_provider_error_costs_the_stage_and_not_the_turn(monkeypatch):
    install(monkeypatch, StubProvider(behaviour="error"))
    turn = pipe.answer(QUESTION)

    assert turn.answer["answered"] is True
    assert set(turn.engines.values()) == {seam_mod.DETERMINISTIC}
    assert all("the model did not answer" in e.detail["model_call"]["fallback_reason"]
               for e in turn.events if e.detail.get("model_call"))


def test_a_reply_that_does_not_conform_is_discarded(monkeypatch):
    """A plausible object with the wrong keys is the dangerous failure."""
    install(monkeypatch, StubProvider(behaviour="malformed",
                                      behaviour_for="plan_the_analysis"))
    turn = pipe.answer(QUESTION)

    plan_event = next(e for e in turn.events if e.stage == pipe.PLAN_CREATED)
    call = plan_event.detail["model_call"]
    assert call["engine"] == seam_mod.DETERMINISTIC
    assert call["fallback_reason"] == "the reply did not conform to the schema"
    assert call["schema_errors"], "nothing was said about what was wrong"
    assert turn.answer["answered"] is True


def test_a_failed_stage_still_spends_the_call_it_made(monkeypatch):
    """The call happened. A ledger that only counted successes would make a
    provider that fails expensively look free."""
    install(monkeypatch, StubProvider(behaviour="error"))
    turn = pipe.answer(QUESTION)
    assert turn.budget["spent"]["model_calls"] > 0
    assert turn.model_calls == [], (
        "a failed call must be spent but never recorded as having served a "
        "stage")


# ----------------------------------------- 4. no stage may claim what it is not


@pytest.mark.parametrize("provider", [
    StubProvider(),
    StubProvider(configured_flag=False),
    StubProvider(behaviour="error"),
    StubProvider(behaviour="malformed"),
], ids=["configured", "offline", "provider_error", "malformed_reply"])
def test_no_stage_claims_a_model_without_a_call_behind_it(monkeypatch,
                                                          provider):
    """The invariant, on every configuration.

    `engine: model` and a recorded call are written from the same Outcome, so
    the only way they could disagree is if a stage set one by hand. This is
    the test that would catch that.
    """
    install(monkeypatch, provider)
    turn = pipe.answer(QUESTION)

    claimed = {stage for stage, engine in turn.engines.items()
               if engine == seam_mod.MODEL}
    recorded = {call["stage"] for call in turn.model_calls}
    assert claimed == recorded, (
        f"{sorted(claimed ^ recorded)} disagree about whether a model ran")
    assert len(turn.model_calls) <= turn.budget["spent"]["model_calls"], (
        "more stages recorded a model than the ledger paid for")


def test_a_stage_that_fell_back_never_appears_in_the_recorded_calls(monkeypatch):
    install(monkeypatch, StubProvider(behaviour="malformed",
                                      behaviour_for="interpret_the_result"))
    turn = pipe.answer(QUESTION)
    stages = {call["stage"] for call in turn.model_calls}
    assert pipe.FINAL_ANSWER not in stages
    assert turn.engines[pipe.FINAL_ANSWER] == seam_mod.DETERMINISTIC


# --------------------------------------------------- 5. ONE budget, per turn


def test_one_ledger_carries_every_stage(configured):
    """Seven stages, one budget, and a ceiling that actually binds."""
    turn = pipe.answer(QUESTION)
    spent = turn.budget["spent"]
    ceilings = turn.budget["ceilings"]

    assert spent["model_calls"] == 7
    assert spent["model_calls"] <= ceilings["model_calls"]
    assert turn.budget["remaining"]["model_calls"] == \
        ceilings["model_calls"] - spent["model_calls"]


def test_a_spent_budget_stops_the_calls_and_not_the_answer(configured,
                                                           monkeypatch):
    """The ceiling is what makes the ledger a budget rather than a counter.

    At a ceiling of three, one call is optional and two are the closing
    reserve — so the early stages fall back and the answer is still written
    by a model, which is the trade the reserve exists to make.
    """
    monkeypatch.setitem(budget_mod.CEILINGS[budget_mod.STANDARD],
                        "model_calls", 3)
    turn = pipe.answer(QUESTION)

    assert turn.budget["spent"]["model_calls"] == 3
    assert len(turn.model_calls) == 3
    assert turn.answer["answered"] is True
    later = [e for e in turn.events
             if "allowance is spent"
             in e.detail.get("model_call", {}).get("fallback_reason", "")]
    assert later, "the stages after the ceiling did not say why they fell back"
    assert "reserved" in later[0].detail["model_call"]["fallback_reason"]
    # The two that matter got the reserve.
    assert turn.engines[pipe.FINAL_ANSWER] == seam_mod.MODEL
    assert turn.engines[pipe.SUMMARY_UPDATED] == seam_mod.MODEL


def test_deep_mode_raises_the_ceiling_and_nothing_else(configured):
    standard = pipe.answer(QUESTION, mode=budget_mod.STANDARD)
    deep = pipe.answer(QUESTION, mode=budget_mod.DEEP)

    assert deep.budget["ceilings"]["model_calls"] > \
        standard.budget["ceilings"]["model_calls"]
    assert deep.selection["selected_functionality"] == \
        standard.selection["selected_functionality"]


# ------------------------------------- 6. repairs and revisions do not reset


def test_a_refused_plan_does_not_give_the_calls_back(monkeypatch):
    """A plan the validator refuses costs the calls that produced it.

    The failure that costs money is the recursive one, and every recursion
    looks affordable if each attempt starts fresh. So the turn that had to
    fall back to the deterministic plan is never CHEAPER than the one that
    did not.
    """
    clean = install(monkeypatch, StubProvider())
    accepted = pipe.answer(QUESTION)
    del clean

    install(monkeypatch, StubProvider(behaviour="foreign_domain",
                                      behaviour_for="plan_the_analysis"))
    refused = pipe.answer(QUESTION)

    assert refused.budget["spent"]["model_calls"] >= \
        accepted.budget["spent"]["model_calls"], (
        "a refused plan made the turn cheaper, which means something reset")
    assert refused.answer["answered"] is True


def test_a_sufficiency_revision_spends_from_the_same_ledger(configured):
    turn = pipe.answer(
        "Why has Contracting deteriorated over six months, and is it "
        "concentrated in a handful of names?")
    spent = turn.budget["spent"]
    assert spent["model_calls"] + spent["executions"] > 0
    # Whatever the review decided, the counters only ever went up.
    counts = [e.detail.get("repairs_spent") for e in turn.events
              if "repairs_spent" in e.detail]
    assert counts == sorted(counts), "a repair counter went backwards"
    revisions = [e.detail.get("revisions_spent") for e in turn.events
                 if "revisions_spent" in e.detail]
    assert revisions == sorted(revisions), "a revision counter went backwards"


# ------------------------------------------------ the controls, under a model


def test_a_model_may_not_open_the_gate(monkeypatch):
    """Routing is a control. A model may tighten it and never loosen it."""
    install(monkeypatch, StubProvider(behaviour="open_the_gate",
                                      behaviour_for="select_functionality"))
    turn = pipe.answer("What happens to ECL if oil falls 30%?")

    assert turn.selection["selected_functionality"] != "early_warning", (
        "the model routed a What-If question into Early Warning and the gate "
        "let it")
    assert not (set(turn.stages) & pipe.ANALYTICAL_STAGES)
    assert turn.selection["model_call"]["accepted"] is False


def test_a_model_plan_naming_another_dataset_is_refused_by_the_validator(
        monkeypatch):
    """Defence in depth: the schema permits it so the validator can refuse it."""
    install(monkeypatch, StubProvider(behaviour="foreign_domain",
                                      behaviour_for="plan_the_analysis"))
    turn = pipe.answer(QUESTION)

    failures = [e for e in turn.events if e.stage == pipe.VALIDATION_FAILED]
    assert failures, "a plan against ifrs9_staging passed validation"
    assert "out_of_domain" in failures[0].detail["codes"]
    assert turn.packet is not None
    planned = (turn.packet.plan or {}).get("steps") or []
    assert planned, "nothing was planned at all"
    assert all(step["domain"] == "early_warning" for step in planned), (
        "a foreign step reached execution")
    assert (turn.packet.plan or {})["engine"] != "model", (
        "the refused plan was the one that ran")


def test_prose_carrying_a_figure_the_packet_does_not_hold_is_discarded(
        monkeypatch):
    """Not annotated. Not shown under a warning. Discarded."""
    install(monkeypatch, StubProvider(behaviour="ungrounded",
                                      behaviour_for="interpret_the_result"))
    turn = pipe.answer(QUESTION)

    assert "88,412.7" not in turn.answer["interpretation"]
    final = next(e for e in turn.events if e.stage == pipe.FINAL_ANSWER)
    assert final.detail["ungrounded_figures"], (
        "the invented figure was not reported")
    assert final.detail["engine"] == seam_mod.DETERMINISTIC


def test_the_model_never_resolves_an_obligor(configured):
    """Entity resolution is the domain's answer, and stays the domain's."""
    turn = pipe.answer("Open the weakest one in Contracting.")
    resolved = (turn.rolling_summary.customer_id
                if turn.rolling_summary else "")
    if not resolved:
        pytest.skip("this phrasing resolved no obligor in the current data")
    from backend.early_warning import v2_service as svc

    frame = svc.borrower_month()
    assert resolved in set(frame["customer_id"].astype(str)), (
        "the thread carries an obligor the published data does not hold")


def test_the_deterministic_answer_is_the_floor_not_a_stub(offline):
    """The fallback has to be worth falling back to."""
    turn = pipe.answer(QUESTION)
    assert len(turn.answer["direct"]) > 30
    assert len(turn.answer["interpretation"]) > 120
    assert turn.answer["follow_ups"]
