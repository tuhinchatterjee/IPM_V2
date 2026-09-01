"""
Who stands above this borrower, who stands below it, and who stands beside it.

R2 §2. The neighbourhood already existed — `service.ego_graph` expands it
server-side and returns nodes and edges. What it did not say is the one thing
a credit officer opens a group structure to find out: WHICH WAY the
relationship runs.

Three directions, and they are three different risks
-----------------------------------------------------
**UPSTREAM.** Parents, ultimate and beneficial owners, control entities,
holding companies, guarantors, support providers. Everything above the
borrower. The question is *who can be called on, and who can pull the rug*: a
guarantor upstream is credit support, and a leveraged parent upstream is a
claim on the borrower's cash.

**DOWNSTREAM.** Subsidiaries, controlled entities, investments, facilities,
guaranteed entities. Everything below. The question is *what does this
borrower carry* — a subsidiary in difficulty is the borrower's problem long
before it is anybody else's.

**LATERAL.** Sister companies, entities under a common owner, connected
counterparties, cross-guarantees. Beside, not above or below. The question is
*what else moves when this moves*, and it is the direction most systems do not
model at all, because it cannot be read off a single edge — a sister is only a
sister by way of the parent they share.

How the direction is decided
-----------------------------
By the DIRECTED path from the centre, not by the edge type. `A OWNS B` read
from B is a parent and read from A is a subsidiary, and the same row of the
same dataset supplies both. So the traversal runs twice — once following
edges into the centre and once following them out — and anything reachable
only by a path that changes direction on the way is lateral.

That last clause is the whole definition of a sister company: up to the
parent, then down to the sibling. A traversal that could not change direction
would find no sisters, and one that ignored direction would call the sister a
parent.

Control and economics are not the same number
----------------------------------------------
`ownership_pct` is the economics and `voting_pct` is the control, and they
differ on purpose: 51% of 51% is 26% of the economics and 100% of the
control. Both travel on the edge, and the classification says which of the
two makes the relationship material, so the screen can draw them differently
rather than picking one and calling it "ownership".

Nothing here computes a figure the graph datasets do not already carry.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.corporate import graphdata

RELATIONSHIPS_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# The three directions
# ---------------------------------------------------------------------------

UPSTREAM = "UPSTREAM"
DOWNSTREAM = "DOWNSTREAM"
LATERAL = "LATERAL"

DIRECTIONS: tuple[str, ...] = (UPSTREAM, DOWNSTREAM, LATERAL)

DIRECTION_LABELS: dict[str, str] = {
    UPSTREAM: "Above this borrower",
    DOWNSTREAM: "Below this borrower",
    LATERAL: "Beside this borrower",
}

DIRECTION_QUESTIONS: dict[str, str] = {
    UPSTREAM: "Who can be called on, and who has a claim on this borrower's "
              "cash?",
    DOWNSTREAM: "What does this borrower carry, and what can it be asked to "
                "support?",
    LATERAL: "What else in the book moves when this borrower moves?",
}

# ---------------------------------------------------------------------------
# What one edge means, read from each end
# ---------------------------------------------------------------------------

#: (looking up from the target, looking down from the source). Read from the
#: CENTRE outwards: the first is what the other party is TO the centre when
#: the edge points at the centre, the second when it points away.
_MEANING: dict[str, tuple[str, str]] = {
    graphdata.OWNS: ("Shareholder", "Investment"),
    graphdata.CONTROLS: ("Controlling entity", "Controlled entity"),
    graphdata.PROVIDES: ("Guarantor", "Guarantee given"),
    graphdata.COVERS: ("Covered by", "Covers"),
    graphdata.HOLDS: ("Held by", "Holds"),
    graphdata.LENT_TO: ("Lender", "Borrower from this entity"),
    graphdata.SUPPLIES_TO: ("Supplier", "Customer"),
    graphdata.EXPOSED_TO: ("Exposed to this entity", "Exposure to"),
    graphdata.FUNDED_BY: ("Funder", "Funds"),
    graphdata.DIRECTOR_OF: ("Director", "Board seat held by this entity"),
    graphdata.REGISTERED_AT: ("Registered address of", "Registered at"),
    graphdata.IN_SECTOR: ("Sector member", "Sector"),
}

#: Edge types on which a percentage is CONTROL rather than economics. Both
#: numbers travel on an OWNS edge; on a CONTROLS edge only the voting one
#: means anything.
_CONTROL_EDGES: frozenset[str] = frozenset({graphdata.CONTROLS})

#: A holding above this is a controlling stake by the ordinary convention.
#: Named because the screen colours by it, and a threshold buried in a
#: comparison is a policy nobody can find.
CONTROL_THRESHOLD = 50.0

#: At or above this, a holding is a significant economic interest even when it
#: carries no control. The same 25% the effective-ownership group uses.
SIGNIFICANT_THRESHOLD = 25.0


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


# ---------------------------------------------------------------------------
# One related party
# ---------------------------------------------------------------------------


@dataclass
class Related:
    """One entity in the neighbourhood, and how it stands to the centre."""

    node_id: str
    label: str
    node_type: str
    detail: str = ""
    direction: str = LATERAL
    #: Steps from the centre. 1 is a direct relationship.
    depth: int = 1
    #: What this party IS to the centre, in a credit officer's words.
    relationship: str = ""
    #: The edge type that decided it, kept for the Trace.
    edge_type: str = ""
    ownership_pct: float | None = None
    voting_pct: float | None = None
    #: A guaranteed or lent amount where the edge carries one. SAR millions,
    #: the unit every monetary figure in the corporate lake is in.
    amount: float | None = None
    instrument: str = ""
    source: str = ""
    confidence: float | None = None
    #: The chain of node ids from the centre to here, so a lateral party can
    #: show WHICH parent makes it a sister rather than merely asserting it.
    via: list[str] = field(default_factory=list)
    #: True when the party is a borrower on this book rather than a holding
    #: company, an address or a natural person.
    is_borrower: bool = False
    exposure: float | None = None

    @property
    def controls(self) -> bool:
        """Whether this relationship carries control rather than economics."""
        if self.edge_type in _CONTROL_EDGES:
            return True
        voting = self.voting_pct
        return voting is not None and voting > CONTROL_THRESHOLD

    @property
    def significant(self) -> bool:
        held = self.ownership_pct
        return held is not None and held >= SIGNIFICANT_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "label": self.label,
            "node_type": self.node_type, "detail": self.detail,
            "direction": self.direction, "depth": self.depth,
            "relationship": self.relationship, "edge_type": self.edge_type,
            "ownership_pct": self.ownership_pct,
            "voting_pct": self.voting_pct,
            "amount": self.amount, "instrument": self.instrument,
            "source": self.source, "confidence": self.confidence,
            "via": list(self.via), "is_borrower": self.is_borrower,
            "exposure": self.exposure,
            "controls": self.controls, "significant": self.significant,
        }


@dataclass
class Network:
    """The classified neighbourhood of one borrower."""

    centre: str
    centre_label: str
    period: str
    as_of: str
    view: str
    depth: int
    parties: list[Related] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    truncation_note: str = ""
    #: The centre's own exposure. Held separately because it is not one of
    #: the RELATED parties, and because a group total that silently omitted
    #: the borrower the screen is about would be wrong in the one direction
    #: nobody would think to check.
    centre_exposure: float | None = None

    def by_direction(self, direction: str) -> list[Related]:
        return [p for p in self.parties if p.direction == direction]

    @property
    def group_exposure(self) -> float:
        """Exposure across the centre and every borrower in the network.

        Summed over the borrowers actually FOUND, which is what makes it
        honest: a network truncated at the node cap has a group exposure that
        is a floor rather than a total, and `truncated` says so beside it.
        """
        total = float(self.centre_exposure or 0.0)
        total += sum(p.exposure or 0.0 for p in self.parties if p.is_borrower)
        return round(total, 2)

    def to_dict(self) -> dict[str, Any]:
        groups = []
        for direction in DIRECTIONS:
            found = self.by_direction(direction)
            groups.append({
                "direction": direction,
                "label": DIRECTION_LABELS[direction],
                "question": DIRECTION_QUESTIONS[direction],
                "count": len(found),
                "parties": [p.to_dict() for p in found],
            })
        borrowers = [p for p in self.parties if p.is_borrower]
        counted = len(borrowers) + (1 if self.centre_exposure is not None
                                    else 0)
        return {
            "version": RELATIONSHIPS_VERSION,
            "centre": self.centre,
            "centre_label": self.centre_label,
            "period": self.period,
            "as_of": self.as_of,
            "view": self.view,
            "depth": self.depth,
            "party_count": len(self.parties),
            "groups": groups,
            "edges": list(self.edges),
            "group_exposure": self.group_exposure,
            "centre_exposure": self.centre_exposure,
            "group_borrowers": counted,
            "exposure_is_floor": self.truncated,
            "truncated": self.truncated,
            "truncation_note": self.truncation_note,
        }


# ---------------------------------------------------------------------------
# The classification
# ---------------------------------------------------------------------------


def classify(centre: str, nodes: list[dict[str, Any]],
             edges: list[dict[str, Any]], *, depth: int) -> list[Related]:
    """Group every party in a neighbourhood by how it stands to the centre.

    Pure: it takes the nodes and edges an ego graph already returned and adds
    the reading. Nothing is loaded here, which is what makes the direction
    rules testable against a hand-built five-node group rather than only
    against whatever the generator happened to produce.
    """
    known = {str(n.get("node_id")): n for n in nodes}
    out_of: dict[str, list[dict[str, Any]]] = {}
    into: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source, target = str(edge.get("from_node")), str(edge.get("to_node"))
        out_of.setdefault(source, []).append(edge)
        into.setdefault(target, []).append(edge)

    # Up first, then down, then whatever is left. The order is the priority:
    # a party that is BOTH a parent and a sister — which happens in a
    # cross-holding — is a parent, because that is the relationship a credit
    # officer must not miss.
    found: dict[str, Related] = {}
    _walk(centre, into, out_of, known, found, direction=UPSTREAM,
          follow_in=True, limit=depth)
    _walk(centre, into, out_of, known, found, direction=DOWNSTREAM,
          follow_in=False, limit=depth)
    _lateral(centre, into, out_of, known, found, limit=depth)
    return sorted(found.values(),
                  key=lambda p: (DIRECTIONS.index(p.direction), p.depth,
                                 -(p.ownership_pct or 0.0), p.node_id))


def _walk(centre: str, into: dict[str, list[dict[str, Any]]],
          out_of: dict[str, list[dict[str, Any]]],
          known: dict[str, dict[str, Any]], found: dict[str, Related], *,
          direction: str, follow_in: bool, limit: int) -> None:
    """Breadth-first in ONE direction, so the reading cannot invert."""
    index = into if follow_in else out_of
    queue: deque[tuple[str, int, list[str]]] = deque([(centre, 0, [centre])])
    seen = {centre}
    while queue:
        node, step, path = queue.popleft()
        if step >= limit:
            continue
        for edge in index.get(node, ()):
            other = str(edge.get("from_node") if follow_in
                        else edge.get("to_node"))
            if other in seen or other == centre:
                continue
            seen.add(other)
            if other not in found:
                found[other] = _party(other, edge, known,
                                      direction=direction, depth=step + 1,
                                      follow_in=follow_in,
                                      via=[*path, other])
            queue.append((other, step + 1, [*path, other]))


def _lateral(centre: str, into: dict[str, list[dict[str, Any]]],
             out_of: dict[str, list[dict[str, Any]]],
             known: dict[str, dict[str, Any]], found: dict[str, Related], *,
             limit: int) -> None:
    """Everything reachable only by a path that changes direction.

    Up to a parent and back down to a sibling. Reached in exactly two steps
    from the centre's own parents, because a sister three parents removed is
    a common-owner entity rather than a sister and the depth already says so.
    """
    if limit < 2:
        return
    parents = [str(edge.get("from_node")) for edge in into.get(centre, ())]
    for parent in parents:
        for edge in out_of.get(parent, ()):
            sibling = str(edge.get("to_node"))
            if sibling == centre or sibling in found:
                continue
            found[sibling] = _party(
                sibling, edge, known, direction=LATERAL, depth=2,
                follow_in=False, via=[centre, parent, sibling],
                relationship=_sibling_words(edge, known.get(parent)))


def _sibling_words(edge: dict[str, Any],
                   parent: dict[str, Any] | None) -> str:
    """What a lateral party is, said with the shared owner named.

    "Sister company" on its own is an assertion. Naming the owner it is
    shared with makes it a statement somebody can check, and the ownership
    percentage on the sibling's own edge says how much of that sister the
    shared owner actually holds.
    """
    whose = (parent or {}).get("label") or (parent or {}).get("node_id") or ""
    held = _number(edge.get("ownership_pct"))
    stake = f", {held:.1f}% held" if held is not None else ""
    return (f"Sister company — same owner ({whose}){stake}" if whose
            else f"Under a common owner{stake}")


def _party(node_id: str, edge: dict[str, Any],
           known: dict[str, dict[str, Any]], *, direction: str, depth: int,
           follow_in: bool, via: list[str],
           relationship: str = "") -> Related:
    node = known.get(node_id) or {}
    edge_type = str(edge.get("edge_type") or "")
    looking_up, looking_down = _MEANING.get(edge_type, ("Related", "Related"))
    return Related(
        node_id=node_id,
        label=str(node.get("label") or node_id),
        node_type=str(node.get("node_type") or "UNKNOWN"),
        detail=str(node.get("detail") or ""),
        direction=direction,
        depth=depth,
        relationship=relationship or (looking_up if follow_in
                                      else looking_down),
        edge_type=edge_type,
        ownership_pct=_number(edge.get("ownership_pct")),
        voting_pct=_number(edge.get("voting_pct")),
        amount=_number(edge.get("amount"))
        or _number(edge.get("guaranteed_amount")),
        instrument=str(edge.get("instrument") or ""),
        source=str(edge.get("source") or ""),
        confidence=_number(edge.get("confidence")),
        via=list(via),
    )


# ---------------------------------------------------------------------------
# Exposure across the group
# ---------------------------------------------------------------------------


def exposure_of(borrower_id: str, snapshot: pd.DataFrame,
                period: str) -> float | None:
    """One borrower's exposure at default, or None when it is not on the book."""
    owed = _owed(snapshot, period)
    return owed.get(borrower_id)


def _owed(snapshot: pd.DataFrame, period: str) -> dict[str, float]:
    if snapshot.empty or "borrower_id" not in snapshot.columns:
        return {}
    block = snapshot[snapshot["period"] == period]
    if block.empty:
        return {}
    column = ("exposure_at_default" if "exposure_at_default" in block.columns
              else "ead" if "ead" in block.columns else "")
    if not column:
        return {}
    out: dict[str, float] = {}
    for borrower, value in zip(block["borrower_id"].astype(str),
                               block[column], strict=True):
        amount = _number(value)
        if amount is not None:
            out[borrower] = amount
    return out


def attach_exposure(parties: list[Related], snapshot: pd.DataFrame,
                    period: str) -> list[Related]:
    """Mark which parties are borrowers on this book, and what they owe.

    A network node is not necessarily a borrower: a holding company, a
    registered address and a natural person are all nodes, and none of them
    has an exposure. Marking them rather than defaulting them to zero is the
    difference between "this party owes nothing" and "this party is not a
    borrower", which are different facts.
    """
    if snapshot.empty or "borrower_id" not in snapshot.columns:
        return parties
    block = snapshot[snapshot["period"] == period]
    if block.empty:
        return parties
    owed = _owed(snapshot, period)
    known = set(block["borrower_id"].astype(str))
    for party in parties:
        if party.node_id in known:
            party.is_borrower = True
            party.exposure = owed.get(party.node_id)
    return parties


__all__ = ["CONTROL_THRESHOLD", "DIRECTIONS", "DIRECTION_LABELS",
           "DIRECTION_QUESTIONS", "DOWNSTREAM", "LATERAL",
           "RELATIONSHIPS_VERSION", "Related", "Network",
           "SIGNIFICANT_THRESHOLD", "UPSTREAM", "attach_exposure", "classify",
           "exposure_of"]
