"""
Trace — how a particular analysis was created.

Not an audit log. An audit log records *that* something happened; Trace shows
*how* a result was produced, as an inspectable, editable graph.

  model.py   TraceGraph / TraceNode / TraceEdge, content hashing, layout layers

Phase 3 adds the recorder (execution -> graph) and Phase 4 the modification
engine (a plain-English change -> a new version, re-running only what the change
actually affected).
"""

from backend.trace.model import (
    GOVERNED_NODE_TYPES,
    INTERPRETIVE_NODE_TYPES,
    NodeStatus,
    NodeType,
    TraceEdge,
    TraceGraph,
    TraceGraphError,
    TraceNode,
)

__all__ = [
    "GOVERNED_NODE_TYPES",
    "INTERPRETIVE_NODE_TYPES",
    "NodeStatus",
    "NodeType",
    "TraceEdge",
    "TraceGraph",
    "TraceGraphError",
    "TraceNode",
]
