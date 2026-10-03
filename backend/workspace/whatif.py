"""The What-If Analysis workspace (P5): the book, the population, the handoffs.

One engine, two entrances (§30, §38). This module is the workspace's side of
the shared contracts -- it defines no scenario semantics of its own:

* the population is a governed cohort (`cohorts.freeze` over the grid view,
  i.e. the engine's own `scenario.cohort.freeze`);
* a scenario is a P4 Scenario Definition object, bound to that cohort;
* a conversation typed at the top of the page is an ordinary Cockpit run whose
  packet carries the active selection in `ui_filters` (the existing channel),
  and whose preview may name the saved cohort by id (`scenario.cohort_refs`);
* a conversation's own frozen cohort can be adopted as a governed cohort, and
  is refused unless the membership hash is identical.

So a manually selected set of rows and a conversationally defined cohort
resolve to ONE cohort contract: same predicate, same period, same membership
hash, same counts.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.cockpit_v4.scenario import cohort as ch
from backend.workspace import access, cohorts, grid, predicates, service
from backend.workspace.access import Book
from backend.workspace.objects import Principal

#: A manual row selection is a list of ids; the governed predicate caps a list
#: at 500 values (`predicates.MAX_VALUES`). Larger populations are selected by
#: filter ("select all filtered"), which has no size limit.
MAX_IDS = predicates.MAX_VALUES

MODES = ("rows", "filtered", "all")


def selection_filters(book: Book, selection: dict[str, Any]
                      ) -> list[dict[str, Any]]:
    """The selection as governed grid filters. Validated, never trusted."""
    mode = str(selection.get("mode") or "")
    if mode not in MODES:
        raise HTTPException(422, {"error_code": "NO_SELECTION",
                                  "message": "select rows, select everything "
                                             "the filters match, or choose "
                                             "the whole book."})
    v = grid.view(book)
    if mode == "rows":
        ids = [str(i) for i in (selection.get("ids") or [])]
        if not ids:
            raise HTTPException(422, {"error_code": "NO_SELECTION",
                                      "message": "no rows are selected."})
        if len(ids) > MAX_IDS:
            raise HTTPException(422, {"error_code": "SELECTION_TOO_LARGE",
                                      "message": f"{len(ids):,} rows; save a "
                                                 f"filter instead (limit "
                                                 f"{MAX_IDS:,})."})
        filters = [{"column": v.key, "op": "in", "values": ids}]
    elif mode == "filtered":
        filters = list(selection.get("filters") or [])
    else:
        filters = []
    return predicates.normalise(filters, columns=v.keys) if filters else []


def summary(book: Book, selection: dict[str, Any]) -> dict[str, Any]:
    """Counts, EAD, booked ECL, stage and band mix of the selection."""
    v = grid.view(book)
    filters = selection_filters(book, selection)
    where, params = predicates.bound(filters) if filters else ("", [])
    s = grid.summary(book, v=v, where=f"WHERE {where}" if where else "",
                     params=params)
    total = grid.summary(book, v=v, where="", params=[])
    spec = grid.SPEC[book.domain_id]
    return {**s, "filters": filters,
            "filter_description": predicates.describe(filters)
            if filters else "the whole active book",
            "mode": selection.get("mode"), "grain": spec["noun"],
            "grain_plural": spec["plural"], "owner_plural": spec["owner_plural"],
            "share_of_book_ead": s["ead"] / total["ead"] if total["ead"] else None,
            "share_of_book_ecl": s["ecl"] / total["ecl"] if total["ecl"] else None,
            "book": {"entities": total["entities"], "ead": total["ead"],
                     "ecl": total["ecl"]},
            "release_id": book.release_id, "fingerprint": book.fingerprint}


def save_selection(book: Book, who: dict[str, Any], selection: dict[str, Any],
                   *, name: str, by_owner: bool = False,
                   source_kind: str = "grid_selection") -> dict[str, Any]:
    filters = selection_filters(book, selection)
    return cohorts.freeze(
        book, service.objects(), Principal.of(who), name=name,
        filters=filters, selection=ch.BY_OWNER if by_owner else ch.BY_ROW,
        source={"kind": source_kind, "label": name,
                "mode": selection.get("mode")},
        snapshot=True)


def context(who: dict[str, Any], domain: str) -> dict[str, Any]:
    """What the workspace header shows: the book, its period and methods."""
    from backend.cockpit_v4.scenario.ml import infer

    book = access.book(who, domain)
    v = grid.view(book)
    total = grid.summary(book, v=v, where="", params=[])
    passed, failures, version = infer.gate_status(
        book.domain_id, release_id=book.release_id)
    spec = grid.SPEC[book.domain_id]
    return {
        "domain_id": book.domain_id, "release_id": book.release_id,
        "fingerprint": book.fingerprint, "period": book.latest_period,
        "period_kind": "quarter" if book.domain_id == "corporate" else "month",
        "grain": spec["noun"], "grain_plural": spec["plural"],
        "owner_plural": spec["owner_plural"], "key": v.key, "owner": v.owner,
        "book": {"entities": total["entities"], "owners": total["owners"],
                 "ead": total["ead"], "ecl": total["ecl"],
                 "stage_mix": total["stage_mix"]},
        "methods": {
            "delta": {"status": "AVAILABLE",
                      "label": "Method 1 — Delta (proportional on booked ECL)"},
            "ml": {"status": "AVAILABLE" if passed else "UNAVAILABLE",
                   "label": "Method 2 — ML emulator", "model_version": version,
                   "reason": "" if passed else
                   "Validation gate failed: " + "; ".join(failures) +
                   ". Never substituted by another method."},
            "user_defined": {"status": "NEEDS_ASSUMPTION",
                             "label": "Method 3 — User-defined impact"},
            "compare": {"status": "AVAILABLE" if passed else "PARTIAL",
                        "label": "Method 4 — Compare methods"},
        },
    }


def _seed(book: Book, cohort: dict[str, Any], *, label: str,
          origin: str) -> dict[str, Any]:
    """An `attention_item`-compatible seed: the existing seeded-thread path."""
    b = cohort["body"]
    corp = book.domain_id == "corporate"
    prior = book.periods[-2] if len(book.periods) > 1 else book.latest_period
    return {
        "item_id": cohort["object_id"], "origin": origin,
        "domain_id": book.domain_id, "release_id": book.release_id,
        "release_fingerprint": book.fingerprint, "headline": label,
        "segment": b.get("filter_description", ""),
        "segment_dimension": "cohort",
        "reporting_period": book.latest_period, "comparison_period": prior,
        "reporting_quarter": book.latest_period if corp else "",
        "comparison_quarter": prior if corp else "",
        "reporting_month": "" if corp else book.latest_period,
        "comparison_month": "" if corp else prior,
        "comparison_basis": "previous published period",
        "metric": "M001", "metric_label": "Booked ECL",
        "issue": (f"The governed cohort {cohort['object_id']} "
                  f"({b['counts']['entities']:,} {b['grain']} exposures, "
                  f"{b['counts']['owners']:,} owners): "
                  f"{b.get('filter_description') or b.get('description', '')}."),
        "why_it_appeared": "Selected by the banker in What-If Analysis.",
        "movement": "",
        "key_numbers": [
            {"label": "Exposures", "value": f"{b['counts']['entities']:,}"},
            {"label": "EAD (SAR m)", "value": f"{b['ead']:,.2f}"},
            {"label": "Booked ECL (SAR m)", "value": f"{b['ecl']:,.4f}"}],
        "evidence": {"cohort_id": cohort["object_id"],
                     "membership_hash": b["membership_hash"],
                     "predicate": b["filters"]},
        "drilldown": {"relation": b["relation"],
                      "measure_fields": ["ead_sar_mn", "ecl_sar_mn", "stage",
                                         "pd_pit_12m", "lgd_pct"],
                      "suggested_questions": [],
                      "entity_count": b["counts"]["entities"]},
        "evidence_url": f"/what-if?cohort={cohort['object_id']}",
    }


def investigate(who: dict[str, Any], cohort_id: str) -> dict[str, Any]:
    """Open an ordinary Cockpit thread about exactly this cohort."""
    principal = Principal.of(who)
    cohort = service.objects().get(cohort_id, principal)
    if cohort["kind"] != "cohort":
        raise HTTPException(422, {"error_code": "NOT_A_COHORT",
                                  "message": f"{cohort_id} is not a cohort."})
    book = access.book(who, cohort["domain_id"])
    store = access.run_store()
    thread_id = store.create_thread(
        tenant_id=principal.tenant, principal_id=principal.id,
        domain_id=book.domain_id, release_id=book.release_id,
        release_fingerprint=book.fingerprint)
    label = f"What-If cohort: {cohort['body']['name']}"[:120]
    store.set_thread_context(thread_id, tenant_id=principal.tenant,
                             kind="attention_item",
                             body=_seed(book, cohort, label=label,
                                        origin="whatif"))
    store.set_thread_title(thread_id, tenant_id=principal.tenant, title=label)
    return {"thread_id": thread_id, "cohort_id": cohort_id}


def thread_cohort(who: dict[str, Any], thread_id: str) -> dict[str, Any]:
    """The cohort a conversation froze, as the thread's server-written
    context holds it -- or a plain statement that it has none yet."""
    from backend.cockpit_v4.scenario import thread as th

    principal = Principal.of(who)
    store = access.run_store()
    owner = store.thread_owner(thread_id)
    if owner is None or owner[0] != principal.tenant or (
            owner[1] != principal.id and not principal.admin):
        raise HTTPException(404, {"error_code": "NOT_FOUND",
                                  "message": "No such conversation is "
                                             "available to you."})
    context = store.thread_context(thread_id, tenant_id=principal.tenant)
    stored = th.read(context) if context else None
    if not stored or "cohort_predicate" not in stored:
        # A conversation opened on a governed cohort (from a Lens, an alert,
        # Early Warning or What-If) names it in its seed: the page can offer
        # What-If on exactly that object.
        seed = (context or {}).get("body") or {}
        seeded = (seed.get("evidence") or {}).get("cohort_id", "") if (
            context or {}).get("kind") == "attention_item" else ""
        return {"thread_id": thread_id, "has_cohort": False,
                "seed_cohort_id": seeded if str(seeded).startswith("coh-")
                else "",
                "message": "This conversation has not frozen a cohort yet. "
                           "Ask for a scenario preview first."}
    return {"thread_id": thread_id, "has_cohort": True,
            "domain_id": stored["domain_id"],
            "release_id": stored["release_id"],
            "period": stored["reporting_period"],
            "membership_hash": stored["canonical"]["cohort"]["membership_hash"],
            "entities": stored["canonical"]["cohort"]["entity_count"],
            "owners": stored.get("cohort_owner_count"),
            "described_as": stored.get("cohort_described_as", ""),
            "selection": stored.get("cohort_selection", ch.BY_ROW),
            "scenario_id": stored["scenario_id"], "state": stored["state"],
            "run_id": stored.get("run_id", ""),
            "method_state": stored.get("method_state", ""),
            "executed_run_id": stored.get("executed_run_id", ""),
            "has_result": bool(stored.get("last_result")),
            "methods_ran": (stored.get("last_result") or {}).get(
                "methods_ran", []),
            "_predicate": stored["cohort_predicate"]}


def adopt_thread_result(who: dict[str, Any], thread_id: str
                        ) -> dict[str, Any]:
    """The scenario a conversation EXECUTED, as a governed Scenario Result.

    Nothing is recomputed: the thread holds the result its own run published
    (the same universal decomposition, both scopes). Idempotent per run.
    """
    from backend.cockpit_v4.scenario import thread as th

    principal = Principal.of(who)
    found = thread_cohort(who, thread_id)
    context = access.run_store().thread_context(thread_id,
                                                tenant_id=principal.tenant)
    stored = th.read(context) if context else None
    result = (stored or {}).get("last_result")
    if not found.get("has_cohort") or not result:
        raise HTTPException(409, {
            "error_code": "NOT_EXECUTED",
            "message": "This conversation has not executed a scenario. A "
                       "confirmed scenario runs only after a method is "
                       "chosen."})
    svc = service.objects()
    for r in svc.list("scenario_result", principal,
                      domain_id=stored["domain_id"]):
        if r["body"].get("cockpit_run_id") == result["run_id"]:
            return r
    canonical = stored["canonical"]
    cohort = {**canonical["cohort"],
              "predicate": stored["cohort_predicate"],
              "selection": stored.get("cohort_selection", ch.BY_ROW),
              "period": stored["reporting_period"],
              "owner_count": stored.get("cohort_owner_count"),
              "described_as": stored.get("cohort_described_as", ""),
              "description": stored.get("cohort_described_as", "")
              or "Conversation cohort",
              "object": {"cohort_id": "", "version": None,
                         "name": stored.get("cohort_described_as", ""),
                         "source": "conversation"}}
    body = {
        "scenario_id": stored["scenario_id"],
        "scenario_version": stored.get("version", 1),
        "scenario_name": stored.get("name") or "Conversation scenario",
        "run_id": result["run_id"], "cockpit_run_id": result["run_id"],
        "thread_id": thread_id, "session_id": thread_id, "entry": "cockpit",
        "domain_id": stored["domain_id"], "release_id": stored["release_id"],
        "period": stored["reporting_period"], "cohort": cohort,
        "baseline": dict(stored.get("baseline") or {})
        or {"mode": "SOURCE_BASELINE"},
        "chain": [{k: c.get(k) for k in ("scenario_id", "name",
                                         "executed_run_id", "delta_change")}
                  for c in stored.get("chain") or []],
        "contract_digest": stored.get("confirmed_digest", ""),
        "execution_digest": result.get("execution_digest", ""),
        "methods": {"chosen": [*result["methods_ran"],
                               *result["methods_unavailable"]],
                    "ran": result["methods_ran"],
                    "unavailable": result["methods_unavailable"]},
        "user_assumption": dict(stored.get("user_assumption") or {}),
        "results": result["results"], "book": result["book"],
        "decomposition": result["decomposition"], "stages": [],
        "top_contributors": [], "notes": result.get("notes", []),
        "stage_policy": result.get("stage_policy", "frozen"),
        "evidence": "Executed in a Cockpit conversation by the engine; "
                    "opened here without recomputation.",
    }
    book = access.book(who, stored["domain_id"])
    return svc.create(
        "scenario_result", principal, body,
        title=f"Result: {body['scenario_name']}"[:160],
        domain_id=stored["domain_id"], release_id=stored["release_id"],
        fingerprint=book.fingerprint, period=stored["reporting_period"],
        lineage={"origin": "conversation",
                 "source": {"thread_id": thread_id,
                            "run_id": result["run_id"]}})


def adopt_thread_cohort(who: dict[str, Any], thread_id: str, *, name: str = ""
                        ) -> dict[str, Any]:
    """The conversation's frozen cohort as a governed cohort object.

    Re-frozen from the engine's own stored predicate and refused unless the
    membership hash is identical, so it is provably the same population.
    """
    found = thread_cohort(who, thread_id)
    if not found["has_cohort"]:
        raise HTTPException(409, {"error_code": "NO_COHORT_YET",
                                  "message": found["message"]})
    book = access.book(who, found["domain_id"])
    if book.release_id != found["release_id"]:
        raise HTTPException(409, {"error_code": "RELEASE_MOVED",
                                  "message": "The conversation froze its "
                                             "cohort on another release."})
    # Idempotent: the conversation's population adopted again (a second
    # click, a Lens proposal reopened by browser Forward) is the cohort
    # already adopted, not another copy (VAL-DEF-049).
    principal = Principal.of(who)
    svc = service.objects()
    for c in svc.list("cohort", principal, domain_id=found["domain_id"]):
        b = c["body"]
        src = b.get("source") or {}
        if (c.get("owner_id") == principal.id and c.get("status") == "ACTIVE"
                and src.get("kind") == "conversation"
                and src.get("thread_id") == thread_id
                and src.get("run_id") == found["run_id"]
                and b.get("release_id") == book.release_id
                and b.get("membership_hash") == found["membership_hash"]):
            return c
    return cohorts.adopt(
        book, svc, principal,
        name=name or f"From conversation: {found['described_as'][:100]}",
        predicate=found["_predicate"], selection=found["selection"],
        period=found["period"], described_as=found["described_as"],
        expected_hash=found["membership_hash"],
        source={"kind": "conversation", "thread_id": thread_id,
                "run_id": found["run_id"],
                "scenario_id": found["scenario_id"]})


def active_context(cohort: dict[str, Any] | None,
                   scenario: dict[str, Any] | None) -> dict[str, Any]:
    """What rides in a run's `ui_filters`: the active selection, by reference.

    The analyst is told it may name the cohort by id in a preview; the
    population itself is never re-described from this block.
    """
    out: dict[str, Any] = {"surface": "whatif"}
    if cohort:
        b = cohort["body"]
        out["active_cohort"] = {
            "cohort_id": cohort["object_id"], "version": cohort["version"],
            "name": b["name"], "entities": b["counts"]["entities"],
            "owners": b["counts"]["owners"],
            "membership_hash": b["membership_hash"],
            "described_as": b.get("filter_description", ""),
            "period": b["period"],
            "how_to_use": ("To stress exactly this selection, pass "
                           "cohort={\"cohort_id\": \"" + cohort["object_id"] +
                           "\"} in preview_scenario. Do not re-describe it "
                           "with filters.")}
    if scenario:
        out["active_scenario"] = {"scenario_id": scenario["object_id"],
                                  "version": scenario["version"],
                                  "name": scenario["body"]["name"]}
    return out


__all__ = ["MAX_IDS", "active_context", "adopt_thread_cohort", "context",
           "investigate", "save_selection", "selection_filters", "summary",
           "thread_cohort"]
