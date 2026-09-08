"""
One ledger, from the first word of a turn to the last.

Why one
-------
A budget that resets after a failure is not a budget. The failure modes that
actually cost money are the recursive ones — a plan that fails validation,
gets repaired, fails again, gets repaired again — and every one of them looks
affordable if each attempt starts from a fresh allowance. So the ledger is
created once, when the request arrives, and every stage after that spends
from the same counters: normalisation, selection, planning, repair,
execution, and every sufficiency revision.

The counters do not reset. Not after a validator rejection, not after an
execution error, not after an insufficiency. That is the whole design.

Mode changes the ceiling, never the rules
-----------------------------------------
Deep allows more decomposition and more revisions than Standard. It allows
nothing else: not another domain, not a skipped validation, not a fact the
evidence does not support. A mode that could reach further into the data
would not be a depth setting, it would be a permission, and permissions are
not a thing a reader picks from a dropdown.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

#: The two depths. Ceilings differ; nothing else does.
STANDARD = "standard"
DEEP = "deep"

#: What each mode allows. Starting settings rather than measured optima, and
#: recorded on every turn so they can be replaced by evidence later.
CEILINGS: dict[str, dict[str, int]] = {
    STANDARD: {
        "model_calls": 8,
        "executions": 6,
        "repairs": 2,
        "revisions": 1,
        "wall_clock_seconds": 60,
    },
    DEEP: {
        "model_calls": 16,
        "executions": 14,
        "repairs": 3,
        "revisions": 3,
        "wall_clock_seconds": 150,
    },
}


class Exhausted(RuntimeError):
    """The turn ran out. Raised so the caller stops honestly rather than
    quietly returning less than it was asked for."""


@dataclass
class Ledger:
    """Everything one turn is allowed to spend, and what it has spent."""

    mode: str = STANDARD
    started_at: float = field(default_factory=time.perf_counter)
    model_calls: int = 0
    sonnet_calls: int = 0
    opus_calls: int = 0
    executions: int = 0
    repairs: int = 0
    revisions: int = 0
    #: Every refusal, so an exhausted turn can say what it ran out of.
    refusals: list[str] = field(default_factory=list)

    @property
    def ceilings(self) -> dict[str, int]:
        return CEILINGS.get(self.mode, CEILINGS[STANDARD])

    @property
    def elapsed_seconds(self) -> float:
        return round(time.perf_counter() - self.started_at, 3)

    def _spend(self, counter: str, amount: int = 1) -> None:
        ceiling = self.ceilings.get(counter)
        current = getattr(self, counter, 0)
        if ceiling is not None and current + amount > ceiling:
            reason = (f"{counter.replace('_', ' ')} budget exhausted: "
                      f"{current} of {ceiling} used")
            self.refusals.append(reason)
            raise Exhausted(reason)
        if self.elapsed_seconds > self.ceilings["wall_clock_seconds"]:
            reason = (f"time budget exhausted: {self.elapsed_seconds:.1f}s of "
                      f"{self.ceilings['wall_clock_seconds']}s used")
            self.refusals.append(reason)
            raise Exhausted(reason)
        setattr(self, counter, current + amount)

    def model_call(self, *, family: str = "") -> None:
        """One call to a model, of either family."""
        self._spend("model_calls")
        if family == "sonnet":
            self.sonnet_calls += 1
        elif family == "opus":
            self.opus_calls += 1

    def execution(self) -> None:
        self._spend("executions")

    def repair(self) -> None:
        """A repair spends from the SAME counters the failed attempt did."""
        self._spend("repairs")

    def revision(self) -> None:
        self._spend("revisions")

    def can(self, counter: str) -> bool:
        """Whether one more of something is affordable, without spending it."""
        ceiling = self.ceilings.get(counter)
        if ceiling is None:
            return True
        if self.elapsed_seconds > self.ceilings["wall_clock_seconds"]:
            return False
        return getattr(self, counter, 0) < ceiling

    @property
    def exhausted(self) -> bool:
        return bool(self.refusals)

    def remaining(self) -> dict[str, int]:
        return {name: max(0, ceiling - getattr(self, name, 0))
                for name, ceiling in self.ceilings.items()
                if name != "wall_clock_seconds"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "ceilings": dict(self.ceilings),
            "spent": {
                "model_calls": self.model_calls,
                "sonnet_calls": self.sonnet_calls,
                "opus_calls": self.opus_calls,
                "executions": self.executions,
                "repairs": self.repairs,
                "revisions": self.revisions,
            },
            "remaining": self.remaining(),
            "elapsed_seconds": self.elapsed_seconds,
            "refusals": list(self.refusals),
            "note": ("One ledger per turn. Counters are not reset by a "
                     "validation failure, an execution error or a "
                     "sufficiency revision — that is what makes them a "
                     "budget rather than a per-attempt allowance."),
        }


def open_ledger(mode: str = STANDARD) -> Ledger:
    return Ledger(mode=mode if mode in CEILINGS else STANDARD)


__all__ = ["CEILINGS", "DEEP", "STANDARD", "Exhausted", "Ledger",
           "open_ledger"]
