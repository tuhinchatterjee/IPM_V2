"""
Agentic health, as a governed state rather than a feeling. §135.

    "agentic runs genuinely execute; the agent worker is healthy and
     observable"

Why this is one object with four state machines
------------------------------------------------
Because "is the agentic layer working?" has four different answers and the
question is usually asked when three of them are fine. A healthy worker with a
stalled queue looks healthy. A live queue with a disabled scheduler looks live.
A completed review of last quarter's data looks completed. Reporting one
number, or one colour, hides whichever of the four is the problem — which is
the one somebody is trying to find.

So there are four independent states and thirty fields, and `sentence()` names
the worst one rather than averaging them.

The states that mean "nobody looked"
--------------------------------------
NOT_RUN, STALLED, DISABLED and STALE all mean the same thing to a reader:
nothing current has been checked. They are kept apart because the fix differs
— start a review, restart a worker, enable a schedule, rerun against current
data — and a single "unavailable" state would leave somebody guessing which.

Nothing here is inferred from an empty table
----------------------------------------------
§136's last line, and it applies to the whole module: a queue with no jobs is
IDLE, not HEALTHY; a case table with no rows is not evidence that a review
found nothing. Every state below is read from a record that something
happened, and where no such record exists the state says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

HEALTH_VERSION = "1.0.0"

# ------------------------------------------------------------ worker state
STARTING = "STARTING"
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
OFFLINE = "OFFLINE"
DRAINING = "DRAINING"

WORKER_STATES: tuple[str, ...] = (STARTING, HEALTHY, DEGRADED, OFFLINE,
                                  DRAINING)

# ------------------------------------------------------------- queue state
IDLE = "IDLE"
ACTIVE = "ACTIVE"
BACKLOGGED = "BACKLOGGED"
STALLED = "STALLED"

QUEUE_STATES: tuple[str, ...] = (IDLE, ACTIVE, BACKLOGGED, STALLED)

# --------------------------------------------------------- scheduler state
ENABLED = "ENABLED"
DISABLED = "DISABLED"
LATE = "LATE"
SCHEDULER_FAILED = "FAILED"

SCHEDULER_STATES: tuple[str, ...] = (ENABLED, DISABLED, LATE,
                                     SCHEDULER_FAILED)

# ------------------------------------------------------ latest review state
NOT_RUN = "NOT_RUN"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
VALIDATING = "VALIDATING"
COMPLETED_WITH_CASES = "COMPLETED_WITH_CASES"
COMPLETED_NO_CASES = "COMPLETED_NO_CASES"
REVIEW_FAILED = "FAILED"
STALE = "STALE"
CANCELLED = "CANCELLED"

REVIEW_STATES: tuple[str, ...] = (NOT_RUN, QUEUED, RUNNING, VALIDATING,
                                  COMPLETED_WITH_CASES, COMPLETED_NO_CASES,
                                  REVIEW_FAILED, STALE, CANCELLED)

#: The two states where a review actually stands behind what the Cockpit says.
#: Everything else means nothing current has been checked, whatever the case
#: table contains.
REVIEWED: frozenset[str] = frozenset({COMPLETED_WITH_CASES,
                                       COMPLETED_NO_CASES})

#: What each review state means to a reader, and what to do about it. Kept
#: apart because the fix differs, and a single "unavailable" would leave
#: somebody guessing which.
REVIEW_MEANS: dict[str, tuple[str, str]] = {
    NOT_RUN: ("No current portfolio review has been completed.",
              "Run a portfolio review."),
    QUEUED: ("A portfolio review is waiting for a worker.", ""),
    RUNNING: ("CreditProbe is reviewing the current portfolio.", ""),
    VALIDATING: ("The review has finished and its findings are being "
                 "validated.", ""),
    COMPLETED_WITH_CASES: ("A validated review found governed thresholds "
                           "requiring attention.", ""),
    COMPLETED_NO_CASES: ("A validated review completed and found no governed "
                         "thresholds requiring attention.", ""),
    REVIEW_FAILED: ("The portfolio review could not complete.",
                    "Retry it, or open the run to see what stopped it."),
    STALE: ("The last review no longer describes the current data, build or "
            "policy.", "Rerun it against what is running now."),
    CANCELLED: ("The portfolio review was cancelled before it finished.",
                "Run it again."),
}

#: Worker heartbeat older than this and the worker is not running.
OFFLINE_AFTER_SECONDS = 120
#: Younger than this after a restart and it is still starting.
STARTING_WITHIN_SECONDS = 30
#: Queue depth above which the backlog is worth reporting.
BACKLOG_AT = 25
#: A queued job older than this with a healthy worker means something is
#: stuck rather than busy.
STALLED_AFTER_SECONDS = 900


@dataclass
class Health:
    """§135's state, field for field."""

    worker_state: str = OFFLINE
    queue_state: str = IDLE
    scheduler_state: str = DISABLED
    latest_review_state: str = NOT_RUN

    worker_last_heartbeat: str = ""
    worker_version: str = ""
    worker_build_sha: str = ""

    queue_depth: int = 0
    oldest_queued_age: int = 0
    running_jobs: int = 0
    failed_jobs_24h: int = 0
    retrying_jobs: int = 0
    dead_letter_jobs: int = 0

    scheduled_reviews_due: int = 0
    scheduled_reviews_late: int = 0

    latest_review_id: int | None = None
    latest_review_scope: str = ""
    latest_review_data_version: str = ""
    latest_review_started_at: str = ""
    latest_review_completed_at: str = ""
    latest_review_duration: float = 0.0
    latest_review_case_counts: dict[str, int] = field(default_factory=dict)
    latest_review_validation_status: str = ""
    latest_review_error_category: str = ""
    #: Safe by construction: a category and a sentence a reader may see, never
    #: a stack trace and never a connection string.
    latest_review_error_detail_safe: str = ""

    current_agentic_release: str = ""
    current_teaching_release: str = ""
    model_configuration_fingerprint: str = ""
    data_version: str = ""
    stale_reasons: list[str] = field(default_factory=list)

    @property
    def reviewed(self) -> bool:
        """Whether a validated review stands behind the current picture.

        The single most important property here, and the one §136 is about: a
        Cockpit may only say "nothing requires attention" when this is true
        AND the state is COMPLETED_NO_CASES.
        """
        return self.latest_review_state in REVIEWED and not self.stale_reasons

    @property
    def worst(self) -> str:
        """The state a reader should be told about first.

        Named rather than averaged. A healthy worker with a stalled queue is
        not "mostly fine"; it is a stalled queue, and reporting the average
        hides the only thing anybody can act on.
        """
        if self.worker_state in (OFFLINE, DEGRADED):
            return f"worker {self.worker_state}"
        if self.queue_state == STALLED:
            return "queue STALLED"
        if self.scheduler_state in (SCHEDULER_FAILED, DISABLED):
            return f"scheduler {self.scheduler_state}"
        if self.latest_review_state in (REVIEW_FAILED, STALE, CANCELLED):
            return f"latest review {self.latest_review_state}"
        if self.queue_state == BACKLOGGED:
            return "queue BACKLOGGED"
        if self.latest_review_state == NOT_RUN:
            return "no review has run"
        return ""

    @property
    def operating(self) -> bool:
        """Whether the agentic layer is genuinely executing work.

        §134's first gate condition. Deliberately strict: a worker that is
        healthy but has never picked up a job has not been shown to execute
        anything.
        """
        return (self.worker_state in (HEALTHY, STARTING, DRAINING)
                and self.queue_state != STALLED
                and self.latest_review_state != NOT_RUN)

    def sentence(self) -> str:
        if not self.worst:
            return ("The agentic layer is running: the worker is healthy, the "
                    "queue is moving, the schedule is enabled and the latest "
                    "review is current.")
        detail = REVIEW_MEANS.get(self.latest_review_state, ("", ""))[0]
        return (f"The agentic layer needs attention: {self.worst}."
                + (f" {detail}" if detail and "review" in self.worst else "")
                + (" " + "; ".join(self.stale_reasons)
                   if self.stale_reasons else ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": HEALTH_VERSION,
            "worker_state": self.worker_state,
            "queue_state": self.queue_state,
            "scheduler_state": self.scheduler_state,
            "latest_review_state": self.latest_review_state,
            "latest_review_means": REVIEW_MEANS.get(
                self.latest_review_state, ("", ""))[0],
            "latest_review_action": REVIEW_MEANS.get(
                self.latest_review_state, ("", ""))[1],
            "worker_last_heartbeat": self.worker_last_heartbeat,
            "worker_version": self.worker_version,
            "worker_build_sha": self.worker_build_sha,
            "queue_depth": self.queue_depth,
            "oldest_queued_age": self.oldest_queued_age,
            "running_jobs": self.running_jobs,
            "failed_jobs_24h": self.failed_jobs_24h,
            "retrying_jobs": self.retrying_jobs,
            "dead_letter_jobs": self.dead_letter_jobs,
            "scheduled_reviews_due": self.scheduled_reviews_due,
            "scheduled_reviews_late": self.scheduled_reviews_late,
            "latest_review_id": self.latest_review_id,
            "latest_review_scope": self.latest_review_scope,
            "latest_review_data_version": self.latest_review_data_version,
            "latest_review_started_at": self.latest_review_started_at,
            "latest_review_completed_at": self.latest_review_completed_at,
            "latest_review_duration": self.latest_review_duration,
            "latest_review_case_counts": dict(self.latest_review_case_counts),
            "latest_review_validation_status":
                self.latest_review_validation_status,
            "latest_review_error_category": self.latest_review_error_category,
            "latest_review_error_detail_safe":
                self.latest_review_error_detail_safe,
            "current_agentic_release": self.current_agentic_release,
            "current_teaching_release": self.current_teaching_release,
            "model_configuration_fingerprint":
                self.model_configuration_fingerprint,
            "data_version": self.data_version,
            "stale_reasons": list(self.stale_reasons),
            "reviewed": self.reviewed,
            "operating": self.operating,
            "worst": self.worst,
            "sentence": self.sentence(),
        }


def worker_state(*, last_heartbeat: datetime | None, draining: bool = False,
                 started_within: float | None = None,
                 consecutive_failures: int = 0) -> str:
    """§135's worker state, from the heartbeat and nothing else.

    A worker that has not beaten is OFFLINE regardless of what a process
    table says: the heartbeat is the only evidence that the worker can still
    reach the database and claim work, which is the thing "healthy" is meant
    to mean.
    """
    if draining:
        return DRAINING
    if last_heartbeat is None:
        return OFFLINE
    age = (datetime.now(UTC) - _aware(last_heartbeat)).total_seconds()
    if age > OFFLINE_AFTER_SECONDS:
        return OFFLINE
    if started_within is not None and started_within < STARTING_WITHIN_SECONDS:
        return STARTING
    if consecutive_failures >= 3:
        return DEGRADED
    return HEALTHY


def queue_state(*, depth: int, running: int, oldest_queued_age: int,
                worker: str) -> str:
    """§135's queue state.

    STALLED is the one that matters: work waiting a long time while a worker
    reports healthy means the worker is alive and not picking it up, which
    every other combination of these numbers looks nothing like.
    """
    if depth and worker in (HEALTHY, STARTING) and not running \
            and oldest_queued_age > STALLED_AFTER_SECONDS:
        return STALLED
    if depth > BACKLOG_AT:
        return BACKLOGGED
    if running or depth:
        return ACTIVE
    return IDLE


def scheduler_state(*, enabled: bool, due: int, late: int,
                    last_error: str = "") -> str:
    if last_error:
        return SCHEDULER_FAILED
    if not enabled:
        return DISABLED
    if late:
        return LATE
    _ = due
    return ENABLED


def review_state(*, run_status: str, validated: bool, cases: int,
                 stale_reasons: list[str] | None = None) -> str:
    """§136's review state, from a RUN rather than from a case table.

    "Do not infer COMPLETED_NO_CASES from an empty case table" is the
    instruction, and this function is where it is obeyed: with no run there is
    no state but NOT_RUN, and an unvalidated run is VALIDATING however many
    cases it produced.
    """
    if stale_reasons:
        return STALE
    status = (run_status or "").strip().lower()
    if not status:
        return NOT_RUN
    if status in ("queued", "pending"):
        return QUEUED
    if status in ("running", "needs_input", "in_progress"):
        return RUNNING
    if status in ("cancelled", "canceled"):
        return CANCELLED
    if status in ("failed", "error", "dead"):
        return REVIEW_FAILED
    if status in ("succeeded", "complete", "completed"):
        if not validated:
            return VALIDATING
        return COMPLETED_WITH_CASES if cases else COMPLETED_NO_CASES
    # An unrecognised status is not a completed one. Fails closed, the same
    # way every other unknown in this product does.
    return REVIEW_FAILED


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def stale_because(*, review_data_version: str, current_data_version: str,
                  review_sha: str = "", current_sha: str = "",
                  review_policy: str = "",
                  current_policy: str = "") -> list[str]:
    """Why a completed review no longer describes what is running.

    An axis the caller cannot version today is skipped rather than reported
    as changed — the same asymmetry as everywhere else. An axis the REVIEW
    never recorded is stale, because a blank is not evidence of agreement.
    """
    reasons: list[str] = []
    for label, was, now in (
            ("the data has changed since the review",
             review_data_version, current_data_version),
            ("the build has changed since the review", review_sha,
             current_sha),
            ("the screening policy has changed since the review",
             review_policy, current_policy)):
        now = str(now or "").strip()
        if not now:
            continue
        if str(was or "").strip() != now:
            reasons.append(label)
    return reasons


__all__ = ["ACTIVE", "BACKLOGGED", "BACKLOG_AT", "CANCELLED",
           "COMPLETED_NO_CASES", "COMPLETED_WITH_CASES", "DEGRADED",
           "DISABLED", "DRAINING", "ENABLED", "HEALTHY", "HEALTH_VERSION",
           "Health", "IDLE", "LATE", "NOT_RUN", "OFFLINE",
           "OFFLINE_AFTER_SECONDS", "QUEUED", "QUEUE_STATES", "REVIEWED",
           "REVIEW_FAILED", "REVIEW_MEANS", "REVIEW_STATES", "RUNNING",
           "SCHEDULER_FAILED", "SCHEDULER_STATES", "STALE", "STALLED",
           "STALLED_AFTER_SECONDS", "STARTING", "STARTING_WITHIN_SECONDS",
           "VALIDATING", "WORKER_STATES", "queue_state", "review_state",
           "scheduler_state", "stale_because", "worker_state"]
