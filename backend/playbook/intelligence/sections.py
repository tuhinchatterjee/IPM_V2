"""Section identity that survives a retitle, and the statistics of a document.

Why a key and not the heading
-----------------------------
`merge._renamed_target` deliberately allows an author to rename the section it
was asked to edit — renaming a section is part of editing it. Keying review
state, reviewers and page ranges on heading text would therefore reset all of
them every time somebody sharpened a title, which is the opposite of what a
governed document needs.

So the key is derived once, from the heading a section FIRST had, and then
carried. A retitle updates `heading` and leaves `section_key` alone.

Statistics come from the artifact, not from a guess
---------------------------------------------------
Page count is read from a rendered file, never estimated from text length. §11
is explicit about this, and the module says which representation a number came
from rather than leaving a reader to assume.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.models.playbook import PlaybookDocumentSection
from backend.playbook import document as D
from backend.playbook import merge

DRAFT = "draft"
GENERATED = "generated"
EVIDENCE_INCOMPLETE = "evidence_incomplete"
NEEDS_REVIEW = "needs_review"
READY_FOR_REVIEW = "ready_for_review"
APPROVED = "approved"
STALE = "stale"

STATUSES = (DRAFT, GENERATED, EVIDENCE_INCOMPLETE, NEEDS_REVIEW,
            READY_FOR_REVIEW, APPROVED, STALE)

#: A section is substantively complete when it has real prose, not a heading
#: with a sentence under it. Twenty words is the smallest thing that reads as
#: a written section rather than a placeholder.
SUBSTANTIVE_WORDS = 20


def key_for(heading: str, ordinal: int) -> str:
    """A stable key from the heading a section first had.

    Leading numbering is stripped, because "4. Methodology" becoming
    "5. Methodology" when a section is inserted above it is a renumbering and
    not a different section. The ordinal is a tiebreak for two sections that
    normalise to the same words, which is rare and must not collide.
    """
    base = re.sub(r"^\s*\d+(\.\d+)*[.)]?\s*", "", (heading or "").strip())
    base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return f"{base or 'section'}-{ordinal}"[:128]


@dataclass(frozen=True)
class SectionFacts:
    """What can be said about a section from the document alone."""

    section_key: str
    heading: str
    ordinal: int
    content_hash: str
    word_count: int
    table_count: int
    has_sources: bool

    @property
    def substantive(self) -> bool:
        return self.word_count >= SUBSTANTIVE_WORDS or self.table_count > 0


def facts(doc: D.Document) -> list[SectionFacts]:
    """Read a canonical document into per-section facts. No model, no guess."""
    out: list[SectionFacts] = []
    for ordinal, section in enumerate(doc.sections, start=1):
        words = len(section.text.split())
        tables = [b for b in section.blocks if b.kind == D.TABLE]
        for block in section.blocks:
            if block.kind in (D.BULLETS, D.NUMBERS):
                words += sum(len(str(i).split())
                             for i in block.data.get("items", []))
        out.append(SectionFacts(
            section_key=key_for(section.heading, ordinal),
            heading=section.heading, ordinal=ordinal,
            content_hash=merge.section_hash(section), word_count=words,
            table_count=len(tables),
            has_sources=any(b.sources for b in section.blocks)))
    return out


def rows_for(session, artifact_id: int) -> list[PlaybookDocumentSection]:
    """Every stored section of one document, in reading order."""
    return (session.query(PlaybookDocumentSection)
            .filter(PlaybookDocumentSection.artifact_id == artifact_id)
            .order_by(PlaybookDocumentSection.ordinal).all())


def sync(session, artifact_id: int, doc: D.Document, *,
         version: int) -> list[PlaybookDocumentSection]:
    """Bring stored section rows into line with a version of the document.

    Matching is by key first and by heading second, so a retitle keeps its row
    and everything attached to it. A section whose content changed has its
    `last_changed_version` moved and any completed review reopened — a
    reviewer signed off on text that no longer exists, and pretending
    otherwise is how a stale approval ends up on a committee paper.
    """
    stored = rows_for(session, artifact_id)
    rows = {r.section_key: r for r in stored}
    by_heading = {r.heading: r for r in stored if r.heading}
    # Positional fallback, admitted only when nothing else moved — the same
    # discipline `merge._renamed_target` uses, and for the same reason: a
    # retitle is inside the scope of editing a section, but guessing which
    # section a new name belongs to is the one mistake worth refusing.
    live = [r for r in stored if r.status != STALE]
    by_ordinal = ({r.ordinal: r for r in live}
                  if len(live) == len(doc.sections) else {})

    seen: set[str] = set()
    written: list[PlaybookDocumentSection] = []
    for fact in facts(doc):
        row = (rows.get(fact.section_key) or by_heading.get(fact.heading)
               or by_ordinal.get(fact.ordinal))
        if row is not None and row.section_key in seen:
            row = None          # already claimed by an earlier section
        if row is None:
            row = PlaybookDocumentSection(
                artifact_id=artifact_id, section_key=fact.section_key,
                first_seen_version=version)
            session.add(row)
            rows[fact.section_key] = row
        elif row.content_hash and row.content_hash != fact.content_hash:
            previous = row.last_changed_version
            row.last_changed_version = version
            if row.reviewed_at is not None:
                row.stale_reason = (
                    f"reviewed at version {previous}; "
                    "the section has changed since")
                _record(session, row, NEEDS_REVIEW, row.stale_reason)

        row.heading = fact.heading
        row.ordinal = fact.ordinal
        row.content_hash = fact.content_hash
        row.word_count = fact.word_count
        # `not row.status` matters: a row that has been added but not yet
        # flushed has status None, because the column default applies at
        # flush. Checking only for "" and DRAFT meant a newly created section
        # never became GENERATED and every first version looked like a draft.
        if not row.status or row.status == DRAFT:
            row.status = GENERATED if fact.substantive else DRAFT
        seen.add(row.section_key)
        written.append(row)

    # A section the document no longer has is not deleted: its review history
    # is evidence of what was once in the paper. It is marked instead.
    for key, row in rows.items():
        if key not in seen and row.status != STALE:
            row.stale_reason = f"not present in version {version}"
            _record(session, row, STALE, row.stale_reason)
    session.flush()
    return written


def _record(session, row, to: str, reason: str) -> None:
    """A transition the DOCUMENT caused, written down like any other.

    `sync` bypasses the HUMAN_ONLY guard deliberately and only in this
    direction: a section going stale or needing review again is something the
    document did, not something a person claimed. It can never move a section
    INTO approved — that is what the guard protects.
    """
    from datetime import UTC, datetime

    row.history = list(row.history or []) + [{
        "at": datetime.now(UTC).isoformat(),
        "from": row.status or DRAFT, "to": to, "actor": "system",
        "reason": reason,
    }]
    row.status = to
    row.reviewed_at = None


def statistics(doc: D.Document, *, files: dict | None = None,
               validations: dict | None = None) -> dict:
    """§11's document statistics, each labelled with where it came from.

    Page count is read from a validated rendered file. If none exists the
    count is absent and says so, rather than being estimated from text length
    and presented as though it had been measured.
    """
    files = files or {}
    validations = validations or {}
    sections = facts(doc)
    tables = sum(s.table_count for s in sections)

    pages, page_source = None, "not rendered"
    for fmt in ("pdf", "docx"):
        checked = getattr(validations.get(fmt), "checked", {}) or {}
        if checked.get("pages"):
            pages, page_source = int(checked["pages"]), f"{fmt} (parsed back)"
            break

    return {
        "sections": len(sections),
        "words": sum(s.word_count for s in sections),
        "tables": tables,
        "pages": pages,
        "page_count_source": page_source,
        "formats": sorted(files),
        "sections_with_sources": sum(1 for s in sections if s.has_sources),
        "substantive_sections": sum(1 for s in sections if s.substantive),
    }


# ==========================================================================
# Status transitions — deterministic, and accountable to a person
# ==========================================================================
#
# A status that changes with no record of who changed it, when, or from what
# is not auditable, and "Approved" is exactly the status a governed document
# has to account for months later. So every transition is checked against a
# table, recorded in `history`, and — for the ones that are governance acts —
# refused without a named person.

class TransitionRefused(ValueError):
    """A status change that is not allowed, with the reason."""


#: What may follow what. Read as "from: the statuses it may become".
#:
#: The system moves a section between DRAFT, GENERATED, EVIDENCE_INCOMPLETE
#: and STALE as the document and its evidence change. A PERSON moves it
#: through review: ready for review, needs review, approved. Nothing may leave
#: APPROVED except by the document changing under it, which is exactly what
#: `sync` does when the content hash moves.
ALLOWED: dict[str, frozenset[str]] = {
    DRAFT: frozenset({GENERATED, EVIDENCE_INCOMPLETE, READY_FOR_REVIEW,
                      STALE}),
    GENERATED: frozenset({DRAFT, EVIDENCE_INCOMPLETE, READY_FOR_REVIEW,
                          NEEDS_REVIEW, STALE}),
    EVIDENCE_INCOMPLETE: frozenset({GENERATED, DRAFT, READY_FOR_REVIEW,
                                    STALE}),
    READY_FOR_REVIEW: frozenset({NEEDS_REVIEW, APPROVED, GENERATED, STALE}),
    NEEDS_REVIEW: frozenset({READY_FOR_REVIEW, GENERATED, APPROVED, STALE}),
    APPROVED: frozenset({NEEDS_REVIEW, STALE}),
    STALE: frozenset({DRAFT, GENERATED, READY_FOR_REVIEW}),
}

#: Transitions a person must own. Marking work reviewed or approved is a
#: governance act: a model may say a section looks finished, and may not
#: record that a human agreed.
HUMAN_ONLY = frozenset({READY_FOR_REVIEW, NEEDS_REVIEW, APPROVED})


#: The review table's own vocabulary, named rather than typed as literals in
#: three files that then have to agree.
REQUESTED, COMPLETE = "requested", "complete"


def _review_row(session, row):
    """Keep the review table in step with who is reviewing this section.

    The section carries `reviewer` for the pane that shows it; the review
    table is what the readiness score and the Review card count. Writing only
    one of them is how a dashboard ends up saying "0 / 0 reviews" beside a
    section that plainly names its reviewer.
    """
    from datetime import UTC, datetime

    from backend.models.playbook import PlaybookReview

    existing = (session.query(PlaybookReview)
                .filter(PlaybookReview.artifact_id == row.artifact_id,
                        PlaybookReview.section_key == row.section_key)
                .one_or_none())
    if not row.reviewer:
        if existing is not None:
            session.delete(existing)
        return None
    if existing is None:
        existing = PlaybookReview(
            workspace_id=_workspace_of(session, row),
            artifact_id=row.artifact_id, section_key=row.section_key,
            reviewer=row.reviewer, status=REQUESTED)
        session.add(existing)
    existing.reviewer = row.reviewer
    if row.status == APPROVED:
        existing.status = COMPLETE
        existing.completed_at = row.reviewed_at or datetime.now(UTC)
    elif existing.status == COMPLETE and row.status != APPROVED:
        # The text moved after sign-off, so the sign-off no longer stands.
        existing.status = REQUESTED
        existing.completed_at = None
    session.flush()
    return existing


def _workspace_of(session, row) -> int:
    from backend.models.playbook import PlaybookArtifact

    artifact = session.get(PlaybookArtifact, row.artifact_id)
    return artifact.workspace_id if artifact else 0


def transition(session, row, *, to: str, actor: str = "", reason: str = "",
               by_system: bool = False):
    """Move one section's status, and write down that it happened.

    `by_system` is how `sync` records the transitions the document itself
    causes — a section going STALE because it left the document, or needing
    review again because its text changed. Everything in HUMAN_ONLY refuses a
    system caller outright, which is the §27 boundary expressed as code rather
    than as a convention somebody has to remember.
    """
    from datetime import UTC, datetime

    if to not in STATUSES:
        raise TransitionRefused(
            f"{to!r} is not a section status. Expected one of: "
            + ", ".join(STATUSES))

    current = row.status or DRAFT
    if to == current:
        return row
    if to not in ALLOWED.get(current, frozenset()):
        raise TransitionRefused(
            f"A section that is {current!r} cannot become {to!r}. "
            f"From {current!r} it may become: "
            + ", ".join(sorted(ALLOWED.get(current, frozenset()))) + ".")
    if to in HUMAN_ONLY:
        if by_system:
            raise TransitionRefused(
                f"Moving a section to {to!r} is a person's decision. "
                "Nothing was changed.")
        if not (actor or "").strip():
            raise TransitionRefused(
                f"Moving a section to {to!r} records who did it. "
                "Nothing was changed.")

    row.history = list(row.history or []) + [{
        "at": datetime.now(UTC).isoformat(),
        "from": current, "to": to,
        "actor": "system" if by_system else (actor or "").strip()[:160],
        "reason": reason,
    }]
    row.status = to
    if to == APPROVED:
        row.reviewed_at = datetime.now(UTC)
    elif to in (NEEDS_REVIEW, STALE):
        row.reviewed_at = None
    # The review table follows the section. Approving completes the review;
    # reopening a section un-completes it, because a sign-off on text that has
    # since moved is not a sign-off.
    _review_row(session, row)
    session.flush()
    return row


def assign_reviewer(session, row, *, reviewer: str, actor: str):
    """Put a named person on a section. A governance act, so it names both.

    Assigning review is not the same as reviewing: the reviewer is recorded
    and the section moves to READY_FOR_REVIEW, but only that reviewer's own
    completion can approve it.
    """
    if not (actor or "").strip():
        raise TransitionRefused(
            "Assigning a reviewer records who assigned them. Nothing changed.")
    if not (reviewer or "").strip():
        raise TransitionRefused(
            "A section is reviewed by a named person. Nothing changed.")
    row.reviewer = reviewer.strip()[:160]
    _review_row(session, row)
    if row.status in ALLOWED and READY_FOR_REVIEW in ALLOWED[row.status]:
        transition(session, row, to=READY_FOR_REVIEW, actor=actor,
                   reason=f"assigned to {row.reviewer}")
    else:
        session.flush()
    return row


def _text_of(session, artifact_id: int, row) -> str:
    """The section's own text, from the current stored version.

    Read from the canonical document rather than from anything re-rendered:
    the canonical form is what the merge, the grounding check and the version
    hash all work from, so a pane showing anything else would be showing a
    reader something the system does not consider to be the document.
    """
    from backend.playbook import repository as repo

    versions = repo.versions(session, artifact_id)
    if not versions:
        return ""
    doc = D.Document.from_dict(versions[-1].content or {})
    for ordinal, section in enumerate(doc.sections, start=1):
        if key_for(section.heading, ordinal) == row.section_key \
                or section.heading == row.heading:
            return "\n\n".join(
                block.text for block in section.blocks if block.text)
    return ""


def detail(session, artifact_id: int, section_key: str,
           workspace_id: int) -> dict:
    """One section with everything attached to it, in one read.

    Metrics, findings, sources, reviewer state and history together — because
    a section pane that needs five round trips to answer "what is the state of
    this section" is a pane nobody keeps open.
    """
    from backend.models.playbook import (
        PlaybookFinding,
        PlaybookMetricBinding,
        PlaybookReview,
        PlaybookSource,
    )
    from backend.playbook.intelligence import binding as bind

    row = (session.query(PlaybookDocumentSection)
           .filter(PlaybookDocumentSection.artifact_id == artifact_id,
                   PlaybookDocumentSection.section_key == section_key)
           .one_or_none())
    if row is None:
        return {}

    bindings = (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id,
                        PlaybookMetricBinding.section_key == section_key)
                .all())
    findings = (session.query(PlaybookFinding)
                .filter(PlaybookFinding.workspace_id == workspace_id,
                        PlaybookFinding.section_key == section_key).all())
    reviews = (session.query(PlaybookReview)
               .filter(PlaybookReview.workspace_id == workspace_id,
                       PlaybookReview.section_key == section_key).all())
    locators = {b.source_locator for b in bindings if b.source_locator}
    sources = (session.query(PlaybookSource)
               .filter(PlaybookSource.workspace_id == workspace_id).all())

    return {
        "section_key": row.section_key,
        "heading": row.heading,
        "ordinal": row.ordinal,
        "status": row.status,
        "may_become": sorted(ALLOWED.get(row.status or DRAFT, frozenset())),
        "word_count": row.word_count,
        "page_from": row.page_from,
        "page_to": row.page_to,
        "reviewer": row.reviewer,
        "reviewed": row.reviewed_at is not None,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else "",
        "stale_reason": row.stale_reason,
        "first_seen_version": row.first_seen_version,
        "last_changed_version": row.last_changed_version,
        "history": list(row.history or []),
        # The moves the service would actually allow from here, and the
        # section's own text. Both exist so a pane can show what a person can
        # do and what they are deciding about, without a second round trip and
        # without offering a transition the service would refuse.
        "allowed": sorted(ALLOWED.get(row.status or DRAFT, frozenset())),
        "human_only": sorted(HUMAN_ONLY),
        "text": _text_of(session, artifact_id, row),
        "metrics": [{
            "id": b.id, "metric_id": b.metric_id,
            "label": b.label or b.metric_id,
            "value_in_document": b.value_in_document,
            "display_value": b.display_value,
            "governed": bind.is_governed(b),
            "method": b.binding_method,
            "source_locator": b.source_locator,
        } for b in bindings],
        "findings": [{
            "id": f.id, "reference": f.reference, "title": f.title,
            "severity": f.severity, "status": f.status,
            "blocking": f.blocking,
        } for f in findings],
        "reviews": [{
            "id": r.id, "reviewer": r.reviewer, "role": r.role,
            "status": r.status, "comment": r.comment,
        } for r in reviews],
        "sources": [{
            "id": s.id, "filename": s.filename, "status": s.status,
            "source_role": s.source_role,
            "cited": any(str(s.id) in loc or s.filename in loc
                         for loc in locators),
        } for s in sources],
    }
