"""P7 — Messages carry governed objects; lineage, tree, comparison, permissions.

EVIDENCE LABEL: NO MODEL. No model call. Workspace HTTP routes on the candidate books;
runs execute through the engine's `bridge.compute_core`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import cohort_refs
from backend.cockpit_v4.scenario import decomposition as dc
from backend.workspace import access, cohorts, messages, runs, scenarios, service
from backend.workspace import api as workspace_api
from backend.workspace.store import WorkspaceStore

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = ("v4-whatif-corporate-20q-s1", "v4-whatif-retail-20m-s1")
SENDER = {"id": "banker", "tenant": "demo-tenant", "roles": ("analyst",)}
RECIPIENT = {"id": "colleague", "tenant": "demo-tenant", "roles": ("analyst",)}
BYSTANDER = {"id": "bystander", "tenant": "demo-tenant", "roles": ("analyst",)}
STRANGER = {"id": "stranger", "tenant": "other-tenant", "roles": ("analyst",)}
CONSTRUCTION = [{"column": "sector", "op": "in", "values": ["Construction"]}]


@pytest.fixture
def svc(tmp_path, monkeypatch):
    for release in CANDIDATE:
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    access.reset_books()
    cohort_refs.register(cohorts.engine_resolver)
    service.use_store(WorkspaceStore(tmp_path / "ws.sqlite3"))
    yield service.objects()
    service.use_store(None)
    access.reset_books()


@pytest.fixture
def who():
    return dict(SENDER)


@pytest.fixture
def client(store_db, runtime, svc, who):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: who, startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app)


def as_(who, person):
    who.clear()
    who.update(person)


def D(x):
    return Decimal(str(x))


def executed(client, scenario_id, *, session="s", methods=("delta",), **kw):
    run = client.post(f"{P}/whatif/runs", json={"scenario_id": scenario_id,
                                                "session_id": session,
                                                **kw}).json()
    assert run["status"] == runs.SCENARIO_PREVIEW, run
    run = client.post(f"{P}/whatif/runs/{run['object_id']}/confirm",
                      json={"digest": run["body"]["contract"]["digest"]}
                      ).json()
    run = client.post(f"{P}/whatif/runs/{run['object_id']}/method",
                      json={"methods": list(methods)}).json()
    out = client.post(f"{P}/whatif/runs/{run['object_id']}/execute")
    assert out.status_code == 200, out.text
    return out.json()["run"], out.json()["result"]


def own_scenario(client, name="Sender Construction PD x1.20 LGD x1.10"):
    r = client.post(f"{P}/scenarios", json={"definition": {
        "name": name, "domain_id": "corporate", "description": "P7 test",
        "risk_thesis": "t",
        "scope": {"type": "filters", "label": "Construction",
                  "filters": CONSTRUCTION},
        "components": [
            {"kind": "parameter", "field": "pd_pit_12m",
             "operation": "multiply", "value": "1.20", "label": "PD x1.20"},
            {"kind": "parameter", "field": "lgd_pct", "operation": "multiply",
             "value": "1.10", "label": "LGD x1.10"}],
        "stage_policy": "frozen", "severity": "moderate", "tags": ["p7"]}})
    assert r.status_code in (200, 201), r.text
    return r.json()


def send(client, object_id, to=("colleague",), message="please review"):
    r = client.post(f"{P}/messages", json={"object_id": object_id,
                                           "to": list(to),
                                           "message": message})
    assert r.status_code == 201, r.text
    return r.json()


def received(client, object_id):
    items = client.get(f"{P}/messages").json()["items"]
    return next(i for i in items if i["object_id"] == object_id)


# ---- first launch ---------------------------------------------------------------

def test_first_launch_inbox_holds_synthetic_shared_definition_result_cohort(
        client, svc, who):
    as_(who, RECIPIENT)
    box = client.get(f"{P}/messages").json()
    kinds = {i["kind"] for i in box["items"] if i["seeded"]}
    assert {"scenario", "scenario_result", "cohort"} <= kinds
    for i in box["items"]:
        assert i["message"].startswith("[SYNTHETIC DEMO]")
        assert i["from_id"] == messages.SEED_SENDER
    assert box["unread"] == len(box["items"])
    result = next(i for i in box["items"] if i["kind"] == "scenario_result")
    d = client.get(f"{P}/messages/{result['share_id']}").json()
    assert d["accessible"] and d["object"]["body"]["methods"]["ran"] == \
        ["delta"]
    dc.check(d["object"]["body"]["decomposition"]["delta"])
    again = client.get(f"{P}/messages").json()
    assert len(again["items"]) == len(box["items"]), "seeded once"
    assert again["unread"] == len(box["items"]) - 1


# ---- unexecuted definition -----------------------------------------------------

def test_recipient_runs_a_shared_definition_as_their_own_linked_run(
        client, svc, who):
    scn = own_scenario(client)
    send(client, scn["object_id"])
    as_(who, RECIPIENT)
    msg = received(client, scn["object_id"])
    card = msg["card"]
    assert card["executed"] is False and card["author"] == "banker"
    assert card["components"] == ["PD x1.20", "LGD x1.10"]
    d = client.get(f"{P}/messages/{msg['share_id']}").json()
    assert {a["action"] for a in d["actions"]} >= {"open", "run",
                                                   "duplicate", "comment"}
    run = client.post(f"{P}/messages/{msg['share_id']}/run", json={}).json()
    assert run["owner_id"] == "colleague"
    assert run["status"] == runs.SCENARIO_PREVIEW
    assert run["body"]["shared_from"]["share_id"] == msg["share_id"]
    assert run["body"]["preview"]["entities"] == 248
    # Still scenario first, method second.
    run = client.post(f"{P}/whatif/runs/{run['object_id']}/confirm",
                      json={"digest": run["body"]["contract"]["digest"]}
                      ).json()
    assert run["status"] == runs.METHOD_SELECTION
    run = client.post(f"{P}/whatif/runs/{run['object_id']}/method",
                      json={"methods": ["delta"]}).json()
    out = client.post(f"{P}/whatif/runs/{run['object_id']}/execute").json()
    assert out["result"]["owner_id"] == "colleague"
    assert out["result"]["body"]["shared_from"]["object_id"] == \
        scn["object_id"]
    as_(who, SENDER)
    assert svc.get(scn["object_id"], service.principal(SENDER))[
        "body"]["name"] == scn["body"]["name"], "sender's object unchanged"


def test_run_on_my_cohort_uses_the_recipients_own_population(client, svc,
                                                              who):
    scn = own_scenario(client)
    send(client, scn["object_id"])
    as_(who, RECIPIENT)
    mine = cohorts.freeze(access.book(RECIPIENT, "corporate"), svc,
                          service.principal(RECIPIENT), name="my construction",
                          filters=CONSTRUCTION)
    msg = received(client, scn["object_id"])
    run = client.post(f"{P}/messages/{msg['share_id']}/run",
                      json={"cohort_id": mine["object_id"]}).json()
    assert run["body"]["cohort"]["membership_hash"] == \
        mine["body"]["membership_hash"]
    assert run["body"]["cohort"]["object"]["cohort_id"] == mine["object_id"]


def test_duplicate_branches_into_the_recipients_own_scenario(client, svc,
                                                              who):
    scn = own_scenario(client)
    send(client, scn["object_id"])
    as_(who, RECIPIENT)
    msg = received(client, scn["object_id"])
    copy = client.post(f"{P}/messages/{msg['share_id']}/duplicate").json()
    assert copy["owner_id"] == "colleague" and copy["kind"] == "scenario"
    assert copy["body"]["parents"][0]["object_id"] == scn["object_id"]
    assert copy["lineage"]["derived_from"][0][0] == scn["object_id"]


# ---- executed result -----------------------------------------------------------

def test_shared_result_opens_compares_reruns_and_saves(client, svc, who):
    scenarios.ensure_seeded(svc, SENDER)
    _run, result = executed(client, scenarios.template_object_id("CORP-01"))
    send(client, result["object_id"])
    as_(who, RECIPIENT)
    msg = received(client, result["object_id"])
    assert msg["card"]["executed"] is True
    assert msg["card"]["methods"] == ["delta"]
    assert msg["card"]["top_components"][0]["id"] == "pd"
    d = client.get(f"{P}/messages/{msg['share_id']}").json()
    acts = {a["action"] for a in d["actions"]}
    assert acts >= {"open", "compare", "rerun_latest", "run", "duplicate",
                    "save", "comment"}
    # Compare with my own result on the same book.
    _r, mine = executed(client, scenarios.template_object_id("CORP-12"),
                        session="mine")
    cmp_ = client.post(f"{P}/messages/{msg['share_id']}/compare",
                       json={"with_result_ids": [mine["object_id"]]})
    assert cmp_.status_code == 201, cmp_.text
    body = cmp_.json()["body"]
    assert body["method"] == "delta" and len(body["items"]) == 2
    pd_ = next(c for c in body["components"] if c["id"] == "pd")
    shared_pd = next(c for c in result["body"]["decomposition"]["delta"][
        "scopes"]["selected"]["components"] if c["id"] == "pd")
    assert pd_["values"][result["object_id"]]["selected"]["value"] == \
        shared_pd["value"], "copied, not recomputed"
    # Re-run on the latest data: a NEW run of the same definition.
    rerun = client.post(f"{P}/messages/{msg['share_id']}/run",
                        json={"latest": True}).json()
    assert rerun["body"]["scenario_id"] == result["body"]["scenario_id"]
    assert rerun["body"]["shared_from"]["mode"] == "rerun_latest"
    saved = client.post(f"{P}/messages/{msg['share_id']}/save").json()
    assert saved["owner_id"] == "colleague"
    assert saved["lineage"]["derived_from"][0][0] == result["object_id"]


def test_a_comparison_is_itself_shareable(client, svc, who):
    scenarios.ensure_seeded(svc, SENDER)
    _a, ra = executed(client, scenarios.template_object_id("CORP-01"))
    _b, rb = executed(client, scenarios.template_object_id("CORP-12"),
                      session="s2")
    cmp_ = client.post(f"{P}/whatif/compare", json={
        "result_ids": [ra["object_id"], rb["object_id"]]}).json()
    send(client, cmp_["object_id"])
    as_(who, RECIPIENT)
    msg = received(client, cmp_["object_id"])
    d = client.get(f"{P}/messages/{msg['share_id']}").json()
    assert d["accessible"]
    # The compared results travelled with it (identity only).
    for rid in (ra["object_id"], rb["object_id"]):
        assert client.get(f"{P}/objects/{rid}").status_code == 200


def test_incompatible_results_are_not_compared(client, svc, who):
    scenarios.ensure_seeded(svc, SENDER)
    _a, corp = executed(client, scenarios.template_object_id("CORP-01"))
    _b, ret = executed(client, scenarios.template_object_id("RET-01"),
                       session="r")
    r = client.post(f"{P}/whatif/compare", json={
        "result_ids": [corp["object_id"], ret["object_id"]]})
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "INCOMPATIBLE"


# ---- comments, versions, permissions ------------------------------------------

def test_comments_attach_to_the_shared_version_and_both_sides_see_them(
        client, svc, who):
    scn = own_scenario(client)
    send(client, scn["object_id"])
    as_(who, RECIPIENT)
    msg = received(client, scn["object_id"])
    c = client.post(f"{P}/messages/{msg['share_id']}/comments",
                    json={"body": "PD x1.20 looks light for Construction"}
                    ).json()
    assert c["version"] == msg["version"]
    as_(who, SENDER)
    sent = client.get(f"{P}/messages", params={"box": "sent"}).json()["items"]
    mine = next(i for i in sent if i["object_id"] == scn["object_id"])
    d = client.get(f"{P}/messages/{mine['share_id']}").json()
    assert any(x["body"].startswith("PD x1.20") for x in d["comments"])


def test_a_pinned_share_stays_openable_after_the_object_moves_on(client, svc,
                                                                  who):
    scn = own_scenario(client)
    v1 = scn["version"]
    r = client.post(f"{P}/messages", json={"object_id": scn["object_id"],
                                           "to": ["colleague"],
                                           "version": v1})
    assert r.status_code == 201
    client.post(f"{P}/scenarios/{scn['object_id']}/revise",
                json={"changes": {"name": "renamed later"},
                      "reason": "rename"})
    as_(who, RECIPIENT)
    msg = received(client, scn["object_id"])
    d = client.get(f"{P}/messages/{msg['share_id']}").json()
    assert d["accessible"] and d["object"]["version"] == v1
    assert d["latest_version"] > v1


def test_a_message_never_grants_access_beyond_the_recipient(client, svc, who):
    scn = own_scenario(client)
    shared = send(client, scn["object_id"])
    share_id = shared["shared"][0]["share_id"]
    as_(who, BYSTANDER)
    assert client.get(f"{P}/messages/{share_id}").status_code == 404
    assert client.get(f"{P}/objects/{scn['object_id']}").status_code == 404
    assert client.post(f"{P}/messages/{share_id}/run",
                       json={}).status_code == 404
    as_(who, STRANGER)
    assert client.get(f"{P}/messages/{share_id}").status_code == 404
    assert client.get(f"{P}/objects/{scn['object_id']}").status_code == 404
    # The recipient cannot widen access by re-sharing a private object.
    as_(who, RECIPIENT)
    r = client.post(f"{P}/messages", json={"object_id": scn["object_id"],
                                           "to": ["bystander"]})
    assert r.status_code == 403
    # Only the recipient acts on a message; the sender opens, not runs.
    as_(who, SENDER)
    assert client.post(f"{P}/messages/{share_id}/run",
                       json={}).status_code == 403


def test_a_shared_cohort_can_be_investigated_without_rebuilding_it(
        client, svc, who, store_db):
    made = cohorts.freeze(access.book(SENDER, "corporate"), svc,
                          service.principal(SENDER), name="Construction",
                          filters=CONSTRUCTION)
    send(client, made["object_id"])
    as_(who, RECIPIENT)
    msg = received(client, made["object_id"])
    assert msg["card"]["membership_hash"] == made["body"]["membership_hash"]
    out = client.post(f"{P}/messages/{msg['share_id']}/investigate").json()
    seed = store_db.thread_context(out["thread_id"], tenant_id="demo-tenant")
    assert seed is not None


# ---- the scenario tree -----------------------------------------------------------

def test_the_session_tree_shows_baseline_layered_and_method_variants(
        client, svc, who):
    scenarios.ensure_seeded(svc, SENDER)
    tid = scenarios.template_object_id
    a, _ = executed(client, tid("CORP-01"), session="t")
    b, _ = executed(client, tid("CORP-06"), session="t",
                    baseline={"mode": "SOURCE_BASELINE"})
    a1, _ = executed(client, tid("CORP-06"), session="t",
                     baseline={"mode": "PRIOR_SCENARIO",
                               "parent_run_id": a["object_id"]})
    variant = client.post(f"{P}/whatif/runs/{a['object_id']}/rerun").json()
    # A variant stays a variant after its method is chosen and it runs (each
    # transition is a revision; found by the GW-P7-03 browser journey).
    client.post(f"{P}/whatif/runs/{variant['object_id']}/method",
                json={"methods": ["user_defined"],
                      "user_assumption": {"form": "relative", "value": "12"}})
    assert client.post(f"{P}/whatif/runs/{variant['object_id']}/execute"
                       ).status_code == 200
    tree = client.get(f"{P}/whatif/tree", params={"session_id": "t"}).json()
    edges = {(e["from"], e["to"], e["kind"]) for e in tree["edges"]}
    assert ("baseline", a["object_id"], "baseline") in edges
    assert ("baseline", b["object_id"], "baseline") in edges
    assert (a["object_id"], a1["object_id"], "layered") in edges
    assert (a["object_id"], variant["object_id"], "method_variant") in edges
    node = next(n for n in tree["nodes"] if n["id"] == a["object_id"])
    assert node["methods_ran"] == ["delta"] and "delta" in node["results"]
    assert D(node["results"]["delta"]["change"]) > 0


def test_a_result_of_a_private_scenario_carries_what_a_rerun_needs(
        client, svc, who):
    scn = own_scenario(client)
    _run, result = executed(client, scn["object_id"])
    shared = send(client, result["object_id"])
    attached = {a["object_id"] for a in shared["object"]["attachments"]}
    assert scn["object_id"] in attached
    as_(who, RECIPIENT)
    msg = received(client, result["object_id"])
    r = client.post(f"{P}/messages/{msg['share_id']}/run",
                    json={"latest": True})
    assert r.status_code == 201, r.text
    assert r.json()["body"]["scenario_id"] == scn["object_id"]
