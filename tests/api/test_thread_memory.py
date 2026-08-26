"""
Multi-turn threads, driven through the endpoints the browser actually calls.

Why this file exists
--------------------
Typed conversation memory was built, tested and shown to work — by tests that
called the orchestrator directly. The browser does not call the orchestrator.
It calls `POST /investigations` and `POST /investigations/{id}/messages`, and
the service behind those passed the analytical state and forgot the memory. So
"which of those fields are financial ratios?" worked in every test and failed
for every user.

A test that drives an internal function is a test of that function. These drive
the surface, in the order a person would, and assert on what comes back.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def require_everything():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if not database_available():
        pytest.skip("Threads need a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


HEADERS = {"X-IPM-Role": "ANALYST"}


def thread(client, questions: list[str]) -> list[dict]:
    """Ask a whole thread the way the browser does, and return each turn."""
    started = client.post("/api/v1/investigations",
                          json={"question": questions[0], "ask": True},
                          headers=HEADERS)
    assert started.status_code in (200, 201), started.text
    body = started.json()
    thread_id = body["thread"]["id"]

    out = [body]
    for question in questions[1:]:
        response = client.post(f"/api/v1/investigations/{thread_id}/messages",
                               json={"question": question}, headers=HEADERS)
        assert response.status_code == 200, response.text
        out.append(response.json())
    return out


def run_of(turn: dict) -> dict:
    return turn.get("run") or {}


def action_of(turn: dict) -> str:
    conversation = run_of(turn).get("conversation") or {}
    return str((conversation.get("continuation") or {}).get("action") or "")


def rows_of(turn: dict) -> list[dict]:
    steps = run_of(turn).get("steps") or []
    return ((steps[0].get("result") or {}).get("rows") or []) if steps else []


# ---------------------------------------------------------------- metadata


def test_a_field_set_can_be_classified_on_the_next_turn(client):
    """The exact thread that worked in tests and failed in the product."""
    turns = thread(client, [
        "What fields are available in the ratings data?",
        "Which of those fields are financial ratios?",
    ])

    assert run_of(turns[0])["status"] == "succeeded"
    assert len(rows_of(turns[0])) > 10, "the first turn must produce a field set"

    answer = run_of(turns[1])
    assert answer["status"] == "succeeded", answer.get("clarification")
    assert action_of(turns[1]) == "METADATA_FOLLOWUP"
    assert 0 < len(rows_of(turns[1])) < len(rows_of(turns[0]))
    assert "ratio" in answer["narrative"]["direct_answer"].lower()


def test_a_dataset_stays_the_subject_for_a_metadata_follow_up(client):
    turns = thread(client, [
        "What IFRS 9 data do you have?",
        "What is the latest available period?",
    ])

    answer = run_of(turns[1])
    assert answer["status"] == "succeeded", answer.get("clarification")
    assert "ifrs9_staging" in answer["narrative"]["direct_answer"]


def test_open_the_latest_dataset_navigates(client):
    turns = thread(client, [
        "What IFRS 9 data do you have?",
        "Open the latest dataset.",
    ])

    assert action_of(turns[1]) == "NAVIGATE"
    answer = run_of(turns[1])
    assert answer["status"] == "succeeded", answer.get("clarification")
    assert "opening" in answer["narrative"]["direct_answer"].lower()


# --------------------------------------------------------------- analytical


def test_a_presentation_change_keeps_the_figures(client):
    """"Show it as a graph" must not recompute a portfolio aggregate."""
    turns = thread(client, [
        "What is total EAD by sector in the latest quarter?",
        "Show it as a graph.",
    ])

    assert action_of(turns[1]) == "MODIFY_PRESENTATION"
    assert run_of(turns[1])["status"] == "succeeded"
    assert len(rows_of(turns[1])) == len(rows_of(turns[0])), (
        "changing how a result is shown must not change what it contains")


def test_a_narrowing_keeps_the_carried_population(client):
    turns = thread(client, [
        "Which customers had a rating downgrade and an increase in ECL over "
        "the latest year?",
        "Only Contracting.",
    ])

    answer = run_of(turns[1])
    assert answer["status"] == "succeeded", answer.get("clarification")
    narrowed = rows_of(turns[1])
    assert 0 < len(narrowed) < len(rows_of(turns[0]))
    assert all(row.get("sector") == "Contracting" for row in narrowed)


def test_an_elided_referent_still_means_the_rows_on_screen(client):
    """"Which also had…" is "which of those also had…" with the referent left
    out, which is how people actually talk."""
    turns = thread(client, [
        "Which customers have worsening leverage and declining DSCR together "
        "with a rating downgrade?",
        "Show the ten largest by EAD.",
        "Which also had an increase in ECL?",
    ])

    assert len(rows_of(turns[1])) == 10
    final = rows_of(turns[2])
    assert 0 < len(final) <= 10, (
        "a continuation must not silently widen back to the whole book")


def test_every_turn_states_the_scope_it_covered(client):
    turns = thread(client, [
        "Show the five largest Real Estate customers by EAD.",
        "Rank those by ECL.",
    ])

    for turn in turns:
        assert run_of(turn)["narrative"]["scope"], (
            "an answer that does not say what it covers can be read as "
            "covering something else")


def test_the_thread_records_how_each_turn_was_routed(client):
    turns = thread(client, ["What is total EAD by sector in the latest quarter?"])
    conversation = run_of(turns[0]).get("conversation") or {}

    assert (conversation.get("routing") or {}).get("route")
    assert (conversation.get("invariants") or {}).get("ok") is True
    assert (conversation.get("scope") or {}).get("after")
