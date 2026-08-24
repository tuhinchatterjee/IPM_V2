"""
The analysis runner — the one way an analysis is executed.

Everything goes through `run_analysis()`: the API, and later the LLM planner.
It is the single choke point where the governance rules are applied, in order:

  1. The analysis must be REGISTERED. An unknown id is refused.
  2. It must be RUNNABLE (certified or user-defined; never draft or deprecated).
  3. Its parameters must satisfy the declared contract.
  4. Its required datasets must be PUBLISHED and readable.
  5. Only then does any data get read or any number get computed.

While it runs, the executor emits the Trace. The graph is not a description
written afterwards — it is the record each step stamps as it happens.

Nothing here accepts Python, SQL, or a file path from a caller. The only inputs
are a registered analysis id and parameters the contract accepts, which is what
makes the same entry point safe for an LLM to drive in Phase 3.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.data_access import get_catalog, get_data_source
from backend.data_access.context import AnalysisContext
from backend.data_access.protocol import DataAccessError
from backend.engine.contracts import ContractError
from backend.engine.execution import ExecutionContext
from backend.engine.registry import AnalysisResult, get_registry
from backend.trace.model import NodeStatus, NodeType, TraceGraph, TraceNode

logger = logging.getLogger(__name__)


class DatasetNotPublishedError(RuntimeError):
    """An analysis needs a dataset that is not available through the governed layer."""


@dataclass
class AnalysisRunResult:
    """One execution: what was asked, what came back, and how it was produced."""

    analysis_id: str
    analysis_version: str
    certification: str
    status: str  # succeeded | failed
    params: dict[str, Any]
    context: dict[str, Any]
    result: AnalysisResult | None
    graph: TraceGraph
    duration_ms: int
    error: str | None = None
    node_hashes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "analysis_version": self.analysis_version,
            "certification": self.certification,
            "status": self.status,
            "params": self.params,
            "context": self.context,
            "result": self.result.to_dict() if self.result else None,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "trace": self.graph.to_dict(),
            "node_hashes": self.node_hashes,
        }


def _require_published(datasets: list[str]) -> None:
    """Refuse to run against a dataset the governed layer does not serve.

    The catalogue contains only bundled datasets and ones a steward has
    PUBLISHED through Data Builder, so this is what stops a draft or
    half-mapped dataset from ever reaching an analysis.
    """
    catalog = get_catalog()
    available = set(catalog.names())
    missing = [d for d in datasets if d not in available]
    if missing:
        raise DatasetNotPublishedError(
            f"Analysis requires dataset(s) not available in the governed layer: "
            f"{', '.join(missing)}. Published datasets: {', '.join(sorted(available)) or '(none)'}. "
            "Publish the dataset in Data Builder first."
        )
    source = get_data_source()
    on_disk = set(source.datasets())
    not_readable = [d for d in datasets if d not in on_disk]
    if not_readable:
        raise DatasetNotPublishedError(
            f"Dataset(s) {', '.join(not_readable)} are in the catalogue but have no data on "
            "disk. Re-publish them in Data Builder."
        )


def run_analysis(
    analysis_id: str,
    *,
    params: dict[str, Any] | None = None,
    period: str | None = None,
    filters: dict[str, Any] | None = None,
    user_id: int | None = None,
    request_id: str | None = None,
    dataset_version: int | None = None,
) -> AnalysisRunResult:
    """Execute one registered analysis and return the result with its Trace."""
    started = time.perf_counter()
    registry = get_registry()

    # (1) and (2): registered, and allowed to run.
    registered = registry.require_runnable(analysis_id)
    contract = registered.contract

    # (3): parameters must satisfy the declared contract.
    resolved_params = contract.validate_params(params or {})

    # (4): the datasets must be governed and readable.
    _require_published(contract.required_datasets)

    context = AnalysisContext(
        period=period or "latest",
        filters=dict(filters or {}),
        dataset_version=dataset_version,
        user_id=user_id,
        request_id=request_id,
    )

    graph = TraceGraph()
    request_node = TraceNode(
        id="request",
        type=NodeType.PLAN,
        label=f"Analysis request · {contract.name}",
        config={
            "analysis_id": analysis_id,
            "analysis_version": contract.version,
            "certification": contract.certification.value,
            "parameters": resolved_params,
            "filters": context.active_filters,
            "requested_period": period or "latest",
            "required_datasets": contract.required_datasets,
        },
        function_id=analysis_id,
        function_version=contract.version,
    )
    request_node.mark_started()
    request_node.mark_ok()
    graph.add_node(request_node)

    exec_ctx = ExecutionContext(
        context=context,
        params=resolved_params,
        graph=graph,
        analysis_id=analysis_id,
        analysis_version=contract.version,
        cursor="request",
    )

    status = "succeeded"
    error: str | None = None
    result: AnalysisResult | None = None

    try:
        # (5): only now is any data read or any number computed.
        result = registered.fn(exec_ctx)

        function_node = TraceNode(
            id="engine_function",
            type=NodeType.ENGINE_FUNCTION,
            label=f"{contract.name} v{contract.version}",
            config={
                "analysis_id": analysis_id,
                "certification": contract.certification.value,
                "calculation_description": contract.calculation_description,
                "validation_rules": [r.to_dict() for r in contract.validation_rules],
                "weighting": result.meta.get("weighting", ""),
                "grain": result.meta.get("grain", ""),
            },
            function_id=analysis_id,
            function_version=contract.version,
        )
        function_node.mark_started()
        function_node.mark_ok(rows_out=len(result.rows))
        graph.add_node(function_node)
        graph.connect(exec_ctx.cursor, "engine_function")

        result_node = TraceNode(
            id="result",
            type=NodeType.RESULT,
            label=f"{len(result.rows)} rows · {len(result.values)} measures",
            config={
                "outputs": [o.to_dict() for o in contract.outputs],
                "units": result.units,
                "supported_visualizations": [v.value for v in contract.supported_visualizations],
            },
            output_preview=result.rows[:5],
            output_summary={k: v for k, v in result.values.items()
                            if isinstance(v, (int, float, str, bool)) or v is None},
            warnings=result.warnings,
        )
        result_node.mark_started()
        result_node.mark_ok(rows_out=len(result.rows))
        graph.add_node(result_node)
        graph.connect("engine_function", "result")

    except (ContractError, DataAccessError, DatasetNotPublishedError, ValueError) as e:
        status, error = "failed", str(e)
        _record_failure(graph, exec_ctx.cursor, error)
        logger.warning("Analysis %s failed: %s", analysis_id, e)
    except Exception as e:  # pragma: no cover - defensive
        status, error = "failed", f"{type(e).__name__}: {e}"
        _record_failure(graph, exec_ctx.cursor, error)
        logger.exception("Analysis %s raised", analysis_id)

    node_hashes = graph.compute_hashes()
    duration_ms = int((time.perf_counter() - started) * 1000)

    return AnalysisRunResult(
        analysis_id=analysis_id,
        analysis_version=contract.version,
        certification=contract.certification.value,
        status=status,
        params=resolved_params,
        context=context.describe(),
        result=result,
        graph=graph,
        duration_ms=duration_ms,
        error=error,
        node_hashes=node_hashes,
    )


def _record_failure(graph: TraceGraph, parent: str, message: str) -> None:
    """A failed run still produces a Trace. Where it stopped is exactly the
    information someone needs, so the graph records the failure rather than
    being discarded."""
    node = TraceNode(id="failure", type=NodeType.RESULT, label="Analysis failed")
    node.mark_started()
    node.mark_failed(message)
    node.status = NodeStatus.FAILED
    graph.add_node(node)
    if parent in graph.nodes:
        graph.connect(parent, "failure")


# ------------------------------------------------------------------ persistence


def persist_run(run: AnalysisRunResult, *, project_id: int | None = None,
                investigation_id: int | None = None, user_id: int | None = None,
                question: str = "") -> int | None:
    """Store the run and its Trace, returning the analysis run id.

    The stored shape is deliberately the same one an Ask CreditProbe investigation uses —
    a plan with one step, and that step's executed result. A single analysis run
    is a one-step investigation, so storing it that way means the Trace viewer and
    the modification path work on it without a second code path.

    Persistence is best-effort: a database problem must not lose an analysis the
    user is already looking at. The result is returned either way; only the
    stored history is affected.
    """
    from backend.config import settings

    if not settings.has_database:
        return None
    try:
        from backend.db.engine import get_session
        from backend.models.platform import AnalysisRun, TraceVersionRow

        graph = run.graph.to_dict()
        # The Trace viewer groups nodes by the plan step they belong to; a
        # one-step run stamps every node with step 1.
        for node in graph.get("nodes", []):
            node.setdefault("config", {})
            node["config"] = {**node["config"], "_step": 1, "_step_title": run.analysis_id}

        contract_name = run.analysis_id
        try:
            contract_name = get_registry().contract(run.analysis_id).name
        except Exception:  # pragma: no cover - registry is always loaded by here
            pass

        step = {
            "index": 0,
            "analysis_id": run.analysis_id,
            "title": contract_name,
            "rationale": "Run directly from the Analysis Library.",
            "params": run.params,
            "filters": run.context.get("filters") or {},
            "period": run.context.get("period"),
            "status": run.status,
            "certification": run.certification,
            "analysis_version": run.analysis_version,
            "duration_ms": run.duration_ms,
            "result": run.result.to_dict() if run.result else None,
            "error": run.error,
            "trace": graph,
            "node_hashes": run.node_hashes,
            "reused": False,
        }
        plan = {
            "question": question,
            "intent": f"Run {contract_name} directly.",
            "steps": [{"analysis_id": run.analysis_id, "title": contract_name,
                       "rationale": step["rationale"], "params": run.params,
                       "filters": step["filters"], "period": step["period"]}],
            "planner": "direct",
            "follow_ups": [],
        }

        with get_session() as session:
            record = AnalysisRun(
                project_id=project_id,
                investigation_id=investigation_id,
                user_id=user_id,
                question=question,
                intent={"analysis_id": run.analysis_id, "source": "direct"},
                plan=plan,
                context=run.context,
                status="succeeded" if run.status == "succeeded" else "failed",
                rejection_reason=run.error,
                result={"steps": [step]},
                function_versions={run.analysis_id: run.analysis_version},
                dataset_version=run.context.get("dataset_version"),
                duration_ms=run.duration_ms,
            )
            session.add(record)
            session.flush()

            session.add(TraceVersionRow(
                analysis_run_id=record.id,
                version_number=1,
                label="Original",
                graph=graph,
                node_hashes=run.node_hashes,
                result={"steps": [step], "plan": plan, "narrative": {}},
                created_by=user_id,
            ))
            return record.id
    except Exception as e:
        logger.warning("Could not persist analysis run %s: %s", run.analysis_id, e)
        return None


def load_trace(analysis_run_id: int, version: int | None = None) -> dict[str, Any] | None:
    """Retrieve a stored Trace graph for an analysis run."""
    from backend.config import settings

    if not settings.has_database:
        return None
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import AnalysisRun, TraceVersionRow

    with get_session() as session:
        run = session.get(AnalysisRun, analysis_run_id)
        if run is None:
            return None
        stmt = select(TraceVersionRow).where(TraceVersionRow.analysis_run_id == analysis_run_id)
        stmt = (
            stmt.where(TraceVersionRow.version_number == version)
            if version
            else stmt.order_by(TraceVersionRow.version_number.desc())
        )
        trace = session.execute(stmt).scalars().first()
        if trace is None:
            return None
        versions = session.execute(
            select(TraceVersionRow.version_number, TraceVersionRow.label)
            .where(TraceVersionRow.analysis_run_id == analysis_run_id)
            .order_by(TraceVersionRow.version_number)
        ).all()
        return {
            "analysis_run_id": analysis_run_id,
            "analysis_id": (run.intent or {}).get("analysis_id"),
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "duration_ms": run.duration_ms,
            "context": run.context,
            "version": trace.version_number,
            "label": trace.label,
            "graph": trace.graph,
            "node_hashes": trace.node_hashes,
            "available_versions": [{"version": v, "label": lbl} for v, lbl in versions],
        }
