"""
The layered scorecard evaluation and the zero-tolerance suite. §A5-§A7.

The critical suite is the part with teeth. Every check in it runs against the
real engine, and each one is a failure mode that fails in the FLATTERING
direction — an immature cohort scored as though it had matured produces a
beautiful default rate, a reversed score direction produces a Gini of the
right magnitude. None of them announces itself, which is why they are
asserted rather than watched for.

The evaluation module is checked for a different property: that it says what
its numbers are numbers OF. A structural readiness figure presented as a
model accuracy figure is the most flattering mistake available in this phase,
so the tests below check the refusal as well as the arithmetic.
"""

from __future__ import annotations

import pytest

from backend.assurance import dimensions as dims
from backend.scorecard import critical
from backend.scorecard import evaluation as ev
from backend.scorecard import holdout as hold
from intelligence_factory.teaching import scorecard as dev


@pytest.fixture(scope="module")
def development():
    return dev.cases()


@pytest.fixture(scope="module")
def critical_result():
    return critical.run()


# --------------------------------------------------- §A7 the critical suite


def test_the_critical_suite_covers_every_failure_mode_the_brief_names():
    """§A7 lists twenty-two. Fewer would mean one is unwatched."""
    ids = {check.id for check in critical.CHECKS}
    for name in ("immature_outcome", "score_direction_declared",
                 "bad_default_inversion", "woe_mapping_mismatch",
                 "wrong_model_version", "scorecard_mixing", "raw_versus_woe",
                 "psi_baseline", "csi_is_not_psi", "ks_reversal",
                 "gini_direction", "pd_bounds", "equation_mismatch",
                 "future_leakage", "empty_default_sample", "tiny_segment",
                 "mape_near_zero", "comparison_population",
                 "report_reconciliation", "no_certification_claim",
                 "candidate_not_activated", "retirement_key"):
        assert name in ids, name
    assert len(critical.CHECKS) >= 22


def test_zero_critical_failures(critical_result):
    """§A7's requirement, stated as the brief states it."""
    assert critical_result.clean, "\n".join(
        f"{o.check_id}: {o.detail}" for o in critical_result.failures)
    assert critical_result.failures == []


def test_every_check_says_why_it_is_critical():
    """A check whose severity nobody can explain gets downgraded the first
    time it is inconvenient."""
    for check in critical.CHECKS:
        assert len(check.why_critical) > 30, check.id
        assert check.dimension in dims.DIMENSIONS, check.id


def test_a_check_that_cannot_run_counts_as_a_failure():
    """A suite that reported a crashed check as a pass would be worse than
    no suite: it would be a green light nobody looked behind."""
    broken = critical.Check(
        "broken", "a check that raises something unexpected",
        "would otherwise be reported as a pass",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    original = critical.CHECKS
    try:
        critical.CHECKS = (broken,)
        result = critical.run()
    finally:
        critical.CHECKS = original
    assert not result.clean
    assert "could not run" in result.failures[0].detail


def test_the_suite_reports_failures_by_name_not_by_count(critical_result):
    payload = critical_result.to_dict()
    assert payload["checks"] == len(critical.CHECKS)
    assert payload["passed"] + payload["failed"] == payload["checks"]
    assert isinstance(payload["failures"], list)


def test_the_catalogue_describes_the_suite_without_running_it():
    entries = critical.catalogue()
    assert len(entries) == len(critical.CHECKS)
    for entry in entries:
        assert entry["failure"] and entry["why_critical"]


# ------------------------------------------------ §A5 reference expectations


def test_expectations_cover_everything_the_brief_lists():
    """§A5's seventeen items."""
    payload = ev.expectations("APPLICATION")
    for key in ("intent", "scorecard_type", "model_version", "period",
                "maturity", "population", "metric_definitions", "variables",
                "equation", "relationships", "plan", "query", "result",
                "invariants", "chart_type", "clarification",
                "controlled_failure"):
        assert key in payload, key


def test_expectations_carry_no_numeric_answer():
    """§A5: do not teach exact numeric answers to the live planner before
    execution. The rule is met by there being no number to teach."""
    import re

    payload = ev.expectations("APPLICATION")
    figure = re.compile(r"\b0\.\d{3,}\b")
    assert not figure.search(repr(payload))
    assert payload["carries_no_figure"] is True


def test_expectations_name_the_variables_that_may_not_be_scored():
    payload = ev.expectations("APPLICATION")
    assert payload["variables"]["not_scoreable"]
    overlap = (set(payload["variables"]["not_scoreable"])
               & set(payload["variables"]["in_model"]))
    assert overlap == set(), (
        f"{overlap} is both in the model and marked not scoreable")


def test_expectations_state_the_declared_score_direction():
    payload = ev.expectations("APPLICATION")
    assert payload["equation"]["score_direction"] in (
        "HIGHER_SCORE_IS_BETTER", "LOWER_SCORE_IS_BETTER")


def test_expectations_on_an_open_month_say_when_the_window_closes():
    month = dev.OPEN_WINDOW[0]
    payload = ev.expectations("APPLICATION", month=month)
    assert payload["maturity"].startswith("NOT MATURED")
    assert payload["performance_window_closes"] > month


# ------------------------------------------------------ §A6 layered scoring


def test_every_dimension_is_reached_by_at_least_one_family():
    """A dimension nothing exercises is a dimension whose score is an
    empty claim."""
    assert ev.coverage()["unreached"] == []


def test_every_family_is_mapped_to_a_dimension(development):
    families = {c.family_id for c in development}
    assert families <= set(ev.FAMILY_LAYERS)


def test_the_layers_register_the_items_the_brief_names():
    """§A6's list, under the platform's own six dimensions."""
    flat = {item for items in ev.LAYERS.values() for item in items}
    for item in ("outcome_maturity", "metric_definition", "auc", "gini",
                 "ks", "brier", "log_loss", "guarded_mape", "score_psi",
                 "variable_csi", "information_value", "score_replication",
                 "causality_language", "two_decimal_presentation",
                 "controlled_failure", "maturity_guard",
                 "dashboard_report_reconciliation"):
        assert item in flat, item


def test_the_result_says_what_its_numbers_are_numbers_of(development):
    result = ev.run(development, with_critical=False).to_dict()
    assert result["basis"] == ev.STRUCTURAL
    assert "No model was asked anything" in result["basis_means"]


def test_a_live_basis_is_refused_rather_than_faked(development):
    """Reporting a structural figure under the live basis would present a
    readiness check as an accuracy score."""
    with pytest.raises(ev.EvaluationError, match="live-model evaluation"):
        ev.run(development, basis=ev.LIVE)


def test_the_development_corpus_is_fully_settled(development):
    result = ev.run(development, with_critical=False).to_dict()
    assert result["cases"] == len(development)
    assert result["unsettled"] == []


def test_the_holdout_is_fully_settled():
    result = ev.run(hold.build(), with_critical=False).to_dict()
    assert result["unsettled"] == []


def test_the_settle_check_can_actually_fail():
    """A check that never fails is a check nobody has tested."""
    class Bogus:
        case_id = "bogus"
        family_id = "SCORECARD_DISCRIMINATION"
        difficulty = "COMPLEX"
        analytical_plan_contract = {"scorecard_type": "MORTGAGE"}
        period_contract: dict = {}

    result = ev.run([Bogus()], with_critical=False).to_dict()
    assert result["unsettled"]
    assert "not a registered scorecard type" in result["unsettled"][0]["why"]


def test_an_immature_month_with_an_outcome_metric_is_unsettled():
    """The rule the module is built around, checked through the evaluator."""
    class Trap:
        case_id = "trap"
        family_id = "SCORECARD_DISCRIMINATION"
        difficulty = "ADVERSARIAL"
        analytical_plan_contract = {"scorecard_type": "APPLICATION",
                                    "requires_matured_outcome": True}
        period_contract = {"month": dev.OPEN_WINDOW[0]}

    result = ev.run([Trap()], with_critical=False).to_dict()
    assert result["unsettled"]
    assert "window has not closed" in result["unsettled"][0]["why"]


def test_results_are_reported_by_family_and_by_difficulty(development):
    """§A6: report by family and difficulty."""
    result = ev.run(development, with_critical=False).to_dict()
    assert len(result["by_family"]) == 23
    assert len(result["by_difficulty"]) >= 4
    for bucket in result["by_family"].values():
        assert "rate" in bucket and "cases" in bucket


def test_a_critical_failure_is_never_averaged_into_a_rate(development):
    """§A6: do not average away critical failures."""
    result = ev.run(development[:20]).to_dict()
    assert result["critical_failures_are_not_averaged"] is True
    assert result["critical"] is not None
    for bucket in result["by_dimension"].values():
        assert "critical" not in bucket
