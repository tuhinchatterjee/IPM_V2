"""
A Document as a Word file. Playbook §11.

"Do not deliver raw Markdown inside a DOCX container" is the requirement, and
it is a real risk: it is entirely possible to write a .docx whose every
paragraph begins with a literal `##`. So this writer uses Word's own machinery —
built-in heading styles so the navigation pane and any later table of contents
work, a real table style with a repeating header row, page numbering in the
footer as a field rather than as typed text, and margins a committee paper can
be printed at.

Sources are collected into a references appendix rather than left inline,
because `[[xlsx://ECL!B12]]` in the middle of a sentence is a debugging artefact,
not a citation somebody can read.
"""

from __future__ import annotations

import io

from backend.playbook import document as D


def _add_field(paragraph, instruction: str) -> None:
    """Insert a Word field (used for PAGE / NUMPAGES).

    Typed page numbers are wrong the moment the document reflows, so the footer
    carries the field Word updates itself.
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _repeat_header(row) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def write(doc: D.Document) -> bytes:
    from docx import Document as Docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    out = Docx()
    out.core_properties.title = doc.title or "CreditProbe report"
    out.core_properties.author = "CreditProbe"

    for section in out.sections:
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)
        section.top_margin = Inches(0.9)
        section.bottom_margin = Inches(0.9)

        header = section.header.paragraphs[0]
        header.text = doc.title or ""
        header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for run in header.runs:
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x6C, 0x7A, 0x8C)

        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = footer.add_run("Page ")
        run.font.size = Pt(8)
        _add_field(footer, "PAGE")
        run = footer.add_run(" of ")
        run.font.size = Pt(8)
        _add_field(footer, "NUMPAGES")
        for run in footer.runs:
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x6C, 0x7A, 0x8C)

    title = out.add_heading(doc.title or "Report", level=0)
    for run in title.runs:
        run.font.color.rgb = RGBColor(0x0B, 0x24, 0x36)
    if doc.subtitle:
        p = out.add_paragraph(doc.subtitle)
        for run in p.runs:
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0x6C, 0x7A, 0x8C)

    if doc.meta:
        line = "  ·  ".join(f"{k.replace('_', ' ').title()}: {v}"
                            for k, v in doc.meta.items() if v)
        if line:
            p = out.add_paragraph(line)
            for run in p.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x6C, 0x7A, 0x8C)

    for section in doc.sections:
        if section.heading:
            out.add_heading(section.heading, level=min(max(section.level, 1), 4))
        for block in section.blocks:
            if block.kind == D.TABLE:
                _write_table(out, block)
            elif block.kind == D.BULLETS:
                for item in block.data.get("items", []):
                    out.add_paragraph(item, style="List Bullet")
            elif block.kind == D.NUMBERS:
                for item in block.data.get("items", []):
                    out.add_paragraph(item, style="List Number")
            elif block.kind == D.CALLOUT:
                p = out.add_paragraph()
                run = p.add_run(block.text)
                run.italic = True
                run.font.color.rgb = RGBColor(0x0B, 0x24, 0x36)
            elif block.text:
                out.add_paragraph(block.text)

    sources = doc.sources
    if sources:
        out.add_page_break()
        out.add_heading("Sources", level=1)
        p = out.add_paragraph(
            "Every figure in this report is traceable to one of the following."
        )
        for run in p.runs:
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0x6C, 0x7A, 0x8C)
        for locator in sources:
            out.add_paragraph(locator, style="List Bullet")

    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()


def _write_table(out, block: D.Block) -> None:
    from docx.shared import Pt, RGBColor

    columns = block.data.get("columns") or []
    rows = block.data.get("rows") or []
    if not columns:
        return
    table = out.add_table(rows=1, cols=len(columns))
    table.style = "Light Grid Accent 1"
    header = table.rows[0]
    for i, name in enumerate(columns):
        cell = header.cells[i]
        cell.text = str(name)
        for p in cell.paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x0B, 0x24, 0x36)
    _repeat_header(header)

    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row[: len(columns)]):
            cells[i].text = "" if value is None else str(value)
            for p in cells[i].paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)
    out.add_paragraph()
