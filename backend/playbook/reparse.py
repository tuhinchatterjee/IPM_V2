"""Stale sources, and re-reading them. §18.

The whole design in one sentence: the bytes are immutable, so a better reader
is a reason to read again, never a reason to ask the user to upload again.

What a parse revision records
-----------------------------
Which reader made it, against which chunk schema, what it produced, and what
it could not read. Every read writes one — the first upload, a retry after a
failure, a re-read after the reader improved. The previous revision is marked
superseded rather than deleted, so a document generated three months ago can
still be traced to the reading it was actually written from.

Staleness is computed, not stored
---------------------------------
A source is stale when its latest parse names a reader version behind the one
in force. That is a comparison against `ingest.version`, made when asked, so
deploying a better reader marks the affected sources stale without a migration
and without a background job rewriting rows.

A source with NO parse revision is stale too. Its reading exists, but nothing
records which reader produced it, and a reading whose provenance cannot be
established is not one to keep quoting. Re-reading it is free and settles the
question.

What a re-read is not
---------------------
It makes no provider call, costs nothing, and changes no document. It replaces
the CHUNKS — what the evidence ledger will draw on next time — and nothing
else. A report already written is not rewritten because its source was read
again; §16's governed refresh is where that decision belongs, and it is a
person's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.models.playbook import PlaybookSource, PlaybookSourceParse
from backend.playbook import ingest, store
from backend.playbook import repository as repo
from backend.playbook.ingest import version as pv

PARSED, PARTIAL, FAILED = "parsed", "partial", "failed"

#: Why a source needs reading again. Distinct reasons, because "re-read" with
#: no explanation is a button nobody presses.
BEHIND = "parser_improved"
UNRECORDED = "no_parse_revision"
FAILED_PARSE = "parse_failed"

REASON_LABELS = {
    BEHIND: "Read with an older version of the reader",
    UNRECORDED: "Read before parse revisions were recorded",
    FAILED_PARSE: "The last read failed",
}


@dataclass
class State:
    """Where one source's reading stands."""

    source_id: int
    filename: str
    format: str = ""
    revision: int = 0
    parser_version: str = ""
    schema_version: str = ""
    current_parser_version: str = ""
    status: str = ""
    chunk_count: int = 0
    stale: bool = False
    reason: str = ""
    reason_label: str = ""
    improvements: list[str] = field(default_factory=list)
    parsed_at: str = ""

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id, "filename": self.filename,
            "format": self.format, "revision": self.revision,
            "parser_version": self.parser_version,
            "schema_version": self.schema_version,
            "current_parser_version": self.current_parser_version,
            "status": self.status, "chunk_count": self.chunk_count,
            "stale": self.stale, "reason": self.reason,
            "reason_label": self.reason_label,
            "improvements": list(self.improvements),
            "parsed_at": self.parsed_at,
        }


# --------------------------------------------------------------------------
# Recording a parse
# --------------------------------------------------------------------------


def record(session, source: PlaybookSource, *, kind: str,
           result=None, failure: str = "") -> PlaybookSourceParse:
    """Write the revision this read produced, and supersede the last one.

    Called from every path that reads bytes. A failed read is recorded too:
    "this file was tried with reader 2 and could not be read" is information,
    and without it a retry loop cannot tell a transient failure from a file
    that will never parse.
    """
    previous = latest(session, source.id)
    for row in _all(session, source.id):
        row.superseded = True

    manifest = result.manifest.as_dict() if result is not None else {}
    row = PlaybookSourceParse(
        source_id=source.id,
        revision=(previous.revision + 1) if previous else 1,
        parser_version=pv.current(kind),
        schema_version=pv.SCHEMA_VERSION,
        status=(FAILED if failure else
                PARSED if manifest.get("complete") else PARTIAL),
        chunk_count=len(result.chunks) if result is not None else 0,
        manifest=manifest,
        failure_reason=failure,
        superseded=False,
    )
    session.add(row)
    session.flush()
    return row


def latest(session, source_id: int) -> PlaybookSourceParse | None:
    return (session.query(PlaybookSourceParse)
            .filter(PlaybookSourceParse.source_id == source_id)
            .order_by(PlaybookSourceParse.revision.desc()).first())


def history(session, source_id: int) -> list[PlaybookSourceParse]:
    """Every reading this source has had, oldest first. Lineage, preserved."""
    return (session.query(PlaybookSourceParse)
            .filter(PlaybookSourceParse.source_id == source_id)
            .order_by(PlaybookSourceParse.revision).all())


def _all(session, source_id: int) -> list[PlaybookSourceParse]:
    return (session.query(PlaybookSourceParse)
            .filter(PlaybookSourceParse.source_id == source_id).all())


# --------------------------------------------------------------------------
# Is it stale
# --------------------------------------------------------------------------


def _format_of(source: PlaybookSource) -> str:
    """Which reader governs this source, from what it actually is.

    Taken from the stored parse manifest where one exists, because that is
    what the reader itself said the bytes were. The filename is the fallback
    and is the weaker answer — a previous report saved as `.txt` is still a
    Word document.
    """
    stored = (source.manifest or {}).get("format")
    if stored:
        return stored
    suffix = (source.filename or "").rsplit(".", 1)[-1].lower()
    return {"docx": "docx", "pdf": "pdf", "xlsx": "xlsx", "xlsm": "xlsx",
            "csv": "csv", "pptx": "pptx"}.get(suffix, suffix)


def state(session, source: PlaybookSource) -> State:
    """Where this source's reading stands, and why."""
    kind = _format_of(source)
    row = latest(session, source.id)
    built = State(source_id=source.id, filename=source.filename, format=kind,
                  current_parser_version=pv.current(kind))

    if row is None:
        built.stale = True
        built.reason = UNRECORDED
        built.reason_label = REASON_LABELS[UNRECORDED]
        built.status = source.status or ""
        return built

    built.revision = row.revision
    built.parser_version = row.parser_version
    built.schema_version = row.schema_version
    built.status = row.status
    built.chunk_count = row.chunk_count
    built.parsed_at = row.created_at.isoformat() if row.created_at else ""

    if row.status == FAILED:
        built.stale = True
        built.reason = FAILED_PARSE
        built.reason_label = REASON_LABELS[FAILED_PARSE]
    elif pv.is_stale(kind, parser_version=row.parser_version,
                     schema_version=row.schema_version):
        built.stale = True
        built.reason = BEHIND
        built.reason_label = REASON_LABELS[BEHIND]
        built.improvements = pv.what_changed(
            kind, parser_version=row.parser_version)
    return built


def states(session, workspace_id: int) -> list[State]:
    """Every source in the workspace, in upload order."""
    return [state(session, s) for s in repo.sources(session, workspace_id)]


def stale(session, workspace_id: int) -> list[State]:
    return [s for s in states(session, workspace_id) if s.stale]


def summary(session, workspace_id: int) -> dict:
    """§17's line: "1 source needs re-read"."""
    all_states = states(session, workspace_id)
    needing = [s for s in all_states if s.stale]
    return {
        "sources": len(all_states),
        "current": len(all_states) - len(needing),
        "needs_reread": len(needing),
        "message": _message(len(all_states), len(needing)),
        "items": [s.as_dict() for s in all_states],
    }


def _message(total: int, needing: int) -> str:
    if not total:
        return "No sources attached"
    if not needing:
        return f"{total} source{'s' if total != 1 else ''} current"
    return (f"{needing} source{'s' if needing != 1 else ''} "
            f"need{'' if needing != 1 else 's'} re-read")


# --------------------------------------------------------------------------
# Re-reading
# --------------------------------------------------------------------------


class BytesGone(repo.NotFound):
    """The stored bytes are missing, so there is nothing to read again."""


def reread(session, scope: repo.Scope, source_id: int) -> State:
    """Read a source's stored bytes again with the reader in force now.

    No upload, no provider call, no charge. The chunks are replaced and a new
    parse revision is written; every earlier revision stays, marked superseded.
    """
    from backend.playbook import service

    source = service.get_source(session, scope, source_id)
    if not source.bytes_path or not store.exists(source.bytes_path):
        raise BytesGone(
            f"The stored bytes for {source.filename} are gone, so it cannot "
            "be read again. Upload it once more.")

    content = store.read(source.bytes_path)
    source.status = "parsing"
    source.failure_reason = ""
    session.flush()

    try:
        accepted, result = ingest.read(source.filename, content)
    except (ingest.UnreadableSource, ingest.RejectedUpload) as exc:
        source.status = "failed"
        source.failure_reason = str(exc)
        source.manifest = {"format": _format_of(source), "complete": False,
                           "read": [], "skipped": [], "warnings": [str(exc)]}
        record(session, source, kind=_format_of(source), failure=str(exc))
        session.flush()
        return state(session, source)

    repo.set_chunks(session, source, result.chunks)
    source.manifest = result.manifest.as_dict()
    source.status = PARSED if result.manifest.complete else PARTIAL
    record(session, source, kind=accepted.kind, result=result)
    session.flush()
    return state(session, source)


def reread_stale(session, scope: repo.Scope, workspace_id: int) -> dict:
    """Re-read every stale source in one workspace. §18's workspace action.

    One failure does not stop the rest: a file whose bytes are gone is
    reported and the others are still brought up to date.
    """
    repo.get_workspace(session, scope, workspace_id)
    results, failures = [], []
    for candidate in stale(session, workspace_id):
        try:
            results.append(reread(session, scope,
                                  candidate.source_id).as_dict())
        except BytesGone as exc:
            failures.append({"source_id": candidate.source_id,
                             "filename": candidate.filename,
                             "reason": str(exc)})
    return {"reread": results, "failed": failures,
            **summary(session, workspace_id)}
