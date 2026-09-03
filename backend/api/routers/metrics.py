"""The Metric Catalogue over HTTP.

What a caller can do here: search the catalogue, read everything a metric
means, calculate one, look at the rows behind it, build one of their own, and
record a check of it against a number they already trusted.

What a caller cannot do: supply a figure, or supply a formula as text. A
metric is submitted as a structured formula, validated against the governed
data catalogue, and compiled to the same analytical plan every other analysis
in CreditProbe uses. There is no path from a request body to SQL.

On permissions
--------------
Access is by role, as everywhere else in this codebase: reading needs an
analyst, building and verifying need one too. CreditProbe does not currently
model per-dataset read permissions — every analyst may read every published
dataset — so the routes pass no dataset restriction. The service layer takes
`readable` and applies it before ranking rather than after, so when
dataset-level permissions do arrive, one place changes and no metric can be
suggested over data the asker cannot see in the meantime.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst
from backend.metrics import library, service
from backend.metrics import search as search_mod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])

MAX_TEXT = 2000


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)})


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "metric_refused", "message": str(exc)})


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "storage_unavailable", "message": str(exc)})


# ------------------------------------------------------------------- shapes


class MetricIn(BaseModel):
    """A metric somebody built.

    `formula` is a structured object, not an expression to parse. That is the
    security property: nothing here becomes SQL by string substitution, and a
    formula naming a field the catalogue does not have is refused before it is
    stored rather than failing at render time on somebody's dashboard.
    """

    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(default="", max_length=MAX_TEXT)
    formula: dict = Field(default_factory=dict)
    unit: str = Field(default="number", max_length=24)
    domain: str = Field(default="", max_length=120)
    portfolio: str = Field(default="", max_length=120)
    presentation: dict = Field(default_factory=dict)
    shared: bool = False


class MetricPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    definition: str | None = Field(default=None, max_length=MAX_TEXT)
    formula: dict | None = None
    unit: str | None = Field(default=None, max_length=24)
    presentation: dict | None = None
    shared: bool | None = None


class StatusIn(BaseModel):
    status: str = Field(max_length=32)


class VerifyIn(BaseModel):
    """A number somebody already trusted, put beside the one CreditProbe made."""

    expected: float | None = None
    period: str = Field(default="", max_length=32)
    expected_source: str = Field(default="", max_length=240)
    note: str = Field(default="", max_length=MAX_TEXT)
    tolerance: float = Field(default=service.DEFAULT_TOLERANCE, ge=0.0, le=1.0)
    decision: str = Field(default=service.DECISION_RECORDED, max_length=24)


# ------------------------------------------------------------------ reading


@router.get("", summary="Search the metric catalogue")
def find_metrics(q: str = Query(default="", max_length=200),
                 limit: int = Query(default=search_mod.DEFAULT_LIMIT,
                                    ge=1, le=50),
                 domain: str = Query(default="", max_length=120),
                 principal: Principal = RequireAnalyst) -> dict:
    """Typeahead. An empty query returns nothing, deliberately.

    §8.3: the picker does not open with the whole catalogue. `/metrics/all` is
    the deliberate way to see everything.
    """
    return service.find(q, user_id=principal.user_id, limit=limit,
                        domain=domain)


@router.get("/all", summary="The whole catalogue, grouped by domain")
def browse_metrics(principal: Principal = RequireAnalyst) -> dict:
    groups = search_mod.browse(service.catalogue(user_id=principal.user_id))
    return {
        "domains": [
            {"domain": domain,
             "metrics": [m.panel() for m in metrics]}
            for domain, metrics in groups],
        "unavailable": [u.to_dict() for u in library.UNSUPPORTED],
        "version": library.LIBRARY_VERSION,
    }


@router.get("/vocabulary", summary="What a metric may be built from")
def metric_vocabulary(principal: Principal = RequireAnalyst) -> dict:
    """The datasets, fields and operations a metric may name.

    The builder offers only these. That is the point: a person composing a
    metric picks from what the governed catalogue actually holds, so a
    definition naming a field that does not exist cannot be assembled in the
    first place — and the server refuses it again on submission, because a
    picker is a convenience and never a control.
    """
    from backend.metrics import formula as formula_mod

    datasets: list[dict] = []
    catalog = service._catalog()
    if catalog is not None:
        # The datasets the governed library already reads. A metric builder
        # that offered all 77 would be offering a person the chance to build
        # something nobody can interpret.
        for name in sorted({d for m in library.ALL for d in m.datasets}):
            try:
                entry = catalog.dataset(name)
            except Exception:  # noqa: BLE001 - a dataset that has gone
                continue
            datasets.append({
                "name": entry.name,
                "business_name": entry.business_name,
                "purpose": entry.purpose,
                "grain": entry.grain,
                "period_field": entry.period_field,
                "fields": [{
                    "name": field.name,
                    "business_name": field.business_name,
                    "definition": field.definition,
                    "data_type": field.data_type,
                    "unit": field.unit,
                    "allowed_values": list(field.allowed_values or []),
                } for field in entry.fields.values()],
            })

    return {
        "datasets": datasets,
        "kinds": list(formula_mod.KINDS),
        "aggregations": dict(formula_mod.AGGREGATIONS),
        "comparisons": dict(formula_mod.COMPARISONS),
        "combiners": list(formula_mod.COMBINERS),
        "units": list(formula_mod.UNITS),
        "needs_denominator": list(formula_mod.NEEDS_DENOMINATOR),
        "domains": sorted({m.domain for m in library.ALL if m.domain}),
    }


@router.post("/preview", summary="What a formula would produce, before storing it")
def preview_metric(payload: MetricIn,
                   period: str = Query(default="", max_length=32),
                   principal: Principal = RequireAnalyst) -> dict:
    """Compile and run a formula without keeping it.

    So somebody building a metric sees the number and the working before they
    commit to a definition, and sees the refusal — with the reason — before
    they have named something that cannot calculate.
    """
    from backend.metrics import execution

    try:
        formula = service.formula_from_dict(payload.formula)
    except service.MetricRefused as e:
        raise _refused(e) from e

    try:
        calculation = execution.run(formula, period=period,
                                    question=payload.name or "metric preview")
    except Exception as e:  # noqa: BLE001 - a preview must never 500
        logger.info("metric preview could not be produced", exc_info=True)
        return {"available": False, "value": None, "unavailable": str(e),
                "formula": formula.describe()}

    return {
        "available": calculation.value is not None,
        "value": calculation.value,
        "unit": payload.unit,
        "unavailable": calculation.unavailable,
        "formula": formula.describe(),
        "calculation": calculation.to_dict(),
    }


@router.get("/{metric_id}", summary="Everything one metric means")
def read_metric(metric_id: str,
                principal: Principal = RequireAnalyst) -> dict:
    """The §6 info panel: definition, formula, sources, filters, caveats."""
    try:
        return service.panel(metric_id, user_id=principal.user_id)
    except service.MetricNotFound as e:
        absent = service.unavailable(metric_id)
        if absent is not None:
            # Known, and known to be uncalculable here. A reader asking for it
            # deserves the reason rather than a bare 404.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "metric_unavailable", "message": absent.because,
                        "metric": absent.to_dict()}) from e
        raise _not_found(e) from e


@router.get("/{metric_id}/value", summary="Calculate a metric now")
def compute_metric(metric_id: str,
                   period: str = Query(default="", max_length=32),
                   principal: Principal = RequireAnalyst) -> dict:
    try:
        return service.value(metric_id, period=period,
                             user_id=principal.user_id)
    except service.MetricNotFound as e:
        raise _not_found(e) from e


@router.get("/{metric_id}/rows", summary="A sample of the rows behind it")
def metric_rows(metric_id: str,
                period: str = Query(default="", max_length=32),
                limit: int = Query(default=25, ge=1, le=200),
                principal: Principal = RequireAnalyst) -> dict:
    """§10.4's record-level proxy, with the inclusion logic worked out."""
    try:
        return service.rows(metric_id, period=period, limit=limit,
                            user_id=principal.user_id)
    except service.MetricNotFound as e:
        raise _not_found(e) from e


# ------------------------------------------------------------------ writing


@router.post("", status_code=201, summary="Build a metric")
def create_metric(payload: MetricIn,
                  principal: Principal = RequireAnalyst) -> dict:
    try:
        formula = service.formula_from_dict(payload.formula)
        metric = service.create(
            name=payload.name, formula=formula, definition=payload.definition,
            unit=payload.unit, domain=payload.domain,
            portfolio=payload.portfolio, presentation=payload.presentation,
            shared=payload.shared, user_id=principal.user_id)
    except service.MetricRefused as e:
        raise _refused(e) from e
    except service.StorageUnavailable as e:
        raise _unavailable(e) from e
    return metric.panel()


@router.patch("/{metric_id}", summary="Change a metric you built")
def patch_metric(metric_id: str, payload: MetricPatch,
                 principal: Principal = RequireAnalyst) -> dict:
    """Changing the arithmetic drops it back to draft and clears its tick."""
    try:
        formula = (service.formula_from_dict(payload.formula)
                   if payload.formula is not None else None)
        metric = service.update(
            metric_id, user_id=principal.user_id, name=payload.name,
            formula=formula, definition=payload.definition, unit=payload.unit,
            presentation=payload.presentation, shared=payload.shared)
    except service.MetricNotFound as e:
        raise _not_found(e) from e
    except service.MetricRefused as e:
        raise _refused(e) from e
    except service.StorageUnavailable as e:
        raise _unavailable(e) from e
    return metric.panel()


@router.delete("/{metric_id}", status_code=204, summary="Delete a metric")
def remove_metric(metric_id: str,
                  principal: Principal = RequireAnalyst) -> None:
    try:
        service.delete(metric_id, user_id=principal.user_id)
    except service.MetricNotFound as e:
        raise _not_found(e) from e
    except service.MetricRefused as e:
        raise _refused(e) from e
    except service.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{metric_id}/status", summary="Move a metric along its lifecycle")
def set_metric_status(metric_id: str, payload: StatusIn,
                      principal: Principal = RequireAnalyst) -> dict:
    """VERIFIED is not settable here — it is conferred by an accepted check."""
    try:
        return service.set_status(metric_id, payload.status,
                                  user_id=principal.user_id).panel()
    except service.MetricNotFound as e:
        raise _not_found(e) from e
    except service.MetricRefused as e:
        raise _refused(e) from e
    except service.StorageUnavailable as e:
        raise _unavailable(e) from e


@router.post("/{metric_id}/calculate", summary="Check that it calculates")
def check_metric(metric_id: str,
                 period: str = Query(default="", max_length=32),
                 principal: Principal = RequireAnalyst) -> dict:
    """Runs it once. A draft that produces a number becomes CALCULATION_READY.

    That is the only promotion without a person in it, and it says nothing
    about whether the number is right — which is what verification is for.
    """
    try:
        return service.calculate_check(metric_id, period=period,
                                       user_id=principal.user_id)
    except service.MetricNotFound as e:
        raise _not_found(e) from e


# ------------------------------------------------------------- verification


@router.post("/{metric_id}/verify", summary="Check it against your own number")
def verify_metric(metric_id: str, payload: VerifyIn,
                  principal: Principal = RequireAnalyst) -> dict:
    """The computed value is never moved toward the expected one.

    If the two disagree, the record says they disagreed. A metric becomes
    verified only when they agree AND the person accepted it.
    """
    try:
        return service.verify(
            metric_id, expected=payload.expected, period=payload.period,
            expected_source=payload.expected_source, note=payload.note,
            tolerance=payload.tolerance, decision=payload.decision,
            user_id=principal.user_id)
    except service.MetricNotFound as e:
        raise _not_found(e) from e
    except service.MetricRefused as e:
        raise _refused(e) from e


@router.get("/{metric_id}/verifications", summary="What has been checked")
def metric_verifications(metric_id: str,
                         limit: int = Query(default=25, ge=1, le=100),
                         principal: Principal = RequireAnalyst) -> dict:
    """Kept whether the checks agreed or not."""
    try:
        service.resolve(metric_id, user_id=principal.user_id)
    except service.MetricNotFound as e:
        raise _not_found(e) from e
    return {"metric_id": metric_id,
            "verifications": service.verifications(metric_id, limit=limit),
            "outcomes": [service.OUTCOME_MATCH, service.OUTCOME_WITHIN,
                         service.OUTCOME_DIFFERS, service.OUTCOME_NOT_COMPARED],
            "decisions": list(service.DECISIONS)}
