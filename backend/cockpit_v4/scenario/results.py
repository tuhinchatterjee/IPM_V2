"""Section 13.1's hierarchy, and the chart kinds that actually exist.

## The hierarchy

A scenario's headline is three numbers, not one: the cohort's change, the
book's change, and the share of the book the cohort is. A reader shown a
change of 180 cannot tell whether it is 180 on 19,800 or 180 on 7,075,662,
and the two mean entirely different things. So `Summary` carries:

* counts, drawn, EAD and ECL before and after, for the cohort AND the book;
* the modelled/overlay split, where the book publishes one;
* the absolute change, the relative change, and the coverage-rate change **in
  percentage points** -- because a coverage rate is itself a percentage, and
  "coverage rose 12%" is ambiguous between 0.56% → 0.63% and 0.56% → 12.56%;
* `"not defined"` where a baseline is zero, never infinity and never a
  percentage of nothing;
* affected + unaffected = the full book, checked rather than asserted.

## The charts

Section 13.3 asks for five figures. Four map onto chart kinds this engine
already has, and one does not exist:

| Asked for | Built as | Why |
|---|---|---|
| ECL bridge | `waterfall` | a real kind (`shared_defs.schema.json:229`) |
| Method comparison | `grouped_bar` | three methods, baseline and scenario |
| Sector / stage before-after | `grouped_bar` | same shape |
| Sensitivity grid | `heatmap` | factor by parameter |
| Top contributors | `bar` plus an "Other" row | so the bars sum to the book |
| **Tornado / diverging bar** | **does not exist** | see below |

**There is no tornado chart, and one is not faked.** `BarChart` computes
`max = Math.max(high, 0)` and `width = abs(value) / max`, so −400 and +400
render as the same rectangle on the same side (`visuals.tsx:245-253`, and
the server-side SVG identically at `export.py:594-601`). A signed ranking
drawn through it would show every driver pointing the same way, which is
worse than no chart. `tornado_substitute()` returns a `waterfall` plus a
signed table and says in its caption that the requested form is unavailable
rather than quietly delivering something else.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import attribution as at
from backend.cockpit_v4.scenario import ledger as lg
from backend.cockpit_v4.scenario.errors import (
    RECONCILIATION_FAILED,
    raise_for,
)

#: What a rate change with no baseline is called. Never infinity, never a
#: large number, never zero: the quantity does not exist.
UNDEFINED = "not defined"

#: The chart kinds this engine actually has, of the ones section 13.3 wants.
WATERFALL = "waterfall"
GROUPED_BAR = "grouped_bar"
HEATMAP = "heatmap"
BAR = "bar"

#: The form that does not exist, and the note that says so wherever it is
#: asked for.
TORNADO_UNAVAILABLE = (
    "A tornado (diverging bar) chart is not available in this application. "
    "Its bar renderer takes the absolute value against a maximum floored at "
    "zero, so a -400 and a +400 draw the same rectangle on the same side and "
    "a signed ranking would show every driver pointing one way. A waterfall "
    "and a signed table are shown instead; they carry the same numbers with "
    "their direction intact.")


@dataclass(frozen=True)
class Measure:
    """One quantity, before and after, with its change stated correctly."""

    name: str
    baseline: Decimal
    scenario: Decimal
    unit: str = "SAR million"
    #: True for a rate, where the change is in PERCENTAGE POINTS and a
    #: relative change would be a second, different number.
    is_rate: bool = False

    @property
    def change(self) -> Decimal:
        return self.scenario - self.baseline

    def relative_pct(self) -> Decimal | str:
        if self.baseline == 0:
            return UNDEFINED
        return self.change / self.baseline * 100

    def change_pp(self) -> Decimal | str:
        """Percentage points. Only meaningful for a rate."""
        if not self.is_rate:
            return UNDEFINED
        return self.change

    def as_row(self) -> dict[str, str]:
        relative = self.relative_pct()
        row = {
            "measure": self.name, "unit": self.unit,
            "baseline": str(self.baseline), "scenario": str(self.scenario),
            "change": str(self.change),
            "relative_change_pct": (relative if isinstance(relative, str)
                                    else str(relative)),
        }
        if self.is_rate:
            row["change_percentage_points"] = str(self.change)
            # A rate's relative change is a real number and a different one.
            # Both are published because "coverage rose 12%" is ambiguous
            # between them, and the ambiguity is the reason this row exists.
            row["note"] = (
                "This is a RATE. Its change is stated in percentage points; "
                "the relative column is the change as a proportion of the "
                "old rate, which is a different number.")
        return row


@dataclass(frozen=True)
class Summary:
    """Section 13.1's hierarchy for one scenario, cohort and book alike."""

    domain_id: str
    period: str
    cohort_rows: int
    book_rows: int
    cohort: tuple[Measure, ...]
    book: tuple[Measure, ...]
    unaffected_baseline: Decimal
    notes: tuple[str, ...] = ()

    def measure(self, name: str, *, scope: str = "cohort") -> Measure | None:
        source = self.cohort if scope == "cohort" else self.book
        return next((m for m in source if m.name == name), None)

    def rows(self) -> list[dict[str, str]]:
        out = []
        for scope, measures in (("cohort", self.cohort), ("book", self.book)):
            for measure in measures:
                out.append({"scope": scope, **measure.as_row()})
        return out

    def check(self, *, tolerance: Decimal = lg.CURRENCY) -> None:
        """Affected plus unaffected is the book, and untouched rows are 0.

        Checked here rather than trusted, because the failure is invisible:
        a cohort total and a book total that disagree still each look like a
        number, and the percentage computed from the wrong one is wrong by
        a factor nobody can see.
        """
        cohort_ecl = self.measure("Total ECL")
        book_ecl = self.measure("Total ECL", scope="book")
        if cohort_ecl is None or book_ecl is None:
            return
        rebuilt = cohort_ecl.baseline + self.unaffected_baseline
        if abs(rebuilt - book_ecl.baseline) > tolerance:
            raise_for(RECONCILIATION_FAILED,
                      f"the cohort's baseline ECL of {cohort_ecl.baseline} "
                      f"plus the {self.unaffected_baseline} outside it is "
                      f"{rebuilt}, and the book's is {book_ecl.baseline}.",
                      field_path="results.book")
        moved_outside = ((book_ecl.scenario - cohort_ecl.scenario)
                         - self.unaffected_baseline)
        if abs(moved_outside) > tolerance:
            raise_for(RECONCILIATION_FAILED,
                      f"{moved_outside} SAR million moved outside the "
                      f"cohort. A scenario over a frozen cohort changes "
                      f"nothing beyond it, exactly.",
                      field_path="results.book")

    def headline(self) -> str:
        cohort = self.measure("Total ECL")
        book = self.measure("Total ECL", scope="book")
        if cohort is None:
            return ""
        relative = cohort.relative_pct()
        movement = (relative if isinstance(relative, str)
                    else f"{relative:+.2f}%")
        line = (f"Cohort ECL {cohort.baseline:,.2f} to "
                f"{cohort.scenario:,.2f} SAR million, {cohort.change:+,.2f} "
                f"({movement}) over {self.cohort_rows:,} rows.")
        if book is not None and book.baseline:
            book_relative = book.relative_pct()
            book_movement = (book_relative if isinstance(book_relative, str)
                             else f"{book_relative:+.2f}%")
            share = cohort.baseline / book.baseline * 100
            line += (f" On the full book of {book.baseline:,.2f} that is "
                     f"{book.change:+,.2f} ({book_movement}); the cohort is "
                     f"{share:.2f}% of the book's baseline ECL.")
        return line


def summarise(*, domain_id: str, period: str,
              cohort_before: Mapping[str, Decimal],
              cohort_after: Mapping[str, Decimal],
              book_before: Mapping[str, Decimal],
              book_after: Mapping[str, Decimal],
              cohort_rows: int, book_rows: int,
              unaffected_baseline: Decimal) -> Summary:
    """Build the hierarchy from two before/after dictionaries per scope.

    Coverage rate is derived here rather than supplied, so it is always
    `ECL / EAD` on the same scope's own numbers and cannot be a rate from
    one population printed beside a total from another.
    """
    def measures(before: Mapping[str, Decimal],
                 after: Mapping[str, Decimal]) -> tuple[Measure, ...]:
        out: list[Measure] = []
        for name, unit in (("Exposures", "count"),
                           ("Drawn", "SAR million"),
                           ("EAD", "SAR million"),
                           ("Modelled ECL", "SAR million"),
                           ("Overlay", "SAR million"),
                           ("Total ECL", "SAR million")):
            if name in before or name in after:
                out.append(Measure(
                    name=name, unit=unit,
                    baseline=Decimal(str(before.get(name, 0))),
                    scenario=Decimal(str(after.get(name, 0)))))
        ead_before = Decimal(str(before.get("EAD", 0)))
        ead_after = Decimal(str(after.get("EAD", 0)))
        if ead_before and ead_after:
            out.append(Measure(
                name="Coverage rate", unit="percent", is_rate=True,
                baseline=Decimal(str(before.get("Total ECL", 0)))
                / ead_before * 100,
                scenario=Decimal(str(after.get("Total ECL", 0)))
                / ead_after * 100))
        return tuple(out)

    made = Summary(
        domain_id=domain_id, period=period, cohort_rows=cohort_rows,
        book_rows=book_rows, cohort=measures(cohort_before, cohort_after),
        book=measures(book_before, book_after),
        unaffected_baseline=unaffected_baseline)
    made.check()
    return made


# ---- charts -------------------------------------------------------------

@dataclass(frozen=True)
class Chart:
    """A chart this engine can actually render, with its rows."""

    kind: str
    title: str
    rows: list[dict[str, Any]]
    caption: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)


def bridge_chart(bridge: at.Bridge, *, title: str = "") -> Chart:
    """§13.3's ECL bridge, as the `waterfall` kind that already exists."""
    rows = [{"label": "Baseline", "value": str(bridge.baseline),
             "kind": "total"}]
    for contribution in bridge.contributions:
        rows.append({"label": contribution.label,
                     "value": str(contribution.change), "kind": "delta"})
    if bridge.residual != 0:
        rows.append({"label": "Unexplained residual",
                     "value": str(bridge.residual), "kind": "delta"})
    rows.append({"label": "Scenario",
                 "value": str(bridge.baseline + bridge.headline),
                 "kind": "total"})
    return Chart(
        kind=WATERFALL,
        title=title or f"ECL bridge — {at.VIEW_LABELS[bridge.view]}",
        rows=rows, caption=bridge.describe())


def method_chart(comparison: Sequence[Mapping[str, Any]]) -> Chart:
    """The methods side by side, baseline and scenario, as `grouped_bar`.

    A method with no number is present as a labelled row with an empty
    value, so a reader sees that it ran and could not answer rather than
    seeing two bars where they expected three.
    """
    rows: list[dict[str, Any]] = []
    for entry in comparison:
        rows.append({"group": entry["label"], "series": "Baseline",
                     "value": entry["baseline"]})
        rows.append({"group": entry["label"], "series": "Scenario",
                     "value": entry.get("scenario") or "",
                     "note": entry.get("reason", "")})
    return Chart(
        kind=GROUPED_BAR, title="ECL by method",
        rows=rows,
        caption=("Alternative answers to one question, shown side by side. "
                 "They are never multiplied together and never averaged."))


def sensitivity_chart(slopes: Sequence[Mapping[str, Any]]) -> Chart:
    """§13.3's sensitivity grid, as the `heatmap` kind."""
    return Chart(
        kind=HEATMAP, title="Macro sensitivities",
        rows=[{"row": str(s["factor_id"]), "column": str(s["parameter"]),
               "value": str(s["native_derivative"]),
               "note": str(s.get("readiness", ""))} for s in slopes],
        caption=("Percentage points of the parameter per one native unit of "
                 "the factor. A cell whose readiness is not "
                 "SUPPORTED_ESTIMATE is shown and is not applied "
                 "automatically."))


def contributor_chart(lines: Sequence[lg.Line], *, top: int = 10) -> Chart:
    """The largest movers, with the rest as one real "Other" row.

    The remainder is a row with a real total rather than a truncation, so
    the bars still sum to the cohort's change. A chart whose bars sum to
    less than the headline invites a reader to add them and get the wrong
    answer.
    """
    ordered = sorted(lines, key=lambda ln: -abs(ln.change))
    head, tail = ordered[:top], ordered[top:]
    rows = [{"label": ln.label or ln.key, "value": str(ln.change)}
            for ln in head]
    if tail:
        rows.append({
            "label": f"Other ({len(tail):,} rows)",
            "value": str(sum((ln.change for ln in tail), Decimal(0)))})
    return Chart(
        kind=BAR, title="Largest contributors", rows=rows,
        caption=(f"The {len(head)} largest movers by absolute change, with "
                 f"the remaining {len(tail):,} rows as one row so the bars "
                 f"still sum to the cohort's change."))


def tornado_substitute(bridge: at.Bridge) -> Chart:
    """What a reader asking for a tornado gets, and why it is not one.

    Not a silent substitution: the caption says the requested form is
    unavailable and says what was drawn instead. Section 13.3 asks for the
    chart to justify its form, and "the one you asked for cannot be drawn
    correctly here" is a justification.
    """
    chart = bridge_chart(bridge, title="Driver contributions (signed)")
    return Chart(
        kind=chart.kind, title=chart.title, rows=chart.rows,
        caption=TORNADO_UNAVAILABLE + " " + chart.caption,
        notes=("tornado_unavailable",))


def signed_table(bridge: at.Bridge) -> list[dict[str, str]]:
    """The signed ranking a tornado would have shown, as a table.

    Sorted by absolute size, with the sign in the value, so the ordering a
    tornado conveys and the direction it conveys both survive.
    """
    ordered = sorted(bridge.contributions, key=lambda c: -abs(c.change))
    return [{
        "rank": str(index),
        "driver": contribution.label,
        "change_sar_mn": str(contribution.change),
        "direction": "increase" if contribution.change > 0 else (
            "decrease" if contribution.change < 0 else "no change"),
    } for index, contribution in enumerate(ordered, start=1)]


def check_chart_sums(chart: Chart, *, headline: Decimal,
                     tolerance: Decimal = lg.CURRENCY) -> None:
    """A bar chart's bars land on the headline. Checked, not hoped for."""
    if chart.kind != BAR:
        return
    total = sum((Decimal(str(r["value"])) for r in chart.rows), Decimal(0))
    if abs(total - headline) > tolerance:
        raise_for(RECONCILIATION_FAILED,
                  f"this chart's bars sum to {total} and the headline change "
                  f"is {headline}. A reader adding the bars has to land on "
                  f"the total.",
                  field_path="chart.rows")


__all__ = ["BAR", "Chart", "GROUPED_BAR", "HEATMAP", "Measure", "Summary",
           "TORNADO_UNAVAILABLE", "UNDEFINED", "WATERFALL", "bridge_chart",
           "check_chart_sums", "contributor_chart", "method_chart",
           "sensitivity_chart", "signed_table", "summarise",
           "tornado_substitute"]
