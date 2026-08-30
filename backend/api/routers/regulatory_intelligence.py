"""Regulatory Intelligence, over HTTP. §29-§38.

§38's eight tabs, and where each one lives
-------------------------------------------
DOCUMENTS, PROCESSING, REQUIREMENTS, REVIEW, CONFLICTS, METHOD CANDIDATES,
RELEASES, AUDIT. The first and the seventh are served by the existing
`/regulatory` router, which already owns the document library and the
Regulatory Knowledge Release. This router owns the six in between — the part
where a person decides what a clause means.

§27 puts this under Analysis Studio and deep-links Regulatory LEARNING from
the AI Intelligence Studio, and the split is not cosmetic. Analysis Studio
owns the source library, the extracted requirements and the promotion into
methods. AI Intelligence Studio owns what the bank LEARNED from them. A
single screen for both would let a circular and a certified method look like
the same kind of object, which §27 forbids in as many words.

Three refusals worth knowing about
-----------------------------------
Every review decision needs a reason, approval included. Every contradiction
resolution that supersedes needs the date it supersedes from. And no route
here writes to the ontology, a method, a policy or a teaching case — §35's
"no direct mutation from extraction" is enforced by there being no such code.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireRegulatoryIngest,
    RequireRegulatoryPromote,
    RequireRegulatoryResolve,
    RequireRegulatoryReview,
    RequireRegulatoryView,
)
from backend.regulatory import contradictions as cd
from backend.regulatory import pipeline as pl
from backend.regulatory import promotion as pm
from backend.regulatory import requirements as rq
from backend.regulatory import review as rv
from backend.regulatory import schema as sc
from backend.services import regulatory_intelligence as ri

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/regulatory-intelligence",
                   tags=["regulatory-intelligence"])


def _session():
    from backend.db.engine import SessionLocal

    return SessionLocal()


def _actor(principal: Principal) -> str:
    return f"user:{principal.user_id}" if principal.user_id else "system"


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "regulatory_refused", "message": str(exc)})


# ================================================================ the schema


@router.get("/schema")
def schema(principal: Principal = RequireRegulatoryView) -> dict[str, Any]:
    """What the regulatory layer knows how to say. §28, §30, §31, §34, §35.

    Served as data rather than documented, so a screen renders the same
    fifteen types and twenty-six topics the backend classifies against. Two
    lists that can drift are two lists that will.
    """
    return {
        "document_types": [{"id": t, "means": sc.DOCUMENT_TYPE_MEANS[t]}
                           for t in sc.DOCUMENT_TYPES],
        "never_in_force": sorted(sc.NOT_IN_FORCE),
        "requirement_types": [{"id": t, "means": rq.TYPE_MEANS[t],
                               "configurable": t in rq.CONFIGURABLE}
                              for t in rq.TYPES],
        "credit_topics": list(rq.TOPIC_IDS),
        "relevance": list(rq.RELEVANCE),
        "review_actions": [{"id": a, "means": rv.ACTION_MEANS[a],
                            "needs_target": a in rv.NEEDS_TARGET,
                            "counts_as_reviewed": a not in rv.NOT_PROGRESS}
                           for a in rv.ACTIONS],
        "contradiction_classes": [{"id": c, "means": m}
                                  for c, m in cd.CLASSES],
        "resolutions": [{"id": r, "means": m,
                         "needs_date": r in cd.NEEDS_DATE,
                         "needs_axis": r in cd.NEEDS_AXIS,
                         "leaves_it_open": r in cd.DEFERRING}
                        for r, m in cd.RESOLUTIONS],
        "promotion_targets": list(rv.PROMOTION_TARGETS),
        "promotion_gates": [{"id": g, "means": m} for g, m in pm.GATES],
        "draft_method_parts": list(pm.METHOD_PARTS),
        "rules": {
            "extraction_never_dismisses": (
                "A clause that matches no credit topic is AMBIGUOUS, not "
                "NOT_CREDIT_RELATED. §31 forbids claiming a clause is "
                "irrelevant without review where there is ambiguity, and "
                "only a named person may make that call."
            ),
            "no_direct_mutation": (
                "§35. Approving a requirement creates a DRAFT addressed to "
                "whichever subsystem owns the thing. Nothing here writes to "
                "the ontology, a method, a policy or a teaching case."
            ),
            "no_auto_certification": (
                "§36. A Draft Method enters the ordinary Analysis Studio "
                "validation and certification workflow. A regulation "
                "requiring a calculation is not evidence that this "
                "particular calculation is right."
            ),
            "never_delete_the_other_one": (
                "§34. There is no resolution that simply removes the losing "
                "position. Supersession carries the date it takes effect, "
                "because a restatement of a prior period still has to quote "
                "what applied then."
            ),
        },
    }


# =========================================================== §29 PROCESSING


class RunBody(BaseModel):
    document_id: str = Field(..., max_length=64)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def start_run(body: RunBody,
              principal: Principal = RequireRegulatoryIngest
              ) -> dict[str, Any]:
    with _session() as session:
        row = ri.start_run(session, body.document_id,
                           actor=_actor(principal))
        session.commit()
        return {"run_id": row.run_id, "document_id": row.document_id,
                "stage": row.stage, "pipeline": list(pl.STAGES),
                "retrievable": False}


class StageBody(BaseModel):
    stage: str = Field(..., max_length=48)
    passed: bool = True
    detail: str = Field(default="", max_length=2000)
    counts: dict[str, int] = Field(default_factory=dict)


@router.post("/runs/{run_id}/advance")
def advance(run_id: str, body: StageBody,
            principal: Principal = RequireRegulatoryIngest
            ) -> dict[str, Any]:
    """Move a run one stage. Refuses a skipped stage.

    The only permitted jump is over CONFIGURED, which §29 marks optional: a
    governance requirement configures nothing in Analysis Studio and should
    not sit one stage from done forever.
    """
    with _session() as session:
        try:
            row = ri.advance_run(session, run_id, body.stage,
                                 actor=_actor(principal), passed=body.passed,
                                 detail=body.detail, counts=body.counts)
        except ri.RegulatoryIntelligenceError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"run_id": row.run_id, "stage": row.stage,
                "blockers": row.blockers or [],
                "history": row.stage_history or []}


@router.get("/runs")
def runs(document_id: str = Query(default=""),
         principal: Principal = RequireRegulatoryView) -> dict[str, Any]:
    """§38's PROCESSING tab."""
    from sqlalchemy import select

    from backend.models.platform import RegulatoryRun

    with _session() as session:
        query = select(RegulatoryRun).order_by(
            RegulatoryRun.created_at.desc())
        if document_id:
            query = query.where(RegulatoryRun.document_id == document_id)
        rows = session.execute(query).scalars().all()
        return {
            "pipeline": [{"stage": s, "means": pl.MEANS[s],
                          "quarantined": s in pl.QUARANTINED,
                          "optional": s in pl.OPTIONAL}
                         for s in pl.STAGES],
            "runs": [{
                "run_id": r.run_id, "document_id": r.document_id,
                "stage": r.stage, "stage_means": pl.MEANS.get(r.stage, ""),
                "blockers": r.blockers or [],
                "history": r.stage_history or [],
                "retrievable": r.stage in (pl.RELEASED, pl.CONFIGURED,
                                           pl.COMPLETE),
                "started_by": r.started_by,
                "created_at": r.created_at.isoformat()
                if r.created_at else "",
            } for r in rows],
        }


# ========================================================= §30 REQUIREMENTS


class ExtractBody(BaseModel):
    document_id: str = Field(..., max_length=64)
    run_id: str = Field(default="", max_length=48)
    jurisdiction: str = Field(default="", max_length=64)
    clauses: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/requirements", status_code=status.HTTP_201_CREATED)
def extract(body: ExtractBody,
            principal: Principal = RequireRegulatoryIngest
            ) -> dict[str, Any]:
    """Turn clauses into proposed requirements. Decides nothing."""
    with _session() as session:
        rows = ri.extract_requirements(
            session, document_id=body.document_id, clauses=body.clauses,
            run_id=body.run_id, jurisdiction=body.jurisdiction)
        session.commit()
        return {
            "document_id": body.document_id,
            "proposed": len(rows),
            "uncited": sum(1 for r in rows
                           if not r.page and not r.section_number),
            "all_at": rq.PROPOSED,
            "note": ("Nothing has been decided. Every requirement here is "
                     "CreditProbe's reading, waiting for a person."),
        }


@router.get("/requirements")
def requirements(document_id: str = Query(default=""),
                 principal: Principal = RequireRegulatoryView
                 ) -> dict[str, Any]:
    """§38's REQUIREMENTS tab, with the queue counted honestly."""
    with _session() as session:
        return ri.queue(session, document_id)


# =============================================================== §32 REVIEW


@router.get("/requirements/{requirement_id}/review")
def review_panel(requirement_id: str,
                 principal: Principal = RequireRegulatoryView
                 ) -> dict[str, Any]:
    """§32's four blocks: SOURCE, UNDERSTANDING, CONFLICTS, ACTIONS."""
    with _session() as session:
        try:
            return ri.review_panel(session, requirement_id)
        except ri.RegulatoryIntelligenceError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"error": "not_found",
                                        "message": str(exc)}) from exc


class DecisionBody(BaseModel):
    action: str = Field(..., max_length=40)
    reason: str = Field(..., max_length=4000)
    target: str = Field(default="", max_length=4000)


@router.post("/requirements/{requirement_id}/decide")
def decide(requirement_id: str, body: DecisionBody,
           principal: Principal = RequireRegulatoryReview) -> dict[str, Any]:
    """Apply one of §32's seven actions. The only route to APPROVED."""
    with _session() as session:
        try:
            row = ri.decide(session, requirement_id, body.action,
                            reviewer=_actor(principal), reason=body.reason,
                            target=body.target)
        except ri.RegulatoryIntelligenceError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"requirement_id": row.requirement_id,
                "validation_status": row.validation_status,
                "relevance": row.relevance,
                "decision": row.decision,
                "reviewer": row.reviewer,
                "version": row.version,
                "counts_as_reviewed": body.action not in rv.NOT_PROGRESS}


class CorrectionBody(BaseModel):
    correction: str = Field(..., max_length=4000)
    reason: str = Field(..., max_length=4000)
    user_role: str = Field(default="", max_length=32)
    corrected_type: str = Field(default="", max_length=24)
    scope: str = Field(default="", max_length=160)
    effective_date: str = Field(default="", max_length=32)
    proposed_target: dict[str, Any] = Field(default_factory=dict)


@router.post("/requirements/{requirement_id}/correct",
             status_code=status.HTTP_201_CREATED)
def correct(requirement_id: str, body: CorrectionBody,
            principal: Principal = RequireRegulatoryReview
            ) -> dict[str, Any]:
    """§33. "No, that is not the case. Understand it this way…"

    Stored beside our reading rather than instead of it, and activating
    nothing. A correction from one user is not automatically authoritative.
    """
    with _session() as session:
        try:
            row = ri.record_correction(
                session, requirement_id, correction=body.correction,
                reason=body.reason, user_id=_actor(principal),
                user_role=body.user_role or principal.role.value,
                corrected_type=body.corrected_type, scope=body.scope,
                effective_date=body.effective_date,
                proposed_target=body.proposed_target)
        except ri.RegulatoryIntelligenceError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"correction_id": row.correction_id,
                "requirement_id": row.requirement_id,
                "authoritative": row.authoritative,
                "activates_nothing": True,
                "note": ("Recorded as a Regulatory Learning Observation. It "
                         "takes effect through review, regression and "
                         "release — not because it was written down.")}


@router.get("/corrections")
def corrections(requirement_id: str = Query(default=""),
                principal: Principal = RequireRegulatoryView
                ) -> dict[str, Any]:
    """What we read, what people said, and how often they differed."""
    from sqlalchemy import select

    from backend.models.platform import RegulatoryCorrection

    with _session() as session:
        query = select(RegulatoryCorrection).order_by(
            RegulatoryCorrection.created_at.desc())
        if requirement_id:
            query = query.where(
                RegulatoryCorrection.requirement_id == requirement_id)
        rows = session.execute(query).scalars().all()
        return {
            "corrections": [{
                "correction_id": r.correction_id,
                "requirement_id": r.requirement_id,
                "we_read_it_as": r.original_interpretation,
                "our_confidence": round(r.original_confidence, 3),
                "they_read_it_as": r.correction,
                "reason": r.reason,
                "by": r.user_id,
                "role": r.user_role,
                "authoritative": r.authoritative,
                "created_at": r.created_at.isoformat()
                if r.created_at else "",
            } for r in rows],
            "note": ("Both readings are kept. A year from now somebody will "
                     "ask whether CreditProbe understood this clause "
                     "correctly the first time, and an edit in place would "
                     "make that unanswerable."),
        }


# ============================================================ §34 CONFLICTS


@router.get("/conflicts")
def conflicts(requirement_id: str = Query(default=""),
              principal: Principal = RequireRegulatoryView) -> dict[str, Any]:
    """§38's CONFLICTS tab, with deferrals counted as outstanding."""
    from sqlalchemy import select

    from backend.models.platform import RegulatoryContradiction

    with _session() as session:
        query = select(RegulatoryContradiction).order_by(
            RegulatoryContradiction.created_at.desc())
        if requirement_id:
            query = query.where(
                RegulatoryContradiction.requirement_id == requirement_id)
        rows = session.execute(query).scalars().all()
        unresolved = [r for r in rows
                      if not r.resolution or r.resolution in cd.DEFERRING]
        return {
            "classes": [{"id": c, "means": m} for c, m in cd.CLASSES],
            "resolutions": [{"id": r, "means": m,
                             "needs_date": r in cd.NEEDS_DATE,
                             "needs_axis": r in cd.NEEDS_AXIS,
                             "leaves_it_open": r in cd.DEFERRING}
                            for r, m in cd.RESOLUTIONS],
            "conflicts": [{
                "contradiction_id": r.contradiction_id,
                "requirement_id": r.requirement_id,
                "conflict_class": r.conflict_class,
                "class_means": dict(cd.CLASSES).get(r.conflict_class, ""),
                "severity": r.severity,
                "summary": r.summary,
                "incoming": r.incoming or {},
                "existing": r.existing or {},
                "available_resolutions": r.available_resolutions or [],
                "resolution": r.resolution,
                "resolution_reason": r.resolution_reason,
                "effective_from": r.effective_from,
                "split_axis": r.split_axis,
                "resolved_by": r.resolved_by,
                "resolved": bool(r.resolution)
                and r.resolution not in cd.DEFERRING,
            } for r in rows],
            "outstanding": len(unresolved),
            "note": ("There is no 'delete the other one'. §34 asks for a "
                     "governed resolution, and supersession carries the "
                     "date it takes effect because a restatement of a prior "
                     "period still has to quote what applied then."),
        }


class ResolveBody(BaseModel):
    resolution: str = Field(..., max_length=40)
    reason: str = Field(..., max_length=4000)
    effective_from: str = Field(default="", max_length=32)
    split_axis: str = Field(default="", max_length=64)


@router.post("/conflicts/{contradiction_id}/resolve")
def resolve(contradiction_id: str, body: ResolveBody,
            principal: Principal = RequireRegulatoryResolve
            ) -> dict[str, Any]:
    with _session() as session:
        try:
            row = ri.resolve_contradiction(
                session, contradiction_id, resolution=body.resolution,
                reason=body.reason, by=_actor(principal),
                effective_from=body.effective_from,
                split_axis=body.split_axis)
        except ri.RegulatoryIntelligenceError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {"contradiction_id": row.contradiction_id,
                "resolution": row.resolution,
                "effective_from": row.effective_from,
                "split_axis": row.split_axis,
                "resolved_by": row.resolved_by,
                "still_open": row.resolution in cd.DEFERRING}


# ==================================================== §35/§36 METHOD CANDIDATES


class PromoteBody(BaseModel):
    targets: list[str] = Field(default_factory=list)
    governance_owner: str = Field(default="", max_length=160)


@router.post("/requirements/{requirement_id}/promote",
             status_code=status.HTTP_201_CREATED)
def promote(requirement_id: str, body: PromoteBody,
            principal: Principal = RequireRegulatoryPromote
            ) -> dict[str, Any]:
    """§35. Create drafts. Changes nothing anywhere else, by construction."""
    with _session() as session:
        try:
            rows = ri.promote(session, requirement_id,
                              actor=_actor(principal),
                              targets=tuple(body.targets),
                              governance_owner=body.governance_owner)
        except ri.RegulatoryIntelligenceError as exc:
            raise _refused(exc) from exc
        session.commit()
        return {
            "requirement_id": requirement_id,
            "drafts": [{"draft_id": r.draft_id, "target": r.target,
                        "status": r.status} for r in rows],
            "nothing_changed_yet": True,
            "outstanding_gates": [f"{g}: {m}" for g, m in pm.GATES],
        }


@router.post("/requirements/{requirement_id}/configure-method",
             status_code=status.HTTP_201_CREATED)
def configure_method(requirement_id: str, body: PromoteBody,
                     principal: Principal = RequireRegulatoryPromote
                     ) -> dict[str, Any]:
    """§36's CONFIGURE IN ANALYSIS STUDIO. A Draft Method, never certified."""
    with _session() as session:
        try:
            row = ri.configure_method(
                session, requirement_id, actor=_actor(principal),
                governance_owner=body.governance_owner)
        except ri.RegulatoryIntelligenceError as exc:
            raise _refused(exc) from exc
        session.commit()
        payload = row.payload or {}
        return {
            "draft_method_id": row.draft_id,
            "name": row.summary,
            "parts": payload.get("parts", {}),
            "established": payload.get("established", {}),
            "certification": payload.get("certification", {}),
            "status": row.status,
        }


@router.get("/drafts")
def drafts(requirement_id: str = Query(default=""),
           principal: Principal = RequireRegulatoryView) -> dict[str, Any]:
    """§38's METHOD CANDIDATES tab, plus every other kind of draft."""
    with _session() as session:
        return {
            "targets": list(rv.PROMOTION_TARGETS),
            "gates": [{"id": g, "means": m} for g, m in pm.GATES],
            "drafts": ri.drafts(session, requirement_id=requirement_id),
            "note": ("A draft is a proposal addressed to whichever subsystem "
                     "owns the thing it would change. None of them applies "
                     "until all five gates are cleared and it is inside a "
                     "release."),
        }


class GateBody(BaseModel):
    gate: str = Field(..., max_length=32)
    note: str = Field(default="", max_length=2000)


@router.post("/drafts/{draft_id}/gate")
def pass_gate(draft_id: str, body: GateBody,
              principal: Principal = RequireRegulatoryPromote
              ) -> dict[str, Any]:
    with _session() as session:
        try:
            row = ri.pass_gate(session, draft_id, body.gate,
                               actor=_actor(principal), note=body.note)
        except ri.RegulatoryIntelligenceError as exc:
            raise _refused(exc) from exc
        session.commit()
        outstanding = [f"{g}: {m}" for g, m in pm.GATES
                       if g not in (row.gates_passed or [])]
        return {"draft_id": row.draft_id, "status": row.status,
                "gates_passed": row.gates_passed or [],
                "outstanding_gates": outstanding,
                "applied": row.status == pm.RELEASED}


# ================================================================ §38 AUDIT


@router.get("/audit")
def audit(document_id: str = Query(default=""),
          principal: Principal = RequireRegulatoryView) -> dict[str, Any]:
    """§38's AUDIT tab: who decided what, and on what basis.

    Everything a regulator would ask for about one document, in one place:
    the stages it went through, every decision with its reason and reviewer,
    every correction with both readings kept, every contradiction and how it
    was settled, and every draft with which gates it has cleared.
    """
    from sqlalchemy import select

    from backend.models.platform import (
        RegulatoryContradiction,
        RegulatoryCorrection,
        RegulatoryDraft,
        RegulatoryRequirement,
        RegulatoryRun,
    )

    with _session() as session:
        def scoped(model, column="document_id"):
            query = select(model)
            if document_id:
                query = query.where(getattr(model, column) == document_id)
            return session.execute(query).scalars().all()

        runs_ = scoped(RegulatoryRun)
        reqs = scoped(RegulatoryRequirement)
        cors = scoped(RegulatoryCorrection)
        cons = scoped(RegulatoryContradiction)
        drafts_ = scoped(RegulatoryDraft)

        return {
            "document_id": document_id,
            "runs": [{"run_id": r.run_id, "stage": r.stage,
                      "history": r.stage_history or []} for r in runs_],
            "decisions": [{
                "requirement_id": r.requirement_id,
                "summary": r.summary,
                "page": r.page, "section": r.section_number,
                "decision": r.decision, "reason": r.decision_reason,
                "reviewer": r.reviewer, "status": r.validation_status,
                "version": r.version,
                "confidence": round(r.interpretation_confidence, 3),
            } for r in reqs if r.decision],
            "undecided": [r.requirement_id for r in reqs if not r.decision],
            "corrections": [{
                "correction_id": r.correction_id,
                "requirement_id": r.requirement_id,
                "we_read_it_as": r.original_interpretation,
                "they_read_it_as": r.correction,
                "reason": r.reason, "by": r.user_id, "role": r.user_role,
                "authoritative": r.authoritative,
            } for r in cors],
            "contradictions": [{
                "contradiction_id": r.contradiction_id,
                "conflict_class": r.conflict_class, "severity": r.severity,
                "resolution": r.resolution, "reason": r.resolution_reason,
                "effective_from": r.effective_from,
                "resolved_by": r.resolved_by,
            } for r in cons],
            "drafts": [{
                "draft_id": r.draft_id, "target": r.target,
                "status": r.status, "gates_passed": r.gates_passed or [],
                "created_by": r.created_by,
            } for r in drafts_],
            "answers": ("What did this document require, who decided what it "
                        "meant, on what basis, and what changed here as a "
                        "result?"),
        }
