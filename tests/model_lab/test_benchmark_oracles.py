"""Independent oracles Q01-Q15: correctness, independence, injected errors,
no leakage. Offline; no model is called.

Wrong candidates are built HERE, with pandas code written separately from
the oracle module, so the grader is tested against independently produced
mistakes rather than against its own diagnostic references.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from conftest import child, make_service, run

from backend.model_lab import assistance, registry
from backend.model_lab import benchmark_oracles as bo
from backend.model_lab import benchmark_questions as bq
from backend.model_lab import oracle as oracle_v2

FAC = bo._frames(bo.RELEASE)[0]
BOR = bo._frames(bo.RELEASE)[1]
L, P = bo._frames(bo.RELEASE)[2], bo._frames(bo.RELEASE)[3]


def rows(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))


def fac(q=None, stage=None):
    d = FAC
    if q is not None:
        d = d[d.reporting_quarter == q]
    if stage is not None:
        d = d[d.stage == stage]
    return d


# ---- 1. Q01 unchanged, all oracles deterministic and versioned -------------

def test_q01_is_the_existing_oracle_unchanged():
    task = oracle_v2.TASKS[0]
    old = oracle_v2.expected(task, bo.RELEASE)["values"]
    new = {r["sector"]: r["ead_sar_mn"] for r in
           bo.expected("Q01")["tables"][0]["rows"]}
    assert set(old) == set(new)
    assert all(abs(old[k] - new[k]) < 1e-6 for k in old)
    assert abs(new["Construction"] - 1016613.64) < 0.005


def test_every_question_has_a_versioned_deterministic_oracle(tmp_path):
    assert set(bo.ORACLES) == {q.qid for q in bq.QUESTIONS}
    a = bo.materialize(tmp_path / "a")
    bo._compute.cache_clear()
    b = bo.materialize(tmp_path / "b")
    assert a == b                                        # byte-identical
    man = json.loads((tmp_path / "a" / "ORACLE_MANIFEST.json").read_text())
    assert man["oracle_version"] == bo.ORACLE_SUITE_VERSION
    assert man["data_snapshot_id"].startswith(bo.RELEASE + "@")
    assert len(man["code_sha256"]) == 64
    for qid in bo.ORACLES:
        e = bo.expected(qid)
        assert e["spec"]["tolerances"] and e["spec"]["materiality"]
        assert e["data_snapshot_id"] == man["data_snapshot_id"]
        assert e["tables"] or e["facts"]


def test_oracles_are_independent_of_the_engine_and_of_models():
    tree = ast.parse(Path(bo.__file__).read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported |= {f"{n.module}.{a.name}" for a in n.names}
        elif isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
    engine = {m for m in imported if m.startswith("backend.cockpit_v4")}
    assert engine <= {"backend.cockpit_v4.lake",
                      "backend.cockpit_v4.analytical_runtime"}
    text = Path(bo.__file__).read_text()
    for forbidden in ("duckdb", "execute_tool", "orchestration",
                      "submissions", "final_response", "opus"):
        assert forbidden not in text.lower().replace(
            "no oracle results, no other", ""), forbidden


def test_q04_bridge_reconciles_and_causes_are_not_facts():
    e = bo.expected("Q04")
    f = {x["fact_id"]: x["value"] for x in e["facts"]}
    bridge = (f["inflow_from_stage1_ead"] + f["inflow_from_stage3_ead"]
              - f["outflow_to_stage1_ead"] - f["outflow_to_stage3_ead"]
              + f["new_stage2_ead"] - f["exited_stage2_ead"]
              + f["stayer_balance_change"])
    assert abs(bridge - f["stage2_ead_change"]) < 1e-3
    assert "UNVERIFIABLE" in e["causal"]


def test_q09_has_components_but_no_overall_winner():
    e = bo.expected("Q09")
    assert e["no_overall_winner"] is True
    cols = e["tables"][0]["metrics"]
    assert not any("rank" in c or "score" in c for c in cols)


# ---- 2. injected errors ------------------------------------------------------

def _q01_candidate(d):
    return rows(d.groupby("sector", as_index=False).agg(
        total=("ead_sar_mn", "sum")).sort_values("total", ascending=False))


def test_correct_candidate_passes():
    g = bo.grade_table("Q01", "stage2_ead_by_sector",
                       _q01_candidate(fac(L, 2)))
    assert g["outcome"] == "PASS"


def test_wrong_quarter_fails():
    g = bo.grade_table("Q01", "stage2_ead_by_sector",
                       _q01_candidate(fac(P, 2)))
    assert g["outcome"] == "FAIL" and "WRONG_QUARTER" in g["diagnosis"]


@pytest.mark.parametrize("stage", [1, 3])
def test_wrong_stage_fails(stage):
    g = bo.grade_table("Q01", "stage2_ead_by_sector",
                       _q01_candidate(fac(L, stage)))
    assert g["outcome"] == "FAIL"
    assert f"WRONG_STAGE_{stage}" in g["diagnosis"]


def test_missing_quarter_filter_fails():
    g = bo.grade_table("Q01", "stage2_ead_by_sector",
                       _q01_candidate(fac(None, 2)))
    assert g["outcome"] == "FAIL" and "NO_QUARTER_FILTER" in g["diagnosis"]


def test_missing_quarter_join_key_inflates_and_fails():
    """Join facility to borrower on borrower_id ONLY (all quarters)."""
    j = fac(L, 2).merge(BOR[["borrower_id", "rating_current"]],
                        on="borrower_id")
    g = bo.grade_table("Q01", "stage2_ead_by_sector", _q01_candidate(j))
    assert g["outcome"] == "FAIL"
    assert {"DUPLICATE_JOIN_INFLATION", "VALUES_INFLATED"} & \
        set(g["diagnosis"])


def test_duplicate_rows_fail():
    c = _q01_candidate(fac(L, 2))
    g = bo.grade_table("Q01", "stage2_ead_by_sector", c + c[:2])
    assert g["outcome"] == "FAIL" and "DUPLICATE_ROWS" in g["diagnosis"]


def test_wrong_metric_fails():
    d = fac(L, 2).groupby("sector", as_index=False).agg(
        ecl=("ecl_sar_mn", "sum"))
    g = bo.grade_table("Q01", "stage2_ead_by_sector", rows(d))
    assert g["outcome"] == "FAIL"


def test_q02_distinct_count_vs_row_count_on_join_fails():
    d = fac(L, 2).merge(BOR[BOR.reporting_quarter == L][["borrower_id"]],
                        on="borrower_id")
    ok = rows(d.groupby("sector", as_index=False).agg(
        n=("facility_id", "nunique")).sort_values("n", ascending=False))
    assert bo.grade_table("Q02", "stage2_facilities_by_sector",
                          ok)["outcome"] == "PASS"
    jj = fac(L, 2).merge(BOR[["borrower_id"]], on="borrower_id")
    bad = rows(jj.groupby("sector", as_index=False).agg(
        n=("facility_id", "count")))
    assert bo.grade_table("Q02", "stage2_facilities_by_sector",
                          bad)["outcome"] == "FAIL"


def _q08(d):
    e = d.groupby("borrower_id", as_index=False).agg(
        ead=("ead_sar_mn", "sum"))
    b = BOR[BOR.reporting_quarter == L][["borrower_id", "sector",
                                        "rating_current"]]
    return e.merge(b, on="borrower_id").sort_values("ead", ascending=False)


def test_top_n_correct_passes_and_wrong_top_n_fails():
    full = _q08(fac(L, 2))
    assert bo.grade_table("Q08", "top10_stage2_borrowers",
                          rows(full.head(10)))["outcome"] == "PASS"
    g = bo.grade_table("Q08", "top10_stage2_borrowers", rows(full.head(9)))
    assert g["outcome"] == "FAIL" and "WRONG_TOP_N" in g["diagnosis"]
    swapped = full.head(10).iloc[[1, 0, 2, 3, 4, 5, 6, 7, 8, 9]]
    g = bo.grade_table("Q08", "top10_stage2_borrowers", rows(swapped))
    assert g["outcome"] == "FAIL" and "WRONG_ORDER" in g["diagnosis"]
    g = bo.grade_table("Q08", "top10_stage2_borrowers",
                       rows(_q08(fac(L, None)).head(10)))
    assert g["outcome"] == "FAIL"                  # all stages, not Stage 2


def test_q07_transition_matrix_and_wrong_pairing():
    a = fac(P)[["facility_id", "stage"]]
    b = fac(L)[["facility_id", "stage", "ead_sar_mn"]]
    m = a.merge(b, on="facility_id", suffixes=("_from", "_to"))
    ok = m.groupby(["stage_from", "stage_to"], as_index=False).agg(
        n=("facility_id", "count"), ead=("ead_sar_mn", "sum"))
    assert bo.grade_table("Q07", "stage_transition_matrix",
                          rows(ok))["outcome"] == "PASS"
    # a common mistake: both sides read from the latest quarter
    same = b.merge(b[["facility_id", "stage"]], on="facility_id",
                   suffixes=("_to", "_from"))
    bad = same.groupby(["stage_from", "stage_to"], as_index=False).agg(
        n=("facility_id", "count"), ead=("ead_sar_mn", "sum"))
    assert bo.grade_table("Q07", "stage_transition_matrix",
                          rows(bad))["outcome"] == "FAIL"


def test_unreconciled_total_is_not_accepted_as_a_fact():
    total = bo.expected("Q11")["facts"][0]["value"]
    good, off = bo.check_facts("Q11", [(total, "money"),
                                       (total + 125.0, "money")])
    assert good["status"] == "CONSISTENT_WITH_ORACLE"
    assert off["status"] == "NOT_IN_ORACLE_FACTS"


# ---- 3. end to end through the frozen engine (scripted fixture) -----------

def _scripted(pid, sql):
    base = registry.load_profiles()["fixture-reference"].raw
    return registry._validate(base | {"profile_id": pid, "fixture_behaviour":
                                      "scripted_sql", "fixture_sql": sql},
                              Path(f"{pid}.json"))


LATEST = ("(SELECT MAX(reporting_quarter) FROM corp_facility_quarter)")


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    q08_ok = f"""
WITH f AS (SELECT borrower_id, SUM(ead_sar_mn) AS ead
           FROM corp_facility_quarter
           WHERE stage = 2 AND reporting_quarter = {LATEST}
           GROUP BY borrower_id)
SELECT f.borrower_id, b.sector, b.rating_current, f.ead
FROM f JOIN corp_borrower_quarter b
  ON b.borrower_id = f.borrower_id
 AND b.reporting_quarter = {LATEST}
ORDER BY f.ead DESC LIMIT 10"""
    q08_nojoinkey = f"""
SELECT f.borrower_id, MAX(b.sector) AS sector, SUM(f.ead_sar_mn) AS ead
FROM corp_facility_quarter f JOIN corp_borrower_quarter b
  ON b.borrower_id = f.borrower_id
WHERE f.stage = 2 AND f.reporting_quarter = {LATEST}
GROUP BY f.borrower_id ORDER BY ead DESC LIMIT 10"""
    q06 = f"""
SELECT stage, sector, SUM(ecl_sar_mn) AS ecl FROM corp_facility_quarter
WHERE reporting_quarter = {LATEST} GROUP BY stage, sector"""
    profiles = registry.load_profiles() | {
        "fx-q08-ok": _scripted("fx-q08-ok", q08_ok),
        "fx-q08-dup": _scripted("fx-q08-dup", q08_nojoinkey),
        "fx-q06": _scripted("fx-q06", q06)}
    svc = make_service(tmp_path_factory.mktemp("lab"), profiles=profiles)
    _, e08 = run(svc, ["fx-q08-ok", "fx-q08-dup"], comparator="",
                 question=bq.get("Q08").text, benchmark_question_id="Q08")
    _, e06 = run(svc, ["fx-q06"], comparator="",
                 question=bq.get("Q06").text, benchmark_question_id="Q06")
    return svc, e08, e06


def _checks(k):
    return {c["check_id"]: c for c in k["checks"]}


def test_e2e_correct_join_passes_and_missing_quarter_key_fails(e2e):
    _, e08, _ = e2e
    ok, dup = child(e08, "fx-q08-ok"), child(e08, "fx-q08-dup")
    assert ok["execution_state"] == dup["execution_state"] == "COMPLETED"
    assert _checks(ok)["S1S2-POP"]["outcome"] == "PASS"
    c = _checks(dup)["S1S2-POP"]
    assert c["outcome"] == "FAIL"
    assert {"DUPLICATE_JOIN_INFLATION", "VALUES_INFLATED", "WRONG_ORDER",
            "WRONG_TOP_N"} & set(c["actual"]["diagnosis"])
    assert ok["stages"]["S2"]["status"] == "PASS"
    assert dup["stages"]["S2"]["status"] == "FAIL"
    assert c["expected"]["oracle_version"] == bo.ORACLE_SUITE_VERSION


def test_e2e_chart_requirement_is_evaluated_separately(e2e):
    _, _, e06 = e2e
    k = child(e06, "fx-q06")
    c = _checks(k)
    assert c["ORACLE-ecl_by_stage_sector"]["outcome"] == "PASS"
    assert c["S4-CHART"]["outcome"] == "FAIL"
    assert c["S4-CHART"]["actual"] == "NO_CHART_GENERATED"


def test_causal_claims_on_causal_limit_questions_are_unverifiable():
    from backend.model_lab.evaluate import _suite_claims
    claims = [{"claim_id": "c1", "claim_type": "causal",
               "verification_status": "UNSUPPORTED",
               "asserted_value": None}]
    checks: list[dict] = []
    _suite_claims(claims, checks, "Q04", {"data_snapshot_id": bo.RELEASE})
    assert claims[0]["verification_status"] == "UNVERIFIABLE"
    assert claims[0]["reviewer_status"] == "NEEDS_REVIEW"
    claims[0]["verification_status"] = "UNSUPPORTED"
    _suite_claims(claims, checks, "Q02", {"data_snapshot_id": bo.RELEASE})
    assert claims[0]["verification_status"] == "UNSUPPORTED"


# ---- 4. no oracle leakage --------------------------------------------------

def test_no_oracle_value_in_any_assistance_packet():
    for q in bq.QUESTIONS:
        text = assistance.render(assistance.build_packet(q.qid))
        leaks = [n for n in bo.oracle_numbers(q.qid) if n in text]
        assert not leaks, (q.qid, leaks[:5])


def test_no_oracle_value_in_provider_requests_outside_tool_results(e2e):
    """The only place an oracle-equal number may reach a model is inside a
    tool_result: the model's OWN executed query result. Never in system,
    user or assistance text."""
    from backend.model_lab import model_io
    svc, _, _ = e2e
    nums = bo.oracle_numbers("Q08") | bo.oracle_numbers("Q06")
    for cid in [r["comparison_id"] for r in svc.coord.store.list_comparisons(
            svc.cfg.tenant_id, 50)]:
        tr = model_io.build(svc.coord, cid, include_bodies=True)
        for ch in tr["children"]:
            for it in ch["timeline"]:
                req = ((it.get("views") or {}).get("engine_request") or {}
                       ).get("request") or {}
                if not req:
                    continue
                outside = json.dumps(req.get("system")) + json.dumps(
                    [m for m in req.get("messages") or []
                     if isinstance(m.get("content"), str)])
                for m in req.get("messages") or []:
                    if isinstance(m.get("content"), list):
                        outside += json.dumps([b for b in m["content"]
                                               if b.get("type") !=
                                               "tool_result"])
                assert not [n for n in nums if n in outside], it["call_id"]


def test_oracle_expected_values_are_not_in_the_spec_sent_to_children(e2e):
    svc, _, _ = e2e
    for r in svc.coord.store.list_comparisons(svc.cfg.tenant_id, 50):
        spec = r["spec_json"]
        for q in ("Q06", "Q08"):
            assert not [n for n in bo.oracle_numbers(q) if n in spec]


def test_questions_carry_no_answers():
    text = Path(bq.__file__).read_text()
    for q in bq.QUESTIONS:
        assert not [n for n in bo.oracle_numbers(q.qid) if n in text]
    assert "SELECT" not in text.upper().replace("SELECTED", "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
