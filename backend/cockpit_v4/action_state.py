"""Which action the run is ALLOWED to take next, and who decides.

The division of labour
----------------------
CreditProbe knows the orchestration STATE: whether metadata is resolved,
whether a result exists, which book is open. Opus owns the analytical
CONTENT: which measure, which aggregation, which filters, which comparison,
what the numbers mean.

Those were mixed. Every action turn was offered every tool and asked to
choose among them -- including tools that could not legally do anything in
the state the run was actually in. A run with nothing executed was offered
`finalize_response`; a run whose governed metadata was fully resolved was
offered `inspect_catalog`; an analytical run was offered product knowledge.

The live failure that made this unavoidable
-------------------------------------------
run-62282e6be0ca48c5a4afdd3c468e3de8, "What is driving Stage 2 and ECL
growth?", Corporate, 120-second allowance:

    0.137s  first action generation starts
   28.303s  rejected: output_truncated -- no complete tool call
   28.3xx   recovery generation starts, WITH A BROADER TOOL SURFACE
            ("Product knowledge lookup available.")
   55.918s  failed: the one re-ask for a complete action was spent

2 of 12 generations. 0 of 5 executions. 0 of 4 catalogue calls. $0.34 of
$1.50. 64 seconds left. Nothing was exhausted except the re-ask, and the
re-ask was spent asking a harder question than the one that had just
failed.

`tool_choice: {"type": "any"}` was not enough. It requires SOME tool call;
it does not narrow WHAT the turn has to consider. With five tools on the
table and an answer contract among them, "any" still means "read all of
this, then decide" -- and the deciding is what ran out of output.

What this module does, and does not
-----------------------------------
It decides which tools are on the request and which one the provider is
told to call. It decides nothing about the analysis: not the relation, not
the measure, not the aggregation, not the periods, not the filters, not the
interpretation. `execute_analysis` is required in a state where executing
is the only legal transition -- WHAT to execute is entirely the analyst's,
and there is no code here that writes SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v4.contracts import (TOOL_EXECUTE, TOOL_FINALIZE,
                                          TOOL_INSPECT, TOOL_PRODUCT,
                                          TOOL_READ)

#: The catalogue is not resolved for this question. The only useful action
#: is to ask for the field facts that are missing.
NEEDS_METADATA = "NEEDS_METADATA"
#: Everything a query needs is already in the packet. The only legal
#: transition is to run one.
READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
#: A validated result exists, or an answer has been refused and is being
#: corrected. The only legal transition is to publish.
RESULT_READY = "RESULT_READY"
#: Not an analytical turn at all.
PRODUCT_HELP = "PRODUCT_HELP"

STATES = (NEEDS_METADATA, READY_FOR_EXECUTION, RESULT_READY, PRODUCT_HELP)

#: What a reader is told each state is doing. No internals.
PUBLIC: dict[str, str] = {
    NEEDS_METADATA: "Reading the field definitions this question needs",
    READY_FOR_EXECUTION: "Preparing the query",
    RESULT_READY: "Writing the answer from the result",
    PRODUCT_HELP: "Answering from CreditProbe's product knowledge",
}


@dataclass(frozen=True)
class Decision:
    """The surface for ONE turn: what is offered, and what is required."""

    state: str
    #: Tool names, in contract order. Everything else is off the request.
    tools: tuple[str, ...]
    #: The tool the provider is told to call, or "" for "any of the above".
    require: str = ""
    #: Why this state, in one line, for the trace.
    because: str = ""
    #: True when this turn is a re-ask after a malformed one. A recovery may
    #: only ever NARROW: see `narrow`.
    recovering: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def stage(self) -> str:
        return PUBLIC.get(self.state, "Preparing the next action")

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "tools": list(self.tools),
                "require": self.require, "because": self.because,
                "recovering": self.recovering, **self.detail}

    def narrow(self) -> "Decision":
        """The same state, as a RECOVERY.

        A re-ask after a malformed action must never be a broader question
        than the one that failed. The live run restored a withheld tool
        between the two attempts, so the turn that had just run out of
        output while deciding was asked to decide among MORE things.

        Where the state already requires one tool there is nothing left to
        take away, and this only records that the turn is a recovery. Where
        it does not -- product help -- the surface is held at what it was.
        """
        return Decision(state=self.state, tools=self.tools,
                        require=self.require, because=self.because,
                        recovering=True, detail=dict(self.detail))


def decide(*, executed: bool, answer_only: bool, analytical: bool,
           readiness: dict[str, Any] | None,
           product_tool_withheld: bool = False) -> Decision:
    """The state this run is in, and the one action it may take.

    `readiness` is `semantics.readiness`: a deterministic, server-side
    statement about whether the governed metadata for THIS question is
    already in the packet. It is computed before any model call and it
    names no method.
    """
    ready = dict(readiness or {})
    if executed or answer_only:
        return Decision(
            state=RESULT_READY, tools=(TOOL_FINALIZE,),
            require=TOOL_FINALIZE,
            because=("a validated result exists, so the only thing left to "
                     "do with it is publish an answer"))

    if not analytical:
        tools = ((TOOL_FINALIZE,) if product_tool_withheld
                 else (TOOL_PRODUCT, TOOL_FINALIZE))
        return Decision(
            state=PRODUCT_HELP, tools=tools,
            require=TOOL_FINALIZE if product_tool_withheld else "",
            because=("a product question: the synopsis in the opening "
                     "context already covers it"
                     if product_tool_withheld else
                     "a product question that names detail beyond the "
                     "synopsis"))

    if ready.get("sufficient"):
        return Decision(
            state=READY_FOR_EXECUTION, tools=(TOOL_EXECUTE,),
            require=TOOL_EXECUTE,
            because=("every field fact this question needs is already "
                     "resolved in the opening packet"),
            detail={"resolved_measures": [
                m.get("term") for m in
                (ready.get("governed_measures_already_resolved") or [])][:8]})

    return Decision(
        state=NEEDS_METADATA, tools=(TOOL_INSPECT,), require=TOOL_INSPECT,
        because=("something this question names is not resolved in the "
                 "opening packet"),
        detail={"unresolved": (ready.get("terms_still_needing_a_decision")
                               or ready.get("values_still_ambiguous") or [])})


def after_catalog(previous: Decision, readiness: dict[str, Any] | None
                  ) -> Decision:
    """Where a run goes once it has read what it asked the catalogue for.

    NEEDS_METADATA is not a place a run stays. It read the field facts it
    said were missing; the next legal transition is to use them. A run that
    could ask the catalogue again and again is the run that died having
    read it twice and answered nothing.
    """
    if previous.state != NEEDS_METADATA:
        return previous
    return Decision(
        state=READY_FOR_EXECUTION, tools=(TOOL_EXECUTE,),
        require=TOOL_EXECUTE,
        because=("the field facts this question was missing have now been "
                 "read"),
        detail={"after": NEEDS_METADATA})


#: Tools that may be BATCHED alongside the required one, because they are
#: reads with no side effects and the contract already allows batching them.
#: `read_artifact` is here so a run that stored a large result can fetch a
#: page of it without a state change.
COMPANIONS: dict[str, tuple[str, ...]] = {
    RESULT_READY: (TOOL_READ,),
}


def offered(decision: Decision) -> tuple[str, ...]:
    """Every tool name on the request for this turn, in contract order."""
    names = list(decision.tools)
    for extra in COMPANIONS.get(decision.state, ()):
        if extra not in names:
            names.append(extra)
    order = (TOOL_INSPECT, TOOL_PRODUCT, TOOL_EXECUTE, TOOL_READ,
             TOOL_FINALIZE)
    return tuple(name for name in order if name in names)


__all__ = ["COMPANIONS", "Decision", "NEEDS_METADATA", "PRODUCT_HELP",
           "PUBLIC", "READY_FOR_EXECUTION", "RESULT_READY", "STATES",
           "after_catalog", "decide", "offered"]
