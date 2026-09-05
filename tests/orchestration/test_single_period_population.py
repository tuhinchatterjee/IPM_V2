"""A condition is not a comparison — Phase 0A remainder.

The planner read ANY condition as a cohort, and every cohort is built from two
periods: an opening scan, a closing scan, a join, and a DERIVE of the
movements. So

    "Which Stage 2 or worse borrowers are on watchlist?"

which compares nothing across two dates, was planned with an empty DERIVE that
the governed runtime refused, and the reader got a validator message where the
answer belonged. Its neighbours failed differently and for the same reason:
"Show Stage 2 borrowers" was asked which figure to measure, of a sentence whose
head noun already said what the answer has one row of.

These tests hold the DECISION shut, not the sentences. Each names the mechanism
it protects.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_catalog
from backend.orchestration import analysis_planner as ap
from backend.orchestration import dimensions as dm
from backend.orchestration import ordinal
from backend.orchestration import predicates as pr
from backend.orchestration.context import retrieve
from backend.orchestration.dynamic import Condition
from backend.orchestration.router import read_request_offline
from backend.orchestration.vocabulary import get_vocabulary

SINGLE_PERIOD = [
    "Show Stage 2 borrowers.",
    "Show Stage 3 borrowers.",
    "Show Stage 2 or worse borrowers.",
    "Which Stage 2 or worse borrowers are on watchlist?",
    "Which watchlist borrowers are Stage 2?",
    "Which Stage 3 borrowers are not on the watchlist?",
    "Show Shipping borrowers.",
    "Which borrowers are in Shipping?",
]

MOVEMENT = [
    "Which borrowers were downgraded?",
    "Which borrowers had rising 12-month PD?",
]


@pytest.fixture(scope="module")
def governed():
    return retrieve("x")


@pytest.fixture(scope="module")
def vocabulary():
    return get_vocabulary()


@pytest.fixture(scope="module")
def book():
    """The governed book at the acceptance period, read directly.

    The point of this fixture is that it does NOT go through the planner: the
    population it computes is an independent second opinion, and a second
    opinion assembled by the thing it is checking is not one.
    """
    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext

    found = get_data_source().fetch(
        "portfolio_facility",
        fields=["customer_id", "ifrs9_stage", "watchlist", "sector"],
        context=AnalysisContext(period="Q2 2026"))
    found["watchlist"] = found["watchlist"].astype(bool)
    return found


def _plan(question):
    return ap.plan(read_request_offline(question), retrieve("x"),
                   question=question)


class TestTheShapeDecision:
    """`Condition.kind` decides, not the mere presence of a condition."""

    def test_a_level_condition_does_not_require_two_periods(self):
        level = Condition(field="watchlist", kind="level", op="eq", value=True)
        assert not ap.asserts_movement([level])

    def test_a_movement_condition_does(self):
        for kind in ("change_pct", "change_abs"):
            moved = Condition(field="pd_12m_pct", kind=kind, op="gt", value=0.0)
            assert ap.asserts_movement([moved]), kind

    def test_one_movement_among_level_tests_still_requires_two(self):
        conditions = [
            Condition(field="watchlist", kind="level", op="eq", value=True),
            Condition(field="pd_12m_pct", kind="change_abs", op="gt", value=0.0),
        ]
        assert ap.asserts_movement(conditions)

    @pytest.mark.parametrize("question", SINGLE_PERIOD)
    def test_a_population_question_is_planned_at_one_period(self, question):
        build = _plan(question)
        assert build.shape not in (ap.COHORT, ap.MOVEMENT), (
            f"{question!r} was planned as a {build.shape}, which reads two "
            f"reporting dates for a question that compares none.")
        assert not build.opening and not build.closing

    @pytest.mark.parametrize("question", MOVEMENT)
    def test_a_movement_question_still_reads_two(self, question):
        build = _plan(question)
        assert build.shape in (ap.COHORT, ap.MOVEMENT)
        assert build.opening and build.closing


class TestThePlanIsRunnable:
    """The governed runtime validates it — the gate that was failing."""

    @pytest.mark.parametrize("question", SINGLE_PERIOD)
    def test_the_runtime_accepts_the_plan(self, question):
        from backend.runtime.ir import AnalyticalPlan
        from backend.runtime.validation import validate

        build = _plan(question)
        report = validate(AnalyticalPlan.from_dict(build.plan))
        assert report.ok, (
            f"{question!r} produced a plan the runtime refuses: "
            f"{'; '.join(report.reasons)}")

    @pytest.mark.parametrize("question", SINGLE_PERIOD)
    def test_no_step_derives_nothing(self, question):
        build = _plan(question)
        for operation in build.plan.get("operations") or []:
            if str(operation.get("op")) == "DERIVE":
                assert (operation.get("params") or {}).get("columns"), (
                    f"{question!r} emitted an empty DERIVE — the step that "
                    f"exists only because a cohort was assumed.")


class TestTheRangeIsARange:
    """"Stage 2 or worse" compiles to `>= 2`, never to an OR of equalities."""

    def test_the_predicate_is_a_range(self):
        build = _plan("Show Stage 2 or worse borrowers.")
        where = [p for op in build.plan["operations"]
                 if str(op.get("op")) == "FILTER"
                 for p in ((op.get("params") or {}).get("where") or [])]
        stage = [p for p in where if p.get("column") == "ifrs9_stage"]
        assert stage, "the stage restriction reached no predicate"
        assert stage[0]["op"] == ">=", stage
        assert stage[0]["value"] == "2"

    def test_the_widening_is_recorded_for_the_reader(self):
        build = _plan("Show Stage 2 or worse borrowers.")
        assert [(w.field, w.op) for w in build.widened] == [("ifrs9_stage", "gte")]

    def test_a_plain_stage_stays_an_equality(self):
        build = _plan("Show Stage 2 borrowers.")
        where = [p for op in build.plan["operations"]
                 if str(op.get("op")) == "FILTER"
                 for p in ((op.get("params") or {}).get("where") or [])]
        stage = [p for p in where if p.get("column") == "ifrs9_stage"]
        assert stage and stage[0]["op"] == "="


class TestTheQualifiersOrIsNotAChoice:
    """"2 or worse" is one value, and splitting the sentence on it widens it.

    Read as a disjunction, "Which Stage 2 or worse borrowers had rising PD?"
    became "stage is 2 OR PD rose" — and said so in its own heading.
    """

    def test_the_qualifier_is_masked(self):
        masked = ordinal.without_qualifiers(
            "Which Stage 2 or worse borrowers had rising PD?")
        assert " or worse" not in masked
        assert "Stage 2" in masked
        assert len(masked) == len("Which Stage 2 or worse borrowers had rising PD?")

    def test_a_genuine_either_or_survives(self):
        said = "Which borrowers are in Stage 2 or Stage 3?"
        assert ordinal.without_qualifiers(said) == said

    def test_a_genuine_disjunction_of_clauses_survives(self):
        said = "Which names had ECL rise or PD rise?"
        assert ordinal.without_qualifiers(said) == said

    def test_the_boolean_reader_conjoins_rather_than_splits(self):
        tests = [
            pr.Test(field="ifrs9_stage", op="gte", value="2", kind=pr.LEVEL,
                    phrase="Stage 2", label="IFRS 9 stage is 2"),
            pr.Test(field="pd_12m_pct", op="gt", value=0.0, kind=pr.MOVEMENT,
                    phrase="rising PD", label="12-month PD rose"),
        ]
        tree = pr.read("Which Stage 2 or worse borrowers had rising PD?", tests)
        assert tree.is_conjunction(), tree.describe()
        assert " or " not in tree.describe()


class TestTheNegationSurvives:
    """"Not on the watchlist" must not compile to `watchlist = true`."""

    def test_it_compiles_to_a_negation(self):
        build = _plan("Which Stage 3 borrowers are not on the watchlist?")
        tested = [op for op in build.plan["operations"]
                  if str(op.get("id")) == "tested"]
        assert tested, "the level test reached no FILTER"
        params = tested[0].get("params") or {}
        assert "expression" in params, (
            "a negated test compiled to a flat where-list, which cannot carry "
            "the negation")
        assert params["expression"]["function"] == "not"

    def test_the_positive_form_stays_flat(self):
        build = _plan("Which Stage 2 or worse borrowers are on watchlist?")
        tested = [op for op in build.plan["operations"]
                  if str(op.get("id")) == "tested"]
        assert tested and "where" in (tested[0].get("params") or {})

    def test_a_negated_single_test_reads_as_english(self):
        tree = pr.Node.negate(pr.Node.leaf(
            pr.Test(field="watchlist", op="eq", value=True, kind=pr.LEVEL,
                    label="on the watchlist")))
        assert tree.describe() == "not on the watchlist"


class TestTheHeadNounDecidesTheGrain:
    """"Stage 2 borrowers" is a population of BORROWERS, restricted by stage."""

    @pytest.mark.parametrize("question", [
        "Show Stage 2 borrowers.",
        "Which Stage 2 or worse borrowers are on watchlist?",
        "Which watchlist borrowers are Stage 2?",
        "Show Shipping borrowers.",
        "Which borrowers have covenant breaches?",
        "Which borrowers were downgraded?",
    ])
    def test_the_entity_is_the_head(self, question, vocabulary):
        found = dm.read(question, vocabulary)
        assert found.entity == "customer", question
        assert not found.is_head, (
            f"{question!r} read a pinned dimension as the thing the answer has "
            f"one row of, so the answer came back one row per stage.")

    @pytest.mark.parametrize("question,dimension", [
        ("Show the stage distribution", "ifrs9_stage"),
        ("Show rating distribution", "internal_grade"),
        ("What is total EAD by sector in the latest quarter?", "sector"),
        ("Which sectors have the highest ECL?", "sector"),
        ("Which sectors have borrowers with rising PD?", "sector"),
    ])
    def test_a_dimension_named_without_a_value_is_untouched(
            self, question, dimension, vocabulary):
        assert dm.read(question, vocabulary).dimension == dimension

    @pytest.mark.parametrize("question", SINGLE_PERIOD)
    def test_the_answer_has_one_row_per_borrower(self, question):
        build = _plan(question)
        assert build.grain == "customer", question
        groups = [op for op in build.plan["operations"]
                  if str(op.get("op")) in ("GROUP", "RECONCILE_GRAIN")]
        assert groups, f"{question!r} never rolled up to the borrower"
        assert "customer_id" in ((groups[0].get("params") or {}).get("by") or [])


class TestTheEntityProfile:
    """A borrower list carries the borrower's governed columns."""

    def test_a_measure_free_question_is_not_refused(self):
        build = _plan("Which borrowers are in Shipping?")
        assert build.matches, "an entity list was refused for naming no figure"

    def test_the_columns_are_governed_concepts(self):
        build = _plan("Show Stage 2 borrowers.")
        found = {m.concept.id for m in build.matches}
        assert {"ead", "ecl", "stage"} <= found, found
        assert found <= set(ap.PROFILE_CONCEPTS)

    def test_it_is_one_dataset(self):
        build = _plan("Show Stage 2 borrowers.")
        assert len({m.dataset for m in build.matches}) == 1

    def test_exposure_leads_so_the_ranking_is_by_size(self):
        build = _plan("Show Stage 2 borrowers.")
        assert build.matches[0].concept.id == "ead"

    def test_the_stage_rolls_up_by_its_governed_direction(self):
        build = _plan("Show Stage 2 borrowers.")
        group = next(op for op in build.plan["operations"]
                     if str(op.get("op")) == "GROUP")
        stage = [a for a in (group["params"].get("aggregates") or [])
                 if a["column"] == "ifrs9_stage"]
        assert stage and stage[0]["function"] == "max", (
            "a borrower with a stage 1 and a stage 3 facility is a stage 3 "
            "borrower")

    def test_a_question_that_names_its_own_measure_keeps_it(self):
        build = _plan("Show the five largest Real Estate customers by EAD.")
        assert not getattr(build, "entity_list", False)
        assert [m.concept.id for m in build.matches] == ["ead"]

    def test_an_unrestricted_entity_list_is_refused_rather_than_dumped(self):
        with pytest.raises(ap.CannotPlan):
            _plan("Show borrowers.")

    def test_a_dataset_that_cannot_test_the_restriction_is_not_chosen(self):
        carries = {d.name: set(d.fields) for d in get_catalog().all()}
        chosen = ap._profile_dataset(carries, {"ifrs9_stage", "watchlist"},
                                     "customer_id")
        assert chosen
        assert {"ifrs9_stage", "watchlist", "customer_id"} <= carries[chosen]


class TestTheBaseDatasetCanTestTheConditions:
    """A source that cannot see the watchlist cannot answer about it."""

    def test_the_condition_columns_are_scoped(self):
        build = _plan("Which Stage 2 or worse borrowers are on watchlist?")
        fields = {d.name: set(d.fields) for d in get_catalog().all()}
        assert {"ifrs9_stage", "watchlist"} <= fields[build.dataset]

    def test_conditions_reach_the_base_choice(self):
        fields = {"thin": {"customer_id", "ifrs9_stage"},
                  "whole": {"customer_id", "ifrs9_stage", "watchlist"}}
        chosen = ap._base_dataset(
            {"thin": [], "whole": []}, fields, [("ifrs9_stage", "2")], "", None,
            conditions=[Condition(field="watchlist", kind="level", op="eq",
                                  value=True)])
        assert chosen == "whole"


class TestTheBuildAdmitsWhatItApplied:
    """A restriction the plan enforced but the build hides cannot be checked."""

    def test_the_conditions_are_recorded(self):
        build = _plan("Which Stage 2 or worse borrowers are on watchlist?")
        assert [c.field for c in build.conditions] == ["watchlist"]

    def test_the_enforcement_carries_the_tree(self):
        build = _plan("Which Stage 3 borrowers are not on the watchlist?")
        assert build.enforcement is not None
        assert "not" in build.enforcement.headline

    def test_the_tested_column_survives_the_roll_up(self):
        build = _plan("Which Stage 2 or worse borrowers are on watchlist?")
        group = next(op for op in build.plan["operations"]
                     if str(op.get("op")) == "GROUP")
        carried = {a["as"] for a in (group["params"].get("aggregates") or [])}
        assert "watchlist" in carried, (
            "QF-3: a predicate on the heading must be checkable in the rows")


class TestTheCohortRollsUpAnOrdinalProperly:
    """A filtered ordinal is not carried by `any_value`.

    A borrower with a stage 1 facility and a stage 3 facility is a stage 3
    borrower. Carried arbitrarily, "which Stage 2 or worse borrowers had rising
    PD?" selected its population from whichever facility the engine reached
    first and agreed with neither reading of the question.
    """

    def test_an_ordinal_carries_its_worst_value(self):
        from backend.orchestration import multi

        assert multi._carry("ifrs9_stage") == "max"
        assert multi._carry("internal_grade") == "max"

    def test_a_better_is_worse_ordinal_carries_the_other_way(self):
        from backend.orchestration import multi

        assert multi._carry("dscr") == "min"

    def test_a_plain_dimension_is_unchanged(self):
        from backend.orchestration import multi

        for column in ("sector", "region", "segment", "period"):
            assert multi._carry(column) == "any_value"


class TestTheRowsAreTheRightRows:
    """§7: the population, reconciled against the governed source itself.

    Not "HTTP 200". Each question's borrower set is recomputed here from the
    same book the plan reads, and the answer is checked against it: no borrower
    on screen that does not belong, no borrower counted that is not there, and
    one row per borrower.
    """

    PERIOD = "Q2 2026"

    @staticmethod
    def _answer(question):
        from backend.orchestration import conversation as cv
        from backend.orchestration import memory as wm
        from backend.orchestration.executor import answer_investigation

        investigation, answered = answer_investigation(
            question, persist=False, state=cv.load({}), memory=wm.load({}))
        step = investigation.steps[0] if investigation.steps else None
        result = (step.result if isinstance(step.result, dict) else {}) if step else {}
        return investigation, answered, list(result.get("rows") or [])

    def _cases(self, book):
        return [
            ("Show Stage 2 borrowers.", book.ifrs9_stage == 2),
            ("Show Stage 3 borrowers.", book.ifrs9_stage == 3),
            ("Show Stage 2 or worse borrowers.", book.ifrs9_stage >= 2),
            ("Which Stage 2 or worse borrowers are on watchlist?",
             (book.ifrs9_stage >= 2) & book.watchlist),
            ("Which watchlist borrowers are Stage 2?",
             (book.ifrs9_stage == 2) & book.watchlist),
            ("Which borrowers are in Shipping?", book.sector == "Shipping"),
        ]

    def test_no_borrower_on_screen_is_outside_the_population(self, book):
        for question, mask in self._cases(book):
            expected = set(book.loc[mask, "customer_id"].unique())
            _, _, rows = self._answer(question)
            got = {str(r.get("customer_id")) for r in rows if r.get("customer_id")}
            assert got <= expected, (
                f"{question!r} returned {sorted(got - expected)[:5]}, which do "
                f"not satisfy the restriction it states.")

    def test_one_row_per_borrower(self, book):
        for question, _ in self._cases(book):
            _, _, rows = self._answer(question)
            ids = [str(r.get("customer_id")) for r in rows]
            assert len(ids) == len(set(ids)), (
                f"{question!r} returned the same borrower more than once.")

    def test_the_headline_states_the_true_population(self, book):
        for question, mask in self._cases(book):
            expected = len(set(book.loc[mask, "customer_id"].unique()))
            investigation, _, rows = self._answer(question)
            said = str(investigation.narrative.direct_answer or "")
            assert f"{expected:,}" in said or str(expected) in said, (
                f"{question!r} says {said!r}; the population is {expected}.")

    def test_an_empty_population_is_said_truthfully(self, book):
        question = "Which Stage 3 borrowers are not on the watchlist?"
        expected = set(book.loc[(book.ifrs9_stage == 3) & ~book.watchlist,
                                "customer_id"].unique())
        assert not expected, (
            "this book has changed: the test relies on every stage 3 facility "
            "being watchlisted")
        investigation, _, rows = self._answer(question)
        assert not rows
        said = str(investigation.narrative.direct_answer or "")
        assert "not on the watchlist" in said
        # The figure that was fabricated: a count of a population the question
        # never asked about, quoted as though it answered this one.
        assert "2,138" not in said and "2138" not in said
        assert "stage 1" not in said.lower()
