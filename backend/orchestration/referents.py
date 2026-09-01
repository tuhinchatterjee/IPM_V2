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
from dataclasses import dataclass, field, replace
from typing import Any

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
    # "Just Healthcare." narrows exactly as "Only Contracting." does. The
    # trailing group is optional for the same reason it is on `only`: people
    # write the bare noun far more often than "just show the".
    (r"^\s*just\s+(?:show|include|keep|the)?\b", cv.MODIFY_PREVIOUS,
     "narrow the previous result"),
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
    # "Which also had an increase in ECL?" is "which of those also…" with the
    # referent left out, which is how people actually talk. Without this it
    # read as a fresh question and answered about the whole book — the exact
    # silent widening the population memory exists to prevent.
    r"^\s*(?:and\s+)?which\s+(?:of\s+\w+\s+)?also\b",
    r"^\s*(?:and\s+)?(?:how\s+many|who)\s+(?:of\s+\w+\s+)?also\b",
    r"^\s*(?:and\s+)?do any (?:of them|of those|of these)\b",
    r"^\s*now\b", r"^\s*and\b", r"^\s*what about\b", r"^\s*how about\b",
    r"^\s*break (?:that|this|it|them)\b", r"\bbreak (?:that|this|it) down\b",
    r"^\s*split (?:that|this|it)\b", r"^\s*group (?:that|this|it)\b",
    r"\beach one'?s?\b", r"\bper (?:one|each)\b", r"\bfor (?:each|every) one\b",
    r"^\s*(?:ok(?:ay)?|right|good)[,.]?\s+(?:now|then)\b",
)

#: A change to how the previous result is *shown*, with no new arithmetic.
#:
#: This is the one action that must not reach the planner. "Show it as a graph"
#: composed from scratch produced an analysis with no measure and no rows, and
#: the user — who could see the numbers a second earlier — was told the filters
#: selected no exposure.
_PRESENTATION: tuple[tuple[str, str], ...] = (
    (r"\bas an?\s+(?:bar\s+|line\s+|pie\s+|column\s+|stacked\s+)?"
     r"(?:graph|chart|plot|visual(?:isation|ization)?)\b", "chart"),
    (r"\b(?:show|display|render|draw|plot|visuali[sz]e)\s+"
     r"(?:it|this|that|them|these|those)?\s*"
     r"(?:as\s+)?(?:a\s+)?(?:bar|line|pie|column)?\s*"
     r"(?:graph|chart|plot)\b", "chart"),
    (r"\b(?:graph|chart|plot)\s+(?:it|this|that|them)\b", "chart"),
    (r"\bas an?\s+(?:plain\s+|simple\s+)?(?:table|grid|list)\b", "table"),
    (r"\b(?:use|show|give me|go back to|revert to|switch to)\s+"
     r"(?:the\s+|a\s+)?(?:table|grid)\b", "table"),
    (r"\btable\s+instead\b", "table"),
    (r"\b(?:no|without|drop|remove)\s+(?:the\s+)?(?:chart|graph|plot)\b", "table"),
)

#: A preference for a picture expressed inside a question that also asks for
#: something new. "Produce a graph of internal grade and DSCR" is an analysis
#: AND a presentation choice; treating it as only the first draws a table the
#: user explicitly did not ask for, and treating it as only the second computes
#: nothing.
_WANTS_CHART: tuple[str, ...] = (
    r"\b(?:graph|chart|plot)\b",
    r"\bvisuali[sz]e\b", r"\bvisuali[sz]ation\b",
)

_WANTS_TABLE: tuple[str, ...] = (
    r"\b(?:table|grid)\b",
)


def wants(question: str) -> str:
    """A presentation preference stated anywhere in the sentence.

    Read separately from `read`, because a preference is not an action. "Show
    me EAD by sector as a bar chart" is a new request that happens to say how it
    should be drawn, and the drawing instruction must survive the planning.
    """
    text = " " + " ".join((question or "").lower().split()) + " "
    for pattern in _WANTS_TABLE:
        if re.search(pattern, text):
            return "table"
    for pattern in _WANTS_CHART:
        if re.search(pattern, text):
            return "chart"
    return ""

#: Opening something rather than asking about it.
_NAVIGATE: tuple[str, ...] = (
    r"^\s*open\b", r"^\s*take me to\b", r"^\s*go to\b",
    r"^\s*navigate to\b", r"^\s*let me see\b.*\bdataset\b",
    r"^\s*(?:show|bring up)\s+(?:me\s+)?the\s+\w+\s+(?:dataset|table)\b",
)

#: A complaint that the previous answer was incomplete.
_INCOMPLETE: tuple[str, ...] = (
    r"you (?:did ?n[o']t|didnt|failed to|haven'?t|have not)\s+answer",
    r"(?:my|the)\s+(?:second|first|third|last|other)\s+(?:question|part)",
    r"that (?:did ?n[o']t|does ?n[o']t)\s+answer",
    r"what about the (?:second|other|rest)",
    r"you only answered",
    r"\bincomplete\b.*\banswer\b",
)

#: A question about the result that is already on the table.
_ABOUT_RESULT: tuple[str, ...] = (
    r"^\s*why (?:is|are|was|were|did|does|do)\b",
    r"^\s*what (?:does|do) (?:that|this|it|these|those) mean\b",
    r"^\s*explain (?:that|this|it|the result)\b",
    r"^\s*what (?:is|'s) driving\b",
    r"^\s*how come\b",
)

#: Throwing the current population away and starting from the whole book.
_RESET: tuple[str, ...] = (
    r"\bforget (?:those|these|that|them|the previous|it)\b",
    r"\bignore (?:those|these|that|them|the previous)\b",
    r"\bstart (?:again|over|fresh)\b",
    r"\bnever mind (?:those|these|that)\b",
    r"\bacross the (?:whole|entire|full) (?:portfolio|book)\b",
    r"\bfor the (?:whole|entire|full) (?:portfolio|book)\b",
    r"\buse the (?:whole|entire|full) (?:portfolio|book)\b",
    # "Now show me the whole portfolio's total exposure." Three of the four
    # patterns above need a preposition in front of "the whole portfolio",
    # and the plainest way a person says it has none — so the sentence read
    # as an ordinary continuation and kept the sector it was asking to drop.
    r"\bthe (?:whole|entire|full|complete) (?:portfolio|book|bank|group)s?\b",
)

#: Asking for more data than the current scope holds.
_WIDEN: tuple[tuple[str, str], ...] = (
    (r"\b(?:now\s+)?compare all\b", "compare across the whole population"),
    (r"\ball (?:sectors|regions|segments|customers|borrowers)\b",
     "widen to every member of the dimension"),
    (r"\badd (?:\w+\s+)?(?:more\s+)?(?:quarters|years|periods|months)\b",
     "extend the period range"),
    (r"\bgo back (?:\w+\s+)?(?:quarters|years|periods)\b",
     "extend the period range"),
    (r"\balso include\b", "add a domain to the analysis"),
    (r"\bbroaden\b", "widen the analysis"),
    (r"\bwiden\b", "widen the analysis"),
    (r"\bexpand (?:it|this|that|the (?:scope|analysis))\b",
     "widen the analysis"),
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
    #: One of `conversation.ACTIONS`.
    action: str = cv.NEW_REQUEST
    #: For MODIFY_PRESENTATION: chart | table.
    presentation: str = ""
    #: Plain-English modifications, for the Trace.
    changes: list[str] = field(default_factory=list)
    #: Why this reading. Shown when the model and this reader disagreed.
    because: str = ""

    @property
    def refers_back(self) -> bool:
        return bool(self.population) or self.action != cv.NEW_REQUEST


#: A sentence that points at what is already on the table.
_POINTS_BACK = re.compile(
    r"\b(?:this|that|these|those|it|them|the (?:above|result|figures|numbers|"
    r"pattern|trend|relationship))\b")


def _asks_about_a_pattern(question: str) -> bool:
    from backend.orchestration import association

    return association.wants(question)


def _asks_about_the_result(question: str) -> bool:
    """Whether the sentence is about the previous RESULT rather than the book.

    Wider than the pattern test above, and checked without requiring a pointing
    word: "are there exceptions?" and "is this monotonic?" are questions about
    the table on the screen whether or not they contain "this".
    """
    from backend.orchestration import reuse

    return reuse.wants(question)


def read(question: str) -> Reference:
    """What this sentence refers back to, without a model and without state.

    State is deliberately not consulted here. Whether a reference *can* be
    resolved is a separate question from whether one was *made*, and conflating
    them produced the worst possible behaviour: a follow-up with nothing to
    resolve was silently answered as a fresh question about the whole book.
    """
    text = " " + " ".join((question or "").lower().split()) + " "

    # Checked before everything else, including the new-subject patterns: a
    # complaint about the previous answer is never a new question, however it
    # is phrased, and reading it as one is precisely the failure it complains
    # about happening twice.
    for pattern in _INCOMPLETE:
        if re.search(pattern, text):
            return Reference(
                action=cv.CORRECT_INCOMPLETE_RESPONSE,
                changes=["answer the part of the previous request that was "
                         "left out"],
                because="the question says the previous answer was incomplete")

    # A presentation change is next, because it must never reach the planner.
    for pattern, kind in _PRESENTATION:
        if re.search(pattern, text):
            return Reference(
                action=cv.MODIFY_PRESENTATION, presentation=kind,
                changes=[f"show the same result as a {kind}"],
                because="the question changes how the result is shown, not "
                        "what it computes")

    # "Does this trend make sense?" points at the answer on the screen. Read as
    # a new request it names no measure, and the planner quite correctly asks
    # which figure to compute — which is the product asking the user to repeat
    # what they just looked at.
    if _asks_about_the_result(question) or (
            _POINTS_BACK.search(text) and _asks_about_a_pattern(question)):
        return Reference(
            action=cv.ASSESS_PREVIOUS_RESULT,
            changes=["assess the pattern in the result already on the table, "
                     "without re-running the analysis that produced it"],
            because="the question asks whether the previous result's pattern "
                    "holds")

    for pattern in _NEW_SUBJECT:
        if re.search(pattern, text):
            return Reference(action=cv.NEW_REQUEST,
                             because="the question opens a new subject")

    for pattern in _NAVIGATE:
        if re.search(pattern, text):
            return Reference(action=cv.NAVIGATE,
                             changes=["open what the conversation is about"],
                             because="the question asks to open something "
                                     "rather than to compute anything")

    for pattern in _ABOUT_RESULT:
        if re.search(pattern, text):
            return Reference(action=cv.ASK_ABOUT_RESULT,
                             because="the question asks about the result that "
                                     "is already on the table")

    for pattern in _RESET:
        if re.search(pattern, text):
            return Reference(action=cv.RESET_SCOPE,
                             changes=["drop the carried population and start "
                                      "from the whole book"],
                             because="the question deliberately discards the "
                                     "current population")

    for pattern, description in _WIDEN:
        if re.search(pattern, text):
            return Reference(action=cv.WIDEN_SCOPE, changes=[description],
                             because="the question asks for more data than the "
                                     "current scope holds")

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


#: A sentence that states its OWN population. Any of these means the reader
#: has said which book they want, so nothing is inherited: a named dimension
#: value ("in Contracting", "Stage 2", "rated BB"), or an explicit widening
#: ("across the portfolio", "the whole book", "every borrower").
_STATES_ITS_OWN_SCOPE: tuple[str, ...] = (
    r"\b(?:across|for|in|within|over)\s+(?:the\s+)?"
    r"(?:whole|entire|full|total)?\s*(?:book|portfolio|bank|group)\b",
    # "Now show me the whole portfolio's total exposure" carries no
    # preposition and is the plainest way there is of saying "stop filtering".
    r"\b(?:whole|entire|full|complete)\s+(?:book|portfolio|bank|group)s?\b",
    r"\b(?:portfolio|bank)[- ]wide\b",
    r"\ball\s+(?:borrowers?|customers?|facilities|accounts?|sectors?|names?)\b",
    r"\bevery\s+(?:borrower|customer|facility|account|sector|name)\b",
    r"\bstage\s*[123]\b",
    r"\brated?\s+[A-C]{1,3}[+-]?\b",
)


def states_its_own_scope(text: str, dimensions: Any = None) -> bool:
    """Whether this sentence says which population it is about. §6.

    Two ways it can. It can widen or restate the scope in words, or it can
    name a governed dimension value — a sector, a region, a segment — in which
    case that value IS the population and inheriting the previous one on top
    of it would answer about the intersection of two books.
    """
    lowered = " ".join(str(text or "").lower().split())
    if not lowered:
        return False
    if any(re.search(pattern, lowered) for pattern in _STATES_ITS_OWN_SCOPE):
        return True
    values = getattr(dimensions, "dimensions", dimensions) or {}
    try:
        for named in values.values():
            for value in named:
                word = str(value).lower()
                if len(word) > 3 and word in lowered:
                    return True
    except Exception:  # noqa: BLE001 - no vocabulary is not a scope statement
        return False
    return False


def refine(reference: Reference, memory: Any) -> Reference:
    """Sharpen a syntactic reading against what the last turn actually produced.

    `read()` deliberately knows nothing about state, so it cannot tell
    "which of those are financial ratios?" — a classification of a remembered
    FIELD SET, answerable from the catalogue — from "which of those are Stage
    2?", which is a filter on an entity set and needs governed data. The
    sentences are identical in shape; only the previous result distinguishes
    them.
    """
    if memory is None or getattr(memory, "empty", True):
        return reference
    result = getattr(memory, "result", None)
    if result is None or result.empty:
        return reference

    # A reference back into a metadata set is answered from the catalogue.
    if result.is_metadata and reference.action in (cv.CONTINUE, cv.NEW_REQUEST):
        if reference.population or reference.action == cv.CONTINUE:
            return replace(
                reference, action=cv.METADATA_FOLLOWUP,
                because=(f"the previous answer was a {result.result_type} and "
                         "the question refers back to it"))
    return reference


def resolve(question: str, state: cv.ConversationState, *,
            model_action: str = "", memory: Any = None) -> cv.Continuation:
    """How this turn relates to the conversation, deciding between two readers.

    The model's `conversation_action` is preferred where the two agree or where
    only one of them saw something. They disagree in one direction that matters:
    the deterministic reader says this refers back and the model says it is a
    fresh request. **The deterministic reader wins that one**, because losing a
    population silently is the failure mode this exists to prevent, and carrying
    context into a genuinely new question is visible and correctable.

    `memory` is the typed working memory, used to sharpen a reading that is
    ambiguous in the sentence and unambiguous once you know what the last turn
    produced. See `refine`.
    """
    read_back = refine(read(question), memory)
    model_action = cv.normalise(model_action) if model_action else ""

    # The deterministic reader owns the actions it can see in the sentence
    # itself. A model that reads "show it as a graph" as a fresh ANALYSIS is
    # not adding information, it is discarding some.
    if read_back.action in _READER_OWNS:
        action = read_back.action
        return _finish(question, read_back, action, state, read_back.because)

    action = model_action or read_back.action
    because = read_back.because or "the model read this as a follow-up"

    if read_back.refers_back and model_action == cv.NEW_REQUEST:
        action = read_back.action
        because = (f"{read_back.because}, so CreditProbe kept the conversation's "
                   "context even though the model read it as a new request")
        logger.info("Referent guardrail: keeping context for %r (%s)",
                    question[:70], read_back.because)

    if action == cv.NEW_REQUEST and _stays_in_the_population(question, state):
        # §6. The thread has settled a population and this sentence does not
        # name one of its own, so it is a question ABOUT that population.
        #
        # "Show exposure for Financial Services" and then "which borrowers are
        # the real issues?" is one conversation about one book. The second
        # sentence carries no referent word, so every reader here called it a
        # new request and the analysis ran over the whole portfolio — an answer
        # that looks right, is arithmetically correct, and is about a different
        # set of borrowers than the person is looking at.
        #
        # The narrowness is the safety. A sentence that names a sector, a
        # stage, a rating band or the whole book states its own scope and is
        # left alone; only a sentence that states none inherits one.
        action = cv.CONTINUE
        because = ("the question names no population of its own, so it "
                   "continues the one the conversation settled")
        carried = _finish(question, read_back, action, state, because)
        # Scope only. The sentence stated its own measure — the guardrail's
        # claim is about WHICH BORROWERS, not about which figure — and adding
        # the previous turn's measure on top answered "show total ECL by
        # sector" with exposure at default.
        carried.inherited["scope_only"] = (
            "the population was carried; the measure came from this question")
        return carried
        logger.info("Population guardrail: continuing %s for %r",
                    ", ".join(f"{k} = {v}" for k, v in state.filter_pairs())
                    or "the previous scope", question[:70])

    if action == cv.NEW_REQUEST:
        return cv.Continuation(action=cv.NEW_REQUEST,
                               because=read_back.because or "a new request")

    return _finish(question, read_back, action, state, because)


def _stays_in_the_population(question: str,
                             state: cv.ConversationState) -> bool:
    """Whether a fresh-looking sentence is still about the settled population.

    True only when there IS a settled population, the sentence names none of
    its own, and the question is an analytical one — a question about the
    catalogue mid-investigation is not narrowed by the sector the reader
    happens to be looking at.
    """
    if not state.filter_pairs():
        return False
    try:
        from backend.orchestration import capability as cap
        from backend.orchestration.vocabulary import get_vocabulary

        # A question about the CATALOGUE has no population to inherit. "What
        # fields are available in the ratings data?" mid-thread is its own
        # request, and narrowing the field list to the sector the reader
        # happens to be looking at is not a narrower answer, it is a wrong
        # one — a dataset's schema does not vary by sector.
        intent, _, _ = cap.recognise(question)
        if intent != cap.Capability.ANALYSIS:
            return False
        vocabulary = get_vocabulary()
    except Exception:  # noqa: BLE001 - without it, do not guess
        return False
    return not states_its_own_scope(question, vocabulary)


#: Actions the sentence settles on its own. A model reading cannot improve on
#: "show it as a graph", and every disagreement it can produce loses something.
_READER_OWNS = frozenset({
    cv.MODIFY_PRESENTATION, cv.CORRECT_INCOMPLETE_RESPONSE, cv.NAVIGATE,
    cv.RESET_SCOPE, cv.METADATA_FOLLOWUP, cv.ASSESS_PREVIOUS_RESULT,
})


def _finish(question: str, read_back: Reference, action: str,
            state: cv.ConversationState, because: str) -> cv.Continuation:
    """Build the continuation, carrying whatever the action needs with it."""
    # A continuation with nothing behind it is a new request. RESET_SCOPE is
    # exempt: "use the whole portfolio" is a legitimate opening sentence.
    if action in cv.CONTINUING and state.empty and action != cv.RESET_SCOPE:
        return cv.Continuation(
            action=cv.NEW_REQUEST,
            because="nothing has been established in this investigation yet")

    continuation = cv.Continuation(
        action=action, referent=read_back.population,
        presentation=read_back.presentation,
        changes=list(read_back.changes), because=because)

    # "Forget those five and use the whole portfolio" means exactly that. A
    # reset that carried the population forward would answer a portfolio
    # question over five names — correct arithmetic, correct-looking table,
    # wrong by three orders of magnitude, with nothing on screen to say so.
    if action == cv.RESET_SCOPE:
        continuation.inherited["scope"] = (
            "the carried population and its filters were dropped, because the "
            "question asked for the whole book")
        return continuation

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
    elif action in (cv.CONTINUE, cv.ENRICH_PREVIOUS, *cv.MODIFICATIONS) \
            and state.result.has_population:
        # "Add their latest internal rating", "show me the ten largest" and
        # "which also had an increase in ECL?" name no referent but plainly
        # mean the rows that are on screen. A continuation that silently
        # widened back to the whole book would be the same failure as losing a
        # referent, arriving by a different route — and it is worse, because
        # the answer looks like a bigger version of the right one.
        continuation.entity_key = state.result.entity_key
        continuation.entity_ids = list(state.result.entity_ids)
        continuation.entity_labels = dict(state.result.entity_labels)
        continuation.inherited["population"] = (
            f"the {len(continuation.entity_ids)} rows already on screen")

    return continuation


def _self_referential(question: str, population: str) -> bool:
    """Whether the reference points at an earlier clause of the SAME question.

        "What columns are in the ratings data, and which of them are ratios?"

    "of them" is the columns the first half asks for. There is no previous
    turn and there does not need to be one, and asking "what does 'of them'
    refer to?" about a sentence that says so is the kind of question that makes
    a product feel like it is not listening.

    Answered by `discourse`, which segments the message and binds each anaphor
    to the cohort an earlier clause defines. This used to be answered by
    `wm.objectives`, a splitter that only cuts on "and <wh-word>" — so

        "Which customers experienced ...? Rank them by EAD."

    came back as ONE objective, the check could not see that "them" was
    introduced in the same message, and the product refused a question that
    answers itself. That was P0.1's defect A.
    """
    from backend.orchestration import discourse as dsc

    return dsc.resolves_locally(question)


def unresolved(question: str, state: cv.ConversationState) -> str:
    """The clarification to ask when a sentence referred to nothing.

    Returned as text rather than raised, because "which five?" is a
    conversation, not an error.
    """
    read_back = read(question)
    if not read_back.population or state.result.has_population:
        return ""
    if _self_referential(question, read_back.population):
        return ""
    # Written as a credit officer would ask it, not as the parser would.
    # The old wording — "no previous result in this investigation returned a
    # set of names to carry forward" — described the mechanism that failed
    # rather than the thing the reader has to decide, and it read as a bug
    # report in front of a client. What is actually needed is one short
    # question: which borrowers do you mean?
    return (
        f"Which borrowers do you mean by {read_back.population!r}? Nothing "
        "earlier in this investigation names a set I can carry forward, so "
        "tell me the population — a sector, a rating band, a stage, or a "
        "question that produces the list — and I will take it from there.")


__all__ = ["Reference", "read", "resolve", "unresolved", "wants"]
