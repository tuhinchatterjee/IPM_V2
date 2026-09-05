"""The sweep that chases people, and the memory that stops it nagging.

A committee pack is late because somebody did not know it was theirs, or knew
and forgot. This is the part of the product that notices, on the committee's
own timing, and tells the one person who can do something about it.

The offsets are the committee's
--------------------------------
Every threshold here is read from `PlaybookCommittee.workflow_offsets` —
`{"inputs": 10, "data_check": 7, "review": 3, "escalate": 1}`, days before the
meeting. A monthly forum and an annual one do not chase people on the same
rhythm, and one hard-coded cadence for every committee is the reason people
turn reminders off.

Fingerprints, and why a reminder loop needs a memory
-----------------------------------------------------
Each message carries a fingerprint built from what it is about and WHEN it is
about — the pack, the entity, the trigger, and the day. A sweep running hourly
would otherwise send the same reminder twenty-four times, and a reminder people
have learned to ignore is worse than none, because it also buries the one that
mattered. The same mechanism the Project Planner uses, for the same reason.

Frozen time
-----------
Every function takes `now`. Nothing here calls `datetime.now()` inside a
decision, so a test can put the clock two days before a meeting and assert what
gets sent, rather than seeding data at an offset from the real clock and hoping
the suite does not run at midnight.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.models.playbook import (
    EDITABLE_PACK_STATUSES,
    SEVERITY_RANK,
    PlaybookAction,
    PlaybookCommittee,
    PlaybookFinding,
    PlaybookMember,
    PlaybookPack,
    PlaybookReminder,
    PlaybookReview,
    PlaybookSection,
)
from backend.playbook import readiness
from backend.playbook.service import DEFAULT_OFFSETS

logger = logging.getLogger(__name__)

#: The job kind this sweep runs under on the existing agent queue. Registered
#: on the platform's worker rather than given a scheduler of its own: that
#: queue already has idempotency, retries and heartbeats, and a second one
#: would be a second thing to operate at three in the morning.
PLAYBOOK_SWEEP = "playbook_sweep"

#: What a message is about, which becomes part of its fingerprint.
TRIGGERS: tuple[str, ...] = (
    "input", "data", "review", "approval", "escalation", "schedule",
    "action", "finding",
)

#: An action is chased this many days before it is due, and again once it is
#: overdue. Not committee-configurable: an action's due date is its own, not
#: the meeting's, and the committee's offsets are about the pack.
ACTION_WARNING_DAYS = 3

#: How far ahead the sweep looks for meetings. Beyond this a pack is not late,
#: it has not started.
HORIZON_DAYS = 30


@dataclass
class Message:
    """One reminder, addressed to one person, about one thing."""

    user_id: int
    committee_id: int
    pack_id: int | None
    entity_type: str
    entity_id: int | None
    trigger: str
    title: str
    body: str
    reason: str
    #: What the notification links to, in the platform's own (type, id) shape.
    link_type: str = "playbook_pack"
    link_id: str = ""

    @property
    def fingerprint(self) -> str:
        """Stable for one person, one thing, one trigger, one day.

        The day is in it on purpose. A reminder that is genuinely still
        outstanding tomorrow SHOULD be sent again tomorrow; what must not
        happen is the same one going out every hour today.
        """
        seed = (f"playbook|{self.user_id}|{self.committee_id}|{self.pack_id}|"
                f"{self.entity_type}|{self.entity_id}|{self.trigger}|"
                f"{self._day}")
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:48]

    _day: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id, "committee_id": self.committee_id,
                "pack_id": self.pack_id, "trigger": self.trigger,
                "title": self.title, "body": self.body,
                "reason": self.reason, "fingerprint": self.fingerprint}


@dataclass
class Sweep:
    """What one pass over the estate did."""

    committees: int = 0
    packs: int = 0
    sent: int = 0
    suppressed: int = 0
    messages: list[Message] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "committees": self.committees, "packs": self.packs,
            "sent": self.sent, "suppressed": self.suppressed,
            "notes": list(self.notes),
            "messages": [m.to_dict() for m in self.messages],
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        if not self.packs:
            return "No committee pack is close enough to its meeting to chase."
        bits = [f"{self.packs} pack{'s' if self.packs != 1 else ''} across "
                f"{self.committees} committee"
                f"{'s' if self.committees != 1 else ''}"]
        bits.append(f"{self.sent} reminder{'s' if self.sent != 1 else ''} sent")
        if self.suppressed:
            bits.append(f"{self.suppressed} already sent today")
        return ", ".join(bits) + "."


def sweep(session: Any, *, now: datetime | None = None,
          committee_id: int | None = None, dry_run: bool = False) -> Sweep:
    """Look at every open pack and chase what is outstanding.

    `dry_run` computes the messages and writes nothing, which is what an
    operator uses to see what a schedule change would do before it does it.
    """
    moment = now or datetime.now(UTC)
    result = Sweep()

    query = select(PlaybookCommittee).where(PlaybookCommittee.active.is_(True))
    if committee_id is not None:
        query = query.where(PlaybookCommittee.id == int(committee_id))
    committees = session.execute(query).scalars().all()

    pending: list[Message] = []
    for committee in committees:
        result.committees += 1
        offsets = {**DEFAULT_OFFSETS, **dict(committee.workflow_offsets or {})}
        members = session.execute(
            select(PlaybookMember).where(
                PlaybookMember.committee_id == committee.id,
                PlaybookMember.active.is_(True),
                PlaybookMember.notify.is_(True))).scalars().all()
        notifiable = {int(m.user_id) for m in members}

        packs = session.execute(
            select(PlaybookPack).where(
                PlaybookPack.committee_id == committee.id,
                PlaybookPack.status.in_(tuple(EDITABLE_PACK_STATUSES)),
                PlaybookPack.meeting_at.isnot(None))).scalars().all()
        for pack in packs:
            days = _days_until(pack.meeting_at, moment)
            if days is None or days > HORIZON_DAYS:
                continue
            result.packs += 1
            pending.extend(_for_pack(session, committee, pack, offsets, days,
                                     notifiable, moment))

        pending.extend(_for_actions(session, committee, notifiable, moment))

    for message in pending:
        message._day = moment.date().isoformat()

    if dry_run:
        result.messages = pending
        result.sent = len(pending)
        result.notes.append(
            "Dry run: nothing was written and nobody was notified.")
        return result

    _deliver(session, pending, result)
    return result


def _days_until(when: Any, now: datetime) -> int | None:
    """Whole days from now to the meeting. Negative once it has passed."""
    if when is None:
        return None
    moment = when if when.tzinfo else when.replace(tzinfo=UTC)
    return (moment.date() - now.date()).days


# ------------------------------------------------------------ what to chase


def _for_pack(session: Any, committee: Any, pack: Any, offsets: dict[str, int],
              days: int, notifiable: set[int], now: datetime) -> list[Message]:
    """Everything outstanding on one pack, addressed to the right person.

    Ordered by the workflow, so a pack ten days out is chased for inputs and a
    pack three days out is chased for reviews. Sending every reminder at every
    stage is how a committee learns to filter the whole channel.
    """
    out: list[Message] = []
    state = readiness.assess(session, pack)
    where = f"{committee.name} — {pack.name}"

    # Inputs: sections nobody has started, chased from the `inputs` offset.
    if days <= int(offsets.get("inputs", 10)):
        for reason in state.checks_named("content"):
            if reason.owner_id and int(reason.owner_id) in notifiable:
                out.append(Message(
                    user_id=int(reason.owner_id),
                    committee_id=int(committee.id), pack_id=int(pack.id),
                    entity_type=reason.entity_type,
                    entity_id=reason.entity_id, trigger="input",
                    title=f"{pack.code}: your section is outstanding",
                    body=f"{reason.text}\n\nThe committee sits in "
                         f"{_in_words(days)}.",
                    reason=reason.text, link_id=str(pack.id)))

    # Data: figures that failed, chased from the `data_check` offset, and to
    # the pack owner rather than to everybody — a broken metric is one
    # person's job to chase.
    if days <= int(offsets.get("data_check", 7)) and pack.owner_id:
        broken = [r for r in state.checks_named("data") if r.blocking]
        if broken and int(pack.owner_id) in notifiable:
            out.append(Message(
                user_id=int(pack.owner_id), committee_id=int(committee.id),
                pack_id=int(pack.id), entity_type="pack",
                entity_id=int(pack.id), trigger="data",
                title=f"{pack.code}: {len(broken)} figure"
                      f"{'s' if len(broken) != 1 else ''} could not be "
                      "calculated",
                body="\n".join(f"• {r.text}" for r in broken[:5])
                     + f"\n\nThe committee sits in {_in_words(days)}.",
                reason=f"{len(broken)} figures unavailable",
                link_id=str(pack.id)))

    # Reviews: named reviewers who have not responded, from the `review`
    # offset.
    if days <= int(offsets.get("review", 3)):
        out.extend(_waiting_reviewers(session, committee, pack, notifiable,
                                      days))

    # Escalation: the chair and the owner, once the pack is inside the last
    # window and still blocked.
    if days <= int(offsets.get("escalate", 1)) and state.blocking:
        for user_id in {committee.chair_id, pack.owner_id}:
            if user_id and int(user_id) in notifiable:
                out.append(Message(
                    user_id=int(user_id), committee_id=int(committee.id),
                    pack_id=int(pack.id), entity_type="pack",
                    entity_id=int(pack.id), trigger="escalation",
                    title=f"{pack.code} is not ready and the committee sits "
                          f"{_in_words(days)}",
                    body=(f"{len(state.blocking)} thing"
                          f"{'s are' if len(state.blocking) != 1 else ' is'} "
                          "blocking it:\n"
                          + "\n".join(f"• {r.text}"
                                      for r in state.blocking[:6])),
                    reason=f"{len(state.blocking)} blocking reasons",
                    link_id=str(pack.id)))

    # Findings nobody has answered, to whoever owns them.
    out.extend(_open_findings(session, committee, pack, notifiable, days,
                              where))
    return out


def _waiting_reviewers(session: Any, committee: Any, pack: Any,
                       notifiable: set[int], days: int) -> list[Message]:
    """Reviewers with a section ready for them and no response given."""
    out: list[Message] = []
    rows = session.execute(
        select(PlaybookSection).where(
            PlaybookSection.pack_id == pack.id,
            PlaybookSection.reviewer_id.isnot(None),
            PlaybookSection.status.in_(
                ("READY_FOR_REVIEW", "IN_REVIEW")))).scalars().all()
    for section in rows:
        given = session.execute(
            select(PlaybookReview).where(
                PlaybookReview.section_id == section.id,
                PlaybookReview.reviewer_id == section.reviewer_id,
                PlaybookReview.at_version >= pack.version,
                PlaybookReview.decision != "PENDING")).scalars().first()
        if given is not None:
            continue
        if int(section.reviewer_id) not in notifiable:
            continue
        out.append(Message(
            user_id=int(section.reviewer_id), committee_id=int(committee.id),
            pack_id=int(pack.id), entity_type="section",
            entity_id=int(section.id), trigger="review",
            title=f"{pack.code}: “{section.title}” is waiting for your review",
            body=(f"It was submitted at version {pack.version} and the "
                  f"committee sits in {_in_words(days)}."),
            reason=f"review outstanding on {section.title}",
            link_id=str(pack.id)))
    return out


def _open_findings(session: Any, committee: Any, pack: Any,
                   notifiable: set[int], days: int, where: str) -> list[Message]:
    """High and critical findings with nobody's answer against them."""
    floor = SEVERITY_RANK[readiness.BLOCKING_SEVERITY]
    rows = session.execute(
        select(PlaybookFinding).where(
            PlaybookFinding.pack_id == pack.id,
            PlaybookFinding.status == "OPEN",
            PlaybookFinding.owner_id.isnot(None))).scalars().all()
    out: list[Message] = []
    for found in rows:
        if SEVERITY_RANK.get(str(found.severity), 0) < floor:
            continue
        if int(found.owner_id) not in notifiable:
            continue
        out.append(Message(
            user_id=int(found.owner_id), committee_id=int(committee.id),
            pack_id=int(pack.id), entity_type="finding",
            entity_id=int(found.id), trigger="finding",
            title=f"{pack.code}: {str(found.severity).lower()} finding needs "
                  "your response",
            body=f"{found.title}\n\n{found.factual_basis}\n\n"
                 f"{where} sits in {_in_words(days)}.",
            reason=found.title, link_id=str(pack.id)))
    return out


def _for_actions(session: Any, committee: Any, notifiable: set[int],
                 now: datetime) -> list[Message]:
    """Committee actions coming due, and ones already past.

    Chased on the ACTION'S own due date rather than the meeting's: an action
    agreed in March and due in May is not a March pack's problem, and chasing
    it at every meeting is how a committee's action log becomes noise.
    """
    from backend.playbook.actions import CLOSED

    out: list[Message] = []
    rows = session.execute(
        select(PlaybookAction).where(
            PlaybookAction.committee_id == committee.id,
            PlaybookAction.due_date.isnot(None),
            PlaybookAction.owner_id.isnot(None),
            PlaybookAction.status.notin_(tuple(CLOSED) + ("DRAFT",)))
    ).scalars().all()
    today = now.date()
    for action in rows:
        if int(action.owner_id) not in notifiable:
            continue
        days = (action.due_date - today).days
        if days > ACTION_WARNING_DAYS:
            continue
        overdue = days < 0
        out.append(Message(
            user_id=int(action.owner_id), committee_id=int(committee.id),
            pack_id=action.pack_id, entity_type="action",
            entity_id=int(action.id), trigger="action",
            title=(f"{action.reference} is {abs(days)} day"
                   f"{'s' if abs(days) != 1 else ''} overdue" if overdue
                   else f"{action.reference} is due {_in_words(days)}"),
            body=f"{action.description}\n\nRaised by {committee.name}."
                 + ("\n\nThere has been no update on it since it was raised."
                    if not str(action.latest_update or "").strip() else ""),
            reason=("overdue" if overdue else "due soon"),
            link_type="playbook_action", link_id=str(action.id)))
    return out


def _in_words(days: int) -> str:
    if days < 0:
        return f"{abs(days)} day{'s' if abs(days) != 1 else ''} ago"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"{days} days"


# ------------------------------------------------------------- delivery


def _deliver(session: Any, pending: list[Message], result: Sweep) -> None:
    """Write the notifications that have not been written before.

    The already-sent set is read in ONE query rather than one per message. A
    sweep over forty committees produces hundreds of candidates, almost all of
    which went out this morning.
    """
    from backend.models.platform import Notification

    if not pending:
        return
    prints = [m.fingerprint for m in pending]
    already = {row for row in session.execute(
        select(PlaybookReminder.fingerprint)
        .where(PlaybookReminder.fingerprint.in_(prints))).scalars()}

    seen: set[str] = set()
    for message in pending:
        if message.fingerprint in already or message.fingerprint in seen:
            result.suppressed += 1
            continue
        seen.add(message.fingerprint)
        note = Notification(
            user_id=message.user_id, kind="playbook",
            title=message.title[:300], body=message.body,
            object_type=message.link_type, object_id=message.link_id,
            actor_id=None)
        session.add(note)
        session.flush()
        session.add(PlaybookReminder(
            pack_id=message.pack_id, committee_id=message.committee_id,
            entity_type=message.entity_type, entity_id=message.entity_id,
            user_id=message.user_id, trigger=message.trigger,
            fingerprint=message.fingerprint, notification_id=int(note.id),
            reason=message.reason[:2000], state="sent"))
        result.messages.append(message)
        result.sent += 1
    session.flush()


# --------------------------------------------------------------- the job


def run_sweep_job(job: Any, should_stop: Any = None) -> dict[str, Any]:
    """The handler the platform's agent worker calls.

    Same shape as every other handler on that queue — `(job, should_stop)` —
    so the worker needs no special case for it.
    """
    from backend.db.engine import get_session

    payload = dict(getattr(job, "payload", None) or {})
    with get_session() as session:
        result = sweep(session, committee_id=payload.get("committee_id"),
                       dry_run=bool(payload.get("dry_run")))
        session.commit()
    logger.info("playbook sweep: %s", result.summary)
    return result.to_dict()


def enqueue_sweep(session: Any, *, committee_id: int | None = None,
                  delay_seconds: int = 0) -> tuple[int, bool]:
    """Ask for a sweep on the existing queue, at most one per hour.

    The idempotency key carries the hour rather than the minute, so an event
    that fires four times in ten minutes produces one sweep.
    """
    from backend.agentic import queue

    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    key = f"playbook-sweep-{committee_id or 'all'}-{hour}"
    return queue.enqueue(
        session, kind=PLAYBOOK_SWEEP, idempotency_key=key,
        payload={"committee_id": committee_id},
        delay_seconds=delay_seconds, timeout_seconds=600)


def next_meeting(committee: Any, *, after: datetime | None = None) -> datetime | None:
    """When this committee next sits, from its cadence and its weekday.

    Returns None where the committee has no weekday or an ad-hoc cadence —
    which is a real answer, not a failure. A forum that meets when it is
    called cannot have its next date computed, and guessing one would put a
    date in front of people that nobody agreed.
    """
    moment = after or datetime.now(UTC)
    cadence = str(committee.cadence or "").upper()
    if cadence == "AD_HOC" or committee.meeting_weekday is None:
        return None
    step = {"WEEKLY": 7, "FORTNIGHTLY": 14, "MONTHLY": 30,
            "QUARTERLY": 91, "SEMI_ANNUAL": 182, "ANNUAL": 365}.get(cadence)
    if step is None:
        return None
    wanted = int(committee.meeting_weekday)
    ahead = (wanted - moment.weekday()) % 7
    first = moment + timedelta(days=ahead or 7)
    return first.replace(hour=9, minute=0, second=0, microsecond=0)


__all__ = [
    "ACTION_WARNING_DAYS", "HORIZON_DAYS", "Message", "PLAYBOOK_SWEEP",
    "Sweep", "TRIGGERS", "enqueue_sweep", "next_meeting", "run_sweep_job",
    "sweep",
]
