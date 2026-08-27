"""
The product hierarchy over HTTP: Projects, Investigations, Analyses.

    Analysis   < Investigation < Project
    one result   a conversation   a body of work

One vocabulary, used identically in the database, in these routes and on the
screen. A caller who has read the product knows what these endpoints are without
being told, which is the whole reason for fixing the vocabulary in the first
place.

Nothing here calculates. Asking a question inside a thread goes through the same
executor a one-off question does; these routes store what happened and hand back
what was stored.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst, RequireDataSteward
from backend.models.platform import PROJECT_STATUS_LABEL
from backend.orchestration import memory as wm
from backend.services import analyses as an
from backend.services import projects as pj
from backend.services import threads as th

logger = logging.getLogger(__name__)

MAX_TEXT = 4000

projects_router = APIRouter(prefix="/projects", tags=["projects"])
threads_router = APIRouter(prefix="/investigations", tags=["investigations"])
analyses_router = APIRouter(prefix="/analyses", tags=["analyses"])


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)},
    )


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)},
    )


def _refused(exc: Exception, code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": code, "message": str(exc)},
    )


# ================================================================= projects


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_TEXT)
    instructions: str = Field(default="", max_length=MAX_TEXT)
    team_id: int | None = None
    default_context: dict = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_TEXT)
    instructions: str | None = Field(default=None, max_length=MAX_TEXT)
    default_context: dict | None = None


class StatusIn(BaseModel):
    status: str = Field(max_length=24)
    note: str = Field(default="", max_length=MAX_TEXT)


class ProjectReviewIn(BaseModel):
    assigned_to: int | None = None
    note: str = Field(default="", max_length=MAX_TEXT)


@projects_router.get("", summary="Projects")
def list_projects(status_filter: str | None = Query(default=None, alias="status"),
                  owner_id: int | None = None,
                  limit: int = Query(default=100, ge=1, le=200)) -> dict:
    return {
        "projects": pj.listing(status=status_filter, owner_id=owner_id, limit=limit),
        "statuses": PROJECT_STATUS_LABEL,
    }


@projects_router.post("", status_code=201, summary="Open a project")
def create_project(payload: ProjectIn, principal: Principal = RequireAnalyst) -> dict:
    try:
        return pj.create(
            name=payload.name, description=payload.description,
            instructions=payload.instructions, team_id=payload.team_id,
            default_context=payload.default_context, user_id=principal.user_id,
        ).to_dict()
    except pj.StorageUnavailable as e:
        raise _unavailable(e) from e


@projects_router.get("/{project_id}", summary="One project and its status history")
def get_project(project_id: int) -> dict:
    try:
        return pj.get(project_id).to_dict()
    except pj.ProjectNotFound as e:
        raise _not_found(e) from e
    except pj.StorageUnavailable as e:
        raise _unavailable(e) from e


@projects_router.get("/{project_id}/contents",
                     summary="The investigations and analyses filed here")
def project_contents(project_id: int,
                     limit: int = Query(default=200, ge=1, le=500)) -> dict:
    try:
        return pj.contents(project_id, limit=limit)
    except pj.ProjectNotFound as e:
        raise _not_found(e) from e
    except pj.StorageUnavailable as e:
        raise _unavailable(e) from e


@projects_router.patch("/{project_id}", summary="Edit a project")
def update_project(project_id: int, payload: ProjectPatch,
                   principal: Principal = RequireAnalyst) -> dict:
    try:
        return pj.update(
            project_id, name=payload.name, description=payload.description,
            instructions=payload.instructions,
            default_context=payload.default_context,
        ).to_dict()
    except pj.ProjectNotFound as e:
        raise _not_found(e) from e
    except pj.StorageUnavailable as e:
        raise _unavailable(e) from e


@projects_router.post("/{project_id}/status", summary="Move a project's status")
def set_project_status(project_id: int, payload: StatusIn,
                       principal: Principal = RequireAnalyst) -> dict:
    """Declare where the work has got to.

    "In review" is refused here on purpose: it means a review is genuinely
    outstanding, so it is reached by sending the project for review.
    """
    try:
        return pj.set_status(project_id, payload.status,
                             actor_id=principal.user_id, note=payload.note).to_dict()
    except pj.ProjectNotFound as e:
        raise _not_found(e) from e
    except pj.InvalidProjectTransition as e:
        raise _refused(e, "invalid_transition") from e
    except pj.StorageUnavailable as e:
        raise _unavailable(e) from e


@projects_router.post("/{project_id}/review", summary="Send a project for review")
def send_project_for_review(project_id: int, payload: ProjectReviewIn,
                            principal: Principal = RequireAnalyst) -> dict:
    try:
        return pj.submit_for_review(
            project_id, assigned_to=payload.assigned_to,
            requested_by=principal.user_id, note=payload.note,
        ).to_dict()
    except pj.ProjectNotFound as e:
        raise _not_found(e) from e
    except pj.InvalidProjectTransition as e:
        raise _refused(e, "already_in_review") from e
    except pj.StorageUnavailable as e:
        raise _unavailable(e) from e


# ========================================================== investigations


class ThreadIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    title: str = Field(default="", max_length=300)
    project_id: int | None = None
    context: dict = Field(default_factory=dict)
    #: Ask straight away rather than opening an empty thread.
    ask: bool = True
    from_period: str | None = Field(default=None, max_length=64)
    to_period: str | None = Field(default=None, max_length=64)

    @property
    def is_project_thread(self) -> bool:
        return self.project_id is not None


class FollowUpIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    from_period: str | None = Field(default=None, max_length=64)
    to_period: str | None = Field(default=None, max_length=64)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class MoveIn(BaseModel):
    project_id: int | None = None


class ContextIn(BaseModel):
    context: dict = Field(default_factory=dict)


def _window(from_period: str | None, to_period: str | None) -> tuple[str, str] | None:
    return (from_period, to_period) if from_period and to_period else None


@threads_router.get("", summary="Investigations")
def list_threads(project_id: int | None = None, owner_id: int | None = None,
                 include_archived: bool = False,
                 scope: str = Query(
                     default="standalone",
                     pattern="^(standalone|project|all)$",
                     description=(
                         "standalone: threads in no project — this is Work > "
                         "Investigations. project: one project's threads. "
                         "all: everything."
                     ),
                 ),
                 limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """Investigations, scoped.

    The default is `standalone`, and that is the rule rather than a
    convenience: a thread started inside a Project belongs to that Project and
    does not also appear in the global list. Otherwise a Project is a tag, not
    a container, and the global list becomes everything anybody ever asked.
    """
    try:
        return {"investigations": th.listing(
            project_id=project_id, owner_id=owner_id, scope=scope,
            include_archived=include_archived, limit=limit,
        ), "scope": scope}
    except ValueError as e:
        raise _refused(e, "invalid_scope") from e


@threads_router.post("", status_code=201, summary="Start an investigation")
def start_thread(payload: ThreadIn, principal: Principal = RequireAnalyst) -> dict:
    """Open a thread on a question, and answer it unless asked not to."""
    try:
        thread = th.create(
            question=payload.question, title=payload.title,
            project_id=payload.project_id, context=payload.context,
            user_id=principal.user_id,
        )
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e

    if not payload.ask:
        return {"status": "created", "thread": thread.to_dict(), "run": None}

    # The opening question is already message 0, so the answer is recorded
    # directly rather than through ask(), which would store it twice.
    from backend.orchestration import conversation as cv
    from backend.orchestration.executor import answer_investigation

    window = _window(payload.from_period, payload.to_period) or th.settled_period(
        thread.context
    )
    result, answered = answer_investigation(
        payload.question, user_id=principal.user_id,
        project_id=payload.project_id, investigation_id=thread.id,
        persist=True, period=window, state=cv.load(thread.context),
        memory=wm.load(thread.context),
    )
    th.remember(thread.id, result, answered)
    if result.status == "needs_clarification":
        run = result.to_dict()
        clarification = run.get("clarification") or {}
        th.append(thread.id, role=th.ROLE_ASSISTANT,
                  content=str(clarification.get("question") or "One thing first."),
                  payload=run, user_id=principal.user_id)
        return {"status": "needs_clarification", "run": run,
                "thread": th.load(thread.id).to_dict()}

    th.record_answer(thread.id, result, user_id=principal.user_id)
    return {"status": result.status, "run": result.to_dict(),
            "thread": th.load(thread.id).to_dict()}


@threads_router.get("/{thread_id}", summary="One investigation, in full")
def get_thread(thread_id: int) -> dict:
    try:
        return th.load(thread_id).to_dict()
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


@threads_router.post("/{thread_id}/messages", summary="Ask the next question")
def follow_up(thread_id: int, payload: FollowUpIn,
              principal: Principal = RequireAnalyst) -> dict:
    """A follow-up inherits what the thread has already settled.

    If the period was agreed earlier in this conversation, it is not asked
    again.
    """
    try:
        return th.ask(thread_id, payload.question, user_id=principal.user_id,
                      period=_window(payload.from_period, payload.to_period))
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


@threads_router.post("/{thread_id}/context", summary="Record what the thread settled")
def set_thread_context(thread_id: int, payload: ContextIn,
                       principal: Principal = RequireAnalyst) -> dict:
    try:
        return th.set_context(thread_id, payload.context).to_dict()
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


@threads_router.post("/{thread_id}/rename", summary="Rename an investigation")
def rename_thread(thread_id: int, payload: RenameIn,
                  principal: Principal = RequireAnalyst) -> dict:
    try:
        return th.rename(thread_id, payload.title).to_dict()
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


@threads_router.post("/{thread_id}/move", summary="Move to a project, or out of one")
def move_thread(thread_id: int, payload: MoveIn,
                principal: Principal = RequireAnalyst) -> dict:
    try:
        return th.move(thread_id, project_id=payload.project_id).to_dict()
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


class PublishIn(BaseModel):
    """Whether this investigation appears in the global list as well. §4."""

    published: bool = True


@threads_router.post("/{thread_id}/publish",
                     summary="Publish a project investigation to the global list")
def publish_thread(thread_id: int, payload: PublishIn,
                   principal: Principal = RequireAnalyst) -> dict:
    """Add a project's investigation to Work → Investigations, or remove it.

    Deliberately not Move. Moving a project thread out takes it out of the
    project, and the project's record of what was explored goes with it;
    publishing leaves the thread where it is and lists it in both places.
    """
    try:
        return th.publish(thread_id, published=payload.published,
                          user_id=principal.user_id).to_dict()
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


class CopyIn(BaseModel):
    """Duplicate a thread. `project_id` null means the standalone list."""

    project_id: int | None = None
    title: str = Field(default="", max_length=300)


class ProjectFromThreadIn(BaseModel):
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=MAX_TEXT)
    #: Move the investigation in, rather than leaving a copy behind.
    move: bool = True


@threads_router.post("/{thread_id}/copy", status_code=201,
                     summary="Duplicate an investigation")
def copy_thread(thread_id: int, payload: CopyIn,
                principal: Principal = RequireAnalyst) -> dict:
    """Take a copy somewhere else, leaving the original where it is.

    Distinct from Move: moving a project's investigation out takes it OUT of the
    project, and the project's record of what was explored should usually
    survive.
    """
    try:
        return th.copy(thread_id, project_id=payload.project_id,
                       title=payload.title, user_id=principal.user_id).to_dict()
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


@threads_router.post("/{thread_id}/project", status_code=201,
                     summary="Start a project from this investigation")
def project_from_thread(thread_id: int, payload: ProjectFromThreadIn,
                        principal: Principal = RequireAnalyst) -> dict:
    """Open a project around a conversation that turned out to matter.

    The investigation's settled context becomes the project's standing context,
    so the work already done carries over rather than being re-established.
    """
    try:
        thread = th.load(thread_id)
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e

    try:
        project = pj.create(
            name=payload.name or thread.title,
            description=payload.description,
            default_context=dict(thread.context or {}),
            user_id=principal.user_id,
        )
        if payload.move:
            th.move(thread_id, project_id=project.id)
        else:
            th.copy(thread_id, project_id=project.id, user_id=principal.user_id)
    except pj.StorageUnavailable as e:
        raise _unavailable(e) from e

    return {"project": pj.get(project.id).to_dict(),
            "investigation": th.load(thread_id).to_dict()}


@threads_router.post("/{thread_id}/archive", summary="Take it off the working list")
def archive_thread(thread_id: int,
                   principal: Principal = RequireDataSteward) -> dict:
    try:
        return th.archive(thread_id).to_dict()
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e


# ================================================================ analyses


class SaveAnalysisIn(BaseModel):
    """Keep one calculation that has already run.

    `analysis_run_id` is what ties this record to the immutable run and its
    Trace. The result is stored as returned; nothing here recalculates it.
    """

    analysis_id: str = Field(min_length=1, max_length=120)
    title: str = Field(default="", max_length=300)
    result: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    period: dict = Field(default_factory=dict)
    data_versions: dict = Field(default_factory=dict)
    analysis_run_id: int | None = None
    investigation_id: int | None = None
    project_id: int | None = None
    note: str = Field(default="", max_length=MAX_TEXT)


class SaveFromMessageIn(BaseModel):
    """Keep the analyses behind one assistant message in a thread."""

    investigation_id: int
    sequence: int
    project_id: int | None = None
    title: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=MAX_TEXT)


@analyses_router.get("", summary="Saved analyses")
def list_analyses(project_id: int | None = None, investigation_id: int | None = None,
                  owner_id: int | None = None, analysis_id: str | None = None,
                  limit: int = Query(default=100, ge=1, le=200)) -> dict:
    return {"analyses": an.listing(
        project_id=project_id, investigation_id=investigation_id,
        owner_id=owner_id, analysis_id=analysis_id, limit=limit,
    )}


@analyses_router.post("", status_code=201, summary="Save an analysis")
def save_analysis(payload: SaveAnalysisIn,
                  principal: Principal = RequireAnalyst) -> dict:
    try:
        return an.save(
            analysis_id=payload.analysis_id, title=payload.title,
            result=payload.result, params=payload.params, filters=payload.filters,
            period=payload.period, data_versions=payload.data_versions,
            analysis_run_id=payload.analysis_run_id,
            investigation_id=payload.investigation_id,
            project_id=payload.project_id, note=payload.note,
            user_id=principal.user_id,
        ).to_dict()
    except an.StorageUnavailable as e:
        raise _unavailable(e) from e


@analyses_router.post("/from-message", status_code=201,
                      summary="Save the analyses behind an answer")
def save_from_message(payload: SaveFromMessageIn,
                      principal: Principal = RequireAnalyst) -> dict:
    """Keep every certified step of a stored answer as its own Analysis.

    The steps are read back from what was stored when the answer was given, so
    the saved figures are the ones the user actually saw.
    """
    try:
        thread = th.load(payload.investigation_id)
    except th.ThreadNotFound as e:
        raise _not_found(e) from e
    except th.StorageUnavailable as e:
        raise _unavailable(e) from e

    message = next(
        (m for m in thread.messages
         if m["sequence"] == payload.sequence and m["role"] == th.ROLE_ASSISTANT),
        None,
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found",
                    "message": f"There is no answer at position {payload.sequence} "
                               "in this investigation."},
        )

    run = message.get("payload") or {}
    steps = [s for s in (run.get("steps") or [])
             if s.get("analysis_id") and s.get("status") == "succeeded"]
    if not steps:
        raise _refused(
            ValueError("This answer has no completed analysis to save."),
            "nothing_to_save",
        )

    scope = (run.get("plan") or {}).get("scope") or {}
    saved = [an.save(
        analysis_id=str(step["analysis_id"]),
        title=payload.title or str(step.get("title") or step["analysis_id"]),
        result=step.get("result") if isinstance(step.get("result"), dict) else {},
        params=dict(step.get("params") or {}),
        filters=dict(step.get("filters") or {}),
        period={
            "period": step.get("period"),
            "from_period": scope.get("from_period"),
            "to_period": scope.get("to_period"),
        },
        data_versions=dict(step.get("node_hashes") or {}),
        analysis_run_id=step.get("analysis_run_id") or run.get("analysis_run_id"),
        investigation_id=payload.investigation_id,
        project_id=payload.project_id or thread.project_id,
        note=payload.note,
        user_id=principal.user_id,
    ).to_dict() for step in steps]
    return {"analyses": saved, "count": len(saved)}


@analyses_router.get("/{saved_id}", summary="One saved analysis")
def get_analysis(saved_id: int) -> dict:
    try:
        return an.get(saved_id).to_dict()
    except an.AnalysisNotFound as e:
        raise _not_found(e) from e
    except an.StorageUnavailable as e:
        raise _unavailable(e) from e


@analyses_router.post("/{saved_id}/move", summary="File it under a project")
def move_analysis(saved_id: int, payload: MoveIn,
                  principal: Principal = RequireAnalyst) -> dict:
    try:
        return an.move(saved_id, project_id=payload.project_id).to_dict()
    except an.AnalysisNotFound as e:
        raise _not_found(e) from e
    except an.StorageUnavailable as e:
        raise _unavailable(e) from e


@analyses_router.post("/{saved_id}/rename", summary="Rename a saved analysis")
def rename_analysis(saved_id: int, payload: RenameIn,
                    principal: Principal = RequireAnalyst) -> dict:
    try:
        return an.rename(saved_id, payload.title).to_dict()
    except an.AnalysisNotFound as e:
        raise _not_found(e) from e
    except an.StorageUnavailable as e:
        raise _unavailable(e) from e


@analyses_router.delete("/{saved_id}", status_code=204,
                        summary="Stop keeping this analysis")
def delete_analysis(saved_id: int, principal: Principal = RequireAnalyst) -> None:
    """Removes the saved record only. The run and its Trace are untouched."""
    try:
        an.delete(saved_id)
    except an.AnalysisNotFound as e:
        raise _not_found(e) from e
    except an.StorageUnavailable as e:
        raise _unavailable(e) from e


__all__ = ["analyses_router", "projects_router", "threads_router"]
