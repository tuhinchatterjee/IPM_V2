"""
Loop and cost safety. §20.

    "Never silently spend unlimited credits."

Every counter in this module exists because there is a way for an agentic run to
consume without bound, and each one closes a specific hole:

    iterations      an orchestrator that re-plans after every result
    tasks           a plan that delegates a task that delegates a task
    repairs         a validation that never passes and is retried forever
    model_calls     the one that costs money directly
    runtime         everything else, caught by the clock
    scans           an analytical loop that is cheap per call and not in total
    rows            one scan over the whole book, repeated
    output          a synthesis that grows until nothing can render it

The important word in §20 is *silently*. Exhausting a budget is not an error and
is not hidden: the run stops, says what it completed, says what remains, and —
where continuing would be reasonable — asks. That is `Exhausted`, and it is a
first-class outcome rather than an exception nobody catches.

Charged before, not after
-------------------------
`spend()` is called BEFORE the thing it pays for. A budget checked afterwards
has already been exceeded, and the model call it was meant to prevent has
already been made and already been billed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# What can be spent
# ---------------------------------------------------------------------------

ITERATIONS = "iterations"
TASKS = "tasks"
REPAIRS = "repairs"
MODEL_CALLS = "model_calls"
SCANS = "scans"
ROWS = "rows"
OUTPUT = "output_chars"
RUNTIME = "runtime_seconds"

METERS: tuple[str, ...] = (
    ITERATIONS, TASKS, REPAIRS, MODEL_CALLS, SCANS, ROWS, OUTPUT, RUNTIME,
)

LABELS: dict[str, str] = {
    ITERATIONS: "orchestration passes",
    TASKS: "delegated tasks",
    REPAIRS: "repair attempts",
    MODEL_CALLS: "model calls",
    SCANS: "analytical scans",
    ROWS: "rows read",
    OUTPUT: "characters of output",
    RUNTIME: "seconds",
}


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Limits:
    """The ceiling for one run."""

    iterations: int = 3
    tasks: int = 24
    repairs: int = 2
    model_calls: int = 12
    scans: int = 40
    rows: int = 20_000_000
    output_chars: int = 40_000
    runtime_seconds: int = 900

    def to_dict(self) -> dict[str, int]:
        return {
            ITERATIONS: self.iterations,
            TASKS: self.tasks,
            REPAIRS: self.repairs,
            MODEL_CALLS: self.model_calls,
            SCANS: self.scans,
            ROWS: self.rows,
            OUTPUT: self.output_chars,
            RUNTIME: self.runtime_seconds,
        }


#: A user waiting for an answer: tighter, because they are watching.
INTERACTIVE = Limits(iterations=2, tasks=12, repairs=1, model_calls=8,
                     scans=20, rows=8_000_000, output_chars=24_000,
                     runtime_seconds=180)

#: A proactive review of a newly published period: wider, because it covers the
#: whole book — but still finite, and still funnelled by the deterministic
#: pre-screen before a single model call is made (§36).
PROACTIVE = Limits(iterations=3, tasks=24, repairs=2, model_calls=16,
                   scans=60, rows=40_000_000, output_chars=60_000,
                   runtime_seconds=1_200)


class Exhausted(RuntimeError):
    """A budget ran out. Carries what was done and what is left.

    An exception rather than a return value because it must interrupt whatever
    was about to happen, and a *specific* one because §20 requires the outcome
    to be reported rather than turned into a generic failure: "CreditProbe
    stopped after 8 model calls" is a different thing to tell a user than
    "CreditProbe failed".
    """

    def __init__(self, meter: str, spent: int, limit: int, *,
                 completed: str = "", remaining: str = "") -> None:
        self.meter = meter
        self.spent = spent
        self.limit = limit
        self.completed = completed
        self.remaining = remaining
        super().__init__(
            f"The {LABELS.get(meter, meter)} budget ran out "
            f"({spent} of {limit}).")

    def sentence(self) -> str:
        """What the user is told. §20: state what was completed, state what
        remains, and ask before continuing."""
        parts = [f"CreditProbe stopped after {self.spent} "
                 f"{LABELS.get(self.meter, self.meter)}, which is the limit "
                 f"for this kind of request."]
        if self.completed:
            parts.append(f"Completed: {self.completed}.")
        if self.remaining:
            parts.append(f"Not done: {self.remaining}.")
        parts.append("Ask again to continue from here.")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meter": self.meter,
            "spent": self.spent,
            "limit": self.limit,
            "completed": self.completed,
            "remaining": self.remaining,
            "message": self.sentence(),
        }


@dataclass
class Budget:
    """What this run is allowed to spend, and what it has spent."""

    limits: Limits = field(default_factory=lambda: INTERACTIVE)
    spent: dict[str, int] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    #: Set when a meter ran out, so the run can report it rather than raise
    #: twice.
    exhausted: Exhausted | None = None

    def __post_init__(self) -> None:
        for meter in METERS:
            self.spent.setdefault(meter, 0)

    # -- spending ----------------------------------------------------------

    def spend(self, meter: str, amount: int = 1, *, completed: str = "",
              remaining: str = "") -> None:
        """Charge a meter BEFORE doing the thing.

        Raises `Exhausted` when the charge would exceed the ceiling. The charge
        is not applied in that case: a run that stopped at its limit should read
        as having reached it, not as having gone one over.
        """
        limit = self.limit(meter)
        now = int(self.spent.get(meter, 0))
        # A limit of ZERO means none allowed, not unlimited. `if limit` treated
        # them as the same thing, so an administrator setting a budget to 0 to
        # switch something off would have granted it without a ceiling —
        # exactly backwards, and silent. Unlimited is expressed as a negative
        # limit, which nothing in the shipped policy uses.
        if limit >= 0 and now + amount > limit:
            self.exhausted = Exhausted(meter, now, limit, completed=completed,
                                       remaining=remaining)
            logger.info("budget exhausted: %s %s/%s", meter, now, limit)
            raise self.exhausted
        self.spent[meter] = now + amount

    def try_spend(self, meter: str, amount: int = 1) -> bool:
        """Charge if there is room. Returns False instead of raising.

        Used where running out is an ordinary decision rather than an
        interruption — "should I enrich this case with a fourth signal?" is
        answered with no, not with a stopped run.
        """
        try:
            self.spend(meter, amount)
        except Exhausted:
            return False
        return True

    def limit(self, meter: str) -> int:
        """The ceiling for a meter. Negative means unlimited.

        A meter nothing defines is unlimited rather than zero: a typo in a
        meter name should not silently stop a run, it should be visible as a
        meter that never fills.
        """
        return int(self.limits.to_dict().get(meter, -1))

    def remaining(self, meter: str) -> int:
        limit = self.limit(meter)
        if limit < 0:
            return 0
        return max(0, limit - int(self.spent.get(meter, 0)))

    # -- the clock ---------------------------------------------------------

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started

    def check_clock(self, *, completed: str = "", remaining: str = "") -> None:
        """The one meter that runs without being charged.

        Called at each checkpoint. Everything else can be counted at the moment
        it is spent; time passes whether or not anybody asks.
        """
        elapsed = int(self.elapsed_seconds)
        self.spent[RUNTIME] = elapsed
        if (self.limits.runtime_seconds >= 0
                and elapsed > self.limits.runtime_seconds):
            self.exhausted = Exhausted(
                RUNTIME, elapsed, self.limits.runtime_seconds,
                completed=completed, remaining=remaining)
            raise self.exhausted

    # -- reporting ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        self.spent[RUNTIME] = int(self.elapsed_seconds)
        limits = self.limits.to_dict()
        return {
            "limits": limits,
            "spent": dict(self.spent),
            "remaining": {m: max(0, limits.get(m, 0) - self.spent.get(m, 0))
                          for m in METERS},
            "exhausted": self.exhausted.to_dict() if self.exhausted else None,
        }

    def usage_line(self) -> str:
        """What a run cost, for the Runs tab. §56 asks for the funnel to be
        persisted; this is the one-line form of it."""
        return (f"{self.spent.get(MODEL_CALLS, 0)} model calls · "
                f"{self.spent.get(SCANS, 0)} scans · "
                f"{self.spent.get(ROWS, 0):,} rows · "
                f"{int(self.elapsed_seconds)}s")


def for_trigger(trigger: str) -> Budget:
    """The right ceiling for what started this run."""
    proactive = trigger in {"scheduled_review", "event", "manual_review"}
    return Budget(limits=PROACTIVE if proactive else INTERACTIVE)


__all__ = [
    "INTERACTIVE",
    "ITERATIONS",
    "LABELS",
    "METERS",
    "MODEL_CALLS",
    "OUTPUT",
    "PROACTIVE",
    "REPAIRS",
    "ROWS",
    "RUNTIME",
    "SCANS",
    "TASKS",
    "Budget",
    "Exhausted",
    "Limits",
    "for_trigger",
]
