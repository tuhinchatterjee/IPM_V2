"""Findings, decisions and actions as governed objects. §6B, §6C, §27.

The boundary this module exists to hold
---------------------------------------
Claude may identify that a decision appears to be required, draft the
question, suggest a recommendation, explain the options, and draft an answer
to a finding. It may not record the committee's decision, impersonate the
decision maker, mark approval complete, close a formal finding or claim an
action was done.

That is not a convention anybody has to remember. Every formal act here goes
through one function, that function refuses a caller with no human name, and
the refusal is the same whether the caller is a router, a worker or a model.
`SYSTEM_ACTORS` names the identities that are never people, so a caller
cannot get past the guard by passing "system" as though it were a person.

Every formal state change writes an audit entry
-----------------------------------------------
Actor, timestamp, previous state, new state, reason. Appended, never
rewritten. §26 asks that no LLM be able to fake that trail; a single writer
that demands a person is how it is enforced rather than hoped.

Origin matters
--------------
A finding knows where it came from — a deterministic threshold rule, an
imported analysis, a validation result, change detection, an AI suggestion, a
person. An AI suggestion never silently becomes a formal blocker: only the
origins a document's own policy permits may raise a blocking finding on
creation, and anything else needs a person to make it blocking.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.models.playbook import (
    PlaybookAction,
    PlaybookDecision,
    PlaybookFinding,
)

# --------------------------------------------------------------------------
# Who may act
# --------------------------------------------------------------------------


class NotPermitted(ValueError):
    """A formal act attempted without the human actor it requires."""


class TransitionRefused(ValueError):
    """A state change that is not allowed, with the reason."""


#: Identities that are never a person. Passing one of these where an actor is
#: required is refused exactly as an empty string is — otherwise the guard
#: could be walked past by typing "system".
SYSTEM_ACTORS = frozenset({"system", "claude", "assistant", "ai", "bot",
                           "playbook", "creditprobe", "model"})


def require_person(actor: str, act: str) -> str:
    """The one gate. Returns the actor, or refuses and says why."""
    name = (actor or "").strip()
    if not name or name.lower() in SYSTEM_ACTORS:
        raise NotPermitted(
            f"{act} is a person's decision and records who made it. "
            "Nothing was changed.")
    return name[:160]


def _audit(row, *, field: str, before: str, after: str, actor: str,
           reason: str, act: str) -> None:
    """Append one entry. Never rewrites, never reorders."""
    row.history = list(row.history or []) + [{
        "at": datetime.now(UTC).isoformat(),
        "act": act, "field": field, "from": before, "to": after,
        "actor": actor, "reason": reason,
    }]


def _reference(session, model, workspace_id: int, prefix: str) -> str:
    """The next `F-01` / `D-01` / `A-01` for this document.

    A human reference, because that is how these objects are spoken about in a
    meeting: "F-03 is still open", "the actions from D-01". Per workspace and
    never reused, so a reference in a set of minutes still finds the right row
    a year later.

    Derived from what is already numbered rather than from a count, so deleting
    a finding does not make the next one collide with an existing reference.
    """
    highest = 0
    for (value,) in session.query(model.reference).filter(
            model.workspace_id == workspace_id).all():
        if value and value.startswith(f"{prefix}-"):
            try:
                highest = max(highest, int(value.split("-", 1)[1]))
            except ValueError:
                continue
    return f"{prefix}-{highest + 1:02d}"


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

OPEN, ANSWERED, ACCEPTED, CLOSED, DEFERRED = (
    "open", "answered", "accepted", "closed", "deferred")

FINDING_STATUSES = (OPEN, ANSWERED, ACCEPTED, CLOSED, DEFERRED)

#: A finding stops counting against a document once a PERSON has disposed of
#: it. "Answered" is not disposal: a drafted answer nobody stood behind is
#: still an open question, which is the distinction §6B turns on.
RESOLVED = frozenset({ACCEPTED, CLOSED, DEFERRED})

FINDING_MOVES: dict[str, frozenset[str]] = {
    OPEN: frozenset({ANSWERED, ACCEPTED, CLOSED, DEFERRED}),
    ANSWERED: frozenset({ACCEPTED, CLOSED, DEFERRED, OPEN}),
    ACCEPTED: frozenset({CLOSED, OPEN}),
    DEFERRED: frozenset({OPEN, ANSWERED, ACCEPTED, CLOSED}),
    CLOSED: frozenset({OPEN}),
}

HIGH, MEDIUM, LOW, INFORMATION = "high", "medium", "low", "information"
SEVERITIES = (HIGH, MEDIUM, LOW, INFORMATION)

#: Where a finding came from. Always explicit — a reader deciding how much
#: weight to give a finding needs to know whether a rule computed it or a
#: model suggested it.
FROM_RULE = "rule"
FROM_IMPORT = "import"
FROM_VALIDATION = "validation"
FROM_CHANGE = "change_detection"
FROM_AI = "ai_suggestion"
FROM_HUMAN = "human"

ORIGINS = (FROM_RULE, FROM_IMPORT, FROM_VALIDATION, FROM_CHANGE, FROM_AI,
           FROM_HUMAN)

ORIGIN_LABELS = {
    FROM_RULE: "Threshold rule",
    FROM_IMPORT: "Imported analysis",
    FROM_VALIDATION: "Validation result",
    FROM_CHANGE: "Change since last time",
    FROM_AI: "Suggested by Claude",
    FROM_HUMAN: "Raised by a person",
}

#: Which origins may raise a BLOCKING finding without a person saying so.
#: Deterministic sources only: a rule that fired, a validation that failed, a
#: movement that breached a stated threshold. A model's suggestion and an
#: imported third-party finding may be blocking only once a person makes them
#: so — that is §6B's "AI-generated findings must never silently become formal
#: blockers".
MAY_AUTO_BLOCK = frozenset({FROM_RULE, FROM_VALIDATION, FROM_CHANGE})


def raise_finding(session, workspace_id: int, *, title: str, origin: str,
                  severity: str = INFORMATION, actor: str = "",
                  blocking: bool = False, **fields) -> PlaybookFinding:
    """Record a finding, from whichever origin found it.

    A human-raised finding needs a person. A rule-raised one does not — a
    threshold that fired is not somebody's opinion — but it may only be
    blocking if its origin is allowed to be, and the downgrade is recorded
    rather than silent.
    """
    if origin not in ORIGINS:
        raise TransitionRefused(
            f"{origin!r} is not a finding origin. Expected one of: "
            + ", ".join(ORIGINS))
    if severity not in SEVERITIES:
        raise TransitionRefused(
            f"{severity!r} is not a severity. Expected one of: "
            + ", ".join(SEVERITIES))
    if origin == FROM_HUMAN:
        actor = require_person(actor, "Raising a finding by hand")

    downgraded = ""
    if blocking and origin not in MAY_AUTO_BLOCK:
        blocking = False
        downgraded = (f"raised as blocking by {ORIGIN_LABELS[origin]}, which "
                      "may not set that on its own; a person must make it "
                      "blocking")

    fields.setdefault("reference",
                      _reference(session, PlaybookFinding, workspace_id, "F"))
    row = PlaybookFinding(
        workspace_id=workspace_id, title=title[:400], severity=severity,
        status=OPEN, raised_by=origin, blocking=blocking,
        **{k: v for k, v in fields.items() if v is not None})
    session.add(row)
    session.flush()
    _audit(row, field="status", before="", after=OPEN,
           actor=actor or "system", act="raised",
           reason=downgraded or f"raised from {ORIGIN_LABELS[origin]}")
    session.flush()
    return row


def draft_answer(session, finding: PlaybookFinding, *, answer: str
                 ) -> PlaybookFinding:
    """Claude drafts. The finding does NOT move status.

    This is the whole point of separating drafting from accepting: a drafted
    answer is visible, reviewable and attributable to the model, and it
    changes nothing about whether the finding is disposed of.
    """
    finding.answer = answer
    finding.answered_by = ""
    finding.answered_at = None
    _audit(finding, field="answer", before="", after="drafted",
           actor="claude", act="drafted_answer",
           reason="drafted for review; not accepted")
    session.flush()
    return finding


def move_finding(session, finding: PlaybookFinding, *, to: str, actor: str,
                 reason: str = "", answer: str = "",
                 resolution: str = "") -> PlaybookFinding:
    """Answer, accept, close, defer or reopen a finding. A person, always.

    Deferring and closing both require a rationale: "closed" with no reason
    is the state a governed document can least afford, because next quarter
    nobody can tell whether it was handled or forgotten.
    """
    if to not in FINDING_STATUSES:
        raise TransitionRefused(
            f"{to!r} is not a finding status. Expected one of: "
            + ", ".join(FINDING_STATUSES))
    current = finding.status or OPEN
    if to == current:
        return finding
    if to not in FINDING_MOVES.get(current, frozenset()):
        raise TransitionRefused(
            f"A finding that is {current!r} cannot become {to!r}. From "
            f"{current!r} it may become: "
            + ", ".join(sorted(FINDING_MOVES.get(current, frozenset()))) + ".")

    who = require_person(actor, f"Moving a finding to {to!r}")
    if to in (CLOSED, DEFERRED) and not (reason or resolution).strip():
        raise TransitionRefused(
            f"{to.capitalize()} needs a rationale. Nothing was changed.")

    now = datetime.now(UTC)
    if to == ANSWERED:
        if answer:
            finding.answer = answer
        if not (finding.answer or "").strip():
            raise TransitionRefused(
                "A finding is answered with an answer. Nothing was changed.")
        finding.answered_by = who
        finding.answered_at = now
    if to in RESOLVED:
        finding.resolution = resolution or reason or finding.resolution
        finding.resolved_by = who
        finding.resolved_at = now
    if to == OPEN:
        finding.resolved_by, finding.resolved_at = "", None

    _audit(finding, field="status", before=current, after=to, actor=who,
           act=to, reason=reason or resolution)
    finding.status = to
    session.flush()
    return finding


def set_blocking(session, finding: PlaybookFinding, *, blocking: bool,
                 actor: str, reason: str = "") -> PlaybookFinding:
    """Make a finding block approval, or stop it blocking. A person's call."""
    who = require_person(actor, "Changing whether a finding blocks approval")
    before = "blocking" if finding.blocking else "not blocking"
    after = "blocking" if blocking else "not blocking"
    if before == after:
        return finding
    _audit(finding, field="blocking", before=before, after=after, actor=who,
           act="set_blocking", reason=reason)
    finding.blocking = blocking
    session.flush()
    return finding


def assign_finding(session, finding: PlaybookFinding, *, owner: str,
                   actor: str) -> PlaybookFinding:
    who = require_person(actor, "Assigning a finding")
    if not (owner or "").strip():
        raise TransitionRefused(
            "A finding is owned by a named person. Nothing was changed.")
    before, finding.owner = finding.owner, owner.strip()[:160]
    _audit(finding, field="owner", before=before, after=finding.owner,
           actor=who, act="assigned", reason="")
    session.flush()
    return finding


def attach_evidence(session, finding: PlaybookFinding, *, actor: str,
                    locator: str = "", metric_id: str = "",
                    previous_value: str = "", current_value: str = "",
                    delta: str = "", note: str = "") -> PlaybookFinding:
    """Point a finding at what it rests on.

    A finding that says a number moved is worth arguing with only if it says
    where the numbers came from. Attaching evidence is a person's act, not
    because it changes a status but because it changes what a reader is being
    asked to believe, and the audit has to name who asked.

    Nothing here is recomputed. The values are recorded as the caller read
    them, so the finding still reads correctly after the data moves on.
    """
    who = require_person(actor, "Attaching evidence to a finding")
    if not any(v.strip() for v in
               (locator, metric_id, previous_value, current_value, delta)):
        raise TransitionRefused(
            "Attaching evidence needs some evidence. Nothing was changed.")

    before = finding.source_locator or ""
    for field, value, limit in (("source_locator", locator, 400),
                                ("metric_id", metric_id, 160),
                                ("previous_value", previous_value, 64),
                                ("current_value", current_value, 64),
                                ("delta", delta, 64)):
        if value.strip():
            setattr(finding, field, value.strip()[:limit])

    _audit(finding, field="evidence", before=before,
           after=finding.source_locator or finding.metric_id, actor=who,
           act="evidence_attached", reason=note)
    session.flush()
    return finding


def unresolved(findings: list[PlaybookFinding]) -> list[PlaybookFinding]:
    """Findings still counting against the document.

    Open AND answered-but-not-accepted. A drafted answer nobody stood behind
    does not dispose of anything.
    """
    return [f for f in findings if (f.status or OPEN) not in RESOLVED]


def blocking_unresolved(findings: list[PlaybookFinding]
                        ) -> list[PlaybookFinding]:
    return [f for f in unresolved(findings) if f.blocking]


# --------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------

PROPOSED, READY_FOR_DECISION, DECIDED, DECISION_DEFERRED, WITHDRAWN = (
    "proposed", "ready_for_decision", "decided", "deferred", "withdrawn")

DECISION_STATUSES = (PROPOSED, READY_FOR_DECISION, DECIDED,
                     DECISION_DEFERRED, WITHDRAWN)

DECISION_MOVES: dict[str, frozenset[str]] = {
    PROPOSED: frozenset({READY_FOR_DECISION, WITHDRAWN}),
    READY_FOR_DECISION: frozenset({DECIDED, DECISION_DEFERRED, PROPOSED,
                                   WITHDRAWN}),
    DECISION_DEFERRED: frozenset({READY_FOR_DECISION, WITHDRAWN}),
    DECIDED: frozenset(),
    WITHDRAWN: frozenset({PROPOSED}),
}

APPROVE, REJECT, MODIFY, DEFER = "approve", "reject", "modify", "defer"
OUTCOMES = (APPROVE, REJECT, MODIFY, DEFER)


def propose_decision(session, workspace_id: int, *, question: str,
                     recommendation: str = "", options: list | None = None,
                     drafted_by_claude: bool = False,
                     actor: str = "", **fields) -> PlaybookDecision:
    """Put a decision on the paper. Claude may draft this one.

    Drafting the question, the recommendation and the options is analysis.
    It produces a PROPOSED decision, which is a request for a person's
    attention and is not a decision.
    """
    fields.setdefault("reference",
                      _reference(session, PlaybookDecision, workspace_id, "D"))
    row = PlaybookDecision(
        workspace_id=workspace_id, question=question,
        recommendation=recommendation, options=list(options or OUTCOMES),
        status=PROPOSED,
        **{k: v for k, v in fields.items() if v is not None})
    session.add(row)
    session.flush()
    _audit(row, field="status", before="", after=PROPOSED,
           actor="claude" if drafted_by_claude else (actor or "system"),
           act="proposed",
           reason="drafted for the committee" if drafted_by_claude
           else "proposed")
    session.flush()
    return row


def move_decision(session, decision: PlaybookDecision, *, to: str, actor: str,
                  reason: str = "") -> PlaybookDecision:
    """Move a decision short of deciding it. `record` does that separately."""
    if to not in DECISION_STATUSES:
        raise TransitionRefused(
            f"{to!r} is not a decision status. Expected one of: "
            + ", ".join(DECISION_STATUSES))
    if to == DECIDED:
        raise TransitionRefused(
            "A decision is recorded with its outcome and its decision maker. "
            "Use `record`. Nothing was changed.")
    current = decision.status or PROPOSED
    if to == current:
        return decision
    if to not in DECISION_MOVES.get(current, frozenset()):
        raise TransitionRefused(
            f"A decision that is {current!r} cannot become {to!r}. From "
            f"{current!r} it may become: "
            + ", ".join(sorted(DECISION_MOVES.get(current, frozenset())))
            + ".")
    who = require_person(actor, f"Moving a decision to {to!r}")
    if to in (DECISION_DEFERRED, WITHDRAWN) and not (reason or "").strip():
        raise TransitionRefused(
            f"{to.capitalize()} needs a rationale. Nothing was changed.")
    _audit(decision, field="status", before=current, after=to, actor=who,
           act=to, reason=reason)
    decision.status = to
    session.flush()
    return decision


def record(session, decision: PlaybookDecision, *, outcome: str, actor: str,
           rationale: str = "", meeting: str = "") -> PlaybookDecision:
    """A person records what the committee decided.

    The one act in this module a model may never perform under any
    circumstance, and the reason `SYSTEM_ACTORS` exists: a decision attributed
    to "system" is not a decision, it is a record nobody can be held to.
    """
    if outcome not in OUTCOMES:
        raise TransitionRefused(
            f"{outcome!r} is not a decision outcome. Expected one of: "
            + ", ".join(OUTCOMES))
    current = decision.status or PROPOSED
    if current == DECIDED:
        raise TransitionRefused(
            "This decision has already been recorded. Nothing was changed.")
    if current != READY_FOR_DECISION:
        raise TransitionRefused(
            f"A decision that is {current!r} is not ready to be taken. "
            "Move it to 'ready_for_decision' first. Nothing was changed.")
    who = require_person(actor, "Recording a committee decision")

    decision.outcome = outcome
    decision.decided_by = who
    decision.decided_at = datetime.now(UTC)
    if rationale:
        decision.rationale = rationale
    if meeting:
        decision.meeting = meeting[:160]
    _audit(decision, field="status", before=current, after=DECIDED, actor=who,
           act="recorded", reason=rationale or outcome)
    decision.status = DECIDED
    session.flush()
    return decision


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

ACTION_OPEN, IN_PROGRESS, ACTION_BLOCKED, COMPLETED, CANCELLED = (
    "open", "in_progress", "blocked", "completed", "cancelled")

ACTION_STATUSES = (ACTION_OPEN, IN_PROGRESS, ACTION_BLOCKED, COMPLETED,
                   CANCELLED)

ACTION_MOVES: dict[str, frozenset[str]] = {
    ACTION_OPEN: frozenset({IN_PROGRESS, ACTION_BLOCKED, COMPLETED,
                            CANCELLED}),
    IN_PROGRESS: frozenset({ACTION_BLOCKED, COMPLETED, CANCELLED,
                            ACTION_OPEN}),
    ACTION_BLOCKED: frozenset({IN_PROGRESS, ACTION_OPEN, CANCELLED,
                               COMPLETED}),
    COMPLETED: frozenset({ACTION_OPEN}),
    CANCELLED: frozenset({ACTION_OPEN}),
}

#: An action still owed. Completed and cancelled are done; the rest are not.
ACTION_OUTSTANDING = frozenset({ACTION_OPEN, IN_PROGRESS, ACTION_BLOCKED})


def create_action(session, workspace_id: int, *, title: str, actor: str = "",
                  decision: PlaybookDecision | None = None,
                  finding: PlaybookFinding | None = None,
                  **fields) -> PlaybookAction:
    """Raise an action, usually from a decision that has been taken."""
    fields.setdefault("reference",
                      _reference(session, PlaybookAction, workspace_id, "A"))
    row = PlaybookAction(
        workspace_id=workspace_id, title=title[:400], status=ACTION_OPEN,
        decision_id=decision.id if decision else None,
        finding_id=finding.id if finding else None,
        **{k: v for k, v in fields.items() if v is not None})
    session.add(row)
    session.flush()
    source = ("decision " + (decision.reference or str(decision.id))
              if decision else
              "finding " + (finding.reference or str(finding.id))
              if finding else "raised directly")
    _audit(row, field="status", before="", after=ACTION_OPEN,
           actor=(actor or "system"), act="created", reason=f"from {source}")
    session.flush()
    return row


def actions_from_decision(session, decision: PlaybookDecision, *,
                          actions: list[dict], actor: str
                          ) -> list[PlaybookAction]:
    """Create the work a recorded decision implies.

    Refused before the decision is taken: actions that exist because of a
    decision nobody made are how a committee pack ends up describing work
    that was never authorised.
    """
    who = require_person(actor, "Creating actions from a decision")
    if (decision.status or PROPOSED) != DECIDED:
        raise TransitionRefused(
            "Actions follow a decision that has been recorded. "
            "Nothing was changed.")
    return [create_action(session, decision.workspace_id, actor=who,
                          decision=decision, **spec) for spec in actions]


def move_action(session, action: PlaybookAction, *, to: str, actor: str,
                note: str = "") -> PlaybookAction:
    """Move an action. Completing one says who completed it."""
    if to not in ACTION_STATUSES:
        raise TransitionRefused(
            f"{to!r} is not an action status. Expected one of: "
            + ", ".join(ACTION_STATUSES))
    current = action.status or ACTION_OPEN
    if to == current:
        return action
    if to not in ACTION_MOVES.get(current, frozenset()):
        raise TransitionRefused(
            f"An action that is {current!r} cannot become {to!r}. From "
            f"{current!r} it may become: "
            + ", ".join(sorted(ACTION_MOVES.get(current, frozenset()))) + ".")
    who = require_person(actor, f"Moving an action to {to!r}")
    if to == CANCELLED and not (note or "").strip():
        raise TransitionRefused(
            "Cancelling an action needs a reason. Nothing was changed.")

    now = datetime.now(UTC)
    if to == COMPLETED:
        action.completed_by = who
        action.completed_at = now
    elif current == COMPLETED:
        action.completed_by, action.completed_at = "", None
    if note:
        action.last_update = note
        action.last_update_at = now
        action.notes = list(action.notes or []) + [
            {"at": now.isoformat(), "actor": who, "note": note}]
    _audit(action, field="status", before=current, after=to, actor=who,
           act=to, reason=note)
    action.status = to
    session.flush()
    return action


def update_action(session, action: PlaybookAction, *, note: str,
                  actor: str) -> PlaybookAction:
    """An owner says where an action stands, without moving it."""
    who = require_person(actor, "Updating an action")
    if not (note or "").strip():
        raise TransitionRefused("An update needs something to say.")
    now = datetime.now(UTC)
    action.last_update = note
    action.last_update_at = now
    action.notes = list(action.notes or []) + [
        {"at": now.isoformat(), "actor": who, "note": note}]
    _audit(action, field="update", before="", after="noted", actor=who,
           act="updated", reason=note)
    session.flush()
    return action


def overdue(actions: list[PlaybookAction], *, today=None) -> list:
    today = today or datetime.now(UTC).date()
    return [a for a in actions
            if a.due_date and a.due_date < today
            and (a.status or ACTION_OPEN) in ACTION_OUTSTANDING]


# --------------------------------------------------------------------------
# The planner seam
# --------------------------------------------------------------------------
#
# A clean contract and nothing more. Playbook is whole without a planner; a
# planner, when one exists, owns execution and reports status back. Nothing
# in this module imports it, checks for it, or behaves differently when it is
# absent.

PLANNER = "project_planner"


def export_payload(action: PlaybookAction) -> dict:
    """What a planner would need to take this action on. Read-only."""
    return {
        "source": "playbook",
        "workspace_id": action.workspace_id,
        "action_reference": action.reference or str(action.id),
        "title": action.title,
        "description": action.description,
        "owner": action.owner,
        "due_date": action.due_date.isoformat() if action.due_date else "",
        "status": action.status,
        "from_decision": action.decision_id,
        "from_finding": action.finding_id,
    }


def record_export(session, action: PlaybookAction, *, system: str,
                  external_ref: str, actor: str) -> PlaybookAction:
    """Note that an action now lives somewhere else too."""
    who = require_person(actor, "Exporting an action")
    action.external_system = system[:48]
    action.external_ref = external_ref[:160]
    action.external_synced_at = datetime.now(UTC)
    _audit(action, field="external_ref", before="", after=external_ref,
           actor=who, act="exported", reason=f"exported to {system}")
    session.flush()
    return action


def read_back(session, action: PlaybookAction, *, external_status: str,
              note: str = "") -> PlaybookAction:
    """What the external system says. Recorded, never trusted as our own.

    The external status is kept in its own column and does NOT move
    `action.status`: a planner saying "done" is evidence, and a person here
    still decides whether this action is complete. That keeps the audit
    truthful when the two systems disagree.
    """
    action.external_status = external_status[:48]
    action.external_synced_at = datetime.now(UTC)
    _audit(action, field="external_status", before="", after=external_status,
           actor=action.external_system or PLANNER, act="read_back",
           reason=note or "status read back from the external system")
    session.flush()
    return action
