"""§14.3: what the model was fitted on, and how today's book differs.

The assertions here are mostly about REFUSALS and about arithmetic that has
to close. The characteristic failure of a representativeness test is not a
wrong index — it is a comparison between two populations that are not
comparable, reported as though they were, and the two cases that matter are
a current month placed beside a matured default rate and a standardisation
computed over a rump of the book.
"""

from __future__ import annotations

import math

import pytest

from backend.scorecard.validation import (
    findings,
    models,
    registry,
    representativeness,
    runner,
    states,
)

RETAIL = "retail_beh_credit_card"


@pytest.fixture(scope="module")
def behavioural() -> models.Model:
    return models.get(RETAIL)


@pytest.fixture(scope="module")
def data_results(behavioural: models.Model) -> dict[str, states.Result]:
    got = runner.run_category(registry.DATA_QUALITY, behavioural)
    return {r.test_id: r for r in got}


# ------------------------------------------------------- they are registered


def test_every_declared_test_has_a_handler() -> None:
    """A registered test with no handler is an honest-looking UNAVAILABLE."""
    missing = [t.test_id for t in registry.TESTS
               if t.test_id not in runner.HANDLERS]
    assert missing == []


@pytest.mark.parametrize("test_id", [
    "DATA-PROVENANCE", "DATA-INPUT-DRIFT", "DATA-ODR", "DATA-MIXADJ"])
def test_the_new_tests_are_in_data_and_representativeness(test_id: str) -> None:
    assert registry.BY_ID[test_id].category == registry.DATA_QUALITY


# ------------------------------------------------------------- provenance


def test_provenance_describes_the_development_sample(
        data_results: dict[str, states.Result]) -> None:
    got = data_results["DATA-PROVENANCE"]
    assert got.measured, got.detail
    # The headline IS the development event rate: every later comparison is
    # made against it, and a provenance card that omitted it would leave a
    # reader comparing today's rate against nothing.
    assert 0.0 < (got.value or 0.0) < 1.0
    assert got.reference_period
    assert got.lineage["development_events"] > 0
    assert math.isclose(
        got.lineage["development_event_rate"], got.value or 0.0, abs_tol=1e-6)


def test_provenance_carries_the_three_panels(
        data_results: dict[str, states.Result]) -> None:
    """Facts, exclusions and score shape are three panels, not one table."""
    panels = data_results["DATA-PROVENANCE"].lineage["panels"]
    titles = [p["title"] for p in panels]
    assert any("developed on" in t for t in titles)
    assert any("Exclusions" in t for t in titles)
    assert any("score distribution" in t for t in titles)
    facts = next(p for p in panels if "developed on" in p["title"])["facts"]
    labels = {f["label"] for f in facts}
    for needed in ("Development window", "Defaults", "Outcome definition",
                   "Performance window", "Eligibility"):
        assert needed in labels


def test_provenance_pluralises_the_subject(
        behavioural: models.Model,
        data_results: dict[str, states.Result]) -> None:
    """"14,767 distinct facilitys" is a governance record with a typo in it."""
    assert representativeness._subject(behavioural) == (
        "facility", "facilities")
    assert "facilitys" not in data_results["DATA-PROVENANCE"].detail


# ------------------------------------------------------------ input drift


def test_input_drift_covers_every_model_input(
        behavioural: models.Model,
        data_results: dict[str, states.Result]) -> None:
    got = data_results["DATA-INPUT-DRIFT"]
    assert got.measured, got.detail
    compared = {row["variable"] for row in got.table}
    assert compared == set(behavioural.binned_variables)


def test_input_drift_headline_is_the_worst_input(
        data_results: dict[str, states.Result]) -> None:
    got = data_results["DATA-INPUT-DRIFT"]
    assert got.value == max(row["csi"] for row in got.table)


def test_input_drift_uses_the_one_csi_definition(
        behavioural: models.Model,
        data_results: dict[str, states.Result]) -> None:
    """§14.3: CSI may not mean a different statistic on another screen.

    So this is not re-derived here. The per-input index has to equal the
    kernel every other CSI in the product is computed with, over the same
    approved bins and the same reference population.
    """
    from backend.scorecard import metrics as kernels

    reference = runner.reference_population(behavioural)
    current = runner.population(behavioural, matured_only=False)
    got = data_results["DATA-INPUT-DRIFT"]
    for row in got.table[:4]:
        direct = kernels.csi(reference.frame, current.frame,
                             variable=row["variable"])
        assert math.isclose(row["csi"], round(direct.index, 6), abs_tol=1e-9)


def test_input_drift_states_its_smoothing(
        data_results: dict[str, states.Result]) -> None:
    lineage = data_results["DATA-INPUT-DRIFT"].lineage
    assert lineage["zero_bin_smoothing"] > 0
    assert "ln(" in lineage["formula"]


# ------------------------------------------------------------------- ODR


def test_odr_never_gives_the_open_cohort_a_default_rate(
        data_results: dict[str, states.Result]) -> None:
    """The defect this test exists for.

    A current month has no realised outcome. Putting it in the same column
    as two matured default rates is how a book with twelve open cohorts
    comes to look like a book that has stopped defaulting.
    """
    got = data_results["DATA-ODR"]
    assert got.measured, got.detail
    current = [row for row in got.table
               if row["population"] == "The book as it stands"]
    assert len(current) == 1
    assert current[0]["observed_rate"] is None
    assert current[0]["events"] is None
    assert "not closed" in current[0]["horizon"]
    # And it still says something: a predicted PD and a stock measure.
    assert current[0]["mean_predicted_pd"] is not None


def test_odr_horizons_are_named_on_every_row(
        data_results: dict[str, states.Result]) -> None:
    for row in data_results["DATA-ODR"].table:
        assert row["horizon"]


def test_odr_gap_reconciles_to_its_own_rows(
        data_results: dict[str, states.Result]) -> None:
    got = data_results["DATA-ODR"]
    matured = [row for row in got.table if row["observed_rate"] is not None]
    if len(matured) < 2:
        pytest.skip("only the development window has closed")
    assert math.isclose(
        got.value or 0.0,
        matured[1]["observed_rate"] - matured[0]["observed_rate"],
        abs_tol=1e-6)


# ------------------------------------------------------- mix adjustment


def test_mix_adjustment_splits_the_move_without_a_residual(
        data_results: dict[str, states.Result]) -> None:
    """Composition plus conditional risk IS the move. No residual to explain."""
    got = data_results["DATA-MIXADJ"]
    if not got.measured:
        pytest.skip(got.detail)
    lineage = got.lineage
    move = lineage["matched_current_rate"] - lineage["matched_development_rate"]
    assert math.isclose(
        lineage["composition_effect"] + lineage["conditional_risk_effect"],
        move, abs_tol=1e-6)


def test_mix_adjustment_covers_most_of_the_book(
        data_results: dict[str, states.Result]) -> None:
    """A composition effect measured over a rump is about the rump.

    Ranking the stratification fields by movement alone chose origination
    vintage — which moves most precisely because vintages that did not exist
    at development have no development counterpart — and standardised nine
    per cent of the book against nine per cent of the book.
    """
    got = data_results["DATA-MIXADJ"]
    if not got.measured:
        pytest.skip(got.detail)
    assert got.lineage["current_book_covered"] >= \
        representativeness.MIN_COVERAGE


def test_mix_adjustment_names_what_it_standardised_over(
        data_results: dict[str, states.Result]) -> None:
    got = data_results["DATA-MIXADJ"]
    if not got.measured:
        pytest.skip(got.detail)
    over = got.lineage["stratified_by"]
    assert over
    for field in over:
        assert field in got.detail


def test_every_stratum_row_contributes_to_the_move(
        data_results: dict[str, states.Result]) -> None:
    got = data_results["DATA-MIXADJ"]
    if not got.measured:
        pytest.skip(got.detail)
    total = sum(row["mix_contribution"] + row["rate_contribution"]
                for row in got.table)
    move = (got.lineage["matched_current_rate"]
            - got.lineage["matched_development_rate"])
    assert math.isclose(total, move, abs_tol=1e-4)


# ---------------------------------------------------------- the finding


def test_the_category_says_why_it_is_less_representative(
        behavioural: models.Model,
        data_results: dict[str, states.Result]) -> None:
    raised = findings.assess(list(data_results.values()), behavioural)
    named = {f.finding_id for f in raised}
    assert "F-PATTERN-LESS-REPRESENTATIVE" in named
    one = next(f for f in raised
               if f.finding_id == "F-PATTERN-LESS-REPRESENTATIVE")
    assert one.what.startswith("The population is less representative because")
    # A finding with no evidence is an opinion; the dataclass enforces that,
    # and this checks it cites the tests it was actually built from.
    assert "DATA-INPUT-DRIFT" in one.evidence
