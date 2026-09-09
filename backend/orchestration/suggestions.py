"""
What is worth asking next, from what is actually on the screen.

The failure
-----------
Every answer offered the same three things. After the five largest Real Estate
customers, after a sector distribution, after a rating-grade profile — "how has
exposure at default moved over the latest year?", every time. A suggestion that
appears whatever the answer was is not a suggestion; it is furniture, and people
stop reading it within about four turns.

What a suggestion has to be
---------------------------
Derived from **this** result. There are five things worth deriving it from, and
they are ranked in the order an analyst would think of them:

1. **The population on the screen.** Five named customers invite questions
   about those five, and the product already knows how to answer them.
2. **The outlier.** One row is bigger, worse or more surprising than the rest,
   and it has a name.
3. **Governed data that was NOT read.** The catalogue holds ratings, covenants
   and delinquency; an answer that used none of them can offer one, and that is
   the suggestion most likely to teach somebody what the product can do.
4. **The obvious next cut** — over time, by sector, as a share.
5. **Keeping the work**, once there is enough of it to be worth keeping.

Nothing here asks a question CreditProbe cannot answer. Every template maps to
a shape the planner handles, because a suggestion that produces a clarification
is worse than no suggestion: the user did what the product told them to and the
product asked them what they meant.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: How many are offered. Three fits under a composer without wrapping; a fourth
#: is allowed when one of them is "keep this", which is an action rather than a
#: question.
MAX_SUGGESTIONS = 4

#: A population small enough that questions about "these" mean something. Above
#: it, "which of these are Stage 2" is a question about a table, not a list.
NAMED_POPULATION = 50

#: Concepts worth offering when the answer did not read them, in the order a
#: credit officer would reach for them. Each maps to a governed dataset.
_ENRICHMENTS: tuple[tuple[str, str, str], ...] = (
    ("ifrs9_stage", "ifrs9_staging", "Which of these are in Stage 2 or Stage 3?"),
    ("internal_grade", "customer_ratings", "Add their latest internal rating."),
    ("total_ecl", "ifrs9_staging",
     "Show expected credit loss and how it moved over the latest year."),
    ("days_past_due", "facility_delinquency",
     "Are any of them past due, and by how long?"),
    ("headroom_pct", "covenant_tests",
     "How much covenant headroom do they have?"),
    ("utilisation_pct", "portfolio_facility",
     "How much of their limits are drawn?"),
)


def after_analysis(build: Any, runtime: Any) -> list[str]:
    """Three or four things worth asking about THIS result."""
    try:
        return _after_analysis(build, runtime)
    except Exception as e:  # noqa: BLE001 - a suggestion must not lose an answer
        logger.warning("Could not build suggestions: %s", e)
        return []


def _after_analysis(build: Any, runtime: Any) -> list[str]:
    rows = list(getattr(runtime, "rows", []) or [])
    out: list[str] = []

    if not rows:
        # An empty result. The useful next questions are about loosening it,
        # not about drilling into nothing.
        conditions = [c for c in (getattr(build, "conditions", None) or [])]
        if conditions:
            out.append("Show the same population without that threshold.")
        if getattr(build, "filters", None):
            out.append("Show the same test across the whole book.")
        out.append("What data does CreditProbe hold on this?")
        return _tidy(out)

    named = _named(build, rows)
    if named:
        out.extend(_about_the_population(build, named))
        # Only where there IS a population. "Which of these are in Stage 2?"
        # under a table of sectors asks about sectors, and a sector has no
        # stage — the suggestion would produce a clarification, which is the
        # product telling somebody to ask a question and then not understanding
        # it.
        out.extend(_unread(build))
    else:
        out.extend(_about_the_distribution(build, rows))
    out.extend(_over_time(build))
    if len(rows) > 1:
        out.append("Save this investigation to a project.")
    return _tidy(out)


# ---------------------------------------------------------------------------
# Which kind of result this is
# ---------------------------------------------------------------------------


def _named(build: Any, rows: list[dict[str, Any]]) -> str:
    """The column naming each counterparty, when the result is a list of them."""
    if len(rows) > NAMED_POPULATION:
        return ""
    if str(getattr(build, "grain", "") or "") not in ("customer", "facility",
                                                      "borrower"):
        return ""
    for key in ("borrower_name", "customer_name", "customer_id", "account_id"):
        if key in rows[0]:
            return key
    return ""


def _about_the_population(build: Any, key: str) -> list[str]:
    """Questions about the counterparties on the screen."""
    del key
    out: list[str] = []
    if len(getattr(build, "matches", None) or []) > 1:
        out.append("Which two are most concerning, and why?")
    else:
        out.append("Which of them is most concerning, and why?")
    return out


def _about_the_distribution(build: Any, rows: list[dict[str, Any]]) -> list[str]:
    """Questions about a result grouped by something."""
    dimension = str(getattr(build, "dimension", "") or "")
    if not dimension:
        return ["Break that down by sector."]

    out: list[str] = []
    leader = _leader(dimension, rows)
    if leader:
        # The outlier has a name, and naming it is what makes the suggestion
        # feel like it was written about this result rather than about results.
        out.append(f"Show the largest customers in {leader}.")
    out.append(f"Show each {dimension.replace('_', ' ')} as a share of the "
               "portfolio.")
    return out


def _leader(dimension: str, rows: list[dict[str, Any]]) -> str:
    """The group the first row is about, when the result is ordered."""
    value = (rows[0] or {}).get(dimension)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


# ---------------------------------------------------------------------------
# Governed data this answer did not read
# ---------------------------------------------------------------------------


def _unread(build: Any) -> list[str]:
    """The first enrichment the answer did not already have.

    One, not all of them. A list of six things the product could also do reads
    as a menu, and a menu under an answer is the product asking the user to do
    its thinking.
    """
    read_fields = {str(getattr(m, "field", "")).lower()
                   for m in (getattr(build, "matches", None) or [])}
    read_datasets = {str(d).lower() for d in (getattr(build, "datasets", None) or [])}

    for field_name, dataset, question in _ENRICHMENTS:
        if field_name in read_fields:
            continue
        if any(field_name in column for column in read_fields):
            continue
        if dataset.lower() in read_datasets and field_name in read_fields:
            continue
        return [question]
    return []


def _over_time(build: Any) -> list[str]:
    """The comparison the answer did not make."""
    if getattr(build, "opening", "") and getattr(build, "closing", ""):
        return ["Which customers drove that movement?"]
    matches = list(getattr(build, "matches", None) or [])
    if not matches:
        return []
    label = str(getattr(matches[0].concept, "label", "") or "").lower()
    if not label:
        return []
    return [f"How has {label} moved over the latest year?"]


# ---------------------------------------------------------------------------
# Metadata answers and the empty Cockpit
# ---------------------------------------------------------------------------


#: How many the Cockpit shows at once. Three fits under the composer without
#: wrapping, and three is enough to say what kind of product this is without
#: turning the opening screen into a menu.
COCKPIT_AT_ONCE = 3

#: The questions approved for the Cockpit, and the governed datasets each one
#: needs before it may be offered.
#:
#: A closed list, on purpose. A suggestion is a PROMISE: the reader did not
#: choose it, the product offered it, and an offered question that comes back
#: as "which figure should CreditProbe measure?" is worse than no suggestion at
#: all — the user did exactly what they were told and the product asked them
#: what they meant. Every one of these has been run through the real Ask path
#: and answers; `tests/api/test_cockpit_suggestions.py` runs them again.
#:
#: `needs` is checked against the catalogue that is actually installed, so a
#: deployment without a dataset offers the question that does not need it
#: rather than a question it cannot answer.
COCKPIT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Where is risk building across the bank?",
     ("portfolio_facility",)),
    ("Which exposures have deteriorated this quarter?",
     ("portfolio_facility",)),
    ("What is driving Stage 2 and ECL growth?",
     ("portfolio_facility", "ifrs9_staging")),
    ("Which borrowers are weakening but are not yet on the watchlist?",
     ("portfolio_facility",)),
    ("Where are multiple warning signals appearing together?",
     ("portfolio_facility",)),
)


def _rotation(on: Any = None) -> int:
    """Which of the approved questions the Cockpit starts from today.

    Rotated by the DATE rather than at random. A random three would change
    under the reader between one page load and the next — including in the
    middle of a sentence someone was reading — and would make the opening
    screen impossible to describe to a colleague. By the date it is stable all
    day, different tomorrow, and reproducible: the same day gives the same
    three, which is what lets a test assert on it.
    """
    from datetime import date

    day = on or date.today()
    return day.toordinal() % max(len(COCKPIT), 1)


def opening(context: Any, *, on: Any = None) -> list[str]:
    """Exactly three things to ask when nothing has been asked yet.

    Three of the approved five, rotated by the day, and only the ones the
    installed catalogue can actually answer.
    """
    try:
        datasets = list(getattr(context, "datasets", None) or [])
        names = {str(getattr(d, "name", "")).lower() for d in datasets}
        answerable = [question for question, needs in COCKPIT
                      if all(n in names for n in needs)]
        if not answerable:
            # Nothing governed to ask about. Offering a question anyway would
            # be advertising a capability this installation does not have.
            if not datasets:
                return []
            first = getattr(datasets[0], "business_name", "") or getattr(
                datasets[0], "name", "")
            return _tidy([f"What data do you have in {first}?"])
        start = _rotation(on) % len(answerable)
        rotated = answerable[start:] + answerable[:start]
        return _tidy(rotated)[:COCKPIT_AT_ONCE]
    except Exception as e:  # noqa: BLE001 - an empty composer is not a failure
        logger.warning("Could not build opening suggestions: %s", e)
        return []


# ---------------------------------------------------------------------------
# After a multi-analysis answer. §40.
# ---------------------------------------------------------------------------


def after_compound(reading: Any, portfolio: Any = None, *,
                   build: Any = None, runtime: Any = None,
                   case_context: str = "") -> list[str]:
    """What is worth asking after a compound answer. §40.

    Two sources a single-analysis answer does not have, and they come first
    because they are the two the reader is most likely to already be
    thinking about:

    **An objective that did not get answered.** If one clause of the request
    needed a word from the user, the most useful next question is the one
    that supplies it. Offering a fresh analysis instead, while a part of what
    they asked sits unanswered, is the product changing the subject.

    **The Project or Risk Case this sits in.** Work inside a case has a next
    step that work outside it does not.

    Everything after that is `after_analysis`'s five, unchanged - they are
    derived from the result on the screen and that reasoning does not change
    because several analyses produced it.

    §40's last two rules are structural here rather than aspirational. Thread
    scope is preserved because every suggestion is phrased against the
    population already on the screen. Nothing unsupported is suggested
    because the only analyses offered are ones the portfolio actually
    proposed - a suggestion the planner already rejected as uncomputable
    would send the user to a refusal they were invited to ask for.
    """
    try:
        out: list[str] = []
        objectives = list(getattr(reading, "objectives", None) or [])

        for objective in objectives:
            status = str(getattr(objective, "status", ""))
            note = str(getattr(objective, "note", "") or "")
            label = str(getattr(objective, "description", "") or "").strip()
            if not label:
                continue
            if status == "NEEDS_CLARIFICATION":
                out.append(_clarifying_prompt(label, note))
            elif status in ("PARTIAL", "FAILED"):
                out.append(f"Go back to \u201c{_short(label)}\u201d and "
                           "finish it.")

        if case_context:
            out.append(f"Add this to {case_context}.")

        # An analysis the planner proposed, could compute, and did not run.
        # Offering one of these is safe by construction: it was scored as
        # available before it was set aside.
        for decision in getattr(portfolio, "rejected", None) or []:
            score = getattr(decision, "score", None)
            if score is None or score.availability < 0.5:
                continue
            question = str(getattr(decision.candidate, "question", "")
                           or "").strip()
            if question:
                out.append(question)
            break

        if build is not None or runtime is not None:
            out.extend(after_analysis(build, runtime))
        return _tidy(out)
    except Exception as e:  # noqa: BLE001 - a suggestion must not lose an answer
        logger.warning("Could not build compound suggestions: %s", e)
        return []


def _short(label: str, limit: int = 60) -> str:
    text = " ".join(str(label or "").split()).rstrip(".?")
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def _clarifying_prompt(label: str, note: str) -> str:
    """The question that would settle an objective the answer stopped on.

    Phrased as the user's own next message rather than as a restatement of
    the problem: "which measure did you mean" is what the product already
    said, and repeating it as a suggestion is not a suggestion.
    """
    hint = " ".join(str(note or "").split())
    if hint:
        return f"About \u201c{_short(label)}\u201d: {hint}"
    return f"Say more about what \u201c{_short(label)}\u201d should mean."


def _tidy(questions: list[str]) -> list[str]:
    """In order, without repeats, capped."""
    seen: set[str] = set()
    out: list[str] = []
    for question in questions:
        text = str(question or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out[:MAX_SUGGESTIONS]


__all__ = ["MAX_SUGGESTIONS", "NAMED_POPULATION", "after_analysis",
           "after_compound", "opening"]
