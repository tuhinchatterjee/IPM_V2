"""
The live orchestration failure: one recovery token, two phases.

MODEL MOCK · REAL DATABASE/RUNNER. No paid provider call.

A live analytical run did everything right and was thrown away at the end:

    ... first useful provider response ~38s
    ... a later response was CUT OFF before the action was complete
    ... one structure regeneration used
    ... regenerated execute_analysis succeeded
    ... query validated and bound
    ... query EXECUTED, rows returned
    ... publication stopped:
        "the one structure-regeneration attempt for this run was already used."
    ... terminal: CALL_LIMIT

The analysis succeeded. What failed was the bookkeeping around it. A single
`format_recoveries` counter, limit one, is spent by THREE different
situations in TWO different phases -- a truncated action, a turn with no tool
call, and a rejected batch -- so a hiccup while AUTHORING the analysis
silently disarmed the recovery that WRITING THE ANSWER would later need.

Those are different phases with different costs. Re-asking for a compact
action is cheap and happens before any work exists; re-asking for an answer
happens after the SQL has run and the result is already paid for. Sharing one
token between them means the second failure is charged for the first.
"""

from __future__ import annotations

import json
import pathlib

import oracles
import pytest
from conftest import ScriptedResult, final, intent, tool_call

from backend.cockpit_v4 import states as st
from backend.cockpit_v4.provider import OutputTruncated


def _ead_call(quarter: str, call_id: str = "tu-1"):
    from test_vertical_slice import EAD_SQL, _execute_call

    return _execute_call(
        EAD_SQL, purpose="EAD by sector", grain="sector",
        units="amount", subquestions=["EAD by sector"],
        fields=["cockpit_facility_quarter.ead_reported"],
        quarter=quarter, call_id=call_id)


def _execution_result(messages):
    """The executed result, wherever it sits in the thread.

    After a rejected answer the LAST message is the rejection, not the
    execution -- and the analyst still has the successful result behind it.
    Reading only the last message would make this helper depend on nothing
    having gone wrong, which is the opposite of what these tests are for.
    """
    for message in reversed(messages):
        for block in (message.get("content") or []):
            if not isinstance(block, dict):
                continue
            raw = block.get("content")
            if not isinstance(raw, str):
                continue
            try:
                body = json.loads(raw)
            except ValueError:
                continue
            if isinstance(body, dict) and body.get("steps"):
                return body
    raise AssertionError("no executed result anywhere in the thread")


def _good_answer(messages):
    """A valid final answer built from whatever the execution returned."""
    body = _execution_result(messages)
    step = body["steps"][0]
    artifact = step["artifact_id"]
    cell = step["preview"][0]
    column = next(c for c in step["columns"] if c != "sector_name")
    return ScriptedResult(tool_calls=[tool_call(
        "finalize_response",
        final(intent=intent("DATA_ANALYSIS", "COCKPIT"),
              narrative="The largest sector carries {{claim.top}}.",
              coverage=[{"subquestion": "EAD by sector",
                         "status": "answered",
                         "evidence_refs": [
                             {"artifact_id": artifact, "row_key": "r0",
                              "column_id": column}]}],
              numeric_claims=[{
                  "claim_id": "top",
                  "decimal_value": str(cell[column]),
                  "unit": "amount", "display_precision": 2,
                  "evidence": {"artifact_id": artifact, "row_key": "r0",
                               "column_id": column}}],
              tables=[{"title": "EAD by sector", "artifact_id": artifact,
                       "columns": list(cell)}]))],
        output_tokens=400)


def _bad_answer(messages):
    """A final answer whose evidence does not resolve. Correctable."""
    artifact = _execution_result(messages)["steps"][0]["artifact_id"]
    return ScriptedResult(tool_calls=[tool_call(
        "finalize_response",
        final(intent=intent("DATA_ANALYSIS", "COCKPIT"),
              narrative="Total exposure is {{claim.total}}.",
              numeric_claims=[{
                  "claim_id": "total", "decimal_value": "1.00",
                  "unit": "amount", "display_precision": 2,
                  "evidence": {"artifact_id": artifact,
                               "row_key": "all sectors",
                               "column_id": "ead_reported_sar_mn"}}]))],
        output_tokens=400)


# ---- the live sequence, end to end ------------------------------------

def test_a_truncated_action_must_not_disarm_a_truncated_answer(
        drive, store_db, release_id):
    """THE live failure, reproduced exactly.

    The live message was "the one structure-regeneration attempt for this run
    was already used" -- which is the TRUNCATION recovery, not the answer
    correction. So the second failure was the FINAL ANSWER being cut off, not
    failing validation: a long written answer is exactly the turn most likely
    to hit its output allowance, and it arrives after the SQL has already run.

    Truncated action -> recover -> analysis succeeds -> truncated ANSWER ->
    recover -> COMPLETED.
    """
    quarter = oracles.latest_quarter(release_id)
    outcome, provider, record = drive(
        "What is total exposure at default by sector in the latest quarter?",
        [OutputTruncated("cut off", limit=4096),           # action cut off
         ScriptedResult(tool_calls=[_ead_call(quarter)]),  # compact retry
         OutputTruncated("cut off", limit=4096),           # ANSWER cut off
         _good_answer])                                    # answer retry

    assert outcome.state == st.COMPLETED, (
        f"the live sequence still does not complete: {outcome.message}")
    assert outcome.response["executed"] is True
    assert "{{claim." not in outcome.response["narrative"]


def test_a_truncated_action_must_not_disarm_the_answer_correction(
        drive, store_db, release_id):
    """The same split, for an answer that fails VALIDATION rather than
    being cut off. Already worked; pinned so it keeps working."""
    quarter = oracles.latest_quarter(release_id)
    outcome, provider, record = drive(
        "What is total exposure at default by sector in the latest quarter?",
        [OutputTruncated("cut off", limit=4096),
         ScriptedResult(tool_calls=[_ead_call(quarter)]),
         _bad_answer, _good_answer])

    assert outcome.state == st.COMPLETED, outcome.message
    assert outcome.response["executed"] is True


def test_each_phase_spends_only_its_own_allowance(drive, store_db,
                                                  release_id):
    """The ledger must show one of each, not two of one."""
    quarter = oracles.latest_quarter(release_id)
    outcome, provider, record = drive(
        "What is total exposure at default by sector in the latest quarter?",
        [OutputTruncated("cut off", limit=4096),
         ScriptedResult(tool_calls=[_ead_call(quarter)]),
         OutputTruncated("cut off", limit=4096), _good_answer])
    assert outcome.state == st.COMPLETED, outcome.message

    spend = store_db.get_run(record.run_id).budget
    assert spend["action_format_recoveries"][0] == 1, spend
    assert spend["answer_format_recoveries"][0] == 1, spend


# ---- the bounds still hold --------------------------------------------

def test_a_second_truncated_action_still_fails_closed(drive, release_id):
    """Separate buckets must not make the action phase unbounded."""
    quarter = oracles.latest_quarter(release_id)
    outcome, provider, _ = drive(
        "What is total exposure at default by sector in the latest quarter?",
        [OutputTruncated("cut off", limit=4096), OutputTruncated("cut off", limit=4096),
         ScriptedResult(tool_calls=[_ead_call(quarter)])])
    assert outcome.state == st.FAILED
    assert outcome.error_code == st.CALL_LIMIT
    assert (outcome.response or {}).get("disposition") != "answer"


def test_a_second_invalid_answer_still_fails_closed(drive, release_id):
    quarter = oracles.latest_quarter(release_id)
    outcome, _, _ = drive(
        "What is total exposure at default by sector in the latest quarter?",
        [ScriptedResult(tool_calls=[_ead_call(quarter)]),
         _bad_answer, _bad_answer, _good_answer])
    assert outcome.state == st.FAILED
    assert outcome.error_code == st.ANSWER_VALIDATION


def test_a_truncated_action_never_executes_partial_arguments(drive,
                                                             store_db,
                                                             release_id):
    quarter = oracles.latest_quarter(release_id)
    outcome, provider, record = drive(
        "What is total exposure at default by sector in the latest quarter?",
        [OutputTruncated("cut off", limit=4096),
         ScriptedResult(tool_calls=[_ead_call(quarter)]),
         _good_answer])
    assert outcome.state == st.COMPLETED, outcome.message
    # Exactly one execution: the truncated turn ran nothing.
    spend = store_db.get_run(record.run_id).budget
    assert spend["execution_submissions"][0] == 1, spend
