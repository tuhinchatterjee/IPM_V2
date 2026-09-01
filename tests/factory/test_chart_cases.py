"""
§89 — the chart teaching case library.

    "Add at least 150 visualization cases. … Include invalid examples."

Why the invalid examples are the library
-----------------------------------------
A hundred and fifty cases of "this shape maps to this chart" teach a mapping
§86 already states as data. The seven invalid examples are the cases where a
plausible chart is a false one, and they are the reason the library exists —
so most of these tests are about them.

Every case is checked against the REAL grammar and the REAL critic rather than
against its own labels. A library that could claim a preference the system
does not make would teach a rule that does not exist, and would go on teaching
it after somebody changed the rule.
"""

from __future__ import annotations

from backend.judgment import visual_critic as vc
from backend.judgment import visual_grammar as vg
from intelligence_factory import chart_cases as cc


def test_the_library_meets_section_89s_floor():
    report = cc.report()

    assert report["total"] >= cc.MINIMUM_CASES
    assert report["meets_minimum"] is True
    assert len(cc.CASES) == report["total"]


def test_every_shape_section_86_names_is_covered():
    assert cc.gaps() == []
    for shape in vg.SHAPES:
        assert cc.coverage()[shape] > 0, shape


def test_case_ids_are_unique():
    ids = [c.case_id for c in cc.CASES]
    assert len(set(ids)) == len(ids)
    assert set(cc.BY_ID) == set(ids)


def test_every_case_carries_the_fields_section_89_lists():
    for case in cc.CASES:
        assert case.result_shape in vg.SHAPES, case.case_id
        assert case.semantic_fields, case.case_id
        assert case.preferred_chart in vg.CHARTS, case.case_id
        assert case.accessibility_fallback.strip(), case.case_id
        assert case.teaches.strip(), case.case_id
        for role in case.semantic_fields.values():
            assert role in vg.ROLES, (case.case_id, role)
        for chart in (*case.acceptable_alternatives, *case.rejected_charts):
            assert chart in vg.CHARTS, (case.case_id, chart)


def test_every_valid_case_declares_what_clicking_does():
    """§90's interactive selection depends on knowing what a click MEANS on
    each shape, and a contract invented at render time is one nobody can
    test."""
    for case in cc.valid():
        assert case.interaction_contract.strip(), case.case_id
    for chart in vg.CHARTS:
        assert cc.INTERACTION[chart].strip(), chart


def test_no_rejection_is_recorded_without_a_reason():
    """A rejection with no reason teaches that a chart is disliked, not what
    is wrong with it."""
    for case in cc.valid():
        for chart in case.rejected_charts:
            assert case.rejection_reasons.get(chart, "").strip(), \
                (case.case_id, chart)


def test_every_valid_case_agrees_with_the_real_grammar():
    """The library cannot claim a preference the system does not make."""
    for case in cc.valid():
        selection = vg.select(case.result_shape, case.scoring_inputs())
        assert selection.chosen == case.preferred_chart, case.case_id
        assert set(case.rejected_charts) == \
            {s.chart for s in selection.rejected}, case.case_id


def test_the_preferred_chart_is_never_one_the_case_also_rejects():
    for case in cc.CASES:
        assert case.preferred_chart not in case.rejected_charts, case.case_id
        assert case.preferred_chart not in case.acceptable_alternatives, \
            case.case_id


def test_every_chart_in_the_mapping_is_taught_somewhere():
    """A library that never mentions a waterfall cannot teach one, however
    many cases it has."""
    mentioned: set[str] = set()
    for case in cc.valid():
        mentioned.add(case.preferred_chart)
        mentioned.update(case.acceptable_alternatives)

    assert set(vg.CHARTS) - mentioned == set()


def test_the_library_covers_the_dimensions_that_change_the_answer():
    """Six sectors and forty-five sectors are different charts; a narrow
    device is a different chart again."""
    shapes = {(c.result_shape, c.inputs.get("categories")) for c in cc.valid()}
    assert len({c for _, c in shapes}) >= 4

    ranking = cc.by_shape(vg.CATEGORY_RANKING)
    preferred = {c.preferred_chart for c in ranking}
    assert len(preferred) >= 3, preferred


# ============================================ §89's seven invalid examples


def test_all_seven_invalid_examples_are_present():
    assert len(cc.INVALID) == 7
    teaches = " ".join(c.teaches for c in cc.INVALID)
    for phrase in ("numeric measure", "vertical bar", "third dimension",
                   "Sankey", "heatmap", "line chart", "zero baseline"):
        assert phrase in teaches, phrase


def test_every_invalid_case_is_actually_refused_by_the_grammar():
    """Written by hand, checked against the real scorer. A case asserting a
    rejection the system does not make would teach a rule that does not
    exist."""
    for case in cc.invalid():
        scored = vg.score(case.attempted_chart, case.scoring_inputs())
        assert scored.accepted is False, case.case_id
        assert any(case.must_reject in reason for reason in scored.rejections),\
            (case.case_id, scored.rejections)


def test_every_invalid_case_names_a_chart_that_would_have_been_drawn():
    """The point of an invalid example is that something plausible produced
    it. A case whose attempted chart nothing would ever choose teaches
    nothing."""
    for case in cc.invalid():
        assert case.attempted_chart in vg.CHARTS, case.case_id
        assert case.attempted_chart in case.rejected_charts, case.case_id
        assert case.attempted_chart != case.preferred_chart, case.case_id


def test_every_invalid_case_offers_something_to_draw_instead():
    for case in cc.invalid():
        assert case.preferred_chart in vg.CHARTS, case.case_id
        assert case.rejection_reasons.get(case.attempted_chart, "").strip(), \
            case.case_id


def test_the_measure_as_category_case_is_refused_by_the_critic_too():
    """The grammar refuses it before the chart is built and the critic
    refuses it after. Both, because a chart can be rebound between them."""
    case = cc.BY_ID["cc-bad-measure-as-category"]
    built = vc.Chart(chart=case.attempted_chart, roles=case.semantic_fields,
                     labels=["1", "2"], series={"v": [1.0, 2.0]},
                     units={"v": "SAR"}, has_accessible_table=True)

    verdict = vc.review(built, vc.Table(values={"v": [1.0, 2.0]},
                                        units={"v": "SAR"}))

    assert verdict.approved is False
    assert verdict.get(vc.MEASURE_AS_LABEL).outcome == vc.FAIL


def test_the_truncated_baseline_case_is_refused_by_the_critic_too():
    case = cc.BY_ID["cc-bad-truncated-baseline"]
    built = vc.Chart(chart=case.attempted_chart, roles=case.semantic_fields,
                     labels=["Contracting", "Real Estate"],
                     series={"coverage": [3.1, 3.3]},
                     units={"coverage": "%"}, axis_starts_at_zero=False,
                     has_accessible_table=True)

    verdict = vc.review(built, vc.Table(values={"coverage": [3.1, 3.3]},
                                        units={"coverage": "%"}))

    assert verdict.approved is False
    assert verdict.get(vc.SCALE).outcome == vc.FAIL


def test_invalid_cases_serialise_with_the_refusal_they_must_produce():
    payload = cc.BY_ID["cc-bad-sankey-without-flow"].to_dict()

    assert payload["invalid"] is True
    assert payload["attempted_chart"] == vg.SANKEY
    assert payload["must_reject"]
    assert payload["preferred_chart"] == vg.MIGRATION_MATRIX


def test_nothing_in_the_library_contains_client_data():
    """A teaching case is a description of a SHAPE. The entities that do
    appear are the governed synthetic names the rest of the factory uses."""
    text = " ".join(str(c.to_dict()) for c in cc.CASES).lower()
    for forbidden in ("api_key", "authorization", "sk-ant", "password",
                      "bearer "):
        assert forbidden not in text
