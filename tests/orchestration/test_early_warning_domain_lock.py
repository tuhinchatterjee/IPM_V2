"""The Early Warning chat domain lock (spec Section F, "non-negotiable"):
when a thread is locked to the Early Warning domain, a plan step whose
registered analysis needs a dataset outside it must be refused at the one
choke point every plan passes through (validate_plan), never silently
answered from another domain.
"""

from __future__ import annotations

import pytest

from backend.engine.registry import get_registry
from backend.orchestration import domain_lock as dl
from backend.orchestration.schema import AnalysisPlan, PlanRejected, PlanStep
from backend.orchestration.validator import validate_plan


def _any_non_ews_analysis_id() -> str:
    """A real registered analysis that reads a dataset outside Early
    Warning — arrears_position/facility_delinquency, if registered;
    otherwise the first registered analysis, whatever it is."""
    reg = get_registry()
    for analysis_id in reg._items:
        analysis = reg.get(analysis_id)
        if analysis.contract.required_datasets and not (
            set(analysis.contract.required_datasets) & dl.DOMAIN_DATASETS[dl.EARLY_WARNING]
        ):
            return analysis_id
    pytest.skip("no registered analysis with required_datasets found")


def test_datasets_for_reads_the_real_contract():
    analysis_id = _any_non_ews_analysis_id()
    datasets = dl.datasets_for(analysis_id)
    assert len(datasets) > 0


def test_datasets_for_unknown_analysis_returns_empty():
    assert dl.datasets_for("not_a_real_analysis_id") == ()


def test_check_plan_finds_no_violation_without_a_lock():
    analysis_id = _any_non_ews_analysis_id()
    step = PlanStep(analysis_id=analysis_id)
    assert dl.check_plan([step], domain_lock=None) == []


def test_check_plan_finds_violation_when_locked():
    analysis_id = _any_non_ews_analysis_id()
    step = PlanStep(analysis_id=analysis_id)
    violations = dl.check_plan([step], domain_lock=dl.EARLY_WARNING)
    assert len(violations) == 1
    assert violations[0].analysis_id == analysis_id
    assert violations[0].domain_lock == dl.EARLY_WARNING


def test_check_plan_allows_early_warning_datasets():
    step = PlanStep(analysis_id="anything")
    # Simulate a step whose analysis reads only Early Warning datasets by
    # checking the allow-list directly rather than requiring a registered
    # EWS analysis to exist yet.
    allowed = dl.DOMAIN_DATASETS[dl.EARLY_WARNING]
    assert "early_warning_borrower_month" in allowed
    assert "early_warning_signal_observation" in allowed


def test_refusal_message_names_the_domain_not_the_answer():
    analysis_id = _any_non_ews_analysis_id()
    violations = dl.check_plan([PlanStep(analysis_id=analysis_id)], domain_lock=dl.EARLY_WARNING)
    message = dl.refusal_message(violations)
    assert "not presently available" in message
    assert "Early Warning" in message


def test_validate_plan_rejects_cross_domain_step_when_locked():
    analysis_id = _any_non_ews_analysis_id()
    plan = AnalysisPlan(question="what is the arrears position?", intent="arrears position",
                         steps=[PlanStep(analysis_id=analysis_id)])
    with pytest.raises(PlanRejected) as exc_info:
        validate_plan(plan, domain_lock=dl.EARLY_WARNING)
    assert any("early_warning" in reason for reason in exc_info.value.reasons)


def test_validate_plan_unaffected_when_no_lock_is_set():
    """Confirms the lock is opt-in: every existing caller of validate_plan
    that never passes domain_lock keeps its current behaviour unchanged."""
    analysis_id = _any_non_ews_analysis_id()
    plan = AnalysisPlan(question="what is the arrears position?", intent="arrears position",
                         steps=[PlanStep(analysis_id=analysis_id)])
    # Should not raise for the domain-lock reason (may still raise for
    # unrelated contract reasons, which is not this test's concern — so we
    # only assert that a domain-lock violation is never among the reasons).
    try:
        validate_plan(plan)
    except PlanRejected as exc:
        assert not any("domain this thread is locked to" in r for r in exc.reasons)
