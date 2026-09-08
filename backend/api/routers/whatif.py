"""
What-If over HTTP.

The configuration a scenario runs under — the rating masterscale, the macro
sensitivity matrix, the IFRS 9 policy — is served as data rather than buried in
the calculation, because section 1E asks for it to be VISIBLE. A credit officer
who cannot see the coefficient cannot argue with it, and a coefficient nobody
can argue with is one nobody should believe.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.api.auth import Principal
from backend.api.permissions import RequireAnalyst
from backend.ifrs9 import policy
from backend.whatif import analysis as ay
from backend.whatif import answers as wa
from backend.whatif import cache as ch
from backend.whatif import comparison as cmp_
from backend.whatif import delta as dl
from backend.whatif import domain as dm
from backend.whatif import engine as wf
from backend.whatif import integration as itg
from backend.whatif import investigate as iv
from backend.whatif import language as lg
from backend.whatif import macro as mc
from backend.whatif import macrolab as mlab
from backend.whatif import masterscale as ms
from backend.whatif import methodology as me
from backend.whatif import migration as mg
from backend.whatif import narrative as nr
from backend.whatif import plausibility as pl
from backend.whatif import product as pd_
from backend.whatif import profiles as pf
from backend.whatif import run as rn
from backend.whatif import scenarios as sc
from backend.whatif import sensitivity as sv
from backend.whatif import staging as stg
from backend.whatif import steps as sp
from backend.whatif import threads as th
from backend.whatif import trace as wt
from backend.whatif.ml import runtime as mlrt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatif", tags=["whatif"])

#: A borrower table longer than this is a download, not a screen.
MAX_ROWS = 500


def _refused(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "invalid_scenario", "message": message})


class ShockIn(BaseModel):
    kind: str = Field(min_length=1, max_length=24)
    magnitude: float = Field(ge=-1000.0, le=1000.0)
    unit: str = Field(default=sc.RELATIVE, max_length=24)
    target: str = Field(default="", max_length=48)


class ThresholdIn(BaseModel):
    """One numeric filter, carried across save and reopen.

    Without these on the contract, "construction borrowers with exposure above
    SAR 100m" reached the engine as "construction borrowers" and priced the
    whole sector. A filter the person stated is part of the scenario.
    """

    field: str = Field(min_length=1, max_length=48)
    operator: str = Field(default="above", max_length=16)
    value: float = Field(ge=-1e12, le=1e12)
    unit: str = Field(default="", max_length=12)


class PopulationIn(BaseModel):
    sectors: list[str] = Field(default_factory=list, max_length=40)
    rating_bands: list[str] = Field(default_factory=list, max_length=20)
    stages: list[int] = Field(default_factory=list, max_length=3)
    borrower_ids: list[str] = Field(default_factory=list, max_length=2000)
    watchlist_only: bool = False
    thresholds: list[ThresholdIn] = Field(default_factory=list, max_length=8)
    top_n: int = Field(default=0, ge=0, le=5000)
    top_by: str = Field(default="ead", max_length=48)


class AssumptionsIn(BaseModel):
    reevaluate_sicr: bool = True
    rating_deterioration_sicr: bool = False
    rating_sicr_notches: int = Field(default=2, ge=1, le=5)
    collateral_to_lgd: bool = True


class RunIn(BaseModel):
    """Either a preconfigured scenario by key, or shocks supplied directly."""

    scenario: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=200)
    shocks: list[ShockIn] = Field(default_factory=list, max_length=12)
    population: PopulationIn = Field(default_factory=PopulationIn)
    assumptions: AssumptionsIn = Field(default_factory=AssumptionsIn)
    period: str = Field(default="", max_length=24)
    limit: int = Field(default=100, ge=1, le=MAX_ROWS)


class AskIn(BaseModel):
    """A scenario stated in words."""

    question: str = Field(min_length=3, max_length=1000)
    limit: int = Field(default=100, ge=1, le=MAX_ROWS)


@router.get("/configuration")
def configuration(_: Any = RequireAnalyst) -> dict[str, Any]:
    """Everything a scenario is computed under, so it can be inspected."""
    return {
        "masterscale": {
            "owner": ms.MASTERSCALE_OWNER,
            "version": ms.MASTERSCALE_VERSION,
            "grades": ms.table(),
            "bands": {name: list(grades) for name, grades in ms.BANDS.items()},
        },
        "sensitivity": sv.describe(),
        "attribution": _attribution_describe(),
        "ifrs9_policy": policy.describe(),
        "scenarios": sc.catalogue(),
        "currency": wf.CURRENCY,
        "periods_note": "Scenarios run against the most recent published "
                        "period unless one is named.",
    }


@router.get("/scenarios")
def scenarios(_: Any = RequireAnalyst) -> dict[str, Any]:
    return {"scenarios": sc.catalogue(), "count": len(sc.PRECONFIGURED)}


def _build(body: RunIn) -> sc.Scenario:
    if body.scenario:
        found = sc.scenario(body.scenario)
        if found is None:
            raise _refused(f"No scenario is configured with the key "
                           f"{body.scenario!r}.")
        if not body.shocks and not body.population.model_dump(exclude_defaults=True):
            return found
        base = found
    else:
        base = None

    shocks = tuple(sc.Shock(kind=s.kind, magnitude=s.magnitude, unit=s.unit,
                            target=s.target)
                   for s in body.shocks) or (base.shocks if base else ())
    if not shocks:
        raise _refused("A scenario needs at least one shock. Name a "
                       "preconfigured scenario or supply shocks.")
    for shock in shocks:
        if shock.kind not in (sc.RATING, sc.PD, sc.LGD, sc.EAD, sc.FINANCIAL,
                              sc.COLLATERAL, sc.MACRO):
            raise _refused(f"{shock.kind!r} is not a shock this engine applies.")
        if shock.kind == sc.MACRO and sv.variable(shock.target) is None:
            raise _refused(f"{shock.target!r} is not a variable in the "
                           f"sensitivity matrix.")

    population = _population_from(body.population)
    if base and population.is_whole_book:
        population = base.population

    return sc.Scenario(
        key=body.scenario or "custom",
        name=body.name or (base.name if base else "Custom scenario"),
        shocks=shocks, population=population,
        assumptions=sc.Assumptions(**body.assumptions.model_dump()),
        severity=(base.severity if base else "custom"),
        rationale=(base.rationale if base else "Composed by the caller."),
        period=body.period)


def _payload(result: wf.Result, limit: int) -> dict[str, Any]:
    return {
        **result.to_dict(),
        "borrowers": wa.borrower_table(result, limit=limit),
        "detail": wt.detail(result),
        "trace": wt.build(result, result.scenario.name).to_dict(),
    }


@router.post("/run")
def run(body: RunIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    try:
        result = wf.run(_build(body), period=body.period)
    except ValueError as exc:
        raise _refused(str(exc)) from exc
    return _payload(result, body.limit)


@router.post("/ask")
def ask(body: AskIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    """A scenario stated in words, read and run."""
    reading = lg.read(body.question)
    if reading.scenario is None:
        return {
            "is_scenario": reading.is_scenario_question,
            "continues_previous": reading.continues_previous,
            "unread": reading.unread,
            "notes": reading.notes,
            "message": "That question does not describe a scenario this "
                       "engine can run. Nothing was guessed.",
        }
    try:
        result = wf.run(reading.scenario)
    except ValueError as exc:
        raise _refused(str(exc)) from exc
    composed = wa.compose_answer(result, reading)
    return {"is_scenario": True, "reading": reading.to_dict(),
            "answer": composed.to_dict(), **_payload(result, body.limit)}


@router.post("/compare")
def compare(keys: list[str], _: Any = RequireAnalyst) -> dict[str, Any]:
    """Several scenarios beside each other, on the same book."""
    wanted = [k for k in keys][:8]
    if not wanted:
        raise _refused("Name at least one scenario to compare.")
    results = []
    for key in wanted:
        found = sc.scenario(key)
        if found is None:
            raise _refused(f"No scenario is configured with the key {key!r}.")
        results.append(wf.run(found))
    frame = wf.compare(results)
    return {"columns": list(frame.columns),
            "rows": frame.values.tolist(),
            "currency": wf.CURRENCY,
            "scenarios": [r.scenario.to_dict() for r in results]}


@router.get("/sensitivity")
def sensitivity(scenario_key: str = Query(default="", max_length=64),
                _: Any = RequireAnalyst) -> dict[str, Any]:
    """The sensitivity table, portfolio-wide or for one scenario's shocks."""
    if not scenario_key:
        return sv.describe()
    found = sc.scenario(scenario_key)
    if found is None:
        raise _refused(f"No scenario is configured with the key "
                       f"{scenario_key!r}.")
    result = wf.run(found)
    return {**sv.describe(), "applied": result.sensitivity_rows}


__all__ = ["router"]


# ===================================================================== What-If
#
# Everything below serves the What-If Analysis product: the guided journeys,
# the layered scenario, the methodology gate, and the model configuration.
#
# The six endpoints above predate it and are left exactly as they were. They
# are the narrow scenario API; these are the product.


def _domain_refused(message: str) -> HTTPException:
    """A read this domain will not serve.

    422 rather than 404, because the request was understood and refused. The
    difference matters to a caller deciding whether to retry.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "outside_domain", "message": message})


def _unavailable(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"error": "unavailable", "message": message})


class StagingRuleIn(BaseModel):
    """One edit to the rule set: change a rule, add one, or remove one.

    `kind` is what makes it an ADDITION — a key the set does not have, with a
    kind the engine can apply, is a new rule. `remove` takes one out. Anything
    else edits the rule the key names.
    """

    key: str = Field(min_length=1, max_length=48)
    threshold: float | None = Field(default=None, ge=0.0, le=1000.0)
    floor: float | None = Field(default=None, ge=0.0, le=1000.0)
    enabled: bool | None = None
    name: str | None = Field(default=None, max_length=80)
    kind: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=300)
    remove: bool = False


class StagingIn(BaseModel):
    """Edited staging criteria. Also has to read `StagingPolicy.describe()`,
    which the client holds and posts back, so the extra descriptive fields it
    carries are ignored rather than refused."""

    rules: list[StagingRuleIn] = Field(default_factory=list, max_length=20)
    combination: str | None = Field(default=stg.ANY, max_length=8)
    note: str | None = Field(default="", max_length=500)


class StepIn(BaseModel):
    kind: str = Field(min_length=1, max_length=24)
    shocks: list[ShockIn] = Field(default_factory=list, max_length=12)
    population: PopulationIn = Field(default_factory=PopulationIn)
    instruction: str = Field(default="", max_length=1000)
    interpreted: str = Field(default="", max_length=1000)
    step_id: str = Field(default="", max_length=48)
    enabled: bool = True
    detail: dict[str, Any] = Field(default_factory=dict)


class SensitivityIn(BaseModel):
    """A macro relationship somebody wants to use for this thread."""

    variable: str = Field(min_length=1, max_length=48)
    source: str = Field(default="user", max_length=16)
    pd_response_kind: str = Field(default="multiplier", max_length=16)
    pd_response: float = Field(default=1.0, ge=-1000.0, le=1000.0)
    lgd_response_kind: str = Field(default="absolute_pp", max_length=16)
    lgd_response: float = Field(default=0.0, ge=-100.0, le=100.0)
    sectors: list[str] = Field(default_factory=list, max_length=40)
    segments: list[str] = Field(default_factory=list, max_length=20)
    rating_bands: list[str] = Field(default_factory=list, max_length=20)
    stages: list[int] = Field(default_factory=list, max_length=3)
    pd_ceiling_pct: float = Field(default=99.0, ge=0.0, le=100.0)
    lgd_ceiling_pct: float = Field(default=95.0, ge=0.0, le=100.0)
    name: str = Field(default="", max_length=120)
    note: str | None = Field(default="", max_length=400)


class StateIn(BaseModel):
    """The scenario state, as the browser holds it.

    The optional strings accept None as well as "" because this model has to
    accept its OWN output: `ScenarioState.to_dict()` writes `None` for a
    methodology that has not been chosen yet, and the client posts that dict
    straight back. A contract that cannot read what it just emitted rejects
    every second request, which is exactly what it did.
    """

    period: str = Field(default="", max_length=24)
    title: str | None = Field(default="", max_length=200)
    thread_id: str | None = Field(default="", max_length=64)
    steps: list[StepIn] = Field(default_factory=list, max_length=40)
    staging: StagingIn | None = None
    methodology: str | None = Field(default="", max_length=48)
    model_version: str | None = Field(default="", max_length=32)
    #: Macro relationships this thread has overridden. Without this field the
    #: state posted back after /macro/configure lost them silently, and a
    #: user-defined sensitivity was unreachable from the browser: the
    #: configure call returned a state carrying it and the next execute threw
    #: it away.
    sensitivities: list[SensitivityIn] = Field(default_factory=list,
                                               max_length=10)


class ExecuteIn(BaseModel):
    state: StateIn
    #: The methodology the person just chose, if they are answering the gate.
    methodology: str = Field(default="", max_length=48)
    instruction: str = Field(default="", max_length=1000)
    limit: int = Field(default=200, ge=1, le=MAX_ROWS)


class SaveIn(BaseModel):
    state: StateIn
    name: str = Field(default="", max_length=180)
    methodology: str = Field(default="", max_length=48)
    instruction: str = Field(default="", max_length=1000)


class TrainIn(BaseModel):
    development_through: str = Field(default="", max_length=24)
    excluded: list[str] = Field(default_factory=list, max_length=16)
    reason: str = Field(default="", max_length=500)
    instruction: str = Field(default="", max_length=1000)


class ActivateIn(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    reason: str = Field(default="", max_length=500)


def _staging_from(body: StagingIn | None) -> stg.StagingPolicy:
    """The thread's What-If rule set, from the edits the client sent.

    Starts from `stg.default()` — the governed three plus Rule A and Rule B —
    and applies each edit in order. A rule the set does not have, carrying a
    kind, is an addition; `remove` takes one out; everything else is an edit.
    """
    policy_ = stg.default()
    if body is None:
        return policy_
    for rule in body.rules:
        if rule.remove:
            policy_ = policy_.removed(rule.key)
            continue
        if policy_.rule(rule.key) is None:
            if not rule.kind:
                raise stg.StagingError(
                    f"There is no staging rule called '{rule.key}', and no "
                    "kind was given to add one. The kinds are: "
                    + ", ".join(stg.KINDS))
            policy_ = policy_.added(stg.Rule(
                key=rule.key, name=rule.name or rule.key, kind=rule.kind,
                threshold=float(rule.threshold or 0.0),
                floor=float(rule.floor or 0.0),
                enabled=True if rule.enabled is None else rule.enabled,
                governed=False, note=rule.note or ""))
            continue
        changes: dict[str, Any] = {}
        if rule.threshold is not None:
            changes["threshold"] = rule.threshold
        if rule.floor is not None:
            changes["floor"] = rule.floor
        if rule.enabled is not None:
            changes["enabled"] = rule.enabled
        if rule.name is not None:
            changes["name"] = rule.name
        if rule.note is not None:
            changes["note"] = rule.note
        if changes:
            policy_ = policy_.with_rule(rule.key, **changes)
    if body.combination:
        policy_ = policy_.combined(body.combination)
    if body.note is not None:
        policy_ = replace(policy_, note=body.note)
    return policy_


def _population_from(body: PopulationIn) -> sc.Population:
    """The population as stated, filters included.

    Every field on the contract is carried. A population that arrives narrower
    than it leaves is a scenario that priced a different book from the one the
    person described.
    """
    return sc.Population(
        sectors=tuple(body.sectors),
        rating_bands=tuple(body.rating_bands),
        stages=tuple(body.stages),
        borrower_ids=tuple(body.borrower_ids),
        watchlist_only=body.watchlist_only,
        thresholds=tuple(sc.Threshold(field=t.field, operator=t.operator,
                                      value=float(t.value), unit=t.unit)
                         for t in body.thresholds),
        top_n=int(body.top_n or 0),
        top_by=body.top_by or "ead")


def _state_from(body: StateIn) -> sp.ScenarioState:
    steps = []
    for raw in body.steps:
        steps.append(sp.Step(
            kind=raw.kind,
            shocks=tuple(sc.Shock(kind=s.kind, magnitude=s.magnitude,
                                  unit=s.unit, target=s.target)
                         for s in raw.shocks),
            population=_population_from(raw.population),
            instruction=raw.instruction, interpreted=raw.interpreted,
            enabled=raw.enabled, detail=dict(raw.detail),
            **({"step_id": raw.step_id} if raw.step_id else {})))
    return sp.ScenarioState(
        period=body.period, title=body.title or "",
        thread_id=body.thread_id or "",
        steps=tuple(steps), staging=_staging_from(body.staging),
        methodology=body.methodology or "",
        model_version=body.model_version or "",
        sensitivities=tuple(_sensitivity_from(x) for x in body.sensitivities))


def _sensitivity_from(body: SensitivityIn) -> Any:
    """One overridden macro relationship, rebuilt from what the browser holds.

    A relationship the contract cannot read is REFUSED rather than dropped: a
    scenario silently priced on the governed matrix when somebody asked for
    their own assumption is the worst of the three outcomes.
    """
    from backend.whatif import macrolab as mlab_

    try:
        return mlab_.Sensitivity.from_dict(body.model_dump())
    except mlab_.MacroLabError as e:
        raise _refused(str(e)) from e


def _owner(principal: Principal) -> int | None:
    return principal.user_id


# ------------------------------------------------------------------ context


@router.get("/periods")
def periods(_: Any = RequireAnalyst) -> dict[str, Any]:
    """Every Corporate IFRS 9 quarter, resolved from the book, never hardcoded."""
    try:
        found = dm.periods()
    except dm.DomainError as e:
        raise _unavailable(str(e)) from e
    return {"periods": found, "latest": found[-1] if found else None,
            "earliest": found[0] if found else None, "count": len(found),
            "domain": dm.DOMAIN_NAME, "grain": dm.GRAIN,
            "aliases": {"latest": found[-1] if found else None,
                        "earliest": found[0] if found else None,
                        "previous": found[-2] if len(found) > 1 else None}}


@router.get("/landing")
def landing(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Everything the What-If landing page shows, in one call."""
    from backend.whatif.ml import registry as rg

    try:
        available = dm.periods()
    except dm.DomainError as e:
        raise _unavailable(str(e)) from e
    active = rg.active()
    owner = _owner(principal)
    return {
        "heading": "What-If",
        "domain": dm.DOMAIN_NAME,
        "restriction": dm.Binding(period=available[-1] if available else "",
                                  periods=tuple(available), rows=0,
                                  borrowers=0).to_dict()["restriction"],
        "periods": available,
        "latest_period": available[-1] if available else None,
        "journeys": JOURNEYS,
        "saved": [s.card() for s in th.listing(owner=owner, status=th.SAVED)],
        "recent": [s.card() for s in th.listing(owner=owner, status=th.RECENT)],
        "persistence": th.describe(),
        "models": me.describe(ml_available=bool(active),
                              model_version=active.version if active else ""),
        "staging": stg.default().describe(),
        "currency": dm.CURRENCY,
    }


#: The six guided starting points. Shortcuts, never restrictions — a person can
#: combine several in one sentence and never touch a card.
JOURNEYS: list[dict[str, Any]] = [
    {"key": "rating", "title": "Rating Movement",
     "summary": "Downgrade or upgrade a population and see what it does to staging and ECL.",
     "opens_with": "rating_profile"},
    {"key": "parameters", "title": "IFRS 9 Risk Parameter Adjustment",
     "summary": "Move PD, LGD, CCF, EAD, collateral or haircut directly.",
     "opens_with": "parameter_profile"},
    {"key": "stage", "title": "Stage Migration",
     "summary": "Move borrowers between Stages 1, 2 and 3, in either direction.",
     "opens_with": "stage_profile"},
    {"key": "macro", "title": "Macroeconomic Shock",
     "summary": "Shock any of ten macro variables through configured sensitivities.",
     "opens_with": "macro_profile"},
    {"key": "sector", "title": "Sector Stress",
     "summary": "Concentrate a scenario on one sector of the corporate book.",
     "opens_with": "sector_profile"},
    {"key": "borrower", "title": "Borrower Stress",
     "summary": "Start from a single name and see the borrower, its sector and the book.",
     "opens_with": "borrower_profile"},
]


# ----------------------------------------------------------------- profiles


@router.get("/profile/rating")
def rating_profile(period: str = Query(default="", max_length=24),
                   _: Any = RequireAnalyst) -> dict[str, Any]:
    """The 19 governed grades plus a Total — twenty rows."""
    try:
        return pf.rating_profile(period)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


@router.get("/profile/stage")
def stage_profile(period: str = Query(default="", max_length=24),
                  _: Any = RequireAnalyst) -> dict[str, Any]:
    try:
        return pf.stage_profile(period)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


@router.get("/profile/sector")
def sector_profile(period: str = Query(default="", max_length=24),
                   _: Any = RequireAnalyst) -> dict[str, Any]:
    try:
        return pf.sector_profile(period)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


@router.get("/profile/parameter/{parameter}")
def parameter_profile(parameter: str,
                      period: str = Query(default="", max_length=24),
                      _: Any = RequireAnalyst) -> dict[str, Any]:
    """PD, LGD or CCF described before anybody is asked to change it."""
    readers = {"pd": pf.pd_profile, "lgd": pf.lgd_profile, "ccf": pf.ccf_profile}
    found = readers.get(str(parameter).lower())
    if found is None:
        raise _domain_refused(
            f"'{parameter}' is not a risk parameter this screen describes. "
            "It describes PD, LGD and CCF.")
    try:
        return found(period)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


@router.get("/profile/macro")
def macro_profile(period: str = Query(default="", max_length=24),
                  _: Any = RequireAnalyst) -> dict[str, Any]:
    """The ten macro variables, their observed levels and their sensitivities."""
    try:
        series = dm.macro()
    except dm.DomainError:
        series = None
    settled = dm.resolve_period(period) if period else ""
    return mc.describe(series, settled)


@router.get("/profile/borrowers")
def borrower_profile(period: str = Query(default="", max_length=24),
                     limit: int = Query(default=10, ge=1, le=100),
                     _: Any = RequireAnalyst) -> dict[str, Any]:
    """Top Stage 2 borrowers by ECL, at true obligor grain."""
    try:
        return pf.top_stage_2(period, limit=limit)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


@router.get("/borrower/{borrower_id}")
def borrower_history(borrower_id: str,
                     quarters: int = Query(default=8, ge=1, le=16),
                     _: Any = RequireAnalyst) -> dict[str, Any]:
    try:
        return pf.borrower_history(borrower_id, quarters=quarters)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


# ---------------------------------------------------------------- migration


@router.get("/migration/rating")
def rating_migration(period: str = Query(default="", max_length=24),
                     opening: str = Query(default="", max_length=24),
                     _: Any = RequireAnalyst) -> dict[str, Any]:
    """One year of rating migration as a 15 x 15 displayed matrix."""
    try:
        return mg.rating_migration(period, opening)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


@router.get("/migration/stage")
def stage_migration(period: str = Query(default="", max_length=24),
                    opening: str = Query(default="", max_length=24),
                    _: Any = RequireAnalyst) -> dict[str, Any]:
    try:
        return mg.stage_migration(period, opening)
    except dm.DomainError as e:
        raise _domain_refused(str(e)) from e


# ------------------------------------------------------------------ staging


@router.get("/staging")
def staging_criteria(_: Any = RequireAnalyst) -> dict[str, Any]:
    """Both rule sets, and what a thread may change about the What-If one.

    The reported-book set is returned alongside so a screen can show the two
    next to each other. It is marked `editable: false` and the engine refuses
    to change it, because it is what staged the accounts.
    """
    whatif = stg.default()
    return {**whatif.describe(),
            "reported": stg.reported().describe(),
            "whatif": whatif.describe(),
            "editable_fields": ["threshold", "floor", "enabled", "name", "note"],
            "combinations": list(stg.COMBINATIONS),
            "kinds": list(stg.KINDS),
            "kind_catalogue": [dict(k) for k in stg.KIND_CATALOGUE]}


@router.post("/staging")
def staging_preview(body: StagingIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    """Validate an edited rule set and show what it would be.

    The reported-book set comes back unchanged next to it, so the screen that
    is about to save an override can show what it is overriding.
    """
    try:
        edited = _staging_from(body)
    except stg.StagingError as e:
        raise _refused(str(e)) from e
    return {**edited.describe(),
            "reported": stg.reported().describe(),
            "whatif": edited.describe(),
            "kind_catalogue": [dict(k) for k in stg.KIND_CATALOGUE],
            "combinations": list(stg.COMBINATIONS)}


# ------------------------------------------------------------- methodology


@router.get("/methodology")
def methodology_gate(active: str = Query(default="", max_length=16),
                     _: Any = RequireAnalyst) -> dict[str, Any]:
    """The question that must be answered before any ECL impact is calculated."""
    from backend.whatif.ml import registry as rg

    current = rg.active()
    runnable = mlrt.check()
    return me.question(
        active=active, ml_available=bool(current) and runnable.available,
        ml_note=(runnable.message() if not runnable.available
                 else "No ML model has been activated yet."))


class InterpretIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    state: StateIn = Field(default_factory=StateIn)
    #: Whether the thread already has a computed result. It changes the
    #: reading: "download the detailed Excel" on an empty thread is somebody
    #: finding out that exports exist, not an export.
    has_result: bool = False
    #: The quick analysis this thread last computed, so a follow-up like
    #: "only show BBB- and weaker" has something to narrow. Without it every
    #: follow-up is a whole question again, and "show exposure too" means
    #: nothing at all.
    analysis: dict[str, Any] | None = None


class AnalyseIn(BaseModel):
    """A question about the reported book, asked inside a What-If thread."""

    question: str = Field(min_length=1, max_length=1000)
    #: The previous request, for a follow-up. Same shape `run` returns.
    previous: dict[str, Any] | None = None
    period: str = Field(default="", max_length=32)
    #: Whether to write a reading over the table. Off for a caller that only
    #: wants the figures, so a table never waits on a model it does not need.
    interpret: bool = True


@router.post("/analyse")
def analyse(body: AnalyseIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    """Answer an analytical question about the book. Changes nothing.

    This is the quick analysis a reader does BEFORE deciding what to stress,
    and it is a first-class part of configuring a scenario rather than a
    diversion from it: "increase BBB PD by 20%" is a different instruction
    depending on whether BBB PD is 0.18% or 1.8%, so the question has to be
    answerable where the scenario is being built.

    Two shapes come back. A question with a magnitude in it — "what would be a
    sensible PD shock for BBB?" — returns evidence-based magnitudes drawn from
    the book's own historical movements. Everything else returns a computed
    table with a reading written over it.
    """
    from backend.whatif import analysis as an
    from backend.whatif import narrative as nr

    previous = an.Request.from_dict(body.previous)
    try:
        if an.wants_a_suggestion(body.question):
            return {"understood": True, "changes_state": False,
                    **an.suggest(body.question, previous=previous,
                                 period=body.period)}
        request = an.read(body.question, previous=previous, period=body.period)
        if request is None:
            raise _refused(
                "That does not name anything to break the book down by. Ask "
                "for a measure and a dimension \u2014 for example \"show "
                "lifetime PD by rating\" or \"LGD by sector\" \u2014 or "
                "describe the shock you want to apply instead.")
        table = an.run(request, source=None)
    except an.AnalysisError as e:
        raise _refused(str(e)) from e
    except dm.DomainError as e:
        raise _refused(str(e)) from e
    if body.interpret:
        table["interpretation"] = nr.interpret_analysis(table)
    table["understood"] = True
    table["changes_state"] = False
    return table


def _quick_analysis(said: str, state: Any, previous: Any) -> dict[str, Any] | None:
    """The answer to an analytical question, or None when it is not one.

    Returning None is the whole point of putting this in one place: a sentence
    that is a SCENARIO must not be answered as a table, and a sentence that is
    a table must not be handed back with a request for a magnitude. The
    decision is made once and both callers get the same one.
    """
    if ay.wants_a_suggestion(said):
        suggested = ay.suggest(said, previous=previous, period=state.period)
        return {
            "understood": True,
            "opens_whatif": False,
            "informational": True,
            "answers_directly": True,
            "intent": iv.VIEW,
            "changes_state": False,
            "analysis": suggested,
            "message": (
                f"Here is what this book has actually done to "
                f"{suggested['measure_label']} for {suggested['population']}, "
                f"so you can size the shock against it rather than guess."),
            "state": state.to_dict(),
        }
    wanted = ay.read(said, previous=previous, period=state.period)
    if wanted is None:
        return None
    try:
        table = ay.run(wanted)
    except (ay.AnalysisError, dm.DomainError) as e:
        raise _refused(str(e)) from e
    table["interpretation"] = nr.interpret_analysis(table)
    return {
        "understood": True,
        "opens_whatif": False,
        "informational": True,
        "answers_directly": True,
        "intent": iv.VIEW,
        "changes_state": False,
        "analysis": table,
        "message": table["interpretation"]["headline"],
        "state": state.to_dict(),
    }


@router.post("/interpret")
def interpret(body: InterpretIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    """Turn a sentence into a scenario STEP on the current state.

    This is the scenario builder. It is deterministic — regular expressions
    over a governed vocabulary, no model — which is why the same sentence
    always produces the same step and why a step can be edited afterwards
    rather than re-argued.

    Three outcomes, and the product needs all three:

      * a step was read, and is appended to the thread;
      * the sentence is a What-If but names no magnitude, so the product asks
        how big rather than guessing;
      * the sentence asks about the book instead of changing it, and is routed
        to the profile screens rather than answered with an ECL figure.
    """
    said = body.instruction.strip()
    try:
        state = _state_from(body.state)
    except (stg.StagingError, sp.StepError) as e:
        raise _refused(str(e)) from e

    # What KIND of message this is decides everything: what answers it, and
    # whether the scenario may be touched at all.
    intent = iv.classify(said, has_result=bool(body.has_result),
                         has_steps=bool(state.active))

    # A question about the PRODUCT, the DATA, the FIELDS or the METHOD is
    # answered here and now. It reads no book, prices nothing, and must never
    # reach the scenario builder — "what can you do?" names no magnitude, so
    # the builder asked how big it should be.
    if intent.intent in (iv.HELP, iv.DATA, iv.FIELDS, iv.METHODOLOGY):
        answered = pd_.answer(intent.intent, said)
        return {
            "understood": True,
            "intent": intent.intent,
            "changes_state": False,
            "opens_whatif": False,
            "informational": True,
            "answers_directly": True,
            "reading": intent.to_dict(),
            "product": answered,
            "message": answered["paragraphs"][0] if answered["paragraphs"] else "",
            "state": state.to_dict(),
        }

    # A question about the RESULT, the BOOK's history or the MODEL. An EXPLAIN
    # is always about the result; a VIEW is only about it when it POINTS at it,
    # because "show Stage 1 PD by sector" is a question about the reported book
    # and belongs on the profile screens, which answer it without an ECL
    # calculation and therefore without a methodology.
    # A VIEW that does not point at the result on screen is a question about
    # the BOOK, and the product now answers those. It has to be tried before
    # the branch below, which would otherwise reply "that is a question about
    # the result" to a question that is not about the result at all.
    previous_analysis = ay.Request.from_dict(body.analysis)
    if intent.intent == iv.VIEW and not intent.about_the_result:
        answered = _quick_analysis(said, state, previous_analysis)
        if answered is not None:
            return answered

    reads = intent.family == iv.READS and (
        intent.intent != iv.VIEW or intent.about_the_result
        or not intent.needs_a_result)
    if reads and (bool(state.active) or not intent.needs_a_result):
        return {
            "understood": True,
            "intent": intent.intent,
            "changes_state": False,
            "opens_whatif": False,
            "informational": False,
            "reading": intent.to_dict(),
            "message": (
                "That is a question about the result, not a change to the "
                "scenario. It is answered from the figures already computed."),
            "state": state.to_dict(),
        }

    reading = lg.read(said)
    informational = rn.informational(said)

    if reading.scenario is None:
        # A question about the book is ANSWERED, not redirected. "Can you give
        # me the rating-wise PDs, getting rid of stages?" names a dimension, a
        # metric and what to do about the Stage split; replying "the profile
        # views answer it" points at a different screen and hands the question
        # back. It is also the wrong moment to do that: nobody asks for
        # rating-wise PDs in a scenario builder out of curiosity — they are
        # deciding what to shock, and the answer is part of that decision.
        answered = _quick_analysis(said, state, previous_analysis)
        if answered is not None:
            return answered
        return {
            "understood": False,
            "opens_whatif": bool(getattr(reading, "opens_whatif", False)),
            "informational": informational,
            "severity": getattr(reading, "severity", ""),
            "message": (
                "That reads as a question about the book, but it does not name "
                "a measure and a dimension I can put in a table. Try naming "
                "both — for example \"lifetime PD by rating\" or \"LGD by "
                "sector\"."
                if informational else
                "That is a What-If, but it does not say how big the movement "
                "is yet. Tell me the size — for example \"two notches\", "
                "\"20%\", or \"five percentage points\"."),
            "notes": list(reading.notes),
            "unread": list(reading.unread),
            "intent": intent.intent,
            "changes_state": True,
            "state": state.to_dict(),
        }

    scenario = reading.scenario
    kinds = {shock.kind for shock in scenario.shocks}
    kind = next((k for k in sp.APPLY_ORDER if k in kinds), sp.PD)
    step = sp.Step(kind=kind, shocks=tuple(scenario.shocks),
                   population=scenario.population,
                   instruction=said, interpreted=scenario.describe())
    updated = state.add(step)
    if scenario.period:
        updated = updated.with_period(scenario.period)

    return {
        "understood": True,
        "opens_whatif": True,
        "informational": False,
        "step": step.to_dict(),
        "restatement": (
            f"Understood: {scenario.describe()} for "
            f"{scenario.population.describe()}."),
        "notes": list(reading.notes),
        "unread": list(reading.unread),
        "objective": reading.objective,
        "intent": intent.intent,
        "changes_state": True,
        "filters": scenario.population.filters(),
        "state": updated.to_dict(),
    }


# ------------------------------------------------------------------ running


@router.post("/execute")
def execute(body: ExecuteIn,
            principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Run the thread's scenario — after the methodology gate has been answered.

    Where it has not been, this returns the GATE rather than a number. That is
    the whole contract: the product does not choose a methodology quietly.
    """
    from backend.whatif.ml import registry as rg

    try:
        state = _state_from(body.state)
    except (stg.StagingError, sp.StepError) as e:
        raise _refused(str(e)) from e

    current = rg.active()
    runnable = mlrt.check()
    if me.needs_gate(calculates_ecl=True, requested=body.methodology,
                     instruction=body.instruction, active=state.methodology):
        return {"needs_methodology": True,
                "gate": me.question(
                    active=state.methodology,
                    ml_available=bool(current) and runnable.available,
                    ml_note=(runnable.message() if not runnable.available
                             else "No ML model has been activated yet.")),
                "state": state.to_dict()}
    try:
        result = rn.execute(state, requested=body.methodology,
                            instruction=body.instruction, limit=body.limit)
    except (rn.RunError, dm.DomainError, ValueError) as e:
        raise _refused(str(e)) from e

    owner = _owner(principal)
    stored = None
    if th.available():
        try:
            stored = th.save(result, name=state.title or result.state.describe()[:80],
                             owner=owner, status=th.RECENT,
                             instruction=body.instruction)
        except Exception:  # noqa: BLE001 - a recent entry is never the answer
            # Failing to note a run in the Recent list must not cost the
            # person the run itself. The scenario computed; it is logged and
            # returned, and the list is simply one shorter.
            logger.warning("Could not record the run in Recent What-Ifs",
                           exc_info=True)
            stored = None
    payload = result.to_dict(limit=body.limit)
    payload["needs_methodology"] = False
    payload["state"] = result.state.to_dict()
    payload["confirmation"] = me.confirmation(result.choice)
    payload["recent_id"] = stored.id if stored else None
    # The borrower-level frame is held so a follow-up question is answered
    # from THIS result rather than from a second run of the same scenario.
    payload["run_id"] = ch.put(result, owner=owner)
    # §74: the engine calculated; the model explains. The reading is
    # written from an evidence packet and re-read against it, and it
    # falls back to the composed one rather than going silent.
    payload["interpretation"] = nr.interpret(result)
    return payload


class ExportIn(BaseModel):
    """A request for the detailed workbook."""

    #: The held result to export. Preferred: it exports exactly the figures
    #: that were on the screen rather than a second run of the same scenario.
    run_id: str = Field(default="", max_length=32)
    #: The scenario to run and export, where nothing is held any more.
    state: StateIn = Field(default_factory=StateIn)
    methodology: str = Field(default="", max_length=48)


@router.post("/export")
def export(body: ExportIn,
           principal: Principal = RequireAnalyst) -> Response:
    """The audit-grade workbook for a What-If, as a download.

    Access is the same rule the rest of the thread obeys: a held result is
    readable only by the person who ran it, so a run_id guessed or copied from
    somebody else's session returns nothing. Every download is audited.
    """
    from backend.exports import audit as ax
    from backend.exports.contract import XLSX_MIME, slug
    from backend.whatif import workbook as wbk

    owner = _owner(principal)
    started = time.monotonic()
    result = ch.get(body.run_id, owner=owner) if body.run_id else None
    recomputed = False
    if result is None:
        if body.run_id:
            # Said, not silently recomputed from a state the caller supplied:
            # a run_id that does not resolve for THIS user is either expired
            # or somebody else's, and those are different problems.
            logger.info("Export asked for a result this user cannot read")
        try:
            state = _state_from(body.state)
        except (stg.StagingError, sp.StepError) as e:
            raise _refused(str(e)) from e
        if not state.active:
            raise _refused(
                "There is no What-If to export yet. Build a scenario and run "
                "it first.")
        try:
            result = rn.execute(state, requested=body.methodology or
                                state.methodology, limit=MAX_ROWS)
        except (rn.RunError, dm.DomainError, ValueError) as e:
            raise _refused(str(e)) from e
        recomputed = True

    try:
        content = wbk.build(result, owner=owner,
                            requested_by=str(principal.role or ""),
                            interpretation=nr.interpret(result))
    except wbk.WorkbookError as e:
        raise _refused(str(e)) from e

    name = slug(result.state.title or result.state.describe() or "what-if")
    filename = f"what-if-{name}-{slug(result.period)}.xlsx"
    ax.record(ax.Entry(
        kind="whatif_detail", object_type="whatif_run",
        object_id=body.run_id or "recomputed", user_id=owner,
        role=str(principal.role or ""), filename=filename,
        content_hash=ax.content_hash(content), size_bytes=len(content),
        row_count=result.population,
        duration_ms=int((time.monotonic() - started) * 1000),
        datasets=[dm.IFRS9, dm.SNAPSHOT, dm.FACILITIES],
        detail={"period": result.period,
                "methodology": result.choice.method,
                "recomputed": recomputed,
                "workbook_version": wbk.WORKBOOK_VERSION}))
    return Response(
        content=content, media_type=XLSX_MIME,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; '
                f"filename*=UTF-8''{filename}"),
            "Content-Length": str(len(content)),
            # A workbook is a point-in-time record. Caching one and serving it
            # after the scenario changed hands somebody the wrong figures
            # under the right filename.
            "Cache-Control": "no-store, max-age=0",
            "X-CreditProbe-WhatIf-Period": result.period,
            "X-CreditProbe-WhatIf-Methodology": result.choice.method,
            "X-CreditProbe-WhatIf-Rows": str(result.population),
        })


class InvestigateIn(BaseModel):
    """A follow-up question about a result that already exists."""

    question: str = Field(min_length=1, max_length=1000)
    run_id: str = Field(default="", max_length=32)
    state: StateIn = Field(default_factory=StateIn)


@router.post("/investigate")
def investigate(body: InvestigateIn,
                principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Answer a question ABOUT a result, without changing it.

    Three things can be asked in a thread, and this endpoint serves two of
    them. An EXPLAIN or a VIEW is answered from the borrower-level figures the
    run already produced — so "why did Stage 3 move?" is answered about the
    number on the screen, and asking it cannot change that number.

    A MODIFY is refused here and sent to the builder, because an endpoint that
    quietly changed the scenario while claiming to explain it would be the
    worst of the three failures available.

    Where the run is no longer held in memory, the scenario is recomputed from
    its steps. The engine is deterministic, so the figures are identical, and
    the answer says that it was recomputed rather than pretending otherwise.
    """
    said = body.question.strip()
    # This endpoint exists to answer a question ABOUT a result, so a result is
    # what it is being asked in the presence of. Classifying without saying so
    # made every intent that only exists after a result degrade to the one it
    # falls back to when a thread is empty.
    reading = iv.classify(said, has_result=True,
                          has_steps=bool(body.state.steps))
    if reading.changes_state:
        return {
            "answered": False,
            "intent": reading.intent,
            "changes_state": True,
            "reading": reading.to_dict(),
            "message": (
                "That changes the scenario rather than asking about it. Send "
                "it to the builder so the step is added and the book priced "
                "again."),
        }

    owner = _owner(principal)
    result = ch.get(body.run_id, owner=owner)
    notes: list[str] = []
    if result is None:
        try:
            state = _state_from(body.state)
        except (stg.StagingError, sp.StepError) as e:
            raise _refused(str(e)) from e
        if not state.active:
            raise _refused(
                "There is no result to explain yet. Run a scenario first, "
                "then ask about it.")
        try:
            result = rn.execute(state, requested=state.methodology,
                                instruction="", limit=MAX_ROWS)
        except (rn.RunError, dm.DomainError, ValueError) as e:
            raise _refused(str(e)) from e
        notes.append(
            "This result was no longer held in memory, so the scenario was "
            "computed again from its steps. The engine is deterministic: the "
            "figures are the same ones you were shown.")

    body_out = iv.answer(reading, result)
    body_out["answered"] = True
    body_out["reading"] = reading.to_dict()
    body_out["notes"] = notes
    body_out["context"] = result.context()
    body_out["run_id"] = body.run_id or ch.put(result, owner=owner)
    return body_out


class ProductAskIn(BaseModel):
    """A question about the product rather than about the book."""

    question: str = Field(min_length=1, max_length=1000)
    intent: str = Field(default="", max_length=24)


@router.post("/product/ask")
def product_ask(body: ProductAskIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    """Answer a product, data, field or methodology question.

    Reads no book and prices nothing, so there is no methodology gate and no
    period to resolve. Where an intent is not supplied it is read from the
    question, and anything that is NOT one of the four is refused here rather
    than answered from the wrong evidence.
    """
    said = body.question.strip()
    intent = (body.intent or "").strip().lower() or iv.classify(said).intent
    if intent not in (iv.HELP, iv.DATA, iv.FIELDS, iv.METHODOLOGY):
        raise _refused(
            f"'{intent}' is not a question about the product. This endpoint "
            "answers what the product does, what data it reads, what fields it "
            "carries and how its methodologies differ.")
    return pd_.answer(intent, said)


@router.get("/product")
def product_surface(_: Any = RequireAnalyst) -> dict[str, Any]:
    """Everything the product can say about itself, without being asked."""
    return {
        **pd_.describe(),
        "capabilities": pd_.capabilities(),
        "methodologies": pd_.methodologies(),
    }


@router.get("/product/fields")
def product_fields(_: Any = RequireAnalyst) -> dict[str, Any]:
    """The field catalogue, grouped and business-readable."""
    return pd_.fields()


@router.get("/investigate/intents")
def investigate_intents(_: Any = RequireAnalyst) -> dict[str, Any]:
    """What a thread does with a message, and which kind may change state."""
    return iv.describe()


class MacroAnalyseIn(BaseModel):
    variable: str = Field(min_length=1, max_length=48)
    state: StateIn = Field(default_factory=StateIn)


class MacroConfigureIn(BaseModel):
    sensitivity: SensitivityIn
    state: StateIn = Field(default_factory=StateIn)


@router.get("/macro/method")
def macro_method(_: Any = RequireAnalyst) -> dict[str, Any]:
    """What a macro relationship can be, and how the three kinds differ."""
    return mlab.describe()


@router.get("/macro/{variable}")
def macro_variable(variable: str, _: Any = RequireAnalyst) -> dict[str, Any]:
    """One variable's card, and the relationship currently in force."""
    found = mc.variable(variable)
    if found is None:
        raise _refused(
            f"'{variable}' is not one of the ten governed macro variables. "
            "They are: " + ", ".join(v.name for v in mc.VARIABLES) + ".")
    described = mc.describe(dm.macro(), dm.latest_period())
    card = next((v for v in described["variables"] if v["key"] == found.key), {})
    return {
        "variable": card,
        "configured": mlab.configured(found.key).to_dict(),
        "method": mlab.describe(),
    }


@router.post("/macro/analyse")
def macro_analyse(body: MacroAnalyseIn,
                  _: Any = RequireAnalyst) -> dict[str, Any]:
    """Align this variable's history to the book's PD, and measure the two.

    Reads the book; changes nothing. The estimate is reported with its
    uncertainty and with the sample it came from, because sixteen quarterly
    observations are directional evidence and not a calibration.
    """
    try:
        state = _state_from(body.state)
    except (stg.StagingError, sp.StepError) as e:
        raise _refused(str(e)) from e
    population = state.scenario().population if state.active else None
    try:
        fit = mlab.estimate(body.variable, population=population)
    except (mlab.MacroLabError, dm.DomainError) as e:
        raise _refused(str(e)) from e
    return {
        "fit": fit.to_dict(),
        "configured": mlab.configured(fit.variable).to_dict(),
        "estimated": mlab.from_fit(fit).to_dict(),
        "recommendation": mlab.recommend(fit),
        "population": (population.describe() if population
                       else "the whole corporate book"),
        "choices": [
            {"choice": mlab.REFERENCE,
             "label": "Keep the configured sensitivity"},
            {"choice": mlab.EMPIRICAL,
             "label": "Use the estimated relationship for this thread",
             "available": fit.strength != "insufficient"},
            {"choice": mlab.USER, "label": "Define my own relationship"},
        ],
    }


@router.post("/macro/configure")
def macro_configure(body: MacroConfigureIn,
                    _: Any = RequireAnalyst) -> dict[str, Any]:
    """Put a relationship in force FOR THIS THREAD.

    The governed reference matrix is never edited by this. The override is
    carried on the state, stamped on every result it produces, saved with the
    What-If and written into the workbook, so a figure computed on somebody's
    own assumption cannot be mistaken for one computed on the governed matrix.
    """
    try:
        state = _state_from(body.state)
    except (stg.StagingError, sp.StepError) as e:
        raise _refused(str(e)) from e
    if mc.variable(body.sensitivity.variable) is None:
        raise _refused(
            f"'{body.sensitivity.variable}' is not one of the ten governed "
            "macro variables.")
    try:
        sensitivity = mlab.Sensitivity.from_dict(
            body.sensitivity.model_dump())
    except mlab.MacroLabError as e:
        raise _refused(str(e)) from e
    updated = state.with_sensitivity(sensitivity)
    return {
        "sensitivity": sensitivity.to_dict(),
        "in_force_for": "this thread only",
        "reference_unchanged": mlab.configured(sensitivity.variable).to_dict(),
        "message": (
            f"{sensitivity.label} in force for {sensitivity.name or sensitivity.variable} "
            f"on this thread: {sensitivity.describe()}. The CreditProbe "
            "reference sensitivity is unchanged and still applies everywhere "
            "else."),
        "state": updated.to_dict(),
    }


class PlausibilityIn(BaseModel):
    state: StateIn = Field(default_factory=StateIn)


@router.post("/plausibility")
def plausibility(body: PlausibilityIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    """Where this scenario sits in what the book has actually done.

    Not a forecast and not a probability. A severe scenario is never refused
    here — it is labelled, and calculated if the caller asks.
    """
    try:
        state = _state_from(body.state)
    except (stg.StagingError, sp.StepError) as e:
        raise _refused(str(e)) from e
    try:
        return pl.assess(state)
    except (dm.DomainError, ValueError) as e:
        raise _refused(str(e)) from e


@router.get("/plausibility/method")
def plausibility_method(_: Any = RequireAnalyst) -> dict[str, Any]:
    """The six controlled labels, and what earns each."""
    return pl.describe()


class CompareIn(BaseModel):
    """A request to price one scenario both ways."""

    state: StateIn
    #: The methodology the person is coming FROM, so the answer is phrased in
    #: their direction. Never changes a figure — both are always computed.
    ran: str = Field(default="", max_length=16)
    #: Whether to write the reading. Off for a caller that only wants figures.
    explain: bool = Field(default=True)


@router.get("/compare-methodologies/method")
def compare_method(_: Any = RequireAnalyst) -> dict[str, Any]:
    """How the comparison is made, and what neither figure is."""
    return cmp_.describe()


@router.post("/compare-methodologies")
def compare_methodologies(body: CompareIn,
                          _: Any = RequireAnalyst) -> dict[str, Any]:
    """The same scenario under both methodologies, and where they disagree.

    Works in both directions from one object: whichever methodology produced
    the result on screen, the other is one question away, and only the
    phrasing follows the reader — the figures do not.
    """
    try:
        state = _state_from(body.state)
    except (stg.StagingError, sp.StepError) as e:
        raise _refused(str(e)) from e
    if not state.active:
        raise _refused(
            "There is no scenario to compare yet. Build one and run it "
            "first, then ask what the other methodology would have said.")
    try:
        found = cmp_.compare(state, ran=body.ran or state.methodology)
    except (rn.RunError, dm.DomainError, ValueError) as e:
        raise _refused(str(e)) from e
    if body.explain:
        found["explanation"] = cmp_.explain(found)
    return found


# ------------------------------------------------------------------- saving


@router.get("/saved")
def saved(principal: Principal = RequireAnalyst,
          limit: int = Query(default=24, ge=1, le=100)) -> dict[str, Any]:
    rows = th.listing(owner=_owner(principal), status=th.SAVED, limit=limit)
    return {"saved": [r.card() for r in rows], "count": len(rows),
            "persistence": th.describe()}


@router.get("/recent")
def recent(principal: Principal = RequireAnalyst,
           limit: int = Query(default=12, ge=1, le=50)) -> dict[str, Any]:
    rows = th.listing(owner=_owner(principal), status=th.RECENT, limit=limit)
    return {"recent": [r.card() for r in rows], "count": len(rows),
            "persistence": th.describe()}


@router.post("/save")
def save(body: SaveIn, principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Run and keep. A saved What-If must be reproducible, so it is run first."""
    try:
        state = _state_from(body.state)
        result = rn.execute(state, requested=body.methodology,
                            instruction=body.instruction)
    except (rn.RunError, dm.DomainError, ValueError) as e:
        raise _refused(str(e)) from e
    try:
        stored = th.save(result, name=body.name, owner=_owner(principal),
                         status=th.SAVED, instruction=body.instruction)
    except th.Unavailable as e:
        raise _unavailable(str(e)) from e
    except th.ThreadError as e:
        raise _refused(str(e)) from e
    return {"saved": stored.card(), "id": stored.id}


@router.get("/saved/{scenario_id}")
def open_saved(scenario_id: int,
               principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Reopen a saved What-If, with the state that reproduces it."""
    try:
        state, stored = th.reopen(scenario_id, owner=_owner(principal))
    except th.Unavailable as e:
        raise _unavailable(str(e)) from e
    except th.ThreadError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(e)}) from e
    return {"card": stored.card(), "state": state.to_dict(),
            "stored": stored.body}


@router.delete("/saved/{scenario_id}")
def delete_saved(scenario_id: int,
                 principal: Principal = RequireAnalyst) -> dict[str, Any]:
    try:
        th.delete(scenario_id, owner=_owner(principal))
    except th.Unavailable as e:
        raise _unavailable(str(e)) from e
    except th.ThreadError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": str(e)}) from e
    return {"deleted": scenario_id}


# ------------------------------------------------------- model configuration


def _attribution_describe() -> dict[str, Any]:
    from backend.whatif import attribution as at

    return at.describe()


@router.get("/integration/contract")
def integration_contract(_: Any = RequireAnalyst) -> dict[str, Any]:
    """What a Corporate IFRS 9 book must provide for What-If to run on it.

    The document somebody wiring a canonical IFRS 9 domain reads BEFORE
    pointing it at this feature: the datasets, the required and optional
    columns with what each optional one buys, and the assumptions that are not
    columns at all — the grain above everything else.
    """
    return itg.contract()


@router.get("/integration/readiness")
def integration_readiness(
        _: Any = RequireAnalyst,
        snapshot: str = Query(default="", max_length=120),
        measurement: str = Query(default="", max_length=120)) -> dict[str, Any]:
    """Whether What-If can run on a book, and exactly what it will not do.

    Defaults to the book this installation carries, so the same call is both
    an integration check for a candidate domain and a health check for the
    current one. It never raises on a bad book: an unreadable dataset is a
    finding, because the whole point is to say what is wrong.
    """
    return itg.assess(snapshot=snapshot, measurement=measurement).to_dict()


@router.get("/schema")
def schema_contract(_: Any = RequireAnalyst) -> dict[str, Any]:
    """The governed schema contract, and how the book on disk compares.

    Served so a schema mismatch is visible as a fact about the installation
    rather than as a failed scenario. `healthy` is false when the Parquet is
    missing something the catalogue declares, even where every scenario still
    prices correctly.
    """
    from backend.whatif import schema as sch

    body = sch.describe()
    try:
        body["installation"] = sch.report()
    except Exception as e:  # noqa: BLE001 - reported, never raised at a reader
        body["installation"] = {"healthy": False, "why": str(e)[:300]}
    return body


@router.get("/attribution")
def attribution_method(_: Any = RequireAnalyst) -> dict[str, Any]:
    """What the driver attribution is, and what it is not."""
    return _attribution_describe()


@router.get("/models/delta")
def delta_model(_: Any = RequireAnalyst) -> dict[str, Any]:
    """The Delta Model as its configuration page explains it."""
    return dl.describe()


@router.get("/models/ml")
def ml_model(_: Any = RequireAnalyst) -> dict[str, Any]:
    """The active model card, the versions, and what retraining would use."""
    from backend.whatif.ml import registry as rg
    from backend.whatif.ml import train as tr

    active = rg.active()
    cards = rg.cards()
    try:
        available = dm.periods()
    except dm.DomainError:
        available = []
    trained_through = ""
    if active and active.split.get("train"):
        trained_through = str((active.split.get("validation")
                               or active.split.get("train"))[-1])
    newer = [p for p in available
             if active and p not in set(active.split.get("train") or ())
             and p not in set(active.split.get("validation") or ())
             and p not in set(active.split.get("out_of_time") or ())]
    return {
        "active": active.to_dict() if active else None,
        "has_active": bool(active),
        "versions": [{"version": c.version, "state": c.state,
                      "built_at": c.built_at, "predecessor": c.predecessor,
                      "validation": c.validation, "out_of_time": c.out_of_time}
                     for c in cards],
        "changelog": rg.changelog(),
        "periods": available,
        "trained_through": trained_through,
        "newer_periods": newer,
        "retrain_prompt": (
            f"Active model trained through {trained_through}. "
            f"{len(newer)} newer IFRS 9 quarter(s) available. Retrain?"
            if active and newer else
            (f"Active model trained through {trained_through}. No newer data."
             if active else "No model has been trained yet.")),
        "defaults": {"development_through": tr.DEFAULT_DEVELOPMENT_THROUGH,
                     "train_share": tr.TRAIN_SHARE, "seed": tr.SEED},
        "features": None,
        # Whether this installation can run the thing at all, said before
        # anybody composes a scenario on it.
        "environment": mlrt.describe(),
    }


@router.post("/models/ml/train")
def train_model(body: TrainIn,
                principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Actually retrain. A candidate is produced; nothing is activated."""
    if not mlrt.available():
        raise _unavailable(mlrt.check().message())
    from backend.whatif.ml import explain as ex
    from backend.whatif.ml import features as ft
    from backend.whatif.ml import registry as rg
    from backend.whatif.ml import train as tr

    try:
        split = tr.plan_split(
            development_through=body.development_through
            or tr.DEFAULT_DEVELOPMENT_THROUGH,
            excluded=tuple(body.excluded))
        trained = tr.fit(split=split)
    except (tr.TrainingError, dm.DomainError, ValueError) as e:
        raise _refused(str(e)) from e

    X = ft.build(tr.load(split.validation or split.train),
                 encoding=trained.encoding).X
    # Explained through the SERVED model. Where the design is one model per
    # Stage, explaining the fallback would describe something the product does
    # not score with.
    served = trained.served()
    importance = ex.importance(served, trained.feature_names, limit=25)
    summary = ex.summary(served, X)
    card = rg.save(trained, built_by=str(principal.user_id or "system"),
                   reason=body.reason or body.instruction,
                   importance=importance, shap=summary)
    rg.record_build(card)
    previous = rg.active_version()
    return {"candidate": card.to_dict(), "activated": False,
            "comparison": rg.compare(previous, card.version) if previous else None,
            "message": ("Trained as a CANDIDATE. The active model is "
                        "unchanged until you activate this one.")}


@router.post("/models/ml/activate")
def activate_model(body: ActivateIn,
                   principal: Principal = RequireAnalyst) -> dict[str, Any]:
    from backend.whatif.ml import registry as rg

    try:
        card = rg.activate(body.version, actor=str(principal.user_id or "system"),
                           reason=body.reason)
    except rg.RegistryError as e:
        raise _refused(str(e)) from e
    return {"activated": card.to_dict()}


@router.get("/models/ml/explain")
def explain_model(version: str = Query(default="", max_length=32),
                  _: Any = RequireAnalyst) -> dict[str, Any]:
    """Feature importance, SHAP, calibration and sensitivity for one model."""
    from backend.whatif.ml import explain as ex
    from backend.whatif.ml import features as ft
    from backend.whatif.ml import registry as rg
    from backend.whatif.ml import train as tr

    chosen = version or rg.active_version()
    if not chosen:
        raise _refused("No ML model has been activated.")
    try:
        card = rg.card(chosen)
        model = rg.load_booster(chosen)
    except rg.RegistryError as e:
        raise _refused(str(e)) from e

    split = tr.Split.from_dict(card.split)
    frame = tr.load(split.validation or split.train)
    matrix = ft.build(frame, encoding=ft.Encoding.from_dict(card.encoding))
    predicted = model.predict(matrix.X)
    return {
        "version": chosen,
        "importance": card.importance or ex.importance(model, tuple(card.features)),
        "shap": card.shap or ex.summary(model, matrix.X),
        "actual_vs_predicted": ex.actual_vs_predicted(matrix.y, predicted),
        "sensitivity": {name: ex.sensitivity(model, matrix.X, name)
                        for name in ("pd_12m", "lgd", "ccf",
                                     "collateral_coverage_pct")},
        # The evidence that "stage-aware" is a property of this model rather
        # than a claim about it: the same shock, inside each Stage.
        "stage_interaction": ex.stage_interaction(model, matrix.X, frame),
        "stage_study": card.stage_study,
        "slices": card.slices,
        "validation": card.validation,
        "out_of_time": card.out_of_time,
        "limitations": card.limitations,
    }


@router.post("/models/ml/example")
def model_example(features: dict[str, Any],
                  _: Any = RequireAnalyst) -> dict[str, Any]:
    """Score one made-up borrower and explain the prediction locally."""
    from backend.whatif.ml import explain as ex
    from backend.whatif.ml import features as ft
    from backend.whatif.ml import predict as mp
    from backend.whatif.ml import registry as rg

    try:
        scored = mp.one(features)
        card = rg.card(scored["model_version"])
        model = rg.load_booster(scored["model_version"])
    except (mp.PredictionError, rg.RegistryError) as e:
        raise _refused(str(e)) from e
    import pandas as pd

    matrix = ft.build(pd.DataFrame([features]),
                      encoding=ft.Encoding.from_dict(card.encoding))
    return {**scored, "explanation": ex.local(model, matrix.X)}
