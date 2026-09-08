"""
The exported-analysis library. Playbook §4, §5.

Creating an export, and finding one again. The two rules that make this a
library rather than a list:

**Only explicit exports are in it.** There is no path here that scans a
module's threads or picks up recently-viewed results. A row exists because
somebody pressed Export to Playbook, or because it is a clearly labelled
demonstration fixture. "Saved in a module" and "exported to Playbook" are
different states and the backend is where that distinction has to be enforced —
a caller who skips the picker and posts an id gets the same answer as one whose
id does not exist.

**Re-exporting is idempotent.** The unique constraint on
`(export_id, content_hash)` means the same snapshot of the same analysis lands
once however many times the button is pressed. A CHANGED analysis makes a new
revision, and evidence a report already cites keeps saying what it said.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, or_, select

from backend.exports import playbook_contract as contract
from backend.models.playbook import AnalysisExport, AnalysisExportRevision
from backend.playbook.repository import NotFound, Scope

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    export_id: int
    revision_id: int
    revision: int
    created: bool
    #: True when an identical snapshot already existed, so nothing was written.
    duplicate: bool = False


def create(session, scope: Scope, snapshot: contract.Snapshot, *,
           seed_version: str = "") -> ExportResult:
    """Persist one exported analysis, idempotently.

    Exporting does not remove or alter the source analysis. It creates a
    self-contained snapshot that stays useful when the user leaves the screen it
    came from.
    """
    snapshot.validate()
    digest = snapshot.content_hash()

    key = _identity(snapshot)
    export = session.execute(
        select(AnalysisExport).where(
            AnalysisExport.tenant == scope.tenant,
            AnalysisExport.source_module == snapshot.source_module,
            AnalysisExport.source_ref["identity"].astext == key,
        )
    ).scalars().first()

    if export is None:
        ref = dict(snapshot.source_ref)
        ref["identity"] = key
        export = AnalysisExport(
            tenant=scope.tenant, owner_id=scope.user_id,
            source_module=snapshot.source_module, source_ref=ref,
            title=snapshot.title, tags=list(snapshot.tags),
            report_family=snapshot.report_family,
            reporting_period=snapshot.reporting_period,
            insight=snapshot.insight, demo_origin=snapshot.demo_origin,
            seed_version=seed_version,
        )
        session.add(export)
        session.flush()

    existing = session.execute(
        select(AnalysisExportRevision).where(
            AnalysisExportRevision.export_id == export.id,
            AnalysisExportRevision.content_hash == digest,
        )
    ).scalars().first()
    if existing is not None:
        return ExportResult(export.id, existing.id, existing.revision,
                            created=False, duplicate=True)

    highest = session.execute(
        select(func.max(AnalysisExportRevision.revision))
        .where(AnalysisExportRevision.export_id == export.id)
    ).scalar() or 0

    revision = AnalysisExportRevision(
        export_id=export.id, revision=highest + 1,
        schema_version=contract.SCHEMA_VERSION, payload=snapshot.payload(),
        content_hash=digest, source_revision=snapshot.source_revision,
        origin="demo_fixture" if snapshot.demo_origin else "user",
        exported_by=scope.user_id,
    )
    session.add(revision)
    session.flush()

    # The family's card shows the newest snapshot's headline.
    export.title = snapshot.title or export.title
    export.insight = snapshot.insight or export.insight
    export.reporting_period = snapshot.reporting_period or export.reporting_period
    export.updated_at = func.now()
    session.flush()
    return ExportResult(export.id, revision.id, revision.revision, created=True)


def _identity(snapshot: contract.Snapshot) -> str:
    """What makes two exports the same analysis rather than two analyses.

    The source ids plus the exported scope. Two exports of the same run at
    different scopes are genuinely different evidence and are kept apart.
    """
    ref = snapshot.source_ref or {}
    parts = [str(ref.get(k, "")) for k in
             ("run_id", "thread_id", "result_id", "lens_id", "report_id",
              "borrower_id", "scenario_id")]
    return "|".join(parts) + "|" + snapshot.scope_kind


@dataclass
class Card:
    """What the library shows before anything is opened."""

    export_id: int
    revision_id: int
    revision: int
    title: str
    source_module: str
    reporting_period: str
    insight: str
    tags: list[str]
    demo_origin: bool
    exported_at: str
    revisions: int

    def as_dict(self) -> dict:
        return {
            "export_id": self.export_id, "revision_id": self.revision_id,
            "revision": self.revision, "title": self.title,
            "source_module": self.source_module,
            "reporting_period": self.reporting_period, "insight": self.insight,
            "tags": list(self.tags), "demo": self.demo_origin,
            "exported_at": self.exported_at, "revisions": self.revisions,
        }


def browse(session, scope: Scope, *, query: str = "", modules: list[str] | None = None,
           period: str = "", sort: str = "recent", limit: int = 24,
           offset: int = 0) -> tuple[list[Card], int]:
    """Search, filter and page the library. Returns cards and a total."""
    stmt = select(AnalysisExport).where(AnalysisExport.tenant == scope.tenant)
    if modules:
        stmt = stmt.where(AnalysisExport.source_module.in_(modules))
    if period:
        stmt = stmt.where(AnalysisExport.reporting_period == period)
    if query:
        like = f"%{query.lower()}%"
        stmt = stmt.where(or_(
            func.lower(AnalysisExport.title).like(like),
            func.lower(AnalysisExport.insight).like(like),
        ))

    total = session.execute(
        select(func.count()).select_from(stmt.subquery())).scalar() or 0

    order = {
        "recent": AnalysisExport.updated_at.desc(),
        "oldest": AnalysisExport.updated_at.asc(),
        "title": AnalysisExport.title.asc(),
        "module": AnalysisExport.source_module.asc(),
    }.get(sort, AnalysisExport.updated_at.desc())
    rows = list(session.execute(
        stmt.order_by(order, AnalysisExport.id.desc())
        .limit(limit).offset(offset)).scalars())

    cards: list[Card] = []
    for export in rows:
        revisions = sorted(export.revisions, key=lambda r: r.revision)
        if not revisions:
            continue
        latest = revisions[-1]
        cards.append(Card(
            export_id=export.id, revision_id=latest.id, revision=latest.revision,
            title=export.title, source_module=export.source_module,
            reporting_period=export.reporting_period, insight=export.insight,
            tags=list(export.tags or []), demo_origin=export.demo_origin,
            exported_at=latest.exported_at.isoformat() if latest.exported_at else "",
            revisions=len(revisions),
        ))
    return cards, total


def preview(session, scope: Scope, revision_id: int) -> dict:
    """The full contents of one snapshot.

    A preview is the analysis, not a title and a sentence: the question, the
    narrative, the tables, the chart data, the scope, the caveats and the
    provenance. §4 is explicit that a preview showing only a summary is not one.
    """
    revision = session.get(AnalysisExportRevision, revision_id)
    if revision is None:
        raise NotFound(f"No exported analysis revision {revision_id}.")
    export = session.get(AnalysisExport, revision.export_id)
    if export is None or export.tenant != scope.tenant:
        raise NotFound(f"No exported analysis revision {revision_id}.")

    newer = [r.revision for r in export.revisions if r.revision > revision.revision]
    payload = dict(revision.payload or {})
    payload["export_id"] = export.id
    payload["revision_id"] = revision.id
    payload["revision"] = revision.revision
    payload["content_hash"] = revision.content_hash
    payload["demo"] = export.demo_origin
    # A newer snapshot must be surfaced, never silently substituted: §5 requires
    # the user to choose it rather than have a report change underneath them.
    payload["newer_revision_available"] = max(newer) if newer else None
    return payload


def latest_revision_id(session, scope: Scope, export_id: int) -> int:
    export = session.get(AnalysisExport, export_id)
    if export is None or export.tenant != scope.tenant:
        raise NotFound(f"No exported analysis {export_id}.")
    revisions = sorted(export.revisions, key=lambda r: r.revision)
    if not revisions:
        raise NotFound(f"Exported analysis {export_id} has no revision.")
    return revisions[-1].id


def counts_by_module(session, scope: Scope) -> dict[str, int]:
    rows = session.execute(
        select(AnalysisExport.source_module, func.count())
        .where(AnalysisExport.tenant == scope.tenant)
        .group_by(AnalysisExport.source_module)
    ).all()
    return {module: count for module, count in rows}
