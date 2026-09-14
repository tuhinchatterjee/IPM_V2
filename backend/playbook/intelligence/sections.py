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


def sync(session, artifact_id: int, doc: D.Document, *,
         version: int) -> list[PlaybookDocumentSection]:
    """Bring stored section rows into line with a version of the document.

    Matching is by key first and by heading second, so a retitle keeps its row
    and everything attached to it. A section whose content changed has its
    `last_changed_version` moved and any completed review reopened — a
    reviewer signed off on text that no longer exists, and pretending
    otherwise is how a stale approval ends up on a committee paper.
    """
    stored = (session.query(PlaybookDocumentSection)
              .filter(PlaybookDocumentSection.artifact_id == artifact_id)
              .order_by(PlaybookDocumentSection.ordinal).all())
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
            row.last_changed_version = version
            if row.reviewed_at is not None:
                row.reviewed_at = None
                row.status = NEEDS_REVIEW
                row.stale_reason = (
                    f"reviewed at version {row.last_changed_version - 1}; "
                    "the section has changed since")

        row.heading = fact.heading
        row.ordinal = fact.ordinal
        row.content_hash = fact.content_hash
        row.word_count = fact.word_count
        if row.status in ("", DRAFT):
            row.status = GENERATED if fact.substantive else DRAFT
        seen.add(row.section_key)
        written.append(row)

    # A section the document no longer has is not deleted: its review history
    # is evidence of what was once in the paper. It is marked instead.
    for key, row in rows.items():
        if key not in seen and row.status != STALE:
            row.status = STALE
            row.stale_reason = f"not present in version {version}"
    session.flush()
    return written


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
