"""
The join graph, and how a path across it is chosen.

The problem
-----------
"Show Real Estate customers whose ECL increased more than 20%, rating
deteriorated at least two notches, and EAD did not decline over the latest year"
needs three governed datasets. Nothing in the question names a dataset, a join
key or a cardinality — and nothing should, because a credit officer thinks in
concepts, not in tables.

So something has to turn "these concepts" into "these datasets, joined this way,
at this grain, aligned across these periods". That is this module.

The rules it follows, and why each one
--------------------------------------
Datasets are nodes; ACTIVE relationships are edges. Finding a path is a
breadth-first search, which is boring on purpose — the interesting part is what
the search REFUSES and how it ranks what survives.

  fewer hops win               every hop is a chance to lose rows, and a
                               three-hop path through an intermediate almost
                               always loses more of the book than a direct one.

  the safe direction wins      many-to-one and one-to-one cannot multiply the
                               left-hand book. One-to-many and many-to-many
                               can, and are allowed only where the resolver
                               also inserts an aggregation before the join.

  measured beats declared      a relationship with a real match rate outranks
                               one nobody has validated, even at the same hop
                               count. An assertion is not evidence.

  authority breaks ties        where two datasets can supply the same concept,
                               the one the catalogue declares authoritative for
                               that governed purpose wins.

  archived is not a candidate  a retired domain is out of the graph entirely,
                               not ranked last.

Nothing here reads data or emits SQL. It takes the governed relationship rows as
plain dictionaries and returns a plan of joins, which means the whole thing is
testable without a database — and a resolver nobody can test is a resolver
nobody should trust.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors backend.services.relationships, repeated rather than imported: this
# module sits in the runtime and may not depend on the service layer, which
# imports the database. The names are asserted equal by the test suite.
ONE_TO_ONE = "one_to_one"
MANY_TO_ONE = "many_to_one"
ONE_TO_MANY = "one_to_many"
MANY_TO_MANY = "many_to_many"

#: Cardinalities where the RIGHT side is unique on the key, so the join cannot
#: multiply the left-hand book.
SAFE_CARDINALITIES = frozenset({ONE_TO_ONE, MANY_TO_ONE})

SAME_PERIOD = "same_period"
LATEST_ON_OR_BEFORE = "latest_on_or_before"
NO_PERIOD = "none"

#: A path longer than this is not an analysis, it is a fishing expedition. Each
#: hop compounds the row loss, and by four hops the population left has usually
#: stopped being the population the question was about.
MAX_PATH_HOPS = 3

#: Two paths whose scores differ by less than this are materially the same
#: choice; anything wider and the resolver has a real preference. Below it, the
#: caller is told there was a choice rather than having one made silently.
AMBIGUITY_MARGIN = 0.15

#: Confidence below which the resolver will not choose without saying so.
LOW_CONFIDENCE = 0.85


@dataclass(frozen=True)
class Edge:
    """One usable relationship, in the direction it will be traversed.

    A stored relationship is directional — `covenant_tests.account_id` points at
    `portfolio_facility.account_id` — but a join path may need to walk it either
    way. Reversing it also reverses the cardinality, which is exactly the
    property that decides whether the walk is safe, so the reversal is explicit
    rather than implied.
    """

    relationship_id: int
    name: str
    left: str
    left_field: str
    right: str
    right_field: str
    cardinality: str
    kind: str
    join_policy: str
    temporal_rule: str
    confidence: float
    version: int
    semantic: str = ""
    match_rate: float | None = None
    duplicate_rate: float | None = None
    validated: bool = False
    reversed_: bool = False

    @property
    def multiplies_left(self) -> bool:
        """Whether joining this edge can produce more rows than it started with."""
        return self.cardinality not in SAFE_CARDINALITIES

    @property
    def is_asof(self) -> bool:
        return self.temporal_rule == LATEST_ON_OR_BEFORE

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "relationship_name": self.name,
            "relationship_version": self.version,
            "left": self.left, "left_field": self.left_field,
            "right": self.right, "right_field": self.right_field,
            "cardinality": self.cardinality, "kind": self.kind,
            "join_policy": self.join_policy,
            "temporal_rule": self.temporal_rule,
            "confidence": self.confidence,
            "semantic": self.semantic,
            "match_rate": self.match_rate,
            "duplicate_rate": self.duplicate_rate,
            "validated": self.validated,
            "reversed": self.reversed_,
            "multiplies_left": self.multiplies_left,
        }


def _reverse_cardinality(cardinality: str) -> str:
    return {ONE_TO_ONE: ONE_TO_ONE, MANY_TO_ONE: ONE_TO_MANY,
            ONE_TO_MANY: MANY_TO_ONE,
            MANY_TO_MANY: MANY_TO_MANY}.get(cardinality, MANY_TO_MANY)


def _edges_from(row: dict[str, Any]) -> list[Edge]:
    """Both traversable directions of one stored relationship."""
    forward = Edge(
        relationship_id=int(row.get("id") or 0),
        name=str(row.get("name") or ""),
        left=str(row["from_dataset"]), left_field=str(row["from_field"]),
        right=str(row["to_dataset"]), right_field=str(row["to_field"]),
        cardinality=str(row.get("cardinality") or MANY_TO_ONE),
        kind=str(row.get("kind") or "key"),
        join_policy=str(row.get("join_policy") or "inner"),
        temporal_rule=str(row.get("temporal_rule") or SAME_PERIOD),
        confidence=float(row.get("confidence") or 1.0),
        version=int(row.get("version") or 1),
        semantic=str(row.get("semantic") or row.get("description") or ""),
        match_rate=row.get("match_rate"),
        duplicate_rate=row.get("duplicate_rate"),
        validated=bool(row.get("validated_at")),
    )
    backward = Edge(
        relationship_id=forward.relationship_id, name=forward.name,
        left=forward.right, left_field=forward.right_field,
        right=forward.left, right_field=forward.left_field,
        cardinality=_reverse_cardinality(forward.cardinality),
        kind=forward.kind, join_policy=forward.join_policy,
        temporal_rule=forward.temporal_rule, confidence=forward.confidence,
        version=forward.version, semantic=forward.semantic,
        match_rate=forward.match_rate, duplicate_rate=forward.duplicate_rate,
        validated=forward.validated, reversed_=True,
    )
    return [forward, backward]


class JoinGraph:
    """Governed datasets as nodes, ACTIVE relationships as edges."""

    def __init__(self, relationships: list[dict[str, Any]]):
        self._edges: dict[str, list[Edge]] = {}
        self._all: list[Edge] = []
        for row in relationships:
            for edge in _edges_from(row):
                if edge.left == edge.right:
                    # A self-join (a parent pointing at another member of the
                    # same table) is a legitimate relationship and a terrible
                    # path step: it would let the search walk in circles. It
                    # stays available to a plan that names it, and out of
                    # traversal.
                    continue
                self._edges.setdefault(edge.left, []).append(edge)
                self._all.append(edge)

    def datasets(self) -> set[str]:
        return set(self._edges)

    def out(self, dataset: str) -> list[Edge]:
        return self._edges.get(dataset, [])

    def direct(self, left: str, right: str) -> list[Edge]:
        return [e for e in self.out(left) if e.right == right]

    def __len__(self) -> int:
        return len(self._all)


@dataclass
class JoinPath:
    """One way to get from a base dataset to a target, and what it costs."""

    target: str
    edges: list[Edge] = field(default_factory=list)
    #: Why this path was ranked where it was, in the words a reviewer checks.
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def hops(self) -> int:
        return len(self.edges)

    @property
    def datasets(self) -> list[str]:
        return [self.edges[0].left, *[e.right for e in self.edges]] if self.edges else []

    @property
    def multiplies(self) -> bool:
        return any(e.multiplies_left for e in self.edges)

    @property
    def needs_asof(self) -> bool:
        return any(e.is_asof for e in self.edges)

    def describe(self) -> str:
        if not self.edges:
            return self.target
        parts = [self.edges[0].left]
        for edge in self.edges:
            parts.append(f"—[{edge.left_field}={edge.right_field}]→ {edge.right}")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "hops": self.hops,
            "datasets": self.datasets,
            "edges": [e.to_dict() for e in self.edges],
            "multiplies": self.multiplies,
            "needs_asof": self.needs_asof,
            "score": round(self.score, 4),
            "reasons": list(self.reasons),
            "description": self.describe(),
        }


def _score(path: list[Edge]) -> tuple[float, list[str]]:
    """How good a path is, and why — worked out from what each hop costs.

    Starts at 1.0 and is charged for everything that makes a path worse. Written
    as explicit deductions rather than a weighted formula so the answer to "why
    did it choose that one" is a list of sentences rather than a number.
    """
    score = 1.0
    reasons: list[str] = []

    hop_penalty = 0.18 * max(0, len(path) - 1)
    if hop_penalty:
        score -= hop_penalty
        reasons.append(
            f"{len(path)} hops — every hop is a chance to lose rows, so a "
            "shorter path is preferred where one exists.")
    else:
        reasons.append("A direct governed relationship, with nothing in between.")

    for edge in path:
        if edge.multiplies_left:
            score -= 0.25
            reasons.append(
                f"{edge.left} → {edge.right} is {edge.cardinality}, so it can "
                "multiply rows and needs an aggregation before the join.")
        if edge.validated and edge.match_rate is not None:
            score += 0.10 * float(edge.match_rate)
            reasons.append(
                f"{edge.name} has been measured against the data: "
                f"{float(edge.match_rate) * 100:.1f}% of rows match.")
        else:
            score -= 0.08
            reasons.append(
                f"{edge.name} has not been validated against the data, so its "
                "match rate is an assertion rather than a measurement.")
        if edge.confidence < 1.0:
            score -= (1.0 - edge.confidence) * 0.3
            reasons.append(
                f"{edge.name} carries a confidence of {edge.confidence:.2f}.")
        if edge.is_asof:
            reasons.append(
                f"{edge.left} and {edge.right} are reported at different "
                "frequencies, so this hop is an as-of join: the latest "
                "observation on or before the analysis period, never a later "
                "one.")
    return score, reasons


def find_paths(graph: JoinGraph, base: str, target: str, *,
               max_hops: int = MAX_PATH_HOPS) -> list[JoinPath]:
    """Every path from base to target, best first.

    Breadth-first so short paths are found first, and exhaustive to `max_hops`
    so the caller can be told there was a choice. A resolver that returns only
    its favourite cannot report ambiguity, and silently choosing between two
    materially different joins is how an analysis answers a question nobody
    asked.
    """
    if base == target:
        return [JoinPath(target=target, score=1.0,
                         reasons=["The dataset is already in the analysis."])]

    found: list[JoinPath] = []
    queue: deque[tuple[str, list[Edge], set[str]]] = deque([(base, [], {base})])

    while queue:
        node, path, seen = queue.popleft()
        if len(path) >= max_hops:
            continue
        for edge in graph.out(node):
            if edge.right in seen:
                continue
            extended = [*path, edge]
            if edge.right == target:
                score, reasons = _score(extended)
                found.append(JoinPath(target=target, edges=extended,
                                      score=score, reasons=reasons))
                continue
            queue.append((edge.right, extended, seen | {edge.right}))

    found.sort(key=lambda p: (-p.score, p.hops))
    return found


@dataclass
class Resolution:
    """The datasets an analysis will read, and how they will be joined."""

    base: str
    paths: list[JoinPath] = field(default_factory=list)
    #: Targets nothing could reach, with the reason.
    unreachable: dict[str, str] = field(default_factory=dict)
    #: Where more than one materially different path existed.
    ambiguous: dict[str, list[JoinPath]] = field(default_factory=dict)
    #: Anything the caller should be told before the numbers are believed.
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unreachable

    @property
    def datasets(self) -> list[str]:
        out = [self.base]
        for path in self.paths:
            for name in path.datasets:
                if name not in out:
                    out.append(name)
        return out

    def edges(self) -> list[Edge]:
        seen: set[tuple[str, str, str, str]] = set()
        out: list[Edge] = []
        for path in self.paths:
            for edge in path.edges:
                key = (edge.left, edge.left_field, edge.right, edge.right_field)
                if key in seen:
                    continue
                seen.add(key)
                out.append(edge)
        return out

    def summary(self) -> str:
        """The plan in one sentence, for the answer and the Trace."""
        if not self.paths:
            return f"Reads {self.base} only."
        names = ", ".join(p.target for p in self.paths)
        return (f"Joins {self.base} to {names} using "
                f"{len(self.edges())} governed relationship"
                f"{'' if len(self.edges()) == 1 else 's'}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "datasets": self.datasets,
            "paths": [p.to_dict() for p in self.paths],
            "edges": [e.to_dict() for e in self.edges()],
            "unreachable": dict(self.unreachable),
            "ambiguous": {k: [p.to_dict() for p in v]
                          for k, v in self.ambiguous.items()},
            "warnings": list(self.warnings),
            "ok": self.ok,
            "summary": self.summary(),
        }


def resolve(graph: JoinGraph, *, base: str, targets: list[str],
            max_hops: int = MAX_PATH_HOPS) -> Resolution:
    """Work out how to reach every target dataset from the base.

    Reports rather than decides where it is not sure. Two paths within
    `AMBIGUITY_MARGIN` of each other are a real choice — customer-level
    aggregation versus facility-level attribution give genuinely different
    answers — and the caller is handed both.
    """
    resolution = Resolution(base=base)

    for target in targets:
        if target == base:
            continue
        options = find_paths(graph, base, target, max_hops=max_hops)
        if not options:
            resolution.unreachable[target] = (
                f"No governed relationship connects {base} to {target} within "
                f"{max_hops} hops. Declare one in Data Builder, or the "
                "question cannot be answered from these datasets.")
            continue

        best = options[0]
        resolution.paths.append(best)

        # Distinct routes, not distinct relationship rows. Two governed
        # relationships between the same pair of datasets — one declared each
        # way round — walk the same tables, and listing that twice reads as a
        # rendering fault rather than as a genuine choice a steward must make.
        rivals: list[JoinPath] = []
        routes = {tuple(best.datasets)}
        for candidate in options[1:]:
            if best.score - candidate.score >= AMBIGUITY_MARGIN:
                continue
            route = tuple(candidate.datasets)
            if route in routes:
                continue
            routes.add(route)
            rivals.append(candidate)
        if rivals:
            resolution.ambiguous[target] = [best, *rivals[:2]]
            resolution.warnings.append(
                f"There is more than one way to reach {target}: "
                + "; ".join(p.describe() for p in [best, *rivals[:2]])
                + f". CreditProbe used {best.describe()} because "
                + (best.reasons[0].lower() if best.reasons else "it scored highest")
            )
        if best.multiplies:
            resolution.warnings.append(
                f"Reaching {target} crosses a relationship that can multiply "
                "rows. CreditProbe aggregates that side to the analysis grain "
                "before joining, so nothing is double-counted.")
        if any(e.confidence < LOW_CONFIDENCE for e in best.edges):
            resolution.warnings.append(
                f"The path to {target} uses a relationship the bank has not "
                "fully confirmed. Read the join lineage on the Trace before "
                "relying on this.")

    return resolution


def build_graph(relationships: list[dict[str, Any]]) -> JoinGraph:
    return JoinGraph(relationships)


__all__ = [
    "AMBIGUITY_MARGIN",
    "LATEST_ON_OR_BEFORE",
    "MANY_TO_MANY",
    "MANY_TO_ONE",
    "MAX_PATH_HOPS",
    "NO_PERIOD",
    "ONE_TO_MANY",
    "ONE_TO_ONE",
    "SAFE_CARDINALITIES",
    "SAME_PERIOD",
    "Edge",
    "JoinGraph",
    "JoinPath",
    "Resolution",
    "build_graph",
    "find_paths",
    "resolve",
]
