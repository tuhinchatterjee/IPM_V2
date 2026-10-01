"""P10 — Monitoring Centre: scheduled refresh, breach alerts, Inbox delivery.

EVIDENCE LABEL: no model call. Lens refreshes evaluate the candidate books
through the metric engine; alerts, deliveries and state transitions are the
workspace store's own records.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import cohort_refs
from backend.workspace import access, cohorts, lenses, metrics, monitoring, service
from backend.workspace import api as workspace_api
from backend.workspace.store import WorkspaceStore

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = ("v4-whatif-corporate-20q-s1", "v4-whatif-retail-20m-s1")
WHO = {"id": "banker", "tenant": "demo-tenant", "roles": ("analyst",)}
ADMIN = {"id": "boss", "tenant": "demo-tenant", "roles": ("administrator",)}


@pytest.fixture
def svc(tmp_path, monkeypatch):
    for release in CANDIDATE:
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    monkeypatch.delenv("COCKPIT_V4_MONITORING_SCHEDULER", raising=False)
    access.reset_books()
    metrics.clear_cache()
    cohort_refs.register(cohorts.engine_resolver)
    service.use_store(WorkspaceStore(tmp_path / "ws.sqlite3"))
    yield service.objects()
    service.use_store(None)
    access.reset_books()


@pytest.fixture
def who():
    return dict(WHO)


@pytest.fixture
def client(store_db, runtime, svc, who):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: who, startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app)


def alerts(svc, lens_id="", live_only=True):
    out = [a for a in svc.store.latest_of_kind("alert",
                                               tenant_id="demo-tenant")
           if (not lens_id or a["body"]["lens_id"] == lens_id)]
    return [a for a in out if not live_only
            or not a["body"].get("demo_historical")]


def breach(svc, lens_id, rule_id):
    return next(a for a in alerts(svc, lens_id)
                if a["body"]["rule_id"] == rule_id)


# ---- thresholds ---------------------------------------------------------------------

@pytest.mark.parametrize("op,th,now,prior,want", [
    ("gt", 0.05, 0.06, None, True), ("gt", 0.05, 0.05, None, False),
    ("lt", 0.30, 0.29, None, True), ("lt", 0.30, 0.31, None, False),
    ("abs_gt", 0.10, -0.11, None, True), ("abs_gt", 0.10, 0.09, None, False),
    ("move_pct_gt", 0.10, 111, 100, True), ("move_pct_gt", 0.10, 110, 100,
                                             False),
    ("move_pct_gt", 0.10, 111, None, False),
    ("move_abs_gt", 0.0015, 0.0120, 0.0100, True),
    ("move_abs_gt", 0.0015, 0.0110, 0.0100, False),
    ("gt", 0.05, None, None, False)])
def test_threshold_comparisons_are_exact(op, th, now, prior, want):
    assert lenses._breached({"comparison": op, "threshold": th}, now,
                            prior) is want


# ---- first launch ------------------------------------------------------------------

def test_first_launch_shows_live_breaches_and_labelled_historical_replay(
        client, svc):
    out = client.get(f"{P}/monitoring", params={"view": "all"}).json()
    assert out["counts"]["new"] >= 1 and out["counts"]["history"] >= 1
    hist = [a for a in out["alerts"] if a["demo_historical"]]
    for a in hist:
        assert a["state"] == "RESOLVED"
        assert a["label"].startswith("HISTORICAL REPLAY (demo)")
    live = client.get(f"{P}/monitoring", params={"view": "active"}).json()
    assert live["alerts"] and not any(a["demo_historical"]
                                      for a in live["alerts"])
    for a in live["alerts"]:
        assert a["metric_id"] and a["metric_version"] and a["rule_id"]
        assert a["lens_id"] and a["release_id"] and a["period"]
    again = client.get(f"{P}/monitoring", params={"view": "all"}).json()
    assert again["total"] == out["total"], "seeded once"


# ---- dedup, cooldown, worsening, resolution --------------------------------------

def _obs(first, *, observed, breached, rule_id):
    body = dict(first["body"])
    body["breaches"] = [{**b, "observed": observed, "breached": breached}
                        if b["rule_id"] == rule_id else b
                        for b in body["breaches"]]
    body["material_changes"] = []
    return {**first, "observation_id": f"obs-test-{time.time_ns()}",
            "finished_at": time.time(), "body": body}


def test_a_persisting_breach_is_one_alert_new_then_active(svc):
    monitoring.ensure_seeded(svc, WHO)
    a = breach(svc, "lens-01", "R01-1")
    assert a["status"] == "NEW"
    obs = lenses.refresh(svc, WHO, "lens-01")
    monitoring.after_refresh(svc, WHO, "lens-01", obs)
    same = [x for x in alerts(svc, "lens-01")
            if x["body"]["rule_id"] == "R01-1"]
    assert len(same) == 1 and same[0]["status"] == "ACTIVE"
    events = svc.store.alert_events(a["object_id"], tenant_id="demo-tenant")
    assert [e["to_state"] for e in events] == ["NEW", "ACTIVE"]


def test_worsening_is_delivered_through_cooldown_and_recovery_resolves(svc):
    monitoring.ensure_seeded(svc, WHO)
    svc.store.subscribe(tenant_id="demo-tenant", object_id="lens-01",
                        user_id="banker")
    first = lenses.refresh(svc, WHO, "lens-01")
    a = breach(svc, "lens-01", "R01-1")
    # Delivered once already: the cooldown is running.
    lens = svc.store.get("lens-01", tenant_id="demo-tenant")
    assert monitoring._deliver(svc, lens, a, "first") == 1
    a = svc.get(a["object_id"], service.principal(WHO))
    worse = _obs(first, observed=a["body"]["observed"] + 0.05, breached=True,
                 rule_id="R01-1")
    out = monitoring.after_refresh(svc, WHO, "lens-01", worse)
    assert out["worsened"] == [a["object_id"]] and out["delivered"] == 1
    assert svc.get(a["object_id"], service.principal(WHO))["status"] == \
        "WORSENING"
    # Same value again inside the cooldown: nothing new delivered.
    again = _obs(first, observed=a["body"]["observed"] + 0.05, breached=True,
                 rule_id="R01-1")
    assert monitoring.after_refresh(svc, WHO, "lens-01",
                                    again)["delivered"] == 0
    healed = _obs(first, observed=0.01, breached=False, rule_id="R01-1")
    out = monitoring.after_refresh(svc, WHO, "lens-01", healed)
    assert out["resolved"] == [a["object_id"]]


def test_cooldown_suppresses_a_duplicate_delivery(svc):
    monitoring.ensure_seeded(svc, WHO)
    a = breach(svc, "lens-02", "R02-1")
    lens = svc.store.get("lens-02", tenant_id="demo-tenant")
    svc.store.subscribe(tenant_id="demo-tenant", object_id="lens-02",
                        user_id="banker")
    assert monitoring._deliver(svc, lens, a, "first") == 1
    fresh = svc.get(a["object_id"], service.principal(WHO))
    assert monitoring._deliver(svc, lens, fresh, "again") == 0
    assert monitoring._deliver(svc, lens, fresh, "worse", force=True) == 1


# ---- the alert state machine -------------------------------------------------------

def test_the_alert_state_machine(client, svc, who):
    client.get(f"{P}/monitoring")
    a = breach(svc, "lens-02", "R02-1")
    url = f"{P}/monitoring/alerts/{a['object_id']}"
    assert client.post(f"{url}/acknowledge", json={}).status_code == 422
    ack = client.post(f"{url}/acknowledge", json={"note": "known, in review"})
    assert ack.json()["status"] == "ACKNOWLEDGED"
    assert client.post(f"{url}/acknowledge",
                       json={"note": "twice"}).status_code == 409
    assert client.post(f"{url}/suppress",
                       json={"note": "noise"}).status_code == 403
    client.post(f"{url}/assign", json={})
    mine = client.get(f"{P}/monitoring", params={"view": "mine"}).json()
    assert [x["alert_id"] for x in mine["alerts"]] == [a["object_id"]]
    client.post(f"{url}/comment", json={"note": "asked RM for details"})
    res = client.post(f"{url}/resolve", json={"note": "remediated"}).json()
    assert res["status"] == "RESOLVED"
    who.clear()
    who.update(ADMIN)
    assert client.post(f"{url}/reopen", json={}).json()["status"] == "ACTIVE"
    assert client.post(f"{url}/suppress",
                       json={"note": "governance waiver"}).json()[
        "status"] == "SUPPRESSED"
    d = client.get(url).json()
    states = [e["to_state"] for e in d["events"]]
    assert states[0] == "NEW" and "ACKNOWLEDGED" in states and \
        states[-1] == "SUPPRESSED"
    assert any(e["note"] == "asked RM for details" for e in d["events"])
    hist = next(x for x in alerts(svc, live_only=False)
                if x["body"].get("demo_historical"))
    r = client.post(f"{P}/monitoring/alerts/{hist['object_id']}/acknowledge",
                    json={"note": "x"})
    assert r.status_code == 409


def test_alert_actions_do_not_touch_source_data(client, svc):
    client.get(f"{P}/monitoring")
    book = access.book(WHO, "corporate")
    before = metrics.evaluate(book, "M001")["value"]
    a = breach(svc, "lens-02", "R02-1")
    client.post(f"{P}/monitoring/alerts/{a['object_id']}/acknowledge",
                json={"note": "seen"})
    metrics.clear_cache()
    assert metrics.evaluate(book, "M001")["value"] == before


# ---- inbox delivery and handoffs -----------------------------------------------------

def test_a_breach_reaches_a_followers_inbox_with_its_actions(client, svc,
                                                             store_db):
    client.get(f"{P}/monitoring")
    client.post(f"{P}/lenses/lens-03/follow", json={"on": True})
    for a in alerts(svc, "lens-03"):          # start clean for lens-03
        monitoring.act(svc, ADMIN, a["object_id"], "resolve", note="reset")
    out = client.post(f"{P}/lenses/lens-03/refresh").json()
    assert out["alerts"]["created"], out["alerts"]
    items = [i for i in client.get(f"{P}/messages").json()["items"]
             if i["kind"] == "alert"]
    assert items and items[0]["from_id"] == monitoring.SENDER
    d = client.get(f"{P}/messages/{items[0]['share_id']}").json()
    acts = {x["action"]: x for x in d["actions"]}
    assert acts["open"]["href"].startswith("/lenses/lens-03?alert=")
    assert {"investigate", "whatif", "open_monitoring", "comment"} <= \
        set(acts)
    thread = client.post(f"{P}/messages/{items[0]['share_id']}/investigate"
                         ).json()
    assert store_db.thread_context(thread["thread_id"],
                                   tenant_id="demo-tenant")
    coh = client.post(f"{P}/messages/{items[0]['share_id']}/whatif").json()
    assert coh["kind"] == "cohort"


def test_opening_an_alert_restores_the_lens_at_its_trigger(client, svc):
    client.get(f"{P}/monitoring")
    a = breach(svc, "lens-15", "R15-1")
    d = client.get(f"{P}/monitoring/alerts/{a['object_id']}").json()
    target = d["open_lens"]
    assert target["lens_id"] == "lens-15"
    assert target["periods"]["corporate"] == a["body"]["period"]
    assert target["filters"][0]["values"] == ["Construction", "Real Estate"]
    r = client.post(f"{P}/lenses/lens-15/render", json={
        "periods": target["periods"], "cross_filters": target["filters"]})
    assert r.json()["books"]["corporate"]["period"] == a["body"]["period"]


# ---- failure honesty, scheduling, replay -----------------------------------------------

def test_a_failed_refresh_is_recorded_and_never_shown_as_current(client, svc,
                                                                  monkeypatch):
    client.get(f"{P}/monitoring")
    client.post(f"{P}/lenses/lens-06/follow", json={"on": True})
    real = access.book

    def broken(who, domain):
        raise HTTPException(503, {"error_code": "BOOK_UNAVAILABLE",
                                  "message": "release not reachable"})

    monkeypatch.setattr(access, "book", broken)
    out = client.post(f"{P}/lenses/lens-06/refresh").json()
    assert out["status"] == "FAILED"
    assert "FAILED" in out["body"]["what_changed"]
    assert out["body"]["values"] == {}
    failure = next(a for a in alerts(svc, "lens-06")
                   if a["body"]["alert_type"] == "refresh_failure")
    assert failure["status"] == "NEW"
    monkeypatch.setattr(access, "book", real)
    health = client.get(f"{P}/monitoring").json()["lens_health"]
    lens6 = next(h for h in health if h["lens_id"] == "lens-06")
    assert lens6["stale"] is True and lens6["last_status"] == "FAILED"
    inbox = [i for i in client.get(f"{P}/messages").json()["items"]
             if i["object_id"] == failure["object_id"]]
    assert inbox and "FAILED" in inbox[0]["message"]
    ok = client.post(f"{P}/lenses/lens-06/refresh").json()
    assert ok["status"] == "SUCCEEDED"
    assert svc.get(failure["object_id"], service.principal(WHO))[
        "status"] == "RESOLVED"


def test_scheduled_refresh_replays_deterministically(svc):
    monitoring.ensure_seeded(svc, WHO)
    n_alerts = len(alerts(svc, live_only=False))
    n_obs = sum(len(svc.store.observations(lens["object_id"],
                                           tenant_id="demo-tenant"))
                for lens in svc.store.latest_of_kind(
                    "lens", tenant_id="demo-tenant"))
    t = time.time() + 2 * 86400          # every daily Lens is due
    first = monitoring.tick(svc, now=t, tenants=["demo-tenant"])
    assert first["refreshed"]
    assert all(r["idempotent"] for r in first["refreshed"]), \
        "same releases: nothing is observed twice"
    second = monitoring.tick(svc, now=t, tenants=["demo-tenant"])
    assert [r["lens"] for r in second["refreshed"]] == \
        [r["lens"] for r in first["refreshed"]]
    assert len(alerts(svc, live_only=False)) == n_alerts
    assert sum(len(svc.store.observations(lens["object_id"],
                                          tenant_id="demo-tenant"))
               for lens in svc.store.latest_of_kind(
                   "lens", tenant_id="demo-tenant")) == n_obs


def test_cadences_decide_what_is_due(svc):
    monitoring.ensure_seeded(svc, WHO)
    now = time.time()
    daily = svc.store.get("lens-02", tenant_id="demo-tenant")
    assert monitoring.due(svc, daily, now)[0] is False
    assert monitoring.due(svc, daily, now + 86401)[0] is True
    pub = svc.store.get("lens-04", tenant_id="demo-tenant")
    go, why = monitoring.due(svc, pub, now + 10 * 86400)
    assert go is False and "no new release" in why
    manual = dict(daily)
    manual["body"] = {**daily["body"], "refresh": {**daily["body"]["refresh"],
                                                   "cadence": "manual"}}
    assert monitoring.due(svc, manual, now + 10 * 86400)[0] is False


def test_m048_counts_live_breaches_the_viewer_can_open(svc):
    monitoring.ensure_seeded(svc, WHO)
    book = access.book(WHO, "corporate")
    token = metrics.VIEWER.set(service.principal(WHO))
    try:
        v = metrics.evaluate(book, "M048")
    finally:
        metrics.VIEWER.reset(token)
    live = [a for a in alerts(svc) if a["status"] in ("NEW", "ACTIVE",
                                                       "WORSENING")
            and a["body"]["alert_type"] == "breach"
            and a["domain_id"] == "corporate"]
    assert v["value"] == len(live) and v["groups"]


def test_monitoring_filters(client, svc):
    client.get(f"{P}/monitoring")
    high = client.get(f"{P}/monitoring", params={"view": "all",
                                                 "severity": "high"}).json()
    assert high["alerts"] and all(a["severity"] == "high"
                                  for a in high["alerts"])
    one = client.get(f"{P}/monitoring", params={"view": "all",
                                                "lens": "lens-02"}).json()
    assert {a["lens_id"] for a in one["alerts"]} == {"lens-02"}
    retail = client.get(f"{P}/monitoring", params={"view": "all",
                                                   "domain": "retail"}).json()
    assert all(a["domain_id"] in ("retail", "") for a in retail["alerts"])
    none = client.get(f"{P}/monitoring", params={"view": "all",
                                                 "lens": "nope"}).json()
    assert none["state"] == "EMPTY_BY_FILTER"


def test_the_scheduler_thread_runs_ticks_when_enabled(svc, monkeypatch):
    monitoring.ensure_seeded(svc, WHO)
    assert monitoring.ensure_scheduler() is None, "off unless enabled"
    monkeypatch.setenv("COCKPIT_V4_MONITORING_SCHEDULER", "1")
    monkeypatch.setenv("COCKPIT_V4_MONITORING_POLL_SECONDS", "0.2")
    monkeypatch.setattr(monitoring, "_SCHEDULER", None)
    sched = monitoring.ensure_scheduler()
    try:
        deadline = time.time() + 30
        while not sched.last and time.time() < deadline:
            time.sleep(0.1)
        assert sched.last.get("at"), sched.last
        assert "error" not in sched.last, sched.last
        assert monitoring.ensure_scheduler() is sched, "started once"
    finally:
        sched.stop()
