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
from backend.cockpit_v4 import investigation as inv_mod
from backend.cockpit_v4.config import Limits

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "analyst.md"

#: Default and maximum recent Q&A pairs carried into a new turn.
DEFAULT_RECENT_TURNS = 3
MAX_RECENT_TURNS = 8

#: How many of a clarification's offered choices ride along in history.
#:
#: Bounded because the block is carried on every turn of the rest of the
#: thread. The contract caps the options anyway; this is the belt.
CLARIFICATION_OPTIONS = 6


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
          session: Any = None, analytical: bool = False) -> Packet:
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
    history = []
    for t in turns:
        prior = t.get("answer") or {}
        entry: dict[str, Any] = {
            "turn_id": t.get("turn_id"), "ordinal": t.get("ordinal"),
            "question": t.get("question"),
            "answer": prior.get("narrative", "")[:1500],
            "disposition": prior.get("disposition", ""),
        }
        # A CLARIFICATION IS HALF A CONVERSATION WITHOUT ITS QUESTION.
        #
        # A turn can end by putting one question back to the reader, who
        # answers it by clicking an option -- and what the next turn then
        # receives as its question is the option's TEXT. "Symmetric
        # allocation." Three words, arriving alone.
        #
        # The question those words answer lives in `clarification_question`,
        # and this block carried the narrative and the disposition and not
        # that. So the analyst saw that it had asked SOMETHING, and a short
        # phrase it had to work backwards from. The round trip completed
        # only when the analyst had happened to repeat its question inside
        # the narrative as well, which nothing requires it to do.
        #
        # The options come too. A reply is usually one of them word for
        # word, and seeing the list is what makes that unmistakable rather
        # than probable.
        if entry["disposition"] == "clarification":
            entry["you_asked"] = str(prior.get("clarification_question") or "")
            offered = [str(o) for o
                       in (prior.get("clarification_options") or ())]
            if offered:
                entry["you_offered"] = offered[:CLARIFICATION_OPTIONS]
            entry["note"] = (
                "The question that follows this turn is most likely the "
                "reader ANSWERING it, often one of the offered choices word "
                "for word. Read it that way and carry on with the analysis "
                "rather than asking again. If it plainly asks something "
                "else, it is a new question.")
        history.append(entry)

    from backend.cockpit_v4 import product_knowledge as pk

    # Computed here, not guessed by the model: which product detail — if any
    # — this question names beyond what the synopsis below already carries.
    # `worker.py` uses the same verdict to decide whether
    # `inspect_product_knowledge` is offered on the first action.
    product_coverage = pk.coverage(question)

    # WHAT THIS QUESTION IS ABOUT, decided before the packet is built.
    #
    # An analytical turn does not carry the product pack. It is about five
    # kilobytes describing what CreditProbe IS, on a request that asks what
    # a book DID -- and `inspect_product_knowledge` is already off the tool
    # list for exactly the same reason. Every byte on an action turn is
    # something the model reads before it can decide anything, and the
    # measured action payload for the two questions that failed on the Mac
    # was sixty kilobytes.
    #
    # It is not a capability the run loses: the tool comes back on the
    # second action like any withheld one, and this is the only turn the
    # pack is missing from.
    product_pack: dict[str, Any] = {} if analytical else {
        # ~900 tokens of product facts. Enough to answer "Who are you?" or
        # "What is CreditProbe?" well in ONE generation; everything deeper
        # is a tool call away. Attaching the whole pack would be the V3
        # mistake in a new costume.
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
    }

    # The seeded packet first, because readiness depends on it: a thread
    # opened from a card already holds the relation, the segment value and
    # both periods, and a run that does not know that goes looking for them.
    seed_packet: dict[str, Any] = {}
    if investigation:
        seed_packet = inv_mod.analysis_packet(
            catalog=catalog, session=session, seed=investigation)
    _readiness = sem.readiness(
        catalog, question, seed_packet=seed_packet,
        value_resolution=_value_resolution(resolved, asked))

    system_blocks: list[dict[str, Any]] = [
        # Stable prefix first, so a cache write is reusable and a changing
        # budget cannot invalidate it.
        {"type": "text", "text": analyst_instruction(catalog)},
        {"type": "text", "text": json.dumps({
            **product_pack,
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
            # §7, §8. Whether the metadata for THIS question is already
            # here, decided by the server before any model call. It names
            # no method: see `semantics.readiness`.
            "analysis_readiness": _readiness,
        }, ensure_ascii=False)},
    ]

    parts = [f"USER REQUEST (original wording, unmodified):\n{question}"]
    analysis: dict[str, Any] = {}
    if investigation:
        analysis = seed_packet
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
        # §19-§21. The ANALYSIS PACKET. A seeded thread is about ONE finding
        # that CreditProbe itself computed, so the relation it came from, the
        # column the segment lives in, the governed value of that segment,
        # the measure's own columns and the two periods are all already
        # known. Handing them over costs a few hundred tokens and removes
        # every reason this thread would have to search for them.
        #
        # The live failure: a Construction card opened a thread that read the
        # catalogue, read it again, read product knowledge, and died with
        # CALL_LIMIT without answering anything. Not one of those calls could
        # have returned something it had not been given.
        if analysis:
            parts.append(
                "ANALYSIS PACKET FOR THIS INVESTIGATION (everything behind "
                "the card, already resolved. These are FACTS, not a method: "
                "which columns the answer needs, how to aggregate them and "
                "which periods to compare are yours to decide. You should "
                "not need inspect_catalog for this conversation; it remains "
                "available if the question turns on a column that is not "
                "here):\n"
                + json.dumps(analysis, ensure_ascii=False, default=str))
        # The older case file: the schema behind the card's own measure,
        # kept for indicators the analysis packet has no relation for.
        case_fields = ([] if analysis else sem.seed_field_packet(
            catalog, str(investigation.get("metric") or "")))
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
                 # The action state machine reads this. It is the same
                 # object the analyst is shown, so the state a run is put
                 # into is the state it was told it is in.
                 "analysis_readiness": _readiness,
                 "value_resolution": _value_resolution(resolved, asked),
                 "recent_turns": history,
                 "investigation": investigation or {},
                 "investigation_packet": analysis,
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


#: How to present the result, carried only on a turn that writes an answer.
#:
#: THE SHAPE OF AN ANALYTICAL ANSWER.
#:
#: `analyst.md` writes four worked shapes under "Writing the answer" and
#: every one of them is a PRODUCT question -- who are you, what does Early
#: Warning do, what is TAC. The shape it never describes is the one this
#: product exists for: the answer written with a result set in hand. The
#: "Analysis" section beside it is entirely about how to RUN the query.
#:
#: So the one act the whole system is built around was the one act nobody
#: had said what good looks like for, and the default an analyst falls back
#: to without it is narrating the table -- which is the one thing the reader
#: already has.
#:
#: This is standards, not a template. It says what an answer is held to, and
#: `length_follows_the_question` is in it because a checklist read as a form
#: to fill produces exactly the padding it is meant to prevent.
#:
#: Here rather than in `analyst.md` for the same reason the chart policy is:
#: it is only true on the turn that has the rows, and the instruction file is
#: carried on every action attempt and measured against a bound.
ANALYTICAL_ANSWER: dict[str, Any] = {
    "phase": "THE ANSWER",
    "who_is_reading": (
        "A senior credit officer with your table in front of them. They can "
        "read rows. What they cannot get from the rows is what you make of "
        "them."),
    "lead_with_the_answer": (
        "The first sentence answers the question that was asked and carries "
        "the figure. Not a restatement of the question, not what you ran, "
        "not what came back."),
    "a_figure_needs_something_beside_it": (
        "A number on its own leaves the reader to size it. Put it against "
        "something the RESULT already holds -- the prior period, the rest "
        "of the book, the other segments, a threshold the policy names. If "
        "the result holds no comparison, give the figure and say so. Do not "
        "reach for one that was not computed."),
    "say_where_it_sits": (
        "Concentration is the sentence a credit officer acts on: how much "
        "of the total sits in how few names, sectors or buckets, and "
        "whether a movement is broad or is one exposure. The rows will "
        "say. The reader should not have to add them up."),
    "what_moved_it": (
        "Where the result shows direction, name the driver and how much of "
        "the change it accounts for. Where it does not, say that this cut "
        "shows the movement and not its cause."),
    "what_it_means_for_the_book": (
        "A sentence or two on the consequence, and what is worth doing "
        "next -- a name to look at, a limit to check, an analysis to run. "
        "Only what these rows support."),
    "what_this_does_not_establish": (
        "Say it once, plainly, where it matters: the grain, the "
        "missingness, the vintage, what this cut cannot see. A limitation "
        "stated once is analysis. One hedged onto every clause is noise."),
    "do_not_narrate_the_table": (
        "The table is published beside you. Walking its rows in prose is "
        "the commonest way an answer gets longer without getting better. "
        "Cite the figures that carry the argument; leave the rest to the "
        "table."),
    "do_not_narrate_the_process": (
        "The reader has the process panel and the governance trace. What "
        "you ran, how many rows came back and which tool you called are "
        "not the answer."),
    "length_follows_the_question": (
        "A one-number question gets a short answer. Padding a direct answer "
        "so it looks thorough is how a careful answer comes to read as "
        "automated."),
}


#: Four live answers came back as tables and nothing else, one of them to a
#: reader who had asked for a line chart by name. The instruction file did
#: not contain the word "chart", so nothing told the analyst that the form
#: was part of the answer or that the request was there to be honoured.
PRESENTATION: dict[str, Any] = {
    "phase": "PRESENTATION",
    "charts_are_part_of_the_answer": (
        "A result that moves, ranks, splits a total or spreads across a "
        "range reads better drawn than listed. Send `charts` with the "
        "answer, not instead of the table."),
    # THE OTHER HALF OF THE SAME INSTRUCTION. The block above was written
    # after four answers arrived with no chart, and it says "send charts"
    # six ways. Nothing said when NOT to, so the only failure it could
    # cause is the opposite one: a bar chart with a single bar under a
    # sentence that already gave the number, which reads as padding and
    # makes a careful answer look automated.
    "a_chart_is_not_always_the_answer": (
        "Not every result has a shape. One figure has none: state it and "
        "send no chart. Two or three values a reader compares at a glance "
        "are already clearer in the table. Draw the result when the FORM "
        "shows what the rows would make the reader work out -- a ranking, "
        "a movement, a concentration, a migration, a spread -- and leave "
        "it out when it would only repeat a small table."),
    "say_why_in_one_line": (
        "Put that reason in `why_this_chart`: the reader's question this "
        "form answers. It is published with the chart and appears in the "
        "governance record. A chart you cannot justify in one line is "
        "usually a chart the answer does not need."),
    "an_explicit_request_wins": (
        "If the reader named a form -- \"give me a line chart\" -- send that "
        "`kind`. Their words are in the conversation above."),
    "otherwise_choose_by_shape": (
        "A sequence draws as line, step_line, area or waterfall; a ranking "
        "as bar or grouped_bar; a composition as pie, donut, stacked_bar or "
        "stacked_bar_100; a spread as histogram, box, scatter or bubble; a "
        "from-to grid as heatmap; a rate beside a volume as combo. The "
        "`kind` enum carries what each one means."),
    "a_bar_chart_states_an_order": (
        "bar and grouped_bar are read top-down as a ranking, so when the "
        "answer says \"the largest\" the result behind them must be ORDERED "
        "by the measure being charted. A series that moves up and down is a "
        "sequence, not a ranking: draw it as a line."),
    "several_small_charts": (
        "Prefer several small charts to one crowded one. A trend \"for each "
        "product\" is one chart per product, each titled for its product, "
        "rather than every series fighting over one axis. Use the chart "
        "allowance the budget gives you."),
    "a_correction_replaces_everything": (
        "If this answer comes back for correction, send the charts again "
        "with the corrected answer. A chart left out of a correction is a "
        "chart the reader never sees."),
}


def finalization_system(system_blocks: list[dict[str, Any]], *,
                        domain_id: str = "",
                        question: str = "") -> list[dict[str, Any]]:
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

    HOW TO PRESENT the result is added here rather than in `analyst.md`,
    because it is only true on this turn. The action turn cannot send a
    chart, and the action payload has no room to spare -- the instruction is
    carried on every attempt and is measured against a bound. So the chart
    policy costs nothing until the turn that can act on it. It reaches the
    correction turn too: that turn answers as well, and a correction replaces
    the whole answer, charts included.
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
    # WHAT the answer must be, then HOW to present it. In that order: the
    # prose is the answer and the charts accompany it, and a block list is
    # read in the order it is sent.
    kept.append({"type": "text", "text": json.dumps(
        ANALYTICAL_ANSWER, ensure_ascii=False)})
    kept.append({"type": "text", "text": json.dumps(
        PRESENTATION, ensure_ascii=False)})
    # THE CREDIT POLICY, on the turn that can collide with it.
    #
    # An action turn is choosing what to run; it holds no number, so a
    # threshold in front of it is a threshold nothing can be compared
    # against. The answer turn has the result in hand, and that is the
    # moment "this is above the limit" becomes a sentence worth writing.
    #
    # RETRIEVED HERE RATHER THAN THROUGH A TOOL. It was a tool first, and
    # the tool could never be called: the state that holds a result REQUIRES
    # `finalize_response`, so a companion offered beside it is a schema the
    # run pays for and cannot reach. Retrieval is deterministic and needs no
    # judgement -- the clause ids and topics are in the reader's own words,
    # exactly like `value_resolution` -- so the server does it and the
    # analyst cannot fail to have asked. A question that names no policy
    # topic gets the synopsis and nothing else.
    if domain_id:
        try:
            from backend.cockpit_v4 import credit_policy as cp

            kept.append({"type": "text", "text": json.dumps(
                cp.synopsis(domain_id), ensure_ascii=False)})
            found = cp.retrieve(domain_id, question=question)
            if found.get("clauses"):
                kept.append({"type": "text", "text": json.dumps(
                    found, ensure_ascii=False)})
        except Exception:  # noqa: BLE001 - a book with no policy pack
            pass
    return kept


__all__ = ["DEFAULT_RECENT_TURNS", "MAX_RECENT_TURNS", "PRESENTATION",
           "Packet", "analyst_instruction", "build", "finalization_system"]
