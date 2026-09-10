"""
What the executions counter counts.

The defect this suite exists for
--------------------------------
A live Standard-mode turn reached `validation` with every model stage served
by a real model, carrying an Opus plan of six analyses — population, movement,
diagnosis, grouping, concentration, ranking. Standard allows six executions.
The turn then emitted:

    stopped_honestly   this turn's executions budget is spent (6 of 6)
    executions         6

No `execution` stage. No `result_packet`. No answer. Six executions charged
and nothing to show for them, which is a ledger describing a turn that did not
happen.

Two things were wrong, and neither of them is the ceiling.

The exhaustion escaped the loop. `ledger.execution()` was called unguarded at
the top of each iteration, `_spend` raises `Exhausted`, and the handler that
caught it discarded every result that had already been computed in order to
report that the next one was one too many. A ceiling is meant to stop the step
it cannot afford, not the turn.

The retry ran inline. A step the executor refused was corrected and re-run
immediately, spending the execution a LATER planned step was going to need. So
one failing step could starve a step that would have succeeded, and a six-step
plan under a six-execution ceiling could stop at five.

The invariant
-------------
`executions` counts governed analytical executions ATTEMPTED — one increment
per call to the executor, charged as the call is made. Never a planned step,
never a validated step, never a reserved slot. A valid six-step plan under a
six-execution ceiling runs exactly six; the seventh is refused before it runs.
The trace and the ledger describe the same turn: zero executed steps cannot
report six.

Charged on attempt, not on success, for the reason model calls are: an
execution that ran and failed cost what one that ran and worked cost. Which is
why `executions_succeeded` and `executions_failed` are recorded beside it
rather than inferred from it.
"""

from __future__ import annotations

import pytest

from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import execute as ex
from backend.early_warning.conversation import pipeline as pipe
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import seam as seam_mod
from tests.early_warning.stub_provider import StubProvider, install

#: The question from the live trace, word for word.
LIVE_QUESTION = ("Why has Contracting deteriorated over six months, and is it "
                 "concentrated in a handful of names?")


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def period() -> str:
    from backend.early_warning import v2_service as svc

    return svc.latest_period()


@pytest.fixture(scope="module")
def earlier(period) -> str:
    from backend.early_warning import v2_service as svc

    periods = list(svc.periods())
    return periods[max(0, periods.index(period) - 6)]


def _steps(period: str, earlier: str, count: int) -> list[dict]:
    """`count` distinct, valid, executable analyses.

    Distinct because a plan of six copies of one analysis is not the plan the
    live turn carried, and would let a deduplicating validator hide the
    defect.
    """
    catalogue = [
        {"analysis": "population"},
        {"analysis": "movement", "comparison_period": earlier},
        {"analysis": "diagnosis"},
        {"analysis": "grouping", "group_by": "sector"},
        {"analysis": "concentration"},
        {"analysis": "ranking", "measures": ["ews_score"]},
        {"analysis": "comparison", "comparison_period": earlier,
         "group_by": "sector"},
    ]
    assert count <= len(catalogue)
    return [dict({"domain": "early_warning", "period": period,
                  "rationale": "one of the planned analyses"}, **step)
            for step in catalogue[:count]]


def _planned(monkeypatch, steps: list[dict], *, behaviour: str = "") -> pipe.Turn:
    install(monkeypatch, StubProvider(
        behaviour=behaviour,
        replies={"plan_the_analysis": {"intent": "diagnosis",
                                       "output_grain": "population_month",
                                       "steps": steps}}))
    return pipe.answer(LIVE_QUESTION)


def _ran(turn: pipe.Turn) -> int:
    return len(turn.packet.steps) if turn.packet is not None else 0


# ------------------------------------------------- where the counter moves


def test_only_the_pipeline_charges_an_execution():
    """No pre-charge, no reservation, no second accountant.

    The counter is charged in exactly one place, immediately before the
    executor is called. A reservation elsewhere that happened to write to the
    same field is the shape of defect this asserts against.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "backend"
    charging = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if ".execution()" in path.read_text())
    assert charging == ["early_warning/conversation/pipeline.py"], charging


def test_the_ledger_charges_one_per_attempt():
    ledger = budget_mod.open_ledger()
    assert ledger.executions == 0
    ledger.execution()
    assert ledger.executions == 1
    assert ledger.executions_succeeded == 0, (
        "an attempt was counted as a success before it had an outcome")


def test_charged_equals_succeeded_plus_failed():
    ledger = budget_mod.open_ledger()
    ledger.execution()
    ledger.settle_execution(analysis="population", ok=True, rows=300)
    ledger.execution()
    ledger.settle_execution(analysis="grouping", ok=False, reason="bad_field")

    spent = ledger.to_dict()
    assert spent["executions_attempted"] == 2
    assert spent["executions_succeeded"] == 1
    assert spent["executions_failed"] == 1
    assert (spent["executions_succeeded"] + spent["executions_failed"]
            == spent["executions_attempted"])
    assert [s["analysis"] for s in spent["steps"]] == ["population", "grouping"]


# ---------------------------------------------------- 1. five under six


def test_a_five_step_plan_runs_all_five(monkeypatch, period, earlier):
    turn = _planned(monkeypatch, _steps(period, earlier, 5))

    assert turn.answer["answered"] is True
    assert _ran(turn) == 5
    assert turn.budget["spent"]["executions"] >= 5
    assert turn.budget["executions_succeeded"] >= 5


# ----------------------------------------------------- 2. six under six


def test_a_six_step_plan_runs_all_six(monkeypatch, period, earlier):
    """The live plan, at the ceiling exactly.

    Six analyses, six executions allowed, six executed — and the turn carries
    on to its answer rather than stopping on the sixth.
    """
    turn = _planned(monkeypatch, _steps(period, earlier, 6))

    assert turn.answer["answered"] is True, turn.answer
    assert _ran(turn) == 6, [s["analysis"] for s in turn.packet.steps]
    assert turn.budget["spent"]["executions"] == 6
    assert turn.budget["executions_succeeded"] == 6
    assert turn.budget["executions_failed"] == 0
    assert pipe.EXECUTION_COMPLETE in turn.stages
    assert pipe.STOPPED_HONESTLY not in turn.stages


# --------------------------------------------------- 3. seven under six


def test_a_seventh_execution_is_refused_before_it_runs(
        monkeypatch, period, earlier):
    """The ceiling stops the step, not the turn.

    Six run, the seventh is declined, and the six that ran still reach the
    packet and the answer.
    """
    turn = _planned(monkeypatch, _steps(period, earlier, 7))

    assert turn.answer["answered"] is True
    assert _ran(turn) == 6
    assert turn.budget["spent"]["executions"] == 6, (
        "the refused step was charged for anyway")
    assert turn.budget["executions_succeeded"] == 6
    assert pipe.EXECUTION_DECLINED in turn.stages
    assert pipe.RESULT_PACKET in turn.stages
    assert pipe.FINAL_ANSWER in turn.stages
    assert pipe.STOPPED_HONESTLY not in turn.stages


def test_the_refusal_names_the_resource(monkeypatch, period, earlier):
    turn = _planned(monkeypatch, _steps(period, earlier, 7))
    declined = [e for e in turn.events if e.stage == pipe.EXECUTION_DECLINED]

    assert declined, "nothing said which analysis was left out"
    assert declined[0].detail["count"] == 1
    assert "executions" in declined[0].detail["reason"]


def test_the_uncovered_part_is_not_reported_as_covered(
        monkeypatch, period, earlier):
    """A declined step is absent from the packet rather than empty in it."""
    turn = _planned(monkeypatch, _steps(period, earlier, 7))
    planned = [s["analysis"] for s in _steps(period, earlier, 7)]
    ran = [s["analysis"] for s in turn.packet.steps]

    assert set(ran) < set(planned)
    assert len(ran) == 6


# ----------------------------------------- 4. validation costs nothing


def test_validation_alone_does_not_consume_execution_budget(
        monkeypatch, period, earlier):
    """The counter must not move before the executor is reached."""
    from backend.early_warning import grain as grain_mod
    from backend.early_warning.conversation import validate as val

    ledger = budget_mod.open_ledger()
    package = grain_mod.build("the Contracting position",
                              capabilities=list(plan_mod.ANALYSIS_TYPES))
    plan = plan_mod.Plan(steps=[plan_mod.Step(**step)
                                for step in _steps(period, earlier, 6)])

    for _ in range(3):
        checked = val.check(plan, package)
    assert checked.ok, [f.code for f in checked.failures]
    assert ledger.executions == 0, (
        "validating a plan spent execution budget")


def test_a_turn_that_never_reaches_the_executor_reports_zero(monkeypatch):
    """The invariant, stated as the live trace failed it.

    Zero executed steps cannot report six. A What-If question is routed away
    before any analysis is planned, so its ledger has to read zero.
    """
    install(monkeypatch, StubProvider())
    turn = pipe.answer("What happens to ECL if oil falls 30%?")

    assert turn.selection["selected_functionality"] == "what_if"
    assert turn.budget["spent"]["executions"] == 0
    assert turn.budget["executions_attempted"] == 0
    assert turn.budget["steps"] == []
    assert turn.budget["model_calls_charged"] == 4
    assert turn.budget["model_calls_succeeded"] == 4
    assert not (set(turn.stages) & pipe.ANALYTICAL_STAGES)


def test_a_plan_the_validator_refuses_costs_nothing_to_refuse(
        monkeypatch, period):
    """The refused plan named another dataset, so it never reached the
    executor. The deterministic plan that replaced it did, and the ledger
    charges for that one and only that one — every execution charged has a
    settled step behind it.
    """
    turn = _planned(monkeypatch, [
        {"analysis": "grouping", "domain": "ifrs9_staging", "period": period,
         "group_by": "sector", "rationale": "another dataset"}])

    assert turn.budget["executions_attempted"] == len(turn.budget["steps"]), (
        "an execution was charged that no step accounts for")
    assert turn.budget["executions_attempted"] == len(turn.packet.steps) \
        + turn.budget["executions_failed"]
    assert "grouping" not in [s["analysis"] for s in turn.budget["steps"]
                              if not s["ok"]]


# --------------------------------- 5. a rejected step is not a success


def test_a_refused_step_is_charged_but_not_counted_as_a_success(
        monkeypatch, period, earlier):
    """It reached the executor, so it cost one; it failed, so it is not one."""
    steps = _steps(period, earlier, 3)
    steps.insert(0, {"analysis": "grouping", "domain": "early_warning",
                     "period": period, "group_by": "sector",
                     "rationale": "the step that will be refused"})

    real = ex.run
    refused: list[str] = []

    def _run(step):
        if step.analysis == "grouping" and not refused:
            refused.append(step.analysis)
            raise ex.ExecutionError("the executor refused this step",
                                    code="grain_unsafe", offered=("sector",))
        return real(step)

    monkeypatch.setattr(ex, "run", _run)
    turn = _planned(monkeypatch, steps)

    assert refused, "the refusal never happened"
    assert turn.budget["executions_failed"] >= 1
    assert (turn.budget["executions_succeeded"]
            + turn.budget["executions_failed"]
            == turn.budget["executions_attempted"])
    failed = [s for s in turn.budget["steps"] if not s["ok"]]
    assert failed and failed[0]["reason"] == "grain_unsafe"


def test_a_correction_does_not_starve_a_later_planned_step(
        monkeypatch, period, earlier):
    """The regression, precisely.

    An inline retry spends the execution the sixth planned step needed. Every
    planned step gets the executor before any correction gets it twice.
    """
    steps = _steps(period, earlier, 6)
    real = ex.run
    refused: list[str] = []

    def _run(step):
        if step.analysis == "population" and not refused:
            refused.append(step.analysis)
            raise ex.ExecutionError("the executor refused this step",
                                    code="grain_unsafe", offered=("sector",))
        return real(step)

    monkeypatch.setattr(ex, "run", _run)
    turn = _planned(monkeypatch, steps)

    ran = [s["analysis"] for s in turn.packet.steps]
    for planned in ("movement", "diagnosis", "grouping", "concentration",
                    "ranking"):
        assert planned in ran, (
            f"{planned} was planned and never ran: the correction of an "
            f"earlier step took its execution. Ran: {ran}")


# ------------------------- 6. repairs and revisions stay on one ledger


def test_a_revision_spends_the_same_execution_counter(monkeypatch, period,
                                                      earlier):
    """One ledger. A revision's execution is on it, and visible on it."""
    install(monkeypatch, StubProvider(
        behaviour="declare_incomplete",
        behaviour_for="review_sufficiency",
        replies={"plan_the_analysis": {
            "intent": "diagnosis", "output_grain": "population_month",
            "steps": _steps(period, earlier, 2)}}))
    turn = pipe.answer(LIVE_QUESTION)

    assert turn.budget["spent"]["revisions"] == 1
    assert turn.budget["executions_attempted"] == 3, turn.budget["steps"]
    assert len(turn.budget["steps"]) == 3
    assert turn.budget["spent"]["executions"] == 3


def test_a_revision_is_refused_when_the_execution_ceiling_is_reached(
        monkeypatch, period, earlier):
    """`may_revise` already asks; this proves the answer is honoured."""
    ledger = budget_mod.open_ledger()
    for _ in range(ledger.ceilings["executions"]):
        ledger.execution()

    assert not ledger.can("executions")
    assert not ledger.may_revise(), (
        "a revision was permitted with no execution left to run it with")


def test_the_counters_do_not_reset_across_a_repair(monkeypatch, period,
                                                   earlier):
    """A repair does not buy a fresh allowance."""
    ledger = budget_mod.open_ledger()
    ledger.execution()
    ledger.settle_execution(analysis="population", ok=False, reason="x")
    ledger.repair()
    ledger.execution()
    ledger.settle_execution(analysis="population", ok=True, rows=1,
                            corrected=True)

    assert ledger.executions == 2
    assert ledger.repairs == 1
    assert [s["corrected"] for s in ledger.steps] == [False, True]


# ------------------------------------------- 7. the live question, whole


def test_the_live_contracting_question_reaches_every_closing_stage(
        monkeypatch, period, earlier):
    """The trace the live run should have produced.

    Six analyses under a six-execution ceiling, then the packet, the review,
    the interpretation, the summary and the thread.
    """
    turn = _planned(monkeypatch, _steps(period, earlier, 6))

    for stage in (pipe.VALIDATION_PASSED, pipe.EXECUTION_COMPLETE,
                  pipe.RESULT_PACKET, pipe.SUFFICIENCY_COMPLETE,
                  pipe.FINAL_ANSWER, pipe.SUMMARY_UPDATED,
                  pipe.THREAD_PERSISTED):
        assert stage in turn.stages, (
            f"{stage} was never reached. Stages: {list(turn.stages)}")
    assert pipe.STOPPED_HONESTLY not in turn.stages
    assert turn.budget["spent"]["executions"] <= 6


def test_every_model_stage_is_still_served_by_a_model(monkeypatch, period,
                                                      earlier):
    """The acceptance target: seven model stages, none of them fallen back."""
    turn = _planned(monkeypatch, _steps(period, earlier, 6))

    for stage in (pipe.SONNET_PASS_1, pipe.SONNET_PASS_2,
                  pipe.FUNCTIONALITY_SELECTED, pipe.PLAN_CREATED,
                  pipe.SUFFICIENCY_COMPLETE, pipe.FINAL_ANSWER,
                  pipe.SUMMARY_UPDATED):
        assert turn.engines.get(stage) == seam_mod.MODEL, (
            f"{stage} fell back: {turn.engines.get(stage)}")
    assert turn.budget["model_calls_charged"] == 7
    assert turn.budget["model_calls_succeeded"] == 7
    assert turn.budget["model_calls_failed"] == 0


# -------------------------------------------------- the ceiling is unchanged


def test_the_standard_execution_ceiling_was_not_raised():
    """The fix is sequencing, not headroom."""
    assert budget_mod.CEILINGS[budget_mod.STANDARD]["executions"] == 6
    assert budget_mod.CEILINGS[budget_mod.DEEP]["executions"] == 14


def test_the_trace_and_the_ledger_describe_the_same_turn(
        monkeypatch, period, earlier):
    """No hidden pre-consumption, checked from both ends."""
    turn = _planned(monkeypatch, _steps(period, earlier, 7))
    complete = [e for e in turn.events if e.stage == pipe.EXECUTION_COMPLETE]

    assert complete
    detail = complete[0].detail
    assert detail["attempted"] == turn.budget["executions_attempted"]
    assert detail["succeeded"] == turn.budget["executions_succeeded"]
    assert detail["failed"] == turn.budget["executions_failed"]
    assert detail["steps"] == len(turn.packet.steps)
    assert len(turn.budget["steps"]) == detail["attempted"]
