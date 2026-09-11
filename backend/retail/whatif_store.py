"""
Saved retail What-Ifs, in the table that already exists for them.

`stress_scenarios` carries a name, a JSON body, an owner, a status and a
timestamp, and the corporate What-If already stores its runs there. A retail run
is a different shape of body in the same table rather than a second table: two
tables would mean two readers, two ownership checks and two chances for them to
disagree about who may see what.

Every read is scoped to the owner. A saved scenario carries the population it
ran over and the figures it reached, so returning somebody else's row would
leak the book.

Nothing here recomputes. A saved run is what that run SAID, pinned to the
snapshot it read — reopening it must show the same numbers a month later, which
is the whole reason a person saves one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

#: Stamped into the row's `version` column, which is VARCHAR(24) — a longer
#: string is not truncated, it is a 500 on save. Kept short and checked by a
#: test rather than by the database.
STORE_VERSION = "retail-whatif-1.0.0"
SAVED = "saved"
KIND = "retail_whatif"


class Unavailable(RuntimeError):
    """There is no database, so nothing can be saved. Said, never faked."""


def _session() -> Any:
    from backend.config import settings

    if not settings.has_database:
        raise Unavailable(
            "Saving a What-If needs the database, and DATABASE_URL is not "
            "configured. Nothing was saved, and the run itself is unaffected.")
    from backend.db.engine import get_session

    return get_session()


def available() -> bool:
    try:
        with _session():
            return True
    except Exception:  # noqa: BLE001
        return False


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class SavedRun:
    id: int
    name: str
    created_at: str
    body: dict[str, Any]

    def card(self) -> dict[str, Any]:
        run = self.body.get("run") or {}
        delta = run.get("delta") or {}
        baseline = run.get("baseline") or {}
        scenario = run.get("scenario") or {}
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "month": self.body.get("month", ""),
            "question": self.body.get("question", ""),
            "run_id": scenario.get("run_id", ""),
            "filters": scenario.get("filters") or {},
            "shocks": scenario.get("shocks") or {},
            "staging_mode": scenario.get("staging_mode", ""),
            "scenario_weights": scenario.get("scenario_weights"),
            "methodology_version": scenario.get("methodology_version", ""),
            "dataset_version": scenario.get("dataset_version", ""),
            "baseline_ecl": baseline.get("ecl_final_sar"),
            "whatif_ecl": (run.get("scenario_result") or {}).get("ecl_final_sar"),
            "delta_sar": delta.get("ecl_final_sar"),
            "delta_pct": delta.get("ecl_final_pct"),
            "facilities": baseline.get("facilities"),
        }


def _row(row: Any) -> SavedRun:
    body = row.parameters if isinstance(row.parameters, dict) else {}
    created = getattr(row, "created_at", None)
    return SavedRun(id=int(row.id), name=str(row.name),
                    created_at=created.isoformat() if created else "",
                    body=body)


def _unique(session: Any, model: Any, name: str, owner: int | None) -> str:
    """A name nobody has used twice. The table is unique on (name, version)."""
    wanted = (name or "What-If").strip()[:120] or "What-If"
    taken = {n for (n,) in session.query(model.name).filter(
        model.created_by == owner).all()}
    if wanted not in taken:
        return wanted
    for suffix in range(2, 100):
        candidate = f"{wanted} ({suffix})"
        if candidate not in taken:
            return candidate
    return f"{wanted} {_now()}"


def save(*, name: str, question: str, month: str, run: dict[str, Any],
         owner: int | None = None) -> SavedRun:
    """Store a run exactly as it was answered."""
    from backend.models.platform import StressScenario

    scenario = run.get("scenario") or {}
    body = {
        "store_version": STORE_VERSION,
        "kind": KIND,
        "saved_at": _now(),
        "month": month,
        "question": question,
        "run": run,
    }
    with _session() as session:
        chosen = _unique(session, StressScenario, name or question[:80], owner)
        row = StressScenario(
            name=chosen,
            description=question[:2000],
            rationale=question[:2000],
            parameters=body,
            severity=_severity((run.get("delta") or {}).get("ecl_final_pct")),
            version=STORE_VERSION,
            status=SAVED,
            created_by=owner)
        session.add(row)
        session.flush()
        return _row(row)


def _severity(change_pct: Any) -> str:
    try:
        value = abs(float(change_pct))
    except (TypeError, ValueError):
        return "low"
    if value >= 25:
        return "severe"
    if value >= 10:
        return "high"
    if value >= 2:
        return "moderate"
    return "low"


def listing(*, owner: int | None = None, limit: int = 25) -> list[SavedRun]:
    from backend.models.platform import StressScenario

    with _session() as session:
        rows = (session.query(StressScenario)
                .filter(StressScenario.created_by == owner,
                        StressScenario.version == STORE_VERSION)
                .order_by(StressScenario.id.desc())
                .limit(max(1, min(limit, 100)))
                .all())
        return [_row(r) for r in rows]


def get(scenario_id: int, *, owner: int | None = None) -> SavedRun:
    from backend.models.platform import StressScenario

    with _session() as session:
        row = (session.query(StressScenario)
               .filter(StressScenario.id == int(scenario_id),
                       StressScenario.created_by == owner)
               .one_or_none())
        if row is None:
            raise KeyError(f"No saved What-If {scenario_id} belongs to you.")
        return _row(row)


def delete(scenario_id: int, *, owner: int | None = None) -> None:
    from backend.models.platform import StressScenario

    with _session() as session:
        row = (session.query(StressScenario)
               .filter(StressScenario.id == int(scenario_id),
                       StressScenario.created_by == owner)
               .one_or_none())
        if row is None:
            raise KeyError(f"No saved What-If {scenario_id} belongs to you.")
        session.delete(row)
