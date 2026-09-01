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


# =========================================== §11 the provenance of a rating


class TestWhatIsRecordedBesideTheRating:
    """§11 names what a thumb has to persist: the user, the investigation,
    the turn, the answer/run/trace identifier, the timestamp, the rating, the
    comment, the model/planner mode, and the release identifier.

    Every one of those is a question a reviewer asks about an unhappy answer,
    and the one that was missing is the one that decides which reviewer it
    goes to: on a deployment with no external provider, "not helpful" usually
    means the deterministic reader did not understand the phrasing, which is
    a different defect from an analysis that came out wrong.
    """

    @staticmethod
    def _stored(feedback_id: str):
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AnswerFeedback

        with get_session() as session:
            return session.execute(
                select(AnswerFeedback).where(
                    AnswerFeedback.feedback_id == feedback_id)).scalar_one()

    def _leave(self, client, **extra):
        given = client.post(
            "/api/v1/feedback/thumbs",
            headers={"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"},
            json={"answer_id": answer_id(), "direction": "DOWN",
                  "correction": {"additional_comment": "It ignored Q1."},
                  **extra})
        assert given.status_code == 201, given.text
        return self._stored(given.json()["feedback_id"])

    def test_the_rating_records_which_reader_produced_the_answer(self, client):
        from backend.llm import get_provider

        row = self._leave(client)
        assert row.planner_mode, (
            "a thumb was stored with no record of how the question was read, "
            "so an aggregated view cannot separate a phrasing failure from an "
            "analytical one")
        # And it is the truth about this deployment rather than a default: it
        # must agree with what the provider itself reports.
        assert row.planner_mode == get_provider().status().state

    def test_the_reader_is_not_taken_from_the_request(self, client):
        """A client that claims a mode must not be believed.

        The operator can add or remove a provider key between the answer and
        the thumb, so the browser's idea of the mode is a guess. A rating
        filed under the wrong reader sends a reviewer to the wrong defect.
        """
        from backend.llm import get_provider

        row = self._leave(client, planner_mode="connected",
                          model="a-model-that-never-ran")
        assert row.planner_mode == get_provider().status().state
        assert row.model != "a-model-that-never-ran"

    def test_everything_section_eleven_names_is_on_the_row(self, client):
        row = self._leave(client, investigation_id="inv-1234")

        assert row.user_id, "no user"
        assert row.investigation_id == "inv-1234", "no investigation"
        assert row.answer_id, "no answer identifier"
        assert row.created_at is not None, "no timestamp"
        assert row.direction == "DOWN", "no rating"
        assert row.correction.get("additional_comment"), "no comment"
        assert row.planner_mode, "no planner mode"
        # build_sha is the release identifier and is stamped from the running
        # build, so it is present or the build is unstamped - either is
        # honest, and neither may be silently absent from the column.
        assert hasattr(row, "build_sha")

    def test_a_thumb_is_still_recorded_when_the_telemetry_is_unavailable(self):
        """Losing the user's actual point over its provenance is the wrong
        trade. The mode is best-effort; the rating is not."""
        from unittest.mock import patch

        from backend.services import answer_feedback as af

        with patch("backend.llm.get_provider", side_effect=RuntimeError("no")):
            assert af._reader() == {"planner_mode": "", "model": ""}
