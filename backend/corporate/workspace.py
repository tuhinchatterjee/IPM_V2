"""
A person's own working set on the Borrower 360. B12.

Two things a credit officer does between sessions, and could not do before:
keep a borrower to hand, and keep a search worth running again.

Why a saved cohort stores the QUERY and not the result
--------------------------------------------------------
The corporate book is rebuilt every quarter. A saved list of borrower ids
would keep returning last quarter's answer under this quarter's name, which
is the worst kind of stale: it looks current, it is nobody's mistake, and the
first person to notice is the one presenting it.

So a cohort stores the facets. "Contracting names over the group limit" is
still that question next quarter; the borrowers it returns are not the same
borrowers, and that is the point of saving it.

Why a pin carries a NOTE
--------------------------
A pinned borrower with nothing beside it tells the reader that somebody
cared, once. The note records what it looked like when it was pinned — "group
utilisation 31%, INVESTIGATE" — so opening the pin a month later shows
whether anything moved rather than only what is true today. It is a string
the person wrote or the screen captured, never a stored figure the product
will later present as current.

Why neither is shared
-----------------------
A pinned name is somebody's judgement about what to watch this week.
Publishing one person's watch list to their team is a different feature, with
a different approval, and inferring it from a pin would publish a judgement
nobody offered. Everything here is scoped to `(tenant, user)`.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.corporate import search as search_mod
from backend.models.platform import Borrower360Workspace

WORKSPACE_VERSION = "1.0.0"

PIN = Borrower360Workspace.KIND_PIN
COHORT = Borrower360Workspace.KIND_COHORT
KINDS: tuple[str, ...] = (PIN, COHORT)

#: How many of each kind one person may keep. A working set that grows
#: without limit is a list nobody reads, and the second failure mode is a
#: screen that takes a second to open because somebody pinned the book.
MAX_PER_KIND = 50

#: What a cohort may filter on: exactly the attributes the search declares.
#: Taken from the search rather than restated, so a facet renamed there
#: renames itself here and a saved cohort cannot filter on a field that no
#: longer exists.
FACETS: tuple[str, ...] = tuple(search_mod.SEARCHABLE)

_SLUG = re.compile(r"[^a-z0-9]+")


class WorkspaceError(ValueError):
    """A working-set change that was refused, with the reason."""


def slug(label: str) -> str:
    """A stable reference for a cohort, from the name a person gave it.

    Deterministic so that saving "Contracting over limit" twice updates one
    cohort rather than creating a second with the same name, which is how a
    list of saved searches becomes a list nobody trusts.
    """
    cleaned = _SLUG.sub("-", (label or "").strip().lower()).strip("-")
    return cleaned[:100] or "cohort"


def _rows(session: Session, *, user_id: int | None, kind: str,
          tenant: str = "") -> list[Borrower360Workspace]:
    query = select(Borrower360Workspace).where(
        Borrower360Workspace.tenant == tenant,
        Borrower360Workspace.user_id == user_id,
        Borrower360Workspace.kind == kind,
    ).order_by(Borrower360Workspace.position,
               Borrower360Workspace.created_at)
    return list(session.execute(query).scalars())


def _validate_query(payload: dict[str, Any] | None) -> dict[str, Any]:
    """A cohort may only filter on declared attributes.

    Refused rather than dropped. A facet silently ignored produces a cohort
    that is wider than the one somebody saved, under the name they gave the
    narrower one.
    """
    given = dict(payload or {})
    facets = dict(given.get("facets") or {})
    unknown = sorted(set(facets) - set(FACETS))
    if unknown:
        raise WorkspaceError(
            f"a cohort cannot filter on {', '.join(unknown)}: the Borrower "
            f"360 searches on {len(FACETS)} declared attributes and these "
            "are not among them")

    flags = [str(f) for f in (given.get("flags") or [])]
    ids = [str(b) for b in (given.get("borrower_ids") or [])]
    text = str(given.get("text") or "").strip()
    if not (facets or flags or ids or text):
        raise WorkspaceError(
            "a cohort with no facet, flag, borrower or search text is the "
            "whole book under a name that suggests otherwise")
    return {"text": text, "facets": facets, "flags": flags,
            "borrower_ids": ids}


def pins(session: Session, *, user_id: int | None,
         tenant: str = "") -> list[dict[str, Any]]:
    return [_view(row) for row in _rows(session, user_id=user_id, kind=PIN,
                                        tenant=tenant)]


def cohorts(session: Session, *, user_id: int | None,
            tenant: str = "") -> list[dict[str, Any]]:
    return [_view(row) for row in _rows(session, user_id=user_id, kind=COHORT,
                                        tenant=tenant)]


def _view(row: Borrower360Workspace) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "reference": row.reference,
        "label": row.label,
        "query": dict(row.query or {}),
        "position": row.position,
        "noted": row.noted,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def pin(session: Session, *, user_id: int | None, borrower_id: str,
        label: str = "", noted: str = "", position: int = 0,
        tenant: str = "") -> dict[str, Any]:
    """Keep one borrower to hand. Pinning twice updates rather than duplicates."""
    reference = (borrower_id or "").strip()
    if not reference:
        raise WorkspaceError("a pin needs a borrower")
    return _upsert(session, user_id=user_id, kind=PIN, reference=reference,
                   label=label or reference, query={}, noted=noted,
                   position=position, tenant=tenant)


def save_cohort(session: Session, *, user_id: int | None, label: str,
                query: dict[str, Any] | None, position: int = 0,
                tenant: str = "") -> dict[str, Any]:
    """Keep a search worth running again. The facets, not the result."""
    name = (label or "").strip()
    if not name:
        raise WorkspaceError("a saved cohort needs a name somebody can read")
    return _upsert(session, user_id=user_id, kind=COHORT,
                   reference=slug(name), label=name,
                   query=_validate_query(query), noted="",
                   position=position, tenant=tenant)


def _upsert(session: Session, *, user_id: int | None, kind: str,
            reference: str, label: str, query: dict[str, Any], noted: str,
            position: int, tenant: str) -> dict[str, Any]:
    existing = session.execute(
        select(Borrower360Workspace).where(
            Borrower360Workspace.tenant == tenant,
            Borrower360Workspace.user_id == user_id,
            Borrower360Workspace.kind == kind,
            Borrower360Workspace.reference == reference)
    ).scalar_one_or_none()

    if existing is not None:
        existing.label = label or existing.label
        existing.query = query or existing.query
        existing.noted = noted or existing.noted
        existing.position = position
        session.flush()
        return _view(existing)

    held = len(_rows(session, user_id=user_id, kind=kind, tenant=tenant))
    if held >= MAX_PER_KIND:
        raise WorkspaceError(
            f"{held} is the most {kind.lower()}s this working set holds. "
            "Remove one before adding another - a list that grows without "
            "limit is a list nobody reads.")

    row = Borrower360Workspace(
        user_id=user_id, kind=kind, reference=reference, label=label,
        query=query, noted=noted, position=position, tenant=tenant)
    session.add(row)
    session.flush()
    return _view(row)


def remove(session: Session, *, user_id: int | None, kind: str,
           reference: str, tenant: str = "") -> bool:
    if kind not in KINDS:
        raise WorkspaceError(f"{kind!r} is not a working-set kind")
    removed = session.query(Borrower360Workspace).filter(
        Borrower360Workspace.tenant == tenant,
        Borrower360Workspace.user_id == user_id,
        Borrower360Workspace.kind == kind,
        Borrower360Workspace.reference == reference).delete()
    session.flush()
    return bool(removed)


def summary(session: Session, *, user_id: int | None,
            tenant: str = "") -> dict[str, Any]:
    """What this person's working set holds, for the screen's header."""
    return {
        "version": WORKSPACE_VERSION,
        "pins": pins(session, user_id=user_id, tenant=tenant),
        "cohorts": cohorts(session, user_id=user_id, tenant=tenant),
        "maximum_per_kind": MAX_PER_KIND,
        "searchable": list(FACETS),
        "note": ("A working set is yours alone. Nothing here is shared with "
                 "your team, and a saved cohort stores the search rather "
                 "than the borrowers it matched - the book is rebuilt every "
                 "quarter."),
    }


__all__ = [
    "COHORT", "FACETS", "KINDS", "MAX_PER_KIND", "PIN",
    "WORKSPACE_VERSION", "WorkspaceError", "cohorts", "pin", "pins",
    "remove", "save_cohort", "slug", "summary",
]
