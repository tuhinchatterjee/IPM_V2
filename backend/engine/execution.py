"""
Execution context and the governed reader — how an analysis reaches data, and
how the Trace gets built while it does.

The rule from docs/PRODUCT_SPEC.md §4.3:

    Trace is emitted by execution. It is never written afterwards.

So an engine function does not read Parquet and later describe what it read. It
calls `ctx.read(...)`, and that call *is* what creates the DATASET, VARIABLE and
FILTER nodes, stamped with the real row counts. The graph cannot drift from what
actually happened, because producing the graph and doing the work are the same
act.

Engine functions receive one `ExecutionContext` and use three things on it:

    ctx.params          validated parameters (the contract already checked them)
    ctx.read(...)       governed data, recorded in the Trace
    ctx.step(...)       record an aggregation or calculation step
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.data_access import get_data_source
from backend.data_access.context import AnalysisContext
from backend.trace.model import NodeType, TraceGraph, TraceNode

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 5


@dataclass
class ExecutionContext:
    """Everything one analysis needs, plus the trace it is writing as it goes."""

    context: AnalysisContext
    params: dict[str, Any]
    graph: TraceGraph
    analysis_id: str
    analysis_version: str
    # Node the next recorded step should hang off. Updated as the analysis walks
    # forward, so the graph's shape follows the real order of work.
    cursor: str = "request"
    source: Any = None
    _counter: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source is None:
            self.source = get_data_source()

    # ------------------------------------------------------------------ ids

    def _next_id(self, prefix: str) -> str:
        self._counter[prefix] = self._counter.get(prefix, 0) + 1
        return f"{prefix}_{self._counter[prefix]}"

    # --------------------------------------------------------------- tracing

    def _add(self, node: TraceNode, parents: list[str]) -> str:
        self.graph.add_node(node)
        for parent in parents:
            if parent in self.graph.nodes:
                self.graph.connect(parent, node.id)
        return node.id

    def step(self, node_type: NodeType, label: str, *, parents: list[str] | None = None,
             config: dict | None = None, rows_in: int | None = None,
             rows_out: int | None = None, preview: pd.DataFrame | None = None,
             summary: dict | None = None, advance: bool = True) -> str:
        """Record one step of work and (by default) move the cursor onto it."""
        node = TraceNode(
            id=self._next_id(node_type.value.lower()),
            type=node_type,
            label=label,
            config=config or {},
            rows_in=rows_in,
            rows_out=rows_out,
            output_summary=summary or {},
        )
        node.mark_started()
        if preview is not None and not preview.empty:
            from backend.engine.helpers import frame_to_rows

            node.output_preview = frame_to_rows(preview.head(PREVIEW_ROWS))
        node.mark_ok(rows_out=rows_out)
        node_id = self._add(node, parents if parents is not None else [self.cursor])
        if advance:
            self.cursor = node_id
        return node_id

    def warn(self, message: str) -> None:
        """Record a non-fatal observation. Surfaces on the result and the trace."""
        self.warnings.append(message)
        logger.info("[%s] %s", self.analysis_id, message)

    # ------------------------------------------------------------- data read

    def read(self, dataset: str, *, fields: list[str], period: str | None = None,
             label: str | None = None, parents: list[str] | None = None) -> tuple[pd.DataFrame, str]:
        """Read a governed dataset, recording the read in the Trace.

        Creates three nodes — the dataset, the variables taken from it, and the
        filters applied — and returns the data plus the id of the last node, so a
        branch reading a second dataset can be joined back explicitly.

        This is the only way an engine function obtains data. It never sees a file
        path and never writes SQL.
        """
        effective_period = period or self.context.period
        anchor = parents if parents is not None else [self.cursor]

        dataset_node = self._add(
            _completed_node(
                node_id=self._next_id("dataset"),
                node_type=NodeType.DATASET,
                label=label or f"{dataset} · {effective_period}",
                config={"dataset": dataset, "period": effective_period},
                dataset=dataset,
                fields_used=list(fields),
                dataset_version=self.context.dataset_version,
            ),
            anchor,
        )

        variable_node = self._add(
            _completed_node(
                node_id=self._next_id("variable"),
                node_type=NodeType.VARIABLE,
                label=f"{len(fields)} governed variables",
                config={"fields": list(fields), "definitions": self._definitions(dataset, fields)},
                dataset=dataset,
                fields_used=list(fields),
            ),
            [dataset_node],
        )

        frame = self.source.fetch(dataset, context=self.context, fields=fields,
                                  period=effective_period)
        rows_before = int(len(frame))
        # Row counts are evidence, recorded after the read rather than guessed
        # before it.
        self.graph.nodes[dataset_node].rows_out = rows_before
        self.graph.nodes[variable_node].rows_out = rows_before

        active = self.context.active_filters
        filter_node = self._add(
            _completed_node(
                node_id=self._next_id("filter"),
                node_type=NodeType.FILTER,
                label=(
                    ", ".join(f"{k}={v}" for k, v in active.items())
                    if active else "No filters applied"
                ),
                config={"filters": active, "period": effective_period},
                dataset=dataset,
                rows_out=rows_before,
            ),
            [variable_node],
        )
        # The filter node reports rows after filtering; the DAL applies filters in
        # the query, so the count that comes back is already the filtered count.
        self.graph.nodes[filter_node].rows_out = rows_before

        if rows_before == 0:
            self.warn(
                f"No rows in '{dataset}' for {effective_period}"
                + (f" with filters {active}" if active else "")
            )

        self.cursor = filter_node
        return frame, filter_node

    def _definitions(self, dataset: str, fields: list[str]) -> dict[str, str]:
        """Business definitions for the variables read, so a Trace node can be
        inspected without leaving the graph."""
        try:
            from backend.data_access import get_catalog

            spec = get_catalog().dataset(dataset)
            return {f: spec.fields[f].definition for f in fields if f in spec.fields}
        except Exception:  # pragma: no cover - the trace must never break the run
            return {}


def _completed_node(*, node_id: str, node_type: NodeType, label: str, config: dict,
                    dataset: str | None = None, fields_used: list[str] | None = None,
                    dataset_version: int | None = None, rows_out: int | None = None) -> TraceNode:
    node = TraceNode(
        id=node_id, type=node_type, label=label, config=config,
        dataset=dataset, fields_used=fields_used or [], dataset_version=dataset_version,
    )
    node.mark_started()
    node.mark_ok(rows_out=rows_out)
    return node
