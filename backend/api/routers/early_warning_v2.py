"""Early Warning V2 over HTTP: the consolidated product's API surface.

Mounted alongside the existing `early_warning` router (which stays live
during the migration described in the implementation plan's Section 16 —
its fitted Forward Risk Signal and rule-based taxonomy are being
consolidated into this surface, not deleted in the same change that
introduces it). Route paths are deliberately distinct
(`/early-warning/v2/...`) so nothing here collides with the 16 existing
routes while the frontend migration (Phase 7) is completed.

Every number returned here comes from the governed Parquet domain built by
`scripts/build_early_warning_v2.py` and scored by the Phase 1 engine — never
computed ad hoc in this router.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireEarlyWarningEditEscalationMatrix,
    RequireEarlyWarningEscalate,
    RequireEarlyWarningRecordAction,
    RequireEarlyWarningReport,
    RequireEarlyWarningView,
)
from backend.early_warning import (
    accelerator as accel,
    aggregation as ta_agg,
    case_bridge,
    catalog as ews_catalog,
    classifiers_v2 as clf,
    escalation as esc,
    lineage as ews_lineage,
    matrix,
    notches as nt,
    reasons,
    reports as ews_reports,
    triggers_v2 as trg,
    v2_service as svc,
)
from backend.early_warning.v2_service import EarlyWarningDataNotBuilt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/early-warning/v2", tags=["early warning v2"])


def _not_built(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "early_warning_v2_not_built", "message": str(exc)},
    )


def _not_found(customer_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "borrower_not_found", "message": f"No Early Warning data for {customer_id}"},
    )


# ============================================================== methodology


@router.get("/methodology", summary="The Version 2 methodology, in full")
def methodology() -> dict:
    """Four layers, two dimensions, one explainable score — Tabs 01-07 of
    the corrected workbook, transcribed exactly. Never hard-codes a sample
    number; every classifier/trigger/sub-category/matrix/notch value here
    is the live seed configuration the scoring engine actually runs."""
    catalog_summary = ews_catalog.describe()
    return {
        "methodology_version": ews_catalog.METHODOLOGY_VERSION,
        "layers": [
            {"code": "L1", "name": "Internal Behavioural Intelligence"},
            {"code": "L2", "name": "Credit & Financial Fundamentals"},
            {"code": "L3", "name": "External Intelligence"},
            {"code": "L4", "name": "Graph & Relationship Intelligence"},
        ],
        "signal_inventory": catalog_summary,
        "classifiers": {
            "count": len(clf.CLASSIFIER_DEFINITIONS),
            "definitions": [c.to_dict() for c in clf.CLASSIFIER_DEFINITIONS],
            "sub_categories": {code: {"name": d.name, "layer": d.layer, "rule": d.rule,
                                       "weight_in_layer_dimension": d.weight_in_layer_dimension}
                               for code, d in clf.SUBCATEGORIES.items()},
            "layer_weights": clf.CLASSIFIER_LAYER_WEIGHTS,
            "aggregation": "Worst-of (plus a bounded corroboration uplift) or weighted blend per "
                           "sub-category (Tab 03 Section A), then L2-C x 0.85 + L4-C x 0.15.",
        },
        "triggers": {
            "count": len(trg.TRIGGER_DEFINITIONS),
            "definitions": [t.to_dict() for t in trg.TRIGGER_DEFINITIONS],
            "sub_categories": {code: {"name": d.name, "layer": d.layer, "rule": d.rule,
                                       "weight_in_layer_dimension": d.weight_in_layer_dimension}
                               for code, d in ta_agg.TA_SUBCATEGORIES.items()},
            "layer_weights": ta_agg.TA_LAYER_WEIGHTS,
        },
        "accelerator": {
            "dimension_weights": accel.DIMENSION_WEIGHTS,
            "decay_classes": [{"name": dc.name, "half_life_days": dc.half_life_days,
                               "floor": dc.floor, "sub_categories": dc.sub_categories}
                              for dc in accel.DECAY_CLASSES],
            "formula": "accelerator_multiplier = decay_factor * (1 + SUM(weight_d * (mult_d - 1)))",
        },
        "matrix": matrix.ANCHOR_MATRIX,
        "notches": {
            "keys": nt.NOTCH_KEYS, "criteria": nt.NOTCH_CRITERIA,
            "points_per_notch": nt.POINTS_PER_NOTCH, "net_notch_cap": nt.NET_NOTCH_CAP,
        },
        "combination": {
            "formula": "anchor = matrix[ta_band][classifier_band]; "
                       "final = clamp(anchor + 8 * net_notches, 0, 100); then caps/overrides.",
            "note": "A published 5x5 matrix anchor, then five +/-1 notches (net capped at +/-2), "
                    "then caps — never a multiplication.",
        },
        "reason_codes": {
            "subcategory": reasons.SUBCATEGORY_REASON_TEXT,
            "ews_expected_action": reasons.EWS_BAND_EXPECTED_ACTION,
        },
    }


@router.get("/lineage", summary="Field-level source lineage")
def lineage() -> dict:
    return {"lineage_version": ews_lineage.LINEAGE_VERSION, "fields": ews_lineage.full_lineage()}


# ============================================================= escalation matrix


def _active_escalation_bundle() -> tuple[str, dict, str]:
    """(version, bundle, change_note) of the active escalation matrix, or the
    default bundle if nothing has been seeded/edited yet."""
    from backend.db.engine import get_session
    from backend.models.platform import EarlyWarningEscalationVersion

    try:
        with get_session() as session:
            row = (session.query(EarlyWarningEscalationVersion)
                   .filter_by(is_active=True).order_by(
                       EarlyWarningEscalationVersion.id.desc()).first())
            if row is not None:
                return row.version, row.bundle, row.change_note
    except Exception:  # pragma: no cover - no database configured
        pass
    return "default", esc.default_bundle(), "Seed default — never edited."


@router.get("/escalation-matrix", summary="The escalation ladder, specialist routes and routing matrix")
def escalation_matrix(principal: Principal = RequireEarlyWarningView) -> dict:
    version, bundle, change_note = _active_escalation_bundle()
    return {"version": version, "change_note": change_note, **bundle}


class EscalationMatrixUpdate(BaseModel):
    bundle: dict
    change_note: str = Field(..., min_length=1, max_length=500)


@router.put("/escalation-matrix", summary="Edit the escalation matrix (versioned, audited)")
def update_escalation_matrix(payload: EscalationMatrixUpdate,
                              principal: Principal = RequireEarlyWarningEditEscalationMatrix) -> dict:
    """Every edit creates a NEW version rather than overwriting the active
    one (spec Section AF): a case raised under the old matrix keeps that
    matrix's routing even after this edit takes effect."""
    from backend.db.engine import get_session
    from backend.models.platform import EarlyWarningEscalationVersion

    with get_session() as session:
        session.query(EarlyWarningEscalationVersion).filter_by(is_active=True).update(
            {"is_active": False})
        existing = session.query(EarlyWarningEscalationVersion).count()
        new_version = f"1.0.{existing}"
        row = EarlyWarningEscalationVersion(
            version=new_version, is_active=True, bundle=payload.bundle,
            change_note=payload.change_note, created_by=principal.user_id,
        )
        session.add(row)
        session.flush()
        return {"version": row.version, "change_note": row.change_note,
                "created_by": row.created_by, **row.bundle}


# ================================================================ portfolio


@router.get("", summary="Portfolio overview")
def overview(period: str | None = Query(None),
             principal: Principal = RequireEarlyWarningView) -> dict:
    try:
        return {
            "summary": svc.portfolio_summary(period),
            "trend": svc.portfolio_trend(),
            "top_high_risk": svc.top_high_risk(period, limit=20),
            "available_periods": svc.periods(),
        }
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)


@router.get("/segments", summary="Segment-level Early Warning")
def segments(period: str | None = Query(None),
             principal: Principal = RequireEarlyWarningView) -> dict:
    try:
        return {"period": period or svc.latest_period(), "segments": svc.segment_summary(period)}
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)


_EWS_BANDS = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")


@router.get("/diagnose", summary="Descriptive driver diagnosis over a selected population")
def diagnose(period: str | None = Query(None), band: str = Query("HIGH_PLUS"),
             segment: str | None = Query(None),
             principal: Principal = RequireEarlyWarningView) -> dict:
    """Descriptive, not predictive (spec Section AO): what a selected
    population has in common — the whole book, one exact band, the
    HIGH-or-worse population, or one segment (composable with a band).
    Never used as approval/decline logic."""
    try:
        bm = svc.borrower_month(period)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    if bm.empty:
        return {"population": 0, "drivers": [], "note": "descriptive only, not predictive"}
    if band == "HIGH_PLUS":
        pop = bm[bm["ews_band"].isin(("HIGH", "VERY_HIGH"))]
    elif band in _EWS_BANDS:
        pop = bm[bm["ews_band"] == band]
    else:
        pop = bm
    if segment:
        pop = pop[pop["segment"] == segment]
    if pop.empty:
        return {"population": 0, "drivers": [], "note": "descriptive only, not predictive"}
    driver_counts = pop["dominant_driver"].dropna().value_counts().head(10)
    return {
        "population": int(len(pop)),
        "total_exposure": round(float(pop["exposure"].sum()), 2),
        "drivers": [{"signal": k, "borrower_count": int(v)} for k, v in driver_counts.items()],
        "note": "Descriptive only: what the current high-risk population has in common. "
                "This does not predict who deteriorates next and must not be used as "
                "automated approval or decline logic.",
    }


# ================================================================= borrower


@router.get("/borrower/{customer_id}", summary="Borrower drill-down")
def borrower(customer_id: str, principal: Principal = RequireEarlyWarningView) -> dict:
    try:
        detail = svc.borrower_detail(customer_id)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError:
        raise _not_found(customer_id)
    period = detail["latest"]["snapshot_month"]
    try:
        obs = svc.signal_observations(customer_id, period)
    except EarlyWarningDataNotBuilt:
        obs = None
    detail["fired_signals"] = obs.to_dict(orient="records") if obs is not None and not obs.empty else []
    return detail


@router.get("/borrower/{customer_id}/tree", summary="Layer -> sub-category -> signal drill-down")
def borrower_tree(customer_id: str, principal: Principal = RequireEarlyWarningView) -> dict:
    """The full hierarchy for the dedicated EWS borrower investigation view
    — every node carries its own score, band and Tab 12 reason text."""
    try:
        return svc.layer_tree(customer_id)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError:
        raise _not_found(customer_id)


class EscalateRequest(BaseModel):
    recipient_user_ids: list[int] = Field(default_factory=list)
    recipient_team_ids: list[int] = Field(default_factory=list)
    message: str = Field("", max_length=2000)
    requested_decision: str = Field("", max_length=300)


class InformRequest(BaseModel):
    recipient_user_ids: list[int] = Field(default_factory=list)
    recipient_team_ids: list[int] = Field(default_factory=list)
    message: str = Field("", max_length=2000)


class EscalationNoteRequest(BaseModel):
    case_key: str = Field("", max_length=64)
    requested_decision: str = Field("", max_length=300)


class ActionRequest(BaseModel):
    action: str = Field(..., max_length=300)
    owner_user_id: int | None = None
    due_at: str | None = None
    closing_evidence_required: str = Field("", max_length=500)


def _latest_row_dict(customer_id: str) -> dict:
    try:
        detail = svc.borrower_detail(customer_id)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError:
        raise _not_found(customer_id)
    return detail["latest"]


@router.post("/borrower/{customer_id}/escalate", summary="Escalate a borrower finding")
def escalate(customer_id: str, payload: EscalateRequest,
             principal: Principal = RequireEarlyWarningEscalate) -> dict:
    """Creates/updates the borrower's RiskCase (about='early-warning-v2',
    deduped on borrower+period) and sends one Message via the existing
    Workflow service — never a parallel inbox (spec Section AG)."""
    row = _latest_row_dict(customer_id)
    if not payload.recipient_user_ids and not payload.recipient_team_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                             detail={"error": "no_recipient",
                                     "message": "Escalate needs at least one recipient."})

    from backend.db.engine import get_session
    from backend.early_warning import facts as ff
    from backend.services import workflow as wf

    band = row.get("ews_band", "LOW")
    exposure = float(row.get("exposure", 0.0) or 0.0)

    # The matrix decides the rung, the urgency and who is told in parallel.
    # It has always been able to; nothing consulted it, so an escalation went
    # exactly where the caller said and carried no clock. Severity decides
    # urgency and materiality decides altitude — neither was being applied.
    try:
        pack = ff.borrower(customer_id)
        drivers = [d["code"] for d in pack.figures.get("drivers") or []]
    except Exception:  # noqa: BLE001 - routing must not depend on the pack
        pack, drivers = None, []
    route = esc.route_with_actions(band, exposure, drivers)
    version, _bundle, _note = _active_escalation_bundle()

    with get_session() as session:
        case = case_bridge.upsert_case(session, row)
        session.flush()
        case_id = case.id
        case_key = case.case_key

    title = f"Early Warning escalation: {row.get('customer_name', customer_id)} ({band})"
    body = payload.message or (
        esc.note_for(pack.figures, case_key=case_key,
                     requested_decision=payload.requested_decision)
        if pack is not None else
        f"{row.get('customer_name', customer_id)} scores {row.get('ews_score', 0):.1f} ({band}).")
    view = wf.send(
        object_type="risk_case", object_id=str(case_id), title=title, message=body,
        recipients=payload.recipient_user_ids, teams=payload.recipient_team_ids,
        action="review", priority="high" if band == "VERY_HIGH" else "normal",
        requested_by=principal.user_id,
        # The decision clock, from the matrix's own SLA for this severity.
        due_at=route.get("decision_due"),
    )

    # The case remembers which matrix routed it and what that route was, so a
    # case raised under one version is not later read against another.
    from backend.models.platform import RiskCase

    with get_session() as session:
        found = session.get(RiskCase, case_id)
        if found is not None:
            evidence = dict(found.evidence or {})
            evidence["escalation_version"] = version
            evidence["routing"] = {
                k: v for k, v in route.items()
                if k in ("severity", "exposure_tier", "escalated_to",
                         "escalated_to_roles", "notified", "notified_roles",
                         "ack_sla_days", "decision_sla_days")}
            found.evidence = evidence
            # The FK exists and was never set, so a case could not point back
            # at the message it raised.
            found.workflow_item_id = view.id
            if route.get("decision_due") and not found.due_at:
                found.due_at = route["decision_due"]
            session.commit()

    return {"case_id": case_id, "case_key": case_key,
            "workflow_item": asdict(view), "routing": route,
            "escalation_version": version}


@router.post("/borrower/{customer_id}/inform", summary="Inform on a borrower finding (FYI)")
def inform(customer_id: str, payload: InformRequest,
           principal: Principal = RequireEarlyWarningEscalate) -> dict:
    """FYI only — does not change case severity/state (spec Section AG)."""
    row = _latest_row_dict(customer_id)
    if not payload.recipient_user_ids and not payload.recipient_team_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                             detail={"error": "no_recipient",
                                     "message": "Inform needs at least one recipient."})

    from backend.db.engine import get_session
    from backend.services import workflow as wf

    with get_session() as session:
        case = case_bridge.upsert_case(session, row)
        session.flush()
        case_id = case.id

    band = row.get("ews_band", "LOW")
    title = f"Early Warning FYI: {row.get('customer_name', customer_id)} ({band})"
    body = payload.message or f"{row.get('customer_name', customer_id)} is at {band} this period. For information."
    view = wf.send(
        object_type="risk_case", object_id=str(case_id), title=title, message=body,
        recipients=payload.recipient_user_ids, teams=payload.recipient_team_ids,
        action="fyi", priority="normal", requested_by=principal.user_id,
    )
    return {"case_id": case_id, "workflow_item": asdict(view)}


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/reports/portfolio", summary="Portfolio Word report")
def report_portfolio(period: str | None = Query(None),
                      principal: Principal = RequireEarlyWarningReport) -> Response:
    try:
        data = ews_reports.generate_docx("portfolio", period=period)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    filename = f"early-warning-portfolio-{period or svc.latest_period()}.docx"
    return Response(content=data, media_type=DOCX_MIME,
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/segment/{segment}", summary="Segment Word report")
def report_segment(segment: str, period: str | None = Query(None),
                    principal: Principal = RequireEarlyWarningReport) -> Response:
    try:
        data = ews_reports.generate_docx("segment", segment, period=period)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                             detail={"error": "segment_not_found", "message": segment})
    filename = f"early-warning-segment-{segment.replace(' ', '-').lower()}.docx"
    return Response(content=data, media_type=DOCX_MIME,
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/borrower/{customer_id}", summary="Borrower Word report")
def report_borrower(customer_id: str, principal: Principal = RequireEarlyWarningReport) -> Response:
    try:
        data = ews_reports.generate_docx("borrower", customer_id)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError:
        raise _not_found(customer_id)
    filename = f"early-warning-{customer_id}.docx"
    return Response(content=data, media_type=DOCX_MIME,
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class MultiBorrowerReportRequest(BaseModel):
    customer_ids: list[str] = Field(..., min_length=1, max_length=200)


@router.post("/reports/borrowers", summary="Multi-borrower Word report")
def report_multi_borrower(payload: MultiBorrowerReportRequest,
                           principal: Principal = RequireEarlyWarningReport) -> Response:
    try:
        data = ews_reports.generate_docx("multi_borrower", customer_ids=payload.customer_ids)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                             detail={"error": "no_borrowers_found", "message": str(exc)})
    filename = f"early-warning-{len(payload.customer_ids)}-borrowers.docx"
    return Response(content=data, media_type=DOCX_MIME,
                     headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/borrower/{customer_id}/action", summary="Record an action against the case")
def record_action(customer_id: str, payload: ActionRequest,
                   principal: Principal = RequireEarlyWarningRecordAction) -> dict:
    """Records the action as a Comment on the case (spec Section BF/AY) — no
    parallel action-log table, and no existing escalation Workflow item is
    required first: an analyst may record an action on a case that was
    never formally escalated."""
    row = _latest_row_dict(customer_id)
    from backend.db.engine import get_session
    from backend.services import workflow as wf

    with get_session() as session:
        case = case_bridge.upsert_case(session, row)
        session.flush()
        case_id = case.id

    body = f"Action recorded: {payload.action}"
    if payload.owner_user_id:
        body += f" (owner user {payload.owner_user_id})"
    if payload.due_at:
        body += f", due {payload.due_at}"
    if payload.closing_evidence_required:
        body += f". Closing evidence required: {payload.closing_evidence_required}"

    comment = wf.comment(object_type="risk_case", object_id=str(case_id), body=body,
                          author_id=principal.user_id)

    # The comment is the human-readable record; these are the fields that make
    # the action a control. Flattening the owner, the due date and the closing
    # evidence into prose meant none of them could be queried — no "open
    # actions", no "overdue", and no way to check a case closed on its
    # evidence rather than on somebody's say-so.
    from backend.models.platform import RiskCase

    with get_session() as session:
        found = session.get(RiskCase, case_id)
        if found is not None:
            if payload.owner_user_id:
                found.owner_id = payload.owner_user_id
            if payload.due_at:
                try:
                    from datetime import datetime

                    found.due_at = datetime.fromisoformat(
                        str(payload.due_at).replace("Z", "+00:00"))
                except ValueError:
                    logger.info("Unparseable due date on an action: %r",
                                payload.due_at)
            evidence = dict(found.evidence or {})
            recorded = list(evidence.get("actions") or [])
            recorded.append({
                "action": payload.action,
                "owner_user_id": payload.owner_user_id,
                "due_at": payload.due_at,
                "closing_evidence_required": payload.closing_evidence_required,
                "recorded_by": principal.user_id,
            })
            evidence["actions"] = recorded
            found.evidence = evidence
            session.commit()

    return {"case_id": case_id, "action": payload.action, "comment": comment}


@router.get("/borrower/{customer_id}/actions",
            summary="The governed actions indicated for this borrower")
def borrower_actions(customer_id: str,
                     principal: Principal = RequireEarlyWarningView) -> dict:
    """What the action library recommends, keyed to this obligor's drivers.

    Ranked worst driver first, with the one to take if only one can be taken
    chosen by reversibility and cost rather than by the score of the node it
    came from.
    """
    from backend.early_warning import actions as act
    from backend.early_warning import facts as ff

    try:
        pack = ff.borrower(customer_id)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError:
        raise _not_found(customer_id)

    drivers = pack.figures.get("drivers") or []
    recommended = act.for_drivers([d["code"] for d in drivers])
    first = act.single_highest_value(recommended)
    return {
        "customer_id": customer_id,
        "customer_name": pack.figures.get("customer_name"),
        "period": pack.period,
        "drivers": drivers,
        "actions": [a.to_dict() for a in recommended],
        "priority_action": first.to_dict() if first else None,
        "routing": esc.route_with_actions(
            pack.figures["ews_band"], float(pack.figures["exposure"]),
            [d["code"] for d in drivers]),
    }


@router.post("/borrower/{customer_id}/escalation-note",
             summary="Draft the escalation note")
def escalation_note(customer_id: str, payload: EscalationNoteRequest,
                    principal: Principal = RequireEarlyWarningEscalate) -> dict:
    """A draft, never a send.

    The note is assembled from the borrower's own facts — position, driver
    with its score, corroboration, recommendation with owner and evidence,
    and the decision requested. Nothing in it is a figure the pack did not
    carry, because an escalation note is the last place to introduce a
    number nobody can trace.
    """
    from backend.early_warning import facts as ff

    try:
        pack = ff.borrower(customer_id)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    except KeyError:
        raise _not_found(customer_id)

    return {
        "customer_id": customer_id,
        "note": esc.note_for(pack.figures, case_key=payload.case_key,
                             requested_decision=payload.requested_decision),
        "routing": esc.route_with_actions(
            pack.figures["ews_band"], float(pack.figures["exposure"]),
            [d["code"] for d in pack.figures.get("drivers") or []]),
    }
