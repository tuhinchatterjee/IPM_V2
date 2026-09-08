"""
A Document as a PDF. Playbook §11.

The requirement that shapes this writer: the DOCX and the PDF of one revision
must contain the same material facts. They do, because both are rendered from
the same `Document` — there is no second content model and no separate
conversion step that could silently drop a table.

reportlab's Platypus handles the parts that are easy to get wrong by hand: a
table that runs past the bottom of a page splits and repeats its header, and
paragraphs flow rather than overlapping the footer. Page numbers are drawn per
page rather than typed.
"""

from __future__ import annotations

import io

from backend.playbook import document as D


def _styles():
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    from backend.reporting.writers import INK, MUTED, NAVY

    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("PbTitle", parent=base["Title"], fontSize=20,
                                leading=24, textColor=NAVY, alignment=TA_LEFT,
                                spaceAfter=6),
        "subtitle": ParagraphStyle("PbSubtitle", parent=base["Normal"],
                                   fontSize=10.5, leading=14, textColor=MUTED,
                                   spaceAfter=10),
        "meta": ParagraphStyle("PbMeta", parent=base["Normal"], fontSize=8.5,
                               leading=12, textColor=MUTED, spaceAfter=14),
        "h1": ParagraphStyle("PbH1", parent=base["Heading1"], fontSize=14,
                             leading=18, textColor=NAVY, spaceBefore=14,
                             spaceAfter=6),
        "h2": ParagraphStyle("PbH2", parent=base["Heading2"], fontSize=11.5,
                             leading=15, textColor=NAVY, spaceBefore=10,
                             spaceAfter=4),
        "body": ParagraphStyle("PbBody", parent=base["Normal"], fontSize=9.5,
                               leading=14, textColor=INK, spaceAfter=6),
        "bullet": ParagraphStyle("PbBullet", parent=base["Normal"], fontSize=9.5,
                                 leading=14, textColor=INK, leftIndent=14,
                                 bulletIndent=4, spaceAfter=3),
        "cell": ParagraphStyle("PbCell", parent=base["Normal"], fontSize=8.5,
                               leading=11, textColor=INK),
        "cellhead": ParagraphStyle("PbCellHead", parent=base["Normal"],
                                   fontSize=8.5, leading=11, textColor=NAVY),
    }


def _escape(text: str) -> str:
    """reportlab reads a limited HTML in paragraphs, so raw text is escaped.

    A source document containing `<script>` or a stray `&` must render as those
    characters, not as markup the renderer tries to interpret.
    """
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _page_furniture(title: str):
    from reportlab.lib.units import mm

    from backend.reporting.writers import MUTED

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        if title:
            canvas.drawRightString(doc.pagesize[0] - 18 * mm,
                                   doc.pagesize[1] - 12 * mm, title[:110])
        canvas.drawCentredString(doc.pagesize[0] / 2, 12 * mm,
                                 f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    return draw


def write(doc: D.Document) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    from backend.reporting.writers import BORDER, NAVY, ROW_ALT

    st = _styles()
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=doc.title or "CreditProbe report", author="CreditProbe",
    )

    flow = [Paragraph(_escape(doc.title or "Report"), st["title"])]
    if doc.subtitle:
        flow.append(Paragraph(_escape(doc.subtitle), st["subtitle"]))
    if doc.meta:
        line = "  ·  ".join(f"{k.replace('_', ' ').title()}: {v}"
                            for k, v in doc.meta.items() if v)
        if line:
            flow.append(Paragraph(_escape(line), st["meta"]))

    for section in doc.sections:
        if section.heading:
            flow.append(Paragraph(_escape(section.heading),
                                  st["h1"] if section.level <= 1 else st["h2"]))
        for block in section.blocks:
            if block.kind == D.TABLE:
                columns = block.data.get("columns") or []
                rows = block.data.get("rows") or []
                if not columns:
                    continue
                data = [[Paragraph(f"<b>{_escape(c)}</b>", st["cellhead"])
                         for c in columns]]
                for row in rows:
                    data.append([Paragraph(_escape(v), st["cell"])
                                 for v in list(row)[: len(columns)]])
                table = Table(data, repeatRows=1, hAlign="LEFT")
                table.setStyle(TableStyle([
                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                     [colors.white, ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                flow.append(table)
                flow.append(Spacer(1, 8))
            elif block.kind in (D.BULLETS, D.NUMBERS):
                for i, item in enumerate(block.data.get("items", []), start=1):
                    marker = f"{i}." if block.kind == D.NUMBERS else "•"
                    flow.append(Paragraph(_escape(item), st["bullet"],
                                          bulletText=marker))
                flow.append(Spacer(1, 4))
            elif block.kind == D.CALLOUT and block.text:
                flow.append(Paragraph(f"<i>{_escape(block.text)}</i>", st["body"]))
            elif block.text:
                flow.append(Paragraph(_escape(block.text), st["body"]))

    sources = doc.sources
    if sources:
        flow.append(PageBreak())
        flow.append(Paragraph("Sources", st["h1"]))
        flow.append(Paragraph(
            "Every figure in this report is traceable to one of the following.",
            st["meta"]))
        for locator in sources:
            flow.append(Paragraph(_escape(locator), st["bullet"], bulletText="•"))

    furniture = _page_furniture(doc.title or "")
    pdf.build(flow, onFirstPage=furniture, onLaterPages=furniture)
    return buf.getvalue()
