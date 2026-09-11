"""The agent's recipient lookup, on an installation with eight thousand people.

Escalation is the Planner's one irreversible-feeling act: it puts a named
person's name on a late task and tells somebody else about it. Everything
about that depends on resolving a recipient CORRECTLY, and the failure mode
is silent — a message that reaches the wrong desk or no desk looks exactly
like a message nobody acted on.

So the claims here are about the lookup rather than about the rules:

  * the recipient is resolved BY ID, never by searching for a name — a search
    can be paged, truncated or ambiguous, and an escalation already knows
    whose desk it belongs on;
  * that resolution does not degrade with the size of the directory: the
    escalation contact who sorts 8,001st alphabetically is named correctly;
  * the person-pickers that CHOOSE that contact reach them too, and never
    hand back an email address while doing it;
  * the notification lands on the intended account and nobody else's.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from tests.planner.conftest import headers

PREFIX = "/api/v1/planner"
POPULATION = 8_000


@pytest.fixture(scope="module")
def crowd():
    """Eight thousand colleagues, and one escalation contact behind them all."""
    from sqlalchemy import delete, insert, select

    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    rows = [{
        "username": f"esc-{tag}-{n:05d}", "password_hash": "x",
        "first_name": f"Crowd{n:05d}", "last_name": f"Member{tag}",
        "email": f"esc-{tag}-{n:05d}@example.invalid",
        "role": "ANALYST", "team": f"Crowd {tag}",
        "department": "Credit Risk", "job_title": "Credit Analyst",
        "is_active": True,
    } for n in range(POPULATION)]
    contact = {
        "username": f"z.escalation-{tag}", "password_hash": "x",
        "first_name": "Zeynep", "last_name": f"Yilmaz{tag}",
        "email": f"zeynep-{tag}@example-bank.com",
        "role": "ANALYST", "team": f"Crowd {tag}",
        "department": "Credit Risk", "job_title": "Head of Credit Risk",
        "is_active": True,
    }
    with get_session() as session:
        session.execute(insert(User), [*rows, contact])
        session.commit()
        found = session.execute(select(User.id).where(
            User.username == contact["username"])).scalar_one()
    yield {"tag": tag, "contact_id": int(found), "contact": contact}
    with get_session() as session:
        session.execute(delete(User).where(User.username.like(f"esc-{tag}-%")))
        session.execute(delete(User).where(
            User.username == contact["username"]))
        session.commit()


# --------------------------------------------- choosing the contact, at scale


def test_the_picker_reaches_the_contact_behind_eight_thousand_names(
        client, cast, crowd):
    """The form has to be able to NAME them before the agent can chase them."""
    found = client.get(f"{PREFIX}/copilot/people",
                       params={"search": crowd["contact"]["username"],
                               "limit": 10},
                       headers=headers(cast["alice"]))
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["people"], "an exact username found nobody"
    assert int(body["people"][0]["user_id"]) == crowd["contact_id"]
    assert body["total"] >= 1


def test_the_picker_says_how_many_it_did_not_show(client, cast, crowd):
    """A truncated list that does not say so is how somebody concludes
    a colleague has no account."""
    found = client.get(f"{PREFIX}/copilot/people",
                       params={"search": f"Crowd {crowd['tag']}", "limit": 25},
                       headers=headers(cast["alice"])).json()
    assert found["total"] > len(found["people"])
    assert found["has_more"] is True
    assert found["limit"] == 25


def test_the_picker_pages_to_anybody_in_the_directory(client, cast, crowd):
    """Anybody in the result set is reachable — including the account that
    sorts LAST behind eight thousand others.

    The claim is that the route's `offset` is faithful to the same total
    ordering the service uses: work out where the contact falls in that
    ordering in-process, then ask the HTTP route for exactly that page and
    expect to find them there. If the route ordered rows any other way — or
    ordered them unstably — the contact would not be on that page.
    """
    from backend.db.engine import get_session
    from backend.services import people

    term = f"Crowd {crowd['tag']}"
    with get_session() as session:
        place, seen = None, 0
        while place is None:
            page = people.search(session, query=term, limit=people.MAX_PAGE,
                                 offset=seen, projection=people.CONTACT)
            if not page.people:
                break
            for n, row in enumerate(page.people):
                if int(row["user_id"]) == crowd["contact_id"]:
                    place = seen + n
                    break
            seen += len(page.people)
    assert place is not None, "the contact is not in their own team's results"
    assert place > 500, (
        "this test is only meaningful if the contact is deep in the results; "
        f"they were at {place}")

    found = client.get(f"{PREFIX}/copilot/people",
                       params={"search": term, "limit": 25,
                               "offset": place - 3},
                       headers=headers(cast["alice"]))
    assert found.status_code == 200, found.text
    body = found.json()
    assert [int(p["user_id"]) for p in body["people"]].index(
        crowd["contact_id"]) == 3, (
        "the route's offset does not agree with the service's ordering")
    assert body["offset"] == place - 3
    assert body["total"] >= POPULATION + 1


def test_two_identical_requests_return_the_same_page(client, cast, crowd):
    """Unordered rows are the silent failure: the same offset would hand back
    a different slice each time, so paging would repeat and skip people."""
    term = f"Crowd {crowd['tag']}"
    ask = lambda: client.get(  # noqa: E731
        f"{PREFIX}/copilot/people",
        params={"search": term, "limit": 40, "offset": 4_000},
        headers=headers(cast["alice"])).json()["people"]
    assert [p["user_id"] for p in ask()] == [p["user_id"] for p in ask()]


def test_the_picker_never_hands_back_an_email_address(client, cast, crowd):
    """It turns a name into a user id. It is not a directory scrape."""
    body = client.get(f"{PREFIX}/copilot/people",
                      params={"search": "Crowd", "limit": 50},
                      headers=headers(cast["alice"])).json()
    assert body["people"]
    for row in body["people"]:
        assert set(row) == {"user_id", "username", "name", "role"}


# ------------------------------------------------- the agent naming the owner


def test_the_agent_names_the_owner_correctly_at_eight_thousand(crowd):
    """`monitor._names` resolves by id, so the population cannot reach it."""
    from backend.db.engine import get_session
    from backend.planner import monitor

    with get_session() as session:
        names = monitor._names(session, {crowd["contact_id"]})
    assert names[crowd["contact_id"]] == \
        f"{crowd['contact']['first_name']} {crowd['contact']['last_name']}"


def test_resolving_a_recipient_never_depends_on_a_page(crowd):
    from backend.db.engine import get_session
    from backend.services import people

    with get_session() as session:
        found = people.by_id(session, crowd["contact_id"])
    assert found["username"] == crowd["contact"]["username"]


# ------------------------------------- the whole way through, over the API


def test_an_escalation_reaches_the_contact_and_nobody_else(
        client, cast, crowd):
    """Publish a project whose escalation contact is the 8,001st name, put a
    task past its date, run the agent, and look in that account's inbox."""
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.platform import Notification

    who = cast["alice"]
    today = date.today()
    code = f"ESC-{crowd['tag'][:6].upper()}"
    started = client.post(f"{PREFIX}/copilot/drafts", headers=headers(who),
                          json={"name": f"Escalation {crowd['tag'][:5]}"})
    key = started.json()["key"]

    for command, payload in (
            ("set_overview", {"name": f"Escalation reach {crowd['tag'][:5]}",
                              "code": code, "description": "x",
                              "objective": "y"}),
            # The escalation contact is the account behind eight thousand
            # others. Everything else is the ordinary test cast.
            ("set_governance", {"sponsor_id": who, "manager_id": who,
                                "owner_id": who,
                                "escalation_id": crowd["contact_id"],
                                "start_date": (today - timedelta(days=40)
                                               ).isoformat(),
                                "target_end_date": (today + timedelta(days=60)
                                                    ).isoformat()}),
            ("set_agentic", {"mode": "CRITICAL"}),
            ("add_milestone", {"name": "Only milestone", "owner_id": who,
                               "start_date": (today - timedelta(days=40)
                                              ).isoformat(),
                               "target_date": (today + timedelta(days=30)
                                               ).isoformat()}),
            ("add_task", {"milestone_code": "M01", "title": "Overdue work",
                          "owner_id": who, "description": "Late on purpose.",
                          "start_date": (today - timedelta(days=30)
                                         ).isoformat(),
                          "due_date": (today - timedelta(days=8)
                                       ).isoformat()})):
        done = client.post(f"{PREFIX}/copilot/drafts/{key}/apply",
                           headers=headers(who),
                           json={"command": command, "payload": payload})
        assert done.status_code == 200, done.text

    made = client.post(f"{PREFIX}/copilot/drafts/{key}/publish",
                       headers=headers(who), json={"confirm": True})
    assert made.status_code == 201, made.text
    project_id = made.json()["project_id"]

    ran = client.post(f"{PREFIX}/projects/{project_id}/sweep",
                      headers=headers(who))
    assert ran.status_code == 200, ran.text

    with get_session() as session:
        landed = session.execute(
            select(Notification).where(
                Notification.user_id == crowd["contact_id"],
                Notification.kind == "planner",
                Notification.title.like(f"{code}%"))
            .order_by(Notification.id.desc())).scalars().all()
        assert landed, (
            "the escalation contact behind eight thousand accounts received "
            "nothing")
        # It is about THIS project, and it names the overdue item.
        said = " ".join(f"{n.title} {n.body}" for n in landed)
        assert code in said
        assert "M01-T01" in said
        # Their own name is in it, resolved by id rather than by a search.
        assert crowd["contact"]["first_name"] in said

        # And nobody outside the plan was told about this project.
        strangers = int(session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.kind == "planner",
                Notification.title.like(f"{code}%"),
                Notification.user_id.notin_([crowd["contact_id"], who]),
            )).scalar() or 0)
        assert strangers == 0, (
            f"{strangers} accounts outside the plan were told about {code}")
