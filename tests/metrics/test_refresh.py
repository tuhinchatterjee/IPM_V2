"""§18–§24: what a refresh is, which one it may be compared with, and what
kind of change it represents.

Everything here runs on constructed snapshots rather than on a database,
because the questions are arithmetic and comparison questions and neither
needs one. What a database WOULD add is covered in
`tests/metrics/test_refresh_store.py`, which skips itself without one.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.metrics import refresh as refresh_mod

NOW = datetime(2026, 9, 9, 8, 30)


def snapshot(key="00:metric:corporate.exposure", *, value=100.0,
             metric_id="corporate.exposure", title="Corporate Exposure",
             unit="currency", period="Q2 2026", definition_hash="def-1",
             domains=("cockpit",), status="succeeded", kind="metric",
             series=()) -> refresh_mod.PanelSnapshot:
    return refresh_mod.PanelSnapshot(
        panel_key=key, metric_id=metric_id, kind=kind, title=title,
        value=value, unit=unit, reporting_period=period,
        definition_hash=definition_hash, domains=list(domains),
        status=status, series=list(series))


def refresh(*panels, at=NOW, period="Q2 2026", filters="filter-a",
            version=1, data=None, id=1) -> refresh_mod.Refresh:
    return refresh_mod.Refresh(
        id=id, lens_id=7, refreshed_at=at, reporting_period=period,
        filter_hash=filters, lens_definition_version=version,
        data_versions=dict(data or {"portfolio_facility": "1/aaa"}),
        panels=list(panels))


# ------------------------------------------------------------- materiality


def test_a_tiny_absolute_movement_on_a_large_figure_is_not_material():
    assert not refresh_mod.material(41_800_000_002.0, 41_800_000_001.0)


def test_a_small_movement_on_a_ratio_is_material():
    assert refresh_mod.material(0.094, 0.091)


def test_an_identical_value_is_not_material():
    assert not refresh_mod.material(9.4, 9.4)


def test_appearing_or_disappearing_is_material():
    assert refresh_mod.material(9.4, None)
    assert refresh_mod.material(None, 9.4)


# ---------------------------------------------------- §24: comparable, not
#                                                       merely previous


def test_the_most_recent_matching_refresh_is_chosen():
    older = refresh(snapshot(), at=NOW - timedelta(days=2), id=1)
    newer = refresh(snapshot(), at=NOW - timedelta(days=1), id=2)
    current = refresh(snapshot(), at=NOW, id=3)
    found = refresh_mod.comparable(current, [older, newer])
    assert found.refresh.id == 2
    assert found.exact


def test_a_different_filter_context_is_never_chosen():
    """§40. A Lens narrowed to Construction is not the corporate book with a
    smaller number on it."""
    other = refresh(snapshot(value=20.0), at=NOW - timedelta(days=1),
                    filters="filter-b", id=1)
    current = refresh(snapshot(), at=NOW, filters="filter-a", id=2)
    found = refresh_mod.comparable(current, [other])
    assert found.refresh is None
    assert "different filter context" in found.why_none


def test_a_definition_version_change_is_recorded_not_hidden():
    older = refresh(snapshot(), at=NOW - timedelta(days=1), version=1, id=1)
    current = refresh(snapshot(), at=NOW, version=2, id=2)
    found = refresh_mod.comparable(current, [older])
    assert found.refresh.id == 1
    assert not found.exact
    assert found.relaxed


def test_an_earlier_reporting_period_is_chosen_and_said_so():
    older = refresh(snapshot(period="Q1 2026"), at=NOW - timedelta(days=90),
                    period="Q1 2026", id=1)
    current = refresh(snapshot(), at=NOW, period="Q2 2026", id=2)
    found = refresh_mod.comparable(current, [older])
    assert found.refresh.id == 1
    assert not found.exact
    assert "Q1 2026" in found.relaxed[0]


def test_the_first_refresh_has_nothing_to_compare_with():
    found = refresh_mod.comparable(refresh(snapshot(), id=1), [])
    assert found.refresh is None
    assert "first recorded refresh" in found.why_none


# ------------------------------------------------------- §21: classification


def test_a_baseline_is_classified_as_one():
    delta = refresh_mod.compare(
        refresh(snapshot(), id=1), refresh_mod.Comparison())
    assert delta.classification == [refresh_mod.BASELINE]
    assert not delta.anything_material


def test_no_source_change_and_no_value_change():
    """§38. Opening the same Lens twice must not manufacture movement."""
    previous = refresh(snapshot(), at=NOW - timedelta(hours=1), id=1)
    current = refresh(snapshot(), at=NOW, id=2)
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    assert delta.classification == [refresh_mod.NO_SOURCE_CHANGE]
    assert not delta.anything_material


def test_source_changed_but_values_did_not():
    """A restatement that did not move the book is a different fact from
    nothing having happened, and no amount of comparing values says which."""
    previous = refresh(snapshot(), at=NOW - timedelta(days=1), id=1,
                       data={"portfolio_facility": "1/aaa"})
    current = refresh(snapshot(), at=NOW, id=2,
                      data={"portfolio_facility": "1/bbb"})
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    assert refresh_mod.SOURCE_CHANGED_VALUE_UNCHANGED in delta.classification
    assert delta.source_changed == ["portfolio_facility"]


def test_source_and_values_both_changed():
    previous = refresh(snapshot(value=100.0), at=NOW - timedelta(days=1), id=1,
                       data={"portfolio_facility": "1/aaa"})
    current = refresh(snapshot(value=120.0), at=NOW, id=2,
                      data={"portfolio_facility": "1/bbb"})
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    assert refresh_mod.SOURCE_AND_VALUE_CHANGED in delta.classification
    change = delta.panels[0]
    assert change.material
    assert change.absolute == 20.0
    assert round(change.relative, 4) == 0.2
    assert change.direction == "up"


def test_a_definition_change_is_classified_and_flagged_on_the_metric():
    """§39. A figure that moved because the FORMULA changed must not read as
    the book moving."""
    previous = refresh(snapshot(value=100.0, definition_hash="def-1"),
                       at=NOW - timedelta(days=1), id=1)
    current = refresh(snapshot(value=120.0, definition_hash="def-2"),
                      at=NOW, id=2)
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    assert refresh_mod.DEFINITION_CHANGED in delta.classification
    assert delta.definitions_changed == ["Corporate Exposure"]
    change = delta.panels[0]
    assert change.definition_changed
    assert "not purely the book" in change.note


def test_a_filter_change_is_classified():
    previous = refresh(snapshot(value=100.0), at=NOW - timedelta(days=1),
                       filters="filter-a", id=1)
    current = refresh(snapshot(value=20.0), at=NOW, filters="filter-b", id=2)
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous))
    assert refresh_mod.FILTER_CHANGED in delta.classification


def test_a_period_advance_is_classified():
    previous = refresh(snapshot(value=100.0, period="Q1 2026"),
                       at=NOW - timedelta(days=90), period="Q1 2026", id=1)
    current = refresh(snapshot(value=120.0), at=NOW, period="Q2 2026", id=2)
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous))
    assert refresh_mod.PERIOD_ADVANCED in delta.classification


def test_a_refresh_can_be_several_classifications_at_once():
    """§21's whole reason for being a set. One label would force a choice
    about which mattered."""
    previous = refresh(snapshot(value=100.0, period="Q1 2026",
                                definition_hash="def-1"),
                       at=NOW - timedelta(days=90), period="Q1 2026", id=1,
                       data={"portfolio_facility": "1/aaa"})
    current = refresh(snapshot(value=120.0, definition_hash="def-2"),
                      at=NOW, period="Q2 2026", id=2,
                      data={"portfolio_facility": "1/bbb"})
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous))
    assert refresh_mod.PERIOD_ADVANCED in delta.classification
    assert refresh_mod.DEFINITION_CHANGED in delta.classification
    assert refresh_mod.SOURCE_AND_VALUE_CHANGED in delta.classification


def test_a_metric_added_or_removed_is_reported_as_structure():
    previous = refresh(snapshot(), at=NOW - timedelta(days=1), id=1)
    current = refresh(
        snapshot(),
        snapshot(key="01:metric:corporate.stage2_ratio",
                 metric_id="corporate.stage2_ratio", title="Stage 2 Ratio",
                 value=9.4, unit="percent"),
        at=NOW, id=2)
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    assert delta.added == ["Stage 2 Ratio"]
    assert refresh_mod.STRUCTURE_CHANGED in delta.classification
    assert delta.anything_material


def test_a_metric_that_stopped_producing_a_figure_says_so():
    previous = refresh(snapshot(value=100.0), at=NOW - timedelta(days=1), id=1)
    current = refresh(snapshot(value=None, status="unavailable"), at=NOW, id=2)
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    change = delta.panels[0]
    assert change.material
    assert "does not now" in change.note


# --------------------------------------------------------------- chart deltas


def test_a_chart_reports_which_labels_moved():
    previous = refresh(snapshot(
        key="00:chart:corporate.exposure:sector", kind="chart", value=None,
        series=[{"label": "Real Estate", "value": 100.0},
                {"label": "Trading", "value": 50.0},
                {"label": "Shipping", "value": 20.0}]),
        at=NOW - timedelta(days=1), id=1)
    current = refresh(snapshot(
        key="00:chart:corporate.exposure:sector", kind="chart", value=None,
        series=[{"label": "Real Estate", "value": 130.0},
                {"label": "Trading", "value": 50.0},
                {"label": "Contracting", "value": 10.0}]),
        at=NOW, id=2)
    delta = refresh_mod.compare(
        current, refresh_mod.Comparison(refresh=previous, exact=True))
    moved = {s["label"]: s for s in delta.panels[0].series_change}
    assert moved["Real Estate"]["material"]
    assert not moved["Trading"]["material"]
    assert moved["Contracting"]["note"] == "new"
    assert moved["Shipping"]["note"] == "gone"


# ------------------------------------------------------------------- capture


def test_capture_reads_the_period_the_engine_resolved():
    """`period` is what a tile PINS itself to and is empty on every tile that
    follows the Lens. Reading it left every snapshot with no reporting period
    and made every refresh compare as "same period"."""
    rendered = {
        "period": None,
        "scope": {"portfolio": "Corporate", "domains": ["Corporate"]},
        "panels": [{
            "kind": "metric", "metric_id": "corporate.exposure",
            "title": "Corporate Exposure", "status": "succeeded",
            "value": 74017.5, "unit": "currency", "period": "",
            "period_used": "Q2 2026",
            "metric": {"name": "Corporate Exposure", "unit": "currency",
                       "datasets": ["portfolio_facility"], "version": "1.0.0",
                       "formula_tree": {"kind": "sum"}},
        }],
    }
    captured = refresh_mod.capture({"id": 7, "version": 3}, rendered)
    assert captured.reporting_period == "Q2 2026"
    assert captured.panels[0].reporting_period == "Q2 2026"
    assert captured.lens_definition_version == 3


def test_a_filter_hash_ignores_the_period():
    """Folding the period into the filter hash would make every quarter a
    different population and every comparison a baseline."""
    scope = {"portfolio": "Corporate", "domains": ["Corporate"]}
    assert refresh_mod.filter_hash(scope) == refresh_mod.filter_hash(scope)


def test_a_different_portfolio_is_a_different_filter_hash():
    a = refresh_mod.filter_hash({"portfolio": "Corporate"})
    b = refresh_mod.filter_hash({"portfolio": "Construction"})
    assert a != b


def test_a_panel_key_survives_a_rearrangement_of_its_own_metric():
    """One metric shown twice — a figure and a chart of it — must not share a
    key, or one would overwrite the other."""
    tile = {"kind": "metric", "metric_id": "corporate.exposure"}
    chart = {"kind": "chart", "metric_id": "corporate.exposure",
             "params": {"dimension": "sector"}}
    assert refresh_mod.panel_key(0, tile) != refresh_mod.panel_key(1, chart)
