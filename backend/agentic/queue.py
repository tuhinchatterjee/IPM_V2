"""
The durable task queue. §17.

Why Postgres and not Redis
--------------------------
§17 asks for a Postgres-backed queue rather than a Redis introduced solely for
this, and the reason is worth stating because it is not laziness. An agentic
job's *state* — which run it belongs to, which tasks completed, what it found —
is already in Postgres and has to be transactional with it. Putting the queue
somewhere else means a job can be acknowledged in Redis and lost in Postgres, or
the reverse, and every one of those windows is a run that silently vanished or
silently ran twice. `SELECT … FOR UPDATE SKIP LOCKED` gives exactly-once claim
semantics inside the same transaction that writes the run, at the cost of one
more service the deployment does not need.

How a job survives everything
-----------------------------
**Claim.** A worker takes one row with `FOR UPDATE SKIP LOCKED`, writes its own
id and a lease expiry, and commits. Two workers racing take two different rows —
`SKIP LOCKED` is what makes that true rather than hopeful.

**Heartbeat.** While it works the worker extends the lease. A job whose lease
has expired is one whose worker is gone.

**Recovery.** `recover_stale()` returns expired-lease jobs to `queued` and
increments the attempt count. A worker killed mid-run does not lose the work; it
loses the attempt.

**Retry.** Failures back off exponentially from the job's own base, and a job
that exhausts `max_attempts` goes to `dead_letter` rather than being retried
forever — §20's "never silently spend unlimited credits" applied to a queue.

**Cancellation.** `cancel()` sets a flag rather than killing anything. The
worker notices at its next checkpoint and stops cleanly, so a cancelled run is
still a *recorded* run showing what it completed. A killed process leaves a row
saying `running` forever.

**Idempotency.** A partial unique index allows one live job per (kind, key).
Enqueuing the same review twice returns the first job. The same review next
quarter has a different key and runs.

Swapping the engine out later
-----------------------------
§17 asks for an abstraction so Temporal or Celery can replace this without
changing agent contracts. That abstraction is the module surface: `enqueue`,
`claim`, `heartbeat`, `complete`, `fail`, `cancel`, `recover_stale`. Nothing
outside this module writes to `agent_jobs`, and nothing inside the agents knows
a queue exists — they are handed a job payload and a cancellation check.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

QUEUED = "queued"
RUNNING = "running"
COMPLETE = "complete"
FAILED = "failed"
DEAD_LETTER = "dead_letter"
CANCELLED = "cancelled"

LIVE: tuple[str, ...] = (QUEUED, RUNNING)
TERMINAL: tuple[str, ...] = (COMPLETE, DEAD_LETTER, CANCELLED)

#: Job kinds.
AGENTIC_RUN = "agentic_run"
PROACTIVE_REVIEW = "proactive_review"
SCHEDULE_TICK = "schedule_tick"

#: How long a claim is good for before a sweep may take the job back. Long
#: enough that a slow scan does not lose its own job; short enough that a dead
#: worker's job is picked up inside a demonstration.
LEASE_SECONDS = 120

#: Backoff is `base * 2 ** (attempts - 1)`, capped. A model that is briefly
#: unavailable recovers on the second attempt; one that is down stays down, and
#: retrying it every second helps nobody.
BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 300

#: A user waiting for an answer outranks a nightly sweep.
PRIORITY_INTERACTIVE = 100
PRIORITY_EVENT = 50
PRIORITY_SCHEDULED = 10


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# What a worker receives
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """One claimed unit of work."""

    id: int
    kind: str
    idempotency_key: str
    payload: dict[str, Any]
    run_id: int | None
    attempts: int
    max_attempts: int
    priority: int
    timeout_seconds: int
    leased_by: str
    lease_expires_at: datetime | None

    @property
    def final_attempt(self) -> bool:
        return self.attempts >= self.max_attempts

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "idempotency_key": self.idempotency_key,
            "run_id": self.run_id,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "priority": self.priority,
            "leased_by": self.leased_by,
        }


def worker_id() -> str:
    """A stable-enough identity for one worker process.

    Host plus pid plus a short random suffix: two containers on one host have
    different pids, two processes restarted in sequence have different suffixes,
    and a lease can always be attributed to a process that actually existed.
    """
    return (f"{socket.gethostname()[:24]}-{os.getpid()}-"
            f"{uuid.uuid4().hex[:6]}")


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def enqueue(session: Any, *, kind: str, idempotency_key: str,
            payload: dict[str, Any] | None = None, run_id: int | None = None,
            priority: int = PRIORITY_EVENT, max_attempts: int = 3,
            timeout_seconds: int = 900,
            delay_seconds: int = 0) -> tuple[int, bool]:
    """Add a job, or find the live one that is already there.

    Returns `(job_id, created)`. `created` is False when an identical job was
    already queued or running — which is the whole point: an event delivered
    twice must produce one run, and the second delivery finds the first rather
    than being told it failed.

    The check is a SELECT before the INSERT *and* a partial unique index behind
    it. The SELECT gives a useful answer; the index is what makes it true under
    two workers enqueuing at the same instant.
    """
    existing = session.execute(
        text("""
            SELECT id FROM agent_jobs
             WHERE kind = :kind AND idempotency_key = :key
               AND status IN ('queued', 'running')
             LIMIT 1
        """),
        {"kind": kind, "key": idempotency_key},
    ).scalar()
    if existing is not None:
        logger.info("job already live: %s/%s → %s", kind, idempotency_key,
                    existing)
        return int(existing), False

    scheduled = _now() + timedelta(seconds=max(0, delay_seconds))
    from sqlalchemy.exc import IntegrityError

    try:
        with session.begin_nested():
            job_id = session.execute(
                text("""
                    INSERT INTO agent_jobs
                        (kind, idempotency_key, payload, run_id, status,
                         priority, scheduled_at, max_attempts,
                         timeout_seconds)
                    VALUES
                        (:kind, :key, CAST(:payload AS jsonb), :run_id,
                         'queued', :priority, :scheduled, :max_attempts,
                         :timeout)
                    RETURNING id
                """),
                {"kind": kind, "key": idempotency_key,
                 "payload": _json(payload or {}), "run_id": run_id,
                 "priority": priority, "scheduled": scheduled,
                 "max_attempts": max_attempts,
                 "timeout": timeout_seconds},
            ).scalar_one()
    except IntegrityError:
        # The partial unique index fired: another caller inserted the same live
        # job between our SELECT and our INSERT. Its job is as good as ours.
        found = session.execute(
            text("""
                SELECT id FROM agent_jobs
                 WHERE kind = :kind AND idempotency_key = :key
                   AND status IN ('queued', 'running')
                 LIMIT 1
            """),
            {"kind": kind, "key": idempotency_key},
        ).scalar()
        if found is None:
            raise
        return int(found), False

    return int(job_id), True


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


def claim(session: Any, *, worker: str,
          kinds: tuple[str, ...] = ()) -> Job | None:
    """Take one job, exclusively.

    `FOR UPDATE SKIP LOCKED` is the entire concurrency design. Without it, two
    workers reading the same top-priority row both believe they own it, and the
    second's UPDATE quietly wins — which is a duplicated run that nothing in the
    system can detect afterwards, because both wrote plausible rows.
    """
    filters = "AND kind = ANY(:kinds)" if kinds else ""
    row = session.execute(
        text(f"""
            SELECT id, kind, idempotency_key, payload, run_id, attempts,
                   max_attempts, priority, timeout_seconds
              FROM agent_jobs
             WHERE status = 'queued'
               AND scheduled_at <= :now
               AND cancel_requested = false
               {filters}
             ORDER BY priority DESC, scheduled_at ASC, id ASC
             LIMIT 1
             FOR UPDATE SKIP LOCKED
        """),
        {"now": _now(), **({"kinds": list(kinds)} if kinds else {})},
    ).mappings().first()

    if row is None:
        return None

    expires = _now() + timedelta(seconds=LEASE_SECONDS)
    session.execute(
        text("""
            UPDATE agent_jobs
               SET status = 'running',
                   attempts = attempts + 1,
                   leased_by = :worker,
                   leased_at = :now,
                   lease_expires_at = :expires,
                   heartbeat_at = :now,
                   updated_at = :now
             WHERE id = :id
        """),
        {"id": row["id"], "worker": worker, "now": _now(), "expires": expires},
    )

    return Job(
        id=int(row["id"]), kind=str(row["kind"]),
        idempotency_key=str(row["idempotency_key"]),
        payload=dict(row["payload"] or {}),
        run_id=row["run_id"], attempts=int(row["attempts"]) + 1,
        max_attempts=int(row["max_attempts"]), priority=int(row["priority"]),
        timeout_seconds=int(row["timeout_seconds"]),
        leased_by=worker, lease_expires_at=expires)


def heartbeat(session: Any, job_id: int, *, worker: str) -> bool:
    """Extend the lease. Returns False when this worker no longer holds it.

    A worker that finds its lease gone must stop: something has decided it was
    dead and given the job to somebody else, and two workers finishing the same
    job is how a run gets two conflicting sets of findings.
    """
    expires = _now() + timedelta(seconds=LEASE_SECONDS)
    updated = session.execute(
        text("""
            UPDATE agent_jobs
               SET heartbeat_at = :now, lease_expires_at = :expires,
                   updated_at = :now
             WHERE id = :id AND leased_by = :worker AND status = 'running'
        """),
        {"id": job_id, "worker": worker, "now": _now(), "expires": expires},
    ).rowcount
    return bool(updated)


def is_cancelled(session: Any, job_id: int) -> bool:
    """Has somebody asked for this to stop?

    Checked at each checkpoint rather than acted on by a signal, so the run
    finishes the task it is in the middle of, writes what it has, and stops —
    leaving a record of what was completed rather than a truncated transaction.
    """
    return bool(session.execute(
        text("SELECT cancel_requested FROM agent_jobs WHERE id = :id"),
        {"id": job_id},
    ).scalar())


# ---------------------------------------------------------------------------
# Finish
# ---------------------------------------------------------------------------


def complete(session: Any, job_id: int, *, worker: str = "") -> None:
    session.execute(
        text("""
            UPDATE agent_jobs
               SET status = 'complete', finished_at = :now, updated_at = :now,
                   leased_by = '', lease_expires_at = NULL
             WHERE id = :id
        """),
        {"id": job_id, "now": _now()},
    )


def fail(session: Any, job_id: int, *, error: str, category: str = "",
         retry: bool = True) -> str:
    """Record a failure and decide what happens next.

    Returns the status the job ended in: `queued` when it will be retried,
    `dead_letter` when its attempts are exhausted.

    A dead letter is not a swept-under-the-carpet failure — it is a job that
    stopped costing money and left a row saying exactly why, which is what §20
    asks for. Something has to look at it; nothing has to keep paying for it.
    """
    row = session.execute(
        text("SELECT attempts, max_attempts FROM agent_jobs WHERE id = :id"),
        {"id": job_id},
    ).mappings().first()
    if row is None:
        return DEAD_LETTER

    attempts = int(row["attempts"])
    exhausted = not retry or attempts >= int(row["max_attempts"])
    if exhausted:
        session.execute(
            text("""
                UPDATE agent_jobs
                   SET status = 'dead_letter', last_error = :error,
                       error_category = :category, finished_at = :now,
                       updated_at = :now, leased_by = '',
                       lease_expires_at = NULL
                 WHERE id = :id
            """),
            {"id": job_id, "error": error[:2000], "category": category[:48],
             "now": _now()},
        )
        logger.warning("job %s dead-lettered after %s attempts: %s",
                       job_id, attempts, error[:200])
        return DEAD_LETTER

    delay = min(BACKOFF_CAP_SECONDS,
                BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)))
    session.execute(
        text("""
            UPDATE agent_jobs
               SET status = 'queued', last_error = :error,
                   error_category = :category, scheduled_at = :next,
                   updated_at = :now, leased_by = '',
                   lease_expires_at = NULL
             WHERE id = :id
        """),
        {"id": job_id, "error": error[:2000], "category": category[:48],
         "next": _now() + timedelta(seconds=delay), "now": _now()},
    )
    logger.info("job %s will retry in %ss (attempt %s)", job_id, delay,
                attempts)
    return QUEUED


def cancel(session: Any, job_id: int) -> bool:
    """Ask a job to stop.

    A queued job is cancelled outright; a running one is flagged and stops at
    its next checkpoint. Nothing here kills a process — see the module note.
    """
    updated = session.execute(
        text("""
            UPDATE agent_jobs
               SET cancel_requested = true,
                   status = CASE WHEN status = 'queued' THEN 'cancelled'
                                 ELSE status END,
                   finished_at = CASE WHEN status = 'queued' THEN :now
                                      ELSE finished_at END,
                   updated_at = :now
             WHERE id = :id AND status IN ('queued', 'running')
        """),
        {"id": job_id, "now": _now()},
    ).rowcount
    return bool(updated)


def stopped(session: Any, job_id: int) -> None:
    """Mark a running job as cancelled, once its worker has actually stopped."""
    session.execute(
        text("""
            UPDATE agent_jobs
               SET status = 'cancelled', finished_at = :now, updated_at = :now,
                   leased_by = '', lease_expires_at = NULL
             WHERE id = :id
        """),
        {"id": job_id, "now": _now()},
    )


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def recover_stale(session: Any) -> list[int]:
    """Return jobs whose worker has gone to the queue.

    This is what makes "durable job survives restart" (§74) true. A container
    that stops mid-run leaves a `running` row with a lease that expires; the
    next sweep re-queues it, and the attempt it lost is counted so a job that
    kills its worker every time still dead-letters rather than looping forever.
    """
    rows = session.execute(
        text("""
            UPDATE agent_jobs
               SET status = CASE
                       WHEN attempts >= max_attempts THEN 'dead_letter'
                       ELSE 'queued' END,
                   last_error = CASE
                       WHEN last_error = '' THEN
                           'The worker holding this job stopped responding.'
                       ELSE last_error END,
                   error_category = CASE
                       WHEN error_category = '' THEN 'lease_expired'
                       ELSE error_category END,
                   finished_at = CASE
                       WHEN attempts >= max_attempts THEN :now
                       ELSE finished_at END,
                   leased_by = '', lease_expires_at = NULL,
                   updated_at = :now
             WHERE status = 'running'
               AND lease_expires_at IS NOT NULL
               AND lease_expires_at < :now
         RETURNING id
        """),
        {"now": _now()},
    ).scalars().all()
    if rows:
        logger.warning("recovered %s stale job(s): %s", len(rows), list(rows))
    return [int(r) for r in rows]


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


def depth(session: Any) -> dict[str, int]:
    """How much work is waiting, by status. Read by the health endpoint."""
    rows = session.execute(
        text("SELECT status, count(*) AS n FROM agent_jobs GROUP BY status"),
    ).mappings().all()
    found = {str(r["status"]): int(r["n"]) for r in rows}
    return {status: found.get(status, 0) for status in
            (QUEUED, RUNNING, COMPLETE, DEAD_LETTER, CANCELLED)}


def job(session: Any, job_id: int) -> dict[str, Any] | None:
    row = session.execute(
        text("""
            SELECT id, kind, idempotency_key, run_id, status, priority,
                   attempts, max_attempts, last_error, error_category,
                   leased_by, cancel_requested, scheduled_at, created_at,
                   finished_at
              FROM agent_jobs WHERE id = :id
        """),
        {"id": job_id},
    ).mappings().first()
    return dict(row) if row else None


def register_worker(session: Any, *, worker: str, build_sha: str = "") -> None:
    session.execute(
        text("""
            INSERT INTO agent_workers
                (worker_id, hostname, status, build_sha, started_at,
                 heartbeat_at)
            VALUES (:id, :host, 'idle', :sha, :now, :now)
            ON CONFLICT (worker_id) DO UPDATE
               SET status = 'idle', heartbeat_at = :now
        """),
        {"id": worker, "host": socket.gethostname()[:120], "sha": build_sha,
         "now": _now()},
    )


def worker_beat(session: Any, *, worker: str, status: str = "idle",
                job_id: int | None = None, completed: int = 0,
                failed: int = 0) -> None:
    session.execute(
        text("""
            UPDATE agent_workers
               SET status = :status, current_job_id = :job,
                   jobs_completed = :completed, jobs_failed = :failed,
                   heartbeat_at = :now
             WHERE worker_id = :id
        """),
        {"id": worker, "status": status, "job": job_id, "completed": completed,
         "failed": failed, "now": _now()},
    )


def workers(session: Any, *, alive_within_seconds: int = 90
            ) -> list[dict[str, Any]]:
    cutoff = _now() - timedelta(seconds=alive_within_seconds)
    rows = session.execute(
        text("""
            SELECT worker_id, hostname, status, current_job_id,
                   jobs_completed, jobs_failed, build_sha, started_at,
                   heartbeat_at,
                   (heartbeat_at >= :cutoff) AS alive
              FROM agent_workers
             ORDER BY heartbeat_at DESC
        """),
        {"cutoff": cutoff},
    ).mappings().all()
    return [dict(r) for r in rows]


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


__all__ = [
    "AGENTIC_RUN",
    "BACKOFF_BASE_SECONDS",
    "CANCELLED",
    "COMPLETE",
    "DEAD_LETTER",
    "FAILED",
    "LEASE_SECONDS",
    "LIVE",
    "PRIORITY_EVENT",
    "PRIORITY_INTERACTIVE",
    "PRIORITY_SCHEDULED",
    "PROACTIVE_REVIEW",
    "QUEUED",
    "RUNNING",
    "SCHEDULE_TICK",
    "TERMINAL",
    "Job",
    "cancel",
    "claim",
    "complete",
    "depth",
    "enqueue",
    "fail",
    "heartbeat",
    "is_cancelled",
    "job",
    "recover_stale",
    "register_worker",
    "stopped",
    "worker_beat",
    "worker_id",
    "workers",
]
