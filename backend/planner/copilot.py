"""The Project Planner Copilot's permissions, expressed as a registry entry.

§2 asks for planner-only scope enforced in the BACKEND rather than in a system
prompt, and this module is the enforcement. It is deliberately small, because
the whole point is that it can be read in one sitting and checked against the
list of tools that exist.

`agent()` returns something with the `may_use` / `may_read` shape that
`backend.agentic.tools.check` already gates every other agent with. Its
`allowed_tools` is a literal tuple naming the twenty-five planner tools and
nothing else. So a model that decides to call `run_analysis`, or invents a
tool id, or is talked into asking for `publish_data` by a sentence somebody
typed into a project description, is refused by the same gate that refuses
every other agent — and the refusal is recorded as a `Call` with its reason,
not swallowed.

Two rules that are easy to state and easy to get wrong.

**The LLM is not authorization.** Every handler here takes the requesting
person's principal and every one of them ends in `access.py`. The model
chooses which question to ask; the participant list decides what comes back.
An agent asked about a project the person cannot see gets the same answer the
person would get by typing the id into the URL: there is no such project.

**Publishing is an act, not a drift.** There is no publish TOOL. The Copilot
can build a plan, show it in full and say it is ready; turning it into a real
project happens on a route a person calls, through `confirm_publish` below,
with a confirmation this module checks rather than trusts from the model's
paraphrase. A conversation that wanders towards "shall I set that up then?"
must not create a project because the model felt agreed with — and the surest
way to guarantee that is for the capability not to be in the agent's hands at
all. `agentic.tools.NO_TOOL_EXISTS` carries `publish_project` for the same
reason it carries `assign_owner`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.agentic import tools as reg
from backend.planner import scope

logger = logging.getLogger(__name__)

COPILOT_VERSION = "1.0.0"

AGENT_ID = "project_planner_copilot"
BUSINESS_NAME = "Project Planner Copilot"


#: Everything the Copilot may call. Written out rather than derived from a
#: prefix: a tool added later whose id happens to start with `planner_` should
#: have to be put on this list by somebody, not acquire access by being named
#: well.
ALLOWED_TOOLS: tuple[str, ...] = (
    # Reading the estate.
    reg.PLANNER_PORTFOLIO,
    reg.PLANNER_PROJECT,
    reg.PLANNER_MY_WORK,
    reg.PLANNER_ATTENTION,
    reg.PLANNER_CHANGES,
    reg.PLANNER_ACTIVITY,
    reg.PLANNER_TASKS,
    reg.PLANNER_DEPENDENCIES,
    reg.PLANNER_RAID,
    reg.PLANNER_MILESTONES,
    reg.PLANNER_CHASE_LIST,
    reg.PLANNER_CRITICAL_PATH,
    reg.PLANNER_SLIP_IMPACT,
    reg.PLANNER_REQUESTS,
    reg.PLANNER_PEOPLE,
    # The three things a person may change by saying so.
    reg.PLANNER_POST_TASK_UPDATE,
    reg.PLANNER_SET_TASK_BLOCKER,
    reg.PLANNER_CREATE_RAID_ITEM,
    reg.PLANNER_DRAFT_UPDATE,
    # Building a plan that is not a project yet.
    reg.PLANNER_DRAFT_START,
    reg.PLANNER_DRAFT_READ,
    reg.PLANNER_DRAFT_APPLY,
    reg.PLANNER_DRAFT_LINK_PREVIEW,
    reg.PLANNER_DRAFT_PREVIEW,
)

#: The Copilot reads no governed data domain. Delivery lives in the planner's
#: own tables, and a Copilot that could read the credit domains would be one
#: prompt away from answering a credit question with real numbers.
ALLOWED_DOMAINS: tuple[str, ...] = ()


class NotConfirmed(PermissionError):
    """A publish arrived without the person actually saying yes."""


@dataclass(frozen=True)
class Copilot:
    """The Copilot as the tool gate sees it."""

    agent_id: str = AGENT_ID
    business_name: str = BUSINESS_NAME
    purpose: str = scope.PURPOSE
    allowed_tools: tuple[str, ...] = ALLOWED_TOOLS
    allowed_data_domains: tuple[str, ...] = ALLOWED_DOMAINS
    version: str = COPILOT_VERSION

    def may_use(self, tool_id: str) -> bool:
        return tool_id in self.allowed_tools

    def may_read(self, domain: str) -> bool:
        return domain in self.allowed_data_domains

    def to_dict(self) -> dict[str, Any]:
        return {"agent_id": self.agent_id,
                "business_name": self.business_name,
                "purpose": self.purpose,
                "allowed_tools": list(self.allowed_tools),
                "allowed_data_domains": list(self.allowed_data_domains),
                "version": self.version}


_AGENT = Copilot()


def agent() -> Copilot:
    return _AGENT


def catalogue() -> dict[str, Any]:
    """What the Copilot can do, for the screen that says so.

    Built by asking the registry about each allowed id rather than by
    describing them again here, so a tool whose purpose changes cannot end up
    described two different ways in two places.
    """
    return {
        "agent": _AGENT.to_dict(),
        "tools": [reg.require(t).to_dict() for t in ALLOWED_TOOLS],
        "out_of_scope": [
            {"area": area.key, "label": area.label, "where": area.where}
            for area in scope.AREAS],
    }


# --------------------------------------------------------------- handlers


def people(session: Any, principal: Any, *, search: str = "",
           limit: int = 20) -> dict[str, Any]:
    """Colleagues who can be named as an owner, sponsor or escalation contact.

    Names and roles only. The Copilot needs to turn "Omar" into a user id to
    put him on a task; it has no business knowing anybody's email address, and
    a lookup that returned one would make the assistant a directory scrape.
    """
    from sqlalchemy import or_, select

    from backend.db.models import User

    query = select(User).where(User.is_active.is_(True))
    text = str(search or "").strip()
    if text:
        like = f"%{text.lower()}%"
        query = query.where(or_(
            User.username.ilike(like), User.first_name.ilike(like),
            User.last_name.ilike(like)))
    rows = list(session.execute(
        query.order_by(User.first_name, User.last_name)
        .limit(max(1, min(int(limit or 20), 50)))).scalars())
    return {"people": [
        {"user_id": int(row.id),
         "name": " ".join(p for p in (row.first_name, row.last_name) if p)
                 or row.username,
         "username": row.username,
         "role": row.role}
        for row in rows]}


#: Words that appear in sentences and never in a person's name. Skipped when
#: working out who a message might be talking about, so a search for
#: colleagues does not fire on "the" and return the first fifty people
#: alphabetically.
_NOT_A_NAME = {
    "add", "and", "the", "for", "with", "under", "owns", "own", "owned",
    "escalate", "escalation", "owner", "contact", "task", "tasks", "move",
    "milestone", "milestones", "start", "starts", "starting", "end", "ends",
    "due", "until", "after", "before", "link", "to", "from", "this", "that",
    "it", "its", "project", "change", "set", "make", "monitoring", "days",
    "day", "critical", "standard", "light", "custom", "need", "needs", "new",
    "first", "second", "third", "next", "last", "only", "can", "cannot",
    "finished", "complete", "completed", "done", "review", "report", "data",
    "call", "called", "name", "named", "remove", "delete", "please",
}


def people_for(session: Any, principal: Any, message: str,
               plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The colleagues this message might be talking about.

    Looked up by the words the person actually used, plus everybody the plan
    already names. A directory page would be wrong twice over: on a bank with
    four thousand staff the fiftieth name alphabetically is not the one being
    talked about, and a truncated list turns "who is Sameer?" into "nobody",
    which is a silent wrong answer rather than a question.

    Searching by word also keeps ambiguity honest: two colleagues called
    Sameer both come back, so the Copilot asks instead of choosing.
    """
    from sqlalchemy import or_, select

    from backend.db.models import User

    words = _name_candidates(message)
    found: dict[int, dict[str, Any]] = {}

    if words:
        clauses = []
        for word in words:
            like = f"{word.lower()}%"
            clauses.extend([User.first_name.ilike(like),
                            User.last_name.ilike(like),
                            User.username.ilike(f"%{word.lower()}%")])
        rows = session.execute(
            select(User).where(User.is_active.is_(True), or_(*clauses))
            .limit(60)).scalars()
        for row in rows:
            found[int(row.id)] = _person_row(row)

    # Everybody the plan already names, so "Priya is the escalation owner"
    # still resolves when the plan is being edited rather than written.
    named = _named_in(plan or {})
    missing = [uid for uid in named if uid not in found]
    if missing:
        rows = session.execute(
            select(User).where(User.id.in_(missing[:60]))).scalars()
        for row in rows:
            found[int(row.id)] = _person_row(row)
    return list(found.values())


def _name_candidates(message: str, limit: int = 20) -> list[str]:
    """The words in a message that could be somebody's name, best first.

    Ordered rather than truncated alphabetically: a cap applied to a sorted
    set drops "Priya" from a sentence that also mentions Draft, December and
    Committee, and the Copilot then reports that nobody by that name exists.
    A word capitalised in the middle of a sentence is the strongest signal
    there is, so those go first and the cap only ever bites on the weak tail.
    """
    tokens = list(re.finditer(r"[A-Za-z][\w'’.\-]*", str(message or "")))
    strong: list[str] = []
    weak: list[str] = []
    for index, token in enumerate(tokens):
        # A name at the end of a sentence carries the full stop with it, and
        # `ilike 'rohan.%'` matches nobody — which reads as "there is no such
        # person" rather than as the punctuation bug it is.
        word = token.group(0).strip(".-'’")
        if word.lower() in _NOT_A_NAME or len(word) < 2:
            continue
        # Capitalised, and not merely the first word of a sentence.
        opener = index == 0 or str(message)[:token.start()].rstrip().endswith(
            (".", "!", "?", "\n"))
        bucket = weak if (not word[0].isupper() or opener) else strong
        if word not in bucket:
            bucket.append(word)
    return (strong + [w for w in weak if w not in strong])[:limit]


def _person_row(row: Any) -> dict[str, Any]:
    return {"user_id": int(row.id),
            "name": " ".join(p for p in (row.first_name, row.last_name) if p)
                    or row.username,
            "username": row.username, "role": row.role}


def _named_in(plan: dict[str, Any]) -> list[int]:
    found: set[int] = set()
    governance = plan.get("governance") or {}
    for key in ("sponsor_id", "manager_id", "owner_id", "escalation_id"):
        if governance.get(key):
            found.add(int(governance[key]))
    for row in [*(plan.get("milestones") or []), *(plan.get("tasks") or [])]:
        for key in ("owner_id", "reviewer_id", "escalation_id"):
            if row.get(key):
                found.add(int(row[key]))
    return sorted(found)


def handlers(session: Any) -> dict[str, Any]:
    """Every tool id the Copilot may call, mapped to what actually runs.

    Assembled from the modules that own each capability — reads from
    `agent.py`, the three conversational writes from `actions.py`, the draft
    flow from `draft.py` — rather than reimplemented here. This module decides
    WHO may call WHAT; it is not a fourth place where planner behaviour lives.
    """
    from backend.planner import actions as planner_actions
    from backend.planner import agent as planner_agent
    from backend.planner import draft as planner_draft

    found: dict[str, Any] = {}
    found.update(planner_agent.handlers(session))
    found.update(planner_actions.handlers(session))

    def start(principal=None, **kw):
        row = planner_draft.create(session, principal,
                                   name=str(kw.get("name") or ""),
                                   source=_source())
        return planner_draft.to_dict(row)

    def read(principal=None, draft=None, **_kw):
        row = planner_draft.load(session, principal, str(draft or ""))
        found_plan = row.plan or planner_draft.empty()
        return {**planner_draft.to_dict(row),
                "completeness": planner_draft.check(found_plan).to_dict(),
                "catalogue": planner_draft.catalogue(found_plan)}

    def apply(principal=None, draft=None, command=None, **kw):
        payload = kw.get("payload")
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise ValueError(
                    "The change was not expressed in a form I could read."
                ) from exc
        expected = kw.get("expected_version")
        return planner_draft.apply(
            session, principal, str(draft or ""), str(command or ""),
            dict(payload or {}),
            expected_version=int(expected) if expected not in (None, "")
            else None,
            source=_source())

    def link(principal=None, draft=None, predecessor=None, successor=None,
             **kw):
        row = planner_draft.load(session, principal, str(draft or ""))
        return planner_draft.link_preview(
            row.plan or planner_draft.empty(),
            str(predecessor or ""), str(successor or ""),
            dependency_type=str(kw.get("dependency_type") or "FS"),
            lag_days=int(kw.get("lag_days") or 0))

    def whole(principal=None, draft=None, **_kw):
        row = planner_draft.load(session, principal, str(draft or ""))
        return planner_draft.preview(row.plan or planner_draft.empty())

    found.update({
        reg.PLANNER_DRAFT_START: start,
        reg.PLANNER_DRAFT_READ: read,
        reg.PLANNER_DRAFT_APPLY: apply,
        reg.PLANNER_DRAFT_LINK_PREVIEW: link,
        reg.PLANNER_DRAFT_PREVIEW: whole,
        reg.PLANNER_PEOPLE: lambda principal=None, **kw: people(
            session, principal, search=str(kw.get("search") or ""),
            limit=int(kw.get("limit") or 20)),
    })
    # Every allowed tool has a handler, or the Copilot advertises a capability
    # that fails at the moment somebody uses it.
    missing = [t for t in ALLOWED_TOOLS if t not in found]
    if missing:  # pragma: no cover - a wiring error, caught by its own test
        logger.error("copilot tools with no handler: %s", ", ".join(missing))
    return {tool_id: handler for tool_id, handler in found.items()
            if tool_id in ALLOWED_TOOLS}


def confirm_publish(session: Any, principal: Any, key: str, *,
                    confirm: Any) -> Any:
    """Turn a draft into a project, on a person's explicit say-so.

    Called from the route the Publish button posts to, never from a tool.
    `confirm` has to be an actual affirmative from the request, so a model
    that decides the conversation amounted to agreement cannot create a
    project; and because there is no registered tool for this, a model cannot
    reach this function at all.
    """
    from backend.planner import draft as planner_draft

    if not _confirmed(confirm):
        raise NotConfirmed(
            "Publishing creates a real project that everybody named on it "
            "will see, so it needs the person to confirm it themselves.")
    return planner_draft.publish(session, principal, str(key or ""),
                                 source=_source())


def _source() -> str:
    """Everything the Copilot writes is marked as having come from the chat.

    §41: an update somebody typed and an update they asked the agent to make
    are different events, and the audit trail has to be able to tell them
    apart forever.
    """
    from backend.models.planner import SOURCE_AI_CHAT

    return SOURCE_AI_CHAT


def _confirmed(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "yes", "confirm",
                                                "confirmed", "publish", "1"}


# ------------------------------------------------------------------- calling


def call(session: Any, principal: Any, tool_id: str,
         parameters: dict[str, Any] | None = None) -> tuple[reg.Call, Any]:
    """Make one tool call as the Copilot, through the ordinary gate.

    The single entry point the chat turn uses. It cannot be persuaded to widen
    itself: the agent it passes to `reg.invoke` is the frozen one above, and
    the principal is whoever is signed in.
    """
    return reg.invoke(_AGENT, tool_id, dict(parameters or {}),
                      principal=principal, handlers=handlers(session))


def in_scope(session: Any, principal: Any, message: str) -> scope.Decision:
    """Whether the Copilot should answer this at all.

    Asked before a tool is chosen, and anchored against the names this person
    can actually see, so a project named after another part of the bank is
    still a project.
    """
    return scope.classify(message,
                          names=scope.names_in_reach(session, principal))


__all__ = ["AGENT_ID", "ALLOWED_DOMAINS", "ALLOWED_TOOLS", "BUSINESS_NAME",
           "COPILOT_VERSION", "Copilot", "NotConfirmed", "agent",
           "catalogue", "call", "confirm_publish", "handlers", "in_scope",
           "people", "people_for"]
