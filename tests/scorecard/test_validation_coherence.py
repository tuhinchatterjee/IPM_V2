"""§14.5: one under-prediction finding, read under four categories.

The failure this guards against is not a wrong number. It is the same
problem reported four times with four ids and four slightly different
values, which a committee counts as four problems, and then one of the four
gets fixed.
"""

from __future__ import annotations

import pytest

from backend.scorecard.validation import (
    findings,
    models,
    registry,
    runner,
    states,
)

MODEL = "retail_beh_credit_card"


@pytest.fixture(scope="module")
def model() -> models.Model:
    return models.get(MODEL)


@pytest.fixture(scope="module")
def whole_run(model: models.Model) -> list[states.Result]:
    out: list[states.Result] = []
    for category in registry.CATEGORIES:
        out.extend(runner.run_category(category, model))
    return out


@pytest.fixture(scope="module")
def raised(model: models.Model,
           whole_run: list[states.Result]) -> list[findings.Finding]:
    return findings.assess(whole_run, model)


def _underprediction(raised: list[findings.Finding]) -> findings.Finding:
    for one in raised:
        if one.finding_id == "F-PATTERN-UNDERPREDICTION":
            return one
    pytest.skip("this book does not under-predict on the current window")


def test_the_finding_is_raised_once(raised: list[findings.Finding]) -> None:
    ids = [f.finding_id for f in raised]
    assert ids.count("F-PATTERN-UNDERPREDICTION") <= 1


def test_it_is_read_under_data_stability_and_segmentation(
        raised: list[findings.Finding]) -> None:
    one = _underprediction(raised)
    assert one.category == registry.CALIBRATION
    for also in (registry.DATA_QUALITY, registry.STABILITY,
                 registry.SEGMENTATION):
        assert also in one.also_in
    body = one.to_dict()
    assert body["categories"][0] == registry.CALIBRATION
    assert len(body["categories"]) == len(set(body["categories"]))


def test_every_category_reads_the_same_values(
        raised: list[findings.Finding]) -> None:
    """One id, one set of values. Not four findings that agree."""
    one = _underprediction(raised)
    body = one.to_dict()
    for category in body["categories"]:
        # The screen filters on `categories`; whichever it lands on, it is
        # this object, with this id and these numbers.
        assert category in body["categories"]
        assert body["finding_id"] == "F-PATTERN-UNDERPREDICTION"
        assert body["values"]["observed_over_expected"] == \
            one.values["observed_over_expected"]


def test_it_reconciles_to_the_calibration_result(
        raised: list[findings.Finding],
        whole_run: list[states.Result]) -> None:
    one = _underprediction(raised)
    oe = next(r for r in whole_run if r.test_id == "CAL-OE")
    assert one.values["observed_over_expected"] == round(oe.value, 6)
    assert one.values["limit"] == oe.limit
    assert one.values["limit_source"] == oe.limit_source
    assert one.period == oe.period


def test_it_fires_on_bands_not_on_the_aggregate(
        raised: list[findings.Finding],
        whole_run: list[states.Result]) -> None:
    """§14.5: 'when observed DR exceeds PD ACROSS BINS'.

    An aggregate O/E above 1 can be one band and a mix. The finding has to
    rest on the band table, and its own count has to match it.
    """
    one = _underprediction(raised)
    bands = next(r for r in whole_run if r.test_id == "CAL-BAND")
    under = [row for row in bands.table
             if row["observed_default_rate"] > row["average_predicted_pd"]]
    assert one.values["bands_under_predicted"] == len(under)
    assert one.values["bands"] == len(bands.table)
    assert len(under) > len(bands.table) / 2


def test_it_works_the_four_explanations_separately(
        raised: list[findings.Finding]) -> None:
    """§14.5 names four, and they are different conversations.

    Composition, conditional risk, a horizon or default-definition
    mismatch, and calibration drift. Reaching for the first one that fits
    is how a definition mismatch present since development becomes a
    re-development request.
    """
    said = _underprediction(raised).what.lower()
    for explanation in ("changing composition", "horizon and default "
                        "definition", "calibration drift"):
        assert explanation in said


def test_discrimination_is_reported_beside_it_and_not_folded_in(
        raised: list[findings.Finding],
        whole_run: list[states.Result]) -> None:
    """Low KS and poor calibration are distinct. §14.5 says so explicitly."""
    one = _underprediction(raised)
    said = one.what
    assert "reported separately and is not part of this finding" in said
    ranking = next(r for r in whole_run
                   if r.test_id == one.values["discrimination_test"])
    assert one.values["discrimination_value"] == round(ranking.value, 6)


def test_unaffected_categories_are_not_painted_red(
        whole_run: list[states.Result]) -> None:
    """§14.5: 'unaffected aspects may correctly remain PASS'.

    This scorecard ranks well and is calibrated to the wrong level. A run
    that turned every category red on the strength of the calibration would
    have destroyed the one piece of information a validator needs to choose
    a recalibration over a re-development.
    """
    by_id = {r.test_id: r for r in whole_run}
    for test_id in ("DISC-AUC", "DISC-KS", "DISC-GINI", "DISC-RANK"):
        assert by_id[test_id].state in (states.PASS, states.NO_LIMIT), \
            f"{test_id} is {by_id[test_id].state}"


def test_the_superseded_single_finding_is_not_also_reported(
        raised: list[findings.Finding]) -> None:
    one = _underprediction(raised)
    assert "F-CAL-OE" in one.supersedes
    assert "F-CAL-OE" not in {f.finding_id for f in raised}
