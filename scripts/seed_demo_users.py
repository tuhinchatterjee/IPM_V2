#!/usr/bin/env python
"""
Seed the demonstration accounts.

    python scripts/seed_demo_users.py

Idempotent: running it twice changes nothing. It creates an account only when
the username is absent, and it NEVER overwrites a password that already exists —
so a real deployment that happens to have a user called `admin` does not have
their credentials replaced by a published one.

The passwords below are printed in the README because this is a demonstration
system with synthetic data. They are not secrets and must not be reused
anywhere. A deployment sets `REQUIRE_LOGIN=true`, changes them on first run, and
uses `scripts/manage_users.py` for real accounts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402

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


def main() -> int:
    if not settings.has_database:
        print("No DATABASE_URL configured; nothing to seed.")
        return 0

    from backend.auth.security import hash_password
    from backend.db.engine import get_session
    from backend.db.models import User

    created, kept = [], []
    with get_session() as session:
        for spec in DEMO_USERS:
            existing = (
                session.query(User).filter(User.username == spec["username"]).first()
            )
            if existing is not None:
                # Fill in only what is genuinely missing. A password is never
                # touched: overwriting one would be a published back door.
                for field in ("first_name", "last_name", "email", "team"):
                    if not getattr(existing, field, ""):
                        setattr(existing, field, spec[field])
                kept.append(spec["username"])
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
            created.append(spec["username"])
        session.commit()

    for username in created:
        print(f"  created {username}")
    for username in kept:
        print(f"  kept    {username} (already exists; password unchanged)")
    if created:
        print()
        print("  Demonstration password for the accounts just created: "
              "creditprobe-demo")
        print("  Synthetic data only. Change these before any real use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
