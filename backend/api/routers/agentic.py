"""
The agentic API: runs, the live officer indicator, agents, schedules, policies,
approvals and evaluations.

Two audiences, two permission bars
----------------------------------
**Anyone running an analysis** may read the live status of their own run — the
officer, the stage, the elapsed time. That is the working indicator, and gating
it behind an administrator role would mean most users never see one.

**Data stewards and administrators** may read Agent Operations: every run, the
registry, the schedules, the policies, the approvals. §28 places it there, and
`principals.require_operate` enforces it rather than the sidebar hiding a link.

Governing agents is narrower still (§32): seeing what the autonomy policy is and
being able to widen it are different privileges, so `require_govern` is
administrator-only.

Why the live endpoint is small
-------------------------------
It is polled while a question is in flight. The full run document is several
kilobytes of plan, findings and validation, and none of it is on screen yet — so
`runs.live` returns the stage, the officer, the specialists and the elapsed
time, and nothing else.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.agentic import (
    approvals,
    autonomy,
    events,
    principals,
    queue,
    registry,
    review,
    runs,
    schedules,
    stages,
)
from backend.agentic import (
    tools as tool_registry,
)
from backend.api.permissions import Principal, current_principal
from backend.db.engine import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agentic", tags=["agentic"])

Caller = Depends(current_principal)


def _guard(principal: Principal, check: Any) -> None:
    try:
        check(principal)
    except principals.NotVisible as denied:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "not_permitted", "message": str(denied)},
        ) from denied


# ---------------------------------------------------------------------------
# The working indicator — §7, §8
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/live", summary="What the officer is doing now")
def live(run_id: int, principal: Principal = Caller) -> dict[str, Any]:
    """The stage, the officer and the elapsed time. Polled while work runs.

    Readable by whoever started the run, and by anyone who may operate agents.
    A run somebody else started is not theirs to watch — §57's filtering
    applied to progress as well as to results.
    """
    with get_session() as session:
        found = runs.live(session, run_id)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found",
                        "message": f"Run {run_id} does not exist."})
        row = runs.load(session, run_id)
        mine = row is not None and row.user_id == principal.user_id
        if not mine and not principals.may_operate_agents(principal):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "not_permitted",
                        "message": "That run belongs to somebody else."})
        return found


class PreviewIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@router.post("/officer", summary="Which officer this request looks like")
def preview_officer(payload: PreviewIn,
                    principal: Principal = Caller) -> dict[str, Any]:
    """§9's first reading, from the sentence alone.

    The indicator has to appear the instant the user presses Ask, and the run
    does not exist until the analysis has started. This is the same
    deterministic selection `interactive.run` makes as its first pass — the
    routing signals counted off the sentence — so the title the user sees
    immediately is the title the run is created with, not a guess that will be
    contradicted.

    Costs nothing: no model, no database, no scan. It is regular expressions
    and arithmetic over one sentence, which is why it can be called on every
    keystroke-completed submit without anybody noticing.

    It can only be WRONG downward: the second reading, once the analysis knows
    how many domains it needed, may escalate (§9). It never demotes, so the
    title shown here is never withdrawn.
    """
    from backend.agentic import officers
    from backend.orchestration import routing as rt

    _ = principal
    chosen = officers.select(payload.question,
                             decision=rt.decide(payload.question))
    found = chosen.to_dict()
    found["provisional"] = True
    found["stage"] = stages.QUEUED
    found["caption"] = stages.CAPTIONS[stages.QUEUED]
    return found


@router.get("/stages", summary="The structured stage vocabulary")
def stage_vocabulary() -> dict[str, Any]:
    """§7's eleven states, with the sentence each one shows.

    Served rather than duplicated in the frontend so the caption a user sees
    and the caption recorded on the run are the same string.
    """
    return {
        "sequence": list(stages.SEQUENCE),
        "terminal": sorted(stages.TERMINAL),
        "stages": [{"id": s, "label": stages.SHORT.get(s, s),
                    "caption": stages.CAPTIONS.get(s, s)}
                   for s in (*stages.SEQUENCE, stages.NEEDS_INPUT,
                             stages.FAILED, stages.CANCELLED)],
    }


# ---------------------------------------------------------------------------
# Runs — §30
# ---------------------------------------------------------------------------


@router.get("/runs", summary="Agentic runs")
def listing(limit: int = 40, status_filter: str = "", trigger: str = "",
            mine: bool = False,
            principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        if not mine:
            _guard(principal, principals.require_operate)
        return {"runs": runs.listing(
            session, limit=min(limit, 200), status=status_filter,
            trigger=trigger,
            user_id=principal.user_id if mine else None)}


@router.get("/runs/{run_id}", summary="One agentic run in full")
def detail(run_id: int, principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        row = runs.load(session, run_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found",
                        "message": f"Run {run_id} does not exist."})
        if row.user_id != principal.user_id:
            _guard(principal, principals.require_operate)
        found = runs.detail(session, row)
        found["approvals"] = [approvals.view(a)
                              for a in approvals.for_run(session, run_id)]
        return found


@router.get("/for-analysis/{analysis_run_id}",
            summary="The agentic run behind an analysis")
def for_analysis(analysis_run_id: int,
                 principal: Principal = Caller) -> dict[str, Any]:
    """§26, §27 — the coordination layer of a Trace.

    Returns nothing (200 with `found: false`) when an analysis was asked for
    directly rather than produced by a coordinated run. That is the ordinary
    case, and it is not an error: most analyses are one person's question.
    """
    with get_session() as session:
        row = runs.for_analysis(session, analysis_run_id)
        if row is None:
            return {"found": False, "analysis_run_id": analysis_run_id}
        if row.user_id != principal.user_id and not (
                principals.may_operate_agents(principal)):
            # Somebody else's run produced this analysis. The analysis itself
            # is governed by its own permissions; the coordination behind it
            # is not theirs to read.
            return {"found": False, "analysis_run_id": analysis_run_id}
        found = runs.detail(session, row)
        found["found"] = True
        found["story"] = runs.story(session, row)
        found["approvals"] = [approvals.view(a)
                              for a in approvals.for_run(session, row.id)]
        return found


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/runs/{run_id}/cancel", summary="Stop a run")
def cancel(run_id: int, payload: CancelIn,
           principal: Principal = Caller) -> dict[str, Any]:
    """Ask a running job to stop. §30.

    A flag, not a kill: the worker notices at its next checkpoint and stops
    cleanly, so a cancelled run still shows what it completed.
    """
    _guard(principal, principals.require_operate)
    with get_session() as session:
        row = runs.load(session, run_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found",
                        "message": f"Run {run_id} does not exist."})
        from sqlalchemy import text

        job_ids = session.execute(
            text("SELECT id FROM agent_jobs WHERE run_id = :r "
                 "AND status IN ('queued','running')"),
            {"r": run_id}).scalars().all()
        stopped = [j for j in job_ids if queue.cancel(session, int(j))]
        if not stopped and row.status in {"complete", "failed", "cancelled"}:
            return {"cancelled": False,
                    "message": f"That run has already {row.status}."}
        return {"cancelled": bool(stopped), "jobs": [int(j) for j in stopped],
                "message": ("The run will stop at its next checkpoint and "
                            "keep whatever it has already completed.")}


class RetryIn(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/runs/{run_id}/retry", summary="Run this again")
def retry(run_id: int, payload: RetryIn,
          principal: Principal = Caller) -> dict[str, Any]:
    """Re-enqueue a failed proactive review. §30.

    Only a proactive run: re-running somebody's question on their behalf would
    produce an answer they did not ask for, in a thread they are reading.
    """
    _guard(principal, principals.require_operate)
    with get_session() as session:
        row = runs.load(session, run_id)
        if row is None or row.trigger == runs.USER_QUESTION:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "not_retryable",
                        "message": ("Only a proactive review can be re-run. "
                                    "A user's question is re-asked by asking "
                                    "it again.")})
        job_id, created = queue.enqueue(
            session, kind=queue.PROACTIVE_REVIEW,
            idempotency_key=f"retry:{run_id}",
            payload={"period": row.period, "trigger": runs.MANUAL_REVIEW,
                     "user_id": principal.user_id},
            priority=queue.PRIORITY_EVENT)
        return {"job_id": job_id, "queued": created,
                "message": (f"A fresh review of {row.period} is queued."
                            if created else
                            "That review is already queued.")}


# ---------------------------------------------------------------------------
# The registry — §29
# ---------------------------------------------------------------------------


@router.get("/agents", summary="The Agent Registry")
def agents(principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_operate)
    with get_session() as session:
        found = registry.catalogue()
        found["last_runs"] = _last_runs(session)
        found["autonomy_levels"] = [
            {"level": level, "name": autonomy.LEVEL_NAMES[level],
             "meaning": autonomy.LEVEL_MEANING[level]}
            for level in autonomy.LEVELS]
        return found


def _last_runs(session: Any) -> dict[str, Any]:
    """When each agent last ran, from the task table.

    §29 asks the Agents tab to show a last run. Read from what actually
    happened rather than from a column somebody has to remember to update.
    """
    from sqlalchemy import text

    rows = session.execute(text("""
        SELECT agent_id, max(created_at) AS at, count(*) AS n
          FROM agent_tasks GROUP BY agent_id
    """)).mappings().all()
    return {str(r["agent_id"]): {"at": r["at"].isoformat() if r["at"] else None,
                                 "tasks": int(r["n"])} for r in rows}


@router.get("/tools", summary="The Tool Registry")
def tools(principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_operate)
    return tool_registry.catalogue()


# ---------------------------------------------------------------------------
# Schedules — §31
# ---------------------------------------------------------------------------


@router.get("/schedules", summary="Governed schedules")
def schedule_list(principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_operate)
    with get_session() as session:
        schedules.seed(session)
        return {"schedules": schedules.listing(session),
                "triggers": [{"id": t, "label": schedules.TRIGGER_LABELS[t]}
                             for t in schedules.TRIGGERS]}


class ScheduleIn(BaseModel):
    enabled: bool


@router.patch("/schedules/{schedule_id}", summary="Enable or disable")
def schedule_toggle(schedule_id: int, payload: ScheduleIn,
                    principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_govern)
    with get_session() as session:
        from backend.models.platform import AgentSchedule

        row = session.get(AgentSchedule, schedule_id)
        if row is None:
            raise HTTPException(status_code=404,
                                detail={"error": "not_found",
                                        "message": "No such schedule."})
        schedules.set_enabled(session, row, enabled=payload.enabled,
                              user_id=principal.user_id)
        return schedules.view(row)


@router.post("/schedules/{schedule_id}/run", summary="Run a schedule now")
def schedule_fire(schedule_id: int,
                  principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_operate)
    with get_session() as session:
        from backend.models.platform import AgentSchedule

        row = session.get(AgentSchedule, schedule_id)
        if row is None:
            raise HTTPException(status_code=404,
                                detail={"error": "not_found",
                                        "message": "No such schedule."})
        job_id, created = schedules.fire(session, row,
                                         user_id=principal.user_id)
        return {"job_id": job_id, "queued": created,
                "message": ("The review is queued."
                            if created else "That review is already queued.")}


# ---------------------------------------------------------------------------
# Policies — §32
# ---------------------------------------------------------------------------


@router.get("/policies", summary="Agent policies")
def policy_list(principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_operate)
    with get_session() as session:
        schedules.seed_policies(session)
        return {"policies": schedules.policies(session)}


class PolicyIn(BaseModel):
    value: dict[str, Any]
    note: str = Field(default="", max_length=500)


@router.put("/policies/{key}", summary="Write a new policy version")
def policy_write(key: str, payload: PolicyIn,
                 principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_govern)
    if key not in schedules.POLICY_KEYS:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_policy",
                    "message": f"'{key}' is not a policy CreditProbe defines."})
    with get_session() as session:
        row = schedules.set_policy(session, key, payload.value,
                                   user_id=principal.user_id,
                                   note=payload.note)
        return {"key": row.key, "version": row.version,
                "value": dict(row.value or {})}


# ---------------------------------------------------------------------------
# Approvals — §22
# ---------------------------------------------------------------------------


@router.get("/approvals", summary="Approval gates waiting for a person")
def approval_list(principal: Principal = Caller) -> dict[str, Any]:
    with get_session() as session:
        rows = approvals.pending(session, role=str(principal.role))
        return {"approvals": [approvals.view(a) for a in rows],
                "role": str(principal.role)}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|changes_requested)$")
    note: str = Field(default="", max_length=2000)


@router.post("/approvals/{approval_id}", summary="Decide an approval gate")
def approval_decide(approval_id: int, payload: DecisionIn,
                    principal: Principal = Caller) -> dict[str, Any]:
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "not_signed_in",
                    "message": ("Approving a material action records who "
                                "decided it, so it needs a signed-in user.")})
    with get_session() as session:
        row = approvals.load(session, approval_id)
        if row is None:
            raise HTTPException(status_code=404,
                                detail={"error": "not_found",
                                        "message": "No such approval."})
        try:
            approvals.decide(session, row, decision=payload.decision,
                             user_id=principal.user_id,
                             role=str(principal.role), note=payload.note)
        except approvals.NotAuthorised as denied:
            raise HTTPException(status_code=403,
                                detail={"error": "not_permitted",
                                        "message": str(denied)}) from denied
        except approvals.AlreadyDecided as settled:
            raise HTTPException(status_code=409,
                                detail={"error": "already_decided",
                                        "message": str(settled)}) from settled
        return approvals.view(row)


# ---------------------------------------------------------------------------
# Events and the proactive review — §34, §35
# ---------------------------------------------------------------------------


@router.get("/events", summary="Governed events")
def event_list(limit: int = 50, kind: str = "",
               principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_operate)
    with get_session() as session:
        return {"events": events.listing(session, limit=min(limit, 200),
                                         kind=kind),
                "kinds": [{"id": k, "label": events.LABELS[k]}
                          for k in events.KINDS]}


class ReviewIn(BaseModel):
    period: str = Field(default="", max_length=32)
    background: bool = True


@router.post("/review", summary="Review a published period")
def start_review(payload: ReviewIn,
                 principal: Principal = Caller) -> dict[str, Any]:
    """§35 — the proactive review, on request.

    Queued by default: a whole-book review takes minutes, and holding an HTTP
    request open for it would time out somewhere between the browser and the
    proxy. `background=false` runs it inline, which is what the runbook and the
    tests use.
    """
    _guard(principal, principals.require_act)
    with get_session() as session:
        period = payload.period or events.latest_period()
        if not period:
            raise HTTPException(
                status_code=409,
                detail={"error": "no_period",
                        "message": ("No portfolio period is published, so "
                                    "there is nothing to review.")})

        event, created = events.record(
            session, kind=events.USER_REQUESTED_REVIEW, period=period,
            actor_id=principal.user_id,
            payload={"requested_by": principal.user_id})
        ready, why = events.ready(session, event)
        if not ready:
            events.ignore(session, event, reason=why)
            raise HTTPException(status_code=409,
                                detail={"error": "not_ready", "message": why})
        events.accept(session, event, reason=why)

        if payload.background:
            job_id, queued = queue.enqueue(
                session, kind=queue.PROACTIVE_REVIEW,
                idempotency_key=f"review:{period}",
                payload={"period": period, "trigger": runs.MANUAL_REVIEW,
                         "event_id": event.id, "user_id": principal.user_id},
                priority=queue.PRIORITY_EVENT)
            return {"queued": queued, "job_id": job_id, "period": period,
                    "event_id": event.id, "created_event": created,
                    "message": (f"A review of {period} is queued."
                                if queued else
                                f"A review of {period} is already running.")}

        row, found = review.run(session, period=period,
                                trigger=runs.MANUAL_REVIEW,
                                event_id=event.id, user_id=principal.user_id)
        return {"queued": False, "run_id": row.id, "period": period,
                "cases_created": found.cases_created,
                "cases_refreshed": found.cases_refreshed,
                "stopped": found.stopped, "note": found.note}


# ---------------------------------------------------------------------------
# Evaluations — §33, §59, §61, §62
# ---------------------------------------------------------------------------


@router.get("/evaluations", summary="How the agents score")
def evaluations(tier: str = "certification",
                principal: Principal = Caller) -> dict[str, Any]:
    """§33's Evaluations tab.

    Runs the corpus on request. It can be: every case is deterministic —
    permission checks, plan validation, budget arithmetic, approval rules — so
    the whole suite runs in milliseconds and calls no model. §83 forbids live
    Anthropic calls in this phase, and this endpoint could not make one if it
    wanted to.

    §33: "Do not use three random questions as certification." The result
    reports per §59 AREA rather than one number, because "87% accurate" is not
    an answer to "can it be trusted not to close a case on its own".
    """
    from backend.agentic import evaluation

    _guard(principal, principals.require_operate)
    chosen = (evaluation.QUICK if tier == evaluation.QUICK
              else evaluation.CERTIFICATION)
    found = evaluation.run(tier=chosen)
    return {
        **found.to_dict(),
        "tiers": [
            {"id": evaluation.QUICK,
             "label": "Quick check",
             "note": "A sample, for a health check. Not a certification."},
            {"id": evaluation.CERTIFICATION,
             "label": "Certification",
             "note": (f"The whole corpus. Zero safety failures and "
                      f"{evaluation.CERTIFY_AT:.0%} accuracy over at least "
                      f"{evaluation.MINIMUM_CASES} cases.")},
        ],
    }


# ---------------------------------------------------------------------------
# Worker health — §18
# ---------------------------------------------------------------------------


@router.get("/workers", summary="Agent worker health")
def workers(principal: Principal = Caller) -> dict[str, Any]:
    _guard(principal, principals.require_operate)
    with get_session() as session:
        found = queue.workers(session)
        return {
            "workers": [
                {**w, "started_at": _iso(w.get("started_at")),
                 "heartbeat_at": _iso(w.get("heartbeat_at"))}
                for w in found],
            "queue": queue.depth(session),
            "alive": sum(1 for w in found if w.get("alive")),
        }


@router.get("/health", summary="Agentic health, as a governed state")
def agentic_health(principal: Principal = Caller) -> dict[str, Any]:
    """§135's AgenticHealth. Four state machines and thirty fields.

    Four rather than one because "is the agentic layer working?" has four
    different answers and the question is usually asked when three of them
    are fine. A healthy worker with a stalled queue looks healthy; reporting
    one colour hides whichever of the four is the problem, which is the one
    somebody is trying to find.
    """
    _guard(principal, principals.require_operate)
    from backend.agentic import health as ah

    with get_session() as session:
        found = queue.workers(session)
        depths = queue.depth(session)
        alive = [w for w in found if w.get("alive")]
        beat = max((w.get("heartbeat_at") for w in alive
                    if w.get("heartbeat_at")), default=None)

        state = ah.Health(
            worker_state=ah.worker_state(last_heartbeat=beat),
            queue_depth=int(depths.get(queue.QUEUED, 0)),
            running_jobs=int(depths.get(queue.RUNNING, 0)),
            dead_letter_jobs=int(depths.get(queue.DEAD_LETTER, 0)),
            worker_last_heartbeat=_iso(beat) or "",
            worker_build_sha=str(
                (alive[0].get("build_sha") if alive else "") or ""),
        )
        state.queue_state = ah.queue_state(
            depth=state.queue_depth, running=state.running_jobs,
            oldest_queued_age=state.oldest_queued_age,
            worker=state.worker_state)
        state.scheduler_state = ah.scheduler_state(
            enabled=bool(schedules.listing(session))
            if hasattr(schedules, "listing") else False,
            due=state.scheduled_reviews_due,
            late=state.scheduled_reviews_late)
        _latest_review(session, state)
        return state.to_dict()


def _latest_review(session: Any, state: Any) -> None:
    """The latest portfolio review, from a RUN rather than a case table.

    §136's last line lives here: with no run there is no state but NOT_RUN,
    however empty the case table is. An empty table means nothing looked.
    """
    from sqlalchemy import text

    from backend.agentic import health as ah

    try:
        row = session.execute(text("""
            SELECT id, status, trigger, started_at, finished_at, period
            FROM agent_runs
            WHERE trigger IN ('scheduled_review', 'manual_review', 'event')
            ORDER BY id DESC LIMIT 1""")).mappings().first()
    except Exception:  # pragma: no cover - the table is not there yet
        row = None

    if row is None:
        state.latest_review_state = ah.NOT_RUN
        return

    counts = _case_counts(session, int(row["id"]))
    state.latest_review_id = int(row["id"])
    state.latest_review_scope = str(row.get("period") or "")
    state.latest_review_started_at = _iso(row.get("started_at")) or ""
    state.latest_review_completed_at = _iso(row.get("finished_at")) or ""
    state.latest_review_case_counts = counts
    # A run that finished is not thereby validated. Until a validation record
    # exists the state is VALIDATING, which is honest and is the state that
    # stops an unvalidated review being reported as a clean book.
    state.latest_review_validation_status = str(row.get("status") or "")
    state.latest_review_state = ah.review_state(
        run_status=str(row.get("status") or ""),
        validated=str(row.get("status") or "").lower() in
        ("succeeded", "complete", "completed"),
        cases=sum(counts.values()),
        stale_reasons=state.stale_reasons)


def _case_counts(session: Any, run_id: int) -> dict[str, int]:
    from sqlalchemy import text

    try:
        rows = session.execute(
            text("SELECT scope, count(*) AS n FROM risk_cases "
                 "WHERE run_id = :run GROUP BY scope"),
            {"run": run_id}).mappings().all()
    except Exception:  # pragma: no cover - the table is not there yet
        return {}
    return {str(r["scope"]): int(r["n"]) for r in rows}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None
