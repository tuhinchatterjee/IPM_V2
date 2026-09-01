"""
P0.6 and P0.7 — a corpus big enough to measure against, scored in layers.

    "Do not call three random cases 'high accuracy.'"
    "A good intent score must not hide a bad analytical plan."

The first sentence is about SIZE and the second is about ARITHMETIC, and these
tests hold the factory to both.
"""

from __future__ import annotations

import pytest

from intelligence_factory import complex as cx
from intelligence_factory import curriculum as cu
from intelligence_factory import generators as gen
from intelligence_factory import layers as ly

# ------------------------------------------------------------ P0.6, the corpus


def test_every_category_meets_the_count_p0_6_names():
    """The counts are large on purpose: a category with five cases produces a
    percentage that moves twenty points when one case flips."""
    coverage = cx.coverage()
    short = [row for row in coverage["categories"] if not row["meets"]]
    assert not short, [f"{r['category']}: {r['built']}/{r['required']}"
                       for r in short]
    assert coverage["complete"] is True
    assert coverage["total_built"] >= 1050


def test_the_twelve_categories_are_the_ones_p0_6_names():
    assert set(cx.CATEGORIES) == set(cx.REQUIRED)
    assert len(cx.CATEGORIES) == 12


@pytest.mark.parametrize("category", cx.CATEGORIES)
def test_a_category_produces_distinct_questions(category):
    """A corpus that reports nine hundred cases and contains six hundred
    distinct questions is measuring six hundred things and claiming nine
    hundred."""
    cases = cx.cases_for(category)
    questions = {t.question for case in cases for t in case.turns}
    assert len(questions) == len(cases), category


def test_the_corpus_is_identical_between_runs():
    """A curriculum whose cases move between runs produces scores that cannot
    be compared, which makes the whole factory decorative."""
    first = [t.question for c in cx.cases_for(cx.COHORT) for t in c.turns]
    second = [t.question for c in cx.cases_for(cx.COHORT) for t in c.turns]
    assert first == second


def test_no_case_carries_an_answer():
    """A stored answer is a number somebody quietly aligns to whatever the
    product returns. Every expectation here is about what the product must DO."""
    for case in cx.cases():
        for turn in case.turns:
            assert not hasattr(turn, "expected_value")
            assert turn.outcome in ("EXECUTE", "CLARIFY", "UNSUPPORTED")
            # The specification is capability, concepts, invariants and
            # forbidden behaviour — never a figure.
            assert all(isinstance(x, str) for x in turn.invariants)


def test_every_case_specifies_something_checkable():
    """A case with no expectation passes whatever the product does."""
    for case in cx.cases():
        for turn in case.turns:
            assert (turn.capability or turn.concepts or turn.invariants
                    or turn.forbidden or turn.outcome != "EXECUTE"), case.id


def test_a_sentence_never_asks_for_a_forbidden_aggregation():
    """"Total ECL coverage" is not a sentence anybody writes, and a corpus of
    questions no credit officer would ask measures how the product handles
    questions no credit officer would ask."""
    from backend.semantics import ontology as on

    ratios = {name for name, _ in cx.RATIOS}
    for case in cx.cases_for(cx.MULTI_CLAUSE):
        question = case.turns[0].question.lower()
        for name in ratios:
            assert f"total {name}" not in question, question
    for name, _ in cx.ADDITIVE:
        contract = next((c for c in on.contracts()
                         if c.business_name.lower() == name), None)
        assert contract is not None and contract.permits(on.SUM), name


def test_no_ambiguous_measure_is_named_bare():
    """An ambiguous measure would make every case a clarification case, which
    is a different category with its own cases."""
    from backend.semantics import ontology as on

    for name, _ in cx.PLAIN:
        contract = next((c for c in on.contracts()
                         if c.business_name.lower() == name), None)
        assert contract is not None, name
        assert contract.ambiguity is None, name


def test_the_corpus_uses_only_synthetic_subjects():
    """P0.6: no production raw client data. Also the only way this file can be
    committed to a branch anybody can read."""
    subjects = set(cx.SECTORS) | set(cx.SEGMENTS)
    for case in cx.cases():
        for turn in case.turns:
            named = [s for s in subjects if s in turn.question]
            assert all(s in subjects for s in named)


def test_the_generator_multiplies_the_corpus_without_changing_its_meaning():
    """P0.6 asks for paraphrases, typos, abbreviations and conversational
    variants. A variant inherits its case's specification unchanged — if a
    paraphrase would change the correct answer, it is not a paraphrase."""
    case = cx.cases_for(cx.COHORT, 1)[0]
    made = gen.variants(case, count=4)
    assert len(made) >= 1
    for variant in made:
        assert variant.case.turns[0].capability == case.turns[0].capability
        assert variant.case.turns[0].outcome == case.turns[0].outcome
        assert tuple(variant.case.turns[0].forbidden) == tuple(
            case.turns[0].forbidden)


def test_the_complex_corpus_does_not_replace_the_hand_written_one():
    """The thirty-three reviewed threads stay: they cover families the
    generated corpus does not, and they are where a user-reported failure is
    added."""
    assert len(cu.CASES) >= 33
    assert set(cu.FAMILIES).isdisjoint(set(cx.CATEGORIES))


# --------------------------------------------------------- P0.7, the layering


def _observation(layer: str, ok: bool, case_id: str = "x") -> ly.Observation:
    return ly.Observation(case_id, layer,
                          ly.PASS if ok else ly.FAIL, "" if ok else "no")


class _Turn:
    def __init__(self, checks: dict[str, bool]) -> None:
        self.checks = checks


class _Result:
    def __init__(self, case_id: str, checks: dict[str, bool],
                 error: str = "") -> None:
        self.case_id = case_id
        self.error = error
        self.turns = [_Turn(checks)] if checks else []


def test_all_sixteen_layers_are_scored():
    assert len(ly.LAYERS) == 16
    report = ly.score([_Result("a", {"capability": True})])
    assert [s.layer for s in report.scores] == list(ly.LAYERS)


def test_a_layer_that_did_not_apply_is_not_counted_as_a_pass():
    """A corpus of metadata questions would otherwise score 100% on the query
    layer by never compiling one — the arithmetic version of SKIPPED is not
    PASS."""
    report = ly.score([_Result(f"c{i}", {"capability": True})
                       for i in range(50)])
    query = report.score(ly.QUERY)
    assert query.observed == 0
    assert query.rate is None
    assert query.skipped == 50
    assert query not in report.measured


def test_the_headline_is_the_weakest_layer_and_never_the_mean():
    """The whole design constraint. Fifty cases where capability is right
    every time and the plan is right half the time must not report 75%."""
    results = [_Result(f"c{i}", {"capability": True, "plan": i % 2 == 0})
               for i in range(60)]
    report = ly.score(results)
    assert report.score(ly.CAPABILITY).rate == pytest.approx(100.0)
    assert report.score(ly.PLAN).rate == pytest.approx(50.0)
    assert report.headline == pytest.approx(50.0)
    assert report.weakest.layer == ly.PLAN
    assert "Analytical plan" in report.sentence()


def test_a_layer_with_too_few_observations_states_no_rate():
    """Three cases at 100% is 'three cases'. Printing a percentage from it is
    the sentence P0.7 exists to prevent."""
    report = ly.score([_Result(f"c{i}", {"plan": True}) for i in range(3)])
    plan = report.score(ly.PLAN)
    assert plan.rate is None
    assert plan.claimable is False
    assert "too few observations" in plan.sentence()
    assert report.headline is None
    assert "No accuracy claim can be made" in report.sentence()


def test_unmeasured_layers_are_reported_rather_than_assumed():
    report = ly.score([_Result(f"c{i}", {"capability": True})
                       for i in range(40)])
    assert ly.PLAN in [s.layer for s in report.unmeasured]
    assert "NOT counted as passing" in report.sentence()


def test_a_case_that_crashed_is_one_error_not_sixteen_defects():
    """Counting a crash as a failure of every layer would make one broken case
    look like sixteen separate problems."""
    report = ly.score([_Result("boom", {}, error="RuntimeError")])
    assert report.score(ly.ERRORS).failed == 1
    for layer in ly.LAYERS:
        if layer != ly.ERRORS:
            assert report.score(layer).observed == 0


@pytest.mark.parametrize("check, layer", [
    ("capability", ly.CAPABILITY),
    ("outcome", ly.CAPABILITY),
    ("concept:expected credit loss", ly.CONCEPT),
    ("dataset:portfolio_facility", ly.DATASET),
    ("invariant:share_bounds", ly.INVARIANTS),
    ("referent", ly.REFERENT),
    ("objectives", ly.OBJECTIVE),
    ("relationship", ly.RELATIONSHIP),
    ("period", ly.PERIOD),
    ("plan", ly.PLAN),
    ("query", ly.QUERY),
    ("result", ly.RESULT),
    ("interpretation", ly.INTERPRETATION),
    ("visual", ly.VISUALIZATION),
    ("trace", ly.TRACE),
    ("error", ly.ERRORS),
    ("officer", ly.OFFICER),
    ("forbidden:causal_claim", ly.INTERPRETATION),
    ("forbidden:whole_portfolio", ly.REFERENT),
    ("forbidden:measure_as_axis", ly.VISUALIZATION),
    ("forbidden:trace_disagrees", ly.TRACE),
    ("forbidden:uncategorised_failure", ly.ERRORS),
])
def test_every_check_the_evaluator_emits_lands_on_a_layer(check, layer):
    """A check that lands nowhere is evidence nobody counted."""
    assert ly._layer_for(check) == layer


def test_every_layer_says_what_it_is_for():
    """A layer name with a percentage beside it and no explanation is a number
    nobody can act on."""
    for layer in ly.LAYERS:
        assert ly.TITLES[layer]
        assert len(ly.MEANINGS[layer]) > 40, layer


def test_the_report_serialises_its_own_rule():
    report = ly.score([_Result(f"c{i}", {"plan": i % 2 == 0})
                       for i in range(60)])
    shown = report.to_dict()
    assert "WEAKEST" in shown["headline_rule"]
    assert shown["weakest_layer"] == ly.PLAN
    assert shown["minimum_observations"] == ly.MIN_OBSERVATIONS
    assert len(shown["layers"]) == 16
