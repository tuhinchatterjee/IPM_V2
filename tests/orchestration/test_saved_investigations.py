"""
Saved investigations: what refreshing an answer is allowed to mean.

The behaviours asserted here are the product's promises, not implementation
details:

  * a saved investigation keeps the answer it had, and gains versions
  * a refresh RE-EXECUTES; it never carries a figure forward
  * the account of what changed is a subtraction of two engine results, and it
    says which way each figure moved without claiming why
  * a metric that only exists on one side is not reported as a movement, because
    there is nothing to compare it with

Everything here needs PostgreSQL, because "kept" is the whole point.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.helpers import FACILITY
from backend.orchestration import investigations as inv
from tests.conftest import database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL not reachable")

QUESTION = "Which sectors deteriorated the most?"


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built — run `python scripts/build_data_lake.py`")


@pytest.fixture(scope="module")
def periods() -> list[str]:
    from backend.orchestration.vocabulary import get_vocabulary

    return get_vocabulary().periods


@pytest.fixture
def saved(periods):
    from backend.orchestration.executor import run_investigation

    result = run_investigation(QUESTION, period=(periods[-2], periods[-1]))
    assert result.status == "succeeded"
    return inv.save(result, title="Sector deterioration")


# ------------------------------------------------------------------ saving


def test_saving_keeps_the_answer_that_was_produced(saved):
    assert saved.version == 1
    assert saved.title == "Sector deterioration"
    assert saved.question == QUESTION
    assert saved.narrative["direct_answer"], "the answer itself must be kept"
    # Version 1 has nothing to compare with, and says so rather than inventing a
    # movement from zero.
    assert saved.change_narrative == ""
    assert saved.changes == []


def test_a_saved_investigation_records_the_periods_it_was_answered_for(saved, periods):
    assert (saved.from_period, saved.to_period) == (periods[-2], periods[-1])


def test_a_saved_investigation_appears_in_the_listing(saved):
    ids = [row["id"] for row in inv.listing()]
    assert saved.id in ids


# --------------------------------------------------------------- refreshing


def test_refreshing_adds_a_version_and_keeps_the_old_one(saved):
    refreshed = inv.refresh(saved.id)
    assert refreshed.version == 2
    assert [v["version"] for v in refreshed.versions] == [1, 2]

    original = inv.load(saved.id, version=1)
    assert original.version == 1
    assert original.narrative["direct_answer"] == saved.narrative["direct_answer"]


def test_a_refresh_over_unchanged_data_says_the_figures_were_recalculated(saved):
    """The promise that matters: identical does not mean copied."""
    refreshed = inv.refresh(saved.id)
    story = refreshed.change_narrative.lower()
    assert "nothing measured here moved" in story
    assert "calculated again" in story
    assert "carried forward" in story


def test_refreshing_with_a_wider_window_reports_what_moved(saved, periods):
    if len(periods) < 4:
        pytest.skip("Not enough published periods to widen the window")
    refreshed = inv.refresh(saved.id, period=(periods[-4], periods[-1]))
    assert (refreshed.from_period, refreshed.to_period) == (periods[-4], periods[-1])
    assert refreshed.changes, "a comparison must be recorded"
    assert refreshed.change_narrative


def test_the_change_narrative_never_claims_a_cause(saved, periods):
    refreshed = inv.refresh(saved.id, period=(periods[-3], periods[-1]))
    story = refreshed.change_narrative.lower()
    for forbidden in ("because of", "caused by", "driven by", "due to"):
        assert forbidden not in story, f"the narrative asserted causation: {forbidden!r}"


def test_archiving_stops_it_being_current_without_deleting_its_history(saved):
    archived = inv.archive(saved.id)
    assert archived.status == "archived"
    assert archived.versions, "the versions and their Traces survive"


# --------------------------------------------------------------- comparison


def test_comparison_only_reports_metrics_present_on_both_sides():
    before = {"metrics": [
        {"label": "Total ECL", "value": 100.0, "unit": "USD mn", "direction": "up-is-bad"},
        {"label": "Gone", "value": 5.0, "unit": "%", "direction": "up-is-bad"},
    ]}
    after = {"metrics": [
        {"label": "Total ECL", "value": 130.0, "unit": "USD mn", "direction": "up-is-bad"},
        {"label": "New", "value": 9.0, "unit": "%", "direction": "up-is-bad"},
    ]}
    changes = {c.label: c for c in inv.compare(before, after)}
    assert set(changes) == {"Total ECL"}
    assert changes["Total ECL"].change == pytest.approx(30.0)
    assert changes["Total ECL"].moved


def test_a_metric_that_did_not_move_is_recorded_as_not_moved():
    same = {"metrics": [{"label": "Total EAD", "value": 48600.0, "unit": "USD mn"}]}
    change = inv.compare(same, same)[0]
    assert change.change == 0
    assert not change.moved


def test_the_narrative_names_the_largest_movement():
    before = {"metrics": [
        {"label": "Total ECL", "value": 100.0, "unit": "USD mn", "direction": "up-is-bad"},
        {"label": "NPL ratio", "value": 4.0, "unit": "%", "direction": "up-is-bad"},
    ]}
    after = {"metrics": [
        {"label": "Total ECL", "value": 160.0, "unit": "USD mn", "direction": "up-is-bad"},
        {"label": "NPL ratio", "value": 4.1, "unit": "%", "direction": "up-is-bad"},
    ]}
    story = inv.change_narrative(
        inv.compare(before, after), from_label="Q4 2025", to_label="Q1 2026"
    )
    assert "Total ECL" in story
    assert "+60.0 USD mn" in story
    assert "adverse" in story
