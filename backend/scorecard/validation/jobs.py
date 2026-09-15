"""Validation runs that do not hold a request open.

§14.2 of the demo completion contract: "Long full-validation jobs should
return a job ID promptly with progress, partial results, cancellation/retry
and an explicit completed/failed status. The page remains usable. Increasing
a request timeout alone is not a fix."

Why a job and not just a faster run
-----------------------------------
The categories are much faster than they were — the slowest is fifteen
seconds rather than seventy-nine — but a browser holding a request open for
fifteen seconds is still a page that cannot be used, and a full run is a
minute. More to the point, a synchronous request gives a reader no way to
know whether it is working, no way to stop it, and nothing at all until it is
finished.

So a run becomes a job: started, polled, and readable WHILE it runs. Each
test that finishes is appended to the job's partial results, so the screen
fills in rather than waiting.

Deliberately in-process
-----------------------
A thread per job and a dictionary of them. No queue, no broker, no worker
pool: this is one analyst pressing a button on one installation, and a
message broker would be a second thing to run, a second thing to fail and a
second thing to explain. The trade is stated rather than hidden — a job does
not survive a backend restart, and `state` says so when one is lost.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

JOBS_VERSION = "retail-validation-jobs-1.0.0"

QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

#: How many finished jobs are kept. A reader reopening a screen wants the run
#: they just did; nobody is paging through last week's.
KEEP = 40


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Job:
    """One validation run, in flight or finished."""

    job_id: str
    model_id: str
    scope: str                    # "CATEGORY" or "FULL"
    categories: tuple[str, ...]
    period: str = ""
    state: str = QUEUED
    started_at: str = ""
    finished_at: str = ""
    total: int = 0
    done: int = 0
    current: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    run_key: str = ""
    body: dict[str, Any] | None = None
    owner: int | None = None
    _stop: threading.Event = field(default_factory=threading.Event,
                                   repr=False)

    @property
    def cancelling(self) -> bool:
        return self._stop.is_set()

    def to_dict(self, *, with_results: bool = True) -> dict[str, Any]:
        out = {
            "job_id": self.job_id, "model_id": self.model_id,
            "scope": self.scope, "categories": list(self.categories),
            "period": self.period, "state": self.state,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "total": self.total, "done": self.done,
            "progress": (round(self.done / self.total, 4)
                         if self.total else 0.0),
            "current": self.current, "error": self.error,
            "run_key": self.run_key,
            "jobs_version": JOBS_VERSION,
            "finished": self.state in (COMPLETED, FAILED, CANCELLED),
            # §14.2 asks for partial results, and this is what makes them
            # partial rather than absent: the count says how much of the run
            # these rows are, so a reader is never shown a tally that looks
            # complete and is not.
            #
            # A cancelled run is partial for exactly the same reason a running
            # one is — it stopped at test seven of forty-eight — and calling
            # it complete because it is finished would put a seven-test tally
            # on screen with nothing saying it is seven of forty-eight.
            "partial": (self.state == RUNNING
                        or (self.state == CANCELLED and self.done < self.total)),
        }
        if with_results:
            out["results"] = list(self.results)
        return out


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def get(job_id: str, *, owner: int | None = None) -> Job | None:
    with _LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        return None
    if owner is not None and job.owner is not None and job.owner != owner:
        return None
    return job


def listing(*, owner: int | None = None, limit: int = 20) -> list[Job]:
    with _LOCK:
        jobs = list(_JOBS.values())
    if owner is not None:
        jobs = [one for one in jobs if one.owner in (None, owner)]
    jobs.sort(key=lambda one: one.started_at, reverse=True)
    return jobs[:limit]


def cancel(job_id: str, *, owner: int | None = None) -> Job | None:
    """Ask a job to stop. It stops between tests, not inside one.

    A test that is already running finishes — killing a thread mid-frame
    would leave the partial results in a state nobody could describe. The job
    reports CANCELLED with whatever it had completed, which is honest and is
    what a reader who pressed Stop actually wants to see.
    """
    job = get(job_id, owner=owner)
    if job is None:
        return None
    if job.state in (COMPLETED, FAILED, CANCELLED):
        return job
    job._stop.set()
    return job


def _prune() -> None:
    with _LOCK:
        if len(_JOBS) <= KEEP:
            return
        finished = sorted(
            (one for one in _JOBS.values()
             if one.state in (COMPLETED, FAILED, CANCELLED)),
            key=lambda one: one.finished_at or one.started_at)
        for one in finished[:max(0, len(_JOBS) - KEEP)]:
            _JOBS.pop(one.job_id, None)


def start(*, model_id: str, categories: tuple[str, ...], scope: str,
          period: str = "", owner: int | None = None,
          record: Any = None, summarise: Any = None) -> Job:
    """Begin a run and return immediately with its id."""
    from backend.scorecard.validation import models as model_registry
    from backend.scorecard.validation import registry as test_registry
    from backend.scorecard.validation import runner

    made = model_registry.get(model_id)
    wanted = [test for category in categories
              for test in test_registry.in_category(category)]
    job = Job(job_id=f"SCVJ-{uuid.uuid4().hex[:12].upper()}",
              model_id=model_id, scope=scope, categories=tuple(categories),
              period=period, total=len(wanted), started_at=_now(),
              owner=owner)
    with _LOCK:
        _JOBS[job.job_id] = job
    _prune()

    def work() -> None:
        job.state = RUNNING
        results: list[Any] = []
        try:
            periods = (period,) if period else ()
            for test in wanted:
                if job.cancelling:
                    job.current = ""
                    # What it reached, packaged the same way a finished run
                    # is, so the screen renders a real tally rather than a
                    # fabricated one. NOT recorded: a governance record with
                    # a run key would claim a validation that did not happen.
                    if summarise is not None and results:
                        try:
                            job.body = summarise(made, results)
                        except Exception as problem:  # noqa: BLE001
                            job.error = (
                                "the run stopped, and the results it had "
                                f"reached could not be summarised: {problem}")
                    job.state = CANCELLED
                    job.finished_at = _now()
                    return
                job.current = test.test_id
                got = runner.run(test.test_id, made, periods=periods)
                results.append(got)
                job.results.append(
                    got.to_dict() if hasattr(got, "to_dict") else dict(got))
                job.done += 1
            job.current = ""
            if record is not None:
                # Recording is part of the job, not of the request that
                # started it: a reader who navigates away still gets their
                # run written to the history.
                try:
                    job.body = record(made, results)
                    job.run_key = str((job.body or {}).get("run_key") or "")
                except Exception as problem:  # noqa: BLE001
                    job.error = f"the run finished but was not recorded: {problem}"
            job.state = COMPLETED
        except Exception as problem:  # noqa: BLE001 - reported, never swallowed
            job.state = FAILED
            job.error = f"{type(problem).__name__}: {problem}"
            job.trace = traceback.format_exc()[-2000:]
        finally:
            if job.state == RUNNING:
                job.state = COMPLETED
            job.finished_at = _now()

    thread = threading.Thread(target=work, name=f"scv-{job.job_id}",
                              daemon=True)
    thread.start()
    return job
