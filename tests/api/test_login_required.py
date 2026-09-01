"""
Signing in is compulsory by default.

The rest of the suite runs with REQUIRE_LOGIN off, because it acts as a
particular role by sending X-IPM-Role — which is the documented mechanism for a
deployment that has deliberately switched signing in off. That leaves the
product's actual default untested, and an untested security default is not one.

So this module sets it explicitly and asserts the two things that matter: an
unauthenticated request is refused, and a header cannot be used to get past the
refusal. The second is the one an attacker would try.

The gate lives in `current_principal`, which every endpoint touching portfolio
data or changing anything depends on. Endpoints that expose neither — the health
check, the list of registered analyses, and `auth/me` itself — stay open on
purpose: `auth/me` has to answer or nothing can render the login form, and the
other two describe the software rather than the book.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.conftest import database_available


@pytest.fixture()
def locked_down(monkeypatch):
    """A backend that insists on a session, for the length of one test."""
    import backend.api.permissions as permissions
    from backend.config import settings

    monkeypatch.setattr(permissions, "settings", replace(settings, require_login=True))
    return True


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def test_the_shipped_default_is_that_a_session_is_required():
    """Read from the module, not from the environment the suite overrode."""
    import inspect

    from backend import config

    source = inspect.getsource(config)
    assert '_get("REQUIRE_LOGIN", "true")' in source, (
        "the shipped default must be that signing in is required"
    )


#: An endpoint that reads governed portfolio data, so it carries a principal.
GOVERNED = "/api/v1/data-builder/datasets/portfolio_facility/rows"


def test_an_unauthenticated_request_is_refused(client, locked_down):
    response = client.get(GOVERNED)
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "not_signed_in"


def test_a_role_header_cannot_be_used_instead_of_signing_in(client, locked_down):
    """The header path is closed entirely, not merely downgraded."""
    for role in ("ADMIN", "DATA_STEWARD", "ANALYST", "VIEWER"):
        response = client.get(GOVERNED, headers={"X-IPM-Role": role})
        assert response.status_code == 401, f"{role} header got past the login gate"


def test_a_user_id_header_cannot_be_used_either(client, locked_down):
    response = client.get(
        GOVERNED, headers={"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"},
    )
    assert response.status_code == 401


def test_asking_a_question_is_refused_without_a_session(client, locked_down):
    response = client.post(
        "/api/v1/ask", json={"question": "What is our current NPL ratio?"},
        headers={"X-IPM-Role": "ANALYST"},
    )
    assert response.status_code == 401


def test_governed_rows_are_refused_without_a_session(client, locked_down):
    response = client.get(
        "/api/v1/data-builder/datasets/portfolio_facility/rows",
        headers={"X-IPM-Role": "DATA_STEWARD"},
    )
    assert response.status_code == 401


def test_who_am_i_still_answers_so_the_login_page_can_be_shown(client, locked_down):
    """This one endpoint must stay open, or nothing can render the login form."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["user"] is None


def test_the_interface_is_told_whether_a_session_is_required(client):
    """So the login gate cannot disagree with the thing enforcing it."""
    body = client.get("/api/v1/auth/me").json()
    assert "login_required" in body
    assert isinstance(body["login_required"], bool)


@pytest.mark.skipif(not database_available(), reason="Signing in needs PostgreSQL")
def test_signing_in_gets_past_the_gate(client, locked_down):
    """The gate has to let the right person through, or it is just a wall."""
    from sqlalchemy import select

    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    username = "gatecheck.steward"
    password = "gate-check-password"
    with get_session() as session:
        existing = session.execute(
            select(User).where(User.username == username)).scalar_one_or_none()
        if existing is None:
            session.add(User(username=username, password_hash=hash_password(password),
                             role="DATA_STEWARD", first_name="Gate",
                             last_name="Check", is_active=True))
        else:
            existing.password_hash = hash_password(password)
            existing.is_active = True
        session.commit()

    signed_in = client.post("/api/v1/auth/login",
                            json={"username": username, "password": password})
    assert signed_in.status_code == 200, signed_in.text

    allowed = client.get(GOVERNED, params={"limit": 1})
    assert allowed.status_code == 200, "a signed-in Data Steward was refused"
