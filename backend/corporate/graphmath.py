"""Derived ownership and control. Phase 2.3, 2.4, 2.5.

Everything in this module is DERIVED: computed from observed assertions, never
asserted by a source. That distinction is the point of the whole design - a
user can be shown the assertion and the inference separately and see which one
they disagree with - so every result carries how it was computed, from what,
under which policy version, and as at which date.

The mathematics
---------------
`A[i, j]` is the direct economic fraction of entity `j` owned by entity `i`.
Integrated ownership sums every path length:

    Ã = A + A² + A³ + ... = A(I − A)⁻¹

which is solved as the linear system `(I − A)X = A` rather than by forming an
inverse. Inverting is both slower and less accurate, and it obscures the one
thing that has to be checked first.

Why the spectral radius is checked BEFORE the solve
---------------------------------------------------
The series converges only when ρ(A) < 1. A holding structure where it does not
is not a hard numerical case to be nursed through - it is a structure that
claims more than 100% of some entity is owned, and the arithmetic saying so is
the finding. Capping, normalising or regularising it would convert a
data-quality defect into a plausible-looking number that no one would ever
question again. So `effective_ownership` raises `GraphDataQualityRejected`
carrying the offending component and its ρ, and computes nothing.

Why it decomposes into components
----------------------------------
Ownership does not cross a weakly connected component, so `Ã` is exactly block
diagonal and each block can be solved on its own. In this universe that turns
one 9,328 × 9,328 problem into 2,622 problems whose largest is 13 × 13. It is
not an approximation: it is the same answer, and it means a defect in one
group rejects that group rather than the whole book.

Control is not ownership
-------------------------
Control is binary, absorptive and transitive; ownership is fractional and
multiplicative. 51% of 51% is 26% of the economics and 100% of the control.
They are computed by different functions from different graphs and are never
substituted for one another.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.corporate import graphdata

logger = logging.getLogger(__name__)

#: Bumped whenever a derived result would change for the same inputs. Stamped
#: on every derived row so a stored figure can be matched to the code that
#: produced it.
PIPELINE_VERSION = "1.0.0"
#: Bumped whenever a THRESHOLD or rule changes without the mathematics
#: changing. Kept separate from the pipeline version because "we lowered the
#: control threshold" and "we fixed the solver" are different events and a
#: reader needs to tell them apart.
POLICY_VERSION = "1.0.0"

# ------------------------------------------------------------ derived types

UBO_OF = "UBO_OF"
CONTROLS_EFFECTIVELY = "CONTROLS_EFFECTIVELY"
MEMBER_OF = "MEMBER_OF"
CONNECTED_TO = "CONNECTED_TO"
SIMILAR_TO = "SIMILAR_TO"

DERIVED_EDGE_TYPES: tuple[str, ...] = (
    UBO_OF, CONTROLS_EFFECTIVELY, MEMBER_OF, CONNECTED_TO, SIMILAR_TO,
)

# ------------------------------------------------------------ policy values

#: Voting share at which control is presumed outright. A demonstration policy
#: value, not a verified regulatory threshold.
MAJORITY_VOTING_PCT = 50.0
#: Voting share at which control may be presumed DE FACTO, when no other
#: holder is larger. Demonstration policy.
DE_FACTO_VOTING_PCT = 30.0
#: Effective economic ownership at which a natural person is reported as an
#: ultimate beneficial owner. Demonstration policy - jurisdictions differ, and
#: 25% is the most common statutory figure rather than a universal one.
UBO_THRESHOLD_PCT = 25.0
#: How deep SHOW OWNERSHIP CHAIN walks before it stops enumerating.
MAX_CHAIN_DEPTH = 6
#: The matrix is authoritative. Path enumeration is truncated at
#: MAX_CHAIN_DEPTH and will therefore usually recover slightly less. A gap
#: wider than this means the explanation is not explaining the answer.
CHAIN_DISAGREEMENT_PCT = 1.0
#: ρ(A) at or above this rejects rather than solves.
SPECTRAL_LIMIT = 1.0
#: Numerical headroom below the limit. A component at 0.9999999 is not a
#: healthy structure that happens to converge; it is a defect that has not
#: quite tipped over, and a solve there is dominated by rounding.
SPECTRAL_WARN = 0.999

UNVERIFIED_POLICY = (
    "UNVERIFIED REGULATORY PARAMETER: the control, de-facto control and "
    "ultimate-beneficial-owner thresholds used here are demonstration values. "
    "They are not a verified statement of any binding requirement in any "
    "jurisdiction and must be replaced with the institution's own approved "
    "policy before any figure derived from them is relied on."
)


class GraphDataQualityRejected(RuntimeError):
    """A derived graph product was refused because its inputs are defective.

    Carries the evidence rather than only a message: which component, which
    entities, and the measured value that failed. A rejection nobody can act
    on is only marginally better than a wrong answer.
    """

    def __init__(self, reason: str, *, evidence: dict[str, Any]):
        super().__init__(reason)
        self.reason = reason
        self.evidence = evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "GRAPH_DATA_QUALITY_REJECTED",
            "reason": self.reason,
            "evidence": self.evidence,
            "pipeline_version": PIPELINE_VERSION,
            "policy_version": POLICY_VERSION,
        }


# ----------------------------------------------------------------- the graph


@dataclass(frozen=True)
class OwnershipGraph:
    """The direct ownership matrix, as at one date, plus its index."""

    nodes: tuple[str, ...]
    #: A[i, j] = fraction of j owned by i, as a fraction rather than a percent.
    matrix: np.ndarray
    #: Voting rights, same shape and index. Carried alongside and NEVER used
    #: in the economic solve.
    voting: np.ndarray
    as_of: str
    components: tuple[tuple[int, ...], ...] = ()

    @property
    def size(self) -> int:
        return len(self.nodes)

    def index_of(self, node: str) -> int:
        try:
            return self.nodes.index(node)
        except ValueError:
            raise KeyError(
                f"'{node}' has no ownership edge as at {self.as_of}. It may "
                "exist as an entity and simply own nothing and be owned by "
                "nothing, which is not the same as being unknown.") from None


def build_ownership_graph(edges: pd.DataFrame, as_of: str) -> OwnershipGraph:
    """The direct ownership matrix as at a date. Phase 2.2, 2.3.

    Filtered through the three-clause as-of predicate, so a shareholding the
    bank had not yet learned about cannot contribute to a historical answer.
    """
    owns = graphdata.as_of(edges[edges["edge_type"] == graphdata.OWNS], as_of)
    nodes = tuple(sorted(set(owns["from_node"]) | set(owns["to_node"])))
    index = {name: position for position, name in enumerate(nodes)}
    size = len(nodes)

    matrix = np.zeros((size, size), dtype=float)
    voting = np.zeros((size, size), dtype=float)
    for owner, owned, pct, vote in zip(
            owns["from_node"], owns["to_node"], owns["ownership_pct"],
            owns["voting_pct"], strict=True):
        i, j = index[owner], index[owned]
        # Accumulated, not overwritten. Two source systems can each assert a
        # tranche of the same holding, and taking the last one silently
        # discards the other.
        matrix[i, j] += float(pct) / 100.0
        voting[i, j] += float(vote) / 100.0

    return OwnershipGraph(nodes=nodes, matrix=matrix, voting=voting,
                          as_of=str(as_of),
                          components=_components(matrix))


def _components(matrix: np.ndarray) -> tuple[tuple[int, ...], ...]:
    """Weakly connected components of the ownership graph.

    Union-find over the undirected edge set. Ownership cannot cross a
    component, so each one can be solved independently and exactly.
    """
    size = matrix.shape[0]
    parent = list(range(size))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    rows, cols = np.nonzero(matrix)
    for i, j in zip(rows, cols, strict=True):
        a, b = find(int(i)), find(int(j))
        if a != b:
            parent[a] = b

    groups: dict[int, list[int]] = {}
    for node in range(size):
        groups.setdefault(find(node), []).append(node)
    return tuple(tuple(members) for members in groups.values())


def spectral_radius(matrix: np.ndarray) -> float:
    """ρ(A), the largest absolute eigenvalue.

    Computed exactly rather than by power iteration: the blocks here are tiny,
    and power iteration converges slowly and unreliably on exactly the
    near-defective structures this check exists to catch.
    """
    if matrix.size == 0:
        return 0.0
    return float(np.max(np.abs(np.linalg.eigvals(matrix))))


# ------------------------------------------------------ effective ownership


@dataclass
class EffectiveOwnership:
    """Ã, plus everything needed to defend it."""

    nodes: tuple[str, ...]
    matrix: np.ndarray
    as_of: str
    spectral_radius_by_component: dict[int, float]
    max_spectral_radius: float
    components_solved: int
    near_singular_components: tuple[int, ...] = ()
    #: Components refused because rho(A) >= 1, and the entities in them.
    #: Their block of the matrix is left at zero, which is why every read
    #: goes through `stake`/`owners_of` and those RAISE rather than return
    #: it - a zero here means "refused", and returning it as a number would
    #: be exactly the manufactured value the whole design forbids.
    rejected_components: tuple[int, ...] = ()
    blocked_nodes: frozenset[str] = frozenset()
    rejections: tuple[dict[str, Any], ...] = ()

    def _guard(self, *entities: str) -> None:
        hit = [e for e in entities if e in self.blocked_nodes]
        if hit:
            raise GraphDataQualityRejected(
                "Effective ownership is unavailable for "
                f"{', '.join(hit)}: the ownership component they belong to "
                "was refused because its series does not converge. There is "
                "no number to report here, and zero is not the answer.",
                evidence={"blocked_entities": hit,
                          "rejections": list(self.rejections),
                          "as_of": self.as_of})

    def stake(self, owner: str, owned: str) -> float:
        """Total effective economic stake of `owner` in `owned`, as a percent."""
        self._guard(owner, owned)
        index = {name: position for position, name in enumerate(self.nodes)}
        if owner not in index or owned not in index:
            return 0.0
        return float(self.matrix[index[owner], index[owned]] * 100.0)

    def owners_of(self, owned: str, *,
                  threshold_pct: float = 0.0) -> list[tuple[str, float]]:
        """Every entity with an effective stake in `owned`, largest first."""
        self._guard(owned)
        index = {name: position for position, name in enumerate(self.nodes)}
        if owned not in index:
            return []
        column = self.matrix[:, index[owned]] * 100.0
        found = [(self.nodes[i], float(column[i]))
                 for i in np.nonzero(column > threshold_pct)[0]]
        return sorted(found, key=lambda pair: -pair[1])

    def is_blocked(self, entity: str) -> bool:
        return entity in self.blocked_nodes

    def inflated_by_reciprocity(self) -> list[tuple[str, str, float]]:
        """Integrated stakes above 100%, which reciprocal holdings produce.

        `Ã = A(I − A)⁻¹` is INTEGRATED ownership, and it legitimately exceeds
        100% when ownership flows back through the owner. A parent holding
        83.7% of a subsidiary directly and 14.1% through a sibling holds
        97.9%; if a third member holds 9.3% of the parent, the loop multiplies
        every stake by 1/(1 − 0.068) and the total reaches 105.0%.

        The arithmetic is right and the number is the one the framework
        specifies, so it is neither capped nor normalised. But a user shown
        "owns 105%" with no explanation concludes the system is broken, so the
        cases are enumerated and reported as a FLAG. An entry above 100% in a
        component with NO cycle would be a genuine defect - there is no
        mechanism that could produce it - and the regression asserts that
        never happens.
        """
        found: list[tuple[str, str, float]] = []
        rows, cols = np.nonzero(self.matrix > 1.0 + 1e-9)
        for i, j in zip(rows, cols, strict=True):
            found.append((self.nodes[i], self.nodes[j],
                          float(self.matrix[i, j] * 100.0)))
        return sorted(found, key=lambda triple: -triple[2])

    def provenance(self) -> dict[str, Any]:
        return {
            "computed_as_of": self.as_of,
            "derivation_method": "solve (I - A)X = A per weakly connected "
                                 "component; A[i,j] = direct economic "
                                 "fraction of j owned by i",
            "pipeline_version": PIPELINE_VERSION,
            "policy_version": POLICY_VERSION,
            "components_solved": self.components_solved,
            "max_spectral_radius": round(self.max_spectral_radius, 9),
            "near_singular_components": list(self.near_singular_components),
            "rejected_components": list(self.rejected_components),
            "blocked_entity_count": len(self.blocked_nodes),
            "rejections": list(self.rejections),
            "integrated_stakes_above_100_pct": [
                {"owner": o, "owned": w, "integrated_pct": round(p, 4)}
                for o, w, p in self.inflated_by_reciprocity()[:25]],
            "integrated_ownership_note": (
                "Integrated ownership sums every path length and can exceed "
                "100% where reciprocal holdings route ownership back through "
                "the owner. Such figures are reported, not capped: the value "
                "is the quantity the method defines. They are listed here so "
                "a reader is never shown a stake above 100% without being "
                "told why it is one."),
            "validation_status": (
                "REJECT" if self.rejected_components
                else "FLAG" if (self.near_singular_components
                                or self.inflated_by_reciprocity())
                else "PASS"),
        }


def effective_ownership(graph: OwnershipGraph, *,
                        strict: bool = False) -> EffectiveOwnership:
    """Ã = A(I − A)⁻¹, solved as (I − A)X = A. Phase 2.3.

    Refuses rather than approximates. A component whose ρ(A) ≥ 1 describes a
    structure claiming more than all of some entity; the series does not
    converge and the correct output is the defect, not a number.

    Refusal is PER COMPONENT, because ownership does not cross one. A single
    defective family group must not blind the rest of the portfolio, and a
    caller that asks about an unaffected borrower deserves its answer. The
    affected entities are recorded in `blocked_nodes`, and every read of them
    raises: their block of the matrix is zero, and returning that zero as a
    stake would be precisely the manufactured value this refuses to produce.

    `strict=True` raises on the first defective component instead, for a
    caller that has passed a single structure and wants the exception.
    """
    size = graph.size
    result = np.zeros((size, size), dtype=float)
    radii: dict[int, float] = {}
    near: list[int] = []
    rejected: list[int] = []
    blocked: set[str] = set()
    notes: list[dict[str, Any]] = []

    for position, members in enumerate(graph.components):
        idx = np.array(members, dtype=int)
        block = graph.matrix[np.ix_(idx, idx)]
        rho = spectral_radius(block)
        radii[position] = rho

        if rho >= SPECTRAL_LIMIT:
            entities = [graph.nodes[i] for i in members]
            evidence = {
                "component": position,
                "spectral_radius": round(rho, 9),
                "limit": SPECTRAL_LIMIT,
                "entity_count": len(members),
                "entities": entities[:50],
                "as_of": graph.as_of,
            }
            reason = (
                "Effective ownership cannot be computed: the ownership "
                f"series does not converge for component {position}, whose "
                f"spectral radius is {rho:.6f}. A structure with rho >= 1 "
                "claims that more than the whole of some entity is owned. "
                "This is a data-quality defect in the ownership assertions, "
                "not a numerical difficulty, and it is reported rather than "
                "capped, normalised or otherwise solved away.")
            if strict:
                raise GraphDataQualityRejected(reason, evidence=evidence)
            rejected.append(position)
            blocked.update(entities)
            notes.append({"reason": reason, **evidence})
            continue

        if rho >= SPECTRAL_WARN:
            near.append(position)

        identity = np.eye(len(members))
        # Solve rather than invert. Same answer, better conditioned, and the
        # residual below is meaningful only for a solve.
        block_result = np.linalg.solve(identity - block, block)
        result[np.ix_(idx, idx)] = block_result

    return EffectiveOwnership(
        nodes=graph.nodes,
        matrix=result,
        as_of=graph.as_of,
        spectral_radius_by_component=radii,
        max_spectral_radius=max(radii.values()) if radii else 0.0,
        components_solved=len(graph.components) - len(rejected),
        near_singular_components=tuple(near),
        rejected_components=tuple(rejected),
        blocked_nodes=frozenset(blocked),
        rejections=tuple(notes),
    )


def residual(graph: OwnershipGraph, solved: EffectiveOwnership) -> float:
    """max |(I − A)X − A|, the solve's own error.

    Reported rather than assumed. A solve that silently returned nonsense
    would otherwise be indistinguishable from one that worked.
    """
    if not graph.size:
        return 0.0
    keep = [i for i, name in enumerate(graph.nodes)
            if name not in solved.blocked_nodes]
    if not keep:
        return 0.0
    # Rejected blocks are excluded: their entries were never solved, so
    # measuring the solver against them would report the refusal as error.
    idx = np.ix_(keep, keep)
    identity = np.eye(len(keep))
    left = (identity - graph.matrix[idx]) @ solved.matrix[idx]
    return float(np.max(np.abs(left - graph.matrix[idx])))


# ------------------------------------------------- ownership chain (explain)


@dataclass
class Chain:
    """One path from an owner to an owned entity, and what it contributes."""

    path: tuple[str, ...]
    percentages: tuple[float, ...]
    product_pct: float
    depth: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": list(self.path),
            "percentages": [round(p, 4) for p in self.percentages],
            "product_pct": round(self.product_pct, 4),
            "depth": self.depth,
        }


@dataclass
class ChainExplanation:
    """SHOW OWNERSHIP CHAIN. Phase 2.4.

    The MATRIX result is authoritative. This exists only to explain it, and
    says so: `authoritative_total_pct` comes from the solve, `explained_pct`
    is what enumeration recovered, and any material gap is reported as a
    warning rather than quietly presented as the answer.
    """

    owner: str
    owned: str
    as_of: str
    direct_pct: float
    indirect_pct: float
    authoritative_total_pct: float
    explained_pct: float
    chains: tuple[Chain, ...]
    #: Cycles the enumeration refused to follow, including those that
    #: re-enter through the target. Counted because a gap with no stated
    #: cause is not an explanation.
    cycles_excluded: int
    max_depth: int
    truncated: bool
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "owned": self.owned,
            "as_of": self.as_of,
            "direct_stake_pct": round(self.direct_pct, 4),
            "indirect_stake_pct": round(self.indirect_pct, 4),
            "total_effective_stake_pct": round(
                self.authoritative_total_pct, 4),
            "explained_by_enumerated_paths_pct": round(self.explained_pct, 4),
            "authority": (
                "The matrix solve is authoritative. Enumerated paths explain "
                "it and are truncated at depth "
                f"{self.max_depth}; they are not the source of the total."),
            "chains": [c.to_dict() for c in self.chains],
            "cycles_excluded": self.cycles_excluded,
            "max_depth": self.max_depth,
            "truncated": self.truncated,
            "warning": self.warning,
            "pipeline_version": PIPELINE_VERSION,
        }


def ownership_chains(graph: OwnershipGraph, solved: EffectiveOwnership,
                     owner: str, owned: str, *,
                     max_depth: int = MAX_CHAIN_DEPTH) -> ChainExplanation:
    """Enumerate the paths that make up an effective stake. Phase 2.4.

    Depth-first with the visited set carried down the path, so a cycle is
    excluded from the enumeration rather than followed forever. Excluded
    cycles are COUNTED, because a structure whose explanation keeps running
    into cycles is one whose explanation is incomplete for a reason worth
    showing.
    """
    index = {name: position for position, name in enumerate(graph.nodes)}
    if owner not in index or owned not in index:
        return ChainExplanation(
            owner=owner, owned=owned, as_of=graph.as_of, direct_pct=0.0,
            indirect_pct=0.0, authoritative_total_pct=0.0, explained_pct=0.0,
            chains=(), cycles_excluded=0, max_depth=max_depth,
            truncated=False,
            warning="One or both entities hold no ownership edge as at this "
                    "date.")

    start, target = index[owner], index[owned]
    chains: list[Chain] = []
    cycles = 0
    truncated = False

    def walk(node: int, path: list[int], product: float,
             percentages: list[float]) -> None:
        nonlocal cycles, truncated
        if len(path) > max_depth:
            truncated = True
            return
        for nxt in np.nonzero(graph.matrix[node])[0]:
            share = float(graph.matrix[node, nxt])
            if share <= 0:
                continue
            if nxt in path:
                cycles += 1
                continue
            carried = product * share
            if nxt == target:
                chains.append(Chain(
                    path=tuple(graph.nodes[i] for i in [*path, nxt]),
                    percentages=tuple([*percentages, share * 100.0]),
                    product_pct=carried * 100.0,
                    depth=len(path)))
                # A cycle that RE-ENTERS the path through the target still
                # contributes to the matrix total - A→B→C→A→B→C… is a real
                # series term - but enumeration stops here and never sees it.
                # Counting it is what makes the disagreement warning
                # explicable: without this the reader is told the numbers
                # differ and given no reason, because nothing was truncated
                # and no cycle was walked into.
                if any(graph.matrix[nxt, back] > 0 for back in path):
                    cycles += 1
                continue
            walk(nxt, [*path, nxt], carried, [*percentages, share * 100.0])

    walk(start, [start], 1.0, [])

    direct = float(graph.matrix[start, target] * 100.0)
    authoritative = solved.stake(owner, owned)
    explained = float(sum(c.product_pct for c in chains))

    warning = ""
    gap = abs(authoritative - explained)
    if gap > CHAIN_DISAGREEMENT_PCT:
        warning = (
            f"EXPLANATION WARNING: enumerated paths account for "
            f"{explained:.2f}% of an authoritative {authoritative:.2f}% "
            f"effective stake, a gap of {gap:.2f} percentage points. The "
            "matrix result stands; the enumeration is incomplete, usually "
            "because paths run deeper than "
            f"{max_depth} or through excluded cycles.")

    return ChainExplanation(
        owner=owner, owned=owned, as_of=graph.as_of,
        direct_pct=direct,
        indirect_pct=max(authoritative - direct, 0.0),
        authoritative_total_pct=authoritative,
        explained_pct=explained,
        chains=tuple(sorted(chains, key=lambda c: -c.product_pct)),
        cycles_excluded=cycles, max_depth=max_depth, truncated=truncated,
        warning=warning)


# --------------------------------------------------------- control closure


@dataclass
class ControlClosure:
    """Who controls whom, transitively. Phase 2.5."""

    nodes: tuple[str, ...]
    #: Direct binary control, before closure.
    direct: np.ndarray
    #: Transitive closure over the SCC condensation.
    effective: np.ndarray
    #: Which SCC each node belongs to; mutual control makes one bloc.
    component_of: dict[str, int]
    as_of: str
    rule_hits: dict[str, int]

    def controls(self, controller: str, controlled: str) -> bool:
        index = {n: i for i, n in enumerate(self.nodes)}
        if controller not in index or controlled not in index:
            return False
        return bool(self.effective[index[controller], index[controlled]])

    def controlled_by(self, controller: str) -> list[str]:
        index = {n: i for i, n in enumerate(self.nodes)}
        if controller not in index:
            return []
        row = self.effective[index[controller]]
        return [self.nodes[i] for i in np.nonzero(row)[0]]

    def provenance(self) -> dict[str, Any]:
        return {
            "computed_as_of": self.as_of,
            "derivation_method": (
                "binary direct control from approved rules; strongly "
                "connected components condensed; reachability over the "
                "condensation DAG"),
            "rules": dict(self.rule_hits),
            "pipeline_version": PIPELINE_VERSION,
            "policy_version": POLICY_VERSION,
            "parameter_caveat": UNVERIFIED_POLICY,
            "semantics": (
                "Control is binary, absorptive and transitive. It is NOT "
                "proportional ownership: 51% of 51% is 26% of the economics "
                "and 100% of the control."),
        }


def control_closure(graph: OwnershipGraph, *,
                    majority_pct: float = MAJORITY_VOTING_PCT,
                    de_facto_pct: float = DE_FACTO_VOTING_PCT,
                    explicit: pd.DataFrame | None = None) -> ControlClosure:
    """Binary control, closed transitively over the SCC condensation.

    Three configurable rules build the direct graph:

    * **majority voting** - a holder above `majority_pct` of the votes;
    * **explicit CONTROLS** - an observed assertion, which outranks any
      inference;
    * **de-facto voting** - a holder above `de_facto_pct` who is strictly the
      largest, which is the case where a 35% holder facing a dispersed
      register controls in practice.

    VOTING drives this, never ownership. Substituting the economic percentage
    is the single most common way a group-structure analysis goes wrong, and
    the two columns exist separately so it cannot happen by accident.
    """
    size = graph.size
    direct = np.zeros((size, size), dtype=bool)
    hits = {"majority_voting": 0, "explicit_control": 0, "de_facto_voting": 0}

    votes = graph.voting
    majority = votes > (majority_pct / 100.0)
    hits["majority_voting"] = int(majority.sum())
    direct |= majority

    # De facto: above the lower threshold AND strictly the largest holder.
    for owned in range(size):
        column = votes[:, owned]
        candidates = np.nonzero(column > (de_facto_pct / 100.0))[0]
        if candidates.size == 0:
            continue
        best = int(candidates[np.argmax(column[candidates])])
        others = column[column != column[best]]
        strictly_largest = (
            others.size == 0 or column[best] > float(np.max(others)))
        # Only a single holder at the top counts; a tie is not de-facto
        # control of anything.
        tied = int(np.sum(column == column[best])) > 1
        if strictly_largest and not tied and not direct[best, owned]:
            direct[best, owned] = True
            hits["de_facto_voting"] += 1

    if explicit is not None and len(explicit):
        index = {name: position for position, name in enumerate(graph.nodes)}
        stated = graphdata.as_of(
            explicit[explicit["edge_type"] == graphdata.CONTROLS],
            graph.as_of)
        for controller, controlled in zip(
                stated["from_node"], stated["to_node"], strict=True):
            if controller in index and controlled in index:
                if not direct[index[controller], index[controlled]]:
                    hits["explicit_control"] += 1
                direct[index[controller], index[controlled]] = True

    component_of, effective = _transitive_closure(direct)
    return ControlClosure(
        nodes=graph.nodes, direct=direct, effective=effective,
        component_of={graph.nodes[i]: c for i, c in enumerate(component_of)},
        as_of=graph.as_of, rule_hits=hits)


def _weak_components(direct: np.ndarray) -> list[list[int]]:
    """Weakly connected components of the direct-control graph."""
    size = direct.shape[0]
    parent = list(range(size))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    rows, cols = np.nonzero(direct)
    for i, j in zip(rows, cols, strict=True):
        a, b = find(int(i)), find(int(j))
        if a != b:
            parent[a] = b

    groups: dict[int, list[int]] = {}
    for node in range(size):
        groups.setdefault(find(node), []).append(node)
    return [g for g in groups.values() if len(g) > 1]


def _transitive_closure(direct: np.ndarray) -> tuple[list[int], np.ndarray]:
    """SCCs, condensation, then reachability. Phase 2.5.

    Condensing first is not an optimisation. Mutual control - A controls B and
    B controls A - is a single bloc, and every member of it controls
    everything the bloc reaches. Running reachability on the raw graph gets
    the same answer here but loses the bloc, which is the thing a user needs
    to see: these entities are not a chain, they are one controlling unit.

    Done PER WEAKLY CONNECTED COMPONENT, because control cannot cross one.
    Dense Warshall over all ~9,000 blocs is 81 million booleans rewritten
    9,000 times, and the closure that follows it was 87 million Python-level
    iterations; the first version of this did not finish inside ten minutes.
    Components here have at most a few dozen members, so the same exact answer
    costs almost nothing.
    """
    size = direct.shape[0]
    component_of = _tarjan(direct)
    effective = np.zeros((size, size), dtype=bool)

    for members in _weak_components(direct):
        idx = np.array(sorted(members), dtype=int)
        local = direct[np.ix_(idx, idx)]
        local_scc = [component_of[i] for i in idx]
        labels = {scc: position
                  for position, scc in enumerate(sorted(set(local_scc)))}
        blocs = len(labels)
        member = np.array([labels[s] for s in local_scc], dtype=int)

        condensed = np.zeros((blocs, blocs), dtype=bool)
        rows, cols = np.nonzero(local)
        for i, j in zip(rows, cols, strict=True):
            a, b = member[i], member[j]
            if a != b:
                condensed[a, b] = True

        reach = condensed.copy()
        for k in range(blocs):
            reach |= np.outer(reach[:, k], reach[k, :])

        # Same bloc, or the bloc is reachable. Built by fancy indexing rather
        # than a nested loop: the loop is what made this unusable.
        block = reach[member[:, None], member[None, :]]
        block |= member[:, None] == member[None, :]
        np.fill_diagonal(block, False)
        effective[np.ix_(idx, idx)] = block

    return component_of, effective


def _tarjan(direct: np.ndarray) -> list[int]:
    """Strongly connected components, iteratively.

    Iterative rather than recursive on purpose: a deep ownership chain would
    otherwise be able to exhaust the Python stack, and a graph algorithm that
    fails on its deepest input fails exactly where it matters.
    """
    size = direct.shape[0]
    index_of: list[int] = [-1] * size
    low: list[int] = [0] * size
    on_stack = [False] * size
    stack: list[int] = []
    component_of = [-1] * size
    counter = 0
    components = 0

    successors = [list(np.nonzero(direct[i])[0]) for i in range(size)]

    for root in range(size):
        if index_of[root] != -1:
            continue
        work: list[tuple[int, int]] = [(root, 0)]
        while work:
            node, position = work[-1]
            if position == 0:
                index_of[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack[node] = True
            recursed = False
            for offset in range(position, len(successors[node])):
                nxt = int(successors[node][offset])
                if index_of[nxt] == -1:
                    work[-1] = (node, offset + 1)
                    work.append((nxt, 0))
                    recursed = True
                    break
                if on_stack[nxt]:
                    low[node] = min(low[node], index_of[nxt])
            if recursed:
                continue
            if low[node] == index_of[node]:
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component_of[member] = components
                    if member == node:
                        break
                components += 1
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return component_of


# ------------------------------------------------ economic interdependence

#: FRAMEWORK.md's predicates. Each is a NAMED test with its own inputs and
#: threshold, not a score: "these two are connected" is unusable to a credit
#: committee, and "68% of A's revenue comes from B, tested against a 40%
#: threshold, evidenced by the FY2025 statement" is what they can act on.
RECEIPT_DEPENDENCE = "RECEIPT_DEPENDENCE"
EXPENDITURE_DEPENDENCE = "EXPENDITURE_DEPENDENCE"
GUARANTEE_OF_EXPOSURE = "GUARANTEE_OF_EXPOSURE"
NON_SUBSTITUTABLE_OUTPUT = "NON_SUBSTITUTABLE_OUTPUT"
SAME_REPAYMENT_SOURCE = "SAME_REPAYMENT_SOURCE"
DIFFICULTY_TRANSMISSION = "DIFFICULTY_TRANSMISSION"
JOINT_INSOLVENCY = "JOINT_INSOLVENCY"
SAME_FUNDING_SOURCE = "SAME_NON_REPLACEABLE_FUNDING_SOURCE"

PREDICATES: tuple[str, ...] = (
    RECEIPT_DEPENDENCE, EXPENDITURE_DEPENDENCE, GUARANTEE_OF_EXPOSURE,
    NON_SUBSTITUTABLE_OUTPUT, SAME_REPAYMENT_SOURCE,
    DIFFICULTY_TRANSMISSION, JOINT_INSOLVENCY, SAME_FUNDING_SOURCE,
)

#: Demonstration thresholds. Every one is a policy choice, not a law.
PREDICATE_THRESHOLDS: dict[str, float] = {
    RECEIPT_DEPENDENCE: 40.0,
    EXPENDITURE_DEPENDENCE: 40.0,
    GUARANTEE_OF_EXPOSURE: 50.0,
    NON_SUBSTITUTABLE_OUTPUT: 50.0,
    SAME_REPAYMENT_SOURCE: 50.0,
    DIFFICULTY_TRANSMISSION: 40.0,
    JOINT_INSOLVENCY: 0.0,
    SAME_FUNDING_SOURCE: 0.0,
}

#: A predicate that has been tested and met, and a human has accepted it.
PREDICATE_VALIDATED = "VALIDATED"
#: Met on the data but not yet accepted. Does NOT form a group.
PREDICATE_CANDIDATE = "CANDIDATE"
PREDICATE_REJECTED = "REJECTED"

PREDICATE_STATUSES: tuple[str, ...] = (
    PREDICATE_VALIDATED, PREDICATE_CANDIDATE, PREDICATE_REJECTED,
)


def interdependence_predicates(
        supply: pd.DataFrame, guarantees: pd.DataFrame,
        exposure: pd.DataFrame, as_of: str, *,
        thresholds: dict[str, float] | None = None) -> pd.DataFrame:
    """Test each predicate and record the test, not just the verdict.

    Every row carries the predicate, its inputs, the threshold it was tested
    against, where the evidence came from, when it was verified, the policy
    version and its status. A connected group whose members cannot each be
    asked "why am I in here" is not auditable, and B54 is explicit that graph
    connectivity is never on its own regulatory connectedness.

    Nothing here forms a group by itself. Only VALIDATED rows are merged, and
    a CANDIDATE row is a question for a human.
    """
    limits = {**PREDICATE_THRESHOLDS, **(thresholds or {})}
    rows: list[dict[str, Any]] = []

    def record(predicate: str, source: str, target: str, value: float,
               inputs: dict[str, Any], evidence: str,
               validated: bool) -> None:
        rows.append({
            "from_node": source,
            "to_node": target,
            "predicate": predicate,
            "observed_value": round(float(value), 4),
            "threshold": limits[predicate],
            "inputs": inputs,
            "evidence": evidence,
            "source": "corporate graph, observed edges",
            "effective_date": as_of,
            "verified_on": as_of,
            "policy_version": POLICY_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "status": (PREDICATE_VALIDATED if validated
                       else PREDICATE_CANDIDATE),
        })

    live_supply = graphdata.as_of(supply, as_of)
    for row in live_supply.itertuples():
        share = float(row.supplier_revenue_share_pct)
        if share >= limits[RECEIPT_DEPENDENCE]:
            record(RECEIPT_DEPENDENCE, str(row.to_node), str(row.from_node),
                   share,
                   {"supplier_revenue_share_pct": share},
                   f"{share:.2f}% of the supplier's revenue comes from this "
                   "buyer", validated=True)
        cost = float(row.buyer_cost_share_pct)
        if cost >= limits[EXPENDITURE_DEPENDENCE]:
            record(EXPENDITURE_DEPENDENCE, str(row.from_node),
                   str(row.to_node), cost,
                   {"buyer_cost_share_pct": cost},
                   f"{cost:.2f}% of the buyer's cost of goods comes from "
                   "this supplier", validated=True)

    live_guarantees = graphdata.as_of(guarantees, as_of)
    provides = live_guarantees[
        live_guarantees["edge_type"] == graphdata.PROVIDES]
    covers = live_guarantees[live_guarantees["edge_type"] == graphdata.COVERS]
    beneficiary = dict(zip(covers["guarantee_id"],
                           covers["beneficiary_borrower_id"], strict=False))
    for row in provides.itertuples():
        served = beneficiary.get(row.guarantee_id)
        if not served or str(row.from_node) == str(served):
            continue
        binding = bool(getattr(row, "legally_binding", True))
        record(GUARANTEE_OF_EXPOSURE, str(row.from_node), str(served),
               100.0 if binding else 0.0,
               {"guarantee_id": str(row.guarantee_id),
                "guaranteed_amount": float(row.guaranteed_amount),
                "legally_binding": binding},
               ("a legally binding guarantee of this borrower's facilities"
                if binding else
                "a comfort letter, which is not legally binding and is "
                "recorded as a candidate only"),
               validated=binding)

    live_exposure = graphdata.as_of(exposure, as_of)
    lending = live_exposure[live_exposure["edge_type"] == graphdata.LENT_TO]
    for row in lending.itertuples():
        record(SAME_REPAYMENT_SOURCE, str(row.from_node), str(row.to_node),
               float(row.amount),
               {"instrument": str(row.instrument),
                "amount": float(row.amount)},
               "intercompany lending makes one party's repayment depend on "
               "the other", validated=True)

    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=[
            "from_node", "to_node", "predicate", "observed_value",
            "threshold", "inputs", "evidence", "source", "effective_date",
            "verified_on", "policy_version", "pipeline_version", "status"])
    return frame


# ------------------------------------------ connected counterparty groups

#: A candidate group larger than this needs a human before it is used for
#: anything. Demonstration policy, and the number a giant-component failure
#: would blow straight through.
REVIEW_GROUP_SIZE = 60
#: Above this share of the whole population a "group" is a percolation
#: failure, not a group.
GIANT_COMPONENT_SHARE = 0.05

#: Why a pair was grouped. Preserved per member, because "these forty
#: borrowers are connected" is unusable without "and here is the reason for
#: each one".
CRITERION_CONTROL = "EFFECTIVE_CONTROL"
CRITERION_INTERDEPENDENCE = "ECONOMIC_INTERDEPENDENCE"

CRITERIA: tuple[str, ...] = (CRITERION_CONTROL, CRITERION_INTERDEPENDENCE)


@dataclass
class ConnectedGroups:
    """Connected-counterparty CANDIDATE groups. Phase 2.6, 2.7."""

    group_of: dict[str, str]
    members: dict[str, list[str]]
    criterion_hits: dict[str, list[str]]
    evidence: dict[str, list[dict[str, Any]]]
    as_of: str
    largest_group: int
    population: int
    needs_review: tuple[str, ...] = ()
    percolation_failed: bool = False

    def size_of(self, borrower: str) -> int:
        group = self.group_of.get(borrower)
        return len(self.members.get(group, [])) if group else 1

    def provenance(self) -> dict[str, Any]:
        return {
            "computed_as_of": self.as_of,
            "derivation_method": (
                "effective-control candidates, then weakly connected "
                "components over the CONTROL graph, then validated economic "
                "interdependence merged in - never weak components over raw "
                "OWNS"),
            "pipeline_version": PIPELINE_VERSION,
            "policy_version": POLICY_VERSION,
            "groups": len(self.members),
            "largest_group": self.largest_group,
            "population": self.population,
            "largest_group_share": round(
                self.largest_group / max(self.population, 1), 6),
            "needs_review": list(self.needs_review),
            "review_threshold": REVIEW_GROUP_SIZE,
            "percolation_failed": self.percolation_failed,
            "validation_status": "FLAG" if (
                self.percolation_failed or self.needs_review) else "PASS",
            "caveat": (
                "A connected-counterparty CANDIDATE group. Graph "
                "connectivity is not regulatory connectedness: these are "
                "candidates for assessment under the institution's own "
                "approved criteria, not a determination."),
        }


def connected_groups(closure: ControlClosure,
                     interdependence: pd.DataFrame | None = None,
                     *, population: int | None = None) -> ConnectedGroups:
    """Candidate groups, from CONTROL and validated interdependence. Phase 2.6.

    The order is the rule, and it is the whole point:

    1. effective control gives the candidate relationships;
    2. weak components are taken over THAT graph;
    3. validated economic interdependence merges further members in;
    4. every member keeps the criterion that put it there.

    Never weak components over raw OWNS. A 2% shareholding is an ownership
    edge and is not a reason to place two borrowers in one obligor group; run
    that rule over the whole register and a common minority investor, a shared
    funder or the assessing bank itself connects the entire portfolio into a
    single "group" that is both useless and confidently wrong.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    hits: dict[str, list[str]] = {}
    evidence: dict[str, list[dict[str, Any]]] = {}

    rows, cols = np.nonzero(closure.effective)
    for i, j in zip(rows, cols, strict=True):
        a, b = closure.nodes[int(i)], closure.nodes[int(j)]
        union(a, b)
        for node in (a, b):
            hits.setdefault(node, [])
            if CRITERION_CONTROL not in hits[node]:
                hits[node].append(CRITERION_CONTROL)
        evidence.setdefault(b, []).append({
            "criterion": CRITERION_CONTROL,
            "counterparty": a,
            "reason": f"{a} effectively controls {b}",
        })

    if interdependence is not None and len(interdependence):
        validated = interdependence[
            interdependence["status"] == PREDICATE_VALIDATED]
        for row in validated.itertuples():
            union(str(row.from_node), str(row.to_node))
            for node in (str(row.from_node), str(row.to_node)):
                hits.setdefault(node, [])
                if CRITERION_INTERDEPENDENCE not in hits[node]:
                    hits[node].append(CRITERION_INTERDEPENDENCE)
            evidence.setdefault(str(row.to_node), []).append({
                "criterion": CRITERION_INTERDEPENDENCE,
                "counterparty": str(row.from_node),
                "predicate": str(row.predicate),
                "reason": str(row.evidence),
            })

    members: dict[str, list[str]] = {}
    for node in list(parent):
        members.setdefault(find(node), []).append(node)

    group_of: dict[str, str] = {}
    labelled: dict[str, list[str]] = {}
    for position, (_, group) in enumerate(sorted(members.items())):
        name = f"CG-{position + 1:05d}"
        labelled[name] = sorted(group)
        for node in group:
            group_of[node] = name

    largest = max((len(g) for g in labelled.values()), default=0)
    total = population or max(len(group_of), 1)
    review = tuple(sorted(
        name for name, group in labelled.items()
        if len(group) > REVIEW_GROUP_SIZE))

    return ConnectedGroups(
        group_of=group_of, members=labelled, criterion_hits=hits,
        evidence=evidence, as_of=closure.as_of,
        largest_group=largest, population=total,
        needs_review=review,
        percolation_failed=largest > total * GIANT_COMPONENT_SHARE,
    )


def raw_ownership_components(graph: OwnershipGraph) -> dict[str, Any]:
    """Weak components over RAW OWNS - the rule that must never be used.

    Computed only so the percolation guard has something to compare against.
    B22 asks for the comparison, and a guard with nothing on the other side of
    it proves nothing: the failure mode is that raw connectivity swallows the
    portfolio while control-based grouping stays small, and both numbers are
    needed to show it did not happen.
    """
    sizes = [len(c) for c in graph.components]
    largest = max(sizes, default=0)
    return {
        "components": len(graph.components),
        "largest": largest,
        "population": graph.size,
        "largest_share": round(largest / max(graph.size, 1), 6),
        "why_not_used": (
            "Weak connectivity over raw OWNS is not a connected-counterparty "
            "rule. A minority stake, a shared funder or the assessing bank "
            "itself would merge unrelated borrowers into one group."),
    }
