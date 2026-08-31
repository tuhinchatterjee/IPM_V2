"""Network analytics over the corporate graph. Phase 2.12 - 2.16.

Five families of measure, each answering a different question, and none of
them a credit measure:

``debtrank``     if this borrower fails, how much of the network's value is
                 impaired - a propagation measure, not a loss estimate.
``pagerank``     forward, reverse and personalised. Who transmits, who is
                 positioned to be hurt, and who matters relative to a seed.
``betweenness``  who sits on the paths between others - the conduits.
``louvain``      which borrowers form a community under modularity.
``similarity``   who shares enough evidence to be worth a second look.

What none of them is
--------------------
None of these is a probability of default, a rating, an IFRS 9 stage, an
expected credit loss or a capital number. DebtRank in particular reads like
one: it is a fraction, it rises with distress, and a reader who meets it
without its caveat will take it for a loss rate. Every result therefore
carries its own disclaimer, and the tests assert the disclaimer is there.

Determinism
-----------
Every algorithm here iterates over sorted structures and stops on a stated
tolerance or a stated cap. Two runs on the same graph give the same numbers,
because a network measure that moves between runs cannot be put in a report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import graphdata

logger = logging.getLogger(__name__)

NETWORK_VERSION = "1.0.0"
POLICY_VERSION = "1.0.0"

#: Said wherever a network measure is shown. Long on purpose: the short
#: version ("this is not a PD") is the one that gets dropped when space is
#: tight, and this one reads as a sentence a reviewer would want kept.
NOT_A_CREDIT_MEASURE = (
    "RELATIVE NETWORK RANKING. This is a structural measure of a borrower's "
    "position in the relationship graph. It is NOT a probability, NOT a "
    "probability of default, NOT a rating, NOT an IFRS 9 stage and NOT an "
    "expected credit loss. It ranks borrowers against each other in this "
    "population and carries no meaning outside it."
)

DEBTRANK_CAVEAT = (
    "DebtRank is network analytics and early warning. It measures how much "
    "of the network's value is impaired when a borrower is shocked. It is "
    "NOT an expected credit loss, NOT a capital methodology and NOT a "
    "regulatory measure of anything."
)


# ------------------------------------------------------------------ helpers


@dataclass(frozen=True)
class DirectedGraph:
    """A weighted directed graph over named nodes, as at one date."""

    nodes: tuple[str, ...]
    weights: np.ndarray
    as_of: str

    @property
    def size(self) -> int:
        return len(self.nodes)

    def index(self) -> dict[str, int]:
        return {name: position for position, name in enumerate(self.nodes)}


def exposure_graph(exposure: pd.DataFrame, guarantees: pd.DataFrame,
                   as_of: str, *, borrowers: list[str] | None = None
                   ) -> DirectedGraph:
    """u -> v means u CARRIES EXPOSURE TO v. Phase 2.11.

    The convention is stated because the opposite one is equally natural and
    silently inverts every downstream answer: a graph where the arrow means
    "is owed by" makes the transmitters look like the victims.

    Guarantees are included as exposure of the GUARANTOR to the borrower it
    guarantees, which is what a guarantee is: the guarantor carries the
    borrower's failure.
    """
    live = graphdata.as_of(exposure, as_of)
    rows: list[tuple[str, str, float]] = [
        (str(r.from_node), str(r.to_node), float(r.amount))
        for r in live.itertuples()]

    live_guarantees = graphdata.as_of(guarantees, as_of)
    provides = live_guarantees[
        live_guarantees["edge_type"] == graphdata.PROVIDES]
    covers = live_guarantees[live_guarantees["edge_type"] == graphdata.COVERS]
    served = dict(zip(covers["guarantee_id"],
                      covers["beneficiary_borrower_id"], strict=False))
    for row in provides.itertuples():
        target = served.get(row.guarantee_id)
        if target and str(row.from_node) != str(target):
            rows.append((str(row.from_node), str(target),
                         float(row.guaranteed_amount)))

    names = sorted({a for a, _, _ in rows} | {b for _, b, _ in rows}
                   | set(borrowers or []))
    index = {name: position for position, name in enumerate(names)}
    weights = np.zeros((len(names), len(names)), dtype=float)
    for source, target, amount in rows:
        weights[index[source], index[target]] += amount
    return DirectedGraph(tuple(names), weights, str(as_of))


def _components(weights: np.ndarray) -> list[list[int]]:
    """Weakly connected components, so every measure can decompose."""
    size = weights.shape[0]
    parent = list(range(size))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    rows, cols = np.nonzero(weights)
    for i, j in zip(rows, cols, strict=True):
        a, b = find(int(i)), find(int(j))
        if a != b:
            parent[a] = b

    groups: dict[int, list[int]] = {}
    for node in range(size):
        groups.setdefault(find(node), []).append(node)
    return list(groups.values())


# ---------------------------------------------------------------- DebtRank

UNDISTRESSED = "UNDISTRESSED"
DISTRESSED = "DISTRESSED"
INACTIVE = "INACTIVE"

DEBTRANK_STATES: tuple[str, ...] = (UNDISTRESSED, DISTRESSED, INACTIVE)

#: Capital floor. A borrower whose recorded equity is negative or trivially
#: small would otherwise divide the impact matrix to infinity, and one bad
#: balance sheet would make every neighbour maximally vulnerable to it.
CAPITAL_FLOOR = 1.0
DEFAULT_SHOCK = 1.0
MAX_ITERATIONS = 100
TOLERANCE = 1e-9


@dataclass
class DebtRankResult:
    """One DebtRank run, and everything needed to reproduce it."""

    seed: str
    shock: float
    impact: float
    iterations: int
    converged: bool
    distress: dict[str, float]
    states: dict[str, str]
    as_of: str
    nodes_touched: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_borrower": self.seed,
            "shock": round(self.shock, 6),
            "network_impact": round(self.impact, 6),
            "iterations": self.iterations,
            "converged": self.converged,
            "nodes_touched": self.nodes_touched,
            "as_of": self.as_of,
            "method_version": NETWORK_VERSION,
            "policy_version": POLICY_VERSION,
            "validation_status": "PASS" if self.converged else "FLAG",
            "states": dict(sorted(self.states.items())),
            "caveat": DEBTRANK_CAVEAT,
        }


def impact_matrix(graph: DirectedGraph, capital: dict[str, float]) -> np.ndarray:
    """W[i, j] = min(1, X[i, j] / C[i]). Phase 2.12.

    The exposure of i to j, as a fraction of i's own capital, capped at one:
    a counterparty cannot cost more than everything you have. The cap is part
    of the published method rather than a convenience - without it a borrower
    with a thin balance sheet transmits impact above 100% and the measure
    stops being interpretable.
    """
    equity = np.array([max(capital.get(name, CAPITAL_FLOOR), CAPITAL_FLOOR)
                       for name in graph.nodes], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = graph.weights / equity[:, None]
    return np.clip(np.nan_to_num(ratio), 0.0, 1.0)


def debtrank(graph: DirectedGraph, capital: dict[str, float], seed: str, *,
             shock: float = DEFAULT_SHOCK,
             max_iterations: int = MAX_ITERATIONS) -> DebtRankResult:
    """Deterministic DebtRank from one seed. Phase 2.12.

    Three states, and the rule that gives the measure its name: a node
    PROPAGATES EXACTLY ONCE. After it has spread its distress it becomes
    INACTIVE and cannot spread again, which is what stops a cycle from
    amplifying a shock forever and is precisely the difference between
    DebtRank and a naive cascade.
    """
    index = graph.index()
    if seed not in index:
        return DebtRankResult(
            seed=seed, shock=shock, impact=0.0, iterations=0, converged=True,
            distress={}, states={}, as_of=graph.as_of, nodes_touched=0)

    weights = impact_matrix(graph, capital)
    size = graph.size
    distress = np.zeros(size, dtype=float)
    state = np.full(size, UNDISTRESSED, dtype=object)

    start = index[seed]
    distress[start] = float(np.clip(shock, 0.0, 1.0))
    state[start] = DISTRESSED

    iterations = 0
    converged = False
    for step in range(1, max_iterations + 1):
        iterations = step
        spreading = np.nonzero(state == DISTRESSED)[0]
        if spreading.size == 0:
            converged = True
            break

        # Everyone currently distressed spreads, then goes inactive. The
        # order is fixed by node index, so the result does not depend on set
        # iteration order.
        incoming = weights[:, spreading] @ distress[spreading]
        updated = np.minimum(distress + incoming, 1.0)

        moved = (updated - distress) > TOLERANCE
        for node in spreading:
            state[node] = INACTIVE
        newly = moved & (state == UNDISTRESSED)
        state[newly] = DISTRESSED
        distress = updated

        if not newly.any():
            converged = True
            break

    # Impact excludes the seed's own distress: the question is what the
    # network lost, not what the borrower that failed lost.
    others = [i for i in range(size) if i != start]
    impact = float(distress[others].sum() / max(len(others), 1))

    return DebtRankResult(
        seed=seed, shock=shock, impact=impact, iterations=iterations,
        converged=converged,
        distress={graph.nodes[i]: float(distress[i])
                  for i in range(size) if distress[i] > 0},
        states={graph.nodes[i]: str(state[i])
                for i in range(size) if state[i] != UNDISTRESSED},
        as_of=graph.as_of,
        nodes_touched=int((distress > 0).sum()))


def debtrank_all(graph: DirectedGraph, capital: dict[str, float], *,
                 seeds: list[str] | None = None) -> dict[str, float]:
    """Network impact for every seed, for ranking. Phase 2.14's input."""
    chosen = seeds if seeds is not None else list(graph.nodes)
    return {name: debtrank(graph, capital, name).impact for name in chosen}


# ---------------------------------------------------------------- PageRank

DAMPING = 0.85
PAGERANK_TOLERANCE = 1e-10
PAGERANK_MAX_ITERATIONS = 200


def pagerank(graph: DirectedGraph, *, damping: float = DAMPING,
             personalisation: dict[str, float] | None = None,
             reverse: bool = False,
             max_iterations: int = PAGERANK_MAX_ITERATIONS) -> dict[str, float]:
    """PageRank, forward or reverse, optionally personalised. Phase 2.13.

    Direction carries the meaning and is the thing most easily got backwards:

    * **forward** ranks TRANSMITTERS - rank flows along the exposure arrow,
      so a borrower many others are exposed to scores highly;
    * **reverse** ranks those STRUCTURALLY POSITIONED TO BE HURT - the same
      computation on the transposed graph;
    * **personalised** restarts at a chosen seed instead of uniformly, which
      makes the score relative to that borrower rather than to the book.

    Dangling nodes redistribute over the restart vector rather than leaking
    rank out of the system, so the result sums to one and can be compared
    across runs.
    """
    size = graph.size
    if size == 0:
        return {}

    weights = graph.weights.T if reverse else graph.weights
    out = weights.sum(axis=1)
    transition = np.zeros_like(weights)
    live = out > 0
    transition[live] = weights[live] / out[live, None]

    restart = np.full(size, 1.0 / size)
    if personalisation:
        index = graph.index()
        restart = np.zeros(size)
        for name, weight in personalisation.items():
            if name in index:
                restart[index[name]] = max(float(weight), 0.0)
        total = restart.sum()
        restart = restart / total if total > 0 else np.full(size, 1.0 / size)

    rank = restart.copy()
    for _ in range(max_iterations):
        dangling = float(rank[~live].sum())
        updated = (damping * (transition.T @ rank + dangling * restart)
                   + (1.0 - damping) * restart)
        if float(np.abs(updated - rank).sum()) < PAGERANK_TOLERANCE:
            rank = updated
            break
        rank = updated

    return {graph.nodes[i]: float(rank[i]) for i in range(size)}


# ------------------------------------------------------------- betweenness


def betweenness(graph: DirectedGraph, *,
                normalise: bool = True) -> dict[str, float]:
    """Brandes' betweenness, per weakly connected component. Phase 2.13.

    Who sits ON the paths between other borrowers - the conduits, as distinct
    from the endpoints. Computed on the unweighted directed graph, because
    the question is structural: whether a path exists through this node, not
    how much money travels it.

    Decomposed by component because betweenness is zero across components by
    definition, and running Brandes over the whole 3,800-node graph does
    O(N·E) work to prove it.
    """
    size = graph.size
    scores = dict.fromkeys(graph.nodes, 0.0)
    if size == 0:
        return scores

    adjacency = [np.nonzero(graph.weights[i])[0] for i in range(size)]

    for members in _components(graph.weights):
        if len(members) < 3:
            continue
        inside = set(members)
        for source in sorted(members):
            stack: list[int] = []
            predecessors: dict[int, list[int]] = {v: [] for v in members}
            sigma = dict.fromkeys(members, 0.0)
            distance = dict.fromkeys(members, -1)
            sigma[source] = 1.0
            distance[source] = 0
            queue = [source]
            head = 0
            while head < len(queue):
                node = queue[head]
                head += 1
                stack.append(node)
                for nxt in adjacency[node]:
                    nxt = int(nxt)
                    if nxt not in inside:
                        continue
                    if distance[nxt] < 0:
                        distance[nxt] = distance[node] + 1
                        queue.append(nxt)
                    if distance[nxt] == distance[node] + 1:
                        sigma[nxt] += sigma[node]
                        predecessors[nxt].append(node)

            delta = dict.fromkeys(members, 0.0)
            while stack:
                node = stack.pop()
                for pred in predecessors[node]:
                    if sigma[node] > 0:
                        delta[pred] += (sigma[pred] / sigma[node]) * (
                            1.0 + delta[node])
                if node != source:
                    scores[graph.nodes[node]] += delta[node]

    if normalise and size > 2:
        scale = 1.0 / ((size - 1) * (size - 2))
        scores = {name: value * scale for name, value in scores.items()}
    return scores


# ----------------------------------------------------------------- Louvain

LOUVAIN_MAX_PASSES = 20


def louvain(graph: DirectedGraph, *,
            max_passes: int = LOUVAIN_MAX_PASSES) -> dict[str, int]:
    """Deterministic modularity communities. Phase 2.13.

    Treated as UNDIRECTED and weighted, which is what modularity is defined
    on. Nodes are visited in index order rather than at random, so two runs on
    the same graph give the same labels - a community that renumbers between
    runs cannot be quoted in a report or compared across quarters.

    A community is not a group. Modularity finds densely connected regions;
    it says nothing about control, and Phase 2.6's grouping does not consult
    it.
    """
    size = graph.size
    if size == 0:
        return {}

    adjacency = graph.weights + graph.weights.T
    np.fill_diagonal(adjacency, 0.0)
    total = float(adjacency.sum())
    if total <= 0:
        return {name: position for position, name in enumerate(graph.nodes)}

    community = np.arange(size)
    strength = adjacency.sum(axis=1)

    for _ in range(max_passes):
        moved = False
        for node in range(size):
            current = community[node]
            neighbours = np.nonzero(adjacency[node])[0]
            if neighbours.size == 0:
                continue

            gains: dict[int, float] = {}
            for other in neighbours:
                label = int(community[other])
                gains[label] = gains.get(label, 0.0) + float(
                    adjacency[node, other])

            community[node] = -1
            sums = {label: float(strength[community == label].sum())
                    for label in gains}
            best, best_gain = current, -np.inf
            for label in sorted(gains):
                gain = gains[label] - strength[node] * sums[label] / total
                # Ties resolve to the lowest label, so the labelling is
                # reproducible rather than dependent on dict order.
                if gain > best_gain + 1e-12:
                    best, best_gain = label, gain
            community[node] = best
            if best != current:
                moved = True
        if not moved:
            break

    labels = {label: position
              for position, label in enumerate(sorted(set(community.tolist())))}
    return {graph.nodes[i]: labels[int(community[i])] for i in range(size)}


def modularity(graph: DirectedGraph, communities: dict[str, int]) -> float:
    """Newman modularity of a partition, for the regression to compare."""
    adjacency = graph.weights + graph.weights.T
    np.fill_diagonal(adjacency, 0.0)
    total = float(adjacency.sum())
    if total <= 0:
        return 0.0
    index = graph.index()
    labels = np.array([communities.get(name, -1) for name in graph.nodes])
    strength = adjacency.sum(axis=1)
    score = 0.0
    for label in sorted(set(labels.tolist())):
        members = np.nonzero(labels == label)[0]
        inside = float(adjacency[np.ix_(members, members)].sum())
        degree = float(strength[members].sum())
        score += inside / total - (degree / total) ** 2
    assert index is not None
    return float(score)


# ------------------------------------------------------ Network Risk Score

#: The published weights. They are constants rather than parameters because a
#: score whose weights move between runs cannot be compared across quarters,
#: and a reviewer who cannot see the weights cannot challenge the score.
NRS_WEIGHTS: dict[str, float] = {
    "debtrank": 0.45,
    "forward_pagerank": 0.35,
    "betweenness": 0.20,
}

#: The banner. Phase 2.14 requires this wording to travel with the number
#: everywhere it is shown - API, screen, export - because the number is a
#: 0-100 quantity that looks exactly like a score a reader already knows.
NRS_LABEL = (
    "NETWORK RISK SCORE - RELATIVE NETWORK RANKING / NOT A PROBABILITY / "
    "NOT PD / NOT A RATING / NOT IFRS 9 STAGE / NOT ECL"
)


def _normalise(values: dict[str, float]) -> dict[str, float]:
    """Min-max onto [0, 1] over the scored population.

    A degenerate population - every borrower identical, or one borrower -
    normalises to zero rather than to one. Mapping "no spread" onto the top of
    the scale would hand every borrower in a flat network the maximum score.
    """
    if not values:
        return {}
    low = min(values.values())
    high = max(values.values())
    span = high - low
    if span <= TOLERANCE:
        return dict.fromkeys(values, 0.0)
    return {name: (value - low) / span for name, value in values.items()}


@dataclass
class NetworkRiskScore:
    """The score for one population, with everything behind it. Phase 2.14."""

    scores: dict[str, float]
    components: dict[str, dict[str, float]]
    normalised: dict[str, dict[str, float]]
    weights: dict[str, float]
    population: int
    as_of: str

    def rank(self, borrower: str) -> int | None:
        """1 = highest score. Rank is the honest reading of this measure."""
        if borrower not in self.scores:
            return None
        order = sorted(self.scores.items(), key=lambda kv: (-kv[1], kv[0]))
        for position, (name, _) in enumerate(order, start=1):
            if name == borrower:
                return position
        return None

    def for_borrower(self, borrower: str) -> dict[str, Any]:
        if borrower not in self.scores:
            return {
                "network_risk_score": None,
                "status": "NOT_AVAILABLE",
                "reason": "Borrower is not a node in the network as at this date",
                "label": NRS_LABEL,
                "as_of": self.as_of,
            }
        return {
            "network_risk_score": round(self.scores[borrower], 2),
            "rank": self.rank(borrower),
            "population": self.population,
            "percentile": round(
                100.0 * (1.0 - ((self.rank(borrower) or 1) - 1)
                         / max(self.population - 1, 1)), 1),
            "components": {
                key: round(self.components[key].get(borrower, 0.0), 6)
                for key in sorted(self.components)},
            "normalised_components": {
                key: round(self.normalised[key].get(borrower, 0.0), 6)
                for key in sorted(self.normalised)},
            "weights": dict(sorted(self.weights.items())),
            "label": NRS_LABEL,
            "status": "AVAILABLE",
            "method_version": NETWORK_VERSION,
            "policy_version": POLICY_VERSION,
            "as_of": self.as_of,
        }


def network_risk_score(graph: DirectedGraph, capital: dict[str, float], *,
                       population: list[str] | None = None,
                       debtrank_impact: dict[str, float] | None = None,
                       ) -> NetworkRiskScore:
    """Combine the three structural measures into one ranking. Phase 2.14.

    The three answer different questions and are deliberately not
    interchangeable: DebtRank asks how much fails WITH this borrower,
    forward PageRank asks how central it is as a transmitter, betweenness
    asks whether it is the only path between others. A borrower can be high
    on one and low on the others, which is why the components are stored
    alongside the score rather than discarded.

    `debtrank_impact` is accepted so a caller that has already run the
    all-seeds sweep does not pay for it twice; when omitted it is computed.
    """
    members = list(population) if population is not None else list(graph.nodes)
    members = [name for name in members if name in graph.index()]

    impact = (debtrank_impact if debtrank_impact is not None
              else debtrank_all(graph, capital, seeds=members))
    forward = pagerank(graph)
    between = betweenness(graph)

    components = {
        "debtrank": {name: float(impact.get(name, 0.0)) for name in members},
        "forward_pagerank": {name: float(forward.get(name, 0.0))
                             for name in members},
        "betweenness": {name: float(between.get(name, 0.0))
                        for name in members},
    }
    normalised = {key: _normalise(values)
                  for key, values in components.items()}

    scores = {
        name: 100.0 * sum(NRS_WEIGHTS[key] * normalised[key].get(name, 0.0)
                          for key in NRS_WEIGHTS)
        for name in members
    }
    return NetworkRiskScore(
        scores=scores, components=components, normalised=normalised,
        weights=dict(NRS_WEIGHTS), population=len(members), as_of=graph.as_of)


# -------------------------------------------------- SIMILAR_TO / similarity

SIMILAR_TO = "SIMILAR_TO"

#: Above this Jaccard the pair is worth a human look. Set for a demo
#: population and labelled as such: the right threshold on a real book is an
#: empirical question about that book's address and director distributions,
#: and copying a demo number into production would be the error.
SIMILARITY_THRESHOLD = 0.30
SIMILARITY_UNVERIFIED = (
    "UNVERIFIED POLICY PARAMETER. The similarity threshold is calibrated for "
    "this synthetic population and is not a validated production threshold."
)

#: What a SIMILAR_TO edge is allowed to be, and the three things it is not.
SIMILARITY_LABEL = "HIDDEN RELATIONSHIP CANDIDATE"
SIMILARITY_PRESENTATION = "DOTTED"
SIMILARITY_CAVEAT = (
    "HIDDEN RELATIONSHIP CANDIDATE. Shared evidence only. This is a "
    "suggestion for investigation. It does NOT establish control, does NOT "
    "establish beneficial ownership and does NOT place either borrower in a "
    "connected group. Only observed and derived control evidence does that."
)

#: Evidence that counts. Sector is excluded on purpose: every borrower has
#: one, thousands share it, and including it would make the whole population
#: look mildly similar to itself and drown the real signal.
SIMILARITY_EVIDENCE: tuple[str, ...] = (
    graphdata.DIRECTOR_OF, graphdata.REGISTERED_AT, graphdata.FUNDED_BY,
)


def evidence_sets(people: pd.DataFrame, as_of_date: str, *,
                  edge_types: tuple[str, ...] = SIMILARITY_EVIDENCE,
                  ) -> dict[str, set[str]]:
    """Borrower -> the set of shared things it touches, as at a date.

    A director edge points person -> company and an address edge points
    company -> address, so the borrower is on a different end of each. Getting
    that backwards produces an empty intersection everywhere and a similarity
    engine that silently finds nothing.
    """
    live = graphdata.as_of(people, as_of_date)
    live = live[live["edge_type"].isin(edge_types)]
    sets: dict[str, set[str]] = {}
    for row in live.itertuples():
        if row.edge_type == graphdata.DIRECTOR_OF:
            borrower, token = str(row.to_node), f"DIR:{row.from_node}"
        else:
            borrower, token = str(row.from_node), f"{row.edge_type}:{row.to_node}"
        sets.setdefault(borrower, set()).add(token)
    return sets


def jaccard(left: set[str], right: set[str]) -> float:
    """|A n B| / |A u B|. Zero for two empty sets, not one.

    Two borrowers about whom nothing is known are not similar; they are
    unknown. The 0/0 = 1 convention would rank every data gap as a perfect
    match and put the least-documented borrowers at the top of the list.
    """
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


@dataclass(frozen=True)
class SimilarityCandidate:
    """One dotted line, and why it is dotted."""

    left: str
    right: str
    score: float
    shared: tuple[str, ...]
    as_of: str

    def to_edge(self) -> dict[str, Any]:
        return {
            "edge_type": SIMILAR_TO,
            "from_node": self.left,
            "to_node": self.right,
            "similarity": round(self.score, 4),
            "shared_evidence": list(self.shared),
            "shared_evidence_count": len(self.shared),
            "label": SIMILARITY_LABEL,
            "presentation": SIMILARITY_PRESENTATION,
            "creates_control": False,
            "creates_ubo": False,
            "creates_group_membership": False,
            "caveat": SIMILARITY_CAVEAT,
            "threshold": SIMILARITY_THRESHOLD,
            "threshold_status": SIMILARITY_UNVERIFIED,
            "method_version": NETWORK_VERSION,
            "policy_version": POLICY_VERSION,
            "as_of": self.as_of,
            "origin": graphdata.ORIGIN,
        }


def similarity_candidates(people: pd.DataFrame, as_of_date: str, *,
                          threshold: float = SIMILARITY_THRESHOLD,
                          subjects: list[str] | None = None,
                          limit: int | None = None,
                          ) -> list[SimilarityCandidate]:
    """Pairs above the threshold. Phase 2.15.

    Candidates are found through an inverted index rather than by comparing
    every pair: at 3,800 borrowers the all-pairs form is 7.2 million
    comparisons for a result that is almost entirely zeros, because two
    borrowers with no shared token cannot have a non-zero Jaccard.
    """
    sets = evidence_sets(people, as_of_date)
    wanted = set(subjects) if subjects else None

    holders: dict[str, list[str]] = {}
    for borrower, tokens in sets.items():
        for token in tokens:
            holders.setdefault(token, []).append(borrower)

    seen: set[tuple[str, str]] = set()
    for members in holders.values():
        if len(members) > 400:
            # A token shared by hundreds is a serviced-office address or a
            # funding channel: it carries no information about any pair, and
            # pairing its members would be quadratic in the worst place.
            continue
        ordered = sorted(set(members))
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                if wanted and left not in wanted and right not in wanted:
                    continue
                seen.add((left, right))

    found: list[SimilarityCandidate] = []
    for left, right in sorted(seen):
        score = jaccard(sets.get(left, set()), sets.get(right, set()))
        if score < threshold:
            continue
        shared = tuple(sorted(sets[left] & sets[right]))
        found.append(SimilarityCandidate(left=left, right=right, score=score,
                                         shared=shared, as_of=as_of_date))

    found.sort(key=lambda c: (-c.score, c.left, c.right))
    return found[:limit] if limit else found


# ------------------------------------------------------- graph confidence

#: How a derived relationship inherits confidence: the WEAKEST link on the
#: path, not the average and not the product.
#:
#: The average lets a long chain of registry filings hide one relationship
#: manager's note. The product punishes length rather than weakness - six
#: certain steps would come out less confident than two doubtful ones. The
#: minimum says the true thing: a conclusion is exactly as good as the worst
#: assertion it depends on.
CONFIDENCE_RULE = "WEAKEST_EVIDENCE_ON_PATH"

CONFIDENCE_BANDS: tuple[tuple[float, str], ...] = (
    (0.90, "HIGH"),
    (0.70, "MEDIUM"),
    (0.00, "LOW"),
)


def confidence_band(value: float) -> str:
    for floor, band in CONFIDENCE_BANDS:
        if value >= floor:
            return band
    return "LOW"


@dataclass(frozen=True)
class PathConfidence:
    """The confidence of one derived relationship, and its weakest link."""

    value: float
    band: str
    weakest_edge: str | None
    weakest_source: str | None
    steps: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": round(self.value, 4),
            "confidence_band": self.band,
            "rule": CONFIDENCE_RULE,
            "weakest_edge_id": self.weakest_edge,
            "weakest_evidence_source": self.weakest_source,
            "path_length": self.steps,
            "method_version": NETWORK_VERSION,
        }


def path_confidence(edges: list[dict[str, Any]]) -> PathConfidence:
    """Confidence of a derived edge from the observed edges under it.

    An empty path is UNKNOWN at 0.0, not certain at 1.0: a derived
    relationship with no evidence beneath it is the case a reviewer most needs
    to see, and defaulting it to full confidence would bury it.
    """
    if not edges:
        return PathConfidence(value=0.0, band="LOW", weakest_edge=None,
                              weakest_source=None, steps=0)
    weakest = min(edges, key=lambda e: (float(e.get("confidence", 0.0)),
                                        str(e.get("edge_id", ""))))
    value = float(weakest.get("confidence", 0.0))
    return PathConfidence(
        value=value,
        band=confidence_band(value),
        weakest_edge=str(weakest.get("edge_id")) if weakest.get("edge_id")
        else None,
        weakest_source=str(weakest.get("source")) if weakest.get("source")
        else None,
        steps=len(edges))


def chain_confidence(chain_edges: pd.DataFrame,
                     edge_ids: list[str]) -> PathConfidence:
    """`path_confidence` against an edge frame, by edge id."""
    if not edge_ids:
        return path_confidence([])
    lookup = chain_edges.set_index("edge_id")
    rows: list[dict[str, Any]] = []
    for edge_id in edge_ids:
        if edge_id not in lookup.index:
            # A path referencing an edge that is not in the as-of view is not
            # a low-confidence path, it is a broken one.
            return PathConfidence(value=0.0, band="LOW", weakest_edge=edge_id,
                                  weakest_source="EDGE NOT FOUND AS AT DATE",
                                  steps=len(edge_ids))
        row = lookup.loc[edge_id]
        rows.append({"edge_id": edge_id,
                     "confidence": float(row["confidence"]),
                     "source": str(row["source"])})
    return path_confidence(rows)
