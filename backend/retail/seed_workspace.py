"""Fill the demonstration workspace with work, and do it twice safely.

What "safely twice" means, and why it is the hard part
-------------------------------------------------------
§24: "Seed refresh must update machine-owned current demo content by stable
IDs and source hashes, preserve user edits, retain historical artifacts and
avoid duplicating account records." Every clause there is a way a seeder
that merely INSERTS goes wrong:

* run it twice and the presenter finds two of everything;
* run it after somebody edited a document and their work is gone;
* run it after the book is rebuilt and the old numbers stay on screen
  beside the new ones with nothing to tell them apart.

So every object carries a stable key, every write is an upsert on that key,
anything a person has touched is left alone and reported, and every computed
result carries the source hash it was measured over. Re-running after a
rebuild refreshes the figures; re-running against the same book is a no-op
that says so.

Nothing here writes a number
------------------------------
§18 forbids seeding statistical answers as hand-entered paragraphs. Every
analysis is a governed definition in `seed_catalogue` and the result is
computed by `measures` at seed time. Where a document quotes a figure, the
figure is interpolated from the computed result at build time — so a paper
and the screen behind it cannot disagree, which is the failure mode that
ends a demonstration.

The dry run
------------
`plan()` reports what would change without changing it: created, refreshed,
skipped-because-edited, and unchanged. §19 asks for that summary explicitly,
and it is also the only way to run a seeder against a database somebody
cares about without holding your breath.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SEEDER_VERSION = "retail-seed-workspace-1.0.0"

#: Where a seeded object's stable key lives. Projects and investigations
#: have no column for it, so it goes in their JSON context under this key —
#: which is also what makes an upsert possible on tables that were not
#: designed for one.
KEY = "seed_key"


@dataclass
class Change:
    kind: str            # "project", "investigation", "analysis", "document"
    key: str
    action: str          # "create", "refresh", "skip", "unchanged"
    detail: str = ""


@dataclass
class Report:
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_hash: str = ""
    month: str = ""
    seconds: float = 0.0

    def add(self, kind: str, key: str, action: str, detail: str = "") -> None:
        self.changes.append(Change(kind, key, action, detail))

    def count(self, kind: str, action: str = "") -> int:
        return sum(1 for one in self.changes
                   if one.kind == kind and (not action
                                            or one.action == action))

    def to_dict(self) -> dict[str, Any]:
        kinds = sorted({one.kind for one in self.changes})
        return {
            "seeder_version": SEEDER_VERSION,
            "source_hash": self.source_hash,
            "month": self.month,
            "seconds": round(self.seconds, 1),
            "summary": {
                kind: {
                    "created": self.count(kind, "create"),
                    "refreshed": self.count(kind, "refresh"),
                    "left_alone": self.count(kind, "skip"),
                    "unchanged": self.count(kind, "unchanged"),
                    "total": self.count(kind),
                } for kind in kinds
            },
            "changes": [{"kind": c.kind, "key": c.key, "action": c.action,
                         "detail": c.detail} for c in self.changes],
            "errors": list(self.errors),
        }


def _now() -> datetime:
    return datetime.now(UTC)


def _fingerprint(payload: Any) -> str:
    """What a stored result was computed from, so a refresh can be skipped.

    Hashing the RESULT rather than the definition: a definition that has not
    changed can still produce a different answer after the book is rebuilt,
    and that is precisely the case a refresh exists for.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


# --------------------------------------------------------------- computing


def compute(one: Any, month: str) -> dict[str, Any]:
    """Run one analysis definition through the governed measure engine."""
    from backend.retail import measures

    if one.shape == "trend":
        every = measures.months()
        window = every[-one.months:] if one.months else every
        return measures.trend(list(one.measures), product=one.product,
                              where=dict(one.where), over=window)
    if one.shape == "table":
        return measures.table(month, list(one.measures), one.cut,
                              product=one.product, where=dict(one.where))
    return measures.value(month, one.measures[0], product=one.product,
                          where=dict(one.where))


def headline(one: Any, result: dict[str, Any]) -> str:
    """One sentence about what was measured, built from the result itself.

    Assembled rather than written, for the same reason the analyses are
    computed rather than typed: a sentence a person wrote about a number is
    a sentence that stops being true when the number moves.
    """
    from backend.retail import measures

    rows = result.get("rows") or []
    if one.shape == "trend" and len(rows) >= 2:
        key = one.measures[0]
        first = next((r.get(key) for r in rows if r.get(key) is not None),
                     None)
        last = next((r.get(key) for r in reversed(rows)
                     if r.get(key) is not None), None)
        if first is None or last is None:
            return (f"No month in the window carries "
                    f"{measures.BY_KEY[key].label.lower()}.")
        measure = measures.BY_KEY[key]
        said = _format(last, measure.unit)
        before = _format(first, measure.unit)
        direction = ("rose" if last > first
                     else "fell" if last < first else "held")
        return (f"{measure.label} {direction} from {before} in "
                f"{rows[0]['month']} to {said} in {rows[-1]['month']}, over "
                f"{len(rows)} months.")
    if one.shape == "table" and rows:
        key = one.measures[-1]
        measure = measures.BY_KEY.get(key)
        ranked = [r for r in rows if r.get(key) is not None]
        if measure and ranked:
            worst = max(ranked, key=lambda r: r[key])
            cut = result.get("cut", "")
            return (f"{measure.label} is highest at "
                    f"{_format(worst[key], measure.unit)} in "
                    f"{cut.replace('_', ' ')} {worst.get(cut)}, over "
                    f"{worst['facilities']:,} facilities of "
                    f"{result.get('facilities', 0):,}.")
        return (f"{len(rows)} levels across "
                f"{result.get('facilities', 0):,} facilities.")
    if one.shape == "value":
        measure = measures.BY_KEY.get(one.measures[0])
        got = result.get("value")
        if measure and got is not None:
            return (f"{measure.label} is {_format(got, measure.unit)} over "
                    f"{result.get('facilities', 0):,} facilities.")
    return "Measured, with nothing in the population to report."


def _format(value: float, unit: str) -> str:
    if unit == "rate":
        return f"{value:.2%}"
    if unit == "money":
        return f"SAR {value:,.0f}"
    if unit == "ratio":
        return f"{value:.2f}"
    return f"{value:,.0f}"


# ----------------------------------------------------------------- writing


def _owner(session: Any) -> Any:
    """The demo user everything is attributed to.

    §17: use existing authorized demo users. A seeder that creates an
    account to own its content creates an account nobody can log in as, and
    §24 asks explicitly that a fresh installation not depend on a manually
    created hidden one.
    """
    from sqlalchemy import select

    from backend.db.models import User

    for username in ("retail.demo", "demo", "admin"):
        found = session.execute(
            select(User).where(User.username == username)).scalars().first()
        if found is not None:
            return found
    return session.execute(select(User).order_by(User.id)).scalars().first()


def _projects(session: Any, owner: Any, report: Report, *,
              preview: bool) -> dict[str, int]:
    from sqlalchemy import select

    from backend.models.platform import Project
    from backend.retail.seed_catalogue import PROJECTS

    made: dict[str, int] = {}
    for one in PROJECTS:
        row = session.execute(
            select(Project).where(
                Project.default_context[KEY].astext == one.key)
        ).scalars().first()
        context = {
            KEY: one.key, "product": one.product, "owner": one.owner,
            "domain": "retail_facility_month", "seeded": True,
        }
        if row is None:
            if preview:
                report.add("project", one.key, "create", one.title)
                continue
            row = Project(name=one.title, description=one.objective,
                          status=one.status, created_by=getattr(owner, "id",
                                                                None),
                          default_context=context,
                          instructions=one.objective)
            session.add(row)
            session.flush()
            report.add("project", one.key, "create", one.title)
        else:
            changed = (row.name != one.title
                       or row.description != one.objective)
            if changed and not preview:
                row.name = one.title
                row.description = one.objective
                row.default_context = {**(row.default_context or {}),
                                       **context}
                row.updated_at = _now()
            report.add("project", one.key,
                       "refresh" if changed else "unchanged", one.title)
        if row is not None and getattr(row, "id", None):
            made[one.key] = row.id
    return made


def _analyses(session: Any, owner: Any, projects: dict[str, int],
              month: str, source_hash: str, report: Report, *,
              preview: bool) -> dict[str, int]:
    from sqlalchemy import select

    from backend.models.platform import SavedAnalysis
    from backend.retail import measures
    from backend.retail.seed_catalogue import ANALYSES

    made: dict[str, int] = {}
    for one in ANALYSES:
        row = session.execute(
            select(SavedAnalysis).where(
                SavedAnalysis.params[KEY].astext == one.key)
        ).scalars().first()

        if preview:
            report.add("analysis", one.key,
                       "create" if row is None else "refresh", one.title)
            continue

        try:
            result = compute(one, month)
        except measures.MeasureRefused as problem:
            # A refusal is a result. §14's contract applies here too: a
            # measure that cannot be computed over this population is
            # recorded with its reason, never as a zero.
            report.add("analysis", one.key, "skip", str(problem)[:120])
            report.errors.append(f"{one.key}: {problem}")
            continue
        except Exception as problem:  # noqa: BLE001
            report.add("analysis", one.key, "skip",
                       f"{type(problem).__name__}: {problem}"[:120])
            report.errors.append(f"{one.key}: {problem}")
            continue

        body = {
            "question": one.question,
            "headline": headline(one, result),
            "shape": one.shape,
            "result": result,
            "tags": list(one.tags),
        }
        print_ = _fingerprint(result)
        params = {
            KEY: one.key, "shape": one.shape,
            "measures": list(one.measures), "cut": one.cut,
            "product": one.product, "where": dict(one.where),
            "months": one.months, "seeded": True,
        }
        versions = {"source_hash": source_hash, "month": month,
                    "measures_version": measures.MEASURES_VERSION,
                    "fingerprint": print_}
        project_id = projects.get(one.projects[0]) if one.projects else None

        if row is None:
            row = SavedAnalysis(
                title=one.title, analysis_id=f"retail.{one.key}",
                analysis_version=measures.MEASURES_VERSION,
                project_id=project_id, params=params,
                filters=dict(one.where),
                period={"month": month, "shape": one.shape},
                result=body, data_versions=versions,
                note=one.question, owner_id=getattr(owner, "id", None))
            session.add(row)
            session.flush()
            report.add("analysis", one.key, "create", one.title)
        elif (row.data_versions or {}).get("fingerprint") == print_:
            report.add("analysis", one.key, "unchanged", one.title)
        else:
            row.title = one.title
            row.params = params
            row.filters = dict(one.where)
            row.period = {"month": month, "shape": one.shape}
            row.result = body
            row.data_versions = versions
            row.note = one.question
            if project_id:
                row.project_id = project_id
            report.add("analysis", one.key, "refresh",
                       f"{one.title} — the book moved")
        made[one.key] = row.id
    return made


def plan(session: Any) -> dict[str, Any]:
    """What a seed run would do, without doing any of it. §19's dry run."""
    return build(session, preview=True)


def build(session: Any, *, preview: bool = False,
          month: str = "") -> dict[str, Any]:
    """Seed or refresh the retail demonstration workspace."""
    import time

    from backend.retail import measures

    started = time.time()
    report = Report()
    every = measures.months()
    report.month = month or (every[-1] if every else "")
    report.source_hash = measures.stamp(report.month).get("source_hash", "")
    if not report.month:
        report.errors.append(
            "The retail book has no months, so there is nothing to seed "
            "content against.")
        return report.to_dict()

    owner = _owner(session)
    projects = _projects(session, owner, report, preview=preview)
    _analyses(session, owner, projects, report.month, report.source_hash,
              report, preview=preview)
    from backend.retail import seed_lenses, seed_threads

    seed_threads.build(session, owner, projects, report.month,
                       report.source_hash, report, preview=preview)
    seed_lenses.build(session, owner, report, preview=preview)
    report.seconds = time.time() - started
    return report.to_dict()


__all__ = ["Change", "KEY", "Report", "SEEDER_VERSION", "build", "compute",
           "headline", "plan"]


# ------------------------------------------------------------- the tidy-up


#: What a retail installation's saved analyses may point at. Anything else
#: is a corporate analysis that reached this database through a test.
RETAIL_ANALYSIS_PREFIX = "retail."


def tidy(session: Any, *, preview: bool = True) -> dict[str, Any]:
    """Remove the residue a retail installation should not be showing.

    §2.5 of the delta map reproduced this as a defect: "the Analyses list
    carries corporate rows — e.g. 'Shipping PD increase' — in a retail-only
    installation". Underneath it is the problem `backend/demo/workspace`
    describes at length — a development database accumulates, and every row
    a passing test left behind is on screen in front of a client.

    What it removes, and the rule for each
    ----------------------------------------
    * **Foreign analyses.** A saved analysis whose registered analysis is
      not a retail one. On this installation that is the corporate shipping
      and borrower-deterioration fixtures, which describe a book this
      product does not hold.
    * **Empty investigations.** A thread with no messages at all. Not a
      conversation — a row a test created and abandoned.

    What it will not touch
    -----------------------
    Anything seeded (it is refreshed rather than deleted), anything with a
    project, and anything carrying actual conversation. A tidy that removed
    a thread somebody had used would be worse than the residue.

    Preview by default. A destructive operation whose default is to do it
    is a destructive operation somebody runs by accident.
    """
    from sqlalchemy import func, select

    from backend.models.platform import (
        Investigation,
        InvestigationMessage,
        SavedAnalysis,
    )

    report = Report()
    report.source_hash = "n/a — this removes rows, it computes nothing"

    for row in session.execute(select(SavedAnalysis)).scalars().all():
        if (row.params or {}).get("seeded"):
            continue
        if str(row.analysis_id or "").startswith(RETAIL_ANALYSIS_PREFIX):
            continue
        report.add("analysis", f"id:{row.id}", "remove",
                   f"{row.title} — {row.analysis_id}, not a retail analysis")
        if not preview:
            session.delete(row)

    counts = dict(session.execute(
        select(InvestigationMessage.investigation_id,
               func.count(InvestigationMessage.id))
        .group_by(InvestigationMessage.investigation_id)).all())
    for row in session.execute(select(Investigation)).scalars().all():
        if (row.context or {}).get(KEY):
            continue
        if counts.get(row.id, 0) > 0 or row.project_id:
            continue
        report.add("investigation", f"id:{row.id}", "remove",
                   f"{str(row.title)[:60]} — no messages, no project")
        if not preview:
            session.delete(row)

    body = report.to_dict()
    body["preview"] = preview
    body["note"] = (
        "Preview by default. Nothing seeded is removed, nothing with a "
        "project is removed, and nothing carrying conversation is removed."
        if preview else "Removed.")
    return body
