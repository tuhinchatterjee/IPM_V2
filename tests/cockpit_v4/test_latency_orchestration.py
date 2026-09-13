"""
Orchestration under realistic provider latency, without waiting for it.

MODEL MOCK · REAL DATABASE/RUNNER. No paid provider call, and no wall-clock
sleeping: a provider that takes 35 seconds is simulated by advancing the
ledger's own clock, which is the clock every deadline decision reads.

Why this exists
---------------
The deterministic suite answers in milliseconds, so every deadline bound
passes trivially and none of them is actually exercised. A live Standard run
budgeted at 120 seconds reached about 143. Tests that never spend time cannot
see that, and adding real sleeps would trade one blind spot for a suite
nobody runs.

So the clock moves instead. `advance` rewinds `started_monotonic`, which is
exactly what `remaining_seconds` subtracts from -- the same arithmetic the
production guard uses, driven from the test.
"""

from __future__ import annotations

import json

import oracles
import pytest
from conftest import ScriptedResult, final, intent, tool_call

from backend.cockpit_v4 import states as st
from test_orchestration_recovery import (_ead_call, _execution_result,
                                         _good_answer)


class Slow:
    """A provider turn that 'takes' a given number of seconds."""

    def __init__(self, seconds: float, result) -> None:
        self.seconds = seconds
        self.result = result

    def __call__(self, messages):
        _advance(self.seconds)
        return self.result(messages) if callable(self.result) else self.result


_LEDGER: list = []


def _advance(seconds: float) -> None:
    for ledger in _LEDGER:
        ledger.started_monotonic -= seconds


@pytest.fixture
def slow_drive(store_db, runtime, make_run, monkeypatch):
    """`drive`, with a handle on the ledger so turns can consume time."""
    from backend.cockpit_v4 import budgets
    from backend.cockpit_v4.worker import Worker
    from conftest import ScriptedProvider

    _LEDGER.clear()
    original = budgets.Ledger.__init__

    def remember(self, *args, **kwargs):
        original(self, *args, **kwargs)
        _LEDGER.append(self)

    monkeypatch.setattr(budgets.Ledger, "__init__", remember)

    def _drive(question: str, script, *, mode: str = "standard"):
        provider = ScriptedProvider(script)
        runtime.provider = provider
        record = make_run(question, mode=mode)
        outcome = Worker(store=store_db, runtime=runtime).execute(record)
        return outcome, provider, record
    return _drive


# ---- the clean path fits the allowance --------------------------------

def test_a_simple_analysis_finishes_well_inside_the_standard_deadline(
        slow_drive, release_id):
    """Two turns at live-like latency, inside 120 seconds."""
    quarter = oracles.latest_quarter(release_id)
    outcome, provider, _ = slow_drive(
        "What is total exposure at default by sector in the latest quarter?",
        [Slow(18.0, ScriptedResult(tool_calls=[_ead_call(quarter)])),
         Slow(16.0, _good_answer)])
    assert outcome.state == st.COMPLETED, outcome.message
    assert len(provider.sent) == 2
    assert _LEDGER, "the ledger was never constructed"
    assert _LEDGER[0].elapsed_seconds < 120.0, (
        f"the run took {_LEDGER[0].elapsed_seconds:.0f}s of a 120s allowance")


def test_a_run_with_a_recovery_still_fits(slow_drive, release_id):
    """Truncated action at 20s, retry at 25s, answer at 20s: 65s of 120."""
    from backend.cockpit_v4.provider import OutputTruncated

    quarter = oracles.latest_quarter(release_id)

    def truncate(messages):
        _advance(20.0)
        return OutputTruncated("cut off", limit=4096)

    outcome, provider, _ = slow_drive(
        "What is total exposure at default by sector in the latest quarter?",
        [truncate,
         Slow(25.0, ScriptedResult(tool_calls=[_ead_call(quarter)])),
         Slow(20.0, _good_answer)])
    assert outcome.state == st.COMPLETED, outcome.message
    assert _LEDGER[0].elapsed_seconds < 120.0


# ---- and the guard fires when it should not fit -----------------------

def test_an_action_is_refused_once_the_finalization_reserve_is_all_that_is_left(
        slow_drive, release_id):
    """The defect: burn the allowance on actions, then have no time to answer.

    The run must stop and SAY it ran out of time, not launch another action
    it cannot use.
    """
    quarter = oracles.latest_quarter(release_id)

    def glacial(messages):
        _advance(55.0)
        return ScriptedResult(tool_calls=[tool_call(
            "inspect_catalog",
            {"relations": ["cockpit_facility_quarter"], "detail": ["fields"],
             "field_ids": ["ead_reported"], "search": "",
             "sample_rows": 0})])

    outcome, provider, _ = slow_drive(
        "What is total exposure at default by sector in the latest quarter?",
        [glacial, glacial, glacial,
         ScriptedResult(tool_calls=[_ead_call(quarter)]), _good_answer])

    assert outcome.state in (st.FAILED, st.EXPIRED, st.PARTIAL), outcome.state
    assert outcome.error_code == st.DEADLINE_EXPIRED, outcome.error_code
    assert "publish" in outcome.message.lower(), outcome.message
    assert (outcome.response or {}).get("disposition") != "answer"


def test_the_answer_turn_may_spend_the_reserve_the_actions_could_not(
        slow_drive, release_id):
    """A finished analysis with little time left still gets written up."""
    quarter = oracles.latest_quarter(release_id)

    def slow_action(messages):
        # Inside the 60s the run starts on; the analytical allowance widens
        # to 120s once this action declares the turn analytical.
        _advance(45.0)
        return ScriptedResult(tool_calls=[_ead_call(quarter)])

    outcome, provider, _ = slow_drive(
        "What is total exposure at default by sector in the latest quarter?",
        [slow_action, Slow(60.0, _good_answer)])
    assert outcome.state == st.COMPLETED, (
        f"an analysis that succeeded was not published: {outcome.message}")
    assert len(provider.sent) == 2


def test_a_successful_analysis_is_preserved_when_time_runs_out(
        slow_drive, store_db, release_id):
    """Analysis success and answer success are different facts."""
    from backend.cockpit_v4 import events as ev

    quarter = oracles.latest_quarter(release_id)

    from test_orchestration_recovery import _bad_answer

    def slow_action(messages):
        _advance(45.0)
        return ScriptedResult(tool_calls=[_ead_call(quarter)])

    def slow_invalid_answer(messages):
        # The analysis has succeeded and the written answer does not bind.
        # A correction is allowed -- but by now there is no time to make
        # one, so the run stops with a stored result and no answer.
        _advance(72.0)
        return _bad_answer(messages)

    outcome, provider, record = slow_drive(
        "What is total exposure at default by sector in the latest quarter?",
        [slow_action, slow_invalid_answer, _good_answer])

    assert outcome.state != st.COMPLETED, (
        "this timing was meant to run out of time; retune it rather than "
        "letting the preservation path go unchecked")
    # A published answer that merely finished late is NOT this case: an
    # answer produced correctly is published, because discarding finished
    # work is the defect this whole round exists to remove.
    events = [e.event_type for e in store_db.events_since(record.run_id)]
    assert ev.ANALYSIS_PRESERVED in events, (
        "the SQL succeeded; a run that stops afterwards must say so rather "
        "than reading as if the mathematics failed")
    # And the result is still readable by an operator.
    run = store_db.get_run(record.run_id)
    assert run.error_code in (st.DEADLINE_EXPIRED, st.COST_LIMIT), \
        run.error_code
    artifacts = [e for e in store_db.events_since(record.run_id)
                 if e.event_type == ev.ANALYSIS_PRESERVED]
    assert artifacts, "the preserved-analysis event carries the artifact ids"
