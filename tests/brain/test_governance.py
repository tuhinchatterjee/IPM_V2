"""Status governance, independent reference validation and the critical suite.

§6, §7, §9. The three that decide whether a number the Brain Center shows can
be believed.
"""

from __future__ import annotations

import pytest

from backend.brain import corpus, critical, reference, status
from backend.brain.cases import (
    AUTO_GENERATED,
    AUTO_VALIDATED,
    HUMAN_APPROVED,
    HUMAN_REVIEWED,
    SYSTEM_REFERENCE_VALIDATED,
    Case,
    Reference,
)


@pytest.fixture(scope="module")
def cases():
    return corpus.build()


@pytest.fixture
def analysis_case(cases):
    return next(c for c in cases if c.case_family == "SINGLE_DOMAIN")


@pytest.fixture
def refusal_case(cases):
    return next(c for c in cases if "credential_probe" in c.cluster)


def _matching(case: Case, **overrides) -> reference.Observation:
    """An observation that agrees with the case on every dimension."""
    base = {
        "capability": case.expected_capability,
        "officer_level": case.expected_officer_level,
        "agents": case.expected_agents,
        "tools": case.expected_tools,
        "datasets": case.expected_datasets,
        "relationships": case.expected_relationships,
        "period_rule": case.expected_period_rule,
        "grain": case.expected_grain,
        "filters": dict(case.expected_filters),
        "operations": case.expected_operations,
        "result_columns": tuple(
            f for f in (case.expected_grain, "value") if f),
        "result_ids": (case.expected_grain,) if case.expected_grain else (),
        "values": {},
        "invariants_held": case.required_invariants,
        "invariants_failed": (),
        "clarified": case.expected_clarification,
        "abstained": case.expected_abstention,
        "figure_present": not (case.expected_clarification
                               or case.expected_abstention),
        "permission_granted": True,
        "state_changed": False,
        "approval_requested": False,
    }
    base.update(overrides)
    return reference.Observation(**base)


# ================================================================ §6 statuses


def test_a_generated_case_starts_with_nothing_established(cases):
    assert all(c.status == AUTO_GENERATED for c in cases)


def test_format_validation_promotes_only_to_auto_validated(analysis_case):
    promoted = status.promote(analysis_case, AUTO_VALIDATED, status.Evidence())
    assert promoted.status == AUTO_VALIDATED
    with pytest.raises(status.StatusError):
        status.promote(analysis_case, SYSTEM_REFERENCE_VALIDATED,
                       status.Evidence())


def test_an_llm_critic_cannot_promote_a_case(analysis_case):
    """§6's load-bearing rule."""
    validated = status.promote(analysis_case, AUTO_VALIDATED,
                               status.Evidence())
    liked = status.Evidence(kind="llm_critic", independent=True,
                            dimensions=("capability", "period"))
    with pytest.raises(status.StatusError, match="not a computation"):
        status.promote(validated, SYSTEM_REFERENCE_VALIDATED, liked)


def test_evidence_that_is_not_independent_cannot_promote(analysis_case):
    validated = status.promote(analysis_case, AUTO_VALIDATED,
                               status.Evidence())
    judged = status.Evidence(kind="model_review", independent=False,
                             dimensions=("capability",))
    with pytest.raises(status.StatusError, match="not independent"):
        status.promote(validated, SYSTEM_REFERENCE_VALIDATED, judged)


def test_a_subjective_case_can_never_be_reference_validated():
    subjective = Case(
        case_id="X-1", case_family="PRESENTATION", cluster="x",
        question="Is this well written?", objectives=("judge the prose",),
        forbidden=("says yes without reading it",),
        reference=Reference(kind="", means="somebody's opinion"))
    assert status.subjective(subjective)
    validated = status.promote(subjective, AUTO_VALIDATED, status.Evidence())
    good = status.Evidence(kind="independent_reference", independent=True,
                           dimensions=("capability",))
    with pytest.raises(status.StatusError, match="no independent reference"):
        status.promote(validated, SYSTEM_REFERENCE_VALIDATED, good)


def test_a_real_reference_report_promotes(analysis_case):
    validated = status.promote(analysis_case, AUTO_VALIDATED,
                               status.Evidence())
    report = reference.check(analysis_case, _matching(analysis_case))
    evidence = status.from_reference(report)
    assert evidence.independent
    promoted = status.promote(validated, SYSTEM_REFERENCE_VALIDATED, evidence)
    assert promoted.status == SYSTEM_REFERENCE_VALIDATED
    assert promoted.version > validated.version


def test_human_statuses_require_a_named_person(analysis_case):
    validated = status.promote(analysis_case, AUTO_VALIDATED,
                               status.Evidence())
    with pytest.raises(status.StatusError, match="named person"):
        status.promote(validated, HUMAN_REVIEWED, status.Evidence())
    reviewed = status.promote(validated, HUMAN_REVIEWED,
                              status.review("A. Reviewer"))
    approved = status.promote(reviewed, HUMAN_APPROVED,
                              status.review("A. Reviewer", "checked"))
    assert approved.status == HUMAN_APPROVED


def test_a_review_without_a_reviewer_is_not_a_review():
    with pytest.raises(status.StatusError):
        status.review("   ")


def test_a_status_cannot_skip_a_step(analysis_case):
    with pytest.raises(status.StatusError, match="does not promote"):
        status.promote(analysis_case, HUMAN_APPROVED,
                       status.review("A. Reviewer"))


def test_demotion_is_always_available_and_needs_a_reason(analysis_case):
    validated = status.promote(analysis_case, AUTO_VALIDATED,
                               status.Evidence())
    demoted = status.demote(validated, AUTO_GENERATED, "found a wrong grain")
    assert demoted.status == AUTO_GENERATED
    with pytest.raises(status.StatusError):
        status.demote(validated, AUTO_GENERATED, "  ")


# ------------------------------------------------------- production policy


def test_only_human_approved_is_retrievable_without_a_policy():
    for name in (AUTO_GENERATED, AUTO_VALIDATED, HUMAN_REVIEWED,
                 SYSTEM_REFERENCE_VALIDATED):
        assert status.may_retrieve(name)[0] is False
    assert status.may_retrieve(HUMAN_APPROVED) == (True, "")


def test_reference_validated_is_retrievable_only_labelled():
    allowed, label = status.may_retrieve(SYSTEM_REFERENCE_VALIDATED,
                                         administrator_policy=True)
    assert allowed
    assert "not reviewed by a person" in label


def test_an_unvalidated_case_may_not_tune_anything():
    assert not status.may_tune(AUTO_GENERATED)
    assert not status.may_tune(AUTO_VALIDATED)
    assert status.may_tune(SYSTEM_REFERENCE_VALIDATED)
    assert status.may_tune(HUMAN_APPROVED)


def test_the_corpus_starts_with_nothing_retrievable_or_tunable(cases):
    assert status.retrievable_cases(cases) == []
    assert status.tunable_cases(cases) == []


# ============================================================== §7 reference


def test_every_dimension_the_brief_names_is_checked(analysis_case):
    report = reference.check(analysis_case, _matching(analysis_case))
    assert [c.dimension for c in report.checks] == list(reference.DIMENSIONS)
    assert len(reference.DIMENSIONS) == 17


def test_a_matching_run_passes_and_settles(analysis_case):
    report = reference.check(analysis_case, _matching(analysis_case))
    assert report.failed == []
    assert report.settled
    assert report.independent


def test_an_empty_observation_measures_nothing_and_settles_nothing(
        analysis_case):
    report = reference.check(analysis_case, reference.Observation())
    assert not report.settled
    assert report.unmeasured_dimensions
    assert report.coverage == 0.0


def test_not_measured_is_never_counted_as_a_pass(analysis_case):
    report = reference.check(analysis_case, reference.Observation())
    assert reference.PERIOD not in report.passed_dimensions
    assert reference.PERIOD in report.unmeasured_dimensions


def test_a_silent_period_choice_fails_rather_than_going_unmeasured(
        analysis_case):
    observed = _matching(analysis_case, period_rule=None,
                         periods=("Q2 2026",))
    report = reference.check(analysis_case, observed)
    period = next(c for c in report.checks
                  if c.dimension == reference.PERIOD)
    assert period.verdict == reference.FAILED
    assert "no period rule was recorded" in period.detail


def test_the_wrong_officer_level_is_named_by_direction(analysis_case):
    observed = _matching(analysis_case, officer_level=4)
    report = reference.check(analysis_case, observed)
    officer = next(c for c in report.checks
                   if c.dimension == reference.OFFICER)
    assert officer.verdict == reference.FAILED
    assert "above" in officer.detail


def test_clarifying_a_question_it_could_answer_fails(analysis_case):
    observed = _matching(analysis_case, clarified=True, figure_present=False)
    report = reference.check(analysis_case, observed)
    check = next(c for c in report.checks
                 if c.dimension == reference.CLARIFICATION)
    assert check.verdict == reference.FAILED


def test_a_figure_beside_a_refusal_fails(refusal_case):
    observed = _matching(refusal_case, abstained=True, figure_present=True)
    report = reference.check(refusal_case, observed)
    check = next(c for c in report.checks
                 if c.dimension == reference.CLARIFICATION)
    assert check.verdict == reference.FAILED


def test_an_unchecked_invariant_is_not_a_held_one(analysis_case):
    observed = _matching(analysis_case, invariants_held=(),
                         invariants_failed=())
    report = reference.check(analysis_case, observed)
    check = next(c for c in report.checks
                 if c.dimension == reference.INVARIANTS)
    assert check.verdict == reference.FAILED
    assert "never checked" in check.detail


def test_values_are_unmeasured_without_an_independent_computation(
        analysis_case):
    report = reference.check(analysis_case,
                             _matching(analysis_case, values={"total": 1.0}))
    assert reference.VALUES in report.unmeasured_dimensions


def test_values_outside_tolerance_fail(analysis_case):
    observed = _matching(analysis_case, values={"total": 100.0})
    report = reference.check(analysis_case, observed,
                             computed_values={"total": 90.0})
    check = next(c for c in report.checks if c.dimension == reference.VALUES)
    assert check.verdict == reference.FAILED


def test_aggregate_reports_unmeasured_beside_passed(analysis_case):
    reports = [reference.check(analysis_case, _matching(analysis_case)),
               reference.check(analysis_case, reference.Observation())]
    summary = reference.aggregate(reports)
    assert summary["cases"] == 2
    assert summary["settled"] == 1
    period = summary["dimensions"][reference.PERIOD]
    assert period[reference.PASSED] == 1
    assert period[reference.NOT_MEASURED] == 1


# =============================================================== §9 critical


def test_the_suite_defines_the_twenty_three_classes_the_brief_names():
    assert len(critical.CLASSES) == 23
    assert len(set(critical.CLASS_IDS)) == 23


def test_the_gate_blocks_on_an_unmeasured_class(refusal_case):
    suite = critical.run([(refusal_case, _matching(refusal_case))])
    allowed, why = critical.gate(suite)
    assert not allowed
    assert "did not measure" in why
    assert suite.status == critical.BLOCKED


def test_the_gate_clears_when_every_class_is_actually_proven(refusal_case):
    suite = critical.run(
        [(refusal_case, _matching(refusal_case))],
        release_state={"release_shown": "brain-1", "release_active": "brain-1",
                       "pack_compatible": True,
                       "pack_inspection": {"clean": True}})
    allowed, why = critical.gate(suite)
    assert allowed, why
    assert suite.status == critical.CLEAR


def test_one_failure_anywhere_blocks(refusal_case):
    """§9: any failure blocks activation."""
    leaked = _matching(refusal_case, abstained=False, figure_present=True)
    suite = critical.run(
        [(refusal_case, leaked)],
        release_state={"release_shown": "brain-1", "release_active": "brain-1",
                       "pack_compatible": True,
                       "pack_inspection": {"clean": True}})
    allowed, why = critical.gate(suite)
    assert not allowed
    assert "secret_request" in why


def test_a_stale_release_blocks(refusal_case):
    suite = critical.run(
        [(refusal_case, _matching(refusal_case))],
        release_state={"release_shown": "brain-2",
                       "release_active": "brain-1",
                       "pack_compatible": True,
                       "pack_inspection": {"clean": True}})
    assert not critical.gate(suite)[0]
    assert suite.outcome_for("stale_release_shown_current") == \
        critical.CLASS_FAILED


def test_an_incompatible_pack_blocks(refusal_case):
    suite = critical.run(
        [(refusal_case, _matching(refusal_case))],
        release_state={"release_shown": "brain-1", "release_active": "brain-1",
                       "pack_compatible": False,
                       "pack_incompatibility": "built against ontology 1.0.0",
                       "pack_inspection": {"clean": True}})
    assert not critical.gate(suite)[0]
    assert suite.outcome_for("pack_compatibility_bypass") == \
        critical.CLASS_FAILED


def test_a_pack_carrying_executable_content_blocks(refusal_case):
    suite = critical.run(
        [(refusal_case, _matching(refusal_case))],
        release_state={"release_shown": "brain-1", "release_active": "brain-1",
                       "pack_compatible": True,
                       "pack_inspection": {
                           "clean": False,
                           "problems": ["entry model.pkl is executable"]}})
    assert not critical.gate(suite)[0]
    assert suite.outcome_for("malicious_pack") == critical.CLASS_FAILED


def test_a_failed_invariant_shown_with_a_figure_is_detected(analysis_case):
    observed = _matching(analysis_case,
                         invariants_failed=("no row is counted twice",),
                         figure_present=True)
    suite = critical.run([(analysis_case, observed)])
    assert suite.outcome_for("failed_invariant_displayed") == \
        critical.CLASS_FAILED


def test_reading_the_holdout_during_a_run_is_detected(analysis_case):
    observed = _matching(analysis_case,
                         datasets=(*analysis_case.expected_datasets,
                                   "holdout_gold"))
    suite = critical.run([(analysis_case, observed)])
    assert suite.outcome_for("benchmark_leakage") == critical.CLASS_FAILED


def test_a_fan_out_join_without_aggregation_is_detected(cases):
    fanned = next(
        c for c in cases
        if c.expected_plan_properties.get("join_cardinality") == "many_to_one")
    observed = _matching(fanned, operations=("join",))
    suite = critical.run([(fanned, observed)])
    assert suite.outcome_for("duplicate_amplification") == \
        critical.CLASS_FAILED


def test_a_result_with_no_identifiers_is_a_fabrication_risk(analysis_case):
    observed = _matching(analysis_case, result_ids=())
    suite = critical.run([(analysis_case, observed)])
    assert suite.outcome_for("fabricated_borrower") == critical.CLASS_FAILED


def test_an_unapproved_state_change_is_detected(cases):
    gated = next(c for c in cases
                 if c.expected_plan_properties.get("requires_confirmation"))
    observed = _matching(gated, state_changed=True,
                         approval_requested=False)
    suite = critical.run([(gated, observed)])
    assert suite.outcome_for("missing_human_approval") == \
        critical.CLASS_FAILED


def test_the_catalogue_describes_every_class():
    entries = critical.catalogue()
    assert len(entries) == 23
    for entry in entries:
        assert entry["title"] and entry["means"]
