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
from backend.playbook.render import inline
from backend.playbook.render import shell as shell_of


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
        # The contents page's own heading. Identical to h1 to look at, and
        # deliberately a different style name: `afterFlowable` notifies on
        # PbH1/PbH2, so sharing one would list "Contents" inside the contents.
        "front": ParagraphStyle("PbFront", parent=base["Heading1"],
                                fontSize=14, leading=18, textColor=NAVY,
                                spaceBefore=14, spaceAfter=6),
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
    """Raw text, with nothing in it readable as markup.

    reportlab reads a limited HTML in paragraphs, so a source document
    containing `<script>` or a stray `&` must render as those characters and
    not as markup the renderer tries to interpret. Used where no formatting is
    wanted at all — headings, cells, locators.
    """
    return inline.escape(inline.plain(str(text)))


def _rich(text: str) -> str:
    """The same, with `**bold**`, `*italic*` and `` `code` `` applied.

    Escaping happens inside `inline.markup`, per run and before its own tags
    are added, so a literal `<` cannot become a tag and a tag it added cannot
    be escaped away. Every paragraph used to go through `_escape` alone, which
    is why the asterisks reached the reader.
    """
    return inline.markup(str(text))


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


def _template():
    """A document that tells the contents where each heading landed.

    reportlab resolves a table of contents over two passes: the first records
    which page every entry finished on, the second draws the list with those
    numbers. `afterFlowable` is the hook that does the recording, and without
    a subclass there is nowhere to put it.
    """
    from reportlab.platypus import SimpleDocTemplate

    class _Doc(SimpleDocTemplate):
        def afterFlowable(self, flowable):  # noqa: N802 — reportlab's name
            style = getattr(getattr(flowable, "style", None), "name", "")
            if style not in ("PbH1", "PbH2"):
                return
            text = flowable.getPlainText()
            if not text:
                return
            level = 0 if style == "PbH1" else 1
            self.notify("TOCEntry", (level, text, self.page))

    return _Doc


def write(doc: D.Document) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.tableofcontents import TableOfContents

    from backend.reporting.writers import BORDER, INK, MUTED, NAVY, ROW_ALT

    contents = TableOfContents()
    contents.levelStyles = [
        ParagraphStyle("PbToc0", fontSize=10, leading=16, textColor=INK,
                       firstLineIndent=0, leftIndent=0),
        ParagraphStyle("PbToc1", fontSize=9, leading=14, textColor=MUTED,
                       firstLineIndent=0, leftIndent=14),
    ]

    st = _styles()
    front = shell_of.shell_of(doc)
    buf = io.BytesIO()
    pdf = _template()(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=front.title, author="CreditProbe",
    )

    # A cover, not a first page that happens to start with a big line. The
    # title sits about a third of the way down, which is where a reader's eye
    # goes and where every committee paper this replaces puts it; without the
    # spacer the block sat under the header with two-thirds of the page blank
    # below it, which reads as a document that failed to render.
    flow = [Spacer(1, 70 * mm) if front.has_contents else Spacer(1, 0),
            Paragraph(_escape(front.title), st["title"])]
    if front.subtitle:
        flow.append(Paragraph(_escape(front.subtitle), st["subtitle"]))
    if front.facts:
        # A record, not a middot-joined caption. Same shape as the Word cover,
        # from the same `Shell`, so the two cannot describe one document
        # differently.
        facts = Table(
            [[Paragraph(f"<b>{_escape(k)}</b>", st["cell"]),
              Paragraph(_escape(v), st["cell"])] for k, v in front.facts],
            colWidths=[38 * mm, None], hAlign="LEFT")
        facts.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, ROW_ALT]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(facts)
        flow.append(Spacer(1, 10))

    if front.has_contents:
        # Built, not a field: a PDF has no reader to update one later. The
        # page numbers come from reportlab's own index of where each heading
        # actually landed — see `_Contents` below.
        flow.append(PageBreak())
        flow.append(Paragraph("Contents", st["front"]))
        flow.append(contents)
        flow.append(PageBreak())

    for section in doc.sections:
        if section.heading:
            # Plain: a heading is an entry in the contents as well as a line
            # in the body, and the two have to read the same.
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
                    data.append([Paragraph(_rich("" if v is None else v),
                                           st["cell"])
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
                    flow.append(Paragraph(_rich(item), st["bullet"],
                                          bulletText=marker))
                flow.append(Spacer(1, 4))
            elif block.kind == D.CALLOUT and block.text:
                flow.append(Paragraph(f"<i>{_rich(block.text)}</i>",
                                      st["body"]))
            elif block.text:
                flow.append(Paragraph(_rich(block.text), st["body"]))

    sources = doc.sources
    if sources:
        flow.append(PageBreak())
        flow.append(Paragraph("Sources", st["h1"]))
        flow.append(Paragraph(
            "Every figure in this report is traceable to one of the following.",
            st["meta"]))
        for locator in sources:
            flow.append(Paragraph(_escape(locator), st["bullet"], bulletText="•"))

    furniture = _page_furniture(front.title)
    if front.has_contents:
        # Two passes, so the page numbers in the contents are the pages the
        # headings actually landed on rather than a guess made before layout.
        #
        # And nothing drawn on the cover: a running header repeating the title
        # six centimetres above the title, and a page number on a page that is
        # not part of the reading, are what a cover page is for NOT having.
        pdf.multiBuild(flow, onFirstPage=lambda *a: None,
                       onLaterPages=furniture)
    else:
        pdf.build(flow, onFirstPage=furniture, onLaterPages=furniture)
    return buf.getvalue()
