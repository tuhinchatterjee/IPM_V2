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
The data. Twenty months of three hundred obligors across two and a half
thousand columns is fifteen million values, and sending it would be both
ruinous and pointless: the planner does not need the values, it needs to know
what it may ask for. Values come back through validated execution, in the
result packet, where they can be checked against what was actually run.

The field dictionary is large for the same reason the domain is: every one of
the 123 signals is exposed at this grain, several columns each. The package
therefore carries the dictionary itself, the signal inventory with the prefix
each signal's columns are built from, and the ten fields most relevant to THIS
request — so a planner composes the column it needs from a naming convention
rather than reading two thousand names looking for one.

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
from backend.early_warning import executable as ex
from backend.early_warning import signal_fields as sigf
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
#: What the book can be cut by, read from the one capability registry.
#:
#: This used to be its own list, and it advertised four levels the execution
#: layer could not run. A planner given a grouping the executor refuses is a
#: planner being set up to fail, and the failure landed as a KeyError in the
#: middle of a turn. Both this and `facts.LEVEL_FIELDS` now read
#: `executable.GROUPINGS`.
GROUPINGS: dict[str, str] = dict(ex.GROUPINGS)

#: The analytical grains a question can legitimately ask for. Anything
#: finer than the domain's own grain does not exist.
ANALYTICAL_GRAINS: tuple[str, ...] = (
    "customer_month", "customer_latest", "population_month",
    "group_month", "population_trend",
    # Two published months read against each other, obligor by obligor. Not
    # a trend: a trend is one series over time, and a transition is a
    # contingency between two points in it.
    "population_transition")


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


#: Words too common to identify a signal by. "Risk" matches ninety of the
#: hundred and twenty-three, which is the same as matching none.
_STOPWORDS = frozenset({
    "and", "or", "of", "the", "in", "on", "to", "a", "an", "for", "by",
    "with", "risk", "score", "signal", "change", "increase", "decrease",
    "decline", "deterioration", "movement", "rate", "level", "new", "other",
    "total", "high", "low", "per", "from", "against", "over", "under"})


def _named_signals(text: str, limit: int = 4) -> list[str]:
    """The inventory rows the request appears to name.

    Matched on the distinctive words in a signal's own name, so "which names
    have a covenant breach?" surfaces the covenant signal's own columns
    rather than only the node it rolls into. Two shared words are required:
    one is how "payment" matches nine unrelated signals.
    """
    words = set(re.findall(r"[a-z]{3,}", text)) - _STOPWORDS
    if not words:
        return []
    hits: list[tuple[int, str]] = []
    for entry in sigf.fields():
        name_words = set(re.findall(
            r"[a-z]{3,}", entry.name.lower())) - _STOPWORDS
        shared = len(words & name_words)
        if shared >= 2 or (shared == 1 and len(name_words) <= 2):
            hits.append((shared, entry.prefix))
    hits.sort(key=lambda h: -h[0])
    return [prefix for _, prefix in hits[:limit]]


def top_fields(request_text: str, limit: int = 10) -> list[dict[str, Any]]:
    """The fields most likely to matter to this request, best first.

    A hint for ordering, never a filter. The full dictionary travels with the
    package regardless, because a planner that cannot see the field it needs
    invents one. That matters more now than it did at seventy-three fields:
    the dictionary is two and a half thousand entries, most of them one
    signal's own columns, and a planner reading it end to end would spend its
    attention on signals this request has nothing to do with.
    """
    text = (request_text or "").lower()
    catalogue = dic.by_name()
    scored: dict[str, int] = {}
    for pattern, names in _HINTS:
        if re.search(pattern, text):
            for rank, name in enumerate(names):
                if name in catalogue:
                    scored[name] = scored.get(name, 0) + (10 - rank)

    # A signal the request names by its own words brings its own columns:
    # whether it fired, what it scored, and the reason it carries.
    for rank, prefix in enumerate(_named_signals(text)):
        for suffix, weight in (("fired", 12), ("score", 11), ("reason", 9)):
            name = f"{prefix}_{suffix}"
            if name in catalogue:
                scored[name] = scored.get(name, 0) + weight - rank
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
                    for k, v in _sampled_columns(row).items()})
    return out


def _sampled_columns(row: dict[str, Any]) -> dict[str, Any]:
    """One row, with only the signals that actually fired for it.

    Every obligor-month carries a column for all 123 signals, and for most
    obligors most of them are empty. A sample row printed in full would be
    two and a half thousand values of which two thousand are nulls, which
    teaches a planner nothing and costs the whole context window. So the
    sample shows the position, and the signals behind THIS obligor's
    position. The dictionary still describes every one of the rest.
    """
    fired = {entry.prefix for entry in sigf.scored_fields()
             if bool(row.get(entry.column("fired")))}
    out: dict[str, Any] = {}
    for name, value in row.items():
        prefix = _signal_prefix(name)
        if prefix is None or prefix in fired:
            out[name] = value
    return out


@functools.lru_cache(maxsize=1)
def _prefixes() -> tuple[str, ...]:
    return tuple(entry.prefix for entry in sigf.fields())


def _signal_prefix(column: str) -> str | None:
    """Which signal a column belongs to, or None if it is not a signal one."""
    if not column.startswith("sig"):
        return None
    for prefix in _prefixes():
        if column.startswith(prefix + "_"):
            return prefix
    return None


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
