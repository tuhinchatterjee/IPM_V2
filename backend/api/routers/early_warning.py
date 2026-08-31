"""
Early Warning over HTTP.

Two audiences, separated by permission rather than by politeness:

  * anyone who may run an analysis can READ the signal — the scored book, the
    factor definitions, how a particular facility scored and why;
  * only an administrator may FIT, VERSION or ACTIVATE a model. Changing the
    model that ranks a bank's watchlist is a governance act, and it is recorded
    as one.

Nothing here lets a caller supply weights, a score, or a probability. The only
way a number comes out is by running a stored specification over governed data.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAdmin
from backend.early_warning import lifecycle as lc
from backend.early_warning import service as ew
from backend.early_warning.factors import FACTOR_FAMILIES, FACTORS
from backend.early_warning.model import BANDS, SignalSpecification
from backend.early_warning.targets import TARGETS, UnknownTargetError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/early-warning", tags=["early warning"])

MAX_TEXT = 2000


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


# ================================================== the governed signal taxonomy
#
# §19: Early Warning "is NOT one opaque score". These routes serve the other
# half of the module — named conditions on named governed fields against named
# thresholds — beside the fitted Forward Risk Signal, not instead of it. A
# credit officer asked to act on a number cannot argue with it; asked to act on
# "utilisation rose 14 points and covenant headroom fell below 10%", they can.


@router.get("/taxonomy", summary="Every governed early-warning signal")
def taxonomy() -> dict:
    """The eight families, their signals, thresholds, owner and version. §20.

    Also what this deployment CANNOT watch for and why (§7). A watchlist
    missing a whole family because a column was never loaded is worse than one
    that says which family it is missing.
    """
    from backend.early_warning import taxonomy as tx

    return tx.describe()


@router.get("/signals", summary="The book, by governed signal")
def signals(period: str = "", limit: int = 100) -> dict:
    """Every borrower's early-warning standing at one reporting period. §28.

    Ranked by breadth of independent evidence, then severity, then
    persistence, then how many conditions are getting worse — every step a
    count somebody can check, and the borrower id last so the ordering is
    total (§11).

    There is deliberately no score in the response.
    """
    from backend.early_warning import signals as sg

    try:
        return sg.portfolio(period, limit=max(1, min(int(limit), 500)))
    except Exception as exc:  # noqa: BLE001 - said, never substituted
        logger.warning("The signal portfolio could not be built: %s", exc)
        raise _unavailable(exc) from exc


@router.get("/signals/{borrower_id}", summary="One borrower's signal standing")
def borrower_signals(borrower_id: str, period: str = "") -> dict:
    """What fires for this borrower, what has cured, and what was not tested.

    All three, because "nothing fires" and "nothing could be tested" are
    different answers and only one of them is reassuring.
    """
    from backend.corporate import service as corporate
    from backend.early_warning import signals as sg

    try:
        snapshot = corporate._load(corporate.SNAPSHOT)
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(exc) from exc

    periods = sorted((str(p) for p in snapshot["period"].unique()),
                     key=sg._period_key)
    chosen = period or (periods[-1] if periods else "")
    index = periods.index(chosen) if chosen in periods else -1
    prior = periods[index - 1] if index > 0 else ""

    rows = snapshot[(snapshot["period"] == chosen)
                    & (snapshot["borrower_id"] == borrower_id)]
    if rows.empty:
        raise _not_found(LookupError(
            f"{borrower_id} is not on book at {chosen}."))
    before = snapshot[(snapshot["period"] == prior)
                      & (snapshot["borrower_id"] == borrower_id)]

    standing = sg.stand(
        rows.iloc[0].to_dict(),
        before.iloc[0].to_dict() if not before.empty else {},
        borrower_id=borrower_id, period=chosen, previous_period=prior)
    return standing.to_dict()


# =================================================================== reading


@router.get("", summary="What the Forward Risk Signal is and what it has")
def overview() -> dict:
    return ew.overview()


@router.get("/methodology", summary="The factor architecture, in full")
def methodology() -> dict:
    """Every family, every factor, every band — the whole specification of what
    the signal is made of, before any model is fitted."""
    return {
        "capability": lc.CAPABILITY_LABEL,
        "notice": lc.CAPABILITY_NOTICE,
        "targets": [t.to_dict() for t in TARGETS],
        "families": [
            {
                **family.to_dict(),
                "factors": [f.to_dict() for f in FACTORS if f.family == family.id],
            }
            for family in FACTOR_FAMILIES
        ],
        "bands": [{"band": band, "floor_pct": floor} for band, floor in BANDS],
        "form": (
            "score = intercept + sum(weight x standardised factor); "
            "probability = 1 / (1 + exp(-score)). Every facility's score "
            "decomposes exactly into one contribution per factor, and those "
            "contributions add up to the score."
        ),
        "document": "docs/EARLY_WARNING_METHODOLOGY.md",
    }


@router.get("/{target_id}/scores", summary="The book, scored")
def scores(target_id: str, period: str | None = None,
           limit: int = Query(default=200, ge=1, le=2000)) -> dict:
    """Score every eligible facility with the active model for this target.

    Returns the full decomposition per facility, so a screen never has to ask
    the model a second question to explain the first answer.
    """
    try:
        spec = ew.active_specification(target_id)
    except UnknownTargetError as e:
        raise _not_found(e) from e
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "no_active_model",
                "message": (
                    "No Forward Risk Signal model has been fitted for this "
                    "target yet. An administrator can fit one in the Model Lab."
                ),
            },
        )
    try:
        body = ew.score_book(spec, period=period, limit=limit)
    except ew.EarlyWarningError as e:
        raise _refused(e, "cannot_score") from e
    return {**body, "notice": lc.CAPABILITY_NOTICE}


@router.get("/{target_id}/facility/{account_id}", summary="Why one facility scored")
def facility(target_id: str, account_id: str, period: str | None = None) -> dict:
    try:
        spec = ew.active_specification(target_id)
    except UnknownTargetError as e:
        raise _not_found(e) from e
    if spec is None:
        raise _not_found(LookupError("No model is active for this target."))

    body = ew.score_book(spec, period=period)
    match = next(
        (s for s in body["scored"] if s["account_id"] == account_id), None
    )
    if match is None:
        raise _not_found(LookupError(
            f"Facility {account_id} is not eligible for {body['target']['label']} "
            f"in {body['period']}."
        ))
    return {
        "period": body["period"],
        "target": body["target"],
        "facility": match,
        "families": body["families"],
        "notice": lc.CAPABILITY_NOTICE,
    }


# ================================================================= model lab


class FitIn(BaseModel):
    target_id: str = Field(max_length=48)
    test_quarters: int = Field(default=ew.DEFAULT_TEST_QUARTERS, ge=1, le=6)
    name: str = Field(default="", max_length=200)
    change_note: str = Field(default="", max_length=MAX_TEXT)
    notes: str = Field(default="", max_length=MAX_TEXT)
    #: Store the result as a new version rather than only reporting it.
    save: bool = True
    activate: bool = True


class CompareIn(BaseModel):
    from_model_id: int
    to_model_id: int
    period: str | None = Field(default=None, max_length=64)


@router.get("/lab/models", summary="Every fitted model version")
def models(target_id: str | None = None,
           principal: Principal = RequireAdmin) -> dict:
    return {"models": ew.versions(target_id)}


@router.post("/lab/fit", summary="Fit a model and backtest it out of time")
def fit(payload: FitIn, principal: Principal = RequireAdmin) -> dict:
    """Fit on the early quarters and test on the ones held back.

    A fit is never silently adopted: the backtest comes back with it, and the
    stored version is a PROTOTYPE regardless of how good the numbers look.
    """
    try:
        result = ew.fit_and_backtest(
            payload.target_id, test_quarters=payload.test_quarters,
            notes=payload.notes,
        )
    except UnknownTargetError as e:
        raise _not_found(e) from e
    except (ew.EarlyWarningError, ValueError) as e:
        raise _refused(e, "cannot_fit") from e

    body = result.to_dict()
    if not payload.save:
        return {**body, "saved": None, "notice": lc.CAPABILITY_NOTICE}
    try:
        saved = ew.save_version(
            result, name=payload.name, change_note=payload.change_note,
            user_id=principal.user_id, activate=payload.activate,
        )
    except ew.StorageUnavailable as e:
        raise _unavailable(e) from e
    return {**body, "saved": saved, "notice": lc.CAPABILITY_NOTICE}


@router.get("/lab/models/{model_id}", summary="One model version, in full")
def model(model_id: int, principal: Principal = RequireAdmin) -> dict:
    try:
        return ew.get_version(model_id)
    except ew.ModelNotFound as e:
        raise _not_found(e) from e
    except ew.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/lab/models/{model_id}/activate", summary="Put a version into use")
def activate(model_id: int, principal: Principal = RequireAdmin) -> dict:
    try:
        return ew.activate(model_id, user_id=principal.user_id)
    except ew.ModelNotFound as e:
        raise _not_found(e) from e
    except ew.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/lab/compare", summary="What changing the model would do")
def compare(payload: CompareIn, principal: Principal = RequireAdmin) -> dict:
    """Impact analysis: consequences, not coefficients.

    Both models are run over the same facilities in the same period, and the
    answer is which facilities change band and how much exposure moves with
    them.
    """
    try:
        return ew.compare_versions(
            payload.from_model_id, payload.to_model_id, period=payload.period,
        )
    except ew.ModelNotFound as e:
        raise _not_found(e) from e
    except ew.EarlyWarningError as e:
        raise _refused(e, "cannot_compare") from e
    except ew.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.get("/lab/models/{model_id}/backtest", summary="A stored model's backtest")
def backtest(model_id: int, principal: Principal = RequireAdmin) -> dict:
    try:
        stored = ew.get_version(model_id)
    except ew.ModelNotFound as e:
        raise _not_found(e) from e
    except ew.StorageUnavailable as e:
        raise _unavailable(e) from e

    specification = stored["specification"]
    return {
        "model": {k: v for k, v in stored.items() if k != "specification"},
        "specification": SignalSpecification.from_dict(specification).to_dict(),
        "backtest": specification.get("backtest"),
        "notice": stored["notice"],
    }


__all__ = ["router"]
