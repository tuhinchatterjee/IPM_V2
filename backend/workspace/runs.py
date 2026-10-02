"""What-If runs: scenario + governed cohort -> confirmed -> METHOD -> result.

The workspace twin of the Cockpit's preview/execute pair, on the SAME engine
objects (v3.1 §5.1, §5.2, §7.1):

    WAITING_BASELINE_CHOICE -> SCENARIO_PREVIEW -> (confirm) ->
    SCENARIO_CONFIRMED -> METHOD_SELECTION -> [METHOD_INPUT_REQUIRED |
    METHOD_UNAVAILABLE] -> READY_TO_EXECUTE -> EXECUTED

* Confirming a scenario never runs it. A confirmed run with no method stops
  at METHOD_SELECTION; there is no default method and no fallback from one
  method to another. An unavailable method (Retail ML while its G4 gate
  fails; a component no governed translation covers) is refused by name.
* A second run in the same What-If session asks which baseline it starts
  from -- the original reported book or the stressed result of a run
  already executed -- and never assumes (BASE01). Layering reuses the
  engine's own overlay chain (`scenario.layering`), so the Cockpit and the
  workspace stack scenarios identically.
* Execution rebuilds the engine contract from the pinned scenario version
  and the re-frozen cohort, and refuses unless it hashes to what was
  confirmed. The result is persisted as a `scenario_result` object carrying
  the universal dual-scope decomposition.
"""

from __future__ import annotations

import time
from dataclasses import replace
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from backend.cockpit_v4.scenario import bridge as br
from backend.cockpit_v4.scenario import cohort as ch
from backend.cockpit_v4.scenario import decomposition as dc
from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario import layering as lay
from backend.cockpit_v4.scenario import run as rn
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import userdefined as ud
from backend.cockpit_v4.scenario.errors import ScenarioError
from backend.workspace import access, cohorts
from backend.workspace import scenario_engine as se
from backend.workspace import scenario_library as lib
from backend.workspace.access import Book
from backend.workspace.objects import ObjectService, Principal, can_edit

WAITING_BASELINE_CHOICE = "WAITING_BASELINE_CHOICE"
SCENARIO_PREVIEW = "SCENARIO_PREVIEW"
SCENARIO_CONFIRMED = "SCENARIO_CONFIRMED"
METHOD_SELECTION = "METHOD_SELECTION"
METHOD_INPUT_REQUIRED = "METHOD_INPUT_REQUIRED"
METHOD_UNAVAILABLE = "METHOD_UNAVAILABLE"
READY_TO_EXECUTE = "READY_TO_EXECUTE"
EXECUTED = "EXECUTED"
STATES = (WAITING_BASELINE_CHOICE, SCENARIO_PREVIEW, SCENARIO_CONFIRMED,
          METHOD_SELECTION, METHOD_INPUT_REQUIRED, METHOD_UNAVAILABLE,
          READY_TO_EXECUTE, EXECUTED)

#: What the reader may choose. "compare" is several methods on one contract.
CHOICES = (sp.DELTA, sp.ML, sp.USER_DEFINED)
LABELS = {sp.DELTA: "Method 1 — Delta", sp.ML: "Method 2 — ML emulator",
          sp.USER_DEFINED: "Method 3 — User-defined",
          "compare": "Compare methods"}

TOP_CONTRIBUTORS = 12


def sl_stage_text(policy: str) -> str:
    from backend.workspace import scenario_library

    return scenario_library.STAGE_POLICIES.get(policy, policy)


def _refuse(status: int, code: str, message: str, **extra: Any) -> None:
    raise HTTPException(status, {"error_code": code, "message": message,
                                 **extra})


def _engine_error(exc: ScenarioError) -> HTTPException:
    return HTTPException(422, {"error_code": exc.code,
                               "message": str(exc.message)})


# ---- the population ----------------------------------------------------------

def _cohort_frozen(book: Book, svc: ObjectService, who: Principal,
                   cohort_id: str, version: int | None = None
                   ) -> tuple[ch.Frozen, dict[str, Any]]:
    """A saved cohort, re-frozen, and refused if its rows moved."""
    cohort = svc.get(cohort_id, who, version=version)
    if cohort["kind"] != "cohort":
        _refuse(422, "NOT_A_COHORT", f"{cohort_id} is not a cohort.")
    if cohort["domain_id"] != book.domain_id:
        _refuse(422, "INCOMPATIBLE_COHORT",
                f"The cohort is on the {cohort['domain_id']} book and the "
                f"scenario is {book.domain_id}. A scenario cannot span both.")
    body = cohort["body"]
    try:
        frozen = cohorts.resolve_stored(book, body)
    except ScenarioError as exc:
        raise _engine_error(exc) from exc
    if frozen.ref.membership_hash != body["membership_hash"]:
        _refuse(409, "MEMBERSHIP_CHANGED",
                f"{body['name']} no longer resolves to the rows it was "
                f"frozen with ({body['counts']['entities']} then, "
                f"{frozen.ref.entity_count} now). Refresh the cohort first.",
                expected=body["membership_hash"],
                resolved=frozen.ref.membership_hash)
    frozen = replace(frozen, ref=replace(frozen.ref, cohort_id=cohort_id),
                     described_as=body["name"])
    return frozen, {"cohort_id": cohort_id, "version": cohort["version"],
                    "name": body["name"], "source": "cohort"}


def _population(book: Book, svc: ObjectService, who: Principal,
                scenario: dict[str, Any], cohort_id: str,
                cohort_version: int | None = None
                ) -> tuple[ch.Frozen, dict[str, Any]]:
    """The run's population: the named cohort, the scenario's bound cohort,
    or the scenario's own scope -- in that order, and always stated."""
    scope = scenario["body"]["scope"]
    if cohort_id:
        return _cohort_frozen(book, svc, who, cohort_id, cohort_version)
    if scope["type"] == "cohort" and scope.get("cohort_id"):
        return _cohort_frozen(book, svc, who, scope["cohort_id"],
                              scope.get("cohort_version"))
    try:
        frozen = se.frozen_for_scope(book, scope,
                                     label=scope.get("label", ""))
    except ScenarioError as exc:
        raise _engine_error(exc) from exc
    return frozen, {"cohort_id": "", "version": None,
                    "name": scope.get("label") or "Scenario scope",
                    "source": "scenario_scope"}


def _cohort_body(frozen: ch.Frozen, origin: dict[str, Any]) -> dict[str, Any]:
    return {**frozen.to_context(), "object": origin,
            "description": frozen.describe()}


# ---- the contract ------------------------------------------------------------

def _definition(book: Book, scenario: dict[str, Any]) -> dict[str, Any]:
    return lib.normalise_definition(scenario["body"], book=book)


def _build(book: Book, scenario: dict[str, Any], frozen: ch.Frozen,
           baseline: dict[str, Any]) -> se.Built:
    try:
        return se.build(book, _definition(book, scenario), frozen=frozen,
                        scenario_id=scenario["object_id"],
                        version=int(scenario["version"]),
                        name=scenario["body"]["name"], baseline=baseline)
    except ScenarioError as exc:
        raise _engine_error(exc) from exc


def _availability(built: se.Built, *, release_id: str,
                  user_assumption: dict[str, Any] | None = None
                  ) -> dict[str, dict[str, Any]]:
    """Every method, READY or the reason it is not. Never a constant."""
    spec = replace(built.spec, user_assumption=dict(user_assumption or {}))
    engine = br.availability(spec, release_id=release_id)
    out: dict[str, dict[str, Any]] = {}
    for method in CHOICES:
        status = engine.get(method, "READY")
        reason = ""
        blocked = built.blockers.get(method) or []
        if method in (sp.DELTA, sp.ML) and blocked:
            status = "BLOCKED"
            reason = ("Not every component has a governed translation for "
                      "this method: " + "; ".join(blocked) + ". Nothing is "
                      "approximated; state the effect under User-defined.")
        elif method in (sp.DELTA, sp.ML) and not built.spec.shocks:
            status, reason = "NOT_APPLICABLE", "no component moves a " \
                                               "parameter this method reads."
        elif status.startswith("MODEL_NOT_READY"):
            reason = status.split(":", 1)[1].strip() if ":" in status \
                else status
            status = "UNAVAILABLE"
            reason = (f"ML emulator validation gate failed: {reason}. Shown, "
                      f"never substituted.")
        elif status == "NEEDS_ASSUMPTION":
            reason = ("You state the ECL impact (relative, absolute, target "
                      "amount, target rate or elasticity). Nothing is "
                      "guessed.")
        out[method] = {"status": status, "label": LABELS[method],
                       "reason": reason, "runnable": status == "READY"}
    ready = [m for m in CHOICES if out[m]["status"] in ("READY",
                                                        "NEEDS_ASSUMPTION")]
    out["compare"] = {"status": "AVAILABLE" if len(ready) > 1 else
                      "NOT_ENOUGH_METHODS", "label": LABELS["compare"],
                      "reason": "runs every chosen available method against "
                                "the same confirmed scenario, cohort and "
                                "baseline", "runnable": len(ready) > 1}
    return out


def _preview(built: se.Built, frozen: ch.Frozen,
             definition: dict[str, Any]) -> dict[str, Any]:
    """What the reader confirms: population, rules, policies, warnings."""
    shocks = [{"field": s.field_id, "operation": s.amount.operation,
               "value": str(s.amount.value),
               "origin": s.origin,
               "reach": (len(next(iter(s.where.values())))
                         if s.where else frozen.ref.entity_count)}
              for s in built.spec.shocks]
    return {
        "population": frozen.describe(),
        "entities": frozen.ref.entity_count,
        "owners": frozen.owner_count,
        "baseline_ead": frozen.ref.baseline_ead,
        "baseline_ecl": frozen.ref.baseline_ecl,
        "period": frozen.period,
        "components": [{"component_id": c["component_id"],
                        "label": c["label"], "kind": c["kind"]}
                       for c in definition["components"]],
        "shocks": shocks,
        "compositions": len(built.spec.compositions),
        "stage_policy": built.spec.stage_policy,
        "stage_policy_requested": definition.get("stage_policy", "frozen"),
        "stage_policy_text": sl_stage_text(definition.get("stage_policy",
                                                          "frozen")),
        "overlay_policy": built.spec.overlay_policy,
        "notes": list(built.notes),
        "blockers": built.blockers,
    }


# ---- the session's history and the baseline question ------------------------

def _session_runs(svc: ObjectService, who: Principal, session_id: str,
                  domain_id: str) -> list[dict[str, Any]]:
    if not session_id:
        return []
    return sorted((r for r in svc.list("run", who, domain_id=domain_id)
                   if r["body"].get("session_id") == session_id),
                  key=lambda r: r["created_at"])


def executed_in_session(svc: ObjectService, who: Principal, session_id: str,
                        domain_id: str) -> list[dict[str, Any]]:
    return [r for r in _session_runs(svc, who, session_id, domain_id)
            if r["status"] == EXECUTED]


def _options(executed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    period = executed[-1]["body"]["cohort"]["period"] if executed else ""
    out = [{"mode": lay.SOURCE_BASELINE,
            "label": f"Original reported baseline ({period})",
            "detail": "Start from the booked ECL, as if no scenario had run."}]
    for r in reversed(executed):
        b = r["body"]
        layered = b["baseline"].get("mode") == lay.PRIOR_SCENARIO
        out.append({"mode": lay.PRIOR_SCENARIO, "parent_run_id": r["object_id"],
                    "label": f"On top of: {b['scenario_name']}"
                             + (" (itself layered)" if layered else ""),
                    "detail": f"Layer on the stressed result of run "
                              f"{r['object_id']} ({', '.join(b['methods_ran'])}"
                              f"), cohort {b['cohort']['entity_count']} "
                              f"{b['cohort']['grain']}s."})
    return out


def _parse_baseline(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict) or raw.get("mode") not in lay.MODES:
        _refuse(422, "INVALID_BASELINE",
                "baseline.mode is SOURCE_BASELINE (the original reported "
                "book) or PRIOR_SCENARIO (with parent_run_id).")
    if raw["mode"] == lay.PRIOR_SCENARIO and not raw.get("parent_run_id"):
        _refuse(422, "INVALID_BASELINE", "a layered run names its parent "
                                         "run (parent_run_id).")
    return {"mode": raw["mode"],
            **({"parent_run_id": str(raw["parent_run_id"])}
               if raw["mode"] == lay.PRIOR_SCENARIO else {})}


def _link(parent: dict[str, Any]) -> dict[str, Any]:
    """One chain link, in the engine's own stored-link format
    (`bridge._LINK_KEYS`), so `bridge._chain_from` re-freezes and verifies
    it exactly as a Cockpit layered scenario is verified."""
    b = parent["body"]
    return {"scenario_id": b["contract"]["scenario_id"],
            "version": b["contract"]["version"],
            "name": b["scenario_name"],
            "canonical": b["contract"]["canonical"],
            "confirmed_digest": b["contract"]["confirmed_digest"],
            "cohort_predicate": b["cohort"]["predicate"],
            "cohort_selection": b["cohort"]["selection"],
            "reporting_period": b["cohort"]["period"],
            "cohort_id": b["cohort"]["cohort_id"],
            "methods": [sp.DELTA],
            "executed_run_id": parent["object_id"],
            "delta_change": b["delta_change"]}


def _lineage(svc: ObjectService, who: Principal, baseline: dict[str, Any] | None,
             *, domain_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The engine baseline block and the ancestor chain for a choice."""
    if not baseline or baseline["mode"] == lay.SOURCE_BASELINE:
        return {}, []
    parent = svc.get(baseline["parent_run_id"], who)
    pb = parent["body"]
    if parent["kind"] != "run" or parent["status"] != EXECUTED:
        _refuse(422, "PARENT_NOT_EXECUTED",
                "a scenario is layered on a run that has been executed.")
    if parent["domain_id"] != domain_id:
        _refuse(422, "BOOK_MISMATCH", "a layered scenario stays in its "
                                      "parent's book.")
    if not pb.get("delta_change"):
        _refuse(422, "PARENT_HAS_NO_ROW_STATE",
                "Layering stacks the parent's row-level parameter moves. "
                "This parent was executed without Delta, so its stressed book "
                "is not defined row by row. Run the parent with Delta (or "
                "Compare) first, or start from the original baseline.")
    chain = [*pb.get("chain", []), _link(parent)]
    return ({"mode": lay.PRIOR_SCENARIO,
             "parent_scenario_id": pb["contract"]["scenario_id"],
             "parent_contract_digest": pb["contract"]["confirmed_digest"],
             "parent_run_id": parent["object_id"]}, chain)


# ---- the state machine -------------------------------------------------------

def _write(svc: ObjectService, who: Principal, run: dict[str, Any],
           body: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    body = {**body, "state": status,
            "state_log": [*body.get("state_log", []),
                          {"state": status, "at": time.time(),
                           "reason": reason}]}
    return svc.revise(run["object_id"], who, body=body, status=status,
                      reason=reason)


def _prepare(book: Book, svc: ObjectService, who: Principal,
             scenario: dict[str, Any], frozen: ch.Frozen,
             baseline: dict[str, Any] | None) -> dict[str, Any]:
    engine_baseline, chain = _lineage(svc, who, baseline,
                                      domain_id=book.domain_id)
    built = _build(book, scenario, frozen, engine_baseline)
    definition = _definition(book, scenario)
    return {
        "baseline": engine_baseline or {"mode": lay.SOURCE_BASELINE},
        "chain": chain,
        "contract": {"scenario_id": built.spec.scenario_id,
                     "version": built.spec.version,
                     "canonical": built.spec.canonical(),
                     "digest": built.spec.digest(),
                     "confirmed_digest": ""},
        "preview": _preview(built, frozen, definition),
        "availability": _availability(built, release_id=book.release_id),
    }


def _refuse_unrunnable(book: Book, svc: ObjectService, who: Principal,
                       scenario: dict[str, Any]) -> None:
    """A run never starts on a definition that cannot honestly be executed.

    * A RETIRED scenario -- this version or its latest -- can be read and
      duplicated, not run (VAL-DEF-011): a share of an older version does
      not resurrect it.
    * Overlapping components whose composition policy is not chosen would
      be silently compounded by the engine, double counting the overlap
      (VAL-DEF-010, CRITICAL). The library already marks such a definition
      BLOCKED; the run refuses it by name until the policy is recorded.
    """
    latest = svc.get(scenario["object_id"], who)
    if "ARCHIVED" in (scenario["status"], latest["status"]):
        _refuse(409, "SCENARIO_RETIRED",
                f"{scenario['object_id']} was retired and cannot be run. "
                f"Duplicate it to run a copy of the definition.")
    pending = [b for b in lib.preview(book, scenario["body"])["blocking"]
               if b["code"] == "NEEDS_COMPOSITION_POLICY"]
    if pending:
        _refuse(409, "COMPOSITION_POLICY_REQUIRED",
                "Overlapping rules need an explicit composition policy before "
                "this scenario can run, so the overlap is never counted "
                "twice: " + "; ".join(b["message"] for b in pending[:5])
                + " Choose a policy for each overlap on the scenario page.")


def create(svc: ObjectService, who_raw: dict[str, Any], *, scenario_id: str,
           scenario_version: int | None = None, cohort_id: str = "",
           cohort_version: int | None = None, session_id: str = "",
           baseline: Any = None, entry: str = "whatif",
           shared_from: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start a run. Asks for the baseline when the session already ran one."""
    who = Principal.of(who_raw)
    scenario = svc.get(scenario_id, who, version=scenario_version)
    if scenario["kind"] != "scenario":
        _refuse(422, "NOT_A_SCENARIO", f"{scenario_id} is not a scenario.")
    book = access.book(who_raw, scenario["domain_id"])
    _refuse_unrunnable(book, svc, who, scenario)
    frozen, origin = _population(book, svc, who, scenario, cohort_id,
                                 cohort_version)
    chosen = _parse_baseline(baseline)
    body: dict[str, Any] = {
        "scenario_id": scenario["object_id"],
        "scenario_version": scenario["version"],
        "scenario_name": scenario["body"]["name"],
        "domain_id": book.domain_id, "release_id": book.release_id,
        "session_id": session_id, "entry": entry,
        "cohort": _cohort_body(frozen, origin),
        "methods_chosen": [], "methods_ran": [], "user_assumption": {},
        "result_id": "", "delta_change": "", "state_log": [],
        "shared_from": dict(shared_from or {}),
    }
    executed = executed_in_session(svc, who, session_id, book.domain_id)
    if executed and chosen is None:
        body.update({"state": WAITING_BASELINE_CHOICE, "baseline": {},
                     "chain": [], "contract": {},
                     "question": {
                         "text": "A scenario has already been executed in "
                                 "this session. Apply this one to the "
                                 "ORIGINAL reported baseline, or LAYER it on "
                                 "a scenario already run? Nothing is assumed.",
                         "options": _options(executed)}})
        status = WAITING_BASELINE_CHOICE
    else:
        body.update(_prepare(book, svc, who, scenario, frozen, chosen))
        status = SCENARIO_PREVIEW
    body["state"] = status
    body["state_log"] = [{"state": status, "at": time.time(),
                          "reason": "run started"}]
    return svc.create(
        "run", who, body, title=f"Run: {scenario['body']['name']}"[:160],
        domain_id=book.domain_id, release_id=book.release_id,
        fingerprint=book.fingerprint, period=frozen.period, status=status,
        lineage={"origin": "run", "derived_from": [
            [scenario["object_id"], scenario["version"]],
            *([[origin["cohort_id"], origin["version"]]]
              if origin["cohort_id"] else [])]})


def _load(svc: ObjectService, who: Principal, run_id: str) -> dict[str, Any]:
    run = svc.get(run_id, who)
    if run["kind"] != "run":
        _refuse(422, "NOT_A_RUN", f"{run_id} is not a What-If run.")
    if not can_edit(run, who):
        _refuse(403, "NOT_EDITABLE", "Only the run's owner advances it. "
                                     "Duplicate the scenario to run your own.")
    return run


def _scenario_and_population(svc: ObjectService, who: Principal,
                             who_raw: dict[str, Any], run: dict[str, Any]
                             ) -> tuple[Book, dict[str, Any], ch.Frozen]:
    b = run["body"]
    scenario = svc.get(b["scenario_id"], who, version=b["scenario_version"])
    book = access.book(who_raw, scenario["domain_id"])
    origin = b["cohort"]["object"]
    frozen, _o = _population(book, svc, who, scenario,
                             origin.get("cohort_id") or "",
                             origin.get("version"))
    if frozen.ref.membership_hash != b["cohort"]["membership_hash"]:
        _refuse(409, "MEMBERSHIP_CHANGED",
                "The run's population no longer resolves to the rows it was "
                "previewed on. Start a new run.")
    return book, scenario, frozen


def choose_baseline(svc: ObjectService, who_raw: dict[str, Any], run_id: str,
                    baseline: Any) -> dict[str, Any]:
    who = Principal.of(who_raw)
    run = _load(svc, who, run_id)
    if run["status"] != WAITING_BASELINE_CHOICE:
        _refuse(409, "INVALID_TRANSITION",
                f"this run is at {run['status']}; its baseline was already "
                f"chosen.")
    chosen = _parse_baseline(baseline)
    if chosen is None:
        _refuse(422, "INVALID_BASELINE", "choose a baseline.")
    book, scenario, frozen = _scenario_and_population(svc, who, who_raw, run)
    body = {**run["body"], **_prepare(book, svc, who, scenario, frozen,
                                      chosen)}
    body.pop("question", None)
    return _write(svc, who, run, body, SCENARIO_PREVIEW,
                  f"baseline chosen: {chosen['mode']}")


def confirm(svc: ObjectService, who_raw: dict[str, Any], run_id: str,
            digest: str) -> dict[str, Any]:
    """Confirm the scenario. NEVER runs it: the next state is METHOD
    SELECTION (UAT-01)."""
    who = Principal.of(who_raw)
    run = _load(svc, who, run_id)
    if run["status"] != SCENARIO_PREVIEW:
        _refuse(409, "INVALID_TRANSITION",
                f"a run is confirmed from {SCENARIO_PREVIEW}, not from "
                f"{run['status']}.")
    contract = run["body"]["contract"]
    if digest != contract["digest"]:
        _refuse(409, "CONFIRMATION_STALE",
                "the confirmation was given for a different preview. Review "
                "the current preview and confirm again.",
                expected=contract["digest"])
    body = {**run["body"], "contract": {**contract,
                                        "confirmed_digest": digest,
                                        "confirmed_at": time.time()}}
    confirmed = _write(svc, who, run, body, SCENARIO_CONFIRMED,
                       "scenario confirmed")
    return _write(svc, who, confirmed, confirmed["body"], METHOD_SELECTION,
                  "confirmed, NOT executed: choose the method")


def _normalise_assumption(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        _refuse(422, "INVALID_ASSUMPTION", "user_assumption is an object.")
    try:
        parsed = ud.from_payload(dict(raw))
    except ScenarioError as exc:
        raise _engine_error(exc) from exc
    except Exception as exc:  # Decimal conversion
        # The conversion error names a Python class; the analyst is told
        # what to correct instead.
        raise HTTPException(422, {
            "error_code": "INVALID_ASSUMPTION",
            "message": "user_assumption: every value must be a number "
                       "(for example 0.25 or -10)."}) from exc
    return {**parsed.canonical(), "stated_as": parsed.stated_as,
            "describe": parsed.describe()}


def choose_method(svc: ObjectService, who_raw: dict[str, Any], run_id: str,
                  methods: list[str], user_assumption: Any = None
                  ) -> dict[str, Any]:
    """Record the reader's method choice, or say why it cannot run."""
    who = Principal.of(who_raw)
    run = _load(svc, who, run_id)
    if run["status"] not in (METHOD_SELECTION, METHOD_INPUT_REQUIRED,
                             METHOD_UNAVAILABLE, READY_TO_EXECUTE):
        _refuse(409, "INVALID_TRANSITION",
                f"a method is chosen after the scenario is confirmed; this "
                f"run is at {run['status']}.")
    wanted = list(dict.fromkeys(str(m) for m in methods or []))
    if "compare" in wanted:
        wanted = [m for m in CHOICES
                  if run["body"]["availability"][m]["status"]
                  in ("READY", "NEEDS_ASSUMPTION")
                  and (m != sp.USER_DEFINED or user_assumption)]
    bad = [m for m in wanted if m not in CHOICES]
    if bad:
        _refuse(422, "UNKNOWN_METHOD", f"{bad} are not methods; choose from "
                                       f"{list(CHOICES)} or compare.")
    assumption = _normalise_assumption(user_assumption)
    avail = dict(run["body"]["availability"])
    if assumption:
        avail[sp.USER_DEFINED] = {**avail[sp.USER_DEFINED], "status": "READY",
                                  "reason": "", "runnable": True}
    body = {**run["body"], "methods_chosen": wanted,
            "user_assumption": assumption, "availability": avail}
    if not wanted:
        state, why = METHOD_SELECTION, "no method chosen: nothing runs"
    elif sp.USER_DEFINED in wanted and not assumption:
        state, why = METHOD_INPUT_REQUIRED, ("User-defined needs your "
                                            "impact assumption")
    elif not [m for m in wanted if avail[m]["status"] == "READY"]:
        state = METHOD_UNAVAILABLE
        why = "; ".join(f"{LABELS[m]}: {avail[m]['status']}" for m in wanted)
        why = f"chosen method cannot run ({why}); nothing is substituted"
    else:
        state, why = READY_TO_EXECUTE, "method chosen: " + ", ".join(
            LABELS[m] for m in wanted)
    body["gate_message"] = why
    return _write(svc, who, run, body, state, why)


def rerun(svc: ObjectService, who_raw: dict[str, Any], run_id: str
          ) -> dict[str, Any]:
    """The same confirmed contract, a new method choice (BASE06). A new run
    at METHOD_SELECTION; the scenario is not rebuilt or reconfirmed."""
    who = Principal.of(who_raw)
    source = svc.get(run_id, who)
    b = source["body"]
    if source["kind"] != "run" or not b.get("contract", {}).get(
            "confirmed_digest"):
        _refuse(409, "NOT_CONFIRMED", "only a confirmed run can be re-run "
                                      "with another method.")
    body = {**b, "methods_chosen": [], "methods_ran": [],
            "user_assumption": {}, "result_id": "", "delta_change": "",
            # In the body, not only the lineage: every later transition is a
            # revision, and a revision's lineage records its parent version.
            "variant_of": b.get("variant_of") or run_id,
            "state": METHOD_SELECTION,
            "state_log": [{"state": METHOD_SELECTION, "at": time.time(),
                           "reason": f"re-run of {run_id}: same confirmed "
                                     f"contract, choose the method"}]}
    return svc.derive("run", who, body, sources=[(run_id, source["version"])],
                      operation="rerun", title=source["title"],
                      status=METHOD_SELECTION, domain_id=source["domain_id"],
                      release_id=source["release_id"],
                      fingerprint=source["fingerprint"],
                      period=source["period"])


# ---- execution ---------------------------------------------------------------

def _stage_table(rows: list[dict[str, Any]], plan: dl.Plan
                 ) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Decimal]] = {}
    for r in rows:
        stage = str(int(r.get("stage") or 0)) if r.get("stage") is not None \
            else "?"
        res = dl.scale_row(plan, dict(r))
        agg = by.setdefault(stage, {"n": Decimal(0), "ead": Decimal(0),
                                    "before": Decimal(0), "after": Decimal(0)})
        agg["n"] += 1
        agg["ead"] += Decimal(str(r.get("ead_sar_mn") or 0))
        agg["before"] += res.baseline_ecl
        agg["after"] += res.scenario_ecl
    return [{"stage": s, "exposures": int(v["n"]), "ead": str(v["ead"]),
             "ecl_before": str(v["before"]), "ecl_after": str(v["after"]),
             "change": str(v["after"] - v["before"])}
            for s, v in sorted(by.items())]


def _top_contributors(rows: list[dict[str, Any]], plan: dl.Plan,
                      domain_id: str) -> list[dict[str, Any]]:
    label_col = "sector" if domain_id == "corporate" else "product"
    out = []
    for r in rows:
        res = dl.scale_row(plan, dict(r))
        before = Decimal(str(r.get("ecl_sar_mn") or 0))
        change = res.scenario_ecl - before
        if change:
            out.append({"entity_id": str(r["entity_id"]),
                        "owner_id": str(r.get("owner_id", "")),
                        "group": str(r.get(label_col, "") or ""),
                        "stage": str(r.get("stage", "")),
                        "ecl_before": str(before),
                        "ecl_after": str(res.scenario_ecl),
                        "change": str(change)})
    out.sort(key=lambda x: -abs(Decimal(x["change"])))
    return out[:TOP_CONTRIBUTORS]


def _calibration_gap(o: Any) -> str | None:
    facts = getattr(o, "facts", None) or {}
    raw, observed = facts.get("raw_model_baseline"), facts.get(
        "observed_modelled_ecl")
    if raw is None or observed is None:
        return None
    return str(Decimal(str(raw)) - Decimal(str(observed)))


#: Edges (percent) of the per-exposure change distribution.
DIST_EDGES = (-100, -50, -20, -10, -5, 0, 5, 10, 20, 30, 50, 100, 1_000_000)


def _pareto(rows: list[dict[str, Any]], plan: dl.Plan, domain_id: str
            ) -> list[dict[str, Any]]:
    """Delta change by segment, largest first, with the cumulative share
    (the top-contributor Pareto). Reconciles to the selected-scope change."""
    col = "sector" if domain_id == "corporate" else "product"
    by: dict[str, Decimal] = {}
    for r in rows:
        res = dl.scale_row(plan, dict(r))
        change = res.scenario_ecl - res.baseline_ecl
        key = str(r.get(col) or "(none)")
        by[key] = by.get(key, Decimal(0)) + change
    total = sum(by.values(), Decimal(0))
    out, running = [], Decimal(0)
    for key, change in sorted(by.items(), key=lambda kv: -abs(kv[1])):
        running += change
        out.append({"group": key, "dimension": col, "change": str(change),
                    "cumulative_share": None if not total else
                    str((running / total).quantize(Decimal("0.0001")))})
    return out


def _distribution(rows: list[dict[str, Any]], plan: dl.Plan
                  ) -> list[dict[str, Any]]:
    """How the per-exposure ECL change is distributed (percent of each
    exposure's own booked ECL), with the EAD in each band."""
    bins = [{"lo": lo, "hi": hi, "n": 0, "ead": Decimal(0)}
            for lo, hi in zip(DIST_EDGES[:-1], DIST_EDGES[1:], strict=True)]
    unaffected = {"n": 0, "ead": Decimal(0)}
    for r in rows:
        res = dl.scale_row(plan, dict(r))
        ead = Decimal(str(r.get("ead_sar_mn") or 0))
        if res.disposition != dl.SCALED or not res.baseline_ecl:
            unaffected["n"] += 1
            unaffected["ead"] += ead
            continue
        pct = (res.scenario_ecl / res.baseline_ecl - 1) * 100
        for b in bins:
            if b["lo"] <= pct < b["hi"]:
                b["n"] += 1
                b["ead"] += ead
                break
    return [{"label": f"{b['lo']}% to {b['hi']}%" if b["hi"] < 1_000_000
             else f"≥ {b['lo']}%", "lo": b["lo"], "hi": b["hi"],
             "n": b["n"], "ead": str(b["ead"])} for b in bins] + [
        {"label": "not moved by the scenario", "lo": None, "hi": None,
         "n": unaffected["n"], "ead": str(unaffected["ead"])}]


def _outcome(o: rn.Outcome) -> dict[str, Any]:
    change = o.change
    pct = (change / o.baseline * 100) if change is not None and o.baseline \
        else None
    return {"method": o.method, "label": LABELS.get(o.method, o.method),
            "status": o.status, "ran": o.ran, "baseline": str(o.baseline),
            "scenario": None if o.scenario is None else str(o.scenario),
            "change": None if change is None else str(change),
            "change_pct": None if pct is None else
            str(pct.quantize(Decimal("0.0001"))),
            "reason": o.reason, "limitations": list(o.limitations),
            # Method 2 only (M042): the emulator's own baseline gap, removed
            # by anchoring and published, never hidden.
            "calibration_gap": _calibration_gap(o)}


def execute(svc: ObjectService, who_raw: dict[str, Any], run_id: str
            ) -> dict[str, Any]:
    """Run the chosen methods on the confirmed contract; persist the result."""
    who = Principal.of(who_raw)
    run = _load(svc, who, run_id)
    b = run["body"]
    if run["status"] != READY_TO_EXECUTE:
        why = {METHOD_INPUT_REQUIRED: "The chosen method still needs your "
                                      "input (the user-defined assumption).",
               METHOD_UNAVAILABLE: "The chosen method is unavailable for "
                                   "this book; choose another method.",
               EXECUTED: "It has already been executed."}.get(
            run["status"], "A confirmed scenario runs only after a method "
                           "is chosen.")
        _refuse(409, "METHOD_SELECTION_REQUIRED" if run["status"] in (
            METHOD_SELECTION, SCENARIO_CONFIRMED) else "INVALID_TRANSITION",
            f"this run is at {run['status']}. {why} Nothing was executed.")
    book, scenario, frozen = _scenario_and_population(svc, who, who_raw, run)
    engine_baseline = {} if b["baseline"].get("mode") == lay.SOURCE_BASELINE \
        else dict(b["baseline"])
    built = _build(book, scenario, frozen, engine_baseline)
    if built.spec.digest() != b["contract"]["confirmed_digest"]:
        _refuse(409, "CONFIRMATION_STALE",
                "the scenario or its population changed since it was "
                "confirmed; nothing was run. Start a new run.",
                confirmed=b["contract"]["confirmed_digest"],
                now=built.spec.digest())
    avail = b["availability"]
    runnable = [m for m in b["methods_chosen"]
                if avail.get(m, {}).get("status") == "READY"]
    unavailable = {m: avail[m]["reason"] or avail[m]["status"]
                   for m in b["methods_chosen"] if m not in runnable}
    spec = replace(built.spec, state=sp.PREVIEW_READY).confirm()
    spec = replace(spec, methods=tuple(runnable),
                   user_assumption={k: v for k, v in
                                    b["user_assumption"].items()
                                    if k in ("form", "value",
                                             "driver_move_pct",
                                             "driver_field", "stated_as")})
    try:
        chain = br._chain_from({"chain": b["chain"]}, session=book.session,
                               domain_id=book.domain_id)
        offset = sum((Decimal(str(c.get("delta_change") or 0))
                      for c in b["chain"]), Decimal(0))
        done = br.compute_core(
            spec, session=book.session, domain_id=book.domain_id,
            release_id=book.release_id, frozen=frozen,
            rows_transform=lay.transform(chain) if chain else None,
            book_offset=offset)
    except ScenarioError as exc:
        raise _engine_error(exc) from exc
    decomposition = dc.from_computed(
        done, component_of=built.component_of, details=built.details,
        selected_label=frozen.describe()[:120], book_label="Total active book",
        # DECOMP21: by population identity, not by the absence of a
        # filter -- a filter that selects every exposure is the whole book.
        selected_equals_total=not chain and (
            not frozen.predicate
            or frozen.ref.entity_count == done.book_rows))
    for d in decomposition.values():
        dc.check(d)
    outcomes = {m: _outcome(o) for m, o in done.outcome.outcomes.items()}
    ran = list(done.outcome.ran)
    for m, o in done.outcome.outcomes.items():
        if not o.ran:
            unavailable.setdefault(m, o.reason or o.status)
    delta = done.outcome.outcomes.get(sp.DELTA)
    delta_change = str(delta.change) if delta is not None and delta.ran \
        and delta.change is not None else ""
    result_body = {
        "scenario_id": scenario["object_id"],
        "scenario_version": scenario["version"],
        "scenario_name": scenario["body"]["name"],
        "run_id": run["object_id"], "session_id": b["session_id"],
        "domain_id": book.domain_id, "release_id": book.release_id,
        "period": frozen.period, "cohort": b["cohort"],
        "baseline": b["baseline"], "chain": b["chain"],
        "contract_digest": spec.confirmed_digest,
        "execution_digest": spec.execution_digest(),
        "methods": {"chosen": b["methods_chosen"], "ran": ran,
                    "unavailable": unavailable},
        "user_assumption": b["user_assumption"],
        "results": outcomes,
        "book": {"baseline": str(done.book_baseline),
                 "outside_cohort": str(done.outside),
                 "rows": done.book_rows},
        "decomposition": decomposition,
        "stages": _stage_table(done.rows, done.plan)
        if sp.DELTA in ran else [],
        "top_contributors": _top_contributors(done.rows, done.plan,
                                              book.domain_id)
        if sp.DELTA in ran else [],
        "pareto": _pareto(done.rows, done.plan, book.domain_id)
        if sp.DELTA in ran else [],
        "change_distribution": _distribution(done.rows, done.plan)
        if sp.DELTA in ran else [],
        "notes": [*b["preview"]["notes"], *done.outcome.notes],
        "stage_policy": spec.stage_policy,
        # SCEN12: the policy the scenario asked for, carried into the
        # result (the engine's "explicit" is any non-frozen request).
        "stage_policy_requested": b["preview"].get("stage_policy_requested",
                                                   spec.stage_policy),
        "evidence": "Engine computation on the governed book; no model call.",
        "entry": b.get("entry", "whatif"),
        "shared_from": b.get("shared_from") or {},
    }
    result = svc.derive(
        "scenario_result", who, result_body,
        sources=[(scenario["object_id"], scenario["version"]),
                 (run["object_id"], run["version"])],
        operation="execute",
        title=f"Result: {scenario['body']['name']}"[:160],
        domain_id=book.domain_id, release_id=book.release_id,
        fingerprint=book.fingerprint, period=frozen.period)
    body = {**b, "methods_ran": ran, "methods_unavailable": unavailable,
            "result_id": result["object_id"], "delta_change": delta_change,
            "contract": {**b["contract"], "confirmed_digest":
                         spec.confirmed_digest}}
    run = _write(svc, who, run, body, EXECUTED,
                 "executed: " + ", ".join(LABELS[m] for m in ran))
    return {"run": run, "result": result}


def get(svc: ObjectService, who_raw: dict[str, Any], run_id: str
        ) -> dict[str, Any]:
    """A run as it stands. Reopening a confirmed, unexecuted run returns it
    at METHOD_SELECTION -- never executes it (UAT-01)."""
    who = Principal.of(who_raw)
    run = svc.get(run_id, who)
    if run["kind"] != "run":
        _refuse(422, "NOT_A_RUN", f"{run_id} is not a What-If run.")
    return run


def _change(svc: ObjectService, who: Principal, run: dict[str, Any]
            ) -> dict[str, Any]:
    rid = run["body"].get("result_id")
    if not rid:
        return {}
    try:
        res = svc.get(rid, who)
    except HTTPException:
        return {}
    return {m: {"change": v.get("change"), "change_pct": v.get("change_pct")}
            for m, v in res["body"]["results"].items() if v.get("ran")}


def tree(svc: ObjectService, who_raw: dict[str, Any], *, session_id: str,
         domain: str) -> dict[str, Any]:
    """The session's scenarios as a tree (§30): original baseline at the
    root, layered scenarios under their parent, method re-runs as variants
    of the run they re-used, combined definitions marked with their parts."""
    who = Principal.of(who_raw)
    domain_id = access.parse_domain(domain)
    nodes = [{"id": "baseline", "kind": "baseline",
              "label": "Original reported baseline"}]
    edges = []
    for r in _session_runs(svc, who, session_id, domain_id):
        b = r["body"]
        variant_of = str(b.get("variant_of") or "")
        parent = b.get("baseline", {}).get("parent_run_id") or "baseline"
        try:
            scenario = svc.get(b["scenario_id"], who,
                               version=b["scenario_version"])
            parts = [p.get("name") for p in scenario["body"].get("parents")
                     or []]
            combined = (scenario["lineage"] or {}).get("origin") == "combine"
        except HTTPException:
            parts, combined = [], False
        nodes.append({
            "id": r["object_id"], "kind": "run", "label": b["scenario_name"],
            "scenario_id": b["scenario_id"],
            "scenario_version": b["scenario_version"],
            "cohort": b["cohort"].get("description", ""),
            "entities": b["cohort"].get("entity_count"),
            "state": r["status"], "methods_ran": b.get("methods_ran", []),
            "baseline_mode": b.get("baseline", {}).get("mode", ""),
            "parent": parent, "variant_of": variant_of,
            "combined": combined, "combined_from": parts if combined else [],
            "result_id": b.get("result_id", ""),
            "results": _change(svc, who, r),
            "created_at": r["created_at"]})
        if variant_of:
            edges.append({"from": variant_of, "to": r["object_id"],
                          "kind": "method_variant"})
        else:
            edges.append({"from": parent, "to": r["object_id"],
                          "kind": "layered" if parent != "baseline"
                          else "baseline"})
    return {"session_id": session_id, "domain_id": domain_id,
            "nodes": nodes, "edges": edges}


def session_listing(svc: ObjectService, who_raw: dict[str, Any], *,
                    session_id: str, domain: str) -> list[dict[str, Any]]:
    who = Principal.of(who_raw)
    domain_id = access.parse_domain(domain)
    return [{**svc.summary(r), "state": r["status"],
             "scenario_name": r["body"]["scenario_name"],
             "baseline": r["body"].get("baseline", {}),
             "result_id": r["body"].get("result_id", ""),
             "methods_ran": r["body"].get("methods_ran", [])}
            for r in _session_runs(svc, who, session_id, domain_id)]


__all__ = ["CHOICES", "EXECUTED", "METHOD_INPUT_REQUIRED", "METHOD_SELECTION",
           "METHOD_UNAVAILABLE", "READY_TO_EXECUTE", "SCENARIO_CONFIRMED",
           "SCENARIO_PREVIEW", "STATES", "WAITING_BASELINE_CHOICE",
           "choose_baseline", "choose_method", "confirm", "create",
           "execute", "executed_in_session", "get", "rerun",
           "session_listing", "tree"]
