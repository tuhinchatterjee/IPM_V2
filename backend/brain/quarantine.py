"""Import a Brain, without letting it touch production. §16, §17, §22, §23.

§16's first sentence is the whole design: "Uploading a Brain Pack or Learning
Bundle must never alter active production immediately."

So an upload is not an install. It is a candidate that sits in quarantine
and walks a pipeline, and every stage can stop it:

    UPLOADED → FORMAT → SIGNATURE → SCHEMA → PROVENANCE → COMPATIBILITY
    → PRIVACY → DIFF → CONFLICTS → EVALUATION → IMPACT → REMEDIATION
    → APPROVAL → STAGED → ACTIVE

The order matters and is not arbitrary. Format before signature, because
verifying a signature means reading the archive. Compatibility before
evaluation, because evaluating components the receiver cannot run wastes a
run and produces a number that means nothing. Evaluation before approval,
because approving without measured lift is approving a claim.

Two states carry most of the value.

`DORMANT` is what an incompatible component becomes. §17 is explicit that a
user may import a package the receiver cannot fully run, and that unsupported
components "must not silently activate". Dormant is visible, inert, and
reversible when the missing module arrives.

`QUARANTINED` never allows retrieval. A candidate's teaching cases are not
reachable from a live answer, at any point, until activation. There is no
flag for this and no configuration - the candidate simply is not in the
retrieval path.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

QUARANTINE_VERSION = "1.0.0"

# ------------------------------------------------------------------ stages

UPLOADED = "UPLOADED"
FORMAT_CHECKED = "FORMAT_CHECKED"
SIGNATURE_CHECKED = "SIGNATURE_CHECKED"
SCHEMA_VALIDATED = "SCHEMA_VALIDATED"
PROVENANCE_CHECKED = "PROVENANCE_CHECKED"
COMPATIBILITY_CHECKED = "COMPATIBILITY_CHECKED"
PRIVACY_SCANNED = "PRIVACY_SCANNED"
DIFFED = "DIFFED"
CONFLICTS_DETECTED = "CONFLICTS_DETECTED"
EVALUATED = "EVALUATED"
IMPACT_REPORTED = "IMPACT_REPORTED"
REMEDIATED = "REMEDIATED"
APPROVED = "APPROVED"
STAGED = "STAGED"
ACTIVE = "ACTIVE"

ROLLED_BACK = "ROLLED_BACK"
RETIRED = "RETIRED"
REJECTED = "REJECTED"
DELETED = "DELETED"

#: The happy path, in order. A candidate may not skip a stage.
PIPELINE: tuple[str, ...] = (
    UPLOADED, FORMAT_CHECKED, SIGNATURE_CHECKED, SCHEMA_VALIDATED,
    PROVENANCE_CHECKED, COMPATIBILITY_CHECKED, PRIVACY_SCANNED, DIFFED,
    CONFLICTS_DETECTED, EVALUATED, IMPACT_REPORTED, REMEDIATED, APPROVED,
    STAGED, ACTIVE,
)

#: States a candidate can end in without activating.
TERMINAL: frozenset[str] = frozenset(
    {ROLLED_BACK, RETIRED, REJECTED, DELETED})

#: Everything before STAGED. Nothing in these states may be retrieved from,
#: tuned against, or counted in a coverage figure.
QUARANTINED: frozenset[str] = frozenset(PIPELINE[:PIPELINE.index(STAGED)])

#: A candidate may be deleted from quarantine by an authorised user, and may
#: not be deleted once it has been activated - §23 keeps the installation
#: record even when the payload is purged.
DELETABLE: frozenset[str] = QUARANTINED | {REJECTED}


class QuarantineError(Exception):
    """A transition that would let a candidate touch production early."""


@dataclass
class Component:
    """One thing an incoming package carries, and whether it can run here."""

    kind: str
    name: str
    version: str = ""
    #: SUPPORTED, DORMANT or INCOMPATIBLE.
    state: str = "SUPPORTED"
    reason: str = ""

    @property
    def activatable(self) -> bool:
        return self.state == "SUPPORTED"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name,
                "version": self.version, "state": self.state,
                "reason": self.reason}


@dataclass
class Step:
    """One stage, and what it found."""

    stage: str
    at: str = ""
    passed: bool = True
    detail: str = ""
    by: str = ""

    def __post_init__(self) -> None:
        self.at = self.at or datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "at": self.at, "passed": self.passed,
                "detail": self.detail, "by": self.by}


@dataclass
class Candidate:
    """An uploaded package, and how far it has got."""

    candidate_id: str = ""
    package_kind: str = ""
    brain_id: str = ""
    brain_name: str = ""
    brain_version: str = ""
    source_instance_id: str = ""
    digest: str = ""
    uploaded_by: str = ""
    uploaded_at: str = ""
    tenant: str = ""

    stage: str = UPLOADED
    history: list[Step] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    #: Filled in as the pipeline runs.
    inspection: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)
    diff: dict[str, Any] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    evaluation: dict[str, Any] = field(default_factory=dict)
    impact: dict[str, Any] = field(default_factory=dict)
    approvals: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.candidate_id = self.candidate_id or f"cand_{uuid.uuid4().hex[:12]}"
        self.uploaded_at = self.uploaded_at or datetime.now(UTC).isoformat()
        if not self.history:
            self.history.append(Step(UPLOADED, by=self.uploaded_by))

    # ---------------------------------------------------------- properties

    @property
    def quarantined(self) -> bool:
        """Whether this candidate is still sealed off from production."""
        return self.stage in QUARANTINED

    @property
    def retrievable(self) -> bool:
        """Whether a live answer may retrieve from this candidate.

        Only once ACTIVE. There is no configuration that changes this: a
        candidate is simply not in the retrieval path until it is the active
        Brain.
        """
        return self.stage == ACTIVE

    @property
    def dormant(self) -> list[Component]:
        return [c for c in self.components if c.state == "DORMANT"]

    @property
    def incompatible(self) -> list[Component]:
        return [c for c in self.components if c.state == "INCOMPATIBLE"]

    @property
    def activatable(self) -> list[Component]:
        return [c for c in self.components if c.activatable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "package_kind": self.package_kind,
            "brain_id": self.brain_id, "brain_name": self.brain_name,
            "brain_version": self.brain_version,
            "source_instance_id": self.source_instance_id,
            "digest": self.digest, "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at, "tenant": self.tenant,
            "stage": self.stage,
            "quarantined": self.quarantined,
            "retrievable": self.retrievable,
            "history": [s.to_dict() for s in self.history],
            "components": [c.to_dict() for c in self.components],
            "dormant": [c.to_dict() for c in self.dormant],
            "incompatible": [c.to_dict() for c in self.incompatible],
            "blockers": list(self.blockers),
            "inspection": self.inspection,
            "compatibility": self.compatibility,
            "diff": self.diff,
            "conflicts": list(self.conflicts),
            "evaluation": self.evaluation,
            "impact": self.impact,
            "approvals": list(self.approvals),
        }


# ------------------------------------------------------------- transitions


def advance(candidate: Candidate, stage: str, *, passed: bool = True,
            detail: str = "", by: str = "") -> Candidate:
    """Move a candidate one stage, or refuse.

    Refuses a skipped stage rather than allowing it. The pipeline order is
    the safety property - approving before evaluating is approving a claim,
    and evaluating before checking compatibility produces a number about
    components the receiver cannot run.
    """
    if stage not in PIPELINE and stage not in TERMINAL:
        raise QuarantineError(f"{stage!r} is not a stage")

    if stage in TERMINAL:
        candidate.stage = stage
        candidate.history.append(Step(stage, passed=passed, detail=detail,
                                      by=by))
        return candidate

    current = PIPELINE.index(candidate.stage) if candidate.stage in PIPELINE \
        else -1
    target = PIPELINE.index(stage)
    if target != current + 1:
        raise QuarantineError(
            f"a candidate at {candidate.stage} cannot move to {stage}: the "
            f"pipeline order is what stops a package being approved before "
            f"it was evaluated. Expected "
            f"{PIPELINE[current + 1] if current + 1 < len(PIPELINE) else 'nothing'}.")

    if not passed:
        candidate.blockers.append(f"{stage}: {detail}")
    candidate.history.append(Step(stage, passed=passed, detail=detail,
                                  by=by))
    candidate.stage = stage
    return candidate


def may_activate(candidate: Candidate, *,
                 high_trust_approval: bool = False) -> tuple[bool, str]:
    """Whether this candidate may become the active Brain, and why not.

    §26: a package from an untrusted signer may be inspected and evaluated
    but not activated without high-trust approval. That is checked here
    rather than at upload, because refusing it at upload would stop a
    reviewer examining a package they had every right to look at.
    """
    if candidate.stage != STAGED:
        return False, (
            f"the candidate is at {candidate.stage}; only a STAGED "
            "candidate may activate, and staging is what proves every "
            "earlier check ran")
    if candidate.blockers:
        return False, ("unresolved: " + "; ".join(candidate.blockers[:4]))
    if not candidate.approvals:
        return False, "nobody has approved this candidate"

    signature = str(candidate.inspection.get("signature_state") or "")
    if signature in ("UNSIGNED", "UNTRUSTED_SIGNER") and \
            not high_trust_approval:
        return False, (
            f"the package is {signature.lower().replace('_', ' ')}. It may "
            "be inspected and evaluated freely; activating it needs "
            "high-trust approval.")
    if signature in ("INVALID", "CONTENT_CHANGED", "MALFORMED"):
        return False, (
            "the signature does not hold, so what was evaluated is not "
            "necessarily what would activate")

    critical = candidate.evaluation.get("critical_regressions") or 0
    if critical:
        return False, (
            f"{critical} critical regression(s) were measured. §9 tolerates "
            "none of these, and a positive average does not offset one.")
    if not candidate.evaluation:
        return False, (
            "no evaluation was recorded, so activating this would be "
            "activating a claim rather than a measurement")
    return True, ""


def activate(candidate: Candidate, *, by: str,
             high_trust_approval: bool = False) -> Candidate:
    allowed, why = may_activate(candidate,
                                high_trust_approval=high_trust_approval)
    if not allowed:
        raise QuarantineError(f"this candidate may not activate: {why}")
    for component in candidate.dormant + candidate.incompatible:
        logger.info("component %s/%s stays %s: %s", component.kind,
                    component.name, component.state, component.reason)
    return advance(candidate, ACTIVE, by=by,
                   detail=f"{len(candidate.activatable)} component(s) "
                          f"activated, {len(candidate.dormant)} dormant")


def roll_back(candidate: Candidate, *, to: str, by: str,
              why: str) -> Candidate:
    """§23. Reversible, and recorded rather than reconstructed."""
    if candidate.stage != ACTIVE:
        raise QuarantineError(
            "only an active Brain can be rolled back; a candidate that "
            "never activated is deleted or rejected instead")
    if not why.strip():
        raise QuarantineError("a rollback with no reason cannot be reviewed")
    return advance(candidate, ROLLED_BACK, by=by,
                   detail=f"rolled back to {to}: {why}")


def delete(candidate: Candidate, *, by: str, why: str) -> Candidate:
    """§23: a candidate may be DELETED from quarantine before activation.

    Never after. An activated Brain leaves an installation record that
    outlives its payload, because "what did we install, when, and did it
    help?" has to stay answerable after the payload is purged.
    """
    if candidate.stage not in DELETABLE:
        raise QuarantineError(
            f"a candidate at {candidate.stage} may not be deleted. An "
            "activated Brain is retired or rolled back, and its "
            "installation record is kept even where the payload is purged.")
    if not why.strip():
        raise QuarantineError("a deletion with no reason cannot be reviewed")
    return advance(candidate, DELETED, by=by, detail=why)


def purge_payload(candidate: Candidate, *, by: str, why: str) -> Candidate:
    """§23's payload purge: the content goes, the record stays.

    Returns the candidate with its payload fields emptied and its manifest,
    history and measured impact intact. Never a hard delete of the evidence.
    """
    if not why.strip():
        raise QuarantineError("a purge with no reason cannot be reviewed")
    candidate.diff = {"purged": True, "why": why}
    candidate.conflicts = []
    candidate.history.append(Step("PAYLOAD_PURGED", by=by, detail=why))
    return candidate
