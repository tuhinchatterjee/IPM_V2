"""
The gate, and the claim, and why they are not the same number.

The single most dangerous thing this product can do is describe itself as more
accurate than its evidence supports. These tests exist to make that difficult.
"""

from __future__ import annotations

from intelligence_factory import certify, metrics


class _Rate:
    def __init__(self, point, lower, total):
        self.point, self.lower, self.total = point, lower, total
        self.successes = int(round(point * total / 100))
        self.reportable = total >= metrics.MIN_OBSERVATIONS

    def supports(self, target):
        return self.reportable and self.lower >= target

    def to_dict(self):
        return {"point_pct": self.point, "lower_pct": self.lower,
                "total": self.total}


class _Accuracy:
    def __init__(self, precision, outcome, critical=()):
        self.rates = {"accepted_precision": precision, "outcome": outcome}
        self.critical_failures = list(critical)
        self.accepted, self.abstained = precision.total, 0

    @property
    def coverage(self):
        return _Rate(100.0, 100.0, self.accepted)

    def claim(self, target):
        return {"sentence": f"claim about {target}"}


def _report(precision_pct, outcome_pct=100.0, total=60, critical=()):
    report = certify.Report(mode="certification", started_at="now")
    report.cases = [object()]
    report.accuracy = _Accuracy(
        _Rate(precision_pct, precision_pct - 6, total),
        _Rate(outcome_pct, outcome_pct - 6, total), critical)
    return report


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_a_clean_run_passes():
    assert _report(100.0).passed


def test_one_critical_failure_blocks_whatever_the_aggregate_says():
    """A wrong answer on a critical case is not a percentage point."""
    report = _report(100.0, critical=("hold-adv-1: answered a bare measure",))
    assert not report.passed
    assert any("critical" in b for b in report.blockers)


def test_precision_below_the_gate_blocks():
    report = _report(90.0)
    assert not report.passed
    assert any("below the" in b for b in report.blockers)


def test_one_wrong_kind_of_outcome_blocks_even_at_high_precision():
    """Answering where it should have asked is not 98% right."""
    report = _report(98.0, outcome_pct=98.0)
    assert not report.passed
    assert any("clarified or refused" in b for b in report.blockers)


def test_a_run_with_no_cases_never_passes():
    report = certify.Report(mode="certification", started_at="now")
    assert not report.passed


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


def test_the_gate_does_not_certify_the_claim():
    """A build may ship and still support no rate claim at all.

    Twenty accepted answers cannot support 95% however they come out. Gating on
    the interval would fail every release forever; reporting it separately is
    what keeps a passing build from being called 99.99% accurate.
    """
    report = _report(100.0, total=20)
    assert report.passed
    evidence = certify._evidence(report.accuracy)
    assert evidence["reportable"] is False
    assert "no rate claim is supportable" in evidence["sentence"]


def test_a_perfect_run_still_refuses_to_claim_99_99():
    accuracy = metrics.Accuracy()
    accuracy.add("accepted_precision", 200, 200)
    claim = accuracy.claim(99.99)
    assert "not yet demonstrated" in claim["sentence"]
    assert "29,958" in claim["sentence"] or "29958" in str(claim)


def test_the_evidence_says_how_many_cases_a_claim_would_need():
    evidence = certify._evidence(_report(100.0).accuracy)
    assert evidence["cases_for_99_99"] == metrics.cases_needed(99.99)
    assert evidence["cases_for_gate"] == metrics.cases_needed(
        certify.GATE_PRECISION)


def test_a_wilson_lower_bound_is_never_the_point_estimate():
    """The normal approximation has zero width at p=1, which is why it is not
    used: a hundred clean cases would "prove" 100%."""
    lower, upper = metrics.wilson(100, 100)
    assert lower < 100.0 <= upper


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_the_cost_is_reported_before_a_run_spends_anything(monkeypatch):
    from intelligence_factory import holdout

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    estimate = certify.cost_estimate(list(holdout.CASES))
    assert estimate["model_calls_if_live"] == 0
    assert estimate["provider_configured"] is False
    assert estimate["turns"] == holdout.turn_count()


def test_a_configured_provider_is_costed_per_turn(monkeypatch):
    from intelligence_factory import holdout

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    estimate = certify.cost_estimate(list(holdout.CASES))
    assert estimate["model_calls_if_live"] == holdout.turn_count() * 2
