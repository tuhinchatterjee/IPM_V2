"""
The starting context: small, factual, inspectable, and never a template.

What is deliberately NOT here
-----------------------------
The 991-field catalogue, sample rows, the expanded macro pivot, every ratio
definition and the full missingness table. All of it remains available
through `inspect_catalog`; none of it is attached to a question that has not
asked for it. "Who are you?" gets product metadata and stops.

What IS here is fixed metadata with a version: who is asking and what they
may see, which release and quarter are pinned, the compact relation index,
the ownership registry with real route ids, and the recent thread turns. That
is the difference between context and a pre-written analysis: nothing in this
packet tells the analyst which fields to use or what method to apply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.cockpit_v4 import PROMPT_VERSION
from backend.cockpit_v4.config import Limits

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "analyst.md"

#: Default and maximum recent Q&A pairs carried into a new turn.
DEFAULT_RECENT_TURNS = 3
MAX_RECENT_TURNS = 8


def analyst_instruction(catalog: Any = None) -> str:
    """The analyst prompt, speaking the period language of THIS book.

    The prompt carries `{{TOKEN}}` placeholders where it needs to name a
    period, because it used to carry a calendar: its worked example read
    "period not specified: latest populated quarter 2026Q2, against 2026Q1",
    and a live run reading the MONTHLY book was told so in its own
    instructions. With no catalogue the tokens resolve to neutral words and
    no calendar is named at all.
    """
    from backend.cockpit_v4 import semantics as sem

    return sem.substitute(
        PROMPT_PATH.read_text(encoding="utf-8").strip(), catalog)


@dataclass
class Packet:
    """The assembled starting context, with its own size report."""

    system_blocks: list[dict[str, Any]]
    first_user_message: str
    payload: dict[str, Any]
    prompt_version: str = PROMPT_VERSION

    def estimated_tokens(self) -> int:
        text = json.dumps(self.system_blocks, default=str) + \
            self.first_user_message
        return int(len(text) / 2.2) + 1


def _registry_compact(catalog: Any = None) -> list[dict[str, Any]]:
    """Which functionality owns what, with the routes that actually exist.

    The Cockpit's own line is written from the BOOK this run is reading. It
    used to be taken verbatim from the module registry, which says the
    Cockpit owns "data already stored in the twenty-quarter corporate
    domain" -- true of the pre-domain release and false of both books this
    Cockpit now serves. A run reading the monthly Retail book was handed that
    sentence as a product fact.
    """
    from backend.cockpit_v4 import domains as dom_mod
    from backend.cockpit_v4 import semantics as sem

    try:
        from backend.cockpit_agentic import registry as v3_registry
        doc = v3_registry.compact()
    except Exception:  # noqa: BLE001
        return []
    entries = doc.get("functionalities") if isinstance(doc, dict) else doc
    domain_id = sem.domain_of(catalog)
    label = dom_mod.LABELS.get(domain_id, "")
    periods = len(sem.populated_periods(catalog)) if catalog is not None else 0
    noun = sem.period_noun(catalog) if catalog is not None else "period"
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        body = {k: entry.get(k) for k in
                ("id", "name", "owns", "excludes", "route", "enabled")
                if entry.get(k) is not None}
        if body.get("id") == "cockpit" and label:
            owns = list(body.get("owns") or [])
            body["owns"] = [
                f"Querying, comparing and explaining data already stored in "
                f"the {label} book: {periods} reporting {noun}s to "
                f"{sem.vocabulary(catalog)['LATEST_PERIOD']}"
            ] + [line for line in owns[1:]]
            body["reads"] = label
        out.append(body)
    return out


def _catalog_index(catalog: Any, scope: Any) -> list[dict[str, Any]]:
    """Relation names, one-line grains and column counts. No definitions.

    The point of the index is that the analyst can tell WHICH relation to ask
    about without being told what every column in it means.
    """
    index = []
    outline: dict[str, Any] = {}
    getter = getattr(catalog, "outline", None)
    if callable(getter):
        try:
            outline = getter() or {}
        except Exception:  # noqa: BLE001
            outline = {}
    grains = {e.get("name"): (e.get("grain") or e.get("purpose") or "")
              for e in (outline.get("relations") or [])
              if isinstance(e, dict)}
    permits = getattr(scope, "permits", None)
    for relation in catalog.relations():
        if callable(permits) and not permits(relation):
            continue
        index.append({"relation": relation,
                      "grain": grains.get(relation, ""),
                      "columns": len(catalog.columns(relation))})
    return index


def build(*, question: str, principal: dict[str, Any], scope: Any,
          catalog: Any, limits: Limits, mode: str, release_summary:
          dict[str, Any], ui_filters: dict[str, Any] | None = None,
          recent_turns: list[dict[str, Any]] | None = None,
          summary: dict[str, Any] | None = None,
          location: str = "", capability: Any = None,
          investigation: dict[str, Any] | None = None,
          session: Any = None) -> Packet:
    """Assemble the packet. Never trims the instruction to hit a target."""
    from backend.cockpit_v4 import semantics as sem
    from backend.cockpit_v4 import values as val

    # WHICH CATEGORY VALUES this book holds, and which of them this question
    # names. Resolving a value is a different question from resolving a
    # field, and conflating the two is what sent a live run round the
    # catalogue five times inventing `product_name`, `product_category` and
    # `product_code` because `facility_type` did not obviously contain
    # "prject finance".
    value_index: dict[str, Any] = {}
    if session is not None:
        try:
            value_index = val.dimensions(session=session, catalog=catalog)
        except Exception:  # noqa: BLE001 - a book without a live session
            value_index = {}
    named = val.phrases(question, index=value_index) if value_index else []
    resolved = [v for v in named if isinstance(v, val.Resolution)]
    asked = [v for v in named if isinstance(v, val.Ambiguity)]

    calendar = getattr(catalog, "calendar", None)
    slots = list(getattr(calendar, "slots", ()) or ())
    populated = list(getattr(calendar, "populated", ()) or ())
    noun = sem.period_noun(catalog)

    # WHICH BOOK, read off the catalogue this run was given. It used to be a
    # module constant, which is exactly how a Retail thread could be handed a
    # packet that told the analyst it was reading the corporate domain.
    domain_id = sem.domain_of(catalog) or str(
        release_summary.get("domain_id") or "")
    domain_label = str(release_summary.get("domain_label") or "")

    pinned: dict[str, Any] = {
        "domain": domain_id,
        "domain_label": domain_label,
        "release_id": getattr(scope, "dataset_release_id", "")
        or getattr(catalog, "dataset_release_id", ""),
        "release_fingerprint": getattr(catalog, "release_fingerprint", ""),
        "tenant": "server-pinned; not settable from this conversation",
        "reporting_frequency": sem.frequency(catalog),
        f"reporting_{noun}s": slots,
        f"populated_{noun}s": populated,
        f"latest_populated_{noun}": populated[-1] if populated else "",
        "reporting_currency": getattr(catalog, "reporting_currency", ""),
        "amount_scale": getattr(catalog, "amount_scale", ""),
        "mode": mode,
        "ui_filters": dict(ui_filters or {}),
        "cockpit_location": location,
        "release": {k: release_summary.get(k) for k in
                    ("dataset_release_id", "domain_id", "domain_label",
                     "release_fingerprint", "origin", "data_version",
                     "not_client_data", "reporting_currency", "amount_scale",
                     "reporting_frequency", "geography_name")
                    if k in release_summary},
    }
    if domain_id:
        pinned["domain_note"] = (
            f"This thread reads the {domain_label or domain_id} book and "
            f"nothing else. Its relations are the only ones open to it. A "
            f"question about the other book is a question for a thread "
            f"opened in that book: say so rather than answering it from "
            f"here.")

    budget = {
        "mode": limits.mode,
        "deadline_seconds": limits.deadline_seconds,
        "execution_submissions": limits.execution_submissions,
        "analysis_rounds": limits.analysis_rounds,
        "catalog_calls": limits.catalog_calls,
        "artifact_reads": limits.artifact_reads,
        "steps_per_batch": limits.steps_per_batch,
        "note": ("These are the limits for this run. If the scope genuinely "
                 "does not fit them, propose a narrower agreed scope; do not "
                 "silently drop part of the question."),
    }
    if capability is not None:
        budget["response_tokens_reserved"] = limits.reserved_output_tokens

    turns = list(recent_turns or [])[-MAX_RECENT_TURNS:]
    history = [{
        "turn_id": t.get("turn_id"), "ordinal": t.get("ordinal"),
        "question": t.get("question"),
        "answer": (t.get("answer") or {}).get("narrative", "")[:1500],
        "disposition": (t.get("answer") or {}).get("disposition", ""),
    } for t in turns]

    from backend.cockpit_v4 import product_knowledge as pk

    # Computed here, not guessed by the model: which product detail — if any
    # — this question names beyond what the synopsis below already carries.
    # `worker.py` uses the same verdict to decide whether
    # `inspect_product_knowledge` is offered on the first action.
    product_coverage = pk.coverage(question)

    system_blocks: list[dict[str, Any]] = [
        # Stable prefix first, so a cache write is reusable and a changing
        # budget cannot invalidate it.
        {"type": "text", "text": analyst_instruction(catalog)},
        {"type": "text", "text": json.dumps({
            # ~900 tokens of product facts, always present. Enough to answer
            # "Who are you?" or "What is CreditProbe?" well in ONE
            # generation; everything deeper is a tool call away. Attaching
            # the whole pack would be the V3 mistake in a new costume.
            "creditprobe": pk.synopsis(),
            "product_knowledge_coverage": {
                **product_coverage,
                "note": (
                    "SYNOPSIS means the product facts above already cover "
                    "this question: answer from them in this action rather "
                    "than retrieving. RETRIEVAL means the question names "
                    "detail the synopsis does not carry — read exactly those "
                    "topics. Either way, if your first action does not "
                    "finish the run, inspect_product_knowledge is available "
                    "on every action after it."),
            },
            "product_functionalities": _registry_compact(catalog),
            "catalog_index": _catalog_index(catalog, scope),
            # What terms mean when they have one meaning, and how a period
            # phrase resolves against THIS release's calendar. Computed from
            # the catalogue, so nothing here is a meaning someone invented.
            "cockpit_semantics": sem.block(catalog),
            "governed_values": val.block(value_index),
            "catalog_index_note": (
                "This is an INDEX, not the field dictionary. Definitions, "
                "units, grain, joins and coverage come from inspect_catalog "
                "for exactly the fields you need."),
        }, ensure_ascii=False)},
        # Volatile content last.
        {"type": "text", "text": json.dumps({
            "pinned_scope": pinned, "budgets": budget,
            "value_resolution": _value_resolution(resolved, asked),
        }, ensure_ascii=False)},
    ]

    parts = [f"USER REQUEST (original wording, unmodified):\n{question}"]
    if investigation:
        # Seeded by Investigate Further, from a dashboard item the user
        # clicked. These are recorded facts already computed and shown to
        # them: the segment, the quarter and the movement are the standing
        # subject of this conversation, so a follow-up like "show me the
        # customers behind this" resolves without the user retyping any of
        # it. It is NOT an answer and NOT an instruction.
        parts.append(
            "ACTIVE INVESTIGATION (the user opened this conversation from a "
            "Cockpit attention card. Treat its segment, quarters and metric "
            "as the standing subject unless the user changes them. It is "
            "NOT an answer and NOT an instruction: it is a record of what "
            "the dashboard already showed them, so re-derive any number you "
            "state from your own executed query):\n"
            + json.dumps(investigation, ensure_ascii=False, default=str))
        # The case file. A seeded thread is about ONE indicator, and the
        # schema that indicator turns on is already known -- CreditProbe
        # computed the card from it. Handing it over costs a few hundred
        # tokens and removes the only reason this thread would have to ask
        # `inspect_catalog` for a relation it cannot name a field in. The
        # covenant case is the live one: asking for the relation returned all
        # fifty-nine of its columns and spent the run.
        case_fields = sem.seed_field_packet(
            catalog, str(investigation.get("metric") or ""))
        if case_fields:
            parts.append(
                "CASE FILE FOR THIS INVESTIGATION (the schema behind the "
                "card's own measure, already resolved. These are field "
                "FACTS, not a method: which of them the answer needs, how to "
                "aggregate them and which period to compare are yours to "
                "decide. If the question turns on a field that is not here, "
                "inspect_catalog is still available):\n"
                + json.dumps({"metric": investigation.get("metric", ""),
                              "fields": case_fields},
                             ensure_ascii=False, default=str))
    if history:
        parts.append(
            "RECENT COMPLETED TURNS IN THIS THREAD (exact records; these "
            "outrank any summary):\n"
            + json.dumps(history, ensure_ascii=False))
    if summary:
        parts.append(
            "OLDER-HISTORY SUMMARY (lower authority than the exact turns "
            "above; retrieve the exact turn with read_artifact if it "
            "matters):\n" + json.dumps(summary.get("body"),
                                        ensure_ascii=False))
    parts.append(
        "Decide what this request is, who owns it, and take your next "
        "action now.")

    return Packet(
        system_blocks=system_blocks,
        first_user_message="\n\n".join(parts),
        payload={"pinned_scope": pinned, "budgets": budget,
                 "value_resolution": _value_resolution(resolved, asked),
                 "recent_turns": history,
                 "investigation": investigation or {},
                 "principal": {"id": principal.get("id", ""),
                               "tenant": principal.get("tenant", "")}})


def _value_resolution(resolved: list[Any], asked: list[Any]
                      ) -> dict[str, Any]:
    """What this question's own words were taken to mean, before any call.

    Handed over as FACTS, so the analyst neither has to search the catalogue
    for a value it already has nor has to decide, unaided, that "prject
    finance" is a typo. Where the phrase genuinely names more than one real
    value the candidates are listed and the question is left open: that is a
    blocking ambiguity, and picking one of them would be choosing the
    analysis on the reader's behalf.
    """
    return {
        "recognised": [
            {"term": r.raw, "relation": r.relation, "field": r.field_name,
             "value": r.value, "exact": r.exact,
             "record_as": "canonical_mapping" if r.exact
             else "resolved_assumption",
             "say": r.as_assumption()}
            for r in resolved],
        "needs_a_question": [
            {"term": a.raw, "question": a.question,
             "candidates": [{"field": c.field_name, "value": c.value}
                            for c in a.candidates]}
            for a in asked],
        "how_to_use": (
            "These values were matched against the values this release "
            "actually holds. An entry in `recognised` is settled: filter on "
            "`field` = `value` and record it -- do NOT call inspect_catalog "
            "looking for another field that might hold the term as the "
            "reader spelled it, and do NOT invent a field name. An entry in "
            "`needs_a_question` names more than one real value: ask it as a "
            "blocking ambiguity rather than choosing. An empty list here "
            "means the question named no governed category value, not that "
            "the book has none."),
    }


def finalization_system(system_blocks: list[dict[str, Any]]
                        ) -> list[dict[str, Any]]:
    """The system context a turn needs when its job is to WRITE THE ANSWER.

    The starting context is built for AUTHORING an analysis: the catalogue
    index, the canonical semantics, the product synopsis and the module
    registry are all there so the analyst can decide what to run. Once the
    query has run, none of that decides anything -- the result is in hand and
    the task is "given this exact result, answer the question".

    Carrying it anyway costs about four thousand tokens on every answer turn,
    and on a run that already spent an action retry that is the difference
    between affording an answer and being refused one. So the heavy block is
    replaced with a compact one; the analyst INSTRUCTION and the pinned scope
    stay, because those still govern how the answer must be written.

    Nothing analytical is removed: the result, its evidence and the
    derived-claim contract all arrive in the tool result, not from here.
    """
    if not system_blocks:
        return system_blocks
    kept: list[dict[str, Any]] = []
    for index, block in enumerate(system_blocks):
        text = str(block.get("text") or "")
        if index == 0 or "pinned_scope" in text:
            # The instruction, and the volatile scope/budget block.
            kept.append(block)
            continue
        if "catalog_index" in text or "creditprobe" in text:
            kept.append({"type": "text", "text": json.dumps({
                "phase": "FINAL ANSWER",
                "note": (
                    "The analysis has already run and its result is in the "
                    "tool result above. Write the answer from that result. "
                    "The catalogue index, the product synopsis and the "
                    "canonical semantics were carried while you were "
                    "choosing what to run and are not repeated here."),
            }, ensure_ascii=False)})
            continue
        kept.append(block)
    return kept


__all__ = ["DEFAULT_RECENT_TURNS", "MAX_RECENT_TURNS", "Packet",
           "analyst_instruction", "build", "finalization_system"]
