"""
The Agent Registry: who CreditProbe's specialists are, and what each may do.

An agent here is a **job description**, not a model. It says what the specialist
is for, which governed tools it may call, which credit domains it may read,
how many steps it gets, what it must return, and what it is never allowed to do
without a person saying yes. §13 lists the fields; they are all present, and
none of them is decoration — the executor reads `allowed_tools` before every
call, the budget reads `maximum_steps`, and the approval gate reads
`human_approval_requirements`.

Why the definitions live in code
--------------------------------
They are seeded into `agent_definitions` so an administrator can see versions,
evaluation scores and history, and so a policy change is a database row rather
than a deploy. But the *source* of a definition is this file, for the same
reason the semantic ontology is a file: an agent's tool permissions are part of
the product's security posture, and a security posture that can be edited in a
form without review is not one.

What is deliberately absent
---------------------------
`allowed_tools` never contains a general one. There is no "run SQL", no "run
Python", no "fetch a URL", no "read a file". §14 is unambiguous about this, and
the reason is that a single general tool makes every other permission in this
file decorative — an agent that can run SQL can read every domain regardless of
`allowed_data_domains`.

Model roles, not model IDs
--------------------------
`model_role_preference` names one of the configured roles — router, planner,
interpretation, critic. Which model serves a role is configuration and stays
that way (§0, §3). A Chief Orchestrator is not a model; it is a job that
currently prefers the planner role.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from backend.agentic import tools as tool_registry

logger = logging.getLogger(__name__)

VERSION = "1.0"

# ---------------------------------------------------------------------------
# Governed credit domains
# ---------------------------------------------------------------------------

#: Domain identifiers carry a DOMAIN_ prefix and the agents do not, because an
#: agent called IFRS9 and a domain called IFRS9 in one module namespace is one
#: definition silently overwriting the other.
DOMAIN_DATA = "data"
DOMAIN_EXPOSURE = "exposure"
DOMAIN_RATINGS = "ratings"
DOMAIN_IFRS9 = "ifrs9"
DOMAIN_DELINQUENCY = "delinquency"
DOMAIN_COVENANTS = "covenants"
DOMAIN_PORTFOLIO = "portfolio"

DOMAINS: tuple[str, ...] = (
    DOMAIN_DATA, DOMAIN_EXPOSURE, DOMAIN_RATINGS, DOMAIN_IFRS9,
    DOMAIN_DELINQUENCY, DOMAIN_COVENANTS, DOMAIN_PORTFOLIO,
)

DOMAIN_LABELS: dict[str, str] = {
    DOMAIN_DATA: "Data",
    DOMAIN_EXPOSURE: "Exposure",
    DOMAIN_RATINGS: "Ratings & Financials",
    DOMAIN_IFRS9: "IFRS 9",
    DOMAIN_DELINQUENCY: "Delinquency",
    DOMAIN_COVENANTS: "Covenants & Collateral",
    DOMAIN_PORTFOLIO: "Portfolio",
}

#: Which domain each governed concept belongs to. Concepts come from the
#: semantic ontology; this maps them onto the specialists who own them, and a
#: concept with no entry belongs to no specialist in particular — which is
#: correct, not a gap: the Credit Analyst handles it.
CONCEPT_DOMAIN: dict[str, str] = {
    "exposure": DOMAIN_EXPOSURE,
    "ead": DOMAIN_EXPOSURE,
    "utilisation": DOMAIN_EXPOSURE,
    "rating": DOMAIN_RATINGS,
    "dscr": DOMAIN_RATINGS,
    "leverage": DOMAIN_RATINGS,
    "ecl": DOMAIN_IFRS9,
    "ecl_coverage": DOMAIN_IFRS9,
    "stage": DOMAIN_IFRS9,
    "stage_share": DOMAIN_IFRS9,
    "dpd": DOMAIN_DELINQUENCY,
    "headroom": DOMAIN_COVENANTS,
}


def domain_of(concept_id: str) -> str:
    """Which governed domain a concept belongs to, or "" if none owns it."""
    return CONCEPT_DOMAIN.get((concept_id or "").strip().lower(), "")


def concepts_in(domain: str) -> tuple[str, ...]:
    """Every governed concept a domain owns."""
    return tuple(sorted(c for c, d in CONCEPT_DOMAIN.items() if d == domain))


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

ACTIVE = "active"
DRAFT = "draft"
RETIRED = "retired"

REVIEWED = "reviewed"
UNREVIEWED = "unreviewed"


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Agent:
    """One specialist's job description. Every field of §13."""

    agent_id: str
    business_name: str
    purpose: str
    when_to_use: tuple[str, ...]
    when_not_to_use: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_data_domains: tuple[str, ...]
    allowed_methods: tuple[str, ...] = ()
    #: What a delegation to this agent must carry.
    input_contract: tuple[str, ...] = ("scope", "period", "objective")
    #: What it must return. A finding with no evidence reference is not a
    #: finding this product will show.
    output_contract: tuple[str, ...] = ("finding", "evidence", "confidence")
    maximum_steps: int = 4
    timeout_seconds: int = 120
    #: (attempts, base backoff seconds)
    retry_policy: tuple[int, int] = (2, 2)
    max_model_calls: int = 2
    max_rows_scanned: int = 2_000_000
    autonomy_level: int = 1
    human_approval_requirements: tuple[str, ...] = ()
    escalation_rules: tuple[str, ...] = ()
    validation_requirements: tuple[str, ...] = ("invariants", "grounding")
    model_role_preference: str = "router"
    owner: str = "Credit Risk"
    version: str = VERSION
    status: str = ACTIVE
    #: Set from the evaluation suite; 0.0 until one has run.
    evaluation_score: float = 0.0
    last_validation: str = ""
    certification_state: str = UNREVIEWED

    @property
    def domain_labels(self) -> tuple[str, ...]:
        return tuple(DOMAIN_LABELS.get(d, d) for d in self.allowed_data_domains)

    def may_use(self, tool_id: str) -> bool:
        return tool_id in self.allowed_tools

    def may_read(self, domain: str) -> bool:
        return domain in self.allowed_data_domains

    def needs_approval_for(self, action: str) -> bool:
        return action in self.human_approval_requirements

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "business_name": self.business_name,
            "purpose": self.purpose,
            "when_to_use": list(self.when_to_use),
            "when_not_to_use": list(self.when_not_to_use),
            "allowed_capabilities": list(self.allowed_capabilities),
            "allowed_tools": list(self.allowed_tools),
            "allowed_data_domains": list(self.allowed_data_domains),
            "domain_labels": list(self.domain_labels),
            "allowed_methods": list(self.allowed_methods),
            "input_contract": list(self.input_contract),
            "output_contract": list(self.output_contract),
            "maximum_steps": self.maximum_steps,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": {"attempts": self.retry_policy[0],
                             "backoff_seconds": self.retry_policy[1]},
            "max_model_calls": self.max_model_calls,
            "max_rows_scanned": self.max_rows_scanned,
            "autonomy_level": self.autonomy_level,
            "human_approval_requirements":
                list(self.human_approval_requirements),
            "escalation_rules": list(self.escalation_rules),
            "validation_requirements": list(self.validation_requirements),
            "model_role_preference": self.model_role_preference,
            "owner": self.owner,
            "version": self.version,
            "status": self.status,
            "evaluation_score": self.evaluation_score,
            "last_validation": self.last_validation,
            "certification_state": self.certification_state,
        }


# ---------------------------------------------------------------------------
# Shorthands used by several definitions
# ---------------------------------------------------------------------------

T = tool_registry

#: What an analytical specialist needs to answer a bounded credit question and
#: prove the answer: resolve the fields, plan the IR, run it, check it, and
#: package what it found. Nothing here compiles arbitrary SQL — `RUN_ANALYSIS`
#: takes a validated Analytical IR and nothing else.
_ANALYTICAL: tuple[str, ...] = (
    T.CATALOGUE_LOOKUP, T.FIELD_RESOLUTION, T.RELATIONSHIP_PATH,
    T.PLAN_ANALYSIS, T.RUN_ANALYSIS, T.NUMERICAL_KERNEL,
    T.PREVIOUS_RESULT, T.VALIDATE_INVARIANTS, T.EVIDENCE_PACKAGE,
)

_WITH_METHODS: tuple[str, ...] = _ANALYTICAL + (T.RUN_CERTIFIED_METHOD,)

_WITH_VISUAL: tuple[str, ...] = _WITH_METHODS + (T.SELECT_VISUALISATION,)


def _analysis_only() -> tuple[str, ...]:
    return ("ANALYSIS",)


# ---------------------------------------------------------------------------
# The specialists — §12
# ---------------------------------------------------------------------------

DATA_STEWARD = Agent(
    agent_id="data_steward",
    business_name="Data Steward",
    purpose=("Confirms what data exists, at which grain, for which periods, "
             "from which authoritative source, and whether it is fit to "
             "answer the question being asked."),
    when_to_use=(
        "A question is about the catalogue, a field, a period or a source.",
        "An analysis needs to know whether a period is published.",
        "A proactive review must confirm readiness before anything runs.",
    ),
    when_not_to_use=(
        "The question asks for a credit figure — that is an analytical "
        "specialist's work.",
        "The answer requires interpreting a movement rather than describing "
        "the data behind it.",
    ),
    allowed_capabilities=("DATA_DISCOVERY", "DATA_INSPECTION",
                          "DATA_DICTIONARY", "DATA_QUALITY",
                          "DATA_RELATIONSHIP"),
    allowed_tools=(T.CATALOGUE_LOOKUP, T.FIELD_RESOLUTION,
                   T.RELATIONSHIP_PATH, T.SOURCE_PROFILE, T.DATA_QUALITY,
                   T.PERIOD_READINESS, T.EVIDENCE_PACKAGE),
    allowed_data_domains=DOMAINS,
    input_contract=("scope", "period", "objective"),
    output_contract=("readiness", "findings", "evidence"),
    maximum_steps=6,
    max_model_calls=1,
    autonomy_level=0,
    escalation_rules=(
        "A period that is not published stops the run rather than being "
        "worked around.",
    ),
    validation_requirements=("catalogue_version",),
    model_role_preference="router",
    owner="Data Governance",
)

CREDIT_ANALYST = Agent(
    agent_id="credit_analyst",
    business_name="Credit Analyst",
    purpose=("Answers a bounded descriptive or diagnostic question over one "
             "governed population."),
    when_to_use=(
        "One measure, one population, one or two periods.",
        "A ranking, a grouping, a filter or a share.",
    ),
    when_not_to_use=(
        "The question spans several credit domains.",
        "The answer requires a segment-level or portfolio-level judgement.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_VISUAL,
    allowed_data_domains=(DOMAIN_EXPOSURE, DOMAIN_RATINGS, DOMAIN_IFRS9,
                          DOMAIN_DELINQUENCY, DOMAIN_COVENANTS),
    maximum_steps=4,
    autonomy_level=1,
    model_role_preference="router",
)

RATINGS_FINANCIALS = Agent(
    agent_id="ratings_financials",
    business_name="Ratings & Financials",
    purpose=("Rating migration, financial-ratio deterioration, and how the "
             "two move together."),
    when_to_use=(
        "A question about downgrades, upgrades or rating distribution.",
        "A question about DSCR, leverage or financial deterioration.",
    ),
    when_not_to_use=(
        "The question is about staging or expected credit loss — that is the "
        "IFRS 9 specialist.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_METHODS,
    allowed_data_domains=(DOMAIN_RATINGS, DOMAIN_EXPOSURE),
    allowed_methods=("rating_migration", "financial_deterioration"),
    maximum_steps=5,
    autonomy_level=1,
    escalation_rules=(
        "A rating movement with no matching financial movement is reported as "
        "unexplained rather than attributed.",
    ),
    model_role_preference="router",
)

IFRS9 = Agent(
    agent_id="ifrs9",
    business_name="IFRS 9",
    purpose="Stage, SICR, ECL, coverage and impairment movement.",
    when_to_use=(
        "A question about staging, expected credit loss or coverage.",
        "A question about impairment movement between periods.",
    ),
    when_not_to_use=(
        "The question is about days past due — that is Delinquency & "
        "Collections, even though the two correlate.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_METHODS,
    allowed_data_domains=(DOMAIN_IFRS9, DOMAIN_EXPOSURE),
    allowed_methods=("stage_migration", "ecl_movement", "coverage_analysis"),
    maximum_steps=5,
    autonomy_level=1,
    human_approval_requirements=("certify_method", "publish_provision"),
    validation_requirements=("invariants", "grounding", "reconciliation"),
    model_role_preference="router",
    owner="Impairment",
)

DELINQUENCY = Agent(
    agent_id="delinquency",
    business_name="Delinquency & Collections",
    purpose="DPD migration, roll rates, cures, and recovery behaviour.",
    when_to_use=(
        "A question about arrears, days past due, buckets or roll rates.",
    ),
    when_not_to_use=(
        "The question is about staging or ECL.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_METHODS,
    allowed_data_domains=(DOMAIN_DELINQUENCY, DOMAIN_EXPOSURE),
    allowed_methods=("dpd_migration", "roll_rate"),
    maximum_steps=5,
    autonomy_level=1,
    model_role_preference="router",
)

COVENANTS = Agent(
    agent_id="covenants",
    business_name="Covenant & Collateral",
    purpose="Headroom, breach proximity, collateral coverage and shortfall.",
    when_to_use=(
        "A question about covenant headroom or breaches.",
        "A question about collateral coverage or security shortfall.",
    ),
    when_not_to_use=(
        "The question is about the borrower's rating rather than its "
        "obligations under the facility.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_METHODS,
    allowed_data_domains=(DOMAIN_COVENANTS, DOMAIN_EXPOSURE),
    allowed_methods=("headroom_analysis", "collateral_coverage"),
    maximum_steps=5,
    autonomy_level=1,
    model_role_preference="router",
)

PORTFOLIO_RISK = Agent(
    agent_id="portfolio_risk",
    business_name="Portfolio Risk",
    purpose=("Portfolio and segment trends, concentration, risk appetite and "
             "the drivers behind a movement."),
    when_to_use=(
        "A question at the portfolio or segment grain.",
        "A concentration or risk-appetite question.",
        "A proactive review of a newly published period.",
    ),
    when_not_to_use=(
        "The question is about one named borrower.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_VISUAL + (T.PRE_SCREEN,),
    allowed_data_domains=DOMAINS,
    allowed_methods=("portfolio_review", "concentration", "driver_analysis"),
    maximum_steps=8,
    timeout_seconds=240,
    max_model_calls=3,
    autonomy_level=1,
    human_approval_requirements=("change_risk_appetite", "change_limits"),
    escalation_rules=(
        "A portfolio movement concentrated in a handful of borrowers is "
        "reported as concentration, not as a broad trend.",
    ),
    model_role_preference="planner",
    owner="Portfolio Risk",
)

EARLY_WARNING = Agent(
    agent_id="early_warning",
    business_name="Early Warning",
    purpose="Proactive deterioration signals and forward risk indicators.",
    when_to_use=(
        "A question about which borrowers are deteriorating.",
        "A watchlist review.",
    ),
    when_not_to_use=(
        "The question asks for a prediction — CreditProbe reports governed "
        "signals, it does not forecast.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_METHODS + (T.PRE_SCREEN,),
    allowed_data_domains=DOMAINS,
    allowed_methods=("early_warning_screen", "watchlist_review"),
    maximum_steps=6,
    autonomy_level=1,
    escalation_rules=(
        "A signal without a governed threshold behind it is not reported as a "
        "warning.",
    ),
    model_role_preference="router",
    owner="Early Warning",
)

STRESS = Agent(
    agent_id="stress",
    business_name="Stress & Scenario",
    purpose="Governed scenario and sensitivity analysis.",
    when_to_use=(
        "A question about a defined scenario or a sensitivity.",
    ),
    when_not_to_use=(
        "The scenario is not one the bank has defined — CreditProbe does not "
        "invent scenarios.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=_WITH_METHODS + (T.RUN_SCENARIO,),
    allowed_data_domains=DOMAINS,
    allowed_methods=("scenario_run", "sensitivity"),
    maximum_steps=6,
    timeout_seconds=240,
    autonomy_level=1,
    human_approval_requirements=("certify_method",),
    model_role_preference="planner",
    owner="Stress Testing",
)

VALIDATION = Agent(
    agent_id="validation",
    business_name="Validation & Assurance",
    purpose=("Checks every calculation before it is reported: plan validity, "
             "business invariants, reconciliation, grounding, and whether the "
             "conclusion the other specialists reached is what the evidence "
             "supports."),
    when_to_use=(
        "Always, before an agentic answer is synthesised.",
    ),
    when_not_to_use=(
        "Never skipped. A result nothing checked is not a result this product "
        "reports.",
    ),
    allowed_capabilities=_analysis_only(),
    allowed_tools=(T.VALIDATE_INVARIANTS, T.RECONCILE, T.EVIDENCE_PACKAGE,
                   T.PREVIOUS_RESULT, T.GROUNDING_CHECK),
    allowed_data_domains=DOMAINS,
    maximum_steps=6,
    max_model_calls=1,
    autonomy_level=0,
    validation_requirements=("invariants", "grounding", "reconciliation",
                             "plan_validation"),
    escalation_rules=(
        "A failed invariant blocks the answer rather than annotating it.",
        "A disagreement with another specialist is recorded, not averaged.",
    ),
    model_role_preference="critic",
    owner="Model Validation",
)

WORKFLOW_COORDINATOR = Agent(
    agent_id="workflow_coordinator",
    business_name="Workflow Coordinator",
    purpose=("Drafts assignments, review requests, case ownership and "
             "follow-up actions — always as drafts."),
    when_to_use=(
        "A validated finding needs somebody to act on it.",
        "A Risk Case needs an owner or a review.",
    ),
    when_not_to_use=(
        "Nothing has been validated yet.",
    ),
    allowed_capabilities=("PROJECT_ACTION", "INVESTIGATION_ACTION",
                          "ANALYSIS_ACTION"),
    allowed_tools=(T.DRAFT_WORKFLOW, T.DRAFT_INVESTIGATION, T.DRAFT_RISK_CASE,
                   T.ADD_TO_PROJECT, T.EVIDENCE_PACKAGE),
    allowed_data_domains=DOMAINS,
    maximum_steps=4,
    autonomy_level=2,
    human_approval_requirements=("send_workflow", "assign_owner",
                                 "close_case", "external_communication"),
    escalation_rules=(
        "Everything this agent produces is a draft. Sending it is a person's "
        "decision.",
    ),
    validation_requirements=(),
    model_role_preference="router",
    owner="Credit Operations",
)

CHIEF_ORCHESTRATOR = Agent(
    agent_id="chief_orchestrator",
    business_name="Chief Orchestrator",
    purpose=("Decomposes a broad request into bounded tasks, delegates them "
             "to specialists, resolves disagreements against the deterministic "
             "evidence, and synthesises one answer."),
    when_to_use=(
        "A request spans several governed domains.",
        "Several specialists have findings that have to be reconciled.",
        "A newly published period is being reviewed proactively.",
    ),
    when_not_to_use=(
        "One specialist can answer the question. Coordinating one agent is "
        "overhead with a title.",
    ),
    allowed_capabilities=("ANALYSIS", "PROJECT_ACTION",
                          "INVESTIGATION_ACTION"),
    allowed_tools=(T.CATALOGUE_LOOKUP, T.PLAN_ANALYSIS, T.PRE_SCREEN,
                   T.EVIDENCE_PACKAGE, T.PREVIOUS_RESULT,
                   T.DRAFT_RISK_CASE, T.DRAFT_INVESTIGATION,
                   T.DRAFT_WORKFLOW, T.ADD_TO_PROJECT),
    allowed_data_domains=DOMAINS,
    maximum_steps=12,
    timeout_seconds=600,
    max_model_calls=4,
    autonomy_level=2,
    human_approval_requirements=("send_workflow", "close_case",
                                 "publish_data", "certify_method",
                                 "change_limits", "change_risk_appetite",
                                 "external_communication", "modify_client_data"),
    escalation_rules=(
        "A budget that runs out stops the run and reports what was completed.",
        "A specialist that fails does not become a fabricated component of a "
        "complete answer.",
    ),
    validation_requirements=("invariants", "grounding", "reconciliation",
                             "assurance"),
    model_role_preference="planner",
    owner="Credit Risk",
)


AGENTS: tuple[Agent, ...] = (
    DATA_STEWARD,
    CREDIT_ANALYST,
    RATINGS_FINANCIALS,
    IFRS9,
    DELINQUENCY,
    COVENANTS,
    PORTFOLIO_RISK,
    EARLY_WARNING,
    STRESS,
    VALIDATION,
    WORKFLOW_COORDINATOR,
    CHIEF_ORCHESTRATOR,
)

_BY_ID: dict[str, Agent] = {a.agent_id: a for a in AGENTS}

#: Which specialist owns each governed domain, for delegation. The Credit
#: Analyst is the fallback and deliberately owns none: a domain with no
#: specialist is answered by a generalist, not left unanswered.
DOMAIN_AGENT: dict[str, str] = {
    DOMAIN_DATA: DATA_STEWARD.agent_id,
    DOMAIN_RATINGS: RATINGS_FINANCIALS.agent_id,
    DOMAIN_IFRS9: IFRS9.agent_id,
    DOMAIN_DELINQUENCY: DELINQUENCY.agent_id,
    DOMAIN_COVENANTS: COVENANTS.agent_id,
    DOMAIN_EXPOSURE: CREDIT_ANALYST.agent_id,
    DOMAIN_PORTFOLIO: PORTFOLIO_RISK.agent_id,
}


def agent(agent_id: str) -> Agent | None:
    return _BY_ID.get((agent_id or "").strip().lower())


def require(agent_id: str) -> Agent:
    found = agent(agent_id)
    if found is None:
        raise KeyError(f"'{agent_id}' is not a registered CreditProbe agent.")
    return found


def all_agents(*, status: str = ACTIVE) -> tuple[Agent, ...]:
    return tuple(a for a in AGENTS if not status or a.status == status)


def specialists() -> tuple[Agent, ...]:
    """Everyone the Chief Orchestrator may delegate to — which is everyone
    except itself. An orchestrator that can delegate to an orchestrator is the
    recursion §73 asks to be prevented, and preventing it here costs nothing."""
    return tuple(a for a in AGENTS if a.agent_id != CHIEF_ORCHESTRATOR.agent_id)


def agent_for_domain(domain: str) -> Agent:
    """The specialist who owns a governed domain."""
    return _BY_ID.get(DOMAIN_AGENT.get((domain or "").lower(), ""),
                      CREDIT_ANALYST)


def agents_for(concepts: list[str] | tuple[str, ...]) -> tuple[Agent, ...]:
    """Which specialists a set of governed concepts needs.

    Order is stable — registry order, not set order — because the specialist
    list is shown to the user and a list that reshuffles between two identical
    requests looks like the plan changed.
    """
    wanted: set[str] = set()
    for concept in concepts or ():
        domain = domain_of(str(concept))
        if domain:
            wanted.add(agent_for_domain(domain).agent_id)
    return tuple(a for a in AGENTS if a.agent_id in wanted)


def fingerprint() -> str:
    """A stable hash of every definition, so a run records which registry it
    ran under and a changed permission is visible in the audit trail."""
    payload = json.dumps([a.to_dict() for a in AGENTS], sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def catalogue() -> dict[str, Any]:
    return {
        "version": VERSION,
        "fingerprint": fingerprint(),
        "agents": [a.to_dict() for a in AGENTS],
        "domains": [{"id": d, "label": DOMAIN_LABELS[d],
                     "concepts": list(concepts_in(d))} for d in DOMAINS],
    }


__all__ = [
    "ACTIVE",
    "AGENTS",
    "CHIEF_ORCHESTRATOR",
    "CONCEPT_DOMAIN",
    "COVENANTS",
    "CREDIT_ANALYST",
    "DATA_STEWARD",
    "DELINQUENCY",
    "DOMAINS",
    "DOMAIN_AGENT",
    "DOMAIN_COVENANTS",
    "DOMAIN_DATA",
    "DOMAIN_DELINQUENCY",
    "DOMAIN_EXPOSURE",
    "DOMAIN_IFRS9",
    "DOMAIN_LABELS",
    "DOMAIN_PORTFOLIO",
    "DOMAIN_RATINGS",
    "DRAFT",
    "EARLY_WARNING",
    "IFRS9",
    "PORTFOLIO_RISK",
    "RATINGS_FINANCIALS",
    "RETIRED",
    "STRESS",
    "VALIDATION",
    "VERSION",
    "WORKFLOW_COORDINATOR",
    "Agent",
    "agent",
    "agent_for_domain",
    "agents_for",
    "all_agents",
    "catalogue",
    "concepts_in",
    "domain_of",
    "fingerprint",
    "require",
    "specialists",
]
