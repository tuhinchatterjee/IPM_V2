#!/usr/bin/env python
"""
Run one Early Warning turn end to end and print what actually happened.

Why a script rather than a test
-------------------------------
The tests assert the invariants. This prints the trace: the stages in the order
they fired, which model served each one, what each call cost, the single ledger
they all spent from, and whether anything analytical ran. It is the artefact a
reader checks a claim against, and it is reproducible — point it at a
deployment with a key and it makes real calls.

    AI_PROVIDER=anthropic ANTHROPIC_API_KEY=... \
    AI_ROUTER_MODEL=claude-sonnet-5 AI_COMPLEX_PLANNER_MODEL=claude-opus-5 \
    AI_CRITIC_MODEL=claude-opus-5 AI_ANALYST_MODEL=claude-opus-5 \
    python scripts/prove_early_warning_conversation.py

With no provider configured it says so at the top and every stage reports
`deterministic` — which is the supported offline configuration, not a failure.
`--stub` runs the same trace against the test double so the wiring can be
exercised without a vendor account; it labels every line as a stub so nothing
here can be mistaken for a vendor call that did not happen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.early_warning.conversation import budget as budget_mod  # noqa: E402
from backend.early_warning.conversation import pipeline as pipe  # noqa: E402
from backend.early_warning.conversation import seam as seam_mod  # noqa: E402

#: The two questions the architecture is claimed on: one Early Warning owns,
#: and one it must hand to What-If without running anything.
OWNED = "Why has Contracting deteriorated over six months, and is it " \
        "concentrated in a handful of names?"
NOT_OWNED = "What happens to ECL if oil falls 30%?"


def _install_stub() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.early_warning.stub_provider import StubProvider

    import backend.llm as llm

    stub = StubProvider(name="stub")
    llm.get_provider = lambda *, refresh=False: stub  # type: ignore[assignment]


def _rule(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def _provider_line() -> None:
    from backend.llm import get_provider

    provider = get_provider()
    status = provider.status()
    _rule("PROVIDER")
    print(f"  configured : {provider.configured}")
    print(f"  provider   : {status.provider}")
    print(f"  state      : {status.state}")
    print(f"  detail     : {status.detail}")
    _rule("STAGE ROUTING (resolved from the configured roles)")
    for row in seam_mod.routing():
        served = row["served_family"] or "provider default"
        flag = "" if row["matches_intent"] else "   <- not this family"
        print(f"  {row['stage']:<30} {row['intended_family']:<7} "
              f"role={row['role']:<16} model={row['model'] or '(inherited)':<22}"
              f" served={served}{flag}")


def _trace(turn: pipe.Turn) -> None:
    _rule(f"STAGE TRACE — {turn.question!r}")
    for event in turn.events:
        engine = event.detail.get("engine", "")
        call = event.detail.get("model_call") or {}
        served = ""
        if call.get("engine") == seam_mod.MODEL:
            served = (f"  [{call['provider']}/{call['model']} "
                      f"role={call['role']} {call['duration_ms']}ms "
                      f"in={call['input_tokens']} out={call['output_tokens']}]")
        elif call.get("fallback_reason"):
            served = f"  [deterministic: {call['fallback_reason']}]"
        print(f"  {event.at_ms:>5}ms  {event.stage:<32}"
              f"{('engine=' + engine) if engine else '':<22}{served}")
        # What was actually wrong, when something was. "Did not conform"
        # without saying which field is a diagnosis nobody can act on.
        for problem in call.get("schema_errors") or []:
            print(f"{'':>9}  {'':<32}    schema: {problem}")
        if call.get("returned_keys"):
            print(f"{'':>9}  {'':<32}    returned: "
                  f"{', '.join(call['returned_keys'])}")
        if event.detail.get("revision_declined"):
            print(f"{'':>9}  {'':<32}    revision declined: "
                  f"{event.detail['revision_declined']}")

    spent = turn.budget["spent"]
    budget = turn.budget
    _rule("ONE LEDGER")
    print(f"  mode              : {budget['mode']}")
    print(f"  model calls       : {budget['model_calls_charged']} charged of "
          f"{budget['ceilings']['model_calls']}"
          f"  ({budget['reserved_model_calls']} reserved for the closing "
          f"stages)")
    print(f"    succeeded       : {budget['model_calls_succeeded']}")
    print(f"    failed          : {budget['model_calls_failed']}")
    print(f"    sonnet / opus   : {spent['sonnet_calls']} / "
          f"{spent['opus_calls']}")
    print(f"  optional left     : "
          f"{budget['optional_model_calls_remaining']}")
    print(f"  executions        : {budget['executions_attempted']} attempted "
          f"of {budget['ceilings']['executions']}")
    print(f"    succeeded       : {budget['executions_succeeded']}")
    print(f"    failed          : {budget['executions_failed']}")
    print(f"  repairs           : {spent['repairs']}")
    print(f"  revisions         : {spent['revisions']}")
    print(f"  elapsed           : {budget['elapsed_seconds']}s of "
          f"{budget['ceilings']['wall_clock_seconds']}s soft, "
          f"{budget['ceilings']['hard_wall_clock_seconds']}s hard")
    print(f"  stages served     : {len(turn.model_calls)}")
    assert (budget["model_calls_succeeded"] + budget["model_calls_failed"]
            == budget["model_calls_charged"]), (
        "the ledger does not reconcile: charged is not succeeded plus failed")
    assert len(turn.model_calls) <= spent["model_calls"], (
        "more stages claimed a model than the ledger paid for")
    assert (budget["executions_succeeded"] + budget["executions_failed"]
            == budget["executions_attempted"] == spent["executions"]), (
        "the ledger does not reconcile: executions charged is not succeeded "
        "plus failed")
    assert len(budget["steps"]) == budget["executions_attempted"], (
        "an execution was charged that no step accounts for")

    if budget["steps"]:
        _rule("EVERY EXECUTION (charged, in order)")
        for step in budget["steps"]:
            mark = "ok  " if step["ok"] else "FAIL"
            print(f"  {step['at_seconds']:>7.2f}s  {mark}  "
                  f"{step['analysis']:<30} {step['rows']:>7} rows"
                  + ("  (corrected)" if step["corrected"] else "")
                  + (f"  {step['reason']}" if step["reason"] else ""))

    if turn.model_attempts:
        _rule("EVERY ATTEMPT (charged, in order)")
        for attempt in turn.model_attempts:
            mark = "ok  " if attempt["ok"] else "FAIL"
            print(f"  {attempt['at_seconds']:>7.2f}s  {mark}  "
                  f"{attempt['stage']:<30} {attempt['family']:<7}"
                  f"{attempt['provider']}/{attempt['model'] or '(default)'}"
                  f"  {attempt['duration_ms']}ms"
                  + (f"  {attempt['reason']}" if attempt["reason"] else ""))

    _rule("OWNERSHIP")
    print(f"  selected          : {turn.selection['selected_functionality']}")
    print(f"  engine            : {turn.selection['engine']}")
    print(f"  rationale         : {turn.selection['ownership_rationale']}")

    reached = sorted(set(turn.stages) & pipe.ANALYTICAL_STAGES)
    _rule("DOMAIN")
    print(f"  analytical stages : {reached or 'none — nothing was run'}")
    if turn.packet is not None:
        domains = {step.get("domain", "early_warning")
                   for step in (turn.packet.plan or {}).get("steps", [])}
        print(f"  domains planned   : {sorted(domains)}")
        print(f"  steps executed    : "
              f"{[s['analysis'] for s in turn.packet.steps]}")
        print(f"  figures           : {len(turn.packet.figures)} from the "
              f"result packet")

    _rule("ANSWER")
    print(f"  answered          : {turn.answer.get('answered')}")
    print(f"  direct            : {turn.answer.get('direct', '')[:300]}")
    reading = turn.answer.get("interpretation", "")
    print(f"  interpretation    : {reading[:400]}")
    for option in turn.answer.get("alternatives") or []:
        print(f"  alternative       : {option['question']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stub", action="store_true",
                        help="run against the test double instead of a vendor")
    parser.add_argument("--mode", default=budget_mod.STANDARD,
                        choices=[budget_mod.STANDARD, budget_mod.DEEP])
    parser.add_argument("--json", action="store_true",
                        help="print the whole turn as JSON as well")
    args = parser.parse_args()

    if args.stub:
        _install_stub()
        print("!! STUB PROVIDER. Every model line below is a test double, "
              "not a vendor call.")

    _provider_line()

    for question in (OWNED, NOT_OWNED):
        turn = pipe.answer(question, mode=args.mode)
        _trace(turn)
        if args.json:
            print(json.dumps(turn.to_dict(), indent=2, default=str)[:20000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
