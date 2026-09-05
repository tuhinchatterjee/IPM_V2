"""What the agent may do, and — mostly — what it may not.

An agent surface is where a carefully governed engine gets handed to
something that will try to be helpful. Nearly every test here is a
prohibition, because the failure mode is not the agent refusing something it
should allow — it is the agent finding a way to be useful that the engine's
authors did not intend.
"""

from __future__ import annotations

import pytest

from backend.agentic.tools import ToolDenied, ToolUnknown
from backend.scorecard import domains
from backend.scorecard.validation import agent, registry, states

# --------------------------------------------------- the prohibitions hold


def test_no_tool_accepts_a_query_or_an_expression() -> None:
    """The strongest form the prohibition takes: nothing to call.

    §14's list of what an agent may never have — arbitrary SQL, arbitrary
    Python, unrestricted filters — is enforced here by there being no
    parameter through which any of it could arrive.
    """
    forbidden = {"sql", "query", "expression", "code", "python", "filter",
                 "where", "predicate", "columns", "select", "eval",
                 "dataset", "table", "path", "file"}
    for tool in agent.TOOLS:
        overlap = forbidden & set(tool.parameters)
        assert not overlap, f"{tool.tool_id} accepts {overlap}"


def test_no_tool_writes() -> None:
    """Nothing this agent can call changes stored state."""
    for tool in agent.TOOLS:
        assert not tool.writes, f"{tool.tool_id} is a writer"


def test_an_unknown_tool_cannot_be_invoked() -> None:
    with pytest.raises(ToolUnknown):
        agent.invoke("scv_run_sql", model_id="sme_champion")


def test_an_unknown_parameter_is_refused_not_ignored() -> None:
    """An ignored parameter is a caller who believes it did something.

    Dropping a `filter` silently returns a portfolio number that will be
    quoted as a filtered one.
    """
    with pytest.raises(ToolDenied, match="does not accept"):
        agent.invoke(agent.RUN_TEST, model_id="sme_champion",
                     test_id="DISC-AUC", filter="segment = 'MICRO'")


def test_a_domain_outside_the_three_is_refused() -> None:
    with pytest.raises((ToolDenied, agent.Clarify)):
        agent.invoke(agent.RUN_TEST, model_id="retail.exposures",
                     test_id="DISC-AUC")


def test_the_agent_publishes_what_it_has_no_tool_for() -> None:
    """A reader should find the absence, not infer it from silence."""
    published = agent.catalogue()["no_tool_for"]
    assert any("SQL" in key for key in published)
    assert any("raw rows" in key for key in published)
    assert any("limit" in key for key in published)


def test_the_catalogue_states_that_it_computes_nothing() -> None:
    assert "does not calculate" in agent.catalogue()["computes_nothing"]


# ------------------------------------------------- it clarifies, not guesses


def test_a_missing_model_is_a_question_not_a_default() -> None:
    """Three scorecards, three sets of limits. Picking one is not helping."""
    with pytest.raises(agent.Clarify) as raised:
        agent.invoke(agent.RUN_TEST, test_id="DISC-AUC")
    payload = raised.value.to_dict()
    assert payload["clarification_required"] is True
    assert "model_id" in payload["question"] or "Which" in payload["question"]


def test_the_clarification_offers_the_real_options() -> None:
    with pytest.raises(agent.Clarify) as raised:
        agent.invoke(agent.PERIODS, model_id="")
    offered = {o["model_id"] for o in raised.value.options}
    assert offered == {"retail_application_champion",
                       "retail_behaviour_champion", "sme_champion"}


def test_an_unknown_test_is_a_question_not_an_approximation() -> None:
    """Running a near-match under the requested name cites a phantom."""
    with pytest.raises(agent.Clarify) as raised:
        agent.invoke(agent.RUN_TEST, model_id="sme_champion",
                     test_id="discrimination-ish")
    assert raised.value.options


def test_a_test_alias_resolves_without_a_question() -> None:
    """Clarifying what is already unambiguous is its own failure."""
    answer = agent.invoke(agent.RUN_TEST, model_id="sme_champion",
                          test_id="auc")
    assert answer["test"]["test_id"] == "DISC-AUC"


# ---------------------------------------------------------- it works


def test_it_lists_exactly_three_scorecards() -> None:
    answer = agent.invoke(agent.LIST_MODELS)
    assert len(answer["scorecards"]) == 3


def test_it_lists_every_test() -> None:
    answer = agent.invoke(agent.LIST_TESTS)
    assert len(answer["tests"]) == len(registry.TESTS)


def test_it_explains_what_a_test_cannot_tell_you() -> None:
    answer = agent.invoke(agent.EXPLAIN_TEST, test_id="CAL-OE")
    assert answer["test"]["test_id"] == "CAL-OE"
    assert answer["cannot_tell_you"], (
        "a test that states no limitation is a test being oversold")


def test_it_answers_maturity_before_anything_else(
        ) -> None:
    answer = agent.invoke(agent.PERIODS, model_id="sme_champion")
    assert answer["immature"]
    assert "not the same as no defaults" in answer["what_immature_means"]


def test_a_run_returns_a_result_not_rows() -> None:
    """The smallest unit is a Result. There is nothing left to aggregate."""
    answer = agent.invoke(agent.RUN_TEST, model_id="sme_champion",
                          test_id="DISC-AUC")
    result = answer["result"]
    assert set(result) >= {"state", "value", "limit", "detail",
                           "calculation_version"}
    assert "rows" not in result


def test_a_run_on_an_immature_period_refuses(
        ) -> None:
    periods = agent.invoke(agent.PERIODS, model_id="sme_champion")
    immature = periods["immature"][-1]
    answer = agent.invoke(agent.RUN_TEST, model_id="sme_champion",
                          test_id="DISC-AUC", period=immature)
    assert answer["result"]["state"] == states.NOT_MATURED
    assert answer["result"]["value"] is None


def test_the_findings_tool_returns_the_shortlist_too() -> None:
    answer = agent.invoke(agent.FINDINGS, model_id="sme_champion")
    assert answer["findings"]
    assert len(answer["burning_weaknesses"]) <= 5
    assert answer["summary"]["patterns_matched"]


def test_the_report_tool_produces_a_draft_and_says_so() -> None:
    answer = agent.invoke(agent.DRAFT_REPORT, model_id="sme_champion")
    assert "draft" in answer["this_is_a_draft"].lower()
    assert answer["opinion"]
    assert answer["content_hash"]


def test_the_regulatory_tool_carries_its_disclaimer() -> None:
    answer = agent.invoke(agent.REGULATORY, model_id="sme_champion")
    assert answer["this_is_not_a_compliance_assessment"] is True


# -------------------------------------------------------- and it redirects


def test_an_out_of_scope_question_says_where_the_answer_lives() -> None:
    """A refusal that leaves somebody stuck is one they route around."""
    answer = agent.refuse_out_of_domain("What is the group's IFRS 9 ECL?")
    assert answer["refused"] is True
    assert answer["where_instead"] == domains.REDIRECT_SENTENCE
    assert answer["route"] == domains.REDIRECT_ROUTE
