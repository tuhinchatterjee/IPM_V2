"""Per-answer feedback through its real routes. §39-§45.

The journey once: leave a thumbs-down with a correction, watch two
presentation preferences change and nine analytical fields go to review,
follow it through Received → Under Review → Fixed → Released, and confirm at
every step that no validation score moved.
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
        pytest.skip("Answer feedback persists everything; PostgreSQL is "
                    "not reachable")


def answer_id() -> str:
    return f"ans-{uuid.uuid4().hex[:12]}"


# ================================================================ §39 prompt


@pytest.mark.parametrize("kind", [
    "metadata", "analysis", "clarification", "unsupported",
    "controlled_failure", "agentic", "regulatory", "project_planner",
])
def test_every_answer_kind_gets_a_prompt(client, kind):
    body = client.get(f"/api/v1/feedback/prompt?answer_kind={kind}",
                      headers=headers("VIEWER")).json()

    assert body["show"] is True
    assert len(body["down"]["fields"]) == 11
    assert len(body["down"]["anchors"]) == 6
    assert len(body["up"]["reasons"]) == 9


def test_a_viewer_may_leave_feedback(client):
    """A user shown an answer and then refused the ability to say it was
    wrong has been asked for their trust and denied the means to withdraw
    it."""
    left = client.post("/api/v1/feedback/thumbs", headers=headers("VIEWER"),
                       json={"answer_id": answer_id(), "direction": "UP",
                             "reasons": ["clear"]})

    assert left.status_code == 201, left.text


def test_an_unknown_answer_kind_is_refused(client):
    refused = client.get("/api/v1/feedback/prompt?answer_kind=vibes",
                         headers=headers())

    assert refused.status_code == 422


# ============================================== §42 immediate vs governed


@pytest.fixture(scope="module")
def corrected(client) -> dict:
    """One thumbs-down carrying both halves of §42's split."""
    given = client.post("/api/v1/feedback/thumbs", headers=headers(), json={
        "answer_id": answer_id(),
        "direction": "DOWN",
        "answer_kind": "analysis",
        "anchor_kind": "figure",
        "anchor_ref": "total-ecl",
        "correction": {
            "preferred_visualization": "chart",
            "better_structure": "brief",
            "correct_period": "Q2 2026",
            "correct_population": "corporate only",
            "preferred_method": "the vintage method",
        },
    })
    assert given.status_code == 201, given.text
    return given.json()


def test_only_presentation_changes_immediately(client, corrected):
    assert corrected["changed_immediately"] == {"result_form": "chart",
                                                "answer_length": "brief"}
    assert set(corrected["under_review"]) == {
        "correct_period", "correct_population", "preferred_method"}


def test_leaving_feedback_changes_no_validation_score(client, corrected):
    """§44: raw thumbs do not change validation scores."""
    assert corrected["validation_score_changed"] is False


def test_the_user_is_told_what_happens_next(client, corrected):
    assert "review, regression and release" in corrected["what_happens_next"]


def test_an_analytical_field_alone_changes_nothing_immediately(client):
    given = client.post("/api/v1/feedback/thumbs", headers=headers(), json={
        "answer_id": answer_id(), "direction": "DOWN",
        "correction": {"correct_concept": "you meant EAD, not exposure"},
    }).json()

    assert given["changed_immediately"] == {}
    assert given["under_review"] == ["correct_concept"]


def test_a_field_nobody_named_is_refused_through_the_route(client):
    refused = client.post("/api/v1/feedback/thumbs", headers=headers(),
                          json={"answer_id": answer_id(),
                                "direction": "DOWN",
                                "correction": {"just_fix_it": "please"}})

    assert refused.status_code == 422
    assert "eleven fields" in refused.json()["detail"]["message"]


# ================================================================ §45 status


def test_feedback_starts_received_and_says_what_is_next(client, corrected):
    body = client.get(f"/api/v1/feedback/thumbs/{corrected['feedback_id']}",
                      headers=headers()).json()

    assert body["status"] == "RECEIVED"
    assert body["next_steps"] == ["UNDER_REVIEW", "REVIEWED_NOT_CHANGING"]
    assert len(body["governed_path"]) == 10
    assert body["raw_feedback_changed_no_score"] is True


def test_the_full_journey_to_released(client):
    given = client.post("/api/v1/feedback/thumbs", headers=headers(), json={
        "answer_id": answer_id(), "direction": "DOWN",
        "correction": {"correct_period": "Q2 2026"}}).json()
    feedback_id = given["feedback_id"]

    for step, extra in (
        ("UNDER_REVIEW", {}),
        ("FIXED", {"linked_kind": "teaching_case",
                   "linked_id": "tc-1",
                   "score_impact": {"raw_thumbs_changed_nothing": True}}),
        ("RELEASED", {"release_id": "rel-9"}),
    ):
        moved = client.post(
            f"/api/v1/feedback/thumbs/{feedback_id}/advance",
            headers=headers(), json={"to": step, **extra})
        assert moved.status_code == 200, moved.text
        assert moved.json()["status"] == step

    body = client.get(f"/api/v1/feedback/thumbs/{feedback_id}",
                      headers=headers()).json()
    assert body["status"] == "RELEASED"
    assert len(body["history"]) == 4
    assert all(step["by"] for step in body["history"][1:])


def test_a_skipped_step_is_refused_through_the_route(client):
    given = client.post("/api/v1/feedback/thumbs", headers=headers(), json={
        "answer_id": answer_id(), "direction": "DOWN",
        "correction": {"correct_period": "Q2"}}).json()

    refused = client.post(
        f"/api/v1/feedback/thumbs/{given['feedback_id']}/advance",
        headers=headers(), json={"to": "RELEASED"})

    assert refused.status_code == 422
    assert "review and regression" in refused.json()["detail"]["message"]


def test_declining_a_correction_without_a_reason_is_refused(client):
    given = client.post("/api/v1/feedback/thumbs", headers=headers(), json={
        "answer_id": answer_id(), "direction": "DOWN",
        "correction": {"correct_period": "Q2"}}).json()

    refused = client.post(
        f"/api/v1/feedback/thumbs/{given['feedback_id']}/advance",
        headers=headers(), json={"to": "REVIEWED_NOT_CHANGING"})

    assert refused.status_code == 422
    assert "achieves nothing" in refused.json()["detail"]["message"]


def test_a_declined_correction_records_who_declined_it_and_why(client):
    given = client.post("/api/v1/feedback/thumbs", headers=headers(), json={
        "answer_id": answer_id(), "direction": "DOWN",
        "correction": {"correct_population": "retail only"}}).json()

    client.post(f"/api/v1/feedback/thumbs/{given['feedback_id']}/advance",
                headers=headers(),
                json={"to": "REVIEWED_NOT_CHANGING",
                      "reason": "the question named the corporate book"})

    body = client.get(f"/api/v1/feedback/thumbs/{given['feedback_id']}",
                      headers=headers()).json()
    assert body["status"] == "REVIEWED_NOT_CHANGING"
    assert body["history"][-1]["reason"]
    assert body["history"][-1]["by"]


# ================================================================ the queue


def test_unopened_feedback_is_counted_separately(client, corrected):
    """A queue that added received to under-review would look healthy while
    nobody had opened anything."""
    body = client.get("/api/v1/feedback/queue", headers=headers()).json()

    assert "RECEIVED" in body["by_status"]
    assert "UNDER_REVIEW" in body["by_status"]
    assert body["unopened"] == body["by_status"]["RECEIVED"]
    assert "nobody looked" in body["note"]


def test_the_queue_is_not_open_to_an_analyst(client):
    assert client.get("/api/v1/feedback/queue",
                      headers=headers("ANALYST")).status_code == 403


def test_satisfaction_says_it_is_not_accuracy(client, corrected):
    body = client.get("/api/v1/feedback/satisfaction",
                      headers=headers()).json()

    assert body["total"] >= 1
    assert "liked and wrong" in body["not_an_accuracy_measure"]
    assert "no thumb moves it" in body["not_an_accuracy_measure"]


# =============================================== §43 the ledger connection


def test_an_analytical_correction_becomes_a_ledger_entry_that_activates_nothing(
        client):
    """§43. Approved feedback-derived learning enters the Learning Ledger —
    at CAPTURED, which is where §42's governed path starts."""
    before = client.get("/api/v1/brain/ledger", headers=headers()).json()

    client.post("/api/v1/feedback/thumbs", headers=headers(), json={
        "answer_id": answer_id(), "direction": "DOWN",
        "correction": {"preferred_method": "use the roll-rate method"}})

    after = client.get("/api/v1/brain/ledger", headers=headers()).json()

    assert after["census"]["captured"] == before["census"]["captured"] + 1
    assert (after["census"]["by_review_status"]["CAPTURED"]
            == before["census"]["by_review_status"]["CAPTURED"] + 1)
    # It landed at CAPTURED and NON_PORTABLE, which is where §42's governed
    # path starts. Nothing was approved and nothing was activated by it.
    assert after["census"]["approved"] == before["census"]["approved"]
    assert after["census"]["activated"] == before["census"]["activated"]
    assert (after["census"]["by_portability"]["NON_PORTABLE"]
            == before["census"]["by_portability"]["NON_PORTABLE"] + 1)
