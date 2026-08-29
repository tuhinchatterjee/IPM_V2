"""
Channel B's frozen Learning Release, and rollback. §23, §24.

What a Learning Release is
---------------------------
The complete answer to "what was CreditProbe running when it produced this?".
Not a version number — a manifest: which teaching release, which regulatory
release, which prompt versions, which routing and agent policies, which
retrieval index, which auxiliary models, which ontology and method versions,
how many cases at which approval status, which feedback went into it, what it
scored, who reviewed it and who approved it.

Production uses ONE active release. Rollback is activating the previous one,
which is a normal operation rather than a recovery, because nothing was
deleted to get here.

The activation gates
---------------------
§23 names four, and each is a way a candidate can look better and be worse:

    zero new critical failures      — a release that fixes six things and
                                      breaks one that matters is a worse
                                      release, and the arithmetic of "net
                                      improvement" is how that ships
    improved target metrics         — measured, on the metrics the candidate
                                      was built to move
    no permission or safety
      regression                    — separately, because these are not
                                      metrics to trade against others
    no holdout leakage              — a candidate trained on its own test set
                                      scores beautifully and teaches nothing

And a fifth this codebase adds for the same reason it appears everywhere else
in the platform: an approver who is not the only reviewer.

    "Do not activate a candidate merely because user satisfaction improved."

Satisfaction is in the manifest and is not a gate. A release that made people
happier and made the answers worse is the exact failure the whole governance
layer exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

LEARNING_RELEASE_VERSION = "1.0.0"

DRAFT = "DRAFT"
CANDIDATE = "CANDIDATE"
ACTIVE = "ACTIVE"
ROLLED_BACK = "ROLLED_BACK"
RETIRED = "RETIRED"
BLOCKED = "BLOCKED"

STATUSES: tuple[str, ...] = (DRAFT, CANDIDATE, ACTIVE, ROLLED_BACK, RETIRED,
                             BLOCKED)


class ReleaseError(Exception):
    """A release that must not be built, activated or rolled back."""


# ---------------------------------------------------------------------------
# The gates
# ---------------------------------------------------------------------------

#: name -> what it is, and why it is not tradeable against the others.
GATES: dict[str, str] = {
    "no_new_critical_failures":
        "No case that passed on production fails on the candidate. A release "
        "that fixes six things and breaks one that matters is a worse "
        "release, and 'net improvement' is how that ships.",
    "target_metrics_improved":
        "The metrics this candidate was built to move actually moved. A "
        "release that changed nothing measurable is a change nobody can "
        "defend.",
    "no_safety_regression":
        "No permission, tenant or approval-gate behaviour got worse. Held "
        "separately from the metrics because it is not a quantity to trade.",
    "no_holdout_leakage":
        "No case in the sealed holdout appears in the training or curriculum "
        "set. A candidate trained on its own test scores beautifully and "
        "teaches nothing.",
    "reviewed_and_approved":
        "A named approver who is not the only reviewer. Two pairs of eyes on "
        "a material action, as everywhere else in the platform.",
}

GATE_NAMES: tuple[str, ...] = tuple(GATES)


@dataclass
class Gate:
    """One activation gate, and what it found."""

    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"gate": self.name, "passed": self.passed,
                "detail": self.detail, "means": GATES.get(self.name, "")}


@dataclass
class Metrics:
    """§27's before-and-after, for one release.

    Every field is `None` until measured. Zero would be a claim; None is the
    truth, and the manifest renders it as "not measured" rather than as a
    flattering nought.
    """

    critical_failures_before: int | None = None
    critical_failures_after: int | None = None
    accepted_precision: float | None = None
    independent_accuracy: float | None = None
    abstention_correctness: float | None = None
    officer_accuracy: float | None = None
    agent_precision: float | None = None
    dataset_accuracy: float | None = None
    method_accuracy: float | None = None
    period_accuracy: float | None = None
    grain_accuracy: float | None = None
    retrieval_precision: float | None = None
    grounding: float | None = None
    assurance_coverage: float | None = None
    satisfaction: float | None = None
    repeat_defect_rate: float | None = None
    latency_ms: int | None = None
    model_calls: float | None = None
    auxiliary_model_scores: dict[str, float] = field(default_factory=dict)

    @property
    def measured(self) -> list[str]:
        return [name for name, value in self.to_dict().items()
                if value is not None and name != "auxiliary_model_scores"]

    @property
    def unmeasured(self) -> list[str]:
        return [name for name, value in self.to_dict().items()
                if value is None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "critical_failures_before": self.critical_failures_before,
            "critical_failures_after": self.critical_failures_after,
            "accepted_precision": self.accepted_precision,
            "independent_accuracy": self.independent_accuracy,
            "abstention_correctness": self.abstention_correctness,
            "officer_accuracy": self.officer_accuracy,
            "agent_precision": self.agent_precision,
            "dataset_accuracy": self.dataset_accuracy,
            "method_accuracy": self.method_accuracy,
            "period_accuracy": self.period_accuracy,
            "grain_accuracy": self.grain_accuracy,
            "retrieval_precision": self.retrieval_precision,
            "grounding": self.grounding,
            "assurance_coverage": self.assurance_coverage,
            "satisfaction": self.satisfaction,
            "repeat_defect_rate": self.repeat_defect_rate,
            "latency_ms": self.latency_ms,
            "model_calls": self.model_calls,
            "auxiliary_model_scores": dict(self.auxiliary_model_scores),
        }


@dataclass
class LearningRelease:
    """§24's manifest, frozen."""

    release_id: str = field(
        default_factory=lambda: f"lr-{uuid.uuid4().hex[:12]}")
    tenant: str = ""
    status: str = DRAFT

    # ---- what it contains
    teaching_release_id: str = ""
    regulatory_release_id: str = ""
    prompt_versions: dict[str, str] = field(default_factory=dict)
    routing_policy: str = ""
    agent_policy: str = ""
    retrieval_index: str = ""
    auxiliary_models: dict[str, str] = field(default_factory=dict)
    ontology_version: str = ""
    method_version: str = ""
    data_semantic_version: str = ""

    # ---- what went into it
    case_counts: dict[str, int] = field(default_factory=dict)
    feedback_events: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)

    # ---- what it scored
    metrics: Metrics = field(default_factory=Metrics)
    gates: list[Gate] = field(default_factory=list)

    # ---- who
    reviewers: list[str] = field(default_factory=list)
    approver: str = ""
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None
    replaces: str = ""
    note: str = ""
    build_sha: str = ""
    schema_version: str = LEARNING_RELEASE_VERSION

    @property
    def blocked_by(self) -> list[str]:
        return [g.name for g in self.gates if not g.passed]

    @property
    def gated(self) -> bool:
        """Whether every gate has been RUN, not whether they passed.

        A release with three of five gates evaluated is not "60% approved" —
        it is unevaluated, and treating a missing gate as a pass is the
        commonest way an unproven release ships.
        """
        return {g.name for g in self.gates} == set(GATE_NAMES)

    def fingerprint(self) -> str:
        body = json.dumps({
            "teaching": self.teaching_release_id,
            "regulatory": self.regulatory_release_id,
            "prompts": dict(sorted(self.prompt_versions.items())),
            "routing": self.routing_policy, "agents": self.agent_policy,
            "index": self.retrieval_index,
            "models": dict(sorted(self.auxiliary_models.items())),
            "ontology": self.ontology_version, "method": self.method_version,
            "candidates": sorted(self.candidates),
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id, "tenant": self.tenant,
            "status": self.status,
            "teaching_release_id": self.teaching_release_id,
            "regulatory_release_id": self.regulatory_release_id,
            "prompt_versions": dict(self.prompt_versions),
            "routing_policy": self.routing_policy,
            "agent_policy": self.agent_policy,
            "retrieval_index": self.retrieval_index,
            "auxiliary_models": dict(self.auxiliary_models),
            "ontology_version": self.ontology_version,
            "method_version": self.method_version,
            "data_semantic_version": self.data_semantic_version,
            "case_counts": dict(self.case_counts),
            "feedback_events": list(self.feedback_events),
            "candidates": list(self.candidates),
            "metrics": self.metrics.to_dict(),
            "measured": self.metrics.measured,
            "not_measured": self.metrics.unmeasured,
            "gates": [g.to_dict() for g in self.gates],
            "gated": self.gated,
            "blocked_by": self.blocked_by,
            "reviewers": sorted(set(self.reviewers)),
            "approver": self.approver, "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "activated_at": (self.activated_at.isoformat()
                             if self.activated_at else ""),
            "replaces": self.replaces, "note": self.note,
            "build_sha": self.build_sha,
            "fingerprint": self.fingerprint(),
            "schema_version": self.schema_version,
        }


def build(candidates: list[Any], *, created_by: str, tenant: str = "",
          teaching_release_id: str = "", regulatory_release_id: str = "",
          note: str = "") -> LearningRelease:
    """Freeze approved candidates into a candidate release.

    Only HUMAN_APPROVED. A release that admitted SYSTEM_REFERENCE_VALIDATED
    cases would be a release of things a deterministic check liked, which is
    not the same as things a person signed for — and the whole nine-status
    ladder exists to keep those apart.
    """
    from backend.learning import candidate as cd

    approved = [c for c in candidates if getattr(c, "status", "")
                == cd.HUMAN_APPROVED]
    if not approved:
        raise ReleaseError(
            "there is nothing to release: no candidate has been approved by a "
            "named reviewer. A deterministic validation passing is not a "
            "person agreeing.")

    counts: dict[str, int] = {}
    for case in candidates:
        status = str(getattr(case, "status", ""))
        counts[status] = counts.get(status, 0) + 1

    return LearningRelease(
        tenant=tenant, status=CANDIDATE,
        teaching_release_id=teaching_release_id,
        regulatory_release_id=regulatory_release_id,
        case_counts=counts,
        candidates=[str(c.candidate_id) for c in approved],
        feedback_events=[str(getattr(c, "feedback_event_id", ""))
                         for c in approved
                         if getattr(c, "feedback_event_id", "")],
        reviewers=[str(getattr(c, "reviewer", "")) for c in approved
                   if getattr(c, "reviewer", "")],
        created_by=created_by, note=note)


def evaluate(release: LearningRelease, *, critical_before: int,
             critical_after: int, improved: dict[str, bool],
             safety_regressions: list[str],
             holdout_overlap: list[str]) -> LearningRelease:
    """Run §23's gates over a measured candidate.

    The gates are recorded whether they pass or fail. A release that fails one
    keeps the finding in its own manifest, so the next attempt starts from
    what was wrong rather than from somebody's memory of it.
    """
    release.metrics.critical_failures_before = critical_before
    release.metrics.critical_failures_after = critical_after

    moved = [name for name, better in improved.items() if better]
    worse = [name for name, better in improved.items() if not better]

    release.gates = [
        Gate("no_new_critical_failures",
             critical_after <= critical_before,
             (f"{critical_after} critical failure(s) against "
              f"{critical_before} on production.")),
        Gate("target_metrics_improved", bool(moved) and not worse,
             (f"improved: {', '.join(moved) or 'none'}"
              + (f"; worse: {', '.join(worse)}" if worse else ""))),
        Gate("no_safety_regression", not safety_regressions,
             ("no permission, tenant or approval-gate regression"
              if not safety_regressions
              else f"regressions: {', '.join(safety_regressions)}")),
        Gate("no_holdout_leakage", not holdout_overlap,
             ("no sealed-holdout case appears in the curriculum"
              if not holdout_overlap
              else (f"{len(holdout_overlap)} holdout case(s) appear in the "
                    "curriculum: " + ", ".join(holdout_overlap[:5])))),
        Gate("reviewed_and_approved", False,
             "not yet approved — an approver is named at activation"),
    ]
    if release.blocked_by != ["reviewed_and_approved"]:
        release.status = BLOCKED
    return release


def activate(release: LearningRelease, *, approver: str,
             current: LearningRelease | None = None) -> LearningRelease:
    """Make a candidate release the one production uses."""
    if release.status not in (CANDIDATE, ROLLED_BACK, BLOCKED):
        raise ReleaseError(f"a {release.status} release cannot be activated")
    if not str(approver).strip():
        raise ReleaseError("a release needs a named approver")
    if not release.gated:
        missing = sorted(set(GATE_NAMES) - {g.name for g in release.gates})
        raise ReleaseError(
            "this release has not been evaluated against every gate; "
            f"{', '.join(missing)} did not run. A gate that did not run is "
            "not a gate that passed.")

    failed = [g for g in release.gates
              if not g.passed and g.name != "reviewed_and_approved"]
    if failed:
        release.status = BLOCKED
        raise ReleaseError(
            "this release failed " + ", ".join(g.name for g in failed)
            + ". " + " ".join(g.detail for g in failed))

    reviewers = {r for r in release.reviewers if r}
    if reviewers and reviewers == {approver.strip()}:
        raise ReleaseError(
            f"{approver} reviewed every candidate in this release and cannot "
            "also approve it: activating a Learning Release changes what "
            "CreditProbe does in production and needs a second pair of eyes")

    release.approver = approver.strip()
    for gate in release.gates:
        if gate.name == "reviewed_and_approved":
            gate.passed = True
            gate.detail = (f"approved by {release.approver}, reviewed by "
                           + ", ".join(sorted(reviewers)) or "—")
    release.status = ACTIVE
    release.activated_at = datetime.now(UTC)
    if current is not None and current.release_id != release.release_id:
        current.status = ROLLED_BACK
        release.replaces = current.release_id
    return release


def rollback(active: LearningRelease, previous: LearningRelease, *,
             approver: str, why: str) -> LearningRelease:
    """Return production to the release before this one."""
    if not str(why).strip():
        raise ReleaseError(
            "a rollback needs a reason: an unexplained return to an earlier "
            "release is indistinguishable from an accident")
    active.status = ROLLED_BACK
    active.note = f"{active.note} Rolled back: {why}".strip()
    previous.status = CANDIDATE
    return activate(previous, approver=approver)


__all__ = ["ACTIVE", "BLOCKED", "CANDIDATE", "DRAFT", "GATES", "GATE_NAMES",
           "Gate", "LEARNING_RELEASE_VERSION", "LearningRelease", "Metrics",
           "RETIRED", "ROLLED_BACK", "ReleaseError", "STATUSES", "activate",
           "build", "evaluate", "rollback"]
