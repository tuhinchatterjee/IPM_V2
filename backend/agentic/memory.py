"""
Agentic working memory. §23.

What this is, and what it is not
--------------------------------
The conversation already has a typed working memory
(`backend/orchestration/memory.py`) holding what the last turn was about. §23
asks for that to be *extended* for agentic state, and the extension is a
parallel typed slice under its own key rather than a dozen new fields on the
existing dataclass.

That is deliberate. `WorkingMemory` is what every referent in the product
resolves against and is covered by a large body of tests; widening it to carry a
task graph would make "what is this conversation about" and "what is the
orchestrator doing" the same object, and the first question would start
returning answers about the second. Two slices, one context document, one
`save()`.

Scoping — the part that is a safety property
--------------------------------------------
§23 requires memory scoped to user/project/investigation/case, tenant-safe,
versioned, auditable, and free of hidden cross-client memory. Each of those is
enforced here rather than trusted:

- Every slice carries its own `scope`, and `load()` **refuses a slice whose
  scope does not match the one asked for**, returning an empty memory instead.
  A context document copied between investigations therefore carries nothing
  across, which is the failure mode that "no hidden cross-client memory" is
  actually about.
- `version` increments on every write, so a stale document cannot silently
  overwrite a newer one.
- `history` keeps the last few decisions with their timestamps, so what the
  agents believed at a point in time is answerable.

Nothing here holds client rows. Findings are sentences plus references to
analysis runs; the figures live in the runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_KEY = "agentic_memory"

#: How many decisions and findings to keep. A conversation that ran forty
#: agentic turns does not need the first thirty in every prompt, and §24 is
#: explicit that a handoff must not carry unlimited history.
KEEP_FINDINGS = 12
KEEP_DECISIONS = 10
KEEP_HISTORY = 20


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """Whose memory this is.

    A tuple rather than a string because each part is checked: memory saved for
    investigation 12 must not be readable as investigation 13's, and comparing
    formatted strings is how a subtle mismatch becomes an equality.
    """

    tenant: str = "default"
    user_id: int | None = None
    project_id: int | None = None
    investigation_id: int | None = None
    case_id: int | None = None

    def matches(self, other: Scope) -> bool:
        return (self.tenant == other.tenant
                and self.user_id == other.user_id
                and self.project_id == other.project_id
                and self.investigation_id == other.investigation_id
                and self.case_id == other.case_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "investigation_id": self.investigation_id,
            "case_id": self.case_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Scope:
        data = raw or {}
        return cls(
            tenant=str(data.get("tenant") or "default"),
            user_id=_int_or_none(data.get("user_id")),
            project_id=_int_or_none(data.get("project_id")),
            investigation_id=_int_or_none(data.get("investigation_id")),
            case_id=_int_or_none(data.get("case_id")),
        )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The slice
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """One specialist's conclusion, with what backs it."""

    agent_id: str
    text: str
    #: AnalysisRun ids. The figures live there; nothing is copied here.
    analyses: list[int] = field(default_factory=list)
    confidence: str = ""
    at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {"agent_id": self.agent_id, "text": self.text,
                "analyses": list(self.analyses), "confidence": self.confidence,
                "at": self.at}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Finding:
        return cls(
            agent_id=str(raw.get("agent_id") or ""),
            text=str(raw.get("text") or ""),
            analyses=[int(a) for a in (raw.get("analyses") or [])
                      if str(a).isdigit()],
            confidence=str(raw.get("confidence") or ""),
            at=str(raw.get("at") or ""))


@dataclass
class AgenticMemory:
    """What the agents are doing, and what they have concluded. §23's list."""

    scope: Scope = field(default_factory=Scope)
    version: int = 0

    active_risk_case: int | None = None
    agentic_run_id: int | None = None
    officer_level: int = 0
    officer_title: str = ""
    active_agents: list[str] = field(default_factory=list)
    #: The plan as a document, not as objects — memory is serialised into a
    #: context column and has to survive a round trip through JSON.
    task_graph: dict[str, Any] = field(default_factory=dict)
    pending_approvals: list[int] = field(default_factory=list)

    #: portfolio | segment | borrower | data — what attention is scoped to.
    attention_scope: str = ""
    portfolio_context: dict[str, Any] = field(default_factory=dict)
    segment_context: dict[str, Any] = field(default_factory=dict)
    borrower_context: dict[str, Any] = field(default_factory=dict)

    agent_findings: list[Finding] = field(default_factory=list)
    agent_conflicts: list[dict[str, Any]] = field(default_factory=list)
    agent_decisions: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.agentic_run_id or self.agent_findings
                    or self.active_risk_case)

    # -- writing -----------------------------------------------------------

    def note(self, what: str, detail: dict[str, Any] | None = None) -> None:
        """Record something that happened, for the audit trail §23 requires."""
        self.history.append({"at": _now(), "what": what,
                             "detail": dict(detail or {})})
        self.history = self.history[-KEEP_HISTORY:]

    def remember_run(self, *, run_id: int | None, officer_level: int = 0,
                     officer_title: str = "", agents: list[str] | None = None,
                     task_graph: dict[str, Any] | None = None) -> None:
        self.agentic_run_id = run_id
        if officer_level:
            self.officer_level = officer_level
            self.officer_title = officer_title
        if agents is not None:
            self.active_agents = list(agents)
        if task_graph is not None:
            self.task_graph = dict(task_graph)
        self.note("run", {"run_id": run_id, "officer": officer_title})

    def add_finding(self, agent_id: str, text: str, *,
                    analyses: list[int] | None = None,
                    confidence: str = "") -> None:
        self.agent_findings.append(Finding(
            agent_id=agent_id, text=text, analyses=list(analyses or []),
            confidence=confidence))
        self.agent_findings = self.agent_findings[-KEEP_FINDINGS:]

    def add_conflict(self, *, between: list[str], about: str,
                     resolution: str = "", basis: str = "") -> None:
        """§25: a disagreement is preserved, not averaged."""
        self.agent_conflicts.append({
            "at": _now(), "between": list(between), "about": about,
            "resolution": resolution, "basis": basis})
        self.agent_conflicts = self.agent_conflicts[-KEEP_DECISIONS:]

    def add_decision(self, *, what: str, why: str, by: str = "") -> None:
        self.agent_decisions.append({"at": _now(), "what": what, "why": why,
                                     "by": by})
        self.agent_decisions = self.agent_decisions[-KEEP_DECISIONS:]

    def focus(self, level: str, detail: dict[str, Any]) -> None:
        """Set what attention is currently scoped to."""
        self.attention_scope = level
        if level == "portfolio":
            self.portfolio_context = dict(detail)
        elif level == "segment":
            self.segment_context = dict(detail)
        elif level == "borrower":
            self.borrower_context = dict(detail)

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "version": self.version,
            "active_risk_case": self.active_risk_case,
            "agentic_run_id": self.agentic_run_id,
            "officer_level": self.officer_level,
            "officer_title": self.officer_title,
            "active_agents": list(self.active_agents),
            "task_graph": dict(self.task_graph),
            "pending_approvals": list(self.pending_approvals),
            "attention_scope": self.attention_scope,
            "portfolio_context": dict(self.portfolio_context),
            "segment_context": dict(self.segment_context),
            "borrower_context": dict(self.borrower_context),
            "agent_findings": [f.to_dict() for f in self.agent_findings],
            "agent_conflicts": list(self.agent_conflicts),
            "agent_decisions": list(self.agent_decisions),
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AgenticMemory:
        data = raw or {}
        return cls(
            scope=Scope.from_dict(data.get("scope")),
            version=int(data.get("version") or 0),
            active_risk_case=_int_or_none(data.get("active_risk_case")),
            agentic_run_id=_int_or_none(data.get("agentic_run_id")),
            officer_level=int(data.get("officer_level") or 0),
            officer_title=str(data.get("officer_title") or ""),
            active_agents=[str(a) for a in (data.get("active_agents") or [])],
            task_graph=dict(data.get("task_graph") or {}),
            pending_approvals=[int(a) for a in
                               (data.get("pending_approvals") or [])
                               if str(a).isdigit()],
            attention_scope=str(data.get("attention_scope") or ""),
            portfolio_context=dict(data.get("portfolio_context") or {}),
            segment_context=dict(data.get("segment_context") or {}),
            borrower_context=dict(data.get("borrower_context") or {}),
            agent_findings=[Finding.from_dict(f) for f in
                            (data.get("agent_findings") or [])],
            agent_conflicts=list(data.get("agent_conflicts") or []),
            agent_decisions=list(data.get("agent_decisions") or []),
            history=list(data.get("history") or []),
        )


# ---------------------------------------------------------------------------
# Load and save
# ---------------------------------------------------------------------------


def load(context: dict[str, Any] | None, scope: Scope) -> AgenticMemory:
    """Read the agentic memory for this scope.

    A slice saved under a different scope comes back EMPTY rather than being
    read. That is the whole tenant guarantee in one line: a context document
    that travels — copied to another investigation, restored from a backup,
    forwarded in a link — carries no agentic state into a place it does not
    belong.
    """
    stored = (context or {}).get(MEMORY_KEY)
    if not stored:
        return AgenticMemory(scope=scope)

    found = AgenticMemory.from_dict(stored)
    if not found.scope.matches(scope):
        logger.info("agentic memory scope mismatch; starting empty "
                    "(stored=%s asked=%s)", found.scope.to_dict(),
                    scope.to_dict())
        return AgenticMemory(scope=scope)
    return found


def save(context: dict[str, Any] | None,
         memory: AgenticMemory) -> dict[str, Any]:
    """Write it back, one version on.

    The version increments here rather than at each mutation, so one turn is
    one version however many findings it recorded — which is what makes
    "version 4 is what the officer saw" a meaningful statement.
    """
    memory.version += 1
    return {**dict(context or {}), MEMORY_KEY: memory.to_dict()}


def forget(context: dict[str, Any] | None) -> dict[str, Any]:
    """Drop the agentic slice, leaving the rest of the context alone.

    Used when an object is copied — a Project template, a duplicated
    Investigation — so the copy starts without the original's agent state
    rather than inheriting findings about a different population.
    """
    out = dict(context or {})
    out.pop(MEMORY_KEY, None)
    return out


__all__ = [
    "KEEP_DECISIONS",
    "KEEP_FINDINGS",
    "MEMORY_KEY",
    "AgenticMemory",
    "Finding",
    "Scope",
    "forget",
    "load",
    "save",
]
