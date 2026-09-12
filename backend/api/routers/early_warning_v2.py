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
from typing import Any
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
    layers as ews_layers,
    lineage as ews_lineage,
    matrix,
    notches as nt,
    reasons,
    reports as ews_reports,
    triggers_v2 as trg,
    v2_service as svc,
)
from backend.early_warning.conversation import progress as ews_progress
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
        "layers": [{"code": entry.code, "name": entry.name}
                   for entry in ews_layers.LAYERS],
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


def _teams_for_route(route: dict) -> tuple[list[int], list[str]]:
    """The team ids behind a route's rungs, and the rungs that have none.

    Both halves are returned: a partial directory should still route where
    it can, and should say plainly which rung it could not reach rather than
    failing as though nothing were configured.
    """
    from backend.db.engine import get_session
    from backend.models.platform import Team

    codes = [str(c) for c in (route.get("escalated_to") or [])]
    codes += [str(c) for c in (route.get("notified") or [])]
    wanted = {esc.team_slug(code): code for code in dict.fromkeys(codes)}
    if not wanted:
        return [], []
    with get_session() as session:
        rows = session.query(Team).filter(Team.name.in_(list(wanted))).all()
        found = {str(t.name): int(t.id) for t in rows}
    ids = [found[name] for name in wanted if name in found]
    missing = [code for name, code in wanted.items() if name not in found]
    return ids, missing


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

    # Who the matrix says decides. Resolved from the rung rather than
    # supplied by the caller: an escalation whose recipient is chosen by
    # whoever raised it is not routed, it is addressed, and the matrix's
    # whole purpose is that severity and materiality decide the altitude.
    #
    # A caller may still name people — a specific colleague alongside the
    # rung is an ordinary thing to want — and those are added, never
    # substituted.
    teams = list(payload.recipient_team_ids or [])
    resolved, missing = _teams_for_route(route)
    teams += [t for t in resolved if t not in teams]
    if not teams and not payload.recipient_user_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "no_recipient",
                    "message": (
                        "The matrix routes this to "
                        + ", ".join(esc.role_of(c) for c in missing)
                        + ", and this deployment has no team for "
                        + ("them" if len(missing) != 1 else "that role")
                        + ". Create "
                        + ", ".join(sorted(esc.team_slug(c) for c in missing))
                        + " and add its members, or name a recipient "
                        + "explicitly."),
                    "routed_to": list(missing),
                    "expected_teams": sorted(esc.team_slug(c) for c in missing)})

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
        recipients=payload.recipient_user_ids, teams=teams,
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


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    period: str | None = None
    customer_id: str | None = Field(None, max_length=64)
    #: The screen the question was asked from — the band filter, the level,
    #: the selected segment. Navigation context, kept apart from the
    #: analytical summary because a screen rebuilt from prose is sometimes
    #: wrong and the client already knows exactly where it is.
    ui_state: dict[str, Any] | None = None
    #: The thread's analytical context, returned by the previous turn.
    rolling_summary: dict[str, Any] | None = None
    thread_id: str | None = Field(None, max_length=64)
    mode: str = Field("standard", pattern="^(standard|deep)$")
    #: A key the client chose for THIS turn, so it can watch the turn happen.
    #: Optional: a caller that does not send one simply gets no progress
    #: document, and the answer is identical either way.
    turn_key: str | None = Field(None, max_length=64)


class ProgressRequest(BaseModel):
    turn_key: str = Field(..., min_length=1, max_length=64)


@router.post("/ask", summary="Ask the Early Warning domain a question")
def ask_early_warning(payload: AskRequest,
                      principal: Principal = RequireEarlyWarningView) -> dict:
    """The screen's own chat, through the governed conversational pipeline.

    The pipeline decides WHO OWNS the question before it plans anything, so
    a question another CreditProbe functionality owns is redirected with
    alternatives rather than approximated from whichever Early Warning
    fields happen to fit. That gate is the reason this endpoint cannot
    quietly answer a portfolio question with the three hundred obligors it
    scores.

    The response keeps the shape the screen already renders. What is new is
    additive: the routing decision, the stages that ran, the budget spent,
    and the rolling summary to hand back on the next turn.
    """
    from backend.early_warning.conversation import live as ews_live
    from backend.early_warning.conversation import pipeline as ews_pipeline

    ui_state = dict(payload.ui_state or {})
    if payload.customer_id:
        ui_state.setdefault("customer_id", payload.customer_id)
    if payload.period:
        ui_state.setdefault("period", payload.period)

    # The turn writes its events where `/ask/progress` can read them while it
    # is still running. An observer and nothing more: the pipeline decides
    # nothing differently for having one, and a client that sent no key gets
    # the same answer by the same path.
    watch = ews_live.open_turn(payload.turn_key or "", principal)
    try:
        turn = ews_pipeline.answer(
            payload.question,
            thread_id=payload.thread_id or "",
            ui_state=ui_state,
            rolling_summary=payload.rolling_summary,
            mode=payload.mode,
            permissions={"can_read": True, "role": principal.role},
            on_event=(lambda event: ews_live.record(watch, event))
            if watch else None,
        )
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    finally:
        # However the turn ended, it is no longer live. A watcher that polls
        # after this sees the finished document rather than a panel that
        # animates forever.
        ews_live.close_turn(watch)

    answer = dict(turn.answer)
    packet = turn.packet
    return {
        **answer,
        "facts": (packet.primary.to_dict()
                  if packet is not None and packet.primary else {}),
        # What the turn actually did, so the Trace can show it rather than
        # describe it.
        "routing": turn.selection,
        "stages": turn.stages,
        "budget": turn.budget,
        "rolling_summary": (turn.rolling_summary.to_dict()
                             if turn.rolling_summary else {}),
        "request_id": turn.request_id,
        # Which stage was served by a model and which by the deterministic
        # implementation, and every call that was actually made. A trace that
        # named the models without this could not be checked.
        "engines": turn.engines,
        "model_calls": [dict(c) for c in turn.model_calls],
        # Every attempt, including one that was charged and then failed. The
        # ledger's charged count and the number of stages a model served are
        # different figures, and a trace that reported only the second leaves
        # the first looking like an error.
        "model_attempts": [dict(c) for c in turn.model_attempts],
        "result_packet": (
            {"diagnostics": packet.diagnostics,
             "provenance": packet.provenance,
             "coverage": packet.coverage,
             "governed_actions": packet.governed_actions,
             "escalation": packet.escalation}
            if packet is not None else {}),
        # The finished progress panel, so the client does not have to race a
        # last poll to render the completed history it has been showing.
        "progress": ews_progress.build(
            turn.events, turn_id=payload.turn_key or turn.request_id,
            active=False).to_dict(),
    }


@router.post("/ask/progress", summary="What this turn is doing now")
def ask_progress(payload: ProgressRequest,
                 principal: Principal = RequireEarlyWarningView) -> dict:
    """The live progress panel for a turn that is still running.

    Polled while `/ask` is in flight, on the same cadence the Cockpit's
    working indicator uses. Deliberately the smallest call in this router:
    the steps, their statuses and their timings, and nothing else.

    An unknown key is not an error. The turn may have finished and expired, or
    this worker may never have run it, and in both cases the client shows a
    plain working state — which is what it would have shown anyway.

    Every label in the response comes from the governed mapping. There is no
    model in this path, no additional call is made to produce it, and nothing
    a model wrote can reach it.
    """
    from backend.early_warning.conversation import live as ews_live

    found = ews_live.read(payload.turn_key or "", principal)
    if found is None:
        return {"watching": False, "version": ews_progress.CONTRACT_VERSION}
    return {"watching": True, **found}


@router.get("/ask/vocabulary", summary="The progress vocabulary, in full")
def ask_vocabulary(principal: Principal = RequireEarlyWarningView) -> dict:
    """Every sentence the progress panel can say.

    Published so the wording is reviewable in one place rather than being
    discovered by watching turns, and so a test can assert that no internal
    model vocabulary has leaked into it.
    """
    del principal
    return {
        "version": ews_progress.CONTRACT_VERSION,
        "steps": [{"key": key, "label": ews_progress.LABELS[key]}
                  for key in ews_progress.STEP_ORDER],
        "notes": [{"key": key, "label": ews_progress.LABELS[key]}
                  for key in (ews_progress.ROUTING, ews_progress.CLARIFYING,
                               ews_progress.REFINING, ews_progress.DEFERRED,
                               ews_progress.FALLBACK,
                               ews_progress.STOPPED_STEP)],
        "analyses": dict(ews_progress.ANALYSIS_LABELS),
        "statuses": [ews_progress.WAITING, ews_progress.ACTIVE,
                     ews_progress.DONE, ews_progress.NOTE,
                     ews_progress.STOPPED],
    }


@router.get("/models", summary="Which model serves which conversational stage")
def ews_models(principal: Principal = RequireEarlyWarningView) -> dict:
    """The stage-to-model routing, resolved against the live configuration.

    Every row says which family the stage asks for, which configured role
    carries it, which model that role currently resolves to and whether that
    model is in the family the stage asked for. A deployment that configured
    one shared model sees that here rather than reading a diagram that says
    otherwise.
    """
    from backend.early_warning.conversation import seam as ews_seam
    from backend.llm import public_health

    del principal
    return {
        "provider_configured": ews_seam.provider_available(),
        "provider": public_health(),
        "stages": ews_seam.routing(),
        "note": ("Where no provider is configured every stage is served by "
                 "its deterministic implementation, the engine says so, and "
                 "the turn's model-call count is zero."),
    }


@router.get("/grain", summary="The Early Warning data-grain package")
def ews_grain(question: str = "", group: str = "",
              principal: Principal = RequireEarlyWarningView) -> dict:
    """What a planner is given instead of the data.

    The grain, the published periods, every field with its definition and
    its MEASURED coverage, the groupings, and a bounded permission-scoped
    sample. Not the rows: twenty months of three hundred obligors across two
    and a half thousand columns is a bill rather than a context, and the
    values come back through validated execution where they can be checked.

    `group` narrows the field dictionary to one group — the signal inventory
    alone is two thousand three hundred entries, and a reader looking for the
    matrix fields should not have to download it to find them. The counts and
    the coverage always describe the whole domain, so a narrowed response
    still says how much of it is being shown.
    """
    from backend.early_warning import grain as ews_grain_mod

    try:
        package = ews_grain_mod.build(
            question, permissions={"role": principal.role})
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    out = package.to_dict()
    if group:
        dictionary = dict(out.get("field_dictionary") or {})
        groups = dictionary.get("groups") or {}
        matched = {name: members for name, members in groups.items()
                   if name.lower() == group.lower()}
        dictionary["groups"] = matched
        dictionary["showing_group"] = group
        dictionary["group_sizes"] = {name: len(members)
                                     for name, members in groups.items()}
        out["field_dictionary"] = dictionary
    return out


@router.get("/functionality", summary="Which CreditProbe functionality owns what")
def ews_functionality(question: str = "",
                      principal: Principal = RequireEarlyWarningView) -> dict:
    """The catalogue, and — when a question is supplied — who owns it.

    Capability metadata only. No other functionality's data travels with it,
    and the selection this returns is the same one the pipeline gates on.
    """
    from backend.early_warning import functionality as ews_fn

    del principal
    out: dict[str, Any] = {"catalogue": ews_fn.describe_all()}
    if question:
        out["selection"] = ews_fn.select(question).to_dict()
    return out


@router.get("/suggestions", summary="Starting questions for the Early Warning chat")
def ask_suggestions(principal: Principal = RequireEarlyWarningView) -> dict:
    """Questions this domain can genuinely answer, not a wish list."""
    from backend.early_warning import ask as ews_ask

    return {"questions": ews_ask.suggestions()}


@router.get("/levels", summary="The fields the book can be grouped by")
def levels(principal: Principal = RequireEarlyWarningView) -> dict:
    """The grouping is not fixed to segment: any attribute that partitions
    the book can become the level the screen renders at."""
    from backend.early_warning import facts as ff

    return {"levels": [{"field": k, "label": v}
                       for k, v in ff.LEVEL_FIELDS.items()]}


@router.get("/level/{field_name}", summary="The book grouped by one field")
def level(field_name: str, period: str | None = Query(None),
          principal: Principal = RequireEarlyWarningView) -> dict:
    from backend.early_warning import compose as cp
    from backend.early_warning import facts as ff

    try:
        pack = ff.level(field_name, period)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                             detail={"error": "unknown_level", "message": field_name})
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    written = cp.compose(pack)
    return {"level": field_name, "label": pack.figures["level_label"],
            "period": pack.period, "rows": pack.rows,
            "reading": {"direct": written.direct,
                        "interpretation": written.interpretation,
                        "points": written.points,
                        "follow_ups": written.follow_ups},
            "caveats": pack.caveats}


@router.get("/insight", summary="The portfolio reading, in prose")
def insight(period: str | None = Query(None),
            principal: Principal = RequireEarlyWarningView) -> dict:
    """What the portfolio figures mean, rather than a restatement of them."""
    from backend.early_warning import compose as cp
    from backend.early_warning import facts as ff

    try:
        pack = ff.portfolio(period)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    written = cp.compose(pack)
    return {"period": pack.period, "direct": written.direct,
            "interpretation": written.interpretation,
            "points": written.points, "follow_ups": written.follow_ups,
            "caveats": written.caveats}


@router.get("/reports/segments", summary="All-segment Word report")
def report_all_segments(period: str | None = Query(None),
                        principal: Principal = RequireEarlyWarningReport) -> Response:
    """Every segment, each on its own terms.

    Distinct from the portfolio report's single segment table, which answers
    "which is worst" and nothing else: this gives each segment its own
    reading, obligor list and chart, because whether a segment's average
    reflects a common condition or one or two names decides whether the
    response is a sector action or a workout.
    """
    try:
        data = ews_reports.generate_docx("all_segments", period=period)
    except EarlyWarningDataNotBuilt as exc:
        raise _not_built(exc)
    return Response(content=data, media_type=DOCX_MIME,
                     headers={"Content-Disposition":
                              'attachment; filename="early-warning-all-segments.docx"'})


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
