"""
What an agent may do on its own, and what needs a person. §21, §22.

Five levels
-----------
    0  OBSERVE     read governed state and summarise it
    1  RECOMMEND   propose an analysis or an action
    2  DRAFT       create a draft: an Investigation, a Risk Case, a workflow
                   request, a Project link, a method review item
    3  EXECUTE     perform a pre-approved low-risk action, where an
                   administrator's policy explicitly allows it
    4  MATERIAL    change something that matters outside CreditProbe

Level 4 has no path
-------------------
There is no autonomy setting that grants Level 4, no policy that unlocks it, and
— crucially — no tool in the registry that performs one (see
`tools.NO_TOOL_EXISTS`). An agent cannot publish data, certify a method, approve
a workflow item, change a limit, close a material case, send an external
message or modify client data, because the function does not exist for it to
call. What it can do is *propose* one, which creates an Approval Gate.

That is the difference between a permission check and an architecture. A check
can be wrong; a missing function cannot be called.

The gate
--------
`gate_for()` builds the record §22 asks for: the proposed action, the reason,
the evidence, the agent, the scope, the objects affected, the risk, the
reversibility, the approver role and the status. It is created BEFORE the action
would happen, so approving it is what causes the action rather than what records
one that already occurred.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

OBSERVE = 0
RECOMMEND = 1
DRAFT = 2
EXECUTE_PREAPPROVED = 3
MATERIAL = 4

LEVELS: tuple[int, ...] = (OBSERVE, RECOMMEND, DRAFT, EXECUTE_PREAPPROVED,
                           MATERIAL)

LEVEL_NAMES: dict[int, str] = {
    OBSERVE: "Observe",
    RECOMMEND: "Recommend",
    DRAFT: "Draft",
    EXECUTE_PREAPPROVED: "Execute pre-approved",
    MATERIAL: "Material side effect",
}

LEVEL_MEANING: dict[int, str] = {
    OBSERVE: "Reads governed state and summarises it. Changes nothing.",
    RECOMMEND: "Proposes an analysis or an action for a person to take.",
    DRAFT: ("Creates a draft — an Investigation, a Risk Case, a workflow "
            "request — which a person then sends, edits or discards."),
    EXECUTE_PREAPPROVED: ("Performs a low-risk action an administrator has "
                          "explicitly pre-approved by policy."),
    MATERIAL: ("Changes something outside CreditProbe. Never permitted without "
               "a named person approving this specific action."),
}


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """One thing an agent might want to do, and what it takes."""

    action_id: str
    label: str
    level: int
    #: What a person is agreeing to, in their own terms.
    consequence: str
    #: reversible | partially_reversible | irreversible
    reversibility: str = "reversible"
    #: low | medium | high
    risk: str = "medium"
    #: The narrowest role that may approve it.
    approver_role: str = "ADMIN"

    @property
    def needs_approval(self) -> bool:
        return self.level >= MATERIAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "level": self.level,
            "level_name": LEVEL_NAMES[self.level],
            "consequence": self.consequence,
            "reversibility": self.reversibility,
            "risk": self.risk,
            "approver_role": self.approver_role,
            "needs_approval": self.needs_approval,
        }


ACTIONS: tuple[Action, ...] = (
    # ---- Level 2: drafts ------------------------------------------------
    Action("draft_risk_case", "Create a draft Risk Case", DRAFT,
           "A case appears in Requires Attention for somebody to triage.",
           reversibility="reversible", risk="low", approver_role="ANALYST"),
    Action("draft_investigation", "Open an Investigation", DRAFT,
           "An Investigation thread is created, seeded from the case.",
           reversibility="reversible", risk="low", approver_role="ANALYST"),
    Action("draft_workflow", "Draft a workflow request", DRAFT,
           "A workflow item is created as a DRAFT. Nobody is notified.",
           reversibility="reversible", risk="low", approver_role="ANALYST"),
    Action("add_to_project", "Link an object to a Project", DRAFT,
           "The object appears in the Project. Nothing is copied.",
           reversibility="reversible", risk="low", approver_role="ANALYST"),

    # ---- Level 3: pre-approved ------------------------------------------
    Action("run_certified_monitoring", "Run a certified monitoring analysis",
           EXECUTE_PREAPPROVED,
           "A certified method runs over published data. Nothing changes.",
           reversibility="reversible", risk="low",
           approver_role="DATA_STEWARD"),
    Action("refresh_attention", "Refresh Requires Attention",
           EXECUTE_PREAPPROVED,
           "Existing cases are re-scored against the current period.",
           reversibility="reversible", risk="low",
           approver_role="DATA_STEWARD"),

    # ---- Level 4: material ----------------------------------------------
    Action("send_workflow", "Send a workflow request to people", MATERIAL,
           "Named people are asked to act, and see it in their queue.",
           reversibility="partially_reversible", risk="medium",
           approver_role="ANALYST"),
    Action("assign_owner", "Assign a case owner", MATERIAL,
           "Somebody becomes accountable for this case.",
           reversibility="reversible", risk="low", approver_role="ANALYST"),
    Action("close_case", "Close or resolve a Risk Case", MATERIAL,
           "The case leaves Requires Attention and stops being reviewed.",
           reversibility="reversible", risk="medium",
           approver_role="DATA_STEWARD"),
    Action("publish_data", "Publish a dataset", MATERIAL,
           "The data becomes authoritative and every analysis will use it.",
           reversibility="partially_reversible", risk="high",
           approver_role="DATA_STEWARD"),
    Action("certify_method", "Certify a method", MATERIAL,
           "The method becomes one the bank stands behind.",
           reversibility="partially_reversible", risk="high",
           approver_role="ADMIN"),
    Action("approve_workflow", "Approve a workflow item", MATERIAL,
           "A decision is recorded in the bank's name.",
           reversibility="irreversible", risk="high", approver_role="ADMIN"),
    Action("change_limits", "Change an exposure limit", MATERIAL,
           "What the bank is permitted to lend changes.",
           reversibility="partially_reversible", risk="high",
           approver_role="ADMIN"),
    Action("change_risk_appetite", "Change a risk-appetite threshold",
           MATERIAL,
           "What counts as a breach changes, for everybody.",
           reversibility="partially_reversible", risk="high",
           approver_role="ADMIN"),
    Action("external_communication", "Send an external communication",
           MATERIAL,
           "Something leaves the bank in the bank's name.",
           reversibility="irreversible", risk="high", approver_role="ADMIN"),
    Action("modify_client_data", "Modify client data", MATERIAL,
           "The bank's record of a client changes.",
           reversibility="irreversible", risk="high",
           approver_role="DATA_STEWARD"),
)

_BY_ID: dict[str, Action] = {a.action_id: a for a in ACTIONS}


def action(action_id: str) -> Action | None:
    return _BY_ID.get((action_id or "").strip())


def level_of(action_id: str) -> int:
    """What level an action sits at. An action nobody defined is treated as
    material, which is the safe direction to be wrong in."""
    found = action(action_id)
    return found.level if found else MATERIAL


def material(action_id: str) -> bool:
    return level_of(action_id) >= MATERIAL


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    """Whether an agent may do this now."""

    allowed: bool
    action_id: str
    level: int
    reason: str
    needs_approval: bool = False
    approver_role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "action": self.action_id,
            "level": self.level,
            "level_name": LEVEL_NAMES.get(self.level, str(self.level)),
            "reason": self.reason,
            "needs_approval": self.needs_approval,
            "approver_role": self.approver_role,
        }


def may(agent: Any, action_id: str, *,
        policy: dict[str, Any] | None = None) -> Verdict:
    """May this agent perform this action without asking a person?

    Three ways to be refused, and they are different refusals:

    - The action is material. Nobody's autonomy grants it, and there is no tool
      to perform it. → needs approval.
    - The action is above the agent's own autonomy level. → refused, and the
      agent should propose rather than act.
    - The action is pre-approved (Level 3) but no policy pre-approves it here.
      → needs approval, because "pre-approved" without a policy is just
      "approved by nobody".
    """
    found = action(action_id)
    if found is None:
        return Verdict(
            allowed=False, action_id=action_id, level=MATERIAL,
            reason=(f"'{action_id}' is not an action CreditProbe defines. "
                    f"Undefined actions are treated as material."),
            needs_approval=True, approver_role="ADMIN")

    agent_level = int(getattr(agent, "autonomy_level", 0) or 0)
    named = set(getattr(agent, "human_approval_requirements", ()) or ())

    if found.level >= MATERIAL:
        return Verdict(
            allowed=False, action_id=action_id, level=found.level,
            reason=(f"{found.label} changes something outside CreditProbe. "
                    f"§21 places it at Level 4, which always requires a named "
                    f"person."),
            needs_approval=True, approver_role=found.approver_role)

    if action_id in named:
        return Verdict(
            allowed=False, action_id=action_id, level=found.level,
            reason=(f"{getattr(agent, 'business_name', 'This agent')}'s "
                    f"definition requires human approval for {found.label}."),
            needs_approval=True, approver_role=found.approver_role)

    if found.level > agent_level:
        return Verdict(
            allowed=False, action_id=action_id, level=found.level,
            reason=(f"{getattr(agent, 'business_name', 'This agent')} operates "
                    f"at autonomy level {agent_level} "
                    f"({LEVEL_NAMES.get(agent_level, '')}); {found.label} is "
                    f"level {found.level}."),
            needs_approval=True, approver_role=found.approver_role)

    if found.level == EXECUTE_PREAPPROVED:
        allowed_here = set((policy or {}).get("pre_approved", []) or [])
        if action_id not in allowed_here:
            return Verdict(
                allowed=False, action_id=action_id, level=found.level,
                reason=(f"{found.label} is a pre-approved action, but no "
                        f"administrator policy pre-approves it here."),
                needs_approval=True, approver_role=found.approver_role)

    return Verdict(
        allowed=True, action_id=action_id, level=found.level,
        reason=f"{found.label} is within this agent's autonomy.")


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@dataclass
class Gate:
    """A proposed material action, as an approver sees it. §22."""

    action_id: str
    title: str
    reason: str
    agent_id: str
    scope: str = ""
    proposal: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    objects_affected: list[dict[str, Any]] = field(default_factory=list)
    risk: str = "medium"
    reversibility: str = "reversible"
    approver_role: str = "ADMIN"
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        found = action(self.action_id)
        return {
            "action": self.action_id,
            "action_label": found.label if found else self.action_id,
            "consequence": found.consequence if found else "",
            "title": self.title,
            "reason": self.reason,
            "agent_id": self.agent_id,
            "scope": self.scope,
            "proposal": dict(self.proposal),
            "evidence": dict(self.evidence),
            "objects_affected": list(self.objects_affected),
            "risk": self.risk,
            "reversibility": self.reversibility,
            "approver_role": self.approver_role,
            "status": self.status,
            # §22's own action list, so the UI does not invent its own.
            "actions": ["APPROVE", "REJECT", "REQUEST CHANGE",
                        "OPEN EVIDENCE", "OPEN TRACE"],
        }


def gate_for(agent: Any, action_id: str, *, title: str, reason: str,
             scope: str = "", proposal: dict[str, Any] | None = None,
             evidence: dict[str, Any] | None = None,
             objects: list[dict[str, Any]] | None = None) -> Gate:
    """Build the approval record for a proposed action."""
    found = action(action_id)
    return Gate(
        action_id=action_id, title=title, reason=reason,
        agent_id=str(getattr(agent, "agent_id", "") or ""),
        scope=scope, proposal=dict(proposal or {}),
        evidence=dict(evidence or {}), objects_affected=list(objects or []),
        risk=found.risk if found else "high",
        reversibility=found.reversibility if found else "irreversible",
        approver_role=found.approver_role if found else "ADMIN")


def policy_defaults() -> dict[str, Any]:
    """The autonomy policy as the product ships.

    Nothing is pre-approved. §21 Level 3 exists so an administrator CAN
    pre-approve a monitoring run, not so the product arrives with a list of
    things it will do without being asked.
    """
    return {
        "pre_approved": [],
        "max_autonomy_level": DRAFT,
        "note": ("No action is pre-approved by default. An administrator adds "
                 "an action id to `pre_approved` to let agents perform it "
                 "without an approval gate."),
    }


__all__ = [
    "ACTIONS",
    "DRAFT",
    "EXECUTE_PREAPPROVED",
    "LEVELS",
    "LEVEL_MEANING",
    "LEVEL_NAMES",
    "MATERIAL",
    "OBSERVE",
    "RECOMMEND",
    "Action",
    "Gate",
    "Verdict",
    "action",
    "gate_for",
    "level_of",
    "material",
    "may",
    "policy_defaults",
]
