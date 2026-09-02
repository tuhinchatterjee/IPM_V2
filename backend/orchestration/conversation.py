"""
What an Investigation remembers between one question and the next.

The behaviour this replaces
---------------------------
A follow-up used to reach the orchestrator as a bare sentence. `run_investigation`
was handed the question string and a period window and nothing else — the thread
id was used only to file the answer. So:

    "Show me the five largest Real Estate customers by EAD."
    "Which of these are Stage 2 or Stage 3?"

...arrived at the planner as *"Which of these are Stage 2 or Stage 3?"* with no
"these" to resolve. The product was not weak at follow-ups; it had no
conversation at all.

What is remembered
------------------
Two layers, and the split matters.

**Turns** are what was said: the question, the headline answer, the run that
produced it. Small, human-readable, and what a model needs to understand a
reference like "those five".

**State** is what was *settled*: the subject, the measures, the dimension, the
filters, the periods, the datasets, the join path, the grain, the plan that ran,
and the identities the result returned. This is the layer that makes a follow-up
deterministic rather than a re-guess — "these" resolves to five specific customer
ids that are written down, not to five names a model recalled from its own
previous sentence.

What is NOT remembered
----------------------
Rows of **source data**. The state never becomes a cache of the book, and a
follow-up that asks a new analytical question re-reads governed data through
the runtime every time.

What IS remembered, and why that is not the same thing
------------------------------------------------------
The previous **result** — the small, grouped table that was already computed,
invariant-checked and shown. It is carried under its own fingerprint, capped at
`MAX_REUSE_ROWS`.

The distinction is the whole of it. "Which of these are Stage 2?" is a new
question about the portfolio and must reach the runtime. "Does this trend make
sense?" is a question about the ten rows already on the screen, and re-running
the scan to answer it would not make the answer more governed — it would just
risk answering about a *different* ten rows, computed a second apart, under a
sentence that says "this".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Where the state lives inside `Investigation.context`. A nested key rather
#: than the whole column, because the column already carries the settled period
#: that `settled_period()` reads.
STATE_KEY = "conversation"

#: How many identities are carried forward. Enough for "those five" and for a
#: top-fifty ranking; a population larger than this is a cohort, and a follow-up
#: about it should re-derive the cohort rather than pin an id list.
MAX_ENTITY_IDS = 200

#: How many turns are kept. A credit conversation that has run longer than this
#: has changed subject several times, and the state — not the transcript — is
#: what carries anything still relevant.
MAX_TURNS = 8

#: Headline rows kept from the previous result, for describing a change.
MAX_SNAPSHOT_ROWS = 10

#: How much of the previous RESULT is carried so a question about it can be
#: answered without re-running the analysis that produced it.
#:
#: Two hundred, because the results these questions are asked about are grouped
#: — rating grades, sectors, quarters, buckets — and a grouped credit result is
#: tens of rows, not thousands. A result larger than this is a customer listing,
#: and a listing is re-read from the stored run rather than pinned here: the
#: conversation state is written on every turn and must stay small enough that
#: writing it is free.
MAX_REUSE_ROWS = 200


# --------------------------------------------------------------- the pieces


@dataclass
class Turn:
    """One exchange, compactly enough to put in a prompt."""

    question: str
    answer: str = ""
    intent: str = ""
    run_id: int | None = None
    status: str = "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "answer": self.answer,
                "intent": self.intent, "run_id": self.run_id,
                "status": self.status}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Turn:
        return cls(question=str(raw.get("question") or ""),
                   answer=str(raw.get("answer") or ""),
                   intent=str(raw.get("intent") or ""),
                   run_id=raw.get("run_id"),
                   status=str(raw.get("status") or "succeeded"))


@dataclass
class ResultShape:
    """What the previous answer returned, without the data itself."""

    columns: list[dict[str, str]] = field(default_factory=list)
    row_count: int = 0
    #: The column that identifies a row — customer_id, account_id, sector.
    entity_key: str = ""
    #: The identities themselves. This is what "these" resolves to.
    entity_ids: list[str] = field(default_factory=list)
    #: id → readable name, so a clarification can say who rather than which key.
    entity_labels: dict[str, str] = field(default_factory=dict)
    #: A few headline rows, for describing what changed between two turns.
    sample: list[dict[str, Any]] = field(default_factory=list)
    run_id: int | None = None
    #: The result itself, up to `MAX_REUSE_ROWS`, so a question ABOUT it can be
    #: answered from it. Empty when the result was too large to carry, in which
    #: case the reuse path reads it back from the stored run instead.
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: True when `rows` holds only the first `MAX_REUSE_ROWS` of the result.
    #: A statistic computed over a truncated table would describe the top of a
    #: ranking and be reported as describing the whole of it.
    truncated: bool = False
    #: What identifies the execution these rows came out of. A follow-up that
    #: reuses them records it, so the answer can be tied back to the exact run
    #: rather than to "the previous turn".
    fingerprint: str = ""
    #: The question that produced them, so a reused answer can restate it.
    question: str = ""

    @property
    def has_population(self) -> bool:
        return bool(self.entity_key and self.entity_ids)

    def names(self, limit: int = 5) -> list[str]:
        out = [self.entity_labels.get(i, i) for i in self.entity_ids[:limit]]
        return [n for n in out if n]

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns), "row_count": self.row_count,
            "entity_key": self.entity_key,
            "entity_ids": list(self.entity_ids),
            "entity_labels": dict(self.entity_labels),
            "sample": list(self.sample), "run_id": self.run_id,
            "rows": list(self.rows), "truncated": self.truncated,
            "fingerprint": self.fingerprint, "question": self.question,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ResultShape:
        raw = raw or {}
        return cls(
            columns=[dict(c) for c in raw.get("columns") or []],
            row_count=int(raw.get("row_count") or 0),
            entity_key=str(raw.get("entity_key") or ""),
            entity_ids=[str(v) for v in raw.get("entity_ids") or []],
            entity_labels={str(k): str(v)
                           for k, v in (raw.get("entity_labels") or {}).items()},
            sample=[dict(r) for r in raw.get("sample") or []],
            run_id=raw.get("run_id"),
            rows=[dict(r) for r in raw.get("rows") or []],
            truncated=bool(raw.get("truncated")),
            fingerprint=str(raw.get("fingerprint") or ""),
            question=str(raw.get("question") or ""),
        )


@dataclass
class ConversationState:
    """Everything settled so far, in the shape a follow-up needs it.

    Every field is what the *last successful analytical turn* established. A
    metadata answer — "what fields does ratings have?" — deliberately leaves the
    analytical state alone: asking about the catalogue mid-investigation should
    not wipe the population you were working on.
    """

    subject: str = ""
    intent: str = ""
    conversation_action: str = ""
    concepts: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    #: [{"kind": "sector", "value": "Real Estate"}]
    filters: list[dict[str, str]] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    opening_period: str = ""
    closing_period: str = ""
    domains: list[str] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    join_path: list[dict[str, Any]] = field(default_factory=list)
    grain: str = ""
    shape: str = ""
    top_n: int = 0
    #: The movement conditions the previous analysis applied, serialised. A
    #: modification that adds a filter must keep them: "only show Contracting"
    #: after a downgrade cohort means Contracting names IN that cohort, not
    #: every Contracting name in the book.
    conditions: list[dict[str, Any]] = field(default_factory=list)
    plan_summary: str = ""
    #: The Analytical IR that last ran. Carried so a modification can be
    #: described against it and so the Trace can show the plan it came from.
    ir: dict[str, Any] = field(default_factory=dict)
    plan_fingerprint: str = ""
    result: ResultShape = field(default_factory=ResultShape)
    visualization: str = ""
    certified_methods: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    #: The question CreditProbe could not plan and asked about, held so the
    #: reply can be merged with it instead of read as a fresh request. §9: a
    #: clarification must not destroy the context the thread had settled.
    #: Cleared by the next turn that settles anything.
    pending: str = ""

    # ---- reading -----------------------------------------------------------

    @property
    def empty(self) -> bool:
        return not self.turns and not self.subject

    @property
    def has_analysis(self) -> bool:
        """Whether an analysis has run — the precondition for a modification."""
        return bool(self.ir)

    def filter_pairs(self) -> list[tuple[str, str]]:
        return [(str(f.get("kind") or f.get("field") or ""),
                 str(f.get("value") or ""))
                for f in self.filters
                if (f.get("kind") or f.get("field")) and f.get("value")]

    # ---- writing -----------------------------------------------------------

    def remember_turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        if len(self.turns) > MAX_TURNS:
            del self.turns[: len(self.turns) - MAX_TURNS]

    def clear_population(self) -> None:
        """Forget the identities but keep the subject.

        Used when a follow-up widens the question back out — "and across the
        whole book?" — where carrying five customer ids would silently answer a
        narrower question than was asked.
        """
        self.result = ResultShape(columns=self.result.columns,
                                  row_count=self.result.row_count)

    # ---- serialisation -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject, "intent": self.intent,
            "conversation_action": self.conversation_action,
            "concepts": list(self.concepts), "metrics": list(self.metrics),
            "dimensions": list(self.dimensions),
            "filters": [dict(f) for f in self.filters],
            "periods": list(self.periods),
            "opening_period": self.opening_period,
            "closing_period": self.closing_period,
            "domains": list(self.domains), "datasets": list(self.datasets),
            "join_path": [dict(j) for j in self.join_path],
            "grain": self.grain, "shape": self.shape, "top_n": self.top_n,
            "conditions": [dict(c) for c in self.conditions],
            "plan_summary": self.plan_summary,
            "ir": dict(self.ir),
            "plan_fingerprint": self.plan_fingerprint,
            "result": self.result.to_dict(),
            "visualization": self.visualization,
            "certified_methods": list(self.certified_methods),
            "turns": [t.to_dict() for t in self.turns],
            "pending": self.pending,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ConversationState:
        raw = raw or {}
        return cls(
            subject=str(raw.get("subject") or ""),
            intent=str(raw.get("intent") or ""),
            conversation_action=str(raw.get("conversation_action") or ""),
            concepts=[str(v) for v in raw.get("concepts") or []],
            metrics=[str(v) for v in raw.get("metrics") or []],
            dimensions=[str(v) for v in raw.get("dimensions") or []],
            filters=[dict(f) for f in raw.get("filters") or []],
            periods=[str(v) for v in raw.get("periods") or []],
            opening_period=str(raw.get("opening_period") or ""),
            closing_period=str(raw.get("closing_period") or ""),
            domains=[str(v) for v in raw.get("domains") or []],
            datasets=[str(v) for v in raw.get("datasets") or []],
            join_path=[dict(j) for j in raw.get("join_path") or []],
            grain=str(raw.get("grain") or ""),
            shape=str(raw.get("shape") or ""),
            top_n=int(raw.get("top_n") or 0),
            conditions=[dict(c) for c in raw.get("conditions") or []],
            plan_summary=str(raw.get("plan_summary") or ""),
            ir=dict(raw.get("ir") or {}),
            plan_fingerprint=str(raw.get("plan_fingerprint") or ""),
            result=ResultShape.from_dict(raw.get("result") or {}),
            visualization=str(raw.get("visualization") or ""),
            certified_methods=[str(v) for v in raw.get("certified_methods") or []],
            turns=[Turn.from_dict(t) for t in raw.get("turns") or []],
            pending=str(raw.get("pending") or ""),
        )

    # ---- what the model is told -------------------------------------------

    def brief(self) -> str:
        """The conversation, compact enough to prepend to every follow-up.

        Deliberately a written summary rather than a dump of the state object.
        The model is being asked *what does this new sentence mean given what
        just happened*, and a prose recap of the last turns plus an explicit
        list of what is currently pinned answers that better than JSON would.

        Never contains a row of governed data beyond the identities and the
        headline sample already in the state.
        """
        if self.empty:
            return ""

        lines: list[str] = ["CONVERSATION SO FAR (most recent last):"]
        for index, turn in enumerate(self.turns[-MAX_TURNS:], start=1):
            lines.append(f"  [{index}] USER: {turn.question}")
            if turn.answer:
                lines.append(f"      CREDITPROBE: {turn.answer[:220]}")

        if not self.has_analysis and not self.subject:
            return "\n".join(lines)

        lines.append("\nWHAT THE CONVERSATION HAS SETTLED:")
        if self.subject:
            lines.append(f"  subject: {self.subject}")
        if self.metrics or self.concepts:
            lines.append("  measures: "
                         + ", ".join(self.metrics or self.concepts))
        if self.dimensions:
            lines.append(f"  broken down by: {', '.join(self.dimensions)}")
        if self.filters:
            lines.append("  filters: " + ", ".join(
                f"{f.get('kind') or f.get('field')} = {f.get('value')}"
                for f in self.filters))
        if self.closing_period and self.opening_period:
            lines.append(f"  comparison: {self.opening_period} → "
                         f"{self.closing_period}")
        elif self.periods:
            lines.append(f"  period: {', '.join(self.periods)}")
        if self.grain:
            lines.append(f"  one row per: {self.grain}")
        if self.datasets:
            lines.append(f"  datasets in use: {', '.join(self.datasets)}")
        if self.top_n:
            lines.append(f"  cut to: top {self.top_n}")
        if self.conditions:
            lines.append("  conditions in force: " + ", ".join(
                str(c.get("describe") or c.get("field")) for c in self.conditions))

        if self.result.has_population:
            names = self.result.names(5)
            lines.append(
                f"\nPREVIOUS RESULT POPULATION — {self.result.row_count} row(s) "
                f"keyed by {self.result.entity_key}"
                + (f", including {', '.join(names)}" if names else "")
                + ".")
            lines.append(
                "  A reference such as \"these\", \"those\", \"them\", \"those "
                "five\" or \"the previous result\" means EXACTLY this "
                "population. Set conversation_action to CONTINUE and leave the "
                "population to CreditProbe — do not restate the ids.")
        if self.result.columns:
            lines.append("  previous columns: " + ", ".join(
                str(c.get("name")) for c in self.result.columns[:12]))
        return "\n".join(lines)


# ------------------------------------------------------------ continuation


NEW_REQUEST = "NEW_REQUEST"
CONTINUE = "CONTINUE"
ENRICH_PREVIOUS = "ENRICH_PREVIOUS"
CLARIFY = "CLARIFY"

#: A modification, in five kinds rather than one.
#:
#: `MODIFY_PREVIOUS` still exists and still means "change the previous plan",
#: because everything downstream branches on it. What it did not carry was
#: *what* was being changed, and the difference matters: replacing the measure
#: keeps the population and rebuilds the arithmetic; changing the presentation
#: keeps the arithmetic and rebuilds nothing at all. Answering "show it as a
#: graph" by recomputing a portfolio aggregate is how a chart request came back
#: as an empty analysis.
MODIFY_PREVIOUS = "MODIFY_PREVIOUS"
MODIFY_CALCULATION = "MODIFY_CALCULATION"
MODIFY_FILTER = "MODIFY_FILTER"
MODIFY_POPULATION = "MODIFY_POPULATION"
MODIFY_PERIOD = "MODIFY_PERIOD"
MODIFY_PRESENTATION = "MODIFY_PRESENTATION"

#: Follow-ups that are not analyses.
ASK_ABOUT_RESULT = "ASK_ABOUT_RESULT"
#: A question about the PATTERN in the result that is already on the table.
#:
#: Distinct from ASK_ABOUT_RESULT, which reads a value back out of it ("what
#: was Contracting?"), and distinct from CONTINUE, which plans and runs
#: something new. "Does this trend make sense?" asks CreditProbe to reason over
#: rows it has already computed — so it reuses them, runs approved statistics
#: over them in memory, and rescans no governed data at all.
ASSESS_PREVIOUS_RESULT = "ASSESS_PREVIOUS_RESULT"
METADATA_FOLLOWUP = "METADATA_FOLLOWUP"
NAVIGATE = "NAVIGATE"
CORRECT_INCOMPLETE_RESPONSE = "CORRECT_INCOMPLETE_RESPONSE"

#: Deliberate changes of analytical scope.
RESET_SCOPE = "RESET_SCOPE"
WIDEN_SCOPE = "WIDEN_SCOPE"
#: The reader named a governed dimension value and nothing else — "Why
#: Shipping?", "And Contracting?", "What about Stage 2?".
#:
#: It is not a new request: the sentence names no measure, so read as one it
#: produced "which figure should CreditProbe measure?" — the product asking the
#: reader to repeat what it had just computed. It is not a CONTINUE either:
#: the named value REPLACES the active scope rather than intersecting with the
#: rows already on screen, and carrying those rows would answer "why Shipping?"
#: about whichever twenty-five names the previous ranking happened to return.
#:
#: So: keep the measure, the period and the shape of the analysis that just
#: ran; take the population from the value the sentence names.
NARROW_SCOPE = "NARROW_SCOPE"

ACTIONS: tuple[str, ...] = (
    NEW_REQUEST, CONTINUE,
    MODIFY_PREVIOUS, MODIFY_CALCULATION, MODIFY_FILTER, MODIFY_POPULATION,
    MODIFY_PERIOD, MODIFY_PRESENTATION,
    ENRICH_PREVIOUS, ASK_ABOUT_RESULT, ASSESS_PREVIOUS_RESULT,
    METADATA_FOLLOWUP, NAVIGATE,
    CORRECT_INCOMPLETE_RESPONSE, RESET_SCOPE, WIDEN_SCOPE, NARROW_SCOPE,
    CLARIFY,
)

#: Every kind of modification, for code that only cares that it is one.
MODIFICATIONS = frozenset({
    MODIFY_PREVIOUS, MODIFY_CALCULATION, MODIFY_FILTER, MODIFY_POPULATION,
    MODIFY_PERIOD, MODIFY_PRESENTATION,
})

#: Actions answered without composing or running anything new. The previous
#: result is already on the table; what changes is how it is shown or what is
#: said about it.
NON_ANALYTICAL = frozenset({
    MODIFY_PRESENTATION, ASK_ABOUT_RESULT, ASSESS_PREVIOUS_RESULT,
    METADATA_FOLLOWUP, NAVIGATE,
})

#: The actions whose answer is computed from the PREVIOUS RESULT rather than
#: from governed data. Everything in here must leave the data access layer,
#: DuckDB and the Parquet lake untouched, and must say so on the Trace.
REUSES_RESULT = frozenset({MODIFY_PRESENTATION, ASSESS_PREVIOUS_RESULT})

#: The actions that carry the previous turn's settled context forward. CLARIFY
#: carries it too — a clarification is answered inside the same subject.
#: WIDEN_SCOPE carries it deliberately: it needs the previous scope precisely so
#: it can say what is being widened from.
CONTINUING = frozenset(
    {CONTINUE, ENRICH_PREVIOUS, CLARIFY, ASK_ABOUT_RESULT,
     ASSESS_PREVIOUS_RESULT, METADATA_FOLLOWUP, NAVIGATE,
     CORRECT_INCOMPLETE_RESPONSE, WIDEN_SCOPE, NARROW_SCOPE}
    | MODIFICATIONS)

#: RESET_SCOPE is deliberately NOT continuing. It is the one follow-up whose
#: whole meaning is "stop using what we established", and treating it as a
#: continuation would inherit the population it exists to discard.


def normalise(action: str) -> str:
    """A model's answer mapped onto an action CreditProbe implements.

    Models produce near-misses — MODIFY, CHANGE_FILTER, FOLLOW_UP — and a
    near-miss that falls through to NEW_REQUEST silently loses the whole
    conversation. Mapping them is cheaper than a repair call and it fails in the
    safe direction: an unrecognised action that mentions a known one is read as
    that one, and anything else is a new request.
    """
    text = (action or "").strip().upper().replace("-", "_").replace(" ", "_")
    if text in ACTIONS:
        return text
    for known in ACTIONS:
        if known in text:
            return known
    if text.startswith("MODIFY") or text.startswith("CHANGE"):
        return MODIFY_PREVIOUS
    if "FOLLOW" in text or "CONTINU" in text:
        return CONTINUE
    return NEW_REQUEST


@dataclass
class Continuation:
    """How this question relates to the one before it, once decided.

    Produced by `resolve()` from the model's `conversation_action`, the
    deterministic referent reader and the state. Carried into the planner and
    onto the Trace, so a follow-up's answer can show what it inherited rather
    than appearing to have been planned from nothing.
    """

    action: str = NEW_REQUEST
    #: The phrase that referred back, where one did — "these", "those five".
    referent: str = ""
    #: chart | table, for MODIFY_PRESENTATION.
    presentation: str = ""
    entity_key: str = ""
    entity_ids: list[str] = field(default_factory=list)
    entity_labels: dict[str, str] = field(default_factory=dict)
    #: What was carried forward, for the Trace: {"dimension": "sector", ...}
    inherited: dict[str, Any] = field(default_factory=dict)
    #: Plain-English modifications, for the Trace's plan-change node.
    changes: list[str] = field(default_factory=list)
    #: Why this was read as a continuation rather than a new request.
    because: str = ""
    #: How an ordinal reference — "the second one" — bound to the stored order.
    #: Carried whether or not it bound: a reference that could not be resolved
    #: is a fact the Trace has to show, not one to leave out.
    ordinal: dict[str, Any] = field(default_factory=dict)

    @property
    def carries_context(self) -> bool:
        return self.action in CONTINUING

    @property
    def has_population(self) -> bool:
        return bool(self.entity_key and self.entity_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action, "referent": self.referent,
            "presentation": self.presentation,
            "entity_key": self.entity_key,
            "entity_ids": list(self.entity_ids),
            "entity_count": len(self.entity_ids),
            "entity_names": [self.entity_labels.get(i, i)
                             for i in self.entity_ids[:8]],
            "inherited": dict(self.inherited),
            "changes": list(self.changes),
            "because": self.because,
            "ordinal": dict(self.ordinal),
        }


#: A reply to a clarification rather than a new question. Short, and it does
#: not ask anything of its own — "Expected credit loss.", "The 12-month PD",
#: "Yes, since last quarter". A full sentence that asks something is a new
#: question however closely it follows a clarification.
_ASKS = re.compile(
    r"^\s*(?:what|which|who|whom|whose|when|where|why|how|show|list|rank|give|"
    r"tell|compare|find|break|bridge|explain|is|are|was|were|do|does|did|can|"
    r"could|would|should|has|have|had)\b", re.IGNORECASE)

#: How long a reply may be and still be read as an answer rather than a
#: question. Long enough for "the movement in expected credit loss since Q4",
#: short enough that a fresh sentence does not slip through.
MAX_REPLY_WORDS = 10


def answers_a_clarification(reply: str) -> bool:
    """Whether this sentence answers the question CreditProbe just asked.

    Deliberately conservative, and in one direction. Reading a reply as a new
    question loses the pending intent, which is the defect §9 names; reading a
    new question as a reply would answer something nobody asked, which is
    worse. So only a short, non-interrogative fragment counts.
    """
    text = " ".join(str(reply or "").split())
    if not text or len(text.split()) > MAX_REPLY_WORDS:
        return False
    return not _ASKS.match(text)


def load(context: dict[str, Any] | None) -> ConversationState:
    """The state out of an Investigation's context column."""
    return ConversationState.from_dict((context or {}).get(STATE_KEY))


def save(context: dict[str, Any] | None,
         state: ConversationState) -> dict[str, Any]:
    """The context column with this state written into it.

    Returns a new dict rather than mutating, because the caller holds a value
    read out of the ORM and writing through it would persist half a change if
    the transaction later failed.
    """
    out = dict(context or {})
    out[STATE_KEY] = state.to_dict()
    return out


__all__ = [
    "ACTIONS", "ASSESS_PREVIOUS_RESULT", "CLARIFY", "CONTINUE", "CONTINUING",
    "ENRICH_PREVIOUS",
    "MAX_ENTITY_IDS", "MAX_REUSE_ROWS", "MAX_SNAPSHOT_ROWS", "MAX_TURNS",
    "MAX_REPLY_WORDS", "MODIFY_PREVIOUS", "NARROW_SCOPE", "NEW_REQUEST",
    "REUSES_RESULT", "STATE_KEY", "answers_a_clarification",
    "ConversationState", "Continuation", "ResultShape", "Turn",
    "load", "save",
]
