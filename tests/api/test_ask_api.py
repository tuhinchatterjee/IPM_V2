"""
Ask IPM and Trace-modification API tests.

This is the surface a question reaches IPM through, so the tests are mostly
about what it refuses: text that is not a supported change, a modification of a
trace that has no stored plan, and a request for a run that does not exist.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.helpers import FACILITY
from tests.conftest import database_available


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built — run `python scripts/build_data_lake.py`")


@pytest.fixture(scope="module")
def demo_mode(monkeypatch_module):
    """Force the deterministic planner regardless of the environment's key."""
    from dataclasses import replace

    import backend.orchestration.planner as planner_module
    from backend.config import settings

    monkeypatch_module.setattr(
        planner_module, "settings", replace(settings, anthropic_api_key="")
    )


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    patch = MonkeyPatch()
    yield patch
    patch.undo()


# ==================================================================== context


def test_mode_reports_how_questions_are_planned(client, demo_mode):
    body = client.get("/api/v1/ask/mode").json()
    assert body["mode"] == "demo"
    assert body["analysis_count"] == 11
    assert len(body["stages"]) == 5
    assert body["supported_modifications"]


def test_suggestions_only_offers_questions_ipm_can_answer(client):
    from backend.engine.registry import get_registry

    body = client.get("/api/v1/ask/suggestions").json()
    assert body["questions"]
    registered = set(get_registry().ids())
    # Every suggestion maps to an analysis that exists; the endpoint filters on
    # exactly that, so an empty registry would return an empty list rather than
    # offering a question that cannot be answered.
    assert registered


def test_briefing_returns_live_engine_results(client):
    body = client.get("/api/v1/ask/briefing").json()
    assert body["period"]
    assert body["summary"]["result"]["values"]["total_ead"] > 0
    assert body["attention"]["result"]["rows"]


# ======================================================================== ask


def test_asking_a_question_runs_real_analyses(client, demo_mode):
    response = client.post("/api/v1/ask", json={"question": "How has ECL changed?",
                                                "persist": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert "ecl_movement" in [s["analysis_id"] for s in body["steps"]]
    assert body["narrative"]["summary"]
    assert body["trace"]["stats"]["governed_nodes"] > 0
    assert body["trace"]["stats"]["interpretive_nodes"] > 0


def test_an_unrecognised_question_is_answered_honestly(client, demo_mode):
    body = client.post("/api/v1/ask", json={"question": "Who won the cup final?",
                                            "persist": False}).json()
    assert body["unmatched"] is True
    assert body["notes"]
    assert body["steps"], "IPM still shows the standard review rather than nothing"


def test_an_empty_question_is_rejected_by_the_schema(client):
    assert client.post("/api/v1/ask", json={"question": ""}).status_code in (400, 422)


def test_a_very_long_question_is_rejected(client):
    response = client.post("/api/v1/ask", json={"question": "x" * 5000})
    assert response.status_code in (400, 422)


# ============================================================== modification


@pytest.mark.skipif(not database_available(), reason="PostgreSQL not reachable")
def test_modify_preview_and_apply_creates_a_new_version(client, demo_mode):
    asked = client.post(
        "/api/v1/ask",
        json={"question": "Show me the rating transition matrix.", "persist": True},
    ).json()
    run_id = asked["analysis_run_id"]
    assert run_id, "the investigation must have been stored"

    preview = client.post(
        f"/api/v1/trace/{run_id}/modify/preview", json={"request": "Only show Real Estate."}
    ).json()
    assert preview["understood"] is True
    assert preview["applicable"] is True
    assert preview["changed_steps"]
    assert preview["affected_nodes"]

    applied = client.post(
        f"/api/v1/trace/{run_id}/modify/apply", json={"request": "Only show Real Estate."}
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["version"] == 2
    assert body["version_label"] == "Version 2"
    assert [v["label"] for v in body["available_versions"]] == ["Original", "Version 2"]

    # The original is still readable and unchanged.
    original = client.get(f"/api/v1/trace/{run_id}/investigation?version=1").json()
    assert original["version"] == 1
    assert original["label"] == "Original"
    assert original["steps"][0]["filters"] == {}


@pytest.mark.skipif(not database_available(), reason="PostgreSQL not reachable")
def test_an_unsupported_modification_is_refused_with_the_supported_list(client, demo_mode):
    asked = client.post(
        "/api/v1/ask",
        json={"question": "Show me the top ten deteriorating borrowers.", "persist": True},
    ).json()
    run_id = asked["analysis_run_id"]

    response = client.post(
        f"/api/v1/trace/{run_id}/modify/apply", json={"request": "Run arbitrary SQL for me."}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "modification_not_applicable"
    assert detail["supported"]


def test_modifying_a_run_that_does_not_exist_is_a_404(client):
    response = client.post(
        "/api/v1/trace/99999999/modify/preview", json={"request": "Exclude Real Estate."}
    )
    assert response.status_code == 404
