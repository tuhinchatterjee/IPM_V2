"""
What has been done to a document, as opposed to what it says. Chapter 03.

Four states, deliberately not one:

    DRAFT      written and delivered. Nobody has checked it.
    REVIEWED   a named person has read it and said so.
    GOVERNED   it has been through the Document Intelligence workflow —
               sections signed off, metrics confirmed, findings answered.
    APPROVED   a named person has formally approved it.

They were previously the same state, and that is what made the old save gate
destructive: a document either passed every check or did not exist. So a table
count that differed took a finished report with it, and a delivered draft was
indistinguishable from an approved one.

Keeping them apart is what lets chapter 16's rule hold — "Draft created — 2
review items" rather than "nothing saved" — while still refusing to call
anything approved that a person has not approved.

Where the state lives
---------------------
On the version's `validation` JSON, under `review`. No migration: a version
that predates this reads as DRAFT with no items, which is exactly what it is.

Who may move it
---------------
Nobody automatic. REVIEWED, GOVERNED and APPROVED each record a person, and
`advance` refuses a system actor for the same reason
`intelligence/governance.py` does — a model may draft, and only a person may
say that a draft has been checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

DRAFT = "draft"
REVIEWED = "reviewed"
GOVERNED = "governed"
APPROVED = "approved"

#: In order. A document climbs it; it does not skip.
LADDER = (DRAFT, REVIEWED, GOVERNED, APPROVED)

LABELS = {
    DRAFT: "Draft",
    REVIEWED: "Reviewed",
    GOVERNED: "Governed",
    APPROVED: "Approved",
}

#: Names that are not a person. Same list as the governance boundary uses,
#: and for the same reason.
SYSTEM_ACTORS = frozenset({
    "", "system", "claude", "assistant", "ai", "bot", "playbook",
    "creditprobe", "model",
})


class NotPermitted(ValueError):
    """An act that needs a person, attempted without one."""


@dataclass
class Review:
    """The review state of one version."""

    state: str = DRAFT
    items: list[dict] = field(default_factory=list)
    by: str = ""
    at: str = ""
    history: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS.get(self.state, LABELS[DRAFT])

    @property
    def open_items(self) -> int:
        return sum(1 for i in self.items if not i.get("resolved"))

    def summary(self) -> str:
        """What to say on a file card. Chapter 16's preferred sentence."""
        if not self.items:
            return self.label
        return f"{self.label} — {self.open_items} review item" + (
            "" if self.open_items == 1 else "s")

    def as_dict(self) -> dict:
        return {"state": self.state, "label": self.label,
                "items": list(self.items), "open_items": self.open_items,
                "by": self.by, "at": self.at, "summary": self.summary(),
                "history": list(self.history)}


def of(version) -> Review:
    """The review state of a stored version. Absent means DRAFT."""
    stored = ((getattr(version, "validation", None) or {}).get("review")
              or {}) if version is not None else {}
    return Review(
        state=stored.get("state") or DRAFT,
        items=list(stored.get("items") or []),
        by=stored.get("by") or "",
        at=stored.get("at") or "",
        history=list(stored.get("history") or []),
    )


def initial(items: list[dict] | None = None) -> dict:
    """The review block a newly written version carries."""
    return Review(state=DRAFT, items=list(items or [])).as_dict()


def advance(version, *, to: str, actor: str, note: str = "") -> Review:
    """Move a version up the ladder, recording who did it.

    Refuses a system actor, refuses an unknown state, and refuses to move
    backwards — a document that was approved and then edited gets a NEW
    version at DRAFT rather than having its approval quietly withdrawn.
    """
    if to not in LADDER:
        raise NotPermitted(f"{to!r} is not a review state.")
    if to == DRAFT:
        raise NotPermitted(
            "A document is a draft when it is written. Nothing moves it back "
            "to one — an edit produces a new version, which is a draft again.")
    if (actor or "").strip().lower() in SYSTEM_ACTORS:
        raise NotPermitted(
            f"Marking a document {LABELS[to].lower()} records who did it, and "
            f"{actor or 'an unnamed caller'!r} is not a person.")

    current = of(version)
    if LADDER.index(to) < LADDER.index(current.state):
        raise NotPermitted(
            f"This version is already {current.label.lower()}; it cannot be "
            f"moved back to {LABELS[to].lower()}.")

    now = datetime.now(UTC).isoformat()
    current.history = [*current.history,
                       {"from": current.state, "to": to, "by": actor,
                        "at": now, "note": note}]
    current.state = to
    current.by = actor
    current.at = now

    validation = dict(getattr(version, "validation", None) or {})
    validation["review"] = current.as_dict()
    version.validation = validation
    return current
