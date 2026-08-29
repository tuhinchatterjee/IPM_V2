"""
§78-§84 — what may be said, and what may not be explained away.

The two sentences these tests exist for
---------------------------------------
    §78: "Do not force a section when evidence is insufficient; state
          insufficient evidence."
    §84: "Never invent a plausible story merely to avoid UNRESOLVED."

Both describe the same failure from opposite ends. A contract with nine
required sections produces nine sections, three of them invented; a
contradiction with no explanation produces an explanation, and it will be
fluent and economically sensible and supported by nothing. The tests below
are mostly about the cases where the plausible output and the honest one
differ, because those are the only cases where any of this machinery earns
its keep.
"""

from __future__ import annotations

import pytest

from backend.judgment import contradictions as cd
from backend.judgment import evidence as ev
from backend.judgment import interpretation as it
from backend.judgment import materiality as mt
from backend.judgment import observations as ob


def _fact(fact_id="f1", **over) -> ev.Fact:
    base = dict(
        fact_id=fact_id, fact_type=ev.CHANGE, metric="expected credit loss",
        entity_type="sector", entity_id="contracting",
        entity_name="Contracting", opening_period="Q1 2026",
        closing_period="Q2 2026", opening_value=100.0, closing_value=140.0,
        change=40.0, unit="SAR", source_run_id="run-1",
        validation_status=ev.VALIDATED, evidence_quality=ev.COMPLETE,
        direction=ev.WORSE)
    base.update(over)
    return ev.Fact(**base)


def _graph(*facts: ev.Fact) -> ev.Graph:
    graph = ev.Graph()
    for fact in facts or (_fact(),):
        graph.add(fact)
    return graph


def _signal(signal_id="s1", **over) -> cd.Signal:
    base = dict(
        signal_id=signal_id, metric="expected credit loss",
        entity="Contracting", population="matched", opening_period="Q1 2026",
        closing_period="Q2 2026", movement=40.0, direction=ev.WORSE,
        timing_frequency="monthly", grain="sector",
        evidence_quality=ev.COMPLETE, validation=ev.VALIDATED)
    base.update(over)
    return cd.Signal(**base)


# ===================================================== §78 the nine sections


def test_the_contract_has_exactly_the_nine_sections_section_78_names():
    assert len(it.SECTIONS) == 9
    assert it.SECTIONS[0] == it.BOTTOM_LINE
    # Every section has a stated purpose and a stated set of feeders. A
    # section nobody can say the purpose of is a heading.
    for section_id in it.SECTIONS:
        assert it.PURPOSE[section_id].strip()
        assert it.FEEDS[section_id]


def test_a_section_with_no_observations_of_its_kinds_is_insufficient():
    """§78's second sentence. The failure it prevents is a DRIVERS section
    written because the template has one, from an analysis that never
    decomposed anything."""
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)

    contract = it.build(found, periods=4)

    drivers = contract.get(it.DRIVERS)
    assert drivers.state == it.INSUFFICIENT
    assert drivers.observation_ids == []
    assert "driver" in drivers.note
    # And the caller cannot talk it into PRESENT, because a PRESENT section's
    # content is its observation ids and there are none.
    assert it.DRIVERS in [s.id for s in contract.insufficient]


def test_insufficient_and_not_applicable_are_different_answers():
    """INSUFFICIENT means we looked and could not tell. NOT_APPLICABLE means
    the question does not have that shape. Reporting a single-period level
    question as having insufficient evidence for persistence would be
    reporting a gap that is not one."""
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.LEVEL, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "period": "Q2 2026", "value": 140},
                      materiality=mt.HIGH), graph)

    single = it.build(found, periods=1)
    assert single.get(it.PERSISTENCE).state == it.NOT_APPLICABLE
    assert "single period" in single.get(it.PERSISTENCE).note

    many = it.build(found, periods=6)
    assert many.get(it.PERSISTENCE).state == it.INSUFFICIENT


def test_a_closed_question_has_no_breadth_and_no_follow_up_section():
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.LEVEL, facts=["f1"],
                      slots={"metric": "EAD", "entity": "Contracting",
                             "period": "Q2 2026", "value": 140},
                      materiality=mt.MODERATE), graph)

    closed = it.build(found, periods=1, question_is_open=False)
    assert closed.get(it.BREADTH).state == it.NOT_APPLICABLE
    assert closed.get(it.NEXT_BEST).state == it.NOT_APPLICABLE

    opened = it.build(found, periods=1, question_is_open=True)
    assert opened.get(it.BREADTH).state == it.INSUFFICIENT
    assert opened.get(it.NEXT_BEST).state == it.INSUFFICIENT


def test_no_bottom_line_is_an_abstention_not_an_insufficient_section():
    """There is no sentence that stands in for a missing answer. A contract
    that reported "insufficient evidence for the bottom line" would let an
    answer be shown with a hole where the answer goes, surrounded by
    materiality and limitations that read like analysis."""
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.LIMITATION,
                      slots={"detail": "covenant data is missing for 40% of "
                                       "the segment"},
                      materiality=mt.HIGH), graph)

    contract = it.build(found, periods=4)

    assert contract.abstain is True
    assert "no bottom line" in contract.abstain_reason.lower()


def test_a_direct_answering_observation_lifts_the_abstention():
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.RANK, facts=["f1"],
                      slots={"entity": "Contracting", "rank": "1",
                             "total": "8", "metric": "ECL coverage"},
                      materiality=mt.HIGH), graph)

    contract = it.build(found, periods=1)

    assert contract.abstain is False
    assert contract.get(it.BOTTOM_LINE).state == it.PRESENT
    assert contract.get(it.BOTTOM_LINE).observation_ids == ["o1"]


def test_an_empty_observation_set_abstains_rather_than_producing_a_shell():
    contract = it.build(ob.Set(), periods=4)

    assert contract.abstain is True
    assert contract.present == []


def test_every_section_state_is_one_of_the_three():
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)

    contract = it.build(found, periods=2)
    assert {s.state for s in contract.sections} <= set(it.STATES)
    assert len(contract.sections) == len(it.SECTIONS)


# ===================================================== §79 the interpretation pack


def test_the_pack_carries_exactly_what_section_79_lists():
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)
    contract = it.build(found, periods=2)

    built = it.pack("What moved?", found, graph, contract)

    assert set(built.to_dict()) == set(it.PACK_FIELDS)
    # Result rows are NOT in the whitelist. A model given a thousand rows will
    # find a pattern in them, and the pattern will not have been computed by
    # anything.
    assert "result_rows" not in built.to_dict()
    assert "rows" not in built.to_dict()


def test_the_pack_carries_only_the_facts_the_observations_cite():
    graph = _graph(_fact("f1"), _fact("f2", entity_name="Real Estate"),
                   _fact("f3", entity_name="Manufacturing"))
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)

    built = it.pack("q", found, graph, it.build(found, periods=2))

    assert [f["fact_id"] for f in built.facts] == ["f1"]


def test_raw_rows_are_permitted_and_recorded_where_a_trace_can_see_them():
    """§79 permits raw tables "unless necessary". Including them is not
    forbidden; doing it invisibly is."""
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)

    built = it.pack("q", found, graph, it.build(found, periods=2),
                    result_rows=[{"sector": "Contracting"}] * 900)

    assert built.answer_contract["raw_rows_included"] == 900


def test_the_length_cap_is_a_cap_and_travels_with_the_pack():
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)
    built = it.pack("q", found, graph, it.build(found, periods=2),
                    max_words=60, locale="ar")

    assert built.max_words == 60
    assert built.locale == "ar"


# ========================================================= the grounding check


def _grounded_pack() -> tuple[it.Pack, ob.Set, ev.Graph]:
    graph = _graph(_fact("f1"))
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.HIGH), graph)
    return it.pack("q", found, graph, it.build(found, periods=2)), found, graph


def test_a_figure_the_pack_never_carried_is_reported_as_ungrounded():
    """Either the model computed it — which it must not do — or it copied a
    figure wrongly. Both are the same defect from the reader's side."""
    built, _, _ = _grounded_pack()

    clean = it.check("ECL for Contracting moved 40 between Q1 2026 and "
                     "Q2 2026.", built)
    assert clean.ungrounded == []
    assert clean.ok is True

    invented = it.check("ECL for Contracting moved 40, and coverage now "
                        "stands at 17.4%.", built)
    # Reported exactly as it appears in the prose, so a reviewer can find it.
    assert invented.ungrounded == ["17.4%"]
    assert invented.ok is False


def test_years_and_small_counts_do_not_need_a_citation():
    """A grounding check that flagged "all three sectors" and "Q2 2026" gets
    switched off, and then nothing is checked at all."""
    built, _, _ = _grounded_pack()

    result = it.check("Across all 3 sectors, ECL moved 40 between Q1 2026 and "
                      "Q2 2026.", built)

    assert result.ungrounded == []


def test_a_figure_matches_however_it_is_formatted():
    """Deliberately loose. The check is for figures that appeared from
    nowhere, and a stricter comparison would fail on formatting and teach
    everybody to disable it."""
    built, _, _ = _grounded_pack()

    for written in ("40", "40.0", "+40", "40%"):
        assert it.check(f"ECL moved {written}.", built).ungrounded == []


def test_an_over_length_narrative_fails_the_check():
    built, _, _ = _grounded_pack()
    built.max_words = 10

    result = it.check(" ".join(["word"] * 40), built)

    assert result.over_length is True
    assert result.words == 40
    assert result.ok is False


def test_using_half_a_contradiction_counts_as_not_using_it():
    """The specific failure of reporting only the reassuring direction. A
    contradiction observation exists to prevent exactly that, so mentioning
    one side of it is not using it."""
    graph = _graph(_fact("f1"), _fact("f2", metric="internal rating",
                                      direction=ev.BETTER))
    found = ob.Set()
    found.add(ob.make("o3", ob.CONTRADICTION, facts=["f1", "f2"],
                      slots={"first": "expected credit loss",
                             "second": "internal rating"},
                      materiality=mt.CRITICAL), graph)
    built = it.pack("q", found, graph, it.build(found, periods=2))

    one_side = it.check("Expected credit loss rose over the quarter.", built)
    assert one_side.unused == ["o3"]

    both = it.check("Expected credit loss rose while the internal rating "
                    "improved.", built)
    assert both.unused == []


def test_an_immaterial_observation_the_narrative_skips_is_not_reported():
    """An answer is allowed to be shorter than its evidence. Only the high
    and critical observations are worth telling somebody were ignored."""
    graph = _graph()
    found = ob.Set()
    found.add(ob.make("o1", ob.CHANGE, facts=["f1"],
                      slots={"metric": "ECL", "entity": "Contracting",
                             "change": 40, "opening": "Q1 2026",
                             "closing": "Q2 2026"},
                      materiality=mt.LOW), graph)
    built = it.pack("q", found, graph, it.build(found, periods=2))

    assert it.check("Nothing material moved.", built).unused == []


# ================================================== §81 normalised signals


def test_a_signal_is_usable_only_when_validated():
    assert _signal().usable is True
    assert _signal(validation=ev.UNVALIDATED).usable is False
    assert _signal(validation=ev.FAILED).usable is False


def test_contradiction_is_decided_in_risk_terms_not_by_sign():
    """Rising ECL and falling DSCR both mean deterioration, and a sign
    comparison calls that a contradiction. Rising ECL against an improving
    rating IS one, and a sign comparison misses it."""
    worse_ecl = _signal("ecl", metric="expected credit loss", movement=40.0,
                        direction=ev.WORSE)
    worse_dscr = _signal("dscr", metric="DSCR", movement=-0.4,
                         direction=ev.WORSE)
    better_rating = _signal("rating", metric="internal rating", movement=-0.3,
                            direction=ev.BETTER)

    assert cd.Pair(worse_ecl, worse_dscr).contradictory is False
    assert cd.Pair(worse_ecl, better_rating).contradictory is True


def test_a_flat_signal_that_crossed_no_threshold_contradicts_a_worsening_one():
    """A classification that has not moved and a measure that moved without
    crossing anything are the same observation seen from two sides — and the
    pair is worth diagnosing rather than dismissing."""
    worse = _signal("ecl", direction=ev.WORSE)
    flat = _signal("stage", metric="IFRS 9 stage", direction=ev.FLAT,
                   threshold_status="not_crossed")
    crossed = _signal("stage2", metric="IFRS 9 stage", direction=ev.FLAT,
                      threshold_status="crossed")

    assert cd.Pair(worse, flat).contradictory is True
    assert cd.Pair(worse, crossed).contradictory is False


def test_detect_ignores_unvalidated_signals():
    """An unvalidated signal disagreeing with a validated one is not a
    contradiction in the data — it is a contradiction between a measurement
    and a guess, and diagnosing it would be diagnosing the guess."""
    signals = [_signal("ecl", direction=ev.WORSE),
               _signal("rating", metric="internal rating", direction=ev.BETTER,
                       validation=ev.UNVALIDATED)]

    assert cd.detect(signals) == []

    signals[1].validation = ev.VALIDATED
    assert len(cd.detect(signals)) == 1


def test_detect_finds_every_disagreeing_pair():
    signals = [_signal("ecl", metric="ECL", direction=ev.WORSE),
               _signal("dpd", metric="DPD", direction=ev.WORSE),
               _signal("rating", metric="internal rating",
                       direction=ev.BETTER)]

    pairs = cd.detect(signals)

    assert len(pairs) == 2
    assert all("rating" in (p.left.signal_id, p.right.signal_id)
               for p in pairs)


# ====================================================== §82 the taxonomy


def test_every_explanation_says_what_it_claims():
    """A taxonomy whose entries are only labels is a taxonomy people file
    things under by vibe."""
    for explanation in cd.EXPLANATIONS:
        assert cd.MEANS[explanation].strip()
        assert len(cd.MEANS[explanation]) > 30


def test_timing_and_threshold_lag_come_first_because_they_come_first_in_reality():
    assert cd.EXPLANATIONS[0] == cd.TIMING_LAG
    assert cd.EXPLANATIONS[1] == cd.THRESHOLD_LAG
    assert cd.CHECK_IDS.index("update_frequency") < \
        cd.CHECK_IDS.index("concentration")


def test_unresolved_and_multiple_are_both_in_the_taxonomy():
    """§82 says not to force one explanation when several remain possible,
    which needs somewhere for "several" to go."""
    assert cd.TRUE_CONTRADICTION in cd.EXPLANATIONS
    assert cd.MULTIPLE in cd.EXPLANATIONS


# ====================================================== §83 the fifteen checks


def test_there_are_fifteen_checks_each_with_a_question_and_a_meaning():
    assert len(cd.CHECKS) == 15
    assert len(set(cd.CHECK_IDS)) == 15
    for check_id in cd.CHECK_IDS:
        assert cd.CHECK_LABEL[check_id].strip()
        assert cd.CHECK_QUESTION[check_id].endswith("?")
        assert cd.SUPPORTS[check_id] in cd.EXPLANATIONS + (
            cd.NOT_A_CONTRADICTION,)


def test_a_check_that_fired_must_say_what_it_found():
    """A diagnosis that explains a contradiction without evidence is exactly
    the story §84 forbids, written in the shape of a diagnostic."""
    diagnosis = cd.diagnose(cd.Pair(_signal("a"), _signal("b")))

    with pytest.raises(ValueError):
        diagnosis.record("update_frequency", cd.FIRED)

    diagnosis.record("update_frequency", cd.FIRED,
                     detail="rating refreshes annually, DPD daily")
    assert diagnosis.fired[0].supports == cd.TIMING_LAG


def test_a_check_outside_the_fifteen_is_refused():
    diagnosis = cd.diagnose(cd.Pair(_signal("a"), _signal("b")))

    with pytest.raises(KeyError):
        diagnosis.record("vibes", cd.CLEAR)
    with pytest.raises(ValueError):
        diagnosis.record("period_alignment", "PROBABLY_FINE")


def test_an_unrun_check_is_not_a_clear_one():
    """§83: "Record every check." A diagnosis that ran four checks and
    concluded EXPLAINED has concluded from four checks."""
    diagnosis = cd.diagnose(cd.Pair(_signal("a"), _signal("b")))
    diagnosis.record("period_alignment", cd.CLEAR)

    assert diagnosis.complete is False
    assert len(diagnosis.not_run) == 14
    assert "concentration" in diagnosis.not_run


def test_a_check_that_only_supports_when_it_fires():
    diagnosis = cd.diagnose(cd.Pair(_signal("a"), _signal("b")))
    cleared = diagnosis.record("concentration", cd.CLEAR)

    assert cleared.supports == ""


# ======================================================== §84 the outcomes


def _run_all(diagnosis: cd.Diagnosis, *, fired: dict[str, str] | None = None,
             skip: tuple[str, ...] = ()) -> cd.Diagnosis:
    fired = fired or {}
    for check_id in cd.CHECK_IDS:
        if check_id in skip:
            continue
        if check_id in fired:
            diagnosis.record(check_id, cd.FIRED, detail=fired[check_id])
        else:
            diagnosis.record(check_id, cd.CLEAR)
    return diagnosis


def test_fifteen_clear_checks_produce_unresolved_not_a_story():
    """The sentence the whole module exists for. Fifteen clear diagnostics
    have a plausible narrative available — lag is always available — and the
    right answer is that somebody needs to look."""
    pair = cd.Pair(_signal("ecl", metric="ECL", direction=ev.WORSE),
                   _signal("rating", metric="internal rating",
                           direction=ev.BETTER))
    diagnosis = cd.conclude(_run_all(cd.diagnose(pair)))

    assert diagnosis.outcome == cd.UNRESOLVED
    assert diagnosis.explanations == [cd.TRUE_CONTRADICTION]
    assert diagnosis.review_candidates
    assert "genuinely disagree" in diagnosis.statement()


def test_too_few_checks_is_data_insufficient_rather_than_a_conclusion():
    pair = cd.Pair(_signal("a", metric="ECL"), _signal("b", metric="rating"))
    diagnosis = cd.diagnose(pair)
    for check_id in cd.CHECK_IDS[:6]:
        diagnosis.record(check_id, cd.CLEAR)
    diagnosis.record("update_frequency", cd.FIRED,
                     detail="rating is annual, DPD daily")

    cd.conclude(diagnosis)

    assert diagnosis.outcome == cd.DATA_INSUFFICIENT
    assert diagnosis.next_analysis
    assert "Too few checks" in diagnosis.statement()


def test_min_checks_is_two_thirds_of_the_sequence():
    assert cd.MIN_CHECKS == 10
    assert cd.MIN_CHECKS < len(cd.CHECK_IDS)


def test_one_explanation_and_a_complete_sequence_is_explained():
    pair = cd.Pair(_signal("ecl", metric="ECL", direction=ev.WORSE),
                   _signal("rating", metric="internal rating",
                           direction=ev.BETTER))
    diagnosis = cd.conclude(_run_all(
        cd.diagnose(pair),
        fired={"update_frequency": "the rating is reviewed annually and was "
                                   "last reviewed 11 months ago"}))

    assert diagnosis.outcome == cd.EXPLAINED
    assert diagnosis.explanations == [cd.TIMING_LAG]
    assert cd.MEANS[cd.TIMING_LAG] in diagnosis.statement()


def test_one_explanation_with_checks_still_unrun_is_only_partially_explained():
    """An explanation that survives ten checks and is untested against five is
    a hypothesis that has done well, not a conclusion."""
    pair = cd.Pair(_signal("ecl", metric="ECL", direction=ev.WORSE),
                   _signal("rating", metric="internal rating",
                           direction=ev.BETTER))
    diagnosis = cd.conclude(_run_all(
        cd.diagnose(pair),
        fired={"update_frequency": "the rating is reviewed annually"},
        skip=("controls", "overlay", "new_exited")))

    assert diagnosis.outcome == cd.PARTIALLY_EXPLAINED
    assert diagnosis.explanations == [cd.TIMING_LAG]
    assert diagnosis.next_analysis


def test_several_surviving_explanations_are_not_forced_into_one():
    """§82: "Do not force one explanation when several remain possible." The
    tempting output here is the strongest of the two; the honest one names
    both and says what would distinguish them."""
    pair = cd.Pair(_signal("ecl", metric="ECL", direction=ev.WORSE),
                   _signal("rating", metric="internal rating",
                           direction=ev.BETTER))
    diagnosis = cd.conclude(_run_all(
        cd.diagnose(pair),
        fired={"update_frequency": "the rating is annual",
               "concentration": "three names carry 71% of the ECL movement"}))

    assert diagnosis.outcome == cd.PARTIALLY_EXPLAINED
    assert cd.MULTIPLE in diagnosis.explanations
    assert cd.TIMING_LAG in diagnosis.explanations
    assert cd.CONCENTRATION_EFFECT in diagnosis.explanations
    assert diagnosis.next_analysis


def test_a_directional_semantics_hit_means_it_was_never_a_contradiction():
    """The signals do not in fact disagree — one of them was read backwards.
    That is not an explanation of a contradiction, it is the absence of
    one, and filing it under an explanation would leave the taxonomy
    recording contradictions that never existed."""
    pair = cd.Pair(_signal("ecl", metric="ECL", direction=ev.WORSE),
                   _signal("cure", metric="cure rate", direction=ev.BETTER))
    diagnosis = cd.conclude(_run_all(
        cd.diagnose(pair),
        fired={"directional_semantics": "a rising cure rate and a rising ECL "
                                        "both follow from more accounts "
                                        "entering and leaving delinquency"}))

    assert diagnosis.outcome == cd.NOT_A_CONTRADICTION
    assert diagnosis.explanations == []
    assert "do not in fact disagree" in diagnosis.statement()


def test_the_statement_always_says_how_many_checks_ran():
    """A confident conclusion from four of fifteen checks should look like
    what it is."""
    pair = cd.Pair(_signal("ecl", metric="ECL", direction=ev.WORSE),
                   _signal("rating", metric="internal rating",
                           direction=ev.BETTER))
    diagnosis = cd.conclude(_run_all(cd.diagnose(pair)))

    assert "15 of 15 diagnostic checks ran" in diagnosis.statement()


def test_the_diagnosis_serialises_with_its_unrun_checks_visible():
    pair = cd.Pair(_signal("ecl", metric="ECL", direction=ev.WORSE),
                   _signal("rating", metric="internal rating",
                           direction=ev.BETTER))
    diagnosis = cd.diagnose(pair)
    diagnosis.record("period_alignment", cd.CLEAR)
    cd.conclude(diagnosis)

    payload = diagnosis.to_dict()

    assert payload["complete"] is False
    assert len(payload["not_run"]) == 14
    assert payload["outcome"] == cd.DATA_INSUFFICIENT
    assert payload["version"] == cd.CONTRADICTION_VERSION


def test_an_outcome_is_always_one_of_the_five():
    pair = cd.Pair(_signal("a"), _signal("b"))
    assert cd.diagnose(pair).outcome in cd.OUTCOMES
    assert cd.conclude(cd.diagnose(pair)).outcome in cd.OUTCOMES
