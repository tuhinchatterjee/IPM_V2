"""What an assistant may do to a committee pack, and what it may not.

Ten read tools and three writers. The asymmetry is the design: an agent that
can answer "what is blocking the March pack" is worth having, and an agent that
can approve it is not something this product will ever ship.

The three writers, and why each one is safe
--------------------------------------------
    playbook_draft_commentary   writes prose about figures the pack already
                                holds, grounded against them, landing as an
                                UNACCEPTED draft nobody has signed
    playbook_refresh_figures    recalculates the governed figures in a draft
                                pack — the same operation a person clicks, and
                                one that produces no new claims
    playbook_draft_action       writes an action into DRAFT, where it stays
                                until a person opens it

None of the three can produce something a committee reads without a person
having handled it in between. That is the property, and it is enforced in the
service functions rather than here, so a tool added later cannot get past it.

What has no tool
----------------
Approving, publishing, recording a review, deciding, closing an action,
dismissing a finding, moving a committed meeting date, editing a formula and
editing an approved pack. Registered in `NO_TOOL_EXISTS` so an auditor can read
the list, and refused inside the service by `access.refuse_ai` so the
prohibition does not depend on the registry being correct.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from backend.models.playbook import SOURCE_AI, PlaybookPack
from backend.playbook import access, actions, monitor, narrative, readiness
from backend.playbook import service as pb

logger = logging.getLogger(__name__)

AGENT_VERSION = "playbook-agent-1.0.0"

# --------------------------------------------------------------- tool ids

PLAYBOOK_COMMITTEES = "playbook_committees"
PLAYBOOK_PACK = "playbook_pack"
PLAYBOOK_READINESS = "playbook_readiness"
PLAYBOOK_FIGURES = "playbook_figures"
PLAYBOOK_FINDINGS = "playbook_findings"
PLAYBOOK_DECISIONS = "playbook_decisions"
PLAYBOOK_ACTIONS = "playbook_actions"
PLAYBOOK_HISTORY = "playbook_history"
PLAYBOOK_COMPARE = "playbook_compare"
PLAYBOOK_CHASE_LIST = "playbook_chase_list"

PLAYBOOK_DRAFT_COMMENTARY = "playbook_draft_commentary"
PLAYBOOK_REFRESH_FIGURES = "playbook_refresh_figures"
PLAYBOOK_DRAFT_ACTION = "playbook_draft_action"

#: Operations an agent must never reach. Named to match
#: `access.AI_FORBIDDEN` exactly, so an auditor can check the two lists
#: against each other, and a test does.
FORBIDDEN: tuple[str, ...] = (
    "approve_pack",
    "approve_section",
    "publish_pack",
    "record_review",
    "decide",
    "close_action",
    "dismiss_finding",
    "change_meeting_date",
    "edit_formula",
    "edit_approved_pack",
    "delete_pack",
    "import_document",
    "delete_section",
)


def handlers(session: Any) -> dict[str, Any]:
    """The Playbook tools, bound to one session.

    Every handler takes `principal` and passes `source=SOURCE_AI` into the
    service, so the AI ceiling and the forbidden-operation checks apply on
    every call. A handler that forgot to pass it would be acting as the human,
    which is exactly the escalation this shape prevents — and it is prevented
    by the source being set HERE rather than by the tool being trusted to send
    one.
    """

    def committees(principal=None, **_: Any) -> dict[str, Any]:
        rows = pb.committees(session, principal, source=SOURCE_AI)
        return {"committees": rows, "count": len(rows)}

    def pack(principal=None, pack_id=None, code=None, **_: Any) -> dict[str, Any]:
        found = _pack_id(session, principal, pack_id, code)
        return pb.pack(session, found, principal, source=SOURCE_AI)

    def readiness_of(principal=None, pack_id=None, code=None,
                     **_: Any) -> dict[str, Any]:
        found = _pack_id(session, principal, pack_id, code)
        row, _ = access.readable_pack(session, found, principal, SOURCE_AI)
        state = readiness.assess(session, row)
        return {"pack_id": int(row.id), "code": str(row.code),
                **state.to_dict()}

    def figures(principal=None, pack_id=None, code=None,
                **_: Any) -> dict[str, Any]:
        """Every governed figure in the pack, with why any of them is absent.

        The one an agent uses to answer "what does the March pack say about
        the default rate". It reads the SNAPSHOTS, so the answer is the pack's
        answer rather than a fresh query that might disagree with the page.
        """
        from backend.models.playbook import PlaybookSection

        found = _pack_id(session, principal, pack_id, code)
        row, _ = access.readable_pack(session, found, principal, SOURCE_AI)
        sections = session.execute(
            select(PlaybookSection).where(PlaybookSection.pack_id == row.id)
            .order_by(PlaybookSection.position)).scalars().all()
        out = []
        for section in sections:
            evidence = narrative.evidence_for(session, row, section)
            if evidence:
                out.append({"section": str(section.title),
                            "section_id": int(section.id),
                            "figures": evidence})
        return {"pack_id": int(row.id), "code": str(row.code),
                "period": str(row.period), "sections": out}

    def findings(principal=None, pack_id=None, code=None, severity=None,
                 **_: Any) -> dict[str, Any]:
        from backend.models.playbook import SEVERITY_RANK, PlaybookFinding

        found = _pack_id(session, principal, pack_id, code)
        row, _ = access.readable_pack(session, found, principal, SOURCE_AI)
        rows = session.execute(
            select(PlaybookFinding)
            .where(PlaybookFinding.pack_id == row.id)).scalars().all()
        floor = SEVERITY_RANK.get(str(severity or "").upper(), 0)
        out = [{
            "id": int(f.id), "severity": str(f.severity),
            "type": str(f.finding_type), "title": str(f.title),
            "status": str(f.status), "basis": str(f.factual_basis),
            "rule": str(f.rule_key), "response": str(f.response),
        } for f in rows if SEVERITY_RANK.get(str(f.severity), 0) >= floor]
        out.sort(key=lambda f: -SEVERITY_RANK.get(f["severity"], 0))
        return {"pack_id": int(row.id), "findings": out, "count": len(out)}

    def decisions(principal=None, committee_id=None, pack_id=None,
                  status=None, **_: Any) -> dict[str, Any]:
        rows = actions.decisions(session, principal, committee_id=committee_id,
                                 pack_id=pack_id, status=status,
                                 source=SOURCE_AI)
        return {"decisions": rows, "count": len(rows)}

    def action_log(principal=None, committee_id=None, pack_id=None,
                   status=None, overdue=False, **_: Any) -> dict[str, Any]:
        rows = actions.actions(session, principal, committee_id=committee_id,
                               pack_id=pack_id, status=status,
                               overdue=bool(overdue), source=SOURCE_AI)
        return {"actions": rows, "count": len(rows)}

    def history(principal=None, pack_id=None, code=None, limit=50,
                **_: Any) -> dict[str, Any]:
        """Who changed what, and through which door.

        The tool that answers "why does this differ from what was circulated".
        """
        from backend.models.playbook import PlaybookEvent

        found = _pack_id(session, principal, pack_id, code)
        row, _ = access.readable_pack(session, found, principal, SOURCE_AI)
        rows = session.execute(
            select(PlaybookEvent).where(PlaybookEvent.pack_id == row.id)
            .order_by(PlaybookEvent.id.desc())
            .limit(max(1, min(200, int(limit))))).scalars().all()
        return {"pack_id": int(row.id), "events": [{
            "at": e.created_at.isoformat() if e.created_at else None,
            "entity": str(e.entity_type), "action": str(e.action),
            "ref": str(e.entity_ref), "by": e.author_id,
            "source": str(e.source), "version": e.at_version,
            "changes": dict(e.changes or {}), "narrative": str(e.narrative),
        } for e in rows], "count": len(rows)}

    def compare(principal=None, pack_id=None, code=None,
                **_: Any) -> dict[str, Any]:
        from backend.playbook import compare as engine

        found = _pack_id(session, principal, pack_id, code)
        return engine.against_previous(session, found, principal,
                                       source=SOURCE_AI)

    def chase_list(principal=None, committee_id=None,
                   **_: Any) -> dict[str, Any]:
        """What the sweep WOULD send. A dry run, so nothing is delivered.

        An agent asked "who is holding up the March pack" answers from this
        rather than by sending anybody anything.
        """
        if committee_id is not None:
            access.committee_grant(session, committee_id, principal,
                                   SOURCE_AI)
            wanted = [int(committee_id)]
        else:
            wanted = access.readable_committee_ids(session, principal)
        if not wanted:
            return {"outstanding": [], "count": 0}
        outstanding = []
        for one in wanted:
            result = monitor.sweep(session, committee_id=one, dry_run=True)
            outstanding.extend(m.to_dict() for m in result.messages)
        return {"outstanding": outstanding, "count": len(outstanding)}

    # -------------------------------------------------------- the writers

    def draft_commentary(principal=None, section_id=None, instructions="",
                         **_: Any) -> dict[str, Any]:
        """Write commentary for one section, as an unaccepted draft."""
        if section_id is None:
            raise pb.InvalidPlaybook(
                "Say which section to write commentary for.")
        made = narrative.draft(session, int(section_id), principal,
                               source=SOURCE_AI, instructions=str(instructions))
        block = narrative.write(session, int(section_id), principal, made,
                                source=SOURCE_AI)
        return {
            "block": block, "draft": made.to_dict(),
            "accepted": False,
            "note": ("This is a draft. It is on the page marked as unaccepted, "
                     "and the pack cannot be approved until a person has read "
                     "it and put their name to it."),
        }

    def refresh_figures(principal=None, pack_id=None, code=None,
                        **_: Any) -> dict[str, Any]:
        """Recalculate a draft pack's governed figures.

        Produces no new claims: every number comes from the metric catalogue
        through the same path a person's click uses. Refused on an approved
        pack by `access.assert_editable`.
        """
        from backend.playbook import generation

        found = _pack_id(session, principal, pack_id, code)
        outcome = generation.generate(session, found, principal,
                                      source=SOURCE_AI)
        return outcome.to_dict()

    def draft_action(principal=None, pack_id=None, code=None, description="",
                     due_date=None, owner_id=None, priority="MEDIUM",
                     decision_id=None, **_: Any) -> dict[str, Any]:
        """Write an action into DRAFT, where a person has to open it."""
        found = _pack_id(session, principal, pack_id, code)
        made = actions.create_action(
            session, found, principal, description=str(description),
            owner_id=owner_id, due_date=_as_date(due_date),
            priority=str(priority), decision_id=decision_id, status="DRAFT",
            source=SOURCE_AI)
        return {
            "action": made,
            "note": ("Drafted, not opened. An action becomes real when a "
                     "person opens it, because that is the moment somebody "
                     "has agreed to do it."),
        }

    return {
        PLAYBOOK_COMMITTEES: committees,
        PLAYBOOK_PACK: pack,
        PLAYBOOK_READINESS: readiness_of,
        PLAYBOOK_FIGURES: figures,
        PLAYBOOK_FINDINGS: findings,
        PLAYBOOK_DECISIONS: decisions,
        PLAYBOOK_ACTIONS: action_log,
        PLAYBOOK_HISTORY: history,
        PLAYBOOK_COMPARE: compare,
        PLAYBOOK_CHASE_LIST: chase_list,
        PLAYBOOK_DRAFT_COMMENTARY: draft_commentary,
        PLAYBOOK_REFRESH_FIGURES: refresh_figures,
        PLAYBOOK_DRAFT_ACTION: draft_action,
    }


def _pack_id(session: Any, principal: Any, pack_id: Any,
             code: Any) -> int:
    """Resolve a pack from an id or its human code.

    A model given a conversation about "the March retail pack" has the code
    and not the id, and making it guess an id is how it guesses somebody
    else's.
    """
    if pack_id is not None:
        return int(pack_id)
    if not str(code or "").strip():
        raise pb.InvalidPlaybook(
            "Say which pack, by its id or its code (for example "
            "RCRC-2026-03).")
    readable = access.readable_committee_ids(session, principal)
    if not readable:
        raise access.PackNotFound(f"No pack {code}.")
    row = session.execute(
        select(PlaybookPack).where(
            PlaybookPack.code == str(code).strip(),
            PlaybookPack.committee_id.in_(readable))).scalar_one_or_none()
    if row is None:
        raise access.PackNotFound(f"No pack {code}.")
    return int(row.id)


def _as_date(value: Any) -> Any:
    if value in (None, ""):
        return None
    if hasattr(value, "year"):
        return value
    from datetime import date

    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise pb.InvalidPlaybook(
            f"'{value}' is not a date. Use YYYY-MM-DD.") from None


__all__ = [
    "AGENT_VERSION", "FORBIDDEN", "PLAYBOOK_ACTIONS", "PLAYBOOK_CHASE_LIST",
    "PLAYBOOK_COMMITTEES", "PLAYBOOK_COMPARE", "PLAYBOOK_DECISIONS",
    "PLAYBOOK_DRAFT_ACTION", "PLAYBOOK_DRAFT_COMMENTARY", "PLAYBOOK_FIGURES",
    "PLAYBOOK_FINDINGS", "PLAYBOOK_HISTORY", "PLAYBOOK_PACK",
    "PLAYBOOK_READINESS", "PLAYBOOK_REFRESH_FIGURES", "handlers",
]
