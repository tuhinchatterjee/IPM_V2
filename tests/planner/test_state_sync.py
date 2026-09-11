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


# --------------------------------- §16: the value written is the value read


#: (command, payload, where it lands in the plan, the completeness sentence
#: that must disappear once it is set)
FIELDS = [
    ("set_overview", {"name": "LGD Model Redevelopment"},
     ("overview", "name"), "The project has no name."),
    ("set_overview", {"code": "LGDMR-UAT"},
     ("overview", "code"), "The project has no code."),
    ("set_governance", {"sponsor_id": "@alice"},
     ("governance", "sponsor_id"), "The project has no sponsor."),
    ("set_governance", {"manager_id": "@alice"},
     ("governance", "manager_id"), "The project has no manager."),
    ("set_governance", {"escalation_id": "@alice"},
     ("governance", "escalation_id"), "There is nobody to escalate to."),
    ("set_governance", {"start_date": "2026-02-02"},
     ("governance", "start_date"), "The project has no start date."),
    ("set_governance", {"target_end_date": "2026-09-30"},
     ("governance", "target_end_date"),
     "The project has no target completion date."),
]


def test_after_every_field_the_draft_and_the_completeness_agree(client, cast):
    """The exact UAT sequence, one field at a time.

    After each save: what the API says the plan holds, what the completeness
    engine says about it, and what the progress panel counts must be three
    views of one document. This test fails if any two of them drift apart.
    """
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Field by field"})
    key = started.json()["key"]
    gone: list[str] = []

    for command, payload, (section, _field), sentence in FIELDS:
        sent = {k: (cast["alice"] if v == "@alice" else v)
                for k, v in payload.items()}
        saved = client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                            headers=headers(cast["alice"]),
                            json={"command": command, "payload": sent})
        assert saved.status_code == 200, saved.text

        read = client.get(f"{PREFIX}/copilot/drafts/{key}",
                          headers=headers(cast["alice"]))
        found = read.json()
        for name, value in sent.items():
            assert found["plan"][section][name] == value, (
                f"{command}.{name}: wrote {value!r}, the draft holds "
                f"{found['plan'][section][name]!r}")

        gone.append(sentence)
        said = [note["message"] for note in found["completeness"]["blockers"]]
        for stale in gone:
            assert stale not in said, (
                f"{stale!r} is still on screen after the field was set")

        # And the progress panel counts the same document.
        counted = found["progress"]
        assert counted["required_remaining"] == \
            len(found["completeness"]["blockers"])
        assert counted["sentence"].endswith("sections complete")


def test_the_read_carries_progress_and_guidance_for_the_same_plan(
        client, cast):
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Guided"})
    key = started.json()["key"]
    found = client.get(f"{PREFIX}/copilot/drafts/{key}",
                       headers=headers(cast["alice"])).json()

    assert len(found["progress"]["sections"]) == 8
    # The draft was started with a name, so the name and its derived code
    # are already in place and the first thing still wanted is the sponsor.
    assert found["guidance"]["next"]["field"] == "governance.sponsor_id"
    assert found["guidance"]["readiness"]["message"].startswith(
        "Publish unavailable —")
    assert [row["key"] for row in found["agentic_settings"]]


def test_a_field_the_draft_does_not_have_is_refused_not_dropped(client, cast):
    """§3. A payload key nobody reads is UI and draft disagreeing, silently."""
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Strays"})
    key = started.json()["key"]
    refused = client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                          headers=headers(cast["alice"]),
                          json={"command": "set_governance",
                                "payload": {"escalation_contact_id": 1}})
    assert refused.status_code == 422, refused.text
    assert "escalation_contact_id" in refused.json()["detail"]["message"]


# ------------------------------------- two ways a field and the draft parted


def test_a_code_that_is_cleared_is_cleared(client, cast):
    """It used to be impossible to empty: the box went blank, the draft did not.

    `if data.get("code")` cannot tell "no opinion" from "I deleted this", so
    a cleared code fell through to the branch that keeps what is there. The
    field then showed one thing and the plan held another until a reload put
    the old value back without saying so.
    """
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Clearable"})
    key = started.json()["key"]
    first = client.get(f"{PREFIX}/copilot/drafts/{key}",
                       headers=headers(cast["alice"])).json()
    assert first["plan"]["overview"]["code"], "a code was suggested"

    client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                headers=headers(cast["alice"]),
                json={"command": "set_overview", "payload": {"code": ""}})
    after = client.get(f"{PREFIX}/copilot/drafts/{key}",
                       headers=headers(cast["alice"])).json()
    assert after["plan"]["overview"]["code"] == ""
    assert "The project has no code." in [
        note["message"] for note in after["completeness"]["blockers"]]


def test_naming_a_project_still_suggests_a_code(client, cast):
    """Clearing is deliberate; not mentioning the code is not."""
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]), json={"name": ""})
    key = started.json()["key"]
    client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                headers=headers(cast["alice"]),
                json={"command": "set_overview",
                      "payload": {"name": "Loss Given Default Rebuild"}})
    found = client.get(f"{PREFIX}/copilot/drafts/{key}",
                       headers=headers(cast["alice"])).json()
    assert found["plan"]["overview"]["code"].startswith("LGDR-")


def test_setting_a_field_does_not_move_the_step_you_are_on(client, cast):
    """Choosing a policy recorded you on the milestones, a step further on.

    Every command returned the step it thought came next and `apply` wrote
    that down, so the draft's idea of where you were ran ahead of you and
    reopening the plan opened it past the step you were working on. Only
    `set_step` means "I have moved".
    """
    started = client.post(f"{PREFIX}/copilot/drafts",
                          headers=headers(cast["alice"]),
                          json={"name": "Staying put"})
    key = started.json()["key"]
    client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                headers=headers(cast["alice"]),
                json={"command": "set_step", "payload": {"step": "AGENTIC"}})
    client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                headers=headers(cast["alice"]),
                json={"command": "set_agentic", "payload": {"mode": "LIGHT"}})

    found = client.get(f"{PREFIX}/copilot/drafts/{key}",
                       headers=headers(cast["alice"])).json()
    assert found["step"] == "AGENTIC"
    assert found["plan"]["agentic"]["mode"] == "LIGHT"
