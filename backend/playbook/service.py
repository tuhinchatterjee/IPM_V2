"""
Playbook, end to end. Playbook §6, §9, §10, §11.

The order of operations for one authoring request, in one place, so that the
sequence is reviewable rather than distributed across a router, a worker and a
provider wrapper.

    accept and read the sources        (ingest — locators and an honest manifest)
    assemble the evidence ledger       (only what was attached; gaps recorded)
    ask the author to write            (prose and structure; never a figure)
    check the draft against evidence   (grounding — unsupported figures removed)
    render the files                   (skill output, or local from the same doc)
    open every file and check it       (validation — nothing is ready untested)
    write an immutable version         (only now, and only if validation held)

Two decisions in that list are worth stating plainly.

**Grounding runs before rendering, and can invalidate a Skill's file.** The
document Skills write their files during the same provider turn that produces
the prose. If grounding then removes an unsupported figure, the file the Skill
wrote no longer matches the document — so it is discarded and the corrected
document is rendered locally instead. The alternative would be shipping a Word
file containing a number the chat has already retracted.

**A version is written last.** A failed generation produces no version, so the
previous good one is still current and still downloadable. There is no such
thing here as a "completed" version whose files do not open.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.playbook import (
    capabilities,
    documents,
    grounding,
    ingest,
    merge,
    prompts,
    provider,
    render,
    reparse,
    review,
    store,
    validate,
)
from backend.playbook import document as D
from backend.playbook import evidence as ev
from backend.playbook import repository as repo
from backend.playbook.intelligence import adopt

logger = logging.getLogger(__name__)

#: What a report is rendered into by default. PowerPoint is produced on request
#: rather than always, because a deck nobody asked for is noise.
DEFAULT_FORMATS = ("docx", "pdf")


@dataclass
class Outcome:
    """What one authoring run produced."""

    workspace_id: int
    artifact_id: int | None = None
    version_id: int | None = None
    version: int = 0
    document: D.Document | None = None
    files: dict[str, bytes] = field(default_factory=dict)
    validations: dict[str, validate.Validation] = field(default_factory=dict)
    #: Every requested format and what became of it, delivered or not. `files`
    #: holds only the ones with real bytes, so a caller that iterates it can
    #: never hand out a download for a format that failed.
    formats: dict = field(default_factory=dict)
    #: Suspected issues in the draft, with where they are. Recorded beside the
    #: document rather than edited out of it: chapter 16 wants "Draft created
    #: — 2 review items", not "nothing saved".
    review_items: list[dict] = field(default_factory=list)
    #: Which path was chosen to make this artifact, and why.
    document_path: dict = field(default_factory=dict)
    #: What the model ATTEMPTED: the first pass, whose findings name every
    #: unsupported figure it wrote and what was done about it. `ok` is False
    #: when the draft reached for something the evidence did not support,
    #: which is a fact about the draft and is kept in the audit record.
    grounding: grounding.GroundingResult | None = None
    renderer: str = ""
    #: For a scoped edit: the heading that was actually revised, and any
    #: sections the model changed without being asked. The merge discards
    #: those; naming them is how the user learns it happened.
    scoped_to: str = ""
    rejected_sections: list[str] = field(default_factory=list)
    #: Named separately so they are never confused. Authoring is the provider
    #: call; rendering is deterministic and local.
    authoring_ms: int = 0
    render_ms: int = 0
    provider_ms: int = 0
    turns: int = 0
    tool_calls: int = 0
    model_served: str = ""
    request_ids: list[str] = field(default_factory=list)
    milestones: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: What writing this version changed in the dashboard: how many sections
    #: it now has, which changed, whose sign-off had to be reopened, how many
    #: metric readings were frozen. Filled in by the projection AFTER the
    #: version has committed, so it is empty on the delivery path and stays
    #: empty when the projection fails.
    adoption: dict = field(default_factory=dict)
    #: What the status projection needs in order to catch up with this
    #: version, once it has been committed. The projection runs in its own
    #: session and may fail without affecting anything recorded here.
    pending_projection: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.version_id) and all(v.ok for v in self.validations.values())


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def add_source(session, scope: repo.Scope, workspace_id: int, *,
               filename: str, content: bytes,
               source_role: str = "supporting"):
    """Validate, store, parse and index one uploaded document.

    Parsing happens on upload so the user sees status and gaps immediately, but
    it does NOT start a generation: §4 is explicit that uploading a file is not
    a request to write a report.
    """
    ws = repo.get_workspace(session, scope, workspace_id)
    accepted = ingest.accept(filename, content)

    source = repo.add_source(
        session, ws.id, scope, filename=store.safe_filename(filename),
        mime=accepted.mime, sha256=store.sha256(content),
        size_bytes=accepted.size_bytes, source_role=source_role,
    )
    stored = store.put_source(ws.id, source.id, filename, content)
    source.bytes_path = stored.relative

    source.status = "parsing"
    session.flush()
    try:
        _, result = ingest.read(filename, content)
    except ingest.UnreadableSource as exc:
        source.status = "failed"
        source.failure_reason = str(exc)
        source.manifest = {"format": accepted.kind, "complete": False,
                           "read": [], "skipped": [], "warnings": [str(exc)]}
        reparse.record(session, source, kind=accepted.kind, failure=str(exc))
        session.flush()
        return source

    repo.set_chunks(session, source, result.chunks)
    source.manifest = result.manifest.as_dict()
    source.status = "parsed" if result.manifest.complete else "partial"
    # Which reader produced this reading, against which chunk schema. §18: a
    # reading whose provenance is not recorded is one nobody can later tell
    # apart from a better one.
    reparse.record(session, source, kind=accepted.kind, result=result)
    session.flush()
    return source


def get_source(session, scope: repo.Scope, source_id: int):
    """One source, or NotFound, scoped to the caller's tenant."""
    from backend.models.playbook import PlaybookSource

    source = session.get(PlaybookSource, source_id)
    if source is None:
        raise repo.NotFound(f"No source {source_id}.")
    repo.get_workspace(session, scope, source.workspace_id)
    return source


def correct_source(session, scope: repo.Scope, source_id: int, *,
                   source_role: str = "", reporting_period: str | None = None):
    """Let the user overrule what the parser decided about a file.

    Two things are recorded, not one: the new value, and that a PERSON set it.
    A role the user corrected must not be quietly re-inferred on the next
    upload of the same file, and a reader of the evidence ledger should be able
    to tell an inference from an instruction.
    """
    from backend.models.playbook import SOURCE_ROLES

    source = get_source(session, scope, source_id)
    if source_role:
        if source_role not in SOURCE_ROLES:
            raise repo.Invalid(
                f"'{source_role}' is not a source role. Expected one of: "
                + ", ".join(SOURCE_ROLES))
        source.source_role = source_role
        source.role_set_by = "user"
        # The parser's confidence described the parser's guess. It says nothing
        # about a value a person typed, so it goes rather than misleading.
        source.role_confidence = ""
    if reporting_period is not None:
        source.reporting_period = reporting_period[:32]
    session.flush()
    return source


def retry_source(session, scope: repo.Scope, source_id: int):
    """Parse a stored file again.

    The bytes are already on disk, so this re-reads them rather than asking the
    user to upload the file a second time. It is the recovery for a parse that
    failed on something transient; a file that is genuinely unreadable fails
    again and says the same thing.
    """
    source = get_source(session, scope, source_id)
    if not source.bytes_path or not store.exists(source.bytes_path):
        raise repo.NotFound(
            "This file's bytes are no longer stored, so it cannot be parsed "
            "again. Upload it once more.")

    content = store.read(source.bytes_path)
    source.status = "parsing"
    source.failure_reason = ""
    session.flush()
    try:
        accepted, result = ingest.read(source.filename, content)
    except ingest.UnreadableSource as exc:
        source.status = "failed"
        source.failure_reason = str(exc)
        source.manifest = {"complete": False, "read": [], "skipped": [],
                           "warnings": [str(exc)]}
        reparse.record(session, source, kind=reparse._format_of(source),
                       failure=str(exc))
        session.flush()
        return source

    repo.set_chunks(session, source, result.chunks)
    source.manifest = result.manifest.as_dict()
    source.status = "parsed" if result.manifest.complete else "partial"
    reparse.record(session, source, kind=accepted.kind, result=result)
    session.flush()
    return source


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


def ledger_for(session, scope: repo.Scope, workspace_id: int, *,
               source_ids: list[int] | None = None,
               export_revision_ids: list[int] | None = None,
               calculations: list | None = None,
               artifact_id: int | None = None,
               chat_context=None) -> ev.Ledger:
    """Assemble the evidence for one request from what was explicitly chosen.

    Nothing is included by being nearby. An empty selection produces an empty
    ledger, and the caller is expected to say so rather than quietly widening
    the search.

    `artifact_id` is the one exception, and it is not "nearby": it is the
    document the request is about. Passing it admits the approved current
    version as evidence, so a revision may restate what that version already
    said. See `add_current_version`.
    """
    ledger = ev.Ledger()
    for source in repo.sources(session, workspace_id):
        if source_ids is not None and source.id not in source_ids:
            continue
        if source.status == "failed":
            ledger.omit(source.filename,
                        source.failure_reason or "the file could not be read")
            continue
        rows = repo.chunks(session, source.id)
        from backend.playbook.ingest.types import Chunk

        ev.from_chunks(
            [Chunk(kind=c.kind, locator=c.locator, text=c.text,
                   path=list(c.path or []), data=dict(c.data or {}),
                   ordinal=c.ordinal) for c in rows],
            label=f"{source.filename} ({source.source_role.replace('_', ' ')})",
            ledger=ledger,
        )
        for gap in (source.manifest or {}).get("skipped", []):
            ledger.omit(f"{source.filename}: {gap.get('what', '')}",
                        gap.get("why", ""))

        # §18, §19(13): a source read by an older reader is evidence read
        # WORSE than it can be — not evidence that is missing, but not a
        # complete reading either. Recorded as a gap so a generation cannot
        # quietly rest on it: the thread says so, and `evidence_complete` is
        # False until the source is re-read, which costs nothing.
        reading = reparse.state(session, source)
        if reading.stale:
            ledger.omit(
                f"{source.filename}: {reading.reason_label.lower()}",
                "; ".join(reading.improvements)
                or "re-read this source to bring its reading up to date")

    for revision_id in export_revision_ids or []:
        revision = repo.find_export_revision(session, scope, revision_id)
        ev.from_export(revision.payload or {}, export_id=revision.export_id,
                       revision=revision.revision, ledger=ledger)

    if calculations:
        ev.add_calculations(ledger, calculations)
    if artifact_id:
        add_current_version(session, ledger, artifact_id)
    if chat_context is not None:
        # The governed facts behind whatever dashboard object the user
        # clicked. §15. Only what the context builder already established as
        # governed arrives here: an unconfirmed suggestion produced a caveat
        # for the person, not a fact, so it cannot become a citable figure by
        # travelling through the composer.
        from backend.playbook.intelligence import context as dashboard

        for item in dashboard.as_items(chat_context):
            ledger.add(item)
    return ledger


def add_current_version(session, ledger: ev.Ledger, artifact_id: int) -> ev.Ledger:
    """Make the version being revised admissible evidence for its revision.

    Without this, a revision is judged against the sources alone, so restating
    a figure the APPROVED previous version already carried reads as inventing
    it — and grounding strips a figure the user explicitly asked to keep.

    This is not a loophole. Version 1's own figures were themselves reconciled
    against the evidence when version 1 was written, so the chain of custody
    holds: nothing becomes quotable here that was not quotable then. What it
    does not do is excuse a NEW figure — anything the model adds still has to
    trace to a source, an export, a calculation, or to this.
    """
    from backend.models.playbook import PlaybookArtifact, PlaybookArtifactVersion

    artifact = session.get(PlaybookArtifact, artifact_id)
    if artifact is None or artifact.current_version_id is None:
        return ledger
    version = session.get(PlaybookArtifactVersion, artifact.current_version_id)
    if version is None:
        return ledger

    doc = D.Document.from_dict(version.content or {})
    ledger.add(ev.Item(
        locator=f"version://{artifact_id}/{version.version}",
        kind="paragraph",
        text=doc.plain_text(),
        origin="version",
        label=f"Approved version {version.version} of this document",
    ))
    return ledger


# --------------------------------------------------------------------------
# Authoring
# --------------------------------------------------------------------------


def _render_locally(doc: D.Document, formats: list[str]) -> dict[str, bytes]:
    return {fmt: render.render(doc, fmt) for fmt in formats}


@dataclass
class FormatOutcome:
    """What happened to one requested format. Chapter 07's third outcome."""

    fmt: str
    content: bytes = b""
    renderer: str = ""
    validation: Any = None
    issues: list[str] = field(default_factory=list)

    @property
    def delivered(self) -> bool:
        """Whether a user may have this file.

        Bytes exist AND the file itself is sound. Chapter 29 draws the line
        there: "a file with no actual bytes is not delivered" and "a truly
        corrupted PDF is not offered as valid", while content findings — a
        table count that differs, a figure with no source — are review
        findings that "do not erase an otherwise safe draft".
        """
        return bool(self.content) and (self.validation is None
                                       or self.validation.sound)

    def as_dict(self) -> dict:
        return {"format": self.fmt, "delivered": self.delivered,
                "renderer": self.renderer, "issues": list(self.issues),
                "bytes": len(self.content)}


def _usable(files: dict[str, bytes], doc: D.Document,
            formats: list[str]) -> dict[str, FormatOutcome]:
    """Decide each requested format on its own.

    This used to be all-or-nothing in both directions: if any format was
    missing or failed, EVERY provider-generated file was thrown away and the
    whole set re-rendered locally, and a single failure then failed the turn.
    So a perfectly good Word file was discarded because the PDF did not
    convert, which is what DC-22 exists to catch and what chapter 08 forbids —
    "never discard a provider-created DOCX/PPTX merely to regenerate it through
    a less expressive writer".

    Now each format is its own outcome. A provider file that validates is kept
    as it came. One that is missing or does not validate falls back to the
    local renderer for that format alone. A format that fails both ways is
    reported as failed and takes nothing else with it.
    """
    produced = {f: b for f, b in files.items() if f in formats}
    checked = validate.validate_all(produced, doc) if produced else {}

    outcomes: dict[str, FormatOutcome] = {}
    for fmt in formats:
        result = checked.get(fmt)
        if fmt in produced and result is not None and result.sound:
            outcomes[fmt] = FormatOutcome(
                fmt=fmt, content=produced[fmt], renderer=capabilities.SKILL,
                validation=result)
            continue

        # Either the provider did not produce this one, or what it produced
        # will not open. Render just this format locally and keep the reason
        # the provider's copy was not used, so the fallback is visible rather
        # than silent. A provider file with only CONTENT findings is kept as
        # it came: re-rendering it through a thinner writer to satisfy a table
        # count is exactly what chapter 08 forbids.
        why = list(result.issues) if result is not None else []
        try:
            content = render.render(doc, fmt)
        except Exception as exc:  # noqa: BLE001 — one format, not the turn
            logger.exception("Playbook local rendering failed for %s", fmt)
            outcomes[fmt] = FormatOutcome(
                fmt=fmt, issues=why + [f"could not be produced: {exc}"])
            continue

        local = validate.validate(content, fmt, doc)
        outcomes[fmt] = FormatOutcome(
            fmt=fmt, content=content, renderer=capabilities.LOCAL,
            validation=local, issues=why + list(local.issues))
    return outcomes


def author_document(session, scope: repo.Scope, workspace_id: int, *,
                    instruction: str,
                    ledger: ev.Ledger,
                    title: str,
                    formats: list[str] | None = None,
                    artifact_id: int | None = None,
                    base_version_id: int | None = None,
                    change_summary: str = "",
                    task_kind: str = "",
                    task_scope: str = "",
                    on_milestone=None,
                    on_delta=None,
                    is_cancelled=None) -> Outcome:
    """One complete authoring run, from instruction to persisted version.

    `task_kind` selects one of §8's framings — create, update, coverage,
    propose, edit, present. It is not decoration: "revise the executive summary"
    and "write this report" are different jobs, and the framing is what carries
    the rules that make them different (return the complete document; never
    soften a negative finding; propose, do not apply).

    When the run revises an existing artifact, the CURRENT DOCUMENT travels with
    the request. A revision that never sees what it is revising cannot leave the
    other sections alone — it can only write them again from memory, which is
    how a scoped edit quietly rewrites a figure three sections away.
    """
    formats = list(formats or DEFAULT_FORMATS)
    for fmt in formats:
        capabilities.require(fmt)

    ws = repo.get_workspace(session, scope, workspace_id)
    outcome = Outcome(workspace_id=ws.id)

    # Which path makes this artifact, decided once and recorded. Chapter 08
    # wants the better path per task rather than a blanket switch, and wants
    # the answer stored: `playbook_artifact_files.renderer` carries it per
    # file, and `_usable` may still fall back for one format without
    # disturbing the others.
    path = documents.choose()
    outcome.document_path = path.as_dict()

    system = prompts.system(formats=formats,
                            document_tools=path.path == documents.SKILL)
    parts = [_framed(task_kind, instruction, task_scope, ws.document_family)]
    current = _current_document(session, artifact_id)
    if current is not None:
        parts.append(prompts.current_document(current.markdown,
                                              version=current.version))
    parts.append(ledger.render())
    user = "\n\n".join(p for p in parts if p)

    # Timed separately, and never added together into one number. Authoring is
    # the provider call; rendering is deterministic, local and fast. Reporting
    # them as one figure is what makes a slow generation impossible to
    # diagnose.
    authoring_began = time.monotonic()
    result = provider.author(
        system=system,
        messages=[{"role": "user", "content": user}],
        formats=formats,
        document_tools=path.path == documents.SKILL,
        on_milestone=on_milestone,
        on_delta=on_delta,
        is_cancelled=is_cancelled,
    )
    outcome.authoring_ms = int((time.monotonic() - authoring_began) * 1000)
    outcome.provider_ms = int(getattr(result, "provider_ms", 0) or 0)
    outcome.turns = int(getattr(result, "turns", 0) or 0)
    outcome.tool_calls = int(getattr(result, "tool_calls", 0) or 0)
    outcome.model_served = result.model_served
    outcome.request_ids = list(result.request_ids)
    outcome.milestones = list(result.milestones)
    if result.downgraded:
        outcome.notes.append(
            f"The provider served {result.model_served} rather than the "
            f"configured {result.model_requested}."
        )

    doc = D.parse(result.text, title=title)
    if not doc.sections:
        raise provider.AuthoringError(
            "The author returned no document. Nothing was saved and the "
            "previous version is unchanged.", category="empty_output")

    # A scoped edit is scoped HERE, not by asking nicely. The model returns a
    # whole document; only the section that was requested is taken from it, and
    # every other section is carried forward from the approved version as the
    # same object. That makes "nothing else changed" true by construction
    # rather than true as far as anybody checked — and it means grounding only
    # scrutinises the section that actually changed, so a revision cannot cause
    # a figure to be stripped from a section it never touched.
    #
    # The base is the STORED CANONICAL version, not the Markdown the prompt
    # showed the model. A Markdown round-trip drops every citation locator,
    # `meta` and `subtitle`, renumbers ordered lists and renormalises
    # whitespace — so merging against it rewrote every unrelated section it
    # claimed to carry forward, and wrote that damage to canonical storage.
    drafted_only: set[str] | None = None
    if task_kind == "edit" and current is not None:
        base_doc = current.canonical
        if base_doc.sections:
            try:
                merged = merge.scoped_merge(base_doc, doc, task_scope)
            except merge.ScopeNotFound as exc:
                raise provider.AuthoringError(
                    str(exc), category="scope_not_found") from exc
            doc = merged.document
            outcome.scoped_to = merged.target
            outcome.rejected_sections = list(merged.rejected)
            drafted_only = {merged.applied_heading}
            if merged.note():
                outcome.notes.append(merged.note())

    # Grounding scrutinises what the model actually wrote. On a scoped edit
    # that is the target section; every other section is byte-identical to an
    # approved version that was itself grounded when it was written, and
    # re-checking it against a DIFFERENT ledger is not a stricter test but a
    # false one — it deletes figures from sections nobody touched.
    #
    # One pass, and it removes nothing. Evidence is CHECKED; the draft is
    # left as it was written and every finding is recorded beside it with its
    # section and its figures.
    #
    # What used to happen: `check(remove=True)` deleted every figure the
    # ledger did not support, a second pass refused the whole turn if removal
    # had not converged, a third refused it if removal had hollowed a section,
    # and any removal at all threw away the provider's files so they could be
    # re-rendered from the edited prose. A draft that was 95% right was
    # destroyed to avoid shipping the other 5%, and the author's sentences
    # were edited by a regular expression before anybody read them.
    #
    # Chapter 16 retires that for ordinary drafting: preserve the authored
    # draft and record suspected issues separately, with their locations.
    # Chapter 03's ladder — DRAFT, REVIEWED, GOVERNED, APPROVED — is what
    # carries the difference between "written" and "checked by a person", and
    # a review finding now moves a document down that ladder instead of
    # deleting it. A corrupt file, a security failure or an unreadable
    # artifact still stops delivery; a figure that wants a source does not.
    review = grounding.check(doc, ledger, remove=False, scope=drafted_only)
    outcome.grounding = review
    outcome.review_items = [
        {"kind": "unsupported_figure", "section": f.section,
         "figures": list(f.figures), "detail": f.line()}
        for f in review.findings
    ]
    if review.note():
        outcome.notes.append(review.note())

    skill_files = {f.format: f.content for f in result.files}

    render_began = time.monotonic()
    produced = _usable(skill_files, doc, formats)
    outcome.render_ms = int((time.monotonic() - render_began) * 1000)
    outcome.formats = produced
    outcome.files = {f: o.content for f, o in produced.items() if o.delivered}
    outcome.validations = {f: o.validation for f, o in produced.items()
                           if o.validation is not None}
    renderers = {o.renderer for o in produced.values() if o.delivered}
    outcome.renderer = renderers.pop() if len(renderers) == 1 else (
        capabilities.LOCAL if renderers else "")

    # A format that could not be produced is reported as itself and takes
    # nothing with it. This used to raise for the whole turn on any validation
    # failure, so one PDF that a derived index disliked destroyed the Word
    # file, the answer and the version — DC-22, and chapter 16's recovery
    # example verbatim: "The Word draft is ready. The PDF conversion could not
    # be completed."
    for fmt, outcome_ in produced.items():
        if not outcome_.delivered:
            outcome.notes.append(
                f"The {fmt.upper()} could not be produced. "
                + "; ".join(outcome_.issues))
        elif outcome_.issues:
            outcome.notes.append(
                f"The {fmt.upper()} was produced with issues worth review: "
                + "; ".join(outcome_.issues))

    if not outcome.files:
        # Nothing at all came back. That IS a failed turn: there is no draft
        # to preserve, and chapter 07 forbids claiming one exists.
        raise provider.AuthoringError(
            "None of the requested formats could be produced, so no file was "
            "saved. "
            + "; ".join(i for o in produced.values() for i in o.issues),
            category="validation",
        )

    outcome.document = doc
    _persist(session, scope, ws, outcome, title=title, artifact_id=artifact_id,
             base_version_id=base_version_id, change_summary=change_summary,
             ledger=ledger)
    return outcome


def _persist(session, scope: repo.Scope, ws, outcome: Outcome, *, title: str,
             artifact_id: int | None, base_version_id: int | None,
             change_summary: str, ledger: ev.Ledger) -> None:
    doc = outcome.document
    from backend.models.playbook import PlaybookArtifact

    if artifact_id:
        artifact = session.get(PlaybookArtifact, artifact_id)
        if artifact is None or artifact.workspace_id != ws.id:
            raise repo.NotFound(f"No artifact {artifact_id} in this workspace.")
    else:
        artifact = repo.create_artifact(session, ws.id, kind="report",
                                        title=title)

    version = repo.new_version(
        session, artifact,
        content=doc.as_dict(),
        source_manifest={
            "locators": sorted(ledger.locators()),
            "omissions": list(ledger.omissions),
            "complete": ledger.complete,
        },
        content_hash=doc.content_hash(),
        change_summary=change_summary,
        base_version_id=base_version_id,
        created_by=scope.user_id,
        validation={
            **{f: v.as_dict() for f, v in outcome.validations.items()},
            # One pass, on the row itself. It used to be written under two
            # keys, "attempted" and "saved", from the days when the second
            # was the re-check of a document that removal had edited. Nothing
            # is removed any more, so both keys held the same object and the
            # record implied a verification step that had not happened.
            "grounding": (outcome.grounding.as_dict()
                          if outcome.grounding else {}),
            # Where this version sits on chapter 03's ladder, and what a
            # reviewer would want to look at. A new version is always a draft
            # — writing is not reviewing — and the findings travel with it
            # rather than having been edited out of it.
            "review": review.initial(outcome.review_items),
        },
    )

    for fmt, content in outcome.files.items():
        cap = capabilities.require(fmt)
        filename = f"{_slug(title)}-v{version.version}.{fmt}"
        stored = store.put_artifact(ws.id, artifact.id, version.version,
                                    filename, content)
        repo.add_file(
            session, version, fmt=fmt, bytes_path=stored.relative,
            mime=cap.mime, filename=filename, size_bytes=stored.size_bytes,
            sha256=stored.sha256, renderer=outcome.renderer,
            validated=outcome.validations.get(fmt, validate.Validation(fmt)).ok,
        )

    # The dashboard is NOT brought into line here, and that is the point.
    #
    # It used to be: adoption ran in this transaction, with a comment saying
    # that a version whose sections were never recorded is one the dashboard
    # misdescribes, so "if that cannot be written, the version is not written
    # either". The consequence was that a failure in the status projection
    # destroyed the file the user was waiting for — the exact coupling the
    # specification's architectural acceptance test exists to catch. With the
    # status service failing, no document could be saved at all.
    #
    # So the version and its files commit on their own, and what the dashboard
    # needs to catch up is recorded for a projection that runs afterwards, in
    # its own session, and is allowed to fail without taking anything with it.
    # A dashboard that is briefly behind says so; a lost report cannot.
    outcome.pending_projection = {
        "workspace_id": ws.id,
        "artifact_id": artifact.id,
        "version_id": version.id,
        "version": version.version,
    }

    repo.touch(session, ws, summary=change_summary or f"{title} v{version.version}")
    outcome.artifact_id = artifact.id
    outcome.version_id = version.id
    outcome.version = version.version


def _framed(kind: str, instruction: str, scope: str, family: str) -> str:
    """The instruction, inside its task framing.

    An unknown or absent kind passes the instruction through untouched rather
    than guessing at one. Guessing would apply "return the complete document"
    to a request that was never about a document.
    """
    if kind not in prompts.TASKS:
        return instruction
    if kind == "edit":
        return prompts.task("edit", scope=scope or "the section named below",
                            instruction=instruction)
    if kind == "create":
        framing = prompts.task(
            "create", family=(family or "report").replace("_", " "))
    else:
        framing = prompts.task(kind)
    return f"{framing}\n\n{instruction}" if instruction else framing


@dataclass
class _Current:
    """The approved version, in both the forms an edit needs.

    `canonical` is the stored Document, unchanged. `markdown` is a rendering of
    it for the prompt and the thread. They are separate fields rather than one,
    because the Markdown is lossy — it drops citation locators, `meta` and
    `subtitle` — and a scoped edit that merged against it would silently rewrite
    every unrelated section it carried forward. Prose for the model; canonical
    for the merge.
    """

    canonical: D.Document
    markdown: str
    version: int


def _current_document(session, artifact_id: int | None) -> _Current | None:
    """The artifact's current version, or None if there is none."""
    if not artifact_id:
        return None
    from backend.models.playbook import PlaybookArtifact, PlaybookArtifactVersion

    artifact = session.get(PlaybookArtifact, artifact_id)
    if artifact is None or artifact.current_version_id is None:
        return None
    version = session.get(PlaybookArtifactVersion, artifact.current_version_id)
    if version is None:
        return None
    doc = D.Document.from_dict(version.content or {})
    return _Current(canonical=doc, markdown=_markdown_of(doc),
                    version=version.version)


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in (text or "report")]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60] or "report"


def content_hash(doc: D.Document) -> str:
    return hashlib.sha256(
        doc.plain_text().encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Sending a message
# --------------------------------------------------------------------------


def send_message(session, scope: repo.Scope, workspace_id: int, *,
                 text: str,
                 source_ids: list[int] | None = None,
                 export_revision_ids: list[int] | None = None,
                 formats: list[str] | None = None,
                 artifact_id: int | None = None,
                 base_version_id: int | None = None,
                 idempotency_key: str = "",
                 task_kind: str = "",
                 task_scope: str = "",
                 context_kind: str = "",
                 context_target: str = "",
                 calculations: list | None = None,
                 on_milestone=None,
                 on_delta=None,
                 on_draft=None,
                 on_plan=None,
                 is_cancelled=None) -> dict:
    """One turn: persist what was asked, do it, persist what came back.

    The user's message and its attachments are written FIRST and committed with
    the job row, so a generation that fails still leaves a thread showing what
    was asked and what went wrong. A thread that loses the question when the
    answer fails is a thread nobody can retry from.

    `idempotency_key` is enforced by a unique constraint. A refresh, a
    double-click or a retry after a dropped connection finds the job that is
    already running rather than starting a second billable one.
    """
    started = begin_generation(
        session, scope, workspace_id, text=text, source_ids=source_ids,
        export_revision_ids=export_revision_ids,
        idempotency_key=idempotency_key, context_kind=context_kind,
        context_target=context_target)
    if started["duplicate"]:
        return started

    return run_generation(
        session, scope, workspace_id, job_id=started["job_id"], text=text,
        source_ids=source_ids, export_revision_ids=export_revision_ids,
        formats=formats, artifact_id=artifact_id,
        base_version_id=base_version_id, task_kind=task_kind,
        task_scope=task_scope, context_kind=context_kind,
        context_target=context_target, calculations=calculations,
        on_milestone=on_milestone, on_delta=on_delta, on_draft=on_draft,
        on_plan=on_plan,
        is_cancelled=is_cancelled)


def resolve_context(session, workspace_id: int, *, kind: str = "",
                    target: str = ""):
    """The dashboard object a turn is about, or None.

    A context that can no longer be resolved — the finding was deleted, the
    metric unlinked — is NOT an error here. The user's question still stands
    and is still answerable; what it loses is the evidence the dashboard would
    have supplied, and the turn proceeds without pretending otherwise. The
    route that built the context in the first place reports the failure, where
    there is still somebody to tell.
    """
    if not kind:
        return None
    from backend.playbook.intelligence import context as dashboard

    try:
        return dashboard.build(session, workspace_id, kind=kind,
                               target=target)
    except dashboard.UnknownContext as exc:
        logger.info("playbook: dashboard context %s/%s unavailable: %s",
                    kind, target, exc)
        return None


def begin_generation(session, scope: repo.Scope, workspace_id: int, *,
                     text: str,
                     source_ids: list[int] | None = None,
                     export_revision_ids: list[int] | None = None,
                     idempotency_key: str = "",
                     context_kind: str = "",
                     context_target: str = "") -> dict:
    """Record the question and claim the job, before any work happens.

    Separate from running it because the streamed path needs the job id in the
    response it returns immediately, while the generation is still going. Both
    paths go through here, so the idempotency guarantee is one piece of code
    rather than two that must agree.

    The user's message and its attachments are written FIRST and committed with
    the job row. A generation that fails still leaves a thread showing what was
    asked and what went wrong; a thread that loses the question when the answer
    fails is a thread nobody can retry from. It is also what lets the stop
    button and the stream, both in other requests, see the job at all.
    """
    from backend.models.playbook import PlaybookJob

    ws = repo.get_workspace(session, scope, workspace_id)
    key = idempotency_key or f"ws{ws.id}:{repo.next_sequence(session, ws.id)}"

    existing = repo.jobs_by_key(session, key, workspace_id=ws.id)
    if existing is not None:
        # A double-click, a refresh, or a retry after a dropped connection.
        # None of them is a second generation.
        return {"job_id": existing.id, "state": existing.state,
                "duplicate": True,
                "message": "This request is already running."}

    # The same key cannot start twice; a DIFFERENT key still could, and did.
    # The client's key is positional — `ws7:turn12` — so the same sentence
    # sent again after the thread reloads gets a new key and was accepted as
    # new work. Four identical messages in one live thread is what that looks
    # like, and each one was a second provider run on the same conversation,
    # charged, with only the newest visible to the user.
    live = _live_job(session, ws.id)
    if live is not None:
        return {"job_id": live.id, "state": live.state, "duplicate": True,
                "message": "A generation is already running in this "
                           "Playbook. Wait for it to finish, or stop it."}

    job = PlaybookJob(workspace_id=ws.id, tenant=scope.tenant,
                      idempotency_key=key, state="queued",
                      requested_by=scope.user_id,
                      heartbeat_at=_now())
    session.add(job)
    try:
        session.flush()
    except IntegrityError:
        # Two requests raced past the check above and the partial unique index
        # caught the loser. The winner is the running generation; report it as
        # the duplicate it is rather than failing the request.
        session.rollback()
        ws = repo.get_workspace(session, scope, workspace_id)
        live = _live_job(session, ws.id)
        if live is None:
            raise
        return {"job_id": live.id, "state": live.state, "duplicate": True,
                "message": "A generation is already running in this "
                           "Playbook. Wait for it to finish, or stop it."}

    # What the turn refers to travels ON the message, so reopening the thread
    # a month later still shows which finding "draft an answer to this" meant.
    from backend.playbook.intelligence import context as dashboard

    content = dashboard.attach(
        {"text": text},
        resolve_context(session, ws.id, kind=context_kind,
                        target=context_target))
    user_message = repo.add_message(
        session, ws.id, role="user",
        content=content, origin="user", author_id=scope.user_id)
    for position, source_id in enumerate(source_ids or []):
        repo.attach(session, ws.id, message_id=user_message.id,
                    source_id=source_id, position=position)
    for position, revision_id in enumerate(export_revision_ids or []):
        # Resolved through the tenant-scoped lookup, so an id that was never
        # exported — or belongs to somebody else — fails here rather than
        # becoming evidence.
        revision = repo.find_export_revision(session, scope, revision_id)
        repo.attach(session, ws.id, message_id=user_message.id,
                    export_revision_id=revision.id,
                    position=len(source_ids or []) + position)
    session.commit()
    return {"job_id": job.id, "state": job.state, "duplicate": False,
            "user_message_id": user_message.id, "idempotency_key": key}


def run_generation(session, scope: repo.Scope, workspace_id: int, *,
                   job_id: int,
                   text: str,
                   source_ids: list[int] | None = None,
                   export_revision_ids: list[int] | None = None,
                   formats: list[str] | None = None,
                   artifact_id: int | None = None,
                   base_version_id: int | None = None,
                   task_kind: str = "",
                   task_scope: str = "",
                   context_kind: str = "",
                   context_target: str = "",
                   calculations: list | None = None,
                   on_milestone=None,
                   on_delta=None,
                   on_draft=None,
                   on_plan=None,
                   is_cancelled=None) -> dict:
    """Do the work a claimed job stands for, and persist what came back.

    One conversational turn. Ordinary questions get ordinary answers; a turn
    that needs a file gets one because the assistant asked for it, not because
    this function decided in advance.

    What used to happen here was a single unconditional call to
    `author_document` with DEFAULT_FORMATS, so every message — including "what
    is the difference between a development and a validation report?" — tried
    to write a document and render Word and PDF, and failed the turn if either
    could not be produced.

    `task_kind`, `task_scope` and `formats` still arrive from callers that know
    what they want (the dashboard's Ask bridge, a scripted journey). They are
    carried into the turn as what the user asked for, NOT as a route: chapter
    04 is explicit that the decision belongs to the assistant.
    """
    from backend.models.playbook import PlaybookJob
    from backend.playbook import chat as chat_turn

    ws = repo.get_workspace(session, scope, workspace_id)
    job = session.get(PlaybookJob, job_id)
    if job is None or job.workspace_id != ws.id:
        raise repo.NotFound(f"No generation {job_id} in this workspace.")

    if is_cancelled is None:
        is_cancelled = cancellation_watcher(job.id)

    def milestone(state: str, detail: str = "") -> None:
        job.state = state if state in {"reviewing_sources", "drafting",
                                       "rendering", "validating"} else job.state
        job.milestones = list(job.milestones or []) + [
            {"state": state, "detail": detail}]
        if on_milestone:
            on_milestone(state, detail)

    def tool_state(name: str, stage: str) -> None:
        """An honest work state, derived from what is happening.

        Chapter 15: event-derived, never a timer pretending to be progress.
        """
        milestone("drafting" if stage == "running" else "rendering",
                  f"{name} {stage}")

    asked = _what_was_asked(text, task_kind=task_kind, task_scope=task_scope,
                            formats=formats)
    try:
        turn = chat_turn.turn(
            session, scope, ws.id, text=asked,
            source_ids=source_ids, export_revision_ids=export_revision_ids,
            artifact_id=artifact_id, base_version_id=base_version_id,
            context_kind=context_kind, context_target=context_target,
            task_kind=task_kind, calculations=calculations,
            on_milestone=milestone, on_delta=on_delta, on_draft=on_draft,
            on_plan=on_plan, on_tool=tool_state,
            is_cancelled=is_cancelled)
    except provider.Cancelled as exc:
        job.state = "cancelled"
        job.finished_at = _now()
        repo.add_message(session, ws.id, role="assistant",
                         content={"text": "This message was stopped. "
                                          "Nothing was saved."},
                         origin="system", job_id=job.id)
        raise exc
    except Exception as exc:
        job.state = "failed"
        job.error = str(exc)[:2000]
        job.finished_at = _now()
        repo.add_message(
            session, ws.id, role="assistant",
            content={"text": str(exc), "failed": True},
            origin="system", job_id=job.id)
        raise

    reply = turn["reply"]
    job.state = "ready"
    job.model = reply.model_served
    job.provider_request_ids = list(reply.request_ids)
    job.usage = {"requests": len(reply.request_ids),
                 "input_tokens": reply.input_tokens,
                 "output_tokens": reply.output_tokens}
    job.finished_at = _now()

    produced = turn["produced"]
    last = produced[-1] if produced else {}
    message = repo.add_message(
        session, ws.id, role="assistant",
        content={
            # The assistant's own words, as it wrote them. Not a rendering of
            # a document, and not rewritten by anything downstream.
            "text": turn["text"],
            "artifact_id": turn["artifact_id"],
            "version_id": last.get("version_id"),
            "version": last.get("version"),
            # Every file this turn produced or failed to produce, so the
            # thread can show a card per delivered format and say what
            # happened to the rest. Chapter 07's three independent outcomes.
            "files": list(produced),
            "notes": [n for p in produced for n in p.get("review_notes", [])],
            "tools": [{"name": r.name, "ok": r.ok, "detail": r.detail}
                      for r in reply.tool_runs],
            # Chapter 07: partial text is labelled, never presented as a
            # finished answer.
            "interrupted": reply.interrupted,
            # The turn's own words described a document and no tool made one.
            # Recorded on the message so the thread can say so, rather than
            # leaving an answer that reads like success beside an empty Files
            # panel — which is exactly what the first live run produced.
            "no_file": reply.broke_its_promise,
            "nudged": reply.nudged,
            "evidence_complete": turn["evidence_complete"],
            "evidence_gaps": list(turn["evidence_gaps"]),
            # Not a claim about the dashboard. The projection runs after this
            # transaction commits, so saying anything else here would be
            # inventing state the client can simply read for itself.
            "dashboard": {"state": "updating"},
        },
        origin="assistant_live", model=reply.model_served,
        request_ids=list(reply.request_ids), job_id=job.id)

    return {"job_id": job.id, "state": "ready", "duplicate": False,
            "message_id": message.id, "artifact_id": turn["artifact_id"],
            "version_id": last.get("version_id"),
            "version": last.get("version", 0),
            "interrupted": reply.interrupted,
            "no_file": reply.broke_its_promise,
            "files": list(produced),
            "notes": [n for p in produced for n in p.get("review_notes", [])],
            # A list: one turn may write more than one version, and every one
            # of them has to be projected or the next comparison is wrong.
            "projections": list(turn["projections"])}


def _what_was_asked(text: str, *, task_kind: str = "", task_scope: str = "",
                    formats: list[str] | None = None) -> str:
    """The user's message, plus what a caller separately said they wanted.

    A caller that knows its own intent — the dashboard's Ask bridge, a
    scripted journey — should not have to phrase it twice, and the assistant
    should not have to guess it. But this is context, not a route: the turn
    still reaches the assistant as a conversation, and the assistant still
    decides whether a file is called for.
    """
    hints: list[str] = []
    if task_kind:
        hints.append(f"requested task: {task_kind}")
    if task_scope:
        hints.append(f"scope: {task_scope}")
    if formats:
        hints.append("requested file formats: " + ", ".join(formats))
    if not hints:
        return text
    return f"{text}\n\n[The interface also recorded — {'; '.join(hints)}.]"


def attach_formats(session, scope: repo.Scope, workspace_id: int,
                   artifact_id: int, produced: dict) -> dict:
    """Store additional formats against the version that already exists.

    A conversion is the same document in another wrapper, so it belongs to the
    version it was converted FROM — chapter 10: "record which source version
    each conversion represents", and "an old PDF must not be labelled current
    after only the Word file changes".

    This is also what makes a retry cheap. Chapter 17 and journey 16 require
    that retrying a failed PDF reuse the saved content rather than author the
    report again, and no provider call is made here at all: re-authoring would
    spend money to produce a DIFFERENT report under the same version number.

    A format that already exists on the version is replaced, so a retry
    supersedes the failed attempt instead of leaving two rows claiming to be
    the PDF of version 3.
    """
    from backend.models.playbook import PlaybookArtifact, PlaybookArtifactVersion

    artifact = session.get(PlaybookArtifact, artifact_id)
    ws = repo.get_workspace(session, scope, workspace_id)
    if artifact is None or artifact.workspace_id != ws.id:
        raise repo.NotFound(f"No artifact {artifact_id} in this workspace.")
    version = (session.get(PlaybookArtifactVersion, artifact.current_version_id)
               if artifact.current_version_id else None)
    if version is None:
        raise repo.NotFound("This document has no saved version.")

    existing = {f.format: f for f in repo.files(session, version.id)}
    delivered, failed = [], {}
    for fmt, outcome in produced.items():
        if not outcome.delivered:
            failed[fmt] = "; ".join(outcome.issues) or "could not be produced"
            continue
        cap = capabilities.require(fmt)
        filename = f"{_slug(artifact.title or ws.title)}-v{version.version}.{fmt}"
        stored = store.put_artifact(ws.id, artifact.id, version.version,
                                    filename, outcome.content)
        if fmt in existing:
            session.delete(existing[fmt])
            session.flush()
        repo.add_file(
            session, version, fmt=fmt, bytes_path=stored.relative,
            mime=cap.mime, filename=filename, size_bytes=stored.size_bytes,
            sha256=stored.sha256, renderer=outcome.renderer,
            validated=bool(outcome.validation is None or outcome.validation.ok))
        delivered.append(fmt)

    return {"version": version.version, "version_id": version.id,
            "delivered": delivered, "failed": failed}


def project_status(session_factory, pending: dict) -> dict:
    """Bring the dashboard into line with a version that has already committed.

    Runs in its own session, and never raises. That is the whole contract:
    the specification's architectural acceptance test is that a user can
    complete a question, create a draft file, download it and reopen the thread
    with the status service deliberately broken, and none of that is possible
    while the projection shares the version's transaction.

    Returns what it recorded, or why it could not. A caller that gets
    `{"ok": False, ...}` has a dashboard that is behind, which the status view
    reports as updating — it does not have a lost document.
    """
    if not pending:
        return {"ok": True, "skipped": "nothing to project"}

    try:
        with session_factory() as session:
            from backend.models.playbook import PlaybookArtifactVersion

            row = session.get(PlaybookArtifactVersion, pending["version_id"])
            if row is None:
                return {"ok": False,
                        "reason": "the version is no longer there to project"}
            doc = D.Document.from_dict(row.content or {})
            recorded = adopt.adopt(
                session, pending["workspace_id"], pending["artifact_id"],
                version_id=row.id, version=row.version, doc=doc).as_dict()
            session.commit()
            return {"ok": True, **recorded}
    except Exception as exc:  # noqa: BLE001 — reported, never propagated
        # Logged with a traceback because a dashboard that silently stops
        # updating is worse than one that visibly fails. Returned rather than
        # raised because the document this describes is already safe.
        logger.exception("Playbook status projection failed for %s", pending)
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def mark_job_finished(session, job_id: int, *, state: str,
                      error: str = "") -> None:
    """Close a job from outside the run that owned it.

    The worker needs this after its own session has been rolled back: the job
    row must still say what happened, or a reader would find a generation that
    is for ever "drafting". Already-finished jobs are left alone, so a stop
    that arrives just after a success does not rewrite it as a failure.
    """
    from backend.models.playbook import PlaybookJob

    job = session.get(PlaybookJob, job_id)
    if job is None or job.finished_at is not None:
        return
    job.state = state
    job.error = error
    job.finished_at = _now()
    session.flush()


def _now():
    from sqlalchemy import func

    return func.now()


#: How long a generation may go unheard-from before it is treated as dead.
#: Comfortably longer than the longest legitimate silence — a sandbox read can
#: sit quiet for `provider.SKILL_READ_TIMEOUT_SECONDS` (420) inside a 600s run
#: deadline — because closing a job that is still working would orphan a live
#: provider call and let a second one start beside it, which is the exact
#: failure this whole mechanism exists to prevent.
STALE_AFTER_SECONDS = 1200


def _live_job(session, workspace_id: int):
    """The generation actually running in this workspace, or None.

    "Actually" is the point. A constraint with no way out is a workspace that
    can be bricked: if the process running a generation is killed, its row
    keeps `finished_at IS NULL` for ever and every later send is refused with
    no way for the user to clear it.

    So a job that has not been heard from within `STALE_AFTER_SECONDS` is
    closed here — finished, marked failed, with a sentence in the thread
    saying so — and this returns None. That is a fact about the row, not a
    guess: the worker stamps `heartbeat_at` as it writes each event.
    """
    from backend.models.playbook import PlaybookJob

    job = session.execute(
        select(PlaybookJob)
        .where(PlaybookJob.workspace_id == workspace_id,
               PlaybookJob.finished_at.is_(None))
        .order_by(PlaybookJob.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None

    last = job.heartbeat_at or job.created_at
    if last is None:
        return job
    age = (datetime.now(UTC) - last).total_seconds()
    if age <= STALE_AFTER_SECONDS:
        return job

    # Dead, not busy. Said in the thread rather than only in a column, because
    # a user who comes back to a silent workspace deserves to read why.
    job.state = "failed"
    job.error = (f"This generation stopped without finishing. Nothing was "
                 f"heard from it for {int(age)} seconds.")
    job.finished_at = _now()
    repo.add_message(
        session, workspace_id, role="assistant",
        content={"text": "This generation stopped without finishing, and "
                         "nothing was saved. Ask again when you are ready.",
                 "failed": True},
        origin="assistant_live", job_id=job.id)
    session.flush()
    return None


def heartbeat(session, job_id: int) -> None:
    """Say the job is still alive. Cheap, and called on every streamed event.

    Deliberately tolerant: a heartbeat that raises would fail a generation
    that is working perfectly well, which is a worse outcome than a missed
    stamp. The next event writes one.
    """
    from backend.models.playbook import PlaybookJob

    try:
        job = session.get(PlaybookJob, job_id)
        if job is not None and job.finished_at is None:
            job.heartbeat_at = _now()
    except Exception:  # noqa: BLE001 — never fail a turn over a timestamp
        logger.debug("Playbook heartbeat failed for job %s", job_id,
                     exc_info=True)


def _markdown_of(doc: D.Document | None) -> str:
    """Re-render the stored document as the Markdown the thread displays.

    Kept as a function rather than storing the model's raw reply, because what
    the thread shows must be what was actually SAVED — after grounding removed
    anything unsupported — not what the model first wrote.
    """
    if doc is None:
        return ""
    lines: list[str] = []
    if doc.title:
        lines.append(f"# {doc.title}")
        lines.append("")
    for section in doc.sections:
        if section.heading:
            lines.append(f"{'#' * min(section.level + 1, 6)} {section.heading}")
            lines.append("")
        for block in section.blocks:
            if block.kind == D.TABLE:
                columns = block.data.get("columns") or []
                if columns:
                    lines.append("| " + " | ".join(str(c) for c in columns) + " |")
                    lines.append("| " + " | ".join("---" for _ in columns) + " |")
                    for row in block.data.get("rows") or []:
                        lines.append("| " + " | ".join(
                            "" if v is None else str(v) for v in row) + " |")
                    lines.append("")
            elif block.kind in (D.BULLETS, D.NUMBERS):
                for i, item in enumerate(block.data.get("items", []), start=1):
                    lines.append(f"{i}. {item}" if block.kind == D.NUMBERS
                                 else f"- {item}")
                lines.append("")
            elif block.text:
                lines.append(block.text)
                lines.append("")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------
# Deciding proposed changes
# --------------------------------------------------------------------------


class DependencyConflict(RuntimeError):
    """An approved change materially depends on one that was rejected.

    Raised rather than resolved. §9 is explicit: the dependency is explained and
    a specific resolution is sought — the exclusion is never silently
    overridden, and neither is the approval silently dropped.
    """

    def __init__(self, message: str, *, conflicts: list[dict]) -> None:
        super().__init__(message)
        self.conflicts = conflicts


def decide_changes(session, scope: repo.Scope, workspace_id: int,
                   change_set_id: int, *, approve: list[str],
                   reject: list[str] | None = None,
                   force: bool = False) -> dict:
    """Record which proposed changes the user accepted.

    Takes STABLE IDS, not display numbers. The user says "1, 2 and 3" and the
    interface resolves that to stable ids before it gets here, because display
    numbers renumber and an instruction must not start meaning something else
    after a refresh.

    Recording a decision does not rewrite the document. The next generation
    applies exactly what was approved, which is what keeps "apply 1, 2 and 3"
    true after a reload rather than only in the moment.
    """
    from backend.models.playbook import PlaybookChangeSet

    ws = repo.get_workspace(session, scope, workspace_id)
    change_set = session.get(PlaybookChangeSet, change_set_id)
    if change_set is None or change_set.workspace_id != ws.id:
        raise repo.NotFound(f"No change set {change_set_id} in this workspace.")

    items = repo.change_items(session, change_set.id)
    known = {i.stable_id for i in items}
    unknown = sorted((set(approve) | set(reject or [])) - known)
    if unknown:
        raise repo.NotFound(
            "These are not changes in this proposal: " + ", ".join(unknown))

    approved = set(approve)
    rejected = set(reject or []) or (known - approved)

    # A change that depends on one being rejected cannot simply be applied.
    conflicts = [
        {"stable_id": item.stable_id,
         "display_number": item.display_number,
         "target_section": item.target_section,
         "depends_on": sorted(set(item.depends_on or []) & rejected)}
        for item in items
        if item.stable_id in approved
        and set(item.depends_on or []) & rejected
    ]
    if conflicts and not force:
        lines = "; ".join(
            f"change {c['display_number']} depends on "
            + ", ".join(c["depends_on"]) for c in conflicts)
        raise DependencyConflict(
            "Some approved changes depend on changes that were excluded: "
            f"{lines}. Nothing has been applied. Either include the changes "
            "they depend on, or drop them.", conflicts=conflicts)

    if change_set.base_version_id is not None:
        from backend.models.playbook import PlaybookArtifact, PlaybookArtifactVersion

        base = session.get(PlaybookArtifactVersion, change_set.base_version_id)
        artifact = (session.get(PlaybookArtifact, base.artifact_id)
                    if base else None)
        if artifact is not None and artifact.current_version_id != base.id:
            raise repo.StaleBaseVersion(
                "This proposal was made against an earlier version of the "
                "document, which has since been revised. Nothing was applied.")

    for item in items:
        item.status = "approved" if item.stable_id in approved else "rejected"
        item.decided_by = scope.user_id
        item.decided_at = _now()
    change_set.status = "decided"
    session.flush()

    return {
        "change_set_id": change_set.id,
        "approved": sorted(approved),
        "rejected": sorted(rejected),
        "conflicts": conflicts,
        "base_version_id": change_set.base_version_id,
    }


def approved_instruction(session, change_set_id: int) -> str:
    """The instruction that applies exactly what was approved, and nothing else.

    Built from the persisted decisions rather than from the chat, so it survives
    a refresh and says the same thing on the second attempt as on the first.
    """
    items = repo.change_items(session, change_set_id)
    approved = [i for i in items if i.status == "approved"]
    rejected = [i for i in items if i.status != "approved"]
    if not approved:
        return ""

    lines = ["Apply ONLY the following approved changes to the current "
             "document. Everything else must be returned unchanged."]
    for item in approved:
        lines.append(
            f"{item.display_number}. {item.target_section} — "
            f"{item.rationale}")
    if rejected:
        lines.append("")
        lines.append("The following were considered and NOT approved. Do not "
                     "make them, and do not make them partially:")
        for item in rejected:
            lines.append(f"- {item.target_section}: {item.rationale}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Restoring an earlier version, and stopping a generation
# --------------------------------------------------------------------------


def version_preview(session, scope: repo.Scope, artifact_id: int,
                    version_number: int) -> dict:
    """One version's document, readable in the application.

    Rendered from the CONTENT that was persisted, not from the generated file
    and not from what the model first replied. Two consequences worth naming:
    it shows what grounding actually left in the document, and it works for a
    version whose files a browser cannot display inline anyway.

    A preview is not a substitute for the file. The download stays the
    authoritative artifact; this is how somebody reads version 1 without
    downloading it.
    """
    from backend.models.playbook import PlaybookArtifact, PlaybookArtifactVersion

    artifact = session.get(PlaybookArtifact, artifact_id)
    if artifact is None:
        raise repo.NotFound(f"No artifact {artifact_id}.")
    repo.get_workspace(session, scope, artifact.workspace_id)

    version = session.execute(
        select(PlaybookArtifactVersion)
        .where(PlaybookArtifactVersion.artifact_id == artifact.id,
               PlaybookArtifactVersion.version == version_number)
    ).scalar_one_or_none()
    if version is None:
        raise repo.NotFound(f"This document has no version {version_number}.")

    doc = D.Document.from_dict(version.content or {})
    return {
        "artifact_id": artifact.id,
        "artifact_title": artifact.title,
        "version": version.version,
        "is_current": version.id == artifact.current_version_id,
        "change_summary": version.change_summary,
        "created_at": version.created_at.isoformat() if version.created_at else "",
        "title": doc.title,
        "subtitle": doc.subtitle,
        "meta": dict(doc.meta),
        "markdown": _markdown_of(doc),
        "sections": [s.heading for s in doc.sections],
        # The locators the document carries, so a reader can see what each
        # claim rests on without opening the file.
        "sources": list(doc.sources),
        "files": [{"id": f.id, "format": f.format, "filename": f.filename,
                   "size_bytes": f.size_bytes, "validated": f.validated}
                  for f in repo.files(session, version.id)],
    }


class AlreadyCurrent(RuntimeError):
    """The version asked for is the one already on screen."""


def restore_version(session, scope: repo.Scope, artifact_id: int,
                    version_number: int) -> dict:
    """Bring an earlier version back as the LATEST one, moving forward.

    Nothing is rewound. History is immutable, so restoring v1 over v3 writes a
    v4 whose content is v1's — v3 stays exactly where it was, and the change
    summary says where v4 came from. A restore that deleted the versions after
    it would destroy the record of what was tried, which is the thing version
    history exists for.

    The FILES are copied too, not regenerated. Regenerating them would produce
    bytes nobody has read, from a renderer that may have changed since; copying
    them means the download from v4 is byte-for-byte the file that was reviewed
    as v1.
    """
    from backend.models.playbook import PlaybookArtifact, PlaybookArtifactVersion

    artifact = session.get(PlaybookArtifact, artifact_id)
    if artifact is None:
        raise repo.NotFound(f"No artifact {artifact_id}.")
    ws = repo.get_workspace(session, scope, artifact.workspace_id)

    source = session.execute(
        select(PlaybookArtifactVersion)
        .where(PlaybookArtifactVersion.artifact_id == artifact.id,
               PlaybookArtifactVersion.version == version_number)
    ).scalar_one_or_none()
    if source is None:
        raise repo.NotFound(
            f"This document has no version {version_number}.")
    if source.id == artifact.current_version_id:
        raise AlreadyCurrent(
            f"Version {version_number} is already the latest version.")

    files = repo.files(session, source.id)
    summary = (f"Restored version {source.version}"
               + (f" — {source.change_summary}" if source.change_summary else ""))
    version = repo.new_version(
        session, artifact,
        content=dict(source.content),
        source_manifest=dict(source.source_manifest),
        content_hash=source.content_hash,
        change_summary=summary,
        origin="restore",
        base_version_id=artifact.current_version_id,
        created_by=scope.user_id,
        validation=dict(source.validation or {}),
    )

    for file in files:
        content = store.read(file.bytes_path)
        filename = file.filename.replace(f"-v{source.version}.",
                                         f"-v{version.version}.")
        stored = store.put_artifact(ws.id, artifact.id, version.version,
                                    filename, content)
        repo.add_file(
            session, version, fmt=file.format, bytes_path=stored.relative,
            mime=file.mime, filename=filename, size_bytes=stored.size_bytes,
            sha256=stored.sha256, renderer=file.renderer,
            validated=file.validated)

    repo.touch(session, ws, summary=summary)
    session.flush()
    return {"artifact_id": artifact.id, "version_id": version.id,
            "version": version.version, "restored_from": source.version,
            "change_summary": summary,
            "files": [f.format for f in files]}


def job_status(session, scope: repo.Scope, job_id: int) -> dict:
    """What a generation is doing, in real milestones and no percentage.

    There is no percentage here because there is no honest basis for one: the
    model does not report progress, and a bar that moves on a timer is a lie
    with an animation.
    """
    from backend.models.playbook import PlaybookJob

    job = session.get(PlaybookJob, job_id)
    if job is None or job.tenant != scope.tenant:
        raise repo.NotFound(f"No generation {job_id}.")
    return {
        "id": job.id, "workspace_id": job.workspace_id, "state": job.state,
        "cancelled": job.cancelled, "milestones": list(job.milestones or []),
        "model": job.model, "error": job.error,
        "finished": job.finished_at is not None,
    }


def running_job(session, scope: repo.Scope, workspace_id: int) -> dict | None:
    """The generation this workspace has in flight, if any.

    Carried on the workspace payload so a browser that has just loaded — a
    refresh mid-generation, or a second tab — knows there is something to
    attach to without having to guess an idempotency key. Without it, the only
    way to find a running job would be to send the message again, which is the
    one thing that must not happen.

    Shares `_live_job`'s definition of "in flight" with `begin_generation`, so
    what the interface shows as running and what the server will refuse a
    second generation for are the same fact. Two readings of that would mean a
    workspace that refuses to send while reporting nothing is running.
    """
    ws = repo.get_workspace(session, scope, workspace_id)
    job = _live_job(session, ws.id)
    if job is None:
        return None
    return job_status(session, scope, job.id)


def retry_generation(session, scope: repo.Scope, job_id: int) -> dict:
    """Try a failed generation again, as a NEW job.

    A new job with a derived key rather than a reset of the old one, and the
    reason is idempotency: the old key stands for an attempt that happened and
    failed, and reusing it would make the failed attempt unfindable. `:retry2`,
    `:retry3` and so on each stand for exactly one attempt, so pressing retry
    twice quickly still produces one generation per press and no more.

    A job that succeeded is not retried. Its answer is in the thread; asking
    again is a new message, not a retry.
    """
    from backend.models.playbook import PlaybookJob

    job = session.get(PlaybookJob, job_id)
    if job is None or job.tenant != scope.tenant:
        raise repo.NotFound(f"No generation {job_id}.")
    if job.state == "ready":
        raise repo.Invalid(
            "That generation succeeded. Its answer is already in the thread; "
            "ask again to produce another.")
    if job.finished_at is None:
        raise repo.Invalid(
            "That generation is still running. Stop it before trying again.")

    base = job.idempotency_key.split(":retry")[0]
    attempt = 2
    while repo.jobs_by_key(session, f"{base}:retry{attempt}",
                           workspace_id=job.workspace_id) is not None:
        attempt += 1
    return {"idempotency_key": f"{base}:retry{attempt}",
            "workspace_id": job.workspace_id, "retry_of": job.id}


def job_by_key(session, scope: repo.Scope, workspace_id: int,
               idempotency_key: str) -> dict:
    """Find the generation a client already knows the key of.

    The client mints the idempotency key before it sends, so this is how a
    synchronous generation becomes stoppable: the browser asks which job its own
    key resolved to and can then stop it. Without this the stop button would
    have nothing to name until the work it wants to stop had already finished.

    Scoped to the workspace the caller is looking at, because that is what a
    key means. Resolving it across workspaces once handed a client the id of a
    generation in a different conversation.
    """
    ws = repo.get_workspace(session, scope, workspace_id)
    job = repo.jobs_by_key(session, idempotency_key, workspace_id=ws.id)
    if job is None or job.tenant != scope.tenant:
        raise repo.NotFound("No generation is running under that key.")
    return job_status(session, scope, job.id)


def request_cancel(session, scope: repo.Scope, job_id: int) -> dict:
    """Ask a running generation to stop.

    Sets a flag rather than killing anything. The generating request reads it
    between steps and raises, so it stops at a point where nothing is
    half-written — a version is written last, so a cancelled run leaves the
    previous version exactly as it was.

    Cancelling a finished job is not an error; it says so and changes nothing.
    A version that was already written is not withdrawn by a stop pressed after
    it landed.
    """
    from backend.models.playbook import PlaybookJob

    job = session.get(PlaybookJob, job_id)
    if job is None or job.tenant != scope.tenant:
        raise repo.NotFound(f"No generation {job_id}.")
    if job.finished_at is not None or job.state in {"ready", "failed",
                                                    "cancelled"}:
        return {"id": job.id, "state": job.state, "cancelled": job.cancelled,
                "message": "That generation had already finished. "
                           "Nothing was undone."}
    job.cancelled = True
    session.flush()
    return {"id": job.id, "state": job.state, "cancelled": True,
            "message": "Stopping. Nothing will be saved."}


def cancellation_watcher(job_id: int):
    """A callable that answers "has the user pressed stop?" from OUTSIDE.

    It has to open its own session: the generating request holds a transaction
    that cannot see a flag another request has since committed. Reading through
    the generator's own session would return the value as it stood when the
    generation began, which is exactly the moment the user had not yet pressed
    anything.
    """
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookJob

    def cancelled() -> bool:
        try:
            with get_session() as session:
                job = session.get(PlaybookJob, job_id)
                return bool(job and job.cancelled)
        except Exception:
            # A watcher that cannot read the flag must not stop the work it is
            # watching. The generation continues; the stop button is what is
            # broken, and it says so by not working rather than by killing a
            # run the user did not cancel.
            return False

    return cancelled
