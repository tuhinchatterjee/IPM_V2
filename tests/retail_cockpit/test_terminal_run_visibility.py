"""A run that settled before the page mounted must still be visible.

The defect this exists for
--------------------------
Asking a question in the candidate produced a thread reading **"0 messages"**,
the book's opening chips, and no sign that anything had been asked. Everything
upstream was correct: the run was accepted, driven by the real worker, and
settled; its seven events were persisted and streamed. What went wrong was in
the thread page, which read the run's status on mount and returned on a
terminal one, leaving nothing on screen.

The assumption behind that return is that a settled run left a TURN for the
transcript reload to speak for it. It holds for a run that answered and fails
for every run that did not: `worker.append_turn` is guarded by
`outcome.response is not None`, so a FAILED, CANCELLED or EXPIRED run writes no
turn -- and `GET /threads/{id}` carries turns and no run, with no thread-to-runs
endpoint anywhere, so the page had nothing left to render it from.

It is a race rather than a rarity, and these tests pin the numbers that make it
one: an offline run reaches FAILED in well under a second, which beats the
navigation every time. A live run that fails at the model call -- no
credential, a rate limit, a refusal -- does the same.

What is asserted here
---------------------
The server-side contract that makes the UI branch matter (a failed run settles,
persists its events, and writes no turn), the replay that makes the fix work (a
terminal run's stream replays from cursor 0 and closes on `run.settled`), and
the absence of the branch itself. The rendering is the browser suite's job;
these are the facts underneath it.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VIEW = ROOT / "frontend/src/components/cockpit-v4/thread-view.tsx"
RECORD = ROOT / "docs/retail_cockpit/PORTED_FILES.md"
WORKER = ROOT / "backend/cockpit_v4/worker.py"
ROUTES = ROOT / "backend/cockpit_v4/routes.py"


# --------------------------------------------------- the server-side contract

def test_a_turn_is_written_only_when_there_is_a_response() -> None:
    """The guard that makes a failed run leave no transcript behind.

    Not a state test: `append_turn` is not gated on the run's state but on
    whether an answer exists. That is why "the transcript will show it" is
    wrong for a failed run, and it is the premise of the whole fix.
    """
    source = WORKER.read_text(encoding="utf-8")
    guard = re.search(
        r"if outcome\.response is not None:\s*\n\s*try:\s*\n\s*"
        r"self\.store\.append_turn\(", source)
    assert guard, ("worker.py no longer guards append_turn on the response. "
                   "If a failed run now writes a turn, the thread page's "
                   "resume path should be re-read: this fix assumes it does "
                   "not.")


def test_the_thread_endpoint_carries_no_run() -> None:
    """The page cannot discover a run from the server, so the client pointer
    is the only route to it -- which is why dropping the pointer lost it."""
    source = ROUTES.read_text(encoding="utf-8")
    body = source[source.index('@router.get("/threads/{thread_id}")'):]
    body = body[:body.index("\n@router")] if "\n@router" in body else body
    assert '"turns": turns' in body
    assert '"run_id"' not in body and '"runs"' not in body
    # And there is no listing to fall back on.
    assert '@router.get("/threads/{thread_id}/runs")' not in source


def test_a_terminal_run_replays_and_closes(offline_settled_run) -> None:
    """The stream is what the fix relies on, so it is asserted directly.

    `events_since(run_id, 0)` yields every frame, and the terminal one is
    followed by `run.settled` and the end of the stream -- so following a run
    that has already finished is a complete render, not a hang.
    """
    run_id, store = offline_settled_run
    events = store.events_since(run_id, 0, limit=200)
    types = [e.event_type for e in events]
    # `run.accepted` is the ROUTE's frame, emitted before the worker is
    # handed the record, so it is not in a worker-driven run. What matters
    # for the replay is that the chain is committed in order and ends on a
    # terminal frame, which is what closes the stream.
    assert types[-1] == "run.failed", types
    assert "run.started" in types, types
    assert "model.requested" in types, types
    # Replay is cursor-based: asking again from 0 returns the same chain, so
    # a page arriving late reads exactly what a page watching live saw.
    assert [e.event_type for e in store.events_since(run_id, 0, limit=200)] \
        == types


def test_the_offline_run_settles_failed_and_writes_no_turn(
        offline_settled_run) -> None:
    run_id, store = offline_settled_run
    record = store.get_run(run_id)
    assert record.state == "FAILED"
    assert record.error_code == "PROVIDER_UNAVAILABLE"
    assert store.thread_turns(record.thread_id) == [], (
        "the failed run wrote a turn, so the thread page would have had "
        "something to render and this fix would be unnecessary")


def test_the_failure_is_fast_enough_to_beat_a_navigation(
        offline_settled_run) -> None:
    """The race, measured rather than asserted from intuition.

    A page that mounts after the run has settled is the normal case offline,
    not an edge one. Two seconds is a generous ceiling; the measured figure is
    well under one.
    """
    import datetime as dt

    run_id, store = offline_settled_run
    record = store.get_run(run_id)
    started = dt.datetime.fromisoformat(str(record.created_at))
    settled = dt.datetime.fromisoformat(str(record.updated_at))
    assert (settled - started).total_seconds() < 2.0


# ------------------------------------------------------------ the client fix

def test_the_resume_path_no_longer_drops_a_settled_run() -> None:
    source = VIEW.read_text(encoding="utf-8")
    assert "const TERMINAL_RUN_STATES" not in source, (
        "the set that named the states a resumed run was dropped on is back. "
        "If it has a new reader, check it is not the resume effect again.")
    # From AFTER the pointer guard -- `if (!active || active.threadId !==
    # threadId) return;` is correct and stays -- to the follow call. Nothing
    # in between may return, because every return in that span is a run the
    # reader asked for and will never see.
    body = source[source.index("let stop: (() => void) | undefined;"):]
    body = body[:body.index("}, [follow, threadId]);")]
    assert "stop = follow(active.runId);" in body
    before_follow = body.split("stop = follow")[0]
    assert "return;" not in before_follow, (
        "the resume effect returns early again before following the run:\n"
        + before_follow)


def test_the_live_panel_still_deduplicates_the_transcript() -> None:
    """Following every run is only safe because of this filter.

    A run that DID write a turn is rendered by the live panel, and the turn it
    wrote is filtered out of the reloaded transcript. Without that, following
    a completed run would draw the exchange twice.
    """
    source = VIEW.read_text(encoding="utf-8")
    assert "turn.run_id !== live.runId" in source


def test_the_record_and_the_file_agree() -> None:
    row = re.search(
        r"^\|\s*`frontend/src/components/cockpit-v4/thread-view\.tsx`\s*"
        r"\|\s*`?([0-9a-f]{8,64})`?\s*\|\s*(.+?)\s*\|\s*$",
        RECORD.read_text(encoding="utf-8"), re.M)
    assert row, f"{RECORD.name} no longer records thread-view.tsx"
    recorded, note = row.group(1), row.group(2)
    digest = hashlib.sha256(VIEW.read_bytes()).hexdigest()
    assert digest.startswith(recorded), (
        f"thread-view.tsx is {digest[:16]} but the record says {recorded}")
    assert "exception" in note.lower() and "F2" in note, note


@pytest.fixture()
def offline_settled_run(chain_store, chain_runtime, chain_release):  # noqa: ANN001
    """Drive one real run to its terminal state with no provider behind it.

    The whole pipeline -- the real worker, the real store, the real event
    stream -- exactly as `drive_chain` does it, with the offline provider in
    place of the scripted one. Only the model call is absent, and its absence
    is the outcome under test.
    """
    from backend.cockpit_v4.worker import Worker
    from backend.retail_cockpit_host.offline import OfflineProvider

    chain_runtime.provider = OfflineProvider()
    thread_id = chain_store.create_thread(
        tenant_id="demo-tenant", principal_id="u1", domain_id="retail",
        release_id=chain_release)
    record, _ = chain_store.accept_run(
        thread_id=thread_id, tenant_id="demo-tenant", principal_id="u1",
        question="What is total exposure at default by product?",
        mode="standard", release_id=chain_release, domain_id="retail",
        ui_filters={}, idempotency_key="", body_digest="",
        startup_sha="testsha", deadline_at="")
    Worker(store=chain_store, runtime=chain_runtime).execute(record)
    return record.run_id, chain_store
