"""The canonical training case contract. §3, §5, §6.

A CANONICAL case is a distinct semantic or behavioural scenario with a
machine-verifiable specification of what a correct answer must do. It is not a
paraphrase, and a typo is not a scenario.

What a case records, and what it must not
-----------------------------------------
It records the SHAPE of a correct answer — which capability, which officer,
which agents, which datasets, which grain, which invariants must hold, what
may legitimately be clarified, and what a wrong-but-plausible answer would
look like.

It records **no portfolio figure**. §5: "Do not store current demo portfolio
numbers as reusable teaching truth." A stored figure is correct for one
quarter and wrong for every quarter after it, and a corpus full of them
becomes a corpus that must be regenerated whenever the data moves. Numerical
expectations are declared as an `independent_reference_spec` — a description
of how to compute the reference at evaluation time — and computed then.

The `forbidden` field is the one that earns its place. Every other field says
what a right answer looks like; this one says what a wrong-but-plausible
answer would look like, and that is the difference between a check and a
formality.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

CASE_SCHEMA_VERSION = "1.0.0"

# --------------------------------------------------------------- families

#: The eleven case families, with the minimum canonical count each must reach.
#: §3's distribution, as data rather than prose, so a test can assert it.
FAMILIES: dict[str, int] = {
    "DATA_DISCOVERY": 120,
    "SINGLE_DOMAIN": 150,
    "MULTI_DOMAIN": 180,
    "MULTI_TURN": 150,
    "COMPOUND": 120,
    "AGENTIC": 120,
    "PROJECT_WORKFLOW": 90,
    "AMBIGUITY": 120,
    "REGULATORY": 80,
    "PRESENTATION": 50,
    "SECURITY": 100,
}

FAMILY_MEANS: dict[str, str] = {
    "DATA_DISCOVERY": "The catalogue, the dictionary and governed "
                      "relationships. Answered from metadata, not by running "
                      "an analysis.",
    "SINGLE_DOMAIN": "One governed dataset, one measure, one grouping.",
    "MULTI_DOMAIN": "Two or more domains joined at a governed grain.",
    "MULTI_TURN": "A thread. Referents, carried scope, previous-result reuse.",
    "COMPOUND": "One message, several objectives. Every one must be answered "
                "or explicitly not answered.",
    "AGENTIC": "Officer selection, specialist selection and the task DAG.",
    "PROJECT_WORKFLOW": "Project scope, Risk Cases, review and approval.",
    "AMBIGUITY": "Clarification, abstention and the unsupported question.",
    "REGULATORY": "What a source says, as of a date, with a citation.",
    "PRESENTATION": "Chart choice, Trace, export and navigation.",
    "SECURITY": "Prompt injection, permission boundaries and tenant "
                "isolation.",
}

MINIMUM_CANONICAL = sum(FAMILIES.values())   # 1,280

#: §8's sealed holdout floor.
MINIMUM_HOLDOUT = 300

# ---------------------------------------------------------------- statuses

#: §6's five statuses, in the order a case moves through them.
AUTO_GENERATED = "AUTO_GENERATED"
AUTO_VALIDATED = "AUTO_VALIDATED"
SYSTEM_REFERENCE_VALIDATED = "SYSTEM_REFERENCE_VALIDATED"
HUMAN_REVIEWED = "HUMAN_REVIEWED"
HUMAN_APPROVED = "HUMAN_APPROVED"

STATUSES: tuple[str, ...] = (AUTO_GENERATED, AUTO_VALIDATED,
                             SYSTEM_REFERENCE_VALIDATED, HUMAN_REVIEWED,
                             HUMAN_APPROVED)

STATUS_MEANS: dict[str, str] = {
    AUTO_GENERATED: "Generated and not validated at all.",
    AUTO_VALIDATED: "Passed format and basic checks. Nothing about its "
                    "CONTENT has been established.",
    SYSTEM_REFERENCE_VALIDATED: "An independent deterministic reference "
                                "agreed with it. No person has read it.",
    HUMAN_REVIEWED: "A person read it and has not approved it.",
    HUMAN_APPROVED: "A person approved it.",
}

#: What each status may be used for in PRODUCTION retrieval. §6's policy,
#: stated as data so the runtime cannot drift from the document.
#:
#: SYSTEM_REFERENCE_VALIDATED is the interesting one. It may be retrieved, and
#: only under an explicit Administrator policy with a visible label - because
#: "a deterministic reference agreed" is real evidence and "nobody has read
#: this" is also true, and a client is entitled to know which they are looking
#: at.
RETRIEVABLE: dict[str, str] = {
    AUTO_GENERATED: "",
    AUTO_VALIDATED: "",
    SYSTEM_REFERENCE_VALIDATED:
        "only under an explicit Administrator policy, and labelled",
    HUMAN_REVIEWED: "",
    HUMAN_APPROVED: "yes",
}

#: Statuses that may be used to TUNE prompts and policies. Wider than
#: retrieval on purpose: tuning against a case whose reference was computed
#: deterministically is sound even when nobody has read the wording.
TUNABLE: frozenset[str] = frozenset({SYSTEM_REFERENCE_VALIDATED,
                                     HUMAN_APPROVED})


class CaseError(Exception):
    """A case that cannot be accepted, and why."""


# ------------------------------------------------------------- the contract


@dataclass
class Reference:
    """How to compute the expected answer INDEPENDENTLY, at evaluation time.

    §5 and §7. Never a stored figure: a `kind` naming the deterministic
    routine and the arguments it takes. The reference is recomputed whenever
    the case is evaluated, so the corpus does not go stale when the data
    moves.
    """

    kind: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    #: How close is close enough, for a numeric comparison.
    tolerance: float = 0.0
    #: What the reference establishes, in one sentence.
    means: str = ""

    @property
    def independent(self) -> bool:
        """Whether this case can be settled without asking a model."""
        return bool(self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "args": dict(self.args),
                "tolerance": self.tolerance, "means": self.means}


@dataclass
class Case:
    """One canonical training case. §5's contract."""

    case_id: str = ""
    case_family: str = ""
    #: A cluster within the family. The SPLIT is by cluster, not by case, so a
    #: paraphrase can never land on the other side of the holdout boundary
    #: from the case it paraphrases.
    cluster: str = ""
    case_type: str = "canonical"
    source: str = "system_generated"
    status: str = AUTO_GENERATED
    criticality: str = "normal"
    difficulty: str = "INTERMEDIATE"
    language: str = "en"
    jurisdiction: str = "SA"
    portfolio_scope: str = "corporate"

    #: The request. `thread` carries the earlier turns for a multi-turn case.
    question: str = ""
    thread: tuple[str, ...] = ()

    #: What a correct answer must settle. One entry per objective; a compound
    #: request has several and every one must be answered or refused.
    objectives: tuple[str, ...] = ()

    expected_capability: str = ""
    expected_conversation_action: str = ""
    expected_officer_level: int | None = None
    expected_agents: tuple[str, ...] = ()
    expected_task_dag: dict[str, Any] = field(default_factory=dict)
    expected_tools: tuple[str, ...] = ()
    expected_data_domains: tuple[str, ...] = ()
    expected_datasets: tuple[str, ...] = ()
    expected_relationships: tuple[str, ...] = ()
    expected_period_rule: str = ""
    expected_population: str = ""
    expected_grain: str = ""
    expected_filters: dict[str, Any] = field(default_factory=dict)
    expected_operations: tuple[str, ...] = ()
    expected_method: str = ""
    expected_plan_properties: dict[str, Any] = field(default_factory=dict)
    required_invariants: tuple[str, ...] = ()
    expected_result_shape: str = ""
    expected_visualization: str = ""
    expected_answer_contract: str = ""
    expected_paragraph_band: str = ""
    expected_clarification: bool = False
    expected_abstention: bool = False

    #: What a wrong-but-plausible answer would do. The field that turns a
    #: check into a discriminator.
    forbidden: tuple[str, ...] = ()

    reference: Reference = field(default_factory=Reference)
    regulatory_citations: tuple[str, ...] = ()
    tenant: str = ""
    required_role: str = ""
    tags: tuple[str, ...] = ()
    version: int = 1
    schema_version: str = CASE_SCHEMA_VERSION

    #: Set on a generated variant, naming the canonical case it came from.
    #: Empty on a canonical case, and that is how the two are counted apart.
    variant_of: str = ""
    variant_kind: str = ""

    @property
    def canonical(self) -> bool:
        return not self.variant_of

    @property
    def fingerprint(self) -> str:
        """Content hash over what the case ASSERTS, not over its prose.

        Two cases that expect the same behaviour of the same question are the
        same case however differently they are worded, and this is what finds
        that.
        """
        payload = json.dumps({
            "question": self.question.strip().lower(),
            # The earlier turns are part of what the case asserts: "and the
            # quarter before that?" means something different after "ECL by
            # sector" than after "arrears by bucket", and a fingerprint that
            # ignored the thread would collapse two real cases into one.
            "thread": [t.strip().lower() for t in self.thread],
            "family": self.case_family,
            "capability": self.expected_capability,
            "officer": self.expected_officer_level,
            "datasets": sorted(self.expected_datasets),
            "grain": self.expected_grain,
            "objectives": [o.strip().lower() for o in self.objectives],
            "clarify": self.expected_clarification,
            "abstain": self.expected_abstention,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        body = {
            "case_id": self.case_id, "case_family": self.case_family,
            "cluster": self.cluster, "case_type": self.case_type,
            "source": self.source, "status": self.status,
            "criticality": self.criticality, "difficulty": self.difficulty,
            "language": self.language, "jurisdiction": self.jurisdiction,
            "portfolio_scope": self.portfolio_scope,
            "question": self.question, "thread": list(self.thread),
            "objectives": list(self.objectives),
            "expected_capability": self.expected_capability,
            "expected_conversation_action": self.expected_conversation_action,
            "expected_officer_level": self.expected_officer_level,
            "expected_agents": list(self.expected_agents),
            "expected_task_dag": dict(self.expected_task_dag),
            "expected_tools": list(self.expected_tools),
            "expected_data_domains": list(self.expected_data_domains),
            "expected_datasets": list(self.expected_datasets),
            "expected_relationships": list(self.expected_relationships),
            "expected_period_rule": self.expected_period_rule,
            "expected_population": self.expected_population,
            "expected_grain": self.expected_grain,
            "expected_filters": dict(self.expected_filters),
            "expected_operations": list(self.expected_operations),
            "expected_method": self.expected_method,
            "expected_plan_properties": dict(self.expected_plan_properties),
            "required_invariants": list(self.required_invariants),
            "expected_result_shape": self.expected_result_shape,
            "expected_visualization": self.expected_visualization,
            "expected_answer_contract": self.expected_answer_contract,
            "expected_paragraph_band": self.expected_paragraph_band,
            "expected_clarification": self.expected_clarification,
            "expected_abstention": self.expected_abstention,
            "forbidden": list(self.forbidden),
            "independent_reference_spec": self.reference.to_dict(),
            "regulatory_citations": list(self.regulatory_citations),
            "tenant": self.tenant, "required_role": self.required_role,
            "tags": list(self.tags), "version": self.version,
            "schema_version": self.schema_version,
            "variant_of": self.variant_of, "variant_kind": self.variant_kind,
            "fingerprint": self.fingerprint,
        }
        return body


#: Words that would mean a portfolio FIGURE has been stored as teaching truth.
#: Checked rather than trusted, because the temptation to paste a number into
#: an expectation is strongest exactly where it does most damage.
_FIGURE_FIELDS = ("expected_result_shape", "expected_answer_contract",
                  "expected_population")


def validate(case: Case) -> list[str]:
    """Everything wrong with this case. Empty means it may be AUTO_VALIDATED.

    Format and structure only — this establishes nothing about whether the
    expectation is CORRECT, which is what `SYSTEM_REFERENCE_VALIDATED` is for
    and why the two statuses are separate.
    """
    problems: list[str] = []

    if not case.case_id:
        problems.append("no case_id")
    if case.case_family not in FAMILIES:
        problems.append(f"unknown family {case.case_family!r}")
    if not case.cluster:
        problems.append("no cluster: the split is by cluster, and a case "
                        "without one cannot be kept out of the holdout")
    if not case.question.strip():
        problems.append("no question")
    if case.status not in STATUSES:
        problems.append(f"unknown status {case.status!r}")

    if not case.objectives:
        problems.append("no objectives: a case that does not say what a "
                        "correct answer must settle cannot score one")

    if case.expected_clarification and case.expected_abstention:
        problems.append("expects both a clarification and an abstention; "
                        "they are different answers")

    if case.expected_officer_level is not None and \
            case.expected_officer_level not in (1, 2, 3, 4):
        problems.append(f"officer level {case.expected_officer_level} is not "
                        "one of the four")

    if not case.forbidden:
        problems.append("no forbidden behaviour: without it the case cannot "
                        "tell a right answer from a convincing substitute")

    # §5: no stored portfolio figures.
    for name in _FIGURE_FIELDS:
        text = str(getattr(case, name, "") or "")
        if any(ch.isdigit() for ch in text) and _looks_like_money(text):
            problems.append(
                f"{name} contains what looks like a portfolio figure. "
                "Declare an independent_reference_spec instead: a stored "
                "number is right for one quarter and wrong afterwards")
    return problems


def _looks_like_money(text: str) -> bool:
    """A number with a scale word beside it. Deliberately narrow.

    "top 5", "four quarters" and "Stage 2" are structure, not figures, and a
    check that rejected them would reject most of the corpus.
    """
    lowered = text.lower()
    scales = ("million", "billion", "sar", "usd", "m ", "bn", "%")
    return any(scale in lowered for scale in scales) and any(
        ch.isdigit() for ch in lowered)
