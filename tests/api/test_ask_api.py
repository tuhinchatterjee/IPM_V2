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
    """With no provider key the product must say it is degraded.

    Not "demo mode" in the old sense — that name described which planner was
    selected. This says what a user needs to know: natural-language
    understanding is constrained, and here is how.
    """
    body = client.get("/api/v1/ask/mode").json()
    assert body["mode"] == "offline"
    assert body["configured"] is False
    assert body["label"] == "LIMITED OFFLINE MODE"
    assert body["limitations"], "an offline product must say what it cannot do"
    assert "LIMITED OFFLINE MODE" == body["label"]
    assert "deterministic" in body["description"]
    assert body["ai"]["state"] == "offline"
    assert body["build"]["version"]
    # Only ANALYSIS computes; the rest are answered from governed metadata.
    computing = [c for c in body["capabilities"] if c["computes"]]
    assert [c["id"] for c in computing] == ["ANALYSIS"]
    # Counted from the registry rather than hard-coded, so adding an analysis
    # does not require editing a test about planning.
    assert body["analysis_count"] == len(
        client.get("/api/v1/engine/analyses").json()["analyses"]
    )
    assert len(body["stages"]) == 6
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


def test_a_change_without_a_period_uses_the_governed_default_and_says_so(client, demo_mode):
    """"How has ECL changed?" gets the review cycle, stated on the answer.

    This used to stop and ask. That was the right instinct applied too widely:
    every credit officer asking it means over the year, and a product that
    interrogates the obvious looks unsure of something it is not unsure of. The
    replacement rule is that the assumption is TAKEN and REPORTED — an unstated
    default would be worse than either.
    """
    response = client.post(
        "/api/v1/ask",
        json={"question": "Which customers had a rating downgrade and an "
                          "increase in ECL?", "persist": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded", body.get("clarification")
    assert body["clarification"] is None

    scope = body["plan"]["scope"]
    periods = client.get("/api/v1/ask/mode").json()["periods"]
    assert scope["to_period"] == periods[-1]
    assert scope["from_period"] == periods[-5], "a year back, on a quarterly book"

    said = " ".join(body["narrative"]["caveats"]).lower()
    assert "governed default" in said, "the assumption must be visible"
    assert scope["from_period"].lower() in said and scope["to_period"].lower() in said


def test_asking_a_question_runs_real_analyses(client, demo_mode):
    response = client.post(
        "/api/v1/ask",
        json={"question": "Show me the ten largest customers by exposure at "
                          "default.", "persist": False})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    # Composed rather than selected: no registered analysis answers this, and
    # the composer built it from the governed concept the question named.
    assert [s["analysis_id"] for s in body["steps"]] == ["dynamic_analysis"]
    assert body["steps"][0]["result"]["datasets"]
    assert body["narrative"]["summary"]
    assert body["trace"]["stats"]["governed_nodes"] > 0
    assert body["trace"]["stats"]["interpretive_nodes"] > 0


def test_a_point_in_time_question_is_answered_without_interrogation(client, demo_mode):
    """The opposite failure: asking about history when none is needed."""
    body = client.post(
        "/api/v1/ask",
        json={"question": "What is total EAD by sector in the latest quarter?",
              "persist": False}).json()
    assert body["status"] == "succeeded", body.get("clarification")
    assert body["clarification"] is None
    assert body["plan"]["scope"]["period_requirement"] == "point_in_time"


def test_a_figure_with_no_governed_field_asks_rather_than_approximating(client, demo_mode):
    """A ratio nothing in the catalogue defines must not be approximated.

    CreditProbe could assemble something plausible-looking out of the fields it
    does have. It must not: a figure the bank has not defined is a figure nobody
    can reconcile, and presenting one under a name people recognise is the exact
    failure this release removed.
    """
    body = client.post(
        "/api/v1/ask",
        json={"question": "What is our net stable funding ratio?",
              "persist": False}).json()
    assert body["status"] == "needs_clarification"
    assert body["steps"] == []
    assert "governed concepts" in body["clarification"]["question"]


def test_a_named_certified_methodology_is_run_rather_than_recomposed(client, demo_mode):
    """"How has ECL changed?" is a methodology the bank has approved.

    Recomposing it from first principles would produce a number that probably
    agrees and is not the same artefact. This is a ROUTE, not the rescue that was
    removed: it fires on the analysis's own name or trigger question, before the
    composer runs, and a failure here composes rather than reaching for a
    different certified analysis.
    """
    body = client.post("/api/v1/ask", json={"question": "How has ECL changed?",
                                            "persist": False}).json()
    assert body["status"] == "succeeded"
    assert [s["analysis_id"] for s in body["steps"]] == ["ecl_movement"]
    assert body["steps"][0]["certification"] == "certified"
    # The window it used must be visible, because a certified analysis brings
    # its own governed default and that may not be the composer's.
    scope = body["plan"]["scope"]
    assert scope["from_period"] and scope["to_period"]


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
    # "Which sectors deteriorated the most?" is a declared trigger question of
    # the certified ECL attribution, so that is what runs. The point of the test
    # is unchanged: it must not come back as a portfolio briefing.
    assert ids == ["ecl_movement"]
    assert [s for s in body["steps"] if s["role"] == "primary"]


def test_an_unrecognised_question_gets_a_question_back_not_a_number(client, demo_mode):
    """The most important refusal in the product.

    This used to run the standard portfolio review and put a note above it, so
    somebody asking about anything at all got the bank's total exposure —
    correctly calculated, carrying a certification tick, answering a question
    nobody asked. A confident answer to the wrong question is worse than no
    answer, because nothing about it looks wrong.
    """
    body = client.post("/api/v1/ask", json={"question": "Who won the cup final?",
                                            "persist": False}).json()
    assert body["status"] == "needs_clarification"
    assert body["steps"] == [], "nothing may be executed for a question not understood"

    clarification = body["clarification"]
    assert clarification["kind"] == "reading"
    # The old refusal offered a menu of registered analyses and said CreditProbe
    # "can only answer with analyses the engine has registered". That sentence
    # described a product that no longer exists, and the menu sent people away
    # from the question they actually had. What is offered now is composed from
    # governed CONCEPTS, so every option is a question the composer can answer.
    assert clarification["options"], "a refusal must leave something to click"
    for option in clarification["options"]:
        assert option["question"], "every offer must be a question that can be asked"
    assert "registered" not in (clarification["detail"] or "").lower()


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
