"""Finding a person, completely and in the same order every time.

One search, used by the messaging directory and by the Project Planner, and
written for the size a real installation reaches rather than the size a demo
does.

Three things were wrong with the searches this replaces, and all three are
the same mistake in different places: they treated "the first N rows that
match" as an answer.

**They were not complete.** A term that matches thousands of accounts — a
role, a team, a common surname — returned an arbitrary slice with no count
and no way to ask for the rest. On this installation, searching the ANALYST
role matched 7,919 accounts and returned 200 of them; the account you wanted
was simply not among them, and nothing on the screen said so. A cap is a
legitimate page size. It is not a legitimate answer, and the difference is
whether the caller is told what it did not get.

**They were not ranked.** Every match was equal, so a person typing an exact
username got it somewhere in an alphabetical list of everybody whose job
title happened to contain the same letters. What a sender means by typing
`a.rahman` is *that account*, and a directory that cannot say so is asking
them to scroll for something it already knows.

**They were not deterministic.** Ordering by first name alone leaves every
account sharing a first name in whatever order the database returns, which
is stable until it is not — and a page-two that overlaps page-one is a
directory that can hide somebody entirely. The ordering here is total: it
ends in the primary key, so no two rows ever tie.

The ranking, most relevant first:

    0  the term IS the username, the email, or the whole name
    1  the term starts one of those
    2  the term starts a word inside the name
    3  the term appears inside an identity field — name, username, email,
       job title
    4  the term only appears in an attribute — role, team, department

Tier 4 is deliberately last, and it is the tier a role search lands in.
Nothing can make one of seven thousand analysts more relevant than another,
which is why a role belongs to `role=` — a filter, with a total and pages —
rather than to the search box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import case, func, or_, select

#: What the messaging directory shows: enough to tell two colleagues apart.
DIRECTORY = "directory"
#: What the Planner shows. No email address: the person-pickers on the
#: creation form turn a name into a user id, and a picker that also handed
#: back everybody's address would be a directory scrape wearing a form.
CONTACT = "contact"

#: The largest page anything may ask for. Not a limit on what is reachable —
#: `offset` reaches all of it — but on what one round trip carries.
MAX_PAGE = 500


@dataclass
class Page:
    """One page of people, and the truth about the rest of them."""

    people: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.people) < self.total

    def to_dict(self) -> dict[str, Any]:
        return {"people": self.people, "total": self.total,
                "limit": self.limit, "offset": self.offset,
                "has_more": self.has_more}


def person(row: Any, *, projection: str = DIRECTORY) -> dict[str, Any]:
    """One account, in the shape the asking surface is allowed to see."""
    if row is None:
        return {}
    full = f"{getattr(row, 'first_name', '')} " \
           f"{getattr(row, 'last_name', '')}".strip()
    if projection == CONTACT:
        # Four fields, and no more. A picker turns a name into a user id;
        # anything else it carried would be a directory scrape wearing a
        # form, and `is_active` would be a second, quieter way of saying
        # who has left.
        return {
            "user_id": int(row.id),
            "name": full or row.username,
            "username": row.username,
            "role": getattr(row, "role", "") or "",
        }
    shown = {
        "id": int(row.id),
        "user_id": int(row.id),
        "username": row.username,
        "name": full or row.username,
        "role": getattr(row, "role", "") or "",
        "is_active": bool(getattr(row, "is_active", True)),
    }
    shown.update({
        "email": getattr(row, "email", "") or "",
        "job_title": getattr(row, "job_title", "") or "",
        "department": getattr(row, "department", "") or "",
        "team": getattr(row, "team", "") or "",
    })
    return shown


def _full_name(User: Any) -> Any:
    return func.lower(func.trim(
        func.coalesce(User.first_name, "") + " "
        + func.coalesce(User.last_name, "")))


def _identity(User: Any, like: str) -> Any:
    """Fields that name a person rather than describe their job."""
    return or_(
        _full_name(User).like(like),
        func.lower(func.coalesce(User.first_name, "")).like(like),
        func.lower(func.coalesce(User.last_name, "")).like(like),
        func.lower(func.coalesce(User.username, "")).like(like),
        func.lower(func.coalesce(User.email, "")).like(like),
        func.lower(func.coalesce(User.job_title, "")).like(like),
    )


def _attribute(User: Any, like: str) -> Any:
    """Fields that describe a group rather than name a person."""
    return or_(
        func.lower(func.coalesce(User.role, "")).like(like),
        func.lower(func.coalesce(User.team, "")).like(like),
        func.lower(func.coalesce(User.department, "")).like(like),
    )


def _rank(User: Any, text: str) -> Any:
    """How well this row answers "find me this person". Lower is better."""
    exact = text
    starts = f"{text}%"
    inside = f"%{text}%"
    word = f"% {text}%"
    return case(
        (or_(func.lower(User.username) == exact,
             func.lower(func.coalesce(User.email, "")) == exact,
             _full_name(User) == exact), 0),
        (or_(func.lower(User.username).like(starts),
             func.lower(func.coalesce(User.email, "")).like(starts),
             _full_name(User).like(starts),
             func.lower(func.coalesce(User.first_name, "")).like(starts),
             func.lower(func.coalesce(User.last_name, "")).like(starts)), 1),
        (_full_name(User).like(word), 2),
        (_identity(User, inside), 3),
        else_=4)


def _ordering(User: Any, text: str) -> list[Any]:
    """A TOTAL order: every tiebreak, ending in the primary key.

    Ending in the id is the part that matters. Two colleagues who share a
    first name, a last name and a blank profile are otherwise interchangeable
    to the database, which may return them in either order — and a page two
    that repeats a row from page one is a directory in which somebody is
    unreachable without anybody being able to say who.
    """
    named = case((or_(func.coalesce(User.first_name, "") != "",
                      func.coalesce(User.last_name, "") != ""), 0), else_=1)
    reachable = case((func.coalesce(User.email, "") != "", 0), else_=1)
    order: list[Any] = []
    if text:
        order.append(_rank(User, text))
    order.extend([named, reachable,
                  func.lower(func.coalesce(User.first_name, "")),
                  func.lower(func.coalesce(User.last_name, "")),
                  func.lower(User.username), User.id])
    return order


def search(session: Any, *, query: str = "", role: str = "", team: str = "",
           department: str = "", include_inactive: bool = False,
           limit: int = 50, offset: int = 0,
           projection: str = DIRECTORY) -> Page:
    """One page of the people who match, ranked, with the total.

    `query` searches for a PERSON. `role`, `team` and `department` filter a
    GROUP, exactly and server-side. Keeping them apart is what makes both
    answerable: a name can be ranked, and a group can only be counted and
    paged.
    """
    from backend.db.models import User

    where = []
    if not include_inactive:
        where.append(User.is_active.is_(True))
    for column, wanted in ((User.role, role), (User.team, team),
                           (User.department, department)):
        value = str(wanted or "").strip()
        if value:
            where.append(func.lower(func.coalesce(column, ""))
                         == value.lower())
    text = str(query or "").strip().lower()
    if text:
        like = f"%{text}%"
        where.append(or_(_identity(User, like), _attribute(User, like)))

    total = int(session.execute(
        select(func.count()).select_from(User).where(*where)).scalar() or 0)

    size = max(1, min(int(limit or 50), MAX_PAGE))
    start = max(0, int(offset or 0))
    rows = session.execute(
        select(User).where(*where)
        .order_by(*_ordering(User, text))
        .limit(size).offset(start)
    ).scalars().all()
    return Page(people=[person(r, projection=projection) for r in rows],
                total=total, limit=size, offset=start)


def by_id(session: Any, user_id: Any, *,
          projection: str = DIRECTORY) -> dict[str, Any]:
    """One account by its id. Never a page, never a search, never a miss.

    This is the path anything that already KNOWS who it means must take —
    the agent about to tell an escalation contact that a task is late, for
    one. Resolving a known recipient by searching for their name is how a
    message ends up at the wrong desk, or at no desk, on an installation
    with enough people to make two of them share a name.
    """
    from backend.db.models import User

    if user_id in (None, ""):
        return {}
    try:
        wanted = int(user_id)
    except (TypeError, ValueError):
        return {}
    return person(session.get(User, wanted), projection=projection)


def by_ids(session: Any, user_ids: Any, *,
           projection: str = DIRECTORY) -> dict[int, dict[str, Any]]:
    """Several accounts by id, in one query, complete.

    No limit: the caller named exactly who it wants, and a lookup that
    silently returned some of them would be the same defect as a truncated
    search wearing different clothes.
    """
    from backend.db.models import User

    wanted: set[int] = set()
    for value in user_ids or ():
        try:
            wanted.add(int(value))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return {}
    rows = session.execute(
        select(User).where(User.id.in_(wanted))).scalars().all()
    return {int(r.id): person(r, projection=projection) for r in rows}


def resolve(session: Any, identifier: Any, *,
            projection: str = DIRECTORY) -> dict[str, Any]:
    """One account by id, username or email address — exactly, or nothing.

    Deliberately refuses to guess. A partial match that returned "the most
    likely person" would be a function that addresses mail to somebody
    nobody named.
    """
    from backend.db.models import User

    text = str(identifier or "").strip()
    if not text:
        return {}
    if text.isdigit():
        return by_id(session, int(text), projection=projection)
    row = session.execute(
        select(User).where(or_(
            func.lower(User.username) == text.lower(),
            func.lower(func.coalesce(User.email, "")) == text.lower()))
        .order_by(User.id)
    ).scalars().first()
    return person(row, projection=projection)


__all__ = ["CONTACT", "DIRECTORY", "MAX_PAGE", "Page", "by_id", "by_ids",
           "person", "resolve", "search"]
