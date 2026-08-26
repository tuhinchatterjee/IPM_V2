"""
Follow-ups answered from what the last turn produced, with nothing recomputed.

Four kinds of turn reach here, and none of them is an analysis:

**METADATA_FOLLOWUP** — "which of those fields are financial ratios?" The
previous turn produced a field set; this one classifies it. The answer is in the
catalogue, and running a portfolio query to produce it would be both slower and
wrong.

**NAVIGATE** — "open the latest dataset." The conversation is already about a
dataset. This is a link, not a question.

**ASK_ABOUT_RESULT** — "why is Contracting highest?" The figures are on the
table. What is wanted is an explanation of them, grounded in what was already
computed.

**MODIFY_PRESENTATION** — "show it as a graph." Handled by the executor, which
has the previous run; this module only recognises it.

Why they are here rather than in `handlers`
-------------------------------------------
`handlers` answers a *capability* — a question about the catalogue, read fresh.
These answer a *reference* — a question about the previous answer. The
distinction is the whole point of typed memory: the same sentence means
different things depending on what is on the table, and a handler that had to
guess which would be guessing on every turn.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.orchestration import memory as wm
from backend.orchestration.handlers import HandlerResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classifying a remembered field set
# ---------------------------------------------------------------------------

#: What a follow-up can ask a field set to be filtered by, and how to decide.
#:
#: Each rule is a question pattern plus a predicate over the field's remembered
#: attributes. Deliberately governed by unit and declared type rather than by
#: the model's opinion of a column name: "is `dscr` a ratio?" has an answer in
#: the catalogue, and asking a model produces one that is usually the same and
#: occasionally not.
_RATIO_UNITS = frozenset({"x", "%", "ratio", "times", "percent", "percentage"})
_MONEY_UNITS = frozenset({"usd mn", "usd", "sar mn", "sar", "mn", "amount"})
_NUMERIC_TYPES = frozenset({"float", "double", "int", "integer", "number",
                            "decimal", "numeric", "bigint"})


def _is_ratio(member: wm.Member) -> bool:
    attrs = member.attributes
    unit = str(attrs.get("unit") or "").strip().lower()
    if unit in _RATIO_UNITS:
        return True
    if unit in _MONEY_UNITS:
        return False
    name = f"{member.id} {member.label}".lower()
    return bool(re.search(r"ratio|coverage|_pct|percent|margin|dscr|leverage"
                          r"|utilisation|utilization|headroom|yield|rate", name))


def _is_money(member: wm.Member) -> bool:
    unit = str(member.attributes.get("unit") or "").strip().lower()
    return unit in _MONEY_UNITS


def _is_numeric(member: wm.Member) -> bool:
    attrs = member.attributes
    if str(attrs.get("type") or "").strip().lower() in _NUMERIC_TYPES:
        return True
    return bool(str(attrs.get("unit") or "").strip())


def _is_date(member: wm.Member) -> bool:
    kind = str(member.attributes.get("type") or "").strip().lower()
    name = f"{member.id}".lower()
    return "date" in kind or "time" in kind or name.endswith(("_date", "_at"))


def _is_identifier(member: wm.Member) -> bool:
    name = str(member.id).lower()
    return name.endswith("_id") or name in {"period", "customer", "account"}


#: (pattern, label, predicate). First match wins, so the specific patterns come
#: before the general ones.
_FIELD_FILTERS: tuple[tuple[str, str, Any], ...] = (
    (r"financial ratios?|\bratios?\b", "financial ratios", _is_ratio),
    (r"monetary|money|amounts?|currency|balances?", "monetary amounts", _is_money),
    (r"\bdates?\b|time|when", "dates", _is_date),
    (r"identifiers?|\bids?\b|keys?", "identifiers", _is_identifier),
    (r"numeric|numerical|numbers?|quantitative|measures?",
     "numeric measures", _is_numeric),
)


def _classify_fields(question: str, result: wm.ResultReference,
                     ) -> HandlerResult | None:
    lowered = (question or "").lower()
    for pattern, label, predicate in _FIELD_FILTERS:
        if not re.search(pattern, lowered):
            continue
        matched = [m for m in result.members if predicate(m)]
        origin = result.origin or "the previous result"
        if not matched:
            return HandlerResult(
                answer=(f"None of the {len(result.members)} fields in {origin} "
                        f"are {label}."),
                rows=[], columns=[])
        rows = [{"field": m.id,
                 "business_name": m.label,
                 "unit": m.attributes.get("unit", ""),
                 "type": m.attributes.get("type", ""),
                 "definition": m.attributes.get("definition", "")}
                for m in matched]
        return HandlerResult(
            answer=(f"{len(matched)} of the {len(result.members)} fields in "
                    f"{origin} are {label}: "
                    + ", ".join(m.label or m.id for m in matched[:8])
                    + ("…" if len(matched) > 8 else "") + "."),
            rows=rows,
            columns=[{"name": "field", "label": "Field"},
                     {"name": "business_name", "label": "Business name"},
                     {"name": "unit", "label": "Unit"},
                     {"name": "type", "label": "Type"},
                     {"name": "definition", "label": "Definition"}],
            values={"matched": len(matched), "of": len(result.members)},
            detail={"classified_from": origin, "criterion": label})
    return None


# ---------------------------------------------------------------------------
# Metadata about whatever the conversation is currently about
# ---------------------------------------------------------------------------

_PERIOD_QUESTION = re.compile(
    r"latest (?:available )?(?:period|quarter|year|reporting date)"
    r"|most recent (?:period|quarter|year)"
    r"|what periods?|which periods?|how (?:many|much) (?:history|periods)"
    r"|period(?:s)? (?:are |is )?(?:available|covered)", re.I)

_COUNT_QUESTION = re.compile(
    r"how many (?:fields|columns|rows|records|datasets|relationships)", re.I)


def _about_subject(question: str, memory: wm.WorkingMemory,
                   context: Any) -> HandlerResult | None:
    """A metadata question about the dataset the thread is already on.

    "What is the latest available period?" after an IFRS 9 answer is a question
    about `ifrs9_staging`, and answering it with a menu of governed figures —
    which is what happened — reads as though CreditProbe forgot the sentence
    before it.
    """
    subject = memory.current_subject or memory.result.origin
    if not subject:
        return None

    dataset = _dataset(subject, context)
    if dataset is None:
        return None

    if _PERIOD_QUESTION.search(question or ""):
        periods = list(getattr(dataset, "periods", ()) or ())
        latest = getattr(dataset, "latest_period", "") or (periods[-1] if periods else "")
        if not latest:
            return None
        return HandlerResult(
            answer=(f"The latest published period in "
                    f"{getattr(dataset, 'business_name', subject)} ({subject}) "
                    f"is {latest}. It carries {len(periods)} periods"
                    + (f", from {periods[0]} to {latest}." if periods else ".")),
            rows=[{"dataset": subject, "period": p,
                   "latest": p == latest} for p in periods],
            columns=[{"name": "dataset", "label": "Dataset"},
                     {"name": "period", "label": "Period"},
                     {"name": "latest", "label": "Latest"}],
            values={"latest_period": latest, "periods": len(periods)},
            detail={"answered_about": subject,
                    "because": "the conversation is about this dataset"})

    if _COUNT_QUESTION.search(question or ""):
        fields = list(getattr(dataset, "fields", ()) or ())
        return HandlerResult(
            answer=(f"{getattr(dataset, 'business_name', subject)} ({subject}) "
                    f"carries {len(fields)} governed fields."),
            values={"fields": len(fields)},
            detail={"answered_about": subject})

    return None


def _dataset(name: str, context: Any) -> Any:
    for dataset in (getattr(context, "datasets", ()) or ()):
        if getattr(dataset, "name", "") == name:
            return dataset
    for dataset in (getattr(context, "other_datasets", ()) or ()):
        if getattr(dataset, "name", "") == name:
            return dataset
    try:
        from backend.data_access import get_data_source

        return get_data_source().describe(name)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


def _navigate(question: str, memory: wm.WorkingMemory,
              context: Any) -> HandlerResult | None:
    """Open what the conversation is about, rather than answering about it."""
    subject = memory.current_subject or memory.result.origin
    if not subject:
        return None
    dataset = _dataset(subject, context)
    if dataset is None:
        return None

    latest = getattr(dataset, "latest_period", "")
    business = getattr(dataset, "business_name", subject)
    return HandlerResult(
        answer=(f"Opening {business} ({subject})"
                + (f" at {latest}." if latest else ".")),
        rows=[{"dataset": subject, "business_name": business,
               "period": latest, "grain": getattr(dataset, "grain", ""),
               "fields": len(getattr(dataset, "fields", ()) or ())}],
        columns=[{"name": "dataset", "label": "Dataset"},
                 {"name": "business_name", "label": "Business name"},
                 {"name": "period", "label": "Period"},
                 {"name": "grain", "label": "Grain"},
                 {"name": "fields", "label": "Fields"}],
        values={"dataset": subject, "period": latest},
        detail={"open": {"kind": "dataset", "name": subject, "period": latest},
                "href": f"/data-builder/{subject}"
                        + (f"?period={latest}" if latest else "")},
        follow_ups=[f"What fields are in {subject}?",
                    f"How is {subject} connected to other data?"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def answer(question: str, action: str, memory: wm.WorkingMemory,
           context: Any) -> HandlerResult | None:
    """Answer this follow-up from memory, or None to fall through.

    Returning None is the normal outcome for anything this cannot answer, and
    the caller then plans an analysis as usual. It never approximates: a
    follow-up it half-understands is one the ordinary path should read
    properly.
    """
    from backend.orchestration import conversation as cv

    if memory is None or memory.empty:
        return None

    try:
        if action == cv.NAVIGATE:
            return _navigate(question, memory, context)

        if action in (cv.METADATA_FOLLOWUP, cv.CONTINUE, cv.NEW_REQUEST):
            if memory.result.result_type == wm.FIELD_SET:
                found = _classify_fields(question, memory.result)
                if found is not None:
                    return found
            return _about_subject(question, memory, context)
    except Exception as e:  # noqa: BLE001 - never lose an answer to a follow-up
        logger.warning("A follow-up could not be answered from memory: %s", e)
        return None

    return None


__all__ = ["answer"]
