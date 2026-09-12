"""
A governed metric, asked for by name, answered by the metric engine.

The failure this exists for
---------------------------
Four questions a Head of Retail Risk asks before lunch, and what CreditProbe
answered:

    "What is the 30+ DPD rate?"
        425.0 days of days past due at 2026-08.

    "Which product has the highest 30+ DPD rate?"
        1,260 days of days past due across 4 products at 2026-08.

    "What is the Stage 3 share of exposure?"
        3.00 IFRS 9 stage in Stage 3 at 2026-08.

    "What proportion of the book is in Stage 2?"
        2.00 IFRS 9 stage in Stage 2 at 2026-08.

Not one of those is a rate, a share or a proportion. The first two summed the
`dpd` column; the second two reported the literal contents of `ifrs9_stage` —
the number 3 and the number 2 — as though the stage label were the answer. All
four ran, all four passed their invariants, and all four are the kind of figure
somebody repeats in a committee.

The cause is structural rather than a bug in any one of them. The Cockpit's
planner composes an analysis out of CONCEPTS, and a concept is one governed
column. A rate is not a column: it is a numerator, a denominator and a scope,
and the only place in this codebase that holds those together is the Metric
Catalogue — which the Cockpit never consulted. So the planner did what it could
with the nearest column, which is exactly the failure this product exists to
prevent.

What this route does
--------------------
A question that names a governed metric whose formula has a DENOMINATOR or a
governed FUNCTION behind it is answered by the metric engine: the same
definition, the same scope and the same arithmetic the lens tile uses. Chat and
dashboard then agree by construction rather than by coincidence, which is worth
more than either number on its own.

What it deliberately does not do
--------------------------------
It is a route, not a rescue, and it is kept narrow in four ways.

  * Only DERIVED metrics. A plain sum — total ECL, gross carrying amount — is
    something the planner expresses perfectly well, and taking those would cost
    the filters, cohorts and comparisons the planner can do and the metric
    engine cannot.
  * Only a precise naming. A one-word alias is ignored unless the word is a
    technical term that means one thing ("gini", "coverage"), because
    "secured" in "what is secured exposure?" is an adjective and not a request
    for the secured share.
  * Never over a movement, a threshold or a two-period comparison. Those are
    questions the planner answers and this engine cannot express at all.
  * Never over a row-level population. "Which customers are 30+ DPD" asks for
    customers; a portfolio rate is not an answer to it.

Anything this route declines falls through to the planner exactly as before.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

#: Formula kinds this route answers. Every one of them needs a denominator or a
#: governed function, which is precisely what a single column cannot carry.
DERIVED_KINDS: frozenset[str] = frozenset({
    "ratio", "percentage", "rate", "function",
})

#: One-word names that mean one thing in a credit book, and may therefore
#: route on their own. Everything else needs at least two words.
#:
#: The list is short on purpose. "secured", "overdue", "exposure" and
#: "allowance" are all single-word aliases of governed metrics and all four are
#: ordinary English adjectives or nouns in a sentence about something else.
UNAMBIGUOUS: frozenset[str] = frozenset({
    "gini", "auc", "auroc", "ks", "coverage", "utilisation", "utilization",
    "forbearance", "forborne", "sicr",
})

#: Row-level subjects. A portfolio rate does not answer a question about them.
_POPULATION = re.compile(
    r"\b(?:which|what|list|show|name|give)\b[^.?]{0,30}?\b"
    r"(?:customers?|borrowers?|facilit(?:y|ies)|accounts?|obligors?|clients?)\b",
    re.IGNORECASE,
)

#: "the highest", "the worst", "top", "lowest" — a request to rank the
#: breakdown rather than to list it.
_RANKED = re.compile(
    r"\b(?:highest|largest|biggest|worst|most|top|lowest|smallest|best|least)\b",
    re.IGNORECASE,
)

#: Words that make a question a comparison between two points in time. The
#: metric engine computes one period; asking it to answer a comparison would
#: mean showing one of the two numbers under a heading promising both.
#: A COMPARISON between two states of the book, which this engine does not
#: produce. "trend" and "over time" have been taken out of it: a series of a
#: governed metric is exactly what the engine does produce, month by month,
#: and declining it sent "show the ECL coverage trend" to a composer that can
#: only average the ratio COLUMN — 2.17% where the book's coverage is 0.77%,
#: over two points where twelve were asked for. See `_TREND` below.
_COMPARISON = re.compile(
    r"\b(?:vs\.?|versus|compared?\s+(?:to|with)|against|since|between|"
    r"year\s+on\s+year|month\s+on\s+month|yoy|mom|"
    r"movement|change[ds]?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Routed:
    """A governed metric this question asked for, and how to report it."""

    metric: Any
    phrase: str
    #: The governed column to break the metric down by, where one was named.
    dimension: str = ""
    dimension_phrase: str = ""
    #: True where the question asked which group is highest rather than for
    #: the whole breakdown.
    ranked: bool = True
    period: str = ""
    #: True where the breakdown IS the period — a series rather than a cut.
    trend: bool = False
    #: The sentence, so the answer can lead with the end it asked for.
    question: str = ""

    @property
    def metric_id(self) -> str:
        return str(self.metric.metric_id)


@lru_cache(maxsize=1)
def _phrases() -> tuple[tuple[str, Any], ...]:
    """Every derived metric's names and aliases, longest phrase first.

    Longest-first is what makes "stage 2 coverage" beat "coverage": both are
    present in the sentence and only one of them is what was asked for.
    """
    from backend.metrics import library

    out: list[tuple[str, Any]] = []
    for metric in library.ALL:
        if str(getattr(metric.formula, "kind", "")) not in DERIVED_KINDS:
            continue
        spellings = {str(metric.name).lower()}
        spellings.update(str(a).lower() for a in metric.aliases)
        for phrase in spellings:
            phrase = phrase.strip()
            if not phrase:
                continue
            if len(phrase.split()) < 2 and phrase not in UNAMBIGUOUS:
                continue
            out.append((phrase, metric))
    out.sort(key=lambda pair: len(pair[0]), reverse=True)
    return tuple(out)


def _qualified_away(text: str, hit: re.Match[str], phrase: str) -> bool:
    """Whether a one-word metric name was QUALIFIED into a different measure.

    "coverage" is in `UNAMBIGUOUS` because a reader who writes it alone means
    ECL coverage. A reader who writes "COLLATERAL coverage" does not, and this
    served them ECL Coverage — 0.77%, confidently, under a question about
    collateral. The right answer is that this installation publishes no
    collateral coverage metric, which the planner says on its own.

    Read from the LIBRARY rather than from a list of qualifiers: the word in
    front is a qualifier where no governed metric of this installation is
    spelled with the pair. "Stage 2 coverage" survives because a metric IS
    spelled that way; "collateral coverage" does not because none is.
    """
    if len(phrase.split()) > 1:
        return False
    before = text[:hit.start()].strip().split()
    if not before:
        return False
    qualifier = re.sub(r"[^a-z0-9+]", "", before[-1].lower())
    if not qualifier or qualifier in _NOT_A_QUALIFIER:
        return False
    pair = f"{qualifier} {phrase}"
    return not any(pair == spelling for spelling, _ in _phrases())


#: Words that stand in front of a metric name without qualifying it.
_NOT_A_QUALIFIER = frozenset({
    "the", "a", "an", "our", "its", "their", "this", "that", "is", "was",
    "of", "in", "at", "for", "on", "and", "or", "what", "whats", "show",
    "give", "me", "current", "total", "latest", "overall", "book", "portfolio",
    "retail", "governed", "reported", "s",
})


def _pattern(phrase: str) -> re.Pattern[str]:
    """A whole-phrase matcher tolerant of how people space and punctuate.

    "30+ DPD" is written "30+ dpd", "30 + dpd" and "30plus dpd", and a metric
    nobody can name is a metric nobody uses.
    """
    parts = [re.escape(word) for word in phrase.split()]
    body = r"[\s\-]*".join(parts)
    body = body.replace(r"\+", r"\s*\+\s*")
    # A leading digit or a trailing "+" is not a word character, so \b does
    # the wrong thing on both ends. Guard on what may NOT sit beside it.
    return re.compile(rf"(?<![\w+]){body}(?![\w])", re.IGNORECASE)


@lru_cache(maxsize=256)
def _compiled() -> tuple[tuple[re.Pattern[str], str, Any], ...]:
    return tuple((_pattern(phrase), phrase, metric)
                 for phrase, metric in _phrases())


#: A follow-up that stays on the metric already answered without naming it.
#:
#: "What's happening to 30+ DPD?" is answered by this engine, and then "which
#: product is driving it?" was not: the metric left nothing on the
#: conversation, the planner read the sentence from a standing start, and the
#: only delinquency column it could find was `dpd` — so it SUMMED it and
#: answered "1,260 days of days past due across 4 products". "By rate, not
#: volume" fared worse and asked which figure to measure.
_STAYS_ON_THE_METRIC = re.compile(
    r"^\s*(?:and\s+|now\s+|ok(?:ay)?[,.]?\s+|so\s+)?"
    r"(?:which|what)\s+\w+\s+(?:is\s+)?(?:driv\w+|caus\w+|behind|"
    r"account\w*\s+for|contribut\w+)\b"
    r"|^\s*(?:and\s+|now\s+)?by\s+[\w\s]{2,30}(?:,\s*not\s+[\w\s]{2,20})?\s*[?.!]*$"
    r"|^\s*(?:and\s+|now\s+)?break\s+(?:that|it|this)\s+down\b"
    r"|^\s*(?:and\s+|now\s+)?(?:show|split|group)\s+(?:that|it|this)\s+by\b",
    re.IGNORECASE)

#: The words that say "as a proportion" rather than "as a count of days".
#: The words that ask for the BOTTOM of a ranking rather than the top.
_ASKS_FOR_THE_LOWEST = re.compile(
    r"\b(?:lowest|smallest|least|best|weakest|minimum|min)\b", re.IGNORECASE)

_BY_RATE = re.compile(r"\brate\b|\bproportion\b|\bshare\b|\bpercent\w*\b"
                      r"|\brelative\b|\bper\s+cent\b", re.IGNORECASE)


def stays_on_the_metric(question: str) -> bool:
    """Whether this follow-up continues the metric already on the table."""
    return bool(_STAYS_ON_THE_METRIC.search(
        " ".join(str(question or "").split())))


def read(question: str, *, carried_metric: str = "",
         carried_dimension: str = "") -> Routed | None:
    """The governed metric this question asks for, or `None` to fall through.

    `None` is the ordinary outcome and costs nothing: every question that is
    not a plain request for a named rate goes to the planner as it always did.

    `carried_metric` is the metric the conversation already settled. It is
    used only where the sentence names none of its own AND plainly continues
    it — a breakdown, a driver question, or "by rate, not volume".
    """
    text = str(question or "")
    if not text.strip():
        return None
    if carried_metric and stays_on_the_metric(text) and not _names_a_metric(text):
        held = _by_id(carried_metric)
        if held is not None:
            routed = _routed_for(held, text, carried=True,
                                 carried_dimension=carried_dimension)
            if routed is not None:
                return routed
    from backend.retail import profile

    if not profile.is_retail():
        # The corporate library's derived metrics read datasets this route has
        # never been driven against. Not a claim that it would not work —
        # a refusal to assert it without having watched it.
        return None
    if _COMPARISON.search(text) or _POPULATION.search(text):
        return None

    found = None
    for pattern, phrase, metric in _compiled():
        hit = pattern.search(text)
        if hit and not _qualified_away(text, hit, phrase):
            found = (phrase, metric)
            break
    if found is None:
        found = _share_of_a_state(text)
    if found is None:
        found = _share_of_a_named_state(text)
    if found is None:
        return None
    phrase, metric = found

    # The movement and threshold guards run against the sentence with the
    # metric's OWN NAME masked out, and that order is load-bearing. "What is
    # the 30+ DPD rate?" carries a threshold — `dpd >= 30` — inside the name of
    # the metric, and a guard reading the raw sentence declines every
    # delinquency question there is. What the guards are for is a threshold or
    # a movement the question adds AROUND the metric, which is a cohort or a
    # trend and not a figure this engine can produce.
    from backend.orchestration import semantics

    masked = _mask(text, phrase)

    # A TREND of a governed metric is this engine's work, not the composer's.
    #
    # It was declined with every other movement, and the composer then did the
    # only thing it can with a ratio COLUMN: averaged it. "Show the ECL
    # coverage trend for the last 12 months" came back as the mean of nineteen
    # thousand per-facility coverage ratios — 2.17% — where the book's coverage
    # is 0.77%, and over two points rather than twelve. A coverage ratio is
    # SUM(ECL) / SUM(gross carrying amount), and only the metric knows that.
    if _TREND.search(text):
        period_field = _period_field(metric)
        if period_field:
            return Routed(metric=metric, phrase=phrase,
                          dimension=period_field, dimension_phrase="month",
                          ranked=False, period="", trend=True, question=text)

    if semantics.find_movement(masked) is not None:
        return None
    if semantics.find_threshold(masked) is not None:
        return None

    dimension, dimension_phrase = _breakdown(text, phrase)
    return Routed(metric=metric, phrase=phrase, dimension=dimension,
                  dimension_phrase=dimension_phrase,
                  ranked=bool(_RANKED.search(text)),
                  period=_period(text, metric), question=text)



def _by_id(metric_id: str) -> Any:
    """One metric out of the library, by its id."""
    from backend.metrics import library

    for metric in library.ALL:
        if str(metric.metric_id) == str(metric_id):
            return metric
    return None


def _names_a_metric(text: str) -> bool:
    """Whether the sentence names a governed metric of its own."""
    for pattern, phrase, _ in _compiled():
        hit = pattern.search(text)
        if hit and not _qualified_away(text, hit, phrase):
            return True
    return _share_of_a_state(text) is not None


def _rate_sibling(metric: Any) -> Any:
    """The proportional form of a metric, where the library publishes one.

    "By rate, not volume" after a count is a request for a different metric,
    not a different presentation, and answering it with the count again would
    be answering the half of the sentence that says "by".
    """
    return metric


def _routed_for(metric: Any, text: str, *, carried: bool = False,
                carried_dimension: str = "") -> Any:
    """Route a CARRIED metric through this question's breakdown and ordering."""
    phrase = str(metric.name).lower()
    if _TREND.search(text):
        period_field = _period_field(metric)
        if period_field:
            return Routed(metric=metric, phrase=phrase,
                          dimension=period_field, dimension_phrase="month",
                          ranked=False, period="", trend=True, question=text)
    dimension, dimension_phrase = _breakdown(text, phrase)
    if not dimension and carried:
        # "Which product is driving it?" names the dimension as its subject
        # rather than after "by", which is what `_breakdown` reads.
        dimension, dimension_phrase = _breakdown(f"by {text}", phrase)
    if not dimension and carried and carried_dimension and _BY_RATE.search(text):
        # "By rate, not volume." The metric IS a rate and the breakdown is the
        # one already on screen, so this is the same answer said again — which
        # is the honest response to a reader asking for something they already
        # have, and better than asking them which figure to measure.
        dimension, dimension_phrase = carried_dimension, carried_dimension.replace(
            "_", " ")
    if not dimension:
        return None
    return Routed(metric=metric, phrase=phrase, dimension=dimension,
                  dimension_phrase=dimension_phrase,
                  ranked=bool(_RANKED.search(text)) or carried,
                  period=_period(text, metric), question=text)

#: A request for the metric AS A SERIES rather than as a figure.
_TREND = re.compile(
    r"\btrend\b|\bover time\b|\bmonth by month\b|\bby month\b|"
    r"\bby reporting month\b|\beach month\b|\bevery month\b|"
    r"\b(?:last|past|latest)\s+\d+\s+months?\b|\btime series\b|"
    r"\bhistory\b|\bhow has it (?:moved|changed|developed)\b",
    re.IGNORECASE)


def _windowed(points: list[dict[str, Any]], question: str
              ) -> list[dict[str, Any]]:
    """The months the question asked for, where it asked for a window.

    "the last 12 months" asked for twelve and the engine returns every month
    the book publishes. Twenty-five points under a question about twelve is an
    honest superset and still not the answer; a window that cannot be read
    leaves the series whole, which is.
    """
    from backend.orchestration import periods as pr

    labels = [str(p.get("label") or "") for p in points]
    try:
        intent = pr.read_period_intent(question, labels)
    except Exception:  # noqa: BLE001 - an unreadable window is the whole series
        return points
    opening = str(getattr(intent, "from_period", "") or "")
    closing = str(getattr(intent, "to_period", "") or "")
    if not (getattr(intent, "specified", False) and opening and closing):
        return points
    kept = [p for p in points
            if opening <= str(p.get("label") or "") <= closing]
    return kept or points


def _period_field(metric: Any) -> str:
    """The column the metric's own dataset is partitioned by."""
    from backend.data_access import get_catalog

    for name in (metric.datasets or ()):
        try:
            field = get_catalog().dataset(name).period_field
        except Exception:  # noqa: BLE001 - an unknown dataset has no period
            continue
        if field:
            return str(field)
    return ""


#: "what share of the book is in Stage 2", "what percentage is Stage 3".
#:
#: A stage share is the one derived metric people almost never name in full.
#: They name the STATE and ask for its share, and the planner's answer to that
#: was the number 2 — the contents of `ifrs9_stage` — presented as a
#: proportion. The metric exists; only the wording was missing.
#: "how much OF", not bare "how much". "How much Stage 3 exposure is in
#: Riyadh?" is an AMOUNT — 221,176 SAR — and it was answered "Stage 3 Share of
#: Exposure is 0.66%", about the whole book, with the city discarded. "How
#: much OF the book is in Stage 3" is the share, and keeps the preposition
#: that makes it one.
_SHARE_WORD = (r"(?:share|proportion|percentage|percent|%|fraction|"
               r"how much of|what part)")
_STAGE_SHARE = re.compile(
    rf"\b{_SHARE_WORD}\b[^.?]{{0,60}}?\bstage\s*(?P<stage>[123]|one|two|three)\b"
    rf"|\bstage\s*(?P<stage2>[123]|one|two|three)\b[^.?]{{0,30}}?\b{_SHARE_WORD}\b",
    re.IGNORECASE,
)

_STAGE_WORDS = {"one": "1", "two": "2", "three": "3",
                "1": "1", "2": "2", "3": "3"}


def _share_of_a_state(question: str) -> tuple[str, Any] | None:
    """A stage share asked for by naming the stage and the word "share"."""
    found = _STAGE_SHARE.search(question)
    if found is None:
        return None
    raw = (found.group("stage") or found.group("stage2") or "").lower()
    stage = _STAGE_WORDS.get(raw, "")
    if not stage:
        return None
    from backend.metrics import library

    wanted = f"retail.stage{stage}.share"
    for metric in library.ALL:
        if metric.metric_id == wanted:
            return (f"stage {stage} share", metric)
    return None


#: "What PROPORTION of the book is secured?" — the share asked for by naming
#: the state and the word proportion, with the two at opposite ends of the
#: sentence. The published metric is "Secured Share"; no alias can be spelled
#: that matches this word order, and the question came back asking which
#: figure to measure on a book whose answer is 74.97%.
_SHARE_OF_A_STATE = re.compile(
    r"\b(?:what\s+)?(?:proportion|share|percentage|percent|fraction|how\s+much)"
    r"\b[^?.!]{0,40}?\b(?:is|are|sits?|carr(?:y|ies))\s+"
    r"(?P<state>[a-z][a-z \-]{2,30}?)\s*[?.!]*$",
    re.IGNORECASE)


def _share_of_a_named_state(question: str) -> tuple[str, Any] | None:
    """A published SHARE metric, asked for by naming the state it is of."""
    found = _SHARE_OF_A_STATE.search(" ".join(str(question or "").split()))
    if found is None:
        return None
    state = " ".join(found.group("state").lower().split())
    if not state:
        return None
    from backend.metrics import library

    for metric in library.ALL:
        if str(getattr(metric.formula, "kind", "")) not in DERIVED_KINDS:
            continue
        spellings = {str(metric.name).lower(),
                     *(str(a).lower() for a in metric.aliases)}
        for wanted in (state, f"{state} share", f"{state} rate"):
            if wanted in spellings:
                return (state, metric)
    return None


def _mask(text: str, phrase: str) -> str:
    """The sentence with the metric's own name blanked out, same length."""
    return _pattern(phrase).sub(lambda m: " " * len(m.group(0)), text)


def _breakdown(question: str, phrase: str) -> tuple[str, str]:
    """The governed dimension the question asked to see the metric across.

    Read from the sentence with the METRIC'S OWN WORDS removed. "30+ DPD rate
    by product" is fine either way, but "Stage 3 share by product" is not: the
    dimension reader sees "stage" inside the metric's name and breaks a
    Stage 3 metric down by IFRS 9 stage, which is one row.
    """
    from backend.orchestration import dimensions

    resolved = dimensions.read(_mask(question, phrase))
    name = str(getattr(resolved, "dimension", "") or "")
    return name, str(getattr(resolved, "phrase", "") or "")


def _period(question: str, metric: Any) -> str:
    """The period the question named, or the metric's own governed default.

    A metric that measures an OUTCOME defaults to the latest matured cohort
    rather than the latest month, and that rule lives on the metric. Overriding
    it from a sentence that named no period is how an observed default rate
    comes back as 100%.
    """
    from backend.metrics import service

    try:
        published = service.periods_with_rows(metric.datasets,
                                              scope=metric.scope)
    except Exception:  # noqa: BLE001 - no lake, no period; the caller states it
        return ""
    if not published:
        return ""
    from backend.orchestration import periods as pr

    intent = pr.read_period_intent(question, list(published))
    named = list(getattr(intent, "named_periods", ()) or ())
    if len(named) == 1:
        return str(named[0])
    return ""


# --------------------------------------------------------------- answering


#: How many groups a breakdown may return before it stops being an answer.
MAX_PERIODS = 60
MAX_GROUPS = 25


def _format(value: float | None, unit: str, decimals: int) -> str:
    """The figure as the reader sees it everywhere else.

    Mirrors `frontend/src/components/metrics/present.ts`. A coverage ratio that
    reads "0.77%" on a lens tile and "0.0077" in the chat is two numbers as far
    as anybody in the room is concerned.
    """
    if value is None:
        return "not available"
    places = int(decimals if decimals is not None else 2)
    if unit in ("percent", "percentage"):
        return f"{value:,.{places}f}%"
    if unit == "probability":
        return f"{value * 100:,.{min(places, 2)}f}%"
    if unit == "currency":
        return f"{value:,.0f} SAR" if abs(value) >= 1000 else (
            f"{value:,.{places}f} SAR")
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "days":
        return f"{value:,.0f} days"
    return f"{value:,.{places}f}"


def answer(routed: Routed, question: str) -> Any:
    """Compute the metric and shape it as an answer.

    Raises nothing a caller has to catch for a data problem: an unavailable
    figure comes back as a stated unavailability, because "we could not compute
    this" and "this is zero" are different sentences and only one of them is
    true.
    """
    from backend.orchestration.handlers import HandlerResult

    metric = routed.metric
    if routed.dimension:
        result = _breakdown_answer(routed, question)
        if result is not None:
            return result
    return _value_answer(routed, question, HandlerResult)


def _panel(metric: Any) -> dict[str, Any]:
    from backend.metrics import service

    try:
        return metric.panel(catalog=service._catalog())
    except Exception:  # noqa: BLE001 - the panel is context, never the answer
        return {"metric_id": metric.metric_id, "name": metric.name,
                "definition": metric.definition, "unit": metric.unit}


def _follow_ups(routed: Routed) -> list[str]:
    metric = routed.metric
    out: list[str] = []
    if not routed.dimension:
        out.append(f"Break {metric.name} down by product")
        out.append(f"Show {metric.name} by customer segment")
    else:
        out.append(f"What is {metric.name} for the whole book?")
        out.append(f"Break {metric.name} down by customer segment")
    out.append(f"How is {metric.name} calculated?")
    return out


def _value_answer(routed: Routed, question: str, result_type: Any) -> Any:
    from backend.metrics import service

    metric = routed.metric
    computed = service.value(metric.metric_id, period=routed.period,
                             question=question)
    value = computed.get("value")
    period = str(computed.get("period") or routed.period or "")
    shown = _format(value, str(metric.unit), int(metric.decimals))
    where = f" at {period}" if period else ""
    if value is None:
        sentence = (f"{metric.name} could not be computed{where}: "
                    f"{computed.get('unavailable') or 'no rows qualified'}.")
    else:
        sentence = f"{metric.name} is {shown}{where}."
        if metric.formula_text:
            sentence += f" It is {metric.formula_text}."
    return result_type(
        answer=sentence,
        rows=[{"metric": metric.name, "value": value, "period": period}],
        columns=[{"name": "metric", "label": "Metric", "type": "string"},
                 {"name": "value", "label": metric.name, "type": "number",
                  "unit": metric.unit, "decimals": metric.decimals},
                 {"name": "period", "label": "Period", "type": "string"}],
        values={"value": value, "unit": metric.unit, "period": period,
                "metric_id": metric.metric_id, "formatted": shown},
        detail={"metric": _panel(metric),
                "calculation": computed.get("calculation") or {},
                "source": "metric_catalogue"},
        chart={},
        execution="computed",
        execution_label="Governed metric engine",
        graph=_trace(question, routed, period, computed.get("calculation")),
        follow_ups=_follow_ups(routed),
        warnings=([str(computed.get("unavailable"))]
                  if computed.get("unavailable") else []),
        title=metric.name,
    )


def _breakdown_answer(routed: Routed, question: str) -> Any:
    """The metric across one governed dimension, or `None` to fall back.

    `None` where the engine says the breakdown cannot be honest — a Gini over a
    segment is not a Gini over the book restricted to that segment's summary
    row, and the engine refuses rather than faking one. Falling back to the
    single figure and saying so beats both a refusal and an invented chart.
    """
    from backend.metrics import execution, service
    from backend.orchestration import dimensions
    from backend.orchestration.handlers import HandlerResult

    metric = routed.metric
    period = "" if routed.trend else (routed.period
                                      or service.default_period(metric))
    try:
        drawn = execution.breakdown(
            metric.formula, dimension=routed.dimension,
            # A series spans every published month, so it names no ONE of
            # them; a cut is taken at a single reporting date.
            period="" if routed.trend else period,
            scope=metric.scope,
            sort="label" if routed.trend else "value",
            direction="asc" if routed.trend else "desc",
            limit=MAX_PERIODS if routed.trend else MAX_GROUPS,
            question=question)
    except Exception:  # noqa: BLE001 - stated, then the single figure
        logger.exception("The metric breakdown failed for %r", metric.metric_id)
        return None
    if drawn.get("unavailable"):
        return None
    points = [p for p in (drawn.get("points") or [])
              if p.get("value") is not None]
    if routed.trend:
        points = _windowed(points, question)
    if not points:
        return None

    label = dimensions.readable(routed.dimension)
    ordered = sorted(points, key=lambda p: p["value"], reverse=True)
    top = ordered[0]
    bottom = ordered[-1]
    unit, places = str(metric.unit), int(metric.decimals)
    where = f" at {period}" if period else ""
    if routed.trend:
        # A series reads in DATE order, never by size: a trend sorted by value
        # is a ranking with the x-axis mislabelled.
        points = sorted(points, key=lambda p: str(p.get("label") or ""))
        first, last = points[0], points[-1]
        direction = ("rose" if last["value"] > first["value"] else
                     "fell" if last["value"] < first["value"] else "was flat")
        sentence = (
            f"{metric.name} {direction} from "
            f"{_format(first['value'], unit, places)} at {first['label']} to "
            f"{_format(last['value'], unit, places)} at {last['label']}, "
            f"across {len(points)} reporting months. It is "
            f"{metric.formula_text}." if metric.formula_text else
            f"{metric.name} {direction} from "
            f"{_format(first['value'], unit, places)} at {first['label']} to "
            f"{_format(last['value'], unit, places)} at {last['label']}, "
            f"across {len(points)} reporting months.")
    elif routed.ranked:
        # Led by the end the question asked for. "Which subsegment has the
        # LOWEST Stage 2 rate?" opened "CARD has the highest Stage 2 Share of
        # Exposure" — the right table under the opposite sentence, and a
        # reader who takes the first line at its word has the wrong answer.
        if _ASKS_FOR_THE_LOWEST.search(routed.question or ""):
            sentence = (
                f"{bottom['label']} has the lowest {metric.name}{where}, at "
                f"{_format(bottom['value'], unit, places)}. "
                f"{top['label']} is the highest, at "
                f"{_format(top['value'], unit, places)}.")
        else:
            sentence = (
                f"{top['label']} has the highest {metric.name}{where}, at "
                f"{_format(top['value'], unit, places)}. "
                f"{bottom['label']} is the lowest, at "
                f"{_format(bottom['value'], unit, places)}.")
    else:
        sentence = (
            f"{metric.name} across {len(ordered)} "
            f"{label.lower()}{'' if len(ordered) == 1 else 's'}{where}. "
            f"{top['label']} is highest at "
            f"{_format(top['value'], unit, places)}.")
    if metric.formula_text:
        sentence += f" Each group is {metric.formula_text}."

    # A series reads in DATE order and a breakdown reads largest first. Both
    # the sentence and the table have to use the same one, or the "highest"
    # the prose names is not the first row of the table.
    shown = points if routed.trend else ordered
    return HandlerResult(
        answer=sentence,
        rows=[{"label": p["label"], "value": p["value"], "rows": p.get("rows", 0)}
              for p in shown],
        columns=[{"name": "label",
                  "label": "Reporting month" if routed.trend else label,
                  "type": "string"},
                 {"name": "value", "label": metric.name, "type": "number",
                  "unit": metric.unit, "decimals": metric.decimals},
                 {"name": "rows", "label": "Facilities", "type": "number"}],
        values={"metric_id": metric.metric_id, "period": period,
                "dimension": routed.dimension,
                "highest": top["label"], "lowest": bottom["label"]},
        detail={"metric": _panel(metric),
                "breakdown": {"dimension": routed.dimension,
                              "period": period,
                              "groups": len(ordered)},
                "source": "metric_catalogue"},
        # A bar for groups on a nominal scale; a LINE for a series, where the
        # order is the meaning. Drawing a month series as bars loses the shape
        # a reader is looking for, and drawing nominal groups as a line
        # asserts an order the dimension does not have.
        chart={"chart": "line" if routed.trend else "bar",
               "x": "label", "y": ["value"],
               "chart_first": True, "alternatives": ["table"],
               "reason": (f"one governed metric compared across "
                          f"{label.lower()}")},
        execution="computed",
        execution_label="Governed metric engine",
        graph=_trace(question, routed, period, None,
                     groups=len(ordered)),
        follow_ups=_follow_ups(routed),
        title=f"{metric.name} by {label.lower()}",
    )


def _trace(question: str, routed: Routed, period: str,
           calculation: Any, *, groups: int = 0) -> Any:
    """The Trace for a metric answer: a real calculation, said to be one.

    It names the metric, its formula in words, its scope and its period rule,
    because the whole reason to answer from the catalogue rather than from a
    fresh group-by is that those four things are published and reviewable.
    """
    from backend.trace.model import NodeType, TraceGraph, TraceNode

    metric = routed.metric
    try:
        graph = TraceGraph()
        graph.add_node(TraceNode(
            id="question", type=NodeType.USER_PROMPT, label="Question asked",
            config={"question": question}))
        intent = graph.add_node(TraceNode(
            id="intent", type=NodeType.CAPABILITY,
            label=f"Read as: the governed metric {metric.name}",
            config={"metric_id": metric.metric_id,
                    "matched_phrase": routed.phrase,
                    "computation_required": True,
                    "rule": ("A rate is a numerator, a denominator and a "
                             "scope. Those live in the Metric Catalogue, so "
                             "the answer is the catalogue's own definition "
                             "rather than a fresh group-by that would agree "
                             "with the dashboard only by coincidence.")}))
        intent.mark_ok()
        graph.connect("question", "intent")

        dataset = metric.datasets[0] if metric.datasets else ""
        source = graph.add_node(TraceNode(
            id="population", type=NodeType.DATASET,
            label=f"{dataset} at {period}" if period else dataset,
            config={"dataset": dataset, "fields": list(metric.fields),
                    "period": period,
                    "period_rule": metric.period_rule,
                    "scope": [c.describe() for c in metric.scope]}))
        source.mark_ok()
        graph.connect("intent", "population")

        node = graph.add_node(TraceNode(
            id="metric", type=NodeType.CALCULATION,
            label=f"{metric.name} — {metric.formula_text or metric.definition}",
            config={"formula": metric.formula.to_dict(),
                    "formula_text": metric.formula_text,
                    "numerator": metric.numerator_text,
                    "denominator": metric.denominator_text,
                    "not_this": metric.not_this,
                    "unit": metric.unit,
                    "calculation": (calculation if isinstance(calculation, dict)
                                    else {}),
                    "groups": groups,
                    "dimension": routed.dimension}))
        node.mark_ok()
        graph.connect("population", "metric")
        return graph
    except Exception:  # noqa: BLE001 - a missing Trace is not a missing answer
        logger.exception("Could not build the Trace for %r", metric.metric_id)
        return None
