#!/usr/bin/env python
"""
Declare the demonstration book's governed joins.

    python scripts/seed_relationships.py

Idempotent and additive: it never removes a relationship a steward declared,
because a bank's own join is not this script's to withdraw. Safe on every boot.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402


def main() -> int:
    if not settings.has_database:
        print("No DATABASE_URL configured — nothing to declare.")
        return 0

    from backend.db.engine import get_session
    from backend.services.relationships import seed

    with get_session() as session:
        result = seed(session)

    print(f"{len(result['declared'])} of {result['total']} governed joins declared.")
    for name in result["declared"]:
        print(f"  {name}")
    for name in result["skipped"]:
        print(f"  skipped (dataset not present): {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
