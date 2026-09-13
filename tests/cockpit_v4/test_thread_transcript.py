"""MODEL MOCK · REAL DATABASE/RUNNER · REAL HTTP · UNIT.

A conversation a reader can scroll, reopen and rename.

The product problem this round exists for: V4 could answer, but it did not
feel like a conversation. One question, one answer, and the reader was still
looking at a dashboard. A transcript is the difference, and a transcript that
renders only its last few exchanges is not one -- it is a window, and a reader
scrolling up to find what they asked half an hour ago finds nothing.

Two sizes on purpose. `recent_turns` is what the ANALYST reads and stays
small, because a twenty-turn conversation must not be sent to a model in
full. `thread_turns` is what a READER reads and is complete.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.cockpit_v4 import routes

P = "/api/v1/cockpit-v4"


@pytest.fixture
def client(store_db, runtime):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: {
                       "id": r.headers.get("X-Test-User", "u1"),
                       "tenant": r.headers.get("X-Test-Tenant",
                                               "demo-tenant")},
                   startup_sha="testsha")
    app.include_router(routes.router)
    return TestClient(app)


def _thread_with(store_db, questions, tenant="demo-tenant"):
    thread_id = store_db.create_thread(tenant_id=tenant, principal_id="u1")
    for index, question in enumerate(questions):
        store_db.append_turn(
            thread_id=thread_id, run_id=f"run-{index}", question=question,
            answer={"narrative": f"Answer {index}", "disposition": "answer",
                    "tables": [], "charts": [],
                    "suggested_questions": [{"question": "And next?"}]})
    return thread_id


# ---- the transcript ----------------------------------------------------

def test_a_thread_renders_every_turn_not_a_window(client, store_db):
    questions = [f"Question {n}?" for n in range(12)]
    thread_id = _thread_with(store_db, questions)

    body = client.get(f"{P}/threads/{thread_id}").json()
    assert body["turn_count"] == 12
    assert [t["question"] for t in body["turns"]] == questions, (
        "the transcript must be complete and in order")


def test_a_turn_carries_what_it_takes_to_render_it(client, store_db):
    thread_id = _thread_with(store_db, ["Total EAD by sector?"])
    turn = client.get(f"{P}/threads/{thread_id}").json()["turns"][0]
    for key in ("turn_id", "run_id", "ordinal", "question", "answer",
                "created_at"):
        assert key in turn, key
    assert turn["run_id"] == "run-0", (
        "without the run id there is no trace to open from a past turn")
    assert turn["answer"]["narrative"] == "Answer 0"


def test_the_analyst_still_reads_only_a_few_turns(store_db):
    """The two sizes are different on purpose."""
    thread_id = _thread_with(store_db, [f"Q{n}?" for n in range(12)])
    assert len(store_db.recent_turns(thread_id, 3)) == 3
    assert len(store_db.thread_turns(thread_id)) == 12


def test_the_transcript_says_what_its_numbers_mean(client, store_db,
                                                   release_id):
    thread_id = _thread_with(store_db, ["Total EAD?"])
    body = client.get(f"{P}/threads/{thread_id}").json()
    assert body["release"]["release_id"] == release_id
    assert body["release"]["reporting_currency"] == "SAR"
    assert len(body["release"]["release_fingerprint"]) == 64


# ---- the title ---------------------------------------------------------

def test_the_first_question_names_the_thread(client, store_db):
    """No model call. The thread is about what was asked in it."""
    thread_id = _thread_with(store_db, ["What is total EAD by sector?",
                                        "And a year ago?"])
    body = client.get(f"{P}/threads/{thread_id}").json()
    assert body["title"] == "What is total EAD by sector?"


def test_a_very_long_question_does_not_become_a_very_long_title(store_db):
    thread_id = store_db.create_thread(tenant_id="demo-tenant",
                                       principal_id="u1")
    store_db.append_turn(thread_id=thread_id, run_id="r", answer={},
                         question="word " * 200)
    assert len(store_db.thread_title(thread_id)) <= 200


def test_renaming_a_thread_keeps_the_new_name(client, store_db):
    thread_id = _thread_with(store_db, ["What is total EAD by sector?"])
    response = client.post(f"{P}/threads/{thread_id}/title",
                           json={"title": "Sector exposure review"})
    assert response.status_code == 200
    assert response.json()["title"] == "Sector exposure review"
    assert client.get(f"{P}/threads/{thread_id}").json()["title"] == \
        "Sector exposure review"


def test_a_rename_does_not_get_overwritten_by_the_next_turn(client,
                                                            store_db):
    thread_id = _thread_with(store_db, ["First question?"])
    client.post(f"{P}/threads/{thread_id}/title", json={"title": "My review"})
    store_db.append_turn(thread_id=thread_id, run_id="r2", answer={},
                         question="Second question?")
    assert store_db.thread_title(thread_id) == "My review"


# ---- §53: a URL is not an authorization --------------------------------

def test_another_tenant_cannot_read_a_thread(client, store_db):
    thread_id = _thread_with(store_db, ["Total EAD?"])
    response = client.get(f"{P}/threads/{thread_id}",
                          headers={"X-Test-Tenant": "other-bank"})
    assert response.status_code == 404, (
        "and 404 rather than 403: it must not confirm the thread exists")


def test_another_tenant_cannot_rename_a_thread(client, store_db):
    thread_id = _thread_with(store_db, ["Total EAD?"])
    response = client.post(f"{P}/threads/{thread_id}/title",
                           json={"title": "Mine now"},
                           headers={"X-Test-Tenant": "other-bank"})
    assert response.status_code == 404
    assert store_db.thread_title(thread_id) == "Total EAD?"


# ---- §36: what "continue where you left off" lists ---------------------

def test_a_reopenable_thread_is_listed_by_what_was_asked_in_it(store_db):
    thread_id = _thread_with(store_db, ["Which sectors carry the most ECL?",
                                        "And the borrowers behind them?"])
    rows = store_db.recent_threads(tenant_id="demo-tenant", principal_id="u1")
    row = next(r for r in rows if r["thread_id"] == thread_id)
    assert row["title"] == "Which sectors carry the most ECL?"
    assert row["turns"] == 2
    assert row["last_activity_at"]


def test_a_renamed_thread_is_listed_under_its_new_name(store_db):
    thread_id = _thread_with(store_db, ["Which sectors carry the most ECL?"])
    store_db.set_thread_title(thread_id, tenant_id="demo-tenant",
                              title="ECL concentration")
    rows = store_db.recent_threads(tenant_id="demo-tenant", principal_id="u1")
    row = next(r for r in rows if r["thread_id"] == thread_id)
    assert row["title"] == "ECL concentration"


# ---- the schema can be added to without losing a database --------------

def test_a_database_written_before_titles_existed_still_opens(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` does not alter an existing table."""
    import sqlite3

    from backend.cockpit_v4.run_store import RunStore

    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE threads (thread_id TEXT PRIMARY KEY, "
                 "tenant_id TEXT NOT NULL, principal_id TEXT NOT NULL, "
                 "created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO threads VALUES ('th-old', 'demo-tenant', "
                 "'u1', '2026-09-01T00:00:00Z')")
    conn.commit()
    conn.close()

    store = RunStore(path)
    assert store.thread_title("th-old") == ""
    assert store.set_thread_title("th-old", tenant_id="demo-tenant",
                                  title="Recovered")
    assert store.thread_title("th-old") == "Recovered"
