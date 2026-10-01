"""Approved protected security fix (P13 Decision 1): a credential typed into
a Cockpit question never reaches durable V4 storage in clear text.

RAW USER INPUT -> active in-memory request (unchanged: the model still sees
exactly what was typed) -> PERSISTENCE BOUNDARY (`run_store`'s connection) ->
secret-sanitised stored representation. Checked on the physical database,
WAL and SHM bytes and on every logical read path: run, thread, messages,
events, turns, investigation, Trace, exports, LLM exchange.

EVIDENCE LABEL: scripted analyst (MODEL MOCK); fake canary credentials only.
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from backend.cockpit_v4 import run_store
from backend.llm import exchange
from tests.cockpit_v4.test_gw_llm_exchange import _finalize_script
from tests.cockpit_v4.test_gw_runs import svc, who  # noqa: F401
from tests.cockpit_v4.test_gw_trace import audited  # noqa: F401

V4 = "/api/v1/cockpit-v4"
ANTHROPIC = "sk-ant-api03-FAKECANARY" + "A" * 32
OPENAI = "sk-proj-FAKECANARY" + "B" * 28
BEARER_VALUE = "FAKECANARYbearer0123456789abcdef"
PASSWORD = "FAKECANARYpw0123"
AWS = "AKIAFAKECANARY012345"
QUESTION = (f"My Anthropic key is {ANTHROPIC}, the OpenAI one {OPENAI}, "
            f"header Authorization: Bearer {BEARER_VALUE}, password="
            f"{PASSWORD} and {AWS}. How many facilities are in the book?")
SECRETS = (ANTHROPIC, OPENAI, BEARER_VALUE, PASSWORD, AWS, "FAKECANARY")


def _absent(label: str, data: bytes | str) -> None:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    for secret in SECRETS:
        assert secret.encode() not in raw, f"{label} holds {secret[:16]}…"


def _db_files(store) -> list[Path]:
    base = Path(store.path)
    return sorted(base.parent.glob(base.name + "*"))


@pytest.fixture
def leaked(audited, drive, make_run, store_db):
    client, holder = audited
    holder["who"] = {"id": "banker", "tenant": "demo-tenant",
                     "roles": ("analyst", "auditor")}
    # The production hand-off: accept (persist) -> a worker claims -> runs.
    accepted = make_run(QUESTION)
    claimed = store_db.claim_next("worker-test")
    assert claimed is not None and claimed.run_id == accepted.run_id
    _o, provider, record = drive(QUESTION, _finalize_script(),
                                 record=claimed)
    # More places a user types: a thread title and an investigation.
    client.post(f"{V4}/threads/{record.thread_id}/title",
                json={"title": f"keys {ANTHROPIC}"})
    inv = client.post(f"{V4}/investigations", json={
        "title": f"Follow-up with Bearer {BEARER_VALUE}",
        "summary": f"password={PASSWORD}",
        "thread_id": record.thread_id})
    return {"client": client, "provider": provider, "record": record,
            "investigation": inv.json() if inv.status_code < 300 else None,
            "store": store_db}


def test_the_model_still_receives_the_question_as_typed(leaked):
    """The fix is at the persistence boundary only: the active request is
    not altered (prompt construction and model-visible text unchanged)."""
    sent = json.dumps(leaked["provider"].sent, default=str)
    assert ANTHROPIC in sent and BEARER_VALUE in sent
    assert exchange.REDACTED not in sent


def test_display_and_read_paths_never_get_the_typed_question(make_run,
                                                             store_db):
    accepted = make_run(QUESTION)
    _absent("accept response", accepted.question)
    _absent("get_run", store_db.get_run(accepted.run_id).question)
    claimed = store_db.claim_next("w")
    assert ANTHROPIC in claimed.question  # execution hand-off only
    _absent("get_run after claim", store_db.get_run(accepted.run_id).question)
    # After a terminal state the in-memory copy is gone.
    store_db.update_state(accepted.run_id, expect_version=claimed.version,
                          state="CANCELLED", operation="test", terminal=True)
    assert accepted.run_id not in store_db._typed


def test_no_secret_bytes_in_the_database_wal_or_shm(leaked):
    files = _db_files(leaked["store"])
    names = {f.name for f in files}
    assert "state.sqlite3" in names and "state.sqlite3-wal" in names, names
    for f in files:
        _absent(f.name, f.read_bytes())


def test_no_secret_on_any_logical_read_path(leaked):
    store, record = leaked["store"], leaked["record"]
    run = store.get_run(record.run_id)
    _absent("runs.question", run.question)
    _absent("messages", json.dumps(store.load_messages(record.run_id)))
    _absent("events", json.dumps(
        [e.__dict__ if hasattr(e, "__dict__") else e
         for e in store.events_since(record.run_id, 0, 5000)], default=str))
    _absent("turns", json.dumps(store.thread_turns(record.thread_id),
                                default=str))
    client = leaked["client"]
    for path in (f"/runs/{record.run_id}", f"/threads/{record.thread_id}",
                 f"/runs/{record.run_id}/trace",
                 f"/runs/{record.run_id}/events",
                 f"/runs/{record.run_id}/governance",
                 "/investigations"):
        r = client.get(f"{V4}{path}")
        assert r.status_code == 200, (path, r.text[:300])
        _absent(path, r.content)
    if leaked["investigation"]:
        iid = leaked["investigation"]["investigation_id"]
        r = client.get(f"{V4}/investigations/{iid}")
        _absent("reopened investigation", r.content)


def test_no_secret_in_any_export(leaked):
    client, record = leaked["client"], leaked["record"]
    for path in (f"/runs/{record.run_id}/export",
                 f"/runs/{record.run_id}/governance/export"):
        r = client.get(f"{V4}{path}")
        assert r.status_code == 200, (path, r.text[:300])
        if r.headers.get("content-type", "").startswith("application/zip"):
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            for name in zf.namelist():
                _absent(f"{path}:{name}", zf.read(name))
        else:
            _absent(path, r.content)
    r = client.get(f"/api/v1/cockpit-v4/workspace/llm-exchange/runs/"
                   f"{record.run_id}/export")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    for name in zf.namelist():
        _absent(f"llm-exchange:{name}", zf.read(name))


def test_the_question_stays_understandable(leaked):
    stored = leaked["store"].get_run(leaked["record"].run_id).question
    assert "How many facilities are in the book?" in stored
    assert stored.count(exchange.REDACTED) >= 4
    assert stored.startswith("My Anthropic key is ")


def test_reopening_makes_zero_model_calls_and_restores_nothing(leaked):
    client, record = leaked["client"], leaked["record"]
    before = len(leaked["provider"].sent)
    for _ in range(2):
        r = client.get(f"{V4}/threads/{record.thread_id}")
        _absent("reopen", r.content)
        _absent("reopen run", client.get(f"{V4}/runs/{record.run_id}").content)
    assert len(leaked["provider"].sent) == before


def test_telemetry_named_like_tokens_is_untouched():
    body = json.dumps({"usage": {"input_tokens": 1200, "output_tokens": 40,
                                 "max_tokens": 4096,
                                 "cache_read_tokens": 0},
                       "token_count": 7, "note": "tokens are telemetry"})
    out = run_store._persistable("INSERT INTO events VALUES (?)", (body,))
    assert out == (body,)
    # A read is never rewritten.
    assert run_store._persistable("SELECT ?", (QUESTION,)) == (QUESTION,)


def test_a_json_payload_with_a_secret_stays_valid_json():
    body = json.dumps({"messages": [{"role": "user", "content": QUESTION}],
                       "headers": {"Authorization": f"Bearer {BEARER_VALUE}"},
                       "usage": {"input_tokens": 9}})
    (out,) = run_store._persistable("UPDATE runs SET x=?", (body,))
    tree = json.loads(out)
    _absent("json", out)
    assert tree["usage"]["input_tokens"] == 9
    assert "How many facilities" in tree["messages"][0]["content"]
    named = run_store._persistable("INSERT INTO t VALUES (:q)", {"q": QUESTION})
    _absent("named params", named["q"])
