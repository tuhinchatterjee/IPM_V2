"""
The Assurance API. §204.

    §204: "Enforce object permissions."

Which is the whole of this file's design. Every route resolves a `Viewer`
from the caller, and every record it touches goes through `access.may_read`
before any of its content is serialised. There is no route that returns a
record without that check, and no route that returns a DIFFERENT error for
"not yours" than for "does not exist" — a caller who could tell those apart
could enumerate the estate's Investigation ids by watching which refusals
came back 403 and which came back 404.

The re-run route, and the two things it will not do
-----------------------------------------------------
    §204: "authorized only and cost-confirmed where live calls are required"

`POST .../assurance/rerun` is administrator-only, and it refuses unless the
caller has explicitly confirmed the cost. It does not itself call a provider:
it records the intent and returns what a re-run would cost and compare. A
route that quietly spent a bank's tokens because somebody clicked a button
labelled "compare" is the failure this shape prevents.

Why the reviews list has no page of its own here
--------------------------------------------------
It lives under `/intelligence/investigation-reviews` because §186 makes it an
AI Intelligence Studio tab, and the Studio's routes are already gathered
there behind the Studio's permissions. This file holds the per-Investigation
routes, which any authorized user of an Investigation may reach.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAdmin, RequireCommenter
from backend.assurance import access as ac
from backend.assurance import comparison as cmp
from backend.assurance import dimensions as dm
from backend.assurance import record as rc
from backend.assurance import review as rv
from backend.assurance import store as st
from backend.assurance import trends as tr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/investigations", tags=["assurance"])
dimensions_router = APIRouter(prefix="/intelligence", tags=["assurance"])

#: One message for both "no such record" and "not yours". See the note above.
NOT_FOUND = {"error": "not_found",
             "message": "No assurance record is available at that address."}


def viewer_for(principal: Principal) -> ac.Viewer:
    """Build the access subject for the caller.

    The project and share memberships are read from the platform where a
    database is present. Where it is not, the viewer keeps their ROLE — so
    an administrator still reaches broadly and an analyst still reaches only
    their own work, which is the fail-closed answer rather than an open one.
    """
    projects: set[str] = set()
    shared: set[str] = set()
    workflow: set[str] = set()
    try:
        from backend.config import settings

        if settings.has_database and principal.user_id is not None:
            from sqlalchemy import text

            from backend.db.engine import get_session

            with get_session() as session:
                rows = session.execute(
                    text("SELECT DISTINCT project_id FROM project_members "
                         "WHERE user_id = :uid"),
                    {"uid": principal.user_id}).fetchall()
                projects = {str(r[0]) for r in rows if r[0] is not None}
    except Exception:  # pragma: no cover - no such table yet, or no database
        # Deliberately silent and deliberately empty: a viewer whose
        # memberships cannot be established has none, which refuses rather
        # than grants.
        projects = set()
    return ac.Viewer(user_id=principal.user_id, role=str(principal.role),
                     project_ids=frozenset(projects),
                     shared_investigation_ids=frozenset(shared),
                     workflow_object_ids=frozenset(workflow))


def _guard(viewer: ac.Viewer, row: st.StoredRecord) -> ac.Decision:
    decision = ac.may_read(viewer, ac.Subject(
        assurance_record_id=row.assurance_record_id,
        investigation_id=row.investigation_id,
        project_id=row.project_id,
        owner_user_id=row.user_id,
        tenant_id=row.tenant_id))
    if not decision.allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=NOT_FOUND)
    return decision


#: What the caller is told when the thread exists, they may read it, and
#: nothing has been assured on it yet. Distinct from NOT_FOUND above, because
#: it is a distinct fact about the world and the reader acts on it differently.
#: A thread the caller can see and whose assurance they may not read. Said
#: plainly, because they already know the Investigation exists.
NOT_YOURS = {"error": "forbidden",
             "message": ("You do not have access to this Investigation's "
                         "assurance. It is visible to the people who ran it, "
                         "to its project, and to reviewers.")}

NOT_YET = ("Nothing on this Investigation has been assured yet. Assurance is "
           "recorded when CreditProbe answers a question, so the first answer "
           "in this thread will produce it.")


#: What `_visible` found. Three states, because the endpoint's answer differs
#: for each and the old code had one answer for all three.
GONE = "GONE"          # no such Investigation, or an id that names nothing
REFUSED = "REFUSED"    # it exists, and this caller may not read its assurance
OPEN = "OPEN"          # it exists and the caller may read it


def _visible(viewer: ac.Viewer, investigation_id: str) -> str:
    """Whether the caller may see the INVESTIGATION, records aside.

    NOT_FOUND deliberately says one thing for "no such record" and for "not
    yours", so that probing RECORD addresses discloses nothing. Applied to a
    whole thread it answered 404 for three different things, and two of them
    do not belong there.

    The thread exists and nothing has been assured on it yet. Every
    Investigation is in that state until its first answer, so every
    Investigation page fetched a 404, logged a console error, and showed the
    reader "No assurance record is available at that address" — a broken link
    where the truth was "not yet".

    The thread exists and this caller may not read its assurance. That is a
    refusal, and saying so here discloses nothing: the caller is looking at
    the Investigation, so they already know it exists. The single 404 protects
    a record id somebody guessed, which is a different thing, and it still
    covers that case below.

    The same policy decides all of it — `may_read`, asked about the
    Investigation's own project, owner and tenant rather than about a record
    that does not exist — so a caller who could not have read its records
    cannot read this either.
    """
    from backend.config import settings

    if not settings.has_database or not investigation_id:
        return GONE
    try:
        numeric = int(investigation_id)
    except (TypeError, ValueError):
        return GONE
    try:
        from backend.db.engine import get_session
        from backend.models.platform import Investigation

        with get_session() as session:
            found = session.get(Investigation, numeric)
            if found is None:
                return GONE
            allowed = ac.may_read(viewer, ac.Subject(
                investigation_id=investigation_id,
                project_id=(str(found.project_id)
                            if found.project_id is not None else None),
                owner_user_id=found.owner_id)).allowed
            return OPEN if allowed else REFUSED
    except Exception as e:  # noqa: BLE001 - the database went away
        # An Investigation that could not be read is not one that is not
        # there, but nothing can be shown either way, and GONE is the
        # answer that discloses least.
        logger.warning("Could not read Investigation %s: %s",
                       investigation_id, e)
        return GONE


def _thread(viewer: ac.Viewer, investigation_id: str) -> list[st.StoredRecord]:
    rows = st.for_investigation(investigation_id)
    return [r for r in rows
            if ac.may_read(viewer, ac.Subject(
                assurance_record_id=r.assurance_record_id,
                investigation_id=r.investigation_id,
                project_id=r.project_id, owner_user_id=r.user_id,
                tenant_id=r.tenant_id)).allowed]


# ============================================================ §204's routes


@router.get("/{investigation_id}/assurance")
def investigation_assurance(investigation_id: str,
                            principal: Principal = RequireCommenter
                            ) -> dict[str, Any]:
    """The thread's assurance: the latest turn's review plus §185's thread
    status over every turn the caller may see."""
    viewer = viewer_for(principal)
    rows = _thread(viewer, investigation_id)
    if not rows:
        seen = _visible(viewer, investigation_id)
        # A thread the caller may read, with nothing assured on it yet, is an
        # empty state and not a missing address.
        if seen == OPEN:
            return {"investigation_id": investigation_id,
                    "assured": False, "statement": NOT_YET}
        # A thread they may NOT read is a refusal, and it reads as one.
        if seen == REFUSED:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=NOT_YOURS)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=NOT_FOUND)
    latest = rows[-1]
    decision = _guard(viewer, latest)
    review = rv.InvestigationReview(record=latest, thread=rows,
                                    decision=decision)
    return review.to_dict()


@router.get("/{investigation_id}/assurance/turns")
def investigation_turns(investigation_id: str,
                        principal: Principal = RequireCommenter
                        ) -> dict[str, Any]:
    """§190's timeline on its own, for a surface that only wants the
    turns."""
    viewer = viewer_for(principal)
    rows = _thread(viewer, investigation_id)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=NOT_FOUND)
    review = rv.InvestigationReview(record=rows[-1], thread=rows,
                                    decision=_guard(viewer, rows[-1]))
    return {"investigation_id": investigation_id,
            "turns": review.timeline(),
            "thread": review.thread_status(),
            "actions": list(rv.TURN_ACTIONS)}


@router.get("/{investigation_id}/assurance/compare")
def compare_records(investigation_id: str,
                    before: str = Query(..., min_length=1),
                    after: str = Query(..., min_length=1),
                    principal: Principal = RequireCommenter
                    ) -> dict[str, Any]:
    """§200. Both records are guarded independently — a comparison is a way
    of reading two records, and reading either one needs permission."""
    viewer = viewer_for(principal)
    first, second = st.get(before), st.get(after)
    if first is None or second is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=NOT_FOUND)
    _guard(viewer, first)
    _guard(viewer, second)
    return cmp.compare(first, second).to_dict()


class RerunRequest(BaseModel):
    """§204's cost confirmation, as an explicit field.

    A boolean the caller has to set rather than a default, because the whole
    point is that somebody agreed to spend the money.
    """

    assurance_record_id: str = Field(..., min_length=1)
    cost_confirmed: bool = False
    note: str = ""


@router.post("/{investigation_id}/assurance/rerun")
def request_rerun(investigation_id: str, body: RerunRequest,
                  principal: Principal = RequireAdmin) -> dict[str, Any]:
    """Record the intent to re-run, and refuse without cost confirmation.

    This route does not itself call a provider. It returns what a re-run
    would compare and what it would cost, and leaves the spending to the
    operator who confirmed it — a route that quietly spent a bank's tokens
    because somebody clicked "compare" is what the confirmation exists to
    prevent.
    """
    viewer = viewer_for(principal)
    row = st.get(body.assurance_record_id)
    if row is None or row.investigation_id != investigation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=NOT_FOUND)
    _guard(viewer, row)
    if not body.cost_confirmed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "cost_not_confirmed",
                    "message": ("Re-running this turn calls the configured "
                                "models again and costs money. Confirm the "
                                "cost to proceed."),
                    "estimated_tokens": row.tokens_in + row.tokens_out,
                    "last_cost_usd": round(row.cost_usd, 4)})
    return {
        "accepted": True,
        "investigation_id": investigation_id,
        "original": row.assurance_record_id,
        "question": row.question,
        "will_compare": [axis for axis, _ in cmp.COMPARABILITY_AXES],
        "note": ("The original record is kept unchanged. The re-run writes a "
                 "new record, and the two are compared rather than merged."),
        "requested_by": principal.user_id,
        "cost_confirmed": True,
    }


@router.get("/{investigation_id}/assurance/{record_id}")
def one_record(investigation_id: str, record_id: str,
               principal: Principal = RequireCommenter) -> dict[str, Any]:
    """§189's full review of one turn."""
    viewer = viewer_for(principal)
    row = st.get(record_id)
    if row is None or row.investigation_id != investigation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=NOT_FOUND)
    decision = _guard(viewer, row)
    review = rv.InvestigationReview(
        record=row, thread=_thread(viewer, investigation_id),
        decision=decision)
    return review.to_dict()


# ------------------------------------------------- the dimension catalogue


@dimensions_router.get("/dimensions")
def dimension_catalogue(principal: Principal = RequireCommenter
                        ) -> dict[str, Any]:
    """§204's `/intelligence/dimensions`, and §201's tiles.

    Open to every signed-in role: what CreditProbe measures about itself is
    not privileged information, and a user shown a score is entitled to know
    what it is a score OF. What is privileged is other people's records, and
    none appear here.
    """
    catalogue = dm.catalogue()
    catalogue["statuses"] = [{"id": s, "means": rc.MEANS[s]}
                             for s in rc.STATUSES]
    catalogue["outcomes"] = list(rc.OUTCOMES)
    catalogue["counted_outcomes"] = sorted(rc.COUNTED)
    catalogue["operational_assurance_label"] = rc.ASSURANCE_LABEL
    catalogue["reference_match_note"] = (
        "Operational assurance is what the runtime could prove about a run. "
        "Reference match is agreement with an approved answer, and exists "
        "only where such an answer does.")
    catalogue["cohorts"] = [{"id": c, "label": label}
                            for c, _, label in tr.COHORTS]
    catalogue["min_sample"] = tr.MIN_SAMPLE
    return catalogue
