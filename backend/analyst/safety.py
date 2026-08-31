"""What the analyst may do to the data, and what it may never do. §4.

The rule
--------
The model never writes a query. It names a governed tool and passes arguments;
CreditProbe builds the analytical plan. So the question "could the model issue
a DELETE?" has a structural answer rather than a filtering one: the analytical
IR (`backend/runtime/ir.py`) has no verb for it. `OpType` enumerates SCAN,
FILTER, DERIVE, GROUP, JOIN, WINDOW, SORT, LIMIT and their relatives. There is
no INSERT, no UPDATE, no DELETE, no DROP, no ALTER, no CREATE, no TRUNCATE, no
COPY, no ATTACH, no INSTALL, no LOAD, and no way to spell one.

That is worth stating plainly because the alternative — letting a model emit
SQL and refusing the dangerous strings — is the arrangement every SQL-injection
advisory of the last twenty years is about. A denylist is a list of the attacks
somebody thought of.

What this module adds on top
----------------------------
The IR being read-only makes a WRITE impossible. It does not make every READ
permissible, and §4 lists the rest:

  * **Authenticated principal.** Every tool call carries one. There is no
    anonymous path and no "system" caller for user questions.
  * **Permission.** The principal's role must carry the capability the tool
    declares. Checked here, before the handler runs.
  * **Dataset authority and scope.** A dataset the principal may not read is
    not merely filtered out of the result — it is not visible in discovery
    either, so the model cannot ask for it and cannot infer it exists.
  * **Governed relationships.** Joins come from the declared relationship
    graph. The model may ask to join two datasets; it may not invent the key.
  * **Timeouts and row limits.** Tighter than the interactive defaults,
    because an agent loop can issue several queries per question.
  * **Deterministic ordering.** Every result is sorted by an explicit key with
    an explicit tie-break, so the same question returns the same rows (§11).

None of this is delegated to the model. A prompt asking it to behave is not a
control; it is a request, and the thing on the other end is a text generator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SAFETY_VERSION = "1.0.0"

# --------------------------------------------------------------- the limits

#: A single tool call's row ceiling. Far below the interactive runtime's
#: 50,000: an agent turn's result is EVIDENCE the model reads, and a hundred
#: thousand rows of it is neither readable by a model nor useful to a reader.
MAX_TOOL_ROWS = 500

#: Rows actually handed back to the model, per call. The rest are counted and
#: summarised. A model given five hundred rows spends its attention on the
#: five hundred rows; the reader sees the full table in the result.
MAX_ROWS_TO_MODEL = 40

#: Seconds one tool call may take. Several of these happen per question.
TOOL_TIMEOUT_SECONDS = 25

#: Tool calls in one investigation. Past this the loop is not converging, and
#: §50 is explicit that a budget is a control rather than a hope.
MAX_TOOL_CALLS = 12

#: Turns of the model in one investigation, including the final answer.
MAX_TURNS = 8


# ------------------------------------------------------------- capabilities

#: What a tool needs the principal to be allowed to do. Deliberately coarse:
#: these map onto the roles the product already has, and inventing a
#: finer-grained permission model for the analyst would create a second
#: authorisation system to keep in step with the first.
READ_DATA = "read_data"
READ_METADATA = "read_metadata"
RUN_ANALYSIS = "run_analysis"

CAPABILITIES: tuple[str, ...] = (READ_METADATA, READ_DATA, RUN_ANALYSIS)

#: Role -> what it may ask the analyst to do. VIEWER may read and may run a
#: governed analysis, because reading a portfolio IS running one; what VIEWER
#: may not do lives elsewhere in the product and is not reachable from here at
#: all, since no tool in the registry writes anything.
BY_ROLE: dict[str, frozenset[str]] = {
    "ADMIN": frozenset(CAPABILITIES),
    "DATA_STEWARD": frozenset(CAPABILITIES),
    "ANALYST": frozenset(CAPABILITIES),
    "VIEWER": frozenset({READ_METADATA, READ_DATA, RUN_ANALYSIS}),
}


class Refused(PermissionError):
    """A tool call that will not be run, with the reason.

    A refusal is a governed outcome, not a fault: the loop is told, the
    reason goes on the Trace, and the model gets to choose something else.
    That is the difference between a control and an outage.
    """


@dataclass(frozen=True)
class Principal:
    """Who is asking. Never absent, never defaulted to an administrator.

    A thin structural copy of the API's principal rather than a reference to
    it, so `backend.analyst` can be unit-tested without an HTTP layer and so
    nothing here can accidentally start depending on a request object.
    """

    user_id: int = 0
    role: str = "VIEWER"
    #: Datasets this principal may read. Empty means "the governed default for
    #: the role", which is resolved by the catalogue rather than assumed here.
    datasets: frozenset[str] = field(default_factory=frozenset)

    @property
    def capabilities(self) -> frozenset[str]:
        return BY_ROLE.get(self.role.upper(), frozenset())

    def may(self, capability: str) -> bool:
        return capability in self.capabilities


# --------------------------------------------------------- the write denial

#: Every statement kind that changes or reaches beyond the data. Present as a
#: BELT, not the braces: the braces are that the IR cannot express any of them.
#: This exists so that if somebody ever adds a tool taking a SQL fragment, the
#: test suite fails on the day they add it rather than in production.
FORBIDDEN_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|MERGE|"
    r"GRANT|REVOKE|COPY|ATTACH|DETACH|INSTALL|LOAD|EXPORT|IMPORT|PRAGMA|"
    r"CALL|EXECUTE|SET\s+GLOBAL|VACUUM|CHECKPOINT)\b",
    re.IGNORECASE)

#: Reaching outside the governed lake. DuckDB will happily read a URL or a
#: local path from inside a query if a query is ever accepted as text.
FORBIDDEN_REACH = re.compile(
    r"read_csv|read_parquet|read_json|glob\s*\(|https?://|file://|"
    r"\.\./|/etc/|~/|system\s*\(|shell",
    re.IGNORECASE)

#: The operations a tool-built plan is allowed to contain. A closed list, so a
#: tool added later cannot quietly widen what the analyst can run: adding an
#: operation here is a visible, reviewable change.
ALLOWED_OPERATIONS: frozenset[str] = frozenset({
    "SCAN", "SELECT", "FILTER", "DERIVE", "CAST", "DEDUPLICATE",
    "SORT", "LIMIT", "TOP_N", "BOTTOM_N",
    "JOIN", "ASOF_JOIN", "UNION", "APPEND",
    "AGGREGATE_BEFORE_JOIN", "RECONCILE_GRAIN", "TEMPORAL_ALIGN",
    "RELATIONSHIP_PATH",
    "GROUP", "AGGREGATE", "DISTINCT_COUNT",
    "WINDOW", "LAG", "LEAD", "ROLLING", "MOVING_AVERAGE", "RANK",
    "RATIO", "PIVOT", "UNPIVOT", "NORMALIZE",
})


def refuse_writes(text: str) -> None:
    """Raise if `text` contains anything that is not a read.

    Applied to any free text that could conceivably reach a query engine. No
    tool currently passes one — the IR is built by CreditProbe from typed
    arguments — and this is here so that the first tool that does is caught by
    `tests/analyst/test_safe_access.py` rather than by an incident.
    """
    found = FORBIDDEN_SQL.search(text or "")
    if found:
        raise Refused(
            f"{found.group(0).upper()} is not something the analyst can do. "
            "Every governed tool reads; none of them writes.")
    reach = FORBIDDEN_REACH.search(text or "")
    if reach:
        raise Refused(
            "That would read from outside the governed data lake. The analyst "
            "can only see datasets the catalogue publishes.")


def check_plan(plan: Any) -> None:
    """Every operation in a tool-built plan is on the allowed list.

    The plan is built by CreditProbe from the tool's typed arguments, so this
    can only fail if a handler is wrong. That is exactly when it should fail —
    loudly, before the query runs, rather than quietly afterwards.
    """
    operations = getattr(plan, "operations", None)
    if operations is None and isinstance(plan, dict):
        operations = plan.get("operations") or []
    for operation in operations or []:
        kind = str(getattr(operation, "op", "")
                   or (operation.get("op") if isinstance(operation, dict)
                       else ""))
        if kind and kind not in ALLOWED_OPERATIONS:
            raise Refused(
                f"{kind} is not an operation the analyst may run. "
                f"The governed list is: {', '.join(sorted(ALLOWED_OPERATIONS))}.")


def check_permission(principal: Principal, capability: str,
                     tool: str) -> None:
    if not principal.may(capability):
        raise Refused(
            f"A {principal.role.title()} may not use {tool}. "
            f"It requires {capability.replace('_', ' ')}.")


def visible_datasets(principal: Principal, published: list[str]) -> list[str]:
    """The datasets this principal may read, in a stable order.

    A dataset the principal may not read is absent from DISCOVERY, not merely
    filtered out of a result. A model told a dataset exists and then refused
    it will spend turns trying to reach it, and — worse — the refusal itself
    tells it something about a book it may not see.
    """
    if not principal.datasets:
        return sorted(published)
    return sorted(name for name in published if name in principal.datasets)
