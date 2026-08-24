"""
Controlled Trace modification — changing an analysis without losing it.

A user reading a Trace says "exclude Real Estate" or "use borrower count instead
of exposure". That is a request to change the *plan*, not the graph: the graph is
a record of what happened and is never edited. So a modification is applied like
this:

    request text
        -> interpreted into ONE supported operation
        -> applied to the stored plan, producing a NEW plan
        -> validated exactly as a fresh plan would be
        -> PREVIEWED: which steps change, which nodes that affects,
                      and what runs downstream of them
        -> only on explicit confirmation: executed, with unchanged steps
           reusing their recorded results
        -> stored as a NEW version. The original is untouched and can be
           reopened at any time.

Why the operation list is closed
--------------------------------
The supported operations are enumerated below and nothing else is possible. A
free-text instruction cannot introduce a new filter dimension, a new data source,
or a new calculation, because there is no operation that does any of those. This
is the same principle as the plan contract: the model chooses among things CreditProbe
already knows how to do, and the choice is validated before it runs.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from backend.engine.registry import get_registry
from backend.orchestration.executor import (
    ExecutedStep,
    Investigation,
    assemble,
    execute_plan,
)
from backend.orchestration.planner import planner_mode
from backend.orchestration.schema import MAX_PLAN_STEPS, AnalysisPlan, PlanRejected, PlanStep
from backend.orchestration.validator import validate_plan
from backend.orchestration.vocabulary import Vocabulary, get_vocabulary

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- operations


@dataclass(frozen=True)
class Operation:
    """One supported change, already resolved against the governed vocabulary."""

    kind: str
    # Everything the applier needs. Contents depend on `kind`; every value here
    # has already been checked against real data or a real contract.
    payload: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "payload": self.payload, "description": self.description}


SUPPORTED_OPERATIONS = [
    {"kind": "only", "label": "Restrict to one group",
     "example": "Only show Real Estate."},
    {"kind": "exclude", "label": "Exclude one group",
     "example": "Exclude Real Estate."},
    {"kind": "clear_filters", "label": "Remove the filters",
     "example": "Remove this filter."},
    {"kind": "set_basis", "label": "Change the measurement basis",
     "example": "Use borrower count instead of EAD."},
    {"kind": "set_period", "label": "Compare against a different period",
     "example": "Compare against a different reporting period."},
    {"kind": "add_analysis", "label": "Add an analysis",
     "example": "Add ECL Movement."},
    {"kind": "remove_analysis", "label": "Remove an analysis",
     "example": "Remove Sector Concentration."},
    {"kind": "set_scenario", "label": "Change the stress scenario",
     "example": "Use the severe scenario."},
    {"kind": "set_top_n", "label": "Change how many rows are returned",
     "example": "Show the top 20 instead."},
]


# ------------------------------------------------------------ interpretation


def _analysis_index() -> dict[str, str]:
    """Every runnable analysis, keyed by normalised name and id."""
    index: dict[str, str] = {}
    for item in get_registry().runnable():
        contract = item.contract
        index[_norm(contract.name)] = contract.id
        index[_norm(contract.id)] = contract.id
    return index


def _norm(text: str) -> str:
    """Lower-case, punctuation-free words — see vocabulary._normalise."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def _find_analysis(text: str) -> str | None:
    """Longest-name-first match, so "ECL Movement" is not shadowed by "ECL"."""
    haystack = " " + _norm(text) + " "
    best, best_len = None, 0
    for name, analysis_id in _analysis_index().items():
        if f" {name} " in haystack and len(name) > best_len:
            best, best_len = analysis_id, len(name)
    return best


def _find_period(text: str, vocab: Vocabulary) -> str | None:
    for period in sorted(vocab.periods, key=len, reverse=True):
        if _norm(period) in _norm(text):
            return period
    return None


def interpret(request: str, plan: AnalysisPlan,
              vocab: Vocabulary | None = None) -> Operation | None:
    """Read a modification request as one supported operation, or nothing.

    Order matters. "Remove this filter" and "Remove Sector Concentration" both
    begin with "remove"; the filter reading is tried first because it is the more
    specific phrase. Returning None is a real answer — an instruction CreditProbe cannot
    carry out is reported as such rather than approximated.
    """
    vocab = vocab or get_vocabulary()
    text = request.strip()
    lowered = _norm(text)
    if not lowered:
        return None

    # --- remove the filters -------------------------------------------------
    if re.search(r"(remove|drop|clear|delete)\s+(this|the|all|any)?\s*filters?", lowered) or \
       re.search(r"(no filters?|unfiltered|whole (book|portfolio)|show (me )?everything)", lowered):
        return Operation("clear_filters", {},
                         "Remove every filter and run against the whole portfolio.")

    # --- measurement basis --------------------------------------------------
    wants_count = re.search(r"(borrower count|by count|number of borrowers|count basis|"
                            r"count instead)", lowered)
    wants_ead = re.search(r"(\bead\b|exposure basis|by exposure|exposure instead|"
                          r"amount instead)", lowered)
    if wants_count and not (wants_ead and lowered.find("ead") < lowered.find("count")):
        return Operation("set_basis", {"basis": "count"},
                         "Measure on borrower count rather than exposure.")
    if wants_ead and re.search(r"use|switch|instead|rather", lowered):
        return Operation("set_basis", {"basis": "ead"},
                         "Measure on exposure (EAD) rather than borrower count.")

    # --- stress scenario ----------------------------------------------------
    scenario = re.search(r"\b(base|mild|moderate|severe)\b", lowered)
    if scenario and re.search(r"scenario|stress|shock|downturn|severity", lowered):
        return Operation("set_scenario", {"scenario": scenario.group(1)},
                         f"Apply the {scenario.group(1)} scenario instead.")

    # --- how many rows ------------------------------------------------------
    top = re.search(r"top\s*(\d+)", lowered)
    if top and re.search(r"top|show|instead|only", lowered):
        n = max(1, min(100, int(top.group(1))))
        return Operation("set_top_n", {"top_n": n}, f"Return the top {n} instead.")

    # --- reporting period ---------------------------------------------------
    named_period = _find_period(text, vocab)
    if named_period:
        return Operation("set_period", {"period": named_period},
                         f"Compare against {named_period} instead.")
    if re.search(r"(different|another|earlier|previous|prior) (reporting )?period|"
                 r"compare (against|to|with) a different", lowered):
        # No period named. Step back one further than the current comparison —
        # a real period from the catalogue, never an invented label.
        candidate = vocab.periods[-3] if len(vocab.periods) >= 3 else vocab.earliest
        if candidate:
            return Operation("set_period", {"period": candidate},
                             f"Compare against {candidate} instead of the prior period.")

    # --- add or remove an analysis -----------------------------------------
    if re.search(r"\b(add|also|include|append|bring in)\b", lowered):
        analysis_id = _find_analysis(text)
        if analysis_id:
            name = get_registry().contract(analysis_id).name
            return Operation("add_analysis", {"analysis_id": analysis_id},
                             f"Add {name} to the investigation.")
    if re.search(r"\b(remove|drop|delete|exclude|without)\b", lowered):
        analysis_id = _find_analysis(text)
        if analysis_id:
            name = get_registry().contract(analysis_id).name
            return Operation("remove_analysis", {"analysis_id": analysis_id},
                             f"Remove {name} from the investigation.")

    # --- restrict to, or exclude, a governed value -------------------------
    hit = vocab.resolve_dimension_value(text)
    if hit:
        dimension, value = hit
        label = dimension.replace("_", " ")
        if re.search(r"\b(only|just|restrict|limit|solely|nothing but)\b", lowered):
            return Operation("only", {"dimension": dimension, "value": value},
                             f"Restrict every step to {label} = {value}.")
        if re.search(r"\b(exclude|without|except|remove|drop|strip|ignore|excluding)\b", lowered):
            others = vocab.other_values(dimension, value)
            if not others:
                return None
            return Operation("exclude",
                             {"dimension": dimension, "value": value, "keep": others},
                             f"Exclude {value}, keeping the other "
                             f"{len(others)} {label} groups.")
        # A bare mention with no verb is read as a restriction, which is what
        # "Real Estate" typed into the box almost always means.
        return Operation("only", {"dimension": dimension, "value": value},
                         f"Restrict every step to {label} = {value}.")

    return None


# --------------------------------------------------------------- application

# Parameters that carry a measurement basis, a period, or a row limit, by name.
BASIS_PARAM = "basis"
TOP_N_PARAMS = ("top_n",)
FROM_PERIOD_PARAMS = ("from_period", "compare_period")


def _contract_params(analysis_id: str) -> set[str]:
    try:
        return {p.name for p in get_registry().contract(analysis_id).parameters}
    except Exception:
        return set()


def _default_step(analysis_id: str, filters: dict[str, Any]) -> PlanStep:
    """A newly added analysis, with parameters taken from its own contract."""
    contract = get_registry().contract(analysis_id)
    params: dict[str, Any] = {}
    for parameter in contract.parameters:
        if parameter.default is not None:
            params[parameter.name] = parameter.default
    return PlanStep(
        analysis_id=analysis_id,
        title=contract.name,
        rationale=f"Added on request. {contract.description}",
        params=params,
        filters=dict(filters),
    )


def apply_operation(operation: Operation, plan: AnalysisPlan) -> AnalysisPlan:
    """Produce the modified plan. Pure — the original plan is not touched."""
    steps = list(plan.steps)
    kind, payload = operation.kind, operation.payload

    if kind == "clear_filters":
        steps = [s.with_filters({}) for s in steps]
        # A sector supplied as a stress parameter is a filter in every sense
        # that matters to the reader, so it is cleared too.
        steps = [
            s.with_params(sector=None) if "sector" in _contract_params(s.analysis_id) else s
            for s in steps
        ]

    elif kind == "only":
        dimension, value = payload["dimension"], payload["value"]
        out = []
        for step in steps:
            if dimension == "sector" and "sector" in _contract_params(step.analysis_id):
                out.append(step.with_params(sector=value))
            else:
                out.append(step.with_filters({**step.filters, dimension: value}))
        steps = out

    elif kind == "exclude":
        dimension, keep = payload["dimension"], payload["keep"]
        out = []
        for step in steps:
            merged = {**step.filters, dimension: keep}
            step = step.with_filters(merged)
            if dimension == "sector" and "sector" in _contract_params(step.analysis_id):
                # The stress function takes a single sector, so an exclusion is
                # expressed by clearing it and filtering instead.
                step = step.with_params(sector=None)
            out.append(step)
        steps = out

    elif kind == "set_basis":
        basis = payload["basis"]
        steps = [
            s.with_params(basis=basis) if BASIS_PARAM in _contract_params(s.analysis_id) else s
            for s in steps
        ]

    elif kind == "set_scenario":
        scenario = payload["scenario"]
        steps = [
            s.with_params(scenario=scenario)
            if "scenario" in _contract_params(s.analysis_id) else s
            for s in steps
        ]

    elif kind == "set_top_n":
        n = payload["top_n"]
        steps = [
            s.with_params(top_n=n) if "top_n" in _contract_params(s.analysis_id) else s
            for s in steps
        ]

    elif kind == "set_period":
        period = payload["period"]
        out = []
        for step in steps:
            available = _contract_params(step.analysis_id)
            changes = {p: period for p in FROM_PERIOD_PARAMS if p in available}
            out.append(step.with_params(**changes) if changes else step)
        steps = out

    elif kind == "add_analysis":
        analysis_id = payload["analysis_id"]
        if not any(s.analysis_id == analysis_id for s in steps):
            filters = steps[0].filters if steps else {}
            steps = [*steps, _default_step(analysis_id, filters)][:MAX_PLAN_STEPS]

    elif kind == "remove_analysis":
        analysis_id = payload["analysis_id"]
        steps = [s for s in steps if s.analysis_id != analysis_id]

    return plan.replace_steps(steps)


# ------------------------------------------------------------------ preview


@dataclass
class ProposedChange:
    """What a modification would do, shown before anything is re-run."""

    request: str
    understood: bool
    operation: Operation | None
    description: str
    current_plan: AnalysisPlan
    proposed_plan: AnalysisPlan
    changed_steps: list[dict[str, Any]] = field(default_factory=list)
    added_steps: list[dict[str, Any]] = field(default_factory=list)
    removed_steps: list[dict[str, Any]] = field(default_factory=list)
    unchanged_steps: list[dict[str, Any]] = field(default_factory=list)
    # Node ids on the current graph that this change invalidates.
    affected_nodes: list[str] = field(default_factory=list)
    downstream_nodes: list[str] = field(default_factory=list)
    unaffected_nodes: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    supported: list[dict[str, str]] = field(default_factory=lambda: list(SUPPORTED_OPERATIONS))

    @property
    def has_effect(self) -> bool:
        return bool(self.changed_steps or self.added_steps or self.removed_steps)

    @property
    def applicable(self) -> bool:
        return self.understood and not self.rejected and self.has_effect

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "understood": self.understood,
            "applicable": self.applicable,
            "operation": self.operation.to_dict() if self.operation else None,
            "description": self.description,
            "current_plan": self.current_plan.to_dict(),
            "proposed_plan": self.proposed_plan.to_dict(),
            "changed_steps": self.changed_steps,
            "added_steps": self.added_steps,
            "removed_steps": self.removed_steps,
            "unchanged_steps": self.unchanged_steps,
            "affected_nodes": self.affected_nodes,
            "downstream_nodes": self.downstream_nodes,
            "unaffected_nodes": self.unaffected_nodes,
            "rejected": self.rejected,
            "supported": self.supported,
        }


# Which contract parameter each operation targets, where it targets one.
OPERATION_PARAM = {
    "set_basis": ("basis", "measures on a choice of basis"),
    "set_top_n": ("top_n", "returns a ranked list you can shorten or lengthen"),
    "set_scenario": ("scenario", "applies a stress scenario"),
}


def _why_no_effect(operation: Operation, plan: AnalysisPlan) -> str:
    """Explain, in the user's terms, why a change would do nothing."""
    kind = operation.kind

    target = OPERATION_PARAM.get(kind)
    if target:
        parameter, phrasing = target
        if not any(parameter in _contract_params(s.analysis_id) for s in plan.steps):
            return (
                f"None of the analyses in this investigation {phrasing}, so there is "
                "nothing to change."
            )
        return "The analyses already use that setting, so nothing would change."

    if kind == "clear_filters":
        return "This investigation has no filters applied, so there is nothing to remove."
    if kind == "add_analysis":
        return "It is already part of this investigation."
    if kind == "remove_analysis":
        return "It is not part of this investigation."
    if kind == "set_period":
        return "The analyses already compare against that period."
    return "This investigation already does that, so nothing would change."


def _step_signature(step: PlanStep) -> str:
    import json

    return json.dumps({"a": step.analysis_id, "p": step.params, "f": step.filters,
                       "d": step.period}, sort_keys=True, separators=(",", ":"), default=str)


def _describe(step: PlanStep, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "analysis_id": step.analysis_id,
        "title": step.title or step.analysis_id,
        "params": step.params,
        "filters": step.filters,
    }


def _nodes_for_steps(graph: dict[str, Any], step_numbers: set[int]) -> list[str]:
    """Node ids belonging to the given plan steps.

    The step number is written onto every node when the reasoning map is built,
    so this is a lookup rather than a guess about which node came from where.
    """
    out = []
    for node in graph.get("nodes") or []:
        step = (node.get("config") or {}).get("_step")
        if isinstance(step, int) and step in step_numbers:
            out.append(str(node.get("id")))
    return out


def preview(request: str, plan: AnalysisPlan, graph: dict[str, Any],
            vocab: Vocabulary | None = None) -> ProposedChange:
    """Work out what a request would change, without running anything."""
    vocab = vocab or get_vocabulary()
    operation = interpret(request, plan, vocab)

    if operation is None:
        return ProposedChange(
            request=request, understood=False, operation=None,
            description=(
                "CreditProbe did not recognise that as a change it can make to this analysis. "
                "The changes it supports are listed below."
            ),
            current_plan=plan, proposed_plan=plan,
        )

    proposed = apply_operation(operation, plan)

    rejected: list[str] = []
    try:
        validate_plan(proposed, vocab)
    except PlanRejected as rejection:
        rejected = rejection.reasons

    before = {_step_signature(s): i for i, s in enumerate(plan.steps)}
    before_ids = [s.analysis_id for s in plan.steps]

    changed, added, unchanged = [], [], []
    changed_numbers: set[int] = set()
    for index, step in enumerate(proposed.steps):
        signature = _step_signature(step)
        if signature in before:
            unchanged.append(_describe(step, index))
            continue
        if step.analysis_id in before_ids:
            described = _describe(step, index)
            original_index = before_ids.index(step.analysis_id)
            described["was"] = _describe(plan.steps[original_index], original_index)
            changed.append(described)
            changed_numbers.add(original_index + 1)
        else:
            added.append(_describe(step, index))

    after_ids = [s.analysis_id for s in proposed.steps]
    removed = [
        _describe(step, index)
        for index, step in enumerate(plan.steps)
        if step.analysis_id not in after_ids
    ]
    removed_numbers = {index + 1 for index, step in enumerate(plan.steps)
                       if step.analysis_id not in after_ids}

    affected = _nodes_for_steps(graph, changed_numbers | removed_numbers)
    # The plan and the narrative always re-derive: the plan because it lists the
    # steps, the narrative because it quotes their figures.
    downstream = [n for n in ("plan", "narrative")
                  if any(x.get("id") == n for x in graph.get("nodes") or [])]
    all_ids = [str(n.get("id")) for n in graph.get("nodes") or []]
    unaffected = [n for n in all_ids if n not in set(affected) | set(downstream)]

    description = operation.description
    if not (changed or added or removed) and not rejected:
        # An instruction that would change nothing is understood but pointless.
        # Saying *why* it would change nothing is what separates a useful refusal
        # from a shrug: "nothing here measures on a basis" and "it already does
        # that" send the reader to different next steps.
        description = f"{operation.description} {_why_no_effect(operation, plan)}"

    return ProposedChange(
        request=request, understood=True, operation=operation,
        description=description,
        current_plan=plan, proposed_plan=proposed,
        changed_steps=changed, added_steps=added, removed_steps=removed,
        unchanged_steps=unchanged,
        affected_nodes=affected, downstream_nodes=downstream, unaffected_nodes=unaffected,
        rejected=rejected,
    )


# -------------------------------------------------------------------- apply


def apply_modification(plan: AnalysisPlan, previous_steps: list[ExecutedStep],
                       change: ProposedChange, *, user_id: int | None = None) -> Investigation:
    """Execute the modified plan, reusing every step that did not change."""
    started = time.perf_counter()
    proposed = validate_plan(change.proposed_plan)
    steps = execute_plan(proposed, user_id=user_id, previous=previous_steps)
    return assemble(proposed, steps,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    mode=planner_mode())


__all__ = [
    "SUPPORTED_OPERATIONS",
    "Operation",
    "ProposedChange",
    "apply_modification",
    "apply_operation",
    "interpret",
    "preview",
]
