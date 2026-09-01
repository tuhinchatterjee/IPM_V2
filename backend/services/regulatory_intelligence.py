"""Regulatory Intelligence, over the database. §29-§37.

The pure modules in `backend/regulatory/` decide; this moves rows.

Two boundaries it enforces, because they are the ones a service layer
usually erodes.

**Extraction never writes a decision.** `extract_requirements` writes rows at
PROPOSED with a confidence computed from evidence. Nothing in this file sets
`validation_status` to APPROVED except `decide`, which takes a named reviewer
and a reason and refuses without either.

**Promotion never writes a change.** `promote` writes drafts into
`regulatory_drafts`, addressed to whichever subsystem owns the thing. There is
no code path from here into the ontology, a method, a policy or a teaching
case. §35: "No direct mutation from extraction."
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.platform import (
    RegulatoryContradiction,
    RegulatoryCorrection,
    RegulatoryDraft,
    RegulatoryRequirement,
    RegulatoryRun,
)
from backend.regulatory import contradictions as cd
from backend.regulatory import pipeline as pl
from backend.regulatory import promotion as pm
from backend.regulatory import requirements as rq
from backend.regulatory import review as rv

logger = logging.getLogger(__name__)


class RegulatoryIntelligenceError(Exception):
    """An action the regulatory layer refused, and why."""


def _now() -> datetime:
    return datetime.now(UTC)


# ==================================================== §29 the pipeline


def start_run(session: Session, document_id: str, *, actor: str,
              tenant: str = "") -> RegulatoryRun:
    """Begin a processing run for one document."""
    progress = pl.Progress(document_id=document_id, tenant=tenant)
    row = RegulatoryRun(
        run_id=progress.run_id, document_id=document_id,
        stage=progress.stage,
        stage_history=[s.to_dict() for s in progress.history],
        tenant=tenant, started_by=actor)
    session.add(row)
    session.flush()
    return row


def _progress_from(row: RegulatoryRun) -> pl.Progress:
    progress = pl.Progress(
        document_id=row.document_id, run_id=row.run_id, stage=row.stage,
        blockers=list(row.blockers or []), tenant=row.tenant)
    progress.history = [
        pl.Step(stage=s.get("stage", ""), at=s.get("at", ""),
                passed=bool(s.get("passed", True)), detail=s.get("detail", ""),
                by=s.get("by", ""), counts=dict(s.get("counts", {})))
        for s in (row.stage_history or [])]
    return progress


def advance_run(session: Session, run_id: str, stage: str, *, actor: str,
                passed: bool = True, detail: str = "",
                counts: dict[str, int] | None = None) -> RegulatoryRun:
    """Move a run one stage, or refuse a skipped one."""
    row = _require_run(session, run_id)
    progress = _progress_from(row)
    try:
        progress = pl.advance(progress, stage, passed=passed, detail=detail,
                              by=actor, counts=counts)
    except pl.PipelineError as exc:
        raise RegulatoryIntelligenceError(str(exc)) from exc
    row.stage = progress.stage
    row.stage_history = [s.to_dict() for s in progress.history]
    row.blockers = list(progress.blockers)
    session.flush()
    return row


def _require_run(session: Session, run_id: str) -> RegulatoryRun:
    row = session.execute(
        select(RegulatoryRun).where(
            RegulatoryRun.run_id == run_id)).scalar_one_or_none()
    if row is None:
        raise RegulatoryIntelligenceError(f"no regulatory run {run_id}")
    return row


# ============================================= §30/§31 extract requirements


def extract_requirements(session: Session, *, document_id: str,
                         clauses: list[dict[str, Any]], run_id: str = "",
                         jurisdiction: str = "",
                         tenant: str = "") -> list[RegulatoryRequirement]:
    """Turn clauses into proposed requirements. Decides nothing.

    A clause with no page and no section still becomes a requirement — and
    `validate()` will refuse to release it. That is deliberate: dropping
    uncited clauses at extraction would make a document whose anchoring
    failed look like a document with fewer obligations.
    """
    written: list[RegulatoryRequirement] = []
    for clause in clauses:
        text = str(clause.get("text", "")).strip()
        if not text:
            continue
        proposed = rq.propose(
            text, document_id=document_id,
            page=int(clause.get("page", 0) or 0),
            section_number=str(clause.get("section_number", "")),
            section_title=str(clause.get("section_title", "")),
            concepts=tuple(clause.get("concepts", ()) or ()),
            datasets=tuple(clause.get("datasets", ()) or ()),
            jurisdiction=jurisdiction, tenant=tenant)
        written.append(_write_requirement(session, proposed, run_id=run_id))
    session.flush()
    logger.info("document %s: %d requirement(s) proposed, %d uncited",
                document_id, len(written),
                sum(1 for r in written if not r.page and not r.section_number))
    return written


def _write_requirement(session: Session, requirement: rq.Requirement, *,
                       run_id: str = "") -> RegulatoryRequirement:
    row = RegulatoryRequirement(
        requirement_id=requirement.requirement_id,
        document_id=requirement.document_id,
        run_id=run_id,
        schema_version=requirement.schema_version,
        page=requirement.page,
        section_number=requirement.section_number,
        section_title=requirement.section_title,
        paragraph=requirement.paragraph,
        excerpt=requirement.excerpt,
        excerpt_truncated=requirement.excerpt_truncated,
        summary=requirement.summary,
        requirement_type=requirement.requirement_type,
        relevance=requirement.relevance,
        topics=list(requirement.topics),
        jurisdiction=requirement.jurisdiction,
        portfolio_scope=list(requirement.portfolio_scope),
        product_scope=list(requirement.product_scope),
        affected={
            "concepts": list(requirement.affected_concepts),
            "datasets": list(requirement.affected_datasets),
            "relationships": list(requirement.affected_relationships),
            "methods": list(requirement.affected_methods),
            "calculations": list(requirement.affected_calculations),
            "controls": list(requirement.affected_controls),
            "reports": list(requirement.affected_reports),
            "agents": list(requirement.affected_agents),
            "teaching_cases": list(requirement.affected_teaching_cases),
        },
        interpretation_confidence=requirement.interpretation_confidence,
        confidence_because=list(requirement.confidence_because),
        validation_status=requirement.validation_status,
        version=requirement.version,
        promotion_status=requirement.promotion_status,
        tenant=requirement.tenant,
    )
    session.add(row)
    return row


def _requirement_from(row: RegulatoryRequirement) -> rq.Requirement:
    affected = row.affected or {}
    return rq.Requirement(
        requirement_id=row.requirement_id, document_id=row.document_id,
        schema_version=row.schema_version, page=row.page,
        section_number=row.section_number, section_title=row.section_title,
        paragraph=row.paragraph, excerpt=row.excerpt,
        excerpt_truncated=row.excerpt_truncated, summary=row.summary,
        requirement_type=row.requirement_type, relevance=row.relevance,
        topics=tuple(row.topics or ()), jurisdiction=row.jurisdiction,
        effective_from=(row.effective_from.date()
                        if row.effective_from else None),
        effective_to=(row.effective_to.date() if row.effective_to else None),
        portfolio_scope=tuple(row.portfolio_scope or ()),
        product_scope=tuple(row.product_scope or ()),
        affected_concepts=tuple(affected.get("concepts", ())),
        affected_datasets=tuple(affected.get("datasets", ())),
        affected_relationships=tuple(affected.get("relationships", ())),
        affected_methods=tuple(affected.get("methods", ())),
        affected_calculations=tuple(affected.get("calculations", ())),
        affected_controls=tuple(affected.get("controls", ())),
        affected_reports=tuple(affected.get("reports", ())),
        affected_agents=tuple(affected.get("agents", ())),
        affected_teaching_cases=tuple(affected.get("teaching_cases", ())),
        interpretation_confidence=row.interpretation_confidence,
        confidence_because=tuple(row.confidence_because or ()),
        validation_status=row.validation_status, reviewer=row.reviewer,
        decision=row.decision, decision_reason=row.decision_reason,
        correction=row.correction, version=row.version,
        conflicts=tuple(row.conflicts or ()),
        promotion_status=row.promotion_status, promoted_as=row.promoted_as,
        created_at=row.created_at.isoformat() if row.created_at else "",
        tenant=row.tenant,
    )


def _require_requirement(session: Session,
                         requirement_id: str) -> RegulatoryRequirement:
    row = session.execute(
        select(RegulatoryRequirement).where(
            RegulatoryRequirement.requirement_id ==
            requirement_id)).scalar_one_or_none()
    if row is None:
        raise RegulatoryIntelligenceError(f"no requirement {requirement_id}")
    return row


# ============================================================ §32 review


def review_panel(session: Session, requirement_id: str, *,
                 document: dict[str, Any] | None = None) -> dict[str, Any]:
    """§32's four blocks for one requirement, with its open conflicts."""
    row = _require_requirement(session, requirement_id)
    conflicts = session.execute(
        select(RegulatoryContradiction).where(
            RegulatoryContradiction.requirement_id ==
            requirement_id)).scalars().all()
    return rv.panel(
        _requirement_from(row), document=document,
        conflicts=[{
            "contradiction_id": c.contradiction_id,
            "conflict_class": c.conflict_class,
            "class_means": dict(cd.CLASSES).get(c.conflict_class, ""),
            "severity": c.severity,
            "summary": c.summary,
            "existing": c.existing or {},
            "resolution": c.resolution,
            "resolved": bool(c.resolution)
            and c.resolution not in cd.DEFERRING,
        } for c in conflicts])


def decide(session: Session, requirement_id: str, action: str, *,
           reviewer: str, reason: str,
           target: str = "") -> RegulatoryRequirement:
    """Apply one of §32's seven actions. The only path to APPROVED."""
    row = _require_requirement(session, requirement_id)
    requirement = _requirement_from(row)
    try:
        requirement = rv.decide(requirement, action, reviewer=reviewer,
                                reason=reason, target=target)
    except rv.ReviewError as exc:
        raise RegulatoryIntelligenceError(str(exc)) from exc
    row.validation_status = requirement.validation_status
    row.relevance = requirement.relevance
    row.reviewer = requirement.reviewer
    row.decision = requirement.decision
    row.decision_reason = requirement.decision_reason
    row.correction = requirement.correction
    row.version = requirement.version
    session.flush()
    return row


def record_correction(session: Session, requirement_id: str, *,
                      correction: str, reason: str, user_id: str,
                      user_role: str, corrected_type: str = "",
                      scope: str = "", effective_date: str = "",
                      proposed_target: dict[str, Any] | None = None
                      ) -> RegulatoryCorrection:
    """§33. Capture a reviewer's reading beside the machine's.

    `authoritative` is False and stays False. A correction from one user is
    not automatically authoritative; it becomes so by travelling the release
    path like everything else.
    """
    row = _require_requirement(session, requirement_id)
    try:
        record = rv.record_correction(
            _requirement_from(row), correction=correction, reason=reason,
            user_id=user_id, user_role=user_role,
            corrected_type=corrected_type, scope=scope,
            effective_date=effective_date, proposed_target=proposed_target)
    except rv.ReviewError as exc:
        raise RegulatoryIntelligenceError(str(exc)) from exc
    written = RegulatoryCorrection(
        correction_id=record.correction_id,
        requirement_id=record.requirement_id,
        document_id=record.document_id,
        original_interpretation=record.original_interpretation,
        original_type=record.original_type,
        original_confidence=record.original_confidence,
        correction=record.correction,
        corrected_type=record.corrected_type,
        reason=record.reason,
        user_id=record.user_id,
        user_role=record.user_role,
        scope=record.scope,
        effective_date=record.effective_date,
        proposed_target=dict(record.proposed_target),
        review_status=record.review_status,
        authoritative=False,
        tenant=record.tenant,
    )
    session.add(written)
    session.flush()
    return written


def queue(session: Session, document_id: str = "", *,
          tenant: str = "") -> dict[str, Any]:
    """The review queue, with deferrals counted as outstanding."""
    query = select(RegulatoryRequirement).where(
        RegulatoryRequirement.tenant == tenant)
    if document_id:
        query = query.where(RegulatoryRequirement.document_id == document_id)
    rows = session.execute(query).scalars().all()
    requirements = [_requirement_from(r) for r in rows]
    return {
        "progress": rv.queue_progress(requirements),
        "census": rq.census(requirements),
        "requirements": [r.to_dict() for r in requirements],
    }


# ====================================================== §34 contradictions


def detect_contradictions(session: Session, requirement_id: str,
                          existing: list[cd.Position], *,
                          tenant: str = "") -> list[RegulatoryContradiction]:
    """§34. Find disagreements BEFORE review, so a reviewer decides once."""
    row = _require_requirement(session, requirement_id)
    requirement = _requirement_from(row)
    incoming = cd.Position(
        kind="requirement", identifier=requirement.requirement_id,
        label=requirement.summary[:80], source=requirement.document_id,
        jurisdiction=requirement.jurisdiction,
        scope=", ".join(requirement.portfolio_scope),
        product=", ".join(requirement.product_scope),
        effective_from=requirement.effective_from,
        statement=requirement.excerpt)
    found = cd.detect(incoming, existing, tenant=tenant)

    written: list[RegulatoryContradiction] = []
    for conflict in found:
        written.append(RegulatoryContradiction(
            contradiction_id=conflict.contradiction_id,
            requirement_id=requirement_id,
            document_id=requirement.document_id,
            conflict_class=conflict.conflict_class,
            severity=conflict.severity,
            summary=conflict.summary,
            incoming=conflict.incoming.to_dict(),
            existing=conflict.existing.to_dict(),
            available_resolutions=list(conflict.available),
            tenant=tenant))
    for one in written:
        session.add(one)
    row.conflicts = [c.contradiction_id for c in written]
    session.flush()
    return written


def resolve_contradiction(session: Session, contradiction_id: str, *,
                          resolution: str, reason: str, by: str,
                          effective_from: str = "", split_axis: str = ""
                          ) -> RegulatoryContradiction:
    """§34. Record a person's decision, never one this module made."""
    row = session.execute(
        select(RegulatoryContradiction).where(
            RegulatoryContradiction.contradiction_id ==
            contradiction_id)).scalar_one_or_none()
    if row is None:
        raise RegulatoryIntelligenceError(
            f"no contradiction {contradiction_id}")
    conflict = cd.Contradiction(
        contradiction_id=row.contradiction_id,
        conflict_class=row.conflict_class, severity=row.severity,
        summary=row.summary,
        available=tuple(row.available_resolutions or ()))
    try:
        conflict = cd.resolve(conflict, resolution, reason=reason, by=by,
                              effective_from=effective_from,
                              split_axis=split_axis)
    except cd.ContradictionError as exc:
        raise RegulatoryIntelligenceError(str(exc)) from exc
    row.resolution = conflict.resolution
    row.resolution_reason = conflict.resolution_reason
    row.effective_from = conflict.effective_from
    row.split_axis = conflict.split_axis
    row.resolved_by = conflict.resolved_by
    row.resolved_at = _now()
    session.flush()
    return row


# ================================================= §35/§36 promotion


def promote(session: Session, requirement_id: str, *, actor: str,
            targets: tuple[str, ...] = (),
            governance_owner: str = "") -> list[RegulatoryDraft]:
    """§35. Write drafts. Changes nothing anywhere else, by construction."""
    row = _require_requirement(session, requirement_id)
    requirement = _requirement_from(row)
    try:
        drafts = pm.promote(requirement, targets=targets, by=actor,
                            governance_owner=governance_owner)
    except pm.PromotionError as exc:
        raise RegulatoryIntelligenceError(str(exc)) from exc

    written: list[RegulatoryDraft] = []
    for draft in drafts:
        one = RegulatoryDraft(
            draft_id=draft.draft_id,
            requirement_id=draft.requirement_id,
            document_id=draft.document_id,
            target=draft.target,
            summary=draft.summary,
            payload=dict(draft.payload),
            citation=dict(draft.citation),
            effective_from=draft.effective_from,
            governance_owner=draft.governance_owner,
            status=draft.status,
            tenant=draft.tenant,
            created_by=actor)
        session.add(one)
        written.append(one)
    row.promotion_status = rq.DRAFTED
    session.flush()
    return written


def configure_method(session: Session, requirement_id: str, *, actor: str,
                     governance_owner: str = "",
                     document: dict[str, Any] | None = None
                     ) -> RegulatoryDraft:
    """§36's CONFIGURE IN ANALYSIS STUDIO. A Draft Method, never certified."""
    row = _require_requirement(session, requirement_id)
    requirement = _requirement_from(row)
    try:
        method = pm.draft_method(requirement, by=actor,
                                 governance_owner=governance_owner,
                                 document=document)
    except pm.PromotionError as exc:
        raise RegulatoryIntelligenceError(str(exc)) from exc

    draft = RegulatoryDraft(
        draft_id=method["draft_method_id"],
        requirement_id=requirement_id,
        document_id=requirement.document_id,
        target="analysis studio method",
        summary=method["name"],
        payload=method,
        citation=method["parts"]["citations"][0],
        effective_from=method["parts"]["effective_date"],
        governance_owner=governance_owner,
        status=pm.DRAFT,
        tenant=requirement.tenant,
        created_by=actor)
    session.add(draft)
    row.promotion_status = rq.DRAFTED
    row.promoted_as = draft.draft_id
    session.flush()
    return draft


def pass_gate(session: Session, draft_id: str, gate: str, *, actor: str,
              note: str = "") -> RegulatoryDraft:
    """Record that one of §35's five gates was cleared for a draft."""
    row = session.execute(
        select(RegulatoryDraft).where(
            RegulatoryDraft.draft_id == draft_id)).scalar_one_or_none()
    if row is None:
        raise RegulatoryIntelligenceError(f"no draft {draft_id}")
    draft = pm.Draft(draft_id=row.draft_id, target=row.target,
                     gates_passed=tuple(row.gates_passed or ()),
                     status=row.status)
    try:
        draft = pm.pass_gate(draft, gate, by=actor, note=note)
    except pm.PromotionError as exc:
        raise RegulatoryIntelligenceError(str(exc)) from exc
    row.gates_passed = list(draft.gates_passed)
    ok, _ = pm.may_release(draft)
    if ok and row.status == pm.DRAFT:
        # Every gate cleared. Still not released — that is the release's
        # own act, and this only records that nothing is outstanding.
        row.status = pm.APPROVED
    session.flush()
    return row


def drafts(session: Session, *, tenant: str = "",
           requirement_id: str = "") -> list[dict[str, Any]]:
    query = select(RegulatoryDraft).where(RegulatoryDraft.tenant == tenant)
    if requirement_id:
        query = query.where(RegulatoryDraft.requirement_id == requirement_id)
    rows = session.execute(
        query.order_by(RegulatoryDraft.created_at.desc())).scalars().all()
    return [{
        "draft_id": r.draft_id,
        "requirement_id": r.requirement_id,
        "target": r.target,
        "summary": r.summary,
        "status": r.status,
        "gates_passed": r.gates_passed or [],
        "outstanding_gates": [f"{name}: {why}" for name, why in pm.GATES
                              if name not in (r.gates_passed or [])],
        "governance_owner": r.governance_owner,
        "effective_from": r.effective_from,
        "citation": r.citation or {},
        "applied": r.status == pm.RELEASED,
        "certification": (r.payload or {}).get("certification", {}),
    } for r in rows]
