"""
Everything a planner needs to know about this domain before writing code.

The package, and why it is shaped this way
------------------------------------------
A planner asked to write analysis against a domain it cannot see will invent
plausible field names. That is not a failure of instruction-following; it is
what happens when the only thing supplied is a question. So the planner is
given the domain instead: the grain, the periods that actually exist, every
field with its definition and its measured coverage, the groupings available,
and a small sample of real rows so the shapes are concrete.

What it deliberately does NOT contain
-------------------------------------
The data. Twenty months of three hundred obligors across seventy-three
columns is four hundred and thirty-eight thousand values, and sending it
would be both ruinous and pointless: the planner does not need the values, it
needs to know what it may ask for. Values come back through validated
execution, in the result packet, where they can be checked against what was
actually run.

The sample is the exception, and it is bounded and permission-scoped for the
same reason: a planner that has seen three rows writes better code than one
that has seen a schema, and one that has seen three hundred writes exactly
the same code as one that has seen three.

Relevance ranking
-----------------
`top_fields` ranks the dictionary against the business request so the most
likely fields are named first. It is a hint, not a filter: the FULL
dictionary always travels with the package, because a planner that cannot
see a field it needs will invent one, which is the failure this exists to
prevent.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import dictionary as dic
from backend.early_warning import v2_service as svc
from backend.early_warning import wide

#: The canonical business name of this domain. One name, used everywhere.
DOMAIN = "Early Warning"

#: The canonical identifier. What the domain lock, the validator and the
#: context packet all compare against.
DOMAIN_ID = "early_warning"

#: The analytical grain. One row is one obligor at one month-end.
GRAIN = ("customer_id", "snapshot_month")

#: How many sample rows travel with the package.
SAMPLE_ROWS = 3

#: Every field a caller may group by, with the label a reader would use.
GROUPINGS: dict[str, str] = {
    "segment": "Segment",
    "sector": "Sector",
    "region": "Region",
    "relationship_manager": "Relationship manager",
    "internal_rating": "Internal grade",
    "ifrs9_stage": "IFRS 9 stage",
    "ews_band": "Early Warning band",
    "ta_band": "T&A band",
    "classifier_band": "Classifier band",
    "dominant_layer": "Dominant layer",
    "dominant_subcategory": "Dominant sub-category",
}

#: The analytical grains a question can legitimately ask for. Anything
#: finer than the domain's own grain does not exist.
ANALYTICAL_GRAINS: tuple[str, ...] = (
    "customer_month", "customer_latest", "population_month",
    "group_month", "population_trend")


@dataclass
class GrainPackage:
    """The domain, described. What the planner is given instead of the data."""

    domain: str = DOMAIN
    domain_id: str = DOMAIN_ID
    grain: tuple[str, ...] = GRAIN
    periods: list[str] = field(default_factory=list)
    current_period: str = ""
    earliest_period: str = ""
    customer_count: int = 0
    field_count: int = 0
    field_dictionary: dict[str, Any] = field(default_factory=dict)
    groupings: dict[str, str] = field(default_factory=dict)
    analytical_grains: tuple[str, ...] = ANALYTICAL_GRAINS
    coverage: dict[str, Any] = field(default_factory=dict)
    top_fields: list[dict[str, Any]] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    methodology: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain, "domain_id": self.domain_id,
            "grain": list(self.grain),
            "periods": list(self.periods),
            "period_count": len(self.periods),
            "current_period": self.current_period,
            "earliest_period": self.earliest_period,
            "customer_count": self.customer_count,
            "field_count": self.field_count,
            "field_dictionary": self.field_dictionary,
            "groupings": dict(self.groupings),
            "analytical_grains": list(self.analytical_grains),
            "coverage": dict(self.coverage),
            "top_fields": list(self.top_fields),
            "sample_rows": list(self.sample_rows),
            "methodology": dict(self.methodology),
            "capabilities": list(self.capabilities),
            "permissions": dict(self.permissions),
        }


@functools.lru_cache(maxsize=1)
def methodology() -> dict[str, Any]:
    """The model's own shape, read from the modules that implement it.

    Read rather than declared, so a change to the engine changes what the
    planner is told about it. A methodology page maintained by hand drifts
    from the engine and is worse than none.
    """
    from backend.early_warning import accelerator as ac
    from backend.early_warning import aggregation as agg
    from backend.early_warning import catalog
    from backend.early_warning import classifiers_v2 as clf
    from backend.early_warning import matrix, notches, triggers_v2

    counts = catalog.status_counts()
    return {
        "signals_total": len(catalog.SIGNAL_INVENTORY),
        "signals_scored": counts.get("SCORED", 0),
        "signals_removed": sum(v for k, v in counts.items() if k != "SCORED"),
        "classifiers": len(clf.CLASSIFIER_DEFINITIONS),
        "triggers": len(triggers_v2.TRIGGER_DEFINITIONS),
        "accelerator_dimensions": list(ac.DIMENSION_WEIGHTS),
        "decay_classes": [d.name for d in ac.DECAY_CLASSES],
        "decay_is_separate_from_accelerator": True,
        "sub_categories": len(agg.TA_SUBCATEGORIES) + len(clf.SUBCATEGORIES),
        "layer_dimension_outputs": len(wide.LAYER_KEYS),
        "matrix": f"{len(matrix.ANCHOR_MATRIX)}x"
                  f"{len(next(iter(matrix.ANCHOR_MATRIX.values())))}",
        "notches": list(notches.NOTCH_KEYS),
        "points_per_notch": notches.POINTS_PER_NOTCH,
        "net_notch_cap": notches.NET_NOTCH_CAP,
        "not_calibrated": (
            "Every weight, band and multiplier is a documented starting "
            "calibration rather than an estimate fitted to default data. The "
            "model orders obligors; it does not predict them, and no output "
            "is a probability."),
    }


#: What a word in the question suggests about which fields matter. Deliberately
#: coarse: this ranks a list the planner can see all of, rather than deciding
#: what it may see.
_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"exposure|amount|size|sar|balance", ("exposure", "limit", "utilisation_pct")),
    (r"arrear|past due|dpd|overdue|delinquen", ("dpd",)),
    (r"grade|rating", ("internal_rating", "pd_12m")),
    (r"stage|ifrs", ("ifrs9_stage",)),
    (r"segment", ("segment",)),
    (r"sector|industry|contracting|construction", ("sector",)),
    (r"region|geograph|branch", ("region",)),
    (r"relationship manager|\brm\b|portfolio owner", ("relationship_manager",)),
    (r"utilisation|drawdown|headroom", ("utilisation_pct", "limit")),
    (r"\bl1\b|behaviour|behavioural|transaction", ("l1_ta",)),
    (r"\bl2\b|credit event|covenant|collateral|security",
     ("l2_ta", "l2_c", "sub_l2_5_score", "sub_l2_t2_score")),
    (r"\bl3\b|external|news|intelligence", ("l3_ta",)),
    (r"\bl4\b|network|supply|counterpart|connected", ("l4_ta", "l4_c")),
    (r"classifier|structural|vulnerab", ("classifier_score", "classifier_band")),
    (r"trigger|live|t&a|happening now|fresh", ("ta_score", "ta_band")),
    (r"notch", tuple(wide.notch_column(k) for k in wide.NOTCH_KEYS)
     + ("net_notches", "notch_points")),
    (r"anchor|matrix", ("anchor_score",)),
    (r"override|cap|floor", ("override_applied", "override_types")),
    (r"mov|chang|deteriorat|improv|trend|worse|rose|fell",
     ("ews_change_1m", "ews_change_12m", "anchor_change_1m",
      "anchor_change_12m")),
    (r"driver|driving|cause|why", ("dominant_subcategory", "dominant_driver",
                                    "dominant_layer")),
    (r"high risk|watchlist|severe|worst|weakest",
     ("ews_band", "high_plus", "ews_score")),
    (r"concentrat", ("exposure", "high_plus", "sector", "segment")),
)


def top_fields(request_text: str, limit: int = 10) -> list[dict[str, Any]]:
    """The fields most likely to matter to this request, best first.

    A hint for ordering, never a filter. The full dictionary travels with the
    package regardless, because a planner that cannot see the field it needs
    invents one.
    """
    text = (request_text or "").lower()
    catalogue = dic.by_name()
    scored: dict[str, int] = {}
    for pattern, names in _HINTS:
        if re.search(pattern, text):
            for rank, name in enumerate(names):
                if name in catalogue:
                    scored[name] = scored.get(name, 0) + (10 - rank)
    # The score and the band are what almost every Early Warning question is
    # ultimately about, so they are always in the running.
    for name in ("ews_score", "ews_band", "customer_name", "exposure"):
        scored.setdefault(name, 1)
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"name": n, "relevance": s, **catalogue[n].to_dict()}
            for n, s in ranked if n in catalogue]


def sample(period: str | None = None, rows: int = SAMPLE_ROWS,
            allowed_customers: set[str] | None = None) -> list[dict[str, Any]]:
    """A few real rows, so the shapes are concrete rather than described.

    Permission-scoped: a caller who may not read an obligor does not see it
    here either. Bounded because a planner that has seen three rows writes
    the same code as one that has seen three hundred.
    """
    frame = wide.with_movement(period)
    if frame.empty:
        return []
    if allowed_customers is not None:
        frame = frame[frame["customer_id"].isin(allowed_customers)]
    if frame.empty:
        return []
    # Spread across the severity range rather than the top of it: a sample of
    # three VERY_HIGH obligors misrepresents a book that is 82% VERY_LOW.
    ordered = frame.sort_values("ews_score", ascending=False)
    picks = [0, len(ordered) // 2, len(ordered) - 1][:rows]
    out: list[dict[str, Any]] = []
    for i in picks:
        row = ordered.iloc[i].to_dict()
        out.append({k: (None if _is_nan(v) else _plain(v))
                    for k, v in row.items()})
    return out


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and value != value


def _plain(value: Any) -> Any:
    """JSON-safe, and numpy-free."""
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return str(value)
    return value


def build(request_text: str = "", *, period: str | None = None,
           permissions: dict[str, Any] | None = None,
           allowed_customers: set[str] | None = None,
           capabilities: list[str] | None = None) -> GrainPackage:
    """The whole package, for one request."""
    periods = svc.periods()
    current = period or (periods[-1] if periods else "")
    frame = wide.customer_month(current)
    return GrainPackage(
        periods=list(periods),
        current_period=current,
        earliest_period=periods[0] if periods else "",
        customer_count=int(frame["customer_id"].nunique()) if not frame.empty else 0,
        field_count=len(dic.fields()),
        field_dictionary=dic.to_dict(current),
        groupings=dict(GROUPINGS),
        coverage=dic.coverage_summary(current),
        top_fields=top_fields(request_text),
        sample_rows=sample(current, allowed_customers=allowed_customers),
        methodology=methodology(),
        capabilities=list(capabilities or []),
        permissions=dict(permissions or {}),
    )


__all__ = ["ANALYTICAL_GRAINS", "DOMAIN", "DOMAIN_ID", "GRAIN", "GROUPINGS",
           "SAMPLE_ROWS", "GrainPackage", "build", "methodology", "sample",
           "top_fields"]
