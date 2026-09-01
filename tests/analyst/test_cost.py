"""
The cost meter, the question classifier, and the budgets they enforce.

R2 §16 asks for the cost to be measured per question; §22 asks for those
measurements to be turned into budgets that a test can assert. Both are here,
because a budget without a meter is a hope and a meter without a budget is a
report nobody reads.

Every test in this file uses a scripted provider. Nothing here makes a live
call or consumes a credit.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.analyst import classify, cost, route, session
from backend.analyst.safety import Principal
from backend.llm.base import LLMResult

# ---------------------------------------------------------------- the meter


class TestWhatTheMeterCounts:
    def test_a_call_is_counted_with_the_tokens_it_consumed(self) -> None:
        meter = cost.Meter()
        meter.record_call(role="analyst", input_tokens=1200,
                          output_tokens=300, duration_ms=900)
        assert meter.model_calls == 1
        assert meter.input_tokens == 1200
        assert meter.output_tokens == 300

    def test_the_tier_comes_from_the_role_rather_than_a_default(self) -> None:
        # The bug this pins: `record_call` defaulted the tier to standard, so
        # the analyst's deep-tier calls were priced at a quarter of what they
        # cost and the first baseline under-priced itself.
        meter = cost.Meter()
        deep = meter.record_call(role="analyst", input_tokens=1000)
        light = meter.record_call(role="router", input_tokens=1000)
        assert deep.tier == cost.DEEP
        assert light.tier == cost.LIGHT
        assert deep.cost_units > light.cost_units

    def test_an_output_token_costs_more_than_an_input_token(self) -> None:
        meter = cost.Meter()
        into = meter.record_call(role="router", input_tokens=1000)
        out = meter.record_call(role="router", output_tokens=1000)
        assert out.cost_units > into.cost_units

    def test_a_cached_input_token_costs_a_fraction_of_a_fresh_one(self) -> None:
        meter = cost.Meter()
        fresh = meter.record_call(role="router", input_tokens=5000)
        cached = meter.record_call(role="router", cache_read_tokens=5000)
        assert cached.cost_units < fresh.cost_units / 5

    def test_a_cache_write_costs_more_than_a_fresh_token(self) -> None:
        # So that caching a prefix used once reads as the loss it is.
        meter = cost.Meter()
        fresh = meter.record_call(role="router", input_tokens=5000)
        written = meter.record_call(role="router", cache_write_tokens=5000)
        assert written.cost_units > fresh.cost_units

    def test_a_failed_call_still_counts(self) -> None:
        meter = cost.Meter()
        meter.record_failed_call(role="analyst")
        assert meter.model_calls == 1
        assert meter.calls[0].ok is False

    def test_retries_are_counted_separately_from_calls(self) -> None:
        meter = cost.Meter()
        meter.record_call(role="analyst", attempts=3)
        assert meter.model_calls == 1
        assert meter.retries == 2

    def test_catalogue_and_evidence_are_measured_apart(self) -> None:
        meter = cost.Meter()
        meter.record_prompt(metadata="x" * 4000, evidence="y" * 8000)
        assert meter.metadata_tokens == 1000
        assert meter.evidence_tokens == 2000

    def test_a_repeated_tool_call_is_visible_as_a_repeat(self) -> None:
        meter = cost.Meter()
        meter.record_tool()
        meter.record_tool(repeated=True)
        # The refused repeat is a repeat, not a call: nothing ran.
        assert meter.tool_calls == 1
        assert meter.repeated_tool_calls == 1

    def test_the_product_shape_never_names_a_model(self) -> None:
        # R2 §16: the model behind an answer is not shown in the product.
        meter = cost.Meter()
        meter.record_call(role="analyst", model="some-configured-model-id")
        shown = meter.to_dict()
        assert "models" not in shown
        assert "model" not in shown["calls"][0]
        assert "some-configured-model-id" not in str(shown)

    def test_the_administrator_shape_does_name_it(self) -> None:
        meter = cost.Meter()
        meter.record_call(role="analyst", model="some-configured-model-id")
        shown = meter.to_dict(models=True)
        assert shown["models"] == ["some-configured-model-id"]
        assert shown["calls"][0]["model"] == "some-configured-model-id"


class TestTheAmbientMeter:
    def test_a_call_site_records_without_knowing_who_is_counting(self) -> None:
        with cost.measuring("a question", keep=False) as meter:
            cost.note_result(LLMResult(data={}, model="m", input_tokens=10,
                                       output_tokens=2),
                             purpose="reading", role="router")
        assert meter.model_calls == 1
        assert meter.calls[0].tier == cost.LIGHT

    def test_recording_outside_a_measured_request_is_a_no_op(self) -> None:
        # No exception, no global counter, nothing attributed to a stranger.
        cost.note_result(LLMResult(data={}, model="m"), role="router")
        assert cost.current() is None

    def test_a_nested_measure_is_the_same_question(self) -> None:
        # A question is one unit of cost however many layers it passes
        # through. A second meter would split the total across two rows.
        with cost.measuring("q", keep=False) as outer:
            with cost.measuring("q", keep=False) as inner:
                assert inner is outer


class TestTheCostAvoided:
    def test_a_reproduced_question_is_priced_at_its_own_class(self) -> None:
        # Not at an average over everything: a reproduced catalogue lookup
        # did not avoid the cost of a forensic decomposition.
        trace = cost.Trace()
        cheap = cost.Meter(question_class=cost.CLASS_A)
        cheap.record_call(role="router", input_tokens=100)
        dear = cost.Meter(question_class=cost.CLASS_C)
        dear.record_call(role="analyst", input_tokens=100_000)
        again = cost.Meter(question_class=cost.CLASS_A, reproduced=True)
        for meter in (cheap, dear, again):
            trace.add(meter)
        avoided = trace.summary()["cost_units_avoided"]
        assert avoided == pytest.approx(cheap.cost_units, rel=1e-6)

    def test_nothing_reproduced_avoids_nothing(self) -> None:
        trace = cost.Trace()
        trace.add(cost.Meter(question_class=cost.CLASS_B))
        assert trace.summary()["cost_units_avoided"] == 0.0


# ----------------------------------------------------------- classification


class TestReadingWhichKindOfQuestion:
    @pytest.mark.parametrize("question", [
        "How many data domains are there?",
        "Which datasets are in the liquidity domain?",
        "What does DSCR mean?",
        "Which reporting periods do we hold?",
        "What is the grain of corporate_ifrs9?",
        "How do covenants join to facilities?",
    ])
    def test_a_question_about_the_data_is_class_a(self, question: str) -> None:
        assert classify.read(question).question_class == cost.CLASS_A

    @pytest.mark.parametrize("question", [
        "Show the top 20 borrowers by 12-month PD.",
        "What is total exposure at default by sector?",
        "How many borrowers are in Stage 2?",
        "List the borrowers with a covenant breach this quarter.",
    ])
    def test_a_governed_figure_is_class_a(self, question: str) -> None:
        assert classify.read(question).question_class == cost.CLASS_A

    @pytest.mark.parametrize("question", [
        "Why did Shipping deteriorate this quarter?",
        "Which of those worry you, and why?",
        "Should we move this borrower to Stage 2?",
        "What would you recommend for the group?",
        "Investigate the Real Estate book.",
        "Tell me about CORP-100376.",
    ])
    def test_a_question_asking_for_a_view_is_class_c(self,
                                                    question: str) -> None:
        assert classify.read(question).question_class == cost.CLASS_C

    def test_a_ranking_inside_a_why_question_is_still_a_why_question(
            self) -> None:
        # Order matters: "why are the top 10 the top 10" contains "top 10"
        # and is not a ranking request.
        reading = classify.read("Why are the top 10 borrowers the top 10?")
        assert reading.question_class == cost.CLASS_C

    def test_several_measures_at_once_is_orchestration(self) -> None:
        reading = classify.read(
            "Show exposure, stage and covenant headroom for CORP-100376.")
        assert reading.question_class == cost.CLASS_B

    def test_an_unreadable_question_falls_to_b_not_a(self) -> None:
        # The failure modes are not symmetric: a judgement answered
        # deterministically is a shallow answer to a serious question, and a
        # lookup sent to the analyst is a few thousand tokens.
        assert classify.read("mmm").question_class == cost.CLASS_B
        assert classify.read("").question_class == cost.CLASS_B

    def test_every_reading_says_why(self) -> None:
        for question in ("How many datasets are there?",
                         "Why did Shipping deteriorate?",
                         "Compare Shipping with Oil & Gas.", "mmm"):
            assert classify.read(question).why.strip()


# ------------------------------------------------------------- the budgets


class Counting:
    """A provider that answers immediately and counts how often it is asked."""

    name = "test"
    model = "counting"
    configured = True

    def __init__(self, script: list[dict[str, Any]] | None = None) -> None:
        self.calls = 0
        self.script = list(script or [])
        self.systems: list[str] = []
        self.prompts: list[str] = []
        self.blocks: list[Any] = []

    def structured(self, *, system: str, prompt: str, schema: Any = None,
                   tool_name: str = "", tool_description: str = "",
                   system_blocks: Any = None, **kwargs: Any) -> LLMResult:
        del schema, tool_name, tool_description, kwargs
        self.calls += 1
        self.systems.append(system)
        self.prompts.append(prompt)
        self.blocks.append(system_blocks)
        if self.script:
            return LLMResult(data=self.script.pop(0), model=self.model)
        return LLMResult(data={"action": "ANSWER", "answer": "Done.",
                               "findings": [], "unavailable": [],
                               "limitations": []},
                         model=self.model)


@pytest.fixture()
def principal() -> Principal:
    return Principal(user_id=1, role="ADMIN")


@pytest.fixture(autouse=True)
def _no_stored_answers() -> Any:
    from backend.analyst import answers

    answers.store().clear()
    yield
    answers.store().clear()


class TestTheBudgetPerQuestionClass:
    """§22. Budgets in calls, asserted against a provider that counts."""

    def test_a_catalogue_question_costs_no_model_call_at_all(
            self, principal: Principal) -> None:
        provider = Counting()
        with cost.measuring("How many data domains are there?",
                            keep=False) as meter:
            payload = route.answer("How many data domains are there?",
                                   principal, provider=provider)
        assert provider.calls == 0, "a catalogue question reached a model"
        assert meter.model_calls == 0
        assert payload["path"] == route.CATALOGUE

    def test_a_governed_figure_costs_no_model_call_in_the_analyst(
            self, principal: Principal) -> None:
        question = "Show the top 20 borrowers by 12-month PD."
        provider = Counting()
        with cost.measuring(question, keep=False) as meter:
            payload = route.answer(question, principal, provider=provider)
        assert provider.calls == 0
        assert meter.model_calls == 0
        assert payload["path"] == route.DETERMINISTIC

    def test_a_judgement_question_is_allowed_its_investigation(
            self, principal: Principal) -> None:
        question = "Why did Shipping deteriorate this quarter?"
        provider = Counting()
        with cost.measuring(question, question_class=cost.CLASS_C,
                            keep=False) as meter:
            route.answer(question, principal, provider=provider)
        assert provider.calls >= 1
        assert meter.model_calls == provider.calls

    def test_the_same_question_twice_costs_nothing_the_second_time(
            self, principal: Principal) -> None:
        question = "Why did Shipping deteriorate this quarter?"
        first = Counting()
        with cost.measuring(question, keep=False):
            route.answer(question, principal, provider=first)
        second = Counting()
        with cost.measuring(question, keep=False) as meter:
            payload = route.answer(question, principal, provider=second)
        assert second.calls == 0, "the run-key store did not serve it"
        assert meter.model_calls == 0
        assert payload["reproduced"] is True


class TestTheBoundedLoop:
    """§18. The loop is a control, not a hope."""

    def test_normal_tool_planning_stops_after_four_loops(self) -> None:
        from backend.analyst import safety

        assert safety.MAX_PLANNING_TURNS == 4
        assert safety.MAX_TURNS == safety.MAX_PLANNING_TURNS + 1

    def test_the_same_query_is_not_run_twice(self,
                                             principal: Principal) -> None:
        same = {"action": "CALL_TOOL", "tool": "list_datasets",
                "arguments": {}, "why": "look"}
        provider = Counting([dict(same), dict(same), dict(same)])
        with cost.measuring("q", keep=False) as meter:
            found = session.investigate("q", principal, provider=provider,
                                        meter=meter)
        assert meter.tool_calls == 1, "the identical call was run again"
        assert meter.repeated_tool_calls == 2
        refusals = [o for o in found.ledger.observations if o.refused]
        assert refusals, "the loop was not told why it got nothing new"
        assert "already been made" in refusals[0].refused

    def test_the_same_arguments_in_a_different_order_are_the_same_query(
            self, principal: Principal) -> None:
        first = {"action": "CALL_TOOL", "tool": "describe_dataset",
                 "arguments": {"dataset": "corporate_ifrs9", "period": "Q2-2026"},
                 "why": "look"}
        second = {"action": "CALL_TOOL", "tool": "describe_dataset",
                  "arguments": {"period": "Q2-2026", "dataset": "corporate_ifrs9"},
                  "why": "look again"}
        provider = Counting([first, second])
        with cost.measuring("q", keep=False) as meter:
            session.investigate("q", principal, provider=provider, meter=meter)
        assert meter.repeated_tool_calls == 1


class TestThePromptShape:
    """§17 and §21. What is sent, and how often."""

    def test_the_rules_and_the_catalogue_are_sent_as_a_cacheable_prefix(
            self, principal: Principal) -> None:
        provider = Counting()
        session.investigate("q", principal, provider=provider)
        blocks = provider.blocks[0]
        assert blocks, "no cache breakpoint was offered to the provider"
        assert any(b.get("cache_control") for b in blocks), \
            "the stable prefix carries no cache breakpoint"

    def test_the_catalogue_is_not_repeated_in_the_varying_prompt(
            self, principal: Principal) -> None:
        provider = Counting()
        session.investigate("q", principal, provider=provider)
        assert "GOVERNED TOOLS" not in provider.prompts[0], \
            "the catalogue is in the user prompt, where no cache reaches it"

    def test_older_evidence_is_summarised_rather_than_re_sent_whole(
            self) -> None:
        from backend.analyst.evidence import Ledger, Observation

        ledger = Ledger()
        for index in range(4):
            ledger.add(Observation(
                tool=f"tool_{index}", total_rows=40,
                rows=[{"borrower": f"CORP-{n}", "ead": n * 1.5}
                      for n in range(40)]))
        text = session._evidence(ledger)
        # The two most recent keep all their rows; the older two are trimmed.
        assert text.count("CORP-39") == 2
        assert "more row(s) not shown" in text

    def test_the_whole_ledger_is_still_evidence_for_grounding(self) -> None:
        # Only the RENDERING is compressed. A figure from a trimmed row is
        # still grounded, or the compression would have removed an answer's
        # right to say it.
        from backend.analyst.evidence import Ledger, Observation

        ledger = Ledger()
        ledger.add(Observation(tool="a", total_rows=40,
                               rows=[{"ead": n * 1.0} for n in range(40)]))
        ledger.add(Observation(tool="b", total_rows=1, rows=[{"ead": 1.0}]))
        ledger.add(Observation(tool="c", total_rows=1, rows=[{"ead": 2.0}]))
        assert 39.0 in ledger.numbers()
        assert "39" not in session._evidence(ledger)
