"""The state machine approves transitions; the model only requests them.
Specification section 11."""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import states as st


def drive(machine: st.Machine, *targets: str) -> st.Machine:
    for t in targets:
        machine.advance(t)
    return machine


def test_the_happy_path_reaches_completed():
    m = drive(st.Machine(), st.NORMALIZING_1, st.NORMALIZING_2,
              st.BUILDING_CONTEXT, st.FUNCTIONALITY_ASSESSMENT, st.PLANNING,
              st.VALIDATING, st.EXECUTING, st.REVIEWING, st.ANSWERING,
              st.SUMMARIZING, st.COMPLETED)
    assert m.finished and m.state == st.COMPLETED


def test_the_gate_cannot_be_skipped():
    m = drive(st.Machine(), st.NORMALIZING_1, st.NORMALIZING_2,
              st.BUILDING_CONTEXT)
    with pytest.raises(st.IllegalTransition):
        m.advance(st.EXECUTING)
    with pytest.raises(st.IllegalTransition):
        m.advance(st.PLANNING)


def test_a_referral_performs_no_execution_by_construction():
    """Section 9.6: a referral performs ZERO analytical executions. The state
    machine makes that structural rather than a matter of discipline."""
    m = drive(st.Machine(), st.NORMALIZING_1, st.NORMALIZING_2,
              st.BUILDING_CONTEXT, st.FUNCTIONALITY_ASSESSMENT)
    assert not m.may(st.EXECUTING)
    assert not m.may(st.VALIDATING)
    assert m.may(st.SUMMARIZING) and m.may(st.REDIRECTED)


def test_a_validation_failure_returns_to_planning_not_to_execution():
    """Section 7.6A: only Opus authors the next candidate, so the edge out of
    VALIDATING on failure goes back to PLANNING."""
    m = drive(st.Machine(), st.NORMALIZING_1, st.NORMALIZING_2,
              st.BUILDING_CONTEXT, st.FUNCTIONALITY_ASSESSMENT, st.PLANNING,
              st.VALIDATING)
    assert m.may(st.PLANNING) and m.may(st.EXECUTING)
    m.advance(st.PLANNING, "validation failed; Opus authors the repair")
    assert m.state == st.PLANNING


def test_a_stopped_request_is_not_reopened():
    m = drive(st.Machine(), st.NORMALIZING_1)
    m.advance(st.TIMED_OUT)
    with pytest.raises(st.IllegalTransition) as e:
        m.advance(st.PLANNING)
    assert "not reopened" in str(e.value)


def test_every_working_state_can_stop_on_a_hard_limit():
    for state in st.WORKING:
        if state == st.SUMMARIZING:
            continue          # summarizing stops into the answer's own status
        allowed = st.TRANSITIONS[state]
        for reason in (st.BUDGET_EXCEEDED, st.TIMED_OUT, st.CANCELLED,
                       st.PROVIDER_ERROR, st.CONTEXT_TOO_LARGE):
            assert reason in allowed, f"{state} cannot stop on {reason}"


def test_terminal_states_have_no_outgoing_edges():
    for state in st.TERMINAL:
        assert st.TRANSITIONS[state] == ()


def test_progress_messages_name_the_actual_work():
    assert st.progress(st.EXECUTING, submission=3,
                       submission_max=5) == "Executing submission 3 of 5"
    assert st.progress(st.REVIEWING, round=2,
                       round_max=3) == "Reviewing the results, round 2 of 3"
    assert "complete" not in st.progress(st.PLANNING).lower()
