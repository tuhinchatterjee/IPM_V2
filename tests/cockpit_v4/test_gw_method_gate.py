"""P6 — the method-selection gate (v3.1 §5.1, §7.1, UAT-01).

SCENARIO and METHOD are separate decisions. A confirmed scenario with no
method is NOT executed: it stops at METHOD_SELECTION. There is no silent Delta
default and no ML-to-Delta fallback; Retail ML stays visibly unavailable while
G4 fails.

EVIDENCE LABEL: NO MODEL. No model call. The engine's own `execute_scenario` path on the
published candidate books, through the same `bridge.execute` a Cockpit turn
dispatches.
"""

from __future__ import annotations

import pytest

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import bridge as br
from backend.cockpit_v4.scenario import thread as th
from tests.cockpit_v4.test_whatif_bridge import Store, run_bridge

CANDIDATE = {"corporate": "v4-whatif-corporate-20q-s1",
             "retail": "v4-whatif-retail-20m-s1"}


@pytest.fixture(autouse=True)
def candidate_books(monkeypatch):
    for release in CANDIDATE.values():
        if not lake.exists(release):
            pytest.skip(f"{release} is not published here")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_CORPORATE", "1")
    monkeypatch.setenv("COCKPIT_V4_WHATIF_RETAIL", "1")
    arun.reset()
    yield
    arun.reset()


#: THE LIVE-UAT REPRODUCTION, exactly: Construction, 100 borrowers, 248
#: facilities, PD x1.20, LGD x1.10, stages fixed, scenario confirmed, and NO
#: method selected. H2 executed this with a Delta-like calculation.
UAT = {
    "operation": br.PREVIEW,
    "cohort": {"filters": [{"column": "sector", "operator": "=",
                            "value": "Construction"}]},
    "shocks": [
        {"field": "pd_pit_12m", "operation": "multiply", "value": "1.20",
         "origin": "PD x1.20"},
        {"field": "lgd_pct", "operation": "multiply", "value": "1.10",
         "origin": "LGD x1.10"}],
    "clauses": ["For the Construction borrowers, PD x1.20 and LGD x1.10, "
                "stages fixed."],
}


def preview(domain="corporate", params=None, store=None, run_id="run-1"):
    store = store or Store()
    made = run_bridge(domain, params or UAT, store=store, run_id=run_id)
    return store, made, made.provenance["whatif_digest_to_confirm"]


def execute(domain, store, digest, run_id="run-2", **extra):
    return run_bridge(domain, {"operation": br.EXECUTE,
                               "confirmation_digest": digest, "reply": "yes",
                               **extra}, store=store, run_id=run_id)


def numbers(produced):
    return [r for r in produced.rows
            if r.get("scenario_sar_mn") not in ("", None)]


def test_uat01_confirmed_scenario_with_no_method_is_not_executed():
    store, made, digest = preview()
    cohort = {r["item"]: r["value"] for r in made.rows
              if r["section"] == "cohort"}
    assert cohort["Exposures selected"] == 248
    assert cohort["Owners behind them"] == 100
    stages = [r for r in made.rows if r["section"] == "policy"
              and r["item"] == "Stages"]
    assert stages[0]["value"] == "frozen"
    out = execute("corporate", store, digest)
    assert out.provenance["whatif_executed"] is False
    assert out.provenance["whatif_state"] == br.METHOD_SELECTION_REQUIRED
    assert out.provenance["whatif_methods_chosen"] == []
    assert not numbers(out), "no ECL figure was produced"
    assert "whatif_methods_ran" not in out.provenance


def test_meth02_meth03_it_enters_method_selection_and_says_confirmed_not_executed():
    store, _made, digest = preview()
    out = execute("corporate", store, digest)
    headline = {r["item"]: r for r in out.rows if r["section"] == "headline"}
    assert headline["Status"]["status"] == br.METHOD_SELECTION_REQUIRED
    assert "confirmed" in headline["Status"]["note"].lower()
    assert "NOT executed" in headline["Status"]["note"]
    assert headline["Executed"]["status"] == "NO"
    offered = {r["method"] for r in out.rows if r["section"] == "method"}
    assert offered == {"delta", "ml", "user_defined", "compare"}
    stored = th.read(store.context)
    assert stored["method_state"] == br.METHOD_SELECTION_REQUIRED
    assert stored["confirmed_digest"] == digest


def test_meth04_meth05_choosing_delta_runs_delta_only_on_the_same_confirmation():
    store, _made, digest = preview()
    gated = execute("corporate", store, digest)
    assert gated.provenance["whatif_executed"] is False
    ran = execute("corporate", store, digest, run_id="run-3",
                  methods=["delta"])
    assert ran.provenance["whatif_methods_ran"] == ["delta"]
    assert ran.provenance["whatif_confirmation_digest"] == digest
    per_method = {r["method"] for r in ran.rows if r["section"] == "method"
                  and r["method"] in ("delta", "ml", "user_defined")}
    assert per_method == {"delta"}


def _ml_libraries() -> bool:
    try:
        import xgboost  # noqa: F401
        return True
    except ImportError:
        return False


#: ML runs on the candidate runtime (.venv-whatif); the accepted interpreter
#: deliberately carries no ML libraries (test_whatif_ml pins that). On it the
#: emulator is UNAVAILABLE for a stated reason -- never substituted.
needs_ml = pytest.mark.skipif(not _ml_libraries(),
                              reason="ML libraries are the candidate "
                                     "runtime's; run on .venv-whatif")


@needs_ml
def test_meth06_corporate_ml_runs_when_every_gate_passes():
    store, _made, digest = preview()
    ran = execute("corporate", store, digest, methods=["ml"])
    assert ran.provenance["whatif_methods_ran"] == ["ml"]


def test_retail_lgd_delta_runs_on_charged_off_rows_without_a_key_error():
    """Defect found in P6 (present at P5): a Retail LGD shock's eligibility
    predicate reads write_off_sar_mn, which the cohort read did not select."""
    params = {**UAT, "methods": ["delta"], "cohort": {"filters": [
        {"column": "product", "operator": "=", "value": "Personal Finance"}]}}
    store, _made, digest = preview("retail", params)
    ran = execute("retail", store, digest)
    assert ran.provenance["whatif_methods_ran"] == ["delta"]


def test_meth07_meth08_direct_retail_ml_is_refused_without_a_delta_fallback():
    params = {**UAT, "cohort": {"filters": [
        {"column": "product", "operator": "=", "value": "Personal Finance"}]}}
    store, _made, digest = preview("retail", params)
    out = execute("retail", store, digest, methods=["ml"])
    assert out.provenance["whatif_executed"] is False
    assert out.provenance["whatif_state"] == br.METHOD_UNAVAILABLE
    assert "G4" in out.provenance["whatif_method_availability"]["ml"]
    assert not numbers(out)
    # The scenario stays confirmed: another method runs without rebuilding it.
    ran = execute("retail", store, digest, run_id="run-3", methods=["delta"])
    assert ran.provenance["whatif_methods_ran"] == ["delta"]


def test_meth12_all_methods_runs_the_available_and_keeps_ml_unavailable():
    params = {**UAT, "cohort": {"filters": [
        {"column": "product", "operator": "=", "value": "Personal Finance"}]}}
    store, _made, digest = preview("retail", params)
    ran = execute("retail", store, digest, methods=["delta", "ml"])
    assert ran.provenance["whatif_methods_ran"] == ["delta"]
    assert ran.provenance["whatif_methods_unavailable"] == ["ml"]


def test_meth09_user_defined_without_input_asks_instead_of_guessing():
    store, _made, digest = preview()
    out = execute("corporate", store, digest, methods=["user_defined"])
    assert out.provenance["whatif_executed"] is False
    assert out.provenance["whatif_state"] == br.METHOD_INPUT_REQUIRED
    assert not numbers(out)


def test_meth10_user_defined_runs_once_its_input_is_supplied():
    store, _made, digest = preview()
    ran = execute("corporate", store, digest, methods=["user_defined"],
                  user_assumption={"form": "relative", "value": "15",
                                   "stated_as": "ECL rises 15%"})
    assert ran.provenance["whatif_methods_ran"] == ["user_defined"]


@needs_ml
def test_meth11_compare_uses_one_contract_cohort_and_baseline():
    store, _made, digest = preview()
    ran = execute("corporate", store, digest, methods=["delta", "ml"])
    assert set(ran.provenance["whatif_methods_ran"]) == {"delta", "ml"}
    baselines = {r["baseline_sar_mn"] for r in ran.rows
                 if r["section"] == "method" and r["baseline_sar_mn"]}
    assert len(baselines) == 1


def test_meth13_a_first_turn_scenario_with_no_method_stops_at_method_selection():
    store, made, digest = preview()
    assert all(r["status"] != "chosen" for r in made.rows
               if r["section"] == "methods")
    assert any("no method is assumed" in r["detail"] for r in made.rows
               if r["section"] == "methods")
    assert execute("corporate", store, digest).provenance[
        "whatif_executed"] is False


def test_meth14_an_explicit_delta_is_not_asked_again():
    store, _made, digest = preview(params={**UAT, "methods": ["delta"]})
    ran = execute("corporate", store, digest)
    assert ran.provenance["whatif_methods_ran"] == ["delta"]


@needs_ml
def test_meth15_an_explicit_compare_is_not_asked_again():
    store, _made, digest = preview(params={**UAT,
                                           "methods": ["delta", "ml"]})
    ran = execute("corporate", store, digest)
    assert set(ran.provenance["whatif_methods_ran"]) == {"delta", "ml"}


def test_base06_changing_only_the_method_reuses_the_confirmed_contract():
    store, _made, digest = preview()
    first = execute("corporate", store, digest, methods=["delta"])
    second = execute("corporate", store, digest, run_id="run-3",
                     methods=["user_defined"],
                     user_assumption={"form": "relative", "value": "10",
                                      "stated_as": "ECL +10%"})
    assert first.provenance["whatif_confirmation_digest"] == \
        second.provenance["whatif_confirmation_digest"] == digest
    assert first.provenance["whatif_membership_hash"] == \
        second.provenance["whatif_membership_hash"]


def test_sec06_an_unavailable_method_cannot_be_forced_by_a_crafted_request():
    params = {**UAT, "cohort": {"filters": [
        {"column": "product", "operator": "=", "value": "Credit Card"}]},
        "methods": ["ml"]}
    store, _made, digest = preview("retail", params)
    out = execute("retail", store, digest)
    assert out.provenance["whatif_executed"] is False
    assert out.provenance["whatif_state"] == br.METHOD_UNAVAILABLE


def test_no_default_method_survives_in_the_request_parser():
    """The line that turned an unnamed method into Delta is gone."""
    assert br._methods(None, path="p") == ()
    parsed = br.validate(UAT, step_id="s1", domain_id=dom.CORPORATE)
    assert parsed.methods == ()
