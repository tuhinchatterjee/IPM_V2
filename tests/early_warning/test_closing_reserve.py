"""
Whether the answer survives the analysis that produced it.

The defect this suite exists for
--------------------------------
A live run reached the end of the analysis with real Sonnet and Opus calls
behind every stage, and then wrote its answer deterministically. The trace
said:

    opus_final_interpretation   deterministic
    sonnet_summary_update       deterministic
    this turn's model-call budget is spent (6 of 8)

Six of eight is not spent. Two calls remained, and two stages needed one each.
What had actually run out was the sixty-second clock, and the fallback reason
named the wrong resource — so the obvious reading of the trace, that the
ceiling was too low, was wrong in a way nothing on the trace could correct.

Two things follow. A budget message has to name the resource that was actually
exhausted. And the two stages a turn cannot end without — the interpretation
and the rolling summary — need their capacity held back from the optional work
that would otherwise spend it, because a turn that pays for four Opus calls and
then writes its answer deterministically has spent the budget on the part the
reader never sees.

The one-ledger principle is untouched. There is still one ledger per turn, the
counters still never reset, and a repair or a revision still spends from the
same ones. The reserve is an ordering rule inside that ledger, not a second
allowance beside it.
"""

from __future__ import annotations

import pytest

from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import seam as seam_mod
from tests.early_warning.stub_provider import StubProvider, install

QUESTION = ("Why has Contracting deteriorated over six months, and is it "
            "concentrated in a handful of names?")


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
    return install(monkeypatch, StubProvider())


def _closing(turn) -> dict[str, str]:
    return {stage: turn.engines.get(stage, "")
            for stage in (pipe.FINAL_ANSWER, pipe.SUMMARY_UPDATED)}


# ----------------------------------------------------- the message was wrong


def test_the_clock_is_not_reported_as_the_call_count():
    """The specific misdiagnosis on the live trace."""
    ledger = budget_mod.open_ledger()
    ledger.model_calls = 6
    ledger.started_at -= 500  # well past the soft deadline

    reason = ledger.why_not("model_calls")
    assert "time budget" in reason, reason
    assert "6 of 8" not in reason, (
        "the message still blames the counter for the clock running out")


def test_the_reserve_is_named_when_it_is_the_reserve():
    ledger = budget_mod.open_ledger()
    ledger.model_calls = 6

    reason = ledger.why_not("model_calls")
    assert "reserved" in reason, reason
    assert "final interpretation" in reason
    # And the closing stages themselves are not blocked by it.
    assert ledger.can("model_calls", closing=True)


def test_a_closing_stage_runs_past_the_soft_deadline():
    """A slow provider costs the revision, not the answer."""
    ledger = budget_mod.open_ledger()
    soft = ledger.ceilings["wall_clock_seconds"]
    ledger.started_at -= soft + 5

    assert not ledger.can("model_calls"), "optional work should have stopped"
    assert ledger.can("model_calls", closing=True), (
        "the answer was lost to a clock that was only meant to stop the "
        "optional work")


def test_the_hard_deadline_stops_even_a_closing_stage():
    """Bounded, not unlimited."""
    ledger = budget_mod.open_ledger()
    ledger.started_at -= ledger.ceilings["hard_wall_clock_seconds"] + 5

    assert not ledger.can("model_calls", closing=True)
    assert "hard" in ledger.why_not("model_calls", closing=True)


# ------------------------------------------------------------- the reserve


def test_standard_mode_has_room_for_seven_calls_and_one_revision():
    """The arithmetic the ceiling is set to.

    Pass one, pass two, selection, plan and one sufficiency review are five;
    a permitted revision costs a second review, making six; the two closing
    stages take it to eight exactly.
    """
    ceiling = budget_mod.CEILINGS[budget_mod.STANDARD]["model_calls"]
    optional = ceiling - budget_mod.RESERVED_MODEL_CALLS
    assert optional == 6
    assert budget_mod.RESERVED_MODEL_CALLS == 2


def test_the_closing_stages_still_run_when_the_optional_allowance_is_gone(
        configured):
    """The defect, end to end.

    Every optional call spent, and the answer is still written by a model.
    """
    ledger = budget_mod.open_ledger()
    for _ in range(6):
        ledger.model_call(family=seam_mod.OPUS)
    assert not ledger.can("model_calls")

    outcome = seam_mod.call(
        seam_mod.INTERPRETATION, system="s", prompt='p {"deterministic_reading": {}}',
        schema={"type": "object", "properties": {"direct": {"type": "string"}},
                "required": []},
        ledger=ledger)
    assert outcome.used_model, outcome.fallback_reason
    assert ledger.model_calls == 7


def test_an_optional_revision_may_not_eat_the_reserve():
    ledger = budget_mod.open_ledger()
    for _ in range(6):
        ledger.model_call(family=seam_mod.OPUS)

    assert not ledger.may_revise(), (
        "a revision was allowed that would have left nothing to write the "
        "answer with")
    assert ledger.can("model_calls", closing=True)


def test_a_revision_is_still_affordable_when_it_genuinely_fits():
    ledger = budget_mod.open_ledger()
    for _ in range(5):  # pass 1, pass 2, selection, plan, one review
        ledger.model_call(family=seam_mod.OPUS)

    assert ledger.may_revise(), (
        "the one revision Standard mode allows was refused when it fitted")


def test_deep_mode_raises_the_ceiling_and_keeps_the_same_reserve():
    deep = budget_mod.CEILINGS[budget_mod.DEEP]
    standard = budget_mod.CEILINGS[budget_mod.STANDARD]
    assert deep["model_calls"] > standard["model_calls"]
    assert deep["wall_clock_seconds"] > standard["wall_clock_seconds"]
    assert deep["hard_wall_clock_seconds"] > deep["wall_clock_seconds"]

    ledger = budget_mod.open_ledger(budget_mod.DEEP)
    for _ in range(6):
        ledger.model_call(family=seam_mod.OPUS)
    assert ledger.may_revise(), "Deep should still have room at six calls"


def test_the_pipeline_declines_the_revision_rather_than_the_answer(
        monkeypatch):
    """The whole point, on a real turn.

    The budget is squeezed until one revision would consume the reserve. The
    turn must return the supported partial answer WITH its model-written
    interpretation, rather than a fuller analysis nobody got to read.
    """
    monkeypatch.setitem(budget_mod.CEILINGS[budget_mod.STANDARD],
                        "model_calls", 7)
    install(monkeypatch, StubProvider(behaviour="declare_incomplete"))
    turn = pipe.answer(QUESTION)

    assert turn.answer["answered"] is True
    for stage, engine in _closing(turn).items():
        assert engine == seam_mod.MODEL, (
            f"{stage} fell back although the reserve was meant to hold it")


# ------------------------------------------------- one ledger, still one


def test_the_counters_still_never_reset(configured):
    turn = pipe.answer(QUESTION)
    charged = [c["at_seconds"] for c in turn.model_attempts]
    assert charged == sorted(charged), "the attempts are not in order"
    assert turn.budget["model_calls_charged"] == len(turn.model_attempts)


def test_a_repair_and_a_revision_spend_from_the_same_ledger():
    ledger = budget_mod.open_ledger()
    ledger.model_call(family=seam_mod.SONNET)
    ledger.repair()
    ledger.revision()
    ledger.model_call(family=seam_mod.OPUS)

    assert ledger.model_calls == 2, (
        "a repair or a revision gave a model call back")
    assert ledger.repairs == 1 and ledger.revisions == 1


def test_the_reserve_is_not_extra_budget():
    """It is an ordering rule inside the same ceiling, not a second one."""
    ledger = budget_mod.open_ledger()
    ceiling = ledger.ceilings["model_calls"]
    for _ in range(ceiling):
        ledger.model_call(family=seam_mod.OPUS, closing=True)
    assert ledger.model_calls == ceiling
    with pytest.raises(budget_mod.Exhausted):
        ledger.model_call(family=seam_mod.OPUS, closing=True)


# ------------------------------------------------------------- the audit


def test_the_ledger_reconciles(configured):
    """`charged = succeeded + failed`, by construction rather than by hope."""
    turn = pipe.answer(QUESTION)
    budget = turn.budget
    assert (budget["model_calls_succeeded"] + budget["model_calls_failed"]
            == budget["model_calls_charged"])


def test_a_failed_call_is_charged_recorded_and_not_counted_as_a_stage(
        monkeypatch):
    """The `6 charged / 5 served` discrepancy, made explicit.

    A call that was made and then failed is real spending. It belongs on the
    ledger; it does not belong in the list of stages a model served. Both
    facts are now reported rather than one being inferred from the other.
    """
    install(monkeypatch, StubProvider(behaviour="malformed",
                                      behaviour_for="plan_the_analysis"))
    turn = pipe.answer(QUESTION)

    assert turn.budget["model_calls_failed"] >= 1
    assert turn.budget["model_calls_charged"] > len(turn.model_calls)
    failed = [a for a in turn.model_attempts if not a["ok"]]
    assert failed, "the failed call is not on the attempt list"
    assert failed[0]["stage"] == pipe.PLAN_CREATED
    assert failed[0]["reason"]
    assert pipe.PLAN_CREATED not in {c["stage"] for c in turn.model_calls}


def test_every_attempt_names_its_stage_provider_and_model(configured):
    turn = pipe.answer(QUESTION)
    assert turn.model_attempts
    for attempt in turn.model_attempts:
        assert attempt["stage"] in seam_mod.STAGES
        assert attempt["provider"] == "stub"
        assert attempt["family"] in (seam_mod.SONNET, seam_mod.OPUS)
        assert isinstance(attempt["ok"], bool)
        assert attempt["at_seconds"] >= 0


def test_the_normal_turn_is_three_sonnet_and_four_opus(configured):
    """The target the brief names, on a question needing no revision."""
    turn = pipe.answer("Why has Contracting deteriorated over six months?")
    spent = turn.budget["spent"]
    assert spent["sonnet_calls"] == 3
    assert spent["opus_calls"] == 4
    assert turn.budget["model_calls_charged"] == 7
    assert turn.budget["model_calls_succeeded"] == 7
    assert set(turn.engines.values()) == {seam_mod.MODEL}
