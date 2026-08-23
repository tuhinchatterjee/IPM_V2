"""
Data Builder tests — the upload → inspect → map → validate → publish workflow.

The behaviour that matters most for governance is the gate: an unpublished
dataset must be invisible to the analytical engine, and a dataset with blocking
quality errors must not be publishable.

These need PostgreSQL and skip themselves without it, so the DB-free suite still
runs on a clean checkout.
"""

from __future__ import annotations

import io
import uuid

import pandas as pd
import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="Data Builder needs a reachable PostgreSQL (docker compose up -d db)",
)


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture()
def dataset_name():
    """A unique name per test, so tests never collide on leftover state."""
    return f"t_{uuid.uuid4().hex[:10]}"


def make_csv(rows: int = 25, *, duplicate_key: bool = False, bad_stage: bool = False,
             negative_ecl: bool = False) -> bytes:
    ids = [f"ACC{i:06d}" for i in range(rows)]
    if duplicate_key:
        ids[1] = ids[0]
    stages = [(i % 3) + 1 for i in range(rows)]
    if bad_stage:
        stages[0] = 7
    ecl = [round(1.5 * (i + 1), 2) for i in range(rows)]
    if negative_ecl:
        ecl[0] = -10.0
    df = pd.DataFrame({
        "CUST_NO": [f"CUS{i:05d}" for i in range(rows)],
        "FACILITY_ID": ids,
        "REPORTING_DATE": ["Q1 2026"] * rows,
        "FINAL_IMPAIRMENT": ecl,
        "STAGE": stages,
    })
    return df.to_csv(index=False).encode()


def onboard(client, name: str, csv: bytes, *, publish: bool = False) -> dict:
    """Walk a dataset through the workflow as far as requested."""
    client.post("/api/v1/data-builder/domains", json={"name": "Test Domain"})
    client.post("/api/v1/data-builder/datasets", json={
        "name": name, "domain": "Test Domain", "period_field": "period",
        "primary_keys": ["period", "account_id"], "grain": "One row per facility per period.",
    })
    upload = client.post(
        f"/api/v1/data-builder/datasets/{name}/upload",
        files={"file": (f"{name}.csv", io.BytesIO(csv), "text/csv")},
    ).json()
    client.put(f"/api/v1/data-builder/datasets/{name}/mappings", json={"mappings": [
        {"source_column": "CUST_NO", "governed_field": "customer_id", "status": "mapped"},
        {"source_column": "FACILITY_ID", "governed_field": "account_id", "status": "mapped"},
        {"source_column": "REPORTING_DATE", "governed_field": "period", "status": "mapped"},
        {"source_column": "FINAL_IMPAIRMENT", "governed_field": "final_ecl", "status": "proposed"},
        {"source_column": "STAGE", "governed_field": "ifrs9_stage", "status": "mapped"},
    ]})
    client.post(f"/api/v1/data-builder/datasets/{name}/fields/seed")
    if publish:
        client.post(f"/api/v1/data-builder/datasets/{name}/publish")
    return upload


# ==================================================================== upload


def test_upload_preserves_the_raw_file_unchanged(client, dataset_name):
    from pathlib import Path

    csv = make_csv()
    body = onboard(client, dataset_name, csv)
    raw = Path(body["upload"]["raw_path"])
    assert raw.exists()
    assert raw.read_bytes() == csv, "the raw file must be kept byte for byte"


def test_upload_rejects_an_unsupported_format(client, dataset_name):
    client.post("/api/v1/data-builder/domains", json={"name": "Test Domain"})
    client.post("/api/v1/data-builder/datasets",
                json={"name": dataset_name, "domain": "Test Domain"})
    r = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/upload",
                    files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")})
    assert r.status_code == 400
    assert "CSV" in r.json()["detail"]["message"]


@pytest.mark.parametrize("fmt", ["csv", "parquet", "xlsx"])
def test_all_three_demo_formats_are_accepted(client, dataset_name, fmt):
    df = pd.DataFrame({"A": [1, 2, 3], "B": ["x", "y", "z"]})
    buffer = io.BytesIO()
    if fmt == "csv":
        buffer.write(df.to_csv(index=False).encode())
    elif fmt == "parquet":
        df.to_parquet(buffer, index=False)
    else:
        df.to_excel(buffer, index=False)
    buffer.seek(0)

    client.post("/api/v1/data-builder/domains", json={"name": "Test Domain"})
    client.post("/api/v1/data-builder/datasets",
                json={"name": dataset_name, "domain": "Test Domain"})
    r = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/upload",
                    files={"file": (f"d.{fmt}", buffer, "application/octet-stream")})
    assert r.status_code == 200, r.json()
    assert r.json()["upload"]["row_count"] == 3


# ================================================================ inspection


def test_inspection_profiles_every_column(client, dataset_name):
    profile = onboard(client, dataset_name, make_csv())["profile"]
    assert profile["row_count"] == 25
    assert profile["column_count"] == 5
    by_name = {c["name"]: c for c in profile["columns"]}
    assert by_name["FINAL_IMPAIRMENT"]["inferred_type"] == "number"
    assert "min" in by_name["FINAL_IMPAIRMENT"] and "max" in by_name["FINAL_IMPAIRMENT"]
    assert by_name["STAGE"]["unique_count"] == 3
    assert all("null_pct" in c for c in profile["columns"])


def test_inspection_identifies_a_reporting_period_candidate(client, dataset_name):
    profile = onboard(client, dataset_name, make_csv())["profile"]
    assert "REPORTING_DATE" in profile["period_candidates"]


# =================================================================== mapping


def test_mappings_are_suggested_from_source_column_names(client, dataset_name):
    """CUST_NO should be recognised as customer_id without being told."""
    suggested = {m["source_column"]: m for m in onboard(client, dataset_name,
                                                        make_csv())["suggested_mappings"]}
    assert suggested["CUST_NO"]["governed_field"] == "customer_id"
    assert suggested["FACILITY_ID"]["governed_field"] == "account_id"
    # A suggestion is never auto-accepted — the steward has to confirm it.
    assert all(m["status"] == "unmapped" for m in suggested.values())


def test_two_columns_cannot_claim_the_same_governed_field(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    r = client.put(f"/api/v1/data-builder/datasets/{dataset_name}/mappings", json={"mappings": [
        {"source_column": "CUST_NO", "governed_field": "customer_id", "status": "mapped"},
        {"source_column": "FACILITY_ID", "governed_field": "customer_id", "status": "mapped"},
    ]})
    assert r.status_code == 400
    assert "claimed by two columns" in r.json()["detail"]["message"]


def test_mapping_supports_all_four_statuses(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    r = client.put(f"/api/v1/data-builder/datasets/{dataset_name}/mappings", json={"mappings": [
        {"source_column": "CUST_NO", "governed_field": "customer_id", "status": "mapped"},
        {"source_column": "FACILITY_ID", "status": "unmapped"},
        {"source_column": "STAGE", "status": "ignored"},
        {"source_column": "FINAL_IMPAIRMENT", "governed_field": "final_ecl", "status": "proposed"},
    ]})
    assert r.status_code == 200
    got = {m["source_column"]: m for m in r.json()["mappings"]}
    assert got["STAGE"]["governed_field"] is None  # ignored columns are dropped
    assert got["FINAL_IMPAIRMENT"]["status"] == "proposed"


def test_mapping_moves_the_dataset_to_mapped(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    detail = client.get(f"/api/v1/data-builder/datasets/{dataset_name}").json()
    assert detail["lifecycle"] == "mapped"


# ================================================================ validation


def test_validation_passes_on_clean_data(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    report = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/validate").json()
    assert report["passed"] is True
    assert report["error_count"] == 0


@pytest.mark.parametrize("flaw,rule", [
    ({"duplicate_key": True}, "primary_key_unique"),
    ({"bad_stage": True}, "valid_ifrs9_stage"),
])
def test_validation_catches_bad_data(client, dataset_name, flaw, rule):
    onboard(client, dataset_name, make_csv(**flaw))
    report = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/validate").json()
    assert report["passed"] is False
    assert rule in {f["rule"] for f in report["findings"]}


def test_validation_moves_a_clean_dataset_to_validated(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    client.post(f"/api/v1/data-builder/datasets/{dataset_name}/validate")
    assert client.get(f"/api/v1/data-builder/datasets/{dataset_name}").json()["lifecycle"] == "validated"


# =================================================================== publish


def test_publish_creates_a_version_and_writes_parquet(client, dataset_name):
    from pathlib import Path

    onboard(client, dataset_name, make_csv())
    r = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/publish")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["version"] == 1
    assert body["row_count"] == 25
    assert body["periods"] == ["Q1 2026"]
    assert Path(body["curated_path"]).exists()
    assert Path(body["analytics_path"]).exists()


def test_publish_is_refused_when_validation_fails(client, dataset_name):
    """The gate. A dataset with blocking errors must not reach the engine."""
    onboard(client, dataset_name, make_csv(duplicate_key=True))
    r = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/publish")
    assert r.status_code == 409
    assert "cannot be published" in r.json()["detail"]["message"]


def test_an_unpublished_dataset_is_invisible_to_the_engine(client, dataset_name):
    """The core governance property of the whole phase."""
    onboard(client, dataset_name, make_csv())  # mapped and valid, but NOT published
    catalog = client.get("/api/v1/catalog").json()
    assert dataset_name not in {d["name"] for d in catalog["datasets"]}


def test_a_published_dataset_becomes_visible_to_the_engine(client, dataset_name):
    onboard(client, dataset_name, make_csv(), publish=True)
    catalog = client.get("/api/v1/catalog").json()
    assert dataset_name in {d["name"] for d in catalog["datasets"]}


def test_republishing_increments_the_version(client, dataset_name):
    onboard(client, dataset_name, make_csv(), publish=True)
    second = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/publish").json()
    assert second["version"] == 2
    versions = client.get(f"/api/v1/data-builder/datasets/{dataset_name}/versions").json()
    assert versions["count"] == 2


def test_published_data_is_readable_through_the_governed_layer(client, dataset_name):
    """End to end: uploaded through Data Builder, read back through the DAL."""
    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext

    onboard(client, dataset_name, make_csv(), publish=True)
    source = get_data_source()
    assert dataset_name in source.datasets()
    frame = source.fetch(dataset_name, context=AnalysisContext(period="Q1 2026"),
                         fields=["account_id", "final_ecl"])
    assert len(frame) == 25
    assert list(frame.columns) == ["account_id", "final_ecl"]


# =============================================================== permissions


def test_a_viewer_cannot_create_a_dataset(client):
    r = client.post("/api/v1/data-builder/datasets",
                    json={"name": "should_not_exist", "domain": "Test Domain"},
                    headers={"X-IPM-Role": "VIEWER"})
    assert r.status_code == 403
    assert "DATA_STEWARD" in r.json()["detail"]["message"]


def test_an_analyst_cannot_publish(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    r = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/publish",
                    headers={"X-IPM-Role": "ANALYST"})
    assert r.status_code == 403


def test_a_data_steward_can_publish(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    r = client.post(f"/api/v1/data-builder/datasets/{dataset_name}/publish",
                    headers={"X-IPM-Role": "DATA_STEWARD"})
    assert r.status_code == 200


def test_an_unknown_role_is_rejected(client):
    """Aimed at a guarded endpoint: reading domains is deliberately open to any
    role, so the role is never evaluated there."""
    r = client.post("/api/v1/data-builder/domains", json={"name": "Nope"},
                    headers={"X-IPM-Role": "WIZARD"})
    assert r.status_code == 400
    assert "not a role" in r.json()["detail"]["message"]


# ============================================================= relationships


def test_a_relationship_can_target_a_bundled_dataset(client, dataset_name):
    """An uploaded extract joining the bundled portfolio is the main use case."""
    onboard(client, dataset_name, make_csv(), publish=True)
    r = client.post("/api/v1/data-builder/relationships", json={
        "from_dataset": dataset_name, "from_field": "account_id",
        "to_dataset": "portfolio_facility", "to_field": "account_id", "kind": "key",
    })
    assert r.status_code == 201


def test_a_relationship_to_an_unknown_dataset_is_refused(client, dataset_name):
    onboard(client, dataset_name, make_csv())
    r = client.post("/api/v1/data-builder/relationships", json={
        "from_dataset": dataset_name, "from_field": "account_id",
        "to_dataset": "no_such_dataset", "to_field": "id",
    })
    assert r.status_code == 400
