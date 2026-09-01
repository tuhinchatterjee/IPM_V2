"""
Files arrive, and something has to decide.

The drift comparison is the part that matters, and the case it exists for is
not a load that fails — it is a load that succeeds while the meaning of a
column changes underneath it. So the tests below are mostly about a file that
parses perfectly and should still be stopped.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from backend.services.drift import (
    DriftKind,
    Severity,
    compare,
)
from backend.services.inbox import (
    AUTO_PUBLISH,
    HELD,
    HOLD,
    PUBLISHED,
    UNMATCHED,
    Match,
    apply_policy,
)


def profile(frame: pd.DataFrame) -> dict:
    from backend.services.data_builder import profile_dataframe

    return profile_dataframe(frame)


def book(rows: int = 100, *, ead_scale: float = 1.0, sectors=None,
         drop: str = "", ead_as_text: bool = False,
         null_ecl: bool = False) -> pd.DataFrame:
    sectors = sectors or ["Real Estate", "Contracting", "Trade"]
    frame = pd.DataFrame({
        "account_id": [f"A{i:05d}" for i in range(rows)],
        "customer_id": [f"C{i % 40:05d}" for i in range(rows)],
        "period": ["Q1 2026"] * rows,
        "ead": [(10.0 + i % 50) * ead_scale for i in range(rows)],
        "total_ecl": [None] * rows if null_ecl else [(0.2 + i % 5) for i in range(rows)],
        "sector": [sectors[i % len(sectors)] for i in range(rows)],
        "ifrs9_stage": [1 + i % 3 for i in range(rows)],
    })
    if ead_as_text:
        # Formatted the way a source system that switched to a report export
        # formats it: thousands separators and a currency suffix, which no
        # longer parses as a number.
        frame["ead"] = frame["ead"].map(lambda v: f"{v * 1000:,.2f} USD")
    if drop:
        frame = frame.drop(columns=[drop])
    return frame


# ------------------------------------------------------------------- no drift


def test_an_identical_file_produces_no_findings():
    before = profile(book())
    report = compare(before, profile(book()), dataset="portfolio_facility")
    assert report.findings == []
    assert report.clean
    assert "Nothing changed" in report.summary()


def test_a_first_load_is_not_reported_as_verified():
    """There is nothing to compare against, and saying 'no drift' would claim a
    check that did not happen."""
    report = compare(None, profile(book()))
    assert report.first_load
    assert "nothing to compare" in report.summary()


# ------------------------------------------------------------- what it catches


def test_a_removed_field_blocks():
    report = compare(profile(book()), profile(book(drop="total_ecl")))
    finding = next(f for f in report.findings if f.kind == DriftKind.FIELD_REMOVED)
    assert finding.severity == Severity.BLOCKING
    assert finding.field == "total_ecl"
    assert finding.because


def test_an_added_field_is_noted_not_blocked():
    extra = book()
    extra["new_column"] = 1
    report = compare(profile(book()), profile(extra))
    finding = next(f for f in report.findings if f.kind == DriftKind.FIELD_ADDED)
    assert finding.severity == Severity.NOTABLE


def test_a_number_arriving_as_text_blocks():
    """The dangerous direction: every comparison silently becomes a string one,
    in which '9' is greater than '10'."""
    report = compare(profile(book()), profile(book(ead_as_text=True)))
    finding = next(f for f in report.findings if f.kind == DriftKind.TYPE_CHANGED)
    assert finding.severity == Severity.BLOCKING
    assert "'9' is greater than '10'" in finding.because


def test_a_unit_change_blocks():
    """The case the whole module exists for. Millions arriving as units: the
    load succeeds, every calculation is correct, every figure is wrong."""
    report = compare(profile(book()), profile(book(ead_scale=1_000_000)))
    finding = next(f for f in report.findings if f.kind == DriftKind.MAGNITUDE_SHIFT)
    assert finding.severity == Severity.BLOCKING
    assert "unit change" in finding.because


def test_a_book_that_merely_grows_is_not_a_unit_change():
    report = compare(profile(book()), profile(book(ead_scale=1.4)))
    assert not any(f.kind == DriftKind.MAGNITUDE_SHIFT for f in report.findings)


def test_a_column_that_stopped_being_populated_blocks():
    report = compare(profile(book()), profile(book(null_ecl=True)))
    finding = next(f for f in report.findings if f.kind == DriftKind.ALL_NULL)
    assert finding.severity == Severity.BLOCKING


def test_a_new_category_value_is_material():
    report = compare(profile(book()),
                     profile(book(sectors=["Real Estate", "Contracting", "Trade",
                                           "Crypto Mining"])))
    finding = next(f for f in report.findings if f.kind == DriftKind.NEW_VALUES)
    assert finding.severity == Severity.MATERIAL
    assert "Crypto Mining" in finding.detail


def test_a_vanished_category_value_is_noted():
    report = compare(profile(book()),
                     profile(book(sectors=["Real Estate", "Contracting"])))
    assert any(f.kind == DriftKind.MISSING_VALUES for f in report.findings)


def test_half_a_book_arriving_is_material():
    report = compare(profile(book(200)), profile(book(80)))
    finding = next(f for f in report.findings if f.kind == DriftKind.ROW_COUNT_CHANGED)
    assert finding.severity == Severity.MATERIAL
    assert "partial extract" in finding.because


def test_an_empty_file_blocks():
    report = compare(profile(book()), profile(book(0)))
    assert any(f.kind == DriftKind.NO_ROWS and f.severity == Severity.BLOCKING
               for f in report.findings)


def test_findings_are_ordered_worst_first():
    report = compare(profile(book(200)),
                     profile(book(80, drop="total_ecl", ead_scale=1_000_000)))
    severities = [f.severity for f in report.by_severity()]
    assert severities == sorted(
        severities,
        key=lambda s: [Severity.BLOCKING, Severity.MATERIAL, Severity.NOTABLE,
                       Severity.INFORMATIONAL].index(s))


def test_every_finding_says_why_it_matters():
    report = compare(profile(book(200)),
                     profile(book(80, drop="total_ecl", ead_as_text=True)))
    assert report.findings
    for finding in report.findings:
        assert finding.detail.strip()
        assert finding.because.strip(), f"{finding.kind} states no consequence"


# ------------------------------------------------------------------ the policy


def test_a_clean_file_publishes_itself():
    report = compare(profile(book()), profile(book()))
    status, decision, reason = apply_policy(
        Match("portfolio_facility", 0.95, ""), report)
    assert (status, decision) == (PUBLISHED, AUTO_PUBLISH)
    assert "unchanged" in reason


def test_anything_blocking_is_held():
    report = compare(profile(book()), profile(book(ead_scale=1_000_000)))
    status, decision, reason = apply_policy(
        Match("portfolio_facility", 0.95, ""), report)
    assert (status, decision) == (HELD, HOLD)
    assert "blocking" in reason


def test_anything_material_is_held():
    report = compare(profile(book(200)), profile(book(80)))
    status, decision, _ = apply_policy(Match("portfolio_facility", 0.95, ""), report)
    assert (status, decision) == (HELD, HOLD)


def test_a_first_load_is_held_for_a_person():
    status, decision, reason = apply_policy(
        Match("portfolio_facility", 0.95, ""), compare(None, profile(book())))
    assert (status, decision) == (HELD, HOLD)
    assert "first file" in reason


def test_an_uncertain_match_is_held_however_clean_the_file():
    report = compare(profile(book()), profile(book()))
    status, decision, reason = apply_policy(
        Match("portfolio_facility", 0.4, ""), report)
    assert (status, decision) == (HELD, HOLD)
    assert "wrong dataset" in reason


def test_a_file_nothing_matches_is_not_published():
    status, decision, reason = apply_policy(
        Match("", 0.0, ""), compare(None, profile(book())))
    assert (status, decision) == (UNMATCHED, HOLD)
    assert "no dataset" in reason


def test_every_decision_carries_a_reason():
    cases = [
        (Match("d", 0.95, ""), compare(profile(book()), profile(book()))),
        (Match("d", 0.95, ""), compare(profile(book()), profile(book(80)))),
        (Match("d", 0.3, ""), compare(profile(book()), profile(book()))),
        (Match("", 0.0, ""), compare(None, profile(book()))),
    ]
    for match, report in cases:
        _, _, reason = apply_policy(match, report)
        assert reason.strip(), "A decision with no reason is not a decision."


# ---------------------------------------------------------------- over HTTP


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def database_available() -> bool:
    from tests.conftest import database_available as available

    return available()


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("PostgreSQL not reachable")


def test_the_inbox_lists_arrivals_with_their_counts(client):
    body = client.get("/api/v1/data-builder/inbox").json()
    assert "items" in body
    assert "needs_attention" in body["counts"]
    assert body["auto_publish_confidence"] >= 0.5


def test_a_file_matching_nothing_is_recorded_not_discarded(client):
    frame = pd.DataFrame({"colour": ["red", "blue"], "shape": ["round", "flat"]})
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    response = client.post(
        "/api/v1/data-builder/inbox",
        headers={"X-IPM-Role": "DATA_STEWARD"},
        files={"file": ("mystery.csv", buffer.getvalue(), "text/csv")},
        data={"publish": "false"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == UNMATCHED
    assert body["decision"] == HOLD
    assert body["decision_reason"]
    assert body["id"], "An unmatched file still gets a row — silence is not a state."


def test_publishing_a_held_file_needs_a_reason(client):
    frame = pd.DataFrame({"colour": ["red"], "shape": ["round"]})
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    created = client.post(
        "/api/v1/data-builder/inbox",
        headers={"X-IPM-Role": "DATA_STEWARD"},
        files={"file": ("mystery2.csv", buffer.getvalue(), "text/csv")},
        data={"publish": "false"},
    ).json()

    response = client.post(
        f"/api/v1/data-builder/inbox/{created['id']}/resolve",
        headers={"X-IPM-Role": "DATA_STEWARD"},
        json={"action": "publish", "note": "", "dataset": "portfolio_facility"},
    )
    assert response.status_code == 400
    assert "reason" in response.json()["detail"]["message"]


def test_rejecting_a_held_file_records_who_and_why(client):
    frame = pd.DataFrame({"colour": ["red"], "shape": ["round"]})
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    created = client.post(
        "/api/v1/data-builder/inbox",
        headers={"X-IPM-Role": "DATA_STEWARD"},
        files={"file": ("mystery3.csv", buffer.getvalue(), "text/csv")},
        data={"publish": "false"},
    ).json()

    body = client.post(
        f"/api/v1/data-builder/inbox/{created['id']}/resolve",
        headers={"X-IPM-Role": "DATA_STEWARD"},
        json={"action": "reject", "note": "Not a credit file."},
    ).json()
    assert body["status"] == "rejected"
    assert body["resolution_note"] == "Not a credit file."
    assert body["resolved_at"]


def test_an_analyst_may_read_the_inbox_but_not_resolve(client):
    assert client.get("/api/v1/data-builder/inbox",
                      headers={"X-IPM-Role": "ANALYST"}).status_code == 200
    response = client.post(
        "/api/v1/data-builder/inbox/1/resolve",
        headers={"X-IPM-Role": "ANALYST"},
        json={"action": "reject", "note": "no"})
    assert response.status_code == 403
