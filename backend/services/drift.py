"""
What changed in this file, field by field.

The failure this exists to prevent
----------------------------------
A source system quietly starts sending EAD in units rather than millions. Every
figure in the book is a thousand times too large, every calculation is correct,
every trace is complete, and nothing anywhere looks wrong. The bank finds out
when somebody notices that a five-million facility is showing as five billion —
which, on a large book, is not next week.

The whole class of these is the same shape: the schema still matches, the load
still succeeds, and the meaning of a column changed. So a new file is compared
against the last one that was accepted, field by field, and what changed is
stated in the words a data steward argues in — not as a row count and a green
tick.

What is compared, and why each one
----------------------------------
  fields added / removed     the schema moved. Removing one breaks every
                             analysis that reads it, which is why it blocks.
  type changed               "12,345" arriving where 12345 used to be. Every
                             numeric comparison silently becomes a string one.
  null rate                  a feed that stopped populating a column looks
                             identical to one that never had it.
  cardinality                a category list that grew from 9 to 4,000 values
                             is an identifier arriving in a category column.
  new / missing category     "Stage 4" appearing, or "Real Estate" vanishing.
  numeric range              the unit change above. A magnitude shift in a
                             column's range is the only signal it gives.
  row count                  half a book arriving is a partial extract.

Severity, and what it means
---------------------------
  BLOCKING       do not publish without a person deciding. The change breaks
                 something, or is the signature of a units/meaning change.
  MATERIAL       publish only under a policy that says so. Something real
                 changed and somebody should know.
  NOTABLE        worth reading, not worth stopping for.
  INFORMATIONAL  recorded so the history is complete.

Nothing here decides anything. `apply_policy` in inbox.py does, and it does it
from these findings — which keeps "what changed" separate from "what we do
about it", because the second is a bank's decision and the first is a fact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class Severity(StrEnum):
    BLOCKING = "blocking"
    MATERIAL = "material"
    NOTABLE = "notable"
    INFORMATIONAL = "informational"


#: Ranked worst-first, so a report sorts by consequence rather than by field name.
SEVERITY_ORDER = [Severity.BLOCKING, Severity.MATERIAL, Severity.NOTABLE,
                  Severity.INFORMATIONAL]


class DriftKind(StrEnum):
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    TYPE_CHANGED = "type_changed"
    NULL_RATE_CHANGED = "null_rate_changed"
    ALL_NULL = "all_null"
    CARDINALITY_CHANGED = "cardinality_changed"
    NEW_VALUES = "new_values"
    MISSING_VALUES = "missing_values"
    RANGE_SHIFTED = "range_shifted"
    MAGNITUDE_SHIFT = "magnitude_shift"
    ROW_COUNT_CHANGED = "row_count_changed"
    NO_ROWS = "no_rows"


# ---- thresholds ------------------------------------------------------------
#
# Named rather than inlined, because a data steward WILL want to argue with
# them, and an argument about a number in a config is a different conversation
# from an argument about a number buried in a comparison.

#: A null rate moving by more than this many percentage points is material.
NULL_RATE_POINTS = 10.0
#: A category column whose distinct count changes by more than this ratio.
CARDINALITY_RATIO = 3.0
#: A numeric range whose midpoint moves by more than this ratio is a magnitude
#: shift — the signature of a unit change. 100x rather than 10x: a book really
#: can double, and really cannot become a hundred times itself in a quarter.
MAGNITUDE_RATIO = 100.0
#: A softer range move, worth reading.
RANGE_RATIO = 3.0
#: A row count moving by more than this share is material.
ROW_COUNT_SHARE = 0.25


@dataclass(frozen=True)
class FieldDrift:
    """One thing that changed, in one field."""

    field: str
    kind: str
    severity: str
    #: What changed, in a sentence a steward would write.
    detail: str
    before: Any = None
    after: Any = None
    #: Why it matters. Separate from `detail` so the interface can show the
    #: fact and the consequence differently.
    because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "kind": self.kind, "severity": self.severity,
                "detail": self.detail, "before": self.before, "after": self.after,
                "because": self.because}


@dataclass
class DriftReport:
    """Everything that changed between two versions of the same dataset."""

    dataset: str = ""
    findings: list[FieldDrift] = field(default_factory=list)
    #: True when there was nothing to compare against — a first load.
    first_load: bool = False
    previous_row_count: int = 0
    current_row_count: int = 0

    @property
    def blocking(self) -> list[FieldDrift]:
        return [f for f in self.findings if f.severity == Severity.BLOCKING]

    @property
    def material(self) -> list[FieldDrift]:
        return [f for f in self.findings if f.severity == Severity.MATERIAL]

    @property
    def clean(self) -> bool:
        """Nothing happened that anybody has to decide about."""
        return not self.blocking and not self.material

    def by_severity(self) -> list[FieldDrift]:
        rank = {s: i for i, s in enumerate(SEVERITY_ORDER)}
        return sorted(self.findings,
                      key=lambda f: (rank.get(f.severity, 9), f.field))

    def summary(self) -> str:
        if self.first_load:
            return ("First load of this dataset. There is nothing to compare it "
                    "against, so nothing here is drift.")
        if not self.findings:
            return "Nothing changed: the same fields, types, ranges and shape."
        parts = []
        for severity in SEVERITY_ORDER:
            count = sum(1 for f in self.findings if f.severity == severity)
            if count:
                parts.append(f"{count} {severity}")
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "findings": [f.to_dict() for f in self.by_severity()],
            "first_load": self.first_load,
            "previous_row_count": self.previous_row_count,
            "current_row_count": self.current_row_count,
            "blocking_count": len(self.blocking),
            "material_count": len(self.material),
            "clean": self.clean,
            "summary": self.summary(),
        }


# ---------------------------------------------------------------- comparison


def _columns(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("name")): c for c in (profile.get("columns") or [])}


def compare(previous: dict[str, Any] | None, current: dict[str, Any], *,
            dataset: str = "") -> DriftReport:
    """Compare a new profile against the last accepted one.

    `previous` is None on a first load, which is a distinct outcome rather than
    "no drift": a first load has nothing to be checked against and should not be
    reported as verified.
    """
    report = DriftReport(dataset=dataset,
                         current_row_count=int(current.get("row_count") or 0))
    if not previous:
        report.first_load = True
        if not report.current_row_count:
            report.findings.append(FieldDrift(
                field="", kind=DriftKind.NO_ROWS, severity=Severity.BLOCKING,
                detail="The file has no rows.",
                because="Publishing an empty dataset would silently empty every "
                        "analysis that reads it."))
        return report

    report.previous_row_count = int(previous.get("row_count") or 0)
    before, after = _columns(previous), _columns(current)

    _shape(report, before, after)
    for name in sorted(set(before) & set(after)):
        _field(report, name, before[name], after[name])
    return report


def _shape(report: DriftReport, before: dict[str, dict[str, Any]],
           after: dict[str, dict[str, Any]]) -> None:
    for name in sorted(set(after) - set(before)):
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.FIELD_ADDED, severity=Severity.NOTABLE,
            detail=f"'{name}' is new in this file.", after=after[name].get("inferred_type"),
            because="A new column is not a problem, but nothing maps it yet, so "
                    "nothing will read it until somebody does."))

    for name in sorted(set(before) - set(after)):
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.FIELD_REMOVED, severity=Severity.BLOCKING,
            detail=f"'{name}' is no longer in the file.",
            before=before[name].get("inferred_type"),
            because="Every analysis reading this field stops working, or starts "
                    "reading nulls. Which of the two is worse depends on the "
                    "analysis, and neither should happen without a decision."))

    current, previous = report.current_row_count, report.previous_row_count
    if current == 0:
        report.findings.append(FieldDrift(
            field="", kind=DriftKind.NO_ROWS, severity=Severity.BLOCKING,
            detail="The file has no rows.", before=previous, after=0,
            because="An empty file replacing a populated one empties every "
                    "analysis that reads it, and each one still returns "
                    "successfully."))
    elif previous:
        share = abs(current - previous) / previous
        if share > ROW_COUNT_SHARE:
            direction = "more" if current > previous else "fewer"
            report.findings.append(FieldDrift(
                field="", kind=DriftKind.ROW_COUNT_CHANGED,
                severity=Severity.MATERIAL,
                detail=(f"{current:,} rows, {share * 100:.0f}% {direction} than "
                        f"the {previous:,} last accepted."),
                before=previous, after=current,
                because="A book does not usually change size by this much between "
                        "loads. A partial extract looks exactly like this."))


def _field(report: DriftReport, name: str, before: dict[str, Any],
           after: dict[str, Any]) -> None:
    _type(report, name, before, after)
    _nulls(report, name, before, after)
    _cardinality(report, name, before, after)
    _values(report, name, before, after)
    _range(report, name, before, after)


def _type(report: DriftReport, name: str, before: dict[str, Any],
          after: dict[str, Any]) -> None:
    was, now = before.get("inferred_type"), after.get("inferred_type")
    if was == now:
        return
    # Numeric to text is the dangerous direction: every comparison silently
    # becomes a string comparison, in which "9" is greater than "10".
    dangerous = was in ("number", "integer") and now == "string"
    report.findings.append(FieldDrift(
        field=name, kind=DriftKind.TYPE_CHANGED,
        severity=Severity.BLOCKING if dangerous else Severity.MATERIAL,
        detail=f"'{name}' arrived as {now}, having been {was}.",
        before=was, after=now,
        because=("Every comparison on this field becomes a text comparison, in "
                 "which '9' is greater than '10'. Nothing fails; the answers "
                 "change." if dangerous else
                 "A type change usually means the source system changed how it "
                 "formats this column.")))


def _nulls(report: DriftReport, name: str, before: dict[str, Any],
           after: dict[str, Any]) -> None:
    was = float(before.get("null_pct") or 0.0)
    now = float(after.get("null_pct") or 0.0)
    if now >= 100.0 and was < 100.0:
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.ALL_NULL, severity=Severity.BLOCKING,
            detail=f"'{name}' is empty in every row of this file.",
            before=f"{was:.1f}% null", after="100% null",
            because="A feed that stopped populating a column is indistinguishable "
                    "from one that never had it, and every average over it "
                    "silently changes."))
        return
    if abs(now - was) > NULL_RATE_POINTS:
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.NULL_RATE_CHANGED,
            severity=Severity.MATERIAL,
            detail=(f"'{name}' is {now:.1f}% empty, having been {was:.1f}%."),
            before=round(was, 2), after=round(now, 2),
            because="Rows missing a value are dropped from some calculations and "
                    "counted as zero in others, so the same figure moves for two "
                    "different reasons."))


def _cardinality(report: DriftReport, name: str, before: dict[str, Any],
                 after: dict[str, Any]) -> None:
    was = int(before.get("unique_count") or 0)
    now = int(after.get("unique_count") or 0)
    if not was or not now:
        return
    ratio = max(was, now) / min(was, now)
    if ratio <= CARDINALITY_RATIO:
        return
    # Only interesting where the field looked like a category. An identifier
    # gaining values is what an identifier does.
    if not (before.get("is_categorical") or after.get("is_categorical")):
        return
    report.findings.append(FieldDrift(
        field=name, kind=DriftKind.CARDINALITY_CHANGED, severity=Severity.MATERIAL,
        detail=f"'{name}' has {now:,} distinct values, having had {was:,}.",
        before=was, after=now,
        because="A category column whose value count multiplies is usually an "
                "identifier arriving where a category used to be — every "
                "breakdown by it becomes one row per record."))


def _values(report: DriftReport, name: str, before: dict[str, Any],
            after: dict[str, Any]) -> None:
    """New or vanished category values.

    Only where BOTH profiles carried a complete sample. Comparing against a
    truncated list would report every value it left out as new, which trains a
    steward to ignore the report.
    """
    if not (before.get("is_categorical") and after.get("is_categorical")):
        return
    was = {str(v) for v in (before.get("sample_values") or [])}
    now = {str(v) for v in (after.get("sample_values") or [])}
    if not was or not now:
        return

    added = sorted(now - was)
    if added:
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.NEW_VALUES, severity=Severity.MATERIAL,
            detail=f"'{name}' contains values not seen before: {', '.join(added[:8])}.",
            before=sorted(was)[:8], after=added[:8],
            because="A value nothing maps falls outside every filter and every "
                    "breakdown, so the exposure carrying it disappears from the "
                    "answer rather than appearing as 'other'."))

    gone = sorted(was - now)
    if gone:
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.MISSING_VALUES, severity=Severity.NOTABLE,
            detail=f"'{name}' no longer contains: {', '.join(gone[:8])}.",
            before=gone[:8], after=sorted(now)[:8],
            because="A category that vanished may mean the book genuinely has "
                    "none, or that the source stopped sending them."))


def _range(report: DriftReport, name: str, before: dict[str, Any],
           after: dict[str, Any]) -> None:
    """The unit-change detector.

    Compared on the SPAN rather than the mean: a book whose exposure grows is a
    book, and a book whose exposure span multiplies by a hundred is a unit
    change. The mean moves for both.
    """
    keys = ("min", "max")
    if not all(k in before and k in after for k in keys):
        return
    try:
        was_span = abs(float(before["max"]) - float(before["min"]))
        now_span = abs(float(after["max"]) - float(after["min"]))
    except (TypeError, ValueError):
        return
    if was_span <= 0 or now_span <= 0:
        return

    ratio = max(was_span, now_span) / min(was_span, now_span)
    if ratio >= MAGNITUDE_RATIO:
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.MAGNITUDE_SHIFT, severity=Severity.BLOCKING,
            detail=(f"'{name}' now spans {float(after['min']):,.4g} to "
                    f"{float(after['max']):,.4g}, having spanned "
                    f"{float(before['min']):,.4g} to {float(before['max']):,.4g} "
                    f"— a factor of about {ratio:,.0f}."),
            before=[before["min"], before["max"]], after=[after["min"], after["max"]],
            because="A range that multiplies by this much between loads is the "
                    "signature of a unit change — millions arriving as units, or "
                    "a rate arriving as a fraction. Every figure stays correctly "
                    "calculated and every one of them is wrong."))
    elif ratio >= RANGE_RATIO:
        report.findings.append(FieldDrift(
            field=name, kind=DriftKind.RANGE_SHIFTED, severity=Severity.NOTABLE,
            detail=(f"'{name}' spans {float(after['min']):,.4g} to "
                    f"{float(after['max']):,.4g}, having spanned "
                    f"{float(before['min']):,.4g} to {float(before['max']):,.4g}."),
            before=[before["min"], before["max"]], after=[after["min"], after["max"]],
            because="Worth a look. A real move in the book looks like this, and "
                    "so does a changed filter upstream."))


__all__ = [
    "CARDINALITY_RATIO",
    "MAGNITUDE_RATIO",
    "NULL_RATE_POINTS",
    "ROW_COUNT_SHARE",
    "DriftKind",
    "DriftReport",
    "FieldDrift",
    "Severity",
    "compare",
]
