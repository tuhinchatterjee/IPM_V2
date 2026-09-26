"""
Post-run evaluation. Reads completed, authorised artifacts; writes a sidecar
assessment. It never calls a model, never feeds anything back into a run,
and can be re-run over stored evidence with a new rubric (a new revision;
the old one is superseded, not overwritten).

Separate dimensions, never merged into one score:
  execution state  (from the coordinator)
  quality          (checks against an independent reference, when one exists)
  evidence         (what could be observed at all)
  review           (human decisions, versioned)

Every derived number links to raw evidence (run id, call id, artifact id,
event seq) and to EVALUATOR_VERSION / ORACLE_VERSION.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.model_lab import EVALUATOR_VERSION, oracle
from backend.model_lab import metrics as mx

PASS, FAIL, PARTIAL = "PASS", "FAIL", "PARTIAL"
NOT_OBSERVED, NOT_REACHED, UNKNOWN = "NOT_OBSERVED", "NOT_REACHED", "UNKNOWN"
NOT_SEP = "NOT_SEPARATELY_OBSERVABLE"
SUPPORTED, CONTRADICTED, UNSUPPORTED = ("SUPPORTED", "CONTRADICTED",
                                        "UNSUPPORTED")
UNVERIFIABLE, QUALIFIED = "UNVERIFIABLE", "NOT_FACTUAL/QUALIFIED"

CAUSAL = re.compile(r"\b(caused|because|due to|driven by|as a result of|"
                    r"owing to|led to|attributable to|resulted from)\b", re.I)
HEDGE = re.compile(r"\b(may|might|could|possibly|suggests?|appears?|"
                   r"likely|consider|recommend)\b", re.I)
NUMBER = re.compile(r"\d[\d,]*(\.\d+)?")


# ---- evidence extraction ----------------------------------------------------

def _tool_results(messages: list[dict[str, Any]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in messages:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for part in c:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                body = part.get("content")
                if isinstance(body, list):
                    body = "".join(b.get("text", "") for b in body
                                   if isinstance(b, dict))
                try:
                    parsed = json.loads(body) if isinstance(body, str) \
                        else {}
                except ValueError:
                    parsed = {"_text": str(body)[:2000]}
                out[part.get("tool_use_id", "")] = {
                    "is_error": bool(part.get("is_error")) or
                    parsed.get("status") in ("rejected", "failed", "error"),
                    "body": parsed}
    return out


#: Per-call evidence status for WHICH tools a generation called.
EV_COMPLETE = "COMPLETE"                     # dict tool_use blocks in history
EV_FROZEN = "FROM_FROZEN_RECORD"             # frozen call_report tool_names
EV_INCOMPLETE = "EVIDENCE_INCOMPLETE"        # frozen says a call; no names
EV_NO_TOOL = "NO_TOOL_CALL_RECORDED"         # frozen says: no tool call


def _result_ids_after(messages: list[dict[str, Any]], index: int
                      ) -> list[str]:
    """tool_use ids answered by the user message after `index`. The engine
    builds these tool_result blocks itself, as dicts, so they survive the
    frozen store even when the assistant blocks were SDK objects."""
    if index + 1 >= len(messages):
        return []
    nxt = messages[index + 1]
    if nxt.get("role") != "user" or not isinstance(nxt.get("content"), list):
        return []
    return [str(p.get("tool_use_id") or "") for p in nxt["content"]
            if isinstance(p, dict) and p.get("type") == "tool_result"]


def _generations(messages: list[dict[str, Any]], call_report: list[dict],
                 spans: list[dict]) -> list[dict[str, Any]]:
    """One row per generation ATTEMPT, joined across three sources.

    WHICH TOOLS a generation called is taken from frozen authority, in
    order, and never inferred:
      1. dict `tool_use` blocks in the stored history (fixtures, OpenAI
         routes);
      2. the frozen call report's own `tool_names` for that attempt, with
         ids paired from the engine-built `tool_result` blocks that answer
         it. This is the path for the live Anthropic route: the frozen
         adapter hands the engine SDK block objects and the frozen store
         persists them as repr strings (OG-12), which are never parsed;
      3. the lab observer's span, recorded as a cross-check only.
    When the frozen record says a call happened but no source names it,
    the call is EVIDENCE_INCOMPLETE -- not "no tool call".
    """
    results = _tool_results(messages)
    assistant_idx = [i for i, m in enumerate(messages)
                     if m.get("role") == "assistant"]
    a_iter = iter(assistant_idx)
    gens = []
    conv_spans = [s for s in spans if s.get("kind") == "converse"]
    for i, entry in enumerate(call_report):
        span = conv_spans[i] if i < len(conv_spans) else None
        frozen_names = [str(n) for n in (entry.get("tool_names") or [])]
        frozen_says_call = (entry.get("parse_status") == "tool_call" or
                            (entry.get("tool_calls") or 0) > 0 or
                            bool(frozen_names))
        observer_names = [str(n) for n in ((span or {}).get("tool_names")
                                           or [])]
        tool_uses: list[dict[str, Any]] = []
        msg_names: list[str] = []
        source, status = "", EV_NO_TOOL
        if frozen_says_call:
            mi = next(a_iter, None)
            content = messages[mi].get("content") if mi is not None else None
            dict_blocks = [p for p in (content or [])
                           if isinstance(p, dict) and
                           p.get("type") == "tool_use"] \
                if isinstance(content, list) else []
            msg_names = [str(b.get("name")) for b in dict_blocks]
            if dict_blocks:
                tool_uses = [{"id": b.get("id"), "name": b.get("name"),
                              "input": b.get("input")} for b in dict_blocks]
                source, status = "stored_messages", EV_COMPLETE
            elif frozen_names:
                ids = _result_ids_after(messages, mi) if mi is not None \
                    else []
                tool_uses = [{"id": ids[k] if k < len(ids) and
                              len(ids) == len(frozen_names) else None,
                              "name": n, "input": None}
                             for k, n in enumerate(frozen_names)]
                source, status = "frozen_call_report", EV_FROZEN
            else:
                source, status = "none", EV_INCOMPLETE
        elif entry.get("parse_status") == "no_tool_call" and \
                entry.get("response_text_chars"):
            next(a_iter, None)   # a text-only turn that entered history
        names = [t["name"] for t in tool_uses]
        by_source = {"stored_messages": msg_names,
                     "frozen_call_report": frozen_names,
                     "observer": observer_names}
        disagree = [k for k, v in by_source.items() if v and v != names]
        gens.append({
            "seq": i + 1, "entry": entry, "span": span,
            "tool_uses": tool_uses,
            "results": [results.get(t.get("id") or "", {})
                        for t in tool_uses],
            "tool_names_source": source, "evidence_status": status,
            "tool_names_by_source": by_source,
            "tool_names_disagree": disagree,
            "attribution_basis": ("order-join of frozen call_report, lab "
                                  "observer spans and persisted messages; "
                                  f"tool names from {source or 'n/a'}")})
    return gens


def _fill_inputs_from_frozen_record(gens: list[dict[str, Any]], runs,
                                    run_id: str, run: Any) -> None:
    """Inputs for calls whose stored block was not a dict, from the frozen
    record only: `execute_analysis` bodies from the frozen `submissions`
    table (in order), and the disposition of the run's final answer from
    `runs.final_response`. Nothing is reconstructed from prose or reprs."""
    subs = [s.get("payload") or {} for s in
            (runs.submissions_for_run(run_id) or [])]
    k = 0
    for g in gens:
        for t in g["tool_uses"]:
            if t["name"] == "execute_analysis" and t["input"] is None:
                if k < len(subs):
                    t["input"] = subs[k]
                    t["input_source"] = "frozen_submissions"
            if t["name"] == "execute_analysis":
                k += 1
    finals = [g for g in gens if any(t["name"] == "finalize_response"
                                     for t in g["tool_uses"])]
    fr = getattr(run, "final_response", None) or {}
    if finals and fr.get("disposition"):
        finals[-1]["final_disposition"] = fr["disposition"]


def classify(gens: list[dict[str, Any]]) -> None:
    """FOUR_STAGE_CROSSWALK.md, applied in place. Multiple tags allowed."""
    prev_error = False
    seen_s1_only = False
    seen_execute = False
    for g in gens:
        e = g["entry"]
        names = [t.get("name") for t in g["tool_uses"]]
        purpose = e.get("purpose", "")
        tags: list[str] = []
        final = next((t for t in g["tool_uses"]
                      if t.get("name") == "finalize_response"), None)
        disp = ((final or {}).get("input") or {}).get("disposition", "") \
            or (g.get("final_disposition", "") if final else "")
        recovering = prev_error or purpose in ("ACTION_FORMAT_RECOVERY",
                                               "ANSWER_FORMAT_RECOVERY",
                                               "ANSWER_CORRECTION")
        if recovering:
            tags.append("S3")
        if any(n in ("inspect_catalog", "inspect_product_knowledge")
               for n in names):
            tags.append("S1")
            seen_s1_only = True
        if final and disp in ("clarification", "referral", "unsupported"):
            tags.append("S1")
        if "execute_analysis" in names:
            if not seen_execute and not seen_s1_only:
                tags += ["S1", "S2"]
            else:
                tags.append("S2")
            if seen_execute and not recovering:
                tags.append("S3")      # continuation after a good result
            seen_execute = True
        if "read_artifact" in names:
            tags.append("S3")
        if final and disp in ("answer", "partial_answer", "partial",
                              "safe_failure"):
            tags.append("S4")
        if final and not disp and e.get("phase") == "answer":
            tags.append("S4")          # an answer turn whose body is stored
        if purpose == "ANSWER_CORRECTION":
            tags += ["S3", "S4"]
        if not names:
            tags.append("S4" if e.get("phase") == "answer" else "S1")
            if g.get("evidence_status") == EV_INCOMPLETE:
                g["protocol_flag"] = ("tool names unavailable "
                                      "(EVIDENCE_INCOMPLETE)")
            else:
                g["protocol_flag"] = "no usable tool call"
        g["stage_tags"] = sorted(set(tags))
        g["shared"] = len(set(tags) - {"S3"}) > 1 or len(set(tags)) > 1
        prev_error = any(r.get("is_error") for r in g["results"]) or \
            not e.get("usable", True)


# ---- per-child evaluation -------------------------------------------------------

def _artifact_rows(runs, artifact_id: str, tenant: str) -> list[dict]:
    try:
        a = runs.get_artifact(artifact_id, tenant_id=tenant)
    except Exception:  # noqa: BLE001
        return []
    return list((a or {}).get("rows") or [])


def _value_column(rows: list[dict], preferred: str | None = None) -> str:
    if not rows:
        return ""
    if preferred and preferred in rows[0]:
        return preferred
    for k, v in rows[0].items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return k
    return ""


def _metric_column(rows: list[dict], reference: dict | None,
                   fr: dict | None) -> tuple[str, bool]:
    """The artifact column that carries the reference's PRIMARY metric.

    Chosen by unit class and column name through `oracle.match_metric`,
    using the units the frozen answer declared (table `column_units`, then
    the numeric claims citing that column). Falls back to the first numeric
    column only when nothing matches, and says so (confirmed=False)."""
    if not rows:
        return "", False
    primary = (reference or {}).get("primary_metric")
    units: dict[str, str] = {}
    for t in (fr or {}).get("tables") or []:
        units.update(t.get("column_units") or {})
    for c in (fr or {}).get("numeric_claims") or []:
        col = (c.get("evidence") or {}).get("column_id")
        if col and c.get("unit"):
            units.setdefault(col, c["unit"])
    numeric = [k for k, v in rows[0].items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if primary:
        hits = [k for k in numeric if oracle.match_metric(
            reference, k, units.get(k), None) == primary]
        if len(hits) == 1:
            return hits[0], True
    return _value_column(rows), False


def _sector_map(rows: list[dict], column: str | None = None
                ) -> dict[str, float]:
    if not rows:
        return {}
    key = next((k for k in rows[0] if k in ("sector", "sector_name")), None)
    col = _value_column(rows, column)
    if not key or not col:
        return {}
    return {str(r[key]): float(r[col]) for r in rows
            if r.get(col) is not None and r.get(key) is not None}


def _reasoning_variant(profile: dict[str, Any]) -> str | None:
    """Label that separates a default-thinking run from a run whose
    reasoning was switched off by a runtime request control."""
    rc = profile.get("request_controls") or {}
    if "reasoning_effort" in rc:
        return f"reasoning_effort={rc['reasoning_effort']}"
    if profile.get("route") == "openai_compat":
        return "runtime-default (no reasoning control sent)"
    return None


def evaluate_child(child: dict[str, Any], *, runs, events: list[dict],
                   spec: dict[str, Any], task: oracle.Task | None,
                   reference: dict[str, Any] | None, tenant: str,
                   profile: dict[str, Any]) -> dict[str, Any]:
    cid = child["child_run_id"]
    fixture = profile.get("role") == "fixture"
    out: dict[str, Any] = {
        "child_run_id": cid, "profile_id": child["profile_id"],
        "display_name": child.get("display_name"), "fixture": fixture,
        "execution_state": child["state"], "reason": child.get("reason", ""),
        "lineage": child.get("lineage"), "repetition": child["repetition"],
        "attempt_id": child["attempt_id"],
        "profile_digest": child["profile_digest"],
        "requested_model": (profile.get("endpoint") or {}).get("model")
        or profile.get("registry_id"),
        "request_controls": profile.get("request_controls") or None,
        "reasoning_variant": _reasoning_variant(profile),
        "parent_profile_id": profile.get("parent_profile_id"),
    }
    turns = child.get("turns") or []
    spans = [e["payload_obj"] for e in events
             if e["child_run_id"] == cid and
             e["event_type"].startswith("provider.")
             and e.get("payload_obj")]
    if not turns:
        out.update(_blocked_view(child, spans))
        return out

    all_gens: list[dict] = []
    frozen_validation: dict[str, Any] | None = None
    answers = []
    app_spans: list[tuple[float, float]] = []
    app_lane: list[dict] = []
    for t in turns:
        run = runs.get_run(t["run_id"])
        messages = runs.load_messages(t["run_id"])
        details = runs.details_for_run(t["run_id"])
        report = next((d["call_report"]["calls"] for d in details.values()
                       if isinstance(d, dict) and "call_report" in d), [])
        run_spans = [s for s in spans if s.get("kind") == "converse"]
        # Spans for THIS turn: the next len(report) converse spans in order.
        offset = sum(len(g) for g in [x["_gens"] for x in answers]) \
            if answers else 0
        gens = _generations(messages, report,
                            run_spans[offset:offset + len(report)])
        _fill_inputs_from_frozen_record(gens, runs, t["run_id"], run)
        classify(gens)
        for g in gens:
            g["run_id"] = t["run_id"]
            g["turn_index"] = t["turn_index"]
            g["call_id"] = (g["span"] or {}).get("call_id") or \
                f"{t['run_id']}#{g['seq']}"
        fevents = runs.events_since(t["run_id"])
        open_tools: dict[str, float] = {}
        for ev in fevents:
            et, el = ev.event_type, float(ev.elapsed_ms or 0)
            if et == "tool.requested":
                open_tools[ev.operation] = el
            elif et in ("tool.completed", "tool.failed") and \
                    ev.operation in open_tools:
                s = open_tools.pop(ev.operation)
                app_spans.append((s, el))
                app_lane.append({"run_id": t["run_id"], "kind": ev.operation,
                                 "status": ev.status, "start_ms": s,
                                 "end_ms": el, "duration_ms": el - s,
                                 "message": ev.public_message[:200],
                                 "event_seq": ev.seq})
            if et == "answer.validated":
                frozen_validation = {
                    "status": ev.status, "message": ev.public_message[:300],
                    "run_id": t["run_id"], "event_seq": ev.seq,
                    "source": "frozen Finalizer (answer.validated event)"}
            if et in ("answer.validated", "answer.ready",
                      "analysis.preserved"):
                app_lane.append({"run_id": t["run_id"], "kind": et,
                                 "status": ev.status, "start_ms": el,
                                 "end_ms": el, "duration_ms": 0.0,
                                 "message": ev.public_message[:200],
                                 "event_seq": ev.seq})
        answers.append({"run_id": t["run_id"], "turn_index":
                        t["turn_index"], "kind": t["kind"],
                        "question": t["question"],
                        "frozen_state": run.state if run else t["state"],
                        "error_code": (run.error_code if run else
                                       t.get("error_code")) or "",
                        "final_response": _safe_final(
                            run.final_response if run else None),
                        "_gens": gens})
        all_gens.extend(gens)

    out["turns"] = [{k: v for k, v in a.items() if k != "_gens"}
                    for a in answers]
    last = answers[-1]
    out["answer"] = last["final_response"]
    out["frozen_state"] = last["frozen_state"]
    out["error_code"] = last["error_code"]

    # ---- identity (A01)
    resolved = sorted({s.get("resolved_model") for s in spans
                       if s.get("resolved_model")})
    out["identity"] = {
        "requested": out["requested_model"], "resolved": resolved,
        "match": (resolved == [out["requested_model"]]) if resolved
        else None,
        "status": ("MATCH" if resolved == [out["requested_model"]] else
                   "MISMATCH" if resolved else "UNAVAILABLE")}

    # ---- calls + stages
    calls = []
    for g in all_gens:
        e, s = g["entry"], g["span"] or {}
        u = s.get("usage") or {}
        token_status = (mx.ESTIMATED if fixture else
                        mx.MEASURED if u.get("input_tokens") is not None
                        else mx.UNAVAILABLE)
        calls.append({
            "call_id": g["call_id"], "run_id": g["run_id"],
            "turn_index": g["turn_index"], "seq": g["seq"],
            "purpose": e.get("purpose"), "phase": e.get("phase"),
            "stage_tags": g["stage_tags"],
            "shared_span": len([x for x in g["stage_tags"]]) > 1,
            "attribution_basis": g["attribution_basis"],
            "tool_names": [t.get("name") for t in g["tool_uses"]],
            "tool_names_source": g["tool_names_source"],
            "tool_names_by_source": g["tool_names_by_source"],
            "tool_names_disagree": g["tool_names_disagree"],
            "evidence_status": g["evidence_status"],
            "tool_choice": e.get("tool_choice"),
            "required_tool": e.get("required_tool"),
            "outcome": e.get("outcome"), "usable": e.get("usable"),
            "stop_reason": e.get("stop_reason") or s.get("stop_reason"),
            "provider_ms_frozen": e.get("provider_ms"),
            "duration_ms": s.get("duration_ms"),
            "start_monotonic": s.get("start_monotonic"),
            "end_monotonic": s.get("end_monotonic"),
            "input_tokens": u.get("input_tokens"),
            "output_tokens": u.get("output_tokens"),
            "cache_read_tokens": u.get("cache_read_tokens"),
            "cache_write_tokens": u.get("cache_write_tokens"),
            "token_status": token_status,
            "token_source": ("fixture synthetic counter (not a tokenizer)"
                             if fixture else "provider-native usage"),
            "native_usage": s.get("native_usage"),
            "native_timing": s.get("native_timing"),
            "errors_returned": [r.get("body", {}).get("error_code") or
                                r.get("body", {}).get("message", "")[:120]
                                for r in g["results"] if r.get("is_error")],
            "protocol_flag": g.get("protocol_flag", ""),
            "provider_error": (s.get("error") or "")[:300],
            "provider_error_code": s.get("error_code") or "",
            "request_controls": s.get("request_controls"),
            "reasoning_chars": s.get("reasoning_chars"),
        })
    out["calls"] = calls
    out["app_lane"] = app_lane

    # ---- checks against the independent reference
    checks, facts = _checks(child, answers, runs, tenant, task, reference)
    out["checks"] = checks
    out["repair"] = _repair(all_gens, facts)
    out["claims"] = _claims(last["final_response"], runs, tenant, task,
                            reference, facts, frozen_validation)
    out["frozen_validation"] = frozen_validation
    out["claim_rates"] = _claim_rates(out["claims"], task, facts)
    out["stages"] = _stages(all_gens, checks, out["repair"], out["claims"],
                            last, task)
    out["metrics"] = _metrics(child, turns, calls, app_spans, fixture,
                              runs, profile)
    out["facts"] = facts
    out["failures"] = _failures(out, task)
    gap = _evidence_gap_card(out)
    if gap:
        out["failures"].append(gap)     # last: never the first divergence
    out["first_divergence"] = _first_divergence(out)
    return out


def _safe_final(fr: dict | None) -> dict | None:
    if not fr:
        return None
    keep = ("disposition", "narrative", "numeric_claims", "tables", "charts",
            "limitations", "clarification_question", "clarification_options",
            "coverage", "executed", "suggested_questions", "referral_reason")
    return {k: fr.get(k) for k in keep if k in fr}


def _blocked_view(child: dict, spans: list[dict]) -> dict[str, Any]:
    blocked = {
        s: {"status": NOT_REACHED, "checks": [],
            "note": "the child never ran: " + (child.get("reason") or
                                                child["state"])}
        for s in ("S1", "S2", "S3", "S4")}
    return {"turns": [], "answer": None, "calls": [], "app_lane": [],
            "checks": [], "claims": [], "claim_rates": _claim_rates(
                [], None, {}),
            "repair": {"status": NOT_OBSERVED, "opportunities": 0,
                       "attempts": 0, "valid_repairs": 0,
                       "business_correct_recoveries": None},
            "stages": blocked, "identity": {"status": "UNAVAILABLE"},
            "metrics": {"queue_delay_ms": mx.unavailable(
                "ms", "child never admitted").to_dict()},
            "failures": [_blocked_card(child)], "first_divergence": None,
            "facts": {}}


def _blocked_card(child: dict) -> dict[str, Any]:
    reason = child.get("reason") or child["state"]
    cat = ("RESOURCE_OR_CONTEXT" if "memory" in reason.lower() or
           "context" in reason.lower() else "BASELINE_OR_INFRASTRUCTURE")
    return {"primary_category": cat, "supporting_categories": [],
            "symptom": f"{child['display_name'] or child['profile_id']} did "
                       f"not run", "failed_requirement": "runnable profile",
            "artifact": {"child_run_id": child["child_run_id"]},
            "likely_owner": "environment / approvals",
            "origin_confidence": "ORIGIN_CONFIRMED",
            "affected_stages": [], "inherited_effects": [],
            "earliest_event": None, "severity": "BLOCKER",
            "next_diagnostic": "resolve the blocker, then rerun",
            "intervention_category": "setup", "approval_needed": reason,
            "model_failure": False, "detail": reason}


def _checks(child, answers, runs, tenant, task, reference
            ) -> tuple[list[dict], dict[str, Any]]:
    checks: list[dict] = []
    facts: dict[str, Any] = {"task_id": task.task_id if task else None}
    last = answers[-1]
    fr = last["final_response"] or {}
    if last["frozen_state"] == "WAITING_FOR_USER":
        facts["clarification"] = fr.get("clarification_question")
    if task is None or reference is None:
        checks.append({"check_id": "REF-000", "stage": "ALL",
                       "kind": "reference_available", "outcome": UNKNOWN,
                       "expected": "an approved task specification",
                       "actual": "no registered task matches this question",
                       "truth_source": "none", "severity": "INFO",
                       "status": "NEEDS_REVIEW", "evidence_ref": None})
        return checks, facts

    # clarification policy
    if fr.get("disposition") == "clarification" or \
            last["frozen_state"] == "WAITING_FOR_USER":
        outcome = (PASS if task.clarification_policy in ("required",
                                                        "optional")
                   else PARTIAL)
        checks.append({
            "check_id": "S1-CLAR", "stage": "S1",
            "kind": "clarification_appropriateness", "outcome": outcome,
            "expected": f"clarification {task.clarification_policy}",
            "actual": fr.get("clarification_question"),
            "truth_source": "task specification", "severity": "MINOR",
            "status": "AUTO_CHECKED" if outcome == PASS else "NEEDS_REVIEW",
            "note": "a necessary question is not a wrong answer; this task "
                    "does not require one, so a reviewer decides whether it "
                    "was reasonable",
            "evidence_ref": {"run_id": last["run_id"]}})

    # the executed artifact the answer rests on
    artifact_id = None
    for t in (fr.get("tables") or []):
        artifact_id = artifact_id or t.get("artifact_id")
    for c in (fr.get("numeric_claims") or []):
        artifact_id = artifact_id or (c.get("evidence") or {}).get(
            "artifact_id")
    produced: dict[str, float] = {}
    metric_column, metric_confirmed = "", False
    if artifact_id:
        rows = _artifact_rows(runs, artifact_id, tenant)
        metric_column, metric_confirmed = _metric_column(
            rows, reference, fr)
        produced = _sector_map(rows, metric_column)
    facts["artifact_id"] = artifact_id
    facts["produced"] = produced
    facts["metric_column"] = metric_column
    facts["metric_column_confirmed"] = metric_confirmed
    exp, wrong = reference["values"], reference["wrong_population_values"]
    if not artifact_id:
        checks.append({"check_id": "S2-RESULT", "stage": "S2",
                       "kind": "result_matches_reference",
                       "outcome": NOT_REACHED, "expected": "an executed "
                       "result", "actual": "no result artifact referenced "
                       "by the final answer", "truth_source": "oracle",
                       "severity": "MAJOR", "status": "AUTO_CHECKED",
                       "evidence_ref": {"run_id": last["run_id"]}})
        facts["population_ok"] = None
        return checks, facts

    same_keys = set(produced) == set(exp)
    mism = {k: (produced.get(k), exp.get(k)) for k in set(produced) | set(exp)
            if k not in produced or k not in exp or
            not oracle.within(produced[k], exp[k], task)}
    pop_ok = same_keys and not mism
    matches_wrong = bool(produced) and set(produced) == set(wrong) and all(
        oracle.within(produced[k], wrong[k], task) for k in produced)
    facts["population_ok"] = pop_ok
    facts["matches_wrong_population"] = matches_wrong
    checks.append({
        "check_id": "S1S2-POP", "stage": "S1+S2",
        "kind": "population_assertion",
        "outcome": PASS if pop_ok else FAIL,
        "expected": reference["population"],
        "actual": ("matches the reference population" if pop_ok else
                   f"matches {reference['wrong_population_label']}"
                   if matches_wrong else
                   f"{len(mism)} sector value(s) differ from the reference"),
        "tolerance": {"abs": task.abs_tolerance, "rel": task.rel_tolerance,
                      "unit": reference["unit"]},
        "truth_source": f"independent pandas oracle "
                        f"({reference['oracle_version']})",
        "severity": "CRITICAL" if not pop_ok else "INFO",
        "status": "AUTO_CHECKED",
        "evidence_ref": {"artifact_id": artifact_id,
                         "run_id": last["run_id"],
                         "metric_column": metric_column},
        "metric": reference.get("primary_metric"),
        "metric_column_confirmed": metric_confirmed,
        "note": ("" if metric_confirmed else
                 f"the metric column could not be confirmed by unit and "
                 f"name; compared column {metric_column!r}"),
        "detail": {k: {"produced": v[0], "expected": v[1]}
                   for k, v in list(mism.items())[:20]}})
    checks.append({
        "check_id": "S2-RESULT", "stage": "S2",
        "kind": "result_matches_reference",
        "outcome": PASS if pop_ok else FAIL,
        "expected": f"{len(exp)} sectors, total "
                    f"{reference['total']:,.2f} {reference['unit']}",
        "actual": f"{len(produced)} sectors, total "
                  f"{sum(produced.values()):,.2f}",
        "tolerance": {"abs": task.abs_tolerance, "rel": task.rel_tolerance},
        "truth_source": "independent pandas oracle", "severity": "MAJOR",
        "status": "AUTO_CHECKED",
        "evidence_ref": {"artifact_id": artifact_id}})
    top = max(produced, key=produced.get) if produced else None
    checks.append({
        "check_id": "S4-LARGEST", "stage": "S4",
        "kind": "required_output:largest_sector",
        "outcome": PASS if top == reference["largest"] and pop_ok else FAIL,
        "expected": reference["largest"], "actual": top,
        "truth_source": "independent pandas oracle", "severity": "MAJOR",
        "status": "AUTO_CHECKED",
        "note": ("correct sector name over the wrong population is not a "
                 "pass" if top == reference["largest"] and not pop_ok
                 else ""),
        "evidence_ref": {"artifact_id": artifact_id}})
    return checks, facts


def _repair(gens: list[dict], facts: dict) -> dict[str, Any]:
    opportunities = attempts = valid = 0
    chains = []
    for i, g in enumerate(gens):
        errs = [r for r in g["results"] if r.get("is_error")]
        if not errs:
            continue
        opportunities += 1
        nxt = gens[i + 1] if i + 1 < len(gens) else None
        resubmitted = bool(nxt and nxt["tool_uses"])
        accepted = bool(nxt and nxt["results"] and not any(
            r.get("is_error") for r in nxt["results"]))
        attempts += int(resubmitted)
        valid += int(accepted)
        body = errs[0].get("body", {})
        chains.append({
            "call_id": g["call_id"], "error_code": body.get("error_code"),
            "feedback": str(body.get("message", ""))[:600],
            "field": body.get("field"),
            "category": ("validation_refusal" if body.get("status") ==
                         "rejected" else "execution_failure"),
            "next_call_id": nxt["call_id"] if nxt else None,
            "next_action": [t.get("name") for t in nxt["tool_uses"]]
            if nxt else [],
            "revalidation": "accepted" if accepted else
            "refused" if resubmitted else "no resubmission",
            "diff": _code_diff(g, nxt)})
    if opportunities == 0:
        status = NOT_OBSERVED
        business = None
    else:
        business = (valid if facts.get("population_ok") else 0) \
            if facts.get("population_ok") is not None else None
        status = PASS if valid == opportunities and (
            business is None or business == valid) else \
            PARTIAL if valid else FAIL
    return {"status": status, "opportunities": opportunities,
            "attempts": attempts, "valid_repairs": valid,
            "business_correct_recoveries": business,
            "note": ("no error occurred, so repair ability was not "
                     "observed (neither 0% nor 100%)" if not opportunities
                     else ""), "chains": chains}


def _code_diff(g: dict, nxt: dict | None) -> dict | None:
    def code(gen):
        for t in (gen or {}).get("tool_uses", []):
            if t.get("name") == "execute_analysis":
                return "\n\n".join(s.get("code", "") for s in
                                   t.get("input", {}).get("steps", []))
        return None
    a, b = code(g), code(nxt)
    if a is None or b is None:
        return None
    import difflib
    return {"before": a, "after": b, "unified": "\n".join(
        difflib.unified_diff(a.splitlines(), b.splitlines(), "submitted",
                             "resubmitted", lineterm=""))}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "")
            if s.strip()]


def _artifact_record(runs, artifact_id: str, tenant: str) -> dict | None:
    if not artifact_id:
        return None
    try:
        return runs.get_artifact(artifact_id, tenant_id=tenant)
    except Exception:  # noqa: BLE001 - an unreadable record is "not mapped"
        return None


def _numeric_claim(c: dict[str, Any], runs, tenant, task, reference,
                   facts, frozen: dict[str, Any],
                   column_units: dict[str, str] | None = None
                   ) -> dict[str, Any]:
    """One structured numeric claim, resolved with the FROZEN resolvers.

    Direct claims are located with `derivation.row_index_for` -- the same
    public helper the frozen Finalizer uses (`r0`, bare index,
    `column=value`, unique value). Derived claims are recomputed with the
    frozen `derivation.parse` / `compute` over the stored artifacts.

    A failure to MAP the evidence is EVIDENCE_INCOMPLETE / UNVERIFIABLE,
    never UNSUPPORTED: a sidecar that cannot find a locator has not shown
    that the claim lacks support. CONTRADICTED is reserved for evidence
    that was found and disagrees.
    """
    from decimal import Decimal, InvalidOperation

    from backend.cockpit_v4 import derivation as deriv

    ev = c.get("evidence") or {}
    status, why, evidence_status = UNVERIFIABLE, "", EV_COMPLETE
    value: Any = None
    refs: list[str] = []
    row_label = None
    metric: str | None = None
    reference_value: float | None = None
    if c.get("derivation"):
        try:
            d = deriv.parse(c["derivation"])
            refs = list(d.artifact_ids)
            arts = {a: _artifact_record(runs, a, tenant) for a in refs}
            missing = [a for a, r in arts.items() if r is None]
            if missing:
                raise deriv.DerivationError(
                    f"artifact(s) {missing} not retrievable by the sidecar")
            value = deriv.compute(d, arts, label=str(c.get("claim_id")))
            claimed = c.get("decimal_value")
            if claimed not in (None, ""):
                try:
                    if Decimal(str(claimed)) != Decimal(str(value)):
                        status, why = CONTRADICTED, (
                            f"recomputed {value} but the claim asserts "
                            f"{claimed}")
                except InvalidOperation:
                    pass
            if status != CONTRADICTED:
                status = SUPPORTED
                why = (f"recomputed from the stored artifacts with the "
                       f"frozen derivation ({d.operation}) = {value}; no "
                       f"independent reference for a derived value")
        except deriv.DerivationError as exc:
            status, evidence_status = UNVERIFIABLE, EV_INCOMPLETE
            why = f"sidecar could not recompute the derivation: {exc}"
    else:
        refs = [ev.get("artifact_id") or ""]
        rec = _artifact_record(runs, refs[0], tenant)
        col = ev.get("column_id")
        if rec is None:
            evidence_status = EV_INCOMPLETE
            why = (f"sidecar could not retrieve artifact {refs[0]!r}; "
                   f"support not assessed")
        else:
            rows = list(rec.get("rows") or [])
            idx = deriv.row_index_for(str(ev.get("row_key") or ""), rows)
            if idx < 0 or not col or col not in rows[idx]:
                evidence_status = EV_INCOMPLETE
                why = (f"sidecar could not locate row "
                       f"{ev.get('row_key')!r} / column {col!r} in "
                       f"{refs[0]!r}; support not assessed")
            else:
                row = rows[idx]
                value = row[col]
                row_label = next((str(row[k]) for k in ("sector",
                                                        "sector_name")
                                  if k in row), None)
                metric = oracle.match_metric(
                    reference, col, c.get("unit"),
                    (column_units or {}).get(col))
                cmp_ = (oracle.compare(reference, metric, row_label,
                                       value, task)
                        if metric and task and row_label and
                        isinstance(value, (int, float)) else None)
                same_artifact = refs[0] == facts.get("artifact_id")
                if facts.get("population_ok") is False and same_artifact:
                    # The COHORT of this result failed the independent
                    # population assertion. That is metric-independent and
                    # already established -- not a cross-metric comparison.
                    status = CONTRADICTED
                    why = (f"matches its own result ({value}) but that "
                           f"result is over the wrong population "
                           f"(S1S2-POP failed)")
                    if cmp_:
                        why += f"; same-metric reference {cmp_[1]:,.2f}"
                elif cmp_ is not None:
                    reference_value = cmp_[1]
                    if cmp_[0]:
                        status = SUPPORTED
                        why = (f"cell {value:,.2f} = {metric} reference "
                               f"{cmp_[1]:,.2f} within tolerance")
                    else:
                        status = CONTRADICTED
                        why = (f"cell {value:,.2f} vs {metric} reference "
                               f"{cmp_[1]:,.2f}")
                else:
                    metric = None
                    status = SUPPORTED
                    why = ("located in the executed result (frozen row "
                           "resolver); frozen Finalizer validated; no "
                           "same-metric independent reference")
    return {
        "claim_id": c.get("claim_id"),
        "answer_span_ref": f"numeric_claims[{c.get('claim_id')}]",
        "extracted_text": c.get("display_value") or "",
        "claim_type": "numeric_derived" if c.get("derivation") else
        "numeric", "asserted_value": value if not hasattr(
            value, "as_tuple") else str(value),
        "units": c.get("unit"),
        "cohort": (reference or {}).get("population"),
        "period": (reference or {}).get("period"),
        "row_label": row_label, "result_refs": refs,
        "reference_metric": metric,
        "reference_value": reference_value,
        "reference_unit": ((reference or {}).get("metrics", {})
                           .get(metric, {}).get("unit") if metric else None),
        "extraction_method": "structured numeric claim (engine)",
        "extraction_confidence_class": "HIGH",
        "verification_status": status, "evidence_status": evidence_status,
        "frozen_validation": frozen,
        "assertion_refs": (["S1S2-POP"] if metric or (
            facts.get("population_ok") is False and refs and
            refs[0] == facts.get("artifact_id")) else []),
        "materiality": "MATERIAL", "evaluator_version": EVALUATOR_VERSION,
        "reviewer_status": ("NEEDS_REVIEW" if evidence_status ==
                            EV_INCOMPLETE else "UNREVIEWED"),
        "explanation": why}


def _claims(fr: dict | None, runs, tenant, task, reference, facts,
            frozen: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not fr:
        return []
    frozen = frozen or {"status": "UNKNOWN",
                        "message": "no answer.validated event found"}
    column_units: dict[str, str] = {}
    for t in fr.get("tables") or []:
        column_units.update(t.get("column_units") or {})
    claims = [_numeric_claim(c, runs, tenant, task, reference, facts,
                             frozen, column_units)
              for c in fr.get("numeric_claims") or []]
    rendered = fr.get("narrative") or ""
    for i, s in enumerate(_sentences(rendered)):
        numeric_rendered = any((c.get("display_value") or "#") in s
                               for c in fr.get("numeric_claims") or [])
        evidence_status = EV_COMPLETE
        if CAUSAL.search(s):
            ctype, status = "causal", UNSUPPORTED
            why = ("asserts a cause; no executed result or approved "
                   "reference in this run supports a causal link")
            conf = "MEDIUM"
        elif HEDGE.search(s):
            ctype, status, why, conf = ("qualified", QUALIFIED,
                                        "hedged or recommendation", "MEDIUM")
        elif numeric_rendered:
            continue       # covered by the structured claim above
        elif NUMBER.search(s):
            # The frozen Finalizer already refuses bare numbers in a
            # published narrative, so what is left is periods, labels and
            # counts it allows. Not bound to a claim here = needs review.
            ctype, status = "numeric_prose", UNVERIFIABLE
            why = ("a number in the validated narrative not bound to a "
                   "structured claim; needs review")
            conf, evidence_status = "LOW", EV_INCOMPLETE
        else:
            ctype, status, why, conf = ("factual", UNVERIFIABLE,
                                        "prose statement; needs review",
                                        "LOW")
        claims.append({
            "claim_id": f"narr-{i + 1}", "answer_span_ref":
            f"narrative.sentence[{i}]", "extracted_text": s[:500],
            "claim_type": ctype, "asserted_value": None, "units": None,
            "cohort": None, "period": None, "row_label": None,
            "result_refs": [],
            "extraction_method": "sentence split + cue patterns (lab)",
            "extraction_confidence_class": conf,
            "verification_status": status,
            "evidence_status": evidence_status,
            "frozen_validation": frozen, "assertion_refs": [],
            "materiality": "MATERIAL" if ctype == "causal" else "MINOR",
            "evaluator_version": EVALUATOR_VERSION,
            "reviewer_status": ("NEEDS_REVIEW" if status in (
                UNVERIFIABLE, UNSUPPORTED) else "UNREVIEWED"),
            "explanation": why})
    return claims


def _claim_rates(claims: list[dict], task, facts) -> dict[str, Any]:
    factual = [c for c in claims if c["claim_type"] in
               ("numeric", "numeric_derived", "causal", "numeric_prose",
                "factual")]
    assessed = [c for c in factual if c["verification_status"] in
                (SUPPORTED, CONTRADICTED, UNSUPPORTED)]
    contra = [c for c in assessed if c["verification_status"] == CONTRADICTED]
    unsup = [c for c in assessed if c["verification_status"] == UNSUPPORTED]

    def rate(n, d):
        return {"numerator": n, "denominator": d,
                "value": (n / d) if d else None,
                "display": f"{n}/{d}" if d else "N/A"}
    produced = facts.get("produced") or {}
    required = list(task.required_outputs) if task else []
    covered = []
    if task and produced:
        covered.append("per_sector_stage2_values")
        if any(c["claim_type"] in ("numeric", "numeric_derived")
               for c in claims):
            covered.append("largest_sector")
    return {
        "contradicted_rate": rate(len(contra), len(assessed)),
        "unsupported_rate": rate(len(unsup), len(assessed)),
        "assessment_coverage": rate(len(assessed), len(factual)),
        "required_output_coverage": rate(len(covered), len(required)),
        "extracted_factual": len(factual), "assessed": len(assessed),
        "unknown": len(factual) - len(assessed),
        "note": "no assessed factual claims: N/A, never 0% hallucination"
        if not assessed else ""}


def _stages(gens, checks, repair, claims, last, task) -> dict[str, Any]:
    by = {c["check_id"]: c for c in checks}
    call_ids = {s: [g["call_id"] for g in gens if s in g["stage_tags"]]
                for s in ("S1", "S2", "S3", "S4")}
    fused = [g["call_id"] for g in gens
             if "S1" in g["stage_tags"] and "S2" in g["stage_tags"]]
    stages: dict[str, Any] = {}
    pop = by.get("S1S2-POP")
    clar = by.get("S1-CLAR")
    # "No usable action" needs FROZEN evidence: every attempt recorded as
    # no_tool_call by the engine itself, and a run that did not complete.
    # Lost or unparseable telemetry is never evidence that no call happened.
    no_tool = bool(gens) and all(g["evidence_status"] == EV_NO_TOOL
                                 for g in gens) and \
        last["frozen_state"] not in ("COMPLETED", "PARTIAL", "REFERRED",
                                     "UNSUPPORTED")
    incomplete = [g["call_id"] for g in gens
                  if g["evidence_status"] == EV_INCOMPLETE]

    # S1
    if no_tool:
        s1 = {"status": FAIL, "note": "no usable action was produced"}
    elif clar:
        s1 = {"status": clar["outcome"], "note": clar.get("note", "")}
    elif pop:
        s1 = {"status": pop["outcome"] if not fused else NOT_SEP,
              "joint_with": "S2" if fused else None,
              "note": ("scope evidence is the submitted query; S1 and S2 "
                       "are evaluated jointly" if fused else
                       "scope inferred from the submitted query (no "
                       "separate plan is exposed); origin may be S1 or S2")}
        if not fused and pop["outcome"] == FAIL:
            s1["origin"] = "MULTI_STAGE_UNRESOLVED"
    elif task is None:
        s1 = {"status": UNKNOWN, "note": "no reference"}
    else:
        s1 = {"status": UNKNOWN, "note": "no scope evidence"}
    stages["S1"] = s1
    # S2
    s2_result = by.get("S2-RESULT")
    if not call_ids["S2"] and s2_result and \
            s2_result["outcome"] in (PASS, FAIL):
        # An executed artifact exists: execution is evidenced by the frozen
        # store even when the call attribution is incomplete.
        stages["S2"] = {"status": s2_result["outcome"],
                        "note": "execution evidenced by the frozen result "
                                "artifact; call attribution incomplete"}
    elif not call_ids["S2"]:
        stages["S2"] = {"status": NOT_REACHED if last["frozen_state"] in (
            "WAITING_FOR_USER", "FAILED") else NOT_OBSERVED,
            "note": "no execute_analysis submission"}
    elif by.get("S2-RESULT"):
        stages["S2"] = {"status": by["S2-RESULT"]["outcome"]}
    else:
        stages["S2"] = {"status": UNKNOWN, "note": "no reference"}
    # S3
    stages["S3"] = {"status": repair["status"], "note": repair["note"]}
    # S4
    fr = last["final_response"] or {}
    if last["frozen_state"] == "WAITING_FOR_USER":
        stages["S4"] = {"status": NOT_REACHED,
                        "note": "waiting for the user's clarification"}
    elif not fr or fr.get("disposition") not in ("answer", "partial_answer"):
        stages["S4"] = {"status": NOT_REACHED,
                        "note": "no final answer (an earlier step failed); "
                                "not an independent narration failure"}
    else:
        bad = [c for c in claims if c["verification_status"] in
               (CONTRADICTED, UNSUPPORTED)]
        # Only a claim whose evidence WAS inspected and found wanting counts
        # against S4. An UNVERIFIABLE claim (the sidecar could not map it)
        # is a review item, never a failure.
        own = [c for c in bad if c["claim_type"] == "causal" and
               c["verification_status"] == UNSUPPORTED]
        inherited = [c for c in bad if c not in own]
        unverifiable = [c for c in claims
                        if c.get("evidence_status") == EV_INCOMPLETE]
        if own:
            stages["S4"] = {"status": FAIL, "note": f"{len(own)} unsupported "
                            f"claim(s) authored in the narrative"}
        elif inherited:
            stages["S4"] = {"status": PARTIAL, "note": (
                "faithful to its own result; inherits the upstream scope "
                "error (not an independent hallucination)"),
                "inherited": True}
        elif by.get("S4-LARGEST"):
            stages["S4"] = {"status": by["S4-LARGEST"]["outcome"]}
        else:
            stages["S4"] = {"status": UNKNOWN, "note": "no reference"}
        if unverifiable and "S4" in stages:
            stages["S4"]["evidence_status"] = EV_INCOMPLETE
            stages["S4"]["note"] = (stages["S4"].get("note", "") + (
                f" {len(unverifiable)} claim(s) could not be mapped by the "
                f"sidecar and need review; the frozen Finalizer's own "
                f"validation is shown per claim.")).strip()
    for s in stages:
        stages[s].setdefault("evidence_status", (
            EV_INCOMPLETE if incomplete and s in ("S1", "S2") else
            EV_FROZEN if any(g["evidence_status"] == EV_FROZEN
                             for g in gens if s in g["stage_tags"])
            else EV_COMPLETE))
        stages[s]["calls"] = call_ids[s]
        stages[s]["shared_calls"] = [g["call_id"] for g in gens
                                     if s in g["stage_tags"] and
                                     len(g["stage_tags"]) > 1]
        stages[s]["checks"] = [c["check_id"] for c in checks
                               if s in c["stage"]]
        stages[s]["evidence_confidence"] = (
            "HIGH" if stages[s]["checks"] else
            "MEDIUM" if stages[s]["calls"] else "LOW")
    return stages


def _metrics(child, turns, calls, app_spans, fixture, runs, profile
             ) -> dict[str, Any]:
    m: dict[str, Any] = {}
    enq, adm = child.get("enqueued_monotonic"), child.get(
        "admitted_monotonic")
    m["queue_delay_ms"] = (mx.measured((adm - enq) * 1000, "ms",
                                       "coordinator monotonic",
                                       "child enqueued -> admitted")
                           if enq and adm else
                           mx.unavailable("ms", "not admitted")).to_dict()
    service = sum(((t["finished_monotonic"] or 0) -
                   (t["started_monotonic"] or 0)) * 1000
                  for t in turns if t.get("finished_monotonic"))
    wait = 0.0
    for a, b in zip(turns, turns[1:], strict=False):
        if b["kind"] == "CLARIFICATION" and a.get("finished_monotonic"):
            wait += (b["started_monotonic"] - a["finished_monotonic"]) * 1000
    m["service_ms"] = mx.measured(service, "ms", "coordinator monotonic",
                                  "sum over turns of run accepted -> frozen "
                                  "Worker returned; excludes user wait"
                                  ).to_dict()
    m["user_wait_ms"] = (mx.derived(wait, "ms", "gap between a WAITING turn "
                                    "and its clarification turn")
                         if len(turns) > 1 else
                         mx.unavailable("ms", "no clarification resumed")
                         ).to_dict()
    spans = [(c["start_monotonic"] * 1000, c["end_monotonic"] * 1000)
             for c in calls if c.get("start_monotonic") is not None]
    prov = mx.interval_union_ms(spans)
    m["provider_call_ms"] = (mx.measured(prov, "ms", "lab ObservingProvider",
                                         "interval union of converse() spans"
                                         ) if spans else
                             mx.unavailable("ms", "no provider calls")
                             ).to_dict()
    m["provider_call_ms_sum"] = mx.derived(
        sum(c["duration_ms"] or 0 for c in calls), "ms",
        "sum of unique call spans (dedup by call_id)").to_dict()
    app = mx.interval_union_ms(app_spans)
    m["creditprobe_ms"] = mx.measured(
        app, "ms", "frozen events elapsed_ms (ms resolution)",
        "interval union of tool.requested -> tool.completed/failed; "
        "validation + execution").to_dict()
    m["unallocated_ms"] = mx.derived(
        max(0.0, service - prov - app), "ms", "service - provider - "
        "creditprobe", "context build, finalizer, persistence, clock "
        "granularity; overlap disclosed, never negative").to_dict()
    m["load_ms"] = mx.unavailable(
        "ms", "model residency/load not exposed by this route" if not
        fixture else "fixture: nothing to load").to_dict()
    m["first_protocol_event_ms"] = mx.unavailable(
        "ms", "non-streaming route (OG-05)").to_dict()
    m["first_visible_text_ms"] = mx.unavailable(
        "ms", "non-streaming route (OG-05)").to_dict()
    m["first_complete_tool_ms"] = mx.unavailable(
        "ms", "non-streaming route (OG-05)").to_dict()
    ins = [c["input_tokens"] for c in calls if c["input_tokens"] is not None]
    outs = [c["output_tokens"] for c in calls
            if c["output_tokens"] is not None]
    tstatus = mx.ESTIMATED if fixture else mx.MEASURED
    src = ("fixture synthetic counter" if fixture else
           "provider-native usage per call")
    m["calls"] = mx.measured(len(calls), "count", "frozen call_report"
                             ).to_dict()
    m["input_tokens"] = (mx.Metric(sum(ins), "tokens", tstatus, src,
                                   "", "sum over unique calls; cache "
                                   "subsets not added").to_dict()
                         if ins else mx.unavailable(
                             "tokens", "no usage reported").to_dict())
    m["output_tokens"] = (mx.Metric(sum(outs), "tokens", tstatus, src, "",
                                    "sum over unique calls").to_dict()
                          if outs else mx.unavailable(
                              "tokens", "no usage reported").to_dict())
    m["peak_context_tokens"] = (mx.Metric(max(ins), "tokens", tstatus, src,
                                          "", "largest single-call input "
                                          "(not a sum)").to_dict()
                                if ins else mx.unavailable(
                                    "tokens", "no usage").to_dict())
    m["reasoning_tokens"] = mx.unavailable(
        "tokens", "not separately reported by this route (OG-06)").to_dict()
    m["tokenizer"] = profile.get("tokenizer_revision") or (
        "fixture (no tokenizer)" if fixture else "provider-native "
        "(identifier not exposed)")
    gen_s = sum((c["duration_ms"] or 0) for c in calls) / 1000.0
    m["client_observed_output_rate"] = (
        mx.derived(sum(outs) / gen_s, "tokens/s", "output tokens / "
                   "client-observed call seconds (includes prompt "
                   "processing and transport)").to_dict()
        if outs and gen_s > 0 and not fixture else
        mx.unavailable("tokens/s", "fixture" if fixture else
                       "no timing").to_dict())
    native = [c["native_timing"] for c in calls if c.get("native_timing")]
    m["server_generation_rate"] = (
        mx.measured(sum(n.get("eval_count", 0) for n in native) /
                    max(1e-9, sum(n.get("eval_duration_ms", 0)
                                  for n in native) / 1000.0),
                    "tokens/s", "runtime-native eval_count/eval_duration"
                    ).to_dict() if native else
        mx.unavailable("tokens/s", "runtime does not expose native "
                       "generation timing on this route").to_dict())
    spend = {"committed_usd": 0.0, "pending_usd": 0.0}
    for t in turns:
        s = runs.spend(t["run_id"])
        spend["committed_usd"] += float(s.get("committed_usd") or 0)
        spend["pending_usd"] += float(s.get("pending_usd") or 0)
    route = profile.get("route")
    if fixture:
        m["cost_usd"] = mx.derived(0.0, "USD", "fixture: no inference "
                                   "performed").to_dict()
    elif route == "anthropic":
        m["cost_usd"] = mx.measured(
            spend["committed_usd"], "USD",
            "frozen Ledger settled usage x frozen verified price card "
            "(2026-09-21)").to_dict()
    else:
        m["cost_usd"] = mx.estimated(
            spend["committed_usd"], "USD",
            "local marginal token charge only; hardware/power/cloud time "
            "NOT included").to_dict()
    m["infrastructure_cost_usd"] = mx.unavailable(
        "USD", "no allocated infrastructure cost configured").to_dict()
    m["cost_pending_usd"] = spend["pending_usd"]
    return m


_TAXONOMY = ("ADAPTER_OR_PROTOCOL", "RUNTIME_CAPABILITY",
             "RESOURCE_OR_CONTEXT", "CATALOGUE_OR_REFERENCE",
             "S1_SCOPE_OR_CLARIFICATION", "S2_ANALYTICAL_OR_AUTHORING",
             "S3_REPAIR_OR_CONTROL", "S4_INTERPRETATION",
             "BASELINE_OR_INFRASTRUCTURE", "MEASUREMENT_OR_REVIEW_GAP")


def _failures(ev: dict[str, Any], task) -> list[dict[str, Any]]:
    cards = []
    fx = ev["fixture"]
    base = {"artifact": {"child_run_id": ev["child_run_id"]},
            "fixture": fx}
    err = ev.get("error_code") or ""
    if ev.get("frozen_state") == "FAILED" and ev["calls"] and all(
            c["evidence_status"] == EV_NO_TOOL for c in ev["calls"]):
        cards.append(base | {
            "primary_category": "RUNTIME_CAPABILITY",
            "supporting_categories": ["S3_REPAIR_OR_CONTROL"],
            "symptom": f"no usable tool call on any turn ({err})",
            "failed_requirement": "forced tool use on action turns (A09)",
            "likely_owner": "model/runtime route",
            "origin_confidence": "ORIGIN_CONFIRMED",
            "affected_stages": ["S1", "S2", "S3", "S4"],
            "inherited_effects": ["no answer: S4 NOT_REACHED"],
            "earliest_event": ev["calls"][0]["call_id"] if ev["calls"]
            else None, "severity": "CRITICAL",
            "next_diagnostic": "inspect the raw provider payload: if it "
                               "carried a tool call the adapter dropped, "
                               "reclassify ADAPTER_OR_PROTOCOL",
            "intervention_category": "verify another compatible route",
            "approval_needed": "none for diagnosis", "model_failure": True,
            "detail": "raw provider output (observer) had no tool_use "
                      "block: model-generated invalidity, not adapter "
                      "corruption"})
    resource = [c for c in ev["calls"] if re.search(
        r"out.of.memory|\boom\b|memory|context length|context window|"
        r"too many tokens|disk", c.get("provider_error") or "", re.I)]
    if resource:
        cards.append(base | {
            "primary_category": "RESOURCE_OR_CONTEXT",
            "supporting_categories": [],
            "symptom": resource[0]["provider_error"],
            "failed_requirement": "the unchanged task must fit the "
                                  "profile's memory/context (O04)",
            "likely_owner": "deployment profile / host",
            "origin_confidence": "ORIGIN_LIKELY",
            "affected_stages": [], "inherited_effects": [
                "the investigation stopped; partial evidence kept"],
            "earliest_event": resource[0]["call_id"], "severity": "MAJOR",
            "next_diagnostic": "same model on approved larger hardware, or "
                               "a smaller pinned quantisation as a NEW "
                               "profile; never trim the task",
            "intervention_category": "profile/runtime",
            "approval_needed": "hardware or new-profile approval",
            "model_failure": False, "detail": ""})
    if err and err.startswith(("DEADLINE", "EXPIRED")) or \
            ev.get("frozen_state") == "EXPIRED":
        cards.append(base | {
            "primary_category": "RESOURCE_OR_CONTEXT",
            "supporting_categories": [], "symptom": f"deadline ({err})",
            "failed_requirement": "frozen run deadline (OG-01)",
            "likely_owner": "deployment profile", "origin_confidence":
            "ORIGIN_LIKELY", "affected_stages": [], "inherited_effects": [],
            "earliest_event": None, "severity": "MAJOR",
            "next_diagnostic": "same model on faster approved hardware "
                               "(same-model hardware diagnostic)",
            "intervention_category": "profile/runtime",
            "approval_needed": "remote hardware or a separately named "
                               "longer-deadline variant",
            "model_failure": False, "detail": ""})
    for c in ev["checks"]:
        if c["outcome"] != FAIL:
            continue
        if c["check_id"] == "S1S2-POP":
            wrong = ev["facts"].get("matches_wrong_population")
            cards.append(base | {
                "primary_category": "S1_SCOPE_OR_CLARIFICATION",
                "supporting_categories": ["S2_ANALYTICAL_OR_AUTHORING"],
                "symptom": "executable, plausible answer over the wrong "
                           "population" + (" (whole book, all stages)"
                                           if wrong else ""),
                "failed_requirement": c["expected"],
                "artifact": base["artifact"] | c["evidence_ref"],
                "likely_owner": "model (S1/S2 jointly)",
                "origin_confidence": "MULTI_STAGE_UNRESOLVED",
                "affected_stages": ["S1", "S2", "S4"],
                "inherited_effects": ["final numbers and narrative inherit "
                                      "the scope error"],
                "earliest_event": c["check_id"], "severity": "CRITICAL",
                "next_diagnostic": "controlled checkpoint replay with the "
                                   "verified cohort supplied at a real seam "
                                   "(needs Deep diagnostics approval)",
                "intervention_category": "grounding/scope diagnostic",
                "approval_needed": "Deep diagnostics preset",
                "model_failure": True, "detail": c.get("detail")})
    for cl in ev["claims"]:
        if cl["claim_type"] == "causal" and cl["verification_status"] == \
                UNSUPPORTED:
            cards.append(base | {
                "primary_category": "S4_INTERPRETATION",
                "supporting_categories": [],
                "symptom": "unsupported causal claim",
                "failed_requirement": "claims supported by evidence (Q07)",
                "artifact": base["artifact"] | {"claim_id": cl["claim_id"]},
                "likely_owner": "model (S4)",
                "origin_confidence": "ORIGIN_CONFIRMED",
                "affected_stages": ["S4"], "inherited_effects": [],
                "earliest_event": cl["claim_id"], "severity": "MAJOR",
                "next_diagnostic": "S4 replay on the same verified result "
                                   "bundle; test a governed-definition/"
                                   "instruction variant first",
                "intervention_category": "prompt/definition diagnostic",
                "approval_needed": "none for diagnosis",
                "model_failure": True, "detail": cl["extracted_text"]})
    return cards


def _evidence_gap_card(ev: dict[str, Any]) -> dict[str, Any] | None:
    calls = [c["call_id"] for c in ev.get("calls") or []
             if c.get("evidence_status") == EV_INCOMPLETE]
    claims = [c["claim_id"] for c in ev.get("claims") or []
              if c.get("evidence_status") == EV_INCOMPLETE and
              c["claim_type"] in ("numeric", "numeric_derived")]
    if not (calls or claims):
        return None
    return {"primary_category": "MEASUREMENT_OR_REVIEW_GAP",
            "supporting_categories": [],
            "symptom": (f"{len(calls)} call(s) without recoverable tool "
                        f"names; {len(claims)} structured claim(s) the "
                        f"sidecar could not map"),
            "failed_requirement": "complete lab evidence mapping",
            "artifact": {"child_run_id": ev["child_run_id"],
                         "calls": calls, "claims": claims},
            "likely_owner": "lab evaluator / observation",
            "origin_confidence": "ORIGIN_CONFIRMED",
            "affected_stages": [], "inherited_effects": [],
            "earliest_event": (calls or claims)[0], "severity": "INFO",
            "next_diagnostic": "inspect the frozen record for these items; "
                               "the frozen Finalizer's own validation is "
                               "shown per claim",
            "intervention_category": "evidence mapping",
            "approval_needed": "none", "model_failure": False,
            "fixture": ev["fixture"], "detail": "EVIDENCE_INCOMPLETE"}


def _first_divergence(ev: dict[str, Any]) -> dict[str, Any] | None:
    order = ["S1-CLAR", "S1S2-POP", "S2-RESULT", "S4-LARGEST"]
    failing = [c for c in ev["checks"] if c["outcome"] == FAIL]
    failing.sort(key=lambda c: order.index(c["check_id"])
                 if c["check_id"] in order else 99)
    if ev["failures"] and ev["failures"][0]["primary_category"] in (
            "RUNTIME_CAPABILITY", "RESOURCE_OR_CONTEXT"):
        f = ev["failures"][0]
        return {"stage": "protocol/runtime", "event": f["earliest_event"],
                "confidence": f["origin_confidence"],
                "downstream": f["affected_stages"], "summary": f["symptom"]}
    if failing:
        c = failing[0]
        return {"stage": c["stage"], "event": c["check_id"],
                "confidence": ("MULTI_STAGE_UNRESOLVED" if "+" in c["stage"]
                               else "ORIGIN_LIKELY"),
                "downstream": [s for s in ("S2", "S3", "S4")
                               if s not in c["stage"]],
                "summary": c["actual"]}
    s4 = [cl for cl in ev["claims"] if cl["verification_status"] ==
          UNSUPPORTED and cl["claim_type"] == "causal"]
    if s4:
        return {"stage": "S4", "event": s4[0]["claim_id"],
                "confidence": "ORIGIN_CONFIRMED", "downstream": [],
                "summary": "unsupported causal claim"}
    return None


# ---- Opus Match (comparator agreement; NOT correctness) ---------------------

def opus_match(cand: dict[str, Any], comp: dict[str, Any] | None
               ) -> dict[str, Any]:
    if comp is None or comp.get("execution_state") != "COMPLETED":
        reason = ("comparator unavailable" if comp is None else
                  f"comparator did not complete ({comp.get('execution_state')})")
        return {s: {"pct": None, "display": "N/A", "reason": reason,
                    "checks": []} for s in ("S1", "S2", "S3", "S4")}
    if not cand.get("turns") or cand.get("execution_state") not in (
            "COMPLETED", "WAITING_USER"):
        reason = (f"candidate did not produce comparable evidence "
                  f"({cand.get('execution_state')})")
        return {s: {"pct": None, "display": "N/A", "reason": reason,
                    "checks": []} for s in ("S1", "S2", "S3", "S4")}
    cf, kf = cand.get("facts") or {}, comp.get("facts") or {}
    cp, kp = cf.get("produced") or {}, kf.get("produced") or {}

    def chk(cid, desc, weight, a, b, agree):
        return {"check_id": cid, "description": desc, "weight": weight,
                "candidate": a, "comparator": b,
                "agree": agree if (a is not None and b is not None)
                else None}
    s1 = [chk("M-S1-POP", "same population (result keys and totals)", 2,
              sorted(cp) or None, sorted(kp) or None,
              bool(cp) and bool(kp) and set(cp) == set(kp) and all(
                  abs(cp[k] - kp[k]) <= 0.01 for k in cp)),
          chk("M-S1-CLAR", "same clarification decision", 1,
              bool(cf.get("clarification")), bool(kf.get("clarification")),
              bool(cf.get("clarification")) == bool(kf.get("clarification")))]
    s2 = [chk("M-S2-RESULT", "same result set within 0.01 (semantics, not "
              "SQL text)", 2, len(cp) or None, len(kp) or None,
              bool(cp) and bool(kp) and set(cp) == set(kp) and all(
                  abs(cp[k] - kp[k]) <= 0.01 for k in cp))]
    cr, kr = cand.get("repair") or {}, comp.get("repair") or {}
    s3 = []
    if cr.get("opportunities") or kr.get("opportunities"):
        s3.append(chk("M-S3-RECOG", "both recognised and repaired their "
                      "errors (or had none)", 1,
                      cr.get("valid_repairs") == cr.get("opportunities"),
                      kr.get("valid_repairs") == kr.get("opportunities"),
                      (cr.get("valid_repairs") == cr.get("opportunities")) ==
                      (kr.get("valid_repairs") == kr.get("opportunities"))))
    ctop = max(cp, key=cp.get) if cp else None
    ktop = max(kp, key=kp.get) if kp else None

    def unsupported(ev):
        return sum(1 for c in ev.get("claims") or []
                   if c["verification_status"] in (UNSUPPORTED,
                                                   CONTRADICTED))
    def answered(ev):
        return ((ev.get("answer") or {}).get("disposition") in
                ("answer", "partial_answer"))
    s4 = []
    if answered(cand) and answered(comp):
        s4 = [chk("M-S4-TOP", "same material conclusion (largest sector)",
                  2, ctop, ktop, ctop == ktop),
              chk("M-S4-CLAIMS", "same claim-support profile (no "
                  "unsupported or contradicted claims on both)", 1,
                  unsupported(cand), unsupported(comp),
                  (unsupported(cand) == 0) == (unsupported(comp) == 0))]
    out = {}
    for s, lst in (("S1", s1), ("S2", s2), ("S3", s3), ("S4", s4)):
        assessed = [c for c in lst if c["agree"] is not None]
        w = sum(c["weight"] for c in assessed)
        pct = (100.0 * sum(c["weight"] for c in assessed if c["agree"]) / w
               if w else None)
        out[s] = {"pct": pct, "display": f"{pct:.0f}%" if pct is not None
                  else "N/A", "assessed": len(assessed), "defined": len(lst),
                  "reason": "" if pct is not None else
                  "insufficient evidence", "checks": lst,
                  "weights_version": "opus-match-1"}
    return out


# ---- the comparison --------------------------------------------------------------

def evaluate_comparison(coord, cid: str) -> dict[str, Any]:
    status = coord.status(cid)
    spec = status["spec"]
    events = coord.store.events(cid, coord.cfg.tenant_id, 0, 100000)
    tenant = coord.data_tenant(spec.get("domain") or "corporate")
    for e in events:
        e["payload_obj"] = (json.loads(coord.store.get_blob(e["payload_ref"]))
                            if e.get("payload_ref") and
                            e["event_type"].startswith("provider.") else None)
    task = oracle.find_task(spec["question_text"], spec.get("task_id") or "")
    reference = None
    if task and task.domain == spec.get("domain"):
        release = spec["data_snapshot_id"].split("@")[0]
        reference = oracle.expected(task, release)
    kids = []
    raw_children = {c["child_run_id"]: c for c in
                    coord.store.children(cid)}
    for c in status["children"]:
        row = raw_children[c["child_run_id"]] | {
            "display_name": c["display_name"], "turns": c["turns"]}
        prof = json.loads(row["profile_json"])
        kids.append(evaluate_child(row, runs=coord.runs, events=events,
                                   spec=spec, task=task,
                                   reference=reference, tenant=tenant,
                                   profile=prof))
    comp_id = spec.get("comparator_id")
    comps = [k for k in kids if k["profile_id"] == comp_id]
    comp = comps[0] if comps else None
    comparator = {
        "profile_id": comp_id,
        "is_opus": comp_id == "opus-frozen",
        "is_fixture": bool(comp and comp["fixture"]),
        "status": ("OPUS_BASELINE_UNAVAILABLE" if comp_id == "opus-frozen"
                   and (comp is None or comp["execution_state"] !=
                        "COMPLETED") else
                   "COMPARATOR_UNAVAILABLE" if comp is None or
                   comp["execution_state"] != "COMPLETED" else "READY"),
        "note": ("the comparator is agreement, not truth; a FIXTURE "
                 "comparator is not Opus" if comp and comp["fixture"]
                 else "the comparator is agreement, not truth")}
    for k in kids:
        k["opus_match"] = (opus_match(k, comp) if k is not comp else None)
    started = next((e["monotonic_time"] for e in events
                    if e["event_type"] == "comparison.created"), None)
    settled = [e["monotonic_time"] for e in events
               if e["event_type"] == "comparison.settled"]
    elapsed = (mx.measured((settled[-1] - started) * 1000, "ms",
                           "lab events monotonic",
                           "click accepted -> last child settled (includes "
                           "queueing across models)").to_dict()
               if started and settled else
               mx.unavailable("ms", "not settled yet").to_dict())
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "oracle_version": oracle.ORACLE_VERSION,
        "comparison_id": cid, "spec_hash": status["spec_hash"],
        "group_state": status["state"],
        "task": task.spec() if task else None,
        "reference": ({k: v for k, v in reference.items()
                       if k != "wrong_population_values"}
                      if reference else None),
        "comparator": comparator, "comparison_elapsed_ms": elapsed,
        "children": kids,
        "summary": _summary(kids),
        "comparison_class": _comparison_class(spec, kids),
        "release_claim": "EXPERIMENTAL / LAB_IMPLEMENTED",
    }


def _comparison_class(spec, kids) -> list[str]:
    tags = ["SEMANTIC_BASELINE_COMPARISON"]
    if any(k["fixture"] for k in kids):
        tags.append("FIXTURE_DEMONSTRATION")
    if spec.get("resource_lane") == "remote_parallel":
        tags.append("CROSS_DEPLOYMENT_COMPARISON")
    elif any(k["profile_id"] == "opus-frozen" and k["turns"] for k in kids):
        tags.append("CROSS_DEPLOYMENT_COMPARISON")
    else:
        tags.append("SAME_HARDWARE_COMPARISON")
    return tags


def _summary(kids: list[dict]) -> dict[str, Any]:
    ran = [k for k in kids if k.get("turns")]
    return {
        "selected": len(kids), "ran": len(ran),
        "blocked": sum(1 for k in kids if k["execution_state"] == "BLOCKED"),
        "completed": sum(1 for k in kids
                         if k["execution_state"] == "COMPLETED"),
        "waiting_user": sum(1 for k in kids
                            if k["execution_state"] == "WAITING_USER"),
        "failed": sum(1 for k in kids if k["execution_state"] == "FAILED"),
        "independently_verified_success": sum(
            1 for k in ran if any(c["check_id"] == "S1S2-POP" and
                                  c["outcome"] == PASS for c in k["checks"])
            and not any(c["verification_status"] in (CONTRADICTED,
                                                    UNSUPPORTED)
                        for c in k["claims"])),
        "note": "one question: a concrete finding, not a ranking; "
                "insufficient sample for any training decision"}
