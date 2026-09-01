"""The analyst investigates, and the rules hold whatever the model says. §2, §5, §7, §8, §10.

Every test here drives the loop with a SCRIPTED model, because the properties
being asserted are about what CreditProbe does when the model behaves badly:
refuses a question it has evidence for, asks twice, invents a figure, calls a
tool that does not exist, or never stops. None of those can be provoked from a
real model on demand, and a suite that could not provoke them would be
asserting that the loop works when the model is well behaved — which is not
where the risk is.

No live provider call is made anywhere in this file.
"""

from __future__ import annotations

import pytest

from backend.analyst import session
from backend.analyst.session import investigate
from tests.analyst.conftest import BrokenProvider, ScriptedProvider


def answer(text="Twelve borrowers are drawn above 90%.", **extra):
    return {"action": "ANSWER", "why": "the evidence supports it",
            "answer": text, **extra}


def call(tool, **arguments):
    return {"action": "CALL_TOOL", "why": f"gather {tool}", "tool": tool,
            "arguments": arguments}


class TestTheModelDrivesTheInvestigation:

    def test_it_can_look_before_it_plans(self, analyst):
        """§2's whole point: discovery, then evidence, then an answer."""
        provider = ScriptedProvider([
            call("list_datasets"),
            call("describe_dataset", dataset="portfolio_facility"),
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=5),
            answer("Contracting carries the largest exposure."),
        ])
        found = investigate("Which sectors carry the most exposure?", analyst,
                            provider=provider)

        assert found.outcome == session.ANSWER
        assert found.ledger.calls == 3
        assert [o.tool for o in found.ledger.observations] == [
            "list_datasets", "describe_dataset", "rank_entities"]
        assert "portfolio_facility" in found.ledger.datasets

    def test_the_next_step_is_chosen_from_the_last_result(self, analyst):
        """The prompt for turn N carries the result of turn N-1.

        This is the difference between an investigation and a plan executed
        blindly, and it is a property of the loop rather than of the model.
        """
        provider = ScriptedProvider([
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=3),
            answer(),
        ])
        investigate("Which sectors?", analyst, provider=provider)

        second = provider.prompts[1]
        assert "EVIDENCE SO FAR" in second
        assert "rank_entities" in second
        assert "row(s)" in second

    def test_the_original_wording_reaches_the_model(self, analyst):
        """§2: the model receives the user's own language, not a restatement."""
        question = ("Who is drawing more heavily because they are under "
                    "pressure rather than because they are growing?")
        provider = ScriptedProvider([answer()])
        investigate(question, analyst, provider=provider)
        assert question in provider.prompts[0]

    def test_a_refused_tool_is_shown_to_the_model_rather_than_thrown(
            self, analyst):
        """A refusal is a governed outcome. The model chooses again."""
        provider = ScriptedProvider([
            call("query_dataset", dataset="not_a_dataset"),
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=3),
            answer(),
        ])
        found = investigate("Which sectors?", analyst, provider=provider)

        assert found.outcome == session.ANSWER
        assert found.ledger.refusals
        assert "REFUSED" in provider.prompts[1]

    def test_the_tools_offered_are_the_ones_the_role_may_use(self, viewer):
        provider = ScriptedProvider([answer()])
        investigate("anything", viewer, provider=provider)
        # The catalogue travels in the cacheable SYSTEM prefix rather than the
        # varying user prompt (R2 §17), so what the model was offered is both
        # halves of what it was sent.
        offered = provider.systems[0] + provider.prompts[0]
        from backend.analyst import tools

        for tool in tools.REGISTRY:
            if viewer.may(tool.capability):
                assert tool.name in offered
            else:
                assert tool.name not in offered


class TestItCannotDeadEnd:
    """§8: four outcomes are permitted and "not understood" is not one."""

    def test_refusing_a_question_it_has_evidence_for_is_not_allowed(
            self, analyst):
        """The model tries to give up after a successful query. It is made to
        finish, because a partly-answerable question is answerable."""
        provider = ScriptedProvider([
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=5),
            {"action": "CANNOT", "why": "the question is too vague"},
            answer("Contracting is the largest sector exposure."),
        ])
        found = investigate("Which sectors carry the most exposure?", analyst,
                            provider=provider)

        assert found.outcome == session.ANSWER
        assert any("do not refuse the whole question" in (o.refused or "")
                   for o in found.ledger.observations)

    def test_refusing_with_nothing_found_is_honest_and_allowed(self, analyst):
        """The counter-test. Forcing an answer out of an empty ledger would be
        the opposite defect."""
        provider = ScriptedProvider([
            {"action": "CANNOT",
             "why": "Nothing in the governed catalogue bears on the weather."},
        ])
        found = investigate("What is the weather in Riyadh?", analyst,
                            provider=provider)

        assert found.outcome == session.CANNOT
        assert "weather" in found.answer

    def test_asking_twice_is_not_a_clarification(self, analyst):
        """§5/§8. One question back, then it works with what it has."""
        provider = ScriptedProvider([
            {"action": "ASK", "why": "ambiguous",
             "question": "Do you mean the booked stage or the predicted one?",
             "assumption": "the booked stage"},
            answer(),
        ])
        found = investigate("Which borrowers are Stage 2?", analyst,
                            provider=provider, context="already asked once")

        assert found.outcome == session.ANSWER, (
            "a second question should have been ignored")

    def test_one_question_back_is_allowed_and_carries_its_assumption(
            self, analyst):
        provider = ScriptedProvider([
            {"action": "ASK", "why": "two governed measures fit",
             "question": ("Do you mean the current 12-month PD, or "
                          "deterioration since last quarter?"),
             "assumption": "the current 12-month PD"},
        ])
        found = investigate(
            "Which borrowers have the highest probability of deterioration?",
            analyst, provider=provider)

        assert found.outcome == session.ASK
        assert found.question_back.endswith("?")
        assert found.assumption
        assert "\n" not in found.question_back, (
            "a clarification is one sentence, not a card")

    def test_running_out_of_turns_answers_on_what_was_found(self, analyst):
        provider = ScriptedProvider([
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=3),
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ecl", top=3),
        ])
        found = investigate("Which sectors?", analyst, provider=provider,
                            max_turns=2)

        assert found.outcome == session.ANSWER
        assert found.answer
        assert "step limit" in found.answer

    def test_a_provider_failure_is_an_error_not_an_exception(self, analyst):
        found = investigate("anything", analyst, provider=BrokenProvider())
        assert found.error == "provider_failed"
        assert found.outcome == session.CANNOT

    def test_no_provider_is_reported_rather_than_guessed_at(self, analyst):
        class Unconfigured:
            configured = False

        found = investigate("anything", analyst, provider=Unconfigured())
        assert found.error == "no_provider"


class TestPartialEvidence:
    """§7: answer the supported portion, disclose the unsupported one."""

    def test_the_unavailable_dimensions_survive_onto_the_result(self, analyst):
        provider = ScriptedProvider([
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=5),
            answer("Contracting shows the most utilisation pressure.",
                   findings=["Contracting is the largest exposure."],
                   unavailable=["cash balances", "short-term debt maturities"]),
        ])
        found = investigate(
            "Which borrowers show liquidity stress? Consider cash balances, "
            "short-term debt maturities and utilisation.", analyst,
            provider=provider)

        assert found.unavailable == ["cash balances",
                                     "short-term debt maturities"]
        assert found.answer

    def test_a_missing_dataset_is_named_rather_than_silently_skipped(
            self, analyst):
        from backend.analyst import tools
        from backend.analyst.safety import Principal

        narrow = Principal(user_id=4, role="ANALYST",
                           datasets=frozenset({"portfolio_facility"}))
        found = tools.call(narrow, "fetch_ifrs9_evidence",
                           {"customer_id": "CORP-1"})
        assert found.refused
        assert "corporate_ifrs9" in found.refused
        assert "unavailable" in found.refused


class TestGrounding:
    """§42: a figure that is in no observation is not a figure."""

    def test_an_invented_number_is_removed(self, analyst):
        provider = ScriptedProvider([
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=3),
            answer("Exposure to Contracting is 999999.99 million.",
                   findings=["Contracting is 999999.99 million."]),
        ])
        found = investigate("How large is Contracting?", analyst,
                            provider=provider)

        assert "999999.99" in " ".join(found.removed)
        assert "999999.99" not in found.answer
        assert not any("999999.99" in f for f in found.findings)
        assert found.limitations, "the removal must be stated, not hidden"

    def test_a_figure_that_came_from_a_tool_survives(self, analyst):
        """The counter-test. A grounding check that removes real figures is a
        grounding check nobody leaves switched on."""
        from backend.analyst import tools

        observed = tools.call(analyst, "rank_entities", {
            "dataset": "portfolio_facility", "entity": "sector",
            "measure": "ead", "top": 3})
        value = observed.rows[0]["value"]
        provider = ScriptedProvider([
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=3),
            answer(f"The largest sector carries {value:.1f}."),
        ])
        found = investigate("How large is the largest sector?", analyst,
                            provider=provider)

        assert not found.removed, found.removed
        assert f"{value:.1f}" in found.answer

    def test_a_year_is_not_treated_as_an_unsupported_figure(self, analyst):
        provider = ScriptedProvider([
            call("get_dataset_periods", dataset="portfolio_facility"),
            answer("The latest reporting period is Q2 2026."),
        ])
        found = investigate("What period is this?", analyst, provider=provider)
        assert not found.removed


class TestTheBudget:
    """§50: a bound is a control; a prompt asking for brevity is not."""

    def test_tool_calls_are_capped(self, analyst):
        # Six DIFFERENT calls. Six identical ones would be stopped by §18's
        # repeat rule before the budget was ever reached, and the test would
        # pass while proving the wrong thing.
        provider = ScriptedProvider(
            [call("rank_entities", dataset="portfolio_facility",
                  entity="sector", measure="ead", top=top)
             for top in range(3, 9)]
            + [answer()])
        found = investigate("Which sectors?", analyst, provider=provider,
                            max_turns=8, max_tool_calls=2)

        ran = [o for o in found.ledger.observations if o.ok]
        assert len(ran) <= 2
        assert any("budget" in (o.refused or "") for o in
                   found.ledger.observations)

    def test_discovery_does_not_spend_the_budget(self, analyst):
        """Looking is free. A model that cannot afford to read the data
        dictionary will guess a field name instead, which is worse."""
        provider = ScriptedProvider([
            call("list_datasets"),
            call("list_data_domains"),
            call("describe_dataset", dataset="portfolio_facility"),
            call("rank_entities", dataset="portfolio_facility",
                 entity="sector", measure="ead", top=3),
            answer(),
        ])
        found = investigate("Which sectors?", analyst, provider=provider,
                            max_tool_calls=1)

        assert found.outcome == session.ANSWER
        assert all(o.ok for o in found.ledger.observations), (
            [o.refused for o in found.ledger.observations])

    def test_turns_are_capped(self, analyst):
        provider = ScriptedProvider(
            [call("list_datasets") for _ in range(3)])
        found = investigate("anything", analyst, provider=provider,
                            max_turns=3)
        assert found.turns == 3
        assert provider.calls == 3


class TestWhatTheModelIsTold:

    def test_the_system_prompt_forbids_naming_the_vendor(self, analyst):
        provider = ScriptedProvider([answer()])
        investigate("anything", analyst, provider=provider)
        assert "Never name the intelligence provider" in provider.systems[0]

    def test_the_system_prompt_says_it_never_calculates(self, analyst):
        provider = ScriptedProvider([answer()])
        investigate("anything", analyst, provider=provider)
        assert "never calculate" in provider.systems[0].lower()

    def test_the_last_turn_is_told_it_is_the_last(self, analyst):
        provider = ScriptedProvider([call("list_datasets"), answer()])
        investigate("anything", analyst, provider=provider, max_turns=2)
        assert "last turn" in provider.prompts[-1]

    def test_the_result_carries_every_step_for_the_trace(self, analyst):
        provider = ScriptedProvider([
            call("list_datasets"), call("rank_entities",
                                        dataset="portfolio_facility",
                                        entity="sector", measure="ead", top=3),
            answer(),
        ])
        found = investigate("Which sectors?", analyst, provider=provider)
        payload = found.to_dict()

        assert len(payload["steps"]) == 3
        assert payload["evidence"]["calls"] == 2
        assert payload["evidence"]["hash"]
        assert all(step["why"] for step in payload["steps"])

    def test_the_result_names_no_vendor(self, analyst):
        """§12 applies to the analyst's own output too."""
        import json

        from backend.release import product_copy

        provider = ScriptedProvider([call("list_datasets"), answer()])
        found = investigate("Which datasets exist?", analyst,
                            provider=provider)
        assert not product_copy.violations(json.dumps(found.to_dict()))


@pytest.mark.parametrize("bad", [
    {"action": "NONSENSE", "why": "x"},
    {"why": "no action at all"},
    {},
])
def test_a_reply_that_does_not_conform_is_not_salvaged(analyst, bad):
    """A malformed decision becomes CANNOT rather than a guess.

    Guessing what a model meant is how a filter goes missing and an analysis
    answers a slightly different question with complete confidence.
    """
    found = investigate("anything", analyst, provider=ScriptedProvider([bad]))
    assert found.outcome == session.CANNOT
