"""Streaming a generation, durably. PB-038.

The interesting cases are not "text arrives". They are: text arriving BEFORE
the run is over, a refresh in the middle, a stop in the middle, a provider
failing in the middle, and two sends that must remain one generation. Each of
those is a way a streamed conversation goes wrong in a way a synchronous one
cannot.

The provider is scripted here, and deliberately chunked, so what is proven is
the transport and the durability around it. Live generation is verified
separately and is never claimed by these tests.
"""

from __future__ import annotations

import threading
import time

import pytest

from backend.playbook import provider, service, stream
from backend.playbook import repository as repo

REPORT_MD = """# Committee report

## 1. Executive summary

Weighted ECL was SAR 22.77 million, an increase of SAR 1.87 million.

## 2. Limitations

Post-model adjustments are outside scope.
"""


@pytest.fixture
def ledger_calcs():
    from backend.playbook.fixtures import ecl_oracle as oracle

    return list(oracle.headline().values())


@pytest.fixture
def job(db, scope, workspace):
    started = service.begin_generation(
        db, scope, workspace.id, text="Write the report.",
        idempotency_key=f"ws{workspace.id}:stream-test")
    return started["job_id"]


def _events(db, job_id):
    return stream.events_since(db, job_id, 0)


class TestTheLogIsTheStream:
    def test_events_are_numbered_from_one_and_never_reused(self, db, job):
        writer = stream.Writer(session=db, job_id=job)
        writer.state("reviewing_sources")
        writer.delta("Weighted ECL ")
        writer.delta("rose to SAR 22.77 million.")
        writer.done({"version": 1})

        kinds = [(e.seq, e.kind) for e in _events(db, job)]
        assert kinds == [(1, "state"), (2, "delta"), (3, "done")]

    def test_deltas_are_coalesced_rather_than_written_per_token(self, db, job):
        writer = stream.Writer(session=db, job_id=job)
        for _ in range(10):
            writer.delta("x" * 20)
        writer.flush()

        deltas = [e for e in _events(db, job) if e.kind == "delta"]
        assert len(deltas) < 10, "one row per token would make the log the "\
                                 "slowest part of the system"
        assert stream.replay_text(_events(db, job)) == "x" * 200

    def test_a_state_flushes_the_text_before_it(self, db, job):
        """Order is meaning: text written before a state must not appear
        after it, or the reader sees the answer jump around."""
        writer = stream.Writer(session=db, job_id=job)
        writer.delta("Half a sentence")
        writer.state("rendering")
        kinds = [e.kind for e in _events(db, job)]
        assert kinds == ["delta", "state"]

    def test_a_failure_discards_the_half_sentence(self, db, job):
        writer = stream.Writer(session=db, job_id=job)
        writer.delta("The weighted ECL is")
        writer.error("The provider failed.", category="server")

        events = _events(db, job)
        assert [e.kind for e in events] == ["error"]
        assert stream.replay_text(events) == ""

    def test_replay_reconstructs_exactly_what_was_written(self, db, job):
        writer = stream.Writer(session=db, job_id=job)
        for piece in ("# Report\n\n", "## 1. Summary\n\n", "It rose.\n"):
            writer.delta(piece)
        writer.flush()
        assert stream.replay_text(_events(db, job)) == (
            "# Report\n\n## 1. Summary\n\nIt rose.\n")


class TestTextArrivesBeforeTheRunIsOver:
    def test_deltas_are_written_while_the_document_is_still_being_made(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        """The whole point of streaming, asserted directly: at the moment the
        author is still writing, the log already holds part of the answer."""
        scripted_author(REPORT_MD, chunk=30)
        seen: list[int] = []
        writer = stream.Writer(session=db, job_id=job)

        original = writer.delta

        def counting(text: str) -> None:
            original(text)
            # How much of the ANSWER exists at this moment, mid-run.
            seen.append(len(stream.replay_text(_events(db, job))))

        service.run_generation(
            db, scope, workspace.id, job_id=job, text="Write the report.",
            calculations=ledger_calcs, on_delta=counting)

        assert seen, "no text was streamed at all"
        assert seen[0] < seen[-1], "text did not grow as it arrived"
        # And the run only finished afterwards.
        assert any(e.kind == "delta" for e in _events(db, job))

    def test_the_streamed_text_is_the_text_that_was_saved(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        scripted_author(REPORT_MD, chunk=25)
        writer = stream.Writer(session=db, job_id=job)
        result = service.run_generation(
            db, scope, workspace.id, job_id=job, text="Write the report.",
            calculations=ledger_calcs, on_delta=writer.delta)
        writer.flush()

        streamed = stream.replay_text(_events(db, job))
        assert "22.77" in streamed
        assert result["state"] == "ready"

    def test_nothing_hidden_is_ever_written_to_the_log(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        """The system prompt and the evidence ledger reach the provider. They
        must not reach the browser."""
        scripted_author(REPORT_MD, chunk=25)
        writer = stream.Writer(session=db, job_id=job)
        service.run_generation(
            db, scope, workspace.id, job_id=job, text="Write the report.",
            calculations=ledger_calcs, on_delta=writer.delta)
        writer.flush()

        blob = " ".join(str(e.data) for e in _events(db, job))
        for secret in ("EVIDENCE", "You are", "sk-ant", "calc://"):
            assert secret not in blob, f"{secret!r} leaked into the stream"


class TestAnInterruptedStreamIsNotAnAnswer:
    def test_a_cancelled_run_writes_no_assistant_answer_and_no_version(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        scripted_author(REPORT_MD, chunk=20)
        writer = stream.Writer(session=db, job_id=job)

        with pytest.raises(provider.Cancelled):
            service.run_generation(
                db, scope, workspace.id, job_id=job, text="Write the report.",
                calculations=ledger_calcs, on_delta=writer.delta,
                is_cancelled=lambda: True)

        messages = repo.messages(db, workspace.id)
        assert [m.role for m in messages] == ["user", "assistant"]
        # The one assistant row is the system's account of the stop, not an
        # answer: it carries no artifact and is not attributed to the model.
        assert messages[1].origin == "system"
        assert messages[1].content.get("artifact_id") is None
        assert repo.artifacts(db, workspace.id) == []

    def test_a_provider_failure_mid_stream_leaves_the_previous_version_current(
            self, db, scope, workspace, ledger_calcs, scripted_author):
        first = service.begin_generation(
            db, scope, workspace.id, text="Draft it.",
            idempotency_key=f"ws{workspace.id}:one")
        scripted_author(REPORT_MD, chunk=30)
        good = service.run_generation(
            db, scope, workspace.id, job_id=first["job_id"], text="Draft it.",
            calculations=ledger_calcs)

        second = service.begin_generation(
            db, scope, workspace.id, text="Revise it.",
            idempotency_key=f"ws{workspace.id}:two")
        writer = stream.Writer(session=db, job_id=second["job_id"])

        def fails(text: str) -> None:
            writer.delta(text)
            raise provider.AuthoringError("The provider went away.",
                                          category="server")

        with pytest.raises(provider.AuthoringError):
            service.run_generation(
                db, scope, workspace.id, job_id=second["job_id"],
                text="Revise it.", calculations=ledger_calcs,
                artifact_id=good["artifact_id"],
                base_version_id=good["version_id"], on_delta=fails)

        from backend.models.playbook import PlaybookArtifact
        artifact = db.get(PlaybookArtifact, good["artifact_id"])
        assert artifact.current_version_id == good["version_id"]

    def test_a_half_streamed_answer_is_not_in_the_thread_at_all(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        """A partial stream lives in the event log and nowhere else, which is
        what stops it being read back — or exported — as a finished analysis."""
        scripted_author(REPORT_MD, chunk=20)
        writer = stream.Writer(session=db, job_id=job)

        def stop_after_a_bit(text: str) -> None:
            writer.delta(text)
            if len(stream.replay_text(_events(db, job))) > 40:
                raise provider.AuthoringError("Interrupted.", category="server")

        with pytest.raises(provider.AuthoringError):
            service.run_generation(
                db, scope, workspace.id, job_id=job, text="Write the report.",
                calculations=ledger_calcs, on_delta=stop_after_a_bit)

        assistant = [m for m in repo.messages(db, workspace.id)
                     if m.role == "assistant"]
        assert len(assistant) == 1
        assert assistant[0].content.get("failed") is True
        assert "markdown" not in assistant[0].content
        assert assistant[0].content.get("version") is None


def _files_in(db, workspace_id):
    """Every artifact file this workspace has. Scoped, because the suite
    shares a database with a seeded demonstration that legitimately has 14."""
    from sqlalchemy import select

    from backend.models.playbook import (
        PlaybookArtifact,
        PlaybookArtifactFile,
        PlaybookArtifactVersion,
    )

    stmt = (select(PlaybookArtifactFile)
            .join(PlaybookArtifactVersion,
                  PlaybookArtifactFile.version_id == PlaybookArtifactVersion.id)
            .join(PlaybookArtifact,
                  PlaybookArtifactVersion.artifact_id == PlaybookArtifact.id)
            .where(PlaybookArtifact.workspace_id == workspace_id))
    return list(db.execute(stmt).scalars())


class TestAnIncompleteAnswerCannotBeTakenAway:
    """The half-written answer must not become a file, a version, or an
    export. It exists in the event log and nowhere a user can act on."""

    def test_an_interrupted_run_leaves_nothing_to_download(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        scripted_author(REPORT_MD, chunk=20)
        writer = stream.Writer(session=db, job_id=job)

        def interrupt(text: str) -> None:
            writer.delta(text)
            raise provider.AuthoringError("Interrupted.", category="server")

        with pytest.raises(provider.AuthoringError):
            service.run_generation(
                db, scope, workspace.id, job_id=job, text="Write the report.",
                calculations=ledger_calcs, on_delta=interrupt)

        assert _files_in(db, workspace.id) == []

    def test_a_stopped_run_leaves_nothing_to_download_either(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        scripted_author(REPORT_MD, chunk=20)
        with pytest.raises(provider.Cancelled):
            service.run_generation(
                db, scope, workspace.id, job_id=job, text="Write the report.",
                calculations=ledger_calcs, is_cancelled=lambda: True)

        assert _files_in(db, workspace.id) == []

    def test_the_partial_text_exists_only_in_the_log(
            self, db, scope, workspace, ledger_calcs, scripted_author, job):
        scripted_author(REPORT_MD, chunk=20)
        writer = stream.Writer(session=db, job_id=job)

        def interrupt(text: str) -> None:
            writer.delta(text)
            if len(writer._buffer) > 10:
                writer.flush()
                raise provider.AuthoringError("Interrupted.", category="server")

        with pytest.raises(provider.AuthoringError):
            service.run_generation(
                db, scope, workspace.id, job_id=job, text="Write the report.",
                calculations=ledger_calcs, on_delta=interrupt)

        # It is in the log…
        assert stream.replay_text(_events(db, job))
        # …and in no message anybody can act on.
        for message in repo.messages(db, workspace.id):
            assert "markdown" not in message.content


class TestARefreshDoesNotStartASecondGeneration:
    def test_the_same_key_finds_the_running_job(self, db, scope, workspace,
                                                job):
        again = service.begin_generation(
            db, scope, workspace.id, text="Write the report.",
            idempotency_key=f"ws{workspace.id}:stream-test")
        assert again["duplicate"] is True
        assert again["job_id"] == job

    def test_a_duplicate_send_adds_no_second_question(self, db, scope,
                                                      workspace, job):
        service.begin_generation(
            db, scope, workspace.id, text="Write the report.",
            idempotency_key=f"ws{workspace.id}:stream-test")
        questions = [m for m in repo.messages(db, workspace.id)
                     if m.role == "user"]
        assert len(questions) == 1

    def test_a_reloading_browser_is_told_what_to_attach_to(self, db, scope,
                                                           workspace, job):
        running = service.running_job(db, scope, workspace.id)
        assert running is not None and running["id"] == job

    def test_a_finished_generation_is_not_offered_as_running(
            self, db, scope, workspace, job):
        service.mark_job_finished(db, job, state="ready")
        assert service.running_job(db, scope, workspace.id) is None

    def test_replay_after_a_refresh_returns_only_what_was_missed(self, db, job):
        writer = stream.Writer(session=db, job_id=job)
        writer.delta("The first half. ")
        writer.flush()
        seen = _events(db, job)[-1].seq
        writer.delta("The second half.")
        writer.flush()

        missed = stream.events_since(db, job, seen)
        assert stream.replay_text(missed) == "The second half."


class TestRetryIsOnePerPress:
    def _failed(self, db, scope, workspace, key):
        started = service.begin_generation(
            db, scope, workspace.id, text="Write it.", idempotency_key=key)
        service.mark_job_finished(db, started["job_id"], state="failed",
                                  error="the provider went away")
        return started["job_id"]

    def test_a_retry_gets_a_new_key_derived_from_the_old(self, db, scope,
                                                         workspace):
        job_id = self._failed(db, scope, workspace, "ws:key")
        assert service.retry_generation(db, scope, job_id)[
            "idempotency_key"] == "ws:key:retry2"

    def test_two_retries_are_two_keys_not_one(self, db, scope, workspace):
        job_id = self._failed(db, scope, workspace, "ws:key")
        first = service.retry_generation(db, scope, job_id)["idempotency_key"]
        service.begin_generation(db, scope, workspace.id, text="Write it.",
                                 idempotency_key=first)
        second = service.retry_generation(db, scope, job_id)["idempotency_key"]
        assert (first, second) == ("ws:key:retry2", "ws:key:retry3")

    def test_a_successful_generation_is_not_retryable(self, db, scope,
                                                      workspace):
        started = service.begin_generation(
            db, scope, workspace.id, text="Write it.", idempotency_key="ws:ok")
        service.mark_job_finished(db, started["job_id"], state="ready")
        with pytest.raises(repo.Invalid):
            service.retry_generation(db, scope, started["job_id"])

    def test_a_running_generation_is_not_retryable(self, db, scope, workspace,
                                                   job):
        with pytest.raises(repo.Invalid):
            service.retry_generation(db, scope, job)

    def test_another_tenants_generation_is_not_retryable(self, db, scope,
                                                         workspace):
        job_id = self._failed(db, scope, workspace, "ws:other")
        other = repo.Scope(tenant="somebody-else", user_id=None)
        with pytest.raises(repo.NotFound):
            service.retry_generation(db, other, job_id)


@pytest.fixture
def committed_job(scope):
    """A job whose rows other CONNECTIONS can see.

    The rest of this suite runs inside a rolled-back transaction, which is
    right for everything except `follow` — a reader opens its own session, and
    a session cannot read another's uncommitted work. So this one commits, and
    cleans up after itself.
    """
    from backend.db.engine import get_session
    from backend.models.playbook import PlaybookJob
    from tests.conftest import database_available

    if not database_available():
        pytest.skip("following a stream needs the platform database")

    with get_session() as session:
        ws = repo.create_workspace(session, scope, title="Streaming acceptance")
        job = PlaybookJob(workspace_id=ws.id, tenant=scope.tenant,
                          idempotency_key=f"follow-{ws.id}", state="drafting")
        session.add(job)
        session.commit()
        ids = (ws.id, job.id)
    yield ids[1]
    from sqlalchemy import text as sql

    with get_session() as session:
        session.execute(sql("DELETE FROM playbook_workspaces WHERE id = :i"),
                        {"i": ids[0]})
        session.commit()


def _committed_writer(job_id):
    from backend.db.engine import get_session

    return stream.Writer(session=get_session().__enter__(), job_id=job_id)


class TestFollowingTheLog:
    """`follow` is what the SSE route iterates. Tested here directly, because
    a bug in it shows up as a connection that never ends."""

    def test_it_replays_and_then_stops_at_done(self, committed_job):
        writer = _committed_writer(committed_job)
        writer.state("drafting")
        writer.delta("Some text.")
        writer.done({"version": 1})

        from backend.db.engine import get_session
        seen = list(stream.follow(get_session, committed_job, after=0,
                                  idle_timeout=10))
        assert [e["kind"] for e in seen] == ["state", "delta", "done"]

    def test_it_resumes_from_a_cursor(self, committed_job):
        writer = _committed_writer(committed_job)
        writer.state("drafting")
        writer.delta("Some text.")
        writer.done({"version": 1})

        from backend.db.engine import get_session
        seen = list(stream.follow(get_session, committed_job, after=1,
                                  idle_timeout=10))
        assert [e["kind"] for e in seen] == ["delta", "done"]

    def test_it_stops_at_an_error_too(self, committed_job):
        writer = _committed_writer(committed_job)
        writer.error("It failed.", category="server")

        from backend.db.engine import get_session
        seen = list(stream.follow(get_session, committed_job, after=0,
                                  idle_timeout=10))
        assert [e["kind"] for e in seen] == ["error"]
        assert seen[0]["data"]["message"] == "It failed."

    def test_a_job_that_ended_without_saying_so_does_not_hang_a_reader(
            self, scope, committed_job):
        """A worker that dies outright leaves no terminal event. The reader
        must end, and must say what happened, rather than holding the
        connection until it times out."""
        from backend.db.engine import get_session

        with get_session() as session:
            service.mark_job_finished(session, committed_job, state="failed",
                                      error="worker lost")
            session.commit()

        seen = list(stream.follow(get_session, committed_job, after=0,
                                  idle_timeout=10))
        assert [e["kind"] for e in seen] == ["error"]
        assert seen[0]["data"]["category"] == "worker_lost"

    def test_a_reader_that_disconnects_stops_reading(self, committed_job):
        writer = _committed_writer(committed_job)
        writer.state("drafting")

        from backend.db.engine import get_session
        seen = list(stream.follow(get_session, committed_job, after=0,
                                  idle_timeout=10,
                                  is_disconnected=lambda: True))
        assert seen == []

    def test_a_live_reader_sees_an_event_written_after_it_started(
            self, committed_job):
        """The tail, not the replay: the reader is already waiting when the
        event is written."""
        from backend.db.engine import get_session

        collected: list[dict] = []

        def read() -> None:
            for event in stream.follow(get_session, committed_job, after=0,
                                       idle_timeout=20):
                if event["kind"] != "ping":
                    collected.append(event)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        time.sleep(0.4)

        writer = _committed_writer(committed_job)
        writer.delta("Arriving late.")
        writer.done({"version": 1})
        reader.join(timeout=20)

        assert [e["kind"] for e in collected] == ["delta", "done"]
        assert stream.replay_text(
            [type("E", (), {"kind": "delta",
                            "data": {"text": collected[0]["data"]["text"]}})()]
        ) == "Arriving late."


class TestTheWireFormat:
    def test_an_event_carries_its_seq_so_a_reconnect_can_resume(self):
        line = stream.sse({"seq": 12, "kind": "delta", "data": {"text": "hi"}})
        assert line.startswith("id: 12\n")
        assert "event: delta\n" in line
        assert '"text":"hi"' in line
        assert line.endswith("\n\n")

    def test_a_heartbeat_is_a_comment_and_carries_nothing(self):
        assert stream.sse({"kind": "ping"}) == ": keep-alive\n\n"

    def test_a_newline_in_the_text_cannot_break_the_frame(self):
        """A raw newline in a `data:` line would end the event early and put
        the rest of the answer on the wire as garbage. JSON encoding is what
        prevents it, and this is the assertion that it is happening."""
        line = stream.sse({"seq": 1, "kind": "delta",
                           "data": {"text": "## Heading\n\nBody"}})
        assert line.count("\n\n") == 1
        assert "\\n\\n" in line
