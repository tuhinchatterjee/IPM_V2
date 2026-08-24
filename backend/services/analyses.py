"""
Saved Analyses: one certified calculation, kept.

Where this sits in the hierarchy
--------------------------------
    Analysis   < Investigation < Project
    one result   a conversation   a body of work

An Analysis is the smallest unit of evidence in CreditProbe: a single certified
engine function, run with stated parameters, over a stated period, against
stated data versions, producing one result. It is what a credit committee points
at.

What "saved" means here
-----------------------
Saving does NOT re-run anything and does not copy figures forward. A saved
analysis records the run that already happened: which analysis, at which
version, at which certification, with which parameters, and the result the
engine returned, together with the `analysis_run_id` that ties it back to the
immutable run and its Trace. Reading a saved analysis reads that record. If you
want current figures, you re-run — that is a new Analysis, not an edit of this
one.

Because the record names its run, everything a reviewer needs is reachable
without trusting this module: the Trace, the data versions, the engine version.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


class AnalysisNotFound(LookupError):
    pass


class StorageUnavailable(RuntimeError):
    """Keeping an analysis needs PostgreSQL. Running one does not."""


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Saving an analysis needs PostgreSQL. Analyses still run without "
            "it; the result just is not kept."
        )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass
class SavedAnalysisView:
    id: int
    title: str
    analysis_id: str
    analysis_version: str
    certification: str
    analysis_run_id: int | None
    investigation_id: int | None
    project_id: int | None
    params: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    period: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    data_versions: dict[str, Any] = field(default_factory=dict)
    note: str = ""
    owner_id: int | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "analysis_id": self.analysis_id,
            "analysis_version": self.analysis_version,
            "certification": self.certification,
            "analysis_run_id": self.analysis_run_id,
            "investigation_id": self.investigation_id,
            "project_id": self.project_id,
            "params": self.params,
            "filters": self.filters,
            "period": self.period,
            "result": self.result,
            "data_versions": self.data_versions,
            "note": self.note,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
        }


def _view(row: Any) -> SavedAnalysisView:
    return SavedAnalysisView(
        id=row.id,
        title=row.title,
        analysis_id=row.analysis_id,
        analysis_version=row.analysis_version,
        certification=row.certification,
        analysis_run_id=row.analysis_run_id,
        investigation_id=row.investigation_id,
        project_id=row.project_id,
        params=dict(row.params or {}),
        filters=dict(row.filters or {}),
        period=dict(row.period or {}),
        result=dict(row.result or {}),
        data_versions=dict(row.data_versions or {}),
        note=row.note,
        owner_id=row.owner_id,
        created_at=_iso(row.created_at),
    )


def _certification_of(analysis_id: str) -> tuple[str, str]:
    """(certification, version) as the registry declares them, or blanks.

    Read from the registry rather than accepted from the caller: certification
    is a governance fact about the function, not something a save request gets
    to assert.
    """
    try:
        from backend.engine.registry import get_registry

        contract = get_registry().contract(analysis_id)
    except Exception:  # pragma: no cover - unknown id, or no registry yet
        return "", ""
    certification = getattr(contract, "certification", None)
    return (
        str(getattr(certification, "value", certification) or ""),
        str(getattr(contract, "version", "") or ""),
    )


def save(*, analysis_id: str, title: str = "", result: dict[str, Any] | None = None,
         params: dict[str, Any] | None = None, filters: dict[str, Any] | None = None,
         period: dict[str, Any] | None = None,
         data_versions: dict[str, Any] | None = None,
         analysis_run_id: int | None = None, investigation_id: int | None = None,
         project_id: int | None = None, note: str = "",
         user_id: int | None = None) -> SavedAnalysisView:
    """Keep a run that has already happened. Nothing is recalculated."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import SavedAnalysis

    certification, version = _certification_of(analysis_id)
    with get_session() as session:
        row = SavedAnalysis(
            title=(title or analysis_id)[:300],
            analysis_id=analysis_id[:120],
            analysis_version=version[:24],
            certification=certification or "draft",
            analysis_run_id=analysis_run_id,
            investigation_id=investigation_id,
            project_id=project_id,
            params=dict(params or {}),
            filters=dict(filters or {}),
            period=dict(period or {}),
            result=dict(result or {}),
            data_versions=dict(data_versions or {}),
            note=note,
            owner_id=user_id,
        )
        session.add(row)
        session.flush()
        session.commit()
        return _view(row)


def save_from_run(run: Any, *, title: str = "", investigation_id: int | None = None,
                  project_id: int | None = None, note: str = "",
                  user_id: int | None = None) -> list[SavedAnalysisView]:
    """Keep every certified step of an executed investigation as an Analysis.

    An answer is usually more than one calculation. Saving the answer as a
    single blob would lose the thing that makes each figure defensible — which
    certified function produced it. So each executed step becomes its own saved
    Analysis, and all of them point back at the same run.
    """
    scope = getattr(getattr(run, "plan", None), "scope", None)
    window = {
        "period": None,
        "from_period": getattr(scope, "from_period", None),
        "to_period": getattr(scope, "to_period", None),
    }

    out: list[SavedAnalysisView] = []
    for step in getattr(run, "steps", []) or []:
        analysis_id = getattr(step, "analysis_id", None)
        if not analysis_id or getattr(step, "status", "") != "succeeded":
            continue
        result = getattr(step, "result", None)
        out.append(save(
            analysis_id=str(analysis_id),
            title=title or getattr(step, "title", "") or str(analysis_id),
            result=result if isinstance(result, dict) else {"value": result},
            params=dict(getattr(step, "params", None) or {}),
            filters=dict(getattr(step, "filters", None) or {}),
            period={**window, "period": getattr(step, "period", None)},
            data_versions=dict(getattr(step, "node_hashes", None) or {}),
            analysis_run_id=(getattr(step, "analysis_run_id", None)
                             or getattr(run, "analysis_run_id", None)),
            investigation_id=investigation_id,
            project_id=project_id,
            note=note,
            user_id=user_id,
        ))
    return out


def get(saved_id: int) -> SavedAnalysisView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import SavedAnalysis

    with get_session() as session:
        row = session.get(SavedAnalysis, saved_id)
        if row is None:
            raise AnalysisNotFound(f"Saved analysis {saved_id} does not exist.")
        return _view(row)


def listing(*, project_id: int | None = None, investigation_id: int | None = None,
            owner_id: int | None = None, analysis_id: str | None = None,
            limit: int = 100) -> list[dict[str, Any]]:
    """Saved analyses, newest first."""
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import SavedAnalysis

    with get_session() as session:
        query = select(SavedAnalysis).order_by(SavedAnalysis.id.desc()).limit(limit)
        if project_id is not None:
            query = query.where(SavedAnalysis.project_id == project_id)
        if investigation_id is not None:
            query = query.where(SavedAnalysis.investigation_id == investigation_id)
        if owner_id is not None:
            query = query.where(SavedAnalysis.owner_id == owner_id)
        if analysis_id:
            query = query.where(SavedAnalysis.analysis_id == analysis_id)
        return [_view(row).to_dict()
                for row in session.execute(query).scalars().all()]


def move(saved_id: int, *, project_id: int | None) -> SavedAnalysisView:
    """File a saved analysis under a project, or take it out of one."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Project, SavedAnalysis

    with get_session() as session:
        row = session.get(SavedAnalysis, saved_id)
        if row is None:
            raise AnalysisNotFound(f"Saved analysis {saved_id} does not exist.")
        if project_id is not None and session.get(Project, project_id) is None:
            raise AnalysisNotFound(f"Project {project_id} does not exist.")
        row.project_id = project_id
        session.commit()
        return _view(row)


def rename(saved_id: int, title: str) -> SavedAnalysisView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import SavedAnalysis

    with get_session() as session:
        row = session.get(SavedAnalysis, saved_id)
        if row is None:
            raise AnalysisNotFound(f"Saved analysis {saved_id} does not exist.")
        row.title = title[:300]
        session.commit()
        return _view(row)


def delete(saved_id: int) -> None:
    """Remove the saved record. The run and its Trace are untouched."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import SavedAnalysis

    with get_session() as session:
        row = session.get(SavedAnalysis, saved_id)
        if row is None:
            raise AnalysisNotFound(f"Saved analysis {saved_id} does not exist.")
        session.delete(row)
        session.commit()


__all__ = [
    "AnalysisNotFound",
    "SavedAnalysisView",
    "StorageUnavailable",
    "delete",
    "get",
    "listing",
    "move",
    "rename",
    "save",
    "save_from_run",
]
