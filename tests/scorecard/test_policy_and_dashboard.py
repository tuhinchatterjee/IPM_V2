"""
Policy, limits, findings, the opinion, and the assembled dashboard.
§7, §22-§27, §33, §40, §44, §47-§50, §80, §81.

The tests that matter here are about what the product refuses to say.

A metric with no limit has not passed. An opinion on a validation that did
not measure discrimination is not SATISFACTORY. A month whose performance
window has not closed does not get a calibration number. Each of those, got
wrong, produces a screen that looks complete and tells a committee something
untrue.
"""

from __future__ import annotations

import pytest

from backend.scorecard import dashboard as dash
from backend.scorecard import policy
from backend.scorecard import synthetic as synth

APP = "APPLICATION"
BEH = "BEHAVIORAL"


def _assessments(**values: float | None) -> list[policy.Assessment]:
    return [policy.assess(metric, value) for metric, value in values.items()]


def _complete(**overrides: float | None) -> list[policy.Assessment]:
    """A set of assessments that covers everything §49 requires."""
    values: dict[str, float | None] = {
        "gini": 0.42, "calibration_in_the_large": 0.05, "score_psi": 0.03,
        "implementation_mismatch_rate": 0.0, "minimum_defaults": 800,
    }
    values.update(overrides)
    return _assessments(**values)


# ------------------------------------------------------- §50 the core rule


def test_a_metric_with_no_approved_limit_has_not_passed():
    """The most common way a dashboard says "checked" when nothing was."""
    found = policy.assess("something_nobody_set_a_limit_for", 0.99)
    assert found.status == policy.NO_LIMIT
    assert found.status != policy.PASS
    assert "never as a pass" in found.to_dict()["why"]


def test_a_metric_that_was_not_measured_is_distinct_from_one_with_no_limit():
    """Two different absences that a single grey chip would conflate."""
    no_limit = policy.assess("unknown_metric", 0.5)
    not_measured = policy.assess("gini", None)
    assert no_limit.status == policy.NO_LIMIT
    assert not_measured.status == policy.NOT_MEASURED
    assert no_limit.status != not_measured.status


def test_every_seeded_limit_is_demo_policy_and_says_so():
    """§26/§80. No conventional cut-off presented as a regulatory rule."""
    body = policy.catalogue()
    assert body["every_limit_here_is_demo_policy"] is True
    assert all(limit["provenance"] == policy.DEMO_POLICY
               for limit in body["limits"])
    assert "is a regulatory threshold and none is presented as one" \
        in body["why"]


def test_the_psi_limit_says_its_cutoffs_are_a_convention():
    limit = policy.LIMITS_BY_METRIC["score_psi"]
    assert "convention" in limit.note
    assert "not a regulatory threshold" in limit.note


@pytest.mark.parametrize("observed,expected", [
    (0.18, policy.BREACH), (0.30, policy.WATCH), (0.45, policy.PASS),
])
def test_an_at_least_limit_grades_in_the_right_direction(observed, expected):
    assert policy.assess("gini", observed).status == expected


@pytest.mark.parametrize("observed,expected", [
    (0.30, policy.BREACH), (0.15, policy.WATCH), (0.02, policy.PASS),
])
def test_an_at_most_limit_grades_in_the_right_direction(observed, expected):
    assert policy.assess("score_psi", observed).status == expected


def test_a_within_limit_grades_on_magnitude_in_both_directions():
    """Over-prediction and under-prediction are both miscalibration."""
    assert policy.assess("calibration_in_the_large", 0.5).status == \
        policy.BREACH
    assert policy.assess("calibration_in_the_large", -0.5).status == \
        policy.BREACH
    assert policy.assess("calibration_in_the_large", 0.05).status == \
        policy.PASS


# ------------------------------------------------------------- §48 findings


def test_a_high_severity_finding_needs_evidence():
    """A finding that cannot point at a number is an opinion."""
    with pytest.raises(policy.PolicyError) as caught:
        policy.Finding(
            finding_id="F-1", model_id="m", model_version="1", period="2025-01",
            category="DISCRIMINATION", title="t", description="d",
            severity=policy.HIGH)
    assert "no way to answer" in str(caught.value)


def test_a_finding_with_no_category_is_refused():
    """It would have no section in the report and be silently dropped."""
    with pytest.raises(policy.PolicyError) as caught:
        policy.Finding(
            finding_id="F-1", model_id="m", model_version="1",
            period="2025-01", category="VIBES", title="t", description="d",
            severity=policy.LOW)
    assert "silently dropped" in str(caught.value)


def test_every_category_maps_to_a_report_section():
    for category in policy.CATEGORIES:
        finding = policy.Finding(
            finding_id="F", model_id="m", model_version="1",
            period="2025-01", category=category, title="t",
            description="d", severity=policy.OBSERVATION)
        assert finding.report_section


def test_a_finding_raised_from_a_breach_carries_its_numbers():
    assessment = policy.assess("gini", 0.18)
    finding = policy.finding_from(
        assessment, finding_id="F-1", model_id="m", model_version="1",
        period="2025-01", category="DISCRIMINATION",
        title="Gini below limit", description="d")
    assert finding.severity == policy.HIGH
    assert finding.observed == 0.18
    assert finding.limit_value == 0.25
    assert finding.limit_source == policy.DEMO_POLICY
    assert finding.breach is True


def test_a_watch_becomes_a_medium_finding_not_a_high_one():
    assessment = policy.assess("gini", 0.30)
    finding = policy.finding_from(
        assessment, finding_id="F-1", model_id="m", model_version="1",
        period="2025-01", category="DISCRIMINATION", title="t",
        description="d")
    assert finding.severity == policy.MEDIUM


# ------------------------------------------------------------ §49 opinion


def test_a_validation_that_did_not_measure_anything_is_incomplete():
    """Not SATISFACTORY. Grading an absence as a pass is the failure."""
    found = policy.opine(_assessments(gini=0.42), [])
    assert found.opinion == policy.INCOMPLETE
    assert "report an absence as a pass" in " ".join(found.because)


def test_a_clean_complete_validation_is_satisfactory():
    found = policy.opine(_complete(), [])
    assert found.opinion == policy.SATISFACTORY


def test_an_unreproducible_implementation_is_material_whatever_else_passed():
    """§33. The model in production is not the model that was approved."""
    found = policy.opine(_complete(implementation_mismatch_rate=0.02), [])
    assert found.opinion == policy.MATERIAL_DEFICIENCIES
    assert "not the model that was approved" in " ".join(found.because)


def test_one_breached_limit_does_not_collapse_to_material_deficiencies():
    """The ladder has five rungs and a single breach is not the bottom.

    A breach and the finding it raised are one fact. Counting them as two
    made every single breach land at MATERIAL DEFICIENCIES, which turned a
    five-level scale into a two-level one.
    """
    assessments = _complete(score_psi=0.4)
    findings = [policy.finding_from(
        a, finding_id="F-1", model_id="m", model_version="1",
        period="2025-01", category="STABILITY", title="t", description="d")
        for a in assessments if a.breached]
    found = policy.opine(assessments, findings)
    assert found.opinion == policy.REQUIRES_REMEDIATION


def test_several_breaches_at_once_are_material_deficiencies():
    assessments = _complete(score_psi=0.4, gini=0.18)
    findings = [policy.finding_from(
        a, finding_id=f"F-{i}", model_id="m", model_version="1",
        period="2025-01", category="STABILITY", title="t", description="d")
        for i, a in enumerate(assessments) if a.breached]
    found = policy.opine(assessments, findings)
    assert found.opinion == policy.MATERIAL_DEFICIENCIES


def test_an_insufficient_sample_makes_the_validation_incomplete():
    found = policy.opine(_complete(), [], sample_sufficient=False)
    assert found.opinion == policy.INCOMPLETE
    assert "arithmetic rather than evidence" in " ".join(found.because)


def test_metrics_with_no_limit_pull_the_opinion_down_to_observations():
    assessments = [*_complete(), policy.assess("unknown_thing", 0.5)]
    found = policy.opine(assessments, [])
    assert found.opinion == policy.SATISFACTORY_WITH_OBSERVATIONS
    assert "have not passed anything" in " ".join(found.because)


def test_the_opinion_says_it_was_derived_and_is_not_a_certification():
    body = policy.opine(_complete(), []).to_dict()
    assert "not chosen" in body["how_this_was_decided"]
    assert "not regulatory certification" in body["not_a_certification"]
    assert "MMS/MMG-aligned" in body["not_a_certification"]


# ------------------------------------------- §7/§44 the dashboard's maturity


def test_the_default_month_is_the_latest_matured_not_the_latest():
    """§18. The dashboard opens on a month that has outcomes."""
    context = dash.resolve(APP)
    assert context.month == context.latest_matured_month
    assert context.outcomes_available


def test_the_context_reports_both_months_separately():
    """§7. The dashboard must visibly state each."""
    body = dash.resolve(APP).to_dict()
    for key in ("latest_data_month", "latest_matured_performance_month",
                "performance_horizon_months", "outcome_maturity_status"):
        assert key in body


def test_an_unknown_model_is_refused_with_the_ones_that_exist():
    with pytest.raises(dash.DashboardError) as caught:
        dash.resolve(APP, model_kind="WISHFUL")
    assert "known:" in str(caught.value)


def test_an_immature_month_is_stability_only():
    """§44. Not a calibration number computed on nothing."""
    context = dash.Context(
        scorecard_type=APP, model_kind="INCUMBENT", month="2025-06",
        latest_data_month="2025-06", latest_matured_month="2025-01",
        horizon_months=12, outcomes_available=False, reference="DEVELOPMENT")
    assert context.stability_only
    body = context.to_dict()
    assert "STABILITY ONLY" in body["outcome_maturity_status"]
    assert "no outcome exists" in body["what_this_means"]


# -------------------------------------------------- the assembled dashboard


@pytest.fixture(scope="module")
def application_dashboard():
    return dash.build_dashboard(APP, segment_by="application_channel")


def test_the_dashboard_carries_every_section_the_brief_asks_for(
        application_dashboard):
    body = application_dashboard.to_dict()
    for section in ("summary", "data_quality", "discrimination",
                    "calibration", "stability", "variables",
                    "implementation", "segments", "findings", "comparison"):
        assert section in body, section


def test_the_dashboard_says_its_data_is_synthetic(application_dashboard):
    body = application_dashboard.to_dict()
    assert body["origin"] == synth.ORIGIN
    assert "no real customer" in body["not_client_data"]


def test_the_limits_table_has_a_status_and_a_source_for_every_row(
        application_dashboard):
    """§81's table: Metric, Observed, Limit, Status, Source."""
    for row in application_dashboard.to_dict()["performance_limits"]:
        assert row["status"] in policy.STATUSES
        if row["status"] not in (policy.NO_LIMIT, policy.NOT_MEASURED):
            assert row["source"] == policy.DEMO_POLICY


def test_the_opinion_is_derived_from_the_limits_on_the_same_dashboard(
        application_dashboard):
    body = application_dashboard.to_dict()
    breached = {row["metric"] for row in body["performance_limits"]
                if row["status"] == policy.BREACH}
    assert set(body["validation_opinion"]["breached_metrics"]) == breached


def test_stability_is_present_and_does_not_depend_on_an_outcome(
        application_dashboard):
    body = application_dashboard.to_dict()["stability"]
    assert body["score_psi"]["index"] >= 0
    assert "needs no realised outcome" in body["available_without_outcomes"]


def test_the_variables_section_separates_active_from_candidate(
        application_dashboard):
    body = application_dashboard.to_dict()["variables"]
    assert body["scope"] == "ACTIVE MODEL VARIABLES"
    assert len(body["active_variables"]) <= 6
    assert body["candidate_count"] >= 24
    assert "not a report on the model" in body["candidate_is_not_active"]
    assert all(row["in_active_model"] for row in body["variables"])


def test_asking_for_every_candidate_widens_the_scope():
    """§32. "Check all candidate variables" is a different question."""
    context = dash.resolve(APP)
    frame = dash.load_month(APP, context.month)
    body = dash.variables_section(frame, context, candidates=True)
    assert body["scope"] == "ALL CANDIDATES"
    assert len(body["variables"]) > 6


def test_the_comparison_scores_every_model_on_identical_rows(
        application_dashboard):
    """§36. A comparison across different populations measures those."""
    body = application_dashboard.to_dict()["comparison"]
    assert len(body["models"]) == 3
    assert "measures the populations" in body["identical_population"]
    assert body["best_rank_ordering"] in {m["model"] for m in body["models"]}


def test_the_recalibrated_model_does_not_change_the_ordering(
        application_dashboard):
    """§74/§36. It is a monotone transformation of the incumbent's logit.

    Its Gini must match the incumbent's to within rounding. A recalibration
    that appeared to improve discrimination would mean somebody changed more
    than they said.
    """
    models = {m["model"]: m
              for m in application_dashboard.to_dict()["comparison"]["models"]}
    # Not exact equality: the scores are stored as float32, so a slope near
    # 1.0 lands a few pairs on ties the other model does not have. The
    # ordering is preserved; the sixth decimal is storage precision.
    assert models["RECALIBRATED"]["gini"] == pytest.approx(
        models["INCUMBENT"]["gini"], abs=1e-4)
    # And it does move the level, which is the point of it.
    assert models["RECALIBRATED"]["average_predicted_pd"] != \
        models["INCUMBENT"]["average_predicted_pd"]


def test_the_implementation_section_validates_on_freshly_built_data(
        application_dashboard):
    body = application_dashboard.to_dict()["implementation"]
    assert body["status"] == "IMPLEMENTATION VALIDATED"
    assert body["mismatch_count"] == 0


def test_every_segment_carries_its_own_sample_sufficiency(
        application_dashboard):
    """§40. Ranking segments on thirty accounts each ranks the noise."""
    body = application_dashboard.to_dict()["segments"]
    assert body["split_by"] == "application_channel"
    for row in body["segments"]:
        assert row["evidence"]
    assert "ranks the noise" in body["sample_sufficiency"]


def test_findings_are_raised_from_breaches_and_watches(
        application_dashboard):
    body = application_dashboard.to_dict()
    statuses = {row["metric"]: row["status"]
                for row in body["performance_limits"]}
    raised = {f["metric"] for f in body["findings"]["findings"]}
    expected = {m for m, s in statuses.items()
                if s in (policy.BREACH, policy.WATCH)}
    assert raised == expected


def test_the_behavioral_dashboard_assembles_too():
    body = dash.build_dashboard(BEH, curves=False).to_dict()
    assert body["context"]["scorecard_type"] == BEH
    assert body["discrimination"]["gini"] > 0.2
    assert body["validation_opinion"]["opinion"] in policy.OPINIONS


def test_asking_for_a_month_that_does_not_exist_is_refused():
    with pytest.raises(dash.DashboardError) as caught:
        dash.build_dashboard(APP, month="1999-01")
    assert "not one of the available months" in str(caught.value)


def test_the_dashboard_returns_summaries_rather_than_rows(
        application_dashboard):
    """§76. Nothing sends 300,000 rows to a browser."""
    body = application_dashboard.to_dict()
    assert body["summary"]["population"] > 10_000
    # The heaviest thing on the payload is a sampled curve, not the data.
    assert len(body["discrimination"]["roc_curve"]) < 250
    assert len(body["discrimination"]["gains"]) == 10
