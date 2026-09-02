"""The Cockpit greeting is a preference, and a preference is not an identity.

Two things are being held apart here, and the second is the one that matters.

**A preference persists.** Changing "Mr. Sajid" to "Dr. Ahmed" survives a
reload, a restart, and a sign-out; it is per-user, so two people can be greeted
differently; and it is plain text, so markup is refused at the door rather than
escaped on the way out.

**A preference changes nothing else.** The account, its role, its permissions,
its team and every field the audit trail records are the same before and after.
A greeting stored on the user record would mean changing what the screen says
changes who the system thinks you are, and a Trace that recorded the name
somebody typed into a settings box would not be an audit trail.
"""

from __future__ import annotations

import pytest

from backend.services import preferences as prefs
from tests.conftest import database_available

ENDPOINT = "/api/v1/preferences"
GREETING = f"{ENDPOINT}/greeting-name"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("Preferences need a database.")


def _account(username: str, password: str, first: str) -> int:
    """A real signed-up account, because a preference belongs to one."""
    from sqlalchemy import select

    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    with get_session() as session:
        row = session.execute(
            select(User).where(User.username == username)).scalar_one_or_none()
        if row is None:
            row = User(username=username, password_hash=hash_password(password),
                       role="ANALYST", first_name=first, last_name="Test",
                       is_active=True)
            session.add(row)
        else:
            row.password_hash = hash_password(password)
            row.is_active = True
            row.role = "ANALYST"
            row.first_name = first
        session.commit()
        return int(row.id)


@pytest.fixture(scope="module")
def signed_in(client):
    """One signed-in account, and its id, cleaned up afterwards."""
    user_id = _account("pref-one", "preference-pass-1", "Sajid")
    response = client.post("/api/v1/auth/login",
                           json={"username": "pref-one",
                                 "password": "preference-pass-1"})
    assert response.status_code == 200, response.text
    yield user_id
    from sqlalchemy import text

    from backend.db.engine import get_session

    with get_session() as session:
        session.execute(text("DELETE FROM user_preferences WHERE user_id = :i"),
                        {"i": user_id})
        session.execute(text("DELETE FROM users WHERE id = :i"), {"i": user_id})
        session.commit()
    client.cookies.clear()


class TestTheValueItself:
    """Validation, unit-level: what may be stored and what may not."""

    @pytest.mark.parametrize("name", [
        "Mr. Sajid", "Ms. Fatima", "Dr. Ahmed", "Sajid",
        "Corporate Risk Team", "Al-Rashid", "O'Brien",
    ])
    def test_professional_names_are_accepted(self, name: str):
        assert prefs.clean_greeting_name(name) == name

    def test_whitespace_is_trimmed_and_collapsed(self):
        # "Mr.   Sajid" and "Mr. Sajid" are the same name; storing both makes
        # two people who typed the same thing look different.
        assert prefs.clean_greeting_name("  Mr.   Sajid  ") == "Mr. Sajid"

    @pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
    def test_an_empty_value_is_refused(self, bad: str):
        with pytest.raises(prefs.PreferenceRejected, match="cannot be empty"):
            prefs.clean_greeting_name(bad)

    @pytest.mark.parametrize("bad", [
        "<script>alert(1)</script>", "Mr. <b>Sajid</b>", "javascript:alert(1)",
        "Sajid&lt;", "Mr.\x00Sajid", "Mr.\x1bSajid", "{{name}}",
    ])
    def test_markup_and_control_characters_are_refused(self, bad: str):
        with pytest.raises(prefs.PreferenceRejected):
            prefs.clean_greeting_name(bad)

    def test_an_overlong_value_is_refused(self):
        with pytest.raises(prefs.PreferenceRejected, match="at most"):
            prefs.clean_greeting_name("A" * (prefs.MAX_LENGTH + 1))

    def test_the_length_limit_itself_is_accepted(self):
        edge = "A" * prefs.MAX_LENGTH
        assert prefs.clean_greeting_name(edge) == edge


class TestTheDefault:
    def test_the_configured_default_is_mr_sajid(self):
        assert prefs.DEFAULT_GREETING_NAME == "Mr. Sajid"

    def test_a_reader_who_has_chosen_nothing_gets_it(self, client):
        body = client.get(ENDPOINT, headers={"X-IPM-Role": "ANALYST"}).json()
        assert body["greeting_name"] == "Mr. Sajid"
        assert body["greeting_name_is_default"] is True


class TestChangingIt:
    def test_it_is_saved_and_read_back(self, client, signed_in):
        saved = client.put(GREETING, json={"greeting_name": "Dr. Ahmed"})
        assert saved.status_code == 200, saved.text
        assert saved.json()["greeting_name"] == "Dr. Ahmed"
        assert saved.json()["greeting_name_is_default"] is False
        assert client.get(ENDPOINT).json()["greeting_name"] == "Dr. Ahmed"

    def test_it_survives_a_new_connection(self, client, signed_in):
        # What "persists across a restart" means for a stored preference: the
        # value is in the database, not in the process that wrote it.
        from backend.db.engine import get_session

        client.put(GREETING, json={"greeting_name": "Ms. Fatima"})
        with get_session() as session:
            assert prefs.read(session, signed_in)["greeting_name"] == "Ms. Fatima"

    def test_an_unsafe_value_is_refused_by_the_api(self, client, signed_in):
        refused = client.put(GREETING,
                             json={"greeting_name": "<script>x</script>"})
        assert refused.status_code == 422
        assert "plain text" in refused.json()["detail"]["message"]

    def test_a_refused_value_does_not_overwrite_the_stored_one(
            self, client, signed_in):
        client.put(GREETING, json={"greeting_name": "Dr. Ahmed"})
        client.put(GREETING, json={"greeting_name": ""})
        assert client.get(ENDPOINT).json()["greeting_name"] == "Dr. Ahmed"

    def test_reset_restores_the_default(self, client, signed_in):
        client.put(GREETING, json={"greeting_name": "Dr. Ahmed"})
        back = client.delete(GREETING)
        assert back.status_code == 200
        assert back.json()["greeting_name"] == "Mr. Sajid"
        assert back.json()["greeting_name_is_default"] is True

    def test_reset_leaves_other_preferences_alone(self, client, signed_in):
        from backend.db.engine import get_session
        from backend.models.platform import UserPreference

        client.put(GREETING, json={"greeting_name": "Dr. Ahmed"})
        with get_session() as session:
            row = session.get(UserPreference, signed_in)
            row.preferences = {**row.preferences, "cockpit.density": "compact"}
            session.commit()
        client.delete(GREETING)
        with get_session() as session:
            kept = session.get(UserPreference, signed_in).preferences
            assert kept.get("cockpit.density") == "compact"
            assert prefs.GREETING_NAME not in kept


class TestItIsPresentationOnly:
    """The guarantee that makes this a preference rather than a rename."""

    def test_the_account_is_untouched(self, client, signed_in):
        from backend.db.engine import get_session
        from backend.db.models import User

        with get_session() as session:
            before = session.get(User, signed_in)
            was = (before.username, before.first_name, before.last_name,
                   before.role, before.email, before.is_active)

        client.put(GREETING, json={"greeting_name": "Dr. Ahmed"})

        with get_session() as session:
            after = session.get(User, signed_in)
            now = (after.username, after.first_name, after.last_name,
                   after.role, after.email, after.is_active)
        assert now == was, "changing the greeting changed the account"

    def test_the_signed_in_identity_the_api_reports_is_unchanged(
            self, client, signed_in):
        before = client.get("/api/v1/auth/me").json()
        client.put(GREETING, json={"greeting_name": "Dr. Ahmed"})
        after = client.get("/api/v1/auth/me").json()
        for field in ("id", "username", "role", "email", "team"):
            assert after["user"][field] == before["user"][field], field

    def test_permissions_are_unchanged(self, client, signed_in):
        before = client.get("/api/v1/auth/me").json().get("permissions")
        client.put(GREETING, json={"greeting_name": "Corporate Risk Team"})
        assert client.get("/api/v1/auth/me").json().get("permissions") == before


class TestItBelongsToOneAccount:
    def test_two_people_can_be_greeted_differently(self, client, signed_in):
        from backend.db.engine import get_session

        other = _account("pref-two", "preference-pass-2", "Fatima")
        try:
            client.put(GREETING, json={"greeting_name": "Dr. Ahmed"})
            with get_session() as session:
                prefs.set_greeting_name(session, other, "Ms. Fatima")
                assert prefs.read(session, other)["greeting_name"] == "Ms. Fatima"
                assert prefs.read(session, signed_in)["greeting_name"] == "Dr. Ahmed"
        finally:
            from sqlalchemy import text

            with get_session() as session:
                session.execute(
                    text("DELETE FROM user_preferences WHERE user_id = :i"),
                    {"i": other})
                session.execute(text("DELETE FROM users WHERE id = :i"),
                                {"i": other})
                session.commit()

    def test_nobody_signed_in_cannot_change_a_greeting(self, client):
        # There is deliberately no user id in the path: a preference is not
        # something one account sets for another.
        client.cookies.clear()
        refused = client.put(GREETING, json={"greeting_name": "Dr. Ahmed"},
                             headers={"X-IPM-Role": "ANALYST"})
        assert refused.status_code == 401
