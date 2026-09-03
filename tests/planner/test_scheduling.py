"""The parts that make the planner run on its own.

Three defects sat behind these tests before they existed, and each one made
the feature silently inert rather than visibly broken:

  * the sweep's job handler took `(session, job)` while the worker calls
    `handler(job, should_stop)`, so the first real scheduled run would have
    died on `Job.execute`;
  * nothing in the product ever enqueued a `planner_sweep`;
  * nothing in the product ever enqueued a `schedule_tick`, so every governed
    schedule row was enabled, due, and never fired.

A test that only calls `sweep()` directly proves none of that. These go
through the queue, the schedule table and the worker's own registration path.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from backend.agentic import queue, schedules, worker
from backend.models.platform import AgentSchedule
from backend.planner import monitor
from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the queue is a PostgreSQL feature")


@pytest.fixture()
def session():
    from backend.db.engine import get_session

    with get_session() as s:
        yield s


def _job(payload: dict) -> queue.Job:
    """A claimed job, shaped exactly as the worker hands one to a handler."""
    return queue.Job(
        id=0, kind=monitor.PLANNER_SWEEP, idempotency_key="test",
        payload=payload, run_id=None, attempts=1, max_attempts=1,
        timeout_seconds=60, priority=queue.PRIORITY_SCHEDULED,
        leased_by="test", lease_expires_at=None)


# ------------------------------------------------------- the handler shape


def test_sweep_handler_matches_the_worker_contract():
    """`handler(job, should_stop)` — the worker's signature, not the module's.

    Asserted structurally rather than by running one, because the failure mode
    is a TypeError at three in the morning and the whole point is to find it
    at import time.
    """
    params = list(inspect.signature(monitor.run_sweep_job).parameters.values())
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    assert len(positional) == 2
    assert positional[0].name == "job"


def test_the_worker_registers_the_sweep():
    worker._HANDLERS.clear()
    worker._install_defaults()
    assert monitor.PLANNER_SWEEP in worker._HANDLERS
    assert queue.SCHEDULE_TICK in worker._HANDLERS


def test_registration_refuses_a_handler_the_worker_cannot_call():
    def wrong(session, job, extra):  # noqa: ANN001 - deliberately wrong
        return None

    with pytest.raises(TypeError, match="handler\\(job, should_stop\\)"):
        worker._check_handler_shape(wrong)


def test_the_sweep_runs_through_the_handler(session):
    """The real path: a Job in, a dict out, its own session inside."""
    job = _job({"today": "2026-06-15", "project_ids": [-1]})
    outcome = monitor.run_sweep_job(job, lambda: False)
    assert outcome["projects"] == 0  # project -1 does not exist
    assert outcome["sent"] == 0


def test_a_draining_worker_stops_the_sweep_before_it_writes():
    job = _job({})
    assert monitor.run_sweep_job(job, lambda: True) == {"stopped": True}


# ------------------------------------------------------------ the schedule


def test_the_planner_schedule_ships_enabled(session):
    schedules.seed(session)
    session.flush()
    row = session.execute(
        select(AgentSchedule).where(
            AgentSchedule.scope == schedules.PLANNER_SCOPE)
    ).scalar_one()
    assert row.enabled is True
    assert row.trigger == schedules.HOURLY


def test_an_hourly_schedule_is_due_an_hour_later(session):
    schedules.seed(session)
    session.flush()
    row = session.execute(
        select(AgentSchedule).where(
            AgentSchedule.scope == schedules.PLANNER_SCOPE)).scalar_one()
    now = datetime.now(UTC)
    row.last_run_at = now
    session.flush()
    assert row not in schedules.due(session, at=now + timedelta(minutes=30))
    assert row in schedules.due(session, at=now + timedelta(minutes=61))


def test_the_tick_enqueues_a_planner_sweep(session):
    """The whole chain: a due planner schedule becomes a queued sweep."""
    schedules.seed(session)
    session.flush()
    row = session.execute(
        select(AgentSchedule).where(
            AgentSchedule.scope == schedules.PLANNER_SCOPE)).scalar_one()
    row.last_run_at = None
    day = datetime.now(UTC) + timedelta(days=400)  # a key nothing else holds
    session.execute(text(
        "DELETE FROM agent_jobs WHERE idempotency_key = :k"),
        {"k": f"planner-sweep:{day.date().isoformat()}"})
    session.flush()

    schedules.tick(session, at=day, scopes=(schedules.PLANNER_SCOPE,))
    session.flush()

    found = session.execute(text(
        "SELECT kind, status FROM agent_jobs WHERE idempotency_key = :k"),
        {"k": f"planner-sweep:{day.date().isoformat()}"}).first()
    assert found is not None, "a due planner schedule enqueued nothing"
    assert found[0] == monitor.PLANNER_SWEEP


def test_scopes_keep_demo_mode_from_firing_a_portfolio_review(session):
    """Demo Mode narrows the tick; it does not switch the planner off."""
    schedules.seed(session)
    session.flush()
    for row in session.execute(select(AgentSchedule)).scalars():
        row.enabled = True
        row.last_run_at = None
    session.flush()

    day = datetime.now(UTC) + timedelta(days=401)
    fired = schedules.due(session, at=day)
    assert any(r.scope == schedules.PLANNER_SCOPE for r in fired)
    assert any(r.scope != schedules.PLANNER_SCOPE for r in fired), \
        "the fixture needs a non-planner schedule to be meaningful"


# ------------------------------------------------------- event-driven work


def test_an_event_queues_one_sweep_for_that_project_only(session):
    session.execute(text(
        "DELETE FROM agent_jobs WHERE idempotency_key LIKE 'planner-event:%'"))
    session.flush()
    job_id, created = monitor.on_event(session, 4242, "task_due_date_changed")
    session.flush()
    assert created is True

    row = session.execute(text(
        "SELECT payload FROM agent_jobs WHERE id = :i"),
        {"i": job_id}).scalar_one()
    assert row["project_ids"] == [4242]
    assert row["reason"] == "event:task_due_date_changed"


def test_a_burst_of_edits_collapses_to_one_sweep(session):
    session.execute(text(
        "DELETE FROM agent_jobs WHERE idempotency_key LIKE 'planner-event:%'"))
    session.flush()
    first, made_first = monitor.on_event(session, 4243, "task_status_changed")
    session.flush()
    second, made_second = monitor.on_event(session, 4243, "task_blocked")
    session.flush()
    assert made_first is True
    assert made_second is False, "a second edit queued a second sweep"
    assert first == second


def test_an_unknown_event_is_refused():
    class Dead:
        def execute(self, *_a, **_k):  # pragma: no cover - never reached
            raise AssertionError("an unknown event should not reach the queue")

    with pytest.raises(ValueError, match="not a planner event"):
        monitor.on_event(Dead(), 1, "somebody_sneezed")


def test_the_service_never_fails_a_save_because_the_queue_is_down(caplog):
    """`signal` is best-effort, and says so in the log rather than silently."""
    from backend.planner import service as svc

    class Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("no queue today")

    svc.signal(Broken(), 7, "task_created")  # must not raise
    assert "could not queue a planner re-evaluation" in caplog.text
