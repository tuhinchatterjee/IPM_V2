"""
Existing reviewed work, in the governed schema. §13.

    "Migrate all eligible existing non-holdout, non-confidential validated Ask
     cases; migrate certified Analysis Studio method examples where suitable."

Three sources, and what each one is worth
-----------------------------------------
``curriculum``  Thirty-three hand-written threads from Phase 0. Small, and the
                only source where a person chose every word.
``complex``     The generated complex-query corpus: reviewed sentence shapes
                instantiated over the governed vocabulary. The specification of
                every case was reviewed once; the phrasing is generated. That
                distinction is recorded on the case rather than smoothed over.
``studio``      The certified methods. §6 names certified Analysis Studio
                methods as a system-validation source, so these are the only
                migrated cases eligible for SYSTEM_VALIDATED — and only the
                CERTIFIED ones. A preconfigured method is a definition somebody
                wrote, not a contract anything validated.

What migration does not do
--------------------------
It does not approve anything. Every case comes out at whatever status its own
validators allow, and a person still has to sign for it before retrieval can
see it. Migration moves work into the schema; it does not inherit a review that
was given for something else.

It also never touches the sealed holdout, and it cannot: this module imports
the open curriculum and the backend, and the import-graph test that has covered
`intelligence_factory` since P1 covers it.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from backend.teaching import families as fam
from backend.teaching import schema as sc
from backend.teaching import status as st

logger = logging.getLogger(__name__)

MIGRATION_VERSION = "1.0.0"

#: The three sources, as they appear in `source_provenance` and in the report.
CURRICULUM = "curriculum"
COMPLEX = "complex"
STUDIO = "studio"

SOURCES: tuple[str, ...] = (CURRICULUM, COMPLEX, STUDIO)


# ---------------------------------------------------------------------------
# Shared conversions
# ---------------------------------------------------------------------------

#: The Phase 0 outcome vocabulary is a subset of §7's. FAIL has no Phase 0
#: equivalent — the complex corpus expresses controlled failure through its
#: category rather than its outcome — so it is added by the category map below
#: rather than translated from a turn.
_OUTCOMES = {"EXECUTE": fam.EXECUTE, "CLARIFY": fam.CLARIFY,
             "UNSUPPORTED": fam.UNSUPPORTED}


def _outcome(turns: list[Any]) -> str:
    """A thread's outcome is its LAST turn's.

    A thread that clarifies and then executes is an executing thread; taking
    the first turn's outcome would file every repair case under CLARIFY and
    leave the family that is about repair empty.
    """
    for turn in reversed(turns):
        declared = _OUTCOMES.get(str(getattr(turn, "outcome", "") or "").upper())
        if declared:
            return declared
    return fam.EXECUTE


def _period_contract(period: str) -> dict[str, Any]:
    """A period phrase as a contract.

    Deliberately keeps the phrase rather than resolving it to dates. The case
    teaches how to read "the latest year"; a resolved date range would teach a
    range that stops being latest next quarter — §8's rule applied to periods.
    """
    text = str(period or "").strip()
    return {"phrase": text, "basis": "as stated"} if text else {}


def _turn(index: int, turn: Any) -> sc.Turn:
    """One Phase 0 turn as a §9 turn."""
    action = str(getattr(turn, "action", "") or "")
    if not action:
        action = "NEW_REQUEST" if index == 0 else "CONTINUE"
    reading = {
        "capability": str(getattr(turn, "capability", "") or ""),
        "concepts": list(getattr(turn, "concepts", ()) or ()),
        "datasets": list(getattr(turn, "datasets", ()) or ()),
    }
    period = _period_contract(getattr(turn, "period", ""))
    if period:
        reading["period"] = period
    return sc.Turn(
        turn_index=index,
        user_message=str(getattr(turn, "question", "") or ""),
        conversation_action=action,
        expected_reading={k: v for k, v in reading.items() if v},
        expected_result_type=_result_type(turn),
        expected_answer_behavior=_behaviour(turn),
    )


def _result_type(turn: Any) -> str:
    outcome = str(getattr(turn, "outcome", "") or "").upper()
    if outcome == "CLARIFY":
        return "CLARIFICATION"
    if outcome == "UNSUPPORTED":
        return "REFUSAL"
    capability = str(getattr(turn, "capability", "") or "").upper()
    if capability.startswith("DATA_") or capability.startswith("METHOD"):
        return "NARRATIVE"
    return "TABLE"


def _behaviour(turn: Any) -> str:
    """What the answer must do, from the turn's own invariants and refusals.

    Written from the structured fields rather than invented, so the sentence a
    reviewer reads is the sentence the evaluator checks — not a paraphrase of
    it that drifts.
    """
    parts: list[str] = []
    invariants = list(getattr(turn, "invariants", ()) or ())
    forbidden = list(getattr(turn, "forbidden", ()) or ())
    if invariants:
        parts.append("Must satisfy " + ", ".join(invariants) + ".")
    if forbidden:
        parts.append("Must not " + ", ".join(forbidden) + ".")
    return " ".join(parts)


def _objectives(turns: list[Any], extra: tuple[str, ...] = ()) -> list[
        sc.Objective]:
    """One objective per turn, plus whatever the source knows to add.

    Deliberately NOT derived by running the product's own objective decomposer
    over the question. An expectation read off the system under test is an
    expectation that agrees with it by construction, which is the same failure
    as a stored answer quietly aligned to whatever the product returns.
    """
    out: list[sc.Objective] = []
    for index, turn in enumerate(turns):
        question = str(getattr(turn, "question", "") or "").strip()
        if not question:
            continue
        out.append(sc.Objective(id=f"t{index}", text=question,
                                kind=str(getattr(turn, "capability", "")
                                         or "ANALYSIS")))
    for position, text in enumerate(extra):
        out.append(sc.Objective(id=f"x{position}", text=text,
                                kind="DECOMPOSITION"))
    return out


def refile(family_id: str, *, outcome: str, capability: str) -> str:
    """The family a case belongs in when the one it was mapped to contradicts
    what the case actually does.

    Phase 0's "ambiguity" family holds both halves of a pair: the question that
    must be clarified, and its counterpart showing that naming the measure
    answers it. Both are ambiguity *lessons*; only one is an AMBIGUITY case
    under §7, because §7's family is defined by the outcome. Filing the
    executing half there would put a case in the family that says "do not
    compute this" whose whole point is that it should be computed.

    So a family with an outcome obligation refuses a case that contradicts it,
    and the case goes where its work actually is.
    """
    family = fam.get(family_id)
    if family is None or not family.outcome or family.outcome == outcome:
        return family_id
    if str(capability or "").upper().startswith("DATA_"):
        return "DATA_DICTIONARY"
    return "SINGLE_DOMAIN_AGGREGATION"


def _cluster(question: str) -> str:
    """A paraphrase cluster for a question. §15.

    Content words only, sorted — so "total EAD by sector in Q1" and "by sector,
    total EAD for Q1" land in one cluster and cannot both dominate retrieval.
    Crude on purpose: an embedding-based cluster is a later refinement, and a
    crude cluster that ships beats an exact one that does not.
    """
    words = sorted({w for w in re.findall(r"[a-z]{4,}", question.lower())
                    if w not in _STOP})
    digest = hashlib.sha256(" ".join(words).encode()).hexdigest()
    return f"cl-{digest[:16]}"


_STOP = frozenset({
    "what", "which", "show", "give", "tell", "have", "does", "with", "from",
    "over", "into", "that", "this", "them", "those", "these", "your", "about",
    "many", "much", "been", "were", "will", "when", "where", "some", "than",
    "then", "there", "here", "just", "also", "only", "more", "most", "each",
    "both", "same", "make", "made", "like", "want", "need", "please",
})


def _base(case_id: str, *, title: str, family_id: str, turns: list[Any],
          source: str, provenance: str, difficulty: str, risk: str,
          objectives: list[sc.Objective],
          authoring: str = st.MIGRATED) -> sc.TeachingCase:
    """The fields every migrated case sets the same way."""
    question = str(getattr(turns[0], "question", "") or "") if turns else ""
    concepts: list[str] = []
    datasets: list[str] = []
    invariants: list[str] = []
    forbidden: list[str] = []
    for turn in turns:
        concepts += [c for c in (getattr(turn, "concepts", ()) or ())
                     if c not in concepts]
        datasets += [d for d in (getattr(turn, "datasets", ()) or ())
                     if d not in datasets]
        invariants += [i for i in (getattr(turn, "invariants", ()) or ())
                       if i not in invariants]
        forbidden += [f for f in (getattr(turn, "forbidden", ()) or ())
                      if f not in forbidden]

    outcome = _outcome(turns)
    case = sc.TeachingCase(
        case_id=case_id,
        title=title[:200],
        family_id=family_id,
        description=f"Migrated from the {source} corpus.",
        question=question,
        conversation_turns=[_turn(i, t) for i, t in enumerate(turns)],
        expected_capability=str(getattr(turns[0], "capability", "") or "")
        if turns else "",
        expected_conversation_action=str(getattr(turns[0], "action", "")
                                         or "NEW_REQUEST") if turns else "",
        expected_outcome=outcome,
        objectives=objectives,
        concepts=concepts,
        required_datasets=datasets,
        invariants=invariants,
        difficulty=difficulty,
        risk_level=risk,
        authoring_method=authoring,
        data_sensitivity=st.PUBLIC,
        source_provenance=provenance,
        cluster_id=_cluster(question),
        tags=[source],
    )
    # Where a refusal lands. §4 gives no general "forbidden behaviours" field —
    # the three it names are about datasets, relationships and tools — so a
    # behavioural refusal goes in the scope contract, which is the field that
    # says what the case is and is not for.
    if forbidden:
        case.scope_contract = {"forbidden_behaviours": forbidden}
    if outcome == fam.EXECUTE:
        case.analytical_plan_contract = {
            "capability": case.expected_capability or "ANALYSIS",
            "concepts": concepts, "datasets": datasets,
        }
    elif outcome == fam.CLARIFY:
        case.clarification_contract = {
            "ask": "Name the measure, population or period the question "
                   "leaves open before computing anything.",
            "forbidden": forbidden or ["ANALYSIS"],
        }
    elif outcome == fam.UNSUPPORTED:
        case.abstention_contract = {
            "declines": question,
            "because": "the data is not held",
            "forbidden": forbidden or ["ANALYSIS"],
        }
    return sc.sealed(case)


# ---------------------------------------------------------------------------
# The Phase 0 curriculum
# ---------------------------------------------------------------------------

#: Which Phase 0 families are worth more than FOUNDATIONAL. The rest are
#: metadata and single-measure questions, and calling those COMPLEX would make
#: §13's "at least 150 must be EXPERT or ADVERSARIAL" meaningless.
_CURRICULUM_DIFFICULTY: dict[str, str] = {
    "nested ratio": sc.COMPLEX,
    "multi-domain join": sc.COMPLEX,
    "filters": sc.COMPLEX,
    "broad investigation": sc.COMPLEX,
    "compound question": sc.COMPLEX,
    "incomplete-response repair": sc.EXPERT,
    "multi-turn referent": sc.COMPLEX,
    "scope narrowing": sc.COMPLEX,
    "scope widening": sc.COMPLEX,
    "scope reset": sc.EXPERT,
    "ambiguity": sc.EXPERT,
    "unsupported": sc.EXPERT,
    "entity resolution": sc.EXPERT,
    "adversarial boundary": sc.ADVERSARIAL,
}

_CURRICULUM_RISK: dict[str, str] = {
    "ambiguity": "HIGH", "unsupported": "HIGH", "entity resolution": "HIGH",
    "adversarial boundary": "HIGH", "broad investigation": "HIGH",
    "incomplete-response repair": "HIGH",
}


def from_curriculum() -> list[sc.TeachingCase]:
    """The thirty-three hand-written Phase 0 threads."""
    from intelligence_factory import curriculum as cur

    out: list[sc.TeachingCase] = []
    for case in cur.CASES:
        family_id = fam.from_legacy(case.family)
        if not family_id:
            # §13 says migrate the ELIGIBLE cases, which means some are not.
            # Logged rather than dropped silently: an unmapped family is a
            # decision somebody has to make, not an absence.
            logger.info("No governed family for %r; case %s not migrated",
                        case.family, case.id)
            continue
        turns = list(case.turns)
        family_id = refile(
            family_id, outcome=_outcome(turns),
            capability=str(getattr(turns[0], "capability", "") or "")
            if turns else "")
        out.append(enrich(_base(
            f"mig-cur-{case.id}", title=case.title, family_id=family_id,
            turns=turns, source=CURRICULUM,
            provenance=f"curriculum:{case.id}@{cur.CURRICULUM_VERSION}",
            difficulty=_CURRICULUM_DIFFICULTY.get(case.family,
                                                  sc.INTERMEDIATE),
            risk=_CURRICULUM_RISK.get(case.family, "MEDIUM"),
            objectives=_objectives(turns))))
    return out


# ---------------------------------------------------------------------------
# The complex-query corpus
# ---------------------------------------------------------------------------

#: Each of the twelve P0.6 categories, as (family, difficulty, risk).
#: Assignments are conservative: a category maps to the family whose obligation
#: its template actually demonstrates, not to the family whose name sounds
#: closest.
_COMPLEX_FAMILIES: dict[str, tuple[str, str, str]] = {
    "same-turn referent": ("SAME_TURN_COREFERENCE", sc.EXPERT, "HIGH"),
    "multi-clause objective": ("COMPOUND_OBJECTIVES", sc.EXPERT, "HIGH"),
    "cohort comparison": ("COHORT_COMPARISON", sc.COMPLEX, "MEDIUM"),
    "multi-domain borrower screen": ("MULTI_DATASET_JOIN", sc.COMPLEX,
                                     "MEDIUM"),
    "portfolio investigation": ("BROAD_INVESTIGATION", sc.EXPERT, "HIGH"),
    "ECL decomposition": ("ECL_CHANGE_DECOMPOSITION", sc.EXPERT, "CRITICAL"),
    "association vs causation": ("ASSOCIATION_NOT_CAUSATION", sc.EXPERT,
                                 "HIGH"),
    "period and population alignment": ("PERIOD_ALIGNMENT", sc.COMPLEX,
                                        "HIGH"),
    "chart selection": ("VISUALIZATION_SELECTION", sc.COMPLEX, "MEDIUM"),
    "agentic Trace consistency": ("TRACE_CONSISTENCY", sc.COMPLEX, "HIGH"),
    "unsupported and abstention": ("UNSUPPORTED_DATA", sc.ADVERSARIAL,
                                   "HIGH"),
    "error control": ("CONTROLLED_FAILURE", sc.ADVERSARIAL, "CRITICAL"),
}

#: §11's decomposition objectives, which a decomposition case must cover and
#: the template cannot express as turns. Written once here rather than repeated
#: across seventy-five generated cases.
_DECOMPOSITION_OBJECTIVES: tuple[str, ...] = (
    "total ECL change over the stated window",
    "exposure effect",
    "stage/SICR effect",
    "PD effect",
    "LGD effect",
    "mix effect",
    "residual and overlay",
    "sector contributors, ranked",
    "customer contributors, ranked",
    "reconciliation of the components back to the total",
    "interpretation of what drove the movement",
)

#: What a multi-clause case must settle. The template builds three clauses; a
#: case that answers two of them and stops is the exact failure §21 forbids.
_MULTI_CLAUSE_OBJECTIVES: tuple[str, ...] = (
    "the requested total for the named population",
    "the ranking by the second measure",
    "which of the ranked borrowers moved the most over the window",
)


def _complex_extra(category: str) -> tuple[str, ...]:
    if category == "ECL decomposition":
        return _DECOMPOSITION_OBJECTIVES
    if category == "multi-clause objective":
        return _MULTI_CLAUSE_OBJECTIVES
    return ()


def from_complex() -> list[sc.TeachingCase]:
    """The generated complex-query corpus, category by category.

    Every case is marked LLM-free but machine-phrased: `authoring_method` stays
    MIGRATED and the description says the specification was reviewed and the
    phrasing generated. §5 forbids calling a generated case human reviewed, and
    the honest description is neither "human wrote this" nor "a model wrote
    this".
    """
    from intelligence_factory import complex as cx

    out: list[sc.TeachingCase] = []
    for case in cx.cases():
        mapping = _COMPLEX_FAMILIES.get(case.family)
        if mapping is None:
            logger.info("No governed family for complex category %r",
                        case.family)
            continue
        family_id, difficulty, risk = mapping
        turns = list(case.turns)
        built = _base(
            f"mig-cx-{case.id}", title=case.title, family_id=family_id,
            turns=turns, source=COMPLEX,
            provenance=f"complex:{case.family}:{case.id}"
                       f"@{cx.COMPLEX_CURRICULUM_VERSION}",
            difficulty=difficulty, risk=risk,
            objectives=_objectives(turns, _complex_extra(case.family)))
        built.description = ("Migrated from the complex-query corpus: a "
                             "reviewed sentence shape instantiated over the "
                             "governed vocabulary. The specification was "
                             "reviewed; the phrasing is generated.")
        out.append(enrich(built))
    return out


#: Clause separators that mark a genuinely separate objective. Deliberately
#: narrow: an explicit conjunction or a semicolon. A comma alone splits "For
#: Contracting, calculate…" into a scope prefix and a fragment, and a corpus
#: full of fragments teaches the coverage validator to accept fragments.
_CLAUSE = re.compile(r",\s+and\s+|;\s+|\s+and then\s+", re.I)


def _clauses(question: str) -> list[str]:
    parts = [p.strip(" .?") for p in _CLAUSE.split(str(question or ""))]
    return [p for p in parts if len(p) > 8]


def enrich(case: sc.TeachingCase) -> sc.TeachingCase:
    """The obligations a family puts on a case, applied wherever it came from.

    This runs for every migrated case, from every source, keyed on the family
    it ended up in rather than on the corpus it came from. That matters: a
    certified method called "ECL Change Decomposition" lands in
    ECL_CHANGE_DECOMPOSITION exactly like a generated case does, and a version
    of this that only ran on the generated corpus would leave it with one
    objective and no reconciliation invariant — a decomposition case that
    cannot fail the coverage validator, which makes it useless for the one
    thing it is meant to teach.
    """
    family_id = case.family_id

    if family_id == "SAME_TURN_COREFERENCE" and \
            not case.same_turn_discourse.bound():
        # §10: the antecedent is inside the sentence, and the case has to say
        # which cohort it is or it teaches nothing about local reference.
        found = _referents_in(case.question)
        case.same_turn_discourse = sc.Discourse(
            cohorts={"matched": "the borrowers the first clause selects"},
            referents={surface: "matched"
                       for surface in (found or ["them"])})
        case.cohorts = list(dict.fromkeys([*case.cohorts, "matched"]))

    elif family_id == "ECL_CHANGE_DECOMPOSITION":
        case.method_contract = {**case.method_contract,
                                "method_id": "ecl_change_decomposition",
                                "order_neutral": True}
        case.invariants = list(dict.fromkeys(
            [*case.invariants, "components_reconcile"]))
        if len(case.objectives) < len(_DECOMPOSITION_OBJECTIVES):
            case.objectives = _objectives_from(_DECOMPOSITION_OBJECTIVES,
                                               "DECOMPOSITION")

    elif family_id == "COMPOUND_OBJECTIVES" and len(case.objectives) < 2:
        clauses = _clauses(case.question)
        if len(clauses) >= 2:
            case.objectives = _objectives_from(tuple(clauses), "CLAUSE")

    elif family_id == "VISUALIZATION_SELECTION":
        case.visualization_contract = case.visualization_contract or {
            "must_suit": "the shape of the result",
            "decline_when": "a chart would misrepresent the data"}

    elif family_id == "TRACE_CONSISTENCY":
        case.trace_contract = case.trace_contract or {
            "skipped_is_not_pass": True, "failure_rolls_up": True}

    elif family_id == "CONTROLLED_FAILURE":
        case.expected_outcome = fam.FAIL
        case.result_contract = case.result_contract or {
            "shape": "an explained failure",
            "forbidden": "a reduced answer that looks complete"}

    elif family_id == "ASSOCIATION_NOT_CAUSATION":
        case.interpretation_contract = case.interpretation_contract or {
            "state_as": "association",
            "must_name": "what evidence would be needed to claim cause"}

    elif family_id == "BROAD_INVESTIGATION":
        case.result_contract = case.result_contract or {
            "shape": "what was examined as well as what was found"}

    return sc.sealed(case)


def _objectives_from(texts: tuple[str, ...], kind: str) -> list[sc.Objective]:
    return [sc.Objective(id=f"o{i}", text=text, kind=kind)
            for i, text in enumerate(texts)]


_PRONOUNS = ("them", "those customers", "these customers", "those",
             "these", "the first group", "the second cohort",
             "these measures", "the worst three", "those that improved")


def _referents_in(question: str) -> list[str]:
    """The local referents a question actually contains. §10's list."""
    lowered = str(question or "").lower()
    return [phrase for phrase in _PRONOUNS if phrase in lowered]


# ---------------------------------------------------------------------------
# Certified Analysis Studio methods
# ---------------------------------------------------------------------------

#: What a method is about, decided by what its name says rather than by its
#: shelf. Checked in order — the first match wins — because "stage migration"
#: is a migration case whatever category it is filed under, and "ECL by stage"
#: is not.
_METHOD_RULES: tuple[tuple[str, str], ...] = (
    (r"\brating\b.*\bmigration\b|\bmigration\b.*\brating\b|\bgrade\b.*"
     r"\bmigration\b|\bnotch\b", "RATING_MIGRATION"),
    (r"\bstage\b.*\bmigration\b|\bmigration\b.*\bstage\b|\bsicr\b",
     "STAGE_MIGRATION"),
    (r"\bdpd\b.*\b(migration|bucket|roll)\b|\bdelinquen\w*\b.*\bmigration\b|"
     r"\bbucket\b.*\bmigration\b", "DPD_MIGRATION"),
    (r"\broll[ -]?rate\b|\bcure\b|\brecovery rate\b|\bre[- ]?default\b",
     "ROLL_RATE_AND_CURE"),
    (r"\bdecompos\w*|\battribution\b|\bbridge\b|\bwalk\b", 
     "ECL_CHANGE_DECOMPOSITION"),
    (r"\bconcentration\b|\bherfindahl\b|\bhhi\b|\bgini\b|\blarge exposure\b",
     "CONCENTRATION"),
    (r"\bvintage\b|\bcohort\b|\bseasoning\b", "VINTAGE_AND_COHORT"),
    (r"\bstress\b|\bscenario\b|\bsensitivit\w*", "STRESS_AND_SCENARIO"),
    (r"\bcovenant\b|\bheadroom\b|\bbreach\b", "COVENANT_AND_COLLATERAL"),
    (r"\bcollateral\b|\bltv\b|\bloan[- ]to[- ]value\b|\bsecurit\w*|"
     r"\bguarantee\b", "COVENANT_AND_COLLATERAL"),
    (r"\bappetite\b|\blimit utilisation\b|\bthreshold\b|\btolerance\b",
     "RISK_APPETITE"),
    (r"\bearly warning\b|\bwatchlist\b|\bwatch list\b|\bsignal\b|\btrigger\b",
     "EARLY_WARNING"),
    (r"\bmix\b|\bcomposition\b|\bdistribution\b|\bshare\b|\bprofile\b",
     "PORTFOLIO_MIX"),
    (r"\bpd\b|\blgd\b|\bprobability of default\b|\bloss given default\b",
     "PD_LGD_EAD_ANALYSIS"),
    (r"\becl\b.*\b(change|movement|growth|drift|trend)\b|"
     r"\b(change|movement|growth|drift|trend)\b.*\becl\b", "ECL_MOVEMENT"),
    (r"\bleverage\b|\bdscr\b|\bcoverage ratio\b|\bebitda\b|\bliquidity\b|"
     r"\bcurrent ratio\b|\bdeteriorat\w*", "FINANCIAL_DETERIORATION"),
)

#: The shelf a method sits on, when its name settles nothing. A category that
#: does not appear here falls through to SINGLE_DOMAIN_AGGREGATION, which is
#: the honest family for "compute this measure over this population".
_METHOD_CATEGORIES: dict[str, str] = {
    "Migration": "STAGE_MIGRATION",
    "Concentration": "CONCENTRATION",
    "Vintage / Cohort": "VINTAGE_AND_COHORT",
    "Stress / Scenario": "STRESS_AND_SCENARIO",
    "Covenants": "COVENANT_AND_COLLATERAL",
    "Collateral": "COVENANT_AND_COLLATERAL",
    "Limits / Large Exposure": "RISK_APPETITE",
    "Risk Appetite": "RISK_APPETITE",
    "Early Warning": "EARLY_WARNING",
    "Watchlist": "EARLY_WARNING",
    "Recovery / Cure": "ROLL_RATE_AND_CURE",
}


def family_for_method(method: Any) -> str:
    """Which governed family a certified method teaches."""
    text = f"{getattr(method, 'id', '')} {getattr(method, 'name', '')}".lower()
    for pattern, family_id in _METHOD_RULES:
        if re.search(pattern, text):
            return family_id
    category = str(getattr(getattr(method, "category", ""), "value",
                           getattr(method, "category", "")) or "")
    return _METHOD_CATEGORIES.get(category, "SINGLE_DOMAIN_AGGREGATION")


def _method_question(method: Any) -> str:
    name = str(getattr(method, "name", "") or "").strip()
    grain = str(getattr(method, "required_grain", "") or "").lower()
    if "customer" in grain or "obligor" in grain or "borrower" in grain:
        return f"Show {name.lower()} by borrower for the latest period."
    if "sector" in grain or "segment" in grain:
        return f"Show {name.lower()} by segment for the latest period."
    return f"What is the {name.lower()} for the latest period?"


def from_certified_methods() -> list[sc.TeachingCase]:
    """Every CERTIFIED Analysis Studio method, as two teaching cases.

    Only certified ones. A preconfigured method is a definition somebody wrote;
    §6 admits "certified Analysis Studio methods" as a system-validation source
    precisely because certification is the step where it stopped being one
    person's opinion.

    Two shapes, because a method teaches two different things:

    - *selection*: a question phrased the way a credit officer would phrase it
      must reach THIS method rather than the nearest-sounding one;
    - *definition*: the same method named directly is a dictionary question,
      and answering it with an analysis is the failure the metadata families
      exist for.
    """
    from backend.studio import library as lib
    from backend.studio.model import Lifecycle

    out: list[sc.TeachingCase] = []
    for method in lib.all_definitions():
        if method.lifecycle != Lifecycle.CERTIFIED:
            continue

        method_id = str(method.id)
        family_id = family_for_method(method)
        provenance = f"studio:{method_id}@{getattr(method, 'version', 1)}"
        fields = list(getattr(method, "required_fields", []) or [])
        domains = list(getattr(method, "required_domains", []) or [])

        selection = sc.TeachingCase(
            case_id=f"mig-std-{method_id}",
            title=f"Select {method.name}",
            family_id=family_id,
            description=f"Derived from the certified method {method.name}.",
            question=_method_question(method),
            expected_capability="ANALYSIS",
            expected_conversation_action="NEW_REQUEST",
            expected_outcome=fam.EXECUTE,
            objectives=[sc.Objective(id="o1",
                                     text=f"compute {method.name.lower()}",
                                     kind="CALCULATION")],
            concepts=list(getattr(method, "required_concepts", []) or []),
            metrics=[method.name.lower()],
            candidate_domains=domains,
            grain=str(getattr(method, "required_grain", "") or ""),
            operations=[str(getattr(method, "output_type", "") or "")],
            method_contract={"method_id": method_id,
                             "engine": str(getattr(method, "engine_analysis",
                                                   "") or ""),
                             "required_fields": fields,
                             "weighting": list(
                                 getattr(method, "weighting_options", [])
                                 or [])},
            analytical_plan_contract={"method": method_id, "fields": fields},
            period_contract=_period_contract(
                str(getattr(method, "required_history", "") or "")),
            result_contract={"shape": str(getattr(method, "output_type", "")
                                          or "")},
            invariants=["method_is_certified"],
            difficulty=sc.INTERMEDIATE,
            risk_level="MEDIUM",
            authoring_method=st.DERIVED,
            data_sensitivity=st.PUBLIC,
            source_provenance=provenance,
            cluster_id=_cluster(_method_question(method)),
            tags=[STUDIO, "certified"],
        )
        out.append(enrich(selection))

        aliases = list(getattr(method, "aliases", []) or [])
        if not aliases or not str(getattr(method, "definition", "") or ""):
            continue
        asked = f"What does {aliases[0]} mean?"
        definition = sc.TeachingCase(
            case_id=f"mig-std-{method_id}-def",
            title=f"Define {method.name}",
            family_id="DATA_DICTIONARY",
            description=f"Derived from the certified method {method.name}.",
            question=asked,
            expected_capability="DATA_DICTIONARY",
            expected_conversation_action="NEW_REQUEST",
            expected_outcome=fam.EXECUTE,
            objectives=[sc.Objective(id="o1",
                                     text=f"define {method.name.lower()}",
                                     kind="DEFINITION")],
            entity_references=aliases,
            metrics=[method.name.lower()],
            analytical_plan_contract={"capability": "DATA_DICTIONARY"},
            result_contract={"shape": "a definition, not a calculation"},
            scope_contract={"forbidden_behaviours": ["ANALYSIS"]},
            difficulty=sc.FOUNDATIONAL,
            risk_level="LOW",
            authoring_method=st.DERIVED,
            data_sensitivity=st.PUBLIC,
            source_provenance=provenance,
            cluster_id=_cluster(asked),
            tags=[STUDIO, "certified", "definition"],
        )
        out.append(enrich(definition))
    return out


# ---------------------------------------------------------------------------
# The whole migration
# ---------------------------------------------------------------------------

def cases() -> list[sc.TeachingCase]:
    """Every eligible existing case, in the governed schema."""
    return [*from_curriculum(), *from_complex(), *from_certified_methods()]


def report() -> dict[str, Any]:
    """What migration produced, and what it could not place.

    Counts by family and by the status the validators put each case in, so a
    source that migrates into DRAFT en masse is visible immediately rather than
    after somebody wonders why retrieval is empty.
    """
    produced = cases()
    by_family: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    problems: dict[str, int] = {}

    for case in produced:
        by_family[case.family_id] = by_family.get(case.family_id, 0) + 1
        resolved = sc.resolve_status(case)
        by_status[resolved] = by_status.get(resolved, 0) + 1
        source = case.tags[0] if case.tags else "unknown"
        by_source[source] = by_source.get(source, 0) + 1
        for problem in sc.validate(case):
            problems[problem.field] = problems.get(problem.field, 0) + 1

    return {
        "total": len(produced),
        "by_source": by_source,
        "by_family": by_family,
        "by_status": by_status,
        "problems": problems,
        "families_touched": len(by_family),
        "clusters": len({c.cluster_id for c in produced}),
    }


__all__ = ["COMPLEX", "CURRICULUM", "MIGRATION_VERSION", "SOURCES", "STUDIO",
           "cases", "enrich", "family_for_method", "from_certified_methods",
           "from_complex", "from_curriculum", "report"]
