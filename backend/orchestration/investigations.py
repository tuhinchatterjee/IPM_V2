"""
Saved investigations: an answer somebody keeps, and can bring up to date.

The distinction this module exists to make
------------------------------------------
An *analysis run* is one execution. It happened, it produced figures, and it
never changes — that is what makes it evidence.

An *investigation* is a thing a person owns. It has a name, it can sit in a
project, and it can be REFRESHED. Refreshing does not touch the run it already
has: it executes the same plan again against whatever is published now, stores
the result as a new version, and describes what moved.

The rule that makes a refresh trustworthy
-----------------------------------------
No figure is ever carried forward. A refresh re-runs the registered analyses. If
a number is unchanged it is because the calculation produced it again, not
because it was copied from the previous version. The comparison between versions
is a subtraction of two engine results — arithmetic on figures the engine
returned, never a new measurement.

The change narrative is interpretation and is labelled as such. It reads the two
stored metric sets and says which moved and by how much. It does not say why.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings
from backend.orchestration.executor import Investigation as RunResult
from backend.orchestration.executor import run_investigation

logger = logging.getLogger(__name__)


class InvestigationNotFound(LookupError):
    pass


class StorageUnavailable(RuntimeError):
    """Saving needs PostgreSQL. Asking does not."""


# --------------------------------------------------------------- comparison


@dataclass(frozen=True)
class MetricChange:
    """One headline figure, before and after."""

    label: str
    unit: str
    before: float | None
    after: float | None
    change: float | None
    direction: str = "up-is-bad"

    @property
    def moved(self) -> bool:
        return self.change is not None and abs(self.change) > 1e-9

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "unit": self.unit, "before": self.before,
            "after": self.after, "change": self.change, "direction": self.direction,
            "moved": self.moved,
        }


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _metric_map(narrative: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(m.get("label")): m
        for m in (narrative or {}).get("metrics") or []
        if isinstance(m, dict) and m.get("label")
    }


def compare(previous: dict[str, Any], current: dict[str, Any]) -> list[MetricChange]:
    """What moved between two stored answers.

    Only labels present in BOTH are compared. A metric that appears or disappears
    means the analysis itself changed, and reporting that as a movement from
    nothing would be a fabrication.
    """
    before, after = _metric_map(previous), _metric_map(current)
    out: list[MetricChange] = []
    for label, new in after.items():
        old = before.get(label)
        if old is None:
            continue
        b, a = _as_number(old.get("value")), _as_number(new.get("value"))
        out.append(MetricChange(
            label=label,
            unit=str(new.get("unit") or ""),
            before=b,
            after=a,
            change=None if b is None or a is None else a - b,
            direction=str(new.get("direction") or "up-is-bad"),
        ))
    return out


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "%":
        return f"{value:+.2f}pp"
    if unit:
        return f"{value:+,.1f} {unit}"
    return f"{value:+,.1f}"


def change_narrative(changes: list[MetricChange], *,
                     from_label: str, to_label: str) -> str:
    """IPM's account of the difference. Interpretation, and no new figures.

    Every number in the sentence is a subtraction of two figures the engine
    produced, and the sentence says which way each one went. It does not offer a
    reason: nothing in a comparison of two totals establishes one.
    """
    moved = [c for c in changes if c.moved]
    if not changes:
        return (
            "This is the first stored answer, so there is nothing to compare it "
            "with yet."
        )

    # A refresh that keeps the same window is asking "has the data changed?",
    # and saying "between Q4 2025 to Q1 2026 and Q4 2025 to Q1 2026" would be a
    # sentence nobody can read. Naming the comparison correctly matters more
    # than reusing one phrasing.
    same_window = from_label == to_label
    against = (
        f"since this was last run for {to_label}" if same_window
        else f"between {from_label} and {to_label}"
    )

    if not moved:
        return (
            f"Nothing measured here moved {against}. The analyses were re-run in "
            "full; the figures are identical because they were calculated again, "
            "not because they were carried forward."
        )

    moved.sort(key=lambda c: abs(c.change or 0), reverse=True)
    lead = moved[0]
    worse = [c for c in moved
             if (c.change or 0) > 0 and c.direction == "up-is-bad"
             or (c.change or 0) < 0 and c.direction == "up-is-good"]

    sentence = (
        f"{len(moved)} of {len(changes)} headline figures moved {against}. "
        f"The largest is {lead.label}, {_fmt(lead.change, lead.unit)}."
    )
    if worse:
        sentence += (
            f" {len(worse)} moved in the adverse direction"
            f"{' — ' + ', '.join(c.label for c in worse[:3]) if worse else ''}."
        )
    sentence += (
        " This states what changed. It does not establish why, and nothing in a "
        "comparison of two periods can."
    )
    return sentence


# ------------------------------------------------------------------ storage


@dataclass
class SavedInvestigation:
    """A saved investigation and one of its versions, ready to render."""

    id: int
    title: str
    question: str
    status: str
    project_id: int | None
    owner_id: int | None
    scope: dict[str, Any]
    version: int
    versions: list[dict[str, Any]] = field(default_factory=list)
    analysis_run_id: int | None = None
    from_period: str | None = None
    to_period: str | None = None
    narrative: dict[str, Any] = field(default_factory=dict)
    change_narrative: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "question": self.question,
            "status": self.status,
            "project_id": self.project_id,
            "owner_id": self.owner_id,
            "scope": self.scope,
            "version": self.version,
            "versions": self.versions,
            "analysis_run_id": self.analysis_run_id,
            "from_period": self.from_period,
            "to_period": self.to_period,
            "narrative": self.narrative,
            "change_narrative": self.change_narrative,
            "changes": self.changes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Saving an investigation needs PostgreSQL. Questions can still be "
            "asked and answered without it; the answer just is not kept."
        )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _version_dict(row: Any) -> dict[str, Any]:
    return {
        "version": row.version_number,
        "analysis_run_id": row.analysis_run_id,
        "from_period": row.from_period,
        "to_period": row.to_period,
        "change_narrative": row.change_narrative,
        "created_at": _iso(row.created_at),
    }


def save(result: RunResult, *, title: str = "", project_id: int | None = None,
         user_id: int | None = None) -> SavedInvestigation:
    """Keep an answer. Version 1 is the run that has already happened."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Investigation, InvestigationVersion

    scope = result.plan.scope
    with get_session() as session:
        row = Investigation(
            project_id=project_id,
            title=(title or result.question)[:300],
            question=result.question,
            scope=scope.to_dict(),
            plan=result.plan.to_dict(),
            owner_id=user_id,
            current_version=1,
        )
        session.add(row)
        session.flush()

        version = InvestigationVersion(
            investigation_id=row.id,
            version_number=1,
            analysis_run_id=result.analysis_run_id,
            from_period=scope.from_period,
            to_period=scope.to_period,
            narrative=result.narrative.to_dict(),
            metrics={"metrics": [m.to_dict() for m in result.narrative.metrics]},
            change_narrative="",
            changes=[],
            created_by=user_id,
        )
        session.add(version)
        session.flush()
        session.commit()
        return load(row.id)


def load(investigation_id: int, version: int | None = None) -> SavedInvestigation:
    """One saved investigation at one of its versions."""
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Investigation, InvestigationVersion

    with get_session() as session:
        row = session.get(Investigation, investigation_id)
        if row is None:
            raise InvestigationNotFound(f"Investigation {investigation_id} does not exist.")

        versions = session.execute(
            select(InvestigationVersion)
            .where(InvestigationVersion.investigation_id == investigation_id)
            .order_by(InvestigationVersion.version_number)
        ).scalars().all()
        if not versions:
            raise InvestigationNotFound(
                f"Investigation {investigation_id} has no stored answer."
            )

        wanted = version or row.current_version
        current = next((v for v in versions if v.version_number == wanted), versions[-1])

        return SavedInvestigation(
            id=row.id,
            title=row.title,
            question=row.question,
            status=row.status,
            project_id=row.project_id,
            owner_id=row.owner_id,
            scope=dict(row.scope or {}),
            version=current.version_number,
            versions=[_version_dict(v) for v in versions],
            analysis_run_id=current.analysis_run_id,
            from_period=current.from_period,
            to_period=current.to_period,
            narrative=dict(current.narrative or {}),
            change_narrative=current.change_narrative,
            changes=list(current.changes or []),
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
        )


def refresh(investigation_id: int, *, user_id: int | None = None,
            period: tuple[str, str] | None = None) -> SavedInvestigation:
    """Re-run the same question and store the new answer as the next version.

    `period` moves the comparison window. Without it the investigation is
    re-asked exactly as it was, which for a two-period analysis means the same
    two periods — the honest reading of "refresh this" when the question named
    its periods. A caller that wants the latest data asks for it explicitly.
    """
    _require_db()
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Investigation, InvestigationVersion

    with get_session() as session:
        row = session.get(Investigation, investigation_id)
        if row is None:
            raise InvestigationNotFound(f"Investigation {investigation_id} does not exist.")
        latest = session.execute(
            select(InvestigationVersion)
            .where(InvestigationVersion.investigation_id == investigation_id)
            .order_by(InvestigationVersion.version_number.desc())
        ).scalars().first()
        question = row.question
        project_id = row.project_id
        previous_narrative = dict(latest.narrative or {}) if latest else {}
        previous_number = latest.version_number if latest else 0
        previous_label = (
            f"{latest.from_period} to {latest.to_period}"
            if latest and latest.from_period and latest.to_period
            else f"version {previous_number}"
        )
        window = period or (
            (latest.from_period, latest.to_period)
            if latest and latest.from_period and latest.to_period else None
        )

    # Outside the session: this executes real analyses and can take seconds.
    result = run_investigation(
        question, user_id=user_id, project_id=project_id, persist=True, period=window,
    )
    if result.status == "needs_clarification":  # pragma: no cover - window is supplied
        raise ValueError(
            "The stored investigation no longer settles its own period. "
            "Refresh it with an explicit comparison."
        )

    scope = result.plan.scope
    changes = compare(previous_narrative, result.narrative.to_dict())
    new_label = (
        f"{scope.from_period} to {scope.to_period}"
        if scope.from_period and scope.to_period else "the current position"
    )
    story = change_narrative(changes, from_label=previous_label, to_label=new_label)

    with get_session() as session:
        row = session.get(Investigation, investigation_id)
        version = InvestigationVersion(
            investigation_id=investigation_id,
            version_number=previous_number + 1,
            analysis_run_id=result.analysis_run_id,
            from_period=scope.from_period,
            to_period=scope.to_period,
            narrative=result.narrative.to_dict(),
            metrics={"metrics": [m.to_dict() for m in result.narrative.metrics]},
            change_narrative=story,
            changes=[c.to_dict() for c in changes],
            created_by=user_id,
        )
        session.add(version)
        row.current_version = previous_number + 1
        row.plan = result.plan.to_dict()
        row.scope = scope.to_dict()
        session.commit()

    return load(investigation_id)


def listing(*, project_id: int | None = None, owner_id: int | None = None,
            limit: int = 50) -> list[dict[str, Any]]:
    """Saved investigations, most recently updated first."""
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Investigation, InvestigationVersion

    with get_session() as session:
        query = select(Investigation).order_by(Investigation.updated_at.desc()).limit(limit)
        if project_id is not None:
            query = query.where(Investigation.project_id == project_id)
        if owner_id is not None:
            query = query.where(Investigation.owner_id == owner_id)
        rows = session.execute(query).scalars().all()

        out: list[dict[str, Any]] = []
        for row in rows:
            current = session.execute(
                select(InvestigationVersion)
                .where(
                    InvestigationVersion.investigation_id == row.id,
                    InvestigationVersion.version_number == row.current_version,
                )
            ).scalars().first()
            narrative = dict(current.narrative or {}) if current else {}
            out.append({
                "id": row.id,
                "title": row.title,
                "question": row.question,
                "status": row.status,
                "project_id": row.project_id,
                "owner_id": row.owner_id,
                "version": row.current_version,
                "answer": narrative.get("direct_answer") or narrative.get("summary") or "",
                "change_narrative": current.change_narrative if current else "",
                "from_period": current.from_period if current else None,
                "to_period": current.to_period if current else None,
                "analysis_run_id": current.analysis_run_id if current else None,
                "updated_at": _iso(row.updated_at),
            })
        return out


def archive(investigation_id: int) -> SavedInvestigation:
    """Stop keeping this current. The versions and their Traces remain."""
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import INV_ARCHIVED, Investigation

    with get_session() as session:
        row = session.get(Investigation, investigation_id)
        if row is None:
            raise InvestigationNotFound(f"Investigation {investigation_id} does not exist.")
        row.status = INV_ARCHIVED
        session.commit()
    return load(investigation_id)


__all__ = [
    "InvestigationNotFound",
    "MetricChange",
    "SavedInvestigation",
    "StorageUnavailable",
    "archive",
    "change_narrative",
    "compare",
    "listing",
    "load",
    "refresh",
    "save",
]
