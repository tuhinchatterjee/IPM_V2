"""Monitoring Centre (§33, P10): Lens refresh scheduling, alerts, delivery.

A workflow layer over governed metrics -- not a second analytical engine:

* SCHEDULE. `tick(now)` refreshes every Lens that is due by its cadence
  (daily / weekly / monthly by elapsed time; on_publication when a book's
  release fingerprint changed; on_result when a scenario result appeared;
  continuous on every tick; manual never). It runs in a daemon thread using
  the V4 runtime's own worker/supervisor model (`serve_forever` with a poll
  interval), and is deterministic: replaying a tick at the same instant on
  the same releases refreshes nothing twice (refresh is idempotent).
* ALERTS. Each SUCCEEDED observation's breach rules drive a governed `alert`
  object per dedup key (Lens + rule + book): NEW on first breach; ACTIVE when
  it persists; WORSENING when the observed value moves further past the
  threshold; RESOLVED when it no longer breaches. Readers may ACKNOWLEDGE,
  RESOLVE, assign or comment; an administrator may SUPPRESS. Every
  transition is an append-only event with actor, note and observed value;
  none changes source data.
* DELIVERY. A new breach, a worsening one, a Lens's material changes and a
  failed refresh reach the Inbox (Messages) of the Lens's owner and
  followers, with Open Lens / Investigate / What-If actions. A rule's
  cooldown suppresses repeats; worsening is always delivered.
* HONESTY. A FAILED refresh is an operational alert and a Lens shows it is
  stale; values are never presented as current from a failed refresh.
* DEMO HISTORY. First launch replays each seeded Lens's rules over the
  previous published periods and records what they would have raised,
  labelled HISTORICAL REPLAY (demo), closed -- never presented as live.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from fastapi import HTTPException

from backend.workspace import access, grid, lenses, metrics
from backend.workspace import metric_catalog as mc
from backend.workspace.objects import LIBRARY_OWNER, ObjectService, Principal, new_id

NEW, ACTIVE, WORSENING = "NEW", "ACTIVE", "WORSENING"
ACKNOWLEDGED, RESOLVED, SUPPRESSED = "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"
OPEN = (NEW, ACTIVE, WORSENING, ACKNOWLEDGED)
SENDER = "creditprobe-monitoring"
CADENCE_SECONDS = {"daily": 86400, "weekly": 7 * 86400,
                   "monthly": 30 * 86400, "continuous": 0}
SEVERITY_ORDER = {"critical": 0, "high": 1, "moderate": 2, "medium": 2,
                  "low": 3, "info": 4}
SEED_VERSION = "gw-monitoring-seed-1.0.0"
REPLAY_LENSES = ("lens-01", "lens-02", "lens-03", "lens-05", "lens-13",
                 "lens-14")


def _refuse(status: int, code: str, message: str) -> None:
    raise HTTPException(status, {"error_code": code, "message": message})


def _library(tenant: str) -> dict[str, Any]:
    return {"id": LIBRARY_OWNER, "tenant": tenant,
            "roles": ("administrator",)}


def _acting(lens: dict[str, Any]) -> dict[str, Any]:
    """Who a scheduled refresh runs as: the Lens's own owner."""
    if lens["owner_id"] == LIBRARY_OWNER:
        return _library(lens["tenant_id"])
    return {"id": lens["owner_id"], "tenant": lens["tenant_id"],
            "roles": ("analyst",)}


# ---- scheduling ---------------------------------------------------------------------

def due(svc: ObjectService, lens: dict[str, Any], now: float
        ) -> tuple[bool, str]:
    """Whether a Lens should refresh at `now`, and why (or why not)."""
    cadence = lens["body"]["refresh"]["cadence"]
    obs = svc.store.observations(lens["object_id"],
                                 tenant_id=lens["tenant_id"], limit=5)
    last = obs[0] if obs else None
    if cadence == "manual":
        return False, "manual refresh only"
    if last is None:
        return True, "never refreshed"
    if cadence in CADENCE_SECONDS:
        age = now - last["finished_at"]
        if last["status"] == "FAILED" and age >= 300:
            return True, "retrying after a failed refresh"
        if age >= CADENCE_SECONDS[cadence]:
            return True, f"{cadence} cadence elapsed"
        return False, f"next {cadence} refresh in " \
                      f"{int(CADENCE_SECONDS[cadence] - age)}s"
    if cadence == "on_publication":
        who = _acting(lens)
        try:
            prints = [access.book(who, d).fingerprint
                      for d in lens["body"]["domain_scope"]]
        except HTTPException:
            return True, "book unavailable: record the failure"
        if ",".join(prints) != last["fingerprint"]:
            return True, "a new release was published"
        return False, "no new release since the last refresh"
    if cadence == "on_result":
        newest = max((r["created_at"] for r in svc.store.latest_of_kind(
            "scenario_result", tenant_id=lens["tenant_id"])), default=0.0)
        if newest > last["finished_at"]:
            return True, "a scenario result was published"
        return False, "no new scenario result"
    return False, f"unknown cadence {cadence}"


def tick(svc: ObjectService, *, now: float | None = None,
         tenants: list[str] | None = None) -> dict[str, Any]:
    """Refresh every due Lens once. Deterministic for a given `now`."""
    now = time.time() if now is None else now
    report: dict[str, Any] = {"at": now, "refreshed": [], "skipped": [],
                              "failed": []}
    for tenant in tenants or svc.store.tenants_with("lens"):
        for lens in svc.store.latest_of_kind("lens", tenant_id=tenant):
            if lens["status"] == "ARCHIVED":
                continue
            go, why = due(svc, lens, now)
            if not go:
                report["skipped"].append({"lens": lens["object_id"],
                                          "why": why})
                continue
            cadence = lens["body"]["refresh"]["cadence"]
            trigger = {"on_publication": "on_publication",
                       "on_result": "on_result"}.get(cadence, "schedule")
            who = _acting(lens)
            obs = lenses.refresh(svc, who, lens["object_id"], trigger=trigger)
            after_refresh(svc, who, lens["object_id"], obs)
            (report["failed"] if obs["status"] == "FAILED"
             else report["refreshed"]).append(
                {"lens": lens["object_id"], "why": why,
                 "observation": obs["observation_id"],
                 "idempotent": bool(obs.get("idempotent"))})
    return report


class Scheduler:
    """The monitoring loop, in the V4 worker/supervisor thread model."""

    def __init__(self, poll_seconds: float = 300.0) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self.last: dict[str, Any] = {}

    def serve_forever(self) -> None:
        from backend.workspace import service

        while not self._stop.is_set():
            try:
                self.last = tick(service.objects())
            except Exception as exc:  # noqa: BLE001 - never kill the loop
                self.last = {"at": time.time(), "error": str(exc)[:500]}
            self._stop.wait(self.poll_seconds)

    def stop(self) -> None:
        self._stop.set()


_SCHEDULER: Scheduler | None = None
_SCHEDULER_LOCK = threading.Lock()


def ensure_scheduler() -> Scheduler | None:
    """Start the loop once, when enabled (`COCKPIT_V4_MONITORING_SCHEDULER`).
    Off in tests; the launchers turn it on."""
    global _SCHEDULER
    if os.environ.get("COCKPIT_V4_MONITORING_SCHEDULER", "") != "1":
        return None
    with _SCHEDULER_LOCK:
        if _SCHEDULER is None:
            _SCHEDULER = Scheduler(float(os.environ.get(
                "COCKPIT_V4_MONITORING_POLL_SECONDS", "300")))
            threading.Thread(target=_SCHEDULER.serve_forever, daemon=True,
                             name="guided-monitoring").start()
    return _SCHEDULER


# ---- alerts ----------------------------------------------------------------------------

def _worse(rule: dict[str, Any], new: float | None, old: float | None
           ) -> bool:
    if new is None or old is None:
        return False
    if rule["comparison"] in ("lt",):
        return new < old
    if rule["comparison"] in ("abs_gt",):
        return abs(new) > abs(old)
    return new > old


def _open_alert(svc: ObjectService, tenant: str, dedup: str
                ) -> dict[str, Any] | None:
    for a in svc.store.latest_of_kind("alert", tenant_id=tenant):
        b = a["body"]
        if b.get("dedup_key") == dedup and a["status"] in OPEN \
                and not b.get("demo_historical"):
            return a
    return None


def _event(svc: ObjectService, alert: dict[str, Any], frm: str, to: str,
           actor: str, note: str = "", observed: Any = None,
           at: float | None = None) -> None:
    svc.store.add_alert_event(tenant_id=alert["tenant_id"],
                              alert_id=alert["object_id"], from_state=frm,
                              to_state=to, actor_id=actor, note=note,
                              observed="" if observed is None
                              else str(observed), at=at)


def _system(tenant: str) -> Principal:
    return Principal(id=SENDER, tenant=tenant,
                     roles=frozenset({"administrator"}))


def _permissions(lens: dict[str, Any], svc: ObjectService) -> dict[str, Any]:
    perms = dict(lens["permissions"] or {})
    readers = set(perms.get("readers") or [])
    readers |= set(svc.store.subscribers(lens["object_id"],
                                         tenant_id=lens["tenant_id"]))
    if lens["owner_id"] != LIBRARY_OWNER:
        readers.add(lens["owner_id"])
    return {"visibility": perms.get("visibility", "private"),
            "readers": sorted(readers), "editors": []}


def _alert_body(lens, rule, obs, *, domain_filters, kind="breach"
                ) -> dict[str, Any]:
    spec = lens["body"]
    periods = dict(p.split(":", 1) for p in (obs.get("period") or "").split(",")
                   if ":" in p)
    b = {"alert_type": kind, "rule_id": rule.get("rule_id", kind),
         "rule_version": lens["version"], "rule_name": rule.get("name", ""),
         "lens_id": lens["object_id"], "lens_version": lens["version"],
         "lens_name": spec["name"], "domain_id": rule.get("domain", ""),
         "metric_id": rule.get("metric_id", ""),
         "metric_version": mc.BY_ID[rule["metric_id"]]["version"]
         if rule.get("metric_id") in mc.BY_ID else None,
         "unit": mc.BY_ID[rule["metric_id"]]["unit"]
         if rule.get("metric_id") in mc.BY_ID else "",
         "comparison": rule.get("comparison", ""),
         "threshold": rule.get("threshold"), "window": rule.get("window", ""),
         "observed": rule.get("observed"), "prior": rule.get("prior"),
         "severity": rule.get("severity", "info"),
         "state": NEW, "dedup_key": f"{lens['object_id']}:"
                                    f"{rule.get('rule_id', kind)}:"
                                    f"{rule.get('domain', '')}",
         "period": periods.get(rule.get("domain", ""), ""),
         "periods": periods, "release_id": obs.get("release_id", ""),
         "fingerprint": obs.get("fingerprint", ""),
         "filters": domain_filters, "observations": [obs["observation_id"]],
         "first_seen": obs["finished_at"], "last_seen": obs["finished_at"],
         "last_delivered_at": None, "assignee": "",
         "cooldown_hours": rule.get("cooldown_hours", 24),
         "demo_historical": False, "label": ""}
    return b


def _create(svc, lens, body, *, at: float | None = None) -> dict[str, Any]:
    tenant = lens["tenant_id"]
    return svc.create(
        "alert", _system(tenant), body,
        title=f"{body['lens_name']}: {body['rule_name'] or body['alert_type']}"
              [:160], domain_id=body["domain_id"] or "both",
        release_id=body["release_id"][:200], status=body["state"],
        permissions=_permissions(lens, svc), owner_id=SENDER,
        object_id=new_id("alert"), created_at=at,
        lineage={"origin": "monitoring", "lens": [lens["object_id"],
                                                  lens["version"]]})


def _move(svc, alert, to: str, *, actor: str, note: str = "",
          body_patch: dict[str, Any] | None = None, at: float | None = None
          ) -> dict[str, Any]:
    body = {**alert["body"], **(body_patch or {}), "state": to}
    out = svc.revise(alert["object_id"], _system(alert["tenant_id"]),
                     body=body, status=to, reason=f"{alert['status']} → {to}",
                     force=True)
    _event(svc, alert, alert["status"], to, actor, note,
           body.get("observed"), at=at)
    return out


def after_refresh(svc: ObjectService, who: dict[str, Any], lens_id: str,
                  obs: dict[str, Any]) -> dict[str, Any]:
    """Alerts and deliveries for one observation (idempotent per observation)."""
    principal = Principal.of(who)
    lens = svc.store.get(lens_id, tenant_id=principal.tenant)
    out: dict[str, Any] = {"created": [], "worsened": [], "resolved": [],
                           "delivered": 0}
    if lens is None or obs.get("idempotent"):
        return out
    body = obs["body"]
    if obs["status"] == "FAILED":
        dedup = f"{lens_id}:refresh_failure:"
        existing = _open_alert(svc, lens["tenant_id"], dedup)
        if existing is None:
            ab = _alert_body(lens, {"rule_id": "refresh_failure",
                                    "name": "Refresh failed",
                                    "severity": "high"}, obs,
                             domain_filters={}, kind="refresh_failure")
            ab["label"] = body.get("what_changed", "")
            created = _create(svc, lens, ab)
            _event(svc, created, "", NEW, SENDER, ab["label"])
            out["created"].append(created["object_id"])
            out["delivered"] += _deliver(svc, lens, created,
                                         f"Refresh FAILED — {lens['body']['name']}"
                                         f": {ab['label']}")
        return out
    # A successful refresh resolves an open failure.
    failure = _open_alert(svc, lens["tenant_id"], f"{lens_id}:refresh_failure:")
    if failure is not None:
        _move(svc, failure, RESOLVED, actor=SENDER,
              note="a later refresh succeeded")
    for rule_result in body.get("breaches") or []:
        rule = next((r for r in lens["body"]["breach_rules"]
                     if r["rule_id"] == rule_result["rule_id"]), rule_result)
        merged = {**rule, **rule_result}
        dedup = f"{lens_id}:{merged['rule_id']}:{merged['domain']}"
        existing = _open_alert(svc, lens["tenant_id"], dedup)
        filters = list((lens["body"].get("filters") or {}).get(
            merged["domain"]) or [])
        if merged["breached"]:
            if existing is None:
                ab = _alert_body(lens, merged, obs, domain_filters=filters)
                created = _create(svc, lens, ab)
                _event(svc, created, "", NEW, SENDER, "rule breached",
                       merged["observed"])
                out["created"].append(created["object_id"])
                out["delivered"] += _deliver(
                    svc, lens, created, _breach_text(lens, merged))
                continue
            eb = existing["body"]
            if obs["observation_id"] in eb.get("observations", []):
                continue
            patch = {"observed": merged["observed"],
                     "last_seen": obs["finished_at"],
                     "observations": [*eb.get("observations", []),
                                      obs["observation_id"]],
                     "release_id": obs.get("release_id", ""),
                     "fingerprint": obs.get("fingerprint", "")}
            if _worse(merged, merged["observed"], eb.get("observed")):
                moved = _move(svc, existing, WORSENING, actor=SENDER,
                              note="breach worsened", body_patch=patch)
                out["worsened"].append(moved["object_id"])
                out["delivered"] += _deliver(
                    svc, lens, moved, "WORSENING — " +
                    _breach_text(lens, merged), force=True)
            elif existing["status"] == NEW:
                _move(svc, existing, ACTIVE, actor=SENDER,
                      note="breach persists", body_patch=patch)
            else:
                svc.revise(existing["object_id"],
                           _system(existing["tenant_id"]),
                           body={**eb, **patch}, reason="breach persists",
                           force=True)
        elif existing is not None:
            moved = _move(svc, existing, RESOLVED, actor=SENDER,
                          note="no longer breaches",
                          body_patch={"observed": merged["observed"],
                                      "last_seen": obs["finished_at"]})
            out["resolved"].append(moved["object_id"])
    changes = body.get("material_changes") or []
    if changes:
        ab = _alert_body(lens, {"rule_id": "changes",
                                "name": f"{len(changes)} material changes",
                                "severity": "info"}, obs, domain_filters={},
                         kind="change")
        ab["changes"] = changes
        ab["label"] = body.get("what_changed", "")
        ab["dedup_key"] = f"{lens_id}:changes:{obs['observation_id']}"
        created = _create(svc, lens, ab)
        _event(svc, created, "", NEW, SENDER, ab["label"])
        out["created"].append(created["object_id"])
        out["delivered"] += _deliver(svc, lens, created,
                                     _changes_text(lens, changes))
    return out


def _fmt(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    v = float(value)
    if unit == "fraction":
        return f"{v * 100:.2f}%"
    if unit == "SAR_mn":
        return f"SAR {v:,.1f}m"
    return f"{v:,.4g}"


def _breach_text(lens, r) -> str:
    unit = mc.BY_ID.get(r["metric_id"], {}).get("unit", "")
    return (f"{lens['body']['name']} — {r['name']}: {r['metric_id']} "
            f"{r['domain']} observed {_fmt(r.get('observed'), unit)} vs "
            f"{r['comparison']} {r['threshold']} ({r['severity']}).")


def _changes_text(lens, changes) -> str:
    parts = [f"{c['name']} {_fmt(c['from'], c['unit'])} → "
             f"{_fmt(c['to'], c['unit'])}" for c in changes[:3]]
    return (f"{lens['body']['name']} — {len(changes)} material change"
            f"{'s' if len(changes) != 1 else ''}: " + "; ".join(parts) + ".")


def recipients(svc: ObjectService, lens: dict[str, Any]) -> list[str]:
    out = set(svc.store.subscribers(lens["object_id"],
                                    tenant_id=lens["tenant_id"]))
    if lens["owner_id"] != LIBRARY_OWNER:
        out.add(lens["owner_id"])
    for r in lens["body"].get("breach_rules") or []:
        out |= {x for x in r.get("recipients") or []
                if x not in ("owner", "team")}
    out.discard(SENDER)
    return sorted(out)


def _deliver(svc: ObjectService, lens: dict[str, Any], alert: dict[str, Any],
             text: str, *, force: bool = False) -> int:
    """Inbox cards for an alert; a rule's cooldown suppresses repeats."""
    if not lens["body"].get("delivery", {}).get("inbox", True):
        return 0
    b = alert["body"]
    now = time.time()
    last = b.get("last_delivered_at")
    if not force and last and now - last < 3600 * float(
            b.get("cooldown_hours") or 24):
        return 0
    from backend.workspace import sharing

    card = {**sharing.card_for(alert), "alert_type": b["alert_type"],
            "severity": b["severity"], "lens_id": b["lens_id"],
            "lens_name": b["lens_name"], "metric_id": b["metric_id"],
            "observed": b["observed"], "threshold": b["threshold"],
            "comparison": b["comparison"], "period": b["period"],
            "state": alert["status"], "changes": b.get("changes", [])}
    n = 0
    for user in recipients(svc, lens):
        svc.store.add_share(tenant_id=alert["tenant_id"],
                            object_id=alert["object_id"],
                            version=alert["version"], kind="alert",
                            from_id=SENDER, to_id=user, message=text,
                            card=card)
        n += 1
    if n:
        svc.revise(alert["object_id"], _system(alert["tenant_id"]),
                   body={**b, "last_delivered_at": now},
                   reason="delivered", force=True)
    return n


# ---- reader actions --------------------------------------------------------------------

ACTIONS = {"acknowledge": ACKNOWLEDGED, "resolve": RESOLVED,
           "suppress": SUPPRESSED, "reopen": ACTIVE}


def act(svc: ObjectService, who: dict[str, Any], alert_id: str, action: str,
        *, note: str = "", assignee: str = "") -> dict[str, Any]:
    principal = Principal.of(who)
    alert = svc.get(alert_id, principal)
    if alert["kind"] != "alert":
        _refuse(422, "NOT_AN_ALERT", f"{alert_id} is not an alert.")
    if alert["body"].get("demo_historical"):
        _refuse(409, "HISTORICAL", "a historical replay event is a record, "
                                   "not a live alert.")
    if action == "comment":
        if not note.strip():
            _refuse(422, "EMPTY", "a comment needs text.")
        _event(svc, alert, alert["status"], alert["status"], principal.id,
               note.strip()[:2000])
        return svc.get(alert_id, principal)
    if action == "assign":
        target = assignee or principal.id
        if alert["body"].get("assignee") == target:
            # Already assigned to that owner: a repeated click writes no new
            # version and no second "assigned to" event (VAL-DEF-008).
            return alert
        _event(svc, alert, alert["status"], alert["status"], principal.id,
               f"assigned to {target}")
        return svc.revise(alert_id, _system(alert["tenant_id"]),
                          body={**alert["body"], "assignee": target},
                          reason=f"assigned to {target}", force=True)
    if action not in ACTIONS:
        _refuse(422, "UNKNOWN_ACTION", f"actions: {sorted(ACTIONS)}, "
                                       f"comment, assign.")
    to = ACTIONS[action]
    if to == SUPPRESSED and not principal.admin:
        _refuse(403, "NOT_PERMITTED", "suppressing an alert is an "
                                      "administrator's governance decision.")
    allowed = {ACKNOWLEDGED: (NEW, ACTIVE, WORSENING),
               RESOLVED: (NEW, ACTIVE, WORSENING, ACKNOWLEDGED),
               SUPPRESSED: (NEW, ACTIVE, WORSENING, ACKNOWLEDGED),
               ACTIVE: (ACKNOWLEDGED, RESOLVED, SUPPRESSED)}
    if alert["status"] not in allowed[to]:
        _refuse(409, "INVALID_TRANSITION",
                f"an alert moves to {to} from {allowed[to]}, not from "
                f"{alert['status']}.")
    if to in (ACKNOWLEDGED, RESOLVED, SUPPRESSED) and not note.strip():
        _refuse(422, "NOTE_REQUIRED", "acknowledging, resolving or "
                                      "suppressing records why.")
    return _move(svc, alert, to, actor=principal.id, note=note.strip())


# ---- reading ------------------------------------------------------------------------------

VIEWS = ("new_today", "active", "worsening", "acknowledged", "resolved",
         "all", "changes", "history", "mine")


def listing(svc: ObjectService, who: dict[str, Any], *, view: str = "active",
            severity: str = "", lens_id: str = "", domain: str = "",
            assignee: str = "") -> dict[str, Any]:
    ensure_seeded(svc, who)
    principal = Principal.of(who)
    rows = svc.list("alert", principal)
    now = time.time()
    day0 = now - (now % 86400)

    def in_view(a: dict[str, Any]) -> bool:
        b = a["body"]
        if view == "history":
            return bool(b.get("demo_historical"))
        if b.get("demo_historical"):
            return view == "all"
        if view == "changes":
            return b["alert_type"] == "change"
        if b["alert_type"] == "change" and view != "all":
            return False
        return {"new_today": a["status"] == NEW and b["first_seen"] >= day0,
                "active": a["status"] in (NEW, ACTIVE, WORSENING),
                "worsening": a["status"] == WORSENING,
                "acknowledged": a["status"] == ACKNOWLEDGED,
                "resolved": a["status"] in (RESOLVED, SUPPRESSED),
                "mine": b.get("assignee") == principal.id,
                "all": True}.get(view, True)

    out = [a for a in rows if in_view(a)
           and (not severity or a["body"]["severity"] == severity)
           and (not lens_id or a["body"]["lens_id"] == lens_id)
           and (not domain or a["body"]["domain_id"] in (domain, ""))
           and (not assignee or a["body"].get("assignee") == assignee)]
    out.sort(key=lambda a: (SEVERITY_ORDER.get(a["body"]["severity"], 9),
                            -a["body"]["last_seen"]))
    counts = {v: 0 for v in ("new", "active", "worsening", "acknowledged",
                             "resolved", "changes", "history")}
    for a in rows:
        b = a["body"]
        if b.get("demo_historical"):
            counts["history"] += 1
        elif b["alert_type"] == "change":
            counts["changes"] += 1
        else:
            key = {NEW: "new", ACTIVE: "active", WORSENING: "worsening",
                   ACKNOWLEDGED: "acknowledged", RESOLVED: "resolved",
                   SUPPRESSED: "resolved"}[a["status"]]
            counts[key] += 1
    return {"view": view, "alerts": [_summary(a) for a in out],
            "counts": counts, "total": len(rows),
            "state": "OK" if out else ("EMPTY_BY_FILTER" if rows
                                       else "NOT_CONFIGURED"),
            "lens_health": _lens_health(svc, principal)}


def _summary(a: dict[str, Any]) -> dict[str, Any]:
    b = a["body"]
    return {"alert_id": a["object_id"], "version": a["version"],
            "state": a["status"], "title": a["title"],
            **{k: b.get(k) for k in (
                "alert_type", "severity", "lens_id", "lens_name", "rule_id",
                "rule_name", "metric_id", "metric_version", "unit", "domain_id",
                "comparison", "threshold", "observed", "prior", "period",
                "first_seen", "last_seen", "assignee", "demo_historical",
                "label", "release_id")}}


def _lens_health(svc: ObjectService, principal: Principal
                 ) -> list[dict[str, Any]]:
    out = []
    for lens in svc.list("lens", principal):
        obs = svc.store.observations(lens["object_id"],
                                     tenant_id=principal.tenant, limit=5)
        last = obs[0] if obs else None
        ok = next((o for o in obs if o["status"] == "SUCCEEDED"), None)
        go, why = due(svc, lens, time.time())
        out.append({"lens_id": lens["object_id"], "name": lens["title"],
                    "cadence": lens["body"]["refresh"]["cadence"],
                    "last_status": last["status"] if last else "NEVER",
                    "last_at": last["finished_at"] if last else None,
                    "last_success_at": ok["finished_at"] if ok else None,
                    "stale": bool(last and last["status"] == "FAILED"),
                    "due": go, "why": why})
    return out


def detail(svc: ObjectService, who: dict[str, Any], alert_id: str
           ) -> dict[str, Any]:
    principal = Principal.of(who)
    alert = svc.get(alert_id, principal)
    if alert["kind"] != "alert":
        _refuse(422, "NOT_AN_ALERT", f"{alert_id} is not an alert.")
    b = alert["body"]
    events = svc.store.alert_events(alert_id, tenant_id=principal.tenant)
    cross = [{**f, "domain": b["domain_id"]} for f in b.get("filters") or []]
    return {"alert": alert, "events": events,
            "open_lens": {"lens_id": b["lens_id"], "periods": b.get(
                "periods") or {}, "filters": cross},
            "metric": mc.BY_ID.get(b.get("metric_id") or "", {}).get("name"),
            "can_act": not b.get("demo_historical")}


def cohort_for(svc: ObjectService, who: dict[str, Any], alert_id: str
               ) -> dict[str, Any]:
    """The alert's affected population as a governed cohort (the Lens's
    scope on the alert's book), so Investigate / What-If never rebuild it."""
    from backend.workspace import cohorts

    principal = Principal.of(who)
    alert = svc.get(alert_id, principal)
    b = alert["body"]
    if b["alert_type"] != "breach" or not b.get("domain_id"):
        _refuse(422, "NO_POPULATION", "only a breach alert names a book and "
                                      "population to investigate.")
    book = access.book(who, b["domain_id"])
    return cohorts.freeze(
        book, svc, principal, name=f"Alert: {alert['title']}"[:150],
        filters=b.get("filters") or [],
        source={"kind": "manual", "ref": alert_id, "label": alert["title"]},
        description=f"Population of {b['lens_name']} on {b['domain_id']} at "
                    f"{b.get('period')}")


def investigate(svc: ObjectService, who: dict[str, Any], alert_id: str
                ) -> dict[str, Any]:
    """The alert's population as a governed cohort, then a Cockpit thread."""
    from backend.workspace import whatif

    principal = Principal.of(who)
    alert = svc.get(alert_id, principal)
    cohort = cohort_for(svc, who, alert_id)
    thread = whatif.investigate(who, cohort["object_id"])
    _event(svc, alert, alert["status"], alert["status"], principal.id,
           f"investigated in Cockpit thread {thread['thread_id']}")
    return {**thread, "cohort_id": cohort["object_id"]}


# ---- first launch ---------------------------------------------------------------------

def ensure_seeded(svc: ObjectService, who: dict[str, Any]) -> dict[str, Any]:
    principal = Principal.of(who)
    key = f"monitoring_seed:{principal.tenant}"
    if svc.store.meta(key) == SEED_VERSION:
        return {"seeded": False}
    lenses.ensure_seeded(svc, who)
    replayed = _replay_history(svc, principal.tenant)
    # A live round over the library: real current breaches on the
    # published synthetic books (not demo, not historical).
    report = tick(svc, tenants=[principal.tenant])
    svc.store.set_meta(key, SEED_VERSION)
    return {"seeded": True, "replayed": replayed,
            "refreshed": len(report["refreshed"])}


def _replay_history(svc: ObjectService, tenant: str) -> int:
    """HISTORICAL REPLAY (demo): what each rule would have raised over the
    previous published periods. Closed records, labelled, never live."""
    made = 0
    who = _library(tenant)
    for oid in REPLAY_LENSES:
        lens = svc.store.get(oid, tenant_id=tenant)
        if lens is None:
            continue
        for rule in lens["body"]["breach_rules"]:
            try:
                book = access.book(who, rule["domain"])
            except HTTPException:
                continue
            flt = list((lens["body"].get("filters") or {}).get(
                rule["domain"]) or []) or None
            periods = book.periods[-5:-1]
            series = []
            token = metrics.VIEWER.set(Principal.of(who))
            try:
                for p in periods:
                    v = grid.view(book, p)
                    now = metrics.evaluate(book, rule["metric_id"], period=p,
                                           filters=flt).get("value")
                    prior = metrics.evaluate(book, rule["metric_id"],
                                             period=v.prior_period,
                                             filters=flt).get("value") \
                        if v.prior_period and mc.BY_ID[rule["metric_id"]][
                            "kind"] == "book" else None
                    series.append((p, now, prior))
            except HTTPException:
                continue
            finally:
                metrics.VIEWER.reset(token)
            breached = [(p, x, y) for p, x, y in series
                        if lenses._breached(rule, x, y)]
            if not breached:
                continue
            first, last = breached[0], breached[-1]
            t0 = time.time() - 86400 * 7 * (len(periods) + 1)
            body = _alert_body(
                lens, {**rule, "observed": last[1], "prior": last[2]},
                {"observation_id": f"replay-{oid}-{rule['rule_id']}",
                 "finished_at": t0, "period": f"{rule['domain']}:{first[0]}",
                 "release_id": book.release_id,
                 "fingerprint": book.fingerprint},
                domain_filters=list(flt or []))
            body.update({"demo_historical": True, "state": RESOLVED,
                         "label": f"HISTORICAL REPLAY (demo) — this rule "
                                  f"would have breached in "
                                  f"{', '.join(p for p, _x, _y in breached)}"
                                  f"; not a current breach.",
                         "dedup_key": f"replay:{oid}:{rule['rule_id']}",
                         "replay": [{"period": p, "observed": x,
                                     "breached": lenses._breached(rule, x, y)}
                                    for p, x, y in series]})
            created = _create(svc, lens, body, at=t0)
            step = 86400.0
            _event(svc, created, "", NEW, SENDER,
                   f"replay: breached at {first[0]}", first[1], at=t0)
            if len(breached) > 1:
                _event(svc, created, NEW, ACTIVE, SENDER,
                       f"replay: persisted to {breached[1][0]}",
                       breached[1][1], at=t0 + step)
            _event(svc, created, ACTIVE if len(breached) > 1 else NEW,
                   RESOLVED, SENDER, "replay closed: historical record only",
                   last[1], at=t0 + 2 * step)
            made += 1
    return made


__all__ = ["ACTIONS", "OPEN", "Scheduler", "VIEWS", "act", "after_refresh",
           "cohort_for", "detail", "due", "ensure_scheduler", "ensure_seeded",
           "investigate", "listing", "recipients", "tick"]
