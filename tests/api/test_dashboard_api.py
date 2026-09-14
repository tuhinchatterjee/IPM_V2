"""The dashboard over HTTP: one scope in, one consistent screen out.

Why these are API tests as well as unit tests
----------------------------------------------
The filtering arithmetic is held in `tests/early_warning/test_dashboard_filters
.py`. What is held HERE is the contract the browser actually meets: that an
ungoverned filter is refused with a message a screen can show rather than
silently ignored, that the export arrives as a workbook with a filename in the
header, and that a reader who cannot see Early Warning cannot export it either.
"""

from __future__ import annotations

import io

import pytest


def headers(role: str = "ANALYST") -> dict[str, str]:
    return {"X-IPM-Role": role}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    return TestClient(create_app())


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


def view(client, **payload):
    reply = client.post("/api/v1/early-warning/v2/dashboard", json=payload,
                        headers=headers())
    assert reply.status_code == 200, reply.text
    return reply.json()


# --------------------------------------------------------------- the view


def test_the_whole_screen_comes_back_from_one_request(client):
    body = view(client)
    for key in ("period", "scope", "kpis", "distribution", "trend", "rows",
                "row_count", "facets", "contract"):
        assert key in body, key


def test_the_measures_agree_with_each_other_over_http(client):
    body = view(client, filters={"ews_band": ["HIGH", "VERY_HIGH"]})
    matched = body["scope"]["matched"]
    assert body["kpis"]["borrower_count"] == matched
    assert sum(b["borrower_count"] for b in body["distribution"]) == matched
    assert body["row_count"] == matched


def test_the_screen_is_told_what_it_may_filter_by(client):
    reply = client.get("/api/v1/early-warning/v2/dashboard/contract",
                       headers=headers())
    assert reply.status_code == 200
    contract = reply.json()
    assert {c["key"] for c in contract["columns"]} >= {
        "customer", "segment", "exposure", "dpd", "ews_band"}


# ------------------------------------------------------- what is refused


def test_an_ungoverned_filter_is_refused_with_something_to_show_the_reader(
        client):
    reply = client.post("/api/v1/early-warning/v2/dashboard",
                        json={"filters": {"made_up": ["x"]}}, headers=headers())
    assert reply.status_code == 422
    detail = reply.json()["detail"]
    assert detail["error"] == "invalid_filter"
    assert "made_up" in detail["message"]
    # The message names what IS filterable, so the screen can say so.
    assert "segment" in detail["message"]


def test_an_impossible_range_is_refused_rather_than_answered_empty(client):
    reply = client.post("/api/v1/early-warning/v2/dashboard",
                        json={"filters": {"exposure": {"min": 900, "max": 1}}},
                        headers=headers())
    assert reply.status_code == 422


def test_the_export_is_guarded_exactly_as_the_view_is(client):
    """No role may download what it may not see, or see what it may not
    download. Two different guards on the same population is how a wider one
    becomes the way round the narrower.
    """
    for role in ("ADMIN", "DATA_STEWARD", "ANALYST", "VIEWER", "NOBODY"):
        seen = client.post("/api/v1/early-warning/v2/dashboard", json={},
                           headers=headers(role)).status_code
        got = client.post("/api/v1/early-warning/v2/dashboard/export", json={},
                          headers=headers(role)).status_code
        allowed = seen == 200
        assert (got == 200) is allowed, role
        if not allowed:
            # 400 for a role the product does not have, 401/403 for one it
            # has and does not admit here. Which of the three does not
            # matter; that the two endpoints answer the same way does.
            assert got == seen, role
            assert got in (400, 401, 403), role


# ------------------------------------------------------------ the export


def test_the_export_arrives_as_a_workbook_with_a_name(client):
    openpyxl = pytest.importorskip("openpyxl")
    reply = client.post("/api/v1/early-warning/v2/dashboard/export",
                        json={"filters": {"ews_band": ["HIGH", "VERY_HIGH"]}},
                        headers=headers())
    assert reply.status_code == 200
    assert reply.headers["content-type"].endswith("spreadsheetml.sheet")

    disposition = reply.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert disposition.endswith('.xlsx"')

    book = openpyxl.load_workbook(io.BytesIO(reply.content))
    assert book.sheetnames == ["Early Warning", "View"]


def test_the_export_holds_the_whole_result_and_the_screen_holds_a_page(client):
    openpyxl = pytest.importorskip("openpyxl")
    narrow = {"filters": {"ews_band": ["HIGH", "VERY_HIGH"]}, "limit": 5}

    on_screen = view(client, **narrow)
    reply = client.post("/api/v1/early-warning/v2/dashboard/export",
                        json=narrow, headers=headers())
    book = openpyxl.load_workbook(io.BytesIO(reply.content))

    assert len(on_screen["rows"]) == 5
    assert book["Early Warning"].max_row - 1 == on_screen["row_count"] > 5


def test_the_export_refuses_an_ungoverned_filter_too(client):
    reply = client.post("/api/v1/early-warning/v2/dashboard/export",
                        json={"filters": {"made_up": ["x"]}}, headers=headers())
    assert reply.status_code == 422
