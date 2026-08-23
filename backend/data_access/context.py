"""
AnalysisContext — the explicit "who is asking, about what" that travels with
every analytical call.

Why this exists
---------------
The original Dash application held the portfolio in module-level global
DataFrames, and every calculation read those globals. That works for one user
looking at one period. It cannot support two users on different periods, a
second portfolio, per-user data permissions, or a request-scoped API.

An AnalysisContext replaces the shared global with an explicit parameter:
every engine function is *handed* the period, filters and dataset version it
should use. Nothing is implicit, so nothing can be accidentally shared between
requests.

It is frozen (immutable) on purpose. A function cannot quietly widen its own
scope mid-calculation; to analyse something else it must derive a new context,
and that derivation is visible in the Trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

# Filters are deliberately a plain mapping of governed field name -> value(s).
# The DAL resolves those names through the catalogue; the engine never writes SQL.
FilterValue = str | int | float | bool | list[str] | list[int] | list[float]


@dataclass(frozen=True)
class AnalysisContext:
    """Everything an analytical call needs to know about its own scope.

    Attributes:
        period:          The reporting period being analysed, e.g. "Q1 2026".
        compare_period:  The period to compare against, e.g. "Q4 2025". Optional —
                         only movement/migration analyses need it.
        filters:         Governed field name -> value(s). "All" or None means no
                         filter on that field.
        dataset_version: Which governed dataset version to read. Recorded on every
                         analysis run so a result can be reproduced exactly.
        user_id:         Who is asking. Used for data-level permissions and audit.
        request_id:      Correlates every log line, trace node and API response
                         belonging to one request.
    """

    period: str
    compare_period: str | None = None
    filters: dict[str, FilterValue] = field(default_factory=dict)
    dataset_version: int | None = None
    user_id: int | None = None
    request_id: str | None = None

    def with_filters(self, **extra: FilterValue) -> AnalysisContext:
        """Derive a narrower context. Returns a new object; the original is
        untouched, so an upstream caller's scope can never be mutated from below."""
        merged = {**self.filters, **extra}
        return replace(self, filters=merged)

    def with_period(self, period: str, compare_period: str | None = None) -> AnalysisContext:
        """Derive a context pointing at a different period — used by trend and
        comparison analyses that need to walk several periods."""
        return replace(self, period=period, compare_period=compare_period)

    @property
    def active_filters(self) -> dict[str, FilterValue]:
        """Only the filters that actually narrow anything. The UI sends "All" for
        an unset dropdown; treating that as a filter would produce empty results
        and a misleading Trace node."""
        return {
            k: v
            for k, v in self.filters.items()
            if v is not None and v != "" and v != "All" and v != []
        }

    def describe(self) -> dict[str, Any]:
        """A plain dictionary for logging, API responses and Trace nodes."""
        return {
            "period": self.period,
            "compare_period": self.compare_period,
            "filters": self.active_filters,
            "dataset_version": self.dataset_version,
            "user_id": self.user_id,
            "request_id": self.request_id,
        }
