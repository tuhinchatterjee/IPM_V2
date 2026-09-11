"""Finding a person, over real HTTP, on a directory of eight thousand.

The unit and API tests prove the search itself. This proves the SHIPPED
product: a live server, a real session cookie, the routes as the browser
calls them, and the escalation contact reading their own inbox.

What it checks, in order:

  1. an exact username finds the intended account first, out of 8,000;
  2. the directory page says how many it did not show;
  3. `offset` reaches the account that sorts LAST, and the page it is on is
     the page the service says it is on;
  4. two identical requests return the same slice — unordered rows would
     silently repeat and skip people;
  5. the Planner's person-picker never hands back an email address;
  6. a project whose escalation contact is that 8,001st account escalates an
     overdue task to THEM, they can see it in their own notifications, and
     nobody outside the plan was told.

It creates its own accounts and deletes them again, whatever happens.

    python scripts/acceptance/directory_lookup.py --api http://localhost:8099
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, timedelta
from typing import Any

API = "http://localhost:8000"
POPULATION = 8_000
PASSWORD = "Directory-Proof-1"
#: Who drives the product. An existing account rather than one of the eight
#: thousand: the crowd this proof creates must stay inert so that it can be
#: removed again, and anybody who publishes a project leaves audit behind.
DRIVER = "alex.rahman"


class Report:
    """What was checked, and what it actually said."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.error = ""

    def check(self, name: str, ok: bool, said: str = "") -> bool:
        self.steps.append({"step": name, "ok": bool(ok), "said": said})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}"
              + (f"\n        {said}" if said else ""))
        return bool(ok)

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [s for s in self.steps if not s["ok"]]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": self.steps, "error": self.error,
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures)}


def _crowd(tag: str) -> tuple[int, int]:
    """Eight thousand colleagues and one escalation contact behind them."""
    from sqlalchemy import insert, select

    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    secret = hash_password(PASSWORD)
    rows = [{
        "username": f"proof-{tag}-{n:05d}", "password_hash": secret,
        "first_name": f"Crowd{n:05d}", "last_name": f"Member{tag}",
        "email": f"proof-{tag}-{n:05d}@example.invalid",
        "role": "ANALYST", "team": f"Proof {tag}",
        "department": "Credit Risk", "job_title": "Credit Analyst",
        "is_active": True,
    } for n in range(POPULATION)]
    contact = {
        "username": f"z.proof-{tag}", "password_hash": secret,
        "first_name": "Zeynep", "last_name": f"Yilmaz{tag}",
        "email": f"zeynep-{tag}@example-bank.com",
        "role": "MANAGER", "team": f"Proof {tag}",
        "department": "Credit Risk", "job_title": "Head of Credit Risk",
        "is_active": True,
    }
    with get_session() as session:
        session.execute(insert(User), [*rows, contact])
        session.commit()
        ids = session.execute(
            select(User.id).where(User.username.in_(
                [contact["username"], f"proof-{tag}-00000"]))
            .order_by(User.id)).scalars().all()
        who = session.execute(select(User.id).where(
            User.username == contact["username"])).scalar_one()
    return int(who), len(ids)


def _remove(tag: str) -> None:
    """Take the crowd away again, including what signing in left behind."""
    from sqlalchemy import delete, select, text

    from backend.db.engine import get_session
    from backend.db.models import User

    mine = (User.username.like(f"proof-{tag}-%")
            if tag else User.username.like("proof-%"))
    with get_session() as session:
        ids = [int(row) for row in session.execute(
            select(User.id).where(mine)).scalars()]
        ids += [int(row) for row in session.execute(select(User.id).where(
            User.username == f"z.proof-{tag}")).scalars()]
        if not ids:
            return
        # The contact signs in to read their own inbox, and signing in is
        # itself an audited act. Those rows are this proof's, and they are
        # what stands between it and putting the directory back as it was.
        session.execute(
            text("DELETE FROM collaboration_audit WHERE actor_id = ANY(:ids)"),
            {"ids": ids})
        session.execute(delete(User).where(User.id.in_(ids)))
        session.commit()


def _signed_in(api: str, username: str, *, demo: bool = False) -> Any:
    import requests

    from backend.services.demo_users import DEMO_PASSWORD

    client = requests.Session()
    out = client.post(f"{api}/api/v1/auth/login", timeout=30,
                      json={"username": username,
                            "password": DEMO_PASSWORD if demo else PASSWORD})
    out.raise_for_status()
    return client


def _place(tag: str, contact_id: int) -> int:
    """Where the contact falls in the service's own total order."""
    from backend.db.engine import get_session
    from backend.services import people

    term = f"Proof {tag}"
    with get_session() as session:
        seen = 0
        while True:
            page = people.search(session, query=term, limit=people.MAX_PAGE,
                                 offset=seen, projection=people.CONTACT)
            if not page.people:
                return -1
            for n, row in enumerate(page.people):
                if int(row["user_id"]) == contact_id:
                    return seen + n
            seen += len(page.people)


def run(api: str, report: Report) -> Report:
    tag = uuid.uuid4().hex[:8]
    contact_id = 0
    # Anything an interrupted earlier run left behind. This script owns the
    # `proof-` prefix and nothing else does.
    _remove("")
    try:
        print(f"Creating {POPULATION:,} accounts and one contact "
              f"(tag {tag})…")
        contact_id, _ = _crowd(tag)
        term = f"Proof {tag}"

        who = _signed_in(api, DRIVER, demo=True)
        # ---------------------------------------------- the messaging directory
        found = who.get(f"{api}/api/v1/messages/directory", timeout=60,
                        params={"q": f"z.proof-{tag}", "limit": 5}).json()
        report.check(
            "an exact username finds the intended account, first",
            bool(found["users"]) and int(found["users"][0]["id"]) == contact_id,
            f"total={found.get('total')} "
            f"first={found['users'][0]['username'] if found['users'] else None}")

        page = who.get(f"{api}/api/v1/messages/directory", timeout=60,
                       params={"q": term, "limit": 25}).json()
        report.check(
            "the directory says how many it did not show",
            page["total"] > len(page["users"]) and page["has_more"] is True,
            f"showed {len(page['users'])} of {page['total']}")

        # ------------------------------------------------- the Planner picker
        place = _place(tag, contact_id)
        deep = who.get(f"{api}/api/v1/planner/copilot/people", timeout=60,
                       params={"search": term, "limit": 25,
                               "offset": max(0, place - 3)}).json()
        ids = [int(p["user_id"]) for p in deep["people"]]
        report.check(
            "offset reaches the account that sorts last, on the page the "
            "service says it is on",
            place > 500 and contact_id in ids and ids.index(contact_id) == 3,
            f"the contact is #{place:,} of {deep['total']:,}; asked for "
            f"offset {max(0, place - 3)} and they were row "
            f"{ids.index(contact_id) if contact_id in ids else 'absent'}")

        twice = [who.get(f"{api}/api/v1/planner/copilot/people", timeout=60,
                         params={"search": term, "limit": 40,
                                 "offset": 4_000}).json()["people"]
                 for _ in range(2)]
        report.check(
            "the same request twice returns the same slice",
            [p["user_id"] for p in twice[0]] == [p["user_id"] for p in twice[1]],
            f"{len(twice[0])} rows, identical")

        shapes = {frozenset(row) for row in deep["people"]}
        report.check(
            "the Planner picker never hands back an email address",
            shapes == {frozenset({"user_id", "name", "username", "role"})},
            f"fields: {sorted(next(iter(shapes)))}")

        # -------------------------------------- the escalation, end to end
        boss = _signed_in(api, f"z.proof-{tag}")
        driver_id = int(who.get(f"{api}/api/v1/auth/me",
                                timeout=30).json()["user"]["id"])
        today = date.today()
        code = f"PRF-{tag[:5].upper()}"
        key = who.post(f"{api}/api/v1/planner/copilot/drafts", timeout=60,
                       json={"name": f"Directory proof {tag[:5]}"}
                       ).json()["key"]
        for command, payload in (
                ("set_overview", {"name": f"Directory proof {tag[:5]}",
                                  "code": code, "description": "x",
                                  "objective": "y"}),
                # The work is the DRIVER's. The escalation contact is the
                # account behind eight thousand others, and the point of the
                # run is whether the chase reaches THEM.
                ("set_governance", {
                    "sponsor_id": driver_id, "manager_id": driver_id,
                    "owner_id": driver_id, "escalation_id": contact_id,
                    "start_date": (today - timedelta(days=40)).isoformat(),
                    "target_end_date": (today + timedelta(days=60)
                                        ).isoformat()}),
                ("set_agentic", {"mode": "CRITICAL"}),
                ("add_milestone", {
                    "name": "Only milestone", "owner_id": driver_id,
                    "start_date": (today - timedelta(days=40)).isoformat(),
                    "target_date": (today + timedelta(days=30)).isoformat()}),
                ("add_task", {
                    "milestone_code": "M01", "title": "Overdue work",
                    "owner_id": driver_id, "description": "Late on purpose.",
                    "start_date": (today - timedelta(days=30)).isoformat(),
                    "due_date": (today - timedelta(days=8)).isoformat()})):
            out = who.post(f"{api}/api/v1/planner/copilot/drafts/{key}/apply",
                           timeout=60,
                           json={"command": command, "payload": payload})
            if out.status_code != 200:
                report.error = f"{command} refused: {out.status_code} {out.text[:200]}"
                return report
        made = who.post(f"{api}/api/v1/planner/copilot/drafts/{key}/publish",
                        timeout=120, json={"confirm": True})
        if made.status_code != 201:
            report.error = f"publish refused: {made.status_code} {made.text[:200]}"
            return report
        project_id = made.json()["project_id"]
        ran = who.post(
            f"{api}/api/v1/planner/projects/{project_id}/sweep", timeout=180)
        report.check("the agent ran over the published project",
                     ran.status_code == 200, f"HTTP {ran.status_code}")

        mine = boss.get(f"{api}/api/v1/workspace/notifications", timeout=60,
                        params={"limit": 50}).json()["notifications"]
        about = [n for n in mine if code in str(n.get("title", ""))
                 + str(n.get("body", ""))]
        said = " ".join(f"{n.get('title')} {n.get('body')}" for n in about)
        report.check(
            "the escalation contact, signed in, sees the escalation",
            bool(about), f"{len(about)} message(s) about {code}")
        report.check(
            "it names the overdue item, and says whose desk it stopped on",
            "M01-T01" in said and f"Zeynep Yilmaz{tag}" in said,
            said[:260].replace("\n", " ⏎ "))

        stranger = _signed_in(api, "omar.nasser", demo=True)
        theirs = stranger.get(f"{api}/api/v1/workspace/notifications",
                              timeout=60, params={"limit": 50}).json()
        leaked = [n for n in theirs["notifications"]
                  if code in str(n.get("title", "")) + str(n.get("body", ""))]
        report.check("nobody outside the plan was told about it",
                     not leaked, f"{len(leaked)} leaked")
    except Exception as exc:  # noqa: BLE001
        report.error = f"{type(exc).__name__}: {exc}"
    finally:
        if contact_id:
            print("Removing the accounts this proof created…")
        _remove(tag)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=API)
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    print(f"Directory and escalation proof against {args.api}\n")
    report = run(args.api, Report())
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, indent=2)
    if report.error:
        print(f"\nNothing is claimed: {report.error}")
        return 2
    print(f"\n{len(report.steps) - len(report.failures)} of "
          f"{len(report.steps)} checks passed.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
