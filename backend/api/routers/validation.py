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
from typing import Any

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
        tone = _tone(str(latest.get("band") or ""),
                     float(latest.get("score") or 0))
    elif latest:
        label = str(latest.get("stale_label") or "AI POWERED · STALE")
        tone = "neutral"
    else:
        label = "AI POWERED"
        tone = "neutral"

    from backend.intelligence_release import release

    certified = release()
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
        # The two things are different and the UI must not merge them.
        #
        # A QUICK INTELLIGENCE CHECK is three hidden benchmark threads run here
        # and now, against this installation's data. It says whether the AI path
        # is working today.
        #
        # A FULL INTELLIGENCE CERTIFICATION is the sealed holdout, and it cannot
        # be a button: the holdout lives in `intelligence_factory`, which the
        # product is forbidden to import — a product that can reach its own exam
        # has no exam. So it is a build-time command, and what the UI shows is
        # the frozen result of one.
        "quick_check": _quick_check_plan(observed, benchmarks),
        "certification": {
            **certified.to_dict(),
            "runnable_here": False,
            "command": "python -m intelligence_factory.certify --certify",
            "why_not_runnable": (
                "The sealed holdout is not shipped inside the application. "
                "Certification runs at build time, and this build reports what "
                "that run found."),
        },
    }


def _quick_check_plan(observed: dict, benchmarks: Any) -> dict:
    """What a quick check would do, and what it would spend, before it starts.

    Shown before the button is pressed. A validation run that silently makes
    thirty model calls is a surprise on somebody's invoice, and a run that makes
    none because no provider is configured should say so rather than producing a
    score that looks live.
    """
    turns = benchmarks.turn_count()
    live = str(observed.get("state") or "") in {"CONNECTED", "CONFIGURED"}
    return {
        "cases": len(benchmarks.CASES),
        "turns": turns,
        # One reading call and one interpretation call per turn, at most.
        "model_calls_if_live": turns * 2 if live else 0,
        "provider_state": observed.get("state", ""),
        "note": (f"About {turns * 2} model calls across {turns} turns."
                 if live else
                 "No provider is reachable, so this exercises the deterministic "
                 "governed reader and costs nothing. The score will be reported "
                 "as UNVERIFIED rather than as a live result."),
    }


def _tone(band: str, score: float) -> str:
    from backend.validation import scoring

    if band == "OFFLINE":
        return "neutral"
    if band == "UNVERIFIED":
        return "amber"
    return scoring.band(score)[1]


@router.post("/validate", summary="Run an intelligence check")
def validate(principal: Principal = RequireAnalyst) -> dict:
    """Three hidden benchmark threads, through the live path, scored.

    Balanced by construction — one metadata thread, one calculation, one
    conversation — and randomly chosen within each, so a score cannot be earned
    by tuning the product to three known questions.
    """
    from backend.llm import telemetry
    from backend.validation import runner, store

    try:
        result = runner.run(user_id=principal.user_id)
    except Exception as e:  # noqa: BLE001
        # Never an unexplained 500. A check that fails with a stack trace tells
        # the person who pressed the button nothing about whether the product
        # is broken, the key has expired, or the account is out of credit —
        # three problems with three completely different owners.
        logger.exception("The intelligence check failed")
        category = telemetry.classify(e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "validation_failed",
                "category": category,
                "message": telemetry.CATEGORY_DETAIL.get(
                    category, telemetry.CATEGORY_DETAIL[telemetry.UNKNOWN]),
                "detail": telemetry.sanitise(str(e))[:300],
            }) from e

    payload = result.to_dict()

    # A run that completed and could not be filed is still a run. Losing the
    # result to a database problem — and reporting it as a validation failure —
    # would be the check lying about itself.
    try:
        result.run_id = store.save(result, user_id=principal.user_id)
        payload["stored"] = result.run_id is not None
        payload["run_id"] = result.run_id
    except Exception as e:  # noqa: BLE001
        logger.exception("The intelligence check could not be stored")
        payload["stored"] = False
        payload["storage_error"] = (
            "This check ran and its result could not be saved, so it will not "
            "appear in the history: " + telemetry.sanitise(str(e))[:200])
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
