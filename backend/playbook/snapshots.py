"""Freezing a governed figure into a pack, so it can be defended later.

A pack does not read live metrics when somebody opens it. It reads the values
that were calculated INTO it, each one carrying the formula version, the period,
the filters, the dataset fingerprint and the executor's run id. That is the
whole reason `playbook_snapshots` exists, and it is what lets somebody sitting
in a meeting six months from now get the same number the committee was given.

Rows here are written and never updated. Refreshing a draft writes NEW rows at
a new pack version; an approved pack's rows are left exactly as they were.

Having no number is five different facts
----------------------------------------
    OK                  there IS a number, and it may legitimately be 0.0
    NO_DATA             the period exists but nothing is in the metric's scope
    NOT_MATURED         the outcome window has not closed yet
    PERIOD_MISSING      the lake holds no rows for that period at all
    CALCULATION_FAILED  something broke, and that is a platform problem
    NOT_AUTHORISED      the reader may not see this source

They are told apart by ASKING THE DATA, not by reading the executor's English.
A classifier built on string matching breaks the first time somebody improves a
message, and it breaks silently, in the direction of calling a data gap a
platform failure.

Zero is a number
----------------
A metric that genuinely computes to 0.0 — no breaches this month, no new
defaults — has a value, and `availability` is OK. It is shown as 0.0 and it
should be. What must never happen is the other one: an immature cohort or an
empty denominator rendering as a client-facing 0.0%. Everything in this module
is arranged so those two cannot be confused, because the executor returns None
for the second and the second never reaches `value`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.models.playbook import PlaybookSnapshot

logger = logging.getLogger(__name__)

# Availability, matching `backend.models.playbook.UNAVAILABLE_REASONS`.
OK = "OK"
NO_DATA = "NO_DATA"
NOT_MATURED = "NOT_MATURED"
CALCULATION_FAILED = "CALCULATION_FAILED"
NOT_AUTHORISED = "NOT_AUTHORISED"
PERIOD_MISSING = "PERIOD_MISSING"
METRIC_UNAVAILABLE = "METRIC_UNAVAILABLE"

#: A number is only ever presented when availability is this.
PRESENTABLE = frozenset({OK})

#: Fields that mean "this row's outcome window has closed". A metric scoped on
#: one of these has a maturity rule, and an empty period under that scope is
#: NOT_MATURED rather than NO_DATA — a distinction worth an afternoon to the
#: person reading the pack.
MATURITY_FIELDS = frozenset({
    "matured_flag", "matured", "is_matured", "outcome_matured",
    "performance_window_closed", "window_closed",
})

#: How many parquet files a fingerprint will stat before it gives up and says
#: so. A dataset with thousands of files should not make opening a pack slow.
FINGERPRINT_FILE_LIMIT = 400


@dataclass
class Figure:
    """One captured figure, before it becomes a row.

    Separated from the ORM object so the same capture can be rendered into an
    export, compared against a previous pack, or written — without three code
    paths each deciding for themselves what the display string is.
    """

    metric_id: str
    metric_name: str = ""
    metric_version: str = ""
    formula_hash: str = ""
    period: str = ""
    comparison_period: str = ""
    filters: dict[str, Any] = field(default_factory=dict)

    value: float | None = None
    comparison_value: float | None = None
    display_value: str = ""
    unit: str = "number"
    decimals: int = 2
    higher_is_better: bool | None = None

    numerator: float | None = None
    denominator: float | None = None
    rows_considered: int = 0
    series: list = field(default_factory=list)

    availability: str = OK
    unavailable_reason: str = ""

    dataset: str = ""
    dataset_version: str = ""
    source_fields: list = field(default_factory=list)
    calculation: dict = field(default_factory=dict)
    run_id: str = ""
    sql: str = ""
    verification_state: str = ""
    governed: bool = True

    @property
    def available(self) -> bool:
        return self.availability in PRESENTABLE and self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id, "metric_name": self.metric_name,
            "metric_version": self.metric_version,
            "formula_hash": self.formula_hash,
            "period": self.period,
            "comparison_period": self.comparison_period,
            "filters": dict(self.filters),
            "value": self.value, "comparison_value": self.comparison_value,
            "display_value": self.display_value, "unit": self.unit,
            "decimals": self.decimals,
            "higher_is_better": self.higher_is_better,
            "numerator": self.numerator, "denominator": self.denominator,
            "rows_considered": self.rows_considered,
            "series": list(self.series),
            "availability": self.availability,
            "unavailable_reason": self.unavailable_reason,
            "dataset": self.dataset, "dataset_version": self.dataset_version,
            "source_fields": list(self.source_fields),
            "run_id": self.run_id,
            "verification_state": self.verification_state,
            "governed": self.governed,
            "available": self.available,
        }


# ------------------------------------------------------------ the fingerprint


def formula_hash(metric: Any) -> str:
    """A stable hash of the arithmetic, not of the version string.

    Two snapshots with the same hash were produced by the same calculation
    whatever anybody wrote in `version`. It is the version string that catches
    a deliberate revision; it is this that catches an undeclared one.
    """
    try:
        payload = {
            "formula": metric.formula.to_dict(),
            "scope": [[c.field, c.op, c.value] for c in metric.scope],
            "period_rule": metric.period_rule,
        }
    except Exception:  # noqa: BLE001 - a metric that cannot describe itself
        logger.warning("could not hash the formula for %s",
                       getattr(metric, "metric_id", "?"), exc_info=True)
        return ""
    canonical = json.dumps(payload, sort_keys=True, default=str,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dataset_fingerprint(dataset: str, period_field: str, period: str) -> str:
    """What the underlying files were when this figure was calculated.

    The catalogue's `version` says what the schema is meant to be. This says
    what the bytes actually were, so a reload of the same period is detectable
    — which is the difference between "the number changed because the formula
    changed" and "the number changed because the data did".

    Cheap on purpose: names, sizes and modification times, not contents. A
    reload that produced byte-identical files with identical timestamps would
    not be detected, and that is the right trade for a stat-only check on a
    page load.
    """
    if not dataset:
        return ""
    root = Path(settings.analytics_dir) / dataset
    if period and period_field:
        root = root / f"{period_field}={period}"
    if not root.exists():
        return ""
    parts: list[str] = []
    for index, path in enumerate(sorted(root.rglob("*.parquet"))):
        if index >= FINGERPRINT_FILE_LIMIT:
            parts.append("truncated")
            break
        try:
            stat = path.stat()
        except OSError:
            continue
        parts.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
    if not parts:
        return ""
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------- formatting


def display(value: float | None, unit: str, decimals: int) -> str:
    """The number as it should be READ, once, in one place.

    Stored on the snapshot so the screen and the PDF cannot round differently.
    Two renderers each formatting the same float is how a pack ends up saying
    14.1% on the page and 14.08% in the appendix, and that discrepancy costs
    more credibility than the rounding ever saved.
    """
    if value is None:
        return "—"
    places = max(0, min(6, int(decimals)))
    unit = (unit or "number").lower()

    if unit == "percent":
        return f"{value:,.{places}f}%"
    if unit == "ratio":
        return f"{value:,.{places}f}x"
    if unit == "currency":
        return _money(value, places)
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "days":
        rounded = f"{value:,.{places}f}"
        return f"{rounded} day" if abs(value - 1.0) < 1e-9 else f"{rounded} days"
    return f"{value:,.{places}f}"


def _money(value: float, places: int) -> str:
    """Currency, scaled so a committee reads it at a glance.

    A pack that prints 207,712,441 makes eight people count digits. The scale
    is chosen from the magnitude and named, so nobody has to guess whether the
    axis was in millions.
    """
    size = abs(value)
    if size >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.{max(1, places)}f}bn"
    if size >= 1_000_000:
        return f"{value / 1_000_000:,.{max(1, places)}f}m"
    if size >= 10_000:
        return f"{value / 1_000:,.{max(1, places)}f}k"
    return f"{value:,.{places}f}"


# ------------------------------------------------------------ classification


def _has_maturity_rule(metric: Any) -> bool:
    from backend.metrics.catalogue import PERIOD_LATEST_MATURED

    if getattr(metric, "period_rule", "") == PERIOD_LATEST_MATURED:
        return True
    return any(c.field in MATURITY_FIELDS for c in getattr(metric, "scope", ()))


def classify(metric: Any, outcome: dict[str, Any]) -> tuple[str, str]:
    """Why this metric has no value — asked of the data, not of the wording.

    Called only when there is no value. The questions are asked most specific
    first, because a broader answer that is also true is the wrong one to give:

      1. Does the lake hold ANY rows for this period? No -> PERIOD_MISSING.
      2. Does it hold rows inside the metric's own scope? No -> the scope
         emptied it, which is NOT_MATURED if the scope is a maturity rule and
         NO_DATA otherwise.
      3. Is the denominator zero? -> NO_DATA. A share of nothing has no value,
         and 0.0% would be a claim about the book that the book does not make.
      4. Otherwise the arithmetic itself failed -> CALCULATION_FAILED, which
         is a platform problem and is meant to look like one.

    Two and three in that order specifically. An immature cohort produces a
    zero denominator — every row is filtered out before it is counted — so a
    zero-denominator test placed first swallows every maturity case and tells
    the reader "the population is empty" when the truth is "the outcome has
    not happened yet". Both sentences are true; only one of them tells
    somebody when to come back.
    """
    from backend.data_access.protocol import DataAccessError
    from backend.metrics import service as metrics

    said = str(outcome.get("unavailable") or "")
    calculation = dict(outcome.get("calculation") or {})
    period = str(outcome.get("period") or "")

    datasets = tuple(getattr(metric, "datasets", ()) or ())
    if not datasets or not period:
        return CALCULATION_FAILED, said or (
            "This metric could not be calculated and did not say why.")

    try:
        anywhere = metrics.periods_with_rows(datasets, ())
    except DataAccessError as e:
        # The lake itself could not be read. That is not a gap in the book.
        return CALCULATION_FAILED, said or str(e)

    if period not in anywhere:
        latest = anywhere[-1] if anywhere else ""
        tail = (f" The most recent period held is {latest}." if latest
                else " No period of this source is held at all.")
        return PERIOD_MISSING, (
            f"{datasets[0]} holds no rows for {period}.{tail}")

    scope = tuple(getattr(metric, "scope", ()) or ())
    if scope:
        try:
            in_scope = metrics.periods_with_rows(datasets, scope)
        except DataAccessError as e:
            return CALCULATION_FAILED, said or str(e)
        if period not in in_scope:
            if _has_maturity_rule(metric):
                latest = in_scope[-1] if in_scope else ""
                tail = (f" The most recent period with closed windows is "
                        f"{latest}." if latest else "")
                return NOT_MATURED, (
                    f"No {period} row has had its performance window close "
                    f"yet, so this outcome has not happened, rather than "
                    f"having happened zero times.{tail}")
            return NO_DATA, (
                said or f"Nothing in {period} is inside this metric's scope, "
                "so it has no value here. That is a fact about the "
                "population, not a failure.")

    denominator = calculation.get("denominator") or {}
    if isinstance(denominator, dict) and denominator.get("value") == 0:
        return NO_DATA, (
            said or f"The denominator is zero for {period}, so this metric "
            "has no value. That is a fact about the population, not a "
            "failure.")

    if int(calculation.get("rows_considered") or 0) == 0:
        return NO_DATA, said or (
            f"No {period} row matched this metric's terms.")

    return CALCULATION_FAILED, said or (
        "This metric could not be calculated and did not say why.")


# ------------------------------------------------------------- the capture


def measure(metric_id: str, *, period: str = "", comparison_period: str = "",
            filters: dict[str, Any] | None = None,
            user_id: int | None = None,
            readable: list[str] | None = None,
            question: str = "") -> Figure:
    """Calculate one governed metric and describe it completely.

    Every path into a snapshot comes through here, so there is exactly one
    place that decides what "available" means and exactly one that produces
    the display string.
    """
    from backend.metrics import service as metrics

    filters = dict(filters or {})
    try:
        metric = metrics.resolve(metric_id, user_id=user_id, readable=readable)
    except metrics.MetricNotFound as e:
        return Figure(
            metric_id=metric_id, period=period, filters=filters,
            availability=METRIC_UNAVAILABLE, unavailable_reason=str(e),
            display_value="—", governed=False)
    except PermissionError as e:
        # A reader who may not see the source is told that, and is told
        # nothing about the figure — not its magnitude, not its direction.
        return Figure(
            metric_id=metric_id, period=period, filters=filters,
            availability=NOT_AUTHORISED, unavailable_reason=str(e),
            display_value="—")

    outcome = metrics.value(metric_id, period=period, user_id=user_id,
                            readable=readable, question=question)
    calculation = dict(outcome.get("calculation") or {})
    resolved_period = str(outcome.get("period") or period)

    figure = Figure(
        metric_id=metric_id,
        metric_name=metric.name,
        metric_version=str(metric.version or ""),
        formula_hash=formula_hash(metric),
        period=resolved_period,
        comparison_period=comparison_period,
        filters=filters,
        unit=str(outcome.get("unit") or metric.unit),
        decimals=int(outcome.get("decimals") or metric.decimals),
        higher_is_better=metric.higher_is_better,
        rows_considered=int(calculation.get("rows_considered") or 0),
        dataset=str(calculation.get("dataset") or ""),
        source_fields=list(metric.fields),
        calculation=calculation,
        run_id=str(calculation.get("run_id") or ""),
        sql=str(calculation.get("sql") or ""),
        verification_state=_verification_of(metric),
        governed=str(getattr(metric, "origin", "")).upper() != "USER",
    )

    numerator = calculation.get("numerator") or {}
    denominator = calculation.get("denominator") or {}
    if isinstance(numerator, dict):
        figure.numerator = numerator.get("value")
    if isinstance(denominator, dict):
        figure.denominator = denominator.get("value")

    figure.dataset_version = _dataset_version(figure.dataset, resolved_period)

    if outcome.get("value") is None:
        figure.availability, figure.unavailable_reason = classify(
            metric, outcome)
        figure.display_value = "—"
        return figure

    figure.value = float(outcome["value"])
    figure.availability = OK
    figure.display_value = display(figure.value, figure.unit, figure.decimals)

    if comparison_period:
        before = metrics.value(metric_id, period=comparison_period,
                               user_id=user_id, readable=readable)
        # A comparison that could not be computed is left as None rather than
        # as zero. "Down 14.1 points" against a missing base is worse than no
        # comparison at all.
        if before.get("value") is not None:
            figure.comparison_value = float(before["value"])

    return figure


def _verification_of(metric: Any) -> str:
    """Whether somebody has checked this metric against their own number."""
    if getattr(metric, "verified_at", ""):
        return "VERIFIED"
    return "NOT_VERIFIED"


def _dataset_version(dataset: str, period: str) -> str:
    """The catalogue version and the file fingerprint, together.

    Both, because they answer different questions: the version says which
    schema this is, and the fingerprint says whether these particular bytes
    have been replaced since.
    """
    if not dataset:
        return ""
    declared = ""
    period_field = ""
    try:
        from backend.data_access.catalog import get_catalog

        definition = get_catalog().dataset(dataset)
        declared = str(getattr(definition, "version", "") or "")
        period_field = str(getattr(definition, "period_field", "") or "")
    except Exception:  # noqa: BLE001 - a fingerprint is still worth having
        logger.debug("no catalogue entry for %s while versioning a snapshot",
                     dataset, exc_info=True)
    print_ = dataset_fingerprint(dataset, period_field, period)
    return "@".join(p for p in (declared, print_) if p)


# ------------------------------------------------------------- writing rows


def write(session: Any, *, pack: Any, figure: Figure,
          user_id: int | None = None, lens_id: int | None = None
          ) -> PlaybookSnapshot:
    """Persist one figure against a pack, at the pack's current version.

    Append-only. This function never updates an existing row, which is why
    refreshing a draft is safe against an approved pack sharing the metric:
    the approved pack points at its own row and that row is untouched.
    """
    row = PlaybookSnapshot(
        pack_id=int(pack.id),
        pack_version=int(pack.version),
        metric_id=figure.metric_id,
        metric_name=figure.metric_name,
        metric_version=figure.metric_version,
        formula_hash=figure.formula_hash,
        period=figure.period,
        comparison_period=figure.comparison_period,
        filters=dict(figure.filters),
        value=figure.value,
        comparison_value=figure.comparison_value,
        display_value=figure.display_value,
        unit=figure.unit,
        decimals=figure.decimals,
        higher_is_better=figure.higher_is_better,
        numerator=figure.numerator,
        denominator=figure.denominator,
        rows_considered=figure.rows_considered,
        series=list(figure.series),
        availability=figure.availability,
        unavailable_reason=figure.unavailable_reason,
        dataset=figure.dataset,
        dataset_version=figure.dataset_version,
        source_fields=list(figure.source_fields),
        calculation=dict(figure.calculation),
        run_id=figure.run_id,
        sql=figure.sql,
        lens_id=lens_id,
        verification_state=figure.verification_state,
        governed=figure.governed,
        calculated_by=user_id,
    )
    session.add(row)
    session.flush()
    return row


def from_row(row: Any) -> Figure:
    """A stored snapshot, read back as the figure it was.

    The export and the comparison both read snapshots rather than recomputing,
    and both go through this so neither can quietly re-derive a display string
    that differs from the one the committee saw.
    """
    return Figure(
        metric_id=str(row.metric_id), metric_name=str(row.metric_name),
        metric_version=str(row.metric_version),
        formula_hash=str(row.formula_hash), period=str(row.period),
        comparison_period=str(row.comparison_period),
        filters=dict(row.filters or {}), value=row.value,
        comparison_value=row.comparison_value,
        display_value=str(row.display_value), unit=str(row.unit),
        decimals=int(row.decimals), higher_is_better=row.higher_is_better,
        numerator=row.numerator, denominator=row.denominator,
        rows_considered=int(row.rows_considered), series=list(row.series or []),
        availability=str(row.availability),
        unavailable_reason=str(row.unavailable_reason),
        dataset=str(row.dataset), dataset_version=str(row.dataset_version),
        source_fields=list(row.source_fields or []),
        calculation=dict(row.calculation or {}), run_id=str(row.run_id),
        sql=str(row.sql), verification_state=str(row.verification_state),
        governed=bool(row.governed))


def movement(figure: Figure) -> dict[str, Any]:
    """How this figure moved, in the direction the metric cares about.

    Returns nothing rather than guessing when either side is missing. A
    movement computed against an absent comparison is the most confidently
    wrong sentence a pack can contain.
    """
    if figure.value is None or figure.comparison_value is None:
        return {"available": False}
    change = figure.value - figure.comparison_value
    base = abs(figure.comparison_value)
    relative = (change / base) if base > 1e-12 else None
    direction = "flat"
    if abs(change) > 1e-12:
        direction = "up" if change > 0 else "down"
    better: bool | None = None
    if figure.higher_is_better is not None and direction != "flat":
        better = (direction == "up") == bool(figure.higher_is_better)
    return {
        "available": True,
        "change": change,
        "relative": relative,
        "direction": direction,
        "better": better,
        "display": display(change, figure.unit, figure.decimals),
        "from": figure.comparison_value,
        "from_display": display(figure.comparison_value, figure.unit,
                                figure.decimals),
    }


__all__ = [
    "CALCULATION_FAILED", "Figure", "METRIC_UNAVAILABLE", "MATURITY_FIELDS",
    "NOT_AUTHORISED", "NOT_MATURED", "NO_DATA", "OK", "PERIOD_MISSING",
    "PRESENTABLE", "classify", "dataset_fingerprint", "display",
    "formula_hash", "from_row", "measure", "movement", "write",
]
