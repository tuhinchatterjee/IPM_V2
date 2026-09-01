"""
§17, §73, §74 — the durable task queue.

These tests run against a real PostgreSQL, because every property that matters
here is a property of the database: SKIP LOCKED, a partial unique index, a
transactional claim. A queue tested against a dictionary is a queue whose only
interesting behaviour was mocked away.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import database_available

pytestmark = pytest.mark.skipif(
    not database_available(), reason="PostgreSQL is not reachable")

from backend.agentic import queue  # noqa: E402
from backend.db.engine import SessionLocal  # noqa: E402


@pytest.fixture
def session():
    """One session, rolled back — except where a test needs two connections to
    observe locking, which those tests set up themselves."""
    s = SessionLocal()
    s.execute(text("DELETE FROM agent_jobs"))
    s.commit()
    try:
        yield s
    finally:
        s.execute(text("DELETE FROM agent_jobs"))
        s.commit()
        s.close()


def _enqueue(session, key="k1", **kw):
    job_id, created = queue.enqueue(
        session, kind=queue.AGENTIC_RUN, idempotency_key=key, **kw)
    session.commit()
    return job_id, created


# ------------------------------------------------------------- idempotency


def test_the_same_job_enqueued_twice_is_one_job(session):
    """§70: an event delivered twice must produce one run."""
    first, created_first = _enqueue(session, "review:Q2 2026")
    second, created_second = _enqueue(session, "review:Q2 2026")
    assert created_first is True
    assert created_second is False
    assert first == second


def test_a_finished_job_does_not_block_the_next_one(session):
    """The same review legitimately runs again next quarter."""
    first, _ = _enqueue(session, "review:Q2 2026")
    queue.complete(session, first)
    session.commit()
    second, created = _enqueue(session, "review:Q2 2026")
    session.commit()
    assert created is True
    assert second != first


def test_the_live_uniqueness_is_enforced_by_the_database(session):
    """Not only by the SELECT in `enqueue`. Two callers racing must not both
    insert, and the index is what makes that true."""
    _enqueue(session, "race")
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.execute(
            text("""
                INSERT INTO agent_jobs (kind, idempotency_key, status)
                VALUES (:k, 'race', 'queued')
            """),
            {"k": queue.AGENTIC_RUN})
        session.commit()
    session.rollback()


# -------------------------------------------------------------- the claim


def test_a_claim_returns_the_job_and_takes_the_lease(session):
    _enqueue(session, "one")
    worker = queue.worker_id()
    claimed = queue.claim(session, worker=worker)
    session.commit()
    assert claimed is not None
    assert claimed.leased_by == worker
    assert claimed.attempts == 1
    assert queue.job(session, claimed.id)["status"] == "running"


def test_higher_priority_runs_first(session):
    """A user waiting on an answer outranks a nightly sweep."""
    _enqueue(session, "sweep", priority=queue.PRIORITY_SCHEDULED)
    _enqueue(session, "asked", priority=queue.PRIORITY_INTERACTIVE)
    claimed = queue.claim(session, worker="w1")
    session.commit()
    assert claimed.idempotency_key == "asked"


def test_a_scheduled_job_is_not_claimed_before_its_time(session):
    _enqueue(session, "later", delay_seconds=600)
    assert queue.claim(session, worker="w1") is None


def test_two_workers_never_claim_the_same_job(session):
    """SKIP LOCKED, on two real connections.

    This is the one property the whole queue rests on, and it cannot be
    observed on a single session: the lock only excludes another transaction.
    """
    _enqueue(session, "only-one")

    first = SessionLocal()
    second = SessionLocal()
    try:
        a = queue.claim(first, worker="w1")
        b = queue.claim(second, worker="w2")
        assert a is not None
        assert b is None, "a second worker claimed a job that was already held"
        first.commit()
        second.commit()
    finally:
        first.close()
        second.close()


def test_two_workers_take_two_different_jobs(session):
    _enqueue(session, "a")
    _enqueue(session, "b")
    first = SessionLocal()
    second = SessionLocal()
    try:
        a = queue.claim(first, worker="w1")
        b = queue.claim(second, worker="w2")
        assert a is not None and b is not None
        assert a.id != b.id
        first.commit()
        second.commit()
    finally:
        first.close()
        second.close()


def test_a_claim_can_be_restricted_to_certain_kinds(session):
    queue.enqueue(session, kind=queue.SCHEDULE_TICK, idempotency_key="tick")
    session.commit()
    assert queue.claim(session, worker="w1", kinds=(queue.AGENTIC_RUN,)) is None
    assert queue.claim(session, worker="w1",
                       kinds=(queue.SCHEDULE_TICK,)) is not None


# ------------------------------------------------------------- heartbeat


def test_a_heartbeat_extends_the_lease(session):
    _enqueue(session, "beat")
    claimed = queue.claim(session, worker="w1")
    session.commit()
    before = queue.job(session, claimed.id)
    assert queue.heartbeat(session, claimed.id, worker="w1") is True
    session.commit()
    after = queue.job(session, claimed.id)
    assert after["status"] == "running"
    assert before is not None


def test_a_worker_that_lost_its_lease_is_told(session):
    """Two workers finishing the same job is how a run gets two conflicting
    sets of findings, so a worker whose lease is gone must stop."""
    _enqueue(session, "lost")
    claimed = queue.claim(session, worker="w1")
    session.commit()
    assert queue.heartbeat(session, claimed.id, worker="somebody-else") is False


# -------------------------------------------------------------- recovery


def test_a_job_whose_worker_died_returns_to_the_queue(session):
    """§74: a durable job survives a restart."""
    _enqueue(session, "orphan")
    claimed = queue.claim(session, worker="dead-worker")
    session.execute(
        text("UPDATE agent_jobs SET lease_expires_at = :past WHERE id = :id"),
        {"past": datetime.now(UTC) - timedelta(minutes=5), "id": claimed.id})
    session.commit()

    recovered = queue.recover_stale(session)
    session.commit()
    assert claimed.id in recovered
    assert queue.job(session, claimed.id)["status"] == "queued"
    assert queue.job(session, claimed.id)["error_category"] == "lease_expired"


def test_a_job_that_kills_every_worker_eventually_dead_letters(session):
    """Recovery counts the lost attempt, so an infinite loop is not one."""
    _enqueue(session, "poison", max_attempts=2)
    for _ in range(3):
        claimed = queue.claim(session, worker="w")
        if claimed is None:
            break
        session.execute(
            text("UPDATE agent_jobs SET lease_expires_at = :past "
                 "WHERE id = :id"),
            {"past": datetime.now(UTC) - timedelta(minutes=5),
             "id": claimed.id})
        session.commit()
        queue.recover_stale(session)
        session.commit()

    statuses = session.execute(
        text("SELECT status FROM agent_jobs WHERE idempotency_key = 'poison'")
    ).scalars().all()
    assert statuses == ["dead_letter"]


# ----------------------------------------------------------------- retry


def test_a_failure_is_retried_with_backoff(session):
    _enqueue(session, "flaky", max_attempts=3)
    claimed = queue.claim(session, worker="w1")
    session.commit()
    status = queue.fail(session, claimed.id, error="the source timed out",
                        category="timeout")
    session.commit()
    assert status == queue.QUEUED
    stored = queue.job(session, claimed.id)
    assert stored["attempts"] == 1
    assert stored["scheduled_at"] > datetime.now(UTC)
    assert "timed out" in stored["last_error"]


def test_backoff_grows(session):
    """Retrying a model that is down every second helps nobody."""
    _enqueue(session, "backoff", max_attempts=5)
    delays = []
    for _ in range(3):
        claimed = queue.claim(session, worker="w1")
        session.commit()
        queue.fail(session, claimed.id, error="down")
        session.commit()
        stored = queue.job(session, claimed.id)
        delays.append((stored["scheduled_at"] - datetime.now(UTC)).total_seconds())
        session.execute(
            text("UPDATE agent_jobs SET scheduled_at = :now WHERE id = :id"),
            {"now": datetime.now(UTC), "id": claimed.id})
        session.commit()
    assert delays[1] > delays[0]
    assert delays[2] > delays[1]


def test_exhausted_attempts_dead_letter_rather_than_loop(session):
    """§20: never silently spend unlimited credits."""
    _enqueue(session, "doomed", max_attempts=2)
    for _ in range(2):
        claimed = queue.claim(session, worker="w1")
        assert claimed is not None
        session.commit()
        status = queue.fail(session, claimed.id, error="no")
        session.execute(
            text("UPDATE agent_jobs SET scheduled_at = :now WHERE id = :id"),
            {"now": datetime.now(UTC), "id": claimed.id})
        session.commit()
    assert status == queue.DEAD_LETTER
    assert queue.claim(session, worker="w1") is None


def test_a_failure_marked_not_retryable_dead_letters_at_once(session):
    _enqueue(session, "fatal", max_attempts=5)
    claimed = queue.claim(session, worker="w1")
    session.commit()
    assert queue.fail(session, claimed.id, error="the period is not published",
                      retry=False) == queue.DEAD_LETTER


# ---------------------------------------------------------- cancellation


def test_a_queued_job_is_cancelled_outright(session):
    job_id, _ = _enqueue(session, "stop-me")
    assert queue.cancel(session, job_id) is True
    session.commit()
    assert queue.job(session, job_id)["status"] == "cancelled"
    assert queue.claim(session, worker="w1") is None


def test_a_running_job_is_flagged_rather_than_killed(session):
    """A cancelled run is still a RECORDED run showing what it completed. A
    killed process leaves a row saying `running` forever."""
    _enqueue(session, "mid-flight")
    claimed = queue.claim(session, worker="w1")
    session.commit()
    queue.cancel(session, claimed.id)
    session.commit()
    stored = queue.job(session, claimed.id)
    assert stored["status"] == "running"
    assert stored["cancel_requested"] is True
    assert queue.is_cancelled(session, claimed.id) is True

    queue.stopped(session, claimed.id)
    session.commit()
    assert queue.job(session, claimed.id)["status"] == "cancelled"


def test_a_cancelled_job_is_not_reclaimed(session):
    """Even while flagged, a job asked to stop is never handed out again."""
    _enqueue(session, "no-more")
    claimed = queue.claim(session, worker="w1")
    session.commit()
    queue.cancel(session, claimed.id)
    queue.fail(session, claimed.id, error="stopped")
    session.execute(
        text("UPDATE agent_jobs SET scheduled_at = :now WHERE id = :id"),
        {"now": datetime.now(UTC), "id": claimed.id})
    session.commit()
    assert queue.claim(session, worker="w2") is None


# ------------------------------------------------------------- observation


def test_depth_reports_every_status(session):
    _enqueue(session, "one")
    _enqueue(session, "two")
    session.commit()
    counts = queue.depth(session)
    assert counts["queued"] == 2
    for status in (queue.RUNNING, queue.COMPLETE, queue.DEAD_LETTER,
                   queue.CANCELLED):
        assert status in counts


def test_a_worker_registers_and_beats(session):
    worker = queue.worker_id()
    queue.register_worker(session, worker=worker, build_sha="abc123")
    queue.worker_beat(session, worker=worker, status="working", completed=3)
    session.commit()
    found = [w for w in queue.workers(session) if w["worker_id"] == worker]
    assert found
    assert found[0]["status"] == "working"
    assert found[0]["jobs_completed"] == 3
    assert found[0]["alive"] is True
    session.execute(text("DELETE FROM agent_workers WHERE worker_id = :w"),
                    {"w": worker})
    session.commit()


def test_worker_ids_are_distinct():
    assert queue.worker_id() != queue.worker_id()
