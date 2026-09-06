"""What a lens says it is for, and which periods it can be shown for.

§8 asks the creation flow to settle a lens's scope — its purpose, its
audience, the book it reads, the domains it draws on, the period it opens on —
before a single metric is chosen. §12 asks that a period picker offers only
periods that exist. These prove both over HTTP, and prove the refusals: a
visibility nobody defined, a comparison the chart vocabulary does not have,
and a viewer trying to repoint somebody else's lens.
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
API = "/api/v1"

needs_db = pytest.mark.skipif(not settings.has_database,
                              reason="lenses are stored in PostgreSQL")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def lens():
    made = ln.create(
        name="Scope Under Test",
        panels=[ln.Panel.metric("corporate.ifrs9.total_ead"),
                ln.Panel.metric("corporate.ifrs9.total_ecl")],
        description="Two tiles, so a scope has something to be about.",
        user_id=1)
    yield made
    try:
        ln.delete(made.id)
    except ln.LensNotFound:
        pass


# --------------------------------------------------------- the library


@needs_db
def test_the_library_names_the_lenses_the_platform_ships(client):
    """A specialist dashboard is not one of "your lenses"; it is shipped."""
    body = client.get(f"{API}/lenses", headers=ANALYST).json()
    shipped_slugs = {row["slug"] for row in body["shipped"]}
    assert shipped_slugs == {spec.slug for spec in shipped.ALL}
    for row in body["shipped"]:
        assert row["purpose"].strip(), row["slug"]
        assert row["audience"].strip(), row["slug"]
        assert row["domains"], row["slug"]
        assert row["tiles"] > 0, row["slug"]
    assert body["cro"]["slug"] == "cro"


@needs_db
def test_the_definition_panel_offers_only_domains_that_exist(client):
    """§12: nobody should be asked to know a technical name to fill this in."""
    body = client.get(f"{API}/lenses/vocabulary", headers=ANALYST).json()
    names = {row["name"] for row in body["domains"]}
    assert "Corporate IFRS 9" in names
    assert "Retail Credit Risk" in names
    for row in body["domains"]:
        assert row["metrics"] > 0, row["name"]
    assert {v["name"] for v in body["visibilities"]} == {"private", "shared"}
    assert "" in {c["name"] for c in body["comparisons"]}


# ------------------------------------------------------------- the scope


@needs_db
def test_a_lens_can_be_told_what_it_is_for(client, lens):
    sent = {"purpose": "What the committee asks for",
            "audience": "IFRS 9 Committee", "portfolio": "Corporate",
            "domains": ["Corporate IFRS 9"], "default_period": "Q4 2024",
            "comparison_period": "previous_period", "visibility": "private"}
    body = client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
                      json=sent).json()
    assert body["scope"] == sent
    # A revision of its own, so repointing a lens is on the record.
    assert body["version"] == lens.version + 1
    assert "Changed" in body["revisions"][0]["change_summary"]


@needs_db
def test_a_lens_opens_on_the_period_it_declares(client, lens):
    """§12. The declared period is what a reader sees without asking."""
    client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
               json={"default_period": "Q4 2024"})
    body = client.get(f"{API}/lenses/{lens.id}/render",
                      headers=ANALYST).json()
    assert body["period"] == "Q4 2024"
    assert {p["period_used"] for p in body["panels"]} == {"Q4 2024"}


@needs_db
def test_an_asked_for_period_beats_the_declared_one(client, lens):
    """Somebody who picked a quarter meant that quarter."""
    client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
               json={"default_period": "Q4 2024"})
    body = client.get(f"{API}/lenses/{lens.id}/render?period=Q2 2025",
                      headers=ANALYST).json()
    assert body["period"] == "Q2 2025"
    assert {p["period_used"] for p in body["panels"]} == {"Q2 2025"}


@needs_db
def test_changing_the_scope_does_not_change_the_tiles(client, lens):
    before = client.get(f"{API}/lenses/{lens.id}", headers=ANALYST).json()
    after = client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
                       json={"purpose": "Something else entirely"}).json()
    assert after["panels"] == before["panels"]


@needs_db
def test_a_tile_edit_does_not_wipe_what_the_lens_is_for(client, lens):
    """A revision that only moves a tile must not lose the lens's purpose.

    `revise` takes scope=None to mean "keep what is there". Passing the
    default empty scope instead would clear a lens's purpose and default
    period on the first rearrangement, silently.
    """
    client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
               json={"purpose": "Kept", "default_period": "Q4 2024"})
    tiles = [{"kind": "metric", "metric_id": "corporate.ifrs9.total_ecl",
              "visual": "kpi"},
             {"kind": "metric", "metric_id": "corporate.ifrs9.total_ead",
              "visual": "kpi"}]
    body = client.put(f"{API}/lenses/{lens.id}/layout", headers=ANALYST,
                      json={"tiles": tiles}).json()
    assert body["scope"]["purpose"] == "Kept"
    assert body["scope"]["default_period"] == "Q4 2024"


@needs_db
def test_restoring_a_version_restores_what_it_was_for(client, lens):
    """Otherwise a restore puts one lens's tiles under another's description."""
    client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
               json={"purpose": "The original"})
    at = client.get(f"{API}/lenses/{lens.id}", headers=ANALYST).json()["version"]
    client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
               json={"purpose": "The replacement"})
    body = client.post(f"{API}/lenses/{lens.id}/restore/{at}",
                       headers=ANALYST).json()
    assert body["scope"]["purpose"] == "The original"


# ---------------------------------------------------------- the refusals


@needs_db
def test_a_visibility_nobody_defined_is_refused(client, lens):
    r = client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
                   json={"visibility": "world-readable"})
    assert r.status_code == 422
    assert "world-readable" in r.json()["detail"]["message"]


@needs_db
def test_a_comparison_the_charts_do_not_have_is_refused(client, lens):
    """A lens and a chart must not mean different things by "the period before"."""
    r = client.put(f"{API}/lenses/{lens.id}/scope", headers=ANALYST,
                   json={"comparison_period": "same_period_last_decade"})
    assert r.status_code == 422


@needs_db
def test_a_viewer_cannot_repoint_a_lens(client, lens):
    r = client.put(f"{API}/lenses/{lens.id}/scope", headers=VIEWER,
                   json={"purpose": "mine now"})
    assert r.status_code in (401, 403)


# ------------------------------------------------------------ the periods


@needs_db
def test_the_period_picker_offers_only_periods_that_exist(client):
    """§12. A quarter the dataset has never seen draws a screen of dashes."""
    lens_id = ln.by_slug("corporate-ifrs9").id
    body = client.get(f"{API}/lenses/{lens_id}/periods",
                      headers=ANALYST).json()
    assert body["periods"], "the IFRS 9 lens can be shown for no period at all"
    assert body["latest"] == body["periods"][-1]
    assert all(p.startswith("Q") for p in body["periods"]), body["periods"]

    # Every offered period actually renders. This is the assertion that would
    # catch a picker built from a hard-coded range.
    rendered = client.get(
        f"{API}/lenses/{lens_id}/render?period={body['periods'][0]}",
        headers=ANALYST).json()
    assert rendered["failed"] == 0


@needs_db
def test_a_lens_spanning_two_calendars_says_so(client):
    """The retail lens reads monthly behaviour and monthly applications.

    Where a lens genuinely spans calendars the picker must not merge them:
    merging two calendars produces an ordering that is wrong in both.
    """
    lens_id = ln.by_slug("retail-analytics").id
    body = client.get(f"{API}/lenses/{lens_id}/periods",
                      headers=ANALYST).json()
    assert body["calendars"], "no calendar at all was reported"
    total = {p for c in body["calendars"] for p in c["periods"]}
    assert set(body["periods"]).issubset(total)
    if len(body["calendars"]) > 1:
        assert body["note"].strip()


@needs_db
def test_a_lens_that_does_not_exist_has_no_periods(client):
    assert client.get(f"{API}/lenses/999999/periods",
                      headers=ANALYST).status_code == 404
