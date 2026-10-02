"""Exhaustive validation round: one regression test per proven backend defect
(docs/guided_workspace/validation/DEFECT_REGISTER.md), plus restart
persistence and the HTTP negative states the round measured.

EVIDENCE LABEL: no model call. The runtime carries a scripted provider with an
empty script; every test asserts nothing was sent to it.
"""

# Fixtures are shared with sibling suites by import; pytest injects them by
# parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import io
import json
import zipfile

import pytest

from backend.workspace import access, scenarios, service
from backend.workspace.store import WorkspaceStore
from tests.cockpit_v4.conftest import ScriptedProvider
from tests.cockpit_v4.test_gw_runs import (  # noqa: F401 (fixtures)
    COLLEAGUE,
    CONSTRUCTION,
    WHO,
    P,
    client,
    confirm,
    execute,
    full_run,
    method,
    start,
    svc,
    uat_scenario,
    who,
)

#: Strings that must never reach a user: engine SQL, Python internals.
LEAKS = ("SELECT ", "duckdb", "Binder Error", "Conversion Error", "Traceback",
         "<class ", "decimal.", "KeyError", "/home/")


@pytest.fixture
def model(runtime):
    provider = ScriptedProvider([])
    runtime.provider = provider
    yield provider
    assert provider.sent == [], "the workspace made a model call"


def _code(resp):
    return resp.json()["detail"]["error_code"]


def _no_leak(resp):
    text = resp.text
    assert not [m for m in LEAKS if m in text], text[:400]


def _own(client, name="VAL scenario"):
    r = client.post(f"{P}/scenarios", json={"status": "SAVED", "definition": {
        "name": name, "domain_id": "corporate", "description": "validation",
        "risk_thesis": "t",
        "scope": {"type": "filters", "label": "Construction",
                  "filters": CONSTRUCTION},
        "components": [{"kind": "parameter", "field": "pd_pit_12m",
                        "operation": "multiply", "value": "1.20",
                        "label": "PD x1.20"}],
        "stage_policy": "frozen", "severity": "moderate", "tags": ["val"]}})
    assert r.status_code == 201, r.text
    return r.json()


def _needs_policy(svc, object_id):
    body = svc.get(object_id, service.principal(WHO))["body"]
    return [m for m in scenarios.lib.preview(access.book(WHO, "corporate"),
                                             body)["overlaps"]
            if m["status"] == "NEEDS_POLICY"]


# ---- VAL-DEF-010 (CRITICAL): an unrunnable scenario never reaches a run ------------

def test_val_def_010_a_conflict_template_is_refused_before_a_run_exists(
        client, svc, model):
    scenarios.ensure_seeded(svc, WHO)
    before = len(svc.store.latest_of_kind("run", tenant_id="demo-tenant"))
    r = client.post(f"{P}/whatif/runs", json={
        "scenario_id": scenarios.template_object_id("CORP-18")})
    assert r.status_code == 409 and _code(r) == "COMPOSITION_POLICY_REQUIRED"
    assert "composition policy" in r.json()["detail"]["message"]
    assert len(svc.store.latest_of_kind("run", tenant_id="demo-tenant")) \
        == before, "no run object was written"


def test_val_def_010_an_unresolved_combination_is_refused(client, svc, model):
    scenarios.ensure_seeded(svc, WHO)
    out = client.post(f"{P}/scenarios/combine", json={"sources": [
        {"object_id": scenarios.template_object_id("CORP-01")},
        {"object_id": scenarios.template_object_id("CORP-05")}],
        "name": "A+B"}).json()
    sid = out["scenario"]["object_id"]
    need = _needs_policy(svc, sid)
    assert need
    r = client.post(f"{P}/whatif/runs", json={"scenario_id": sid})
    assert r.status_code == 409 and _code(r) == "COMPOSITION_POLICY_REQUIRED"
    # Choosing every policy makes the same combination runnable, and the
    # executed result reconciles (the stacking path is not broken).
    fixed = client.post(f"{P}/scenarios/{sid}/resolve", json={
        "resolutions": {m["overlap_id"]: {"policy": m["allowed"][0]}
                        for m in need}})
    assert fixed.status_code == 200, fixed.text
    _run, result = full_run(client, sid)
    assert result is not None
    sel = result["body"]["decomposition"]["delta"]["scopes"]["selected"]
    assert sel["reconciles"] is True


def test_val_def_010_a_retired_scenario_is_not_run(client, svc, model):
    obj = _own(client)
    oid = obj["object_id"]
    assert client.post(f"{P}/scenarios/{oid}/retire").status_code == 200
    r = client.post(f"{P}/whatif/runs", json={"scenario_id": oid})
    assert r.status_code == 409 and _code(r) == "SCENARIO_RETIRED"
    # An earlier version of a now-retired scenario is refused too.
    r = client.post(f"{P}/whatif/runs", json={"scenario_id": oid,
                                              "scenario_version": 1})
    assert r.status_code == 409 and _code(r) == "SCENARIO_RETIRED"


# ---- VAL-DEF-011: retire is idempotent; a retired scenario is not revised ---------

def test_val_def_011_retire_twice_writes_one_version(client, svc, model):
    oid = _own(client)["object_id"]
    first = client.post(f"{P}/scenarios/{oid}/retire").json()
    second = client.post(f"{P}/scenarios/{oid}/retire").json()
    first_v = first.get("version") or first["scenario"]["version"]
    second_v = second.get("version") or second["scenario"]["version"]
    assert first_v == second_v
    hist = client.get(f"{P}/objects/{oid}/history").json()["versions"]
    assert [v["status"] for v in hist].count("ARCHIVED") == 1
    r = client.post(f"{P}/scenarios/{oid}/revise",
                    json={"changes": {"name": "after retirement"}})
    assert r.status_code == 409 and _code(r) == "SCENARIO_RETIRED"


# ---- VAL-DEF-015: a policy for an overlap that does not exist is refused ----------

def test_val_def_015_unknown_overlap_id_is_refused(client, svc, model):
    scenarios.ensure_seeded(svc, WHO)
    out = client.post(f"{P}/scenarios/combine", json={"sources": [
        {"object_id": scenarios.template_object_id("CORP-01")},
        {"object_id": scenarios.template_object_id("CORP-05")}]}).json()
    sid = out["scenario"]["object_id"]
    before = client.get(f"{P}/objects/{sid}/history").json()["versions"]
    r = client.post(f"{P}/scenarios/{sid}/resolve", json={
        "resolutions": {"bogus-id": {"policy": "max"}}})
    assert r.status_code == 422 and _code(r) == "UNKNOWN_OVERLAP"
    after = client.get(f"{P}/objects/{sid}/history").json()["versions"]
    assert len(after) == len(before), "nothing was written"


# ---- VAL-DEF-008: assigning to the current assignee writes nothing ----------------

def test_val_def_008_repeated_assign_is_a_no_op(client, svc, model):
    client.get(f"{P}/monitoring")
    alert = next(a for a in svc.store.latest_of_kind(
        "alert", tenant_id="demo-tenant")
        if not a["body"].get("demo_historical"))
    url = f"{P}/monitoring/alerts/{alert['object_id']}"
    one = client.post(f"{url}/assign", json={}).json()
    two = client.post(f"{url}/assign", json={}).json()
    assert one["version"] == two["version"]
    events = client.get(url).json()["events"]
    assigned = [e for e in events if "assigned to" in (e.get("note") or "")]
    assert len(assigned) == 1, events


# ---- grid and cohort negative states ----------------------------------------------

def test_a_wrong_type_filter_value_is_422_in_plain_words(client, svc, model):
    bad = [{"column": "sector", "op": "gt", "value": 5}]
    for path, body in (("/grid/query", {"filters": bad}),
                       ("/grid/export", {"filters": bad})):
        r = client.post(f"{P}{path}", json=body)
        assert r.status_code == 422, (path, r.status_code, r.text[:300])
        assert _code(r) == "INVALID_FILTER"
        _no_leak(r)


def test_a_cohort_on_an_unresolvable_filter_names_no_sql(client, svc, model):
    r = client.post(f"{P}/cohorts", json={
        "name": "bad", "filters": [{"column": "sector", "op": "gt",
                                    "value": 5}]})
    assert r.status_code == 422, r.text
    _no_leak(r)


def test_paging_beyond_the_book_is_empty_and_a_huge_offset_is_refused(
        client, svc, model):
    r = client.post(f"{P}/grid/query", json={"offset": 10_000_000})
    assert r.status_code == 200 and r.json()["rows"] == []
    assert r.json()["total"] > 0
    r = client.post(f"{P}/grid/query", json={"offset": 2 ** 63})
    assert r.status_code == 422
    _no_leak(r)


# ---- Lens rule validation ---------------------------------------------------------

@pytest.mark.parametrize(("rule", "why"), [
    ({"comparison": "gt"}, "threshold"),
    ({"comparison": "gt", "threshold": "high"}, "threshold"),
    ({"comparison": "gt", "threshold": 0.1, "domain": "mars"}, "scope"),
    ({"comparison": "gt", "threshold": 0.1, "severity": "urgent"},
     "severity"),
    ({"comparison": "gt", "threshold": 0.1, "name": ""}, "name"),
])
def test_an_unevaluable_lens_rule_is_refused_on_save(client, svc, model,
                                                     rule, why):
    full = {"rule_id": "r1", "name": "rule", "metric_id": "M001",
            "domain": "corporate", "severity": "high", **rule}
    if "threshold" not in rule:
        full.pop("threshold", None)
    r = client.post(f"{P}/lenses/lens-02/revise", json={
        "changes": {"breach_rules": [full]}, "reason": "validation"})
    assert r.status_code == 422, r.text
    assert _code(r) == "INVALID_RULE"
    assert why in r.json()["detail"]["message"]
    # The Lens still refreshes: the bad rule was never stored.
    assert client.post(f"{P}/lenses/lens-02/refresh").status_code in (200,
                                                                      201)


def test_listing_parameters_outside_their_vocabulary_are_refused(
        client, svc, model):
    for path in ("/lenses?domain=xyz", "/monitoring?domain=xyz",
                 "/monitoring?view=bogus", "/monitoring?severity=bogus"):
        assert client.get(f"{P}{path}").status_code == 422, path
    for path in ("/lenses?domain=retail", "/monitoring?view=all",
                 "/monitoring?severity=high&domain=corporate"):
        assert client.get(f"{P}{path}").status_code == 200, path


# ---- run-state messages -----------------------------------------------------------

def test_a_non_numeric_assumption_is_explained_without_python_names(
        client, svc, model):
    obj, cohort = uat_scenario(svc)
    run = confirm(client, start(client, obj["object_id"],
                                cohort_id=cohort["object_id"]))
    r = client.post(f"{P}/whatif/runs/{run['object_id']}/method", json={
        "methods": ["user_defined"],
        "user_assumption": {"form": "relative", "value": "abc"}})
    assert r.status_code == 422 and _code(r) == "INVALID_ASSUMPTION"
    assert "must be a number" in r.json()["detail"]["message"]
    _no_leak(r)


def test_execute_refusal_says_why_at_method_input_required(client, svc,
                                                           model):
    obj, cohort = uat_scenario(svc)
    run = method(client, confirm(client, start(
        client, obj["object_id"], cohort_id=cohort["object_id"])),
        ["user_defined"])
    assert run["status"] == "METHOD_INPUT_REQUIRED"
    r = execute(client, run)
    assert r.status_code == 409
    msg = r.json()["detail"]["message"]
    assert "needs your input" in msg and "Nothing was executed" in msg


# ---- stale share ------------------------------------------------------------------

def test_a_share_of_a_since_retired_scenario_says_so_and_offers_no_run(
        client, svc, who, model):
    oid = _own(client, "To share")["object_id"]
    assert client.post(f"{P}/scenarios/{oid}/share",
                       json={"to": ["colleague"]}).status_code in (200, 201)
    client.post(f"{P}/scenarios/{oid}/retire")
    who.clear()
    who.update(COLLEAGUE)
    item = next(i for i in client.get(f"{P}/messages").json()["items"]
                if i["object_id"] == oid)
    d = client.get(f"{P}/messages/{item['share_id']}").json()
    assert d["retired"] is True and d["latest_status"] == "ARCHIVED"
    actions = {a["action"] for a in d["actions"]}
    assert not actions & {"run", "rerun_latest"}
    assert "duplicate" in actions
    r = client.post(f"{P}/messages/{item['share_id']}/run", json={})
    assert r.status_code == 409 and _code(r) == "SCENARIO_RETIRED"


# ---- export of an unexecuted run ----------------------------------------------------

def test_an_unexecuted_run_export_carries_a_caveat(client, svc, model):
    obj, cohort = uat_scenario(svc)
    run = confirm(client, start(client, obj["object_id"],
                                cohort_id=cohort["object_id"]))
    r = client.get(f"{P}/exports/objects/{run['object_id']}")
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["caveats"] and "NOT executed" in manifest["caveats"][0]
    assert "CAVEAT: This run was NOT executed" in zf.read(
        "README.txt").decode()
    _run, result = full_run(client, obj["object_id"],
                            cohort_id=cohort["object_id"], session_id="x")
    done = client.get(f"{P}/exports/objects/{_run['object_id']}")
    assert json.loads(zipfile.ZipFile(io.BytesIO(done.content)).read(
        "manifest.json"))["caveats"] == []


# ---- restart persistence: reopen, zero model calls ----------------------------------

def test_every_object_survives_a_store_restart_unchanged(client, svc, model,
                                                         tmp_path):
    obj, cohort = uat_scenario(svc)
    run, result = full_run(client, obj["object_id"],
                           cohort_id=cohort["object_id"], session_id="r")
    ids = [obj["object_id"], cohort["object_id"], run["object_id"],
           result["object_id"]]
    p = service.principal(WHO)
    before = {i: svc.get(i, p) for i in ids}
    ledger = svc.store.verify_ledger(tenant_id="demo-tenant")
    path = svc.store.path
    service.use_store(None)
    service.use_store(WorkspaceStore(path))
    again = service.objects()
    for i in ids:
        now = again.get(i, p)
        assert now["content_hash"] == before[i]["content_hash"]
        assert now["version"] == before[i]["version"]
        assert now["status"] == before[i]["status"]
    reread = client.get(f"{P}/scenarios/{obj['object_id']}/results").json()
    assert result["object_id"] in json.dumps(reread)
    after = again.store.verify_ledger(tenant_id="demo-tenant")
    assert after["ok"] and after["entries"] == ledger["entries"]
    assert after["chain_head"] == ledger["chain_head"]
