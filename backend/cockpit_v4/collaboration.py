"""
What a credit officer does with an answer after reading it.

Five verbs, all of them V4's own: save an analysis, open an investigation and
put saved work in it, comment on either, share either with a colleague inside
the bank, and notify someone. Nothing here reaches back into the previous
Cockpit's investigation API or its endpoints; the storage, the routes and the
authorization are this module's.

Delivery is the part worth reading carefully
--------------------------------------------
A notification is RECORDED, and it is only ever SENT by a transport that has
been configured and named. With no transport configured -- which is the
default, and the state of every build that has not been given one -- a
notification lands in the outbox in state RECORDED with
`delivered=false` and a reason that says so. No code path in this module can
produce `delivered=true` without a transport object having actually accepted
the message and returned a receipt.

Recipients are not merely filtered, they are gated. `RecipientPolicy` holds
an explicit allow-list, and an address outside it is REFUSED -- the row is
written in state REFUSED so the attempt is auditable, and nothing is handed
to a transport. An empty allow-list therefore refuses everything, which is
the correct behaviour for a build nobody has authorized to mail anyone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

#: What a comment or a share can be about. Both kinds are V4 objects.
SAVED_ANALYSIS = "saved_analysis"
INVESTIGATION = "investigation"
SUBJECT_KINDS = (SAVED_ANALYSIS, INVESTIGATION)

#: An investigation's lifecycle. Deliberately short: this is a workspace for
#: a credit officer, not a ticketing system.
OPEN, IN_REVIEW, CLOSED = "open", "in_review", "closed"
STATUSES = (OPEN, IN_REVIEW, CLOSED)

#: Outbox states. RECORDED is the resting state of a build with no transport.
RECORDED, REFUSED, SENT, FAILED = "RECORDED", "REFUSED", "SENT", "FAILED"

_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_BODY = 4000


class CollaborationError(Exception):
    """A refusal the caller should show, with a code the UI can switch on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Transport(Protocol):
    """A real, authorized delivery channel.

    `name` is recorded on every message it accepts, so an audit can say which
    transport delivered what. `send` returns a receipt id or raises.
    """

    name: str

    def send(self, *, recipient: str, subject: str, body: str) -> str: ...


@dataclass(frozen=True)
class RecipientPolicy:
    """Who this deployment is allowed to notify.

    `allowed` is exact addresses. `allowed_domains` admits a whole domain and
    exists for an internal directory, not for the open internet. Both default
    to empty, so a build that has not been told whom it may write to writes
    to nobody.
    """

    allowed: frozenset[str] = frozenset()
    allowed_domains: frozenset[str] = frozenset()
    label: str = "no recipients authorized"

    def permits(self, recipient: str) -> bool:
        address = recipient.strip().lower()
        if not _ADDRESS.match(address):
            return False
        if address in {a.lower() for a in self.allowed}:
            return True
        domain = address.rsplit("@", 1)[-1]
        return domain in {d.lower().lstrip("@") for d in self.allowed_domains}


@dataclass
class Notifier:
    """Records every notification; delivers only what a transport accepts."""

    policy: RecipientPolicy = field(default_factory=RecipientPolicy)
    transport: Transport | None = None

    @property
    def transport_name(self) -> str:
        return getattr(self.transport, "name", "") if self.transport else ""

    def describe(self) -> dict[str, Any]:
        return {"transport": self.transport_name or None,
                "can_deliver": self.transport is not None,
                "recipient_policy": self.policy.label,
                "authorized_recipients": sorted(self.policy.allowed),
                "authorized_domains": sorted(self.policy.allowed_domains)}

    def notify(self, store, *, tenant_id: str, actor_id: str, recipient: str,
               subject: str, body: str, subject_kind: str = "",
               subject_id: str = "") -> dict[str, Any]:
        """Write the outbox row, then attempt delivery only if allowed."""
        if not recipient.strip():
            raise CollaborationError("INVALID_RECIPIENT",
                                     "A recipient is required.")
        if len(body) > MAX_BODY:
            raise CollaborationError(
                "BODY_TOO_LONG",
                f"A notification body is limited to {MAX_BODY} characters.")

        if not self.policy.permits(recipient):
            return store.put_notification(
                tenant_id=tenant_id, actor_id=actor_id, recipient=recipient,
                subject=subject, body=body, subject_kind=subject_kind,
                subject_id=subject_id, state=REFUSED, transport="",
                receipt="",
                reason=(f"{recipient} is not an authorized recipient for "
                        f"this deployment ({self.policy.label}). The message "
                        f"was recorded and NOT sent."))

        if self.transport is None:
            return store.put_notification(
                tenant_id=tenant_id, actor_id=actor_id, recipient=recipient,
                subject=subject, body=body, subject_kind=subject_kind,
                subject_id=subject_id, state=RECORDED, transport="",
                receipt="",
                reason=("No delivery transport is configured, so this "
                        "message was recorded and NOT sent."))

        try:
            receipt = self.transport.send(recipient=recipient,
                                          subject=subject, body=body)
        except Exception as exc:                              # noqa: BLE001
            return store.put_notification(
                tenant_id=tenant_id, actor_id=actor_id, recipient=recipient,
                subject=subject, body=body, subject_kind=subject_kind,
                subject_id=subject_id, state=FAILED,
                transport=self.transport_name, receipt="",
                reason=f"The transport refused the message: {exc}")
        return store.put_notification(
            tenant_id=tenant_id, actor_id=actor_id, recipient=recipient,
            subject=subject, body=body, subject_kind=subject_kind,
            subject_id=subject_id, state=SENT,
            transport=self.transport_name, receipt=str(receipt),
            reason=f"Delivered by {self.transport_name}.")


def check_subject(kind: str, subject_id: str) -> None:
    if kind not in SUBJECT_KINDS:
        raise CollaborationError(
            "UNKNOWN_SUBJECT_KIND",
            f"A comment or share is about one of {', '.join(SUBJECT_KINDS)}.")
    if not subject_id.strip():
        raise CollaborationError("MISSING_SUBJECT",
                                 "A subject id is required.")


def summarize_answer(response: dict[str, Any] | None) -> dict[str, Any]:
    """What a saved analysis keeps: the answer and where to verify it.

    The stored copy is the PUBLISHED response, not a re-rendering of it, so a
    saved analysis can never drift from what the reader saw.
    """
    body = response or {}
    return {
        "narrative": str(body.get("narrative") or ""),
        "disposition": str(body.get("disposition") or ""),
        "executed": bool(body.get("executed")),
        "numeric_claims": list(body.get("numeric_claims") or []),
        "tables": list(body.get("tables") or []),
        "charts": list(body.get("charts") or []),
        "limitations": list(body.get("limitations") or []),
        "artifact_ids": sorted({
            str(t.get("artifact_id")) for t in
            (list(body.get("tables") or []) + list(body.get("charts") or []))
            if t.get("artifact_id")}),
    }


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = ["CLOSED", "CollaborationError", "FAILED", "INVESTIGATION",
           "IN_REVIEW", "MAX_BODY", "Notifier", "OPEN", "RECORDED",
           "REFUSED", "RecipientPolicy", "SAVED_ANALYSIS", "SENT",
           "STATUSES", "SUBJECT_KINDS", "Transport", "as_json",
           "check_subject", "summarize_answer"]
