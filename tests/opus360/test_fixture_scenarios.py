"""
§27 pre-live fixture validation: ten scripted paths through the REAL engine.

MODEL MOCK · REAL ROUTE · REAL WORKER · REAL VALIDATOR/EXECUTOR/FINALIZER.
Each scenario proves that the harness captures what happened and classifies it
correctly. No paid call is possible: the provider is scripted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cert import oracles as orc
from cert import protected, scripted
from cert.ledger import Experiment
from cert.runner import Guards, Price, Runner
from cert.scripted import ScriptedProvider, ScriptedResult, final, intent, tool_call  # frozen test helpers

S2_BY_SECTOR = {"fn": "by_dim", "dim": "sector", "metrics": ["ead_s2"]}
TOP3 = {"fn": "by_dim", "dim": "sector", "metrics": ["ead_s2"], "rank_by": "ead_s2", "topn": 3}


def case(cid: str, question: str, oracle: dict, *, expected: str = "ANSWER", thread: str = "",
         turn: int = 1, fresh: bool = True, **extra) -> dict[str, Any]:
    row = {"case_id": cid, "family_id": cid, "domain": "corporate", "question": question,
           "test_class": extra.pop("test_class", "A_BASELINE"), "thread_id": thread or f"T-{cid}",
           "turn_number": turn, "fresh_thread": fresh, "oracle_type": "EXACT" if oracle.get("fn") != "none" else "BEHAVIOURAL",
           "expected_behavior": expected, "difficulty": "simple", "paraphrase_group": "",
           "repeatability_group": "", "tags": [], "notes": "", "oracle": oracle,
           "acceptable_behaviours": {"ANSWER": ["ANSWER"], "CLARIFY": ["CLARIFY"]}[expected]}
    row.update(extra)
    return row


def run(harness, tmp_path: Path, cases: list[dict], factory) -> tuple[Experiment, list[dict]]:
    exp = Experiment(tmp_path / "exp")
    exp.create({"experiment_id": "fixture", "live": False, "frozen_commit": "x"})
    refs = {}
    for c in cases:
        refs[f"{c['case_id']}:primary"] = orc.compute(c["oracle"], c["domain"])
        if c.get("followup_oracle"):
            refs[f"{c['case_id']}:followup"] = orc.compute(c["followup_oracle"], c["domain"])
    runner = Runner(exp, harness, harness.recorder, bank_rows=cases, refs=refs,
                    price=Price(5.0, 25.0, 6.25, 0.5), guards=Guards(live=False, max_usd=None, max_hours=None),
                    live=False, script_factory=factory, echo=False,
                    protected_manifest_sha=protected.verify().manifest_sha256)
    runner.run_phase("core", cases)
    rows = [r for r in exp.results() if r.get("record_type") == "turn"]
    return exp, rows


def execute(sqls: list[str], question: str = "q") -> ScriptedResult:
    return ScriptedResult(tool_calls=[tool_call("execute_analysis",
                                                scripted._execute_payload(question, sqls, "corporate"), "tu-x")])


def _steps_from(messages) -> list[dict]:
    for m in reversed(messages):
        content = m.get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                try:
                    body = json.loads(block["content"])
                except (TypeError, ValueError):
                    continue
                if isinstance(body, dict) and body.get("steps") and any(s.get("artifact_id") for s in body["steps"]):
                    return body["steps"]
    return []


def answer(ref: orc.Reference, *, break_column: bool = False):
    def build(messages):
        claims, tables = scripted.bind_claims(ref, _steps_from(messages))
        if break_column and claims:
            claims[0] = dict(claims[0], evidence=dict(claims[0]["evidence"], column_id="no_such_column"))
        narrative = "Result: " + " ".join(f"{{{{claim.{c['claim_id']}}}}}" for c in claims)
        return ScriptedResult(tool_calls=[tool_call("finalize_response", final(
            intent=intent("DATA_ANALYSIS", "COCKPIT"), disposition="answer", narrative=narrative,
            numeric_claims=claims, tables=tables))])
    return build


def decline(text: str = "CreditProbe could not compute this from the governed data.") -> ScriptedResult:
    return ScriptedResult(tool_calls=[tool_call("finalize_response", final(
        intent=intent("DATA_ANALYSIS", "COCKPIT"), disposition="unsupported", narrative=text))])


GOOD_SQL = scripted.sql_for(S2_BY_SECTOR, "corporate")
BAD_SQL = ["SELECT sector, SUM(no_such_column) AS x FROM corp_facility_quarter "
           "WHERE reporting_quarter = '2026Q2' GROUP BY sector"]
CROSS_DOMAIN_SQL = ["SELECT product, SUM(ead_sar_mn) AS ead FROM retail_account_month "
                    "WHERE reporting_month = '2026-08' GROUP BY product"]


def ref_of(spec: dict) -> orc.Reference:
    return orc.compute(spec, "corporate")


# ---- 1. one-pass success ---------------------------------------------------------------

def test_01_one_pass_success(harness, tmp_path):
    ref = ref_of(S2_BY_SECTOR)
    exp, rows = run(harness, tmp_path, [case("FX-01", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    lambda c, r, d, b, a: ScriptedProvider([execute(GOOD_SQL), answer(ref)]))
    row = rows[0]
    assert row["passed"] and row["root_cause"] == "PASS"
    assert row["first_pass_valid"] and row["repairs"] == 0 and row["analysis_submissions"] == 1
    assert row["model_calls"] == 2 and row["native_input_tokens"] == 2400 and row["native_output_tokens"] == 600
    assert row["tokens_reconcile"] is True
    assert row["cost_usd"] == pytest.approx(0.027) and row["cost_independent_usd"] == pytest.approx(0.027)
    assert row["numeric_published"] == row["numeric_required"] == 14
    assert row["tool_sequence"] == ["execute_analysis", "finalize_response"]
    assert isinstance(row["e2e_processing_ms"], int) and isinstance(row["provider_ms"], int)
    assert Path(row["evidence_dir"], "calls.json").exists()


# ---- 2. invalid analysis submission ------------------------------------------------------------

def test_02_invalid_submission_is_recorded(harness, tmp_path):
    exp, rows = run(harness, tmp_path, [case("FX-02", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    lambda c, r, d, b, a: ScriptedProvider([execute(BAD_SQL), decline(), decline(), decline()]))
    row = rows[0]
    assert not row["passed"]
    assert row["first_pass_valid"] is False and row["analysis_submissions"] >= 1
    assert row["validation_errors"] + row["execution_errors"] >= 1
    assert row["root_cause"] in ("MODEL_CODE", "MODEL_REPAIR"), row["root_cause_evidence"]
    subs = json.loads(Path(row["evidence_dir"], "submissions.json").read_text())
    assert "no_such_column" in json.dumps(subs)


# ---- 3. validation refusal (cross-domain relation) -------------------------------------------------

def test_03_validation_refusal(harness, tmp_path):
    exp, rows = run(harness, tmp_path, [case("FX-03", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    lambda c, r, d, b, a: ScriptedProvider([execute(CROSS_DOMAIN_SQL), decline(), decline(), decline()]))
    row = rows[0]
    assert not row["passed"]
    events = json.loads(Path(row["evidence_dir"], "events.json").read_text())
    refused = [e for e in events if e["event_type"] == "tool.failed" and e.get("stage") == "validating"]
    assert refused, "the validator's refusal must be in the captured events"
    assert row["validation_errors"] >= 1 and row["submission_statuses"][0] == "rejected"
    assert row["domain_leak"] is True or row["root_cause"] in ("MODEL_CODE", "MODEL_REPAIR", "ARCH_CONTEXT")


# ---- 4. repair then success ---------------------------------------------------------------------

def test_04_repair_then_success(harness, tmp_path):
    ref = ref_of(S2_BY_SECTOR)
    exp, rows = run(harness, tmp_path, [case("FX-04", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    lambda c, r, d, b, a: ScriptedProvider([execute(BAD_SQL), execute(GOOD_SQL), answer(ref)]))
    row = rows[0]
    assert row["passed"], row["failure_reasons"]
    assert row["needed_repair"] and row["repairs"] == 1 and row["repair_succeeded"]
    assert row["first_pass_valid"] is False
    assert isinstance(row["repair_tokens"], (int, float)) and row["repair_tokens"] > 0
    assert row["timings"]["repair_ms"] >= 0


# ---- 5. repair then failure ----------------------------------------------------------------------

def test_05_repair_then_failure(harness, tmp_path):
    bads = [[f"SELECT sector, SUM(no_such_column_{i}) AS x FROM corp_facility_quarter "
             f"WHERE reporting_quarter = '2026Q2' GROUP BY sector"] for i in range(8)]
    exp, rows = run(harness, tmp_path, [case("FX-05", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    lambda c, r, d, b, a: ScriptedProvider([execute(x) for x in bads] + [decline()] * 4))
    row = rows[0]
    assert not row["passed"]
    assert row["needed_repair"] and not row["repair_succeeded"] and row["repairs"] >= 1
    assert row["root_cause"] in ("MODEL_REPAIR", "MODEL_CODE", "ARCH_REPAIR_LOOP"), (row["root_cause"], row["error_code"])


# ---- 6. clarification ------------------------------------------------------------------------------

def test_06_clarification_and_resume(harness, tmp_path):
    followup = {"fn": "by_dim", "dim": "sector", "metrics": ["ead"]}
    c = case("FX-06", "What is total exposure by sector in the latest quarter?", {"fn": "none"}, expected="CLARIFY",
             test_class="E_CLARIFICATION", clarification_class="CLARIFICATION_REQUIRED",
             clarification_followup="EAD, please.", followup_oracle=followup)

    def factory(cse, ref, domain, behaviour, attempt):
        return scripted.analyst_for(cse, ref, domain=domain, behaviour=behaviour)

    exp, rows = run(harness, tmp_path, [c], factory)
    row = rows[0]
    assert row["behaviour_observed"] == "CLARIFY" and row["passed"]
    assert row["clarification_resumed_passed"] is True
    support = [r for r in exp.results() if r.get("record_type") == "support"]
    assert [s["support_kind"] for s in support] == ["clarification-response"]
    assert support[0]["thread_real_id"] == row["thread_real_id"]


# ---- 7. finalization rejection, then corrected ------------------------------------------------------

def test_07_finalizer_rejection_then_corrected(harness, tmp_path):
    ref = ref_of(S2_BY_SECTOR)
    exp, rows = run(harness, tmp_path, [case("FX-07", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    lambda c, r, d, b, a: ScriptedProvider([execute(GOOD_SQL), answer(ref, break_column=True), answer(ref)]))
    row = rows[0]
    assert row["finalizer_errors"] == 1 and row["finalization_calls"] == 2
    assert row["passed"], row["failure_reasons"]
    assert row["terminal_state"] == "COMPLETED"


# ---- 8. wrong final numerical claim -------------------------------------------------------------------

def test_08_wrong_period_claim_is_caught(harness, tmp_path):
    prev = dict(S2_BY_SECTOR, period="prev")
    prev_ref = ref_of(prev)
    exp, rows = run(harness, tmp_path, [case("FX-08", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    lambda c, r, d, b, a: ScriptedProvider([execute(scripted.sql_for(prev, "corporate")), answer(prev_ref)]))
    row = rows[0]
    assert not row["passed"] and row["oracle_pass"] is False
    assert "WRONG_PERIOD" in row["fact_statuses"]
    assert row["root_cause"] == "MODEL_UNDERSTANDING"
    assert row["reporting_period_actual"] == "2026Q1"


# ---- 9. provider transient, harness retry ---------------------------------------------------------------

def test_09_provider_transient_is_retried_by_the_harness(harness, tmp_path):
    ref = ref_of(S2_BY_SECTOR)

    def factory(c, r, d, b, attempt):
        if attempt == 1:
            return ScriptedProvider([RuntimeError("Error code: 529 - overloaded_error: Overloaded"),
                                     RuntimeError("Error code: 529 - overloaded_error: Overloaded"),
                                     RuntimeError("Error code: 529 - overloaded_error: Overloaded")])
        return ScriptedProvider([execute(GOOD_SQL), answer(ref)])

    exp, rows = run(harness, tmp_path, [case("FX-09", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR)],
                    factory)
    row = rows[0]
    assert row["attempts"] == 2 and row["harness_transient_retries"] == 1
    assert row["passed"]
    first = json.loads((Path(row["evidence_dir"]).parent / "attempt-1" / "root_cause.json").read_text())
    assert first["primary"] == "PROVIDER_TRANSIENT"
    retries = [json.loads(line) for line in exp.events_path.read_text().splitlines()
               if '"transient_retry"' in line]
    assert len(retries) == 1


# ---- 10. thread continuation ---------------------------------------------------------------------------

def test_10_thread_continuation(harness, tmp_path):
    t1 = case("FX-10-1", "Show Stage 2 EAD by sector for the latest quarter.", S2_BY_SECTOR,
              thread="TFX10", turn=1, fresh=True, test_class="D_THREAD")
    t2 = case("FX-10-2", "Only show the top three.", TOP3, thread="TFX10", turn=2, fresh=False, test_class="D_THREAD")

    def factory(c, r, d, b, a):
        return scripted.analyst_for(c, r, domain=d, behaviour=b)

    exp, rows = run(harness, tmp_path, [t1, t2], factory)
    r1, r2 = rows
    assert r1["passed"] and r2["passed"], (r1["failure_reasons"], r2["failure_reasons"])
    assert r1["thread_real_id"] == r2["thread_real_id"] and r1["thread_real_id"]
    assert r2["estimated_history_tokens"] > 0 and r2["history_tax"] > 0
    assert r1["estimated_history_tokens"] == 0
    assert r2["ranking_ok"] is True
