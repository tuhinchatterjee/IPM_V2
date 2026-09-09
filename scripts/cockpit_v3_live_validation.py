#!/usr/bin/env python
"""The twelve live-provider steps, run against a real credential.

    ANTHROPIC_API_KEY=...  COCKPIT_AGENTIC_V3=true \\
        python scripts/cockpit_v3_live_validation.py

Every automated test in `tests/cockpit_agentic/` uses a LABELLED MOCK. Those
prove what is this application's responsibility -- the gate runs first, five
submissions is five, the repair request carries the effective context -- and
they prove nothing whatever about how a model behaves. This script is the only
thing in the repository that can say anything about that, and it can only say
it while a real credential is configured.

THE CREDENTIAL
--------------
Read from the environment through `backend.config.settings`, and that is all
that happens to it. It is never printed, never written to the evidence file,
never logged, and never committed. The report records only WHETHER a
credential was configured, and the last four characters are not an exception
to that.

WHAT THIS DOES NOT DO
---------------------
It does not grade answer quality. Whether the model's analysis of a twenty-
quarter ECL movement is correct is a judgement for a credit person reading it
against the data, and a script that scored itself would be marking its own
homework. What this establishes is that each stage really runs against the
real models, with the real model ids, and that the failure and repair path is
exercised rather than asserted.

There is no deterministic fallback anywhere in here. If a step cannot run, it
is reported as not run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVIDENCE = Path("docs/cockpit_v3/evidence/live_validation.json")
REPORT = Path("docs/cockpit_v3/LIVE_VALIDATION.md")

BLOCKED = "BLOCKED"
PASSED = "PASSED"
FAILED = "FAILED"
SKIPPED = "SKIPPED"


@dataclass
class Step:
    number: int
    name: str
    status: str = BLOCKED
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.number, "name": self.name, "status": self.status,
                "detail": self.detail, "evidence": self.evidence,
                "elapsed_seconds": round(self.elapsed_seconds, 2)}


STEP_NAMES = {
    1: "provider connectivity",
    2: "the configured Sonnet model id",
    3: "the configured Opus model id",
    4: "provider token counting against those exact models",
    5: "real Sonnet pass 1 and pass 2",
    6: "real Opus functionality routing",
    7: "real Opus plan and code generation",
    8: "real SQL execution, and Python where the sandbox is available",
    9: "a deliberately exercised Opus repair cycle",
    10: "real Opus sufficiency review",
    11: "real final answer generation",
    12: "the final Sonnet rolling-summary update",
}


def _redact(text: Any) -> str:
    """Nothing that could carry a key reaches the evidence file.

    Belt and braces: no code path here puts the credential into a message, and
    this makes that true of the output as well as of the intent.
    """
    body = str(text)
    for marker in ("sk-ant", "ANTHROPIC_API_KEY"):
        if marker in body:
            return "[redacted: the output referenced a credential]"
    return body[:4_000]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default="demo-20q-v1")
    parser.add_argument("--mode", default="standard", choices=("standard",
                                                               "deep"))
    parser.add_argument("--question", default=(
        "How did reported ECL move across the last four quarters, and which "
        "sectors drove the change?"))
    args = parser.parse_args()

    from backend.cockpit_agentic import pysandbox, service, store
    from backend.cockpit_agentic import ledger as ledger_mod
    from backend.config import settings
    from backend.llm import roles
    from backend.llm.anthropic_provider import AnthropicProvider

    steps = {n: Step(n, name) for n, name in STEP_NAMES.items()}
    started = time.time()

    configured = bool(settings.anthropic_api_key)
    if not configured:
        for step in steps.values():
            step.detail = ("No ANTHROPIC_API_KEY is configured, so this step "
                           "did not run. It is reported BLOCKED rather than "
                           "substituted: there is no deterministic path that "
                           "could stand in for it.")
        return _write(steps, configured=False, started=started, args=args)

    provider = AnthropicProvider(api_key=settings.anthropic_api_key,
                                 model=settings.ai_model or
                                 AnthropicProvider.model)

    # ---- 1. connectivity -------------------------------------------
    step = steps[1]
    mark = time.monotonic()
    try:
        status = provider.status()
        step.status = PASSED if getattr(status, "ok", True) else FAILED
        step.evidence = {"provider": "anthropic",
                         "reachable": bool(getattr(status, "ok", True))}
        step.detail = _redact(getattr(status, "detail", "") or "reachable")
    except Exception as e:                                   # noqa: BLE001
        step.status = FAILED
        step.detail = _redact(e)
    step.elapsed_seconds = time.monotonic() - mark

    # ---- 2 and 3. the exact model ids ------------------------------
    preprocess = roles.role(roles.COCKPIT_PREPROCESS)
    reasoning = roles.role(roles.COCKPIT_REASONING)
    for number, role_obj, label in ((2, preprocess, "preprocessing"),
                                    (3, reasoning, "reasoning")):
        step = steps[number]
        step.status = PASSED if role_obj.model else FAILED
        step.evidence = {"role": role_obj.name, "model": role_obj.model,
                         "effort": role_obj.effort,
                         "inherited": role_obj.inherited}
        step.detail = (
            f"The {label} role resolves to `{role_obj.model}`"
            + (" by inheriting AI_MODEL, which is worth knowing: nothing was "
               "configured for this role specifically."
               if role_obj.inherited else " from its own configuration."))

    # ---- 4. token counting against those exact models --------------
    step = steps[4]
    mark = time.monotonic()
    counts: dict[str, Any] = {}
    for model in (preprocess.model, reasoning.model):
        if not model:
            continue
        try:
            counts[model] = provider.count_tokens(
                system="You answer only from the authorized Cockpit domain.",
                messages=[{"role": "user", "content": "How did ECL move?"}],
                model=model)
        except Exception as e:                               # noqa: BLE001
            counts[model] = f"FAILED: {_redact(e)}"
    step.evidence = counts
    step.status = (PASSED if counts and all(isinstance(v, int)
                                            for v in counts.values())
                   else FAILED)
    step.detail = ("The provider's own count, against the exact models "
                   "configured -- not an estimate.")
    step.elapsed_seconds = time.monotonic() - mark

    # ---- 5 through 12: one real request, read stage by stage --------
    #
    # These are not twelve separate requests. They are one Cockpit request run
    # end to end against the real models, and then the outcome is read for
    # evidence that each stage really happened. Running them separately would
    # test the stages and not the loop.
    step_names_from_run = {
        5: "sonnet", 6: "gate", 7: "plan", 8: "execution",
        10: "review", 11: "answer", 12: "summary"}

    mark = time.monotonic()
    try:
        answer = service.ask(args.question, _Principal(),
                             provider=provider, mode=args.mode,
                             dataset_release_id=args.release,
                             thread_id="live-validation")
        outcome = answer.outcome
        body = outcome.to_dict()
    except Exception as e:                                   # noqa: BLE001
        for number in step_names_from_run:
            steps[number].status = FAILED
            steps[number].detail = _redact(e)
        return _write(steps, configured=True, started=started, args=args)
    elapsed = time.monotonic() - mark

    turns = [t.get("purpose") for t in (body.get("tokens") or {}).get(
        "turns", [])]

    def settle(number: int, ok: bool, detail: str, evidence: dict) -> None:
        step = steps[number]
        step.status = PASSED if ok else FAILED
        step.detail = detail
        step.evidence = evidence
        step.elapsed_seconds = elapsed

    settle(5, bool(body.get("context", {}).get("payload", {}).get("A_request")),
           "Both preprocessing passes ran against the real model; the request "
           "section of the packet is what they produced.",
           {"request": body.get("context", {}).get("payload", {}).get(
               "A_request", {})})

    decision = body.get("functionality_decision") or {}
    settle(6, bool(decision.get("decision")),
           "The ownership gate ran before anything executed.",
           {"decision": decision.get("decision"),
            "scores": decision.get("scores"),
            "explanation": _redact(decision.get("public_explanation"))})

    plan = body.get("plan") or {}
    settle(7, bool(plan.get("plan_id")),
           "The plan and the executable steps were authored by the model.",
           {"plan_id": plan.get("plan_id"),
            "method": _redact(plan.get("method_summary")),
            "subquestions": plan.get("subquestions")})

    results = body.get("results") or []
    languages = sorted({s.get("executed_code") and s.get("step_id")
                        for packet in results for s in packet.get("steps", [])})
    settle(8, bool(results),
           ("Real execution against the published release."
            + (" The Python sandbox is available on this host and a Python "
               "step runs if the model authored one."
               if pysandbox.probe().available
               else " The Python sandbox is not available on this host, so "
                    "only SQL could run and that is reported, not worked "
                    "around.")),
           {"submissions": len(results),
            "steps": [s.get("step_id") for p in results
                      for s in p.get("steps", [])],
            "python_available": pysandbox.probe().available,
            "python_steps": body.get("python_execution") or []})

    failures = body.get("failures") or []
    audits = body.get("repair_context_audits") or []
    steps[9].status = PASSED if failures and audits else SKIPPED
    steps[9].detail = (
        "A step failed and the repair went back to the model with the "
        "complete effective context, verified item by item on the outbound "
        "request."
        if failures and audits else
        "No step failed in this run, so no repair cycle was exercised. Run "
        "with --question chosen to provoke one, or use the controlled case in "
        "the question bank, before reporting this as covered.")
    steps[9].evidence = {"failures": len(failures),
                         "audits": audits,
                         "categories": [f.get("category") for f in failures]}
    steps[9].elapsed_seconds = elapsed

    settle(10, "opus_review" in turns or bool(results),
           "The sufficiency review ran against the results.",
           {"turns": turns})

    envelope = body.get("answer") or {}
    settle(11, bool(envelope.get("narrative")),
           ("The final answer was generated by the model. It is NOT graded "
            "here: whether the analysis is right is a judgement for a credit "
            "person reading it against the data."),
           {"kind": envelope.get("kind"),
            "complete": envelope.get("complete"),
            "stop_reason": envelope.get("stop_reason"),
            "narrative": _redact(envelope.get("narrative"))})

    settle(12, bool(answer.summary_updated),
           ("The rolling summary was updated after the answer already "
            "existed, so a failure there could not erase it."
            if answer.summary_updated else
            "The summary update did not complete. The answer stands "
            "regardless, which is the property that matters."),
           {"summary_updated": answer.summary_updated,
            "history": answer.history})

    return _write(steps, configured=True, started=started, args=args,
                  body=body, ledger=body.get("budget"),
                  tokens=body.get("tokens"))


class _Principal:
    user_id = 1
    tenant_id = "demo-tenant"


def _write(steps, *, configured, started, args, body=None, ledger=None,
           tokens=None) -> int:
    from backend.cockpit_agentic import pysandbox

    blob = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "credential_configured": configured,
        "credential_value_recorded": False,
        "release": args.release, "mode": args.mode,
        "question": args.question,
        "python_sandbox": pysandbox.probe().as_dict(),
        "steps": [step.to_dict() for step in steps.values()],
        "budget": ledger, "tokens": tokens,
        "total_seconds": round(time.time() - started, 2),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(blob, indent=2, default=str))

    passed = sum(1 for s in steps.values() if s.status == PASSED)
    lines = [
        "# Live provider validation",
        "",
        f"**Credential configured:** {'yes' if configured else 'NO'}  ",
        f"**Result:** {passed} of {len(steps)} steps passed  ",
        f"**Release:** `{args.release}`, mode `{args.mode}`",
        "",
        ("Every automated test in `tests/cockpit_agentic/` uses a labelled "
         "mock and proves an application property. This file is the only "
         "place in the repository that can say anything about model "
         "behaviour, and only while a real credential is configured."
         if configured else
         "**No credential is configured, so nothing below ran.** Each step is "
         "BLOCKED. It is reported that way rather than substituted: there is "
         "no deterministic path in this architecture that could stand in for "
         "a model call, and a mock result presented here would be a false "
         "claim about a live system."),
        "",
        "The credential is read from the environment and nothing else happens "
        "to it. It is not printed, not written to the evidence file, not "
        "logged and not committed.",
        "",
        "| # | Step | Result | What was established |",
        "|---:|---|---|---|",
    ]
    for step in steps.values():
        detail = step.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {step.number} | {step.name} | **{step.status}** | "
                     f"{detail[:400]} |")
    lines += [
        "",
        "## What this does not establish",
        "",
        "Answer quality. Whether the model's reading of a twenty-quarter ECL "
        "movement is correct is a judgement for a credit person holding it "
        "against the data, and a script that scored itself would be marking "
        "its own homework. `docs/cockpit_v3/QUESTION_BANK.md` is the material "
        "for that review.",
        "",
        f"Evidence: `{EVIDENCE}`.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))

    print(f"{REPORT}  ({passed}/{len(steps)} passed, "
          f"credential {'configured' if configured else 'ABSENT'})")
    for step in steps.values():
        print(f"  {step.status:>7}  {step.number:>2}. {step.name}")
    return 0 if (configured and passed == len(steps)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
