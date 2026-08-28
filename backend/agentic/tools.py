"""
The Tool Registry: the complete set of things an agent may do.

§14 says agents may use only approved CreditProbe tools, and then lists what
they may never have: arbitrary SQL, arbitrary Python, unrestricted network,
filesystem access outside governed services, database access outside service
contracts. This module is where that becomes enforceable rather than aspirational.

The shape of the guarantee
--------------------------
An agent does not *have* functions. It has a list of tool ids, and every call
goes through `invoke()`, which checks three things in order:

1. Is this a registered tool at all?
2. Is it on this agent's `allowed_tools`?
3. Does the requested scope fall inside the agent's `allowed_data_domains` and
   inside the calling principal's own data permissions?

Only then is the underlying governed service reached. There is no fourth path.
An agent cannot construct a call this module has not defined, because the
executor never hands an agent a callable — it hands it a tool id and a
parameter document.

Why every tool is a thin wrapper
--------------------------------
Each one delegates to a service that already exists and is already tested: the
catalogue, the analysis planner, the runtime executor, the invariant checker,
the workflow service. A tool that reimplemented any of those would be a second
opinion about what a governed calculation is, and the whole product rests on
there being exactly one.

Side effects
------------
`writes` marks a tool that changes something. Every one of them produces a
DRAFT, never a sent, published or approved object — §21's Level 4 actions have
no tool at all, which is the strongest form the prohibition can take: there is
nothing for an agent to call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool ids
# ---------------------------------------------------------------------------

CATALOGUE_LOOKUP = "catalogue_lookup"
FIELD_RESOLUTION = "field_resolution"
RELATIONSHIP_PATH = "relationship_path"
SOURCE_PROFILE = "source_profile"
DATA_QUALITY = "data_quality"
PERIOD_READINESS = "period_readiness"

PLAN_ANALYSIS = "plan_analysis"
RUN_ANALYSIS = "run_analysis"
RUN_CERTIFIED_METHOD = "run_certified_method"
RUN_SCENARIO = "run_scenario"
NUMERICAL_KERNEL = "numerical_kernel"
PREVIOUS_RESULT = "previous_result"
PRE_SCREEN = "pre_screen"

VALIDATE_INVARIANTS = "validate_invariants"
RECONCILE = "reconcile"
GROUNDING_CHECK = "grounding_check"
EVIDENCE_PACKAGE = "evidence_package"
SELECT_VISUALISATION = "select_visualisation"

DRAFT_WORKFLOW = "draft_workflow"
DRAFT_INVESTIGATION = "draft_investigation"
DRAFT_RISK_CASE = "draft_risk_case"
ADD_TO_PROJECT = "add_to_project"


class ToolDenied(PermissionError):
    """An agent asked for something it is not permitted to do."""


class ToolUnknown(KeyError):
    """A tool id nothing in the registry defines."""


class ToolFailed(RuntimeError):
    """The underlying governed service could not answer."""


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    """One approved capability, and what calling it costs."""

    tool_id: str
    name: str
    purpose: str
    #: The governed service behind it, named for the audit record.
    service: str
    #: Parameter names this tool accepts. Anything else is rejected rather than
    #: ignored: a parameter the tool does not understand is a caller who thinks
    #: it does something it does not.
    parameters: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    #: True where calling it changes stored state. Every writer produces a
    #: draft.
    writes: bool = False
    #: True where it can reach client row-level data, and therefore has to be
    #: filtered to the principal's permissions.
    reads_data: bool = False
    #: Roughly how expensive, for the budget: "free", "scan", "model".
    cost: str = "free"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "purpose": self.purpose,
            "service": self.service,
            "parameters": list(self.parameters),
            "required": list(self.required),
            "writes": self.writes,
            "reads_data": self.reads_data,
            "cost": self.cost,
        }


TOOLS: tuple[Tool, ...] = (
    Tool(CATALOGUE_LOOKUP, "Catalogue lookup",
         "Which datasets, domains and periods the bank has published.",
         "backend.orchestration.context",
         parameters=("query", "domain", "dataset"), cost="free"),
    Tool(FIELD_RESOLUTION, "Field resolution",
         "Which governed field carries a named credit concept.",
         "backend.orchestration.concepts",
         parameters=("concept", "dataset"), required=("concept",)),
    Tool(RELATIONSHIP_PATH, "Relationship path",
         "The governed join path between two datasets, or the fact that "
         "there is not one.",
         "backend.services.relationships",
         parameters=("left", "right"), required=("left", "right")),
    Tool(SOURCE_PROFILE, "Source profile",
         "Row counts, distributions and key uniqueness for a published "
         "dataset at a period.",
         "backend.data_access.duckdb_source",
         parameters=("dataset", "period"), required=("dataset",),
         reads_data=True, cost="scan"),
    Tool(DATA_QUALITY, "Data quality",
         "Governed quality rules, drift and relationship health.",
         "backend.services.drift",
         parameters=("dataset", "period")),
    Tool(PERIOD_READINESS, "Period readiness",
         "Whether a reporting period is published and complete enough to "
         "analyse.",
         "backend.services.domain_status",
         parameters=("period", "domain")),

    Tool(PLAN_ANALYSIS, "Plan analysis",
         "Compose a validated Analytical IR for a bounded question. Produces "
         "a plan; it does not execute one.",
         "backend.orchestration.analysis_planner",
         parameters=("question", "concepts", "dimensions", "period",
                     "filters", "grain"),
         required=("question",), cost="model"),
    Tool(RUN_ANALYSIS, "Run analysis",
         "Execute a validated Analytical IR through the deterministic "
         "runtime. Takes an IR and nothing else — there is no path here for a "
         "string of SQL.",
         "backend.runtime.executor",
         parameters=("plan", "period", "limit"), required=("plan",),
         reads_data=True, cost="scan"),
    Tool(RUN_CERTIFIED_METHOD, "Run certified method",
         "Execute a method the bank has certified, with governed parameters.",
         "backend.orchestration.certified",
         parameters=("method", "parameters", "period"), required=("method",),
         reads_data=True, cost="scan"),
    Tool(RUN_SCENARIO, "Run scenario",
         "Execute a scenario the bank has defined.",
         "backend.stress",
         parameters=("scenario", "period"), required=("scenario",),
         reads_data=True, cost="scan"),
    Tool(NUMERICAL_KERNEL, "Numerical kernel",
         "An approved numerical operation over a result that already exists.",
         "backend.orchestration.kernels",
         parameters=("kernel", "result_ref", "column"),
         required=("kernel", "result_ref")),
    Tool(PREVIOUS_RESULT, "Previous result",
         "Reuse a result this run or this conversation already computed, "
         "rather than rescanning for it.",
         "backend.orchestration.reuse",
         parameters=("result_ref",), required=("result_ref",)),
    Tool(PRE_SCREEN, "Deterministic pre-screen",
         "Certified portfolio indicators and threshold tests over aggregates, "
         "run before any model call to decide what is worth looking at.",
         "backend.agentic.screening",
         parameters=("period", "prior_period", "scope"),
         reads_data=True, cost="scan"),

    Tool(VALIDATE_INVARIANTS, "Validate invariants",
         "Check a result against the business invariants its concepts carry.",
         "backend.orchestration.invariants",
         parameters=("result_ref", "concepts"), required=("result_ref",)),
    Tool(RECONCILE, "Reconcile",
         "Check that a result's totals agree with the sources it was built "
         "from.",
         "backend.orchestration.invariants",
         parameters=("result_ref",), required=("result_ref",)),
    Tool(GROUNDING_CHECK, "Grounding check",
         "Check that every figure in a written finding appears in the "
         "computed result.",
         "backend.orchestration.assembly",
         parameters=("text", "result_ref"), required=("text", "result_ref")),
    Tool(EVIDENCE_PACKAGE, "Evidence package",
         "Assemble the figures, scope and provenance behind a finding.",
         "backend.orchestration.evidence",
         parameters=("result_ref", "concepts")),
    Tool(SELECT_VISUALISATION, "Select visualisation",
         "Choose the governed chart form for a result shape.",
         "backend.orchestration.visualize",
         parameters=("result_ref",), required=("result_ref",)),

    Tool(DRAFT_WORKFLOW, "Draft workflow request",
         "Create a DRAFT workflow item. Sending it is a person's decision.",
         "backend.services.workflow",
         parameters=("object_type", "object_id", "title", "action",
                     "message", "recipients", "priority", "due_at"),
         required=("object_type", "object_id", "title"), writes=True),
    Tool(DRAFT_INVESTIGATION, "Draft investigation",
         "Open an Investigation seeded from a case or a finding.",
         "backend.services.threads",
         parameters=("question", "title", "project_id", "context"),
         required=("question",), writes=True),
    Tool(DRAFT_RISK_CASE, "Draft risk case",
         "Create a DRAFT Risk Case from validated evidence.",
         "backend.agentic.cases",
         parameters=("level", "entity", "entity_id", "title", "period",
                     "signals", "metrics", "evidence", "conclusion"),
         required=("level", "title", "period"), writes=True),
    Tool(ADD_TO_PROJECT, "Add to project",
         "Link an existing object to a Project.",
         "backend.services.projects",
         parameters=("project_id", "object_type", "object_id"),
         required=("project_id", "object_type", "object_id"), writes=True),
)

_BY_ID: dict[str, Tool] = {t.tool_id: t for t in TOOLS}

#: Actions §21 places at autonomy Level 4. Deliberately not tools: there is no
#: registry entry an agent could call, so the prohibition does not depend on a
#: permission check being written correctly.
NO_TOOL_EXISTS: tuple[str, ...] = (
    "publish_data",
    "certify_method",
    "approve_workflow",
    "send_workflow",
    "send_external_communication",
    "change_limits",
    "change_risk_appetite",
    "close_risk_case",
    "modify_client_data",
    "alter_certified_method",
    "execute_sql",
    "execute_python",
    "fetch_url",
    "read_file",
)


def tool(tool_id: str) -> Tool | None:
    return _BY_ID.get((tool_id or "").strip())


def require(tool_id: str) -> Tool:
    found = tool(tool_id)
    if found is None:
        raise ToolUnknown(
            f"'{tool_id}' is not a CreditProbe tool. Agents may only call "
            f"registered tools.")
    return found


def catalogue() -> dict[str, Any]:
    return {
        "tools": [t.to_dict() for t in TOOLS],
        "no_tool_exists": list(NO_TOOL_EXISTS),
    }


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass
class Call:
    """One tool call, as it happened. Recorded whether or not it succeeded."""

    tool_id: str
    agent_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    allowed: bool = False
    reason: str = ""
    duration_ms: int = 0
    rows_read: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool_id,
            "agent": self.agent_id,
            "parameters": _safe_parameters(self.parameters),
            "allowed": self.allowed,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "rows_read": self.rows_read,
            "error": self.error,
        }


def _safe_parameters(params: dict[str, Any]) -> dict[str, Any]:
    """Parameters as they go into the audit record.

    A plan or a result reference is kept; anything large is summarised. The
    audit trail has to show what was asked for, not carry a copy of the data.
    """
    out: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value if not isinstance(value, str) else value[:400]
        elif isinstance(value, (list, tuple)):
            out[key] = f"[{len(value)} items]"
        elif isinstance(value, dict):
            out[key] = f"{{{len(value)} keys}}"
        else:
            out[key] = type(value).__name__
    return out


def check(agent: Any, tool_id: str, parameters: dict[str, Any] | None = None,
          *, domains: list[str] | tuple[str, ...] = ()) -> Call:
    """May this agent make this call?

    Returns a Call rather than raising, so a refusal is recorded on the run's
    audit trail with its reason before anything decides what to do about it.
    A refusal that vanishes into an exception traceback is a refusal nobody can
    review afterwards.
    """
    agent_id = str(getattr(agent, "agent_id", "") or "unknown")
    call = Call(tool_id=tool_id, agent_id=agent_id,
                parameters=dict(parameters or {}))

    found = tool(tool_id)
    if found is None:
        call.reason = (f"'{tool_id}' is not a registered CreditProbe tool.")
        return call

    if not getattr(agent, "may_use", lambda _t: False)(tool_id):
        call.reason = (
            f"{getattr(agent, 'business_name', agent_id)} is not permitted to "
            f"use {found.name}.")
        return call

    missing = [p for p in found.required if p not in call.parameters]
    if missing:
        call.reason = (f"{found.name} needs {', '.join(missing)}.")
        return call

    unknown = [p for p in call.parameters if p not in found.parameters]
    if unknown:
        call.reason = (
            f"{found.name} does not take {', '.join(sorted(unknown))}.")
        return call

    for domain in domains or ():
        if not getattr(agent, "may_read", lambda _d: False)(domain):
            call.reason = (
                f"{getattr(agent, 'business_name', agent_id)} may not read the "
                f"{domain} domain.")
            return call

    call.allowed = True
    call.reason = f"{found.name} is permitted for this agent and scope."
    return call


def invoke(agent: Any, tool_id: str, parameters: dict[str, Any] | None = None,
           *, domains: list[str] | tuple[str, ...] = (),
           principal: Any = None,
           handlers: dict[str, Callable[..., Any]] | None = None,
           ) -> tuple[Call, Any]:
    """Make a permitted call, or refuse it.

    `handlers` maps tool ids onto the callables that do the work. The executor
    supplies it; the registry never imports the services itself, which is what
    keeps this module free of a circular dependency on half the backend and
    makes the whole gate trivially testable with a dictionary of fakes.

    The principal travels into every handler that reads data, because §57 is
    absolute: an agent runs with the requesting user's permissions and cannot
    widen them.
    """
    import time

    call = check(agent, tool_id, parameters, domains=domains)
    if not call.allowed:
        logger.info("tool refused: %s → %s (%s)", call.agent_id, tool_id,
                    call.reason)
        return call, None

    handler = (handlers or {}).get(tool_id)
    if handler is None:
        call.allowed = False
        call.error = "not_wired"
        call.reason = (
            f"{require(tool_id).name} is approved for this agent but no "
            f"handler is available in this context.")
        return call, None

    started = time.perf_counter()
    try:
        found = require(tool_id)
        result = (handler(principal=principal, **(parameters or {}))
                  if found.reads_data or found.writes
                  else handler(**(parameters or {})))
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        call.error = f"{type(exc).__name__}: {exc}"
        call.duration_ms = int((time.perf_counter() - started) * 1000)
        logger.warning("tool failed: %s → %s (%s)", call.agent_id, tool_id,
                       call.error)
        return call, None

    call.duration_ms = int((time.perf_counter() - started) * 1000)
    call.rows_read = int(getattr(result, "rows_read", 0) or 0)
    return call, result


__all__ = [
    "ADD_TO_PROJECT",
    "CATALOGUE_LOOKUP",
    "DATA_QUALITY",
    "DRAFT_INVESTIGATION",
    "DRAFT_RISK_CASE",
    "DRAFT_WORKFLOW",
    "EVIDENCE_PACKAGE",
    "FIELD_RESOLUTION",
    "GROUNDING_CHECK",
    "NO_TOOL_EXISTS",
    "NUMERICAL_KERNEL",
    "PERIOD_READINESS",
    "PLAN_ANALYSIS",
    "PRE_SCREEN",
    "PREVIOUS_RESULT",
    "RECONCILE",
    "RELATIONSHIP_PATH",
    "RUN_ANALYSIS",
    "RUN_CERTIFIED_METHOD",
    "RUN_SCENARIO",
    "SELECT_VISUALISATION",
    "SOURCE_PROFILE",
    "TOOLS",
    "VALIDATE_INVARIANTS",
    "Call",
    "Tool",
    "ToolDenied",
    "ToolFailed",
    "ToolUnknown",
    "catalogue",
    "check",
    "invoke",
    "require",
    "tool",
]
