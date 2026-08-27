"""
Answering the questions that are not calculations.

"What data do you have about borrower ratings?" and "How is ratings connected to
IFRS 9?" are not analyses. They were being scored against credit-risk intents
and answered with portfolio statistics, which is how a question about the
catalogue came back as a Stage 2 distribution.

Each handler here answers from governed metadata, returns a structured result
rather than prose, and produces a Trace that says what it actually consulted. No
handler in this module reads a row of data, and none of them fabricates a
mathematical query for a question that never ran one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import capability as cap
from backend.orchestration.context import GovernedContext
from backend.trace.model import NodeType, TraceGraph, TraceNode

logger = logging.getLogger(__name__)


@dataclass
class HandlerResult:
    """What a non-analytical capability returns.

    Shaped like an engine result where it can be — `rows`, `columns`, `values`
    — because the answer surface renders one thing, and a second shape means a
    second renderer that will drift.
    """

    answer: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    #: Structured detail the answer panel renders in its own block.
    detail: dict[str, Any] = field(default_factory=dict)
    graph: TraceGraph | None = None
    follow_ups: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer, "rows": self.rows, "columns": self.columns,
            "values": self.values, "detail": self.detail,
            "follow_ups": self.follow_ups, "warnings": self.warnings,
        }


# ------------------------------------------------------------------ tracing


def _graph(question: str, reading: cap.Reading, *,
           consulted: str, detail: dict[str, Any]) -> TraceGraph:
    """The Trace for a metadata answer.

    Deliberately short and deliberately honest: question, how it was read, what
    was consulted, what came back. No SQL node, no engine node, no mathematical
    query — because none of those ran, and inventing one so the picture looks
    full would make every other Trace less believable.
    """
    graph = TraceGraph()
    graph.add_node(TraceNode(
        id="question", type=NodeType.USER_PROMPT, label="Question asked",
        config={"question": question}))

    intent = graph.add_node(TraceNode(
        id="intent", type=NodeType.CAPABILITY,
        label=f"Read as: {reading.label}",
        config={
            "intent": reading.intent, "intent_label": reading.label,
            "objective": reading.objective,
            "concepts": list(reading.concepts),
            "entities": [dict(e) for e in reading.entities],
            "datasets": list(reading.datasets),
            "confidence": round(reading.confidence, 3),
            "reasoning": reading.reasoning,
            "read_by": reading.source,
            "model": reading.model,
            "computation_required": False,
            "rule": ("This request was answered from the governed catalogue. "
                     "No analytical engine ran and no figure was computed."),
        }))
    intent.mark_ok()
    graph.connect("question", "intent")

    source = graph.add_node(TraceNode(
        id="catalogue", type=NodeType.GOVERNED_METADATA,
        label=consulted, config=detail))
    source.mark_ok(rows_out=detail.get("count"))
    graph.connect("intent", "catalogue")

    answer = graph.add_node(TraceNode(
        id="result", type=NodeType.RESULT, label="Answer",
        config={"from": "governed metadata"}))
    answer.mark_ok(rows_out=detail.get("count"))
    graph.connect("catalogue", "result")
    graph.compute_hashes()
    return graph


def _relevant(reading: cap.Reading, context: GovernedContext,
              question: str) -> list[Any]:
    """The datasets a metadata question is about, most likely first.

    Named ones first, then the retrieval order — which already scores the
    question against every dataset's purpose, grain, field names and
    authoritative role, and which `retrieve` now guarantees includes any dataset
    the question names.

    An earlier version re-sorted this by word overlap with the dataset's name.
    It looked more precise and was less accurate: "borrower ratings" overlaps
    "Borrower Financials & External Ratings" on two words and the annual rating
    history on one, so the reference table won and the eight years of rating
    history the question was about came second.
    """
    named = [d for d in context.datasets if d.name in reading.datasets]
    return named or list(context.datasets)


#: How many datasets a discovery answer describes. The primary and enough
#: neighbours to see the shape of what is held; the rest are counted, not
#: listed, because a list of twenty is a list nobody reads.
MAX_DISCOVERED = 6


def _rows_in(name: str) -> int:
    """How many governed rows this dataset holds.

    Counted in DuckDB from the Parquet footers, so it costs milliseconds. It is
    here because "we have a ratings dataset" and "we have 32,800 rows of
    ratings" are different answers, and only the second one tells a credit
    officer whether it is worth asking about.
    """
    try:
        from backend.data_access import get_data_source

        return int(get_data_source().row_count(name))
    except Exception as e:  # noqa: BLE001 - a size is not worth losing an answer
        logger.debug("No row count for %s: %s", name, e)
        return 0


def _catalogue_row(dataset: Any) -> dict[str, Any]:
    """One dataset, described the way somebody deciding whether to use it needs.

    Everything here answers a question a data steward or a credit officer
    actually asks before trusting a source: how much of it is there, how far
    back does it go, who says it is right, and is it real client data or the
    demonstration book.
    """
    return {
        "business_name": dataset.business_name,
        "dataset": dataset.name,
        "domain": dataset.domain,
        "grain": dataset.grain,
        "rows": _rows_in(dataset.name),
        "fields": len(dataset.fields),
        "periods": dataset.period_count,
        "from": dataset.periods[0] if dataset.periods else "",
        "to": dataset.latest_period,
        "origin": dataset.origin,
        "authoritative_for": ", ".join(dataset.authoritative_for),
        "state": ("Demonstration data" if dataset.is_synthetic
                  else "Client data"),
    }


_DISCOVERY_COLUMNS = [
    {"name": "business_name", "label": "Dataset", "semantic": "text"},
    {"name": "dataset", "label": "Technical id", "semantic": "text"},
    {"name": "domain", "label": "Domain", "semantic": "text"},
    {"name": "grain", "label": "One row per", "semantic": "text"},
    {"name": "rows", "label": "Rows", "semantic": "count", "decimals": 0,
     "align": "right"},
    {"name": "fields", "label": "Fields", "semantic": "count", "decimals": 0,
     "align": "right"},
    {"name": "periods", "label": "Periods", "semantic": "count", "decimals": 0,
     "align": "right"},
    {"name": "from", "label": "First period", "semantic": "period"},
    {"name": "to", "label": "Latest period", "semantic": "period"},
    {"name": "origin", "label": "Origin", "semantic": "text"},
    {"name": "authoritative_for", "label": "Authoritative for",
     "semantic": "text"},
    {"name": "state", "label": "State", "semantic": "text"},
]


def data_discovery(question: str, reading: cap.Reading,
                   context: GovernedContext) -> HandlerResult:
    """What CreditProbe holds on a subject.

    One dataset is the answer and the others are context. Presenting all six as
    equal matches is what made an IFRS 9 question look like it could be
    answered from six places, when five of them were merely adjacent.
    """
    datasets = _relevant(reading, context, question)[:MAX_DISCOVERED]
    if not datasets:
        return HandlerResult(
            answer=("Nothing in the governed catalogue matches that. The "
                    "catalogue holds "
                    f"{len(context.other_datasets)} datasets across "
                    f"{len(context.domains)} domains."),
            graph=_graph(question, reading, consulted="Data Builder catalogue",
                         detail={"count": 0}))

    rows = [_catalogue_row(d) for d in datasets]
    lead, related = rows[0], rows[1:]

    span = (f", {lead['periods']} periods from {lead['from']} to {lead['to']}"
            if lead["periods"] > 1 else
            (f" at {lead['to']}" if lead["to"] else ""))
    size = f"{lead['rows']:,} rows" if lead["rows"] else "no rows yet"
    answer = (
        f"{datasets[0].business_name} ({lead['dataset']}) is the governed "
        f"source for that: {size}, {lead['fields']} fields, "
        f"{str(lead['grain']).rstrip('.').lower()}{span}."
    )
    if lead["authoritative_for"]:
        answer += (f" It is the authoritative source for "
                   f"{lead['authoritative_for']}.")
    if related:
        answer += (f" {len(related)} further governed "
                   f"{'dataset is' if len(related) == 1 else 'datasets are'} "
                   "related.")

    return HandlerResult(
        answer=answer,
        rows=rows,
        columns=list(_DISCOVERY_COLUMNS),
        values={"datasets": len(datasets), "rows_in_primary": lead["rows"]},
        detail={"count": len(datasets),
                # The primary and the rest, kept apart. The surface collapses
                # the second group under "Related governed data" so a reader is
                # not asked to judge six equal-looking candidates.
                "primary": lead,
                "related": related,
                "datasets": [d.to_dict() for d in datasets],
                "domains": context.domains},
        graph=_graph(question, reading, consulted="Data Builder catalogue",
                     detail={"count": len(datasets),
                             "primary": lead["dataset"],
                             "datasets": [d.name for d in datasets],
                             "domains": sorted({d.domain for d in datasets})}),
        follow_ups=[
            f"What fields are in {lead['dataset']}?",
            f"Open {lead['dataset']} at {lead['to']}." if lead["to"]
            else f"Open {lead['dataset']}.",
            f"How is {lead['dataset']} connected to the facility book?",
        ],
    )


# ------------------------------------------------------ what a field means


#: Field-name heads too generic to be a filter on their own.
#:
#: `data_origin` has the head `data`, and every question about a dataset says
#: "data" — so "what fields are in the ratings data?" matched `data_origin` in
#: four datasets and answered with four copies of one governed marker column.
_WEAK_HEAD = frozenset({
    "data", "total", "current", "last", "first", "is", "has", "value",
    "amount", "count", "date", "period", "name", "id", "type", "flag",
    "source", "record", "row", "field", "latest", "as", "of", "the", "new",
})


def _named_fields(lowered: str, datasets: list[Any]) -> list[tuple[Any, dict[str, Any]]]:
    """The fields this question names, by field name or business name.

    Two rules earn their place. Matching is on the whole word *or* on the first
    token of the field name, because "which fields contain PD?" names `pd_12m`
    and a whole-word match finds nothing — the underscore is a word character,
    so `\bpd\b` never fires inside `pd_12m`.

    And a term that is the dataset's OWN name is not a field filter. "What
    fields are in the watchlist data?" names the watchlist dataset and wants all
    of it; reading `watchlist` as a field narrowed a twenty-field answer to two.
    """
    import re

    owned = {w for d in datasets
             for w in re.findall(r"[a-z0-9]+",
                                 f"{d.name} {getattr(d, 'business_name', '')}".lower())}

    hits: list[tuple[Any, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for dataset in datasets:
        for entry in dataset.fields:
            name = str(entry["name"]).lower()
            business = str(entry.get("business_name") or "").lower()
            head = name.split("_", 1)[0]
            candidates = {name, business}
            if len(head) > 1 and head not in owned and head not in _WEAK_HEAD:
                candidates.add(head)
            for candidate in candidates:
                if not candidate or candidate in owned:
                    continue
                if re.search(rf"\b{re.escape(candidate)}\b", lowered):
                    key = (dataset.name, name)
                    if key not in seen:
                        seen.add(key)
                        hits.append((dataset, entry))
                    break
    return hits


def data_dictionary(question: str, reading: cap.Reading,
                    context: GovernedContext) -> HandlerResult:
    """What a field or a term means, and what a dataset carries."""
    import re

    datasets = _relevant(reading, context, question)
    if not datasets:
        return HandlerResult(answer="No governed dataset matches that.",
                             graph=_graph(question, reading,
                                          consulted="Data Dictionary",
                                          detail={"count": 0}))

    lowered = (question or "").lower()

    # "What fields are in the watchlist data?" asks for a LIST. "What does
    # watchlist mean?" asks for a definition. Both mention a field name, and
    # answering the first with the second — one row defining `watchlist` — is a
    # true sentence about the wrong question.
    wants_the_list = bool(re.search(
        r"\bwhat (?:fields?|columns?)\b|\bwhich (?:fields?|columns?)\b"
        r"|\bfields? (?:are|is) (?:available|in|there)\b"
        r"|\blist (?:the )?(?:fields?|columns?)\b", lowered))

    hits = _named_fields(lowered, datasets)

    if wants_the_list and hits:
        # "Which fields contain PD, LGD and ECL?" wants a list, but of the
        # three fields it named — not of all twenty-nine. Returning everything
        # is a true answer to "what fields are there", which is a different
        # question and one the user did not ask.
        dataset = hits[0][0]
        rows = [{"dataset": d.name, "field": e["name"],
                 "business_name": e["business_name"], "unit": e.get("unit") or "",
                 "type": e["type"], "definition": e["definition"]}
                for d, e in hits[:40]]
        answer = (f"{len(rows)} field"
                  + ("s" if len(rows) != 1 else "")
                  + f" in {dataset.business_name} ({dataset.name}) match that: "
                  + ", ".join(f"{e['business_name']} ({e['name']})"
                              for _, e in hits[:8])
                  + ("…" if len(hits) > 8 else "") + ".")
    elif hits and not wants_the_list:
        dataset, entry = hits[0]
        unit = f" Measured in {entry['unit']}." if entry.get("unit") else ""
        answer = (f"{entry['business_name']} ({dataset.name}.{entry['name']}) "
                  f"— {entry['definition']}{unit}")
        rows = [{"dataset": d.name, "field": e["name"],
                 "business_name": e["business_name"], "unit": e.get("unit") or "",
                 "type": e["type"], "definition": e["definition"]}
                for d, e in hits[:20]]
    else:
        dataset = datasets[0]
        answer = (f"{dataset.business_name} ({dataset.name}) carries "
                  f"{len(dataset.fields)} governed fields at "
                  f"{dataset.grain.rstrip('.').lower()}.")
        rows = [{"dataset": dataset.name, "field": e["name"],
                 "business_name": e["business_name"], "unit": e.get("unit") or "",
                 "type": e["type"], "definition": e["definition"]}
                for e in dataset.fields]

    return HandlerResult(
        answer=answer, rows=rows,
        columns=[{"name": k, "type": "text"} for k in (rows[0] if rows else {})],
        values={"fields": len(rows)},
        detail={"count": len(rows), "dataset": datasets[0].name},
        graph=_graph(question, reading, consulted="Data Dictionary",
                     detail={"count": len(rows),
                             "dataset": datasets[0].name,
                             "fields": [r["field"] for r in rows[:20]]}),
        follow_ups=[f"What data do you have about {datasets[0].business_name}?"],
    )


# --------------------------------------------------------- coverage, history


def data_quality(question: str, reading: cap.Reading,
                 context: GovernedContext) -> HandlerResult:
    """How much history there is, and how complete it is.

    The lead dataset is the best-matching one that ACTUALLY HAS a history. A
    coverage question is asking how far back the data goes, so leading with a
    reference table that matches the words and carries no periods at all —
    "rating_transitions is not partitioned by reporting period" in answer to
    "how many years of ratings history do you have?" — is a true sentence about
    the wrong table.
    """
    datasets = _relevant(reading, context, question)[:5]
    datasets = sorted(datasets, key=lambda d: (d.period_count == 0,))
    if not datasets:
        return HandlerResult(answer="No governed dataset matches that.",
                             graph=_graph(question, reading,
                                          consulted="Data Builder coverage",
                                          detail={"count": 0}))

    rows = [{"dataset": d.name, "business_name": d.business_name,
             "periods": d.period_count,
             "from": d.periods[0] if d.periods else "",
             "to": d.latest_period,
             "grain": d.grain, "fields": len(d.fields),
             "version": d.version, "origin": d.origin}
            for d in datasets]

    lead = datasets[0]
    if lead.period_count > 1:
        answer = (f"{lead.business_name} ({lead.name}) has "
                  f"{lead.period_count} published periods, from "
                  f"{lead.periods[0]} to {lead.latest_period}.")
    elif lead.period_count == 1:
        answer = (f"{lead.business_name} ({lead.name}) has one published "
                  f"period, {lead.latest_period}.")
    else:
        answer = (f"{lead.business_name} ({lead.name}) is not partitioned by "
                  "reporting period — it is a reference table.")

    return HandlerResult(
        answer=answer, rows=rows,
        columns=[{"name": k, "type": "text"} for k in rows[0]],
        values={"periods": lead.period_count},
        detail={"count": len(rows), "periods": list(lead.periods)},
        graph=_graph(question, reading, consulted="Data Builder coverage",
                     detail={"count": len(rows), "dataset": lead.name,
                             "periods": list(lead.periods)}),
        follow_ups=[f"What fields are in {lead.name}?"],
    )


# ------------------------------------------------------- looking at a table


def data_inspection(question: str, reading: cap.Reading,
                    context: GovernedContext) -> HandlerResult:
    """What one dataset is, without reading its rows.

    Deliberately does not return sample rows. Governed data is read through the
    Data Access Layer with a period and a field list, and a "show me some rows"
    shortcut that bypasses that is exactly the hole this architecture closes.
    The answer points at Data Builder, which reads it properly.
    """
    datasets = _relevant(reading, context, question)
    if not datasets:
        return HandlerResult(answer="No governed dataset matches that.",
                             graph=_graph(question, reading,
                                          consulted="Data Builder catalogue",
                                          detail={"count": 0}))
    dataset = datasets[0]
    answer = (
        f"{dataset.business_name} ({dataset.name}) — {dataset.purpose} "
        f"One row is {dataset.grain.rstrip('.').lower()}. "
        f"{len(dataset.fields)} governed fields"
        + (f", {dataset.period_count} periods to {dataset.latest_period}."
           if dataset.period_count else ".")
        + " Open it in Data Builder to browse the rows themselves.")
    rows = [{"field": e["name"], "business_name": e["business_name"],
             "unit": e.get("unit") or "", "type": e["type"]}
            for e in dataset.fields]
    return HandlerResult(
        answer=answer, rows=rows,
        columns=[{"name": k, "type": "text"} for k in (rows[0] if rows else {})],
        detail={"count": len(rows), "dataset": dataset.name,
                "open_in_data_builder": f"/data-builder/dataset/{dataset.name}"},
        graph=_graph(question, reading, consulted="Data Builder catalogue",
                     detail={"count": len(rows), "dataset": dataset.name}),
    )


# ------------------------------------------------------ how things connect


def data_relationship(question: str, reading: cap.Reading,
                      context: GovernedContext) -> HandlerResult:
    """How two governed datasets join, from the declared relationship graph.

    Answers with the path a real analysis would walk — the same graph, the same
    resolver — rather than describing one in prose. If the planner would join
    them one way, this says that way.
    """
    from backend.runtime.joins import build_graph, resolve

    wanted = _mentioned(question, reading, context)
    if len(wanted) < 2:
        return _relationship_overview(question, reading, context, wanted)

    left, right = wanted[0], wanted[1]
    rows_from = [{"id": r.relationship_id, "from": f"{r.from_dataset}.{r.from_field}",
                  "to": f"{r.to_dataset}.{r.to_field}",
                  "cardinality": r.cardinality, "join": r.join_policy,
                  "periods": r.temporal_rule, "means": r.semantic,
                  "version": r.version, "match_rate": r.match_rate}
                 for r in context.relationships]

    graph = build_graph([
        {"id": r.relationship_id, "from_dataset": r.from_dataset,
         "from_field": r.from_field, "to_dataset": r.to_dataset,
         "to_field": r.to_field, "cardinality": r.cardinality,
         "join_policy": r.join_policy, "temporal_rule": r.temporal_rule,
         "semantic": r.semantic, "version": r.version,
         "match_rate": r.match_rate, "confidence": 1.0,
         "validated_at": True if r.match_rate is not None else None}
        for r in context.relationships])
    resolution = resolve(graph, base=left.name, targets=[right.name])

    left_periods = (f"{left.period_count} periods to {left.latest_period}"
                    if left.period_count else "no reporting period")
    right_periods = (f"{right.period_count} periods to {right.latest_period}"
                     if right.period_count else "no reporting period")

    if not resolution.paths:
        answer = (
            f"No active governed relationship connects {left.name} to "
            f"{right.name}. A data steward can declare one in Data Builder; "
            "until then CreditProbe will not join them.")
        detail = {"count": 0, "left": left.name, "right": right.name}
        return HandlerResult(
            answer=answer, rows=rows_from,
            columns=[{"name": k, "type": "text"} for k in (rows_from[0] if rows_from else {})],
            detail=detail,
            graph=_graph(question, reading,
                         consulted="Governed relationship graph", detail=detail),
            warnings=[f"{left.name} and {right.name} are not joined."])

    path = resolution.paths[0]
    hops = " → ".join([path.edges[0].left] + [e.right for e in path.edges])
    keys = "; ".join(f"{e.left}.{e.left_field} = {e.right}.{e.right_field}"
                     for e in path.edges)
    asof = any(e.is_asof for e in path.edges)

    alignment = (
        f"{right.business_name} is reported at a different frequency, so "
        "CreditProbe joins it as-of: the latest observation dated on or before "
        "the reporting date, never after it."
        if asof else
        "Both sides are read at the same reporting period.")

    answer = (
        f"{left.business_name} joins to {right.business_name} through "
        f"{hops}, on {keys}. "
        f"{left.name} is {left.grain.rstrip('.').lower()} with {left_periods}; "
        f"{right.name} is {right.grain.rstrip('.').lower()} with "
        f"{right_periods}. {alignment}")

    rows = [{
        "step": i + 1,
        "from": f"{e.left}.{e.left_field}",
        "to": f"{e.right}.{e.right_field}",
        "cardinality": e.cardinality.replace("_", " "),
        "join": e.join_policy,
        "periods": e.temporal_rule.replace("_", " "),
        "match_rate": (f"{e.match_rate * 100:.1f}%"
                       if e.match_rate is not None else "not measured"),
        "version": e.version,
        "means": e.semantic,
    } for i, e in enumerate(path.edges)]

    detail = {
        "count": len(rows), "left": left.name, "right": right.name,
        "path": [e.to_dict() for e in path.edges],
        "hops": path.hops, "needs_asof": asof,
        "multiplies": path.multiplies,
        "left_grain": left.grain, "right_grain": right.grain,
        "left_periods": list(left.periods), "right_periods": list(right.periods),
        "warnings": list(resolution.warnings),
    }
    return HandlerResult(
        answer=answer, rows=rows,
        columns=[{"name": k, "type": "text"} for k in rows[0]],
        values={"hops": path.hops},
        detail=detail,
        graph=_relationship_graph(question, reading, left, right, path, detail),
        warnings=list(resolution.warnings),
        follow_ups=[
            f"What fields are in {right.name}?",
            f"What data do you have about {right.business_name}?",
        ],
    )


def _relationship_overview(question: str, reading: cap.Reading,
                           context: GovernedContext,
                           wanted: list[Any]) -> HandlerResult:
    """Only one dataset was named — say what it joins to."""
    if not wanted:
        return HandlerResult(
            answer=("Name two datasets and CreditProbe will show the governed "
                    "path between them."),
            graph=_graph(question, reading,
                         consulted="Governed relationship graph",
                         detail={"count": 0}))
    subject = wanted[0]
    edges = [r for r in context.relationships
             if subject.name in (r.from_dataset, r.to_dataset)]
    rows = [{"from": f"{r.from_dataset}.{r.from_field}",
             "to": f"{r.to_dataset}.{r.to_field}",
             "cardinality": r.cardinality.replace("_", " "),
             "periods": r.temporal_rule.replace("_", " "),
             "means": r.semantic} for r in edges]
    others = sorted({r.to_dataset if r.from_dataset == subject.name
                     else r.from_dataset for r in edges})
    answer = (
        f"{subject.business_name} ({subject.name}) is joined to "
        f"{len(others)} governed "
        f"{'dataset' if len(others) == 1 else 'datasets'}: "
        f"{', '.join(others)}." if others else
        f"{subject.business_name} ({subject.name}) has no declared "
        "relationships, so nothing can carry an attribute onto it.")
    detail = {"count": len(rows), "dataset": subject.name, "joins_to": others}
    return HandlerResult(
        answer=answer, rows=rows,
        columns=[{"name": k, "type": "text"} for k in (rows[0] if rows else {})],
        detail=detail,
        graph=_graph(question, reading,
                     consulted="Governed relationship graph", detail=detail))


def _relationship_graph(question: str, reading: cap.Reading, left: Any,
                        right: Any, path: Any,
                        detail: dict[str, Any]) -> TraceGraph:
    """A Trace shaped like the join it describes: dataset → relationship →
    dataset, with no calculation node anywhere."""
    graph = TraceGraph()
    graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                             label="Question asked",
                             config={"question": question}))
    intent = graph.add_node(TraceNode(
        id="intent", type=NodeType.CAPABILITY,
        label=f"Read as: {reading.label}",
        config={"intent": reading.intent, "intent_label": reading.label,
                "objective": reading.objective, "read_by": reading.source,
                "confidence": round(reading.confidence, 3),
                "computation_required": False,
                "rule": ("Answered from the declared relationship graph. No "
                         "analysis ran and no figure was computed.")}))
    intent.mark_ok()
    graph.connect("question", "intent")

    previous = "intent"
    for side, dataset in (("left", left), ("right", right)):
        node = graph.add_node(TraceNode(
            id=f"dataset_{dataset.name}", type=NodeType.DATASET,
            label=f"{dataset.business_name}",
            config={"dataset": dataset.name, "domain": dataset.domain,
                    "grain": dataset.grain, "periods": list(dataset.periods),
                    "period_count": dataset.period_count,
                    "field_count": len(dataset.fields),
                    "origin": dataset.origin, "side": side,
                    "is_synthetic": dataset.is_synthetic},
            dataset=dataset.name))
        node.mark_ok()
        graph.connect(previous, node.id)

    for index, edge in enumerate(path.edges):
        node = graph.add_node(TraceNode(
            id=f"relationship_{index}", type=NodeType.RELATIONSHIP,
            label=f"{edge.left} → {edge.right}",
            config={"relationship_id": edge.relationship_id,
                    "relationship_name": edge.name,
                    "relationship_version": edge.version,
                    "keys": f"{edge.left}.{edge.left_field} = "
                            f"{edge.right}.{edge.right_field}",
                    "cardinality": edge.cardinality,
                    "join_policy": edge.join_policy,
                    "temporal_rule": edge.temporal_rule,
                    "match_rate": edge.match_rate,
                    "means": edge.semantic}))
        node.mark_ok()
        graph.connect(f"dataset_{left.name}", node.id)
        graph.connect(node.id, f"dataset_{right.name}")

    answer = graph.add_node(TraceNode(
        id="result", type=NodeType.RESULT, label="Governed join path",
        config={"hops": path.hops, "needs_asof": detail.get("needs_asof")}))
    answer.mark_ok(rows_out=len(path.edges))
    graph.connect(f"dataset_{right.name}", "result")
    graph.compute_hashes()
    return graph


def _mentioned(question: str, reading: cap.Reading,
               context: GovernedContext) -> list[Any]:
    """Datasets a relationship question names, in the order it names them.

    Order matters: "how is ratings connected to IFRS 9" should resolve the path
    from ratings, not from whichever happens to sort first.
    """
    import re

    named = [context.dataset(n) for n in reading.datasets]
    named = [d for d in named if d is not None]

    lowered = (question or "").lower()
    positioned: list[tuple[int, Any]] = []
    for dataset in context.datasets:
        aliases = {dataset.name, dataset.name.replace("_", " "),
                   dataset.business_name.lower()}
        aliases |= _ALIASES.get(dataset.name, set())
        best = None
        for alias in aliases:
            if not alias:
                continue
            found = re.search(rf"\b{re.escape(alias.lower())}\b", lowered)
            if found and (best is None or found.start() < best):
                best = found.start()
        if best is not None:
            positioned.append((best, dataset))

    positioned.sort(key=lambda pair: pair[0])
    out: list[Any] = []
    for _, dataset in positioned:
        if dataset not in out:
            out.append(dataset)
    for dataset in named:
        if dataset not in out:
            out.append(dataset)
    return out


#: What people call these datasets when they are not reading the catalogue.
_ALIASES: dict[str, set[str]] = {
    "customer_ratings": {"ratings", "rating", "rating data", "borrower ratings",
                         "internal ratings", "credit ratings", "rating cycle"},
    "ifrs9_staging": {"ifrs 9", "ifrs9", "ifrs-9", "staging", "impairment",
                      "ecl data", "provisioning", "ifrs 9 data"},
    "portfolio_facility": {"facility book", "the book", "portfolio",
                           "facilities", "facility position", "exposures"},
    "borrower_financials": {"financials", "borrower financials", "accounts",
                            "financial statements"},
    "facility_delinquency": {"arrears", "delinquency", "dpd", "past due",
                             "collections"},
    "covenant_tests": {"covenants", "covenant", "covenant tests"},
    "collateral_register": {"collateral", "security"},
    "watchlist_register": {"watchlist", "watch list"},
    "macro_saudi": {"macro", "macroeconomic", "economy", "gdp"},
    "credit_memo_signals": {"credit memos", "memos", "credit files"},
    "rating_transitions": {"transitions", "migration", "transition matrix"},
    "payment_history": {"payments", "payment history"},
}


# --------------------------------------------------------------- methods


def method_discovery(question: str, reading: cap.Reading,
                     context: GovernedContext) -> HandlerResult:
    """Which Analysis Studio methods exist for this subject."""
    methods = context.methods
    if not methods:
        return HandlerResult(
            answer=("No method in Analysis Studio matches that. CreditProbe "
                    "can still compose the analysis dynamically — ask for the "
                    "figure directly."),
            graph=_graph(question, reading, consulted="Analysis Studio",
                         detail={"count": 0}))
    rows = [{"id": m.id, "name": m.name,
             "category": getattr(m.category, "value", m.category),
             "certified": "yes" if m.is_certified else "no",
             "definition": m.definition, "when_to_use": m.when_to_use}
            for m in methods]
    certified = sum(1 for m in methods if m.is_certified)
    answer = (
        f"{len(methods)} {'method' if len(methods) == 1 else 'methods'} match, "
        f"{certified} of them certified. {methods[0].name} is the closest: "
        f"{methods[0].definition}")
    return HandlerResult(
        answer=answer, rows=rows,
        columns=[{"name": k, "type": "text"} for k in rows[0]],
        values={"methods": len(methods)},
        detail={"count": len(methods),
                "methods": [m.to_dict() for m in methods]},
        graph=_graph(question, reading, consulted="Analysis Studio",
                     detail={"count": len(methods),
                             "methods": [m.id for m in methods]}),
        follow_ups=[f"How does {methods[0].name} work?"])


def method_explanation(question: str, reading: cap.Reading,
                       context: GovernedContext) -> HandlerResult:
    """How one method works, from its recorded methodology."""
    if not context.methods:
        return HandlerResult(
            answer=("No method in Analysis Studio matches that."),
            graph=_graph(question, reading, consulted="Analysis Studio",
                         detail={"count": 0}))
    method = context.methods[0]
    try:
        from backend.studio.registry import get_registry

        full = get_registry().get(method.id)
        methodology = full.methodology or method.definition
        limitations = full.limitations
    except Exception:
        methodology, limitations = method.definition, ""

    answer = f"{method.name} — {method.definition}"
    detail = {"count": 1, "method": method.to_dict(),
              "methodology": methodology, "limitations": limitations}
    return HandlerResult(
        answer=answer,
        rows=[{"section": "Methodology", "text": methodology}]
             + ([{"section": "Limitations", "text": limitations}]
                if limitations else [])
             + ([{"section": "When not to use it",
                  "text": method.when_not_to_use}]
                if method.when_not_to_use else []),
        columns=[{"name": "section", "type": "text"},
                 {"name": "text", "type": "text"}],
        detail=detail,
        graph=_graph(question, reading, consulted="Analysis Studio",
                     detail={"count": 1, "method": method.id,
                             "certified": method.is_certified}),
        follow_ups=[f"Run {method.name} on the latest quarter."])


def method_creation(question: str, reading: cap.Reading,
                    context: GovernedContext) -> HandlerResult:
    """Point at the builder rather than pretending to author a method."""
    return HandlerResult(
        answer=("Analysis Studio builds methods. Describe the calculation "
                "there and CreditProbe will compose it, run its validation "
                "pack and keep it as a draft — a method arrives with no "
                "certification until somebody reviews it. You can also ask "
                "the question here and save the answer as a method."),
        detail={"count": 0, "open": "/studio/new"},
        graph=_graph(question, reading, consulted="Analysis Studio",
                     detail={"count": 0}))


def workspace_action(question: str, reading: cap.Reading,
                     context: GovernedContext) -> HandlerResult:
    """Say what CreditProbe can and cannot do to a workspace object.

    It does not act. A chat turn that silently renames a project or moves an
    investigation is a change nobody approved, and the audit trail would show
    the model as the author.
    """
    where = {cap.Capability.PROJECT_ACTION: ("Projects", "/projects"),
             cap.Capability.INVESTIGATION_ACTION: ("Investigations",
                                                   "/investigations"),
             cap.Capability.ANALYSIS_ACTION: ("Analyses", "/analyses")}
    label, href = where.get(reading.intent, ("the workspace", "/"))
    return HandlerResult(
        answer=(f"That is a change to {label} rather than a question about the "
                "portfolio. CreditProbe does not change workspace objects from "
                f"a chat turn — open {label} and make the change there, so the "
                "audit trail records who did it."),
        detail={"count": 0, "open": href},
        graph=_graph(question, reading, consulted="Workspace",
                     detail={"count": 0}))


#: Which handler answers which capability.
HANDLERS = {
    cap.Capability.DATA_DISCOVERY: data_discovery,
    cap.Capability.DATA_DICTIONARY: data_dictionary,
    cap.Capability.DATA_QUALITY: data_quality,
    cap.Capability.DATA_INSPECTION: data_inspection,
    cap.Capability.DATA_RELATIONSHIP: data_relationship,
    cap.Capability.METHOD_DISCOVERY: method_discovery,
    cap.Capability.METHOD_EXPLANATION: method_explanation,
    cap.Capability.METHOD_CREATION: method_creation,
    cap.Capability.PROJECT_ACTION: workspace_action,
    cap.Capability.INVESTIGATION_ACTION: workspace_action,
    cap.Capability.ANALYSIS_ACTION: workspace_action,
}


def handle(question: str, reading: cap.Reading,
           context: GovernedContext) -> HandlerResult | None:
    """Answer a non-analytical request, or None if this one computes."""
    handler = HANDLERS.get(reading.intent)
    if handler is None:
        return None
    return handler(question, reading, context)


__all__ = ["HANDLERS", "HandlerResult", "handle"]
