#!/usr/bin/env python
"""
Certify Early Warning against a REAL Anthropic provider, on your own machine.

Why this script exists
----------------------
Everything else in this repository can be proved without a vendor account. The
one thing that cannot is whether the model-backed stages behave when a real
model serves them: whether each stage is actually reached, whether any of them
runs out of output allowance halfway through a document, whether the planner's
reply conforms, and whether the final prose survives the grounding check
instead of being discarded and replaced.

So this runs the turns that matter, records exactly what happened at each
stage, and exits non-zero if any of it is not what the architecture claims.

Your key never reaches anyone
-----------------------------
This script never reads, prints, logs or writes `ANTHROPIC_API_KEY`. It asks
the provider whether it is CONFIGURED and nothing else. Every string that
lands in the report is passed through `_safe()`, which refuses to emit
anything that looks like a credential. Run it yourself; nothing is uploaded.

How to run it (macOS)
---------------------
Paste the key at a prompt rather than typing it into the command line, so it
never enters your shell history:

    cd /path/to/IPM_V2
    read -rs -p "Anthropic API key: " ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY && echo
    export AI_PROVIDER=anthropic
    export AI_ROUTER_MODEL=claude-sonnet-5
    export AI_COMPLEX_PLANNER_MODEL=claude-opus-5
    export AI_CRITIC_MODEL=claude-opus-5
    export AI_ANALYST_MODEL=claude-opus-5
    .venv/bin/python scripts/certify_early_warning_live.py

Then, when it finishes:

    unset ANTHROPIC_API_KEY

The report is written to `docs/evidence/live/` and the exit code is the
verdict: 0 certified, 1 something failed, 2 no provider was configured.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.early_warning.conversation import budget as budget_mod  # noqa: E402
from backend.early_warning.conversation import pipeline as pipe  # noqa: E402
from backend.early_warning.conversation import seam as seam_mod  # noqa: E402

DEFAULT_REPORT = Path("docs/evidence/live/early_warning_live_certification.json")

#: Anything shaped like a credential never leaves this process. Belt and
#: braces: the script does not read the key in the first place, and this
#: catches a value that arrived by some other route — an error message from
#: the SDK that echoed a header, say.
_SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9_\-\.]{8,}")


def _safe(value):
    """Scrub anything credential-shaped out of a value before it is written."""
    if isinstance(value, str):
        return _SECRET.sub("[redacted]", value)
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value


# --------------------------------------------------------------- the cases


#: The eight categories the certification covers. Each names what a PASS
#: requires, because "it answered" is not a result — the whole point of this
#: exercise is that an answer can be fluent, grounded, arithmetically sound
#: and about a different question.
CASES: tuple[dict, ...] = (
    {
        "id": "LIVE-1", "category": "easy retrieval",
        "question": "What is the current Early Warning distribution by risk band?",
        "owner": "early_warning", "analytical": True,
    },
    {
        "id": "LIVE-2", "category": "diagnostic",
        "question": ("Why has the Contracting sector deteriorated over the "
                     "last six months?"),
        "owner": "early_warning", "analytical": True,
    },
    {
        "id": "LIVE-3", "category": "multi-part analytical",
        "question": ("Why has Contracting deteriorated over six months, is it "
                     "concentrated in a handful of names, and which layer is "
                     "driving it?"),
        "owner": "early_warning", "analytical": True,
    },
    {
        "id": "LIVE-4", "category": "follow-up",
        "question": "Which two of those worsened fastest?",
        "owner": "early_warning", "analytical": True,
        # Runs as the second turn of LIVE-3's thread, so the pronoun has
        # something to resolve against. A follow-up asked cold is a different
        # test and would pass for the wrong reason.
        "follows": "LIVE-3",
    },
    {
        "id": "LIVE-5", "category": "incorrect premise",
        "question": ("Given every Contracting obligor improved last month, "
                     "which one improved most?"),
        "owner": "early_warning", "analytical": True,
        # A turn that accepts the premise and names a winner has failed, even
        # though it will look like a confident answer.
        "must_not_simply_agree": True,
    },
    {
        "id": "LIVE-6", "category": "cross-product What-If route",
        "question": "What happens to ECL if oil falls 30%?",
        "owner": "what_if", "analytical": False,
        # Early Warning must hand this over without running an analysis.
        "expect_no_executions": True,
    },
    {
        "id": "LIVE-7", "category": "noisy spelling",
        "question": "wich contrcting names deterioted mst lst 6 mnths",
        "owner": "early_warning", "analytical": True,
    },
    {
        "id": "LIVE-8", "category": "mixed language",
        "question": "construction ka risk last 6 months mein kyun badha?",
        "owner": "early_warning", "analytical": True,
    },
)

#: The stages a normal analytical turn must have served with a model.
#: `opus_repair` is absent deliberately: it runs only when the validator
#: refuses a plan, and a turn that needed no repair is a better turn.
REQUIRED_MODEL_STAGES: tuple[str, ...] = (
    seam_mod.PASS_1, seam_mod.PASS_2, seam_mod.FUNCTIONALITY, seam_mod.PLAN,
    seam_mod.SUFFICIENCY, seam_mod.INTERPRETATION, seam_mod.SUMMARY,
)

#: §18. The stage that truncated at 700 tokens on the last live run. It is
#: named separately because it is the specific regression this certification
#: exists to close, and a summary that silently falls back to the
#: deterministic writer would otherwise look like a pass.
SUMMARY_STAGE = seam_mod.SUMMARY


# ------------------------------------------------------------- the checks


def _stage_rows(turn) -> list[dict]:
    """One row per model-backed stage: who served it, and how it went."""
    rows: list[dict] = []
    for event in turn.events:
        call = event.detail.get("model_call") or {}
        if not call:
            continue
        stage = seam_mod.STAGES.get(call.get("stage") or event.stage)
        allowance = stage.max_tokens if stage else None
        out_tokens = int(call.get("output_tokens") or 0)
        rows.append({
            "stage": call.get("stage") or event.stage,
            "engine": call.get("engine", ""),
            "intended_family": call.get("family", ""),
            "served_family": call.get("served_family", ""),
            "model": call.get("model", ""),
            "role": call.get("role", ""),
            "duration_ms": call.get("duration_ms"),
            "input_tokens": call.get("input_tokens"),
            "output_tokens": out_tokens,
            "output_allowance": allowance,
            # A reply that spent its entire allowance is a reply that was cut
            # off. The allowance is not a budget for the document; it is the
            # ceiling, and touching it means the document did not finish.
            "truncated": bool(allowance and out_tokens >= allowance),
            "fallback_reason": call.get("fallback_reason", ""),
            "schema_errors": list(call.get("schema_errors") or []),
        })
    return rows


def _final_detail(turn) -> dict:
    for event in turn.events:
        if event.stage == pipe.FINAL_ANSWER:
            return dict(event.detail or {})
    return {}


def _ungrounded(turn) -> list[str]:
    return list(_final_detail(turn).get("ungrounded_figures") or [])


def _reading_diagnostics(turn) -> dict:
    """What the reading declared, and what it wrote if it was thrown away.

    Diagnostics only — nothing here decides a PASS. It exists because the last
    live run reported five bare numbers and nothing else, and working out
    where `11.31` and `-5` came from meant rebuilding the packets by hand. A
    report that names the figure, the sentence it sat in, and the arithmetic
    the model claimed for it can be read directly.
    """
    detail = _final_detail(turn)
    claims = list(detail.get("derived_claims") or [])
    out = {
        "engine": detail.get("engine", ""),
        "ungrounded_figures": list(detail.get("ungrounded_figures") or []),
        "derived_claims": claims,
        "derived_claims_refused": [c for c in claims if not c.get("accepted")],
    }
    call = detail.get("model_call") or {}
    if detail.get("ungrounded_figures"):
        # The prose the runtime discarded. Scrubbed like everything else, and
        # trimmed: this is for diagnosis, not for reading the answer twice.
        out["discarded_prose"] = _safe(
            str(call.get("discarded_prose") or "")[:600])
        out["fallback_reason"] = _safe(str(call.get("fallback_reason") or ""))
    return out


def _check(case: dict, turn) -> tuple[list[dict], list[dict]]:
    """Every assertion this case makes, and whether each held."""
    stages = _stage_rows(turn)
    by_stage = {row["stage"]: row for row in stages}
    budget = turn.budget
    answer = turn.answer or {}
    owner = (turn.selection or {}).get("selected_functionality", "")
    checks: list[dict] = []

    def check(what: str, ok: bool, detail="") -> None:
        checks.append({"what": what, "pass": bool(ok),
                       "detail": _safe(detail)})

    check("ownership resolved as expected", owner == case["owner"],
          f"selected {owner!r}, expected {case['owner']!r}")
    check("an answer came back", bool(answer.get("direct")),
          (answer.get("direct") or "")[:200])

    if case.get("expect_no_executions"):
        check("nothing analytical ran for another product's question",
              budget["executions_attempted"] == 0,
              f"{budget['executions_attempted']} executions attempted")
    if case.get("analytical"):
        check("at least one governed analysis ran",
              budget["executions_succeeded"] > 0,
              f"{budget['executions_succeeded']} succeeded of "
              f"{budget['executions_attempted']} attempted")
        for stage in REQUIRED_MODEL_STAGES:
            row = by_stage.get(stage)
            check(f"{stage} served by a model",
                  bool(row and row["engine"] == seam_mod.MODEL),
                  (row or {}).get("fallback_reason") or "stage never reached")

    # §18, stated as its own assertion so the report says it in as many words.
    summary = by_stage.get(SUMMARY_STAGE)
    if case.get("analytical"):
        check(f"{SUMMARY_STAGE} engine=model",
              bool(summary and summary["engine"] == seam_mod.MODEL),
              (summary or {}).get("fallback_reason") or "stage never reached")
        check(f"{SUMMARY_STAGE} not truncated",
              bool(summary and not summary["truncated"]),
              f"{(summary or {}).get('output_tokens')} of "
              f"{(summary or {}).get('output_allowance')} tokens")

    truncated = [row["stage"] for row in stages if row["truncated"]]
    check("no stage spent its whole output allowance", not truncated, truncated)

    fell_back = [row["stage"] for row in stages if row["fallback_reason"]]
    check("no stage fell back to the deterministic writer", not fell_back,
          [f"{row['stage']}: {row['fallback_reason']}"
           for row in stages if row["fallback_reason"]])

    malformed = [f"{row['stage']}: {row['schema_errors']}"
                 for row in stages if row["schema_errors"]]
    check("every model reply conformed to its schema", not malformed, malformed)

    # "unknown" means the model id is not one whose family can be read off
    # the id — a stub, or a deployment pointing at an alias. That is a thing
    # this check cannot tell, and reporting it as a wrong family would be
    # reporting an absence of evidence as evidence.
    wrong_family = [f"{row['stage']}: asked {row['intended_family']}, "
                    f"served {row['served_family']}"
                    for row in stages
                    if row["engine"] == seam_mod.MODEL
                    and row["served_family"] not in ("", "unknown")
                    and row["served_family"] != row["intended_family"]]
    check("each stage was served by the family it asked for",
          not wrong_family, wrong_family)

    ungrounded = _ungrounded(turn)
    check("the model's prose was kept rather than discarded for an "
          "ungrounded figure", not ungrounded, ungrounded)

    check("the ledger reconciles",
          (budget["model_calls_succeeded"] + budget["model_calls_failed"]
           == budget["model_calls_charged"]),
          budget.get("spent"))

    if case.get("must_not_simply_agree"):
        text = " ".join(str(answer.get(k) or "") for k in
                        ("direct", "interpretation"))
        text += " " + " ".join(str(c) for c in (answer.get("caveats") or []))
        pushed_back = any(word in text.lower() for word in (
            "did not", "does not", "not the case", "premise", "in fact",
            "however", "rather than", "no obligor", "none of", "instead"))
        check("the false premise was not simply accepted", pushed_back,
              text[:240])

    return checks, stages


# --------------------------------------------------------------- the runner


def _run_case(case: dict, threads: dict, mode: str) -> dict:
    thread_id = f"live-cert-{case.get('follows') or case['id']}"
    prior = threads.get(thread_id, {})
    started = time.perf_counter()
    error = ""
    turn = None
    try:
        turn = pipe.answer(case["question"], thread_id=thread_id, mode=mode,
                           rolling_summary=prior.get("rolling_summary"))
    except Exception as failure:  # noqa: BLE001 - a failure is a result
        error = f"{type(failure).__name__}: {failure}"
    elapsed = round(time.perf_counter() - started, 2)

    if turn is None:
        return {"id": case["id"], "category": case["category"],
                "question": case["question"], "elapsed_s": elapsed,
                "error": _safe(error), "pass": False, "checks": [],
                "stages": []}

    # The pipeline takes the summary as a plain document, the way the API
    # hands it back to the browser. Passing the object through works until
    # the next turn tries to read it.
    threads[thread_id] = {
        "rolling_summary": (turn.rolling_summary.to_dict()
                            if turn.rolling_summary else None)}
    checks, stages = _check(case, turn)
    budget = turn.budget
    row = {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "elapsed_s": elapsed,
        "resolved_ownership": (turn.selection or {}).get(
            "selected_functionality", ""),
        "ownership_engine": (turn.selection or {}).get("engine", ""),
        "stages_reached": list(turn.stages),
        "stages": stages,
        "model_families": sorted({row["served_family"] for row in stages
                                  if row["served_family"]}),
        "model_calls_charged": budget["model_calls_charged"],
        "model_calls_succeeded": budget["model_calls_succeeded"],
        "model_calls_failed": budget["model_calls_failed"],
        "executions_attempted": budget["executions_attempted"],
        "executions_succeeded": budget["executions_succeeded"],
        "answer_present": bool((turn.answer or {}).get("direct")),
        "answer_scope": (turn.answer or {}).get("scope", ""),
        "grounding": ("kept" if not _ungrounded(turn)
                      else "discarded: " + ", ".join(_ungrounded(turn))),
        "reading": _reading_diagnostics(turn),
        "direct": _safe((turn.answer or {}).get("direct", ""))[:400],
        "checks": checks,
    }
    row["pass"] = all(c["pass"] for c in checks)
    return row


def _provider() -> dict:
    from backend.llm import get_provider

    provider = get_provider()
    status = provider.status()
    return {
        "configured": bool(provider.configured),
        "provider": _safe(status.provider),
        "state": _safe(status.state),
        "detail": _safe(status.detail),
        # The names of the variables that are SET, never their values.
        "environment_present": sorted(
            name for name in ("AI_PROVIDER", "AI_ROUTER_MODEL",
                              "AI_COMPLEX_PLANNER_MODEL", "AI_CRITIC_MODEL",
                              "AI_ANALYST_MODEL", "ANTHROPIC_API_KEY")
            if os.environ.get(name)),
        "routing": [_safe(row) for row in seam_mod.routing()],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT,
                        help="where to write the machine-readable report")
    parser.add_argument("--mode", default=budget_mod.STANDARD,
                        choices=[budget_mod.STANDARD, budget_mod.DEEP])
    parser.add_argument("--only", default="",
                        help="run one case by id, for example LIVE-4")
    parser.add_argument("--stub", action="store_true",
                        help=("run against the repository's test double "
                              "instead of a vendor. Proves the wiring and "
                              "the assertions; certifies nothing."))
    args = parser.parse_args(argv)

    if args.stub:
        from tests.early_warning.stub_provider import StubProvider
        import backend.llm as llm

        stub = StubProvider(name="stub")
        llm.get_provider = lambda *, refresh=False: stub  # type: ignore[assignment]
        print("!! STUB PROVIDER. Nothing below is a vendor call and nothing "
              "here certifies anything.")

    provider = _provider()
    print("PROVIDER")
    print(f"  configured : {provider['configured']}")
    print(f"  provider   : {provider['provider']}")
    print(f"  state      : {provider['state']}")
    print(f"  variables  : {', '.join(provider['environment_present']) or 'none'}"
          "   (names only — no value is read or printed)")
    if not provider["configured"]:
        print()
        print("No AI provider is configured, so nothing here can be certified.")
        print("Set AI_PROVIDER and the model roles, and provide the key with:")
        print('  read -rs -p "Anthropic API key: " ANTHROPIC_API_KEY '
              "&& export ANTHROPIC_API_KEY && echo")
        return 2

    cases = [c for c in CASES if not args.only or c["id"] == args.only]
    # A follow-up needs the turn it follows, so its parent comes too.
    if args.only:
        needed = {c.get("follows") for c in cases if c.get("follows")}
        cases = [c for c in CASES if c["id"] in
                 {*(c["id"] for c in cases), *needed}]

    threads: dict = {}
    results = []
    print()
    print("CERTIFICATION")
    for case in cases:
        row = _run_case(case, threads, args.mode)
        results.append(row)
        mark = "PASS" if row["pass"] else "FAIL"
        print(f"  [{mark}] {row['id']:<8} {row['category']:<26} "
              f"{row['elapsed_s']:>6.2f}s  {row.get('resolved_ownership', '')}")
        for check in row["checks"]:
            if not check["pass"]:
                print(f"           x {check['what']}: {check['detail']}")
        if row.get("error"):
            print(f"           x raised: {row['error']}")

    failed = [r for r in results if not r["pass"]]
    elapsed = [r["elapsed_s"] for r in results]
    report = {
        "verdict": ("STUB_ONLY" if args.stub else
                    "CERTIFIED" if not failed else "NOT_CERTIFIED"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "provider": provider,
        "cases_run": len(results),
        "cases_passed": len(results) - len(failed),
        "cases_failed": [r["id"] for r in failed],
        "required_model_stages": list(REQUIRED_MODEL_STAGES),
        "summary_stage_assertion": (
            f"{SUMMARY_STAGE} must report engine=model and must not spend its "
            f"whole output allowance"),
        # §15's figure, which can only be measured with a provider: offline
        # no model call is made, so the planner receives nothing.
        "largest_planner_input_tokens": max(
            [int(row.get("input_tokens") or 0)
             for r in results for row in r.get("stages", [])
             if row.get("stage") == seam_mod.PLAN] or [0]),
        "largest_input_tokens_any_stage": max(
            [int(row.get("input_tokens") or 0)
             for r in results for row in r.get("stages", [])] or [0]),
        "elapsed_seconds": {
            "total": round(sum(elapsed), 2),
            "median": round(sorted(elapsed)[len(elapsed) // 2], 2) if elapsed else 0,
            "slowest": round(max(elapsed), 2) if elapsed else 0,
        },
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(_safe(report), indent=2, default=str))

    print()
    print(f"  {report['cases_passed']}/{report['cases_run']} certified   "
          f"median {report['elapsed_seconds']['median']}s   "
          f"slowest {report['elapsed_seconds']['slowest']}s")
    print(f"  report: {args.out}")
    print(f"  VERDICT: {report['verdict']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
