"""
Validation policy, limits and the governed opinion. §48-§50, §79-§81.

Three things live here, and they are deliberately separate: what a limit
*is*, what a finding *is*, and how an overall opinion is *derived*. Keeping
them apart is what stops the opinion becoming a number somebody tuned.

The rule that matters most
---------------------------
§50: "No approved limit → NO APPROVED LIMIT, not PASS."

A metric with no limit behind it has not passed anything. Reporting it green
is the most common way a validation dashboard tells a committee that
something was checked when nothing was. `Assessment.status` has a distinct
value for it and the colour is never the pass colour.

Every limit carries where it came from
----------------------------------------
§50's five provenances. A number seeded for a demonstration and a number
from a regulator's text are both limits and are not the same kind of thing,
and a validator has to be able to tell which is which at a glance. Every
limit here is DEMO_POLICY, because that is what it is: §26 and §80 say seed
demonstration policy only, and no conventional PSI cut-off is presented as a
regulatory requirement.

The opinion is derived, not chosen
------------------------------------
§49's five opinions come out of a policy function over the findings and the
gates. The LLM explains the result; it does not pick it. An opinion a model
could choose is an opinion that moves when the prompt does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

POLICY_VERSION = "1.0.0"

# ------------------------------------------------------------ §50 provenance

INSTITUTION_POLICY = "INSTITUTION POLICY"
REGULATORY_REQUIREMENT = "REGULATORY REQUIREMENT"
DEVELOPMENT_STANDARD = "MODEL DEVELOPMENT STANDARD"
DEMO_POLICY = "SEEDED POLICY"
USER_APPROVED = "USER-APPROVED VALIDATION POLICY"

PROVENANCES: tuple[str, ...] = (INSTITUTION_POLICY, REGULATORY_REQUIREMENT,
                                DEVELOPMENT_STANDARD, DEMO_POLICY,
                                USER_APPROVED)

# ------------------------------------------------------------ §81 statuses

PASS = "PASS"
WATCH = "WATCH"
BREACH = "BREACH"
NO_LIMIT = "NO APPROVED LIMIT"
NOT_MEASURED = "NOT MEASURED"

STATUSES: tuple[str, ...] = (PASS, WATCH, BREACH, NO_LIMIT, NOT_MEASURED)

#: Which comparison a limit makes.
AT_LEAST = "AT_LEAST"
AT_MOST = "AT_MOST"
WITHIN = "WITHIN"
DIRECTIONS: tuple[str, ...] = (AT_LEAST, AT_MOST, WITHIN)


class PolicyError(Exception):
    """A limit or finding that may not be recorded as asked."""


@dataclass(frozen=True)
class Limit:
    """One threshold, and where it came from."""

    metric: str
    label: str
    direction: str
    #: The value at which the metric stops being acceptable.
    breach_at: float
    #: The value at which it stops being comfortable. Optional.
    watch_at: float | None = None
    provenance: str = DEMO_POLICY
    source: str = ""
    note: str = ""

    def assess(self, observed: float | None) -> str:
        if observed is None:
            return NOT_MEASURED
        if self.direction == AT_LEAST:
            if observed < self.breach_at:
                return BREACH
            if self.watch_at is not None and observed < self.watch_at:
                return WATCH
            return PASS
        if self.direction == AT_MOST:
            if observed > self.breach_at:
                return BREACH
            if self.watch_at is not None and observed > self.watch_at:
                return WATCH
            return PASS
        # WITHIN: the limit is an absolute tolerance around zero.
        magnitude = abs(observed)
        if magnitude > self.breach_at:
            return BREACH
        if self.watch_at is not None and magnitude > self.watch_at:
            return WATCH
        return PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric, "label": self.label,
            "direction": self.direction, "breach_at": self.breach_at,
            "watch_at": self.watch_at, "provenance": self.provenance,
            "source": self.source, "note": self.note,
        }


#: §80's configurable policy, seeded as DEMO POLICY only.
#:
#: Every number below is a demonstration default. None of them is a
#: regulatory threshold and none is presented as one. The conventional PSI
#: cut-offs in particular are scorecard practice: §26 explicitly says not to
#: hard-code them as universal regulatory requirements, and the provenance
#: field is how that instruction is honoured rather than remembered.
DEMO_LIMITS: tuple[Limit, ...] = (
    Limit("gini", "Gini / Accuracy Ratio", AT_LEAST, 0.25, 0.35,
          note="A retail scorecard below 0.25 Gini has lost most of its "
               "rank ordering. Set by the institution in production."),
    Limit("auc", "AUC", AT_LEAST, 0.625, 0.675,
          note="The Gini limit expressed as an area."),
    Limit("ks", "KS", AT_LEAST, 0.20, 0.28),
    Limit("gini_deterioration", "Gini deterioration vs development",
          AT_MOST, 0.10, 0.05,
          note="Absolute drop from the development Gini."),
    Limit("score_psi", "Score PSI", AT_MOST, 0.25, 0.10,
          note='The 0.10 and 0.25 cut-offs are a scorecard convention, not a '
               'regulatory threshold. Seeded here as synthetic policy so the '
               'dashboard has something to compare against.'),
    Limit("variable_csi", "Variable CSI", AT_MOST, 0.25, 0.10,
          note="Same convention as PSI, applied per active variable."),
    Limit("calibration_in_the_large", "Calibration in the large", WITHIN,
          0.35, 0.20,
          note="Log-odds gap between observed and predicted. Zero means "
               "the level is right."),
    Limit("bucket_rmse", "Calibration RMSE by band", AT_MOST, 0.02, 0.01),
    Limit("brier_score", "Brier score", AT_MOST, 0.10, 0.07),
    Limit("missing_rate", "Missingness on an active variable", AT_MOST,
          0.20, 0.10),
    Limit("special_bin_rate", "Special-bin usage", AT_MOST, 0.25, 0.15,
          note="MISSING plus UNSEEN. Growth here means the approved binning "
               "is covering less of the population than it was fitted on."),
    Limit("implementation_mismatch_rate", "Implementation mismatch rate",
          AT_MOST, 0.0, None,
          note="Zero tolerance. A stored score that does not match its own "
               "equation is not the model that was approved."),
    Limit("minimum_defaults", "Defaults in the validation sample", AT_LEAST,
          30, 100,
          note="Below thirty events a discrimination statistic is "
               "arithmetic rather than evidence."),
    Limit("minimum_observations", "Observations in the validation sample",
          AT_LEAST, 500, 2_000),
    Limit("override_rate", "Override rate", AT_MOST, 0.20, 0.10,
          note="Applies only where decision data exists."),
)

LIMITS_BY_METRIC: dict[str, Limit] = {limit.metric: limit
                                      for limit in DEMO_LIMITS}


@dataclass
class Assessment:
    """One metric, its limit, and what that comparison says."""

    metric: str
    label: str
    observed: float | None
    limit: Limit | None
    status: str
    evidence: str = ""

    @property
    def breached(self) -> bool:
        return self.status == BREACH

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "label": self.label,
            "observed": (None if self.observed is None
                         else round(float(self.observed), 6)),
            "limit": self.limit.to_dict() if self.limit else None,
            "limit_value": self.limit.breach_at if self.limit else None,
            "status": self.status,
            "source": self.limit.provenance if self.limit else None,
            "evidence": self.evidence,
            "why": self._why(),
        }

    def _why(self) -> str:
        if self.status == NO_LIMIT:
            return (
                "No approved limit exists for this metric, so it has not "
                "passed anything. §50: a metric with nothing to compare "
                "against is reported as having no limit, never as a pass.")
        if self.status == NOT_MEASURED:
            return "This metric was not measured on this sample."
        if self.limit is None:
            return ""
        return (f"{self.label} is {self.observed:,.4f} against a "
                f"{self.limit.direction.replace('_', ' ').lower()} limit of "
                f"{self.limit.breach_at:,.4f} "
                f"({self.limit.provenance}).")


def assess(metric: str, observed: float | None, *,
           limits: dict[str, Limit] | None = None,
           label: str = "", evidence: str = "") -> Assessment:
    """Compare one observed value against its approved limit, or say there
    is none.

    §50's rule, implemented once. Everything that shows a status goes
    through here, so there is no second path where a missing limit becomes
    a green tick.
    """
    catalogue = limits if limits is not None else LIMITS_BY_METRIC
    limit = catalogue.get(metric)
    if limit is None:
        return Assessment(metric=metric, label=label or metric,
                          observed=observed, limit=None, status=NO_LIMIT,
                          evidence=evidence)
    return Assessment(metric=metric, label=label or limit.label,
                      observed=observed, limit=limit,
                      status=limit.assess(observed), evidence=evidence)


# ------------------------------------------------------------ §48 findings

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
OBSERVATION = "OBSERVATION"
SEVERITIES: tuple[str, ...] = (HIGH, MEDIUM, LOW, OBSERVATION)

#: §48's categories, mapped to the report section each belongs in.
CATEGORIES: dict[str, str] = {
    "DATA_QUALITY": "8.1 Data and sample diagnostics",
    "DISCRIMINATION": "8.2 Discriminatory power",
    "CALIBRATION": "8.3 Calibration and accuracy",
    "STABILITY": "8.4 Stability and robustness",
    "VARIABLE_DIAGNOSTICS": "8.5 Sensitivity and variable diagnostics",
    "SEGMENT_PERFORMANCE": "8.6 Segment performance",
    "CUTOFF": "8.7 Cut-off and decision performance",
    "OVERRIDES": "8.8 Overrides and usage",
    "CHALLENGER": "8.9 Challenger comparison",
    "IMPLEMENTATION": "7 Implementation verification",
    "MODEL_DESIGN": "6 Model design and conceptual soundness",
    "GOVERNANCE": "4 Governance and independence",
    "MONITORING": "9 Monitoring review",
}

OPEN = "OPEN"
IN_REMEDIATION = "IN REMEDIATION"
AWAITING_APPROVAL = "AWAITING APPROVAL"
CLOSED = "CLOSED"
ACCEPTED = "RISK ACCEPTED"
FINDING_STATUSES: tuple[str, ...] = (OPEN, IN_REMEDIATION,
                                     AWAITING_APPROVAL, CLOSED, ACCEPTED)


@dataclass
class Finding:
    """§48. One governed finding, with the evidence that produced it."""

    finding_id: str
    model_id: str
    model_version: str
    period: str
    category: str
    title: str
    description: str
    severity: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    analysis_run_ids: list[str] = field(default_factory=list)
    metric: str = ""
    observed: float | None = None
    limit_value: float | None = None
    limit_source: str = ""
    breach: bool = False
    impact: str = ""
    recommendation: str = ""
    owner: str = ""
    status: str = OPEN
    due_date: str = ""
    regulatory_references: list[str] = field(default_factory=list)
    raised_by: str = ""
    raised_at: str = ""
    comments: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise PolicyError(
                f"{self.severity!r} is not a severity; expected one of "
                f"{', '.join(SEVERITIES)}")
        if self.category not in CATEGORIES:
            raise PolicyError(
                f"{self.category!r} is not a finding category. A finding "
                "with no category has no section in the validation report "
                "and would be silently dropped from it.")
        if not self.evidence and self.severity in (HIGH, MEDIUM):
            raise PolicyError(
                f"a {self.severity} finding needs evidence. §48: findings "
                "carry the analysis that produced them, and one that cannot "
                "point at a number is an opinion the model owner has no way "
                "to answer.")
        self.raised_at = self.raised_at or datetime.now(UTC).isoformat()

    @property
    def report_section(self) -> str:
        return CATEGORIES[self.category]

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "period": self.period,
            "category": self.category,
            "report_section": self.report_section,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "evidence": list(self.evidence),
            "analysis_run_ids": list(self.analysis_run_ids),
            "metric": self.metric,
            "observed": self.observed,
            "limit_value": self.limit_value,
            "limit_source": self.limit_source,
            "breach": self.breach,
            "impact": self.impact,
            "recommendation": self.recommendation,
            "owner": self.owner,
            "status": self.status,
            "due_date": self.due_date,
            "regulatory_references": list(self.regulatory_references),
            "raised_by": self.raised_by,
            "raised_at": self.raised_at,
            "comments": list(self.comments),
        }


def finding_from(assessment: Assessment, *, finding_id: str, model_id: str,
                 model_version: str, period: str, category: str,
                 title: str, description: str, impact: str = "",
                 recommendation: str = "", raised_by: str = "",
                 regulatory_references: list[str] | None = None) -> Finding:
    """Raise a finding from a breached limit, carrying its numbers along."""
    severity = {BREACH: HIGH, WATCH: MEDIUM}.get(assessment.status,
                                                 OBSERVATION)
    return Finding(
        finding_id=finding_id, model_id=model_id,
        model_version=model_version, period=period, category=category,
        title=title, description=description, severity=severity,
        evidence=[assessment.to_dict()],
        metric=assessment.metric, observed=assessment.observed,
        limit_value=(assessment.limit.breach_at if assessment.limit
                     else None),
        limit_source=(assessment.limit.provenance if assessment.limit
                      else ""),
        breach=assessment.breached, impact=impact,
        recommendation=recommendation, raised_by=raised_by,
        regulatory_references=list(regulatory_references or ()))


# --------------------------------------------------------- §49 the opinion

SATISFACTORY = "SATISFACTORY"
SATISFACTORY_WITH_OBSERVATIONS = "SATISFACTORY WITH OBSERVATIONS"
REQUIRES_REMEDIATION = "REQUIRES REMEDIATION"
MATERIAL_DEFICIENCIES = "MATERIAL DEFICIENCIES"
INCOMPLETE = "INCOMPLETE VALIDATION"

OPINIONS: tuple[str, ...] = (SATISFACTORY, SATISFACTORY_WITH_OBSERVATIONS,
                             REQUIRES_REMEDIATION, MATERIAL_DEFICIENCIES,
                             INCOMPLETE)


@dataclass
class Opinion:
    """§49. The derived opinion, and the reasoning that produced it."""

    opinion: str
    because: list[str] = field(default_factory=list)
    high_findings: int = 0
    medium_findings: int = 0
    low_findings: int = 0
    observations: int = 0
    breached_metrics: list[str] = field(default_factory=list)
    unmeasured: list[str] = field(default_factory=list)
    no_limit: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": POLICY_VERSION,
            "opinion": self.opinion,
            "because": list(self.because),
            "findings": {
                "high": self.high_findings, "medium": self.medium_findings,
                "low": self.low_findings, "observations": self.observations,
            },
            "breached_metrics": list(self.breached_metrics),
            "metrics_not_measured": list(self.unmeasured),
            "metrics_with_no_approved_limit": list(self.no_limit),
            "how_this_was_decided": (
                "Derived by policy from the findings and the gates below, "
                "not chosen. The explanation of this result is written by "
                "the model; the result itself is not — an opinion a model "
                "could choose is one that moves when the prompt does."),
            "not_a_certification": (
                "This is a CBUAE MMS/MMG-aligned validation opinion produced "
                "by CreditProbe's governed policy. It is not regulatory "
                "certification and it is not a legal compliance opinion."),
        }


#: Which metrics have to be measured before an opinion can be more than
#: INCOMPLETE. Missing any one of them means the validation did not cover
#: what a validation covers.
REQUIRED_COVERAGE: tuple[str, ...] = (
    "gini", "calibration_in_the_large", "score_psi",
    "implementation_mismatch_rate", "minimum_defaults",
)


def opine(assessments: list[Assessment], findings: list[Finding], *,
          sample_sufficient: bool = True) -> Opinion:
    """§49. Derive the overall opinion from the evidence.

    The order of the checks is the argument. Incompleteness comes first —
    a validation that did not measure discrimination cannot conclude
    anything about it, and grading it SATISFACTORY because nothing failed
    would be reporting an absence as a pass.
    """
    by_metric = {a.metric: a for a in assessments}
    breached = sorted(a.metric for a in assessments if a.breached)
    unmeasured = sorted(a.metric for a in assessments
                        if a.status == NOT_MEASURED)
    no_limit = sorted(a.metric for a in assessments if a.status == NO_LIMIT)

    high = sum(1 for f in findings if f.severity == HIGH)
    medium = sum(1 for f in findings if f.severity == MEDIUM)
    low = sum(1 for f in findings if f.severity == LOW)
    observations = sum(1 for f in findings if f.severity == OBSERVATION)

    result = Opinion(opinion=SATISFACTORY, high_findings=high,
                     medium_findings=medium, low_findings=low,
                     observations=observations, breached_metrics=breached,
                     unmeasured=unmeasured, no_limit=no_limit)

    missing = [m for m in REQUIRED_COVERAGE
               if m not in by_metric or by_metric[m].status == NOT_MEASURED]
    if missing or not sample_sufficient:
        result.opinion = INCOMPLETE
        if missing:
            result.because.append(
                "The validation did not measure: " + ", ".join(missing)
                + ". A validation that did not measure discrimination, "
                  "calibration, stability or implementation cannot conclude "
                  "anything about them, and grading it satisfactory because "
                  "nothing failed would report an absence as a pass.")
        if not sample_sufficient:
            result.because.append(
                "The validation sample is below the approved minimum for "
                "defaults or observations, so the statistics on it are "
                "arithmetic rather than evidence.")
        return result

    implementation = by_metric.get("implementation_mismatch_rate")
    if implementation is not None and implementation.breached:
        result.opinion = MATERIAL_DEFICIENCIES
        result.because.append(
            "The stored scores could not be reproduced from the approved "
            "equation. Whatever the discrimination looks like, the model in "
            "production is not the model that was approved.")
        return result

    # A breach and the finding it raised are one fact, not two. Counting
    # them separately made a single breached limit land at MATERIAL
    # DEFICIENCIES, which collapsed a five-level scale to two. Material
    # deficiencies mean several things are wrong at once.
    if high >= 2 or (high and len(breached) >= 2):
        result.opinion = MATERIAL_DEFICIENCIES
        result.because.append(
            f"{high} high-severity finding(s) across {len(breached)} "
            "breached limit(s). Several dimensions are outside their "
            "approved limits at once, so the model is not suitable for its "
            "intended use without remediation.")
        return result

    if high or len(breached) >= 2:
        result.opinion = REQUIRES_REMEDIATION
        result.because.append(
            f"{high} high-severity finding(s) and {len(breached)} breached "
            f"limit(s): {', '.join(breached) or 'none'}.")
        return result

    if breached or medium:
        result.opinion = REQUIRES_REMEDIATION if breached else \
            SATISFACTORY_WITH_OBSERVATIONS
        result.because.append(
            f"{len(breached)} breached limit(s) and {medium} "
            "medium-severity finding(s).")
        if no_limit:
            result.because.append(
                f"{len(no_limit)} metric(s) have no approved limit and are "
                "reported as such rather than as passes.")
        return result

    if low or observations or no_limit:
        result.opinion = SATISFACTORY_WITH_OBSERVATIONS
        result.because.append(
            f"No limits breached. {low} low-severity finding(s) and "
            f"{observations} observation(s) remain open.")
        if no_limit:
            result.because.append(
                f"{len(no_limit)} metric(s) have no approved limit: "
                + ", ".join(no_limit)
                + ". These have not passed anything.")
        return result

    result.because.append(
        "Every measured metric is within its approved limit and no findings "
        "are open.")
    return result


def catalogue() -> dict[str, Any]:
    """The policy, for a screen that has to show what it is comparing to."""
    return {
        "policy_version": POLICY_VERSION,
        "provenances": list(PROVENANCES),
        "statuses": list(STATUSES),
        "severities": list(SEVERITIES),
        "opinions": list(OPINIONS),
        "categories": dict(CATEGORIES),
        "finding_statuses": list(FINDING_STATUSES),
        "limits": [limit.to_dict() for limit in DEMO_LIMITS],
        "every_limit_here_is_demo_policy": all(
            limit.provenance == DEMO_POLICY for limit in DEMO_LIMITS),
        "why": (
            '§80 and §26: seed synthetic policy only. None of these numbers is '
            'a regulatory threshold and none is presented as one. The '
            'conventional PSI and CSI cut-offs in particular are scorecard '
            'practice, and the provenance field is how that is enforced rather '
            'than remembered.'),
    }
