"""
Part F — the six Intelligence Dimensions and the Investigation Assurance
Record. §178-§203.

Four instructions, each naming a way a score lies
---------------------------------------------------
    §182: "Do not compute the overall result by blindly averaging the six
           dimensions."
    §183: "SKIPPED is never PASS." / "A missing check is not silently treated
           as NOT_APPLICABLE."
    §184: "Do not display 'Accuracy 96%' for a live Investigation with no
           independent reference."
    §212: "A critical failure overrides a high average."

The last one is the shape of all four. Every convenient way to compute an
assurance number involves averaging away the one check that mattered, and
every test below is about the case where the average and the truth differ.
"""

from __future__ import annotations

import pytest

from backend.assurance import dimensions as dm
from backend.assurance import panel as pn
from backend.assurance import record as rc


def _passing(*, skip: set[str] | None = None) -> rc.Record:
    """A record where every subcomponent passed, except any skipped."""
    skip = skip or set()
    made = rc.Record(question="what moved in Contracting?", answer_id="a1",
                     investigation_id="inv-1", build_sha="abc123")
    for name in dm.all_subcomponents():
        made.checks.append(
            rc.check(name, rc.SKIPPED if name in skip else rc.PASS))
    return rc.seal(made)


# ================================================ §178, §179 the six dimensions


def test_there_are_exactly_six_dimensions():
    assert len(dm.DIMENSIONS) == 6
    for dimension in dm.DIMENSIONS:
        assert dm.LABELS[dimension].strip()
        assert dm.ANSWERS[dimension].endswith("?")


def test_every_dimension_answers_a_question_a_person_actually_has():
    """Six dimensions each answer a question somebody arrives with. A flat
    wall of ninety checks answers none of them, because it never says what
    any check is for."""
    for dimension in dm.DIMENSIONS:
        assert len(dm.ANSWERS[dimension]) > 40, dimension


def test_the_detailed_checks_are_not_deleted():
    """§179. The dimension is where you notice a problem and the
    subcomponent is where you fix it."""
    assert len(dm.all_subcomponents()) >= 90
    for dimension in dm.DIMENSIONS:
        assert len(dm.SUBCOMPONENTS[dimension]) >= 12, dimension


def test_every_subcomponent_belongs_to_exactly_one_dimension():
    seen: dict[str, str] = {}
    for dimension, names in dm.SUBCOMPONENTS.items():
        for name in names:
            assert name not in seen, (name, seen.get(name), dimension)
            seen[name] = dimension


def test_a_subcomponent_nobody_placed_is_reported_rather_than_guessed():
    """Filing it under whichever dimension sorts first would count it toward
    a score it has nothing to do with."""
    assert dm.dimension_of("something_new") == ""


def test_the_weights_sum_to_a_hundred_and_are_versioned():
    """A policy whose weights do not sum to 100 produces a score nobody can
    compare with another one."""
    assert sum(dm.WEIGHTS.values()) == 100
    assert dm.Weights().version == dm.WEIGHTS_VERSION

    with pytest.raises(ValueError):
        dm.Weights(weights={**dm.WEIGHTS, dm.COMPUTATION: 40})
    with pytest.raises(ValueError):
        dm.Weights(weights={dm.COMPUTATION: 100})


def test_computation_carries_the_most_weight():
    """A wrong number is the failure that cannot be recovered from
    downstream."""
    assert dm.WEIGHTS[dm.COMPUTATION] == max(dm.WEIGHTS.values())


# ================================================ §183 the five outcomes


def test_there_are_exactly_six_check_outcomes():
    """§183 named five; §20 added the sixth.

    NOT_AVAILABLE is split out of SKIPPED because they are different problems
    with different owners: SKIPPED means execution deliberately did not run
    the check on this turn, and NOT_AVAILABLE means the check cannot run for
    ANY turn because nothing emits its signal. Collapsed together, every
    uninstrumented check hides inside the noise of legitimately skipped ones.
    """
    assert len(rc.OUTCOMES) == 6
    assert set(rc.OUTCOMES) == {rc.PASS, rc.WARNING, rc.FAIL, rc.SKIPPED,
                                rc.NOT_APPLICABLE, rc.NOT_AVAILABLE}
    for outcome in rc.OUTCOMES:
        assert len(rc.OUTCOME_MEANS[outcome]) > 30, outcome


def test_neither_skipped_nor_not_available_counts_as_coverage():
    assert rc.SKIPPED not in rc.COUNTED
    assert rc.NOT_AVAILABLE not in rc.COUNTED
    assert rc.UNRESOLVED == {rc.SKIPPED, rc.NOT_AVAILABLE}


def test_a_critical_check_with_no_signal_blocks():
    """§20: "Critical NOT_AVAILABLE blocks."

    UNVERIFIED rather than FAILED — nothing is proven wrong. But no score
    either: a critical check nobody could run leaves the central question
    unanswered, and "we did not look" must never produce the same status as
    "we looked and it was fine".
    """
    made = rc.Record(answer_id="a")
    for name in dm.all_subcomponents():
        made.checks.append(
            rc.check(name, rc.NOT_AVAILABLE if name == "figure_grounding"
                     else rc.PASS))

    verdict = made.overall()

    assert verdict["overall_status"] == rc.UNVERIFIED
    assert verdict["operational_assurance"] is None
    assert "no signal exists" in verdict["reasons"][0]
    assert made.critical_not_available == ["figure_grounding"]


def test_a_mandatory_check_with_no_signal_blocks_like_a_skip():
    """An uninstrumented mandatory check must not escape §20's mandatory-skip
    gate by being a different word."""
    made = rc.Record(answer_id="a")
    made.checks = [rc.check("trace_clarity", rc.NOT_AVAILABLE)]

    assert "trace_clarity" in made.skipped_mandatory


def test_skipped_is_never_pass():
    """§183 says it in as many words, and it is the rule that stops a
    coverage number being improved by running fewer checks."""
    assert rc.SKIPPED not in rc.COUNTED
    skipped = rc.check("figure_grounding", rc.SKIPPED)
    assert skipped.counted is False


def test_a_not_applicable_with_no_reason_is_refused():
    """It removes the check from the coverage denominator, which improves
    coverage by not looking — the exact incentive §183 exists to remove."""
    with pytest.raises(rc.NotEstablished):
        rc.check("persistence_noise", rc.NOT_APPLICABLE)

    allowed = rc.check("persistence_noise", rc.NOT_APPLICABLE,
                       because="the question covers one period")
    assert allowed.not_applicable_because


def test_a_missing_check_is_skipped_rather_than_not_applicable():
    """§183's other half. A subcomponent absent from the record is skipped,
    because nothing ran it."""
    sparse = rc.Record(answer_id="a")
    sparse.checks = [rc.check("capability_intent", rc.PASS)]

    missing = sparse.skipped_mandatory
    assert "figure_grounding" in missing
    assert "business_invariants" in missing


def test_a_skipped_check_stays_in_the_coverage_denominator():
    full = _passing()
    partial = _passing(skip={"latency", "accessibility", "ui_responsiveness"})

    assert partial.coverage_pct < full.coverage_pct


def test_a_deterministically_inapplicable_check_leaves_the_denominator():
    made = rc.Record(answer_id="a")
    made.checks = [rc.check(name, rc.PASS)
                   for name in dm.all_subcomponents()
                   if name != "persistence_noise"]
    made.checks.append(rc.check("persistence_noise", rc.NOT_APPLICABLE,
                                because="the question covers one period"))

    assert made.coverage_pct == 100.0


# ============================================== §181, §182 the status model


def test_the_seven_statuses_section_181_names_all_mean_something():
    assert len(rc.STATUSES) == 7
    for status in rc.STATUSES:
        assert len(rc.MEANS[status]) > 40, status


def test_a_critical_failure_overrides_a_high_average():
    """§212, and the shape of everything else here. A record with a failed
    invariant does not get a score: reporting "72/100 (FAILED)" invites
    somebody to notice the 72."""
    made = _passing()
    made.checks = [c for c in made.checks
                   if c.subcomponent != "business_invariants"]
    made.checks.append(rc.check("business_invariants", rc.FAIL,
                                detail="the components do not sum to the "
                                       "movement"))

    verdict = made.overall()

    assert verdict["overall_status"] == rc.FAILED
    assert verdict["operational_assurance"] is None
    assert "business_invariants failed" in verdict["reasons"][0]


def test_the_gates_run_before_the_score():
    """§182's order: critical gates, coverage gate, then the weighted
    score."""
    thin = rc.Record(answer_id="a")
    thin.checks = [rc.check("capability_intent", rc.PASS)]

    verdict = thin.overall()

    assert verdict["overall_status"] == rc.UNVERIFIED
    assert verdict["operational_assurance"] is None
    assert "not enough to claim anything" in verdict["reasons"][0]


def test_a_skipped_mandatory_check_produces_needs_review():
    made = _passing(skip={"figure_grounding"})

    verdict = made.overall()

    assert verdict["overall_status"] == rc.NEEDS_REVIEW
    assert "figure_grounding" in verdict["reasons"][0]


def test_a_clean_record_with_high_coverage_is_high_assurance():
    verdict = _passing().overall()

    assert verdict["overall_status"] == rc.HIGH_ASSURANCE
    assert verdict["operational_assurance"] == 100.0
    assert verdict["coverage_pct"] == 100.0


def test_a_warning_caps_the_status_even_at_a_high_score():
    """A correct answer with a stated gap is not the same claim as a correct
    answer without one."""
    made = _passing()
    made.checks = [c for c in made.checks if c.subcomponent != "concision_no_repetition"]
    made.checks.append(rc.check("concision_no_repetition", rc.WARNING,
                                detail="the second paragraph repeats the "
                                       "first"))

    verdict = made.overall()

    assert verdict["overall_status"] == rc.VALIDATED_WITH_LIMITATIONS
    assert verdict["operational_assurance"] > 95.0


def test_a_stated_limitation_caps_the_status_too():
    made = _passing()
    made.limitations = ["covenant data is missing for 40% of the segment"]

    assert made.overall()["overall_status"] == rc.VALIDATED_WITH_LIMITATIONS


def test_stale_beats_everything():
    """Not a lower grade of assurance — a statement about a version that no
    longer runs."""
    made = _passing()
    made.stale_reasons = ["the ontology has changed since this ran"]

    verdict = made.overall()

    assert verdict["overall_status"] == rc.STALE
    assert verdict["operational_assurance"] is None


def test_the_payload_says_it_was_not_scored_on_an_average():
    assert _passing().overall()["scored_on_average"] is False


def test_a_dimension_nobody_measured_neither_helps_nor_hurts():
    """It shows as unmeasured, which is what it is."""
    made = rc.Record(answer_id="a")
    made.checks = [rc.check(name, rc.PASS)
                   for name in dm.SUBCOMPONENTS[dm.COMPUTATION]]

    results = {r.dimension: r for r in made.by_dimension()}
    assert results[dm.COMPUTATION].score == 100.0
    assert results[dm.AGENTIC].score is None


def test_a_warning_is_worth_half_a_pass():
    """A real defect and not a wrong answer. Scoring it as either extreme
    makes the score useless in one direction."""
    result = rc.DimensionResult(dimension=dm.JUDGMENT)
    result.checks = [rc.check("materiality", rc.PASS),
                     rc.check("limitations", rc.WARNING, detail="thin")]

    assert result.score == 75.0


# ==================================== §184 operational assurance vs reference


def test_a_live_investigation_reports_operational_assurance_not_accuracy():
    """A live Investigation has no right answer to compare against — that is
    what makes it live. Calling what the runtime proved "accuracy" invites a
    reader to believe it answers "is this right?"."""
    payload = _passing().to_dict()

    assert "Operational assurance" in payload["operational_assurance_label"]
    assert "accuracy" not in payload["operational_assurance_label"].lower()
    assert payload["reference_match"]["available"] is False
    assert payload["reference_match"]["value_pct"] is None
    assert "no independent reference" in payload["reference_match"]["why"]


def test_a_reference_match_appears_only_where_a_reference_exists():
    made = _passing()
    made.reference_match_pct = 98.0
    made.reference_source = "sealed holdout case h-42"

    payload = made.to_dict()

    assert payload["reference_match"]["available"] is True
    assert payload["reference_match"]["value_pct"] == 98.0
    assert payload["reference_match"]["source"]


def test_the_two_numbers_are_never_combined():
    made = _passing()
    made.reference_match_pct = 98.0

    payload = made.to_dict()

    assert payload["operational_assurance"] != 98.0
    assert isinstance(payload["reference_match"], dict)


# ================================================== §180 immutability


def test_a_record_hashes_its_own_content():
    """An assurance record that could be revised after the fact is a record
    of what somebody wanted to have happened."""
    made = _passing()

    assert made.intact is True

    made.checks[0].outcome = rc.FAIL
    assert made.intact is False


def test_an_unsealed_record_is_not_intact():
    made = rc.Record(answer_id="a")

    assert made.intact is False


def test_the_record_carries_every_field_section_180_names():
    payload = _passing().to_dict()

    for name in ("assurance_record_id", "tenant_id", "user_id",
                 "investigation_id", "message_id", "answer_id",
                 "analysis_run_ids", "trace_id", "agentic_run_id",
                 "project_id", "portfolio_scope", "language", "question",
                 "answer_type", "created_at", "completed_at", "duration_ms",
                 "build_sha", "app_version", "intelligence_release_id",
                 "teaching_release_id", "ontology_version",
                 "method_versions", "relationship_versions",
                 "prompt_versions", "routing_policy_version", "model_roles",
                 "served_models", "officer_level", "agent_roles",
                 "blueprint_id", "retrieved_teaching_case_ids",
                 "objective_coverage", "data_versions",
                 "result_fingerprints", "overall_status", "coverage_pct",
                 "critical_failures", "warnings", "limitations",
                 "repair_count", "clarification_count",
                 "user_feedback_summary", "dimension_results",
                 "subcomponent_results", "review_state", "stale",
                 "stale_reasons", "fingerprint"):
        assert name in payload, name


# ============================================ §188-§198 the panel


def test_the_button_has_one_name_everywhere():
    """Two names for the same thing is two things as far as a user is
    concerned."""
    assert pn.BUTTON == "How CreditProbe performed"
    assert len(pn.PLACEMENTS) == 5


def test_the_panel_says_why_every_point_went():
    """§197. A score without this is a grade; with it, it is a review."""
    made = _passing()
    made.checks = [c for c in made.checks
                   if c.subcomponent != "figure_grounding"]
    made.checks.append(rc.check("figure_grounding", rc.FAIL,
                                detail="17.4% traces to no fact",
                                evidence=["narrative paragraph 2"]))

    built = pn.Panel(made).dimensions()
    computation = next(d for d in built if d["dimension"] == dm.COMPUTATION)

    lost = computation["why_points_were_lost"]
    assert lost
    assert lost[0]["subcomponent"] == "figure_grounding"
    assert lost[0]["why"] == "17.4% traces to no fact"
    assert lost[0]["critical"] is True


def test_a_skipped_check_costs_coverage_rather_than_points():
    """Saying so stops a reader assuming the score already accounts for
    it."""
    made = _passing(skip={"accessibility"})

    built = pn.Panel(made).dimensions()
    reliability = next(d for d in built if d["dimension"] == dm.RELIABILITY)

    lost = [entry for entry in reliability["why_points_were_lost"]
            if entry["subcomponent"] == "accessibility"]
    assert lost[0]["cost"] == "coverage, not points"


def test_the_recommendations_name_the_actual_failure():
    """"Improve grounding" is advice nobody can act on. "The figure 17.4%
    traces to no fact" is a task."""
    made = _passing()
    made.checks = [c for c in made.checks
                   if c.subcomponent != "scope_isolation"]
    made.checks.append(rc.check("scope_isolation", rc.FAIL,
                                detail="a row outside the permitted scope "
                                       "reached the result"))

    steps = pn.recommended(made)

    assert any("scope isolation" in step for step in steps)


def test_a_dimension_with_a_critical_failure_is_failed_whatever_it_scored():
    made = _passing()
    made.checks = [c for c in made.checks
                   if c.subcomponent != "permission_enforcement"]
    made.checks.append(rc.check("permission_enforcement", rc.FAIL,
                                detail="an unauthorized dataset was read"))

    built = pn.Panel(made).dimensions()
    computation = next(d for d in built if d["dimension"] == dm.COMPUTATION)

    assert computation["status"] == rc.FAILED
    assert computation["score"] > 90.0


def test_the_panel_header_keeps_the_two_numbers_apart():
    header = pn.Panel(_passing()).header()

    assert "operational_assurance" in header
    assert header["reference_match"]["available"] is False
    # The LABEL never says accuracy. The reference-match explanation does,
    # deliberately -- "no accuracy figure can be given" is the sentence that
    # tells a reader why there is no such number here.
    assert "accuracy" not in header["operational_assurance_label"].lower()
    assert "accuracy" in header["reference_match"]["why"].lower()


# ================================================== §185 thread level


def test_a_thread_is_as_good_as_its_worst_turn():
    """Averaging one FAILED turn against nine good ones produces a
    comfortable number describing a conversation that contained a wrong
    answer."""
    good = _passing()
    bad = rc.Record(answer_id="a2", question="and the drivers?")
    bad.checks = [rc.check("result_correctness", rc.FAIL,
                           detail="the total does not reconcile")]

    summary = pn.Summary(investigation_id="inv-1",
                         records=[good, good, good, bad]).to_dict()

    assert summary["status"] == rc.FAILED
    assert summary["averaged"] is False
    assert "result_correctness" in summary["critical_failures"]
    assert summary["turn_count"] == 4


def test_a_thread_of_clean_turns_is_clean():
    summary = pn.Summary(records=[_passing(), _passing()]).to_dict()

    assert summary["status"] == rc.HIGH_ASSURANCE


def test_an_empty_thread_is_unverified_rather_than_clean():
    assert pn.Summary(records=[]).to_dict()["status"] == rc.UNVERIFIED


def test_every_turn_appears_in_the_timeline():
    summary = pn.Summary(records=[_passing(), _passing()]).to_dict()

    assert [t["turn"] for t in summary["turns"]] == [1, 2]
    for turn in summary["turns"]:
        assert turn["overall_status"] in rc.STATUSES
