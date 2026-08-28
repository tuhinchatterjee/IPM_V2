"""
The export audit log.

§41. Every attempt to download an analysis is recorded — allowed, denied or
failed. A log that recorded only the successes could not answer the question an
access review actually asks, which is "who tried".

Writing a record must never be able to stop a download. A database that has gone
away is a serious operational problem and it is not this user's problem; the
export completes and the failure is logged loudly for whoever is watching the
service. The reverse — refusing to serve a file because the log is unavailable —
would turn a monitoring outage into an outage of the product.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ALLOWED = "allowed"
DENIED = "denied"
FAILED = "failed"


@dataclass
class Entry:
    """One row of the export log, before it is written."""

    kind: str
    object_type: str = "analysis_run"
    object_id: str = ""
    run_id: int | None = None
    trace_version: int | None = None
    user_id: int | None = None
    role: str = ""
    status: str = ALLOWED
    authorization: str = ""
    reason: str = ""
    filename: str = ""
    content_hash: str = ""
    size_bytes: int | None = None
    row_count: int | None = None
    duration_ms: int | None = None
    datasets: list[str] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def content_hash(content: bytes) -> str:
    """The SHA-256 of what was sent.

    Two downloads of the same run at the same Trace version should differ only
    in their timestamp and their downloader. A differing hash is therefore a
    real question, and recording it is what makes that question answerable.
    """
    return hashlib.sha256(content).hexdigest()


def record(entry: Entry) -> int | None:
    """Write one audit row. Returns its id, or None if it could not be written."""
    from backend.config import settings

    if not settings.has_database:
        logger.info("Export not audited (no database): %s %s by user %s — %s",
                    entry.kind, entry.object_id, entry.user_id, entry.status)
        return None
    try:
        from backend.db.engine import get_session
        from backend.models.platform import ExportRecord

        with get_session() as session:
            row = ExportRecord(
                kind=entry.kind,
                object_type=entry.object_type,
                object_id=str(entry.object_id),
                run_id=entry.run_id,
                trace_version=entry.trace_version,
                user_id=entry.user_id,
                role=entry.role,
                status=entry.status,
                authorization=entry.authorization[:64],
                reason=entry.reason,
                filename=entry.filename[:255],
                content_hash=entry.content_hash,
                size_bytes=entry.size_bytes,
                row_count=entry.row_count,
                duration_ms=entry.duration_ms,
                datasets=list(entry.datasets),
                redactions=list(entry.redactions),
                detail=dict(entry.detail),
            )
            session.add(row)
            session.flush()
            return row.id
    except Exception as e:  # noqa: BLE001 - never fail a download over the log
        logger.error("Could not write the export audit record: %s", e, exc_info=True)
        return None


def history(*, run_id: int | None = None, object_type: str = "",
            object_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """The download history of one run, investigation or project.

    Read by the Analysis and Project audit views. Returns the most recent first,
    which is the order somebody asking "who has had this?" reads in.
    """
    from backend.config import settings

    if not settings.has_database:
        return []
    try:
        from sqlalchemy import desc, select

        from backend.db.engine import get_session
        from backend.db.models import User
        from backend.models.platform import ExportRecord

        with get_session() as session:
            query = select(ExportRecord).order_by(desc(ExportRecord.created_at))
            if run_id is not None:
                query = query.where(ExportRecord.run_id == run_id)
            if object_type:
                query = query.where(ExportRecord.object_type == object_type)
            if object_id:
                query = query.where(ExportRecord.object_id == str(object_id))
            rows = session.execute(query.limit(limit)).scalars().all()

            names: dict[int, str] = {}
            wanted = {r.user_id for r in rows if r.user_id}
            if wanted:
                for user in session.execute(
                    select(User).where(User.id.in_(wanted))
                ).scalars().all():
                    names[user.id] = (
                        f"{user.first_name} {user.last_name}".strip()
                        or user.username
                    )

            return [{
                "id": row.id,
                "kind": row.kind,
                "kind_label": ("Results workbook" if row.kind == "results"
                               else "Full calculation pack"),
                "object_type": row.object_type,
                "object_id": row.object_id,
                "run_id": row.run_id,
                "trace_version": row.trace_version,
                "user_id": row.user_id,
                "user_name": names.get(row.user_id or 0, ""),
                "role": row.role,
                "status": row.status,
                "authorization": row.authorization,
                "reason": row.reason,
                "filename": row.filename,
                "content_hash": row.content_hash,
                "size_bytes": row.size_bytes,
                "row_count": row.row_count,
                "duration_ms": row.duration_ms,
                "datasets": list(row.datasets or []),
                "redactions": list(row.redactions or []),
                "at": row.created_at.isoformat() if row.created_at else "",
            } for row in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read the export audit history: %s", e)
        return []
