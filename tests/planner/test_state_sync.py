"""The defect UAT reported: a field saved, and a panel that still says it is empty.

Reproduced first, at the level it actually happens: not in the browser, and
not in the completeness engine — which was right about what it was given —
but in the moment between a write and the read that follows it.

`get_db` used to commit in a `yield` dependency's teardown. That teardown
does not run where it reads as though it runs. FastAPI closes the request's
exit stack in `AsyncExitStackMiddleware`, which wraps the call that SENDS the
response, so the commit landed AFTER the browser had been told the save
succeeded. The creation form saves a step and immediately re-reads the draft;
served from before its own write, every panel computed from that read is
wrong in exactly the way that was reported — a sponsor chosen, and a panel
still saying the project has none.

The tests here pin the invariant rather than the mechanism: by the time the
dependency teardown runs, the write must already be visible to a connection
that knows nothing about this request.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Request
from sqlalchemy import select

from tests.planner.conftest import headers

PREFIX = "/api/v1/planner"


def _draft_name(session, key: str) -> str | None:
    """What a connection outside this request can see, right now."""
    from backend.models.planner import PlannerDraft

    return session.execute(
        select(PlannerDraft.name).where(PlannerDraft.key == key)
    ).scalar_one_or_none()


@pytest.fixture
def teardown_watch(client):
    """Replace `get_db` with one that observes instead of committing.

    Identical to production except for the one thing under test: where
    production's teardown used to commit, this looks — from a separate
    session, on a separate connection — for the row the request just wrote,
    and records whether it is there.

    A teardown that has to commit cannot see the write at this point. A
    request that committed before it answered has already made it visible.
    Nothing about timing, threads or luck is involved.
    """
    from backend.api.main import app
    from backend.api.routers import planner as router
    from backend.db.engine import SessionLocal

    seen: list[tuple[str, str | None]] = []
    watching: dict[str, str] = {}

    def observed_db(request: Request):
        session = SessionLocal()
        setattr(request.state, router.SESSION_ON_REQUEST, session)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            key = watching.get("key", "")
            if key:
                outside = SessionLocal()
                try:
                    seen.append((key, _draft_name(outside, key)))
                finally:
                    outside.close()
            setattr(request.state, router.SESSION_ON_REQUEST, None)
            session.close()

    app.dependency_overrides[router.get_db] = observed_db
    try:
        yield watching, seen
    finally:
        app.dependency_overrides.pop(router.get_db, None)


def test_a_saved_field_is_visible_before_the_dependency_teardown(
        client, cast, teardown_watch):
    """§1. The exact failure, at the point it happens."""
    watching, seen = teardown_watch

    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Race reproduction"})
    assert started.status_code == 201, started.text
    key = started.json()["key"]
    watching["key"] = key

    wanted = f"Named {uuid.uuid4().hex[:6]}"
    saved = client.post(
        f"{PREFIX}/copilot/drafts/{key}/apply", headers=headers(cast["alice"]),
        json={"command": "set_overview", "payload": {"name": wanted}})
    assert saved.status_code == 200, saved.text

    assert seen, "the observing dependency never ran"
    key_seen, name_seen = seen[-1]
    assert key_seen == key
    assert name_seen == wanted, (
        "the write was not visible outside the request when its dependency "
        "was torn down — which is after the response has been sent, so the "
        "next read can be served from before this save")


def test_the_write_survives_a_teardown_that_does_not_commit(
        client, cast, teardown_watch):
    """The same thing, said the other way: nothing relies on the teardown."""
    watching, _seen = teardown_watch

    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Survives teardown"})
    key = started.json()["key"]
    watching["key"] = key

    client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                headers=headers(cast["alice"]),
                json={"command": "set_overview",
                      "payload": {"objective": "Prove the commit is real"}})

    from backend.db.engine import get_session

    with get_session() as outside:
        from backend.models.planner import PlannerDraft

        row = outside.execute(
            select(PlannerDraft).where(PlannerDraft.key == key)
        ).scalar_one()
        assert (row.plan or {}).get("overview", {}).get("objective") == \
            "Prove the commit is real"


def test_every_planner_route_commits_inside_the_request(client):
    """A router added without the route class would race again, quietly."""
    from backend.api.main import app
    from backend.api.routers.planner import Durable

    escaped = [
        getattr(route, "path", "")
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/planner")
        and not isinstance(route, Durable)
    ]
    assert escaped == [], (
        "these planner routes commit in dependency teardown, after their "
        f"response has been sent: {escaped}")


# ------------------------------------------------- the symptom, as reported


def test_choosing_a_sponsor_stops_the_panel_saying_there_is_none(client, cast):
    """§3. Write, then read: the read must not contradict the write."""
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Sponsor visibility"})
    key = started.json()["key"]

    client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                headers=headers(cast["alice"]),
                json={"command": "set_governance",
                      "payload": {"sponsor_id": cast["alice"],
                                  "manager_id": cast["alice"],
                                  "escalation_id": cast["alice"],
                                  "start_date": "2026-02-02",
                                  "target_end_date": "2026-09-30"}})

    read = client.get(f"{PREFIX}/copilot/drafts/{key}",
                      headers=headers(cast["alice"]))
    assert read.status_code == 200, read.text
    found = read.json()
    governance = found["plan"]["governance"]
    assert governance["sponsor_id"] == cast["alice"]
    assert governance["start_date"] == "2026-02-02"

    said = " ".join(note["message"].lower()
                    for note in found["completeness"]["blockers"])
    for gone in ("no sponsor", "no project manager", "nobody to escalate",
                 "no start date", "no target completion"):
        assert gone not in said, f"still saying {gone!r} after it was set"


def test_a_write_then_read_pair_never_disagrees_over_many_rounds(client, cast):
    """§16 in miniature: the value written is the value read, every time."""
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Round trip"})
    key = started.json()["key"]

    for round_number in range(12):
        wanted = f"Round {round_number}"
        client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                    headers=headers(cast["alice"]),
                    json={"command": "set_overview",
                          "payload": {"name": wanted}})
        read = client.get(f"{PREFIX}/copilot/drafts/{key}",
                          headers=headers(cast["alice"]))
        assert read.json()["plan"]["overview"]["name"] == wanted, (
            f"round {round_number}: wrote {wanted!r}, read back "
            f"{read.json()['plan']['overview']['name']!r}")
