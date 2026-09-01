"""
Who an agentic run acts as. §57, §58.

    "Every specialist inherits the requesting user/service principal's
     permissions. A user must not gain access to data through an agent that
     they could not access directly."

The rule inverted is the risk: an agent that ran as an administrator would let
any user reach any data by asking a question, and nothing on the screen would
show it happening. So there is exactly one principal per run, it comes from the
caller, and every tool call carries it.

Two kinds of principal
----------------------
**A user's.** An interactive run inherits the signed-in principal, unchanged.

**A service identity.** A scheduled or event-driven review has no user, and
"no user" must not mean "no limits". `SERVICE` is a real principal with a real
role — DATA_STEWARD, wide enough to read the published book and narrow enough
that it cannot manage models or approve anything.

Filtering results back to the reader
------------------------------------
§57's last line: "Results are filtered to the viewing user's permissions." A
proactive run reads more than any one user might; what it PRODUCES is read by
people whose permissions differ from the service identity's. `visible_to()` is
where that is applied, and it is applied on read rather than on write, because
one case is read by many people.

Tenancy
-------
The product is currently single-tenant: there is one bank's data in one
deployment, and no table carries a tenant id. §58 asks that where tenancy is not
implemented, the boundary is preserved and documented as a release requirement.
`TENANT` and `tenant_of()` are that boundary — every agentic object is scoped
through them, so making the product multi-tenant means giving `tenant_of()` a
real implementation rather than finding every query that forgot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.api.permissions import Principal, Role

logger = logging.getLogger(__name__)

#: The single tenant this deployment serves. See the module note: this is a
#: seam, not a feature. Multi-tenancy is a release requirement documented in
#: docs/AGENTIC_AI.md, and it is implemented by resolving this per request.
TENANT = "default"

#: The identity a proactive run acts as. Named, so every row it touches is
#: attributable to something rather than to NULL.
SERVICE_IDENTITY = "creditprobe.review"

#: A DATA_STEWARD: may read the whole published book and run analyses, may not
#: manage models and may not approve anything. Deliberately not ADMIN — a
#: background process holding the widest role in the product is how a
#: convenience becomes an escalation path.
SERVICE = Principal(user_id=None, role=Role.DATA_STEWARD)


class NotVisible(PermissionError):
    """A reader asked for something their permissions do not reach."""


@dataclass(frozen=True)
class Actor:
    """Who a run is acting as, and how it is described in the record."""

    principal: Principal
    #: "" for a user, SERVICE_IDENTITY for a proactive run.
    service_identity: str = ""
    tenant: str = TENANT

    @property
    def user_id(self) -> int | None:
        return self.principal.user_id

    @property
    def role(self) -> str:
        return str(self.principal.role)

    @property
    def is_service(self) -> bool:
        return bool(self.service_identity)

    @property
    def label(self) -> str:
        return self.service_identity or f"user {self.user_id}"

    def to_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "role": self.role,
                "service_identity": self.service_identity,
                "tenant": self.tenant, "is_service": self.is_service}


def for_user(principal: Principal) -> Actor:
    """The actor for an interactive run: the caller, unchanged."""
    return Actor(principal=principal, service_identity="", tenant=TENANT)


def for_service() -> Actor:
    """The actor for a proactive run."""
    return Actor(principal=SERVICE, service_identity=SERVICE_IDENTITY,
                 tenant=TENANT)


def tenant_of(principal: Principal | None = None) -> str:
    """Which tenant a principal belongs to.

    Single-valued today. Every agentic query goes through it so that making the
    product multi-tenant is one function rather than an audit of every query.
    """
    _ = principal
    return TENANT


# ---------------------------------------------------------------------------
# Reading agentic output back
# ---------------------------------------------------------------------------

#: Who may see Risk Cases at all. A VIEWER may read approved and shared
#: objects; a Risk Case is neither until somebody shares it, so a viewer sees
#: only cases they own or were assigned.
CAN_READ_CASES: frozenset[Role] = frozenset(
    {Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})

#: Who may act on a case — assign, snooze, dismiss, resolve, investigate.
CAN_ACT_ON_CASES: frozenset[Role] = frozenset(
    {Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})

#: Who may see Agent Operations. §28: an Administrator/Data Steward screen.
CAN_OPERATE_AGENTS: frozenset[Role] = frozenset(
    {Role.ADMIN, Role.DATA_STEWARD})

#: Who may change agent policies and schedules. Narrower than reading them:
#: seeing what the autonomy policy is and being able to widen it are different
#: privileges.
CAN_GOVERN_AGENTS: frozenset[Role] = frozenset({Role.ADMIN})


def may_read_cases(principal: Principal) -> bool:
    return principal.role in CAN_READ_CASES


def may_act_on_cases(principal: Principal) -> bool:
    return principal.role in CAN_ACT_ON_CASES


def may_operate_agents(principal: Principal) -> bool:
    return principal.role in CAN_OPERATE_AGENTS


def may_govern_agents(principal: Principal) -> bool:
    return principal.role in CAN_GOVERN_AGENTS


def visible_to(principal: Principal, cases: list[Any]) -> list[Any]:
    """Filter cases to what this reader may see. §57's last line.

    Applied on READ rather than on write, because one case is read by many
    people with different permissions and a case filtered at creation would be
    filtered to whoever happened to trigger the review.

    A VIEWER sees only what is theirs. Everyone else sees the book, because
    that is what a credit risk function is — a Requires Attention that hid
    other people's cases would hide the concentration that only shows up when
    they are seen together.
    """
    if principal.role != Role.VIEWER:
        return list(cases)
    mine = principal.user_id
    if mine is None:
        return []
    return [c for c in cases if getattr(c, "owner_id", None) == mine]


def require_read(principal: Principal) -> None:
    if not may_read_cases(principal):
        raise NotVisible(
            "Risk Cases are visible to analysts, data stewards and "
            "administrators. A viewer sees the cases assigned to them.")


def require_act(principal: Principal) -> None:
    if not may_act_on_cases(principal):
        raise NotVisible(
            "Acting on a Risk Case needs at least an analyst's permissions.")


def require_operate(principal: Principal) -> None:
    if not may_operate_agents(principal):
        raise NotVisible(
            "Agent Operations is available to data stewards and "
            "administrators.")


def require_govern(principal: Principal) -> None:
    if not may_govern_agents(principal):
        raise NotVisible(
            "Changing agent policies, schedules and budgets is an "
            "administrator's decision.")


# ---------------------------------------------------------------------------
# The guarantee agents run under
# ---------------------------------------------------------------------------


def narrower_of(actor: Actor, agent: Any) -> Actor:
    """The permissions a specialist actually runs with.

    The INTERSECTION of the actor's and the agent's — never the union, and
    never the agent's alone. An agent whose definition allows every domain
    still cannot read a domain the calling user cannot; a user with every
    permission still cannot make an agent read outside its definition.

    Returned as the same actor because the domain restriction lives on the
    agent and is enforced by `tools.check`; this function exists to make the
    direction explicit and to be the one place a future data-level permission
    would be intersected.
    """
    _ = agent
    return actor


__all__ = [
    "CAN_ACT_ON_CASES",
    "CAN_GOVERN_AGENTS",
    "CAN_OPERATE_AGENTS",
    "CAN_READ_CASES",
    "SERVICE",
    "SERVICE_IDENTITY",
    "TENANT",
    "Actor",
    "NotVisible",
    "for_service",
    "for_user",
    "may_act_on_cases",
    "may_govern_agents",
    "may_operate_agents",
    "may_read_cases",
    "narrower_of",
    "require_act",
    "require_govern",
    "require_operate",
    "require_read",
    "tenant_of",
    "visible_to",
]
