"""Who may read a pack, who may change it, and what the AI may never do.

Every read and every write in Playbook comes through this module. Nothing else
loads a pack row by id, because an id in a URL is a guess until somebody checks
it, and the check has to live in one place or it lives in none.

Three questions, kept apart
---------------------------
**Who are you on this committee?** `PlaybookMember.access_role` — VIEWER,
CONTRIBUTOR, REVIEWER, EDITOR, APPROVER, OWNER. A committee's participant list
is the boundary around its packs. CreditProbe has no organisation table, so
this is the boundary, exactly as it is for a Planner project.

**Is the pack still open?** An APPROVED or PUBLISHED pack is immutable. An
OWNER may not edit one either. A correction is an amendment at a new version,
which is a different operation with its own record.

**Which door did the change come through?** A person acting through the UI, and
an agent acting on that person's behalf, are not the same principal. The agent
can never exceed the person, and is additionally capped below approval: there
is no path by which an AI narrative job approves the pack it just wrote.

Not-found and denied
--------------------
A caller who is not on the committee gets `PackNotFound`, the same answer as an
id that does not exist. Telling those apart lets somebody walk the id space and
learn which packs the bank holds, which committees sit, and how often — from a
403 alone, without ever reading a figure. `PackDenied` is only ever raised at
somebody who can already see the object.

The administrative exception, stated rather than hidden
-------------------------------------------------------
A platform ADMIN reaches any committee. That is the power an administrator
already has over every other object here, every use of it is stamped
`administrative=True` in the event record, and the alternative is that a
committee whose only owner has left the bank cannot be repaired. It is not a
licence to write on somebody's behalf silently: the event says who did it and
that they did it as an administrator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from backend.api.permissions import Role
from backend.models.playbook import (
    ACCESS_RANK,
    ACCESS_ROLES,
    EDITABLE_PACK_STATUSES,
    LOCKED_PACK_STATUSES,
    SOURCE_AI,
    SOURCE_AI_CHAT,
    SOURCE_UI,
    SOURCES,
    PlaybookAction,
    PlaybookBlock,
    PlaybookCommittee,
    PlaybookDecision,
    PlaybookFinding,
    PlaybookMember,
    PlaybookPack,
    PlaybookReview,
    PlaybookSection,
    PlaybookSnapshot,
    PlaybookSource,
)

# The six access roles, spelled out so callers need not index a tuple.
VIEWER = "VIEWER"
CONTRIBUTOR = "CONTRIBUTOR"
REVIEWER = "REVIEWER"
EDITOR = "EDITOR"
APPROVER = "APPROVER"
OWNER = "OWNER"

#: The highest access an AI-sourced call may ever exercise, whoever it is
#: acting for. An agent may draft, refresh, comment and raise a finding. It may
#: not approve, publish, decide, or close an action — and this ceiling holds
#: even when the human on whose behalf it runs is the committee OWNER.
#:
#: The ceiling alone is NOT what stops an agent recording a review. REVIEWER
#: sits BELOW EDITOR in `ACCESS_RANK` — a reviewer on a committee is less
#: senior than an editor — so a cap at EDITOR still satisfies `at_least(
#: REVIEWER)`. Reviewing, approving, publishing and the rest of `AI_FORBIDDEN`
#: are refused by an explicit `by_ai` check at the operation, not by rank.
#:
#: Worth stating rather than leaving to be rediscovered: a reading in which the
#: rank cap were the only mechanism would leave the review record open, and it
#: would look closed.
AI_CEILING = EDITOR

#: Operations no AI tool exists for, at any privilege. Kept here rather than
#: only in the tool registry so that a future tool cannot acquire one by being
#: registered: `refuse_ai` is called inside the service function itself.
AI_FORBIDDEN: dict[str, str] = {
    "approve_pack":
        "Approving a pack is a person putting their name to it. There is no "
        "tool for this and there is not going to be one.",
    "approve_section":
        "A section approval is a named reviewer saying they have read it. An "
        "agent cannot say that on their behalf.",
    "publish_pack":
        "Publishing sends the pack to the committee. A person decides when "
        "that happens.",
    "record_review":
        "A review records that a particular person read a particular version. "
        "Recording one for them would make every review in the system "
        "unreliable.",
    "decide":
        "The committee decides. An agent may draft the paper that asks for the "
        "decision and may never record the answer.",
    "close_action":
        "Closing an action asserts the work was done. The owner asserts that.",
    "dismiss_finding":
        "Dismissing a finding is management accepting a risk. It needs a name "
        "against it.",
    "change_meeting_date":
        "Moving a committed meeting date affects other people's diaries.",
    "edit_formula":
        "Metric formulas are governed in the metric catalogue and changed "
        "through it, by a data steward.",
    "edit_approved_pack":
        "An approved pack is a historical record. Correcting one is an "
        "amendment, raised by a person.",
    "delete_pack":
        "Packs are not deleted by software.",
    "import_document":
        "Importing somebody's existing pack brings ungoverned content into "
        "CreditProbe. A person does that, and says what the content is.",
    "delete_section":
        "Removing a page from a pack under review is a person's decision.",
}


class PackNotFound(LookupError):
    """No such object — or none this caller is allowed to know about.

    One exception for both, on purpose. See the module docstring.
    """


class PackDenied(PermissionError):
    """The caller can see this pack but may not do this to it."""


class PackLocked(PermissionError):
    """The pack has been approved and is not editable by anybody.

    Separate from `PackDenied` because the answer to it is different: denied
    means ask for access, locked means raise an amendment.
    """


@dataclass(frozen=True)
class Grant:
    """What one caller may do on one committee."""

    committee_id: int
    user_id: int | None
    access: str
    business_role: str = ""
    #: True where this comes from the platform ADMIN role rather than from a
    #: membership row. Recorded on every event written under it.
    administrative: bool = False
    #: The door the call came through — UI, API, AI, AI_CHAT, IMPORT, SYSTEM.
    #: An AI-sourced grant is capped at `AI_CEILING` before it is returned, so
    #: `at_least` needs no special case and cannot be bypassed by forgetting
    #: one.
    source: str = SOURCE_UI

    def at_least(self, level: str) -> bool:
        """Whether this grant reaches `level`.

        An unknown level is never satisfied. A typo in a required level must
        fail closed; the alternative is a permission check that silently
        passes everyone.
        """
        if self.access not in ACCESS_RANK or level not in ACCESS_RANK:
            return False
        return ACCESS_RANK[self.access] >= ACCESS_RANK[level]

    @property
    def by_ai(self) -> bool:
        return self.source in (SOURCE_AI, SOURCE_AI_CHAT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "committee_id": self.committee_id,
            "user_id": self.user_id,
            "access": self.access,
            "business_role": self.business_role,
            "administrative": self.administrative,
            "source": self.source,
        }


# ------------------------------------------------------------------ helpers


def _role_of(principal: Any) -> str:
    role = getattr(principal, "role", None)
    return str(getattr(role, "value", role) or "").upper()


def _user_of(principal: Any) -> int | None:
    found = getattr(principal, "user_id", None)
    try:
        return int(found) if found is not None else None
    except (TypeError, ValueError):
        return None


def is_admin(principal: Any) -> bool:
    return _role_of(principal) == Role.ADMIN.value


def normalise_source(source: str | None) -> str:
    """A source value, defaulting to UI and refusing anything unrecognised.

    An unknown source silently becoming "UI" would let a caller launder an AI
    write into a human one by sending a typo, so anything outside the
    vocabulary raises.

    None and "" DO become UI, because at a Python call boundary they are
    indistinguishable from the argument not being passed at all. The property
    that makes that safe is architectural rather than defensive: the source is
    decided by which code path is executing — the router passes UI, the agent
    tool passes AI — and is NEVER read from a request body or a tool argument.
    A caller who could name their own source could name UI, and no amount of
    validation here would help.
    """
    found = str(source or SOURCE_UI).upper()
    if found not in SOURCES:
        raise ValueError(
            f"'{source}' is not a recorded source. One of: "
            f"{', '.join(SOURCES)}.")
    return found


def _capped(access: str, source: str) -> str:
    """The effective access for a call arriving through `source`.

    This is the one place the AI ceiling is applied, and it is applied on the
    way out of `grant`, so every downstream check sees the capped value.
    """
    if source in (SOURCE_AI, SOURCE_AI_CHAT):
        if ACCESS_RANK.get(access, -1) > ACCESS_RANK[AI_CEILING]:
            return AI_CEILING
    return access


def refuse_ai(grant: Grant, operation: str) -> None:
    """Refuse an operation no agent may perform, whatever its access.

    Called inside the service function rather than only at the tool boundary.
    A tool that is added later, or an orchestrator that calls the service
    directly, still cannot reach past this.
    """
    if not grant.by_ai:
        return
    reason = AI_FORBIDDEN.get(operation)
    if reason is None:
        return
    raise PackDenied(reason)


# ----------------------------------------------------------------- the door


def committee_grant(session: Any, committee_id: int, principal: Any,
                    source: str = SOURCE_UI) -> Grant:
    """What this caller may do on this committee, or `PackNotFound`."""
    committee = session.get(PlaybookCommittee, int(committee_id))
    if committee is None:
        raise PackNotFound(f"No committee {committee_id}.")
    return committee_grant_for(session, committee, principal, source)


def committee_grant_for(session: Any, committee: Any, principal: Any,
                        source: str = SOURCE_UI) -> Grant:
    """The same decision when the committee row is already loaded."""
    channel = normalise_source(source)
    user_id = _user_of(principal)

    if user_id is not None:
        row = session.execute(
            select(PlaybookMember).where(
                PlaybookMember.committee_id == committee.id,
                PlaybookMember.user_id == user_id,
                PlaybookMember.active.is_(True))
        ).scalar_one_or_none()
        if row is not None:
            access = str(row.access_role)
            if access not in ACCESS_ROLES:
                # A membership row with a value outside the vocabulary is a
                # data fault, and the safe reading of a fault is the weakest
                # one rather than the one that happens to sort highest.
                access = VIEWER
            return Grant(int(committee.id), user_id, _capped(access, channel),
                         str(row.business_role), source=channel)

    if is_admin(principal):
        return Grant(int(committee.id), user_id, _capped(OWNER, channel),
                     "PLATFORM_ADMIN", administrative=True, source=channel)

    raise PackNotFound(f"No committee {committee.id}.")


def require_committee(session: Any, committee_id: int, principal: Any,
                      level: str, what: str = "do that",
                      source: str = SOURCE_UI) -> Grant:
    """A committee grant reaching `level`, or a refusal naming what is short."""
    found = committee_grant(session, committee_id, principal, source)
    _assert_level(found, level, what)
    return found


def _assert_level(found: Grant, level: str, what: str) -> None:
    if found.at_least(level):
        return
    if found.by_ai and ACCESS_RANK.get(level, 99) > ACCESS_RANK[AI_CEILING]:
        raise PackDenied(
            f"{level.title()} access is needed to {what}, and an assistant "
            f"never holds more than {AI_CEILING.lower()} access however it is "
            "asked. A person has to do this one.")
    raise PackDenied(
        f"You have {found.access.lower()} access to this committee, and "
        f"{level.lower()} access is needed to {what}.")


def pack_grant(session: Any, pack_id: int, principal: Any,
               source: str = SOURCE_UI) -> tuple[Any, Grant]:
    """One pack and the caller's access to it, or `PackNotFound`.

    Pack ids are global. This is where a guessed one is refused, and it is why
    no router ever calls `session.get(PlaybookPack, ...)` itself.
    """
    pack = session.get(PlaybookPack, int(pack_id))
    if pack is None:
        raise PackNotFound(f"No pack {pack_id}.")
    found = committee_grant(session, int(pack.committee_id), principal, source)
    return pack, found


def readable_pack(session: Any, pack_id: int, principal: Any,
                  source: str = SOURCE_UI) -> tuple[Any, Grant]:
    """A pack the caller may read."""
    return pack_grant(session, pack_id, principal, source)


def writable_pack(session: Any, pack_id: int, principal: Any,
                  level: str = CONTRIBUTOR, what: str = "change this pack",
                  source: str = SOURCE_UI) -> tuple[Any, Grant]:
    """A pack the caller may change, in a status that still allows changes.

    Both halves matter and both are checked here so no caller can remember one
    and forget the other.
    """
    pack, found = pack_grant(session, pack_id, principal, source)
    assert_editable(pack)
    _assert_level(found, level, what)
    return pack, found


def assert_editable(pack: Any) -> None:
    """Refuse a write against a pack that has been signed off.

    The message names the amendment route, because "you cannot edit this" with
    no next step is how somebody ends up editing the database directly.
    """
    status = str(pack.status)
    if status in EDITABLE_PACK_STATUSES:
        return
    if status in LOCKED_PACK_STATUSES:
        raise PackLocked(
            f"This pack was {status.lower()} on "
            f"{_when(pack)} and is a historical record now. To correct it, "
            "raise an amendment: that creates a new version alongside this "
            "one and leaves what the committee actually saw intact.")
    raise PackLocked(
        f"This pack is {status.lower().replace('_', ' ')} and is not being "
        "edited.")


def _when(pack: Any) -> str:
    moment = getattr(pack, "approved_at", None) or getattr(
        pack, "published_at", None)
    return moment.date().isoformat() if moment is not None else "sign-off"


# -------------------------------------------------- objects inside the pack
#
# Every one of these takes the CHILD id and finds its pack, rather than
# trusting a pack id the caller also sent. A caller who sends pack 4 and
# section 900 must not be able to edit section 900 because they can read pack
# 4 — and that is exactly the shape the bug takes when the two are checked
# independently.


def visible_section(session: Any, section_id: int, principal: Any,
                    source: str = SOURCE_UI) -> tuple[Any, Any, Grant]:
    """(section, pack, grant) — or `PackNotFound`."""
    section = session.get(PlaybookSection, int(section_id))
    if section is None:
        raise PackNotFound(f"No section {section_id}.")
    pack, found = pack_grant(session, int(section.pack_id), principal, source)
    return section, pack, found


def visible_block(session: Any, block_id: int, principal: Any,
                  source: str = SOURCE_UI) -> tuple[Any, Any, Any, Grant]:
    """(block, section, pack, grant) — or `PackNotFound`."""
    block = session.get(PlaybookBlock, int(block_id))
    if block is None:
        raise PackNotFound(f"No block {block_id}.")
    section = session.get(PlaybookSection, int(block.section_id))
    if section is None:
        raise PackNotFound(f"No block {block_id}.")
    pack, found = pack_grant(session, int(section.pack_id), principal, source)
    return block, section, pack, found


def visible_snapshot(session: Any, snapshot_id: int, principal: Any,
                     source: str = SOURCE_UI) -> tuple[Any, Any, Grant]:
    """(snapshot, pack, grant). Snapshots carry the working behind a figure."""
    snapshot = session.get(PlaybookSnapshot, int(snapshot_id))
    if snapshot is None:
        raise PackNotFound(f"No calculation {snapshot_id}.")
    pack, found = pack_grant(session, int(snapshot.pack_id), principal, source)
    return snapshot, pack, found


def visible_finding(session: Any, finding_id: int, principal: Any,
                    source: str = SOURCE_UI) -> tuple[Any, Any, Grant]:
    finding = session.get(PlaybookFinding, int(finding_id))
    if finding is None:
        raise PackNotFound(f"No finding {finding_id}.")
    pack, found = pack_grant(session, int(finding.pack_id), principal, source)
    return finding, pack, found


def visible_decision(session: Any, decision_id: int, principal: Any,
                     source: str = SOURCE_UI) -> tuple[Any, Any | None, Grant]:
    """(decision, pack-or-None, grant).

    A decision outlives the pack it was raised in — a decision log is read by
    committee, not by pack — so `pack_id` may be null and the authorisation
    falls back to the committee.
    """
    decision = session.get(PlaybookDecision, int(decision_id))
    if decision is None:
        raise PackNotFound(f"No decision {decision_id}.")
    pack = None
    if decision.pack_id is not None:
        pack = session.get(PlaybookPack, int(decision.pack_id))
    found = committee_grant(session, int(decision.committee_id), principal,
                            source)
    return decision, pack, found


def visible_action(session: Any, action_id: int, principal: Any,
                   source: str = SOURCE_UI) -> tuple[Any, Any | None, Grant]:
    """(action, pack-or-None, grant). Same reasoning as a decision."""
    action = session.get(PlaybookAction, int(action_id))
    if action is None:
        raise PackNotFound(f"No action {action_id}.")
    pack = None
    if action.pack_id is not None:
        pack = session.get(PlaybookPack, int(action.pack_id))
    found = committee_grant(session, int(action.committee_id), principal,
                            source)
    return action, pack, found


def visible_review(session: Any, review_id: int, principal: Any,
                   source: str = SOURCE_UI) -> tuple[Any, Any, Grant]:
    review = session.get(PlaybookReview, int(review_id))
    if review is None:
        raise PackNotFound(f"No review {review_id}.")
    pack, found = pack_grant(session, int(review.pack_id), principal, source)
    return review, pack, found


def visible_source(session: Any, source_id: int, principal: Any,
                   source: str = SOURCE_UI) -> tuple[Any, Any, Grant]:
    """(source row, pack, grant).

    This is the one that guards a download. A source row names a file on disk,
    and an unauthorised read here is the difference between a committee pack
    and a public one.
    """
    row = session.get(PlaybookSource, int(source_id))
    if row is None:
        raise PackNotFound(f"No source {source_id}.")
    pack, found = pack_grant(session, int(row.pack_id), principal, source)
    return row, pack, found


# ----------------------------------------------------- finer-grained writes


def may_edit_section(session: Any, section: Any, grant: Grant,
                     what: str = "edit this section") -> None:
    """Whether this caller may change this particular section.

    CONTRIBUTOR is why this exists rather than a bare level check. A
    contributor writes the section they were given and nobody else's. Being
    able to rewrite any section of a pack you contribute one page to is not
    contribution.
    """
    if grant.at_least(EDITOR):
        return
    if not grant.at_least(CONTRIBUTOR):
        raise PackDenied(
            "You can read this pack but not write in it. Contributor access "
            f"is needed to {what}.")
    if grant.user_id is not None and section.owner_id == grant.user_id:
        return
    raise PackDenied(
        f"“{section.title}” belongs to somebody else. Contributors write the "
        "sections they own; editing another person's section needs editor "
        "access to the committee.")


def may_review_section(section: Any, grant: Grant) -> None:
    """Whether this caller may record a review of this section.

    A named reviewer may review the section they were named on. REVIEWER
    access is the general permission; the named reviewer keeps it even at
    CONTRIBUTOR, because being asked to review something and then refused is
    the failure that looks like the software being broken.
    """
    if grant.by_ai:
        raise PackDenied(AI_FORBIDDEN["record_review"])
    if grant.user_id is not None and section.reviewer_id == grant.user_id:
        return
    if grant.at_least(REVIEWER):
        return
    raise PackDenied(
        "Reviewer access is needed to review a section, and you are not the "
        f"named reviewer of “{section.title}”.")


def may_approve_pack(pack: Any, grant: Grant) -> None:
    """Whether this caller may approve the whole pack.

    Three separate refusals, because they need three different answers:
    an agent must be told no tool exists, a reviewer must be told they need
    approver access, and an author must be told they cannot approve their own
    work.
    """
    if grant.by_ai:
        raise PackDenied(AI_FORBIDDEN["approve_pack"])
    if not grant.at_least(APPROVER):
        raise PackDenied(
            f"You have {grant.access.lower()} access to this committee. "
            "Approving a pack needs approver access.")
    if (grant.user_id is not None and pack.owner_id == grant.user_id
            and not grant.administrative):
        raise PackDenied(
            "You own this pack, so you cannot also be the person who approves "
            "it. Ask another approver on the committee.")


def readable_committee_ids(session: Any, principal: Any) -> list[int]:
    """Every committee this caller may see, in one query.

    The list screen and every "across my committees" question start here.
    Asking per committee is the difference between a page that loads and a
    page that times out at forty forums.
    """
    if is_admin(principal):
        return [int(i) for i in session.execute(
            select(PlaybookCommittee.id)).scalars()]
    user_id = _user_of(principal)
    if user_id is None:
        return []
    return [int(i) for i in session.execute(
        select(PlaybookMember.committee_id).where(
            PlaybookMember.user_id == user_id,
            PlaybookMember.active.is_(True))).scalars()]


def grants_for(session: Any, principal: Any,
               source: str = SOURCE_UI) -> dict[int, Grant]:
    """The caller's access to every committee they can see, in one query."""
    channel = normalise_source(source)
    user_id = _user_of(principal)
    if is_admin(principal):
        return {
            int(i): Grant(int(i), user_id, _capped(OWNER, channel),
                          "PLATFORM_ADMIN", administrative=True,
                          source=channel)
            for i in session.execute(select(PlaybookCommittee.id)).scalars()}
    if user_id is None:
        return {}
    rows = session.execute(
        select(PlaybookMember).where(
            PlaybookMember.user_id == user_id,
            PlaybookMember.active.is_(True))).scalars()
    return {
        int(r.committee_id): Grant(
            int(r.committee_id), user_id,
            _capped(str(r.access_role), channel), str(r.business_role),
            source=channel)
        for r in rows}


def readable_pack_ids(session: Any, principal: Any, *,
                      committee_id: int | None = None) -> list[int]:
    """Every pack the caller may read. One query after the committee list.

    `committee_id` narrows to one committee, and narrows by INTERSECTION
    rather than by replacing the readable set: asking about a committee the
    caller cannot read returns nothing rather than that committee's packs.
    """
    committees = readable_committee_ids(session, principal)
    if committee_id is not None:
        committees = [i for i in committees if int(i) == int(committee_id)]
    if not committees:
        return []
    return [int(i) for i in session.execute(
        select(PlaybookPack.id).where(
            PlaybookPack.committee_id.in_(committees))).scalars()]


__all__ = [
    "AI_CEILING", "AI_FORBIDDEN", "APPROVER", "CONTRIBUTOR", "EDITOR",
    "Grant", "OWNER", "PackDenied", "PackLocked", "PackNotFound", "REVIEWER",
    "VIEWER", "assert_editable", "committee_grant", "committee_grant_for",
    "grants_for", "is_admin", "may_approve_pack", "may_edit_section",
    "may_review_section", "normalise_source", "pack_grant",
    "readable_committee_ids", "readable_pack", "readable_pack_ids",
    "refuse_ai", "require_committee", "visible_action", "visible_block",
    "visible_decision", "visible_finding", "visible_review", "visible_section",
    "visible_snapshot", "visible_source", "writable_pack",
]
