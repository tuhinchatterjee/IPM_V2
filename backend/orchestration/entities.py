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


def _value_pattern(kind: str, token: str) -> str:
    """How a dimension VALUE is recognised in free text.

    The defect this closes, and it was a wide one. `application_score_band`
    and `behavioural_score_band` carry the values "A", "A+", "B"…"E", and this
    matcher looked for each of them as a bare word. So

        "give me a breakdown by product"

    resolved `application_score_band = A` out of the indefinite article, and
    the answer came back about score band A alone — correctly computed,
    wrongly scoped, under a note saying "Restricted to application score band =
    A" that a reader skims straight past. Any question containing the word "a"
    was affected, which is most of them.

    `resolve_dimension_value` already refuses a value this short. This reader
    did not, and the two were the same vocabulary read two ways.

    So a SHORT value — anything under `MIN_MATCHABLE_VALUE`, letters or digits
    — matches only where the dimension is NAMED: "band A", "score band A",
    "stage 2", never a bare "A" or a bare "2". A value long enough to be
    unmistakable is matched as it always was.
    """
    from backend.orchestration.vocabulary import MIN_MATCHABLE_VALUE

    if token.isdigit():
        return _numeric_pattern(kind, token)

    literal = re.escape(token.lower()).replace(r"\ ", r"[\s\-_]+")
    if len(token) >= MIN_MATCHABLE_VALUE:
        return r"\b" + literal + r"\b"

    # Short enough to appear by accident. The dimension's own noun has to be
    # beside it — and the noun may be the last word of a compound name, so
    # "application_score_band" is reached by "band" as well as by the whole.
    noun = re.escape(str(kind).rsplit("_", 1)[-1].lower())
    return rf"\b{noun}s?\s*(?:of\s+)?{literal}(?![\w+])"


@functools.lru_cache(maxsize=1)
def _flag_phrases() -> tuple[tuple[str, str, str], ...]:
    """Phrases that name a two-valued dimension and its value at once.

    Read from the vocabulary so there is one list rather than two that drift.
    Sorted longest-first, which is what makes a negation beat the positive
    phrase inside it.
    """
    from backend.orchestration.vocabulary import Vocabulary

    return tuple(sorted(Vocabulary.FLAG_PHRASES,
                        key=lambda row: -len(row[0])))


def match_all(question: str, dimensions: dict[str, list[str]]) -> list[EntityMatch]:
    text = " ".join(str(question or "").split())
    lowered = text.lower()
    out: list[EntityMatch] = []
    claimed: set[str] = set()

    # A TWO-VALUED dimension is named by a phrase, never by its value. Its
    # values are "True" and "False", and nobody types either — so
    # "salary transfer" matched nothing, the condition was dropped in silence,
    # and the answer came back about the whole product. Matched first and
    # longest-first, so "non-salary-transfer" beats the "salary transfer"
    # inside it.
    for phrase, kind, value in _flag_phrases():
        if kind not in dimensions:
            continue
        if value not in {str(v) for v in dimensions[kind]}:
            continue
        pattern = r"\b" + re.escape(phrase).replace(r"\ ", r"[\s\-_]+") + r"\b"
        found = re.search(pattern, lowered)
        if found and found.group(0) not in claimed and kind not in {
                m.kind for m in out}:
            claimed.add(found.group(0))
            out.append(EntityMatch(kind=kind, value=value,
                                   phrase=found.group(0), confidence=1.0,
                                   exact=True))

    # Longest values first, so "Real Estate Development" is not shadowed by
    # "Real Estate" matching inside it.
    for kind, values in dimensions.items():
        for value in sorted(values, key=lambda v: -len(str(v))):
            token = str(value)
            if not token:
                continue
            pattern = _value_pattern(kind, token)
            found = re.search(pattern, lowered)
            if found and found.group(0) not in claimed:
                claimed.add(found.group(0))
                out.append(EntityMatch(kind=kind, value=token,
                                       phrase=found.group(0), confidence=1.0,
                                       exact=True))
    return out


def _numeric_pattern(kind: str, token: str) -> str:
    """A whole-number match a decimal literal cannot satisfy, and — for a
    dimension whose values are bare codes — one that needs the dimension named.

    Two failures, one root: a number in a question is usually a quantity, and
    IFRS 9 stages are the values "1", "2" and "3".

    **A word boundary is the wrong boundary for a digit.** `.` is a non-word
    character, so `\b1\b` matches inside "1.2". "Which borrowers have a DSCR
    below 1.2?" resolved a stage filter of 1 AND a stage filter of 2 out of the
    threshold. The answer came back about a different population, correctly
    computed, and nothing said so until the invariant check found that the rows
    did not match the filter the question was recorded as carrying.

    **And a bare digit is not a stage.** "a DSCR of 2" names a ratio. The
    governed vocabulary already refuses to infer these dimensions from free
    text — `AMBIGUOUS_DIMENSIONS` exists for exactly this — and the entity
    matcher was the reader that did not honour it. So a numeric value of an
    ambiguous dimension matches only where the dimension is NAMED: "stage 2",
    never "2".
    """
    from backend.orchestration import vocabulary as vc

    digits = re.escape(str(token))
    # Part of a longer number when a digit sits beside it, or when a decimal
    # point or thousands separator with a DIGIT on its far side does. The digit
    # on the far side is what makes the separator a separator: a trailing full
    # stop is a sentence ("customers in Stage 2.") and a trailing comma is a
    # list ("stage 1, 2 or 3"), neither of which is 1,200.
    bounded = rf"(?<!\d)(?<!\d[.,]){digits}(?!\d)(?![.,]\d)"
    if kind not in vc.AMBIGUOUS_DIMENSIONS:
        return bounded
    # The noun can be shared across a coordination — "stages 2 and 3" names
    # both — so a chain of coordinated numbers may sit between it and this one.
    # The chain still has to START at the noun, which is what keeps "a DSCR
    # between 1 and 2" from resolving a stage out of its upper bound.
    noun = re.escape(str(kind).rsplit("_", 1)[-1].lower())
    # `\s*` rather than `\s+`: people write "stage2" as often as "stage 2",
    # and requiring the space meant a filter a reader plainly stated was
    # dropped without a word.
    return rf"\b{noun}s?\s*(?:of\s+)?(?:\d+\s*(?:,|and|or)\s+)*{bounded}"


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
    # The names of the DATA are governed vocabulary too — the domain heading,
    # the dataset and its business name. The product tells the user to type
    # them: "Cockpit Data" is the heading on the Data Builder screen and the
    # opening words of the Cockpit's own suggested questions. Without this,
    # "Use Cockpit Data for August 2026" was read as a question about a
    # borrower called Cockpit Data and refused, on a turn where the only
    # unrecognised thing was the name of the book itself.
    governed |= _catalogue_vocabulary()

    # A name does not span a sentence. Without this, "Something seems wrong
    # with Contracting. Investigate it." reads "Contracting. Investigate" as one
    # proper noun and refuses a question about a sector CreditProbe knows well.
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text) if part]

    # Each phrase is kept WITH the sentence it came from. The rule that a
    # capitalised word opening a sentence is ordinary English is a rule about
    # sentences, and applying it only to the first one is how "Explain the
    # SICR evidence for every borrower" — the second sentence of a perfectly
    # clear question — was reported as a borrower nobody had heard of.
    found: list[tuple[str, str]] = [
        (sentence, match)
        for sentence in sentences
        for match in re.findall(
            r"\b(?:[A-Z][a-z0-9&'-]+)(?:\s+[A-Z][a-z0-9&'-]+)*\b", sentence)]

    candidates: list[str] = []
    for sentence, phrase in found:
        opens_sentence = sentence.startswith(phrase)
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
        # A capitalised word at the start of a sentence is usually just
        # English — an imperative verb, most often. True of EVERY sentence,
        # not only the first: "Explain", "Consider", "Separate" and "Rank" all
        # open a clause in the questions a credit officer actually types.
        if opens_sentence and " " not in phrase:
            continue
        candidates.append(phrase)
    return candidates


#: The catalogue vocabulary, held only once a real catalogue read has produced
#: one. Deliberately not an `lru_cache`: the read goes to PostgreSQL, and
#: caching an EMPTY answer from a turn taken before the database was reachable
#: would leave the product refusing its own domain heading for the life of the
#: process — the exact failure this vocabulary exists to prevent, made
#: permanent and intermittent at once.
_CATALOGUE_WORDS: frozenset[str] | None = None


def _catalogue_vocabulary() -> frozenset[str]:
    """Every word of every governed dataset, domain and business name."""
    global _CATALOGUE_WORDS
    if _CATALOGUE_WORDS is not None:
        return _CATALOGUE_WORDS

    words: set[str] = set(_shipped_catalogue_vocabulary())
    published = False
    try:
        from backend.data_access.catalog import get_catalog

        datasets = list(get_catalog().all())
        for dataset in datasets:
            for text in (dataset.name, dataset.domain, dataset.business_name):
                words.update(re.findall(r"[a-z0-9]+", str(text or "").lower()))
        published = bool(datasets)
    except Exception as e:  # noqa: BLE001 - nothing published yet
        logger.warning("Could not read the catalogue vocabulary: %s", e)

    if published:
        _CATALOGUE_WORDS = frozenset(words)
    return frozenset(words)


@functools.lru_cache(maxsize=1)
def _shipped_catalogue_vocabulary() -> frozenset[str]:
    """The same names, read from the catalogue file the build ships.

    The domain heading and the dataset names are decided when the book is BUILT,
    not when it is published, and the file that records them sits next to the
    running code. Reading it means the words the product itself puts on screen
    and into its own suggested questions are governed vocabulary from the first
    turn, whether or not the catalogue table has been read yet.
    """
    words: set[str] = set()
    try:
        import json

        from backend.config import settings
        from backend.data_access.catalogue_io import CATALOGUE_FILE

        path = settings.metadata_dir / CATALOGUE_FILE
        if not path.exists():
            return frozenset()
        document = json.loads(path.read_text())
        for dataset in document.get("datasets", []) or []:
            for key in ("name", "domain", "business_name"):
                words.update(
                    re.findall(r"[a-z0-9]+", str(dataset.get(key) or "").lower()))
    except Exception as e:  # noqa: BLE001 - no catalogue file shipped
        logger.warning("Could not read the shipped catalogue vocabulary: %s", e)
    return frozenset(words)


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
#: Words that open a request rather than name a thing.
#:
#: The regex that finds proper nouns cannot tell "Only Contracting" from
#: "Summit Power", so a follow-up narrowing the previous result to a governed
#: sector came back as "CreditProbe could not find Only Contracting in the
#: published data" — a refusal, on a turn where everything was recognised
#: except the first word.
#: Words that are never a borrower, however they are capitalised.
#:
#: Two jobs. A single word here is not reported as an unknown name, and a
#: phrase STARTING with one has it stripped — so "Explain SICR evidence"
#: becomes "SICR evidence" rather than a company called Explain.
#:
#: Everything added below is an ordinary instruction verb or an analytical
#: term a credit officer types constantly. None of them is a plausible
#: borrower name, and a bank that genuinely has an obligor called "Separate"
#: has a naming problem this list is not the place to solve.
_NOT_A_NAME = frozenset({
    "what", "which", "show", "list", "how", "why", "when", "where", "who",
    "creditprobe", "ifrs", "stage", "the", "give", "find", "identify", "tell",
    "data", "please", "real", "does", "did", "are", "is", "can", "could",
    "only", "just", "now", "also", "add", "rank", "sort", "order", "open",
    "and", "but", "then", "keep", "include", "exclude", "restrict", "narrow",
    "filter", "replace", "compare", "investigate", "display", "return",
    # -- instruction verbs the reported questions actually opened with
    "explain", "consider", "separate", "distinguish", "summarise", "summarize",
    "describe", "assess", "evaluate", "review", "analyse", "analyze",
    "highlight", "flag", "group", "break", "split", "focus", "look", "check",
    "compute", "calculate", "measure", "quantify", "attribute", "decompose",
    "rate", "score", "select", "take", "use", "using", "based", "for", "each",
    "every", "their", "these", "those", "them", "both", "any", "all", "some",
    # -- auxiliaries. "Has Zenith Petrochemical breached a covenant?" opens
    # with one, and without these the whole phrase "Has Zenith Petrochemical"
    # is reported as the unknown name — which is worse than reporting nothing,
    # because the message then names a borrower that does not exist in a form
    # nobody typed.
    "has", "have", "had", "was", "were", "will", "would", "should", "shall",
    "may", "might", "must", "am", "be", "been", "being",
    # -- the calendar. A retail book is selected by month, so "August 2026",
    # "for Q2", "since January" and "compare with July" are typed constantly.
    # Without these, the FIRST question the product's own suggested prompts
    # tell a user to ask — "Use Cockpit Data for August 2026..." — came back as
    # "CreditProbe could not find August in the published data".
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "today", "yesterday", "month", "months", "quarter", "quarters",
    "year", "years", "ytd", "qtd", "mtd", "latest", "last", "previous",
    "prior", "current", "next", "period", "periods", "snapshot", "vintage",
    # -- analytical vocabulary that is a concept, never an obligor
    "sicr", "ecl", "pd", "lgd", "ead", "dpd", "ebitda", "raroc", "npl",
    "watchlist", "covenant", "collateral", "utilisation", "utilization",
    "leverage", "liquidity", "concentration", "materiality", "macroeconomic",
    "quantitative", "qualitative", "forward", "looking", "borrower",
    "borrowers", "customer", "customers", "counterparty", "counterparties",
    "portfolio", "sector", "sectors", "exposure", "facility", "facilities",
    # -- the product's OWN vocabulary. "Which deserve an Early Warning
    # investigation?" came back "CreditProbe could not find Early Warning in
    # the published data ... a borrower it has never been given cannot be
    # looked up", about a module in its own navigation. "What's the Gini?"
    # was refused the same way. A capitalised noun that names a screen or a
    # statistic is not an obligor, and telling a reader to ask a Data Steward
    # to onboard "Early Warning" is the product failing to recognise itself.
    "early", "warning", "warnings", "signal", "signals", "cockpit",
    "playbook", "lens", "lenses", "investigation", "investigations", "trace",
    "scorecard", "scorecards", "validation", "gini", "auc", "roc", "ks",
    "psi", "brier", "calibration", "discrimination", "stability", "drift",
    "characteristic", "characteristics", "woe", "credit", "probe",
    "creditprobe", "workspace", "studio", "metric", "metrics", "dashboard",
    "report", "reports", "analysis", "analyses", "what", "if",
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
