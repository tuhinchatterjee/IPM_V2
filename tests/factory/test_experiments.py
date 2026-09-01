"""
§30-§34 and §40-§42 — choosing a model, choosing thresholds, and refusing to
claim more than the sample supports.

The two sentences the whole file defends
-----------------------------------------
    "Do not select a model based only on average score.
     Require zero critical-case regressions."   §30

    "Do not claim 99.99% until statistically supported."   §40

Both are about the same temptation: a number that is technically computed and
rhetorically wrong. An arm that gains two points overall and breaks one
grounding case has not won. A precision of 100% over forty cases is not 100%.
"""

from __future__ import annotations

import random

import pytest

from backend.teaching import classifiers as cl
from backend.teaching import failures as fl
from backend.teaching import policy as pol
from intelligence_factory import experiments as ex
from intelligence_factory import holdout as ho


class _Case:
    def __init__(self, index: int, family: str = "ECL_MOVEMENT"):
        self.id = f"c{index:03d}"
        self.family = family
        self.turns = [1]


def _cases(count: int = 150) -> list[_Case]:
    families = ["ECL_MOVEMENT", "AMBIGUITY", "GRAIN_RECONCILIATION"]
    return [_Case(i, families[i % 3]) for i in range(count)]


def _runner(*, accuracy: float, seed: int = 1, break_critical: str = "",
            abstain_every: int = 9):
    rng = random.Random(seed)

    def run(case: _Case) -> ex.Outcome:
        index = int(case.id[1:])
        behaviour = (ex.CLARIFIED if index % abstain_every == 0
                     else ex.ANSWERED)
        if behaviour != ex.ANSWERED:
            return ex.Outcome(case_id=case.id, family=case.family,
                              passed=True, behaviour=behaviour)
        ok = rng.random() < accuracy
        if break_critical and case.id == break_critical:
            ok = False
        return ex.Outcome(
            case_id=case.id, family=case.family, passed=ok,
            behaviour=ex.ANSWERED,
            failure="" if ok else ("GRAIN" if case.id == break_critical
                                   else "INTERPRETATION"),
            dimensions={"plan": ok, "invariants": ok},
            input_tokens=2000, output_tokens=500, latency_ms=11.0)

    return run


# ============================================================ §34 the taxonomy


def test_every_category_section_34_names_is_declared():
    required = {
        "INTENT", "SAME_TURN_COREFERENCE", "MULTI_TURN_CONTEXT",
        "OBJECTIVE_OMISSION", "CONCEPT", "AMBIGUITY", "DATASET",
        "RELATIONSHIP", "PERIOD", "GRAIN", "PLAN", "QUERY", "EXECUTION",
        "INVARIANT", "GROUNDING", "INTERPRETATION", "VISUALIZATION", "TRACE",
        "SCOPE", "PERMISSION", "UNSUPPORTED", "PROVIDER", "COST_BUDGET",
        "CONTROLLED_FAILURE"}
    assert required == set(fl.IDS)


def test_a_correct_abstention_is_not_counted_as_a_defect():
    """An accuracy figure counting a correct abstention as a failure pushes
    the product towards answering questions it should decline."""
    assert not fl.is_defect("UNSUPPORTED")
    assert not fl.is_defect("CONTROLLED_FAILURE")
    assert not fl.is_defect("COST_BUDGET")
    assert fl.is_defect("GROUNDING")


def test_an_unknown_category_counts_as_a_defect():
    """A value nobody recognises must not be the one that quietly improves the
    score."""
    assert fl.is_defect("SOMETHING_ELSE")


def test_every_category_says_what_a_reviewer_is_looking_at():
    for category in fl.CATEGORIES:
        assert len(category.looks_like) > 40
        assert category.stage in fl.STAGES


def test_the_tally_reports_the_zeroes_too():
    """A taxonomy reported only where it fired cannot show what is not
    happening."""
    counts = fl.tally(["GRAIN"])
    assert set(counts) == set(fl.IDS)
    assert counts["GRAIN"] == 1
    assert counts["PROVIDER"] == 0


# =========================================================== §42 the estimate


def test_an_estimate_costs_nothing_and_says_what_a_run_would():
    found = ex.estimate(_cases(100), arms=[ex.BASELINE, ex.CANDIDATE_B],
                        price=ex.Price(0.003, 0.015))
    assert found.calls > 0
    assert found.cost > 0
    assert not found.nominal
    assert "model calls" in found.sentence()


def test_an_estimate_without_a_price_says_the_cost_is_unknown():
    """Zero because no price was supplied is a different fact from zero
    because the run is free."""
    found = ex.estimate(_cases(10))
    assert found.nominal
    assert found.cost == 0.0
    assert "cost unknown" in found.sentence()


def test_a_batch_refuses_to_run_without_an_explicit_confirmation(tmp_path):
    """§42: "Do not spend credits automatically." As a parameter rather than
    as a convention — a caller that forgets gets an exception naming the
    estimate, not a bill."""
    batch = ex.Batch(path=tmp_path / "run.jsonl")
    with pytest.raises(ex.NotConfirmed, match="not confirmed"):
        ex.run_batch(_cases(20), _runner(accuracy=0.9), batch=batch)
    assert not (tmp_path / "run.jsonl").exists()


def test_a_batch_resumes_rather_than_re_spending(tmp_path):
    """A run that dies at case four hundred of five hundred and cannot be
    resumed costs the four hundred again."""
    path = tmp_path / "run.jsonl"
    first = ex.run_batch(_cases(30), _runner(accuracy=0.9),
                         batch=ex.Batch(path=path), confirmed=True)
    assert len(first.outcomes) == 30

    calls = {"n": 0}

    def counting(case):
        calls["n"] += 1
        return _runner(accuracy=0.9)(case)

    second = ex.run_batch(_cases(30), counting, batch=ex.Batch(path=path),
                          confirmed=True)
    assert len(second.outcomes) == 30
    assert calls["n"] == 0, "a resumed batch must re-run nothing"


# ================================================ §40 accepted-answer precision


def test_precision_counts_displayed_answers_only():
    """§40: clarifications and safe abstentions are not incorrect answers, so
    they are not in the denominator."""
    result = ex.run_arm(ex.BASELINE, _runner(accuracy=1.0), _cases(90))
    assert result.displayed < len(result.outcomes)
    assert result.precision.total == result.displayed
    assert result.precision.point == 100.0


def test_coverage_is_reported_beside_precision_and_never_folded_into_it():
    """The two trade: an arm that abstains on everything hard has perfect
    precision and is useless. One number hiding that trade is the number
    people quote."""
    result = ex.run_arm(ex.BASELINE, _runner(accuracy=1.0, abstain_every=2),
                        _cases(90))
    assert result.precision.point == 100.0
    assert result.coverage.point < 60.0


def test_a_perfect_score_on_a_small_sample_does_not_claim_certainty():
    """§40. A precision of 1.0 over forty cases has a lower bound near 0.91,
    and the honest sentence is the bound."""
    result = ex.run_arm(ex.BASELINE, _runner(accuracy=1.0, abstain_every=999),
                        _cases(40))
    assert result.precision.point == 100.0
    assert result.precision.lower < 95.0
    assert not result.precision.supports(99.99)
    assert "CI" in result.precision.sentence()


def test_too_few_observations_is_said_rather_than_reported_as_a_rate():
    result = ex.run_arm(ex.BASELINE, _runner(accuracy=1.0), _cases(6))
    assert not result.precision.reportable
    assert "too few observations" in result.precision.sentence()


# ==================================================== §30 comparing the arms


def test_a_critical_regression_blocks_a_candidate_however_good_its_average():
    """§30's rule, at the point it costs something. The candidate is better
    overall and has moved the failure somewhere nobody was looking."""
    cases = _cases(150)
    baseline = ex.run_arm(ex.BASELINE, _runner(accuracy=0.80, seed=1), cases)
    winner_case = next(o.case_id for o in baseline.outcomes
                       if o.passed and o.behaviour == ex.ANSWERED)
    candidate = ex.run_arm(ex.CANDIDATE_B,
                           _runner(accuracy=0.95, seed=2,
                                   break_critical=winner_case), cases)

    found = ex.compare(baseline, [candidate])
    assert found.winner == ""
    assert winner_case in found.regressions[ex.CANDIDATE_B]
    assert "zero critical regressions" in found.reason


def test_a_non_critical_regression_does_not_block():
    """Only §34's critical categories block. A case that was never critical
    cannot become a critical regression by failing."""
    cases = _cases(400)
    baseline = ex.run_arm(ex.BASELINE, _runner(accuracy=0.60, seed=1), cases)
    candidate = ex.run_arm(ex.CANDIDATE_B, _runner(accuracy=0.92, seed=2),
                           cases)
    found = ex.compare(baseline, [candidate])
    assert found.regressions[ex.CANDIDATE_B] == []
    assert found.winner == ex.CANDIDATE_B


def test_a_candidate_must_clear_the_baseline_with_its_interval():
    """A candidate nominally ahead on forty cases is not ahead."""
    cases = _cases(60)
    baseline = ex.run_arm(ex.BASELINE, _runner(accuracy=0.85, seed=3), cases)
    candidate = ex.run_arm(ex.CANDIDATE_A, _runner(accuracy=0.88, seed=4),
                           cases)
    found = ex.compare(baseline, [candidate])
    assert found.winner == ""
    assert "margin" in found.reason or "interval" in found.reason


def test_the_decision_is_keep_the_baseline_when_nothing_wins():
    baseline = ex.run_arm(ex.BASELINE, _runner(accuracy=0.9), _cases(60))
    found = ex.compare(baseline, [])
    assert found.to_dict()["decision"] == "keep the baseline"


def test_results_are_reported_by_family_rather_than_as_one_average():
    """§30: "Evaluate by family." An average over families hides the family
    that broke."""
    result = ex.run_arm(ex.BASELINE, _runner(accuracy=0.8), _cases(90))
    families = result.by_family()
    assert set(families) == {"ECL_MOVEMENT", "AMBIGUITY",
                             "GRAIN_RECONCILIATION"}
    for row in families.values():
        assert row["cases"] > 0
        assert row["displayed"] <= row["cases"]


def test_the_four_arms_section_30_names_are_declared_with_their_purpose():
    assert set(ex.ARMS) == {ex.BASELINE, ex.CANDIDATE_A, ex.CANDIDATE_B,
                            ex.CANDIDATE_C}
    for arm in ex.ARMS:
        assert len(ex.ARM_PURPOSE[arm]) > 30


def test_a_runner_that_crashes_scores_the_case_rather_than_stopping_the_run():
    """An arm that crashes on one case in fifty is an arm with a defect, and
    losing the other forty-nine measurements hides it."""
    def broken(case):
        if case.id == "c005":
            raise RuntimeError("the planner exploded")
        return _runner(accuracy=1.0)(case)

    result = ex.run_arm(ex.BASELINE, broken, _cases(20))
    assert len(result.outcomes) == 20
    crashed = next(o for o in result.outcomes if o.case_id == "c005")
    assert crashed.failure == "EXECUTION"
    assert crashed.behaviour == ex.FAILED


# =================================================== §31 threshold selection


def test_the_policy_carries_every_threshold_section_31_names():
    body = pol.default().to_dict()
    assert set(body) == {
        "direct_complex_at", "escalate_at", "critic_at", "abstain_below",
        "retrieval_floor", "max_examples", "token_budget"}


def test_a_policy_refuses_an_impossible_combination():
    """A request scoring above the escalation threshold but below the direct
    one would be escalated to a route it was already eligible for."""
    with pytest.raises(ValueError, match="escalate_at"):
        pol.Policy(direct_complex_at=5, escalate_at=3)


def test_a_policy_refuses_more_examples_than_section_17_permits():
    with pytest.raises(ValueError, match="five examples"):
        pol.Policy(max_examples=8)


def test_the_default_policy_matches_what_the_modules_actually_do():
    """A number copied into the policy would be right on the day it was
    copied."""
    from backend.orchestration import routing as rt
    from backend.teaching import retrieval as rv

    found = pol.default()
    assert found.direct_complex_at == rt.COMPLEX_AT
    assert found.retrieval_floor == rv.FLOOR
    assert found.max_examples == rv.MAX_CASES


def test_the_fingerprint_moves_with_the_values():
    assert pol.default().fingerprint == pol.default().fingerprint
    assert pol.Policy(max_examples=3).fingerprint != \
        pol.Policy(max_examples=4).fingerprint


def test_a_sweep_picks_a_policy_with_no_critical_failures():
    cases = _cases(120)

    def runner_for(candidate: pol.Policy):
        # A degenerate product where a lower floor genuinely helps, so the
        # sweep has something real to find.
        accuracy = 0.75 + (0.32 - candidate.retrieval_floor)

        def run(case):
            index = int(case.id[1:])
            ok = (index * 7919 % 100) / 100 < accuracy
            return ex.Outcome(case_id=case.id, family=case.family, passed=ok,
                              behaviour=ex.ANSWERED,
                              failure="" if ok else "INTERPRETATION")
        return run

    found = ex.sweep(cases, runner_for,
                     policies=[pol.Policy(retrieval_floor=f)
                               for f in (0.12, 0.18, 0.25, 0.32)])
    assert found.chosen is not None
    assert found.chosen.retrieval_floor == 0.12
    assert "development cases" in found.reason


def test_a_sweep_that_finds_only_critical_failures_chooses_nothing():
    def runner_for(candidate):
        def run(case):
            return ex.Outcome(case_id=case.id, family=case.family,
                              passed=False, behaviour=ex.ANSWERED,
                              failure="GROUNDING")
        return run

    found = ex.sweep(_cases(40), runner_for, policies=[pol.default()])
    assert found.chosen is None
    assert "not the problem" in found.reason


def test_a_frozen_policy_cannot_be_overwritten(tmp_path):
    path = tmp_path / "routing_policy.json"
    ex.freeze_policy(pol.default(), path=path)
    with pytest.raises(FileExistsError):
        ex.freeze_policy(pol.default(), path=path)


# ================================================= §32 auxiliary classifiers


def test_every_task_section_32_names_has_a_named_baseline():
    required = {"intent", "same_turn_coreference", "conversation_action",
                "objective_decomposition", "period_parser",
                "scope_classifier", "retrieval_reranker"}
    assert required == set(cl.TASKS)
    for task in cl.TASKS:
        assert "backend." in cl.BASELINES[task]


def test_a_candidate_that_wins_on_average_and_loses_on_critical_is_refused():
    """A period parser that gains two points overall by reading "last year" as
    a calendar year is worse, not better."""
    samples = [cl.Sample(item=i, expected=i % 2, critical=(i % 10 == 0))
               for i in range(300)]
    decision = cl.compare(cl.PERIOD,
                          baseline=lambda i: i % 2,
                          candidate=lambda i: (1 - i % 2) if i % 10 == 0
                          else i % 2,
                          samples=samples)
    assert not decision.adopt
    assert "critical" in decision.reason


def test_a_candidate_inside_the_margin_is_not_adopted():
    """A development set of a few hundred cases cannot distinguish a one-point
    difference from noise."""
    samples = [cl.Sample(item=i, expected=i % 2) for i in range(300)]
    decision = cl.compare(cl.INTENT,
                          baseline=lambda i: i % 2 if i % 100 else 9,
                          candidate=lambda i: i % 2 if i % 150 else 9,
                          samples=samples)
    assert not decision.adopt
    assert "margin" in decision.reason


def test_a_clear_winner_with_no_new_critical_errors_is_adopted():
    samples = [cl.Sample(item=i, expected=i % 2, critical=(i % 25 == 0))
               for i in range(300)]
    decision = cl.compare(cl.SCOPE,
                          baseline=lambda i: i % 2 if i % 4 else 9,
                          candidate=lambda i: i % 2,
                          samples=samples)
    assert decision.adopt
    assert decision.gain > cl.MARGIN


def test_a_candidate_that_crashes_scores_the_case_wrong():
    """A candidate that crashes on one input in fifty is a candidate with a
    defect, and hiding it behind an exception makes it look untried."""
    def explodes(item):
        if item == 3:
            raise ValueError("no")
        return item % 2

    samples = [cl.Sample(item=i, expected=i % 2) for i in range(50)]
    found = cl.measure("candidate", explodes, samples)
    assert found.correct == 49
    assert any("error" in e["predicted"] for e in found.errors)


def test_the_report_names_the_tasks_nobody_has_measured():
    """A report listing only the experiments somebody ran cannot show which of
    the seven nobody has looked at."""
    samples = [cl.Sample(item=i, expected=i % 2) for i in range(60)]
    decision = cl.compare(cl.INTENT, baseline=lambda i: i % 2,
                          candidate=lambda i: i % 2, samples=samples)
    found = cl.report([decision])
    assert len(found["tasks"]) == len(cl.TASKS)
    assert cl.INTENT in found["measured"]
    assert cl.RERANKER in found["unmeasured"]


def test_a_task_outside_section_32s_list_is_refused():
    with pytest.raises(ValueError, match="not one of"):
        cl.compare("vibes", baseline=lambda i: i, candidate=lambda i: i,
                   samples=[cl.Sample(item=1, expected=1)])


# ================================================== §41 the sealed holdout


def test_the_holdout_covers_every_kind_section_41_names():
    required = {"unseen entity", "unseen period", "unseen alias",
                "unseen paraphrase", "unseen combination",
                "same-turn reference", "adversarial ambiguity",
                "multi-turn scope change", "boundary value",
                "compound request", "broad investigation",
                "corporate variant", "retail variant"}
    assert required == set(ho.KINDS)
    covered = ho.coverage()
    assert all(covered[kind] > 0 for kind in required)


def test_the_holdout_grew_rather_than_being_rebuilt():
    """The Phase 1 cases are still there. A holdout that is rewritten between
    releases measures a different thing each time, and the scores stop being
    comparable."""
    assert ho.BY_ID.get("hold-ent-1") is not None
    assert len(ho.CASES) >= 90


def test_the_holdout_carries_critical_cases_that_cannot_be_averaged_away():
    critical = ho.critical()
    assert len(critical) >= 25
    assert {c.kind for c in critical} >= {"unseen combination",
                                          "same-turn reference"}


def test_the_extension_carries_no_answers():
    """A holdout case is a specification. A stored answer is a number somebody
    quietly aligns to whatever the product returns."""
    for case in ho.CASES:
        body = case.to_dict()
        assert "answer" not in body
        assert "expected_value" not in body
        for turn in body["turns"]:
            assert set(turn) == {"question", "outcome", "capability",
                                 "action", "concepts", "datasets",
                                 "invariants", "forbidden", "critical"}
