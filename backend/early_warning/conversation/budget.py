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

The closing reserve
-------------------
Two stages are not optional: the final interpretation, and the rolling summary
that lets the next turn resolve "it". A turn that spent its whole allowance on
an optional sufficiency revision and then had nothing left to write the answer
with has spent the budget on the part the reader never sees.

So a slice of the allowance is reserved for those two, and optional work —
a revision, a repair — may not touch it. The reserve is not extra budget: the
ceiling is unchanged and every stage still spends from the same counters. It
is an ordering rule, and it makes an optional revision genuinely optional
rather than a gamble against the answer.

Two clocks, for the same reason
-------------------------------
The soft deadline stops optional work. The hard deadline stops everything. A
provider that is merely slow should cost the revision, not the interpretation
— and one clock cannot express that, which is how a turn ends up with six real
model calls and a deterministic answer.
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
        # The soft deadline. Measured against real Opus latency rather than
        # against the deterministic path it was first set for: four Opus
        # calls over a grain package take longer than the sixty seconds a
        # sub-second deterministic turn never came close to.
        "wall_clock_seconds": 120,
        # The hard deadline. Only the closing stages may run between the two.
        "hard_wall_clock_seconds": 240,
    },
    DEEP: {
        "model_calls": 16,
        "executions": 14,
        "repairs": 3,
        "revisions": 3,
        "wall_clock_seconds": 240,
        "hard_wall_clock_seconds": 480,
    },
}

#: Model calls held back for the two stages a turn cannot end without: the
#: final interpretation and the rolling summary. Optional work may not spend
#: into this.
#:
#: Standard's arithmetic, which is why the ceiling is eight: pass one, pass
#: two, functionality selection, the analysis plan and one sufficiency review
#: are five; a single permitted revision costs a second review, making six;
#: the two closing stages take it to eight exactly. A second revision would
#: eat the reserve, and is refused rather than allowed to.
RESERVED_MODEL_CALLS = 2


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
    #: Of the model calls charged, how many produced a usable answer. A call
    #: that was made and then failed is still charged — a ledger that counted
    #: only successes would make a provider that fails expensively look free —
    #: so the two are recorded separately rather than one being inferred.
    model_calls_succeeded: int = 0
    model_calls_failed: int = 0
    #: The same distinction for executions. `executions` is what was charged,
    #: and it is charged at the moment a step is about to be run — never for a
    #: step that was merely planned, validated or queued. So a turn that
    #: reached the executor zero times reports zero, and one that reports six
    #: ran six.
    executions_succeeded: int = 0
    executions_failed: int = 0
    #: Every attempt, in order, with what served it and how it ended. This is
    #: what lets the ledger be reconstructed from the trace rather than
    #: reconciled by arithmetic.
    calls: list[dict[str, Any]] = field(default_factory=list)
    #: Every execution attempt, in order, with how it ended. The trace and
    #: the ledger have to describe the same turn; this is what makes that
    #: checkable rather than asserted.
    steps: list[dict[str, Any]] = field(default_factory=list)
    #: Every refusal, so an exhausted turn can say what it ran out of.
    refusals: list[str] = field(default_factory=list)

    @property
    def ceilings(self) -> dict[str, int]:
        return CEILINGS.get(self.mode, CEILINGS[STANDARD])

    @property
    def elapsed_seconds(self) -> float:
        return round(time.perf_counter() - self.started_at, 3)

    def _deadline(self, *, closing: bool) -> int:
        """Which clock this stage is measured against."""
        if closing:
            return int(self.ceilings.get("hard_wall_clock_seconds")
                       or self.ceilings["wall_clock_seconds"])
        return int(self.ceilings["wall_clock_seconds"])

    def _headroom(self, counter: str, *, closing: bool) -> int:
        """The ceiling this caller may spend up to.

        Optional work stops short of the closing reserve. The closing stages
        themselves spend up to the real ceiling — the reserve is theirs.
        """
        ceiling = self.ceilings.get(counter)
        if ceiling is None:
            return -1
        if counter == "model_calls" and not closing:
            return max(0, ceiling - RESERVED_MODEL_CALLS)
        return ceiling

    def why_not(self, counter: str, *, closing: bool = False) -> str:
        """Why one more of something is unaffordable, or "" if it is not.

        Returns the reason rather than a bare False, because "the budget is
        spent" over a turn that used six of eight calls is a sentence that
        sends a reader looking in the wrong place. It was the clock.
        """
        deadline = self._deadline(closing=closing)
        if self.elapsed_seconds > deadline:
            return (f"the turn's {'hard ' if closing else ''}time budget is "
                    f"spent ({self.elapsed_seconds:.1f}s of {deadline}s)")
        headroom = self._headroom(counter, closing=closing)
        if headroom < 0:
            return ""
        current = getattr(self, counter, 0)
        if current >= headroom:
            ceiling = self.ceilings.get(counter)
            if counter == "model_calls" and not closing and headroom < ceiling:
                return (f"this turn's optional model-call allowance is spent "
                        f"({current} of {headroom}; {RESERVED_MODEL_CALLS} "
                        f"of {ceiling} are reserved for the final "
                        f"interpretation and the thread summary)")
            return (f"this turn's {counter.replace('_', ' ')} budget is spent "
                    f"({current} of {ceiling})")
        return ""

    def _spend(self, counter: str, amount: int = 1, *,
               closing: bool = False) -> None:
        blocked = self.why_not(counter, closing=closing)
        if blocked:
            self.refusals.append(blocked)
            raise Exhausted(blocked)
        setattr(self, counter, getattr(self, counter, 0) + amount)

    def model_call(self, *, family: str = "", closing: bool = False) -> None:
        """One call to a model, of either family.

        Charged before the call rather than after it. A stage that checked
        afterwards would be a stage that could always afford one more.
        """
        self._spend("model_calls", closing=closing)
        if family == "sonnet":
            self.sonnet_calls += 1
        elif family == "opus":
            self.opus_calls += 1

    def settle(self, *, stage: str, family: str = "", ok: bool,
               provider: str = "", model: str = "", role: str = "",
               reason: str = "", duration_ms: int = 0,
               input_tokens: int = 0, output_tokens: int = 0) -> None:
        """How the call that was just charged actually ended.

        Separate from `model_call` because the charge happens before the
        provider is asked and the outcome is only known after. Both halves
        are recorded, so `charged = succeeded + failed` holds by
        construction rather than by hope.
        """
        if ok:
            self.model_calls_succeeded += 1
        else:
            self.model_calls_failed += 1
        self.calls.append({
            "stage": stage, "family": family, "ok": ok,
            "provider": provider, "model": model, "role": role,
            "reason": reason, "duration_ms": duration_ms,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "at_seconds": self.elapsed_seconds,
        })

    def execution(self) -> None:
        """One governed analytical execution, charged as it is attempted.

        Charged on attempt rather than on success, for the reason model calls
        are: an execution that ran and failed cost what one that ran and
        worked cost. What it is emphatically NOT charged for is a planned
        step, a validated step or a reserved slot — the counter moves only
        where the executor is about to be called, one increment per call.

        The caller asks `can("executions")` first and declines the step when
        the answer is no. Letting this raise mid-loop would end the turn on
        the step that could not run and throw away the ones that did.
        """
        self._spend("executions")

    def settle_execution(self, *, analysis: str = "", ok: bool,
                         rows: int = 0, reason: str = "",
                         corrected: bool = False) -> None:
        """How the execution that was just charged actually ended.

        `executions = executions_succeeded + executions_failed` holds by
        construction, so a ledger reporting six executions can be read back
        as six real attempts against named analyses.
        """
        if ok:
            self.executions_succeeded += 1
        else:
            self.executions_failed += 1
        self.steps.append({
            "analysis": analysis, "ok": ok, "rows": rows,
            "reason": reason, "corrected": corrected,
            "at_seconds": self.elapsed_seconds,
        })

    def repair(self) -> None:
        """A repair spends from the SAME counters the failed attempt did."""
        self._spend("repairs")

    def revision(self) -> None:
        self._spend("revisions")

    def can(self, counter: str, *, closing: bool = False) -> bool:
        """Whether one more of something is affordable, without spending it."""
        return not self.why_not(counter, closing=closing)

    def may_revise(self) -> bool:
        """Whether an OPTIONAL sufficiency revision is affordable.

        A revision costs a revision, an execution and a second sufficiency
        review, and the closing stages still have to happen afterwards. So
        the question is not "is there one call left" but "is there one left
        that is not the answer's".
        """
        return (self.can("revisions")
                and self.can("executions")
                and self.can("model_calls"))

    @property
    def exhausted(self) -> bool:
        return bool(self.refusals)

    def remaining(self) -> dict[str, int]:
        return {name: max(0, ceiling - getattr(self, name, 0))
                for name, ceiling in self.ceilings.items()
                if not name.endswith("wall_clock_seconds")}

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "ceilings": dict(self.ceilings),
            "reserved_model_calls": RESERVED_MODEL_CALLS,
            "spent": {
                "model_calls": self.model_calls,
                "sonnet_calls": self.sonnet_calls,
                "opus_calls": self.opus_calls,
                "executions": self.executions,
                "repairs": self.repairs,
                "revisions": self.revisions,
            },
            # Charged, and how it ended. `model_calls` above is what the turn
            # was billed for; these say what the billing bought.
            "model_calls_charged": self.model_calls,
            "model_calls_succeeded": self.model_calls_succeeded,
            "model_calls_failed": self.model_calls_failed,
            "calls": [dict(c) for c in self.calls],
            # Executions, on the same terms: charged at the moment the
            # executor was called, and settled by how the call ended.
            "executions_attempted": self.executions,
            "executions_succeeded": self.executions_succeeded,
            "executions_failed": self.executions_failed,
            "steps": [dict(s) for s in self.steps],
            "remaining": self.remaining(),
            "optional_model_calls_remaining": max(
                0, self._headroom("model_calls", closing=False)
                - self.model_calls),
            "elapsed_seconds": self.elapsed_seconds,
            "refusals": list(self.refusals),
            "note": ("One ledger per turn. Counters are not reset by a "
                     "validation failure, an execution error or a "
                     "sufficiency revision — that is what makes them a "
                     "budget rather than a per-attempt allowance. Two model "
                     "calls are reserved for the final interpretation and "
                     "the thread summary, so optional work cannot spend the "
                     "answer. Executions count analyses actually run, never "
                     "analyses planned or validated: a step the ceiling "
                     "refuses is declined before it runs and is not "
                     "charged."),
        }


def open_ledger(mode: str = STANDARD) -> Ledger:
    return Ledger(mode=mode if mode in CEILINGS else STANDARD)


__all__ = ["CEILINGS", "DEEP", "RESERVED_MODEL_CALLS", "STANDARD",
           "Exhausted", "Ledger", "open_ledger"]
