"""A small, coherent example of the internal workflow, seeded idempotently.

What this is for
-----------------
So the capability can be reviewed the moment somebody signs in, without their
first act being to invent a colleague and write themselves a message. Three
threads, not three hundred: a mailbox full of generated noise demonstrates
nothing except that a loop ran.

The rules it follows
---------------------
**Idempotent.** Every thread is keyed, and a key that already exists is left
alone. Running the bootstrap twice does not produce two copies, and neither
does restarting a container mid-seed.

**Real objects.** The investigation and analysis attachments point at rows that
actually exist in this database — found, never invented. If nothing suitable is
installed, that attachment is simply omitted and the covering note still makes
sense, because a card that opens onto a 404 is worse than no card.

**Through the real path.** The system message is produced by
`publish_data_release_event`, the same function Data Builder will call. Not
inserted as a row that merely looks like one: a fake system message would pass
every visual check and prove nothing about the mechanism.

**Nobody's identity is changed.** Seeding writes messages between the
demonstration accounts. It does not touch who is signed in, and it does not
alter a password.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)

#: The stable key each seeded thread carries in its subject-plus-sender
#: identity. Kept here rather than derived from the subject text so that
#: rewording a covering note does not silently seed a second copy.
SEED_KEYS = (
    "seed:shipping-review",
    "seed:ecl-review",
)

#: The dataset a data-release notification describes when the caller does not
#: name one. The book the product is actually about, so the example message is
#: about something a reviewer recognises — and, more importantly, the SAME
#: thing on every call.
PREFERRED_RELEASE_DATASET = "portfolio_facility"


@dataclass
class SeededWorkflow:
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"created": list(self.created), "kept": list(self.kept),
                "skipped": list(self.skipped)}


def _user(session: Any, username: str) -> Any:
    from backend.db.models import User

    return session.execute(
        select(User).where(User.username == username)
    ).scalars().first()


def _already(session: Any, subject: str, sender_id: int) -> bool:
    """Whether this exact seeded conversation is already here.

    Keyed on subject AND sender, because two different people may legitimately
    send messages with the same subject and only one of them is this seed.
    """
    from backend.models.collaboration import Message, MessageThread

    return session.execute(
        select(MessageThread.id)
        .join(Message, Message.thread_id == MessageThread.id)
        .where(MessageThread.subject == subject,
               Message.sender_user_id == sender_id)
        .limit(1)
    ).scalars().first() is not None


def _an_investigation(session: Any, sender_id: int) -> str:
    """A real investigation THIS SENDER may share, or "".

    Two conditions, both required. It must exist — a card that opens onto
    nothing teaches a reviewer that the cards are decorative. And the sender
    must be able to read it, because the seed goes through the same
    `send_message` a person does and is refused by the same rule: you cannot
    share what you were never shown. Checking here rather than catching the
    refusal later means the seed picks a workable object instead of failing on
    whichever one happened to be newest.

    Preference for a title mentioning shipping, so the covering note and the
    card agree.
    """
    from backend.models.platform import Investigation
    from backend.services import collaboration as collab

    for stmt in (
        select(Investigation).where(Investigation.title.ilike("%shipping%"))
        .order_by(Investigation.id.desc()).limit(20),
        select(Investigation).order_by(Investigation.id.desc()).limit(20),
    ):
        for row in session.execute(stmt).scalars().all():
            if collab.can_read_object(session, "investigation", str(row.id),
                                      sender_id):
                return str(row.id)
    return ""


def _an_analysis(session: Any, sender_id: int, like: str = "") -> str:
    """A real saved analysis THIS SENDER may share, or "".

    The same two conditions as `_an_investigation` above, and for the same
    reason. This function used to check only the first one: it took the newest
    analysis whose title matched, and if none matched, the newest analysis in
    the deployment. Nothing asked whether the sender could read it.

    On a fresh database every saved analysis belongs to the account that
    generated the portfolio, so the answer was always no, and `send_message`
    refused the seed with "You cannot share an analysis you do not have access
    to." The bootstrap step recorded FAILED, the readiness marker recorded
    `ok: false`, and the container health check — which reads that marker
    precisely so an empty product cannot pass for a working one — never went
    healthy. The web container waits on that health, so `docker compose up`
    came up with no user interface at all, on a failure two removes from
    anything a reader would connect to messaging.

    Preferring a title that matches `like` keeps the covering note and the
    attached card talking about the same thing, but a readable analysis on a
    different subject beats an unreadable one on the right subject: the note
    reads a little loose, rather than the seed not existing.
    """
    from backend.models.platform import SavedAnalysis
    from backend.services import collaboration as collab

    statements = []
    if like:
        statements.append(
            select(SavedAnalysis).where(SavedAnalysis.title.ilike(f"%{like}%"))
            .order_by(SavedAnalysis.id.desc()).limit(20))
    statements.append(
        select(SavedAnalysis).order_by(SavedAnalysis.id.desc()).limit(20))

    for stmt in statements:
        for row in session.execute(stmt).scalars().all():
            if collab.can_read_object(session, "analysis", str(row.id),
                                      sender_id):
                return str(row.id)
    return ""


def seed(session: Any) -> SeededWorkflow:
    """Seed the example workflow. Does not commit — the caller owns that."""
    from backend.models.collaboration import (
        PRIORITY_HIGH,
        REQ_FYI,
        REQ_REVIEW,
    )
    from backend.services import collaboration as collab

    result = SeededWorkflow()

    sarah = _user(session, "sarah.khan")
    ahmed = _user(session, "ahmed.saleh")
    alex = _user(session, "alex.rahman")
    if sarah is None or ahmed is None or alex is None:
        # The demonstration accounts have not been seeded yet. Say so rather
        # than half-seeding a conversation with a missing participant.
        result.skipped.append("demonstration accounts are not present")
        return result

    # 1. Corporate Credit Manager → Head of Credit Risk Analytics, with the
    #    governed objects the note is about.
    subject = "Shipping deterioration — please review"
    if _already(session, subject, sarah.id):
        result.kept.append(subject)
    else:
        attachments: list[dict[str, Any]] = []
        investigation = _an_investigation(session, sarah.id)
        if investigation:
            attachments.append({"type": "investigation",
                                "object_id": investigation})
        analysis = _an_analysis(session, sarah.id, like="deteriorat")
        if analysis:
            attachments.append({"type": "analysis", "object_id": analysis})
        collab.send_message(
            session, sender_id=sarah.id, to=[alex.id], subject=subject,
            body=("Please review the attached shipping work before tomorrow's "
                  "portfolio review.\n\n"
                  "Two names moved more than I expected between the quarters, "
                  "and I would rather we agreed a line before the committee "
                  "than during it."),
            attachments=attachments, request_type=REQ_REVIEW, priority=PRIORITY_HIGH,
        )
        result.created.append(subject)

    # 2. IFRS 9 Manager → the same reader, for information rather than review.
    subject = "Q2 ECL decomposition — for your information"
    if _already(session, subject, ahmed.id):
        result.kept.append(subject)
    else:
        attachments = []
        analysis = _an_analysis(session, ahmed.id, like="ecl")
        if analysis:
            attachments.append({"type": "analysis", "object_id": analysis})
        collab.send_message(
            session, sender_id=ahmed.id, to=[alex.id], subject=subject,
            body=("The Q2 decomposition is reconciled and attached. Nothing "
                  "needs a decision from you — sending it so the committee "
                  "pack does not arrive as a surprise."),
            attachments=attachments, request_type=REQ_FYI,
        )
        result.created.append(subject)

    return result


def seed_data_release(session: Any, *, dataset: str = "",
                      recipients: list[int] | None = None) -> dict[str, Any]:
    """One governed data-release notification, through the real event path.

    Reads the facts off the installed dataset rather than composing them. When
    no published dataset carries a period, nothing is sent: a notification about
    a release that cannot be described is a notification with nothing in it.
    """
    from backend.models.platform import DatasetDefinition, DataVersion
    from backend.services import collaboration as collab

    stmt = select(DatasetDefinition).where(
        DatasetDefinition.lifecycle == "published")
    if dataset:
        stmt = stmt.where(DatasetDefinition.name == dataset)
    else:
        # A STABLE choice, not merely a plausible one.
        #
        # `published_at` ties across every dataset a build script installed in
        # the same second, so ordering on it alone picks a different winner on
        # each call — and because idempotency is keyed on dataset + period, a
        # second call then seeds a SECOND notification about a different
        # dataset. Naming the headline dataset first, with the name as the
        # tiebreaker, makes repeated calls describe the same release.
        stmt = stmt.where(DatasetDefinition.name == PREFERRED_RELEASE_DATASET)
    definition = session.execute(
        stmt.order_by(DatasetDefinition.published_at.desc(),
                      DatasetDefinition.name).limit(1)
    ).scalars().first()
    if definition is None and not dataset:
        # The preferred dataset is not installed here. Fall back to the whole
        # published set, still deterministically ordered.
        definition = session.execute(
            select(DatasetDefinition)
            .where(DatasetDefinition.lifecycle == "published")
            .order_by(DatasetDefinition.name).limit(1)
        ).scalars().first()
    if definition is None:
        return {"created": False, "reason": "no published dataset"}

    version = session.execute(
        select(DataVersion)
        .where(DataVersion.dataset_id == definition.id)
        .order_by(DataVersion.version.desc()).limit(1)
    ).scalars().first()

    # Where the facts come from, in order of authority.
    #
    # A DataVersion row is the governed record of a publication and is used
    # whenever there is one. On a deployment whose lake was built by the build
    # scripts rather than through Data Builder's publish gate there is no such
    # row, and the second-best source is the governed catalogue itself — the
    # periods and the row count the analytical engine actually reads. Both are
    # measured; neither is composed. What is NOT done is fill the gap with a
    # plausible number, which is why `row_count` stays None when even the
    # catalogue cannot answer and the message simply omits it.
    periods: list[str] = list(version.periods or []) if version else []
    row_count = (int(version.row_count)
                 if version is not None and version.row_count is not None
                 else None)
    if not periods:
        try:
            from backend.data_access import get_data_source

            source = get_data_source()
            periods = [str(p) for p in source.periods(definition.name)]
            if periods:
                row_count = int(source.row_count(definition.name, periods[-1]))
        except Exception as e:  # noqa: BLE001 - the lake may not be built
            logger.info("No governed periods for %s: %s", definition.name, e)
            periods = []
    if not periods:
        return {"created": False, "reason": "the release carries no period"}

    quality = dict(version.quality_report or {}) if version else {}
    return collab.publish_data_release_event(
        session,
        dataset=definition.name,
        dataset_label=(definition.business_name
                       or definition.name.replace("_", " ").title()),
        domain=str(getattr(definition, "domain", "") or ""),
        period=periods[-1],
        previous_period=periods[-2] if len(periods) > 1 else "",
        version=str(version.version) if version else str(
            definition.published_version or ""),
        row_count=row_count,
        published_at=(version.published_at.strftime("%Y-%m-%d %H:%M UTC")
                      if version is not None
                      and getattr(version, "published_at", None)
                      else (definition.published_at.strftime("%Y-%m-%d %H:%M UTC")
                            if getattr(definition, "published_at", None) else "")),
        published_by_id=version.published_by if version else None,
        # Only True when the report actually says so. `passed` absent means the
        # publisher did not record a validation outcome, and the message says
        # the narrower thing rather than assuming the wider one.
        validated=True if quality.get("passed") is True else None,
        recipients=recipients,
    )


__all__ = ["SeededWorkflow", "seed", "seed_data_release"]
