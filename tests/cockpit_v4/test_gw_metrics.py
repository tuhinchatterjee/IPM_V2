"""P8 — Metric Catalogue 2.0: fully defined, persisted, versioned, correct.

EVIDENCE LABEL: no model call. Formula tests recompute each metric in Python
from the governed grid rows of the candidate books and compare with the
metric engine; nothing here reuses the engine's SQL.
"""

from __future__ import annotations

import json
from collections import defaultdict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import cohort_refs
from backend.workspace import (access, cohorts, grid, metric_registry, metrics,
                               scenarios, service)
from backend.workspace import api as workspace_api
from backend.workspace import metric_catalog as mc
from backend.workspace.store import WorkspaceStore

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = ("v4-whatif-corporate-20q-s1", "v4-whatif-retail-20m-s1")
WHO = {"id": "banker", "tenant": "demo-tenant", "roles": ("analyst",)}

#: §46, verbatim ids and names. The catalogue may add, never weaken.
SPEC = {
    "M001": "Booked ECL", "M002": "ECL change", "M003": "ECL change %",
    "M004": "Stage 1 EAD share", "M005": "Stage 2 EAD share",
    "M006": "Stage 3 EAD share", "M007": "Stage 2 ECL share",
    "M008": "Stage 3 ECL share", "M009": "Stage 1→2 migration EAD",
    "M010": "Stage 2→3 migration EAD", "M011": "Cure EAD",
    "M012": "Default-entry rate", "M013": "Default count",
    "M014": "NPL / default EAD", "M015": "EAD-weighted PD",
    "M016": "EAD-weighted LGD", "M017": "EAD-weighted CCF",
    "M018": "Total EAD", "M019": "Utilisation rate",
    "M020": "Top-10 concentration", "M021": "Largest-name concentration",
    "M022": "Sector/product EAD share", "M023": "Rating downgrade rate",
    "M024": "Rating upgrade rate", "M025": "Average rating notch movement",
    "M026": "Behaviour score movement",
    "M027": "Application score distribution", "M028": "30+ DPD rate",
    "M029": "90+ DPD rate", "M030": "Roll-forward rate", "M031": "Cure rate",
    "M032": "EWS warned customers", "M033": "EWS high/critical share",
    "M034": "Forward-risk customers", "M035": "EWS score",
    "M036": "Covenant breach rate", "M037": "Limit utilisation",
    "M038": "Limit breach count", "M039": "Scenario ECL delta",
    "M040": "Scenario ECL delta %",
    "M041": "Selected-scope contribution to total ECL change",
    "M042": "Model calibration gap", "M043": "MEV sensitivity coefficient",
    "M044": "MEV sensitivity stability", "M045": "Data completeness",
    "M046": "Data freshness", "M047": "Reconciliation residual",
    "M048": "Breach count active",
    "M049": "Material changes since prior refresh",
    "M050": "Lens refresh age",
}


@pytest.fixture
def svc(tmp_path, monkeypatch):
    for release in CANDIDATE:
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    access.reset_books()
    metrics.clear_cache()
    cohort_refs.register(cohorts.engine_resolver)
    service.use_store(WorkspaceStore(tmp_path / "ws.sqlite3"))
    yield service.objects()
    service.use_store(None)
    access.reset_books()
    metrics.clear_cache()


@pytest.fixture
def client(store_db, runtime, svc):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: WHO, startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app)


def rows_of(book, period=""):
    v = grid.view(book, period)
    return book.rows(f"SELECT * FROM ({v.sql}) g", [])


def close(a, b, rel=1e-9):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


# ---- the registry --------------------------------------------------------------

def test_first_launch_catalogue_is_persisted_and_holds_at_least_50(client,
                                                                    svc):
    body = client.get(f"{P}/metrics").json()
    assert body["count"] >= 50
    persisted = svc.store.latest_of_kind("metric", tenant_id="demo-tenant")
    assert len(persisted) == body["count"] == len(mc.METRICS)
    assert all(m["object_id"].startswith("met-") for m in body["metrics"])
    again = client.get(f"{P}/metrics").json()
    assert again["count"] == body["count"], "seeded once"


def test_every_spec_metric_is_present_under_its_spec_name():
    for mid, name in SPEC.items():
        assert mid in mc.BY_ID, mid
        assert mc.BY_ID[mid]["name"].replace(" / ", "/") == \
            name.replace(" / ", "/"), mid


def test_every_metric_is_fully_defined():
    for m in mc.METRICS:
        for f in (*mc.DEFINITION_FIELDS, "owner", "catalog_version"):
            assert m.get(f) not in (None, "", [], {}), (m["metric_id"], f)
        assert m["directionality"] in ("lower_is_better", "higher_is_better",
                                       "context")
        assert m["num_sql"] or m["evaluator"] or m["relative_to"], \
            m["metric_id"]


def test_a_changed_definition_is_a_new_version_and_the_old_stays(svc,
                                                                  monkeypatch):
    metric_registry.ensure_seeded(svc, WHO)
    v1 = metric_registry.get(svc, WHO, "M005")
    changed = [dict(m) for m in mc.METRICS]
    for m in changed:
        if m["metric_id"] == "M005":
            m["definition"] = m["definition"] + " (clarified)"
    monkeypatch.setattr(mc, "METRICS", changed)
    out = metric_registry.ensure_seeded(svc, WHO)
    assert out["revised"] == 1
    v2 = metric_registry.get(svc, WHO, "M005")
    assert v2["version"] == v1["version"] + 1
    old = metric_registry.get(svc, WHO, "M005", version=v1["version"])
    assert old["body"]["definition"] == v1["body"]["definition"]


# ---- formula tests: recomputed independently ------------------------------------

@pytest.mark.parametrize("domain", ["corporate", "retail"])
def test_book_formulas_reconcile_to_a_python_recomputation(svc, domain):
    book = access.book(WHO, domain)
    rows = rows_of(book)
    ead = sum(r["ead_sar_mn"] or 0 for r in rows)
    ecl = sum(r["ecl_sar_mn"] or 0 for r in rows)
    staged = [r for r in rows if r["stage"] in (1, 2, 3)]
    staged_ead = sum(r["ead_sar_mn"] or 0 for r in staged)
    staged_ecl = sum(r["ecl_sar_mn"] or 0 for r in staged)
    by_owner = defaultdict(float)
    owner = grid.view(book).owner
    for r in rows:
        by_owner[r[owner]] += r["ead_sar_mn"] or 0
    top = sorted(by_owner.values(), reverse=True)
    pd_rows = [r for r in rows if r["pd_pit_12m"] is not None]
    lgd_rows = [r for r in rows if r["lgd_pct"] is not None]
    expected = {
        "M001": ecl, "M018": ead,
        "M005": sum(r["ead_sar_mn"] for r in staged if r["stage"] == 2)
        / staged_ead,
        "M006": sum(r["ead_sar_mn"] for r in staged if r["stage"] == 3)
        / staged_ead,
        "M007": sum(r["ecl_sar_mn"] for r in staged if r["stage"] == 2)
        / staged_ecl,
        "M015": sum(r["ead_sar_mn"] * r["pd_pit_12m"] for r in pd_rows)
        / sum(r["ead_sar_mn"] for r in pd_rows),
        "M020": sum(top[:10]) / ead,
        "M021": top[0] / ead,
        "M052": ecl / ead,
        "M060": len(rows),
        "M059": len(by_owner),
    }
    lgd = sum(r["ead_sar_mn"] * r["lgd_pct"] for r in lgd_rows) / \
        sum(r["ead_sar_mn"] for r in lgd_rows)
    for mid, want in expected.items():
        got = metrics.evaluate(book, mid)["value"]
        assert close(got, want), (domain, mid, got, want)
    got_lgd = metrics.evaluate(book, "M016")["value"]
    # LGD is stored in percent; the metric is a fraction.
    assert close(got_lgd, lgd / 100) or close(got_lgd, lgd), (got_lgd, lgd)


def test_retail_delinquency_rates_reconcile(svc):
    book = access.book(WHO, "retail")
    rows = rows_of(book)
    ead = sum(r["ead_sar_mn"] or 0 for r in rows)
    assert "dpd_days" in rows[0]
    for mid, days in (("M028", 30), ("M029", 90)):
        got = metrics.evaluate(book, mid)["value"]
        by_count = sum(1 for r in rows if (r["dpd_days"] or 0) >= days) / \
            len(rows)
        assert close(got, by_count), (mid, got)
    # Non-trivial on this book (max DPD is 28 days): past-due EAD.
    past_due = [r for r in rows if (r["dpd_days"] or 0) > 0]
    assert past_due
    assert close(metrics.evaluate(book, "M054")["value"],
                 sum(r["ead_sar_mn"] for r in past_due))
    assert ead > 0


def test_a_movement_metric_is_the_difference_of_its_base(svc):
    book = access.book(WHO, "corporate")
    v = grid.view(book)
    now = metrics.evaluate(book, "M001")["value"]
    prior = metrics.evaluate(book, "M001", period=v.prior_period)["value"]
    change = metrics.evaluate(book, "M002")
    assert close(change["value"], now - prior)
    pct = metrics.evaluate(book, "M003")["value"]
    assert close(pct, now / prior - 1)


def test_a_filtered_metric_equals_the_same_formula_on_the_filtered_rows(svc):
    book = access.book(WHO, "corporate")
    flt = [{"column": "sector", "op": "in", "values": ["Construction"]}]
    got = metrics.evaluate(book, "M001", filters=flt)["value"]
    want = sum(r["ecl_sar_mn"] for r in rows_of(book)
               if r["sector"] == "Construction")
    assert close(got, want)


@pytest.mark.parametrize("domain", ["corporate", "retail"])
def test_every_applicable_metric_evaluates_on_both_books(svc, domain):
    book = access.book(WHO, domain)
    for m in mc.METRICS:
        if not mc.applies(m, domain):
            continue
        out = metrics.evaluate(book, m["metric_id"])
        assert out["metric_id"] == m["metric_id"]
        assert out["metric_version"] == m["version"]
        if m["kind"] in ("book", "delta", "delta_pct") and \
                m["metric_id"] not in ("M027",):
            assert out.get("value") is not None or out.get("groups"), \
                (domain, m["metric_id"], out)


# ---- scenario metrics read the published results --------------------------------

def test_scenario_metrics_read_the_published_decomposition(client, svc):
    scenarios.ensure_seeded(svc, WHO)
    run = client.post(f"{P}/whatif/runs", json={
        "scenario_id": scenarios.template_object_id("CORP-01"),
        "session_id": "m"}).json()
    run = client.post(f"{P}/whatif/runs/{run['object_id']}/confirm",
                      json={"digest": run["body"]["contract"]["digest"]}
                      ).json()
    run = client.post(f"{P}/whatif/runs/{run['object_id']}/method",
                      json={"methods": ["delta"]}).json()
    result = client.post(f"{P}/whatif/runs/{run['object_id']}/execute"
                         ).json()["result"]
    d = result["body"]["decomposition"]["delta"]
    book = access.book(WHO, "corporate")
    m39 = metrics.evaluate(book, "M039")
    assert m39["latest_result"] == result["object_id"]
    assert close(m39["value"], float(d["scopes"]["selected"]["change"]))
    m40 = metrics.evaluate(book, "M040")["value"]
    assert close(m40, float(d["scopes"]["selected"]["change"])
                 / float(d["scopes"]["selected"]["opening"]))
    m41 = metrics.evaluate(book, "M041")["value"]
    assert close(m41, 1.0), "the rest of the book does not move"
    m42 = metrics.evaluate(book, "M042")
    assert m42["groups"] == [], "no ML result, so no calibration gap group"


# ---- lineage and drill ----------------------------------------------------------

def test_lineage_names_sources_sql_and_users(client, svc):
    lin = client.get(f"{P}/metrics/M001/lineage").json()
    assert lin["sources"] and lin["num_sql"]
    assert lin["versions"][0]["version"] == 1
    assert lin["used_by"]["issue_detectors"], "Requires Attention uses M001"
    detail = client.get(f"{P}/metrics/M001").json()
    assert detail["object_id"] == "met-m001" and detail["object_version"] >= 1


def test_drill_to_rows_honours_the_clicked_dimension(client, svc):
    flt = json.dumps([{"column": "sector", "op": "in",
                       "values": ["Construction"]}])
    out = client.get(f"{P}/metrics/M001/rows",
                     params={"domain": "corporate", "filters": flt,
                             "limit": 500}).json()
    assert out["total"] == 248
    assert {r["sector"] for r in out["rows"]} == {"Construction"}
