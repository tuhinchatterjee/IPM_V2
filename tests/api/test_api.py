"""
API tests.

These cover the contract the Next.js front end is written against. The health
endpoint gets the most attention because it is the one thing that must work when
everything else is broken — it is how a non-developer finds out *what* is broken.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app

VALID_STATUSES = {"ok", "degraded", "unavailable", "not_configured", "empty"}


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ------------------------------------------------------------------- health


def test_health_always_answers(client):
    """The health endpoint must respond even when dependencies are down —
    otherwise it cannot tell you which dependency is down."""
    assert client.get("/api/v1/health").status_code == 200


def test_health_reports_every_component(client):
    body = client.get("/api/v1/health").json()
    names = {c["name"] for c in body["components"]}
    assert names == {"postgresql", "analytical_store", "data_catalog", "ipm_engine"}


def test_health_statuses_are_from_the_known_set(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] in {"ok", "degraded", "unavailable"}
    for component in body["components"]:
        assert component["status"] in VALID_STATUSES


def test_every_component_explains_itself_in_plain_english(client):
    """These strings are shown to a non-developer in the status panel, so an
    empty detail is a real defect rather than a cosmetic one."""
    for component in client.get("/api/v1/health").json()["components"]:
        assert component["detail"].strip(), f"{component['name']} reports no explanation"


def test_overall_status_is_the_worst_component(client):
    body = client.get("/api/v1/health").json()
    severity = {"ok": 0, "empty": 1, "not_configured": 2, "degraded": 2, "unavailable": 3}
    worst = max(severity[c["status"]] for c in body["components"])
    expected = "ok" if worst <= 1 else ("degraded" if worst == 2 else "unavailable")
    assert body["status"] == expected


def test_health_identifies_the_build_phase(client):
    body = client.get("/api/v1/health").json()
    assert body["phase"]
    assert body["version"]
    assert body["environment"]


def test_healthz_probe_has_no_dependencies(client):
    """A plain liveness probe that must never touch the database."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ------------------------------------------------------------------ catalog


def test_catalog_lists_governed_datasets(client):
    body = client.get("/api/v1/catalog").json()
    assert body["dataset_count"] >= 1
    assert body["field_count"] > 0
    assert body["domains"]


def test_catalog_flags_synthetic_data(client):
    """Synthetic data must be labelled wherever its figures appear. If the API
    does not carry the flag, the UI cannot show it."""
    body = client.get("/api/v1/catalog").json()
    for dataset in body["datasets"]:
        assert isinstance(dataset["is_synthetic"], bool)


def test_catalog_exposes_grain_for_each_dataset(client):
    """Grain — what one row represents — is the most misunderstood property of a
    table and the one Data Builder must always show."""
    for dataset in client.get("/api/v1/catalog").json()["datasets"]:
        assert dataset["grain"].strip()


# ------------------------------------------------------------- engine library


def test_engine_library_responds_when_empty(client):
    """Phase 1 registers no analyses. An empty library is a valid state and must
    not be an error."""
    r = client.get("/api/v1/engine/library")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(body["analyses"])
    assert body["certified"] <= body["total"]


def test_every_analysis_declares_its_certification(client):
    """The blue tick is a control. An analysis with no certification value would
    render as uncertified-by-accident rather than by decision."""
    for analysis in client.get("/api/v1/engine/library").json()["analyses"]:
        assert analysis["certification"] in {"certified", "user_defined", "draft", "deprecated"}
        assert isinstance(analysis["is_certified"], bool)


# ------------------------------------------------------------------- plumbing


def test_root_points_at_health_and_docs(client):
    body = client.get("/").json()
    assert body["health"] == "/api/v1/health"


def test_every_response_carries_a_request_id(client):
    """The id is echoed to the browser and will be written onto trace nodes, so a
    wrong number on screen can be traced back to its server-side log lines."""
    r = client.get("/api/v1/health")
    assert r.headers.get("x-request-id")
    assert r.headers.get("x-response-time-ms")


def test_supplied_request_id_is_preserved(client):
    r = client.get("/api/v1/health", headers={"x-request-id": "trace-me-123"})
    assert r.headers["x-request-id"] == "trace-me-123"


def test_unknown_route_returns_json_not_html(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_openapi_schema_is_available_in_dev(client):
    """The TypeScript client is generated against this; if it stops being served
    the front end silently drifts from the backend."""
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/health" in r.json()["paths"]
