"""
The Investigation Blueprint Library. §66, §67, §68, §69.

What a blueprint is, and why it is not a prompt
------------------------------------------------
A blueprint is the list of things a competent analyst would look at before
answering a question of a given shape. "Contracting looks worse — what is going
on?" has an answer that a good credit analyst arrives at by checking sixteen
things, and the difference between a good answer and a plausible one is almost
entirely which of the sixteen got checked.

A model asked the same question checks whatever the question mentioned. That is
the failure this library exists for: not wrong analysis, but INCOMPLETE analysis
that reads as complete because nothing in the answer says what was skipped.

So a blueprint states its objectives, and §68's rule is the load-bearing one:

    "The planner may omit an unavailable optional branch only when: availability
     is checked; omission is explicit; the limitation is shown; objective
     coverage records it."

Four conditions, all of them, or the branch is not omitted — it is missing.

Mandatory and optional
----------------------
A MANDATORY objective cannot be skipped. If its data is unavailable the
investigation is incomplete and says so; it does not quietly become a shorter
investigation. An OPTIONAL objective may be omitted under §68's four
conditions, and every omission is recorded with its reason.

That distinction is the blueprint's real content. Anybody can list sixteen
things to look at; deciding which four cannot be dropped is the judgement.

Selection is scored, not matched
---------------------------------
§69: "Do not choose solely from keywords." A question mentioning "ECL" is not
necessarily an ECL movement investigation — it might be a data question, a
methodology question, or a concentration question that happens to use ECL as
its measure. So selection reads twelve signals and reports why, and a
low-scoring best match is reported as a low-scoring best match rather than as a
choice.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any

BLUEPRINT_VERSION = "1.0.0"

# --------------------------------------------------------------- statuses
DRAFT = "DRAFT"
SYSTEM_VALIDATED = "SYSTEM_VALIDATED"
SME_REVIEW_REQUIRED = "SME_REVIEW_REQUIRED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
RETIRED = "RETIRED"
STALE = "STALE"

STATUSES: tuple[str, ...] = (DRAFT, SYSTEM_VALIDATED, SME_REVIEW_REQUIRED,
                             APPROVED, REJECTED, RETIRED, STALE)

#: §66: "Only approved/system-validated active blueprints may be used in
#: production." Same shape as a teaching case, and for the same reason: a
#: blueprint decides what gets looked at, so an unreviewed one decides what
#: gets missed.
USABLE: frozenset[str] = frozenset({APPROVED, SYSTEM_VALIDATED})

# ------------------------------------------------------------------ scope
CORPORATE = "CORPORATE"
RETAIL = "RETAIL"
#: §66's third value, spelled out: a blueprint that applies to both keeps a
#: SEPARATE applicability record for each, because "both" almost always means
#: "the same objectives with different grain, vocabulary and data", and one
#: record cannot hold two of those.
BOTH = "BOTH_AS_SEPARATE_APPLICABILITY_RECORDS"
NO_SCOPE = "NONE"

SCOPES: tuple[str, ...] = (CORPORATE, RETAIL, BOTH, NO_SCOPE)


@dataclass(frozen=True)
class Objective:
    """One thing the investigation looks at."""

    id: str
    statement: str
    #: A mandatory objective cannot be omitted. If its data is unavailable the
    #: investigation is incomplete and says so.
    mandatory: bool = True
    #: The governed concepts it needs. Used to check availability before the
    #: investigation starts rather than discovering it halfway through.
    concepts: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    #: The engine that answers it, where a governed one does.
    engine: str = ""
    #: What a correct answer to this objective must satisfy.
    invariants: tuple[str, ...] = ()


def _o(oid: str, statement: str, *, mandatory: bool = True,
       concepts: tuple[str, ...] = (), datasets: tuple[str, ...] = (),
       engine: str = "", invariants: tuple[str, ...] = ()) -> Objective:
    return Objective(id=oid, statement=statement, mandatory=mandatory,
                     concepts=concepts, datasets=datasets, engine=engine,
                     invariants=invariants)


@dataclass
class Blueprint:
    """§66's schema."""

    blueprint_id: str = ""
    version: int = 1
    business_name: str = ""
    family: str = ""
    description: str = ""
    applicable_scope: str = NO_SCOPE
    supported_grains: list[str] = field(default_factory=list)
    #: Phrases that suggest this blueprint. NEVER the whole selection — §69 is
    #: explicit — but a real signal, and the one a reader recognises.
    trigger_patterns: list[str] = field(default_factory=list)
    when_to_use: str = ""
    when_not_to_use: str = ""

    required_objectives: list[Objective] = field(default_factory=list)
    optional_objectives: list[Objective] = field(default_factory=list)
    required_concepts: list[str] = field(default_factory=list)
    optional_concepts: list[str] = field(default_factory=list)
    required_data_capabilities: list[str] = field(default_factory=list)
    optional_data_capabilities: list[str] = field(default_factory=list)
    required_methods: list[str] = field(default_factory=list)
    optional_methods: list[str] = field(default_factory=list)
    required_relationships: list[str] = field(default_factory=list)

    period_contract: dict[str, Any] = field(default_factory=dict)
    population_contract: dict[str, Any] = field(default_factory=dict)
    grain_contract: dict[str, Any] = field(default_factory=dict)

    hypothesis_templates: list[str] = field(default_factory=list)
    challenge_templates: list[str] = field(default_factory=list)
    mandatory_validations: list[str] = field(default_factory=list)
    #: When the investigation may stop. Without these an open investigation
    #: runs until a budget stops it, and a budget is not an analytical
    #: judgement.
    stopping_rules: list[str] = field(default_factory=list)
    minimum_evidence: int = 1

    expected_outputs: list[str] = field(default_factory=list)
    interpretation_contract: dict[str, Any] = field(default_factory=dict)
    visualization_contract: dict[str, Any] = field(default_factory=dict)
    limitations_contract: dict[str, Any] = field(default_factory=dict)

    officer_level: int = 2
    agent_roles: list[str] = field(default_factory=list)
    model_route: str = "C_COMPLEX"
    cost_budget: float = 0.0
    latency_budget: float = 0.0

    owner: str = ""
    review_status: str = DRAFT
    reviewer: str = ""
    approved_at: str = ""
    last_validated: str = ""
    evaluation_score: float = 0.0
    ontology_version: str = ""
    method_version: str = ""
    fingerprint: str = ""
    status: str = DRAFT

    @property
    def objectives(self) -> list[Objective]:
        return [*self.required_objectives, *self.optional_objectives]

    @property
    def usable(self) -> bool:
        return self.review_status in USABLE and self.status not in (
            RETIRED, STALE)

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["required_objectives"] = [asdict(o)
                                       for o in self.required_objectives]
        body["optional_objectives"] = [asdict(o)
                                       for o in self.optional_objectives]
        return body

    @classmethod
    def from_dict(cls, raw: Any) -> Blueprint:
        raw = dict(raw) if isinstance(raw, dict) else {}
        for key in ("required_objectives", "optional_objectives"):
            raw[key] = [Objective(**o) if isinstance(o, dict) else o
                        for o in (raw.get(key) or [])]
        allowed = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in allowed})


FINGERPRINTED: tuple[str, ...] = (
    "blueprint_id", "family", "applicable_scope", "required_objectives",
    "optional_objectives", "required_concepts", "required_methods",
    "required_relationships", "mandatory_validations", "stopping_rules",
)


def fingerprint(blueprint: Blueprint) -> str:
    body = blueprint.to_dict()
    payload = {name: body.get(name) for name in FINGERPRINTED}
    blob = json.dumps(payload, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# §67 — the families
# ---------------------------------------------------------------------------

PORTFOLIO_HEALTH = "PORTFOLIO_HEALTH_REVIEW"
SEGMENT_DETERIORATION = "SEGMENT_DETERIORATION"
BORROWER_DEEP_DIVE = "BORROWER_DEEP_DIVE"
ECL_MOVEMENT = "IFRS9_ECL_MOVEMENT"
ECL_DECOMPOSITION = "ECL_CHANGE_DECOMPOSITION"
STAGE_MIGRATION = "STAGE_MIGRATION"
RATING_MIGRATION = "RATING_MIGRATION"
DPD_MIGRATION = "DPD_MIGRATION"
CONCENTRATION = "CONCENTRATION"
EARLY_WARNING = "EARLY_WARNING"
COVENANT_COLLATERAL = "COVENANT_AND_COLLATERAL_DETERIORATION"
FINANCIAL_DETERIORATION = "FINANCIAL_DETERIORATION"
CONTRADICTORY = "CONTRADICTORY_SIGNALS"
RISK_APPETITE = "RISK_APPETITE"
STRESS = "STRESS_SCENARIO"
VINTAGE = "VINTAGE_COHORT"
DATA_QUALITY = "DATA_QUALITY_RELATIONSHIP_INVESTIGATION"
MODEL_PERFORMANCE = "MODEL_METHOD_PERFORMANCE_REVIEW"
DEMO_EXECUTIVE = "CLIENT_DEMO_EXECUTIVE_PORTFOLIO_REVIEW"

# ------------------------------------------- the corporate graph. B45-B49.
#
# Ten families whose questions cannot be answered from the credit book at
# all. Each one exists because an analyst asking it would otherwise be
# offered a blueprint about facilities, which shares its words and answers a
# different question.
GROUP_STRUCTURE = "CORPORATE_GROUP_STRUCTURE"
BENEFICIAL_OWNERSHIP = "BENEFICIAL_OWNERSHIP"
CONNECTED_COUNTERPARTY = "CONNECTED_COUNTERPARTY_ASSESSMENT"
GROUP_LIMIT = "GROUP_LIMIT_UTILISATION"
NETWORK_CONTAGION = "NETWORK_CONTAGION"
NETWORK_CENTRALITY = "NETWORK_CENTRALITY"
SUPPLY_CHAIN = "SUPPLY_CHAIN_DEPENDENCE"
GUARANTEE_NETWORK = "GUARANTEE_NETWORK"
HIDDEN_RELATIONSHIP = "HIDDEN_RELATIONSHIP_DISCOVERY"
GRAPH_QUALITY = "GRAPH_DATA_QUALITY_REVIEW"

FAMILIES: tuple[str, ...] = (
    PORTFOLIO_HEALTH, SEGMENT_DETERIORATION, BORROWER_DEEP_DIVE, ECL_MOVEMENT,
    ECL_DECOMPOSITION, STAGE_MIGRATION, RATING_MIGRATION, DPD_MIGRATION,
    CONCENTRATION, EARLY_WARNING, COVENANT_COLLATERAL,
    FINANCIAL_DETERIORATION, CONTRADICTORY, RISK_APPETITE, STRESS, VINTAGE,
    DATA_QUALITY, MODEL_PERFORMANCE, DEMO_EXECUTIVE,
    GROUP_STRUCTURE, BENEFICIAL_OWNERSHIP, CONNECTED_COUNTERPARTY,
    GROUP_LIMIT, NETWORK_CONTAGION, NETWORK_CENTRALITY, SUPPLY_CHAIN,
    GUARANTEE_NETWORK, HIDDEN_RELATIONSHIP, GRAPH_QUALITY,
)

#: Validations no investigation may skip, whatever its family. Not a per-
#: blueprint choice: these are the four ways an investigation is wrong in a way
#: nobody can see from its output.
UNIVERSAL_VALIDATIONS: tuple[str, ...] = (
    "periods_aligned",
    "population_accounted_for",
    "grain_consistent",
    "totals_reconcile",
)

#: When an investigation may stop, by default. §93 elaborates; these are the
#: floor, and a blueprint that states none inherits them.
DEFAULT_STOPPING_RULES: tuple[str, ...] = (
    "every mandatory objective is settled",
    "every material observation has been challenged",
    "no unresolved material contradiction remains",
    "further analysis would not change the bottom line",
)


def _bp(blueprint_id: str, family: str, name: str, description: str, *,
        required: list[Objective], optional: list[Objective] | None = None,
        scope: str = NO_SCOPE, grains: tuple[str, ...] = ("portfolio",),
        triggers: tuple[str, ...] = (), when: str = "", when_not: str = "",
        officer: int = 2, route: str = "C_COMPLEX",
        hypotheses: tuple[str, ...] = (),
        challenges: tuple[str, ...] = (),
        validations: tuple[str, ...] = (),
        outputs: tuple[str, ...] = (),
        minimum_evidence: int = 3) -> Blueprint:
    built = Blueprint(
        blueprint_id=blueprint_id, family=family, business_name=name,
        description=description, applicable_scope=scope,
        supported_grains=list(grains), trigger_patterns=list(triggers),
        when_to_use=when, when_not_to_use=when_not,
        required_objectives=list(required),
        optional_objectives=list(optional or []),
        required_concepts=sorted({c for o in required for c in o.concepts}),
        optional_concepts=sorted({c for o in (optional or [])
                                  for c in o.concepts}),
        required_data_capabilities=sorted({d for o in required
                                           for d in o.datasets}),
        optional_data_capabilities=sorted({d for o in (optional or [])
                                           for d in o.datasets}),
        required_methods=sorted({o.engine for o in required if o.engine}),
        optional_methods=sorted({o.engine for o in (optional or [])
                                 if o.engine}),
        hypothesis_templates=list(hypotheses),
        challenge_templates=list(challenges),
        mandatory_validations=sorted(set(UNIVERSAL_VALIDATIONS)
                                     | set(validations)),
        stopping_rules=list(DEFAULT_STOPPING_RULES),
        minimum_evidence=minimum_evidence,
        expected_outputs=list(outputs),
        officer_level=officer, model_route=route,
        review_status=SYSTEM_VALIDATED, status=SYSTEM_VALIDATED,
        owner="CreditProbe methodology",
    )
    built.fingerprint = fingerprint(built)
    return built


# ------------------------------------------------- §68's segment blueprint
#
# Written out in full because §68 writes it out in full, and because it is the
# blueprint every other deterioration investigation borrows from. The four
# mandatory objectives are the ones an answer is wrong without: what moved, how
# much of the book it touches, whether it is a few names or the segment, and
# whether it is a trend or a quarter.

_SEGMENT_REQUIRED = [
    _o("exposure", "Exposure and portfolio share for the segment",
       concepts=("exposure at default",), datasets=("portfolio_facility",),
       invariants=("share_bounds",)),
    _o("ecl_movement", "ECL movement over the window, with the population "
                       "accounted for on both sides",
       concepts=("expected credit loss",), datasets=("ifrs9_staging",),
       engine="ecl_movement",
       invariants=("opening_plus_change_equals_closing",)),
    _o("breadth", "Whether the movement is broad or concentrated",
       engine="breadth", invariants=("min_entities",)),
    _o("persistence", "Whether the movement persists or is one period",
       engine="persistence", invariants=("required_history_stated",)),
]

_SEGMENT_OPTIONAL = [
    _o("concentration", "Concentration within the segment", mandatory=False,
       engine="concentration", concepts=("exposure at default",)),
    _o("rating_distribution", "Rating distribution and migration",
       mandatory=False, concepts=("internal rating",),
       datasets=("customer_ratings", "rating_transitions")),
    _o("stage_distribution", "Stage distribution and migration",
       mandatory=False, concepts=("ifrs 9 stage",),
       datasets=("ifrs9_staging",)),
    _o("parameters", "PD and LGD movement", mandatory=False,
       concepts=("twelve-month pd",), datasets=("ifrs9_staging",)),
    _o("delinquency", "DPD and delinquency", mandatory=False,
       concepts=("days past due",), datasets=("facility_delinquency",)),
    _o("financials", "Financial-ratio deterioration", mandatory=False,
       concepts=("net leverage", "debt service coverage ratio"),
       datasets=("borrower_financials",)),
    _o("utilisation", "Utilisation against limits", mandatory=False,
       concepts=("limit utilisation",), datasets=("facility_limits",)),
    _o("covenants", "Covenant position", mandatory=False,
       concepts=("covenant headroom",), datasets=("covenant_tests",)),
    _o("collateral", "Collateral coverage", mandatory=False,
       datasets=("collateral_register",)),
    _o("population", "New and exited customer mix", mandatory=False,
       engine="population_effect"),
    _o("contributors", "Customer contributors to the movement",
       mandatory=False, engine="drivers",
       invariants=("components_reconcile",)),
    _o("data_quality", "Data-quality and relationship limitations",
       mandatory=False),
    _o("challenge", "Challenge and alternative explanation", mandatory=False,
       engine="challenge"),
    _o("next", "The next analysis worth running", mandatory=False),
]

SEGMENT_BLUEPRINT = _bp(
    "bp-segment-deterioration", SEGMENT_DETERIORATION,
    "Segment or sector deterioration",
    "What changed in a segment, how much of it matters, whether it is a few "
    "names or the whole segment, and whether it will still be true next "
    "quarter.",
    required=_SEGMENT_REQUIRED, optional=_SEGMENT_OPTIONAL,
    grains=("segment", "sector", "borrower"),
    triggers=("deteriorat", "what is going on in", "worse", "concern",
              "look into", "problem with"),
    when="A named segment or sector appears to have worsened and the question "
         "is open rather than about one measure.",
    when_not="The question names one measure and one period — that is an "
             "aggregation, and running a sixteen-branch investigation for it "
             "wastes the reader's attention.",
    officer=3,
    hypotheses=(
        "Exposure growth or portfolio mix explains the movement.",
        "Underlying credit quality deteriorated.",
        "The result is concentrated in a few borrowers.",
        "The result is broad across the segment.",
        "The change is temporary rather than persistent.",
        "Data, joins, periods or denominator changes explain the apparent "
        "movement.",
    ),
    challenges=("largest_borrower", "population_change", "new_exited",
                "denominator", "one_period_noise", "period_alignment",
                "grain_alignment", "join_integrity", "hidden_offsets",
                "overlay_effect", "data_quality", "alternative_conclusion",
                "second_method"),
    validations=("components_reconcile", "population_matched_both_dates"),
    outputs=("bottom line", "materiality", "main drivers", "breadth",
             "exceptions", "credit-risk meaning", "limitations",
             "next best analysis"),
    minimum_evidence=6,
)


def _simple(blueprint_id: str, family: str, name: str, description: str,
            required: list[Objective], optional: list[Objective], **kwargs
            ) -> Blueprint:
    return _bp(blueprint_id, family, name, description, required=required,
               optional=optional, **kwargs)


LIBRARY: tuple[Blueprint, ...] = (
    SEGMENT_BLUEPRINT,

    _simple("bp-portfolio-health", PORTFOLIO_HEALTH, "Portfolio health review",
            "The whole book at a reporting date: where it stands, what moved, "
            "and what needs attention.",
            [_o("exposure", "Total exposure and its distribution",
                concepts=("exposure at default",),
                datasets=("portfolio_facility",)),
             _o("quality", "Stage and rating distribution",
                concepts=("ifrs 9 stage", "internal rating"),
                datasets=("ifrs9_staging", "customer_ratings")),
             _o("ecl", "ECL and coverage",
                concepts=("expected credit loss", "ecl coverage"),
                datasets=("ifrs9_staging",)),
             _o("attention", "What needs attention, with materiality",
                engine="materiality")],
            [_o("concentration", "Concentration", mandatory=False,
                engine="concentration"),
             _o("appetite", "Position against risk appetite", mandatory=False,
                datasets=("risk_appetite_limits",)),
             _o("movement", "What moved since the prior period",
                mandatory=False, engine="drivers"),
             _o("watchlist", "Watchlist position", mandatory=False,
                datasets=("watchlist_register",))],
            grains=("portfolio", "segment"), officer=4,
            triggers=("portfolio", "the book", "overall", "how are we"),
            when="An open question about the whole portfolio.",
            when_not="A question about one segment — the segment blueprint "
                     "asks better questions about a segment."),

    _simple("bp-borrower-deep-dive", BORROWER_DEEP_DIVE, "Borrower deep dive",
            "Everything governed data holds about one borrower, in the order "
            "a credit officer would want it.",
            [_o("position", "Exposure, limits and utilisation",
                concepts=("exposure at default", "limit utilisation"),
                datasets=("portfolio_facility", "facility_limits")),
             _o("quality", "Rating, stage and ECL",
                concepts=("internal rating", "ifrs 9 stage",
                          "expected credit loss"),
                datasets=("customer_ratings", "ifrs9_staging")),
             _o("performance", "Delinquency and payment behaviour",
                concepts=("days past due",),
                datasets=("facility_delinquency", "payment_history"))],
            [_o("financials", "Financial ratios and their direction",
                mandatory=False, concepts=("net leverage",),
                datasets=("borrower_financials",)),
             _o("covenants", "Covenant position", mandatory=False,
                datasets=("covenant_tests",)),
             _o("collateral", "Collateral and coverage", mandatory=False,
                datasets=("collateral_register",)),
             _o("group", "Group exposure", mandatory=False,
                datasets=("group_structure",)),
             _o("history", "How the position has moved", mandatory=False,
                engine="persistence")],
            grains=("borrower", "obligor"), scope=BOTH, officer=2,
            triggers=("tell me about", "deep dive", "everything on",
                      "what do we know about")),

    _simple("bp-ecl-movement", ECL_MOVEMENT, "IFRS 9 ECL movement",
            "How ECL moved between two dates, with the population accounted "
            "for on both sides.",
            [_o("movement", "Opening and closing ECL, and the change",
                concepts=("expected credit loss",),
                datasets=("ifrs9_staging",), engine="ecl_movement",
                invariants=("opening_plus_change_equals_closing",)),
             _o("population", "New and exited accounts", engine="population_effect"),
             _o("coverage", "ECL coverage, before and after",
                concepts=("ecl coverage",))],
            [_o("by_stage", "The movement by stage", mandatory=False,
                concepts=("ifrs 9 stage",)),
             _o("drivers", "Which entities moved it", mandatory=False,
                engine="drivers", invariants=("components_reconcile",)),
             _o("overlay", "Overlay and management adjustment",
                mandatory=False)],
            triggers=("ecl", "expected credit loss", "impairment", "provision"),
            grains=("portfolio", "segment", "borrower")),

    _simple("bp-ecl-decomposition", ECL_DECOMPOSITION,
            "ECL change decomposition",
            "The ECL movement attributed to exposure, mix, stage, PD, LGD and "
            "model effects, order-neutrally and reconciling to the total.",
            [_o("total", "The total change over the window",
                concepts=("expected credit loss",)),
             _o("decompose", "The change attributed to its drivers",
                engine="ecl_change_decomposition",
                invariants=("components_reconcile", "order_neutral")),
             _o("reconcile", "Reconciliation of components to the total",
                invariants=("components_reconcile",))],
            [_o("sectors", "Sector contributors, ranked", mandatory=False,
                engine="drivers"),
             _o("customers", "Customer contributors, ranked", mandatory=False,
                engine="drivers"),
             _o("interpretation", "What drove the movement", mandatory=False)],
            triggers=("decompose", "attribute", "bridge", "what drove",
                      "break down the change"),
            officer=3, minimum_evidence=8),

    _simple("bp-stage-migration", STAGE_MIGRATION, "Stage migration",
            "Movement between IFRS 9 stages on a matched population.",
            [_o("matrix", "The from-stage by to-stage matrix",
                concepts=("ifrs 9 stage",), datasets=("ifrs9_staging",),
                invariants=("population_matched_both_dates",
                            "transitions_sum")),
             _o("exposure", "The exposure behind each transition",
                concepts=("exposure at default",))],
            [_o("sicr", "What triggered the SICR", mandatory=False),
             _o("cures", "Cures back to Stage 1", mandatory=False),
             _o("drivers", "Which entities moved", mandatory=False,
                engine="drivers")],
            triggers=("stage migration", "moved to stage", "sicr",
                      "stage transition")),

    _simple("bp-rating-migration", RATING_MIGRATION, "Rating migration",
            "Movement between internal grades, ordinal and directional.",
            [_o("matrix", "The from-grade by to-grade matrix",
                concepts=("internal rating",),
                datasets=("customer_ratings", "rating_transitions"),
                invariants=("ordinal_direction",
                            "population_matched_both_dates")),
             _o("direction", "Upgrades and downgrades, counted separately")],
            [_o("notches", "Average notch movement", mandatory=False),
             _o("watch", "Movement into watch grade", mandatory=False),
             _o("exposure", "Exposure behind the movement", mandatory=False,
                concepts=("exposure at default",))],
            triggers=("rating migration", "downgrade", "upgrade", "notch")),

    _simple("bp-dpd-migration", DPD_MIGRATION, "Delinquency migration",
            "Movement between DPD buckets, with deterioration and cure kept "
            "apart.",
            [_o("matrix", "Bucket-to-bucket movement",
                concepts=("days past due",),
                datasets=("facility_delinquency",),
                invariants=("bucket_order", "flows_reconcile_to_opening")),
             _o("direction", "Deterioration and cure, separately")],
            [_o("roll_rates", "Roll rates over the opening population",
                mandatory=False,
                invariants=("denominator_is_opening_population",)),
             _o("collections", "Collections activity", mandatory=False,
                datasets=("payment_history",))],
            triggers=("dpd", "delinquen", "arrears", "past due", "roll rate"),
            scope=BOTH),

    _simple("bp-concentration", CONCENTRATION, "Concentration",
            "How concentrated the book is, by a governed measure rather than "
            "by whichever top-N is on screen.",
            [_o("measure", "The governed concentration measure",
                concepts=("exposure at default",), engine="concentration"),
             _o("distribution", "The distribution it is computed over",
                invariants=("distribution_complete",))],
            [_o("largest", "The largest exposures", mandatory=False),
             _o("groups", "Concentration after group aggregation",
                mandatory=False, datasets=("group_structure",),
                invariants=("no_double_counting",)),
             _o("trend", "How concentration has moved", mandatory=False,
                engine="persistence")],
            triggers=("concentration", "herfindahl", "largest exposures",
                      "top twenty")),

    _simple("bp-early-warning", EARLY_WARNING, "Early warning",
            "Borrowers whose signals are turning before a stage or rating "
            "has moved.",
            [_o("signals", "Which signals have moved",
                concepts=("limit utilisation", "days past due",
                          "covenant headroom"),
                datasets=("portfolio_facility", "facility_delinquency")),
             _o("unmoved", "That stage and rating have not yet moved",
                concepts=("ifrs 9 stage", "internal rating")),
             _o("confirm", "What evidence would confirm the deterioration")],
            [_o("watchlist", "Whether they are already on the watchlist",
                mandatory=False, datasets=("watchlist_register",)),
             _o("financials", "Financial-ratio direction", mandatory=False,
                datasets=("borrower_financials",))],
            triggers=("early warning", "before it", "leading indicator",
                      "watch for")),

    _simple("bp-covenant-collateral", COVENANT_COLLATERAL,
            "Covenant and collateral deterioration",
            "Headroom, breach, coverage and shortfall, each with the "
            "direction it actually has.",
            [_o("headroom", "Covenant headroom and its direction",
                concepts=("covenant headroom",), datasets=("covenant_tests",),
                invariants=("direction_of_deterioration",)),
             _o("breaches", "Who is in breach and by how much",
                invariants=("breach_flag_matches_test",))],
            [_o("collateral", "Collateral coverage and shortfall",
                mandatory=False, datasets=("collateral_register",)),
             _o("trend", "How the position has moved", mandatory=False,
                engine="persistence")],
            scope=CORPORATE, grains=("borrower", "obligor"),
            triggers=("covenant", "headroom", "collateral", "ltv",
                      "security")),

    _simple("bp-financial-deterioration", FINANCIAL_DETERIORATION,
            "Financial deterioration",
            "Leverage, coverage, liquidity and margin combined without "
            "averaging away the direction.",
            [_o("ratios", "Which ratios moved, and which way",
                concepts=("net leverage", "debt service coverage ratio"),
                datasets=("borrower_financials",),
                invariants=("direction_of_deterioration",)),
             _o("intersection", "Borrowers where several moved together",
                invariants=("condition",))],
            [_o("magnitude", "How far each moved", mandatory=False),
             _o("rating", "Whether the rating has followed", mandatory=False,
                concepts=("internal rating",))],
            scope=CORPORATE, grains=("borrower", "obligor"),
            triggers=("leverage", "dscr", "interest cover", "ebitda",
                      "financial deterioration")),

    _simple("bp-contradictory", CONTRADICTORY, "Contradictory signals",
            "Two signals pointing opposite ways, surfaced rather than "
            "resolved.",
            [_o("both", "Both movements, stated"),
             _o("candidates", "What could reconcile them",
                engine="contradiction"),
             _o("evidence", "What would distinguish between the "
                            "explanations")],
            [_o("population", "Whether the population changed",
                mandatory=False, engine="population_effect"),
             _o("overlay", "Whether an overlay moved it", mandatory=False),
             _o("denominator", "Whether a denominator changed",
                mandatory=False)],
            officer=3, minimum_evidence=4,
            triggers=("while", "but", "at the same time", "contradict",
                      "does not add up", "inconsistent")),

    _simple("bp-risk-appetite", RISK_APPETITE, "Risk appetite",
            "A measured position against a stated limit, with the headroom or "
            "the breach.",
            [_o("position", "The measured position",
                concepts=("exposure at default",)),
             _o("limit", "The stated limit",
                datasets=("risk_appetite_limits",),
                invariants=("limit_stated",)),
             _o("headroom", "The headroom or the size of the breach",
                invariants=("headroom_signed",))],
            [_o("trend", "The direction of travel", mandatory=False,
                engine="persistence"),
             _o("drivers", "What is consuming the headroom", mandatory=False,
                engine="drivers")],
            triggers=("appetite", "limit", "tolerance", "within", "breach")),

    _simple("bp-stress", STRESS, "Stress and scenario",
            "Scenario-specific figures kept distinct from the reported "
            "probability-weighted ones.",
            [_o("scenario", "The figure under the named scenario",
                datasets=("scenario_definitions",),
                invariants=("scenario_named",)),
             _o("reported", "The reported probability-weighted figure",
                concepts=("expected credit loss",)),
             _o("difference", "The difference between them")],
            [_o("weights", "The scenario weights in force", mandatory=False,
                invariants=("weights_sum_to_one",)),
             _o("drivers", "What the scenario moves most", mandatory=False,
                engine="drivers")],
            triggers=("stress", "scenario", "downside", "what if", "shock")),

    _simple("bp-vintage", VINTAGE, "Vintage and cohort",
            "A cohort fixed at origination and followed, not re-formed each "
            "period.",
            [_o("cohort", "The cohort, fixed at origination",
                invariants=("cohort_membership_fixed",)),
             _o("development", "How the measure develops by months on book",
                invariants=("survivorship_reported",))],
            [_o("compare", "Comparison with other vintages", mandatory=False),
             _o("survivors", "How many remain on book", mandatory=False)],
            scope=BOTH, grains=("cohort", "vintage"),
            triggers=("vintage", "cohort", "originated in", "months on book",
                      "seasoning")),

    _simple("bp-data-quality", DATA_QUALITY,
            "Data quality and relationship investigation",
            "Whether the data can answer the question, and what it cannot.",
            [_o("coverage", "What the datasets cover and how completely"),
             _o("relationships", "Whether the declared relationships hold",
                invariants=("join_integrity",))],
            [_o("drift", "Whether anything changed between periods",
                mandatory=False),
             _o("nulls", "Where values are missing", mandatory=False),
             _o("duplicates", "Whether a join multiplied rows",
                mandatory=False, invariants=("no_double_counting",))],
            officer=2, route="B_ROUTINE",
            triggers=("data quality", "missing", "does the data",
                      "how complete", "why don't we have")),

    _simple("bp-model-performance", MODEL_PERFORMANCE,
            "Model and method performance review",
            "Whether a model or method is still doing what it was certified "
            "to do.",
            [_o("outcome", "Predicted against observed",
                datasets=("pd_model_performance",)),
             _o("stability", "Whether performance has moved",
                engine="persistence")],
            [_o("segments", "Where it performs worst", mandatory=False),
             _o("recalibration", "Whether recalibration is indicated",
                mandatory=False)],
            officer=3,
            triggers=("model performance", "backtest", "calibration",
                      "is the model")),

    _simple("bp-demo-executive", DEMO_EXECUTIVE,
            "Client-demo executive portfolio review",
            "The portfolio review shown to a room, where every claim has to "
            "hold and an unproven one costs more than a missing one.",
            [_o("position", "Where the book stands",
                concepts=("exposure at default",)),
             _o("movement", "What moved and by how much",
                engine="drivers", invariants=("components_reconcile",)),
             _o("attention", "What needs attention", engine="materiality"),
             _o("assurance", "What was checked and what was not")],
            [_o("concentration", "Concentration", mandatory=False,
                engine="concentration"),
             _o("appetite", "Position against appetite", mandatory=False)],
            officer=4, minimum_evidence=8,
            when="Demo Safe Mode, where an unproven claim is more expensive "
                 "than a missing one.",
            when_not="Ordinary internal use — the stricter evidence floor "
                     "makes the answer slower and no more correct."),

    # ---------------------------------------- the corporate relationship graph
    #
    # Every one of these carries a `when_not_to_use` that names the blueprint
    # a reader is likely to reach for instead. That clause is the load-bearing
    # half: "the group" means three different sets of companies, and a
    # blueprint that answers the wrong one answers confidently.

    _simple("bp-group-structure", GROUP_STRUCTURE,
            "Corporate group structure",
            "Who owns and who controls a borrower, and how the two differ.",
            [_o("ownership", "Integrated ownership through the chain",
                concepts=("effective ownership",),
                datasets=("corporate_ownership_edges",
                          "corporate_connected_groups"),
                engine="ownership_and_control_structure",
                invariants=("register_sums_within_bounds",)),
             _o("control", "Who can direct decisions, over VOTING rights",
                concepts=("control group",),
                datasets=("corporate_connected_groups",)),
             _o("difference", "Where control and economics disagree, and why",
                invariants=("control_is_not_ownership",))],
            [_o("chains", "The ownership chains, with each step",
                mandatory=False, datasets=("corporate_ownership_edges",)),
             _o("confidence", "How well evidenced the structure is",
                mandatory=False, concepts=("graph confidence",))],
            grains=("borrower", "obligor"), scope=CORPORATE, officer=3,
            triggers=("group structure", "who owns", "who controls",
                      "ownership chain", "parent company"),
            hypotheses=("The control group and the ownership group differ "
                        "because an intermediate holding company votes more "
                        "than it economically owns.",),
            challenges=("Is the difference between control and economics real, "
                        "or an artefact of a shareholder register that does "
                        "not sum?",),
            when="A question about how a borrower sits inside a corporate "
                 "structure.",
            when_not="A question about the bank's exposure to that structure "
                     "— that is the group limit blueprint. This one is about "
                     "the structure, not the money."),

    _simple("bp-beneficial-ownership", BENEFICIAL_OWNERSHIP,
            "Ultimate beneficial ownership",
            "The natural persons behind a borrower, found through the chain "
            "rather than from direct shareholdings.",
            [_o("ubo", "Natural persons at or above the 25% threshold",
                concepts=("ultimate beneficial owner",),
                datasets=("corporate_connected_groups",),
                engine="ownership_and_control_structure"),
             _o("path", "The chain that reaches each of them",
                datasets=("corporate_ownership_edges",)),
             _o("evidence", "The weakest assertion on each path",
                concepts=("graph confidence",),
                invariants=("weakest_evidence_reported",))],
            [_o("blocked", "Borrowers whose ownership was refused, and why",
                mandatory=False, datasets=("corporate_graph_dq",)),
             _o("shared", "Owners shared with other borrowers",
                mandatory=False)],
            grains=("borrower", "obligor"), scope=CORPORATE, officer=3,
            triggers=("beneficial owner", "ubo", "who really owns",
                      "ultimate owner", "natural person"),
            hypotheses=("A borrower with no identified beneficial owner has a "
                        "chain that terminates in a company rather than a "
                        "person, not an absence of owners.",),
            challenges=("Is 'no beneficial owner' a finding about the "
                        "borrower, or a data-quality refusal reported as "
                        "one?",),
            validations=("blocked_is_not_absent",),
            when="A KYC or beneficial-ownership question about one borrower "
                 "or a cohort.",
            when_not="A question about control. A 30% holder facing a "
                     "dispersed register may control without reaching the "
                     "beneficial-ownership threshold."),

    _simple("bp-connected-counterparty", CONNECTED_COUNTERPARTY,
            "Connected counterparty assessment",
            "Which borrowers should be assessed as one obligor, on what "
            "basis, and what the evidence for each member is.",
            [_o("candidates", "The candidate group and its members",
                concepts=("connected counterparty group",),
                datasets=("corporate_connected_groups",),
                engine="connected_group_exposure"),
             _o("criterion", "Why each member is in it — control or "
                "validated interdependence",
                invariants=("every_member_has_a_criterion",)),
             _o("caveat", "That this is a candidate, not a determination",
                invariants=("candidate_not_determination",))],
            [_o("interdependence", "The economic predicates that were tested",
                mandatory=False),
             _o("percolation", "Whether the grouping has collapsed into one "
                "giant component", mandatory=False)],
            grains=("borrower", "obligor"), scope=CORPORATE, officer=4,
            triggers=("connected counterparty", "obligor group",
                      "single risk", "group of connected clients"),
            hypotheses=("A group that grew unusually large this quarter did "
                        "so through one new control edge rather than through "
                        "many.",),
            challenges=("Would this group survive being built from raw "
                        "shareholdings instead of control? If so it is not a "
                        "group, it is a common investor.",),
            validations=("candidate_not_determination",),
            when="Assessing whether borrowers form one obligor for limit or "
                 "regulatory purposes.",
            when_not="Reporting a limit position — that is the group limit "
                     "blueprint. Graph connectivity is not regulatory "
                     "connectedness and this blueprint produces candidates."),

    _simple("bp-group-limit", GROUP_LIMIT, "Group limit utilisation",
            "What the bank is exposed to at the group level, and where that "
            "sits against the limit.",
            [_o("exposure", "Group exposure and its members' shares",
                concepts=("connected group exposure",),
                datasets=("corporate_connected_groups",),
                engine="connected_group_exposure"),
             _o("utilisation", "Position against the group limit",
                concepts=("group limit utilisation",),
                invariants=("group_at_least_single_name",)),
             _o("parameter", "That the threshold is unverified",
                invariants=("unverified_parameter_declared",))],
            [_o("single_name", "How the group compares with its largest "
                "single name", mandatory=False),
             _o("movement", "How the group's utilisation has moved",
                mandatory=False, engine="persistence")],
            grains=("obligor", "portfolio"), scope=CORPORATE, officer=4,
            triggers=("group limit", "large exposure", "group utilisation",
                      "group concentration", "in breach"),
            hypotheses=("A group crossing the trigger did so through one "
                        "member's growth rather than through a change in the "
                        "group's membership.",),
            challenges=("Did the group's exposure move, or did its "
                        "membership? A group that gained a member did not "
                        "gain risk.",),
            validations=("unverified_parameter_declared",),
            when="A limit, large-exposure or concentration question at group "
                 "level.",
            when_not="Single-name concentration — the credit book answers "
                     "that, and it answers it about facilities."),

    _simple("bp-network-contagion", NETWORK_CONTAGION,
            "Network contagion",
            "What would travel through the network if a borrower failed, and "
            "how far.",
            [_o("impact", "DebtRank impact from the borrower as seed",
                concepts=("DebtRank impact",),
                datasets=("corporate_connected_groups",),
                engine="network_risk_ranking"),
             _o("paths", "The exposures and guarantees it would travel",
                datasets=("corporate_exposure_network",
                          "corporate_guarantees")),
             _o("caveat", "That DebtRank is not an ECL or a capital measure",
                invariants=("not_a_credit_measure",))],
            [_o("neighbours", "Who is most affected", mandatory=False),
             _o("unmeasured", "Borrowers with no network measurement",
                mandatory=False)],
            grains=("borrower", "portfolio"), scope=CORPORATE, officer=4,
            triggers=("contagion", "debtrank", "if they failed",
                      "knock-on", "systemic"),
            hypotheses=("A borrower with high impact and low exposure "
                        "transmits through guarantees rather than through "
                        "direct claims.",),
            challenges=("Is the impact concentrated in one neighbour, in "
                        "which case it is a single-name question wearing a "
                        "network's clothes?",),
            validations=("not_a_credit_measure",),
            when="A question about what a failure would spread to.",
            when_not="A question about the size of a loss. DebtRank is a "
                     "propagation measure and is not an expected credit "
                     "loss."),

    _simple("bp-network-centrality", NETWORK_CENTRALITY,
            "Network position",
            "Where a borrower sits in the relationship network: who "
            "transmits, who is exposed, who is a conduit.",
            [_o("score", "Network Risk Score and its three components",
                concepts=("network risk score",),
                datasets=("corporate_connected_groups",),
                engine="network_risk_ranking"),
             _o("direction", "Transmitter against exposed — forward and "
                "reverse are different questions",
                concepts=("network centrality",),
                invariants=("direction_is_stated",)),
             _o("caveat", "That the score is a ranking, not a probability",
                invariants=("ranking_not_probability",))],
            [_o("community", "The network community it sits in",
                mandatory=False, concepts=("network community",)),
             _o("conduit", "Whether it is on the only path between others",
                mandatory=False)],
            grains=("borrower", "portfolio"), scope=CORPORATE, officer=3,
            triggers=("most central", "network position", "pagerank",
                      "betweenness", "network risk score"),
            hypotheses=("A borrower high on betweenness and low on PageRank "
                        "is a bridge between two clusters rather than a large "
                        "counterparty.",),
            challenges=("Is a high score driven by one component? The "
                        "composite hides a borrower that is extreme on one "
                        "measure and unremarkable on the others.",),
            validations=("ranking_not_probability",),
            when="A question about a borrower's structural position.",
            when_not="A question about its credit quality. The score is a "
                     "relative ranking in this population and is not a PD, a "
                     "rating or a stage."),

    _simple("bp-supply-chain", SUPPLY_CHAIN, "Supply chain dependence",
            "Who a borrower depends on and who depends on it, and whether "
            "that dependence is material.",
            [_o("suppliers", "Upstream counterparties and revenue shares",
                concepts=("suppliers",),
                datasets=("corporate_supply_chain",)),
             _o("customers", "Downstream counterparties and COGS shares",
                concepts=("customers of the borrower",),
                datasets=("corporate_supply_chain",)),
             _o("boundary", "That a supply relationship forms no regulatory "
                "group on its own",
                invariants=("supply_is_not_a_group",))],
            [_o("concentration", "Whether one counterparty dominates",
                mandatory=False),
             _o("substitutability", "Whether the output can be sourced "
                "elsewhere", mandatory=False)],
            grains=("borrower",), scope=CORPORATE, officer=2,
            triggers=("supply chain", "suppliers", "buyers", "upstream",
                      "downstream", "dependence"),
            hypotheses=("A borrower with one dominant buyer carries that "
                        "buyer's credit risk whether or not the two are "
                        "connected.",),
            challenges=("Does the dependence clear the interdependence "
                        "threshold, or is it a commercial fact with no "
                        "grouping consequence?",),
            validations=("supply_is_not_a_group",),
            when="A question about commercial dependence between borrowers.",
            when_not="A connectedness assessment. A supply relationship is "
                     "one input to the interdependence test and never forms "
                     "a group by itself."),

    _simple("bp-guarantee-network", GUARANTEE_NETWORK, "Guarantee network",
            "Who stands behind whose obligations, and whether the guarantor "
            "could.",
            [_o("given", "Guarantees this borrower has given",
                concepts=("guarantee links",),
                datasets=("corporate_guarantees",)),
             _o("received", "Guarantees it benefits from",
                datasets=("corporate_guarantees",)),
             _o("guarantor", "The guarantor's own position",
                datasets=("corporate_borrower_360",))],
            [_o("joint", "Joint and several arrangements", mandatory=False),
             _o("correlation", "Whether guarantor and borrower fail together",
                mandatory=False)],
            grains=("borrower", "obligor"), scope=CORPORATE, officer=3,
            triggers=("guarantee", "guarantor", "stands behind", "surety",
                      "cross guarantee"),
            hypotheses=("A guarantee from within the borrower's own group "
                        "transfers less risk than one from outside it, "
                        "because the two fail together.",),
            challenges=("Is the guarantor's own exposure large enough that "
                        "the guarantee is worth less than its face value?",),
            when="A question about credit support between counterparties.",
            when_not="A collateral question — collateral is an asset and a "
                     "guarantee is a counterparty."),

    _simple("bp-hidden-relationship", HIDDEN_RELATIONSHIP,
            "Hidden relationship discovery",
            "Borrowers that share enough evidence to be worth a second look, "
            "and nothing more than that.",
            [_o("candidates", "Pairs above the similarity threshold",
                datasets=("corporate_ownership_edges",)),
             _o("evidence", "What exactly is shared",
                invariants=("shared_evidence_listed",)),
             _o("boundary", "That a candidate establishes nothing",
                invariants=("creates_no_relationship",))],
            [_o("threshold", "That the threshold is unvalidated",
                mandatory=False),
             _o("followup", "What a human would check next",
                mandatory=False)],
            grains=("borrower", "portfolio"), scope=CORPORATE, officer=3,
            triggers=("hidden relationship", "shared director",
                      "same address", "undisclosed", "similar borrowers"),
            hypotheses=("Two borrowers sharing a director and an address are "
                        "more likely to share a controller than two sharing "
                        "only an address.",),
            challenges=("Is the shared evidence a serviced office or a "
                        "nominee director, which thousands share and which "
                        "identifies nobody?",),
            validations=("creates_no_relationship",),
            when="Looking for relationships nobody has declared.",
            when_not="Establishing a relationship. A candidate creates no "
                     "control, no beneficial ownership and no group "
                     "membership, and may not be used as though it did."),

    _simple("bp-graph-quality", GRAPH_QUALITY, "Graph data quality review",
            "Whether the relationship graph can be trusted this quarter, and "
            "which derived figures a refusal blocked.",
            [_o("checks", "Every check and what it observed",
                concepts=("data quality check verdict",),
                datasets=("corporate_graph_dq",),
                engine="graph_data_quality"),
             _o("blocked", "Which computations a REJECT stopped",
                invariants=("reject_names_what_it_blocked",)),
             _o("affected", "Which borrowers carry a blocked field",
                datasets=("corporate_connected_groups",))],
            [_o("trend", "Whether quality has moved since the prior quarter",
                mandatory=False, engine="persistence"),
             _o("confidence", "How much of the graph rests on weak evidence",
                mandatory=False, concepts=("graph evidence confidence",))],
            grains=("portfolio",), scope=CORPORATE, officer=3,
            triggers=("graph quality", "can we trust", "data quality check",
                      "which figures were blocked"),
            hypotheses=("A quarter with more rejections has a source-system "
                        "change behind it rather than a change in the "
                        "borrowers.",),
            challenges=("Does a PASS mean the data is right, or only that "
                        "this check found nothing it tests for?",),
            when="Before relying on a derived graph figure, or when one "
                 "reads DATA_QUALITY_BLOCKED.",
            when_not="A general data-quality question about the credit book "
                     "— that is a different register and different checks."),
)

BY_ID: dict[str, Blueprint] = {b.blueprint_id: b for b in LIBRARY}
BY_FAMILY: dict[str, Blueprint] = {b.family: b for b in LIBRARY}


def get(blueprint_id: str) -> Blueprint | None:
    return BY_ID.get(str(blueprint_id or ""))


def for_family(family: str) -> Blueprint | None:
    return BY_FAMILY.get(str(family or ""))


def usable() -> list[Blueprint]:
    """§66: only approved or system-validated blueprints reach production."""
    return [b for b in LIBRARY if b.usable]


# ---------------------------------------------------------------------------
# §69 — selection
# ---------------------------------------------------------------------------

#: The twelve signals §69 lists, and what each is worth. Triggers are ONE of
#: twelve on purpose: "Do not choose solely from keywords."
SELECTION_WEIGHTS: dict[str, float] = {
    "triggers": 2.5,
    "capability": 1.5,
    "subject": 2.0,
    "objectives": 2.0,
    "scope": 1.5,
    "grain": 1.5,
    "period": 1.0,
    "concepts": 3.0,
    "data_available": 2.0,
    "breadth": 2.0,
    "materiality": 1.0,
    "officer": 1.0,
}

#: Below this a "best match" is a shrug. Reported as such rather than chosen,
#: because a blueprint applied to a question it does not fit runs sixteen
#: analyses nobody asked for and calls the result an investigation.
CONFIDENT_AT = 0.35


@dataclass
class Selection:
    """§69's persisted record."""

    selected_blueprint_id: str = ""
    version: int = 0
    selection_score: float = 0.0
    selection_reasons: list[str] = field(default_factory=list)
    required_objectives: list[str] = field(default_factory=list)
    optional_objectives: list[str] = field(default_factory=list)
    omitted_objectives: list[str] = field(default_factory=list)
    omission_reasons: dict[str, str] = field(default_factory=dict)
    custom_additions: list[str] = field(default_factory=list)
    #: Every candidate and what it scored, so a reader can see the second
    #: choice. A selection that shows only its winner cannot be argued with.
    considered: list[dict[str, Any]] = field(default_factory=list)
    confident: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_blueprint_id": self.selected_blueprint_id,
            "version": self.version,
            "selection_score": round(self.selection_score, 4),
            "selection_reasons": list(self.selection_reasons),
            "required_objectives": list(self.required_objectives),
            "optional_objectives": list(self.optional_objectives),
            "omitted_objectives": list(self.omitted_objectives),
            "omission_reasons": dict(self.omission_reasons),
            "custom_additions": list(self.custom_additions),
            "considered": list(self.considered),
            "confident": self.confident,
        }


@dataclass(frozen=True)
class Request:
    """What is known about the question, for selection to read."""

    question: str = ""
    capability: str = ""
    #: portfolio | segment | sector | borrower | facility | dataset | method
    subject: str = ""
    objectives: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    datasets_available: tuple[str, ...] = ()
    scope: str = NO_SCOPE
    grain: str = ""
    periods: int = 1
    broad: bool = False
    high_materiality: bool = False
    officer_level: int = 0


def _overlap(held: list[str] | tuple[str, ...],
             wanted: tuple[str, ...]) -> float:
    if not wanted:
        return 0.0
    have = {str(x).lower() for x in held}
    return len({w for w in wanted if str(w).lower() in have}) / len(wanted)


#: The signals that actually discriminate between blueprints. Data
#: availability, officer level and scope are CONSTRAINTS — they rule a
#: blueprint out, they do not argue for it — and a selection made on
#: constraints alone has been made on nothing.
DISCRIMINATING: frozenset[str] = frozenset({"triggers", "subject",
                                            "concepts", "objectives"})

#: Total matched trigger length at which the trigger signal saturates. Twelve
#: characters is roughly one specific phrase or two generic ones.
TRIGGER_SPECIFICITY = 12.0

#: What a score is multiplied by when no discriminating signal fired. Not
#: zero: the blueprint may still be the right one, and a caller needs a
#: ranking rather than a wall of zeroes. Low enough that it can never be
#: confident.
UNDISCRIMINATED = 0.35


def score(blueprint: Blueprint, request: Request) -> tuple[float, list[str]]:
    """How well one blueprint fits, and why.

    A signal the request says nothing about is NOT SCORED rather than scored
    as a match. That distinction is the difference between a selector and a
    coin: with generous defaults for absent information, a nonsense question
    scored 0.52 against every blueprint in the library and the top one was
    whichever happened to sort first.
    """
    parts: dict[str, float] = {}
    reasons: list[str] = []
    text = " ".join((request.question or "").lower().split())

    if text:
        hits = [t for t in blueprint.trigger_patterns
                if t and re.search(re.escape(t), text)]
        # Scored by how SPECIFIC the matched phrases are, not how many there
        # are. "decompose" is a claim about what the question wants;
        # "ecl" is a claim that it mentions a measure, and counting them
        # equally made "Decompose the ECL change" select the ECL movement
        # blueprint over the decomposition one by a hundredth of a point.
        matched = sum(len(t) for t in hits)
        parts["triggers"] = min(1.0, matched / TRIGGER_SPECIFICITY)
        if hits:
            reasons.append(f"the question uses {', '.join(hits[:3])}")

    if request.capability:
        parts["capability"] = float(
            request.capability == "ANALYSIS"
            or blueprint.family == DATA_QUALITY)

    if request.subject:
        fits = request.subject in blueprint.supported_grains
        parts["subject"] = float(fits)
        if fits:
            reasons.append(f"it works at {request.subject} grain")

    if request.objectives:
        parts["objectives"] = _overlap([o.id for o in blueprint.objectives],
                                       request.objectives)

    if request.concepts:
        parts["concepts"] = _overlap(blueprint.required_concepts,
                                     request.concepts)
        if parts["concepts"] > 0:
            reasons.append(
                f"{parts['concepts']:.0%} of the named concepts are ones it "
                "requires")

    needed = blueprint.required_data_capabilities
    if needed and request.datasets_available:
        parts["data_available"] = _overlap(list(request.datasets_available),
                                           tuple(needed))
        if parts["data_available"] < 1.0:
            reasons.append(
                f"only {parts['data_available']:.0%} of the data it needs is "
                "available")

    if request.scope and request.scope != NO_SCOPE:
        parts["scope"] = (1.0 if blueprint.applicable_scope in (NO_SCOPE, BOTH)
                          else float(blueprint.applicable_scope
                                     == request.scope))

    if request.grain:
        parts["grain"] = float(request.grain in blueprint.supported_grains)

    # Which blueprints are inherently two-period. Read from the objectives
    # rather than declared, so a blueprint that gains a movement objective
    # starts asking for two periods without anybody remembering to say so.
    wants_two = any(
        any(word in o.id or word in (o.engine or "")
            for word in ("movement", "migration", "decompos", "change",
                         "transition"))
        for o in blueprint.required_objectives)
    if wants_two:
        parts["period"] = float(request.periods >= 2)

    if request.broad or len(blueprint.objectives) >= 8:
        parts["breadth"] = float(request.broad == (
            len(blueprint.objectives) >= 8))

    if request.high_materiality:
        parts["materiality"] = float(blueprint.officer_level >= 3)

    if request.officer_level:
        parts["officer"] = float(
            abs(blueprint.officer_level - request.officer_level) <= 1)

    if not parts:
        return 0.0, ["nothing in the request bears on any blueprint"]

    weight = sum(SELECTION_WEIGHTS[k] for k in parts)
    total = sum(SELECTION_WEIGHTS[k] * v for k, v in parts.items()) / weight

    # A blueprint that scores only on constraints has not been argued for.
    if not any(parts.get(name, 0.0) > 0 for name in DISCRIMINATING):
        total *= UNDISCRIMINATED
        reasons.append("nothing in the question points at this blueprint; it "
                       "is compatible rather than indicated")

    return total, reasons


def select(request: Request, *,
           library: tuple[Blueprint, ...] | None = None) -> Selection:
    """Which blueprint answers this, and what it will and will not look at.

    §69's twelve signals, weighted. Triggers are one of them: a question
    mentioning "ECL" is not necessarily an ECL movement investigation — it
    might be a data question, a methodology question, or a concentration
    question that happens to use ECL as its measure.
    """
    candidates = list(library or usable())
    scored: list[tuple[float, Blueprint, list[str]]] = []
    for blueprint in candidates:
        value, reasons = score(blueprint, request)
        scored.append((value, blueprint, reasons))
    scored.sort(key=lambda row: (-row[0], row[1].blueprint_id))

    selection = Selection(considered=[
        {"blueprint_id": b.blueprint_id, "family": b.family,
         "score": round(v, 4)} for v, b, _ in scored[:6]])

    if not scored:
        selection.selection_reasons.append("no blueprint is available")
        return selection

    best, blueprint, reasons = scored[0]
    selection.selected_blueprint_id = blueprint.blueprint_id
    selection.version = blueprint.version
    selection.selection_score = best
    selection.confident = best >= CONFIDENT_AT
    selection.selection_reasons = reasons or [
        "no signal was strong; this is the closest of the available "
        "blueprints"]
    if not selection.confident:
        selection.selection_reasons.insert(
            0, f"the best match scores {best:.0%}, below the {CONFIDENT_AT:.0%} "
               "threshold — treat the objective list as a starting point "
               "rather than a fit")

    selection.required_objectives = [o.id
                                     for o in blueprint.required_objectives]

    # §68's rule. An optional objective whose data is unavailable is omitted
    # WITH a reason; one whose data is present stays. A mandatory objective is
    # never omitted — if its data is missing the investigation is incomplete,
    # which is a different and more honest outcome than a shorter one.
    available = {d.lower() for d in request.datasets_available}
    for objective in blueprint.optional_objectives:
        needed = {d.lower() for d in objective.datasets}
        if needed and available and not (needed <= available):
            selection.omitted_objectives.append(objective.id)
            selection.omission_reasons[objective.id] = (
                f"{', '.join(sorted(needed - available))} is not available")
        else:
            selection.optional_objectives.append(objective.id)

    return selection


def incomplete(blueprint: Blueprint, request: Request) -> list[str]:
    """Mandatory objectives whose data is not available.

    Returned rather than omitted. §68 permits omitting an OPTIONAL branch; a
    mandatory one whose data is missing makes the investigation incomplete,
    and saying so is the whole difference between an honest short answer and a
    confident one.
    """
    available = {d.lower() for d in request.datasets_available}
    if not available:
        return []
    blocked: list[str] = []
    for objective in blueprint.required_objectives:
        needed = {d.lower() for d in objective.datasets}
        if needed and not (needed <= available):
            blocked.append(objective.id)
    return blocked


__all__ = ["APPROVED", "BLUEPRINT_VERSION", "BOTH", "BY_FAMILY", "BY_ID",
           "DISCRIMINATING", "TRIGGER_SPECIFICITY", "UNDISCRIMINATED",
           "Blueprint", "CONFIDENT_AT", "CORPORATE", "DEFAULT_STOPPING_RULES",
           "DRAFT", "FAMILIES", "FINGERPRINTED", "LIBRARY", "NO_SCOPE",
           "Objective", "REJECTED", "RETAIL", "RETIRED", "Request",
           "SCOPES", "SEGMENT_BLUEPRINT", "SELECTION_WEIGHTS",
           "SME_REVIEW_REQUIRED", "STALE", "STATUSES", "SYSTEM_VALIDATED",
           "Selection", "USABLE", "UNIVERSAL_VALIDATIONS", "fingerprint",
           "for_family", "get", "incomplete", "score", "select", "usable",
           "PORTFOLIO_HEALTH", "SEGMENT_DETERIORATION", "BORROWER_DEEP_DIVE",
           "ECL_MOVEMENT", "ECL_DECOMPOSITION", "STAGE_MIGRATION",
           "RATING_MIGRATION", "DPD_MIGRATION", "CONCENTRATION",
           "EARLY_WARNING", "COVENANT_COLLATERAL", "FINANCIAL_DETERIORATION",
           "CONTRADICTORY", "RISK_APPETITE", "STRESS", "VINTAGE",
           "DATA_QUALITY", "MODEL_PERFORMANCE", "DEMO_EXECUTIVE"]
