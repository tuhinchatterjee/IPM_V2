"""
Approval gates, persisted. §22.

The record exists BEFORE the action does
----------------------------------------
That is the whole property. An approval row written after an action happened is
a receipt; one written before it is a gate. `open_gate()` creates a pending row
and returns; nothing performs the action until `decide()` records an APPROVE and
the caller then performs it, attributed to the person who approved.

An approver must be able to check
---------------------------------
§22 lists what a gate shows: the proposed action, the reason, the evidence, the
agent, the scope, the objects affected, the risk, the reversibility, the
approver role and the status. All of it is stored, because an approver being
asked to trust a one-line summary is an approver rubber-stamping.

Who may decide
--------------
`approver_role` comes from `autonomy.Action`, not from the agent proposing it,
and `decide()` checks it. A gate anybody can open is not a gate — and letting
the proposer choose its own approver would be exactly that.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.agentic import autonomy
from backend.models.platform import AgentApproval

logger = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
CHANGES_REQUESTED = "changes_requested"
EXPIRED = "expired"

DECISIONS: tuple[str, ...] = (APPROVED, REJECTED, CHANGES_REQUESTED)

#: Which roles may decide at each level, widest first. A role may approve
#: anything its own level or below — an ADMIN may approve an ANALYST-level
#: gate, and not the reverse.
ROLE_RANK: dict[str, int] = {
    "VIEWER": 0,
    "ANALYST": 1,
    "DATA_STEWARD": 2,
    "ADMIN": 3,
}


class NotAuthorised(PermissionError):
    """Somebody without the standing tried to decide a gate."""


class AlreadyDecided(ValueError):
    """A gate that has already been settled cannot be settled again."""


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------


def open_gate(session: Any, gate: Any, *, run_id: int | None = None,
              task_id: int | None = None) -> AgentApproval:
    """Record a proposed material action, waiting for a person."""
    row = AgentApproval(
        run_id=run_id, task_id=task_id,
        agent_id=getattr(gate, "agent_id", "") or "",
        action=getattr(gate, "action_id", "") or "",
        title=getattr(gate, "title", "")[:300],
        reason=getattr(gate, "reason", "") or "",
        proposal=dict(getattr(gate, "proposal", {}) or {}),
        evidence=dict(getattr(gate, "evidence", {}) or {}),
        scope=getattr(gate, "scope", "") or "",
        objects_affected=list(getattr(gate, "objects_affected", []) or []),
        risk=getattr(gate, "risk", "medium"),
        reversibility=getattr(gate, "reversibility", "reversible"),
        approver_role=getattr(gate, "approver_role", "ADMIN"),
        status=PENDING)
    session.add(row)
    session.flush()
    logger.info("approval gate %s opened: %s by %s", row.id, row.action,
                row.agent_id)
    return row


def may_decide(role: str, approval: AgentApproval) -> bool:
    """Whether this role has the standing to settle this gate."""
    return (ROLE_RANK.get(str(role or "").upper(), -1)
            >= ROLE_RANK.get(approval.approver_role.upper(), 99))


def decide(session: Any, approval: AgentApproval, *, decision: str,
           user_id: int, role: str, note: str = "") -> AgentApproval:
    """Settle a gate.

    Refuses a second decision. An approval that could be flipped afterwards is
    a record of an opinion rather than of a decision, and the audit trail would
    not show which one the action was taken under.
    """
    if decision not in DECISIONS:
        raise ValueError(f"'{decision}' is not an approval decision.")
    if approval.status != PENDING:
        raise AlreadyDecided(
            f"This gate was already {approval.status}. Reopening it would "
            f"leave no record of which decision the action was taken under.")
    if not may_decide(role, approval):
        raise NotAuthorised(
            f"{approval.title} needs {approval.approver_role} approval; "
            f"{role or 'this role'} cannot decide it.")

    approval.status = decision
    approval.decided_by = user_id
    approval.decided_at = _now()
    approval.decision_note = note or ""
    session.flush()
    logger.info("approval gate %s %s by user %s", approval.id, decision,
                user_id)
    return approval


def approved(approval: AgentApproval | None) -> bool:
    """Whether an action may now be performed.

    Checked immediately before the action, never cached: a gate approved and
    then the action deferred is a decision about something that may have moved
    on.
    """
    return approval is not None and approval.status == APPROVED


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def load(session: Any, approval_id: int) -> AgentApproval | None:
    return session.get(AgentApproval, approval_id)


def pending(session: Any, *, role: str = "", limit: int = 50
            ) -> list[AgentApproval]:
    """Gates waiting for somebody.

    Filtered to what this role can actually decide, because a queue full of
    items somebody cannot act on trains them to ignore the queue.
    """
    rows = list(session.execute(
        select(AgentApproval).where(AgentApproval.status == PENDING)
        .order_by(AgentApproval.created_at.desc()).limit(limit)
    ).scalars().all())
    if not role:
        return rows
    return [r for r in rows if may_decide(role, r)]


def for_run(session: Any, run_id: int) -> list[AgentApproval]:
    return list(session.execute(
        select(AgentApproval).where(AgentApproval.run_id == run_id)
        .order_by(AgentApproval.created_at)
    ).scalars().all())


def view(approval: AgentApproval) -> dict[str, Any]:
    """One gate, as an approver sees it. §22's list."""
    from backend.agentic import registry

    action = autonomy.action(approval.action)
    agent = registry.agent(approval.agent_id)
    return {
        "id": approval.id,
        "run_id": approval.run_id,
        "task_id": approval.task_id,
        "action": approval.action,
        "action_label": action.label if action else approval.action,
        "consequence": action.consequence if action else "",
        "autonomy_level": action.level if action else autonomy.MATERIAL,
        "agent_id": approval.agent_id,
        "agent_name": agent.business_name if agent else approval.agent_id,
        "title": approval.title,
        "reason": approval.reason,
        "proposal": dict(approval.proposal or {}),
        "evidence": dict(approval.evidence or {}),
        "scope": approval.scope,
        "objects_affected": list(approval.objects_affected or []),
        "risk": approval.risk,
        "reversibility": approval.reversibility,
        "approver_role": approval.approver_role,
        "status": approval.status,
        "decided_by": approval.decided_by,
        "decided_at": (approval.decided_at.isoformat()
                       if approval.decided_at else None),
        "decision_note": approval.decision_note,
        "created_at": (approval.created_at.isoformat()
                       if approval.created_at else None),
        "actions": ["APPROVE", "REJECT", "REQUEST CHANGE", "OPEN EVIDENCE",
                    "OPEN TRACE"],
    }


__all__ = [
    "APPROVED",
    "CHANGES_REQUESTED",
    "DECISIONS",
    "EXPIRED",
    "PENDING",
    "REJECTED",
    "ROLE_RANK",
    "AlreadyDecided",
    "NotAuthorised",
    "approved",
    "decide",
    "for_run",
    "load",
    "may_decide",
    "open_gate",
    "pending",
    "view",
]
