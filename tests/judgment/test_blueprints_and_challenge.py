"""
§66-§71 — what an investigation is going to look at, and what it asks its own
conclusion before saying it.

The failure this whole group prevents
--------------------------------------
Not wrong analysis. INCOMPLETE analysis that reads as complete because nothing
in the answer says what was skipped. A model asked "what is going on in
Contracting?" checks whatever the question mentioned; a blueprint states the
sixteen things a competent analyst would check, and §68's four conditions make
every omission visible.
"""

from __future__ import annotations

import pytest

from backend.judgment import blueprints as bp
from backend.judgment import hypotheses as hy
from backend.judgment import materiality as mt

# ================================================= §66, §67 the library


def test_every_family_section_67_names_has_a_blueprint():
    required = {
        "PORTFOLIO_HEALTH_REVIEW", "SEGMENT_DETERIORATION",
        "BORROWER_DEEP_DIVE", "IFRS9_ECL_MOVEMENT",
        "ECL_CHANGE_DECOMPOSITION", "STAGE_MIGRATION", "RATING_MIGRATION",
        "DPD_MIGRATION", "CONCENTRATION", "EARLY_WARNING",
        "COVENANT_AND_COLLATERAL_DETERIORATION", "FINANCIAL_DETERIORATION",
        "CONTRADICTORY_SIGNALS", "RISK_APPETITE", "STRESS_SCENARIO",
        "VINTAGE_COHORT", "DATA_QUALITY_RELATIONSHIP_INVESTIGATION",
        "MODEL_METHOD_PERFORMANCE_REVIEW",
        "CLIENT_DEMO_EXECUTIVE_PORTFOLIO_REVIEW"}
    assert required == set(bp.FAMILIES)
    assert required == set(bp.BY_FAMILY)


def test_every_blueprint_states_mandatory_and_optional_objectives():
    """§67: "Each blueprint must state mandatory and optional objectives."
    Deciding which cannot be dropped is the judgement; anybody can list
    sixteen things to look at."""
    for blueprint in bp.LIBRARY:
        assert blueprint.required_objectives, blueprint.blueprint_id
        assert all(o.mandatory for o in blueprint.required_objectives)
        assert all(not o.mandatory for o in blueprint.optional_objectives)


def test_every_blueprint_carries_the_universal_validations():
    """Four ways an investigation is wrong in a way nobody can see from its
    output. Not a per-blueprint choice."""
    for blueprint in bp.LIBRARY:
        assert set(bp.UNIVERSAL_VALIDATIONS) <= \
            set(blueprint.mandatory_validations), blueprint.blueprint_id


def test_every_blueprint_says_when_it_may_stop():
    """Without stopping rules an open investigation runs until a budget stops
    it, and a budget is not an analytical judgement."""
    for blueprint in bp.LIBRARY:
        assert blueprint.stopping_rules
        assert blueprint.minimum_evidence >= 1


def test_only_approved_or_system_validated_blueprints_reach_production():
    """§66. A blueprint decides what gets looked at, so an unreviewed one
    decides what gets missed."""
    assert bp.USABLE == {bp.APPROVED, bp.SYSTEM_VALIDATED}
    for blueprint in bp.usable():
        assert blueprint.review_status in bp.USABLE

    draft = bp.Blueprint(blueprint_id="x", review_status=bp.DRAFT)
    assert not draft.usable
    retired = bp.Blueprint(blueprint_id="y", review_status=bp.APPROVED,
                           status=bp.RETIRED)
    assert not retired.usable


def test_a_blueprint_survives_a_round_trip():
    original = bp.SEGMENT_BLUEPRINT
    again = bp.Blueprint.from_dict(original.to_dict())
    assert again.to_dict() == original.to_dict()
    assert bp.fingerprint(again) == original.fingerprint


def test_both_scope_is_spelled_out_rather_than_abbreviated():
    """"Both" almost always means "the same objectives with different grain,
    vocabulary and data", and one record cannot hold two of those."""
    assert bp.BOTH == "BOTH_AS_SEPARATE_APPLICABILITY_RECORDS"


# ===================================================== §68 the segment case


def test_the_segment_blueprint_considers_what_section_68_lists():
    """§68 writes out seventeen branches. Every one has to be somewhere."""
    ids = {o.id for o in bp.SEGMENT_BLUEPRINT.objectives}
    assert {"exposure", "concentration", "rating_distribution",
            "stage_distribution", "ecl_movement", "parameters", "delinquency",
            "financials", "utilisation", "covenants", "collateral",
            "population", "contributors", "breadth", "persistence",
            "data_quality", "challenge", "next"} <= ids


def test_the_four_things_a_segment_answer_is_wrong_without_are_mandatory():
    """What moved, how much of the book it touches, whether it is a few names
    or the segment, and whether it is a trend or a quarter."""
    required = {o.id for o in bp.SEGMENT_BLUEPRINT.required_objectives}
    assert required == {"exposure", "ecl_movement", "breadth", "persistence"}


def test_an_optional_branch_is_omitted_only_with_a_recorded_reason():
    """§68's four conditions. An omission with no reason is a branch that is
    missing rather than omitted."""
    request = bp.Request(
        question="What is going on in Contracting?", subject="sector",
        datasets_available=("portfolio_facility", "ifrs9_staging"),
        broad=True, periods=2)
    selection = bp.select(request)

    assert selection.omitted_objectives
    for objective_id in selection.omitted_objectives:
        assert selection.omission_reasons[objective_id]
        assert "not available" in selection.omission_reasons[objective_id]


def test_an_available_optional_branch_is_kept():
    request = bp.Request(
        question="What is going on in Contracting?", subject="sector",
        datasets_available=tuple(
            bp.SEGMENT_BLUEPRINT.required_data_capabilities
            + bp.SEGMENT_BLUEPRINT.optional_data_capabilities),
        broad=True, periods=2)
    selection = bp.select(request)
    assert selection.omitted_objectives == []


def test_a_mandatory_objective_is_never_omitted_it_makes_the_run_incomplete():
    """§68 permits omitting an OPTIONAL branch. A mandatory one whose data is
    missing makes the investigation incomplete, and saying so is the whole
    difference between an honest short answer and a confident one."""
    request = bp.Request(question="What is going on in Contracting?",
                         subject="sector",
                         datasets_available=("portfolio_facility",))
    blocked = bp.incomplete(bp.SEGMENT_BLUEPRINT, request)
    assert "ecl_movement" in blocked

    selection = bp.select(request)
    assert set(selection.required_objectives) == {
        o.id for o in bp.SEGMENT_BLUEPRINT.required_objectives}
    assert not set(blocked) & set(selection.omitted_objectives)


# ========================================================= §69 selection


def test_selection_reads_twelve_signals_not_only_keywords():
    """§69: "Do not choose solely from keywords." A question mentioning ECL
    might be a data question, a methodology question, or a concentration
    question that happens to use ECL as its measure."""
    assert len(bp.SELECTION_WEIGHTS) == 12
    assert bp.SELECTION_WEIGHTS["triggers"] < sum(
        v for k, v in bp.SELECTION_WEIGHTS.items() if k != "triggers")


def test_a_deterioration_question_selects_the_segment_blueprint():
    selection = bp.select(bp.Request(
        question="Something looks wrong in Contracting — what is going on?",
        capability="ANALYSIS", subject="sector",
        concepts=("expected credit loss",),
        datasets_available=("portfolio_facility", "ifrs9_staging"),
        broad=True, periods=2))
    assert selection.selected_blueprint_id == "bp-segment-deterioration"
    assert selection.confident


def test_a_decomposition_question_selects_the_decomposition_blueprint():
    selection = bp.select(bp.Request(
        question="Decompose the ECL change into exposure, stage, PD and LGD.",
        capability="ANALYSIS", subject="portfolio",
        concepts=("expected credit loss",), periods=2))
    assert selection.selected_blueprint_id == "bp-ecl-decomposition"


def test_a_weak_match_is_reported_as_weak_rather_than_chosen():
    """A blueprint applied to a question it does not fit runs sixteen analyses
    nobody asked for and calls the result an investigation."""
    selection = bp.select(bp.Request(question="zxqv wibble frobnicate",
                                     subject="", periods=1))
    assert not selection.confident
    assert "below the" in selection.selection_reasons[0]


def test_the_record_shows_the_runners_up():
    """A selection that shows only its winner cannot be argued with."""
    selection = bp.select(bp.Request(
        question="What is going on in Contracting?", subject="sector",
        broad=True, periods=2))
    assert len(selection.considered) > 1
    scores = [c["score"] for c in selection.considered]
    assert scores == sorted(scores, reverse=True)


def test_the_selection_record_carries_what_section_69_persists():
    selection = bp.select(bp.Request(question="What is going on in "
                                              "Contracting?",
                                     subject="sector", broad=True))
    body = selection.to_dict()
    assert set(body) >= {"selected_blueprint_id", "version",
                         "selection_score", "selection_reasons",
                         "required_objectives", "optional_objectives",
                         "omitted_objectives", "omission_reasons",
                         "custom_additions"}


# ====================================================== §70 the hypothesis tree


def test_the_standard_tree_names_the_artefact_hypothesis():
    """"The movement is an artefact" is unglamorous and correct often enough
    to be worth naming every time."""
    tree = hy.standard_tree("Contracting appears to have deteriorated.")
    assert len(tree.hypotheses) == 6
    assert any("Data, joins, periods or denominator" in h.statement
               for h in tree.hypotheses)


def test_a_tree_of_unresolved_hypotheses_is_a_list_of_questions():
    """A legitimate intermediate state and an illegitimate final one."""
    tree = hy.standard_tree("x")
    assert not tree.complete
    for hypothesis in tree.hypotheses:
        tree.settle(hypothesis.hypothesis_id, hy.NOT_TESTABLE,
                    reason="no history")
    assert tree.complete


def test_confidence_comes_from_evidence_coverage_and_validation():
    """§70: "confidence is not LLM self-confidence"."""
    tree = hy.standard_tree("x")
    tree.settle("H3", hy.SUPPORTED, reason="top three explain 78%",
                facts=["f1", "f2"], validated=2)
    assert tree.get("H3").confidence == 1.0

    tree.settle("H4", hy.PARTIALLY_SUPPORTED, reason="thin",
                facts=["f1"], validated=0)
    assert tree.get("H4").confidence == 0.0


def test_not_testable_is_a_status_of_its_own():
    """"The change is temporary" is not testable on two periods, and
    UNRESOLVED implies somebody could resolve it by trying harder."""
    assert hy.NOT_TESTABLE in hy.STATUSES
    assert hy.NOT_TESTABLE in hy.SETTLED
    assert hy.UNRESOLVED not in hy.SETTLED


def test_an_unknown_status_is_refused():
    tree = hy.standard_tree("x")
    with pytest.raises(ValueError, match="not a hypothesis status"):
        tree.settle("H1", "PROBABLY", reason="")


# ================================================== §71 the challenge pass


def test_all_fourteen_challenges_section_71_lists_are_declared():
    assert len(hy.CHALLENGES) == 14
    assert {c.id for c in hy.CHALLENGES} >= {
        "largest_borrower", "population_change", "new_exited", "denominator",
        "one_period_noise", "persistent", "period_alignment",
        "grain_alignment", "join_integrity", "hidden_offsets",
        "overlay_effect", "data_quality", "alternative_conclusion",
        "second_method"}


def test_a_skipped_challenge_is_not_a_passed_challenge():
    """The same sentence Phase 0's Trace work turned on, recurring because it
    is the same failure: an unrun check reported as clear."""
    found = hy.Pass(conclusion="ECL deteriorated")
    found.record("period_alignment", hy.PASSED)
    assert not found.complete
    assert len(found.outstanding) > 1
    assert all(f.outcome == hy.NOT_RUN for f in found.outstanding)


def test_a_complete_pass_survives_and_says_so():
    found = hy.Pass(conclusion="ECL deteriorated")
    for challenge in hy.CHALLENGES:
        found.record(challenge.id, hy.PASSED)
    assert found.complete
    assert found.survives
    assert "none was left open" in found.sentence()


def test_a_raised_challenge_must_say_what_it_found():
    """An unexplained "raised" is an alarm with no information."""
    found = hy.Pass()
    with pytest.raises(ValueError, match="what it found"):
        found.record("largest_borrower", hy.RAISED)
    with pytest.raises(ValueError, match="what it found"):
        found.record("largest_borrower", hy.NOT_RUN)


def test_a_raised_challenge_stays_outstanding_until_resolved():
    found = hy.Pass()
    for challenge in hy.CHALLENGES:
        found.record(challenge.id, hy.PASSED)
    found.findings[0].outcome = hy.RAISED
    found.findings[0].detail = "one name is 62% of the movement"
    assert not found.survives

    found.resolve(found.findings[0].challenge_id, "reported separately")
    assert found.survives


def test_the_answer_states_the_unresolved_challenges():
    """§71's last sentence, as a sentence."""
    found = hy.Pass(conclusion="ECL deteriorated")
    found.record("largest_borrower", hy.RAISED,
                 detail="one name is 62% of the movement")
    said = found.sentence()
    assert "one large borrower" in said
    assert "62%" in said


def test_an_unrun_non_material_challenge_does_not_block():
    """Running fourteen clearances on every immaterial observation buries the
    ones that matter."""
    found = hy.Pass()
    for challenge in hy.CHALLENGES:
        if challenge.material:
            found.record(challenge.id, hy.PASSED)
    assert found.complete
    assert found.survives


def test_corroboration_is_required_only_where_the_stakes_justify_it():
    assert len(hy.required_for(mt.CRITICAL)) == len(hy.CHALLENGES)
    assert len(hy.required_for(mt.LOW)) < len(hy.CHALLENGES)
    assert all(c.material for c in hy.required_for(mt.LOW))


def test_an_unknown_challenge_is_refused():
    found = hy.Pass()
    with pytest.raises(KeyError):
        found.record("did_we_check_the_vibes", hy.PASSED)
