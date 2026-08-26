"""
AI validation — the intelligence check behind the AI POWERED control.

    GET  /ai/status                    what the header chip shows
    POST /ai/validate                  run a check now (Analyst and above)
    GET  /ai/validation                the latest run, in full
    GET  /ai/validation/history        previous runs, for spotting a regression
    GET  /ai/validation/{id}/{case}    one case, with its reference answer

What this surface will not do
-----------------------------
Run on a timer. A hidden benchmark makes real model calls and reads the whole
analytical layer; doing that continuously would spend a bank's provider budget on
a number nobody asked for. It runs when somebody presses the button.

It also never returns a benchmark's expected answer before the case has been
executed. The reference on a case record was computed after the fact by the
runner; there is no endpoint that will hand out a gold answer in advance,
because there is no code path that has one.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend.api.permissions import Principal, RequireAnalyst

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", summary="What the AI POWERED control shows")
def ai_status() -> dict:
    """Provider health, build, and the last intelligence check.

    Deliberately one endpoint. The header chip has to say one thing, and
    assembling it from three calls in the browser is how a chip ends up
    reporting CONNECTED next to a two-week-old score.
    """
    from backend.build_info import build_info
    from backend.llm import health as ai_health
    from backend.validation import benchmarks, store

    observed = ai_health()
    latest = store.latest()
    info = build_info()

    if latest and not latest.get("stale"):
        label = latest.get("label") or "AI POWERED"
        tone = _tone(float(latest.get("score") or 0))
    elif latest:
        label = "AI POWERED · STALE"
        tone = "neutral"
    else:
        label = "AI POWERED"
        tone = "neutral"

    return {
        "label": label,
        "tone": tone,
        "ai": observed,
        "build": info.to_dict(),
        "latest": latest,
        "benchmark_count": len(benchmarks.CASES),
        "benchmark_turns": benchmarks.turn_count(),
        "history_available": store.available(),
        "can_run": True,
    }


def _tone(score: float) -> str:
    from backend.validation import scoring

    return scoring.band(score)[1]


@router.post("/validate", summary="Run an intelligence check")
def validate(principal: Principal = RequireAnalyst) -> dict:
    """Three hidden benchmark threads, through the live path, scored.

    Balanced by construction — one metadata thread, one calculation, one
    conversation — and randomly chosen within each, so a score cannot be earned
    by tuning the product to three known questions.
    """
    from backend.validation import runner, store

    try:
        result = runner.run(user_id=principal.user_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("The intelligence check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "validation_failed", "message": str(e)}) from e

    result.run_id = store.save(result, user_id=principal.user_id)
    payload = result.to_dict()
    payload["stored"] = result.run_id is not None
    return payload


@router.get("/validation", summary="The latest intelligence check")
def latest() -> dict:
    from backend.validation import store

    found = store.latest()
    if found is None:
        return {"run": None,
                "message": "No intelligence check has been run on this "
                           "installation yet."}
    return {"run": found}


@router.get("/validation/history", summary="Previous checks")
def history(limit: int = 20) -> dict:
    from backend.validation import store

    return {"runs": store.history(limit=limit),
            "available": store.available()}


@router.get("/validation/{run_id}/{benchmark_id}",
            summary="One validation case, in full")
def one_case(run_id: int, benchmark_id: str) -> dict:
    from backend.validation import store

    found = store.case(run_id, benchmark_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "case_not_found",
                    "message": f"No case {benchmark_id} in run {run_id}."})
    return found


__all__ = ["router"]
