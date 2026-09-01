"""
Data Builder as a control plane, not an inventory.

The behaviours here are the ones that stop a bank looking at a number produced
from the wrong book:

  * CreditProbe says, per governed purpose, which dataset answers it and whether that
    dataset is demonstration data
  * archiving the only authoritative source for a purpose is REFUSED, and the
    refusal names the certified analyses that would stop being answerable
  * a replacement is checked field by field before it happens
  * marking client data authoritative displaces the demo dataset for that
    purpose — two authoritative sources for one purpose is not a reachable state
  * a steward's decision that something is client data survives a re-sync of the
    bundled catalogue
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL not reachable")

FACILITY = "portfolio_facility"
PURPOSE = "credit_facility_position"
CLIENT = "test_client_facility_book"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def bundled(client):
    """The bundled book, registered in Data Builder, and restored afterwards."""
    response = client.post("/api/v1/data-builder/sync-bundled")
    assert response.status_code == 200
    yield
    _cleanup(client)


def _cleanup(client) -> None:
    from backend.db.engine import get_session
    from backend.models.platform import DatasetDefinition
    from backend.services import governance

    with get_session() as session:
        row = session.query(DatasetDefinition).filter_by(name=CLIENT).first()
        if row is not None:
            session.delete(row)
        session.commit()
        governance.sync_bundled_catalog(session)
        session.commit()


@pytest.fixture
def client_dataset(client):
    """A published client dataset covering the same fields as the demo book."""
    from backend.db.engine import get_session
    from backend.models.platform import DS_PUBLISHED, DatasetDefinition, FieldDefinition
    from backend.services import data_builder as db

    with get_session() as session:
        existing = session.query(DatasetDefinition).filter_by(name=CLIENT).first()
        if existing is not None:
            session.delete(existing)
            session.commit()

        demo = db.get_dataset(session, FACILITY)
        row = DatasetDefinition(
            name=CLIENT, domain=demo.domain, business_name="Client Facility Book",
            lifecycle=DS_PUBLISHED, origin="client", dataset_family=demo.dataset_family,
            source_type="upload",
        )
        session.add(row)
        session.flush()
        for f in demo.fields:
            session.add(FieldDefinition(
                dataset_id=row.id, name=f.name, business_name=f.business_name,
                definition=f.definition, data_type=f.data_type, unit=f.unit,
            ))
        session.commit()
    yield CLIENT
    _cleanup(client)


# ------------------------------------------------------------ control plane


def test_ipm_says_which_dataset_answers_each_governed_purpose(client):
    body = client.get("/api/v1/data-builder/control-plane").json()
    by_purpose = {p["purpose"]: p for p in body["purposes"]}
    assert PURPOSE in by_purpose
    assert by_purpose[PURPOSE]["dataset"] == FACILITY
    assert by_purpose[PURPOSE]["is_demo"] is True
    assert body["using_demo_data"] is True, "a bank must never be unclear about this"


def test_datasets_are_grouped_into_families(client):
    families = client.get("/api/v1/data-builder/families").json()["families"]
    assert any(f["family"] == "portfolio_facility" for f in families)


# ------------------------------------------------------------- dependencies


def test_used_by_names_the_analyses_that_would_stop_working(client):
    body = client.get(f"/api/v1/data-builder/datasets/{FACILITY}/used-by").json()
    kinds = {d["kind"] for d in body["blocking"]}
    assert "purpose" in kinds
    assert "analysis" in kinds
    assert body["safe_to_archive"] is False


def test_archiving_the_only_authoritative_source_is_refused(client):
    response = client.post(f"/api/v1/data-builder/datasets/{FACILITY}/archive")
    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    assert PURPOSE in message
    assert "acknowledge=true" in message, "the refusal must say how to proceed anyway"


# -------------------------------------------------------------- replacement


def test_a_replacement_is_compared_field_by_field(client, client_dataset):
    body = client.get(
        f"/api/v1/data-builder/datasets/{FACILITY}/compare/{client_dataset}"
    ).json()
    assert body["compatible"] is True
    assert body["missing_fields"] == []


def test_an_incompatible_replacement_is_refused(client, client_dataset):
    """Drop a field the demo book supplies, and the handover stops."""
    from backend.db.engine import get_session
    from backend.models.platform import DatasetDefinition

    with get_session() as session:
        row = session.query(DatasetDefinition).filter_by(name=client_dataset).first()
        session.delete(row.fields[0])
        session.commit()

    comparison = client.get(
        f"/api/v1/data-builder/datasets/{FACILITY}/compare/{client_dataset}"
    ).json()
    assert comparison["compatible"] is False
    assert comparison["missing_fields"]

    response = client.post(
        f"/api/v1/data-builder/datasets/{FACILITY}/replace",
        json={"incoming": client_dataset},
    )
    assert response.status_code == 409
    assert "field(s) missing" in response.json()["detail"]["message"]


def test_client_data_takes_the_purpose_and_displaces_the_demo_book(client, client_dataset):
    body = client.post(
        f"/api/v1/data-builder/datasets/{FACILITY}/replace",
        json={"incoming": client_dataset},
    ).json()

    assert body["purposes_transferred"] == [PURPOSE]
    assert FACILITY in body["handover"]["displaced_demo_datasets"]

    plane = client.get("/api/v1/data-builder/control-plane").json()
    resolved = {p["purpose"]: p for p in plane["purposes"]}[PURPOSE]
    assert resolved["dataset"] == client_dataset
    assert resolved["is_demo"] is False


def test_only_one_dataset_can_be_authoritative_for_a_purpose(client, client_dataset):
    client.post(f"/api/v1/data-builder/datasets/{client_dataset}/authoritative",
                json={"purposes": [PURPOSE]})
    datasets = client.get("/api/v1/data-builder/datasets").json()["datasets"]
    claiming = [
        d["name"] for d in datasets
        if PURPOSE in (d.get("authoritative_for") or [])
    ]
    assert claiming == [client_dataset]


def test_an_unpublished_dataset_cannot_be_authoritative(client):
    from backend.db.engine import get_session
    from backend.models.platform import DS_DRAFT, DatasetDefinition

    with get_session() as session:
        session.add(DatasetDefinition(
            name="test_draft_book", domain="Core Portfolio / Facility",
            lifecycle=DS_DRAFT, origin="client",
        ))
        session.commit()
    try:
        response = client.post(
            "/api/v1/data-builder/datasets/test_draft_book/authoritative",
            json={"purposes": [PURPOSE]},
        )
        assert response.status_code == 400
        assert "not published" in response.json()["detail"]["message"]
    finally:
        with get_session() as session:
            row = session.query(DatasetDefinition).filter_by(name="test_draft_book").first()
            if row:
                session.delete(row)
            session.commit()


def test_an_unknown_purpose_is_refused(client):
    response = client.post(
        f"/api/v1/data-builder/datasets/{FACILITY}/authoritative",
        json={"purposes": ["whatever_we_feel_like"]},
    )
    assert response.status_code == 400
    assert "Not governed purposes" in response.json()["detail"]["message"]


def test_a_stewards_client_marking_survives_a_resync(client, client_dataset):
    """The bundled catalogue does not get to overwrite a governance decision."""
    body = client.post("/api/v1/data-builder/sync-bundled").json()
    assert client_dataset not in body["synced"]

    datasets = {d["name"]: d for d in client.get("/api/v1/data-builder/datasets").json()["datasets"]}
    assert datasets[client_dataset]["origin"] == "client"
