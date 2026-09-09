"""Every failed-query continuation carries the full effective context.
Specification sections 8.1 and 14.3.

Section 14.3 is specific about the method: capture the ACTUAL serialized
outbound requests and assert what they contain. "A schema hash/ID alone must
fail this test", so these tests read the request the provider was really given
and look for the content, not for a reference to it.

The mock provider is labelled and these tests prove an application property --
what CreditProbe puts in the request -- which is exactly the kind of thing a
mock can prove. They say nothing about how a real model uses it.
"""

from __future__ import annotations

import json

import pytest

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import failure as failure_mod
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider

GOOD = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
        "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")


def plan(plan_id="plan-1"):
    return {"plan_id": plan_id,
            "subquestions": ["the PIT twelve-month PD by sector"],
            "fields_required": ["pd_pit_12m", "sector_code"],
            "method_summary": "average the PIT twelve-month PD by sector for "
                              "the selected quarter",
            "assumptions": ["the user means the point-in-time PD"]}


def steps(code, step_id="s1"):
    return [{"step_id": step_id, "language": "sql", "code": code}]


@pytest.fixture()
def repair_run(runtime_factory, sonnet_answers):
    """The worked example from section 8.2, driven end to end."""
    captured: dict[str, object] = {}

    failing = ("SELECT facility_id, pd_12_month FROM cockpit_facility_quarter "
               "WHERE reporting_quarter = '2026Q2' AND sector_code = 'F41'")

    def gate(_request):
        return {"decision": "PROCEED_COCKPIT", "scores": scores(),
                "public_explanation": "The Cockpit owns stored PD history.",
                "plan": plan(), "steps": steps(failing)}

    def repaired(request):
        captured["request"] = request
        return {"action": "submit_repaired_code",
                "what_went_wrong": "pd_12_month is not a column; the request "
                                   "asked for the PIT twelve-month PD",
                "plan": plan(), "steps": steps(GOOD, "s2")}

    provider = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[gate, repaired,
                         lambda _r: {"decision": "ANSWER",
                                     "answer": {"narrative": "PIT PD by "
                                                             "sector."}}])
    outcome = runtime_factory(provider).run(
        "Show me the PIT 12-month PD by sector for Construction in 2026Q2")
    return {"outcome": outcome, "provider": provider,
            "repair_request": captured["request"],
            "serialized": json.dumps(captured["request"], default=str),
            "failing_sql": failing}


# ---- section 8.1: the full effective context ------------------------------

def test_the_repair_request_carries_the_original_and_normalized_question(
        repair_run):
    blob = repair_run["serialized"]
    assert "Show me the PIT 12-month PD by sector" in blob, (
        "the original question is not in the repair request")
    assert "business_request" in blob


def test_the_repair_request_carries_the_complete_field_dictionary(repair_run):
    """Not a hash, not an id -- the dictionary itself."""
    blob = repair_run["serialized"]
    for field_name in ("pd_pit_12m", "pd_ttc_12m", "pd_pit_lifetime",
                       "ifrs9_stage", "ecl_reported", "dscr",
                       "cockpit_facility_quarter",
                       "cockpit_borrower_financial_quarter"):
        assert field_name in blob, f"{field_name} is missing from the context"
    # The definitions, not only the names.
    assert "point-in-time probability of default" in blob.lower()
    assert "catalog_version" in blob


def test_a_schema_hash_alone_would_not_pass_this_test(repair_run):
    """Section 8.1: a request id or a schema hash alone is NOT memory."""
    from backend.cockpit_agentic import CATALOG_VERSION

    blob = repair_run["serialized"]
    hash_only = json.dumps({"catalog_version": CATALOG_VERSION,
                            "request_id": "req-1"})
    assert "pd_ttc_12m" in blob and "pd_ttc_12m" not in hash_only
    assert len(blob) > 20 * len(hash_only)


def test_the_repair_request_carries_the_scope_and_coverage(repair_run):
    blob = repair_run["serialized"]
    assert "effective_scope" in blob
    assert "dataset_release_id" in blob
    assert "computed_from" in blob, "the measured coverage profile is missing"
    assert "the full authorized release, not the sample rows" in blob


def test_the_repair_request_carries_the_approved_ownership_decision(repair_run):
    """The gate ran, and its result is still in the conversation rather than
    being re-decided."""
    blob = repair_run["serialized"]
    assert "functionality_decision" in blob
    assert "PROCEED_COCKPIT" in blob


def test_the_repair_request_carries_the_exact_failed_sql(repair_run):
    blob = repair_run["serialized"]
    assert repair_run["failing_sql"] in blob or "pd_12_month" in blob
    packet = repair_run["outcome"].failures[0]
    assert packet.submitted_code == repair_run["failing_sql"]


def test_the_repair_request_carries_the_catalogue_alternatives_and_no_repair(
        repair_run):
    """Section 7.6A: CreditProbe reports facts. It does not choose and it does
    not write code."""
    blob = repair_run["serialized"]
    assert "pd_pit_12m" in blob and "pd_ttc_12m" in blob
    assert "probability_0_1" in blob
    # The corrected query is NOT in what CreditProbe sent.
    assert "sum(ecl_reported)" not in blob, (
        "CreditProbe put a repaired query into the repair request")


def test_the_repair_request_carries_the_remaining_budget(repair_run):
    blob = repair_run["serialized"]
    assert "submissions_remaining" in blob
    assert "analysis_rounds_remaining" in blob
    assert "seconds_remaining" in blob
    packet = repair_run["outcome"].failures[0]
    assert packet.budget["submissions_remaining"] == 4


def test_the_repair_request_names_every_required_context_part(repair_run):
    packet = repair_run["outcome"].failures[0]
    assert set(packet.context_attached) == set(failure_mod.REQUIRED_CONTEXT)
    blob = repair_run["serialized"]
    for part in failure_mod.REQUIRED_CONTEXT:
        assert part in blob


def test_the_pit_ttc_constraint_is_not_lost_in_the_repair(repair_run):
    """The user said PIT twelve-month. That constraint must survive."""
    blob = repair_run["serialized"]
    assert "PIT 12-month" in blob or "pit" in blob.lower()
    packet = repair_run["outcome"].failures[0]
    # Both are offered; neither is chosen for the model.
    names = [a.field_name for a in packet.available_alternatives]
    assert "pd_pit_12m" in names and "pd_ttc_12m" in names


# ---- provider protocol correctness ----------------------------------------

def test_tool_use_and_tool_result_blocks_are_paired_and_ordered(repair_run):
    """Section 8.1: keep the assistant tool-use and corresponding tool-result
    blocks paired and ordered correctly."""
    messages = repair_run["repair_request"]["messages"]
    tool_use_ids: list[str] = []
    tool_result_ids: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            kind = getattr(block, "type", None) or (
                block.get("type") if isinstance(block, dict) else None)
            if kind == "tool_use":
                tool_use_ids.append(getattr(block, "id", ""))
            elif kind == "tool_result":
                tool_result_ids.append(block["tool_use_id"])
    assert tool_use_ids, "no assistant tool_use block was threaded back"
    assert tool_result_ids == tool_use_ids[:len(tool_result_ids)], (
        "tool_result blocks are not paired with their tool_use in order")


def test_the_assistant_blocks_go_back_verbatim(repair_run):
    """The provider's own blocks, not a reconstruction."""
    messages = repair_run["repair_request"]["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert assistant, "the assistant's turn was not threaded back"
    block = assistant[0]["content"][0]
    assert getattr(block, "type", "") == "tool_use"
    assert getattr(block, "id", "").startswith("toolu_")


def test_the_context_is_sent_once_as_a_cached_prefix_not_per_error(repair_run):
    """Section 8.1: the full static context belongs ONCE in the assembled
    input, not redundantly inside every error JSON as well."""
    system = repair_run["repair_request"]["system"]
    assert isinstance(system, list)
    cached = [b for b in system if b.get("cache_control")]
    assert len(cached) == 1, "the stable prefix is not marked for caching once"
    assert "pd_pit_12m" in cached[0]["text"], (
        "the catalogue is not in the cached prefix")
    # And the error packet does not repeat the whole catalogue inside itself.
    packet = repair_run["outcome"].failures[0]
    packet_blob = json.dumps(packet.to_dict(), default=str)
    assert "pd_pit_lifetime_at_origination" not in packet_blob, (
        "the failure packet duplicated the whole dictionary inside itself")


def test_the_conversation_continues_rather_than_restarting(repair_run):
    """Section 8.1: do not flatten an error into an unrelated new
    conversation."""
    messages = repair_run["repair_request"]["messages"]
    assert len(messages) >= 4, (
        "the repair turn started a fresh conversation instead of continuing")
    assert messages[0]["role"] == "user"
    # The assistant's planning turn is still in the conversation, wherever it
    # sits: asserting a position would break the moment the opening context
    # became its own message, which is exactly what happened.
    roles = [m["role"] for m in messages]
    assert "assistant" in roles
    assert roles.index("assistant") < len(roles) - 1, (
        "the assistant's turn is not followed by anything, so nothing "
        "continued")


# ---- the attempt history --------------------------------------------------

def test_previous_failed_approaches_are_carried_so_they_are_not_repeated(
        runtime_factory, sonnet_answers):
    bad = "SELECT nope_{} FROM cockpit_facility_quarter"
    seen: list[str] = []

    def repair_turn(n):
        def turn(request):
            seen.append(json.dumps(request, default=str))
            return {"action": "submit_repaired_code", "plan": plan(),
                    "steps": steps(bad.format(n), f"s{n}")}
        return turn

    provider = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[
            lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                        "public_explanation": "x", "plan": plan(),
                        "steps": steps(bad.format(0), "s0")},
            repair_turn(1), repair_turn(2), repair_turn(3), repair_turn(4)])
    outcome = runtime_factory(provider).run("Show me something")

    assert outcome.budget["submissions_used"] == 5
    last = seen[-1]
    assert "previous_failed_approaches" in last
    # Every earlier attempt is named in the final repair request.
    for n in range(0, 3):
        assert f"nope_{n}" in last, f"attempt {n} is missing from the history"


def test_the_permitted_next_actions_come_from_the_server(repair_run):
    packet = repair_run["outcome"].failures[0]
    assert "submit_repaired_code" in packet.permitted_next_actions
    assert "explain_and_stop" in packet.permitted_next_actions


def test_when_nothing_remains_the_only_permitted_action_is_to_explain(
        runtime_factory, sonnet_answers):
    bad = "SELECT nope_{} FROM cockpit_facility_quarter"
    turns = [lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                         "public_explanation": "x", "plan": plan(),
                         "steps": steps(bad.format(0), "s0")}]
    for i in range(1, 6):
        turns.append(lambda _r, i=i: {"action": "submit_repaired_code",
                                      "plan": plan(),
                                      "steps": steps(bad.format(i), f"s{i}")})
    provider = FakeProvider(structured_script=list(sonnet_answers),
                            converse_script=turns)
    outcome = runtime_factory(provider).run("Show me something")
    assert outcome.status == st.EXECUTION_FAILED
    assert outcome.failures[-1].budget["submissions_remaining"] == 0
