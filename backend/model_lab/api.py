"""
Lab API, on its OWN router (`/api/v1/model-lab`), never on the frozen
`routes.router` (whose compartmentalisation guard audits every route).

Identity comes from the frozen principal resolver; every endpoint checks the
caller's tenant against the comparison's owner scope and answers 404 -- not
403 -- for anything outside it, so guessing an id reveals nothing. The
browser never receives provider credentials or endpoint secrets.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.cockpit_v4.routes import principal
from backend.model_lab import FROZEN_COMMIT, LAB_VERSION, RELEASE_CLAIM
from backend.model_lab.coordinator import SpecError
from backend.model_lab.registry import load_presets

router = APIRouter(prefix="/api/v1/model-lab", tags=["model-lab"])
_SVC: dict[str, Any] = {}


def install(service) -> None:
    _SVC["svc"] = service


def svc():
    s = _SVC.get("svc")
    if s is None:
        raise HTTPException(503, "the model lab is not installed")
    return s


def _scoped(who: dict[str, Any]) -> None:
    if who.get("tenant") != svc().cfg.tenant_id:
        raise HTTPException(404, "not found")


def _comparison(cid: str, who: dict[str, Any]) -> dict[str, Any]:
    _scoped(who)
    try:
        return svc().coord.status(cid)
    except KeyError:
        raise HTTPException(404, "not found") from None


class CompareRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    profile_ids: list[str] = Field(min_length=1, max_length=24)
    comparator_id: str = ""
    preset_id: str = ""
    execution_mode: str = "E2E_BASELINE"
    deployment: str = "mac_sequential"
    trial_count: int = 1
    run_order_seed: int | None = None
    group_spend_cap_usd: float = 0.0
    group_wall_clock_s: float = 1800
    domain: str = "corporate"
    mode: str = "standard"
    task_id: str = ""
    label: str = ""
    parent_id: str | None = None


class ClarifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    child_ids: list[str] = Field(min_length=1)


class FollowUpRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    child_ids: list[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    target: str = Field(min_length=3, max_length=200)
    decision: str
    reason: str = Field(min_length=1, max_length=2000)


class ReplayRequest(BaseModel):
    kind: str
    child_ids: list[str] = Field(default_factory=list)


@router.get("/info")
async def info(who: dict = Depends(principal)) -> dict[str, Any]:
    _scoped(who)
    return {"lab_version": LAB_VERSION, "frozen_commit": FROZEN_COMMIT,
            "release_claim": RELEASE_CLAIM,
            "presets": list(load_presets().values())}


@router.get("/model-profiles")
async def model_profiles(who: dict = Depends(principal)) -> dict[str, Any]:
    _scoped(who)
    s = svc()
    ready = s.coord.readiness()
    return {"profiles": [p.public() | {"readiness": ready[pid]}
                         for pid, p in s.coord.profiles.items()],
            "presets": list(load_presets().values())}


@router.post("/comparisons/preflight")
async def preflight(body: CompareRequest, who: dict = Depends(principal)
                    ) -> dict[str, Any]:
    _scoped(who)
    return svc().coord.preflight(body.model_dump())


@router.post("/comparisons", status_code=202)
async def create(body: CompareRequest, who: dict = Depends(principal),
                 idempotency_key: str = Header(default="",
                                               alias="Idempotency-Key")
                 ) -> dict[str, Any]:
    _scoped(who)
    try:
        return await asyncio.to_thread(
            svc().coord.create, body.model_dump(),
            principal_id=str(who.get("id")), idempotency_key=idempotency_key)
    except SpecError as exc:
        raise HTTPException(422, {"error_code": "PREFLIGHT_FAILED",
                                  "message": str(exc)}) from exc


@router.get("/comparisons")
async def list_comparisons(who: dict = Depends(principal)) -> dict[str, Any]:
    _scoped(who)
    s = svc()
    out = []
    for r in s.coord.store.list_comparisons(s.cfg.tenant_id, 100):
        spec = json.loads(r["spec_json"])
        out.append({"comparison_id": r["comparison_id"], "state": r["state"],
                    "created_at": r["created_at"],
                    "question": spec["question_text"],
                    "profiles": spec["selected_profile_ids"],
                    "label": r["label"], "parent_id": r["parent_id"]})
    return {"comparisons": out}


@router.get("/comparisons/{cid}")
async def get_comparison(cid: str, who: dict = Depends(principal)
                         ) -> dict[str, Any]:
    st = _comparison(cid, who)
    s = svc()
    cur = s.coord.store.current_evaluation(cid, s.cfg.tenant_id)
    exp = s.coord.store.latest_export(cid, s.cfg.tenant_id)
    return st | {"evaluation": cur["body"] if cur else None,
                 "evaluation_revision": cur["revision"] if cur else None,
                 "evaluation_history": s.coord.store.evaluation_history(
                     cid, s.cfg.tenant_id),
                 "export": ({k: exp[k] for k in ("export_id", "revision",
                                                 "state", "sha256",
                                                 "created_at")}
                            if exp else None),
                 "reviews": s.coord.store.reviews(cid, s.cfg.tenant_id)}


@router.get("/comparisons/{cid}/events")
async def events(cid: str, request: Request, cursor: int = 0,
                 stream: bool = False, who: dict = Depends(principal)):
    _comparison(cid, who)
    s = svc()
    if not stream:
        evs = s.coord.store.events(cid, s.cfg.tenant_id, cursor, 500)
        return {"events": evs, "cursor": evs[-1]["seq"] if evs else cursor}

    async def gen():
        cur = cursor
        while True:
            if await request.is_disconnected():
                return
            evs = s.coord.store.events(cid, s.cfg.tenant_id, cur, 200)
            for e in evs:
                cur = e["seq"]
                yield f"id: {cur}\nevent: lab\ndata: {json.dumps(e)}\n\n"
            st = s.coord.status(cid)["state"]
            if not evs and st in ("COMPLETE", "PARTIAL", "CANCELLED",
                                  "BLOCKED"):
                yield f"event: settled\ndata: {json.dumps({'state': st})}\n\n"
                return
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/comparisons/{cid}/cancel")
async def cancel(cid: str, who: dict = Depends(principal)) -> dict[str, Any]:
    _comparison(cid, who)
    return svc().coord.cancel(cid)


@router.post("/comparisons/{cid}/clarifications")
async def clarifications(cid: str, body: ClarifyRequest,
                         who: dict = Depends(principal)) -> dict[str, Any]:
    _comparison(cid, who)
    try:
        return svc().coord.answer_clarification(cid, text=body.text,
                                                child_ids=body.child_ids)
    except SpecError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/comparisons/{cid}/follow-ups")
async def follow_ups(cid: str, body: FollowUpRequest,
                     who: dict = Depends(principal)) -> dict[str, Any]:
    _comparison(cid, who)
    try:
        return svc().coord.follow_up(cid, text=body.text,
                                     child_ids=body.child_ids or None)
    except SpecError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/comparisons/{cid}/replays")
async def replays(cid: str, body: ReplayRequest,
                  who: dict = Depends(principal)) -> dict[str, Any]:
    _comparison(cid, who)
    # Controlled checkpoint replay needs a saved, bounded Deep diagnostics
    # preset AND an approved replay reference. Neither exists by default.
    raise HTTPException(409, {
        "error_code": "REPLAY_NOT_APPROVED",
        "message": "Controlled replays are disabled until a bounded 'Deep "
                   "diagnostics' preset and an independently verified "
                   "replay reference are approved. Nothing was run.",
        "status": "INSUFFICIENT_REFERENCE"})


@router.post("/comparisons/{cid}/reviews")
async def reviews(cid: str, body: ReviewRequest,
                  who: dict = Depends(principal)) -> dict[str, Any]:
    _comparison(cid, who)
    try:
        return await asyncio.to_thread(
            svc().add_review, cid, reviewer=str(who.get("id")),
            target=body.target, decision=body.decision, reason=body.reason)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/comparisons/{cid}/re-evaluate")
async def re_evaluate(cid: str, who: dict = Depends(principal)
                      ) -> dict[str, Any]:
    _comparison(cid, who)
    body = await asyncio.to_thread(svc().evaluate, cid)
    return {"evaluation_id": body["evaluation_id"],
            "revision": body["revision"], "inference_calls": 0}


@router.post("/comparisons/{cid}/export")
async def build_export(cid: str, partial: bool = False,
                       who: dict = Depends(principal)) -> dict[str, Any]:
    _comparison(cid, who)
    return await asyncio.to_thread(svc().export, cid, partial=partial)


@router.get("/comparisons/{cid}/export")
async def download(cid: str, who: dict = Depends(principal)):
    _comparison(cid, who)
    s = svc()
    exp = s.coord.store.latest_export(cid, s.cfg.tenant_id)
    if not exp or exp["state"] != "READY":
        res = await asyncio.to_thread(s.export, cid, partial=s.coord.status(
            cid)["state"] not in ("COMPLETE", "PARTIAL", "CANCELLED",
                                  "BLOCKED"))
        if res["state"] != "READY":
            raise HTTPException(503, {"error_code": "EXPORT_FAILED",
                                      "retryable": True})
        path = res["path"]
    else:
        path = exp["path"]
    p = Path(path).resolve()
    if s.exports_dir.resolve() not in p.parents:
        raise HTTPException(404, "not found")
    return FileResponse(p, media_type="application/zip", filename=p.name)


@router.get("/training-readiness")
async def training_readiness(who: dict = Depends(principal)
                             ) -> dict[str, Any]:
    _scoped(who)
    return await asyncio.to_thread(svc().training_readiness)
