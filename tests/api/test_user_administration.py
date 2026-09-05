"""Who may create a colleague, and what stops an administrator locking the door.

The four properties held here
------------------------------
1. **Only an administrator.** Enforced by the route's dependency, not by the
   screen hiding a button, so a direct call from a signed-in analyst is refused
   with the same 403 as a curl from anywhere else.
2. **Two people cannot share an identifier.** A duplicate username or address
   is two accounts nobody can tell apart in a directory, and a message sent to
   the wrong one of them looks exactly like a message sent to the right one.
3. **Deactivation is an act, not a drift.** It records who did it and when, and
   reactivating clears the flag without erasing the record.
4. **The last administrator cannot be removed.** Not by deactivation and not by
   demotion — both close the only door back into the product's administration.

Job title is checked alongside role on purpose. They are different facts: role
is what somebody MAY do and job title is what they DO, and a directory in which
four people are all "ANALYST" cannot tell a sender which of them owns the
shipping book.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available

USERS = "/api/v1/users"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("User administration needs a database.")


def _name() -> str:
    """A username no other run has used.

    The suite runs against a real database that other suites and the demo
    bootstrap also write to, so a fixed name is a test that passes once.
    """
    return f"t.{uuid.uuid4().hex[:12]}"


def _admin() -> dict[str, str]:
    return {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}


def _analyst() -> dict[str, str]:
    return {"X-IPM-Role": "ANALYST"}


@pytest.fixture
def made(client):
    """Users created by a test, removed afterwards.

    Deactivated rather than deleted where rows reference them — which is the
    product's own rule, and applying it to the fixture keeps the test from
    exercising a path the product does not have.
    """
    created: list[int] = []
    yield created
    for user_id in created:
        client.patch(f"{USERS}/{user_id}", json={"is_active": False},
                     headers=_admin())


class TestOnlyAnAdministratorMayCreate:

    def test_an_administrator_may(self, client, made):
        r = client.post(USERS, json={"username": _name(),
                                     "password": "creditprobe-demo",
                                     "first_name": "Sarah", "last_name": "Khan",
                                     "role": "ANALYST"}, headers=_admin())
        assert r.status_code == 201, r.text
        made.append(r.json()["id"])

    def test_an_analyst_may_not(self, client):
        r = client.post(USERS, json={"username": _name(),
                                     "password": "creditprobe-demo"},
                        headers=_analyst())
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "forbidden"

    def test_a_viewer_may_not(self, client):
        r = client.post(USERS, json={"username": _name(),
                                     "password": "creditprobe-demo"},
                        headers={"X-IPM-Role": "VIEWER"})
        assert r.status_code == 403

    def test_an_analyst_may_not_list_accounts_either(self, client):
        assert client.get(USERS, headers=_analyst()).status_code == 403


class TestTheFieldsAPersonIsDescribedBy:

    def test_job_title_and_department_are_stored_and_returned(self, client, made):
        r = client.post(USERS, json={
            "username": _name(), "password": "creditprobe-demo",
            "first_name": "Sarah", "last_name": "Khan",
            "job_title": "Corporate Credit Manager",
            "department": "Credit Risk", "team": "Corporate Credit",
            "role": "ANALYST"}, headers=_admin())
        assert r.status_code == 201
        body = r.json()
        made.append(body["id"])
        assert body["job_title"] == "Corporate Credit Manager"
        assert body["department"] == "Credit Risk"
        assert body["team"] == "Corporate Credit"
        # What they MAY do is a separate field from what they DO.
        assert body["role"] == "ANALYST"

    def test_they_can_be_edited(self, client, made):
        created = client.post(USERS, json={"username": _name(),
                                           "password": "creditprobe-demo",
                                           "role": "ANALYST"},
                              headers=_admin()).json()
        made.append(created["id"])
        r = client.patch(f"{USERS}/{created['id']}",
                         json={"job_title": "Portfolio Risk Manager",
                               "department": "Portfolio"}, headers=_admin())
        assert r.status_code == 200
        assert r.json()["job_title"] == "Portfolio Risk Manager"
        assert r.json()["department"] == "Portfolio"

    def test_the_display_name_is_derived_not_stored_twice(self, client, made):
        created = client.post(USERS, json={
            "username": _name(), "password": "creditprobe-demo",
            "first_name": "Sarah", "last_name": "Khan"},
            headers=_admin()).json()
        made.append(created["id"])
        assert created["display_name"] == "Sarah Khan"


class TestTwoPeopleCannotShareAnIdentifier:

    def test_a_duplicate_username_is_refused(self, client, made):
        name = _name()
        first = client.post(USERS, json={"username": name,
                                         "password": "creditprobe-demo"},
                            headers=_admin())
        assert first.status_code == 201
        made.append(first.json()["id"])
        again = client.post(USERS, json={"username": name,
                                         "password": "creditprobe-demo"},
                            headers=_admin())
        assert again.status_code == 409
        assert again.json()["detail"]["error"] == "username_taken"

    def test_a_duplicate_email_is_refused(self, client, made):
        address = f"{uuid.uuid4().hex[:10]}@example-bank.com"
        first = client.post(USERS, json={"username": _name(),
                                         "password": "creditprobe-demo",
                                         "email": address}, headers=_admin())
        assert first.status_code == 201
        made.append(first.json()["id"])
        again = client.post(USERS, json={"username": _name(),
                                         "password": "creditprobe-demo",
                                         "email": address}, headers=_admin())
        assert again.status_code == 409
        assert again.json()["detail"]["error"] == "email_taken"

    def test_an_email_is_matched_case_insensitively(self, client, made):
        address = f"{uuid.uuid4().hex[:10]}@example-bank.com"
        first = client.post(USERS, json={"username": _name(),
                                         "password": "creditprobe-demo",
                                         "email": address}, headers=_admin())
        made.append(first.json()["id"])
        again = client.post(USERS, json={"username": _name(),
                                         "password": "creditprobe-demo",
                                         "email": address.upper()},
                            headers=_admin())
        assert again.status_code == 409

    def test_a_blank_email_is_not_a_duplicate_of_another_blank_one(
            self, client, made):
        # Several accounts legitimately have no address. Treating absence as a
        # value would make the second such account impossible to create.
        for _ in range(2):
            r = client.post(USERS, json={"username": _name(),
                                         "password": "creditprobe-demo"},
                            headers=_admin())
            assert r.status_code == 201
            made.append(r.json()["id"])


class TestDeactivationIsAnAct:

    def test_it_records_when(self, client, made):
        created = client.post(USERS, json={"username": _name(),
                                           "password": "creditprobe-demo"},
                              headers=_admin()).json()
        made.append(created["id"])
        assert created["deactivated_at"] is None
        off = client.patch(f"{USERS}/{created['id']}", json={"is_active": False},
                           headers=_admin())
        assert off.status_code == 200
        assert off.json()["is_active"] is False
        assert off.json()["deactivated_at"] is not None

    def test_reactivating_clears_the_flag(self, client, made):
        created = client.post(USERS, json={"username": _name(),
                                           "password": "creditprobe-demo"},
                              headers=_admin()).json()
        made.append(created["id"])
        client.patch(f"{USERS}/{created['id']}", json={"is_active": False},
                     headers=_admin())
        on = client.patch(f"{USERS}/{created['id']}", json={"is_active": True},
                          headers=_admin())
        assert on.json()["is_active"] is True
        assert on.json()["deactivated_at"] is None

    def test_the_account_survives_deactivation(self, client, made):
        # Not a delete. Historical messages, investigations and audit rows all
        # point at this id, and removing it would take them with it.
        created = client.post(USERS, json={"username": _name(),
                                           "password": "creditprobe-demo"},
                              headers=_admin()).json()
        made.append(created["id"])
        client.patch(f"{USERS}/{created['id']}", json={"is_active": False},
                     headers=_admin())
        listing = client.get(USERS, headers=_admin()).json()
        assert any(u["id"] == created["id"] for u in listing["users"])


class TestTheLastAdministrator:

    def test_cannot_be_deactivated(self, client):
        # Whoever is the only active ADMIN on this database. Found rather than
        # assumed, so the test says something true of the deployment it runs on.
        listing = client.get(USERS, headers=_admin()).json()["users"]
        admins = [u for u in listing
                  if u["role"] == "ADMIN" and u["is_active"]]
        if len(admins) != 1:
            pytest.skip("This database has more than one administrator.")
        r = client.patch(f"{USERS}/{admins[0]['id']}", json={"is_active": False},
                         headers=_admin())
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "last_administrator"

    def test_cannot_be_demoted(self, client):
        listing = client.get(USERS, headers=_admin()).json()["users"]
        admins = [u for u in listing
                  if u["role"] == "ADMIN" and u["is_active"]]
        if len(admins) != 1:
            pytest.skip("This database has more than one administrator.")
        r = client.patch(f"{USERS}/{admins[0]['id']}", json={"role": "VIEWER"},
                         headers=_admin())
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "last_administrator"


class TestTheDirectory:
    """Who a message can be addressed to — a different question from who exists."""

    def test_an_analyst_may_read_it(self, client):
        # A sender has to be able to find a recipient. Restricting the
        # directory to administrators would make messaging unusable for
        # everybody it is for.
        assert client.get(f"{USERS}/directory",
                          headers=_analyst()).status_code == 200

    def test_it_names_people_and_teams(self, client):
        body = client.get(f"{USERS}/directory", headers=_analyst()).json()
        assert "people" in body and "teams" in body

    def test_a_deactivated_person_leaves_it(self, client, made):
        created = client.post(USERS, json={"username": _name(),
                                           "password": "creditprobe-demo",
                                           "first_name": "Temp"},
                              headers=_admin()).json()
        made.append(created["id"])
        before = client.get(f"{USERS}/directory", headers=_analyst()).json()
        assert any(p["id"] == created["id"] for p in before["people"])
        client.patch(f"{USERS}/{created['id']}", json={"is_active": False},
                     headers=_admin())
        after = client.get(f"{USERS}/directory", headers=_analyst()).json()
        assert not any(p["id"] == created["id"] for p in after["people"])


class TestAdministrationIsAudited:

    def test_creating_a_user_writes_an_audit_row(self, client, made):
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.collaboration import CollaborationAudit
        from backend.services import collaboration as collab

        created = client.post(USERS, json={"username": _name(),
                                           "password": "creditprobe-demo"},
                              headers=_admin()).json()
        made.append(created["id"])
        with get_session() as session:
            rows = session.execute(
                select(CollaborationAudit).where(
                    CollaborationAudit.action == collab.USER_CREATED,
                    CollaborationAudit.object_id == str(created["id"]))
            ).scalars().all()
        assert len(rows) == 1
        assert rows[0].subject_user_id == created["id"]

    def test_deactivating_writes_its_own_action(self, client, made):
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.collaboration import CollaborationAudit
        from backend.services import collaboration as collab

        created = client.post(USERS, json={"username": _name(),
                                           "password": "creditprobe-demo"},
                              headers=_admin()).json()
        made.append(created["id"])
        client.patch(f"{USERS}/{created['id']}", json={"is_active": False},
                     headers=_admin())
        with get_session() as session:
            actions = session.execute(
                select(CollaborationAudit.action).where(
                    CollaborationAudit.object_id == str(created["id"]))
            ).scalars().all()
        assert collab.USER_DEACTIVATED in actions
        assert collab.USER_CREATED in actions
