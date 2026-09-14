"""What a reader has narrowed the book to, as one governed object.

Why a typed spec rather than query parameters
----------------------------------------------
The dashboard's tiles, its band distribution, its trend chart, its borrower
table and its export all have to describe the SAME population. When each
computes its own scope from its own parameters, they drift -- the tiles say
the book, the table says the twenty rows it happened to fetch, and the chart
says something else again, while all three sit under one heading. A reader
comparing them is not comparing anything.

So the scope is one object. `FilterSpec` is built once from the request,
validated once against the governed field dictionary, and then every measure
on the screen is computed from the same filtered frame. A tile and a row
cannot disagree, because there is nothing for them to disagree about.

It is also what the chat is told the reader is looking at, and what the export
writes into its metadata sheet. One scope, four consumers, no fourth copy of
the filtering logic.

Server-side, and why
--------------------
Filtering in the browser filters the page, not the book. A reader who narrows
to exposure above five hundred million and sees four obligors has been shown
the four in the twenty that were fetched, not the four in three hundred -- and
nothing on the screen says so. Every filter here is applied to the whole
published population before anything is counted or truncated.

Configurable filterability
--------------------------
`COLUMNS` is the registry: which columns can be filtered, how each one behaves
(text, multi-select, numeric range), and what a reader calls it. The API
publishes it, so the screen builds its controls from the contract rather than
from a list that has to be kept in step by hand. Adding a filterable column is
an entry here and nothing else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from backend.early_warning.classifiers_v2 import BAND_ORDER

#: The five severity bands, from the module that defines them.
BANDS: tuple[str, ...] = tuple(BAND_ORDER)

#: What a reader calls a band. The stored value is the contract between the
#: screen and the engine; this is what goes in a chip and an export cell,
#: because "VERY_HIGH" is a constant and "Very High" is a word.
BAND_LABELS: dict[str, str] = {b: b.replace("_", " ").title() for b in BANDS}


def readable(value: str) -> str:
    return BAND_LABELS.get(str(value), str(value))

#: How a filter behaves, which is what the screen needs to draw a control.
TEXT = "text"
MULTI = "multi"
RANGE = "range"


@dataclass(frozen=True)
class Column:
    """One filterable column, and what a reader may do with it."""

    key: str
    label: str
    kind: str
    #: The frame column it filters. Usually `key`; named separately so a
    #: reader-facing key never has to match a stored column name.
    column: str = ""
    #: For a multi-select whose values are a closed set. Empty means the
    #: values are read from the data, which is how a segment list stays
    #: correct when a segment is added.
    choices: tuple[str, ...] = ()
    #: The unit a range is expressed in, for the chip and the export sheet.
    unit: str = ""

    @property
    def field(self) -> str:
        return self.column or self.key

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "field": self.field, "choices": list(self.choices),
                "unit": self.unit}


#: The registry. §28: what is filterable is configuration, not code.
COLUMNS: tuple[Column, ...] = (
    Column("customer", "Customer", TEXT, column="customer_name"),
    Column("segment", "Segment", MULTI, column="segment"),
    # Exposure is STORED in millions, which is what the table renders under
    # a "(SAR m)" header. A range control labelled plain "SAR" would invite a
    # reader to type 500,000,000 for half a billion and then show them an
    # empty table with no explanation.
    Column("exposure", "Exposure", RANGE, column="exposure", unit="SAR m"),
    Column("dpd", "Days past due", RANGE, column="dpd", unit="days"),
    Column("ews_band", "Early Warning band", MULTI, column="ews_band",
           choices=BANDS),
    Column("ews_score", "Early Warning score", RANGE, column="ews_score",
           unit="points"),
    Column("ta_band", "Trigger & Accelerator band", MULTI, column="ta_band",
           choices=BANDS),
    Column("ta_score", "Trigger & Accelerator score", RANGE,
           column="ta_score", unit="points"),
    Column("classifier_band", "Classifier band", MULTI,
           column="classifier_band", choices=BANDS),
    Column("classifier_score", "Classifier score", RANGE,
           column="classifier_score", unit="points"),
    Column("dominant_driver", "Dominant driver", MULTI,
           column="dominant_driver"),
)

BY_KEY: dict[str, Column] = {c.key: c for c in COLUMNS}

#: What the table may be sorted by. The filterable columns, plus the
#: identifier -- a reader sorting by name is sorting, not filtering.
SORTABLE: tuple[str, ...] = tuple(
    [c.field for c in COLUMNS] + ["customer_id"])

#: The most rows one request will return. A reader asking for the whole book
#: on a screen gets a page of it and a count of the rest; the export is where
#: the complete result belongs.
MAX_PAGE = 500
DEFAULT_PAGE = 50


class InvalidFilter(ValueError):
    """A filter that cannot be honoured, said precisely enough to fix."""


def _clean(value: Any) -> float | None:
    """A number, or nothing. Never NaN, which compares false with itself."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvalidFilter(f"{value!r} is not a number.") from None
    if math.isnan(number) or math.isinf(number):
        raise InvalidFilter(f"{value!r} is not a usable number.")
    return number


def _strings(values: Any, *, key: str) -> tuple[str, ...]:
    if values is None or values == "":
        return ()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        raise InvalidFilter(f"{key} takes a list of values.")
    return tuple(str(v) for v in values if str(v).strip())


@dataclass
class Range:
    """A closed interval, either end of which may be open."""

    minimum: float | None = None
    maximum: float | None = None

    @property
    def active(self) -> bool:
        return self.minimum is not None or self.maximum is not None

    def to_dict(self) -> dict[str, Any]:
        return {"min": self.minimum, "max": self.maximum}


@dataclass
class FilterSpec:
    """One description of the population every measure is computed over."""

    period: str = ""
    #: Free text against the customer name. A reader typing three letters
    #: means "the ones containing this", not "the one called exactly this".
    customer: str = ""
    #: Multi-selects, by column key. Empty means no restriction, which is
    #: not the same as "none selected" -- a spec with an empty band list
    #: covers every band, and one with all five also covers every band.
    selections: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: Numeric ranges, by column key.
    ranges: dict[str, Range] = field(default_factory=dict)

    sort_by: str = "ews_score"
    descending: bool = True
    limit: int = DEFAULT_PAGE
    offset: int = 0

    # ------------------------------------------------------------- parsing

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "FilterSpec":
        """Build a spec from a request body, refusing anything ungoverned.

        An unknown filter key is refused rather than ignored. Ignoring it
        would show a reader a filter chip for something that was never
        applied, which is worse than an error: the count would be right for
        a population they did not ask for.
        """
        raw = dict(payload or {})
        spec = cls()
        spec.period = str(raw.pop("period", "") or "")
        spec.customer = str(raw.pop("customer", "") or "").strip()

        sort_by = str(raw.pop("sort_by", "") or "ews_score")
        if sort_by not in SORTABLE:
            raise InvalidFilter(
                f"The table cannot be sorted by {sort_by!r}. "
                f"Sortable: {', '.join(sorted(SORTABLE))}.")
        spec.sort_by = sort_by
        spec.descending = bool(raw.pop("descending", True))

        limit = int(raw.pop("limit", DEFAULT_PAGE) or DEFAULT_PAGE)
        spec.limit = max(1, min(limit, MAX_PAGE))
        spec.offset = max(0, int(raw.pop("offset", 0) or 0))

        filters = raw.pop("filters", None)
        if filters is None:
            filters = raw  # a flat body is accepted too
            raw = {}
        if not isinstance(filters, dict):
            raise InvalidFilter("`filters` must be an object keyed by column.")

        for key, value in filters.items():
            column = BY_KEY.get(str(key))
            if column is None:
                raise InvalidFilter(
                    f"{key!r} is not a filterable column. Filterable: "
                    f"{', '.join(sorted(BY_KEY))}.")
            if column.kind == TEXT:
                spec.customer = str(value or "").strip()
            elif column.kind == MULTI:
                chosen = _strings(value, key=str(key))
                if column.choices:
                    unknown = [c for c in chosen if c not in column.choices]
                    if unknown:
                        raise InvalidFilter(
                            f"{column.label} has no value "
                            f"{unknown[0]!r}. Values: "
                            f"{', '.join(column.choices)}.")
                if chosen:
                    spec.selections[column.key] = chosen
            else:
                if not isinstance(value, dict):
                    raise InvalidFilter(
                        f"{column.label} takes a range, as "
                        '{"min": ..., "max": ...}.')
                low = _clean(value.get("min"))
                high = _clean(value.get("max"))
                if low is not None and high is not None and low > high:
                    raise InvalidFilter(
                        f"{column.label}: the minimum {low:g} is above the "
                        f"maximum {high:g}, so nothing can match.")
                span = Range(low, high)
                if span.active:
                    spec.ranges[column.key] = span

        for leftover in raw:
            raise InvalidFilter(f"{leftover!r} is not something this "
                                "dashboard filters by.")
        return spec

    # ------------------------------------------------------------ applying

    @property
    def active(self) -> bool:
        return bool(self.customer or self.selections or self.ranges)

    def apply(self, frame: pd.DataFrame) -> pd.DataFrame:
        """The population, narrowed. Applied to the whole book, not a page.

        A filter naming a column the frame does not carry is skipped rather
        than raising: the registry describes the domain, and a frame built
        for one purpose may legitimately carry a subset of it. Skipping is
        visible -- `describe()` still lists the chip -- so a reader is never
        shown a narrower count than the filter they set.
        """
        out = frame
        if self.customer and "customer_name" in out.columns:
            # `regex=False`, and it is not a detail. A reader typing a name
            # is typing a name: "Al-Rajhi (Holding)" is a bracket and a
            # hyphen, not a capture group and a range, and read as a pattern
            # it is either an error or a match on something else. The default
            # here is to interpret it, so the default is wrong.
            out = out[out["customer_name"].astype(str).str.contains(
                self.customer, case=False, na=False, regex=False)]

        for key, chosen in self.selections.items():
            column = BY_KEY[key].field
            if column in out.columns:
                out = out[out[column].astype(str).isin(chosen)]

        for key, span in self.ranges.items():
            column = BY_KEY[key].field
            if column not in out.columns:
                continue
            values = pd.to_numeric(out[column], errors="coerce")
            if span.minimum is not None:
                out = out[values >= span.minimum]
                values = values.loc[out.index]
            if span.maximum is not None:
                out = out[values <= span.maximum]
        return out

    def sort(self, frame: pd.DataFrame) -> pd.DataFrame:
        if self.sort_by not in frame.columns:
            return frame
        return frame.sort_values(self.sort_by, ascending=not self.descending,
                                 kind="mergesort")

    def page(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.iloc[self.offset:self.offset + self.limit]

    # ----------------------------------------------------------- reporting

    def describe(self) -> list[dict[str, Any]]:
        """One chip per active filter: what it is, and what would clear it.

        The screen renders these rather than reconstructing them from its own
        state, so a chip cannot describe a filter the server did not apply.
        """
        chips: list[dict[str, Any]] = []
        if self.customer:
            chips.append({"key": "customer", "label": "Customer",
                          "value": f"contains “{self.customer}”"})
        for key, chosen in self.selections.items():
            column = BY_KEY[key]
            chips.append({"key": key, "label": column.label,
                          "value": ", ".join(readable(c) for c in chosen)})
        for key, span in self.ranges.items():
            column = BY_KEY[key]
            unit = f" {column.unit}" if column.unit else ""
            if span.minimum is not None and span.maximum is not None:
                text = f"{span.minimum:,.10g} to {span.maximum:,.10g}{unit}"
            elif span.minimum is not None:
                text = f"at least {span.minimum:,.10g}{unit}"
            else:
                text = f"at most {span.maximum:,.10g}{unit}"
            chips.append({"key": key, "label": column.label, "value": text})
        return chips

    def to_dict(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.customer:
            filters["customer"] = self.customer
        for key, chosen in self.selections.items():
            filters[key] = list(chosen)
        for key, span in self.ranges.items():
            filters[key] = span.to_dict()
        return {"period": self.period, "filters": filters,
                "sort_by": self.sort_by, "descending": self.descending,
                "limit": self.limit, "offset": self.offset}

    def sentence(self) -> str:
        """The scope in one line, for the chat, the export and a caption.

        A scope the reader cannot read back is a scope they cannot check.
        """
        if not self.active:
            return "the whole book"
        parts = [f"{c['label'].lower()} {c['value']}" for c in self.describe()]
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]


def facets(frame: pd.DataFrame) -> dict[str, list[str]]:
    """The values each open multi-select can actually offer.

    Read from the data, not from a list somebody maintains: a segment that
    exists in the book and not in the control is a filter a reader cannot
    set, and one in the control and not the book is a filter that returns
    nothing for no visible reason.
    """
    out: dict[str, list[str]] = {}
    for column in COLUMNS:
        if column.kind != MULTI:
            continue
        if column.choices:
            out[column.key] = list(column.choices)
        elif column.field in frame.columns:
            values = sorted({str(v) for v in frame[column.field].dropna()
                             if str(v).strip()})
            out[column.key] = values
        else:
            out[column.key] = []
    return out


def contract() -> dict[str, Any]:
    """What the screen needs to build its controls. §28."""
    return {
        "columns": [c.to_dict() for c in COLUMNS],
        "sortable": list(SORTABLE),
        "bands": list(BANDS),
        "max_page": MAX_PAGE,
        "default_page": DEFAULT_PAGE,
    }


__all__ = ["BANDS", "BAND_LABELS", "BY_KEY", "COLUMNS", "DEFAULT_PAGE", "MAX_PAGE", "MULTI",
           "RANGE", "SORTABLE", "TEXT", "Column", "FilterSpec", "InvalidFilter",
           "Range", "contract", "facets", "readable"]
