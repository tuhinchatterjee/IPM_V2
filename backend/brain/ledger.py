"""The Learning Ledger. §13, §14.

Every installation learns constantly and almost none of it is an answer. A
steward maps a field. An officer corrects a covenant threshold. A reviewer
rejects an extracted regulatory requirement and says what it really means.
An SME renames an ontology alias. None of that arrives through the feedback
button, and all of it is learning.

`learning_observations` already records what happens on an ANSWER, and keeps
doing so. This is the superset: one immutable place where learning from any
of §13's fifteen sources lands, whether or not anyone ever acts on it.

Two rules give the module its shape.

**Nothing here activates.** An entry is a record that something was learned,
not a change to how CreditProbe behaves. Promotion runs through review,
regression and release, and this table has no path to production.

**Nothing here is deleted.** §13: "Never lose the observation locally under
retention policy." An entry found to be wrong is superseded by a new entry
that points at it, so the ledger is a history rather than a current state.
That is what makes "how much have we learned, and how much of it was any
good?" answerable a year later.

Portability is the third idea and it is separate from both. Most learning is
local by right: it names a borrower, quotes a confidential document, or is
simply nobody else's business. §14 is a gate an entry passes, not a property
it starts with, and `NON_PORTABLE` is the default rather than the exception.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

LEDGER_SCHEMA_VERSION = "1.0.0"

# ------------------------------------------------------------------ sources
#
# §13's list. Named as constants because a source string somebody typed is a
# source nobody can group by.

ASK = "ASK"
FEEDBACK = "FEEDBACK"
BETTER_APPROACH = "BETTER_APPROACH"
INVESTIGATION_CORRECTION = "INVESTIGATION_CORRECTION"
STUDIO_METHOD = "STUDIO_METHOD"
STUDIO_VALIDATION = "STUDIO_VALIDATION"
DATA_BUILDER_MAPPING = "DATA_BUILDER_MAPPING"
DATA_BUILDER_RELATIONSHIP = "DATA_BUILDER_RELATIONSHIP"
REGULATORY_REVIEW = "REGULATORY_REVIEW"
RISK_CASE = "RISK_CASE"
AGENTIC_REVIEW = "AGENTIC_REVIEW"
WORKFLOW_COMMENT = "WORKFLOW_COMMENT"
VISUALIZATION_CORRECTION = "VISUALIZATION_CORRECTION"
INTERPRETATION_CORRECTION = "INTERPRETATION_CORRECTION"
EXPERIMENT = "EXPERIMENT"
ADMIN_DECISION = "ADMIN_DECISION"
BRAIN_IMPORT = "BRAIN_IMPORT"

SOURCES: tuple[str, ...] = (
    ASK, FEEDBACK, BETTER_APPROACH, INVESTIGATION_CORRECTION,
    STUDIO_METHOD, STUDIO_VALIDATION, DATA_BUILDER_MAPPING,
    DATA_BUILDER_RELATIONSHIP, REGULATORY_REVIEW, RISK_CASE,
    AGENTIC_REVIEW, WORKFLOW_COMMENT, VISUALIZATION_CORRECTION,
    INTERPRETATION_CORRECTION, EXPERIMENT, ADMIN_DECISION, BRAIN_IMPORT,
)

# ------------------------------------------------------------ review status

CAPTURED = "CAPTURED"
TRIAGED = "TRIAGED"
REPRODUCED = "REPRODUCED"
UNDER_REVIEW = "UNDER_REVIEW"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"
DEFERRED = "DEFERRED"

REVIEW_STATUSES: tuple[str, ...] = (
    CAPTURED, TRIAGED, REPRODUCED, UNDER_REVIEW, APPROVED, REJECTED,
    SUPERSEDED, DEFERRED,
)

#: The only status from which an entry may enter a release. Written as a set
#: of one so a later edit that widens it has to be deliberate.
RELEASABLE: frozenset[str] = frozenset({APPROVED})

# --------------------------------------------------------- portability

#: §14. LOCAL_ONLY is the default: most learning names a borrower, quotes a
#: confidential document, or is nobody else's business.
NON_PORTABLE = "NON_PORTABLE"
PENDING_ADJUDICATION = "PENDING_ADJUDICATION"
PORTABLE = "PORTABLE"

PORTABILITY: tuple[str, ...] = (NON_PORTABLE, PENDING_ADJUDICATION, PORTABLE)

#: §14's conditions, as data. An entry is portable only when every one is
#: true, and the report says which failed rather than "not eligible".
ELIGIBILITY: tuple[tuple[str, str], ...] = (
    ("adjudicated", "a human or a deterministic reference settled it"),
    ("identifiers_removed", "no client identifier survives"),
    ("no_live_figures", "no live numeric answer, unless synthetic and "
                        "diagnostic"),
    ("no_client_rows", "no raw client rows"),
    ("document_rights", "no confidential excerpt beyond approved rights"),
    ("single_tenant", "nothing from another tenant"),
    ("schema_valid", "the teaching or policy schema validates"),
    ("regression_passed", "the regression suite passed"),
    ("reviewer_approved", "a reviewer approved it"),
    ("provenance_retained", "its provenance is intact"),
)

# ------------------------------------------------------------- redaction

REDACTION_NONE = "NONE"
REDACTION_PARTIAL = "PARTIAL"
REDACTION_COMPLETE = "REDACTED"


@dataclass
class Entry:
    """One thing an installation learned. Immutable once written."""

    entry_id: str = ""
    source: str = ASK
    schema_version: str = LEDGER_SCHEMA_VERSION

    # who and when
    tenant: str = ""
    user_id: str = ""
    created_at: str = ""

    # what it is about
    object_kind: str = ""
    object_id: str = ""
    related_ids: dict[str, str] = field(default_factory=dict)
    summary: str = ""
    body: dict[str, Any] = field(default_factory=dict)

    # what it was learned against
    build_sha: str = ""
    intelligence_release_id: str = ""
    teaching_release_id: str = ""
    ontology_version: str = ""

    # governance
    classification: str = "LOCAL"
    portability: str = NON_PORTABLE
    portability_blockers: tuple[str, ...] = ()
    redaction_status: str = REDACTION_NONE
    review_status: str = CAPTURED
    reviewer: str = ""
    review_note: str = ""

    # what it might become
    candidate_components: tuple[str, ...] = ()
    candidate_case_id: str = ""
    candidate_policy_id: str = ""
    candidate_method_id: str = ""
    candidate_ontology_change: str = ""

    # where it ended up
    approved_at: str = ""
    released_in: str = ""
    activated_at: str = ""

    #: Set when a later entry corrects this one. The ledger is a history.
    superseded_by: str = ""

    def __post_init__(self) -> None:
        self.entry_id = self.entry_id or f"led_{uuid.uuid4().hex[:16]}"
        self.created_at = self.created_at or datetime.now(UTC).isoformat()

    @property
    def fingerprint(self) -> str:
        """What makes this entry the same observation as another.

        Deliberately excludes time and reviewer: the same steward mapping the
        same field twice is one thing learned, not two, and counting it twice
        would inflate "learning captured" without anyone learning anything.
        """
        payload = json.dumps({
            "source": self.source,
            "object": f"{self.object_kind}:{self.object_id}",
            "summary": " ".join(self.summary.lower().split()),
            "tenant": self.tenant,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    @property
    def releasable(self) -> bool:
        return self.review_status in RELEASABLE

    @property
    def exportable(self) -> bool:
        """Whether this may go into a Learning Bundle or a Brain Pack.

        Both conditions, not either: an approved entry that is local by
        right stays local, and a portable entry nobody approved is not
        learning yet.
        """
        return self.releasable and self.portability == PORTABLE

    def to_dict(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}


class LedgerError(Exception):
    """An entry that may not be written, or a change that may not be made."""


def validate(entry: Entry) -> list[str]:
    problems: list[str] = []
    if entry.source not in SOURCES:
        problems.append(f"{entry.source!r} is not a learning source")
    if entry.review_status not in REVIEW_STATUSES:
        problems.append(f"{entry.review_status!r} is not a review status")
    if entry.portability not in PORTABILITY:
        problems.append(f"{entry.portability!r} is not a portability state")
    if not entry.summary.strip():
        problems.append("an entry with no summary cannot be reviewed later")
    if entry.portability == PORTABLE and entry.portability_blockers:
        problems.append(
            "the entry is marked portable and lists blockers, which cannot "
            "both be true")
    if entry.releasable and not entry.reviewer:
        problems.append(
            "an approved entry names no reviewer, and an approval nobody "
            "signed is not an approval")
    return problems


def eligibility(checks: dict[str, bool]) -> tuple[str, tuple[str, ...]]:
    """§14's gate. Returns the portability state and what blocked it.

    A missing check counts as failed. "Nobody looked" and "it passed" are
    different, and defaulting the difference towards portable is how a
    client identifier leaves a building.
    """
    blockers = tuple(
        f"{name}: {why}" for name, why in ELIGIBILITY
        if not checks.get(name, False))
    if blockers:
        return (PENDING_ADJUDICATION if len(blockers) < len(ELIGIBILITY)
                else NON_PORTABLE), blockers
    return PORTABLE, ()


def capture(source: str, summary: str, **fields: Any) -> Entry:
    """Record something learned. Never activates anything."""
    entry = Entry(source=source, summary=summary, **fields)
    problems = validate(entry)
    if problems:
        raise LedgerError(
            f"this learning entry may not be recorded: {'; '.join(problems)}")
    return entry


def supersede(entry: Entry, replacement: Entry, why: str) -> Entry:
    """Correct an entry by writing a new one that points at it.

    Not an update. §13 requires the observation never to be lost, and an
    UPDATE is a deletion with extra steps - it destroys what the
    installation believed at the time, which is the only thing that makes a
    later "was that learning any good?" answerable.
    """
    if not why.strip():
        raise LedgerError("a supersession with no reason cannot be reviewed")
    superseded = Entry(**{**entry.to_dict(),
                          "review_status": SUPERSEDED,
                          "superseded_by": replacement.entry_id,
                          "review_note": why})
    return superseded


def census(entries: list[Entry]) -> dict[str, Any]:
    """What the Learning Ledger holds, honestly split.

    Captured, approved and activated are three different numbers, and §63
    is explicit that more of the first is not an improvement. They are
    reported separately here so nothing downstream can add them up.
    """
    by_source: dict[str, int] = {}
    by_status: dict[str, int] = dict.fromkeys(REVIEW_STATUSES, 0)
    by_portability: dict[str, int] = dict.fromkeys(PORTABILITY, 0)
    for entry in entries:
        by_source[entry.source] = by_source.get(entry.source, 0) + 1
        by_status[entry.review_status] = by_status.get(
            entry.review_status, 0) + 1
        by_portability[entry.portability] = by_portability.get(
            entry.portability, 0) + 1

    live = [e for e in entries if e.review_status != SUPERSEDED]
    return {
        "captured": len(entries),
        "live": len(live),
        "by_source": by_source,
        "by_review_status": by_status,
        "by_portability": by_portability,
        "approved": sum(1 for e in live if e.releasable),
        "activated": sum(1 for e in live if e.activated_at),
        "exportable": sum(1 for e in live if e.exportable),
        "note": "captured, approved and activated are three different "
                "numbers. More capture is not improvement.",
    }


def portable_view(entry: Entry) -> dict[str, Any]:
    """What of an entry may leave this installation.

    A projection rather than the row. `Entry` carries the tenant, the user
    who was working when the thing was learned, and the free-text note the
    reviewer wrote, and none of those is learning — they are who we are and
    who works here. What travels is the observation and enough provenance to
    judge it: which source, against which release, approved by whom in what
    role.

    Refuses an entry that is not exportable rather than redacting it into
    something exportable. §14 is a gate an entry passes; quietly stripping
    fields until it fits would turn the gate into a formatting step.
    """
    if not entry.exportable:
        raise LedgerError(
            f"{entry.entry_id} may not be exported: review status is "
            f"{entry.review_status} and portability is {entry.portability}. "
            "Both must be settled — approved but local stays local, and "
            "portable but unapproved is not learning yet.")
    return {
        "entry_id": entry.entry_id,
        "schema_version": entry.schema_version,
        "source": entry.source,
        "object_kind": entry.object_kind,
        "summary": entry.summary,
        "body": entry.body,
        "learned_against": {
            "build_sha": entry.build_sha,
            "intelligence_release_id": entry.intelligence_release_id,
            "teaching_release_id": entry.teaching_release_id,
            "ontology_version": entry.ontology_version,
        },
        "candidate_components": list(entry.candidate_components),
        "redaction_status": entry.redaction_status,
        "approved_at": entry.approved_at,
        "released_in": entry.released_in,
    }
