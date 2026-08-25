"""
The Trace graph — how an analysis was actually created.

The design rule (docs/PRODUCT_SPEC.md §4.3):

    Trace is emitted by execution. It is never written afterwards, and it is
    never written by the LLM.

If the model describes what it did, that is a story. If each step stamps its own
card as it runs — which data, which filter, how many rows before and after, which
function, which version, how long it took — that is evidence. The graph IS the
execution record, so it cannot drift from the truth.

Content hashing
---------------
Every node carries a hash derived from its type, its configuration, and the
hashes of the nodes feeding into it. Two consequences, both essential:

  * Change one filter and only the nodes downstream of it get a new hash. Those
    are exactly the nodes that must re-run; everything else reuses its recorded
    result. That is what makes "use EAD rather than borrower count" take a second
    instead of a minute.
  * The UI can highlight precisely which nodes a modification affected, because
    "affected" is a computed fact rather than a guess.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class NodeType(StrEnum):
    """The kinds of step an analysis is made of.

    The split between *governed* and *interpretive* nodes matters more than the
    list itself: a reader must be able to see at a glance where the AI's judgement
    ends and the deterministic engine begins.
    """

    USER_PROMPT = "USER_PROMPT"
    LLM_INTENT = "LLM_INTENT"
    PLAN = "PLAN"
    DATA_DOMAIN = "DATA_DOMAIN"
    DATASET_FAMILY = "DATASET_FAMILY"
    DATASET = "DATASET"
    VARIABLE = "VARIABLE"
    FILTER = "FILTER"
    JOIN = "JOIN"
    #: How the population changed at each step of a composed multi-dataset
    #: analysis. Governed, because every figure on it was counted rather than
    #: asserted.
    RECONCILIATION = "RECONCILIATION"
    DERIVED_VARIABLE = "DERIVED_VARIABLE"
    TRANSFORMATION = "TRANSFORMATION"
    AGGREGATION = "AGGREGATION"
    WINDOW = "WINDOW"
    ENGINE_FUNCTION = "ENGINE_FUNCTION"
    CERTIFIED_METHOD = "CERTIFIED_METHOD"
    #: The compiled statement actually sent to DuckDB, with its parameters kept
    #: separate — the separation IS the safety property, so the Trace shows it.
    SQL_QUERY = "SQL_QUERY"
    #: An allowlisted numerical operation run on the query's result.
    KERNEL = "KERNEL"
    CALCULATION = "CALCULATION"
    RESULT = "RESULT"
    LLM_EXPLANATION = "LLM_EXPLANATION"
    VISUALIZATION = "VISUALIZATION"


# Nodes whose output is a number the bank must be able to defend. These are drawn
# differently in the UI from the interpretive ones.
GOVERNED_NODE_TYPES = frozenset(
    {
        NodeType.DATA_DOMAIN,
        NodeType.DATASET_FAMILY,
        NodeType.DATASET,
        NodeType.VARIABLE,
        NodeType.FILTER,
        NodeType.JOIN,
        NodeType.RECONCILIATION,
        NodeType.DERIVED_VARIABLE,
        NodeType.TRANSFORMATION,
        NodeType.AGGREGATION,
        NodeType.WINDOW,
        NodeType.ENGINE_FUNCTION,
        NodeType.CERTIFIED_METHOD,
        NodeType.SQL_QUERY,
        NodeType.KERNEL,
        NodeType.CALCULATION,
        NodeType.RESULT,
    }
)

# Nodes produced by the language model. Never carry arithmetic.
INTERPRETIVE_NODE_TYPES = frozenset(
    {NodeType.USER_PROMPT, NodeType.LLM_INTENT, NodeType.PLAN, NodeType.LLM_EXPLANATION}
)


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"  # unchanged on a re-run; the recorded result was reused
    CACHED = "cached"


def _stable_json(payload: Any) -> str:
    """Deterministic JSON so the same configuration always hashes the same way.

    Sorted keys and a fixed separator matter: without them, two identical
    configurations built in a different order would hash differently and the
    selective re-execution would re-run work it did not need to.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class TraceNode:
    """One step in the analysis."""

    id: str
    type: NodeType
    label: str  # short, human-readable — what the box says on the graph

    # What this step was configured to do. For an ENGINE_FUNCTION node that is the
    # function id, version and parameters; for a FILTER node the field and value.
    config: dict[str, Any] = field(default_factory=dict)

    # Evidence recorded during execution — never configured in advance.
    status: NodeStatus = NodeStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    rows_in: int | None = None
    rows_out: int | None = None
    output_preview: list[dict[str, Any]] | None = None  # first few rows, for inspection
    output_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    # Provenance for governed nodes.
    dataset: str | None = None
    fields_used: list[str] = field(default_factory=list)
    function_id: str | None = None
    function_version: str | None = None
    dataset_version: int | None = None

    # Set by TraceGraph.compute_hashes(); do not set by hand.
    content_hash: str | None = None

    @property
    def is_governed(self) -> bool:
        return self.type in GOVERNED_NODE_TYPES

    @property
    def is_interpretive(self) -> bool:
        return self.type in INTERPRETIVE_NODE_TYPES

    def hash_payload(self) -> dict[str, Any]:
        """Only what genuinely determines the output.

        Timings, row counts and status are deliberately excluded: they are the
        *result* of running, not an input to it. Including them would make every
        re-run produce a different hash and defeat selective re-execution.
        """
        return {
            "type": self.type.value,
            "config": self.config,
            "dataset": self.dataset,
            "fields_used": sorted(self.fields_used),
            "function_id": self.function_id,
            "function_version": self.function_version,
            "dataset_version": self.dataset_version,
        }

    def mark_started(self) -> None:
        self.status = NodeStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def mark_ok(self, *, rows_out: int | None = None) -> None:
        self.status = NodeStatus.OK
        self.finished_at = datetime.now(UTC)
        if self.started_at:
            self.duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
        if rows_out is not None:
            self.rows_out = rows_out

    def mark_failed(self, error: str) -> None:
        self.status = NodeStatus.FAILED
        self.error = error
        self.finished_at = datetime.now(UTC)
        if self.started_at:
            self.duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "config": self.config,
            "status": self.status.value,
            "is_governed": self.is_governed,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "output_preview": self.output_preview,
            "output_summary": self.output_summary,
            "warnings": self.warnings,
            "error": self.error,
            "dataset": self.dataset,
            "fields_used": self.fields_used,
            "function_id": self.function_id,
            "function_version": self.function_version,
            "dataset_version": self.dataset_version,
            "content_hash": self.content_hash,
        }


@dataclass
class TraceEdge:
    """A directed dependency: `source` feeds `target`."""

    source: str
    target: str
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "label": self.label}


class TraceGraphError(RuntimeError):
    pass


@dataclass
class TraceGraph:
    """The nodes and edges of one analysis."""

    nodes: dict[str, TraceNode] = field(default_factory=dict)
    edges: list[TraceEdge] = field(default_factory=list)

    def add_node(self, node: TraceNode) -> TraceNode:
        if node.id in self.nodes:
            raise TraceGraphError(f"Duplicate trace node id: {node.id}")
        self.nodes[node.id] = node
        return node

    def connect(self, source: str, target: str, label: str | None = None) -> None:
        for n in (source, target):
            if n not in self.nodes:
                raise TraceGraphError(f"Cannot connect unknown node: {n}")
        self.edges.append(TraceEdge(source=source, target=target, label=label))

    def parents(self, node_id: str) -> list[str]:
        return [e.source for e in self.edges if e.target == node_id]

    def children(self, node_id: str) -> list[str]:
        return [e.target for e in self.edges if e.source == node_id]

    def roots(self) -> list[str]:
        targets = {e.target for e in self.edges}
        return [n for n in self.nodes if n not in targets]

    def leaves(self) -> list[str]:
        sources = {e.source for e in self.edges}
        return [n for n in self.nodes if n not in sources]

    # -------------------------------------------------------------- ordering

    def topological_order(self) -> list[str]:
        """Nodes in dependency order — every node after everything it depends on.

        Raises if the graph contains a cycle. An analysis that depends on its own
        output is not an analysis, and catching it here is far cheaper than
        discovering it as an infinite loop during a demo.
        """
        indegree = {n: 0 for n in self.nodes}
        for e in self.edges:
            indegree[e.target] += 1
        # Sorted for determinism: the same graph must always lay out the same way.
        queue = sorted([n for n, d in indegree.items() if d == 0])
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for child in sorted(self.children(current)):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
                    queue.sort()
        if len(order) != len(self.nodes):
            unresolved = sorted(set(self.nodes) - set(order))
            raise TraceGraphError(f"Trace graph contains a cycle involving: {', '.join(unresolved)}")
        return order

    def layers(self) -> list[list[str]]:
        """Nodes grouped into dependency layers — the basis of the graph layout.

        A deterministic layered layout is what stops the Trace view from looking
        like a different diagram every time it is opened.
        """
        depth: dict[str, int] = {}
        for node_id in self.topological_order():
            parents = self.parents(node_id)
            depth[node_id] = (max(depth[p] for p in parents) + 1) if parents else 0
        out: list[list[str]] = []
        for node_id, d in sorted(depth.items(), key=lambda kv: (kv[1], kv[0])):
            while len(out) <= d:
                out.append([])
            out[d].append(node_id)
        return out

    # --------------------------------------------------------------- hashing

    def compute_hashes(self) -> dict[str, str]:
        """Assign every node a content hash derived from its own configuration and
        its parents' hashes. Returns {node_id: hash}."""
        for node_id in self.topological_order():
            node = self.nodes[node_id]
            parent_hashes = sorted(
                self.nodes[p].content_hash or "" for p in self.parents(node_id)
            )
            payload = _stable_json({"self": node.hash_payload(), "parents": parent_hashes})
            node.content_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return {n: self.nodes[n].content_hash or "" for n in self.nodes}

    def descendants(self, node_id: str) -> set[str]:
        """Everything downstream of a node — what a change to it invalidates."""
        seen: set[str] = set()
        stack = list(self.children(node_id))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.children(current))
        return seen

    def affected_by(self, changed_node_ids: list[str]) -> set[str]:
        """The full set that must re-run when the given nodes change: the nodes
        themselves plus everything downstream of them."""
        affected: set[str] = set(changed_node_ids)
        for n in changed_node_ids:
            affected |= self.descendants(n)
        return affected

    def diff_hashes(self, previous: dict[str, str]) -> dict[str, list[str]]:
        """Compare against a previous hash map — drives the "what changed" preview
        the user sees before accepting a Trace modification."""
        current = {n: (node.content_hash or "") for n, node in self.nodes.items()}
        return {
            "added": sorted(set(current) - set(previous)),
            "removed": sorted(set(previous) - set(current)),
            "changed": sorted(
                n for n in set(current) & set(previous) if current[n] != previous[n]
            ),
            "unchanged": sorted(
                n for n in set(current) & set(previous) if current[n] == previous[n]
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [self.nodes[n].to_dict() for n in self.topological_order()],
            "edges": [e.to_dict() for e in self.edges],
            "layers": self.layers(),
            "stats": {
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "governed_nodes": sum(1 for n in self.nodes.values() if n.is_governed),
                "interpretive_nodes": sum(1 for n in self.nodes.values() if n.is_interpretive),
            },
        }
