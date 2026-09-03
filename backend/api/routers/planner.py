"""The Project Planner's HTTP surface.

Every route follows the same discipline:

  * a Principal is named on the signature, so a route that loses its
    authorisation is a diff nobody can miss;
  * the project is resolved through `backend.planner.access` before anything
    else is read — an id in a URL is a request, not a permission;
  * `ProjectNotFound` becomes 404 and `ProjectDenied` becomes 403, and the
    first of those is also what a project somebody may not see returns;
  * `PlannerError` becomes 422 with the sentence the service wrote, because
    "Percent complete must be between 0 and 100" is an answer and "invalid
    request" is not;
  * nothing returns a stack trace.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.permissions import (
    Principal,
    RequireAdmin,
    RequireAnalyst,
    RequireCommenter,
)
from backend.config import settings
from backend.db.engine import SessionLocal
from backend.models.planner import PlannerProject
from backend.planner import access as acl
from backend.planner import monitor as mon
from backend.planner import query as pq
from backend.planner import service as svc
from backend.planner import workbook as wb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/planner", tags=["project planner"])


def get_db() -> Session:
    """A transactional session per request, committed on success."""
    if not settings.has_database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "database_unavailable",
                    "message": "The Project Planner needs PostgreSQL, and "
                               "this deployment has none configured."})
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _fail(exc: Exception) -> HTTPException:
    """One place that turns a service refusal into an HTTP answer."""
    if isinstance(exc, acl.ProjectNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(exc)})
    if isinstance(exc, acl.ProjectDenied):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": str(exc)})
    if isinstance(exc, svc.StaleWrite):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stale_write", "message": str(exc)})
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "invalid_request", "message": str(exc)})


def _guard(fn: Any) -> Any:
    """Run a service call, translating its refusals. Used by every route."""
    try:
        return fn()
    except (acl.ProjectNotFound, acl.ProjectDenied, svc.PlannerError) as exc:
        raise _fail(exc) from exc


# ============================================================== portfolio


@router.get("/projects", summary="Every project you can see")
def list_projects(status_filter: str = Query(default="", alias="status"),
                  health: str = "", manager_id: int | None = None,
                  search: str = Query(default="", max_length=120),
                  include_archived: bool = False,
                  limit: int = Query(default=100, ge=1, le=500),
                  offset: int = Query(default=0, ge=0),
                  session: Session = Depends(get_db),
                  principal: Principal = RequireCommenter) -> dict:
    return pq.portfolio(session, principal, status=status_filter,
                        health=health, manager_id=manager_id, search=search,
                        include_archived=include_archived, limit=limit,
                        offset=offset)


@router.get("/attention", summary="Projects that need somebody to act")
def attention(limit: int = Query(default=10, ge=1, le=50),
              session: Session = Depends(get_db),
              principal: Principal = RequireCommenter) -> dict:
    return {"items": pq.attention(session, principal, limit=limit)}


@router.get("/my-work", summary="What you have to do")
def my_work(horizon_days: int = Query(default=30, ge=1, le=365),
            session: Session = Depends(get_db),
            principal: Principal = RequireCommenter) -> dict:
    return pq.my_work(session, principal, horizon_days=horizon_days)


# ============================================================== projects


class ProjectIn(BaseModel):
    code: str = Field(max_length=40)
    name: str = Field(max_length=200)
    description: str = ""
    objective: str = ""
    business_context: str = ""
    status: str = "DRAFT"
    priority: str = "MEDIUM"
    sponsor_id: int | None = None
    manager_id: int | None = None
    team_id: int | None = None
    start_date: str | None = None
    target_end_date: str | None = None
    reporting_cadence: str = "WEEKLY"
    reminder_days: list[int] | None = None
    stale_after_days: int = 7


@router.post("/projects", status_code=status.HTTP_201_CREATED,
             summary="Start a project")
def create_project(payload: ProjectIn, session: Session = Depends(get_db),
                   principal: Principal = RequireAnalyst) -> dict:
    project = _guard(lambda: svc.create_project(
        session, principal, **payload.model_dump()))
    pq.refresh_calculations(session, project)
    session.flush()
    return pq.project_detail(session, principal, int(project.id))


@router.get("/projects/{project_id}", summary="One project, in full")
def get_project(project_id: int, session: Session = Depends(get_db),
                principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: pq.project_detail(session, principal, project_id))


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    objective: str | None = None
    business_context: str | None = None
    status: str | None = None
    priority: str | None = None
    sponsor_id: int | None = None
    manager_id: int | None = None
    start_date: str | None = None
    target_end_date: str | None = None
    actual_end_date: str | None = None
    reporting_cadence: str | None = None
    reminder_days: list[int] | None = None
    stale_after_days: int | None = None
    expected_version: int | None = None


@router.patch("/projects/{project_id}", summary="Change a project")
def patch_project(project_id: int, payload: ProjectPatch,
                  session: Session = Depends(get_db),
                  principal: Principal = RequireAnalyst) -> dict:
    # `exclude_unset` and not a plain dump: absent means "leave it alone",
    # and present-and-null means "clear it". A dump that cannot tell those
    # apart sends target_end_date=None on every rename and quietly erases
    # the delivery date the project is judged against.
    sent = payload.model_dump(exclude_unset=True)
    fields = {k: v for k, v in sent.items() if k != "expected_version"}
    project = _guard(lambda: svc.update_project(
        session, principal, project_id,
        expected_version=payload.expected_version, **fields))
    pq.refresh_calculations(session, project)
    session.flush()
    return pq.project_detail(session, principal, project_id)


class HealthOverrideIn(BaseModel):
    health: str = ""
    reason: str = ""


@router.post("/projects/{project_id}/health",
             summary="Report a health colour by hand")
def override_health(project_id: int, payload: HealthOverrideIn,
                    session: Session = Depends(get_db),
                    principal: Principal = RequireAnalyst) -> dict:
    _guard(lambda: svc.set_health_override(
        session, principal, project_id, health=payload.health,
        reason=payload.reason))
    return pq.project_detail(session, principal, project_id)


@router.post("/projects/{project_id}/recalculate",
             summary="Recompute progress and health now")
def recalculate(project_id: int, session: Session = Depends(get_db),
                principal: Principal = RequireCommenter) -> dict:
    _guard(lambda: acl.readable(session, project_id, principal))
    project = session.get(PlannerProject, int(project_id))
    verdict = pq.refresh_calculations(session, project)
    return {"health": verdict.to_dict(),
            "percent_complete": int(project.calculated_percent_complete or 0)}


# ========================================================== participants


class ParticipantIn(BaseModel):
    user_id: int
    project_role: str = "CONTRIBUTOR"
    access: str = "CONTRIBUTOR"
    workstream_id: int | None = None
    notifications_enabled: bool = True
    notes: str = ""


@router.post("/projects/{project_id}/participants",
             summary="Put somebody on the project")
def add_participant(project_id: int, payload: ParticipantIn,
                    session: Session = Depends(get_db),
                    principal: Principal = RequireAnalyst) -> dict:
    _guard(lambda: svc.add_participant(session, principal, project_id,
                                       **payload.model_dump()))
    return pq.project_detail(session, principal, project_id)


@router.delete("/projects/{project_id}/participants/{user_id}",
               summary="Take somebody off")
def remove_participant(project_id: int, user_id: int,
                       session: Session = Depends(get_db),
                       principal: Principal = RequireAnalyst) -> dict:
    _guard(lambda: svc.remove_participant(session, principal, project_id,
                                          user_id=user_id))
    return pq.project_detail(session, principal, project_id)


# =========================================================== workstreams


class WorkstreamIn(BaseModel):
    code: str = Field(max_length=40)
    name: str = Field(max_length=200)
    description: str = ""
    lead_id: int | None = None
    status: str = "ACTIVE"
    start_date: str | None = None
    target_end_date: str | None = None
    sequence: int = 0


@router.post("/projects/{project_id}/workstreams",
             status_code=status.HTTP_201_CREATED, summary="Add a workstream")
def create_workstream(project_id: int, payload: WorkstreamIn,
                      session: Session = Depends(get_db),
                      principal: Principal = RequireAnalyst) -> dict:
    _guard(lambda: svc.create_workstream(session, principal, project_id,
                                         **payload.model_dump()))
    return pq.project_detail(session, principal, project_id)


# ================================================================= tasks


class TaskIn(BaseModel):
    code: str = Field(max_length=40)
    title: str = Field(max_length=300)
    description: str = ""
    workstream_id: int | None = None
    parent_id: int | None = None
    owner_id: int | None = None
    reviewer_id: int | None = None
    contributor_ids: list[int] | None = None
    status: str = "NOT_STARTED"
    priority: str = "MEDIUM"
    start_date: str | None = None
    due_date: str | None = None
    effort_days: float | None = None
    weight: float = 1
    percent_complete: int = 0
    critical: bool = False
    blocked: bool = False
    blocker_reason: str = ""
    next_step: str = ""
    tags: list[str] | None = None
    notes: str = ""


@router.post("/projects/{project_id}/tasks",
             status_code=status.HTTP_201_CREATED, summary="Add a task")
def create_task(project_id: int, payload: TaskIn,
                session: Session = Depends(get_db),
                principal: Principal = RequireAnalyst) -> dict:
    task = _guard(lambda: svc.create_task(session, principal, project_id,
                                          **payload.model_dump()))
    session.flush()
    project = session.get(PlannerProject, int(project_id))
    pq.refresh_calculations(session, project)
    return {"id": int(task.id), "code": task.code}


class TaskPatch(BaseModel):
    """Every field is optional and absent means 'leave it alone'.

    Distinct from present-and-null, which means 'clear it'. A PATCH that
    cannot tell those apart wipes the owner off every task it touches.
    """

    title: str | None = None
    description: str | None = None
    notes: str | None = None
    status: str | None = None
    priority: str | None = None
    percent_complete: int | None = None
    owner_id: int | None = None
    reviewer_id: int | None = None
    contributor_ids: list[int] | None = None
    workstream_id: int | None = None
    start_date: str | None = None
    due_date: str | None = None
    weight: float | None = None
    critical: bool | None = None
    blocked: bool | None = None
    blocker_reason: str | None = None
    next_step: str | None = None
    tags: list[str] | None = None
    narrative: str = ""
    expected_version: int | None = None


@router.patch("/tasks/{task_id}", summary="Update a task")
def patch_task(task_id: int, payload: TaskPatch,
               session: Session = Depends(get_db),
               principal: Principal = RequireCommenter) -> dict:
    sent = payload.model_dump(exclude_unset=True)
    narrative = str(sent.pop("narrative", "") or "")
    expected = sent.pop("expected_version", None)
    task = _guard(lambda: svc.update_task(
        session, principal, task_id, expected_version=expected,
        narrative=narrative, **sent))
    session.flush()
    project = session.get(PlannerProject, int(task.project_id))
    pq.refresh_calculations(session, project)
    return _guard(lambda: pq.task_detail(session, principal, int(task.id)))


@router.delete("/tasks/{task_id}", summary="Delete a task")
def delete_task(task_id: int, session: Session = Depends(get_db),
                principal: Principal = RequireAnalyst) -> dict:
    task, _ = _guard(lambda: acl.visible_task(session, task_id, principal))
    project_id = int(task.project_id)
    _guard(lambda: svc.delete_task(session, principal, task_id))
    session.flush()
    project = session.get(PlannerProject, project_id)
    pq.refresh_calculations(session, project)
    return {"deleted": task_id, "project_id": project_id}


# ============================================================ milestones


class MilestoneIn(BaseModel):
    code: str = Field(max_length=40)
    name: str = Field(max_length=300)
    description: str = ""
    workstream_id: int | None = None
    owner_id: int | None = None
    target_date: str | None = None
    status: str = "PENDING"
    critical: bool = False


@router.post("/projects/{project_id}/milestones",
             status_code=status.HTTP_201_CREATED, summary="Add a milestone")
def create_milestone(project_id: int, payload: MilestoneIn,
                     session: Session = Depends(get_db),
                     principal: Principal = RequireAnalyst) -> dict:
    milestone = _guard(lambda: svc.create_milestone(
        session, principal, project_id, **payload.model_dump()))
    return {"id": int(milestone.id), "code": milestone.code}


class MilestonePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    owner_id: int | None = None
    target_date: str | None = None
    actual_date: str | None = None
    status: str | None = None
    critical: bool | None = None
    narrative: str = ""
    expected_version: int | None = None


@router.patch("/milestones/{milestone_id}", summary="Update a milestone")
def patch_milestone(milestone_id: int, payload: MilestonePatch,
                    session: Session = Depends(get_db),
                    principal: Principal = RequireAnalyst) -> dict:
    sent = payload.model_dump(exclude_unset=True)
    narrative = str(sent.pop("narrative", "") or "")
    expected = sent.pop("expected_version", None)
    row = _guard(lambda: svc.update_milestone(
        session, principal, milestone_id, expected_version=expected,
        narrative=narrative, **sent))
    session.flush()
    project = session.get(PlannerProject, int(row.project_id))
    pq.refresh_calculations(session, project)
    return {"id": int(row.id), "status": row.status}


# ========================================================== dependencies


class DependencyIn(BaseModel):
    predecessor_type: str = "TASK"
    predecessor_id: int
    successor_type: str = "TASK"
    successor_id: int
    dependency_type: str = "FS"
    lag_days: int = 0
    notes: str = ""


@router.post("/projects/{project_id}/dependencies",
             status_code=status.HTTP_201_CREATED,
             summary="Link two things")
def create_dependency(project_id: int, payload: DependencyIn,
                      session: Session = Depends(get_db),
                      principal: Principal = RequireAnalyst) -> dict:
    row = _guard(lambda: svc.create_dependency(session, principal, project_id,
                                               **payload.model_dump()))
    return {"id": int(row.id)}


@router.delete("/dependencies/{dependency_id}", summary="Unlink them")
def delete_dependency(dependency_id: int, session: Session = Depends(get_db),
                      principal: Principal = RequireAnalyst) -> dict:
    _guard(lambda: svc.delete_dependency(session, principal, dependency_id))
    return {"deleted": dependency_id}


# ================================================================== RAID


class RaidIn(BaseModel):
    code: str = ""
    raid_type: str = "RISK"
    title: str = Field(max_length=300)
    description: str = ""
    workstream_id: int | None = None
    owner_id: int | None = None
    raised_date: str | None = None
    target_date: str | None = None
    probability: str = ""
    impact: str = ""
    severity: str = "MEDIUM"
    status: str = "OPEN"
    mitigation: str = ""
    resolution: str = ""
    linked_entity_type: str = ""
    linked_entity_id: int | None = None


@router.post("/projects/{project_id}/raid",
             status_code=status.HTTP_201_CREATED,
             summary="Raise a risk, assumption, issue or decision")
def create_raid(project_id: int, payload: RaidIn,
                session: Session = Depends(get_db),
                principal: Principal = RequireCommenter) -> dict:
    row = _guard(lambda: svc.create_raid(session, principal, project_id,
                                         **payload.model_dump()))
    return {"id": int(row.id), "code": row.code}


class RaidPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    owner_id: int | None = None
    severity: str | None = None
    status: str | None = None
    target_date: str | None = None
    probability: str | None = None
    impact: str | None = None
    mitigation: str | None = None
    resolution: str | None = None
    narrative: str = ""
    expected_version: int | None = None


@router.patch("/raid/{raid_id}", summary="Update a RAID item")
def patch_raid(raid_id: int, payload: RaidPatch,
               session: Session = Depends(get_db),
               principal: Principal = RequireCommenter) -> dict:
    sent = payload.model_dump(exclude_unset=True)
    narrative = str(sent.pop("narrative", "") or "")
    expected = sent.pop("expected_version", None)
    row = _guard(lambda: svc.update_raid(
        session, principal, raid_id, expected_version=expected,
        narrative=narrative, **sent))
    return {"id": int(row.id), "status": row.status}


# ============================================================== history


# ============================================================== the sweep


@router.post("/sweep", summary="Run the overnight check now")
def run_sweep(dry_run: bool = False,
              session: Session = Depends(get_db),
              principal: Principal = RequireAdmin) -> dict:
    """Administrators only, and normally the scheduler's job.

    Exposed because "why did nobody get a reminder?" is a question somebody
    has to be able to answer on a Tuesday afternoon, and `dry_run` answers it
    without sending anything.
    """
    outcome = mon.sweep(session, send=not dry_run)
    body = outcome.to_dict()
    if dry_run:
        body["would_send"] = [
            {"user_id": m.user_id, "project": m.project_code,
             "reference": m.entity_code, "trigger": m.trigger,
             "body": m.body} for m in outcome.messages]
    return body


# ============================================================ the workbook


def _attachment(content: bytes, filename: str) -> Response:
    return Response(
        content=content, media_type=wb.XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/template", summary="An empty plan workbook")
def download_template(principal: Principal = RequireCommenter) -> Response:
    return _attachment(wb.template(), "creditprobe-project-plan.xlsx")


@router.get("/projects/{project_id}/export",
            summary="This project as a workbook")
def export_project(project_id: int, session: Session = Depends(get_db),
                   principal: Principal = RequireCommenter) -> Response:
    content = _guard(lambda: wb.export(session, principal, project_id))
    project = session.get(PlannerProject, int(project_id))
    return _attachment(content, f"{project.code}-plan.xlsx")


@router.post("/projects/{project_id}/import",
             summary="Upload a workbook and see what it would do")
async def upload_workbook(project_id: int, file: UploadFile = File(...),
                          session: Session = Depends(get_db),
                          principal: Principal = RequireAnalyst) -> dict:
    """Parse, check, stage — and change nothing.

    The response is a preview. Applying it is a second, deliberate call, so
    that "I uploaded the wrong file" is a thing somebody can notice before it
    is a thing somebody has to undo.
    """
    content = await file.read()
    try:
        parsed = wb.parse(content, file.filename or "")
    except wb.ImportRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "unreadable_workbook",
                    "message": str(exc)}) from exc
    preview = _guard(lambda: wb.validate(
        session, principal, project_id, parsed,
        filename=file.filename or "", content=content))
    return preview.to_dict()


@router.post("/imports/{import_id}/commit",
             summary="Apply a workbook you have already seen")
def commit_import(import_id: int, session: Session = Depends(get_db),
                  principal: Principal = RequireAnalyst) -> dict:
    result = _guard(lambda: wb.commit(session, principal, import_id))
    session.flush()
    project = session.get(PlannerProject, int(result["project_id"]))
    pq.refresh_calculations(session, project)
    return result


class UpdateIn(BaseModel):
    narrative: str = Field(min_length=1, max_length=4000)
    entity_type: str = "PROJECT"
    entity_id: int | None = None
    blocker: str = ""
    next_step: str = ""


@router.post("/projects/{project_id}/updates",
             status_code=status.HTTP_201_CREATED,
             summary="Say something without changing anything")
def post_update(project_id: int, payload: UpdateIn,
                session: Session = Depends(get_db),
                principal: Principal = RequireCommenter) -> dict:
    row = _guard(lambda: svc.post_update(session, principal, project_id,
                                         **payload.model_dump()))
    session.flush()
    return {"id": int(row.id), "posted_at": row.created_at.isoformat()
            if row.created_at else None}


@router.get("/projects/{project_id}/activity",
            summary="The project's own timeline")
def activity(project_id: int, limit: int = Query(default=100, ge=1, le=500),
             offset: int = Query(default=0, ge=0),
             session: Session = Depends(get_db),
             principal: Principal = RequireCommenter) -> dict:
    return _guard(lambda: pq.activity(session, principal, project_id,
                                      limit=limit, offset=offset))


@router.get("/projects/{project_id}/changes",
            summary="What actually moved since a moment")
def changes(project_id: int, days: int = Query(default=7, ge=1, le=365),
            session: Session = Depends(get_db),
            principal: Principal = RequireCommenter) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    return _guard(lambda: pq.changes_since(session, principal, project_id,
                                           since))


__all__ = ["router"]
