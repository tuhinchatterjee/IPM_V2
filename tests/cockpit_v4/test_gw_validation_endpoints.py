"""Exhaustive validation: the workspace endpoints no earlier suite called by
HTTP, each asserted on the business state it returns or writes (not only its
status code).

EVIDENCE LABEL: no model call (the runtime's provider is a scripted provider
with an empty script; every test asserts nothing was sent to it).
"""

# ruff: noqa: F811

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.workspace import access, grid, metrics, monitoring, scenarios, service
from tests.cockpit_v4.conftest import ScriptedProvider
from tests.cockpit_v4.test_gw_runs import (  # noqa: F401 (fixtures)
    CONSTRUCTION,
    WHO,
    P,
    client,
    full_run,
    svc,
    uat_scenario,
    who,
)


@pytest.fixture
def model(runtime):
    provider = ScriptedProvider([])
    runtime.provider = provider
    yield provider
    assert provider.sent == [], "a workspace endpoint called the model"


def D(x):
    return Decimal(str(x if x is not None else 0))


def test_grid_schema_values_and_group_describe_the_same_book(client, svc,
                                                             model):
    schema = client.get(f"{P}/grid/schema?domain=corporate").json()
    book = access.book(WHO, "corporate")
    assert schema["fingerprint"] == book.fingerprint
    assert schema["key"] == "facility_id"
    assert {"sector", "ecl_sar_mn", "stage"} <= {c["key"] for c in
                                                schema["columns"]}
    total = client.post(f"{P}/grid/query", json={"limit": 1}).json()
    values = client.get(f"{P}/grid/values?domain=corporate&column=sector"
                        ).json()["values"]
    assert sum(v["count"] for v in values) == total["total"], \
        "every row has exactly one sector value"
    groups = client.post(f"{P}/grid/group", json={
        "domain": "corporate", "dimension": "sector"}).json()["groups"]
    ecl = sum(D(g.get("ecl_sar_mn")) for g in groups)
    assert abs(ecl - D(total["summary"]["ecl"])) <= Decimal("1e-6")
    assert client.get(f"{P}/grid/values?domain=corporate&column=nope"
                      ).status_code == 422


def test_an_issue_cohort_freezes_the_issue_population(client, svc, model):
    issue = client.get(f"{P}/issues?domain=corporate").json()["issues"][0]
    out = client.post(f"{P}/issues/{issue['issue_id']}/cohort",
                      json={"domain": "corporate"})
    assert out.status_code in (200, 201), out.text
    cohort = out.json()
    assert cohort["kind"] == "cohort"
    assert cohort["body"]["counts"]["entities"] == issue["cohort"]["entities"]
    assert cohort["body"]["source"]["ref"] == issue["issue_id"]


def test_metric_evaluate_matches_the_metric_engine(client, svc, model):
    book = access.book(WHO, "corporate")
    r = client.post(f"{P}/metrics/evaluate", json={"metric_id": "M001",
                                                   "domain": "corporate"})
    assert r.status_code == 200, r.text
    token = metrics.VIEWER.set(service.principal(WHO))
    try:
        direct = metrics.evaluate(book, "M001")
    finally:
        metrics.VIEWER.reset(token)
    assert r.json()["value"] == direct["value"]
    assert client.post(f"{P}/metrics/evaluate", json={
        "metric_id": "M999", "domain": "corporate"}).status_code == 404


def _breach(client, svc):
    client.get(f"{P}/monitoring")
    return next(a for a in svc.store.latest_of_kind("alert",
                                                    tenant_id="demo-tenant")
                if a["body"].get("alert_type") == "breach"
                and not a["body"].get("demo_historical"))


def test_an_alert_cohort_and_investigation_carry_the_alert_population(
        client, svc, model):
    alert = _breach(client, svc)
    c = client.post(f"{P}/monitoring/alerts/{alert['object_id']}/cohort")
    assert c.status_code == 201, c.text
    cohort = c.json()
    assert cohort["kind"] == "cohort"
    assert cohort["domain_id"] == alert["body"]["domain_id"]
    aid = alert["object_id"]
    inv = client.post(f"{P}/monitoring/alerts/{aid}/investigate")
    assert inv.status_code == 201, inv.text
    assert inv.json()["thread_id"].startswith("th-")
    seeded = client.get(f"{P}/whatif/threads/{inv.json()['thread_id']}/"
                        f"cohort").json()
    assert seeded["has_cohort"] is False
    assert seeded["seed_cohort_id"] == inv.json()["cohort_id"], \
        "the thread names the governed cohort it was opened on"
    frozen = client.get(f"{P}/objects/{inv.json()['cohort_id']}").json()
    assert frozen["body"]["membership_hash"] == \
        cohort["body"]["membership_hash"], "the same alert population"


def test_tick_and_refresh_and_alert_record_observations(client, svc, model):
    monitoring.ensure_seeded(svc, WHO)
    first = client.post(f"{P}/monitoring/tick")
    assert first.status_code == 200, first.text
    lens = client.get(f"{P}/lenses").json()["lenses"][0]
    before = len(client.get(f"{P}/lenses/{lens['object_id']}/observations"
                            ).json()["observations"])
    out = client.post(f"{P}/lenses/{lens['object_id']}/refresh-and-alert")
    assert out.status_code == 200, out.text
    assert out.json()["observation"]["status"] in ("SUCCEEDED",
                                                    "UNCHANGED", "FAILED")
    after = client.get(f"{P}/lenses/{lens['object_id']}/observations"
                       ).json()["observations"]
    assert len(after) >= before + (0 if out.json()["observation"].get(
        "idempotent") else 1)


def test_a_cohort_refresh_on_an_unchanged_book_is_identical(client, svc,
                                                            model):
    c = client.post(f"{P}/cohorts", json={"domain": "corporate",
                                          "name": "c", "filters":
                                          CONSTRUCTION}).json()
    r = client.post(f"{P}/cohorts/{c['object_id']}/refresh")
    assert r.status_code == 200, r.text
    body = r.json()
    after = body.get("cohort", body)
    assert after["body"]["membership_hash"] == c["body"]["membership_hash"]


def test_clone_branch_and_lineage(client, svc, model):
    scenarios.ensure_seeded(svc, WHO)
    tpl = scenarios.template_object_id("CORP-01")
    a = client.post(f"{P}/scenarios/{tpl}/clone", json={"name": "A copy"})
    b = client.post(f"{P}/scenarios/{tpl}/branch", json={})
    assert a.status_code == b.status_code == 201
    assert a.json()["lineage"]["origin"] == "duplicate"
    assert b.json()["lineage"]["origin"] == "branch"
    tree = client.get(f"{P}/objects/{a.json()['object_id']}/lineage").json()
    assert [x["object_id"] for x in tree["ancestors"]] == [tpl]
    kids = client.get(f"{P}/objects/{tpl}/lineage").json()["descendants"]
    assert {a.json()["object_id"], b.json()["object_id"]} <= \
        {k["object_id"] for k in kids}
    assert "scenario" in client.get(f"{P}/kinds").json()["kinds"]


def test_preview_of_an_unsaved_definition_writes_nothing(client, svc, model):
    before = len(svc.store.latest_of_kind("scenario", tenant_id="demo-tenant"))
    r = client.post(f"{P}/scenarios/preview", json={"definition": {
        "name": "unsaved", "domain_id": "corporate",
        "scope": {"type": "filters", "label": "C", "filters": CONSTRUCTION},
        "components": [{"kind": "parameter", "field": "pd_pit_12m",
                        "operation": "multiply", "value": "1.2"}],
        "stage_policy": "frozen"}})
    assert r.status_code == 200, r.text
    assert r.json()["scope"]["summary"]["entities"] == 248
    assert len(svc.store.latest_of_kind("scenario",
                                        tenant_id="demo-tenant")) == before


def test_my_results_list_the_executed_result_and_ask_context_carries_the_cohort(
        client, svc, model):
    obj, cohort = uat_scenario(svc)
    _run, result = full_run(client, obj["object_id"],
                            cohort_id=cohort["object_id"], session_id="r")
    mine = client.get(f"{P}/whatif/results").json()["results"]
    assert result["object_id"] in {r["object_id"] for r in mine}
    ctx = client.post(f"{P}/whatif/ask-context", json={
        "cohort_id": cohort["object_id"], "scenario_id": obj["object_id"]})
    assert ctx.status_code == 200, ctx.text
    text = str(ctx.json())
    assert cohort["object_id"] in text and \
        cohort["body"]["membership_hash"][:12] in text


def test_an_exchange_call_is_readable_only_by_exchange_roles(client, svc,
                                                             who, model,
                                                             monkeypatch,
                                                             tmp_path):
    from backend.llm import exchange
    from backend.workspace import exchange_api
    from tests.cockpit_v4.conftest import ScriptedResult

    store = exchange.ExchangeStore(tmp_path / "x.sqlite3")

    class Inner:
        name = "inner"

        def converse(self, **kw):
            return ScriptedResult(text="hi", stop_reason="end_turn")

    exchange.RecordingProvider(Inner(), store, exchange.Binding(
        run_id="r-1", tenant_id="demo-tenant")).converse(
        system=[{"type": "text", "text": "S"}],
        messages=[{"role": "user", "content": "Q"}], tools=[],
        max_tokens=8, model="m")
    xid = store.for_run("r-1", tenant_id="demo-tenant")[0]["exchange_id"]
    monkeypatch.setattr(exchange_api, "exchange_store", lambda: store)
    assert client.get(f"{P}/llm-exchange/calls/{xid}").status_code == 403
    who.update({"roles": ("administrator",)})
    got = client.get(f"{P}/llm-exchange/calls/{xid}")
    assert got.status_code == 200, got.text
    assert got.json()["exchange_id"] == xid
    who.update({"tenant": "other-bank"})
    assert client.get(f"{P}/llm-exchange/calls/{xid}").status_code == 404


def test_grid_view_key_is_the_cohort_grain(svc):
    for domain, key in (("corporate", "facility_id"), ("retail",
                                                       "account_id")):
        assert grid.view(access.book(WHO, domain)).key == key
