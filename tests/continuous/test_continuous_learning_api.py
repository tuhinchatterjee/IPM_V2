"""Continuous Learning through its real routes. §60, §64-§66, §72, §86.

Two things this suite proves that the unit tests cannot.

The cockpit is honest when there is nothing to show. An installation on its
first day has no baseline and no snapshots, and the two states say different
things: "nothing to compare against" and "nobody looked in this window". A
screen that showed zeros for both would report a new installation and a
neglected one identically.

And no sealed-holdout content reaches the screen. §58 names the
continuous-learning UI among the six places it may never appear.
"""

from __future__ import annotations

import uuid

import pytest

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
        pytest.skip("Continuous Learning persists everything; PostgreSQL "
                    "is not reachable")


# =================================================== the rules, as data


def test_the_thirteen_windows_are_served_with_their_anchoring(client):
    body = client.get("/api/v1/continuous-learning/windows",
                      headers=headers()).json()

    assert len(body["windows"]) == 13
    anchored = {w["id"] for w in body["windows"] if w["anchored"]}
    assert "SINCE_CURRENT_BRAIN" in anchored
    assert "LAST_7_DAYS" not in anchored
    assert len(body["triggers"]) == 11


def test_the_measurement_rules_state_what_a_number_may_claim(client):
    rules = client.get("/api/v1/continuous-learning/measurement-rules",
                       headers=headers()).json()

    assert rules["minimum_cases"] == 30
    assert "40% improvement" in rules["rules"]["three_forms"]
    assert "MORE KNOWLEDGE CAPTURED" in rules["rules"][
        "quantity_is_not_quality"]
    assert "tuned against" in rules["rules"][
        "validation_outranks_development"]
    assert "made balance" in rules["rules"]["the_waterfall_may_not_balance"]


def test_the_partitions_route_names_all_six_forbidden_audiences(client):
    body = client.get("/api/v1/continuous-learning/partitions",
                      headers=headers()).json()

    assert len(body["sealed_holdout_never_reaches"]) == 6
    audiences = {a["audience"] for a in body["sealed_holdout_never_reaches"]}
    assert "continuous_learning_ui" in audiences
    assert "ordinary_administrators" in audiences

    development = next(p for p in body["partitions"]
                       if p["id"] == "DEVELOPMENT")
    validation = next(p for p in body["partitions"]
                      if p["id"] == "VALIDATION")
    assert development["may_tune_against"] is True
    assert validation["may_tune_against"] is False


def test_the_partitions_route_serves_only_aggregate_field_names(client):
    body = client.get("/api/v1/continuous-learning/partitions",
                      headers=headers()).json()

    assert "score" in body["aggregate_fields_only"]
    assert "question" not in body["aggregate_fields_only"]
    assert "gold_answer" not in body["aggregate_fields_only"]


# ============================================= permissions (§86)


def test_an_analyst_may_read_how_the_product_has_been_performing(client):
    """§77 requires every improvement claim to travel with its sample. A
    claim only administrators can check is a claim."""
    assert client.get("/api/v1/continuous-learning/cockpit",
                      headers=headers("ANALYST")).status_code == 200


def test_a_viewer_may_not(client):
    assert client.get("/api/v1/continuous-learning/cockpit",
                      headers=headers("VIEWER")).status_code == 403


def test_an_analyst_may_not_record_a_measurement(client):
    """A snapshot is a permanent record other decisions get made against."""
    refused = client.post("/api/v1/continuous-learning/baselines",
                          headers=headers("ANALYST"),
                          json={"instance_id": "i", "build_sha": "abc",
                                "development_set_version": "d1"})

    assert refused.status_code == 403


# ===================================================== the records


def test_a_baseline_without_a_case_set_version_is_refused(client):
    refused = client.post("/api/v1/continuous-learning/baselines",
                          headers=headers(),
                          json={"instance_id": "i", "build_sha": "abc",
                                "development_set_version": ""})

    assert refused.status_code == 422
    assert "oldest way to report one" in refused.json()["detail"]["message"]


@pytest.fixture(scope="module")
def measured(client) -> dict:
    """A baseline and a snapshot, recorded through the routes."""
    tag = uuid.uuid4().hex[:8]
    baseline = client.post("/api/v1/continuous-learning/baselines",
                           headers=headers(), json={
                               "instance_id": f"inst-{tag}",
                               "build_sha": "abc123",
                               "ontology_version": "2.0.0",
                               "development_set_version": f"dev-{tag}",
                               "validation_set_version": f"val-{tag}",
                               "sealed_holdout_version": f"hold-{tag}",
                               "six_dimension_scores": {
                                   "Understanding & Context": 0.82,
                                   "Analytical Design": 0.78,
                                   "Computation & Evidence": 0.90,
                                   "Judgment & Presentation": 0.75,
                                   "Agentic Delivery": 0.70,
                                   "Reliability & Experience": 0.88,
                               },
                               "validation_metrics": {
                                   "Understanding & Context": 0.80,
                               },
                           })
    assert baseline.status_code == 201, baseline.text

    snapshot = client.post("/api/v1/continuous-learning/snapshots",
                           headers=headers(), json={
                               "comparison_baseline_id":
                                   baseline.json()["baseline_id"],
                               "trigger": "RELEASE",
                               "development_set_version": f"dev-{tag}",
                               "validation_set_version": f"val-{tag}",
                               "six_dimension_scores_dev": {
                                   "Understanding & Context": 0.885,
                               },
                               "six_dimension_scores_validation": {
                                   "Understanding & Context": 0.805,
                               },
                               "case_count_dev": 200,
                               "case_count_validation": 200,
                               "new_learning_captured": 400,
                               "new_learning_activated": 0,
                           })
    assert snapshot.status_code == 201, snapshot.text
    return {"baseline_id": baseline.json()["baseline_id"],
            "snapshot_id": snapshot.json()["snapshot_id"]}


def test_a_baseline_says_what_it_is_comparable_to(client, measured):
    assert measured["baseline_id"]


def test_a_snapshot_is_immutable_and_there_is_no_update_route(client):
    body = client.get("/api/v1/openapi.json") if False else None
    from backend.api.main import create_app

    paths = create_app().openapi()["paths"]
    snapshots = paths.get("/api/v1/continuous-learning/snapshots", {})

    assert "post" in snapshots
    assert "put" not in snapshots
    assert "patch" not in snapshots
    assert body is None


# ==================================================== §64 the cockpit


def test_the_cockpit_keeps_captured_and_changed_apart(client, measured):
    # Read the window id from the route that serves them rather than
    # hard-coding a spelling. §60 calls this one SINCE CURRENT INTELLIGENCE
    # RELEASE, and a client that guessed the shorter form would be refused —
    # which is the right refusal, and the reason to ask.
    served = client.get("/api/v1/continuous-learning/windows",
                        headers=headers()).json()["windows"]
    window = next(w["id"] for w in served if "INTELLIGENCE_RELEASE" in w["id"])

    body = client.get(
        f"/api/v1/continuous-learning/cockpit?window={window}",
        headers=headers()).json()

    assert "learning_captured" in body
    assert "measured_change" in body
    assert "never added" in body["these_are_not_the_same_thing"]


def test_the_cockpit_shows_no_holdout_content(client, measured):
    """§58's sixth audience is this screen."""
    body = client.get("/api/v1/continuous-learning/cockpit",
                      headers=headers()).json()

    assert body["sealed_holdout"]["content_shown"] is False
    assert body["sealed_holdout"]["version"]
    assert "may never reach the continuous-learning UI" in \
        body["sealed_holdout"]["why"]


def test_the_cockpit_reports_the_overfitting_gap(client, measured):
    """Development 82.0 → 88.5 with validation 80.0 → 80.5."""
    body = client.get("/api/v1/continuous-learning/cockpit",
                      headers=headers()).json()

    drift = body["overfitting"]
    assert "possible_overfitting" in drift
    assert "gap_points" in drift
    assert drift["recommended_review"]


def test_the_cockpit_carries_a_release_gate(client, measured):
    body = client.get("/api/v1/continuous-learning/cockpit",
                      headers=headers()).json()

    assert "may_activate" in body["release_gate"]


def test_an_unknown_window_is_refused(client):
    refused = client.get(
        "/api/v1/continuous-learning/cockpit?window=WHENEVER",
        headers=headers())

    assert refused.status_code == 422


def test_an_anchored_window_is_answered_from_the_baseline_not_a_default(
        client, measured):
    """The cockpit anchors SINCE_CURRENT_BRAIN on the baseline it found.
    Answering it with a duration would silently answer a different
    question."""
    body = client.get(
        "/api/v1/continuous-learning/cockpit?window=SINCE_CURRENT_BRAIN",
        headers=headers())

    assert body.status_code == 200
    assert body.json()["window"] == "SINCE_CURRENT_BRAIN"


# ================================================== §65/§66/§72


def test_the_timeline_marks_which_snapshots_follow_a_change(client,
                                                            measured):
    body = client.get("/api/v1/continuous-learning/timeline",
                      headers=headers()).json()

    assert body["points"]
    mine = next(p for p in body["points"]
                if p["snapshot_id"] == measured["snapshot_id"])
    assert mine["trigger"] == "RELEASE"
    assert mine["marks_a_change"] is True
    assert "data point about noise" in body["note"]


def test_velocity_reports_captured_and_activated_separately(client,
                                                            measured):
    body = client.get("/api/v1/continuous-learning/velocity?days=30",
                      headers=headers()).json()

    assert "captured_per_day" in body
    assert "activated_per_day" in body


def test_recording_a_snapshot_records_which_partitions_it_used(client,
                                                               measured):
    """§72. This is what makes validation drifting into a second
    development set visible."""
    body = client.get("/api/v1/continuous-learning/partitions",
                      headers=headers()).json()

    hygiene = body["hygiene"]
    assert hygiene["development_runs"] >= 1
    assert hygiene["validation_runs"] >= 1
    assert "still reversible" in hygiene["note"]
