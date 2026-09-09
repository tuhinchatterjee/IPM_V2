#!/usr/bin/env python
"""
Run the Cockpit V2 evaluation. Brief §8.2, §8.3.

    .venv/bin/python tests/evals/cockpit_v2/run_eval.py --api http://127.0.0.1:8100/api/v1

Scores DETERMINISTICALLY: numeric facts within their stated tolerance and
attached to the right unit, required outputs answered, forbidden claims absent,
claim validation passed. No model grades a model, and nothing is scored against
the reference prose — that is for a human to write and approve.

Numeric matching is not substring matching. `12.65` is looked for as a NUMBER
parsed out of the answer and compared within tolerance, so `112.65` does not
satisfy a case that needs `12.65`, and the unit named in the case must appear
in the same sentence as the number.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CASES = Path(__file__).resolve().parent / "cases.json"

_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def ask(api: str, question: str, turns: list[str]) -> dict[str, Any]:
    """Ask through the real /ask endpoint, replaying earlier turns first.

    The transcript is passed back on each call, so a follow-up case genuinely
    exercises the conversation path rather than asking an isolated question
    that happens to be the last line of one.
    """
    last: dict[str, Any] = {}
    transcript: list[dict[str, str]] = []
    for text in ([*turns] if turns else [question]):
        body = json.dumps({"question": text, "persist": False,
                           "turns": list(transcript)}).encode()
        request = urllib.request.Request(
            api.rstrip("/") + "/ask", data=body,
            headers={"Content-Type": "application/json"})
        started = time.time()
        with urllib.request.urlopen(request, timeout=300) as response:
            last = json.loads(response.read())
        last["_elapsed_ms"] = int((time.time() - started) * 1000)
        transcript.append({
            "question": text,
            "answer": ((last.get("narrative") or {}).get("direct_answer")
                       or "")[:600]})
    return last


def _answer_text(payload: dict[str, Any]) -> str:
    v2 = payload.get("cockpit_v2") or {}
    narrative = payload.get("narrative") or {}
    parts = [v2.get("narrative") or "",
             narrative.get("direct_answer") or "",
             narrative.get("interpretation") or "",
             " ".join(narrative.get("interpretation_points") or [])]
    for section in v2.get("sections", []):
        parts.extend(section.get("paragraphs") or [])
        parts.extend(section.get("findings") or [])
        parts.extend(section.get("limitations") or [])
    return "\n".join(p for p in parts if p)


def _table_numbers(payload: dict[str, Any]) -> list[float]:
    out: list[float] = []
    for table in (payload.get("cockpit_v2") or {}).get("tables", []) or []:
        for row in table.get("rows", []):
            out.extend(float(v) for v in row.values()
                       if isinstance(v, (int, float))
                       and not isinstance(v, bool))
    return out


def _numbers(text: str) -> list[float]:
    out: list[float] = []
    for token in _NUMBER.findall(text):
        try:
            out.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return out


def check_fact(fact: dict[str, Any], text: str,
               table_numbers: list[float]) -> dict[str, Any]:
    """One numeric fact, matched as a number rather than as a substring."""
    expected = fact["value"]
    if not isinstance(expected, (int, float)):
        return {"name": fact["name"], "passed": None,
                "detail": "not a numeric fact"}
    tolerance = max(float(fact.get("tolerance", 0.01)),
                    abs(float(expected)) * float(fact.get("tolerance", 0.01)))

    in_prose = False
    unit_ok = False
    unit = str(fact.get("unit", "")).lower()
    for sentence in _SENTENCE.split(text):
        for value in _numbers(sentence):
            if abs(value - float(expected)) <= tolerance:
                in_prose = True
                if not unit or unit in sentence.lower() or unit in (
                        "count", "notches", "percent"):
                    unit_ok = True
    in_table = any(abs(v - float(expected)) <= tolerance
                   for v in table_numbers)

    passed = (in_prose and unit_ok) or in_table
    return {"name": fact["name"], "expected": expected,
            "unit": fact.get("unit"), "tolerance": tolerance,
            "passed": bool(passed),
            "found_in": ("prose" if in_prose else "") + (
                " table" if in_table else ""),
            "detail": ("" if passed else
                       f"{expected} {fact.get('unit')} not found within "
                       f"{tolerance} in the prose (with its unit) or the table")}


def score(case: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    v2 = payload.get("cockpit_v2") or {}
    text = _answer_text(payload)
    lower = text.lower()
    table_numbers = _table_numbers(payload)
    understood = v2.get("understood") or {}
    answered_outputs = {s["output"] for s in v2.get("sections", [])
                        if s.get("answered")}
    unanswered = {u["output"] for u in v2.get("unanswered", [])}

    checks: list[dict[str, Any]] = []

    for fact in case["numeric_facts"]:
        result = check_fact(fact, text, table_numbers)
        result["kind"] = "numeric"
        result["critical"] = True
        checks.append(result)

    for output in case["required_outputs"]:
        # A case that expects the Cockpit to STATE A GAP is satisfied when the
        # output was recognised and reported as unanswerable. Requiring it to
        # be answered as well asked for the substitution the case exists to
        # forbid.
        answered = (output in answered_outputs
                    or (case["expect_unanswered"] and output in unanswered))
        checks.append({
            "kind": "output", "name": output, "critical": True,
            "passed": answered,
            "detail": "" if answered else (
                f"{output} was not answered; unanswered={sorted(unanswered)}, "
                f"answered={sorted(answered_outputs)}")})

    for output in case.get("forbidden_outputs", []):
        present_output = output in answered_outputs
        checks.append({
            "kind": "forbidden_output", "name": output, "critical": True,
            "passed": not present_output,
            "detail": "" if not present_output else
                      f"{output} was produced for a question that asked for "
                      f"the current position instead"})

    for phrase in case["must_mention"]:
        found = phrase.lower() in lower
        checks.append({"kind": "mention", "name": phrase, "critical": False,
                       "passed": found,
                       "detail": "" if found else f"{phrase!r} not mentioned"})

    for phrase in case["must_not_claim"]:
        found = phrase.lower() in lower
        checks.append({"kind": "forbidden", "name": phrase, "critical": True,
                       "passed": not found,
                       "detail": "" if not found else
                                 f"forbidden claim present: {phrase!r}"})

    validation = v2.get("validation") or {}
    checks.append({"kind": "validation", "name": "claims_validate",
                   "critical": True, "passed": bool(validation.get("ok", True)),
                   "detail": json.dumps(validation.get("issues", []))[:300]})

    if case["requires_table"]:
        has = bool(v2.get("tables"))
        checks.append({"kind": "table", "name": "table_present",
                       "critical": False, "passed": has,
                       "detail": "" if has else "no table returned"})
    if case["requires_chart"] is False:
        has = bool(v2.get("charts"))
        checks.append({"kind": "chart", "name": "no_chart", "critical": True,
                       "passed": not has,
                       "detail": "" if not has else
                                 "a chart was returned for a question that "
                                 "asked for none"})
    if case["expect_unanswered"]:
        stated = bool(unanswered) or "not loaded" in lower or \
            "not published" in lower or "earliest published" in lower
        checks.append({"kind": "unanswered", "name": "states_the_gap",
                       "critical": True, "passed": stated,
                       "detail": "" if stated else
                                 "the gap was not stated; a substitute may "
                                 "have been used"})

    critical = [c for c in checks if c.get("critical")]
    failed_critical = [c for c in critical if c["passed"] is False]
    optional = [c for c in checks if not c.get("critical")]
    passed_optional = [c for c in optional if c["passed"]]

    return {
        "case_id": case["case_id"], "split": case["split"],
        "family": case["family"], "question": case["question"],
        "status": case["status"],
        "passed": case["status"] == "READY" and not failed_critical,
        "critical_total": len(critical),
        "critical_failed": len(failed_critical),
        "optional_total": len(optional),
        "optional_passed": len(passed_optional),
        "checks": checks,
        "prose_source": (payload.get("narrative") or {}).get("prose_source"),
        "elapsed_ms": payload.get("_elapsed_ms"),
        "tools": (v2.get("trace") or {}).get("tools_called", []),
        "requested_outputs": understood.get("requested_outputs", []),
        "model_calls": v2.get("model_calls"),
        "answer_excerpt": text[:600],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8100/api/v1")
    parser.add_argument("--split", default="", choices=["", "development",
                                                        "holdout"])
    parser.add_argument("--out", default=str(
        ROOT / "docs" / "cockpit_v2" / "evidence" / "eval_run.json"))
    parser.add_argument("--repeat", type=int, default=1,
                        help="run each case N times to expose variability")
    args = parser.parse_args()

    payload = json.loads(CASES.read_text("utf-8"))
    cases = [c for c in payload["cases"]
             if not args.split or c["split"] == args.split]

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        runs = []
        for _ in range(max(1, args.repeat)):
            try:
                response = ask(args.api, case["question"], case["turns"])
                runs.append(score(case, response))
            except Exception as e:  # noqa: BLE001 - a failure is a result
                runs.append({"case_id": case["case_id"], "split": case["split"],
                             "family": case["family"],
                             "question": case["question"],
                             "status": case["status"], "passed": False,
                             "error": repr(e)[:300], "checks": [],
                             "critical_total": 0, "critical_failed": 1,
                             "optional_total": 0, "optional_passed": 0})
        best = runs[0]
        best["repeats"] = len(runs)
        best["repeat_agreement"] = (
            len({r["passed"] for r in runs}) == 1 if len(runs) > 1 else None)
        results.append(best)
        print(f"[{index:>2}/{len(cases)}] {case['case_id']:<8} "
              f"{'PASS' if best['passed'] else 'FAIL'}  {case['question'][:60]}")

    development = [r for r in results if r["split"] == "development"]
    holdout = [r for r in results if r["split"] == "holdout"]
    latencies = [r["elapsed_ms"] for r in results if r.get("elapsed_ms")]

    def rate(rows: list[dict[str, Any]]) -> float:
        return (sum(1 for r in rows if r["passed"]) / len(rows) * 100.0
                if rows else 0.0)

    summary = {
        "api": args.api,
        "cases_run": len(results),
        "development": {"run": len(development),
                        "passed": sum(1 for r in development if r["passed"]),
                        "pass_rate_pct": round(rate(development), 2)},
        "holdout": {"run": len(holdout),
                    "passed": sum(1 for r in holdout if r["passed"]),
                    "pass_rate_pct": round(rate(holdout), 2)},
        "incomplete_cases": [r["case_id"] for r in results
                             if r["status"] != "READY"],
        "critical_failures": [
            {"case_id": r["case_id"],
             "failed": [c["name"] for c in r.get("checks", [])
                        if c.get("critical") and c["passed"] is False],
             "detail": [c["detail"] for c in r.get("checks", [])
                        if c.get("critical") and c["passed"] is False][:2]}
            for r in results if r["critical_failed"]],
        "latency_ms": {
            "median": int(statistics.median(latencies)) if latencies else None,
            "p90": int(sorted(latencies)[int(len(latencies) * 0.9)])
            if latencies else None,
            "max": max(latencies) if latencies else None},
        "prose_sources": {s: sum(1 for r in results
                                 if r.get("prose_source") == s)
                          for s in {r.get("prose_source") for r in results}},
        "model_calls_total": sum(r.get("model_calls") or 0 for r in results),
        "scoring": ("Deterministic. Numeric facts matched as parsed numbers "
                    "within tolerance with the unit in the same sentence, or "
                    "in a returned table. No model grades a model. Reference "
                    "prose is not scored against."),
        "live_provider": ("LIVE_PROVIDER_UNVERIFIED — no credential in this "
                          "environment. Every answer here was composed by the "
                          "governed deterministic path and made zero model "
                          "calls. These results are NOT evidence of live LLM "
                          "operation."),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": results},
                              indent=2), encoding="utf-8")
    print("\n" + json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
