"""
What the reader is told a turn is doing, while it does it.

Why this exists
---------------
An Early Warning turn takes fifteen to sixty seconds. For all of that time the
screen used to show a grey rectangle, and a grey rectangle is indistinguishable
from a hang. The reader cannot tell whether CreditProbe is thinking, stuck, or
about to fail — so they wait, or they reload and pay for the turn twice.

The turn already knows exactly what it is doing: `pipeline.answer` emits an
event at every stage. This module is the translation layer between those events
and a sentence a credit officer can read.

Two rules govern it
-------------------
**Nothing here invents progress.** Every visible step is produced by a real
pipeline event. There is no timer that advances the display while the server is
quiet, no estimated percentage, and no step that appears because it usually
happens next. A step the pipeline never reported is a step the reader never
sees. That is the difference between a progress indicator and a decoration, and
it is the whole reason the mapping is a pure function of the event list rather
than a state machine with its own clock.

**Nothing here is model engineering.** The reader does not see `sonnet_pass_1`,
a provider name, a token count, a schema error or a call budget. They see
"Understanding your question". The internal vocabulary is the audit record; this
is the sentence, and the two are deliberately different things kept in one file
so they cannot drift apart.

What it is not
--------------
Not a chain-of-thought viewer. The only strings this module can produce are the
constants written below and values the governed plan already recorded — an
analysis type, a segment name, a period. There is no path from a model's
intermediate text to a progress label, and adding one would make this a window
into deliberation that is not the reader's to see.

The ordering question
---------------------
The visible sequence follows the order the pipeline ACTUALLY runs in, which
puts "Loading Early Warning evidence" before "Checking the right CreditProbe
functionality": the domain package is built first, and ownership is decided
from the normalised request against that package. Listing ownership first would
read better and would be a lie — the reader would watch a step tick after the
step below it had already ticked. The Cockpit learned the same lesson (see
`backend/agentic/stages.py`, where COORDINATING was moved after CALCULATING for
exactly this reason), and truthfulness wins over the tidier reading order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Bumped when the shape below changes in a way a client must notice. The
#: frontend reads it and falls back to a plain working state rather than
#: rendering a document it does not understand.
CONTRACT_VERSION = 1

# ------------------------------------------------------------------ statuses

WAITING = "waiting"
ACTIVE = "active"
DONE = "done"
#: Informational. A step that happened but is not a milestone — a deferred
#: drill-down, a plan correction, a governed fallback. Rendered quietly,
#: never as a failure, because none of them is one.
NOTE = "note"
#: The turn stopped here for a stated reason.
STOPPED = "stopped"

# -------------------------------------------------------------------- steps

UNDERSTANDING = "understanding"
SCOPING = "scoping"
EVIDENCE = "evidence"
OWNERSHIP = "ownership"
PLANNING = "planning"
VALIDATING = "validating"
ANALYSING = "analysing"
CHECKING = "checking"
INTERPRETING = "interpreting"
CONTEXT = "context"
COMPLETE = "complete"

#: The milestones, in the order the pipeline reaches them. A turn does not
#: emit all of them — a redirect reaches four — which is the point of a
#: sequence rather than a checklist.
STEP_ORDER: tuple[str, ...] = (
    UNDERSTANDING, SCOPING, EVIDENCE, OWNERSHIP, PLANNING, VALIDATING,
    ANALYSING, CHECKING, INTERPRETING, CONTEXT, COMPLETE)

#: Steps that are not milestones and never appear in the skeleton: they are
#: added only where the turn actually took that path.
ROUTING = "routing"
CLARIFYING = "clarifying"
REFINING = "refining"
DEFERRED = "deferred"
FALLBACK = "fallback"
STOPPED_STEP = "stopped"

#: §5's mapping, and the only place these sentences are written.
LABELS: dict[str, str] = {
    UNDERSTANDING: "Understanding your question",
    SCOPING: "Resolving scope and intent",
    EVIDENCE: "Loading Early Warning evidence",
    OWNERSHIP: "Checking the right CreditProbe functionality",
    PLANNING: "Planning the investigation",
    VALIDATING: "Validating the analysis",
    ANALYSING: "Running Early Warning analysis",
    CHECKING: "Checking evidence and completeness",
    INTERPRETING: "Preparing risk interpretation",
    CONTEXT: "Updating conversation context",
    COMPLETE: "Analysis complete",
    ROUTING: "Routing to another CreditProbe functionality",
    CLARIFYING: "Clarification required",
    REFINING: "Refining the investigation plan",
    DEFERRED: "Additional drill-down deferred",
    FALLBACK: "Using governed Early Warning reader",
    STOPPED_STEP: "Analysis stopped",
}

#: The event a stage emits when it BEGINS, carrying the visible step it is
#: about to work on.
#:
#: Without it the panel would be blank for the first few seconds of every
#: turn: the pipeline's stage events are emitted when a stage FINISHES, and
#: the expensive part is what happens before that. A panel that can only show
#: completed work shows nothing at all while the work is being done, which is
#: the dead state this whole feature exists to remove.
#:
#: The alternative — guessing which stage comes next from the one that just
#: finished — was rejected. It is a prediction, and on the turns where the
#: pipeline branches (ownership going to another product, a plan that cannot
#: be repaired) the guess would put a step on screen that never ran.
STAGE_STARTED = "stage_started"

#: Which visible step each pipeline event belongs to. An event absent from
#: this map is an internal one the reader has no use for; it is dropped rather
#: than shown under a guessed label.
EVENT_STEPS: dict[str, str] = {
    "sonnet_pass_1": UNDERSTANDING,
    "sonnet_pass_2": SCOPING,
    "ews_context_built": EVIDENCE,
    "opus_functionality_selection": OWNERSHIP,
    "opus_analysis_plan": PLANNING,
    "validation": VALIDATING,
    "execution": ANALYSING,
    "result_packet": ANALYSING,
    "opus_sufficiency_review": CHECKING,
    "opus_final_interpretation": INTERPRETING,
    "sonnet_summary_update": CONTEXT,
    "thread_persisted": COMPLETE,
    "redirect_answer_created": ROUTING,
    "clarification_answer_created": CLARIFYING,
    "opus_plan_repair": REFINING,
    "execution_declined": DEFERRED,
    "stopped_honestly": STOPPED_STEP,
}

#: The names of the other CreditProbe functionalities, for the routing line.
#: Business names, because "what_if" is an identifier and What-If Analysis is
#: a product the reader has heard of.
PRODUCTS: dict[str, str] = {
    "early_warning": "Early Warning",
    "what_if": "What-If Analysis",
    "cockpit": "Portfolio Cockpit",
    "scorecard_validation": "Scorecard Validation",
    "data_builder": "Data Builder",
    "ask": "Ask CreditProbe",
}

# ---------------------------------------------------------------- substeps

#: §8's business descriptions of the governed analyses, so "Running Early
#: Warning analysis" becomes an investigation taking shape rather than a
#: spinner that lasts twenty seconds.
#:
#: Every one of these is NEUTRAL about what will be found. §9: the progress
#: text must not pre-judge the answer, because the turn is allowed to come
#: back and say the premise was wrong. "Checking movement over the selected
#: period" survives that; "Finding why Contracting deteriorated" does not, and
#: reads as a broken promise when the segment turns out to have improved.
ANALYSIS_LABELS: dict[str, str] = {
    "population": "Establishing the portfolio position",
    "movement": "Checking movement over the selected period",
    "layer": "Decomposing movement by intelligence layer",
    "diagnosis": "Diagnosing the main drivers",
    "grouping": "Identifying common warning characteristics",
    "concentration": "Testing concentration in high-risk obligors",
    "ranking": "Ranking the names driving the result",
    "borrower": "Reviewing borrower-level evidence",
    "evidence": "Reviewing underlying warning signals",
    "comparison": "Comparing the two periods",
    "methodology": "Reading the published methodology",
    "action": "Assembling the governed actions",
    "network": "Checking network and contagion evidence",
}

#: Groupings that are about the model's own nodes rather than about a
#: portfolio attribute, so the wording can say which. §8 asks for exactly this
#: distinction and it is the one case where the same analysis type deserves
#: two sentences.
_NODE_GROUPINGS: frozenset[str] = frozenset({
    "dominant_subcategory", "subcategory", "sub_category",
    "dominant_layer", "layer"})


def analysis_label(analysis: str, *, group_by: str = "",
                   scope: str = "") -> str:
    """The business sentence for one governed analysis.

    Scope-aware where the plan knows it: "Establishing the Contracting
    portfolio position" says more than the generic line and costs nothing,
    because the segment is already on the step the executor ran.
    """
    key = str(analysis or "").strip().lower()
    if key == "grouping" and str(group_by or "").lower() in _NODE_GROUPINGS:
        return "Identifying dominant warning sub-categories"
    label = ANALYSIS_LABELS.get(key)
    if label is None:
        # An analysis type this map has not been taught. Named plainly rather
        # than dropped — the reader should see that something ran — and
        # without inventing a description of what it does.
        return f"Running the {key.replace('_', ' ')} analysis" if key else \
            "Running a governed analysis"
    named = str(scope or "").strip()
    if named and key == "population":
        return f"Establishing the {named} portfolio position"
    return label


def product_name(selected: str) -> str:
    key = str(selected or "").strip().lower()
    return PRODUCTS.get(key, key.replace("_", " ").title() or "another product")


# ----------------------------------------------------------------- the shape


@dataclass
class Step:
    """One visible row of the progress panel. §21."""

    key: str
    label: str
    status: str = WAITING
    #: Milliseconds from the start of the turn to when this step began and
    #: ended. Both come from the pipeline's own event clock, so a duration on
    #: screen is a duration that was measured rather than one the browser
    #: guessed while it was not being told anything.
    started_ms: int | None = None
    completed_ms: int | None = None
    #: The governed analyses under "Running Early Warning analysis".
    substeps: list[Substep] = field(default_factory=list)
    #: Business-safe extras: a product name, a segment, a period. Never a
    #: model name, a token count, a schema error or a budget counter.
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_ms(self) -> int | None:
        if self.started_ms is None:
            return None
        if self.completed_ms is None:
            return None
        return max(0, self.completed_ms - self.started_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "status": self.status,
            "started_ms": self.started_ms, "completed_ms": self.completed_ms,
            "elapsed_ms": self.elapsed_ms,
            "substeps": [s.to_dict() for s in self.substeps],
            "detail": dict(self.detail),
        }


@dataclass
class Substep:
    """One governed analysis inside the execution step."""

    key: str
    label: str
    status: str = WAITING
    completed_ms: int | None = None
    rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "status": self.status,
                "completed_ms": self.completed_ms, "rows": self.rows}


@dataclass
class Progress:
    """The whole progress document for one turn. §21.

    Built by replaying the turn's events in order. Replaying rather than
    mutating as they arrive, because the same function then produces the live
    view during the turn and the historical view afterwards, and a reader who
    reopens a finished turn sees exactly what they saw while it ran.
    """

    turn_id: str = ""
    version: int = CONTRACT_VERSION
    sequence: int = 0
    steps: list[Step] = field(default_factory=list)
    #: Business-level facts about the turn, for the Details expander. §18.
    summary: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    active: bool = True
    #: Set once the turn has finished, whatever the outcome.
    outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id, "version": self.version,
            "sequence": self.sequence,
            "steps": [s.to_dict() for s in self.steps],
            "summary": dict(self.summary),
            "elapsed_ms": self.elapsed_ms,
            "active": self.active, "outcome": self.outcome,
            "completion_line": completion_line(self),
        }


# ------------------------------------------------------------------ building


def _scope_of(detail: dict[str, Any]) -> str:
    """A readable population name from a step's own filters."""
    filters = detail.get("filters")
    if isinstance(filters, dict):
        for key in ("sector", "segment", "industry", "region", "grade"):
            value = filters.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    scope = detail.get("scope")
    return scope.strip() if isinstance(scope, str) else ""


def build(events: list[Any], *, turn_id: str = "", active: bool = True,
          elapsed_ms: int = 0) -> Progress:
    """Replay a turn's events into the panel the reader sees.

    Replaying rather than mutating as events arrive, because the same function
    then produces the live view during the turn and the historical view
    afterwards — so a reader who reopens a finished turn sees exactly what
    they saw while it ran, rather than a second rendering that can disagree
    with the first.

    `events` are `pipeline.Event`s or their dictionaries: the API holds
    dictionaries and the tests hold objects, and both describe the same turn.
    """
    rows = [_as_dict(e) for e in events]
    progress = Progress(turn_id=turn_id, active=active,
                        sequence=len(rows), elapsed_ms=elapsed_ms)
    steps: dict[str, Step] = {}
    order: list[str] = []
    planned: list[Substep] = []
    last_ms = 0

    def touch(key: str, at_ms: int) -> Step:
        step = steps.get(key)
        if step is None:
            step = Step(key=key, label=LABELS.get(key, key), started_ms=at_ms)
            steps[key] = step
            order.append(key)
        if step.started_ms is None:
            step.started_ms = at_ms
        return step

    for event in rows:
        stage = str(event.get("stage") or "")
        detail = event.get("detail") or {}
        at_ms = int(event.get("at_ms") or 0)
        last_ms = max(last_ms, at_ms)

        # A stage announcing that it has BEGUN. This is what puts a step on
        # screen while the work is happening rather than after it.
        if stage == STAGE_STARTED:
            key = str(detail.get("step") or "")
            if key in LABELS:
                step = touch(key, at_ms)
                if step.status == WAITING:
                    step.status = ACTIVE
                # The whole plan, listed the moment execution begins rather
                # than appearing one analysis at a time. A reader watching an
                # empty "Running Early Warning analysis" for the length of the
                # first query cannot tell how much is coming; a list of six
                # with one ticked says it at a glance.
                if key == ANALYSING and not step.substeps and planned:
                    step.substeps = planned
            continue

        if stage == "opus_analysis_plan":
            # The plan names its analyses before any of them runs, so the
            # execution step can show the whole investigation as a list that
            # fills in — rather than one line that sits there for twenty
            # seconds and then says "done".
            planned = [
                Substep(key=str(name), label=analysis_label(str(name)))
                for name in (detail.get("steps") or [])]

        key = EVENT_STEPS.get(stage)
        if key is None:
            continue

        step = touch(key, at_ms)

        if key == ANALYSING and not step.substeps and planned:
            step.substeps = planned

        if stage == "redirect_answer_created":
            product = product_name(str(detail.get("to") or ""))
            step.label = f"Routing to {product}"
            step.detail["product"] = product
            step.status = DONE
            step.completed_ms = at_ms
            continue

        if stage == "opus_plan_repair":
            step.status = NOTE
            step.completed_ms = at_ms
            continue

        if stage == "execution_declined":
            step.status = NOTE
            step.completed_ms = at_ms
            # The governed reason belongs in the audit record, not on screen:
            # §11 is explicit that "6 of 6 execution budget exhausted" is not
            # a sentence for a credit officer.
            count = int(detail.get("count") or 0)
            if count:
                step.detail["deferred"] = count
            continue

        if stage == "clarification_answer_created":
            step.status = ACTIVE
            continue

        if stage == "stopped_honestly":
            step.status = STOPPED
            step.completed_ms = at_ms
            continue

        step.status = DONE
        step.completed_ms = at_ms

    _apply_executions(rows, steps)
    _apply_fallback(rows, steps, order, last_ms)
    _close(steps, order, last_ms, active=active)

    progress.steps = [steps[k] for k in order]
    progress.elapsed_ms = max(elapsed_ms, last_ms)
    progress.summary = _summary(rows)
    progress.outcome = _outcome(rows, progress)
    return progress


def _apply_fallback(rows: list[dict[str, Any]], steps: dict[str, Step],
                    order: list[str], last_ms: int) -> None:
    """§12's governed-reader note, where the answer was written without a model.

    Shown when the prose the reader is holding came from the deterministic
    Early Warning reader rather than from a model — either because no provider
    is configured or because the interpretation call did not land. It is a
    NOTE, never an error: the answer is a governed answer either way, and the
    reader is told which engine wrote it rather than being shown an HTTP
    status they cannot act on.
    """
    interpretation = next(
        (e for e in rows
         if str(e.get("stage") or "") == "opus_final_interpretation"), None)
    if interpretation is None:
        return
    engine = str((interpretation.get("detail") or {}).get("engine") or "")
    if engine == "model":
        return
    step = Step(key=FALLBACK, label=LABELS[FALLBACK], status=NOTE,
                started_ms=last_ms, completed_ms=last_ms)
    steps[FALLBACK] = step
    # Immediately after the interpretation step, so it reads as a note about
    # how the answer was written rather than as a separate phase of work.
    at = order.index(INTERPRETING) + 1 if INTERPRETING in order else len(order)
    order.insert(at, FALLBACK)


def _apply_executions(rows: list[dict[str, Any]],
                      steps: dict[str, Step]) -> None:
    """Tick each governed analysis off as its own event reported it.

    Matched by position within an analysis type rather than by name alone, so
    a plan carrying the same analysis twice ticks the right one.
    """
    step = steps.get(ANALYSING)
    if step is None:
        return
    seen: dict[str, int] = {}
    for event in rows:
        if str(event.get("stage") or "") != "execution_step":
            continue
        detail = event.get("detail") or {}
        name = str(detail.get("analysis") or "")
        nth = seen.get(name, 0)
        seen[name] = nth + 1
        target = _nth_substep(step.substeps, name, nth)
        if target is None:
            target = Substep(
                key=name,
                label=analysis_label(name,
                                     group_by=str(detail.get("group_by") or ""),
                                     scope=_scope_of(detail)))
            step.substeps.append(target)
        else:
            scope = _scope_of(detail)
            group_by = str(detail.get("group_by") or "")
            if scope or group_by:
                target.label = analysis_label(name, group_by=group_by,
                                              scope=scope)
        target.status = DONE if detail.get("ok") else NOTE
        target.completed_ms = int(event.get("at_ms") or 0)
        target.rows = int(detail.get("rows") or 0)


def _nth_substep(substeps: list[Substep], name: str,
                 nth: int) -> Substep | None:
    found = 0
    for candidate in substeps:
        if candidate.key != name:
            continue
        if found == nth:
            return candidate
        found += 1
    return None


def _close(steps: dict[str, Step], order: list[str], last_ms: int, *,
           active: bool) -> None:
    """Finish what the turn finished.

    The moment a turn ends nothing is left active — an indicator still beating
    beside a finished answer teaches the reader that the beat means nothing.
    A step that was still running when the turn stopped is closed at the
    turn's own last timestamp rather than being left open forever.

    While the turn is live this only reaches into the execution step: the
    analyses that have not reported yet are waiting, and the first of them is
    the one running. That is derived from the events that HAVE arrived, not
    from a clock.
    """
    if not active:
        for key in order:
            step = steps[key]
            if step.status in (WAITING, ACTIVE):
                step.status = DONE
                step.completed_ms = step.completed_ms or last_ms
            for substep in step.substeps:
                if substep.status in (WAITING, ACTIVE):
                    # Planned, never run — the ceiling or an earlier stop got
                    # there first. On a finished turn "waiting" would be a
                    # promise the turn is not going to keep, so it becomes a
                    # note, and its missing completion time is what keeps it
                    # out of the analyses count.
                    substep.status = NOTE
        return
    running = next((steps[k] for k in reversed(order)
                    if steps[k].status == ACTIVE), None)
    if running is None:
        return
    for substep in running.substeps:
        if substep.status == WAITING:
            substep.status = ACTIVE
            break


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """§18's Details block. Business facts only.

    Everything here is something a credit officer could sensibly ask about:
    which product answered, over what population and period, how many
    analyses ran, whether the evidence check passed. No model, no provider, no
    tokens, no budget counters — those stay on the audit trail, which is where
    an administrator already reads them.
    """
    out: dict[str, Any] = {}
    analyses = 0
    for event in rows:
        stage = str(event.get("stage") or "")
        detail = event.get("detail") or {}
        if stage == "request_started":
            out["mode"] = "Deep" if str(detail.get("mode")) == "deep" \
                else "Standard"
        elif stage == "opus_functionality_selection":
            out["functionality"] = product_name(str(detail.get("selected") or ""))
        elif stage == "execution_step":
            if detail.get("ok"):
                analyses += 1
            # The population and the period the analyses actually ran over,
            # read off the steps that ran rather than off the request. A
            # reader checking the Details wants to know what was analysed,
            # not what was asked for — those are the same thing until a
            # period is unpublished or a filter is normalised away.
            out.setdefault("scope", _scope_of(detail))
            period = str(detail.get("period") or "")
            earlier = str(detail.get("comparison_period") or "")
            if period:
                out["period"] = (f"{earlier} \u2192 {period}"
                                 if earlier and earlier != period else period)
        elif stage == "execution_declined":
            out["deferred"] = int(detail.get("count") or 0)
        elif stage == "opus_sufficiency_review":
            out["evidence_check"] = "Passed" if detail.get("complete") \
                else "Partial"
    if analyses:
        out["analyses"] = analyses
    if not out.get("scope"):
        out.pop("scope", None)
    return out


def _outcome(rows: list[dict[str, Any]], progress: Progress) -> str:
    stages = {str(e.get("stage") or "") for e in rows}
    if progress.active:
        return ""
    if "redirect_answer_created" in stages:
        return "redirected"
    if "clarification_answer_created" in stages:
        return "clarification"
    if "stopped_honestly" in stages:
        return "stopped"
    if "thread_persisted" in stages:
        return "complete"
    return ""


def _as_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    to_dict = getattr(event, "to_dict", None)
    return to_dict() if callable(to_dict) else {}


# ------------------------------------------------------------ the last line


def seconds(ms: int | None) -> str:
    """Elapsed time at the precision a reader can use.

    One decimal under a minute — 31.8s is a number somebody reads as "about
    half a minute" — then whole minutes and seconds. Milliseconds imply a
    precision nobody needs and change too fast to read.
    """
    if not ms or ms < 0:
        return ""
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    total = ms // 1000
    rest = total % 60
    return f"{total // 60}m {rest}s" if rest else f"{total // 60}m"


def completion_line(progress: Progress) -> str:
    """§17's collapsed bar: what happened, in one line.

    "Analysed in 31.8s · 6 analyses · evidence checked", and the variants for
    a redirect, a deferred drill-down and the governed reader.
    """
    if progress.active:
        return ""
    time = seconds(progress.elapsed_ms)
    parts: list[str] = [f"Analysed in {time}" if time else "Analysed"]
    summary = progress.summary

    if progress.outcome == "redirected":
        routed = next((s for s in progress.steps if s.key == ROUTING), None)
        product = str((routed.detail if routed else {}).get("product") or "")
        parts.append(f"routed to {product}" if product
                     else "routed to another functionality")
        return " · ".join(parts)

    if progress.outcome == "clarification":
        parts.append("clarification needed")
        return " · ".join(parts)

    if progress.outcome == "stopped":
        parts.append("stopped — see the answer for why")
        return " · ".join(parts)

    count = int(summary.get("analyses") or 0)
    if count:
        parts.append(f"{count} analys{'es' if count != 1 else 'is'}")
    if any(s.key == FALLBACK for s in progress.steps):
        parts.append("governed Early Warning reader")
    check = str(summary.get("evidence_check") or "")
    if check == "Passed":
        parts.append("evidence checked")
    elif check == "Partial":
        parts.append("evidence checked · some limitations remain")
    deferred = int(summary.get("deferred") or 0)
    if deferred:
        parts.append("additional drill-down deferred")
    return " · ".join(parts)


__all__ = [
    "ACTIVE", "ANALYSING", "ANALYSIS_LABELS", "CHECKING", "CLARIFYING",
    "COMPLETE", "CONTEXT", "CONTRACT_VERSION", "DEFERRED", "DONE",
    "EVENT_STEPS", "EVIDENCE", "FALLBACK", "INTERPRETING", "LABELS", "NOTE",
    "OWNERSHIP", "PLANNING", "PRODUCTS", "Progress", "REFINING", "ROUTING",
    "SCOPING", "STEP_ORDER", "STOPPED", "STOPPED_STEP", "Step", "Substep",
    "UNDERSTANDING", "VALIDATING", "WAITING", "analysis_label", "build",
    "completion_line", "product_name", "seconds",
]
