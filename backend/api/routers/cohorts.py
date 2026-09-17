"""Cohorts: the handoff object, the customer list, and what people keep.

Every route here recheckes authorisation. Knowing a snapshot id is not
permission to read one, and the four moments a cohort changes hands — created,
read, exported, reopened — are four separate checks, because a person's access
can be withdrawn between any two of them.

A refusal is worded exactly like an absence. Saying "that exists but is not
yours" confirms somebody else's customer list exists, which is itself a
disclosure.

Nothing here executes anything on a customer. These routes create records of
what was looked at.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, current_principal
from backend.db.engine import get_session
from backend.retail import cohort as ch
from backend.retail import cohort_360
from backend.retail import episode_answers as ea
from backend.retail import episode_measures as em
from backend.retail import episodes as ep
from backend.retail import investigation_store as store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retail/cohorts", tags=["retail cohorts"])
saved_router = APIRouter(prefix="/retail/investigations",
                         tags=["retail investigations"])
# The prompts live under their own prefix, not under /retail/investigations.
#
# They were there first, and `/retail/investigations/{saved_id}` is declared
# above them — so FastAPI matched "chips" as a saved-investigation id and
# answered 404 for every request. The page then rendered with no prompt chips
# at all and nothing anywhere said why, which is precisely the failure a
# browser run exists to catch and an API test would not have.
episodes_router = APIRouter(prefix="/retail/episodes",
                            tags=["retail investigations"])

Caller = Depends(current_principal)


def _team(principal: Principal) -> int | None:
    return getattr(principal, "team_id", None)


def _refused(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _read_snapshot(session: Any, snapshot_id: str, principal: Principal,
                   *, action: str) -> Any:
    try:
        return ch.read(session, snapshot_id, user_id=principal.user_id,
                       role=str(principal.role), team_id=_team(principal),
                       action=action)
    except ch.NotPermitted as denied:
        raise _refused(str(denied)) from denied


def _bundle_id() -> str:
    from backend.retail import bundle as bnd

    return bnd.current_id()


# ---------------------------------------------------------------------------


class FromStepIn(BaseModel):
    case_id: str = Field(..., max_length=16)
    step: str = Field("S0", max_length=4)
    month: str = Field("", max_length=16)
    thread_id: str = Field("", max_length=64)
    occurrence_id: str = Field("", max_length=64)
    purpose: str = Field("retail investigation", max_length=120)


class SelectIn(BaseModel):
    customer_ids: list[str] = Field(default_factory=list)
    #: flagged_only | all_authorised_facilities
    facility_mode: str = Field("", max_length=40)


class SaveIn(BaseModel):
    title: str = Field("", max_length=240)
    pinned: bool = False


class NoteIn(BaseModel):
    body: str = Field(..., max_length=8000)
    subject_id: str = Field("", max_length=64)


@router.post("/from-step", summary="Freeze a thread step's customers")
def from_step(payload: FromStepIn, principal: Principal = Caller
              ) -> dict[str, Any]:
    """Create the immutable cohort behind one step, and its draft investigation.

    The draft is written here rather than on Save, because the failure it
    prevents is a reader losing a list by closing a tab.
    """
    case_id = payload.case_id.upper()
    episode = ep.by_id(case_id)
    if episode is None:
        raise _refused(f"No story {payload.case_id!r} is published here.")
    step = payload.step.upper() or "S0"
    if step not in ch.STEPS:
        raise HTTPException(status_code=400,
                            detail=f"step must be one of {ch.STEPS}")

    found = ea.scope(payload.month, case_id, step)
    if not found.get("available"):
        raise _refused(found.get("because") or "nothing to export")

    card = em.headline(found["as_of"], case_id)
    with get_session() as session:
        snapshot = ch.create(session, ch.Draft(
            case_id=case_id,
            occurrence_id=payload.occurrence_id or case_id,
            thread_id=payload.thread_id,
            step_id=step,
            source_as_of=found["as_of"],
            source_bundle_id=_bundle_id(),
            versions={"episodes": ep.config_version(),
                      "metrics": em.mc.VERSION,
                      "cohort": ch.VERSION},
            metric_definition_ids=found["metric_definition_ids"],
            root_predicate=ep.predicate(case_id),
            predicate=found["predicate"],
            customer_ids=found["customers"],
            facility_ids=found["facilities"],
            visited_steps=[s for s in ch.STEPS
                           if s <= step and s in ch.STEPS],
            owner_user_id=principal.user_id,
            team_id=_team(principal),
            purpose=payload.purpose,
            totals=found["totals"],
        ))
        draft = store.draft_for(
            session, snapshot,
            title=f"{episode.title} — {step}",
            issue=episode.card_measure,
            segment=episode.pocket_label,
            odr=store.not_yet_observed(
                window=em.mc.definition(episode.headline_metric)["window"]),
            owner_user_id=principal.user_id,
            team_id=_team(principal))
        session.commit()
        return {
            "snapshot": ch.view(snapshot),
            "saved": store.view(draft),
            "card": {k: card.get(k) for k in
                     ("title", "card_measure", "severity", "affected",
                      "eligible", "as_of")},
        }


@router.get("/{snapshot_id}", summary="One cohort, without its identifiers")
def detail(snapshot_id: str, principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        snapshot = _read_snapshot(session, snapshot_id, principal,
                                  action="read")
        return {"snapshot": ch.view(snapshot),
                "totals": cohort_360.totals(snapshot)}


@router.get("/{snapshot_id}/customers", summary="The imported customer list")
def customers(snapshot_id: str, offset: int = Query(0, ge=0),
              limit: int = Query(50, ge=1, le=500),
              context_facilities: bool = True,
              principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        snapshot = _read_snapshot(session, snapshot_id, principal,
                                  action="read")
        return cohort_360.customers(
            snapshot, offset=offset, limit=limit,
            with_context_facilities=context_facilities)


@router.post("/{snapshot_id}/select", summary="Narrow to a ticked subset")
def select(snapshot_id: str, payload: SelectIn,
           principal: Principal = Caller) -> dict[str, Any]:
    """A selection, or a switch to all of a customer's facilities.

    Both write a NEW snapshot with recomputed counts rather than a flag on the
    old one, because both change the financial baseline the investigation has
    been carrying.
    """
    with get_session() as session:
        parent = _read_snapshot(session, snapshot_id, principal,
                                action="select")
        mode = payload.facility_mode or parent.facility_mode
        wanted = [str(c) for c in payload.customer_ids] or list(
            parent.customer_ids or [])

        data = em.frame(parent.source_as_of)
        held = data[data["customer_id"].astype(str).isin(set(wanted))]
        if mode == ch.ALL_FACILITIES:
            facilities = sorted(set(held["facility_id"].astype(str)))
        else:
            flagged = {str(f) for f in (parent.facility_ids or [])}
            facilities = sorted(
                set(held["facility_id"].astype(str)) & flagged)
        rows = held[held["facility_id"].astype(str).isin(set(facilities))]
        totals = {
            "gca_sar": round(float(rows["gross_carrying_amount_sar"].sum()), 2),
            "ead_sar": round(float(rows["ead_base_sar"].sum()), 2),
            "ecl_weighted_sar": round(float(rows["ecl_weighted_sar"].sum()), 2),
        }
        try:
            child = ch.select_subset(
                session, parent, customer_ids=wanted,
                facility_ids=facilities, facility_mode=mode,
                owner_user_id=principal.user_id, totals=totals)
        except ValueError as bad:
            raise HTTPException(status_code=400, detail=str(bad)) from bad
        draft = store.draft_for(session, child,
                                title=f"{parent.case_id} — selection",
                                issue=parent.case_id,
                                owner_user_id=principal.user_id,
                                team_id=_team(principal))
        session.commit()
        return {"snapshot": ch.view(child), "saved": store.view(draft),
                "totals": totals}


@saved_router.get("/recent", summary="Recent investigations")
def recent(limit: int = Query(12, ge=1, le=50),
           principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        rows = store.recent(session, user_id=principal.user_id,
                            role=str(principal.role), team_id=_team(principal),
                            limit=limit)
        return {"rows": [store.view(r, note_rows=store.notes(s := session,
                                                             r.saved_id))
                         for r in rows]}


@saved_router.get("/{saved_id}", summary="Reopen a saved investigation")
def reopen(saved_id: str, version: int | None = None,
           principal: Principal = Caller) -> dict[str, Any]:
    """The saved list, its notes and the snapshot it was saved against.

    The snapshot is read, never re-derived. A saved investigation that re-ran
    its predicate would show a population that is not the one somebody saved,
    and the note written under it would no longer be supported by the figures
    above it.
    """
    with get_session() as session:
        try:
            row = store.read(session, saved_id, user_id=principal.user_id,
                             role=str(principal.role), team_id=_team(principal),
                             version=version)
        except store.NotPermitted as denied:
            raise _refused(str(denied)) from denied
        snapshot = _read_snapshot(session, row.snapshot_id, principal,
                                  action="reopen")
        return {
            "saved": store.view(row, note_rows=store.notes(session, saved_id),
                                snapshot=snapshot),
            "versions": [{"version": v.version, "snapshot_id": v.snapshot_id,
                          "customer_count": v.customer_count,
                          "created_at": v.created_at.isoformat()
                          if v.created_at else None}
                         for v in store.versions(session, saved_id)],
            "totals": cohort_360.totals(snapshot),
        }


@saved_router.post("/{saved_id}/save", summary="Name and pin an investigation")
def save(saved_id: str, payload: SaveIn,
         principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        try:
            row = store.read(session, saved_id, user_id=principal.user_id,
                             role=str(principal.role), team_id=_team(principal))
        except store.NotPermitted as denied:
            raise _refused(str(denied)) from denied
        store.save(session, row, title=payload.title, pinned=payload.pinned)
        session.commit()
        return {"saved": store.view(row,
                                    note_rows=store.notes(session, saved_id))}


@saved_router.post("/{saved_id}/refresh", summary="Version against the latest")
def refresh(saved_id: str, principal: Principal = Caller) -> dict[str, Any]:
    """Re-measure against the current book as a NEW version.

    The saved version is left exactly as it was. That is the difference
    between "what does this say now" and "what did this say when I saved it",
    and both have to have answers.
    """
    with get_session() as session:
        try:
            row = store.read(session, saved_id, user_id=principal.user_id,
                             role=str(principal.role), team_id=_team(principal))
        except store.NotPermitted as denied:
            raise _refused(str(denied)) from denied
        previous = _read_snapshot(session, row.snapshot_id, principal,
                                  action="refresh")
        found = ea.scope("", previous.case_id, previous.step_id or "S0")
        if not found.get("available"):
            raise _refused(found.get("because") or "nothing to refresh to")
        newest = ch.create(session, ch.Draft(
            case_id=previous.case_id,
            occurrence_id=previous.occurrence_id,
            thread_id=previous.thread_id,
            step_id=previous.step_id,
            source_as_of=found["as_of"],
            source_bundle_id=_bundle_id(),
            versions=dict(previous.versions or {}),
            metric_definition_ids=found["metric_definition_ids"],
            root_predicate=dict(previous.root_predicate or {}),
            predicate=found["predicate"],
            customer_ids=found["customers"],
            facility_ids=found["facilities"],
            visited_steps=list(previous.visited_steps or []),
            owner_user_id=principal.user_id,
            team_id=_team(principal),
            purpose=previous.purpose,
            totals=found["totals"],
        ))
        made = store.refresh(session, row, newest)
        session.commit()
        return {
            "saved": store.view(made),
            "previous": {"version": row.version,
                         "snapshot_id": row.snapshot_id,
                         "customer_count": row.customer_count},
            "note": ("The earlier version is unchanged and still readable at "
                     "its own version number."),
        }


@saved_router.post("/{saved_id}/notes", summary="Add a note")
def add_note(saved_id: str, payload: NoteIn,
             principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        try:
            row = store.read(session, saved_id, user_id=principal.user_id,
                             role=str(principal.role), team_id=_team(principal))
        except store.NotPermitted as denied:
            raise _refused(str(denied)) from denied
        note = store.add_note(
            session, row, body=payload.body,
            author_user_id=principal.user_id,
            author_name=str(getattr(principal, "name", "") or ""),
            subject_id=payload.subject_id)
        session.commit()
        return {"note": store.note_view(note)}


@saved_router.get("/{saved_id}/notes", summary="Notes, with their history")
def list_notes(saved_id: str, history: bool = False,
               principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        try:
            store.read(session, saved_id, user_id=principal.user_id,
                       role=str(principal.role), team_id=_team(principal))
        except store.NotPermitted as denied:
            raise _refused(str(denied)) from denied
        return {"rows": [store.note_view(n) for n in
                         store.notes(session, saved_id,
                                     include_history=history)]}


@router.post("/{snapshot_id}/workbook.xlsx",
             summary="The evidence workbook for one step")
def workbook(snapshot_id: str, principal: Principal = Caller) -> Any:
    """Thirteen sheets, capped at the steps the reader actually visited.

    The export is recorded whether or not it succeeded. A refused download and
    a failed one are both things somebody will later need to explain, and a log
    that only records successes cannot answer "who tried".
    """
    from fastapi.responses import Response

    from backend.models.platform import ExportRecord
    from backend.retail import investigation_workbook as wb

    with get_session() as session:
        snapshot = _read_snapshot(session, snapshot_id, principal,
                                  action="export")
        saved = store.load_by_snapshot(session, snapshot_id)
        notes = ([store.note_view(n)
                  for n in store.notes(session, saved.saved_id)]
                 if saved is not None else [])
        payload, manifest = wb.build(
            snapshot, notes=notes, saved_id=saved.saved_id if saved else "",
            user=str(principal.user_id or ""),
            permitted_fields=list(snapshot.permitted_fields or []))
        session.add(ExportRecord(
            kind="investigation_workbook",
            object_type="cohort_snapshot", object_id=snapshot_id,
            user_id=principal.user_id, role=str(principal.role),
            status="allowed", authorization=f"role:{principal.role}",
            filename=f"{snapshot_id}.xlsx",
            content_hash=manifest["content_hash"],
            size_bytes=manifest["size_bytes"],
            row_count=manifest["facility_count"],
            datasets=[em.BOOK], detail=manifest))
        session.commit()

    return Response(
        content=payload,
        media_type=("application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"),
        headers={
            "Content-Disposition":
                f'attachment; filename="{snapshot_id}.xlsx"',
            "X-Content-Hash": manifest["content_hash"],
            "X-Visited-Steps": ",".join(manifest["visited_steps"]),
        })


@router.get("/{snapshot_id}/whatif", summary="The What-If landing scope")
def whatif_scope(snapshot_id: str,
                 principal: Principal = Caller) -> dict[str, Any]:
    """The unchanged baseline and the reconciliation that gates simulation."""
    from backend.retail import cohort_whatif

    with get_session() as session:
        snapshot = _read_snapshot(session, snapshot_id, principal,
                                  action="read")
        return cohort_whatif.handoff(snapshot)


@router.post("/{snapshot_id}/to-whatif", summary="Export the scope to What-If")
def to_whatif(snapshot_id: str, principal: Principal = Caller
              ) -> dict[str, Any]:
    """Write the What-If selection, refusing if the baseline does not agree.

    The refusal is the point. A scenario run on a cohort that is not the one
    the reader selected produces a plausible number that answers a question
    nobody asked, and nothing in the result would show it.
    """
    from backend.retail import cohort_whatif

    with get_session() as session:
        snapshot = _read_snapshot(session, snapshot_id, principal,
                                  action="export")
        found = cohort_whatif.handoff(snapshot)
        if not found["may_simulate"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": ("The imported scope does not reconcile with "
                                "the investigation it came from, so it is not "
                                "handed to What-If."),
                    "reconciliation": found["reconciliation"],
                    "stale_bundle": found.get("stale_bundle", ""),
                })
        selection = cohort_whatif.to_selection(
            snapshot, created_by=str(principal.user_id or ""))
        return {"selection_id": selection.selection_id, **found}


@episodes_router.get("/{case_id}/chips", summary="The five prompts for a story")
def chips(case_id: str, visited: str = "",
          principal: Principal = Caller) -> dict[str, Any]:
    """The prompts above the composer, with what has been visited.

    Served rather than hardcoded in the interface for the reason the whole
    episode config is generated: the prompts are the specification's own
    sentences, and a second copy of them in TypeScript is a second place for
    them to stop matching what the backend actually answers.
    """
    episode = ep.by_id(case_id.upper())
    if episode is None:
        raise _refused(f"No story {case_id!r} is published here.")
    seen = [s.strip().upper() for s in visited.split(",") if s.strip()]
    return {"case_id": episode.case_id, "title": episode.title,
            "countercheck": episode.countercheck,
            "rows": ea.chips(episode.case_id, seen)}
