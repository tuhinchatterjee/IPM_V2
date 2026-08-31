"""
The planner and the wall in front of it.

These tests exist for one reason: the planner is the only component that reads
free text, and the validator is the only thing standing between what it produced
and the engine. If either drifts, CreditProbe can answer a question it did not
understand, or run something nobody registered.
"""

from __future__ import annotations

import pytest

from backend.engine.registry import get_registry
from backend.orchestration.planner import DemoPlanner, get_planner, planner_mode
from backend.orchestration.schema import MAX_PLAN_STEPS, AnalysisPlan, PlanRejected, PlanStep
from backend.orchestration.validator import validate_plan, validate_step
from backend.orchestration.vocabulary import get_vocabulary


@pytest.fixture(scope="module")
def vocab():
    return get_vocabulary()


@pytest.fixture(scope="module")
def planner():
    return DemoPlanner()


# The questions the demonstration is built around. Each names the analysis that
# must appear in the plan for the answer to be the right one.
DEMO_QUESTIONS = [
    # "What deteriorated?" asks what moved, not what the book looks like — so the
    # plan leads with a movement analysis rather than the portfolio position.
    ("What deteriorated this period?", "stage_migration"),
    ("Why has Stage 2 increased?", "stage_migration"),
    ("Which sectors deteriorated the most?", "ecl_movement"),
    ("Show me the rating transition matrix.", "rating_transition_matrix"),
    ("Show me the top ten deteriorating borrowers.", "top_deteriorating_borrowers"),
    ("Stress the Real Estate portfolio.", "stress_scenario_basic"),
    ("How has ECL changed?", "ecl_movement"),
]


@pytest.mark.parametrize("question,expected", DEMO_QUESTIONS)
def test_demo_planner_selects_the_right_analysis(planner, vocab, question, expected):
    plan = planner.plan(question, vocab)
    assert not plan.unmatched, f"{question!r} was not recognised"
    assert expected in [s.analysis_id for s in plan.steps]
    assert plan.intent


@pytest.mark.parametrize("question,_expected", DEMO_QUESTIONS)
def test_every_demo_plan_passes_the_validator(planner, vocab, question, _expected):
    validate_plan(planner.plan(question, vocab), vocab)


def test_a_sector_named_in_the_question_is_resolved_against_real_data(planner, vocab):
    plan = planner.plan("Stress the Real Estate portfolio.", vocab)
    stress = next(s for s in plan.steps if s.analysis_id == "stress_scenario_basic")
    assert stress.params.get("sector") == "Real Estate"
    assert "Real Estate" in vocab.dimensions["sector"]


@pytest.mark.parametrize("question,expected", DEMO_QUESTIONS)
def test_exactly_one_step_answers_the_question(planner, vocab, question, expected):
    """Question-scoped planning: one PRIMARY analysis, and it is the right one."""
    plan = planner.plan(question, vocab)
    primaries = [s for s in plan.steps if s.is_primary]
    assert len(primaries) == 1
    assert primaries[0].analysis_id == expected
    assert plan.primary is primaries[0]


def test_a_narrow_question_does_not_return_a_general_briefing(planner, vocab):
    """"Which sectors deteriorated?" is a ranking, not a portfolio review."""
    plan = planner.plan("Which sectors deteriorated the most?", vocab)
    assert [s.analysis_id for s in plan.steps] == ["ecl_movement"]
    assert plan.scope.focus == "sector deterioration"
    assert plan.scope.dimension == "sector"


def test_a_period_chosen_by_the_user_overrides_the_wording(planner, vocab):
    plan = planner.plan("How has ECL changed?", vocab, period=("Q1 2025", "Q1 2026"))
    assert plan.scope.period_specified is True
    assert (plan.scope.from_period, plan.scope.to_period) == ("Q1 2025", "Q1 2026")
    primary = plan.primary
    assert primary.params.get("from_period") == "Q1 2025"
    assert primary.params.get("to_period") == "Q1 2026"


def test_a_stage_mentioned_in_a_question_is_not_read_as_a_filter(planner, vocab):
    """"Why has Stage 2 increased?" asks *about* Stage 2 — it does not ask for
    every other stage to be discarded before answering."""
    plan = planner.plan("Why has Stage 2 increased?", vocab)
    assert all("ifrs9_stage" not in s.filters for s in plan.steps)


def test_an_unrecognised_question_is_reported_rather_than_guessed(planner, vocab):
    plan = planner.plan("What is the weather in Dubai?", vocab)
    assert plan.unmatched
    assert plan.notes and "did not recognise" in plan.notes[0]
    # It still runs something useful, and every step is still a real analysis.
    assert plan.steps
    validate_plan(plan, vocab)


def test_plans_never_exceed_the_step_limit(planner, vocab):
    for question, _ in DEMO_QUESTIONS:
        assert len(planner.plan(question, vocab).steps) <= MAX_PLAN_STEPS


# ------------------------------------------------------------- the validator


def _plan(step: PlanStep) -> AnalysisPlan:
    return AnalysisPlan(question="q", intent="i", steps=[step])


def test_an_unregistered_analysis_is_refused(vocab):
    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(_plan(PlanStep("calculate_ecl_directly")), vocab)
    assert "not a registered CreditProbe analysis" in str(excinfo.value)


def test_an_unknown_parameter_is_refused(vocab):
    problems = validate_step(
        PlanStep("portfolio_summary", params={"drop_table": "facilities"}), vocab
    )
    assert problems and "does not accept" in problems[0]


def test_a_parameter_outside_its_allowed_values_is_refused(vocab):
    problems = validate_step(
        PlanStep("stage_migration", params={"basis": "vibes"}), vocab
    )
    assert problems and "must be one of" in problems[0]


def test_a_period_the_bank_has_no_data_for_is_refused(vocab):
    problems = validate_step(PlanStep("portfolio_summary", params={"period": "Q9 2099"}), vocab)
    assert problems and "not a reporting period" in problems[0]


def test_period_aliases_are_accepted(vocab):
    assert validate_step(PlanStep("portfolio_summary", params={"period": "latest"}), vocab) == []


def test_an_ungoverned_filter_dimension_is_refused(vocab):
    problems = validate_step(
        PlanStep("portfolio_summary", filters={"account_id": "ACC000001"}), vocab
    )
    assert problems and "not a dimension CreditProbe allows filtering on" in problems[0]


def test_a_filter_value_absent_from_the_data_is_refused(vocab):
    problems = validate_step(
        PlanStep("portfolio_summary", filters={"sector": "Interstellar Freight"}), vocab
    )
    assert problems and "not present in the governed data" in problems[0]


def test_an_empty_plan_is_refused(vocab):
    with pytest.raises(PlanRejected):
        validate_plan(AnalysisPlan(question="q", intent="i", steps=[]), vocab)


def test_a_plan_longer_than_the_limit_is_refused(vocab):
    steps = [PlanStep("portfolio_summary") for _ in range(MAX_PLAN_STEPS + 1)]
    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(AnalysisPlan(question="q", intent="i", steps=steps), vocab)
    assert "runs at most" in str(excinfo.value)


def test_every_analysis_the_planner_can_name_is_runnable(planner, vocab):
    runnable = {a.contract.id for a in get_registry().runnable()}
    for question, _ in DEMO_QUESTIONS:
        for step in planner.plan(question, vocab).steps:
            assert step.analysis_id in runnable


# ------------------------------------------------------------- planner choice


def test_the_planner_is_chosen_by_whether_a_key_is_configured(monkeypatch):
    from dataclasses import replace

    import backend.orchestration.planner as planner_module
    from backend.config import settings

    monkeypatch.setattr(planner_module, "settings", replace(settings, anthropic_api_key=""))
    assert isinstance(get_planner(), DemoPlanner)
    assert planner_mode()["mode"] == "demo"

    monkeypatch.setattr(
        planner_module, "settings", replace(settings, anthropic_api_key="sk-ant-not-real")
    )
    assert planner_mode()["mode"] == "model"


# ---------------------------------------------------------------------------
# Two values of one dimension. §8.
# ---------------------------------------------------------------------------


class TestATransitionIsNotAConjunction:
    """"Migrate from Stage 1 to Stage 2" resolved BOTH stages as filters.

    They were emitted as a conjunction on the same rows, so no row could
    satisfy the plan. The engine ran, the post-result invariant correctly
    observed that the rows did not match the filters the question was recorded
    as carrying, and the presenter was shown "CreditProbe could not complete
    that request" for a governed IFRS 9 question the catalogue can answer. It
    is one of the six questions in the acceptance run.
    """

    @staticmethod
    def _reading(objective: str):
        from backend.orchestration.capability import Reading

        return Reading(intent="ANALYSIS", objective=objective,
                       entities=({"kind": "ifrs9_stage", "value": "1"},
                                 {"kind": "ifrs9_stage", "value": "2"}))

    @staticmethod
    def _context():
        from backend.orchestration import context as ctx_mod

        return ctx_mod.retrieve("What is total exposure by IFRS 9 stage?")

    def test_the_destination_survives_and_the_origin_does_not(self):
        from backend.orchestration import analysis_planner as ap

        question = ("Which borrowers are most likely to migrate from IFRS 9 "
                    "Stage 1 to Stage 2?")
        got = ap._filters(self._reading(question), self._context(), question)
        assert got == [("ifrs9_stage", "2")], (
            "a transition must leave one filter - the destination")

    def test_a_set_of_two_stages_is_left_exactly_as_resolved(self):
        """The fix must not have become "always drop all but the last".

        "Stage 2 and Stage 3 exposure" names two values of one dimension and
        is not a movement; both belong, and the layer below decides whether it
        can express the disjunction. Narrowing it here would silently answer
        about Stage 3 alone.
        """
        from backend.orchestration import analysis_planner as ap

        question = "Show Stage 2 and Stage 3 exposure at Q2 2026."
        got = ap._filters(self._reading(question), self._context(), question)
        assert got == [("ifrs9_stage", "1"), ("ifrs9_stage", "2")], (
            "a set was narrowed as though it were a transition")

    def test_one_value_of_one_dimension_is_untouched(self):
        from backend.orchestration import analysis_planner as ap
        from backend.orchestration.capability import Reading

        reading = Reading(intent="ANALYSIS",
                          objective="Which borrowers are in Stage 2?",
                          entities=({"kind": "ifrs9_stage", "value": "2"},))
        got = ap._filters(reading, self._context(),
                          "Which borrowers moved into Stage 2 from elsewhere?")
        assert got == [("ifrs9_stage", "2")]

    def test_dropping_the_origin_is_declared_not_silent(self):
        """The substitution must reach the answer, not only the log.

        Reporting who is AT Stage 2 in place of who MOVED to Stage 2 is a
        near-miss: it includes every borrower that was already there. That is
        an acceptable answer only if the answer says so.
        """
        from backend.orchestration import analysis_planner as ap

        question = "Which borrowers moved from Stage 1 to Stage 2?"
        notes: list[str] = []
        ap._filters(self._reading(question), self._context(), question, notes)
        assert notes, "the narrowing was performed without stating it"
        said = " ".join(notes)
        assert "IFRS 9 stage 1" in said and "IFRS 9 stage 2" in said, (
            f"the caveat does not name both endpoints: {said!r}")
        assert "ifrs9_stage" not in said, (
            f"the caveat shows a column name to a credit officer: {said!r}")

    def test_a_set_produces_no_caveat_because_nothing_was_dropped(self):
        from backend.orchestration import analysis_planner as ap

        notes: list[str] = []
        question = "Show Stage 2 and Stage 3 exposure at Q2 2026."
        ap._filters(self._reading(question), self._context(), question, notes)
        assert not notes, f"a caveat was invented for an untouched plan: {notes}"


# ---------------------------------------------------------------------------
# "the 10 borrowers with the highest probability of credit deterioration
# over the next 12 months" - one of §17's six, and four defects deep. §3.
# ---------------------------------------------------------------------------


class TestTheDeteriorationRanking:
    """The acceptance run asked this and got a clarification.

    Underneath it were four separate failures, each of which alone produces a
    confidently wrong answer to a question the catalogue can answer:

      1. The phrase named no governed measure, so the planner refused and
         listed four concepts that do not include the one being described.
      2. Once it resolved, "the 10 borrowers with the highest X" was not read
         as a count, because the count and the superlative are not adjacent.
      3. "deterioration" - the word that made the measure resolve - was read a
         SECOND time as an assertion that the measure had deteriorated, so a
         ranking became a cohort of everyone whose PD rose.
      4. The same word made the question a two-period comparison, so the
         answer compared the portfolio's PD across two historical quarters
         and contained no borrower list at all.

    Each is pinned separately, because a fix for one that quietly undoes
    another would otherwise pass.
    """

    QUESTION = ("Identify the 10 borrowers with the highest probability of "
                "credit deterioration over the next 12 months. For each "
                "borrower, explain the top five drivers.")

    def test_the_phrase_resolves_to_the_twelve_month_pd(self):
        """A forward-looking likelihood of a credit outcome over twelve
        months IS the twelve-month PD. Understanding only "12-month PD" is a
        vocabulary gap, not a governed limit."""
        import re

        from backend.orchestration.concepts import CONCEPTS

        found = {c.id for c in CONCEPTS if re.search(c.pattern, self.QUESTION,
                                                     re.IGNORECASE)}
        assert "pd_12m" in found, found

    def test_a_past_deterioration_does_not_resolve_to_pd(self):
        """So the vocabulary addition cannot pass by matching everything.

        "Which borrowers deteriorated?" is a movement question about what has
        already happened. Resolving it to a forward-looking probability would
        answer a different question with confidence.
        """
        import re

        from backend.orchestration.concepts import CONCEPTS

        found = {c.id for c in CONCEPTS
                 if re.search(c.pattern,
                              "Which borrowers deteriorated last quarter?",
                              re.IGNORECASE)}
        assert "pd_12m" not in found, found

    def test_ten_borrowers_is_a_count_of_ten(self):
        from backend.orchestration.analysis_planner import _explicit_top_n

        assert _explicit_top_n(self.QUESTION) == 10, (
            "the population was sized by the 'top five drivers' in the second "
            "sentence rather than by the ten borrowers in the first")

    def test_a_count_is_not_read_across_a_conjunction(self):
        from backend.orchestration.analysis_planner import _explicit_top_n

        assert _explicit_top_n(
            "Show 3 sectors and the highest rated borrowers.") == 0

    def test_the_measures_own_name_is_not_also_its_movement(self):
        from backend.orchestration.semantics import movement_near

        assert movement_near(self.QUESTION,
                             "probability of credit deterioration") is None

    def test_a_movement_outside_the_phrase_is_still_read(self):
        """The mask must not have switched movement detection off."""
        from backend.orchestration.semantics import movement_near

        assert movement_near(
            "borrowers whose ECL deteriorated this quarter", "ECL") is not None

    def test_a_forward_looking_question_is_not_a_two_period_comparison(self):
        from backend.orchestration.router import _period_requirement

        assert _period_requirement(self.QUESTION, "ANALYSIS") == "point_in_time"

    def test_a_retrospective_question_still_is(self):
        from backend.orchestration.router import _period_requirement

        for question in ("Which borrowers deteriorated between Q1 2026 and "
                         "Q2 2026?",
                         "How has ECL changed over the last four quarters?",
                         "PD rose last quarter; who is most likely to "
                         "deteriorate over the next 12 months?"):
            assert _period_requirement(question, "ANALYSIS") == "two_period", (
                question)


class TestSayingWhatCouldNotBeComputed:
    """§3: "return the supported part and state specifically what cannot be
    computed. Do not throw the entire question away."

    The first half already worked, and that was the problem. Asked to weigh
    cash balances, working-capital movements, short-term debt maturities and
    utilisation together, CreditProbe composed on the one of the four the
    catalogue carries and said so about none of them - so a reader saw a
    utilisation figure under a heading about liquidity stress with nothing on
    screen telling them three quarters of the question had gone missing.
    """

    @staticmethod
    def _notes(question, labels):
        from backend.orchestration import analysis_planner as ap

        class _C:
            def __init__(self, label): self.label = label

        class _M:
            def __init__(self, label): self.concept, self.phrase = _C(label), label

        notes: list[str] = []
        ap._note_unresolved_dimensions(question, [_M(x) for x in labels], notes)
        return notes

    QUESTION = ("Which borrowers have the strongest evidence of liquidity "
                "stress? Consider cash balances, working-capital movements, "
                "short-term debt maturities and facility utilisation "
                "together.")

    def test_the_dimensions_with_no_governed_measure_are_named(self):
        notes = self._notes(self.QUESTION, ["utilisation"])
        assert notes, "the answer was composed on one of four and said nothing"
        said = notes[0].lower()
        for missing in ("cash balance", "working-capital", "short-term debt"):
            assert missing in said, f"{missing!r} was dropped silently: {said}"

    def test_what_it_did_use_is_named_too(self):
        """A limitation with no statement of what WAS used is half an answer."""
        assert "utilisation" in self._notes(self.QUESTION, ["utilisation"])[0]

    def test_nothing_is_said_where_every_dimension_resolved(self):
        notes = self._notes(
            "Rank borrowers by EAD, considering ECL and utilisation together.",
            ["exposure at default", "expected credit loss", "utilisation"])
        assert not notes, f"invented a limitation that does not exist: {notes}"

    def test_a_question_that_enumerates_nothing_gets_no_note(self):
        assert not self._notes("What is total exposure by sector?", ["exposure"])

    def test_a_question_where_nothing_resolved_gets_no_note(self):
        """That is a clarification, which is a better response than a list of
        things the catalogue does not have."""
        assert not self._notes(self.QUESTION, [])


class TestAnExplanationClauseDoesNotSetTheGrain:
    """§17's "explanation dimensions", and the last of Q1's defects.

    "…Identify the 10 borrowers … For each borrower, explain the top five
    drivers, distinguish borrower-specific drivers from macroeconomic
    drivers, and rank the evidence by materiality."

    "macroeconomic" resolves to a governed macro concept published at
    PORTFOLIO grain. It arrived from the third clause - a request to separate
    two KINDS of driver in the EXPLANATION - and then set the grain of the
    whole answer, so a question asking for ten borrowers was refused with "the
    governed data behind it can only be reported as one row for the whole
    portfolio". The population clause never mentioned macro at all.
    """

    QUESTION = ("Identify the 10 borrowers with the highest probability of "
                "credit deterioration over the next 12 months. For each "
                "borrower, explain the top five drivers, distinguish "
                "borrower-specific drivers from macroeconomic drivers, and "
                "rank the evidence by materiality.")

    @staticmethod
    def _labels(question, phrases):
        from backend.orchestration import analysis_planner as ap

        class _C:
            def __init__(self, label): self.label = label

        class _M:
            def __init__(self, p): self.concept, self.phrase = _C(p), p

        return [m.phrase for m in
                ap._drop_explanation_only(question, [_M(p) for p in phrases])]

    def test_a_concept_named_only_in_the_explanation_is_dropped(self):
        kept = self._labels(
            self.QUESTION,
            ["probability of credit deterioration", "macroeconomic"])
        assert kept == ["probability of credit deterioration"], kept

    def test_the_measure_in_the_population_clause_survives(self):
        assert "probability of credit deterioration" in self._labels(
            self.QUESTION, ["probability of credit deterioration",
                            "macroeconomic"])

    def test_a_single_measure_is_never_dropped(self):
        """"Rank those by ECL instead" names its only measure inside a ranking
        clause. Removing it would leave nothing to compute."""
        assert self._labels("Rank those by ECL instead.", ["ECL"]) == ["ECL"]

    def test_a_measure_named_only_after_the_opening_survives_when_alone(self):
        kept = self._labels(
            "Show the customers we discussed. Rank them by ECL.", ["ECL"])
        assert kept == ["ECL"], kept

    def test_a_single_clause_question_is_untouched(self):
        kept = self._labels(
            "Show EAD and ECL by sector at Q2 2026.", ["EAD", "ECL"])
        assert kept == ["EAD", "ECL"], kept
