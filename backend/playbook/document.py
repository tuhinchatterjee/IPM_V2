"""
The canonical document. Playbook §10, §11.

Why there is a document model at all
------------------------------------
The specification warns against forcing long-form writing through a rigid,
minimal JSON schema — and it is right, because a model asked to emit
`{"sections":[{"text":"..."}]}` writes like a form rather than like an author.
But without *some* shared structure there is no way to render Word and PDF from
one source of truth, no way to check that they say the same thing, no way to
apply a change to "section 4" and no way to diff two versions.

So the structure is deliberately thin and the prose stays prose. A document is
headings, paragraphs, tables, lists and callouts; a paragraph is a paragraph,
not a tree of spans. The model writes in a constrained Markdown it is already
fluent in, and `parse()` reads that into this model. Nothing about the writing
is constrained except where the headings go.

Citations
---------
A claim may carry the locators it rests on, written inline as `[[locator]]`.
They are lifted out of the text into `Block.sources` at parse time, so a
rendered document can show them as references rather than as literal brackets,
and so PB-033 has something to check. A paragraph with no citation is not an
error — an author's recommendation is not supposed to have one — but the
grounding pass will want to know where a *figure* came from.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field

PARAGRAPH = "paragraph"
TABLE = "table"
BULLETS = "bullets"
NUMBERS = "numbers"
CALLOUT = "callout"

BLOCK_KINDS = (PARAGRAPH, TABLE, BULLETS, NUMBERS, CALLOUT)

_CITATION = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class Block:
    kind: str
    text: str = ""
    #: For TABLE: {"columns": [...], "rows": [[...], ...]}
    #: For BULLETS/NUMBERS: {"items": [...]}
    data: dict = field(default_factory=dict)
    #: Locators supporting this block, lifted from inline [[...]] markers.
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        # Deep-copied, both ways. `data` holds a table's rows — a list of
        # lists — and a shallow dict() leaves those rows shared, so a document
        # "copied" through as_dict/from_dict was still the same table and
        # grounding one of them silently rewrote the other.
        return {"kind": self.kind, "text": self.text,
                "data": copy.deepcopy(self.data),
                "sources": list(self.sources)}

    @classmethod
    def from_dict(cls, d: dict) -> Block:
        return cls(kind=d.get("kind", PARAGRAPH), text=d.get("text", ""),
                   data=copy.deepcopy(d.get("data") or {}),
                   sources=list(d.get("sources") or []))


@dataclass
class Section:
    heading: str
    level: int = 1
    blocks: list[Block] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text)

    def as_dict(self) -> dict:
        return {"heading": self.heading, "level": self.level,
                "blocks": [b.as_dict() for b in self.blocks]}

    @classmethod
    def from_dict(cls, d: dict) -> Section:
        return cls(heading=d.get("heading", ""), level=int(d.get("level", 1)),
                   blocks=[Block.from_dict(b) for b in d.get("blocks") or []])


@dataclass
class Document:
    title: str = ""
    subtitle: str = ""
    sections: list[Section] = field(default_factory=list)
    #: Reporting period, currency, scope — what a committee reader needs in the
    #: header of every page rather than buried in paragraph three.
    meta: dict = field(default_factory=dict)

    def section(self, needle: str) -> Section | None:
        """Find a section by heading, tolerantly.

        "the executive summary" has to resolve to "1. Executive summary",
        because that is how people refer to it and a scoped edit that cannot
        find its target silently edits nothing.
        """
        want = _normalise(needle)
        if not want:
            return None
        for s in self.sections:
            if _normalise(s.heading) == want:
                return s
        for s in self.sections:
            if want in _normalise(s.heading) or _normalise(s.heading) in want:
                return s
        return None

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for s in self.sections:
            for b in s.blocks:
                for loc in b.sources:
                    if loc not in seen:
                        seen.append(loc)
        return seen

    def plain_text(self) -> str:
        parts = [self.title, self.subtitle]
        for s in self.sections:
            parts.append(s.heading)
            for b in s.blocks:
                if b.kind == TABLE:
                    parts.append(" ".join(b.data.get("columns", [])))
                    parts.extend(" ".join(str(c) for c in row)
                                 for row in b.data.get("rows", []))
                elif b.kind in (BULLETS, NUMBERS):
                    parts.extend(b.data.get("items", []))
                else:
                    parts.append(b.text)
        return "\n".join(p for p in parts if p)

    def as_dict(self) -> dict:
        return {"title": self.title, "subtitle": self.subtitle,
                "meta": dict(self.meta),
                "sections": [s.as_dict() for s in self.sections]}

    @classmethod
    def from_dict(cls, d: dict) -> Document:
        return cls(title=d.get("title", ""), subtitle=d.get("subtitle", ""),
                   meta=dict(d.get("meta") or {}),
                   sections=[Section.from_dict(s) for s in d.get("sections") or []])

    def content_hash(self) -> str:
        """A stable hash of the document's meaning.

        Sorted keys and no timestamps, so two renders of the same content hash
        the same and a version that claims to differ actually does.
        """
        payload = json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalise(text: str) -> str:
    """Lowercase, without numbering or punctuation, for tolerant matching."""
    text = re.sub(r"^\s*\d+(\.\d+)*[.)]?\s*", "", (text or "").strip())
    text = re.sub(r"[^a-z0-9 ]+", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _extract_sources(text: str) -> tuple[str, list[str]]:
    found = [m.strip() for m in _CITATION.findall(text)]
    return _CITATION.sub("", text).replace("  ", " ").strip(), found


def _table_from(lines: list[str]) -> Block:
    """A GitHub-style pipe table into columns and rows."""
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue  # the alignment rule
        rows.append(cells)
    if not rows:
        return Block(PARAGRAPH, "")
    header, *body = rows
    joined = " ".join(" ".join(r) for r in rows)
    _, sources = _extract_sources(joined)
    clean_header = [_extract_sources(c)[0] for c in header]
    clean_body = [[_extract_sources(c)[0] for c in r] for r in body]
    return Block(TABLE, "", {"columns": clean_header, "rows": clean_body},
                 sources)


def parse(markdown: str, *, title: str = "") -> Document:
    """Read the constrained Markdown the author writes into a Document.

    Deliberately forgiving. A model that writes a slightly unusual list marker
    should produce a slightly imperfect document, not an exception that loses
    twenty pages of work.
    """
    doc = Document(title=title)
    current = Section(heading="", level=1)
    buffer: list[str] = []
    table: list[str] = []
    listing: list[str] = []
    list_kind = ""

    def flush() -> None:
        nonlocal buffer, table, listing, list_kind
        if table:
            current.blocks.append(_table_from(table))
            table = []
        if listing:
            items, sources = [], []
            for item in listing:
                clean, found = _extract_sources(item)
                items.append(clean)
                sources.extend(found)
            current.blocks.append(
                Block(list_kind, "", {"items": items}, sources))
            listing, list_kind = [], ""
        if buffer:
            text, sources = _extract_sources(" ".join(buffer).strip())
            if text:
                current.blocks.append(Block(PARAGRAPH, text, {}, sources))
            buffer = []

    def close_section() -> None:
        flush()
        if current.heading or current.blocks:
            doc.sections.append(current)

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level, text = len(heading.group(1)), heading.group(2).strip()
            # The leading H1 is the document's title, not its first section —
            # including when the caller already supplied that title. Without
            # the second clause a round-trip through Markdown (which writes
            # "# {title}") comes back with a phantom empty section named after
            # the document, which then reads as a section the model added.
            at_the_top = not doc.sections and not current.blocks
            if level == 1 and at_the_top and (
                    not doc.title or _normalise(text) == _normalise(doc.title)):
                doc.title = doc.title or text
                current = Section(heading="", level=1)
                continue
            close_section()
            current = Section(heading=text, level=max(1, level - 1) if doc.title else level)
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            if buffer:
                text, sources = _extract_sources(" ".join(buffer).strip())
                if text:
                    current.blocks.append(Block(PARAGRAPH, text, {}, sources))
                buffer = []
            table.append(stripped)
            continue
        if table:
            current.blocks.append(_table_from(table))
            table = []

        bullet = re.match(r"^[-*•]\s+(.*)$", stripped)
        number = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet or number:
            kind = BULLETS if bullet else NUMBERS
            if list_kind and kind != list_kind:
                flush()
            list_kind = kind
            listing.append((bullet or number).group(1).strip())
            continue
        if listing:
            items, sources = [], []
            for item in listing:
                clean, found = _extract_sources(item)
                items.append(clean)
                sources.extend(found)
            current.blocks.append(Block(list_kind, "", {"items": items}, sources))
            listing, list_kind = [], ""

        if not stripped:
            flush()
            continue
        buffer.append(stripped)

    close_section()
    return doc
