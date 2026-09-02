"""What the answer has one row of — read from the noun the question asks for.

The defect
----------
    "Which sectors concern you most?"   → twenty-five borrowers
    "Show rating distribution."         → one number, 10.00

Both sentences name the thing they want one row of. Neither was read that way.
The planner resolved a breakdown only from an explicit "by X" phrase, so a
question whose dimension is its SUBJECT — "which sectors", "rating
distribution" — arrived with no dimension at all and fell through to whatever
grain the source dataset happened to be keyed on. The figures were right. The
rows were about the wrong thing, which is not a smaller version of the right
answer.

Measure and dimension are different questions
----------------------------------------------
    "Which sectors have the highest ECL?"

    measure    expected credit loss
    dimension  sector
    answer     one row per sector, ranked by ECL

Reading "ECL" and stopping there is how that question came back as a list of
borrowers. This module answers only the second half. It never chooses a
measure.

Three rules, in this order
--------------------------
1. **breakdown** — an explicit instruction: "by sector", "per rating",
   "for each stage", "grouped by region", "broken down by segment".
2. **named** — the dimension used as a noun-modifier of a shape word:
   "rating distribution", "sector split", "stage mix".
3. **requested** — the head noun of the request itself: "which sectors…",
   "show me the ratings…", "the five largest sectors…".

Rule 3 is the one that was missing, and it is also the one that outranks an
entity noun later in the sentence: "which SECTORS have borrowers with rising
PD?" asks for sectors, and the borrowers are a condition on which sectors
qualify, not the grain of the answer.

Where the two disagree, ask
----------------------------
    "Show the five largest borrowers by exposure, grouped by sector."

The head noun asks for borrowers and the breakdown asks for sectors. Those are
two different tables and no single grain is both. Collapsing to one silently —
which is what happened, five sector rows under a heading promising five
borrowers — is the failure this module exists to prevent, so the conflict is
reported and the caller asks which was meant.

Governed metadata, not a synonym table
---------------------------------------
The dimensions come from the installation's own vocabulary and are matched on
their governed names first. `ALIASES` holds only the spellings where a credit
officer's word and the governed field name genuinely differ, and where nothing
in the ontology already covers it. Anything not resolved by a name or an alias
is resolved against the governed CONCEPT catalogue, restricted to ordinal and
categorical concepts — which is what makes "rating" reach `internal_grade`
without this module holding an opinion about ratings.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DIMENSIONS_VERSION = "1.0.0"

#: Governed spellings a field name does not already carry. Deliberately short:
#: every entry here is a claim that the catalogue cannot answer on its own, and
#: a long list of those is a parallel vocabulary by another name.
ALIASES: dict[str, tuple[str, ...]] = {
    "sector": ("industry", "industries", "sectors"),
    "region": ("regions", "geography", "geographies"),
    "segment": ("segments", "client segment", "customer segment"),
    "product_type": ("product", "products", "product types"),
    "country": ("countries",),
    "rating_bucket": ("rating buckets", "rating bands", "rating band"),
    "ifrs9_stage": ("stage", "stages", "ifrs 9 stage", "ifrs 9 stages",
                    "ifrs9 stage", "staging", "impairment stage"),
}

#: What one row is when the head noun is an entity rather than a dimension.
#: Mirrors `grain`'s own vocabulary rather than restating it: this module only
#: needs to know that the noun was an entity, and which one.
_CUSTOMER_NOUNS = re.compile(
    r"^(?:customers?|borrowers?|obligors?|clients?|counterpart(?:y|ies)|"
    r"names?|companies|company|groups?|entities|entity|credits?)$")
_FACILITY_NOUNS = re.compile(
    r"^(?:facilit(?:y|ies)|accounts?|loans?|drawdowns?|tranches?|"
    r"exposure lines?|lines?)$")

#: 1. An explicit instruction to break the answer down.
_BREAKDOWN = re.compile(
    r"\b(?:for each|for every|grouped by|group by|broken down by|split by|"
    r"by|per|across)\s+(?P<phrase>[a-z0-9][a-z0-9 ]{1,30}?)"
    r"\s*(?:,|\.|;|\?|$|\band\b|\bshow\b|\bwith\b|\bin the\b|\bfor the\b|"
    r"\bat\b|\bover the\b|\bduring\b|\bthis\b|\blast\b)")

#: 2. The dimension as a modifier of a shape word: "rating distribution".
_NAMED = re.compile(
    r"\b(?P<phrase>[a-z0-9][a-z0-9 ]{1,24}?)\s+"
    r"(?:distribution|breakdown|split|mix|profile|composition|spread)\b")

#: 3. The head noun of the request. Everything between the request verb and
#: the noun is quantity and superlative — "the five largest", "top 10" — and
#: is skipped rather than read, because it sizes the answer and does not say
#: what the answer is of.
_HEAD = re.compile(
    r"^(?:so|and|but|ok|okay|now|then|please)?[,\s]*"
    r"(?:which|what|who|show(?:\s+me)?|list|rank|give\s+me|find|name|tell\s+me"
    r"|display|report)\s+"
    r"(?:the\s+|me\s+|us\s+|all\s+|any\s+|our\s+)*"
    r"(?:(?:\d+|top|bottom|first|last|largest|biggest|smallest|worst|best|"
    r"highest|lowest|riskiest|weakest|strongest|one|two|three|four|five|six|"
    r"seven|eight|nine|ten|twenty|fifty)\s+){0,3}"
    r"(?P<phrase>[a-z0-9][a-z0-9 ]{1,30}?)\b")

#: How many words of the head phrase are tried, longest first. Three is enough
#: for "rating grade", "product type", "ifrs 9 stage".
_HEAD_WORDS = 3

#: Words that end a head noun phrase. Without them "which sectors have the
#: highest ECL" offers "sectors have the" as a candidate, which resolves to
#: nothing but costs a lookup and reads badly in the Trace.
_STOP = frozenset({
    "have", "has", "had", "is", "are", "was", "were", "with", "that", "which",
    "who", "whose", "concern", "concerns", "worry", "worries", "saw", "see",
    "show", "shows", "showed", "deteriorated", "deteriorate", "improved",
    "increased", "decreased", "rose", "fell", "by", "in", "for", "at", "on",
    "of", "and", "or", "the", "a", "an", "to", "from", "most", "me", "us",
})


@dataclass(frozen=True)
class Resolved:
    """The dimension a question asks its answer to be broken down by."""

    dimension: str = ""
    #: The words that named it, for the Trace and for a clarification.
    phrase: str = ""
    #: breakdown | named | requested. Empty when nothing was named.
    rule: str = ""
    #: customer | facility, when the HEAD noun named an entity instead.
    entity: str = ""
    #: The head noun, when it named an entity.
    entity_phrase: str = ""
    because: str = ""

    @property
    def found(self) -> bool:
        return bool(self.dimension)

    @property
    def is_head(self) -> bool:
        """Whether the dimension IS what the question asked for.

        A head dimension outranks an entity noun elsewhere in the sentence.
        A breakdown does not — "the ten largest customers by sector" is a
        question about customers however it is grouped.
        """
        return self.rule == "requested"

    @property
    def conflicts(self) -> bool:
        """The head asks for one grain and the breakdown asks for another."""
        return bool(self.dimension and self.entity and not self.is_head)

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "phrase": self.phrase,
                "rule": self.rule, "entity": self.entity,
                "entity_phrase": self.entity_phrase, "because": self.because}


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _spellings(name: str) -> set[str]:
    """Every way the installation's own field name is written in a sentence."""
    plain = name.replace("_", " ")
    spaced = re.sub(r"(\d)", r" \1 ", plain)
    out = {name, plain, " ".join(spaced.split())}
    out |= {f"{form}s" for form in list(out)}
    return out


def _as_dimension(phrase: str, dimensions: Any) -> str:
    """The governed dimension this phrase names, or "".

    Names and aliases first, the concept catalogue second. Never a guess: a
    phrase that resolves to neither returns nothing, and the caller plans the
    question without a breakdown rather than inventing one.
    """
    words = " ".join(str(phrase or "").lower().split())
    if not words:
        return ""
    singular = " ".join(_singular(w) for w in words.split())
    names = list(getattr(dimensions, "dimensions", dimensions) or [])

    for name in names:
        forms = _spellings(name) | set(ALIASES.get(name, ()))
        if words in forms or singular in forms:
            return name
    # A dimension the installation does not carry may still be a governed
    # concept — "rating" is an ordinal scale with ten grades and exactly what
    # a rating distribution has one row per.
    return _as_concept(singular or words)


def _as_concept(phrase: str) -> str:
    """A governed ORDINAL or CATEGORICAL concept used as a breakdown.

    Restricted to those two on purpose. Grouping by a continuous money measure
    produces one row per distinct amount, which is not a breakdown — it is the
    raw table with extra steps.
    """
    try:
        from backend.orchestration import concepts as cx
        from backend.semantics import ontology
    except Exception:  # noqa: BLE001 - no catalogue names no dimension
        return ""
    for concept in cx.CONCEPTS:
        try:
            if not re.search(concept.pattern, phrase):
                continue
            contract = ontology.contract(concept.id)
            if contract is None or not (contract.is_ordinal
                                        or contract.is_categorical):
                continue
            return concept.default_candidate().field
        except Exception:  # noqa: BLE001 - one bad concept is not a failure
            continue
    return ""


def _candidates(phrase: str) -> list[str]:
    """The head phrase, longest sensible noun first."""
    words = [w for w in str(phrase or "").lower().split() if w]
    out: list[str] = []
    for size in range(min(_HEAD_WORDS, len(words)), 0, -1):
        head = words[:size]
        if head[-1] in _STOP:
            continue
        out.append(" ".join(head))
    return out


def read(text: str, dimensions: Any = None) -> Resolved:
    """The dimension this question asks its answer to be broken down by.

    `dimensions` is the installation's governed vocabulary — a mapping of
    dimension name to values, or anything carrying one on `.dimensions`. It is
    read, never extended: a dimension this installation does not govern is not
    a dimension, whatever the sentence calls it.
    """
    lowered = " ".join(str(text or "").lower().split())
    if not lowered:
        return Resolved()
    if dimensions is None:
        try:
            from backend.orchestration.vocabulary import get_vocabulary

            dimensions = get_vocabulary()
        except Exception:  # noqa: BLE001 - without a vocabulary, no dimension
            return Resolved()

    entity, entity_phrase = _head_entity(lowered, dimensions)

    for match in _BREAKDOWN.finditer(lowered):
        phrase = match.group("phrase").strip()
        for candidate in _candidates(phrase) or [phrase]:
            found = _as_dimension(candidate, dimensions)
            if found:
                return Resolved(
                    dimension=found, phrase=candidate, rule="breakdown",
                    entity=entity, entity_phrase=entity_phrase,
                    because=(f"the question asks for a breakdown by "
                             f"{candidate}"))

    for match in _NAMED.finditer(lowered):
        phrase = match.group("phrase").strip()
        # Longest first, but the LAST words of the modifier are the head of it:
        # "total exposure distribution" is an exposure distribution and the
        # dimension, if any, is the word next to the shape word.
        words = phrase.split()
        for size in range(min(_HEAD_WORDS, len(words)), 0, -1):
            candidate = " ".join(words[-size:])
            if candidate in _STOP:
                continue
            found = _as_dimension(candidate, dimensions)
            if found:
                return Resolved(
                    dimension=found, phrase=candidate, rule="named",
                    entity=entity, entity_phrase=entity_phrase,
                    because=(f"the question asks for a {candidate} "
                             f"distribution"))

    head = _HEAD.match(lowered)
    if head is not None:
        for candidate in _candidates(head.group("phrase")):
            found = _as_dimension(candidate, dimensions)
            if found:
                return Resolved(
                    dimension=found, phrase=candidate, rule="requested",
                    because=(f"the question asks for {candidate}, so each row "
                             f"is one {candidate.rstrip('s')}"))
            if _CUSTOMER_NOUNS.match(candidate) or _FACILITY_NOUNS.match(candidate):
                break

    return Resolved(entity=entity, entity_phrase=entity_phrase)


def _head_entity(lowered: str, dimensions: Any) -> tuple[str, str]:
    """The head noun when it is an entity rather than a dimension.

    Only the HEAD. "Which sectors have borrowers with rising PD?" names
    borrowers, and they are a condition on which sectors qualify rather than
    what the answer has one row of.
    """
    head = _HEAD.match(lowered)
    if head is None:
        return ("", "")
    for candidate in _candidates(head.group("phrase")):
        if _as_dimension(candidate, dimensions):
            return ("", "")
        if _CUSTOMER_NOUNS.match(candidate):
            return ("customer", candidate)
        if _FACILITY_NOUNS.match(candidate):
            return ("facility", candidate)
    return ("", "")


def clarification(found: Resolved) -> str:
    """What to ask when the head noun and the breakdown want different tables."""
    entity = found.entity_phrase or found.entity or "rows"
    dimension = found.phrase or found.dimension.replace("_", " ")
    return (
        f"Should the answer be one row per {entity.rstrip('s')}, or one row "
        f"per {dimension.rstrip('s')}? The question asks for {entity} and "
        f"also asks to group by {dimension}, and those are two different "
        f"tables — say which one you want, or ask for {entity} with their "
        f"{dimension} shown as a column.")


__all__ = ["ALIASES", "DIMENSIONS_VERSION", "Resolved", "clarification", "read"]
