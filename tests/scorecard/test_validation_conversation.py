"""Reading a validator's question. §21.

The claim under test throughout this file is one sentence: **a language model
may decide which question to answer, and never what the answer is.** Every
test below is that sentence from a different angle — the deterministic reader
resolving questions with no provider at all, the guardrail refusing a
model's invented tool call, and the refusals that happen before a provider is
consulted rather than by asking one to decline.
"""

from __future__ import annotations

import pytest

from backend.scorecard.validation import agent
from backend.scorecard.validation import conversation as reader
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry


class TestWhichScorecard:
    def test_each_of_the_three_is_named_by_its_own_words(self):
        assert reader.which_scorecard(
            "the Saudi SME scorecard") == "sme_champion"
        assert reader.which_scorecard(
            "the retail application scorecard"
        ) == "retail_application_champion"
        assert reader.which_scorecard(
            "the retail behaviour scorecard"
        ) == "retail_behaviour_champion"

    def test_behaviour_is_not_read_as_application(self):
        """Both names begin "retail".

        Matching the shorter phrase first resolves every behavioural question
        to the application scorecard, and the answer looks entirely
        plausible - a number, from a scorecard, about retail.
        """
        assert reader.which_scorecard(
            "retail behavioural scorecard PSI"
        ) == "retail_behaviour_champion"
        assert reader.which_scorecard(
            "retail behavioral scorecard PSI"
        ) == "retail_behaviour_champion"

    def test_a_question_naming_none_of_them_resolves_to_nothing(self):
        assert reader.which_scorecard("what is the AUC?") == ""


class TestWhichTest:
    def test_an_explicit_id_wins(self):
        assert reader.which_test("run STAB-CSI please") == "STAB-CSI"

    def test_an_explicit_id_beats_a_synonym_in_the_same_sentence(self):
        """Somebody who typed an id meant that id.

        "The PSI is fine but run STAB-CSI" names two tests and only one of
        them is an instruction.
        """
        assert reader.which_test(
            "the PSI looks fine but run STAB-CSI") == "STAB-CSI"

    @pytest.mark.parametrize("phrase,expected", [
        ("what is the AUC", "DISC-AUC"),
        ("the Gini", "DISC-GINI"),
        ("KS statistic", "DISC-KS"),
        ("information value", "VAR-IV"),
        ("weight of evidence", "VAR-WOE"),
        ("the bootstrap interval", "ROB-BOOTSTRAP"),
        ("observed over expected", "CAL-OE"),
        ("population stability", "STAB-PSI"),
    ])
    def test_the_words_a_validator_types(self, phrase, expected):
        assert reader.which_test(phrase) == expected

    def test_a_statistic_name_inside_a_word_is_not_a_match(self):
        """`iv` is inside "arrive", "give", "derivative".

        A substring test is how a question about a derivative resolves to the
        information value, and the answer carries a number.
        """
        assert reader.which_test("when did the file arrive") == ""
        assert reader.which_test("the derivative book") == ""

    def test_every_registered_test_id_resolves_to_itself(self):
        for test in test_registry.TESTS:
            assert reader.which_test(
                f"run {test.test_id}") == test.test_id


class TestWhichCategory:
    @pytest.mark.parametrize("phrase,expected", [
        ("is it still discriminating", test_registry.DISCRIMINATION),
        ("still ranking risk", test_registry.DISCRIMINATION),
        ("is the calibration right", test_registry.CALIBRATION),
        ("has the population drifted", test_registry.STABILITY),
        ("how robust is this", test_registry.ROBUSTNESS),
        ("which characteristics still work", test_registry.VARIABLES),
        ("does it hold by segment", test_registry.SEGMENTATION),
        ("is the challenger better", test_registry.CHAMPION_CHALLENGER),
    ])
    def test_the_question_a_validator_actually_asks(self, phrase, expected):
        assert reader.which_category(phrase) == expected

    def test_every_category_key_resolves_to_itself(self):
        for category in test_registry.CATEGORIES:
            assert reader.which_category(
                f"run the {category.replace('_', ' ')} tests") == category


class TestTheScreenFillsTheGap:
    def test_a_question_without_a_scorecard_uses_the_one_on_screen(self):
        """A validator looking at the SME scorecard means the SME scorecard.

        Asking "which scorecard?" of somebody who is looking at one is
        pedantry, and pedantry is what gets a conversational surface
        abandoned.
        """
        found = reader.read("what is the AUC?", model_id="sme_champion")
        assert found is not None
        assert found.parameters["model_id"] == "sme_champion"

    def test_the_words_on_the_page_override_the_screen(self):
        """What the person typed beats what they were looking at."""
        found = reader.read("what is the SME AUC?",
                            model_id="retail_application_champion")
        assert found is not None
        assert found.parameters["model_id"] == "sme_champion"


class TestExplainRatherThanRun:
    def test_asking_what_a_test_measures_does_not_run_it(self):
        """A definition question answered by a minute of computation.

        Worse than slow: it attaches a number to a question that did not ask
        for one, and the number is what gets quoted.
        """
        found = reader.read("what does STAB-CSI measure?")
        assert found is not None
        assert found.tool_id == agent.EXPLAIN_TEST
        assert found.parameters == {"test_id": "STAB-CSI"}

    def test_asking_for_the_value_does_run_it(self):
        found = reader.read("what is the STAB-CSI?", model_id="sme_champion")
        assert found is not None
        assert found.tool_id == agent.RUN_TEST


class TestANamedTestWins:
    """A question that names a test is about that test.

    "What is the worst CSI?" resolved to the findings engine, because it
    contains the word "worst" — an answer about eight tests to a question
    about one, and nothing on the way told the reader that had happened.
    """

    @pytest.mark.parametrize("question,expected", [
        ("What is the worst CSI?", "STAB-CSI"),
        ("Which characteristic has the worst information value?", "VAR-IV"),
        ("Is the AUC a concern?", "DISC-AUC"),
    ])
    def test_a_keyword_does_not_beat_a_named_test(self, question, expected):
        found = reader.read(question, model_id="sme_champion")
        assert found is not None
        assert found.tool_id == agent.RUN_TEST
        assert found.parameters["test_id"] == expected

    def test_a_question_naming_no_test_still_reaches_the_findings(self):
        found = reader.read("What are the biggest weaknesses?",
                            model_id="sme_champion")
        assert found is not None
        assert found.tool_id == agent.FINDINGS


class TestTheRefusalShapeIsOne:
    """Two refusals with the same key meaning different things.

    `refused` was a boolean in one path and a sentence in the other. The
    client rendered it directly, so a validator asking for raw rows was shown
    the word "true".
    """

    @pytest.mark.parametrize("question", [
        "run some SQL over the population",
        "what is the IFRS 9 stage distribution",
    ])
    def test_refused_is_always_a_flag(self, question):
        refusal = reader.answer(question)["refusal"]
        assert refusal["refused"] is True
        assert isinstance(refusal.get("why", ""), str)
        assert refusal["scope"]

    def test_what_was_refused_has_its_own_field(self):
        refusal = reader.answer("give me the raw rows")["refusal"]
        assert refusal["what"] == "raw rows"


class TestTheRefusals:
    @pytest.mark.parametrize("question", [
        "run some SQL over the scorecard population",
        "write me python to compute the AUC",
        "give me the raw rows for the failing segment",
        "change the limit on DISC-AUC to 0.60",
        "sign off this model",
    ])
    def test_what_this_module_will_not_do(self, question):
        """Refused before a provider is asked.

        A refusal that depends on a model declining is not a refusal — it is
        a request that usually gets turned down.
        """
        assert reader.refuses(question)
        body = reader.answer(question)
        assert body["answered"] is False
        assert "refusal" in body

    @pytest.mark.parametrize("question", [
        "what is the IFRS 9 stage distribution",
        "which borrowers breached a covenant",
        "show me the corporate exposure network",
        "what is the ECL coverage",
    ])
    def test_another_surface_s_question_is_not_answered_here(self, question):
        assert reader.out_of_domain(question) is True
        body = reader.answer(question)
        assert body["answered"] is False
        assert "refusal" in body

    def test_a_scorecard_question_that_mentions_another_domain_is_not_refused(
            self):
        """"The SME scorecard's IFRS 9 treatment" is a scorecard question.

        Refusing on the presence of a word from another domain would refuse
        half of what a validator asks. The domain gate belongs to the data
        layer; this one only decides which surface the question is for.
        """
        assert reader.out_of_domain(
            "does the SME scorecard's default definition match IFRS 9?"
        ) is False


class TestTheGuardrailOnTheModel:
    def test_an_invented_tool_is_refused(self):
        assert reader._accept({
            "tool_id": "scv_run_sql", "in_scope": True, "because": ""}) is None

    def test_an_invented_test_id_is_refused(self):
        assert reader._accept({
            "tool_id": agent.RUN_TEST, "model_id": "sme_champion",
            "test_id": "DISC-SHARPE", "in_scope": True,
            "because": ""}) is None

    def test_an_invented_category_is_refused(self):
        assert reader._accept({
            "tool_id": agent.RUN_CATEGORY, "model_id": "sme_champion",
            "category": "profitability", "in_scope": True,
            "because": ""}) is None

    def test_a_scorecard_outside_the_three_is_refused(self):
        assert reader._accept({
            "tool_id": agent.PERIODS, "model_id": "corporate_pd_model",
            "in_scope": True, "because": ""}) is None

    def test_out_of_scope_is_honoured(self):
        assert reader._accept({
            "tool_id": agent.LIST_MODELS, "in_scope": False,
            "because": ""}) is None

    def test_a_valid_choice_is_accepted_and_says_where_it_came_from(self):
        accepted = reader._accept({
            "tool_id": agent.RUN_TEST, "model_id": "sme_champion",
            "test_id": "DISC-AUC", "in_scope": True,
            "because": "the question asks about discrimination"})
        assert accepted is not None
        assert accepted.tool_id == agent.RUN_TEST
        assert accepted.parameters == {"model_id": "sme_champion",
                                       "test_id": "DISC-AUC"}
        assert accepted.source == reader.MODEL_CHOSEN

    def test_a_parameter_the_tool_does_not_take_is_dropped_not_passed(self):
        """`agent._check` refuses the whole call on an unknown parameter.

        Passing one through would turn a question the reader could answer into
        a refusal, on the strength of a field the model added and nobody
        asked for.
        """
        accepted = reader._accept({
            "tool_id": agent.PERIODS, "model_id": "sme_champion",
            "category": "discrimination", "in_scope": True, "because": ""})
        assert accepted is not None
        assert "category" not in accepted.parameters


class TestTheDeterministicReaderComesFirst:
    def test_a_resolvable_question_never_reaches_a_provider(self, monkeypatch):
        """A configured provider must not change what a clear question means.

        If it could, the same question would resolve differently on two
        deployments, and a validation module whose answers depend on whether
        an API key is present is not one anybody can rely on.
        """
        def explode(*_: object, **__: object):
            raise AssertionError("the provider was consulted")

        monkeypatch.setattr("backend.llm.get_provider", explode)
        found = reader.choose("what is the AUC?", model_id="sme_champion")
        assert found is not None
        assert found.source == reader.DETERMINISTIC


class TestTheAnswer:
    def test_an_answered_question_carries_a_computed_result(self):
        body = reader.answer("what does DISC-AUC measure?")
        assert body["answered"] is True
        assert "result" in body
        assert body["reading"]["tool_id"] == agent.EXPLAIN_TEST

    def test_every_answer_says_where_its_figures_came_from(self):
        for question in ("what does DISC-AUC measure?",
                         "what is the IFRS 9 stage distribution"):
            assert "language model" in reader.answer(question)["figures"]

    def test_an_under_specified_question_is_clarified_not_refused(self):
        """Vague is not out of scope, and the two need different answers.

        Refusing "how is the SME scorecard doing?" tells a validator their
        question was about the wrong thing. It was about the right thing, too
        generally, and the answer is the eleven questions a validation asks.
        """
        body = reader.answer("how is the SME scorecard doing?",
                             model_id="sme_champion")
        assert body["answered"] is False
        assert "clarification" in body
        assert "refusal" not in body
        assert len(body["clarification"]["options"]) == len(
            test_registry.CATEGORIES)

    def test_which_scorecard_is_asked_when_none_is_known(self):
        """`scv_periods` needs a model id and the question named none."""
        body = reader.answer("which periods have matured?")
        assert body["answered"] is False
        assert body["clarification"]["question"] == "Which scorecard?"
        assert len(body["clarification"]["options"]) == len(
            model_registry.all_models())

    def test_the_shape_is_the_same_whatever_happened(self):
        for question, screen in [
            ("what does DISC-AUC measure?", ""),
            ("what is the ECL coverage", ""),
            ("run some SQL", ""),
            ("how is it doing?", "sme_champion"),
        ]:
            body = reader.answer(question, model_id=screen)
            assert set(body) >= {"conversation_version", "question",
                                 "answered", "figures", "scope"}
            assert isinstance(body["answered"], bool)
