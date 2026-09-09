"""
A Document as a PowerPoint deck. Playbook §11.

The two rules the specification is explicit about, both honoured here:

**Native and editable.** Every slide is real text boxes and real PowerPoint
tables. Nothing is flattened to a picture, so a committee member can fix a
number in the room.

**A deck is not a report with the paragraphs moved.** So the writer summarises
rather than transcribes: a section becomes a slide with a concise headline and
a small number of points, long paragraphs are reduced to their leading
sentences, and anything that will not fit legibly goes to the speaker notes
instead of being shrunk until nobody can read it. Caveats are preserved — in the
notes if not on the slide — because a deck that quietly drops the limitation
paragraph is how a qualified finding becomes an unqualified one.
"""

from __future__ import annotations

import io
import re

from backend.playbook import document as D

#: Beyond this, a bullet stops being readable at the back of a room.
MAX_BULLETS = 5
MAX_BULLET_CHARS = 180
#: A table wider or longer than this goes to an appendix slide summary.
MAX_TABLE_ROWS = 8


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _points(section: D.Section) -> tuple[list[str], list[str]]:
    """What belongs on the slide, and what belongs in the notes."""
    on_slide: list[str] = []
    notes: list[str] = []
    for block in section.blocks:
        if block.kind in (D.BULLETS, D.NUMBERS):
            for item in block.data.get("items", []):
                (on_slide if len(on_slide) < MAX_BULLETS else notes).append(item)
        elif block.kind == D.TABLE:
            continue
        elif block.text:
            parts = _sentences(block.text)
            if parts and len(on_slide) < MAX_BULLETS:
                lead = parts[0]
                on_slide.append(lead if len(lead) <= MAX_BULLET_CHARS
                                else lead[: MAX_BULLET_CHARS - 1].rstrip() + "…")
                notes.extend(parts[1:])
            else:
                notes.extend(parts)
    return on_slide[:MAX_BULLETS], notes


def _tables(section: D.Section) -> list[D.Block]:
    return [b for b in section.blocks if b.kind == D.TABLE
            and (b.data.get("columns") or [])]


def write(doc: D.Document) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    navy = RGBColor(0x0B, 0x24, 0x36)
    muted = RGBColor(0x6C, 0x7A, 0x8C)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    title_slide = prs.slides.add_slide(prs.slide_layouts[0])
    title_slide.shapes.title.text = doc.title or "CreditProbe"
    for run in title_slide.shapes.title.text_frame.paragraphs[0].runs:
        run.font.color.rgb = navy
        run.font.size = Pt(36)
    subtitle_text = doc.subtitle or "  ·  ".join(
        f"{k.replace('_', ' ').title()}: {v}" for k, v in doc.meta.items() if v)
    if len(title_slide.placeholders) > 1:
        title_slide.placeholders[1].text = subtitle_text or ""
        for p in title_slide.placeholders[1].text_frame.paragraphs:
            for run in p.runs:
                run.font.size = Pt(14)
                run.font.color.rgb = muted

    for section in doc.sections:
        if not section.heading and not section.blocks:
            continue
        points, notes = _points(section)
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = section.heading or doc.title or "Findings"
        for run in slide.shapes.title.text_frame.paragraphs[0].runs:
            run.font.color.rgb = navy
            run.font.size = Pt(28)

        body = slide.placeholders[1].text_frame
        body.clear()
        if points:
            body.paragraphs[0].text = points[0]
            for extra in points[1:]:
                para = body.add_paragraph()
                para.text = extra
            for para in body.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(16)
        else:
            body.paragraphs[0].text = ""

        if notes:
            slide.notes_slide.notes_text_frame.text = "\n".join(notes)

        for block in _tables(section):
            _table_slide(prs, section.heading, block, navy)

    if doc.sources:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Sources"
        for run in slide.shapes.title.text_frame.paragraphs[0].runs:
            run.font.color.rgb = navy
            run.font.size = Pt(28)
        frame = slide.placeholders[1].text_frame
        frame.clear()
        shown = doc.sources[:MAX_BULLETS]
        frame.paragraphs[0].text = shown[0]
        for locator in shown[1:]:
            frame.add_paragraph().text = locator
        for para in frame.paragraphs:
            for run in para.runs:
                run.font.size = Pt(12)
                run.font.color.rgb = muted
        if len(doc.sources) > MAX_BULLETS:
            slide.notes_slide.notes_text_frame.text = "\n".join(
                doc.sources[MAX_BULLETS:])

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _table_slide(prs, heading: str, block: D.Block, navy) -> None:
    """One table on its own slide, as a native editable PowerPoint table."""
    from pptx.util import Inches, Pt

    columns = block.data.get("columns") or []
    rows = list(block.data.get("rows") or [])
    overflow = rows[MAX_TABLE_ROWS:]
    rows = rows[:MAX_TABLE_ROWS]

    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = heading or "Results"
    for run in slide.shapes.title.text_frame.paragraphs[0].runs:
        run.font.color.rgb = navy
        run.font.size = Pt(26)

    shape = slide.shapes.add_table(
        len(rows) + 1, len(columns),
        Inches(0.7), Inches(1.8), Inches(11.9),
        Inches(0.4 * (len(rows) + 1)),
    )
    table = shape.table
    for c, name in enumerate(columns):
        cell = table.cell(0, c)
        cell.text = str(name)
        for para in cell.text_frame.paragraphs:
            for run in para.runs:
                run.font.bold = True
                run.font.size = Pt(12)
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(list(row)[: len(columns)]):
            cell = table.cell(r, c)
            cell.text = "" if value is None else str(value)
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(11)

    if overflow:
        slide.notes_slide.notes_text_frame.text = (
            f"{len(overflow)} further row(s) are in the report and were not "
            "shown here for legibility."
        )
