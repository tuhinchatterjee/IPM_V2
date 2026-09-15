"""One chronological record of everything that happened to a document. §20.

Why this is assembled rather than stored
----------------------------------------
Every governed object already keeps its own append-only `history`, versions
carry their own creation record, sources carry their parse revisions, and a
metric binding records who confirmed it and when. Writing a second, separate
event log beside all of that would create a thing that can disagree with the
rows it describes — and the one that disagrees is always the one somebody
reads.

So this module reads those trails and merges them. It cannot drift, because
there is nothing to drift from: delete a finding and its entries leave the
feed with it.

What an event is
----------------
`{at, kind, title, detail, actor, link, ids}`. `kind` is closed, so a reader
can filter on it and a renderer can choose an icon without string-matching a
sentence. `actor` is the person who did it, or "" where the event had no human
actor — never "system" dressed up as a name.

Ordering is newest first, on the timestamp the source rows recorded. Entries
with no timestamp at all sort last rather than being dropped: an event that
happened is worth showing even when nobody wrote down when.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from backend.models.playbook import (
    PlaybookAction,
    PlaybookDecision,
    PlaybookDocumentSection,
    PlaybookFinding,
    PlaybookMetricBinding,
)
from backend.playbook import repository as repo
from backend.playbook.intelligence import governance as gov
from backend.playbook.intelligence import service as svc

# Event kinds. Closed, so a filter and an icon can key on them.
VERSION = "version"
SOURCE = "source"
PARSE = "parse"
BINDING = "binding"
SECTION = "section"
FINDING = "finding"
DECISION = "decision"
ACTION = "action"

KINDS = (VERSION, SOURCE, PARSE, BINDING, SECTION, FINDING, DECISION, ACTION)

KIND_LABELS = {
    VERSION: "Version",
    SOURCE: "Source",
    PARSE: "Parse",
    BINDING: "Metric link",
    SECTION: "Section",
    FINDING: "Finding",
    DECISION: "Decision",
    ACTION: "Action",
}


@dataclass
class Event:
    at: str
    kind: str
    title: str
    detail: str = ""
    actor: str = ""
    #: Which dashboard tab answers "show me this". Never a URL: the frontend
    #: owns routing, and a backend that hard-codes one breaks on every rename.
    link: str = ""
    ids: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"at": self.at, "kind": self.kind,
                "kind_label": KIND_LABELS.get(self.kind, self.kind),
                "title": self.title, "detail": self.detail,
                "actor": self.actor, "link": self.link, "ids": dict(self.ids)}


def _stamp(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _entries(row, *, kind: str, subject: str, link: str,
             ids: dict) -> list[Event]:
    """Turn one governed row's append-only `history` into events."""
    out = []
    for entry in (row.history or []):
        act = str(entry.get("act", "changed"))
        before, after = entry.get("from", ""), entry.get("to", "")
        if before and after:
            detail = f"{before} → {after}"
        else:
            detail = after or before or ""
        if entry.get("reason"):
            detail = f"{detail} · {entry['reason']}" if detail \
                else str(entry["reason"])
        actor = str(entry.get("actor", ""))
        out.append(Event(
            at=str(entry.get("at", "")), kind=kind,
            title=f"{subject} {act.replace('_', ' ')}",
            detail=detail,
            # A row whose act was performed by a system actor says so rather
            # than showing a name nobody can be held to.
            actor="" if actor.lower() in gov.SYSTEM_ACTORS else actor,
            link=link, ids=dict(ids)))
    return out


def events(session, workspace_id: int) -> list[Event]:
    """Everything that happened here, newest first."""
    out: list[Event] = []
    artifact = svc._current_artifact(session, workspace_id)

    if artifact is not None:
        for version in repo.versions(session, artifact.id):
            formats = sorted(f.format for f in repo.files(session, version.id))
            out.append(Event(
                at=_stamp(version.created_at), kind=VERSION,
                title=f"Version {version.version} created",
                detail=version.change_summary or "",
                # A seeded version says so rather than being attributed to a
                # model that did not write it. §13.
                actor="" if version.origin == "seed_fixture"
                else (f"user:{version.created_by}" if version.created_by
                      else ""),
                link="history",
                ids={"artifact_id": artifact.id, "version": version.version,
                     "formats": formats, "origin": version.origin}))

        for row in (session.query(PlaybookDocumentSection)
                    .filter(PlaybookDocumentSection.artifact_id == artifact.id)
                    .all()):
            out += _entries(row, kind=SECTION, subject=row.heading or "Section",
                            link="sections",
                            ids={"section_key": row.section_key})

    from backend.playbook import reparse

    for source in repo.sources(session, workspace_id):
        out.append(Event(
            at=_stamp(source.created_at), kind=SOURCE,
            title=f"{source.filename} uploaded",
            detail=f"{source.source_role.replace('_', ' ')}",
            link="sources", ids={"source_id": source.id}))
        for parse in reparse.history(session, source.id):
            out.append(Event(
                at=_stamp(parse.created_at), kind=PARSE,
                title=(f"{source.filename} read"
                       + (f" again (revision {parse.revision})"
                          if parse.revision > 1 else "")),
                detail=(parse.failure_reason or
                        f"parser {parse.parser_version}, "
                        f"{parse.chunk_count} evidence item(s)"),
                link="sources",
                ids={"source_id": source.id, "revision": parse.revision,
                     "parser_version": parse.parser_version}))

    for binding in (session.query(PlaybookMetricBinding)
                    .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                    .all()):
        if binding.confirmed_at is None:
            continue
        out.append(Event(
            at=_stamp(binding.confirmed_at), kind=BINDING,
            title=f"{binding.label or binding.metric_id} link confirmed",
            detail=(f"{binding.source_locator} → {binding.metric_id}"
                    if binding.source_locator else binding.metric_id),
            actor=binding.confirmed_by, link="metrics",
            ids={"binding_id": binding.id, "metric_id": binding.metric_id}))

    for finding in (session.query(PlaybookFinding)
                    .filter(PlaybookFinding.workspace_id == workspace_id)
                    .all()):
        out += _entries(finding, kind=FINDING,
                        subject=finding.reference or finding.title,
                        link="findings", ids={"finding_id": finding.id})

    for decision in (session.query(PlaybookDecision)
                     .filter(PlaybookDecision.workspace_id == workspace_id)
                     .all()):
        out += _entries(decision, kind=DECISION,
                        subject=decision.reference or "Decision",
                        link="decisions", ids={"decision_id": decision.id})

    for action in (session.query(PlaybookAction)
                   .filter(PlaybookAction.workspace_id == workspace_id).all()):
        out += _entries(action, kind=ACTION,
                        subject=action.reference or action.title,
                        link="decisions", ids={"action_id": action.id})

    # Newest first. An entry with no timestamp sorts last rather than being
    # dropped: something that happened is worth showing even when nobody wrote
    # down when it did.
    return sorted(out, key=lambda e: (e.at != "", e.at), reverse=True)


def feed(session, workspace_id: int, *, kinds: list[str] | None = None,
         limit: int = 200) -> dict:
    """The history tab's payload."""
    everything = events(session, workspace_id)
    wanted = [e for e in everything
              if not kinds or e.kind in kinds]
    return {
        "total": len(everything),
        "shown": len(wanted[:limit]),
        "kinds": [{"kind": k, "label": KIND_LABELS[k],
                   "count": sum(1 for e in everything if e.kind == k)}
                  for k in KINDS],
        "events": [e.as_dict() for e in wanted[:limit]],
    }
