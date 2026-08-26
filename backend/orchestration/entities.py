"""
Turning the names in a question into governed values.

"Real Estate", "Contracting", "Stage 2", "Summit Power" — a question names
things, and every one of them has to resolve to something the catalogue
actually contains before it becomes a filter. Two failures are being avoided:

**Hallucinating a customer.** A question naming a borrower CreditProbe has never
heard of must say so. Quietly matching it to the nearest name produces an
analysis of the wrong company, correctly computed.

**Missing a real one.** "real estate", "Real-Estate" and "REAL ESTATE" are the
same sector, and a filter that misses because of a hyphen returns an empty
result that reads as "there is nothing there".

So matching is exact first, then normalised, then fuzzy with a floor and a
recorded confidence — and a fuzzy match near the floor is reported as a
suggestion rather than applied.
"""

from __future__ import annotations

import difflib
import functools
import logging
import re
from dataclasses import dataclass
from typing import Any

#: Below this, two strings are not the same thing however close they look.
#: 0.82 keeps "Real Estate"/"real-estate" and rejects "Retail"/"Real Estate".
logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.82

#: A fuzzy match at or above this is applied; between the floor and this it is
#: offered as a suggestion, because a filter the user did not ask for is a
#: different question.
CONFIDENT_SIMILARITY = 0.92


@dataclass(frozen=True)
class EntityMatch:
    kind: str
    value: str
    #: What the user typed.
    phrase: str
    confidence: float
    exact: bool

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "value": self.value}


def _normalise(text: str) -> str:
    """Case, punctuation and spacing removed; the rest kept."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def resolve_entities(question: str, context: Any) -> list[dict[str, str]]:
    """Every governed dimension value the question names.

    Returns the plain shape the Reading carries. `match_dimension` is the
    function to call when the confidence and the phrase matter.
    """
    return [m.to_dict() for m in match_all(question, context.dimensions)]


def match_all(question: str, dimensions: dict[str, list[str]]) -> list[EntityMatch]:
    text = " ".join(str(question or "").split())
    lowered = text.lower()
    out: list[EntityMatch] = []
    claimed: set[str] = set()

    # Longest values first, so "Real Estate Development" is not shadowed by
    # "Real Estate" matching inside it.
    for kind, values in dimensions.items():
        for value in sorted(values, key=lambda v: -len(str(v))):
            token = str(value)
            if not token:
                continue
            pattern = r"\b" + re.escape(token.lower()).replace(r"\ ", r"[\s\-_]+") + r"\b"
            found = re.search(pattern, lowered)
            if found and found.group(0) not in claimed:
                claimed.add(found.group(0))
                out.append(EntityMatch(kind=kind, value=token,
                                       phrase=found.group(0), confidence=1.0,
                                       exact=True))
    return out


def match_dimension(phrase: str, kind: str,
                    values: list[str]) -> EntityMatch | None:
    """One phrase against one dimension's permitted values.

    Used when something upstream — a model reading, a follow-up — has already
    decided a phrase is meant to be a value of this dimension, and the only
    question is which one.
    """
    if not phrase or not values:
        return None
    wanted = _normalise(phrase)
    by_norm = {_normalise(str(v)): str(v) for v in values}

    if wanted in by_norm:
        return EntityMatch(kind=kind, value=by_norm[wanted], phrase=phrase,
                           confidence=1.0, exact=True)

    close = difflib.get_close_matches(wanted, list(by_norm), n=1,
                                      cutoff=MIN_SIMILARITY)
    if not close:
        return None
    score = difflib.SequenceMatcher(None, wanted, close[0]).ratio()
    return EntityMatch(kind=kind, value=by_norm[close[0]], phrase=phrase,
                       confidence=round(score, 3), exact=False)


def unresolved_names(question: str, context: Any) -> list[str]:
    """Capitalised phrases that look like a named thing and matched nothing.

    Deliberately narrow. It is looking for "Summit Power" in "how is Summit
    Power doing" so the answer can say that name is not in the book, rather
    than silently analysing the whole portfolio.
    """
    text = " ".join(str(question or "").split())
    matched = {m.phrase.lower() for m in match_all(text, context.dimensions)}
    # Every WORD of every governed value, so a fragment of a multi-word value is
    # not reported as an unknown borrower. "Transport & Logistics" is a sector;
    # the ampersand breaks it into two capitalised fragments, and reporting
    # "Transport" as a name nobody has heard of turned a valid ranking into a
    # refusal.
    governed = {
        word
        for values in (context.dimensions or {}).values()
        for value in values
        for word in re.findall(r"[a-z0-9]+", str(value).lower())
    }

    candidates: list[str] = []
    for phrase in re.findall(r"\b(?:[A-Z][a-z0-9&.'-]+)(?:\s+[A-Z][a-z0-9&.'-]+)*\b",
                             text):
        # "Summit Power's exposure" names Summit Power. The possessive is
        # grammar, and reporting it as part of the name makes the "we have
        # never heard of this borrower" message look like a parsing bug.
        phrase = re.sub(r"['\u2019]s$", "", phrase).strip()
        # "Show Real Estate customers whose…" opens with a capitalised verb, and
        # the regex reads "Show Real Estate" as one proper noun. Dropping a
        # leading English word leaves the governed value behind it — without
        # this, a perfectly ordinary request came back as "CreditProbe could not
        # find Show Real Estate in the published data".
        head = phrase.split(" ", 1)
        while len(head) == 2 and head[0].lower() in _NOT_A_NAME:
            phrase = head[1].strip()
            head = phrase.split(" ", 1)
        if len(phrase) < 4 or phrase.lower() in matched:
            continue
        if phrase.lower() in _NOT_A_NAME:
            continue
        words = set(re.findall(r"[a-z0-9]+", phrase.lower()))
        if words and words <= governed:
            continue
        # A capitalised word at the start of a sentence is usually just English.
        if text.startswith(phrase) and " " not in phrase:
            continue
        candidates.append(phrase)
    return candidates


def known_borrower(name: str) -> str | None:
    """The published borrower this name refers to, if there is one.

    A real read through the Data Access Layer rather than a scan of the
    vocabulary: there are thousands of borrowers and the vocabulary deliberately
    holds only the small dimensions a planner filters on. Cached for the life of
    the process, because the answer changes only when a dataset is published.
    """
    wanted = " ".join(str(name or "").lower().split())
    if not wanted:
        return None
    for candidate in _borrower_names():
        text = " ".join(candidate.lower().split())
        if text == wanted or wanted in text or text in wanted:
            return candidate
    return None


@functools.lru_cache(maxsize=1)
def _borrower_names() -> tuple[str, ...]:
    """Every borrower name in the latest published period."""
    try:
        from backend.data_access import get_data_source
        from backend.data_access.context import AnalysisContext
        from backend.engine.helpers import FACILITY

        source = get_data_source()
        periods = source.periods(FACILITY)
        if not periods:
            return ()
        latest = periods[-1]
        frame = source.fetch(FACILITY, context=AnalysisContext(period=latest),
                             fields=["borrower_name"], period=latest)
        return tuple(sorted({str(v) for v in frame["borrower_name"].dropna()}))
    except Exception as e:  # noqa: BLE001 - nothing published yet
        logger.warning("Could not read borrower names: %s", e)
        return ()


#: Capitalised words that are English rather than entities.
_NOT_A_NAME = frozenset({
    "what", "which", "show", "list", "how", "why", "when", "where", "who",
    "creditprobe", "ifrs", "stage", "the", "give", "find", "identify", "tell",
    "data", "please", "real", "does", "did", "are", "is", "can", "could",
})


__all__ = [
    "CONFIDENT_SIMILARITY",
    "MIN_SIMILARITY",
    "EntityMatch",
    "match_all",
    "known_borrower",
    "match_dimension",
    "resolve_entities",
    "unresolved_names",
]
