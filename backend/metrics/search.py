"""Finding a metric by typing part of what you call it.

§8.3 asks for a metric picker that does not open with the whole catalogue.
Sixty-two governed metrics in a scrolling list is a list nobody reads: people
give up and rebuild a number they already had, which is how two definitions of
"default rate" end up on two dashboards.

So the picker starts empty and answers what you type. Three properties matter
more than cleverness here:

**It is deterministic.** No model ranks these. The same query returns the same
metrics in the same order on every machine, which is what lets a test assert
that typing ``delinq 30`` narrows to the two 30-day metrics rather than
asserting something vague about relevance.

**It answers to the words people use.** "NPL rate", "bad rate" and "default
rate" are one metric. The aliases are part of the definition (see
:mod:`backend.metrics.catalogue`), and they are searched with the same weight
logic as the name, one tier below it.

**It never suggests a metric the asker may not read.** ``readable`` is applied
before ranking, not after, so a permitted metric is never pushed off the end
of the list by a hidden one.

Ranking is tiered, strongest first, and a stronger tier always outranks a
weaker one regardless of score:

===== ===========================================================
 Tier  Match
===== ===========================================================
 1     the query is exactly the name, an alias, or the metric id
 2     the name begins with the query
 3     an alias begins with the query
 4     every word of the query prefixes a word of the metric
 5     the query is a near-miss spelling of the name or an alias
===== ===========================================================

Tier 4 is what makes multi-word typing narrow rather than widen: every token
must match *something*, so each word you add can only remove candidates.

When nothing matches but the words name something CreditProbe knows it cannot
calculate here, :func:`unsupported_for` returns that entry, so the picker can
say why the metric is missing instead of showing an empty list.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from backend.metrics.catalogue import MetricDefinition, Unsupported

#: How many suggestions a typeahead shows before it stops being a typeahead.
DEFAULT_LIMIT = 8

#: Below this, a near-miss is a coincidence rather than a typo.
FUZZY_FLOOR = 0.72

#: Fuzzy matching on one or two characters matches everything, so it waits.
FUZZY_MIN_QUERY = 4

TIER_EXACT = 5
TIER_NAME_PREFIX = 4
TIER_ALIAS_PREFIX = 3
TIER_TOKENS = 2
TIER_FUZZY = 1

#: What a word matching in each place is worth, in tier 4. A word found in the
#: name says more than the same word found in the prose definition.
_WEIGHTS = (("name", 12.0), ("alias", 9.0), ("id", 7.0), ("domain", 4.0),
            ("definition", 2.0))

_WORD = re.compile(r"[a-z0-9]+")

#: Words that carry no signal in a catalogue where nearly everything is a rate
#: of something. Dropped from a multi-word query only when other words remain.
_NOISE = frozenset({"the", "a", "an", "of", "by", "for", "in", "on", "and",
                    "show", "me", "what", "is"})


def _words(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(text.lower()))


def _normalise(text: str) -> str:
    """Lowercased, punctuation-free, single-spaced, for exact comparison.

    ``"30+ DPD"`` and ``"30 dpd"`` are the same query typed two ways.
    """
    return " ".join(_words(text))


@dataclass(frozen=True)
class Hit:
    """One suggestion, and why it was suggested.

    ``matched`` and ``why`` exist so the picker can show *"matched alias: bad
    rate"* under a result named "Retail Default Rate". A suggestion whose
    reason is invisible looks like a bug.
    """

    metric: MetricDefinition
    tier: int
    score: float
    matched: str
    why: str

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric.metric_id,
            "name": self.metric.name,
            "domain": self.metric.domain,
            "unit": self.metric.unit,
            "definition": self.metric.definition,
            "origin": self.metric.origin,
            "status": self.metric.status,
            "governed": self.metric.governed,
            "datasets": list(self.metric.datasets),
            "matched": self.matched,
            "why": self.why,
        }


# --------------------------------------------------------------- the index


@dataclass(frozen=True)
class _Indexed:
    metric: MetricDefinition
    name: str
    aliases: tuple[str, ...]
    identifier: str
    #: word -> best weight of the place it was found in
    words: dict[str, float]


def _index(metric: MetricDefinition) -> _Indexed:
    places = {
        "name": metric.name,
        "alias": " ".join(metric.aliases),
        "id": metric.metric_id.replace(".", " ").replace("_", " "),
        "domain": f"{metric.domain} {metric.portfolio}",
        "definition": metric.definition,
    }
    words: dict[str, float] = {}
    for place, weight in _WEIGHTS:
        for word in _words(places[place]):
            if words.get(word, 0.0) < weight:
                words[word] = weight
    return _Indexed(
        metric=metric,
        name=_normalise(metric.name),
        aliases=tuple(_normalise(a) for a in metric.aliases),
        identifier=_normalise(metric.metric_id.replace(".", " ")),
        words=words,
    )


def _visible(metric: MetricDefinition,
             readable: Iterable[str] | None) -> bool:
    """Whether the asker may see this metric at all.

    A metric is visible only when *every* dataset it reads is readable: a
    ratio whose denominator comes from a dataset you cannot see is a number
    you cannot be shown, not a number to show partially.
    """
    if readable is None:
        return True
    allowed = set(readable)
    return all(dataset in allowed for dataset in metric.datasets)


# -------------------------------------------------------------- the search


def _tier_and_score(entry: _Indexed, query: str,
                    tokens: Sequence[str]) -> tuple[int, float, str, str]:
    """Best tier this metric reaches for this query, or tier 0 for no match."""
    name, aliases = entry.name, entry.aliases

    if query == name:
        return TIER_EXACT, 100.0, "name", "exact name"
    if query == entry.identifier:
        return TIER_EXACT, 99.0, "id", "exact metric id"
    for alias in aliases:
        if query == alias:
            return TIER_EXACT, 98.0, "alias", f'exact alias "{alias}"'

    if name.startswith(query):
        # A shorter name is a closer match: "ECL Coverage" before "Stage 1 ECL
        # Coverage" when the query is "ecl cov".
        return TIER_NAME_PREFIX, 100.0 - min(len(name), 90) / 2.0, "name", \
            "name starts with what you typed"
    for alias in aliases:
        if alias.startswith(query):
            return TIER_ALIAS_PREFIX, 100.0 - min(len(alias), 90) / 2.0, \
                "alias", f'alias "{alias}" starts with what you typed'

    if tokens:
        total = 0.0
        places: list[str] = []
        for token in tokens:
            best = 0.0
            for word, weight in entry.words.items():
                if word.startswith(token):
                    hit = weight if word == token else weight - 1.0
                    best = max(best, hit)
            if best <= 0.0:
                break
            total += best
            places.append(token)
        else:
            return TIER_TOKENS, total / len(tokens), "words", \
                "matched every word you typed"

    if len(query) >= FUZZY_MIN_QUERY:
        best, against = 0.0, ""
        for candidate in (name, *aliases):
            ratio = SequenceMatcher(None, query, candidate).ratio()
            if ratio > best:
                best, against = ratio, candidate
        if best >= FUZZY_FLOOR:
            return TIER_FUZZY, best * 100.0, "spelling", \
                f'closest match is "{against}"'

    return 0, 0.0, "", ""


def search(metrics: Iterable[MetricDefinition], query: str, *,
           limit: int = DEFAULT_LIMIT,
           readable: Iterable[str] | None = None,
           domain: str = "") -> list[Hit]:
    """Rank metrics against what somebody has typed so far.

    An empty query returns nothing on purpose: §8.3 asks that the catalogue is
    not dumped into a dropdown. :func:`browse` is the deliberate way to see it
    all.

    ``readable`` is the set of dataset names the asker may read. Passing
    ``None`` means no restriction, which is correct only for callers that have
    already resolved permissions or are not acting for a user.
    """
    text = _normalise(query)
    if not text:
        return []

    tokens = list(_words(text))
    meaningful = [t for t in tokens if t not in _NOISE]
    if meaningful:
        tokens = meaningful

    hits: list[Hit] = []
    for metric in metrics:
        if domain and metric.domain != domain:
            continue
        if not _visible(metric, readable):
            continue
        entry = _index(metric)
        tier, score, matched, why = _tier_and_score(entry, text, tokens)
        if tier:
            hits.append(Hit(metric=metric, tier=tier, score=score,
                            matched=matched, why=why))

    # A near-miss is only interesting when nothing matched properly. Typing
    # "30+ dpd" should not suggest the 60-day metric just because the two
    # names are three characters apart.
    if any(hit.tier > TIER_FUZZY for hit in hits):
        hits = [hit for hit in hits if hit.tier > TIER_FUZZY]

    # Name breaks the final tie so that ordering is stable across runs rather
    # than dependent on catalogue order.
    hits.sort(key=lambda h: (-h.tier, -h.score, h.metric.name))
    return hits[:max(0, limit)]


def browse(metrics: Iterable[MetricDefinition], *,
           readable: Iterable[str] | None = None,
           ) -> list[tuple[str, list[MetricDefinition]]]:
    """The whole catalogue, grouped by domain, for when somebody asks for it.

    Separate from :func:`search` because showing everything should be a thing
    a person chose, not the default state of a text box.
    """
    groups: dict[str, list[MetricDefinition]] = {}
    for metric in metrics:
        if not _visible(metric, readable):
            continue
        groups.setdefault(metric.domain, []).append(metric)
    for entries in groups.values():
        entries.sort(key=lambda m: m.name)
    return sorted(groups.items(), key=lambda pair: pair[0])


def unsupported_for(entries: Iterable[Unsupported], query: str, *,
                    limit: int = 3) -> list[Unsupported]:
    """Metrics CreditProbe knows about and cannot calculate here.

    Called when a search finds nothing, so the picker can answer "roll rate"
    with the reason it is unavailable rather than with silence. Never mixed
    into :func:`search` results: an unsupported entry is not a metric you can
    put on a lens.
    """
    text = _normalise(query)
    if not text:
        return []
    tokens = [t for t in _words(text) if t not in _NOISE] or list(_words(text))

    scored: list[tuple[float, str, Unsupported]] = []
    for entry in entries:
        haystack = set(_words(f"{entry.name} {entry.domain} {entry.metric_id}"))
        matched = sum(
            1 for token in tokens
            if any(word.startswith(token) for word in haystack))
        if matched == len(tokens):
            scored.append((-float(matched), entry.name, entry))
    scored.sort()
    return [entry for _, _, entry in scored[:max(0, limit)]]


__all__ = ["DEFAULT_LIMIT", "Hit", "search", "browse", "unsupported_for",
           "TIER_EXACT", "TIER_NAME_PREFIX", "TIER_ALIAS_PREFIX",
           "TIER_TOKENS", "TIER_FUZZY"]
