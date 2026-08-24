"""
Engine and Trace API tests.

The important cases are the refusals. This surface is what the LLM planner will
drive in Phase 3, so it has to be impossible to reach a calculation through it
except by naming a registered analysis with parameters its contract accepts.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.helpers import FACILITY


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built — run `python scripts/build_data_lake.py`")


# =================================================================== library


def test_library_lists_ten_certified_and_one_user_defined(client):
    body = client.get("/api/v1/engine/analyses").json()
    assert body["certified"] == 10
    assert body["user_defined"] == 1
    assert body["total"] == 11


def test_library_can_filter_to_certified_only(client):
    body = client.get("/api/v1/engine/analyses", params={"certified_only": True}).json()
    assert all(a["is_certified"] for a in body["analyses"])
    assert body["total"] == 10


def test_analysis_definition_carries_everything_engine_builder_shows(client):
    body = client.get("/api/v1/engine/analyses/stage_migration").json()
    for key in ("id", "name", "description", "category", "version", "owner",
                "certification", "required_datasets", "required_fields", "parameters",
                "outputs", "validation_rules", "supported_visualizations",
                "calculation_description", "datasets", "validation_status"):
        assert key in body, key
    assert body["datasets"][0]["available"] is True


def test_unknown_analysis_returns_404(client):
    assert client.get("/api/v1/engine/analyses/not_real").status_code == 404


# =================================================================== execute


def test_execute_returns_result_and_trace(client):
    r = client.post("/api/v1/engine/analyses/portfolio_summary/execute", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["result"]["values"]["total_ead"] > 0
    assert body["trace"]["stats"]["node_count"] > 5
    assert body["analysis_run_id"] is not None


def test_execute_rejects_an_unregistered_analysis(client):
    """The wall: an invented calculation cannot be executed."""
    r = client.post("/api/v1/engine/analyses/drop_all_tables/execute", json={})
    assert r.status_code == 404


def test_execute_rejects_a_parameter_the_contract_does_not_accept(client):
    r = client.post("/api/v1/engine/analyses/portfolio_summary/execute",
                    json={"params": {"sql": "SELECT * FROM users"}})
    assert r.status_code == 422
    assert "does not accept" in r.json()["detail"]["message"]


def test_execute_rejects_a_value_outside_the_allowed_set(client):
    r = client.post("/api/v1/engine/analyses/sector_concentration/execute",
                    json={"params": {"dimension": "borrower_name"}})
    assert r.status_code == 422


def test_execute_rejects_a_value_outside_its_numeric_bounds(client):
    r = client.post("/api/v1/engine/analyses/sector_concentration/execute",
                    json={"params": {"top_n": 9999}})
    assert r.status_code == 422


def test_execute_rejects_an_unknown_period(client):
    r = client.post("/api/v1/engine/analyses/portfolio_summary/execute",
                    json={"params": {"period": "Q9 1999"}})
    assert r.status_code == 400
    assert "not a reporting period" in r.json()["detail"]["message"]


def test_a_failed_run_still_returns_its_trace(client):
    """Where an analysis stopped is exactly what someone needs to know."""
    r = client.post("/api/v1/engine/analyses/stage_migration/execute",
                    json={"params": {"from_period": "latest", "to_period": "latest"}})
    assert r.status_code == 400
    assert r.json()["detail"]["trace"]["stats"]["node_count"] >= 1


def test_a_viewer_cannot_execute_an_analysis(client):
    r = client.post("/api/v1/engine/analyses/portfolio_summary/execute", json={},
                    headers={"X-IPM-Role": "VIEWER"})
    assert r.status_code == 403


def test_filters_are_honoured_by_the_api(client):
    whole = client.post("/api/v1/engine/analyses/portfolio_summary/execute",
                        json={}).json()["result"]["values"]["total_ead"]
    part = client.post("/api/v1/engine/analyses/portfolio_summary/execute",
                       json={"filters": {"sector": "Contracting"}}).json()["result"]["values"]["total_ead"]
    assert 0 < part < whole


# ======================================================== periods/dimensions


def test_periods_lists_what_is_available_with_aliases(client):
    body = client.get("/api/v1/engine/periods").json()
    assert body["count"] >= 2
    assert body["latest"] == body["periods"][-1]
    assert body["earliest"] == body["periods"][0]
    assert body["aliases"]["previous"] == body["periods"][-2]


def test_dimensions_lists_filterable_fields_and_their_values(client):
    body = client.get("/api/v1/engine/dimensions").json()
    by_field = {d["field"]: d for d in body["dimensions"]}
    assert "sector" in by_field
    assert by_field["sector"]["values"]
    assert by_field["sector"]["definition"]


# ===================================================================== trace


def test_trace_can_be_retrieved_after_execution(client):
    run_id = client.post("/api/v1/engine/analyses/stage_distribution/execute",
                         json={}).json()["analysis_run_id"]
    body = client.get(f"/api/v1/trace/{run_id}").json()
    assert body["version"] == 1
    assert body["graph"]["nodes"]
    assert len(body["node_hashes"]) == len(body["graph"]["nodes"])


def test_trace_records_the_function_version_that_produced_the_result(client):
    """Reproducibility: a number must be attributable to an exact version."""
    run_id = client.post("/api/v1/engine/analyses/ecl_movement/execute",
                         json={}).json()["analysis_run_id"]
    nodes = client.get(f"/api/v1/trace/{run_id}").json()["graph"]["nodes"]
    engine_node = next(n for n in nodes if n["type"] == "ENGINE_FUNCTION")
    assert engine_node["function_id"] == "ecl_movement"
    assert engine_node["function_version"]


def test_trace_distinguishes_governed_from_interpretive_nodes(client):
    run_id = client.post("/api/v1/engine/analyses/portfolio_summary/execute",
                         json={}).json()["analysis_run_id"]
    body = client.get(f"/api/v1/trace/{run_id}").json()
    assert body["graph"]["stats"]["governed_nodes"] > 0
    assert all(isinstance(n["is_governed"], bool) for n in body["graph"]["nodes"])


def test_trace_records_row_counts_as_evidence(client):
    run_id = client.post("/api/v1/engine/analyses/portfolio_summary/execute",
                         json={}).json()["analysis_run_id"]
    nodes = client.get(f"/api/v1/trace/{run_id}").json()["graph"]["nodes"]
    dataset_node = next(n for n in nodes if n["type"] == "DATASET")
    assert dataset_node["rows_out"] > 0
    assert dataset_node["fields_used"]


def test_missing_trace_returns_404(client):
    assert client.get("/api/v1/trace/99999999").status_code == 404


def test_no_endpoint_accepts_sql_or_a_file_path(client):
    """A structural guarantee, checked against the generated OpenAPI schema: the
    engine surface exposes no way to send raw SQL, Python or a path."""
    schema = client.get("/openapi.json").json()
    text = str(schema).lower()
    for forbidden in ('"sql"', '"query"', '"file_path"', '"python"', '"expression"'):
        assert forbidden not in text, f"engine API exposes {forbidden}"
