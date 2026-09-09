"""Rearranging a lens by hand, over HTTP.

The point of this route is that arranging a lens directly is not a way around
the rules that govern arranging one by asking. What these prove: a tile drawn
as something its metric has not declared itself drawable as is refused; a band
pointing at a tile that is not there is refused; the change is versioned and
can be put back; and a viewer cannot rearrange anything.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import settings
from backend.metrics import lenses as shipped
from backend.services import lenses as ln

ANALYST = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}
VIEWER = {"X-IPM-Role": "VIEWER", "X-IPM-User-Id": "2"}

needs_db = pytest.mark.skipif(not settings.has_database,
                              reason="lenses are stored in PostgreSQL")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def lens():
    """A lens of this test's own, removed however the test ends."""
    made = ln.create(
        name="Layout Under Test",
        panels=[ln.Panel.metric("corporate.npl_rate", title="NPL rate"),
                ln.Panel.metric("corporate.ifrs9.total_ecl", title="ECL"),
                ln.Panel.metric("corporate.ifrs9.total_ead", title="Exposure")],
        description="Three tiles, so an ordering has somewhere to go.",
        user_id=1)
    yield made
    try:
        ln.delete(made.id)
    except ln.LensNotFound:
        pass


def _tiles(lens_view):
    return [{"kind": p["kind"], "metric_id": p["metric_id"],
             "analysis_id": p["analysis_id"], "title": p["title"],
             "visual": p["visual"], "params": p["params"],
             "filters": p["filters"], "period": p["period"],
             "note": p["note"]}
            for p in lens_view.panels]


@needs_db
def test_reordering_is_kept_and_versioned(client, lens):
    tiles = _tiles(lens)
    reversed_tiles = list(reversed(tiles))

    out = client.put(f"/api/v1/lenses/{lens.id}/layout",
                     json={"tiles": reversed_tiles}, headers=ANALYST)
    assert out.status_code == 200, out.text
    body = out.json()
    assert [p["metric_id"] for p in body["panels"]] == \
        [t["metric_id"] for t in reversed_tiles]

    # And the previous arrangement is still there to go back to.
    assert body["version"] > lens.version
    restored = client.post(
        f"/api/v1/lenses/{lens.id}/restore/{lens.version}",
        headers=ANALYST).json()
    assert [p["metric_id"] for p in restored["panels"]] == \
        [t["metric_id"] for t in tiles]


@needs_db
def test_a_tile_cannot_be_drawn_as_something_it_is_not(client, lens):
    """The quiet failure: a single ratio as a line of one point.

    "line" IS a way a panel may be drawn — the refusal has to come from the
    metric's own declaration, not from the global list, or the check would
    pass for every visual the platform happens to support.
    """
    tiles = _tiles(lens)
    assert "line" in ln.VISUALS, "otherwise this tests the wrong refusal"
    tiles[0]["visual"] = "line"

    out = client.put(f"/api/v1/lenses/{lens.id}/layout",
                     json={"tiles": tiles}, headers=ANALYST)
    assert out.status_code == 422, out.text
    message = out.json()["detail"]["message"]
    assert "should not be drawn" in message
    assert "kpi" in message, "the refusal has to say what it CAN be drawn as"

    # And nothing was stored.
    assert ln.get(lens.id).version == lens.version


@needs_db
def test_a_band_cannot_point_at_a_tile_that_is_not_there(client, lens):
    tiles = _tiles(lens)
    out = client.put(
        f"/api/v1/lenses/{lens.id}/layout",
        json={"tiles": tiles,
              "sections": [{"title": "Everything", "panels": [0, 1, 7]}]},
        headers=ANALYST)
    assert out.status_code == 422, out.text
    assert "points at tile 7" in out.json()["detail"]["message"]
    assert ln.get(lens.id).version == lens.version


@needs_db
def test_bands_are_stored_with_the_order_they_were_sent_with(client, lens):
    tiles = list(reversed(_tiles(lens)))
    body = client.put(
        f"/api/v1/lenses/{lens.id}/layout",
        json={"tiles": tiles,
              "sections": [{"title": "The provision",
                            "subtitle": "What is set aside.",
                            "panels": [0, 1]},
                           {"title": "The book", "panels": [2]}]},
        headers=ANALYST).json()
    assert [s["title"] for s in body["sections"]] == \
        ["The provision", "The book"]
    assert body["sections"][0]["panels"] == [0, 1]
    # `subtitle` is the key the renderer reads. Stored under any other name a
    # band's line of prose is simply absent on screen, silently.
    assert body["sections"][0]["subtitle"] == "What is set aside."


@needs_db
def test_a_lens_cannot_be_emptied_by_rearranging_it(client, lens):
    out = client.put(f"/api/v1/lenses/{lens.id}/layout",
                     json={"tiles": []}, headers=ANALYST)
    assert out.status_code == 422
    assert "at least one panel" in out.json()["detail"]["message"]


@needs_db
def test_a_rearrangement_says_what_changed(client, lens):
    """A history of nine identical summaries says which of the nine to
    restore: none of them."""
    tiles = _tiles(lens)
    client.put(f"/api/v1/lenses/{lens.id}/layout",
               json={"tiles": tiles[:2]}, headers=ANALYST)
    after = ln.get(lens.id)
    latest = after.revisions[0]
    assert "removed" in latest["change_summary"]
    assert tiles[2]["metric_id"] in latest["change_summary"]


@needs_db
def test_a_viewer_cannot_rearrange_a_lens(client, lens):
    out = client.put(f"/api/v1/lenses/{lens.id}/layout",
                     json={"tiles": _tiles(lens)}, headers=VIEWER)
    assert out.status_code == 403, out.text
    assert ln.get(lens.id).version == lens.version


@needs_db
def test_rearranging_a_lens_that_does_not_exist_is_a_clean_404(client):
    out = client.put("/api/v1/lenses/99999999/layout",
                     json={"tiles": []}, headers=ANALYST)
    assert out.status_code == 404
    assert out.json()["detail"]["error"] == "not_found"


def test_every_shipped_lens_still_checks_out():
    """Unrelated to the route, and the reason it sits here: the layout editor
    writes the same definition shape the shipped lenses use, so a change to
    that shape has to leave them installable."""
    assert shipped.check() == []


@needs_db
def test_a_lens_can_be_created_with_metric_tiles(client):
    """Most of what a lens holds now is metric tiles.

    The create route required an analysis id on every panel, which predates
    metric tiles: a lens of nothing but metrics could not be made through the
    API at all, only from inside the service.
    """
    made = client.post(
        "/api/v1/lenses",
        json={"name": "Made Of Metrics",
              "panels": [{"kind": "metric",
                          "metric_id": "corporate.ifrs9.total_ead",
                          "title": "Exposure", "visual": "kpi"}]},
        headers=ANALYST)
    assert made.status_code == 201, made.text
    body = made.json()
    try:
        assert body["panels"][0]["metric_id"] == "corporate.ifrs9.total_ead"
        assert body["panels"][0]["kind"] == "metric"
    finally:
        ln.delete(body["id"])


@needs_db
def test_a_tile_naming_neither_an_analysis_nor_a_metric_says_so(client):
    """Widening the shape must not turn a clear refusal into a vague one."""
    out = client.post(
        "/api/v1/lenses",
        json={"name": "Nothing In Particular", "panels": [{"title": "?"}]},
        headers=ANALYST)
    assert out.status_code == 422, out.text
    message = out.json()["detail"]["message"]
    assert "registered analysis" in message or "name a metric" in message, message
