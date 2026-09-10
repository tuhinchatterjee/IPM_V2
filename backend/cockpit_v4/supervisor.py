"""
The independent supervisor: deadlines and abandoned runs.

Separate from the worker on purpose. A cooperative deadline check inside the
orchestration loop is only reached when the loop is running; a worker blocked
on a socket, or one whose process died, never reaches it. So this polls the
store, settles what the worker cannot, and is the reason a browser stops
spinning when a worker disappears.

It never replays work. An abandoned run becomes INTERRUPTED with its last
operation and its preserved artifacts, and a retry is a new explicit run.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4 import events as ev
from backend.cockpit_v4 import states as st
from backend.cockpit_v4.run_store import LeaseLost, RunStore, TerminalAlready

logger = logging.getLogger(__name__)


@dataclass
class Supervisor:
    store: RunStore
    poll_seconds: float = 2.0
    lease_stale_seconds: float = 10.0
    stop_event: threading.Event = field(default_factory=threading.Event)

    def serve_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.sweep()
            except Exception:  # noqa: BLE001
                logger.exception("V4 supervisor sweep failed")
            self.stop_event.wait(self.poll_seconds)

    def stop(self) -> None:
        self.stop_event.set()

    def sweep(self) -> dict[str, int]:
        expired = self._settle_expired()
        interrupted = self._settle_abandoned()
        return {"expired": expired, "interrupted": interrupted}

    def _settle_expired(self) -> int:
        settled = 0
        for record in self.store.expiring_runs():
            if self._terminate(
                    record, st.EXPIRED, st.DEADLINE_EXPIRED, ev.RUN_EXPIRED,
                    f"The {record.mode} deadline passed while "
                    f"{record.operation or 'this request was working'}."):
                settled += 1
        return settled

    def _settle_abandoned(self) -> int:
        settled = 0
        for record in self.store.stale_runs(
                stale_seconds=self.lease_stale_seconds):
            if self._terminate(
                    record, st.INTERRUPTED, st.WORKER_LOST,
                    ev.RUN_INTERRUPTED,
                    ("The process handling this request stopped responding. "
                     "Nothing was replayed: a paid call or an executed query "
                     "may already have happened, and repeating it "
                     "automatically would spend it twice. Any results "
                     "already produced are preserved.")):
                settled += 1
        return settled

    def _terminate(self, record: Any, state: str, code: str,
                   event_type: str, message: str) -> bool:
        try:
            self.store.update_state(
                record.run_id, expect_version=record.version, state=state,
                error_code=code, terminal=True)
        except (LeaseLost, TerminalAlready):
            # The worker settled it first. That outcome stands.
            return False
        except Exception:  # noqa: BLE001
            logger.exception("V4 supervisor could not settle %s",
                             record.run_id)
            return False
        emitter = ev.Emitter(self.store, record.run_id,
                             started_monotonic=time.monotonic())
        emitter.append(event_type, stage="publishing", operation="supervisor",
                       status=ev.STATUS_FAILED, public_message=message)
        return True


__all__ = ["Supervisor"]
