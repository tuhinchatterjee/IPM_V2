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

from backend.cockpit_v4 import DOMAIN, PROMPT_VERSION
from backend.cockpit_v4.config import Limits

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "analyst.md"

#: Default and maximum recent Q&A pairs carried into a new turn.
DEFAULT_RECENT_TURNS = 3
MAX_RECENT_TURNS = 8


def analyst_instruction() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


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


def _registry_compact() -> list[dict[str, Any]]:
    """Which functionality owns what, with the routes that actually exist."""
    try:
        from backend.cockpit_agentic import registry as v3_registry
        doc = v3_registry.compact()
    except Exception:  # noqa: BLE001
        return []
    entries = doc.get("functionalities") if isinstance(doc, dict) else doc
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        out.append({k: entry.get(k) for k in
                    ("id", "name", "owns", "excludes", "route", "enabled")
                    if entry.get(k) is not None})
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
          investigation: dict[str, Any] | None = None) -> Packet:
    """Assemble the packet. Never trims the instruction to hit a target."""
    calendar = getattr(catalog, "calendar", None)
    quarters = list(getattr(calendar, "slots", ()) or ())
    populated = list(getattr(calendar, "populated", ()) or ())

    pinned = {
        "domain": DOMAIN,
        "release_id": getattr(scope, "dataset_release_id", ""),
        "tenant": "server-pinned; not settable from this conversation",
        "reporting_quarters": quarters,
        "populated_quarters": populated,
        "latest_populated_quarter": populated[-1] if populated else "",
        "reporting_currency": getattr(catalog, "reporting_currency", ""),
        "amount_scale": getattr(catalog, "amount_scale", ""),
        "mode": mode,
        "ui_filters": dict(ui_filters or {}),
        "cockpit_location": location,
        "release": {k: release_summary.get(k) for k in
                    ("dataset_release_id", "origin", "data_version",
                     "not_client_data", "reporting_currency", "amount_scale")
                    if k in release_summary},
    }

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
        {"type": "text", "text": analyst_instruction()},
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
            "product_functionalities": _registry_compact(),
            "catalog_index": _catalog_index(catalog, scope),
            "catalog_index_note": (
                "This is an INDEX, not the field dictionary. Definitions, "
                "units, grain, joins and coverage come from inspect_catalog "
                "for exactly the fields you need."),
        }, ensure_ascii=False)},
        # Volatile content last.
        {"type": "text", "text": json.dumps({
            "pinned_scope": pinned, "budgets": budget,
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
            "Cockpit attention card; treat its segment, quarters and metric "
            "as the standing subject unless the user changes them, and "
            "re-derive any number you state from your own executed query):\n"
            + json.dumps(investigation, ensure_ascii=False, default=str))
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
                 "recent_turns": history,
                 "investigation": investigation or {},
                 "principal": {"id": principal.get("id", ""),
                               "tenant": principal.get("tenant", "")}})


__all__ = ["DEFAULT_RECENT_TURNS", "MAX_RECENT_TURNS", "Packet",
           "analyst_instruction", "build"]
