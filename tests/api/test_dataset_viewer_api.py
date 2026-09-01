"""
The dataset viewer and the domain landing page, over HTTP.

Two things are being checked here that the service-level tests cannot see:
who is allowed to do this, and what the wire format actually says. A refusal
that only exists in the service is not a control — the endpoint has to enforce
it, and a Viewer has to get a 403 rather than a page of governed rows.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="The viewer API needs a reachable PostgreSQL (docker compose up -d db)",
)

DATASET = "portfolio_facility"
STEWARD = {"X-IPM-Role": "DATA_STEWARD"}
VIEWER = {"X-IPM-Role": "VIEWER"}
ADMIN = {"X-IPM-Role": "ADMIN"}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def rows_url() -> str:
    return f"/api/v1/data-builder/datasets/{DATASET}/rows"


# --------------------------------------------------------------- the rows


def test_a_steward_reads_a_page_not_the_dataset(client, rows_url):
    body = client.get(rows_url, params={"limit": 5}, headers=STEWARD).json()
    assert body["returned"] <= 5
    assert len(body["rows"]) == body["returned"]
    assert body["total_rows"] > body["returned"], "the fixture book should be large"


def test_a_viewer_may_not_read_governed_rows(client, rows_url):
    assert client.get(rows_url, headers=VIEWER).status_code == 403


def test_the_page_carries_every_governed_field_name(client, rows_url):
    """So the grid can offer a hidden column without a second request."""
    body = client.get(rows_url, params={"limit": 1}, headers=STEWARD).json()
    assert body["all_fields"]
    assert {f["name"] for f in body["fields"]} <= set(body["all_fields"])


def test_a_filter_on_an_ungoverned_column_is_refused(client, rows_url):
    response = client.get(rows_url, params={"filter": "secret_salary:eq:1"},
                          headers=STEWARD)
    assert response.status_code == 422
    assert "not a field" in response.json()["detail"]["message"]


def test_an_operator_outside_the_offered_set_is_refused(client, rows_url):
    response = client.get(rows_url, params={"filter": "ead:like:%1%"},
                          headers=STEWARD)
    assert response.status_code == 422
    assert "not a comparison" in response.json()["detail"]["message"]


def test_a_sort_on_an_ungoverned_column_is_refused(client, rows_url):
    response = client.get(rows_url, params={"sort": "1; drop table x"},
                          headers=STEWARD)
    assert response.status_code == 422


def test_filtering_reports_the_unfiltered_count_too(client, rows_url):
    body = client.get(rows_url, params={"limit": 1, "filter": "ifrs9_stage:eq:2"},
                      headers=STEWARD).json()
    assert body["filtered"] is True
    assert body["total_rows"] < body["total_in_period"]


def test_filters_and_search_combine(client, rows_url):
    stage2 = client.get(rows_url, params={"limit": 1, "filter": "ifrs9_stage:eq:2"},
                        headers=STEWARD).json()
    both = client.get(
        rows_url,
        params={"limit": 1, "filter": "ifrs9_stage:eq:2", "q": "Riyadh"},
        headers=STEWARD,
    ).json()
    assert both["total_rows"] <= stage2["total_rows"]


# ----------------------------------------------------------- column profile


def test_a_column_profile_is_served_to_a_steward(client):
    body = client.get(
        f"/api/v1/data-builder/datasets/{DATASET}/columns/ifrs9_stage",
        headers=STEWARD,
    ).json()
    assert body["field"] == "ifrs9_stage"
    assert body["rows"] > 0
    assert body["top_values"]


def test_profiling_an_ungoverned_column_is_refused(client):
    response = client.get(
        f"/api/v1/data-builder/datasets/{DATASET}/columns/salary", headers=STEWARD,
    )
    assert response.status_code == 422


def test_a_viewer_may_not_profile_a_column(client):
    response = client.get(
        f"/api/v1/data-builder/datasets/{DATASET}/columns/ead", headers=VIEWER,
    )
    assert response.status_code == 403


# ------------------------------------------------------------------ export


def test_an_export_leads_with_the_header_row(client):
    """A spreadsheet reads line one as the column names."""
    response = client.get(
        f"/api/v1/data-builder/datasets/{DATASET}/export",
        params={"limit": 3}, headers=STEWARD,
    )
    assert response.status_code == 200
    lines = response.text.splitlines()
    assert not lines[0].startswith("#")
    assert "," in lines[0]


def test_an_export_records_its_provenance_after_the_data(client):
    response = client.get(
        f"/api/v1/data-builder/datasets/{DATASET}/export",
        params={"limit": 3, "filter": "ifrs9_stage:eq:3"}, headers=STEWARD,
    )
    trailer = "\n".join(
        line for line in response.text.splitlines() if line.startswith("#")
    )
    assert "ifrs9_stage:eq:3" in trailer
    assert "TRUNCATED" in trailer


def test_a_synthetic_export_says_so_in_the_file_and_the_filename(client):
    response = client.get(
        f"/api/v1/data-builder/datasets/{DATASET}/export",
        params={"limit": 2}, headers=STEWARD,
    )
    assert "SYNTHETIC" in response.text
    assert "SYNTHETIC" in response.headers["content-disposition"]
    assert response.headers["x-creditprobe-synthetic"] == "true"


def test_a_viewer_may_not_export(client):
    response = client.get(
        f"/api/v1/data-builder/datasets/{DATASET}/export", headers=VIEWER,
    )
    assert response.status_code == 403


# ---------------------------------------------------------------- domains


def test_the_domain_overview_reports_size_and_coverage(client):
    body = client.get("/api/v1/data-builder/domains/overview", headers=STEWARD).json()
    assert body["domains"], "no domains defined"
    for domain in body["domains"]:
        assert domain["status"] in {"ACTIVE", "ARCHIVED"}
        assert domain["dataset_count"] >= domain["published_count"] >= 0
        assert domain["row_count"] >= 0
        if domain["first_period"] and domain["last_period"]:
            assert domain["period_count"] >= 1


def test_a_domain_holding_datasets_cannot_be_deleted(client):
    """The refusal names what is in the way, rather than just saying no."""
    overview = client.get("/api/v1/data-builder/domains/overview",
                          headers=STEWARD).json()["domains"]
    occupied = next((d for d in overview if d["dataset_count"] > 0), None)
    if occupied is None:
        pytest.skip("no domain currently holds a dataset")

    response = client.delete(
        f"/api/v1/data-builder/domains/{occupied['name']}", headers=ADMIN,
    )
    assert response.status_code == 400
    message = response.json()["detail"]["message"]
    assert occupied["datasets"][0]["name"] in message


def test_a_viewer_may_not_archive_a_domain(client):
    overview = client.get("/api/v1/data-builder/domains/overview",
                          headers=STEWARD).json()["domains"]
    if not overview:
        pytest.skip("no domains defined")
    response = client.post(
        f"/api/v1/data-builder/domains/{overview[0]['name']}/status",
        json={"status": "ARCHIVED"}, headers=VIEWER,
    )
    assert response.status_code == 403


def test_an_unknown_domain_status_is_refused(client):
    response = client.post(
        "/api/v1/data-builder/domains/Anything/status",
        json={"status": "DELETED"}, headers=STEWARD,
    )
    assert response.status_code == 422


def test_archiving_and_restoring_a_domain_round_trips(client):
    overview = client.get("/api/v1/data-builder/domains/overview",
                          headers=STEWARD).json()["domains"]
    subject = next((d for d in overview if d["status"] == "ACTIVE"), None)
    if subject is None:
        pytest.skip("no active domain to archive")
    name = subject["name"]

    try:
        archived = client.post(
            f"/api/v1/data-builder/domains/{name}/status",
            json={"status": "ARCHIVED"}, headers=STEWARD,
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "ARCHIVED"

        # Archiving must not hide the datasets or stop them being read.
        after = client.get("/api/v1/data-builder/domains/overview",
                           headers=STEWARD).json()["domains"]
        same = next(d for d in after if d["name"] == name)
        assert same["dataset_count"] == subject["dataset_count"]
        assert same["row_count"] == subject["row_count"]
    finally:
        client.post(f"/api/v1/data-builder/domains/{name}/status",
                    json={"status": "ACTIVE"}, headers=STEWARD)
