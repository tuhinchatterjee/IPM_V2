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


def _short(value: Any) -> str:
    """A filter value as it should read on a node label.

    An exclusion becomes a list of every other sector; printing all eleven
    would make the box unreadable, so the count is shown instead.
    """
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return ", ".join(str(v) for v in items) if len(items) <= 2 else f"{len(items)} values"
    return str(value)


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
    # Domain name -> trace node id, so one domain is drawn once per analysis.
    _domains: dict[str, str] = field(default_factory=dict)
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
        """Read a governed dataset, recording the whole lineage in the Trace.

        Creates four nodes — the data domain, the dataset (with its family,
        version and reporting period), the governed variables taken from it, and
        the filters applied — and returns the data plus the id of the last node,
        so a branch reading a second dataset can be joined back explicitly.

        Two things happen here that matter for governance.

        **The dataset name is resolved, not obeyed.** An engine function asks for
        `portfolio_facility`. If a client dataset has been published and marked
        authoritative for the same governed purpose, the read goes there instead
        — and the DATASET node records that it was redirected, and why. The
        engine never learns which physical table it read, and a reader of the
        Trace always does.

        **The domain is on the map.** "Where did this number come from?" is
        answered by four boxes in a row, not by reading a log.

        This is the only way an engine function obtains data. It never sees a
        file path and never writes SQL.
        """
        from backend.data_access.authority import resolve_dataset

        effective_period = period or self.context.period
        anchor = parents if parents is not None else [self.cursor]

        resolution = resolve_dataset(dataset)
        actual = resolution.dataset
        spec = self._spec(actual)

        # --- the data domain, created once per domain per analysis ----------
        domain_node = self._domain_node(resolution, anchor)

        # --- the dataset -----------------------------------------------------
        dataset_node = self._add(
            _completed_node(
                node_id=self._next_id("dataset"),
                node_type=NodeType.DATASET,
                label=label or f"{spec.business_name if spec else actual} · {effective_period}",
                config={
                    "dataset": actual,
                    "business_name": spec.business_name if spec else actual,
                    "dataset_family": resolution.dataset_family,
                    "version": resolution.version,
                    "reporting_period": effective_period,
                    "grain": spec.grain if spec else "",
                    "primary_keys": list(spec.primary_keys) if spec else [],
                    "origin": resolution.origin,
                    "is_demo": resolution.is_demo,
                    "published": True,
                    "requested_as": dataset,
                    "redirected": actual != dataset,
                    "selection_reason": resolution.reason,
                },
                dataset=actual,
                fields_used=list(fields),
                dataset_version=self.context.dataset_version,
            ),
            [domain_node],
        )

        # --- the governed variables -----------------------------------------
        variable_node = self._add(
            _completed_node(
                node_id=self._next_id("variable"),
                node_type=NodeType.VARIABLE,
                label=f"{len(fields)} governed variables",
                config={"fields": list(fields), "variables": self._variables(actual, fields)},
                dataset=actual,
                fields_used=list(fields),
            ),
            [dataset_node],
        )

        frame = self.source.fetch(actual, context=self.context, fields=fields,
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
                    ", ".join(f"{k}={_short(v)}" for k, v in active.items())
                    if active else "No filters applied"
                ),
                config={"filters": active, "period": effective_period},
                dataset=actual,
                rows_out=rows_before,
            ),
            [variable_node],
        )
        # The filter node reports rows after filtering; the DAL applies filters in
        # the query, so the count that comes back is already the filtered count.
        self.graph.nodes[filter_node].rows_out = rows_before

        if rows_before == 0:
            self.warn(
                f"No rows in '{actual}' for {effective_period}"
                + (f" with filters {active}" if active else "")
            )

        self.cursor = filter_node
        return frame, filter_node

    def _domain_node(self, resolution: Any, anchor: list[str]) -> str:
        """The DATA DOMAIN node, created once per domain within one analysis.

        Two reads of the same domain hang off one box. Drawing the domain twice
        would suggest two sources where there is one.
        """
        from backend.data_access.catalog import GOVERNED_PURPOSES

        existing = self._domains.get(resolution.domain)
        if existing:
            return existing

        node_id = self._add(
            _completed_node(
                node_id=self._next_id("domain"),
                node_type=NodeType.DATA_DOMAIN,
                label=resolution.domain,
                config={
                    "domain": resolution.domain,
                    "purpose": resolution.purpose,
                    "purpose_description": GOVERNED_PURPOSES.get(resolution.purpose, ""),
                    "authoritative": resolution.authoritative,
                    "origin": resolution.origin,
                    "is_demo": resolution.is_demo,
                    "selection_reason": resolution.reason,
                    "alternatives_not_used": list(resolution.alternatives),
                },
            ),
            anchor,
        )
        self._domains[resolution.domain] = node_id
        return node_id

    def _spec(self, dataset: str) -> Any:
        try:
            from backend.data_access import get_catalog

            return get_catalog().dataset(dataset)
        except Exception:  # pragma: no cover - the trace must never break the run
            return None

    def _variables(self, dataset: str, fields: list[str]) -> list[dict[str, Any]]:
        """Business name, technical field and unit for every variable read.

        A Trace that lists `ecl_coverage_pct` tells a developer something. One
        that lists "ECL Coverage · ecl_coverage_pct · %" tells a credit officer
        the same thing.
        """
        spec = self._spec(dataset)
        if spec is None:
            return [{"field": f} for f in fields]
        out = []
        for f in fields:
            definition = spec.fields.get(f)
            out.append({
                "field": f,
                "business_name": definition.business_name if definition else f,
                "unit": definition.unit if definition else None,
                "data_type": definition.data_type if definition else "",
                "definition": definition.definition if definition else "",
            })
        return out


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
