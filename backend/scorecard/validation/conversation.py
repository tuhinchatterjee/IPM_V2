"""Reading a validator's question, and choosing a tool to answer it. §21.

The rule this module exists to keep
-------------------------------------
**A language model may decide WHICH question to answer. It never decides what
the answer is.**

Every number that reaches a validator through this surface came out of
`runner.run`, which came out of `backend/scorecard/metrics.py`. The model's
entire job is to turn "is the SME scorecard still ranking risk?" into
`scv_run_category(model_id="sme_champion", category="discrimination")`. It
does not see a row, it does not write a query, and it does not phrase a
figure — the sentence beside every result is the runner's own `detail`, which
was written to be quoted into a report unedited.

That is not a limitation to be worked around later. A validation environment
where an LLM computes, restates or rounds a statistic is one whose numbers
cannot be reproduced, and reproducibility is the entire value of the exercise.

Why a deterministic reader at all
-----------------------------------
`read()` resolves a question without any provider. Three reasons, in order of
how much they matter:

1. **It has to work with no provider configured.** A bank network that refuses
   egress is a supported deployment, not a degraded one, and a validation
   module that becomes a set of buttons without an API key is a validation
   module nobody can use where it is most needed.
2. **It is the guardrail on the model.** When a provider IS configured, its
   choice is checked against the same registry: an unknown tool, an unknown
   test id, an unknown category or a model id outside the three is refused
   here and the deterministic reading is used instead. A hallucinated tool
   call cannot become an executed one.
3. **It is testable.** A fixed question maps to a fixed tool call, in every
   process, with no network. The suite pins the mapping.

The model is asked only when the deterministic reader is unsure, and its
answer is accepted only where the reader would otherwise have refused.

Out of domain
---------------
A question about IFRS 9 staging, a borrower, a covenant or the corporate book
is not answered approximately here. `read()` returns None and the caller
refuses with `agent.refuse_out_of_domain`, which says where the answer does
live. That is the same boundary `backend/scorecard/domains` enforces in the
data layer, stated one level earlier so the conversation is honest rather than
merely safe.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.scorecard.validation import agent
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry

logger = logging.getLogger(__name__)

CONVERSATION_VERSION = "1.0.0"

DETERMINISTIC = "DETERMINISTIC READER"
MODEL_CHOSEN = "MODEL-SELECTED TOOL, REGISTRY-CHECKED"

#: How the answer's figures were produced. Stated on every response, because
#: the one thing a reader must never have to guess is whether a number was
#: computed or written.
FIGURES_ARE_COMPUTED = (
    "Every figure in this answer was computed by the validation runner over "
    "the governed population. No figure was produced, restated or rounded by "
    "a language model.")


# ============================================================ what was asked

@dataclass(frozen=True)
class Reading:
    """One question, resolved to one tool call."""

    tool_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    #: How the tool was chosen. Shown to the user rather than kept internal:
    #: "the deterministic reader matched DISC-AUC" and "a model chose this
    #: tool and the registry accepted it" are different provenances and a
    #: validator is entitled to know which one they are reading.
    source: str = DETERMINISTIC
    #: What in the question led here. One clause, for the same reason.
    because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"tool_id": self.tool_id, "parameters": dict(self.parameters),
                "source": self.source, "because": self.because}


# ======================================================== the vocabulary map

#: Words that name one of the three scorecards. Ordered longest-first at use,
#: so "retail behaviour" is not matched as "retail".
_SCORECARD_WORDS: tuple[tuple[str, str], ...] = (
    ("saudi sme", "sme_champion"),
    ("sme scorecard", "sme_champion"),
    ("sme", "sme_champion"),
    ("retail application", "retail_application_champion"),
    ("application scorecard", "retail_application_champion"),
    ("origination", "retail_application_champion"),
    ("retail behaviour", "retail_behaviour_champion"),
    ("retail behavioral", "retail_behaviour_champion"),
    ("retail behavioural", "retail_behaviour_champion"),
    ("behaviour scorecard", "retail_behaviour_champion"),
    ("behavioural scorecard", "retail_behaviour_champion"),
    ("behavioral scorecard", "retail_behaviour_champion"),
)

#: Statistic names a validator actually types, mapped to the test that
#: computes them. Not an exhaustive synonym list and not trying to be: this is
#: the set that appears in a validation conversation, and anything outside it
#: falls through to the category match or to the model.
_TEST_WORDS: tuple[tuple[str, str], ...] = (
    ("area under the curve", "DISC-AUC"),
    ("auc", "DISC-AUC"),
    ("roc", "DISC-AUC"),
    ("gini", "DISC-GINI"),
    ("accuracy ratio", "DISC-GINI"),
    ("kolmogorov", "DISC-KS"),
    ("ks statistic", "DISC-KS"),
    ("ks", "DISC-KS"),
    ("rank order", "DISC-RANK"),
    ("rank inversion", "DISC-RANK"),
    ("lift", "DISC-LIFT"),
    ("observed over expected", "CAL-OE"),
    ("observed to expected", "CAL-OE"),
    ("o/e", "CAL-OE"),
    ("brier", "CAL-BRIER"),
    ("calibration slope", "CAL-SLOPE"),
    ("population stability", "STAB-PSI"),
    ("psi", "STAB-PSI"),
    ("characteristic stability", "STAB-CSI"),
    ("csi", "STAB-CSI"),
    ("information value", "VAR-IV"),
    ("iv", "VAR-IV"),
    ("weight of evidence", "VAR-WOE"),
    ("woe", "VAR-WOE"),
    ("monotonic", "VAR-WOE"),
    ("override", "USE-OVERRIDE-RATE"),
    ("cut-off", "USE-CUTOFF"),
    ("cut off", "USE-CUTOFF"),
    ("cutoff", "USE-CUTOFF"),
    ("swap set", "CC-SWAPSET"),
    ("swapset", "CC-SWAPSET"),
    ("bootstrap", "ROB-BOOTSTRAP"),
    ("confidence interval", "ROB-BOOTSTRAP"),
    ("replicate", "IMPL-REPLICATE"),
    ("implementation", "IMPL-REPLICATE"),
    ("maturity", "DATA-MATURITY"),
    ("matured", "DATA-MATURITY"),
    ("missing", "DATA-MISSING"),
    ("duplicate", "DATA-DUPLICATES"),
)

#: Words that name a category. The categories' own titles are matched too;
#: these are the extra phrasings.
_CATEGORY_WORDS: tuple[tuple[str, str], ...] = (
    ("discriminat", test_registry.DISCRIMINATION),
    ("rank risk", test_registry.DISCRIMINATION),
    ("ranking risk", test_registry.DISCRIMINATION),
    ("ranks risk", test_registry.DISCRIMINATION),
    ("rank order risk", test_registry.DISCRIMINATION),
    ("separat", test_registry.DISCRIMINATION),
    ("calibrat", test_registry.CALIBRATION),
    ("predicted default rate", test_registry.CALIBRATION),
    ("stability", test_registry.STABILITY),
    ("drift", test_registry.STABILITY),
    ("shift", test_registry.STABILITY),
    ("robust", test_registry.ROBUSTNESS),
    ("sensitiv", test_registry.ROBUSTNESS),
    ("variable", test_registry.VARIABLES),
    ("characteristic", test_registry.VARIABLES),
    ("binning", test_registry.VARIABLES),
    ("override", test_registry.USAGE),
    ("policy", test_registry.USAGE),
    ("use test", test_registry.USAGE),
    ("segment", test_registry.SEGMENTATION),
    ("challenger", test_registry.CHAMPION_CHALLENGER),
    ("champion", test_registry.CHAMPION_CHALLENGER),
    ("conceptual", test_registry.CONCEPTUAL),
    ("design", test_registry.CONCEPTUAL),
    ("documentation", test_registry.CONCEPTUAL),
    ("data quality", test_registry.DATA_QUALITY),
    ("representative", test_registry.DATA_QUALITY),
    ("implementation", test_registry.IMPLEMENTATION),
)

#: Subjects this module does not answer. Matched only when nothing in the
#: question names a scorecard, a test or a category — a question that says
#: "the SME scorecard's IFRS 9 stage distribution" is about the SME scorecard
#: and gets a refusal from the tool, not from here.
_OTHER_DOMAINS: tuple[str, ...] = (
    "ifrs 9", "ifrs9", "ecl", "expected credit loss", "stage 2", "stage 3",
    "provision", "impairment", "covenant", "collateral", "borrower",
    "corporate", "counterparty", "beneficial owner", "ownership",
    "early warning", "watchlist", "exposure at default", "lgd",
    "liquidity", "cash flow", "rating transition", "sicr",
)

#: Anything that reads as an instruction to leave the tools behind. Refused
#: before a provider is asked, because a refusal that depends on a model
#: declining is not a refusal.
_NOT_A_TOOL: tuple[tuple[str, str], ...] = (
    ("sql", "arbitrary SQL or Python"),
    ("query the database", "arbitrary SQL or Python"),
    ("python", "arbitrary SQL or Python"),
    ("raw data", "raw rows"),
    ("raw rows", "raw rows"),
    ("row level", "raw rows"),
    ("record level", "raw rows"),
    ("change the limit", "changing a limit or a model"),
    ("set the limit", "changing a limit or a model"),
    ("adjust the threshold", "changing a limit or a model"),
    ("sign off", "issuing a report or an opinion"),
    ("approve the model", "issuing a report or an opinion"),
    ("certify", "issuing a report or an opinion"),
)


def _words(question: str) -> str:
    return re.sub(r"\s+", " ", (question or "").strip().lower())


def which_scorecard(question: str) -> str:
    """The model id the question names, or empty.

    Longest phrase first, so "retail behaviour scorecard" does not resolve to
    the application scorecard on the strength of the word "retail".
    """
    text = _words(question)
    for phrase, model_id in sorted(_SCORECARD_WORDS,
                                   key=lambda p: -len(p[0])):
        if phrase in text:
            return model_id
    return ""


def which_test(question: str) -> str:
    """The test id the question names, or empty."""
    text = _words(question)
    # An explicit id wins over any synonym: somebody who typed STAB-CSI meant
    # STAB-CSI, whatever else the sentence contains.
    for test in test_registry.TESTS:
        if test.test_id.lower() in text:
            return test.test_id
    for phrase, test_id in sorted(_TEST_WORDS, key=lambda p: -len(p[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return test_id
    return ""


def which_category(question: str) -> str:
    """The category the question names, or empty."""
    text = _words(question)
    for category in test_registry.CATEGORIES:
        if category.replace("_", " ") in text:
            return category
    for entry in test_registry.CATEGORY_DEFINITIONS:
        if entry.title.lower() in text:
            return entry.key
    for phrase, category in sorted(_CATEGORY_WORDS, key=lambda p: -len(p[0])):
        if phrase in text:
            return category
    return ""


def names_a_scorecard_subject(question: str) -> bool:
    """Whether anything in the question is about scorecard validation."""
    text = _words(question)
    if which_scorecard(question) or which_test(question):
        return True
    if which_category(question):
        return True
    return any(word in text for word in
               ("scorecard", "validation", "model risk", "validate",
                "score band", "cbuae", "mms", "mmg"))


def refuses(question: str) -> str:
    """The thing this module will not do, if the question asks for one."""
    text = _words(question)
    for phrase, what in _NOT_A_TOOL:
        if phrase in text:
            return what
    return ""


def out_of_domain(question: str) -> bool:
    """Whether the question belongs to a different surface."""
    if names_a_scorecard_subject(question):
        return False
    text = _words(question)
    return any(word in text for word in _OTHER_DOMAINS)


# ================================================================== the read

def read(question: str, *, model_id: str = "") -> Reading | None:
    """Resolve a question to one tool call, deterministically.

    `model_id` is the scorecard the screen is already showing. It is used only
    when the question does not name one — a validator looking at the SME
    scorecard who asks "what is the AUC?" means that one, and asking them
    which scorecard they meant would be pedantry. A question that DOES name a
    scorecard overrides the screen, because the words on the page are what the
    person actually asked for.
    """
    text = _words(question)
    if not text:
        return None

    wanted = which_scorecard(question) or model_id
    test_id = which_test(question)
    category = which_category(question)

    # --- questions about the module itself, before anything is run ---------
    if any(phrase in text for phrase in
           ("which scorecards", "what scorecards", "list the scorecards",
            "what models", "which models")):
        return Reading(agent.LIST_MODELS,
                       because="the question asks what is validated here")

    if any(phrase in text for phrase in
           ("what tests", "which tests", "list the tests",
            "what can you test", "what do you test")):
        return Reading(agent.LIST_TESTS,
                       {"category": category} if category else {},
                       because=("the question asks what the registry "
                                "contains"))

    # "What does X measure" is a registry question, not a run. Answering it by
    # running the test would spend a minute of computation to explain a
    # definition, and would attach a number to a question that did not ask for
    # one.
    if test_id and any(phrase in text for phrase in
                       ("what does", "what is the definition", "explain",
                        "how is it calculated", "how do you calculate",
                        "what does it mean", "tell me about")):
        return Reading(agent.EXPLAIN_TEST, {"test_id": test_id},
                       because=f"the question asks what {test_id} measures")

    if any(phrase in text for phrase in
           ("which periods", "what periods", "which months", "what months",
            "how much data", "is it matured", "has it matured",
            "outcome window")):
        return Reading(agent.PERIODS, {"model_id": wanted},
                       because="the question asks what data exists")

    # A question that NAMES a test is about that test, whatever else it
    # contains. "What is the worst CSI?" resolved to the findings engine
    # because it contains the word "worst" — an answer about eight tests to a
    # question about one, and the reader had no way to tell that had happened.
    if not test_id and any(phrase in text for phrase in
                           ("findings", "weaknesses", "what is wrong",
                            "what's wrong", "biggest problem", "worst",
                            "concerns")):
        return Reading(agent.FINDINGS, {"model_id": wanted},
                       because="the question asks what the results add up to")

    if any(phrase in text for phrase in
           ("cbuae", "regulator", "mms", "mmg", "supervisor",
            "regulatory coverage", "which requirements")):
        return Reading(agent.REGULATORY, {"model_id": wanted},
                       because=("the question asks which supervisory "
                                "expectations the evidence speaks to"))

    if any(phrase in text for phrase in
           ("draft the report", "draft a report", "write the report",
            "validation report", "generate the report")):
        return Reading(agent.DRAFT_REPORT, {"model_id": wanted},
                       because="the question asks for the report draft")

    # --- questions that need a number -------------------------------------
    if test_id:
        return Reading(agent.RUN_TEST,
                       {"model_id": wanted, "test_id": test_id},
                       because=f"the question names {test_id}")

    if category:
        return Reading(agent.RUN_CATEGORY,
                       {"model_id": wanted, "category": category},
                       because=(f"the question is a "
                                f"{category.replace('_', ' ')} question"))

    return None


# ========================================================== the model's turn

#: What the provider is allowed to return. Deliberately small: a tool id and
#: its parameters. There is no field for a sentence, a number or an
#: interpretation, so there is nothing for the model to fill one into.
CHOICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool_id": {
            "type": "string",
            "enum": [tool.tool_id for tool in agent.TOOLS],
            "description": "Which governed tool answers this question.",
        },
        "model_id": {
            "type": "string",
            "enum": [""] + [m.model_id for m in model_registry.all_models()],
            "description": "Which of the three scorecards, or empty.",
        },
        "test_id": {
            "type": "string",
            "description": "A registered test id, or empty.",
        },
        "category": {
            "type": "string",
            "enum": [""] + list(test_registry.CATEGORIES),
            "description": "A validation category, or empty.",
        },
        "in_scope": {
            "type": "boolean",
            "description": ("False when the question is not about validating "
                            "one of the three scorecards."),
        },
        "because": {
            "type": "string",
            "description": "One clause naming what in the question led here.",
        },
    },
    "required": ["tool_id", "in_scope", "because"],
}


def _system() -> str:
    tools = "\n".join(
        f"- {t.tool_id}: {t.purpose} "
        f"(requires: {', '.join(t.required) or 'nothing'})"
        for t in agent.TOOLS)
    scorecards = "\n".join(
        f"- {m.model_id}: {m.name}, {m.portfolio}"
        for m in model_registry.all_models())
    return (
        "You route questions inside CreditProbe's Scorecard Validation "
        "module. You choose ONE tool. You never state a figure, a verdict or "
        "an interpretation: the tool computes those and the product renders "
        "them.\n\n"
        f"Scope: {agent.SCOPE}\n"
        f"Out of scope: {agent.OUT_OF_SCOPE}\n\n"
        f"The scorecards:\n{scorecards}\n\n"
        f"The tools:\n{tools}\n\n"
        "Set in_scope false when the question is about anything other than "
        "validating one of those three scorecards. Do not guess a scorecard "
        "the question does not name and the screen has not selected — leave "
        "model_id empty and the product will ask.")


def _accept(document: dict[str, Any]) -> Reading | None:
    """Check the model's choice against the registry before it can run.

    Everything the provider returned is treated as a claim. A tool id that is
    not one of the nine, a test id that is not one of the forty-eight, a
    category that is not one of the eleven, or a scorecard that is not one of
    the three is rejected here — so a hallucinated tool call is refused rather
    than executed, and the deterministic reading is used instead.
    """
    if not document.get("in_scope", False):
        return None
    tool_id = str(document.get("tool_id") or "")
    if tool_id not in agent.BY_ID:
        return None

    parameters: dict[str, Any] = {}
    model_id = str(document.get("model_id") or "")
    if model_id:
        if model_id not in {m.model_id for m in model_registry.all_models()}:
            return None
        parameters["model_id"] = model_id

    test_id = str(document.get("test_id") or "")
    if test_id:
        found = test_registry.resolve(test_id)
        if found is None:
            return None
        parameters["test_id"] = found.test_id

    category = str(document.get("category") or "")
    if category:
        if category not in test_registry.CATEGORIES:
            return None
        parameters["category"] = category

    # A parameter the tool does not accept is dropped rather than passed on:
    # `agent._check` would refuse the whole call, and refusing a question the
    # deterministic reader could have answered is a worse outcome than
    # ignoring a field the model added.
    tool = agent.BY_ID[tool_id]
    parameters = {k: v for k, v in parameters.items() if k in tool.parameters}

    return Reading(tool_id, parameters, source=MODEL_CHOSEN,
                   because=str(document.get("because") or "")[:240])


def choose(question: str, *, model_id: str = "") -> Reading | None:
    """The deterministic reading, or a provider's if the reader is unsure.

    The order is not negotiable. The deterministic reader is asked first and
    its answer is used when it has one, so a configured provider cannot change
    what a question that already resolves means. The provider is consulted
    only where the alternative is refusing to answer at all.
    """
    plain = read(question, model_id=model_id)
    if plain is not None:
        return plain
    if out_of_domain(question):
        return None

    from backend.llm import get_provider

    provider = get_provider()
    if not provider.configured:
        return None

    try:
        result = provider.structured(
            system=_system(),
            prompt=(f"Question: {question}\n"
                    f"Scorecard currently on screen: {model_id or 'none'}"),
            schema=CHOICE_SCHEMA,
            tool_name="choose_validation_tool",
            tool_description="Route one validation question to one tool.",
            max_tokens=400,
            purpose="reading",
            role="reading",
        )
    except Exception:  # noqa: BLE001 - a provider failure is not an answer
        logger.warning("scorecard validation: the provider could not route "
                       "the question; falling back to a refusal")
        return None

    document = getattr(result, "document", None) or getattr(result, "data", None)
    if not isinstance(document, dict):
        return None

    accepted = _accept(document)
    if accepted is None:
        return None
    # The screen's scorecard fills a gap the model left, exactly as it does
    # for the deterministic reader.
    if "model_id" in agent.BY_ID[accepted.tool_id].required \
            and not accepted.parameters.get("model_id") and model_id:
        accepted.parameters["model_id"] = model_id
    return accepted


# ================================================================== answering

def answer(question: str, *, model_id: str = "") -> dict[str, Any]:
    """One question in, one governed tool result out.

    The return shape is the same whatever happened — answered, clarified or
    refused — so a client has one thing to render and no branch on which it
    can accidentally show a refusal as an answer.
    """
    body: dict[str, Any] = {
        "conversation_version": CONVERSATION_VERSION,
        "question": question,
        "answered": False,
        "figures": FIGURES_ARE_COMPUTED,
        "scope": agent.SCOPE,
    }

    denied = refuses(question)
    if denied:
        # The same shape `agent.refuse_out_of_domain` returns: `refused` is a
        # flag, and what was refused is its own field. Two refusals with the
        # same key meaning different things — a boolean here and a sentence
        # there — is how a client ends up rendering the word "true" to a
        # validator.
        body["refusal"] = {
            "refused": True,
            "what": denied,
            "why": agent.NO_TOOL_FOR.get(denied, ""),
            "scope": agent.SCOPE,
            "question": question,
        }
        return body

    if out_of_domain(question):
        body["refusal"] = agent.refuse_out_of_domain(question)
        return body

    reading = choose(question, model_id=model_id)
    if reading is None:
        # A question that names a scorecard but no measurable subject is not
        # out of domain — it is under-specified, and the two need different
        # answers. Refusing it would tell a validator their question was about
        # the wrong thing when it was about the right thing too vaguely.
        wanted = which_scorecard(question) or model_id
        if wanted and names_a_scorecard_subject(question):
            body["clarification"] = {
                "clarification_required": True,
                "question": "Which part of the validation?",
                "because": (
                    "Forty-eight tests run against this scorecard, in eleven "
                    "categories that ask different questions. Running all of "
                    "them to answer a general question would take a minute "
                    "and bury the answer."),
                "options": [
                    {"category": entry.key, "title": entry.title,
                     "asks": entry.question}
                    for entry in test_registry.CATEGORY_DEFINITIONS],
            }
            return body
        body["refusal"] = agent.refuse_out_of_domain(question)
        return body

    body["reading"] = reading.to_dict()
    try:
        body["result"] = agent.invoke(reading.tool_id, **reading.parameters)
        body["answered"] = True
    except agent.Clarify as clarification:
        body["clarification"] = clarification.to_dict()
    except (agent.ToolDenied, agent.ToolUnknown) as refused_by_agent:
        body["refusal"] = {"refused": True,
                           "what": str(refused_by_agent),
                           "scope": agent.SCOPE,
                           "question": question}
    return body


__all__ = [
    "CONVERSATION_VERSION", "DETERMINISTIC", "FIGURES_ARE_COMPUTED",
    "MODEL_CHOSEN", "Reading", "answer", "choose", "out_of_domain", "read",
    "names_a_scorecard_subject", "refuses", "which_category",
    "which_scorecard", "which_test",
]
