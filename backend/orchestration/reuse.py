"""
Answering a question about the result that is already on the screen.

The behaviour this replaces
---------------------------
    "For each rating grade, show average ECL coverage, average leverage and
     average DSCR in the latest period."
    "Does this trend make sense?"

The second question used to re-plan and re-execute: a fresh scan of the lake, a
fresh DuckDB statement, a fresh join, a fresh aggregation — to produce the same
ten rows the user was looking at while they typed. It gave the right answer, and
it was wrong in three ways.

It was **slow**, paying full analytical cost for a question that needed none.

It was **fragile**: a re-plan is a re-guess, and a sentence naming no measure
("does this trend make sense?") gives the planner nothing to plan from, so the
turn could come back asking which figure the user meant — about the figures
already on their screen.

And it was **unsound**. Two executions a second apart are two results. If the
second one differed at all, the answer would describe a table nobody had seen,
under a sentence that says "this".

What this module does instead
------------------------------
It hands back the previous result — the rows, the schema, the population, the
periods, the filters, the fingerprint — so the assessment can be computed over
exactly what was shown.

Where the rows come from
------------------------
Two places, in order, and **neither of them reads governed data**:

1. **The conversation state.** The last result is carried there, capped at
   `conversation.MAX_REUSE_ROWS`. Grouped results are tens of rows, so this is
   the normal path.
2. **The stored run.** When the result was too large to carry, or the state has
   been pruned, the rows are read back out of the run that was persisted when
   the answer was first given. That is a Postgres read of a recorded artefact,
   not an analytical execution: no Parquet, no DuckDB, no join.

If neither has it, this module says so and the caller asks. It does not quietly
re-run the analysis — §18 of the remediation brief, and the point of the whole
exercise: the failure mode being fixed is silently answering from something
other than what the user is looking at.

What is deliberately NOT here
------------------------------
Widening. "Show me the customers inside grade 5" is a new analysis and must be
planned and executed like one. Reuse answers questions about the result; it
never grows the result to make a question answerable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import conversation as cv
from backend.orchestration import kernels

logger = logging.getLogger(__name__)

#: Below this many rows a result describes a position, not a pattern. One row
#: is an aggregate; four are four points. Either can be reported back, neither
#: can carry "the trend is consistent".
MIN_ROWS_FOR_A_PATTERN = kernels.MIN_OBSERVATIONS

#: How the state records where the reused rows came from.
FROM_STATE = "conversation_state"
FROM_STORE = "stored_run"


# ---------------------------------------------------------------------------
# Recognising the question
# ---------------------------------------------------------------------------

#: Questions that are about the previous RESULT rather than about the book.
#:
#: Every one of these is unanswerable without the previous result — which is
#: what makes the list safe to act on. "Does this trend make sense?" has no
#: meaning as an opening question, so reading it as one was never right; the
#: only question was whether CreditProbe noticed.
#:
#: Deliberately excluded: "why", which asks for a cause. Those are answered
#: too, but with the association AND the statement that an aggregate cannot
#: establish why — see `association.CAVEAT`.
_ABOUT_THE_RESULT: tuple[str, ...] = (
    r"\bdoes (?:this|that|the) .{0,40}\bmake sense\b",
    r"\bdoes (?:this|that|it) make sense\b",
    r"\bmakes? sense\b",
    r"\b(?:is|are) (?:that|this|these|those|the) .{0,40}"
    r"(?:consistent|monotonic|reliable|meaningful|supported|justified|"
    r"reasonable|plausible|expected)\b",
    r"\bis (?:that|this|the) (?:conclusion|reading|finding|pattern|trend|"
    r"relationship|association) supported\b",
    r"\bhow strong is (?:that|this|the) (?:relationship|association|"
    r"correlation|pattern|trend)\b",
    r"\bare there (?:any )?(?:exceptions|outliers|inversions|breaks)\b",
    r"\bwhich .{0,30}(?:do not|don'?t|does not|doesn'?t) fit\b",
    r"\bis (?:this|that|it) monotonic\b",
    r"\bwhat (?:explains|drives) (?:this|that|the) (?:pattern|trend|"
    r"relationship|result)\b",
    r"\bwhat should i take (?:from|away from) (?:this|that|these)\b",
    r"\bwhat do you (?:make of|read into) (?:this|that|these)\b",
    r"\bhow (?:reliable|robust|solid) is (?:this|that|the) ",
    r"\bdo (?:these|those|the) (?:figures|numbers|results|rows) "
    r"(?:hold together|agree|line up)\b",
)

_PATTERN = re.compile("|".join(_ABOUT_THE_RESULT), re.I)

#: A sentence that explicitly asks for MORE than the result holds. These are
#: never reuse, however much they look like a question about the result — they
#: are a scope change, and §18 says a scope change is executed on request and
#: traced separately, not slipped in behind an assessment.
_WIDENS = re.compile(
    r"\b(?:expand|widen|broaden|drill (?:down|into)|break (?:this )?down|"
    r"go deeper|at (?:the )?(?:customer|borrower|facility|account) level|"
    r"by customer|by borrower|per customer|per borrower|"
    r"run (?:it|that|this) (?:again|properly)|re-?run)\b", re.I)


def wants(question: str) -> bool:
    """Whether this sentence asks about the result already on the table."""
    text = " ".join((question or "").lower().split())
    if not text:
        return False
    if _WIDENS.search(text):
        return False
    return bool(_PATTERN.search(text))


def asks_to_expand(question: str) -> bool:
    """Whether the sentence explicitly asks for a wider analysis."""
    return bool(_WIDENS.search(question or ""))


# ---------------------------------------------------------------------------
# The cached result
# ---------------------------------------------------------------------------


@dataclass
class Cached:
    """The previous governed result, exactly as it was shown."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    #: Where the rows came back from. Both sources are recorded reads; neither
    #: touches governed data. On the Trace so a reader can check the claim.
    source: str = ""
    run_id: int | None = None
    fingerprint: str = ""
    question: str = ""
    dimension: str = ""
    periods: list[str] = field(default_factory=list)
    filters: list[dict[str, str]] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    join_path: list[dict[str, Any]] = field(default_factory=list)
    entity_key: str = ""
    entity_ids: list[str] = field(default_factory=list)
    plan_summary: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.rows and self.columns)

    @property
    def dimension_label(self) -> str:
        """The grouping column as a reader sees it, not as the lake stores it.

        "10 internal grade groups", never "10 customer_ratings_internal_grade
        groups" — the prefixed name is a join artefact and putting it in a
        sentence makes the product sound like its own schema.
        """
        for column in self.columns:
            if str(column.get("name") or "") == self.dimension:
                return str(column.get("label") or self.dimension)
        return self.dimension

    def scope_sentence(self) -> str:
        """What this result covered, in one line, for the reused answer."""
        parts: list[str] = []
        if self.dimension:
            parts.append(f"{self.row_count} "
                         f"{self.dimension_label.lower()} groups")
        elif self.row_count:
            parts.append(f"{self.row_count} rows")
        if self.periods:
            parts.append(" to ".join(self.periods) if len(self.periods) > 1
                         else self.periods[0])
        for f in self.filters[:2]:
            value = str(f.get("value") or "").strip()
            if value:
                parts.append(value)
        return " · ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count, "truncated": self.truncated,
            "source": self.source, "run_id": self.run_id,
            "fingerprint": self.fingerprint, "question": self.question,
            "dimension": self.dimension, "periods": list(self.periods),
            "filters": [dict(f) for f in self.filters],
            "datasets": list(self.datasets),
            "columns": [str(c.get("name") or "") for c in self.columns],
            "population": len(self.entity_ids),
            "plan_summary": self.plan_summary,
        }


@dataclass
class Provenance:
    """What a reused answer records about where its figures came from.

    Every field here is asserted by a test, because "no governed data was
    rescanned" is a claim the product makes on screen and a claim of that kind
    has to be checkable rather than believed.
    """

    derived_from_run_id: int | None = None
    derived_from_result_fingerprint: str = ""
    reused_result: bool = True
    data_rescan: bool = False
    original_run_sha: str = ""
    original_question: str = ""
    original_periods: list[str] = field(default_factory=list)
    original_scope: str = ""
    source: str = ""
    rows_reused: int = 0
    #: Which approved kernels ran, by name.
    kernels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_from_run_id": self.derived_from_run_id,
            "derived_from_result_fingerprint":
                self.derived_from_result_fingerprint,
            "reused_result": self.reused_result,
            "data_rescan": self.data_rescan,
            "original_run_sha": self.original_run_sha,
            "original_question": self.original_question,
            "original_periods": list(self.original_periods),
            "original_scope": self.original_scope,
            "source": self.source,
            "rows_reused": self.rows_reused,
            "kernels": list(self.kernels),
        }


def provenance_of(cached: Cached, *, kernels_run: list[str] | None = None
                  ) -> Provenance:
    return Provenance(
        derived_from_run_id=cached.run_id,
        derived_from_result_fingerprint=cached.fingerprint,
        original_run_sha=_build_sha(),
        original_question=cached.question,
        original_periods=list(cached.periods),
        original_scope=cached.scope_sentence(),
        source=cached.source,
        rows_reused=len(cached.rows),
        # The DISTINCT kernels, in a stable order. The same statistic running
        # once per measure pair is one approved operation, not four, and a
        # provenance record that lists it four times reads as four decisions.
        kernels=sorted(set(kernels_run or [])),
    )


def _build_sha() -> str:
    """The build that produced the answer being reused.

    Recorded rather than assumed: a reused result computed by one build and
    assessed by another is still the same rows, but a reader auditing it needs
    to know the two halves came from different code.
    """
    try:
        from backend.build_info import build_info

        return build_info().sha
    except Exception:  # noqa: BLE001 - provenance must not lose an answer
        return ""


# ---------------------------------------------------------------------------
# Finding it
# ---------------------------------------------------------------------------


def cached_result(state: cv.ConversationState) -> Cached | None:
    """The previous result, from the state or from the run that recorded it.

    Returns None when there is no previous analytical result at all — a first
    question, or a thread that has only asked about the catalogue.
    """
    if state is None or getattr(state, "empty", True):
        return None
    shape = getattr(state, "result", None)
    if shape is None or not shape.columns:
        return None

    rows = [dict(r) for r in (shape.rows or [])]
    source = FROM_STATE
    if not rows and shape.run_id:
        rows = _rows_from_store(shape.run_id)
        source = FROM_STORE if rows else ""
    if not rows:
        return None

    return Cached(
        rows=rows,
        columns=[dict(c) for c in shape.columns],
        row_count=shape.row_count or len(rows),
        truncated=bool(shape.truncated) and source == FROM_STATE,
        source=source,
        run_id=shape.run_id,
        fingerprint=shape.fingerprint or state.plan_fingerprint,
        question=shape.question or _last_analytical_question(state),
        dimension=(state.dimensions[0] if state.dimensions else ""),
        periods=list(state.periods),
        filters=[dict(f) for f in state.filters],
        datasets=list(state.datasets),
        join_path=[dict(j) for j in state.join_path],
        entity_key=shape.entity_key,
        entity_ids=list(shape.entity_ids),
        plan_summary=state.plan_summary,
    )


def _last_analytical_question(state: cv.ConversationState) -> str:
    for turn in reversed(list(getattr(state, "turns", []) or [])):
        if turn.status == "succeeded" and turn.run_id:
            return turn.question
    return state.subject or ""


def _rows_from_store(run_id: int) -> list[dict[str, Any]]:
    """The rows of a recorded run, read back from the platform database.

    Not an analytical execution. The rows were computed once, validated once
    and filed; this reads the file. It is the same operation the Trace viewer
    performs when a user reopens an investigation, and it is why reopening one
    does not re-run it.
    """
    try:
        from backend.orchestration import store

        payload = store.load_version(run_id)
    except Exception as e:  # noqa: BLE001 - absence is an outcome, not a crash
        logger.info("The stored run %s could not be read back: %s", run_id, e)
        return []

    for step in payload.get("steps") or []:
        rows = ((step or {}).get("result") or {}).get("rows")
        if rows:
            return [dict(r) for r in rows]
    return []


# ---------------------------------------------------------------------------
# Whether it is enough
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sufficiency:
    """Whether the cached result can carry the question asked of it."""

    ok: bool
    #: What is missing, in the words the answer will use.
    missing: str = ""
    #: The analysis that WOULD answer it, offered rather than run.
    offer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "missing": self.missing, "offer": self.offer}


def sufficient(cached: Cached | None, question: str = "") -> Sufficiency:
    """Whether an assessment can honestly be made from these rows.

    The one-row case is the one that matters. A portfolio aggregate answers
    "what is total ECL?" perfectly and establishes nothing whatever about a
    trend — and inventing an assessment from it is exactly the confident,
    reconciled, wrong answer this whole phase exists to stop.
    """
    if cached is None or not cached.usable:
        return Sufficiency(
            ok=False,
            missing="there is no previous result in this investigation to "
                    "assess",
            offer="Ask an analytical question first, and I will assess the "
                  "pattern in what it returns.")

    measures = [c for c in cached.columns
                if not c.get("hidden") and _is_measure(c)]
    if len(cached.rows) < MIN_ROWS_FOR_A_PATTERN:
        held = ("one aggregate row" if len(cached.rows) == 1
                else f"{len(cached.rows)} rows")
        return Sufficiency(
            ok=False,
            missing=(f"the previous result contains {held}, so it cannot "
                     "establish an association — at least "
                     f"{MIN_ROWS_FOR_A_PATTERN} grouped observations are "
                     "needed before a pattern can be told from the spread"),
            offer=_expansion_offer(cached))
    if not measures:
        return Sufficiency(
            ok=False,
            missing="the previous result carries no measure to assess — it "
                    "lists identities rather than figures",
            offer="Add a measure to the result, and I will assess how it "
                  "moves across the groups.")
    if cached.truncated:
        return Sufficiency(
            ok=False,
            missing=(f"only the first {len(cached.rows)} rows of a "
                     f"{cached.row_count}-row result are held, and a "
                     "statistic computed over the top of a ranking would be "
                     "reported as describing all of it"),
            offer="Re-run the analysis grouped, and I will assess the "
                  "pattern across the groups.")
    return Sufficiency(ok=True)


def _is_measure(column: dict[str, Any]) -> bool:
    """Whether a column holds a figure to reason about rather than a label."""
    role = str(column.get("role") or "").lower()
    if role in ("dimension", "subject", "identity", "label", "period"):
        return False
    semantic = str(column.get("semantic") or column.get("unit") or "").lower()
    return semantic not in ("", "text", "identity", "label", "category")


def _expansion_offer(cached: Cached) -> str:
    """The analysis that would make the question answerable, as an offer.

    Named specifically — "at customer level within each grade" rather than
    "expand the analysis" — because a generic offer makes the user do the work
    of designing the follow-up CreditProbe just declined to guess at.
    """
    if cached.dimension:
        return (f"Expand the analysis to the individual rows inside each "
                f"{cached.dimension}, and I will assess the pattern across "
                "them.")
    return ("Expand the analysis to a grouped view — by rating grade, sector "
            "or period — and I will assess the pattern across the groups.")


__all__ = [
    "FROM_STATE", "FROM_STORE", "MIN_ROWS_FOR_A_PATTERN",
    "Cached", "Provenance", "Sufficiency",
    "asks_to_expand", "cached_result", "provenance_of", "sufficient", "wants",
]
