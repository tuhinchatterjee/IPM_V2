#!/usr/bin/env python3
"""What a live start would do, and what it would cost. Without doing it.

    .venv/bin/python scripts/retail_cockpit/check_live.py

Run this BEFORE spending anything. It reads the configuration the launcher
would read, loads the price card through the engine's own loader, and reports
the model, the four rates, the caps and the projected cost of the
twelve-question UAT.

It makes NO provider call. It does not construct an Anthropic client, does not
import one, and never prints or logs the credential -- only whether one is
set. The one thing it therefore cannot tell you is whether the provider will
actually serve the model; that is `verify_live`'s job, and it happens when the
engine starts.

It measures the environment THE LAUNCHER WILL USE
-------------------------------------------------
By default it resolves `.env.retail-candidate` exactly as the launcher does --
`set -a; . file` -- and reads the result, not your bare shell. That is not a
nicety. This script used to read `os.environ` alone, so it reported the card
an operator had EXPORTED while the launcher went on to source a file that
overwrote it, and the two never met: the preflight said LIVE READY about the
candidate card, the engine loaded the fail-closed placeholder, and the first
live question came back 503 with no provider call and no spend.

`--env-file ""` reads the bare environment, for when you mean to.

Exit 0 when a live start would work.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: From LIVE_UAT_PLAN.md: twelve runs, ~18,500 input on a first turn and
#: ~22,000 on the follow-up, <= 4,000 output. Generations per run is the
#: number that actually decides the bill, and `config.py` records the
#: measured shape: "metadata, submission, one repair and a finalization --
#: four generations".
UAT_RUNS = 12
UAT_INPUT_TOKENS = 18_500
UAT_OUTPUT_TOKENS = 4_000
UAT_GENERATIONS = 4


def resolve(env_file: str) -> dict[str, str]:
    """The environment the launcher will hand the engine.

    The launcher does `set -a; . "$ENV_FILE"; set +a`, so the file is SHELL,
    not a key-value list: its `${VAR:-default}` forms have to be expanded by a
    shell that already holds the current environment. So a shell expands it
    and prints the result, rather than this script pretending to parse it --
    a parser that ignored the `:-` forms would report the file's defaults over
    an operator's exports and reintroduce the very mismatch this exists to
    stop.
    """
    if not env_file:
        return {}
    path = Path(env_file)
    if not path.exists():
        return {}
    script = (f'set -a; . "{path}"; set +a; '
              f'python3 -c "import json,os;print(json.dumps(dict(os.environ)))"')
    done = subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, cwd=str(ROOT))
    if done.returncode != 0:
        raise SystemExit(f"{path} could not be resolved: "
                         f"{(done.stderr or '').strip()[:300]}")
    return {k: v for k, v in json.loads(done.stdout).items()
            if isinstance(v, str)}


#: Settings whose value names a place on disk. Anchored to the repository
#: root before anything reads them, because the engine resolves a relative
#: path against the PROCESS WORKING DIRECTORY -- so which ledger a cap counts
#: and which lake a release is looked for in would otherwise depend on where
#: the operator happened to be standing.
PATH_SETTINGS = ("DATA_ANALYTICS_DIR", "METADATA_DIR",
                 "COCKPIT_V4_RUNTIME_DIR", "COCKPIT_V4_STATE_DATABASE",
                 "COCKPIT_V4_PRICE_CARD")


def anchored(value: str) -> str:
    """A relative path made absolute against ROOT. Creates nothing.

    Deliberately NOT `backend.config._resolve_dir`, which `mkdir`s what it
    resolves. A script that creates the book directory it was about to read
    turns a loud "this is not published" into a quiet pass over an empty
    book, which is the opposite of what reading it was for.
    """
    value = value.strip()
    if not value or value.startswith("~"):
        return value
    path = Path(value)
    return str(path if path.is_absolute() else (ROOT / path))


def apply_environment(env_file: str) -> dict[str, str]:
    """Resolve the candidate's configuration INTO THIS PROCESS, once.

    `resolve()` reports what the launcher would use; this makes the calling
    process actually use it, with every path absolute. Two things make the
    ordering load-bearing for any caller, and neither is tidiness:

    * `backend/config.py` ends with `settings = _load()` at module scope and
      `lake.root()` is derived from it, so resolving after the first
      `backend.*` import leaves the caller reading a different lake than the
      engine serves from;
    * `config._resolve_dir` creates what it resolves, so importing backend
      under a bare shell silently makes `data/analytics` and friends in the
      worktree.

    So callers do this before importing backend. It is the repair for a live
    UAT that judged a paid answer against `data/retail/analytics` -- a path
    that does not exist in a candidate clone -- because the script resolved
    the env file in a SUBPROCESS and then read its own bare shell.
    """
    resolved = resolve(env_file)
    for name in PATH_SETTINGS:
        if resolved.get(name):
            resolved[name] = anchored(resolved[name])
    os.environ.update(resolved)
    # An exported value is anchored too: a shell holds a relative path as
    # readily as the file does.
    for name in PATH_SETTINGS:
        if not resolved.get(name) and os.environ.get(name):
            os.environ[name] = anchored(os.environ[name])
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--env-file", default=str(ROOT / ".env.retail-candidate"),
        help="resolve this the way the launcher does before reading the "
             "configuration. Pass an empty string to read the bare shell.")
    args = parser.parse_args()

    resolved = resolve(args.env_file)
    if resolved:
        os.environ.update(resolved)

    from backend.cockpit_v4 import capability as cap_mod
    from backend.cockpit_v4 import config as config_mod
    from backend.cockpit_v4 import model_capabilities as caps
    from backend.retail_cockpit_host import spend

    report: dict[str, object] = {}
    findings: list[str] = []

    cfg = config_mod.load()
    model = str(cfg.reasoning_model or "")
    report["model"] = model or None
    if not model:
        findings.append(
            f"{config_mod.REASONING_MODEL_VAR} is not set. The engine does "
            f"not default a model.")

    # Credential: PRESENCE only. The value is never read into a variable that
    # could be printed, and never leaves this line.
    has_key = bool(os.environ.get(config_mod.CREDENTIAL_VAR, "").strip())
    report["credential"] = ("set" if has_key else "missing")
    if not has_key:
        findings.append(
            f"{config_mod.CREDENTIAL_VAR} is not set in this environment, so "
            f"no live call is possible. Export it in the shell that runs the "
            f"launcher; never write it into the env file.")

    card_path = str(cfg.price_card_path or "")
    report["price_card"] = card_path or None
    capability = None
    if not card_path:
        findings.append("COCKPIT_V4_PRICE_CARD is not set.")
    elif not model:
        pass
    else:
        try:
            capability = cap_mod.load_price_card(
                card_path, model_id=model, provider=cfg.provider)
        except cap_mod.CapabilityUnverified as exc:
            findings.append(str(exc))

    if capability is not None:
        price = capability.price.to_dict()
        report["price"] = price
        report["context_tokens"] = capability.context_tokens
        report["max_output_tokens"] = capability.max_output_tokens
        if any(v <= 0 for v in price.values()):
            findings.append(
                "a billing class is priced at zero. The loader accepts it, "
                "and `budgets.affordable` then treats the per-run ceiling as "
                "unenforceable while still reporting cost_enforced. A live "
                "card must carry real prices.")
        per_generation = capability.price.cost(
            input_tokens=UAT_INPUT_TOKENS, output_tokens=UAT_OUTPUT_TOKENS)
        per_run = per_generation * UAT_GENERATIONS
        report["projected"] = {
            "per_generation_usd": round(per_generation, 4),
            "generations_assumed_per_run": UAT_GENERATIONS,
            "per_run_usd": round(per_run, 4),
            "runs": UAT_RUNS,
            "uat_total_usd": round(per_run * UAT_RUNS, 2)}

    # What the engine knows about this model's request shape.
    if model:
        traits = caps.traits_for(model)
        report["traits"] = {"source": traits.source,
                            "forced_tool_use": traits.forced_tool_use,
                            "effort_control": traits.effort_control}
        if traits.source == "default":
            findings.append(
                f"{model!r} is not in model_capabilities.REGISTRY (checked "
                f"{caps.CHECKED_AT}), so it gets neutral defaults: forcing is "
                f"assumed and costs a billed 400 if refused, and effort "
                f"control is silently off.")

    # The caps, per run and cumulative.
    limits = config_mod.ANALYTICAL_STANDARD_LIMITS
    report["per_run_ceiling_usd"] = limits.spend_ceiling_usd
    try:
        verdict = spend.allowed()
        report["cumulative"] = verdict.to_dict()
        if verdict.uncapped:
            findings.append(
                f"{spend.CAP_VAR} is not set, so there is NO cumulative cap. "
                f"The engine bounds one run at "
                f"${limits.spend_ceiling_usd:.2f} and counts nothing across "
                f"runs.")
        elif not verdict.allowed:
            findings.append(
                f"the cumulative cap of ${verdict.cap_usd:,.2f} is already "
                f"reached (${verdict.spent_usd:,.2f} recorded). No run will "
                f"be accepted.")
    except spend.SpendCapInvalid as exc:
        findings.append(str(exc))

    report["findings"] = findings
    report["verdict"] = "LIVE READY" if not findings else "NOT LIVE READY"

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"  model             {report.get('model')}")
        traits = report.get("traits") or {}
        print(f"  known to engine   {traits.get('source')} "
              f"(forcing={traits.get('forced_tool_use')}, "
              f"effort={traits.get('effort_control')})")
        print(f"  credential        {report.get('credential')} "
              f"(presence only; the value is never read here)")
        print(f"  price card        {report.get('price_card')}")
        price = report.get("price") or {}
        if price:
            print(f"    input           ${price['input_usd_per_mtok']}/MTok")
            print(f"    output          ${price['output_usd_per_mtok']}/MTok")
            print(f"    cache write     "
                  f"${price['cache_write_usd_per_mtok']}/MTok  (never billed: "
                  f"the engine sends no cache_control)")
            print(f"    cache read      "
                  f"${price['cache_read_usd_per_mtok']}/MTok  (same)")
        projected = report.get("projected") or {}
        if projected:
            print(f"  per run           ~${projected['per_run_usd']} "
                  f"({projected['generations_assumed_per_run']} generations "
                  f"at {UAT_INPUT_TOKENS:,} in / {UAT_OUTPUT_TOKENS:,} out)")
            print(f"  the {projected['runs']}-question UAT  "
                  f"~${projected['uat_total_usd']}")
        print(f"  ceiling per run   ${report.get('per_run_ceiling_usd')} "
              f"(the engine's own, per run)")
        cumulative = report.get("cumulative") or {}
        print(f"  cumulative cap    {cumulative.get('spend_cap_usd')} "
              f"(spent {cumulative.get('spent_usd')})")
        print(f"\n  {report['verdict']}")
        for line in findings:
            print(f"    - {line}")

    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
