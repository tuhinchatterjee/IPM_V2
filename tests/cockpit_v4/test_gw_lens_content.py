"""P16: the Lens content the seeded library lacked, proven on governed data.

LENS-04 management overlay, LENS-05/08/09 top warning reasons (incl. the
salary-interruption proxy), LENS-06 ECL, LENS-12 recoveries and write-offs,
LENS-16 method comparison / concentration / stage view of the latest
result, LENS-18 alerts by state, metric and owner, and M049/M050 (material
changes, refresh age) -- each recomputed independently here and each
rendered through the real Lens renderer.

EVIDENCE LABEL: INDEPENDENT ORACLE; REAL DATABASE (governed candidate books);
NO MODEL.
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import time

import pytest

from backend.workspace import access, lens_seed, lenses, metrics, monitoring, service
from backend.workspace import metric_catalog as mc
from tests.cockpit_v4.test_gw_metrics import close, rows_of
from tests.cockpit_v4.test_gw_monitoring import (  # noqa: F401 (fixtures)
    WHO,
    P,
    alerts,
    breach,
    client,
    svc,
    who,
)
from tests.cockpit_v4.test_gw_runs import full_run

BOOKS = ("corporate", "retail")


def _render(svc, lens_id):
    lenses.ensure_seeded(svc, WHO)
    return lenses.render(svc, WHO, lens_id)


def _visual(rendered, metric_id, vtype=None, domain=None):
    out = [v for v in rendered["visuals"] if v["metric_id"] == metric_id
           and (vtype is None or v["type"] == vtype)
           and (domain is None or v["domain"] == domain)]
    assert out, (metric_id, vtype, domain)
    return out[0]


# ---- LENS-04: management overlay ---------------------------------------------

@pytest.mark.parametrize("domain", BOOKS)
def test_m065_m066_overlay_match_the_published_ifrs9_overlay(svc, domain):
    book = access.book(WHO, domain)
    rows = rows_of(book)
    overlay = sum(r["ecl_overlay_sar_mn"] or 0 for r in rows)
    ecl = sum(r["ecl_sar_mn"] or 0 for r in rows)
    assert overlay > 0, "the governed books publish an overlay"
    assert close(metrics.evaluate(book, "M065")["value"], overlay)
    assert close(metrics.evaluate(book, "M066")["value"], overlay / ecl)


def test_lens04_renders_the_overlay_and_reconciliation(svc):
    r = _render(svc, "lens-04")
    assert all(v["status"] == "OK" for v in r["visuals"]), \
        [v for v in r["visuals"] if v["status"] != "OK"]
    for d in BOOKS:
        assert _visual(r, "M065", "kpi", d)["value"] > 0
    assert _visual(r, "M065", "breakdown", "corporate")["groups"]
    assert _visual(r, "M066", "breakdown", "retail")["groups"]
    assert _visual(r, "M047", "kpi", "corporate")["value"] is not None


# ---- LENS-05 / 08 / 09: top warning reasons ------------------------------------

RULE_ORACLE = {
    "R-DPD": lambda r: (r["dpd_days"] or 0) > 0,
    "R-SCORE-LOW": lambda r: r["score_band"] in ("D", "E"),
    "R-SCORE-DOWN": lambda r: r["score_migration"] == "Deteriorated",
    "R-UTIL": lambda r: r["utilisation_pct"] is not None
    and r["utilisation_pct"] >= 85,
    "R-MINPAY": lambda r: r["payment_ratio_pct"] is not None
    and r["payment_ratio_pct"] < 35,
    "R-SALARY": lambda r: r["employment_type"] in ("Salaried-Private",
                                                   "Salaried-Government")
    and r["employer_sector_group"] == "Cyclical"
    and r["payment_ratio_pct"] is not None and r["payment_ratio_pct"] < 35,
    "C-WATCH": lambda r: r["watchlist_flag"] == 1,
    "C-DOWNGRADE": lambda r: (r["rating_notches_moved"] or 0) > 0,
    "C-COVENANT": lambda r: (r["covenant_breaches"] or 0) > 0,
    "C-DPD": lambda r: (r["dpd_days"] or 0) > 0,
    "C-SICR": lambda r: r["sicr_flag"] == 1,
    "C-UTIL": lambda r: r["utilisation_pct"] is not None
    and r["utilisation_pct"] >= 90,
}


@pytest.mark.parametrize("domain", BOOKS)
def test_m069_reasons_match_each_rule_recomputed(svc, domain):
    book = access.book(WHO, domain)
    rows = rows_of(book)
    got = metrics.evaluate(book, "M069")
    assert not got["rules_not_evaluated"]
    by_rule = {g["rule_id"]: g for g in got["groups"]}
    assert set(by_rule) == {k for k in RULE_ORACLE
                            if k.startswith("R-" if domain == "retail"
                                            else "C-")}
    fired = 0
    for rule_id, g in by_rule.items():
        hit = [r for r in rows if RULE_ORACLE[rule_id](r)]
        assert g["value"] == len(hit), (rule_id, g["value"], len(hit))
        assert close(g["numerator"], sum(r["ead_sar_mn"] or 0 for r in hit))
        fired += bool(hit)
    assert fired >= 2, "at least two reasons fire on each book"
    warned = sum(1 for r in rows if r["ews_band"] != "none")
    assert got["value"] == warned
    values = [g["value"] for g in got["groups"]]
    assert values == sorted(values, reverse=True)


def test_the_salary_signal_is_the_labelled_governed_proxy(svc):
    book = access.book(WHO, "retail")
    g = next(x for x in metrics.evaluate(book, "M069")["groups"]
             if x["rule_id"] == "R-SALARY")
    assert "proxy" in g["dimension"].lower()
    assert "no salary-credit feed" in g["limitation"]


@pytest.mark.parametrize("lens_id,domains", [
    ("lens-05", BOOKS), ("lens-08", ("retail",)), ("lens-09", ("retail",))])
def test_reason_visuals_render_and_honour_the_lens_filter(svc, lens_id,
                                                          domains):
    r = _render(svc, lens_id)
    for d in domains:
        v = _visual(r, "M069", "groups", d)
        assert v["status"] == "OK" and v["groups"]
        assert any(g["value"] for g in v["groups"])
    if lens_id != "lens-05":
        # Product Lenses narrow the reasons to their own product.
        spec = lens_seed.by_id()[lens_id.upper()]
        book = access.book(WHO, "retail")
        whole = {g["rule_id"]: g["value"] for g in
                 metrics.evaluate(book, "M069")["groups"]}
        mine = {g["rule_id"]: g["value"] for g in
                _visual(r, "M069", "groups", "retail")["groups"]}
        assert spec["filters"]["retail"]
        assert all(mine[k] <= whole[k] for k in mine)
        assert mine != whole


# ---- LENS-06: ECL bound --------------------------------------------------------

def test_lens06_shows_booked_ecl_and_its_sector_breakdown(svc):
    r = _render(svc, "lens-06")
    book = access.book(WHO, "corporate")
    ecl = sum(x["ecl_sar_mn"] or 0 for x in rows_of(book))
    assert close(_visual(r, "M001", "kpi")["value"], ecl)
    by = _visual(r, "M001", "breakdown")["groups"]
    assert close(sum(g["value"] for g in by), ecl)
    assert _visual(r, "M023", "kpi")["value"] is not None


# ---- LENS-12: recoveries and write-offs ------------------------------------------

@pytest.mark.parametrize("domain", BOOKS)
def test_recoveries_and_write_offs_match_the_published_rows(svc, domain):
    book = access.book(WHO, domain)
    seen = 0.0
    for period in book.periods:
        rows = rows_of(book, period)
        rec = sum(r["recovery_sar_mn"] or 0 for r in rows)
        wo = sum(r["write_off_sar_mn"] or 0 for r in rows)
        assert close(metrics.evaluate(book, "M067", period=period)["value"],
                     rec), (domain, period)
        assert close(metrics.evaluate(book, "M068", period=period)["value"],
                     wo), (domain, period)
        seen += rec
    assert seen > 0, "recoveries occur somewhere in each book's history"


def test_lens12_renders_recoveries_vs_write_offs(svc):
    r = _render(svc, "lens-12")
    trend = next(v for v in r["visuals"] if v["type"] == "trend"
                 and {s["metric_id"] for s in v["series"]} == {"M067",
                                                              "M068"})
    assert all(len(s["points"]) == 12 for s in trend["series"])
    assert any(p["value"] for s in trend["series"] for p in s["points"])
    assert _visual(r, "M067", "kpi")["status"] == "OK"
    assert _visual(r, "M067", "breakdown")["groups"]


# ---- LENS-16: the latest result by method / segment / stage ----------------------

def test_lens16_method_concentration_and_stage_views_read_the_result(svc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.workspace import api as workspace_api
    from backend.workspace import scenarios

    app = FastAPI()
    app.include_router(workspace_api.router)
    from backend.cockpit_v4 import routes
    routes._STATE["principal"] = lambda r: WHO
    http = TestClient(app)
    scenarios.ensure_seeded(svc, WHO)
    # First render seeds the Lens library's demo results; the result run
    # below is then the latest one the Lens must read.
    _render(svc, "lens-16")
    lib = http.get(f"{P}/scenarios", params={"domain": "corporate"}).json()
    sid = next(s["object_id"] for s in lib["scenarios"]
               if s["name"] == "Construction PD+LGD downside")
    _run, result = full_run(http, sid, methods=("delta",))
    assert result is not None
    stored = svc.store.get(result["object_id"], tenant_id="demo-tenant")
    token = metrics.VIEWER.set(service.principal(WHO))
    try:
        r = _render(svc, "lens-16")
    finally:
        metrics.VIEWER.reset(token)
    body = stored["body"]
    methods = _visual(r, "M073", "groups", "corporate")
    assert methods["latest_result"] == result["object_id"]
    assert [g["dimension"] for g in methods["groups"]] == [
        body["results"]["delta"]["label"]]
    assert close(methods["groups"][0]["value"],
                 float(body["results"]["delta"]["change"]))
    pareto = _visual(r, "M074", "groups", "corporate")
    assert [g["dimension"] for g in pareto["groups"]] == [
        x["group"] for x in body["pareto"]]
    assert close(sum(g["value"] for g in pareto["groups"]),
                 float(body["decomposition"]["delta"]["scopes"]["selected"][
                     "change"]))
    stages = _visual(r, "M075", "groups", "corporate")
    assert [g["dimension"] for g in stages["groups"]] == [
        f"Stage {x['stage']}" for x in body["stages"]]
    assert stages["stage_policy"] == body["stage_policy"]
    assert mc.BY_ID["M075"]["scenario_interpretation"].endswith(
        "not stage migration.")


# ---- LENS-18: alerts by state, metric and owner ------------------------------------

def test_lens18_alert_groups_match_the_alert_store(client, svc, who):
    client.get(f"{P}/monitoring")
    a = breach(svc, "lens-02", "R02-1")
    client.post(f"{P}/monitoring/alerts/{a['object_id']}/assign", json={})
    token = metrics.VIEWER.set(service.principal(WHO))
    try:
        book = access.book(WHO, "corporate")
        by_state = metrics.evaluate(book, "M070")
        by_metric = metrics.evaluate(book, "M071")
        by_owner = metrics.evaluate(book, "M072")
        r = _render(svc, "lens-18")
    finally:
        metrics.VIEWER.reset(token)
    mine = [x for x in alerts(svc) if x["body"]["alert_type"] == "breach"
            and x["domain_id"] in ("corporate", "both")]
    live = [x for x in mine if x["status"] in ("NEW", "ACTIVE", "WORSENING")]
    states = {g["dimension"]: g["value"] for g in by_state["groups"]}
    assert set(states) >= {"NEW", "ACTIVE", "WORSENING", "ACKNOWLEDGED",
                           "RESOLVED"}
    assert sum(states.values()) == len(mine) == by_state["value"]
    want = {}
    for x in live:
        want[x["body"]["metric_id"]] = want.get(x["body"]["metric_id"], 0) + 1
    assert {g["dimension"]: g["value"] for g in by_metric["groups"]} == want
    owners = {g["dimension"]: g["value"] for g in by_owner["groups"]}
    assert owners.get(WHO["id"]) == 1
    assert sum(owners.values()) == len(live)
    for mid in ("M070", "M071", "M072"):
        assert _visual(r, mid, "groups")["groups"]


# ---- M049 / M050 ----------------------------------------------------------------------

def test_m050_is_hours_since_each_lens_last_successful_refresh(svc):
    monitoring.ensure_seeded(svc, WHO)
    book = access.book(WHO, "corporate")
    before = metrics.evaluate(book, "M050")
    now = time.time()
    want = {}
    for lens in svc.store.latest_of_kind("lens", tenant_id="demo-tenant"):
        if "corporate" not in lens["body"]["domain_scope"]:
            continue
        ok = next((o for o in svc.store.observations(
            lens["object_id"], tenant_id="demo-tenant")
            if o["status"] == "SUCCEEDED"), None)
        want[lens["object_id"]] = None if ok is None else \
            (now - ok["finished_at"]) / 3600
    got = {g["lens_id"]: g["value"] for g in before["groups"]}
    assert set(got) == set(want)
    for k, v in want.items():
        assert (got[k] is None) == (v is None)
        if v is not None:
            assert abs(got[k] - v) < 0.01
    aged = [v for v in want.values() if v is not None]
    assert aged and abs(before["value"] - max(aged)) < 0.01
    # A refresh resets that Lens' age to ~0; the oldest stays the headline.
    lenses.refresh(svc, WHO, "lens-02")
    after = {g["lens_id"]: g["value"] for g in
             metrics.evaluate(book, "M050")["groups"]}
    assert after["lens-02"] < 0.01


def test_m049_counts_the_material_changes_of_each_lens_latest_refresh(svc):
    monitoring.ensure_seeded(svc, WHO)
    book = access.book(WHO, "corporate")
    # Make one material move: a prior observation whose Booked ECL was 20%
    # lower, then refresh (the same technique as the Lens suite).
    first = lenses.refresh(svc, WHO, "lens-02")
    body = dict(first["body"])
    values = {d: {m: dict(v) for m, v in per.items()}
              for d, per in body["values"].items()}
    values["corporate"]["M001"]["value"] *= 0.8
    svc.store.add_observation({**{k: first[k] for k in (
        "tenant_id", "lens_id", "lens_version", "release_id", "fingerprint",
        "period")}, "trigger": "test", "status": "SUCCEEDED",
        # Just after the first, so the refresh below is the latest one.
        "started_at": first["started_at"] + 0.0005,
        "finished_at": first["finished_at"] + 0.0005,
        "body": {**body, "values": values}})
    lenses.refresh(svc, WHO, "lens-02")
    want = 0
    for lens in svc.store.latest_of_kind("lens", tenant_id="demo-tenant"):
        obs = svc.store.observations(lens["object_id"],
                                     tenant_id="demo-tenant", limit=1)
        if obs and obs[0]["status"] == "SUCCEEDED":
            want += len(obs[0]["body"].get("material_changes") or [])
    assert metrics.evaluate(book, "M049")["value"] == want
    assert want > 0, "the material move is counted"


def test_every_seeded_lens_still_renders_every_visual(svc):
    lenses.ensure_seeded(svc, WHO)
    monitoring.ensure_seeded(svc, WHO)
    for spec in lens_seed.LENSES:
        r = lenses.render(svc, WHO, spec["lens_id"].lower())
        bad = [v["visual_id"] for v in r["visuals"] if v["status"] != "OK"]
        assert not bad, (spec["lens_id"], bad)
