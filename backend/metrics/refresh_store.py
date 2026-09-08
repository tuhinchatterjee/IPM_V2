"""Where a Lens's refreshes live, and who may read them back. §20, §32, §48.

Reading history is not a way round permissions
-----------------------------------------------
§48 is the rule that shapes this module: a person opening a Lens today may not
see, in its history, anything they would not be allowed to compute now. So
`history` takes the same `user_id` and `readable` a live render takes, resolves
the Lens through the same permission-aware service, and drops any snapshot
whose metric that person can no longer resolve.

That last clause is the one that matters. A metric can become unreadable
between two refreshes — it was un-shared, or the person's role changed — and a
history table that answered from stored rows alone would happily hand back a
figure the live product would refuse. So stored figures are filtered by what
the asker may compute TODAY, not by what was computable when they were stored.

Two histories, never mixed
---------------------------
§22. `refresh_history` is one point per refresh, oldest first: Sep 1 9.1%,
Sep 2 9.1%, Sep 3 9.4%. `period_history` is one point per reporting period,
taking the LAST refresh in each: Q4 2025 7.5%, Q1 2026 8.1%, Q2 2026 9.4%.
They answer different questions and the screen labels them separately, because
a reader shown one and told it is the other draws the wrong conclusion with
complete confidence.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from backend.config import settings
from backend.metrics.refresh import (
    HISTORY_LIMIT,
    PanelSnapshot,
    Refresh,
)

logger = logging.getLogger(__name__)

STORE_VERSION = "3.0.0"


class StorageUnavailable(RuntimeError):
    """There is no database, so a Lens cannot remember anything."""


def available() -> bool:
    return bool(settings.has_database)


def _require_db() -> None:
    if not available():
        raise StorageUnavailable(
            "Lens refresh history needs the database, and this deployment has "
            "none configured. The Lens still renders; it cannot yet say what "
            "changed.")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def record(refresh: Refresh) -> Refresh:
    """Store one refresh and its snapshots. Returns it with its id filled in."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import LensMetricSnapshot, LensRefresh

    with get_session() as session:
        row = LensRefresh(
            lens_id=refresh.lens_id,
            reporting_period=refresh.reporting_period[:32],
            filter_hash=refresh.filter_hash[:32],
            lens_definition_version=refresh.lens_definition_version,
            data_versions=dict(refresh.data_versions),
            trigger=refresh.trigger,
            status=refresh.status,
            classification={"codes": list(refresh.classification)},
            compared_with_id=refresh.compared_with_id,
            interpretation=dict(refresh.interpretation),
            duration_ms=int(refresh.duration_ms),
            budget=dict(refresh.budget),
            triggered_by=refresh.triggered_by,
        )
        if refresh.refreshed_at is not None:
            row.refreshed_at = refresh.refreshed_at
        session.add(row)
        session.flush()
        for snapshot in refresh.panels:
            session.add(LensMetricSnapshot(
                refresh_id=row.id,
                panel_key=snapshot.panel_key[:160],
                metric_id=snapshot.metric_id[:160],
                kind=snapshot.kind[:24],
                title=snapshot.title[:240],
                metric_definition_version=snapshot.metric_definition_version[:32],
                definition_hash=snapshot.definition_hash[:32],
                value=snapshot.value,
                comparison_value=snapshot.comparison_value,
                unit=snapshot.unit[:24],
                decimals=snapshot.decimals,
                grain=snapshot.grain[:240],
                coverage=dict(snapshot.coverage),
                reporting_period=snapshot.reporting_period[:32],
                domains={"domains": list(snapshot.domains)},
                series={"points": list(snapshot.series)},
                query_version=snapshot.query_version[:32],
                data_version=snapshot.data_version[:64],
                status=snapshot.status[:24],
                diagnostics=dict(snapshot.diagnostics),
            ))
        session.commit()
        refresh.id = row.id
        refresh.refreshed_at = row.refreshed_at
        return refresh


def annotate(refresh_id: int, *, compared_with_id: int | None = None,
             classification: list[str] | None = None,
             interpretation: dict[str, Any] | None = None,
             duration_ms: int | None = None,
             budget: dict[str, Any] | None = None) -> None:
    """Fill in what is only known once the comparison and the reading are done.

    Separate from `record` because the snapshot must be STORED before it is
    compared: comparing first and storing afterwards would leave a window in
    which a concurrent refresh compares against a row that is not there yet.
    """
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import LensRefresh

    with get_session() as session:
        row = session.get(LensRefresh, refresh_id)
        if row is None:
            return
        if compared_with_id is not None:
            row.compared_with_id = compared_with_id
        if classification is not None:
            row.classification = {"codes": list(classification)}
        if interpretation is not None:
            row.interpretation = dict(interpretation)
        if duration_ms is not None:
            row.duration_ms = int(duration_ms)
        if budget is not None:
            row.budget = dict(budget)
        session.commit()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _as_refresh(row: Any, snapshots: Iterable[Any]) -> Refresh:
    return Refresh(
        id=row.id, lens_id=row.lens_id, refreshed_at=row.refreshed_at,
        reporting_period=row.reporting_period or "",
        filter_hash=row.filter_hash or "",
        lens_definition_version=int(row.lens_definition_version or 1),
        data_versions=dict(row.data_versions or {}),
        trigger=row.trigger or "lens_opened",
        status=row.status or "succeeded",
        classification=list((row.classification or {}).get("codes") or []),
        compared_with_id=row.compared_with_id,
        interpretation=dict(row.interpretation or {}),
        duration_ms=int(row.duration_ms or 0),
        budget=dict(row.budget or {}),
        triggered_by=row.triggered_by,
        panels=[PanelSnapshot(
            panel_key=s.panel_key, metric_id=s.metric_id, kind=s.kind,
            title=s.title, value=s.value,
            comparison_value=s.comparison_value, unit=s.unit,
            decimals=int(s.decimals or 2), grain=s.grain,
            reporting_period=s.reporting_period,
            metric_definition_version=s.metric_definition_version,
            definition_hash=s.definition_hash,
            coverage=dict(s.coverage or {}),
            domains=list((s.domains or {}).get("domains") or []),
            series=list((s.series or {}).get("points") or []),
            query_version=s.query_version, data_version=s.data_version,
            status=s.status, diagnostics=dict(s.diagnostics or {}),
        ) for s in snapshots],
    )


def history(lens_id: int, *, limit: int = HISTORY_LIMIT,
            user_id: int | None = None,
            readable: Iterable[str] | None = None,
            before_id: int | None = None) -> list[Refresh]:
    """This Lens's recent refreshes, newest first, filtered by permission.

    See the module docstring: a snapshot whose metric the asker cannot resolve
    TODAY is dropped, whatever was true when it was stored.
    """
    if not available():
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import LensMetricSnapshot, LensRefresh

    try:
        with get_session() as session:
            query = (select(LensRefresh)
                     .where(LensRefresh.lens_id == lens_id)
                     .order_by(LensRefresh.refreshed_at.desc(),
                               LensRefresh.id.desc())
                     .limit(max(1, int(limit))))
            if before_id:
                query = query.where(LensRefresh.id < before_id)
            rows = list(session.execute(query).scalars().all())
            if not rows:
                return []
            ids = [r.id for r in rows]
            snapshots = list(session.execute(
                select(LensMetricSnapshot)
                .where(LensMetricSnapshot.refresh_id.in_(ids))
                .order_by(LensMetricSnapshot.panel_key)).scalars().all())
    except Exception:  # noqa: BLE001 - a Lens without history still renders
        logger.warning("could not read lens refresh history", exc_info=True)
        return []

    allowed = _readable_metric_ids(user_id=user_id, readable=readable)
    by_refresh: dict[int, list[Any]] = {}
    for snapshot in snapshots:
        if allowed is not None and snapshot.metric_id and (
                snapshot.metric_id not in allowed):
            continue
        by_refresh.setdefault(snapshot.refresh_id, []).append(snapshot)
    return [_as_refresh(row, by_refresh.get(row.id, [])) for row in rows]


def _readable_metric_ids(*, user_id: int | None,
                         readable: Iterable[str] | None) -> set[str] | None:
    """Every metric this person may compute now, or None when unrestricted.

    None rather than "all of them" so the common case — an analyst who may
    read everything — costs one catalogue read and no set membership test per
    snapshot.
    """
    from backend.metrics import service

    try:
        pool = service.catalogue(user_id=user_id, readable=readable)
    except Exception:  # noqa: BLE001 - fail closed
        return set()
    return {m.metric_id for m in pool}


def get(refresh_id: int) -> Refresh | None:
    if not available():
        return None
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import LensMetricSnapshot, LensRefresh

    with get_session() as session:
        row = session.get(LensRefresh, refresh_id)
        if row is None:
            return None
        snapshots = list(session.execute(
            select(LensMetricSnapshot)
            .where(LensMetricSnapshot.refresh_id == refresh_id)
            .order_by(LensMetricSnapshot.panel_key)).scalars().all())
        return _as_refresh(row, snapshots)


def latest(lens_id: int) -> Refresh | None:
    found = history(lens_id, limit=1)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# §22 and §32: the two histories
# ---------------------------------------------------------------------------


def series(lens_id: int, metric_id: str, *, limit: int = HISTORY_LIMIT,
           user_id: int | None = None,
           readable: Iterable[str] | None = None) -> dict[str, Any]:
    """One metric's two histories on this Lens, labelled and never mixed.

    `refresh_history` is one point per refresh — what this metric said each
    time the Lens ran. `reporting_period_history` is one point per business
    period, taking the LAST refresh that reported each. A metric refreshed
    three times in one quarter has three points in the first and one in the
    second, and that is the distinction §32 asks the screen to make explicit.
    """
    refreshes = history(lens_id, limit=max(limit * 3, limit),
                        user_id=user_id, readable=readable)
    refreshes = list(reversed(refreshes))  # oldest first, for a chart

    by_refresh: list[dict[str, Any]] = []
    by_period: dict[str, dict[str, Any]] = {}
    for refresh in refreshes:
        for snapshot in refresh.panels:
            if snapshot.metric_id != metric_id:
                continue
            point = {
                "refresh_id": refresh.id,
                "refreshed_at": (refresh.refreshed_at.isoformat()
                                 if refresh.refreshed_at else ""),
                "reporting_period": snapshot.reporting_period,
                "value": snapshot.value,
                "unit": snapshot.unit,
                "decimals": snapshot.decimals,
                "status": snapshot.status,
                "definition_hash": snapshot.definition_hash,
                "trigger": refresh.trigger,
            }
            by_refresh.append(point)
            if snapshot.reporting_period:
                by_period[snapshot.reporting_period] = point
            break

    definitions = {p["definition_hash"] for p in by_refresh
                   if p["definition_hash"]}
    return {
        "metric_id": metric_id,
        "lens_id": lens_id,
        # §22A. One point per refresh: "Sep 1 9.1%, Sep 2 9.1%, Sep 3 9.4%".
        "refresh_history": by_refresh[-limit:],
        # §22B. One point per business period: "Q4 2025 7.5%, Q1 2026 8.1%".
        "reporting_period_history": list(by_period.values())[-limit:],
        "labels": {
            "refresh_history": "Refresh history — what this metric said each "
                               "time the Lens ran",
            "reporting_period_history": "Reporting period history — what this "
                                        "metric said for each business "
                                        "period",
        },
        # A history whose points were not all computed the same way, said
        # rather than drawn as though they were.
        "definition_changed_during": len(definitions) > 1,
        "definition_note": (
            "This metric was calculated differently at some point in this "
            "history, so the points are not all measurements of the same "
            "definition." if len(definitions) > 1 else ""),
    }


def prune(lens_id: int, *, keep: int = 200) -> int:
    """Drop the oldest refreshes beyond `keep`. Returns how many went.

    A Lens opened fifty times a day accumulates rows nobody will read. The
    limit is generous and the deletion cascades to snapshots; the newest are
    always kept, because history is read backwards.
    """
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import LensRefresh

    with get_session() as session:
        ids = list(session.execute(
            select(LensRefresh.id)
            .where(LensRefresh.lens_id == lens_id)
            .order_by(LensRefresh.refreshed_at.desc(), LensRefresh.id.desc())
            .offset(max(1, int(keep)))).scalars().all())
        if not ids:
            return 0
        for refresh_id in ids:
            row = session.get(LensRefresh, refresh_id)
            if row is not None:
                session.delete(row)
        session.commit()
        return len(ids)


__all__ = ["STORE_VERSION", "StorageUnavailable", "annotate", "available",
           "get", "history", "latest", "prune", "record", "series"]
