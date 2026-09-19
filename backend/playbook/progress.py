"""
What was asked for, what exists, what remains. Chapter 12.

Four questions, answered separately because they have different answers:

    CONTENT       how much of the document is substantively written
    DELIVERABLES  which requested file formats exist
    REVIEW        whether a person has checked any of it
    FILES         what became of each format, including the ones that failed

Keeping them apart is the requirement. A PDF that failed to convert must not
drag eight finished sections back to zero, and a complete set of files must not
imply that anybody has read them.

Nothing here asks a model anything. Every number is counted from rows: the
sections of the stored version, the files on it, and the review block. Chapter
12 is explicit — "a model may suggest the plan, but CreditProbe calculates
completion from recorded item states" — and a percentage a model produced is
not a measurement.

The arithmetic
--------------
    100 × delivered required weights / active required weights

with every item weighing 1 unless a weight is configured and visible. When
there is nothing to count the answer is **not applicable**, never 100% and
never 0%: a Playbook with no document has not finished anything and has not
failed at anything either.

What counts as written
----------------------
A section is delivered when it says something. A section whose whole body is
an admission that the evidence is missing is NOT complete — chapter 12's
example is exact: "a placeholder saying 'the requested OOT testing evidence is
missing' does not complete a requested OOT-results section." That rule is
deterministic and it says why, so a reader can disagree with a specific
judgement rather than with a number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.playbook import document as D
from backend.playbook import repository as repo
from backend.playbook import review as review_state

#: States a work item can be in. Chapter 12's vocabulary.
NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
DELIVERED = "delivered"
NEEDS_INPUT = "needs_input"
NEEDS_REVISION = "needs_revision"
DONE = "done"

#: Counted as delivered in the numerator.
COUNTS = frozenset({DELIVERED, DONE})

#: Phrases that mark a section as an admission rather than an account. Kept
#: short and literal on purpose: a long list of clever patterns would start
#: judging prose, and the point is only to catch a section that exists to say
#: something is missing.
_GAP_PHRASES = (
    "not supplied", "was not provided", "were not provided", "not provided",
    "not available", "is missing", "are missing", "was not performed",
    "were not performed", "not performed", "no evidence", "to be confirmed",
    "to be supplied", "outside scope", "out of scope", "not yet available",
    "awaiting", "tbd", "placeholder",
)

#: Below this a section is a stub: too short to be an account of anything.
#: Deliberately small. An earlier version used 160 and marked a perfectly
#: good 108-character conclusion as unfinished, which is grading brevity
#: rather than detecting absence — a short section can be a complete one.
_STUB = 60

#: A gap phrase only decides the matter while it is the SUBSTANCE of the
#: section. Above this the section is an account that happens to mention
#: scope, not a note saying evidence is missing.
_GAP_DOMINATES = 240


@dataclass
class Item:
    """One thing the user asked for."""

    key: str
    label: str
    kind: str                      # "content" | "deliverable"
    state: str = NOT_STARTED
    weight: int = 1
    detail: str = ""

    @property
    def delivered(self) -> bool:
        return self.state in COUNTS

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "state": self.state, "weight": self.weight,
                "delivered": self.delivered, "detail": self.detail}


@dataclass
class Completion:
    """A fraction that can show its working."""

    delivered: int = 0
    total: int = 0

    @property
    def applicable(self) -> bool:
        return self.total > 0

    @property
    def percent(self) -> int | None:
        """None when there is nothing to count. Never 0, never 100."""
        if not self.applicable:
            return None
        return round(100 * self.delivered / self.total)

    def as_dict(self) -> dict:
        return {"delivered": self.delivered, "total": self.total,
                "percent": self.percent,
                "applicable": self.applicable,
                # The numerator and denominator, so "why 80%?" is answerable
                # from the payload rather than by asking anybody.
                "label": (f"{self.delivered} / {self.total}"
                          if self.applicable else "Not applicable")}


@dataclass
class Progress:
    """The whole answer for one workspace."""

    available: bool = False
    reason: str = ""
    items: list[Item] = field(default_factory=list)
    content: Completion = field(default_factory=Completion)
    deliverables: Completion = field(default_factory=Completion)
    overall: Completion = field(default_factory=Completion)
    review: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)
    version: int = 0

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "version": self.version,
            "items": [i.as_dict() for i in self.items],
            "content": self.content.as_dict(),
            "deliverables": self.deliverables.as_dict(),
            "overall": self.overall.as_dict(),
            "review": dict(self.review),
            "files": dict(self.files),
        }


def _body(section) -> str:
    return " ".join(b.text for b in section.blocks if getattr(b, "text", ""))


def _section_state(section) -> tuple[str, str]:
    """Whether this section says something, and why not when it does not."""
    text = _body(section).strip()
    if not text:
        return NOT_STARTED, "nothing written yet"
    lowered = text.lower()
    hit = next((p for p in _GAP_PHRASES if p in lowered), "")
    if hit and len(text) < _GAP_DOMINATES:
        return NEEDS_INPUT, f"states that evidence is missing ({hit!r})"
    if len(text) < _STUB:
        return IN_PROGRESS, f"only {len(text)} characters so far"
    return DELIVERED, ""


def of(session, workspace_id: int) -> Progress:
    """Count what this workspace has produced.

    Reads rows and nothing else. Never raises for a workspace with no
    document — that is a real state with a real answer, and chapter 11 wants
    it said rather than filled with noughts.
    """
    from backend.playbook.intelligence import service as intel

    artifact = intel._current_artifact(session, workspace_id)
    if artifact is None or artifact.current_version_id is None:
        return Progress(
            available=False,
            reason="No document deliverable has been requested yet.")

    versions = repo.versions(session, artifact.id)
    current = next((v for v in versions
                    if v.id == artifact.current_version_id), None)
    if current is None:
        return Progress(available=False,
                        reason="This document has no current version.")

    doc = D.Document.from_dict(current.content or {})
    items: list[Item] = []

    # Content: one item per section of the version in front of the reader.
    for ordinal, section in enumerate(doc.sections, start=1):
        state, why = _section_state(section)
        items.append(Item(key=f"section:{ordinal}",
                          label=section.heading or f"Section {ordinal}",
                          kind="content", state=state, detail=why))

    # Deliverables: one per format that exists on this version. A format that
    # was attempted and failed leaves no file row, so it is counted through
    # the stored validation record instead of vanishing from the plan.
    files = {f.format: f for f in repo.files(session, current.id)}
    attempted = sorted(
        set(files) | {f for f in (current.validation or {})
                      if f in {"docx", "pdf", "pptx", "xlsx"}})
    for fmt in attempted:
        present = fmt in files
        items.append(Item(
            key=f"file:{fmt}", label=fmt.upper(), kind="deliverable",
            state=DELIVERED if present else NEEDS_REVISION,
            detail="" if present else "could not be produced"))

    content = Completion(
        delivered=sum(i.weight for i in items
                      if i.kind == "content" and i.delivered),
        total=sum(i.weight for i in items if i.kind == "content"))
    deliverables = Completion(
        delivered=sum(i.weight for i in items
                      if i.kind == "deliverable" and i.delivered),
        total=sum(i.weight for i in items if i.kind == "deliverable"))
    overall = Completion(
        delivered=content.delivered + deliverables.delivered,
        total=content.total + deliverables.total)

    state = review_state.of(current)
    return Progress(
        available=True,
        version=current.version,
        items=items,
        content=content,
        deliverables=deliverables,
        overall=overall,
        review={"state": state.state, "label": state.label,
                "summary": state.summary(), "open_items": state.open_items,
                "by": state.by},
        files={fmt: {"present": fmt in files,
                     "size_bytes": getattr(files.get(fmt), "size_bytes", 0),
                     "renderer": getattr(files.get(fmt), "renderer", ""),
                     "file_id": getattr(files.get(fmt), "id", None)}
               for fmt in attempted},
    )


#: Kept for the one thing a regular expression is good for here: turning a
#: heading like "3. Calibration" into something a person reads in a list.
_NUMBERED = re.compile(r"^\s*\d+[.)]\s*")


def short_label(heading: str) -> str:
    return _NUMBERED.sub("", heading or "").strip() or "Untitled section"
