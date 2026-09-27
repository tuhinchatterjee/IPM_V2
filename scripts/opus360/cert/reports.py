"""
Every dataset and report, generated from the experiment's persisted evidence.

Nothing here is written by hand after a run: each table and every sentence
that states a number is computed from case_results.jsonl and the evidence
files. When the experiment is a DRY RUN (scripted analyst), every report says
so in its first line, and no figure in it is presented as an Opus result.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cert import metrics as M
from cert import protected
from cert.ledger import Experiment, now_iso
from cert.observe import UNKNOWN
from cert.safe_io import read_jsonl, rows_to_xlsx, write_csv, write_text_atomic

STATIC_FINDINGS = [
    {"id": "S-01", "severity": "HIGH", "layer": "ARCH_CONTRACT",
     "title": "finalize_response disposition enum disagrees with the parser",
     "evidence": "contracts/finalize_response.schema.json offers ['answer','partial','referral','clarification','unsupported'] "
                 "to the model; contracts.py:56-58 DISPOSITIONS accepts 'partial_answer' and 'safe_failure' and rejects 'partial' "
                 "(contracts.py:1019-1024). A schema-compliant PARTIAL answer is refused and costs an answer correction; "
                 "'partial_answer' is never offered.",
     "live_signal": "answer.validated rejections whose problems contain 'disposition must be one of'"},
    {"id": "S-02", "severity": "MEDIUM", "layer": "ARCH_CONTRACT",
     "title": "answer-reserve prompt instructs an invalid disposition",
     "evidence": "orchestration.py:618 tells the model to use `cannot_answer`, which is in neither the tool schema nor DISPOSITIONS.",
     "live_signal": "runs that entered answer_reserve with executed=false and then failed ANSWER_VALIDATION"},
    {"id": "S-03", "severity": "MEDIUM", "layer": "ARCH_BUDGET",
     "title": "SDK retries are not disabled; up to 3 HTTP attempts per paid call are invisible to the ledger",
     "evidence": "backend/llm/anthropic_provider.py:327-328 builds anthropic.Anthropic(api_key, timeout) without max_retries; "
                 "anthropic 0.112.0 DEFAULT_MAX_RETRIES == 2 (verified). allow_retry=False only disables the adapter loop.",
     "live_signal": "http_attempts > 1 per converse call (model_calls.csv provider_retries)"},
    {"id": "S-04", "severity": "MEDIUM", "layer": "ARCH_BUDGET",
     "title": "each generation spends 3+ provider attempts against a 24-attempt limit",
     "evidence": "provider.py:232 (count_input), :332 (_converse.send) and :497 (ask) each call ledger.spend_provider_attempt(); "
                 "about 8 generations exhaust provider_attempts=24 before generation_attempts=12.",
     "live_signal": "runs ending CALL_LIMIT; budget.provider_attempts.used vs generation_attempts.used"},
    {"id": "S-05", "severity": "LOW", "layer": "ARCH_ORCHESTRATION",
     "title": "operator records redact every *token* count",
     "evidence": "run_store.redact() (run_store.py:1610) replaces any key containing 'token', so model.response_received details "
                 "and the call_report store '[redacted]' for token usage. Only reservations.usage keeps native counts.",
     "live_signal": "details bodies with '[redacted]' token keys"},
    {"id": "S-06", "severity": "LOW", "layer": "ARCH_ORCHESTRATION",
     "title": "served model id is never read",
     "evidence": "anthropic_provider.py:298 returns model=chosen (the requested id); message.model is discarded, so the product "
                 "cannot evidence which model served a call.",
     "live_signal": "served_models column (from the harness SDK shim) vs requested_model"},
    {"id": "S-07", "severity": "LOW", "layer": "ARCH_ORCHESTRATION",
     "title": "assistant turns persisted as Python repr strings",
     "evidence": "run_store.save_messages json.dumps(default=str) on SDK block objects (run_store.py:918).",
     "live_signal": "messages.json assistant content is a string beginning with a block class name"},
    {"id": "S-08", "severity": "LOW", "layer": "TEST_HYGIENE",
     "title": "the frozen regression suite rewrites tracked evidence files",
     "evidence": "Running tests/cockpit_v4 modifies docs/cockpit_v4/evidence/{dual_domain_performance,math_query_engine,"
                 "overnight_analytical_benchmark,performance,saudi_release_fingerprint}.json (restored by the harness).",
     "live_signal": "artifacts/opus360/regression/*.json tracked_files_written_by_suite_and_restored"},
    {"id": "S-09", "severity": "LOW", "layer": "ARCH_ORCHESTRATION",
     "title": "one worker thread per process; per-principal limit of 2 active runs",
     "evidence": "app.py:176-186 starts a single Worker.serve_forever thread; routes.py:328-335 returns 429 when a principal has 2 "
                 "active runs. Concurrency beyond 1 queues; beyond 2 is refused at admission.",
     "live_signal": "load_test.csv queue_wait_ms and admission_retries_429"},
    {"id": "S-10", "severity": "LOW", "layer": "TEST_HYGIENE",
     "title": "Round H live-UAT capture read event fields that do not exist",
     "evidence": "scripts/cockpit_v4/live_uat.py:587-589 reads e.created_at / e.body; Event has occurred_at / detail_ref, so the "
                 "Round H evidence file's event bodies were empty.",
     "live_signal": "n/a (historical evidence quality)"},
]


def _load_gz(path: str) -> Any:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _fmt(v: Any, pct: bool = False, money: bool = False) -> str:
    if v is None or v == UNKNOWN:
        return "n/a"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if money and isinstance(v, (int, float)):
        return f"${v:,.4f}"
    if pct and isinstance(v, (int, float)):
        return f"{v * 100:.1f}%"
    if isinstance(v, float) and v.is_integer() and abs(v) >= 1000:
        return f"{int(v):,}"
    if isinstance(v, float):
        return f"{v:,.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def build(exp: Experiment, bank_rows: list[dict[str, Any]]) -> dict[str, Path]:
    manifest = exp.manifest()
    live = bool(manifest.get("live"))
    banner = ("LIVE OPUS CERTIFICATION" if live else
              "DRY RUN — SCRIPTED ANALYST, NOT OPUS. Every figure below measures the HARNESS and the frozen "
              "deterministic pipeline driven by a scripted model. None of it is evidence about Opus.")
    results = read_jsonl(exp.results_path)
    bank = {r["case_id"]: r for r in bank_rows}
    core = M.turn_rows(results, "core")
    support = [r for r in results if r.get("record_type") == "support" and r.get("phase") == "core"]
    calib = M.turn_rows(results, "calibration")
    load = [r for r in results if r.get("record_type") == "load"]
    root = exp.root
    files: dict[str, Path] = {}

    # ---- datasets ---------------------------------------------------------------
    case_cols = ["case_id", "test_class", "question", "domain_expected", "domain_actual", "thread_key",
                 "thread_real_id", "turn_number", "reporting_period_expected", "reporting_period_actual",
                 "terminal_state", "error_code", "disposition", "behaviour_expected", "behaviour_observed",
                 "passed", "oracle_pass", "oracle_type", "numeric_required", "numeric_published",
                 "numeric_artifact_only", "numeric_wrong", "claim_count", "supported_claim_count",
                 "unsupported_claim_count", "incorrect_claim_count", "unverifiable_claim_count",
                 "omitted_required_claim_count", "e2e_processing_ms", "e2e_wall_ms", "queue_wait_ms", "provider_ms",
                 "token_count_call_ms", "local_ms", "model_calls", "token_count_calls", "native_input_tokens",
                 "native_output_tokens", "native_total_tokens", "estimated_system_tokens",
                 "estimated_tool_schema_tokens", "estimated_history_tokens", "estimated_tool_result_tokens",
                 "static_context_tax", "history_tax", "tool_result_tax", "repair_tokens",
                 "finalization_tokens_after_correct_artifact", "cost_usd", "cost_independent_usd",
                 "catalog_calls", "product_knowledge_calls", "analysis_submissions", "read_artifact_calls",
                 "finalization_calls", "first_pass_valid", "repairs", "clarification_observed",
                 "clarification_class", "validation_errors", "execution_errors", "finalizer_errors",
                 "provider_retries", "rate_limit_events", "harness_transient_retries", "root_cause",
                 "root_cause_secondary", "severity", "failure_reasons", "domain_leak", "served_models",
                 "tokens_reconcile", "evidence_dir"]
    write_csv(root / "case_results.csv", core, case_cols)
    files["case_results.csv"] = root / "case_results.csv"
    with open(root / "case_results.jsonl", "w", encoding="utf-8") as fh:
        for r in core + support:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    model_calls, tool_calls, subs, arts, claims, oracle_rows = [], [], [], [], [], []
    for r in core + calib:
        evdir = Path(r["evidence_dir"])
        calls = _read(evdir / "calls.json") or []
        for c in calls:
            model_calls.append({
                "experiment_id": manifest["experiment_id"], "phase": r["phase"], "case_id": r["case_id"],
                "thread": r.get("thread_key"), "turn_number": r.get("turn_number"), "kind": c.get("kind"),
                "seq": c.get("seq"), "purpose": c.get("purpose"), "started_at": c.get("started_at"),
                "finished_at": c.get("finished_at"), "elapsed_ms": c.get("elapsed_ms"),
                "provider_http_ms": c.get("http_ms"), "local_ms": c.get("local_ms"),
                "requested_model": c.get("requested_model"), "served_model": c.get("served_model"),
                "stop_reason": c.get("stop_reason"), "input_tokens": c.get("input_tokens"),
                "output_tokens": c.get("output_tokens"), "total_tokens": c.get("total_tokens"),
                "cache_read_tokens": c.get("cache_read_tokens"), "cache_write_tokens": c.get("cache_write_tokens"),
                "reasoning_tokens": c.get("reasoning_tokens"), "max_tokens": c.get("max_tokens"),
                "tool_choice": c.get("tool_choice"), "tools_exposed": c.get("tools_exposed"),
                "effort": c.get("effort"), "status": c.get("status"), "provider_retries": c.get("provider_retries"),
                "provider_error": c.get("error_text"), "rate_limit_events": c.get("rate_limit_events"),
                "counted_tokens": c.get("counted_tokens"), "context_bytes_total": (c.get("context_bytes") or {}).get("total")})
        tele = _read(evdir / "telemetry.json") or {}
        for t in tele.get("tools") or []:
            tool_calls.append({"case_id": r["case_id"], "phase": r["phase"], **t})
        details = _read(evdir / "details.json") or {}
        events = _read(evdir / "events.json") or []
        failed_by_sub: dict[str, dict[str, Any]] = {}
        for e in events:
            if e.get("event_type") == "tool.failed" and e.get("detail_ref"):
                body = details.get(e["detail_ref"]) or {}
                sid = str(body.get("submission_id") or e.get("submission") or "")
                failed_by_sub.setdefault(sid, body)
        messages = _read(evdir / "messages.json") or []
        step_ms: dict[str, Any] = {}
        for m in messages:
            for block in m.get("content") if isinstance(m.get("content"), list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    try:
                        body = json.loads(block.get("content") or "{}")
                    except (TypeError, ValueError):
                        continue
                    for st in body.get("steps") or [] if isinstance(body, dict) else []:
                        if st.get("artifact_id"):
                            step_ms[st["artifact_id"]] = st.get("elapsed_ms")
        artifacts = _read(evdir / "artifacts.json") or []
        for s in _read(evdir / "submissions.json") or []:
            payload = s.get("payload") or {}
            steps = payload.get("steps") or []
            fb = failed_by_sub.get(str(s.get("submission_id")), {})
            subs.append({"case_id": r["case_id"], "phase": r["phase"], "submission_id": s.get("submission_id"),
                         "attempt_number": s.get("ordinal"), "round": s.get("round"), "status": s.get("status"),
                         "repair_of": payload.get("repair_of_submission_id") or "",
                         "sql_statements": [st.get("code") for st in steps if st.get("language", "sql") == "sql"],
                         "python_steps": [st.get("code") for st in steps if st.get("language") == "python"],
                         "raw_submission": payload,
                         "validation_result": "rejected" if s.get("status") == "rejected" else "passed",
                         "failed_check": fb.get("failed_check", ""), "error_code": fb.get("error_code", ""),
                         "error_text": fb.get("message", ""), "failed_step": s.get("failed_step", ""),
                         "no_progress_key": s.get("no_progress_key")})
        for a in artifacts:
            scope = a.get("scope") or {}
            arts.append({"case_id": r["case_id"], "phase": r["phase"], "artifact_id": a.get("artifact_id"),
                         "run_id": a.get("run_id"), "kind": a.get("kind"), "release_id": a.get("release_id"),
                         "columns": a.get("columns"), "row_count": a.get("row_count"),
                         "produced_rows": scope.get("produced_rows"), "complete": scope.get("complete"),
                         "relations": scope.get("relations"), "domain_id": scope.get("domain_id"),
                         "code_digest": a.get("code_digest"), "created_at": a.get("created_at"),
                         "execution_ms": step_ms.get(a.get("artifact_id"), UNKNOWN)})
        verdict = _read(evdir / "verdict.json") or {}
        for c in verdict.get("claims") or []:
            claims.append({"case_id": r["case_id"], "phase": r["phase"], **c})
        for u in verdict.get("unbound") or []:
            claims.append({"case_id": r["case_id"], "phase": r["phase"], "claim_id": "(unbound narrative number)",
                           "value": u.get("value"), "display_value": u.get("raw"),
                           "status": "UNSUPPORTED_UNBOUND" + ("" if u.get("in_universe") else "_OUTSIDE_UNIVERSE"),
                           "matched_fact": "", "context": u.get("context")})
        for f in verdict.get("facts") or []:
            oracle_rows.append({"case_id": r["case_id"], "phase": r["phase"], **f})
        if verdict.get("ranking", {}).get("required"):
            oracle_rows.append({"case_id": r["case_id"], "phase": r["phase"], "fact_id": "RANKING",
                                "status": "OK" if verdict["ranking"].get("ok") else "FAIL",
                                "expected": verdict["ranking"].get("expected"),
                                "matched_value": verdict["ranking"].get("published")})
        if verdict.get("members", {}).get("required"):
            oracle_rows.append({"case_id": r["case_id"], "phase": r["phase"], "fact_id": "MEMBERSHIP",
                                "status": "OK" if verdict["members"].get("ok") else "FAIL",
                                "expected": verdict["members"].get("missing"),
                                "matched_value": verdict["members"].get("extra")})
    for name, rows in (("model_calls.csv", model_calls), ("tool_calls.csv", tool_calls),
                       ("submissions.csv", subs), ("artifacts.csv", arts), ("claims.csv", claims),
                       ("oracle_results.csv", oracle_rows)):
        write_csv(root / name, rows)
        files[name] = root / name

    threads = M.thread_metrics(core)
    para = M.paraphrase_metrics(core)
    rep = M.repeatability_metrics(core)
    fails = [{"case_id": r["case_id"], "test_class": r["test_class"], "domain": r["domain_expected"],
              "question": r["question"], "root_cause": r["root_cause"],
              "secondary": r.get("root_cause_secondary"), "severity": r.get("severity"),
              "layer": M.LAYER.get(r["root_cause"], ""), "failure_reasons": r.get("failure_reasons"),
              "evidence": r.get("root_cause_evidence"), "fact_statuses": r.get("fact_statuses"),
              "error_code": r.get("error_code"), "evidence_dir": r.get("evidence_dir")}
             for r in core if not r.get("passed")]
    write_csv(root / "thread_metrics.csv", threads)
    write_csv(root / "paraphrase_metrics.csv", para)
    write_csv(root / "repeatability_metrics.csv", rep)
    write_csv(root / "failure_analysis.csv", fails)
    timing_rows = []
    timing_keys = ["e2e_processing_ms", "e2e_wall_ms", "queue_wait_ms", "provider_ms", "token_count_call_ms",
                   "local_ms"]
    detail_keys = ["catalog_ms", "product_knowledge_ms", "analysis_validation_ms", "execution_ms",
                   "artifact_read_ms", "finalization_ms", "repair_ms", "time_to_first_successful_execute_ms",
                   "success_to_final_ms", "provider_retry_ms"]
    groups = {"ALL": core}
    for r in core:
        groups.setdefault(r["test_class"], []).append(r)
    for g, rs in groups.items():
        for k in timing_keys:
            timing_rows.append({"group": g, "metric": k, **M.dist(r.get(k) for r in rs)})
        for k in detail_keys:
            timing_rows.append({"group": g, "metric": k, **M.dist((r.get("timings") or {}).get(k) for r in rs)})
    write_csv(root / "timing_metrics.csv", timing_rows)
    token_rows = []
    for g, rs in groups.items():
        for k in ("native_input_tokens", "native_output_tokens", "native_total_tokens", "model_calls",
                  "estimated_system_tokens", "estimated_tool_schema_tokens", "estimated_history_tokens",
                  "estimated_tool_result_tokens", "static_context_tax", "history_tax", "tool_result_tax",
                  "repair_tokens", "finalization_tokens_after_correct_artifact"):
            token_rows.append({"row_type": "distribution", "group": g, "metric": k, **M.dist(r.get(k) for r in rs)})
    qt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in core:
        qt[M.question_type(r, bank)].append(r)
        qt[f"domain:{r['domain_expected']}"].append(r)
    for g, rs in sorted(qt.items()):
        token_rows.append({"row_type": "by_question_type", "group": g, "metric": "native_total_tokens",
                           **M.dist(r.get("native_total_tokens") for r in rs),
                           "sum": sum(M.nums(r.get("native_total_tokens") for r in rs))})
    comp_tot: Counter = Counter()
    for r in core:
        for k, v in (r.get("token_components_estimated") or {}).items():
            if isinstance(v, (int, float)):
                comp_tot[k] += v
    total_in = sum(comp_tot.values()) or 1
    for k, v in comp_tot.most_common():
        token_rows.append({"row_type": "component_share_ESTIMATED", "group": "ALL", "metric": k,
                           "sum": round(v, 1), "mean": round(v / total_in, 4)})
    write_csv(root / "token_metrics.csv", token_rows)
    cost_rows = [{"case_id": r["case_id"], "phase": r["phase"], "cost_product_ledger_usd": r.get("cost_usd"),
                  "cost_independent_usd": r.get("cost_independent_usd"), "cumulative_usd": r.get("cumulative_usd"),
                  "native_input_tokens": r.get("native_input_tokens"),
                  "native_output_tokens": r.get("native_output_tokens")}
                 for r in calib + core] + [{"case_id": s["case_id"], "phase": s["phase"],
                                            "cost_product_ledger_usd": s.get("cost_usd"), "support": True}
                                           for s in results if s.get("record_type") == "support"]
    write_csv(root / "cost_metrics.csv", cost_rows)
    write_csv(root / "load_test.csv", load)
    for name in ("thread_metrics.csv", "paraphrase_metrics.csv", "repeatability_metrics.csv",
                 "failure_analysis.csv", "timing_metrics.csv", "token_metrics.csv", "cost_metrics.csv",
                 "load_test.csv"):
        files[name] = root / name

    # question bank copy (immutable per experiment)
    bank_copy = root / "question_bank.yaml"
    if not bank_copy.exists():
        from cert.paths import BANK_PATH
        bank_copy.write_bytes(BANK_PATH.read_bytes())

    # ---- metrics + markdown ----------------------------------------------------------
    arch = M.architecture_metrics(core, support)
    cls = M.by_class(core)
    clus = M.clusters(core, bank)
    verdict = protected.verify(expected_manifest_sha=manifest.get("protected_manifest_sha256", ""))
    import subprocess

    from cert import FROZEN_COMMIT
    from cert.paths import ROOT
    diff = subprocess.run(["git", "diff", "--name-only", FROZEN_COMMIT, "--", *protected.PROTECTED_DIRS,
                           *protected.PROTECTED_FILES], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    proof = {"protected_manifest_ok": verdict.ok, "files_checked": verdict.checked_files,
             "problems": verdict.problems[:20], "git_diff_protected_paths": diff or "(empty)",
             "status": "PROTECTED_CORE_UNCHANGED" if (verdict.ok and not diff) else "INVALID_PROTECTED_CORE_CHANGED"}
    signals = live_signals(core, exp)
    state = exp.state()
    ctx = {"banner": banner, "manifest": manifest, "arch": arch, "cls": cls, "clusters": clus, "proof": proof,
           "threads": threads, "para": para, "rep": rep, "core": core, "load": load, "calib": calib,
           "signals": signals, "state": state, "bank": bank, "support": support}
    (root / "metrics.json").write_text(json.dumps({"architecture": arch, "by_class": cls, "clusters": clus,
                                                   "protected_proof": proof, "static_signals": signals},
                                                  indent=1, default=str), encoding="utf-8")
    write_text_atomic(root / "EXECUTIVE_SUMMARY.md", executive_summary(ctx))
    write_text_atomic(root / "ARCHITECTURE_CERTIFICATION_REPORT.md", certification_report(ctx))
    write_text_atomic(root / "ARCHITECTURE_FINDINGS.md", findings_report(ctx))
    write_text_atomic(root / "FREEZE_READINESS.md", freeze_readiness(ctx))
    for n in ("EXECUTIVE_SUMMARY.md", "ARCHITECTURE_CERTIFICATION_REPORT.md", "ARCHITECTURE_FINDINGS.md",
              "FREEZE_READINESS.md", "metrics.json"):
        files[n] = root / n

    summary_sheet = [{"metric": k, "value": (json.dumps(v, default=str) if isinstance(v, (dict, list)) else v)}
                     for k, v in arch.items()]
    rows_to_xlsx(root / "opus360_results.xlsx", [
        ("Summary", summary_sheet), ("Cases", [{k: r.get(k) for k in case_cols} for r in core]),
        ("Failures", fails), ("ModelCalls", model_calls), ("ToolCalls", tool_calls), ("Submissions", subs),
        ("Claims", claims), ("Oracle", oracle_rows), ("Threads", threads), ("Paraphrase", para),
        ("Repeatability", rep), ("Timing", timing_rows), ("Tokens", token_rows), ("Cost", cost_rows),
        ("LoadTest", load), ("Clusters", clus), ("StaticFindings", STATIC_FINDINGS)])
    files["opus360_results.xlsx"] = root / "opus360_results.xlsx"
    files["checksums.sha256"] = exp.write_checksums()
    return files


def live_signals(core: list[dict[str, Any]], exp: Experiment) -> dict[str, Any]:
    """Count live occurrences of each static finding's signal."""
    enum_rejections, reserve_entries, redacted_details, repr_messages = [], 0, 0, 0
    call_limit = [r["case_id"] for r in core if r.get("error_code") == "CALL_LIMIT"]
    for r in core:
        evdir = Path(r["evidence_dir"])
        events = _read(evdir / "events.json") or []
        details = _read(evdir / "details.json") or {}
        for e in events:
            if e.get("event_type") == "answer.validated" and e.get("status") == "rejected":
                body = json.dumps(details.get(e.get("detail_ref") or "", {}), default=str)
                if "disposition must be one of" in body:
                    enum_rejections.append(r["case_id"])
            if e.get("operation") == "answer_reserve":
                reserve_entries += 1
        redacted_details += sum(1 for b in details.values() if "[redacted]" in json.dumps(b, default=str))
        for m in _read(evdir / "messages.json") or []:
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                repr_messages += 1
    return {"S-01_disposition_enum_rejections": sorted(set(enum_rejections)),
            "S-02_answer_reserve_entries": reserve_entries,
            "S-03_hidden_sdk_retries": sum(int(r.get("provider_retries") or 0) for r in core),
            "S-04_call_limit_runs": call_limit,
            "S-05_redacted_detail_records": redacted_details,
            "S-06_served_models": sorted({m for r in core for m in (r.get("served_models") or [])}),
            "S-07_assistant_messages_as_strings": repr_messages}


# ---- markdown -------------------------------------------------------------------------

def _table(rows: list[tuple[str, str]], head: tuple[str, str] = ("Metric", "Result")) -> str:
    out = [f"| {head[0]} | {head[1]} |", "|---|---:|"]
    out += [f"| {a} | {b} |" for a, b in rows]
    return "\n".join(out)


def _sev_counts(core: list[dict[str, Any]]) -> dict[str, Counter]:
    arch, model, prov, other = Counter(), Counter(), Counter(), Counter()
    for r in core:
        if r.get("passed"):
            continue
        cause, sev = str(r.get("root_cause")), str(r.get("severity") or "")
        if cause.startswith("ARCH_"):
            arch[sev] += 1
        elif cause.startswith("MODEL_"):
            model[sev] += 1
        elif cause == "PROVIDER_TRANSIENT":
            prov[sev] += 1
        else:
            other[sev] += 1
    return {"arch": arch, "model": model, "provider": prov, "other": other}


def executive_summary(ctx: dict[str, Any]) -> str:
    a, core, m = ctx["arch"], ctx["core"], ctx["manifest"]
    sev = _sev_counts(core)
    planned = 250
    lines = [f"# Executive summary — {m['experiment_id']}", "", f"> **{ctx['banner']}**", "",
             f"Frozen commit `{m['frozen_commit']}` · model `{m.get('model')}` · protected core: "
             f"**{ctx['proof']['status']}** · generated {now_iso()}", ""]
    rows = [("Core user turns (planned)", str(planned)), ("Completed", _fmt(a["completed"])),
            ("Correct (all checks passed)", f"{a['passed']} ({_fmt(a['pass_rate'], pct=True)})"),
            ("Exact oracle pass", _fmt(a["exact_oracle_pass_rate"], pct=True)),
            ("Analytical oracle pass", _fmt(a["analytical_oracle_pass_rate"], pct=True)),
            ("Behavioural oracle pass", _fmt(a["behavioural_oracle_pass_rate"], pct=True)),
            ("Supported claims", _fmt(a["supported_claim_rate"], pct=True)),
            ("First-pass execute", _fmt(a["first_pass_execute_rate"], pct=True)),
            ("Repair rate", _fmt(a["repair_rate"], pct=True)),
            ("Paraphrase invariance", _fmt(M.rate(sum(1 for p in ctx["para"] if p["classification"] == "INVARIANT"), len(ctx["para"])), pct=True)),
            ("Thread continuity (turns 2-5)", _fmt(a["thread_continuity_rate"], pct=True)),
            ("Domain leakage", _fmt(a["domain_leakage_rate"], pct=True)),
            ("Input tokens", _fmt(a["input_tokens_total"])), ("Output tokens", _fmt(a["output_tokens_total"])),
            ("Total tokens", _fmt(a["total_tokens"])),
            ("Experiment cost (core + support)", _fmt(a["cost_total_usd"], money=True)),
            ("Median latency", f"{_fmt((a['latency_ms'].get('median') or 0) / 1000)} s"),
            ("P95 latency", f"{_fmt((a['latency_ms'].get('p95') or 0) / 1000)} s"),
            ("Critical architecture findings", str(sev["arch"].get("CRITICAL", 0))),
            ("High architecture findings", str(sev["arch"].get("HIGH", 0))),
            ("Model-specific findings", str(sum(sev["model"].values()))),
            ("Provider/transient findings", str(sum(sev["provider"].values())))]
    lines += [_table(rows), ""]
    by_cls = ctx["cls"]
    lines += ["## Top 10 things working well", ""]
    good = sorted(by_cls.items(), key=lambda kv: -(kv[1]["pass_rate"] or 0))
    n = 0
    for g, s in good:
        if s["pass_rate"] and n < 5:
            n += 1
            lines.append(f"{n}. **{g}**: {s['n']} turns, pass rate {_fmt(s['pass_rate'], pct=True)}, "
                         f"median {_fmt((s['median_latency_ms'] or 0) / 1000)} s.")
    extra = [("Token reconciliation (ledger vs provider-native)", a["token_reconciliation_rate"]),
             ("Supported-claim rate", a["supported_claim_rate"]),
             ("First-pass execute rate", a["first_pass_execute_rate"]),
             ("Clarification detection on genuinely ambiguous questions", a["clarification_required_detected"]),
             ("Absence of domain leakage", None if a["domain_leakage_rate"] is None else 1 - a["domain_leakage_rate"])]
    for label, val in extra:
        if n < 10 and val is not None:
            n += 1
            lines.append(f"{n}. **{label}**: {_fmt(val, pct=True)}.")
    lines += ["", "## Top 10 problems", ""]
    for i, c in enumerate(ctx["clusters"][:10], 1):
        lines.append(f"{i}. **{c['root_cause']}** ({c['worst_severity']}) × {c['count']}: "
                     f"{', '.join(c['case_ids'][:8])}{' …' if c['count'] > 8 else ''}. "
                     f"Layer: {c['layer']}. {'; '.join(c['sample_evidence'][:2])}")
    if not ctx["clusters"]:
        lines.append("No failing turns.")
    lines += ["", "## Top 10 token / latency observations", ""]
    obs = token_latency_observations(ctx)
    lines += [f"{i}. {o}" for i, o in enumerate(obs[:10], 1)]
    lines += ["", "## Architecture vs Opus", "",
              f"- Architecture-attributed failing turns: {sum(sev['arch'].values())} "
              f"({dict(sev['arch'])}).",
              f"- Model-attributed failing turns: {sum(sev['model'].values())} ({dict(sev['model'])}).",
              f"- Provider/transient: {sum(sev['provider'].values())}.",
              f"- Other (oracle/data/harness): {sum(sev['other'].values())}.",
              "- Attribution rules are mechanical (cert/evaluate.py `root_cause`); every row in "
              "failure_analysis.csv carries the evidence line that decided it.", "",
              "## What to investigate before freeze", ""]
    ranked = sorted(ctx["clusters"], key=lambda c: (["CRITICAL", "HIGH", "MEDIUM", "LOW", "EFFICIENCY", ""].index(
        c["worst_severity"] if c["worst_severity"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "EFFICIENCY") else ""), -c["count"]))
    for i, c in enumerate(ranked[:10], 1):
        lines.append(f"{i}. [{c['worst_severity']}] {c['layer']} — {c['count']} case(s): {', '.join(c['case_ids'][:6])}")
    lines += ["", "Static, code-verified findings (independent of any run) are listed in ARCHITECTURE_FINDINGS.md "
              "(S-01 … S-10) with their live signal counts.", ""]
    if not ctx["manifest"].get("live"):
        lines += ["---", "", "**This is a dry run.** To run the live Opus certification, see the command in "
                  "`docs/opus360/RUNBOOK.md` (it requires `OPUS360_MAX_USD` and the Cockpit credential)."]
    return "\n".join(lines) + "\n"


def token_latency_observations(ctx: dict[str, Any]) -> list[str]:
    a, core = ctx["arch"], ctx["core"]
    out = []
    comp: Counter = Counter()
    for r in core:
        for k, v in (r.get("token_components_estimated") or {}).items():
            if isinstance(v, (int, float)):
                comp[k] += v
    tot = sum(comp.values())
    if tot:
        top3 = ", ".join(f"{k} {v / tot:.0%}" for k, v in comp.most_common(3))
        out.append(f"Input-token composition (ESTIMATED, byte share of native totals): {top3}.")
    st = a["static_context_tax"]
    if st.get("n"):
        out.append(f"Static context tax (system + tool schema ÷ input): median {st['median']:.0%}, p95 {st['p95']:.0%}.")
    ht = a["history_tax"]
    if ht.get("n"):
        out.append(f"History tax: median {ht['median']:.0%}, max {ht['max']:.0%}.")
    tr = a["tool_result_tax"]
    if tr.get("n"):
        out.append(f"Tool-result tax: median {tr['median']:.0%}, p95 {tr['p95']:.0%}.")
    by = ctx["cls"]
    if by:
        worst = max(by.items(), key=lambda kv: kv[1]["mean_total_tokens"] or 0)
        out.append(f"Most expensive class: {worst[0]} (mean {worst[1]['mean_total_tokens'] or 0:,.0f} tokens/turn).")
        slow = max(by.items(), key=lambda kv: kv[1]["median_latency_ms"] or 0)
        out.append(f"Slowest class: {slow[0]} (median {(slow[1]['median_latency_ms'] or 0) / 1000:.1f} s).")
    out.append(f"Repair tokens: {_fmt(a['repair_tokens_total'])} across all turns; "
               f"tokens after a correct artifact existed: {_fmt(a['finalization_tokens_total'])}.")
    if a.get("provider_time_share") is not None:
        out.append(f"Provider (model + token counting) share of processing time: {a['provider_time_share']:.0%}; "
                   f"local deterministic share: {a['local_time_share']:.0%}.")
    tc = sum(int(r.get("token_count_calls") or 0) for r in core)
    mc = sum(int(r.get("model_calls") or 0) for r in core)
    out.append(f"{tc:,} count_tokens round trips accompanied {mc:,} paid generations "
               f"({tc / mc:.2f} per generation)." if mc else "No generations recorded.")
    grow = [g for t in ctx["threads"] for g in t["token_growth_per_turn"]]
    if grow:
        out.append(f"Thread input-token growth per turn: median {M.dist(grow)['median']:,.0f} tokens.")
    tops = M.top(core, "native_total_tokens", 1)
    if tops:
        out.append(f"Largest single turn: {tops[0]['case_id']} with {tops[0]['native_total_tokens']:,} tokens "
                   f"({M.explain_outlier(tops[0])}).")
    return out


def certification_report(ctx: dict[str, Any]) -> str:
    a, m, core = ctx["arch"], ctx["manifest"], ctx["core"]
    L = [f"# AdvancedCockpit architecture certification report — {m['experiment_id']}", "",
         f"> **{ctx['banner']}**", "", "## Provenance", ""]
    prov = [("Frozen tag", m.get("frozen_tag")), ("Frozen commit", m.get("frozen_commit")),
            ("Harness commit", m.get("harness_head")), ("Harness version", m.get("harness_version")),
            ("Question bank SHA-256", m.get("bank_sha256")), ("Oracle references SHA-256", m.get("oracle_refs_sha256")),
            ("Protected manifest SHA-256", m.get("protected_manifest_sha256")),
            ("Model (requested)", m.get("model")), ("Price card", m.get("price_card")),
            ("Releases", json.dumps(m.get("releases"))), ("Release fingerprints (this runtime)", json.dumps(m.get("release_fingerprints"))),
            ("Release fingerprint note", m.get("release_fingerprint_note", "")),
            ("Python", m.get("python")), ("Dependency lock SHA-256", m.get("requirements_sha256")),
            ("Live", str(m.get("live"))), ("Spend cap", str(m.get("max_usd"))), ("Wall-clock cap (h)", str(m.get("max_hours")))]
    L += [_table([(k, f"`{v}`") for k, v in prov], ("Item", "Value")), "", "## Protected-core proof", "",
          f"- Status: **{ctx['proof']['status']}**", f"- Files verified: {ctx['proof']['files_checked']}",
          f"- git diff vs frozen commit on protected paths: {ctx['proof']['git_diff_protected_paths']}",
          f"- Problems: {ctx['proof']['problems'] or 'none'}", "", "## Architecture-level metrics", ""]
    L += [_table([(k, _fmt(v, pct=k.endswith('rate') or k.endswith('share'), money=k.startswith('cost')))
                  for k, v in a.items() if not isinstance(v, dict)])]
    for k in ("input_tokens", "output_tokens", "total_tokens_dist", "latency_ms", "static_context_tax",
              "history_tax", "tool_result_tax"):
        d = a[k]
        if d.get("n"):
            L.append(f"\n**{k}**: mean {_fmt(d['mean'])}, median {_fmt(d['median'])}, p75 {_fmt(d['p75'])}, "
                     f"p90 {_fmt(d['p90'])}, p95 {_fmt(d['p95'])}, p99 {d['p99'] if isinstance(d['p99'], str) else _fmt(d['p99'])}, "
                     f"min {_fmt(d['min'])}, max {_fmt(d['max'])} (n={d['n']})")
    L += ["", "## By test class", "", "| Class | n | Pass | Median latency s | P95 latency s | Mean tokens | Cost |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for g, s in ctx["cls"].items():
        L.append(f"| {g} | {s['n']} | {_fmt(s['pass_rate'], pct=True)} | {_fmt((s['median_latency_ms'] or 0) / 1000)} | "
                 f"{_fmt((s['p95_latency_ms'] or 0) / 1000)} | {_fmt(s['mean_total_tokens'])} | {_fmt(s['cost_usd'], money=True)} |")
    L += ["", "## Biggest token sinks and slowest turns (evidence-based reasons)", ""]
    for key, label in (("native_total_tokens", "total tokens"), ("native_input_tokens", "input tokens"),
                       ("repair_tokens", "repair tokens"), ("estimated_history_tokens", "history tokens (ESTIMATED)"),
                       ("estimated_tool_result_tokens", "tool-result tokens (ESTIMATED)"),
                       ("model_calls", "model calls"), ("e2e_processing_ms", "latency ms")):
        L += [f"### Top 20 by {label}", "", "| # | Case | Value | Reason |", "|---:|---|---:|---|"]
        for i, r in enumerate(M.top(core, key), 1):
            L.append(f"| {i} | {r['case_id']} | {_fmt(r[key])} | {M.explain_outlier(r)} |")
        L.append("")
    L += ["## Paraphrase invariance", "", "| Group | Classification | Members | Oracle pass |", "|---|---|---|---|"]
    for p in ctx["para"]:
        L.append(f"| {p['paraphrase_group']} | {p['classification']} | {', '.join(p['members'])} | {p['oracle_pass']} |")
    L += ["", "## Repeatability", "", "| Group | All pass | SQL identical | Tool sequence identical | Token CV | Latency CV |",
          "|---|---|---|---|---:|---:|"]
    for r in ctx["rep"]:
        L.append(f"| {r['repeatability_group']} | {r['all_oracle_pass']} | {r['sql_plan_identical']} | "
                 f"{r['tool_sequence_identical']} | {r['token_cv']} | {r['latency_cv']} |")
    L += ["", "## Threads", "", "| Thread | Passed turns | Continuity 2-5 | Leaks | Stale context | Input tokens by turn | Latency ms by turn |",
          "|---|---:|---:|---:|---:|---|---|"]
    for t in ctx["threads"]:
        L.append(f"| {t['thread']} | {t['passed_turns']}/{t['turns']} | {_fmt(t['continuity_rate_turns_2_5'], pct=True)} | "
                 f"{t['domain_leaks']} | {t['stale_context_turns']} | {t['input_tokens_by_turn']} | {t['latency_ms_by_turn']} |")
    if ctx["load"]:
        L += ["", "## Load microtest (not part of core certification)", "",
              "| Concurrency | Runs | Pass | Median queue wait ms | Throughput/min | 429 admissions | Deadline failures |",
              "|---:|---:|---:|---:|---:|---:|---:|"]
        for c in sorted({r["concurrency"] for r in ctx["load"]}):
            rs = [r for r in ctx["load"] if r["concurrency"] == c]
            L.append(f"| {c} | {len(rs)} | {sum(1 for r in rs if r['passed'])} | "
                     f"{_fmt(M.dist(r['queue_wait_ms'] for r in rs).get('median'))} | {rs[0]['throughput_runs_per_min']} | "
                     f"{sum(r['admission_retries_429'] for r in rs)} | {sum(1 for r in rs if r['deadline_failure'])} |")
    L += ["", "## Every non-passing turn", "", "| Case | Class | Cause | Severity | Why |", "|---|---|---|---|---|"]
    for r in core:
        if not r.get("passed"):
            L.append(f"| {r['case_id']} | {r['test_class']} | {r['root_cause']} | {r.get('severity')} | "
                     f"{'; '.join(r.get('root_cause_evidence') or [])[:220]} |")
    not_run = [c for c in ctx["bank"] if c not in {r['case_id'] for r in core}]
    if not_run:
        cond = (ctx["state"].get("phase_core") or {}).get("stopped") or {}
        L += ["", f"## Not run: {len(not_run)} turns", "",
              f"Reason: {cond.get('condition', 'not reached')} — {cond.get('detail', '')}", "",
              ", ".join(not_run)]
    return "\n".join(L) + "\n"


def findings_report(ctx: dict[str, Any]) -> str:
    L = [f"# Architecture findings — {ctx['manifest']['experiment_id']}", "", f"> **{ctx['banner']}**", "",
         "No change has been made to the frozen AdvancedCockpit. Every item below is a recommendation to "
         "INVESTIGATE; nothing has been implemented.", "",
         "## Static, code-verified findings (independent of any run)", "",
         "| ID | Severity | Layer | Finding | Evidence | Live signal (this experiment) |", "|---|---|---|---|---|---|"]
    sig = ctx["signals"]
    live_map = {"S-01": sig["S-01_disposition_enum_rejections"], "S-02": sig["S-02_answer_reserve_entries"],
                "S-03": sig["S-03_hidden_sdk_retries"], "S-04": sig["S-04_call_limit_runs"],
                "S-05": sig["S-05_redacted_detail_records"], "S-06": sig["S-06_served_models"],
                "S-07": sig["S-07_assistant_messages_as_strings"]}
    for f in STATIC_FINDINGS:
        L.append(f"| {f['id']} | {f['severity']} | {f['layer']} | {f['title']} | {f['evidence']} | "
                 f"{live_map.get(f['id'], 'see regression/load evidence')} |")
    L += ["", "## Failure clusters from this experiment", ""]
    if not ctx["clusters"]:
        L.append("No failing turns.")
    for i, c in enumerate(ctx["clusters"], 1):
        L += [f"### C-{i:02d}: {c['root_cause']} ({c['worst_severity']}) — {c['count']} case(s)", "",
              f"- Layer: {c['layer']}", f"- Error code: {c['error_code'] or 'none'}",
              f"- Fact statuses: {c['fact_statuses'] or 'n/a'}",
              f"- Domains: {', '.join(c['domains'])}; classes: {', '.join(c['test_classes'])}",
              f"- Reproducibility: {c['reproducible']}",
              f"- Cases: {', '.join(c['case_ids'])}",
              f"- Evidence: {'; '.join(c['sample_evidence'])}",
              f"- Recommended investigation: {RECOMMEND.get(c['root_cause'], 'inspect the evidence files of the listed cases')}",
              ""]
    return "\n".join(L) + "\n"


RECOMMEND = {
    "ARCH_CONTRACT": "Align the tool schema, the parser and the prompts (S-01, S-02); replay the listed cases' finalize payloads against the parser.",
    "ARCH_VALIDATION": "Replay the rejected submissions (validator_replay in evidence) and review the check that refused correct SQL.",
    "ARCH_DEADLINE": "Break down where the 180 s went (timing_metrics.csv) before any deadline change; compare provider vs local time.",
    "ARCH_BUDGET": "Check provider-attempt accounting (S-04) against the generations actually made in these runs.",
    "ARCH_REPAIR_LOOP": "Compare successive correction packets for the listed runs; check whether the repair feedback names the failing construct.",
    "ARCH_CONTEXT": "Inspect the history section of the first request (calls/*.json.gz) for the listed thread turns.",
    "ARCH_ROUTING": "Check the route's domain/thread resolution for the listed requests.",
    "ARCH_ORCHESTRATION": "Read the terminal events and error_id of the listed runs.",
    "MODEL_UNDERSTANDING": "Compare the question, the declared intent and the executed SQL; decide whether the prompt or the catalogue could have prevented it.",
    "MODEL_CODE": "Diff the executed SQL against the oracle's definition (oracle_results.csv) for the listed cases.",
    "MODEL_TOOL_USE": "Review the tool sequence and action-state decisions for the listed runs.",
    "MODEL_REPAIR": "Check whether the error information returned to the model was adequate.",
    "MODEL_PRESENTATION": "The artifacts held correct values; check claim binding and table selection in the finalize payloads.",
    "PROVIDER_TRANSIENT": "No architecture action; confirm the retry evidence.",
}


def freeze_readiness(ctx: dict[str, Any]) -> str:
    a, core = ctx["arch"], ctx["core"]
    sev = _sev_counts(core)
    fails = [r for r in core if not r.get("passed")]

    def ids(pred) -> str:
        c = [r["case_id"] for r in core if pred(r)]
        return f"{len(c)}: {', '.join(c[:15])}{' …' if len(c) > 15 else ''}" if c else "0"

    L = [f"# Freeze readiness inputs — {ctx['manifest']['experiment_id']}", "", f"> **{ctx['banner']}**", "",
         "This document gives the evidence for a freeze decision. It does not make the decision.", "",
         f"Protected core: **{ctx['proof']['status']}**.", "",
         "## Numerical correctness", "",
         f"- Exact-oracle pass rate: {_fmt(a['exact_oracle_pass_rate'], pct=True)}; analytical: {_fmt(a['analytical_oracle_pass_rate'], pct=True)}.",
         f"- Required figures published correctly: {a['required_facts_published']}/{a['required_facts_total']}; "
         f"computed but not published: {a['required_facts_artifact_only']}.",
         f"- Turns with a numerical error: {ids(lambda r: int(r.get('numeric_wrong') or 0) > 0 or int(r.get('incorrect_claim_count') or 0) > 0)}.",
         f"- Wrong period: {ids(lambda r: 'WRONG_PERIOD' in (r.get('fact_statuses') or []))}.",
         f"- Wrong population: {ids(lambda r: 'WRONG_POPULATION' in (r.get('fact_statuses') or []))}.", "",
         "## Analytical robustness (wording)", ""]
    for cls_name in ("INVARIANT", "PRESENTATION_ONLY_VARIATION", "MATERIAL_ANALYTICAL_VARIATION", "FAIL"):
        g = [p["paraphrase_group"] for p in ctx["para"] if p["classification"] == cls_name]
        L.append(f"- {cls_name}: {len(g)} group(s) {', '.join(g)}")
    L += ["", "## Conversation robustness", "",
          f"- Thread continuity (turns 2-5): {_fmt(a['thread_continuity_rate'], pct=True)}.",
          f"- Domain leakage: {ids(lambda r: r.get('domain_leak'))}.",
          f"- Stale context (wrong period/population on a follow-up): {sum(t['stale_context_turns'] for t in ctx['threads'])} turn(s).",
          f"- Route refusal on a domain switch inside a pinned thread: "
          f"{ids(lambda r: r.get('behaviour_observed') == 'ROUTE_REFUSED_DOMAIN_PINNED')}.", "",
          "## Governance", "",
          f"- Behavioural pass rate (clarify/refuse/answer correctly): {_fmt(a['behavioural_oracle_pass_rate'], pct=True)}.",
          f"- Numbers stated outside the governed universe: {ids(lambda r: any('numbers_outside' in f for f in (r.get('forbidden_violations') or [])))}.",
          f"- Genuine ambiguity detected: {_fmt(a['clarification_required_detected'], pct=True)}; "
          f"avoidable clarifications: {ids(lambda r: r.get('clarification_observed') and r.get('behaviour_expected') == 'ANSWER')}.",
          f"- Unhedged causal language (HEURISTIC): {ids(lambda r: r.get('unhedged_causality_HEURISTIC'))}.", "",
          "## Validation", "",
          f"- Validator rejections: {sum(int(r.get('validation_errors') or 0) for r in core)} across "
          f"{sum(1 for r in core if int(r.get('validation_errors') or 0))} turns.",
          f"- Rejections that replay to a correct answer (validator refused good work): "
          f"{ids(lambda r: r.get('root_cause') == 'ARCH_VALIDATION')}.",
          f"- Finalizer rejections: {sum(int(r.get('finalizer_errors') or 0) for r in core)}.", "",
          "## Repair", "",
          f"- Repair rate: {_fmt(a['repair_rate'], pct=True)}; repair success: {_fmt(a['repair_success_rate'], pct=True)}; "
          f"mean repairs per executing turn: {_fmt(a['average_repairs'])}; repair tokens: {_fmt(a['repair_tokens_total'])}.", "",
          "## Efficiency", ""]
    L += [f"- {o}" for o in token_latency_observations(ctx)]
    L += ["", "## Stability", ""]
    for r in ctx["rep"]:
        L.append(f"- {r['repeatability_group']}: all pass {r['all_oracle_pass']}, SQL identical {r['sql_plan_identical']}, "
                 f"token CV {r['token_cv']}, latency CV {r['latency_cv']}")
    L += ["", "## Corporate versus Retail", ""]
    for dom in ("corporate", "retail"):
        rs = [r for r in core if r.get("domain_expected") == dom]
        L.append(f"- {dom}: {len(rs)} turns, pass {_fmt(M.rate(sum(1 for r in rs if r.get('passed')), len(rs)), pct=True)}, "
                 f"leaks {sum(1 for r in rs if r.get('domain_leak'))}")
    L += ["", "## Operational reliability", "",
          f"- Provider/transient failures: {sum(sev['provider'].values())}; harness transient retries: {a['harness_transient_retries']}; "
          f"hidden SDK HTTP retries: {a['sdk_hidden_http_retries']}; rate-limit events: {a['rate_limit_events']}.",
          f"- Deadline failures: {ids(lambda r: r.get('root_cause') == 'ARCH_DEADLINE')}.",
          f"- Budget terminations: {ids(lambda r: r.get('root_cause') == 'ARCH_BUDGET')}.", "",
          "## Architecture defects (by severity)", "", f"{dict(sev['arch'])}", "",
          "## Model-specific defects (by severity)", "", f"{dict(sev['model'])}", "",
          "## Freeze decision inputs", "",
          "- Critical architecture findings: " + str(sev["arch"].get("CRITICAL", 0)),
          "- High architecture findings: " + str(sev["arch"].get("HIGH", 0)),
          "- Static findings open: " + ", ".join(f"{f['id']} ({f['severity']})" for f in STATIC_FINDINGS),
          f"- Failing turns: {len(fails)} of {len(core)} completed.",
          "- The decision is the reader's."]
    return "\n".join(L) + "\n"
