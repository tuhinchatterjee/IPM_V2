"""The papers people write, as opposed to the reports CreditProbe generates.

The distinction this module rests on
-------------------------------------
A generated report is a download. It is assembled from results, reproducible
from its own evidence register, owned by nobody and edited by nobody — ask
for it twice and you get the same file. The product already produces several
and they are not documents.

A Document is the other thing. It is the paper a credit officer drafts for a
committee: written by a person, edited over a fortnight, given evidence to
stand on, sent for review, argued about in comments and eventually approved.
It has an author, a status, a life and a history, and none of those are
properties a generated file can have.

What §19 asks for, and how each part is met
--------------------------------------------
* **An editable central document.** Markdown in one column. Saved by
  autosave or by hand; both land in the same place.
* **A section outline.** DERIVED from the headings in the body rather than
  stored beside it. Stored separately the two drift the first time somebody
  renames a heading, and the outline is what a reviewer navigates by.
* **Supporting evidence.** Two kinds, deliberately: `evidence` references
  things that live elsewhere in the product (an analysis, an investigation,
  a validation run) by id, and `attachments` hold actual bytes for the files
  that do not — an evidence workbook, a chart bundle, a specification
  extract.
* **Revision history.** A revision is a ROW. §19 requires an approved record
  to be an immutable snapshot and an edit to create a new draft revision,
  which a version column with an update path cannot express: the moment
  editing is possible in place, "what did the committee approve?" is a
  question about backup tapes.
* **Comments.** The platform `comments` table, keyed on "document". One
  comment table for the installation, which is the same argument the
  validation commentary makes.

The seed contract
------------------
§24: a seed refresh updates machine-owned content by stable id, preserves
user edits, and shows a dry-run summary. `seed_key` is the stable id,
`seeded` marks machine authorship, and `user_edited` is the flag that makes
the seeder leave a row alone. A seeder that overwrites somebody's draft
because the title matched is a seeder nobody runs twice.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.models.platform import (
    DOC_APPROVED,
    DOC_ARCHIVED,
    DOC_DRAFT,
    DOC_IN_REVIEW,
    DOCUMENT_STATUS_LABEL,
    DOCUMENT_STATUSES,
    Document,
    DocumentAttachment,
)

DOCUMENTS_VERSION = "retail-documents-1.0.0"

#: What a supporting file is FOR, so the right-hand rail can group them.
ROLES: tuple[str, ...] = ("workbook", "analysis", "specification", "charts",
                          "note", "lineage", "other")

#: Status transitions a person may make. Approval is deliberately not
#: reachable from a draft: §19's lifecycle goes through review, and a
#: one-click draft-to-approved would make the review state decorative.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    DOC_DRAFT: (DOC_IN_REVIEW, DOC_ARCHIVED),
    DOC_IN_REVIEW: (DOC_APPROVED, DOC_DRAFT, DOC_ARCHIVED),
    DOC_APPROVED: (DOC_ARCHIVED,),
    DOC_ARCHIVED: (DOC_DRAFT,),
}

#: The largest supporting file this table will hold. Anything above it is a
#: signal that the document should reference a generated export rather than
#: carry a copy of one, and a row that silently truncated a workbook would
#: be worse than a refusal.
LARGEST_ATTACHMENT = 12 * 1024 * 1024


class DocumentError(RuntimeError):
    """A document was asked for in a state it cannot be in."""


class NotFound(DocumentError):
    """No such document."""


class Immutable(DocumentError):
    """An approved record cannot be edited. A new revision can be created."""


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value or "")


HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)


def outline(body: str) -> list[dict[str, Any]]:
    """The section outline, computed from the body's headings.

    Derived rather than stored, so it cannot disagree with the document it
    describes. The anchor is a slug a link can jump to; duplicates get a
    suffix, because two sections called "Findings" in one paper is ordinary
    and an outline where both entries scroll to the first one is not.
    """
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for match in HEADING.finditer(body or ""):
        title = match.group(2).strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "section"
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        out.append({"level": len(match.group(1)), "title": title,
                    "anchor": slug})
    return out


def words(body: str) -> int:
    return len((body or "").split())


def get(session: Session, document_id: int) -> Document:
    found = session.execute(
        select(Document)
        .options(selectinload(Document.attachments))
        .where(Document.id == document_id)).scalar_one_or_none()
    if found is None:
        raise NotFound(f"Document {document_id} does not exist.")
    return found


def header(session: Session, row: Document) -> dict[str, Any]:
    """What a LIST row needs. Never the body — a list of forty papers that
    carried forty bodies is a megabyte of text to render forty titles."""
    from backend.services import workflow as wf

    comments = wf.comments("document", str(row.id))
    return {
        "documents_version": DOCUMENTS_VERSION,
        "id": row.id,
        "title": row.title,
        "kind": row.kind,
        "product": row.product,
        "status": row.status,
        "status_label": DOCUMENT_STATUS_LABEL.get(row.status, row.status),
        "as_of": row.as_of,
        "summary": row.summary,
        "owner": row.owner_name,
        "owner_id": row.owner_id,
        "project_id": row.project_id,
        "revision": row.revision,
        "is_current": row.is_current,
        # §19: a current/historical badge. A stale document about a smaller
        # book stays traceable and must not be mistaken for the live one.
        "badge": "Current" if row.is_current else f"Revision {row.revision}",
        "supersedes_id": row.supersedes_id,
        "data_versions": dict(row.data_versions or {}),
        "evidence_count": len(row.evidence or []),
        "attachment_count": len(row.attachments or []),
        "comment_count": len(comments),
        "open_comments": sum(1 for one in comments if not one.get("resolved")),
        "seeded": row.seeded,
        "user_edited": row.user_edited,
        "words": words(row.body),
        "sections": len(outline(row.body)),
        "approved_at": _stamp(row.approved_at),
        "approved_by": row.approved_by,
        "created_at": _stamp(row.created_at),
        "updated_at": _stamp(row.updated_at),
    }


def body_of(session: Session, row: Document) -> dict[str, Any]:
    """The whole document, for the detail screen."""
    from backend.services import workflow as wf

    return {
        **header(session, row),
        "body": row.body,
        "outline": outline(row.body),
        "evidence": list(row.evidence or []),
        "attachments": [{
            "id": one.id, "filename": one.filename, "label": one.label,
            "role": one.role, "content_type": one.content_type,
            "size_bytes": one.size_bytes,
            "href": f"/workspace/documents/attachments/{one.id}",
            "created_at": _stamp(one.created_at),
        } for one in sorted(row.attachments, key=lambda a: a.id)],
        "comments": wf.comments("document", str(row.id)),
        "can_edit": row.status != DOC_APPROVED,
        "why_not_editable": (
            "This revision is approved, and an approved record is an "
            "immutable snapshot of what was signed. Create a revision to "
            "carry on working; the approved text keeps its own row."
            if row.status == DOC_APPROVED else ""),
        "transitions": list(TRANSITIONS.get(row.status, ())),
        "statuses": [{"status": s, "label": DOCUMENT_STATUS_LABEL[s]}
                     for s in DOCUMENT_STATUSES],
        "roles": list(ROLES),
    }


def listing(session: Session, *, product: str = "", status: str = "",
            kind: str = "", project_id: int | None = None,
            owner: str = "", search: str = "", current_only: bool = True,
            limit: int = 100) -> list[Document]:
    query = select(Document).options(selectinload(Document.attachments))
    if current_only:
        query = query.where(Document.is_current.is_(True))
    if product:
        query = query.where(Document.product == product)
    if status:
        query = query.where(Document.status == status)
    if kind:
        query = query.where(Document.kind == kind)
    if project_id is not None:
        query = query.where(Document.project_id == project_id)
    if owner:
        query = query.where(Document.owner_name == owner)
    if search:
        like = f"%{search.lower()}%"
        query = query.where(
            func.lower(Document.title).like(like)
            | func.lower(Document.summary).like(like)
            | func.lower(Document.body).like(like))
    return list(session.execute(
        query.order_by(Document.updated_at.desc()).limit(limit))
        .scalars().all())


def facets(session: Session) -> dict[str, Any]:
    """What the filter bar can offer, read from the rows rather than declared.

    A hard-coded product list is a filter that stops matching the first time
    a paper is written about something new, and it fails silently — the
    option is simply absent and nobody knows to look for it.
    """
    def distinct(column: Any) -> list[str]:
        return [one for (one,) in session.execute(
            select(column).where(Document.is_current.is_(True))
            .where(column != "").distinct().order_by(column)).all()]

    return {
        "products": distinct(Document.product),
        "kinds": distinct(Document.kind),
        "owners": distinct(Document.owner_name),
        "statuses": [{"status": s, "label": DOCUMENT_STATUS_LABEL[s]}
                     for s in DOCUMENT_STATUSES],
    }


def revisions(session: Session, document_id: int) -> list[dict[str, Any]]:
    """Every revision of this paper, newest first.

    Walks the supersedes chain in both directions from whichever revision
    was asked for, so opening an old one still shows the whole history.
    """
    row = get(session, document_id)
    chain = [row]
    while chain[0].supersedes_id:
        earlier = session.get(Document, chain[0].supersedes_id)
        if earlier is None:
            break
        chain.insert(0, earlier)
    while True:
        later = session.execute(
            select(Document).where(Document.supersedes_id == chain[-1].id)
        ).scalars().first()
        if later is None:
            break
        chain.append(later)
    return [header(session, one) for one in reversed(chain)]


def create(session: Session, *, title: str, kind: str = "",
           product: str = "", body: str = "", summary: str = "",
           as_of: str = "", project_id: int | None = None,
           owner_id: int | None = None, owner_name: str = "",
           data_versions: dict[str, Any] | None = None,
           evidence: list[dict[str, Any]] | None = None,
           seed_key: str = "", seeded: bool = False,
           status: str = DOC_DRAFT) -> Document:
    if not (title or "").strip():
        raise DocumentError("A document needs a title.")
    if status not in DOCUMENT_STATUSES:
        raise DocumentError(
            f"{status!r} is not a document status. They are: "
            + ", ".join(DOCUMENT_STATUSES))
    row = Document(
        title=title.strip(), kind=kind, product=product, status=status,
        as_of=as_of, summary=summary, body=body, project_id=project_id,
        owner_id=owner_id, owner_name=owner_name,
        data_versions=dict(data_versions or {}),
        evidence=list(evidence or []), seed_key=seed_key, seeded=seeded,
        revision=1, is_current=True)
    session.add(row)
    session.flush()
    return row


def save(session: Session, document_id: int, *, title: str | None = None,
         body: str | None = None, summary: str | None = None,
         kind: str | None = None, product: str | None = None,
         as_of: str | None = None, project_id: int | None = None,
         evidence: list[dict[str, Any]] | None = None,
         by_a_person: bool = True) -> Document:
    """Edit a draft in place. Refused on an approved revision.

    `by_a_person` is what stops the seeder erasing somebody's work: a human
    save sets `user_edited`, and the seeder skips any row carrying it.
    """
    row = get(session, document_id)
    if row.status == DOC_APPROVED:
        raise Immutable(
            f"Document {document_id} is approved. An approved record is an "
            "immutable snapshot of what was signed; create a revision to "
            "carry on working.")
    if title is not None:
        row.title = title.strip() or row.title
    if body is not None:
        row.body = body
    if summary is not None:
        row.summary = summary
    if kind is not None:
        row.kind = kind
    if product is not None:
        row.product = product
    if as_of is not None:
        row.as_of = as_of
    if project_id is not None:
        row.project_id = project_id or None
    if evidence is not None:
        row.evidence = list(evidence)
    if by_a_person:
        row.user_edited = True
    row.updated_at = _now()
    session.flush()
    return row


def revise(session: Session, document_id: int, *, owner_id: int | None = None,
           owner_name: str = "") -> Document:
    """A new draft revision carrying this one's content forward.

    The old row keeps everything — its text, its status, its approval and
    its attachments — and stops being current. That is what makes "what did
    the committee approve?" answerable a year later.
    """
    row = get(session, document_id)
    made = Document(
        title=row.title, kind=row.kind, product=row.product,
        status=DOC_DRAFT, as_of=row.as_of, summary=row.summary,
        body=row.body, project_id=row.project_id,
        owner_id=owner_id or row.owner_id,
        owner_name=owner_name or row.owner_name,
        data_versions=dict(row.data_versions or {}),
        evidence=list(row.evidence or []),
        revision=row.revision + 1, is_current=True, supersedes_id=row.id,
        seed_key=row.seed_key, seeded=False, user_edited=False)
    row.is_current = False
    session.add(made)
    session.flush()
    # Supporting files follow the revision: a paper whose evidence stayed
    # behind on the previous version is a paper a reviewer cannot check.
    for one in row.attachments:
        session.add(DocumentAttachment(
            document_id=made.id, filename=one.filename, label=one.label,
            content_type=one.content_type, role=one.role,
            size_bytes=one.size_bytes, content=one.content))
    session.flush()
    return made


def set_status(session: Session, document_id: int, status: str, *,
               by: str = "") -> Document:
    row = get(session, document_id)
    if status not in DOCUMENT_STATUSES:
        raise DocumentError(
            f"{status!r} is not a document status. They are: "
            + ", ".join(DOCUMENT_STATUSES))
    allowed = TRANSITIONS.get(row.status, ())
    if status not in allowed:
        raise DocumentError(
            f"A {DOCUMENT_STATUS_LABEL[row.status].lower()} document cannot "
            f"go straight to {DOCUMENT_STATUS_LABEL[status].lower()}. From "
            f"here it can go to: "
            + (", ".join(DOCUMENT_STATUS_LABEL[s].lower() for s in allowed)
               or "nowhere"))
    row.status = status
    if status == DOC_APPROVED:
        row.approved_at = _now()
        row.approved_by = by
    row.updated_at = _now()
    session.flush()
    return row


def attach(session: Session, document_id: int, *, filename: str,
           content: bytes, content_type: str = "", label: str = "",
           role: str = "other") -> DocumentAttachment:
    row = get(session, document_id)
    if row.status == DOC_APPROVED:
        raise Immutable(
            f"Document {document_id} is approved. Its evidence is part of "
            "what was signed; create a revision to add to it.")
    safe = (filename or "attachment").strip().replace("/", "_")
    if len(content) > LARGEST_ATTACHMENT:
        raise DocumentError(
            f"{safe} is {len(content):,} bytes and the limit here is "
            f"{LARGEST_ATTACHMENT:,}. A file this large belongs in a "
            "generated export the document references rather than in a copy "
            "it carries.")
    made = DocumentAttachment(
        document_id=row.id, filename=safe, label=label or safe,
        content_type=content_type or "application/octet-stream",
        role=role if role in ROLES else "other",
        size_bytes=len(content), content=content)
    session.add(made)
    session.flush()
    return made


def attachment(session: Session, attachment_id: int) -> DocumentAttachment:
    found = session.get(DocumentAttachment, attachment_id)
    if found is None:
        raise NotFound(f"Attachment {attachment_id} does not exist.")
    return found


def remove(session: Session, document_id: int) -> None:
    """Archive rather than delete. A paper somebody wrote is not scratch."""
    row = get(session, document_id)
    row.status = DOC_ARCHIVED
    row.updated_at = _now()
    session.flush()


def support_bundle(session: Session, document_id: int) -> tuple[bytes, str]:
    """Every supporting file, plus the paper itself, as one zip.

    §19 asks for a support-bundle download. The point is a reviewer who
    wants the evidence without clicking eight links, so the bundle carries
    the document text and a manifest naming what each file is and where it
    came from — a zip of eight spreadsheets with no manifest is eight
    spreadsheets.
    """
    row = get(session, document_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(f"{_slug(row.title)}.md", row.body or "")
        lines = [
            f"# {row.title}",
            "",
            f"Kind: {row.kind or 'not recorded'}",
            f"Product: {row.product or 'retail'}",
            f"Status: {DOCUMENT_STATUS_LABEL.get(row.status, row.status)}",
            f"As of: {row.as_of or 'not recorded'}",
            f"Owner: {row.owner_name or 'not recorded'}",
            f"Revision: {row.revision}"
            + ("" if row.is_current else " (superseded)"),
            "",
            "## Data and model versions",
        ]
        for key, value in sorted((row.data_versions or {}).items()):
            lines.append(f"- {key}: {value}")
        if not row.data_versions:
            lines.append("- none recorded")
        lines += ["", "## Linked evidence"]
        for one in (row.evidence or []):
            lines.append(f"- {one.get('kind', 'item')}: "
                         f"{one.get('label') or one.get('id')}"
                         + (f" ({one.get('href')})" if one.get("href") else ""))
        if not row.evidence:
            lines.append("- none linked")
        lines += ["", "## Files in this bundle"]
        for one in sorted(row.attachments, key=lambda a: a.id):
            lines.append(f"- {one.filename} — {one.label} "
                         f"({one.role}, {one.size_bytes:,} bytes)")
            bundle.writestr(f"evidence/{one.filename}", one.content)
        if not row.attachments:
            lines.append("- none attached")
        bundle.writestr("MANIFEST.md", "\n".join(lines) + "\n")
    return buffer.getvalue(), f"{_slug(row.title)}-support.zip"


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "document").lower()).strip("-")


__all__ = [
    "DOCUMENTS_VERSION", "Document", "DocumentAttachment", "DocumentError",
    "Immutable", "LARGEST_ATTACHMENT", "NotFound", "ROLES", "TRANSITIONS",
    "attach", "attachment", "body_of", "create", "facets", "get", "header",
    "listing", "outline", "remove", "revise", "revisions", "save",
    "set_status", "support_bundle", "words",
]
