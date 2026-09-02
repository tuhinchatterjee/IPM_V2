"""The internal workflow spine: users a person can be described by, message
threads, attachments held as bytes, explicit object shares, and an audit log.

Why the users columns are here rather than in a directory service
------------------------------------------------------------------
`job_title` and `department` are not `role`. Role is what somebody may do and
lives in the permission registry; job title is what they do, and it is the field
a sender actually reads when choosing who to send a shipping question to. A
directory in which four people are all "ANALYST" cannot answer that.

`deactivated_at`/`deactivated_by` exist because deactivation is an act somebody
performs, not a state that drifts. Reactivating a suspended account must not
erase the record that it was suspended, and `is_active` alone cannot carry that.

Why attachment bytes are a column
----------------------------------
`message_artifacts.content` is BYTEA. A path on a container's filesystem is a
working attachment until the first restart and a broken promise afterwards, and
this schema already stores governed Parquet the same way. The row also carries a
SHA-256, so "the workbook attached to the March message" is checkable rather
than merely named.

Why the sender check constraint
--------------------------------
A CreditProbe system message has no user behind it. Enforcing that in the
database — SYSTEM implies no sender_user_id, USER implies one — means no request
body, and no future caller of the messaging service, can dress a person up as
the product. The unique `event_key` is the same kind of guarantee for
idempotency: a publication replayed after a restart cannot notify the same
people twice, because the second insert fails rather than relying on a service
remembering.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------- users
    op.add_column("users", sa.Column("job_title", sa.String(120),
                                     nullable=False, server_default=""))
    op.add_column("users", sa.Column("department", sa.String(120),
                                     nullable=False, server_default=""))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True),
                                     nullable=True))
    op.add_column("users", sa.Column("deactivated_at",
                                     sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("deactivated_by", sa.Integer(),
                                     nullable=True))
    op.create_foreign_key("fk_users_deactivated_by", "users", "users",
                          ["deactivated_by"], ["id"])

    # ---------------------------------------------------------- threads
    op.create_table(
        "message_threads",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("origin", sa.String(8), nullable=False, server_default="USER"),
        sa.Column("message_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_message_threads_recent", "message_threads",
                    ["last_message_at"])

    # --------------------------------------------------------- messages
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("thread_id", sa.BigInteger(),
                  sa.ForeignKey("message_threads.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("parent_id", sa.BigInteger(),
                  sa.ForeignKey("messages.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("sender_type", sa.String(8), nullable=False,
                  server_default="USER"),
        sa.Column("sender_user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False,
                  server_default="draft"),
        sa.Column("request_type", sa.String(16), nullable=False,
                  server_default="fyi"),
        sa.Column("request_status", sa.String(16), nullable=True),
        sa.Column("priority", sa.String(12), nullable=False,
                  server_default="normal"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_key", sa.String(250), nullable=True),
        sa.Column("actions", postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("context", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(sender_type = 'SYSTEM' AND sender_user_id IS NULL) OR "
            "(sender_type = 'USER' AND sender_user_id IS NOT NULL)",
            name="ck_messages_sender",
        ),
        sa.UniqueConstraint("event_key", name="uq_messages_event_key"),
    )
    op.create_index("ix_messages_thread", "messages", ["thread_id", "created_at"])
    op.create_index("ix_messages_drafts", "messages",
                    ["sender_user_id", "status"])

    op.create_table(
        "message_recipients",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("message_id", sa.BigInteger(),
                  sa.ForeignKey("messages.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("kind", sa.String(4), nullable=False, server_default="to"),
        sa.UniqueConstraint("message_id", "user_id",
                            name="uq_message_recipient"),
    )
    op.create_index("ix_message_recipients_user", "message_recipients",
                    ["user_id"])

    op.create_table(
        "thread_participants",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("thread_id", sa.BigInteger(),
                  sa.ForeignKey("message_threads.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("addressed", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("thread_id", "user_id",
                            name="uq_thread_participant"),
    )
    op.create_index("ix_thread_participants_inbox", "thread_participants",
                    ["user_id", "archived_at", "read_at"])

    # ------------------------------------------------------ attachments
    op.create_table(
        "message_artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("source_object_type", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("source_object_id", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_message_artifacts_hash", "message_artifacts", ["sha256"])

    op.create_table(
        "message_attachments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("message_id", sa.BigInteger(),
                  sa.ForeignKey("messages.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("attachment_type", sa.String(24), nullable=False),
        sa.Column("object_id", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("object_version", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("artifact_id", sa.BigInteger(),
                  sa.ForeignKey("message_artifacts.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("label", sa.String(300), nullable=False, server_default=""),
        sa.Column("meta", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_message_attachments_message", "message_attachments",
                    ["message_id"])
    op.create_index("ix_message_attachments_object", "message_attachments",
                    ["attachment_type", "object_id"])

    # ---------------------------------------------------------- sharing
    op.create_table(
        "object_shares",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("object_type", sa.String(24), nullable=False),
        sa.Column("object_id", sa.String(120), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("message_id", sa.BigInteger(),
                  sa.ForeignKey("messages.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("object_version", sa.String(64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("object_type", "object_id", "user_id",
                            name="uq_object_share"),
    )
    op.create_index("ix_object_shares_user", "object_shares",
                    ["user_id", "object_type"])

    # ------------------------------------------------ workflow and audit
    op.create_table(
        "request_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("message_id", sa.BigInteger(),
                  sa.ForeignKey("messages.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_request_status_events_message", "request_status_events",
                    ["message_id", "created_at"])

    op.create_table(
        "collaboration_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("actor_type", sa.String(8), nullable=False,
                  server_default="USER"),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("object_type", sa.String(48), nullable=False,
                  server_default=""),
        sa.Column("object_id", sa.String(120), nullable=False,
                  server_default=""),
        sa.Column("subject_user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=False,
                  server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_collaboration_audit_action", "collaboration_audit",
                    ["action", "created_at"])
    op.create_index("ix_collaboration_audit_object", "collaboration_audit",
                    ["object_type", "object_id"])
    op.create_index("ix_collaboration_audit_actor", "collaboration_audit",
                    ["actor_id", "created_at"])


def downgrade() -> None:
    op.drop_table("collaboration_audit")
    op.drop_table("request_status_events")
    op.drop_table("object_shares")
    op.drop_table("message_attachments")
    op.drop_table("message_artifacts")
    op.drop_table("thread_participants")
    op.drop_table("message_recipients")
    op.drop_table("messages")
    op.drop_table("message_threads")
    op.drop_constraint("fk_users_deactivated_by", "users", type_="foreignkey")
    for column in ("deactivated_by", "deactivated_at", "updated_at",
                   "department", "job_title"):
        op.drop_column("users", column)
