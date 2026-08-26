"""
Working out what "these" means.

A credit conversation is full of reference. Nobody asks the second question in
full:

    "Show me the five largest Real Estate customers by EAD."
    "Which of these are Stage 2 or Stage 3?"
    "Rank those by ECL instead."
    "Add their latest internal rating."

Three sentences that are meaningless alone and unambiguous in sequence. This
module is what makes them unambiguous to CreditProbe.

The rule it enforces
--------------------
**A referent resolves to identities, never to a re-derivation.** "These" means
the five customer ids the previous run actually returned — written down in the
conversation state — not "the five largest Real Estate customers", which would
be recomputed and could quietly come back as a different five if the period
moved. That distinction is the difference between a conversation and a sequence
of similar questions.

Deterministic, and why
----------------------
The live model also reports a `conversation_action`, and it is better than this
module at unusual phrasing. But a model that decides a follow-up is a fresh
request silently loses the population, and the user sees the failure the whole
release was called for. So this reader runs on every turn regardless of provider
and acts as the floor: where it is confident and the model disagrees, the
conversation is treated as continuing and the Trace records that it was.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from backend.orchestration import conversation as cv

logger = logging.getLogger(__name__)

#: Phrases that point back at the previous result's population.
#: Ordered longest-first so "those five customers" is reported rather than
#: "those", which reads better in the Trace and in a clarification.
_POPULATION: tuple[str, ...] = (
    r"the previous result", r"the previous answer", r"the last result",
    r"the results? above", r"that result", r"that analysis",
    r"those (?:five|ten|\d+) (?:customers|borrowers|names|sectors|groups)",
    r"these (?:five|ten|\d+) (?:customers|borrowers|names|sectors|groups)",
    r"the (?:five|ten|\d+) (?:customers|borrowers|names|sectors|groups)",
    r"those (?:customers|borrowers|names|sectors|groups|facilities|accounts)",
    r"these (?:customers|borrowers|names|sectors|groups|facilities|accounts)",
    r"the same (?:customers|borrowers|names|sectors|group)",
    r"same customers", r"same names", r"same group",
    r"the first (?:five|ten|\d+)", r"the top (?:five|ten|\d+) above",
    r"those (?:five|ten|\d+)", r"these (?:five|ten|\d+)",
    r"of those", r"of these", r"of them",
    r"\bthose\b", r"\bthese\b", r"\bthem\b", r"\bthe ones\b",
)

#: Phrases that point back at the previous *period* rather than the population.
_SAME_PERIOD: tuple[str, ...] = (
    r"same period", r"the same quarter", r"the same year",
    r"that period", r"that quarter", r"the same window",
    r"the same comparison",
)

#: Number words a credit officer writes out rather than digits.
_COUNT = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty)"
_SUPERLATIVE = r"largest|biggest|smallest|worst|best|top|highest|lowest|first"

#: A modification of the plan that just ran, rather than a new question.
#: `(pattern, action, description)` — the description reaches the Trace.
_MODIFY: tuple[tuple[str, str, str], ...] = (
    (r"\binstead\b", cv.MODIFY_PREVIOUS, "replace part of the previous analysis"),
    (r"\breplace\b", cv.MODIFY_PREVIOUS, "replace a measure"),
    (r"^\s*(?:now\s+)?(?:show|display|give me)\s+only\b", cv.MODIFY_PREVIOUS,
     "narrow the previous result"),
    (r"^\s*only\s+(?:show|include|keep)?\b", cv.MODIFY_PREVIOUS,
     "narrow the previous result"),
    (r"^\s*just\s+(?:show|the)\b", cv.MODIFY_PREVIOUS, "narrow the previous result"),
    (r"\bnarrow (?:it |this |that )?(?:down )?to\b", cv.MODIFY_PREVIOUS,
     "narrow the previous result"),
    (r"\brestrict (?:it |this |that )?to\b", cv.MODIFY_PREVIOUS,
     "narrow the previous result"),
    (r"\bfilter (?:it |this |that )?(?:down )?to\b", cv.MODIFY_PREVIOUS,
     "narrow the previous result"),
    (r"^\s*(?:now\s+)?(?:re)?(?:sort|order|rank)\b", cv.MODIFY_PREVIOUS,
     "re-order the previous result"),
    (rf"^\s*(?:now\s+)?(?:show|give|list)\s+(?:me\s+)?(?:the\s+)?"
     rf"(?:{_COUNT}\s+(?:{_SUPERLATIVE})|(?:{_SUPERLATIVE})\s+{_COUNT})\b",
     cv.MODIFY_PREVIOUS, "cut the previous result to a different size"),
    (rf"^\s*(?:the\s+)?{_COUNT}\s+(?:{_SUPERLATIVE})\b",
     cv.MODIFY_PREVIOUS, "cut the previous result to a different size"),
    (r"\bexclude\b", cv.MODIFY_PREVIOUS, "exclude part of the previous result"),
    (r"\bdrop\b", cv.MODIFY_PREVIOUS, "drop part of the previous result"),
)

#: An addition to what the previous turn produced.
_ENRICH: tuple[tuple[str, str], ...] = (
    (r"^\s*(?:now\s+)?(?:also\s+)?add\b", "add a column to the previous result"),
    (r"\balso (?:show|include|add)\b", "add a column to the previous result"),
    (r"\bas well\b", "add a column to the previous result"),
    (r"\balongside\b", "add a column to the previous result"),
    (r"\bbring in\b", "add a column to the previous result"),
    (r"\band (?:their|its) (?:latest|current)\b",
     "add a column to the previous result"),
)

#: A follow-up that continues the subject without referring to the population —
#: "Now show each one's percentage of total portfolio EAD."
_CONTINUE: tuple[str, ...] = (
    r"^\s*now\b", r"^\s*and\b", r"^\s*what about\b", r"^\s*how about\b",
    r"^\s*break (?:that|this|it|them)\b", r"\bbreak (?:that|this|it) down\b",
    r"^\s*split (?:that|this|it)\b", r"^\s*group (?:that|this|it)\b",
    r"\beach one'?s?\b", r"\bper (?:one|each)\b", r"\bfor (?:each|every) one\b",
    r"^\s*(?:ok(?:ay)?|right|good)[,.]?\s+(?:now|then)\b",
)

#: A question that plainly starts a new subject, even if it uses a pronoun.
#: Checked first, because "What data do you have about ratings?" mid-thread is
#: not a follow-up about the population.
_NEW_SUBJECT: tuple[str, ...] = (
    r"^\s*what data\b", r"^\s*which datasets?\b", r"^\s*what datasets?\b",
    r"^\s*what fields?\b", r"^\s*which fields?\b",
    r"^\s*how (?:is|are|does|do)\b.*\bconnected\b",
    r"^\s*how many (?:years|quarters|periods|months)\b",
    r"^\s*what (?:does|do)\b.*\bmean\b",
    r"^\s*(?:what|which) methods?\b",
)


@dataclass(frozen=True)
class Reference:
    """What the sentence pointed back at, read deterministically."""

    #: The population referent, e.g. "those five customers". Empty for none.
    population: str = ""
    #: True when the sentence asked for the previous comparison window.
    same_period: bool = False
    #: NEW_REQUEST | CONTINUE | MODIFY_PREVIOUS | ENRICH_PREVIOUS
    action: str = cv.NEW_REQUEST
    #: Plain-English modifications, for the Trace.
    changes: list[str] = field(default_factory=list)
    #: Why this reading. Shown when the model and this reader disagreed.
    because: str = ""

    @property
    def refers_back(self) -> bool:
        return bool(self.population) or self.action != cv.NEW_REQUEST


def read(question: str) -> Reference:
    """What this sentence refers back to, without a model and without state.

    State is deliberately not consulted here. Whether a reference *can* be
    resolved is a separate question from whether one was *made*, and conflating
    them produced the worst possible behaviour: a follow-up with nothing to
    resolve was silently answered as a fresh question about the whole book.
    """
    text = " " + " ".join((question or "").lower().split()) + " "

    for pattern in _NEW_SUBJECT:
        if re.search(pattern, text):
            return Reference(action=cv.NEW_REQUEST,
                             because="the question opens a new subject")

    population = ""
    for pattern in _POPULATION:
        match = re.search(pattern, text)
        if match:
            population = match.group(0).strip()
            break

    same_period = any(re.search(p, text) for p in _SAME_PERIOD)

    changes: list[str] = []
    action = cv.NEW_REQUEST
    because = ""

    for pattern, kind, description in _MODIFY:
        if re.search(pattern, text):
            action = kind
            changes.append(description)
            because = "the question modifies the analysis that just ran"
            break

    if action == cv.NEW_REQUEST:
        for pattern, description in _ENRICH:
            if re.search(pattern, text):
                action = cv.ENRICH_PREVIOUS
                changes.append(description)
                because = "the question adds to the result that just ran"
                break

    if action == cv.NEW_REQUEST and population:
        action = cv.CONTINUE
        because = f"the question refers back with {population!r}"

    if action == cv.NEW_REQUEST and any(re.search(p, text) for p in _CONTINUE):
        action = cv.CONTINUE
        because = "the question continues the previous one"

    if action == cv.NEW_REQUEST and same_period:
        action = cv.CONTINUE
        because = "the question reuses the previous period"

    return Reference(population=population, same_period=same_period,
                     action=action, changes=changes, because=because)


def resolve(question: str, state: cv.ConversationState, *,
            model_action: str = "") -> cv.Continuation:
    """How this turn relates to the conversation, deciding between two readers.

    The model's `conversation_action` is preferred where the two agree or where
    only one of them saw something. They disagree in one direction that matters:
    the deterministic reader says this refers back and the model says it is a
    fresh request. **The deterministic reader wins that one**, because losing a
    population silently is the failure mode this exists to prevent, and carrying
    context into a genuinely new question is visible and correctable.
    """
    read_back = read(question)
    model_action = (model_action or "").strip().upper()
    if model_action not in cv.ACTIONS:
        model_action = ""

    action = model_action or read_back.action
    because = read_back.because or "the model read this as a follow-up"

    if read_back.refers_back and model_action == cv.NEW_REQUEST:
        action = read_back.action
        because = (f"{read_back.because}, so CreditProbe kept the conversation's "
                   "context even though the model read it as a new request")
        logger.info("Referent guardrail: keeping context for %r (%s)",
                    question[:70], read_back.because)

    # A continuation with nothing behind it is a new request. This is the case
    # where the model has decided the first question in a thread is a follow-up.
    if action in cv.CONTINUING and state.empty:
        return cv.Continuation(
            action=cv.NEW_REQUEST,
            because="nothing has been established in this investigation yet")

    if action == cv.NEW_REQUEST:
        return cv.Continuation(action=cv.NEW_REQUEST,
                               because=read_back.because or "a new request")

    continuation = cv.Continuation(
        action=action, referent=read_back.population,
        changes=list(read_back.changes), because=because)

    # The population, when the sentence pointed at one and one exists. A
    # reference with nothing to resolve is left unresolved rather than quietly
    # widened: the caller asks, which is the honest outcome.
    if read_back.population and state.result.has_population:
        continuation.entity_key = state.result.entity_key
        continuation.entity_ids = list(state.result.entity_ids)
        continuation.entity_labels = dict(state.result.entity_labels)
        continuation.inherited["population"] = (
            f"{len(continuation.entity_ids)} {state.result.entity_key} "
            f"from the previous result")
    elif action in (cv.ENRICH_PREVIOUS, cv.MODIFY_PREVIOUS) \
            and state.result.has_population:
        # "Add their latest internal rating" and "show me the ten largest" name
        # no referent but plainly mean the rows that are on screen. A
        # modification that silently widened back to the whole book would be the
        # same failure as losing a referent, arriving by a different route.
        continuation.entity_key = state.result.entity_key
        continuation.entity_ids = list(state.result.entity_ids)
        continuation.entity_labels = dict(state.result.entity_labels)
        continuation.inherited["population"] = (
            f"the {len(continuation.entity_ids)} rows already on screen")

    return continuation


def unresolved(question: str, state: cv.ConversationState) -> str:
    """The clarification to ask when a sentence referred to nothing.

    Returned as text rather than raised, because "which five?" is a
    conversation, not an error.
    """
    read_back = read(question)
    if not read_back.population or state.result.has_population:
        return ""
    return (
        f"CreditProbe could not work out what {read_back.population!r} refers "
        "to — no previous result in this investigation returned a set of names "
        "to carry forward. Ask the question with the population named, or run "
        "the analysis that produces it first.")


__all__ = ["Reference", "read", "resolve", "unresolved"]
