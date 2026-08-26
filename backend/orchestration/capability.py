"""
What kind of request is this?

The single most consequential thing the old Ask experience got wrong was
assuming every question was a request for a number. "What data do you have about
borrower ratings?" was scored against credit-risk intents, matched nothing well,
and returned a portfolio summary. "How is ratings connected to IFRS 9?" matched
the string `ifrs9` and returned a Stage 2 distribution. Both are *correct
figures for questions nobody asked*, which is the failure this product exists to
prevent.

So nothing reaches the numerical path until something has decided what kind of
request it is. That decision is this module, and it produces a structured
document — never prose that is later parsed.

Only ANALYSIS executes a calculation. Everything else is answered from governed
metadata, and its Trace says so rather than manufacturing a mathematical query
that never ran.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------- the kinds


class Capability:
    """What CreditProbe was asked to do.

    Grouped by what answers them: the DATA_* family is answered from Data
    Builder, METHOD_* from Analysis Studio, ANALYSIS from the runtime, and the
    *_ACTION family changes a workspace object rather than reading anything.
    """

    DATA_DISCOVERY = "DATA_DISCOVERY"
    DATA_INSPECTION = "DATA_INSPECTION"
    DATA_DICTIONARY = "DATA_DICTIONARY"
    DATA_QUALITY = "DATA_QUALITY"
    DATA_RELATIONSHIP = "DATA_RELATIONSHIP"

    METHOD_DISCOVERY = "METHOD_DISCOVERY"
    METHOD_EXPLANATION = "METHOD_EXPLANATION"
    METHOD_CREATION = "METHOD_CREATION"

    ANALYSIS = "ANALYSIS"

    PROJECT_ACTION = "PROJECT_ACTION"
    INVESTIGATION_ACTION = "INVESTIGATION_ACTION"
    ANALYSIS_ACTION = "ANALYSIS_ACTION"

    CLARIFICATION = "CLARIFICATION"


ALL: tuple[str, ...] = (
    Capability.DATA_DISCOVERY, Capability.DATA_INSPECTION,
    Capability.DATA_DICTIONARY, Capability.DATA_QUALITY,
    Capability.DATA_RELATIONSHIP, Capability.METHOD_DISCOVERY,
    Capability.METHOD_EXPLANATION, Capability.METHOD_CREATION,
    Capability.ANALYSIS, Capability.PROJECT_ACTION,
    Capability.INVESTIGATION_ACTION, Capability.ANALYSIS_ACTION,
    Capability.CLARIFICATION,
)

#: The only capability that computes a figure.
COMPUTES = frozenset({Capability.ANALYSIS})

#: Answered from Data Builder, with no engine call.
FROM_DATA_BUILDER = frozenset({
    Capability.DATA_DISCOVERY, Capability.DATA_INSPECTION,
    Capability.DATA_DICTIONARY, Capability.DATA_QUALITY,
    Capability.DATA_RELATIONSHIP,
})

FROM_STUDIO = frozenset({
    Capability.METHOD_DISCOVERY, Capability.METHOD_EXPLANATION,
    Capability.METHOD_CREATION,
})

LABELS: dict[str, str] = {
    Capability.DATA_DISCOVERY: "What data is available",
    Capability.DATA_INSPECTION: "Looking at a dataset",
    Capability.DATA_DICTIONARY: "What a field means",
    Capability.DATA_QUALITY: "Data quality and coverage",
    Capability.DATA_RELATIONSHIP: "How datasets connect",
    Capability.METHOD_DISCOVERY: "What methods are available",
    Capability.METHOD_EXPLANATION: "How a method works",
    Capability.METHOD_CREATION: "Building a method",
    Capability.ANALYSIS: "Analysis",
    Capability.PROJECT_ACTION: "Project action",
    Capability.INVESTIGATION_ACTION: "Investigation action",
    Capability.ANALYSIS_ACTION: "Analysis action",
    Capability.CLARIFICATION: "Needs one more thing",
}


@dataclass(frozen=True)
class Reading:
    """The structured reading of one request.

    This is what both the model and the offline planner produce, and what the
    Trace records as its first governed node. Nothing downstream reads the
    question string again to decide anything.
    """

    intent: str
    objective: str = ""
    #: How this message relates to the one before it. See
    #: backend/orchestration/conversation for the enum and what each means.
    conversation_action: str = ""
    #: Governed concepts named or implied — "exposure at default", "rating".
    concepts: tuple[str, ...] = ()
    #: The measures to report, where the request distinguishes them from the
    #: concepts it merely mentions. "Rank those by ECL" concerns ratings and
    #: stages too; only ECL is the measure.
    metrics: tuple[str, ...] = ()
    #: Concepts the request cannot be answered without. Used by the guardrail
    #: and by validation scoring; a superset of `metrics`.
    required_concepts: tuple[str, ...] = ()
    #: Named things: sectors, customers, stages, regions.
    entities: tuple[dict[str, str], ...] = ()
    #: Phrases that point back at an earlier turn — "these", "those five".
    entity_references: tuple[str, ...] = ()
    #: Explicit governed restrictions, as {field, value}. Distinct from
    #: `entities`, which are named things the request is *about*.
    filters: tuple[dict[str, str], ...] = ()
    #: What to break the answer down by.
    dimensions: tuple[str, ...] = ()
    #: One row per what — customer, facility, sector.
    grain: str = ""
    #: Governed data domains the request plausibly needs.
    candidate_domains: tuple[str, ...] = ()
    #: Analysis Studio methods that may already answer this.
    candidate_methods: tuple[str, ...] = ()
    #: Datasets the request is *about*, where it named or implied one.
    datasets: tuple[str, ...] = ()
    #: sum | average | count | rank | compare | distribution | list | none
    operation: str = "none"
    computation_required: bool = False
    period_requirement: str = "none"   # none | point_in_time | two_period
    periods: tuple[str, ...] = ()
    confidence: float = 0.0
    reasoning: str = ""
    #: Set when the reading is not usable as it stands.
    clarification: str = ""
    alternatives: tuple[str, ...] = ()
    #: Which planner produced this, for the Trace and the mode banner.
    source: str = "offline"
    model: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.intent, self.intent)

    @property
    def computes(self) -> bool:
        return self.intent in COMPUTES

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent, "intent_label": self.label,
            "objective": self.objective,
            "conversation_action": self.conversation_action,
            "concepts": list(self.concepts),
            "metrics": list(self.metrics),
            "required_concepts": list(self.required_concepts),
            "entity_references": list(self.entity_references),
            "filters": [dict(f) for f in self.filters],
            "grain": self.grain,
            "candidate_domains": list(self.candidate_domains),
            "candidate_methods": list(self.candidate_methods),
            "entities": [dict(e) for e in self.entities],
            "dimensions": list(self.dimensions),
            "datasets": list(self.datasets),
            "operation": self.operation,
            "computation_required": self.computation_required,
            "period_requirement": self.period_requirement,
            "periods": list(self.periods),
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "clarification": self.clarification,
            "alternatives": list(self.alternatives),
            "source": self.source, "model": self.model,
        }


# ------------------------------------------------------- the JSON schema
#
# This is the contract the model answers through. It is defined here rather than
# beside the prompt because the offline planner has to satisfy the same shape,
# and two definitions of one contract is how they drift.

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string", "enum": list(ALL),
            "description": (
                "What KIND of request this is. Only ANALYSIS computes a figure. "
                "A question about what data exists is DATA_DISCOVERY; about how "
                "two datasets connect is DATA_RELATIONSHIP; about what a field "
                "means is DATA_DICTIONARY; about coverage, nulls or how many "
                "periods exist is DATA_QUALITY."),
        },
        "objective": {
            "type": "string",
            "description": "What the user wants, in one sentence, in their terms.",
        },
        "conversation_action": {
            "type": "string",
            "enum": ["NEW_REQUEST", "CONTINUE", "MODIFY_PREVIOUS",
                     "ENRICH_PREVIOUS", "CLARIFY"],
            "description": (
                "How this message relates to the conversation so far. "
                "NEW_REQUEST: a fresh subject. CONTINUE: a new question scoped "
                "to what the previous turn established (its population, "
                "period, filters). MODIFY_PREVIOUS: change the analysis that "
                "just ran — a different cut, order, filter or measure. "
                "ENRICH_PREVIOUS: keep the previous rows and add a column. "
                "CLARIFY: the user is answering a question CreditProbe asked. "
                "When the message refers back with \"these\", \"those\", "
                "\"them\" or \"the previous result\", it is NEVER "
                "NEW_REQUEST."),
        },
        "concepts": {
            "type": "array", "items": {"type": "string"},
            "description": (
                "Governed credit concepts named or implied, using the concept "
                "labels supplied in the context — never column names."),
        },
        "metrics": {
            "type": "array", "items": {"type": "string"},
            "description": (
                "The governed concepts that are the MEASURES to report, using "
                "the concept labels supplied in the context. A subset of "
                "`concepts`: a request may involve a concept as a condition "
                "without reporting it."),
        },
        "required_concepts": {
            "type": "array", "items": {"type": "string"},
            "description": "Every governed concept the request cannot be "
                           "answered without, measures and conditions alike.",
        },
        "entity_references": {
            "type": "array", "items": {"type": "string"},
            "description": (
                "Phrases in the message that point back at an earlier turn — "
                "\"these\", \"those five\", \"them\", \"the previous "
                "result\". List them verbatim; CreditProbe resolves them "
                "against the identities the previous run returned. Do NOT "
                "invent the ids yourself."),
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["field", "value"],
            },
            "description": "Explicit governed restrictions, using only the "
                           "dimension names and values supplied in the context.",
        },
        "grain": {
            "type": "string",
            "description": "One row per what — customer, facility or a "
                           "dimension name. Empty when the request does not say.",
        },
        "candidate_domains": {
            "type": "array", "items": {"type": "string"},
            "description": "Governed data domains this plausibly needs.",
        },
        "candidate_methods": {
            "type": "array", "items": {"type": "string"},
            "description": "Ids of Analysis Studio methods supplied in the "
                           "context that may already answer this.",
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "description": "sector | region | segment | stage | "
                                            "customer | rating | product_type"},
                    "value": {"type": "string"},
                },
                "required": ["kind", "value"],
            },
            "description": "Named things to filter or look up. Use the exact "
                           "governed values supplied in the context.",
        },
        "dimensions": {
            "type": "array", "items": {"type": "string"},
            "description": "What to break the answer down by, e.g. sector.",
        },
        "datasets": {
            "type": "array", "items": {"type": "string"},
            "description": "Governed dataset names the request is about, where "
                           "it names or clearly implies them.",
        },
        "operation": {
            "type": "string",
            "enum": ["sum", "average", "count", "rank", "compare",
                     "distribution", "list", "none"],
        },
        "computation_required": {
            "type": "boolean",
            "description": "True only when a figure must be calculated from data.",
        },
        "period_requirement": {
            "type": "string", "enum": ["none", "point_in_time", "two_period"],
        },
        "periods": {
            "type": "array", "items": {"type": "string"},
            "description": "Reporting periods named or implied, using the exact "
                           "period labels supplied in the context.",
        },
        "confidence": {
            "type": "number",
            "description": "0 to 1. Below 0.55 CreditProbe will ask rather than run.",
        },
        "reasoning": {
            "type": "string",
            "description": "One or two sentences on why this reading. A summary "
                           "for an auditor, not your deliberation.",
        },
        "clarification": {
            "type": "string",
            "description": "If the request cannot be answered as it stands, the "
                           "ONE question to ask back. Otherwise empty.",
        },
        "alternatives": {
            "type": "array", "items": {"type": "string"},
            "description": "Where a term could mean more than one governed "
                           "figure, the readings not taken.",
        },
    },
    "required": ["intent", "objective", "confidence"],
}


#: Below this the router asks rather than running. Chosen so a reading that is
#: merely incomplete still runs (the planner will ask its own question), while
#: one that is genuinely a guess never reaches the data.
MIN_CONFIDENCE = 0.55


def from_payload(payload: dict[str, Any], *, source: str,
                 model: str = "") -> Reading:
    """A Reading from whatever the model returned, coerced rather than trusted.

    The schema constrains the model, but a schema is a request and not a
    guarantee: an unknown intent, a string where an array belongs, or a
    confidence of 4 all have to land somewhere sensible rather than throwing
    three layers down.
    """
    intent = str(payload.get("intent") or "").strip().upper()
    if intent not in ALL:
        intent = Capability.ANALYSIS if payload.get("computation_required") \
            else Capability.CLARIFICATION

    def strings(key: str) -> tuple[str, ...]:
        value = payload.get(key)
        if isinstance(value, str):
            value = [value]
        return tuple(str(v).strip() for v in (value or []) if str(v).strip())

    entities: list[dict[str, str]] = []
    for raw in payload.get("entities") or []:
        if isinstance(raw, dict) and raw.get("value"):
            entities.append({"kind": str(raw.get("kind") or "unknown"),
                             "value": str(raw["value"])})
        elif isinstance(raw, str) and raw.strip():
            entities.append({"kind": "unknown", "value": raw.strip()})

    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    operation = str(payload.get("operation") or "none").strip().lower()
    if operation not in {"sum", "average", "count", "rank", "compare",
                         "distribution", "list", "none"}:
        operation = "none"

    requirement = str(payload.get("period_requirement") or "none").strip().lower()
    if requirement not in {"none", "point_in_time", "two_period"}:
        requirement = "none"

    filters: list[dict[str, str]] = []
    for raw in payload.get("filters") or []:
        if isinstance(raw, dict) and raw.get("field") and raw.get("value"):
            filters.append({"field": str(raw["field"]),
                            "value": str(raw["value"])})

    action = str(payload.get("conversation_action") or "").strip().upper()

    return Reading(
        intent=intent,
        objective=str(payload.get("objective") or "").strip(),
        conversation_action=action,
        concepts=strings("concepts"),
        metrics=strings("metrics"),
        required_concepts=strings("required_concepts") or strings("concepts"),
        entities=tuple(entities),
        entity_references=strings("entity_references"),
        filters=tuple(filters),
        grain=str(payload.get("grain") or "").strip().lower(),
        candidate_domains=strings("candidate_domains"),
        candidate_methods=strings("candidate_methods"),
        dimensions=strings("dimensions"),
        datasets=strings("datasets"),
        operation=operation,
        computation_required=bool(payload.get("computation_required"))
        or intent == Capability.ANALYSIS,
        period_requirement=requirement,
        periods=strings("periods"),
        confidence=confidence,
        reasoning=str(payload.get("reasoning") or "").strip(),
        clarification=str(payload.get("clarification") or "").strip(),
        alternatives=strings("alternatives"),
        source=source, model=model,
    )


# ------------------------------------------------------- offline recognition
#
# What follows is NOT the old phrase-to-analysis map. It does not select an
# analysis and it does not decide what to compute. It decides one thing — what
# KIND of request this is — and it exists because a product with no model key
# must still route a data question to Data Builder rather than to the engine.
#
# The signals are shape-of-request signals ("what data", "how is X connected
# to Y", "what does X mean"), not credit-risk phrases, and the whole table is
# about forty lines. Everything downstream of the routing decision is semantic.


@dataclass(frozen=True)
class _Signal:
    intent: str
    pattern: str
    weight: int = 3


_SIGNALS: tuple[_Signal, ...] = (
    # ---- what data exists
    _Signal(Capability.DATA_DISCOVERY,
            r"\bwhat (?:kind of )?data\b|\bwhat datasets?\b|\bwhich datasets?\b", 8),
    _Signal(Capability.DATA_DISCOVERY,
            r"\b(?:do you|have you|is there|are there)\b.{0,30}\bdata\b", 6),
    _Signal(Capability.DATA_DISCOVERY,
            r"\bwhat(?:'s| is)? available\b|\bwhat can you (?:see|access|read)\b", 6),
    _Signal(Capability.DATA_DISCOVERY, r"\bdata do you have\b", 9),
    _Signal(Capability.DATA_DISCOVERY,
            r"\bwhat (?:domains?|sources?|tables?)\b", 6),

    # ---- how things connect
    _Signal(Capability.DATA_RELATIONSHIP,
            r"\bhow (?:is|are|does|do)\b.{0,60}\b(?:connect|link|relate|join)", 9),
    _Signal(Capability.DATA_RELATIONSHIP,
            r"\b(?:connected|linked|related|joined) to\b", 8),
    _Signal(Capability.DATA_RELATIONSHIP,
            r"\bjoin (?:key|path)\b|\brelationship between\b", 8),
    _Signal(Capability.DATA_RELATIONSHIP,
            r"\bhow (?:would|do) (?:you|i|we) join\b", 8),

    # ---- what a field means
    _Signal(Capability.DATA_DICTIONARY,
            r"\bwhat does\b.{0,40}\bmean\b|\bdefinition of\b", 8),
    _Signal(Capability.DATA_DICTIONARY,
            r"\bhow (?:is|are|do you) (?:[\w-]+ ){0,4}defined?\b", 7),
    _Signal(Capability.DATA_DICTIONARY,
            r"\bwhat is meant by\b|\bmeaning of\b|\bwhat counts as\b", 7),
    _Signal(Capability.DATA_DICTIONARY,
            r"\bwhat fields?\b|\bwhich fields?\b|\bwhat columns?\b", 7),

    # ---- coverage and quality
    _Signal(Capability.DATA_QUALITY,
            r"\bhow many (?:quarters|periods|years|rows|records)\b", 8),
    _Signal(Capability.DATA_QUALITY,
            r"\bhow much history\b|\bwhat periods?\b|\bwhich periods?\b", 7),
    # "coverage" alone is a trap: ECL coverage is a governed MEASURE, and a
    # request for "average ECL coverage by rating grade" was routed to the data
    # quality handler and answered with catalogue metadata.
    _Signal(Capability.DATA_QUALITY,
            r"\bdata quality\b|\bdata coverage\b|\bcoverage of the (?:data|"
            r"dataset|catalogue)\b|\bmissing (?:values|data)\b|\bnulls?\b"
            r"|\bhow complete\b|\bpopulated\b", 7),

    # ---- looking at one dataset
    _Signal(Capability.DATA_INSPECTION,
            r"\bshow me the\b.{0,30}\b(?:dataset|table|file)\b", 7),
    _Signal(Capability.DATA_INSPECTION,
            r"\bsample (?:of|rows)\b|\bfirst \d+ rows\b|\bpreview\b", 7),

    # ---- methods
    _Signal(Capability.METHOD_DISCOVERY,
            r"\bwhat (?:methods?|analyses|analysis|models?)\b.{0,20}\b(?:do you|are|exist|available)", 8),
    _Signal(Capability.METHOD_DISCOVERY,
            r"\bwhich (?:analytical )?methods?\b|\blist (?:the )?methods?\b"
            r"|\bwhat (?:analytical )?methods?\b", 7),
    _Signal(Capability.METHOD_DISCOVERY,
            r"\b(?:methods?|analyses)\b.{0,20}\b(?:exist|available|do you have)\b", 8),
    _Signal(Capability.METHOD_EXPLANATION,
            r"\bhow (?:do you|does creditprobe|is)\b.{0,40}\bcalculat", 8),
    _Signal(Capability.METHOD_EXPLANATION,
            r"\bwhat methodology\b|\bhow does the\b.{0,30}\bmethod\b", 7),
    _Signal(Capability.METHOD_CREATION,
            r"\b(?:create|build|make|define) (?:a |an )?(?:new )?method\b", 8),

    # ---- workspace actions
    _Signal(Capability.PROJECT_ACTION,
            r"\b(?:create|start|open|add to) (?:a )?project\b", 8),
    _Signal(Capability.INVESTIGATION_ACTION,
            r"\b(?:save|rename|share|export) (?:this )?investigation\b", 8),
    _Signal(Capability.ANALYSIS_ACTION,
            r"\bsave (?:this )?(?:as a )?(?:method|analysis)\b", 8),
)

# Signals that an actual figure is wanted. These do not select an analysis;
# they distinguish "tell me about the data" from "compute something from it".
#
# Split by how much each is worth, because the two are used for different
# decisions. STRONG signals are unambiguous requests to compute over the book,
# and only they may override a data-shaped reading. WEAK signals — a metric
# name, "how many" — are ordinary English that appears just as readily in a
# question about the catalogue: "how many quarters of DPD are there" is a
# coverage question, and reading it as a count is exactly the mistake this
# module exists to stop.

_ANALYTICAL_STRONG = (
    r"\b(?:top|largest|biggest|smallest|bottom|worst|best|rank|ranked)\b",
    r"\b(?:by sector|by region|by segment|by stage|by rating|by product|"
    r"breakdown|split)\b",
    r"\b(?:increase|decrease|rose|fell|grew|declin|worsen|improv|deteriorat|"
    r"downgrade|upgrade|movement|trend)\w*\b",
    r"\b(?:which|show|list|find|identify)\b.{0,40}\b(?:customers?|borrowers?|"
    r"facilities|accounts?|exposures?)\b",
    r"\bcompare\b|\bversus\b|\bvs\b",
    r"\btotal\b|\bsum of\b|\baggregate\b",
    # Per-group aggregation, which is an analysis however it is phrased.
    # "For each rating grade, show average ECL coverage…" names no dataset and
    # asks for three figures grouped by a dimension; without this it scored as
    # a coverage question and came back as catalogue metadata.
    r"\bfor each\b|\bper (?:sector|region|segment|stage|grade|rating|"
    r"customer|borrower|facility|product)\b",
    r"\b(?:average|mean|median|total|sum)\b.{0,40}\b(?:by|per|for each)\b",
    r"\b(?:by|per|for each)\b.{0,40}\b(?:average|mean|median|total|sum)\b",
)

# "mean" is deliberately absent: in "what does DSCR mean" it is a verb, and
# counting it as the average routed a dictionary question into the engine.
_ANALYTICAL_WEAK = (
    r"\b(?:sum|average|median|count|how many|how much)\b",
    r"\b(?:ead|ecl|pd|lgd|dpd|dscr|rwa|npl)\b",
    r"\bexposure\b|\bbalance\b|\bprovision\b",
)


def recognise(question: str) -> tuple[str, float, str]:
    """The kind of request, without a model.

    Returns (intent, confidence, why). Deliberately conservative: where the
    shape signals are weak but the question clearly wants a figure, it returns
    ANALYSIS, because the analytical path is the one that asks its own
    clarifying questions and refuses what it cannot read.
    """
    text = (question or "").strip().lower()
    if not text:
        return Capability.CLARIFICATION, 0.0, "Nothing was asked."

    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for signal in _SIGNALS:
        if re.search(signal.pattern, text):
            scores[signal.intent] = scores.get(signal.intent, 0) + signal.weight
            hits.setdefault(signal.intent, []).append(signal.pattern)

    strong = sum(1 for pattern in _ANALYTICAL_STRONG if re.search(pattern, text))
    weak = sum(1 for pattern in _ANALYTICAL_WEAK if re.search(pattern, text))

    if scores:
        intent = max(scores, key=lambda k: scores[k])
        best = scores[intent]
        # A data-shaped question that also unambiguously asks for a figure is an
        # analysis: "show me the top ten borrowers in the ratings data" names a
        # dataset but wants a ranking. Only STRONG evidence may override — a
        # metric name is not enough, or every question mentioning EAD would be
        # dragged into the engine.
        # ...unless the OBJECT of the sentence is the data itself. "Which
        # datasets do you have for exposure?" matches the ranking shape —
        # "which … exposure" — and is a catalogue question, not a ranking.
        about_the_catalogue = re.search(
            r"\bdatasets?\b|\bwhat data\b|\bfields?\b|\bcolumns?\b|"
            r"\btables?\b|\bsources?\b", text)
        if (intent in FROM_DATA_BUILDER and strong >= 1
                and not about_the_catalogue
                and intent != Capability.DATA_RELATIONSHIP):
            return (Capability.ANALYSIS, 0.7,
                    "It asks about data, but it asks for a figure computed from it.")
        confidence = min(0.95, 0.45 + 0.06 * best)
        return intent, confidence, f"Recognised as {LABELS[intent].lower()}."

    if strong or weak:
        return (Capability.ANALYSIS, min(0.9, 0.5 + 0.1 * (strong * 2 + weak)),
                "It asks for a figure computed from governed data.")

    return (Capability.ANALYSIS, 0.45,
            "No clear signal; treated as an analysis, which will ask if it "
            "cannot read the question.")


__all__ = [
    "ALL",
    "COMPUTES",
    "FROM_DATA_BUILDER",
    "FROM_STUDIO",
    "LABELS",
    "MIN_CONFIDENCE",
    "SCHEMA",
    "Capability",
    "Reading",
    "from_payload",
    "recognise",
]
