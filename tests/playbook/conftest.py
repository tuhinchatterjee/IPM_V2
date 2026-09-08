"""Fixtures for the Playbook suite.

Real files, built here rather than committed as binaries: a test that reads a
document nobody can regenerate is a test whose failure nobody can diagnose.
"""

from __future__ import annotations

import io

import pytest


@pytest.fixture
def committee_report_docx() -> bytes:
    """A previous-period committee report, with the structure Playbook edits."""
    from docx import Document

    doc = Document()
    doc.core_properties.title = "IFRS 9 Committee Report — Q1 2026"
    doc.core_properties.author = "Credit Risk"

    doc.sections[0].header.paragraphs[0].text = "IFRS 9 Committee Report — Q1 2026"

    doc.add_heading("1. Executive summary", level=1)
    doc.add_paragraph(
        "Weighted ECL for the quarter was SAR 20.90 million against exposure of "
        "SAR 1,000 million, a coverage ratio of 2.09 per cent."
    )
    doc.add_heading("2. Scenario results", level=1)
    doc.add_heading("2.1 Weighted outcome", level=2)
    doc.add_paragraph("Scenario weights were unchanged at 60/15/25.")
    table = doc.add_table(rows=4, cols=2)
    rows = [("Scenario", "ECL, SAR million"), ("Base", "18.00"),
            ("Upturn", "14.00"), ("Downturn", "32.00")]
    for r, (a, b) in enumerate(rows):
        table.rows[r].cells[0].text = a
        table.rows[r].cells[1].text = b
    doc.add_heading("3. Limitations", level=1)
    doc.add_paragraph("Post-model adjustments are not covered in this report.")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def results_workbook_xlsx() -> bytes:
    """A current-period results workbook, including the two awkward cases:
    a hidden sheet, and a formula with no cached value."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "ECL"
    for row in [
        ["Scenario", "ECL, SAR million", "Weight"],
        ["Base", 19.20, 0.60],
        ["Upturn", 15.00, 0.15],
        ["Downturn", 36.00, 0.25],
    ]:
        ws.append(row)
    # Written as a formula and never calculated, so no cached value exists.
    ws["B6"] = "=SUMPRODUCT(B2:B4,C2:C4)"
    ws["A6"] = "Weighted"

    exposure = wb.create_sheet("Exposure")
    exposure.append(["Period", "Exposure, SAR million"])
    exposure.append(["Q1 2026", 1000])
    exposure.append(["Q2 2026", 1050])

    working = wb.create_sheet("Working")
    working.append(["scratch", 1])
    working.sheet_state = "hidden"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def methodology_docx() -> bytes:
    """A methodology document naming topics a report should cover."""
    from docx import Document

    doc = Document()
    doc.add_heading("IFRS 9 ECL Methodology", level=1)
    for topic in [
        "Scenario design and weighting",
        "Staging criteria and SICR",
        "Post-model adjustments",
        "Model monitoring and validation",
    ]:
        doc.add_heading(topic, level=2)
        doc.add_paragraph(f"Requirements for {topic.lower()}.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def simple_deck_pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Q2 2026 ECL"
    slide.placeholders[1].text = "Weighted ECL rose to SAR 22.77 million."
    slide.notes_slide.notes_text_frame.text = "Mention the coverage ratio."

    blank = prs.slides.add_slide(prs.slide_layouts[6])
    table = blank.shapes.add_table(2, 2, Inches(1), Inches(1),
                                   Inches(4), Inches(1)).table
    table.cell(0, 0).text = "Scenario"
    table.cell(0, 1).text = "ECL"
    table.cell(1, 0).text = "Base"
    table.cell(1, 1).text = "19.20"

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


@pytest.fixture
def text_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 760, "Behavioural Scorecard Validation — Q2 2026")
    c.drawString(72, 740, "Gini was 0.58 against a limit of 0.45.")
    c.showPage()
    c.drawString(72, 760, "Population stability index was 0.08.")
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def image_only_pdf() -> bytes:
    """A PDF with no text layer at all — a scan, in effect."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(100, 100, 300, 300, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def db():
    """A session against the configured platform database, or a skip.

    Follows the repository's own convention: `database_available()` from the
    root conftest decides, and a missing database skips rather than failing —
    except that Playbook's persistence tests are the point of the suite, so a
    skip here is reported as a skip and never counted as a pass.
    """
    from tests.conftest import database_available

    if not database_available():
        pytest.skip("Playbook persistence needs the platform database")
    from backend.db.engine import get_session

    with get_session() as session:
        yield session


@pytest.fixture
def scope():
    from backend.playbook.repository import Scope

    return Scope(tenant="test-tenant", user_id=None)


@pytest.fixture
def workspace(db, scope):
    from backend.playbook import repository as repo

    ws = repo.create_workspace(db, scope, title="IFRS 9 Committee Report",
                               document_family="ifrs9_committee_report")
    db.flush()
    return ws


@pytest.fixture
def scripted_author(monkeypatch):
    """Stand in for the provider, so the pipeline around it can be tested.

    Returns a setter: the test supplies the Markdown the author "wrote" and,
    optionally, files it "produced". Nothing here reaches a network, and results
    obtained this way are never reported as live verification.
    """
    from backend.playbook import provider

    state = {"text": "", "files": [], "model": "scripted-author"}

    def fake_author(*, system, messages, formats, purpose="playbook_authoring",
                    container_id="", on_milestone=None, is_cancelled=None):
        if is_cancelled and is_cancelled():
            raise provider.Cancelled("stopped")
        if on_milestone:
            on_milestone("drafting", "scripted")
        result = provider.AuthoringResult(
            text=state["text"],
            files=list(state["files"]),
            model_requested=state["model"],
            model_served=state["model"],
            request_ids=["req_scripted"],
            turns=1,
        )
        state["last_system"] = system
        state["last_user"] = messages[0]["content"]
        return result

    monkeypatch.setattr(provider, "author", fake_author)
    monkeypatch.setattr("backend.playbook.service.provider.author", fake_author)

    def configure(text: str, files=None, model: str = "scripted-author"):
        state["text"] = text
        state["files"] = files or []
        state["model"] = model
        return state

    configure.state = state
    return configure
