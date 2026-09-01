"""
Change-isolation experiments. §68.

This module exists to set one boolean honestly. Most of these tests are
about the cases where it must come back False.
"""

from __future__ import annotations

import pytest

from backend.continuous import isolation, measurement, partitions


def _scores(n: int, value: float, *, offset: float = 0.0) -> dict[str, float]:
    return {f"case_{i:03d}": value + (offset if i % 2 else 0.0)
            for i in range(n)}


def _arm(label: str, n: int, value: float, *, changes=frozenset(),
         **kwargs) -> isolation.Arm:
    return isolation.Arm(label=label, changes=changes,
                         scores=_scores(n, value),
                         families={f"case_{i:03d}":
                                   ("ECL" if i % 2 else "Migration")
                                   for i in range(n)},
                         **kwargs)


def _experiment(n: int = 60, before: float = 0.80, after: float = 0.86,
                **kwargs) -> isolation.Experiment:
    defaults = dict(
        change_kind="TEACHING_CASE_BATCH", change_id="batch-17",
        baseline=_arm("baseline", n, before),
        treatment=_arm("treatment", n, after, changes=frozenset({"batch-17"})))
    defaults.update(kwargs)
    return isolation.Experiment(**defaults)


# ------------------------------------------------------- what earns isolated


def test_a_clean_two_arm_experiment_is_isolated_and_says_so():
    result = isolation.run(_experiment(), by="ops@bank")
    assert result.isolated is True
    assert result.why_not_isolated == ""
    assert result.overall.points == pytest.approx(6.0, abs=0.01)

    contribution = result.contribution()
    assert contribution.isolated is True
    assert contribution.source == "Teaching Cases"
    assert result.experiment_id in contribution.evidence


def test_the_contribution_is_the_only_place_isolated_becomes_true():
    """A Contribution built anywhere else defaults to not isolated."""
    assert measurement.Contribution(source="Teaching Cases",
                                    points=6.0).isolated is False


# ------------------------------------------------ what does not earn it


def test_two_changes_in_one_arm_is_a_joint_effect_not_an_isolated_one():
    experiment = _experiment()
    experiment.treatment.changes = frozenset({"batch-17", "routing-v4"})
    result = isolation.run(experiment, by="ops@bank")

    assert result.isolated is False
    assert "2 changes" in result.why_not_isolated
    assert "not an isolated one" in result.why_not_isolated
    # The measurement is still real and still reported.
    assert result.overall.points == pytest.approx(6.0, abs=0.01)
    assert result.contribution().isolated is False


def test_arms_scored_on_different_cases_are_not_a_controlled_comparison():
    experiment = _experiment()
    experiment.treatment.scores.pop("case_000")
    experiment.treatment.scores["case_999"] = 0.9
    result = isolation.run(experiment, by="ops@bank")

    assert result.isolated is False
    assert "different cases" in result.why_not_isolated
    assert "measures the cases as much as the change" in result.why_not_isolated


def test_an_arm_that_also_removes_something_is_not_baseline_plus_one():
    experiment = _experiment()
    experiment.baseline.changes = frozenset({"routing-v3"})
    experiment.treatment.changes = frozenset({"batch-17"})
    result = isolation.run(experiment, by="ops@bank")
    assert result.isolated is False
    assert "removes routing-v3" in result.why_not_isolated


def test_a_clean_design_on_too_few_cases_is_still_too_few_cases():
    result = isolation.run(_experiment(n=12), by="ops@bank")
    assert result.isolated is False
    assert "The design is clean" in result.why_not_isolated
    assert str(measurement.MINIMUM_CASES) in result.why_not_isolated


def test_an_empty_arm_reports_nothing_rather_than_a_delta():
    experiment = _experiment()
    experiment.treatment.scores = {}
    result = isolation.run(experiment, by="ops@bank")
    assert result.isolated is False
    assert "measures nothing" in result.why_not_isolated


# ------------------------------------------------------------- the refusals


def test_a_live_provider_arm_refuses_to_run_without_authorization():
    """§68: no automatic expensive live A/B. An A/B doubles the calls."""
    experiment = _experiment(mode=isolation.LIVE_PROVIDER)
    with pytest.raises(isolation.IsolationError) as caught:
        isolation.run(experiment, by="ops@bank")
    message = str(caught.value)
    assert "without authorization" in message
    assert "doubles the call count" in message


def test_a_live_provider_arm_runs_once_somebody_authorizes_it():
    experiment = _experiment(mode=isolation.LIVE_PROVIDER)
    result = isolation.run(experiment, by="ops@bank",
                           authorization="cro@bank approved 2026-08-30")
    assert result.mode == isolation.LIVE_PROVIDER
    assert result.authorization.startswith("cro@bank")


def test_no_experiment_may_run_against_the_sealed_holdout():
    experiment = _experiment(partition=partitions.SEALED_HOLDOUT)
    with pytest.raises(isolation.IsolationError) as caught:
        isolation.run(experiment, by="ops@bank")
    assert "stops it being a holdout" in str(caught.value)


def test_an_unknown_change_kind_cannot_attribute_anything():
    experiment = _experiment(change_kind="VIBES")
    with pytest.raises(isolation.IsolationError) as caught:
        isolation.run(experiment, by="ops@bank")
    assert "cannot name what it changed" in str(caught.value)


def test_an_unsigned_experiment_is_not_evidence():
    with pytest.raises(isolation.IsolationError):
        isolation.run(_experiment(), by="")


def test_every_change_kind_maps_to_a_real_attribution_source():
    """An experiment must not be able to invent a waterfall source."""
    assert set(isolation.CHANGE_KINDS.values()) <= set(measurement.SOURCES)


def test_the_four_worked_examples_from_the_brief_are_all_expressible():
    for kind in ("TEACHING_CASE_BATCH", "ROUTING_CHANGE", "BRAIN_PATCH",
                 "REGULATORY_LEARNING"):
        assert kind in isolation.CHANGE_KINDS


# ------------------------------------------------------------- what it shows


def test_a_critical_regression_is_the_finding_whatever_the_average_did():
    experiment = _experiment(before=0.80, after=0.90)
    experiment.treatment.critical_failures = frozenset({"case_003"})
    result = isolation.run(experiment, by="ops@bank")

    assert result.critical_regressions == ("case_003",)
    assert result.overall.verdict == measurement.REGRESSED
    assert "whatever the average did" in result.sentence()


def test_a_fixed_critical_case_is_reported_as_a_fix():
    experiment = _experiment()
    experiment.baseline.critical_failures = frozenset({"case_005"})
    result = isolation.run(experiment, by="ops@bank")
    assert result.critical_fixes == ("case_005",)
    assert result.critical_regressions == ()


def test_the_result_carries_a_case_family_delta():
    result = isolation.run(_experiment(), by="ops@bank")
    assert set(result.by_family) == {"ECL", "Migration"}
    for change in result.by_family.values():
        assert change.cases > 0


def test_the_result_carries_a_six_dimension_delta_where_both_arms_scored():
    experiment = _experiment()
    experiment.baseline.dimensions = {"Analytical Design": 0.80,
                                      "Judgment & Presentation": 0.75}
    experiment.treatment.dimensions = {"Analytical Design": 0.86,
                                       "Judgment & Presentation": 0.75}
    result = isolation.run(experiment, by="ops@bank")
    assert set(result.by_dimension) == {"Analytical Design",
                                        "Judgment & Presentation"}
    assert result.by_dimension["Analytical Design"].points == pytest.approx(
        6.0, abs=0.01)
    assert result.by_dimension["Judgment & Presentation"].points == 0.0


def test_latency_and_cost_deltas_are_reported():
    experiment = _experiment()
    experiment.baseline.latency_ms, experiment.baseline.cost_units = 900.0, 1.0
    experiment.treatment.latency_ms = 1450.0
    experiment.treatment.cost_units = 1.4
    result = isolation.run(experiment, by="ops@bank")
    assert result.latency_delta_ms == pytest.approx(550.0)
    assert result.cost_delta_units == pytest.approx(0.4)


def test_an_arm_without_scores_is_handed_to_the_supplied_evaluator():
    """Nothing here scores anything — that is what keeps one scorer."""
    calls: list[str] = []

    def evaluate(arm: isolation.Arm) -> isolation.Arm:
        calls.append(arm.label)
        arm.scores = _scores(40, 0.8 if arm.label == "baseline" else 0.85)
        return arm

    experiment = isolation.Experiment(
        change_kind="ROUTING_CHANGE", change_id="r4",
        baseline=isolation.Arm("baseline"),
        treatment=isolation.Arm("treatment", changes=frozenset({"r4"})))
    result = isolation.run(experiment, by="ops@bank", evaluate=evaluate)

    assert calls == ["baseline", "treatment"]
    assert result.isolated is True


# ------------------------------------------------------------ the set


def test_non_isolated_experiments_stay_in_the_contribution_list():
    """Dropping them would grow the residual with no explanation."""
    clean = isolation.run(_experiment(), by="ops@bank")
    joint = _experiment(change_kind="ROUTING_CHANGE", change_id="r4")
    joint.treatment.changes = frozenset({"r4", "batch-17"})
    joint_result = isolation.run(joint, by="ops@bank")

    contributions = isolation.contributions([clean, joint_result])
    assert len(contributions) == 2
    assert [c.isolated for c in contributions] == [True, False]


def test_the_summary_only_adds_up_the_isolated_ones():
    clean = isolation.run(_experiment(), by="ops@bank")
    small = isolation.run(_experiment(n=12, change_id="batch-18"),
                          by="ops@bank")
    body = isolation.summary([clean, small])
    assert body["experiments"] == 2
    assert body["isolated"] == 1
    assert body["not_isolated"] == 1
    assert set(body["by_source"]) == {"Teaching Cases"}
    assert "different claim" in body["note"]


def test_the_result_serialises_with_its_provenance():
    result = isolation.run(_experiment(), by="ops@bank")
    body = result.to_dict()
    assert body["isolated"] is True
    assert body["attributed_source"] == "Teaching Cases"
    assert body["ran_by"] == "ops@bank"
    assert body["mode"] == isolation.DETERMINISTIC
    assert "by_case_family" in body and "by_dimension" in body
