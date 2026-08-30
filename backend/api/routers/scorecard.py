"""Retail Scorecard Validation, over HTTP. §17-§21, §34-§36, §87.

Everything here is deterministic and reads the Parquet lake. No route calls
a provider, and none of them spends anything: a validation dashboard is a
screen somebody opens every morning, and one that cost money to open is one
nobody opens.

Two contracts the routes hold
------------------------------
**Maturity is answered, not assumed.** Every response carries the latest
data month, the latest fully matured month and the horizon. A route asked
for an outcome metric on an immature cohort returns a refusal explaining
when the window closes, never a number.

**A candidate is never an activation.** §35: a natural-language model edit
produces a CANDIDATE. The route that builds one requires
SCORECARD_MODEL_EDIT_CANDIDATE; the route that approves one requires
SCORECARD_MODEL_APPROVE, which is a narrower set. Proposing a change to a
credit model and accepting it are different acts.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireScorecardAnalyse,
    RequireScorecardModelEdit,
    RequireScorecardModelView,
    RequireScorecardView,
)
from backend.scorecard import build as build_mod
from backend.scorecard import catalogue as catalogue_mod
from backend.scorecard import dashboard as dash
from backend.scorecard import diagnostics as diagnostics_mod
from backend.scorecard import equation as equation_mod
from backend.scorecard import metrics as metrics_mod
from backend.scorecard import policy as policy_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scorecard", tags=["retail-scorecard-validation"])

APP = vars_mod.APPLICATION_SCORECARD
BEH = vars_mod.BEHAVIORAL_SCORECARD


def _refused(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "validation_refused", "message": str(exc)})


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": str(exc)})


def _check_type(scorecard_type: str) -> str:
    upper = scorecard_type.upper()
    if upper not in vars_mod.SCORECARD_TYPES:
        raise _refused(ValueError(
            f"{scorecard_type!r} is not a scorecard type; expected "
            f"{' or '.join(vars_mod.SCORECARD_TYPES)}"))
    return upper


# =============================================================== §17 OVERVIEW


@router.get("/overview")
def overview(principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """§17/§18. What exists, and which month each side opens on."""
    body: dict[str, Any] = {
        "module": "RETAIL SCORECARD VALIDATION",
        "scorecard_types": list(vars_mod.SCORECARD_TYPES),
        "origin": synth.ORIGIN,
        "not_client_data": (
            "Every figure in this module is computed over synthetic "
            "demonstration data. It describes no real customer and no real "
            "bank's book."),
        "scorecards": {},
        "domains": catalogue_mod.summary(),
    }
    for scorecard_type in vars_mod.SCORECARD_TYPES:
        try:
            months = dash.available_months(scorecard_type)
        except Exception:  # noqa: BLE001 - an unbuilt lake is a real state
            body["scorecards"][scorecard_type] = {
                "available": False,
                "why": ("The demonstration universe has not been built. Run "
                        "scripts/build_retail_scorecards.py."),
            }
            continue
        matured = [m for m in months if synth.matured(m)]
        body["scorecards"][scorecard_type] = {
            "available": bool(months),
            "months": months,
            "month_count": len(months),
            "latest_data_month": months[-1] if months else "",
            "latest_matured_performance_month": matured[-1] if matured
            else "",
            "performance_horizon_months": synth.DEFAULT_HORIZON_MONTHS,
            "models": list(build_mod.MODEL_KINDS),
            "candidate_variables": len(vars_mod.catalogue(scorecard_type)),
            "families": list(build_mod.FAMILIES[scorecard_type]),
        }
    return body


@router.get("/policy")
def validation_policy(principal: Principal = RequireScorecardView
                      ) -> dict[str, Any]:
    """§50/§80/§81. The limits, and where each one came from."""
    return policy_mod.catalogue()


# ============================================================== §22 DASHBOARD


@router.get("/dashboard/{scorecard_type}")
def dashboard(scorecard_type: str,
              model: str = Query(default="INCUMBENT"),
              month: str = Query(default=""),
              segment_by: str = Query(default=""),
              curves: bool = Query(default=True),
              principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """§22/§47. The whole validation dashboard for one model and month."""
    kind = _check_type(scorecard_type)
    try:
        return dash.build_dashboard(
            kind, model_kind=model.upper(), month=month,
            segment_by=segment_by, curves=curves).to_dict()
    except dash.DashboardError as exc:
        raise _not_found(exc) from exc
    except metrics_mod.MetricError as exc:
        raise _refused(exc) from exc


@router.get("/months/{scorecard_type}")
def months(scorecard_type: str,
           principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """§44's month picker, with maturity marked on each."""
    kind = _check_type(scorecard_type)
    found = dash.available_months(kind)
    return {
        "scorecard_type": kind,
        "months": [
            {"month": month, "matured": synth.matured(month),
             "outcome_available_from": synth.add_months(
                 month, synth.DEFAULT_HORIZON_MONTHS)}
            for month in found
        ],
        "latest_data_month": found[-1] if found else "",
        "latest_matured_performance_month": next(
            (m for m in reversed(found) if synth.matured(m)), ""),
        "performance_horizon_months": synth.DEFAULT_HORIZON_MONTHS,
        "immature_months_are_stability_only": (
            "§44: a month whose performance window has not closed can be "
            "selected, and shows stability only. It has no observed default "
            "rate to compare a prediction against."),
    }


# ================================================================ §12 MODELS


@router.get("/models/{scorecard_type}")
def models(scorecard_type: str,
           principal: Principal = RequireScorecardModelView
           ) -> dict[str, Any]:
    """§12/§34. The registry: every version, its equation and its fit."""
    kind = _check_type(scorecard_type)
    try:
        registry = build_mod.load_models(kind)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    return {
        "scorecard_type": kind,
        "default_definition": registry["default_definition"],
        "score_mapping": registry["score_mapping"],
        "models": registry["models"],
        "answered_from_the_registry": (
            "§34: equation questions are answered from the model registry, "
            "never from a model's recollection of it."),
    }


@router.get("/models/{scorecard_type}/{model}/equation")
def equation(scorecard_type: str, model: str,
             principal: Principal = RequireScorecardModelView
             ) -> dict[str, Any]:
    """§13/§34. The exact equation, as a person would write it."""
    kind = _check_type(scorecard_type)
    try:
        found = build_mod.load_equation(kind, model.upper())
    except (FileNotFoundError, KeyError) as exc:
        raise _not_found(exc) from exc
    body = found.to_dict()
    body["pd_from_logit"] = "predicted_pd = 1 / (1 + exp(-logit_bad))"
    body["validation"] = equation_mod.validate(found).to_dict()
    return body


@router.get("/binning/{scorecard_type}")
def binning(scorecard_type: str,
            variable: str = Query(default=""),
            principal: Principal = RequireScorecardModelView
            ) -> dict[str, Any]:
    """§10/§34. The approved WoE bins, frozen at development."""
    kind = _check_type(scorecard_type)
    try:
        spec = build_mod.load_spec(kind)
    except FileNotFoundError as exc:
        raise _not_found(exc) from exc
    body = spec.to_dict()
    if variable:
        if variable not in spec.variables:
            raise _not_found(KeyError(
                f"{variable} has no approved binning in "
                f"{spec.spec_version}; the specification covers "
                + ", ".join(sorted(spec.variables))))
        body["variables"] = {variable: spec.variables[variable].to_dict()}
    return body


@router.get("/variables/{scorecard_type}")
def variables(scorecard_type: str,
              principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """§8/§9/§11. The candidate dictionary, and which are active."""
    kind = _check_type(scorecard_type)
    active = {model: list(names) for model, names
              in build_mod.MODEL_VARIABLES[kind].items()}
    return {
        "scorecard_type": kind,
        "candidates": [v.to_dict() for v in vars_mod.catalogue(kind)],
        "candidate_count": len(vars_mod.catalogue(kind)),
        "active_by_model": active,
        "sensitive_excluded_from_scoring": vars_mod.sensitive(kind),
        "candidate_is_not_active": (
            "§11. The dataset carries every candidate above; an active "
            "scorecard uses five or six of them. A drift report on all of "
            "them is not a report on the model."),
    }


# ============================================================ §28-§32 DIAGNOSTICS


@router.get("/diagnose/{scorecard_type}/low-discrimination")
def low_discrimination(scorecard_type: str,
                       model: str = Query(default="INCUMBENT"),
                       month: str = Query(default=""),
                       question: str = Query(default=""),
                       leave_one_out: bool = Query(default=True),
                       principal: Principal = RequireScorecardAnalyse
                       ) -> dict[str, Any]:
    """§28/§58. "KS is poor — which variable is responsible?" """
    kind = _check_type(scorecard_type)
    try:
        return diagnostics_mod.low_discrimination(
            kind, month=month, model_kind=model.upper(), question=question,
            leave_one_out=leave_one_out).to_dict()
    except metrics_mod.ImmatureCohortError as exc:
        raise _refused(exc) from exc
    except dash.DashboardError as exc:
        raise _not_found(exc) from exc


@router.get("/diagnose/{scorecard_type}/accuracy")
def accuracy(scorecard_type: str,
             model: str = Query(default="INCUMBENT"),
             month: str = Query(default=""),
             question: str = Query(default=""),
             principal: Principal = RequireScorecardAnalyse
             ) -> dict[str, Any]:
    """§29/§59. "Accuracy deteriorated — what changed?" """
    kind = _check_type(scorecard_type)
    try:
        return diagnostics_mod.accuracy_deterioration(
            kind, month=month, model_kind=model.upper(),
            question=question).to_dict()
    except dash.DashboardError as exc:
        raise _not_found(exc) from exc


@router.get("/trend/{scorecard_type}/odr")
def odr_trend(scorecard_type: str,
              months_back: int = Query(default=20, ge=1, le=60),
              model: str = Query(default="INCUMBENT"),
              principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """§30/§60. Observed default rate against average predicted PD."""
    kind = _check_type(scorecard_type)
    try:
        return diagnostics_mod.odr_trend(kind, months=months_back,
                                         model_kind=model.upper())
    except dash.DashboardError as exc:
        raise _not_found(exc) from exc


@router.get("/trend/{scorecard_type}/score")
def score_trend(scorecard_type: str,
                months_back: int = Query(default=12, ge=1, le=60),
                model: str = Query(default="INCUMBENT"),
                principal: Principal = RequireScorecardView
                ) -> dict[str, Any]:
    """§31. Has the score pattern changed?"""
    kind = _check_type(scorecard_type)
    try:
        return diagnostics_mod.score_trend(kind, months=months_back,
                                           model_kind=model.upper())
    except dash.DashboardError as exc:
        raise _not_found(exc) from exc


@router.get("/drift/{scorecard_type}")
def drift(scorecard_type: str,
          model: str = Query(default="INCUMBENT"),
          month: str = Query(default=""),
          candidates: bool = Query(default=False),
          principal: Principal = RequireScorecardView) -> dict[str, Any]:
    """§32. CSI for the active variables, or for every candidate."""
    kind = _check_type(scorecard_type)
    try:
        return diagnostics_mod.variable_drift(
            kind, month=month, model_kind=model.upper(),
            candidates=candidates)
    except dash.DashboardError as exc:
        raise _not_found(exc) from exc


@router.get("/segments/{scorecard_type}")
def segments(scorecard_type: str,
             by: str = Query(...),
             model: str = Query(default="INCUMBENT"),
             month: str = Query(default=""),
             principal: Principal = RequireScorecardAnalyse
             ) -> dict[str, Any]:
    """§40. Performance by segment, with sufficiency per segment."""
    kind = _check_type(scorecard_type)
    try:
        context = dash.resolve(kind, model_kind=model.upper(), month=month)
        frame = dash.load_month(kind, context.month)
        return dash.segment_section(frame, context, by=by)
    except dash.DashboardError as exc:
        raise _not_found(exc) from exc
    except metrics_mod.MetricError as exc:
        raise _refused(exc) from exc


# ================================================== §16/§35 CANDIDATE MODELS


class TermBody(BaseModel):
    variable: str = Field(..., max_length=80)
    coefficient: float


class CandidateBody(BaseModel):
    """§35. A candidate model version. Never an activation."""

    model_name: str = Field(..., max_length=120)
    intercept: float
    terms: list[TermBody] = Field(..., max_length=30)
    based_on: str = Field(default="INCUMBENT", max_length=32)


@router.post("/models/{scorecard_type}/candidate")
def create_candidate(scorecard_type: str, body: CandidateBody,
                     principal: Principal = RequireScorecardModelEdit
                     ) -> dict[str, Any]:
    """§16/§35. Validate a proposed equation and show the diff.

    Produces a CANDIDATE and nothing else. It is not stored as active, it
    is not scored into the lake, and approving it is a separate permission
    held by a narrower set of roles.
    """
    kind = _check_type(scorecard_type)
    try:
        current = build_mod.load_equation(kind, body.based_on.upper())
        spec = build_mod.load_spec(kind)
    except (FileNotFoundError, KeyError) as exc:
        raise _not_found(exc) from exc

    candidate = equation_mod.Equation(
        model_name=body.model_name, scorecard_type=kind,
        intercept=body.intercept,
        terms=[equation_mod.Term(variable=t.variable,
                                 coefficient=t.coefficient)
               for t in body.terms],
        binning_spec_version=spec.spec_version,
        score_mapping=current.score_mapping,
        output_prefix="candidate")

    validation = equation_mod.validate(candidate, spec=spec)
    return {
        "candidate": candidate.to_dict(),
        "validation": validation.to_dict(),
        "diff": equation_mod.diff(current, candidate),
        "status": "CANDIDATE",
        "activated": False,
        "what_happens_next": (
            "This is a candidate. It has not been activated, nothing has "
            "been rescored with it, and the active model is unchanged. "
            "Activating it requires SCORECARD_MODEL_APPROVE, which is a "
            "narrower permission than the one that created it — proposing a "
            "change to a credit model and accepting it are different acts."),
    }


class RescoreBody(BaseModel):
    model_name: str = Field(..., max_length=120)
    intercept: float
    terms: list[TermBody] = Field(..., max_length=30)
    months: list[str] = Field(..., max_length=24)
    based_on: str = Field(default="INCUMBENT", max_length=32)


@router.post("/models/{scorecard_type}/rescore")
def rescore(scorecard_type: str, body: RescoreBody,
            principal: Principal = RequireScorecardModelEdit
            ) -> dict[str, Any]:
    """§35. Score a candidate over chosen months and compare it.

    Deterministic and in memory. Nothing is written to the lake: a candidate
    that had already replaced the stored scores would be an activation
    wearing a different name.
    """
    kind = _check_type(scorecard_type)
    try:
        current = build_mod.load_equation(kind, body.based_on.upper())
        spec = build_mod.load_spec(kind)
    except (FileNotFoundError, KeyError) as exc:
        raise _not_found(exc) from exc

    candidate = equation_mod.Equation(
        model_name=body.model_name, scorecard_type=kind,
        intercept=body.intercept,
        terms=[equation_mod.Term(variable=t.variable,
                                 coefficient=t.coefficient)
               for t in body.terms],
        binning_spec_version=spec.spec_version,
        score_mapping=current.score_mapping, output_prefix="candidate")

    validation = equation_mod.validate(candidate, spec=spec)
    if not validation.valid:
        raise _refused(ValueError(
            "the candidate equation did not validate: "
            + "; ".join(p.detail for p in validation.blockers)))

    available = set(dash.available_months(kind))
    unknown = [m for m in body.months if m not in available]
    if unknown:
        raise _not_found(KeyError(
            "not available: " + ", ".join(unknown)))

    direction = (current.score_mapping.score_direction
                 if current.score_mapping else "")
    rows: list[dict[str, Any]] = []
    for month in body.months:
        frame = dash.load_month(kind, month)
        if not synth.matured(month):
            rows.append({
                "month": month, "comparable": False,
                "why": ("no realised outcome: this month's performance "
                        "window has not closed"),
            })
            continue
        scored = build_mod.score_frame(
            frame, {"CANDIDATE": candidate}, spec)
        candidate_found = metrics_mod.discrimination(
            scored, score="score_candidate", target="actual_default",
            score_direction=direction)
        incumbent_found = metrics_mod.discrimination(
            frame, score=f"score_{build_mod.OUTPUT_SUFFIX[body.based_on.upper()]}",
            target="actual_default", score_direction=direction)
        rows.append({
            "month": month, "comparable": True,
            "observations": len(frame),
            "candidate": {"gini": round(candidate_found.gini, 6),
                          "ks": round(candidate_found.ks, 6),
                          "auc": round(candidate_found.auc, 6)},
            "baseline": {"gini": round(incumbent_found.gini, 6),
                         "ks": round(incumbent_found.ks, 6),
                         "auc": round(incumbent_found.auc, 6)},
            "gini_delta": round(candidate_found.gini - incumbent_found.gini,
                                6),
            "evidence": candidate_found.evidence,
        })

    comparable = [r for r in rows if r.get("comparable")]
    return {
        "candidate": candidate.to_dict(),
        "validation": validation.to_dict(),
        "diff": equation_mod.diff(current, candidate),
        "compared_against": body.based_on.upper(),
        "months": rows,
        "months_comparable": len(comparable),
        "mean_gini_delta": (
            round(sum(r["gini_delta"] for r in comparable) / len(comparable),
                  6) if comparable else None),
        "activated": False,
        "nothing_was_written": (
            "The candidate was scored in memory and compared. No stored "
            "score changed and the active model is untouched — a candidate "
            "that had already replaced the stored scores would be an "
            "activation wearing a different name."),
    }
