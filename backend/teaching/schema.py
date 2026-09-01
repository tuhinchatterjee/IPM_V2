"""
The governed TeachingCase schema. §4, §9, §10, §11.

What a teaching case is
-----------------------
A worked example of *how to analyse*, never of what the answer was. §8 is the
line: a case carries the question's structure, the reading, the plan, the
concepts, the data, the method, the invariants and the shape of the answer —
and not "Contracting ECL is 8,563", because that sentence is true for one
quarter and teaches a model to recite a number for every quarter after.

The deterministic runtime calculates. The library teaches how to get there.

Why seventy-one fields
----------------------
Because §4 names seventy-one, and a schema that quietly drops the awkward ones
is a schema that stops governing the awkward cases. They are grouped here for
reading, but every name in §4 is a real attribute, `REQUIRED_FIELDS` lists
them, and a test asserts the list and the dataclass have not drifted apart.

Seven more are declared beyond §4 (`EXTENSION_FIELDS`) because later sections
need them and there is nowhere honest to hide them: `expected_outcome` because
§7's families are defined by it and §21 forbids silent partial answers;
`cluster_id` because §15 requires a paraphrase cluster; and the five staleness
versions §5 names that §4's three version fields do not cover.

Validation is where the governance lives
----------------------------------------
A case that parses is not a case that teaches. `validate` is the part worth
reading: it is a list of the ways a case can look complete and be worthless —
a SAME_TURN_COREFERENCE case with no antecedent, an AMBIGUITY case expected to
execute, a MULTI_TURN_REFERENTS case with one turn, a structure-only case with
a portfolio figure baked into its expected answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any

from backend.teaching import families as fam
from backend.teaching import status as st

SCHEMA_VERSION = "1.0.0"

# ------------------------------------------------------------- vocabularies
FOUNDATIONAL = "FOUNDATIONAL"
INTERMEDIATE = "INTERMEDIATE"
COMPLEX = "COMPLEX"
EXPERT = "EXPERT"
ADVERSARIAL = "ADVERSARIAL"

DIFFICULTIES: tuple[str, ...] = (FOUNDATIONAL, INTERMEDIATE, COMPLEX, EXPERT,
                                 ADVERSARIAL)
#: §13 counts these two together as the demanding end of the library.
DEMANDING: frozenset[str] = frozenset({EXPERT, ADVERSARIAL})

RISK_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Model *roles*, not model IDs. §23 is explicit that provider model
#: identifiers are configuration and must never be embedded as behaviour, so a
#: case declares which role should serve it and the configuration decides what
#: that role is served by. Mirrors `backend.orchestration.routing.ROUTES`;
#: copied rather than imported to keep this module free of the orchestrator,
#: and a test asserts the copy still matches.
ROUTES: tuple[str, ...] = ("A_DETERMINISTIC", "B_ROUTINE", "C_COMPLEX",
                           "D_CRITIC")

EFFORTS: tuple[str, ...] = ("LOW", "STANDARD", "HIGH", "EXHAUSTIVE")

#: Officer levels 1-4 as the agentic layer defines them. 0 means the case does
#: not constrain the level.
OFFICER_LEVELS: tuple[int, ...] = (0, 1, 2, 3, 4)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

#: A run of four or more digits, optionally grouped, that is not a year. What
#: §8 forbids in a structure-only case: "Contracting ECL is 8,563" survives one
#: quarter and then teaches a wrong number for every quarter after.
_FIGURE = re.compile(
    r"(?<![\d.,])"
    # A bare four-digit year is a period, not a portfolio figure. Excluded
    # here rather than filtered afterwards so "over 2024" reads as prose while
    # "20241231" and "8,563" both stay caught.
    r"(?!(?:19|20)\d{2}(?!\d|[.,]\d))"
    r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,}(?:\.\d+)?)"
    r"(?!\d)")


@dataclass(frozen=True)
class Problem:
    """One reason a case does not validate."""

    field: str
    detail: str
    #: A fatal problem stops the case entering any status above DRAFT. A
    #: non-fatal one routes it to SME_REVIEW_REQUIRED — §14's rule for a
    #: variant a validator cannot vouch for, applied to authored cases too.
    fatal: bool = True

    def __str__(self) -> str:
        return f"{self.field}: {self.detail}"


@dataclass
class Discourse:
    """Same-turn antecedents. §10.

    The example §10 gives — "…worsening DPD and declining covenant headroom
    over the latest year? Rank them by EAD." — has no prior conversation at
    all. "them" points backwards inside its own sentence, to a cohort the
    sentence has just defined. That cohort has no name in the text, so the
    case has to give it one, and that is what `cohorts` is for.
    """

    #: A local cohort id → what defines it, in words.
    cohorts: dict[str, str] = field(default_factory=dict)
    #: The surface form as written → the cohort id it resolves to.
    referents: dict[str, str] = field(default_factory=dict)

    def bound(self) -> bool:
        return bool(self.referents) and all(
            target in self.cohorts for target in self.referents.values())

    def to_dict(self) -> dict[str, Any]:
        return {"cohorts": dict(self.cohorts),
                "referents": dict(self.referents)}

    @classmethod
    def from_dict(cls, raw: Any) -> Discourse:
        raw = raw if isinstance(raw, dict) else {}
        return cls(cohorts=dict(raw.get("cohorts") or {}),
                   referents=dict(raw.get("referents") or {}))


@dataclass
class Objective:
    """One thing the question asks for. §11.

    §11's worked example decomposes one sentence into eleven of these. The
    point of listing them is `required`: a case declares which objectives an
    answer may not omit, and §21's coverage validator has something to check
    against rather than a prose paragraph to interpret.
    """

    id: str
    text: str
    #: What kind of work it is — calculation, ranking, reconciliation,
    #: interpretation. Free vocabulary: the taxonomy belongs to the planner,
    #: not to the case.
    kind: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "kind": self.kind,
                "required": self.required}

    @classmethod
    def from_dict(cls, raw: Any) -> Objective:
        raw = raw if isinstance(raw, dict) else {}
        return cls(id=str(raw.get("id") or ""), text=str(raw.get("text") or ""),
                   kind=str(raw.get("kind") or ""),
                   required=bool(raw.get("required", True)))


@dataclass
class Turn:
    """One turn of a thread. §9's twelve fields, none of them optional to the
    families that are about conversation.

    The split between `expected_reading` and `expected_plan_change` is the one
    that matters. A follow-up turn frequently changes the reading without
    changing the plan ("show it as a chart") or changes the plan without
    changing the reading ("only Contracting"), and a case that records only
    one of them cannot tell the two apart.
    """

    turn_index: int = 0
    user_message: str = ""
    #: The same-turn antecedents this turn defines, if any.
    local_discourse_entities: Discourse = field(default_factory=Discourse)
    #: NEW_REQUEST | CONTINUE | MODIFY_PREVIOUS | MODIFY_PRESENTATION |
    #: WIDEN_SCOPE | RESET_SCOPE | METADATA_FOLLOWUP | NAVIGATE |
    #: ASSESS_PREVIOUS_RESULT | CORRECT_INCOMPLETE_RESPONSE
    conversation_action: str = ""
    #: What this turn carries forward from the last one.
    inherited_context: dict[str, Any] = field(default_factory=dict)
    #: What it changes about the scope: narrowed, widened, reset, unchanged.
    scope_delta: dict[str, Any] = field(default_factory=dict)
    expected_reading: dict[str, Any] = field(default_factory=dict)
    expected_plan_change: dict[str, Any] = field(default_factory=dict)
    #: TABLE | SERIES | SCALAR | NARRATIVE | CLARIFICATION | REFUSAL
    expected_result_type: str = ""
    #: Which referent resolves to what, once the prior turns are in play.
    expected_referent_resolution: dict[str, Any] = field(default_factory=dict)
    expected_presentation: dict[str, Any] = field(default_factory=dict)
    #: What the answer must do, in the words a reviewer would use.
    expected_answer_behavior: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["local_discourse_entities"] = self.local_discourse_entities.to_dict()
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> Turn:
        raw = dict(raw) if isinstance(raw, dict) else {}
        raw["local_discourse_entities"] = Discourse.from_dict(
            raw.get("local_discourse_entities"))
        allowed = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in allowed})


@dataclass
class TeachingCase:
    """§4's schema, in full."""

    # ---- identity ----------------------------------------------------------
    case_id: str = ""
    case_version: int = 1
    title: str = ""
    family_id: str = ""
    subfamily: str = ""
    description: str = ""
    language: str = "en"
    locale: str = ""
    #: CORPORATE | RETAIL | NONE
    portfolio_scope: str = fam.NO_SCOPE
    industry_or_product_scope: str = ""
    difficulty: str = INTERMEDIATE
    risk_level: str = "MEDIUM"

    # ---- what was asked ----------------------------------------------------
    question: str = ""
    conversation_turns: list[Turn] = field(default_factory=list)
    same_turn_discourse: Discourse = field(default_factory=Discourse)
    prior_context: dict[str, Any] = field(default_factory=dict)

    # ---- what should happen ------------------------------------------------
    expected_capability: str = ""
    expected_conversation_action: str = ""
    expected_officer_level: int = 0
    expected_agent_roles: list[str] = field(default_factory=list)
    expected_model_route: str = ""
    expected_effort: str = ""

    # ---- what it is about --------------------------------------------------
    objectives: list[Objective] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    entity_references: list[str] = field(default_factory=list)
    cohorts: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    filters: list[dict[str, Any]] = field(default_factory=list)

    # ---- the data ----------------------------------------------------------
    period_contract: dict[str, Any] = field(default_factory=dict)
    grain: str = ""
    population_contract: dict[str, Any] = field(default_factory=dict)
    candidate_domains: list[str] = field(default_factory=list)
    required_datasets: list[str] = field(default_factory=list)
    forbidden_datasets: list[str] = field(default_factory=list)
    required_relationships: list[str] = field(default_factory=list)
    forbidden_relationships: list[str] = field(default_factory=list)
    join_contracts: list[dict[str, Any]] = field(default_factory=list)

    # ---- the analysis ------------------------------------------------------
    operations: list[str] = field(default_factory=list)
    analytical_plan_contract: dict[str, Any] = field(default_factory=dict)
    analytical_ir_contract: dict[str, Any] = field(default_factory=dict)
    formula_contract: dict[str, Any] = field(default_factory=dict)
    method_contract: dict[str, Any] = field(default_factory=dict)
    invariants: list[str] = field(default_factory=list)

    # ---- the answer --------------------------------------------------------
    result_contract: dict[str, Any] = field(default_factory=dict)
    interpretation_contract: dict[str, Any] = field(default_factory=dict)
    visualization_contract: dict[str, Any] = field(default_factory=dict)
    clarification_contract: dict[str, Any] = field(default_factory=dict)
    abstention_contract: dict[str, Any] = field(default_factory=dict)
    trace_contract: dict[str, Any] = field(default_factory=dict)
    scope_contract: dict[str, Any] = field(default_factory=dict)

    # ---- the budget and the boundary ---------------------------------------
    cost_budget: float = 0.0
    latency_budget: float = 0.0
    allowed_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    security_constraints: list[str] = field(default_factory=list)
    #: STRUCTURE_ONLY | DIAGNOSTIC | CLIENT
    data_sensitivity: str = st.PUBLIC
    source_provenance: str = ""

    # ---- governance --------------------------------------------------------
    authoring_method: str = st.HUMAN
    review_status: str = st.DRAFT
    reviewer: str = ""
    approved_at: str = ""
    last_validated_at: str = ""
    ontology_version: str = ""
    method_version: str = ""
    relationship_version: str = ""
    prompt_compatibility: str = ""
    fingerprint: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    # ---- extensions beyond §4, required by later sections ------------------
    #: EXECUTE | CLARIFY | UNSUPPORTED | FAIL. §7 defines three families by it
    #: and §21 forbids answering an ambiguous question as though it were clear.
    expected_outcome: str = fam.EXECUTE
    #: §15's paraphrase cluster, so variants of one question cannot flood
    #: retrieval and cannot straddle an evaluation split.
    cluster_id: str = ""
    #: The four staleness axes §5 names that §4's version fields do not carry.
    dataset_contract_version: str = ""
    planner_schema_version: str = ""
    prompt_schema_version: str = ""
    model_family: str = ""
    #: The family list this case was authored against.
    family_version: str = fam.FAMILY_VERSION

    # ---------------------------------------------------------------- views
    @property
    def family(self) -> fam.Family | None:
        return fam.get(self.family_id)

    def turn_count(self) -> int:
        return len(self.conversation_turns)

    def recorded_versions(self) -> dict[str, str]:
        """The versions this case was validated against, by staleness axis."""
        return {
            st.ONTOLOGY: self.ontology_version,
            st.METHOD: self.method_version,
            st.RELATIONSHIP: self.relationship_version,
            st.DATASET_CONTRACT: self.dataset_contract_version,
            st.PLANNER_SCHEMA: self.planner_schema_version,
            st.PROMPT_SCHEMA: self.prompt_schema_version,
            st.MODEL_FAMILY: self.model_family,
        }

    # ------------------------------------------------------ serialisation
    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["same_turn_discourse"] = self.same_turn_discourse.to_dict()
        out["conversation_turns"] = [t.to_dict()
                                     for t in self.conversation_turns]
        out["objectives"] = [o.to_dict() for o in self.objectives]
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> TeachingCase:
        raw = dict(raw) if isinstance(raw, dict) else {}
        raw["same_turn_discourse"] = Discourse.from_dict(
            raw.get("same_turn_discourse"))
        raw["conversation_turns"] = [Turn.from_dict(t)
                                     for t in (raw.get("conversation_turns")
                                               or [])]
        raw["objectives"] = [Objective.from_dict(o)
                             for o in (raw.get("objectives") or [])]
        allowed = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in allowed})


# --------------------------------------------------------------- the fields
#: §4's list, verbatim and in order. A test compares it against the dataclass
#: so neither can lose a field without the other noticing.
REQUIRED_FIELDS: tuple[str, ...] = (
    "case_id", "case_version", "title", "family_id", "subfamily",
    "description", "language", "locale", "portfolio_scope",
    "industry_or_product_scope", "difficulty", "risk_level", "question",
    "conversation_turns", "same_turn_discourse", "prior_context",
    "expected_capability", "expected_conversation_action",
    "expected_officer_level", "expected_agent_roles", "expected_model_route",
    "expected_effort", "objectives", "concepts", "ambiguities", "entities",
    "entity_references", "cohorts", "metrics", "dimensions", "filters",
    "period_contract", "grain", "population_contract", "candidate_domains",
    "required_datasets", "forbidden_datasets", "required_relationships",
    "forbidden_relationships", "join_contracts", "operations",
    "analytical_plan_contract", "analytical_ir_contract", "formula_contract",
    "method_contract", "invariants", "result_contract",
    "interpretation_contract", "visualization_contract",
    "clarification_contract", "abstention_contract", "trace_contract",
    "scope_contract", "cost_budget", "latency_budget", "allowed_tools",
    "forbidden_tools", "security_constraints", "data_sensitivity",
    "source_provenance", "authoring_method", "review_status", "reviewer",
    "approved_at", "last_validated_at", "ontology_version", "method_version",
    "relationship_version", "prompt_compatibility", "fingerprint", "tags",
    "notes",
)

EXTENSION_FIELDS: tuple[str, ...] = (
    "expected_outcome", "cluster_id", "dataset_contract_version",
    "planner_schema_version", "prompt_schema_version", "model_family",
    "family_version",
)

#: The fields the fingerprint is computed over: what the case *teaches*.
#: Deliberately excludes review metadata, tags, notes and every version — two
#: cases teaching the same thing must fingerprint the same however differently
#: they were reviewed, or duplicate control (§15) cannot see them.
FINGERPRINTED: tuple[str, ...] = (
    "family_id", "subfamily", "portfolio_scope", "question",
    "expected_capability", "expected_conversation_action", "expected_outcome",
    "objectives", "concepts", "metrics", "dimensions", "filters",
    "period_contract", "grain", "population_contract", "required_datasets",
    "required_relationships", "operations", "analytical_plan_contract",
    "analytical_ir_contract", "formula_contract", "method_contract",
    "invariants", "result_contract", "visualization_contract",
)


def fingerprint(case: TeachingCase) -> str:
    """A stable identity for what a case teaches.

    Turns are folded in by message and action only. Two threads asking the
    same questions and taking the same conversational turns teach the same
    thing even when one records richer expectations than the other, and §15
    wants the pair caught rather than counted twice.
    """
    body = case.to_dict()
    payload: dict[str, Any] = {k: body.get(k) for k in FINGERPRINTED}
    payload["turns"] = [(t.turn_index, t.user_message.strip().lower(),
                         t.conversation_action)
                        for t in case.conversation_turns]
    blob = json.dumps(payload, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _text_of(*blocks: Any) -> str:
    """Every string inside a set of contract dicts, flattened."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            found.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    for block in blocks:
        walk(block)
    return " ".join(found)


def validate(case: TeachingCase) -> list[Problem]:  # noqa: C901 - a list of
    # independent rules reads better flat than split across helpers that each
    # need the whole case anyway.
    """Every way this case fails to teach what its family says it teaches."""
    problems: list[Problem] = []
    add = problems.append

    # ---- identity ---------------------------------------------------------
    if not _ID.match(case.case_id or ""):
        add(Problem("case_id", "must be a short slug of letters, digits, "
                               "dot, colon, dash or underscore"))
    if case.case_version < 1:
        add(Problem("case_version", "starts at 1"))
    if not (case.title or "").strip():
        add(Problem("title", "a case with no title is one nobody finds"))
    if not (case.language or "").strip():
        add(Problem("language", "required; default 'en'"))

    family = case.family
    if family is None:
        add(Problem("family_id", f"{case.family_id or 'none'} is not a "
                                 "governed family"))
    if case.difficulty not in DIFFICULTIES:
        add(Problem("difficulty", f"{case.difficulty!r} is not one of "
                                  f"{', '.join(DIFFICULTIES)}"))
    if case.risk_level not in RISK_LEVELS:
        add(Problem("risk_level", f"{case.risk_level!r} is not one of "
                                  f"{', '.join(RISK_LEVELS)}"))
    if case.portfolio_scope not in fam.PORTFOLIO_SCOPES:
        add(Problem("portfolio_scope", f"{case.portfolio_scope!r} is not one "
                                       f"of {', '.join(fam.PORTFOLIO_SCOPES)}"))
    if case.expected_outcome not in fam.OUTCOMES:
        add(Problem("expected_outcome", f"{case.expected_outcome!r} is not "
                                        f"one of {', '.join(fam.OUTCOMES)}"))

    # ---- what was asked ---------------------------------------------------
    turns = case.conversation_turns
    if not (case.question or "").strip() and not turns:
        add(Problem("question", "a case needs a question or a thread"))
    if turns:
        indices = [t.turn_index for t in turns]
        if indices != list(range(len(turns))):
            add(Problem("conversation_turns", "turn_index must run 0, 1, 2 "
                                              f"…; got {indices}"))
        if any(not (t.user_message or "").strip() for t in turns):
            add(Problem("conversation_turns", "every turn needs a message"))
        first = (turns[0].user_message or "").strip()
        asked = (case.question or "").strip()
        if asked and first and asked != first:
            add(Problem("question", "must match the first turn's message, or "
                                    "be left empty"))
        for turn in turns[1:]:
            if not (turn.conversation_action or "").strip():
                add(Problem("conversation_turns", f"turn {turn.turn_index} "
                                                  "needs a conversation "
                                                  "action"))

    # ---- what should happen -----------------------------------------------
    if case.expected_model_route and case.expected_model_route not in ROUTES:
        add(Problem("expected_model_route",
                    f"{case.expected_model_route!r} is not a governed route; "
                    "routes are roles, never provider model IDs"))
    if case.expected_effort and case.expected_effort not in EFFORTS:
        add(Problem("expected_effort", f"{case.expected_effort!r} is not one "
                                       f"of {', '.join(EFFORTS)}"))
    if case.expected_officer_level not in OFFICER_LEVELS:
        add(Problem("expected_officer_level", "officer levels run 1-4, or 0 "
                                              "for unconstrained"))

    # ---- objectives -------------------------------------------------------
    seen: set[str] = set()
    for objective in case.objectives:
        if not objective.id or not objective.text:
            add(Problem("objectives", "every objective needs an id and text"))
        elif objective.id in seen:
            add(Problem("objectives", f"duplicate objective id "
                                      f"{objective.id!r}"))
        seen.add(objective.id)
    if case.expected_outcome == fam.EXECUTE and not case.objectives:
        add(Problem("objectives", "a case expected to execute must say what "
                                  "it is asking for (§11)", fatal=False))

    # ---- the family's own rules -------------------------------------------
    if family is not None:
        if family.turns > 1 and len(turns) < family.turns:
            add(Problem("conversation_turns",
                        f"{family.id} is about what a later turn does with an "
                        f"earlier one; it needs at least {family.turns} turns"))
        if family.discourse and not case.same_turn_discourse.bound():
            add(Problem("same_turn_discourse",
                        f"{family.id} requires a local antecedent: every "
                        "referent must bind to a declared cohort (§10)"))
        if family.outcome and case.expected_outcome != family.outcome:
            add(Problem("expected_outcome",
                        f"{family.id} cases must expect {family.outcome}, "
                        f"not {case.expected_outcome}"))
        if family.scope and case.portfolio_scope != family.scope:
            add(Problem("portfolio_scope",
                        f"{family.id} cases must be scoped {family.scope}"))

    if not case.same_turn_discourse.bound() and case.same_turn_discourse.referents:
        add(Problem("same_turn_discourse",
                    "a referent points at a cohort that is not declared"))

    # ---- the outcome's own contracts --------------------------------------
    if case.expected_outcome == fam.CLARIFY and not case.clarification_contract:
        add(Problem("clarification_contract",
                    "a case expected to clarify must say what it asks"))
    if case.expected_outcome == fam.UNSUPPORTED and not case.abstention_contract:
        add(Problem("abstention_contract",
                    "a case expected to abstain must say what it declines "
                    "and why"))
    if (case.expected_outcome == fam.EXECUTE
            and not (case.analytical_plan_contract or case.method_contract
                     or case.analytical_ir_contract)):
        add(Problem("analytical_plan_contract",
                    "a case expected to execute must specify a plan, an IR or "
                    "a method", fatal=False))

    # ---- data ------------------------------------------------------------
    for name, required, forbidden in (
            ("datasets", case.required_datasets, case.forbidden_datasets),
            ("relationships", case.required_relationships,
             case.forbidden_relationships),
            ("tools", case.allowed_tools, case.forbidden_tools)):
        both = sorted(set(required) & set(forbidden))
        if both:
            add(Problem(f"forbidden_{name}", f"{', '.join(both)} is both "
                                             "required and forbidden"))

    if case.cost_budget < 0:
        add(Problem("cost_budget", "cannot be negative"))
    if case.latency_budget < 0:
        add(Problem("latency_budget", "cannot be negative"))

    # ---- §8: structure, not last quarter's numbers -------------------------
    if case.data_sensitivity == st.PUBLIC:
        prose = _text_of(case.result_contract, case.interpretation_contract,
                         case.description,
                         [t.expected_answer_behavior for t in turns])
        figures = _FIGURE.findall(prose)
        if figures:
            add(Problem("result_contract",
                        "a structure-only case must not carry portfolio "
                        f"figures ({', '.join(sorted(set(figures))[:3])}); "
                        "mark it DIAGNOSTIC if the value validates a method "
                        "(§8)"))

    # ---- governance --------------------------------------------------------
    if case.authoring_method not in st.AUTHORING_METHODS:
        add(Problem("authoring_method", f"{case.authoring_method!r} is not a "
                                        "known authoring method"))
    if case.data_sensitivity not in st.SENSITIVITIES:
        add(Problem("data_sensitivity", f"{case.data_sensitivity!r} is not "
                                        "one of "
                                        f"{', '.join(st.SENSITIVITIES)}"))
    if not st.known(case.review_status):
        add(Problem("review_status", f"{case.review_status!r} is not a known "
                                     "status"))
    if case.authoring_method == st.VARIANT and not case.cluster_id:
        add(Problem("cluster_id", "a variant must record the cluster it "
                                  "belongs to (§15)"))
    if case.fingerprint and case.fingerprint != fingerprint(case):
        add(Problem("fingerprint", "does not match the case's content"))

    return problems


def problems_blocking(case: TeachingCase) -> list[Problem]:
    return [p for p in validate(case) if p.fatal]


def valid(case: TeachingCase) -> bool:
    return not problems_blocking(case)


def resolve_status(case: TeachingCase) -> str:
    """The status the validators alone can put a case in.

    Never APPROVED — that needs a person, and `status.may_approve` is where
    the person is checked for. A case a validator cannot vouch for goes to
    SME_REVIEW_REQUIRED rather than being failed outright, which is §14's rule
    for variants applied to everything: a validator's doubt is a reason to ask
    somebody, not a reason to throw the case away.
    """
    found = validate(case)
    if any(p.fatal for p in found):
        return st.DRAFT
    if found:
        return st.SME_REVIEW_REQUIRED
    return st.AUTO_VALIDATED


def sealed(case: TeachingCase) -> TeachingCase:
    """The case with its fingerprint written in."""
    case.fingerprint = fingerprint(case)
    return case


__all__ = [
    "ADVERSARIAL", "COMPLEX", "DEMANDING", "DIFFICULTIES", "EFFORTS",
    "EXPERT", "EXTENSION_FIELDS", "FINGERPRINTED", "FOUNDATIONAL",
    "INTERMEDIATE", "OFFICER_LEVELS", "Objective", "Problem",
    "REQUIRED_FIELDS", "RISK_LEVELS", "ROUTES", "SCHEMA_VERSION", "Discourse",
    "TeachingCase", "Turn", "fingerprint", "problems_blocking",
    "resolve_status", "sealed", "valid", "validate",
]
