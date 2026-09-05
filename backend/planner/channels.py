"""Where a planner notification can actually go, and where it cannot.

CreditProbe delivers notifications in the application. It has no outbound
email provider — no SMTP configuration, no transactional mail service, no
governed sending identity — and this module does not invent one. Creating SMTP
credentials so that one feature could send mail would put a password in an
environment file, a sending address on the bank's domain, and an unreviewed
outbound channel into a product whose whole claim is that everything is
traceable. That is a platform decision with its own approvals, and it is not
the Project Planner's to make.

What the planner does instead is the honest version of the same thing:

  * every reminder is delivered in the application, where it is already read;
  * every reminder is ALSO composed as a complete, channel-ready message —
    subject, recipient, the project, the task, the deadline, the progress, the
    factual reason and a direct link — so that the day a provider exists, the
    only work is a transport;
  * nothing anywhere says an email was sent.

`describe()` is what the API and the screen report. It says `configured:
False` and names what is missing, so that "did they get an email?" has an
answer rather than a shrug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CHANNELS_VERSION = "1.0.0"

IN_APP = "in_app"
EMAIL = "email"

#: The product name that appears on anything leaving the building. Not a
#: provider, not a model — the bank's own product.
SENDER_LABEL = "CreditProbe Project Agent"


@dataclass(frozen=True)
class Channel:
    """One way of reaching somebody, and whether it exists here."""

    name: str
    label: str
    available: bool
    #: Why not, in a sentence somebody can act on. Empty when available.
    unavailable_because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label,
                "available": self.available,
                "unavailable_because": self.unavailable_because}


IN_APP_CHANNEL = Channel(
    IN_APP, "In the application", True)

EMAIL_CHANNEL = Channel(
    EMAIL, "Email", False,
    "CreditProbe has no outbound mail provider configured. The Project "
    "Planner composes every reminder in a form an email transport could send "
    "unchanged, but nothing sends it, and nothing in the product claims "
    "otherwise. Adding one is a platform change: a governed sending identity, "
    "a provider, and the approval that goes with putting the bank's name on "
    "outbound mail.")


def channels() -> list[Channel]:
    return [IN_APP_CHANNEL, EMAIL_CHANNEL]


def describe() -> dict[str, Any]:
    """What an operator sees when they ask how reminders are delivered."""
    return {
        "version": CHANNELS_VERSION,
        "sender": SENDER_LABEL,
        "channels": [c.to_dict() for c in channels()],
        "delivered": [IN_APP],
        "composed_but_not_sent": [EMAIL],
    }


@dataclass
class Outbound:
    """One reminder, composed for any channel that might one day carry it.

    Deliberately complete rather than a summary: a transport should not have
    to go back to the database to write a subject line, and a payload that
    made it do so would be a payload that drifted from what the screen said.
    """

    channel: str
    user_id: int
    subject: str
    body: str
    action_label: str
    link: str
    project_code: str
    project_name: str
    reference: str = ""
    reference_title: str = ""
    due_date: str = ""
    percent_complete: int | None = None
    reason: str = ""
    trigger: str = ""
    #: False, always, for anything but the in-application channel. The field
    #: exists so that no caller has to infer it.
    sent: bool = False
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel, "user_id": self.user_id,
            "subject": self.subject, "body": self.body,
            "action_label": self.action_label, "link": self.link,
            "project_code": self.project_code,
            "project_name": self.project_name,
            "reference": self.reference,
            "reference_title": self.reference_title,
            "due_date": self.due_date,
            "percent_complete": self.percent_complete,
            "reason": self.reason, "trigger": self.trigger,
            "sent": self.sent, "facts": dict(self.facts),
        }


def compose(message: Any, *, project_name: str = "", base_url: str = "",
            channel: str = EMAIL, due_date: str = "",
            percent_complete: int | None = None) -> Outbound:
    """Turn a monitor message into a channel-ready payload.

    Takes the `Message` the sweep already built rather than re-deriving
    anything: the subject a person would read in their inbox and the line they
    read in the application have to be the same claim, and the only way to
    guarantee that is for them to come from the same object.
    """
    reference = getattr(message, "entity_code", "") or ""
    title = getattr(message, "title", "")
    link = f"{base_url.rstrip('/')}/delivery/{message.project_id}"
    if getattr(message, "entity_type", "") == "TASK":
        link = f"{link}?task={message.entity_id}"

    subject = f"{SENDER_LABEL} — {title}"
    if reference:
        subject = f"{subject}: {reference}"

    lines = [message.body]
    if getattr(message, "action", ""):
        lines.append(message.action)
    lines.append(f"Open it in CreditProbe: {link}")

    return Outbound(
        channel=channel,
        user_id=int(message.user_id),
        subject=subject,
        body="\n\n".join(part for part in lines if part),
        action_label=getattr(message, "label", "Open"),
        link=link,
        project_code=message.project_code,
        project_name=project_name,
        reference=reference,
        reference_title=title,
        due_date=due_date,
        percent_complete=percent_complete,
        reason=getattr(message, "reason", ""),
        trigger=message.trigger,
        sent=channel == IN_APP,
        facts={"entity_type": getattr(message, "entity_type", ""),
               "entity_id": getattr(message, "entity_id", None),
               "asked": bool(getattr(message, "asked", False))},
    )


__all__ = [
    "CHANNELS_VERSION", "IN_APP", "EMAIL", "SENDER_LABEL",
    "Channel", "channels", "describe", "Outbound", "compose",
]
