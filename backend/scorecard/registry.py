"""
The Retail Scorecard Model Registry. §12, §13, §35, §94.

Why a registry at all, when the equation is already on disk
-------------------------------------------------------------
`build.py` writes the binning specification and the fitted equations beside
the Parquet lake, and for computing a score that is enough. It is not enough
for governance, and the difference shows up the first time somebody asks a
question with a date in it.

A finding raised in March against version 1.0.0 has to still mean something
in September. By then 1.1.0 may be active and the demonstration universe has
been rebuilt twice — `build.py` deletes and regenerates. The registry is the
part that does not get regenerated: what was registered, who approved it,
what was found against it, and what was reported to whom.

Three rules this module enforces rather than documents
--------------------------------------------------------
* **§35: a candidate never overwrites Active.** `propose_candidate` writes a
  new row with status CANDIDATE. There is no code path that mutates an
  ACTIVE row's equation, because the operation people actually want under
  deadline pressure is exactly the one that must not exist.
* **§13: the registry defines the sign convention.** `score_direction` has
  no default here, in the ORM column, or in the equation IR. A default would
  be one of these three layers quietly choosing for the institution.
* **§26/§80: every limit says where it came from.** Seeded limits are
  DEMO POLICY. A conventional PSI cut-off recorded without its provenance
  becomes a regulatory requirement the third time somebody reads the table.

Transitions are checked, and the check is small
-------------------------------------------------
`TRANSITIONS` is a map, not a workflow engine. A scorecard moves
DEVELOPMENT → CANDIDATE → APPROVED → ACTIVE → RETIRED, plus the refusals
(back to DEVELOPMENT) and the direct retirement of something that was never
activated. Anything else raises. The value is not that the graph is
sophisticated; it is that "activate this candidate without approving it" is
a rejected transition rather than an UPDATE somebody ran.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.platform import (
    ScorecardBinningSpec,
    ScorecardDashboardPin,
    ScorecardFinding,
    ScorecardModel,
    ScorecardModelApproval,
    ScorecardModelVariable,
    ScorecardPolicyLimit,
    ScorecardReport,
    ScorecardReportEvidence,
    ScorecardValidationRun,
)
from backend.scorecard import build as build_mod
from backend.scorecard import equation as equation_mod
from backend.scorecard import policy as policy_mod
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

REGISTRY_VERSION = "1.0.0"

# ------------------------------------------------------------------ statuses

DEVELOPMENT = "DEVELOPMENT"
CANDIDATE = "CANDIDATE"
APPROVED = "APPROVED"
ACTIVE = "ACTIVE"
RETIRED = "RETIRED"

STATUSES: tuple[str, ...] = (DEVELOPMENT, CANDIDATE, APPROVED, ACTIVE,
                             RETIRED)

#: §12's lifecycle. Every legal move, written out.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    DEVELOPMENT: (CANDIDATE, RETIRED),
    # A candidate can be approved, sent back, or dropped.
    CANDIDATE: (APPROVED, DEVELOPMENT, RETIRED),
    # Approval and activation are separate acts. A model can be approved and
    # not yet implemented, which is the normal state between a committee
    # meeting and a release.
    APPROVED: (ACTIVE, DEVELOPMENT, RETIRED),
    ACTIVE: (RETIRED,),
    RETIRED: (),
}

#: The variable roles §12 distinguishes.
ACTIVE_VARIABLE = "ACTIVE"
CANDIDATE_VARIABLE = "CANDIDATE"

#: §2. Nothing generated in this workspace describes a real customer.
SYNTHETIC_DEMO = "SYNTHETIC_DEMO"


class RegistryError(Exception):
    """A registry operation that may not be performed as asked."""


# ------------------------------------------------------------------ identity


def model_id_for(scorecard_type: str, kind: str) -> str:
    """A stable id for a seeded model.

    Derived rather than random so re-seeding an installation produces the
    same ids and a finding raised before the reseed still points at
    something.
    """
    return f"{scorecard_type.lower()}-{kind.lower()}"


def _fingerprint(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(UTC)


# -------------------------------------------------------------- registration


@dataclass(frozen=True)
class Registration:
    """What a registration produced, for the caller to report."""

    model_id: str
    model_version: str
    status: str
    created: bool


def register(session: Session, *,
             equation: equation_mod.Equation,
             model_id: str,
             model_version: str,
             status: str,
             scorecard_type: str,
             candidate_variables: tuple[str, ...] = (),
             spec: Any = None,
             owner: str = "",
             developer: str = "",
             validator: str = "",
             development_period: str = "",
             validation_period: str = "",
             default_definition: dict[str, Any] | None = None,
             population: str = "",
             product_scope: str = "",
             based_on_model_id: str = "",
             materiality: str = "",
             model_risk_rating: str = "",
             notes: str = "",
             created_by: str = "",
             tenant: str = "") -> Registration:
    """Record one model version, with its variables.

    Idempotent on (tenant, model_id, model_version): re-registering the same
    version updates it rather than raising, which is what re-seeding a
    demonstration installation needs. Changing an ACTIVE row's equation is
    refused, because that is the operation §35 exists to prevent — a new
    equation is a new version.
    """
    if status not in STATUSES:
        raise RegistryError(
            f"{status} is not a registry status. Known statuses are "
            f"{', '.join(STATUSES)}.")
    if equation.score_mapping is None:
        raise RegistryError(
            f"{model_id} has no score mapping, so the registry cannot record "
            "its sign convention. §13 says the registry defines the "
            "convention; a model registered without one leaves every "
            "discrimination statistic ambiguous.")

    mapping = equation.score_mapping
    existing = session.execute(
        select(ScorecardModel).where(
            ScorecardModel.tenant == tenant,
            ScorecardModel.model_id == model_id,
            ScorecardModel.model_version == model_version)
    ).scalar_one_or_none()

    payload = equation.to_dict()
    if existing is not None and existing.status == ACTIVE:
        if _fingerprint(existing.equation) != _fingerprint(payload):
            raise RegistryError(
                f"{model_id} {model_version} is ACTIVE and its equation "
                "differs from the one supplied. An active model's equation "
                "is not editable: a different equation is a different "
                "version, which is what §35's candidate flow is for.")

    row = existing or ScorecardModel(
        model_id=model_id, model_version=model_version, tenant=tenant)
    row.model_name = equation.model_name
    row.scorecard_type = scorecard_type
    row.status = status
    row.owner = owner
    row.developer = developer
    row.validator = validator
    row.development_period = development_period
    row.validation_period = validation_period
    row.performance_horizon_months = int(
        (default_definition or {}).get("performance_window_months", 12))
    row.default_definition = default_definition or {}
    row.target = str((default_definition or {}).get("target", ""))
    row.population = population
    row.product_scope = product_scope
    row.baseline_population = development_period
    row.binning_spec_version = equation.binning_spec_version
    row.woe_spec_version = equation.binning_spec_version
    row.intercept = float(equation.intercept)
    row.equation = payload
    row.logit_direction = equation.link
    row.pd_mapping = "SIGMOID"
    row.base_score = mapping.base_score
    row.pdo = mapping.pdo
    row.base_odds = mapping.base_odds
    row.score_direction = mapping.score_direction
    row.min_score = mapping.min_score
    row.max_score = mapping.max_score
    row.based_on_model_id = based_on_model_id
    row.materiality = materiality
    row.model_risk_rating = model_risk_rating
    row.notes = notes
    row.origin = SYNTHETIC_DEMO
    row.created_by = created_by or row.created_by
    if existing is None:
        session.add(row)
    session.flush()

    _replace_variables(session, row, equation=equation, spec=spec,
                       candidate_variables=candidate_variables,
                       scorecard_type=scorecard_type, tenant=tenant)
    return Registration(model_id=model_id, model_version=model_version,
                        status=status, created=existing is None)


def _replace_variables(session: Session, row: ScorecardModel, *,
                       equation: equation_mod.Equation,
                       spec: Any,
                       candidate_variables: tuple[str, ...],
                       scorecard_type: str,
                       tenant: str) -> None:
    """Rewrite the variable rows for one model version.

    Deleted and re-inserted rather than merged. A model version's variable
    list is not something that evolves — if it changed, this is a different
    model, and the merge would hide that.

    `variables.get` raises on a name the dictionary does not define, and
    that exception is allowed through. Registering a model against an
    undefined variable with blank metadata is precisely how a hidden
    predictor gets into a registry and stays there.
    """
    session.query(ScorecardModelVariable).filter(
        ScorecardModelVariable.tenant == tenant,
        ScorecardModelVariable.model_id == row.model_id,
        ScorecardModelVariable.model_version == row.model_version).delete()

    # Information value belongs to the binning, not to the fit: it is a
    # property of how a variable separates good from bad under the approved
    # bins, and the same variable has a different IV under a different spec.
    ivs: dict[str, float] = {}
    if spec is not None:
        for name, entry in (spec.to_dict().get("variables") or {}).items():
            value = entry.get("information_value")
            if value is not None:
                ivs[name] = float(value)
    position = 0
    for term in equation.terms:
        variable = vars_mod.get(scorecard_type, term.variable)
        session.add(ScorecardModelVariable(
            model_id=row.model_id, model_version=row.model_version,
            variable=term.variable, role=ACTIVE_VARIABLE,
            coefficient=float(term.coefficient),
            transformation=term.transformation,
            information_value=ivs.get(term.variable),
            risk_direction=variable.risk_direction,
            scoreable=bool(variable.scoreable),
            position=position, tenant=tenant))
        position += 1

    active = set(equation.active_variables)
    for name in candidate_variables:
        if name in active:
            continue
        variable = vars_mod.get(scorecard_type, name)
        session.add(ScorecardModelVariable(
            model_id=row.model_id, model_version=row.model_version,
            variable=name, role=CANDIDATE_VARIABLE,
            information_value=ivs.get(name),
            risk_direction=variable.risk_direction,
            scoreable=bool(variable.scoreable),
            position=position, tenant=tenant))
        position += 1
    session.flush()


def register_binning_spec(session: Session, spec: Any, *,
                          scorecard_type: str, target: str = "",
                          created_by: str = "",
                          tenant: str = "") -> str:
    """Record one versioned WoE specification, whole.

    Whole so a score is reproducible from this row alone: §52's
    implementation replication is a comparison against the specification
    that was approved, not against whatever the binner would produce today.
    """
    payload = spec.to_dict()
    existing = session.execute(
        select(ScorecardBinningSpec).where(
            ScorecardBinningSpec.tenant == tenant,
            ScorecardBinningSpec.spec_version == spec.spec_version)
    ).scalar_one_or_none()
    row = existing or ScorecardBinningSpec(spec_version=spec.spec_version,
                                           tenant=tenant)
    row.scorecard_type = scorecard_type
    row.development_population = spec.development_population
    row.target = target
    row.spec = payload
    row.variable_count = len(payload.get("variables", {}) or {})
    row.origin = SYNTHETIC_DEMO
    row.created_by = created_by or row.created_by
    if existing is None:
        session.add(row)
    session.flush()
    return spec.spec_version


def register_limits(session: Session,
                    limits: tuple[policy_mod.Limit, ...] = (), *,
                    policy_version: str = policy_mod.POLICY_VERSION,
                    scorecard_type: str = "",
                    approved_by: str = "",
                    tenant: str = "") -> int:
    """Record the validation policy's limits, each carrying its provenance.

    §26 and §80: seeded limits are DEMO POLICY, and this function will not
    quietly promote one. A limit whose provenance says REGULATORY has to
    have been written that way by whoever recorded it.
    """
    limits = limits or policy_mod.DEMO_LIMITS
    written = 0
    for limit in limits:
        if limit.provenance not in policy_mod.PROVENANCES:
            raise RegistryError(
                f"{limit.metric} has provenance {limit.provenance!r}, which "
                "is not one of the five §50 recognises. A limit whose source "
                "cannot be named should not be recorded: the source is what "
                "tells a reader whether the number is a convention or a "
                "requirement.")
        existing = session.execute(
            select(ScorecardPolicyLimit).where(
                ScorecardPolicyLimit.tenant == tenant,
                ScorecardPolicyLimit.policy_version == policy_version,
                ScorecardPolicyLimit.metric == limit.metric,
                ScorecardPolicyLimit.scorecard_type == scorecard_type)
        ).scalar_one_or_none()
        row = existing or ScorecardPolicyLimit(
            policy_version=policy_version, metric=limit.metric,
            scorecard_type=scorecard_type, tenant=tenant)
        row.source = limit.provenance
        row.comparison = limit.direction
        row.warn_at = limit.watch_at
        row.breach_at = limit.breach_at
        row.rationale = limit.note or limit.source
        row.approved_by = approved_by
        row.active = True
        if existing is None:
            session.add(row)
        written += 1
    session.flush()
    return written


# ------------------------------------------------------------------- reading


def models(session: Session, *, scorecard_type: str = "",
           status: str = "", tenant: str = "") -> list[ScorecardModel]:
    query = select(ScorecardModel).where(ScorecardModel.tenant == tenant)
    if scorecard_type:
        query = query.where(ScorecardModel.scorecard_type == scorecard_type)
    if status:
        query = query.where(ScorecardModel.status == status)
    return list(session.execute(
        query.order_by(ScorecardModel.scorecard_type,
                       ScorecardModel.model_id,
                       ScorecardModel.model_version)).scalars())


def get(session: Session, model_id: str, model_version: str = "", *,
        tenant: str = "") -> ScorecardModel:
    """One model version, or the most recent if no version is named."""
    query = select(ScorecardModel).where(
        ScorecardModel.tenant == tenant,
        ScorecardModel.model_id == model_id)
    if model_version:
        query = query.where(ScorecardModel.model_version == model_version)
    row = session.execute(
        query.order_by(ScorecardModel.created_at.desc())).scalars().first()
    if row is None:
        raise RegistryError(
            f"{model_id}"
            + (f" {model_version}" if model_version else "")
            + " is not in the registry. Seeding it is "
              "`scripts/build_retail_scorecards.py --register`; a validation "
              "run against a model nobody registered would have no version "
              "to attach its findings to.")
    return row


def variables_for(session: Session, model_id: str, model_version: str, *,
                  tenant: str = "") -> list[ScorecardModelVariable]:
    return list(session.execute(
        select(ScorecardModelVariable).where(
            ScorecardModelVariable.tenant == tenant,
            ScorecardModelVariable.model_id == model_id,
            ScorecardModelVariable.model_version == model_version)
        .order_by(ScorecardModelVariable.position)).scalars())


def equation_for(session: Session, model_id: str, model_version: str = "", *,
                 tenant: str = "") -> equation_mod.Equation:
    """Rebuild the equation IR from the registry row.

    From the stored equation, not from the variable rows: the equation is
    what the model computes and it is stored whole for exactly this.
    """
    row = get(session, model_id, model_version, tenant=tenant)
    payload = dict(row.equation or {})
    if not payload:
        raise RegistryError(
            f"{row.model_id} {row.model_version} has no stored equation, so "
            "nothing can be scored with it.")
    return equation_mod.Equation(
        model_name=payload.get("model_name", row.model_name),
        scorecard_type=row.scorecard_type,
        intercept=float(payload.get("intercept", row.intercept)),
        terms=[equation_mod.Term(
            variable=t["variable"], coefficient=float(t["coefficient"]),
            transformation=t.get("transformation", "WOE"))
            for t in payload.get("terms", [])],
        link=payload.get("link", equation_mod.LOGIT),
        binning_spec_version=row.binning_spec_version,
        score_mapping=equation_mod.ScoreMapping(
            base_score=float(row.base_score or 0.0),
            pdo=float(row.pdo or 0.0),
            base_odds=float(row.base_odds or 1.0),
            score_direction=row.score_direction,
            min_score=float(row.min_score or 0.0),
            max_score=float(row.max_score or 1000.0)),
        output_prefix=payload.get("output_prefix", ""))


def limits(session: Session, *, policy_version: str = "",
           scorecard_type: str = "",
           tenant: str = "") -> list[ScorecardPolicyLimit]:
    query = select(ScorecardPolicyLimit).where(
        ScorecardPolicyLimit.tenant == tenant,
        ScorecardPolicyLimit.active.is_(True))
    if policy_version:
        query = query.where(
            ScorecardPolicyLimit.policy_version == policy_version)
    if scorecard_type:
        query = query.where(
            ScorecardPolicyLimit.scorecard_type.in_(("", scorecard_type)))
    return list(session.execute(
        query.order_by(ScorecardPolicyLimit.metric)).scalars())


# ---------------------------------------------------------------- candidates


def propose_candidate(session: Session, *,
                      equation: equation_mod.Equation,
                      based_on: ScorecardModel,
                      model_version: str,
                      created_by: str = "",
                      notes: str = "",
                      tenant: str = "") -> Registration:
    """§35. Record a proposed equation as a CANDIDATE version.

    A new row. The model it was proposed from is untouched, still ACTIVE,
    still the thing every dashboard reads. That is the whole point: the
    natural-language edit path ends in something a committee can look at,
    not in a changed production model.
    """
    if based_on.model_id == "" or based_on.model_version == "":
        raise RegistryError(
            "a candidate has to name the version it was proposed from, so a "
            "reviewer can see what changed.")
    if model_version == based_on.model_version:
        raise RegistryError(
            f"the candidate carries the same version as {based_on.model_id} "
            f"{based_on.model_version}, which would make the proposal and "
            "the model it modifies indistinguishable in every later record.")

    return register(
        session, equation=equation, model_id=based_on.model_id,
        model_version=model_version, status=CANDIDATE,
        scorecard_type=based_on.scorecard_type,
        default_definition=dict(based_on.default_definition or {}),
        owner=based_on.owner, developer=created_by,
        development_period=based_on.development_period,
        population=based_on.population, product_scope=based_on.product_scope,
        based_on_model_id=f"{based_on.model_id}:{based_on.model_version}",
        materiality=based_on.materiality,
        model_risk_rating=based_on.model_risk_rating,
        notes=notes, created_by=created_by, tenant=tenant)


def transition(session: Session, *, model_id: str, model_version: str,
               to_status: str, decision: str = "APPROVED",
               rationale: str = "", conditions: str = "",
               committee: str = "", decided_by: str = "",
               tenant: str = "") -> ScorecardModelApproval:
    """Move a model version to a new status, and record who did it.

    The transition check is the control. Activating a candidate that was
    never approved is a rejected move rather than an UPDATE, and the
    approval row survives whatever the status column says later.
    """
    if to_status not in STATUSES:
        raise RegistryError(f"{to_status} is not a registry status.")
    row = get(session, model_id, model_version, tenant=tenant)
    allowed = TRANSITIONS.get(row.status, ())
    if to_status not in allowed:
        raise RegistryError(
            f"{model_id} {model_version} is {row.status} and cannot move to "
            f"{to_status}. From {row.status} the legal moves are "
            f"{', '.join(allowed) if allowed else 'none'}. Approval and "
            "activation are separate acts, and skipping one is the specific "
            "thing this refusal exists to stop.")

    if to_status == ACTIVE:
        _retire_incumbent(session, row, decided_by=decided_by, tenant=tenant)

    approval = ScorecardModelApproval(
        model_id=model_id, model_version=model_version,
        from_status=row.status, to_status=to_status, decision=decision,
        rationale=rationale, conditions=conditions, committee=committee,
        decided_by=decided_by, decided_at=_now(), tenant=tenant)
    session.add(approval)
    row.status = to_status
    if to_status == ACTIVE and not row.implementation_date:
        row.implementation_date = _now().date().isoformat()
    session.flush()
    logger.info("scorecard registry: %s %s -> %s by %s", model_id,
                model_version, to_status, decided_by or "unknown")
    return approval


def _retire_incumbent(session: Session, incoming: ScorecardModel, *,
                      decided_by: str, tenant: str) -> None:
    """Retire whatever else was ACTIVE for this scorecard type.

    Scoped to the scorecard type rather than to the model id, and the
    difference matters. A challenger is registered under its own model id,
    so retiring only same-id versions would leave the incumbent live
    alongside the challenger that replaced it — two active scorecards
    deciding the same applications, which is not a state anybody means to be
    in. It is the state that happens when activation forgets to retire.

    Application and Behavioral are separate types and both stay live: they
    score different populations at different points in the account
    lifecycle, so one of each is the normal arrangement.

    The retirement is recorded as its own approval row rather than done
    silently, because "when did 1.0.0 stop being live?" is an audit
    question.
    """
    for row in session.execute(
        select(ScorecardModel).where(
            ScorecardModel.tenant == tenant,
            ScorecardModel.scorecard_type == incoming.scorecard_type,
            ScorecardModel.status == ACTIVE)
    ).scalars():
        if (row.model_id == incoming.model_id
                and row.model_version == incoming.model_version):
            continue
        session.add(ScorecardModelApproval(
            model_id=row.model_id, model_version=row.model_version,
            from_status=ACTIVE, to_status=RETIRED, decision="SUPERSEDED",
            rationale=(f"Superseded by {incoming.model_id} "
                       f"{incoming.model_version}, activated on "
                       f"{_now().date().isoformat()}."),
            decided_by=decided_by, decided_at=_now(), tenant=tenant))
        row.status = RETIRED


def approvals_for(session: Session, model_id: str, *, model_version: str = "",
                  tenant: str = "") -> list[ScorecardModelApproval]:
    query = select(ScorecardModelApproval).where(
        ScorecardModelApproval.tenant == tenant,
        ScorecardModelApproval.model_id == model_id)
    if model_version:
        query = query.where(
            ScorecardModelApproval.model_version == model_version)
    return list(session.execute(
        query.order_by(ScorecardModelApproval.decided_at)).scalars())


# --------------------------------------------------------------------- runs


def record_run(session: Session, *, run_id: str, model_id: str,
               model_version: str, scorecard_type: str, period: str,
               matured: bool, metrics: dict[str, Any],
               performance_window_closes: str = "",
               population_rows: int = 0, opinion: str = "",
               opinion_reasoning: str = "",
               policy_version: str = policy_mod.POLICY_VERSION,
               binning_spec_version: str = "", analysis_id: str = "",
               trace_id: str = "", created_by: str = "",
               tenant: str = "") -> ScorecardValidationRun:
    """Record one validation of one model over one period.

    `matured` is required rather than derived here. §7 forbids computing
    actual against predicted on an immature cohort, and the caller is the
    one that knows whether the twelve-month window closed — deriving it in
    the registry from a period string would put the rule in the wrong place
    and make it easy to bypass by passing a different string.
    """
    row = ScorecardValidationRun(
        run_id=run_id, model_id=model_id, model_version=model_version,
        scorecard_type=scorecard_type, period=period, matured=bool(matured),
        performance_window_closes=performance_window_closes,
        population_rows=int(population_rows), metrics=metrics,
        opinion=opinion, opinion_reasoning=opinion_reasoning,
        policy_version=policy_version,
        binning_spec_version=binning_spec_version, analysis_id=analysis_id,
        trace_id=trace_id, origin=SYNTHETIC_DEMO, created_by=created_by,
        tenant=tenant)
    session.add(row)
    session.flush()
    return row


def runs_for(session: Session, model_id: str, *, period: str = "",
             tenant: str = "") -> list[ScorecardValidationRun]:
    query = select(ScorecardValidationRun).where(
        ScorecardValidationRun.tenant == tenant,
        ScorecardValidationRun.model_id == model_id)
    if period:
        query = query.where(ScorecardValidationRun.period == period)
    return list(session.execute(
        query.order_by(ScorecardValidationRun.created_at.desc())).scalars())


# ----------------------------------------------------------------- findings


def record_finding(session: Session, finding: policy_mod.Finding, *,
                   validation_run_id: str = "", created_by: str = "",
                   tenant: str = "") -> ScorecardFinding:
    """Persist a governed finding with the evidence behind it."""
    if finding.severity not in policy_mod.SEVERITIES:
        raise RegistryError(
            f"{finding.severity} is not a recognised severity.")
    if finding.status not in policy_mod.FINDING_STATUSES:
        raise RegistryError(f"{finding.status} is not a finding status.")
    if finding.breach and not finding.limit_source:
        raise RegistryError(
            f"{finding.finding_id} records a breach with no limit source. A "
            "breach of an unattributed limit cannot be defended: the reader "
            "has no way to tell a seeded default from a requirement.")

    existing = session.execute(
        select(ScorecardFinding).where(
            ScorecardFinding.tenant == tenant,
            ScorecardFinding.finding_id == finding.finding_id)
    ).scalar_one_or_none()
    row = existing or ScorecardFinding(finding_id=finding.finding_id,
                                       tenant=tenant)
    row.model_id = finding.model_id
    row.model_version = finding.model_version
    row.period = finding.period
    row.category = finding.category
    row.title = finding.title
    row.description = finding.description
    row.severity = finding.severity
    row.metric = finding.metric
    row.observed = finding.observed
    row.limit_value = finding.limit_value
    row.limit_source = finding.limit_source
    row.breach = bool(finding.breach)
    row.impact = finding.impact
    row.recommendation = finding.recommendation
    row.evidence = list(finding.evidence)
    row.analysis_run_ids = list(finding.analysis_run_ids)
    row.owner = finding.owner
    row.status = finding.status
    row.due_date = finding.due_date
    row.validation_run_id = validation_run_id
    row.created_by = created_by or row.created_by
    if existing is None:
        session.add(row)
    session.flush()
    return row


def set_finding_status(session: Session, finding_id: str, status: str, *,
                       by: str = "", tenant: str = "") -> ScorecardFinding:
    if status not in policy_mod.FINDING_STATUSES:
        raise RegistryError(
            f"{status} is not a finding status. Known statuses are "
            f"{', '.join(policy_mod.FINDING_STATUSES)}.")
    row = session.execute(
        select(ScorecardFinding).where(
            ScorecardFinding.tenant == tenant,
            ScorecardFinding.finding_id == finding_id)
    ).scalar_one_or_none()
    if row is None:
        raise RegistryError(f"{finding_id} is not a recorded finding.")
    row.status = status
    if status == policy_mod.CLOSED:
        row.closed_at = _now()
    if status == policy_mod.ACCEPTED:
        row.approved_by = by
        row.approved_at = _now()
    session.flush()
    return row


def findings_for(session: Session, *, model_id: str = "", period: str = "",
                 status: str = "", severity: str = "",
                 tenant: str = "") -> list[ScorecardFinding]:
    query = select(ScorecardFinding).where(ScorecardFinding.tenant == tenant)
    if model_id:
        query = query.where(ScorecardFinding.model_id == model_id)
    if period:
        query = query.where(ScorecardFinding.period == period)
    if status:
        query = query.where(ScorecardFinding.status == status)
    if severity:
        query = query.where(ScorecardFinding.severity == severity)
    return list(session.execute(
        query.order_by(ScorecardFinding.created_at.desc())).scalars())


# --------------------------------------------------------------------- pins


def pin(session: Session, *, user_id: int | None, scorecard_type: str,
        kind: str, reference: str, model_id: str = "", label: str = "",
        position: int = 0, tenant: str = "") -> ScorecardDashboardPin:
    existing = session.execute(
        select(ScorecardDashboardPin).where(
            ScorecardDashboardPin.tenant == tenant,
            ScorecardDashboardPin.user_id == user_id,
            ScorecardDashboardPin.scorecard_type == scorecard_type,
            ScorecardDashboardPin.model_id == model_id,
            ScorecardDashboardPin.kind == kind,
            ScorecardDashboardPin.reference == reference)
    ).scalar_one_or_none()
    if existing is not None:
        existing.label = label or existing.label
        existing.position = position
        session.flush()
        return existing
    row = ScorecardDashboardPin(
        user_id=user_id, scorecard_type=scorecard_type, model_id=model_id,
        kind=kind, reference=reference, label=label, position=position,
        tenant=tenant)
    session.add(row)
    session.flush()
    return row


def unpin(session: Session, *, user_id: int | None, scorecard_type: str,
          kind: str, reference: str, model_id: str = "",
          tenant: str = "") -> bool:
    removed = session.query(ScorecardDashboardPin).filter(
        ScorecardDashboardPin.tenant == tenant,
        ScorecardDashboardPin.user_id == user_id,
        ScorecardDashboardPin.scorecard_type == scorecard_type,
        ScorecardDashboardPin.model_id == model_id,
        ScorecardDashboardPin.kind == kind,
        ScorecardDashboardPin.reference == reference).delete()
    session.flush()
    return bool(removed)


def pins_for(session: Session, *, user_id: int | None,
             scorecard_type: str = "",
             tenant: str = "") -> list[ScorecardDashboardPin]:
    query = select(ScorecardDashboardPin).where(
        ScorecardDashboardPin.tenant == tenant,
        ScorecardDashboardPin.user_id == user_id)
    if scorecard_type:
        query = query.where(
            ScorecardDashboardPin.scorecard_type == scorecard_type)
    return list(session.execute(
        query.order_by(ScorecardDashboardPin.position,
                       ScorecardDashboardPin.id)).scalars())


# ------------------------------------------------------------------ reports


def record_report(session: Session, *, report_id: str, model_id: str,
                  model_version: str, scorecard_type: str, period: str,
                  title: str, structure_version: str, disclaimer: str,
                  sections: list[dict[str, Any]] | None = None,
                  opinion: str = "", status: str = "DRAFT",
                  validation_run_id: str = "", docx_path: str = "",
                  evidence_path: str = "", created_by: str = "",
                  tenant: str = "") -> ScorecardReport:
    """Record a generated validation report.

    `disclaimer` is required and stored. §0 forbids claiming CreditProbe
    certifies anything, and a disclaimer rendered from a template at
    download time is one refactor away from not being there — the copy
    somebody was given has to be recoverable from the record.
    """
    if not disclaimer.strip():
        raise RegistryError(
            "a validation report is recorded with the disclaimer it was "
            "issued with. CreditProbe does not provide regulatory "
            "certification, and a report record that cannot show it said so "
            "is not evidence of anything.")
    row = ScorecardReport(
        report_id=report_id, model_id=model_id, model_version=model_version,
        scorecard_type=scorecard_type, period=period, title=title,
        structure_version=structure_version, opinion=opinion, status=status,
        validation_run_id=validation_run_id, docx_path=docx_path,
        evidence_path=evidence_path, sections=sections or [],
        disclaimer=disclaimer, origin=SYNTHETIC_DEMO, created_by=created_by,
        tenant=tenant)
    session.add(row)
    session.flush()
    return row


def add_evidence(session: Session, report_id: str,
                 entries: list[dict[str, Any]], *,
                 tenant: str = "") -> int:
    """§55. Link every figure a report prints to the run that produced it."""
    for position, entry in enumerate(entries):
        session.add(ScorecardReportEvidence(
            report_id=report_id,
            section=str(entry.get("section", "")),
            label=str(entry.get("label", "")),
            metric=str(entry.get("metric", "")),
            value=entry.get("value"),
            value_text=str(entry.get("value_text", "")),
            validation_run_id=str(entry.get("validation_run_id", "")),
            analysis_id=str(entry.get("analysis_id", "")),
            trace_id=str(entry.get("trace_id", "")),
            workbook_sheet=str(entry.get("workbook_sheet", "")),
            workbook_cell=str(entry.get("workbook_cell", "")),
            position=position, tenant=tenant))
    session.flush()
    return len(entries)


def evidence_for(session: Session, report_id: str, *,
                 tenant: str = "") -> list[ScorecardReportEvidence]:
    return list(session.execute(
        select(ScorecardReportEvidence).where(
            ScorecardReportEvidence.tenant == tenant,
            ScorecardReportEvidence.report_id == report_id)
        .order_by(ScorecardReportEvidence.position)).scalars())


# -------------------------------------------------------------------- seed


#: Which seeded model of each scorecard is the one in production. The other
#: two are a challenger and a recalibration — real states for a model
#: registry to be in, and the reason the comparison screens have three
#: things to compare rather than one thing and two hypotheticals.
SEED_STATUS: dict[str, str] = {
    "INCUMBENT": ACTIVE,
    "CHALLENGER": CANDIDATE,
    "RECALIBRATED": CANDIDATE,
}

def _considered(scorecard_type: str,
                equation: equation_mod.Equation) -> tuple[str, ...]:
    """Variables the development weighed for this scorecard but did not use.

    Taken across every seeded model of the type, not just this one. "Which
    variables were considered and rejected?" is a standard validation
    question, and answering it from one model's own term list would only
    ever return nothing.
    """
    considered: list[str] = []
    for names in build_mod.MODEL_VARIABLES[scorecard_type].values():
        for name in names:
            if name not in considered:
                considered.append(name)
    active = set(equation.active_variables)
    return tuple(name for name in considered if name not in active)


SEED_OWNER = "Retail Credit Risk"
SEED_DEVELOPER = "Model Development"
SEED_VALIDATOR = "Independent Model Validation"


def seed(session: Session, *, tenant: str = "",
         created_by: str = "seed") -> dict[str, Any]:
    """Register the built scorecards, their specs and the demo policy.

    Reads what `build.py` produced rather than refitting: a registry that
    fitted its own copy of the model would be recording a different model
    from the one the lake was scored with, which is the exact failure §52's
    implementation replication exists to detect.
    """
    from backend.scorecard import synthetic as synth

    registered: list[dict[str, str]] = []
    for scorecard_type in (build_mod.APP, build_mod.BEH):
        spec = build_mod.load_spec(scorecard_type)
        register_binning_spec(session, spec, scorecard_type=scorecard_type,
                              target=build_mod.TARGET,
                              created_by=created_by, tenant=tenant)
        payload = build_mod.load_models(scorecard_type)
        months = (synth.APPLICATION_MONTHS if scorecard_type == build_mod.APP
                  else synth.BEHAVIORAL_MONTHS)
        matured = [m for m in months if synth.matured(m)]

        for kind in payload["models"]:
            eq = build_mod.load_equation(scorecard_type, kind)
            status = SEED_STATUS.get(kind, DEVELOPMENT)
            result = register(
                session, equation=eq,
                model_id=model_id_for(scorecard_type, kind),
                model_version="1.0.0", status=status,
                scorecard_type=scorecard_type,
                candidate_variables=_considered(scorecard_type, eq),
                spec=spec,
                owner=SEED_OWNER, developer=SEED_DEVELOPER,
                validator=SEED_VALIDATOR,
                development_period=(
                    f"{synth.DEVELOPMENT_MONTHS[0]} to "
                    f"{synth.DEVELOPMENT_MONTHS[-1]}"),
                validation_period=(f"{months[0]} to {matured[-1]}"
                                   if matured else ""),
                default_definition=dict(build_mod.DEFAULT_DEFINITION),
                population=spec.development_population,
                product_scope=scorecard_type.title() + " retail lending",
                materiality="HIGH", model_risk_rating="HIGH",
                created_by=created_by, tenant=tenant)
            registered.append({"model_id": result.model_id,
                               "model_version": result.model_version,
                               "status": result.status})

    written = register_limits(session, approved_by=created_by, tenant=tenant)
    return {"models": registered, "limits": written,
            "registry_version": REGISTRY_VERSION,
            "origin": SYNTHETIC_DEMO}
