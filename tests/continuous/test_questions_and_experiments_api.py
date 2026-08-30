"""
§84's learning questions and §68's isolation experiments, over HTTP.

What these prove that the unit tests cannot: the governance rules survive
the trip through the router. A refusal that becomes a 200 with a plausible
body on the way out is the failure that matters here, because the screen
would render it as an answer.
"""

from __future__ import annotations

import pytest

from backend.continuous import isolation as iso
from backend.continuous import measurement, questions
from tests.conftest import database_available


def headers(role: str = "ADMIN") -> dict[str, str]:
    return {"X-IPM-Role": role}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("these routes read persisted snapshots; PostgreSQL is "
                    "not reachable")


def _arm(label: str, value: float, *, changes=(), n=60) -> dict:
    return {
        "label": label,
        "changes": list(changes),
        "scores": {f"case_{i:03d}": value for i in range(n)},
        "families": {f"case_{i:03d}": ("ECL" if i % 2 else "Migration")
                     for i in range(n)},
        "dimensions": {"Analytical Design": value},
        "critical_failures": [],
    }


# ============================================================ §84 questions


def test_the_catalogue_lists_all_nine_and_says_no_model_is_involved(client):
    body = client.get("/api/v1/continuous-learning/questions",
                      headers=headers()).json()
    assert len(body["questions"]) == questions.EXPECTED_QUESTIONS == 9
    assert body["answered_from"] == "persisted snapshots and evaluations"
    assert "do not let an LLM invent" in body["no_model_involved"]


def test_an_unrecognised_question_is_refused_through_the_route(client):
    """The failure that matters: a refusal rendered as an answer."""
    response = client.post("/api/v1/continuous-learning/questions",
                           json={"question": "what is the capital of France?"},
                           headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["answerable"] is False
    assert body["numbers"] == []
    assert "not one of the questions" in body["headline"]
    assert len(body["catalogue"]) == 9


@pytest.mark.parametrize("shape", questions.SHAPES,
                         ids=[s.question_id for s in questions.SHAPES])
def test_every_governed_question_answers_without_inventing_a_number(
        client, shape):
    """A fresh installation answers all nine — most of them with a refusal.

    That is the point. "Never measured" is an answer; a zero is not.
    """
    response = client.post("/api/v1/continuous-learning/questions",
                           json={"question": shape.canonical},
                           headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["headline"]
    assert "no model produced any number" in body["not_generated"]
    for number in body["numbers"]:
        assert number["source"], number
    if not body["answerable"]:
        assert body["missing"], shape.question_id


def test_the_questions_sit_behind_the_same_gate_as_the_rest_of_the_area(
        client):
    """An ANALYST may read learning; a VIEWER may not.

    The new routes inherit the area's existing gate rather than defining a
    looser one of their own — a screen that answered "how much did we
    improve" to an audience the cockpit beside it refuses would be a
    governance hole shaped like a convenience.
    """
    assert client.get("/api/v1/continuous-learning/questions",
                      headers=headers("ANALYST")).status_code == 200
    assert client.get("/api/v1/continuous-learning/questions",
                      headers=headers("VIEWER")).status_code == 403
    # Reading is not measuring: an ANALYST may not run an experiment.
    assert client.post(
        "/api/v1/continuous-learning/experiments",
        json={"change_kind": "TEACHING_CASE_BATCH", "change_id": "b1",
              "baseline": _arm("baseline", 0.80),
              "treatment": _arm("treatment", 0.86, changes=["b1"])},
        headers=headers("ANALYST")).status_code == 403


# ========================================================= §68 experiments


def test_the_experiment_kinds_name_what_each_can_attribute(client):
    body = client.get("/api/v1/continuous-learning/experiments",
                      headers=headers()).json()
    kinds = {k["id"]: k["attributes_to"] for k in body["change_kinds"]}
    assert set(kinds) == set(iso.CHANGE_KINDS)
    assert set(kinds.values()) <= set(measurement.SOURCES)
    assert body["default_mode"] == iso.DETERMINISTIC
    assert "doubles the call count" in body["live_provider_rule"]


def test_a_clean_experiment_runs_deterministically_and_is_isolated(client):
    response = client.post(
        "/api/v1/continuous-learning/experiments",
        json={"change_kind": "TEACHING_CASE_BATCH", "change_id": "batch-17",
              "baseline": _arm("baseline", 0.80),
              "treatment": _arm("treatment", 0.86, changes=["batch-17"])},
        headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["isolated"] is True
    assert body["mode"] == iso.DETERMINISTIC
    assert body["contribution"]["isolated"] is True
    assert body["contribution"]["source"] == "Teaching Cases"
    assert body["overall"]["points"] == pytest.approx(6.0, abs=0.01)


def test_a_live_provider_experiment_is_refused_without_authorization(client):
    """§68, through the route. This one costs money if it gets through."""
    response = client.post(
        "/api/v1/continuous-learning/experiments",
        json={"change_kind": "ROUTING_CHANGE", "change_id": "r4",
              "mode": iso.LIVE_PROVIDER,
              "baseline": _arm("baseline", 0.80),
              "treatment": _arm("treatment", 0.86, changes=["r4"])},
        headers=headers())
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "without authorization" in detail["message"]


def test_an_experiment_against_the_sealed_holdout_is_refused(client):
    response = client.post(
        "/api/v1/continuous-learning/experiments",
        json={"change_kind": "TEACHING_CASE_BATCH", "change_id": "b1",
              "partition": "SEALED_HOLDOUT",
              "baseline": _arm("baseline", 0.80),
              "treatment": _arm("treatment", 0.86, changes=["b1"])},
        headers=headers())
    assert response.status_code == 422
    assert "holdout" in response.json()["detail"]["message"]


def test_a_joint_change_comes_back_measured_but_not_isolated(client):
    response = client.post(
        "/api/v1/continuous-learning/experiments",
        json={"change_kind": "TEACHING_CASE_BATCH", "change_id": "batch-17",
              "baseline": _arm("baseline", 0.80),
              "treatment": _arm("treatment", 0.86,
                                changes=["batch-17", "routing-v4"])},
        headers=headers())
    body = response.json()
    assert body["isolated"] is False
    assert body["contribution"]["isolated"] is False
    assert body["overall"]["points"] == pytest.approx(6.0, abs=0.01)
    assert "not an isolated one" in body["why_not_isolated"]


def test_running_an_experiment_needs_more_than_view_permission(client):
    response = client.post(
        "/api/v1/continuous-learning/experiments",
        json={"change_kind": "TEACHING_CASE_BATCH", "change_id": "b1",
              "baseline": _arm("baseline", 0.80),
              "treatment": _arm("treatment", 0.86, changes=["b1"])},
        headers=headers("VIEWER"))
    assert response.status_code == 403
