"""P9 — Lenses 2.0: populated persona Lenses on governed metrics.

EVIDENCE LABEL: no model call. Every Lens renders from the candidate books
through the metric engine; the one-prompt proposer is deterministic.
"""

from __future__ import annotations

import itertools
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import cohort_refs
from backend.workspace import access, cohorts, lenses, metrics, service
from backend.workspace import api as workspace_api
from backend.workspace import lens_seed as seed
from backend.workspace import metric_catalog as mc
from backend.workspace.store import WorkspaceStore

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = ("v4-whatif-corporate-20q-s1", "v4-whatif-retail-20m-s1")
WHO = {"id": "banker", "tenant": "demo-tenant", "roles": ("analyst",)}
COLLEAGUE = {"id": "colleague", "tenant": "demo-tenant", "roles": ("analyst",)}

#: §45's minimum catalogue, by id and name.
SPEC = {"LENS-01": "CRO Executive Overview",
        "LENS-02": "Head of Corporate Credit",
        "LENS-03": "Head of Retail Risk", "LENS-04": "IFRS 9 / ECL Oversight",
        "LENS-05": "Early Warning Command Center",
        "LENS-06": "Corporate Portfolio Manager",
        "LENS-07": "Retail Portfolio Manager", "LENS-08": "Credit Card Risk",
        "LENS-09": "Personal Finance Risk", "LENS-10": "Home Finance Risk",
        "LENS-11": "Auto Finance Risk", "LENS-12": "Collections & Recoveries",
        "LENS-13": "Risk Appetite & Limits",
        "LENS-14": "Board Risk Committee Pack",
        "LENS-15": "Sector Watch — Construction & CRE",
        "LENS-16": "Scenario Impact Watch",
        "LENS-17": "Data Quality & Coverage",
        "LENS-18": "Monitoring & Breach Executive"}


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


def render(client, oid, **body):
    r = client.post(f"{P}/lenses/{oid}/render", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---- first launch ----------------------------------------------------------------

def test_first_launch_library_holds_the_18_spec_lenses_and_more(client):
    lib = client.get(f"{P}/lenses").json()
    assert lib["total"] >= 18 and lib["state"] == "OK"
    by_id = {c["lens_id"]: c for c in lib["lenses"]}
    for lens_id, name in SPEC.items():
        assert by_id[lens_id]["name"] == name
    assert len({c["name"] for c in lib["lenses"]}) == lib["total"]


def test_lenses_are_materially_distinct():
    sigs = {lens["lens_id"]: {(v["type"], v.get("metric_id"), v["domain"],
                                v.get("group_by"), str(lens["filters"]))
                               for v in lens["visuals"]}
            for lens in seed.LENSES}
    for a, b in itertools.combinations(sigs, 2):
        jaccard = len(sigs[a] & sigs[b]) / len(sigs[a] | sigs[b])
        assert jaccard < 0.6, (a, b, jaccard)


def test_every_lens_renders_real_values_in_at_least_five_visuals(client):
    for c in client.get(f"{P}/lenses").json()["lenses"]:
        out = render(client, c["object_id"])
        visuals = out["visuals"]
        assert len(visuals) >= 5, c["name"]
        for v in visuals:
            assert v["status"] == "OK", (c["name"], v)
            if v["type"] == "kpi":
                assert v["value"] is not None or v.get("note"), \
                    (c["name"], v["metric_id"])
            if v["type"] in ("breakdown", "stage_mix"):
                assert v["groups"], (c["name"], v["title"])
            if v["type"] == "table":
                assert v["rows"], (c["name"], v["title"])
            if v["type"] == "trend":
                assert all(s["points"] for s in v["series"])


def test_no_anonymous_kpi_every_binding_is_a_pinned_catalogue_metric(client,
                                                                     svc):
    for lens in svc.list("lens", service.principal(WHO)):
        b = lens["body"]
        for m in b["metrics"]:
            assert m["metric_id"] in mc.BY_ID
            assert m["version"] == mc.BY_ID[m["metric_id"]]["version"]
        bound = {(m["metric_id"], m["domain"]) for m in b["metrics"]}
        for v in b["visuals"]:
            for mid in v.get("metric_ids") or [v["metric_id"]]:
                assert (mid, v["domain"]) in bound
        for r in b["breach_rules"]:
            assert (r["metric_id"], r["domain"]) in bound
        assert b["refresh"]["cadence"] in lenses.CADENCES
    assert all(lens["body"]["breach_rules"]
               for lens in svc.list("lens", service.principal(WHO))
               if lens["seeded"])


# ---- reactive behaviour -------------------------------------------------------------

def test_a_category_click_cross_filters_every_compatible_visual(client):
    cross = [{"column": "sector", "op": "in", "values": ["Construction"],
              "domain": "corporate"}]
    out = render(client, "lens-02", cross_filters=cross)
    by_sector = next(v for v in out["visuals"]
                     if v["type"] == "breakdown" and v["group_by"] == "sector")
    assert [g["dimension"] for g in by_sector["groups"]] == ["Construction"]
    table = next(v for v in out["visuals"] if v["type"] == "table")
    assert {r["sector"] for r in table["rows"]} == {"Construction"}
    ecl = next(v for v in out["visuals"] if v["type"] == "kpi"
               and v["metric_id"] == "M001")
    base = render(client, "lens-02")
    ecl0 = next(v for v in base["visuals"] if v["type"] == "kpi"
                and v["metric_id"] == "M001")
    assert ecl["value"] < ecl0["value"]
    # A both-book Lens applies it to Corporate and SAYS it skipped Retail.
    cro = render(client, "lens-01", cross_filters=cross)
    retail = next(v for v in cro["visuals"] if v["domain"] == "retail"
                  and v["type"] == "kpi")
    assert retail["filters_skipped"] and not retail["filters_applied"]


def test_moving_the_lens_to_a_period_is_explicit(client):
    base = render(client, "lens-02")
    prior = base["books"]["corporate"]["periods"][-2]
    moved = render(client, "lens-02", periods={"corporate": prior})
    assert moved["books"]["corporate"]["period"] == prior
    assert all(v["period"] == prior for v in moved["visuals"]
               if v["status"] == "OK")


def test_default_filters_scope_a_product_lens(client):
    out = render(client, "lens-08")
    table = next(v for v in out["visuals"] if v["type"] == "table")
    assert {r["product"] for r in table["rows"]} == {"Credit Card"}


# ---- refresh -------------------------------------------------------------------------

def test_refresh_records_an_immutable_observation_with_what_changed(client,
                                                                    svc):
    first = client.post(f"{P}/lenses/lens-01/refresh").json()
    assert first["status"] == "SUCCEEDED"
    assert first["body"]["what_changed"].startswith("First observation")
    assert any(b["breached"] for b in first["body"]["breaches"])
    second = client.post(f"{P}/lenses/lens-01/refresh").json()
    # The books did not move. Only the platform metric M048 (active breach
    # count) may, because the first refresh raised alerts.
    moved = {c["metric_id"] for c in second["body"]["material_changes"]}
    assert moved <= {"M048"}, moved
    assert second["body"]["previous_observation"] == first["observation_id"]
    same = lenses.refresh(svc, WHO, "lens-01", trigger="on_publication")
    assert same.get("idempotent") is True
    hist = client.get(f"{P}/lenses/lens-01/observations").json()
    assert len(hist["observations"]) == 2
    with pytest.raises(sqlite3.DatabaseError):
        svc.store._conn.execute(
            "UPDATE lens_observations SET status='X' WHERE observation_id=?",
            (first["observation_id"],))


def test_a_material_move_is_reported(client, svc):
    first = lenses.refresh(svc, WHO, "lens-02")
    body = dict(first["body"])
    values = {d: {m: dict(v) for m, v in per.items()}
              for d, per in body["values"].items()}
    values["corporate"]["M001"]["value"] *= 0.8
    svc.store.add_observation({**{k: first[k] for k in (
        "tenant_id", "lens_id", "lens_version", "release_id", "fingerprint",
        "period")}, "trigger": "test", "status": "SUCCEEDED",
        "started_at": first["started_at"] + 1,
        "finished_at": first["finished_at"] + 1,
        "body": {**body, "values": values}})
    again = lenses.refresh(svc, WHO, "lens-02")
    moved = {c["metric_id"] for c in again["body"]["material_changes"]}
    assert "M001" in moved and "Booked ECL" in again["body"]["what_changed"]


# ---- creating and editing ---------------------------------------------------------

def test_a_prompt_returns_a_preview_and_nothing_is_saved(client, svc):
    before = len(svc.list("lens", service.principal(WHO)))
    out = client.post(f"{P}/lenses/propose", json={
        "prompt": "Credit card dashboard with Stage 2 EAD share, weekly"}
    ).json()
    assert out["matched_template"] == "LENS-08" and out["saved"] is False
    assert out["summary"]["refresh"] == "weekly"
    assert any(v.get("metric_id") == "M005" for v in out["spec"]["visuals"])
    assert len(svc.list("lens", service.principal(WHO))) == before
    refined = client.post(f"{P}/lenses/propose", json={
        "prompt": "remove stage 2 ead share", "base": out["spec"]}).json()
    assert not any(v.get("metric_id") == "M005" and v["type"] == "kpi"
                   for v in refined["spec"]["visuals"])
    saved = client.post(f"{P}/lenses", json={"spec": out["spec"]}).json()
    assert saved["owner_id"] == "banker" and saved["version"] == 1
    assert render(client, saved["object_id"])["visuals"]


def test_an_anonymous_metric_is_refused(client):
    spec = lenses.propose(WHO, "credit card")["spec"]
    spec["visuals"].append({"type": "kpi", "metric_id": "X999",
                            "domain": "retail", "visual_id": "v99"})
    r = client.post(f"{P}/lenses", json={"spec": spec})
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "ANONYMOUS_METRIC"


def test_editing_writes_a_version_and_a_library_lens_is_copied(client, svc):
    lib = client.post(f"{P}/lenses/lens-02/revise", json={
        "changes": {"name": "My corporate credit view"},
        "reason": "rename"})
    assert lib.status_code == 200, lib.text
    lib = lib.json()
    assert lib["object_id"] != "lens-02" and lib["owner_id"] == "banker"
    assert svc.get("lens-02", service.principal(WHO))["version"] == 1
    v2 = client.post(f"{P}/lenses/{lib['object_id']}/revise", json={
        "changes": {"refresh": {"cadence": "weekly", "timezone": "Asia/Riyadh",
                                "expected_availability": "x"}},
        "reason": "weekly"})
    assert v2.status_code == 200, v2.text
    v2 = v2.json()
    assert v2["object_id"] == lib["object_id"] and v2["version"] == 2


def test_save_an_investigation_as_a_lens_keeps_its_cohort(client, svc):
    book = access.book(WHO, "corporate")
    principal = service.principal(WHO)
    coh = cohorts.freeze(book, svc, principal, name="Construction",
                         filters=[{"column": "sector", "op": "in",
                                   "values": ["Construction"]}])
    inv = svc.create("investigation", principal, {
        "title": "Construction deterioration", "path": [],
        "cohort_id": coh["object_id"], "domain_id": "corporate",
        "thread_id": "th-x"}, title="Construction deterioration",
        domain_id="corporate")
    out = client.post(f"{P}/lenses/propose", json={
        "from_investigation": inv["object_id"]}).json()
    assert out["spec"]["filters"]["corporate"][0]["values"] == \
        ["Construction"]
    assert out["source"]["kind"] == "investigation"
    saved = client.post(f"{P}/lenses", json={"spec": out["spec"],
                                             "source": out["source"]}).json()
    assert saved["lineage"]["derived_from"][0][0] == inv["object_id"]


def test_a_lens_is_shared_through_messages(client, who):
    lens = client.post(f"{P}/lenses", json={
        "spec": lenses.propose(WHO, "retail portfolio")["spec"]}).json()
    client.post(f"{P}/messages", json={"object_id": lens["object_id"],
                                       "to": ["colleague"]})
    who.clear()
    who.update(COLLEAGUE)
    item = next(i for i in client.get(f"{P}/messages").json()["items"]
                if i["object_id"] == lens["object_id"])
    d = client.get(f"{P}/messages/{item['share_id']}").json()
    assert {a["action"] for a in d["actions"]} >= {"open", "save", "comment"}
    assert render(client, lens["object_id"])["visuals"]


def test_scenario_metrics_only_count_results_the_viewer_can_open(client, svc,
                                                                  who):
    lib = client.get(f"{P}/lenses").json()   # seeds tenant-visible demos
    assert lib["total"]
    out = render(client, "lens-16")
    k39 = next(v for v in out["visuals"] if v["metric_id"] == "M039"
               and v["domain"] == "corporate" and v["type"] == "kpi")
    assert k39["value"] is not None, "the tenant-visible demo result counts"
    scen = next(v for v in out["visuals"] if v["type"] == "scenario_results"
                and v["domain"] == "corporate")
    seen = {g["object_id"] for g in scen["groups"]}
    private = [r for r in svc.store.latest_of_kind(
        "scenario_result", tenant_id="demo-tenant")
        if (r["permissions"] or {}).get("visibility") != "tenant"]
    assert not (seen & {r["object_id"] for r in private})
