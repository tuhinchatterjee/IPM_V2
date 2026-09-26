"""The authorised integration adapter: a governed step that runs a scenario.

Section 7 of `PROTECTED_CORE_INCOMPATIBILITY.md` recorded the boundary this
module crosses, and why it could not be crossed without permission. The
engine was built, governed and tested, and none of it was reachable from a
typed question: a governed Python step runs under `-I -S` from a temporary
directory with no `PYTHONPATH`, so it can import the standard library and
nothing else. `import pandas` and `from backend.cockpit_v4.scenario import
run` both fail with `ModuleNotFoundError`, measured directly.

The approved fix is Option A: the existing governed executor recognises one
strictly typed operation and dispatches it SERVER-SIDE to `run.py`. This
module is the whole of that dispatch. `execute_tool.py` gained a branch, a
guard and an error translation; everything a reader could influence is
checked here, in a file that is not protected and can therefore be read,
tested and corrected without touching the core.

## What this module refuses to accept, by construction

**No module name, callable, path or Python expression.** The operation is an
enum of two values. Everything else is a checked structure: a cohort is a
list of typed comparisons (`selector`), a rule is a field the book declares
mutable plus an amount in a named unit (`fields`, `units`), a confirmation is
a hex digest compared against one the SERVER wrote. `step.code` is never
parsed and never executed on this path.

**No SQL from a model.** `cohort.freeze` takes a predicate and says in its
own docstring that the caller has validated it. `selector` is that caller,
and it composes the predicate from column names checked against
`schema.relations()` and literals checked against a character allowlist.

**No sandbox change.** `-I` and `-S` stay, no `PYTHONPATH` is set, no backend
directory joins `sys.path`, and model-authored Python still imports the
standard library and nothing else. This path does not run model-authored code
at all, which is why it needs none of that.

**No second executor.** The step is validated, counted, budgeted, timed,
stored and evented by the machinery that was already there. What arrives here
has passed `intent.may_execute`, spent its submission and its steps, and has
a deadline. What leaves here is an artifact and a `StepResult`.

## Two operations, and why not one

A scenario is previewed, then approved, then run -- section 6.2 is explicit
that reading a sensitivity or naming a method is not approval of a
calculation nobody has seen. So `preview_scenario` freezes the cohort,
compiles the rules and publishes what would happen; the reader answers; and
`execute_scenario` reads back the scenario the SERVER stored, re-verifies the
confirmation against it, and runs it.

The second operation carries almost nothing: a digest and the reader's reply.
The rules, the cohort, the release and the baseline all come from
`store.thread_context`, which is written only by `worker.py` through the
server-only `set_thread_context`. A model cannot author the scenario it asks
to execute, because by then the scenario is already a stored fact.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import attribution as at
from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import fields as fd
from backend.cockpit_v4.scenario import flags
from backend.cockpit_v4.scenario import ledger as lg
from backend.cockpit_v4.scenario import preview as pv
from backend.cockpit_v4.scenario import results as rs
from backend.cockpit_v4.scenario import rules as ru
from backend.cockpit_v4.scenario import run as rn
from backend.cockpit_v4.scenario import selector as sel
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import sql as sq
from backend.cockpit_v4.scenario import thread as th
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import (
    BUDGET_EXCEEDED,
    CALCULATION_FAILED,
    CONFIRMATION_STALE,
    METHOD_COVERAGE_GAP,
    PARAMETER_OUT_OF_RANGE,
    as_step_failed,
    raise_for,
)

#: THE TWO OPERATIONS. A closed set, checked by exact match.
PREVIEW = "preview_scenario"
EXECUTE = "execute_scenario"
OPERATIONS: tuple[str, ...] = (PREVIEW, EXECUTE)

#: Keys each operation accepts. Anything else is refused by name rather than
#: ignored: a misspelled key that is silently dropped is a rule that silently
#: did not happen.
PREVIEW_KEYS = frozenset({
    "operation", "period", "cohort", "shocks", "methods", "delta_submode",
    "user_assumption", "name", "clauses", "scenario_id"})
EXECUTE_KEYS = frozenset({
    "operation", "confirmation_digest", "reply", "methods"})
SHOCK_KEYS = frozenset({"field", "operation", "value", "where", "origin"})

#: How many rules one scenario may carry, and how many rows one run may
#: touch. Declared rather than discovered: `_run_step` computes a per-step
#: time budget and enforces none of it, each existing arm enforcing its own,
#: so this arm declares its bounds and checks them.
MAX_SHOCKS = 12
MAX_COHORT_ROWS = 250_000

#: How long the arithmetic may take once the rows are in hand, as a share of
#: the step's own budget. The read is bounded by the engine; this is the part
#: that runs in this process.
DEADLINE_SHARE = 0.9

#: The sections one result artifact carries. A scenario answers several
#: questions at once -- what changed, by which method, driven by what -- and
#: one tidy table with a section column keeps them reconcilable to each other
#: rather than spread across artifacts that can disagree.
SECTIONS: tuple[str, ...] = (
    "headline", "cohort", "book", "method", "coverage",
    "attribution_economic", "attribution_mechanism", "ml_explanation")


@dataclass(frozen=True)
class Produced:
    """What a scenario step gives the executor back."""

    columns: list[str]
    rows: list[dict[str, Any]]
    relations: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreviewRequest:
    """A scenario to freeze, compile and show. Checked, not trusted."""

    operation: str
    selection: sel.Selection
    shocks: tuple[sp.Shock, ...]
    methods: tuple[str, ...]
    delta_submode: str
    user_assumption: dict[str, Any]
    name: str
    clauses: tuple[str, ...]
    period: str
    scenario_id: str


@dataclass(frozen=True)
class ExecuteRequest:
    """An approval of something already stored."""

    operation: str
    confirmation_digest: str
    reply: str
    methods: tuple[str, ...]


# ---- validation ---------------------------------------------------------

def validate(parameters: Any, *, step_id: str,
             domain_id: str = "") -> PreviewRequest | ExecuteRequest:
    """Parse the operation, or raise a `ScenarioError` naming what was wrong.

    Pure: no database, no store, no clock. `validate_batch` calls it before
    any step in the batch runs, which is the existing whole-batch-first
    discipline -- a fourth step that names a field the book does not have
    should not have run the first three.

    `domain_id` is optional here only because the validation pass has the
    scope and the *shape* checks do not need it. The field and column checks
    DO, and they are the reason a scenario step is validated per book rather
    than once: `pd_pit_12m` is a Corporate field and `score_behavioural` is a
    Retail one, and a runtime that accepted either for either would be
    checking spelling rather than authorisation.
    """
    path = f"steps.{step_id}.parameters"
    if not isinstance(parameters, Mapping) or not parameters:
        raise_for(CONFIRMATION_STALE,
                  f"{path} must carry a What-If operation. A scenario step "
                  f"with no operation is not a scenario.",
                  field_path=path)
    operation = str(parameters.get("operation") or "")
    if operation not in OPERATIONS:
        raise_for(CONFIRMATION_STALE,
                  f"{operation!r} is not a What-If operation. They are: "
                  f"{', '.join(OPERATIONS)}. Nothing else is dispatched, and "
                  f"no module, function or expression may be named here.",
                  field_path=f"{path}.operation")
    if operation == EXECUTE:
        return _execute_request(parameters, path=path)
    return _preview_request(parameters, path=path, domain_id=domain_id)


def _reject_unknown(parameters: Mapping[str, Any], allowed: frozenset[str], *,
                    path: str) -> None:
    unknown = set(parameters) - allowed
    if unknown:
        raise_for(CONFIRMATION_STALE,
                  f"{path} carries {sorted(unknown)}, which this operation "
                  f"does not accept. The accepted keys are "
                  f"{sorted(allowed)} -- an unrecognised key is refused "
                  f"rather than dropped, because a rule that was silently "
                  f"ignored is a scenario nobody described.",
                  field_path=path)


def _execute_request(parameters: Mapping[str, Any], *,
                     path: str) -> ExecuteRequest:
    _reject_unknown(parameters, EXECUTE_KEYS, path=path)
    digest = str(parameters.get("confirmation_digest") or "").strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise_for(CONFIRMATION_STALE,
                  f"{path}.confirmation_digest must be the 64-character hex "
                  f"digest of the preview the reader approved. It identifies "
                  f"WHICH scenario is being run and is compared against the "
                  f"one the server stored.",
                  field_path=f"{path}.confirmation_digest")
    return ExecuteRequest(
        operation=EXECUTE, confirmation_digest=digest,
        reply=str(parameters.get("reply") or ""),
        methods=_methods(parameters.get("methods"), path=path,
                         allow_empty=True))


def _preview_request(parameters: Mapping[str, Any], *, path: str,
                     domain_id: str) -> PreviewRequest:
    _reject_unknown(parameters, PREVIEW_KEYS, path=path)
    if not domain_id:
        raise_for(CONFIRMATION_STALE,
                  "a scenario is a statement about one book, and no book was "
                  "in scope when this step was validated.",
                  field_path="domain_id")
    raw_shocks = parameters.get("shocks") or []
    if (not isinstance(raw_shocks, Sequence)
            or isinstance(raw_shocks, (str, bytes)) or not raw_shocks):
        raise_for(CONFIRMATION_STALE,
                  f"{path}.shocks must be a non-empty list of rules. A "
                  f"scenario that moves nothing has no scenario ECL to "
                  f"report.", field_path=f"{path}.shocks")
    if len(raw_shocks) > MAX_SHOCKS:
        raise_for(BUDGET_EXCEEDED,
                  f"{path}.shocks carries {len(raw_shocks)} rules and the "
                  f"declared limit is {MAX_SHOCKS}.",
                  field_path=f"{path}.shocks")
    columns = sel.columns_of(domain_id)
    shocks = tuple(
        _shock(raw, domain_id=domain_id, columns=columns,
               path=f"{path}.shocks[{i}]")
        for i, raw in enumerate(raw_shocks))
    submode = str(parameters.get("delta_submode") or sp.PROPORTIONAL)
    if submode not in sp.DELTA_SUBMODES:
        raise_for(CONFIRMATION_STALE,
                  f"{submode!r} is not a Delta submode. They are: "
                  f"{', '.join(sp.DELTA_SUBMODES)}, and they give different "
                  f"numbers on purpose.",
                  field_path=f"{path}.delta_submode")
    assumption = parameters.get("user_assumption") or {}
    if not isinstance(assumption, Mapping):
        raise_for(CONFIRMATION_STALE,
                  f"{path}.user_assumption must be an object.",
                  field_path=f"{path}.user_assumption")
    clauses = parameters.get("clauses") or []
    if isinstance(clauses, (str, bytes)) or not isinstance(clauses, Sequence):
        raise_for(CONFIRMATION_STALE,
                  f"{path}.clauses must be a list of the reader's own "
                  f"sentences.", field_path=f"{path}.clauses")
    return PreviewRequest(
        operation=PREVIEW,
        selection=sel.parse(parameters.get("cohort"), domain_id=domain_id,
                            path=f"{path}.cohort"),
        shocks=shocks,
        methods=_methods(parameters.get("methods"), path=path),
        delta_submode=submode,
        user_assumption=dict(assumption),
        name=str(parameters.get("name") or "")[:120],
        clauses=tuple(str(c)[:400] for c in clauses),
        period=str(parameters.get("period") or ""),
        scenario_id=str(parameters.get("scenario_id") or ""))


def _methods(raw: Any, *, path: str,
             allow_empty: bool = False) -> tuple[str, ...]:
    if raw is None:
        if allow_empty:
            return ()
        return (sp.DELTA,)
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise_for(CONFIRMATION_STALE,
                  f"{path}.methods must be a list.",
                  field_path=f"{path}.methods")
    asked = [str(m) for m in raw]
    unknown = [m for m in asked if m not in sp.METHODS]
    if unknown:
        raise_for(METHOD_COVERAGE_GAP,
                  f"{unknown} are not methods this runtime has. They are: "
                  f"{', '.join(sp.METHODS)}.",
                  field_path=f"{path}.methods")
    if not asked and not allow_empty:
        raise_for(METHOD_COVERAGE_GAP,
                  f"{path}.methods is empty. A scenario with no method has "
                  f"nothing to compute.", field_path=f"{path}.methods")
    # Deduplicated, order preserved: asking for Delta twice is one Delta.
    seen: list[str] = []
    for method in asked:
        if method not in seen:
            seen.append(method)
    return tuple(seen)


def _shock(raw: Any, *, domain_id: str, columns: Sequence[str],
           path: str) -> sp.Shock:
    if not isinstance(raw, Mapping):
        raise_for(CONFIRMATION_STALE, f"{path} must be an object.",
                  field_path=path)
    unknown = set(raw) - SHOCK_KEYS
    if unknown:
        raise_for(CONFIRMATION_STALE,
                  f"{path} carries {sorted(unknown)}, which is not part of a "
                  f"rule.", field_path=path)
    field_id = str(raw.get("field") or "")
    # `fields.mutable` owns both refusals: a field the book does not carry,
    # and a field a scenario may not move. It raises with the book's own
    # list, which is the list a reader can act on.
    fd.mutable(domain_id, field_id)
    operation = str(raw.get("operation") or "")
    if operation not in un.OPERATIONS:
        raise_for(PARAMETER_OUT_OF_RANGE,
                  f"{operation!r} is not a unit this runtime applies. They "
                  f"are: {', '.join(un.OPERATIONS)}. \"Increase PD by 20\" is "
                  f"four different instructions and they differ by a factor "
                  f"of ten between neighbours, so the operation is required "
                  f"rather than inferred.",
                  field_path=f"{path}.operation")
    amount = un.parse(raw.get("value"), operation,
                      str(raw.get("origin") or ""))
    where = raw.get("where") or {}
    if not isinstance(where, Mapping):
        raise_for(CONFIRMATION_STALE,
                  f"{path}.where must be an object of column to value, which "
                  f"is what scopes one rule to part of the cohort.",
                  field_path=f"{path}.where")
    scope: dict[str, Any] = {}
    for key, value in where.items():
        column = str(key)
        if column not in set(columns):
            raise_for(CONFIRMATION_STALE,
                      f"{column!r} is not a column of this book's exposure "
                      f"relation, so a rule cannot be scoped by it. It has: "
                      f"{', '.join(sorted(columns))}.",
                      field_path=f"{path}.where")
        scope[column] = sel.literal_value(
            value, path=f"{path}.where.{column}")
    return sp.Shock(field_id=field_id, amount=amount, where=scope,
                    origin=str(raw.get("origin") or "")[:400])


# ---- execution ----------------------------------------------------------

def execute(parameters: Any, *, session: Any, scope: Any, catalog: Any,
            store: Any, run_id: str, tenant_id: str, release_id: str,
            header: Any = None, step_id: str = "",
            deadline_seconds: float = 30.0) -> Produced:
    """Run one scenario operation and return the rows the step publishes."""
    domain_id = str(getattr(scope, "domain_id", "")
                    or getattr(catalog, "domain_id", ""))
    if not flags.enabled(domain_id):
        raise_for(METHOD_COVERAGE_GAP,
                  f"What-If is not enabled for the {domain_id or 'current'} "
                  f"book in this runtime, so no scenario was executed.",
                  field_path="domain_id")
    request = validate(parameters, step_id=step_id, domain_id=domain_id)
    clock = _Clock(deadline_seconds * DEADLINE_SHARE)
    if isinstance(request, PreviewRequest):
        return _preview(request, session=session, scope=scope, store=store,
                        run_id=run_id, tenant_id=tenant_id,
                        release_id=release_id, domain_id=domain_id,
                        clock=clock)
    return _execute(request, session=session, scope=scope, store=store,
                    run_id=run_id, tenant_id=tenant_id,
                    release_id=release_id, domain_id=domain_id, clock=clock)


def _preview(request: PreviewRequest, *, session: Any, scope: Any,
             store: Any, run_id: str, tenant_id: str, release_id: str,
             domain_id: str, clock: _Clock) -> Produced:
    """Freeze the cohort, compile the rules, and publish what WOULD happen.

    Nothing is calculated against `ecl_sar_mn` here beyond the baseline the
    cohort already carries: `preview.build` never touches it, and that is the
    point -- a preview is a statement about what is about to be computed, and
    a preview that computed it would make the confirmation ceremonial.
    """
    frozen = ch.freeze(
        session=session, scope=scope,
        predicate=request.selection.predicate(),
        period=request.period,
        selection=request.selection.selection,
        described_as=request.selection.describe())
    clock.check("freezing the cohort")
    _bound_cohort(frozen)
    draft = sp.ScenarioSpec(
        scenario_id=request.scenario_id or f"sc-{frozen.ref.membership_hash[:12]}",
        version=1,
        source=sp.SourceRef(
            domain_id=domain_id, release_id=frozen.release_id,
            release_fingerprint=frozen.release_fingerprint,
            reporting_period=frozen.period),
        cohort=frozen.ref, shocks=request.shocks,
        methods=request.methods, delta_submode=request.delta_submode,
        user_assumption=request.user_assumption,
        name=request.name, original_clauses=request.clauses)
    graph = ru.compile_rules(draft)
    overlaps = ru.overlaps(draft)
    built = pv.build(spec=draft, frozen=frozen, graph=graph,
                     overlaps=overlaps,
                     readiness=_readiness(draft, release_id=release_id))
    clock.check("building the preview")
    _remember_spec(store, run_id=run_id, tenant_id=tenant_id,
                   release_id=release_id, spec=built.spec, frozen=frozen,
                   headline=built.question())
    rows = _preview_rows(built, frozen=frozen, graph=graph,
                         overlaps=overlaps, release_id=release_id)
    return Produced(
        columns=list(rows[0].keys()) if rows else list(_PREVIEW_COLUMNS),
        rows=rows,
        relations=(ch.GRAIN[domain_id]["relation"],),
        provenance={
            "whatif_operation": PREVIEW,
            "whatif_scenario_id": built.spec.scenario_id,
            "whatif_scenario_version": built.spec.version,
            "whatif_digest_to_confirm": built.digest(),
            "whatif_cohort_id": frozen.ref.cohort_id,
            "whatif_membership_hash": frozen.ref.membership_hash,
            "whatif_reporting_period": frozen.period,
            "origin": "SYNTHETIC_DEMO"},
        warnings=list(built.spec.warnings))


_PREVIEW_COLUMNS: tuple[str, ...] = (
    "section", "item", "detail", "value", "unit", "status")


def _preview_rows(built: pv.Preview, *, frozen: ch.Frozen, graph: ru.Graph,
                  overlaps: Sequence[Any], release_id: str
                  ) -> list[dict[str, Any]]:
    """The preview as a table, so the analyst quotes rows rather than prose.

    Every number a reader is shown before approving comes from here, and
    every one of them is a row with an id -- which is what lets the numeric
    validator check the answer against the preview instead of trusting it.
    """
    spec = built.spec
    out: list[dict[str, Any]] = []

    def add(section: str, item: str, detail: str = "", value: Any = "",
            unit: str = "", status: str = "") -> None:
        out.append({"section": section, "item": item, "detail": detail,
                    "value": value, "unit": unit, "status": status})

    add("scope", "Book", frozen.domain_id, frozen.domain_id)
    add("scope", "Release", "the bytes this scenario is built against",
        frozen.release_id, status=release_id == frozen.release_id
        and "in use" or "NOT THE RELEASE IN USE")
    add("scope", "Reporting period", "", frozen.period)
    add("cohort", "Cohort id", frozen.described_as, frozen.ref.cohort_id)
    add("cohort", "Membership hash",
        "the identity of these exact rows; a different hash is a different "
        "cohort", frozen.ref.membership_hash)
    add("cohort", "Exposures selected", frozen.ref.grain,
        frozen.ref.entity_count, "count")
    add("cohort", "Owners behind them",
        "everything these owners hold is a WIDER population and a different "
        "cohort", frozen.owner_count, "count")
    add("cohort", "Baseline EAD", "", frozen.ref.baseline_ead,
        "SAR million")
    add("cohort", "Baseline ECL",
        "what the scenario will be measured against",
        frozen.ref.baseline_ecl, "SAR million")
    for rule in graph.order():
        add("rules", rule.field_id, rule.origin or "",
            rule.amount.describe(),
            status=("scoped to " + ", ".join(
                f"{k}={v}" for k, v in sorted(rule.where.items())))
            if rule.where else "every row in the cohort")
    add("rules", "Order applied",
        "rule order changes the answer, so it is part of the confirmation",
        " then ".join(spec.ordering()))
    for overlap in overlaps:
        add("overlaps", overlap.field_id, overlap.question(),
            " | ".join(overlap.options()),
            status=overlap.composition or "NEEDS A DECISION")
    for method, state in _readiness(spec, release_id=release_id).items():
        add("methods", rn.LABELS.get(method, method), "", method,
            status=state)
    add("policy", "Stages", "", spec.stage_policy)
    add("policy", "Overlay", "", spec.overlay_policy)
    add("policy", "FX", "", spec.fx_policy)
    add("confirmation", "Digest to approve",
        "a plain yes approves exactly this; any change is a new version",
        built.digest())
    add("confirmation", "The source is read and never written",
        pv.SOURCE_UNTOUCHED, "simulation")
    return out


def _execute(request: ExecuteRequest, *, session: Any, scope: Any, store: Any,
             run_id: str, tenant_id: str, release_id: str, domain_id: str,
             clock: _Clock) -> Produced:
    """Run the scenario the SERVER stored, after proving it is that scenario.

    The order of the checks is the argument. The book is checked before the
    confirmation, the confirmation is recomputed from the stored rules rather
    than compared against a second stored digest, and the cohort is
    re-resolved and its hash compared before any arithmetic. Each of those
    refusals is cheaper than a wrong number and none of them is skippable.
    """
    stored = _stored_scenario(store, run_id=run_id, tenant_id=tenant_id,
                              release_id=release_id, scope=scope)
    rebuilt = sp.from_canonical(
        stored.get("canonical") or {},
        scenario_id=str(stored.get("scenario_id") or ""),
        version=int(stored.get("version") or 1),
        name=str(stored.get("name") or ""),
        state=sp.PREVIEW_READY,
        cohort_id=str(stored.get("cohort_id") or ""),
        cohort_baseline_ead=str(stored.get("cohort_baseline_ead") or "0"),
        cohort_baseline_ecl=str(stored.get("cohort_baseline_ecl") or "0"),
        original_clauses=list(stored.get("original_clauses") or []))
    offered = rebuilt.digest()
    if request.confirmation_digest != offered:
        raise_for(CONFIRMATION_STALE,
                  f"the approval names scenario "
                  f"{request.confirmation_digest[:12]} and the scenario this "
                  f"conversation is holding hashes to {offered[:12]}. "
                  f"Something that changes the answer moved between the "
                  f"preview and the approval, so nothing was run: the reader "
                  f"has to see the current preview and approve that.",
                  field_path="confirmation_digest",
                  approved=request.confirmation_digest, stored=offered)
    confirmed = pv.confirm(pv.Preview(spec=rebuilt, body={}), request.reply)
    # `require_confirmed` recomputes the digest from the rules about to run.
    # This is the authorisation check, and it is deliberately not the stored
    # `confirmed_digest == digest_now` comparison, which proves only that two
    # strings written at one moment still agree with each other.
    confirmed.require_confirmed()
    if request.methods:
        chosen = tuple(m for m in confirmed.methods if m in request.methods)
        if not chosen:
            raise_for(METHOD_COVERAGE_GAP,
                      f"the approved scenario carries "
                      f"{list(confirmed.methods)} and this run asked for "
                      f"{list(request.methods)}. A method nobody approved is "
                      f"not run, and narrowing to none leaves nothing to "
                      f"compute.", field_path="methods")
        if chosen != confirmed.methods:
            # A narrowing is a different scenario and needs its own approval.
            raise_for(CONFIRMATION_STALE,
                      f"the reader approved {list(confirmed.methods)} and "
                      f"this run asked for {list(chosen)}. Which methods run "
                      f"is inside the confirmation, so a different set is a "
                      f"new version with a new preview.",
                      field_path="methods")
    rn.require_same_book(confirmed, release_id=release_id,
                         release_fingerprint=str(
                             getattr(scope, "release_fingerprint", "") or ""))
    clock.check("checking the confirmation")
    frozen = ch.reresolve(session=session, scope=scope,
                          stored=_cohort_context(stored, confirmed))
    _bound_cohort(frozen)
    clock.check("re-resolving the cohort")
    return _compute(confirmed, session=session, scope=scope, store=store,
                    run_id=run_id, tenant_id=tenant_id,
                    release_id=release_id, domain_id=domain_id,
                    frozen=frozen, clock=clock, reply=request.reply,
                    # WHAT A SECOND RUN OF THE SAME SCENARIO IS.
                    #
                    # Not refused, and not a second answer. The engine is
                    # deterministic over a frozen cohort and a confirmed
                    # spec, so pressing Run twice can only produce the same
                    # numbers -- and refusing the repeat would break a
                    # reopen, which is the same request arriving
                    # legitimately.
                    #
                    # So it is published as a RE-RUN, naming the run that
                    # produced the result first. A reader comparing two
                    # turns then sees one result reported twice rather than
                    # two results that happen to agree.
                    previous_run_id=str(
                        stored.get("executed_run_id") or ""))


#: Columns every scenario run reads, whatever it moves: the identity, the
#: baseline it is measured against, and the exposure the coverage rate needs.
#: Named here rather than selected with `*` so the artifact's
#: `referenced_relations` is a statement about what was read.
BASE_COLUMNS: tuple[str, ...] = ("ead_sar_mn", "ecl_sar_mn")

#: The dimensions a result breaks its movement down by, per book.
#:
#: Checked against the release's declared columns in `_cohort_rows`, so a name
#: that is not in the book is dropped rather than put into a query. The names
#: here were WRONG on the first attempt -- `rating_current` and
#: `product_type`, neither of which exists -- and the drop hid it: the run
#: succeeded with a breakdown missing a dimension nobody had asked after.
#: `test_the_declared_groupings_are_real_columns` is the guard, and it is the
#: reason this list is short and exact rather than hopeful.
GROUPINGS: dict[str, tuple[str, ...]] = {
    "corporate": ("sector", "stage", "facility_class", "region",
                  "relationship_tier"),
    "retail": ("product", "stage", "score_band", "region",
               "employment_type"),
}


def _compute(confirmed: sp.ScenarioSpec, *, session: Any, scope: Any,
             store: Any, run_id: str, tenant_id: str, release_id: str,
             domain_id: str, frozen: ch.Frozen, clock: _Clock,
             reply: str = "", previous_run_id: str = "") -> Produced:
    """Every eligible method, against ONE contract, and the results composed.

    Section 12's requirement in one sentence: the same book, period, release,
    cohort, revision, baseline and source versions for every method selected.
    That is not enforced by discipline here -- it is enforced by there being
    one `ScenarioSpec`, one `frozen` cohort and one set of `rows`, which every
    method is handed. `run.execute` then refuses if any method's baseline
    differs from another's, which is the check that would catch a future
    method reading its own population.
    """
    plan = dl.plan(confirmed)
    grain = ch.GRAIN[domain_id]
    rows = _cohort_rows(session, plan=plan, grain=grain, frozen=frozen,
                        domain_id=domain_id)
    clock.check("reading the cohort")
    book_baseline, book_rows, outside = _book_totals(
        session, spec=confirmed, frozen=frozen)
    clock.check("reading the book total")
    loaded, anchored, unavailable = _ml_inputs(
        confirmed, rows=rows, domain_id=domain_id, release_id=release_id,
        plan=plan)
    clock.check("preparing the emulator")
    outcome = rn.execute(
        confirmed, rows, key="entity_id", ecl_column="ecl_sar_mn", plan=plan,
        anchored=anchored, ml_unavailable=unavailable, loaded=loaded,
        book_baseline=book_baseline)
    clock.check("running the methods")
    ledgers = _ledgers(outcome, confirmed, rows=rows, plan=plan,
                       book_baseline=book_baseline)
    views = _attribution(confirmed, rows=rows, plan=plan,
                         baseline=_total(rows, "ecl_sar_mn"),
                         headline=_delta_headline(outcome))
    clock.check("attributing the movement")
    summary = _summary(confirmed, rows=rows, outcome=outcome, frozen=frozen,
                       book_baseline=book_baseline, book_rows=book_rows,
                       outside=outside, plan=plan)
    _remember_spec(store, run_id=run_id, tenant_id=tenant_id,
                   release_id=release_id, spec=confirmed, frozen=frozen,
                   headline=summary.headline(), executed=True)
    table = _result_rows(confirmed, outcome=outcome, summary=summary,
                         views=views, ledgers=ledgers, rows=rows,
                         frozen=frozen, domain_id=domain_id, loaded=loaded,
                         unavailable=unavailable, reply=reply,
                         previous_run_id=previous_run_id, run_id=run_id)
    return Produced(
        columns=list(_RESULT_COLUMNS), rows=table,
        relations=(grain["relation"],),
        provenance={
            "whatif_operation": EXECUTE,
            "whatif_scenario_id": confirmed.scenario_id,
            "whatif_scenario_version": confirmed.version,
            "whatif_confirmation_digest": confirmed.confirmed_digest,
            "whatif_cohort_id": confirmed.cohort.cohort_id,
            "whatif_membership_hash": confirmed.cohort.membership_hash,
            "whatif_reporting_period": confirmed.source.reporting_period,
            "whatif_methods_ran": list(outcome.ran),
            "whatif_methods_unavailable": list(outcome.unavailable),
            "whatif_previous_run_id": previous_run_id,
            "whatif_is_rerun": bool(previous_run_id
                                    and previous_run_id != run_id),
            "whatif_model_version": getattr(loaded, "model_version", ""),
            "origin": "SYNTHETIC_DEMO"},
        warnings=list(outcome.notes))


def _cohort_rows(session: Any, *, plan: dl.Plan, grain: Mapping[str, str],
                 frozen: ch.Frozen, domain_id: str) -> list[dict[str, Any]]:
    """The cohort's rows, with exactly the columns this run reads.

    The predicate is `frozen.predicate`, which `selector` composed and
    `cohort.freeze` has already run once to produce the membership hash that
    `reresolve` just re-checked. So these are the approved rows, not a second
    selection that happens to look similar.
    """
    wanted: list[str] = [f"{grain['key']} AS entity_id",
                         f"{grain['owner']} AS owner_id"]
    seen = {"entity_id", "owner_id"}
    declared = set(sel.columns_of(domain_id))
    for column in (*BASE_COLUMNS, *plan.fields(),
                   *GROUPINGS.get(domain_id, ()), "overlay_sar_mn",
                   "drawn_sar_mn", "undrawn_sar_mn", "balance_sar_mn", "ccf",
                   *[c for f in plan.factors for c, _ in f.scope]):
        if column in seen or column not in declared:
            continue
        seen.add(column)
        wanted.append(column)
    where = f"{grain['period']} = '{frozen.period}'"
    if frozen.predicate:
        where += f" AND ({frozen.predicate})"
    if frozen.selection == ch.BY_OWNER:
        where = (f"{grain['period']} = '{frozen.period}' AND "
                 f"{grain['owner']} IN (SELECT {grain['owner']} FROM "
                 f"{grain['relation']} WHERE {where})")
    found = ch._rows(session, f"""
        SELECT {', '.join(wanted)}
        FROM {grain['relation']}
        WHERE {where}
        ORDER BY {grain['key']}
    """)
    if len(found) != frozen.ref.entity_count:
        raise_for(CALCULATION_FAILED,
                  f"the cohort re-resolved to {frozen.ref.entity_count} "
                  f"exposures and reading their values returned "
                  f"{len(found)}. Nothing was calculated on a population that "
                  f"does not match the one that was approved.",
                  field_path="cohort",
                  approved=frozen.ref.entity_count, read=len(found))
    return [{k: _as_decimal(v) for k, v in row.items()} for row in found]


def _as_decimal(value: Any) -> Any:
    """Numbers as `Decimal`, everything else untouched.

    `units`' header is the reason: a currency calculation that passes through
    a float is a calculation whose last digits are decoration.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return value


def _total(rows: Sequence[Mapping[str, Any]], column: str) -> Decimal:
    return sum((_as_decimal(r.get(column, 0)) or Decimal(0) for r in rows),
               Decimal(0))


def _book_totals(session: Any, *, spec: sp.ScenarioSpec,
                 frozen: ch.Frozen) -> tuple[Decimal, int, Decimal]:
    """The whole book at this period, from the same relation as the cohort."""
    found = ch._rows(session, sq.book_totals_sql(spec, frozen=frozen))
    if not found:
        return Decimal(0), 0, Decimal(0)
    row = found[0]
    return (_as_decimal(row.get("book_baseline_sar_mn", 0)) or Decimal(0),
            int(row.get("book_rows", 0) or 0),
            _as_decimal(row.get("outside_cohort_sar_mn", 0)) or Decimal(0))


def _ml_inputs(spec: sp.ScenarioSpec, *, rows: Sequence[Mapping[str, Any]],
               domain_id: str, release_id: str,
               plan: dl.Plan) -> tuple[Any, Any, str]:
    """The frozen emulator and its anchored prediction, or the reason there is
    none.

    NEVER RAISES, and that is deliberate. An unavailable Method 2 is a fact
    about Method 2, not a failure of the run: Delta and User-defined are
    unaffected and must still produce their numbers. Section 12's rule is that
    an unavailable method shows its reason and its status -- never a zero, and
    never another model quietly standing in for it.

    The import is local because `scenario.ml` needs xgboost, lightgbm and
    pandas, which the ACCEPTED environment does not have and must not need.
    A runtime without them reports MODEL_NOT_READY with the missing library
    named, which is the truth, rather than failing the turn.
    """
    if sp.ML not in spec.methods:
        return None, None, ""
    try:
        from backend.cockpit_v4.scenario.ml import infer
    except ImportError as exc:
        return None, None, (
            f"the emulator's libraries are not installed in this runtime "
            f"({exc}). Method 2 is unavailable here; Method 1 and the "
            f"user-defined method are not affected.")
    try:
        loaded = infer.load(domain_id, release_id=release_id)
    except Exception as exc:  # noqa: BLE001
        return None, None, _reason_of(exc)
    if not loaded.passed_every_gate:
        return loaded, None, (
            "this emulator did not pass its predeclared validation gates: "
            + "; ".join(loaded.failures())
            + ". Its estimate is model-development evidence and is not "
              "reported beside the accepted methods.")
    try:
        anchored = infer.for_scenario(loaded, spec=spec, rows=rows, plan=plan)
    except Exception as exc:  # noqa: BLE001
        return loaded, None, _reason_of(exc)
    return loaded, anchored, ""


def _reason_of(exc: Exception) -> str:
    return str(getattr(exc, "message", "") or exc) or type(exc).__name__


def _delta_headline(outcome: rn.Run) -> Decimal:
    """The movement the bridge attributes, which is Delta's.

    Attribution decomposes a DETERMINISTIC movement into the interventions
    that produced it. Delta is that movement: it is exact, it is per row, and
    the coalition values Shapley needs are re-runs of the same arithmetic. An
    emulator's change is a prediction, and decomposing a prediction by
    re-running the model on sub-coalitions would be a different quantity
    wearing the same word -- section 13.2's own separation, and why the ML
    explanation is its own section rather than another view here.
    """
    found = outcome.outcomes.get(sp.DELTA)
    if found is None or found.change is None:
        return Decimal(0)
    return found.change


def _ledgers(outcome: rn.Run, spec: sp.ScenarioSpec, *,
             rows: Sequence[Mapping[str, Any]], plan: dl.Plan,
             book_baseline: Decimal) -> dict[str, lg.Ledger]:
    """A reconciled per-row ledger for Delta. Built, then checked by `build`."""
    if sp.DELTA not in outcome.outcomes:
        return {}
    per_row = {str(row["entity_id"]): dl.scale_row(plan, dict(row))
               for row in rows}
    labels = {str(row["entity_id"]): str(row.get("owner_id") or "")
              for row in rows}
    return {sp.DELTA: lg.build(
        domain_id=spec.source.domain_id,
        period=spec.source.reporting_period,
        membership_hash=spec.cohort.membership_hash,
        results=per_row, labels=labels, book_baseline=book_baseline)}


def _bound_cohort(frozen: ch.Frozen) -> None:
    """Refuse a cohort larger than this arm declared it would carry."""
    if frozen.ref.entity_count > MAX_COHORT_ROWS:
        raise_for(BUDGET_EXCEEDED,
                  f"this selection is {frozen.ref.entity_count:,} exposures "
                  f"and a scenario step carries at most "
                  f"{MAX_COHORT_ROWS:,}. Narrow the cohort; nothing was "
                  f"calculated on part of it.",
                  field_path="cohort",
                  entity_count=frozen.ref.entity_count,
                  limit=MAX_COHORT_ROWS)


def _cohort_context(stored: Mapping[str, Any],
                    confirmed: sp.ScenarioSpec) -> dict[str, Any]:
    """What `cohort.reresolve` needs, from what the thread kept."""
    canonical = dict(stored.get("canonical") or {})
    cohort = dict(canonical.get("cohort") or {})
    return {
        "domain_id": confirmed.source.domain_id,
        "predicate": str(stored.get("cohort_predicate") or ""),
        "period": confirmed.source.reporting_period,
        "selection": str(stored.get("cohort_selection") or ch.BY_ROW),
        "cohort_id": confirmed.cohort.cohort_id,
        "described_as": str(stored.get("cohort_described_as") or ""),
        "fixed": bool(cohort.get("fixed", True)),
        "membership_hash": confirmed.cohort.membership_hash,
    }


def _stored_scenario(store: Any, *, run_id: str, tenant_id: str,
                     release_id: str, scope: Any) -> dict[str, Any]:
    """The scenario this thread is holding, or a refusal saying there is none.

    Read from `store.thread_context`, which only `worker.py` writes and only
    through the server-only `set_thread_context`. That is the whole reason a
    model may send a digest and nothing else: by the time it can ask for a
    run, the scenario is a fact the server recorded, not a payload.
    """
    record = store.get_run(run_id)
    thread_id = str(getattr(record, "thread_id", "") or "")
    if not thread_id:
        raise_for(CONFIRMATION_STALE,
                  "this run is not attached to a conversation, so there is "
                  "no confirmed scenario to execute.",
                  field_path="thread_id")
    seed = store.thread_context(thread_id, tenant_id=tenant_id)
    stored = th.read(seed)
    if stored is None:
        raise_for(CONFIRMATION_STALE,
                  "this conversation is not holding a scenario. A scenario is "
                  "previewed and approved before it runs, and nothing here "
                  "has been previewed.",
                  field_path="thread_id")
    status, reason = th.state_of(
        stored, release_id=release_id,
        release_fingerprint=str(getattr(scope, "release_fingerprint", "")
                                or ""))
    if status == th.INVALIDATED:
        raise_for(CONFIRMATION_STALE, reason, field_path="thread_id",
                  status=status)
    return stored


def _readiness(spec: sp.ScenarioSpec, *, release_id: str) -> dict[str, str]:
    """Which methods can run, with ML answered by its GATES rather than by a
    constant. `preview.readiness` owns the rule; this passes the book."""
    return pv.readiness(spec, release_id=release_id)


def _remember_spec(store: Any, *, run_id: str, tenant_id: str,
                   release_id: str, spec: sp.ScenarioSpec, frozen: ch.Frozen,
                   headline: str = "", executed: bool = False) -> None:
    """Publish the scenario as the artifact `thread.remember` looks for.

    Published by the RUN, read by `worker.py` after the answer settles, and
    written to the thread through `set_thread_context`. A model response is
    never the source: the artifact is the run's own record of what it did.

    The cohort's predicate, selection and description travel in the body
    alongside the canonical form, because `cohort.reresolve` needs them and
    `CohortRef.canonical` deliberately does not carry them -- a membership
    hash identifies a cohort, and re-deriving it needs the question that
    produced it.
    """
    stored = th.body(spec, domain_id=frozen.domain_id,
                     release_id=frozen.release_id,
                     release_fingerprint=frozen.release_fingerprint,
                     reporting_period=frozen.period, run_id=run_id,
                     headline=headline)
    if executed:
        # WHICH RUN ACTUALLY CALCULATED SOMETHING.
        #
        # `body["run_id"]` is set on both paths, because both are runs. It is
        # therefore not the answer to "has this been executed before": a
        # preview writes its own run id, and reading that back as a previous
        # execution made every first run report itself as a re-run of the
        # preview that produced it.
        stored["executed_run_id"] = run_id
    stored["cohort_predicate"] = frozen.predicate
    stored["cohort_selection"] = frozen.selection
    stored["cohort_described_as"] = frozen.described_as
    stored["cohort_owner_count"] = frozen.owner_count
    store.put_artifact(
        run_id=run_id, tenant_id=tenant_id, kind=th.ARTIFACT_KIND,
        release_id=release_id,
        scope={"step_id": "", "whatif_scenario_id": spec.scenario_id,
               "whatif_scenario_version": spec.version,
               "complete": True, "produced_rows": 1,
               "referenced_relations": [], "origin": "SYNTHETIC_DEMO"},
        columns=["kind", "body"],
        rows=[{"kind": th.KIND, "body": stored}])


#: One tidy table, so every number a reader is shown has a row id and every
#: section reconciles to the ones above it.
_RESULT_COLUMNS: tuple[str, ...] = (
    "section", "view", "method", "item", "scope", "baseline_sar_mn",
    "scenario_sar_mn", "change_sar_mn", "change_pct", "unit", "status",
    "note")


def _groups(spec: sp.ScenarioSpec, view: str
            ) -> dict[str, tuple[sp.Shock, ...]]:
    """The interventions this view attributes across.

    THE TWO VIEWS ARE NOT TWO NAMINGS OF ONE DECOMPOSITION, and section 13.2
    is explicit that they are never added together.

    The MECHANISM view groups by risk parameter: what moved in the
    calculation. A macro instruction that induced a PD move appears as the PD
    move, because that is the parameter the arithmetic used.

    The ECONOMIC view groups by root cause: `derived_from` walked back to the
    clause the reader wrote. A macro instruction and the PD move it induced
    are ONE intervention here, which is what stops a single economic
    statement being drawn as two additive bars.
    """
    out: dict[str, list[sp.Shock]] = {}
    for shock in spec.shocks:
        if view == at.MECHANISM:
            key = shock.field_id
        else:
            root = shock.derived_from or shock.field_id
            key = (shock.origin.strip() or root)[:80]
        out.setdefault(key, []).append(shock)
    return {k: tuple(v) for k, v in sorted(out.items())}


def _coalition_value(spec: sp.ScenarioSpec,
                     groups: Mapping[str, tuple[sp.Shock, ...]],
                     rows: Sequence[Mapping[str, Any]]):
    """A function from a set of group names to the cohort's scenario ECL.

    Each evaluation is a real Delta pass over the real rows with only those
    interventions in the plan -- not an interpolation and not a linearisation.
    That is what makes the interaction term a measurement rather than a
    residual, and it is also why `EXACT_LIMIT` is eight.
    """
    baseline = _total(rows, "ecl_sar_mn")
    cache: dict[frozenset[str], Decimal] = {frozenset(): baseline}

    def value(members: frozenset[str]) -> Decimal:
        if members in cache:
            return cache[members]
        shocks = tuple(s for name in sorted(members)
                       for s in groups.get(name, ()))
        if not shocks:
            cache[members] = baseline
            return baseline
        partial = dl.plan(spec.__class__(
            **{**{f.name: getattr(spec, f.name)
                  for f in spec.__dataclass_fields__.values()},
               "shocks": shocks, "state": sp.PREVIEW_READY,
               "confirmed_digest": ""}))
        total = sum((dl.scale_row(partial, dict(row)).scenario_ecl
                     for row in rows), Decimal(0))
        cache[members] = total
        return total

    return value, baseline


def _attribution(spec: sp.ScenarioSpec, *,
                 rows: Sequence[Mapping[str, Any]], plan: dl.Plan,
                 baseline: Decimal, headline: Decimal) -> at.Views:
    """Both views of WHY the ECL moved, each reconciled to the same headline.

    Exact Shapley up to `EXACT_LIMIT` groups, seeded paired permutations
    above it with the standard error and a NOT CONVERGED verdict published.
    The residual is shown as its own row by `Bridge.rows()` and is never
    spread across the drivers to make the arithmetic close.
    """
    made: dict[str, at.Bridge | None] = {}
    for view in (at.ECONOMIC, at.MECHANISM):
        groups = _groups(spec, view)
        names = sorted(groups)
        if not names:
            made[view] = None
            continue
        value, base = _coalition_value(spec, groups, rows)
        # `choose` names the method this many groups can afford, and all three
        # of its answers are honoured. A single intervention went to the
        # sampled estimator once, which spent 400 coalition evaluations
        # proving that one driver explains the whole of a change it is the
        # only cause of -- a correct answer at 200 times the price, and a
        # published standard error on a quantity that has none.
        method = at.choose(names)
        if method == at.SEQUENTIAL:
            running = [
                (name,
                 tuple(sorted({s.field_id for s in groups[name]})),
                 value(frozenset(names[:i + 1])))
                for i, name in enumerate(names)]
            made[view] = at.sequential(names, running, view=view,
                                       baseline=base, headline=headline)
        elif method == at.SHAPLEY:
            from itertools import combinations
            values: dict[frozenset[str], Decimal] = {}
            for size in range(1, len(names) + 1):
                for members in combinations(names, size):
                    key = frozenset(members)
                    values[key] = value(key)
            made[view] = at.exact(values, view=view, baseline=base,
                                  headline=headline)
        else:
            made[view] = at.sampled(names, value, view=view, baseline=base,
                                    headline=headline)
        if made[view] is not None:
            at.check(made[view])
    return at.Views(economic=made[at.ECONOMIC], mechanism=made[at.MECHANISM],
                    headline=headline)


def _summary(spec: sp.ScenarioSpec, *, rows: Sequence[Mapping[str, Any]],
             outcome: rn.Run, frozen: ch.Frozen, book_baseline: Decimal,
             book_rows: int, outside: Decimal,
             plan: dl.Plan) -> rs.Summary:
    """Section 13.1's hierarchy: cohort and book, before and after.

    The book's scenario total is the cohort's scenario total plus everything
    outside the cohort UNCHANGED, which is the identity the specification asks
    to hold rather than a second query that might not. `summarise` derives the
    coverage rate itself from each scope's own numbers, so a rate from one
    population can never be printed beside a total from another.
    """
    cohort_ecl = _total(rows, "ecl_sar_mn")
    cohort_ead = _total(rows, "ead_sar_mn")
    delta = outcome.outcomes.get(sp.DELTA)
    after = (delta.scenario if delta is not None and delta.scenario is not None
             else cohort_ecl)
    return rs.summarise(
        domain_id=spec.source.domain_id,
        period=spec.source.reporting_period,
        cohort_before={"Exposures": Decimal(len(rows)), "EAD": cohort_ead,
                       "Total ECL": cohort_ecl},
        cohort_after={"Exposures": Decimal(len(rows)), "EAD": cohort_ead,
                      "Total ECL": after},
        book_before={"Exposures": Decimal(book_rows),
                     "Total ECL": book_baseline},
        book_after={"Exposures": Decimal(book_rows),
                    "Total ECL": after + outside},
        cohort_rows=len(rows), book_rows=book_rows,
        unaffected_baseline=outside)


def _pct(baseline: Decimal, change: Decimal) -> Any:
    """Relative change, or the words for a baseline of zero.

    Never an infinity and never a blank: section 13.1 asks for "not defined"
    in so many words, because a reader who sees an empty cell cannot tell a
    zero baseline from a failed calculation.
    """
    if baseline == 0:
        return "not defined (the baseline is zero)"
    return str((change / baseline * 100).quantize(Decimal("0.0001")))


def _result_rows(spec: sp.ScenarioSpec, *, outcome: rn.Run,
                 summary: rs.Summary, views: at.Views,
                 ledgers: Mapping[str, lg.Ledger],
                 rows: Sequence[Mapping[str, Any]], frozen: ch.Frozen,
                 domain_id: str, loaded: Any, unavailable: str,
                 reply: str, previous_run_id: str = "",
                 run_id: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(section: str, item: str, **kw: Any) -> None:
        row = {c: "" for c in _RESULT_COLUMNS}
        row.update({"section": section, "item": item})
        row.update(kw)
        out.append(row)

    # -- what was run, and against what
    add("headline", "Scenario", scope=spec.scenario_id,
        note=f"version {spec.version}; "
             f"confirmed {spec.confirmed_digest[:12]}", status="CONFIRMED")
    add("headline", "Cohort", scope=spec.cohort.cohort_id,
        note=f"{spec.cohort.entity_count} {spec.cohort.grain}; membership "
             f"{spec.cohort.membership_hash[:12]}",
        status="RE-RESOLVED AND UNCHANGED")
    add("headline", "Release", scope=spec.source.release_id,
        note=f"period {spec.source.reporting_period}; fingerprint "
             f"{spec.source.release_fingerprint[:12]}")
    add("headline", "Approval", scope=reply[:60],
        note="the reader's own words, as they were given")
    add("headline", "This is a simulation",
        note=pv.SOURCE_UNTOUCHED, status="NO SOURCE ROW CHANGED")
    if previous_run_id and previous_run_id != run_id:
        add("headline", "This result was produced before",
            scope=previous_run_id, status="RE-RUN, NOT A SECOND RESULT",
            note=f"run {previous_run_id} ran this same confirmed scenario "
                 f"over this same frozen cohort. The engine is "
                 f"deterministic, so these are the same numbers reported "
                 f"again -- not a second opinion, and not two runs to "
                 f"average.")

    # -- section 13.1's hierarchy
    for scope_name, measures in (("cohort", summary.cohort),
                                 ("book", summary.book)):
        for measure in measures:
            add(scope_name, measure.name, scope=scope_name,
                baseline_sar_mn=str(measure.baseline),
                scenario_sar_mn=str(measure.scenario),
                change_sar_mn=str(measure.scenario - measure.baseline),
                change_pct=_pct(measure.baseline,
                                measure.scenario - measure.baseline),
                unit=measure.unit)
    add("book", "Outside the cohort", scope="book",
        baseline_sar_mn=str(summary.unaffected_baseline),
        scenario_sar_mn=str(summary.unaffected_baseline),
        change_sar_mn="0", unit="SAR million",
        status="UNAFFECTED",
        note="exactly zero, not approximately: no rule reached these rows")

    # -- every selected method, side by side, with its own status
    for method in rn.ORDER:
        if method not in spec.methods:
            continue
        got = outcome.outcomes.get(method)
        label = rn.LABELS.get(method, method)
        if got is None:
            add("method", label, method=method, status=rn.UNAVAILABLE,
                note=f"{method} was selected and produced no outcome.")
            continue
        add("method", label, method=method,
            baseline_sar_mn=str(got.baseline),
            scenario_sar_mn=("" if got.scenario is None
                             else str(got.scenario)),
            change_sar_mn=("" if got.change is None else str(got.change)),
            change_pct=("" if got.change is None
                        else _pct(got.baseline, got.change)),
            unit="SAR million", status=got.status,
            # A method that did not run leaves its cells EMPTY rather than
            # zero. Section 12: never insert a zero for an unavailable
            # method, because zero is a result and "no result" is not.
            note=got.reason or "; ".join(got.limitations))
    add("coverage", "Populations", note=outcome.coverage.describe(),
        status=("IDENTICAL" if outcome.coverage.uniform
                else "DIFFERENT PER METHOD"))
    if len(outcome.ran) > 1:
        add("coverage", "Method disagreement", note=outcome.disagreement(),
            status="EXPLAINED, NOT AVERAGED")

    # -- section 13.2's two views, separately labelled
    for view, bridge in (("attribution_economic", views.economic),
                         ("attribution_mechanism", views.mechanism)):
        if bridge is None:
            continue
        for line in bridge.rows():
            add(view, line["intervention"], view=bridge.view,
                method=bridge.method,
                scope=line["fields"],
                change_sar_mn=line["change_sar_mn"],
                unit="SAR million", status=line["converged"],
                note=(f"standard error "
                      f"{line['standard_error_sar_mn']} SAR million; "
                      f"sequence {line['sequence']}"))
        add(view, "Reconciles to", view=bridge.view,
            change_sar_mn=str(bridge.headline),
            note=f"explained {bridge.explained}, residual {bridge.residual}; "
                 f"{bridge.evaluations} coalition evaluations",
            status="CONVERGED" if bridge.converged() else "NOT CONVERGED")
    if views.economic is not None and views.mechanism is not None:
        add("attribution_economic", "The two views are never added",
            note=views.warning(), status="DO NOT SUM")

    # -- section 13.2 B: why the emulator predicted what it did
    for line in _ml_explanation(loaded, outcome=outcome,
                                unavailable=unavailable):
        out.append(line)

    for note in outcome.notes:
        add("note", "Run note", note=note)
    for name, book in ledgers.items():
        add("note", f"{rn.LABELS.get(name, name)} ledger",
            method=name, status="RECONCILED",
            note=f"{len(book.lines)} rows, each reconciled to the "
                 f"cohort total and the book total")
    return out


def _ml_explanation(loaded: Any, *, outcome: rn.Run,
                    unavailable: str) -> list[dict[str, Any]]:
    """Section 13.2 B, and NOT a decomposition of the scenario movement.

    Two different questions share the word "contribution" and answering one
    with the other is the specific error section 13.2 names. Scenario-impact
    attribution asks why ECL moved and is measured by re-running the
    calculation on sub-coalitions of interventions. This asks why the frozen
    emulator produced its number, and is a statement about the fitted
    function's response to its own inputs: association, not causation, and
    not a share of the ECL movement.

    So it lives in its own section, carries no `change_sar_mn`, and is
    absent entirely when Method 2 did not produce an estimate -- an
    explanation of a prediction nobody published would be an explanation of
    nothing.
    """
    rows: list[dict[str, Any]] = []

    def add(item: str, **kw: Any) -> None:
        row = {c: "" for c in _RESULT_COLUMNS}
        row.update({"section": "ml_explanation", "method": sp.ML,
                    "item": item})
        row.update(kw)
        rows.append(row)

    got = outcome.outcomes.get(sp.ML)
    if got is None or not got.ran:
        if unavailable:
            add("No explanation", status=rn.UNAVAILABLE,
                note=f"Method 2 produced no estimate, so there is no "
                     f"prediction to explain. {unavailable}")
        return rows
    try:
        from backend.cockpit_v4.scenario.ml import explain
    except ImportError:
        add("No explanation", status=rn.UNAVAILABLE,
            note="the explainability libraries are not installed in this "
                 "runtime.")
        return rows
    try:
        told = explain.for_outcome(loaded, facts=got.facts)
    except Exception as exc:  # noqa: BLE001
        add("No explanation", status=rn.UNAVAILABLE, note=_reason_of(exc))
        return rows
    for line in told:
        add(str(line.get("item", "")), scope=str(line.get("kind", "")),
            unit=str(line.get("unit", "")),
            status=str(line.get("status", "")),
            note=str(line.get("note", "")))
    add("What this is not",
        status="NOT A DECOMPOSITION OF THE SCENARIO MOVEMENT",
        note="These describe how the fitted function responds to its own "
             "inputs. They are association in a model, not causation, and "
             "they do not add up to the ECL change: that decomposition is "
             "the attribution sections above.")
    return rows


class _Clock:
    """The step's own deadline, enforced between phases.

    `_run_step` computes a per-step budget and enforces none of it: the SQL
    arm passes it to the engine, the Python arm passes it to the subprocess
    jail, and an in-process arm that ignored it would be the one step in the
    system that could outlive the run's clock. Checked between phases rather
    than by a watchdog thread, because every phase here is bounded work and a
    half-cancelled Decimal loop is harder to reason about than a refusal.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = max(0.5, float(seconds))
        self.started = time.monotonic()

    @property
    def spent(self) -> float:
        return time.monotonic() - self.started

    def check(self, phase: str) -> None:
        if self.spent > self.seconds:
            raise_for(BUDGET_EXCEEDED,
                      f"the scenario step reached its {self.seconds:.1f}s "
                      f"budget during {phase} and stopped. No partial result "
                      f"was published.",
                      field_path="deadline_seconds",
                      phase=phase, spent_seconds=round(self.spent, 3))


__all__ = ["EXECUTE", "EXECUTE_KEYS", "MAX_COHORT_ROWS", "MAX_SHOCKS",
           "OPERATIONS", "PREVIEW", "PREVIEW_KEYS", "Produced",
           "ExecuteRequest", "PreviewRequest", "SECTIONS", "SHOCK_KEYS",
           "as_step_failed", "execute", "validate"]
