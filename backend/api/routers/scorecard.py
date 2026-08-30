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
    RequireScorecardFindingCreate,
    RequireScorecardModelApprove,
    RequireScorecardModelEdit,
    RequireScorecardModelView,
    RequireScorecardView,
)
from backend.db.engine import get_session
from backend.scorecard import build as build_mod
from backend.scorecard import catalogue as catalogue_mod
from backend.scorecard import dashboard as dash
from backend.scorecard import diagnostics as diagnostics_mod
from backend.scorecard import equation as equation_mod
from backend.scorecard import metrics as metrics_mod
from backend.scorecard import policy as policy_mod
from backend.scorecard import registry as registry_mod
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
    #: Record the proposal in the registry as a CANDIDATE version. Off by
    #: default because the same route is what the Studio calls to preview a
    #: diff while somebody is still editing, and a registry full of every
    #: keystroke is a registry nobody reads.
    record: bool = False
    notes: str = Field(default="", max_length=4000)


def _next_version(version: str) -> str:
    """The next minor version after a registered one.

    Minor rather than patch: a changed coefficient is a changed model, and
    calling that a patch invites somebody to treat it as one.
    """
    parts = (version or "1.0.0").split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        return f"{int(parts[0])}.{int(parts[1]) + 1}.0"
    except ValueError:
        return f"{version}-candidate"


@router.post("/models/{scorecard_type}/candidate")
def create_candidate(scorecard_type: str, body: CandidateBody,
                     principal: Principal = RequireScorecardModelEdit
                     ) -> dict[str, Any]:
    """§16/§35. Validate a proposed equation, show the diff, record it.

    Produces a CANDIDATE and nothing else. It is not stored as active, it
    is not scored into the lake, and approving it is a separate permission
    held by a narrower set of roles.

    With `record`, the proposal is written to the registry as a new
    CANDIDATE version alongside the model it was proposed from. The base
    model is not touched — that is the property §35 is actually asking for,
    and the reason the write adds a row rather than updating one.
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

    recorded: dict[str, Any] = {"recorded": False, "why_not": ""}
    if body.record:
        if not validation.valid:
            # A candidate with a BLOCKING problem is a proposal somebody
            # has to fix, not a version to file. Recording it would put an
            # equation the validator rejected into the same table as the
            # approved ones. Warnings do not stop it: a sign warning is a
            # finding about the model, and filing the model is how it gets
            # discussed.
            recorded["why_not"] = (
                "The proposed equation has "
                f"{len(validation.blockers)} blocking problem(s), so it was "
                "not recorded. Fix them and propose it again.")
        else:
            base_id = registry_mod.model_id_for(kind, body.based_on.upper())
            with get_session() as session:
                try:
                    base = registry_mod.get(session, base_id)
                    result = registry_mod.propose_candidate(
                        session, equation=candidate, based_on=base,
                        model_version=_next_version(base.model_version),
                        created_by=_actor(principal), notes=body.notes)
                except registry_mod.RegistryError as exc:
                    recorded["why_not"] = str(exc)
                else:
                    recorded = {"recorded": True, "why_not": "",
                                "model_id": result.model_id,
                                "model_version": result.model_version,
                                "status": result.status,
                                "based_on": (f"{base.model_id}:"
                                             f"{base.model_version}")}

    return {
        "candidate": candidate.to_dict(),
        "validation": validation.to_dict(),
        "diff": equation_mod.diff(current, candidate),
        "status": "CANDIDATE",
        "activated": False,
        "registry": recorded,
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


# ---------------------------------------------------------------------------
# The model registry. §12, §35, §94.
#
# These are the only routes here that touch PostgreSQL. Everything above
# reads the Parquet lake and computes; this reads and writes what the
# institution decided, which is a different kind of fact with a different
# lifetime. A dashboard survives a rebuild of the demonstration universe
# only because these rows do.
# ---------------------------------------------------------------------------


def _actor(principal: Principal) -> str:
    """Who to record as having decided something.

    The Principal carries a role and a user id, not a name — identity is
    resolved at the edge and the router never sees an address. Recording
    both is what makes "ADMIN #4 activated 1.1.0" answerable later; the role
    alone would say what kind of person did it and not which one.
    """
    role = getattr(principal.role, "value", str(principal.role))
    return f"{role}#{principal.user_id}" if principal.user_id else str(role)


def _model_payload(row: Any, variables: list[Any]) -> dict[str, Any]:
    return {
        "model_id": row.model_id,
        "model_name": row.model_name,
        "model_version": row.model_version,
        "scorecard_type": row.scorecard_type,
        "status": row.status,
        "owner": row.owner,
        "developer": row.developer,
        "validator": row.validator,
        "development_period": row.development_period,
        "validation_period": row.validation_period,
        "performance_horizon_months": row.performance_horizon_months,
        "default_definition": row.default_definition,
        "target": row.target,
        "population": row.population,
        "product_scope": row.product_scope,
        "binning_spec_version": row.binning_spec_version,
        "intercept": row.intercept,
        "equation": row.equation,
        "score_direction": row.score_direction,
        "base_score": row.base_score,
        "pdo": row.pdo,
        "base_odds": row.base_odds,
        "min_score": row.min_score,
        "max_score": row.max_score,
        "implementation_date": row.implementation_date,
        "last_validation_date": row.last_validation_date,
        "materiality": row.materiality,
        "model_risk_rating": row.model_risk_rating,
        "based_on_model_id": row.based_on_model_id,
        "origin": row.origin,
        "notes": row.notes,
        "active_variables": [
            {"variable": v.variable, "coefficient": v.coefficient,
             "transformation": v.transformation,
             "information_value": v.information_value,
             "risk_direction": v.risk_direction, "scoreable": v.scoreable}
            for v in variables if v.role == registry_mod.ACTIVE_VARIABLE],
        "candidate_variables": [
            {"variable": v.variable,
             "information_value": v.information_value,
             "risk_direction": v.risk_direction, "scoreable": v.scoreable}
            for v in variables if v.role == registry_mod.CANDIDATE_VARIABLE],
    }


@router.get("/registry")
def registry_models(scorecard_type: str = Query(default=""),
                    model_status: str = Query(default=""),
                    principal: Principal = RequireScorecardModelView
                    ) -> dict[str, Any]:
    """§12. Every registered model version, with its variables.

    Empty is a real answer and says so. An installation whose lake was built
    without `--register` has models it can score with and none it can raise
    a finding against, and reporting that as "no models" would hide a
    fixable gap behind what looks like an empty portfolio.
    """
    kind = _check_type(scorecard_type) if scorecard_type else ""
    with get_session() as session:
        rows = registry_mod.models(session, scorecard_type=kind,
                                   status=model_status.upper())
        payload = [
            _model_payload(row, registry_mod.variables_for(
                session, row.model_id, row.model_version))
            for row in rows]

    return {
        "models": payload,
        "count": len(payload),
        "statuses": list(registry_mod.STATUSES),
        "registry_version": registry_mod.REGISTRY_VERSION,
        "nothing_registered": (
            "" if payload else
            "No scorecard is registered. The lake can still be scored and "
            "every dashboard above works, but a finding has no model "
            "version to attach itself to. Register with "
            "`python scripts/build_retail_scorecards.py --register`."),
    }


@router.get("/registry/{model_id}")
def registry_model(model_id: str,
                   model_version: str = Query(default=""),
                   principal: Principal = RequireScorecardModelView
                   ) -> dict[str, Any]:
    """One registered version, its variables and its approval history."""
    with get_session() as session:
        try:
            row = registry_mod.get(session, model_id, model_version)
        except registry_mod.RegistryError as exc:
            raise _not_found(exc) from exc
        variables = registry_mod.variables_for(session, row.model_id,
                                               row.model_version)
        approvals = registry_mod.approvals_for(session, row.model_id)
        payload = _model_payload(row, variables)
        payload["approvals"] = [
            {"from_status": a.from_status, "to_status": a.to_status,
             "decision": a.decision, "rationale": a.rationale,
             "conditions": a.conditions, "committee": a.committee,
             "decided_by": a.decided_by,
             "decided_at": a.decided_at.isoformat() if a.decided_at else "",
             "model_version": a.model_version}
            for a in approvals]
        payload["legal_transitions"] = list(
            registry_mod.TRANSITIONS.get(row.status, ()))
    return payload


class TransitionBody(BaseModel):
    model_version: str = Field(..., max_length=32)
    to_status: str = Field(..., max_length=24)
    decision: str = Field(default="APPROVED", max_length=24)
    rationale: str = Field(default="", max_length=4000)
    conditions: str = Field(default="", max_length=4000)
    committee: str = Field(default="", max_length=120)


@router.post("/registry/{model_id}/transition")
def registry_transition(model_id: str, body: TransitionBody,
                        principal: Principal = RequireScorecardModelApprove
                        ) -> dict[str, Any]:
    """Move a registered model to a new status.

    Requires SCORECARD_MODEL_APPROVE, which is Administrator only. The route
    that proposes a candidate requires a wider permission on purpose:
    proposing a change to a credit model and accepting it are different
    acts, and one person doing both is the control failing quietly.
    """
    with get_session() as session:
        try:
            approval = registry_mod.transition(
                session, model_id=model_id,
                model_version=body.model_version,
                to_status=body.to_status.upper(),
                decision=body.decision.upper(), rationale=body.rationale,
                conditions=body.conditions, committee=body.committee,
                decided_by=_actor(principal))
        except registry_mod.RegistryError as exc:
            raise _refused(exc) from exc
        row = registry_mod.get(session, model_id, body.model_version)
        result = {
            "model_id": model_id,
            "model_version": body.model_version,
            "from_status": approval.from_status,
            "status": row.status,
            "decided_by": approval.decided_by,
            "legal_transitions": list(
                registry_mod.TRANSITIONS.get(row.status, ())),
        }
    return result


@router.get("/registry/{model_id}/findings")
def registry_findings(model_id: str,
                      period: str = Query(default=""),
                      finding_status: str = Query(default=""),
                      principal: Principal = RequireScorecardView
                      ) -> dict[str, Any]:
    """§48. Findings raised against one model, most recent first."""
    with get_session() as session:
        rows = registry_mod.findings_for(
            session, model_id=model_id, period=period,
            status=finding_status.upper())
        payload = [
            {"finding_id": f.finding_id, "model_version": f.model_version,
             "period": f.period, "category": f.category, "title": f.title,
             "description": f.description, "severity": f.severity,
             "metric": f.metric, "observed": f.observed,
             "limit_value": f.limit_value,
             # Carried onto every finding: a breach of a demonstration
             # default and a breach of a regulator's number read the same
             # without it.
             "limit_source": f.limit_source, "breach": f.breach,
             "impact": f.impact, "recommendation": f.recommendation,
             "evidence": f.evidence, "analysis_run_ids": f.analysis_run_ids,
             "owner": f.owner, "status": f.status, "due_date": f.due_date,
             "validation_run_id": f.validation_run_id,
             "created_at": f.created_at.isoformat() if f.created_at else ""}
            for f in rows]
    return {"model_id": model_id, "findings": payload, "count": len(payload),
            "statuses": list(policy_mod.FINDING_STATUSES),
            "severities": list(policy_mod.SEVERITIES)}


class FindingStatusBody(BaseModel):
    status: str = Field(..., max_length=24)


@router.post("/registry/findings/{finding_id}/status")
def registry_finding_status(finding_id: str, body: FindingStatusBody,
                            principal: Principal = RequireScorecardFindingCreate
                            ) -> dict[str, Any]:
    """Move a finding through its lifecycle."""
    with get_session() as session:
        try:
            row = registry_mod.set_finding_status(
                session, finding_id, body.status.upper(),
                by=_actor(principal))
        except registry_mod.RegistryError as exc:
            raise _refused(exc) from exc
        result = {"finding_id": row.finding_id, "status": row.status,
                  "closed_at": (row.closed_at.isoformat()
                                if row.closed_at else "")}
    return result


class PinBody(BaseModel):
    scorecard_type: str = Field(..., max_length=24)
    kind: str = Field(..., max_length=24)
    reference: str = Field(..., max_length=120)
    model_id: str = Field(default="", max_length=64)
    label: str = Field(default="", max_length=160)
    position: int = Field(default=0, ge=0, le=64)


@router.get("/pins")
def list_pins(scorecard_type: str = Query(default=""),
              principal: Principal = RequireScorecardView) -> dict[str, Any]:
    kind = _check_type(scorecard_type) if scorecard_type else ""
    with get_session() as session:
        rows = registry_mod.pins_for(session, user_id=principal.user_id,
                                     scorecard_type=kind)
        payload = [{"kind": p.kind, "reference": p.reference,
                    "label": p.label, "model_id": p.model_id,
                    "scorecard_type": p.scorecard_type,
                    "position": p.position} for p in rows]
    return {"pins": payload, "count": len(payload)}


@router.post("/pins")
def create_pin(body: PinBody,
               principal: Principal = RequireScorecardView) -> dict[str, Any]:
    kind = _check_type(body.scorecard_type)
    with get_session() as session:
        row = registry_mod.pin(
            session, user_id=principal.user_id, scorecard_type=kind,
            kind=body.kind, reference=body.reference,
            model_id=body.model_id, label=body.label,
            position=body.position)
        result = {"kind": row.kind, "reference": row.reference,
                  "label": row.label, "model_id": row.model_id,
                  "scorecard_type": row.scorecard_type,
                  "position": row.position}
    return result


@router.delete("/pins")
def delete_pin(scorecard_type: str = Query(...),
               kind: str = Query(...),
               reference: str = Query(...),
               model_id: str = Query(default=""),
               principal: Principal = RequireScorecardView) -> dict[str, Any]:
    resolved = _check_type(scorecard_type)
    with get_session() as session:
        removed = registry_mod.unpin(
            session, user_id=principal.user_id, scorecard_type=resolved,
            kind=kind, reference=reference, model_id=model_id)
    return {"removed": removed}
