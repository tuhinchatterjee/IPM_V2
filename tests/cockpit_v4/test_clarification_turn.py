"""
The run can put a question back, instead of guessing and answering.

MODEL MOCK · REAL DATABASE/RUNNER. No paid provider call.

The defect this exists for
--------------------------
A live Corporate run was asked:

    compare between PD, LGD & CCF and tell me what is most dominant
    on this quarter's ECL change

Every term in that question resolves. The METHOD does not: attribution can
be sequential, in which case the order decides which factor "dominates", or
it can be a symmetric allocation that does not depend on order. Those give
different rankings from the same rows. The run recorded

    Assumed: attribution is sequential (PD first, then LGD, then EAD)

and published a ranking built on a choice nobody asked for.

It was not the model being careless. Every part of the machine pushed it
there:

  * `blocking_ambiguities` stops execution and nothing else;
  * a run that is READY_FOR_EXECUTION is offered `execute_analysis` and
    REQUIRED to call it, so a refused submission comes straight back to the
    same compelled call;
  * the refusal itself advised that a resolution "belongs in
    resolved_assumptions ... which do not stop execution".

Guessing was the only move left. Meanwhile `disposition: "clarification"`
existed in the contract, mapped to WAITING_FOR_USER, and rendered in the
reader's panel as clickable options -- complete, end to end, and
unreachable.

What is pinned here:

  a declared ambiguity has somewhere to go -> NEEDS_CLARIFICATION
  the gate stops demanding execution       -> finalize is the only tool
  the refusal stops advising a guess       -> it says to ask
  the run settles as a question            -> WAITING_FOR_USER, with options
  a question with one reading is untouched -> no new round trip
"""

from __future__ import annotations

import pytest
from conftest import ScriptedResult, final, intent, tool_call

from backend.cockpit_v4 import action_state as acts
from backend.cockpit_v4 import states as st

#: The reading that changes the answer. Not a term in any catalogue.
THE_AMBIGUITY = ("attribution across PD, LGD and CCF can be sequential "
                 "(order decides the ranking) or symmetric (order-free)")

THE_OPTIONS = ["Sequential, PD first", "Sequential, LGD first",
               "Symmetric allocation (order-independent)"]


def _submits_with_a_blocking_ambiguity(quarter: str):
    """An `execute_analysis` whose intent says it cannot choose."""
    from test_vertical_slice import EAD_SQL

    return ScriptedResult(tool_calls=[tool_call("execute_analysis", {
        "intent": intent("DATA_ANALYSIS", "COCKPIT",
                         understood="attribute the ECL change",
                         ambiguities=[THE_AMBIGUITY]),
        "objective": "attribute the ECL change",
        "subquestions": ["which factor dominates"],
        "scope": {"reporting_periods": [quarter], "filters": {}},
        "metadata_receipt_ids": [],
        "fields_required": ["cockpit_facility_quarter.ead_reported"],
        "expected_output_grain": "sector", "expected_units": "amount",
        "steps": [{"step_id": "s1", "language": "sql",
                   "code": EAD_SQL.replace("?", f"'{quarter}'"),
                   "parameters": {}, "purpose": "attribution",
                   "input_artifact_ids": [], "depends_on_step_ids": []}],
        "repair_of_submission_id": ""})])


def _asks_the_reader(messages):
    """The finalize turn the run should now be able to make."""
    return ScriptedResult(tool_calls=[tool_call("finalize_response", final(
        intent=intent("DATA_ANALYSIS", "COCKPIT",
                      understood="attribute the ECL change"),
        disposition="clarification",
        narrative=("Attribution across PD, LGD and CCF depends on how the "
                   "change is split, and the two conventions rank the "
                   "factors differently."),
        clarification_question=(
            "Which attribution should I use for the ECL change?"),
        clarification_options=THE_OPTIONS))])


# ---- the gate ------------------------------------------------------------

def test_a_declared_ambiguity_takes_execution_off_the_table():
    """The state that did not exist.

    Without it the run stays READY_FOR_EXECUTION, which REQUIRES
    `execute_analysis` -- so the turn after a refusal is compelled to submit
    the same thing again.
    """
    decision = acts.decide(
        executed=False, answer_only=False, analytical=True,
        readiness={"sufficient": True}, must_clarify=True)
    assert decision.state == acts.NEEDS_CLARIFICATION
    assert decision.tools == ("finalize_response",)
    assert decision.require == "finalize_response"


def test_the_same_run_without_an_ambiguity_still_executes():
    """The gate is not loosened for everybody.

    A question with one defensible reading must not acquire a round trip.
    """
    decision = acts.decide(
        executed=False, answer_only=False, analytical=True,
        readiness={"sufficient": True})
    assert decision.state == acts.READY_FOR_EXECUTION
    assert decision.require == "execute_analysis"


def test_a_result_that_already_exists_wins():
    """An ambiguity cannot outlive the result it prevented.

    If rows exist, the thing the ambiguity was blocking already happened,
    and the run's business is publishing them.
    """
    decision = acts.decide(
        executed=True, answer_only=False, analytical=True,
        readiness={"sufficient": True}, must_clarify=True)
    assert decision.state == acts.RESULT_READY


def test_every_state_tells_a_reader_what_it_is_doing():
    """The panel reads this table; a missing row shows an internal name."""
    for state in acts.STATES:
        assert acts.PUBLIC.get(state), state


# ---- the refusal ---------------------------------------------------------

def test_the_refusal_stops_advising_a_guess(service):
    """It said the doubt "belongs in resolved_assumptions".

    That is true of a doubt that does not change the figures, and it is
    exactly the wrong thing to say to one that does -- which is the only
    kind that should ever have been declared blocking.
    """
    from backend.cockpit_v4.contracts import Rejection, parse_execution

    submission = parse_execution({
        "intent": intent("DATA_ANALYSIS", "COCKPIT",
                         understood="attribute the change",
                         ambiguities=[THE_AMBIGUITY]),
        "objective": "attribute", "subquestions": ["which factor"],
        "scope": {"reporting_months": [], "filters": {}},
        "metadata_receipt_ids": [], "fields_required": [],
        "expected_output_grain": "sector", "expected_units": "SAR million",
        "steps": [{"step_id": "s1", "language": "sql",
                   "code": "SELECT 1 AS n", "parameters": {},
                   "purpose": "p", "input_artifact_ids": [],
                   "depends_on_step_ids": []}],
        "repair_of_submission_id": ""}, max_steps=4)

    with pytest.raises(Rejection) as caught:
        service.validate_batch(submission)
    said = caught.value.message
    assert "goes back to the reader" in said, said
    assert "would NOT change the figures" in said, said


# ---- end to end ----------------------------------------------------------

def test_a_run_that_cannot_choose_asks_instead_of_guessing(drive, store_db,
                                                           release_id):
    """The live sequence, with the ending it should have had.

    This one proves the DISPOSITION settles correctly. It does not prove
    the gate: a scripted analyst calls whatever the script says next,
    whether or not the tool was offered, so this test passes even with the
    gate change reverted. `test_the_turn_that_asks_was_not_offered_execution`
    is the one that holds the mechanism, and it does fail without it --
    checked, not assumed.
    """
    import oracles

    quarter = oracles.latest_quarter(release_id)
    outcome, provider, record = drive(
        "compare between PD, LGD & CCF and tell me what is most dominant",
        [_submits_with_a_blocking_ambiguity(quarter), _asks_the_reader])

    assert outcome.state == st.WAITING_FOR_USER, outcome.message
    published = outcome.response or {}
    assert published["disposition"] == "clarification"
    assert published["clarification_question"]
    assert published["clarification_options"] == THE_OPTIONS

    # Nothing was executed under a reading nobody chose.
    assert not store_db.artifact_ids_for_run(
        record.run_id, tenant_id=record.tenant_id)


def test_the_turn_that_asks_was_not_offered_execution(drive, store_db,
                                                      release_id):
    """The mechanical claim: the compelled call is gone.

    The second request must carry `finalize_response` and nothing else --
    the run had been told to execute, and that is what made it guess.
    """
    import oracles

    quarter = oracles.latest_quarter(release_id)
    _outcome, provider, _record = drive(
        "compare between PD, LGD & CCF and tell me what is most dominant",
        [_submits_with_a_blocking_ambiguity(quarter), _asks_the_reader])

    offered = [t.get("name") for t in (provider.sent[-1].get("tools") or [])]
    assert offered == ["finalize_response"], offered


def test_a_published_result_says_what_first_went_wrong(drive, store_db,
                                                       release_id):
    """The reason reaches the ROWS, not only the process panel.

    A live run's first submission failed to parse -- `syntax error at or
    near "both"` -- recovered, executed, and then ran out of time. The
    reason it had lost those seconds sat one click away in the panel, for
    whoever thought to look. It belongs beside the result.
    """
    import oracles
    from conftest import ScriptedResult
    from test_orchestration_recovery import _ead_call
    from backend.cockpit_v4.provider import OutputTruncated

    quarter = oracles.latest_quarter(release_id)
    broken = ScriptedResult(tool_calls=[tool_call("execute_analysis", {
        "intent": intent("DATA_ANALYSIS", "COCKPIT", understood="totals"),
        "objective": "totals", "subquestions": ["totals"],
        "scope": {"reporting_periods": [quarter], "filters": {}},
        "metadata_receipt_ids": [], "fields_required": [],
        "expected_output_grain": "sector", "expected_units": "amount",
        "steps": [{"step_id": "s1", "language": "sql",
                   "code": "WITH both AS (SELECT 1) SELECT * FROM both",
                   "parameters": {}, "purpose": "totals",
                   "input_artifact_ids": [], "depends_on_step_ids": []}],
        "repair_of_submission_id": ""})])

    outcome, _provider, _record = drive(
        "What is total exposure at default by sector?",
        [broken, ScriptedResult(tool_calls=[_ead_call(quarter)]),
         OutputTruncated("cut off", limit=4096),
         OutputTruncated("cut off", limit=4096),
         OutputTruncated("cut off", limit=4096)])

    published = outcome.response or {}
    assert published.get("result_only") is True, outcome.message
    said = " ".join(published["limitations"])
    assert "first thing that went wrong" in said, said


def test_the_reader_is_told_a_question_is_being_put_back(drive, store_db,
                                                        release_id):
    """The panel says what the run is doing, in the run's own words."""
    import oracles

    quarter = oracles.latest_quarter(release_id)
    _outcome, _provider, record = drive(
        "compare between PD, LGD & CCF and tell me what is most dominant",
        [_submits_with_a_blocking_ambiguity(quarter), _asks_the_reader])

    said = " ".join(e.public_message
                    for e in store_db.events_since(record.run_id))
    assert "question" in said.lower()
