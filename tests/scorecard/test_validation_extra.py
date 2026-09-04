"""The rest of the validation calculations, and the states they may not use.

The recurring assertion here is that a test which found something says so.
A validation engine's characteristic failure is not a wrong number — it is a
right number wearing the wrong colour, and every case below is one where the
arithmetic was already correct and the reported state was not.
"""

from __future__ import annotations

import pytest

from backend.scorecard.validation import (
    extra,
    models,
    registry,
    runner,
    states,
)

CHAMPION = "sme_champion"
RETAIL = "retail_application_champion"


@pytest.fixture(scope="module")
def champion() -> models.Model:
    return models.get(CHAMPION)


@pytest.fixture(scope="module")
def retail() -> models.Model:
    return models.get(RETAIL)


def _sweep(model: models.Model) -> list[states.Result]:
    out: list[states.Result] = []
    for category in registry.CATEGORIES:
        out.extend(runner.run_category(category, model))
    return out


@pytest.fixture(scope="module")
def champion_sweep(champion: models.Model) -> list[states.Result]:
    """Every test on the SME book, run once for the whole module.

    The sweep assertions below are about the shape of a result rather than
    its value, and there are several of them. Running forty-eight tests per
    assertion turns a test file into a coffee break, and a suite nobody waits
    for is a suite nobody runs.
    """
    return _sweep(champion)


@pytest.fixture(scope="module")
def retail_sweep(retail: models.Model) -> list[states.Result]:
    return _sweep(retail)


# ------------------------------------------------------------- the coverage


def test_every_registered_test_has_a_calculation() -> None:
    missing = [t.test_id for t in registry.TESTS
               if t.test_id not in runner.HANDLERS]
    assert not missing, (
        f"{len(missing)} registered tests have no handler: {missing}. A test "
        "in the registry with nothing behind it is a row on a validation "
        "report that will never carry a result.")


def test_importing_the_runner_is_enough_to_get_them_all() -> None:
    """A caller must not have to remember a second import.

    Half the handlers live in `extra`, which registers into the runner's
    dictionary when it is imported. If nothing imported it, every one of
    those tests would come back UNAVAILABLE — honestly, and uselessly — and
    the only symptom would be a validation report missing half its rows.
    So the runner imports it, and this asserts that it still does.
    """
    import subprocess
    import sys

    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c",
         "from backend.scorecard.validation import runner;"
         "print(len(runner.HANDLERS))"],
        capture_output=True, text=True, check=True)
    assert int(done.stdout.strip()) == len(registry.TESTS), (
        "importing the runner alone did not register every handler")


# --------------------------------------------- a number is not a green tick


def test_a_measured_value_with_no_limit_is_not_reported_as_a_pass(
        champion: models.Model) -> None:
    """The defect this state exists to prevent.

    VAR-GINI reports the strongest characteristic's univariate Gini. No
    threshold is configured for it on any model — there is no conventional
    one — and before `NO_LIMIT` existed it came back PASS: a real number,
    compared against nothing, coloured green.
    """
    result = runner.run("VAR-GINI", champion)
    assert result.measured
    assert result.limit is None
    assert result.state == states.NO_LIMIT
    assert result.state != states.PASS


def test_a_structural_breach_is_a_failure_not_an_uncompared_number(
        champion: models.Model) -> None:
    """The other half of the same decision.

    VAR-WOE counts characteristics whose approved ordering the data has
    reversed. That has no defensible non-zero tolerance, so it carries a
    STRUCTURAL limit of zero rather than being left uncompared — and on this
    book it finds one, which is a finding rather than a grey cell.
    """
    result = runner.run("VAR-WOE", champion)
    limit = champion.limit_for("VAR-WOE")
    assert limit is not None
    assert limit.value == 0.0
    assert limit.source == "STRUCTURAL"
    assert result.state == (states.FAIL if result.value else states.PASS)


def test_no_limit_is_measured_but_not_adverse() -> None:
    assert states.NO_LIMIT in states.MEASURED
    assert states.NO_LIMIT not in states.ADVERSE
    assert states.NO_LIMIT not in states.UNMEASURED
    # It needs a person before a pass does, and after a real breach.
    assert (states.SEVERITY_ORDER[states.FAIL]
            < states.SEVERITY_ORDER[states.NO_LIMIT]
            < states.SEVERITY_ORDER[states.PASS])


def test_a_no_limit_result_still_carries_its_number(
        champion: models.Model) -> None:
    for test_id in ("VAR-WOE", "VAR-OCCUPANCY", "DATA-DUPLICATES"):
        result = runner.run(test_id, champion)
        if result.state == states.NO_LIMIT:
            assert result.value is not None
            assert result.limit is None
            assert result.limit_source == ""


# ------------------------------------------------------------ data quality


def test_the_row_waterfall_accounts_for_every_row(
        champion: models.Model) -> None:
    result = runner.run("DATA-ROWS", champion)
    steps = result.table
    assert steps[0]["step"] == "rows read"
    for before, after in zip(steps, steps[1:], strict=False):
        assert before["rows"] - after["rows"] == after["removed"], (
            "a waterfall whose steps do not reconcile is a waterfall that "
            "hides where the rows went")


def test_duplicate_keys_are_measured_on_the_declared_grain(
        champion: models.Model) -> None:
    result = runner.run("DATA-DUPLICATES", champion)
    assert result.measured
    assert result.lineage["grain"], "the grain tested has to be stated"


def test_coverage_counts_immature_cells_as_unassessable(
        champion: models.Model) -> None:
    result = runner.run("DATA-COVERAGE", champion)
    ready = set(runner.matured_periods(champion))
    for cell in result.table:
        if cell["period"] not in ready:
            assert not cell["assessable"], (
                f"{cell['period']} has no realised outcome and was counted "
                "as assessable")


def test_missingness_is_reported_per_period_not_only_pooled(
        champion: models.Model) -> None:
    result = runner.run("DATA-MISSING", champion)
    cells = result.chart.get("cells", [])
    assert {c["period"] for c in cells} == set(
        runner.available_periods(champion))


# --------------------------------------------------- conceptual soundness


def test_conceptual_tests_report_evidence_not_an_opinion(
        champion: models.Model) -> None:
    """The machine's honest contribution is the checklist, not the verdict."""
    for test_id in extra.CONCEPTUAL_EVIDENCE:
        result = runner.run(test_id, champion)
        assert result.table, f"{test_id} assembled no evidence"
        assert "judgement_belongs_to" in result.lineage, (
            f"{test_id} does not say whose judgement this is")
        for item in result.table:
            assert item["recorded"] or item["value"] == "NOT RECORDED" \
                or item["evidence"].startswith("declared"), (
                "anything absent is recorded absent, never inferred")


def test_a_missing_governance_field_is_marked_not_recorded(
        champion: models.Model) -> None:
    blank = models.Model(
        **{**{f.name: getattr(champion, f.name)
              for f in champion.__dataclass_fields__.values()},
           "intended_use": "", "owner": ""})
    result = runner.run("CONC-PURPOSE", blank)
    absent = [i for i in result.table if not i["recorded"]]
    assert {i["evidence"] for i in absent} >= {"intended_use", "owner"}
    assert all(i["value"] == "NOT RECORDED" for i in absent)
    assert result.value < 1.0
    assert "NOT RECORDED" in result.detail or "Not recorded" in result.detail


def test_the_direction_check_runs_on_matured_rows(
        champion: models.Model) -> None:
    """Otherwise the one quantitative check in the test silently vanishes."""
    result = runner.run("CONC-DIRECTION", champion)
    checks = [i for i in result.table
              if i["evidence"] == "declared direction against the data"]
    assert checks, (
        "the direction check needs an outcome, and its population has none "
        "unless it asks for the matured window itself")
    assert "AUC" in checks[0]["value"]


def test_an_inverted_score_direction_is_caught(
        champion: models.Model) -> None:
    flipped = models.Model(
        **{**{f.name: getattr(champion, f.name)
              for f in champion.__dataclass_fields__.values()},
           "score_direction": "LOWER_SCORE_IS_BETTER"})
    result = runner.run("CONC-DIRECTION", flipped)
    check = next(i for i in result.table
                 if i["evidence"] == "declared direction against the data")
    assert not check["recorded"]
    assert "inverted" in check["value"]


# ------------------------------------------------------------ through time


def test_the_discrimination_trend_keeps_its_thin_cohorts(
        champion: models.Model) -> None:
    """A series that drops its smallest months has a hole where it matters."""
    result = runner.run("DISC-TREND", champion)
    assert [row["period"] for row in result.table] == list(
        runner.matured_periods(champion))
    for row in result.table:
        assert "observations" in row and "events" in row


def test_a_cohort_too_thin_to_measure_carries_no_auc(
        champion: models.Model) -> None:
    result = runner.run("DISC-TREND", champion)
    for row in result.table:
        if row["auc"] is None:
            continue
        assert row["events"] > 0, (
            "an AUC on a cohort with no events is arithmetic on an empty set")


def test_the_rolling_window_is_declared(champion: models.Model) -> None:
    result = runner.run("STAB-ROLLING", champion)
    assert result.lineage["window_cohorts"] == extra.ROLLING_WINDOW
    assert str(extra.ROLLING_WINDOW) in result.detail


# -------------------------------------------------------------- robustness


def test_the_bootstrap_interval_is_reproducible(
        champion: models.Model) -> None:
    """An interval that moves between runs cannot be filed as evidence."""
    first = runner.run("ROB-BOOTSTRAP", champion)
    second = runner.run("ROB-BOOTSTRAP", champion)
    assert first.table[0] == second.table[0]
    assert first.lineage["seed"] == extra.BOOTSTRAP_SEED


def test_the_bootstrap_says_when_the_interval_straddles_the_limit(
        champion: models.Model) -> None:
    result = runner.run("ROB-BOOTSTRAP", champion)
    row = result.table[0]
    limit = champion.limit_for("DISC-AUC")
    assert limit is not None
    straddles = row["lower"] < limit.value < row["upper"]
    assert ("straddles" in result.detail) is straddles, (
        "an interval that crosses the limit must say so — the point estimate "
        "alone does not settle whether the model is inside it")


def test_segment_exclusion_reports_against_the_whole_book(
        champion: models.Model) -> None:
    result = runner.run("ROB-SEGMENT-EXCLUSION", champion)
    assert result.comparison_value is not None
    assert result.chart["baseline"] == result.comparison_value


def test_window_sensitivity_uses_contiguous_windows(
        champion: models.Model) -> None:
    result = runner.run("ROB-WINDOW", champion)
    ready = runner.matured_periods(champion)
    for row in result.table:
        start, end = row["periods"].split("..")
        assert start in ready and end in ready
        assert ready.index(start) <= ready.index(end)


# ---------------------------------------------------------- implementation


def test_replication_is_not_applicable_without_a_published_equation(
        champion: models.Model) -> None:
    """Not the same as a pass, and not the same as a failure to replicate."""
    result = runner.run("IMPL-REPLICATE", champion)
    assert result.state == states.NOT_APPLICABLE
    assert result.value is None
    assert "equation" in result.detail


def test_replication_runs_where_the_equation_is_published(
        retail: models.Model) -> None:
    result = runner.run("IMPL-REPLICATE", retail)
    assert result.measured, result.detail
    assert result.table[0]["tolerance"] > 0
    assert result.lineage["equation"], (
        "a replication result has to name the equation it replicated against")
    assert result.lineage["specification"]


def test_an_unstamped_version_is_unavailable_not_a_pass(
        champion: models.Model) -> None:
    result = runner.run("IMPL-VERSION", champion)
    if result.state == states.UNAVAILABLE:
        assert "version" in result.detail
        assert result.value is None


# ------------------------------------------------------------- the outputs


def test_no_handler_can_report_a_number_it_did_not_measure(
        champion_sweep: list[states.Result],
        retail_sweep: list[states.Result]) -> None:
    for result in [*champion_sweep, *retail_sweep]:
        if result.state in states.UNMEASURED:
            assert result.value is None, (
                f"{result.test_id} is {result.state} and carries a number")
            assert result.detail, f"{result.test_id} explains nothing"
        else:
            assert result.value is not None, (
                f"{result.test_id} is {result.state} and carries no number")


def test_every_result_can_be_serialised(
        champion_sweep: list[states.Result]) -> None:
    """A result that cannot reach an API is a result nobody will read."""
    import json

    for result in champion_sweep:
        json.dumps(result.to_dict(), default=str)


def test_every_result_names_the_model_and_the_calculation(
        champion: models.Model,
        champion_sweep: list[states.Result]) -> None:
    for result in champion_sweep:
        assert result.model_id == champion.model_id
        assert result.method, f"{result.test_id} states no method"


def test_the_sweep_covers_every_registered_test(
        champion_sweep: list[states.Result]) -> None:
    """A category run that quietly dropped a test would pass everything else."""
    assert ({r.test_id for r in champion_sweep}
            == {t.test_id for t in registry.TESTS})
