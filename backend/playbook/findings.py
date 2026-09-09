"""Material observations: reading them, answering them, and refusing to bury
one.

A finding is raised by a declared materiality rule against a governed figure —
never by a model deciding something looks important. `backend.playbook.
materiality` does the raising; this module is what a person does about it
afterwards.

Answering a finding is the pivot of the whole cycle. A pack cannot reach
approval with a serious finding nobody has responded to, so the honest paths
out are:

  ACKNOWLEDGED   somebody has seen it and owns it
  EXPLAINED      there is a management response on the record
  ACTIONED       an action was raised, and the action is the answer
  RESOLVED       the underlying condition has gone away
  DISMISSED      it is not material after all, and here is why

Only the last one removes a finding from the committee's view, which is why it
is the one that demands a written reason and refuses an AI-sourced grant. §8.4
is explicit: an assistant may never suppress a finding. It cannot do so here
even holding OWNER access, because the refusal is on the operation rather than
on the rank.

Severity is not editable. It comes from the rule that fired, and a finding
whose severity a person could turn down is a finding that stops meaning
anything.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.models.playbook import (
    FINDING_STATUSES,
    SEVERITIES,
    SEVERITY_RANK,
    SOURCE_UI,
    PlaybookFinding,
    PlaybookSnapshot,
)
from backend.playbook import access, readiness, service
from backend.playbook.access import CONTRIBUTOR, REVIEWER
from backend.playbook.service import InvalidPlaybook, record

logger = logging.getLogger(__name__)

#: Statuses that mean the committee has an answer on the record. Kept in step
#: with `readiness.FINDING_ANSWERED`, which decides whether a pack may go for
#: approval — the same list read for two purposes, asserted equal in the tests
#: so the two cannot drift into disagreeing about what "answered" means.
ANSWERED = frozenset({"ACKNOWLEDGED", "EXPLAINED", "ACTIONED", "RESOLVED",
                      "DISMISSED"})

#: Answers that need words. Saying a finding is explained without saying what
#: the explanation is leaves the pack asserting that somebody dealt with it.
NEEDS_RESPONSE = frozenset({"EXPLAINED"})

#: The one status that takes a finding off the committee's list. It needs a
#: reason, and no agent may set it.
DISMISSAL = "DISMISSED"


def findings(session: Any, principal: Any, *, pack_id: int | None = None,
             committee_id: int | None = None, status: str | None = None,
             severity: str | None = None, open_only: bool = False,
             source: str = SOURCE_UI) -> list[dict[str, Any]]:
    """What has been raised, most serious first.

    Ordered by severity rather than by when it was raised: a committee reading
    a list of findings wants the critical one at the top, not the oldest one.
    """
    if pack_id is not None:
        pack, _ = access.readable_pack(session, pack_id, principal, source)
        query = select(PlaybookFinding).where(
            PlaybookFinding.pack_id == int(pack.id))
    elif committee_id is not None:
        access.committee_grant(session, committee_id, principal, source)
        readable = access.readable_pack_ids(session, principal,
                                            committee_id=int(committee_id))
        if not readable:
            return []
        query = select(PlaybookFinding).where(
            PlaybookFinding.pack_id.in_(readable))
    else:
        readable = access.readable_pack_ids(session, principal)
        if not readable:
            return []
        query = select(PlaybookFinding).where(
            PlaybookFinding.pack_id.in_(readable))

    if status:
        _one_of(status, FINDING_STATUSES, "finding status")
        query = query.where(PlaybookFinding.status == status.upper())
    if severity:
        _one_of(severity, SEVERITIES, "severity")
        query = query.where(PlaybookFinding.severity == severity.upper())
    if open_only:
        query = query.where(PlaybookFinding.status.notin_(tuple(ANSWERED)))

    rows = list(session.execute(query).scalars())
    rows.sort(key=lambda r: (-SEVERITY_RANK.get(str(r.severity), 0),
                             -int(r.id)))
    return [_dict(session, r) for r in rows]


def finding(session: Any, finding_id: int, principal: Any, *,
            source: str = SOURCE_UI) -> dict[str, Any]:
    """One finding, with the figure it was raised against."""
    row, _, _ = access.visible_finding(session, finding_id, principal, source)
    return _dict(session, row)


def respond(session: Any, finding_id: int, principal: Any, *, status: str,
            response: str = "", owner_id: int | None = None,
            reason: str = "", source: str = SOURCE_UI) -> dict[str, Any]:
    """Answer a finding, in one of the ways a committee actually answers one.

    `reason` is only read for a dismissal, and is required for one. Everything
    else is recorded on the pack's history with who said it and through which
    door, so "who signed this off" is answerable a year later.
    """
    row, pack, grant = access.visible_finding(session, finding_id, principal,
                                              source)
    _one_of(status, FINDING_STATUSES, "finding status")
    wanted = status.upper()

    # CONTRIBUTOR to answer one; a dismissal needs a reviewer, because taking
    # something off the committee's list is a judgement about materiality
    # rather than a piece of pack authoring.
    needed = REVIEWER if wanted == DISMISSAL else CONTRIBUTOR
    what = ("dismiss a finding on this pack" if wanted == DISMISSAL
            else "answer a finding on this pack")
    if not grant.at_least(needed):
        raise access.PackDenied(
            f"You need {needed.lower()} access on this committee to {what}. "
            f"You have {grant.access.lower()}.")
    access.assert_editable(pack)

    if wanted == DISMISSAL:
        # Not a rank check. An agent holding OWNER on a committee still cannot
        # reach this, because burying an observation is not a thing software
        # decides.
        access.refuse_ai(grant, "dismiss_finding")
        if not str(reason or "").strip():
            raise InvalidPlaybook(
                "Dismissing a finding needs a reason. It is the one answer "
                "that takes something off the committee's list, and a reader "
                "six months from now has to be able to see why.")
    if wanted in NEEDS_RESPONSE and not str(response or "").strip():
        raise InvalidPlaybook(
            f"Marking a finding {wanted.lower()} needs the explanation "
            "itself. Without it the pack says somebody dealt with this and "
            "does not say how.")

    was = str(row.status)
    changes: dict[str, list] = {}
    if was != wanted:
        changes["status"] = [was, wanted]
    row.status = wanted
    if response:
        if str(row.response or "") != response:
            changes["response"] = [str(row.response or ""), response]
        row.response = response
    if owner_id is not None:
        if not service._user_exists(session, int(owner_id)):
            raise InvalidPlaybook(f"There is no user {owner_id}.")
        if row.owner_id != int(owner_id):
            changes["owner_id"] = [row.owner_id, int(owner_id)]
        row.owner_id = int(owner_id)
    if wanted == DISMISSAL:
        row.dismissed_reason = reason
        row.dismissed_by = grant.user_id
        row.dismissed_at = datetime.now(UTC)
        changes["dismissed_reason"] = [None, reason]
    row.updated_at = datetime.now(UTC)
    session.flush()

    if changes:
        record(session, entity_type="finding", action="answered", pack=pack,
               entity_id=int(row.id), entity_ref=str(row.finding_type),
               changes=changes, narrative=_narrative(row, was, wanted, reason),
               grant=grant)
        readiness.refresh(session, pack)
    return _dict(session, row)


def _narrative(row: Any, was: str, now: str, reason: str) -> str:
    title = str(row.title)
    if now == DISMISSAL:
        return (f"“{title}” was dismissed as not material. Reason given: "
                f"{reason}")
    return f"“{title}” moved from {was.lower()} to {now.lower()}."


def reopen(session: Any, finding_id: int, principal: Any, *, why: str,
           source: str = SOURCE_UI) -> dict[str, Any]:
    """Put an answered finding back on the list.

    Kept separate from `respond` because it is the opposite motion and should
    read that way in the history: somebody has decided the answer given was
    not good enough. A dismissal that is reopened keeps its dismissal reason
    on the record rather than erasing it — the point is that both are visible.
    """
    row, pack, grant = access.visible_finding(session, finding_id, principal,
                                              source)
    if not grant.at_least(REVIEWER):
        raise access.PackDenied(
            "You need reviewer access on this committee to reopen a finding. "
            f"You have {grant.access.lower()}.")
    access.assert_editable(pack)
    if not str(why or "").strip():
        raise InvalidPlaybook(
            "Reopening a finding needs a reason — it contradicts an answer "
            "somebody already gave.")
    was = str(row.status)
    if was == "OPEN":
        raise InvalidPlaybook(f"“{row.title}” is already open.")

    row.status = "OPEN"
    row.updated_at = datetime.now(UTC)
    session.flush()
    record(session, entity_type="finding", action="reopened", pack=pack,
           entity_id=int(row.id), entity_ref=str(row.finding_type),
           changes={"status": [was, "OPEN"]},
           narrative=f"“{row.title}” was reopened. {why}", grant=grant)
    readiness.refresh(session, pack)
    return _dict(session, row)


def _one_of(value: Any, allowed: Any, what: str) -> None:
    if str(value).upper() not in allowed:
        raise InvalidPlaybook(
            f"'{value}' is not a {what}. One of: {', '.join(allowed)}.")


def _dict(session: Any, row: Any) -> dict[str, Any]:
    figure = None
    if row.snapshot_id is not None:
        snapshot = session.get(PlaybookSnapshot, int(row.snapshot_id))
        if snapshot is not None:
            figure = {
                "metric_id": str(snapshot.metric_id),
                "period": str(snapshot.period),
                "display_value": str(snapshot.display_value),
                "availability": str(snapshot.availability),
            }
    return {
        "id": int(row.id), "pack_id": int(row.pack_id),
        "section_id": row.section_id,
        "finding_type": str(row.finding_type),
        "severity": str(row.severity), "title": str(row.title),
        "description": str(row.description or ""),
        # What makes it challengeable: the rule that fired and the numbers it
        # fired on, carried to the screen rather than summarised away.
        "factual_basis": str(row.factual_basis or ""),
        "rule_key": str(row.rule_key or ""),
        "rule_detail": dict(row.rule_detail or {}),
        "metric_id": str(row.metric_id or ""), "period": str(row.period or ""),
        "figure": figure,
        "status": str(row.status), "answered": str(row.status) in ANSWERED,
        "owner_id": row.owner_id, "response": str(row.response or ""),
        "dismissed_reason": str(row.dismissed_reason or ""),
        "dismissed_by": row.dismissed_by,
        "dismissed_at": (row.dismissed_at.isoformat()
                         if row.dismissed_at else None),
        "source": str(row.source),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


__all__ = ["ANSWERED", "DISMISSAL", "NEEDS_RESPONSE", "finding", "findings",
           "reopen", "respond"]
