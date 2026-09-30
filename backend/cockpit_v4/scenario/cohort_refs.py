"""A governed cohort, named by id, bound into a scenario preview.

The What-If workspace and the Cockpit are two entrances to one engine
(§30, §38). A banker who selects rows in the workspace grid and then asks the
Cockpit to stress "this selection" must get EXACTLY the population they
selected -- not the analyst's reconstruction of it from a description, which
could differ by a filter the grid had and the selector cannot express.

So a preview may name a saved cohort instead of carrying filters:

    "cohort": {"cohort_id": "coh-1a2b3c4d5e6f"}

Nothing about the population comes from the request. The id is resolved by
the resolver the Guided Workspace registers (server code, reading the
server-written cohort record), the engine freezes the predicate that record
holds, and the preview is refused unless the frozen membership hash equals the
one the cohort was saved with. A cohort whose rows moved is named as moved;
it is never silently re-resolved into a different population.

When no resolver is registered (the workspace flag is off), a cohort id is
refused by name -- the accepted runtime behaves exactly as before.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.cockpit_v4.scenario.errors import COHORT_UNRESOLVED, raise_for

#: What a governed cohort id looks like. Checked before any lookup.
COHORT_ID = re.compile(r"^coh-[0-9a-f]{12}$")

Resolver = Callable[..., dict[str, Any]]

_RESOLVER: dict[str, Resolver] = {}


def register(resolver: Resolver) -> None:
    """Install the resolver. Server code only; called at workspace import."""
    _RESOLVER["fn"] = resolver


def unregister() -> None:
    _RESOLVER.pop("fn", None)


def registered() -> bool:
    return "fn" in _RESOLVER


def resolve(cohort_id: str, *, domain_id: str, tenant_id: str,
            release_id: str) -> dict[str, Any]:
    """The stored cohort's predicate and identity, or a refusal.

    Returns `predicate`, `selection`, `period`, `membership_hash`,
    `entity_count`, `described_as` and `name`. Every value is server-written.
    """
    if not COHORT_ID.match(cohort_id or ""):
        raise_for(COHORT_UNRESOLVED,
                  f"{cohort_id!r} is not a governed cohort id.",
                  field_path="cohort.cohort_id")
    fn = _RESOLVER.get("fn")
    if fn is None:
        raise_for(COHORT_UNRESOLVED,
                  "saved cohorts are not available in this runtime, so a "
                  "cohort cannot be named by id. Describe the population "
                  "with filters instead.",
                  field_path="cohort.cohort_id")
    return fn(cohort_id, domain_id=domain_id, tenant_id=tenant_id,
              release_id=release_id)


__all__ = ["COHORT_ID", "register", "registered", "resolve", "unregister"]
