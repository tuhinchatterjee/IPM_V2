"""
When nothing matched, say what the population actually is.

The failure this fixes
----------------------
A credit officer asked for the five largest Real Estate customers by EAD, got
them, and then asked:

    Which of these are Stage 2 or Stage 3?

All five were Stage 1. CreditProbe answered "0 customers where IFRS 9 stage is
in 2, 3", which is true, useless, and reads like a malfunction. What an analyst
says is:

    None of the five customers is in Stage 2 or Stage 3; all five are
    currently Stage 1 at Q2 2026.

The difference is not phrasing. The second sentence contains a fact the first
one does not — where the population actually sits — and getting it requires
asking the data a second question.

What this does
--------------
Exactly one thing, and only when a result came back empty: it re-runs the plan
that produced nothing, with the predicate that emptied it removed, grouped by
the column that predicate tested. That returns the distribution of the
classifying attribute across the population the user was actually looking at.

Why it is safe
--------------
* It never runs unless the result is empty, so no answer that works today
  changes.
* It is the same governed plan, through the same runtime, with one predicate
  removed — not a second query written somewhere else that could disagree.
* Every restriction that is not the classifying one survives, including the
  carried population. Dropping those would answer a question about the whole
  book and present it as a question about five customers.
* Anything unexpected returns no partition at all. An empty result explained
  badly is worse than an empty result explained not at all.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: More distinct values than this and the attribute is an identifier rather
#: than a classification. "None of the five are X; they are spread across 4,812
#: values" is not a sentence that helps anybody.
MAX_CLASSES = 12

#: Beyond this the population is not something a sentence can characterise.
MAX_MEMBERS = 5000


@dataclass
class Partition:
    """Where the population sits on the attribute that excluded it."""

    #: The governed column the excluded predicate tested.
    column: str = ""
    #: What a credit officer calls it.
    label: str = ""
    #: The values the question asked for, as text.
    wanted: list[str] = field(default_factory=list)
    #: value -> how many members of the population carry it, largest first.
    counts: list[tuple[str, int]] = field(default_factory=list)
    #: How many members the population has in total.
    total: int = 0
    #: The period the attribute was read at.
    period: str = ""
    #: What the members are: customers, facilities, sectors.
    grain: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.column and self.counts and self.total)

    @property
    def unanimous(self) -> bool:
        """Whether the whole population sits on one value."""
        return len(self.counts) == 1

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "label": self.label,
                "wanted": list(self.wanted),
                "counts": [{"value": v, "members": n} for v, n in self.counts],
                "total": self.total, "period": self.period,
                "grain": self.grain}


# ---------------------------------------------------------------------------
# Finding the predicate that emptied the result
# ---------------------------------------------------------------------------


def _predicate_columns(operation: dict[str, Any]) -> list[str]:
    where = ((operation.get("params") or {}).get("where") or [])
    return [str(p.get("column") or "") for p in where if isinstance(p, dict)]


def _wanted(operations: list[dict[str, Any]], column: str) -> list[str]:
    """The values the question asked for, in the order it asked for them."""
    out: list[str] = []
    for operation in operations:
        if str(operation.get("op") or "") != "FILTER":
            continue
        for predicate in ((operation.get("params") or {}).get("where") or []):
            if not isinstance(predicate, dict):
                continue
            if str(predicate.get("column") or "") != column:
                continue
            if "values" in predicate:
                out.extend(str(v) for v in (predicate.get("values") or []))
            elif "value" in predicate:
                out.append(str(predicate.get("value")))
    return out


def classifying(build: Any) -> str:
    """The column whose predicate is the one worth removing.

    A question restricts a population in two different ways at once. "Which of
    these five are Stage 2 or Stage 3" carries a restriction to the five — that
    is the population, and removing it changes the subject — and a restriction
    to stages 2 and 3, which is the classification being asked about. Only the
    second is removable, and it is identified by being the one the question
    named a concept for.
    """
    named = [m for m in (getattr(build, "matches", None) or [])]
    fields = {str(getattr(m, "field", "")) for m in named}

    # A LEVEL CONDITION FIRST, where the plan carries one.
    #
    # A question restricts a population twice over, and the two halves are not
    # interchangeable. "Which Stage 3 borrowers are not on the watchlist?"
    # names its SUBJECT with the stage — that is who the question is about —
    # and applies its TEST with the watchlist. Removing the subject asks a
    # different question, and the answer said so out loud: "None of Stage 3
    # customers is in IFRS 9 stage 3; all 2,138 are in stage 1", a sentence
    # that contradicts its own first clause and counts a population nobody
    # asked about.
    #
    # So where a question states both, the test is what is worth removing:
    # "where do the borrowers the question was about actually sit?" is a
    # question about the test, not about the subject.
    for condition in (getattr(build, "conditions", None) or []):
        if str(getattr(condition, "kind", "")) == "level" \
                and str(getattr(condition, "field", "")) in fields:
            return str(getattr(condition, "field", ""))

    # A membership filter the planner recorded as a value restriction. Where
    # the question stated no separate test — "which of these five are Stage 2
    # or Stage 3" — the value restriction IS the classification being asked
    # about, and removing it is what shows the reader where the five sit.
    for filter_field, _value in (getattr(build, "filters", None) or []):
        if str(filter_field) in fields:
            return str(filter_field)
    return ""


# ---------------------------------------------------------------------------
# Rewriting the plan
# ---------------------------------------------------------------------------


def probe_plan(plan: dict[str, Any], column: str,
               key: str) -> dict[str, Any] | None:
    """The same plan, without `column`'s predicate, counted by `column`.

    Returns None where the plan is not a shape this can rewrite. That is a
    normal outcome and not an error: the caller simply has no partition to
    report, which is where it started.
    """
    operations = copy.deepcopy(list(plan.get("operations") or []))
    if not operations:
        return None

    kept: list[dict[str, Any]] = []
    removed = False
    #: Nodes dropped entirely, and what their consumers should read instead.
    rewire: dict[str, str] = {}

    for operation in operations:
        identifier = str(operation.get("id") or "")
        inputs = [rewire.get(i, i) for i in (operation.get("inputs") or [])]
        operation["inputs"] = inputs

        if str(operation.get("op") or "") == "FILTER" \
                and column in _predicate_columns(operation):
            params = operation.get("params") or {}
            where = [p for p in (params.get("where") or [])
                     if not (isinstance(p, dict)
                             and str(p.get("column") or "") == column)]
            removed = True
            if not where:
                # The node existed only to apply this predicate. Drop it and
                # point whatever read it at what it read.
                if not inputs:
                    return None
                rewire[identifier] = inputs[0]
                continue
            operation["params"] = {**params, "where": where}
        kept.append(operation)

    if not removed:
        return None

    anchor = _anchor(kept)
    if anchor is None:
        return None

    kept = kept[:kept.index(anchor) + 1]
    if not _carries(anchor, column, key):
        return None
    kept.append({
        "id": "partition",
        "op": "GROUP",
        "inputs": [str(anchor.get("id"))],
        "params": {
            "by": [column],
            "aggregates": [{"function": "count_distinct", "column": key,
                            "as": "members"}],
        },
        "label": f"Count the population by {column.replace('_', ' ')}",
    })
    kept.append({
        "id": "result",
        "op": "SORT",
        "inputs": ["partition"],
        "params": {"by": [{"column": "members", "direction": "desc"},
                          {"column": column, "direction": "asc"}]},
        "label": "Largest group first",
    })

    return {**{k: v for k, v in plan.items() if k != "operations"},
            "id": f"{plan.get('id') or 'plan'}_partition",
            "operations": kept}


def _carries(anchor: dict[str, Any], column: str, key: str) -> bool:
    """Whether the population node still holds both columns to group by.

    A GROUP that reduced to one row per customer without keeping the stage on
    it cannot be grouped by stage afterwards. Where the column is missing this
    adds it as a per-member value rather than silently producing a partition of
    something else; where the node is not a GROUP at all it is a row-level
    frame and carries whatever the scan read.
    """
    if str(anchor.get("op") or "") != "GROUP":
        return True

    params = anchor.get("params") or {}
    grouped = [str(c) for c in (params.get("by") or [])]
    aggregates = list(params.get("aggregates") or [])
    produced = grouped + [str(a.get("as") or a.get("column") or "")
                          for a in aggregates if isinstance(a, dict)]

    if key not in produced:
        return False
    if column in produced:
        return True

    anchor["params"] = {
        **params,
        "aggregates": [*aggregates,
                       {"function": "max", "column": column, "as": column}],
    }
    return True


def _anchor(operations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The node that holds one row per member of the population.

    The last GROUP, which is where the pipeline reduces to the grain. Falling
    back to the last node that is not an ordering or a cap, because a plan with
    no grouping in it already carries one row per member.
    """
    for operation in reversed(operations):
        if str(operation.get("op") or "") == "GROUP":
            return operation
    for operation in reversed(operations):
        if str(operation.get("op") or "") not in ("SORT", "LIMIT"):
            return operation
    return None


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def explain(build: Any, question: str = "") -> Partition | None:
    """Where the population sits on the attribute that excluded all of it.

    Called only when a result came back empty. Returns None whenever anything
    is not exactly as expected, which is most of the ways this can go.
    """
    try:
        return _explain(build, question)
    except Exception as e:  # noqa: BLE001 - an explanation must not lose an answer
        logger.info("No partition could be computed for an empty result: %s", e)
        return None


def _explain(build: Any, question: str) -> Partition | None:
    from backend.runtime.executor import ExecutionClass, execute

    column = classifying(build)
    if not column:
        return None

    key = _key_of(build)
    if not key:
        return None

    plan = probe_plan(getattr(build, "plan", None) or {}, column, key)
    if plan is None:
        return None

    runtime = execute(plan, question=question,
                      intent=f"What the population's {column} actually is",
                      certification=ExecutionClass.DYNAMIC)

    counts: list[tuple[str, int]] = []
    for row in (getattr(runtime, "rows", None) or []):
        value = row.get(column)
        members = row.get("members")
        if value is None or not isinstance(members, (int, float)):
            continue
        counts.append((_readable(value), int(members)))

    if not counts or len(counts) > MAX_CLASSES:
        return None
    total = sum(n for _, n in counts)
    if not total or total > MAX_MEMBERS:
        return None

    return Partition(
        column=column, label=_label_of(build, column),
        wanted=_wanted(list((getattr(build, "plan", None) or {})
                            .get("operations") or []), column),
        counts=counts, total=total,
        period=str(getattr(build, "closing", "")
                   or getattr(build, "period", "") or ""),
        grain=str(getattr(build, "grain", "") or ""))


def _key_of(build: Any) -> str:
    """The column that identifies one member of the population."""
    grain = str(getattr(build, "grain", "") or "")
    return {"customer": "customer_id", "facility": "account_id",
            "borrower": "customer_id"}.get(grain, "customer_id")


def _label_of(build: Any, column: str) -> str:
    for match in (getattr(build, "matches", None) or []):
        if str(getattr(match, "field", "")) == column:
            concept = getattr(match, "concept", None)
            label = str(getattr(concept, "label", "") or "")
            if label:
                return label
    return column.replace("_", " ")


def _readable(value: Any) -> str:
    """A governed value as it is said out loud.

    An IFRS 9 stage stored as 1 is "Stage 1" in every sentence anybody writes
    about it, and "1" in a sentence about stages reads as a count.
    """
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


__all__ = ["MAX_CLASSES", "MAX_MEMBERS", "Partition", "classifying", "explain",
           "probe_plan"]
