"""Playbook over HTTP. PB-002, PB-005, PB-006, PB-020, PB-037.

Exercised through the real application with a real database, because the
refusals that matter here — a foreign tenant's export, an id that was never
exported, a download of somebody else's file — are enforced in the route and
the repository, not in the picker.
"""

from __future__ import annotations

import io

import pytest

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="the Playbook API needs the platform database")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import create_app

    with TestClient(create_app()) as c:
        c.headers.update({"X-IPM-Role": "ADMIN"})
        yield c


@pytest.fixture(autouse=True)
def _clean_playbook_rows():
    """Remove what these tests created.

    The API tests go through the real application, so they commit — the
    transaction-rollback fixture used elsewhere in this suite cannot help here.
    `tests/exports/conftest.py` solves the same problem the same way, and the
    reason it matters is written down in backend/demo/workspace.py: a
    development database that accumulates test rows is one nobody can
    demonstrate from.
    """
    yield
    from sqlalchemy import text

    from backend.db.engine import get_session

    with get_session() as session:
        session.execute(text(
            "TRUNCATE analysis_export_revisions, analysis_exports, "
            "playbook_artifact_files, playbook_artifact_versions, "
            "playbook_artifacts, playbook_attachments, playbook_change_items, "
            "playbook_change_sets, playbook_jobs, playbook_messages, "
            "playbook_source_chunks, playbook_sources, playbook_workspaces "
            "RESTART IDENTITY CASCADE"))


@pytest.fixture
def workspace_id(client) -> int:
    response = client.post("/api/v1/playbook/workspaces",
                           json={"title": "API test workspace"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _export_body(**over) -> dict:
    body = {
        "source_module": "cockpit",
        "title": "Stage migration, Q2 2026",
        "question": "Which sectors drove the Stage 2 increase?",
        "narrative": ("Stage 2 exposure rose by SAR 41.00 million, "
                      "concentrated in Contracting. The movement is driven by "
                      "two obligors whose utilisation rose sharply."),
        "tables": [{"id": "by_sector", "title": "By sector",
                    "columns": ["Sector", "Movement"],
                    "rows": [["Contracting", "41.00"]],
                    "units": {"Movement": "SAR million"}}],
        "source_ref": {"run_id": 8801},
        "reporting_period": "Q2 2026",
        "insight": "Stage 2 rose, concentrated in Contracting.",
    }
    body.update(over)
    return body


class TestCapabilitiesAreReportedHonestly:
    def test_the_formats_are_listed(self, client):
        body = client.get("/api/v1/playbook/capabilities").json()
        assert {f["format"] for f in body["formats"]} == {"docx", "pdf", "pptx",
                                                          "xlsx"}

    def test_the_provider_state_is_reported_without_a_credential(self, client):
        """Naming the variable is how an operator knows what to set. Carrying
        its VALUE is the thing that must never happen, so this looks for a key
        rather than for the word."""
        import os
        import re

        body = client.get("/api/v1/playbook/capabilities").json()
        assert "configured" in body["provider"]
        blob = str(body)
        assert not re.search(r"sk-ant-[A-Za-z0-9_\-]{8,}", blob)
        live = os.environ.get("ANTHROPIC_API_KEY", "")
        if live:
            assert live not in blob


class TestTheHomeScreenPayload:
    def test_it_carries_recent_playbooks_then_recent_exports(self, client,
                                                             workspace_id):
        body = client.get("/api/v1/playbook/home").json()
        assert "recent_playbooks" in body
        assert "recent_exports" in body
        assert any(w["id"] == workspace_id for w in body["recent_playbooks"])

    def test_the_key_order_matches_the_screen_order(self, client):
        """§3 fixes the order: Recent Playbooks before Recent Exported
        Analyses. The payload is built in that order so a client rendering it
        in key order cannot get it wrong."""
        body = client.get("/api/v1/playbook/home").json()
        keys = list(body)
        assert keys.index("recent_playbooks") < keys.index("recent_exports")


class TestUploads:
    def test_a_word_document_uploads_parses_and_reports_its_manifest(
            self, client, workspace_id, committee_report_docx):
        response = client.post(
            f"/api/v1/playbook/workspaces/{workspace_id}/sources",
            files={"file": ("prior.docx", io.BytesIO(committee_report_docx),
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document")},
            data={"source_role": "previous_report"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] in ("parsed", "partial")
        assert body["role"] == "previous_report"
        assert body["manifest"]["read"]

    def test_a_macro_enabled_file_is_refused_with_a_reason(
            self, client, workspace_id, results_workbook_xlsx):
        response = client.post(
            f"/api/v1/playbook/workspaces/{workspace_id}/sources",
            files={"file": ("results.xlsm", io.BytesIO(results_workbook_xlsx),
                            "application/vnd.ms-excel.sheet.macroEnabled.12")},
        )
        assert response.status_code == 422
        assert "macros" in response.json()["detail"]["message"]

    def test_an_unsupported_type_is_refused(self, client, workspace_id):
        response = client.post(
            f"/api/v1/playbook/workspaces/{workspace_id}/sources",
            files={"file": ("thing.exe", io.BytesIO(b"MZ\x90\x00"),
                            "application/octet-stream")},
        )
        assert response.status_code == 422

    def test_uploading_does_not_start_a_generation(
            self, client, workspace_id, committee_report_docx):
        client.post(
            f"/api/v1/playbook/workspaces/{workspace_id}/sources",
            files={"file": ("prior.docx", io.BytesIO(committee_report_docx),
                            "application/octet-stream")})
        body = client.get(f"/api/v1/playbook/workspaces/{workspace_id}").json()
        assert body["artifacts"] == []
        assert body["messages"] == []


class TestExportToPlaybook:
    def test_a_completed_analysis_exports_and_appears_in_the_library(self, client):
        created = client.post("/api/v1/playbook/exports", json=_export_body())
        assert created.status_code == 201, created.text
        revision_id = created.json()["revision_id"]

        found = client.get("/api/v1/playbook/exports",
                           params={"q": "stage migration"}).json()
        assert found["total"] >= 1
        assert any(c["revision_id"] == revision_id for c in found["analyses"])

    def test_exporting_twice_is_idempotent(self, client):
        first = client.post("/api/v1/playbook/exports",
                            json=_export_body(source_ref={"run_id": 8802}))
        second = client.post("/api/v1/playbook/exports",
                             json=_export_body(source_ref={"run_id": 8802}))
        assert second.json()["duplicate"] is True
        assert second.json()["revision_id"] == first.json()["revision_id"]
        assert "already in your Playbook" in second.json()["message"]

    def test_a_greeting_cannot_be_exported(self, client):
        response = client.post("/api/v1/playbook/exports",
                               json=_export_body(narrative="Hi there.",
                                                 tables=[]))
        assert response.status_code == 422
        assert "not a completed" in response.json()["detail"]["message"]

    def test_the_preview_carries_the_whole_analysis(self, client):
        created = client.post("/api/v1/playbook/exports",
                              json=_export_body(source_ref={"run_id": 8803}))
        payload = client.get(
            f"/api/v1/playbook/exports/revisions/{created.json()['revision_id']}"
        ).json()
        assert "41.00" in payload["narrative"]
        assert payload["tables"][0]["rows"]
        assert payload["question"]
        assert payload["content_hash"]

    def test_an_id_that_was_never_exported_is_not_found(self, client):
        assert client.get(
            "/api/v1/playbook/exports/revisions/99999999").status_code == 404

    def test_project_planner_is_not_an_accepted_source_module(self, client):
        response = client.post(
            "/api/v1/playbook/exports",
            json=_export_body(source_module="project_planner"))
        assert response.status_code == 422
        assert "not a module" in response.json()["detail"]["message"]

    def test_the_library_reports_which_modules_are_implemented(self, client):
        body = client.get("/api/v1/playbook/exports").json()
        assert "what_if" in body["modules"]
        assert "what_if" not in body["implemented_modules"]


class TestWorkspacesAndDownloads:
    def test_a_workspace_reopens_with_everything_on_it(
            self, client, workspace_id, committee_report_docx):
        client.post(f"/api/v1/playbook/workspaces/{workspace_id}/sources",
                    files={"file": ("prior.docx",
                                    io.BytesIO(committee_report_docx),
                                    "application/octet-stream")})
        body = client.get(f"/api/v1/playbook/workspaces/{workspace_id}").json()
        assert body["id"] == workspace_id
        assert len(body["sources"]) == 1

    def test_a_workspace_can_be_renamed(self, client, workspace_id):
        response = client.patch(f"/api/v1/playbook/workspaces/{workspace_id}",
                                json={"title": "Renamed by the user"})
        assert response.json()["title"] == "Renamed by the user"

    def test_a_missing_workspace_is_not_found(self, client):
        assert client.get(
            "/api/v1/playbook/workspaces/99999999").status_code == 404

    def test_a_missing_artifact_file_is_not_found(self, client):
        assert client.get(
            "/api/v1/playbook/artifact-files/99999999/download"
        ).status_code == 404


class TestTheMonitoringPlaybooksFeatureIsUntouched:
    def test_its_routes_still_exist_and_answer(self, client):
        """The standing-instruction Playbook of PRODUCT_SPEC §9 is a different
        feature and this branch must not have disturbed it."""
        response = client.get("/api/v1/playbooks")
        assert response.status_code in (200, 503)

    def test_the_two_features_have_separate_prefixes(self, client):
        from backend.api.main import create_app

        paths = set(create_app().openapi()["paths"])
        assert "/api/v1/playbooks" in paths
        assert "/api/v1/playbook/home" in paths
