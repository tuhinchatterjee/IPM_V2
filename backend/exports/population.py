"""
The analytical population, read back for the calculation pack.

§24 asks the full pack to carry the calculation population itself where it is a
manageable size and the reader is authorised to see it — so a reviewer can
recompute a group total in Excel rather than take the workbook's word for it.

The runtime does not persist that population. It persists the plan, the query
and the final result; the rows the query read were never materialised outside
DuckDB. So the extract here is a fresh READ of the governed source data, at the
period and through the filters the plan recorded — the same thing a Data
Builder preview does, not a re-execution of the analysis.

That distinction is the whole design, and the sheet says it in as many words:

* what is exported is the SOURCE POPULATION, read at export time;
* it is not the joined, derived intermediate the calculation worked on;
* where joins, unsupported filters or a moved data version mean it cannot
  faithfully stand in for that population, the extract is not written at all
  and the sheet says why.

An extract that quietly differed from the analysed population would be worse
than no extract: a reviewer would reconcile against it, find a difference, and
have no way to know which of the two was wrong.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.exports.contract import MAX_INLINE_POPULATION_ROWS, ROWS_PER_SHEET

logger = logging.getLogger(__name__)

#: Filter operators the data access layer can apply faithfully on a read. A
#: plan using anything else gets no extract rather than a differently-filtered
#: one.
SUPPORTED_OPERATORS = {"=", "==", "in", "IN"}


@dataclass
class Population:
    """The source population behind one analysis, or the reason there is none."""

    dataset: str = ""
    business_name: str = ""
    period: str = ""
    grain: str = ""
    columns: list[dict[str, Any]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    filters: list[str] = field(default_factory=list)
    #: True where this is the population the calculation worked on, rather than
    #: one source among several that were joined together.
    stands_for_calculation: bool = False
    #: How many rows go on one sheet before the extract is split.
    rows_per_sheet: int = ROWS_PER_SHEET
    omitted: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return bool(self.rows) and not self.omitted

    @property
    def chunks(self) -> list[tuple[int, int]]:
        """Row ranges, one per sheet: (first row number, last row number), 1-based."""
        if not self.rows:
            return []
        size = max(1, int(self.rows_per_sheet))
        return [(start + 1, min(start + size, len(self.rows)))
                for start in range(0, len(self.rows), size)]

    def slice(self, chunk: tuple[int, int]) -> list[list[Any]]:
        first, last = chunk
        return self.rows[first - 1:last]


def extract_for(pack: Any, view: Any, *, limit: int = MAX_INLINE_POPULATION_ROWS,
                rows_per_sheet: int = ROWS_PER_SHEET) -> Population:
    """Read back the source population behind one analysis.

    Never raises. Every path that cannot produce a faithful extract sets
    `omitted` to a sentence explaining which one it was, and the workbook prints
    that sentence where the table would have been.
    """
    out = Population(rows_per_sheet=rows_per_sheet)
    scans = list(getattr(view, "scans", []))
    if not scans:
        out.omitted = (
            "This analysis ran a certified method rather than a composed plan, "
            "so there is no scanned source population to extract. The method's "
            "own inputs are recorded on the FORMULAS & QUERY sheet."
        )
        return out

    scan = scans[0]
    out.dataset = scan.dataset
    out.period = scan.period
    out.stands_for_calculation = len(scans) == 1 and not getattr(view, "joins", [])
    if not out.stands_for_calculation:
        out.notes.append(
            "This analysis read more than one source. The rows below are the "
            "primary source population only — the calculation worked on the "
            "joined table, whose row counts are on JOIN RECONCILIATION."
        )

    filters, unsupported = _filters(view)
    if unsupported:
        out.omitted = (
            "The population was not extracted because this plan filters on "
            + ", ".join(unsupported)
            + ", which cannot be re-applied on a read exactly as the query "
            "applied it. An extract filtered differently from the analysis "
            "would not reconcile, so none is offered."
        )
        return out
    out.filters = [f"{name} = {_shown(value)}" for name, value in filters.items()]

    try:
        from backend.data_access import get_data_source
        from backend.data_access.catalog import get_catalog
        from backend.data_access.context import AnalysisContext

        spec = get_catalog().dataset(scan.dataset)
        source = get_data_source()
        out.business_name = spec.business_name
        out.grain = spec.grain

        wanted = [f for f in view.fields_for(scan.dataset) if f in spec.fields]
        if not wanted:
            out.omitted = (
                "The plan recorded no readable fields for this dataset, so "
                "there is nothing to extract."
            )
            return out

        counted = source.row_count(scan.dataset, scan.period or None)
        if counted > limit:
            out.row_count = counted
            out.omitted = (
                f"This population is {counted:,} rows, above the {limit:,}-row "
                "ceiling for an inline extract. The workbook does not carry it, "
                "and does not pretend to: request a governed row-level extract "
                "for this run if the population itself is needed."
            )
            return out

        context = AnalysisContext(period=scan.period or pack.period,
                                  filters=dict(filters), user_id=pack.user_id)
        frame = source.fetch(scan.dataset, context=context,
                             fields=wanted, period=scan.period or None)
    except Exception as e:  # noqa: BLE001 - an extract is never worth an export
        logger.info("Population extract unavailable for %s: %s", scan.dataset, e)
        out.omitted = f"The population could not be read back: {e}"
        return out

    out.columns = [_column(spec, name) for name in wanted]
    out.rows = [[_cell(v) for v in row] for row in frame.itertuples(index=False)]
    out.row_count = len(out.rows)
    return out


def _filters(view: Any) -> tuple[dict[str, Any], list[str]]:
    """The plan's filters as a governed filter map, and what could not be mapped."""
    applied: dict[str, Any] = {}
    unsupported: list[str] = []
    for condition in getattr(view, "conditions", []):
        name = condition.field_name
        operator = (condition.operator or "").strip()
        if not name or operator not in SUPPORTED_OPERATORS:
            unsupported.append(
                f"{name or 'an unnamed column'} {operator or '(no operator)'}".strip()
            )
            continue
        value: Any = condition.value
        if operator.lower() == "in":
            value = [v.strip() for v in str(condition.value).split(",") if v.strip()]
        applied[name] = value
    return applied, unsupported


def _column(spec: Any, name: str) -> dict[str, Any]:
    """A population column in the shape the styling layer formats."""
    found = spec.fields.get(name)
    unit = str(getattr(found, "unit", "") or "")
    kind = str(getattr(found, "data_type", "")).lower()
    return {
        "name": name,
        "label": getattr(found, "business_name", "") or name,
        "unit": unit,
        "semantic": _semantic(name, unit, kind),
        "sensitivity": str(getattr(found, "sensitivity", "") or ""),
    }


def _semantic(name: str, unit: str, kind: str) -> str:
    """How a population column should be formatted.

    The declared unit first, because that is the governed statement. Where a
    dataset's catalogue entry carries no unit — several of the derived tables
    do not — the column's name is the next best evidence, and a percentage
    rendered to four decimals as though it were a ratio is the kind of small
    wrongness that makes a reviewer distrust the sheet.
    """
    if kind in {"string", "date", "boolean"}:
        return "identity" if name.endswith("_id") else "text"
    if unit == "%" or name.endswith(("_pct", "_rate")):
        return "percent"
    if unit == "days" or name.endswith("_days"):
        return "days"
    if unit in {"x", "score"}:
        return "ratio"
    if unit in {"grade", "stage"}:
        return "ordinal"
    if unit and unit != "count":
        return "money"
    if kind == "integer":
        return "count"
    return "ratio"


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float | int | str | bool):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):  # pragma: no cover - defensive
            return str(value)
    return str(value)


def _shown(value: Any) -> str:
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return str(value)
