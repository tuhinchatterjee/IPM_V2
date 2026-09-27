#!/usr/bin/env python3
"""
Opus360 — overnight certification of the frozen AdvancedCockpit.

    # no spend: the full pipeline against a scripted analyst
    .venv/bin/python scripts/opus360/run_certification.py --suite architecture-v1 --dry-run \
        --run-calibration --run-core --run-load-test --export

    # live (requires OPUS360_MAX_USD and the Cockpit credential)
    OPUS360_MAX_USD=150 .venv/bin/python scripts/opus360/run_certification.py --suite architecture-v1 \
        --live --sequential --resume --run-calibration --run-core --run-load-test --export

Order: preflight -> pre-run summary -> calibration (10 cases) -> calibration
verification -> core (250 turns, sequential) -> load microtest -> export.
Live execution continues past calibration automatically only when every
condition in the brief's §29 holds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

# backend.config.settings reads the V3 namespace at IMPORT time, so it must be
# set before anything imports the backend -- exactly as start.py puts it in the
# API child's environment before that process starts.
os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", os.environ.get("COCKPIT_V4_NAMESPACE", "cockpit_v4"))

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from cert import (  # noqa: E402
    APPROVED_FINGERPRINTS,
    APPROVED_MODEL,
    APPROVED_PRICE_CARD,
    APPROVED_RELEASES,
    FROZEN_COMMIT,
    FROZEN_TAG,
    HARNESS_VERSION,
    protected,  # noqa: E402
)
from cert import oracles as orc  # noqa: E402
from cert.ledger import Experiment, new_experiment_id, now_iso  # noqa: E402
from cert.paths import ARTIFACTS, BANK_PATH, BANK_SHA_PATH, PROTECTED_MANIFEST, ROOT  # noqa: E402

CALIBRATION = ["A-C01", "A-C07", "A-R01", "A-R05", "B-C03-1", "B-R03-2", "C-C02", "C-R06", "E-01",
               "D-TD04-1", "D-TD04-2"]
LOAD = ["A-C01", "A-C07", "A-C12", "C-C02", "C-C05", "A-C17",
        "A-R01", "A-R05", "A-R11", "C-R02", "C-R05", "A-R16"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_bank() -> tuple[dict, str]:
    import yaml

    raw = BANK_PATH.read_bytes()
    doc = yaml.safe_load(raw)
    return doc, sha256_bytes(raw)


class PreflightError(RuntimeError):
    pass


def preflight(args: argparse.Namespace) -> dict:
    """Everything that must be true before the first call. Raises on a hard blocker."""
    out: dict = {"checked_at": now_iso()}
    # P0: baseline
    tag_target = git("rev-parse", f"{FROZEN_TAG}^{{commit}}")
    out["frozen_tag"] = FROZEN_TAG
    out["tag_resolves_to"] = tag_target
    if tag_target != FROZEN_COMMIT:
        raise PreflightError(f"tag {FROZEN_TAG} resolves to {tag_target!r}, expected {FROZEN_COMMIT}")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", FROZEN_COMMIT, "HEAD"], cwd=ROOT).returncode == 0
    out["harness_head"] = git("rev-parse", "HEAD")
    out["frozen_commit_is_ancestor_of_head"] = ancestor
    if not ancestor:
        raise PreflightError("HEAD does not descend from the frozen commit")
    out["git_status_porcelain"] = git("status", "--porcelain", "--untracked-files=no")
    # P2: protected core
    verdict = protected.verify()
    out["protected"] = verdict.to_dict()
    if not verdict.ok:
        raise PreflightError("protected manifest verification failed: " + "; ".join(verdict.problems[:5]))
    # bank
    doc, bank_sha = load_bank()
    stored = BANK_SHA_PATH.read_text(encoding="utf-8").split()[0]
    rows = doc["rows"]
    out.update(bank_sha256=bank_sha, bank_sha_stored=stored, bank_rows=len(rows))
    if bank_sha != stored:
        raise PreflightError("question bank SHA-256 differs from the frozen value")
    if len(rows) != 250 or doc.get("core_turns") != 250:
        raise PreflightError(f"question bank has {len(rows)} rows, not 250")
    # releases
    fps, note = {}, []
    for dom in ("corporate", "retail"):
        integ = orc.release_integrity(dom)
        if not integ.get("present"):
            raise PreflightError(f"{APPROVED_RELEASES[dom]} is not published; run scripts/cockpit_v4/seed_domains.py")
        if not integ["self_consistent"]:
            raise PreflightError(f"{APPROVED_RELEASES[dom]}: parquet bytes do not match the manifest fingerprint")
        fps[dom] = integ["manifest_fingerprint"]
        if fps[dom] != APPROVED_FINGERPRINTS[dom]:
            note.append(f"{dom}: byte fingerprint {fps[dom][:16]} != approved {APPROVED_FINGERPRINTS[dom][:16]} "
                        f"(built_with {integ.get('built_with')})")
    parity = None
    if note:
        parity = content_parity()
        out["content_parity"] = parity
        if not parity["ok"]:
            raise PreflightError("release bytes differ from the approved pair AND content parity failed: "
                                 + json.dumps(parity)[:500])
        note.append(f"content parity against the Round H approved oracle values: {parity['values_compared']} values, "
                    f"{parity['journeys_compared']} journeys, 0 differences")
    out["release_fingerprints"] = fps
    out["release_fingerprint_note"] = " | ".join(note) if note else "matches the approved Round H pair"
    # price card
    card = json.loads((ROOT / APPROVED_PRICE_CARD).read_text(encoding="utf-8"))
    entry = card["models"][APPROVED_MODEL]
    out["price_card"] = {"path": APPROVED_PRICE_CARD, "sha256": sha256_bytes((ROOT / APPROVED_PRICE_CARD).read_bytes()),
                         "verified_at": entry.get("verified_at"), "price": entry["price"]}
    out["model"] = APPROVED_MODEL
    # environment
    out["python"] = platform.python_version()
    out["requirements_sha256"] = sha256_bytes((ROOT / "requirements.txt").read_bytes())
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    if not freeze.strip():
        freeze = subprocess.run(["uv", "pip", "freeze", "--python", sys.executable], capture_output=True, text=True).stdout
    out["pip_freeze_sha256"] = sha256_bytes(freeze.encode("utf-8"))
    out["key_packages"] = {p: _version(p) for p in ("anthropic", "duckdb", "pandas", "pyarrow", "numpy", "fastapi")}
    # live prerequisites
    cap = os.environ.get("OPUS360_MAX_USD", "").strip()
    hours = os.environ.get("OPUS360_MAX_HOURS", "").strip()
    out["max_usd"] = float(cap) if cap else None
    out["max_hours"] = float(hours) if hours else None
    if args.live:
        if out["max_usd"] is None or out["max_usd"] <= 0:
            raise PreflightError("OPUS360_MAX_USD is not set; no paid call will be made")
        # §27: no paid call until the fixture validation passed on THIS harness source.
        from run_fixture_validation import OUT as FIXTURE_DIR
        from run_fixture_validation import harness_tree_sha

        fx_path = FIXTURE_DIR / "fixture_validation.json"
        if not fx_path.exists():
            raise PreflightError("fixture validation has not been run: "
                                 ".venv/bin/python scripts/opus360/run_fixture_validation.py")
        fx = json.loads(fx_path.read_text(encoding="utf-8"))
        if not fx.get("ok"):
            raise PreflightError(f"fixture validation did not pass: {fx.get('not_passed')}")
        if fx.get("harness_tree_sha256") != harness_tree_sha():
            raise PreflightError("the harness changed after fixture validation; re-run "
                                 "scripts/opus360/run_fixture_validation.py")
        if fx.get("platform_system") != platform.system() or fx.get("python") != platform.python_version():
            raise PreflightError(f"fixture validation was recorded on {fx.get('platform_system')} / Python "
                                 f"{fx.get('python')}; validate on THIS machine first: "
                                 ".venv/bin/python scripts/opus360/run_fixture_validation.py")
        out["fixture_validation"] = {k: fx[k] for k in ("tests", "passed", "harness_tree_sha256", "validated_at")}
        key, source = obtain_credential(allow_prompt=sys.stdin.isatty())
        if not key:
            raise PreflightError("COCKPIT_ANTHROPIC_API_KEY is not available (environment, macOS Keychain "
                                 "'creditprobe-cockpit-v4', or an interactive prompt)")
        os.environ["COCKPIT_ANTHROPIC_API_KEY"] = key
        out["credential_source"] = source
    else:
        out["credential_source"] = "not needed (dry run)"
    return out


def _version(pkg: str) -> str:
    try:
        from importlib.metadata import version

        return version(pkg)
    except Exception:  # noqa: BLE001
        return "absent"


def obtain_credential(*, allow_prompt: bool) -> tuple[str, str]:
    """The frozen launcher's own mechanism, imported read-only."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("cockpit_v4_start", ROOT / "scripts" / "cockpit_v4" / "start.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cockpit_v4_start"] = module
    spec.loader.exec_module(module)
    return module.obtain_credential(allow_prompt=allow_prompt)


def content_parity() -> dict:
    """Recompute the Round H approved oracle values on this runtime's releases."""
    import importlib.util
    import math

    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT / "tests" / "cockpit_v4"))
    spec = importlib.util.spec_from_file_location("live_uat", ROOT / "scripts" / "cockpit_v4" / "live_uat.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["live_uat"] = module
    spec.loader.exec_module(module)
    approved = json.loads((ROOT / "docs" / "cockpit_v4" / "evidence" / "live_uat_dry_run.json").read_text())
    index = {j.jid: j for j in module.matrix()}

    def flat(x, p=""):
        if isinstance(x, dict):
            for k, v in x.items():
                yield from flat(v, f"{p}/{k}")
        elif isinstance(x, (list, tuple)):
            for i, v in enumerate(x):
                yield from flat(v, f"{p}[{i}]")
        else:
            yield p, x

    journeys = values = 0
    diffs = []
    for j in approved["journeys"]:
        exp = (j.get("oracle") or {}).get("expected")
        jr = index.get(j["journey"])
        if exp is None or jr is None or jr.oracle is None:
            continue
        got = jr.oracle()
        a = dict(flat(json.loads(json.dumps(exp, default=str))))
        b = dict(flat(json.loads(json.dumps(got, default=str))))
        journeys += 1
        for k in set(a) | set(b):
            values += 1
            x, y = a.get(k), b.get(k)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if not math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9):
                    diffs.append((j["journey"], k, x, y))
            elif str(x) != str(y):
                diffs.append((j["journey"], k, x, y))
    return {"ok": journeys > 0 and not diffs, "journeys_compared": journeys, "values_compared": values,
            "differences": diffs[:20],
            "source": "docs/cockpit_v4/evidence/live_uat_dry_run.json (Round H, approved releases)"}


def pre_run_summary(pf: dict, exp: Experiment, bank_rows: list[dict], refs: dict, live: bool) -> str:
    corp = sum(1 for r in bank_rows if r["domain"] == "corporate")
    threads = len({r["thread_id"] for r in bank_rows if r["test_class"] == "D_THREAD"})
    oracle_cov = {}
    for r in bank_rows:
        oracle_cov[r["oracle_type"]] = oracle_cov.get(r["oracle_type"], 0) + 1
    lines = [
        "=" * 78, "OPUS360 PRE-RUN SUMMARY", "=" * 78,
        f"frozen commit           {FROZEN_COMMIT} ({FROZEN_TAG})",
        f"harness HEAD            {pf['harness_head']}",
        f"protected manifest      {'PASS' if pf['protected']['ok'] else 'FAIL'} ({pf['protected']['checked_files']} files)",
        f"question bank           {pf['bank_rows']} core turns, sha256 {pf['bank_sha256']}",
        f"corporate / retail      {corp} / {len(bank_rows) - corp}",
        f"threads                 {threads} (x5 turns)",
        f"oracle coverage         {oracle_cov} ({len(refs)} references frozen)",
        f"live model              {APPROVED_MODEL} ({'LIVE' if live else 'DRY RUN - scripted analyst'})",
        f"resolved model          {'recorded per call from the SDK response' if live else 'n/a (scripted)'}",
        f"spend cap               {pf['max_usd'] if pf['max_usd'] is not None else 'NOT SET'}",
        f"wall-clock cap          {pf['max_hours'] if pf['max_hours'] is not None else 'none'}",
        f"releases                {json.dumps(pf['release_fingerprints'])}",
        f"release note            {pf['release_fingerprint_note']}",
        f"runtime directory       {exp.runtime_dir}",
        f"evidence directory      {exp.root}",
        f"credential              {pf['credential_source']}", "=" * 78]
    return "\n".join(lines)


def build_refs(bank_rows: list[dict], calibration: list[dict], load: list[dict]) -> dict:
    refs = {}
    for row in bank_rows + calibration + load:
        for label, key in (("primary", "oracle"), ("followup", "followup_oracle")):
            spec = row.get(key)
            if spec:
                refs[f"{row['case_id']}:{label}"] = orc.compute(spec, spec.get("domain") or row["domain"])
    return refs


def calibration_cases(by_id: dict) -> list[dict]:
    out = []
    for cid in CALIBRATION:
        row = dict(by_id[cid])
        row["case_id"] = f"CAL-{cid}"
        row["thread_id"] = f"CAL-{row['thread_id']}"
        if row.get("preserve_from"):
            row["preserve_from"] = f"CAL-{row['preserve_from']}"
        out.append(row)
    return out


def load_cases(by_id: dict) -> list[dict]:
    out = []
    for cid in LOAD:
        row = dict(by_id[cid])
        row["case_id"] = f"LOADQ-{cid}"
        out.append(row)
    return out


def verify_calibration(exp: Experiment, live: bool, pf: dict, price) -> dict:
    """P10: the instrumentation itself, checked on the calibration turns."""
    rows = [r for r in exp.results() if r.get("phase") == "calibration" and r.get("record_type") == "turn"]
    checks: dict[str, dict] = {}

    def check(name: str, ok: bool, detail: str) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    check("all_calibration_turns_recorded", len(rows) == len(CALIBRATION), f"{len(rows)}/{len(CALIBRATION)}")
    native = all(isinstance(r.get("native_input_tokens"), int) and isinstance(r.get("native_output_tokens"), int)
                 for r in rows if r.get("model_calls"))
    check("native_tokens_captured", native, "input/output are provider-native integers on every turn with model calls")
    check("tokens_reconcile_with_product_ledger", all(r.get("tokens_reconcile") for r in rows if r.get("model_calls")),
          "harness per-call totals == reservations.usage totals")
    cost_ok = all(abs(float(r.get("cost_usd") or 0) - float(r.get("cost_independent_usd") or 0)) < 1e-6
                  for r in rows if isinstance(r.get("cost_independent_usd"), float))
    check("cost_calculation_matches_price_card", cost_ok, "product ledger cost == tokens x verified price card")
    timing = all(isinstance(r.get("provider_ms"), int) and isinstance(r.get("e2e_processing_ms"), int) for r in rows)
    check("provider_and_local_timing_captured", timing, "provider_ms and e2e_processing_ms present")
    if live:
        http = all((r.get("provider_http_ms") not in (None, "UNKNOWN")) for r in rows if r.get("model_calls"))
        check("http_attempts_observed", http, "httpx shim saw the provider's HTTP attempts")
        served = all(r.get("served_models") == [APPROVED_MODEL] or any(
            str(m).startswith(APPROVED_MODEL) for m in r.get("served_models") or []) for r in rows if r.get("model_calls"))
        check("served_model_is_approved", served, f"served models: {sorted({m for r in rows for m in r.get('served_models') or []})}")
    subs = all(int(r.get("analysis_submissions") or 0) > 0 for r in rows if r.get("oracle_type") in ("EXACT", "ANALYTICAL")
               and r.get("behaviour_observed") == "ANSWER")
    check("submitted_analysis_saved", subs, "every answered numeric turn has >=1 persisted submission")
    tools = True
    for r in rows:
        ev = json.loads(Path(r["evidence_dir"], "events.json").read_text())
        requested = sum(1 for e in ev if e.get("event_type") == "tool.requested")
        tele = json.loads(Path(r["evidence_dir"], "telemetry.json").read_text())
        tools &= requested == len(tele.get("tools") or [])
    check("tool_calls_saved", tools, "tool rows == tool.requested events")
    oracle = all(r.get("oracle_pass") is not None for r in rows if r.get("oracle_type") in ("EXACT", "ANALYTICAL")
                 and r.get("behaviour_observed") in ("ANSWER", "PARTIAL"))
    check("oracle_comparison_works", oracle, "every answered numeric turn has an oracle verdict")
    claims = all(Path(r["evidence_dir"], "verdict.json").exists() for r in rows)
    check("claims_evaluated", claims, "verdict.json (claims, unbound numbers) written for every turn")
    answers = all(r.get("terminal_state") for r in rows)
    check("final_answer_saved", answers, "terminal state + final_response persisted")
    verdict = protected.verify()
    check("protected_core_unchanged", verdict.ok, "; ".join(verdict.problems[:3]) or "ok")
    ok = all(c["ok"] for c in checks.values())
    result = {"ok": ok, "live": live, "checks": checks, "verified_at": now_iso()}
    (exp.root / "calibration_verification.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", default="architecture-v1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sequential", action="store_true", help="accepted; the core run is always concurrency 1")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--experiment", default="", help="experiment id to resume (default: latest of this mode)")
    parser.add_argument("--run-calibration", action="store_true")
    parser.add_argument("--run-core", action="store_true")
    parser.add_argument("--run-load-test", action="store_true")
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated core case ids (diagnostics)")
    parser.add_argument("--max-turns", type=int, default=0, help="cap the core phase (diagnostics)")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--no-static-count", action="store_true",
                        help="live: skip provider-counted static blocks in token decomposition")
    args = parser.parse_args()
    live = bool(args.live)

    try:
        pf = preflight(args)
    except PreflightError as exc:
        print(f"PREFLIGHT BLOCKED: {exc}")
        if live:
            print("\nNo paid call was made. To start the live certification once the blocker is fixed:\n"
                  "  export OPUS360_MAX_USD=<your cap in USD>   # e.g. 150\n"
                  "  launchers/START_OPUS360_OVERNIGHT.command\n")
        return 2
    if args.preflight_only:
        print(json.dumps(pf, indent=1, default=str))
        return 0

    doc, bank_sha = load_bank()
    bank_rows = doc["rows"]
    by_id = {r["case_id"]: r for r in bank_rows}
    cal_rows, load_rows = calibration_cases(by_id), load_cases(by_id)
    refs = build_refs(bank_rows, cal_rows, load_rows)
    refs_blob = json.dumps({k: {"sha256": v.sha256(), "reference": v.to_dict()} for k, v in sorted(refs.items())},
                           sort_keys=True, default=str)
    refs_sha = sha256_bytes(refs_blob.encode("utf-8"))

    # experiment folder
    suffix = "live" if live else "dry"
    if args.resume:
        if args.experiment:
            root = ARTIFACTS / args.experiment
        else:
            cands = sorted(p for p in ARTIFACTS.glob(f"{args.suite}-{suffix}-*") if (p / "manifest.json").exists())
            root = cands[-1] if cands else None
        if root is None or not (root / "manifest.json").exists():
            print("nothing to resume; starting a new experiment")
            args.resume = False
    if not args.resume:
        root = ARTIFACTS / new_experiment_id(args.suite, live)
    exp = Experiment(root)
    if not args.resume:
        manifest = {"experiment_id": root.name, "suite": args.suite, "live": live, "harness_version": HARNESS_VERSION,
                    "frozen_tag": FROZEN_TAG, "frozen_commit": FROZEN_COMMIT, "harness_head": pf["harness_head"],
                    "protected_manifest_sha256": pf["protected"]["manifest_sha256"],
                    "protected_manifest_path": str(PROTECTED_MANIFEST.relative_to(ROOT)),
                    "bank_sha256": bank_sha, "bank_path": str(BANK_PATH.relative_to(ROOT)),
                    "oracle_refs_sha256": refs_sha, "oracle_version": orc.ORACLE_VERSION,
                    "model": APPROVED_MODEL, "price_card": pf["price_card"], "releases": APPROVED_RELEASES,
                    "release_fingerprints": pf["release_fingerprints"],
                    "release_fingerprint_note": pf["release_fingerprint_note"],
                    "approved_fingerprints": APPROVED_FINGERPRINTS, "python": pf["python"],
                    "requirements_sha256": pf["requirements_sha256"], "pip_freeze_sha256": pf["pip_freeze_sha256"],
                    "key_packages": pf["key_packages"], "max_usd": pf["max_usd"], "max_hours": pf["max_hours"],
                    "credential_source": pf["credential_source"], "platform": platform.platform(),
                    "calibration_cases": CALIBRATION, "load_cases": LOAD, "created_at": now_iso(),
                    "preflight": {k: v for k, v in pf.items() if k not in ("protected",)}}
        exp.create(manifest)
        (root / "oracle_references.json").write_text(refs_blob, encoding="utf-8")
    else:
        m = exp.manifest()
        if m.get("bank_sha256") != bank_sha or m.get("oracle_refs_sha256") != refs_sha:
            print("RESUME REFUSED: the bank or oracle references differ from the experiment's manifest")
            return 2
    exp.claim_ownership(sys.argv)
    exp.event("session_start", argv=sys.argv, pid=os.getpid())
    print(pre_run_summary(pf, exp, bank_rows, refs, live), flush=True)

    # boot the frozen app
    from cert.engine import CockpitHarness
    from cert.observe import Recorder
    from cert.runner import Guards, Price, Runner, install_signal_handlers, order_cases

    recorder = Recorder(exp.calls_root)
    harness = CockpitHarness(exp.runtime_dir, live=live, recorder=recorder)
    if harness.preflight_error:
        print(f"RUNTIME PREFLIGHT FAILED: {harness.preflight_error}")
        exp.error("runtime_preflight", harness.preflight_error)
        return 2
    exp.event("runtime_booted", health=harness.health(), capability=harness.capability(), shims=harness.shims)
    price_entry = pf["price_card"]["price"]
    price = Price(price_entry["input_usd_per_mtok"], price_entry["output_usd_per_mtok"],
                  price_entry["cache_write_usd_per_mtok"], price_entry["cache_read_usd_per_mtok"],
                  pf["price_card"]["path"])
    guards = Guards(live=live, max_usd=pf["max_usd"], max_hours=pf["max_hours"], stop_file=root / "STOP")
    install_signal_handlers(guards)
    script_factory = None
    if not live:
        from cert.scripted import analyst_for

        def script_factory(case, ref, domain, behaviour, attempt):  # noqa: ANN001
            return analyst_for(case, ref, domain=domain, behaviour=behaviour)

    static_counter = None
    if live and not args.no_static_count:
        cache: dict[str, int] = {}
        inner = harness.provider._inner

        def static_counter(kind, obj):  # noqa: ANN001
            key = hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
            if key not in cache:
                try:
                    if kind == "tool_schema":
                        base = inner.count_tokens(system="x", messages=[{"role": "user", "content": "x"}],
                                                  tools=None, model=APPROVED_MODEL)
                        full = inner.count_tokens(system="x", messages=[{"role": "user", "content": "x"}],
                                                  tools=obj, model=APPROVED_MODEL)
                    else:
                        text = obj.get("text") if isinstance(obj, dict) else str(obj)
                        base = inner.count_tokens(system="x", messages=[{"role": "user", "content": "x"}],
                                                  tools=None, model=APPROVED_MODEL)
                        full = inner.count_tokens(system=[{"type": "text", "text": "x"}, {"type": "text", "text": text}],
                                                  messages=[{"role": "user", "content": "x"}], tools=None,
                                                  model=APPROVED_MODEL)
                    cache[key] = max(0, int(full) - int(base))
                except Exception:  # noqa: BLE001
                    cache[key] = -1
            return cache[key] if cache[key] >= 0 else None

    runner = Runner(exp, harness, recorder, bank_rows=bank_rows, refs=refs, price=price, guards=guards, live=live,
                    script_factory=script_factory, static_counter=static_counter,
                    protected_manifest_sha=pf["protected"]["manifest_sha256"])

    exit_code = 0
    if args.run_calibration:
        exp.log("P9: calibration (10 representative cases, 11 turns)")
        summary = runner.run_phase("calibration", cal_rows, batch=100)
        cal = verify_calibration(exp, live, pf, price)
        exp.log(f"P10: calibration instrumentation {'PASS' if cal['ok'] else 'FAIL'}: "
                + ", ".join(f"{k}={'ok' if v['ok'] else 'FAIL'}" for k, v in cal["checks"].items()))
        if not cal["ok"] or summary.get("stopped"):
            exp.log("STOP: calibration did not verify; the core run will not start. Fix the certification harness only.")
            args.run_core = args.run_load_test = False
            exit_code = 3
    if args.run_core:
        cases = order_cases(bank_rows)
        if args.only:
            wanted = [x.strip() for x in args.only.split(",") if x.strip()]
            cases = [c for c in cases if c["case_id"] in wanted]
        if args.max_turns:
            cases = cases[:args.max_turns]
        exp.log(f"P11: core certification, {len(cases)} planned turns, concurrency 1")
        summary = runner.run_phase("core", cases)
        if summary.get("stopped"):
            exit_code = 4
            if summary["stopped"]["condition"] == "INVALID_PROTECTED_CORE_CHANGED":
                args.run_load_test = False
    if args.run_load_test and exit_code in (0,):
        exp.log("P12: load microtest (12 questions at concurrency 1, 2, 4)")
        try:
            runner.run_load(load_rows)
        except Exception as exc:  # noqa: BLE001
            exp.error("load", repr(exc))
            exp.log(f"load microtest stopped: {exc}")
    if args.export:
        from cert import reports

        files = reports.build(exp, bank_rows)
        exp.log(f"P13: exported {len(files)} files to {exp.root}")
    harness.close()
    exp.event("session_end", exit_code=exit_code)
    if args.export:
        # Last write of the session, so every file it covers is final.
        exp.write_checksums()
    return exit_code


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # The frozen app's worker/supervisor daemon threads and DuckDB's native
    # threads are still alive here; normal interpreter teardown aborts in C++
    # ("terminate called without an active exception") AFTER every record has
    # been fsync'd. Exit explicitly so the launcher sees the real status.
    os._exit(code)
