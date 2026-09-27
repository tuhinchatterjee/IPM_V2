"""Aggregate metrics over completed turns. Pure functions over result rows."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def nums(values: Iterable[Any]) -> list[float]:
    return [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
            and not (isinstance(v, float) and math.isnan(v))]


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (k - lo)


def dist(values: Iterable[Any]) -> dict[str, Any]:
    v = nums(values)
    if not v:
        return {"n": 0}
    out = {"n": len(v), "mean": statistics.fmean(v), "median": statistics.median(v),
           "p50": pct(v, 0.5), "p75": pct(v, 0.75), "p90": pct(v, 0.9), "p95": pct(v, 0.95),
           "min": min(v), "max": max(v)}
    out["p99"] = pct(v, 0.99) if len(v) >= 100 else "n<100"
    return out


def rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def cv(values: list[float]) -> float | None:
    if len(values) < 2 or statistics.fmean(values) == 0:
        return None
    return round(statistics.pstdev(values) / statistics.fmean(values), 4)


def turn_rows(results: list[dict[str, Any]], phase: str = "core") -> list[dict[str, Any]]:
    return [r for r in results if r.get("record_type") == "turn" and r.get("phase") == phase]


def architecture_metrics(rows: list[dict[str, Any]], support: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    completed = [r for r in rows if r.get("terminal_state") or r.get("http_status")]
    passed = [r for r in rows if r.get("passed")]

    def cls(r: dict[str, Any]) -> str:
        return r.get("oracle_type", "")

    exact = [r for r in rows if cls(r) == "EXACT" and r.get("oracle_pass") is not None]
    analytical = [r for r in rows if cls(r) == "ANALYTICAL" and r.get("oracle_pass") is not None]
    behavioural = [r for r in rows if cls(r) == "BEHAVIOURAL"]
    claims = sum(int(r.get("claim_count") or 0) for r in rows)
    supported = sum(int(r.get("supported_claim_count") or 0) for r in rows)
    unsupported = sum(int(r.get("unsupported_claim_count") or 0) for r in rows)
    incorrect = sum(int(r.get("incorrect_claim_count") or 0) for r in rows)
    with_exec = [r for r in rows if int(r.get("analysis_submissions") or 0) > 0]
    needed = [r for r in with_exec if r.get("needed_repair")]
    clar_e = [r for r in rows if r.get("test_class") == "E_CLARIFICATION"]
    avoidable = [r for r in rows if r.get("clarification_observed") and r.get("behaviour_expected") == "ANSWER"]
    thread = [r for r in rows if r.get("test_class") == "D_THREAD" and int(r.get("turn_number") or 1) > 1]
    tot_in = nums(r.get("native_input_tokens") for r in rows)
    tot_out = nums(r.get("native_output_tokens") for r in rows)
    tot_all = nums(r.get("native_total_tokens") for r in rows)
    cost = sum(nums(r.get("cost_usd") for r in rows)) + sum(nums(s.get("cost_usd") for s in support))
    lat = nums(r.get("e2e_processing_ms") for r in rows)
    prov = sum(nums(r.get("provider_ms") for r in rows)) + sum(nums(r.get("token_count_call_ms") for r in rows))
    local = sum(nums(r.get("local_ms") for r in rows))
    fact_st = [s for r in rows for s in (r.get("fact_statuses") or [])]
    correct_total_tokens = sum(nums(r.get("native_total_tokens") for r in passed))
    return {
        "core_turns": n, "completed": len(completed), "passed": len(passed),
        "completion_rate": rate(len(completed), n), "pass_rate": rate(len(passed), n),
        "exact_oracle_pass_rate": rate(sum(1 for r in exact if r.get("oracle_pass")), len(exact)),
        "analytical_oracle_pass_rate": rate(sum(1 for r in analytical if r.get("oracle_pass")), len(analytical)),
        "behavioural_oracle_pass_rate": rate(sum(1 for r in behavioural if r.get("behaviour_ok")), len(behavioural)),
        "claims_total": claims, "supported_claim_rate": rate(supported, claims),
        "unsupported_claim_rate": rate(unsupported, claims), "incorrect_claims": incorrect,
        "numerical_error_rate": rate(sum(1 for r in rows if int(r.get("numeric_wrong") or 0) > 0 or int(r.get("incorrect_claim_count") or 0) > 0), n),
        "wrong_period_rate": rate(sum(1 for r in rows if "WRONG_PERIOD" in (r.get("fact_statuses") or [])), n),
        "wrong_population_rate": rate(sum(1 for r in rows if "WRONG_POPULATION" in (r.get("fact_statuses") or [])), n),
        "required_facts_total": len(fact_st),
        "required_facts_published": sum(1 for s in fact_st if s.startswith("PUBLISHED")),
        "required_facts_artifact_only": fact_st.count("ARTIFACT_ONLY"),
        "first_pass_execute_rate": rate(sum(1 for r in with_exec if r.get("first_pass_valid")), len(with_exec)),
        "repair_rate": rate(len(needed), len(with_exec)),
        "repair_success_rate": rate(sum(1 for r in needed if r.get("repair_succeeded")), len(needed)),
        "average_repairs": round(statistics.fmean([int(r.get("repairs") or 0) for r in with_exec]), 3) if with_exec else None,
        "clarification_rate": rate(sum(1 for r in rows if r.get("clarification_observed")), n),
        "avoidable_clarification_rate": rate(len(avoidable), n),
        "clarification_required_detected": rate(sum(1 for r in clar_e if r.get("clarification_class") == "CLARIFICATION_REQUIRED" and r.get("clarification_observed")),
                                                sum(1 for r in clar_e if r.get("clarification_class") == "CLARIFICATION_REQUIRED")),
        "domain_leakage_rate": rate(sum(1 for r in rows if r.get("domain_leak")), n),
        "thread_continuity_rate": rate(sum(1 for r in thread if r.get("passed")), len(thread)),
        "provider_transient_rate": rate(sum(1 for r in rows if r.get("root_cause") == "PROVIDER_TRANSIENT"), n),
        "deadline_failure_rate": rate(sum(1 for r in rows if r.get("root_cause") == "ARCH_DEADLINE"), n),
        "budget_termination_rate": rate(sum(1 for r in rows if r.get("root_cause") == "ARCH_BUDGET"), n),
        "input_tokens_total": sum(tot_in), "output_tokens_total": sum(tot_out), "total_tokens": sum(tot_all),
        "input_tokens": dist(tot_in), "output_tokens": dist(tot_out), "total_tokens_dist": dist(tot_all),
        "tokens_per_correct_answer": round(correct_total_tokens / len(passed), 1) if passed else None,
        "repair_tokens_total": sum(nums(r.get("repair_tokens") for r in rows)),
        "finalization_tokens_total": sum(nums(r.get("finalization_tokens_after_correct_artifact") for r in rows)),
        "static_context_tax": dist(r.get("static_context_tax") for r in rows),
        "history_tax": dist(r.get("history_tax") for r in rows),
        "tool_result_tax": dist(r.get("tool_result_tax") for r in rows),
        "latency_ms": dist(lat),
        "provider_time_share": round(prov / (prov + local), 4) if (prov + local) else None,
        "local_time_share": round(local / (prov + local), 4) if (prov + local) else None,
        "cost_total_usd": round(cost, 6),
        "cost_per_case_usd": round(cost / n, 6) if n else None,
        "cost_per_correct_case_usd": round(cost / len(passed), 6) if passed else None,
        "support_turns": len(support),
        "harness_transient_retries": sum(int(r.get("harness_transient_retries") or 0) for r in rows),
        "sdk_hidden_http_retries": sum(int(r.get("provider_retries") or 0) for r in rows),
        "rate_limit_events": sum(int(r.get("rate_limit_events") or 0) for r in rows),
        "token_reconciliation_rate": rate(sum(1 for r in rows if r.get("tokens_reconcile")), n),
    }


def by_class(rows: list[dict[str, Any]], key: str = "test_class") -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(key) or "")].append(r)
    out = {}
    for g, rs in sorted(groups.items()):
        out[g] = {"n": len(rs), "pass_rate": rate(sum(1 for r in rs if r.get("passed")), len(rs)),
                  "median_latency_ms": dist(r.get("e2e_processing_ms") for r in rs).get("median"),
                  "p95_latency_ms": dist(r.get("e2e_processing_ms") for r in rs).get("p95"),
                  "median_total_tokens": dist(r.get("native_total_tokens") for r in rs).get("median"),
                  "mean_total_tokens": dist(r.get("native_total_tokens") for r in rs).get("mean"),
                  "total_tokens": sum(nums(r.get("native_total_tokens") for r in rs)),
                  "cost_usd": round(sum(nums(r.get("cost_usd") for r in rs)), 6),
                  "mean_model_calls": dist(r.get("model_calls") for r in rs).get("mean")}
    return out


QUESTION_TYPE_TAGS = [("ranking", ("ranking", "top", "bottom", "top N")),
                      ("comparison", ("QoQ", "MoM", "YoY", "previous period", "period")),
                      ("analytical", ("attribution", "contribution", "stock vs rate", "multi-condition",
                                      "threshold", "concentration", "migration", "driver table"))]


def question_type(row: dict[str, Any], bank: dict[str, dict[str, Any]]) -> str:
    case = bank.get(row["case_id"], {})
    tc = row.get("test_class", "")
    if tc == "B_PARAPHRASE":
        return "paraphrase"
    if tc == "D_THREAD":
        return "multi-turn"
    if tc == "E_CLARIFICATION":
        return "clarification"
    if tc == "F_GOVERNANCE":
        return "guardrail"
    tags = set(case.get("tags") or [])
    for name, keys in QUESTION_TYPE_TAGS[::-1]:
        if tags & set(keys):
            return name
    return "simple factual"


def paraphrase_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("paraphrase_group"):
            groups[r["paraphrase_group"]].append(r)
    out = []
    for g, rs in sorted(groups.items()):
        rs = sorted(rs, key=lambda r: r["case_id"])
        domains = {r.get("domain_actual") for r in rs}
        periods = {r.get("reporting_period_actual") for r in rs}
        oracle = [r.get("oracle_pass") for r in rs]
        statuses = [tuple(r.get("fact_statuses") or []) for r in rs]
        all_pass = all(o is True for o in oracle)
        any_pass = any(o is True for o in oracle)
        if all_pass and len(domains) == 1 and len(periods) <= 1:
            cls = "INVARIANT"
        elif all_pass:
            cls = "PRESENTATION_ONLY_VARIATION"
        elif any_pass:
            cls = "MATERIAL_ANALYTICAL_VARIATION"
        elif all(all(s in ("ARTIFACT_ONLY",) or s.startswith("PUBLISHED") for s in st) and st for st in statuses):
            cls = "PRESENTATION_ONLY_VARIATION"
        else:
            cls = "FAIL"
        out.append({"paraphrase_group": g, "members": [r["case_id"] for r in rs],
                    "questions": [r["question"] for r in rs], "classification": cls,
                    "domains": sorted(d for d in domains if d), "sql_periods": sorted(p for p in periods if p),
                    "oracle_pass": oracle, "fact_statuses": [list(s) for s in statuses],
                    "root_causes": [r.get("root_cause") for r in rs],
                    "total_tokens": [r.get("native_total_tokens") for r in rs],
                    "latency_ms": [r.get("e2e_processing_ms") for r in rs]})
    return out


def repeatability_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("repeatability_group"):
            groups[r["repeatability_group"]].append(r)
    out = []
    for g, rs in sorted(groups.items()):
        rs = sorted(rs, key=lambda r: r["case_id"])
        oracle = [r.get("oracle_pass") for r in rs]
        pubs = [sorted(round(x, 6) for x in (r.get("published_numbers") or [])) for r in rs]
        tok = nums(r.get("native_total_tokens") for r in rs)
        lat = nums(r.get("e2e_processing_ms") for r in rs)
        seqs = [tuple(r.get("tool_sequence") or []) for r in rs]
        sqls = [tuple(r.get("sql_digests") or []) for r in rs]
        out.append({"repeatability_group": g, "members": [r["case_id"] for r in rs],
                    "numerical_stability": all(o is True for o in oracle) or len({str(o) for o in oracle}) == 1 and oracle[0] is not False,
                    "all_oracle_pass": all(o is True for o in oracle),
                    "period_stability": len({r.get("reporting_period_actual") for r in rs}) == 1,
                    "population_stability": len({tuple(r.get("fact_statuses") or []) for r in rs}) == 1,
                    "sql_plan_identical": len(set(sqls)) == 1,
                    "distinct_sql_plans": len(set(sqls)),
                    "tool_sequence_identical": len(set(seqs)) == 1,
                    "published_numbers_identical": all(p == pubs[0] for p in pubs),
                    "token_cv": cv(tok), "latency_cv": cv(lat),
                    "tokens": [r.get("native_total_tokens") for r in rs],
                    "latency_ms": [r.get("e2e_processing_ms") for r in rs],
                    "model_calls": [r.get("model_calls") for r in rs]})
    return out


def thread_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("test_class") == "D_THREAD":
            threads[r["case_id"].split("-")[1]].append(r)
    for t, rs in sorted(threads.items()):
        rs = sorted(rs, key=lambda r: int(r["turn_number"]))
        inputs = [r.get("native_input_tokens") for r in rs]
        hist = [r.get("estimated_history_tokens") for r in rs]
        lat = [r.get("e2e_processing_ms") for r in rs]
        vin = nums(inputs)
        growth = [round(vin[i] - vin[i - 1], 1) for i in range(1, len(vin))] if len(vin) == len(inputs) else []
        out.append({"thread": t, "turns": len(rs), "passed_turns": sum(1 for r in rs if r.get("passed")),
                    "continuity_rate_turns_2_5": rate(sum(1 for r in rs[1:] if r.get("passed")), len(rs[1:])),
                    "domain_leaks": sum(1 for r in rs if r.get("domain_leak")),
                    "stale_context_turns": sum(1 for r in rs if int(r["turn_number"]) > 1 and (
                        "WRONG_PERIOD" in (r.get("fact_statuses") or []) or "WRONG_POPULATION" in (r.get("fact_statuses") or []))),
                    "input_tokens_by_turn": inputs, "history_tokens_by_turn": hist,
                    "token_growth_per_turn": growth,
                    "latency_ms_by_turn": lat, "results_by_turn": [r.get("root_cause") for r in rs]})
    return out


def top(rows: list[dict[str, Any]], key: str, n: int = 20) -> list[dict[str, Any]]:
    valid = [r for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
    valid.sort(key=lambda r: r[key], reverse=True)
    return valid[:n]


def explain_outlier(r: dict[str, Any]) -> str:
    bits = []
    if int(r.get("model_calls") or 0) >= 4:
        bits.append(f"{r['model_calls']} model calls")
    if int(r.get("repairs") or 0):
        bits.append(f"{r['repairs']} repair(s)")
    if int(r.get("catalog_calls") or 0) >= 2:
        bits.append(f"{r['catalog_calls']} catalogue reads")
    if int(r.get("finalizer_errors") or 0):
        bits.append(f"{r['finalizer_errors']} finalizer rejection(s)")
    if isinstance(r.get("history_tax"), float) and r["history_tax"] > 0.1:
        bits.append(f"history {r['history_tax']:.0%} of input")
    if isinstance(r.get("static_context_tax"), float):
        bits.append(f"static context {r['static_context_tax']:.0%} of input")
    if isinstance(r.get("tool_result_tax"), float) and r["tool_result_tax"] > 0.1:
        bits.append(f"tool results {r['tool_result_tax']:.0%} of input")
    if int(r.get("provider_retries") or 0):
        bits.append(f"{r['provider_retries']} hidden SDK retries")
    return "; ".join(bits) or "no single dominant driver"


def clusters(rows: list[dict[str, Any]], bank: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Repeated mechanisms among non-passing turns."""
    fails = [r for r in rows if not r.get("passed")]
    keyed: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in fails:
        statuses = tuple(sorted(set(s for s in (r.get("fact_statuses") or []) if not s.startswith("PUBLISHED"))))
        keyed[(r.get("root_cause"), r.get("error_code") or "", statuses)].append(r)
    out = []
    for (cause, code, statuses), rs in sorted(keyed.items(), key=lambda kv: -len(kv[1])):
        domains = sorted({r.get("domain_expected") for r in rs})
        classes = sorted({r.get("test_class") for r in rs})
        sev = sorted({r.get("severity") for r in rs if r.get("severity")},
                     key=["CRITICAL", "HIGH", "MEDIUM", "LOW", "EFFICIENCY"].index)
        out.append({"root_cause": cause, "error_code": code, "fact_statuses": list(statuses),
                    "count": len(rs), "case_ids": [r["case_id"] for r in rs], "domains": domains,
                    "test_classes": classes, "worst_severity": sev[0] if sev else "",
                    "layer": LAYER.get(str(cause), "unknown"),
                    "reproducible": _reproducible(rs, rows),
                    "sample_evidence": [e for r in rs[:3] for e in (r.get("root_cause_evidence") or [])][:5]})
    return out


def _reproducible(fails: list[dict[str, Any]], rows: list[dict[str, Any]]) -> str:
    groups = {r.get("repeatability_group") for r in fails if r.get("repeatability_group")} | \
             {r.get("paraphrase_group") for r in fails if r.get("paraphrase_group")}
    if not groups:
        return "single occurrence per case; no repeat group" if len(fails) == 1 else "multiple distinct cases"
    rep = [r for r in rows if r.get("repeatability_group") in groups or r.get("paraphrase_group") in groups]
    failed = sum(1 for r in rep if not r.get("passed"))
    return f"{failed}/{len(rep)} runs in the affected repeat/paraphrase groups failed"


LAYER = {"ARCH_ROUTING": "architecture: routing", "ARCH_CONTEXT": "architecture: context/memory",
         "ARCH_CONTRACT": "architecture: tool/prompt contract", "ARCH_VALIDATION": "architecture: validation",
         "ARCH_REPAIR_LOOP": "architecture: repair", "ARCH_BUDGET": "architecture: budgeting",
         "ARCH_DEADLINE": "architecture: deadlines", "ARCH_TOKEN_OVERHEAD": "architecture: token overhead",
         "ARCH_ORCHESTRATION": "architecture: orchestration", "MODEL_UNDERSTANDING": "model: understanding",
         "MODEL_CODE": "model: SQL/Python", "MODEL_TOOL_USE": "model: tool use", "MODEL_REPAIR": "model: repair",
         "MODEL_PRESENTATION": "model: answer presentation", "DATA_CATALOG": "data/catalogue",
         "ORACLE_DEFECT": "certification oracle", "PROVIDER_TRANSIENT": "provider/transient"}
