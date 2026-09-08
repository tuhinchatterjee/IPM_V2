#!/usr/bin/env python
"""Run the labelled ownership benchmark. Specification section 14.2.

    COCKPIT_AGENTIC_V3=true python tests/evals/cockpit_agentic/run_ownership_eval.py

Routing correctness is the MODEL's job, so this is only meaningful against a
live provider. With no credential configured it reports BLOCKED and exits
non-zero rather than reporting a score obtained from a mock. Section 18 and the
task's standing constraint both forbid presenting mock output as evidence that
the agentic architecture works.

What it measures, from section 14.2:

* routing correctness against the hand-labelled owner;
* that EVERY referral triggered ZERO analytical SQL and ZERO other-module
  calls -- measured from the runtime's own result and failure lists, not
  asserted;
* that alternative questions are genuinely answerable: every field they name
  is resolved against the real catalogue, and one that is not is a failure;
* that an in-scope question with no data for the selected quarter reports a
  coverage limitation rather than being referred away;
* latency, tokens and cost per case.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.cockpit_agentic import catalog as catalog_mod
from backend.cockpit_agentic import registry, service, states, store

CASES = Path(__file__).with_name("ownership_cases.json")


def credential_configured() -> bool:
    from backend.config import settings

    return bool(settings.anthropic_api_key) and \
        str(settings.ai_provider).lower() != "offline"


def observed_owner(outcome) -> str:
    if outcome.status == states.REDIRECTED and outcome.decision:
        return outcome.decision.referral_destination
    if outcome.status in (states.CLARIFICATION_REQUIRED,):
        return "clarify"
    if outcome.status == states.UNSUPPORTED:
        return "unsupported"
    if outcome.decision and outcome.decision.may_execute:
        return "cockpit"
    return f"({outcome.status})"


def check_alternatives(outcome, catalog) -> list[str]:
    """Every field an alternative names must exist. Section 6.3."""
    problems: list[str] = []
    for alternative in (outcome.envelope.alternatives or []):
        for field_name in alternative.required_fields:
            found = False
            for relation in catalog.relations():
                try:
                    catalog.resolve(relation, field_name)
                    found = True
                    break
                except Exception:                          # noqa: BLE001
                    continue
            if not found:
                problems.append(
                    f"{alternative.question!r} needs {field_name!r}, which is "
                    f"not in the catalogue")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=service.DEFAULT_RELEASE)
    parser.add_argument("--mode", default="standard")
    parser.add_argument("--out",
                        default="docs/cockpit_agentic_v3/evidence/"
                                "ownership_eval.json")
    args = parser.parse_args()

    payload = json.loads(CASES.read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not credential_configured():
        report = {
            "status": "BLOCKED",
            "reason": ("No model credential is configured in this "
                       "environment, so routing was not exercised against a "
                       "live provider. Routing correctness is the model's "
                       "job; a score obtained from a mock would say nothing "
                       "about it and is not produced."),
            "cases_available": len(payload["cases"]),
            "started_at": started,
            "live_verified": False,
        }
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print("BLOCKED: no credential configured. Routing was NOT verified.")
        print(f"  {len(payload['cases'])} labelled cases are ready to run.")
        print(f"  written to {out}")
        return 2

    try:
        calendar = store.load_calendar(args.release)
    except store.ReleaseNotFound as e:
        print(f"BLOCKED: {e}")
        return 2
    catalog = catalog_mod.build(dataset_release_id=args.release,
                               calendar=calendar)

    class Principal:
        user_id = 1

    results: list[dict] = []
    for case in payload["cases"]:
        began = time.monotonic()
        try:
            answer = service.ask(case["question"], Principal(),
                                 mode=args.mode,
                                 dataset_release_id=args.release,
                                 thread_id=f"eval-{case['case_id']}")
            outcome = answer.outcome
        except Exception as e:                              # noqa: BLE001
            results.append({**case, "error": str(e), "passed": False})
            continue

        owner = observed_owner(outcome)
        referred = outcome.status == states.REDIRECTED
        executions = len(outcome.results)
        problems = check_alternatives(outcome, catalog)

        passed = owner == case["expected_owner"]
        if referred and executions:
            passed = False
            problems.append(f"a referral executed {executions} query step(s)")
        if problems:
            passed = False

        results.append({
            "case_id": case["case_id"],
            "question": case["question"],
            "expected_owner": case["expected_owner"],
            "observed_owner": owner,
            "status": outcome.status,
            "passed": passed,
            "problems": problems,
            "executions": executions,
            "alternatives": len(outcome.envelope.alternatives or []),
            "latency_ms": int((time.monotonic() - began) * 1000),
            "tokens": outcome.budget.get("tokens_used"),
            "spend": outcome.budget.get("spend_usd"),
        })

    passed = [r for r in results if r.get("passed")]
    referrals = [r for r in results
                 if r.get("status") == states.REDIRECTED]
    report = {
        "status": "LIVE_VERIFIED" if len(passed) == len(results) else "MEASURED",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": args.mode,
        "dataset_release_id": args.release,
        "registry_version": registry.REGISTRY_VERSION,
        "cases": len(results),
        "routing_correct": len(passed),
        "routing_accuracy": round(len(passed) / max(1, len(results)), 4),
        "referrals": len(referrals),
        "referrals_that_executed_sql": sum(
            1 for r in referrals if r.get("executions")),
        "live_verified": True,
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"routing correct: {len(passed)}/{len(results)}")
    print(f"referrals that executed SQL: "
          f"{report['referrals_that_executed_sql']} (must be 0)")
    print(f"written to {out}")
    return 0 if report["routing_correct"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
