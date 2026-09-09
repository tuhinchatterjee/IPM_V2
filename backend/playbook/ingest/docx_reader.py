"""
Reading a Word document. Playbook §7.

What matters here is not the text — python-docx gives that away — but the
STRUCTURE, because everything Playbook is asked to do afterwards is structural:
"sharpen the executive summary", "make Section 4 more concise", "what does the
previous report already cover". A flat list of paragraphs cannot answer any of
those without guessing which paragraphs belonged to which section.

So the reader keeps a heading stack and stamps every chunk with the trail that
led to it, and it keeps document order across paragraphs and tables — which
python-docx does not give you directly, because `doc.paragraphs` and
`doc.tables` are two separate sequences and a table's position between two
paragraphs is only recoverable from the underlying body XML.

Headers, footers and core properties are read too. A committee report's period
is very often in the header rather than the body, and a reporting period that
has to be guessed is a reporting period that will eventually be guessed wrong.
"""

from __future__ import annotations

import io

from backend.playbook.ingest.types import (
    HEADING,
    NOTE,
    PARAGRAPH,
    TABLE,
    Chunk,
    Manifest,
    ReadResult,
    UnreadableSource,
)


def _heading_level(style_name: str) -> int:
    """The outline depth of a paragraph style, or 0 if it is not a heading."""
    name = (style_name or "").strip().lower()
    if name == "title":
        return 1
    if name.startswith("heading"):
        tail = name.replace("heading", "").strip()
        if tail.isdigit():
            return int(tail)
        return 1
    return 0


def _table_rows(table) -> dict:
    """A table as columns and typed-as-read rows.

    Values stay strings here. Turning "1,050" into a number is a decision with a
    unit attached, and it belongs to `backend.playbook.calc`, which will refuse
    the ones that are not really numbers rather than coercing them to zero.
    """
    grid = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if not grid:
        return {"columns": [], "rows": []}
    header, *body = grid
    return {"columns": header, "rows": body}


def read(content: bytes, *, filename: str = "") -> ReadResult:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise UnreadableSource("python-docx is not installed") from exc

    manifest = Manifest(format="docx")
    try:
        doc = Document(io.BytesIO(content))
    except Exception as exc:
        raise UnreadableSource(
            f"{filename or 'This file'} could not be opened as a Word document."
        ) from exc

    chunks: list[Chunk] = []
    stack: list[str] = []
    para_n = table_n = 0

    # Walk the body in document order. Paragraph and table indices are counted
    # separately so a locator points at "the 17th paragraph", which is what the
    # editor and the citation both mean by it.
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            level = _heading_level(para.style.name if para.style else "")
            if level:
                del stack[level - 1:]
                stack.append(text)
                chunks.append(Chunk(HEADING, f"docx://para/{para_n}", text,
                                    list(stack[:-1]), ordinal=len(chunks)))
            else:
                chunks.append(Chunk(PARAGRAPH, f"docx://para/{para_n}", text,
                                    list(stack), ordinal=len(chunks)))
            para_n += 1
        elif tag == "tbl":
            table = Table(child, doc)
            data = _table_rows(table)
            summary = " | ".join(data["columns"])
            chunks.append(Chunk(TABLE, f"docx://table/{table_n}", summary,
                                list(stack), data, ordinal=len(chunks)))
            table_n += 1

    if not chunks:
        raise UnreadableSource(
            f"{filename or 'This document'} contains no readable text."
        )
    manifest.read.append(f"{para_n} paragraphs, {table_n} tables")

    # Headers and footers, where the period usually hides.
    seen: set[str] = set()
    for i, section in enumerate(doc.sections):
        for label, part in (("header", section.header), ("footer", section.footer)):
            try:
                text = "\n".join(p.text.strip() for p in part.paragraphs).strip()
            except Exception:  # pragma: no cover - malformed section part
                manifest.skip(f"section {i} {label}", "could not be read")
                continue
            if text and text not in seen:
                seen.add(text)
                chunks.append(Chunk(NOTE, f"docx://{label}/{i}", text,
                                    [], ordinal=len(chunks)))
    if seen:
        manifest.read.append(f"{len(seen)} distinct header/footer blocks")

    try:
        props = doc.core_properties
        meta = {
            "title": props.title or "",
            "author": props.author or "",
            "created": props.created.isoformat() if props.created else "",
            "modified": props.modified.isoformat() if props.modified else "",
        }
        if any(meta.values()):
            chunks.append(Chunk(NOTE, "docx://properties", "", [], meta,
                                ordinal=len(chunks)))
            manifest.read.append("core properties")
    except Exception:  # pragma: no cover - optional part
        manifest.skip("core properties", "could not be read")

    # An inline image is not evidence unless somebody looked at it. Saying so
    # is the difference between an honest gap and an invented reading.
    images = [r for r in doc.part.rels.values() if "image" in r.reltype]
    if images:
        manifest.warnings.append(
            f"{len(images)} embedded image(s) were not interpreted; any figure "
            "they carry is not part of what was read."
        )

    return ReadResult(chunks, manifest)
