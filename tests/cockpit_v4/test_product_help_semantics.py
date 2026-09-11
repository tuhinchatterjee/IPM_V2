"""
Product Help: scope, semantic equivalence, and the one-generation policy.

Evidence: UNIT for the coverage and retrieval rules, MODEL MOCK for the runs.
The scripted analyst lets us check what CreditProbe PUT IN FRONT of the model
and how many generations the run cost -- which is exactly what the live
`run-53dfe2c6f10c480bb7b2d033273a6427` spent two of. It says nothing about the
wording Opus chooses.
"""

from __future__ import annotations

import pytest

from backend.cockpit_v4 import product_knowledge as pk
from backend.cockpit_v4.contracts import (TOOL_FINALIZE, TOOL_NAMES,
                                          TOOL_PRODUCT, provider_tools)
from conftest import ScriptedResult, final, intent, tool_call

# ---- the two scopes -----------------------------------------------------

BROAD = [
    "Who are you?",
    "What are you?",
    "What is CreditProbe?",
    "Tell me about CreditProbe.",
    "What is CreditProbe AI?",
    "What does CreditProbe do?",
    "What problem does CreditProbe solve?",
    "Why would a CRO use CreditProbe?",
    "What can CreditProbe do?",
    "What are the seven main functionalities?",
    "Explain CreditProbe at a high level.",
]

COCKPIT = [
    "What is Cockpit?",
    "What is Cockpit in CreditProbe?",
    "What does Cockpit do?",
    "Why should I use Cockpit?",
    "Explain CreditProbe Cockpit.",
    "What problem does Cockpit solve?",
]

DEEP = [
    "Explain TAC.",
    "What are the four EWS layers?",
    "How does Playbook work?",
    "How do Cockpit and What-If differ?",
    "How does AI Project Planner track dependencies?",
    "What is Graph Data?",
    "How does Scorecard Validation work?",
    "Explain External Intelligence.",
]


@pytest.mark.parametrize("question", BROAD)
def test_a_broad_product_question_is_one_generation(question):
    verdict = pk.coverage(question)
    assert verdict["level"] == pk.COVERAGE_SYNOPSIS, question
    assert verdict["deep_topics_named"] == []


@pytest.mark.parametrize("question", COCKPIT)
def test_a_cockpit_question_is_scoped_to_cockpit(question):
    verdict = pk.coverage(question)
    assert verdict["level"] == pk.COVERAGE_RETRIEVAL, question
    assert "cockpit" in verdict["deep_topics_named"]


@pytest.mark.parametrize("question", DEEP)
def test_a_specific_question_still_retrieves(question):
    verdict = pk.coverage(question)
    assert verdict["level"] == pk.COVERAGE_RETRIEVAL, question
    assert verdict["deep_topics_named"]


def test_similar_intent_does_not_mean_the_same_grounding():
    """"Who are you?" and "What is Cockpit?" must not be the same answer."""
    broad = pk.synopsis()
    cockpit = pk.retrieve(query="What is Cockpit of CreditProbe?")
    section = next(s for s in cockpit["sections"] if s["topic"] == "cockpit")

    # The Cockpit answer has material the broad one does not: what Cockpit
    # owns in detail, its boundary, and where it stops.
    assert section["boundary"]
    assert section["three_beats"]
    assert section["example_questions"]
    broad_text = str(broad)
    assert section["boundary"] not in broad_text
    # And the broad synopsis still situates Cockpit, so a Cockpit answer can
    # place it inside the product without a second retrieval.
    assert any(m["name"] == "Cockpit" for m in broad["seven_functionalities"])


def test_a_cockpit_question_retrieves_its_boundaries_against_the_neighbours():
    sections = pk.retrieve(query="What problem does Cockpit solve?")["sections"]
    titles = " ".join(str(s.get("title", "")) for s in sections)
    assert "Cockpit" in titles
    relationships = [s for s in sections if s["topic"] == "relationships"]
    assert relationships, "a Cockpit answer can say where Cockpit ends"


# ---- what must never leak ----------------------------------------------

@pytest.mark.parametrize("question", BROAD + COCKPIT + DEEP)
def test_no_product_answer_can_reach_the_superseded_architecture(question):
    payload = str(pk.retrieve(query=question)) + str(pk.synopsis())
    lowered = payload.lower()
    for forbidden in ("multi-agent", "multi agent", "orchestrator agent",
                      "agent swarm"):
        assert forbidden not in lowered, f"{question}: leaked {forbidden}"


def test_the_grounding_carries_no_release_ids_or_route_names():
    payload = str(pk.synopsis())
    for forbidden in ("v4-uat-", "/api/v1/", "cockpit_facility_quarter",
                      "dataset_release_id"):
        assert forbidden not in payload, forbidden


# ---- the tool policy ----------------------------------------------------

def test_withholding_removes_only_the_product_tool():
    full = [t["name"] for t in provider_tools()]
    assert set(full) == set(TOOL_NAMES)
    trimmed = [t["name"] for t in provider_tools(withhold=(TOOL_PRODUCT,))]
    assert TOOL_PRODUCT not in trimmed
    assert set(full) - set(trimmed) == {TOOL_PRODUCT}


def test_the_run_can_never_lose_its_way_to_terminate():
    names = [t["name"] for t in provider_tools(withhold=(TOOL_FINALIZE,))]
    assert TOOL_FINALIZE in names


def test_an_unknown_tool_name_in_withhold_is_refused():
    with pytest.raises(ValueError):
        provider_tools(withhold=("inspect_the_vibes",))


def test_who_are_you_is_offered_four_tools_and_costs_one_generation(
        drive, store_db):
    script = [ScriptedResult(tool_calls=[tool_call("finalize_response", {
        **intent(mode="PRODUCT_HELP", owner="COCKPIT"),
        **final(disposition="answer",
                narrative="# CreditProbe AI\n\nAn intelligent credit "
                          "investigation layer for risk teams.")})])]
    outcome, provider, record = drive("Who are you?", script)

    assert outcome.state == "COMPLETED"
    assert len(provider.sent) == 1, "one generation, no retrieval round trip"
    offered = [t["name"] for t in provider.sent[0]["tools"]]
    assert TOOL_PRODUCT not in offered
    assert TOOL_FINALIZE in offered
    assert len(offered) == len(TOOL_NAMES) - 1

    run = store_db.get_run(record.run_id)
    assert run.budget["generation_attempts"][0] == 1


def test_a_cockpit_question_is_offered_the_product_tool_from_the_start(drive):
    def second(messages):
        return ScriptedResult(tool_calls=[tool_call("finalize_response", {
            **intent(mode="PRODUCT_HELP", owner="COCKPIT"),
            **final(disposition="answer",
                    narrative="## Cockpit\n\nIt interrogates the recorded "
                              "book.")})])

    script = [ScriptedResult(tool_calls=[tool_call(
        "inspect_product_knowledge", {
            **intent(mode="PRODUCT_HELP", owner="COCKPIT"),
            "query": "What is Cockpit?", "topics": ["cockpit"],
            "detail": "standard"})]), second]
    outcome, provider, _record = drive("What is Cockpit of CreditProbe?",
                                       script)

    assert outcome.state == "COMPLETED"
    offered = [t["name"] for t in provider.sent[0]["tools"]]
    assert TOOL_PRODUCT in offered, "a named module needs the retrieval tool"


def test_a_withheld_tool_comes_back_for_the_second_action(drive):
    """The economy is first-action only. It can never strand a run."""
    def second(messages):
        return ScriptedResult(tool_calls=[tool_call(
            "inspect_product_knowledge", {
                **intent(mode="PRODUCT_HELP", owner="COCKPIT"),
                "query": "tac", "topics": ["tac"], "detail": "standard"})])

    def third(messages):
        return ScriptedResult(tool_calls=[tool_call("finalize_response", {
            **intent(mode="PRODUCT_HELP", owner="COCKPIT"),
            **final(disposition="answer", narrative="TAC is a classifier.")})])

    # A first action that is NOT a finalization, on a question the policy
    # judged synopsis-covered.
    script = [ScriptedResult(tool_calls=[tool_call("inspect_catalog", {
        **intent(mode="DATA_ANALYSIS", owner="COCKPIT"),
        "query": "exposure", "relation_ids": [], "field_ids": [],
        "detail": ["discovery"], "reporting_quarters": [], "sample_rows": 0,
        "cursor": ""})]), second, third]

    outcome, provider, _record = drive("Who are you?", script)
    assert outcome.state == "COMPLETED"
    first_offer = [t["name"] for t in provider.sent[0]["tools"]]
    second_offer = [t["name"] for t in provider.sent[1]["tools"]]
    assert TOOL_PRODUCT not in first_offer
    assert TOOL_PRODUCT in second_offer
    assert set(second_offer) == set(TOOL_NAMES)


def test_the_context_tells_the_model_which_policy_applies(drive):
    script = [ScriptedResult(tool_calls=[tool_call("finalize_response", {
        **intent(mode="PRODUCT_HELP", owner="COCKPIT"),
        **final(disposition="answer", narrative="Hello.")})])]
    _outcome, provider, _record = drive("Who are you?", script)
    sent = provider.first_input_text()
    assert "product_knowledge_coverage" in sent
    assert pk.COVERAGE_SYNOPSIS in sent


def test_the_instruction_states_the_scope_rule():
    from backend.cockpit_v4 import context as context_mod

    instruction = context_mod.analyst_instruction()
    assert "Answer it in\nthis one action" in instruction
    assert "not the same answer" in instruction
