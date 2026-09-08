"""Charts have to be IN the document, not merely requested.

`charts.render()` swallows every exception and returns None, so a renderer
that raised would produce a chart-less report and break no test — the
existing report tests check sections, tables and figures and never open the
archive. A renderer can therefore rot silently, and the first person to
notice is whoever opens the report in front of a committee.

These tests open the generated `.docx` as the zip it is and assert the image
parts are actually there, for every scope. They also assert the sections the
reference reports establish: a score composition a committee can argue with,
an evidence trail with the decay state, actions with an owner and a closing
test, and the limitations of an uncalibrated model.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from backend.early_warning import reports as rpt
from backend.early_warning import v2_service as svc


@pytest.fixture(scope="module", autouse=True)
def _require_domain():
    try:
        svc.latest_period()
    except Exception:  # noqa: BLE001
        pytest.skip("Early Warning V2 domain is not built")


@pytest.fixture(scope="module")
def worst_ids():
    return [r["customer_id"] for r in svc.top_high_risk(limit=3)]


def _media(data: bytes) -> list[str]:
    archive = zipfile.ZipFile(io.BytesIO(data))
    return [n for n in archive.namelist()
            if n.startswith("word/media/") and n.endswith((".png", ".jpg"))]


def test_the_borrower_report_embeds_its_chart(worst_ids):
    assert _media(rpt.generate_docx("borrower", worst_ids[0]))


def test_the_portfolio_report_embeds_its_charts():
    assert len(_media(rpt.generate_docx("portfolio"))) >= 2


def test_the_segment_report_embeds_its_chart():
    segment = svc.segment_summary()[0]["segment"]
    assert _media(rpt.generate_docx("segment", segment))


def test_the_all_segment_report_gives_every_segment_its_own_chart():
    """A flat table of segments answers "which is worst" and nothing else."""
    data = rpt.generate_docx("all_segments")
    segments = svc.segment_summary()
    # One overview chart plus one per segment.
    assert len(_media(data)) >= len(segments)


def test_the_multi_borrower_report_embeds_charts(worst_ids):
    """It had none at all: every section omitted the chart argument."""
    assert _media(rpt.generate_docx("multi_borrower", customer_ids=worst_ids))


# ------------------------------------------------------- reference sections


def test_the_borrower_report_shows_how_the_score_was_reached(worst_ids):
    """A final score alone cannot be challenged: a committee needs the anchor
    and the notches separately to know which half to argue with."""
    report = rpt.borrower_report(worst_ids[0])
    composition = next(s for s in report["sections"] if s["key"] == "composition")
    steps = [row[0] for row in composition["table"]["rows"]]
    assert "Anchor from the matrix" in steps
    assert "Net notches" in steps


def test_the_borrower_report_carries_the_decay_state_in_its_lineage(worst_ids):
    for cid in worst_ids:
        report = rpt.borrower_report(cid)
        evidence = next(s for s in report["sections"] if s["key"] == "evidence")
        if not evidence["table"]:
            continue
        assert "Decay applied" in evidence["table"]["columns"]
        assert "Signal class" in evidence["table"]["columns"]
        return
    pytest.skip("no signal fired for the sampled obligors")


def test_every_scope_states_its_limitations(worst_ids):
    reports = [rpt.borrower_report(worst_ids[0]), rpt.portfolio_report(),
               rpt.all_segments_report(),
               rpt.multi_borrower_report(worst_ids)]
    for report in reports:
        limitations = next(
            (s for s in report["sections"] if s["key"] == "limitations"), None)
        assert limitations is not None, report["type"]
        text = " ".join(f["text"] for f in limitations["findings"])
        assert "not calibrated" in text
        assert "synthetic" in text


def test_recommended_actions_reach_the_document_as_a_section(worst_ids):
    """The writer renders `sections` and ignores a report's `actions` key
    entirely, so an action list set there is silently dropped."""
    report = rpt.borrower_report(worst_ids[0])
    actions = next((s for s in report["sections"] if s["key"] == "actions"), None)
    if actions is None:
        pytest.skip("no driver scoring for this obligor")
    assert "Owner" in actions["table"]["columns"]
    assert "Evidence to close" in actions["table"]["columns"]
    for row in actions["table"]["rows"]:
        assert row[3].strip(), row  # an owner
        assert row[5].strip(), row  # something that closes it


def test_the_portfolio_report_reads_grade_against_early_warning():
    report = rpt.portfolio_report()
    grades = next(s for s in report["sections"] if s["key"] == "grades")
    assert "review cycle" in grades["narrative"]
    assert "not a reason to change a grade" in grades["narrative"].replace(
        "it is not a reason to change a grade", "not a reason to change a grade")


def test_the_portfolio_report_carries_the_diagnosis_and_its_limits():
    report = rpt.portfolio_report()
    diagnosis = next(s for s in report["sections"] if s["key"] == "diagnosis")
    text = " ".join(f["text"] for f in diagnosis["findings"])
    assert "not predictive" in text
    assert "approval or decline" in text


def test_an_unknown_scope_is_still_refused():
    with pytest.raises(ValueError):
        rpt.generate_docx("not_a_scope")
