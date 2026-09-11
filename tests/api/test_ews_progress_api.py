"""
The progress endpoints, as a client actually uses them.

What is proved here that the unit tests cannot
----------------------------------------------
That a turn can be WATCHED WHILE IT RUNS. The unit tests replay a finished
turn's events, which proves the mapping; this starts a real request on one
thread and polls it from another, which proves the thing the reader cares
about — that the panel fills in during the fifteen to sixty seconds rather
than arriving complete at the end with everything already ticked.

It also proves the boring half. An unknown key is an ordinary answer rather
than a 404. Another caller cannot read somebody else's turn. A client that
sends no key still gets its answer. And the published vocabulary — every
sentence the panel can say — carries no model, provider or budget word.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app

BASE = "/api/v1/early-warning/v2"
LIVE_QUESTION = ("Why has Contracting deteriorated over six months, and is it "
                 "concentrated in a handful of names?")


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    from backend.early_warning import v2_service as svc

    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


def _ask(client: TestClient, question: str, key: str | None) -> dict:
    body = {"question": question}
    if key:
        body["turn_key"] = key
    reply = client.post(f"{BASE}/ask", json=body)
    assert reply.status_code == 200, reply.text
    return reply.json()


# --------------------------------------------------------- watching it happen


def test_the_panel_fills_in_while_the_turn_is_still_running(client):
    """The defect, end to end.

    A second thread polls while the answer is in flight and keeps every
    distinct view it saw. If progress only existed at the end there would be
    one view, with everything already done.
    """
    key = "ews-live-1"
    views: list[tuple[str, ...]] = []

    def watch() -> None:
        for _ in range(200):
            reply = client.post(f"{BASE}/ask/progress", json={"turn_key": key})
            if reply.status_code == 200 and reply.json().get("watching"):
                document = reply.json()
                views.append(tuple(
                    f"{s['key']}:{s['status']}" for s in document["steps"]))
                if not document["active"]:
                    return
            time.sleep(0.05)

    watcher = threading.Thread(target=watch)
    watcher.start()
    answer = _ask(client, LIVE_QUESTION, key)
    watcher.join(timeout=30)

    distinct = list(dict.fromkeys(views))
    assert len(distinct) >= 2, (
        "the panel never changed: progress arrived only at the end")
    assert answer["answered"] is True

    # The views only ever grow: a step never un-ticks, and the list never
    # shortens. A panel that went backwards would be worse than none.
    for earlier, later in zip(distinct, distinct[1:], strict=False):
        assert len(later) >= len(earlier), (earlier, later)


def test_a_watched_turn_was_seen_running_before_it_finished(client):
    key = "ews-live-2"
    running: list[bool] = []

    def watch() -> None:
        for _ in range(200):
            reply = client.post(f"{BASE}/ask/progress", json={"turn_key": key})
            if reply.status_code == 200 and reply.json().get("watching"):
                document = reply.json()
                running.append(bool(document["active"]))
                if not document["active"]:
                    return
            time.sleep(0.05)

    watcher = threading.Thread(target=watch)
    watcher.start()
    _ask(client, LIVE_QUESTION, key)
    watcher.join(timeout=30)

    assert any(running), "the turn was never observed while it was active"
    assert running[-1] is False, "the panel never stopped"


def test_the_answer_carries_the_finished_panel(client):
    """So the client does not have to race a last poll for it."""
    answer = _ask(client, LIVE_QUESTION, "ews-final-1")
    panel = answer["progress"]

    assert panel["active"] is False
    assert panel["version"] >= 1
    assert panel["completion_line"].startswith("Analysed in ")
    assert [s["key"] for s in panel["steps"]][-1] == "complete"


def test_a_turn_without_a_key_still_answers(client):
    """Progress is optional. The answer is not."""
    answer = _ask(client, LIVE_QUESTION, None)

    assert answer["answered"] is True
    assert answer["progress"]["steps"], "the finished panel should still exist"


def test_a_finished_turn_is_readable_for_a_while(client):
    key = "ews-after-1"
    _ask(client, LIVE_QUESTION, key)
    reply = client.post(f"{BASE}/ask/progress", json={"turn_key": key})

    assert reply.status_code == 200
    document = reply.json()
    assert document["watching"] is True
    assert document["active"] is False


# ------------------------------------------------------------- the boring half


def test_an_unknown_turn_is_not_an_error(client):
    reply = client.post(f"{BASE}/ask/progress",
                        json={"turn_key": "never-existed"})

    assert reply.status_code == 200
    assert reply.json() == {"watching": False, "version": 1}


def test_a_rejected_key_is_refused_by_the_schema(client):
    reply = client.post(f"{BASE}/ask/progress", json={"turn_key": ""})
    assert reply.status_code == 422

    reply = client.post(f"{BASE}/ask/progress", json={"turn_key": "x" * 65})
    assert reply.status_code == 422


def test_a_malformed_key_reads_as_nothing_rather_than_crashing(client):
    reply = client.post(f"{BASE}/ask/progress",
                        json={"turn_key": "../../etc/passwd"})

    assert reply.status_code == 200
    assert reply.json()["watching"] is False


def test_another_caller_cannot_read_a_turn(client):
    key = "ews-owned-1"
    _ask(client, LIVE_QUESTION, key)

    mine = client.post(f"{BASE}/ask/progress", json={"turn_key": key})
    assert mine.json()["watching"] is True

    theirs = client.post(f"{BASE}/ask/progress", json={"turn_key": key},
                         headers={"X-IPM-User-Id": "999", "X-IPM-Role": "analyst"})
    assert theirs.json()["watching"] is False, (
        "a turn was readable by somebody who did not run it")


# ------------------------------------------------------- the routing journey


def test_a_what_if_question_shows_routing_and_runs_nothing(client):
    answer = _ask(client, "What happens to ECL if oil falls 30%?",
                  "ews-routing-1")
    panel = answer["progress"]
    keys = [s["key"] for s in panel["steps"]]

    assert answer["redirected"] is True
    assert "routing" in keys
    assert "analysing" not in keys
    assert "planning" not in keys
    assert answer["budget"]["spent"]["executions"] == 0
    assert "routed to What-If Analysis" in panel["completion_line"]


# ------------------------------------------------------------- the vocabulary


FORBIDDEN = ("sonnet", "opus", "claude", "anthropic", "token", "schema",
             "provider", "budget", "ledger", "prompt", "llm", "model")


def test_the_published_vocabulary_carries_no_engineering_words(client):
    reply = client.get(f"{BASE}/ask/vocabulary")
    assert reply.status_code == 200
    published = reply.json()

    sentences = ([row["label"] for row in published["steps"]]
                 + [row["label"] for row in published["notes"]]
                 + list(published["analyses"].values()))
    assert sentences
    for sentence in sentences:
        low = sentence.lower()
        for word in FORBIDDEN:
            assert word not in low, f"{word!r} appeared in {sentence!r}"


def test_the_vocabulary_covers_the_required_mapping(client):
    """§5's eleven labels, by the words the brief asked for."""
    published = client.get(f"{BASE}/ask/vocabulary").json()
    labels = {row["key"]: row["label"] for row in published["steps"]}

    assert labels["understanding"] == "Understanding your question"
    assert labels["scoping"] == "Resolving scope and intent"
    assert labels["ownership"] == "Checking the right CreditProbe functionality"
    assert labels["evidence"] == "Loading Early Warning evidence"
    assert labels["planning"] == "Planning the investigation"
    assert labels["validating"] == "Validating the analysis"
    assert labels["analysing"] == "Running Early Warning analysis"
    assert labels["checking"] == "Checking evidence and completeness"
    assert labels["interpreting"] == "Preparing risk interpretation"
    assert labels["context"] == "Updating conversation context"
    assert labels["complete"] == "Analysis complete"


def test_no_progress_response_leaks_an_internal_stage_name(client):
    """The audit trail keeps them. The reader never sees them."""
    answer = _ask(client, LIVE_QUESTION, "ews-clean-1")
    written = str(answer["progress"]).lower()

    for internal in ("sonnet_pass_1", "sonnet_pass_2", "opus_analysis_plan",
                     "opus_sufficiency_review", "opus_final_interpretation",
                     "ews_context_built"):
        assert internal not in written, internal
