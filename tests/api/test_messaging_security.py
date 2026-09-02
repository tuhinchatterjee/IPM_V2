"""The access-control matrix, over HTTP, with three real signed-in people.

Why this suite goes through the HTTP layer when the others do not
------------------------------------------------------------------
The service tests prove the rules. This one proves the ROUTES apply them —
that there is no path into a mailbox that skips the participation check, that a
guessed id is refused by the server rather than merely hidden by the screen,
and that the four service errors arrive as the four statuses a caller can act
on rather than as a 500.

Three people, again, because two cannot tell "anyone may read it" apart from
"the participants may read it".

The suite signs in for real rather than sending role headers. A header-based
identity is the documented development path, and testing authorization with it
would be testing the wrong door: what has to hold is that ONE SIGNED-IN USER
cannot reach ANOTHER SIGNED-IN USER's mail.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest

from tests.conftest import database_available

API = "/api/v1"
MESSAGES = f"{API}/messages"
PASSWORD = "creditprobe-demo"


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("Messaging security needs a database.")


@pytest.fixture(scope="module")
def app():
    """Signing in is the whole point here, so this suite is the one place that
    turns the product's own default back on.

    It patches `permissions.settings` rather than reloading `backend.config`.
    Reloading builds a NEW settings object while `backend.api.permissions` goes
    on holding a reference to the old one — so the reload appears to work,
    every session-based test still passes, and the single test that asserts the
    production posture quietly asserts nothing. That is exactly how this suite
    passed alone and failed inside the full run.

    The same mechanism `tests/api/test_login_required.py` uses, for the same
    reason. One way to establish a posture, not two.
    """
    from dataclasses import replace

    import backend.api.permissions as permissions
    from backend.config import settings

    original = permissions.settings
    permissions.settings = replace(settings, require_login=True)
    yield
    permissions.settings = original


@pytest.fixture(scope="module")
def accounts():
    """Three accounts with known passwords, so each can hold its own session."""
    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    made = []
    with get_session() as session:
        for first in ("Alpha", "Beta", "Gamma"):
            row = User(username=f"t.{uuid.uuid4().hex[:12]}",
                       password_hash=hash_password(PASSWORD),
                       first_name=first, last_name="Case", role="ANALYST",
                       is_active=True)
            session.add(row)
            session.flush()
            made.append({"id": row.id, "username": row.username})
        session.commit()
    yield made
    with get_session() as session:
        for who in made:
            row = session.get(User, who["id"])
            if row is not None:
                row.is_active = False
        session.commit()


def _signed_in(username: str):
    """A client holding one person's session cookie."""
    from fastapi.testclient import TestClient

    from backend.api.main import app as fastapi_app

    client = TestClient(fastapi_app)
    r = client.post(f"{API}/auth/login",
                    json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(scope="module")
def alpha(accounts, app):
    return _signed_in(accounts[0]["username"])


@pytest.fixture(scope="module")
def beta(accounts, app):
    return _signed_in(accounts[1]["username"])


@pytest.fixture(scope="module")
def gamma(accounts, app):
    return _signed_in(accounts[2]["username"])


@pytest.fixture
def private_thread(alpha, accounts):
    """Alpha writes to Beta. Gamma is nowhere near it."""
    r = alpha.post(f"{MESSAGES}/send", json={
        "to": [accounts[1]["id"]],
        "subject": f"Private {uuid.uuid4().hex[:6]}",
        "body": "Between the two of us."})
    assert r.status_code == 201, r.text
    return r.json()


class TestAPrivateThreadIsPrivate:

    def test_the_participants_can_read_it(self, alpha, beta, private_thread):
        for client in (alpha, beta):
            r = client.get(f"{MESSAGES}/threads/{private_thread['thread_id']}")
            assert r.status_code == 200

    def test_a_third_person_cannot(self, gamma, private_thread):
        r = gamma.get(f"{MESSAGES}/threads/{private_thread['thread_id']}")
        assert r.status_code == 404

    def test_the_refusal_does_not_confirm_the_thread_exists(self, gamma,
                                                            private_thread):
        # A real-but-forbidden thread and an entirely absent one must be
        # indistinguishable, or the id space becomes an existence oracle.
        real = gamma.get(f"{MESSAGES}/threads/{private_thread['thread_id']}")
        absent = gamma.get(f"{MESSAGES}/threads/99999999")
        assert real.status_code == absent.status_code == 404
        assert real.json()["detail"]["error"] == absent.json()["detail"]["error"]

    def test_it_is_not_in_a_third_persons_inbox(self, gamma, private_thread):
        rows = gamma.get(f"{MESSAGES}?box=inbox").json()["items"]
        assert not any(i["thread_id"] == private_thread["thread_id"]
                       for i in rows)

    def test_a_third_person_cannot_reply_into_it(self, gamma, private_thread):
        r = gamma.post(f"{MESSAGES}/threads/{private_thread['thread_id']}/reply",
                       json={"body": "Butting in."})
        assert r.status_code == 404

    def test_a_third_person_cannot_mark_it_read(self, gamma, private_thread):
        r = gamma.post(f"{MESSAGES}/threads/{private_thread['thread_id']}/read",
                       json={"read": True})
        assert r.status_code == 404

    def test_a_third_person_cannot_archive_it(self, gamma, private_thread):
        r = gamma.post(
            f"{MESSAGES}/threads/{private_thread['thread_id']}/archive",
            json={"archived": True})
        assert r.status_code == 404

    def test_search_does_not_reach_it(self, alpha, gamma, accounts):
        token = uuid.uuid4().hex[:10]
        alpha.post(f"{MESSAGES}/send", json={
            "to": [accounts[1]["id"]], "subject": f"Secret {token}",
            "body": "x"})
        found = gamma.get(f"{MESSAGES}?box=inbox&q={token}").json()
        assert found["items"] == []
        assert found["total"] == 0


class TestADraftIsPrivate:

    @pytest.fixture
    def draft(self, alpha):
        r = alpha.post(f"{MESSAGES}/drafts",
                       json={"subject": "Unfinished", "body": "half a"})
        assert r.status_code == 201
        return r.json()

    def test_its_author_can_edit_it(self, alpha, draft):
        r = alpha.patch(f"{MESSAGES}/drafts/{draft['message_id']}",
                        json={"body": "half a thought"})
        assert r.status_code == 200

    def test_nobody_else_can_edit_it(self, beta, draft):
        r = beta.patch(f"{MESSAGES}/drafts/{draft['message_id']}",
                       json={"body": "hijacked"})
        assert r.status_code == 404

    def test_nobody_else_sees_it_in_their_drafts(self, beta, draft):
        rows = beta.get(f"{MESSAGES}?box=drafts").json()["items"]
        assert not any(i["message_id"] == draft["message_id"] for i in rows)

    def test_nobody_else_can_read_its_thread(self, beta, draft):
        r = beta.get(f"{MESSAGES}/threads/{draft['thread_id']}")
        assert r.status_code == 404

    def test_nobody_else_can_send_it(self, beta, draft, accounts):
        r = beta.post(f"{MESSAGES}/send",
                      json={"to": [accounts[2]["id"]],
                            "draft_id": draft["message_id"], "body": "x"})
        assert r.status_code == 404


class TestAnAttachmentIsProtected:

    @pytest.fixture
    def shared_file(self, alpha, accounts):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        content = buf.getvalue()
        up = alpha.post(f"{MESSAGES}/artifacts",
                        files={"file": ("Shipping_Q2_2026.xlsx", content,
                                        "application/octet-stream")})
        assert up.status_code == 201, up.text
        artifact = up.json()["artifact_id"]
        alpha.post(f"{MESSAGES}/send", json={
            "to": [accounts[1]["id"]], "subject": "Workbook", "body": "x",
            "attachments": [{"type": "file", "artifact_id": artifact}]})
        return {"artifact_id": artifact, "content": content}

    def test_the_recipient_gets_the_exact_bytes(self, beta, shared_file):
        r = beta.get(f"{MESSAGES}/artifacts/{shared_file['artifact_id']}")
        assert r.status_code == 200
        assert r.content == shared_file["content"]

    def test_a_third_person_cannot_download_it(self, gamma, shared_file):
        r = gamma.get(f"{MESSAGES}/artifacts/{shared_file['artifact_id']}")
        assert r.status_code == 404

    def test_guessing_an_id_gets_the_same_refusal(self, gamma, shared_file):
        real = gamma.get(f"{MESSAGES}/artifacts/{shared_file['artifact_id']}")
        absent = gamma.get(f"{MESSAGES}/artifacts/99999999")
        assert real.status_code == absent.status_code == 404

    def test_a_third_person_cannot_attach_it_to_their_own_message(
            self, gamma, shared_file, accounts):
        r = gamma.post(f"{MESSAGES}/send", json={
            "to": [accounts[0]["id"]], "subject": "Borrowed", "body": "x",
            "attachments": [{"type": "file",
                             "artifact_id": shared_file["artifact_id"]}]})
        assert r.status_code == 403

    def test_an_executable_is_refused_at_upload(self, alpha):
        r = alpha.post(f"{MESSAGES}/artifacts",
                       files={"file": ("payload.exe", b"MZ",
                                       "application/octet-stream")})
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_request"


class TestTheSystemSenderCannotBeForged:

    def test_extra_fields_in_the_body_do_not_change_the_sender(
            self, alpha, beta, accounts):
        # The request model has no sender field at all, so this is checking
        # that a hopeful extra key is ignored rather than bound.
        r = alpha.post(f"{MESSAGES}/send", json={
            "to": [accounts[1]["id"]], "subject": "Impersonation", "body": "x",
            "sender_type": "SYSTEM", "sender_user_id": None})
        assert r.status_code == 201
        thread = beta.get(f"{MESSAGES}/threads/{r.json()['thread_id']}").json()
        sender = thread["messages"][0]["sender"]
        assert sender["type"] == "USER"
        assert sender["name"] == "Alpha Case"

    def test_there_is_no_route_that_creates_a_system_message(self):
        # A system message is produced by a governed event, not by a request.
        # An endpoint that could create one would be an endpoint somebody
        # could point at their own inbox.
        from backend.api.routers import messages as router

        paths = {r.path for r in router.router.routes}
        assert not any("system" in p for p in paths)


class TestWhoMayReachTheseRoutesAtAll:

    def test_an_anonymous_caller_is_refused(self):
        from fastapi.testclient import TestClient

        from backend.api.main import app as fastapi_app

        anonymous = TestClient(fastapi_app)
        for path in (f"{MESSAGES}?box=inbox", f"{MESSAGES}/counts",
                     f"{MESSAGES}/shared-with-me"):
            assert anonymous.get(path).status_code == 401

    def test_a_header_cannot_replace_a_session(self, accounts):
        # With REQUIRE_LOGIN on, the demonstration header path is closed. A
        # deployment that could be entered by asserting a role in a header
        # would have no authorization at all.
        from fastapi.testclient import TestClient

        from backend.api.main import app as fastapi_app

        forged = TestClient(fastapi_app)
        r = forged.get(f"{MESSAGES}?box=inbox",
                       headers={"X-IPM-Role": "ADMIN",
                                "X-IPM-User-Id": str(accounts[0]["id"])})
        assert r.status_code == 401

    def test_a_signed_in_person_reads_their_own_counts(self, alpha):
        r = alpha.get(f"{MESSAGES}/counts")
        assert r.status_code == 200
        assert set(r.json()) == {"unread", "action_required", "shared_with_me"}

    def test_creating_a_user_is_still_administrator_only(self, alpha):
        # The messaging feature must not have opened a side door into
        # administration for the ordinary analysts who use it.
        r = alpha.post(f"{API}/users",
                       json={"username": f"t.{uuid.uuid4().hex[:10]}",
                             "password": PASSWORD})
        assert r.status_code == 403


class TestErrorsArriveAsStatusesNotAsFailures:

    def test_an_unknown_mailbox_is_a_400(self, alpha):
        r = alpha.get(f"{MESSAGES}?box=everything")
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "invalid_request"

    def test_an_absent_thread_is_a_404(self, alpha):
        assert alpha.get(f"{MESSAGES}/threads/99999999").status_code == 404

    def test_no_recipients_is_a_400_rather_than_a_500(self, alpha):
        r = alpha.post(f"{MESSAGES}/send",
                       json={"to": [], "subject": "Nobody", "body": "x"})
        assert r.status_code == 400

    def test_an_unknown_recipient_is_a_400(self, alpha):
        r = alpha.post(f"{MESSAGES}/send",
                       json={"to": [99999999], "subject": "Ghost", "body": "x"})
        assert r.status_code == 400

    def test_a_refusal_never_leaks_a_stack_trace(self, gamma, private_thread):
        r = gamma.get(f"{MESSAGES}/threads/{private_thread['thread_id']}")
        body = r.text.lower()
        for leak in ("traceback", "sqlalchemy", ".py", "select "):
            assert leak not in body
