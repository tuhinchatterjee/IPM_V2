"""
Regulatory SME review and Regulatory Knowledge Releases. Part G.

Why a release rather than a switch
-----------------------------------
Approving a rule one at a time and letting each approval reach production the
moment it is made produces a corpus nobody can describe. Ask "what regulatory
knowledge was this answer based on?" and the honest answer is "whatever had
been approved by the time it ran", which is not an answer.

A Regulatory Knowledge Release is a frozen set: these circulars, these
approved rules, these effective dates, this hash. Production uses ONE active
release. An answer records the release it was produced under, so the question
above has an answer that will still be true next quarter.

Rollback is activating the previous release. Nothing is deleted, so rolling
back is a normal operation rather than a recovery.

The SME review
---------------
Extraction proposes; a person disposes. `review` records an SME's verdict on
one rule with a reason, and the reason is required — "approved" with no
assessment is indistinguishable from nobody having looked, which is the state
this exists to end.

An SME may not approve their own extraction into production on their own: a
release needs an approver, and `activate` refuses when the approver is the
same person who reviewed every rule in it. That is not distrust of the SME; it
is the same two-pairs-of-eyes rule the rest of the platform applies to
material actions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.regulatory import schema as rs

logger = logging.getLogger(__name__)

RELEASE_VERSION = "1.0.0"

DRAFT = "DRAFT"
CANDIDATE = "CANDIDATE"
ACTIVE = "ACTIVE"
ROLLED_BACK = "ROLLED_BACK"
RETIRED = "RETIRED"

RELEASE_STATUSES: tuple[str, ...] = (DRAFT, CANDIDATE, ACTIVE, ROLLED_BACK,
                                     RETIRED)


class ReleaseError(Exception):
    """A release that must not be made or activated."""


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    """One SME's decision on one candidate rule."""

    rule_id: str
    decision: str
    reviewer: str
    note: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "decision": self.decision,
                "reviewer": self.reviewer, "note": self.note,
                "at": self.at.isoformat()}


#: What an SME may decide. `AMEND` exists because the common case is not
#: "right" or "wrong" — it is "the machine found the sentence and clipped it
#: in the wrong place", and forcing that into a rejection loses the rule.
APPROVE = "APPROVE"
REJECT = "REJECT"
AMEND = "AMEND"
DEFER = "DEFER"

DECISIONS: tuple[str, ...] = (APPROVE, REJECT, AMEND, DEFER)

_RESULTING_STATUS = {
    APPROVE: rs.APPROVED,
    REJECT: rs.REJECTED,
    AMEND: rs.REVIEWED,
    DEFER: rs.IN_REVIEW,
}


def review(rule: rs.Rule, *, decision: str, reviewer: str, note: str,
           text: str = "") -> Verdict:
    """Record an SME's verdict on one candidate rule.

    `text` amends the rule's own wording, which is what AMEND is for. The
    amendment is applied to the rule and the original wording is kept in the
    note, because a rule whose text changed with no record of what it used to
    say cannot be reconciled against the circular it came from.
    """
    if decision not in DECISIONS:
        raise ReleaseError(f"{decision!r} is not a review decision: "
                           + ", ".join(DECISIONS))
    if not str(reviewer).strip():
        raise ReleaseError("a review needs a named reviewer")
    if not str(note).strip():
        raise ReleaseError(
            "a review needs the reviewer's assessment: 'approved' with no "
            "reason is indistinguishable from nobody having looked")
    if decision == AMEND and not str(text).strip():
        raise ReleaseError("an amendment needs the amended text")

    if decision == AMEND:
        note = f"{note} (was: {rule.text!r})"
        rule.text = str(text).strip()
    rule.status = _RESULTING_STATUS[decision]
    rule.reviewer = str(reviewer).strip()
    rule.review_note = note
    return Verdict(rule_id=rule.rule_id, decision=decision,
                   reviewer=rule.reviewer, note=note)


def review_queue(circulars: list[rs.Circular], *,
                 limit: int = 50) -> list[dict[str, Any]]:
    """What an SME should look at next, hardest first.

    Ordered by what a wrong answer costs rather than by upload date. A
    threshold is first because a wrong number is quoted verbatim into a credit
    paper; an exception is second because a missed carve-out makes an answer
    confidently over-strict; an obligation third; a definition last, because a
    wrong definition is usually caught by the analyst who reads it.
    """
    weight = {rs.THRESHOLD: 0, rs.EXCEPTION: 1, rs.OBLIGATION: 2,
              rs.DEFINITION: 3}
    rows: list[dict[str, Any]] = []
    for circular in circulars:
        for rule in circular.rules:
            if rule.status not in (rs.CANDIDATE, rs.IN_REVIEW):
                continue
            rows.append({
                "circular_id": circular.circular_id,
                "circular": circular.citation(),
                "regulator": circular.regulator,
                "effective": circular.effective.isoformat()
                if circular.effective else "",
                "confidentiality": circular.confidentiality,
                "rule": rule.to_dict(),
                "weight": weight.get(rule.kind, 4),
                "why_you": (
                    f"{rs.RULE_MEANS.get(rule.kind, '')} Extraction proposed "
                    f"it because {rule.because}."),
            })
    rows.sort(key=lambda r: (r["weight"], -r["rule"]["confidence"],
                            r["circular_id"]))
    return rows[:limit]


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------


@dataclass
class Release:
    """A frozen set of approved regulatory knowledge."""

    release_id: str
    tenant: str = ""
    status: str = DRAFT
    #: circular_id -> the rule ids approved in this release.
    contents: dict[str, list[str]] = field(default_factory=dict)
    circular_hashes: dict[str, str] = field(default_factory=dict)
    reviewers: list[str] = field(default_factory=list)
    approver: str = ""
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    #: The release this one replaced, so rollback is a lookup.
    replaces: str = ""
    note: str = ""
    fingerprint: str = ""
    schema_version: str = rs.REGULATORY_SCHEMA_VERSION

    @property
    def rule_count(self) -> int:
        return sum(len(v) for v in self.contents.values())

    @property
    def circular_count(self) -> int:
        return len(self.contents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id, "tenant": self.tenant,
            "status": self.status,
            "circulars": self.circular_count, "rules": self.rule_count,
            "contents": {k: list(v) for k, v in self.contents.items()},
            "circular_hashes": dict(self.circular_hashes),
            "reviewers": sorted(set(self.reviewers)),
            "approver": self.approver, "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "activated_at": self.activated_at.isoformat()
            if self.activated_at else "",
            "replaces": self.replaces, "note": self.note,
            "fingerprint": self.fingerprint,
            "schema_version": self.schema_version,
            "version": RELEASE_VERSION,
        }


def fingerprint_of(contents: dict[str, list[str]],
                   hashes: dict[str, str]) -> str:
    """What this release IS, independent of who made it or when.

    Two releases with the same fingerprint contain the same knowledge, whoever
    assembled them — which is how a rollback can be recognised as a return to
    a known state rather than as a new and unproven one.
    """
    body = json.dumps(
        {"contents": {k: sorted(v) for k, v in sorted(contents.items())},
         "hashes": dict(sorted(hashes.items()))},
        sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def build(circulars: list[rs.Circular], *, release_id: str, created_by: str,
          tenant: str = "", note: str = "") -> Release:
    """Freeze every approved rule into a candidate release.

    Only APPROVED rules from circulars that are themselves APPROVED or
    SUPERSEDED. A superseded circular's approved rules stay in the release
    because as-of retrieval needs them; its date range is what stops them
    being quoted as current.
    """
    contents: dict[str, list[str]] = {}
    hashes: dict[str, str] = {}
    reviewers: list[str] = []
    for circular in circulars:
        if tenant and circular.tenant and circular.tenant != tenant:
            continue
        if circular.status not in rs.RETRIEVABLE_STATUSES:
            continue
        approved = [r.rule_id for r in circular.rules
                    if r.status == rs.APPROVED]
        if not approved:
            continue
        contents[circular.circular_id] = approved
        hashes[circular.circular_id] = circular.content_hash
        reviewers.extend(r.reviewer for r in circular.rules
                         if r.status == rs.APPROVED and r.reviewer)

    if not contents:
        raise ReleaseError(
            "there is nothing to release: no rule has been approved by an "
            "SME. Extraction proposes candidates; a release contains what a "
            "person signed for.")

    return Release(
        release_id=release_id, tenant=tenant, status=CANDIDATE,
        contents=contents, circular_hashes=hashes, reviewers=reviewers,
        created_by=created_by, note=note,
        fingerprint=fingerprint_of(contents, hashes))


def activate(release: Release, *, approver: str,
             current: Release | None = None) -> Release:
    """Make a candidate release the one production uses.

    Two refusals, both deliberate.

    A release with no approver is not activated: someone has to be
    accountable for the set, not only for its parts.

    And the approver may not be the only reviewer. Two pairs of eyes is the
    rule the rest of the platform applies to a material action, and admitting
    regulatory knowledge to production is one.
    """
    if release.status not in (CANDIDATE, ROLLED_BACK):
        raise ReleaseError(
            f"a {release.status} release cannot be activated; build a "
            "candidate first")
    if not str(approver).strip():
        raise ReleaseError("a release needs a named approver")

    reviewers = {r for r in release.reviewers if r}
    if reviewers == {approver.strip()}:
        raise ReleaseError(
            f"{approver} reviewed every rule in this release and cannot also "
            "approve it: admitting regulatory knowledge to production is a "
            "material action and needs a second pair of eyes")

    release.approver = approver.strip()
    release.status = ACTIVE
    release.activated_at = datetime.now(UTC)
    if current is not None and current.release_id != release.release_id:
        current.status = ROLLED_BACK
        release.replaces = current.release_id
    return release


def rollback(active: Release, previous: Release, *, approver: str,
             why: str) -> Release:
    """Return production to the release before this one."""
    if not str(why).strip():
        raise ReleaseError("a rollback needs a reason: an unexplained return "
                           "to an earlier release is indistinguishable from "
                           "an accident")
    active.status = ROLLED_BACK
    active.note = f"{active.note} Rolled back: {why}".strip()
    previous.status = CANDIDATE
    previous.reviewers = list(previous.reviewers) or [approver]
    return activate(previous, approver=approver)


def manifest(release: Release, circulars: list[rs.Circular]) -> dict[str, Any]:
    """What this release contains, in the words a regulator would want."""
    by_id = {c.circular_id: c for c in circulars}
    rows = []
    for circular_id, rule_ids in sorted(release.contents.items()):
        circular = by_id.get(circular_id)
        if circular is None:
            continue
        rows.append({
            "circular": circular.citation(),
            "reference": circular.reference,
            "regulator": circular.regulator,
            "effective": circular.effective.isoformat()
            if circular.effective else "",
            "expires": circular.expires.isoformat()
            if circular.expires else "",
            "status": circular.status,
            "confidentiality": circular.confidentiality,
            "content_hash": circular.content_hash,
            "rules": len(rule_ids),
            "rule_counts": circular.rule_counts(),
        })
    return {**release.to_dict(), "documents": rows}


__all__ = ["ACTIVE", "AMEND", "APPROVE", "CANDIDATE", "DECISIONS", "DEFER",
           "DRAFT", "REJECT", "RELEASE_STATUSES", "RELEASE_VERSION",
           "RETIRED", "ROLLED_BACK", "Release", "ReleaseError", "Verdict",
           "activate", "build", "fingerprint_of", "manifest", "review",
           "review_queue", "rollback"]
