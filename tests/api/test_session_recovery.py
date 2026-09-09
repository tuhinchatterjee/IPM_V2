"""A session must not silently die on a routine local restart.

UAT hit this precisely: signed in, the top navigation said so, and the very
next Lens save answered "Sign in to use CreditProbe." Nobody's session had
actually expired in the way that message implies — the backend process had
simply restarted (a `--reload`, a fix being applied, exactly what "real local
UAT" looks like) with no `SECRET_KEY` configured, which invalidates every
signature in flight. The cookie was still in the browser; the fact that it
now meant nothing was not.

This module tests the piece of that fix that lives entirely in one function:
`ENV=dev` sessions are signed with a key persisted next to the logs, so a
local restart does not invalidate them, while every other environment keeps
the original behaviour — a restart there still invalidates a signature, on
purpose, because trusting a written-down key in a real deployment is the
wrong trade in the other direction.

What this module does NOT claim to test: the browser-side recovery when a
session genuinely has expired (a different machine, a real 8-hour timeout,
`ENV` not `dev`). That is `scripts/acceptance/lens_auth_journeys.py`, which
drives a real browser through the actual sign-in screen.
"""

from __future__ import annotations

from dataclasses import replace

import pytest


@pytest.fixture()
def auth_module(tmp_path, monkeypatch):
    """`backend.api.auth`, reset to a clean, isolated key cache each test."""
    import backend.api.auth as auth
    from backend.config import settings

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(auth, "settings", replace(settings, env="dev", secret_key="",
                                                   log_dir=log_dir))
    monkeypatch.setattr(auth, "_DEV_KEY", None)
    monkeypatch.setattr(auth, "_PROCESS_KEY", None)
    return auth


def _restart(auth_module, monkeypatch) -> None:
    """Simulate a fresh backend process: the module-level key caches are gone,
    but whatever was written to disk is not."""
    monkeypatch.setattr(auth_module, "_DEV_KEY", None)
    monkeypatch.setattr(auth_module, "_PROCESS_KEY", None)


def test_a_dev_session_survives_a_restart(auth_module, monkeypatch):
    token = auth_module._sign({"user_id": 9, "issued": __import__("time").time()})

    _restart(auth_module, monkeypatch)

    assert auth_module._unsign(token) is not None, (
        "a session signed before a local restart must still verify after one"
    )


def test_the_key_is_actually_written_to_disk(auth_module):
    auth_module._sign({"user_id": 9, "issued": 0})
    written = auth_module.settings.log_dir / ".dev_session_secret"
    assert written.exists(), (
        "restart durability comes from a real file, not an in-memory "
        "assumption that happens to hold for one test process"
    )
    assert len(written.read_text(encoding="utf-8").strip()) >= 32


def test_a_second_process_reads_the_same_key(auth_module, monkeypatch):
    """Two workers behind the same load balancer must agree on one signature,
    not each mint their own and reject each other's cookies."""
    token = auth_module._sign({"user_id": 9, "issued": __import__("time").time()})

    # A second process never shares the first one's module-level cache at all,
    # which the restart helper models faithfully.
    _restart(auth_module, monkeypatch)

    assert auth_module._unsign(token) is not None


def test_outside_dev_a_restart_still_invalidates_the_session(auth_module, monkeypatch):
    """The narrow exception is `ENV=dev` only. Staging and production keep the
    original, deliberately unforgiving behaviour: an unconfigured secret means
    a restart is visible, not silently trusted away."""
    from dataclasses import replace as _replace

    monkeypatch.setattr(auth_module, "settings",
                        _replace(auth_module.settings, env="staging"))
    token = auth_module._sign({"user_id": 9, "issued": __import__("time").time()})

    _restart(auth_module, monkeypatch)

    assert auth_module._unsign(token) is None, (
        "ENV=staging (or prod) must not gain restart durability from an "
        "unconfigured secret -- that would be a real security regression"
    )


def test_a_configured_secret_key_always_wins_over_the_dev_file(auth_module, monkeypatch):
    from dataclasses import replace as _replace

    monkeypatch.setattr(auth_module, "settings",
                        _replace(auth_module.settings, secret_key="a-real-configured-secret"))
    token = auth_module._sign({"user_id": 9, "issued": __import__("time").time()})

    assert not (auth_module.settings.log_dir / ".dev_session_secret").exists(), (
        "a configured SECRET_KEY must never fall through to writing a dev file"
    )
    assert auth_module._unsign(token) is not None


def test_a_missing_or_unreadable_dev_key_file_degrades_to_a_fresh_key_not_a_crash(
    auth_module,
):
    """A read-only local disk should cost open sessions, not the ability to
    sign in at all."""
    written = auth_module.settings.log_dir / ".dev_session_secret"
    written.mkdir()  # a directory where a file is expected: read_text() will fail

    token = auth_module._sign({"user_id": 9, "issued": __import__("time").time()})
    assert auth_module._unsign(token) is not None


# ------------------------------------------------- the contract the UI relies on


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def test_an_expired_session_answers_with_the_exact_code_the_frontend_matches_on(
    client, monkeypatch,
):
    """`frontend/src/lib/api.ts` flips the whole app back to the sign-in screen
    on exactly `status == 401 and code == "not_signed_in"`. If this code or
    status ever drifts, that recovery silently stops firing and the original
    UAT defect is back -- so the contract is pinned here, not only implied by
    the permissions module's own docstring."""
    import backend.api.permissions as permissions
    from backend.config import settings

    monkeypatch.setattr(permissions, "settings", replace(settings, require_login=True))

    response = client.post(
        "/api/v1/lenses/1/ask", json={"request": "add coverage", "apply": True},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "not_signed_in"
