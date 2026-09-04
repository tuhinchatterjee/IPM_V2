"""Committees, templates, packs, sections and blocks — with the record.

Everything a person or an agent does to a Playbook goes through a function
here, and every one of those functions does the same four things in the same
order:

    1. authorise, through `backend.playbook.access` and nothing else
    2. validate, against the declared vocabularies
    3. change exactly what was asked for
    4. write an event saying what changed, who changed it and through which door

Step four is not optional and is not "logging". `playbook_events` is what a
committee reads when it asks why a figure in the tabled pack differs from the
one circulated on Tuesday, and an operation that skips it has removed the
answer to that question.

Two editors, one pack
---------------------
Every content write takes the version the caller believed they were editing. If
the pack has moved on, the write is refused and the refusal says what changed
and who changed it. Last-write-wins on a governance document means one person's
paragraph silently disappears between the draft and the meeting, and nobody
finds out until somebody asks about a sentence that is no longer there.

Status is a transition, not an assignment
-----------------------------------------
`set_status` will not put a pack in a status it cannot reach from where it is,
and the gates on the two that matter — READY_FOR_APPROVAL and APPROVED — are
enforced here rather than in the router. A second caller reaching the service
directly must not be able to walk a pack past a gate the screen enforces.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select

from backend.models.playbook import (
    ACCESS_ROLES,
    BLOCK_TYPES,
    BUSINESS_ROLES,
    CADENCES,
    CALCULATED_BLOCK_TYPES,
    CONFIDENTIALITY,
    EDITABLE_PACK_STATUSES,
    IMPORT_CLASSES,
    LOCKED_PACK_STATUSES,
    PACK_STATUSES,
    REVIEW_DECISIONS,
    SECTION_STATUSES,
    SOURCE_UI,
    STATEMENT_KINDS,
    TEMPLATE_STATUSES,
    PlaybookBlock,
    PlaybookCommittee,
    PlaybookEvent,
    PlaybookMember,
    PlaybookPack,
    PlaybookReview,
    PlaybookSection,
    PlaybookSnapshot,
    PlaybookTemplate,
)
from backend.playbook import access, materiality, readiness
from backend.playbook.access import (
    APPROVER,
    CONTRIBUTOR,
    EDITOR,
    OWNER,
    REVIEWER,
    PackDenied,
    PackLocked,
    PackNotFound,
)

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"[^a-z0-9]+")


class InvalidPlaybook(ValueError):
    """The request is not a thing this product can represent.

    Always names the allowed values. A refusal that says "invalid status" and
    stops leaves the caller guessing, and the guess is usually another attempt
    at the same wrong value.
    """


class StaleWrite(RuntimeError):
    """Somebody else changed this while you were editing it."""


#: Where a pack may go from where it is. Written out rather than derived,
#: because "which transitions are legitimate" is a governance decision and
#: deriving it from anything would make it look like a consequence.
#:
#: SUPERSEDED and ARCHIVED are terminal. An approved pack reaches SUPERSEDED
#: only by being amended, which `amend` does; nothing sets it directly.
TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"DATA_PENDING", "GENERATING", "CONTRIBUTOR_REVIEW",
                        "ARCHIVED"}),
    "DATA_PENDING": frozenset({"DRAFT", "GENERATING", "ARCHIVED"}),
    "GENERATING": frozenset({"DRAFT", "DATA_PENDING", "CONTRIBUTOR_REVIEW",
                             "ARCHIVED"}),
    "CONTRIBUTOR_REVIEW": frozenset({"DRAFT", "REVIEW", "CHANGES_REQUESTED",
                                     "ARCHIVED"}),
    "REVIEW": frozenset({"CHANGES_REQUESTED", "READY_FOR_APPROVAL",
                         "CONTRIBUTOR_REVIEW", "ARCHIVED"}),
    "CHANGES_REQUESTED": frozenset({"DRAFT", "CONTRIBUTOR_REVIEW", "REVIEW",
                                    "ARCHIVED"}),
    "READY_FOR_APPROVAL": frozenset({"APPROVED", "CHANGES_REQUESTED",
                                     "REVIEW", "ARCHIVED"}),
    "APPROVED": frozenset({"PUBLISHED"}),
    "PUBLISHED": frozenset(),
    "SUPERSEDED": frozenset(),
    "ARCHIVED": frozenset({"DRAFT"}),
}

#: The access needed to move a pack INTO each status. Absent means EDITOR.
TRANSITION_ACCESS: dict[str, str] = {
    "READY_FOR_APPROVAL": EDITOR,
    "APPROVED": APPROVER,
    "PUBLISHED": APPROVER,
    "ARCHIVED": OWNER,
}

#: Default committee workflow timing, in days before the meeting. Overridden
#: per committee by `workflow_offsets`: a monthly forum and an annual one do
#: not chase people on the same rhythm, and §3.2 forbids one hard-coded
#: cadence for every committee.
DEFAULT_OFFSETS: dict[str, int] = {
    "create": 14, "inputs": 10, "data_check": 7, "generate": 5,
    "review": 3, "escalate": 1,
}


# ------------------------------------------------------------- the record


def record(session: Any, *, entity_type: str, action: str,
           pack: Any = None, committee_id: int | None = None,
           entity_id: int | None = None, entity_ref: str = "",
           changes: dict[str, Any] | None = None, narrative: str = "",
           grant: access.Grant | None = None) -> PlaybookEvent:
    """One line of history. Append-only; nothing updates or deletes these.

    Takes the grant rather than a principal so the event records the SOURCE
    and whether the actor was acting administratively — both facts a reader of
    the history needs and neither derivable afterwards.
    """
    event = PlaybookEvent(
        pack_id=int(pack.id) if pack is not None else None,
        committee_id=(committee_id if committee_id is not None
                      else (int(pack.committee_id) if pack is not None
                            else None)),
        entity_type=entity_type,
        entity_id=entity_id,
        entity_ref=entity_ref[:64],
        action=action,
        changes=dict(changes or {}),
        narrative=narrative,
        at_version=int(pack.version) if pack is not None else None,
        author_id=grant.user_id if grant else None,
        source=grant.source if grant else SOURCE_UI,
    )
    if grant is not None and grant.administrative:
        # Said on the event rather than inferred later. An administrator
        # acting on a committee they are not a member of is legitimate and
        # rare, and the history should show which it was.
        event.changes = {**event.changes, "_administrative": True}
    session.add(event)
    return event


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """{field: [before, after]} for the fields that actually moved.

    The same shape `planner_updates` uses. Fields whose value is unchanged are
    omitted: a history in which every save lists forty fields is a history
    nobody reads.
    """
    out: dict[str, Any] = {}
    for field, value in after.items():
        was = before.get(field)
        if was != value:
            out[field] = [_plain(was), _plain(value)]
    return out


def _plain(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


# ------------------------------------------------------------- committees


def committees(session: Any, principal: Any, *,
               source: str = SOURCE_UI) -> list[dict[str, Any]]:
    """Every committee this caller may see, with what is open on each."""
    grants = access.grants_for(session, principal, source)
    if not grants:
        return []
    rows = session.execute(
        select(PlaybookCommittee)
        .where(PlaybookCommittee.id.in_(list(grants)))
        .order_by(PlaybookCommittee.name)).scalars().all()

    counts = dict(session.execute(
        select(PlaybookPack.committee_id, func.count())
        .where(PlaybookPack.committee_id.in_(list(grants)),
               PlaybookPack.status.notin_(("ARCHIVED", "SUPERSEDED")))
        .group_by(PlaybookPack.committee_id)).all())

    latest = {}
    for committee_id, meeting in session.execute(
        select(PlaybookPack.committee_id, func.max(PlaybookPack.meeting_at))
        .where(PlaybookPack.committee_id.in_(list(grants)))
        .group_by(PlaybookPack.committee_id)).all():
        latest[int(committee_id)] = meeting

    return [{**_committee_dict(row),
             "access": grants[int(row.id)].access,
             "open_packs": int(counts.get(int(row.id), 0)),
             "next_meeting_at": _plain(latest.get(int(row.id)))}
            for row in rows]


def committee(session: Any, committee_id: int, principal: Any, *,
              source: str = SOURCE_UI) -> dict[str, Any]:
    """One committee, its members and its packs."""
    grant = access.committee_grant(session, committee_id, principal, source)
    row = session.get(PlaybookCommittee, int(committee_id))
    members = session.execute(
        select(PlaybookMember)
        .where(PlaybookMember.committee_id == row.id)
        .order_by(PlaybookMember.business_role,
                  PlaybookMember.id)).scalars().all()
    packs = session.execute(
        select(PlaybookPack)
        .where(PlaybookPack.committee_id == row.id)
        .order_by(PlaybookPack.meeting_at.desc().nullslast(),
                  PlaybookPack.id.desc())).scalars().all()
    return {
        **_committee_dict(row),
        "access": grant.access,
        "members": [_member_dict(m) for m in members],
        "packs": [_pack_summary(p) for p in packs],
        "offsets": _offsets(row),
    }


def create_committee(session: Any, principal: Any, *, name: str,
                     code: str = "", description: str = "", purpose: str = "",
                     business_area: str = "", cadence: str = "MONTHLY",
                     meeting_weekday: int | None = None,
                     confidentiality: str = "CONFIDENTIAL",
                     standard_agenda: list | None = None,
                     workflow_offsets: dict | None = None,
                     chair_id: int | None = None,
                     secretary_id: int | None = None,
                     source: str = SOURCE_UI) -> dict[str, Any]:
    """Stand up a new forum.

    A platform ADMIN or DATA_STEWARD creates committees; the creator becomes
    its OWNER. Somebody has to be able to administer a committee from the
    moment it exists, and a committee with no members is one nobody can open.
    """
    channel = access.normalise_source(source)
    if channel in ("AI", "AI_CHAT"):
        raise PackDenied(
            "Standing up a governance forum is a decision about how the bank "
            "runs. There is no tool for it.")
    from backend.api.permissions import Role

    role = str(getattr(getattr(principal, "role", ""), "value",
                       getattr(principal, "role", ""))).upper()
    if role not in (Role.ADMIN.value, Role.DATA_STEWARD.value):
        raise PackDenied(
            "Creating a committee needs administrator or data steward access.")

    name = _required(name, "a committee name")
    code = _slugify(code or name)[:40]
    if session.execute(select(PlaybookCommittee.id).where(
            PlaybookCommittee.code == code)).scalar_one_or_none() is not None:
        raise InvalidPlaybook(
            f"A committee with the code '{code}' already exists. Committee "
            "codes are how packs are named, so they have to be unique.")
    _one_of(cadence, CADENCES, "cadence")
    _one_of(confidentiality, CONFIDENTIALITY, "confidentiality")
    if meeting_weekday is not None and not 0 <= int(meeting_weekday) <= 6:
        raise InvalidPlaybook(
            "A meeting weekday is 0 (Monday) to 6 (Sunday).")
    offsets = _validate_offsets(workflow_offsets)

    user_id = getattr(principal, "user_id", None)
    row = PlaybookCommittee(
        code=code, name=name.strip(), description=description or "",
        purpose=purpose or "", business_area=business_area or "",
        cadence=cadence.upper(), meeting_weekday=meeting_weekday,
        confidentiality=confidentiality.upper(),
        standard_agenda=list(standard_agenda or []),
        workflow_offsets=offsets, chair_id=chair_id,
        secretary_id=secretary_id, created_by=user_id, updated_by=user_id)
    session.add(row)
    session.flush()

    if user_id is not None:
        session.add(PlaybookMember(
            committee_id=int(row.id), user_id=int(user_id),
            business_role="PACK_OWNER", access_role=OWNER,
            title="", notify=True, active=True))
        session.flush()

    grant = access.committee_grant_for(session, row, principal, channel)
    record(session, entity_type="committee", action="created",
           committee_id=int(row.id), entity_id=int(row.id), entity_ref=code,
           narrative=f"{name} was created.", grant=grant)
    return _committee_dict(row)


def update_committee(session: Any, committee_id: int, principal: Any, *,
                     source: str = SOURCE_UI,
                     **changes: Any) -> dict[str, Any]:
    """Change a committee's standing configuration."""
    grant = access.require_committee(
        session, committee_id, principal, OWNER,
        "change how this committee runs", source)
    access.refuse_ai(grant, "change_meeting_date")
    row = session.get(PlaybookCommittee, int(committee_id))

    allowed = {"name", "description", "purpose", "business_area", "cadence",
               "meeting_weekday", "confidentiality", "standard_agenda",
               "workflow_offsets", "chair_id", "secretary_id", "active"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidPlaybook(
            f"{', '.join(sorted(unknown))} is not something a committee "
            f"carries. Changeable: {', '.join(sorted(allowed))}.")

    if "cadence" in changes:
        _one_of(changes["cadence"], CADENCES, "cadence")
        changes["cadence"] = str(changes["cadence"]).upper()
    if "confidentiality" in changes:
        _one_of(changes["confidentiality"], CONFIDENTIALITY, "confidentiality")
        changes["confidentiality"] = str(changes["confidentiality"]).upper()
    if "workflow_offsets" in changes:
        changes["workflow_offsets"] = _validate_offsets(
            changes["workflow_offsets"])

    before = {k: getattr(row, k) for k in changes}
    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_by = grant.user_id
    row.updated_at = datetime.now(UTC)
    session.flush()

    moved = _diff(before, changes)
    if moved:
        record(session, entity_type="committee", action="updated",
               committee_id=int(row.id), entity_id=int(row.id),
               entity_ref=str(row.code), changes=moved, grant=grant)
    return _committee_dict(row)


def add_member(session: Any, committee_id: int, principal: Any, *,
               user_id: int, business_role: str = "MEMBER",
               access_role: str = "VIEWER", title: str = "",
               notify: bool = True,
               source: str = SOURCE_UI) -> dict[str, Any]:
    """Put somebody on a committee, in a business role and an access role."""
    grant = access.require_committee(
        session, committee_id, principal, OWNER,
        "change who is on this committee", source)
    if grant.by_ai:
        raise PackDenied(
            "Who sits on a committee is a decision about the bank's "
            "governance. There is no tool for it.")
    _one_of(business_role, BUSINESS_ROLES, "business role")
    _one_of(access_role, ACCESS_ROLES, "access role")
    if not _user_exists(session, user_id):
        raise InvalidPlaybook(f"There is no user {user_id}.")

    existing = session.execute(select(PlaybookMember).where(
        PlaybookMember.committee_id == int(committee_id),
        PlaybookMember.user_id == int(user_id))).scalar_one_or_none()
    if existing is not None:
        raise InvalidPlaybook(
            "That person is already on this committee. Change their role "
            "rather than adding them twice.")

    row = PlaybookMember(
        committee_id=int(committee_id), user_id=int(user_id),
        business_role=business_role.upper(), access_role=access_role.upper(),
        title=title or "", notify=bool(notify), active=True)
    session.add(row)
    session.flush()
    record(session, entity_type="committee", action="member_added",
           committee_id=int(committee_id), entity_id=int(row.id),
           changes={"user_id": [None, int(user_id)],
                    "access_role": [None, row.access_role]},
           narrative=f"Added as {row.business_role.replace('_', ' ').lower()} "
                     f"with {row.access_role.lower()} access.",
           grant=grant)
    return _member_dict(row)


def update_member(session: Any, member_id: int, principal: Any, *,
                  source: str = SOURCE_UI, **changes: Any) -> dict[str, Any]:
    """Change somebody's role on a committee, or take them off it."""
    row = session.get(PlaybookMember, int(member_id))
    if row is None:
        raise PackNotFound(f"No committee member {member_id}.")
    grant = access.require_committee(
        session, int(row.committee_id), principal, OWNER,
        "change who is on this committee", source)
    if grant.by_ai:
        raise PackDenied(
            "Who sits on a committee is a decision about the bank's "
            "governance. There is no tool for it.")

    allowed = {"business_role", "access_role", "title", "notify", "active"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidPlaybook(
            f"{', '.join(sorted(unknown))} is not something a membership "
            f"carries. Changeable: {', '.join(sorted(allowed))}.")
    if "business_role" in changes:
        _one_of(changes["business_role"], BUSINESS_ROLES, "business role")
        changes["business_role"] = str(changes["business_role"]).upper()
    if "access_role" in changes:
        _one_of(changes["access_role"], ACCESS_ROLES, "access role")
        changes["access_role"] = str(changes["access_role"]).upper()

    if (changes.get("access_role") not in (None, OWNER)
            or changes.get("active") is False) and str(row.access_role) == OWNER:
        _refuse_last_owner(session, row)

    before = {k: getattr(row, k) for k in changes}
    for field, value in changes.items():
        setattr(row, field, value)
    session.flush()
    moved = _diff(before, changes)
    if moved:
        record(session, entity_type="committee", action="member_updated",
               committee_id=int(row.committee_id), entity_id=int(row.id),
               changes=moved, grant=grant)
    return _member_dict(row)


def _refuse_last_owner(session: Any, member: Any) -> None:
    """A committee always keeps at least one owner.

    Removing the last one leaves a forum nobody can administer, whose packs
    nobody can approve, and which only a platform administrator can rescue.
    """
    others = session.execute(
        select(func.count()).select_from(PlaybookMember).where(
            PlaybookMember.committee_id == member.committee_id,
            PlaybookMember.access_role == OWNER,
            PlaybookMember.active.is_(True),
            PlaybookMember.id != member.id)).scalar_one()
    if int(others) == 0:
        raise InvalidPlaybook(
            "This is the committee's only owner. Give somebody else owner "
            "access first — a committee with no owner is one nobody can "
            "administer and whose packs nobody can approve.")


# -------------------------------------------------------------- templates


def templates(session: Any, principal: Any, *, committee_id: int | None = None,
              source: str = SOURCE_UI) -> list[dict[str, Any]]:
    """Pack shapes this caller may use.

    A template with no committee is a platform-wide shape available to
    everybody; one bound to a committee is visible only to its members.
    """
    readable = access.readable_committee_ids(session, principal)
    query = select(PlaybookTemplate).where(
        (PlaybookTemplate.committee_id.is_(None))
        | (PlaybookTemplate.committee_id.in_(readable or [-1])))
    if committee_id is not None:
        access.committee_grant(session, committee_id, principal, source)
        query = query.where(
            (PlaybookTemplate.committee_id == int(committee_id))
            | (PlaybookTemplate.committee_id.is_(None)))
    rows = session.execute(query.order_by(
        PlaybookTemplate.name, PlaybookTemplate.version.desc())).scalars()
    return [_template_dict(t) for t in rows]


def create_template(session: Any, principal: Any, *, name: str,
                    code: str = "", committee_id: int | None = None,
                    description: str = "", sections: list | None = None,
                    materiality_rules: list | None = None,
                    required_domains: list | None = None,
                    required_datasets: list | None = None,
                    export_settings: dict | None = None,
                    confidentiality: str = "CONFIDENTIAL",
                    status: str = "DRAFT",
                    source: str = SOURCE_UI) -> dict[str, Any]:
    """A new template, or a new VERSION of an existing one.

    Versions are new rows and old rows are never edited, because a pack tabled
    last quarter was built from the shape as it was then and reproducing it
    means being able to read that shape.
    """
    channel = access.normalise_source(source)
    if committee_id is not None:
        grant = access.require_committee(
            session, committee_id, principal, EDITOR,
            "create a pack template for this committee", channel)
    else:
        from backend.api.permissions import Role

        role = str(getattr(getattr(principal, "role", ""), "value",
                           getattr(principal, "role", ""))).upper()
        if role not in (Role.ADMIN.value, Role.DATA_STEWARD.value):
            raise PackDenied(
                "A platform-wide pack template is available to every "
                "committee, so creating one needs administrator or data "
                "steward access. A template for one committee needs only "
                "editor access to that committee.")
        grant = access.Grant(0, getattr(principal, "user_id", None), OWNER,
                             "PLATFORM_ADMIN", administrative=True,
                             source=channel)
    if grant.by_ai:
        raise PackDenied(
            "A template decides what every future pack of this committee "
            "contains. A person writes it.")

    name = _required(name, "a template name")
    code = _slugify(code or name)[:40]
    _one_of(status, TEMPLATE_STATUSES, "template status")
    _one_of(confidentiality, CONFIDENTIALITY, "confidentiality")
    shape = _validate_sections(sections)
    rules = materiality.parse(materiality_rules)

    latest = session.execute(
        select(func.max(PlaybookTemplate.version))
        .where(PlaybookTemplate.code == code)).scalar_one()
    row = PlaybookTemplate(
        committee_id=committee_id, code=code, name=name.strip(),
        description=description or "", version=int(latest or 0) + 1,
        status=status.upper(), sections=shape,
        materiality=[r.to_dict() for r in rules],
        required_domains=list(required_domains or []),
        required_datasets=list(required_datasets or []),
        export_settings=dict(export_settings or {}),
        confidentiality=confidentiality.upper(),
        created_by=grant.user_id)
    session.add(row)
    session.flush()
    record(session, entity_type="template", action="created",
           committee_id=committee_id, entity_id=int(row.id),
           entity_ref=f"{code}@{row.version}",
           narrative=f"{name} version {row.version} was created with "
                     f"{len(shape)} section{'s' if len(shape) != 1 else ''}.",
           grant=grant)
    return _template_dict(row)


def set_template_status(session: Any, template_id: int, principal: Any, *,
                        status: str, source: str = SOURCE_UI) -> dict[str, Any]:
    """Publish or retire a template version.

    A DRAFT template can be built from, so this is not a gate on use — it is
    the committee saying which shape is the current one.
    """
    row = session.get(PlaybookTemplate, int(template_id))
    if row is None:
        raise PackNotFound(f"No template {template_id}.")
    _one_of(status, TEMPLATE_STATUSES, "template status")
    if row.committee_id is not None:
        grant = access.require_committee(
            session, int(row.committee_id), principal, EDITOR,
            "change this template's status", source)
    else:
        from backend.api.permissions import Role

        role = str(getattr(getattr(principal, "role", ""), "value",
                           getattr(principal, "role", ""))).upper()
        if role != Role.ADMIN.value:
            raise PackDenied(
                "Changing a platform-wide template's status needs "
                "administrator access.")
        grant = access.Grant(0, getattr(principal, "user_id", None), OWNER,
                             "PLATFORM_ADMIN", administrative=True,
                             source=access.normalise_source(source))
    if grant.by_ai:
        raise PackDenied("A person decides which template shape is current.")

    was = str(row.status)
    row.status = status.upper()
    row.updated_at = datetime.now(UTC)
    session.flush()
    record(session, entity_type="template", action="status_changed",
           committee_id=row.committee_id, entity_id=int(row.id),
           entity_ref=f"{row.code}@{row.version}",
           changes={"status": [was, row.status]}, grant=grant)
    return _template_dict(row)


# ------------------------------------------------------------------ packs


def packs(session: Any, principal: Any, *, committee_id: int | None = None,
          status: str | None = None, mine: bool = False, limit: int = 100,
          source: str = SOURCE_UI) -> list[dict[str, Any]]:
    """Packs across every committee this caller can see."""
    readable = access.readable_committee_ids(session, principal)
    if not readable:
        return []
    if committee_id is not None:
        access.committee_grant(session, committee_id, principal, source)
        readable = [int(committee_id)]

    query = select(PlaybookPack).where(PlaybookPack.committee_id.in_(readable))
    if status:
        _one_of(status, PACK_STATUSES, "pack status")
        query = query.where(PlaybookPack.status == status.upper())
    if mine:
        user_id = getattr(principal, "user_id", None)
        if user_id is None:
            return []
        query = query.where(PlaybookPack.owner_id == int(user_id))
    rows = session.execute(query.order_by(
        PlaybookPack.meeting_at.desc().nullslast(),
        PlaybookPack.id.desc()).limit(max(1, min(500, int(limit))))).scalars()
    return [_pack_summary(p) for p in rows]


def pack(session: Any, pack_id: int, principal: Any, *,
         source: str = SOURCE_UI) -> dict[str, Any]:
    """One pack, whole: sections, blocks, the figures behind them, readiness.

    An APPROVED or PUBLISHED pack renders from the snapshots it was approved
    with. A draft renders from its current ones. Neither recalculates on open,
    which is what makes a tabled pack the same document every time it is
    opened.
    """
    row, grant = access.readable_pack(session, pack_id, principal, source)
    sections = session.execute(
        select(PlaybookSection).where(PlaybookSection.pack_id == row.id)
        .order_by(PlaybookSection.position)).scalars().all()
    blocks = session.execute(
        select(PlaybookBlock).where(PlaybookBlock.pack_id == row.id)
        .order_by(PlaybookBlock.position)).scalars().all()

    wanted = [int(b.snapshot_id) for b in blocks if b.snapshot_id is not None]
    figures: dict[int, Any] = {}
    if wanted:
        figures = {int(s.id): s for s in session.execute(
            select(PlaybookSnapshot)
            .where(PlaybookSnapshot.id.in_(wanted))).scalars()}

    by_section: dict[int, list] = {}
    for block in blocks:
        by_section.setdefault(int(block.section_id), []).append(block)

    state = readiness.assess(session, row)
    committee_row = session.get(PlaybookCommittee, int(row.committee_id))
    return {
        **_pack_summary(row),
        "access": grant.access,
        "editable": (str(row.status) in EDITABLE_PACK_STATUSES
                     and grant.at_least(CONTRIBUTOR)),
        "locked": str(row.status) in LOCKED_PACK_STATUSES,
        "committee": _committee_dict(committee_row),
        "readiness": state.to_dict(),
        "sections": [
            {**_section_dict(s),
             "blocks": [_block_dict(b, figures.get(int(b.snapshot_id))
                                    if b.snapshot_id else None)
                        for b in by_section.get(int(s.id), [])]}
            for s in sections],
    }


def create_pack(session: Any, principal: Any, *, committee_id: int,
                name: str = "", period: str = "",
                comparison_period: str = "",
                meeting_at: datetime | None = None,
                as_of_date: date | None = None,
                template_id: int | None = None,
                owner_id: int | None = None,
                source: str = SOURCE_UI) -> dict[str, Any]:
    """Open the next pack for a committee, shaped by a template.

    Links itself to the previous approved pack of the same committee so that
    "what changed since last time" is a stored relationship rather than a
    guess from dates — which matters the first time somebody backfills a pack
    for a meeting that already happened.
    """
    grant = access.require_committee(
        session, committee_id, principal, EDITOR,
        "open a new pack for this committee", source)
    committee_row = session.get(PlaybookCommittee, int(committee_id))

    template = None
    if template_id is not None:
        template = session.get(PlaybookTemplate, int(template_id))
        if template is None:
            raise InvalidPlaybook(f"There is no template {template_id}.")
        if (template.committee_id is not None
                and int(template.committee_id) != int(committee_id)):
            raise InvalidPlaybook(
                f"“{template.name}” belongs to another committee.")
    elif committee_row.default_template_id is not None:
        template = session.get(PlaybookTemplate,
                               int(committee_row.default_template_id))

    period = str(period or "").strip()
    name = (name or "").strip() or _pack_name(committee_row, period, meeting_at)
    code = _pack_code(session, committee_row, period, meeting_at)

    previous = session.execute(
        select(PlaybookPack)
        .where(PlaybookPack.committee_id == int(committee_id),
               PlaybookPack.status.in_(("APPROVED", "PUBLISHED")))
        .order_by(PlaybookPack.meeting_at.desc().nullslast(),
                  PlaybookPack.id.desc()).limit(1)).scalar_one_or_none()

    row = PlaybookPack(
        code=code, committee_id=int(committee_id),
        template_id=int(template.id) if template is not None else None,
        name=name, period=period, comparison_period=comparison_period or "",
        meeting_at=meeting_at, as_of_date=as_of_date,
        owner_id=owner_id if owner_id is not None else grant.user_id,
        status="DRAFT",
        confidentiality=str(template.confidentiality if template is not None
                            else committee_row.confidentiality),
        previous_pack_id=int(previous.id) if previous is not None else None,
        created_by=grant.user_id, updated_by=grant.user_id)
    session.add(row)
    session.flush()

    made = 0
    if template is not None:
        made = _sections_from_template(session, row, template)

    record(session, entity_type="pack", action="created", pack=row,
           entity_id=int(row.id), entity_ref=code,
           narrative=(f"{name} was opened"
                      + (f" from {template.name} version {template.version}, "
                         f"with {made} section{'s' if made != 1 else ''}"
                         if template is not None else "")
                      + "."),
           grant=grant)
    readiness.refresh(session, row)
    return _pack_summary(row)


def _sections_from_template(session: Any, row: Any, template: Any) -> int:
    """Lay out a pack's sections from its template version."""
    made = 0
    for index, spec in enumerate(list(template.sections or [])):
        if not isinstance(spec, dict):
            continue
        section = PlaybookSection(
            pack_id=int(row.id),
            template_key=str(spec.get("key") or "")[:64],
            title=str(spec.get("title") or f"Section {index + 1}")[:240],
            purpose=str(spec.get("purpose") or ""),
            position=int(spec.get("order", index)),
            required=bool(spec.get("required", True)),
            narrative_instructions=str(spec.get("narrative_instructions") or ""),
            status="NOT_STARTED")
        session.add(section)
        session.flush()
        made += 1
        for order, block in enumerate(list(spec.get("blocks") or [])):
            if not isinstance(block, dict):
                continue
            kind = str(block.get("type") or block.get("block_type") or "")
            if kind.upper() not in BLOCK_TYPES:
                continue
            session.add(PlaybookBlock(
                section_id=int(section.id), pack_id=int(row.id),
                block_type=kind.upper(), position=order,
                title=str(block.get("title") or "")[:240],
                body=str(block.get("body") or ""),
                config=dict(block.get("config") or {}),
                filters=dict(block.get("filters") or {}),
                period=str(block.get("period") or ""),
                source=SOURCE_UI))
    session.flush()
    return made


def update_pack(session: Any, pack_id: int, principal: Any, *,
                expected_version: int | None = None, source: str = SOURCE_UI,
                **changes: Any) -> dict[str, Any]:
    """Change a pack's heading information."""
    row, grant = access.writable_pack(
        session, pack_id, principal, EDITOR, "change this pack", source)
    _check_version(session, row, expected_version)

    allowed = {"name", "period", "comparison_period", "meeting_at",
               "as_of_date", "data_freeze_at", "owner_id", "confidentiality",
               "minutes"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidPlaybook(
            f"{', '.join(sorted(unknown))} is not something a pack carries "
            f"directly. Changeable: {', '.join(sorted(allowed))}.")
    if "confidentiality" in changes:
        _one_of(changes["confidentiality"], CONFIDENTIALITY, "confidentiality")
        changes["confidentiality"] = str(changes["confidentiality"]).upper()
    if "meeting_at" in changes and row.meeting_at is not None:
        # A committed date is in other people's diaries. An agent may not move
        # one at all, and a person moving one leaves a reason in the history.
        access.refuse_ai(grant, "change_meeting_date")

    before = {k: getattr(row, k) for k in changes}
    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_by = grant.user_id
    row.updated_at = datetime.now(UTC)
    moved = _diff(before, changes)
    if moved:
        row.version = int(row.version) + 1
        session.flush()
        record(session, entity_type="pack", action="updated", pack=row,
               entity_id=int(row.id), entity_ref=str(row.code),
               changes=moved, grant=grant)
        readiness.refresh(session, row)
    return _pack_summary(row)


def set_pack_status(session: Any, pack_id: int, principal: Any, *,
                    status: str, note: str = "",
                    source: str = SOURCE_UI) -> dict[str, Any]:
    """Move a pack through its lifecycle, or say why it cannot move.

    The gate on READY_FOR_APPROVAL is the readiness assessment's BLOCKING
    reasons and nothing else — not the percentage, which is a progress bar.
    The gate on APPROVED is `access.may_approve_pack`, which refuses an agent,
    refuses anybody below approver, and refuses the pack's own owner.
    """
    _one_of(status, PACK_STATUSES, "pack status")
    wanted = status.upper()
    row, grant = access.pack_grant(session, pack_id, principal, source)
    was = str(row.status)

    if wanted == was:
        return _pack_summary(row)
    if wanted not in TRANSITIONS.get(was, frozenset()):
        reachable = sorted(TRANSITIONS.get(was, frozenset()))
        raise InvalidPlaybook(
            f"This pack is {_readable(was)} and cannot go straight to "
            f"{_readable(wanted)}. From here it can go to: "
            + (", ".join(_readable(s) for s in reachable) if reachable
               else "nowhere — this is where a pack's life ends."))

    if wanted == "APPROVED":
        access.may_approve_pack(row, grant)
    elif wanted == "PUBLISHED":
        access.refuse_ai(grant, "publish_pack")
        _assert_level(grant, TRANSITION_ACCESS.get(wanted, EDITOR), wanted)
    else:
        _assert_level(grant, TRANSITION_ACCESS.get(wanted, EDITOR), wanted)

    if wanted in ("READY_FOR_APPROVAL", "APPROVED"):
        ready, blocking = readiness.may_submit_for_approval(session, row)
        if not ready:
            listed = "\n".join(f"  • {r.text}" for r in blocking[:8])
            more = (f"\n  … and {len(blocking) - 8} more"
                    if len(blocking) > 8 else "")
            raise InvalidPlaybook(
                f"This pack is not ready to go to committee. "
                f"{len(blocking)} thing"
                f"{'s are' if len(blocking) != 1 else ' is'} blocking it:\n"
                f"{listed}{more}")

    row.status = wanted
    now = datetime.now(UTC)
    if wanted == "APPROVED":
        row.approved_by = grant.user_id
        row.approved_at = now
        row.approved_version = int(row.version)
        _freeze(session, row, grant)
    if wanted == "PUBLISHED":
        row.published_at = now
    row.updated_by = grant.user_id
    row.updated_at = now
    session.flush()

    record(session, entity_type="pack", action="status_changed", pack=row,
           entity_id=int(row.id), entity_ref=str(row.code),
           changes={"status": [was, wanted]},
           narrative=note or f"Moved from {_readable(was)} to "
                             f"{_readable(wanted)}.",
           grant=grant)
    readiness.refresh(session, row)
    return _pack_summary(row)


def _freeze(session: Any, row: Any, grant: access.Grant) -> None:
    """Lock every section of a pack that has just been approved."""
    sections = session.execute(
        select(PlaybookSection)
        .where(PlaybookSection.pack_id == row.id)).scalars().all()
    for section in sections:
        if str(section.status) != "LOCKED":
            section.status = "LOCKED"
    session.flush()
    record(session, entity_type="pack", action="frozen", pack=row,
           entity_id=int(row.id), entity_ref=str(row.code),
           narrative=(f"Approved at version {row.version}. Its "
                      f"{len(sections)} section"
                      f"{'s are' if len(sections) != 1 else ' is'} locked and "
                      "its figures are the ones the committee saw."),
           grant=grant)


# --------------------------------------------------------------- sections


def create_section(session: Any, pack_id: int, principal: Any, *, title: str,
                   purpose: str = "", position: int | None = None,
                   owner_id: int | None = None, reviewer_id: int | None = None,
                   required: bool = True, due_date: date | None = None,
                   narrative_instructions: str = "",
                   template_key: str = "",
                   expected_version: int | None = None,
                   source: str = SOURCE_UI) -> dict[str, Any]:
    """Add a page to a pack."""
    row, grant = access.writable_pack(
        session, pack_id, principal, EDITOR, "add a section to this pack",
        source)
    _check_version(session, row, expected_version)
    title = _required(title, "a section title")

    if position is None:
        highest = session.execute(
            select(func.max(PlaybookSection.position))
            .where(PlaybookSection.pack_id == row.id)).scalar_one()
        position = int(highest or -1) + 1

    section = PlaybookSection(
        pack_id=int(row.id), template_key=template_key[:64],
        title=title.strip()[:240], purpose=purpose or "",
        position=int(position), owner_id=owner_id, reviewer_id=reviewer_id,
        required=bool(required), due_date=due_date,
        narrative_instructions=narrative_instructions or "",
        status="NOT_STARTED", updated_by=grant.user_id)
    session.add(section)
    row.version = int(row.version) + 1
    session.flush()
    record(session, entity_type="section", action="created", pack=row,
           entity_id=int(section.id), entity_ref=section.title[:64],
           narrative=f"“{section.title}” was added.", grant=grant)
    readiness.refresh(session, row)
    return _section_dict(section)


def update_section(session: Any, section_id: int, principal: Any, *,
                   expected_version: int | None = None,
                   source: str = SOURCE_UI, **changes: Any) -> dict[str, Any]:
    """Change a section. Contributors may change only the ones they own."""
    section, row, grant = access.visible_section(
        session, section_id, principal, source)
    access.assert_editable(row)
    access.may_edit_section(session, section, grant)
    _check_version(session, row, expected_version)

    allowed = {"title", "purpose", "position", "owner_id", "reviewer_id",
               "required", "due_date", "narrative_instructions", "status"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidPlaybook(
            f"{', '.join(sorted(unknown))} is not something a section "
            f"carries. Changeable: {', '.join(sorted(allowed))}.")
    if "status" in changes:
        _one_of(changes["status"], SECTION_STATUSES, "section status")
        changes["status"] = str(changes["status"]).upper()
        if changes["status"] in ("APPROVED", "LOCKED"):
            raise InvalidPlaybook(
                "A section is not approved by setting its status. Record a "
                "review against it, so the pack knows who approved it and at "
                "which version.")
    if {"owner_id", "reviewer_id"} & set(changes) and not grant.at_least(EDITOR):
        raise PackDenied(
            "Deciding who writes and who reviews a section needs editor "
            "access to the committee.")

    before = {k: getattr(section, k) for k in changes}
    for field, value in changes.items():
        setattr(section, field, value)
    section.updated_by = grant.user_id
    section.updated_at = datetime.now(UTC)
    moved = _diff(before, changes)
    if moved:
        section.version = int(section.version) + 1
        row.version = int(row.version) + 1
        session.flush()
        record(session, entity_type="section", action="updated", pack=row,
               entity_id=int(section.id), entity_ref=section.title[:64],
               changes=moved, grant=grant)
        readiness.refresh(session, row)
    return _section_dict(section)


def delete_section(session: Any, section_id: int, principal: Any, *,
                   source: str = SOURCE_UI) -> None:
    """Take a page out of a draft, with its blocks.

    Two refusals, and neither is bureaucracy:

    A section carrying a TEMPLATE KEY came from the committee's template — it
    is the shape the committee agreed its pack has. Dropping it from one pack
    quietly makes that pack a different document from every other one in the
    series, so the change belongs in the template, where it applies to the
    series. (The test is `template_key`, not `required`: `required` says
    readiness will block while the section is empty, which is equally true of
    a page somebody added here, and that page IS deletable.)

    A section anybody has REVIEWED carries a named person's statement that
    they read it. Deleting it would delete that statement, and a review log
    with holes in it is worse than no review log. Emptying the section is the
    honest move; the review then correctly reads as stale.
    """
    section, row, grant = access.visible_section(session, section_id,
                                                 principal, source)
    access.assert_editable(row)
    access.may_edit_section(session, section, grant, "remove this section")
    access.refuse_ai(grant, "delete_section")

    if str(section.template_key or "").strip():
        raise InvalidPlaybook(
            f"“{section.title}” is part of this committee's standard pack, so "
            "it cannot be dropped from one pack on its own. Change the "
            "template if the committee no longer wants this section.")
    reviewed = session.execute(
        select(func.count()).select_from(PlaybookReview)
        .where(PlaybookReview.section_id == section.id)).scalar_one()
    if int(reviewed or 0):
        raise InvalidPlaybook(
            f"“{section.title}” has been reviewed, and deleting it would "
            "delete the record of who read it. Empty it instead — the review "
            "will then show as out of date, which is the truth.")

    title, ref = str(section.title), int(section.id)
    blocks = int(session.execute(
        select(func.count()).select_from(PlaybookBlock)
        .where(PlaybookBlock.section_id == section.id)).scalar_one() or 0)
    session.delete(section)
    row.version = int(row.version) + 1
    session.flush()
    record(session, entity_type="section", action="deleted", pack=row,
           entity_id=ref, entity_ref=title[:64],
           narrative=(f"“{title}” was removed from the pack, with "
                      f"{blocks} block{'' if blocks == 1 else 's'} on it."),
           grant=grant)
    readiness.refresh(session, row)


def submit_section(session: Any, section_id: int, principal: Any, *,
                   note: str = "", source: str = SOURCE_UI) -> dict[str, Any]:
    """The owner says their section is ready to be read.

    An agent may not submit on somebody's behalf: submitting is a person
    saying they have finished, and a machine saying it for them is the
    beginning of a pack nobody has actually read.
    """
    section, row, grant = access.visible_section(
        session, section_id, principal, source)
    access.assert_editable(row)
    if grant.by_ai:
        raise PackDenied(
            "Submitting a section is its author saying they have finished "
            "with it. There is no tool for that.")
    access.may_edit_section(session, section, grant, "submit this section")

    was = str(section.status)
    section.status = "READY_FOR_REVIEW"
    section.submitted_at = datetime.now(UTC)
    section.submitted_by = grant.user_id
    session.flush()
    record(session, entity_type="section", action="submitted", pack=row,
           entity_id=int(section.id), entity_ref=section.title[:64],
           changes={"status": [was, section.status]}, narrative=note,
           grant=grant)
    readiness.refresh(session, row)
    return _section_dict(section)


def review_section(session: Any, section_id: int, principal: Any, *,
                   decision: str, note: str = "", conditions: str = "",
                   source: str = SOURCE_UI) -> dict[str, Any]:
    """Record that a named person read a named version and what they thought.

    Tied to `pack.version` at the moment of review. A reviewer who approved
    version 4 has not approved version 5, and the readiness check knows it.
    """
    section, row, grant = access.visible_section(
        session, section_id, principal, source)
    access.assert_editable(row)
    access.may_review_section(section, grant)
    _one_of(decision, REVIEW_DECISIONS, "review decision")
    wanted = decision.upper()
    if wanted == "PENDING":
        raise InvalidPlaybook(
            "A review that is pending is a review that has not been given. "
            "Request one instead.")
    if wanted == "CHANGES_REQUESTED" and not str(note or "").strip():
        raise InvalidPlaybook(
            "Asking for changes without saying what they are leaves the "
            "author guessing. Say what needs to change.")

    review = PlaybookReview(
        pack_id=int(row.id), section_id=int(section.id), scope="SECTION",
        reviewer_id=int(grant.user_id), decision=wanted, note=note or "",
        conditions=conditions or "", at_version=int(row.version),
        requested_by=section.owner_id, responded_at=datetime.now(UTC))
    session.add(review)

    was = str(section.status)
    if wanted == "APPROVED":
        section.status = "APPROVED"
        section.approved_at = datetime.now(UTC)
        section.approved_by = grant.user_id
    elif wanted == "CHANGES_REQUESTED":
        section.status = "CHANGES_REQUESTED"
    session.flush()

    record(session, entity_type="review", action="recorded", pack=row,
           entity_id=int(review.id), entity_ref=section.title[:64],
           changes={"decision": [None, wanted],
                    "section_status": [was, section.status]},
           narrative=note or f"{_readable(wanted)} at version {row.version}.",
           grant=grant)
    readiness.refresh(session, row)
    return {**_section_dict(section), "review": _review_dict(review)}


def request_review(session: Any, section_id: int, principal: Any, *,
                   reviewer_id: int, source: str = SOURCE_UI) -> dict[str, Any]:
    """Ask somebody to read a section.

    Writes a PENDING review row so the pack can say who it is waiting for,
    which is what turns "review outstanding" into a name.
    """
    section, row, grant = access.visible_section(
        session, section_id, principal, source)
    access.assert_editable(row)
    access.may_edit_section(session, section, grant, "ask for a review")
    if not _user_exists(session, reviewer_id):
        raise InvalidPlaybook(f"There is no user {reviewer_id}.")

    standing = session.execute(select(PlaybookReview).where(
        PlaybookReview.section_id == int(section.id),
        PlaybookReview.reviewer_id == int(reviewer_id),
        PlaybookReview.decision == "PENDING")).scalar_one_or_none()
    if standing is not None:
        return _review_dict(standing)

    review = PlaybookReview(
        pack_id=int(row.id), section_id=int(section.id), scope="SECTION",
        reviewer_id=int(reviewer_id), decision="PENDING",
        at_version=int(row.version), requested_by=grant.user_id)
    session.add(review)
    if str(section.status) == "READY_FOR_REVIEW":
        section.status = "IN_REVIEW"
    session.flush()
    record(session, entity_type="review", action="requested", pack=row,
           entity_id=int(review.id), entity_ref=section.title[:64],
           changes={"reviewer_id": [None, int(reviewer_id)]}, grant=grant)
    return _review_dict(review)


# ----------------------------------------------------------------- blocks


def create_block(session: Any, section_id: int, principal: Any, *,
                 block_type: str, title: str = "", body: str = "",
                 statement_kind: str = "", config: dict | None = None,
                 filters: dict | None = None, period: str = "",
                 position: int | None = None, import_class: str = "",
                 expected_version: int | None = None,
                 source: str = SOURCE_UI) -> dict[str, Any]:
    """Put something on a page.

    A calculated block is created without a figure and gets one when the pack
    is refreshed. That is deliberate: creating the block and computing the
    number are separate operations, and a create that silently ran a query
    would make laying out a pack take minutes.
    """
    section, row, grant = access.visible_section(
        session, section_id, principal, source)
    access.assert_editable(row)
    access.may_edit_section(session, section, grant, "add to this section")
    _check_version(session, row, expected_version)
    _one_of(block_type, BLOCK_TYPES, "block type")
    kind = block_type.upper()

    if statement_kind:
        _one_of(statement_kind, STATEMENT_KINDS, "statement kind")
        statement_kind = statement_kind.upper()
    if import_class:
        _one_of(import_class, IMPORT_CLASSES, "import class")
        import_class = import_class.upper()

    # An UNMAPPED_TABLE is the one table that names no metric, and it is not
    # an exception grudgingly allowed — it is the honest record of a table
    # lifted out of somebody's file, which CreditProbe did not calculate and
    # is not asserting. Everything downstream reads `import_class` to keep
    # the two apart: generation does not try to calculate it, `refresh_block`
    # refuses it by name, and a reader sees it labelled as theirs until a
    # person maps it to a metric.
    if kind in CALCULATED_BLOCK_TYPES and import_class != "UNMAPPED_TABLE":
        metric_id = str((config or {}).get("metric_id") or "").strip()
        if not metric_id:
            raise InvalidPlaybook(
                f"A {kind.lower()} block shows a governed figure and has to "
                "name the metric it shows.")

    if position is None:
        highest = session.execute(
            select(func.max(PlaybookBlock.position))
            .where(PlaybookBlock.section_id == section.id)).scalar_one()
        position = int(highest or -1) + 1

    block = PlaybookBlock(
        section_id=int(section.id), pack_id=int(row.id), block_type=kind,
        position=int(position), title=(title or "")[:240], body=body or "",
        statement_kind=statement_kind, config=dict(config or {}),
        filters=dict(filters or {}), period=str(period or ""),
        import_class=import_class, author_id=grant.user_id,
        source=grant.source, ai_accepted=not grant.by_ai)
    session.add(block)
    if str(section.status) == "NOT_STARTED":
        section.status = "DRAFTING"
    row.version = int(row.version) + 1
    session.flush()
    record(session, entity_type="block", action="created", pack=row,
           entity_id=int(block.id), entity_ref=kind,
           narrative=f"A {kind.lower().replace('_', ' ')} block was added to "
                     f"“{section.title}”.", grant=grant)
    readiness.refresh(session, row)
    return _block_dict(block, None)


def update_block(session: Any, block_id: int, principal: Any, *,
                 expected_version: int | None = None,
                 source: str = SOURCE_UI, **changes: Any) -> dict[str, Any]:
    """Change one block.

    Editing the body of an AI draft is how a person accepts it: the words are
    now theirs, so `ai_accepted` follows. An agent editing its own draft does
    not clear that flag on somebody else's behalf.
    """
    block, section, row, grant = access.visible_block(
        session, block_id, principal, source)
    access.assert_editable(row)
    access.may_edit_section(session, section, grant, "change this block")
    _check_version(session, row, expected_version)

    # `import_class` is deliberately NOT here. It is the label that says
    # whether a number is CreditProbe's or somebody's file, and it is set in
    # exactly two places: by the importer when a block is created, and by
    # `import_.map_to_metric`, which first resolves the metric the table is
    # being mapped to. A generic field update that could write it would let a
    # caller relabel an imported table as a governed figure without any
    # metric existing behind it, which is the one lie this product cannot
    # tell.
    allowed = {"title", "body", "statement_kind", "config", "filters",
               "period", "position", "ai_accepted"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidPlaybook(
            f"{', '.join(sorted(unknown))} is not something a block carries. "
            f"Changeable: {', '.join(sorted(allowed))}. A block's type is "
            "fixed once it exists — delete it and add the kind you meant.")
    if "statement_kind" in changes and changes["statement_kind"]:
        _one_of(changes["statement_kind"], STATEMENT_KINDS, "statement kind")
        changes["statement_kind"] = str(changes["statement_kind"]).upper()
    if changes.get("ai_accepted") and grant.by_ai:
        raise PackDenied(
            "Accepting a draft is a person saying the words are theirs now. "
            "An assistant cannot accept its own writing.")

    before = {k: getattr(block, k) for k in changes}
    for field, value in changes.items():
        setattr(block, field, value)
    if "body" in changes and not grant.by_ai:
        block.ai_accepted = True
        block.stale = False
    block.updated_at = datetime.now(UTC)
    moved = _diff(before, changes)
    if moved:
        block.version = int(block.version) + 1
        row.version = int(row.version) + 1
        session.flush()
        record(session, entity_type="block", action="updated", pack=row,
               entity_id=int(block.id), entity_ref=str(block.block_type),
               changes=moved, grant=grant)
        readiness.refresh(session, row)
    figure = (session.get(PlaybookSnapshot, int(block.snapshot_id))
              if block.snapshot_id else None)
    return _block_dict(block, figure)


def delete_block(session: Any, block_id: int, principal: Any, *,
                 source: str = SOURCE_UI) -> None:
    """Take something off a page.

    Blocks are the one Playbook object that IS deleted rather than superseded.
    A block only exists inside a draft — an approved pack's content lives in
    its immutable version document — so removing one destroys no record.
    """
    block, section, row, grant = access.visible_block(
        session, block_id, principal, source)
    access.assert_editable(row)
    access.may_edit_section(session, section, grant, "remove this block")

    kind, ref = str(block.block_type), int(block.id)
    session.delete(block)
    row.version = int(row.version) + 1
    session.flush()
    record(session, entity_type="block", action="deleted", pack=row,
           entity_id=ref, entity_ref=kind,
           narrative=f"A {kind.lower().replace('_', ' ')} block was removed "
                     f"from “{section.title}”.", grant=grant)
    readiness.refresh(session, row)


def reorder(session: Any, pack_id: int, principal: Any, *,
            section_ids: list[int] | None = None,
            block_ids: list[int] | None = None,
            section_id: int | None = None,
            source: str = SOURCE_UI) -> dict[str, Any]:
    """Put the sections of a pack, or the blocks of a section, in an order.

    Takes the whole ordered list rather than a move instruction, because two
    people dragging at once with move instructions produce an order neither
    of them asked for.
    """
    row, grant = access.writable_pack(
        session, pack_id, principal, EDITOR, "reorder this pack", source)

    if section_ids is not None:
        rows = {int(s.id): s for s in session.execute(
            select(PlaybookSection)
            .where(PlaybookSection.pack_id == row.id)).scalars()}
        _assert_complete(set(rows), section_ids, "section")
        for index, sid in enumerate(section_ids):
            rows[int(sid)].position = index
        what = "sections"
    elif block_ids is not None and section_id is not None:
        section, owner_pack, _ = access.visible_section(
            session, section_id, principal, source)
        if int(owner_pack.id) != int(row.id):
            raise PackNotFound(f"No section {section_id} in this pack.")
        rows = {int(b.id): b for b in session.execute(
            select(PlaybookBlock)
            .where(PlaybookBlock.section_id == section.id)).scalars()}
        _assert_complete(set(rows), block_ids, "block")
        for index, bid in enumerate(block_ids):
            rows[int(bid)].position = index
        what = f"blocks of “{section.title}”"
    else:
        raise InvalidPlaybook(
            "Say what to reorder: `section_ids` for the pack's sections, or "
            "`block_ids` with `section_id` for one section's blocks.")

    row.version = int(row.version) + 1
    session.flush()
    record(session, entity_type="pack", action="reordered", pack=row,
           entity_id=int(row.id), entity_ref=str(row.code),
           narrative=f"The {what} were reordered.", grant=grant)
    return _pack_summary(row)


def _assert_complete(known: set[int], given: list[int], what: str) -> None:
    """The order has to name every one of them, exactly once.

    A partial order leaves the unnamed ones at whatever position they held,
    which interleaves them with the new order in a way the person who dragged
    them did not ask for and cannot predict.
    """
    wanted = [int(i) for i in given]
    if len(set(wanted)) != len(wanted):
        raise InvalidPlaybook(f"The same {what} is listed twice.")
    missing = known - set(wanted)
    extra = set(wanted) - known
    if extra:
        raise PackNotFound(
            f"{', '.join(str(i) for i in sorted(extra))} is not a {what} of "
            "this pack.")
    if missing:
        raise InvalidPlaybook(
            f"An order has to name every {what}. Missing: "
            f"{', '.join(str(i) for i in sorted(missing))}.")


# ---------------------------------------------------------------- helpers


def _check_version(session: Any, row: Any, expected: int | None) -> None:
    """Refuse a write against a version that has moved on.

    The refusal names who moved it and what they did, from the event record,
    because "somebody changed this" without saying who sends the caller to
    ask around the floor.
    """
    if expected is None:
        return
    if int(expected) == int(row.version):
        return
    last = session.execute(
        select(PlaybookEvent)
        .where(PlaybookEvent.pack_id == row.id)
        .order_by(PlaybookEvent.id.desc()).limit(1)).scalar_one_or_none()
    who = ""
    if last is not None:
        name = _display_name(session, last.author_id)
        what = str(last.action).replace("_", " ")
        who = f" {name} {what} the {last.entity_type} most recently."
    raise StaleWrite(
        f"This pack has moved on since you opened it — you were editing "
        f"version {expected} and it is now at version {row.version}.{who} "
        "Reload before saving, so nothing of theirs is lost.")


def _display_name(session: Any, user_id: int | None) -> str:
    if user_id is None:
        return "Somebody"
    from backend.db.models import User

    user = session.get(User, int(user_id))
    if user is None:
        return "Somebody"
    parts = [str(getattr(user, "first_name", "") or ""),
             str(getattr(user, "last_name", "") or "")]
    full = " ".join(p for p in parts if p).strip()
    return full or str(getattr(user, "username", "") or "Somebody")


def _user_exists(session: Any, user_id: int | None) -> bool:
    if user_id is None:
        return False
    from backend.db.models import User

    return session.get(User, int(user_id)) is not None


def _required(value: str, what: str) -> str:
    if not str(value or "").strip():
        raise InvalidPlaybook(f"This needs {what}.")
    return str(value)


def _one_of(value: Any, allowed: tuple[str, ...], what: str) -> None:
    if str(value or "").upper() not in allowed:
        raise InvalidPlaybook(
            f"'{value}' is not a {what} this product records. One of: "
            f"{', '.join(allowed)}.")


def _assert_level(grant: access.Grant, level: str, status: str) -> None:
    if grant.at_least(level):
        return
    raise PackDenied(
        f"You have {grant.access.lower()} access to this committee, and "
        f"{level.lower()} access is needed to move a pack to "
        f"{_readable(status)}.")


def _readable(status: str) -> str:
    return str(status).lower().replace("_", " ")


def _slugify(value: str) -> str:
    return _SLUG.sub("-", str(value or "").strip().lower()).strip("-")


def _validate_offsets(offsets: Any) -> dict[str, int]:
    """Per-committee workflow timing, checked rather than trusted.

    A negative offset would schedule a reminder after the meeting; an offset
    of two hundred days would chase people about a pack nobody has started.
    Both are refused with the range said out loud.
    """
    if offsets in (None, {}):
        return dict(DEFAULT_OFFSETS)
    if not isinstance(offsets, dict):
        raise InvalidPlaybook(
            "Workflow timing is a set of named offsets in days before the "
            f"meeting, e.g. {DEFAULT_OFFSETS}.")
    out = dict(DEFAULT_OFFSETS)
    for key, value in offsets.items():
        if key not in DEFAULT_OFFSETS:
            raise InvalidPlaybook(
                f"'{key}' is not a step in the pack workflow. One of: "
                f"{', '.join(DEFAULT_OFFSETS)}.")
        try:
            days = int(value)
        except (TypeError, ValueError):
            raise InvalidPlaybook(
                f"The '{key}' offset is a whole number of days.") from None
        if not 0 <= days <= 180:
            raise InvalidPlaybook(
                f"The '{key}' offset is {days} days before the meeting, and "
                "an offset runs from 0 to 180. A negative one would fire "
                "after the meeting.")
        out[key] = days
    return out


def _validate_sections(sections: Any) -> list:
    """A template's section list, checked before it shapes a hundred packs."""
    if sections in (None, []):
        return []
    if not isinstance(sections, list):
        raise InvalidPlaybook("A template's sections are a list.")
    seen: set[str] = set()
    out = []
    for index, spec in enumerate(sections):
        if not isinstance(spec, dict):
            raise InvalidPlaybook(
                f"Section {index + 1} of this template is not a section "
                "definition.")
        title = str(spec.get("title") or "").strip()
        if not title:
            raise InvalidPlaybook(
                f"Section {index + 1} of this template has no title.")
        key = str(spec.get("key") or _slugify(title))[:64]
        if key in seen:
            raise InvalidPlaybook(
                f"Two sections of this template share the key '{key}'. The "
                "key is how a pack is compared with the previous one, so it "
                "has to identify one section.")
        seen.add(key)
        for block in list(spec.get("blocks") or []):
            if not isinstance(block, dict):
                raise InvalidPlaybook(
                    f"A block of “{title}” is not a block definition.")
            kind = str(block.get("type") or block.get("block_type") or "")
            _one_of(kind, BLOCK_TYPES, "block type")
            if kind.upper() in CALCULATED_BLOCK_TYPES and not str(
                    (block.get("config") or {}).get("metric_id") or "").strip():
                raise InvalidPlaybook(
                    f"A {kind.lower()} block in “{title}” shows a governed "
                    "figure and has to name the metric it shows.")
        out.append({**spec, "key": key, "title": title,
                    "order": int(spec.get("order", index))})
    return out


def _offsets(committee_row: Any) -> dict[str, int]:
    return {**DEFAULT_OFFSETS, **dict(committee_row.workflow_offsets or {})}


def _pack_name(committee_row: Any, period: str, meeting_at: Any) -> str:
    when = period or (meeting_at.date().isoformat()
                      if isinstance(meeting_at, datetime) else "")
    return f"{committee_row.name} — {when}" if when else committee_row.name


def _pack_code(session: Any, committee_row: Any, period: str,
               meeting_at: Any) -> str:
    """A short, unique, readable identifier for the pack.

    Readable because it appears in an export filename and in a meeting
    invitation, and `RCRC-2026-03` tells somebody what they are looking at in
    a way an id does not.
    """
    when = _slugify(period) or (
        meeting_at.date().isoformat() if isinstance(meeting_at, datetime)
        else datetime.now(UTC).date().isoformat())
    base = f"{committee_row.code}-{when}"[:44]
    code = base
    suffix = 2
    while session.execute(select(PlaybookPack.id).where(
            PlaybookPack.code == code)).scalar_one_or_none() is not None:
        code = f"{base}-{suffix}"[:48]
        suffix += 1
    return code


# ------------------------------------------------------------ presentation


def _committee_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id), "code": str(row.code), "name": str(row.name),
        "description": str(row.description), "purpose": str(row.purpose),
        "business_area": str(row.business_area), "cadence": str(row.cadence),
        "meeting_weekday": row.meeting_weekday,
        "default_template_id": row.default_template_id,
        "standard_agenda": list(row.standard_agenda or []),
        "confidentiality": str(row.confidentiality),
        "chair_id": row.chair_id, "secretary_id": row.secretary_id,
        "active": bool(row.active), "demo": bool(row.demo_origin),
        "created_at": _plain(row.created_at),
        "updated_at": _plain(row.updated_at),
    }


def _member_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id), "committee_id": int(row.committee_id),
        "user_id": int(row.user_id), "business_role": str(row.business_role),
        "access_role": str(row.access_role), "title": str(row.title),
        "notify": bool(row.notify), "active": bool(row.active),
    }


def _template_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id), "committee_id": row.committee_id,
        "code": str(row.code), "name": str(row.name),
        "description": str(row.description), "version": int(row.version),
        "status": str(row.status), "sections": list(row.sections or []),
        "materiality": list(row.materiality or []),
        "required_domains": list(row.required_domains or []),
        "required_datasets": list(row.required_datasets or []),
        "export_settings": dict(row.export_settings or {}),
        "confidentiality": str(row.confidentiality),
        "created_at": _plain(row.created_at),
    }


def summary_of(row: Any) -> dict[str, Any]:
    """One pack, as a list screen and every other module reads it.

    Public because generation and export both hand a pack back to a caller
    and neither should invent its own shape — two presenters of one object is
    how a status reads differently on two screens.
    """
    return _pack_summary(row)


def _pack_summary(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id), "code": str(row.code),
        "committee_id": int(row.committee_id), "template_id": row.template_id,
        "name": str(row.name), "period": str(row.period),
        "comparison_period": str(row.comparison_period),
        "meeting_at": _plain(row.meeting_at),
        "as_of_date": _plain(row.as_of_date),
        "data_freeze_at": _plain(row.data_freeze_at),
        "owner_id": row.owner_id, "status": str(row.status),
        "status_label": _readable(row.status).title(),
        "confidentiality": str(row.confidentiality),
        "version": int(row.version), "approved_version": row.approved_version,
        "amends_pack_id": row.amends_pack_id,
        "amendment_reason": str(row.amendment_reason),
        "previous_pack_id": row.previous_pack_id,
        "readiness_percent": int(row.readiness_percent),
        "readiness_state": str(row.readiness_state),
        "readiness_at": _plain(row.readiness_at),
        "data_state": str(row.data_state),
        "approved_by": row.approved_by, "approved_at": _plain(row.approved_at),
        "published_at": _plain(row.published_at),
        "minutes": str(row.minutes), "demo": bool(row.demo_origin),
        "created_at": _plain(row.created_at),
        "updated_at": _plain(row.updated_at),
    }


def _section_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id), "pack_id": int(row.pack_id),
        "template_key": str(row.template_key), "title": str(row.title),
        "purpose": str(row.purpose), "position": int(row.position),
        "owner_id": row.owner_id, "reviewer_id": row.reviewer_id,
        "status": str(row.status), "status_label": _readable(row.status).title(),
        "required": bool(row.required), "due_date": _plain(row.due_date),
        "narrative_instructions": str(row.narrative_instructions),
        "version": int(row.version),
        "submitted_at": _plain(row.submitted_at),
        "approved_at": _plain(row.approved_at), "approved_by": row.approved_by,
        "updated_at": _plain(row.updated_at),
    }


def _block_dict(row: Any, figure: Any) -> dict[str, Any]:
    from backend.playbook import snapshots as snap

    out = {
        "id": int(row.id), "section_id": int(row.section_id),
        "pack_id": int(row.pack_id), "block_type": str(row.block_type),
        "position": int(row.position), "title": str(row.title),
        "body": str(row.body), "statement_kind": str(row.statement_kind),
        "config": dict(row.config or {}), "filters": dict(row.filters or {}),
        "period": str(row.period), "snapshot_id": row.snapshot_id,
        "import_class": str(row.import_class), "author_id": row.author_id,
        "source": str(row.source), "ai_accepted": bool(row.ai_accepted),
        "stale": bool(row.stale), "version": int(row.version),
        "calculated": str(row.block_type) in CALCULATED_BLOCK_TYPES,
        "figure": None,
    }
    if figure is not None:
        out["figure"] = {**snap.from_row(figure).to_dict(),
                         "snapshot_id": int(figure.id),
                         "calculated_at": _plain(figure.calculated_at)}
    return out


def _review_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id), "pack_id": int(row.pack_id),
        "section_id": row.section_id, "scope": str(row.scope),
        "reviewer_id": int(row.reviewer_id), "decision": str(row.decision),
        "note": str(row.note), "conditions": str(row.conditions),
        "at_version": int(row.at_version),
        "requested_at": _plain(row.requested_at),
        "requested_by": row.requested_by,
        "responded_at": _plain(row.responded_at),
    }


__all__ = [
    "DEFAULT_OFFSETS", "InvalidPlaybook", "PackDenied", "PackLocked",
    "PackNotFound", "REVIEWER", "StaleWrite", "TRANSITIONS", "add_member",
    "committee", "committees", "create_block", "create_committee",
    "create_pack", "create_section", "create_template", "delete_block",
    "pack", "packs", "record", "reorder", "request_review", "review_section",
    "set_pack_status", "set_template_status", "submit_section",
    "summary_of", "templates",
    "update_block", "update_committee", "update_member", "update_pack",
    "update_section",
]
