"""
Reading and writing investigation versions.

The versioning rule from docs/PRODUCT_SPEC.md §4.4:

    A modification never edits a trace. It creates a new version whose parent is
    the version it came from. Every earlier version stays readable for ever.

So there is no update path in this module. `save_version` only inserts, and the
original row is never touched — which is what allows the UI to offer Original /
Version 2 / Version 3 and mean it.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.config import settings
from backend.orchestration.executor import ExecutedStep, Investigation
from backend.orchestration.schema import AnalysisPlan

logger = logging.getLogger(__name__)


class InvestigationNotFound(LookupError):
    pass


def _versions_for(session: Any, run_id: int) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from backend.models.platform import TraceVersionRow

    rows = session.execute(
        select(TraceVersionRow.version_number, TraceVersionRow.label,
               TraceVersionRow.created_at)
        .where(TraceVersionRow.analysis_run_id == run_id)
        .order_by(TraceVersionRow.version_number)
    ).all()
    return [
        {"version": v, "label": label,
         "created_at": created.isoformat() if created else None}
        for v, label, created in rows
    ]


def load_version(run_id: int, version: int | None = None) -> dict[str, Any]:
    """Load one stored version of an investigation, with its siblings listed."""
    if not settings.has_database:
        raise InvestigationNotFound(
            "No database is configured, so stored investigations cannot be reopened."
        )
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import AnalysisRun, TraceVersionRow

    with get_session() as session:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise InvestigationNotFound(f"No analysis run {run_id}.")

        stmt = select(TraceVersionRow).where(TraceVersionRow.analysis_run_id == run_id)
        stmt = (
            stmt.where(TraceVersionRow.version_number == version)
            if version
            else stmt.order_by(TraceVersionRow.version_number.desc())
        )
        row = session.execute(stmt).scalars().first()
        if row is None:
            raise InvestigationNotFound(
                f"No trace version {version or '(latest)'} for analysis run {run_id}."
            )

        stored = row.result if isinstance(row.result, dict) else {}
        # Version 1 of a single-analysis run predates the investigation shape and
        # stores only the engine result, so the plan is recovered from the run.
        plan_payload = stored.get("plan") or run.plan or {}
        return {
            "analysis_run_id": run_id,
            "question": run.question or "",
            "intent": (run.intent or {}).get("intent") or "",
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "duration_ms": run.duration_ms,
            "context": run.context or {},
            "version": row.version_number,
            "version_id": row.id,
            "label": row.label,
            "graph": row.graph or {},
            "node_hashes": row.node_hashes or {},
            "plan": plan_payload,
            "steps": stored.get("steps") or (run.result or {}).get("steps") or [],
            "narrative": stored.get("narrative") or {},
            "follow_ups": run.follow_ups or [],
            "available_versions": _versions_for(session, run_id),
            "model_provider": run.model_provider,
            "model_name": run.model_name,
        }


def plan_of(payload: dict[str, Any]) -> AnalysisPlan:
    plan = AnalysisPlan.from_dict(payload.get("plan") or {})
    if not plan.question:
        plan = AnalysisPlan(
            question=payload.get("question") or "",
            intent=plan.intent or payload.get("intent") or "",
            steps=plan.steps, planner=plan.planner, model_name=plan.model_name,
            follow_ups=plan.follow_ups, unmatched=plan.unmatched, notes=plan.notes,
        )
    return plan


def steps_of(payload: dict[str, Any]) -> list[ExecutedStep]:
    return [ExecutedStep.from_dict(s) for s in payload.get("steps") or []]


def save_version(run_id: int, *, from_version_id: int | None,
                 investigation: Investigation, request_text: str,
                 change_payload: dict[str, Any],
                 user_id: int | None = None) -> dict[str, Any]:
    """Insert a new trace version and record the modification that produced it."""
    if not settings.has_database:
        raise InvestigationNotFound(
            "No database is configured, so a new version cannot be stored."
        )
    from sqlalchemy import func, select

    from backend.db.engine import get_session
    from backend.models.platform import TraceModificationRow, TraceVersionRow

    with get_session() as session:
        highest = session.execute(
            select(func.max(TraceVersionRow.version_number))
            .where(TraceVersionRow.analysis_run_id == run_id)
        ).scalar() or 0
        number = int(highest) + 1

        row = TraceVersionRow(
            analysis_run_id=run_id,
            version_number=number,
            parent_version_id=from_version_id,
            label=f"Version {number}",
            graph=investigation.graph.to_dict(),
            node_hashes=investigation.node_hashes,
            result={"steps": [s.to_dict() for s in investigation.steps],
                    "narrative": investigation.narrative.to_dict(),
                    "plan": investigation.plan.to_dict(),
                    "request": request_text},
            created_by=user_id,
        )
        session.add(row)
        session.flush()

        if from_version_id is not None:
            session.add(TraceModificationRow(
                from_version_id=from_version_id,
                to_version_id=row.id,
                request_text=request_text,
                interpretation=change_payload.get("operation") or {},
                affected_nodes=change_payload.get("affected_nodes") or [],
                hash_diff=change_payload.get("hash_diff") or {},
                status="accepted",
                created_by=user_id,
            ))
        return {"version": number, "version_id": row.id, "label": row.label}


def list_modifications(run_id: int) -> list[dict[str, Any]]:
    """Every change ever requested against this investigation, applied or not."""
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import TraceModificationRow, TraceVersionRow

    with get_session() as session:
        version_ids = [
            v for (v,) in session.execute(
                select(TraceVersionRow.id).where(TraceVersionRow.analysis_run_id == run_id)
            ).all()
        ]
        if not version_ids:
            return []
        rows = session.execute(
            select(TraceModificationRow)
            .where(TraceModificationRow.from_version_id.in_(version_ids))
            .order_by(TraceModificationRow.created_at)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "request": r.request_text,
                "interpretation": r.interpretation,
                "affected_nodes": r.affected_nodes,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def recent_investigations(limit: int = 8) -> list[dict[str, Any]]:
    """The most recent questions asked, for the Cockpit's Recent Investigations."""
    if not settings.has_database:
        return []
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AnalysisRun

        with get_session() as session:
            rows = session.execute(
                select(AnalysisRun)
                .where(AnalysisRun.question != "")
                .order_by(AnalysisRun.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return [
                {
                    "analysis_run_id": r.id,
                    "question": r.question,
                    "intent": (r.intent or {}).get("intent") or "",
                    "status": r.status,
                    "summary": r.narrative,
                    "step_count": len((r.plan or {}).get("steps") or []),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "duration_ms": r.duration_ms,
                }
                for r in rows
            ]
    except Exception as e:  # pragma: no cover - history is a convenience
        logger.warning("Could not list recent investigations: %s", e)
        return []


__all__ = [
    "InvestigationNotFound",
    "list_modifications",
    "load_version",
    "plan_of",
    "recent_investigations",
    "save_version",
    "steps_of",
]
