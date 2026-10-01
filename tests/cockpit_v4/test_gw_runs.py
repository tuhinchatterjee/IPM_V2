"""P6 — What-If runs: scenario and method are separate decisions; results
carry the universal dual-scope decomposition; lineage is asked, never assumed.

EVIDENCE LABEL: NO MODEL. No model call. The workspace HTTP routes on the candidate
books, executing through the engine's own `bridge.compute_core` -- the same
object the Cockpit's `execute_scenario` uses.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.cockpit_v4 import lake, routes
from backend.cockpit_v4.scenario import cohort_refs
from backend.cockpit_v4.scenario import decomposition as dc
from backend.workspace import access, cohorts, runs, scenarios, service
from backend.workspace import api as workspace_api
from backend.workspace.store import WorkspaceStore
from tests.cockpit_v4.test_gw_method_gate import UAT
from tests.cockpit_v4.test_gw_method_gate import execute as cockpit_execute
from tests.cockpit_v4.test_gw_method_gate import preview as cockpit_preview

P = "/api/v1/cockpit-v4/workspace"
CANDIDATE = {"corporate": "v4-whatif-corporate-20q-s1",
             "retail": "v4-whatif-retail-20m-s1"}
WHO = {"id": "banker", "tenant": "demo-tenant", "roles": ("analyst",)}
COLLEAGUE = {"id": "colleague", "tenant": "demo-tenant", "roles": ("analyst",)}
CONSTRUCTION = [{"column": "sector", "op": "in", "values": ["Construction"]}]


@pytest.fixture
def svc(tmp_path, monkeypatch):
    for release in CANDIDATE.values():
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
    return dict(WHO)


@pytest.fixture
def client(store_db, runtime, svc, who):
    app = FastAPI()
    routes.install(store=store_db, runtime=runtime, cfg=runtime.cfg,
                   principal_resolver=lambda r: who, startup_sha="t")
    app.include_router(routes.router)
    app.include_router(workspace_api.router)
    return TestClient(app)


def D(x):
    return Decimal(str(x))


def uat_scenario(svc):
    """The live-UAT scenario as a workspace object, bound to the governed
    Construction cohort: PD x1.20, LGD x1.10, stages fixed."""
    principal = service.principal(WHO)
    book = access.book(WHO, "corporate")
    cohort = cohorts.freeze(book, svc, principal, name="Construction",
                            filters=CONSTRUCTION)
    obj = scenarios.create(svc, WHO, {
        "name": "UAT Construction PD x1.20 LGD x1.10",
        "domain_id": "corporate", "description": "live UAT reproduction",
        "risk_thesis": "UAT-01",
        "scope": {"type": "whole_book", "label": "Whole active book"},
        "components": [
            {"kind": "parameter", "field": "pd_pit_12m",
             "operation": "multiply", "value": "1.20", "label": "PD x1.20"},
            {"kind": "parameter", "field": "lgd_pct",
             "operation": "multiply", "value": "1.10", "label": "LGD x1.10"}],
        "stage_policy": "frozen", "severity": "moderate", "tags": ["uat"]})
    return obj, cohort


def start(client, scenario_id, **kw):
    r = client.post(f"{P}/whatif/runs", json={"scenario_id": scenario_id,
                                              **kw})
    assert r.status_code == 201, r.text
    return r.json()


def confirm(client, run):
    r = client.post(f"{P}/whatif/runs/{run['object_id']}/confirm",
                    json={"digest": run["body"]["contract"]["digest"]})
    assert r.status_code == 200, r.text
    return r.json()


def method(client, run, methods, assumption=None):
    r = client.post(f"{P}/whatif/runs/{run['object_id']}/method",
                    json={"methods": methods,
                          "user_assumption": assumption})
    assert r.status_code == 200, r.text
    return r.json()


def execute(client, run):
    return client.post(f"{P}/whatif/runs/{run['object_id']}/execute")


def results(svc):
    return svc.store.latest_of_kind("scenario_result", tenant_id="demo-tenant")


def full_run(client, scenario_id, methods=("delta",), **kw):
    run = start(client, scenario_id, **kw)
    if run["status"] != runs.SCENARIO_PREVIEW:
        return run, None
    run = method(client, confirm(client, run), list(methods))
    out = execute(client, run)
    assert out.status_code == 200, out.text
    return out.json()["run"], out.json()["result"]


# ---- UAT-01 through the workspace ------------------------------------------------

def test_uat01_workspace_confirmed_with_no_method_stops_at_method_selection(
        client, svc):
    obj, cohort = uat_scenario(svc)
    run = start(client, obj["object_id"], cohort_id=cohort["object_id"],
                session_id="s-uat")
    assert run["status"] == runs.SCENARIO_PREVIEW
    pv = run["body"]["preview"]
    assert (pv["entities"], pv["owners"]) == (248, 100)
    assert pv["stage_policy"] == "frozen"
    assert run["body"]["methods_chosen"] == []
    confirmed = confirm(client, run)
    assert confirmed["status"] == runs.METHOD_SELECTION
    states = [s["state"] for s in confirmed["body"]["state_log"]]
    assert states == [runs.SCENARIO_PREVIEW, runs.SCENARIO_CONFIRMED,
                      runs.METHOD_SELECTION]
    assert confirmed["body"]["result_id"] == ""
    refused = execute(client, confirmed)
    assert refused.status_code == 409
    assert refused.json()["detail"]["error_code"] == \
        "METHOD_SELECTION_REQUIRED"
    assert results(svc) == [], "nothing was executed"
    # Reopening does not execute either.
    again = client.get(f"{P}/whatif/runs/{run['object_id']}").json()
    assert again["status"] == runs.METHOD_SELECTION
    offered = set(again["body"]["availability"])
    assert offered == {"delta", "ml", "user_defined", "compare"}


def test_an_empty_method_choice_stays_at_method_selection(client, svc):
    obj, cohort = uat_scenario(svc)
    run = confirm(client, start(client, obj["object_id"],
                                cohort_id=cohort["object_id"]))
    assert method(client, run, [])["status"] == runs.METHOD_SELECTION
    assert results(svc) == []


def test_choosing_delta_runs_delta_only_and_matches_the_cockpit_entrance(
        client, svc):
    obj, cohort = uat_scenario(svc)
    run, result = full_run(client, obj["object_id"],
                           cohort_id=cohort["object_id"])
    assert run["status"] == runs.EXECUTED
    body = result["body"]
    assert body["methods"]["ran"] == ["delta"]
    assert set(body["decomposition"]) == {"delta"}
    # The same scenario through the Cockpit's execute_scenario: one engine,
    # one number.
    store, _made, digest = cockpit_preview(params={**UAT})
    cockpit = cockpit_execute("corporate", store, digest, methods=["delta"])
    cockpit_change = cockpit.provenance["whatif_decomposition"]["delta"][
        "scopes"]["selected"]["change"]
    assert abs(D(body["results"]["delta"]["change"]) - D(cockpit_change)) \
        <= D("0.000001")
    assert body["cohort"]["membership_hash"] == \
        cockpit.provenance["whatif_membership_hash"]


def test_the_result_decomposition_is_dual_scope_and_reconciles(client, svc):
    obj, cohort = uat_scenario(svc)
    _run, result = full_run(client, obj["object_id"],
                            cohort_id=cohort["object_id"])
    d = result["body"]["decomposition"]["delta"]
    dc.check(d)
    sel, tot = d["scopes"]["selected"], d["scopes"]["total"]
    for s in (sel, tot):
        assert [c["id"] for c in s["components"]] == list(dc.ORDER)
        moved = sum(D(c["value"]) for c in s["components"]
                    if c["kind"] != "total" and c["value"])
        assert abs(D(s["opening"]) + moved - D(s["closing"])) <= D("1e-6")
    rest = D(d["cross_scope"]["rest_of_book_delta"])
    assert abs(D(sel["change"]) + rest - D(tot["change"])) <= D("1e-6")
    by = {c["id"]: c for c in sel["components"]}
    assert D(by["pd"]["value"]) > 0 and D(by["lgd"]["value"]) > 0
    assert by["new_originations"]["status"] == "N/A"
    assert result["body"]["stages"] and result["body"]["top_contributors"]
    # Stages frozen: every stage's before/after reconciles to the cohort.
    moved = sum(D(s["change"]) for s in result["body"]["stages"])
    assert abs(moved - D(sel["change"])) <= D("1e-6")


def test_retail_ml_is_visibly_unavailable_and_never_substituted(client, svc):
    scenarios.ensure_seeded(svc, WHO)
    tpl = scenarios.template_object_id("RET-01")
    run = confirm(client, start(client, tpl))
    ml = run["body"]["availability"]["ml"]
    assert ml["status"] == "UNAVAILABLE" and "G4" in ml["reason"]
    gated = method(client, run, ["ml"])
    assert gated["status"] == runs.METHOD_UNAVAILABLE
    assert execute(client, gated).status_code == 409
    assert results(svc) == []
    ran = method(client, gated, ["delta"])
    assert ran["status"] == runs.READY_TO_EXECUTE
    out = execute(client, ran).json()
    assert out["result"]["body"]["methods"]["ran"] == ["delta"]


def test_compare_on_retail_runs_the_available_and_names_ml_unavailable(
        client, svc):
    scenarios.ensure_seeded(svc, WHO)
    tpl = scenarios.template_object_id("RET-01")
    run = method(client, confirm(client, start(client, tpl)),
                 ["delta", "ml"])
    out = execute(client, run).json()["result"]["body"]
    assert out["methods"]["ran"] == ["delta"]
    assert "G4" in out["methods"]["unavailable"]["ml"]


def test_user_defined_asks_for_its_input_then_runs(client, svc):
    obj, cohort = uat_scenario(svc)
    run = confirm(client, start(client, obj["object_id"],
                                cohort_id=cohort["object_id"]))
    asked = method(client, run, ["user_defined"])
    assert asked["status"] == runs.METHOD_INPUT_REQUIRED
    assert execute(client, asked).status_code == 409
    ready = method(client, asked, ["user_defined"],
                   {"form": "relative", "value": "15",
                    "stated_as": "ECL rises 15%"})
    assert ready["status"] == runs.READY_TO_EXECUTE
    body = execute(client, ready).json()["result"]["body"]
    assert body["methods"]["ran"] == ["user_defined"]
    d = body["decomposition"]["user_defined"]["scopes"]["selected"]
    overlay = next(c for c in d["components"]
                   if c["id"] == "management_overlay")
    assert abs(D(overlay["value"]) - D(d["opening"]) * D("0.15")) < D("0.01")


def test_a_component_without_governed_translation_blocks_delta_by_name(
        client, svc):
    scenarios.ensure_seeded(svc, WHO)
    run = confirm(client, start(client,
                                scenarios.template_object_id("RET-05")))
    delta = run["body"]["availability"]["delta"]
    assert delta["status"] == "BLOCKED" and "Delinquency" in delta["reason"]
    assert method(client, run, ["delta"])["status"] == \
        runs.METHOD_UNAVAILABLE


def test_the_collateral_sign_warning_survives_into_the_result(client, svc):
    scenarios.ensure_seeded(svc, WHO)
    _run, result = full_run(client, scenarios.template_object_id("RET-07"))
    assert any("SIGN_REVIEW" in n for n in result["body"]["notes"])
    comp = {c["id"]: c for c in result["body"]["decomposition"]["delta"][
        "scopes"]["selected"]["components"]}
    assert D(comp["collateral"]["value"]) < 0


def test_ccf_runs_on_the_derived_conversion_factor(client, svc):
    """Defect found in P6 (present since the engine landed): Corporate CCF
    is DERIVED, the cohort read never supplied it, and every CCF shock
    raised KeyError('ccf')."""
    scenarios.ensure_seeded(svc, WHO)
    _run, result = full_run(client, scenarios.template_object_id("CORP-10"))
    comp = {c["id"]: c for c in result["body"]["decomposition"]["delta"][
        "scopes"]["selected"]["components"]}
    assert D(comp["ccf_ead"]["value"]) > 0


# ---- lineage: asked, never assumed ------------------------------------------------

def test_a_second_run_in_a_session_asks_for_the_baseline(client, svc):
    scenarios.ensure_seeded(svc, WHO)
    a, _ = full_run(client, scenarios.template_object_id("CORP-01"),
                    session_id="s1")
    second = start(client, scenarios.template_object_id("CORP-05"),
                   session_id="s1")
    assert second["status"] == runs.WAITING_BASELINE_CHOICE
    options = second["body"]["question"]["options"]
    assert options[0]["mode"] == "SOURCE_BASELINE"
    assert options[1]["parent_run_id"] == a["object_id"]
    assert execute(client, second).status_code == 409
    # Another session has nothing executed: no question.
    other = start(client, scenarios.template_object_id("CORP-05"),
                  session_id="s2")
    assert other["status"] == runs.SCENARIO_PREVIEW


def test_original_baseline_choice_runs_on_the_booked_book(client, svc):
    scenarios.ensure_seeded(svc, WHO)
    full_run(client, scenarios.template_object_id("CORP-01"), session_id="s1")
    second = start(client, scenarios.template_object_id("CORP-05"),
                   session_id="s1")
    chosen = client.post(f"{P}/whatif/runs/{second['object_id']}/baseline",
                         json={"baseline": {"mode": "SOURCE_BASELINE"}}
                         ).json()
    assert chosen["status"] == runs.SCENARIO_PREVIEW
    assert chosen["body"]["baseline"] == {"mode": "SOURCE_BASELINE"}
    assert chosen["body"]["chain"] == []


def test_branches_a_b_ab_abc_persist_their_lineage(client, svc):
    scenarios.ensure_seeded(svc, WHO)
    tid = scenarios.template_object_id
    a, ra = full_run(client, tid("CORP-01"), session_id="s1")
    b, rb = full_run(client, tid("CORP-06"), session_id="s1",
                     baseline={"mode": "SOURCE_BASELINE"})
    ab, rab = full_run(client, tid("CORP-06"), session_id="s1",
                       baseline={"mode": "PRIOR_SCENARIO",
                                 "parent_run_id": a["object_id"]})
    abc, rabc = full_run(client, tid("CORP-05"), session_id="s1",
                         baseline={"mode": "PRIOR_SCENARIO",
                                   "parent_run_id": ab["object_id"]})
    assert b["body"]["baseline"] == {"mode": "SOURCE_BASELINE"}
    assert ab["body"]["baseline"]["parent_run_id"] == a["object_id"]
    assert [c["executed_run_id"] for c in abc["body"]["chain"]] == \
        [a["object_id"], ab["object_id"]]
    # The layered book starts where its ancestors left it.
    book0 = D(ra["body"]["book"]["baseline"])
    assert abs(D(rab["body"]["book"]["baseline"])
               - (book0 + D(ra["body"]["results"]["delta"]["change"]))) \
        <= D("1e-6")
    assert abs(D(rabc["body"]["book"]["baseline"])
               - (book0 + D(ra["body"]["results"]["delta"]["change"])
                  + D(rab["body"]["results"]["delta"]["change"]))) \
        <= D("1e-6")
    # Layering changes the number: B on A differs from B alone.
    assert rab["body"]["results"]["delta"]["change"] != \
        rb["body"]["results"]["delta"]["change"]
    for r in (ra, rb, rab, rabc):
        dc.check(r["body"]["decomposition"]["delta"])
    # Every contract records its baseline; the digests differ.
    assert ab["body"]["contract"]["confirmed_digest"] != \
        b["body"]["contract"]["confirmed_digest"]


def test_layering_on_a_run_without_delta_is_refused(client, svc):
    obj, cohort = uat_scenario(svc)
    run = confirm(client, start(client, obj["object_id"],
                                cohort_id=cohort["object_id"],
                                session_id="s1"))
    run = method(client, run, ["user_defined"],
                 {"form": "relative", "value": "5"})
    parent = execute(client, run).json()["run"]
    r = client.post(f"{P}/whatif/runs", json={
        "scenario_id": obj["object_id"], "cohort_id": cohort["object_id"],
        "session_id": "s1",
        "baseline": {"mode": "PRIOR_SCENARIO",
                     "parent_run_id": parent["object_id"]}})
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "PARENT_HAS_NO_ROW_STATE"


# ---- one contract, many methods ----------------------------------------------------

def test_rerun_with_another_method_reuses_the_confirmed_contract(client, svc):
    obj, cohort = uat_scenario(svc)
    first, _ = full_run(client, obj["object_id"],
                        cohort_id=cohort["object_id"])
    again = client.post(f"{P}/whatif/runs/{first['object_id']}/rerun")
    assert again.status_code == 201
    again = again.json()
    assert again["status"] == runs.METHOD_SELECTION
    assert again["body"]["contract"]["confirmed_digest"] == \
        first["body"]["contract"]["confirmed_digest"]
    ran = method(client, again, ["user_defined"],
                 {"form": "absolute", "value": "10"})
    out = execute(client, ran).json()["result"]["body"]
    assert out["contract_digest"] == \
        first["body"]["contract"]["confirmed_digest"]


def test_a_stale_confirmation_is_refused(client, svc):
    obj, cohort = uat_scenario(svc)
    run = start(client, obj["object_id"], cohort_id=cohort["object_id"])
    r = client.post(f"{P}/whatif/runs/{run['object_id']}/confirm",
                    json={"digest": "0" * 64})
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "CONFIRMATION_STALE"


def test_only_the_owner_advances_a_run(client, svc, who):
    obj, cohort = uat_scenario(svc)
    run = start(client, obj["object_id"], cohort_id=cohort["object_id"])
    who.update(COLLEAGUE)
    r = client.post(f"{P}/whatif/runs/{run['object_id']}/confirm",
                    json={"digest": run["body"]["contract"]["digest"]})
    assert r.status_code in (403, 404)


def test_session_listing_shows_state_and_result(client, svc):
    scenarios.ensure_seeded(svc, WHO)
    full_run(client, scenarios.template_object_id("CORP-01"), session_id="sx")
    listed = client.get(f"{P}/whatif/runs",
                        params={"session_id": "sx"}).json()["runs"]
    assert len(listed) == 1 and listed[0]["state"] == runs.EXECUTED
    assert listed[0]["result_id"].startswith("res-")


# ---- the Cockpit entrance ----------------------------------------------------------

def test_a_cockpit_execution_opens_as_the_same_governed_result(client, svc,
                                                               store_db):
    """UAT reproduction in the conversation, then Delta chosen: the thread's
    own published result opens as a Scenario Result -- no recomputation --
    with the same dual-scope decomposition contract a What-If run has."""
    store, _made, digest = cockpit_preview(params={**UAT})
    gated = cockpit_execute("corporate", store, digest)
    assert gated.provenance["whatif_executed"] is False
    thread_id = store_db.create_thread(
        tenant_id="demo-tenant", principal_id="banker", domain_id="corporate",
        release_id=CANDIDATE["corporate"], release_fingerprint="")
    store_db.set_thread_context(thread_id, tenant_id="demo-tenant",
                                kind=store.context["kind"],
                                body=store.context["body"])
    seen = client.get(f"{P}/whatif/threads/{thread_id}/cohort").json()
    assert seen["method_state"] == "METHOD_SELECTION_REQUIRED"
    assert seen["has_result"] is False
    refused = client.post(f"{P}/whatif/threads/{thread_id}/adopt-result")
    assert refused.status_code == 409
    ran = cockpit_execute("corporate", store, digest, run_id="run-3",
                          methods=["delta"])
    store_db.set_thread_context(thread_id, tenant_id="demo-tenant",
                                kind=store.context["kind"],
                                body=store.context["body"])
    adopted = client.post(f"{P}/whatif/threads/{thread_id}/adopt-result")
    assert adopted.status_code == 201, adopted.text
    body = adopted.json()["body"]
    assert body["entry"] == "cockpit" and body["methods"]["ran"] == ["delta"]
    assert body["decomposition"] == ran.provenance["whatif_decomposition"]
    dc.check(body["decomposition"]["delta"])
    again = client.post(f"{P}/whatif/threads/{thread_id}/adopt-result").json()
    assert again["object_id"] == adopted.json()["object_id"], "idempotent"


def test_pareto_and_distribution_reconcile_to_the_selected_change(client,
                                                                   svc):
    """VIZ10 / VIZ11 data: the Pareto sums to the selected-scope Delta
    change and ends at 100%; the distribution counts every exposure once."""
    scenarios.ensure_seeded(svc, WHO)
    _run, result = full_run(client, scenarios.template_object_id("CORP-18"))
    b = result["body"]
    sel = D(b["decomposition"]["delta"]["scopes"]["selected"]["change"])
    assert abs(sum(D(p["change"]) for p in b["pareto"]) - sel) <= D("1e-6")
    assert D(b["pareto"][-1]["cumulative_share"]) == D("1.0000")
    assert sum(x["n"] for x in b["change_distribution"]) == \
        b["cohort"]["entity_count"]


def test_meth05_results_carry_the_governed_method_names(client, svc):
    """METH05 / UAT-08: a Delta result is labelled "Method 1 — Delta", and
    the run's own log says which method was chosen by that name."""
    obj, cohort = uat_scenario(svc)
    run, result = full_run(client, obj["object_id"],
                           cohort_id=cohort["object_id"], session_id="s-m5")
    assert result["body"]["results"]["delta"]["label"] == "Method 1 — Delta"
    assert any(e.get("reason") == "method chosen: Method 1 — Delta"
               for e in run["body"]["state_log"])
    assert runs.LABELS == {"delta": "Method 1 — Delta",
                           "ml": "Method 2 — ML emulator",
                           "user_defined": "Method 3 — User-defined",
                           "compare": "Compare methods"}


def test_arch02_cockpit_and_whatif_build_the_identical_contract(client, svc):
    """ARCH-02: the same input -- UAT-01 (Construction, PD x1.20, LGD x1.10,
    stages fixed) -- previewed in a Cockpit conversation and started in the
    dedicated What-If workspace yields ONE contract: identical digest over
    everything that can change a number (source, cohort hash, shocks,
    policies, warnings), identity fields aside."""
    from backend.cockpit_v4.scenario import spec as sp_mod
    _store, made, cockpit_digest = cockpit_preview()
    obj, cohort = uat_scenario(svc)
    run = start(client, obj["object_id"], cohort_id=cohort["object_id"],
                session_id="s-arch02")
    contract = run["body"]["contract"]
    assert contract["digest"] == cockpit_digest
    canon = made.provenance.get("whatif_canonical") or {}
    if canon:
        assert canon["cohort"]["membership_hash"] == \
            cohort["body"]["membership_hash"]
    assert sp_mod  # the digest is ScenarioSpec.digest() on both paths


def test_decomp14_a_single_customer_scenario_decomposes_customer_then_book(
        client, svc):
    """DECOMP14: one borrower's facilities as the selected scope; the result
    shows the customer-level decomposition first and the total active book
    second, each reconciling, the customer's change inside the book's."""
    book = access.book(WHO, "corporate")
    borrower = book.rows(
        "SELECT borrower_id, COUNT(*) AS n FROM corp_facility_quarter WHERE "
        "reporting_quarter = ? AND sector = 'Construction' GROUP BY 1 "
        "HAVING COUNT(*) >= 2 ORDER BY 1 LIMIT 1",
        [book.latest_period])[0]
    one = cohorts.freeze(book, svc, service.principal(WHO),
                         name=f"Borrower {borrower['borrower_id']}",
                         filters=[{"column": "borrower_id", "op": "eq",
                                   "value": borrower["borrower_id"]}])
    assert one["body"]["counts"]["owners"] == 1
    obj, _ = uat_scenario(svc)
    run, result = full_run(client, obj["object_id"],
                           cohort_id=one["object_id"], session_id="s-d14")
    assert result is not None, run["status"]
    d = result["body"]["decomposition"]["delta"]
    assert list(d["scopes"]) == ["selected", "total"]
    sel, tot = d["scopes"]["selected"], d["scopes"]["total"]
    assert sel["kpis"]["exposures"] == borrower["n"]
    assert tot["kpis"]["exposures"] == 2996
    assert sel["reconciles"] and tot["reconciles"]
    assert d["cross_scope"]["reconciles"]
    assert D(sel["change"]) == D(d["cross_scope"]["selected_delta"])
    assert D(tot["change"]) == D(d["cross_scope"]["total_delta"])
    assert D(d["cross_scope"]["rest_of_book_delta"]) == 0
    assert not d["cross_scope"].get("selected_equals_total")


def test_scen12_a_stage_retest_policy_persists_into_execution(client, svc):
    """SCEN12 / DECOMP07 / DECOMP11: CORP-08 asks for a SICR re-test. The
    request survives preview, confirmation and execution; the stage
    components are listed separately and marked not applicable with the
    re-test reason (this book publishes no lifetime ECL curve for re-staged
    exposures), so no migrating ECL is invented and the bridge reconciles."""
    from backend.cockpit_v4.scenario import decomposition as dc
    scenarios.ensure_seeded(svc, WHO)
    sid = scenarios.template_object_id("CORP-08")
    assert svc.get(sid, service.principal(WHO))["body"]["stage_policy"] == \
        "retest_sicr"
    run = start(client, sid, session_id="s-scen12")
    assert run["body"]["preview"]["stage_policy_requested"] == "retest_sicr"
    assert run["body"]["preview"]["stage_policy"] == "explicit"
    run, result = full_run(client, sid, session_id="s-scen12b")
    assert result is not None, run["status"]
    b = result["body"]
    assert b["stage_policy_requested"] == "retest_sicr"
    d = b["decomposition"]["delta"]
    for scope in d["scopes"].values():
        comps = {c["id"]: c for c in scope["components"]}
        stage_ids = [c.id for c in dc.TAXONOMY if c.id.startswith("stage_")]
        assert stage_ids
        for cid in stage_ids:
            assert comps[cid]["status"] == "N/A", cid
            assert "re-test was requested" in comps[cid]["reason"], cid
        assert scope["reconciles"]
    # Frozen is a different, stated reason.
    obj, cohort = uat_scenario(svc)
    _r, frozen = full_run(client, obj["object_id"],
                          cohort_id=cohort["object_id"], session_id="s-fz")
    fz = {c["id"]: c for c in frozen["body"]["decomposition"]["delta"]
          ["scopes"]["selected"]["components"]}
    assert "frozen" in fz[stage_ids[0]]["reason"]


def _assert_scope_equals_book(d):
    assert d["selected_equals_total"] is True
    assert d["cross_scope"]["scope_equivalence"] == "Selected scope = Total book"
    assert "no rest of book" in d["cross_scope"]["rest_of_book_reason"]
    assert D(d["cross_scope"]["rest_of_book_delta"]) == 0
    assert D(d["cross_scope"]["selected_delta"]) == \
        D(d["cross_scope"]["total_delta"])
    sel, tot = d["scopes"]["selected"], d["scopes"]["total"]
    for k in ("opening", "closing", "change"):
        assert sel[k] == tot[k], k
    by_id = {c["id"]: c for c in tot["components"]}
    assert len(sel["components"]) == len(tot["components"]) >= 20
    for c in sel["components"]:
        assert (c["value"], c["status"]) == (by_id[c["id"]]["value"],
                                            by_id[c["id"]]["status"]), c["id"]


@pytest.mark.parametrize("how", ["whole_book", "filter_selecting_all"])
def test_decomp21_selected_scope_equal_to_the_book_is_one_population(
        client, svc, how):
    """DECOMP21: when the selected population IS the whole book -- with no
    filter, or with a filter that happens to select every exposure -- the
    result says so, the rest-of-book delta is zero, and the two scopes are
    identical component by component (the page then draws one bridge)."""
    obj, _cohort = uat_scenario(svc)
    kw = {}
    if how == "filter_selecting_all":
        every = cohorts.freeze(
            access.book(WHO, "corporate"), svc, service.principal(WHO),
            name="Every stage", filters=[{"column": "stage", "op": "in",
                                          "values": [1, 2, 3]}])
        assert every["body"]["counts"]["entities"] == 2996
        kw["cohort_id"] = every["object_id"]
    run, result = full_run(client, obj["object_id"], session_id=f"s-{how}",
                           **kw)
    assert result is not None, run["status"]
    _assert_scope_equals_book(result["body"]["decomposition"]["delta"])


def test_decomp21_a_true_subset_is_never_called_the_whole_book(client, svc):
    obj, cohort = uat_scenario(svc)
    _r, result = full_run(client, obj["object_id"],
                          cohort_id=cohort["object_id"], session_id="s-sub")
    d = result["body"]["decomposition"]["delta"]
    assert d["selected_equals_total"] is False
    assert "scope_equivalence" not in d["cross_scope"]


def test_decomp24_method_comparison_keeps_a_dual_scope_bridge_per_method(
        client, svc):
    """DECOMP24: Delta and User-defined on ONE confirmed contract: each
    method has its own selected-scope and total-book decomposition, on the
    same cohort and the same booked baseline; nothing is re-cohorted."""
    obj, cohort = uat_scenario(svc)
    run = confirm(client, start(client, obj["object_id"],
                                cohort_id=cohort["object_id"],
                                session_id="s-d24"))
    ready = method(client, run, ["delta", "user_defined"],
                   {"form": "relative", "value": "10",
                    "stated_as": "ECL rises 10%"})
    assert ready["status"] == runs.READY_TO_EXECUTE
    body = execute(client, ready).json()["result"]["body"]
    assert sorted(body["methods"]["ran"]) == ["delta", "user_defined"]
    decs = body["decomposition"]
    assert set(decs) == {"delta", "user_defined"}
    openings = {(m, s): d["scopes"][s]["opening"]
                for m, d in decs.items() for s in ("selected", "total")}
    assert openings[("delta", "selected")] == \
        openings[("user_defined", "selected")]
    assert openings[("delta", "total")] == openings[("user_defined", "total")]
    for d in decs.values():
        assert list(d["scopes"]) == ["selected", "total"]
        assert d["scopes"]["selected"]["kpis"]["exposures"] == 248
        assert d["cross_scope"]["reconciles"]
        assert d["scopes"]["selected"]["label"] == \
            decs["delta"]["scopes"]["selected"]["label"]


def test_base05_an_assumption_before_execution_amends_the_same_run(
        client, svc):
    """BASE05: supplying the missing assumption before execution is a new
    VERSION of the same run (same id, same confirmed contract), never a
    child scenario or a new run."""
    obj, cohort = uat_scenario(svc)
    run = confirm(client, start(client, obj["object_id"],
                                cohort_id=cohort["object_id"],
                                session_id="s-b05"))
    asked = method(client, run, ["user_defined"])
    ready = method(client, asked, ["user_defined"],
                   {"form": "relative", "value": "5", "stated_as": "+5%"})
    assert ready["object_id"] == asked["object_id"] == run["object_id"]
    assert ready["version"] > asked["version"] > run["version"] - 1
    assert ready["body"]["contract"]["confirmed_digest"] == \
        run["body"]["contract"]["confirmed_digest"]
    assert ready["body"]["scenario_id"] == obj["object_id"]
    assert ready["body"]["scenario_version"] == obj["version"]
    # The scenario object itself is untouched: no child was derived.
    assert svc.get(obj["object_id"], service.principal(WHO))["version"] == \
        obj["version"]
    kids = [c for c in svc.store.children_of(obj["object_id"],
                                             tenant_id="demo-tenant")
            if c["kind"] == "scenario"]
    assert kids == []


@pytest.mark.parametrize("template,component", [("CORP-07", "rating_score"),
                                                ("CORP-05", "macro")])
def test_decomp08_rating_and_macro_contributions_are_measured(client, svc,
                                                              template,
                                                              component):
    """DECOMP08: a rating-notch scenario measures the rating/score bar; a
    macro scenario measures the macro bar -- server-side, in the published
    decomposition, reconciling."""
    scenarios.ensure_seeded(svc, WHO)
    run, result = full_run(client, scenarios.template_object_id(template),
                           session_id=f"s-d08-{template}")
    assert result is not None, run["status"]
    sel = result["body"]["decomposition"]["delta"]["scopes"]["selected"]
    comp = {c["id"]: c for c in sel["components"]}[component]
    assert comp["status"] == "MEASURED", comp
    assert D(comp["value"]) != 0
    assert sel["reconciles"]
