"""The validation runner: what it computes, and what it refuses to compute.

Most of these assert a refusal rather than a number. That is deliberate. A
validation engine that produces a number for every test is not more capable
than one that refuses some of them — it is one that has stopped telling the
difference between a measurement and a placeholder, and the placeholder that
matters here is 0.0%, which reads as "no defaults" rather than "no outcome
yet".
"""

from __future__ import annotations

import os
import subprocess
import sys

import pandas as pd
import pytest

from backend.scorecard import binning, domains
from backend.scorecard.sme import build as sme_build
from backend.scorecard.validation import models, registry, runner, states

CHAMPION = "sme_champion"


@pytest.fixture(scope="module")
def champion() -> models.Model:
    return models.get(CHAMPION)


# ------------------------------------------------------------- determinism


def test_the_universe_is_the_same_in_a_second_process() -> None:
    """The seed must not come from Python's randomised string hashing.

    This is a regression test for a defect, not a hypothetical. The SME
    generator seeded itself with `hash(key)`, which Python randomises per
    interpreter, so every process built a different universe. The binning
    specification is fitted on that data, so every approved bin, weight of
    evidence and information value moved between runs — and a validation
    result filed on Monday could not be reproduced on Tuesday.

    Two subprocesses with explicitly different hash seeds. If the seeding
    ever goes back to `hash()`, they disagree.
    """
    code = (
        "from backend.scorecard.sme import build;"
        "sp = build.spec();"
        "print(sorted((k, round(v.information_value, 8))"
        " for k, v in sp.variables.items()))"
    )
    outputs = []
    for seed in ("1", "2"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", code], capture_output=True, text=True,
            env=env, check=True)
        outputs.append(done.stdout.strip())
    assert outputs[0] == outputs[1], (
        "the approved binning specification differs between two processes, "
        "so no validation result computed from it is reproducible")


def test_two_runs_of_the_same_test_agree(champion: models.Model) -> None:
    first = runner.run("DISC-AUC", champion)
    second = runner.run("DISC-AUC", champion)
    assert first.value == second.value
    assert first.observations == second.observations


# ------------------------------------------------------------- the gates


def test_an_immature_period_is_refused_rather_than_measured(
        champion: models.Model) -> None:
    """The gate that matters most, because skipping it yields a number."""
    immature = runner.available_periods(champion)[-1]
    assert immature not in runner.matured_periods(champion)
    result = runner.run("DISC-AUC", champion, periods=(immature,))
    assert result.state == states.NOT_MATURED
    assert result.value is None
    assert immature in result.detail or result.period == immature


def test_a_refusal_says_when_the_window_closes(
        champion: models.Model) -> None:
    immature = runner.available_periods(champion)[-1]
    result = runner.run("CAL-OE", champion, periods=(immature,))
    assert result.state == states.NOT_MATURED
    assert result.detail.strip(), "a refusal with no explanation is a blank"
    assert result.remedy or "close" in result.detail.lower()


def test_a_test_the_model_cannot_support_is_not_applicable() -> None:
    """Not the same as a failure, and not the same as a zero."""
    stripped = models.get(CHAMPION)
    without_pd = models.Model(
        **{**{f.name: getattr(stripped, f.name)
              for f in stripped.__dataclass_fields__.values()},
           "pd_column": ""})
    result = runner.run("CAL-OE", without_pd)
    assert result.state == states.NOT_APPLICABLE
    assert result.value is None
    assert registry.REQUIREMENT_MEANING[registry.NEEDS_PD] in result.detail


def test_a_sample_too_small_to_measure_is_refused_not_reported(
        champion: models.Model) -> None:
    one_month = runner.matured_periods(champion)[0]
    field = champion.segmentation_fields[0]
    result = runner.run("DISC-AUC", champion, periods=(one_month,),
                        segment="MEDIUM", segment_field=field)
    # One month of the medium-enterprise book is a couple of hundred
    # accounts carrying a handful of defaults. An AUC computed on that is
    # arithmetic, not evidence.
    assert result.state == states.INSUFFICIENT_SAMPLE
    assert result.value is None
    assert str(registry.MIN_EVENTS) in result.detail \
        or str(registry.MIN_OBS) in result.detail


def test_a_domain_outside_the_three_is_refused(
        champion: models.Model) -> None:
    trespassing = models.Model(
        **{**{f.name: getattr(champion, f.name)
              for f in champion.__dataclass_fields__.values()},
           "domain": "retail_lending"})
    result = runner.run("DISC-AUC", trespassing)
    assert result.state == states.NOT_AUTHORISED
    assert result.value is None


def test_a_test_with_no_handler_says_so_rather_than_passing(
        champion: models.Model) -> None:
    """A registry entry with nothing behind it must not read as a pass."""
    unhandled = [t.test_id for t in registry.TESTS
                 if t.test_id not in runner.HANDLERS]
    if not unhandled:
        pytest.skip("every registered test has a handler")
    for test_id in unhandled:
        result = runner.run(test_id, champion)
        assert result.state != states.PASS, (
            f"{test_id} has no handler and still reported PASS")


# ------------------------------------------- what the tests actually measure


def test_discrimination_matches_the_kernel(champion: models.Model) -> None:
    """The runner must not compute; it must call."""
    from backend.scorecard import metrics as kernels

    pool = runner.population(champion)
    direct = kernels.discrimination(
        pool.frame, score=champion.score_column,
        target=champion.outcome_column,
        score_direction=champion.score_direction)
    assert runner.run("DISC-AUC", champion).value == direct.auc
    assert runner.run("DISC-GINI", champion).value == direct.gini
    assert runner.run("DISC-KS", champion).value == direct.ks


def test_the_verdict_is_arithmetic_not_judgement(
        champion: models.Model) -> None:
    result = runner.run("DISC-AUC", champion)
    limit = champion.limit_for("DISC-AUC")
    assert limit is not None
    assert result.state == limit.verdict(result.value)
    assert result.limit == limit.value
    assert result.limit_source == limit.source


def test_stability_is_measured_on_the_current_book_not_the_matured_one(
        champion: models.Model) -> None:
    """The finding lives in the newest month, and only there.

    PSI and CSI need no realised outcome, so confining them to the matured
    window would measure the drift of the book as it stood a year ago. On
    this model that is the difference between a pass and a breach.
    """
    result = runner.run("STAB-CSI", champion)
    assert result.period == runner.available_periods(champion)[-1]
    assert result.period not in runner.matured_periods(champion)

    matured_only = runner.run(
        "STAB-CSI", champion, periods=runner.matured_periods(champion))
    assert result.value > matured_only.value


def test_the_stability_series_covers_every_period(
        champion: models.Model) -> None:
    result = runner.run("STAB-PSI", champion)
    periods = [row["period"] for row in result.table]
    assert periods == list(runner.available_periods(champion))


def test_information_value_is_compared_against_approval(
        champion: models.Model) -> None:
    result = runner.run("VAR-IV", champion)
    spec = champion.approved_spec()
    for row in result.table:
        approved = spec.variables.get(row["variable"])
        if approved is None:
            continue
        assert row["information_value_at_approval"] == round(
            approved.information_value, 6)


def test_information_value_decay_ignores_variables_that_had_none(
        champion: models.Model) -> None:
    """Otherwise the noisiest characteristic tops the finding every time."""
    result = runner.run("VAR-IV", champion)
    below = [row["variable"] for row in result.table
             if (row["information_value_at_approval"] or 0.0)
             < runner.IV_FLOOR]
    for variable in below:
        assert variable in result.detail, (
            "a characteristic excluded from the comparison has to be named, "
            "or the reader cannot tell it was excluded")


def test_observed_information_value_uses_the_approved_bins() -> None:
    """Re-binning on the validation sample would measure a different model."""
    frame = pd.read_parquet(
        runner._analytics_root() / sme_build.MONTHLY
        / "cohort_month=2023-01")
    with pytest.raises(binning.BinningError):
        binning.observed_information_value(
            frame.drop(columns=[c for c in frame.columns
                                if c.endswith("_bin")]),
            variable="dscr", target="actual_default_12m")


# --------------------------------------------------------------- coverage


def test_every_category_can_be_run(champion: models.Model) -> None:
    for category in registry.CATEGORIES:
        results = runner.run_category(category, champion)
        assert results, f"{category} produced nothing at all"
        assert all(isinstance(r, states.Result) for r in results)


def test_a_category_returns_its_refusals_too(
        champion: models.Model) -> None:
    """A validation report has to state its own scope."""
    results = runner.run_category(registry.CALIBRATION, champion)
    assert len(results) == len(registry.in_category(registry.CALIBRATION))


def test_nothing_reports_a_number_it_did_not_measure(
        champion: models.Model) -> None:
    for category in registry.CATEGORIES:
        for result in runner.run_category(category, champion):
            if result.state in states.UNMEASURED:
                assert result.value is None, (
                    f"{result.test_id} is {result.state} and carries "
                    f"{result.value}")
                assert result.detail, f"{result.test_id} explains nothing"


def test_the_population_never_reaches_outside_the_three_domains() -> None:
    for name in ("retail.exposures", "sme.loans", "corporate.limits"):
        trespassing = models.Model(
            model_id="x", name="x", domain=name, scorecard_type="SME",
            reference_number="x", version="1")
        with pytest.raises(domains.DomainRefused):
            runner.population(trespassing)
