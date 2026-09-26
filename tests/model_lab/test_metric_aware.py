"""Metric-aware references (lab-eval-3 / lab-oracle-2).

Live UAT `cmp-f364d8b6901a` (re-scored with lab-eval-2) marked the claim
`construction_facilities` = 1,370 facilities CONTRADICTED against 1,016,613.64
-- the Construction Stage 2 EAD in SAR million. `_numeric_claim` applied the
oracle whenever the row's SECTOR matched, whatever the claim's column/unit.
A claim may now only be compared with a reference for the SAME metric.
No model call; everything runs through the real frozen engine or the lab's
own evaluator functions.
"""

from __future__ import annotations

import pytest
from conftest import child, make_service, run
from live_shape import factory

from backend.model_lab import evaluate as E
from backend.model_lab import oracle

RELEASE = "v4-saudi-corporate-20q-v4"


@pytest.fixture(scope="module")
def ref():
    task = oracle.find_task("stage 2 exposure by sector")
    return task, oracle.expected(task, RELEASE)


@pytest.fixture(scope="module")
def two_metric_run(tmp_path_factory):
    svc = make_service(tmp_path_factory.mktemp("twometric"),
                       provider_factory=factory({
                           "fixture-reference": "two_metrics"}))
    cid, ev = run(svc, ["fixture-reference"])
    return svc, cid, ev


def test_reference_values_are_independent_per_metric(ref):
    _, r = ref
    assert r["metrics"]["stage2_ead"]["values"]["Construction"] == \
        pytest.approx(1016613.64, abs=0.01)
    assert r["metrics"]["stage2_facility_count"]["values"]["Construction"] \
        == 1370
    assert r["oracle_version"] == "lab-oracle-2"


def test_live_reproduction_both_claims_resolve_and_are_supported(
        two_metric_run):
    """Construction EAD = 1,016,613.64 and Construction facilities = 1,370,
    cited on the SAME row of the SAME artifact, Anthropic-shaped (`rN` ids,
    SDK blocks), through the real frozen engine."""
    _, _, ev = two_metric_run
    k = child(ev, "fixture-reference")
    assert k["execution_state"] == "COMPLETED"
    by = {c["claim_id"]: c for c in k["claims"]}
    ead, fac = by["construction"], by["construction_facilities"]
    assert ead["row_label"] == fac["row_label"] == "Construction"
    assert ead["asserted_value"] == pytest.approx(1016613.64, abs=0.01)
    assert fac["asserted_value"] == 1370
    assert ead["verification_status"] == "SUPPORTED"
    assert fac["verification_status"] == "SUPPORTED"
    assert ead["reference_metric"] == "stage2_ead"
    assert fac["reference_metric"] == "stage2_facility_count"
    assert ead["reference_value"] == pytest.approx(1016613.64, abs=0.01)
    assert fac["reference_value"] == 1370
    assert fac["reference_unit"] == "facilities"
    for c in (ead, fac):
        assert c["frozen_validation"]["status"] == "ok"
    assert k["stages"]["S4"]["status"] == "PASS"
    pop = next(c for c in k["checks"] if c["check_id"] == "S1S2-POP")
    assert pop["outcome"] == "PASS"
    assert pop["evidence_ref"]["metric_column"] == "stage2_ead_sar_mn"
    assert pop["metric_column_confirmed"] is True


def _artifact(svc, rows, columns):
    return svc.coord.runs.put_artifact(
        run_id="run-synthetic", tenant_id="demo-tenant", kind="result",
        release_id=RELEASE, scope={}, columns=columns, rows=rows)


def test_a_wrong_facility_count_is_still_contradicted(tmp_path, ref):
    task, r = ref
    svc = make_service(tmp_path)
    art = _artifact(svc, [{"sector": "Construction",
                           "stage2_ead_sar_mn": 1016613.64,
                           "stage2_facilities": 1371}],
                    ["sector", "stage2_ead_sar_mn", "stage2_facilities"])
    c = {"claim_id": "construction_facilities", "unit": "facilities",
         "evidence": {"artifact_id": art, "row_key": "r0",
                      "column_id": "stage2_facilities"}}
    out = E._numeric_claim(c, svc.coord.runs, "demo-tenant", task, r,
                           {"population_ok": True, "artifact_id": art},
                           {"status": "ok", "message": "m"})
    assert out["verification_status"] == "CONTRADICTED"
    assert out["reference_metric"] == "stage2_facility_count"
    assert out["reference_value"] == 1370
    assert "1,371" in out["explanation"] and "1,370" in out["explanation"]


def test_no_same_metric_reference_never_contradicts(tmp_path, ref):
    task, r = ref
    svc = make_service(tmp_path)
    art = _artifact(svc, [{"sector": "Construction", "avg_pd_pct": 4.2,
                           "stage2_facilities": 1370}],
                    ["sector", "avg_pd_pct", "stage2_facilities"])
    for col, unit in (("avg_pd_pct", "%"),
                      ("stage2_facilities", "SAR million")):  # unit clash
        c = {"claim_id": col, "unit": unit,
             "evidence": {"artifact_id": art, "row_key": "r0",
                          "column_id": col}}
        out = E._numeric_claim(c, svc.coord.runs, "demo-tenant", task, r,
                               {"population_ok": True,
                                "artifact_id": art},
                               {"status": "ok", "message": "m"})
        assert out["verification_status"] == "SUPPORTED", (col, out)
        assert out["reference_metric"] is None
        assert "no same-metric independent reference" in out["explanation"]


def test_population_check_uses_the_metric_column_not_the_first(tmp_path,
                                                              ref):
    task, r = ref
    svc = make_service(tmp_path)
    ead = r["metrics"]["stage2_ead"]["values"]
    fac = r["metrics"]["stage2_facility_count"]["values"]
    rows = [{"sector": s, "stage2_facilities": fac[s],
             "stage2_ead_sar_mn": ead[s]} for s in ead]    # count FIRST
    art = _artifact(svc, rows, ["sector", "stage2_facilities",
                                "stage2_ead_sar_mn"])
    fr = {"disposition": "answer", "numeric_claims": [],
          "tables": [{"artifact_id": art, "column_units": {
              "stage2_ead_sar_mn": "SAR million",
              "stage2_facilities": "facilities"}}]}
    answers = [{"final_response": fr, "frozen_state": "COMPLETED",
                "run_id": "run-synthetic"}]
    checks, facts = E._checks({}, answers, svc.coord.runs, "demo-tenant",
                              task, r)
    pop = next(c for c in checks if c["check_id"] == "S1S2-POP")
    assert pop["outcome"] == "PASS"
    assert facts["metric_column"] == "stage2_ead_sar_mn"
    assert facts["metric_column_confirmed"] is True


def test_match_metric_is_unit_and_name_aware(ref):
    _, r = ref
    assert oracle.match_metric(r, "stage2_ead_sar_mn", "SAR million") == \
        "stage2_ead"
    assert oracle.match_metric(r, "stage2_facilities", "facilities") == \
        "stage2_facility_count"
    assert oracle.match_metric(r, "stage2_facilities", "SAR million") is None
    assert oracle.match_metric(r, "ead_sar_mn", "borrowers") is None
    assert oracle.match_metric(r, "avg_pd", "%") is None
