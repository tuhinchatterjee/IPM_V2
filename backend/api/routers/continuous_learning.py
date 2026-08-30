"""Continuous Learning, over HTTP. §60, §64-§66, §72, §76-§78, §86.

Everything here is deterministic and cheap. Opening the cockpit reads
recorded snapshots; it does not run an evaluation, does not call a provider
and does not spend anything. A screen that cost money to open is a screen
nobody opens, and this one exists to be looked at often.

Two contracts the routes hold
------------------------------
**Captured is never added to improved.** Every response separates the two
and says why. §63's sentence — MORE KNOWLEDGE CAPTURED, NO MEASURED
PERFORMANCE IMPROVEMENT YET — is the honest headline for the case that
actually happens, and it is produced rather than avoided.

**No sealed-holdout content leaves.** §58 names the continuous-learning UI
among the six places it may never reach. The version identifier is served;
the questions are not, and there is no parameter that changes that.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireLearningMeasure,
    RequireLearningView,
)
from backend.continuous import measurement as ms
from backend.continuous import partitions as pt
from backend.continuous import snapshots as sn
from backend.services import continuous_learning as cl

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/continuous-learning", tags=["continuous-learning"])


def _session():
    from backend.db.engine import SessionLocal

    return SessionLocal()


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "measurement_refused", "message": str(exc)})


@router.get("/cockpit")
def cockpit(window: str = Query(default=sn.SINCE_CURRENT_RELEASE),
            principal: Principal = RequireLearningView) -> dict[str, Any]:
    """§64. What has been learned, and — separately — what changed."""
    with _session() as session:
        try:
            return cl.cockpit(session, window=window)
        except sn.SnapshotError as exc:
            raise _refused(exc) from exc


@router.get("/windows")
def windows(principal: Principal = RequireLearningView) -> dict[str, Any]:
    """§60's thirteen, and which of them need an anchor rather than a
    duration."""
    return {
        "windows": [{"id": w, "anchored": w in sn.ANCHORED}
                    for w in sn.WINDOWS],
        "triggers": [{"id": t, "marks_a_change": t in sn.CHANGE_TRIGGERS}
                     for t in sn.TRIGGERS],
        "note": (
            "An anchored window starts at an event — an installation, a "
            "Brain activation, a release — rather than a number of days "
            "ago. Answering it with a duration would silently answer a "
            "different question than the one on the screen."
        ),
    }


@router.get("/timeline")
def timeline(window: str = Query(default=sn.LAST_12_MONTHS),
             principal: Principal = RequireLearningView) -> dict[str, Any]:
    """§65."""
    with _session() as session:
        try:
            return cl.timeline(session, window=window)
        except sn.SnapshotError as exc:
            raise _refused(exc) from exc


@router.get("/velocity")
def velocity(days: int = Query(default=30, ge=1, le=365),
             principal: Principal = RequireLearningView) -> dict[str, Any]:
    """§66."""
    with _session() as session:
        return cl.velocity(session, days=days)


@router.get("/partitions")
def partitions(principal: Principal = RequireLearningView) -> dict[str, Any]:
    """§58/§72. The three sets, what each is for, and how they are being used.

    The hygiene report is the point. Validation drifting into a second
    development set has no symptom until a release lands badly, and this is
    where it becomes visible while it is still reversible.
    """
    with _session() as session:
        return {
            "partitions": [{
                "id": p, "means": pt.MEANS[p],
                "used_for": list(pt.USED_FOR[p]),
                "may_tune_against": pt.tuning_allowed(p)[0],
                "why_not": pt.tuning_allowed(p)[1],
            } for p in pt.PARTITIONS],
            "sealed_holdout_never_reaches": [
                {"audience": a, "because": why}
                for a, why in pt.NEVER_EXPOSE_TO],
            "aggregate_fields_only": sorted(pt.AGGREGATE_ONLY),
            "hygiene": cl.partition_hygiene(session),
        }


@router.get("/measurement-rules")
def measurement_rules(principal: Principal = RequireLearningView
                      ) -> dict[str, Any]:
    """What a number on this screen is allowed to claim. §61-§63, §76-§78."""
    return {
        "labels": list(ms.LABELS),
        "evidence_levels": list(ms.EVIDENCE_LEVELS),
        "minimum_cases": ms.MINIMUM_CASES,
        "trivial_cases": ms.TRIVIAL_CASES,
        "material_points": ms.MATERIAL_POINTS,
        "stale_days": ms.STALE_DAYS,
        "attribution_sources": list(ms.SOURCES),
        "rules": {
            "three_forms": (
                "§61. Every change is shown as percentage points, as a "
                "relative change and as error reduction. All three are "
                "true and they say different things: points is what to "
                "quote, relative is what a vendor quotes, and error "
                "reduction is what an engineer cares about. Reporting only "
                "the relative figure is how a 2 pp move on a small base "
                "becomes 'a 40% improvement'."
            ),
            "quantity_is_not_quality": (
                "§63. Do not claim CreditProbe learned 15% more merely "
                "because more cases were added. Where capture rose with no "
                "measured lift the headline is MORE KNOWLEDGE CAPTURED — "
                "NO MEASURED PERFORMANCE IMPROVEMENT YET."
            ),
            "validation_outranks_development": (
                "§76. Development is the set that was tuned against, so a "
                "development improvement validation does not confirm is "
                "MIXED at best. A screen taking the development verdict "
                "would report every round of tuning as a win."
            ),
            "no_percentage_without_a_sample": (
                "§77. Every figure travels with a case count and an "
                "evidence level. Below "
                f"{ms.MINIMUM_CASES} cases a difference is not "
                "distinguishable from noise, and below "
                f"{ms.TRIVIAL_CASES} a percentage should not be shown at "
                "all."
            ),
            "the_waterfall_may_not_balance": (
                "§78. Only isolated evaluations are attributed; everything "
                "else goes into UNATTRIBUTED / INTERACTION. A waterfall "
                "that always balances is one somebody made balance, and the "
                "made-up bar is the one a reader trusts most because it "
                "makes the picture work."
            ),
            "critical_validation_regression_blocks_activation": (
                "§76. Not weighed against the improvements — a critical "
                "failure on the out-of-sample set is a wrong answer the "
                "bank would have shown a client."
            ),
        },
    }


class BaselineBody(BaseModel):
    instance_id: str = Field(..., max_length=64)
    build_sha: str = Field(..., max_length=40)
    app_version: str = Field(default="", max_length=32)
    brain_id: str = Field(default="", max_length=64)
    brain_version: str = Field(default="", max_length=32)
    intelligence_release_id: str = Field(default="", max_length=64)
    teaching_release_id: str = Field(default="", max_length=64)
    ontology_version: str = Field(default="", max_length=16)
    development_set_version: str = Field(..., max_length=32)
    validation_set_version: str = Field(default="", max_length=32)
    sealed_holdout_version: str = Field(default="", max_length=32)
    six_dimension_scores: dict[str, float] = Field(default_factory=dict)
    validation_metrics: dict[str, float] = Field(default_factory=dict)
    case_counts: dict[str, int] = Field(default_factory=dict)
    known_limitations: list[str] = Field(default_factory=list)


@router.post("/baselines", status_code=status.HTTP_201_CREATED)
def create_baseline(body: BaselineBody,
                    principal: Principal = RequireLearningMeasure
                    ) -> dict[str, Any]:
    """§57. Record what we were and how we did, as a reference point."""
    baseline = sn.Baseline(
        instance_id=body.instance_id, build_sha=body.build_sha,
        app_version=body.app_version, brain_id=body.brain_id,
        brain_version=body.brain_version,
        intelligence_release_id=body.intelligence_release_id,
        teaching_release_id=body.teaching_release_id,
        ontology_version=body.ontology_version,
        development_set_version=body.development_set_version,
        validation_set_version=body.validation_set_version,
        sealed_holdout_version=body.sealed_holdout_version,
        six_dimension_scores=dict(body.six_dimension_scores),
        validation_metrics=dict(body.validation_metrics),
        case_counts=dict(body.case_counts),
        known_limitations=tuple(body.known_limitations),
    )
    with _session() as session:
        try:
            row = cl.record_baseline(session, baseline)
        except cl.ContinuousLearningError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"baseline_id": row.baseline_id,
                "comparable_to": baseline.comparable_to,
                "fingerprint": row.fingerprint}


class SnapshotBody(BaseModel):
    instance_id: str = Field(default="", max_length=64)
    trigger: str = Field(default=sn.MANUAL, max_length=32)
    comparison_baseline_id: str = Field(..., max_length=48)
    development_set_version: str = Field(default="", max_length=32)
    validation_set_version: str = Field(default="", max_length=32)
    six_dimension_scores_dev: dict[str, float] = Field(default_factory=dict)
    six_dimension_scores_validation: dict[str, float] = Field(
        default_factory=dict)
    critical_failures_dev: int = 0
    critical_failures_validation: int = 0
    coverage_dev: float = 0.0
    coverage_validation: float = 0.0
    case_count_dev: int = 0
    case_count_validation: int = 0
    new_learning_captured: int = 0
    new_learning_reviewed: int = 0
    new_learning_approved: int = 0
    new_learning_activated: int = 0
    new_teaching_cases: int = 0
    open_learning_items: int = 0


@router.post("/snapshots", status_code=status.HTTP_201_CREATED)
def create_snapshot(body: SnapshotBody,
                    principal: Principal = RequireLearningMeasure
                    ) -> dict[str, Any]:
    """§59. Record a measurement. Immutable: there is no update route."""
    snapshot = sn.Snapshot(**body.model_dump())
    with _session() as session:
        try:
            row = cl.record_snapshot(session, snapshot)
        except cl.ContinuousLearningError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"snapshot_id": row.snapshot_id, "trigger": row.trigger,
                "fingerprint": row.fingerprint, "immutable": True}


# ---------------------------------------------------------------- §83, §87


@router.get("/staleness")
def staleness(principal: Principal = RequireLearningView) -> dict[str, Any]:
    """§87. Whether the newest measurement still describes what is running.

    Names the axes individually rather than returning a boolean. "Stale"
    tells a reader to re-run something; "stale, the ontology changed on the
    14th" tells them what to re-run and roughly how much to expect — and
    lets them decide that a prompt-only change probably did not move
    Computation & Evidence.
    """
    from backend import build_info
    from backend.continuous import staleness as st
    from backend.semantics import ontology

    with _session() as session:
        baseline = cl.current_baseline(session)
        rows = cl.snapshots_in(session, window=sn.ALL_TIME)
        latest = rows[-1] if rows else None

        if latest is None:
            return {
                "label": st.CURRENT,
                "stale": False,
                "changed_axes": [],
                "findings": [],
                "why": ("Nothing has been measured, so nothing can be out of "
                        "date. That is not the same as being current."),
                "axes": [{"axis": a, "what_it_is": w,
                          "plausibly_affects": e} for a, w, e in st.AXES],
            }

        measured = {
            "brain_version": latest.brain_version,
            "intelligence_release_id": latest.intelligence_release_id,
            "development_set_version": latest.development_set_version,
            "build_sha": baseline.build_sha if baseline else "",
            "ontology_version": (baseline.ontology_version
                                 if baseline else ""),
            "prompt_versions": (baseline.prompt_versions
                                if baseline else {}),
            "model_role_configuration": (baseline.model_role_configuration
                                         if baseline else {}),
            "method_version": "",
            "relationship_version": "",
        }
        running = dict(measured)
        running["build_sha"] = getattr(build_info, "GIT_SHA", "") or ""
        running["ontology_version"] = ontology.ONTOLOGY_VERSION

        body = st.assess(measured, running).to_dict()
        body["measured_at"] = (latest.created_at.isoformat()
                               if latest.created_at else "")
        body["axes"] = [{"axis": a, "what_it_is": w, "plausibly_affects": e}
                        for a, w, e in st.AXES]
        return body


@router.get("/report")
def learning_report(window: str = Query(default=sn.SINCE_CURRENT_RELEASE),
                    principal: Principal = RequireLearningView) -> Response:
    """§83's DOWNLOAD LEARNING REPORT.

    Refuses to write a workbook carrying a secret or a client row — the scan
    runs over the assembled cells rather than over the inputs, because the
    leak that matters is the one that reached a cell.
    """
    from backend.continuous import report as rp
    from backend.exports.contract import XLSX_MIME

    with _session() as session:
        try:
            payload = cl.cockpit(session, window=window)
        except sn.SnapshotError as exc:
            raise _refused(exc) from exc

    try:
        book = rp.build(payload)
    except rp.ReportError as exc:
        raise _refused(exc) from exc

    return Response(
        content=book.content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{book.filename}"',
            "X-CreditProbe-Sheets": str(len(book.manifest["sheets"])),
        },
    )


# ==================================================== §84 LEARNING QUESTIONS


class QuestionBody(BaseModel):
    question: str = Field(..., max_length=500)
    window: str = Field(default=sn.SINCE_CURRENT_RELEASE, max_length=64)


@router.get("/questions")
def question_catalogue(principal: Principal = RequireLearningView
                       ) -> dict[str, Any]:
    """§84. The questions this screen can answer, and where from."""
    from backend.continuous import questions as qs

    return {
        "questions": qs.catalogue(),
        "windows_available": list(sn.WINDOWS),
        "answered_from": "persisted snapshots and evaluations",
        "no_model_involved": (
            "§84: do not let an LLM invent performance numbers. Nothing on "
            "this route calls a model. A question that does not match one "
            "of these shapes is refused rather than approximated."),
    }


@router.post("/questions")
def ask_question(body: QuestionBody,
                 principal: Principal = RequireLearningView
                 ) -> dict[str, Any]:
    """§84. Answer one governed question from what is already stored."""
    from backend.continuous import questions as qs

    with _session() as session:
        try:
            answer = cl.answer_question(
                session, body.question, window=body.window,
                asker=getattr(principal, "user_id", "") or "")
        except sn.SnapshotError as exc:
            raise _refused(exc) from exc
    answer["catalogue"] = qs.catalogue()
    return answer


# ============================================ §68 CHANGE-ISOLATION EXPERIMENTS


class ArmBody(BaseModel):
    label: str = Field(..., max_length=64)
    changes: list[str] = Field(default_factory=list, max_length=32)
    scores: dict[str, float] = Field(default_factory=dict)
    families: dict[str, str] = Field(default_factory=dict)
    dimensions: dict[str, float] = Field(default_factory=dict)
    critical_failures: list[str] = Field(default_factory=list, max_length=500)
    latency_ms: float = 0.0
    cost_units: float = 0.0


class ExperimentBody(BaseModel):
    change_kind: str = Field(..., max_length=48)
    change_id: str = Field(..., max_length=128)
    baseline: ArmBody
    treatment: ArmBody
    partition: str = Field(default=pt.VALIDATION, max_length=32)
    mode: str = Field(default="DETERMINISTIC", max_length=32)
    authorization: str = Field(default="", max_length=200)


@router.get("/experiments")
def experiment_kinds(principal: Principal = RequireLearningView
                     ) -> dict[str, Any]:
    """§68. What an isolation experiment can attribute, and what it costs."""
    from backend.continuous import isolation as iso

    return {
        "change_kinds": [{"id": kind, "attributes_to": source}
                         for kind, source in iso.CHANGE_KINDS.items()],
        "modes": list(iso.MODES),
        "default_mode": iso.DETERMINISTIC,
        "minimum_cases": ms.MINIMUM_CASES,
        "live_provider_rule": (
            "§68: a live-provider A/B may not run without authorization. An "
            "A/B doubles the call count by construction."),
        "what_isolation_means": (
            "Two arms on the same cases, differing in exactly one declared "
            "change. Anything else is a real measurement of a joint effect, "
            "and may not be added to a waterfall as if it were additive."),
    }


@router.post("/experiments")
def run_experiment(body: ExperimentBody,
                   principal: Principal = RequireLearningMeasure
                   ) -> dict[str, Any]:
    """§68. Run one change-isolation experiment and report what it showed.

    Deterministic by default and free by default. The live-provider mode
    exists, refuses without authorization, and is never the default.
    """
    from backend.continuous import isolation as iso

    def _arm(payload: ArmBody) -> iso.Arm:
        return iso.Arm(
            label=payload.label, changes=frozenset(payload.changes),
            scores=dict(payload.scores), families=dict(payload.families),
            dimensions=dict(payload.dimensions),
            critical_failures=frozenset(payload.critical_failures),
            latency_ms=payload.latency_ms, cost_units=payload.cost_units)

    experiment = iso.Experiment(
        change_kind=body.change_kind, change_id=body.change_id,
        baseline=_arm(body.baseline), treatment=_arm(body.treatment),
        partition=body.partition, mode=body.mode)
    try:
        result = iso.run(experiment, by=_actor(principal),
                         authorization=body.authorization)
    except iso.IsolationError as exc:
        raise _refused(exc) from exc

    payload = result.to_dict()
    payload["contribution"] = result.contribution().to_dict()
    return payload


def _actor(principal: Principal) -> str:
    return getattr(principal, "user_id", "") or "unknown"
