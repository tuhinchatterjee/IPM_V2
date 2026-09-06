"""
Saved and recent What-Ifs, and why this needed no new table.

Reusing what was already there
------------------------------
`stress_scenarios` has existed since migration 0002 with exactly the shape this
feature needs — a name, a version, a severity, a rationale, a `parameters`
JSONB, an owner and a timestamp, unique on `(name, version)` — and until now
nothing in the product read or wrote a single row of it. It was a migrated
table with no code behind it.

`Scenario.to_dict()` already produced the shape `parameters` wants, so a
scenario definition, the steps that built it, the staging criteria it ran on,
the methodology and model version it used and the figures it produced all fit
in that column. No migration was needed, and one written anyway would have
collided with 0042 and 0043, which the Project Planner branch has already
taken.

Saved and recent are the same row with a different status
----------------------------------------------------------
A saved What-If is one somebody named and kept. A recent What-If is one they
ran and did not name. Making them separate tables would mean two readers, two
access checks and two chances to disagree about who owns what — so they are one
row with a `status`, and "save this" is a status change rather than a copy.

Recent entries are pruned per owner. A list of every scenario anybody ever ran
is not a list anybody reads.

Ownership
---------
Every read is scoped to `created_by`. A saved What-If carries the population
that produced it and the figures it reached, so leaking one across users would
leak the book. There is no sharing in this scope and therefore no path that
returns another person's row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

THREADS_VERSION = "1.0.0"

SAVED = "saved"
RECENT = "recent"
STATUSES: tuple[str, ...] = (SAVED, RECENT)

#: How many unnamed runs are kept per person.
RECENT_LIMIT = 12


class ThreadError(ValueError):
    """A What-If that cannot be stored or read back."""


class Unavailable(ThreadError):
    """There is no database, so nothing can be saved. Said, never faked."""


def _session():
    from backend.config import settings

    if not settings.has_database:
        raise Unavailable(
            "Saved What-Ifs need the database, and DATABASE_URL is not "
            "configured. Nothing was saved.")
    from backend.db.engine import get_session

    return get_session()


def available() -> bool:
    from backend.config import settings

    return bool(settings.has_database)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Saved:
    """One stored What-If, as a card shows it."""

    id: int
    name: str
    status: str
    version: str
    severity: str
    created_at: str
    body: dict[str, Any]

    @property
    def period(self) -> str:
        return str(self.body.get("period") or "")

    def card(self) -> dict[str, Any]:
        summary = self.body.get("summary") or {}
        context = self.body.get("context") or {}
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "version": self.version, "severity": self.severity,
            "created_at": self.created_at,
            "last_opened_at": self.body.get("last_opened_at"),
            "period": self.period,
            "dataset": context.get("dataset") or "corporate_ifrs9",
            "scenario": context.get("scenario") or self.body.get("description", ""),
            "scenario_kinds": self.body.get("kinds") or [],
            "population_count": context.get("population_count"),
            "baseline_ecl": summary.get("baseline_ecl"),
            "whatif_ecl": summary.get("stressed_ecl"),
            "absolute_change": summary.get("incremental_ecl"),
            "percentage_change": summary.get("incremental_ecl_pct"),
            "ecl_methodology": context.get("ecl_methodology"),
            "ecl_methodology_version": context.get("ecl_methodology_version"),
            "staging_version": context.get("staging_version"),
            "currency": context.get("currency") or "SAR",
        }


def _row_to_saved(row: Any) -> Saved:
    body = row.parameters if isinstance(row.parameters, dict) else {}
    return Saved(id=int(row.id), name=str(row.name), status=str(row.status),
                 version=str(row.version), severity=str(row.severity),
                 created_at=row.created_at.isoformat() if row.created_at else "",
                 body=body)


def _unique_name(session: Any, model: Any, name: str, owner: int | None) -> str:
    """A name that does not collide with any row, not just the caller's own.

    The uniqueness constraint on this table is `(name, version)` and it is
    GLOBAL — it predates this feature and knows nothing about owners. Checking
    only the caller's own names would pass here and fail in the database the
    moment two people saved "Downgrade test", so the check has to match the
    constraint rather than the access rule.

    A person who saves the same name twice means two What-Ifs, not an error, so
    the second becomes "Downgrade test (2)".
    """
    _ = owner
    base = (name or "Untitled What-If").strip()[:170]
    rows = session.query(model.name).filter(
        model.version == THREADS_VERSION).all()
    existing = {str(r[0]) if isinstance(r, tuple) else str(r) for r in rows}
    if base not in existing:
        return base
    for n in range(2, 5000):
        candidate = f"{base} ({n})"
        if candidate not in existing:
            return candidate
    return f"{base} ({_now()})"  # pragma: no cover


def save(result: Any, *, name: str = "", owner: int | None = None,
         status: str = SAVED, instruction: str = "") -> Saved:
    """Store a run, with everything needed to reopen and reproduce it.

    The stored body carries the structured steps rather than the transcript,
    the staging criteria AND their version, the methodology AND its version,
    and the figures the run reached — so reopening it a month later shows the
    same scenario, and re-running it can be checked against what it said.
    """
    from backend.models.platform import StressScenario

    if status not in STATUSES:
        raise ThreadError(f"'{status}' is not a What-If status.")
    context = result.context()
    body = {
        "threads_version": THREADS_VERSION,
        "saved_at": _now(),
        "last_opened_at": _now(),
        "period": result.period,
        "instruction": instruction,
        "description": result.state.describe(),
        "kinds": list(result.state.kinds),
        "state": result.state.to_dict(),
        "context": context,
        "summary": dict(result.summary),
        "factors": result.factors.to_dict() if result.factors else None,
        "stage_movement": dict(result.stage_movement),
        "ml": dict(result.ml),
        "warnings": list(result.warnings),
    }
    with _session() as session:
        chosen = _unique_name(session, StressScenario, name or result.state.title
                              or result.state.describe()[:120], owner)
        row = StressScenario(
            name=chosen,
            description=result.state.describe()[:2000],
            rationale=instruction or result.state.describe()[:2000],
            parameters=body,
            severity=_severity(result.summary.get("incremental_ecl_pct", 0.0)),
            version=THREADS_VERSION,
            status=status,
            created_by=owner)
        session.add(row)
        session.flush()
        stored = _row_to_saved(row)
    if status == RECENT:
        prune(owner)
    return stored


def _severity(change_pct: float) -> str:
    """A severity read off the answer rather than asked for.

    The bands are the ones the preconfigured catalogue already uses, so a
    saved What-If sits alongside them without a second vocabulary.
    """
    moved = abs(float(change_pct or 0.0))
    if moved < 1.0:
        return "base"
    if moved < 15.0:
        return "mild"
    if moved < 50.0:
        return "moderate"
    return "severe"


def promote(scenario_id: int, *, name: str = "", owner: int | None = None) -> Saved:
    """Turn a recent run into a saved one. A status change, never a copy."""
    from backend.models.platform import StressScenario

    with _session() as session:
        row = _owned(session, StressScenario, scenario_id, owner)
        body = dict(row.parameters or {})
        body["saved_at"] = _now()
        row.parameters = body
        row.status = SAVED
        if name:
            row.name = _unique_name(session, StressScenario, name, owner)
        session.flush()
        return _row_to_saved(row)


def _owned(session: Any, model: Any, scenario_id: int, owner: int | None) -> Any:
    """One row, and only if it belongs to the person asking.

    A What-If carries the population it ran over and the figures it reached, so
    handing one to the wrong person hands them the book. The refusal does not
    distinguish "does not exist" from "is not yours", which is deliberate.
    """
    row = session.get(model, int(scenario_id))
    if row is None or (owner is not None and row.created_by not in (owner, None)):
        raise ThreadError(f"There is no What-If {scenario_id} you can open.")
    if owner is None and row.created_by is not None:
        raise ThreadError(f"There is no What-If {scenario_id} you can open.")
    return row


def get(scenario_id: int, *, owner: int | None = None) -> Saved:
    """Reopen a stored What-If, and note that it was opened."""
    from backend.models.platform import StressScenario

    with _session() as session:
        row = _owned(session, StressScenario, scenario_id, owner)
        body = dict(row.parameters or {})
        body["last_opened_at"] = _now()
        row.parameters = body
        session.flush()
        return _row_to_saved(row)


def listing(*, owner: int | None = None, status: str = SAVED,
            limit: int = 24) -> list[Saved]:
    """Somebody's own What-Ifs, most recent first."""
    from backend.models.platform import StressScenario

    if not available():
        return []
    with _session() as session:
        query = session.query(StressScenario).filter(
            StressScenario.status == status)
        query = query.filter(StressScenario.created_by == owner)
        rows = query.order_by(StressScenario.created_at.desc()).limit(
            int(limit)).all()
        return [_row_to_saved(r) for r in rows]


def prune(owner: int | None) -> int:
    """Keep the recent list short. Saved What-Ifs are never pruned."""
    from backend.models.platform import StressScenario

    if not available():
        return 0
    with _session() as session:
        rows = session.query(StressScenario).filter(
            StressScenario.status == RECENT,
            StressScenario.created_by == owner).order_by(
            StressScenario.created_at.desc()).all()
        removed = 0
        for row in rows[RECENT_LIMIT:]:
            session.delete(row)
            removed += 1
        return removed


def delete(scenario_id: int, *, owner: int | None = None) -> None:
    from backend.models.platform import StressScenario

    with _session() as session:
        row = _owned(session, StressScenario, scenario_id, owner)
        session.delete(row)


def reopen(scenario_id: int, *, owner: int | None = None) -> Any:
    """The stored What-If rebuilt as live scenario state."""
    from backend.whatif import steps as sp

    stored = get(scenario_id, owner=owner)
    state = sp.ScenarioState.from_dict(stored.body.get("state"))
    return state, stored


def describe() -> dict[str, Any]:
    """What this layer can and cannot do right now, said plainly."""
    return {
        "version": THREADS_VERSION,
        "available": available(),
        "table": "stress_scenarios",
        "migration_required": False,
        "why_no_migration": (
            "stress_scenarios has existed since migration 0002 with the shape "
            "this feature needs and no code behind it. The scenario state, "
            "staging criteria, methodology, versions and figures all fit its "
            "parameters JSONB."),
        "statuses": list(STATUSES),
        "recent_limit": RECENT_LIMIT,
        "scoping": "Every read is scoped to the owner. There is no sharing.",
        "unavailable_message": (
            "" if available() else
            "DATABASE_URL is not configured, so What-Ifs cannot be saved or "
            "listed. Scenarios still run."),
    }


__all__ = [
    "RECENT", "RECENT_LIMIT", "SAVED", "STATUSES", "Saved", "THREADS_VERSION",
    "ThreadError", "Unavailable", "available", "delete", "describe", "get",
    "listing", "promote", "prune", "reopen", "save",
]
