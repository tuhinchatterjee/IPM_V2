"""
One metric shape for the UI, the database, CSV and the workbook.

A metric is never a bare number. It carries its unit, how it was obtained, and
-- when there is no value -- why. `None` stays `None` all the way to the
export; nothing in this module turns an unknown into zero.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

MEASURED = "MEASURED"
ESTIMATED = "ESTIMATED"
DERIVED = "DERIVED"
UNAVAILABLE = "UNAVAILABLE"
SHARED = "SHARED"
HUMAN_REVIEWED = "HUMAN_REVIEWED"
STATUSES = (MEASURED, ESTIMATED, DERIVED, UNAVAILABLE, SHARED,
            HUMAN_REVIEWED)


@dataclass(frozen=True)
class Metric:
    value: float | int | str | None
    unit: str
    status: str
    source: str = ""
    missing_reason: str = ""
    definition: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown metric status {self.status!r}")
        if self.value is None and self.status not in (UNAVAILABLE,):
            raise ValueError("a metric without a value must be UNAVAILABLE")
        if self.status == UNAVAILABLE and not self.missing_reason:
            raise ValueError("an UNAVAILABLE metric must say why")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def measured(value, unit: str, source: str, definition: str = "") -> Metric:
    return Metric(value, unit, MEASURED, source, "", definition)


def derived(value, unit: str, source: str, definition: str = "") -> Metric:
    return Metric(value, unit, DERIVED, source, "", definition)


def estimated(value, unit: str, source: str, definition: str = "") -> Metric:
    return Metric(value, unit, ESTIMATED, source, "", definition)


def unavailable(unit: str, reason: str, source: str = "",
                definition: str = "") -> Metric:
    return Metric(None, unit, UNAVAILABLE, source, reason, definition)


def interval_union_ms(spans: list[tuple[float, float]]) -> float:
    """Length of the union of [start, end) intervals, in the spans' unit.

    Parallel or nested spans are merged, so the same wall-clock second is
    never counted twice (M06)."""
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted((a, b) for a, b in spans if b >= a):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def median(values: list[float]) -> float | None:
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def sample_summary(values: list[float], *, unique_tasks: int,
                   unit: str) -> dict[str, Any]:
    """Median/range with the sample it rests on. p95 is withheld below 20
    observations: a tail statistic of a handful of runs is noise (M15)."""
    v = [x for x in values if x is not None]
    out: dict[str, Any] = {"n": len(v), "unique_tasks": unique_tasks,
                           "unit": unit, "median": median(v),
                           "min": min(v) if v else None,
                           "max": max(v) if v else None}
    out["p95"] = None
    out["p95_status"] = ("INSUFFICIENT_SAMPLE" if len(v) < 20
                         else "EXPLORATORY_NEAREST_RANK")
    if len(v) >= 20:
        s = sorted(v)
        out["p95"] = s[max(0, int(round(0.95 * len(s))) - 1)]
    return out
