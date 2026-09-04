"""The Scorecard Validation Intelligence cockpit, over HTTP.

Three scorecards, forty-eight tests, and one rule that shapes every route
here: a response never contains a number the engine did not measure. A test
that could not run comes back with its state, its explanation and no value,
and the client renders the explanation. There is no field a chart can read
that says 0.0 because a cohort has not matured.

What is deterministic and what is not
-------------------------------------
Everything on these routes is deterministic. Every figure comes from
`backend/scorecard/metrics.py` through `backend/scorecard/validation/runner`,
every verdict is `Limit.verdict` comparing a number to a governed threshold,
and no route calls a language model. The conversational surface is a separate
concern and reaches the same results through the same runner.

Domain isolation
----------------
`backend/scorecard/domains` is the boundary, and it is enforced below the
router rather than in it: `runner.population` calls
`domains.require_validation_domain`, and `models.get` refuses any id outside
the three. A route cannot widen that by passing a different argument, which
is the point — a permission check that lives in a handler is a permission
check somebody forgets to copy into the next handler.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from backend.api.permissions import (
    Principal,
    RequireScorecardAnalyse,
    RequireScorecardView,
)
from backend.scorecard import domains
from backend.scorecard.validation import (
    models as model_registry,
)
from backend.scorecard.validation import (
    registry as test_registry,
)
from backend.scorecard.validation import (
    runner,
    states,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scorecard-validation",
                   tags=["scorecard-validation-intelligence"])

#: A whole-model run touches every test on every period. It is a minute of
#: work on the larger books, not a page load, so the route that does it says
#: so rather than being called by accident from a dashboard poll.
FULL_RUN_IS_SLOW = (
    "A full run executes every applicable test over every period. On the "
    "larger books that is a minute or more of computation, most of it in the "
    "bootstrap resampling. Run it deliberately, not on a page refresh.")


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "validation_refused", "message": str(exc)})


def _forbidden(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "domain_refused", "message": str(exc)})


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)})


def _model(model_id: str) -> model_registry.Model:
    try:
        return model_registry.get(model_id)
    except domains.DomainRefused as e:
        raise _forbidden(e) from e


def _periods(period: str) -> tuple[str, ...]:
    """A comma-separated period list, or empty for the governed default.

    Parsed rather than trusted: this argument can arrive from a tool call
    whose parameters a language model wrote, and the runner reads it as a
    partition path.
    """
    wanted = tuple(p.strip() for p in period.split(",") if p.strip())
    for one in wanted:
        if not one.replace("-", "").isalnum():
            raise _refused(ValueError(
                f"{one!r} is not a period. A period is a month like "
                "2025-04."))
    return wanted


# ================================================================== what is


@router.get("/overview")
def overview(principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """The three scorecards, the test registry, and what each can support.

    Deliberately does not run anything. This is the route a page load calls,
    and a page that computed forty-eight tests to render a heading would be
    a page nobody opens twice.
    """
    scorecards: list[dict[str, Any]] = []
    for made in model_registry.all_models():
        entry = made.to_dict()
        try:
            available = runner.available_periods(made)
            matured = runner.matured_periods(made)
            entry["data"] = {
                "available": bool(available),
                "periods": len(available),
                "latest_period": available[-1] if available else "",
                "matured_periods": len(matured),
                "latest_matured_period": matured[-1] if matured else "",
                "immature_periods": len(available) - len(matured),
                "performance_window_months": made.performance_window_months,
                "why_immature": (
                    "A cohort whose performance window has not closed has no "
                    "realised outcome. It is reported as NOT YET MATURED, "
                    "never as zero defaults."),
            }
        except Exception as e:  # noqa: BLE001 - an unbuilt lake is a real state
            entry["data"] = {"available": False, "why": str(e)}
        entry["applicable_tests"] = [t.test_id
                                     for t in made.applicable_tests()]
        entry["inapplicable_tests"] = [
            {"test_id": t.test_id,
             "why": ", ".join(t.missing_for(made.capabilities()))}
            for t in made.inapplicable_tests()]
        scorecards.append(entry)

    return {
        "module": "SCORECARD VALIDATION INTELLIGENCE",
        "domains": domains.summary(),
        "scorecards": scorecards,
        "registry": test_registry.summary(),
        "result_states": [
            {"state": s, "label": states.STATE_LABELS[s],
             "meaning": states.STATE_MEANING[s],
             "carries_a_number": s in states.MEASURED}
            for s in states.STATES
        ],
        "full_run_cost": FULL_RUN_IS_SLOW,
    }


@router.get("/tests")
def tests(category: str = Query("", description="One category, or all"),
          principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """The test registry: what each test asks, and how it is calculated."""
    wanted = (test_registry.in_category(category) if category
              else test_registry.all_tests())
    if category and not wanted:
        raise _not_found(ValueError(
            f"{category!r} is not a validation category. They are: "
            f"{', '.join(test_registry.CATEGORIES)}."))
    return {
        "registry_version": test_registry.REGISTRY_VERSION,
        "category": category,
        "tests": [t.to_dict() for t in wanted],
    }


@router.get("/models/{model_id}")
def model(model_id: str,
          principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """One scorecard's governed record, including its limits and their source."""
    made = _model(model_id)
    body = made.to_dict()
    try:
        body["approved_specification"] = {
            "spec_version": getattr(made.approved_spec(), "spec_version", ""),
            "variables": list(made.binned_variables),
        }
    except Exception as e:  # noqa: BLE001 - reported, not hidden
        body["approved_specification"] = {"available": False, "why": str(e)}
    try:
        equation = made.approved_equation()
        body["approved_equation"] = {
            "equation": getattr(equation, "model_name", ""),
            "specification": getattr(equation, "binning_spec_version", ""),
            "link": getattr(equation, "link", ""),
            "terms": len(getattr(equation, "terms", ())),
        }
    except model_registry.ModelError as e:
        body["approved_equation"] = {"available": False, "why": str(e)}
    return body


# ================================================================ what it is


@router.post("/models/{model_id}/tests/{test_id}")
def run_one(model_id: str, test_id: str,
            period: str = Query("", description="Comma-separated months"),
            segment: str = Query(""),
            segment_field: str = Query(""),
            principal: Principal = RequireScorecardAnalyse
            ) -> dict[str, Any]:
    """Run one validation test and return its result, whatever that is.

    A refusal is a 200 carrying a refusal, not an error status. The client
    has to render it either way, and a test that legitimately cannot run on
    an immature cohort is not a fault in the request.
    """
    made = _model(model_id)
    wanted = test_registry.resolve(test_id)
    if wanted is None:
        raise _not_found(ValueError(
            f"{test_id!r} is not a validation test. There are "
            f"{len(test_registry.TESTS)}; see /scorecard-validation/tests."))
    result = runner.run(wanted.test_id, made, periods=_periods(period),
                        segment=segment, segment_field=segment_field)
    return {"test": wanted.to_dict(), "result": result.to_dict()}


@router.post("/models/{model_id}/categories/{category}")
def run_category(model_id: str, category: str,
                 period: str = Query(""),
                 segment_field: str = Query(""),
                 principal: Principal = RequireScorecardAnalyse
                 ) -> dict[str, Any]:
    """Every test in one category, refusals included.

    The refusals are returned rather than filtered, because a validation
    report has to state its own scope: "not applicable, no score-to-PD
    mapping" is a finding about the model, not an empty row.
    """
    made = _model(model_id)
    if category not in test_registry.CATEGORIES:
        raise _not_found(ValueError(
            f"{category!r} is not a validation category. They are: "
            f"{', '.join(test_registry.CATEGORIES)}."))
    results = runner.run_category(category, made, periods=_periods(period),
                                  segment_field=segment_field)
    return _package(made, category, results)


@router.post("/models/{model_id}/run")
def run_all(model_id: str,
            period: str = Query(""),
            principal: Principal = RequireScorecardAnalyse
            ) -> dict[str, Any]:
    """Every applicable test across every category. See `FULL_RUN_IS_SLOW`."""
    made = _model(model_id)
    results: list[states.Result] = []
    for category in test_registry.CATEGORIES:
        results.extend(runner.run_category(category, made,
                                           periods=_periods(period)))
    body = _package(made, "", results)
    body["cost"] = FULL_RUN_IS_SLOW
    return body


def _package(made: model_registry.Model, category: str,
             results: list[states.Result]) -> dict[str, Any]:
    """Results, ranked, tallied, and honest about its own coverage.

    The coverage block is not decoration. A reader looking at eleven passes
    needs to know whether that is eleven of eleven or eleven of forty-eight,
    and a summary that reports only what ran reads as the former.
    """
    ranked = states.rank(results)
    ran = {r.test_id for r in results if r.measured}
    return {
        "model": {"model_id": made.model_id, "name": made.name,
                  "version": made.version, "domain": made.domain,
                  "scorecard_type": made.scorecard_type},
        "category": category,
        "results": [r.to_dict() for r in ranked],
        "tally": states.tally(results),
        "adverse": [r.test_id for r in ranked if r.adverse],
        "measured": len(ran),
        "returned": len(results),
        "coverage": test_registry.coverage(ran),
        "coverage_means": (
            "A test counted here is one that produced a number. A test that "
            "refused is returned with its reason and is not counted as "
            "covered — the point of the distinction is that a validation "
            "opinion resting on tests that did not run is an opinion resting "
            "on nothing."),
        "calculation_version": runner.RUNNER_VERSION,
    }


# =============================================================== the periods


@router.get("/models/{model_id}/periods")
def periods(model_id: str,
            principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """Which months exist, and which of them have a realised outcome.

    The single most useful route on this router, because almost every wrong
    number in model validation comes from running an outcome metric over a
    window that has not closed.
    """
    made = _model(model_id)
    try:
        available = runner.available_periods(made)
        matured = set(runner.matured_periods(made))
    except Exception as e:  # noqa: BLE001 - an unbuilt lake is a real state
        raise _refused(e) from e
    return {
        "model_id": made.model_id,
        "performance_window_months": made.performance_window_months,
        "periods": [{"period": p, "matured": p in matured} for p in available],
        "latest_period": available[-1] if available else "",
        "latest_matured_period": (max(p for p in available if p in matured)
                                  if matured else ""),
        "immature": [p for p in available if p not in matured],
        "what_immature_means": (
            "The performance window for these cohorts has not closed. They "
            "carry no realised outcome — which is not the same as carrying "
            "no defaults, and every outcome test refuses them by name."),
    }


__all__ = ["router"]
