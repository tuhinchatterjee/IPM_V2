#!/usr/bin/env python
"""Thirty real Analyses, computed rather than composed. Part 3.

    python scripts/seed_analyses.py            seed what is missing
    python scripts/seed_analyses.py --check    report only; change nothing
    python scripts/seed_analyses.py --force    recompute and replace
    python scripts/seed_analyses.py --json     machine-readable result

The defect this exists to fix
-----------------------------
The Analyses list held 564 rows. Four distinct analysis types between them,
443 of those one repeated `portfolio_summary`, and 236 with an EMPTY result —
saved Analyses that open onto nothing. A list that long and that thin is worse
than an empty one: it looks like a working installation and cannot survive
being clicked on.

What this seeds is the opposite shape. One Analysis per registered runnable
function, each computed by the real engine against the governed book, each
with a result, a period, the datasets it read and the certification of the
function that produced it. Twenty-nine functions are registered; the thirtieth
is `portfolio_trend` run over a second window, so the set demonstrates that
these are parameterised runs and not one-shot fixtures.

Nothing here invents a figure
------------------------------
Every row comes from `runner.run_analysis`, which is the same path the API and
the planner use. An analysis that fails to run is REPORTED as failed and is
not saved; there is no placeholder result, no "0", and no row that claims to
be an analysis without being one. A seeded list that quietly contains three
fabrications is not worth the twenty-seven real ones beside it.

Idempotent
----------
A seeded Analysis is marked in its note with SEED_MARKER. Re-running replaces
the previous generation rather than adding a second, so the list does not grow
by thirty every time somebody bootstraps.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: How a seeded Analysis identifies itself, so re-seeding can replace rather
#: than accumulate, and so a reader can tell demonstration content from a run
#: somebody actually asked for.
SEED_MARKER = "SYNTHETIC_DEMO seeded analysis"

#: The thirtieth. Every registered function gets one run at the default window;
#: this one gets a second, longer window, so the set shows a parameterised run
#: rather than thirty one-shot fixtures.
SECOND_WINDOW = ("portfolio_trend", {"n_periods": 8})

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_CANNOT_RUN = 2


@dataclass
class Seeded:
    """One attempt, and what came of it."""

    analysis_id: str
    title: str
    status: str = "pending"
    saved_id: int | None = None
    rows: int = 0
    period: str = ""
    certification: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"analysis_id": self.analysis_id, "title": self.title,
                "status": self.status, "saved_id": self.saved_id,
                "rows": self.rows, "period": self.period,
                "certification": self.certification, "error": self.error[:300]}


@dataclass
class Report:
    seeded: list[Seeded] = field(default_factory=list)
    removed: int = 0
    error: str = ""

    @property
    def succeeded(self) -> list[Seeded]:
        return [s for s in self.seeded if s.status == "saved"]

    @property
    def failed(self) -> list[Seeded]:
        return [s for s in self.seeded if s.status == "failed"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.error,
            "attempted": len(self.seeded),
            "saved": len(self.succeeded),
            "failed": len(self.failed),
            "replaced": self.removed,
            "analyses": [s.to_dict() for s in self.seeded],
        }


def _title(contract: Any) -> str:
    """What the Analysis is called in the list.

    The function's own name, which is written for a credit officer. Inventing
    a second name here would put two names on the same thing.
    """
    return str(getattr(contract, "name", "") or getattr(contract, "id", ""))


def _rows_in(result: Any) -> int:
    if result is None:
        return 0
    for attr in ("row_count", "rows"):
        found = getattr(result, attr, None)
        if isinstance(found, int):
            return found
        if isinstance(found, list):
            return len(found)
    return 0


def _existing_seeded() -> list[int]:
    from backend.db.engine import get_session
    from backend.models.platform import SavedAnalysis

    with get_session() as session:
        return [r.id for r in session.query(SavedAnalysis)
                .filter(SavedAnalysis.note.like(f"%{SEED_MARKER}%")).all()]


def _plan() -> list[tuple[str, dict[str, Any]]]:
    """Every runnable analysis once, plus the second window."""
    from backend.engine.registry import get_registry

    ids = [a.contract.id for a in get_registry().runnable()]
    plan: list[tuple[str, dict[str, Any]]] = [(one, {}) for one in ids]
    second_id, second_params = SECOND_WINDOW
    if second_id in ids:
        plan.append((second_id, second_params))
    return plan


def run(*, check: bool = False, force: bool = False) -> Report:
    report = Report()
    try:
        from backend.config import settings
    except Exception as e:  # noqa: BLE001
        report.error = f"Configuration could not be read: {e}"
        return report
    if not settings.has_database:
        report.error = "No database is configured, so nothing can be seeded."
        return report

    from backend.engine.runner import run_analysis
    from backend.services import analyses as svc

    existing = _existing_seeded()
    plan = _plan()

    if check:
        for analysis_id, _params in plan:
            report.seeded.append(Seeded(analysis_id=analysis_id,
                                        title=analysis_id, status="would-run"))
        report.removed = len(existing)
        return report

    if existing and not force:
        # Already seeded. Replacing on every call would churn ids that a
        # bookmark or a project may point at.
        for one in plan:
            report.seeded.append(Seeded(analysis_id=one[0], title=one[0],
                                        status="already-seeded"))
        return report

    for saved_id in existing:
        try:
            svc.delete(saved_id)
            report.removed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ! could not remove seeded analysis {saved_id}: {e}",
                  file=sys.stderr)

    for analysis_id, params in plan:
        entry = Seeded(analysis_id=analysis_id, title=analysis_id)
        report.seeded.append(entry)
        try:
            found = run_analysis(analysis_id, params=params, period="latest")
        except Exception as e:  # noqa: BLE001
            entry.status, entry.error = "failed", f"{type(e).__name__}: {e}"
            continue

        if found.status != "succeeded" or found.result is None:
            entry.status = "failed"
            entry.error = found.error or "the engine returned no result"
            continue

        from backend.engine.registry import get_registry
        contract = get_registry().contract(analysis_id)
        entry.title = _title(contract)
        entry.certification = found.certification
        entry.rows = _rows_in(found.result)
        entry.period = str((found.context or {}).get("period") or "")

        view = svc.save(
            analysis_id=analysis_id,
            title=entry.title,
            result=found.result.to_dict(),
            params=dict(found.params or {}),
            period={"period": entry.period},
            data_versions=dict(found.node_hashes or {}),
            note=SEED_MARKER,
        )
        entry.saved_id = view.id if hasattr(view, "id") else None
        entry.status = "saved"

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run(check=args.check, force=args.force)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.error:
            print(f"! {report.error}")
        if report.removed:
            print(f"  replaced {report.removed} previously seeded analysis(es)")
        for one in report.seeded:
            if one.status == "saved":
                print(f"  ok     {one.analysis_id:34s} {one.rows:6d} row(s)  "
                      f"{one.period}  {one.certification}")
            elif one.status == "failed":
                print(f"  FAILED {one.analysis_id:34s} {one.error[:90]}")
        print(f"\n{len(report.succeeded)} saved, {len(report.failed)} failed, "
              f"of {len(report.seeded)} attempted.")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_OK if not report.failed else EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
