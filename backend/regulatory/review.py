"""One-by-one regulatory review, and what a correction becomes. §32, §33.

The screen this module is the backend for
------------------------------------------
§32 shows a reviewer four blocks for every proposed requirement: SOURCE (the
page, the excerpt, the document), CREDITPROBE UNDERSTANDING (what we think it
means and what we would reconfigure), CONFLICTS (what already here disagrees)
and ACTIONS. `panel()` builds exactly those four, in that order, because the
order is the argument: a reviewer who sees the machine's interpretation before
the regulator's words is reviewing the interpretation.

Seven actions, and why REJECT is two words longer
--------------------------------------------------
§32's reject is "REJECT — NOT RELEVANT", not "REJECT". The distinction
matters: rejecting a requirement because the extraction garbled it is a
different fact from deciding the clause does not apply to this bank, and only
the second one is a statement about the regulation. Both are available, and
they are separate actions.

A correction is not an edit
----------------------------
§33: when a reviewer says "no, that is not the case, understand it this
way", the original machine interpretation is kept beside their words. The
record is the pair, not the winner. A year later somebody will ask whether
CreditProbe understood this clause correctly the first time, and an edit in
place makes that unanswerable.

And §33's last line is the one that shapes the module: "A correction from one
user is not automatically authoritative." A correction is captured as a
Regulatory Learning Observation and takes effect through review, regression
and release — never because a reviewer was confident and had the button.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.regulatory import requirements as rq

logger = logging.getLogger(__name__)

REVIEW_VERSION = "1.0.0"

# --------------------------------------------------------------- §32 actions

APPROVE = "APPROVE"
REJECT_NOT_RELEVANT = "REJECT_NOT_RELEVANT"
CORRECT_INTERPRETATION = "CORRECT_INTERPRETATION"
SPLIT_REQUIREMENT = "SPLIT_REQUIREMENT"
MERGE_WITH_EXISTING = "MERGE_WITH_EXISTING"
DEFER = "DEFER"
REQUEST_SECOND_REVIEW = "REQUEST_SECOND_REVIEW"

ACTIONS: tuple[str, ...] = (
    APPROVE, REJECT_NOT_RELEVANT, CORRECT_INTERPRETATION, SPLIT_REQUIREMENT,
    MERGE_WITH_EXISTING, DEFER, REQUEST_SECOND_REVIEW,
)

ACTION_MEANS: dict[str, str] = {
    APPROVE: "This is what the clause requires, and this is what it would "
             "touch here.",
    REJECT_NOT_RELEVANT: "The clause is real and does not apply to this "
                         "bank. A statement about the regulation, not about "
                         "the extraction.",
    CORRECT_INTERPRETATION: "The clause matters and we read it wrongly. Your "
                            "reading is kept beside ours, not instead of it.",
    SPLIT_REQUIREMENT: "This is two requirements wearing one clause. Each "
                       "half gets its own review.",
    MERGE_WITH_EXISTING: "We already hold this requirement from another "
                         "document. Keep one, cited from both.",
    DEFER: "Not now. Stays in the queue with a reason and does not count as "
           "reviewed.",
    REQUEST_SECOND_REVIEW: "Above my pay grade, or I am not certain. Goes to "
                           "another named reviewer rather than through.",
}

#: Which validation status each action produces.
OUTCOME: dict[str, str] = {
    APPROVE: rq.APPROVED,
    REJECT_NOT_RELEVANT: rq.REJECTED,
    CORRECT_INTERPRETATION: rq.CORRECTED,
    SPLIT_REQUIREMENT: rq.SPLIT,
    MERGE_WITH_EXISTING: rq.MERGED,
    DEFER: rq.DEFERRED,
    REQUEST_SECOND_REVIEW: rq.SECOND_REVIEW,
}

#: Actions that need more than a reason: a correction needs the corrected
#: reading, a split needs the pieces, a merge needs what it merges into.
NEEDS_TARGET: frozenset[str] = frozenset({
    CORRECT_INTERPRETATION, SPLIT_REQUIREMENT, MERGE_WITH_EXISTING,
})

#: Actions that do NOT count as having reviewed the requirement. A queue that
#: counted deferrals as progress would report itself finished while the hard
#: ones sat untouched.
NOT_PROGRESS: frozenset[str] = frozenset({DEFER, REQUEST_SECOND_REVIEW})


class ReviewError(Exception):
    """A review decision that was refused, and why."""


# --------------------------------------------------------------- §32's panel


def panel(requirement: rq.Requirement, *,
          document: dict[str, Any] | None = None,
          conflicts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """§32's four blocks, in §32's order.

    SOURCE first and always. A reviewer shown the machine's reading before
    the regulator's sentence is reviewing the reading, and will agree with it
    more often than they should.
    """
    doc = document or {}
    return {
        "requirement_id": requirement.requirement_id,
        "source": {
            "page": requirement.page,
            "section": requirement.section_number,
            "section_title": requirement.section_title,
            "paragraph": requirement.paragraph,
            "excerpt": requirement.excerpt,
            "excerpt_truncated": requirement.excerpt_truncated,
            "document": {
                "document_id": requirement.document_id,
                "title": doc.get("title", ""),
                "regulator": doc.get("regulator", ""),
                "reference": doc.get("reference", ""),
                "jurisdiction": doc.get("jurisdiction",
                                        requirement.jurisdiction),
                "issued": doc.get("issued", ""),
                "effective": doc.get("effective", ""),
                "content_hash": doc.get("content_hash", ""),
            },
        },
        "understanding": {
            "summary": requirement.summary,
            "requirement_type": requirement.requirement_type,
            "type_means": rq.TYPE_MEANS.get(requirement.requirement_type, ""),
            "relevance": requirement.relevance,
            "topics": list(requirement.topics),
            "scope": {
                "jurisdiction": requirement.jurisdiction,
                "portfolio": list(requirement.portfolio_scope),
                "product": list(requirement.product_scope),
                "effective_from": (requirement.effective_from.isoformat()
                                   if requirement.effective_from else ""),
            },
            "implications": _implications(requirement),
            "proposed_configuration": _proposed_configuration(requirement),
            "interpretation_confidence":
                requirement.interpretation_confidence,
            "confidence_because": list(requirement.confidence_because),
            "this_is_our_reading": (
                "Everything in this block is CreditProbe's interpretation of "
                "the excerpt above. The excerpt is the regulator's; this is "
                "not."
            ),
        },
        "conflicts": conflicts or [],
        "actions": [{"id": a, "means": ACTION_MEANS[a],
                     "needs_target": a in NEEDS_TARGET,
                     "counts_as_reviewed": a not in NOT_PROGRESS}
                    for a in ACTIONS],
    }


def _implications(requirement: rq.Requirement) -> list[str]:
    """What accepting this requirement would mean here, as sentences.

    Says nothing where nothing was found, rather than listing empty
    categories. "Affected methods: none" reads as a checked box; the absence
    of the line reads as what it is.
    """
    lines: list[str] = []
    pairs = (
        ("concept", requirement.affected_concepts),
        ("dataset", requirement.affected_datasets),
        ("governed relationship", requirement.affected_relationships),
        ("certified method", requirement.affected_methods),
        ("calculation", requirement.affected_calculations),
        ("control", requirement.affected_controls),
        ("regulatory report", requirement.affected_reports),
        ("agent", requirement.affected_agents),
        ("teaching case", requirement.affected_teaching_cases),
    )
    for label, values in pairs:
        if not values:
            continue
        plural = "" if len(values) == 1 else "s"
        lines.append(
            f"Touches {len(values)} {label}{plural}: {', '.join(values[:6])}"
            + (" …" if len(values) > 6 else ""))
    if not lines:
        lines.append(
            "Nothing here was identified as affected. That is a reason to "
            "look harder rather than a reason to approve quickly: a "
            "requirement that touches nothing is usually a requirement we "
            "did not map.")
    return lines


def _proposed_configuration(requirement: rq.Requirement) -> dict[str, Any]:
    """What §35 would DRAFT if this were approved. A draft, never a change."""
    return {
        "would_draft": requirement.configurable
        or bool(requirement.affected_concepts
                or requirement.affected_methods),
        "analysis_studio_draft_method": requirement.configurable,
        "why_only_a_draft": (
            "§35 forbids direct mutation from extraction, and §36 forbids "
            "auto-certification. Approving this requirement creates a draft "
            "that then goes through the ordinary Analysis Studio validation "
            "and certification workflow, exactly as a method somebody wrote "
            "by hand would."
        ),
        "targets": _targets(requirement),
    }


#: §35's promotion targets, by requirement type. What a requirement of this
#: kind could plausibly change — offered as a starting point for the
#: reviewer, never applied.
TARGETS: dict[str, tuple[str, ...]] = {
    rq.DEFINITION: ("ontology concept", "concept alias", "semantic contract",
                    "teaching case"),
    rq.SCOPE: ("semantic contract", "business invariant",
               "investigation blueprint"),
    rq.THRESHOLD: ("risk appetite threshold", "business invariant",
                   "risk case rule", "method validation"),
    rq.CALCULATION: ("analysis studio method", "method validation",
                     "business invariant"),
    rq.CLASSIFICATION: ("analysis studio method", "ontology concept",
                        "business invariant", "teaching case"),
    rq.DATA: ("data builder required field", "quality rule",
              "relationship requirement"),
    rq.REPORTING: ("regulatory report requirement", "monitoring schedule"),
    rq.DISCLOSURE: ("regulatory report requirement",),
    rq.GOVERNANCE: ("workflow control", "agent policy"),
    rq.CONTROL: ("workflow control", "quality rule", "agent policy"),
    rq.MONITORING: ("monitoring schedule", "risk case rule", "agent policy"),
    rq.WORKFLOW: ("workflow control", "risk case rule"),
    rq.TIMELINE: ("monitoring schedule", "workflow control"),
    rq.EXCEPTION: ("business invariant", "semantic contract",
                   "analysis studio method"),
    rq.TRANSITION: ("business invariant", "monitoring schedule",
                    "teaching case"),
}

#: §35's eighteen. Listed so a target nobody thought of cannot be invented by
#: a caller passing a string.
PROMOTION_TARGETS: tuple[str, ...] = (
    "ontology concept", "concept alias", "semantic contract",
    "data builder required field", "quality rule",
    "relationship requirement", "analysis studio method",
    "method validation", "business invariant", "risk appetite threshold",
    "agent policy", "monitoring schedule", "risk case rule",
    "workflow control", "teaching case", "investigation blueprint",
    "prompt and context retrieval", "regulatory report requirement",
)

EXPECTED_TARGETS = 18
if len(PROMOTION_TARGETS) != EXPECTED_TARGETS:
    raise AssertionError(
        f"§35 names {EXPECTED_TARGETS} promotion targets; this module has "
        f"{len(PROMOTION_TARGETS)}.")


def _targets(requirement: rq.Requirement) -> list[str]:
    return list(TARGETS.get(requirement.requirement_type, ()))


# ------------------------------------------------------ §33 the observation


@dataclass
class Correction:
    """§33's record. What we thought, what they said, and neither wins yet.

    Every field §33 lists, and one it does not: `authoritative`, which is
    always False on creation. §33's closing line is that a correction from
    one user is not automatically authoritative, and a record with no field
    for that fact would leave it to whoever writes the next query.
    """

    correction_id: str = ""
    requirement_id: str = ""
    document_id: str = ""

    #: What the machine said. Kept verbatim; the correction sits beside it.
    original_interpretation: str = ""
    original_type: str = ""
    original_confidence: float = 0.0

    #: What the reviewer said it really means.
    correction: str = ""
    corrected_type: str = ""
    reason: str = ""

    user_id: str = ""
    user_role: str = ""

    scope: str = ""
    effective_date: str = ""
    #: The structured change the reviewer is proposing, if any — a threshold
    #: value, a concept alias, a method input. Free-form on purpose: it is a
    #: proposal, and forcing it into a schema before anyone has agreed it is
    #: how a proposal becomes a fact.
    proposed_target: dict[str, Any] = field(default_factory=dict)

    review_status: str = rq.PROPOSED
    conflict_impact: tuple[str, ...] = ()
    regression_tests: tuple[str, ...] = ()

    #: Never true on creation. Becomes true only through the release path.
    authoritative: bool = False
    created_at: str = ""
    tenant: str = ""

    def __post_init__(self) -> None:
        self.correction_id = (self.correction_id
                              or f"rcor_{uuid.uuid4().hex[:16]}")
        self.created_at = self.created_at or datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "correction_id": self.correction_id,
            "requirement_id": self.requirement_id,
            "document_id": self.document_id,
            "original_interpretation": self.original_interpretation,
            "original_type": self.original_type,
            "original_confidence": round(self.original_confidence, 3),
            "correction": self.correction,
            "corrected_type": self.corrected_type,
            "reason": self.reason,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "scope": self.scope,
            "effective_date": self.effective_date,
            "proposed_target": dict(self.proposed_target),
            "review_status": self.review_status,
            "conflict_impact": list(self.conflict_impact),
            "regression_tests": list(self.regression_tests),
            "authoritative": self.authoritative,
            "created_at": self.created_at,
            "activates_nothing": True,
        }


def record_correction(requirement: rq.Requirement, *, correction: str,
                      reason: str, user_id: str, user_role: str,
                      corrected_type: str = "", scope: str = "",
                      effective_date: str = "",
                      proposed_target: dict[str, Any] | None = None
                      ) -> Correction:
    """§33. Capture a reviewer's reading beside the machine's, activating
    nothing.

    Refuses a correction with no reason. "That is wrong" tells the next
    reviewer that somebody disagreed and nothing about why, and this record
    exists precisely to be read by somebody who was not in the room.
    """
    if not correction.strip():
        raise ReviewError(
            "a correction has to say what the clause does mean. Saying only "
            "that our reading is wrong leaves the next reviewer with two "
            "unknowns instead of one")
    if not reason.strip():
        raise ReviewError(
            "a correction with no reason cannot be reviewed later, and this "
            "is the record somebody will read a year from now")
    if not user_id.strip():
        raise ReviewError("a correction needs a named person")
    if corrected_type and corrected_type not in rq.TYPES:
        raise ReviewError(
            f"{corrected_type!r} is not one of §30's fifteen requirement "
            "types")
    return Correction(
        requirement_id=requirement.requirement_id,
        document_id=requirement.document_id,
        original_interpretation=requirement.summary,
        original_type=requirement.requirement_type,
        original_confidence=requirement.interpretation_confidence,
        correction=correction.strip(),
        corrected_type=corrected_type or requirement.requirement_type,
        reason=reason.strip(),
        user_id=user_id,
        user_role=user_role,
        scope=scope,
        effective_date=effective_date,
        proposed_target=proposed_target or {},
        tenant=requirement.tenant,
    )


# ------------------------------------------------------------ §32 the action


def decide(requirement: rq.Requirement, action: str, *, reviewer: str,
           reason: str, target: str = "") -> rq.Requirement:
    """Apply one of §32's seven actions, or refuse.

    Returns the requirement at its new status. The reason is required for
    every action including approval: "approved" with no assessment is
    indistinguishable from nobody having looked, which is the state this
    whole review exists to end.
    """
    if action not in ACTIONS:
        raise ReviewError(
            f"{action!r} is not one of §32's seven actions; expected one of "
            f"{', '.join(ACTIONS)}")
    if not reviewer.strip():
        raise ReviewError("a review decision needs a named reviewer")
    if not reason.strip():
        raise ReviewError(
            "every decision needs a reason, approval included. 'Approved' "
            "with no assessment reads exactly like nobody having looked")
    if action in NEEDS_TARGET and not target.strip():
        needs = {
            CORRECT_INTERPRETATION: "the corrected reading",
            SPLIT_REQUIREMENT: "what the two requirements are",
            MERGE_WITH_EXISTING: "the requirement this merges into",
        }[action]
        raise ReviewError(f"{action} needs {needs}")
    if requirement.validation_status in (rq.APPROVED, rq.REJECTED) \
            and action != CORRECT_INTERPRETATION:
        raise ReviewError(
            f"this requirement is already {requirement.validation_status}. "
            "Re-deciding it would overwrite a decision somebody made; a new "
            "reading is recorded as a correction against it")

    requirement.validation_status = OUTCOME[action]
    requirement.reviewer = reviewer.strip()
    requirement.decision = action
    requirement.decision_reason = reason.strip()
    requirement.version += 1
    if action == CORRECT_INTERPRETATION:
        requirement.correction = target.strip()
    if action == REJECT_NOT_RELEVANT:
        # Only now may a clause be called not credit-related: a person said
        # so and their name is on it. §31 forbids extraction from doing this.
        requirement.relevance = rq.NOT_CREDIT_RELATED
    return requirement


def queue_progress(requirements: list[rq.Requirement]) -> dict[str, Any]:
    """How much of a document has genuinely been reviewed.

    Deferrals and second-review requests are counted separately and not as
    progress. A queue that counted them would report itself finished while
    every hard requirement sat untouched — which is the shape of every
    review backlog that has ever been declared complete.
    """
    total = len(requirements)
    decided = [r for r in requirements
               if r.decision and r.decision not in NOT_PROGRESS]
    parked = [r for r in requirements if r.decision in NOT_PROGRESS]
    untouched = [r for r in requirements if not r.decision]
    return {
        "total": total,
        "reviewed": len(decided),
        "parked": len(parked),
        "untouched": len(untouched),
        "parked_ids": [r.requirement_id for r in parked],
        "complete": total > 0 and len(decided) == total,
        "note": (
            "Deferred and second-review requirements are not counted as "
            "reviewed. A queue that counted them would report itself "
            "finished with every difficult requirement still open."
        ),
    }
