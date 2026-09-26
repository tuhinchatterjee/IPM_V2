"""Regressions for the two defects the live Opus comparison exposed
(`cmp-f364d8b6901a`), reproduced offline with the transport shape the frozen
Anthropic adapter really produces. No network, no paid call.

Defect 1: the frozen store persists Anthropic SDK assistant blocks as repr
strings; the lab read only dict blocks, so live calls showed `tools=(none)`
and S1 failed "no usable action" on a completed run.

Defect 2: the lab resolved `row_key` only as `column=value`, while the
frozen Finalizer (and live Opus) use published row ids (`r0`) and derived
claims; every unmapped claim was mislabelled UNSUPPORTED.
"""

from __future__ import annotations

import pytest
from conftest import child, make_service, run
from live_shape import factory

from backend.model_lab import evaluate as E


@pytest.fixture(scope="module")
def live_shape(tmp_path_factory):
    svc = make_service(tmp_path_factory.mktemp("liveshape"),
                       provider_factory=factory({
                           "fixture-reference": "reference",
                           "fixture-invented-cause": "invented_cause",
                           "fixture-repair": "repair",
                           "fixture-wrong-scope": "wrong_scope"}))
    cid, ev = run(svc, ["fixture-reference", "fixture-invented-cause",
                        "fixture-repair", "fixture-wrong-scope"])
    return svc, cid, ev


def test_the_stored_blocks_really_are_sdk_reprs(live_shape):
    """The reproduction is faithful: the frozen store holds strings."""
    svc, _, ev = live_shape
    k = child(ev, "fixture-reference")
    msgs = svc.coord.runs.load_messages(k["turns"][0]["run_id"])
    blocks = next(m["content"] for m in msgs if m["role"] == "assistant")
    assert all(isinstance(b, str) for b in blocks)
    assert blocks[-1].startswith("ToolUseBlock(")


def test_1_tool_use_stop_with_a_real_call_never_shows_no_tools(live_shape):
    _, _, ev = live_shape
    for k in ev["children"]:
        for c in k["calls"]:
            if c["stop_reason"] == "tool_use":
                assert c["tool_names"], c
                assert c["tool_names_source"] == "frozen_call_report"
                assert c["evidence_status"] == "FROM_FROZEN_RECORD"
                obs = c["tool_names_by_source"]["observer"]
                assert obs == c["tool_names"], "observer disagrees"
                assert not c["tool_names_disagree"]


def test_2_completed_run_does_not_fail_S1_on_telemetry(live_shape):
    _, _, ev = live_shape
    k = child(ev, "fixture-reference")
    assert k["execution_state"] == "COMPLETED"
    assert k["stages"]["S1"]["status"] in ("PASS", "NOT_SEPARATELY_"
                                           "OBSERVABLE")
    assert k["stages"]["S2"]["status"] == "PASS"
    assert not [f for f in k["failures"]
                if f["primary_category"] == "RUNTIME_CAPABILITY"]


def _synthetic_lost_names():
    """A completed run whose stored call report has NO tool names and whose
    stored blocks are SDK reprs: every source of names is gone."""
    messages = [
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": ["ToolUseBlock(id='t1', …)"]},
        {"role": "user", "content": [{"type": "tool_result",
                                      "tool_use_id": "t1",
                                      "content": '{"status": "ok"}'}]}]
    report = [{"seq": 1, "purpose": "ANALYSIS_ACTION", "phase": "action",
               "parse_status": "tool_call", "tool_calls": 1,
               "stop_reason": "tool_use", "usable": True}]
    return messages, report


def test_2_3_lost_names_are_evidence_incomplete_not_failure():
    messages, report = _synthetic_lost_names()
    gens = E._generations(messages, report, [])
    assert gens[0]["evidence_status"] == "EVIDENCE_INCOMPLETE"
    assert gens[0]["tool_uses"] == []          # nothing fabricated
    E.classify(gens)
    assert "EVIDENCE_INCOMPLETE" in gens[0]["protocol_flag"]
    for g in gens:
        g["call_id"] = "c1"
    pop = {"check_id": "S1S2-POP", "stage": "S1+S2", "outcome": "PASS"}
    res = {"check_id": "S2-RESULT", "stage": "S2", "outcome": "PASS"}
    stages = E._stages(gens, [pop, res],
                       {"status": "NOT_OBSERVED", "note": ""}, [],
                       {"frozen_state": "COMPLETED",
                        "final_response": {"disposition": "answer"}},
                       task=object())
    assert stages["S1"]["status"] == "PASS"
    assert stages["S1"]["evidence_status"] == "EVIDENCE_INCOMPLETE"
    assert stages["S2"]["status"] == "PASS"


def test_2_a_genuine_frozen_no_call_still_fails():
    """The protocol-failure verdict survives when the FROZEN record says
    no tool call was produced and the run failed."""
    report = [{"seq": 1, "phase": "action", "parse_status": "no_tool_call",
               "tool_calls": 0, "response_text_chars": 12, "usable": False}]
    messages = [{"role": "user", "content": "Q"},
                {"role": "assistant", "content": ["TextBlock(text='x')"]}]
    gens = E._generations(messages, report, [])
    assert gens[0]["evidence_status"] == "NO_TOOL_CALL_RECORDED"
    E.classify(gens)
    gens[0]["call_id"] = "c1"
    st = E._stages(gens, [], {"status": "NOT_OBSERVED", "note": ""}, [],
                   {"frozen_state": "FAILED", "final_response": None},
                   task=None)
    assert st["S1"]["status"] == "FAIL"


def test_4_evidence_bound_and_derived_claims_are_supported(live_shape):
    _, _, ev = live_shape
    k = child(ev, "fixture-reference")
    by = {c["claim_id"]: c for c in k["claims"]}
    assert by["top"]["verification_status"] == "SUPPORTED"
    assert by["top"]["row_label"] == "Construction"      # resolved from r0
    assert by["total"]["claim_type"] == "numeric_derived"
    assert by["total"]["verification_status"] == "SUPPORTED"
    for c in (by["top"], by["total"]):
        assert c["frozen_validation"]["status"] == "ok"
        assert "evidence-bound" in c["frozen_validation"]["message"]
    assert k["stages"]["S4"]["status"] == "PASS"


def test_5_unresolvable_reference_is_unverifiable_not_unsupported(
        live_shape):
    svc, _, ev = live_shape
    k = child(ev, "fixture-reference")
    art = k["claims"][0]["result_refs"][0]
    fr = {"narrative": "", "numeric_claims": [
        {"claim_id": "a", "unit": "SAR million",
         "evidence": {"artifact_id": "art-doesnotexist", "row_key": "r0",
                      "column_id": "stage2_ead_sar_mn"}},
        {"claim_id": "b", "unit": "SAR million",
         "evidence": {"artifact_id": art, "row_key": "r999",
                      "column_id": "stage2_ead_sar_mn"}},
        {"claim_id": "c", "unit": "SAR million",
         "evidence": {"artifact_id": art, "row_key": "r0",
                      "column_id": "no_such_column"}},
        {"claim_id": "d", "unit": "SAR million", "derivation": {
            "operation": "sum", "operands": [
                {"artifact_id": "art-gone", "column_id": "x",
                 "rows": "all"}]}}]}
    claims = E._claims(fr, svc.coord.runs, "demo-tenant", None, None, {},
                       {"status": "ok", "message": "frozen validated"})
    for c in claims:
        assert c["verification_status"] == "UNVERIFIABLE", c
        assert c["evidence_status"] == "EVIDENCE_INCOMPLETE"
        assert c["reviewer_status"] == "NEEDS_REVIEW"
        assert c["frozen_validation"]["status"] == "ok"   # kept separate
    rates = E._claim_rates(claims, None, {})
    assert rates["unsupported_rate"]["display"] == "N/A"


def test_5_unmapped_claims_do_not_fail_S4():
    claims = [{"claim_id": "x", "claim_type": "numeric",
               "verification_status": "UNVERIFIABLE",
               "evidence_status": "EVIDENCE_INCOMPLETE"}]
    st = E._stages([], [{"check_id": "S4-LARGEST", "stage": "S4",
                         "outcome": "PASS"}],
                   {"status": "NOT_OBSERVED", "note": ""}, claims,
                   {"frozen_state": "COMPLETED",
                    "final_response": {"disposition": "answer"}},
                   task=object())
    assert st["S4"]["status"] == "PASS"
    assert st["S4"]["evidence_status"] == "EVIDENCE_INCOMPLETE"


def test_6_invented_cause_stays_unsupported_on_the_live_shape(live_shape):
    _, _, ev = live_shape
    k = child(ev, "fixture-invented-cause")
    causal = [c for c in k["claims"] if c["claim_type"] == "causal"]
    assert causal and causal[0]["verification_status"] == "UNSUPPORTED"
    assert k["stages"]["S4"]["status"] == "FAIL"
    assert k["stages"]["S2"]["status"] == "PASS"


def test_7_wrong_scope_still_fails_on_the_live_shape(live_shape):
    _, _, ev = live_shape
    k = child(ev, "fixture-wrong-scope")
    pop = next(c for c in k["checks"] if c["check_id"] == "S1S2-POP")
    assert pop["outcome"] == "FAIL"
    top = next(c for c in k["claims"] if c["claim_id"] == "top")
    assert top["verification_status"] == "CONTRADICTED"
    assert k["stages"]["S4"]["status"] == "PARTIAL"


def test_repair_chain_uses_frozen_submissions_on_the_live_shape(
        live_shape):
    _, _, ev = live_shape
    rep = child(ev, "fixture-repair")["repair"]
    assert (rep["opportunities"], rep["valid_repairs"]) == (1, 1)
    diff = rep["chains"][0]["diff"]
    assert diff and "stage2_exposure" in diff["before"]
    assert "stage2_exposure" not in diff["after"]
