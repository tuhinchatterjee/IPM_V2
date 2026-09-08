"""
The order the stages run in, the budget they share, and where they stop.

Why the order is tested rather than documented
-----------------------------------------------
A pipeline whose order is written down but not observable is one whose order
drifts. The stage that matters — ownership — sits fifth, before any plan
exists, and every property this architecture claims rests on it being there
rather than later. So the stages are emitted, and these assert the sequence.

The budget is tested the same way and for the same reason. "One ledger per
turn" is a sentence until something proves that a repair does not get a fresh
allowance, and the failure modes that actually cost money are exactly the
ones where each attempt looks affordable on its own.
"""

from __future__ import annotations

import pytest

from backend.early_warning import grain as grain_mod
from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import execute as ex
from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import summary as summary_mod
from backend.early_warning.conversation import validate as val

#: The order a successful analytical turn must run in.
ANALYTICAL_ORDER = [
    pipe.REQUEST_STARTED,
    pipe.SONNET_PASS_1,
    pipe.SONNET_PASS_2,
    pipe.CONTEXT_BUILT,
    pipe.FUNCTIONALITY_SELECTED,
    pipe.PLAN_CREATED,
    pipe.VALIDATION_PASSED,
    pipe.EXECUTION_COMPLETE,
    pipe.RESULT_PACKET,
    pipe.SUFFICIENCY_COMPLETE,
    pipe.FINAL_ANSWER,
    pipe.SUMMARY_UPDATED,
    pipe.THREAD_PERSISTED,
]

#: And the order a redirect must run in. Shorter by exactly the analytical
#: stages, which is the property being asserted.
REDIRECT_ORDER = [
    pipe.REQUEST_STARTED,
    pipe.SONNET_PASS_1,
    pipe.SONNET_PASS_2,
    pipe.CONTEXT_BUILT,
    pipe.FUNCTIONALITY_SELECTED,
    pipe.REDIRECT_ANSWER,
    pipe.SUMMARY_UPDATED,
    pipe.THREAD_PERSISTED,
]


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


def _ordered(stages: list[str], expected: list[str]) -> bool:
    """Whether `expected` appears in `stages`, in order, allowing extras."""
    it = iter(stages)
    return all(any(stage == want for stage in it) for want in expected)


# ------------------------------------------------------------- the order


def test_an_analytical_turn_runs_the_stages_in_order():
    turn = pipe.answer("Why has portfolio EWS deteriorated over six months?")
    assert _ordered(turn.stages, ANALYTICAL_ORDER), turn.stages


def test_ownership_is_decided_before_a_plan_exists():
    """The one ordering that the whole architecture rests on."""
    turn = pipe.answer("Why has portfolio EWS deteriorated over six months?")
    stages = turn.stages
    assert pipe.FUNCTIONALITY_SELECTED in stages
    assert pipe.PLAN_CREATED in stages
    assert stages.index(pipe.FUNCTIONALITY_SELECTED) < \
        stages.index(pipe.PLAN_CREATED), (
        "a plan was created before ownership was decided, which makes the "
        "selector a preference rather than a gate")


def test_a_redirect_runs_the_shorter_sequence():
    turn = pipe.answer("What happens to ECL if oil falls 30%?")
    assert _ordered(turn.stages, REDIRECT_ORDER), turn.stages
    for stage in pipe.ANALYTICAL_STAGES:
        assert stage not in turn.stages, f"{stage} ran after a redirect"


def test_every_turn_updates_the_summary_and_persists():
    """On every path, including the ones that answered nothing.

    A redirect that did not update the thread would leave the next turn
    reading a summary that stops before the question the reader just asked.
    """
    for question in ("Why has portfolio EWS deteriorated?",
                     "What happens to ECL if oil falls 30%?",
                     "Calculate Gini for the rating model."):
        turn = pipe.answer(question)
        assert pipe.SUMMARY_UPDATED in turn.stages, question
        assert pipe.THREAD_PERSISTED in turn.stages, question
        assert turn.rolling_summary is not None


def test_the_summary_is_updated_once_and_only_after_the_answer():
    turn = pipe.answer("Why has portfolio EWS deteriorated over six months?")
    stages = turn.stages
    assert stages.count(pipe.SUMMARY_UPDATED) == 1, (
        "the rolling summary was updated more than once in a turn")
    last_answer = max(i for i, s in enumerate(stages)
                      if s in (pipe.FINAL_ANSWER, pipe.REDIRECT_ANSWER,
                               pipe.CLARIFICATION_ANSWER, pipe.STOPPED_HONESTLY))
    assert stages.index(pipe.SUMMARY_UPDATED) > last_answer, (
        "the summary was written before the answer it is supposed to record")


# ------------------------------------------------------------- the budget


def test_one_ledger_survives_a_repair():
    """A budget that resets after a failure is not a budget."""
    ledger = budget_mod.open_ledger(budget_mod.STANDARD)
    ledger.execution()
    ledger.repair()
    assert ledger.executions == 1
    assert ledger.repairs == 1
    ledger.repair()
    with pytest.raises(budget_mod.Exhausted):
        ledger.repair()
    # And the executions counter is untouched by the repair exhaustion: the
    # ledger records what was spent, not what failed.
    assert ledger.executions == 1


def test_deep_mode_raises_the_ceiling_and_nothing_else():
    standard = budget_mod.open_ledger(budget_mod.STANDARD)
    deep = budget_mod.open_ledger(budget_mod.DEEP)
    assert deep.ceilings["revisions"] > standard.ceilings["revisions"]
    assert deep.ceilings["executions"] > standard.ceilings["executions"]
    # Depth is not a permission. Both read the same domain under the same
    # validator, and the ledger has no field that could say otherwise.
    assert set(deep.ceilings) == set(standard.ceilings)


def test_an_exhausted_turn_stops_and_says_what_it_ran_out_of():
    ledger = budget_mod.open_ledger(budget_mod.STANDARD)
    for _ in range(ledger.ceilings["executions"]):
        ledger.execution()
    with pytest.raises(budget_mod.Exhausted) as stopped:
        ledger.execution()
    assert "executions" in str(stopped.value)
    assert ledger.exhausted
    assert ledger.to_dict()["refusals"]


def test_the_turn_reports_what_it_spent():
    turn = pipe.answer("Why has portfolio EWS deteriorated over six months?")
    spent = turn.budget["spent"]
    assert spent["executions"] >= 1
    # No provider is configured in this deployment, and the ledger says so
    # rather than implying a call that did not happen.
    assert spent["model_calls"] == spent["sonnet_calls"] + spent["opus_calls"]


# ------------------------------------------------------------- the repair


def test_an_unknown_field_is_refused_with_the_fields_that_exist():
    """What makes a repair converge rather than guess again."""
    package = grain_mod.build("x")
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.POPULATION, period=package.current_period,
        measures=["ews_rating"])])
    result = val.check(plan, package)
    assert not result.ok
    failure = result.failures[0]
    assert failure.code == "unknown_field"
    assert failure.repairable
    assert "internal_rating" in failure.offered, failure.offered


def test_a_repair_fixes_the_named_field_and_the_plan_then_runs():
    package = grain_mod.build("x")
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.POPULATION, period=package.current_period,
        measures=["ews_rating"], order_by="ews_rating")])
    result = val.check(plan, package)
    repaired = pipe._repair(plan, result, package)
    assert val.check(repaired, package).ok, (
        "the repair did not produce a runnable plan")


def test_a_cross_domain_step_cannot_be_repaired_into_an_allowed_one():
    """A refusal that a repair can rewrite is a cosmetic refusal."""
    package = grain_mod.build("x")
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.POPULATION, domain="ifrs9_staging",
        period=package.current_period)])
    result = val.check(plan, package)
    assert not result.ok
    assert not result.repairable, (
        "a step reaching another domain was marked repairable")
    assert result.failures[0].code == "out_of_domain"


def test_a_failure_packet_carries_what_a_repair_needs():
    package = grain_mod.build("x")
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.POPULATION, period="1999-01")])
    result = val.check(plan, package)
    found = val.failure_packet(plan, result, package, question="q",
                               remaining={"executions": 3})
    assert found["available_periods"], "no periods offered"
    assert found["available_fields"], "no fields offered"
    assert found["domain"] == grain_mod.DOMAIN_ID
    assert found["remaining_budget"] == {"executions": 3}


def test_repeated_failure_does_not_loop_forever():
    """The repair counter is what bounds it, not a hope that it converges."""
    ledger = budget_mod.open_ledger(budget_mod.STANDARD)
    attempts = 0
    try:
        while True:
            ledger.repair()
            attempts += 1
            if attempts > 50:
                pytest.fail("the repair counter never exhausted")
    except budget_mod.Exhausted:
        pass
    assert attempts == ledger.ceilings["repairs"]


# --------------------------------------------------------- the result packet


def test_the_packet_is_the_only_source_the_prose_may_draw_on():
    turn = pipe.answer("Why has portfolio EWS deteriorated over six months?")
    assert turn.packet is not None
    numbers = turn.packet.numbers()
    assert numbers, "the packet carries no figures for the prose to use"
    assert turn.packet.provenance, "no provenance travelled with the figures"


def test_the_packet_carries_the_governed_route_rather_than_deciding_one():
    """Escalation is decided by the matrix. The answer reports it."""
    from backend.early_warning import v2_service as svc

    frame = svc.borrower_month()
    worst = frame.sort_values("ews_score", ascending=False).iloc[0]
    turn = pipe.answer(f"What should I do about {worst['customer_name']}?")
    packet = turn.packet
    if packet is None or not packet.escalation:
        pytest.skip("no escalation route for this obligor")
    assert packet.escalation["decided_by"].startswith("escalation matrix")
    assert packet.escalation["escalated_to"] or \
        packet.escalation["severity"], "the route carries neither rung nor band"


def test_governed_actions_come_from_the_library():
    from backend.early_warning import v2_service as svc

    frame = svc.borrower_month()
    worst = frame.sort_values("ews_score", ascending=False).iloc[0]
    turn = pipe.answer(f"What should I do about {worst['customer_name']}?")
    if turn.packet is None or not turn.packet.governed_actions:
        pytest.skip("no governed action applies to this obligor")
    for action in turn.packet.governed_actions:
        assert action.get("owner"), "an action with no owner is an opinion"
        assert action.get("timeframe"), "an action with no timeframe"
        assert action.get("evidence_to_close"), (
            "an action with no way to tell when it is done")


# ---------------------------------------------------------------- the seam


def test_no_stage_claims_a_model_that_did_not_run():
    """§32: never pretend a live model ran.

    No provider is configured here, so every stage is deterministic and
    every stage says so. A stage that recorded `engine: model` without a
    call in the ledger would be the product lying about its own provenance.
    """
    turn = pipe.answer("Why has portfolio EWS deteriorated over six months?")
    claimed = [e for e in turn.events
               if e.detail.get("engine") not in (None, "deterministic",
                                                  "deterministic-repair")]
    if turn.budget["spent"]["model_calls"] == 0:
        assert not claimed, (
            f"stages claimed a model engine with zero model calls: "
            f"{[(e.stage, e.detail.get('engine')) for e in claimed]}")


def test_the_executor_reads_this_domain_and_no_other():
    """The second control, and the one that would hold without the first."""
    assert set(ex.DATA_DOORS) == {
        "backend.early_warning.wide",
        "backend.early_warning.v2_service",
        "backend.early_warning.facts",
    }, ("the executor gained a data door; every one of them has to be an "
        "Early Warning reader")


def test_the_packet_builder_needs_no_other_domain():
    package = grain_mod.build("x")
    plan = plan_mod.Plan(steps=[])
    built = packet_mod.build("q", object(), plan, [], package=package)
    assert built.selected_functionality == grain_mod.DOMAIN_ID


def test_an_old_thread_still_opens():
    """A saved investigation that cannot be reopened is one that was lost."""
    older = {"scope": "portfolio", "period": "2026-01",
             "a_field_that_no_longer_exists": True}
    loaded = summary_mod.load(older)
    assert loaded.scope == "portfolio"
    assert loaded.period == "2026-01"
    assert loaded.version == summary_mod.SUMMARY_VERSION
