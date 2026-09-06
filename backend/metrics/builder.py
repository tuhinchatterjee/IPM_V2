"""Building a metric, and a lens, by describing it.

§1–§11 of the Lenses brief. The product question this answers is not "can a
model write a formula" — it must not — but "can a person who knows what they
want, and does not know the schema, get a governed metric out of CreditProbe
without being handed a field list".

Four things, and the order they happen in is the design
-------------------------------------------------------
1. :func:`interpret` reads a sentence and says what it recognised: which
   governed data domains it names, which existing metrics answer to it, which
   dimension it wants a chart across, which period it means. It answers with
   CANDIDATES rather than a decision, because the next screen shows them as
   options the person picks from.
2. :func:`propose` turns that into a metric skeleton when nothing existing
   fits — a kind, a dataset, a numerator term, and the filters it heard.
3. :func:`explain` renders one metric definition three ways at once: the
   algebra, the plain-English execution logic, and the actual SQL the engine
   will run. §7 requires those three to stay reconciled through an edit, and
   they do because all three are generated from the same tree every time it
   is asked for. There is no stored prose to drift.
4. :func:`preview` runs it against real stored data and shows every step §8
   asks for: the dataset and domain, the periods available, the fields read,
   the filters applied, each numerator and denominator term with its own
   value and row count, the aggregation, and the final arithmetic.

What is deliberately not here
------------------------------
**No model writes a formula.** Every candidate this module returns is either
a metric already in the governed catalogue or a skeleton whose every part —
dataset, field, aggregation, comparison — was matched against the catalogue
before it was offered. A sentence CreditProbe does not recognise produces a
question, not a guess.

**No prose is stored.** The plain-English reading and the SQL are computed
from the formula on every request. A stored description would be right when it
was written and wrong after the first edit, and the screen would show a
definition that disagrees with the number.

**Nothing here relaxes the domain boundary.** `interpret` and `propose` read
the catalogue through the same permission-aware entry points every other
surface uses, so a dataset the asker may not read cannot be suggested, and a
metric built on one cannot be assembled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.metrics import search
from backend.metrics.catalogue import MetricDefinition
from backend.metrics.formula import (
    AGGREGATIONS,
    NEEDS_DENOMINATOR,
    Condition,
    Formula,
    Side,
    Term,
)

BUILDER_VERSION = "1.0.0"

#: How many of each kind of candidate a screen is offered. Enough to choose
#: from, few enough that choosing is not itself a task.
CANDIDATES = 6


# ---------------------------------------------------------------------------
# Reading a sentence
# ---------------------------------------------------------------------------

#: Words that say "break this down", and what follows one is a dimension.
_BY = re.compile(r"\b(?:by|per|across|split by|broken down by|grouped by)\s+"
                 r"([a-z][a-z0-9 _-]{2,40})", re.I)

#: Words that say "over time".
_TREND = re.compile(r"\b(trend|over time|month by month|quarter by quarter|"
                    r"monthly|quarterly|time series|history|historic)\b", re.I)

#: A period written the way people write one.
_PERIOD = re.compile(r"\b(Q[1-4]\s*20\d\d|20\d\d-\d{1,2}|20\d\d)\b", re.I)

#: Words that mean "I want a new one", used only to break a tie: a sentence
#: that names an existing metric gets that metric whatever else it says.
_NEW = re.compile(r"\b(new|custom|my own|build|create|define|invent)\b", re.I)

#: Filler that carries no signal when matching the catalogue.
#:
#: The second block is the part worth explaining. "trend", "over", "time" and
#: "monthly" are not filler in the sentence — they are how somebody asks for a
#: series, and `_TREND` reads them for exactly that. What they must not also
#: do is stand as evidence about which METRIC is meant, and they were: the
#: typeahead's fuzzy tier matched the standalone word "over" to "Overlay" and
#: "Management Overlay" came back as the best reading of "delinquency trend
#: over time". A word this module has already consumed for its shape does not
#: get a second vote on its subject.
_STOP = frozenset("""
a an and are as at be built by can create dashboard define for from how i
in is it lens like me monitor my need new of on or our show that the them
they to track want watch we what which with would

trend trends over time times monthly quarterly history historic series
across split grouped broken down per each every
""".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())]


def _signal(text: str) -> list[str]:
    words = _words(text)
    meaningful = [w for w in words if w not in _STOP and len(w) > 2]
    return meaningful or words


@dataclass
class DomainOption:
    """A governed data domain the sentence might mean.

    `chosen` is what the screen pre-ticks. It is a suggestion the person
    overrides — §3 asks for clickable options AND free text, so nothing here
    is a decision.
    """

    name: str
    metrics: int
    matched: str
    chosen: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "metrics": self.metrics,
                "matched": self.matched, "chosen": self.chosen}


@dataclass
class Intent:
    """What CreditProbe understood, as options rather than as a decision."""

    text: str
    domains: list[DomainOption] = field(default_factory=list)
    portfolios: list[str] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    over_time: bool = False
    dimensions: list[str] = field(default_factory=list)
    unavailable: list[dict[str, Any]] = field(default_factory=list)
    wants_new: bool = False
    question: str = ""
    understood: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "domains": [d.to_dict() for d in self.domains],
            "portfolios": list(self.portfolios),
            "metrics": list(self.metrics),
            "charts": list(self.charts),
            "periods": list(self.periods),
            "over_time": self.over_time,
            "dimensions": list(self.dimensions),
            "unavailable": list(self.unavailable),
            "wants_new": self.wants_new,
            "question": self.question,
            "understood": self.understood,
        }


def interpret(text: str, *, user_id: int | None = None,
              readable: Any = None) -> Intent:
    """What a sentence asks for, as options a person then picks from.

    Deterministic. The same sentence produces the same reading on every
    machine, which is what lets a test assert it and what stops the builder
    from being a different product on a bad day.

    A compound sentence — "IFRS 9 coverage and retail delinquency" — resolves
    to BOTH domains rather than to whichever matched first. That is the case
    that decides whether this is a real interpreter or a keyword switch, so
    the domain pass scores every domain and keeps every one that scored.
    """
    from backend.metrics import service as metrics

    said = (text or "").strip()
    intent = Intent(text=said)
    if not said:
        intent.question = ("Describe what you want this lens to watch, in "
                           "your own words.")
        return intent

    pool = metrics.catalogue(user_id=user_id, readable=readable)
    tokens = _signal(said)

    # -- domains -----------------------------------------------------------
    #
    # Scored per domain, and EVERY domain that scores is kept. A sentence
    # naming two books is a request for two, and a picker that silently kept
    # one would drop half of what was asked for without saying so.
    counts: dict[str, int] = {}
    hit_words: dict[str, set[str]] = {}
    for metric in pool:
        if not metric.domain:
            continue
        counts.setdefault(metric.domain, 0)
        hit_words.setdefault(metric.domain, set())
    for domain in list(counts):
        vocabulary = set(_words(domain))
        for token in tokens:
            if any(w.startswith(token) or token.startswith(w)
                   for w in vocabulary if len(w) > 2):
                hit_words[domain].add(token)

    # A metric that matched contributes its own domain, which is how
    # "delinquency" reaches Retail Credit Risk without naming it — and how a
    # sentence naming four corporate domains by the word "corporate" is
    # narrowed to the one its metrics are actually in.
    found = _metrics_for(said, pool)
    for hit in found:
        if hit.metric.domain:
            hit_words.setdefault(hit.metric.domain, set()).add(
                f"metric:{hit.metric.name}")

    for metric in pool:
        if metric.domain in counts:
            counts[metric.domain] += 1

    # A domain that produced one of the best-matching metrics is chosen even
    # if its NAME was never said. "IFRS 9 coverage and retail delinquency"
    # names one domain and describes another, and a builder that kept only
    # the one it could see the name of would drop half the request — which is
    # the compound case §20 asks to be handled.
    #: The top three, not the top six. Six candidates for "exposure" span
    #: every corporate domain, and ticking all four says nothing.
    leading = {hit.metric.domain for hit in found[:3] if hit.metric.domain}
    scored = [(len(hit_words.get(d, set())), d) for d in counts]
    best = max((s for s, _ in scored), default=0)
    for score, domain in sorted(scored, key=lambda p: (-p[0], p[1])):
        if score == 0:
            continue
        intent.domains.append(DomainOption(
            name=domain, metrics=counts[domain],
            matched=", ".join(sorted(hit_words[domain])),
            chosen=domain in leading or score >= max(1, best)))

    intent.portfolios = sorted({
        m.portfolio for m in pool if m.portfolio
        and m.domain in {d.name for d in intent.domains if d.chosen}})

    # -- existing metrics --------------------------------------------------
    intent.metrics = [hit.to_dict() for hit in found[:CANDIDATES]]
    # Always, not only when nothing matched. "Roll rate for the retail book"
    # matches plenty of retail metrics, and the one thing the person asked for
    # by name is the one CreditProbe cannot do — so it has to say so beside
    # what it found rather than quietly offering four things they did not ask
    # for. §20: the truthful refusal is preserved.
    intent.unavailable = [entry.to_dict() for entry in
                          _unsupported_for(said)]

    # -- shape: a figure, a breakdown, or a trend --------------------------
    intent.over_time = bool(_TREND.search(said))
    for match in _BY.finditer(said):
        wanted = match.group(1).strip().lower()
        for metric in ([m for m in pool
                        if m.metric_id == intent.metrics[0]["metric_id"]]
                       if intent.metrics else []):
            for dimension in metrics.dimension_fields(metric):
                label = str(dimension["business_name"]).lower()
                name = str(dimension["name"]).lower()
                if wanted.startswith(name) or wanted.startswith(label) or (
                        label.startswith(wanted) or name.startswith(wanted)):
                    if dimension["name"] not in intent.dimensions:
                        intent.dimensions.append(dimension["name"])

    if intent.metrics and (intent.dimensions or intent.over_time):
        primary = intent.metrics[0]["metric_id"]
        metric = next(m for m in pool if m.metric_id == primary)
        offerable = {d["name"]: d for d in metrics.dimension_fields(metric)}
        wanted = list(intent.dimensions)
        if intent.over_time:
            over = next((d["name"] for d in offerable.values()
                         if d["over_time"]), "")
            if over and over not in wanted:
                wanted.insert(0, over)
        for name in wanted:
            chosen = offerable.get(name)
            if chosen is None:
                continue
            available, _refused = metrics.chart_types_for(metric, chosen)
            if not available:
                continue
            intent.charts.append({
                "metric_id": primary,
                "metric_name": metric.name,
                "dimension": name,
                "dimension_label": chosen["business_name"],
                "over_time": bool(chosen["over_time"]),
                "visual": "line" if "line" in available else available[0],
                "chart_types": available,
            })

    intent.periods = [p.strip() for p in _PERIOD.findall(said)]
    intent.wants_new = bool(_NEW.search(said)) and not intent.metrics

    intent.understood = _understood(intent)
    intent.question = _question(intent)
    return intent


def _unsupported_for(text: str) -> list[Any]:
    """What CreditProbe knows it cannot calculate, that these words name.

    Phrase by phrase, like the metric matching, so "roll rate" inside a
    sentence reaches the roll rate's refusal. Answering a whole sentence with
    silence teaches somebody that the builder does not understand them, when
    what happened is that CreditProbe understood exactly and cannot do it.
    """
    from backend.metrics import library

    out: list[Any] = []
    seen: set[str] = set()
    for phrase in _phrases(text):
        # Two words at least. A single word matches far too much — "retail"
        # alone reaches Retail ECL and the retail staging split, neither of
        # which was asked for — and a refusal nobody asked for reads as the
        # product listing things it cannot do.
        if len(phrase.split()) < 2:
            continue
        for entry in search.unsupported_for(library.UNSUPPORTED, phrase):
            if entry.metric_id not in seen:
                seen.add(entry.metric_id)
                out.append(entry)
    return out[:3]


#: How long a phrase may be when matching a sentence against the catalogue.
#: Three, because metric names people say out loud are one to three words —
#: "coverage", "cure rate", "30+ dpd exposure rate" — and a four-word window
#: over a sentence starts matching across the clause boundary.
MAX_PHRASE = 3


def _phrases(text: str) -> list[str]:
    """The sentence as the phrases a metric might be named by, longest first.

    `search.search` is built for a typeahead: it requires EVERY word of the
    query to match something, which is exactly right when somebody is typing
    a name and exactly wrong for a sentence. "Show me exposure by sector" has
    two words that name a metric and four that do not, and asking the
    typeahead about the whole thing returns nothing.

    So the sentence is cut into overlapping phrases and each is asked
    separately. That reuses the ranking that is already tested rather than
    growing a second one, and it keeps two-word names intact — "cure rate"
    scores as a phrase before "cure" and "rate" are tried apart.
    """
    tokens = _signal(text)
    out: list[str] = []
    for size in range(min(MAX_PHRASE, len(tokens)), 0, -1):
        for start in range(len(tokens) - size + 1):
            out.append(" ".join(tokens[start:start + size]))
    return out


def _metrics_for(text: str, pool: list[MetricDefinition]) -> list[Any]:
    """Metrics a sentence names, ranked, without requiring it to be a name.

    A longer phrase that matches is worth more than a short one: "cure rate"
    naming the cure rate is a stronger signal than "rate" naming forty things.
    Within that, the typeahead's own tier and score order the result, so a
    sentence and the words typed out of it agree about what they mean.
    """
    scored: dict[str, tuple[float, Any]] = {}
    for phrase in _phrases(text):
        weight = float(len(phrase.split())) ** 2
        for hit in search.search(pool, phrase, limit=CANDIDATES):
            key = hit.metric.metric_id
            points = weight * (hit.tier + hit.score / 1000.0)
            best = scored.get(key)
            if best is None or points > best[0]:
                scored[key] = (points, hit)
    ranked = sorted(scored.values(),
                    key=lambda pair: (-pair[0], pair[1].metric.name))
    return [hit for _points, hit in ranked]


def _understood(intent: Intent) -> str:
    """One sentence saying what was recognised, in the reader's words.

    Shown before anything is built. A builder that acts on a reading it never
    displayed is a builder people stop trusting the first time it is wrong.
    """
    parts: list[str] = []
    chosen = [d.name for d in intent.domains if d.chosen]
    if chosen:
        parts.append("the " + " and ".join(chosen) + " data")
    if intent.metrics:
        names = [m["name"] for m in intent.metrics[:3]]
        parts.append(f"metrics like {', '.join(names)}")
    if intent.charts:
        parts.append("broken out by "
                     + ", ".join(c["dimension_label"] for c in intent.charts))
    if intent.periods:
        parts.append("for " + ", ".join(intent.periods))
    if not parts:
        return ("Nothing in the governed catalogue answers to those words "
                "yet.")
    return "Read as: " + "; ".join(parts) + "."


def _question(intent: Intent) -> str:
    """What to ask next. Never more than one thing at a time."""
    if not intent.domains and not intent.metrics:
        return ("Which part of the book is this about? Pick a data domain, "
                "or say it another way.")
    if len(intent.domains) > 1 and sum(
            1 for d in intent.domains if d.chosen) > 1:
        return ("This reads as more than one data domain. Keep the ones you "
                "meant.")
    if not intent.metrics:
        return ("No governed metric answers to that yet. Define a new one, or "
                "search the library.")
    return "Add the metrics you want, or define a new one."


# ---------------------------------------------------------------------------
# Proposing a new metric
# ---------------------------------------------------------------------------

#: What a phrase asks the metric to BE. Ordered: the first match wins, so
#: "rate" beats "count" in "count rate", which is what a reader means.
_KIND_WORDS: tuple[tuple[str, str], ...] = (
    (r"\b(rate|ratio|share|percentage|percent|proportion|%)\b", "percentage"),
    # Before the plain average, because "weighted average" contains it and
    # first-match-wins would otherwise read the more specific phrase as the
    # less specific one — and a weighted average computed unweighted is a
    # different number that looks like the right one.
    (r"\b(weighted|weight by|weighted by)\b", "weighted_average"),
    (r"\b(average|mean|avg)\b", "average"),
    (r"\b(distinct|unique)\b", "distinct_count"),
    (r"\b(number of|count|how many)\b", "count"),
    (r"\b(total|sum|amount|exposure|balance|value)\b", "sum"),
)


@dataclass
class Proposal:
    """A metric skeleton, and everything about it that is a guess.

    `assumptions` is the point. Every part of this was matched against the
    governed catalogue, and every part is still a guess about what somebody
    meant — so the screen shows them as editable fields with the reasoning
    beside each, rather than as a definition to accept.
    """

    name: str
    kind: str
    dataset: str
    domain: str
    formula: Formula
    assumptions: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "dataset": self.dataset,
                "domain": self.domain, "formula": self.formula.to_dict(),
                "assumptions": list(self.assumptions),
                "unresolved": list(self.unresolved)}


def propose(text: str, *, domain: str = "", dataset: str = "",
            user_id: int | None = None, readable: Any = None) -> Proposal:
    """A metric skeleton for a sentence nothing existing answers.

    Every field it names exists in the dataset, every aggregation is in the
    governed set, and every filter is a comparison the engine performs. What
    it cannot do is know whether that is the metric somebody wanted, so it
    says what it assumed and leaves the rest unresolved rather than filling
    the gap with something plausible.
    """
    from backend.metrics import service as metrics

    said = (text or "").strip()
    kind = "sum"
    for pattern, wanted in _KIND_WORDS:
        if re.search(pattern, said, re.I):
            kind = wanted
            break

    pool = metrics.catalogue(user_id=user_id, readable=readable)
    if not dataset:
        dataset, domain = _dataset_for(said, pool, domain)

    assumptions: list[str] = []
    unresolved: list[str] = []
    if not dataset:
        return Proposal(
            name=_title(said), kind=kind, dataset="", domain=domain,
            formula=Formula(kind=kind),
            unresolved=["Which governed dataset this reads. Choose a data "
                        "domain and CreditProbe will offer the datasets in "
                        "it."])

    catalog = _catalog()
    fields = _fields_of(catalog, dataset)
    measure = _best_field(said, fields, numeric=True)
    if measure:
        assumptions.append(
            f"Measures '{fields[measure]['business_name']}' "
            f"({measure}), because it is the field in {dataset} whose name "
            "is closest to what you wrote.")
    elif kind not in ("count", "distinct_count"):
        unresolved.append(
            f"Which field to measure. {dataset} has "
            f"{len(fields)} to choose from.")

    where = _conditions(said, fields)
    for condition in where:
        assumptions.append(
            f"Filters on {fields[condition.field]['business_name']} "
            f"{condition.describe().split(' ', 1)[1]}, read from your words.")

    aggregate = {"sum": "sum", "average": "avg", "count": "count",
                 "distinct_count": "count_distinct",
                 "weighted_average": "weighted_avg",
                 "percentage": "count" if not measure else "sum",
                 }.get(kind, "sum")
    if aggregate not in AGGREGATIONS:  # pragma: no cover - table is closed
        aggregate = "sum"

    top = Term(id="numerator", label=_title(said) or "Measured",
               dataset=dataset, aggregate=aggregate,
               field=("" if aggregate == "count" else (measure or "")),
               where=tuple(where))

    formula = Formula(kind=kind, numerator=Side(terms=(top,)))
    if kind in NEEDS_DENOMINATOR:
        bottom = Term(id="denominator", label="Everything in scope",
                      dataset=dataset, aggregate=aggregate,
                      field=("" if aggregate == "count" else (measure or "")))
        formula = Formula(kind=kind, numerator=Side(terms=(top,)),
                          denominator=Side(terms=(bottom,)), scale=100.0)
        assumptions.append(
            "Divides by the same measure with the filters removed, which is "
            "what a rate usually means. Change the denominator if you meant "
            "a different population.")

    if kind == "weighted_average":
        unresolved.append("Which field to weight by. A weighted average needs "
                          "one, and guessing it would change the answer.")

    return Proposal(name=_title(said) or "New metric", kind=kind,
                    dataset=dataset, domain=domain, formula=formula,
                    assumptions=assumptions, unresolved=unresolved)


def _catalog() -> Any:
    from backend.metrics.service import _catalog as catalog

    return catalog()


def _fields_of(catalog: Any, dataset: str) -> dict[str, dict[str, Any]]:
    try:
        entry = catalog.dataset(dataset)
    except Exception:  # noqa: BLE001 - a dataset that has gone
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, definition in entry.fields.items():
        out[str(name)] = {
            "name": str(name),
            "business_name": str(getattr(definition, "business_name", "")
                                  or name),
            "definition": str(getattr(definition, "definition", "") or ""),
            "data_type": str(getattr(definition, "data_type", "") or ""),
            "sensitivity": str(getattr(definition, "sensitivity", "") or ""),
            "allowed_values": list(
                getattr(definition, "allowed_values", ()) or ()),
        }
    return out


def _dataset_for(text: str, pool: list[MetricDefinition],
                 domain: str) -> tuple[str, str]:
    """The dataset a new metric most likely reads.

    Chosen from the datasets governed metrics in the chosen domain already
    read, rather than from every dataset in the lake. A new metric belongs
    beside the ones it will be read next to, and a dataset nobody has built a
    governed metric on is not somewhere to start a person off.
    """
    wanted = [m for m in pool if not domain or m.domain == domain]
    counts: dict[tuple[str, str], int] = {}
    for metric in wanted:
        for dataset in metric.datasets:
            counts[(dataset, metric.domain)] = counts.get(
                (dataset, metric.domain), 0) + 1
    if not counts:
        return "", domain
    tokens = set(_signal(text))
    def score(pair: tuple[tuple[str, str], int]) -> tuple[int, int, str]:
        (dataset, _domain), used = pair
        named = sum(1 for t in tokens if t in dataset.lower())
        return (named, used, dataset)
    (dataset, found), _used = max(counts.items(), key=score)
    return dataset, domain or found


def _best_field(text: str, fields: dict[str, dict[str, Any]], *,
                numeric: bool) -> str:
    """The field whose name is closest to what somebody wrote, or nothing.

    Nothing rather than the first numeric column: a metric measuring a field
    nobody asked for is worse than one that asks which field to measure.
    """
    tokens = set(_signal(text))
    if not tokens:
        return ""
    best, chosen = 0.0, ""
    for name, definition in fields.items():
        if numeric and definition["data_type"] not in ("number", "integer"):
            continue
        if definition["sensitivity"] in ("confidential", "restricted"):
            continue
        vocabulary = set(_words(name)) | set(_words(definition["business_name"]))
        overlap = tokens & vocabulary
        if not overlap:
            continue
        weight = len(overlap) + (0.5 if name.lower() in text.lower() else 0.0)
        if weight > best:
            best, chosen = weight, name
    return chosen


def _conditions(text: str, fields: dict[str, dict[str, Any]]
                ) -> list[Condition]:
    """Filters read out of a sentence, and only ones the catalogue confirms.

    A value is only accepted when the dataset declares it as an allowed value
    of that field. That is what stops "stage 2" becoming a filter on a field
    that has no such value and returning zero rows with a straight face.
    """
    lowered = (text or "").lower()
    found: list[Condition] = []
    for name, definition in fields.items():
        if definition["sensitivity"] in ("confidential", "restricted"):
            continue
        for value in definition["allowed_values"]:
            token = str(value).strip()
            if len(token) < 3:
                continue
            if re.search(rf"\b{re.escape(token.lower())}\b", lowered):
                found.append(Condition(name, "=", value))
                break
        if definition["data_type"] == "boolean":
            label = definition["business_name"].lower()
            if re.search(rf"\b{re.escape(label)}\b", lowered) or (
                    re.search(rf"\b{re.escape(name.lower())}\b", lowered)):
                found.append(Condition(name, "=", True))
    # A days-past-due threshold, which people write as a number and a word.
    dpd = re.search(r"\b(\d{1,3})\s*\+?\s*(?:day|dpd)", lowered)
    if dpd:
        for name in ("days_past_due", "current_dpd", "dpd_days"):
            if name in fields:
                found.append(Condition(name, ">=", int(dpd.group(1))))
                break
    seen: set[str] = set()
    unique: list[Condition] = []
    for condition in found:
        if condition.field in seen:
            continue
        seen.add(condition.field)
        unique.append(condition)
    return unique[:4]


def _title(text: str) -> str:
    """A metric name from a sentence, without the filler."""
    words = [w for w in re.findall(r"[A-Za-z0-9+]+", text or "")
             if w.lower() not in _STOP]
    if not words:
        return ""
    return " ".join(w if w.isupper() else w.capitalize()
                    for w in words[:6])


__all__ = ["BUILDER_VERSION", "CANDIDATES", "DomainOption", "Intent",
           "Proposal", "interpret", "propose", "explain", "preview",
           "plain_english", "compiled_sql", "expanded_formula"]


# ---------------------------------------------------------------------------
# One definition, three readings that cannot disagree
# ---------------------------------------------------------------------------

#: How each aggregation reads in a sentence.
_SAYS = {
    "sum": "the total of", "count": "how many rows there are in",
    "count_distinct": "how many different values there are of",
    "avg": "the average of", "min": "the smallest", "max": "the largest",
    "median": "the middle value of", "stddev": "the spread of",
    "weighted_avg": "the weighted average of",
}

#: How each comparison reads.
_READS = {
    "=": "is", "!=": "is not", "<": "is below", "<=": "is at most",
    ">": "is above", ">=": "is at least", "in": "is one of",
    "not_in": "is none of", "between": "is between",
    "is_null": "is not recorded", "is_not_null": "is recorded",
    "contains": "contains", "starts_with": "starts with",
    "ends_with": "ends with",
}

#: How each kind of metric reads as a final sentence.
_FINAL = {
    "percentage": "Divide the first by the second and multiply by 100, "
                  "giving a percentage.",
    "rate": "Divide the first by the second and multiply by 100, giving a "
            "rate.",
    "ratio": "Divide the first by the second.",
    "weighted_average": "Weight each value by its weight field and average "
                        "them.",
}


def _field_name(fields: dict[str, dict[str, Any]], name: str) -> str:
    """A field in the reader's words, falling back to its column name."""
    entry = fields.get(name)
    if entry and entry["business_name"]:
        return f"{entry['business_name']}"
    return name


def _term_english(term: Term, fields: dict[str, dict[str, Any]]) -> str:
    # A count counts rows, whether or not a field is named on it. The field
    # on a filtered count is what the filter reads, not what is being
    # counted, and saying "how many rows there are in current DPD" reads as
    # though the two were the same thing.
    if term.aggregate == "count":
        line = "How many rows there are"
    elif term.aggregate == "count_distinct":
        line = ("How many different values there are of "
                + _field_name(fields, term.field))
    else:
        says = _SAYS.get(term.aggregate, term.aggregate)
        what = _field_name(fields, term.field or term.weight_field)
        line = f"{says} {what}".capitalize()
    if term.weight_field and term.aggregate == "weighted_avg":
        line += f", weighted by {_field_name(fields, term.weight_field)}"
    if term.where:
        clauses = []
        for condition in term.where:
            reads = _READS.get(condition.op, condition.op)
            value = condition.value
            if isinstance(value, bool):
                clauses.append(
                    f"{_field_name(fields, condition.field)} is "
                    f"{'set' if value else 'not set'}")
            elif isinstance(value, (list, tuple)):
                clauses.append(
                    f"{_field_name(fields, condition.field)} {reads} "
                    f"{', '.join(str(v) for v in value)}")
            elif value is None:
                clauses.append(f"{_field_name(fields, condition.field)} {reads}")
            else:
                clauses.append(
                    f"{_field_name(fields, condition.field)} {reads} {value}")
        line += ", counting only rows where " + " and ".join(clauses)
    return line


def plain_english(metric: MetricDefinition,
                  fields: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """The execution logic as numbered steps somebody can check.

    §6 asks for this beside the formula and the SQL, and §7 asks that all
    three stay reconciled through an edit. They do because none of them is
    stored: each is generated from the same tree every time it is asked for,
    so there is nothing that can be right when it was written and wrong after.

    Steps rather than a paragraph. A person checking a definition is checking
    a sequence — which rows, which field, which arithmetic — and a paragraph
    makes them find the sequence inside it first.
    """
    if fields is None:
        fields = _fields_of(_catalog(), metric.datasets[0]
                            if metric.datasets else "")
    formula = metric.formula
    steps: list[str] = []

    dataset = metric.datasets[0] if metric.datasets else "the dataset"
    steps.append(f"Read every row of {dataset} for the period being shown.")
    if metric.scope:
        clauses = " and ".join(
            _term_english(Term(id="s", label="", dataset=dataset,
                               aggregate="count", where=(c,)), fields)
            .split("counting only rows where ")[-1]
            for c in metric.scope)
        steps.append(f"Keep only the rows where {clauses}.")

    if formula.kind == "function":
        steps.append(
            f"Hand those rows to CreditProbe's governed "
            f"{formula.function} function, which computes the statistic over "
            "the whole population rather than from a summary.")
        return steps

    for index, term in enumerate(formula.numerator.terms, start=1):
        label = ("Take " if len(formula.numerator.terms) == 1
                 else f"Term {index}: take ")
        steps.append(label + _term_english(term, fields).lower() + ".")
    if len(formula.numerator.terms) > 1:
        steps.append(
            f"Combine those terms by {formula.numerator.combine} to get the "
            "numerator.")

    if formula.denominator and formula.denominator.terms:
        for index, term in enumerate(formula.denominator.terms, start=1):
            label = ("Then take " if len(formula.denominator.terms) == 1
                     else f"Denominator term {index}: take ")
            steps.append(label + _term_english(term, fields).lower() + ".")
        if len(formula.denominator.terms) > 1:
            steps.append(
                f"Combine those by {formula.denominator.combine} to get the "
                "denominator.")

    final = _FINAL.get(formula.kind)
    if final:
        steps.append(final)
    elif formula.scale != 1.0:
        steps.append(f"Multiply the result by {formula.scale:g}.")
    else:
        steps.append("Report that figure.")
    if metric.unit == "currency":
        steps.append("Report it as an amount of money.")
    elif metric.unit == "percent":
        steps.append("Report it as a percentage.")
    return steps


def _expanded_side(side: Side) -> str:
    joiner = {"add": " + ", "subtract": " − ", "multiply": " × ",
              "divide": " ÷ "}.get(side.combine, ", ")
    if not side.terms:
        return ""
    if side.combine == "first" or len(side.terms) == 1:
        return side.terms[0].describe()
    return joiner.join(t.describe() for t in side.terms)


def expanded_formula(formula: Formula) -> str:
    """The algebra with every term written out, labels ignored.

    `Formula.describe()` prefers a term's LABEL when it has one, which reads
    well on a governed metric — "(Breached EAD) / (Total exposure) × 100" is
    what a risk person wants on an info panel.

    It is the wrong thing while somebody is editing. A label is prose that was
    written once; move a threshold from 0 to 5 and the labelled line does not
    change, so §7's promise that the readings stay reconciled would be broken
    by the one reading a person looks at first. This expands every term to the
    aggregation, the field and the conditions, so an edit always shows.
    """
    if formula.kind == "function":
        return f"{formula.function}({_expanded_side(formula.numerator)})"
    top = _expanded_side(formula.numerator)
    if formula.denominator is None or not formula.denominator.terms:
        return (f"({top}) × {formula.scale:g}" if formula.scale != 1.0
                else top)
    bottom = _expanded_side(formula.denominator)
    tail = (f" × {formula.scale:g}" if formula.scale != 1.0 else "")
    return f"({top}) / ({bottom}){tail}"


def compiled_sql(metric: MetricDefinition, *, period: str = "",
                 dimension: str = "") -> dict[str, Any]:
    """The actual SQL the engine will run, without running it.

    §6 asks for "actual safe SQL/Python/query logic" and this is it — not a
    reconstruction and not an illustration. It is the same compiler the
    executor calls, over the same validated plan, so what is shown is what
    will run.

    Parameters are returned separately and are never interpolated into the
    string. That is not presentation: it is why a filter value somebody typed
    cannot become SQL.
    """
    from backend.metrics import execution
    from backend.runtime.compiler import compile_plan
    from backend.runtime.validation import validate
    from backend.scorecard.domains import GOVERNED_METRIC

    try:
        if dimension:
            plan = execution.compile_breakdown(
                metric.formula, dimension=dimension, period=period,
                scope=metric.scope)
        else:
            plan = execution.compile_metric(metric.formula, period=period,
                                            scope=metric.scope)
    except Exception as e:  # noqa: BLE001 - a definition that will not compile
        return {"sql": "", "params": [], "datasets": [],
                "unavailable": str(e)}

    report = validate(plan, scope=GOVERNED_METRIC)
    if not report.ok:
        return {"sql": "", "params": [], "datasets": [],
                "unavailable": " ".join(report.reasons)}
    try:
        query = compile_plan(plan, report)
    except Exception as e:  # noqa: BLE001 - reported rather than raised
        return {"sql": "", "params": [], "datasets": [],
                "unavailable": str(e)}
    return {
        "sql": query.sql,
        "params": [str(p) for p in query.params],
        "datasets": list(query.datasets),
        "steps": dict(query.steps),
        "unavailable": "",
    }


def explain(metric: MetricDefinition, *, period: str = "",
            dimension: str = "") -> dict[str, Any]:
    """One definition, read three ways, generated together.

    Together on purpose. §7 requires the algebra, the English and the SQL to
    stay reconciled when somebody edits the definition, and the way to
    guarantee that is not to synchronise three stored things — it is to have
    only one stored thing and derive the other two on every request.
    """
    catalog = _catalog()
    fields = _fields_of(catalog, metric.datasets[0]
                        if metric.datasets else "")
    query = compiled_sql(metric, period=period, dimension=dimension)
    return {
        "metric_id": metric.metric_id,
        "name": metric.name,
        "definition": metric.definition,
        "kind": metric.formula.kind,
        "unit": metric.unit,
        "decimals": metric.decimals,
        "domain": metric.domain,
        "portfolio": metric.portfolio,
        "datasets": list(metric.datasets),
        # Two readings of the algebra, and the screen needs both. `formula`
        # is the labelled one an info panel shows; `formula_detail` writes
        # every term out, which is the one that moves when a threshold does.
        "formula": metric.formula_text or metric.formula.describe(),
        "formula_detail": expanded_formula(metric.formula),
        "formula_tree": metric.formula.to_dict(),
        "plain_english": plain_english(metric, fields),
        "sql": query["sql"],
        "sql_params": query["params"],
        "sql_unavailable": query["unavailable"],
        "fields": [fields[f] for f in metric.fields if f in fields],
        "filters": list(metric.filters),
        "status": metric.status,
        "origin": metric.origin,
        "version": metric.version,
    }


# ---------------------------------------------------------------------------
# Running it against real data, before anybody trusts it
# ---------------------------------------------------------------------------


def preview(metric: MetricDefinition, *, period: str = "",
            rows: int = 8, user_id: int | None = None) -> dict[str, Any]:
    """§8. What this definition produces on the real book, step by step.

    Everything §8 asks for and in the order somebody checks it: which dataset
    and domain, which periods exist, which fields are read, which filters are
    applied, each numerator and denominator term with its own value and its
    own row count, the aggregation, and the final arithmetic written out.

    The row counts per term are the part that earns its place. "The numerator
    is zero" and "the numerator matched no rows" are different problems and
    only one of them is a formula error, and without the counts a person
    debugging their own filter cannot tell which they have.

    Nothing is invented. A period with no data comes back as a preview that
    says so, with the periods that DO exist beside it, rather than as a zero.
    """
    from backend.metrics import execution
    from backend.metrics import service as metrics

    catalog = _catalog()
    dataset = metric.datasets[0] if metric.datasets else ""
    fields = _fields_of(catalog, dataset)

    try:
        available = metrics.periods_with_rows(metric.datasets, metric.scope)
    except Exception:  # noqa: BLE001 - a dataset that has gone
        available = []
    wanted = period or (available[-1] if available else "")

    grain = ""
    if dataset:
        try:
            grain = str(catalog.dataset(dataset).grain or "")
        except Exception:  # noqa: BLE001
            grain = ""

    shell: dict[str, Any] = {
        "metric_id": metric.metric_id,
        "name": metric.name,
        "domain": metric.domain,
        "portfolio": metric.portfolio,
        "dataset": dataset,
        "grain": grain,
        "periods": list(available),
        "period": wanted,
        "unit": metric.unit,
        "decimals": metric.decimals,
        "fields": [fields[f] for f in metric.fields if f in fields],
        "scope": [c.describe() for c in metric.scope],
        "kind": metric.formula.kind,
        "aggregations": sorted({t.aggregate for t in metric.formula.terms}),
        "numerator": [], "denominator": [],
        "numerator_value": None, "denominator_value": None,
        "final": "", "value": None, "formatted": "",
        "rows_considered": 0, "sample": {"columns": [], "rows": []},
        "sql": "", "run_id": "", "warnings": [], "unavailable": "",
    }

    if not available:
        shell["unavailable"] = (
            f"{dataset or 'This dataset'} holds no periods this metric can "
            "read, so there is nothing to preview against.")
        return shell

    try:
        calculation = execution.run(metric.formula, period=wanted,
                                    scope=metric.scope,
                                    question=f"Preview {metric.name}")
    except Exception as e:  # noqa: BLE001 - reported, never raised at a screen
        shell["unavailable"] = str(e)
        return shell

    shown = calculation.to_dict()
    shell.update({
        "numerator": (shown.get("numerator") or {}).get("terms") or [],
        "denominator": (shown.get("denominator") or {}).get("terms") or [],
        "numerator_value": (shown.get("numerator") or {}).get("value"),
        "denominator_value": (shown.get("denominator") or {}).get("value"),
        "final": shown.get("final") or "",
        "value": calculation.value,
        "rows_considered": calculation.rows_considered,
        "sql": calculation.sql,
        "run_id": calculation.run_id,
        "warnings": [w for w in calculation.warnings if w],
        "unavailable": calculation.unavailable,
    })
    if calculation.value is not None:
        shell["formatted"] = _formatted(calculation.value, metric)

    # A handful of the rows behind it, with the inclusion logic worked out per
    # term. What makes this useful is not the rows but the columns beside them
    # saying whether each row counted, which is how somebody checks that a
    # filter means what they meant.
    if rows > 0 and calculation.value is not None:
        try:
            shell["sample"] = execution.sample(
                metric.formula, period=wanted, scope=metric.scope,
                limit=int(rows))
        except Exception:  # noqa: BLE001 - a sample is a convenience
            shell["sample"] = {"columns": [], "rows": [],
                               "unavailable": "The sample could not be read."}
    return shell


def _formatted(value: float, metric: MetricDefinition) -> str:
    """The figure as the tile would print it, so a preview and a tile agree."""
    decimals = int(metric.decimals)
    if metric.unit == "percent":
        return f"{value:,.{decimals}f}%"
    if metric.unit == "currency":
        return f"SAR {value:,.{decimals}f}"
    return f"{value:,.{decimals}f}"
