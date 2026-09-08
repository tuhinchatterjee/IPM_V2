"""What a model is allowed to know when it designs or changes a Lens.

§3's "CreditProbe restricted Lens context builder", built once and passed to
every model call in the Lens flow, so there is exactly one place that decides
what a model may see. Two properties matter more than anything else in this
module:

**It is restricted before it is built, not filtered afterwards.** Every dataset
in it came out of :mod:`backend.metrics.lens_domains`, so a dataset outside the
Cockpit and Early Warning domains is not in the context to be picked from. A
model cannot propose what it was never shown, which is a stronger guarantee
than validating the proposal — and the proposal is validated too.

**It is small on purpose.** §45 asks for token efficiency, and a field
dictionary of fifty datasets at fifty fields each is thirty thousand tokens of
which a Lens design uses perhaps two hundred. So the context is layered: every
permitted dataset appears with its grain, its period field and its purpose;
FIELDS are carried in full only for the datasets a request actually reaches
for, and as counts and a sample elsewhere. `focus()` is how a caller says which
those are.

What a reader should be able to check
--------------------------------------
That the context contains no figure. It carries names, grains, types, coverage
and relationships — the shape of the book, never the book. A model designing a
Lens has no business seeing an exposure, and one interpreting a refresh is
given the rendered figures separately and deliberately.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from backend.metrics import lens_domains as domains

logger = logging.getLogger(__name__)

CONTEXT_VERSION = "3.0.0"

#: How many fields a dataset carries into the context when it is not in focus.
#: Enough to recognise the table; not enough to design against it, which is
#: what `focus` is for.
SAMPLE_FIELDS = 8

#: How many governed metrics the catalogue section carries. The full catalogue
#: is 99 entries in this deployment and is carried whole, because choosing
#: among existing metrics is the single most valuable thing the model does and
#: a truncated catalogue is how a Lens ends up with a new metric that already
#: existed.
MAX_CATALOGUE = 400

#: Visual types a Lens element may be. Mirrors `catalogue.VISUALS` rather than
#: re-deciding it; repeated here so the context has one list to show.
VISUALS: tuple[str, ...] = (
    "kpi", "line", "bar", "stacked_bar", "area", "table", "histogram",
    "distribution", "heatmap", "scatter", "waterfall", "cohort",
)


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------


def _field_entry(spec: Any) -> dict[str, Any]:
    return {
        "name": spec.name,
        "business_name": getattr(spec, "business_name", "") or spec.name,
        "type": getattr(spec, "type", "") or getattr(spec, "dtype", ""),
        "unit": getattr(spec, "unit", ""),
        "meaning": (getattr(spec, "description", "") or "")[:140],
    }


def _dataset_entry(spec: Any, *, full: bool) -> dict[str, Any]:
    names = sorted(spec.fields)
    entry: dict[str, Any] = {
        "dataset": spec.name,
        "business_name": spec.business_name,
        "grain": spec.grain,
        "period_field": spec.period_field,
        "primary_keys": list(spec.primary_keys),
        "purpose": (spec.purpose or "")[:200],
        "field_count": len(names),
    }
    if full:
        entry["fields"] = [_field_entry(spec.fields[n]) for n in names]
    else:
        entry["sample_fields"] = names[:SAMPLE_FIELDS]
    return entry


def _coverage(dataset: str) -> dict[str, Any]:
    """Which periods a dataset actually has, bounded.

    The whole list where it is short and the ends plus a count where it is
    long: "Q1 2022 … Q2 2026, 18 quarters" is what a period rule is designed
    against, and eighteen strings is not.
    """
    try:
        from backend.data_access import get_data_source

        periods = list(get_data_source().periods(dataset))
    except Exception:  # noqa: BLE001 - coverage is context, not correctness
        return {"periods": [], "count": 0}
    if len(periods) <= 6:
        return {"periods": periods, "count": len(periods),
                "earliest": periods[0] if periods else "",
                "latest": periods[-1] if periods else ""}
    return {"periods": periods[:2] + ["…"] + periods[-3:],
            "count": len(periods), "earliest": periods[0],
            "latest": periods[-1]}


def _relationships(permitted: set[str]) -> list[dict[str, Any]]:
    """The governed Cockpit ↔ EWS relationship graph, restricted.

    Only edges whose BOTH ends are inside the boundary. An edge with one end
    outside is not a shortcut across the boundary; it is not an edge, and it is
    dropped here rather than refused later, so a model designing a cross-domain
    metric never sees a join it would not be allowed to walk.
    """
    try:
        from backend.services import relationships as rel

        rows = rel.active_relationships()
    except Exception:  # noqa: BLE001 - no database, no graph, still a context
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        left = str(row.get("from_dataset") or "")
        right = str(row.get("to_dataset") or "")
        if left not in permitted or right not in permitted:
            continue
        out.append({
            "from_dataset": left, "from_field": str(row.get("from_field") or ""),
            "to_dataset": right, "to_field": str(row.get("to_field") or ""),
            "cardinality": str(row.get("cardinality") or ""),
            "temporal_rule": str(row.get("temporal_rule") or ""),
            "crosses_domains": (
                set(domains.domains_of(left)) != set(domains.domains_of(right))),
        })
    return out


def _catalogue(pool: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for metric in pool:
        if not domains.metric_permitted(metric):
            continue
        out.append({
            "id": metric.metric_id,
            "name": metric.name,
            "unit": metric.unit,
            "domains": list(domains.metric_domains(metric)),
            "datasets": list(getattr(metric, "datasets", ()) or ()),
            "definition": (getattr(metric, "definition", "") or "")[:180],
            "formula": getattr(metric, "formula_text", "") or "",
        })
        if len(out) >= MAX_CATALOGUE:
            break
    return out


# ---------------------------------------------------------------------------
# The context
# ---------------------------------------------------------------------------


@dataclass
class LensContext:
    """Everything a model may know, and nothing else."""

    domains: dict[str, dict[str, Any]] = field(default_factory=dict)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    catalogue: list[dict[str, Any]] = field(default_factory=list)
    visuals: list[str] = field(default_factory=lambda: list(VISUALS))
    lens: dict[str, Any] = field(default_factory=dict)
    thread: list[dict[str, Any]] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)

    @property
    def dataset_names(self) -> list[str]:
        return sorted({d["dataset"]
                       for domain in self.domains.values()
                       for d in domain.get("datasets", [])})

    def metric_ids(self) -> list[str]:
        return [m["id"] for m in self.catalogue]

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary": "Cockpit and Early Warning only.",
            "domains": self.domains,
            "relationships": self.relationships,
            "governed_metrics": self.catalogue,
            "visual_types": self.visuals,
            "lens": self.lens,
            "recent_thread": self.thread,
            "permissions": self.permissions,
            "budget": self.budget,
            "outside_boundary": self.refused,
            "version": CONTEXT_VERSION,
        }


def build(*, focus: Iterable[str] = (), user_id: int | None = None,
          readable: Any = None, lens: dict[str, Any] | None = None,
          thread: Iterable[dict[str, Any]] = (),
          budget: Any = None, role: str = "") -> LensContext:
    """The restricted context for one Lens request.

    `focus` names the datasets whose full field dictionaries are needed —
    normally the ones a deterministic first pass has already resolved from the
    request. Everything permitted still appears; only the depth differs.
    """
    from backend.data_access.catalog import get_catalog
    from backend.metrics import service as metrics

    focus_set = {f for f in focus if f}
    try:
        catalog = get_catalog()
        names = catalog.names()
    except Exception:  # noqa: BLE001 - reported, not raised
        logger.warning("no governed catalogue available for a Lens context")
        catalog, names = None, []

    permitted: set[str] = set()
    grouped: dict[str, dict[str, Any]] = {
        domain: {"label": domains.LABELS[domain],
                 "purpose": domains.PURPOSE[domain], "datasets": []}
        for domain in domains.LENS_DOMAINS
    }
    refused: list[str] = []
    for name in names:
        serves = domains.domains_of(name)
        if not serves:
            refused.append(name)
            continue
        permitted.add(name)
        try:
            spec = catalog.dataset(name)
        except Exception:  # noqa: BLE001
            continue
        entry = _dataset_entry(spec, full=name in focus_set)
        entry["coverage"] = _coverage(name)
        entry["lens_domains"] = list(serves)
        if len(serves) > 1:
            entry["early_warning_fields"] = sorted(
                domains.EWS_FIELDS.get(name, frozenset()))
        for domain in serves:
            grouped[domain]["datasets"].append(entry)

    pool = metrics.catalogue(user_id=user_id, readable=readable)
    return LensContext(
        domains=grouped,
        relationships=_relationships(permitted),
        catalogue=_catalogue(pool),
        lens=dict(lens or {}),
        thread=[dict(t) for t in list(thread)[-6:]],
        permissions={"role": role or "", "user_id": user_id,
                     "datasets_readable": sorted(permitted)},
        budget=(budget.to_dict() if hasattr(budget, "to_dict") else {}),
        refused=sorted(refused),
    )


def fields_of(dataset: str) -> dict[str, dict[str, Any]]:
    """The field dictionary of one permitted dataset, or nothing.

    Refuses rather than returns for a dataset outside the boundary, so a
    caller that forgot to check cannot accidentally read one.
    """
    domains.require([dataset])
    from backend.data_access.catalog import get_catalog

    spec = get_catalog().dataset(dataset)
    return {name: _field_entry(spec.fields[name]) for name in sorted(spec.fields)}


__all__ = ["CONTEXT_VERSION", "MAX_CATALOGUE", "SAMPLE_FIELDS", "VISUALS",
           "LensContext", "build", "fields_of"]
