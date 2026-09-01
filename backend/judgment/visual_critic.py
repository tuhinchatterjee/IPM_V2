"""
The Visual Critic: twelve checks between choosing a chart and drawing it. §88.

    "If the critic rejects the chart: choose the next valid candidate or a
     table."

Why a second pass at all
------------------------
§87 scores a candidate from the SHAPE of a result — how many categories, how
long the labels, how many periods. That is everything you can know before the
chart is built and nothing you can only know after. The axis that got bound to
the wrong field, the total that does not match the table beside it, the
four-decimal label, the legend with no accessible equivalent: all of those are
properties of the built chart, and a check that ran before it was built cannot
see any of them.

So the critic runs last, on the thing that is about to be rendered. It is the
same argument as the grounding check in §79: a check inside the chooser is a
preference, and a preference is not a control.

The reconciliation check is the one that matters
-------------------------------------------------
A chart whose bars do not add up to the table underneath it is the single
worst thing this system could put in front of a credit committee, because both
numbers are on screen and only one of them is right. Every other check here
prevents a chart that reads badly; that one prevents a chart that lies. It is
the only check with no tolerance for judgement — the figures match or the
chart does not render.

Falling back is not failing
----------------------------
A rejected chart is replaced by the next candidate §87 accepted, and if none
remains, by a table. The table is never wrong. A product that renders a
doubtful chart because the alternative feels like a climbdown has chosen its
own dignity over the reader's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.judgment import visual_grammar as vg

CRITIC_VERSION = "1.0.0"

# ------------------------------------------------------------ §88's twelve
AXES = "axes_semantically_valid"
MEASURE_AS_LABEL = "measure_not_used_as_category"
LABELS = "labels_readable"
UNITS = "units_correct"
ORDERING = "ordering_meaningful"
CATEGORY_COUNT = "category_count_manageable"
SCALE = "scale_not_misleading"
THIRD_DIMENSION = "third_dimension_independent"
RECONCILES = "values_reconcile_to_table"
PRECISION = "display_precision"
ACCESSIBLE = "accessible_alternative"
MISSING = "missing_values_handled"

CHECKS: tuple[str, ...] = (
    AXES, MEASURE_AS_LABEL, LABELS, UNITS, ORDERING, CATEGORY_COUNT, SCALE,
    THIRD_DIMENSION, RECONCILES, PRECISION, ACCESSIBLE, MISSING,
)

#: What each check is actually asking, in the words a reviewer would use.
ASKS: dict[str, str] = {
    AXES: "Does each axis carry a field whose role that axis can take?",
    MEASURE_AS_LABEL: "Is a quantity being used where a category name "
                      "belongs?",
    LABELS: "Will the labels be readable at the size this renders at?",
    UNITS: "Is every series in the unit its axis claims?",
    ORDERING: "Is the order on screen the order the data has?",
    CATEGORY_COUNT: "Are there few enough categories to tell apart?",
    SCALE: "Does the axis exaggerate the difference?",
    THIRD_DIMENSION: "Is the third dimension independent and worth having?",
    RECONCILES: "Do the plotted values equal the table's?",
    PRECISION: "Is the display precision at most two decimals?",
    ACCESSIBLE: "Is there a table or summary for a reader who cannot use the "
                "chart?",
    MISSING: "Are gaps shown as gaps rather than as zeros?",
}

#: A failure here is not a chart that reads poorly — it is a chart that
#: asserts something untrue. These cannot be waived, argued down, or
#: outweighed by the other nine passing.
FATAL: frozenset[str] = frozenset({AXES, MEASURE_AS_LABEL, RECONCILES, SCALE,
                                    UNITS})

PASS = "PASS"
FAIL = "FAIL"
#: The check does not apply to this chart kind — a scatter has no ordering to
#: be meaningful. Deliberately distinct from PASS: §88's checks are only
#: evidence of anything if a reader can tell which ones ran.
NOT_APPLICABLE = "NOT_APPLICABLE"
#: Nothing was supplied to check against. Never PASS — the assurance rules
#: this system is built on say a skipped check is not a passed one, and the
#: reconciliation check in particular passes far too easily when the table it
#: compares against was never handed over.
UNCHECKED = "UNCHECKED"

OUTCOMES: tuple[str, ...] = (PASS, FAIL, NOT_APPLICABLE, UNCHECKED)

#: Checks that must actually run. An UNCHECKED here rejects the chart, because
#: the alternative is rendering a chart nobody compared with its own figures.
MANDATORY: frozenset[str] = frozenset({AXES, MEASURE_AS_LABEL, RECONCILES,
                                        ACCESSIBLE})

#: The display contract, from P0.12. Two decimals, everywhere, always.
MAX_DECIMALS = 2

#: How far a plotted value may differ from the table's before the chart is
#: refused. Floating-point noise, and nothing else: a rounding difference the
#: reader can see is a difference the reader will ask about.
TOLERANCE = 1e-6


@dataclass
class Chart:
    """The built chart the critic is handed, as it will render.

    Deliberately the RENDERED values rather than the query that produced them.
    The failure this catches is a chart built correctly from a result that was
    then transformed for display — re-aggregated, re-sorted, unit-converted —
    and a critic reading the query would agree with the chart and miss it.
    """

    chart: str = vg.TABLE
    #: Field bound to each of §85's slots.
    bindings: dict[str, str] = field(default_factory=dict)
    #: Role of the field in each slot.
    roles: dict[str, str] = field(default_factory=dict)
    #: Category labels in the order they will appear.
    labels: list[str] = field(default_factory=list)
    #: Plotted values, keyed by series name.
    series: dict[str, list[float | None]] = field(default_factory=dict)
    #: The unit each series claims.
    units: dict[str, str] = field(default_factory=dict)
    axis_starts_at_zero: bool = True
    #: The order the labels are in: "as_given", "by_value", "by_ordinal".
    ordering: str = "as_given"
    decimals: int = 0
    has_accessible_table: bool = False
    #: How gaps are drawn: "gap", "zero", "interpolated".
    missing_shown_as: str = "gap"
    third_dimension_field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"chart": self.chart,
                "label": vg.CHART_LABEL.get(self.chart, self.chart),
                "bindings": dict(self.bindings), "roles": dict(self.roles),
                "labels": list(self.labels),
                "series": {k: list(v) for k, v in self.series.items()},
                "units": dict(self.units),
                "axis_starts_at_zero": self.axis_starts_at_zero,
                "ordering": self.ordering, "decimals": self.decimals,
                "has_accessible_table": self.has_accessible_table,
                "missing_shown_as": self.missing_shown_as,
                "third_dimension_field": self.third_dimension_field}


@dataclass
class Table:
    """What the chart is checked against.

    The table is the source of truth. Where they disagree the chart is wrong,
    not the table — the reader can add up a table.
    """

    #: Values keyed by series name, in the same category order as the chart.
    values: dict[str, list[float | None]] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)
    #: The order the result came out in, when it has an inherent one.
    ordinal_order: list[str] = field(default_factory=list)


@dataclass
class Finding:
    """One of §88's twelve, and what it found."""

    check: str
    outcome: str = UNCHECKED
    detail: str = ""

    @property
    def asks(self) -> str:
        return ASKS.get(self.check, "")

    @property
    def fatal(self) -> bool:
        return self.outcome == FAIL and self.check in FATAL

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "asks": self.asks,
                "outcome": self.outcome, "detail": self.detail,
                "fatal": self.fatal}


@dataclass
class Verdict:
    """Whether this chart may render, and everything that decided it."""

    chart: str = vg.TABLE
    findings: list[Finding] = field(default_factory=list)
    approved: bool = False

    def get(self, check: str) -> Finding | None:
        return next((f for f in self.findings if f.check == check), None)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.outcome == FAIL]

    @property
    def unchecked(self) -> list[Finding]:
        return [f for f in self.findings
                if f.outcome == UNCHECKED and f.check in MANDATORY]

    def why(self) -> str:
        if self.approved:
            return (f"{vg.CHART_LABEL.get(self.chart, self.chart)} passed all "
                    f"{len([f for f in self.findings if f.outcome == PASS])} "
                    "applicable checks.")
        reasons = [f.detail for f in self.failures if f.detail]
        reasons += [f"{ASKS.get(f.check, f.check)} — nothing was supplied to "
                    "check against" for f in self.unchecked]
        return (f"{vg.CHART_LABEL.get(self.chart, self.chart)} was refused: "
                + "; ".join(reasons) + ".")

    def to_dict(self) -> dict[str, Any]:
        return {"version": CRITIC_VERSION, "chart": self.chart,
                "approved": self.approved,
                "findings": [f.to_dict() for f in self.findings],
                "failed": [f.check for f in self.failures],
                "unchecked": [f.check for f in self.unchecked],
                "why": self.why()}


def _values_match(drawn: list[float | None],
                  tabled: list[float | None]) -> tuple[bool, str]:
    if len(drawn) != len(tabled):
        return False, (f"the chart plots {len(drawn)} points against "
                       f"{len(tabled)} rows in the table")
    for index, (left, right) in enumerate(zip(drawn, tabled, strict=True)):
        if left is None and right is None:
            continue
        if left is None or right is None:
            return False, (f"point {index + 1} is missing on one side and "
                           "present on the other")
        if abs(float(left) - float(right)) > TOLERANCE:
            return False, (f"point {index + 1} is drawn as {left} and tabled "
                           f"as {right}")
    return True, ""


def review(chart: Chart, table: Table | None = None) -> Verdict:
    """§88's twelve checks, on the chart that is about to render."""
    verdict = Verdict(chart=chart.chart)
    found: dict[str, Finding] = {c: Finding(check=c) for c in CHECKS}

    def mark(check: str, outcome: str, detail: str = "") -> None:
        found[check].outcome = outcome
        found[check].detail = detail

    # A table is not a chart and none of the chart checks describe it. It is
    # the fallback everything else falls to, so it approves.
    if chart.chart == vg.TABLE:
        for check in CHECKS:
            mark(check, NOT_APPLICABLE, "a table is not a chart")
        mark(ACCESSIBLE, PASS, "the table is its own accessible form")
        verdict.findings = [found[c] for c in CHECKS]
        verdict.approved = True
        return verdict

    # 1 & 2 — axes and the measure-as-label failure. Delegated to §85's roles
    # rather than restated, so a role reclassified in the grammar cannot leave
    # the critic checking the old meaning.
    compatibility, problems = vg.compatible(chart.chart, chart.roles,
                                            measures=len(chart.series))
    if not chart.roles:
        mark(AXES, UNCHECKED, "no field roles were supplied")
    elif compatibility:
        mark(AXES, PASS)
    else:
        mark(AXES, FAIL, "; ".join(problems))

    label_slots = [s for s in vg.LABEL_SLOTS if chart.roles.get(s)]
    misused = [s for s in label_slots if vg.plottable(chart.roles[s])]
    if not chart.roles:
        mark(MEASURE_AS_LABEL, UNCHECKED, "no field roles were supplied")
    elif misused:
        mark(MEASURE_AS_LABEL, FAIL,
             f"the {misused[0]} axis carries {chart.roles[misused[0]]}, which "
             "is a quantity and not a category name")
    else:
        mark(MEASURE_AS_LABEL, PASS)

    # 3 — readability.
    if not chart.labels:
        mark(LABELS, NOT_APPLICABLE, "this chart has no category labels")
    else:
        longest = max(len(str(label)) for label in chart.labels)
        if chart.chart in vg.VERTICAL_LABELS and longest > vg.MAX_LABEL:
            mark(LABELS, FAIL,
                 f"labels up to {longest} characters would be rotated under a "
                 "vertical axis")
        else:
            mark(LABELS, PASS)

    # 4 — units. Two series in different units on one axis is a chart of two
    # unrelated things drawn as though they were comparable.
    if not chart.units or table is None or not table.units:
        mark(UNITS, UNCHECKED, "no units were supplied")
    else:
        wrong = [name for name, unit in chart.units.items()
                 if name in table.units and table.units[name] != unit]
        distinct = {u for u in chart.units.values() if u}
        if wrong:
            mark(UNITS, FAIL,
                 f"{wrong[0]} is drawn as {chart.units[wrong[0]]} and "
                 f"computed as {table.units[wrong[0]]}")
        elif len(distinct) > 1 and chart.chart not in (vg.SCATTER, vg.BUBBLE,
                                                       vg.RISK_LANDSCAPE):
            mark(UNITS, FAIL,
                 "series in " + " and ".join(sorted(distinct))
                 + " share one axis and are not comparable")
        else:
            mark(UNITS, PASS)

    # 5 — ordering. Sorting rating grades by their ECL puts CCC beside AA and
    # calls it a ranking.
    ordinal = any(chart.roles.get(s) in vg.ORDERED for s in vg.LABEL_SLOTS)
    if not chart.labels:
        mark(ORDERING, NOT_APPLICABLE, "this chart has no ordered axis")
    elif ordinal and chart.ordering == "by_value":
        mark(ORDERING, FAIL,
             "an ordinal axis is sorted by value, which destroys the order "
             "that is the information")
    elif table is not None and table.ordinal_order \
            and chart.labels != table.ordinal_order:
        mark(ORDERING, FAIL,
             "the chart's order does not match the order the result has")
    else:
        mark(ORDERING, PASS)

    # 6 — category count, against §87's per-chart ceilings.
    ceiling = vg.CATEGORY_CEILING.get(chart.chart, 20)
    if not chart.labels:
        mark(CATEGORY_COUNT, NOT_APPLICABLE, "this chart has no categories")
    elif len(chart.labels) > ceiling:
        mark(CATEGORY_COUNT, FAIL,
             f"{len(chart.labels)} categories in "
             f"{vg.CHART_LABEL.get(chart.chart, chart.chart)}, which reads to "
             f"about {ceiling}")
    else:
        mark(CATEGORY_COUNT, PASS)

    # 7 — scale. The one charting failure with its own literature.
    if chart.chart not in vg.LENGTH_ENCODED:
        mark(SCALE, NOT_APPLICABLE,
             "this chart does not encode value as a length")
    elif not chart.axis_starts_at_zero:
        mark(SCALE, FAIL,
             "the value is encoded as a length and the axis does not start at "
             "zero, which exaggerates every difference on screen")
    else:
        mark(SCALE, PASS)

    # 8 — the third dimension.
    if chart.chart not in (vg.BUBBLE, vg.RISK_LANDSCAPE):
        mark(THIRD_DIMENSION, NOT_APPLICABLE,
             "this chart has no third dimension")
    elif not chart.third_dimension_field:
        mark(THIRD_DIMENSION, FAIL,
             "a three-dimensional chart with no third measure is decoration")
    elif chart.third_dimension_field in (
            chart.bindings.get("value"), chart.bindings.get("second_value")):
        mark(THIRD_DIMENSION, FAIL,
             f"{chart.third_dimension_field} is already on an axis, so the "
             "size restates a number the reader can see")
    else:
        mark(THIRD_DIMENSION, PASS)

    # 9 — reconciliation. The check that prevents a chart that lies rather
    # than one that reads badly.
    if table is None or not table.values:
        mark(RECONCILES, UNCHECKED,
             "no table was supplied to reconcile against")
    else:
        mismatches = []
        for name, drawn in chart.series.items():
            if name not in table.values:
                mismatches.append(f"{name} is plotted and is not in the table")
                continue
            ok, detail = _values_match(drawn, table.values[name])
            if not ok:
                mismatches.append(f"{name}: {detail}")
        missing = [n for n in table.values if n not in chart.series]
        if mismatches:
            mark(RECONCILES, FAIL, "; ".join(mismatches))
        elif not chart.series:
            mark(RECONCILES, UNCHECKED, "the chart plots no series")
        else:
            mark(RECONCILES, PASS,
                 f"{len(missing)} tabled series not plotted" if missing else "")

    # 10 — precision.
    if chart.decimals > MAX_DECIMALS:
        mark(PRECISION, FAIL,
             f"{chart.decimals} decimals on screen, where the display "
             f"contract is {MAX_DECIMALS}")
    else:
        mark(PRECISION, PASS)

    # 11 — the accessible alternative.
    mark(ACCESSIBLE, PASS if chart.has_accessible_table else FAIL,
         "" if chart.has_accessible_table else
         "no table or summary accompanies the chart")

    # 12 — missing values. Drawing a gap as a zero states that something was
    # measured and was nothing, which is a different claim entirely.
    gaps = any(v is None for values in chart.series.values() for v in values)
    if not gaps:
        mark(MISSING, NOT_APPLICABLE, "nothing is missing")
    elif chart.missing_shown_as == "gap":
        mark(MISSING, PASS)
    else:
        mark(MISSING, FAIL,
             f"missing values are drawn as {chart.missing_shown_as}, which "
             "states that something was measured and was nothing")

    verdict.findings = [found[c] for c in CHECKS]
    verdict.approved = not verdict.failures and not verdict.unchecked
    return verdict


@dataclass
class Rendered:
    """What actually goes on screen, and everything that was refused first."""

    chart: str = vg.TABLE
    verdict: Verdict | None = None
    #: Every candidate the critic refused, in the order it tried them.
    refused: list[Verdict] = field(default_factory=list)
    fell_back_to_table: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"version": CRITIC_VERSION, "chart": self.chart,
                "label": vg.CHART_LABEL.get(self.chart, self.chart),
                "verdict": self.verdict.to_dict() if self.verdict else None,
                "refused": [v.to_dict() for v in self.refused],
                "fell_back_to_table": self.fell_back_to_table,
                "why": self.verdict.why() if self.verdict else ""}


def render(candidates: list[Chart], table: Table | None = None) -> Rendered:
    """§88's rule: the first candidate that passes, or a table.

    Every refusal is kept. A product that showed only what it drew would make
    the critic invisible, and an invisible control is one nobody maintains.
    """
    result = Rendered()
    for candidate in candidates:
        verdict = review(candidate, table)
        if verdict.approved:
            result.chart = candidate.chart
            result.verdict = verdict
            result.fell_back_to_table = (candidate.chart == vg.TABLE
                                         and bool(result.refused))
            return result
        result.refused.append(verdict)

    fallback = review(Chart(chart=vg.TABLE), table)
    result.chart = vg.TABLE
    result.verdict = fallback
    result.fell_back_to_table = True
    return result


__all__ = ["ACCESSIBLE", "ASKS", "AXES", "CATEGORY_COUNT", "CHECKS",
           "CRITIC_VERSION", "Chart", "FAIL", "FATAL", "Finding", "LABELS",
           "MANDATORY", "MAX_DECIMALS", "MEASURE_AS_LABEL", "MISSING",
           "NOT_APPLICABLE", "ORDERING", "OUTCOMES", "PASS", "PRECISION",
           "RECONCILES", "Rendered", "SCALE", "THIRD_DIMENSION", "TOLERANCE",
           "Table", "UNCHECKED", "UNITS", "Verdict", "render", "review"]
