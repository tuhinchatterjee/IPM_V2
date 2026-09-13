"""
What "Export to Playbook" produces. Playbook §5.

The shared payload every in-scope module writes and Playbook reads. One
versioned shape, so a future module can be wired in by producing this rather
than by teaching Playbook a fifth dialect.

The rule inherited from `backend/exports/contract.py`
-----------------------------------------------------
**An export never recomputes.** It reads what was persisted when the analysis
ran and writes it down. An export that re-ran its analysis would be a second
answer wearing the first one's filename, and the moment the book moved on, the
snapshot and the screen would disagree with nobody able to say which was right.

Why the snapshot is self-contained
----------------------------------
It has to still be useful when the user has left the source screen, when the
source thread is archived, and when the quarterly rebuild has changed the
numbers underneath. So it carries the narrative, the tables with their units and
precision, the chart specification, the scope, the assumptions, the limitations
and the provenance — not a link that will one day resolve to something else.

Idempotency lives in the content hash. The same analysis exported twice produces
the same hash and therefore the same revision; an analysis that has changed
produces a new one, and a report already citing the old revision keeps citing
exactly what it was built on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Bumped when the payload shape changes, so a snapshot found in a database in
#: two years can be matched against the code that wrote it.
#: 1.1 adds `Table.metrics` — stable metric identity. Additive: a 1.0
#: payload is still valid and simply carries no metrics.
SCHEMA_VERSION = "1.1"
GENERATOR = "creditprobe-playbook-export/1.0"

COCKPIT = "cockpit"
EARLY_WARNING = "early_warning"
WHAT_IF = "what_if"
SCORECARD_VALIDATION = "scorecard_validation"
LENSES = "lenses"

#: The five modules §5 places in scope. Project Planner is deliberately absent,
#: and on this baseline no such module exists to exclude.
SOURCE_MODULES: tuple[str, ...] = (
    COCKPIT, EARLY_WARNING, WHAT_IF, SCORECARD_VALIDATION, LENSES,
)

#: Modules with a producing surface on this baseline. `what_if` is not one of
#: them — see docs/playbook/INTEGRATION_NOTES.md. Kept separate from
#: SOURCE_MODULES so the contract can describe a module it cannot yet serve,
#: which is the honest shape of a deferred integration.
IMPLEMENTED_MODULES: tuple[str, ...] = (
    COCKPIT, EARLY_WARNING, SCORECARD_VALIDATION, LENSES,
)

#: Export scope. The default is one analysis; anything wider is chosen, never
#: assumed.
SCOPE_ANALYSIS = "analysis"
SCOPE_SELECTED = "selected_results"
SCOPE_INVESTIGATION = "investigation"
SCOPES = (SCOPE_ANALYSIS, SCOPE_SELECTED, SCOPE_INVESTIGATION)


class InvalidExport(ValueError):
    """The analysis cannot be exported, and the message says why."""


@dataclass
class Metric:
    """One governed figure, with the identity a document can bind to.

    The reason this exists
    ----------------------
    A living document has to say "the default rate this paper relied on is the
    same series as the default rate you are looking at now". Names cannot carry
    that: two modules can both produce a "Default rate", for different
    populations, periods and denominators, and binding them because the words
    match is precisely the mistake that makes a governed pack wrong. So a
    module that knows what it computed states an id, and everything downstream
    links through the id or admits it did not link.

    The dimensions below are part of identity, not decoration. A rate for the
    retail book is not the same metric as a rate for the corporate book, and a
    Q1 reading is not a Q2 reading — two figures agree on `metric_id` and
    differ on `population`, and they are different series.

    `value` is exact and `display_value` is how it is shown, the same
    separation `backend/playbook/calc.py` keeps between a value and its
    presentation. Both travel, because a report quotes one and reconciles
    against the other.
    """

    metric_id: str
    label: str = ""
    value: str = ""
    display_value: str = ""
    unit: str = ""
    currency: str = ""
    population: str = ""
    segment: str = ""
    reporting_period: str = ""
    scenario: str = ""
    as_of: str = ""
    #: Where in the producing analysis this came from — a cell, a table
    #: coordinate, a calculation id. What makes the figure reviewable.
    locator: str = ""
    catalogue_id: str = ""

    def as_dict(self) -> dict:
        return {"metric_id": self.metric_id, "label": self.label,
                "value": self.value, "display_value": self.display_value,
                "unit": self.unit, "currency": self.currency,
                "population": self.population, "segment": self.segment,
                "reporting_period": self.reporting_period,
                "scenario": self.scenario, "as_of": self.as_of,
                "locator": self.locator, "catalogue_id": self.catalogue_id}

    @classmethod
    def from_dict(cls, d: dict) -> Metric:
        return cls(**{k: d.get(k, "") for k in (
            "metric_id", "label", "value", "display_value", "unit", "currency",
            "population", "segment", "reporting_period", "scenario", "as_of",
            "locator", "catalogue_id")})


@dataclass
class Table:
    """One result table, with what a reader needs to interpret it."""

    id: str
    title: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    #: Per-column unit and precision. Without these a column of "2.09" is
    #: ambiguous between a percentage, a ratio and SAR billion.
    units: dict[str, str] = field(default_factory=dict)
    precision: dict[str, int] = field(default_factory=dict)
    #: The governed figures this table states. Additive and optional: an
    #: exporter that does not know its metric ids omits them and its figures
    #: are simply not auto-bindable, which is the honest outcome. It is never
    #: filled in by guessing from a column heading.
    metrics: list[Metric] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "columns": list(self.columns),
                "rows": [list(r) for r in self.rows], "units": dict(self.units),
                "precision": dict(self.precision),
                "metrics": [m.as_dict() for m in self.metrics]}


@dataclass
class Chart:
    """A chart as data plus specification, never as a bare picture.

    An image alone cannot be re-rendered into a report at a different size, and
    cannot be checked against the table it came from.
    """

    id: str
    kind: str = "bar"
    title: str = ""
    categories: list[str] = field(default_factory=list)
    series: dict[str, list[Any]] = field(default_factory=dict)
    #: Where an immutable rendered asset exists, its reference. Optional.
    asset_ref: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title,
                "categories": list(self.categories),
                "series": {k: list(v) for k, v in self.series.items()},
                "asset_ref": self.asset_ref}


@dataclass
class Snapshot:
    """One exported analysis, complete."""

    source_module: str
    title: str
    #: The question as the user asked it. A title is a label; this is the ask.
    question: str = ""
    narrative: str = ""
    tables: list[Table] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)

    #: Reporting period, dataset dates, currency, filters, segments, population,
    #: scenario and model versions. Everything needed to know what the figures
    #: describe.
    scope: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    data_quality: list[str] = field(default_factory=list)

    #: Thread / run / result ids and a stable in-product link.
    source_ref: dict[str, Any] = field(default_factory=dict)
    source_revision: str = ""
    #: Trace ids, dataset versions, engine function versions.
    provenance: dict[str, Any] = field(default_factory=dict)

    scope_kind: str = SCOPE_ANALYSIS
    report_family: str = ""
    tags: list[str] = field(default_factory=list)
    reporting_period: str = ""
    insight: str = ""
    #: True only for clearly labelled demonstration fixtures.
    demo_origin: bool = False
    created_at: str = ""

    def validate(self) -> None:
        """Refuse what is not a completed analysis. §5.

        A greeting is not an analysis and neither is a failed or half-streamed
        answer. Exporting one would put a card in the library that opens on
        nothing, which is worse than the export having failed.
        """
        if self.source_module not in SOURCE_MODULES:
            raise InvalidExport(
                f"{self.source_module!r} is not a module Playbook accepts "
                f"exports from. Expected one of: {', '.join(SOURCE_MODULES)}."
            )
        if self.scope_kind not in SCOPES:
            raise InvalidExport(f"{self.scope_kind!r} is not an export scope.")
        if not (self.title or "").strip():
            raise InvalidExport("An export needs a title.")
        substantive = (
            len((self.narrative or "").strip()) >= 80
            or any(t.rows for t in self.tables)
            or any(c.series for c in self.charts)
        )
        if not substantive:
            raise InvalidExport(
                "This is not a completed analysis: it carries no narrative of "
                "any length, no table with rows, and no chart data. A greeting "
                "or an answer that did not finish cannot be exported."
            )

    def payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "generator": GENERATOR,
            "source_module": self.source_module,
            "source_ref": dict(self.source_ref),
            "source_revision": self.source_revision,
            "scope_kind": self.scope_kind,
            "title": self.title,
            "question": self.question,
            "narrative": self.narrative,
            "tables": [t.as_dict() for t in self.tables],
            "charts": [c.as_dict() for c in self.charts],
            "scope": dict(self.scope),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "caveats": list(self.caveats),
            "data_quality": list(self.data_quality),
            "provenance": dict(self.provenance),
            "report_family": self.report_family,
            "tags": list(self.tags),
            "reporting_period": self.reporting_period,
            "insight": self.insight,
            "demo_origin": self.demo_origin,
            "created_at": self.created_at or datetime.now(UTC).isoformat(),
        }

    def content_hash(self) -> str:
        """A hash of the analysis's MEANING.

        Everything that would change what a report built on this snapshot says
        is included; the export timestamp is not, because exporting the same
        unchanged analysis twice is the same evidence and must deduplicate.
        """
        payload = self.payload()
        payload.pop("created_at", None)
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False,
                       default=str).encode("utf-8")
        ).hexdigest()
