"""
When CreditProbe has not understood, and what it should say instead.

The behaviour this replaces
--------------------------
Asked something it could not read, the planner used to run the standard
portfolio review and put a note above it. That is the worst possible failure for
a product whose claim is that its numbers are trustworthy: the user asked about
Summit Power and got the bank's total exposure at default, correctly calculated,
carrying a certification tick, answering a question nobody asked.

A confident answer to the wrong question is more damaging than no answer,
because nothing about it looks wrong.

So: four situations, four honest responses, and none of them is a number.

    UNKNOWN INTENT    "I can look at several things about this. Which?"
    UNKNOWN ENTITY    "I can't find Summit Power in the published data."
    MISSING DATASET   "That needs the ratings history, which is not published."
    AMBIGUOUS PERIOD  handled in clarification.py — a narrower case with its
                      own logic, because a period has real options to offer.

Each one names what CreditProbe CAN do next, because a refusal that leaves
somebody with nothing to click is only half an answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from backend.orchestration.schema import AnalysisPlan, Clarification
from backend.orchestration.vocabulary import Vocabulary, get_vocabulary

logger = logging.getLogger(__name__)

KIND_INTENT = "intent"
KIND_ENTITY = "entity"
KIND_DATASET = "dataset"

#: A proper noun in a question is usually a borrower. Two or more capitalised
#: words in a row, not at the start of the sentence, and not a word the product
#: uses itself.
_ENTITY_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+)\b")

#: Words that are capitalised in ordinary use and are not borrowers.
_NOT_ENTITIES = frozenset({
    "credit probe", "creditprobe", "early warning", "real estate",
    "stage migration", "portfolio summary", "expected credit loss",
    "commercial real estate", "data builder", "engine builder",
    "forward risk signal", "saudi arabia", "board risk", "risk committee",
    "credit risk", "days past due", "loss given default", "point in time",
    "trace", "which", "what", "how", "why", "show", "give",
})

#: Analyses to offer when the question named a borrower CreditProbe knows about
#: but did not say what to look at. Ordered by how often it is the right answer.
_ENTITY_OPTIONS: list[tuple[str, str]] = [
    ("its exposure and limits", "How much exposure do we have to {entity}?"),
    ("its rating and PD", "How has {entity}'s rating moved?"),
    ("its expected credit loss", "How has {entity}'s expected credit loss moved?"),
    ("its arrears", "Is {entity} in arrears?"),
]


@dataclass(frozen=True)
class Comprehension:
    """What CreditProbe made of the question, before it runs anything."""

    understood: bool
    clarification: Clarification | None = None

    @property
    def should_ask(self) -> bool:
        return not self.understood and self.clarification is not None


def named_entities(question: str) -> list[str]:
    """Proper nouns in the question that look like a borrower's name.

    Deliberately conservative. A false positive here means asking about
    something the user did not name, which is annoying; a false negative means
    falling through to the ordinary path, which is what used to happen anyway.
    """
    out: list[str] = []
    for match in _ENTITY_RE.finditer(question):
        candidate = match.group(1).strip()
        if candidate.lower() in _NOT_ENTITIES:
            continue
        # A capitalised phrase at the very start of a sentence is usually just a
        # sentence, not a name.
        if match.start() == 0:
            continue
        out.append(candidate)
    return out


def find_borrower(name: str, vocab: Vocabulary | None = None) -> str | None:
    """The published borrower this name refers to, if there is one.

    A real read through the Data Access Layer, not a scan of the vocabulary:
    there are thousands of borrowers and the vocabulary deliberately holds only
    the small dimensions a planner filters on. This asks the governed reader for
    the borrower names in the latest period and matches against those, so it can
    only ever resolve to a borrower that genuinely exists.

    Cached for the life of the process, because the answer changes only when a
    dataset is published — the same reason the vocabulary is cached.
    """
    vocab = vocab or get_vocabulary()
    wanted = " ".join(name.lower().split())
    if not wanted:
        return None

    for candidate in _borrower_names(vocab.latest):
        text = " ".join(candidate.lower().split())
        if text == wanted or wanted in text or text in wanted:
            return candidate
    return None


@lru_cache(maxsize=4)
def _borrower_names(period: str | None) -> tuple[str, ...]:
    """Every borrower name in one published period.

    Read once and held, because it is a property of the published data rather
    than of a request. An empty tuple where nothing is published means every
    name is reported as not found — which is the correct answer when there is
    no book to look in.
    """
    if not period:
        return ()
    try:
        from backend.data_access import get_data_source
        from backend.data_access.context import AnalysisContext
        from backend.engine.helpers import FACILITY

        frame = get_data_source().fetch(
            FACILITY, context=AnalysisContext(period=period),
            fields=["borrower_name"], period=period,
        )
        return tuple(sorted({str(v) for v in frame["borrower_name"].dropna()}))
    except Exception as e:  # pragma: no cover - nothing published yet
        logger.warning("Could not read borrower names for %s: %s", period, e)
        return ()


def _entity_clarification(entity: str, resolved: str | None) -> Clarification:
    """Either "which measure?" or "I cannot find them"."""
    if resolved is None:
        return Clarification(
            kind=KIND_ENTITY,
            question=f"I could not find {entity} in the published data.",
            detail=(
                "CreditProbe only reads datasets that have been published and "
                "marked authoritative, so a borrower it has never been given "
                "cannot be looked up. Check the name, or ask a Data Steward "
                "whether that book has been onboarded."
            ),
            options=[],
            because="No published dataset contains that borrower.",
            allow_custom=False,
        )

    return Clarification(
        kind=KIND_ENTITY,
        question=f"What would you like to know about {resolved}?",
        detail=(
            "I can look at several things, and they are different questions "
            "with different answers."
        ),
        options=[
            {
                "id": f"entity-{index}",
                "label": label,
                "question": template.format(entity=resolved),
            }
            for index, (label, template) in enumerate(_ENTITY_OPTIONS)
        ],
        because=f"{resolved} is in the published data.",
        allow_custom=True,
    )


def _intent_clarification(vocab: Vocabulary) -> Clarification:
    """"I did not follow that." — with the things CreditProbe can actually do.

    The options are read from the Engine Registry rather than written here, so
    the list is what the product can genuinely answer today and cannot drift out
    of date as analyses are added.
    """
    # Ordered by what somebody is most likely to want, using the registry's own
    # category rather than the alphabet: where the book stands, then what is
    # deteriorating, then why.
    rank = {"monitor": 0, "detect": 1, "investigate": 2, "stress": 3, "reference": 4}
    candidates = [
        (rank.get(str(entry.get("category")), 9), analysis_id, entry)
        for analysis_id, entry in vocab.analyses.items()
        if entry.get("trigger_questions")
    ]
    candidates.sort(key=lambda item: (item[0], item[1]))

    # A handful, not a menu of everything. Somebody who reads eight options
    # reads none of them.
    offers = [
        {
            "id": analysis_id,
            "label": str(entry.get("name") or analysis_id),
            "question": str((entry.get("trigger_questions") or [""])[0]),
        }
        for _, analysis_id, entry in candidates[:4]
    ]

    return Clarification(
        kind=KIND_INTENT,
        question="I did not follow that one.",
        detail=(
            "I can only answer with analyses the engine has registered, so "
            "rather than guess and give you a confident number about something "
            "else, here is what I can look at."
        ),
        options=offers,
        because="No registered analysis matches the question as written.",
        allow_custom=True,
    )


def comprehend(question: str, plan: AnalysisPlan,
               vocab: Vocabulary | None = None) -> Comprehension:
    """Decide whether to answer or to ask.

    Called before anything runs. Returning `should_ask` stops the executor
    dead — it does NOT fall through to a default analysis, which is the whole
    point of this module existing.
    """
    vocab = vocab or get_vocabulary()

    # A named borrower is the strongest signal in a question, and it is worth
    # checking even when the intent matched: "Summit Power" with no measure is
    # ambiguous however confidently the planner read the rest.
    for entity in named_entities(question):
        resolved = find_borrower(entity, vocab)
        if resolved is None:
            logger.info("Question names %r, which is not in the published data.", entity)
            return Comprehension(False, _entity_clarification(entity, None))
        if plan.unmatched:
            return Comprehension(False, _entity_clarification(entity, resolved))

    if plan.unmatched:
        logger.info("No registered analysis matches %r.", question[:80])
        return Comprehension(False, _intent_clarification(vocab))

    return Comprehension(True)


__all__ = [
    "KIND_DATASET",
    "KIND_ENTITY",
    "KIND_INTENT",
    "Comprehension",
    "comprehend",
    "find_borrower",
    "named_entities",
]
