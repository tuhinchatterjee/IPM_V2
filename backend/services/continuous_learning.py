"""Continuous Learning, over the database. §56-§93.

The three things §56 separates, kept separate here.

**Capture is continuous.** Counting what arrived costs nothing and this
service reads it freely.

**Activation is governed.** There is no function in this file that activates
anything. Snapshots record; releases activate, and they live elsewhere.

**Measurement is continuous and versioned.** Every figure is attached to a
baseline and a case-set version, and a comparison across two different case
sets is reported as not comparable rather than as a difference.

What this service will not do
------------------------------
It will not put a sealed-holdout question anywhere. §58 names the
continuous-learning UI among the six places holdout content may never reach,
and `cockpit()` carries a version identifier and aggregate certified scores
and nothing else from that partition.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.continuous import measurement as ms
from backend.continuous import partitions as pt
from backend.continuous import questions as qs
from backend.continuous import snapshots as sn
from backend.models.platform import (
    EvaluationUse,
    LearningBaseline,
    LearningSnapshot,
)

logger = logging.getLogger(__name__)


class ContinuousLearningError(Exception):
    """A measurement that may not be recorded, and why."""


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ §57


def record_baseline(session: Session, baseline: sn.Baseline, *,
                    tenant: str = "") -> LearningBaseline:
    """Write a baseline. Append-only, and refuses one that cannot be used.

    A baseline missing its case-set version passes today and produces an
    unanswerable question in six months: two scores over two different case
    sets, with the difference presented as improvement.
    """
    problems = sn.validate_baseline(baseline)
    if problems:
        raise ContinuousLearningError(
            "this baseline may not be recorded: " + "; ".join(problems))
    row = LearningBaseline(
        baseline_id=baseline.baseline_id,
        instance_id=baseline.instance_id,
        tenant=tenant or baseline.tenant,
        build_sha=baseline.build_sha,
        app_version=baseline.app_version,
        brain_id=baseline.brain_id,
        brain_version=baseline.brain_version,
        intelligence_release_id=baseline.intelligence_release_id,
        teaching_release_id=baseline.teaching_release_id,
        regulatory_release_id=baseline.regulatory_release_id,
        ontology_version=baseline.ontology_version,
        blueprint_version=baseline.blueprint_version,
        judgment_policy_version=baseline.judgment_policy_version,
        visualization_grammar_version=(
            baseline.visualization_grammar_version),
        routing_policy_version=baseline.routing_policy_version,
        prompt_versions=dict(baseline.prompt_versions),
        model_role_configuration=dict(baseline.model_role_configuration),
        development_set_version=baseline.development_set_version,
        validation_set_version=baseline.validation_set_version,
        sealed_holdout_version=baseline.sealed_holdout_version,
        development_metrics=dict(baseline.development_metrics),
        validation_metrics=dict(baseline.validation_metrics),
        critical_failure_counts=dict(baseline.critical_failure_counts),
        coverage_metrics=dict(baseline.coverage_metrics),
        six_dimension_scores=dict(baseline.six_dimension_scores),
        subcomponent_scores=dict(baseline.subcomponent_scores),
        case_counts=dict(baseline.case_counts),
        learning_ledger_counts=dict(baseline.learning_ledger_counts),
        approved_learning_counts=dict(baseline.approved_learning_counts),
        known_limitations=list(baseline.known_limitations),
        fingerprint=baseline.fingerprint,
    )
    session.add(row)
    session.flush()
    return row


def _baseline_from(row: LearningBaseline) -> sn.Baseline:
    return sn.Baseline(
        baseline_id=row.baseline_id, instance_id=row.instance_id,
        tenant=row.tenant, build_sha=row.build_sha,
        app_version=row.app_version, brain_id=row.brain_id,
        brain_version=row.brain_version,
        intelligence_release_id=row.intelligence_release_id,
        teaching_release_id=row.teaching_release_id,
        regulatory_release_id=row.regulatory_release_id,
        ontology_version=row.ontology_version,
        blueprint_version=row.blueprint_version,
        judgment_policy_version=row.judgment_policy_version,
        visualization_grammar_version=row.visualization_grammar_version,
        routing_policy_version=row.routing_policy_version,
        prompt_versions=dict(row.prompt_versions or {}),
        model_role_configuration=dict(row.model_role_configuration or {}),
        development_set_version=row.development_set_version,
        validation_set_version=row.validation_set_version,
        sealed_holdout_version=row.sealed_holdout_version,
        development_metrics=dict(row.development_metrics or {}),
        validation_metrics=dict(row.validation_metrics or {}),
        critical_failure_counts=dict(row.critical_failure_counts or {}),
        coverage_metrics=dict(row.coverage_metrics or {}),
        six_dimension_scores=dict(row.six_dimension_scores or {}),
        subcomponent_scores=dict(row.subcomponent_scores or {}),
        case_counts=dict(row.case_counts or {}),
        learning_ledger_counts=dict(row.learning_ledger_counts or {}),
        approved_learning_counts=dict(row.approved_learning_counts or {}),
        known_limitations=tuple(row.known_limitations or ()),
        fingerprint=row.fingerprint,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def current_baseline(session: Session, *,
                     tenant: str = "") -> LearningBaseline | None:
    return session.execute(
        select(LearningBaseline).where(
            LearningBaseline.tenant == tenant).order_by(
            LearningBaseline.created_at.desc()).limit(1)).scalar_one_or_none()


# ------------------------------------------------------------------ §59


def record_snapshot(session: Session, snapshot: sn.Snapshot, *,
                    tenant: str = "") -> LearningSnapshot:
    """Write a snapshot. Immutable: this is the only path, and it inserts."""
    problems = sn.validate_snapshot(snapshot)
    if problems:
        raise ContinuousLearningError(
            "this snapshot may not be recorded: " + "; ".join(problems))
    row = LearningSnapshot(
        snapshot_id=snapshot.snapshot_id,
        instance_id=snapshot.instance_id,
        tenant=tenant or snapshot.tenant,
        trigger=snapshot.trigger,
        brain_id=snapshot.brain_id,
        brain_version=snapshot.brain_version,
        intelligence_release_id=snapshot.intelligence_release_id,
        development_set_version=snapshot.development_set_version,
        validation_set_version=snapshot.validation_set_version,
        development_scores=dict(snapshot.development_scores),
        validation_scores=dict(snapshot.validation_scores),
        six_dimension_scores_dev=dict(snapshot.six_dimension_scores_dev),
        six_dimension_scores_validation=dict(
            snapshot.six_dimension_scores_validation),
        subcomponent_scores_dev=dict(snapshot.subcomponent_scores_dev),
        subcomponent_scores_validation=dict(
            snapshot.subcomponent_scores_validation),
        critical_failures_dev=snapshot.critical_failures_dev,
        critical_failures_validation=snapshot.critical_failures_validation,
        coverage_dev=snapshot.coverage_dev,
        coverage_validation=snapshot.coverage_validation,
        accepted_answer_precision_dev=snapshot.accepted_answer_precision_dev,
        accepted_answer_precision_validation=(
            snapshot.accepted_answer_precision_validation),
        abstention_rate_dev=snapshot.abstention_rate_dev,
        abstention_rate_validation=snapshot.abstention_rate_validation,
        case_count_dev=snapshot.case_count_dev,
        case_count_validation=snapshot.case_count_validation,
        latency_ms=snapshot.latency_ms,
        tokens=snapshot.tokens,
        estimated_cost=snapshot.estimated_cost,
        new_learning_captured=snapshot.new_learning_captured,
        new_learning_reviewed=snapshot.new_learning_reviewed,
        new_learning_approved=snapshot.new_learning_approved,
        new_learning_rejected=snapshot.new_learning_rejected,
        new_learning_activated=snapshot.new_learning_activated,
        new_teaching_cases=snapshot.new_teaching_cases,
        new_regulatory_items=snapshot.new_regulatory_items,
        new_blueprint_changes=snapshot.new_blueprint_changes,
        new_policy_changes=snapshot.new_policy_changes,
        new_method_changes=snapshot.new_method_changes,
        new_feedback_regressions=snapshot.new_feedback_regressions,
        open_learning_items=snapshot.open_learning_items,
        known_limitations=list(snapshot.known_limitations),
        comparison_baseline_id=snapshot.comparison_baseline_id,
        fingerprint=snapshot.fingerprint,
    )
    session.add(row)
    _record_uses(session, snapshot, tenant=tenant)
    session.flush()
    return row


def _record_uses(session: Session, snapshot: sn.Snapshot, *,
                 tenant: str) -> None:
    """§72. Note which partitions this snapshot actually consulted."""
    if snapshot.six_dimension_scores_dev:
        session.add(EvaluationUse(
            partition=pt.DEVELOPMENT, purpose=snapshot.trigger,
            snapshot_id=snapshot.snapshot_id,
            case_count=snapshot.case_count_dev, tenant=tenant))
    if snapshot.six_dimension_scores_validation:
        session.add(EvaluationUse(
            partition=pt.VALIDATION, purpose=snapshot.trigger,
            snapshot_id=snapshot.snapshot_id,
            case_count=snapshot.case_count_validation, tenant=tenant))


def _snapshot_from(row: LearningSnapshot) -> sn.Snapshot:
    return sn.Snapshot(
        snapshot_id=row.snapshot_id, instance_id=row.instance_id,
        tenant=row.tenant, trigger=row.trigger, brain_id=row.brain_id,
        brain_version=row.brain_version,
        intelligence_release_id=row.intelligence_release_id,
        development_set_version=row.development_set_version,
        validation_set_version=row.validation_set_version,
        development_scores=dict(row.development_scores or {}),
        validation_scores=dict(row.validation_scores or {}),
        six_dimension_scores_dev=dict(row.six_dimension_scores_dev or {}),
        six_dimension_scores_validation=dict(
            row.six_dimension_scores_validation or {}),
        subcomponent_scores_dev=dict(row.subcomponent_scores_dev or {}),
        subcomponent_scores_validation=dict(
            row.subcomponent_scores_validation or {}),
        critical_failures_dev=row.critical_failures_dev,
        critical_failures_validation=row.critical_failures_validation,
        coverage_dev=row.coverage_dev,
        coverage_validation=row.coverage_validation,
        accepted_answer_precision_dev=row.accepted_answer_precision_dev,
        accepted_answer_precision_validation=(
            row.accepted_answer_precision_validation),
        abstention_rate_dev=row.abstention_rate_dev,
        abstention_rate_validation=row.abstention_rate_validation,
        case_count_dev=row.case_count_dev,
        case_count_validation=row.case_count_validation,
        latency_ms=row.latency_ms, tokens=row.tokens,
        estimated_cost=row.estimated_cost,
        new_learning_captured=row.new_learning_captured,
        new_learning_reviewed=row.new_learning_reviewed,
        new_learning_approved=row.new_learning_approved,
        new_learning_rejected=row.new_learning_rejected,
        new_learning_activated=row.new_learning_activated,
        new_teaching_cases=row.new_teaching_cases,
        new_regulatory_items=row.new_regulatory_items,
        new_blueprint_changes=row.new_blueprint_changes,
        new_policy_changes=row.new_policy_changes,
        new_method_changes=row.new_method_changes,
        new_feedback_regressions=row.new_feedback_regressions,
        open_learning_items=row.open_learning_items,
        known_limitations=tuple(row.known_limitations or ()),
        comparison_baseline_id=row.comparison_baseline_id,
        fingerprint=row.fingerprint,
        timestamp=row.created_at.isoformat() if row.created_at else "",
    )


def snapshots_in(session: Session, *, tenant: str = "",
                 window: str = sn.LAST_30_DAYS,
                 anchor: datetime | None = None) -> list[LearningSnapshot]:
    start, end = sn.window_bounds(window, anchor=anchor)
    query = select(LearningSnapshot).where(LearningSnapshot.tenant == tenant)
    if start is not None:
        query = query.where(LearningSnapshot.created_at >= start)
    return list(session.execute(
        query.where(LearningSnapshot.created_at <= end).order_by(
            LearningSnapshot.created_at)).scalars().all())


# ------------------------------------------------------------------ §64


#: The six Intelligence Dimensions, in the order §62 lists them.
DIMENSIONS: tuple[str, ...] = (
    "Understanding & Context", "Analytical Design", "Computation & Evidence",
    "Judgment & Presentation", "Agentic Delivery", "Reliability & Experience",
)


def cockpit(session: Session, *, tenant: str = "",
            window: str = sn.SINCE_CURRENT_RELEASE,
            anchor: datetime | None = None) -> dict[str, Any]:
    """§64's Continuous Learning cockpit.

    What has been learned since a chosen baseline, and — separately, and
    never added to it — what measurably changed. The two blocks are the
    screen's whole argument: an installation that captured four hundred
    observations and improved by nothing has done something worth knowing,
    and one number would report it as progress.
    """
    baseline_row = current_baseline(session, tenant=tenant)
    if baseline_row is None:
        return _no_baseline(window)

    baseline = _baseline_from(baseline_row)
    rows = snapshots_in(session, tenant=tenant, window=window,
                        anchor=anchor or baseline_row.created_at)
    if not rows:
        return _no_snapshots(baseline, window)

    latest = _snapshot_from(rows[-1])
    dimensions = _dimension_results(baseline, latest)
    quantity = _sum_quantity(rows)

    verdict = ms.quality_verdict(quantity=quantity, dimensions=dimensions)
    drift = ms.overfitting(dimensions)
    ok, why = ms.may_activate(dimensions)

    return {
        "baseline": {
            "baseline_id": baseline.baseline_id,
            "comparable_to": baseline.comparable_to,
            "brain": f"{baseline.brain_id} {baseline.brain_version}".strip(),
            "created_at": baseline.created_at,
        },
        "window": window,
        "windows_available": list(sn.WINDOWS),
        "headline": verdict["headline"],
        "learning_captured": verdict["learning_quantity"],
        "measured_change": verdict["learning_quality"],
        "dimensions": [d.to_dict() for d in dimensions],
        "overfitting": drift.to_dict(),
        "release_gate": {"may_activate": ok, "because": why},
        "hygiene": partition_hygiene(session, tenant=tenant),
        "sealed_holdout": {
            "version": baseline.sealed_holdout_version,
            "content_shown": False,
            "why": (
                "§58: sealed-holdout content may never reach the "
                "continuous-learning UI. The version identifier says which "
                "exam was sat; aggregate figures appear only after an "
                "approved certification run."
            ),
        },
        # §60's distinction, about the two blocks directly above it.
        "these_are_not_the_same_thing": (
            "Learning captured is what went in. Measured change is what "
            "came out. They are reported separately and never added: an "
            "installation that captured four hundred observations and "
            "improved by nothing has done something worth knowing, and one "
            "number would report it as progress."
        ),
        # §63's, about quantity against quality, which is the same idea
        # applied to the verdict rather than to the two blocks.
        "quantity_is_not_quality": verdict["why_they_are_separate"],
    }


def _no_baseline(window: str) -> dict[str, Any]:
    return {
        "baseline": None,
        "window": window,
        "windows_available": list(sn.WINDOWS),
        "headline": ("NO BASELINE — nothing here can be compared to "
                     "anything yet"),
        "learning_captured": {},
        "measured_change": {},
        "dimensions": [],
        "why": (
            "A baseline is recorded when a Brain is activated or an "
            "Intelligence Release goes live. Until one exists, any figure "
            "on this screen would be a number with no reference point — and "
            "a number with no reference point gets compared to whichever "
            "earlier number flatters it."
        ),
    }


def _no_snapshots(baseline: sn.Baseline, window: str) -> dict[str, Any]:
    return {
        "baseline": {"baseline_id": baseline.baseline_id,
                     "comparable_to": baseline.comparable_to,
                     "created_at": baseline.created_at},
        "window": window,
        "windows_available": list(sn.WINDOWS),
        "headline": "NOT MEASURED IN THIS WINDOW",
        "learning_captured": {},
        "measured_change": {},
        "dimensions": [],
        "why": (
            "No evaluation ran inside this window. That is not the same as "
            "nothing having changed: it means nobody looked, and the two "
            "read identically on a chart."
        ),
    }


def _dimension_results(baseline: sn.Baseline,
                       latest: sn.Snapshot) -> list[ms.DimensionResult]:
    results: list[ms.DimensionResult] = []
    for name in DIMENSIONS:
        before_dev = baseline.six_dimension_scores.get(name, 0.0)
        before_val = baseline.validation_metrics.get(name, before_dev)
        results.append(ms.DimensionResult(
            dimension=name,
            development=ms.Change(
                name, before_dev,
                latest.six_dimension_scores_dev.get(name, before_dev),
                cases=latest.case_count_dev,
                critical_introduced=latest.critical_failures_dev,
                coverage=latest.coverage_dev, partition=pt.DEVELOPMENT),
            validation=ms.Change(
                name, before_val,
                latest.six_dimension_scores_validation.get(name, before_val),
                cases=latest.case_count_validation,
                critical_introduced=latest.critical_failures_validation,
                coverage=latest.coverage_validation, partition=pt.VALIDATION),
        ))
    return results


def _sum_quantity(rows: list[LearningSnapshot]) -> dict[str, int]:
    keys = ("new_learning_captured", "new_learning_reviewed",
            "new_learning_approved", "new_learning_rejected",
            "new_learning_activated", "new_teaching_cases",
            "new_regulatory_items", "new_blueprint_changes",
            "new_policy_changes", "new_method_changes",
            "new_feedback_regressions")
    totals = {k: sum(getattr(r, k, 0) for r in rows) for k in keys}
    totals["still_open"] = rows[-1].open_learning_items if rows else 0
    return totals


# ------------------------------------------------------------------ §65/§66


def timeline(session: Session, *, tenant: str = "",
             window: str = sn.LAST_12_MONTHS) -> dict[str, Any]:
    """§65. Every snapshot in order, with what triggered it.

    The trigger matters more than the date: a snapshot taken because a Brain
    was imported is the one worth comparing against, and a daily snapshot
    taken while nothing happened is a data point about noise.
    """
    rows = snapshots_in(session, tenant=tenant, window=window)
    return {
        "window": window,
        "points": [{
            "snapshot_id": r.snapshot_id,
            "at": r.created_at.isoformat() if r.created_at else "",
            "trigger": r.trigger,
            "marks_a_change": r.trigger in sn.CHANGE_TRIGGERS,
            "development": dict(r.six_dimension_scores_dev or {}),
            "validation": dict(r.six_dimension_scores_validation or {}),
            "critical_failures_validation": r.critical_failures_validation,
            "captured": r.new_learning_captured,
            "activated": r.new_learning_activated,
        } for r in rows],
        "note": (
            "A snapshot taken because something changed is worth comparing "
            "against. A scheduled one taken while nothing happened is a "
            "data point about noise, and the trigger column is how to tell "
            "them apart."
        ),
    }


def velocity(session: Session, *, tenant: str = "",
             days: int = 30) -> dict[str, Any]:
    """§66. How fast learning arrives, and how fast it lands."""
    rows = snapshots_in(session, tenant=tenant, window=sn.LAST_30_DAYS)
    return ms.velocity([_snapshot_from(r) for r in rows], days=days)


# ------------------------------------------------------------------ §72


def partition_hygiene(session: Session, *, tenant: str = "",
                      window_days: int = 30) -> dict[str, Any]:
    rows = session.execute(
        select(EvaluationUse).where(
            EvaluationUse.tenant == tenant)).scalars().all()
    uses = [pt.Use(partition=r.partition, at=r.created_at or _now(),
                   purpose=r.purpose, by=r.by) for r in rows]
    return pt.hygiene(uses, window_days=window_days).to_dict()


# ====================================================== §84 LEARNING QUESTIONS


def learning_facts(session: Session, *, tenant: str = "",
                   window: str = sn.SINCE_CURRENT_RELEASE,
                   anchor: datetime | None = None,
                   asker: str = "") -> qs.Facts:
    """Assemble what a §84 answer is allowed to read.

    Everything here comes out of the same `cockpit()` the screen shows, so
    a question and the dashboard beside it cannot disagree. Nothing is
    recomputed and nothing is estimated: a fact that is not persisted is
    absent, and an absent fact produces a refusal rather than a zero.
    """
    baseline_row = current_baseline(session, tenant=tenant)
    if baseline_row is None:
        return qs.Facts(window=window)

    baseline = _baseline_from(baseline_row)
    rows = snapshots_in(session, tenant=tenant, window=window,
                        anchor=anchor or baseline_row.created_at)
    if not rows:
        return qs.Facts(window=window,
                        baseline_snapshot_id=baseline.baseline_id)

    latest = _snapshot_from(rows[-1])
    return qs.Facts(
        dimensions=_dimension_results(baseline, latest),
        quantity=_sum_quantity(rows),
        pending_activation=_pending_activation(session, tenant=tenant),
        brain_lift=_brain_lift(session, tenant=tenant),
        feedback_attribution=_feedback_attribution(session, asker=asker,
                                                   tenant=tenant),
        window=window,
        window_label=_window_label(window),
        baseline_snapshot_id=baseline.baseline_id,
        current_snapshot_id=latest.snapshot_id,
    )


def _window_label(window: str) -> str:
    return window.replace("_", " ").lower()


def _pending_activation(session: Session, *,
                        tenant: str = "") -> list[dict[str, Any]]:
    """Approved learning that is not yet live.

    Approved is not activated. Until it is activated it is changing nothing
    about the answers users see, and a screen that counted the two together
    would report intent as effect.
    """
    from backend.models.platform import BrainLedgerEntry

    query = select(BrainLedgerEntry).where(
        BrainLedgerEntry.review_status == "APPROVED",
        BrainLedgerEntry.activated_at.is_(None))
    if tenant:
        query = query.where(BrainLedgerEntry.tenant == tenant)
    rows = session.execute(query.limit(200)).scalars().all()
    return [{"id": row.entry_id,
             "description": row.summary or row.object_kind or row.entry_id}
            for row in rows]


def _brain_lift(session: Session, *,
                tenant: str = "") -> dict[str, dict[str, Any]]:
    """Imported Brains that were actually measured in the Lift Lab.

    An import with no evaluation is left out rather than entered with a
    zero: "imported but never measured" and "measured and moved nothing"
    are different answers to "did it make us better".
    """
    from backend.models.platform import BrainImport, BrainPackage

    query = (select(BrainImport, BrainPackage)
             .join(BrainPackage,
                   BrainPackage.package_id == BrainImport.package_id))
    if tenant:
        query = query.where(BrainImport.tenant == tenant)
    rows = session.execute(query.limit(100)).all()

    out: dict[str, dict[str, Any]] = {}
    for record, package in rows:
        evaluation = record.evaluation or {}
        if not evaluation:
            continue
        name = package.brain_name or package.brain_id or record.import_id
        out[name] = {
            "validation_points": evaluation.get("validation_points"),
            "verdict": evaluation.get("verdict", ""),
            "isolated": bool(evaluation.get("isolated")),
            "reads_as": evaluation.get("reads_as", ""),
            "evaluation_id": record.import_id,
        }
    return out


def _feedback_attribution(session: Session, *, asker: str,
                          tenant: str = "") -> dict[str, Any]:
    """What one person's feedback led to. Empty when nobody is named.

    Three counts, deliberately kept apart: what they sent, how much of it
    became governed learning, and how much of that is actually live. The
    gap between the first and the last is the honest answer to "did my
    feedback change anything".
    """
    if not asker:
        return {}
    from backend.models.platform import AnswerFeedback, AnswerFeedbackStatus

    query = select(AnswerFeedback).where(AnswerFeedback.user_id == asker)
    if tenant:
        query = query.where(AnswerFeedback.tenant == tenant)
    rows = session.execute(query.limit(500)).scalars().all()
    if not rows:
        return {}

    ids = [row.feedback_id for row in rows]
    statuses = session.execute(
        select(AnswerFeedbackStatus)
        .where(AnswerFeedbackStatus.feedback_id.in_(ids))
    ).scalars().all()
    released = {s.feedback_id for s in statuses if s.status == "RELEASED"}

    return {
        "submitted": len(rows),
        "became_cases": sum(1 for row in rows if row.ledger_entry_id),
        "activated": len(released),
    }


def answer_question(session: Session, asked: str, *, tenant: str = "",
                    window: str = sn.SINCE_CURRENT_RELEASE,
                    asker: str = "") -> dict[str, Any]:
    """§84. Answer one governed question from persisted evaluations."""
    facts = learning_facts(session, tenant=tenant, window=window,
                           asker=asker)
    return qs.ask(asked, facts).to_dict()
