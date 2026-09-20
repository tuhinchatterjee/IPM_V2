#!/usr/bin/env python3
"""The twelve-question live UAT, driven end to end.

    .venv/bin/python scripts/retail_cockpit/run_uat.py

Runs `docs/retail_cockpit/LIVE_UAT_PLAN.md` against a LIVE engine, through the
retail proxy -- the same path a question typed into the UI takes, so the
cumulative spend cap applies to this exactly as it applies to a reader.

**This spends real money.** Roughly $9 against a $15 cap at the candidate
card's rates. It refuses to start unless `check_live.py` says the deployment
is live-ready, and it stops at the cap.

How an answer is judged
-----------------------
Not by reading the prose. Every figure the analyst publishes is a
`numeric_claim` the engine has already bound to an executed cell, so the check
is: **does every number the answer states appear among the numbers the oracle
independently computed, within the oracle's own tolerance?**

That is a real check and it is not the same as "the answer is correct". It
catches a fabricated figure, a wrong denomination, a ratio of averages, an
un-de-duplicated customer total -- because all four produce a number the
oracle does not have. It does not catch an answer that states only true
numbers and draws a wrong conclusion from them. The report says which of the
two it is measuring, and never claims the stronger one.

What stops the run
------------------
* **Question 2 failing.** The plan: "if question 2 fails, the work goes back
  to the steering seam before anything else is spent."
* **A containment failure** -- 9 or 10 answering instead of refusing.
* **The cumulative cap.**

A numerical disagreement on 1 or 3-8 is recorded and the run continues, so one
pass buys the whole picture. It is still a failure in the report.

Everything is written after every question, and `--from N` resumes, so a stop
never costs the questions already paid for. The credential is never read into
a value here, never printed and never written to the evidence file.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE = ROOT / "docs" / "retail_cockpit" / "evidence" / "live_uat.json"

#: The twelve, in order, from LIVE_UAT_PLAN.md. `oracle` names a case in
#: `backend.retail_cockpit_adapter.oracle.CASES`; `check` names the special
#: judgement where a number is not what settles it.
QUESTIONS: tuple[dict[str, Any], ...] = (
    {"n": "1", "ask": "What is total exposure at default by product in the "
                      "latest month?",
     "oracle": "Q01", "settles": "the simplest possible agreement"},
    {"n": "2", "ask": "Which facilities carry the largest balances this "
                      "month?",
     "check": "denomination", "stop_on_fail": True,
     "settles": "THE MONEY RULE. Facility grain: does it choose the riyal "
                "column unprompted, or publish SAR 0 million?"},
    {"n": "3", "ask": "Show recognised ECL and coverage by product and "
                      "IFRS 9 stage for the latest month.",
     "oracle": "Q03", "settles": "ratio of sums, not an averaged ratio"},
    {"n": "4", "ask": "Where did the 1-29 day past due population move this "
                      "month?",
     "oracle": "Q05", "settles": "a movement, with the denominator stated"},
    {"n": "5", "ask": "Decompose the ECL movement since last month.",
     "oracle": "Q21", "settles": "against the panel's own attribution"},
    {"n": "6", "ask": "Which customers have the highest debt burden?",
     "oracle": "Q22", "settles": "CUSTOMER grain: is it de-duplicated?"},
    {"n": "7", "ask": "Show the twelve-month ECL trend.",
     "oracle": "Q26", "settles": "a series, not two endpoints"},
    {"n": "8", "ask": "Which behavioural score band carries the most "
                      "exposure?",
     "oracle": "Q17", "settles": "the governed band order, not alphabetical"},
    {"n": "9", "ask": "What is the Early Warning score for these customers?",
     "check": "refusal", "owner": "EWS", "stop_on_fail": True,
     "settles": "A REFUSAL. Another module's domain: it must hand off."},
    {"n": "10", "ask": "Which corporate sectors deteriorated this quarter?",
     "check": "refusal", "stop_on_fail": True,
     "settles": "A REFUSAL. Another book: it must say so."},
    {"n": "11a", "ask": "What is total ECL by product in the latest month?",
     "oracle": "Q03", "settles": "sets up the follow-up"},
    {"n": "11b", "ask": "And which product drove the increase?",
     "follow_up": True, "check": "context",
     "settles": "context retention: stays in the thread, own evidence"},
)

#: Dispositions that mean the Cockpit declined rather than answered.
DECLINED = {"referral", "unsupported"}
ANSWERED = {"answer", "partial_answer"}


# --------------------------------------------------------------- the client

class Cockpit:
    """The proxy, driven the way `check_ready.py` drives it."""

    def __init__(self, api: str, timeout: float) -> None:
        import httpx

        self.base = f"{api.rstrip('/')}/api/v1/cockpit-v4"
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

    def thread(self) -> str:
        reply = self.client.post(f"{self.base}/threads",
                                 json={"domain": "retail"})
        reply.raise_for_status()
        return str(reply.json()["thread_id"])

    def ask(self, thread_id: str, question: str, mode: str) -> Any:
        return self.client.post(
            f"{self.base}/runs",
            # Unique per question. A fixed key answers IDEMPOTENCY_CONFLICT
            # on a resumed run, which reads as a refusal when it is not one.
            headers={"Idempotency-Key": f"uat-{uuid.uuid4().hex}"},
            json={"question": question, "thread_id": thread_id, "mode": mode})

    def follow(self, run_id: str, deadline: float) -> list[str]:
        """Drain the stream until the run settles. Returns the event names."""
        seen: list[str] = []
        with self.client.stream(
                "GET", f"{self.base}/runs/{run_id}/events",
                params={"cursor": 0},
                headers={"Accept": "text/event-stream"},
                timeout=None) as stream:
            for line in stream.iter_lines():
                if time.monotonic() > deadline:
                    seen.append("(deadline)")
                    break
                if not line.startswith("event: "):
                    continue
                name = line[7:].strip()
                seen.append(name)
                if name == "run.settled":
                    break
        return seen

    def result(self, run_id: str) -> dict[str, Any]:
        reply = self.client.get(f"{self.base}/runs/{run_id}")
        reply.raise_for_status()
        return dict(reply.json())


# ------------------------------------------------------------- the judgement

def _numbers(value: Any, into: list[float]) -> None:
    """Every number reachable in an oracle row, flattened."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        into.append(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, into)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _numbers(item, into)


def expected_numbers(case_id: str, snapshot: Any) -> tuple[list[float], Any]:
    from backend.retail_cockpit_adapter import oracle as oracle_mod

    expected = oracle_mod.ORACLES[case_id](snapshot)
    found: list[float] = []
    for row in expected.rows:
        _numbers(row, found)
    return found, expected


def claim_values(final: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for claim in final.get("numeric_claims") or []:
        raw = claim.get("decimal_value")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        out.append({"claim_id": claim.get("claim_id"), "value": value,
                    "unit": claim.get("unit", "")})
    return out


def agrees(value: float, expected: list[float], tolerance: float) -> bool:
    for candidate in expected:
        if abs(value - candidate) <= max(tolerance,
                                         abs(candidate) * tolerance):
            return True
        # A riyal figure against a millions oracle, and the reverse. Both are
        # the same quantity and this book publishes both denominations.
        for scaled in (candidate * 1e6, candidate / 1e6):
            if abs(value - scaled) <= max(tolerance, abs(scaled) * tolerance):
                return True
    return False


def judge(question: dict[str, Any], final: dict[str, Any],
          snapshot: Any) -> dict[str, Any]:
    """What this question was asked to settle, and whether it did."""
    disposition = str(final.get("disposition") or "")
    claims = claim_values(final)
    narrative = str(final.get("narrative") or "")
    kind = question.get("check", "oracle")

    if kind == "refusal":
        owner = str(final.get("referral_owner") or "")
        declined = disposition in DECLINED
        named = bool(owner and owner != "NONE") or bool(
            final.get("referral_reason"))
        ok = declined and named
        return {"kind": "refusal", "passed": ok,
                "disposition": disposition, "referral_owner": owner,
                "reason": str(final.get("referral_reason") or "")[:300],
                "containment_failure": disposition in ANSWERED,
                "why": ("declined and named an owner" if ok else
                        "ANSWERED a question it should have refused"
                        if disposition in ANSWERED else
                        "declined without naming who owns it")}

    if kind == "denomination":
        # The whole point of question 2. A facility balance is ~SAR 100k, so
        # a millions answer rounds it to zero -- which is the failure this is
        # here to catch, in the analyst's own published figures.
        zero_million = any(
            c["value"] == 0 and "million" in c["unit"].lower() for c in claims)
        said_zero_million = "sar 0 million" in narrative.lower()
        riyal_scale = [c for c in claims if abs(c["value"]) >= 1_000]
        ok = bool(claims) and not zero_million and not said_zero_million \
            and bool(riyal_scale)
        return {"kind": "denomination", "passed": ok,
                "claims": claims[:12],
                "why": ("published riyal-scale figures at facility grain"
                        if ok else
                        "published SAR 0 million at facility grain" if
                        (zero_million or said_zero_million) else
                        "published no facility-scale figure at all")}

    if kind == "context":
        ok = disposition in ANSWERED and bool(final.get("evidence_bound"))
        return {"kind": "context", "passed": ok,
                "disposition": disposition,
                "evidence_bound": bool(final.get("evidence_bound")),
                "claims": claims[:12],
                "why": ("stayed in the thread and bound its own evidence"
                        if ok else "did not answer with bound evidence")}

    case_id = question["oracle"]
    expected, spec = expected_numbers(case_id, snapshot)
    unmatched = [c for c in claims
                 if not agrees(c["value"], expected, spec.tolerance)]
    ok = disposition in ANSWERED and bool(claims) and not unmatched
    return {"kind": "oracle", "case": case_id, "passed": ok,
            "disposition": disposition,
            "tolerance": spec.tolerance, "period": spec.period,
            "grain": spec.grain, "unit": spec.unit,
            "claims_total": len(claims), "claims_unmatched": len(unmatched),
            "unmatched": unmatched[:8],
            "why": ("every published figure matches the oracle" if ok else
                    "no figure was published" if not claims else
                    f"{len(unmatched)} published figure(s) match no value the "
                    f"oracle computes")}


# ------------------------------------------------------------------- the run

def preflight(python: str) -> tuple[bool, str]:
    done = subprocess.run(
        [python, str(ROOT / "scripts/retail_cockpit/check_live.py")],
        capture_output=True, text=True, cwd=str(ROOT))
    return done.returncode == 0, (done.stdout or "") + (done.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8329")
    parser.add_argument("--mode", default="standard")
    parser.add_argument("--from", dest="start", default="",
                        help="resume at this question number, e.g. 7")
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="seconds allowed for one question")
    parser.add_argument("--out", type=Path, default=EVIDENCE)
    parser.add_argument("--analytics-dir", type=Path, default=None)
    parser.add_argument("--metadata-dir", type=Path, default=None)
    parser.add_argument(
        "--i-accept-the-cost", action="store_true",
        help="required for a live run. This spends real money.")
    parser.add_argument(
        "--rehearse", action="store_true",
        help="drive all twelve against an OFFLINE engine. Proves the "
             "plumbing -- threads, submission, the stream, the result, the "
             "oracles, the cap, the evidence file -- and answers nothing. "
             "Costs nothing and refuses to run against a live engine.")
    args = parser.parse_args()

    rehearsal = bool(args.rehearse)
    if rehearsal:
        # The guard that keeps this honest: rehearsal is only meaningful
        # against an engine that CANNOT call out, and only safe there.
        if not os.environ.get("RETAIL_COCKPIT_OFFLINE", "").strip():
            print("--rehearse needs RETAIL_COCKPIT_OFFLINE set, so it cannot "
                  "be pointed at an engine that would spend money.")
            return 2
        print("  REHEARSAL. The engine is offline, so every question will "
              "settle as a provider failure.\n  This proves the runner, not "
              "the Cockpit's answers, and costs nothing.\n")
    else:
        if not args.i_accept_the_cost:
            print("This runs twelve real analyses and spends real money.\n"
                  "Re-run with --i-accept-the-cost once you mean it, or "
                  "--rehearse to prove the runner for free.")
            return 2
        ok, detail = preflight(sys.executable)
        print(detail.rstrip())
        if not ok:
            print("\n  REFUSING TO START: check_live.py is not satisfied.")
            return 1

    from backend.retail_cockpit_adapter.source import open_snapshot
    from backend.retail_cockpit_host import spend

    analytics = args.analytics_dir or Path(
        os.environ.get("DATA_ANALYTICS_DIR", "data/retail/analytics"))
    metadata = args.metadata_dir or Path(
        os.environ.get("METADATA_DIR", "metadata/retail"))
    snapshot = open_snapshot(analytics, metadata)

    cockpit = Cockpit(args.api, timeout=args.timeout)
    started_spend = spend.spent()

    report: dict[str, Any] = {
        "evidence_class": ("offline rehearsal -- the runner, not the answers"
                           if rehearsal else "live provider run"),
        "paid_provider_calls": not rehearsal,
        "what_is_measured": (
            "Whether every figure the analyst publishes as a numeric_claim "
            "appears among the values an independent oracle computes from "
            "the source book, at the oracle's own tolerance; whether a "
            "facility-grain money question answers in riyals; whether two "
            "out-of-scope questions are declined and say who owns them; and "
            "whether a follow-up stays in its thread with its own evidence."),
        "what_is_not_measured": (
            "Whether an answer that states only true numbers draws the right "
            "conclusion from them. A human reads the narratives for that."),
        "model": os.environ.get("AI_COCKPIT_REASONING_MODEL", ""),
        "mode": args.mode,
        "spend_before_usd": round(started_spend, 6),
        "questions": [],
    }
    if args.out.exists():
        try:
            previous = json.loads(args.out.read_text(encoding="utf-8"))
            if args.start:
                report["questions"] = previous.get("questions", [])
        except (OSError, json.JSONDecodeError):
            pass

    def save() -> None:
        report["spend_after_usd"] = round(spend.spent(), 6)
        report["spend_this_run_usd"] = round(
            report["spend_after_usd"] - started_spend, 6)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, default=str),
                            encoding="utf-8")

    started = not args.start
    thread_id = ""
    stopped = ""

    for question in QUESTIONS:
        if not started:
            if question["n"] != args.start:
                continue
            started = True

        verdict = spend.allowed()
        if not verdict.allowed:
            stopped = (f"the cumulative cap of ${verdict.cap_usd:,.2f} was "
                       f"reached (${verdict.spent_usd:,.2f} recorded)")
            break

        if not question.get("follow_up") or not thread_id:
            thread_id = cockpit.thread()

        print(f"\n[{question['n']}] {question['ask']}")
        print(f"      settles: {question['settles']}")
        before = spend.spent()
        accepted = cockpit.ask(thread_id, question["ask"], args.mode)
        if accepted.status_code != 202:
            entry = {"n": question["n"], "ask": question["ask"],
                     "accepted": accepted.status_code,
                     "error": accepted.text[:400], "passed": False}
            report["questions"].append(entry)
            save()
            stopped = (f"question {question['n']} was not accepted "
                       f"({accepted.status_code})")
            break

        run_id = str(accepted.json()["run_id"])
        frames = cockpit.follow(run_id, deadline=time.monotonic()
                                + args.timeout)
        record = cockpit.result(run_id)
        final = dict(record.get("final_response") or {})
        state = str(record.get("state") or "")

        entry: dict[str, Any] = {
            "n": question["n"], "ask": question["ask"],
            "settles": question["settles"],
            "thread_id": thread_id, "run_id": run_id, "state": state,
            "error_code": record.get("error_code") or "",
            "disposition": final.get("disposition", ""),
            "narrative": str(final.get("narrative") or "")[:1200],
            "frames": frames,
            "budget": record.get("budget") or {},
            "cost_usd": round(spend.spent() - before, 6),
        }
        if state != "COMPLETED" or not final:
            entry["passed"] = False
            entry["judgement"] = {
                "kind": "run", "passed": False,
                "why": f"the run settled {state or 'unknown'} without an "
                       f"answer: {record.get('error_code') or 'no code'}"}
        else:
            entry["judgement"] = judge(question, final, snapshot)
            entry["passed"] = bool(entry["judgement"]["passed"])

        report["questions"].append(entry)
        save()

        mark = "ok  " if entry["passed"] else "FAIL"
        print(f"      {mark} {entry['judgement']['why']}  "
              f"(${entry['cost_usd']:.4f})")

        if not entry["passed"] and question.get("stop_on_fail") \
                and not rehearsal:
            if entry["judgement"].get("containment_failure"):
                stopped = (f"CONTAINMENT FAILURE on question "
                           f"{question['n']}: it answered a question it must "
                           f"refuse")
            else:
                stopped = (f"question {question['n']} failed, and the plan "
                           f"stops the run there rather than spending on the "
                           f"rest")
            break

    report["stopped_because"] = stopped
    passed = [q for q in report["questions"] if q.get("passed")]
    if rehearsal:
        # A rehearsal cannot pass or fail the UAT: nothing was answered. What
        # it reports is whether the RUNNER drove all twelve.
        drove = len(report["questions"])
        report["verdict"] = (
            f"REHEARSAL: the runner drove {drove} of {len(QUESTIONS)} "
            f"questions. No answer was produced and none was possible.")
    else:
        report["verdict"] = (
            "UAT PASSED" if not stopped and len(passed) == len(QUESTIONS)
            else "UAT FAILED")
    save()

    print(f"\n  {len(passed)} of {len(report['questions'])} questions passed "
          f"({len(QUESTIONS)} in the plan)")
    print(f"  spent ${report['spend_this_run_usd']:.4f} this run, "
          f"${report['spend_after_usd']:.4f} recorded in total")
    if stopped:
        print(f"  STOPPED: {stopped}")
    print(f"  {report['verdict']}")
    print(f"  evidence: {args.out}")
    for entry in report["questions"]:
        if not entry.get("passed"):
            print(f"    - [{entry['n']}] "
                  f"{entry.get('judgement', {}).get('why', 'failed')}")
    if rehearsal:
        return 0 if len(report["questions"]) == len(QUESTIONS) else 1
    return 0 if report["verdict"] == "UAT PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
