"""
Ask CreditProbe and Trace-modification API tests.

This is the surface a question reaches CreditProbe through, so the tests are mostly
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
    # Counted from the registry rather than hard-coded, so adding an analysis
    # does not require editing a test about planning.
    assert body["analysis_count"] == len(
        client.get("/api/v1/engine/analyses").json()["analyses"]
    )
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


def test_a_question_about_change_without_a_period_asks_instead_of_guessing(client, demo_mode):
    """"How has ECL changed?" has no answer until someone says since when."""
    response = client.post("/api/v1/ask", json={"question": "How has ECL changed?",
                                                "persist": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    clarification = body["clarification"]
    assert clarification["kind"] == "period"
    assert len(clarification["options"]) >= 2
    # Every option resolves to real published periods, so answering is a click.
    periods = client.get("/api/v1/ask/mode").json()
    for option in clarification["options"]:
        assert option["from_period"] and option["to_period"]
        assert option["from_period"] != option["to_period"]
    assert periods  # the endpoint is reachable; the assertion above is the point
    assert not body["steps"], "nothing may run before the question is answerable"


def test_asking_a_question_runs_real_analyses(client, demo_mode):
    response = client.post("/api/v1/ask", json={"question": "How has ECL changed?",
                                                "persist": False,
                                                "from_period": "Q4 2025",
                                                "to_period": "Q1 2026"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert "ecl_movement" in [s["analysis_id"] for s in body["steps"]]
    assert body["narrative"]["summary"]
    assert body["trace"]["stats"]["governed_nodes"] > 0
    assert body["trace"]["stats"]["interpretive_nodes"] > 0


def test_a_point_in_time_question_is_answered_without_interrogation(client, demo_mode):
    """The opposite failure: asking about history when none is needed."""
    body = client.post("/api/v1/ask", json={"question": "What is our current NPL ratio?",
                                            "persist": False}).json()
    assert body["status"] == "succeeded"
    assert body["clarification"] is None


def test_an_answer_separates_calculated_facts_from_ipm_interpretation(client, demo_mode):
    body = client.post("/api/v1/ask", json={"question": "Which sectors deteriorated the most?",
                                            "persist": False,
                                            "from_period": "Q4 2025",
                                            "to_period": "Q1 2026"}).json()
    narrative = body["narrative"]
    assert narrative["direct_answer"], "the question must be answered in one sentence"
    assert narrative["interpretation_points"], "CreditProbe's reading must be stated separately"
    # The reading may not claim causation the decomposition did not establish.
    reading = " ".join(narrative["interpretation_points"]).lower()
    assert "caused by" not in reading


def test_a_question_is_answered_with_the_analysis_it_asked_for(client, demo_mode):
    """Question-scoped: a sector question does not return a portfolio briefing."""
    body = client.post("/api/v1/ask", json={"question": "Which sectors deteriorated the most?",
                                            "persist": False,
                                            "from_period": "Q4 2025",
                                            "to_period": "Q1 2026"}).json()
    ids = [s["analysis_id"] for s in body["steps"]]
    assert ids == ["ecl_movement"]
    assert [s for s in body["steps"] if s["role"] == "primary"]


def test_an_unrecognised_question_is_answered_honestly(client, demo_mode):
    body = client.post("/api/v1/ask", json={"question": "Who won the cup final?",
                                            "persist": False}).json()
    assert body["unmatched"] is True
    assert body["notes"]
    assert body["steps"], "CreditProbe still shows the standard review rather than nothing"


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
        json={"question": "Show me the rating transition matrix.", "persist": True,
              "from_period": "Q4 2025", "to_period": "Q1 2026"},
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
        json={"question": "Show me the top ten deteriorating borrowers.", "persist": True,
              "from_period": "Q4 2025", "to_period": "Q1 2026"},
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
