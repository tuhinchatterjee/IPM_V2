"""Four real people, one real database, one real HTTP client.

The permission tests in this package are the reason it exists, and they are
only worth anything if they run through the actual application: a service
called directly with a hand-made principal proves that the service checks,
not that the route does. Every fixture here therefore ends at `TestClient`,
and the only thing a test varies is the header naming who is calling.

The cast, which the spec names:

  Alice    manages the project. Owner access.
  Bob      does the work. Contributor access — his own tasks, and nothing else.
  Carol    watches. Viewer access, reads everything, changes nothing.
  Mallory  is a real, valid, signed-in user of CreditProbe who has nothing to
           do with this project. She is not an attacker from outside; she is
           the far more common case, and the one an id in a URL invites.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available

PREFIX = "/api/v1/planner"


def headers(user_id: int, role: str = "ANALYST") -> dict[str, str]:
    return {"X-IPM-Role": role, "X-IPM-User-Id": str(user_id)}


@pytest.fixture(scope="session", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def cast() -> dict[str, int]:
    """Create the four users once, with names nothing else will collide with."""
    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    people = {"alice": "ANALYST", "bob": "ANALYST",
              "carol": "VIEWER", "mallory": "ANALYST"}
    ids: dict[str, int] = {}
    with get_session() as session:
        for name, role in people.items():
            row = User(username=f"planner-{name}-{tag}",
                       password_hash="x", role=role,
                       first_name=name.title(), last_name="Test",
                       email=f"{name}-{tag}@example.invalid")
            session.add(row)
            session.flush()
            ids[name] = int(row.id)
        session.commit()
    return ids


@pytest.fixture(scope="session")
def project(client, cast) -> dict:
    """One project with the cast on it, built entirely through the API.

    Built through HTTP on purpose. A fixture that reaches into the database
    to insert participants would be testing a state the product cannot
    actually reach, and would hide a broken participant route.
    """
    tag = uuid.uuid4().hex[:6].upper()
    created = client.post(
        f"{PREFIX}/projects",
        headers=headers(cast["alice"]),
        json={"code": f"TST-{tag}", "name": "Permission fixture project",
              "status": "ACTIVE", "manager_id": cast["alice"],
              "start_date": "2026-01-05", "target_end_date": "2026-12-18"})
    assert created.status_code == 201, created.text
    detail = created.json()
    project_id = detail["project"]["id"]

    for name, role, access in (("bob", "CONTRIBUTOR", "CONTRIBUTOR"),
                                ("carol", "REVIEWER", "VIEWER")):
        added = client.post(
            f"{PREFIX}/projects/{project_id}/participants",
            headers=headers(cast["alice"]),
            json={"user_id": cast[name], "project_role": role,
                  "access": access})
        assert added.status_code == 200, added.text

    ws = client.post(f"{PREFIX}/projects/{project_id}/workstreams",
                     headers=headers(cast["alice"]),
                     json={"code": "WS-A", "name": "Delivery"})
    assert ws.status_code == 201, ws.text

    bobs = client.post(
        f"{PREFIX}/projects/{project_id}/tasks", headers=headers(cast["alice"]),
        json={"code": "T-BOB", "title": "Bob's task", "owner_id": cast["bob"],
              "start_date": "2026-02-02", "due_date": "2026-03-02"})
    assert bobs.status_code == 201, bobs.text

    alices = client.post(
        f"{PREFIX}/projects/{project_id}/tasks", headers=headers(cast["alice"]),
        json={"code": "T-ALICE", "title": "Alice's task",
              "owner_id": cast["alice"],
              "start_date": "2026-02-02", "due_date": "2026-04-02"})
    assert alices.status_code == 201, alices.text

    return {"id": project_id, "code": detail["project"]["code"],
            "bob_task": bobs.json()["id"], "alice_task": alices.json()["id"]}
