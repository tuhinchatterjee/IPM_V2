"""Learning baselines and performance snapshots. §57, §59, §60.

Two immutable records and the windows that compare them.

A BASELINE is the reference point: what this installation was and how it
performed at the moment a Brain was activated or a release went live. §57
lists thirty-odd fields and most of them are versions, because the question a
baseline exists to answer is "compared to WHAT?" and the honest answer names
the ontology version, the prompt versions and the case-set versions rather
than a date.

A SNAPSHOT is a measurement at a moment, against a baseline. §59 requires it
to be immutable, and this module has no update path: a snapshot recomputed
after somebody noticed the number looked wrong is a different snapshot.

The distinction §60 insists on
-------------------------------
**Learning captured during a window is not performance change observed
during a window.** They are different columns here and they are never added.
An installation that captured four hundred observations and improved by
nothing has done something worth knowing, and a screen that showed one
number would report it as progress.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

SNAPSHOT_SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------- §59's triggers

HOURLY = "HOURLY"
DAILY = "DAILY"
WEEKLY = "WEEKLY"
MONTHLY = "MONTHLY"
YEARLY = "YEARLY"
RELEASE = "RELEASE"
BRAIN_IMPORT = "BRAIN_IMPORT"
REGULATORY_RELEASE = "REGULATORY_RELEASE"
MANUAL = "MANUAL"
FEEDBACK_BATCH = "FEEDBACK_BATCH"
MODEL_CHANGE = "MODEL_CHANGE"

TRIGGERS: tuple[str, ...] = (
    HOURLY, DAILY, WEEKLY, MONTHLY, YEARLY, RELEASE, BRAIN_IMPORT,
    REGULATORY_RELEASE, MANUAL, FEEDBACK_BATCH, MODEL_CHANGE,
)

#: Triggers that mark a CHANGE rather than the passage of time. A snapshot
#: taken because something changed is the one worth comparing against; a
#: daily snapshot taken while nothing happened is a data point about noise.
CHANGE_TRIGGERS: frozenset[str] = frozenset({
    RELEASE, BRAIN_IMPORT, REGULATORY_RELEASE, FEEDBACK_BATCH, MODEL_CHANGE,
})


class SnapshotError(Exception):
    """A snapshot or baseline that may not be written."""


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]


# --------------------------------------------------------------- §57


@dataclass
class Baseline:
    """§57's LEARNING BASELINE SNAPSHOT. What we were, and how we did.

    Most of the fields are versions because "compared to what?" is the
    question a baseline answers, and a date is not an answer: two
    installations on the same date can be running different ontologies,
    different prompts and different case sets.

    `sealed_holdout_version` is metadata only, and §57 says so. The version
    identifier says which exam was sat; the questions stay sealed.
    """

    baseline_id: str = ""
    instance_id: str = ""
    tenant: str = ""
    created_at: str = ""
    activated_at: str = ""

    build_sha: str = ""
    app_version: str = ""
    brain_id: str = ""
    brain_version: str = ""
    intelligence_release_id: str = ""
    teaching_release_id: str = ""
    regulatory_release_id: str = ""
    ontology_version: str = ""
    blueprint_version: str = ""
    judgment_policy_version: str = ""
    visualization_grammar_version: str = ""
    routing_policy_version: str = ""
    prompt_versions: dict[str, str] = field(default_factory=dict)
    model_role_configuration: dict[str, str] = field(default_factory=dict)

    development_set_version: str = ""
    validation_set_version: str = ""
    #: Metadata only. §57 and §58 both.
    sealed_holdout_version: str = ""

    development_metrics: dict[str, float] = field(default_factory=dict)
    validation_metrics: dict[str, float] = field(default_factory=dict)
    critical_failure_counts: dict[str, int] = field(default_factory=dict)
    coverage_metrics: dict[str, float] = field(default_factory=dict)
    six_dimension_scores: dict[str, float] = field(default_factory=dict)
    subcomponent_scores: dict[str, float] = field(default_factory=dict)
    case_counts: dict[str, int] = field(default_factory=dict)
    learning_ledger_counts: dict[str, int] = field(default_factory=dict)
    approved_learning_counts: dict[str, int] = field(default_factory=dict)
    known_limitations: tuple[str, ...] = ()
    fingerprint: str = ""

    def __post_init__(self) -> None:
        self.baseline_id = self.baseline_id or f"base_{uuid.uuid4().hex[:16]}"
        self.created_at = self.created_at or datetime.now(UTC).isoformat()
        self.fingerprint = self.fingerprint or _fingerprint({
            "brain": f"{self.brain_id}:{self.brain_version}",
            "releases": [self.intelligence_release_id,
                         self.teaching_release_id,
                         self.regulatory_release_id],
            "versions": [self.ontology_version, self.blueprint_version,
                         self.judgment_policy_version,
                         self.visualization_grammar_version,
                         self.routing_policy_version],
            "sets": [self.development_set_version,
                     self.validation_set_version,
                     self.sealed_holdout_version],
        })

    @property
    def comparable_to(self) -> str:
        """What a comparison against this baseline actually establishes."""
        return (f"ontology {self.ontology_version or '?'}, teaching release "
                f"{self.teaching_release_id or '?'}, development set "
                f"{self.development_set_version or '?'}, validation set "
                f"{self.validation_set_version or '?'}")

    def to_dict(self) -> dict[str, Any]:
        body = {k: (list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}
        body["comparable_to"] = self.comparable_to
        body["sealed_holdout_content_included"] = False
        return body


def validate_baseline(baseline: Baseline) -> list[str]:
    """What is missing from a baseline that would make it useless later."""
    problems: list[str] = []
    if not baseline.instance_id:
        problems.append("a baseline with no instance cannot be compared to "
                        "anything")
    if not baseline.build_sha:
        problems.append("no build. A comparison against an unknown build "
                        "cannot separate 'we improved' from 'we deployed'")
    if not baseline.development_set_version:
        problems.append(
            "no development set version. Comparing scores across two "
            "different case sets and calling the difference improvement is "
            "the oldest way to report one")
    if not baseline.six_dimension_scores:
        problems.append("no dimension scores, so nothing can be compared "
                        "dimension by dimension later")
    return problems


# --------------------------------------------------------------- §59


@dataclass
class Snapshot:
    """§59's LearningPerformanceSnapshot. Immutable, by having no setter.

    Every field §59 names, and the pairs kept as pairs: `development_scores`
    beside `validation_scores`, `critical_failures_dev` beside
    `critical_failures_validation`. A screen that showed one of each pair
    would show the flattering one, because development is always the
    flattering one — it is the set that was tuned against.
    """

    snapshot_id: str = ""
    instance_id: str = ""
    tenant: str = ""
    timestamp: str = ""
    window_start: str = ""
    window_end: str = ""
    trigger: str = MANUAL

    brain_id: str = ""
    brain_version: str = ""
    intelligence_release_id: str = ""
    development_set_version: str = ""
    validation_set_version: str = ""

    development_scores: dict[str, float] = field(default_factory=dict)
    validation_scores: dict[str, float] = field(default_factory=dict)
    six_dimension_scores_dev: dict[str, float] = field(default_factory=dict)
    six_dimension_scores_validation: dict[str, float] = field(
        default_factory=dict)
    subcomponent_scores_dev: dict[str, float] = field(default_factory=dict)
    subcomponent_scores_validation: dict[str, float] = field(
        default_factory=dict)
    critical_failures_dev: int = 0
    critical_failures_validation: int = 0
    coverage_dev: float = 0.0
    coverage_validation: float = 0.0
    accepted_answer_precision_dev: float = 0.0
    accepted_answer_precision_validation: float = 0.0
    abstention_rate_dev: float = 0.0
    abstention_rate_validation: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0
    estimated_cost: float = 0.0

    # §63's quantity half. Never added to the quality half.
    new_learning_captured: int = 0
    new_learning_reviewed: int = 0
    new_learning_approved: int = 0
    new_learning_rejected: int = 0
    new_learning_activated: int = 0
    new_teaching_cases: int = 0
    new_regulatory_items: int = 0
    new_blueprint_changes: int = 0
    new_policy_changes: int = 0
    new_method_changes: int = 0
    new_feedback_regressions: int = 0
    open_learning_items: int = 0

    known_limitations: tuple[str, ...] = ()
    comparison_baseline_id: str = ""
    case_count_dev: int = 0
    case_count_validation: int = 0
    fingerprint: str = ""

    def __post_init__(self) -> None:
        self.snapshot_id = self.snapshot_id or f"snap_{uuid.uuid4().hex[:16]}"
        self.timestamp = self.timestamp or datetime.now(UTC).isoformat()
        self.fingerprint = self.fingerprint or _fingerprint({
            "at": self.timestamp, "trigger": self.trigger,
            "dev": self.development_scores,
            "validation": self.validation_scores,
            "sets": [self.development_set_version,
                     self.validation_set_version],
        })

    @property
    def quantity(self) -> dict[str, int]:
        """§63's LEARNING QUANTITY. What was captured, reviewed, approved."""
        return {
            "new_observations": self.new_learning_captured,
            "new_reviewed_items": self.new_learning_reviewed,
            "new_approved_cases": self.new_learning_approved,
            "new_rejected": self.new_learning_rejected,
            "new_activated": self.new_learning_activated,
            "new_teaching_cases": self.new_teaching_cases,
            "new_regulatory_requirements": self.new_regulatory_items,
            "new_blueprint_changes": self.new_blueprint_changes,
            "new_policy_changes": self.new_policy_changes,
            "new_method_changes": self.new_method_changes,
            "new_feedback_regressions": self.new_feedback_regressions,
            "still_open": self.open_learning_items,
        }

    def to_dict(self) -> dict[str, Any]:
        body = {k: (list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items()}
        body["quantity"] = self.quantity
        body["immutable"] = True
        return body


def validate_snapshot(snapshot: Snapshot) -> list[str]:
    problems: list[str] = []
    if snapshot.trigger not in TRIGGERS:
        problems.append(f"{snapshot.trigger!r} is not one of §59's triggers")
    if not snapshot.comparison_baseline_id:
        problems.append(
            "no baseline. A snapshot compared to nothing is a number, and a "
            "number with no reference point gets compared to whichever "
            "earlier number flatters it")
    if snapshot.validation_scores and not snapshot.validation_set_version:
        problems.append(
            "validation scores with no validation set version. Two runs "
            "against different case sets are not comparable, and nothing "
            "downstream would be able to tell")
    return problems


# ---------------------------------------------------------------- §60


LAST_HOUR = "LAST_HOUR"
LAST_24_HOURS = "LAST_24_HOURS"
LAST_7_DAYS = "LAST_7_DAYS"
LAST_30_DAYS = "LAST_30_DAYS"
THIS_MONTH = "THIS_MONTH"
LAST_3_MONTHS = "LAST_3_MONTHS"
LAST_12_MONTHS = "LAST_12_MONTHS"
SINCE_INSTALLATION = "SINCE_INSTALLATION"
SINCE_CURRENT_BRAIN = "SINCE_CURRENT_BRAIN"
SINCE_CURRENT_RELEASE = "SINCE_CURRENT_INTELLIGENCE_RELEASE"
CUSTOM = "CUSTOM_DATE_RANGE"
YEAR_TO_DATE = "YEAR_TO_DATE"
ALL_TIME = "ALL_TIME"

WINDOWS: tuple[str, ...] = (
    LAST_HOUR, LAST_24_HOURS, LAST_7_DAYS, LAST_30_DAYS, THIS_MONTH,
    LAST_3_MONTHS, LAST_12_MONTHS, SINCE_INSTALLATION, SINCE_CURRENT_BRAIN,
    SINCE_CURRENT_RELEASE, CUSTOM, YEAR_TO_DATE, ALL_TIME,
)

EXPECTED_WINDOWS = 13
if len(WINDOWS) != EXPECTED_WINDOWS:
    raise AssertionError(
        f"§60 names {EXPECTED_WINDOWS} time windows; this module has "
        f"{len(WINDOWS)}.")

#: Windows whose start is an EVENT rather than a duration. These need the
#: event's timestamp supplied; a duration cannot be computed for them, and
#: silently substituting one would answer a different question.
ANCHORED: frozenset[str] = frozenset({
    SINCE_INSTALLATION, SINCE_CURRENT_BRAIN, SINCE_CURRENT_RELEASE, CUSTOM,
})

_DURATIONS: dict[str, timedelta] = {
    LAST_HOUR: timedelta(hours=1),
    LAST_24_HOURS: timedelta(days=1),
    LAST_7_DAYS: timedelta(days=7),
    LAST_30_DAYS: timedelta(days=30),
    LAST_3_MONTHS: timedelta(days=91),
    LAST_12_MONTHS: timedelta(days=365),
}


def window_bounds(window: str, *, now: datetime | None = None,
                  anchor: datetime | None = None,
                  until: datetime | None = None
                  ) -> tuple[datetime | None, datetime]:
    """The start and end of one window. Start is None for ALL_TIME.

    Refuses an anchored window with no anchor rather than defaulting to
    thirty days. "Since the current Brain was activated" and "in the last
    month" are different questions, and answering the second while the
    screen says the first is the kind of wrong nobody catches.
    """
    end = until or now or datetime.now(UTC)
    if window not in WINDOWS:
        raise SnapshotError(f"{window!r} is not one of §60's time windows")
    if window == ALL_TIME:
        return None, end
    if window in _DURATIONS:
        return end - _DURATIONS[window], end
    if window == THIS_MONTH:
        return end.replace(day=1, hour=0, minute=0, second=0,
                           microsecond=0), end
    if window == YEAR_TO_DATE:
        return end.replace(month=1, day=1, hour=0, minute=0, second=0,
                           microsecond=0), end
    if anchor is None:
        raise SnapshotError(
            f"{window} starts at an event, not a duration. Without the "
            "event's timestamp this would silently answer a different "
            "question than the one on the screen")
    return anchor, end


def compare(baseline: Baseline, snapshot: Snapshot, *,
            window: str = SINCE_CURRENT_RELEASE) -> dict[str, Any]:
    """§60's two answers, kept apart.

    LEARNING CAPTURED DURING WINDOW and PERFORMANCE CHANGE OBSERVED DURING
    WINDOW are separate blocks, never summed and never presented as one
    figure. An installation that captured four hundred observations and
    improved by nothing has done something worth knowing, and one number
    would report it as progress.
    """
    dev_delta = _delta(baseline.six_dimension_scores,
                       snapshot.six_dimension_scores_dev)
    val_delta = _delta(
        {k: baseline.validation_metrics.get(k, baseline.six_dimension_scores
                                            .get(k, 0.0))
         for k in snapshot.six_dimension_scores_validation},
        snapshot.six_dimension_scores_validation)

    return {
        "window": window,
        "baseline_id": baseline.baseline_id,
        "snapshot_id": snapshot.snapshot_id,
        "comparable_to": baseline.comparable_to,
        "case_sets_match": (
            baseline.development_set_version
            == snapshot.development_set_version
            and baseline.validation_set_version
            == snapshot.validation_set_version),
        "learning_captured_during_window": snapshot.quantity,
        "performance_change_during_window": {
            "development": dev_delta,
            "validation": val_delta,
            "critical_failures_dev": snapshot.critical_failures_dev,
            "critical_failures_validation":
                snapshot.critical_failures_validation,
            "coverage_dev": round(snapshot.coverage_dev, 4),
            "coverage_validation": round(snapshot.coverage_validation, 4),
        },
        "these_are_not_the_same_thing": (
            "Learning captured is what went in. Performance change is what "
            "came out. They are reported separately and never added: an "
            "installation that captured four hundred observations and "
            "improved by nothing has done something worth knowing, and one "
            "number would report it as progress."
        ),
    }


def _delta(before: dict[str, float],
           after: dict[str, float]) -> list[dict[str, Any]]:
    """Percentage-point change per dimension, including the unchanged ones.

    A dimension omitted because it did not move would read as a dimension
    that was not measured, and the two mean opposite things.
    """
    names = sorted(set(before) | set(after))
    return [{
        "dimension": name,
        "before": round(before.get(name, 0.0), 4),
        "after": round(after.get(name, 0.0), 4),
        "points": round((after.get(name, 0.0) - before.get(name, 0.0)) * 100,
                        2),
        "measured": name in after,
    } for name in names]
