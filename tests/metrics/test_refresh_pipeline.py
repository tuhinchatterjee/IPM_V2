"""§51's second integration path, against a real Lens and a real database.

    Lens open → current execution → snapshot → prior comparison
              → Opus package → interpretation → claim verification → render

Skips itself without PostgreSQL, because there is nothing to test: a Lens with
no memory renders and says so, and that IS covered here.
"""

from __future__ import annotations

import pytest

from backend.metrics import refresh as refresh_mod
from backend.metrics import refresh_pipeline as pipeline
from backend.metrics import refresh_store
from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="the refresh pipeline needs the database to remember anything")


@pytest.fixture()
def lens_id():
    """A shipped Lens with its own refresh history, cleared before each test."""
    from backend.services import lenses as lens_service

    try:
        view = lens_service.by_slug("portfolio-quality")
    except Exception:  # pragma: no cover - the shipped lenses are not seeded
        pytest.skip("the shipped Lenses are not installed in this database")
    _clear(view.id)
    yield view.id
    _clear(view.id)


def _clear(lens_id: int) -> None:
    from sqlalchemy import delete

    from backend.db.engine import get_session
    from backend.models.platform import LensRefresh

    with get_session() as session:
        session.execute(delete(LensRefresh).where(
            LensRefresh.lens_id == lens_id))
        session.commit()


# ------------------------------------------------------- §43: the baseline


def test_the_first_refresh_is_a_baseline_and_says_so(lens_id):
    outcome = pipeline.run(lens_id, trigger=refresh_mod.TRIGGER_OPENED)
    assert outcome.remembered
    assert outcome.refresh.id is not None
    assert outcome.refresh.baseline
    assert outcome.delta.classification == [refresh_mod.BASELINE]
    assert "next comparable refresh" in outcome.reading.headline


def test_the_snapshot_records_a_reporting_period(lens_id):
    """§18B. A Lens that pins no period still reports one — the period its
    tiles actually read."""
    outcome = pipeline.run(lens_id)
    assert outcome.refresh.reporting_period
    assert all(p.reporting_period for p in outcome.refresh.panels
               if p.status == "succeeded")


def test_every_panel_gets_a_snapshot_including_the_unavailable_ones(lens_id):
    """A metric available last refresh and not now is a change worth
    reporting, and a table of successes could not report it."""
    outcome = pipeline.run(lens_id)
    rendered = len(outcome.rendered["panels"])
    assert len(outcome.refresh.panels) == rendered


# ------------------------------------------------------- §38: no change


def test_a_second_refresh_over_identical_data_finds_nothing(lens_id):
    pipeline.run(lens_id, trigger=refresh_mod.TRIGGER_OPENED)
    outcome = pipeline.run(lens_id, trigger=refresh_mod.TRIGGER_MANUAL)

    assert outcome.delta.classification == [refresh_mod.NO_SOURCE_CHANGE]
    assert not outcome.delta.anything_material
    assert outcome.reading.no_material_change
    assert "No material changes" in outcome.reading.headline
    # …and the comparison was exact rather than relaxed.
    assert outcome.delta.comparison.exact
    assert outcome.delta.comparison.refresh is not None


def test_opening_a_lens_twice_does_not_manufacture_daily_movement(lens_id):
    """§21's opening line, tested directly."""
    pipeline.run(lens_id)
    pipeline.run(lens_id)
    outcome = pipeline.run(lens_id)
    assert not outcome.delta.material_changes


# --------------------------------------------- §24: comparable selection


def test_the_previous_comparable_refresh_is_chosen_by_id(lens_id):
    first = pipeline.run(lens_id).refresh
    second = pipeline.run(lens_id).refresh
    third = pipeline.run(lens_id)
    assert third.delta.comparison.refresh.id == second.id
    assert third.delta.comparison.refresh.id != first.id


def test_a_refresh_records_which_one_it_was_compared_with(lens_id):
    pipeline.run(lens_id)
    outcome = pipeline.run(lens_id)
    stored = refresh_store.get(outcome.refresh.id)
    assert stored.compared_with_id == outcome.delta.comparison.refresh.id


# ---------------------------------------------------- §25: the package


def test_the_package_is_bounded(lens_id):
    """§45. The whole point of the package is that it is a fraction of the
    figures the Lens holds."""
    import json

    pipeline.run(lens_id)
    outcome = pipeline.run(lens_id)
    size = len(json.dumps(outcome.package, default=str))
    assert size < 120_000, (
        f"the package is {size} characters, which is a prompt nobody should "
        "pay for and no model reads carefully")
    assert outcome.package["metrics"]
    assert outcome.package["refresh"]["reporting_period"]
    assert outcome.package["lens"]["name"]


def test_the_package_separates_the_two_domains(lens_id):
    pipeline.run(lens_id)
    outcome = pipeline.run(lens_id)
    assert "cockpit_changes" in outcome.package
    assert "ews_changes" in outcome.package


# ------------------------------------------------------ §22 and §32


def test_the_two_histories_are_kept_apart(lens_id):
    for _ in range(3):
        pipeline.run(lens_id)
    outcome = pipeline.run(lens_id)
    metric_id = next(p.metric_id for p in outcome.refresh.panels
                     if p.metric_id and p.status == "succeeded")

    series = refresh_store.series(lens_id, metric_id)
    # Four refreshes, all of the same quarter.
    assert len(series["refresh_history"]) == 4
    assert len(series["reporting_period_history"]) == 1
    assert "each time the Lens ran" in series["labels"]["refresh_history"]
    assert "each business period" in \
        series["labels"]["reporting_period_history"]


def test_history_is_newest_first_and_bounded(lens_id):
    for _ in range(3):
        pipeline.run(lens_id)
    history = refresh_store.history(lens_id, limit=2)
    assert len(history) == 2
    assert history[0].id > history[1].id


# ------------------------------------------------------------ §31: present


def test_the_header_carries_what_section_thirty_one_asks_for(lens_id):
    pipeline.run(lens_id)
    body = pipeline.present(pipeline.run(lens_id))
    assert body["reporting_period"]
    assert body["last_refreshed"]
    assert body["compared_with"] is not None
    assert "cockpit" in body["data_changes"]
    assert "ews" in body["data_changes"]
    assert body["classification_labels"]
    assert body["classification_meaning"]
    assert body["changes"]["headline"]
    assert body["history"]


# ------------------------------------------------------------- §19: one
#                                                                pipeline


@pytest.mark.parametrize("trigger", [
    refresh_mod.TRIGGER_OPENED,
    refresh_mod.TRIGGER_MANUAL,
    refresh_mod.TRIGGER_SCHEDULED,
])
def test_all_three_doors_lead_to_the_same_pipeline(lens_id, trigger):
    outcome = pipeline.run(lens_id, trigger=trigger)
    assert outcome.refresh.trigger == trigger
    assert outcome.remembered


def test_a_refresh_can_skip_the_written_reading(lens_id):
    """The figures and the deterministic change without paying for prose."""
    pipeline.run(lens_id)
    outcome = pipeline.run(lens_id, interpret=False)
    assert outcome.reading is None
    assert outcome.delta is not None
    assert outcome.refresh.id is not None


# ------------------------------------------------- §39: definition change


def test_a_definition_change_is_detected_from_the_stored_snapshots(lens_id):
    """§39's mechanism, without needing to actually edit a governed metric:
    the definition hash is what distinguishes "this moved" from "this is
    calculated differently now", and it is computed from the definition rather
    than from a version somebody remembered to increment."""
    pipeline.run(lens_id)
    outcome = pipeline.run(lens_id)
    stored = refresh_store.get(outcome.refresh.id)
    assert all(p.definition_hash for p in stored.panels)

    # Rewrite one snapshot's definition hash, as an edited formula would.
    from backend.db.engine import get_session
    from backend.models.platform import LensMetricSnapshot

    with get_session() as session:
        row = session.query(LensMetricSnapshot).filter(
            LensMetricSnapshot.refresh_id == outcome.refresh.id).first()
        row.definition_hash = "changed-by-an-edit"
        session.commit()

    later = pipeline.run(lens_id)
    assert refresh_mod.DEFINITION_CHANGED in later.delta.classification
    assert later.delta.definitions_changed
