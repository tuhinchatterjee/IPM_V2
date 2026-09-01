"""
Multi-condition questions, asked through the real planning path.

The defect
----------
    "Which customers were downgraded and had expected credit loss rise?"

came back as every customer whose ECL rose. The downgrade condition was read,
resolved to `customer_ratings.internal_grade`, and then vanished: the concept's
matched PHRASE was the movement word, the movement reader masked the phrase out
before looking for a direction, and nothing was left to find. No condition, no
predicate, no filter — and a heading quoting both conditions above a population
that met one.

Every test here asserts on what the PLAN does, not on what the reading
believed. That distinction is the whole point: a reading that understood a
condition and then lost it passes any test written against the reading.

The suite is deterministic and offline. It plans against the governed catalogue
and inspects the compiled IR; the tests that also run the query are marked and
skip cleanly where the lake is not built.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.orchestration import analysis_planner as ap
from backend.orchestration import concepts as cx
from backend.orchestration import context as gc
from backend.orchestration import gate, multi
from backend.orchestration import predicates as pr
from backend.orchestration import semantics as sm

# --------------------------------------------------------------------------
# The thirteen questions the remediation names, and what each one must produce
# --------------------------------------------------------------------------
#
# `predicates` is the set of governed FIELDS the plan has to test. Written as
# fields rather than as phrases because a field is what the runtime filters on
# and a phrase is what the reader believed.

CASES: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("downgrade_and_ecl",
     "Which customers were downgraded and had expected credit loss rise?",
     frozenset({"internal_grade", "total_ecl"})),
    ("pd_and_downgrade",
     "Which borrowers had 12-month PD increase and were downgraded?",
     frozenset({"pd_12m_pct", "internal_grade"})),
    ("stage_and_watchlist",
     "Which Stage 2 borrowers are on watchlist?",
     frozenset({"ifrs9_stage", "watchlist"})),
    ("utilisation_and_dscr",
     "Which borrowers have rising utilisation and declining DSCR?",
     frozenset({"utilisation_pct", "dscr"})),
    ("covenant_and_pd",
     "Which borrowers have covenant breach and rising 12-month PD?",
     frozenset({"breached", "pd_12m_pct"})),
    ("three_conditions",
     "Which borrowers were downgraded, had ECL rise and moved to Stage 2?",
     frozenset({"internal_grade", "total_ecl", "ifrs9_stage"})),
    ("leverage_margin_dscr",
     "Which customers have increasing leverage, falling EBITDA margin and "
     "weakening DSCR?",
     frozenset({"net_leverage", "ebitda_margin_pct", "dscr"})),
    ("pd_and_collateral",
     # The mandate's case 8. The core credit book publishes the collateral
     # AMOUNT and no coverage ratio, so the contract here is the honest one:
     # the PD condition is applied, and the coverage condition is REPORTED as
     # unavailable rather than quietly tested against the amount. That last
     # behaviour is what this question used to do — "below 50%" compared
     # against a figure in millions.
     "Which borrowers have 12-month PD above 5% and collateral coverage "
     "below 50%?",
     frozenset({"pd_12m_pct"})),
    ("unchanged_rating_rising_pd",
     "Which borrowers have unchanged ratings but materially rising "
     "12-month PD?",
     frozenset({"internal_grade", "pd_12m_pct"})),
    ("shipping_utilisation_liquidity",
     "Which Shipping borrowers have rising utilisation and worsening "
     "liquidity?",
     frozenset({"sector", "utilisation_pct", "liquidity_coverage_months"})),
    ("stage_not_watchlist",
     "Which Stage 2 borrowers are NOT on watchlist?",
     frozenset({"ifrs9_stage", "watchlist"})),
    ("covenant_or_dpd",
     "Which borrowers have either covenant breach OR 90+ DPD?",
     frozenset({"breached", "days_past_due"})),
    ("nested",
     "Which borrowers have (rising 12-month PD AND rating downgrade) OR "
     "Stage 3?",
     frozenset({"pd_12m_pct", "internal_grade", "ifrs9_stage"})),
)

IDS = [name for name, _, _ in CASES]
QUESTIONS = [(q, fields) for _, q, fields in CASES]


def _planned(question: str) -> ap.AnalysisBuild:
    """The plan the product builds for this question, through the real path."""
    from backend.orchestration import router

    context = gc.retrieve(question)
    reading = router.read(question).reading
    return ap.plan(reading, context, question=question)


def _tested_columns(build: ap.AnalysisBuild) -> set[str]:
    return gate.enforced_columns(build.plan)


def _governed_field(column: str, fields: frozenset[str]) -> str:
    """Which governed field a runtime column tests, or ''.

    A column reaches the FILTER prefixed by the dataset it came from and
    suffixed by what was derived from it — `customer_ratings_internal_grade_`
    `change`, `closing_covenant_tests_breached`. Matching on the governed field
    inside is what makes the assertion about the CONDITION rather than about
    the naming convention of the day.
    """
    for field_name in fields:
        if field_name in column:
            return field_name
    return ""


@pytest.fixture(scope="module")
def catalogue() -> Any:
    from backend.data_access import get_catalog

    return get_catalog()


# ==========================================================================
# The root cause
# ==========================================================================


class TestAPhraseThatIsItselfAMovement:
    """The mechanism that lost the downgrade, tested at the mechanism."""

    def test_a_bare_movement_word_asserts_its_movement(self) -> None:
        assert sm.phrase_asserts_movement("downgraded") is not None
        assert sm.phrase_asserts_movement("upgraded") is not None

    def test_a_measure_whose_name_contains_one_does_not(self) -> None:
        # The pair to the test above, and the reason the mask exists at all.
        # "probability of credit deterioration" is the NAME of twelve-month PD;
        # reading its "deterioration" as an assertion turned a request for a
        # ranking into a cohort of everyone whose PD rose.
        assert sm.phrase_asserts_movement(
            "probability of credit deterioration") is None
        assert sm.phrase_asserts_movement("expected credit loss") is None

    def test_the_movement_survives_the_mask(self) -> None:
        found = sm.movement_near(
            "Which customers were downgraded and had ECL rise?", "downgraded")
        assert found is not None
        assert found.direction.kind == "worse"

    def test_a_movement_outside_the_phrase_is_still_read(self) -> None:
        assert sm.movement_near(
            "borrowers whose ECL deteriorated this quarter", "ECL") is not None


# ==========================================================================
# The predicate tree
# ==========================================================================


def _t(phrase: str, field_name: str, op: str = "gt",
       kind: str = pr.MOVEMENT) -> pr.Test:
    return pr.Test(field=field_name, op=op, kind=kind, phrase=phrase,
                   label=phrase)


class TestTheBooleanStructureIsPreserved:
    def test_a_conjunction_stays_a_conjunction(self) -> None:
        tree = pr.read("Which customers were downgraded and had ECL rise?",
                       [_t("downgraded", "grade"), _t("ECL", "ecl")])
        assert tree.kind == pr.AND
        assert len(tree.leaves()) == 2
        assert tree.is_conjunction()

    def test_a_disjunction_is_not_flattened_into_a_conjunction(self) -> None:
        # Flattened, this asks for borrowers meeting BOTH — a smaller and
        # different population, returned under the question's own heading.
        tree = pr.read("Which borrowers have either covenant breach OR 90+ DPD?",
                       [_t("covenant breach", "breached", "eq"),
                        _t("DPD", "days_past_due", "gte")])
        assert tree.kind == pr.OR
        assert not tree.is_conjunction()

    def test_a_negation_applies_to_what_follows_it(self) -> None:
        tree = pr.read("Which Stage 2 borrowers are NOT on watchlist?",
                       [_t("Stage 2", "ifrs9_stage", "eq", pr.MEMBERSHIP),
                        _t("watchlist", "watchlist", "eq")])
        assert tree.kind == pr.AND
        kinds = sorted(c.kind for c in tree.children)
        assert kinds == [pr.NOT, pr.TEST], (
            "the negation swallowed the whole clause, so the answer excluded "
            "the Stage 2 borrowers as well as the watchlisted ones")

    def test_brackets_group(self) -> None:
        tree = pr.read(
            "Which borrowers have (rising PD AND rating downgrade) OR Stage 3?",
            [_t("PD", "pd"), _t("rating", "grade"),
             _t("Stage 3", "ifrs9_stage", "eq", pr.MEMBERSHIP)])
        assert tree.kind == pr.OR
        assert any(c.kind == pr.AND and len(c.children) == 2
                   for c in tree.children)

    def test_and_binds_tighter_than_or(self) -> None:
        tree = pr.read("A rose and B fell or C rose",
                       [_t("A", "a"), _t("B", "b"), _t("C", "c")])
        assert tree.kind == pr.OR
        assert tree.children[0].kind == pr.AND

    def test_but_is_a_conjunction(self) -> None:
        tree = pr.read("unchanged ratings but materially rising PD",
                       [_t("ratings", "grade", "eq"), _t("PD", "pd")])
        assert tree.kind == pr.AND
        assert len(tree.leaves()) == 2

    def test_a_test_the_sentence_cannot_place_is_still_kept(self) -> None:
        # An inherited filter names no phrase in this turn's words. Dropping it
        # for want of somewhere to put it is the defect this module exists to
        # stop, arriving from the module itself.
        tree = pr.read("which of those are the real issues?",
                       [_t("", "sector", "eq", pr.MEMBERSHIP)])
        assert len(tree.leaves()) == 1


class TestTheTreeCompilesToWhatItMeans:
    def test_a_conjunction_compiles_to_the_flat_predicate_list(self) -> None:
        # The shape every existing plan, Trace and test already reads. A
        # question with one condition must produce exactly the plan it did
        # before this module existed.
        tree = pr.read("A rose and B rose", [_t("A", "a"), _t("B", "b")])
        params = pr.compile_filter(tree, lambda t: t.field)
        assert list(params) == ["where"]
        assert [p["column"] for p in params["where"]] == ["a", "b"]

    def test_a_disjunction_compiles_to_an_expression(self) -> None:
        tree = pr.read("A rose or B rose", [_t("A", "a"), _t("B", "b")])
        params = pr.compile_filter(tree, lambda t: t.field)
        assert list(params) == ["expression"]
        assert params["expression"]["function"] == "or"

    def test_a_negation_compiles_to_a_negation(self) -> None:
        tree = pr.read("not on watchlist", [_t("watchlist", "w", "eq")])
        params = pr.compile_filter(tree, lambda t: t.field)
        assert params["expression"]["function"] == "not"

    def test_a_compiled_expression_binds_its_values(self) -> None:
        # Never spliced text. The value came from a question, and a question is
        # not a place a statement may be assembled from.
        tree = pr.read("A rose or B rose",
                       [pr.Test(field="a", op="gt", value=7.5, phrase="A"),
                        _t("B", "b")])
        found = pr.expression(tree, lambda t: t.field)
        assert found["args"][0]["args"][1] == {"type": "literal", "value": 7.5}

    def test_the_tree_reads_back_as_the_sentence(self) -> None:
        tree = pr.read(
            "Which borrowers have (rising PD AND rating downgrade) OR Stage 3?",
            [_t("PD", "pd"), _t("rating", "grade"),
             _t("Stage 3", "ifrs9_stage", "eq", pr.MEMBERSHIP)])
        assert tree.describe() == "(PD and rating) or Stage 3"


# ==========================================================================
# The thirteen questions, planned for real
# ==========================================================================


class TestEveryConditionReachesThePlan:
    @pytest.mark.parametrize("question,fields", QUESTIONS, ids=IDS)
    def test_every_named_predicate_is_tested_by_the_plan(
            self, question: str, fields: frozenset[str]) -> None:
        """The release-blocking assertion, and the one the defect failed.

        Not "the reading found both conditions" — it did, and the answer was
        still wrong. This asks the compiled FILTER which columns it tests.
        """
        try:
            build = _planned(question)
        except ap.CannotPlan as stop:
            pytest.skip(f"the planner stopped to ask: {stop.reason}")
        tested = _tested_columns(build)
        reached = {_governed_field(c, fields) for c in tested} - {""}
        missing = fields - reached
        assert not missing, (
            f"{question!r} planned a filter on {sorted(reached)} and silently "
            f"dropped {sorted(missing)}")

    @pytest.mark.parametrize("question,fields", QUESTIONS, ids=IDS)
    def test_the_plan_records_the_boolean_structure(
            self, question: str, fields: frozenset[str]) -> None:
        try:
            build = _planned(question)
        except ap.CannotPlan as stop:
            pytest.skip(f"the planner stopped to ask: {stop.reason}")
        tree = multi.predicate_tree_of(build.plan)
        if tree is None:
            pytest.skip("this shape does not compile through the multi builder")
        assert tree.leaves(), "the plan recorded no predicates at all"
        assert tree.describe(), "the structure has no readable form"

    @pytest.mark.parametrize("question,fields", QUESTIONS, ids=IDS)
    def test_nothing_is_dropped_without_saying_so(
            self, question: str, fields: frozenset[str]) -> None:
        """Either every condition ran, or the answer says which did not.

        The one outcome that is never acceptable is the third: a condition
        neither applied nor mentioned.
        """
        try:
            build = _planned(question)
        except ap.CannotPlan:
            return  # stopping to ask is not a silent drop
        enforcement = build.enforcement
        if enforcement is None or enforcement.complete:
            return
        said = " ".join(build.warnings)
        for missing in list(enforcement.missing):
            assert missing.describe() in said or enforcement.limitation in said
        for unread in enforcement.unread:
            assert unread in said, (
                f"{question!r} did not apply {unread!r} and did not say so")

    @pytest.mark.parametrize("question,fields", QUESTIONS, ids=IDS)
    def test_a_cross_domain_condition_is_joined_rather_than_abandoned(
            self, question: str, fields: frozenset[str]) -> None:
        """A condition in another dataset is a join, not an excuse."""
        try:
            build = _planned(question)
        except ap.CannotPlan as stop:
            pytest.skip(f"the planner stopped to ask: {stop.reason}")
        request = build.request
        if request is None or len(request.datasets) < 2:
            pytest.skip("this question is answered from one dataset")
        assert request.resolution is not None and request.resolution.ok
        assert build.joins, "several datasets were read with no join recorded"


class TestGrainIsNotDoubleCounted:
    """A many-to-one join must be rolled up before it multiplies the book."""

    def test_a_facility_grained_condition_is_aggregated_to_the_borrower(
            self) -> None:
        question = ("Which borrowers have rising utilisation and declining "
                    "DSCR?")
        try:
            build = _planned(question)
        except ap.CannotPlan as stop:
            pytest.skip(f"the planner stopped to ask: {stop.reason}")
        assert build.grain == "customer"
        operations = build.plan.get("operations") or []
        kinds = {str(o.get("op") or "") for o in operations}
        assert "RECONCILE_GRAIN" in kinds or "GROUP" in kinds, (
            "a facility-grained measure reached a borrower-grained answer with "
            "no roll-up, so a borrower with four facilities counts four times")

    def test_one_row_per_borrower(self) -> None:
        question = "Which customers were downgraded and had expected credit " \
                   "loss rise?"
        build = _planned(question)
        request = build.request
        assert request is not None
        assert request.key == "customer_id"
        # The join that pairs the two dates is on the analysis key alone. Any
        # other key here would pair a borrower with somebody else's closing row.
        joins = [o for o in (build.plan.get("operations") or [])
                 if str(o.get("op") or "") == "JOIN"
                 and str(o.get("id") or "") == "movement"]
        assert joins and joins[0]["params"]["on"] == ["customer_id"]


# ==========================================================================
# The coverage gate
# ==========================================================================


class TestTheCoverageGate:
    def test_a_condition_the_plan_does_not_test_is_reported(self) -> None:
        tree = pr.read("A rose and B rose", [_t("A", "a"), _t("B", "b")])
        plan = {"operations": [
            {"op": "FILTER", "params": {"where": [{"column": "a", "op": ">"}]}}]}
        found = gate.inspect(tree, plan)
        assert not found.complete
        assert [t.field for t in found.missing] == ["b"]
        assert "B" in found.limitation

    def test_a_plan_that_tests_everything_is_complete(self) -> None:
        tree = pr.read("A rose and B rose", [_t("A", "a"), _t("B", "b")])
        plan = {"operations": [{"op": "FILTER", "params": {"where": [
            {"column": "a", "op": ">"}, {"column": "b", "op": ">"}]}}]}
        assert gate.inspect(tree, plan).complete

    def test_a_column_inside_an_expression_counts_as_tested(self) -> None:
        # A disjunction compiles to an expression rather than a predicate list,
        # and a gate that only read the list would report every OR question as
        # having dropped half its conditions.
        tree = pr.read("A rose or B rose", [_t("A", "a"), _t("B", "b")])
        plan = {"operations": [{"op": "FILTER", "params": {
            "expression": pr.expression(tree, lambda t: t.field)}}]}
        assert gate.inspect(tree, plan).complete

    def test_the_sentence_names_only_what_ran(self) -> None:
        tree = pr.read("A rose and B rose", [_t("A", "a"), _t("B", "b")])
        plan = {"operations": [
            {"op": "FILTER", "params": {"where": [{"column": "a", "op": ">"}]}}]}
        found = gate.inspect(tree, plan)
        said = gate.population_sentence(found, grain="customer")
        assert "A" in said
        assert "B" not in said, (
            "the answer claimed a condition the plan did not apply")

    def test_a_negation_the_plan_ignored_is_caught(self) -> None:
        dropped = gate.dropped_structure(
            "Which Stage 2 borrowers are NOT on watchlist?",
            None, None, [], [], [("ifrs9_stage", "2")])
        assert any("exclusion" in d for d in dropped)

    def test_a_disjunction_the_plan_ignored_is_caught(self) -> None:
        dropped = gate.dropped_structure(
            "Which borrowers have either covenant breach OR 90+ DPD?",
            None, None, [], [], [])
        assert any("either" in d for d in dropped)

    def test_a_directed_clause_with_no_governed_concept_is_caught(self) -> None:
        # "worsening liquidity" resolved to nothing at all, so no leaf exists
        # to compare against the plan. Read from the sentence instead.
        dropped = gate.dropped_structure(
            "Which borrowers have rising utilisation and worsening "
            "reputational standing?",
            None, None, [], [], [])
        assert any("reputational" in d for d in dropped)

    def test_an_ordinary_answered_question_reports_nothing(self) -> None:
        # The gate must be quiet when there is nothing wrong, or nobody will
        # read it when there is.
        build = _planned("Which customers were downgraded and had expected "
                         "credit loss rise?")
        assert build.enforcement is not None
        assert build.enforcement.complete
        assert not [w for w in build.warnings if "could not apply" in w]


# ==========================================================================
# What the answer says about itself
# ==========================================================================


class TestTheNarrativeDerivesFromThePlan:
    def test_the_claim_is_not_made_from_the_question(self) -> None:
        from backend.orchestration import assembly

        build = _planned("Which customers were downgraded and had expected "
                         "credit loss rise?")
        said = assembly._stated(build)
        assert "internal rating was downgraded" in said
        assert "ECL rose" in said

    def test_a_disjunction_is_not_read_back_as_a_conjunction(self) -> None:
        from backend.orchestration import assembly

        try:
            build = _planned(
                "Which borrowers have either covenant breach OR 90+ DPD?")
        except ap.CannotPlan as stop:
            pytest.skip(f"the planner stopped to ask: {stop.reason}")
        assert " or " in assembly._stated(build), (
            "an either/or question was read back as though both had to hold")


# ==========================================================================
# What the answer shows
# ==========================================================================


class TestThePresentationOfTheLiveQuestion:
    QUESTION = ("Which customers were downgraded and had expected credit "
                "loss rise?")

    @pytest.fixture(scope="class")
    @classmethod
    def shown(cls) -> list[dict[str, Any]]:
        from backend.orchestration import presentation as pres
        from backend.orchestration.executor import answer_investigation

        try:
            _, answered = answer_investigation(cls.QUESTION, persist=False)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the governed runtime is not available: {exc}")
        if getattr(answered, "runtime", None) is None:
            pytest.skip("the question did not reach the runtime in this build")
        return pres.contract(answered.runtime, answered.build)

    def test_it_is_a_table_and_not_a_chart(self, shown: Any) -> None:
        from backend.orchestration import viz_intent as vi

        assert shown, "the result carried no columns"
        # Table first. A list of borrowers to act on is read row by row, and a
        # chart of 262 of them answers nobody's question.
        assert vi.classify(self.QUESTION) == vi.RETRIEVAL
        assert not vi.asked_for_a_chart(self.QUESTION)
        assert vi.wants_rows(self.QUESTION)

    @pytest.mark.parametrize("wanted", [
        "Borrower", "Customer", "Internal rating", "Expected credit loss",
        "Change in Internal rating", "Change in Expected credit loss",
        "IFRS 9 stage", "EAD", "Sector",
    ])
    def test_the_column_the_question_needs_is_there(self, shown: Any,
                                                    wanted: str) -> None:
        labels = [c["label"] for c in shown if not c["hidden"]]
        assert any(wanted in label for label in labels), (
            f"{wanted!r} is not on the answer, so the reader cannot check it")

    def test_a_measure_keeps_its_opening_closing_and_change_together(
            self, shown: Any) -> None:
        labels = [c["label"] for c in shown if not c["hidden"]]
        rating = [i for i, label in enumerate(labels)
                  if "Internal rating" in label]
        assert rating == list(range(rating[0], rating[0] + len(rating))), (
            "the opening and closing rating are separated by other columns, "
            "and the pair is what the question is about")

    def test_an_attribute_is_not_shown_twice(self, shown: Any) -> None:
        labels = [c["label"] for c in shown if not c["hidden"]]
        for attribute in ("Sector", "Region", "Segment"):
            assert sum(1 for label in labels if label.startswith(attribute)) <= 1, (
                f"{attribute} is shown at both dates, and it does not move")


# ==========================================================================
# The post-result check, under a disjunction
# ==========================================================================


class TestTheInvariantRespectsTheStructure:
    def test_a_row_meeting_one_side_of_an_or_is_not_a_violation(self) -> None:
        from backend.orchestration import invariants as inv

        tree = pr.read("A rose or B rose",
                       [pr.Test(field="a", op="gt", value=0.0, phrase="A"),
                        pr.Test(field="b", op="gt", value=0.0, phrase="B")])
        check = inv.Check(rule="predicate_tree", claim="every row satisfies it",
                          params={"tree": tree.to_dict()})
        rows = [{"a": 1.0, "b": -1.0}, {"a": -1.0, "b": 2.0}]
        assert inv._predicate_tree(check, rows, None) is None

    def test_a_row_meeting_neither_side_is_a_violation(self) -> None:
        from backend.orchestration import invariants as inv

        tree = pr.read("A rose or B rose",
                       [pr.Test(field="a", op="gt", value=0.0, phrase="A"),
                        pr.Test(field="b", op="gt", value=0.0, phrase="B")])
        check = inv.Check(rule="predicate_tree", claim="every row satisfies it",
                          params={"tree": tree.to_dict()})
        rows = [{"a": -1.0, "b": -1.0}]
        assert inv._predicate_tree(check, rows, None) is not None

    def test_a_negation_is_evaluated_as_one(self) -> None:
        from backend.orchestration import invariants as inv

        tree = pr.read("not on watchlist",
                       [pr.Test(field="w", op="eq", value=True,
                                phrase="watchlist")])
        check = inv.Check(rule="predicate_tree", claim="not on the watchlist",
                          params={"tree": tree.to_dict()})
        assert inv._predicate_tree(check, [{"w": False}], None) is None
        assert inv._predicate_tree(check, [{"w": True}], None) is not None


# ==========================================================================
# The governed vocabulary the repair needed
# ==========================================================================


class TestTheStatesTheQuestionsName:
    @pytest.mark.parametrize("phrase,field_name", [
        ("on watchlist", "watchlist"),
        ("covenant breach", "breached"),
    ])
    def test_a_state_resolves_to_a_governed_field(self, phrase: str,
                                                  field_name: str,
                                                  catalogue: Any) -> None:
        known = {d.name: {f["name"] for f in d.fields}
                 for d in gc.all_datasets()}
        found = cx.read_concepts(f"Which borrowers have {phrase}?",
                                 known=known, catalogue=catalogue)
        assert any(m.field == field_name for m in found.matches), (
            f"{phrase!r} resolves to nothing, so the condition cannot be built")

    def test_naming_a_state_is_asserting_it(self) -> None:
        known = {d.name: {f["name"] for f in d.fields}
                 for d in gc.all_datasets()}
        from backend.data_access import get_catalog

        found = cx.read_concepts("Which borrowers are on watchlist?",
                                 known=known, catalogue=get_catalog())
        match = next(m for m in found.matches if m.field == "watchlist")
        condition = sm.state_condition(match, "Which borrowers are on "
                                              "watchlist?")
        assert condition is not None
        assert condition.op == "eq" and condition.value is True

    def test_a_state_asked_to_be_reported_is_not_a_condition(self) -> None:
        known = {d.name: {f["name"] for f in d.fields}
                 for d in gc.all_datasets()}
        from backend.data_access import get_catalog

        question = "Show exposure by watchlist status."
        found = cx.read_concepts(question, known=known,
                                 catalogue=get_catalog())
        for match in found.matches:
            if match.field == "watchlist":
                assert sm.state_condition(match, question) is None

    def test_a_number_beside_a_state_is_not_a_threshold_on_it(self) -> None:
        # "covenant breach or 90+ DPD" built `breached >= 90`, which the
        # database refused at the point the answer was due — and which would
        # have been worse had it succeeded.
        known = {d.name: {f["name"] for f in d.fields}
                 for d in gc.all_datasets()}
        from backend.data_access import get_catalog

        question = "Which borrowers have covenant breach or 90+ DPD?"
        found = cx.read_concepts(question, known=known,
                                 catalogue=get_catalog())
        for match in found.matches:
            if match.field != "breached":
                continue
            level = sm.threshold_condition(
                match, sm.threshold_near(question, match.phrase))
            assert level is None

    def test_the_plus_shorthand_is_a_bound(self) -> None:
        found = sm.find_threshold("90+ DPD")
        assert found is not None
        assert (found.op, found.value) == ("gte", 90.0)


class TestTheLiquidityDomainIsReachable:
    def test_a_governed_relationship_connects_it(self) -> None:
        # Registered as a dataset with no join, which refused every question
        # combining liquidity with anything else.
        from backend.runtime.joins import build_graph, resolve

        # Every declared relationship, not the handful a retrieval window
        # surfaces for one phrase: the question is whether the join EXISTS.
        rows = ap._relationship_rows(
            gc.retrieve("rising utilisation and worsening liquidity"))
        rows = rows or []
        if len(rows) < len(gc.all_relationships()):
            rows = [
                {"id": r.relationship_id, "from_dataset": r.from_dataset,
                 "from_field": r.from_field, "to_dataset": r.to_dataset,
                 "to_field": r.to_field, "cardinality": r.cardinality,
                 "join_policy": r.join_policy,
                 "temporal_rule": r.temporal_rule, "semantic": r.semantic,
                 "version": r.version, "match_rate": r.match_rate,
                 "confidence": 1.0, "validated_at": True}
                for r in gc.all_relationships()]
        if not rows:
            pytest.skip("no relationship graph is published in this build")
        graph = build_graph(rows)
        found = resolve(graph, base=multi.DEFAULT_BASE,
                        targets=["liquidity_buffer"])
        assert found.ok, (
            "liquidity cannot be joined to the facility book, so every "
            "question combining it with anything else is refused")
