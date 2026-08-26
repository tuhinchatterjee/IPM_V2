"""
Keeping intelligence checks, so a score can be compared with the last one.

A single number is nearly useless. "94" says almost nothing; "94 on Tuesday, 79
today, same benchmark, new model" says exactly what happened and what to look at.
So every run is kept with what it was validating — provider, model, build,
benchmark version, data version — and a score is marked **stale** the moment any
of those move on rather than being quietly compared across a change.

Degrades rather than fails. With no database the check still runs and still shows
its result; only the history is unavailable, and the panel says so instead of
pretending there was never a previous run.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: How many runs the history shows. A year of weekly checks, which is more than
#: anybody scrolls and enough to see a regression.
HISTORY = 50


def available() -> bool:
    from backend.config import settings

    return bool(settings.has_database)


def save(result: Any, *, user_id: int | None = None) -> int | None:
    """Store one run and its cases. Returns the run id, or None if unstored."""
    if not available():
        return None
    try:
        from backend.db.engine import get_session
        from backend.models.platform import AiValidationCase, AiValidationRun

        with get_session() as session:
            row = AiValidationRun(
                user_id=user_id, provider=result.provider, model=result.model,
                build_sha=result.build_sha, app_version=result.app_version,
                benchmark_version=result.benchmark_version,
                data_version=result.data_version, ai_state=result.ai_state,
                status="completed", score=result.score, band=result.band,
                case_count=len(result.cases), passed=result.passed,
                partial=result.partial, failed=result.failed,
                duration_ms=result.duration_ms,
                components=dict(result.components),
                selected_ids=[c.benchmark_id for c in result.cases],
                notes=list(result.notes),
            )
            session.add(row)
            session.flush()
            for position, case in enumerate(result.cases):
                session.add(AiValidationCase(
                    run_id=row.id, position=position,
                    benchmark_id=case.benchmark_id, category=case.category,
                    title=case.title, score=case.score, verdict=case.verdict,
                    latency_ms=case.latency_ms, used_fallback=case.used_fallback,
                    components=dict(case.components), turns=list(case.turns),
                    deductions=list(case.deductions),
                    reference=dict(case.reference),
                ))
            session.commit()
            return int(row.id)
    except Exception as e:  # noqa: BLE001 - a storage failure must not lose a run
        logger.warning("Could not store the validation run: %s", e)
        return None


def latest() -> dict[str, Any] | None:
    """The most recent run, with its cases, or None."""
    runs = history(limit=1, with_cases=True)
    return runs[0] if runs else None


def history(*, limit: int = HISTORY,
            with_cases: bool = False) -> list[dict[str, Any]]:
    if not available():
        return []
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AiValidationRun

        with get_session() as session:
            rows = session.execute(
                select(AiValidationRun)
                .order_by(AiValidationRun.created_at.desc())
                .limit(max(1, min(limit, HISTORY)))
            ).scalars().all()
            return [_run_dict(r, with_cases=with_cases) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read validation history: %s", e)
        return []


def case(run_id: int, benchmark_id: str) -> dict[str, Any] | None:
    """One case in full — every turn, the reference and the deductions."""
    if not available():
        return None
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AiValidationCase

        with get_session() as session:
            row = session.execute(
                select(AiValidationCase)
                .where(AiValidationCase.run_id == run_id,
                       AiValidationCase.benchmark_id == benchmark_id)
            ).scalars().first()
            return _case_dict(row) if row is not None else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read validation case: %s", e)
        return None


def _label(band: str) -> str:
    from backend.validation.runner import _label as label_for

    return label_for(str(band or ""))


def _run_dict(row: Any, *, with_cases: bool) -> dict[str, Any]:
    out = {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "provider": row.provider, "model": row.model,
        "build_sha": row.build_sha, "app_version": row.app_version,
        "benchmark_version": row.benchmark_version,
        "data_version": row.data_version, "ai_state": row.ai_state,
        "status": row.status, "score": row.score, "band": row.band,
        "label": _label(row.band),
        "case_count": row.case_count, "passed": row.passed,
        "partial": row.partial, "failed": row.failed,
        "duration_ms": row.duration_ms, "components": dict(row.components or {}),
        "selected_ids": list(row.selected_ids or []),
        "notes": list(row.notes or []),
        **staleness(row),
    }
    if with_cases:
        out["cases"] = [_case_dict(c) for c in row.cases]
    return out


def _case_dict(row: Any) -> dict[str, Any]:
    return {
        "benchmark_id": row.benchmark_id, "category": row.category,
        "title": row.title, "score": row.score, "verdict": row.verdict,
        "latency_ms": row.latency_ms, "used_fallback": row.used_fallback,
        "components": dict(row.components or {}),
        "turns": list(row.turns or []),
        "deductions": list(row.deductions or []),
        "reference": dict(row.reference or {}),
    }


def staleness(row: Any) -> dict[str, Any]:
    """Whether this score still describes what is running.

    A score earned against one model, on one build, over one benchmark version
    and one data universe says nothing about another. Rather than compare across
    the change and produce a misleading trend, the run is labelled STALE and the
    user is invited to re-run it.
    """
    from backend.build_info import build_info
    from backend.llm import health as ai_health
    from backend.validation import gold, runner

    observed = ai_health()
    info = build_info()
    changed: list[str] = []

    if str(row.provider or "") != str(observed.get("provider") or ""):
        changed.append("the AI provider has changed")
    if str(row.model or "") != str(observed.get("model") or ""):
        changed.append("the model has changed")
    if str(row.build_sha or "") != info.short_sha:
        changed.append("CreditProbe has been rebuilt")
    if str(row.benchmark_version or "") != gold.BENCHMARK_VERSION:
        changed.append("the benchmark library has changed")
    current_data = runner._data_version()
    if str(row.data_version or "") != current_data:
        changed.append("the published data has changed")

    # The stale label keeps the run's own honesty. A check that never reached
    # the model was labelled AI OFFLINE; going stale must not promote it to
    # AI POWERED on its way out.
    return {
        "stale": bool(changed),
        "stale_because": changed,
        "stale_label": f"{_label(row.band)} · STALE" if changed else "",
    }


__all__ = ["HISTORY", "available", "case", "history", "latest", "save",
           "staleness"]
