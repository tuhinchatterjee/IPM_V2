"""Whether a pack can go to committee, and precisely why not.

Readiness is CALCULATED from the facts every time it is asked for. The pack row
caches the last answer alongside the moment it was computed, and nothing trusts
the cache without that timestamp. A stored percentage nobody can explain — or
one written by a process that has since been superseded — is exactly the number
that gets a pack tabled when it should not have been.

What "88%" has to mean
----------------------
Nothing, on its own. The percentage is a progress bar; the REASONS are the
product. Every reason names the thing that is not done and the person it is
waiting on, because "Data readiness: amber" sends the pack owner to ask three
people what they are missing, and "Retail default rate has no value for July —
no account's performance window has closed" does not.

Amber and red
-------------
    GREEN   nothing is blocking; the pack can be tabled
    AMBER   something is outstanding but none of it blocks approval
    RED     at least one blocking reason

Blocking is a property of the CHECK, not of the score. A pack can be at 94% and
red, because the one thing missing is a required section nobody has written.
Deriving the state from the percentage would let a pack cross a threshold into
green while still missing the only section the committee asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.models.playbook import (
    CALCULATED_BLOCK_TYPES,
    SEVERITY_RANK,
    PlaybookAction,
    PlaybookBlock,
    PlaybookDecision,
    PlaybookFinding,
    PlaybookReview,
    PlaybookSection,
    PlaybookSnapshot,
)
from backend.playbook import snapshots as snap

GREEN = "GREEN"
AMBER = "AMBER"
RED = "RED"

#: Section statuses that count as the owner having finished their part.
SECTION_DONE = frozenset({"READY_FOR_REVIEW", "IN_REVIEW", "APPROVED", "LOCKED"})
SECTION_SIGNED_OFF = frozenset({"APPROVED", "LOCKED"})

#: Findings at or above this severity must have a response before approval.
#: Below it, an open finding is worth saying and is not worth blocking on.
BLOCKING_SEVERITY = "HIGH"

#: Finding statuses that mean somebody has dealt with it.
FINDING_ANSWERED = frozenset({
    "ACKNOWLEDGED", "EXPLAINED", "ACTIONED", "DISMISSED", "RESOLVED"})

#: The checks, in the order a pack owner would work through them, with the
#: share of the progress bar each carries. Weights rather than an equal split
#: because writing the sections is most of the work and setting the meeting
#: date is not.
WEIGHTS: dict[str, int] = {
    "schedule": 5,
    "data": 25,
    "content": 30,
    "narrative": 10,
    "findings": 10,
    "decisions": 5,
    "actions": 5,
    "review": 10,
}


@dataclass
class Reason:
    """One thing that is not done, said in a sentence somebody can act on."""

    check: str
    #: True where this stops the pack going to committee.
    blocking: bool
    text: str
    #: What it is about, so the screen can link straight to it.
    entity_type: str = ""
    entity_id: int | None = None
    #: Who it is waiting on, where there is somebody.
    owner_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.check, "blocking": self.blocking,
                "text": self.text, "entity_type": self.entity_type,
                "entity_id": self.entity_id, "owner_id": self.owner_id}


@dataclass
class Check:
    """One dimension of readiness: how far it has got, and what is left."""

    key: str
    label: str
    weight: int
    #: 0.0 to 1.0. The share of this check that is complete.
    progress: float = 0.0
    reasons: list[Reason] = field(default_factory=list)
    #: Set where the check could not be run at all — which is not the same as
    #: the check failing, and must not silently score zero.
    not_assessed: str = ""

    @property
    def state(self) -> str:
        if any(r.blocking for r in self.reasons):
            return RED
        if self.reasons or self.not_assessed:
            return AMBER
        return GREEN

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "weight": self.weight,
                "progress": round(self.progress, 4), "state": self.state,
                "not_assessed": self.not_assessed,
                "reasons": [r.to_dict() for r in self.reasons]}


@dataclass
class Readiness:
    """The whole answer, with the moment it was computed attached to it."""

    percent: int
    state: str
    data_state: str
    checks: list[Check]
    computed_at: datetime

    @property
    def reasons(self) -> list[Reason]:
        out: list[Reason] = []
        for check in self.checks:
            out.extend(check.reasons)
        # Blocking first: a pack owner opening this sees what stops them
        # before what merely bothers them.
        return sorted(out, key=lambda r: (not r.blocking, r.check))

    @property
    def blocking(self) -> list[Reason]:
        return [r for r in self.reasons if r.blocking]

    def to_dict(self) -> dict[str, Any]:
        return {
            "percent": self.percent,
            "state": self.state,
            "data_state": self.data_state,
            "computed_at": self.computed_at.isoformat(),
            "checks": [c.to_dict() for c in self.checks],
            "reasons": [r.to_dict() for r in self.reasons],
            "blocking_count": len(self.blocking),
        }


# --------------------------------------------------------------- the checks


def assess(session: Any, pack: Any) -> Readiness:
    """Work out, now, whether this pack can go to committee.

    Reads only what is stored. Deliberately does not recalculate metrics: a
    readiness check that re-runs the whole pack takes minutes and would be run
    by a scheduler on every pack every hour. What it asks is whether the
    snapshots the pack HAS are usable, which is the question that matters and
    is answerable from one query.
    """
    sections = list(session.execute(
        select(PlaybookSection).where(PlaybookSection.pack_id == pack.id)
        .order_by(PlaybookSection.position)).scalars())
    blocks = list(session.execute(
        select(PlaybookBlock).where(PlaybookBlock.pack_id == pack.id)
        .order_by(PlaybookBlock.position)).scalars())

    checks = [
        _schedule(pack),
        _data(session, pack, blocks),
        _content(sections),
        _narrative(blocks),
        _findings(session, pack),
        _decisions(session, pack, blocks),
        _actions(session, pack),
        _review(session, pack, sections),
    ]

    percent = _score(checks)
    state = RED if any(c.state == RED for c in checks) else (
        AMBER if any(c.state == AMBER for c in checks) else GREEN)
    data_state = next(c.state for c in checks if c.key == "data")
    return Readiness(percent=percent, state=state, data_state=data_state,
                     checks=checks, computed_at=datetime.now(UTC))


def _score(checks: list[Check]) -> int:
    """The progress bar.

    A check that could not be assessed contributes nothing and does not
    inflate the denominator either: scoring an unknown as complete is how a
    pack reports 100% while nobody has looked at a third of it.
    """
    total = sum(c.weight for c in checks if not c.not_assessed)
    if total <= 0:
        return 0
    earned = sum(c.weight * max(0.0, min(1.0, c.progress))
                 for c in checks if not c.not_assessed)
    return int(round(100.0 * earned / total))


def _schedule(pack: Any) -> Check:
    check = Check("schedule", "Meeting and period", WEIGHTS["schedule"])
    done = 0
    wanted = 3
    if pack.meeting_at is not None:
        done += 1
    else:
        check.reasons.append(Reason(
            "schedule", True, "This pack has no meeting date, so nothing can "
            "be scheduled against it and nobody can be chased.",
            "pack", int(pack.id), pack.owner_id))
    if str(pack.period or ""):
        done += 1
    else:
        check.reasons.append(Reason(
            "schedule", True, "This pack has no reporting period, so its "
            "figures would have nothing to be as at.",
            "pack", int(pack.id), pack.owner_id))
    if pack.owner_id is not None:
        done += 1
    else:
        check.reasons.append(Reason(
            "schedule", True, "This pack has no owner. Somebody has to be "
            "answerable for it before it goes to committee.",
            "pack", int(pack.id)))
    check.progress = done / wanted
    return check


def _data(session: Any, pack: Any, blocks: list[Any]) -> Check:
    """Whether the governed figures in this pack are actually there.

    The most important check, and the one that has to be most careful about
    what it calls a failure. A metric with no value because the outcome has
    not matured is a fact about the calendar and blocks nothing; a metric
    whose calculation broke is a platform problem and blocks everything.
    """
    check = Check("data", "Data readiness", WEIGHTS["data"])
    wanted = [b for b in blocks if b.block_type in CALCULATED_BLOCK_TYPES]
    if not wanted:
        check.not_assessed = (
            "This pack has no calculated figures in it yet.")
        return check

    ids = [int(b.snapshot_id) for b in wanted if b.snapshot_id is not None]
    rows = {}
    if ids:
        rows = {int(r.id): r for r in session.execute(
            select(PlaybookSnapshot)
            .where(PlaybookSnapshot.id.in_(ids))).scalars()}

    good = 0
    for block in wanted:
        row = rows.get(int(block.snapshot_id)) if block.snapshot_id else None
        if row is None:
            check.reasons.append(Reason(
                "data", True,
                f"“{block.title or block.block_type.title()}” has not been "
                "calculated yet, so the pack has a placeholder where a figure "
                "should be.", "block", int(block.id)))
            continue

        availability = str(row.availability)
        if availability == snap.OK:
            good += 1
            continue

        # Everything below has no number. What separates them is whether the
        # committee can be given the pack anyway.
        if availability in (snap.NOT_MATURED, snap.NO_DATA, snap.PERIOD_MISSING):
            # Not blocking. These are facts about the book and the calendar,
            # and a pack that states them plainly is a better pack than one
            # that waits for them to change.
            good += 1
            check.reasons.append(Reason(
                "data", False,
                f"“{row.metric_name or row.metric_id}”: "
                f"{row.unavailable_reason}",
                "block", int(block.id)))
        elif availability == snap.NOT_AUTHORISED:
            check.reasons.append(Reason(
                "data", True,
                f"“{row.metric_name or row.metric_id}” could not be read by "
                "the person who generated this pack. Somebody with access to "
                "that source has to refresh it.",
                "block", int(block.id), pack.owner_id))
        else:
            check.reasons.append(Reason(
                "data", True,
                f"“{row.metric_name or row.metric_id}” failed to calculate: "
                f"{row.unavailable_reason}",
                "block", int(block.id), pack.owner_id))

    check.progress = good / len(wanted)
    return check


def _content(sections: list[Any]) -> Check:
    """Whether the people who owe sections have written them."""
    check = Check("content", "Sections written", WEIGHTS["content"])
    required = [s for s in sections if s.required]
    if not required:
        check.not_assessed = "This pack has no required sections."
        return check

    done = 0
    for section in required:
        if str(section.status) in SECTION_DONE:
            done += 1
            continue
        waiting = "nobody" if section.owner_id is None else "its owner"
        check.reasons.append(Reason(
            "content", True,
            f"“{section.title}” is "
            f"{str(section.status).lower().replace('_', ' ')} and is still "
            f"with {waiting}.",
            "section", int(section.id), section.owner_id))
    check.progress = done / len(required)
    return check


def _narrative(blocks: list[Any]) -> Check:
    """Whether a person has stood behind the words a machine drafted.

    An AI narrative nobody has accepted is a draft. A pack going to committee
    with unaccepted machine prose in it is the single failure this product
    exists to prevent, so it blocks.
    """
    check = Check("narrative", "Commentary accepted", WEIGHTS["narrative"])
    drafted = [b for b in blocks if b.block_type == "AI_NARRATIVE"]
    if not drafted:
        check.not_assessed = "This pack has no AI-drafted commentary."
        return check

    done = 0
    for block in drafted:
        if block.stale:
            check.reasons.append(Reason(
                "narrative", True,
                f"“{block.title or 'A commentary block'}” was written about "
                "figures that have since changed, so it has to be re-read "
                "before it goes anywhere.", "block", int(block.id)))
            continue
        if not block.ai_accepted:
            check.reasons.append(Reason(
                "narrative", True,
                f"“{block.title or 'A commentary block'}” is a draft nobody "
                "has accepted. Somebody has to put their name to it.",
                "block", int(block.id), block.author_id))
            continue
        done += 1
    check.progress = done / len(drafted)
    return check


def _findings(session: Any, pack: Any) -> Check:
    """Whether the material observations have been answered."""
    check = Check("findings", "Findings answered", WEIGHTS["findings"])
    rows = list(session.execute(
        select(PlaybookFinding)
        .where(PlaybookFinding.pack_id == pack.id)).scalars())
    if not rows:
        check.not_assessed = "Nothing material has been raised on this pack."
        return check

    floor = SEVERITY_RANK[BLOCKING_SEVERITY]
    done = 0
    for finding in rows:
        if str(finding.status) in FINDING_ANSWERED:
            done += 1
            continue
        serious = SEVERITY_RANK.get(str(finding.severity), 0) >= floor
        check.reasons.append(Reason(
            "findings", serious,
            f"{str(finding.severity).title()}: “{finding.title}” has not been "
            "answered.", "finding", int(finding.id), finding.owner_id))
    check.progress = done / len(rows)
    return check


def _decisions(session: Any, pack: Any, blocks: list[Any]) -> Check:
    """Whether every decision the pack asks for has actually been drafted.

    A DECISION_REQUEST block with no decision behind it is a slide that asks
    a committee to approve something the pack never defines.
    """
    check = Check("decisions", "Decisions framed", WEIGHTS["decisions"])
    asks = [b for b in blocks if b.block_type == "DECISION_REQUEST"]
    if not asks:
        check.not_assessed = "This pack asks the committee for no decisions."
        return check

    rows = list(session.execute(
        select(PlaybookDecision)
        .where(PlaybookDecision.pack_id == pack.id)).scalars())
    ready = [d for d in rows if str(d.status) != "DRAFT" and str(d.question)]
    if len(ready) >= len(asks):
        check.progress = 1.0
        return check

    check.progress = (len(ready) / len(asks)) if asks else 0.0
    check.reasons.append(Reason(
        "decisions", True,
        f"This pack has {len(asks)} decision request"
        f"{'s' if len(asks) != 1 else ''} on its pages and "
        f"{len(ready)} written up. A committee cannot decide something the "
        "pack has not put to it.", "pack", int(pack.id), pack.owner_id))
    return check


def _actions(session: Any, pack: Any) -> Check:
    """Whether the actions this committee is carrying have been updated.

    Not blocking. An overdue action is the committee's business to discuss,
    and holding the pack back until somebody closes it would be the software
    deciding what the meeting is for.
    """
    check = Check("actions", "Actions updated", WEIGHTS["actions"])
    rows = list(session.execute(
        select(PlaybookAction).where(
            PlaybookAction.committee_id == pack.committee_id,
            PlaybookAction.status.in_(("OPEN", "IN_PROGRESS", "BLOCKED")))
    ).scalars())
    if not rows:
        check.not_assessed = "This committee is carrying no open actions."
        return check

    done = 0
    for action in rows:
        if str(action.latest_update or "").strip():
            done += 1
            continue
        check.reasons.append(Reason(
            "actions", False,
            f"{action.reference or 'An action'} has no update since it was "
            "raised, so the pack cannot say where it stands.",
            "action", int(action.id), action.owner_id))
    check.progress = done / len(rows)
    return check


def _review(session: Any, pack: Any, sections: list[Any]) -> Check:
    """Whether the named reviewers have reviewed the version that exists now.

    Version-aware on purpose. A reviewer who approved version 4 has not
    approved version 5, and a readiness check that counts their old approval
    is how a pack reaches committee carrying a paragraph nobody signed off.
    """
    check = Check("review", "Reviews complete", WEIGHTS["review"])
    wanted = [s for s in sections if s.required and s.reviewer_id is not None]
    if not wanted:
        check.not_assessed = "No section of this pack has a named reviewer."
        return check

    rows = list(session.execute(
        select(PlaybookReview).where(
            PlaybookReview.pack_id == pack.id,
            PlaybookReview.scope == "SECTION")).scalars())
    given: dict[int, list[Any]] = {}
    for row in rows:
        if row.section_id is not None:
            given.setdefault(int(row.section_id), []).append(row)

    version = int(pack.version)
    done = 0
    for section in wanted:
        mine = given.get(int(section.id), [])
        current = [r for r in mine if int(r.at_version) >= version]
        approved = [r for r in current if str(r.decision) == "APPROVED"]
        changes = [r for r in current if str(r.decision) == "CHANGES_REQUESTED"]

        if changes:
            check.reasons.append(Reason(
                "review", True,
                f"“{section.title}”: the reviewer has asked for changes.",
                "section", int(section.id), section.owner_id))
            continue
        if approved:
            done += 1
            continue
        stale = [r for r in mine if int(r.at_version) < version
                 and str(r.decision) == "APPROVED"]
        if stale:
            check.reasons.append(Reason(
                "review", True,
                f"“{section.title}” was approved at version "
                f"{max(int(r.at_version) for r in stale)} and the pack is now "
                f"at version {version}. It has to be looked at again.",
                "section", int(section.id), section.reviewer_id))
            continue
        check.reasons.append(Reason(
            "review", True,
            f"“{section.title}” is waiting on its reviewer.",
            "section", int(section.id), section.reviewer_id))
    check.progress = done / len(wanted)
    return check


# ------------------------------------------------------------------ caching


def refresh(session: Any, pack: Any) -> Readiness:
    """Assess and write the answer onto the pack, with its timestamp.

    The cache exists so a list of forty packs does not run forty assessments.
    It is written here and read nowhere that matters: any screen showing a
    single pack asks `assess` directly, because a stale amber on the screen
    somebody is working on is worse than the query it saved.
    """
    outcome = assess(session, pack)
    pack.readiness_percent = outcome.percent
    pack.readiness_state = outcome.state
    pack.readiness_at = outcome.computed_at
    pack.readiness_reasons = [r.to_dict() for r in outcome.reasons]
    pack.data_state = outcome.data_state
    return outcome


def may_submit_for_approval(session: Any, pack: Any) -> tuple[bool, list[Reason]]:
    """Whether this pack may move to READY_FOR_APPROVAL, and what is missing.

    The gate the workflow actually enforces. It is the blocking reasons and
    nothing else — not the percentage, which is a progress bar and was never
    meant to be a threshold.
    """
    outcome = assess(session, pack)
    return (not outcome.blocking), outcome.blocking


__all__ = [
    "AMBER", "BLOCKING_SEVERITY", "Check", "GREEN", "RED", "Readiness",
    "Reason", "SECTION_DONE", "SECTION_SIGNED_OFF", "WEIGHTS", "assess",
    "may_submit_for_approval", "refresh",
]
