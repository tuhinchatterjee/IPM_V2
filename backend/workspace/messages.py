"""Messages: governed objects travel between people (v3.1 §31, P7).

A message carries an object REFERENCE (id + version + summary card), never
rows or prose copied out of it. Opening it goes through the recipient's own
permissions and tenant scope, so a message cannot grant data access the
recipient does not already have. The recipient acts on the SAME object:

* scenario (defined, not executed): Open, Comment, Duplicate/Branch, Run on my
  cohort or book;
* scenario result (executed): Open analysis, Compare with my results,
  Duplicate the definition, Re-run on the latest data, Save a copy, Comment;
* cohort: Open in What-If, Investigate in Cockpit, Save a copy, Comment;
* comparison: Open, Save a copy, Comment.

A run started from a message is the recipient's own run, linked to the shared
definition (`shared_from`); its result is a new object, so the sender's
result is never changed. Comments attach to the version that was shared.

First launch seeds a shared Scenario Definition, a shared Scenario Result
and a shared cohort from a clearly synthetic colleague (§44 "seed before
show"), so the object-sharing experience is testable without setup.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from backend.workspace import access, cohorts, comparisons, runs, scenarios, sharing, whatif
from backend.workspace.objects import ObjectService, Principal

SEED_VERSION = "gw-messages-seed-1.0.0"
#: The synthetic colleague the demo messages come from. Named as synthetic
#: everywhere it appears.
SEED_SENDER = "head-of-corporate-credit.synthetic"
SYNTHETIC = "SYNTHETIC DEMO"


def _refuse(status: int, code: str, message: str) -> None:
    raise HTTPException(status, {"error_code": code, "message": message})


# ---- the inbox -----------------------------------------------------------------

def inbox(svc: ObjectService, who_raw: dict[str, Any], *, box: str = "inbox"
          ) -> dict[str, Any]:
    ensure_seeded(svc, who_raw)
    p = Principal.of(who_raw)
    rows = svc.store.shares_for(tenant_id=p.tenant, recipients=[p.id],
                                sent_by=p.id)
    items = []
    for r in rows:
        direction = "received" if r["to_id"] == p.id else "sent"
        if box == "inbox" and direction != "received":
            continue
        if box == "sent" and direction != "sent":
            continue
        items.append({"share_id": r["share_id"], "direction": direction,
                      "from_id": r["from_id"], "to_id": r["to_id"],
                      "object_id": r["object_id"], "version": r["version"],
                      "kind": r["kind"], "message": r["message"],
                      "created_at": r["created_at"],
                      "read_at": r.get("read_at") if direction == "received"
                      else None,
                      "seeded": r["seeded"], "card": r["card"]})
    unread = sum(1 for i in items if i["direction"] == "received"
                 and not i["read_at"])
    return {"box": box, "items": items, "unread": unread}


def _share_row(svc: ObjectService, p: Principal, share_id: str
               ) -> dict[str, Any]:
    row = svc.store.share(share_id, tenant_id=p.tenant)
    if row is None or (p.id not in (row["to_id"], row["from_id"])
                       and not p.admin):
        _refuse(404, "NOT_FOUND", "No such message is available to you.")
    return row


def _actions(obj: dict[str, Any], *, recipient: bool) -> list[dict[str, str]]:
    kind, b = obj["kind"], obj["body"]
    oid, ver = obj["object_id"], obj["version"]
    out: list[dict[str, str]] = []

    def add(action: str, label: str, href: str = "") -> None:
        out.append({"action": action, "label": label, "href": href})

    if kind == "scenario":
        add("open", "Open definition", f"/scenarios/{oid}?version={ver}")
        add("run", "Run on my cohort or book")
        add("duplicate", "Duplicate / branch")
    elif kind == "scenario_result":
        add("open", "Open analysis", f"/what-if/result/{oid}")
        add("compare", "Compare with my results")
        if b.get("entry") != "cockpit":
            add("rerun_latest", "Re-run on the latest data")
            add("run", "Run on my cohort")
            add("duplicate", "Duplicate the definition")
        else:
            add("open_thread", "Open the conversation",
                f"/cockpit/thread/{b.get('thread_id', '')}")
        add("save", "Save a copy")
    elif kind == "cohort":
        add("open", "Open in What-If", f"/what-if?cohort={oid}")
        add("investigate", "Investigate in Cockpit")
        add("save", "Save a copy")
    elif kind == "comparison":
        add("open", "Open comparison", f"/what-if/compare/{oid}")
        add("save", "Save a copy")
    elif kind == "alert":
        add("open", "Open Lens at the trigger",
            f"/lenses/{b['lens_id']}?alert={oid}")
        add("open_monitoring", "Open in Monitoring Centre",
            f"/monitoring?alert={oid}")
        if b.get("alert_type") == "breach":
            add("investigate", "Investigate in Cockpit")
            add("whatif", "What-If on this population")
    elif kind == "lens":
        add("open", "Open Lens", f"/lenses/{oid}")
        add("save", "Save my own copy")
    elif kind == "run":
        add("open", "Open the run", f"/what-if?run={oid}")
    elif kind == "investigation" and b.get("thread_id"):
        add("open", "Open the investigation",
            f"/cockpit/thread/{b['thread_id']}")
    elif kind == "issue" and b.get("issue_id"):
        add("open", "Open the issue", f"/issues/{b['issue_id']}")
    elif kind == "metric" and b.get("metric_id"):
        add("open", "Open in the Metric Catalogue",
            f"/metrics?m={b['metric_id']}")
    else:
        # Findings and anything without a page of its own open in the
        # governance Trace, which renders every object the viewer may read.
        add("open", "Open", f"/trace/object/{oid}")
    add("comment", "Comment")
    if not recipient:
        out = [a for a in out if a["action"] in ("open", "comment",
                                                 "open_thread",
                                                 "open_monitoring")]
    return out


def detail(svc: ObjectService, who_raw: dict[str, Any], share_id: str
           ) -> dict[str, Any]:
    p = Principal.of(who_raw)
    row = _share_row(svc, p, share_id)
    recipient = row["to_id"] == p.id
    if recipient:
        svc.store.mark_read(share_id, p.id)
    try:
        obj = svc.get(row["object_id"], p, version=row["version"])
        latest = svc.get(row["object_id"], p)
    except HTTPException:
        return {"share": {**row, "card": row["card"]}, "accessible": False,
                "reason": "This object is no longer available to you. A "
                          "message never grants access by itself.",
                "actions": [], "comments": []}
    comments = [c for c in svc.store.comments(row["object_id"],
                                              tenant_id=p.tenant)]
    return {"share": row, "accessible": True,
            "object": obj, "card": sharing.card_for(obj),
            "latest_version": latest["version"],
            "newer_content": latest["content_hash"] != obj["content_hash"],
            "actions": _actions(obj, recipient=recipient),
            "comments": comments,
            "attachments": row["card"].get("attachments", [])}


# ---- recipient actions ---------------------------------------------------------

def _shared(svc: ObjectService, p: Principal, share_id: str
            ) -> tuple[dict[str, Any], dict[str, Any]]:
    row = _share_row(svc, p, share_id)
    if row["to_id"] != p.id:
        _refuse(403, "NOT_RECIPIENT", "Only the recipient acts on a message.")
    return row, svc.get(row["object_id"], p, version=row["version"])


def _definition_of(obj: dict[str, Any]) -> tuple[str, int]:
    if obj["kind"] == "scenario":
        return obj["object_id"], obj["version"]
    if obj["kind"] == "scenario_result" and obj["body"].get("entry") != \
            "cockpit":
        return obj["body"]["scenario_id"], obj["body"]["scenario_version"]
    _refuse(422, "NOT_RUNNABLE", "This object carries no scenario definition "
                                 "to run. A result executed in a Cockpit "
                                 "conversation is re-run from that "
                                 "conversation.")
    raise AssertionError  # pragma: no cover


def run(svc: ObjectService, who_raw: dict[str, Any], share_id: str, *,
        cohort_id: str = "", baseline: Any = None, latest: bool = False
        ) -> dict[str, Any]:
    """The recipient's OWN run of the shared definition, linked to it."""
    p = Principal.of(who_raw)
    row, obj = _shared(svc, p, share_id)
    scenario_id, version = _definition_of(obj)
    if cohort_id:
        mine = svc.get(cohort_id, p)
        if mine["kind"] != "cohort":
            _refuse(422, "NOT_A_COHORT", f"{cohort_id} is not a cohort.")
    return runs.create(
        svc, who_raw, scenario_id=scenario_id, scenario_version=version,
        cohort_id=cohort_id, session_id=f"msg-{share_id}",
        baseline=baseline, entry="messages",
        shared_from={"share_id": share_id, "object_id": obj["object_id"],
                     "version": obj["version"], "kind": obj["kind"],
                     "from_id": row["from_id"],
                     "mode": "rerun_latest" if latest else "run"})


def duplicate(svc: ObjectService, who_raw: dict[str, Any], share_id: str
              ) -> dict[str, Any]:
    p = Principal.of(who_raw)
    _row, obj = _shared(svc, p, share_id)
    scenario_id, version = _definition_of(obj)
    return scenarios.clone(svc, who_raw, scenario_id, version=version,
                           operation="branch")


def save(svc: ObjectService, who_raw: dict[str, Any], share_id: str
         ) -> dict[str, Any]:
    p = Principal.of(who_raw)
    _row, obj = _shared(svc, p, share_id)
    if obj["kind"] == "scenario":
        return duplicate(svc, who_raw, share_id)
    if obj["kind"] == "lens":
        from backend.workspace import lenses

        return lenses.revise(svc, who_raw, obj["object_id"],
                             {"name": f"{obj['body']['name']} (my copy)"},
                             reason="saved from a message")
    if obj["kind"] not in ("scenario_result", "cohort", "comparison"):
        _refuse(422, "NOT_SAVEABLE", f"a {obj['kind']} is not copied.")
    return svc.duplicate(obj["object_id"], p, version=obj["version"],
                         title=f"{obj['title']} (saved from message)"[:160])


def compare(svc: ObjectService, who_raw: dict[str, Any], share_id: str,
            with_result_ids: list[str], method: str = "") -> dict[str, Any]:
    p = Principal.of(who_raw)
    _row, obj = _shared(svc, p, share_id)
    if obj["kind"] != "scenario_result":
        _refuse(422, "NOT_COMPARABLE", "only executed results are compared.")
    return comparisons.compare(svc, p, [obj["object_id"], *with_result_ids],
                               method=method)


def investigate(svc: ObjectService, who_raw: dict[str, Any], share_id: str
                ) -> dict[str, Any]:
    p = Principal.of(who_raw)
    _row, obj = _shared(svc, p, share_id)
    if obj["kind"] == "alert":
        from backend.workspace import monitoring

        return monitoring.investigate(svc, who_raw, obj["object_id"])
    if obj["kind"] != "cohort":
        _refuse(422, "NOT_A_COHORT", "only a cohort is investigated.")
    return whatif.investigate(who_raw, obj["object_id"])


def whatif_population(svc: ObjectService, who_raw: dict[str, Any],
                      share_id: str) -> dict[str, Any]:
    """An alert's population as a governed cohort for What-If."""
    from backend.workspace import monitoring

    p = Principal.of(who_raw)
    _row, obj = _shared(svc, p, share_id)
    if obj["kind"] != "alert":
        _refuse(422, "NOT_AN_ALERT", "only an alert carries a population.")
    return monitoring.cohort_for(svc, who_raw, obj["object_id"])


def comment(svc: ObjectService, who_raw: dict[str, Any], share_id: str,
            body: str) -> dict[str, Any]:
    p = Principal.of(who_raw)
    row = _share_row(svc, p, share_id)
    svc.get(row["object_id"], p, version=row["version"])
    text = body.strip()[:4000]
    if not text:
        _refuse(422, "EMPTY", "a comment needs text.")
    return svc.store.add_comment(tenant_id=p.tenant,
                                 object_id=row["object_id"],
                                 version=row["version"], author_id=p.id,
                                 body=text)


# ---- first launch ----------------------------------------------------------------

def _sender(who_raw: dict[str, Any]) -> dict[str, Any]:
    return {"id": SEED_SENDER, "tenant": access.tenant_of(who_raw),
            "roles": ("analyst",)}


def _seed_objects(svc: ObjectService, who_raw: dict[str, Any]
                  ) -> dict[str, str]:
    """The synthetic colleague's objects, made once per tenant."""
    tenant = access.tenant_of(who_raw)
    key = f"messages_seed_objects:{tenant}"
    stored = svc.store.meta(key)
    if stored:
        return json.loads(stored)
    sender = _sender(who_raw)
    sp_ = Principal.of(sender)
    scenarios.ensure_seeded(svc, sender)
    # "Construction Downside Sep-26" (§44 example), defined, NOT executed.
    definition = scenarios.clone(
        svc, sender, scenarios.template_object_id("CORP-02"),
        name="Construction Downside Sep-26", operation="duplicate")
    # An executed result: GDP recession on the whole Corporate book, Delta.
    run_ = runs.create(svc, sender,
                       scenario_id=scenarios.template_object_id("CORP-05"),
                       session_id="seed-messages", entry="messages")
    run_ = runs.confirm(svc, sender, run_["object_id"],
                        run_["body"]["contract"]["digest"])
    run_ = runs.choose_method(svc, sender, run_["object_id"], ["delta"])
    done = runs.execute(svc, sender, run_["object_id"])
    book = access.book(sender, "corporate")
    cohort = cohorts.freeze(
        book, svc, sp_, name="Hospitality — Stage 2 (synthetic demo)",
        filters=[{"column": "sector", "op": "in", "values": ["Hospitality"]},
                 {"column": "stage", "op": "in", "values": [2]}],
        source={"kind": "message"})
    ids = {"definition": definition["object_id"],
           "result": done["result"]["object_id"],
           "cohort": cohort["object_id"]}
    svc.store.set_meta(key, json.dumps(ids))
    return ids


def ensure_seeded(svc: ObjectService, who_raw: dict[str, Any]) -> None:
    p = Principal.of(who_raw)
    if p.id == SEED_SENDER:
        return
    key = f"messages_seed:{p.tenant}:{p.id}"
    if svc.store.meta(key) == SEED_VERSION:
        return
    try:
        ids = _seed_objects(svc, who_raw)
    except HTTPException:
        return  # a book is not published here: the inbox says EMPTY
    sender = Principal.of(_sender(who_raw))
    notes = {
        "definition": "Please review before Thursday's committee — defined, "
                      "not executed. Run it on your own cohort if useful.",
        "result": "GDP recession on the whole Corporate book, Delta. Compare "
                  "with your runs.",
        "cohort": "The Stage 2 hospitality names we discussed; investigate "
                  "or stress them without rebuilding the population.",
    }
    for key_, oid in ids.items():
        sharing.share(svc, sender, oid, to=[p.id],
                      message=f"[{SYNTHETIC}] {notes[key_]}", seeded=True)
    svc.store.set_meta(key, SEED_VERSION)


__all__ = ["SEED_SENDER", "SEED_VERSION", "compare", "comment", "detail",
           "duplicate", "ensure_seeded", "inbox", "investigate", "run",
           "save"]
