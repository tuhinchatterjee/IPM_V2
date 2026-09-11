"""Finding a person on an installation with eight thousand of them.

The defect these pin: the recipient directory returned "the first N rows that
match" and called it an answer. With 8,599 accounts carrying the ANALYST
role, searching that role returned 200 of them, in an order that ended at
`username` — so the account somebody wanted was not there, nothing said so,
and paging past it could repeat a row or skip one.

Four claims, each tested against a population built for the purpose rather
than against whatever the shared database happens to hold:

**Complete.** Every matching account is reachable. The total is the truth,
and walking the pages reaches all of it exactly once.

**Ordered totally.** The ordering ends in the primary key, so no two rows
tie and the same query returns the same sequence every time. That is what
makes a page boundary safe.

**Ranked.** An exact username, email or whole name comes first. What a
sender means by typing `a.rahman` is that account.

**Exact when it has to be.** `by_id` and `resolve` never page, never guess
and never miss — because the agent about to escalate a late task already
knows whose desk it belongs on.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest import database_available

#: Big enough that no page size in the product can hide anybody inside it,
#: and the number the report quotes.
POPULATION = 8_000


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("The directory is a PostgreSQL feature.")


@pytest.fixture(scope="module")
def crowd():
    """Eight thousand colleagues, one of whom is the one we want.

    Inserted in bulk and removed afterwards. They are given a shared team so
    the group filter has something real to count, and sequential names so the
    ordering is checkable by eye when one of these fails.
    """
    from sqlalchemy import delete, insert, select

    from backend.db.engine import get_session
    from backend.db.models import User

    tag = uuid.uuid4().hex[:8]
    team = f"Crowd {tag}"
    rows = [{
        "username": f"crowd-{tag}-{n:05d}",
        "password_hash": "x",
        "first_name": f"Crowd{n:05d}",
        "last_name": f"Member{tag}",
        "email": f"crowd-{tag}-{n:05d}@example.invalid",
        "role": "ANALYST",
        "team": team,
        "department": "Credit Risk",
        "job_title": "Credit Analyst",
        "is_active": True,
    } for n in range(POPULATION)]
    # The one a sender is actually looking for, named like a real colleague
    # and sitting deliberately late in the alphabet so no first page can
    # contain them by accident.
    wanted = {
        "username": f"z.rahman-{tag}",
        "password_hash": "x",
        "first_name": "Zafar",
        "last_name": f"Rahman{tag}",
        "email": f"zafar.rahman-{tag}@example-bank.com",
        "role": "ANALYST",
        "team": team,
        "department": "Credit Risk",
        "job_title": "Head of Model Validation",
        "is_active": True,
    }
    with get_session() as session:
        session.execute(insert(User), [*rows, wanted])
        session.commit()
        found = session.execute(select(User.id).where(
            User.username == wanted["username"])).scalar_one()
    yield {"tag": tag, "team": team, "wanted_id": int(found),
           "wanted": wanted, "size": POPULATION + 1}
    with get_session() as session:
        session.execute(delete(User).where(
            User.username.like(f"crowd-{tag}-%")))
        session.execute(delete(User).where(User.username == wanted["username"]))
        session.commit()


@pytest.fixture
def session():
    from backend.db.engine import get_session

    with get_session() as s:
        yield s


# ------------------------------------------------------------- completeness


def test_the_total_is_the_truth_not_the_page_size(session, crowd):
    from backend.services import people

    page = people.search(session, team=crowd["team"], limit=50)
    assert page.total == crowd["size"], "the count must be of matches, not rows"
    assert len(page.people) == 50
    assert page.has_more is True


def test_walking_the_pages_reaches_everybody_exactly_once(session, crowd):
    """The claim a cap can never make: nobody is unreachable, nobody twice."""
    from backend.services import people

    seen: list[int] = []
    offset = 0
    while True:
        page = people.search(session, team=crowd["team"], limit=500,
                             offset=offset)
        if not page.people:
            break
        seen.extend(int(row["id"]) for row in page.people)
        offset += len(page.people)
        if offset >= page.total:
            break

    assert len(seen) == crowd["size"]
    assert len(set(seen)) == crowd["size"], "a page repeated somebody"
    assert crowd["wanted_id"] in set(seen)


def test_the_account_we_want_is_reachable_by_its_group(session, crowd):
    """8,001 people in one team, and the one you want is still findable."""
    from backend.services import people

    offset, found = 0, False
    while not found:
        page = people.search(session, team=crowd["team"], limit=500,
                             offset=offset)
        if not page.people:
            break
        found = any(int(r["id"]) == crowd["wanted_id"] for r in page.people)
        offset += len(page.people)
    assert found


# --------------------------------------------------------------- ordering


def test_the_same_query_returns_the_same_sequence(session, crowd):
    from backend.services import people

    first = [r["id"] for r in
             people.search(session, team=crowd["team"], limit=200).people]
    second = [r["id"] for r in
              people.search(session, team=crowd["team"], limit=200).people]
    assert first == second


def test_page_boundaries_do_not_overlap_or_drop(session, crowd):
    """The reason the ordering ends in the primary key."""
    from backend.services import people

    whole = [r["id"] for r in
             people.search(session, team=crowd["team"], limit=300).people]
    halves = (
        [r["id"] for r in people.search(session, team=crowd["team"],
                                        limit=150, offset=0).people]
        + [r["id"] for r in people.search(session, team=crowd["team"],
                                          limit=150, offset=150).people])
    assert whole == halves


def test_a_page_past_the_end_is_empty_rather_than_wrong(session, crowd):
    from backend.services import people

    page = people.search(session, team=crowd["team"], limit=50,
                         offset=crowd["size"] + 10)
    assert page.people == []
    assert page.total == crowd["size"]
    assert page.has_more is False


# ---------------------------------------------------------------- ranking


def test_an_exact_username_comes_first(session, crowd):
    from backend.services import people

    page = people.search(session, query=crowd["wanted"]["username"], limit=10)
    assert page.people, "an exact username found nobody"
    assert int(page.people[0]["id"]) == crowd["wanted_id"]


def test_an_exact_email_comes_first(session, crowd):
    from backend.services import people

    page = people.search(session, query=crowd["wanted"]["email"].upper(),
                         limit=10)
    assert int(page.people[0]["id"]) == crowd["wanted_id"]


def test_a_whole_name_comes_first(session, crowd):
    """"Zafar Rahman<tag>" — two columns, and no single one holds it."""
    from backend.services import people

    whole = f"{crowd['wanted']['first_name']} {crowd['wanted']['last_name']}"
    page = people.search(session, query=whole, limit=10)
    assert int(page.people[0]["id"]) == crowd["wanted_id"]


def test_a_name_prefix_beats_eight_thousand_job_titles(session, crowd):
    """Typing three letters of a surname must not be buried by a job title.

    Every one of the eight thousand is a "Credit Analyst", and the ranking
    has to put somebody whose NAME starts with what was typed above people
    whose job description merely contains it.
    """
    from backend.services import people

    page = people.search(session, query="zafar", limit=10)
    assert int(page.people[0]["id"]) == crowd["wanted_id"]


def test_a_role_search_ranks_last_because_it_cannot_rank(session, crowd):
    """Nothing makes one of eight thousand analysts more relevant.

    Which is exactly why a role is a FILTER with a total and pages, and the
    search box says so by putting attribute-only matches behind every
    identity match.
    """
    from backend.services import people

    page = people.search(session, query="ANALYST", limit=5)
    assert page.total >= crowd["size"]
    assert page.has_more is True


# ------------------------------------------------------------ exact lookup


def test_by_id_finds_the_account_whatever_the_population(session, crowd):
    from backend.services import people

    found = people.by_id(session, crowd["wanted_id"])
    assert int(found["id"]) == crowd["wanted_id"]
    assert found["username"] == crowd["wanted"]["username"]


def test_by_ids_returns_all_of_them_with_no_cap(session, crowd):
    """A thousand recipients asked for is a thousand recipients returned."""
    from sqlalchemy import select

    from backend.db.models import User
    from backend.services import people

    ids = [int(i) for i in session.execute(
        select(User.id).where(User.username.like(f"crowd-{crowd['tag']}-%"))
        .limit(1000)).scalars()]
    assert len(ids) == 1000
    found = people.by_ids(session, ids)
    assert set(found) == set(ids)


def test_resolve_takes_an_id_a_username_or_an_email(session, crowd):
    from backend.services import people

    for handle in (crowd["wanted_id"], str(crowd["wanted_id"]),
                   crowd["wanted"]["username"], crowd["wanted"]["email"]):
        assert int(people.resolve(session, handle)["id"]) == crowd["wanted_id"]


def test_resolve_refuses_to_guess(session, crowd):
    """A partial match is not an answer when the answer is a recipient."""
    from backend.services import people

    assert people.resolve(session, "zafar") == {}
    assert people.resolve(session, crowd["wanted"]["username"][:-3]) == {}
    assert people.resolve(session, "") == {}


# ------------------------------------------------------------- permissions


def test_the_planner_projection_never_carries_an_email(session, crowd):
    """The person-pickers turn a name into an id. That is all they may do."""
    from backend.services import people

    page = people.search(session, query="Zafar", limit=5,
                         projection=people.CONTACT)
    assert page.people
    for row in page.people:
        assert "email" not in row
        assert "department" not in row
        assert "job_title" not in row
    assert "email" not in people.by_id(session, crowd["wanted_id"],
                                       projection=people.CONTACT)


def test_a_suspended_account_is_not_offered_as_a_recipient(session, crowd):
    from sqlalchemy import select

    from backend.db.models import User
    from backend.services import people

    row = session.execute(select(User).where(
        User.id == crowd["wanted_id"])).scalars().one()
    row.is_active = False
    session.flush()
    try:
        page = people.search(session, query=crowd["wanted"]["username"])
        assert page.people == []
        assert page.total == 0
        # ...but a message already addressed to them still resolves, because
        # a suspended recipient is a fact the caller has to be able to see.
        assert people.by_id(session, crowd["wanted_id"])["is_active"] is False
        assert people.search(session, query=crowd["wanted"]["username"],
                             include_inactive=True).total == 1
    finally:
        row.is_active = True
        session.flush()


def test_nothing_ever_returns_a_password_hash(session, crowd):
    from backend.services import people

    row = people.search(session, query="Zafar", limit=1).people[0]
    assert "password_hash" not in row
    assert not any("password" in key for key in row)
