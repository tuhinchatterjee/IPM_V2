"""Saving a cohort, reopening it, and never silently showing a newer one.

The defect this exists for
--------------------------
A reader exports a customer list into Borrower 360, spends twenty minutes on
it, downloads a workbook, closes the tab — and the list is gone, because
nothing was written until they pressed Save and they never did. So every
import writes a DRAFT investigation before the reader does anything. Save then
means "name and pin this", not "begin persisting".

The second failure is quieter and worse. A saved investigation that re-runs
its predicate when it is reopened shows a population that is not the one that
was saved: the book has been rebuilt since, three customers have cured, two
new ones qualify, and the figures under the note somebody wrote no longer
support the note. So a saved version points at an IMMUTABLE cohort snapshot,
and refreshing against a newer book writes version n+1 and leaves version n
exactly as it was.

Notes are data, not instructions
--------------------------------
A note is free text a person typed. It can say anything, including "ignore
your previous instructions". Nothing here treats it as anything but content:
it is stored, versioned and rendered escaped, and where it is handed to a
model it is labelled as untrusted. It cannot change a permission, a policy or
an execution decision.

Everything stored here describes SYNTHETIC demonstration data.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from backend.models.platform import (
    CohortSnapshot,
    InvestigationNote,
    SavedInvestigation,
)
from backend.retail import cohort as ch

logger = logging.getLogger(__name__)

VERSION = "retail-investigation-store-1.0.0"

DRAFT = "draft"
SAVED = "saved"


class NotPermitted(PermissionError):
    """The reader may not have this investigation. Worded like an absence."""


def _now() -> datetime:
    return datetime.now(UTC)


def _new_saved_id() -> str:
    return "CPSI-" + uuid.uuid4().hex[:12].upper()


def _new_note_id() -> str:
    return "CPNT-" + uuid.uuid4().hex[:12].upper()


# ---------------------------------------------------------------------------
# Drafting and saving
# ---------------------------------------------------------------------------


def draft_for(session: Any, snapshot: CohortSnapshot, *,
              title: str = "", issue: str = "", segment: str = "",
              noticed_at: datetime | None = None,
              odr: dict[str, Any] | None = None,
              owner_user_id: int | None = None,
              team_id: int | None = None) -> SavedInvestigation:
    """The draft every import writes, before anybody presses Save.

    Idempotent per snapshot: importing the same cohort twice does not create
    two cards. A second import of a DIFFERENT cohort does, because it is a
    different list.
    """
    existing = session.execute(
        select(SavedInvestigation)
        .where(SavedInvestigation.snapshot_id == snapshot.snapshot_id)
        .order_by(SavedInvestigation.version.desc())
    ).scalars().first()
    if existing is not None:
        return existing

    row = SavedInvestigation(
        saved_id=_new_saved_id(),
        version=1,
        snapshot_id=snapshot.snapshot_id,
        case_id=snapshot.case_id,
        occurrence_id=snapshot.occurrence_id,
        thread_id=snapshot.thread_id,
        source_step=snapshot.step_id,
        title=title or issue[:200] or snapshot.case_id,
        issue=issue,
        segment=segment,
        state=DRAFT,
        noticed_at=noticed_at,
        customer_count=snapshot.customer_count,
        facility_count=snapshot.facility_count,
        odr=dict(odr or not_yet_observed()),
        totals=dict(snapshot.totals or {}),
        owner_user_id=owner_user_id if owner_user_id is not None
        else snapshot.owner_user_id,
        team_id=team_id if team_id is not None else snapshot.team_id,
    )
    session.add(row)
    session.flush()
    logger.info("investigation draft %s for cohort %s (%d customers)",
                row.saved_id, snapshot.snapshot_id, row.customer_count)
    return row


def not_yet_observed(*, window: str = "") -> dict[str, Any]:
    """The honest state of an outcome rate whose window has not completed.

    A recent-investigation card shows this rather than a rate, because a
    fabricated default rate on a card somebody glances at is worse than no
    figure: it will be quoted.
    """
    return {
        "state": "not_yet_observed",
        "label": "Not yet observed",
        "because": ("the outcome window for this cohort has not completed, so "
                    "there is no observed rate to show"),
        "window": window,
        "value": None, "numerator": None, "denominator": None,
    }


def observed(*, value: float, numerator: int, denominator: int, window: str,
             snapshot_id: str, definition: str = "") -> dict[str, Any]:
    """An observed rate WITH everything needed to check it."""
    return {
        "state": "observed",
        "label": f"{value * 100:.1f}%",
        "value": round(value, 6),
        "numerator": int(numerator),
        "denominator": int(denominator),
        "window": window,
        "source_snapshot_id": snapshot_id,
        "definition": definition,
    }


def save(session: Any, saved: SavedInvestigation, *, title: str = "",
         pinned: bool | None = None) -> SavedInvestigation:
    """Name and pin an existing draft. Does not change what it points at."""
    saved.state = SAVED
    saved.saved_at = saved.saved_at or _now()
    if title:
        saved.title = title
    if pinned is not None:
        saved.pinned = bool(pinned)
    session.flush()
    return saved


def refresh(session: Any, saved: SavedInvestigation,
            snapshot: CohortSnapshot) -> SavedInvestigation:
    """Version n+1 against a newer cohort. Version n is left exactly as it was.

    The whole point of the store: "what did this say when I saved it" has an
    answer forever, and "what does it say now" is a deliberate act with its
    own row.
    """
    if snapshot.snapshot_id == saved.snapshot_id:
        return saved
    latest = session.execute(
        select(func.max(SavedInvestigation.version))
        .where(SavedInvestigation.saved_id == saved.saved_id)
    ).scalar_one()
    row = SavedInvestigation(
        saved_id=saved.saved_id,
        version=int(latest or saved.version) + 1,
        snapshot_id=snapshot.snapshot_id,
        case_id=saved.case_id,
        occurrence_id=saved.occurrence_id,
        thread_id=saved.thread_id,
        source_step=snapshot.step_id or saved.source_step,
        title=saved.title,
        issue=saved.issue,
        segment=saved.segment,
        state=saved.state,
        pinned=saved.pinned,
        noticed_at=saved.noticed_at,
        saved_at=_now(),
        customer_count=snapshot.customer_count,
        facility_count=snapshot.facility_count,
        odr=dict(saved.odr or {}),
        totals=dict(snapshot.totals or {}),
        owner_user_id=saved.owner_user_id,
        team_id=saved.team_id,
        share_scope=saved.share_scope,
    )
    session.add(row)
    session.flush()
    logger.info("investigation %s refreshed to version %d against cohort %s",
                row.saved_id, row.version, snapshot.snapshot_id)
    return row


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def load(session: Any, saved_id: str,
         version: int | None = None) -> SavedInvestigation | None:
    query = select(SavedInvestigation).where(
        SavedInvestigation.saved_id == saved_id)
    if version is not None:
        query = query.where(SavedInvestigation.version == version)
    return session.execute(
        query.order_by(SavedInvestigation.version.desc())
    ).scalars().first()


def load_by_snapshot(session: Any, snapshot_id: str
                     ) -> SavedInvestigation | None:
    """The investigation a cohort belongs to, latest version.

    Every import writes one, so this is normally present; a snapshot created
    outside that path has none, and the export then carries no notes rather
    than failing.
    """
    return session.execute(
        select(SavedInvestigation)
        .where(SavedInvestigation.snapshot_id == snapshot_id)
        .order_by(SavedInvestigation.version.desc())
    ).scalars().first()


def permitted(row: SavedInvestigation, *, user_id: int | None,
              role: str = "", team_id: int | None = None) -> bool:
    if (role or "").upper() in ("ADMIN", "OWNER"):
        return True
    if row.owner_user_id is None:
        return False
    if user_id is not None and row.owner_user_id == user_id:
        return True
    return bool(row.share_scope == "team" and row.team_id
                and team_id and row.team_id == team_id)


def read(session: Any, saved_id: str, *, user_id: int | None,
         role: str = "", team_id: int | None = None,
         version: int | None = None) -> SavedInvestigation:
    row = load(session, saved_id, version)
    if row is None or not permitted(row, user_id=user_id, role=role,
                                    team_id=team_id):
        raise NotPermitted(
            f"No investigation {saved_id!r} is readable here. It may not "
            f"exist, or it may not be yours.")
    return row


def recent(session: Any, *, user_id: int | None, role: str = "",
           team_id: int | None = None, limit: int = 12
           ) -> list[SavedInvestigation]:
    """The cards below the Borrower 360 chatbox: latest version of each.

    Drafts are included. A draft is a real, reopenable investigation that
    simply has no name yet, and hiding it would recreate the loss this store
    exists to prevent.
    """
    latest = (
        select(SavedInvestigation.saved_id,
               func.max(SavedInvestigation.version).label("version"))
        .group_by(SavedInvestigation.saved_id).subquery())
    rows = session.execute(
        select(SavedInvestigation)
        .join(latest,
              (SavedInvestigation.saved_id == latest.c.saved_id)
              & (SavedInvestigation.version == latest.c.version))
        .where(SavedInvestigation.archived_at.is_(None))
        .order_by(SavedInvestigation.pinned.desc(),
                  SavedInvestigation.created_at.desc())
        .limit(limit * 4)
    ).scalars().all()
    return [r for r in rows
            if permitted(r, user_id=user_id, role=role, team_id=team_id)
            ][:limit]


def versions(session: Any, saved_id: str) -> list[SavedInvestigation]:
    return list(session.execute(
        select(SavedInvestigation)
        .where(SavedInvestigation.saved_id == saved_id)
        .order_by(SavedInvestigation.version.asc())
    ).scalars().all())


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


def add_note(session: Any, saved: SavedInvestigation, *, body: str,
             author_user_id: int | None, author_name: str = "",
             subject_id: str = "") -> InvestigationNote:
    row = InvestigationNote(
        note_id=_new_note_id(), version=1, saved_id=saved.saved_id,
        snapshot_id=saved.snapshot_id, subject_id=subject_id,
        body=body, author_user_id=author_user_id, author_name=author_name)
    session.add(row)
    session.flush()
    return row


def edit_note(session: Any, note_id: str, *, body: str,
              author_user_id: int | None,
              author_name: str = "") -> InvestigationNote:
    """A new version, never an overwrite.

    In a dispute about what somebody was told, the previous wording is the
    part that matters.
    """
    latest = session.execute(
        select(InvestigationNote)
        .where(InvestigationNote.note_id == note_id)
        .order_by(InvestigationNote.version.desc())
    ).scalars().first()
    if latest is None:
        raise LookupError(f"no note {note_id!r}")
    row = InvestigationNote(
        note_id=note_id, version=latest.version + 1,
        saved_id=latest.saved_id, snapshot_id=latest.snapshot_id,
        subject_id=latest.subject_id, body=body,
        author_user_id=author_user_id, author_name=author_name)
    session.add(row)
    session.flush()
    return row


def notes(session: Any, saved_id: str, *,
          include_history: bool = False) -> list[InvestigationNote]:
    rows = list(session.execute(
        select(InvestigationNote)
        .where(InvestigationNote.saved_id == saved_id,
               InvestigationNote.deleted_at.is_(None))
        .order_by(InvestigationNote.created_at.asc(),
                  InvestigationNote.version.asc())
    ).scalars().all())
    if include_history:
        return rows
    seen: dict[str, InvestigationNote] = {}
    for row in rows:
        current = seen.get(row.note_id)
        if current is None or row.version > current.version:
            seen[row.note_id] = row
    return sorted(seen.values(), key=lambda r: r.created_at or _now())


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def note_view(row: InvestigationNote) -> dict[str, Any]:
    return {
        "note_id": row.note_id,
        "version": row.version,
        "body": row.body,
        "author": row.author_name,
        "author_user_id": row.author_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "untrusted_content": True,
        "note": ("A note is content a person typed. It is never read as an "
                 "instruction to this product and cannot change a permission, "
                 "a policy or an execution decision."),
    }


def view(row: SavedInvestigation, *, note_rows: list[InvestigationNote] | None
         = None, snapshot: CohortSnapshot | None = None) -> dict[str, Any]:
    stored = list(note_rows or [])
    return {
        "saved_id": row.saved_id,
        "version": row.version,
        "snapshot_id": row.snapshot_id,
        "case_id": row.case_id,
        "occurrence_id": row.occurrence_id,
        "thread_id": row.thread_id,
        "source_step": row.source_step,
        "title": row.title,
        "issue": row.issue,
        "segment": row.segment,
        "state": row.state,
        "pinned": row.pinned,
        "noticed_at": row.noticed_at.isoformat() if row.noticed_at else None,
        "saved_at": row.saved_at.isoformat() if row.saved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "customer_count": row.customer_count,
        "facility_count": row.facility_count,
        "odr": dict(row.odr or {}),
        "totals": dict(row.totals or {}),
        "share_scope": row.share_scope,
        "notes": [note_view(n) for n in stored],
        "note_count": len(stored),
        "notes_preview": (stored[-1].body[:160] if stored else ""),
        "snapshot": ch.view(snapshot) if snapshot is not None else None,
    }
