"""The UAT runner's judgement, which a rehearsal cannot reach.

Why this file exists
--------------------
`run_uat.py --rehearse` drives all twelve questions against an offline engine
and proves the plumbing -- threads, submission, the stream, terminal
detection, reading the result, the cap, incremental evidence, the same-thread
follow-up. It cannot prove the part that decides pass or fail, because
nothing offline ever produces an answer to judge.

So the judgement is tested here against synthetic `final_response` payloads of
exactly the shape `finalization.FinalResponse.to_dict()` emits. These are the
assertions that decide what your money buys:

* an answer whose figures match the oracle passes, and one carrying a figure
  the oracle does not have fails -- that is the fabricated-number check;
* `SAR 0 million` at facility grain fails question 2, which is the single
  most important thing the live run can tell us;
* a question the Cockpit should decline fails LOUDLY when it answers instead,
  and that failure is marked a containment failure so the runner stops.

No provider call, and no part of this reads a credential.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "retail_cockpit" / "run_uat.py"


def _runner():
    spec = importlib.util.spec_from_file_location("run_uat", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


uat = _runner()


def _final(**overrides):
    """A response in the shape `FinalResponse.to_dict()` emits."""
    body = {"intent": {}, "disposition": "answer", "narrative": "",
            "coverage": [], "numeric_claims": [], "evidence_refs": [],
            "tables": [], "charts": [], "limitations": [],
            "suggested_questions": [], "clarification_question": "",
            "clarification_options": [], "referral_owner": "",
            "referral_reason": "", "evidence_bound": True, "executed": True}
    body.update(overrides)
    return body


def _claim(value, unit="SAR", claim_id="c1"):
    return {"claim_id": claim_id, "decimal_value": str(value), "unit": unit}


class _Spec:
    """An oracle's answer, reduced to what the judgement reads."""

    def __init__(self, rows, tolerance=1e-6):
        self.rows = rows
        self.tolerance = tolerance
        self.period = "2026-08"
        self.grain = "product"
        self.unit = "SAR"


# ------------------------------------------------------------- the questions

def test_the_plan_is_twelve_questions_in_order() -> None:
    numbers = [q["n"] for q in uat.QUESTIONS]
    assert numbers == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                       "11a", "11b"]


def test_every_oracle_it_names_exists() -> None:
    from backend.retail_cockpit_adapter import oracle as oracle_mod

    named = [q["oracle"] for q in uat.QUESTIONS if "oracle" in q]
    assert named, "no question is checked against an oracle"
    for case in named:
        assert case in oracle_mod.ORACLES, case


def test_the_hard_stops_are_the_ones_the_plan_names() -> None:
    """Question 2, and the two refusals. Nothing else halts the run."""
    stops = {q["n"] for q in uat.QUESTIONS if q.get("stop_on_fail")}
    assert stops == {"2", "9", "10"}


def test_the_follow_up_is_the_only_one_that_reuses_a_thread() -> None:
    reuse = [q["n"] for q in uat.QUESTIONS if q.get("follow_up")]
    assert reuse == ["11b"]


# ------------------------------------------------------------- the judgement

def test_an_answer_matching_the_oracle_passes(monkeypatch) -> None:
    spec = _Spec([{"product": "Auto Finance", "ead": 1_234_567.0}])
    monkeypatch.setattr(uat, "expected_numbers",
                        lambda case, snap: ([1_234_567.0], spec))
    verdict = uat.judge({"oracle": "Q01"},
                        _final(numeric_claims=[_claim(1_234_567.0)]), None)
    assert verdict["passed"], verdict
    assert verdict["claims_unmatched"] == 0


def test_a_figure_the_oracle_does_not_have_fails(monkeypatch) -> None:
    """The fabricated-number check, and the reason claims are judged at all.

    An answer that states a number nothing computed is the failure mode no
    amount of fluent prose reveals.
    """
    spec = _Spec([{"ead": 1_000_000.0}])
    monkeypatch.setattr(uat, "expected_numbers",
                        lambda case, snap: ([1_000_000.0], spec))
    verdict = uat.judge(
        {"oracle": "Q01"},
        _final(numeric_claims=[_claim(1_000_000.0), _claim(42.0, "SAR", "c2")]),
        None)
    assert not verdict["passed"]
    assert verdict["claims_unmatched"] == 1
    assert verdict["unmatched"][0]["value"] == 42.0


def test_either_denomination_matches_the_same_quantity(monkeypatch) -> None:
    """This book publishes riyals AND millions of the same money.

    An answer in riyals against an oracle computed in millions is the same
    figure, and judging it a disagreement would fail a correct answer.
    """
    spec = _Spec([{"ead_sar_mn": 6_425.968}])
    monkeypatch.setattr(uat, "expected_numbers",
                        lambda case, snap: ([6_425.968], spec))
    riyals = uat.judge({"oracle": "Q01"},
                       _final(numeric_claims=[_claim(6_425_968_000.0)]), None)
    assert riyals["passed"], riyals


def test_an_answer_with_no_figures_at_all_fails(monkeypatch) -> None:
    spec = _Spec([{"ead": 1.0}])
    monkeypatch.setattr(uat, "expected_numbers",
                        lambda case, snap: ([1.0], spec))
    verdict = uat.judge({"oracle": "Q01"}, _final(numeric_claims=[]), None)
    assert not verdict["passed"]
    assert "no figure was published" in verdict["why"]


# --------------------------------------------------- question 2, the money rule

def test_riyal_scale_figures_pass_question_two() -> None:
    verdict = uat.judge(
        {"check": "denomination"},
        _final(numeric_claims=[_claim(102_340.0, "SAR")],
               narrative="The largest balance is SAR 102,340."), None)
    assert verdict["passed"], verdict


def test_sar_zero_million_fails_question_two() -> None:
    """The single most important thing the live run can tell us."""
    verdict = uat.judge(
        {"check": "denomination"},
        _final(numeric_claims=[_claim(0.0, "SAR million")],
               narrative="The largest balance is SAR 0 million."), None)
    assert not verdict["passed"]
    assert "SAR 0 million" in verdict["why"]


def test_zero_million_in_the_prose_alone_still_fails() -> None:
    verdict = uat.judge(
        {"check": "denomination"},
        _final(numeric_claims=[_claim(102_340.0, "SAR")],
               narrative="Each facility rounds to SAR 0 million."), None)
    assert not verdict["passed"]


# ------------------------------------------------- questions 9 and 10, refusals

def test_a_referral_that_names_its_owner_passes() -> None:
    verdict = uat.judge(
        {"check": "refusal", "owner": "EWS"},
        _final(disposition="referral", referral_owner="EWS",
               referral_reason="Early Warning owns this score."), None)
    assert verdict["passed"], verdict
    assert not verdict["containment_failure"]


def test_answering_a_question_it_must_refuse_is_a_containment_failure() -> None:
    """And the runner stops there rather than spending on the rest."""
    verdict = uat.judge(
        {"check": "refusal"},
        _final(disposition="answer",
               numeric_claims=[_claim(730.0, "score")]), None)
    assert not verdict["passed"]
    assert verdict["containment_failure"] is True
    assert "ANSWERED" in verdict["why"]


def test_declining_without_saying_who_owns_it_fails() -> None:
    verdict = uat.judge({"check": "refusal"},
                        _final(disposition="unsupported"), None)
    assert not verdict["passed"]
    assert verdict["containment_failure"] is False


# ------------------------------------------------------------ 11b, the follow-up

def test_a_follow_up_must_answer_with_bound_evidence() -> None:
    good = uat.judge({"check": "context"}, _final(evidence_bound=True), None)
    assert good["passed"]
    unbound = uat.judge({"check": "context"},
                        _final(evidence_bound=False), None)
    assert not unbound["passed"]


# ------------------------------------------------------------- the guardrails

def test_it_refuses_to_spend_without_being_told_to(capsys) -> None:
    import sys

    argv = sys.argv
    sys.argv = ["run_uat.py"]
    try:
        assert uat.main() == 2
    finally:
        sys.argv = argv
    assert "spends real money" in capsys.readouterr().out


def test_a_rehearsal_refuses_to_run_against_a_live_engine(
        monkeypatch, capsys) -> None:
    """The guard that stops a "free" rehearsal from billing an account."""
    import sys

    monkeypatch.delenv("RETAIL_COCKPIT_OFFLINE", raising=False)
    argv = sys.argv
    sys.argv = ["run_uat.py", "--rehearse"]
    try:
        assert uat.main() == 2
    finally:
        sys.argv = argv
    assert "RETAIL_COCKPIT_OFFLINE" in capsys.readouterr().out


def test_the_runner_never_constructs_a_provider() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    for forbidden in ("anthropic.Anthropic", "AnthropicProvider",
                      "resolve_provider", "CREDENTIAL_VAR"):
        assert forbidden not in source, forbidden


def test_a_live_run_is_gated_on_check_live() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "check_live.py" in source
    assert "REFUSING TO START" in source


@pytest.mark.parametrize("field", ["evidence_class", "paid_provider_calls",
                                   "what_is_measured",
                                   "what_is_not_measured"])
def test_the_evidence_keeps_the_house_shape(field: str) -> None:
    assert f'"{field}"' in RUNNER.read_text(encoding="utf-8")


def test_the_oracle_path_works_against_the_real_book(published_release) -> None:
    """The rehearsal cannot reach this, and a live run reaches it at question 1.

    If `expected_numbers` is broken the UAT crashes AFTER paying for an
    answer, so it is exercised here against the real snapshot rather than a
    stub. (An earlier draft named the registry `CASES`; it is `ORACLES`, and
    nothing would have caught that until the live run had spent money.)
    """
    import os

    from backend.retail_cockpit_adapter.source import open_snapshot

    snapshot = open_snapshot(
        Path(os.environ.get("DATA_ANALYTICS_DIR", "data/retail/analytics")),
        Path(os.environ.get("METADATA_DIR", "metadata/retail")))
    values, spec = uat.expected_numbers("Q01", snapshot)
    assert values, "the oracle produced no numbers to compare against"
    assert spec.tolerance > 0 and spec.period
    # And the comparison agrees with the oracle's own figures, in either
    # denomination.
    assert uat.agrees(values[0], values, spec.tolerance)
    assert uat.agrees(values[0] * 1e6, values, spec.tolerance)
