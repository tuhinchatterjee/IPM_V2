"""What CreditProbe means by each number, in one place.

Before this, a dashboard's formulas lived in the component that drew them. A
number on a screen and the same number in an answer were two implementations
of one definition, and the only way to know whether they agreed was to read
both.

A metric definition here carries everything §6 asks a tile to be able to
explain about itself: the business definition, the formula, the unit, the
numerator and the denominator, the domain, the dataset, the source fields, the
filters, the period rule, the transformation, the exclusions, the owner, the
version, the status — and what it is NOT, which for several metrics is the
most useful field on the panel.

Three rules:

**Nothing is defined that the data cannot support.** A metric whose fields do
not exist in any governed dataset does not get an entry with a shrug in it; it
gets an `Unsupported` entry naming what is missing, so a lens can say "retail
IFRS 9 staging is not available in this deployment, because there is no retail
impairment dataset" rather than drawing an empty tile. `check_catalogue()`
proves the rest against the live catalogue, and a test runs it.

**Governed and user-built are the same shape and different things.** Both are
`MetricDefinition`. What differs is `origin` and `status`: a metric somebody
built this morning is USER/DRAFT until it has been verified, and every surface
that shows it says which.

**Aliases are part of the definition.** "NPL rate", "default rate" and "bad
rate" are three names people use; a catalogue that only answers to the first
is a catalogue people stop searching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.metrics.formula import Condition, Formula, Side, Term

CATALOGUE_VERSION = "1.0.0"

# --------------------------------------------------------------- governance

ORIGIN_GOVERNED = "CREDITPROBE_GOVERNED"
ORIGIN_USER = "USER"
ORIGINS = (ORIGIN_GOVERNED, ORIGIN_USER)

STATUS_DRAFT = "DRAFT"
STATUS_CALCULATION_READY = "CALCULATION_READY"
STATUS_VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
STATUS_VERIFIED = "VERIFIED"
STATUS_PUBLISHED = "PUBLISHED"
STATUS_DEPRECATED = "DEPRECATED"
STATUSES = (STATUS_DRAFT, STATUS_CALCULATION_READY,
            STATUS_VERIFICATION_REQUIRED, STATUS_VERIFIED, STATUS_PUBLISHED,
            STATUS_DEPRECATED)

#: What a reader is told about how far a metric has been taken. Three words,
#: because a governance label nobody reads is a governance label that does not
#: work.
LABELS = {
    ORIGIN_GOVERNED: "CreditProbe governed",
    ORIGIN_USER: "User built",
}
STATUS_LABELS = {
    STATUS_DRAFT: "Draft",
    STATUS_CALCULATION_READY: "Calculates",
    STATUS_VERIFICATION_REQUIRED: "Needs verification",
    STATUS_VERIFIED: "User verified",
    STATUS_PUBLISHED: "Published",
    STATUS_DEPRECATED: "Deprecated",
}

#: How a period is chosen when a lens does not say. Named so the info panel
#: can state it rather than leaving a reader to assume.
PERIOD_LATEST = "latest_available"
PERIOD_SELECTED = "as_selected"
PERIOD_ROLLING = "rolling_window"
#: The most recent period whose performance window has closed. Distinct from
#: `latest_available`, and the distinction matters: a scorecard's Gini for last
#: month is not "zero" or "unknown", it does not exist yet, because none of
#: those accounts has had time to default. A validation metric that quietly
#: used the latest month would report on a cohort with no outcomes in it.
PERIOD_LATEST_MATURED = "latest_matured"

#: Visualisations a metric may honestly be drawn as. A single ratio has no
#: business being a bar chart of one bar, and this is where that is said.
VISUALS = ("kpi", "line", "bar", "stacked_bar", "area", "table", "histogram",
           "distribution", "heatmap", "scatter", "waterfall", "cohort")


@dataclass(frozen=True)
class Unsupported:
    """A metric CreditProbe knows about and cannot calculate here.

    Its own type rather than a definition with an empty formula, so that a
    lens has to decide what to say about it rather than drawing a tile with a
    dash in it. `because` is written for the person reading the dashboard, not
    for the engineer.
    """

    metric_id: str
    name: str
    domain: str
    because: str
    needs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"metric_id": self.metric_id, "name": self.name,
                "domain": self.domain, "available": False,
                "because": self.because, "needs": list(self.needs)}


@dataclass(frozen=True)
class MetricDefinition:
    """One number, and everything a reader may ask about it."""

    metric_id: str
    name: str
    definition: str
    formula: Formula
    unit: str = "number"
    domain: str = ""
    portfolio: str = ""
    aliases: tuple[str, ...] = ()
    #: Plain English, for the info panel. Distinct from `definition`, which is
    #: what it measures: this is how the arithmetic reads.
    formula_text: str = ""
    numerator_text: str = ""
    denominator_text: str = ""
    period_rule: str = PERIOD_SELECTED
    transformation: str = ""
    exclusions: str = ""
    #: What this metric is NOT, where a reasonable person would assume
    #: otherwise. Often the most-read line on the panel.
    not_this: str = ""
    visuals: tuple[str, ...] = ("kpi",)
    decimals: int = 2
    higher_is_better: bool | None = None
    owner: str = "Credit Risk Analytics"
    origin: str = ORIGIN_GOVERNED
    status: str = STATUS_PUBLISHED
    version: str = "1.0.0"
    #: The metric's own scope, applied to every term alike.
    scope: tuple[Condition, ...] = ()
    #: Filled for user metrics; empty for governed ones.
    created_by: int | None = None
    verified_by: int | None = None
    verified_at: str = ""
    last_verified_note: str = ""
    id: int | None = None

    # -- reading it ---------------------------------------------------------

    @property
    def datasets(self) -> tuple[str, ...]:
        return self.formula.datasets

    @property
    def fields(self) -> tuple[str, ...]:
        out: list[str] = []
        for term in self.formula.terms:
            for name in (term.field, term.weight_field):
                if name and name not in out:
                    out.append(name)
            for condition in term.where:
                if condition.field and condition.field not in out:
                    out.append(condition.field)
        for condition in self.scope:
            if condition.field and condition.field not in out:
                out.append(condition.field)
        return tuple(out)

    @property
    def filters(self) -> tuple[str, ...]:
        return tuple(c.describe() for c in self.scope)

    @property
    def governed(self) -> bool:
        return self.origin == ORIGIN_GOVERNED

    @property
    def trustworthy(self) -> bool:
        """Whether a lens may show it without a caveat beside it."""
        return self.governed or self.status in (STATUS_VERIFIED,
                                                STATUS_PUBLISHED)

    def panel(self, *, catalog: Any = None) -> dict[str, Any]:
        """Everything §6 requires an info control to show.

        Assembled here rather than in the component so that the panel on a
        dashboard, the panel in a chart and the answer to "how is this
        calculated?" are one thing.
        """
        source_fields = []
        for name in self.fields:
            entry: dict[str, Any] = {"name": name}
            if catalog is not None and self.datasets:
                try:
                    definition = catalog.dataset(
                        self.datasets[0]).fields.get(name)
                except Exception:  # noqa: BLE001 - unknown dataset, no detail
                    definition = None
                if definition is not None:
                    entry.update({
                        "business_name": definition.business_name,
                        "definition": definition.definition,
                        "data_type": definition.data_type,
                        "unit": definition.unit})
            source_fields.append(entry)

        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "definition": self.definition,
            "formula": self.formula_text or self.formula.describe(),
            "formula_tree": self.formula.to_dict(),
            "unit": self.unit,
            "decimals": self.decimals,
            "numerator": self.numerator_text or (
                self.formula.numerator.describe()),
            "denominator": self.denominator_text or (
                self.formula.denominator.describe()
                if self.formula.denominator else ""),
            "domain": self.domain,
            "portfolio": self.portfolio,
            "datasets": list(self.datasets),
            "source_fields": source_fields,
            "filters": list(self.filters),
            "period_rule": self.period_rule,
            "transformation": self.transformation,
            "exclusions": self.exclusions,
            "not_this": self.not_this,
            "visuals": list(self.visuals),
            "higher_is_better": self.higher_is_better,
            "owner": self.owner,
            "origin": self.origin,
            "origin_label": LABELS.get(self.origin, self.origin),
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "governed": self.governed,
            "trustworthy": self.trustworthy,
            "version": self.version,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at,
            "last_verified_note": self.last_verified_note,
            "aliases": list(self.aliases),
        }

    def to_dict(self, *, catalog: Any = None) -> dict[str, Any]:
        return self.panel(catalog=catalog)


# ---------------------------------------------------------------------------
# Shorthand for writing the library below without ceremony
# ---------------------------------------------------------------------------


def _t(term_id: str, label: str, dataset: str, aggregate: str = "sum",
       column: str = "", **where: Any) -> Term:
    """One term. Keyword filters read as `stage=2` or `dpd__gte=30`."""
    conditions: list[Condition] = []
    for key, value in where.items():
        if "__" in key:
            name, op = key.rsplit("__", 1)
            conditions.append(Condition(name, _OPS.get(op, op), value))
        else:
            conditions.append(Condition(key, "=", value))
    return Term(id=term_id, label=label, dataset=dataset,
                aggregate=aggregate, field=column,
                where=tuple(conditions))


_OPS = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<", "ne": "!=",
        "in": "in", "notin": "not_in", "isnull": "is_null",
        "notnull": "is_not_null", "between": "between"}


def _ratio(top: list[Term], bottom: list[Term], *, scale: float = 100.0,
           kind: str = "percentage") -> Formula:
    return Formula(kind=kind, numerator=Side(terms=tuple(top)),
                   denominator=Side(terms=tuple(bottom)), scale=scale)


def _total(term: Term, *, kind: str = "sum") -> Formula:
    return Formula(kind=kind, numerator=Side(terms=(term,)))


__all__ = [
    "CATALOGUE_VERSION",
    "ORIGIN_GOVERNED", "ORIGIN_USER", "ORIGINS",
    "STATUS_DRAFT", "STATUS_CALCULATION_READY", "STATUS_VERIFICATION_REQUIRED",
    "STATUS_VERIFIED", "STATUS_PUBLISHED", "STATUS_DEPRECATED", "STATUSES",
    "LABELS", "STATUS_LABELS",
    "PERIOD_LATEST", "PERIOD_SELECTED", "PERIOD_ROLLING",
    "PERIOD_LATEST_MATURED", "VISUALS",
    "Unsupported", "MetricDefinition",
]
