"""
Reading a request, with a model when there is one and without when there is not.

Both paths produce the same `Reading`, and both are treated with the same
scepticism afterwards: a reading is a claim about what was asked, never a claim
about what is true. Nothing here touches data.

The model's job here is narrow on purpose. It is not asked to plan the
calculation — that is the next stage — only to say what kind of request this is,
which governed concepts it involves, which entities it names, and how sure it
is. Keeping the two apart means a wrong plan and a wrong reading fail
differently and are debuggable separately, and it means the cheap question
("is this even an analysis?") is answered before the expensive one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.analyst import cost as _cost
from backend.llm import LLMError, get_provider
from backend.orchestration import capability as cap
from backend.orchestration import conversation as cv
from backend.orchestration import guardrail as gr
from backend.orchestration import movement as mv
from backend.orchestration import routing as rt
from backend.orchestration.context import GovernedContext, retrieve

logger = logging.getLogger(__name__)

TOOL_NAME = "record_reading"

SYSTEM = """You are the request router for CreditProbe AI, a credit-risk \
intelligence platform used by banks.

Your ONLY job is to say what KIND of request this is and what governed concepts \
and entities it involves. You do NOT plan the calculation and you NEVER state a \
figure — a deterministic engine computes every number.

Route by what the user wants, not by which words appear:

- DATA_DISCOVERY     what data exists at all ("what data do you have about X")
- DATA_INSPECTION    look at one dataset's contents
- DATA_DICTIONARY    what a field or term means, what fields a dataset has
- DATA_QUALITY       coverage, history length, missing values, how many periods
- DATA_RELATIONSHIP  how two datasets connect, join keys, grain alignment
- METHOD_DISCOVERY   which analytical methods exist
- METHOD_EXPLANATION how a named method works
- METHOD_CREATION    build or save a method
- ANALYSIS           compute a figure from governed data
- PROJECT_ACTION / INVESTIGATION_ACTION / ANALYSIS_ACTION  change a workspace object
- CLARIFICATION      the request cannot be acted on as it stands

Critical distinctions:
- "How is ratings connected to IFRS 9?" is DATA_RELATIONSHIP, NOT an analysis of \
IFRS 9 stages.
- "What data do you have about ratings?" is DATA_DISCOVERY, NOT a portfolio summary.
- "How many quarters of DPD are there?" is DATA_QUALITY, NOT a count of anything.
- "How many customers are in Stage 2?" IS an ANALYSIS — it counts rows in data.

Use ONLY the governed concept labels, dataset names, dimension values and period \
labels supplied in the context. Never invent a column name, a customer or a sector.

CONVERSATION

When a CONVERSATION SO FAR block is present, this message is part of a thread \
and you MUST read it in that light.

- Set `conversation_action` on every reading.
- A message that refers back — "these", "those", "them", "those five", "the \
previous result", "same period", "that analysis" — is NEVER NEW_REQUEST. Put \
the referring phrase in `entity_references` and let CreditProbe resolve it \
against the identities the previous run returned. Never invent the ids.
- "Show only the five largest", "rank those by X instead", "replace X with Y" \
are MODIFY_PREVIOUS. "Add their latest rating", "also show X" are \
ENRICH_PREVIOUS.
- A follow-up inherits the previous turn's period, filters, dimension and \
grain unless it changes them. Do not re-ask for what the thread has settled.
- A genuinely new subject — a question about the catalogue, a different book — \
is NEW_REQUEST even mid-thread.

Set `clarification` ONLY when you genuinely cannot proceed — for example when a \
term maps to two different governed figures and the choice changes the answer. \
Do not ask for a period the user did not need to give: the planner resolves \
"latest" and "the latest year" itself, and asking for a window the governed \
default already covers is a worse answer than giving the default and saying so.

Be honest about `confidence`. A confident answer to the wrong question is the \
worst outcome this system can produce."""


def _prompt(question: str, context: GovernedContext,
            state: cv.ConversationState | None = None,
            memory: Any = None, *, note: str = "") -> str:
    """The governed context, compact. Metadata only — never a row of data.

    The conversation brief goes FIRST, before the catalogue. A follow-up is
    understood by what just happened rather than by the field list, and a model
    reading a long prompt weights the opening more heavily than the middle.
    """
    lines: list[str] = []

    # The typed working memory first, then what the last analysis settled. A
    # follow-up about a field set is unreadable without the first and unhelped
    # by the second, and the order is what a model weights.
    if memory is not None and not getattr(memory, "empty", True):
        lines.append(memory.brief())
        lines.append("")

    if state is not None and not state.empty:
        lines.append(state.brief())
        lines.append("")

    lines.append("GOVERNED DATASETS (name · grain · what it is for):")
    for d in context.datasets:
        auth = (f" · authoritative for {', '.join(d.authoritative_for)}"
                if d.authoritative_for else "")
        lines.append(f"  {d.name} · {d.grain} · {d.purpose}{auth}")
        lines.append(f"      periods: {d.period_count} "
                     f"({d.periods[0] if d.periods else 'n/a'}"
                     f"..{d.latest_period or 'n/a'})")
        shown = [f["name"] for f in d.fields[:18]]
        lines.append(f"      fields: {', '.join(shown)}"
                     + (" …" if len(d.fields) > 18 else ""))
    if context.other_datasets:
        lines.append(f"  (also available, ask if needed: "
                     f"{', '.join(context.other_datasets)})")

    lines.append("\nGOVERNED CREDIT CONCEPTS (use these labels):")
    for c in context.concepts:
        note = " (ordinal)" if c.get("is_ordinal") else ""
        lines.append(f"  {c['label']}{note} — carried by "
                     f"{', '.join(c['carried_by'])}")

    if context.relationships:
        lines.append("\nDECLARED RELATIONSHIPS:")
        for r in context.relationships[:20]:
            lines.append(f"  {r.describe()}")

    if context.methods:
        lines.append("\nRELEVANT ANALYSIS STUDIO METHODS:")
        for m in context.methods:
            tick = " [certified]" if m.is_certified else ""
            lines.append(f"  {m.id}: {m.name}{tick} — {m.definition[:110]}")

    lines.append(f"\nREPORTING PERIODS: {', '.join(context.periods)}")
    lines.append(f"LATEST PERIOD: {context.latest_period}")
    lines.append("\nFILTER DIMENSIONS AND PERMITTED VALUES:")
    for name, values in context.dimensions.items():
        shown = values if len(values) <= 18 else values[:18] + ["…"]
        lines.append(f"  {name}: {', '.join(str(v) for v in shown)}")

    lines.append(f"\nREQUEST: {question}")
    if note:
        lines.append("\n" + note)
    return "\n".join(lines)


@dataclass(frozen=True)
class Read:
    """A reading, and the evidence about how much to trust it."""

    reading: cap.Reading
    verdict: gr.Verdict
    #: Model calls made to produce this — one, or two when a repair ran.
    calls: int = 0
    duration_ms: int = 0
    #: Set when the live path was attempted and failed. Sanitised, and shown to
    #: the user rather than swallowed: an answer produced offline while a key is
    #: configured must say so.
    degraded_reason: str = ""
    #: Which route and model served this reading. None when nothing was called.
    decision: Any = None

    @property
    def live(self) -> bool:
        return self.reading.source in ("llm", "guardrail") and self.calls > 0


def read(question: str, *, context: GovernedContext | None = None,
         state: cv.ConversationState | None = None,
         memory: Any = None, decision: Any = None) -> Read:
    """What kind of request this is, checked before it is acted on.

    Three stages, and each is recorded rather than inferred:

      1. the live model reads the request against the governed catalogue and the
         conversation so far;
      2. the governed semantic reader checks that reading for a cross-family
         contradiction;
      3. one repair call where they disagree, and the safe reading where they
         still do.

    With no provider — or with one that fails — stage 1 is the deterministic
    reader, stages 2 and 3 have nothing to check, and `degraded_reason` says
    which of those two situations applies. It never raises: an unreadable
    question is a conversation, and an unreachable provider is a status.
    """
    import time

    started = time.perf_counter()
    context = context or retrieve(question)
    provider = get_provider()

    if not provider.configured:
        offline = read_request_offline(question, context=context)
        return Read(reading=offline, verdict=gr.Verdict(outcome=gr.UNCHECKED),
                    duration_ms=int((time.perf_counter() - started) * 1000))

    # Which model reads this. Decided before the call rather than after, and
    # recorded whichever way it goes: an answer whose route nobody can see is
    # an answer nobody can reproduce.
    if decision is None:
        decision = rt.decide(question, continuation=None, memory=memory)

    try:
        result = provider.structured(
            system=SYSTEM,
            prompt=_prompt(question, context, state, memory),
            schema=cap.SCHEMA,
            tool_name=TOOL_NAME,
            tool_description=(
                "Record how you have read this request. Call this exactly "
                "once. Do not compute anything."),
            max_tokens=1600,
            purpose="reading",
            # The route chose the role AND its model. Both travel with the
            # call, so the telemetry records which configured role actually
            # answered rather than leaving it to be inferred later.
            model=getattr(decision, "model", "") or "",
            role=getattr(decision, "role", "") or "",
            effort=getattr(decision, "effort", "") or "",
        )
        _cost.note_result(result, purpose="reading",
                          role=getattr(decision, "role", "") or "router")
    except LLMError as e:
        _cost.note_failure(purpose="reading",
                           role=getattr(decision, "role", "") or "router",
                           model=getattr(decision, "model", "") or "")
        return _degraded(question, context, started, str(e))
    except Exception as e:  # noqa: BLE001 - an outage must not 500
        return _degraded(question, context, started, str(e))

    reading = _sanitised(cap.from_payload(result.data, source="llm",
                                          model=result.model), context)
    verdict = gr.check(question, reading)
    calls = 1

    if verdict.conflict:
        repaired = _repair(question, context, state, reading, verdict)
        if repaired is not None:
            calls = 2
        reading, verdict = gr.settle(question, reading, verdict,
                                     repaired=repaired)

    return Read(reading=reading, verdict=verdict, calls=calls,
                decision=decision,
                duration_ms=int((time.perf_counter() - started) * 1000))


def _repair(question: str, context: GovernedContext,
            state: cv.ConversationState | None, reading: cap.Reading,
            verdict: gr.Verdict) -> cap.Reading | None:
    """One re-read, with the conflict stated. Never more than one.

    A second repair would be a negotiation, and a model that has not been
    convinced by the evidence in the first note will not be convinced by the
    same note again — it would only cost the user another few seconds before
    the same outcome.
    """
    provider = get_provider()
    try:
        result = provider.structured(
            system=SYSTEM,
            prompt=_prompt(question, context, state,
                           note=gr.repair_note(question, reading, verdict)),
            schema=cap.SCHEMA,
            tool_name=TOOL_NAME,
            tool_description=("Record your re-read of this request. Call this "
                              "exactly once."),
            max_tokens=1600,
            purpose="repair",
            role="critic",
        )
        _cost.note_result(result, purpose="repair", role="critic")
    except Exception as e:  # noqa: BLE001 - a failed repair just means "reject"
        _cost.note_failure(purpose="repair", role="critic")
        logger.info("The repair call failed for %r: %s", question[:70], e)
        return None
    return _sanitised(cap.from_payload(result.data, source="llm",
                                       model=result.model), context)


def _degraded(question: str, context: GovernedContext, started: float,
              reason: str) -> Read:
    """The offline reading, labelled as a degradation rather than a mode.

    A key is configured and the model did not answer. The reading is still
    produced — refusing to answer at all would be worse — but the answer, the
    Trace and the mode banner all say the live path failed, so nobody reads a
    deterministic reading as the product's full intelligence.
    """
    import time

    from backend.llm import telemetry

    logger.warning("The live reading failed for %r; using the governed "
                   "semantic reader. Reason: %s", question[:70],
                   telemetry.sanitise(reason))
    return Read(
        reading=read_request_offline(question, context=context),
        verdict=gr.Verdict(outcome=gr.UNCHECKED),
        duration_ms=int((time.perf_counter() - started) * 1000),
        degraded_reason=telemetry.sanitise(reason),
    )


def read_request(question: str, *,
                 context: GovernedContext | None = None) -> cap.Reading:
    """The reading alone, for callers that do not need the evidence."""
    return read(question, context=context).reading


def read_request_offline(question: str, *,
                         context: GovernedContext | None = None) -> cap.Reading:
    """The reading CreditProbe can produce with no model.

    Shape recognition for the capability, then the governed concept and entity
    resolvers for the content. It is not a phrase-to-analysis map: nothing here
    selects what to compute, and every concept it names came from the governed
    catalogue rather than from a table of anticipated questions.
    """
    from backend.orchestration import concepts as cx
    from backend.orchestration.entities import resolve_entities

    context = context or retrieve(question)
    intent, confidence, why = cap.recognise(question)

    known = {d.name: {f["name"] for f in d.fields} for d in context.datasets}
    reading = cx.read_concepts(question, known=known,
                               catalogue=_catalogue_or_none())
    found = [m.concept.label for m in reading.matches]

    entities = resolve_entities(question, context)
    dimensions = _dimensions(question, context)
    requirement = _period_requirement(question, intent)
    periods = _periods(question, context, requirement)

    return cap.Reading(
        intent=intent,
        objective=question.strip(),
        concepts=tuple(found),
        entities=tuple(entities),
        dimensions=tuple(dimensions),
        datasets=tuple(sorted({m.dataset for m in reading.matches})),
        operation=_operation(question),
        computation_required=intent in cap.COMPUTES,
        period_requirement=requirement,
        periods=tuple(periods),
        confidence=confidence,
        reasoning=why,
        source="offline",
    )


def _catalogue_or_none() -> Any:
    from backend.data_access import get_catalog

    try:
        return get_catalog()
    except Exception:
        return None


def _sanitised(reading: cap.Reading, context: GovernedContext) -> cap.Reading:
    """Drop anything the model named that the catalogue does not have.

    A hallucinated dataset or sector must never reach the planner. Silently
    dropping is right here rather than refusing: the planner re-resolves
    concepts and entities against the catalogue anyway, and a reading that lost
    one invented name is still a better reading than none.
    """
    import dataclasses

    known_datasets = {d.name for d in context.datasets} | set(context.other_datasets)
    datasets = tuple(d for d in reading.datasets if d in known_datasets)

    permitted = {k: {str(v).lower() for v in vals}
                 for k, vals in context.dimensions.items()}
    entities = tuple(
        e for e in reading.entities
        if e["kind"] not in permitted
        or str(e["value"]).lower() in permitted[e["kind"]]
    )

    periods = tuple(p for p in reading.periods if p in context.periods)
    dropped = (len(reading.datasets) - len(datasets)
               + len(reading.entities) - len(entities)
               + len(reading.periods) - len(periods))
    if dropped:
        logger.info("Dropped %d name(s) the catalogue does not carry.", dropped)
    return dataclasses.replace(reading, datasets=datasets, entities=entities,
                               periods=periods)


# ------------------------------------------------------- offline helpers


_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("rank", r"\b(?:top|largest|biggest|smallest|bottom|worst|best|"
             r"rank|ranked|five|ten|\d+)\b.{0,25}\b(?:by|customers?|borrowers?)\b"),
    ("rank", r"\b(?:top|largest|biggest|smallest|bottom)\b"),
    # One vocabulary, in `movement`. The private list this used to carry read
    # "movement" and not "moved", so the same question compiled to a comparison
    # or to a level depending on which spelling the user reached for.
    ("compare", rf"\b(?:{mv.CHANGE})\b"),
    ("distribution", r"\b(?:distribution|breakdown|split|by sector|by region|"
                     r"by segment|by stage|by rating)\b"),
    ("average", r"\b(?:average|mean of|median)\b"),
    ("count", r"\bhow many\b|\bnumber of\b|\bcount\b"),
    ("sum", r"\b(?:total|sum|aggregate|how much)\b"),
    ("list", r"\b(?:which|show|list|find|identify)\b"),
)


def _operation(question: str) -> str:
    import re

    # Masked by the same rule the period requirement uses. "Which of these
    # moved to Stage 3?" is a list of accounts that crossed a boundary, not a
    # comparison of a measure across two dates, and reading it as one produced
    # "0.00 stage migration in Stage 3" where a list of names belonged.
    text = mv.without_migration((question or "").lower())
    for name, pattern in _OPERATIONS:
        if re.search(pattern, text):
            return name
    return "none"


def _dimensions(question: str, context: GovernedContext) -> list[str]:
    """Which governed dimension the answer should be broken down by."""
    import re

    text = (question or "").lower()
    out: list[str] = []
    for name in context.dimensions:
        if re.search(rf"\bby {re.escape(name)}\b|\bper {re.escape(name)}\b"
                     rf"|\bacross {re.escape(name)}s?\b", text):
            out.append(name)
    return out


def _periods(question: str, context: GovernedContext,
             requirement: str = "two_period") -> list[str]:
    """The periods the question named, in the shape the requirement needs.

    A point-in-time question gets ONE period — the close. "In the latest
    quarter" reads as a window because the period reader is built for
    comparisons, and handing both ends of that window to a single-period plan
    would report the opening quarter as though it were the answer.
    """
    from backend.orchestration.periods import read_period_intent

    read = read_period_intent(question, context.periods)
    both = [p for p in (read.from_period, read.to_period) if p]
    if requirement == "two_period":
        return both
    return both[-1:]


#: Phrases that describe the FUTURE. A comparison window is retrospective by
#: definition - it needs two periods that have both happened - so a movement
#: word inside one of these is not asking for one.
#:
#: "the 10 borrowers with the highest probability of credit deterioration over
#: the next 12 months" was planned as a two-period comparison because it
#: contains "deteriorat". It is a forward-looking LIKELIHOOD at one date, and
#: the answer that came back compared the portfolio's PD across two historical
#: quarters - a different question, with no borrower list in it at all. §3.
#: Compiled on first use, because `re` is imported inside the function.
_FORWARD = None


def _period_requirement(question: str, intent: str) -> str:
    import re

    global _FORWARD
    if _FORWARD is None:
        _FORWARD = re.compile(
            r"over the next\s+\w+\s+\w+"
            r"|(?:probabilit(?:y|ies)|likelihood|chance|risk)\s+of\s+"
            r"(?:\w+\s+){0,2}?(?:deteriorat\w*|default\w*|downgrad\w*"
            r"|migrat\w*)"
            r"|(?:expected|forecast\w*|projected|predicted|forward[- ]looking)"
            r"\s+(?:\w+\s+){0,2}?(?:deteriorat\w*|downgrad\w*|migrat\w*)",
            re.IGNORECASE)

    if intent not in cap.COMPUTES:
        return "none"
    text = (question or "").lower()
    # Blanked, not stripped: the rest of the sentence is still read, so
    # "PD rose last quarter; who is most likely to deteriorate next year?"
    # keeps its "rose" and stays a two-period question.
    text = _FORWARD.sub(lambda m: " " * len(m.group(0)), text)
    if mv.asks_for_change(text):
        return "two_period"
    return "point_in_time"


__all__ = ["SYSTEM", "TOOL_NAME", "Read", "read", "read_request",
           "read_request_offline"]
