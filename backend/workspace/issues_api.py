"""
Guided Cockpit HTTP surface: Requires Attention, Investigate, and the
investigation path with its next-best questions.

Investigate opens an ORDINARY Cockpit thread (`RunStore.create_thread`) seeded
through the existing `attention_item` thread context -- the same path the
accepted "Investigate further" uses -- so every later turn is a governed
AdvancedCockpit run. It also freezes the issue's population as a governed
cohort and records an Investigation object whose path and suggestion clicks are
the audit trail of how the banker was guided (GX-05).
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import access, cohorts, issues, metrics, nbq, service
from backend.workspace import metric_catalog as mc
from backend.workspace.errors import GovernedRoute

router = APIRouter(tags=["workspace-guided"], route_class=GovernedRoute)

PATH_STEPS = ("Issue", "Evidence", "Driver", "Cohort", "Finding",
              "Scenario/Decision")


def _find(who: dict[str, Any], issue_id: str, domain: str = ""
          ) -> tuple[Any, dict[str, Any]]:
    domains = [access.parse_domain(domain)] if domain else ["corporate",
                                                            "retail"]
    for domain_id in domains:
        book = access.book(who, domain_id)
        card = issues.find(book, issue_id)
        if card is not None:
            return book, card
    raise HTTPException(404, {"error_code": "NOT_FOUND",
                              "message": "No such issue in the book in use. "
                                         "It may belong to an earlier "
                                         "release."})


@router.get("/issues")
async def list_issues(domain: str = Query("corporate"),
                      refresh: bool = Query(False),
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    book = access.book(who, domain)
    feed = issues.feed(book, refresh=refresh)
    return {**feed, "counts": {
        "total": len(feed["issues"]),
        "by_severity": {s: sum(1 for i in feed["issues"] if i["severity"] == s)
                        for s in ("critical", "high", "moderate", "low")}}}


@router.get("/issues/{issue_id}")
async def get_issue(issue_id: str, domain: str = Query(""),
                    who: dict[str, Any] = Depends(v4routes.principal)
                    ) -> dict[str, Any]:
    book, card = _find(who, issue_id, domain)
    extra = {}
    for metric_id in ("M005", "M015", "M052"):
        if mc.applies(mc.BY_ID[metric_id], book.domain_id):
            extra[metric_id] = metrics.series(
                book, metric_id, periods=8,
                filters=card["cohort"]["filters"] or None)
    return {**card, "context_series": extra}


class Investigate(BaseModel):
    domain: str = Field(default="", max_length=20)


def _investigation_body(card: dict[str, Any], *, thread_id: str,
                        cohort: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    return {
        "title": card["title"], "issue_id": card["issue_id"],
        "issue_rule": card["detection_rule"], "thread_id": thread_id,
        "domain_id": card["domain_id"],
        "cohort_id": cohort["object_id"],
        "cohort_membership_hash": cohort["body"]["membership_hash"],
        "path": [
            {"step": "Issue", "status": "done", "at": now,
             "detail": card["title"]},
            {"step": "Evidence", "status": "done", "at": now,
             "detail": f"{', '.join(card['evidence']['metric_ids'])}; "
                       f"{card['evidence']['prior_period']} → "
                       f"{card['evidence']['period']}"},
            {"step": "Driver", "status": "open", "at": None,
             "detail": (card["drivers"][0]["label"] if card["drivers"]
                        else "")},
            {"step": "Cohort", "status": "done", "at": now,
             "detail": f"{cohort['body']['counts']['entities']:,} "
                       f"{card['entity_plural']} frozen as "
                       f"{cohort['object_id']}"},
            {"step": "Finding", "status": "open", "at": None, "detail": ""},
            {"step": "Scenario/Decision", "status": "open", "at": None,
             "detail": ""}],
        "asked": [], "clicks": [],
        "suggestions_offered": [s["suggestion_id"] for s in
                                card["next_best_questions"]["primary"]],
    }


@router.post("/issues/{issue_id}/investigate", status_code=201)
async def investigate(issue_id: str, body: Investigate,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    book, card = _find(who, issue_id, body.domain)
    principal = service.principal(who)
    store = access.run_store()
    thread_id = store.create_thread(
        tenant_id=principal.tenant, principal_id=principal.id,
        domain_id=book.domain_id, release_id=book.release_id,
        release_fingerprint=book.fingerprint)
    store.set_thread_context(thread_id, tenant_id=principal.tenant,
                             kind="attention_item",
                             body=issues.seed_for_thread(card))
    store.set_thread_title(thread_id, tenant_id=principal.tenant,
                           title=card["title"][:120])
    svc = service.objects()
    cohort = cohorts.freeze(
        book, svc, principal, name=f"Issue cohort: {card['title'][:100]}",
        filters=card["cohort"]["filters"], source={
            "kind": "issue", "ref": card["issue_id"],
            "label": card["title"]},
        description=card["cohort"]["description"])
    inv = svc.create("investigation", principal,
                     _investigation_body(card, thread_id=thread_id,
                                         cohort=cohort),
                     title=card["title"], domain_id=book.domain_id,
                     release_id=book.release_id, fingerprint=book.fingerprint,
                     period=book.latest_period, trace_refs=[thread_id],
                     lineage={"origin": "issue", "issue_id": card["issue_id"],
                              "derived_from": [[cohort["object_id"], 1]]})
    return {"thread_id": thread_id, "investigation_id": inv["object_id"],
            "cohort_id": cohort["object_id"],
            "cohort": {k: cohort["body"][k] for k in (
                "counts", "ead", "ecl", "membership_hash", "filters",
                "filter_description")},
            "issue": {k: card[k] for k in ("issue_id", "title", "severity",
                                           "domain_id")},
            "suggestions": card["next_best_questions"]}


@router.post("/issues/{issue_id}/cohort")
async def issue_cohort(issue_id: str, body: Investigate,
                       who: dict[str, Any] = Depends(v4routes.principal)
                       ) -> dict[str, Any]:
    book, card = _find(who, issue_id, body.domain)
    return cohorts.freeze(
        book, service.objects(), service.principal(who),
        name=f"Issue cohort: {card['title'][:100]}",
        filters=card["cohort"]["filters"],
        source={"kind": "issue", "ref": card["issue_id"],
                "label": card["title"]},
        description=card["cohort"]["description"])


def _investigation_for_thread(who: dict[str, Any], thread_id: str
                              ) -> dict[str, Any] | None:
    principal = service.principal(who)
    for inv in service.objects().list("investigation", principal):
        if inv["body"].get("thread_id") == thread_id:
            return inv
    return None


def _state(who: dict[str, Any], inv: dict[str, Any]) -> dict[str, Any]:
    store = access.run_store()
    thread_id = inv["body"]["thread_id"]
    turns = store.thread_turns(thread_id)
    answered = [t["question"] for t in turns
                if (t.get("answer") or {}).get("narrative")
                or (t.get("answer") or {}).get("disposition") == "answer"]
    has_finding = bool(answered)
    book = access.book(who, inv["domain_id"])
    card = issues.find(book, inv["body"]["issue_id"])
    path = [dict(s) for s in inv["body"]["path"]]
    if has_finding:
        for step in path:
            if step["step"] in ("Driver", "Finding") and step["status"] != "done":
                step["status"] = "done"
                step["detail"] = step["detail"] or answered[-1][:160]
    if any(c.get("kind") == "run_whatif" for c in inv["body"].get("clicks", [])):
        path[-1]["status"] = "in_progress"
    suggestions = (nbq.for_issue(card, answered=answered +
                                 inv["body"].get("asked", []),
                                 cohort_hash=inv["body"]["cohort_membership_hash"],
                                 has_finding=has_finding)
                   if card else {"primary": [], "more": [], "suppressed": [],
                                 "note": "The issue is not in the current "
                                         "release's feed; its path is kept."})
    return {"investigation_id": inv["object_id"], "version": inv["version"],
            "thread_id": thread_id, "title": inv["title"],
            "issue_id": inv["body"]["issue_id"],
            "cohort_id": inv["body"]["cohort_id"], "path": path,
            "turns_answered": len(answered), "suggestions": suggestions,
            "clicks": inv["body"].get("clicks", [])}


@router.get("/investigations/by-thread/{thread_id}")
async def investigation_by_thread(thread_id: str,
                                  who: dict[str, Any] = Depends(
                                      v4routes.principal)) -> dict[str, Any]:
    inv = _investigation_for_thread(who, thread_id)
    if inv is None:
        return {"thread_id": thread_id, "investigation_id": None,
                "note": "This conversation did not start from a guided "
                        "issue. Ask freely; suggestions appear on "
                        "investigations."}
    return _state(who, inv)


class Step(BaseModel):
    suggestion_id: str = Field(default="", max_length=40)
    kind: str = Field(default="", max_length=40)
    question: str = Field(default="", max_length=2000)
    run_id: str = Field(default="", max_length=80)


@router.post("/investigations/{investigation_id}/steps")
async def record_step(investigation_id: str, step: Step,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    """Record a guided click: WHICH suggestion, WHY it was offered, and the
    exact request it submitted -- the trace of guidance (GX-05)."""
    svc = service.objects()
    principal = service.principal(who)
    inv = svc.get(investigation_id, principal)
    body = dict(inv["body"])
    card = None
    try:
        card = issues.find(access.book(who, inv["domain_id"]),
                           body["issue_id"])
    except HTTPException:
        card = None
    offered = {}
    if card:
        for s in (card["next_best_questions"]["primary"]
                  + card["next_best_questions"]["more"]):
            offered[s["suggestion_id"]] = s
        state = _state(who, inv)
        for s in state["suggestions"]["primary"] + state["suggestions"]["more"]:
            offered[s["suggestion_id"]] = s
    chosen = offered.get(step.suggestion_id)
    body["clicks"] = list(body.get("clicks", [])) + [{
        "suggestion_id": step.suggestion_id, "kind": step.kind or (
            chosen or {}).get("type", "free_form"),
        "exact_request": step.question or (chosen or {}).get(
            "exact_request", ""),
        "rationale": (chosen or {}).get("rationale", ""),
        "source": (chosen or {}).get("source", {}),
        "run_id": step.run_id, "at": time.time()}]
    if step.question:
        body["asked"] = list(body.get("asked", [])) + [step.question]
    updated = svc.revise(investigation_id, principal, body=body,
                         reason=f"guided step: {step.kind or 'question'}")
    return _state(who, updated)


__all__ = ["PATH_STEPS", "router"]


# ---- Early Warning (V4 runtime) -------------------------------------------------

EW_BANDS = ("critical", "high", "moderate", "low")


def _reason_token(label: str) -> str:
    """The longest leading part of a rule label the predicate layer will
    write into a query (it refuses `<`, `>`, `=`, `%` and never escapes)."""
    from backend.workspace import predicates

    token = ""
    for ch in label:
        if not predicates.SAFE_TEXT.match(ch):
            break
        token += ch
    return token.rstrip(" (")


def _reason_filter(book, reason: str) -> list[dict[str, Any]]:
    """A warning reason as a governed predicate. Only a label of the
    domain's own rule set is accepted (no free text reaches the query). The
    filter matches the label's safe leading token, and only when that token
    identifies exactly ONE rule of the set -- otherwise it refuses rather
    than over-match."""
    from backend.workspace import ews

    if not reason:
        return []
    labels = [r["label"] for r in ews.describe(book.domain_id)]
    if reason not in labels:
        raise HTTPException(422, {"error_code": "UNKNOWN_EWS_REASON",
                                  "message": f"{reason!r} is not a rule of "
                                             f"{ews.RULESET_VERSION}; they "
                                             f"are {labels}."})
    token = _reason_token(reason)
    if not token or sum(token.lower() in x.lower() for x in labels) != 1:
        raise HTTPException(422, {"error_code": "AMBIGUOUS_EWS_REASON",
                                  "message": f"{reason!r} cannot be filtered "
                                             f"exactly on this book."})
    return [{"column": "ews_reasons", "op": "contains", "value": token}]


@router.get("/early-warning")
async def early_warning(domain: str = Query("retail"),
                        reason: str = Query("", max_length=120),
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    """Governed EWS rule set over the book in use: bands, reasons, segments.

    `reason` cross-filters the bands, segments and severe list to exposures
    tripping that rule; the reasons chart itself ignores it (so every rule
    stays visible and selectable), as a chart ignores its own filter.
    """
    from backend.workspace import ews, grid

    book = access.book(who, domain)
    by_reason = _reason_filter(book, reason)
    segment = "sector" if book.domain_id == "corporate" else "product"
    bands = grid.grouped(book, dimension="ews_band", filters=by_reason)
    by_segment = []
    for value in [r["value"] for r in grid.grouped(book, dimension=segment,
                                                   filters=by_reason)]:
        rows = grid.grouped(book, dimension="ews_band", filters=[
            {"column": segment, "op": "eq", "value": value}, *by_reason])
        by_segment.append({"segment": value, "bands": rows})
    warned = grid.rows_for(book, filters=[{"column": "ews_band", "op": "in",
                                           "values": list(EW_BANDS)}],
                           columns=["ews_reasons", "ead_sar_mn"])[2]
    reasons: dict[str, dict[str, float]] = {}
    for row in warned:
        for tripped in str(row.get("ews_reasons") or "").split("; "):
            if tripped:
                slot = reasons.setdefault(tripped, {"n": 0, "ead": 0.0})
                slot["n"] += 1
                slot["ead"] += float(row.get("ead_sar_mn") or 0)
    top = grid.query(book, filters=[{"column": "ews_band", "op": "in",
                                     "values": ["critical", "high"]},
                                    *by_reason],
                     sort="ews_score", limit=25)
    trend = metrics.series(book, "M063", periods=8)
    return {"domain_id": book.domain_id, "release_id": book.release_id,
            "fingerprint": book.fingerprint, "period": book.latest_period,
            "ruleset": ews.RULESET_VERSION, "rules": ews.describe(book.domain_id),
            "segment_dimension": segment, "bands": bands,
            "by_segment": by_segment,
            "reasons": sorted(({"reason": k, **v} for k, v in reasons.items()),
                              key=lambda r: -r["n"]),
            "top": top["rows"], "severe_total": top["total"],
            "severe_ead_trend": trend["points"], "reason": reason,
            "filters": by_reason, "model_calls": 0}


class EarlyWarningCohort(BaseModel):
    domain: str = Field(default="retail", max_length=20)
    bands: list[str] = Field(default_factory=lambda: ["critical", "high"])
    segment: str = Field(default="", max_length=80)
    reason: str = Field(default="", max_length=120)


def _ew_filters(book, body: EarlyWarningCohort) -> list[dict[str, Any]]:
    bands = [b for b in body.bands if b in EW_BANDS] or ["critical", "high"]
    filters: list[dict[str, Any]] = [{"column": "ews_band", "op": "in",
                                      "values": bands}]
    if body.segment:
        dim = "sector" if book.domain_id == "corporate" else "product"
        filters.append({"column": dim, "op": "eq", "value": body.segment})
    return filters + _reason_filter(book, body.reason)


@router.post("/early-warning/cohort")
async def early_warning_cohort(body: EarlyWarningCohort,
                               who: dict[str, Any] = Depends(v4routes.principal)
                               ) -> dict[str, Any]:
    book = access.book(who, body.domain)
    filters = _ew_filters(book, body)
    label = f"EWS {'/'.join(filters[0]['values'])}" + (
        f" · {body.segment}" if body.segment else "") + (
        f" · {body.reason}" if body.reason else "")
    return cohorts.freeze(book, service.objects(), service.principal(who),
                          name=label, filters=filters,
                          source={"kind": "early_warning",
                                  "label": label, "ref": "gw-ews-1.0.0"})


@router.post("/early-warning/investigate", status_code=201)
async def early_warning_investigate(body: EarlyWarningCohort,
                                    who: dict[str, Any] = Depends(
                                        v4routes.principal)) -> dict[str, Any]:
    """Open a Cockpit investigation on the EXACT early-warning cohort."""
    book = access.book(who, body.domain)
    principal = service.principal(who)
    filters = _ew_filters(book, body)
    label = f"Early warning: {'/'.join(filters[0]['values'])} band" + (
        f" in {body.segment}" if body.segment else "") + (
        f" tripping '{body.reason}'" if body.reason else "")
    cohort = cohorts.freeze(book, service.objects(), principal, name=label,
                            filters=filters,
                            source={"kind": "early_warning", "label": label,
                                    "ref": "gw-ews-1.0.0"})
    store = access.run_store()
    thread_id = store.create_thread(
        tenant_id=principal.tenant, principal_id=principal.id,
        domain_id=book.domain_id, release_id=book.release_id,
        release_fingerprint=book.fingerprint)
    grain = cohort["body"]
    seed = {
        "item_id": cohort["object_id"], "origin": "early_warning",
        "domain_id": book.domain_id, "release_id": book.release_id,
        "release_fingerprint": book.fingerprint, "headline": label,
        "segment": body.segment, "segment_dimension":
        ("sector" if book.domain_id == "corporate" else "product")
        if body.segment else "portfolio",
        "reporting_period": book.latest_period,
        "comparison_period": book.periods[-2],
        "reporting_quarter": book.latest_period if book.domain_id == "corporate" else "",
        "comparison_quarter": book.periods[-2] if book.domain_id == "corporate" else "",
        "reporting_month": book.latest_period if book.domain_id == "retail" else "",
        "comparison_month": book.periods[-2] if book.domain_id == "retail" else "",
        "comparison_basis": "previous published period",
        "metric": "M063", "metric_label": "High/critical EWS EAD",
        "issue": (f"{grain['counts']['entities']:,} {grain['grain']} exposures "
                  f"({grain['counts']['owners']:,} owners) trip the governed "
                  f"EWS rule set gw-ews-1.0.0 at {', '.join(filters[0]['values'])}."),
        "why_it_appeared": "Early Warning selection by the banker.",
        "movement": "", "key_numbers": [
            {"label": "Exposures", "value": f"{grain['counts']['entities']:,}"},
            {"label": "EAD", "value": issues.fmt(grain['ead'], 'SAR_mn')},
            {"label": "ECL", "value": issues.fmt(grain['ecl'], 'SAR_mn')}],
        "evidence": {"cohort_id": cohort["object_id"], "predicate": filters},
        "drilldown": {"relation": grain["relation"],
                      "measure_fields": ["ead_sar_mn", "ecl_sar_mn", "stage",
                                         "pd_pit_12m", "dpd_days"],
                      "suggested_questions": [],
                      "entity_count": grain["counts"]["entities"]},
        "evidence_url": "/early-warning",
    }
    store.set_thread_context(thread_id, tenant_id=principal.tenant,
                             kind="attention_item", body=seed)
    store.set_thread_title(thread_id, tenant_id=principal.tenant,
                           title=label[:120])
    return {"thread_id": thread_id, "cohort_id": cohort["object_id"],
            "cohort": {k: grain[k] for k in ("counts", "ead", "ecl",
                                             "membership_hash", "filters")}}
