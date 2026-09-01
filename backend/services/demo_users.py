"""The four demonstration accounts, and the one rule about seeding them.

Moved here out of `scripts/seed_demo_users.py` so the bootstrap and the script
run the SAME code rather than two copies that drift. The script is now a thin
wrapper; its behaviour is unchanged, including what it prints.

The rule: **an existing password is never touched.** Re-seeding fills in a
blank name or team and leaves the credential alone. A start-up step that reset
a password every boot would be a published back door on any deployment that
kept the default compose file — and it would do it silently, on the machine
where somebody had just changed it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: One person per role, so the demonstration can show what each of them sees.
DEMO_USERS: list[dict[str, str]] = [
    {
        "username": "alex.rahman",
        "password": "creditprobe-demo",
        "first_name": "Alex",
        "last_name": "Rahman",
        "email": "alex.rahman@example-bank.com",
        "role": "ADMIN",
        "team": "Credit Risk Analytics",
    },
    {
        "username": "sara.qahtani",
        "password": "creditprobe-demo",
        "first_name": "Sara",
        "last_name": "Al Qahtani",
        "email": "sara.qahtani@example-bank.com",
        "role": "DATA_STEWARD",
        "team": "Risk Data Management",
    },
    {
        "username": "omar.nasser",
        "password": "creditprobe-demo",
        "first_name": "Omar",
        "last_name": "Nasser",
        "email": "omar.nasser@example-bank.com",
        "role": "ANALYST",
        "team": "Portfolio Management",
    },
    {
        "username": "layla.haddad",
        "password": "creditprobe-demo",
        "first_name": "Layla",
        "last_name": "Haddad",
        "email": "layla.haddad@example-bank.com",
        "role": "VIEWER",
        "team": "Board Risk Committee",
    },
]

DEMO_PASSWORD = "creditprobe-demo"


@dataclass
class Seeded:
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"created": list(self.created), "kept": list(self.kept)}


def seed(session: Any) -> Seeded:
    """Create the demonstration accounts that do not exist yet.

    Does not commit — the caller owns the transaction, which is what lets the
    bootstrap seed users and register the catalogue in one unit of work.
    """
    from backend.auth.security import hash_password
    from backend.db.models import User

    result = Seeded()
    for spec in DEMO_USERS:
        existing = session.query(User).filter(
            User.username == spec["username"]).first()
        if existing is not None:
            # Fill in only what is genuinely missing. A password is never
            # touched: overwriting one would be a published back door.
            for attribute in ("first_name", "last_name", "email", "team"):
                if not getattr(existing, attribute, ""):
                    setattr(existing, attribute, spec[attribute])
            result.kept.append(spec["username"])
            continue

        session.add(User(
            username=spec["username"],
            password_hash=hash_password(spec["password"]),
            first_name=spec["first_name"],
            last_name=spec["last_name"],
            email=spec["email"],
            role=spec["role"],
            team=spec["team"],
            is_active=True,
        ))
        result.created.append(spec["username"])
    return result


__all__ = ["DEMO_PASSWORD", "DEMO_USERS", "Seeded", "seed"]
