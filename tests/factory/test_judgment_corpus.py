"""
§95, §96 — the analytical-judgment corpus and its four evaluations.

    §95: "Do not inflate with trivial variants."
    §96: "Evaluate separately."

Both lines are about the same temptation. Six hundred cases is easy to produce
and hard to produce honestly — swapping one sector for another gives you two
cases and one lesson. One aggregate score is easy to report and hides
precisely the failure that matters, because the four suites fail for unrelated
reasons and each masks the others.

So these tests check the honesty machinery as much as the counts: that the
distinct-lesson count is real, that no dimension defaults to a pass, that a
clean-but-small sample is not reported as a defect, and that no combined
judgment score exists anywhere.
"""

from __future__ import annotations

import pytest

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st
from intelligence_factory import judgment_evaluations as je
from intelligence_factory.teaching import judgment_blueprints as jb

# ================================================== §95 the corpus


def test_the_corpus_meets_every_target_section_95_sets():
    report = jb.report()

    assert report["meets_targets"] is True
    assert report["short_of_target"] == {}
    assert report["total"] == sum(jb.TARGETS.values())
    for family, target in jb.TARGETS.items():
        assert report["by_family"][family] >= target, family


def test_every_family_the_corpus_writes_to_exists():
    known = {f.id for f in fam.FAMILIES}
    for family in jb.TARGETS:
        assert family in known, family


def test_no_case_claims_to_be_human_written():
    """Calling six hundred generated cases HUMAN would make the governance
    report say something untrue about how this library was built."""
    for case in jb.cases():
        assert case.authoring_method == st.BLUEPRINT, case.case_id
        assert case.authoring_method in st.GENERATED


def test_every_case_validates():
    problems: dict[str, int] = {}
    for case in jb.cases():
        for problem in sc.validate(case):
            problems[problem.field] = problems.get(problem.field, 0) + 1

    assert problems == {}


def test_case_ids_are_unique_and_stable_between_runs():
    """A corpus whose cases move between runs produces scores that cannot be
    compared."""
    first = jb.cases()
    second = jb.cases()

    ids = [c.case_id for c in first]
    assert len(set(ids)) == len(ids)
    assert ids == [c.case_id for c in second]
    assert [c.fingerprint for c in first] == [c.fingerprint for c in second]


def test_no_two_cases_are_the_same_case():
    fingerprints = [c.fingerprint for c in jb.cases()]

    assert len(set(fingerprints)) == len(fingerprints)


def test_the_corpus_is_not_inflated_with_trivial_variants():
    """§95's last line, made checkable. A family with a hundred cases and six
    lessons has been inflated; the same family with sixty has not. The floor
    is one distinct lesson per three cases — below that the family is teaching
    the same thing over and over."""
    produced = jb.cases()
    distinct = jb.lessons(produced)

    for family in jb.TARGETS:
        cases = len([c for c in produced if c.family_id == family])
        assert distinct[family] * 3 >= cases, (
            family, distinct[family], cases)


def test_each_family_varies_along_the_axis_it_is_about():
    """Not merely along the sector name. The right answer has to move."""
    produced = jb.cases()

    blueprints = {c.expected_blueprint
                  for c in produced
                  if c.family_id == "INVESTIGATION_BLUEPRINT"}
    assert len(blueprints) >= 10

    explanations = {c.expected_contradiction
                    for c in produced
                    if c.family_id == "CONTRADICTORY_SIGNALS"}
    assert len(explanations) >= 8

    charts = {c.expected_visualization
              for c in produced
              if c.family_id == "VISUALIZATION_SELECTION"}
    assert len(charts) >= 8

    bands = {c.expected_materiality_band
             for c in produced if c.family_id == "MATERIALITY_JUDGMENT"}
    assert len(bands) >= 4


def test_the_contradiction_family_teaches_unresolved_as_an_answer():
    """§84's whole point is that UNRESOLVED is sometimes right, and a corpus
    without it teaches that every contradiction has a story."""
    from backend.judgment import contradictions as cd

    unresolved = [c for c in jb.cases()
                  if c.family_id == "CONTRADICTORY_SIGNALS"
                  and c.expected_contradiction == cd.TRUE_CONTRADICTION]

    assert unresolved
    assert any("somebody needs to look" in t.expected_answer_behavior
               for c in unresolved for t in c.conversation_turns)


def test_the_visualization_family_teaches_the_table_as_an_answer():
    from backend.judgment import visual_grammar as vg

    tables = [c for c in jb.cases()
              if c.family_id == "VISUALIZATION_SELECTION"
              and c.expected_visualization == vg.TABLE]

    assert tables


def test_every_case_declares_a_plan_an_ir_or_a_method():
    for case in jb.cases():
        assert case.analytical_plan_contract, case.case_id


def test_the_report_names_a_shortfall_rather_than_hiding_it():
    """A family that cannot reach its target is a family whose blueprint
    needs more shapes, which is a decision for a person."""
    report = jb.report()

    assert "short_of_target" in report
    assert "distinct_lessons" in report
    assert "none written by hand" in report["sentence"]


# ================================================ §96 the four evaluations


def _clean(suite: str, count: int) -> list[je.Case]:
    return [je.Case(f"{suite}-{i}", suite,
                    {d: True for d in je.DIMENSIONS[suite]})
            for i in range(count)]


def test_the_four_suites_section_96_names_have_all_their_dimensions():
    assert set(je.SUITES) == {je.INVESTIGATION, je.INTERPRETATION,
                              je.CONTRADICTION, je.VISUALIZATION}
    assert len(je.DIMENSIONS[je.INVESTIGATION]) == 8
    assert len(je.DIMENSIONS[je.INTERPRETATION]) == 10
    assert len(je.DIMENSIONS[je.CONTRADICTION]) == 5
    assert len(je.DIMENSIONS[je.VISUALIZATION]) == 7
    for suite in je.SUITES:
        for dimension in je.DIMENSIONS[suite]:
            assert je.ASKS[dimension].endswith("?"), dimension


def test_there_is_no_combined_judgment_score_anywhere():
    """One aggregate would be the most misleading number this system could
    produce: a system that picks blueprints perfectly and invents
    contradiction explanations would score well."""
    report = je.report(_clean(je.VISUALIZATION, 200))

    assert report["no_combined_score"] is True
    assert "overall_score" not in report
    assert "accuracy" not in report
    assert isinstance(report["releasable"], bool)


def test_a_dimension_no_case_exercised_is_named_rather_than_passed():
    """A suite that silently omitted a dimension would report a perfect score
    for the seven it did run, and §96 asks for eight."""
    partial = [je.Case("a", je.INVESTIGATION, {"blueprint_selection": True})]

    result = je.evaluate(je.INVESTIGATION, partial)

    assert "challenge_quality" in result.unmeasured
    assert result.clean is False
    assert "not measured" in result.sentence()


def test_an_unmeasured_critical_dimension_fails():
    """A grounding check nobody ran is not evidence that the answers were
    grounded."""
    partial = [je.Case("a", je.INTERPRETATION, {"directness": True})]

    result = je.evaluate(je.INTERPRETATION, partial)

    assert "facts" in result.critical_failures
    assert "non_causality" in result.critical_failures


def test_a_dimension_is_measured_only_over_the_cases_that_recorded_it():
    """Otherwise a suite looks worse the more unrelated cases it grows."""
    cases = [*_clean(je.CONTRADICTION, 40),
             je.Case("x", je.CONTRADICTION, {"detection": True})]

    result = je.evaluate(je.CONTRADICTION, cases)

    assert result.rates["detection"].total == 41
    assert result.rates["taxonomy"].total == 40


def test_a_claim_is_compared_against_the_lower_bound():
    """A point estimate of 100% over twenty cases supports a claim of about
    84%, and quoting the point estimate is the mistake `metrics` exists to
    stop."""
    small = je.evaluate(je.CONTRADICTION, _clean(je.CONTRADICTION, 20))

    assert small.rates["detection"].point == 100.0
    assert small.rates["detection"].lower < 95.0
    assert small.clean is False


def test_a_clean_but_small_sample_is_not_reported_as_a_defect():
    """The answer there is more cases, not a fix, and a gate that cannot say
    so sends a team hunting a bug that is a sample size."""
    small = je.evaluate(je.VISUALIZATION, _clean(je.VISUALIZATION, 60))

    assert small.underpowered
    assert "underpowered" in small.sentence()
    assert "more cases, not a fix" in small.sentence()

    # Scoped to this suite: a report over one suite's cases correctly fails
    # the other three for having measured nothing at all.
    report = je.report(_clean(je.VISUALIZATION, 60))
    visual = [f for f in report["critical_failures_with_errors"]
              if f.startswith("VISUALIZATION.")]
    assert visual == []
    assert "VISUALIZATION.reconciliation" in report["underpowered"]


def test_a_real_critical_failure_is_told_apart_from_an_underpowered_one():
    cases = _clean(je.VISUALIZATION, 200)
    for case in cases[:40]:
        case.outcomes["reconciliation"] = False

    report = je.report(cases)

    assert "VISUALIZATION.reconciliation" in \
        report["critical_failures_with_errors"]
    assert "VISUALIZATION.reconciliation" not in report["underpowered"]
    assert report["releasable"] is False


def test_a_large_clean_run_is_releasable():
    cases = [c for suite in je.SUITES for c in _clean(suite, 200)]

    report = je.report(cases)

    assert report["critical_failures"] == []
    assert report["releasable"] is True


def test_every_critical_dimension_is_one_where_the_output_asserts_something():
    """The same line §94 draws between safety and quality: a failure here is
    an untrue statement, not a clumsy one."""
    assert "reconciliation" in je.CRITICAL
    assert "facts" in je.CRITICAL
    assert "unresolved_honesty" in je.CRITICAL
    # Readability and repetition are real defects and are not of this kind.
    assert "readability" not in je.CRITICAL
    assert "repetition" not in je.CRITICAL


def test_critical_dimensions_are_held_to_a_higher_bar():
    assert je.CRITICAL_TARGET_PCT > je.TARGET_PCT


def test_an_unknown_suite_is_refused():
    with pytest.raises(KeyError):
        je.evaluate("VIBES", [])


def test_an_empty_run_reports_nothing_evaluated_rather_than_success():
    report = je.report([])

    assert report["releasable"] is False
    for suite in je.SUITES:
        assert "nothing was evaluated" in \
            report["suites"][suite]["sentence"]
