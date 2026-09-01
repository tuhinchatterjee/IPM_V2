"""
Is this worker actually working? §18.

The container's health check. It has no HTTP surface — a worker serves nothing —
so a port probe is not available, and would not answer the right question
anyway: a process that is running but has stopped claiming jobs is not healthy,
and a listening socket would call it healthy.

What this checks instead:

1. The database is reachable. A worker that cannot read the queue cannot work,
   whatever else is true of it.
2. This host's worker row has beaten recently. `queue.register_worker` writes it
   at start-up and `worker_beat` updates it on every loop, so a stale beat means
   the loop has stopped even though the process has not.

Exit 0 healthy, exit 1 not. Deliberately no output on success: a health check
that prints on every interval fills a log with the fact that nothing is wrong.
"""

from __future__ import annotations

import socket
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

#: How long a worker may go without beating before Docker restarts it. Three
#: idle loops plus slack — `worker.IDLE_SLEEP_SECONDS` is 2s and a beat happens
#: every loop, so a minute of silence means something is genuinely stuck.
STALE_AFTER_SECONDS = 120


def last_beat(session: Any, *, worker: str) -> datetime | None:
    """The most recent heartbeat from a worker whose id starts with `worker`.

    A prefix, because `queue.worker_id()` is host-pid-suffix and the health
    check knows only the host: a container restarted five times has five rows
    and the live one is whichever beat last.
    """
    from sqlalchemy import text

    return session.execute(
        text("""
            SELECT max(heartbeat_at) FROM agent_workers
             WHERE worker_id LIKE :prefix AND status <> 'stopped'
        """),
        {"prefix": f"{worker}%"},
    ).scalar()


def healthy(session: Any, *, worker: str) -> bool:
    """Whether this worker's loop is still beating.

    Separated from `main` so the rule can be tested. A health check whose only
    entry point reads the hostname and opens its own connection is a rule that
    is exercised for the first time in production.
    """
    beat = last_beat(session, worker=worker)
    if beat is None:
        return False
    return beat >= datetime.now(UTC) - timedelta(seconds=STALE_AFTER_SECONDS)


def main() -> int:
    try:
        from backend.db.engine import get_session
    except Exception as exc:  # noqa: BLE001
        print(f"worker health: cannot import the database layer: {exc}",
              file=sys.stderr)
        return 1

    host = socket.gethostname()[:24]

    try:
        with get_session() as session:
            beat = last_beat(session, worker=host)
    except Exception as exc:  # noqa: BLE001
        print(f"worker health: the database is not reachable: {exc}",
              file=sys.stderr)
        return 1

    if beat is None:
        # Starting up: the row is written once the loop begins. Docker's
        # start_period covers this window.
        print("worker health: no heartbeat recorded yet", file=sys.stderr)
        return 1

    if beat < datetime.now(UTC) - timedelta(seconds=STALE_AFTER_SECONDS):
        print(f"worker health: last heartbeat {beat.isoformat()} is older than "
              f"{STALE_AFTER_SECONDS}s", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - a container entry point
    raise SystemExit(main())
