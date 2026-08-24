"""
Every answer must be traceable — from wherever it was produced.

CreditProbe's central promise is that any figure can be followed back to the
rows behind it. That promise is kept by one integer: the `analysis_run_id` on
an answer, which is what puts a working Trace button on it.

It was silently broken. `analysis_runs.chat_id` pointed at the old `chats`
table while conversations had moved to `investigations`, so every answer
produced inside a conversation failed its foreign key on the way to being
stored. Persistence is deliberately best-effort — a database problem must not
lose an answer somebody is already reading — so nothing raised. The only
symptom was a null id and a dead Trace button on every answer in the product.

These tests exist so that cannot happen again quietly. They assert the id all
the way through: returned by the API, stored on the message, and resolving to a
trace graph that can actually be fetched.
"""

from __future__ import annotations

import pytest

from backend.data_access import get_data_source
from backend.engine.helpers import FACILITY
from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="Trace reachability needs a reachable PostgreSQL",
)

ANALYST = {"X-IPM-Role": "ANALYST"}


@pytest.fixture(scope="module", autouse=True)
def require_data():
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def answered(client) -> dict:
    """One real answer, produced the way the product produces every answer."""
    started = client.post(
        "/api/v1/investigations",
        json={"question": "What is our current NPL ratio?", "ask": True},
        headers=ANALYST,
    )
    assert started.status_code in (200, 201), started.text
    return started.json()


def test_an_answer_in_a_conversation_carries_a_run_id(answered):
    """The one integer the whole Trace promise rests on."""
    run = answered["run"]
    assert run["status"] == "succeeded", run.get("clarification")
    assert run["analysis_run_id"] is not None, (
        "the answer was not persisted — the Trace button on it is dead"
    )


def test_the_run_id_is_stored_on_the_message_not_just_returned(answered):
    """Re-opening the conversation must still offer the Trace."""
    assistant = [m for m in answered["thread"]["messages"]
                 if m["role"] == "assistant"]
    assert assistant, "the answer was not recorded in the conversation"
    assert assistant[-1]["analysis_run_id"] == answered["run"]["analysis_run_id"]


def test_reopening_the_conversation_still_carries_the_run_id(client, answered):
    thread = client.get(
        f"/api/v1/investigations/{answered['thread']['id']}", headers=ANALYST,
    ).json()
    assistant = [m for m in thread["messages"] if m["role"] == "assistant"]
    assert assistant[-1]["analysis_run_id"] == answered["run"]["analysis_run_id"]
    assert (assistant[-1]["payload"] or {})["analysis_run_id"] == \
        answered["run"]["analysis_run_id"]


def test_the_run_id_resolves_to_a_trace_that_can_be_fetched(client, answered):
    """A button that leads to a 404 is not a Trace."""
    run_id = answered["run"]["analysis_run_id"]
    response = client.get(f"/api/v1/investigations/run/{run_id}", headers=ANALYST)
    if response.status_code == 404:
        response = client.get(f"/api/v1/trace/{run_id}", headers=ANALYST)
    assert response.status_code == 200, (
        f"the Trace for run {run_id} could not be fetched: {response.text[:200]}"
    )


def test_a_follow_up_in_the_same_conversation_is_also_traceable(client, answered):
    """The second question must be as traceable as the first."""
    thread_id = answered["thread"]["id"]
    turn = client.post(
        f"/api/v1/investigations/{thread_id}/messages",
        json={"question": "How is exposure split across stages?"},
        headers=ANALYST,
    ).json()
    if turn["status"] == "needs_clarification":
        pytest.skip("the follow-up needed a clarification rather than running")
    assert turn["run"]["analysis_run_id"] is not None
    assert turn["run"]["analysis_run_id"] != answered["run"]["analysis_run_id"], (
        "a follow-up must get its own run, not reuse the previous one"
    )
