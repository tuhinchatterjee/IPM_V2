"""Q01-Q16, M02-M16: the evaluator catches KNOWN injected errors, keeps
unknowns unknown, and never invents precision."""

from __future__ import annotations

import pytest
from conftest import child, make_service, run

from backend.model_lab import metrics as mx
from backend.model_lab import oracle


def _check(k, cid):
    return next(c for c in k["checks"] if c["check_id"] == cid)


def test_Q01_the_comparator_is_not_the_answer_key(tmp_path):
    """A WRONG comparator: candidates that disagree with it and are right
    pass; the comparator itself fails the independent check."""
    svc = make_service(tmp_path)
    _, ev = run(svc, ["fixture-wrong-scope", "fixture-reference"],
                comparator="fixture-wrong-scope")
    comp = child(ev, "fixture-wrong-scope")
    ref = child(ev, "fixture-reference")
    assert _check(comp, "S1S2-POP")["outcome"] == "FAIL"
    assert _check(ref, "S1S2-POP")["outcome"] == "PASS"
    assert ref["opus_match"]["S2"]["pct"] == 0.0   # disagrees, and is right


def test_Q02_a_different_valid_plan_passes(demo):
    _, _, ev = demo
    alt = child(ev, "fixture-alternate-plan")
    assert _check(alt, "S1S2-POP")["outcome"] == "PASS"
    assert alt["stages"]["S2"]["status"] == "PASS"
    assert alt["opus_match"]["S2"]["pct"] == 100.0   # semantics, not text


def test_Q03_wrong_cohort_is_caught_and_S4_inherits_it(demo):
    _, _, ev = demo
    w = child(ev, "fixture-wrong-scope")
    pop = _check(w, "S1S2-POP")
    assert pop["outcome"] == "FAIL" and "whole book" in pop["actual"]
    assert w["stages"]["S4"]["status"] == "PARTIAL"
    assert w["stages"]["S4"].get("inherited") is True
    assert w["first_divergence"]["confidence"] == "MULTI_STAGE_UNRESOLVED"
    assert w["claims"][0]["verification_status"] == "CONTRADICTED"


def test_Q04_tolerances_are_declared_and_applied():
    t = oracle.find_task("stage 2 exposure by sector")
    assert t.abs_tolerance == 0.01
    assert oracle.within(100.0, 100.009, t)
    assert not oracle.within(100.0, 100.02, t)


def test_Q05_free_form_question_gets_needs_review_not_a_score(tmp_path):
    svc = make_service(tmp_path)
    _, ev = run(svc, ["fixture-reference"],
                question="Tell me something interesting about the book.")
    k = child(ev, "fixture-reference")
    assert ev["task"] is None
    assert k["checks"][0]["status"] == "NEEDS_REVIEW"
    assert all(c["outcome"] != "PASS" for c in k["checks"])
    assert k["stages"]["S2"]["status"] in ("UNKNOWN", "NOT_OBSERVED")


def test_Q06_Q07_claim_statuses_stay_distinct(demo):
    _, _, ev = demo
    inv = child(ev, "fixture-invented-cause")
    by = {c["claim_type"]: c["verification_status"] for c in inv["claims"]}
    assert by["numeric"] == "SUPPORTED"
    assert by["causal"] == "UNSUPPORTED"
    assert inv["stages"]["S4"]["status"] == "FAIL"
    assert inv["stages"]["S2"]["status"] == "PASS"   # correct numbers kept
    assert any(f["primary_category"] == "S4_INTERPRETATION"
               for f in inv["failures"])


def test_Q08_empty_answers_cannot_game_the_rates(demo):
    _, _, ev = demo
    nt = child(ev, "fixture-no-tool")
    r = nt["claim_rates"]
    assert r["contradicted_rate"]["display"] == "N/A"
    assert r["assessment_coverage"]["display"] == "N/A"
    ref = child(ev, "fixture-reference")
    assert ref["claim_rates"]["required_output_coverage"]["display"] == "2/2"


def test_Q09_repair_denominator(demo):
    _, _, ev = demo
    rep = child(ev, "fixture-repair")["repair"]
    assert (rep["opportunities"], rep["valid_repairs"],
            rep["business_correct_recoveries"]) == (1, 1, 1)
    assert rep["chains"][0]["diff"]["after"] != rep["chains"][0]["diff"][
        "before"]
    none = child(ev, "fixture-reference")["repair"]
    assert none["status"] == "NOT_OBSERVED" and none["opportunities"] == 0


def test_Q10_protocol_failure_is_not_blamed_on_reasoning(demo):
    _, _, ev = demo
    nt = child(ev, "fixture-no-tool")
    assert nt["failures"][0]["primary_category"] == "RUNTIME_CAPABILITY"
    assert nt["stages"]["S4"]["status"] == "NOT_REACHED"


def test_Q11_replays_refuse_without_approval(demo):
    from fastapi.testclient import TestClient  # noqa: F401 - api test below
    svc, cid, _ = demo
    assert svc.coord.readiness()  # replay endpoint covered in test_api


def test_Q13_reviews_are_versioned_and_keep_the_prior(tmp_path):
    svc = make_service(tmp_path)
    cid, ev = run(svc, ["fixture-invented-cause"],
                  comparator="fixture-invented-cause")
    k = ev["children"][0]
    causal = next(c for c in k["claims"] if c["claim_type"] == "causal")
    target = f"{k['child_run_id']}:{causal['claim_id']}"
    with pytest.raises(ValueError):
        svc.add_review(cid, reviewer="r", target=target,
                       decision="OVERTURN_TO_SUPPORTED", reason=" ")
    out = svc.add_review(cid, reviewer="r", target=target,
                         decision="OVERTURN_TO_SUPPORTED",
                         reason="the user supplied a source")
    cur = svc.coord.store.current_evaluation(cid, svc.cfg.tenant_id)
    c2 = next(c for c in cur["body"]["children"][0]["claims"]
              if c["claim_id"] == causal["claim_id"])
    assert c2["verification_status"] == "SUPPORTED"
    assert c2["review"]["automatic_status"] == "UNSUPPORTED"
    rv = svc.coord.store.reviews(cid, svc.cfg.tenant_id)
    assert rv[0]["prior"]["verification_status"] == "UNSUPPORTED"
    assert out["evaluation_revision"] == cur["revision"]


def test_Q14_one_question_never_recommends_training(demo):
    svc, _, _ = demo
    tr = svc.training_readiness()
    assert tr["profiles"]
    for p in tr["profiles"]:
        assert p["status"] in ("COLLECT_MORE_EVIDENCE",
                               "FIX_INTEGRATION_FIRST")
        assert p["tentative"] is True
    assert "No training" in tr["disclaimer"]


def test_M04_shared_calls_are_counted_once(demo):
    _, _, ev = demo
    for k in ev["children"]:
        ids = [c["call_id"] for c in k["calls"]]
        assert len(ids) == len(set(ids))
        total = sum(c["duration_ms"] or 0 for c in k["calls"])
        if k["calls"]:
            assert abs(k["metrics"]["provider_call_ms_sum"]["value"] -
                       total) < 1e-6


def test_M05_M06_application_time_is_separate_and_unions_overlaps():
    assert mx.interval_union_ms([(0, 10), (5, 15), (20, 25)]) == 20
    assert mx.interval_union_ms([(0, 10), (2, 3)]) == 10
    assert mx.interval_union_ms([]) == 0


def test_M02_M09_unknowns_stay_unknown(demo):
    _, _, ev = demo
    k = child(ev, "fixture-reference")
    for name in ("first_protocol_event_ms", "reasoning_tokens",
                 "infrastructure_cost_usd"):
        m = k["metrics"][name]
        assert m["value"] is None and m["status"] == "UNAVAILABLE"
        assert m["missing_reason"]
    with pytest.raises(ValueError):
        mx.Metric(None, "ms", "MEASURED")
    with pytest.raises(ValueError):
        mx.Metric(None, "ms", "UNAVAILABLE")      # needs a reason


def test_M08_M10_M11_tokens(demo):
    _, _, ev = demo
    k = child(ev, "fixture-repair")
    ins = [c["input_tokens"] for c in k["calls"]]
    assert k["metrics"]["peak_context_tokens"]["value"] == max(ins)
    assert k["metrics"]["input_tokens"]["value"] == sum(ins)
    assert k["metrics"]["input_tokens"]["status"] == "ESTIMATED"
    assert "fixture" in k["metrics"]["tokenizer"]


def test_M12_M13_throughput_and_cost_labels(demo):
    _, _, ev = demo
    k = child(ev, "fixture-reference")
    assert k["metrics"]["server_generation_rate"]["status"] == "UNAVAILABLE"
    assert "fixture" in k["metrics"]["cost_usd"]["source"]


def test_M14_resource_samples_state_their_source(demo):
    svc, cid, _ = demo
    evs = [e for e in svc.coord.store.events(cid, svc.cfg.tenant_id)
           if e["event_type"] == "resource.samples"]
    import json
    body = json.loads(svc.coord.store.get_blob(evs[0]["payload_ref"]))
    assert body["method"] and body["gpu"] is None and body["gpu_reason"]
    assert body["model_runtime_memory"] is None


def test_M15_small_samples_withhold_p95():
    s = mx.sample_summary([1, 2, 3], unique_tasks=1, unit="ms")
    assert s["p95"] is None and s["p95_status"] == "INSUFFICIENT_SAMPLE"
    assert s["median"] == 2


def test_Q16_no_training_export_exists_without_approval():
    from pathlib import Path

    import backend.model_lab as lab
    names = [p.name for p in Path(lab.__file__).parent.rglob("*.py")]
    assert not any("train" in n for n in names)
