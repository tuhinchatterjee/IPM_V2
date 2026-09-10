"""
The ledger: counters, cost reservations, and the run deadline.

The property this module has to have
------------------------------------
Every loop in the orchestration consumes something here that is never
replenished. Not "should consume" -- `spend_generation`, `spend_submission`,
`open_round`, `spend_format_recovery` and `spend_answer_correction` all raise
`BudgetExceeded` at zero, and the orchestrator has no path back to the model
that does not call one of them.

Cost is reserved BEFORE a paid attempt and settled after, at the verified
price. A cancelled or disconnected call settles as UNCERTAIN and its
reservation is held pending, because the provider may still have billed it.
Booking that as zero is how a run reports $0.00 having spent real money.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4.capability import Capability
from backend.cockpit_v4.config import Limits
from backend.cockpit_v4.states import (CALL_LIMIT, COST_LIMIT,
                                       DEADLINE_EXPIRED, EXECUTION_LIMIT,
                                       NO_PROGRESS, ROUND_LIMIT)


class BudgetExceeded(RuntimeError):
    """A bound was reached. Carries the code so the stop names the guardrail."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Counters:
    generation_attempts: int = 0
    provider_attempts: int = 0
    execution_submissions: int = 0
    analysis_rounds: int = 0
    catalog_calls: int = 0
    artifact_reads: int = 0
    steps_attempted: int = 0
    format_recoveries: int = 0
    answer_corrections: int = 0
    transport_retries: int = 0


@dataclass
class Ledger:
    """One run's bounded resources. Server-owned; the model cannot widen it."""

    limits: Limits
    capability: Capability
    store: Any
    run_id: str
    started_monotonic: float = field(default_factory=time.monotonic)
    counters: Counters = field(default_factory=Counters)
    #: Reservation ids opened and not yet settled, so a cancel can mark them.
    open_reservations: list[str] = field(default_factory=list)
    #: A round is "open" once an execution batch has run successfully and its
    #: results reached the analyst. See `open_round`.
    _round_open: bool = False
    cancelled: bool = False

    # -- time ------------------------------------------------------------

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_monotonic

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.deadline_seconds - self.elapsed_seconds)

    def check_deadline(self) -> None:
        if self.remaining_seconds <= 0:
            raise BudgetExceeded(
                DEADLINE_EXPIRED,
                f"the {self.limits.deadline_seconds:.0f}-second "
                f"{self.limits.mode} deadline passed.")

    # -- calls -----------------------------------------------------------

    def spend_generation(self) -> int:
        self.check_deadline()
        if self.counters.generation_attempts >= self.limits.generation_attempts:
            raise BudgetExceeded(
                CALL_LIMIT,
                f"all {self.limits.generation_attempts} generation attempts "
                f"for this run were used.")
        self.counters.generation_attempts += 1
        return self.counters.generation_attempts

    def spend_provider_attempt(self) -> int:
        """Every actual HTTP attempt, including token counting and retries.

        The SDK's own retries are disabled in `provider.py`; if that ever
        changes, this counter is where the omission shows up.
        """
        if self.counters.provider_attempts >= self.limits.provider_attempts:
            raise BudgetExceeded(
                CALL_LIMIT,
                f"all {self.limits.provider_attempts} provider HTTP attempts "
                f"for this run were used.")
        self.counters.provider_attempts += 1
        return self.counters.provider_attempts

    def spend_catalog_call(self) -> int:
        self.check_deadline()
        if self.counters.catalog_calls >= self.limits.catalog_calls:
            raise BudgetExceeded(
                CALL_LIMIT,
                f"all {self.limits.catalog_calls} catalog calls were used.")
        self.counters.catalog_calls += 1
        return self.counters.catalog_calls

    def spend_artifact_read(self) -> int:
        self.check_deadline()
        if self.counters.artifact_reads >= self.limits.artifact_reads:
            raise BudgetExceeded(
                CALL_LIMIT,
                f"all {self.limits.artifact_reads} artifact reads were used.")
        self.counters.artifact_reads += 1
        return self.counters.artifact_reads

    def spend_submission(self) -> int:
        """Counted for ANY fully received execute_analysis request.

        Including one that fails validation. A rejected candidate cost a
        generation and a validation pass, and letting invalid submissions be
        free is an unbounded loop with a counter that never moves.
        """
        self.check_deadline()
        if (self.counters.execution_submissions
                >= self.limits.execution_submissions):
            raise BudgetExceeded(
                EXECUTION_LIMIT,
                f"all {self.limits.execution_submissions} execution "
                f"submissions for this run were used.")
        self.counters.execution_submissions += 1
        return self.counters.execution_submissions

    def open_round(self) -> int:
        """Rounds, by the mechanical rule in section 11.

        Round 1 starts at the first submission. A failed or partly failed
        batch may be repaired WITHIN that round. Only after a batch completes
        successfully and its results reach the analyst does the next execution
        batch open a new round. Metadata reads and finalization open nothing.
        """
        if not self._round_open:
            if self.counters.analysis_rounds >= self.limits.analysis_rounds:
                raise BudgetExceeded(
                    ROUND_LIMIT,
                    f"all {self.limits.analysis_rounds} analysis rounds were "
                    f"used.")
            self.counters.analysis_rounds += 1
            self._round_open = True
        return self.counters.analysis_rounds

    def close_round(self) -> None:
        """A batch completed successfully; the next batch opens a new round."""
        self._round_open = False

    def spend_steps(self, count: int) -> None:
        if self.counters.steps_attempted + count > self.limits.total_steps:
            raise BudgetExceeded(
                EXECUTION_LIMIT,
                f"this batch would attempt "
                f"{self.counters.steps_attempted + count} steps and the run "
                f"allows {self.limits.total_steps}. Nothing was executed and "
                f"no step was dropped.")
        self.counters.steps_attempted += count

    def spend_format_recovery(self) -> None:
        if self.counters.format_recoveries >= self.limits.format_regenerations:
            raise BudgetExceeded(
                CALL_LIMIT,
                "the one structure-regeneration attempt for this run was "
                "already used.")
        self.counters.format_recoveries += 1

    def spend_answer_correction(self) -> None:
        if self.counters.answer_corrections >= self.limits.answer_corrections:
            raise BudgetExceeded(
                CALL_LIMIT,
                "the one answer-only correction for this run was already "
                "used.")
        self.counters.answer_corrections += 1

    def spend_transport_retry(self) -> None:
        if self.counters.transport_retries >= 1:
            raise BudgetExceeded(
                CALL_LIMIT,
                "the one transport retry for this run was already used.")
        self.counters.transport_retries += 1

    # -- cost ------------------------------------------------------------

    def spend(self) -> dict[str, Any]:
        return self.store.spend(self.run_id)

    def affordable(self, *, input_tokens: int, output_tokens: int,
                   cache_write_tokens: int = 0) -> float:
        """The worst-case cost of the next attempt, at the verified price."""
        return self.capability.price.cost(
            input_tokens=input_tokens, output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens)

    def reserve(self, *, purpose: str, input_tokens: int, output_tokens: int,
                cache_write_tokens: int = 0) -> str:
        """Atomic reservation at the worst applicable price. Fails closed.

        Reserving the MAXIMUM output rather than an expected output is
        deliberate: the run must be able to afford the response it asked for,
        not the response it hopes for.
        """
        worst = self.affordable(input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cache_write_tokens=cache_write_tokens)
        current = self.spend()
        projected = current["committed_usd"] + current["pending_usd"] + worst
        if projected > self.limits.spend_ceiling_usd:
            raise BudgetExceeded(
                COST_LIMIT,
                f"this attempt would reserve ${worst:.4f} against a "
                f"${self.limits.spend_ceiling_usd:.2f} ceiling with "
                f"${current['committed_usd'] + current['pending_usd']:.4f} "
                f"already committed or pending.")
        reservation_id = self.store.reserve(
            run_id=self.run_id, purpose=purpose, reserved_usd=worst)
        self.open_reservations.append(reservation_id)
        return reservation_id

    def settle(self, reservation_id: str, *, usage: dict[str, Any],
               uncertain: bool = False) -> float | None:
        """Settle at actual usage, or hold pending when the outcome is unknown."""
        if reservation_id in self.open_reservations:
            self.open_reservations.remove(reservation_id)
        if uncertain:
            self.store.settle(reservation_id, settled_usd=None, usage=usage,
                              uncertain=True)
            return None
        actual = self.capability.price.cost(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_write_tokens=int(usage.get("cache_write_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_tokens") or 0))
        self.store.settle(reservation_id, settled_usd=actual, usage=usage,
                          uncertain=False)
        return actual

    def cancel(self) -> None:
        """Mark every open reservation uncertain. A cancelled provider call
        may still be billed; pretending otherwise understates real spend."""
        self.cancelled = True
        for reservation_id in list(self.open_reservations):
            self.store.settle(reservation_id, settled_usd=None,
                              usage={"cancelled": True}, uncertain=True)
        self.open_reservations.clear()

    # -- no-progress -----------------------------------------------------

    def no_progress_check(self, key: str) -> None:
        """Refuse the same deterministic failure twice.

        The key includes the error CLASS, so a transient environment failure
        is not permanently cached as an invalid query -- a genuine recovery
        can retry, an identical deterministic failure cannot.
        """
        if key and key in self.store.no_progress_keys(self.run_id):
            raise BudgetExceeded(
                NO_PROGRESS,
                "this exact code, parameters, release and failure class were "
                "already tried in this run and nothing about the environment "
                "changed. It was not run again.")

    # -- reporting -------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        spend = self.spend()
        c, lim = self.counters, self.limits
        return {
            "mode": lim.mode,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "remaining_seconds": round(self.remaining_seconds, 3),
            "generation_attempts": [c.generation_attempts,
                                    lim.generation_attempts],
            "provider_attempts": [c.provider_attempts, lim.provider_attempts],
            "execution_submissions": [c.execution_submissions,
                                      lim.execution_submissions],
            "analysis_rounds": [c.analysis_rounds, lim.analysis_rounds],
            "catalog_calls": [c.catalog_calls, lim.catalog_calls],
            "artifact_reads": [c.artifact_reads, lim.artifact_reads],
            "steps_attempted": [c.steps_attempted, lim.total_steps],
            "format_recoveries": [c.format_recoveries,
                                  lim.format_regenerations],
            "answer_corrections": [c.answer_corrections,
                                   lim.answer_corrections],
            "spend": spend,
            "spend_ceiling_usd": lim.spend_ceiling_usd,
            # An "enforced" badge is only honest when the price is verified
            # AND nothing is held as an unknown amount.
            "cost_enforced": (self.capability.price is not None
                              and not spend["uncertain"]),
        }


__all__ = ["BudgetExceeded", "Counters", "Ledger"]
