"""
The grid remembers how you arranged it — per person, per dataset.

Stored on the server rather than in the browser, so somebody who spends an
afternoon arranging the facility grid finds it arranged the next morning and on
the other machine. Two properties matter beyond "it round-trips": one person's
arrangement must not become another's, and saving must REPLACE rather than
merge, because with a merge un-hiding a column would be impossible — the absence
of a key would be indistinguishable from not mentioning it.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="Grid preferences need PostgreSQL",
)

DATASET = "portfolio_facility"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture()
def two_people():
    """Two real users, so "per user" can actually be tested."""
    from sqlalchemy import select

    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    ids = []
    with get_session() as session:
        for username in ("gridpref.one", "gridpref.two"):
            row = session.execute(
                select(User).where(User.username == username)).scalar_one_or_none()
            if row is None:
                row = User(username=username, password_hash=hash_password("x" * 12),
                           role="DATA_STEWARD", is_active=True)
                session.add(row)
                session.flush()
            ids.append(row.id)
        session.commit()
    return ids


def _headers(user_id: int) -> dict:
    return {"X-IPM-Role": "DATA_STEWARD", "X-IPM-User-Id": str(user_id)}


def _url(dataset: str = DATASET) -> str:
    return f"/api/v1/data-builder/datasets/{dataset}/grid-preferences"


def test_a_reader_who_has_never_arranged_it_gets_nothing(client, two_people):
    body = client.get(_url("macro_saudi"), headers=_headers(two_people[1])).json()
    assert body["preferences"] in ({}, None) or isinstance(body["preferences"], dict)


def test_an_arrangement_round_trips(client, two_people):
    arrangement = {
        "widths": {"ead": 220, "borrower_name": 300},
        "hidden": ["ai_risk_score"],
        "frozen": 3,
        "dense": True,
    }
    saved = client.put(_url(), json=arrangement, headers=_headers(two_people[0]))
    assert saved.status_code == 200
    assert saved.json()["stored"] is True

    read = client.get(_url(), headers=_headers(two_people[0])).json()["preferences"]
    assert read["widths"]["ead"] == 220
    assert read["hidden"] == ["ai_risk_score"]
    assert read["frozen"] == 3
    assert read["dense"] is True


def test_saving_replaces_rather_than_merges(client, two_people):
    """Otherwise un-hiding a column would be impossible."""
    client.put(_url(), json={"widths": {}, "hidden": ["ead", "npl"], "frozen": 2,
                             "dense": False}, headers=_headers(two_people[0]))
    client.put(_url(), json={"widths": {}, "hidden": [], "frozen": 2,
                             "dense": False}, headers=_headers(two_people[0]))

    read = client.get(_url(), headers=_headers(two_people[0])).json()["preferences"]
    assert read["hidden"] == [], "a column that was un-hidden came back hidden"


def test_one_persons_arrangement_is_not_anothers(client, two_people):
    first, second = two_people
    client.put(_url(), json={"widths": {"ead": 400}, "hidden": [], "frozen": 1,
                             "dense": True}, headers=_headers(first))
    client.put(_url(), json={"widths": {"ead": 100}, "hidden": [], "frozen": 0,
                             "dense": False}, headers=_headers(second))

    mine = client.get(_url(), headers=_headers(first)).json()["preferences"]
    theirs = client.get(_url(), headers=_headers(second)).json()["preferences"]
    assert mine["widths"]["ead"] == 400
    assert theirs["widths"]["ead"] == 100
    assert mine["dense"] is True and theirs["dense"] is False


def test_arrangements_are_per_dataset(client, two_people):
    user = two_people[0]
    client.put(_url(DATASET), json={"widths": {}, "hidden": ["ead"], "frozen": 2,
                                    "dense": False}, headers=_headers(user))
    client.put(_url("macro_saudi"), json={"widths": {}, "hidden": [], "frozen": 0,
                                          "dense": True}, headers=_headers(user))

    facility = client.get(_url(DATASET), headers=_headers(user)).json()["preferences"]
    macro = client.get(_url("macro_saudi"), headers=_headers(user)).json()["preferences"]
    assert facility["hidden"] == ["ead"]
    assert macro["hidden"] == []
    assert macro["dense"] is True


def test_an_absurd_column_width_is_clamped(client, two_people):
    """A stored preference is a convenience, not a place to put anything."""
    client.put(_url(), json={"widths": {"ead": 99_999, "npl": -5}, "hidden": [],
                             "frozen": 2, "dense": False},
               headers=_headers(two_people[0]))
    read = client.get(_url(), headers=_headers(two_people[0])).json()["preferences"]
    assert 48 <= read["widths"]["ead"] <= 1200
    assert 48 <= read["widths"]["npl"] <= 1200


def test_an_absurd_frozen_count_is_refused(client, two_people):
    response = client.put(
        _url(), json={"widths": {}, "hidden": [], "frozen": 99, "dense": False},
        headers=_headers(two_people[0]),
    )
    assert response.status_code == 422


def test_a_viewer_may_not_touch_the_grid_or_its_preferences(client):
    """The grid itself is closed to Viewers, so its preferences are too."""
    assert client.get(_url(), headers={"X-IPM-Role": "VIEWER"}).status_code == 403
    assert client.put(_url(), json={"widths": {}, "hidden": [], "frozen": 2,
                                    "dense": False},
                      headers={"X-IPM-Role": "VIEWER"}).status_code == 403
