"""
Building the Playbook demonstration. Playbook §13, §14.

Thirty exported analyses and three complete workspaces, seeded through the same
persistence the product uses for real records — the same tables, the same
ingestion, the same renderers, the same validation. A demonstration assembled
by writing rows directly would be a demonstration of something other than the
product.

No provider call
----------------
`backend/demo/seed.py` states the rule and this follows it: pre-answering the
questions a presenter is about to ask live is what §26 forbids. Every document
here is rendered deterministically by `backend/playbook/render`, and every
seeded assistant turn carries `origin="seed_fixture"` with no model recorded,
because no model wrote it.

Idempotent, and why that is not optional
----------------------------------------
`reseed` is safe to run repeatedly: an existing workspace with the current seed
version is left alone rather than duplicated. The reason is written in
`backend/demo/workspace.py` — this repository's development database once held
2,079 identically named Projects, every one created by a passing test, and every
one of them would have been on screen in front of a client.

Edited demonstration threads are preserved. A workspace whose message count no
longer matches what was seeded has been used, and using it is what it is for.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from backend.models.playbook import PlaybookWorkspace
from backend.playbook import capabilities, library, render, seed_exports, seed_threads, store, validate
from backend.playbook import document as D
from backend.playbook import repository as repo

logger = logging.getLogger(__name__)

SEED_VERSION = "1.0.0"

#: What each workspace produces. A report in Word and PDF, and — where the
#: history shows one being asked for — a deck.
REPORT_FORMATS = ("docx", "pdf")
DECK_FORMATS = ("pptx",)


class SeedResult(dict):
    """What a seeding run did, in numbers a caller can assert on."""


def _existing(session, scope: repo.Scope, title: str) -> PlaybookWorkspace | None:
    return session.execute(
        select(PlaybookWorkspace).where(
            PlaybookWorkspace.tenant == scope.tenant,
            PlaybookWorkspace.title == title,
        )
    ).scalars().first()


def seed_exports_library(session, scope: repo.Scope) -> dict:
    """The thirty demonstration analyses. Idempotent by content hash."""
    created = duplicate = 0
    by_title: dict[str, int] = {}
    for snapshot in seed_exports.catalogue():
        snapshot.demo_origin = True
        result = library.create(session, scope, snapshot,
                                seed_version=SEED_VERSION)
        by_title[snapshot.title] = result.revision_id
        if result.duplicate:
            duplicate += 1
        else:
            created += 1
    return {"created": created, "already_present": duplicate,
            "revision_ids": by_title}


def _render_and_store(session, scope: repo.Scope, ws, artifact, version,
                      doc: D.Document, formats: tuple[str, ...],
                      slug: str) -> list[str]:
    """Render, validate, persist. A file that fails validation is not stored.

    The same rule the live path follows: nothing is labelled ready because it
    was produced. If a seeded document will not reopen and reconcile, that is a
    defect in the renderer and the seeding should fail loudly rather than put a
    broken file behind a download button.
    """
    written: list[str] = []
    for fmt in formats:
        cap = capabilities.require(fmt)
        content = render.render(doc, fmt)
        result = validate.validate(content, fmt, doc)
        if not result.ok:
            raise RuntimeError(
                f"seeded {fmt} for {artifact.title} failed validation: "
                + "; ".join(result.issues))
        filename = f"{slug}-v{version.version}.{fmt}"
        stored = store.put_artifact(ws.id, artifact.id, version.version,
                                    filename, content)
        repo.add_file(session, version, fmt=fmt, bytes_path=stored.relative,
                      mime=cap.mime, filename=filename,
                      size_bytes=stored.size_bytes, sha256=stored.sha256,
                      renderer=capabilities.LOCAL, validated=True)
        written.append(fmt)
    return written


def _slug(text: str) -> str:
    keep = "".join(c.lower() if c.isalnum() else "-" for c in text)
    while "--" in keep:
        keep = keep.replace("--", "-")
    return keep.strip("-")[:60] or "report"


def seed_workspace(session, scope: repo.Scope, spec: seed_threads.ThreadSpec,
                   export_revisions: dict[str, int]) -> dict:
    """One complete demonstration workspace, or nothing if it already exists."""
    from backend.playbook import service

    if _existing(session, scope, spec.title) is not None:
        return {"title": spec.title, "created": False,
                "reason": "already present"}

    ws = repo.create_workspace(
        session, scope, title=spec.title,
        document_family=spec.document_family,
        demo_origin=True, seed_version=SEED_VERSION)
    ws.state_summary = spec.summary

    # Sources go through the real ingestion, so their chunks, locators and
    # manifests are what the parsers actually produced.
    source_ids: list[int] = []
    for position, source in enumerate(spec.sources):
        row = service.add_source(session, scope, ws.id,
                                 filename=source.filename,
                                 content=source.content,
                                 source_role=source.role)
        source_ids.append(row.id)
        repo.attach(session, ws.id, source_id=row.id, position=position)

    attached_revisions = []
    for position, title in enumerate(spec.export_titles):
        revision_id = export_revisions.get(title)
        if revision_id is None:
            raise RuntimeError(
                f"{spec.title} attaches {title!r}, which is not in the "
                "demonstration export catalogue.")
        repo.attach(session, ws.id, export_revision_id=revision_id,
                    position=len(source_ids) + position)
        attached_revisions.append(revision_id)

    artifact = repo.create_artifact(session, ws.id, kind="report",
                                    title=spec.title)
    manifest = {"sources": source_ids, "export_revisions": attached_revisions,
                "complete": True, "origin": "seed"}

    v1 = repo.new_version(session, artifact, content=spec.v1.as_dict(),
                          source_manifest=manifest,
                          content_hash=spec.v1.content_hash(),
                          change_summary="First draft.",
                          origin="seed_fixture")
    _render_and_store(session, scope, ws, artifact, v1, spec.v1,
                      REPORT_FORMATS, _slug(spec.title))

    change_set = repo.create_change_set(session, ws.id, message_id=None,
                                        base_version_id=v1.id,
                                        items=spec.change_items)
    for item in repo.change_items(session, change_set.id):
        item.status = ("applied" if item.stable_id in spec.approved
                       else "rejected")

    v2 = repo.new_version(session, artifact, content=spec.v2.as_dict(),
                          source_manifest=manifest,
                          content_hash=spec.v2.content_hash(),
                          change_summary=spec.v2_summary,
                          applied_change_item_ids=list(spec.approved),
                          base_version_id=v1.id, origin="seed_fixture")
    _render_and_store(session, scope, ws, artifact, v2, spec.v2,
                      REPORT_FORMATS, _slug(spec.title))

    deck_id = None
    if spec.deck_from_v2:
        deck = repo.create_artifact(
            session, ws.id, kind="presentation",
            title=f"{spec.title} — committee deck",
            derived_from_artifact_id=artifact.id,
            derived_from_version_id=v2.id)
        deck_version = repo.new_version(
            session, deck, content=spec.v2.as_dict(),
            source_manifest={**manifest, "from_report_version": v2.version},
            content_hash=spec.v2.content_hash(),
            change_summary=f"Built from report version {v2.version}.",
            origin="seed_fixture")
        _render_and_store(session, scope, ws, deck, deck_version, spec.v2,
                          DECK_FORMATS, _slug(spec.title) + "-deck")
        deck_id = deck.id

    # The conversation last, so a message referring to a version refers to one
    # that exists.
    version_by_number = {1: v1.id, 2: v2.id}
    for turn in spec.turns:
        content: dict = {"text": turn.text}
        if turn.role == "assistant":
            content["markdown"] = turn.text
            if turn.notes:
                content["notes"] = list(turn.notes)
            if turn.version:
                content["artifact_id"] = artifact.id
                content["version"] = turn.version
                content["version_id"] = version_by_number[turn.version]
        repo.add_message(
            session, ws.id, role=turn.role, content=content,
            # A seeded assistant turn is a fixture and says so. No model is
            # recorded against it, because none wrote it.
            origin="user" if turn.role == "user" else "seed_fixture")

    repo.touch(session, ws, summary=spec.summary)
    return {"title": spec.title, "created": True, "workspace_id": ws.id,
            "artifact_id": artifact.id, "deck_id": deck_id,
            "versions": 2, "messages": len(spec.turns),
            "sources": len(source_ids),
            "attached_analyses": len(attached_revisions)}


def reseed(session, scope: repo.Scope) -> SeedResult:
    """Seed the whole demonstration. Safe to run repeatedly."""
    exports = seed_exports_library(session, scope)
    workspaces = [
        seed_workspace(session, scope, spec, exports["revision_ids"])
        for spec in seed_threads.threads()
    ]
    result = SeedResult(
        seed_version=SEED_VERSION,
        exports=exports["created"],
        exports_already_present=exports["already_present"],
        exports_total=len(exports["revision_ids"]),
        workspaces=workspaces,
    )
    logger.info("Playbook demonstration seeded: %s exports, %s workspaces",
                result["exports_total"],
                sum(1 for w in workspaces if w["created"]))
    return result


def status(session, scope: repo.Scope) -> dict:
    """What is present, for the readiness check."""
    counts = library.counts_by_module(session, scope)
    titles = [spec.title for spec in seed_threads.threads()]
    present = [t for t in titles if _existing(session, scope, t) is not None]
    return {
        "seed_version": SEED_VERSION,
        "exports_by_module": counts,
        "exports_total": sum(counts.values()),
        "workspaces_expected": titles,
        "workspaces_present": present,
        "ready": len(present) == len(titles) and sum(counts.values()) >= 30,
    }
