"""
The sequential certification runner.

For each planned user turn: guard checks -> POST through the real route ->
wait for the run to settle -> read the product's record -> grade against the
independent oracle -> persist the complete turn record and its evidence
(fsync'd) -> print one progress line.

Retries happen ONLY for genuine provider/infrastructure transients, at most
twice, and the original attempt stays in evidence. A wrong SQL, a validator
refusal, a clarification, a finalizer rejection or a wrong answer is an
outcome and is never retried.
"""

from __future__ import annotations

import json
import signal
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cert import evaluate as ev
from cert import oracles as orc
from cert import protected
from cert import telemetry as tel
from cert.engine import CockpitHarness, parse_iso
from cert.ledger import Experiment, now_iso
from cert.observe import UNKNOWN, Recorder

GROUP_ORDER = ["A_BASELINE", "B_PARAPHRASE", "C_COMPLEX", "D_THREAD", "E_CLARIFICATION",
               "F_GOVERNANCE", "G_REPEAT"]
PER_TURN_CEILING_USD = 1.50   # config.ANALYTICAL_STANDARD_LIMITS.spend_ceiling_usd
TRANSIENT_BACKOFF_S = (20.0, 60.0)


class StopRun(RuntimeError):
    def __init__(self, condition: str, detail: str) -> None:
        super().__init__(f"{condition}: {detail}")
        self.condition = condition
        self.detail = detail


@dataclass
class Price:
    input_per_mtok: float
    output_per_mtok: float
    cache_write_per_mtok: float
    cache_read_per_mtok: float
    source: str = ""

    def cost(self, i: Any, o: Any, cw: Any = 0, cr: Any = 0) -> float | None:
        if not isinstance(i, int) or not isinstance(o, int):
            return None
        cw = cw if isinstance(cw, int) else 0
        cr = cr if isinstance(cr, int) else 0
        return (i * self.input_per_mtok + o * self.output_per_mtok + cw * self.cache_write_per_mtok
                + cr * self.cache_read_per_mtok) / 1e6


@dataclass
class Guards:
    live: bool
    max_usd: float | None
    max_hours: float | None
    started_mono: float = field(default_factory=time.monotonic)
    stop_requested: bool = False
    stop_file: Path | None = None

    def check(self, cumulative_usd: float) -> None:
        if self.stop_requested or (self.stop_file is not None and self.stop_file.exists()):
            raise StopRun("STOPPED_BY_OPERATOR", "a stop was requested")
        if self.max_hours is not None:
            elapsed_h = (time.monotonic() - self.started_mono) / 3600.0
            if elapsed_h + (6.0 / 60.0) > self.max_hours:
                raise StopRun("NOT_RUN_TIME_CAP", f"{elapsed_h:.2f} h elapsed of {self.max_hours} h")
        if self.live:
            if self.max_usd is None:
                raise StopRun("NO_SPEND_CAP", "OPUS360_MAX_USD is not set")
            if cumulative_usd + PER_TURN_CEILING_USD > self.max_usd:
                raise StopRun("NOT_RUN_SPEND_CAP",
                              f"${cumulative_usd:.4f} spent + a possible ${PER_TURN_CEILING_USD:.2f} "
                              f"would exceed OPUS360_MAX_USD=${self.max_usd:.2f}")


ScriptFactory = Callable[[dict[str, Any], "orc.Reference | None", str, str, int], Any]


class Runner:
    def __init__(self, exp: Experiment, harness: CockpitHarness, recorder: Recorder, *,
                 bank_rows: list[dict[str, Any]], refs: dict[str, orc.Reference], price: Price,
                 guards: Guards, live: bool, script_factory: ScriptFactory | None = None,
                 static_counter: Callable[[str, Any], int | None] | None = None,
                 turn_timeout_s: float = 420.0, echo: bool = True,
                 protected_manifest_sha: str = "") -> None:
        self.exp, self.h, self.rec = exp, harness, recorder
        self.rows = bank_rows
        self.by_id = {r["case_id"]: r for r in bank_rows}
        self.refs = refs
        self.price = price
        self.guards = guards
        self.live = live
        self.script_factory = script_factory
        self.static_counter = static_counter
        self.turn_timeout_s = turn_timeout_s
        self.echo = echo
        self.protected_sha = protected_manifest_sha
        state = exp.state()
        self.cumulative_usd = float(state.get("cumulative_usd") or 0.0)
        self.threads: dict[str, str] = dict(state.get("threads") or {})
        self.turns_done = int(state.get("turns_completed") or 0)
        self.published_numbers: dict[str, list[float]] = dict(state.get("published_numbers") or {})
        self.critical = int(state.get("critical_failures") or 0)
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------------------
    def _save_state(self, **extra: Any) -> None:
        state = self.exp.state()
        state.update(cumulative_usd=round(self.cumulative_usd, 6), threads=self.threads,
                     turns_completed=self.turns_done, published_numbers=self.published_numbers,
                     critical_failures=self.critical, updated_at=now_iso(), **extra)
        self.exp.save_state(state)

    def verify_protected(self, when: str) -> None:
        verdict = protected.verify(expected_manifest_sha=self.protected_sha)
        self.exp.event("protected_manifest", when=when, ok=verdict.ok, problems=verdict.problems[:20])
        if not verdict.ok:
            self._save_state(certification_status="INVALID_PROTECTED_CORE_CHANGED")
            raise StopRun("INVALID_PROTECTED_CORE_CHANGED", "; ".join(verdict.problems[:5]))

    # -- one POST ---------------------------------------------------------------------
    def _post_once(self, case: dict[str, Any], question: str, *, thread_id: str, domain: str,
                   behaviour: str, attempt: int, spec_override: dict[str, Any] | None = None,
                   ref: orc.Reference | None = None) -> dict[str, Any]:
        self.guards.check(self.cumulative_usd)
        if self.h.switch is not None and self.script_factory is not None:
            scripted_case = dict(case, _asked_question=question)
            if spec_override is not None:
                scripted_case["_spec"] = spec_override
            self.h.switch.set(self.script_factory(scripted_case, ref, case["domain"], behaviour, attempt))
        start_mono = time.monotonic()
        turn = self.h.post(question, domain=domain, thread_id=thread_id)
        turn = self.h.wait(turn, timeout_seconds=self.turn_timeout_s)
        evidence = self.h.collect(turn.run_id) if turn.run_id else {"record": {}}
        calls = [c.to_dict() for c in self.rec.calls_between(start_mono, turn.observed_terminal_mono)]
        spend = evidence.get("spend") or {}
        measured = float(spend.get("committed_usd") or 0.0) + float(spend.get("pending_usd") or 0.0)
        with self._lock:
            self.cumulative_usd += measured
        return {"turn": turn, "evidence": evidence, "calls": calls, "measured_usd": measured,
                "posted_domain": domain, "posted_thread": thread_id, "question": question}

    @staticmethod
    def finalize_template(calls: list[dict[str, Any]]) -> str:
        for c in reversed(calls):
            for tc in reversed(c.get("response_tool_calls") or []):
                if tc.get("name") == "finalize_response":
                    return str((tc.get("input") or {}).get("narrative") or "")
        return ""

    def _grade(self, case: dict[str, Any], ref: orc.Reference | None, post: dict[str, Any],
               preserve: list[float] | None = None) -> tuple[ev.Verdict, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        turn, evidence, calls = post["turn"], post["evidence"], post["calls"]
        verdict = ev.evaluate(case, ref, http_status=turn.http_status, http_body=turn.http_body,
                              evidence=evidence, timed_out=turn.timed_out,
                              finalize_template=self.finalize_template(calls), preserve_numbers=preserve)
        sub = ev.submission_summary(evidence.get("submissions") or [], evidence.get("events") or [])
        replay = ev.validator_replay(ref, evidence.get("submissions") or [], evidence.get("events") or [],
                                     evidence.get("details") or {})
        cause = ev.root_cause(case, verdict, evidence, sub, calls, replay)
        return verdict, sub, cause, replay

    # -- one planned user turn -----------------------------------------------------------
    def run_case(self, case: dict[str, Any], phase: str) -> dict[str, Any]:
        cid = case["case_id"]
        ref = self.refs.get(f"{cid}:primary")
        transport = dict(case.get("transport") or {})
        thread_key = transport.get("thread_ref") or case["thread_id"]
        support: list[dict[str, Any]] = []

        # thread + domain resolution
        is_fresh = bool(case.get("fresh_thread")) and not transport.get("thread_ref")
        thread_id = "" if is_fresh else self.threads.get(thread_key, "")
        send_domain = case["domain"] if (not thread_id or transport.get("send_domain")) else ""

        # setup turns (support, clarification tests only)
        for i, setup in enumerate(case.get("setup_turns") or [], 1):
            post = self._post_once(case, setup["question"], thread_id=thread_id,
                                   domain=setup.get("domain", case["domain"]) if not thread_id else "",
                                   behaviour="ANSWER", attempt=1, spec_override=None, ref=None)
            if post["turn"].thread_id:
                thread_id = post["turn"].thread_id
                self.threads[thread_key] = thread_id
            send_domain = ""
            support.append(self._support_row(case, phase, f"setup-{i}", post, None))

        attempts: list[dict[str, Any]] = []
        expected = case.get("expected_behavior", "ANSWER")
        scripted_behaviour = expected
        for attempt in range(1, 4):
            post = self._post_once(case, case["question"], thread_id=thread_id, domain=send_domain,
                                   behaviour=scripted_behaviour, attempt=attempt, ref=ref)
            turn = post["turn"]
            if turn.thread_id:
                thread_id = turn.thread_id
                self.threads[thread_key] = thread_id
            preserve = self.published_numbers.get(case.get("preserve_from", ""), None) \
                if case.get("preserve_from") else None
            verdict, sub, cause, replay = self._grade(case, ref, post, preserve)
            attempts.append({"post": post, "verdict": verdict, "sub": sub, "cause": cause, "replay": replay})
            if cause["primary"] != "PROVIDER_TRANSIENT" or attempt == 3:
                break
            self.exp.event("transient_retry", case_id=cid, attempt=attempt, cause=cause)
            if self.live:
                time.sleep(TRANSIENT_BACKOFF_S[attempt - 1])
        final = attempts[-1]
        post, verdict, sub, cause = final["post"], final["verdict"], final["sub"], final["cause"]

        # route refusal -> follow the product's own action (new conversation in the asked book)
        follow = None
        if (verdict.behaviour_observed == "ROUTE_REFUSED_DOMAIN_PINNED"
                and transport.get("on_domain_pinned") == "follow_action"):
            fpost = self._post_once(case, case["question"], thread_id="", domain=case["domain"],
                                    behaviour="ANSWER", attempt=1, ref=ref)
            new_key = transport.get("new_thread_key") or f"{thread_key}-{case['domain']}"
            if fpost["turn"].thread_id:
                self.threads[new_key] = fpost["turn"].thread_id
            fcase = dict(case, expected_behavior="ANSWER", acceptable_behaviours=["ANSWER"])
            fverdict, fsub, fcause, _ = self._grade(fcase, ref, fpost)
            follow = {"post": fpost, "verdict": fverdict, "sub": fsub, "cause": fcause}
            support.append(self._support_row(case, phase, "domain-follow-action", fpost, fverdict, fcause))
            if not fverdict.passed:
                verdict.passed = False
                verdict.failure_reasons.append("follow-action run in the new conversation failed")
                if cause["primary"] == "PASS":
                    cause = fcause

        # clarification continuation
        clar = None
        if case.get("clarification_followup") and verdict.behaviour_observed == "CLARIFY":
            fref = self.refs.get(f"{cid}:followup")
            cpost = self._post_once(case, case["clarification_followup"], thread_id=thread_id, domain="",
                                    behaviour="ANSWER", attempt=1,
                                    spec_override=case.get("followup_oracle"), ref=fref)
            ccase = dict(case, expected_behavior="ANSWER", acceptable_behaviours=["ANSWER"],
                         domain=case["domain"])
            cverdict, csub, ccause, _ = self._grade(ccase, fref, cpost)
            clar = {"post": cpost, "verdict": cverdict, "sub": csub, "cause": ccause}
            support.append(self._support_row(case, phase, "clarification-response", cpost, cverdict, ccause))

        row = self._turn_row(case, phase, attempts, verdict, sub, cause, follow, clar, thread_key)
        for s in support:
            self.exp.record_result(s)
        self.exp.record_result(row)
        self.published_numbers[cid] = row["published_numbers"]
        self.turns_done += 1
        if row["severity"] == "CRITICAL":
            self.critical += 1
        self._save_state()
        return row

    # -- rows ------------------------------------------------------------------------------
    def _telemetry(self, post: dict[str, Any], verdict: ev.Verdict | None) -> dict[str, Any]:
        evidence, calls, turn = post["evidence"], post["calls"], post["turn"]
        events = evidence.get("events") or []
        record = evidence.get("record") or {}
        tools = tel.tool_activity(events, calls, evidence.get("messages") or [])
        times = tel.timings(events, record, calls, tools, turn.post_mono, turn.observed_terminal_mono)
        decomps = [tel.decompose_call(c, self.static_counter) for c in calls if c.get("kind") == "converse"]
        first_fail = next((parse_iso(e.get("occurred_at", "")) for e in events if e.get("event_type") == "tool.failed"
                           and e.get("stage") in ("validating", "executing")), None)
        first_correct = None
        if verdict is not None and verdict.facts:
            correct_arts = {f["matched_ref"].split("#")[0] for f in verdict.facts
                            if f["status"] in ("ARTIFACT_ONLY",) or f["status"].startswith("PUBLISHED")}
            for a in evidence.get("artifacts") or []:
                if a.get("artifact_id") in correct_arts:
                    ts = parse_iso(str(a.get("created_at") or ""))
                    if ts and (first_correct is None or ts < first_correct):
                        first_correct = ts
        tokens = tel.token_summary(calls, decomps, first_fail, first_correct)
        reservations = evidence.get("reservations") or []
        res_in = sum(int((r.get("usage") or {}).get("input_tokens") or 0) for r in reservations)
        res_out = sum(int((r.get("usage") or {}).get("output_tokens") or 0) for r in reservations)
        conv = [c for c in calls if c.get("kind") == "converse"]
        indep = [self.price.cost(c.get("input_tokens"), c.get("output_tokens"),
                                 c.get("cache_write_tokens"), c.get("cache_read_tokens")) for c in conv]
        indep_cost = sum(x for x in indep if x is not None) if indep and all(x is not None for x in indep) else (
            UNKNOWN if indep else 0.0)
        return {"tools": tools, "timings": times, "tokens": tokens, "decompositions": decomps,
                "reservation_input_tokens": res_in, "reservation_output_tokens": res_out,
                "cost_product_ledger_usd": round(post["measured_usd"], 6),
                "cost_independent_usd": round(indep_cost, 6) if isinstance(indep_cost, float) else indep_cost}

    def _support_row(self, case: dict[str, Any], phase: str, kind: str, post: dict[str, Any],
                     verdict: ev.Verdict | None, cause: dict[str, Any] | None = None) -> dict[str, Any]:
        t = self._telemetry(post, verdict)
        sid = f"{case['case_id']}::{kind}"
        evdir, sha = self.exp.write_evidence(phase, sid.replace(":", "_"), 1, {
            "record": post["evidence"].get("record"), "events": post["evidence"].get("events"),
            "submissions": post["evidence"].get("submissions"), "artifacts": post["evidence"].get("artifacts"),
            "reservations": post["evidence"].get("reservations"), "calls": post["calls"],
            "verdict": verdict.to_dict() if verdict else None, "telemetry": t,
            "http": {"status": post["turn"].http_status, "body": post["turn"].http_body}})
        return {"record_type": "support", "phase": phase, "case_id": sid, "parent_case_id": case["case_id"],
                "support_kind": kind, "question": post["question"], "run_id": post["turn"].run_id,
                "thread_real_id": post["turn"].thread_id, "http_status": post["turn"].http_status,
                "behaviour_observed": verdict.behaviour_observed if verdict else "",
                "passed": verdict.passed if verdict else None,
                "root_cause": (cause or {}).get("primary", ""),
                "native_input_tokens": t["tokens"]["native_input_tokens"],
                "native_output_tokens": t["tokens"]["native_output_tokens"],
                "cost_usd": t["cost_product_ledger_usd"],
                "e2e_processing_ms": t["timings"]["e2e_processing_ms"],
                "evidence_dir": str(evdir), "evidence_sha256": sha, "completed_at": now_iso()}

    def _turn_row(self, case: dict[str, Any], phase: str, attempts: list[dict[str, Any]], verdict: ev.Verdict,
                  sub: dict[str, Any], cause: dict[str, Any], follow: dict[str, Any] | None,
                  clar: dict[str, Any] | None, thread_key: str) -> dict[str, Any]:
        cid = case["case_id"]
        post = attempts[-1]["post"]
        record = post["evidence"].get("record") or {}
        final = record.get("final_response") or {}
        tele = self._telemetry(post, verdict)
        # evidence for every attempt (the original attempt stays)
        evdir, sha = None, ""
        for n, a in enumerate(attempts, 1):
            p = a["post"]
            evdir, sha = self.exp.write_evidence(phase, cid, n, {
                "record": p["evidence"].get("record"), "events": p["evidence"].get("events"),
                "details": p["evidence"].get("details"), "submissions": p["evidence"].get("submissions"),
                "artifacts": p["evidence"].get("artifacts"), "messages": p["evidence"].get("messages"),
                "reservations": p["evidence"].get("reservations"), "thread_turns": p["evidence"].get("thread_turns"),
                "calls": p["calls"], "verdict": a["verdict"].to_dict(), "submission_summary": a["sub"],
                "root_cause": a["cause"], "validator_replay": a["replay"],
                "telemetry": self._telemetry(p, a["verdict"]),
                "http": {"status": p["turn"].http_status, "body": p["turn"].http_body}})
        tools = tele["tools"]
        counts = {t: sum(1 for x in tools if x["tool"] == t) for t in tel.TOOLS}
        validation_errors = sum(1 for x in tools if x["tool"] == "execute_analysis" and x["outcome"] == "rejected")
        execution_errors = sum(1 for x in tools if x["tool"] == "execute_analysis" and x["outcome"] == "failed")
        finalizer_errors = sum(1 for x in tools if x["tool"] == "finalize_response" and x["outcome"] == "rejected")
        submissions = post["evidence"].get("submissions") or []
        sql_periods = sorted({p for s in submissions for st in ((s.get("payload") or {}).get("steps") or [])
                              for p in ev.period_tokens(st.get("code") or "")})
        published = [c["value"] for c in verdict.claims if isinstance(c.get("value"), (int, float))]
        for t in final.get("tables") or []:
            for r in t.get("rows") or []:
                can = r.get("canonical") if isinstance(r, dict) else None
                for v in (can or {}).values():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        published.append(float(v))
        counts_claims = verdict.counts()
        calls = post["calls"]
        conv = [c for c in calls if c.get("kind") == "converse"]
        served = sorted({str(c.get("served_model")) for c in conv if c.get("served_model") not in (None, UNKNOWN)})
        tokens = tele["tokens"]
        times = tele["timings"]
        row = {
            "record_type": "turn", "phase": phase, "case_id": cid, "test_class": case["test_class"],
            "family_id": case["family_id"], "question": case["question"],
            "domain_expected": case["domain"], "domain_actual": record.get("domain_id", ""),
            "thread_key": thread_key, "thread_real_id": post["turn"].thread_id or self.threads.get(thread_key, ""),
            "turn_number": case["turn_number"], "run_id": post["turn"].run_id,
            "paraphrase_group": case.get("paraphrase_group", ""),
            "repeatability_group": case.get("repeatability_group", ""),
            "oracle_type": case["oracle_type"], "difficulty": case.get("difficulty", ""),
            "reporting_period_expected": ",".join(self.refs[f"{cid}:primary"].periods) if f"{cid}:primary" in self.refs else "",
            "reporting_period_actual": ",".join(sql_periods),
            "http_status": post["turn"].http_status,
            "terminal_state": record.get("state", ""), "error_code": record.get("error_code", ""),
            "disposition": final.get("disposition", ""),
            "query_mode": ((final.get("intent") or {}).get("query_mode") or ""),
            "behaviour_expected": verdict.behaviour_expected, "behaviour_observed": verdict.behaviour_observed,
            "behaviour_ok": verdict.behaviour_ok, "oracle_pass": verdict.oracle_pass,
            "passed": verdict.passed, "failure_reasons": verdict.failure_reasons,
            "root_cause": cause["primary"], "root_cause_secondary": cause["secondary"],
            "severity": cause["severity"], "root_cause_evidence": cause["evidence"],
            "numeric_required": verdict.numeric_required, "numeric_published": verdict.numeric_published,
            "numeric_artifact_only": verdict.numeric_artifact_only, "numeric_wrong": verdict.numeric_wrong,
            "fact_statuses": [f["status"] for f in verdict.facts],
            "ranking_ok": verdict.ranking.get("ok") if verdict.ranking.get("required") else None,
            "members_ok": verdict.members.get("ok") if verdict.members.get("required") else None,
            **counts_claims,
            "unbound_numbers": [u["raw"] for u in verdict.unbound],
            "unbound_outside_universe": verdict.unbound_outside_universe,
            "unhedged_causality_HEURISTIC": verdict.causality.get("unhedged_causality"),
            "domain_leak": bool(verdict.leakage.get("leak")),
            "leakage": verdict.leakage,
            "forbidden_violations": verdict.forbidden_violations,
            "preservation_ok": verdict.preservation.get("ok") if verdict.preservation else None,
            "published_numbers": published[:500],
            "e2e_wall_ms": times["e2e_wall_ms"], "e2e_processing_ms": times["e2e_processing_ms"],
            "queue_wait_ms": times["queue_wait_ms"], "provider_ms": times["model_call_ms"],
            "token_count_call_ms": times["token_count_call_ms"], "provider_http_ms": times["provider_http_ms"],
            "local_ms": times["local_deterministic_ms"], "timings": times,
            "model_calls": tokens["model_calls"], "token_count_calls": tokens["token_count_calls"],
            "native_input_tokens": tokens["native_input_tokens"],
            "native_output_tokens": tokens["native_output_tokens"],
            "native_total_tokens": tokens["native_total_tokens"],
            "cache_read_tokens": tokens["cache_read_tokens"], "cache_write_tokens": tokens["cache_write_tokens"],
            "reservation_input_tokens": tele["reservation_input_tokens"],
            "reservation_output_tokens": tele["reservation_output_tokens"],
            "tokens_reconcile": (tele["reservation_input_tokens"] == tokens["native_input_tokens"]
                                 and tele["reservation_output_tokens"] == tokens["native_output_tokens"]),
            "estimated_system_tokens": round(sum(tokens["components_estimated"][k] for k in (
                "system_instruction", "system_static_knowledge", "system_volatile", "system_other")), 1),
            "estimated_tool_schema_tokens": tokens["components_estimated"]["tool_schema"],
            "estimated_history_tokens": tokens["estimated_history_tokens"],
            "estimated_tool_result_tokens": tokens["estimated_tool_result_tokens"],
            "static_context_tax": tokens["static_context_tax"], "history_tax": tokens["history_tax"],
            "tool_result_tax": tokens["tool_result_tax"], "repair_tokens": tokens["repair_tokens"],
            "finalization_tokens_after_correct_artifact": tokens["finalization_tokens_after_correct_artifact"],
            "token_components_estimated": tokens["components_estimated"],
            "decomposition_method": tokens["decomposition_method"],
            "cost_usd": tele["cost_product_ledger_usd"], "cost_independent_usd": tele["cost_independent_usd"],
            "cumulative_usd": round(self.cumulative_usd, 6),
            "catalog_calls": counts["inspect_catalog"], "product_knowledge_calls": counts["inspect_product_knowledge"],
            "analysis_submissions": sub["submissions"], "read_artifact_calls": counts["read_artifact"],
            "finalization_calls": counts["finalize_response"],
            "first_pass_valid": sub["first_pass_valid"], "needed_repair": sub["needed_repair"],
            "repairs": sub["repairs"], "repair_succeeded": sub["repair_succeeded"],
            "submission_statuses": sub["statuses"],
            "validation_errors": validation_errors, "execution_errors": execution_errors,
            "finalizer_errors": finalizer_errors,
            "provider_retries": sum(int(c.get("provider_retries") or 0) for c in calls),
            "rate_limit_events": sum(int(c.get("rate_limit_events") or 0) for c in calls),
            "provider_errors": sum(1 for c in calls if c.get("status") == "error"),
            "harness_transient_retries": len(attempts) - 1,
            "served_models": served, "requested_model": (conv[0].get("requested_model") if conv else ""),
            "tool_sequence": [t["tool"] for t in tools],
            "sql_digests": [ev.norm(" ".join(str(st.get("code") or "").split()))[:0] + _sql_digest(st.get("code"))
                            for s in submissions for st in ((s.get("payload") or {}).get("steps") or [])],
            "clarification_observed": verdict.behaviour_observed == "CLARIFY",
            "clarification_class": case.get("clarification_class", ""),
            "clarification_resumed_passed": clar["verdict"].passed if clar else None,
            "clarification_resumed_ms": (clar["post"]["turn"].observed_terminal_mono - clar["post"]["turn"].post_mono) * 1000 if clar else None,
            "clarification_resumed_tokens": _tok(clar["post"]["calls"]) if clar else None,
            "follow_action_passed": follow["verdict"].passed if follow else None,
            "observer_errors": self.rec.observer_errors,
            "evidence_dir": str(evdir), "evidence_sha256": sha, "attempts": len(attempts),
            "completed_at": now_iso(),
        }
        return row

    # -- phases -----------------------------------------------------------------------------
    def progress_line(self, n: int, total: int, row: dict[str, Any]) -> str:
        status = "PASS" if row["passed"] else f"FAIL {row['root_cause']}"
        secs = (row["e2e_wall_ms"] or 0) / 1000
        i, o = row["native_input_tokens"], row["native_output_tokens"]
        fi = f"{i:,}" if isinstance(i, int) else str(i)
        fo = f"{o:,}" if isinstance(o, int) else str(o)
        return (f"[{n:03d}/{total}] {row['case_id']} {status} | {secs:.1f}s | {fi} in | {fo} out | "
                f"{row['repairs']} repairs | ${row['cost_usd']:.4f} (cum ${self.cumulative_usd:.4f})")

    def run_phase(self, phase: str, cases: list[dict[str, Any]], *, batch: int = 25) -> dict[str, Any]:
        done = self.exp.completed(phase)
        total = len(cases)
        self.exp.log(f"phase {phase}: {total} planned turns, {len(done)} already completed and verified")
        self.verify_protected(f"{phase}:start")
        passed = sum(1 for r in done.values() if r.get("passed"))
        n = len(done)
        stopped = None
        started = time.monotonic()
        for case in cases:
            if case["case_id"] in done:
                continue
            try:
                row = self.run_case(case, phase)
            except StopRun as stop:
                stopped = {"condition": stop.condition, "detail": stop.detail, "at_case": case["case_id"]}
                self.exp.log(f"STOP [{stop.condition}] {stop.detail}")
                self.exp.event("stop", **stopped)
                break
            except Exception as exc:  # noqa: BLE001 - a harness fault is evidence, and it stops the phase
                stopped = {"condition": "HARNESS_ERROR", "detail": f"{type(exc).__name__}: {exc}",
                           "at_case": case["case_id"]}
                self.exp.error("run_case", traceback.format_exc(), case_id=case["case_id"])
                self.exp.log(f"HARNESS ERROR at {case['case_id']}: {type(exc).__name__}: {exc}")
                break
            n += 1
            passed += int(bool(row["passed"]))
            self.exp.log(self.progress_line(n, total, row), echo=self.echo)
            if n % batch == 0:
                self.verify_protected(f"{phase}:after-{n}")
                elapsed = time.monotonic() - started
                self.exp.log(f"--- {phase} {n}/{total} completed | pass {passed}/{n} "
                             f"({100.0 * passed / n:.1f}%) | cumulative ${self.cumulative_usd:.4f} | "
                             f"elapsed {elapsed / 60:.1f} min | remaining {total - n} turns | "
                             f"critical failures {self.critical}", echo=self.echo)
        self.verify_protected(f"{phase}:end")
        remaining = [c["case_id"] for c in cases if c["case_id"] not in self.exp.completed(phase)]
        summary = {"phase": phase, "planned": total, "completed": total - len(remaining),
                   "passed": passed, "stopped": stopped, "not_run": remaining}
        self.exp.event("phase_summary", **summary)
        self._save_state(**{f"phase_{phase}": summary})
        return summary

    # -- load microtest ------------------------------------------------------------------------
    def run_load(self, cases: list[dict[str, Any]], levels: tuple[int, ...] = (1, 2, 4)) -> list[dict[str, Any]]:
        from fastapi.testclient import TestClient

        from cert.engine import API, TERMINAL_STATES

        out: list[dict[str, Any]] = []
        done = {r["case_id"] for r in self.exp.results() if r.get("phase") == "load"}
        self.verify_protected("load:start")
        for level in levels:
            key = f"LOAD-c{level}"
            if any(d.startswith(key) for d in done):
                continue
            self.guards.check(self.cumulative_usd + PER_TURN_CEILING_USD * (level - 1))
            wall0 = time.monotonic()
            local = threading.local()

            def job(case: dict[str, Any], local: threading.local = local) -> dict[str, Any]:
                if not hasattr(local, "client"):
                    local.client = TestClient(self.h.app)
                client = local.client
                body = {"question": case["question"], "mode": "standard", "domain": case["domain"]}
                t0 = time.monotonic()
                admission_retries = 0
                while True:
                    resp = client.post(f"{API}/runs", json=body)
                    if resp.status_code == 429 and admission_retries < 600:
                        admission_retries += 1
                        time.sleep(1.0)
                        continue
                    break
                t_admit = time.monotonic()
                payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                run_id = payload.get("run_id", "")
                timed_out = False
                deadline = time.monotonic() + self.turn_timeout_s
                while run_id and time.monotonic() < deadline:
                    rec = self.h.store.get_run(run_id)
                    if rec is not None and str(rec.state) in TERMINAL_STATES:
                        break
                    time.sleep(0.2)
                else:
                    timed_out = bool(run_id)
                t1 = time.monotonic()
                return {"case": case, "run_id": run_id, "http_status": resp.status_code, "http_body": payload,
                        "admission_retries": admission_retries, "admission_wait_ms": int((t_admit - t0) * 1000),
                        "client_wall_ms": int((t1 - t0) * 1000), "timed_out": timed_out, "t0": t0, "t1": t1}

            if self.h.switch is not None and self.script_factory is not None:
                self.h.switch.set(_RoutingScript(self.script_factory, {c["question"]: c for c in cases},
                                                 self.refs, "load"))
            with ThreadPoolExecutor(max_workers=level) as pool:
                results = list(pool.map(job, cases))
            wall = time.monotonic() - wall0
            for r in results:
                case = r["case"]
                evidence = self.h.collect(r["run_id"]) if r["run_id"] else {"record": {}}
                events = evidence.get("events") or []
                record = evidence.get("record") or {}
                calls = [c.to_dict() for c in self.rec.calls_between(r["t0"], r["t1"])]
                ref = self.refs.get(f"{case['case_id']}:primary")
                verdict = ev.evaluate(case, ref, http_status=r["http_status"], http_body=r["http_body"],
                                      evidence=evidence, timed_out=r["timed_out"],
                                      finalize_template="")
                accepted = next((parse_iso(e.get("occurred_at", "")) for e in events if e.get("event_type") == "run.accepted"), None)
                claimed = next((parse_iso(e.get("occurred_at", "")) for e in events if e.get("event_type") != "run.accepted"), None)
                spend = evidence.get("spend") or {}
                cost = float(spend.get("committed_usd") or 0) + float(spend.get("pending_usd") or 0)
                self.cumulative_usd += cost
                row = {"record_type": "load", "phase": "load", "case_id": f"{key}:{case['case_id']}",
                       "concurrency": level, "source_case": case["case_id"], "domain": case["domain"],
                       "run_id": r["run_id"], "http_status": r["http_status"],
                       "admission_retries_429": r["admission_retries"], "admission_wait_ms": r["admission_wait_ms"],
                       "queue_wait_ms": int((claimed - accepted) * 1000) if (claimed and accepted) else UNKNOWN,
                       "client_wall_ms": r["client_wall_ms"], "terminal_state": record.get("state", ""),
                       "error_code": record.get("error_code", ""),
                       "deadline_failure": record.get("error_code") == "DEADLINE_EXPIRED" or record.get("state") == "EXPIRED",
                       "rate_limit_events": sum(int(c.get("rate_limit_events") or 0) for c in calls),
                       "provider_ms_window_HEURISTIC": sum(int(c.get("elapsed_ms") or 0) for c in calls if c.get("kind") == "converse"),
                       "storage_errors": record.get("error_code") in ("STORAGE_UNAVAILABLE",),
                       "oracle_pass": verdict.oracle_pass, "passed": verdict.passed,
                       "batch_wall_s": round(wall, 2), "throughput_runs_per_min": round(len(cases) / wall * 60, 3),
                       "cost_usd": round(cost, 6), "completed_at": now_iso()}
                self.exp.record_result(row)
                out.append(row)
            self.exp.log(f"load c={level}: {len(cases)} runs in {wall:.1f}s "
                         f"({len(cases) / wall * 60:.2f}/min), pass "
                         f"{sum(1 for x in out if x['concurrency'] == level and x['passed'])}/{len(cases)}")
            self._save_state()
        self.verify_protected("load:end")
        return out


class _RoutingScript:
    """Dry-run only: the single V4 worker runs one run at a time, so a new script is
    chosen whenever a run's first request (one message) arrives."""

    def __init__(self, factory: ScriptFactory, by_question: dict[str, dict[str, Any]],
                 refs: dict[str, orc.Reference], phase: str) -> None:
        self.factory, self.by_question, self.refs = factory, by_question, refs
        self.current: Any = None

    def count_tokens(self, **kwargs: Any) -> int:
        return int(len(json.dumps(kwargs, default=str)) / 3.5) + 1

    def converse(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or []
        if len(messages) == 1:
            text = str(messages[0].get("content") or "")
            case = next((c for q, c in self.by_question.items() if q in text), None)
            ref = self.refs.get(f"{case['case_id']}:primary") if case else None
            self.current = self.factory(case, ref, case["domain"], case.get("expected_behavior", "ANSWER"), 1)
        return self.current.converse(**kwargs)


def _sql_digest(code: Any) -> str:
    import hashlib

    text = " ".join(str(code or "").lower().split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _tok(calls: list[dict[str, Any]]) -> Any:
    vals = [(c.get("input_tokens"), c.get("output_tokens")) for c in calls if c.get("kind") == "converse"]
    if not vals or any(not isinstance(a, int) or not isinstance(b, int) for a, b in vals):
        return UNKNOWN
    return sum(a + b for a, b in vals)


def install_signal_handlers(guards: Guards) -> None:
    def handler(signum, frame):  # noqa: ANN001
        guards.stop_requested = True
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def order_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {g: i for i, g in enumerate(GROUP_ORDER)}
    return sorted(rows, key=lambda r: (rank.get(r["test_class"], 99), rows.index(r)))
