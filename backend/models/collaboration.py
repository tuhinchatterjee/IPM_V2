"""
The internal workflow spine: who works here, what they send each other, and
what CreditProbe itself tells them.

Why this is not the workflow tables next door
----------------------------------------------
`workflow_items` (models/platform.py) is ANCHORED: every row is a review of one
governed object, and object_type/object_id are the reason the row exists. That
is the right shape for "certify this analysis" and the wrong shape for "here are
three things, please look before tomorrow's committee". A message has a subject,
a body, zero or many attachments of DIFFERENT kinds, and it is addressed to a
PERSON rather than raised against an object.

So this is a second, smaller model beside it rather than a widening of it. The
two are related — a message may carry a review request — but a message with no
attachment is still a message, and a certification with no covering note is
still a certification.

What it deliberately reuses
----------------------------
`users` is THE user table. There is no second identity here: a participant is a
`users.id`, a sender is a `users.id`, and the role that decides what somebody
may do is the one in `backend/api/permissions.py`. Nothing in this module can
grant a permission the role registry does not already recognise.

`notifications` stays the unread badge. A message produces a Notification row
through the same service every other part of the product uses, so the bell
count does not fork into two competing truths.

The three properties this schema is built to hold
--------------------------------------------------
1. **A system message has no user behind it.** `sender_type` is SYSTEM and
   `sender_user_id` is NULL, enforced by a check constraint rather than by
   convention, so no request body can forge CreditProbe as a sender by naming a
   user id — and no administrator can log in as "CreditProbe AI", because there
   is no such account to log in to.

2. **An attached file is bytes this database holds.** Not a path. A path under
   /tmp is a working attachment until the container restarts and a 404 for the
   rest of the object's life, and "the message from March had the workbook
   attached" is exactly the sentence a bank cannot afford to be wrong about.

3. **A share is a grant, not a link.** Sending an investigation records who may
   now open it. Revoking it leaves the audit record standing: what was shared,
   by whom, to whom, and when, is a separate fact from who may read it today.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import models as _core_models  # noqa: F401  (registers `users`)
from backend.db.base import Base

# --------------------------------------------------------------------------
# Vocabularies. Module constants rather than database enums, for the reason
# given in models/platform.py: a new state should not need a migration.
# --------------------------------------------------------------------------

#: Who sent it. The only two kinds there will ever be: a person, or the product.
SENDER_USER = "USER"
SENDER_SYSTEM = "SYSTEM"

#: A message is a draft until it is sent. A draft is private to its author and
#: has no recipients yet — which is why `message_recipients` is written at send
#: time and not at compose time.
MSG_DRAFT = "draft"
MSG_SENT = "sent"

#: What the sender is asking for. Three, on purpose: a risk team needs to
#: distinguish "read this" from "I need your opinion" from "you have to do
#: something", and does not need a nine-state approval ladder to do it. The
#: certification ladder already exists in `workflow_items` for the cases that
#: genuinely need it.
REQ_FYI = "fyi"
REQ_REVIEW = "review"
REQ_ACTION = "action"
REQUEST_TYPES = (REQ_FYI, REQ_REVIEW, REQ_ACTION)

#: Where a request has got to. Only set on a message that asks for something;
#: a for-information message has no status because there is nothing to close.
REQ_OPEN = "open"
REQ_IN_REVIEW = "in_review"
REQ_RESPONDED = "responded"
REQ_CLOSED = "closed"
REQUEST_STATES = (REQ_OPEN, REQ_IN_REVIEW, REQ_RESPONDED, REQ_CLOSED)
REQUEST_OPEN_STATES = (REQ_OPEN, REQ_IN_REVIEW)

#: What can be attached. `report` and `file` both resolve to stored bytes; they
#: are distinguished so the reader is told which one they are looking at.
ATT_INVESTIGATION = "investigation"
ATT_ANALYSIS = "analysis"
ATT_REPORT = "report"
ATT_FILE = "file"
ATTACHMENT_TYPES = (ATT_INVESTIGATION, ATT_ANALYSIS, ATT_REPORT, ATT_FILE)

#: The attachment kinds that are governed objects rather than stored bytes, and
#: therefore go through the share-grant path.
SHAREABLE_OBJECTS = (ATT_INVESTIGATION, ATT_ANALYSIS)

PRIORITY_NORMAL = "normal"
PRIORITY_HIGH = "high"
PRIORITIES = (PRIORITY_NORMAL, PRIORITY_HIGH)


# ==========================================================================
# Threads and messages
# ==========================================================================


class MessageThread(Base):
    """One conversation. A subject, and everyone who can see it.

    The thread owns participation; the messages own content. That split is what
    makes "archive this conversation" a per-person act — archiving is a row on
    the participant, so one person filing a thread away does not remove it from
    anybody else's inbox.
    """

    __tablename__ = "message_threads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Who started it. NULL when CreditProbe did.
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    #: USER | SYSTEM — matches the first message's sender_type.
    origin: Mapped[str] = mapped_column(
        String(8), nullable=False, default=SENDER_USER, server_default=SENDER_USER
    )
    #: Denormalised so a 50-row inbox does not count messages 50 times.
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="thread", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    participants: Mapped[list[ThreadParticipant]] = relationship(
        back_populates="thread", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_message_threads_recent", "last_message_at"),
    )


class Message(Base):
    """One thing somebody said, with whatever they attached to it.

    Immutable once sent. `sent_at` is the line: before it the row is a private
    draft its author may rewrite, after it the body is evidence. A correction is
    a reply, because a message somebody has already read and acted on must not
    change under them.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("message_threads.id", ondelete="CASCADE"), nullable=False
    )
    #: The message this one answers, where the reader picked one. A flat reply
    #: to the thread leaves this NULL — most replies are to the conversation.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    sender_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default=SENDER_USER, server_default=SENDER_USER
    )
    sender_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: draft | sent
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=MSG_DRAFT, server_default=MSG_DRAFT
    )

    #: fyi | review | action
    request_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=REQ_FYI, server_default=REQ_FYI
    )
    #: open | in_review | responded | closed. NULL for a for-information message.
    request_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    priority: Mapped[str] = mapped_column(
        String(12), nullable=False, default=PRIORITY_NORMAL,
        server_default=PRIORITY_NORMAL,
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Stable identity of the event that produced a system message, e.g.
    #: "DATA_RELEASE_PUBLISHED:portfolio_facility:v7". UNIQUE, so a retried or
    #: replayed publication cannot notify the same people twice. NULL for
    #: everything a person sends.
    event_key: Mapped[str | None] = mapped_column(String(250), nullable=True)
    #: What a system message offers the reader: [{"action": "open_dataset",
    #: "label": "Open Dataset", "href": "/data-builder/...", ...}]. Only
    #: actions the product can actually carry out are ever written here.
    actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: Governed facts behind a system message — dataset, period, row counts —
    #: exactly as the publishing service reported them. Never composed.
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    thread: Mapped[MessageThread] = relationship(back_populates="messages")
    recipients: Mapped[list[MessageRecipient]] = relationship(
        back_populates="message", cascade="all, delete-orphan",
    )
    attachments: Mapped[list[MessageAttachment]] = relationship(
        back_populates="message", cascade="all, delete-orphan",
        order_by="MessageAttachment.id",
    )

    __table_args__ = (
        # The forgery guard. A SYSTEM message has no user behind it and a USER
        # message must name one: the database refuses the combination that
        # would let a request body dress a person up as CreditProbe.
        CheckConstraint(
            "(sender_type = 'SYSTEM' AND sender_user_id IS NULL) OR "
            "(sender_type = 'USER' AND sender_user_id IS NOT NULL)",
            name="ck_messages_sender",
        ),
        # One system event, one message. Idempotency lives in the schema
        # rather than in a service that might be called twice.
        UniqueConstraint("event_key", name="uq_messages_event_key"),
        Index("ix_messages_thread", "thread_id", "created_at"),
        Index("ix_messages_drafts", "sender_user_id", "status"),
    )


class MessageRecipient(Base):
    """Who a message was addressed to, and how.

    Written at SEND time. A draft has no recipients: the addressee list on an
    unsent message is part of the draft's private payload, not a fact about
    anybody's inbox.
    """

    __tablename__ = "message_recipients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: to | cc
    kind: Mapped[str] = mapped_column(
        String(4), nullable=False, default="to", server_default="to"
    )

    message: Mapped[Message] = relationship(back_populates="recipients")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_recipient"),
        Index("ix_message_recipients_user", "user_id"),
    )


class ThreadParticipant(Base):
    """One person's relationship with one conversation.

    This row IS the authorization to read the thread. There is no other test:
    if you are not a participant, the thread does not exist as far as the API is
    concerned, and guessing its id returns the same 404 a genuinely absent
    thread returns.

    `read_at` and `archived_at` are per-person for the same reason — an inbox
    is a personal view of shared content, and one reader marking a thread read
    must not mark it read for everyone.
    """

    __tablename__ = "thread_participants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("message_threads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    #: Whether this person has ever been an addressee, or only a sender. Both
    #: are participants; only an addressee's unread state counts as an inbox
    #: item, which is what keeps your own sent mail out of your own inbox.
    addressed: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default=text("true")
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    thread: Mapped[MessageThread] = relationship(back_populates="participants")

    __table_args__ = (
        UniqueConstraint("thread_id", "user_id", name="uq_thread_participant"),
        Index("ix_thread_participants_inbox", "user_id", "archived_at", "read_at"),
    )


# ==========================================================================
# Attachments
# ==========================================================================


class MessageArtifact(Base):
    """A file, held as bytes.

    In the database on purpose. The alternative — a path on a container's disk —
    is a working attachment until the first restart, and this product already
    stores governed Parquet the same way (`dataset_sheets.parquet`), so this is
    the established pattern rather than a new one.

    `sha256` is what makes "the file that was sent in March" a checkable claim
    rather than a filename.
    """

    __tablename__ = "message_artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    #: Where the bytes came from, when they came from inside the product:
    #: ("analysis_run", "412") for a generated workbook. Empty for an upload.
    source_object_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default="", server_default=""
    )
    source_object_id: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )

    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_message_artifacts_hash", "sha256"),)


class MessageAttachment(Base):
    """One thing hanging off one message.

    A governed object records its identity AND what it looked like when it was
    sent. The snapshot in `meta` is not a cache: it is the answer to "what did
    the recipient think they were being sent", which stays true even after the
    investigation moves on to a later period.
    """

    __tablename__ = "message_attachments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    #: investigation | analysis | report | file
    attachment_type: Mapped[str] = mapped_column(String(24), nullable=False)
    #: The governed object's id, as text so an int id and a slug both fit.
    object_id: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    #: The version at share time, where the object is versioned.
    object_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("message_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    #: What to call it on the card. Captured at share time so a renamed
    #: investigation does not rewrite the history of what was sent.
    label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    #: Owner, period, scope, status — whatever the card shows, as it was.
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped[Message] = relationship(back_populates="attachments")
    artifact: Mapped[MessageArtifact | None] = relationship()

    __table_args__ = (
        Index("ix_message_attachments_message", "message_id"),
        Index("ix_message_attachments_object", "attachment_type", "object_id"),
    )


# ==========================================================================
# Sharing
# ==========================================================================


class ObjectShare(Base):
    """An explicit grant: this person may open this governed object.

    Sending an investigation does not make it public and does not copy it. It
    creates one of these rows, and the object's own read check consults it.

    `revoked_at` rather than a delete. "Who has access today" and "what was
    shared with whom in March" are different questions, and a bank needs both
    to be answerable from the same table.
    """

    __tablename__ = "object_shares"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: investigation | analysis
    object_type: Mapped[str] = mapped_column(String(24), nullable=False)
    object_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Who may now read it.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    #: The message that carried it, when a message did.
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    object_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("object_type", "object_id", "user_id",
                         name="uq_object_share"),
        Index("ix_object_shares_user", "user_id", "object_type"),
    )


# ==========================================================================
# Workflow transitions and audit
# ==========================================================================


class RequestStatusEvent(Base):
    """One transition of a review/action request. Append-only.

    Every field a reviewer would later be asked about: who moved it, when, from
    what, to what, and what they said. A status column alone answers "where is
    it" and nothing else.
    """

    __tablename__ = "request_status_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_request_status_events_message", "message_id", "created_at"),
    )


class CollaborationAudit(Base):
    """Who did what, to what, when.

    Separate from the domain tables because an audit record must survive the
    thing it describes. A thread deleted by an administrator takes its messages
    with it; it does not take with it the record that a message was sent.

    Deliberately NOT shown in the conversational UI. It is evidence for the
    governance surfaces, and an inbox that narrates its own audit log to the
    reader is an inbox nobody can read.
    """

    __tablename__ = "collaboration_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: USER_CREATED, MESSAGE_SENT, OBJECT_SHARED, FILE_DOWNLOADED, …
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    #: USER | SYSTEM — who acted.
    actor_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default=SENDER_USER, server_default=SENDER_USER
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    object_type: Mapped[str] = mapped_column(
        String(48), nullable=False, default="", server_default=""
    )
    object_id: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    #: The person acted upon, where there is one: the recipient of a message,
    #: the user an administrator deactivated.
    subject_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_collaboration_audit_action", "action", "created_at"),
        Index("ix_collaboration_audit_object", "object_type", "object_id"),
        Index("ix_collaboration_audit_actor", "actor_id", "created_at"),
    )
