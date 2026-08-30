"""
The forty-five case families a teaching library has to cover. §7.

Why a family is a governed object rather than a string
------------------------------------------------------
A free-text family label makes coverage unmeasurable. If one author writes
"ECL movement" and another writes "ecl_movement", the library reports two
families with one case each instead of one family with two, and the gap that
matters — the family with *no* cases — is invisible underneath the noise.

So a family is declared here, once, with the thing a case in it has to
demonstrate. The library counts against this list, §13 reports quality by
family against this list, and a case naming a family that is not here does not
validate.

What each family carries beyond its name
----------------------------------------
Three of the fields are enforced by the schema rather than documentation, and
they exist because each encodes a way a case can look right and teach nothing:

``turns``      A MULTI_TURN_REFERENTS case with one turn has no referent to
               resolve. It would still parse.
``discourse``  A SAME_TURN_COREFERENCE case with no local antecedent recorded
               is an ordinary filter question wearing the family's name.
``scope``      A CORPORATE_SCOPE case scoped to NONE teaches nothing about
               corporate lending.

``outcome`` is the fourth: an AMBIGUITY case whose expected behaviour is to
execute is teaching the opposite of what the family is for.

Two families are gated
----------------------
ARABIC_QUERY and PROJECT_PLANNER_QUERY are named by §7 with conditions —
"when Arabic is implemented", "only after Project Planner exists". They are
declared so the list is complete and so coverage reporting can say *why* they
are empty, and they are marked unavailable so nothing counts a gap against
a capability the product does not yet have.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Moves when a family is added, removed, or changes what it teaches. A case
#: validated against an older list is STALE, not wrong (see ``status.py``).
FAMILY_VERSION = "1.1.0"

# ---------------------------------------------------------------- the groups
# Groups exist for the administrator's eye, not for logic: forty-five rows in
# one flat list is a list nobody reads. Nothing branches on a group.
METADATA = "metadata"
CALCULATION = "calculation"
CONVERSATION = "conversation"
STRUCTURE = "structure"
MIGRATION = "migration"
ECL = "ecl"
PORTFOLIO = "portfolio"
BORROWER = "borrower"
JUDGMENT = "judgment"
REFUSAL = "refusal"
GOVERNANCE = "governance"
SCOPE = "scope"
SCORECARD = "scorecard"

GROUPS: tuple[str, ...] = (
    METADATA, CALCULATION, CONVERSATION, STRUCTURE, MIGRATION, ECL,
    PORTFOLIO, BORROWER, JUDGMENT, REFUSAL, GOVERNANCE, SCOPE, SCORECARD,
)

# ------------------------------------------------------------- the outcomes
# What a correct answer does at all, before any question of whether it does it
# well. A case declares one; a family may require one.
EXECUTE = "EXECUTE"
CLARIFY = "CLARIFY"
UNSUPPORTED = "UNSUPPORTED"
FAIL = "FAIL"

OUTCOMES: tuple[str, ...] = (EXECUTE, CLARIFY, UNSUPPORTED, FAIL)

# ---------------------------------------------------------- portfolio scope
CORPORATE = "CORPORATE"
RETAIL = "RETAIL"
NO_SCOPE = "NONE"

PORTFOLIO_SCOPES: tuple[str, ...] = (CORPORATE, RETAIL, NO_SCOPE)


@dataclass(frozen=True)
class Family:
    """One family, and what a case in it must demonstrate."""

    id: str
    label: str
    group: str
    #: The sentence a reviewer reads before deciding whether a case belongs
    #: here. Written as an obligation on the case, not a description of the
    #: topic, because "about ECL" admits everything and "must reconcile the
    #: decomposition back to the total" admits one thing.
    teaches: str
    #: Minimum turns. Two means the family is about what the second turn does
    #: with the first.
    turns: int = 1
    #: The family requires a recorded same-turn antecedent (§10).
    discourse: bool = False
    #: The outcome every case in the family must declare, or "" for any.
    outcome: str = ""
    #: The portfolio scope every case must declare, or "" for any.
    scope: str = ""
    #: Empty when the family is live. Otherwise the capability it waits on:
    #: coverage reports the family as deferred rather than as a gap.
    gated_on: str = ""

    @property
    def available(self) -> bool:
        return not self.gated_on


FAMILIES: tuple[Family, ...] = (
    # ------------------------------------------------------------ metadata
    Family("DATA_DISCOVERY", "Data discovery", METADATA,
           "Answer what data exists without computing over it.",
           outcome=EXECUTE),
    Family("DATA_DICTIONARY", "Data dictionary", METADATA,
           "Define a field or a concept in the governed vocabulary, and "
           "resist the pull to analyse it instead."),
    Family("DATA_RELATIONSHIPS", "Data relationships", METADATA,
           "Explain how two governed datasets join, including the grain the "
           "join produces."),
    Family("DATA_INSPECTION", "Data inspection", METADATA,
           "Report the shape, coverage or quality of held data — row counts, "
           "history depth, missingness — as a fact about the data."),

    # --------------------------------------------------------- calculation
    Family("SINGLE_DOMAIN_AGGREGATION", "Single-domain aggregation",
           CALCULATION,
           "Aggregate one governed measure over one dimension in one period, "
           "with the aggregation the concept permits."),
    Family("FILTERING_AND_RANKING", "Filtering and ranking", CALCULATION,
           "Separate a threshold from a movement and a filter from an order, "
           "and honour a stated row limit."),
    Family("COMPOUND_OBJECTIVES", "Compound objectives", CALCULATION,
           "Decompose a sentence carrying more than one objective and answer "
           "every one of them (§11)."),
    Family("COHORT_COMPARISON", "Cohort comparison", CALCULATION,
           "Compare two populations on the same measure and period, and say "
           "which comparison is being made."),

    # -------------------------------------------------------- conversation
    Family("SAME_TURN_COREFERENCE", "Same-turn coreference", CONVERSATION,
           "Resolve a pronoun to a cohort defined earlier in the same "
           "sentence, with no prior turn to lean on (§10).",
           discourse=True),
    Family("MULTI_TURN_REFERENTS", "Multi-turn referents", CONVERSATION,
           "Carry a population, field set or period across turns, and narrow, "
           "widen or reset it as the user asks.",
           turns=2),
    Family("PREVIOUS_RESULT_REUSE", "Previous-result reuse", CONVERSATION,
           "Answer from the result already on screen instead of recomputing "
           "it, and say that is what happened.",
           turns=2),
    Family("PRESENTATION_MODIFICATION", "Presentation modification",
           CONVERSATION,
           "Change how an existing result is shown without changing what was "
           "calculated.",
           turns=2),

    # ------------------------------------------------------------ structure
    Family("PERIOD_ALIGNMENT", "Period alignment", STRUCTURE,
           "Put both sides of a comparison on the same period basis, and "
           "state the basis."),
    Family("AS_OF_JOIN", "As-of join", STRUCTURE,
           "Attach an attribute as it stood at the analysis date rather than "
           "as it stands today."),
    Family("MULTI_DATASET_JOIN", "Multi-dataset join", STRUCTURE,
           "Join across governed domains along a declared relationship, "
           "without inventing a path."),
    Family("GRAIN_RECONCILIATION", "Grain reconciliation", STRUCTURE,
           "Move between facility, borrower and portfolio grain without "
           "double-counting, and prove the total still ties."),

    # ------------------------------------------------------------ migration
    Family("RATING_MIGRATION", "Rating migration", MIGRATION,
           "Read internal grades as ordinal, in the right direction, and "
           "count movement between two dates."),
    Family("STAGE_MIGRATION", "Stage migration", MIGRATION,
           "Count IFRS 9 stage transitions between two dates, keeping "
           "direction and SICR meaning."),
    Family("DPD_MIGRATION", "DPD migration", MIGRATION,
           "Count delinquency-bucket movement, treating buckets as ordered "
           "and cures as a direction rather than an absence."),
    Family("ROLL_RATE_AND_CURE", "Roll rates and cures", MIGRATION,
           "Compute a roll rate as a flow over an opening population, not a "
           "ratio of two closing snapshots."),

    # ------------------------------------------------------------------ ECL
    Family("ECL_MOVEMENT", "ECL movement", ECL,
           "Measure the change in expected credit loss between two dates, "
           "with the population accounted for on both sides."),
    Family("ECL_CHANGE_DECOMPOSITION", "ECL change decomposition", ECL,
           "Attribute an ECL change to exposure, mix, stage, PD, LGD and "
           "model effects, order-neutrally, and reconcile to the total."),
    Family("PD_LGD_EAD_ANALYSIS", "PD, LGD and EAD analysis", ECL,
           "Analyse a risk parameter as a parameter — weighted, bounded, "
           "never summed — and keep 12-month and lifetime apart."),

    # ------------------------------------------------------------ portfolio
    Family("PORTFOLIO_MIX", "Portfolio mix", PORTFOLIO,
           "Separate a change in the mix of a portfolio from a change in the "
           "risk of its parts."),
    Family("CONCENTRATION", "Concentration", PORTFOLIO,
           "Quantify concentration by a governed method, and not by whichever "
           "top-N happens to be on screen."),
    Family("VINTAGE_AND_COHORT", "Vintage and cohort", PORTFOLIO,
           "Hold a cohort fixed at origination and follow it, rather than "
           "re-forming the cohort each period."),
    Family("RISK_APPETITE", "Risk appetite", PORTFOLIO,
           "Compare a measured position against a stated limit and report the "
           "headroom or breach, not the measure alone."),
    Family("STRESS_AND_SCENARIO", "Stress and scenario", PORTFOLIO,
           "Keep scenario-weighted and scenario-specific figures distinct, "
           "and name the scenario behind every number."),

    # ------------------------------------------------------------- borrower
    Family("COVENANT_AND_COLLATERAL", "Covenant and collateral", BORROWER,
           "Read headroom, breach, coverage and shortfall with the direction "
           "of deterioration each one actually has."),
    Family("FINANCIAL_DETERIORATION", "Financial deterioration", BORROWER,
           "Combine leverage, coverage, liquidity and margin into a "
           "deterioration reading without averaging away the direction."),
    Family("EARLY_WARNING", "Early warning", BORROWER,
           "Identify borrowers whose signals are turning before a stage or "
           "rating has moved, and say what would confirm it."),

    # ------------------------------------------------------------- judgment
    Family("BROAD_INVESTIGATION", "Broad investigation", JUDGMENT,
           "Turn an open prompt into a bounded set of governed analyses, and "
           "report what was examined as well as what was found."),
    Family("CONTRADICTORY_SIGNALS", "Contradictory signals", JUDGMENT,
           "Surface signals that point opposite ways instead of resolving "
           "them silently into one direction."),
    Family("ASSOCIATION_NOT_CAUSATION", "Association, not causation", JUDGMENT,
           "State a relationship as association, and name what evidence would "
           "be needed before claiming cause."),
    Family("VISUALIZATION_SELECTION", "Visualization selection", JUDGMENT,
           "Choose a chart the data's shape supports, and decline to chart "
           "what a chart would misrepresent."),
    Family("INVESTIGATION_BLUEPRINT", "Investigation blueprint", JUDGMENT,
           "Select the blueprint a competent analyst would work from, and "
           "record a reason for every mandatory objective omitted."),
    Family("ANALYST_INTERPRETATION", "Analyst interpretation", JUDGMENT,
           "Say what the numbers mean in the order a credit reader needs, "
           "and decline a section the evidence does not support."),
    Family("MATERIALITY_JUDGMENT", "Materiality, breadth and persistence",
           JUDGMENT,
           "Decide how large, how broad and how sustained a movement is from "
           "governed measures rather than from the size of its percentage."),
    Family("CHALLENGE_PASS", "Challenge pass", JUDGMENT,
           "Attack the conclusion before a reader does, and report what "
           "survived rather than that a challenge ran."),

    # -------------------------------------------------------------- refusal
    Family("AMBIGUITY", "Ambiguity", REFUSAL,
           "Ask one question that resolves the ambiguity, rather than "
           "guessing a reading and computing it.",
           outcome=CLARIFY),
    Family("UNSUPPORTED_DATA", "Unsupported data", REFUSAL,
           "Say the data is not held, without substituting the nearest thing "
           "that is.",
           outcome=UNSUPPORTED),
    Family("CONTROLLED_FAILURE", "Controlled failure", REFUSAL,
           "Fail visibly and explain what broke, rather than returning a "
           "reduced answer that looks complete.",
           outcome=FAIL),

    # ----------------------------------------------------------- governance
    Family("AGENTIC_ORCHESTRATION", "Agentic orchestration", GOVERNANCE,
           "Plan work across agents and tools within the registry, budget and "
           "approval gates that govern them."),
    Family("TRACE_CONSISTENCY", "Trace consistency", GOVERNANCE,
           "Produce a Trace whose stages agree with what ran: skipped is not "
           "passed, and a failed step fails its stage."),
    Family("OBJECTIVE_COVERAGE", "Objective coverage", GOVERNANCE,
           "Report coverage of every requested objective explicitly, and "
           "never return a silent partial answer."),

    # ---------------------------------------------------------------- scope
    Family("CORPORATE_SCOPE", "Corporate scope", SCOPE,
           "Use corporate vocabulary, grain and concepts — obligor, facility, "
           "covenant, financial spreading.",
           scope=CORPORATE),
    Family("RETAIL_SCOPE", "Retail scope", SCOPE,
           "Use retail vocabulary, grain and concepts — account, product, "
           "bureau score, behavioural scoring.",
           scope=RETAIL),
    Family("ARABIC_QUERY", "Arabic query", SCOPE,
           "Read a question asked in Arabic to the same structured reading an "
           "English question would produce.",
           gated_on="Arabic language support"),
    Family("PROJECT_PLANNER_QUERY", "Project Planner query", SCOPE,
           "Read a question about a planned project against the Project "
           "Planner's governed objects.",
           gated_on="Project Planner"),

    # ------------------------------------------------------------ scorecard
    # §A2. Retail model validation is its own vocabulary, and the families
    # below are separated more finely than the topic strictly requires. That
    # is deliberate: PSI, CSI and "stability" get merged in conversation and
    # then in code, and a corpus that merged them could not tell whether a
    # model had learned the difference between a score distribution moving
    # and one variable's bins moving.
    Family("SCORECARD_DATA_DISCOVERY", "Scorecard data discovery", SCORECARD,
           "Say which scorecard datasets, months and models exist, without "
           "computing a validation metric over them.",
           scope=RETAIL, outcome=EXECUTE),
    Family("SCORECARD_MODEL_EQUATION", "Scorecard model equation", SCORECARD,
           "Report the registered equation — intercept, terms, link and "
           "score mapping — as the registry holds it, including the declared "
           "score direction rather than an assumed one.",
           scope=RETAIL),
    Family("SCORECARD_VARIABLES", "Scorecard variables", SCORECARD,
           "Distinguish a variable in the model from a variable in the "
           "dictionary, and report which are scoreable.",
           scope=RETAIL),
    Family("SCORECARD_WOE_BINNING", "Scorecard WoE and binning", SCORECARD,
           "Read the frozen binning specification: bins, Weight of Evidence "
           "and Information Value under the approved spec version, never "
           "recomputed from the validation month.",
           scope=RETAIL),
    Family("SCORECARD_DISCRIMINATION", "Scorecard discrimination", SCORECARD,
           "Compute or explain rank ordering — AUC, Gini, KS — on a matured "
           "cohort, respecting the registered score direction.",
           scope=RETAIL),
    Family("SCORECARD_CALIBRATION", "Scorecard calibration", SCORECARD,
           "Compare predicted PD against the observed default rate, and keep "
           "that question separate from rank ordering.",
           scope=RETAIL),
    Family("SCORECARD_STABILITY", "Scorecard stability", SCORECARD,
           "Report population and characteristic movement against the "
           "development baseline, which needs no outcome and is therefore "
           "available on an immature month.",
           scope=RETAIL),
    Family("SCORECARD_PSI", "Scorecard PSI", SCORECARD,
           "Population Stability Index on the SCORE distribution, against "
           "the declared baseline, with the cut-offs named as a convention "
           "rather than a regulatory requirement.",
           scope=RETAIL),
    Family("SCORECARD_CSI", "Scorecard CSI", SCORECARD,
           "Characteristic Stability Index on ONE VARIABLE's bins — not the "
           "score, and not the population as a whole.",
           scope=RETAIL),
    Family("SCORECARD_VARIABLE_DIAGNOSTICS", "Scorecard variable diagnostics",
           SCORECARD,
           "Report a single variable's standalone power and separate it from "
           "the model's power; a variable's Gini is not the model's Gini.",
           scope=RETAIL),
    Family("SCORECARD_IMPLEMENTATION", "Scorecard implementation replication",
           SCORECARD,
           "Re-derive bin, WoE, logit, PD and score from the stored "
           "specification and report where the production value differs.",
           scope=RETAIL),
    Family("SCORECARD_SEGMENT_PERFORMANCE", "Scorecard segment performance",
           SCORECARD,
           "Report performance within a segment and refuse to rank a segment "
           "too small to carry the metric.",
           scope=RETAIL),
    Family("SCORECARD_CUTOFF", "Scorecard cut-off", SCORECARD,
           "Answer a decision-performance question only where an approved "
           "cut-off exists, and say so where none does.",
           scope=RETAIL),
    Family("SCORECARD_OVERRIDE", "Scorecard override and usage", SCORECARD,
           "Answer an override or usage question from recorded data, or "
           "state that this workspace does not capture it.",
           scope=RETAIL),
    Family("SCORECARD_MODEL_COMPARISON", "Scorecard model comparison",
           SCORECARD,
           "Compare models on an identical population and period, and say "
           "when overlapping intervals mean the difference is not "
           "established.",
           scope=RETAIL),
    Family("SCORECARD_RESCORING", "Scorecard candidate and rescoring",
           SCORECARD,
           "Treat a proposed equation as a candidate version: validated, "
           "diffed, scored in memory, never activated.",
           scope=RETAIL),
    Family("SCORECARD_MATURITY", "Scorecard outcome maturity", SCORECARD,
           "Distinguish the latest data month from the latest matured "
           "performance month, and refuse an outcome metric on a cohort "
           "whose window has not closed.",
           scope=RETAIL),
    Family("SCORECARD_DEFAULT_DEFINITION", "Scorecard default definition",
           SCORECARD,
           "Report the governed default definition in full — basis, days "
           "past due, window, exclusions, indeterminate treatment.",
           scope=RETAIL),
    Family("SCORECARD_REPORT", "Scorecard validation report", SCORECARD,
           "Answer from the governed report and its evidence index, and "
           "reconcile a reported figure to the dashboard it came from.",
           scope=RETAIL),
    Family("SCORECARD_REGULATORY", "Scorecard regulatory framing", SCORECARD,
           "Describe the report structure as CBUAE MMS/MMG-ALIGNED and "
           "refuse to present CreditProbe as providing certification, or a "
           "seeded limit as a regulatory requirement.",
           scope=RETAIL),
    Family("SCORECARD_AGENTIC_DIAGNOSIS", "Scorecard agentic diagnosis",
           SCORECARD,
           "Run a governed diagnostic investigation — why discrimination "
           "fell, what changed when accuracy did — and label the claim "
           "strength honestly.",
           scope=RETAIL),
    Family("SCORECARD_AMBIGUITY", "Scorecard ambiguity", SCORECARD,
           "Ask which model, which month or which metric was meant, rather "
           "than picking one and computing confidently.",
           scope=RETAIL, outcome=CLARIFY),
    Family("SCORECARD_CONTROLLED_FAILURE", "Scorecard controlled failure",
           SCORECARD,
           "Refuse a scorecard question the data cannot answer, and say what "
           "is missing rather than returning a number.",
           scope=RETAIL),
)

BY_ID: dict[str, Family] = {f.id: f for f in FAMILIES}
IDS: tuple[str, ...] = tuple(f.id for f in FAMILIES)
AVAILABLE: tuple[str, ...] = tuple(f.id for f in FAMILIES if f.available)
GATED: tuple[str, ...] = tuple(f.id for f in FAMILIES if not f.available)


def get(family_id: str) -> Family | None:
    return BY_ID.get(str(family_id or "").strip().upper())


def in_group(group: str) -> tuple[Family, ...]:
    return tuple(f for f in FAMILIES if f.group == group)


# ------------------------------------------------------------- the crosswalk
# The Phase 0 curriculum names twenty-five families of its own, and §13 asks
# for every eligible existing case to be migrated rather than rewritten. This
# is the map that makes the migration mechanical instead of a judgment call
# repeated three hundred times.
#
# Deliberately literals on both sides. The backend must not import the
# curriculum — a module here that can reach `intelligence_factory` can reach
# the sealed holdout one line later — so the left-hand names are copied, and a
# factory-side test asserts the copy still matches.
LEGACY_FAMILIES: dict[str, str] = {
    "data discovery": "DATA_DISCOVERY",
    "data inspection": "DATA_INSPECTION",
    "data dictionary": "DATA_DICTIONARY",
    "relationships": "DATA_RELATIONSHIPS",
    "field classification": "DATA_DICTIONARY",
    "methods": "DATA_DICTIONARY",
    "simple calculation": "SINGLE_DOMAIN_AGGREGATION",
    "conditional aggregation": "SINGLE_DOMAIN_AGGREGATION",
    "nested ratio": "PD_LGD_EAD_ANALYSIS",
    "period comparison": "PERIOD_ALIGNMENT",
    "multi-domain join": "MULTI_DATASET_JOIN",
    "ranking": "FILTERING_AND_RANKING",
    "filters": "FILTERING_AND_RANKING",
    "broad investigation": "BROAD_INVESTIGATION",
    "presentation change": "PRESENTATION_MODIFICATION",
    "compound question": "COMPOUND_OBJECTIVES",
    "incomplete-response repair": "OBJECTIVE_COVERAGE",
    "entity resolution": "AMBIGUITY",
    "ambiguity": "AMBIGUITY",
    "unsupported": "UNSUPPORTED_DATA",
    "multi-turn referent": "MULTI_TURN_REFERENTS",
    "scope narrowing": "MULTI_TURN_REFERENTS",
    "scope widening": "MULTI_TURN_REFERENTS",
    "scope reset": "MULTI_TURN_REFERENTS",
    "adversarial boundary": "FILTERING_AND_RANKING",
}


def from_legacy(family: str) -> str:
    """The governed family a Phase 0 curriculum family migrates into.

    Returns "" for anything unrecognised rather than guessing: an unmapped
    legacy family is a case a person has to place, and §13 says migrate the
    *eligible* cases, which means some are not.
    """
    return LEGACY_FAMILIES.get(str(family or "").strip().lower(), "")


__all__ = [
    "AVAILABLE", "BY_ID", "CALCULATION", "CLARIFY", "CORPORATE", "EXECUTE",
    "FAIL", "FAMILIES", "FAMILY_VERSION", "GATED", "GROUPS", "IDS",
    "LEGACY_FAMILIES", "NO_SCOPE", "OUTCOMES", "PORTFOLIO_SCOPES", "RETAIL",
    "UNSUPPORTED", "Family", "from_legacy", "get", "in_group",
    "METADATA", "CONVERSATION", "STRUCTURE", "MIGRATION", "ECL", "PORTFOLIO",
    "BORROWER", "JUDGMENT", "REFUSAL", "GOVERNANCE", "SCOPE",
]
