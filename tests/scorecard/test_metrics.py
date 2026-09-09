"""
The deterministic scorecard metrics. §23-§27, §33, §92.

§92 asks for independent reference implementations. That is the shape of
most of this file: the expected value is computed a second way — by
definition, by brute force over pairs, by an analytic result on a
constructed case — and compared against the engine. A test that recomputed
the metric the same way the engine does would prove only that the code runs.

The refusals get as much space as the arithmetic. A KS that comes back
wrong is a bug somebody will notice; a KS computed on an immature cohort
comes back plausible and is wrong in a way nobody notices.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.scorecard import equation as equation_mod
from backend.scorecard import metrics
from backend.scorecard import synthetic as synth

HIGHER_BETTER = equation_mod.HIGHER_SCORE_IS_BETTER
LOWER_BETTER = equation_mod.LOWER_SCORE_IS_BETTER


def _frame(scores: list[float], outcomes: list[int], *,
           matured: bool = True) -> pd.DataFrame:
    return pd.DataFrame({
        "score": scores,
        "actual_default": outcomes,
        "matured_flag": [matured] * len(scores),
        "performance_window_end": ["2026-01"] * len(scores),
    })


# ------------------------------------------------- §92 independent references


def _auc_by_pairs(scores: np.ndarray, outcomes: np.ndarray) -> float:
    """AUC by its definition: over every good/bad pair, who ranked riskier.

    O(n^2) and unusable on real data, which is exactly why it is the right
    reference — it shares no code path with the rank-based implementation.
    """
    bads = scores[outcomes == 1]
    goods = scores[outcomes == 0]
    wins = 0.0
    for bad in bads:
        wins += float(np.sum(bad > goods)) + 0.5 * float(np.sum(bad == goods))
    return wins / (len(bads) * len(goods))


def test_auc_matches_a_brute_force_count_over_every_pair():
    rng = np.random.default_rng(11)
    risk = rng.normal(size=400)
    outcomes = (rng.random(400) < 1 / (1 + np.exp(-risk))).astype(int)
    # Higher score is better, so the score is the negative of the risk.
    frame = _frame(list(-risk), list(outcomes))
    engine = metrics.discrimination(frame, score="score",
                                    target="actual_default",
                                    score_direction=HIGHER_BETTER)
    reference = _auc_by_pairs(risk, outcomes)
    assert engine.auc == pytest.approx(reference, abs=1e-9)


def test_gini_is_exactly_two_auc_minus_one():
    frame = _frame([600, 620, 580, 700, 540, 660, 520, 690],
                   [1, 0, 1, 0, 1, 0, 1, 0])
    found = metrics.discrimination(frame, score="score",
                                   target="actual_default",
                                   score_direction=HIGHER_BETTER)
    assert found.gini == pytest.approx(2 * found.auc - 1)


def test_ks_matches_the_cumulative_distributions_computed_by_hand():
    scores = [500, 520, 540, 560, 580, 600, 620, 640, 660, 680]
    outcomes = [1, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    frame = _frame(scores, outcomes)
    found = metrics.discrimination(frame, score="score",
                                   target="actual_default",
                                   score_direction=HIGHER_BETTER)

    # By hand, riskiest first: the bad rate is front-loaded, so the maximum
    # gap is after the fifth observation — 4 of 5 bads and 1 of 5 goods.
    order = sorted(zip(scores, outcomes, strict=True))
    bads = sum(outcomes)
    goods = len(outcomes) - bads
    bad_seen = good_seen = 0
    best = 0.0
    for _, outcome in order:
        bad_seen += outcome
        good_seen += 1 - outcome
        best = max(best, abs(bad_seen / bads - good_seen / goods))
    assert found.ks == pytest.approx(best)


def test_a_perfect_separator_scores_auc_one():
    frame = _frame([500, 510, 520, 900, 910, 920], [1, 1, 1, 0, 0, 0])
    found = metrics.discrimination(frame, score="score",
                                   target="actual_default",
                                   score_direction=HIGHER_BETTER)
    assert found.auc == pytest.approx(1.0)
    assert found.ks == pytest.approx(1.0)


def test_brier_and_log_loss_match_their_definitions():
    frame = pd.DataFrame({
        "pd": [0.1, 0.2, 0.8, 0.9],
        "actual_default": [0, 0, 1, 1],
        "matured_flag": [True] * 4,
    })
    found = metrics.calibration(frame, pd_column="pd",
                                target="actual_default")
    expected_brier = np.mean([(0.1 - 0) ** 2, (0.2 - 0) ** 2,
                              (0.8 - 1) ** 2, (0.9 - 1) ** 2])
    expected_ll = -np.mean([math.log(0.9), math.log(0.8),
                            math.log(0.8), math.log(0.9)])
    assert found.brier == pytest.approx(expected_brier)
    assert found.log_loss == pytest.approx(expected_ll, abs=1e-9)


def test_psi_matches_the_standard_sum_computed_by_hand():
    reference = pd.DataFrame({"score": list(range(100))})
    current = pd.DataFrame({"score": list(range(50, 150))})
    found = metrics.psi(reference, current, score="score", bands=4)

    total = sum(
        (row["current_share"] - row["reference_share"])
        * math.log(row["current_share"] / row["reference_share"])
        for row in found.bins)
    assert found.index == pytest.approx(total, abs=1e-9)
    assert found.index > 0.1


def test_an_unchanged_population_has_a_psi_of_zero():
    frame = pd.DataFrame({"score": list(range(200))})
    found = metrics.psi(frame, frame.copy(), score="score", bands=5)
    assert found.index == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------ score direction


def test_reversing_the_score_direction_gives_the_complementary_auc():
    """§13/§23. The bug that inverts every discrimination statistic."""
    frame = _frame([500, 520, 540, 700, 720, 740], [1, 1, 1, 0, 0, 0])
    higher = metrics.discrimination(frame, score="score",
                                    target="actual_default",
                                    score_direction=HIGHER_BETTER)
    lower = metrics.discrimination(frame, score="score",
                                   target="actual_default",
                                   score_direction=LOWER_BETTER)
    assert higher.auc == pytest.approx(1.0)
    assert lower.auc == pytest.approx(0.0)
    assert higher.auc + lower.auc == pytest.approx(1.0)


def test_the_result_records_which_convention_it_used():
    frame = _frame([600, 620, 580, 700], [1, 0, 1, 0])
    body = metrics.discrimination(frame, score="score",
                                  target="actual_default",
                                  score_direction=HIGHER_BETTER).to_dict()
    assert body["score_direction"] == HIGHER_BETTER
    assert body["definitions"]["gini"] == "Gini = 2 * AUC - 1"


# --------------------------------------------------------- §7 the maturity gate


def test_discrimination_refuses_on_an_immature_cohort():
    """The failure that returns a plausible number and is silently wrong."""
    frame = _frame([600, 620, 580, 700], [1, 0, 1, 0], matured=False)
    with pytest.raises(metrics.ImmatureCohortError) as caught:
        metrics.discrimination(frame, score="score", target="actual_default",
                               score_direction=HIGHER_BETTER)
    message = str(caught.value)
    assert "not a zero" in message
    assert "Stability metrics do not need outcomes" in message


def test_calibration_refuses_on_an_immature_cohort():
    frame = pd.DataFrame({
        "pd": [0.1, 0.2], "actual_default": [0, 1],
        "matured_flag": [False, False],
        "performance_window_end": ["2026-06", "2026-06"],
    })
    with pytest.raises(metrics.ImmatureCohortError):
        metrics.calibration(frame, pd_column="pd", target="actual_default")


def test_an_absent_outcome_is_refused_even_when_the_flag_says_matured():
    """Belt and braces: the flag and the column have to agree."""
    frame = pd.DataFrame({
        "pd": [0.1, 0.2], "actual_default": [0, None],
        "matured_flag": [True, True],
    })
    with pytest.raises(metrics.ImmatureCohortError):
        metrics.calibration(frame, pd_column="pd", target="actual_default")


def test_stability_does_not_need_a_matured_outcome():
    """§7. PSI on the latest raw month is legitimate and useful."""
    reference = pd.DataFrame({"score": list(range(200))})
    current = pd.DataFrame({"score": list(range(100, 300)),
                            "matured_flag": [False] * 200})
    found = metrics.psi(reference, current, score="score", bands=5)
    assert found.index > 0


# --------------------------------------------------- §24 the MAPE guard


def test_mape_is_refused_when_every_band_is_below_the_floor():
    """A 0.1pp miss on a 0.2% band is a 50% error and means nothing."""
    rng = np.random.default_rng(3)
    n = 4_000
    frame = pd.DataFrame({
        "pd": rng.uniform(0.0001, 0.0009, n),
        "score": rng.uniform(500, 900, n),
        "actual_default": (rng.random(n) < 0.0004).astype(int),
        "matured_flag": [True] * n,
    })
    found = metrics.calibration(frame, pd_column="pd",
                                target="actual_default", score="score",
                                score_direction=HIGHER_BETTER)
    assert found.mape is None
    assert metrics.NOT_RELIABLE in found.mape_status
    assert "dividing by noise" in found.mape_status


def test_mape_says_how_many_bands_it_excluded():
    rng = np.random.default_rng(5)
    n = 20_000
    risk = rng.normal(size=n)
    probability = 1 / (1 + np.exp(-(risk - 3.0)))
    frame = pd.DataFrame({
        "pd": probability,
        "score": -risk * 50 + 600,
        "actual_default": (rng.random(n) < probability).astype(int),
        "matured_flag": [True] * n,
    })
    found = metrics.calibration(frame, pd_column="pd",
                                target="actual_default", score="score",
                                score_direction=HIGHER_BETTER)
    assert found.mape_status.startswith(("COMPUTED ON",))


def test_bucket_rmse_and_brier_are_reported_as_different_things():
    """§24. Quoting one as the other overstates precision."""
    rng = np.random.default_rng(9)
    n = 8_000
    risk = rng.normal(size=n)
    probability = 1 / (1 + np.exp(-(risk - 2.5)))
    frame = pd.DataFrame({
        "pd": probability, "score": -risk * 50 + 600,
        "actual_default": (rng.random(n) < probability).astype(int),
        "matured_flag": [True] * n,
    })
    body = metrics.calibration(frame, pd_column="pd",
                               target="actual_default", score="score",
                               score_direction=HIGHER_BETTER).to_dict()
    assert body["bucket_rmse"] != body["brier_score"]
    assert "different questions" in body["what_rmse_means_here"]


# --------------------------------------------- thin samples are a result


def test_a_thin_sample_is_labelled_rather_than_quoted_confidently():
    frame = _frame([600, 620, 580, 700, 540, 660], [1, 0, 1, 0, 1, 0])
    found = metrics.discrimination(frame, score="score",
                                   target="actual_default",
                                   score_direction=HIGHER_BETTER)
    assert found.evidence == metrics.NO_EVIDENCE
    assert metrics.NO_EVIDENCE in found.sentence()


def test_a_sample_with_one_outcome_class_is_refused_not_scored():
    frame = _frame([600, 620, 580, 700], [0, 0, 0, 0])
    with pytest.raises(metrics.MetricError) as caught:
        metrics.discrimination(frame, score="score", target="actual_default",
                               score_direction=HIGHER_BETTER)
    assert "only one" in str(caught.value)


def test_the_auc_confidence_interval_widens_on_a_smaller_sample():
    rng = np.random.default_rng(21)

    def spread(n: int) -> float:
        risk = rng.normal(size=n)
        outcomes = (rng.random(n) < 1 / (1 + np.exp(-risk))).astype(int)
        found = metrics.discrimination(
            _frame(list(-risk), list(outcomes)), score="score",
            target="actual_default", score_direction=HIGHER_BETTER)
        low, high = found.auc_confidence
        return high - low

    assert spread(200) > spread(5_000)


# ------------------------------------------------------------ §26 CSI


def test_csi_is_computed_on_the_approved_bins_not_fresh_cuts():
    reference = pd.DataFrame({"x_bin": ["B1"] * 50 + ["B2"] * 50})
    current = pd.DataFrame({"x_bin": ["B1"] * 20 + ["B2"] * 80})
    found = metrics.csi(reference, current, variable="x")
    assert found.kind == "CSI"
    assert found.index > 0.1


def test_csi_refuses_when_the_bin_column_is_absent():
    reference = pd.DataFrame({"x": [1, 2, 3]})
    current = pd.DataFrame({"x": [4, 5, 6]})
    with pytest.raises(metrics.MetricError) as caught:
        metrics.csi(reference, current, variable="x")
    assert "different questions" in str(caught.value)


def test_a_shift_result_says_its_thresholds_are_policy_not_regulation():
    """§26. Do not hard-code conventional cut-offs as regulatory limits."""
    reference = pd.DataFrame({"x_bin": ["B1", "B2"] * 50})
    current = pd.DataFrame({"x_bin": ["B1"] * 80 + ["B2"] * 20})
    body = metrics.csi(reference, current, variable="x").to_dict()
    assert "no regulatory threshold" in body["thresholds_are_policy"]


def test_psi_bands_come_from_the_reference_and_not_from_each_month():
    """Cutting each month at its own deciles compares it to itself."""
    reference = pd.DataFrame({"score": list(range(1000))})
    shifted = pd.DataFrame({"score": [v + 700 for v in range(1000)]})
    found = metrics.psi(reference, shifted, score="score", bands=10)
    assert found.index > 0.5, found.index


# ------------------------------------------------------ §33 replication


def test_replication_reproduces_a_correctly_stored_score():
    equation = equation_mod.Equation(
        model_name="m", scorecard_type="APPLICATION", intercept=-3.0,
        terms=[equation_mod.Term("bureau_score", -0.8)],
        output_prefix="incumbent",
        score_mapping=equation_mod.ScoreMapping(
            base_score=600, pdo=20, base_odds=50,
            score_direction=HIGHER_BETTER, min_score=300, max_score=900))
    woe = [0.4, -0.2, 0.1, -0.5]
    logits = [-3.0 - 0.8 * w for w in woe]
    frame = pd.DataFrame({
        "bureau_score_woe": woe,
        "logit_incumbent": logits,
        "pd_incumbent": [equation_mod.Equation.pd_from_logit(x)
                         for x in logits],
        "score_incumbent": [equation.score_mapping.score(x) for x in logits],
    })
    found = metrics.replicate(frame, equation)
    assert found.validated
    assert found.to_dict()["status"] == "IMPLEMENTATION VALIDATED"


def test_a_single_wrong_stored_score_blocks_implementation_validated():
    """§33. A critical mismatch blocks it, whatever the average looks like."""
    equation = equation_mod.Equation(
        model_name="m", scorecard_type="APPLICATION", intercept=-3.0,
        terms=[equation_mod.Term("bureau_score", -0.8)],
        output_prefix="incumbent")
    woe = [0.4, -0.2, 0.1, -0.5]
    logits = [-3.0 - 0.8 * w for w in woe]
    logits[2] += 0.05                       # one row implemented wrongly
    frame = pd.DataFrame({
        "bureau_score_woe": woe,
        "logit_incumbent": logits,
        "pd_incumbent": [equation_mod.Equation.pd_from_logit(x)
                         for x in logits],
    })
    found = metrics.replicate(frame, equation)
    assert not found.validated
    assert found.mismatch_count == 1
    assert "not the model that was approved" in found.to_dict()["why"]


def test_replication_refuses_when_the_woe_column_was_not_stored():
    equation = equation_mod.Equation(
        model_name="m", scorecard_type="APPLICATION", intercept=-3.0,
        terms=[equation_mod.Term("bureau_score", -0.8)],
        output_prefix="incumbent")
    with pytest.raises(metrics.MetricError) as caught:
        metrics.replicate(pd.DataFrame({"logit_incumbent": [1.0]}), equation)
    assert "independently reconstructed" in str(caught.value)


# ------------------------------------------------- §27 variable diagnostics


def test_a_variable_is_measured_on_its_woe_where_one_exists():
    """A raw AUC on a U-shaped variable understates what the model sees."""
    rng = np.random.default_rng(4)
    n = 3_000
    raw = rng.uniform(0, 100, n)
    # U-shaped: risk at both ends. WoE captures it; a raw AUC cannot.
    risk = ((raw - 50) / 25.0) ** 2 - 1.0
    outcomes = (rng.random(n) < 1 / (1 + np.exp(-risk))).astype(int)
    frame = pd.DataFrame({
        "u": raw, "u_woe": -risk, "actual_default": outcomes,
        "matured_flag": [True] * n,
    })
    found = metrics.variable_discrimination(frame, variable="u",
                                            target="actual_default")
    assert found["measured_on"] == "u_woe"
    assert found["auc"] > 0.6


def test_a_variable_with_one_outcome_class_reports_why_rather_than_a_number():
    frame = pd.DataFrame({
        "x": [1.0, 2.0, 3.0], "actual_default": [0, 0, 0],
        "matured_flag": [True] * 3,
    })
    found = metrics.variable_discrimination(frame, variable="x",
                                            target="actual_default")
    assert found["auc"] is None
    assert found["evidence"] == metrics.NO_EVIDENCE
    assert "only one outcome class" in found["why"]


# ------------------------------------------------------------ §23 gains


def test_gains_capture_more_than_the_population_share_in_the_top_decile():
    rng = np.random.default_rng(7)
    n = 5_000
    risk = rng.normal(size=n)
    outcomes = (rng.random(n) < 1 / (1 + np.exp(-(risk - 2)))).astype(int)
    frame = _frame(list(-risk * 50 + 600), list(outcomes))
    rows = metrics.gains(frame, score="score", target="actual_default",
                         score_direction=HIGHER_BETTER)
    assert len(rows) == 10
    assert rows[0]["lift"] > 1.5
    assert rows[-1]["cumulative_capture_rate"] == pytest.approx(1.0, abs=1e-6)
    # Capture is monotone: you cannot capture fewer bads by taking more rows.
    captures = [r["cumulative_capture_rate"] for r in rows]
    assert captures == sorted(captures)


# ---------------------------------------------- against the real universe


@pytest.fixture(scope="module")
def application_month():
    frame = synth.application_month("2024-01", offset=12)
    from backend.scorecard import build

    spec = build.load_spec("APPLICATION")
    equations = {k: build.load_equation("APPLICATION", k)
                 for k in build.MODEL_KINDS}
    return build.score_frame(frame, equations, spec)


def test_the_engine_produces_plausible_numbers_on_the_real_universe(
        application_month):
    found = metrics.discrimination(
        application_month, score="score_incumbent",
        target="actual_default", score_direction=HIGHER_BETTER)
    assert 0.60 < found.auc < 0.85, found.auc
    assert 0.20 < found.ks < 0.60, found.ks
    assert found.evidence == metrics.HIGH_EVIDENCE


def test_every_pd_on_the_real_universe_is_a_probability(application_month):
    """§73's critical case: PD outside [0, 1] is arithmetic gone wrong."""
    for kind in ("incumbent", "challenger", "recalibrated"):
        values = application_month[f"pd_{kind}"]
        assert values.min() >= 0.0 and values.max() <= 1.0, kind


def test_a_freshly_scored_month_replicates_against_its_own_equation(
        application_month):
    from backend.scorecard import build

    found = metrics.replicate(application_month,
                              build.load_equation("APPLICATION", "INCUMBENT"))
    assert found.validated, found.to_dict()


# ------------------------------------------- §40 the bootstrap and its paths


def _sample(rows: int = 4000, distinct: int = 40, seed: int = 7):
    """A book with heavy tying, which is what a scorecard actually produces."""
    rng = np.random.default_rng(seed)
    score = rng.integers(300, 300 + distinct, rows).astype(float)
    risk = 1.0 / (1.0 + np.exp((score - 320) / 6.0))
    return pd.DataFrame({
        "score": score,
        "actual_default": (rng.random(rows) < risk).astype(float),
    })


def test_the_counted_auc_is_the_ranked_auc_to_the_last_bit():
    """The two bootstrap paths must not drift apart.

    `bootstrap_auc` compresses a heavily tied score to a count table and
    computes the Mann-Whitney statistic across it, which is why an interval
    on a third of a million rows takes seconds rather than a minute and a
    half. That is only legitimate if the compressed statistic is the same
    statistic — so this asserts it on the degenerate draw, where the counts
    are the observed ones.
    """
    frame = _sample()
    y, raw = metrics._clean(frame["actual_default"], frame["score"])
    risk = metrics._risk_ordered(raw, HIGHER_BETTER)
    values, index = np.unique(risk, return_inverse=True)
    bad = np.bincount(index, weights=y, minlength=len(values))
    good = np.bincount(index, minlength=len(values)) - bad

    counted = metrics.auc_from_counts(good, bad)
    ranked = metrics.discrimination(
        frame, score="score", target="actual_default",
        score_direction=HIGHER_BETTER).auc
    assert counted == ranked


def test_the_counted_auc_handles_ties_the_way_midranks_do():
    """A tie is worth half a comparison, on both paths."""
    frame = pd.DataFrame({
        "score": [500.0, 500.0, 500.0, 600.0],
        "actual_default": [1.0, 0.0, 1.0, 0.0],
    })
    y, raw = metrics._clean(frame["actual_default"], frame["score"])
    risk = metrics._risk_ordered(raw, HIGHER_BETTER)
    values, index = np.unique(risk, return_inverse=True)
    bad = np.bincount(index, weights=y, minlength=len(values))
    good = np.bincount(index, minlength=len(values)) - bad
    assert metrics.auc_from_counts(good, bad) == metrics.discrimination(
        frame, score="score", target="actual_default",
        score_direction=HIGHER_BETTER).auc


def test_a_bootstrap_interval_brackets_its_point_estimate():
    frame = _sample()
    interval = metrics.bootstrap_auc(
        frame, score="score", target="actual_default",
        score_direction=HIGHER_BETTER, resamples=300, seed=11)
    assert interval.lower < interval.point < interval.upper
    assert interval.resamples == 300
    assert interval.observations == len(frame)


def test_the_same_seed_gives_the_same_interval():
    """An interval that moves between runs cannot be filed as evidence."""
    frame = _sample()
    first = metrics.bootstrap_auc(
        frame, score="score", target="actual_default",
        score_direction=HIGHER_BETTER, resamples=200, seed=11)
    second = metrics.bootstrap_auc(
        frame, score="score", target="actual_default",
        score_direction=HIGHER_BETTER, resamples=200, seed=11)
    assert (first.lower, first.upper) == (second.lower, second.upper)


def test_a_different_seed_gives_a_different_interval():
    """If it did not, the seed would not be doing anything."""
    frame = _sample()
    made = [metrics.bootstrap_auc(
        frame, score="score", target="actual_default",
        score_direction=HIGHER_BETTER, resamples=200, seed=seed)
        for seed in (11, 12)]
    assert (made[0].lower, made[0].upper) != (made[1].lower, made[1].upper)


def test_more_data_gives_a_narrower_interval():
    """The property that makes a confidence interval worth reporting."""
    narrow = metrics.bootstrap_auc(
        _sample(rows=40_000), score="score", target="actual_default",
        score_direction=HIGHER_BETTER, resamples=300, seed=11)
    wide = metrics.bootstrap_auc(
        _sample(rows=2_000), score="score", target="actual_default",
        score_direction=HIGHER_BETTER, resamples=300, seed=11)
    assert (narrow.upper - narrow.lower) < (wide.upper - wide.lower)


def test_both_bootstrap_paths_agree_on_the_same_book():
    """The compression is a speed decision, not a statistical one.

    The counted path and the plain resample draw different random numbers,
    so their intervals differ by sampling noise — but not by more than that,
    and this pins how much. If the compression were subtly wrong, the two
    would separate by far more than a percentile's Monte Carlo error.
    """
    frame = _sample(rows=20_000)
    y, raw = metrics._clean(frame["actual_default"], frame["score"])
    risk = metrics._risk_ordered(raw, HIGHER_BETTER)
    values, index = np.unique(risk, return_inverse=True)

    counted = metrics._bootstrap_counted(
        y, index, len(values), 400, np.random.default_rng(3))
    resampled = metrics._bootstrap_resampled(
        y, risk, 400, np.random.default_rng(3))
    for tail in (2.5, 50.0, 97.5):
        assert abs(float(np.percentile(counted, tail))
                   - float(np.percentile(resampled, tail))) < 0.005


def test_a_bootstrap_refuses_an_immature_cohort():
    frame = _sample()
    frame["matured_flag"] = False
    with pytest.raises(metrics.ImmatureCohortError):
        metrics.bootstrap_auc(
            frame, score="score", target="actual_default",
            score_direction=HIGHER_BETTER, resamples=50, seed=1)


def test_a_bootstrap_refuses_a_sample_with_one_outcome_class():
    frame = _sample()
    frame["actual_default"] = 0.0
    with pytest.raises(metrics.MetricError):
        metrics.bootstrap_auc(
            frame, score="score", target="actual_default",
            score_direction=HIGHER_BETTER, resamples=50, seed=1)
