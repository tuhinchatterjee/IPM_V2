"""
§72-§77 — the deterministic engines an investigation reasons with.

The sentence every one of these modules exists to enforce
---------------------------------------------------------
    "Do not let the LLM decide broad versus concentrated from prose alone."

and its four siblings: do not let it decide persistent, do not let it assign a
materiality band, do not let it assert a contribution that does not reconcile,
and do not let it say anything that is not a registered validated fact.

Each is a place where a model produces a plausible answer every time and
nobody can tell when it is wrong. These tests are about the cases where the
plausible answer and the right answer differ.
"""

from __future__ import annotations

import pytest

from backend.judgment import breadth as br
from backend.judgment import drivers as dr
from backend.judgment import evidence as ev
from backend.judgment import materiality as mt
from backend.judgment import observations as ob
from backend.judgment import persistence as pe


def _fact(fact_id="f1", **over) -> ev.Fact:
    base = dict(
        fact_id=fact_id, fact_type=ev.CHANGE, metric="expected credit loss",
        entity_type="sector", entity_id="contracting",
        entity_name="Contracting", opening_period="Q1 2026",
        closing_period="Q2 2026", opening_value=100.0, closing_value=140.0,
        change=40.0, change_pct=0.4, unit="SAR", source_run_id="run-1",
        validation_status=ev.VALIDATED, evidence_quality=ev.COMPLETE,
        direction=ev.WORSE)
    base.update(over)
    return ev.Fact(**base)


# =============================================== §76 the Evidence Fact Graph


def test_the_narrative_may_use_only_registered_validated_facts():
    graph = ev.Graph()
    graph.add(_fact("good"))
    graph.add(_fact("unchecked", validation_status=ev.UNVALIDATED))
    graph.add(_fact("broken", validation_status=ev.FAILED))

    assert [f.fact_id for f in graph.usable()] == ["good"]
    for fact_id in ("unchecked", "broken"):
        with pytest.raises(ev.NotRegistered):
            graph.cite([fact_id])


def test_an_unvalidated_fact_and_a_failed_one_are_different_states():
    """A fact whose invariant failed is evidence that something is wrong; a
    fact nothing has checked is evidence of nothing. Both are unusable, for
    reasons a reader needs to tell apart."""
    graph = ev.Graph()
    graph.add(_fact("a", validation_status=ev.UNVALIDATED))
    graph.add(_fact("b", validation_status=ev.FAILED))
    assert graph.get("a").validation_status != graph.get("b").validation_status


def test_citing_a_set_with_one_bad_fact_refuses_the_whole_set():
    """A sentence built on four facts of which one is unvalidated is a
    sentence that should not be written, and quietly writing it from the other
    three changes what it says."""
    graph = ev.Graph()
    graph.add(_fact("a"))
    graph.add(_fact("b", validation_status=ev.UNVALIDATED))
    with pytest.raises(ev.NotRegistered):
        graph.cite(["a", "b"])


def test_a_percentage_measure_must_record_percentage_points():
    """"Coverage rose 2%" means two different things, and the fix is to record
    both or neither."""
    graph = ev.Graph()
    graph.add(_fact("pct", metric="ecl coverage", unit="%", change_pct=0.02,
                    change=None))
    assert graph.refused
    assert "percentage points" in graph.refused[0][1]


def test_a_derived_fact_names_what_it_came_from():
    """"ECL rose while coverage fell" is two facts and one claim, and the
    claim is the part that needs its own fact."""
    graph = ev.Graph()
    graph.add(_fact("a"))
    graph.add(_fact("b", metric="ecl coverage", unit="ratio", change=-0.01,
                    change_pct=-0.05))
    orphan = ev.Fact(fact_id="c", fact_type=ev.DERIVED, metric="divergence",
                     value=1.0, validation_status=ev.VALIDATED)
    graph.add(orphan)
    assert any("derived_from" in why for _, why in graph.refused)

    joined = ev.Fact(fact_id="d", fact_type=ev.DERIVED, metric="divergence",
                     value=1.0, validation_status=ev.VALIDATED,
                     derived_from=["a", "b"])
    graph.add(joined)
    assert "d" in graph.facts


def test_a_derived_fact_cannot_cite_a_fact_the_graph_lacks():
    graph = ev.Graph()
    graph.add(ev.Fact(fact_id="d", fact_type=ev.DERIVED, metric="x",
                      value=1.0, validation_status=ev.VALIDATED,
                      derived_from=["nowhere"]))
    assert any("does not hold" in why for _, why in graph.refused)


def test_two_runs_measuring_the_same_thing_fingerprint_alike():
    """So a Trace can show they agree, and so a narrative citing both is
    visibly citing one fact twice."""
    graph = ev.Graph()
    graph.add(_fact("a", source_run_id="run-1"))
    graph.add(_fact("b", source_run_id="run-2"))
    assert len(graph.duplicates()) == 1


def test_direction_is_what_a_movement_means_not_its_sign():
    """A falling DSCR and a rising ECL are both deterioration."""
    assert ev.direction_of(True, 10) == ev.WORSE
    assert ev.direction_of(True, -10) == ev.BETTER
    assert ev.direction_of(False, -10) == ev.WORSE
    assert ev.direction_of(None, 10) == ev.UNKNOWN_DIRECTION


# ================================================ §72 drivers and contributions


def test_a_decomposition_reports_its_residual_whether_or_not_it_is_small():
    """A contribution table that quietly absorbs 0.4% into rounding is a table
    somebody will later find does not tie, and by then it is in a board
    pack."""
    result = dr.decompose("ecl", {"a": 100, "b": 50}, {"a": 130, "b": 45})
    assert result.residual == 0.0
    assert result.reconciles
    assert "residual" in result.to_dict()


def test_a_ratio_has_no_contributions_without_a_governed_method():
    with pytest.raises(dr.NotAdditive, match="not additive"):
        dr.decompose("ecl coverage", {"a": 1}, {"a": 2}, additive=False)

    allowed = dr.decompose("ecl coverage", {"a": 1}, {"a": 2}, additive=False,
                           governed_method="coverage_decomposition")
    assert allowed.limitations


def test_offsets_are_reported_because_a_net_change_hides_them():
    """A total that moved 5 out of 30 adverse and 25 favourable is a different
    portfolio from one that moved 5 out of 5 adverse."""
    quiet = dr.decompose("ecl", {"a": 100, "b": 100}, {"a": 105, "b": 100})
    churning = dr.decompose("ecl", {"a": 100, "b": 100}, {"a": 130, "b": 75})

    assert quiet.change == churning.change == 5
    assert not dr.offsets(quiet)["material_offset"]
    assert dr.offsets(churning)["material_offset"]
    assert dr.offsets(churning)["gross_adverse"] == 30


def test_the_population_effect_is_computed_rather_than_assumed():
    """§71's challenge — did new or exited customers drive it — answered by
    computing the movement twice."""
    effect = dr.population_effect(
        "ecl", {"a": 100, "gone": 40}, {"a": 105, "new": 30})
    assert effect["entered"] == 1
    assert effect["exited"] == 1
    assert effect["matched_change"] == 5
    assert effect["population_change"] == effect["total_change"] - 5


def test_driven_by_is_earned_rather_than_assumed():
    """Below the threshold the answer is a distribution, and calling a
    distribution a driver is the most common overstatement in a credit
    narrative."""
    spread = dr.decompose("ecl", {f"e{i}": 100 for i in range(20)},
                          {f"e{i}": 105 for i in range(20)})
    assert not spread.driven

    two_names = dr.decompose(
        "ecl", {f"e{i}": 100 for i in range(20)},
        {f"e{i}": (200 if i < 2 else 101) for i in range(20)})
    assert two_names.driven


def test_a_favourable_mover_has_a_negative_contribution():
    result = dr.decompose("ecl", {"a": 100}, {"a": 80})
    assert result.contributions[0].contribution == -20
    assert not result.contributions[0].adverse


# ============================================ §73 breadth and concentration


def test_two_names_moving_is_concentrated_and_twenty_is_broad():
    opening = {f"e{i}": 100 for i in range(20)}
    concentrated = dr.decompose(
        "ecl", opening, {f"e{i}": (160 if i < 2 else 102)
                         for i in range(20)})
    broad = dr.decompose("ecl", opening,
                         {f"e{i}": 105 for i in range(20)})

    assert br.assess(concentrated).verdict == br.CONCENTRATED
    assert br.assess(broad).verdict == br.BROAD


def test_too_few_entities_is_undetermined_rather_than_a_guess():
    """Four borrowers cannot show a segment-wide pattern, and a confident
    verdict over four is a verdict about noise."""
    small = dr.decompose("ecl", {"a": 100, "b": 100},
                         {"a": 150, "b": 90})
    verdict = br.assess(small)
    assert verdict.verdict == br.UNDETERMINED
    assert not verdict.determined
    assert "at least" in verdict.reasons[0]


def test_a_few_large_movers_over_a_drift_is_mixed_rather_than_either():
    """A real portfolio shape, not an error. Reporting either half alone would
    be wrong in a way somebody acts on."""
    # Three comparable large movers — jointly two-thirds of the movement, no
    # one of them dominant — over a drift the whole population takes part in.
    opening = {f"e{i}": 100 for i in range(40)}
    closing = {f"e{i}": (300 if i < 3 else 108) for i in range(40)}
    verdict = br.assess(dr.decompose("ecl", opening, closing))
    assert verdict.verdict == br.MIXED
    assert verdict.measures["top_3"] >= br.CONCENTRATED_AT
    assert verdict.measures["top_1"] <= br.BROAD_TOP_AT


def test_the_verdict_names_the_measures_that_decided_it():
    """So a reader can disagree with the measure they think is wrong rather
    than with the conclusion."""
    opening = {f"e{i}": 100 for i in range(20)}
    verdict = br.assess(dr.decompose(
        "ecl", opening, {f"e{i}": (200 if i < 2 else 101)
                         for i in range(20)}))
    assert verdict.reasons
    assert set(verdict.measures) >= {"top_1", "top_3", "hhi", "participation",
                                     "moving", "offsets"}


def test_the_herfindahl_is_computed_over_absolute_contributions():
    """A book where one name moved +50 and another −50 is concentrated, and a
    signed index would call it empty."""
    assert br.herfindahl([50, -50]) == pytest.approx(0.5)
    assert br.herfindahl([1] * 100) == pytest.approx(0.01)
    assert br.herfindahl([]) == 0.0


def test_a_broad_verdict_never_claims_more_than_it_measured():
    verdict = br.assess(dr.decompose("ecl", {f"e{i}": 100 for i in range(20)},
                                     {f"e{i}": 105 for i in range(20)}))
    assert "broad across the population" in verdict.sentence()


# ============================================== §74 persistence and noise


def test_a_two_point_change_is_never_persistent():
    """§74's own sentence. Two points define a line, and a line looks like a
    trend to everybody who sees one."""
    verdict = pe.assess([100, 140])
    assert verdict.verdict == pe.INSUFFICIENT
    assert not verdict.determined
    assert str(pe.MIN_PERIODS) in verdict.sentence()


def test_the_required_history_is_stated_rather_than_implied():
    verdict = pe.assess([100, 140])
    assert verdict.required_periods == pe.MIN_PERIODS
    assert "required" in verdict.reasons[0]


@pytest.mark.parametrize("series,expected", [
    ([10, 11, 12, 13, 14], pe.PERSISTENT),
    ([14, 13, 12, 11, 10], pe.PERSISTENT),
    ([10, 10.2, 9.9, 10.1, 18], pe.SPIKE),
    ([10, 20, 5, 25, 3], pe.VOLATILE),
    ([10, 11, 12, 13, 9], pe.REVERSING),
])
def test_the_five_verdicts_separate_the_series_they_are_for(series, expected):
    assert pe.assess(series).verdict == expected


def test_a_spike_is_a_movement_that_dominates_rather_than_merely_a_big_one():
    """A creeping series whose latest step is slightly bigger than the last
    one is not a spike, and a sigma test alone calls it one."""
    creep = pe.assess([10, 10.1, 10.2, 10.15, 10.3])
    assert creep.verdict == pe.SPIKE
    assert "no run behind it" in creep.reasons[0]

    real = pe.assess([10, 10.2, 9.9, 10.1, 18])
    assert "larger than everything the series did before it" in \
        real.reasons[0]


def test_a_volatile_series_is_caught_by_where_it_ended_not_how_far_it_moved():
    """A series swinging +20, −22, +25 has a perfectly ordinary standard
    deviation relative to its typical movement, which is why §74 lists sign
    consistency separately."""
    verdict = pe.assess([10, 20, 5, 25, 3])
    assert verdict.verdict == pe.VOLATILE
    assert verdict.measures["efficiency"] < pe.EFFICIENCY_AT


def test_the_sentence_names_the_run_rather_than_the_direction():
    """A reader seeing "four consecutive periods" against a chart showing two
    will catch a series handed over in the wrong order."""
    said = pe.assess([10, 11, 12, 13, 14]).sentence()
    assert "consecutive periods" in said


# ================================================== §75 the materiality engine


def test_the_band_comes_from_a_policy_with_named_components():
    found = mt.assess(mt.Inputs(
        absolute_amount=50e6, amount_scale=60e6, relative_movement=0.3,
        portfolio_share=0.09, segment_share=0.4, exposure_affected=800e6,
        portfolio_exposure=4e9, entities_affected=40, population=120,
        concentration=0.3, persistent=True, evidence_quality="COMPLETE"))
    assert found.band in mt.BANDS
    assert set(found.component_scores) == set(mt.WEIGHTS)
    assert found.policy_version


def test_a_risk_appetite_breach_sets_a_floor_the_score_cannot_average_away():
    """The bank has already decided in advance that it cares. A score that
    could average that away would be a policy quietly reversing a policy."""
    tiny = mt.Inputs(absolute_amount=1000, amount_scale=60e6,
                     evidence_quality="COMPLETE")
    assert mt.assess(tiny).band == mt.IMMATERIAL

    breached = mt.assess(mt.Inputs(**{**tiny.__dict__,
                                      "appetite_breach": True}))
    assert breached.band == mt.HIGH
    assert breached.adjusted == "floor"


def test_a_critical_breach_floors_higher_than_an_appetite_breach():
    tiny = {"absolute_amount": 1000, "amount_scale": 60e6,
            "evidence_quality": "COMPLETE"}
    assert mt.assess(mt.Inputs(**tiny, critical_breach=True)).band == \
        mt.CRITICAL


def test_thin_evidence_caps_the_band_rather_than_reducing_it():
    """Reducing would say the finding is smaller than it is; capping says we
    cannot yet claim it is as large as it looks."""
    large = dict(absolute_amount=50e6, amount_scale=60e6,
                 relative_movement=0.3, portfolio_share=0.09,
                 segment_share=0.4, exposure_affected=800e6,
                 portfolio_exposure=4e9, entities_affected=40,
                 population=120, concentration=0.3, persistent=True)
    complete = mt.assess(mt.Inputs(**large, evidence_quality="COMPLETE"))
    thin = mt.assess(mt.Inputs(**large, evidence_quality="THIN"))

    assert thin.score == complete.score, "the score is unchanged"
    assert mt.BANDS.index(thin.band) < mt.BANDS.index(complete.band)
    assert thin.adjusted == "cap"
    assert "cap, not a reduction" in " ".join(thin.reasons)


def test_an_unvalidated_finding_cannot_be_material():
    found = mt.assess(mt.Inputs(absolute_amount=50e6, amount_scale=60e6,
                                portfolio_share=0.5, validated=False))
    assert mt.BANDS.index(found.band) <= mt.BANDS.index(mt.LOW)


def test_an_unmeasurable_finding_says_so_rather_than_scoring_low():
    """"Immaterial" and "we could only measure two of nine things" are
    different findings and a reader needs to tell them apart."""
    found = mt.assess(mt.Inputs(absolute_amount=1000, amount_scale=60e6))
    assert "components could be measured" in " ".join(found.reasons)


def test_what_a_model_is_given_cannot_be_used_to_choose_a_band():
    """§75: it may explain the result; it may not assign it."""
    found = mt.assess(mt.Inputs(absolute_amount=50e6, amount_scale=60e6))
    given = mt.explainable(found)
    assert given["band"] == found.band
    assert "do not assign a different one" in given["instruction"]
    assert "weights" not in given


# ============================================== §77 the Observation Engine


def _graph() -> ev.Graph:
    graph = ev.Graph()
    graph.add(_fact("f1"))
    graph.add(_fact("f2", metric="days past due", entity_id="contracting",
                    change=5.0, change_pct=0.2, unit="days"))
    return graph


def test_every_type_section_77_names_is_declared():
    required = {
        "LEVEL", "CHANGE", "RANK", "TREND", "PERSISTENCE", "CONCENTRATION",
        "BREADTH", "DRIVER", "OFFSET", "EXCEPTION", "THRESHOLD_BREACH",
        "MIGRATION", "ASSOCIATION", "CONTRADICTION", "UNCERTAINTY",
        "LIMITATION", "NEXT_STEP", "NO_MATCH", "UNAVAILABLE"}
    assert required == set(ob.TYPES)


def test_an_observation_that_asserts_something_must_cite_a_fact():
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, slots={"metric": "ECL"}), graph)
    assert any("must cite the facts" in why for _, why in found.refused)


def test_a_contradiction_between_one_fact_is_not_a_contradiction():
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CONTRADICTION, facts=["f1"],
                      slots={"first": "a", "second": "b"}), graph)
    assert any("one fact cannot be one" in why for _, why in found.refused)


def test_an_observation_about_the_analysis_needs_no_facts():
    """A fact requirement on a limitation would force somebody to invent
    one."""
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.LIMITATION,
                      slots={"detail": "collateral data is 12% incomplete"}),
              graph)
    assert found.refused == []
    assert found.observations[0].confidence_from_evidence == 1.0


def test_a_template_cannot_assert_more_than_its_slots():
    """A model handed the same inputs writes "driven by deterioration in the
    construction sector", and three of those claims have no fact behind
    them."""
    graph = _graph()
    found = ob.Set()
    made = ob.make("o1", ob.CHANGE, facts=["f1"],
                   slots={"metric": "ECL", "entity": "Contracting",
                          "change": "+40", "opening": "Q1", "closing": "Q2"})
    found.add(made, graph)
    assert made.render() == ("ECL for Contracting moved +40 between Q1 and "
                             "Q2.")
    assert set(made.slot_names()) == set(made.slots)


def test_a_missing_slot_renders_visibly_rather_than_vanishing():
    """A sentence with a hole in it is better than one that reads smoothly and
    means something else."""
    made = ob.Observation(statement_template="{a} and {b}", slots={"a": "x"})
    assert "[b unavailable]" in made.render()


def test_confidence_comes_from_the_evidence_and_nowhere_else():
    graph = ev.Graph()
    graph.add(_fact("solid", evidence_quality=ev.COMPLETE))
    graph.add(_fact("thin", metric="dpd", evidence_quality=ev.THIN,
                    change=2.0, change_pct=0.1))

    strong = ob.make("o1", ob.CHANGE, facts=["solid"],
                     slots={"metric": "a", "entity": "b", "change": "c",
                            "opening": "d", "closing": "e"})
    weak = ob.make("o2", ob.CHANGE, facts=["thin"],
                   slots={"metric": "a", "entity": "b", "change": "c",
                          "opening": "d", "closing": "e"})
    found = ob.Set()
    found.add(strong, graph)
    found.add(weak, graph)
    assert strong.confidence_from_evidence == 1.0
    assert weak.confidence_from_evidence < 0.5


def test_a_limitation_comes_early_whatever_its_materiality():
    """A reader who does not know the data is incomplete will misread
    everything under it."""
    graph = _graph()
    found = ob.Set()
    rank = ob.make("rank", ob.RANK, facts=["f1"], materiality=mt.CRITICAL,
                   slots={"entity": "a", "rank": "1", "total": "20",
                          "metric": "ECL"})
    limitation = ob.make("lim", ob.LIMITATION, materiality=mt.LOW,
                         slots={"detail": "12% of collateral is missing"})
    found.add(rank, graph)
    found.add(limitation, graph)
    assert [o.observation_id for o in found.ordered()][0] == "lim"


def test_materiality_shifts_within_a_type_rather_than_across_types():
    """A reader needs the movement before the league table, even when the
    league table is the alarming part."""
    graph = _graph()
    found = ob.Set()
    change = ob.make("chg", ob.CHANGE, facts=["f1"], materiality=mt.LOW,
                     slots={"metric": "a", "entity": "b", "change": "c",
                            "opening": "d", "closing": "e"})
    rank = ob.make("rnk", ob.RANK, facts=["f1"], materiality=mt.CRITICAL,
                   slots={"entity": "a", "rank": "1", "total": "2",
                          "metric": "ECL"})
    found.add(change, graph)
    found.add(rank, graph)
    assert [o.observation_id for o in found.ordered()] == ["chg", "rnk"]


def test_a_withheld_observation_is_kept_rather_than_dropped():
    """One that was found and withheld is a different thing from one that was
    never found."""
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.LIMITATION, slots={"detail": "x"},
                      status=ob.WITHHELD), graph)
    assert found.ordered() == []
    assert len(found.to_dict()["withheld"]) == 1


def test_every_type_has_a_reviewed_template():
    for kind in ob.TYPES:
        assert kind in ob.TEMPLATES
        assert "{" in ob.TEMPLATES[kind]
