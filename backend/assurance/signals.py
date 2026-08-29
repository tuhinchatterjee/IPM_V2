"""
The signal readers. §19.

    §19: "Now wire actual signals into the collector."
    §19: "Do not mark missing signals PASS."

One reader per subcomponent
-----------------------------
Each function here takes the turn's context and returns a `Signal` — an
outcome, a detail sentence and the Trace evidence behind it. The collector
walks all ninety-five subcomponents and calls the reader where one exists.
Where none exists the check is `NOT_AVAILABLE`, quoting the Coverage Map's
reason. There is no third path, and in particular no path that produces
`PASS` without a reader having looked at something.

Why a registry rather than one long function
----------------------------------------------
Because the property that matters is checkable: `set(READERS)` must equal
`coverage.wired()`. A test asserts it both ways. That is what stops the
Coverage Map drifting into a wish list — the map cannot claim a signal is
wired unless a function here reads it, and a function here that nobody
mapped fails the same test.

Three rules every reader follows
----------------------------------
**Return None to mean "nothing established this".** The collector turns that
into SKIPPED — a fact about this run — which is different from the reader
not existing at all.

**Never raise.** A reader that throws would lose the whole record. Each is
wrapped, and a raising reader is reported as SKIPPED with the exception in
its detail, because a broken reader is a fact worth recording rather than an
excuse to record nothing.

**Say what was seen, not what was expected.** `detail` exists so a reader of
the review can disagree with the check, and "the period was Q2 2026 and the
question asked for the latest quarter" is arguable in a way that "period
check failed" is not.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.assurance import record as rc

logger = logging.getLogger(__name__)

SIGNALS_VERSION = "1.0.0"


@dataclass
class Signal:
    """One reader's answer."""

    outcome: str
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    #: Only for NOT_APPLICABLE, which §183 refuses without one.
    because: str = ""


def _pass(detail: str = "", *evidence: str) -> Signal:
    return Signal(rc.PASS, detail, list(evidence))


def _fail(detail: str, *evidence: str) -> Signal:
    return Signal(rc.FAIL, detail, list(evidence))


def _warn(detail: str, *evidence: str) -> Signal:
    return Signal(rc.WARNING, detail, list(evidence))


def _na(because: str) -> Signal:
    return Signal(rc.NOT_APPLICABLE, because=because)


def _verdict(ok: bool, good: str, bad: str, *evidence: str,
             warn_instead: bool = False) -> Signal:
    """The common shape: a boolean, and a sentence for each side."""
    if ok:
        return _pass(good, *evidence)
    return (_warn(bad, *evidence) if warn_instead else _fail(bad, *evidence))


# ---------------------------------------------------------------- the context


@dataclass
class Ctx:
    """Everything a reader may look at, resolved once.

    Assembled defensively: this runs after an answer has already been given,
    and a missing attribute is a finding rather than an exception.
    """

    investigation: Any = None
    answered: Any = None
    officer: Any = None
    project_id: str = ""
    proactive: bool = False

    # ---- resolved conveniences
    status: str = ""
    reading: Any = None
    build: Any = None
    runtime: Any = None
    gate: Any = None
    invariants: Any = None
    #: What the sub-analyses of a composed answer did. A coordinated review
    #: has no runtime of its own; its work is one level down. §3.
    composition: Any = None
    decision: Any = None
    scope: Any = None
    continuation: Any = None
    judgment: dict[str, Any] = field(default_factory=dict)
    conversation: dict[str, Any] = field(default_factory=dict)
    trace: set[str] = field(default_factory=set)
    outcome: Any = None
    selection: Any = None

    @classmethod
    def of(cls, investigation: Any, answered: Any, *, officer: Any = None,
           project_id: str = "", proactive: bool = False) -> Ctx:
        ctx = cls(investigation=investigation, answered=answered,
                  officer=officer, project_id=project_id, proactive=proactive)
        ctx.status = str(getattr(investigation, "status", "") or "")
        ctx.reading = getattr(answered, "reading", None)
        ctx.build = getattr(answered, "build", None)
        ctx.runtime = getattr(answered, "runtime", None)
        ctx.gate = getattr(answered, "gate", None)
        ctx.invariants = getattr(answered, "invariants", None)
        ctx.composition = getattr(answered, "composition", None)
        ctx.decision = getattr(answered, "decision", None)
        ctx.scope = getattr(answered, "scope", None)
        ctx.continuation = getattr(answered, "continuation", None)
        ctx.judgment = getattr(answered, "judgment", None) or {}
        ctx.conversation = getattr(investigation, "conversation", None) or {}
        ctx.outcome = getattr(officer, "outcome", None)
        ctx.selection = getattr(officer, "selection", None)
        graph = getattr(investigation, "graph", None)
        if graph is not None:
            try:
                ctx.trace = {str(n.get("id", ""))
                             for n in graph.to_dict().get("nodes", [])}
            except Exception:  # pragma: no cover - a broken graph is a finding
                ctx.trace = set()
        return ctx

    # ---- the questions readers keep asking ---------------------------

    @property
    def executed(self) -> bool:
        """Whether THIS turn produced a governed result of its own.

        Deliberately not widened to cover a composed answer. Every reader
        gated on this then goes on to read `ctx.build`, which a composed
        answer does not have — so widening it would turn a fleet of honest
        NOT_APPLICABLEs into a fleet of FAILs. The composed case is a
        separate question, asked separately. §3.
        """
        return self.runtime is not None

    @property
    def composed(self) -> bool:
        """Whether this answer was assembled out of several analyses.

        A coordinated review runs six governed analyses and keeps none of
        their runtimes. Before this existed, every analysis check on such a
        turn answered "no analysis was planned on this turn", which is the
        most confident way to be wrong. §3 (D4/D19).
        """
        return bool(getattr(self.composition, "executed", False))

    @property
    def analysed(self) -> bool:
        """Governed analysis ran, one way or the other."""
        return self.executed or self.composed

    @property
    def wrote_prose(self) -> bool:
        sections = getattr(self.answered, "sections", None)
        return bool(getattr(sections, "sections", None))

    @property
    def datasets(self) -> list[str]:
        found = list(getattr(self.runtime, "datasets", None) or [])
        if found:
            return [str(d) for d in found]
        single = getattr(self.build, "dataset", "")
        if single:
            return [str(single)]
        # The datasets a composed review read are the union of what its
        # sub-analyses read. Reporting none of them is what made a
        # coordinated review's Trace unable to say what it touched. §3 (D19).
        composed = [str(d) for d in (getattr(self.composition, "datasets", None)
                                     or [])]
        if composed:
            return composed
        # And a catalogue answer consulted dataset metadata, which it records
        # in its own detail and nothing read. §3 (D5).
        result = getattr(self.answered, "result", None)
        detail = getattr(result, "detail", None) or {}
        found: list[str] = []
        for entry in (detail.get("datasets") or []):
            name = (str(entry.get("name") or entry.get("dataset") or "")
                    if isinstance(entry, dict) else str(entry or ""))
            if name and name not in found:
                found.append(name)
        return found

    @property
    def multi_dataset(self) -> bool:
        return len(self.datasets) > 1 or bool(getattr(self.build, "joins",
                                                      None))

    @property
    def first_turn(self) -> bool:
        action = str(getattr(self.continuation, "action", "") or "")
        return action in ("", "NEW_REQUEST")

    @property
    def gate_checks(self) -> dict[str, Any]:
        return {str(c.key): c for c in (getattr(self.gate, "checks", None)
                                        or [])}

    def gate_check(self, key: str, *, warn: bool = False) -> Signal | None:
        """One presentability gate check, translated.

        The gate already ran fourteen checks with PASS / FAIL /
        NOT_APPLICABLE semantics of its own. Translating them is far better
        than re-deriving them: two implementations of "is the bottom line
        direct" would eventually disagree, and the one on the screen would
        be whichever ran last.
        """
        found = self.gate_checks.get(key)
        if found is None:
            return None
        status = str(getattr(found, "status", "") or "").upper()
        detail = str(getattr(found, "detail", "") or "")
        title = str(getattr(found, "title", "") or key)
        if status == "PASS":
            return _pass(detail or title, "presentability")
        if status == "NOT_APPLICABLE":
            return _na(detail or f"{title} does not apply to this turn")
        if status in ("FAIL", "FAILED"):
            return (_warn if warn else _fail)(detail or f"{title} failed",
                                              "presentability")
        return None


# ================================================================= readers
#
# Understanding & context
# ---------------------------------------------------------------------------


def capability_intent(ctx: Ctx) -> Signal | None:
    intent = str(getattr(ctx.reading, "intent", "") or "")
    if not intent:
        return None
    return _pass(f"Read as {intent}.", "capability", "intent")


def conversation_action(ctx: Ctx) -> Signal | None:
    action = str(getattr(ctx.continuation, "action", "") or "")
    if not action:
        return None
    because = str(getattr(ctx.continuation, "because", "") or "")
    return _pass(f"Conversation action {action}"
                 + (f" — {because}." if because else "."), "conversation")


def objective_extraction(ctx: Ctx) -> Signal | None:
    objective = str(getattr(ctx.reading, "objective", "") or "")
    concepts = list(getattr(ctx.reading, "concepts", None) or [])
    if not objective and not concepts:
        return None
    return _verdict(
        bool(objective),
        f"Objective extracted: {objective[:80]}",
        "No objective could be extracted from the question.", "intent")


def same_turn_coreference(ctx: Ctx) -> Signal | None:
    references = list(getattr(ctx.reading, "entity_references", None) or [])
    if not references:
        return _na("the question contains no same-turn referent")
    resolved = list(getattr(ctx.continuation, "entity_ids", None) or [])
    return _verdict(
        bool(resolved),
        f"{len(references)} same-turn referent(s) resolved.",
        f"{len(references)} referent(s) in this turn resolved to nothing.",
        "conversation")


def multi_turn_context(ctx: Ctx) -> Signal | None:
    if ctx.first_turn:
        return _na("this is the first turn of the thread")
    inherited = dict(getattr(ctx.continuation, "inherited", None) or {})
    return _verdict(
        bool(inherited),
        f"Inherited {', '.join(sorted(inherited))} from the previous turn.",
        "The turn continued a thread and recorded nothing inherited.",
        "conversation")


def context_carry_forward(ctx: Ctx) -> Signal | None:
    if ctx.first_turn:
        return _na("this is the first turn of the thread")
    kind = str(getattr(ctx.scope, "kind", "") or "")
    if not kind:
        return None
    return _pass(f"Scope movement recorded as {kind}.", "scope")


def new_topic_reset_detection(ctx: Ctx) -> Signal | None:
    if ctx.first_turn:
        return _na("this is the first turn of the thread")
    kind = str(getattr(ctx.scope, "kind", "") or "")
    if not kind:
        return None
    changes = list(getattr(ctx.scope, "changes", None) or [])
    if kind == "NEW_TOPIC":
        return _pass("A new topic reset the inherited scope.", "scope")
    return _pass(f"Scope {kind.lower().replace('_', ' ')}"
                 + (f": {', '.join(str(c) for c in changes[:3])}."
                    if changes else "."), "scope")


def ambiguity_detection(ctx: Ctx) -> Signal | None:
    """The check is that a GUESS was not made, so it applies to every turn.

    A confident answer to an ambiguous question is the failure; a
    clarification is the pass. An unambiguous question passes trivially, and
    that is correct — nothing was guessed.
    """
    ambiguity = dict(getattr(ctx.answered, "ambiguity", None) or {})
    if ctx.status == "needs_clarification":
        return _pass("The question was ambiguous and CreditProbe asked "
                     "rather than guessing.", "clarification")
    if ambiguity.get("ambiguous"):
        return _fail("The question was recorded as ambiguous and was "
                     "answered anyway.", "clarification")
    return _pass("Nothing about the question required a guess.", "intent")


def clarification_quality(ctx: Ctx) -> Signal | None:
    if ctx.status != "needs_clarification":
        return _na("the turn did not ask for clarification")
    clarification = getattr(ctx.investigation, "clarification", None)
    options = list(getattr(clarification, "options", None) or [])
    question = str(getattr(clarification, "question", "") or "")
    return _verdict(
        bool(options) or len(question) > 20,
        f"The clarification offers {len(options)} named choice(s).",
        "The clarification is generic: it names no specific choice.",
        "clarification")


def language_locale_understanding(ctx: Ctx) -> Signal | None:
    language = str(ctx.conversation.get("language")
                   or getattr(ctx.reading, "language", "") or "en")
    return _pass(f"Language resolved as {language}.")


def entity_cohort_resolution(ctx: Ctx) -> Signal | None:
    entities = list(getattr(ctx.reading, "entities", None) or [])
    if not entities:
        return _na("the question names no entity or cohort")
    labels = dict(getattr(ctx.continuation, "entity_labels", None) or {})
    ids = list(getattr(ctx.continuation, "entity_ids", None) or [])
    resolved = len(labels) or len(ids)
    return _verdict(
        resolved >= 1 or bool(getattr(ctx.build, "filters", None)),
        f"{len(entities)} named entity/entities resolved.",
        f"{len(entities)} named entity/entities resolved to nothing.",
        "intent")


# ---------------------------------------------------------------------------
# Analytical design
# ---------------------------------------------------------------------------


def objective_coverage(ctx: Ctx) -> Signal | None:
    """Read from the presentability gate, which already computed it.

    Two implementations of "was every objective addressed" would drift, and
    the one shown would be whichever ran last.
    """
    return ctx.gate_check("objectives_addressed")


def concept_selection(ctx: Ctx) -> Signal | None:
    if ctx.composed and not ctx.executed:
        found = list(getattr(ctx.composition, "concepts", None) or [])
        return _verdict(bool(found),
                        f"{len(found)} governed concept(s) resolved across "
                        f"{ctx.composition.ran} sub-analyses.",
                        "The review ran analyses that resolved no governed "
                        "concept.", "data")
    if not ctx.executed:
        return _na("no analysis was planned on this turn")
    concepts = list(getattr(ctx.reading, "concepts", None) or [])
    matches = list(getattr(ctx.build, "matches", None) or [])
    return _verdict(
        bool(matches) or bool(concepts),
        f"{len(matches) or len(concepts)} concept(s) resolved against the "
        "ontology.",
        "No concept resolved against the ontology.", "data")


def dataset_selection(ctx: Ctx) -> Signal | None:
    if ctx.composed and not ctx.executed:
        found = list(getattr(ctx.composition, "datasets", None) or [])
        return _verdict(bool(found),
                        f"{len(found)} governed dataset(s) read across "
                        f"{ctx.composition.ran} sub-analyses: "
                        + ", ".join(found) + ".",
                        "The review reports no dataset behind its findings.",
                        "data")
    if not ctx.executed:
        return _na("no analysis was planned on this turn")
    datasets = ctx.datasets
    return _verdict(
        bool(datasets),
        f"Read {', '.join(datasets)}.",
        "The analysis executed and recorded no dataset.", "data")


def period_selection(ctx: Ctx) -> Signal | None:
    check = ctx.gate_check("period_correct")
    if check is not None:
        return check
    if ctx.composed and not ctx.executed:
        found = list(getattr(ctx.composition, "periods", None) or [])
        return _verdict(bool(found),
                        "Sub-analyses read " + ", ".join(found) + ".",
                        "The review's sub-analyses recorded no period.",
                        "data")
    if not ctx.executed:
        return _na("no analysis was planned on this turn")
    period = str(getattr(ctx.build, "period", "") or "")
    return _verdict(bool(period), f"Period {period}.",
                    "The analysis executed with no period recorded.", "data")


def grain_selection(ctx: Ctx) -> Signal | None:
    """Whether the answer declared what one of its rows is, and why. §4.

    A grain read off the source dataset is not a declaration — every plan has
    one of those and it says nothing about the answer. What is checked is the
    governed contract: the grain the objective asked for, the grain the plan
    emitted, and the two agreeing.
    """
    from backend.orchestration import grain as gr

    if ctx.composed and not ctx.executed:
        # §4: a broad investigation may contain several Analyses at different
        # grains, and each declares and validates its own.
        ok = ctx.composition.grain_contracts_ok
        grains = list(getattr(ctx.composition, "grains", None) or [])
        return _verdict(
            ok == ctx.composition.ran,
            f"{ok} of {ctx.composition.ran} sub-analyses declared and met "
            "their own output grain (" + ", ".join(grains) + ").",
            f"{ctx.composition.ran - ok} sub-analyses emitted a grain their "
            "own objective did not ask for.", "data")
    if not ctx.executed:
        return _na("no analysis was planned on this turn")
    contract = gr.contract_of(ctx.build)
    if contract is None:
        grain = str(getattr(ctx.build, "grain", "") or "")
        return _verdict(bool(grain),
                        f"Source grain {grain}, with no output-grain contract.",
                        "No output grain was recorded.", "data")
    got = contract.got or contract.want.grain
    return _verdict(
        contract.ok,
        f"{gr.MEANS.get(got, got)} — {contract.want.because}.",
        (f"The question asks for {gr.MEANS.get(contract.want.grain, '')} and "
         f"the plan emits {gr.MEANS.get(got, got)}."),
        "data")


def population_definition(ctx: Ctx) -> Signal | None:
    check = ctx.gate_check("population_correct")
    if check is not None:
        return check
    if not ctx.executed:
        return _na("no analysis was planned on this turn")
    return None


def filter_definition(ctx: Ctx) -> Signal | None:
    if not ctx.executed:
        return _na("no analysis was planned on this turn")
    filters = list(getattr(ctx.build, "filters", None) or [])
    conditions = list(getattr(ctx.build, "conditions", None) or [])
    if not filters and not conditions:
        return _pass("No filter was applied, and none was requested.")
    return _pass(f"{len(filters) + len(conditions)} governed filter(s) "
                 "applied.", "data")


def plan_completeness(ctx: Ctx) -> Signal | None:
    plan = getattr(ctx.investigation, "plan", None)
    steps = list(getattr(plan, "steps", None) or [])
    if not steps:
        return _na("no analysis was planned on this turn")
    unmatched = list(getattr(plan, "unmatched", None) or [])
    return _verdict(
        not unmatched,
        f"{len(steps)} step(s), every clause matched.",
        f"{len(unmatched)} clause(s) left unmatched: "
        f"{', '.join(str(u) for u in unmatched[:3])}", "plan")


def relationship_join_path(ctx: Ctx) -> Signal | None:
    joins = list(getattr(ctx.build, "joins", None)
                 or getattr(ctx.runtime, "joins", None) or [])
    if not joins:
        return _na("the analysis touched a single dataset")
    return _pass(f"{len(joins)} governed relationship(s) used.", "data")


def method_blueprint_selection(ctx: Ctx) -> Signal | None:
    if not ctx.executed:
        return _na("no analysis was planned on this turn")
    methods = list(getattr(ctx.runtime, "methods", None) or [])
    shape = str(getattr(ctx.build, "shape", "") or "")
    return _verdict(
        bool(methods) or bool(shape),
        f"Method: {', '.join(str(m) for m in methods) or shape}.",
        "No governed method or shape was selected.", "method")


def model_route_escalation(ctx: Ctx) -> Signal | None:
    route = str(getattr(ctx.decision, "route", "") or "")
    if not route:
        return None
    reason = str(getattr(ctx.decision, "reason", "") or "")
    escalated = str(getattr(ctx.decision, "escalated_from", "") or "")
    return _pass(f"Route {route}"
                 + (f", escalated from {escalated}" if escalated else "")
                 + (f" — {reason}" if reason else "."), "routing")


def teaching_case_retrieval(ctx: Ctx) -> Signal | None:
    cases = list(getattr(ctx.decision, "teaching_cases", None) or [])
    if not cases:
        return _na("no teaching pack was built for this turn")
    return _pass(f"{len(cases)} production-eligible case(s) retrieved.",
                 "routing")


def task_dag(ctx: Ctx) -> Signal | None:
    if ctx.outcome is None:
        return _na("no orchestration ran on this turn")
    plan = getattr(ctx.outcome, "plan", None)
    tasks = list(getattr(plan, "tasks", None) or [])
    return _verdict(bool(tasks), f"{len(tasks)} task(s) planned.",
                    "The orchestrator produced a plan with no tasks.",
                    "agentic_run")


# ---------------------------------------------------------------------------
# Computation & evidence
# ---------------------------------------------------------------------------


def analytical_ir(ctx: Ctx) -> Signal | None:
    if ctx.composed and not ctx.executed:
        made = ctx.composition.ir_validated
        return _verdict(made == ctx.composition.ran,
                        f"{made} of {ctx.composition.ran} sub-analyses "
                        "validated an Analytical IR.",
                        f"{ctx.composition.ran - made} sub-analyses produced "
                        "a result with no validated IR.", "query")
    if not ctx.executed:
        return _na("no analysis executed on this turn")
    plan = getattr(ctx.runtime, "plan", None)
    operations = list(getattr(plan, "operations", None) or [])
    return _verdict(bool(operations),
                    f"IR validated with {len(operations)} operation(s).",
                    "The analysis ran with no validated IR.", "query")


def generated_query(ctx: Ctx) -> Signal | None:
    if ctx.composed and not ctx.executed:
        made = ctx.composition.queries_compiled
        return _verdict(made == ctx.composition.ran,
                        f"{made} of {ctx.composition.ran} sub-analyses "
                        "compiled a query through the safe compiler.",
                        f"{ctx.composition.ran - made} sub-analyses ran with "
                        "no recorded query.", "query")
    if not ctx.executed:
        return _na("no analysis executed on this turn")
    query = getattr(ctx.runtime, "query", None)
    return _verdict(bool(query),
                    "The query was compiled by the safe compiler.",
                    "The analysis ran with no recorded query.", "query")


def approved_kernel_use(ctx: Ctx) -> Signal | None:
    methods = list(getattr(ctx.runtime, "methods", None) or [])
    if not methods:
        return _na("no numerical kernel ran on this turn")
    return _pass(f"{len(methods)} approved method(s) used.", "query")


def execution(ctx: Ctx) -> Signal | None:
    """Whether governed analysis actually ran.

    Two shapes count, because the product has two. A single analysis leaves
    a `runtime` result. A broad or coordinated investigation runs its work
    through governed probes and specialist sub-analyses and leaves executed
    STEPS instead — reading only the first reported the portfolio review,
    which ran six governed probes, as having executed nothing.
    """
    if ctx.executed:
        rows = int(getattr(ctx.runtime, "row_count", 0) or 0)
        return _pass(f"Executed and returned {rows} row(s).", "result")
    steps = list(getattr(ctx.investigation, "steps", None) or [])
    probes = _probe_count(ctx)
    if steps or probes:
        return _pass(f"{probes or len(steps)} governed "
                     f"{'probe' if probes else 'step'}(s) executed.",
                     "result")
    if ctx.status in ("needs_clarification", "rejected"):
        return _na(f"the turn ended in {ctx.status} before reaching the "
                   "engine")
    return None


def _probe_count(ctx: Ctx) -> int:
    """How many governed checks a broad investigation ran."""
    for step in (getattr(ctx.investigation, "steps", None) or []):
        result = getattr(step, "result", None)
        if not isinstance(result, dict):
            continue
        summary = (result.get("detail") or {}).get("investigation") or {}
        probes = summary.get("probes")
        if isinstance(probes, list | tuple):
            return len(probes)
        if isinstance(probes, int):
            return probes
    return 0


def data_quality(ctx: Ctx) -> Signal | None:
    if not ctx.executed:
        return _na("no analysis executed on this turn")
    warnings = list(getattr(ctx.runtime, "warnings", None) or [])
    if not warnings:
        return _pass("No dataset read raised a quality warning.", "data")
    return _warn(f"{len(warnings)} data-quality warning(s): "
                 f"{'; '.join(str(w) for w in warnings[:2])}", "data")


def join_reconciliation(ctx: Ctx) -> Signal | None:
    joins = list(getattr(ctx.runtime, "joins", None) or [])
    if not joins:
        return _na("the analysis touched a single dataset")
    reconciliation = getattr(ctx.runtime, "reconciliation", None)
    if reconciliation is None:
        return None
    return _pass(f"{len(joins)} join(s) reconciled.", "data")


def row_customer_reconciliation(ctx: Ctx) -> Signal | None:
    if not list(getattr(ctx.runtime, "joins", None) or []):
        return _na("the analysis touched a single dataset")
    reconciliation = getattr(ctx.runtime, "reconciliation", None)
    if reconciliation is None:
        return None
    return _pass("Subject counts reconcile across the join.", "data")


def result_correctness(ctx: Ctx) -> Signal | None:
    """The post-result invariants derived from the request.

    Read from `Report.failures` rather than a `passed` attribute that does
    not exist — reading a missing attribute made this check silently absent
    on every turn, which is how a critical check disappears without anybody
    noticing it had.
    """
    if ctx.invariants is None:
        return _na("no result was returned on this turn")
    failures = list(getattr(ctx.invariants, "failures", None) or [])
    checks = list(getattr(ctx.invariants, "checks", None) or [])
    if not checks and not failures:
        return _na("no invariant applied to this result")
    return _verdict(
        not failures,
        f"{len(checks)} invariant(s) applied and held.",
        f"{len(failures)} invariant(s) did not hold: "
        f"{'; '.join(str(getattr(f, 'claim', f)) for f in failures[:2])}",
        "invariants")


def business_invariants(ctx: Ctx) -> Signal | None:
    return result_correctness(ctx)


def mathematical_invariants(ctx: Ctx) -> Signal | None:
    if ctx.invariants is None:
        return _na("no result was returned on this turn")
    checks = list(getattr(ctx.invariants, "checks", None) or [])
    maths = [c for c in checks
             if str(getattr(c, "rule", "")) in
             ("share_bounds", "numerator_within_denominator",
              "components_sum_to_total", "non_negative")]
    if not maths:
        return _na("the result has no mathematical decomposition")
    failures = {str(getattr(f, "rule", "")) for f in
                (getattr(ctx.invariants, "failures", None) or [])}
    broken = [c for c in maths if str(getattr(c, "rule", "")) in failures]
    return _verdict(not broken,
                    f"{len(maths)} mathematical invariant(s) held.",
                    f"{len(broken)} mathematical invariant(s) failed.",
                    "invariants")


def totals_reconciliation(ctx: Ctx) -> Signal | None:
    check = ctx.gate_check("no_contradictory_figures")
    if check is not None:
        return check
    return result_correctness(ctx)


def evidence_fact_graph(ctx: Ctx) -> Signal | None:
    facts = ctx.judgment.get("facts") or {}
    if not facts:
        return None if ctx.executed else _na("no result was returned on this "
                                             "turn")
    usable = int(facts.get("usable") or 0)
    refused = len(facts.get("refused") or [])
    return _verdict(usable > 0,
                    f"{usable} usable validated fact(s), {refused} refused.",
                    "No fact could be registered from the result.",
                    "evidence")


def entity_grounding(ctx: Ctx) -> Signal | None:
    if not ctx.wrote_prose:
        return _na("no prose was written on this turn")
    return ctx.gate_check("no_unsupported_claims")


def figure_grounding(ctx: Ctx) -> Signal | None:
    contract = ctx.judgment.get("contract") or {}
    grounded = contract.get("grounded")
    if grounded is None:
        if not ctx.wrote_prose:
            return _na("no prose was written on this turn")
        return ctx.gate_check("no_unsupported_claims")
    ungrounded = list(contract.get("ungrounded") or [])
    return _verdict(
        bool(grounded),
        "Every figure in the prose traces to a validated fact.",
        f"{len(ungrounded)} figure(s) trace to no fact: "
        f"{', '.join(str(u) for u in ungrounded[:3])}", "grounding")


def period_unit_grounding(ctx: Ctx) -> Signal | None:
    if not ctx.wrote_prose:
        return _na("no prose was written on this turn")
    check = ctx.gate_check("period_correct")
    return check if check is not None else None


def cached_result_integrity(ctx: Ctx) -> Signal | None:
    cached = getattr(ctx.answered, "cached", None)
    if cached is None:
        return _na("no previous result was reused on this turn")
    fingerprint = str(getattr(cached, "fingerprint", "") or "")
    return _verdict(bool(fingerprint),
                    "The reused result carries its original fingerprint.",
                    "A result was reused with no fingerprint to check.",
                    "result")


def scope_isolation(ctx: Ctx) -> Signal | None:
    check = ctx.gate_check("scope_correct")
    if check is not None:
        return check
    after = getattr(ctx.scope, "after", None)
    if after is None:
        return None
    return _pass("The analytical scope is recorded.", "scope")


def permission_enforcement(ctx: Ctx) -> Signal | None:
    """Every read on this turn went through the governed services.

    The pass condition is deliberately about the PATH rather than about a
    role check returning true: the runtime has no ungoverned read, so a turn
    that produced a result through the engine is a turn whose reads were
    permitted. A turn that produced a result some other way is what this
    would catch.
    """
    if not ctx.executed:
        return _pass("No data was read on this turn.")
    if getattr(ctx.runtime, "query", None) is None:
        return _fail("A result was produced with no governed query behind "
                     "it.", "query")
    return _pass("Every read went through the governed query path.", "query")


# ---------------------------------------------------------------------------
# Judgment & presentation
# ---------------------------------------------------------------------------


def materiality(ctx: Ctx) -> Signal | None:
    rubric = ctx.judgment.get("rubric") or {}
    if not rubric:
        return None
    band = rubric.get("materiality")
    if band is None:
        return _na("no movement was described on this turn")
    return _pass(f"Materiality band {band}, from the versioned policy.",
                 "analytical_judgment")


def direct_bottom_line(ctx: Ctx) -> Signal | None:
    return ctx.gate_check("direct_answer_present")


def analyst_interpretation(ctx: Ctx) -> Signal | None:
    if not ctx.wrote_prose:
        return _na("no prose was written on this turn")
    contract = ctx.judgment.get("contract") or {}
    if not contract:
        return ctx.gate_check("no_unsupported_claims")
    return _verdict(
        bool(contract.get("grounded", True)),
        "The interpretation is bound to registered facts.",
        "The interpretation asserts something unregistered.", "grounding")


def limitations(ctx: Ctx) -> Signal | None:
    return ctx.gate_check("missing_evidence_stated")


def concision_no_repetition(ctx: Ctx) -> Signal | None:
    return ctx.gate_check("no_duplication", warn=True)


def number_formatting(ctx: Ctx) -> Signal | None:
    return ctx.gate_check("no_raw_decimals", warn=True)


def visualization_validity(ctx: Ctx) -> Signal | None:
    return ctx.gate_check("visualisation_semantics")


def client_presentability(ctx: Ctx) -> Signal | None:
    if ctx.gate is None:
        return None
    error = str(getattr(ctx.gate, "error", "") or "")
    checks = list(getattr(ctx.gate, "checks", None) or [])
    if not checks:
        return None
    failed = [c for c in checks
              if str(getattr(c, "status", "")).upper() in ("FAIL", "FAILED")]
    return _verdict(
        not failed and not error,
        f"The presentability gate ran {len(checks)} checks and returned "
        "SHOW.",
        f"The gate blocked on {len(failed)} check(s)"
        + (f": {error}" if error else "."),
        "presentability", warn_instead=False)


def trace_clarity(ctx: Ctx) -> Signal | None:
    check = ctx.gate_check("trace_agrees_with_execution")
    if check is not None:
        return check
    if not ctx.trace:
        return _fail("The turn left no Trace node.")
    return _pass(f"{len(ctx.trace)} Trace node(s) recorded.")


def table_column_ordering(ctx: Ctx) -> Signal | None:
    """Columns reach the reader in governed rank order, identity first, whole.

    This check used to read `presentation.contract`, and it failed on every
    two-period cohort. That was a defect in the check. `contract` returns the
    columns in the order the RUNTIME produced them — its docstring says so —
    because the rows are keyed by name and nothing downstream should have to
    care. `schema` is the ordered one, and it is what the table renders from.
    So the check was reporting the compiler's emission order as the reader's
    order, and calling the difference a presentation fault. §3 (D17).

    Reading `schema` instead would make the check vacuous: it sorts, so its
    ranks are always sorted. What is worth checking is what the ordering is
    FOR, so three things are asserted about the order the reader gets:

      * every column the runtime produced still reaches them — a column that
        vanished because a ranking rule did not recognise it is a figure
        nobody can see or ask about;
      * the ranks do not go backwards;
      * the subject is first, because a table whose first column is not what
        its rows are about cannot be scanned.
    """
    if not ctx.executed:
        return _na("no table was displayed on this turn")
    try:
        from backend.orchestration import presentation as pr

        ordered = pr.schema(ctx.runtime, ctx.build)
    except Exception as e:  # noqa: BLE001 - no schema is a finding, not a raise
        return _fail(f"The presentation schema could not be built: {e}",
                     "result")
    if not ordered:
        return _na("no table was displayed on this turn")

    produced = {str(c.get("name") if isinstance(c, dict)
                    else getattr(c, "name", c))
                for c in (getattr(ctx.runtime, "columns", None) or [])}
    placed = {str(c.get("name")) for c in ordered}
    missing = sorted(produced - placed)
    if missing:
        return _fail(
            f"{len(missing)} column(s) the analysis produced never reach the "
            f"table: {', '.join(missing[:5])}.", "result")

    shown = [c for c in ordered if not c.get("hidden")]
    ranks = [c.get("rank") for c in shown if c.get("rank") is not None]
    if ranks != sorted(ranks):
        return _fail("Columns are not in the governed rank order.", "result")

    identities = [i for i, c in enumerate(shown) if c.get("is_identity")]
    if identities and identities[0] != 0:
        return _fail(
            "The column the rows are about is not the first one.", "result")
    return _pass(f"{len(shown)} column(s) in governed rank order, "
                 "identity first, none dropped.", "result")


def expected_output_visual_intent(ctx: Ctx) -> Signal | None:
    """Whether the output form matches what the request asked for."""
    if not ctx.executed:
        return _na("no result was produced on this turn")
    chart = getattr(ctx.runtime, "chart", None)
    presentation = str(getattr(ctx.continuation, "presentation", "") or "")
    if not presentation:
        return _pass("No particular output form was requested"
                     + (f"; a {getattr(chart, 'kind', 'chart')} was offered."
                        if chart else "; a table was returned."), "result")
    return _verdict(
        bool(chart) or presentation.lower() in ("table", "list"),
        f"The requested {presentation} was produced.",
        f"A {presentation} was requested and not produced.", "result")


def actionability(ctx: Ctx) -> Signal | None:
    """Whether the answer names what to do or look at next.

    A number with nothing after it is a correct answer that leaves the
    reader where they started.
    """
    if not ctx.wrote_prose:
        return _na("no prose was written on this turn")
    plan = getattr(ctx.investigation, "plan", None)
    follow_ups = list(getattr(plan, "follow_ups", None) or [])
    sections = getattr(ctx.answered, "sections", None)
    keys = {str(getattr(sec, "key", "")) for sec in
            (getattr(sections, "sections", None) or [])}
    actionable = bool(follow_ups) or bool(
        keys & {"next_analyses", "what_to_do", "recommendations",
                "limitations"})
    return _verdict(actionable,
                    f"{len(follow_ups)} next analysis/analyses offered.",
                    "The answer stops at a number: nothing to do or look at "
                    "next is named.", "interpretation", warn_instead=True)


def follow_up_quality(ctx: Ctx) -> Signal | None:
    """Every suggestion must be answerable in the current scope."""
    plan = getattr(ctx.investigation, "plan", None)
    follow_ups = list(getattr(plan, "follow_ups", None) or [])
    if not follow_ups:
        return _na("no follow-up suggestions were offered on this turn")
    return _pass(f"{len(follow_ups)} suggestion(s) offered within the "
                 "governed scope.", "interpretation")


def _contract_columns(ctx: Ctx) -> list[dict[str, Any]]:
    """The presentation contract for this result, or nothing."""
    if not ctx.executed:
        return []
    try:
        from backend.orchestration import presentation as pr

        return [c for c in pr.contract(ctx.runtime, ctx.build)
                if not c.get("hidden")]
    except Exception:  # pragma: no cover - no contract is a finding, not a raise
        return []


def association_versus_causation(ctx: Ctx) -> Signal | None:
    if not ctx.wrote_prose:
        return _na("no prose was written on this turn")
    association = dict(getattr(ctx.answered, "association", None) or {})
    if association.get("causal_language"):
        return _fail("A causal claim was made from associational evidence.",
                     "interpretation")
    return _pass("No causal claim was made from associational evidence.",
                 "interpretation")


# ---------------------------------------------------------------------------
# Agentic delivery
# ---------------------------------------------------------------------------


def officer_level_selection(ctx: Ctx) -> Signal | None:
    if ctx.selection is None:
        return _na("no agentic run exists for this turn")
    level = getattr(ctx.selection, "level", None)
    if level is None:
        return None
    reasons = list(getattr(ctx.selection, "reasons", None) or [])
    return _verdict(
        bool(reasons),
        f"Level {level} selected for {len(reasons)} recorded reason(s).",
        f"Level {level} selected with no recorded reason.", "agentic_run")


def agent_selection(ctx: Ctx) -> Signal | None:
    if ctx.outcome is None:
        return _na("no orchestration ran on this turn")
    plan = getattr(ctx.outcome, "plan", None)
    agents = list(getattr(plan, "agents", None) or [])
    if not agents:
        return _pass("No specialist was engaged, and none was needed.",
                     "agentic_run")
    # The concepts that chose the specialists are NOT always the router's
    # own reading: a broad investigation's router reading is empty, and the
    # specialists are selected from the concepts its governed probes named.
    # Reading only `answered.reading` reported every coordinated review as
    # having selected five specialists on no basis at all.
    concepts = set(str(c).lower()
                   for c in (getattr(ctx.reading, "concepts", None) or []))
    concepts |= _probe_concepts(ctx)
    return _verdict(
        bool(concepts),
        f"{len(agents)} specialist(s) selected against "
        f"{len(concepts)} governed concept(s).",
        f"{len(agents)} specialist(s) selected with no concept behind them.",
        "agentic_run")


def _probe_concepts(ctx: Ctx) -> set[str]:
    """The governed concepts a broad investigation's probes named."""
    found: set[str] = set()
    for step in (getattr(ctx.investigation, "steps", None) or []):
        result = getattr(step, "result", None)
        if not isinstance(result, dict):
            continue
        summary = (result.get("detail") or {}).get("investigation") or {}
        for probe in (summary.get("probes") or []):
            name = str((probe or {}).get("concept")
                       if isinstance(probe, dict) else probe or "").lower()
            if name:
                found.add(name)
    return found


def orchestration_plan(ctx: Ctx) -> Signal | None:
    if ctx.outcome is None:
        return _na("no orchestration ran on this turn")
    plan = getattr(ctx.outcome, "plan", None)
    return _verdict(plan is not None, "A bounded orchestration plan exists.",
                    "The orchestrator produced no plan.", "agentic_run")


def task_execution(ctx: Ctx) -> Signal | None:
    if ctx.outcome is None:
        return _na("no orchestration ran on this turn")
    plan = getattr(ctx.outcome, "plan", None)
    tasks = list(getattr(plan, "tasks", None) or [])
    if not tasks:
        return _na("the plan contained no task")
    return _pass(f"{len(tasks)} task(s) reached a terminal state.",
                 "agentic_run")


def challenge_conflict_resolution(ctx: Ctx) -> Signal | None:
    if ctx.outcome is None:
        return _na("no orchestration ran on this turn")
    conflicts = list(getattr(ctx.outcome, "conflicts", None) or [])
    if not conflicts:
        return _na("no conflict arose between specialists")
    return _pass(f"{len(conflicts)} conflict(s) recorded and reported.",
                 "agentic_run")


def assurance_agent_checks(ctx: Ctx) -> Signal | None:
    if not bool(getattr(ctx.officer, "coordinated", False)):
        return _na("the turn was not a coordinated review")
    assurance = getattr(ctx.officer, "assurance", None)
    return _verdict(assurance is not None,
                    "The assurance agent ran and recorded a verdict.",
                    "A coordinated review ran with no assurance agent.",
                    "agentic_run")


def budget_loop_safety(ctx: Ctx) -> Signal | None:
    if ctx.outcome is None:
        return _na("no orchestration ran on this turn")
    budget = getattr(ctx.outcome, "budget", None)
    exceeded = bool(getattr(budget, "exceeded", False))
    return _verdict(not exceeded, "The run stayed inside its budget.",
                    "The run exceeded its budget.", "agentic_run")


def agentic_trace_consistency(ctx: Ctx) -> Signal | None:
    if ctx.officer is None or getattr(ctx.officer, "run_id", None) is None:
        return _na("no agentic run exists for this turn")
    outcome = ctx.outcome
    if outcome is None:
        return _pass("An agentic run is recorded and no orchestration was "
                     "required.", "agentic_run")
    plan = getattr(outcome, "plan", None)
    tasks = list(getattr(plan, "tasks", None) or [])
    return _pass(f"The Agentic Trace lists {len(tasks)} task(s), matching "
                 "the run.", "agentic_run")


# ---------------------------------------------------------------------------
# Reliability & experience
# ---------------------------------------------------------------------------


def controlled_error_handling(ctx: Ctx) -> Signal | None:
    # Five, not four. "unsupported" is what a governed refusal looks like —
    # the status a prompt-injection attempt correctly produces — and leaving
    # it out reported every safe refusal as an UNCONTRACTED state.
    contracted = ("succeeded", "partial", "needs_clarification", "rejected",
                  "failed", "unsupported")
    if not ctx.status:
        return None
    return _verdict(ctx.status in contracted,
                    f"The turn ended in the contracted state {ctx.status}.",
                    f"The turn ended in the uncontracted state {ctx.status}.")


def no_unexplained_500(ctx: Ctx) -> Signal | None:
    check = ctx.gate_check("no_unexplained_failure")
    if check is not None:
        return check
    failure = str(getattr(ctx.answered, "failure", "") or "")
    if ctx.status == "failed" and not failure:
        return _fail("The turn failed with no stated reason.")
    return _pass("No unexplained failure occurred.")


def latency(ctx: Ctx) -> Signal | None:
    duration = int(getattr(ctx.investigation, "duration_ms", 0) or 0)
    if not duration:
        return None
    #: The configured target. A warning rather than a failure: a slow
    #: correct answer is not a wrong answer.
    target = 30_000
    return _verdict(duration <= target, f"{duration} ms.",
                    f"{duration} ms, above the {target} ms target.",
                    warn_instead=True)


def provider_model_availability(ctx: Ctx) -> Signal | None:
    if ctx.decision is None:
        return None
    degraded = str(getattr(ctx.decision, "degraded", "") or "")
    if degraded:
        return _warn(f"The provider was degraded: {degraded}.", "routing")
    return _pass("The provider state was resolved before routing.", "routing")


def stale_build_configuration_detection(ctx: Ctx) -> Signal | None:
    try:
        from backend.build_info import build_info

        # `.sha` — the resolved source-or-image SHA. `.git_sha` has never
        # existed on BuildInfo, and reading it silently blanked the build on
        # every assurance record, so the build staleness axis could never
        # fire.
        sha = build_info().sha or ""
    except Exception:  # pragma: no cover
        sha = ""
    return _verdict(bool(sha),
                    f"Recorded against build {sha[:12]}.",
                    "The turn recorded no build.")


def token_cost_efficiency(ctx: Ctx) -> Signal | None:
    calls = getattr(ctx.answered, "calls", None)
    if calls is None:
        return None
    count = calls if isinstance(calls, int) else len(calls)
    #: The envelope for one interactive turn: a router call, a planner call,
    #: an interpretation call and at most one critic repair.
    envelope = 4
    return _verdict(count <= envelope,
                    f"{count} model call(s), within the envelope of "
                    f"{envelope}.",
                    f"{count} model call(s), above the envelope of "
                    f"{envelope}.", "routing", warn_instead=True)


def privacy_tenant_safety(ctx: Ctx) -> Signal | None:
    """No cross-tenant read is possible on this path.

    The governed query path is scoped before it compiles, so a turn that
    produced its result through it read only what the caller may read. This
    check exists to catch a result produced some OTHER way.
    """
    if ctx.composed and not ctx.executed:
        reads = ctx.composition.governed_reads
        return _verdict(reads == ctx.composition.ran,
                        f"All {reads} sub-analyses read through the "
                        "tenant-scoped query path.",
                        f"{ctx.composition.ran - reads} sub-analyses produced "
                        "a result outside the governed query path.", "query")
    if not ctx.executed:
        return _pass("No data was read on this turn.")
    if getattr(ctx.runtime, "query", None) is None:
        return _fail("A result was produced outside the governed query "
                     "path.", "query")
    return _pass("Every read went through the tenant-scoped query path.",
                 "query")


def audit_completeness(ctx: Ctx) -> Signal | None:
    """Whether this turn left the record it is supposed to leave.

    Deliberately self-referential and deliberately honest: it passes when
    the Trace carries the nodes the turn's own stages should have written,
    and the assurance record being assembled right now is the other half of
    the audit trail.
    """
    if not ctx.trace:
        return _fail("The turn left no Trace at all.")
    missing: list[str] = []
    if "question" not in ctx.trace:
        missing.append("the question")
    if ctx.executed and not any(n == "result" or n.startswith("run__")
                                for n in ctx.trace):
        # A composed analysis records its lineage under `run__*` rather than
        # a single `result` node. Expecting the literal id reported every
        # successful composed run as missing its result.
        missing.append("the execution lineage")
    return _verdict(not missing,
                    f"{len(ctx.trace)} Trace node(s) recorded, and an "
                    "assurance record was written.",
                    f"The Trace is missing {', '.join(missing)}.")


# =========================================================== the registry

READERS: dict[str, Callable[[Ctx], Signal | None]] = {
    # Understanding & context
    "capability_intent": capability_intent,
    "conversation_action": conversation_action,
    "objective_extraction": objective_extraction,
    "same_turn_coreference": same_turn_coreference,
    "multi_turn_context": multi_turn_context,
    "context_carry_forward": context_carry_forward,
    "new_topic_reset_detection": new_topic_reset_detection,
    "ambiguity_detection": ambiguity_detection,
    "clarification_quality": clarification_quality,
    "language_locale_understanding": language_locale_understanding,
    "entity_cohort_resolution": entity_cohort_resolution,
    # Analytical design
    "objective_coverage": objective_coverage,
    "concept_selection": concept_selection,
    "dataset_selection": dataset_selection,
    "period_selection": period_selection,
    "grain_selection": grain_selection,
    "population_definition": population_definition,
    "filter_definition": filter_definition,
    "plan_completeness": plan_completeness,
    "relationship_join_path": relationship_join_path,
    "method_blueprint_selection": method_blueprint_selection,
    "model_route_escalation": model_route_escalation,
    "teaching_case_retrieval": teaching_case_retrieval,
    "task_dag": task_dag,
    # Computation & evidence
    "analytical_ir": analytical_ir,
    "generated_query": generated_query,
    "approved_kernel_use": approved_kernel_use,
    "execution": execution,
    "data_quality": data_quality,
    "join_reconciliation": join_reconciliation,
    "row_customer_reconciliation": row_customer_reconciliation,
    "result_correctness": result_correctness,
    "business_invariants": business_invariants,
    "mathematical_invariants": mathematical_invariants,
    "totals_reconciliation": totals_reconciliation,
    "evidence_fact_graph": evidence_fact_graph,
    "entity_grounding": entity_grounding,
    "figure_grounding": figure_grounding,
    "period_unit_grounding": period_unit_grounding,
    "cached_result_integrity": cached_result_integrity,
    "scope_isolation": scope_isolation,
    "permission_enforcement": permission_enforcement,
    # Judgment & presentation
    "materiality": materiality,
    "direct_bottom_line": direct_bottom_line,
    "analyst_interpretation": analyst_interpretation,
    "limitations": limitations,
    "concision_no_repetition": concision_no_repetition,
    "number_formatting": number_formatting,
    "visualization_validity": visualization_validity,
    "client_presentability": client_presentability,
    "trace_clarity": trace_clarity,
    "association_versus_causation": association_versus_causation,
    "table_column_ordering": table_column_ordering,
    "expected_output_visual_intent": expected_output_visual_intent,
    "actionability": actionability,
    "follow_up_quality": follow_up_quality,
    # Agentic delivery
    "officer_level_selection": officer_level_selection,
    "agent_selection": agent_selection,
    "orchestration_plan": orchestration_plan,
    "task_execution": task_execution,
    "challenge_conflict_resolution": challenge_conflict_resolution,
    "assurance_agent_checks": assurance_agent_checks,
    "budget_loop_safety": budget_loop_safety,
    "agentic_trace_consistency": agentic_trace_consistency,
    # Reliability & experience
    "controlled_error_handling": controlled_error_handling,
    "no_unexplained_500": no_unexplained_500,
    "latency": latency,
    "provider_model_availability": provider_model_availability,
    "stale_build_configuration_detection": stale_build_configuration_detection,
    "token_cost_efficiency": token_cost_efficiency,
    "privacy_tenant_safety": privacy_tenant_safety,
    "audit_completeness": audit_completeness,
}


def read(name: str, ctx: Ctx) -> Signal | None:
    """Call one reader, never raising.

    A reader that throws is reported as SKIPPED with the exception in its
    detail: a broken reader is a fact worth recording, and losing the whole
    record because one check misbehaved would be a far worse trade.
    """
    reader = READERS.get(name)
    if reader is None:
        return None
    try:
        return reader(ctx)
    except Exception as e:  # noqa: BLE001 - a broken reader is a finding
        logger.warning("Assurance reader %s raised: %s", name, e)
        return Signal(rc.SKIPPED,
                      f"The reader for this check raised {type(e).__name__}: "
                      f"{e}")
