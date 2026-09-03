"""The Metric Catalogue over HTTP.

What these prove, beyond the routes returning 200: that a caller cannot get a
number into the platform, cannot get a formula in as text, cannot be told a
metric exists over data they may not read, and is never handed a raw 500 for a
bad request.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import settings
from backend.metrics import service

ANALYST = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}
VIEWER = {"X-IPM-Role": "VIEWER", "X-IPM-User-Id": "2"}

needs_db = pytest.mark.skipif(not settings.has_database,
                              reason="user metrics are stored in PostgreSQL")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _late_share() -> dict:
    """A ratio submitted the only way the API accepts one: structured."""
    return {
        "kind": "percentage", "scale": 100.0,
        "numerator": {"terms": [{
            "id": "late", "label": "Balance 30+ DPD",
            "dataset": "retail_behavioral_scorecard_monthly_validation",
            "aggregate": "sum", "field": "current_balance",
            "where": [{"field": "current_dpd", "op": ">=", "value": 30}]}]},
        "denominator": {"terms": [{
            "id": "all", "label": "Total balance",
            "dataset": "retail_behavioral_scorecard_monthly_validation",
            "aggregate": "sum", "field": "current_balance"}]},
    }


# ---------------------------------------------------------------- searching


def test_the_picker_does_not_open_with_the_whole_catalogue(client):
    body = client.get("/api/v1/metrics", headers=ANALYST).json()
    assert body["results"] == []
    assert body["count"] == 0


def test_typing_narrows_rather_than_widens(client):
    broad = client.get("/api/v1/metrics", params={"q": "delinq", "limit": 50},
                       headers=ANALYST).json()
    narrow = client.get("/api/v1/metrics",
                        params={"q": "delinq 30", "limit": 50},
                        headers=ANALYST).json()
    assert 0 < narrow["count"] < broad["count"]
    ids = {r["metric_id"] for r in narrow["results"]}
    assert "retail.dpd_30_count" in ids
    assert "retail.dpd_60_count" not in ids


def test_a_search_that_finds_nothing_explains_what_is_unavailable(client):
    body = client.get("/api/v1/metrics", params={"q": "roll rate"},
                      headers=ANALYST).json()
    assert body["results"] == []
    assert body["unavailable"]
    assert body["unavailable"][0]["because"].strip()


def test_the_whole_catalogue_is_available_deliberately(client):
    body = client.get("/api/v1/metrics/all", headers=ANALYST).json()
    assert len(body["domains"]) >= 3
    assert sum(len(d["metrics"]) for d in body["domains"]) >= 60
    assert body["unavailable"], "the catalogue must say what it cannot do"


# ------------------------------------------------------------- one metric


def test_the_panel_carries_everything_a_reader_may_ask(client):
    body = client.get("/api/v1/metrics/corporate.ifrs9.coverage",
                      headers=ANALYST).json()
    for field in ("definition", "formula", "numerator", "denominator",
                  "source_fields", "period_rule", "not_this", "owner",
                  "origin_label", "status_label", "version"):
        assert body.get(field) not in (None, ""), field


def test_a_metric_that_does_not_exist_is_a_clean_404(client):
    r = client.get("/api/v1/metrics/no.such.metric", headers=ANALYST)
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "not_found"


def test_a_metric_this_deployment_cannot_calculate_says_why(client):
    r = client.get("/api/v1/metrics/retail.roll_rate", headers=ANALYST)
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "metric_unavailable"
    assert detail["message"].strip()
    assert detail["metric"]["needs"]


def test_calculating_returns_a_number_and_its_working(client):
    body = client.get("/api/v1/metrics/corporate.ifrs9.coverage/value",
                      params={"period": "Q4 2024"}, headers=ANALYST).json()
    assert body["available"] is True
    assert 0.0 < body["value"] < 100.0
    assert body["calculation"]["sql"].strip()
    assert "=" in body["calculation"]["final"]


def test_a_period_with_no_data_is_explained_rather_than_a_500(client):
    r = client.get("/api/v1/metrics/corporate.ifrs9.coverage/value",
                   params={"period": "1999-01"}, headers=ANALYST)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "1999-01" in body["unavailable"]


def test_the_rows_behind_a_metric_can_be_looked_at(client):
    body = client.get("/api/v1/metrics/retail.dpd_30_balance/rows",
                      params={"limit": 5}, headers=ANALYST).json()
    assert 0 < len(body["rows"]) <= 5
    assert body["columns"]


# ------------------------------------------------------------ permissions


def test_a_viewer_cannot_read_the_catalogue(client):
    for path in ("/api/v1/metrics", "/api/v1/metrics/all",
                 "/api/v1/metrics/corporate.ifrs9.coverage"):
        assert client.get(path, headers=VIEWER).status_code == 403, path


def test_a_viewer_cannot_build_a_metric(client):
    r = client.post("/api/v1/metrics", headers=VIEWER,
                    json={"name": "Mine", "formula": _late_share()})
    assert r.status_code == 403


def test_the_metric_routes_sit_behind_the_login_gate(monkeypatch, client):
    """The suite runs with REQUIRE_LOGIN off, so this turns it back on.

    Otherwise the assertion would be about the test environment rather than
    about these routes: with the gate down, an unauthenticated caller is
    treated as an administrator and every one of these returns 200.
    """
    from dataclasses import replace

    import backend.api.permissions as permissions
    from backend.config import settings

    monkeypatch.setattr(permissions, "settings",
                        replace(settings, require_login=True))
    for path in ("/api/v1/metrics", "/api/v1/metrics/all",
                 "/api/v1/metrics/corporate.ifrs9.coverage",
                 "/api/v1/metrics/corporate.ifrs9.coverage/value"):
        assert client.get(path).status_code == 401, path
    # A header must not get past the refusal — the thing an attacker tries.
    assert client.get("/api/v1/metrics/all",
                      headers={"X-IPM-Role": "ADMIN"}).status_code == 401


# --------------------------------------------------------------- building


@needs_db
def test_a_metric_arrives_as_a_draft_and_is_labelled_as_one(client):
    r = client.post("/api/v1/metrics", headers=ANALYST, json={
        "name": "Api Late Share", "definition": "Balance 30+ DPD over the book.",
        "formula": _late_share(), "unit": "percent"})
    assert r.status_code == 201, r.text
    body = r.json()
    try:
        assert body["origin_label"] == "User built"
        assert body["status_label"] == "Draft"
        assert body["governed"] is False
        assert body["trustworthy"] is False
    finally:
        client.delete(f"/api/v1/metrics/{body['metric_id']}", headers=ANALYST)


@needs_db
def test_the_lifecycle_runs_draft_to_calculates_to_verified(client):
    made = client.post("/api/v1/metrics", headers=ANALYST, json={
        "name": "Api Lifecycle Share", "formula": _late_share(),
        "unit": "percent"}).json()
    metric_id = made["metric_id"]
    try:
        checked = client.post(f"/api/v1/metrics/{metric_id}/calculate",
                              headers=ANALYST).json()
        assert checked["available"] is True
        assert checked["metric"]["status_label"] == "Calculates"

        verified = client.post(
            f"/api/v1/metrics/{metric_id}/verify", headers=ANALYST,
            json={"expected": checked["value"], "decision": "ACCEPTED",
                  "expected_source": "recomputed by hand"}).json()
        assert verified["agrees"] is True
        assert verified["metric_status"] == "VERIFIED"

        history = client.get(f"/api/v1/metrics/{metric_id}/verifications",
                             headers=ANALYST).json()
        assert len(history["verifications"]) == 1
    finally:
        client.delete(f"/api/v1/metrics/{metric_id}", headers=ANALYST)


@needs_db
def test_a_caller_cannot_simply_declare_a_metric_verified(client):
    made = client.post("/api/v1/metrics", headers=ANALYST, json={
        "name": "Api Assert Verified", "formula": _late_share(),
        "unit": "percent"}).json()
    try:
        r = client.post(f"/api/v1/metrics/{made['metric_id']}/status",
                        headers=ANALYST, json={"status": "VERIFIED"})
        assert r.status_code == 422
        assert "checked against" in r.json()["detail"]["message"]
    finally:
        client.delete(f"/api/v1/metrics/{made['metric_id']}", headers=ANALYST)


@needs_db
def test_a_disagreement_is_recorded_and_confers_nothing(client):
    made = client.post("/api/v1/metrics", headers=ANALYST, json={
        "name": "Api Disagreement", "formula": _late_share(),
        "unit": "percent"}).json()
    metric_id = made["metric_id"]
    try:
        truth = client.post(f"/api/v1/metrics/{metric_id}/calculate",
                            headers=ANALYST).json()["value"]
        body = client.post(f"/api/v1/metrics/{metric_id}/verify",
                           headers=ANALYST,
                           json={"expected": truth + 7.0,
                                 "decision": "ACCEPTED"}).json()
        assert body["outcome"] == service.OUTCOME_DIFFERS
        assert body["metric_status"] != "VERIFIED"
        assert body["computed"] == pytest.approx(truth), (
            "the computed value must never move toward the expectation")
    finally:
        client.delete(f"/api/v1/metrics/{metric_id}", headers=ANALYST)


@needs_db
def test_changing_the_arithmetic_drops_the_verification(client):
    made = client.post("/api/v1/metrics", headers=ANALYST, json={
        "name": "Api Reformed", "formula": _late_share(),
        "unit": "percent"}).json()
    metric_id = made["metric_id"]
    try:
        truth = client.post(f"/api/v1/metrics/{metric_id}/calculate",
                            headers=ANALYST).json()["value"]
        client.post(f"/api/v1/metrics/{metric_id}/verify", headers=ANALYST,
                    json={"expected": truth, "decision": "ACCEPTED"})
        changed = {**_late_share(), "scale": 1.0}
        after = client.patch(f"/api/v1/metrics/{metric_id}", headers=ANALYST,
                             json={"formula": changed}).json()
        assert after["status_label"] == "Draft"
        assert after["verified_by"] is None
    finally:
        client.delete(f"/api/v1/metrics/{metric_id}", headers=ANALYST)


@needs_db
def test_a_metric_belongs_to_the_person_who_built_it(client):
    made = client.post("/api/v1/metrics", headers=ANALYST, json={
        "name": "Api Ownership", "formula": _late_share()}).json()
    other = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "99"}
    try:
        assert client.patch(f"/api/v1/metrics/{made['metric_id']}",
                            headers=other,
                            json={"name": "Mine"}).status_code == 422
        assert client.delete(f"/api/v1/metrics/{made['metric_id']}",
                             headers=other).status_code == 422
    finally:
        client.delete(f"/api/v1/metrics/{made['metric_id']}", headers=ANALYST)


# ------------------------------------------------------------ what it refuses


@pytest.mark.parametrize("formula,why", [
    ({}, "an empty formula"),
    ({"kind": "nonsense"}, "a kind that does not exist"),
    ({"kind": "percentage", "numerator": "1=1; DROP TABLE users"},
     "a string where a structured side belongs"),
    ({"kind": "sum", "numerator": {"terms": [{
        "id": "x", "dataset": "retail_behavioral_scorecard_monthly_validation",
        "aggregate": "sum", "field": "no_such_column"}]}},
     "a field the catalogue does not have"),
    ({"kind": "sum", "numerator": {"terms": [{
        "id": "x", "dataset": "there_is_no_such_dataset",
        "aggregate": "sum", "field": "x"}]}},
     "a dataset the catalogue does not have"),
])
def test_a_formula_that_cannot_calculate_is_refused_with_a_reason(
        client, formula, why):
    r = client.post("/api/v1/metrics", headers=ANALYST,
                    json={"name": f"Doomed {why}", "formula": formula})
    assert r.status_code == 422, f"{why} was accepted"
    assert r.json()["detail"]["message"].strip()


def test_no_request_produces_an_unexplained_500(client):
    """Every refusal above arrives as a sentence, not a stack trace."""
    for payload in ({"name": "x", "formula": {"kind": "sum",
                                              "numerator": []}},
                    {"name": "x", "formula": {"numerator": {"terms": "nope"}}},
                    {"name": "", "formula": _late_share()}):
        r = client.post("/api/v1/metrics", headers=ANALYST, json=payload)
        assert r.status_code < 500, payload
