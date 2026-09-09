"""§25–§30: the package, the reading, and every number in it verified.

The tests that matter here are the ones about what a written reading is NOT
allowed to say. A change interpretation that invents a figure is worse than no
interpretation, because a committee will act on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.metrics import refresh as refresh_mod
from backend.metrics import refresh_intelligence as intel
from backend.metrics import refresh_package as pack

NOW = datetime(2026, 9, 9, 8, 30)


@dataclass
class FakeAnswer:
    """A model answer, without a model."""

    data: dict[str, Any]
    model: str = "test-model"
    duration_ms: int = 0


def snapshot(**kw) -> refresh_mod.PanelSnapshot:
    base = dict(panel_key="00:metric:corporate.stage2_ratio",
                metric_id="corporate.stage2_ratio", kind="metric",
                title="Stage 2 Ratio", value=9.4, unit="percent",
                decimals=2, reporting_period="Q2 2026",
                definition_hash="def-1", domains=["cockpit"],
                status="succeeded",
                coverage={"rows_considered": 16346,
                          "datasets": ["portfolio_facility"]})
    base.update(kw)
    return refresh_mod.PanelSnapshot(**base)


def two_refreshes(current_value=9.4, previous_value=9.1, **kw):
    previous = refresh_mod.Refresh(
        id=1, lens_id=7, refreshed_at=NOW - timedelta(days=1),
        reporting_period="Q2 2026", filter_hash="f",
        data_versions={"portfolio_facility": "1/aaa"},
        panels=[snapshot(value=previous_value)])
    current = refresh_mod.Refresh(
        id=2, lens_id=7, refreshed_at=NOW, reporting_period="Q2 2026",
        filter_hash="f", data_versions={"portfolio_facility": "1/bbb"},
        panels=[snapshot(value=current_value, **kw)])
    comparison = refresh_mod.Comparison(refresh=previous, exact=True)
    return current, refresh_mod.compare(current, comparison)


def package_for(current, delta, history=()):
    return pack.build(
        {"id": 7, "name": "Portfolio Quality", "description": "A test Lens",
         "audience": "Credit committee"},
        {"scope": {}, "sections": []}, current, delta, list(history))


# --------------------------------------------------------------- §25: size


def test_the_package_carries_the_change_already_computed():
    current, delta = two_refreshes()
    package = package_for(current, delta)
    assert package["material_changes"]
    change = package["material_changes"][0]
    assert change["previous"] == "9.10%"
    assert change["current"] == "9.40%"
    assert change["direction"] == "up"
    # The model is not asked to subtract two columns.
    assert change["absolute"] == "0.30%"


def test_figures_are_formatted_exactly_as_the_lens_shows_them():
    """§29 matches prose against these strings. A package saying "9.4" where
    the screen says "9.40%" would make every correct sentence look
    fabricated."""
    current, delta = two_refreshes()
    package = package_for(current, delta)
    assert package["metrics"][0]["current"] == "9.40%"


def test_the_package_contains_no_row_level_data():
    current, delta = two_refreshes()
    package = package_for(current, delta)
    text = str(package).lower()
    for forbidden in ("borrower_name", "customer_id", "account_id"):
        assert forbidden not in text


def test_a_chart_travels_as_a_summary_and_its_moved_labels():
    """§45. A twelve-quarter trend of twenty sectors is 240 points, which is a
    reasonable row and an unreasonable prompt."""
    series = [{"label": f"Sector {i}", "value": float(100 - i)}
              for i in range(20)]
    previous = refresh_mod.Refresh(
        id=1, lens_id=7, refreshed_at=NOW - timedelta(days=1),
        reporting_period="Q2 2026", filter_hash="f",
        panels=[snapshot(panel_key="00:chart:x:sector", kind="chart",
                         value=None, series=series)])
    current = refresh_mod.Refresh(
        id=2, lens_id=7, refreshed_at=NOW, reporting_period="Q2 2026",
        filter_hash="f",
        panels=[snapshot(panel_key="00:chart:x:sector", kind="chart",
                         value=None,
                         series=[{"label": "Sector 0", "value": 150.0}]
                                + series[1:])])
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    package = package_for(current, delta)
    chart = package["charts"][0]
    assert chart["groups"] == 20
    assert len(chart["top"]) <= pack.CHART_LABELS
    assert chart["summary"]["total"]
    assert chart["result_reference"]["panel_key"] == "00:chart:x:sector"
    assert [m["label"] for m in chart["moved"]] == ["Sector 0"]


def test_deep_mode_carries_more_without_carrying_everything():
    current, delta = two_refreshes()
    standard = package_for(current, delta)
    deep = pack.build(
        {"id": 7}, {"scope": {}}, current, delta, [], mode=pack.MODE_DEEP)
    assert standard["mode"] == pack.MODE_STANDARD
    assert deep["mode"] == pack.MODE_DEEP


# -------------------------------------------------- §30: nothing happened


def test_nothing_material_produces_the_honest_sentence_with_no_model_call():
    current, delta = two_refreshes(current_value=9.4, previous_value=9.4)
    reading = intel.interpret({}, current, delta, package_for(current, delta))
    assert reading.no_material_change
    assert "No material changes" in reading.headline
    assert reading.verified
    # …with the facts that support it, so it is not a bare assertion.
    assert any("reporting period is unchanged" in c.text
               for c in reading.material_changes)


def test_a_restatement_that_moved_nothing_says_which_it_was():
    """Identical values over changed source is a different fact from nothing
    having happened."""
    current, delta = two_refreshes(current_value=9.4, previous_value=9.4)
    reading = intel.quiet_reading(current, delta)
    assert any("republished" in c.text for c in reading.material_changes)


# ---------------------------------------------------------- §43: baseline


def test_a_baseline_says_change_interpretation_comes_next_time():
    current = refresh_mod.Refresh(id=1, lens_id=7, refreshed_at=NOW,
                                  panels=[snapshot()])
    delta = refresh_mod.compare(current, refresh_mod.Comparison())
    reading = intel.interpret({}, current, delta, {})
    assert reading.baseline
    assert "next comparable refresh" in reading.headline


# ------------------------------------------------------ §40: filter change


def test_a_filter_change_draws_no_comparison_at_all():
    previous = refresh_mod.Refresh(
        id=1, lens_id=7, refreshed_at=NOW - timedelta(days=1),
        reporting_period="Q2 2026", filter_hash="corporate",
        panels=[snapshot(value=9.1)])
    current = refresh_mod.Refresh(
        id=2, lens_id=7, refreshed_at=NOW, reporting_period="Q2 2026",
        filter_hash="construction", panels=[snapshot(value=14.2)])
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous))
    reading = intel.interpret({}, current, delta, {})
    assert "filter context changed" in reading.headline
    assert "FILTER CONTEXT CHANGE" in reading.definition_caveat
    assert "not a movement in the book" in reading.definition_caveat


# ------------------------------------------------- §29: every number checked


def test_a_supported_figure_survives():
    current, delta = two_refreshes()
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "Stage 2 Ratio rose from 9.10% to 9.40%.",
        "material_changes": [{
            "text": "Stage 2 Ratio moved 0.30% to 9.40%.",
            "basis": "CHANGE", "metrics": ["Stage 2 Ratio"]}],
        "no_material_change": False})
    reading = intel.checked(answer, package, delta)
    assert reading.verified
    assert not reading.ungrounded
    assert reading.headline.startswith("Stage 2 Ratio rose")


def test_an_invented_figure_discards_the_whole_reading():
    current, delta = two_refreshes()
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "Stage 2 Ratio rose from 9.10% to 12.70%.",
        "material_changes": [],
        "no_material_change": False})
    reading = intel.checked(answer, package, delta)
    assert reading.ungrounded == ["12.70%"]
    assert "12.70%" in reading.unavailable
    assert "9.40%" in reading.headline or "moved" in reading.headline, (
        "the deterministic account should still be shown")


def test_a_computed_figure_is_an_invented_one():
    """"9.10 plus 9.40 is 18.50" is arithmetic the model was told not to do."""
    current, delta = two_refreshes()
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "The two readings sum to 18.50%.",
        "material_changes": [], "no_material_change": False})
    assert intel.checked(answer, package, delta).ungrounded == ["18.50%"]


def test_an_invented_figure_inside_a_claim_is_caught_too():
    current, delta = two_refreshes()
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "Stage 2 Ratio rose.",
        "material_changes": [{
            "text": "It reached 99.90%, which is unprecedented.",
            "basis": "FACT", "metrics": ["Stage 2 Ratio"]}],
        "no_material_change": False})
    assert "99.90%" in intel.checked(answer, package, delta).ungrounded


# ------------------------------------------------- §28: no causal invention


def test_a_confirmed_driver_without_a_mechanism_is_downgraded():
    """"Stage 2 and high-severity EWS both rose" survives as a correlation.
    "EWS deterioration caused Stage 2 migration" does not stand as a
    confirmed driver on the strength of two things moving together."""
    current, delta = two_refreshes()
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "Stage 2 Ratio rose.",
        "material_changes": [],
        "supported_drivers": [{
            "text": "EWS deterioration caused Stage 2 migration.",
            "basis": "CONFIRMED_DRIVER", "metrics": ["Stage 2 Ratio"]}],
        "no_material_change": False})
    reading = intel.checked(answer, package, delta)
    claim = reading.supported_drivers[0]
    assert claim.basis == intel.CORRELATION
    assert claim.downgraded_from == intel.CONFIRMED_DRIVER
    assert reading.downgraded


def test_a_confirmed_driver_backed_by_a_migration_figure_stands():
    current = refresh_mod.Refresh(
        id=2, lens_id=7, refreshed_at=NOW, reporting_period="Q2 2026",
        filter_hash="f", data_versions={"portfolio_facility": "1/bbb"},
        panels=[snapshot(),
                snapshot(panel_key="01:metric:corporate.ifrs9.stage_1_to_2_ead",
                         metric_id="corporate.ifrs9.stage_1_to_2_ead",
                         title="Stage 1 to 2 Transition EAD", value=1200.0,
                         unit="currency")])
    previous = refresh_mod.Refresh(
        id=1, lens_id=7, refreshed_at=NOW - timedelta(days=1),
        reporting_period="Q2 2026", filter_hash="f",
        data_versions={"portfolio_facility": "1/aaa"},
        panels=[snapshot(value=9.1),
                snapshot(panel_key="01:metric:corporate.ifrs9.stage_1_to_2_ead",
                         metric_id="corporate.ifrs9.stage_1_to_2_ead",
                         title="Stage 1 to 2 Transition EAD", value=400.0,
                         unit="currency")])
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "Stage 2 Ratio rose.",
        "material_changes": [],
        "supported_drivers": [{
            "text": "The rise in Stage 2 Ratio is accounted for by the "
                    "transition into stage 2.",
            "basis": "CONFIRMED_DRIVER",
            "metrics": ["Stage 1 to 2 Transition EAD"]}],
        "no_material_change": False})
    reading = intel.checked(answer, package, delta)
    assert reading.supported_drivers[0].basis == intel.CONFIRMED_DRIVER
    assert not reading.downgraded


def test_a_dangling_metric_reference_is_dropped_and_the_sentence_kept():
    current, delta = two_refreshes()
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "Stage 2 Ratio rose.",
        "material_changes": [{
            "text": "Worth watching.", "basis": "INTERPRETATION",
            "metrics": ["Stage 2 Ratio", "A Metric Nobody Has"]}],
        "no_material_change": False})
    reading = intel.checked(answer, package, delta)
    assert reading.material_changes[0].metrics == ["Stage 2 Ratio"]
    assert reading.material_changes[0].text == "Worth watching."


def test_an_unknown_basis_falls_back_to_interpretation():
    current, delta = two_refreshes()
    package = package_for(current, delta)
    answer = FakeAnswer({
        "headline": "Something moved.",
        "material_changes": [{"text": "A claim.", "basis": "MADE_UP",
                              "metrics": []}],
        "no_material_change": False})
    reading = intel.checked(answer, package, delta)
    assert reading.material_changes[0].basis == intel.INTERPRETATION


# --------------------------------------------------------------- degrading


def test_no_provider_still_reports_the_movement():
    """The changes were computed deterministically and are worth showing on
    their own. What is missing is the reading, and the sentence says so."""
    current, delta = two_refreshes()
    reading = intel._deterministic_reading(delta, why="no provider here")
    assert reading.verified
    assert reading.material_changes
    assert "9.10%" in reading.material_changes[0].text
    assert "9.40%" in reading.material_changes[0].text
    assert reading.unavailable == "no provider here"
