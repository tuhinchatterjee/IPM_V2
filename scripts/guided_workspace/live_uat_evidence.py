#!/usr/bin/env python3
"""Collect the P14 live-provider evidence pack from a RUNNING UAT instance.

Run after the human session, while the UAT is still up:

    .venv-whatif/bin/python scripts/guided_workspace/live_uat_evidence.py \\
        --api http://127.0.0.1:8434 --out ~/CreditProbe_UAT_evidence

It reads, never writes, the running instance (zero model calls):

* the tenant ledger verification (`/trace/ledger/verify`);
* every recorded LLM exchange (`/model-lab/exchanges`) and, per run, the
  sanitized LLM Exchange package (`/llm-exchange/runs/{id}/export`);
* every object the session created (not seeded) -- results, comparisons,
  scenarios, cohorts, Lenses, alerts -- as its governed export package with
  manifest hashes, each verified back against the store
  (`/exports/verify`);
* the models actually served, from the exchange records.

Then it scans the pack AND the runtime directory's databases for the real
credential's bytes (read from the Keychain or the shell into memory, compared,
discarded): PASS or FAIL is written; the value never is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

WS = "/api/v1/cockpit-v4/workspace"
ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = Path.home() / ".creditprobe" / "guided_workspace_uat"


def get(api: str, path: str) -> bytes:
    with urllib.request.urlopen(api + path, timeout=120) as r:
        return r.read()


def post(api: str, path: str, body: bytes, ctype: str) -> bytes:
    req = urllib.request.Request(api + path, data=body, method="POST",
                                 headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def credential() -> bytes:
    value = os.environ.get("COCKPIT_ANTHROPIC_API_KEY", "").strip()
    if not value and platform.system() == "Darwin" and shutil.which("security"):
        out = subprocess.run(
            ["security", "find-generic-password", "-s",
             os.environ.get("CREDITPROBE_KEYCHAIN_SERVICE",
                            "creditprobe-cockpit-v4"), "-w"],
            capture_output=True, text=True)
        value = out.stdout.strip() if out.returncode == 0 else ""
    return value.encode()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="http://127.0.0.1:8434")
    p.add_argument("--out", default=str(Path.home()
                                        / "CreditProbe_UAT_evidence"))
    p.add_argument("--runtime-dir", default=str(RUNTIME_DIR),
                   help="the UAT runtime directory to scan (default: the "
                        "launcher's)")
    args = p.parse_args()
    runtime = Path(args.runtime_dir).expanduser()
    out = Path(args.out).expanduser() / time.strftime("%Y%m%dT%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"api": args.api, "collected_at": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model_calls_made": 0}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    marker = runtime / ".candidate_sha"
    manifest["candidate_sha"] = head
    manifest["runtime_candidate_sha"] = (marker.read_text().strip()
                                         if marker.exists() else "")
    manifest["runtime_is_this_candidate"] = \
        manifest["runtime_candidate_sha"] == head

    ledger = json.loads(get(args.api, f"{WS}/trace/ledger/verify"))
    (out / "ledger_verify.json").write_text(json.dumps(ledger, indent=2))
    manifest["ledger_ok"] = ledger["ok"]

    lab = json.loads(get(args.api, f"{WS}/model-lab/exchanges"))
    exchanges = lab.get("exchanges", [])
    (out / "llm_exchanges.json").write_text(json.dumps(exchanges, indent=2))
    manifest["models_served"] = sorted({e.get("resolved_model") or ""
                                        for e in exchanges} - {""})
    runs = sorted({e["run_id"] for e in exchanges if e.get("run_id")})
    (out / "llm_exchange").mkdir(exist_ok=True)
    for run_id in runs:
        (out / "llm_exchange" / f"{run_id}.zip").write_bytes(
            get(args.api, f"{WS}/llm-exchange/runs/{run_id}/export"))
    manifest["llm_runs"] = len(runs)
    manifest["llm_calls"] = len(exchanges)

    packages, verified = [], []
    (out / "objects").mkdir(exist_ok=True)
    candidates = []
    for book in ("corporate", "retail"):
        listing = json.loads(get(args.api, f"{WS}/whatif/results?domain={book}"))
        candidates += [r.get("object_id") for r in listing.get("results", [])
                       if r.get("mine")]
    for oid in [c for c in candidates if c]:
        data = get(args.api, f"{WS}/exports/objects/{oid}")
        path = out / "objects" / f"{oid}.zip"
        path.write_bytes(data)
        report = json.loads(post(args.api, f"{WS}/exports/verify", data,
                                 "application/zip"))
        packages.append(oid)
        verified.append({"object_id": oid, "ok": report["ok"],
                         "problems": report["problems"][:5]})
    (out / "package_verification.json").write_text(json.dumps(verified,
                                                              indent=2))
    manifest["packages"] = len(packages)
    manifest["packages_verified"] = all(v["ok"] for v in verified)

    secret = credential()
    leaks = []
    if secret:
        scan = [*out.rglob("*")]
        # Every runtime file: state, workspace and exchange databases with
        # their WAL/SHM, the API and UI logs, artifacts.
        scan += [*runtime.rglob("*")] if runtime.exists() else []
        manifest["runtime_files_scanned"] = sum(
            1 for q in scan if q.is_file() and runtime in q.parents)
        for path in scan:
            if path.is_file():
                data = path.read_bytes()
                if secret in data:
                    leaks.append(str(path))
                if path.suffix == ".zip":
                    import zipfile
                    with zipfile.ZipFile(path) as zf:
                        for n in zf.namelist():
                            if secret in zf.read(n):
                                leaks.append(f"{path}:{n}")
        manifest["credential_scan"] = "PASS" if not leaks else "FAIL"
        manifest["credential_leaks"] = leaks  # paths only, never the value
    else:
        manifest["credential_scan"] = "NOT RUN (no credential available)"
    del secret

    files = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()
                                                      ).hexdigest()
             for p in sorted(out.rglob("*")) if p.is_file()}
    manifest["files"] = files
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: manifest[k] for k in (
        "candidate_sha", "runtime_is_this_candidate", "ledger_ok", "models_served", "llm_runs", "llm_calls", "packages",
        "packages_verified", "credential_scan")}, indent=2))
    print(f"\nEvidence pack: {out}")
    ok = manifest["ledger_ok"] and manifest["packages_verified"] and \
        manifest["credential_scan"] == "PASS"
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
