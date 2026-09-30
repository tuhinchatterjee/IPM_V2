"""P6 — universal dual-scope ECL decomposition and scenario lineage.

EVIDENCE LABEL: no model call. The engine's `execute_scenario` on the
candidate books; decompositions are read from the published result, and the
identities are re-verified from the published strings.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import bridge as br
from backend.cockpit_v4.scenario import decomposition as dc
from backend.cockpit_v4.scenario import thread as th
from backend.cockpit_v4.scenario.errors import ScenarioError
from tests.cockpit_v4.test_whatif_bridge import Store, book_of, run_bridge

CANDIDATE = ("v4-whatif-corporate-20q-s1", "v4-whatif-retail-20m-s1")


@pytest.fixture(autouse=True)
def candidate_books(monkeypatch):
    for release in CANDIDATE:
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    arun.reset()
    yield
    arun.reset()


def construction(**over):
    base = {"operation": br.PREVIEW,
            "cohort": {"filters": [{"column": "sector", "operator": "=",
                                    "value": "Construction"}]},
            "shocks": [{"field": "pd_pit_12m", "operation": "multiply",
                        "value": "1.20", "origin": "PD x1.20"},
                       {"field": "lgd_pct", "operation": "multiply",
                        "value": "1.10", "origin": "LGD x1.10"}],
            "methods": ["delta"], "name": "Construction PD+LGD"}
    base.update(over)
    return base


def run(params, store, n, domain="corporate", **execute):
    made = run_bridge(domain, params, store=store, run_id=f"run-p{n}")
    if made.provenance.get("whatif_state") == br.BASELINE_CHOICE_REQUIRED:
        return made, None
    digest = made.provenance["whatif_digest_to_confirm"]
    out = run_bridge(domain, {"operation": br.EXECUTE,
                              "confirmation_digest": digest, "reply": "yes",
                              **execute}, store=store, run_id=f"run-e{n}")
    return made, out


def D(x):
    return Decimal(str(x))


# ---- the decomposition contract ---------------------------------------------------

def test_decomp_every_scope_reconciles_and_carries_the_whole_taxonomy():
    store = Store()
    _made, out = run(construction(), store, 1)
    d = out.provenance["whatif_decomposition"]["delta"]
    dc.check(d)
    for scope in ("selected", "total"):
        s = d["scopes"][scope]
        assert [c["id"] for c in s["components"]] == list(dc.ORDER)
        total = D(s["opening"]) + sum(D(c["value"]) for c in s["components"]
                                      if c["kind"] != "total" and c["value"])
        assert abs(total - D(s["closing"])) <= D("0.000001")
        assert s["reconciles"] is True


def test_decomp_pd_and_lgd_are_separately_measured_and_flows_are_na_with_reasons():
    store = Store()
    _made, out = run(construction(), store, 1)
    comps = {c["id"]: c for c in out.provenance["whatif_decomposition"]
             ["delta"]["scopes"]["selected"]["components"]}
    assert comps["pd"]["status"] == dc.MEASURED and D(comps["pd"]["value"]) > 0
    assert comps["lgd"]["status"] == dc.MEASURED and D(comps["lgd"]["value"]) > 0
    for flow in ("new_originations", "repayment_amortisation", "cures",
                 "new_defaults", "recoveries"):
        assert comps[flow]["status"] == dc.NOT_APPLICABLE
        assert comps[flow]["reason"]
    assert comps["stage_1_to_2"]["status"] == dc.NOT_APPLICABLE
    assert "frozen" in comps["stage_1_to_2"]["reason"]
    assert comps["residual"]["status"] in (dc.MEASURED, dc.ZERO)


def test_decomp_selected_plus_rest_of_book_equals_total_in_the_same_result():
    store = Store()
    _made, out = run(construction(), store, 1)
    d = out.provenance["whatif_decomposition"]["delta"]
    cross = d["cross_scope"]
    assert D(cross["selected_delta"]) + D(cross["rest_of_book_delta"]) == \
        D(cross["total_delta"])
    assert D(cross["rest_of_book_delta"]) == 0 and cross["rest_of_book_reason"]
    assert cross["selected_share_of_total_change_pct"] == "100.00"
    sel, tot = d["scopes"]["selected"], d["scopes"]["total"]
    assert D(tot["opening"]) > D(sel["opening"])
    assert D(tot["change"]) == D(sel["change"])
    assert d["selected_equals_total"] is False


def test_decomp_the_same_components_match_between_scopes():
    store = Store()
    _made, out = run(construction(), store, 1)
    d = out.provenance["whatif_decomposition"]["delta"]
    sel = {c["id"]: c for c in d["scopes"]["selected"]["components"]}
    tot = {c["id"]: c for c in d["scopes"]["total"]["components"]}
    for cid in dc.ORDER:
        assert sel[cid]["label"] == tot[cid]["label"]
        assert sel[cid]["order"] == tot[cid]["order"]
        if sel[cid]["kind"] != "total":
            assert (None if sel[cid]["value"] is None else D(sel[cid]["value"])) \
                == (None if tot[cid]["value"] is None else D(tot[cid]["value"]))
            assert sel[cid]["status"] == tot[cid]["status"]


def test_decomp_whole_book_scope_is_labelled_selected_equals_total():
    store = Store()
    _made, out = run(construction(cohort={"filters": []}), store, 1)
    d = out.provenance["whatif_decomposition"]["delta"]
    assert d["selected_equals_total"] is True
    assert d["scopes"]["selected"]["opening"] == d["scopes"]["total"]["opening"]


def test_decomp_rows_are_published_for_every_component_and_scope():
    store = Store()
    _made, out = run(construction(), store, 1)
    rows = [r for r in out.rows if r["section"].startswith("decomposition_")]
    scopes = {r["view"] for r in rows if r["section"] != "decomposition_cross"}
    assert scopes == {"selected", "total"}
    assert len([r for r in rows if r["view"] == "selected"]) == len(dc.ORDER)
    assert any(r["section"] == "decomposition_cross" and
               r["status"] == "RECONCILES" for r in rows)


def test_decomp_user_defined_is_a_management_overlay_not_a_driver_split():
    store = Store()
    _made, out = run(construction(methods=["user_defined"],
                                  user_assumption={"form": "relative",
                                                   "value": "12",
                                                   "stated_as": "+12%"}),
                     store, 1)
    comps = {c["id"]: c for c in out.provenance["whatif_decomposition"]
             ["user_defined"]["scopes"]["selected"]["components"]}
    assert comps["management_overlay"]["status"] == dc.MEASURED
    assert comps["pd"]["status"] == dc.NOT_APPLICABLE


def test_decomp10_no_shap_or_feature_attribution_is_in_the_accounting_contract():
    store = Store()
    _made, out = run(construction(), store, 1)
    blob = str(out.provenance["whatif_decomposition"]).lower()
    assert "shap" not in blob.replace("shapley", "")


# ---- lineage: the second scenario ------------------------------------------------

def test_base01_a_second_scenario_asks_original_baseline_or_on_top():
    store = Store()
    run(construction(), store, 1)
    made, out = run(construction(name="Second", shocks=[
        {"field": "lgd_pct", "operation": "multiply", "value": "1.05",
         "origin": "LGD x1.05"}]), store, 2)
    assert out is None
    assert made.provenance["whatif_state"] == br.BASELINE_CHOICE_REQUIRED
    assert made.provenance["whatif_previewed"] is False
    options = [r["value"] for r in made.rows if r["item"].startswith("Option")]
    assert "SOURCE_BASELINE" in options and "PRIOR_SCENARIO" in options
    # The executed scenario is still the one the thread holds.
    assert th.read(store.context)["executed_run_id"] == "run-e1"


def test_base03_explicit_original_baseline_branches_from_the_source():
    store = Store()
    _m1, first = run(construction(), store, 1)
    _m2, second = run(construction(name="B", baseline={
        "mode": "SOURCE_BASELINE"}), store, 2)
    assert second.provenance["whatif_baseline"] == {"mode": "SOURCE_BASELINE"}
    a = first.provenance["whatif_decomposition"]["delta"]["scopes"]["selected"]
    b = second.provenance["whatif_decomposition"]["delta"]["scopes"]["selected"]
    assert a["opening"] == b["opening"], "both start from the booked baseline"


def test_base02_on_top_of_the_previous_scenario_layers_on_its_result():
    store = Store()
    _m1, first = run(construction(shocks=[
        {"field": "pd_pit_12m", "operation": "multiply", "value": "1.20",
         "origin": "PD x1.20"}], name="A"), store, 1)
    a_id = first.provenance["whatif_scenario_id"]
    _m2, child = run(construction(name="C", shocks=[
        {"field": "lgd_pct", "operation": "multiply", "value": "1.10",
         "origin": "LGD x1.10"}],
        baseline={"mode": "PRIOR_SCENARIO", "parent_scenario_id": a_id}),
        store, 2)
    assert child.provenance["whatif_baseline"]["parent_scenario_id"] == a_id
    a = first.provenance["whatif_decomposition"]["delta"]["scopes"]
    c = child.provenance["whatif_decomposition"]["delta"]["scopes"]
    # The child's opening IS the parent's closing, at both scopes.
    assert D(c["selected"]["opening"]) == D(a["selected"]["closing"])
    assert abs(D(c["total"]["opening"]) - D(a["total"]["closing"])) <= \
        D("0.000001")
    # And the layered change is LGD on the PD-stressed values: x1.10 of it.
    change = D(c["selected"]["change"])
    assert abs(change - D(a["selected"]["closing"]) * D("0.10")) <= \
        D(a["selected"]["closing"]) * D("0.02")


def test_base04_a_specific_earlier_scenario_can_be_the_parent():
    store = Store()
    _m1, first = run(construction(name="A"), store, 1)
    _m2, _second = run(construction(name="B", baseline={
        "mode": "SOURCE_BASELINE"}, shocks=[
        {"field": "lgd_pct", "operation": "multiply", "value": "1.02",
         "origin": "LGD x1.02"}]), store, 2)
    a_id = first.provenance["whatif_scenario_id"]
    _m3, third = run(construction(name="A1", baseline={
        "mode": "PRIOR_SCENARIO", "parent_scenario_id": a_id}), store, 3)
    assert third.provenance["whatif_baseline"]["parent_scenario_id"] == a_id


def test_persist09_a_tampered_parent_contract_is_refused():
    store = Store()
    _m1, first = run(construction(name="A"), store, 1)
    a_id = first.provenance["whatif_scenario_id"]
    made = run_bridge("corporate", construction(name="C", baseline={
        "mode": "PRIOR_SCENARIO", "parent_scenario_id": a_id}),
        store=store, run_id="run-p2")
    body = store.context["body"]
    body["chain"][0]["canonical"]["shocks"][0]["value"] = "9.99"
    with pytest.raises(ScenarioError):
        run_bridge("corporate", {"operation": br.EXECUTE,
                                 "confirmation_digest": made.provenance[
                                     "whatif_digest_to_confirm"],
                                 "reply": "yes"}, store=store,
                   run_id="run-e2")


def test_base08_layering_never_writes_a_source_row():
    book, _scope = book_of("corporate")

    def total():
        return D(book.session.connection.execute(
            "SELECT SUM(ecl_sar_mn) FROM corp_facility_quarter WHERE "
            "reporting_quarter = '2026Q2'").fetchone()[0])

    before = total()
    store = Store()
    _m1, first = run(construction(name="A"), store, 1)
    run(construction(name="C", baseline={
        "mode": "PRIOR_SCENARIO",
        "parent_scenario_id": first.provenance["whatif_scenario_id"]}),
        store, 2)
    assert total() == before


def test_an_unknown_parent_is_refused_by_name():
    store = Store()
    run(construction(name="A"), store, 1)
    with pytest.raises(ScenarioError):
        run_bridge("corporate", construction(name="C", baseline={
            "mode": "PRIOR_SCENARIO", "parent_scenario_id": "sc-nope"}),
            store=store, run_id="run-p2")
