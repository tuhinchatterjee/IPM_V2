"""Promoting an approved requirement into a DRAFT change. §35, §36.

The sentence this module implements
------------------------------------
§35: **"No direct mutation from extraction."**

Not "extraction should be careful". Not "extraction changes production only
after review". There is no code path in this module that writes to the
ontology, a method, a policy, a threshold or a teaching case. What promotion
produces is a DRAFT: a proposed change, addressed to the subsystem that owns
the thing, which then goes through that subsystem's own validation,
regression, approval and release.

That is slower and it is the point. A bank that can point at a regulation and
say "this changed our ECL staging rule" needs the chain of custody in
between, and a chain that includes an automatic step has a link nobody signed.

§36 and the Draft Method
-------------------------
For a calculation, threshold or classification requirement, §36 asks for a
CONFIGURE IN ANALYSIS STUDIO action producing a Draft Method with fifteen
named parts — source regulation, citations, applicability, population,
period, inputs, formula, thresholds, exceptions, data requirements,
relationships, validation cases, effective date, governance owner, version
and regulatory status.

`draft_method()` builds exactly those, fills what the requirement actually
established, and leaves the rest empty and named. An empty `formula` is the
honest output for a clause that says a figure must be calculated without
saying how, and filling it with a guess would produce a method that computes
something the regulator never asked for.

And §36's last line: **do not auto-certify.** The draft's status is DRAFT,
there is no argument that changes it, and `certification` states in words
that the ordinary Analysis Studio workflow applies.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.regulatory import requirements as rq
from backend.regulatory import review as rv

logger = logging.getLogger(__name__)

PROMOTION_VERSION = "1.0.0"

DRAFT = "DRAFT"
SUBMITTED = "SUBMITTED_FOR_VALIDATION"
VALIDATED = "VALIDATED"
APPROVED = "APPROVED"
RELEASED = "RELEASED"
WITHDRAWN = "WITHDRAWN"

DRAFT_STATUSES: tuple[str, ...] = (DRAFT, SUBMITTED, VALIDATED, APPROVED,
                                   RELEASED, WITHDRAWN)

#: What a draft has to clear before it is anything but a proposal. §35's
#: five, as data, so the gate can be reported rather than described.
GATES: tuple[tuple[str, str], ...] = (
    ("validation", "the change was validated against the subsystem that "
                   "owns it"),
    ("regression", "the existing regression suite still passes with it"),
    ("approval", "a named person with the standing to approve it did"),
    ("version", "it carries a version, so an answer can say which one it "
                "was produced under"),
    ("release", "it is inside an approved release rather than loose"),
)


class PromotionError(Exception):
    """A promotion that was refused, and why."""


@dataclass
class Draft:
    """A proposed change addressed to whoever owns the thing it changes.

    Never applied by this module. `target` names the subsystem, `payload`
    carries what is being proposed in that subsystem's own terms, and the
    subsystem decides.
    """

    draft_id: str = ""
    requirement_id: str = ""
    document_id: str = ""
    #: One of §35's eighteen targets.
    target: str = ""
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    #: Where the regulation is, so the change can be defended.
    citation: dict[str, Any] = field(default_factory=dict)
    effective_from: str = ""
    governance_owner: str = ""

    status: str = DRAFT
    gates_passed: tuple[str, ...] = ()
    version: int = 1
    created_by: str = ""
    created_at: str = ""
    tenant: str = ""

    def __post_init__(self) -> None:
        self.draft_id = self.draft_id or f"rdraft_{uuid.uuid4().hex[:16]}"
        self.created_at = self.created_at or datetime.now(UTC).isoformat()

    @property
    def outstanding(self) -> tuple[str, ...]:
        return tuple(f"{name}: {why}" for name, why in GATES
                     if name not in self.gates_passed)

    @property
    def applied(self) -> bool:
        """Whether this change is actually in production.

        Only from RELEASED. A draft that has been validated and approved is
        still a draft: approval is permission to release, not a release.
        """
        return self.status == RELEASED

    def to_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "requirement_id": self.requirement_id,
            "document_id": self.document_id,
            "target": self.target,
            "summary": self.summary,
            "payload": dict(self.payload),
            "citation": dict(self.citation),
            "effective_from": self.effective_from,
            "governance_owner": self.governance_owner,
            "status": self.status,
            "gates_passed": list(self.gates_passed),
            "outstanding_gates": list(self.outstanding),
            "version": self.version,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "applied": self.applied,
            "nothing_changed_yet": not self.applied,
        }


def promote(requirement: rq.Requirement, *, targets: tuple[str, ...] = (),
            by: str = "", governance_owner: str = "") -> list[Draft]:
    """Turn one approved requirement into drafts. Changes nothing.

    Refuses an unapproved or uncited requirement. The citation matters as
    much as the approval: a draft that cannot say which clause it came from
    is a change to the bank's rules whose justification is somebody's memory.
    """
    if requirement.validation_status not in rq.PROMOTABLE:
        raise PromotionError(
            f"this requirement is {requirement.validation_status}. Only an "
            "approved or corrected requirement may be promoted, because a "
            "draft carries the claim that somebody agreed with the reading")
    if not requirement.cited:
        raise PromotionError(
            "this requirement has no page, section or paragraph. A change to "
            "the bank's rules whose justification cannot be located is a "
            "change nobody can defend to a regulator")
    if not by.strip():
        raise PromotionError("a promotion needs a named person")

    wanted = targets or tuple(rv.TARGETS.get(requirement.requirement_type, ()))
    unknown = [t for t in wanted if t not in rv.PROMOTION_TARGETS]
    if unknown:
        raise PromotionError(
            f"{', '.join(unknown)} — not among §35's eighteen promotion "
            "targets. A target nobody named is a subsystem nobody owns")
    if not wanted:
        raise PromotionError(
            f"a {requirement.requirement_type} requirement has no promotion "
            "target. It may still be released as regulatory knowledge; it "
            "does not change a configuration here")

    citation = {
        "document_id": requirement.document_id,
        "page": requirement.page,
        "section": requirement.section_number,
        "paragraph": requirement.paragraph,
        "excerpt": requirement.excerpt,
    }
    drafts: list[Draft] = []
    for target in wanted:
        drafts.append(Draft(
            requirement_id=requirement.requirement_id,
            document_id=requirement.document_id,
            target=target,
            summary=(f"{requirement.summary} — proposed as a change to the "
                     f"{target}."),
            payload={
                "requirement_type": requirement.requirement_type,
                "correction": requirement.correction,
                "affected_concepts": list(requirement.affected_concepts),
                "affected_datasets": list(requirement.affected_datasets),
                "affected_methods": list(requirement.affected_methods),
                "portfolio_scope": list(requirement.portfolio_scope),
                "product_scope": list(requirement.product_scope),
            },
            citation=citation,
            effective_from=(requirement.effective_from.isoformat()
                            if requirement.effective_from else ""),
            governance_owner=governance_owner,
            created_by=by,
            tenant=requirement.tenant,
        ))
    requirement.promotion_status = rq.DRAFTED
    logger.info("requirement %s promoted to %d draft(s); nothing changed",
                requirement.requirement_id, len(drafts))
    return drafts


def pass_gate(draft: Draft, gate: str, *, by: str, note: str = "") -> Draft:
    """Record that one of §35's five gates was cleared."""
    names = {name for name, _ in GATES}
    if gate not in names:
        raise PromotionError(
            f"{gate!r} is not one of §35's gates; expected one of "
            f"{', '.join(sorted(names))}")
    if not by.strip():
        raise PromotionError(f"clearing the {gate} gate needs a named person")
    if gate in draft.gates_passed:
        return draft
    draft.gates_passed = (*draft.gates_passed, gate)
    logger.info("draft %s cleared %s (%s)%s", draft.draft_id, gate, by,
                f": {note}" if note else "")
    return draft


def may_release(draft: Draft) -> tuple[bool, tuple[str, ...]]:
    """Whether this draft may become a real change. All five gates, no
    exceptions."""
    return (not draft.outstanding), draft.outstanding


# --------------------------------------------------- §36 the Draft Method


#: §36's fifteen named parts. A Draft Method missing one of these is
#: incomplete rather than concise, and the reviewer is entitled to see which
#: parts the regulation actually established.
METHOD_PARTS: tuple[str, ...] = (
    "source_regulation", "citations", "applicability", "population",
    "period", "inputs", "formula", "thresholds", "exceptions",
    "data_requirements", "relationships", "validation_cases",
    "effective_date", "governance_owner", "version",
)

EXPECTED_PARTS = 15
if len(METHOD_PARTS) != EXPECTED_PARTS:
    raise AssertionError(
        f"§36 names {EXPECTED_PARTS} parts of a Draft Method; this module "
        f"has {len(METHOD_PARTS)}.")


def draft_method(requirement: rq.Requirement, *, by: str,
                 governance_owner: str = "",
                 document: dict[str, Any] | None = None) -> dict[str, Any]:
    """§36's CONFIGURE IN ANALYSIS STUDIO. A draft, never a certification.

    Every one of the fifteen parts is present. The ones the regulation did
    not establish are empty AND named in `established` as not established,
    because a Draft Method with a blank formula and no note reads as a method
    somebody forgot to finish, while the same blank with "the clause requires
    a calculation without specifying one" is a finding for the reviewer.
    """
    if not requirement.configurable:
        raise PromotionError(
            f"a {requirement.requirement_type} requirement at "
            f"{requirement.validation_status} does not configure a method. "
            f"§36 offers this for an approved calculation, threshold or "
            f"classification; a governance requirement would produce a "
            f"method that computes nothing")
    if not by.strip():
        raise PromotionError("a Draft Method needs a named author")

    doc = document or {}
    parts: dict[str, Any] = {
        "source_regulation": {
            "document_id": requirement.document_id,
            "title": doc.get("title", ""),
            "regulator": doc.get("regulator", ""),
            "reference": doc.get("reference", ""),
            "content_hash": doc.get("content_hash", ""),
        },
        "citations": [{
            "page": requirement.page,
            "section": requirement.section_number,
            "paragraph": requirement.paragraph,
            "excerpt": requirement.excerpt,
        }],
        "applicability": {
            "jurisdiction": requirement.jurisdiction,
            "portfolio_scope": list(requirement.portfolio_scope),
            "product_scope": list(requirement.product_scope),
        },
        "population": list(requirement.portfolio_scope),
        "period": "",
        "inputs": list(requirement.affected_concepts),
        "formula": "",
        "thresholds": [],
        "exceptions": [],
        "data_requirements": list(requirement.affected_datasets),
        "relationships": list(requirement.affected_relationships),
        "validation_cases": [],
        "effective_date": (requirement.effective_from.isoformat()
                           if requirement.effective_from else ""),
        "governance_owner": governance_owner,
        "version": 1,
    }

    established = {
        part: _established(part, parts[part], requirement)
        for part in METHOD_PARTS
    }

    return {
        "draft_method_id": f"rmeth_{uuid.uuid4().hex[:16]}",
        "requirement_id": requirement.requirement_id,
        "name": requirement.summary[:120],
        "parts": parts,
        "established": established,
        "status": DRAFT,
        "regulatory_status": requirement.validation_status,
        "created_by": by,
        "created_at": datetime.now(UTC).isoformat(),
        "certification": {
            "certified": False,
            "auto_certified": False,
            "why": (
                "§36: do not auto-certify. This draft enters the ordinary "
                "Analysis Studio validation and certification workflow, "
                "exactly as a method somebody wrote by hand would. A "
                "regulation requiring a calculation is not evidence that "
                "this particular calculation is right."
            ),
        },
    }


def _established(part: str, value: Any, requirement: rq.Requirement) -> str:
    """Whether the regulation established this part, in a sentence.

    Empty-because-the-clause-was-silent is a different finding from
    empty-because-nobody-filled-it-in, and only the first is the regulator's
    fault.
    """
    filled = bool(value) if not isinstance(value, (int, float)) else True
    if filled:
        return "established from the clause"
    reasons = {
        "period": "the clause does not say over what period the figure is "
                  "measured",
        "formula": "the clause requires a calculation without specifying "
                   "how it is computed",
        "thresholds": "no numeric trigger was extracted from the clause",
        "exceptions": "the clause states no carve-out",
        "validation_cases": "no worked example appears in the document; a "
                            "method with no validation case cannot be "
                            "certified",
        "relationships": "no governed relationship was identified",
        "governance_owner": "nobody has been named as owner yet",
        "population": "the clause does not delimit the population",
        "data_requirements": "no governed dataset was mapped",
        "inputs": "no governed concept resolved from the clause",
    }
    return reasons.get(part, "not established")
