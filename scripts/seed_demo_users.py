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
from backend.services.demo_users import DEMO_PASSWORD, DEMO_USERS, seed  # noqa: E402,F401


def main() -> int:
    """Seed the four demonstration accounts. Idempotent, and it never changes
    an existing password.

    The accounts and the seeding rule live in `backend/services/demo_users.py`
    so that this script and the Docker bootstrap run the same code. Two copies
    of a credential list is one copy that goes stale.
    """
    if not settings.has_database:
        print("No DATABASE_URL configured; nothing to seed.")
        return 0

    from backend.db.engine import get_session

    with get_session() as session:
        result = seed(session)
        session.commit()

    for username in result.created:
        print(f"  created {username}")
    for username in result.kept:
        print(f"  kept    {username} (already exists; password unchanged)")
    if result.created:
        print()
        print("  Demonstration password for the accounts just created: "
              f"{DEMO_PASSWORD}")
        print("  Synthetic data only. Change these before any real use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
