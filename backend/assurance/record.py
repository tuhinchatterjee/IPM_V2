"""
The Investigation Assurance Record: what this answer can prove about itself.
§180, §181, §182, §183, §184, §185.

Four instructions, and each one is a place a score lies
--------------------------------------------------------
    §182: "Do not compute the overall result by blindly averaging the six
           dimensions."
    §183: "SKIPPED is never PASS."
    §183: "A missing check is not silently treated as NOT_APPLICABLE."
    §184: "Do not display 'Accuracy 96%' for a live Investigation with no
           independent reference."

The last one is the deepest. A live Investigation has no right answer to
compare against — that is what makes it a live Investigation rather than an
evaluation case. Everything the runtime can establish is OPERATIONAL: the plan
validated, the joins reconciled, the invariants held, every figure traced to a
fact, the Trace matches what ran. That is a great deal and it is not accuracy.
Calling it accuracy invites a reader to believe the number answers "is this
right?", which nothing here can answer without a reference answer, and the
absence of one is not visible on screen.

So there are two separate things and they are never combined: OPERATIONAL
ASSURANCE, always available; REFERENCE MATCH, available only where an approved
benchmark exists.

The gates come before the score
---------------------------------
§182's order is critical gates, then coverage gate, then the weighted score.
A record with a failed invariant does not get a score at all — it gets FAILED,
and reporting "72/100 (FAILED)" would invite somebody to notice the 72. So
`overall()` returns early and the score is None where a gate fired.

Immutable
---------
§180 says so and `fingerprint()` enforces it: the record hashes its own
content, and a record whose fingerprint does not match its content has been
edited. An assurance record that could be revised after the fact is a record
of what somebody wanted to have happened.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.assurance import dimensions as dm

RECORD_VERSION = "1.0.0"

# ---------------------------------------------------- §183's five outcomes
PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
#: Never PASS. §183 says it in as many words, and it is the rule that stops a
#: coverage number being improved by running fewer checks.
SKIPPED = "SKIPPED"
#: Excluded from the denominator ONLY where applicability was deterministically
#: established. A check nobody ran is SKIPPED, not NOT_APPLICABLE.
NOT_APPLICABLE = "NOT_APPLICABLE"

OUTCOMES: tuple[str, ...] = (PASS, WARNING, FAIL, SKIPPED, NOT_APPLICABLE)

#: Outcomes that count toward coverage — the check actually ran and produced
#: a judgement.
COUNTED: frozenset[str] = frozenset({PASS, WARNING, FAIL})

# ------------------------------------------------- §181's seven statuses
HIGH_ASSURANCE = "HIGH_ASSURANCE"
VALIDATED = "VALIDATED"
VALIDATED_WITH_LIMITATIONS = "VALIDATED_WITH_LIMITATIONS"
NEEDS_REVIEW = "NEEDS_REVIEW"
FAILED = "FAILED"
UNVERIFIED = "UNVERIFIED"
STALE = "STALE"

STATUSES: tuple[str, ...] = (HIGH_ASSURANCE, VALIDATED,
                             VALIDATED_WITH_LIMITATIONS, NEEDS_REVIEW,
                             FAILED, UNVERIFIED, STALE)

MEANS: dict[str, str] = {
    HIGH_ASSURANCE: "Every mandatory critical check passed, evidence coverage "
                    "is high, and the release and build are current.",
    VALIDATED: "Every mandatory critical check passed on sufficient evidence. "
               "Some non-critical warnings exist.",
    VALIDATED_WITH_LIMITATIONS: "The correctness checks passed and material "
                                "limitations or evidence gaps exist. They are "
                                "stated in the answer.",
    NEEDS_REVIEW: "Nothing is proven wrong, and one or more required checks "
                  "were incomplete, skipped or ambiguous. A person should "
                  "look.",
    FAILED: "A critical check failed. This answer should have been blocked or "
            "controlled.",
    UNVERIFIED: "Not enough validation evidence exists to make any assurance "
                "claim about this answer.",
    STALE: "Something this record was produced against has since changed, so "
           "it describes a version of CreditProbe that no longer runs.",
}

#: Score at or above which HIGH_ASSURANCE is available, and coverage at or
#: above which a claim may be made at all. Both versioned with the weights.
#: §184. The one name this number is allowed to have, wherever it is shown.
#: A constant rather than a string literal per surface, because "accuracy"
#: appearing on one screen out of six is exactly how the rule gets lost.
ASSURANCE_LABEL = "Operational assurance"

HIGH_ASSURANCE_AT = 90.0
MIN_COVERAGE_PCT = 70.0
#: Below this, nothing may be claimed: UNVERIFIED.
UNVERIFIED_BELOW_PCT = 40.0


@dataclass
class Check:
    """One subcomponent's outcome. §179's fields."""

    subcomponent: str
    outcome: str = SKIPPED
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    #: Why this check does not apply. Required for NOT_APPLICABLE: §183 says
    #: applicability must be deterministically established, and a reason is
    #: the cheapest evidence that somebody established it.
    not_applicable_because: str = ""

    @property
    def dimension(self) -> str:
        return dm.dimension_of(self.subcomponent)

    @property
    def critical(self) -> bool:
        return self.subcomponent in dm.CRITICAL

    @property
    def counted(self) -> bool:
        return self.outcome in COUNTED

    def to_dict(self) -> dict[str, Any]:
        return {"subcomponent": self.subcomponent,
                "dimension": self.dimension, "outcome": self.outcome,
                "detail": self.detail, "evidence": list(self.evidence),
                "critical": self.critical, "counted": self.counted,
                "not_applicable_because": self.not_applicable_because}


class NotEstablished(Exception):
    """A NOT_APPLICABLE with no reason.

    §183: "NOT_APPLICABLE is excluded from the denominator only when
    applicability is deterministically established." An unreasoned
    NOT_APPLICABLE removes a check from the denominator, which improves
    coverage by not looking — the exact incentive this rule exists to remove.
    """


@dataclass
class DimensionResult:
    """One dimension's rolled-up result."""

    dimension: str
    checks: list[Check] = field(default_factory=list)

    @property
    def counted(self) -> list[Check]:
        return [c for c in self.checks if c.counted]

    @property
    def passed(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == PASS]

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == FAIL]

    @property
    def critical_failures(self) -> list[Check]:
        return [c for c in self.failures if c.critical]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == WARNING]

    @property
    def skipped(self) -> list[Check]:
        return [c for c in self.checks if c.outcome == SKIPPED]

    @property
    def coverage_pct(self) -> float:
        """How much of this dimension actually ran.

        The denominator is every subcomponent the dimension HAS, minus the
        ones deterministically established as not applicable. A skipped check
        stays in the denominator, which is what stops coverage being improved
        by running fewer checks.
        """
        total = len(dm.SUBCOMPONENTS.get(self.dimension, ()))
        excluded = len([c for c in self.checks
                        if c.outcome == NOT_APPLICABLE])
        denominator = max(0, total - excluded)
        return (len(self.counted) / denominator * 100.0) if denominator else 0.0

    @property
    def score(self) -> float | None:
        """Points out of a hundred for this dimension, or None if nothing ran.

        A warning is worth half a pass: it is a real defect and it is not a
        wrong answer, and scoring it as either extreme makes the score
        useless in one direction.
        """
        if not self.counted:
            return None
        earned = len(self.passed) + 0.5 * len(self.warnings)
        return earned / len(self.counted) * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "label": dm.LABELS.get(self.dimension, self.dimension),
            "answers": dm.ANSWERS.get(self.dimension, ""),
            "weight": dm.WEIGHTS.get(self.dimension, 0),
            "score": (round(self.score, 1) if self.score is not None
                      else None),
            "coverage_pct": round(self.coverage_pct, 1),
            "checks_run": len(self.counted),
            "passed": len(self.passed),
            "warnings": len(self.warnings),
            "failed": len(self.failures),
            "skipped": len(self.skipped),
            "critical_failures": [c.subcomponent
                                  for c in self.critical_failures],
            "subcomponents": [c.to_dict() for c in self.checks],
        }


@dataclass
class Record:
    """§180's immutable record. Every field it names."""

    assurance_record_id: str = ""
    tenant_id: str = ""
    user_id: int | None = None
    investigation_id: str = ""
    message_id: str = ""
    answer_id: str = ""
    analysis_run_ids: list[str] = field(default_factory=list)
    trace_id: str = ""
    agentic_run_id: str = ""
    project_id: str = ""
    portfolio_scope: str = ""
    language: str = "en"
    question: str = ""
    answer_type: str = ""
    created_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0

    build_sha: str = ""
    app_version: str = ""
    intelligence_release_id: str = ""
    teaching_release_id: str = ""
    ontology_version: str = ""
    method_versions: dict[str, str] = field(default_factory=dict)
    relationship_versions: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    routing_policy_version: str = ""
    model_roles: dict[str, str] = field(default_factory=dict)
    served_models: dict[str, str] = field(default_factory=dict)
    officer_level: int = 0
    agent_roles: list[str] = field(default_factory=list)
    blueprint_id: str = ""
    retrieved_teaching_case_ids: list[str] = field(default_factory=list)
    objective_coverage: dict[str, Any] = field(default_factory=dict)
    data_versions: dict[str, str] = field(default_factory=dict)
    result_fingerprints: list[str] = field(default_factory=list)

    checks: list[Check] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    repair_count: int = 0
    clarification_count: int = 0
    user_feedback_summary: dict[str, Any] = field(default_factory=dict)
    review_state: str = ""
    stale_reasons: list[str] = field(default_factory=list)
    #: Only where an approved benchmark exists. §184: never combined with
    #: operational assurance and never called accuracy without one.
    reference_match_pct: float | None = None
    reference_source: str = ""
    fingerprint: str = ""

    # ---- rolled up ----------------------------------------------------

    @property
    def stale(self) -> bool:
        return bool(self.stale_reasons)

    def by_dimension(self) -> list[DimensionResult]:
        placed: dict[str, DimensionResult] = {
            d: DimensionResult(dimension=d) for d in dm.DIMENSIONS}
        for check in self.checks:
            if check.dimension:
                placed[check.dimension].checks.append(check)
        return [placed[d] for d in dm.DIMENSIONS]

    @property
    def critical_failures(self) -> list[str]:
        return [c.subcomponent for c in self.checks
                if c.outcome == FAIL and c.critical]

    @property
    def warnings(self) -> list[str]:
        return [c.subcomponent for c in self.checks if c.outcome == WARNING]

    @property
    def skipped_mandatory(self) -> list[str]:
        """Mandatory checks that were skipped, or never recorded at all.

        §183's other half: "a missing check is not silently treated as
        NOT_APPLICABLE". A subcomponent absent from the record is skipped,
        because nothing ran it.
        """
        seen = {c.subcomponent: c for c in self.checks}
        return sorted(
            name for name in dm.MANDATORY
            if name not in seen or seen[name].outcome == SKIPPED)

    @property
    def coverage_pct(self) -> float:
        total = len(dm.all_subcomponents())
        excluded = len([c for c in self.checks
                        if c.outcome == NOT_APPLICABLE])
        denominator = max(0, total - excluded)
        counted = len([c for c in self.checks if c.counted])
        return (counted / denominator * 100.0) if denominator else 0.0

    def weighted_score(self, weights: dm.Weights | None = None
                       ) -> float | None:
        """§182's step 3. Only meaningful after the gates pass.

        Dimensions with nothing measured are excluded from the numerator AND
        the denominator, so a dimension nobody checked neither helps nor
        hurts — it shows as unmeasured, which is what it is.
        """
        policy = weights or dm.Weights()
        earned = 0.0
        available = 0
        for result in self.by_dimension():
            score = result.score
            if score is None:
                continue
            weight = policy.weights[result.dimension]
            earned += score * weight
            available += weight
        return (earned / available) if available else None

    def overall(self, weights: dm.Weights | None = None) -> dict[str, Any]:
        """§182's gates, in §182's order. The score comes last or not at all.

        A record with a failed invariant does not get a score: reporting
        "72/100 (FAILED)" invites somebody to notice the 72.
        """
        policy = weights or dm.Weights()

        # 0. Stale beats everything. It is not a lower grade of assurance; it
        # is a statement about a version that no longer runs.
        if self.stale:
            return _verdict(STALE, None, self.coverage_pct, policy,
                            reasons=self.stale_reasons)

        # 1. Critical gates.
        if self.critical_failures:
            return _verdict(
                FAILED, None, self.coverage_pct, policy,
                reasons=[f"{name} failed" for name in self.critical_failures])

        # 2. Coverage gate.
        coverage = self.coverage_pct
        if coverage < UNVERIFIED_BELOW_PCT:
            return _verdict(
                UNVERIFIED, None, coverage, policy,
                reasons=[f"only {coverage:.0f}% of the checks ran, which is "
                         "not enough to claim anything"])
        missing = self.skipped_mandatory
        if missing or coverage < MIN_COVERAGE_PCT:
            return _verdict(
                NEEDS_REVIEW, None, coverage, policy,
                reasons=([f"{len(missing)} mandatory check(s) did not run: "
                          + ", ".join(missing[:4])] if missing else [])
                + ([f"coverage is {coverage:.0f}%"]
                   if coverage < MIN_COVERAGE_PCT else []))

        # 3. Weighted score, and only now.
        score = self.weighted_score(policy)
        if score is None:
            return _verdict(UNVERIFIED, None, coverage, policy,
                            reasons=["no dimension produced a score"])

        # 4. Limitations. A material limitation caps the status even where the
        # number is high — a correct answer with a stated gap is not the same
        # claim as a correct answer without one.
        if self.limitations or self.warnings:
            return _verdict(VALIDATED_WITH_LIMITATIONS, score, coverage,
                            policy,
                            reasons=(self.limitations[:3] or
                                     [f"{len(self.warnings)} warning(s)"]))
        if score >= HIGH_ASSURANCE_AT and coverage >= 90.0:
            return _verdict(HIGH_ASSURANCE, score, coverage, policy)
        return _verdict(VALIDATED, score, coverage, policy)

    def compute_fingerprint(self) -> str:
        """The record's own hash. §180: immutable.

        A record whose fingerprint does not match its content has been
        edited, and an assurance record that could be revised after the fact
        is a record of what somebody wanted to have happened.
        """
        return fingerprint_of(fingerprint_body(
            answer_id=self.answer_id,
            investigation_id=self.investigation_id,
            question=self.question,
            build_sha=self.build_sha,
            checks=[(c.subcomponent, c.outcome) for c in self.checks],
            limitations=list(self.limitations),
            created_at=self.created_at))

    @property
    def intact(self) -> bool:
        return bool(self.fingerprint) and \
            self.fingerprint == self.compute_fingerprint()

    def to_dict(self, weights: dm.Weights | None = None) -> dict[str, Any]:
        verdict = self.overall(weights)
        return {
            "version": RECORD_VERSION,
            "assurance_record_id": self.assurance_record_id,
            "tenant_id": self.tenant_id, "user_id": self.user_id,
            "investigation_id": self.investigation_id,
            "message_id": self.message_id, "answer_id": self.answer_id,
            "analysis_run_ids": list(self.analysis_run_ids),
            "trace_id": self.trace_id, "agentic_run_id": self.agentic_run_id,
            "project_id": self.project_id,
            "portfolio_scope": self.portfolio_scope,
            "language": self.language, "question": self.question,
            "answer_type": self.answer_type,
            "created_at": self.created_at, "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "build_sha": self.build_sha, "app_version": self.app_version,
            "intelligence_release_id": self.intelligence_release_id,
            "teaching_release_id": self.teaching_release_id,
            "ontology_version": self.ontology_version,
            "method_versions": dict(self.method_versions),
            "relationship_versions": dict(self.relationship_versions),
            "prompt_versions": dict(self.prompt_versions),
            "routing_policy_version": self.routing_policy_version,
            "model_roles": dict(self.model_roles),
            "served_models": dict(self.served_models),
            "officer_level": self.officer_level,
            "agent_roles": list(self.agent_roles),
            "blueprint_id": self.blueprint_id,
            "retrieved_teaching_case_ids": list(
                self.retrieved_teaching_case_ids),
            "objective_coverage": dict(self.objective_coverage),
            "data_versions": dict(self.data_versions),
            "result_fingerprints": list(self.result_fingerprints),
            **verdict,
            "critical_failures": self.critical_failures,
            "warnings": self.warnings,
            "limitations": list(self.limitations),
            "repair_count": self.repair_count,
            "clarification_count": self.clarification_count,
            "user_feedback_summary": dict(self.user_feedback_summary),
            "dimension_results": [d.to_dict() for d in self.by_dimension()],
            "subcomponent_results": [c.to_dict() for c in self.checks],
            "review_state": self.review_state,
            "stale": self.stale, "stale_reasons": list(self.stale_reasons),
            "fingerprint": self.fingerprint,
            "intact": self.intact,
            # §184's separation, on the payload so no reader can combine them.
            "reference_match": reference_block(self.reference_match_pct,
                                          self.reference_source),
        }


def fingerprint_body(*, answer_id: str, investigation_id: str,
                     question: str, build_sha: str,
                     checks: list[tuple[str, str]], limitations: list[str],
                     created_at: str) -> dict[str, Any]:
    """What a record's fingerprint is taken over.

    Module-level so the thing that VERIFIES a record after a round trip
    through the database computes the same hash as the thing that sealed it.
    Two copies of this dictionary would drift, and the first symptom would be
    every stored record reporting itself as tampered with.
    """
    return {
        "answer_id": answer_id,
        "investigation_id": investigation_id,
        "question": question,
        "build_sha": build_sha,
        "checks": sorted(checks),
        "limitations": sorted(limitations),
        "created_at": created_at,
    }


def fingerprint_of(body: dict[str, Any]) -> str:
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def reference_block(pct: float | None, source: str) -> dict[str, Any]:
    """§184's REFERENCE MATCH, kept apart from operational assurance.

    Present only where an approved benchmark exists. Where none does the
    payload says so in words, because a missing key reads as an oversight and
    this is a fact about the question: a live Investigation has no right
    answer to compare against.
    """
    if pct is None:
        return {
            "available": False,
            "value_pct": None,
            "source": "",
            "why": ("This is a live Investigation with no independent "
                    "reference answer, so no accuracy figure can be given. "
                    "The operational assurance above is what the runtime "
                    "could prove, which is a different claim."),
        }
    return {"available": True, "value_pct": round(pct, 2), "source": source,
            "why": ("An approved reference answer exists for this question, "
                    "so the answer could be compared against it.")}


def _verdict(status: str, score: float | None, coverage: float,
             weights: dm.Weights,
             reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "overall_status": status,
        "status_means": MEANS.get(status, ""),
        # §184: never "accuracy". The label is part of the contract.
        "operational_assurance": (round(score, 1) if score is not None
                                  else None),
        "operational_assurance_label": (
            f"Operational assurance: {score:.0f} / 100" if score is not None
            else f"Operational assurance: {status.replace('_', ' ').lower()}"),
        "coverage_pct": round(coverage, 1),
        "weights": weights.to_dict(),
        "reasons": list(reasons or []),
        "scored_on_average": False,
    }


def check(subcomponent: str, outcome: str, *, detail: str = "",
          evidence: list[str] | None = None,
          because: str = "") -> Check:
    """One check, refusing an unreasoned NOT_APPLICABLE.

    §183: applicability must be deterministically established. An unreasoned
    NOT_APPLICABLE removes a check from the denominator, which improves
    coverage by not looking.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"{outcome!r} is not one of §183's five outcomes")
    if outcome == NOT_APPLICABLE and not str(because).strip():
        raise NotEstablished(
            f"{subcomponent} was marked NOT_APPLICABLE with no reason. That "
            "removes it from the coverage denominator, which improves "
            "coverage by not looking.")
    return Check(subcomponent=subcomponent, outcome=outcome, detail=detail,
                 evidence=list(evidence or []),
                 not_applicable_because=because)


def seal(record: Record) -> Record:
    """Stamp the record and freeze it. §180."""
    record.created_at = record.created_at or datetime.now(UTC).isoformat(
        timespec="seconds")
    record.fingerprint = record.compute_fingerprint()
    return record


__all__ = ["ASSURANCE_LABEL", "COUNTED", "Check", "DimensionResult", "FAIL", "FAILED",
           "HIGH_ASSURANCE", "HIGH_ASSURANCE_AT", "MEANS", "MIN_COVERAGE_PCT",
           "NEEDS_REVIEW", "NOT_APPLICABLE", "NotEstablished", "OUTCOMES",
           "PASS", "RECORD_VERSION", "Record", "SKIPPED", "STALE",
           "STATUSES", "UNVERIFIED", "fingerprint_body", "fingerprint_of", "UNVERIFIED_BELOW_PCT", "VALIDATED",
           "VALIDATED_WITH_LIMITATIONS", "WARNING", "check", "seal"]
