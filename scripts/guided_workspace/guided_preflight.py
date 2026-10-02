#!/usr/bin/env python3
"""Refuse to start the Guided Risk Workspace Mac UAT on anything but the
build the regression of record was run on.

Every check is named and any failure is a refusal (LAUNCH01-05):

1. **The exact candidate.** `git rev-parse HEAD` must EQUAL the SHA pinned
   in `docs/guided_workspace/UAT_CANDIDATE.json`, read from the programme
   branch (the evidence commit that recorded the regression of record on
   that SHA), and the working tree must be clean. No tag exists by decision;
   the pinned SHA is the candidate. There is no `--any-revision`.
   The scenario-library, Lens and metric seed definitions must hash to the
   digests the manifest recorded, and a runtime directory left by another
   build is refused (`--fresh` moves it aside), so every seeded object the
   UAT sees comes from the pinned build.
2. **Python >= 3.12** and the candidate interpreter (`.venv-whatif`), with
   `pip check` clean (LAUNCH01, LAUNCH02).
3. **Frontend**: Next.js installed in `frontend/node_modules` (LAUNCH03).
4. **Books**: both What-If candidate releases published with the expected
   fingerprints, plus the legacy compatibility release (LAUNCH04).
5. **Emulators**: both artifact sets present, gate verdicts read out --
   Retail's failed G4 is printed, because Method 2 stays UNAVAILABLE there
   (LAUNCH05).
6. **Both Guided Workspace books** verified by fingerprint, and the
   **model and price card** resolved without a provider call.
7. **Credential**: present in the approved macOS Keychain item, by NAME
   only; the value is never read here, printed or written. A shell variable
   is accepted only with `--credential-from-shell`, stated in the output.

Nothing here starts a server or takes a port.

    .venv-whatif/bin/python scripts/guided_workspace/guided_preflight.py
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "whatif"))

import uat_preflight as wf  # noqa: E402  (the What-If checks, reused as-is)

OK, BAD = wf.OK, wf.BAD
KEYCHAIN_SERVICE = os.environ.get("CREDITPROBE_KEYCHAIN_SERVICE",
                                  "creditprobe-cockpit-v4")
COMPAT_RELEASE = "v4-saudi-20q-v1"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


MANIFEST_PATH = "docs/guided_workspace/UAT_CANDIDATE.json"
BRANCH = "claude/guided-workspace-exhaustive-validation"
RUNTIME_DIR = Path.home() / ".creditprobe" / "guided_workspace_uat"
#: The verified price card lives OUTSIDE the checkout, so filling it in never
#: dirties the pinned tree. The committed card is a placeholder by design.
PRICE_CARD = Path(os.environ.get(
    "COCKPIT_V4_PRICE_CARD",
    str(Path.home() / ".creditprobe" / "price_card.json"))).expanduser()


def manifest() -> dict | None:
    """The pinned candidate, read from the programme branch's evidence
    commit (local branch first, then origin), or from `--manifest`."""
    override = os.environ.get("GUIDED_UAT_MANIFEST", "")
    if override:
        return json.loads(Path(override).expanduser().read_text())
    for ref in (BRANCH, f"origin/{BRANCH}"):
        out = subprocess.run(["git", "show", f"{ref}:{MANIFEST_PATH}"],
                             cwd=ROOT, capture_output=True, text=True)
        if out.returncode == 0:
            return json.loads(out.stdout)
    return None


def seed_digests() -> dict[str, str]:
    import hashlib

    from backend.workspace import lens_seed, metric_catalog, scenario_seed

    def digest(value) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True,
                                         default=str).encode()).hexdigest()
    return {"scenario_templates": digest([scenario_seed.SEED_VERSION,
                                          scenario_seed.TEMPLATES]),
            "lenses": digest([lens_seed.SEED_VERSION, lens_seed.LENSES]),
            "metrics": digest([metric_catalog.CATALOG_VERSION,
                               metric_catalog.METRICS])}


def seed_versions() -> dict[str, str]:
    from backend.workspace import lens_seed, metric_catalog, scenario_seed
    return {"scenario_templates": scenario_seed.SEED_VERSION,
            "lenses": lens_seed.SEED_VERSION,
            "metrics": metric_catalog.CATALOG_VERSION}


def revision() -> list[str]:
    m = manifest()
    head = git("rev-parse", "HEAD")
    if m is None:
        return [f"{BAD}no candidate manifest ({MANIFEST_PATH} on {BRANCH}). "
                f"Run `git fetch origin {BRANCH}` first."]
    expected = m.get("expected_guided_uat_sha", "")
    if head != expected:
        return [f"{BAD}HEAD {head[:12]} is not the pinned candidate "
                f"{expected[:12]}. Check it out exactly:\n"
                f"    git checkout --detach {expected}"]
    dirty = git("status", "--porcelain")
    if dirty:
        return [f"{BAD}the working tree has changes; the candidate must run "
                f"exactly as committed:\n{dirty}"]
    print(f"{OK}candidate {head} = pinned EXPECTED_GUIDED_UAT_SHA; tree "
          f"clean; regression of record: {m.get('regression_status', '?')}")
    return []


def seeds() -> list[str]:
    want = (manifest() or {}).get("seed_digests", {})
    got = seed_digests()
    bad = [k for k in got if want.get(k) != got[k]]
    if bad:
        return [f"{BAD}seed definitions differ from the pinned build: {bad}"]
    versions = ", ".join(f"{k} {v}" for k, v in seed_versions().items())
    print(f"{OK}seed definitions match the pinned build ({versions})")
    return []


def runtime_dir(fresh: bool) -> list[str]:
    marker = RUNTIME_DIR / ".candidate_sha"
    head = git("rev-parse", "HEAD")
    if RUNTIME_DIR.exists() and any(RUNTIME_DIR.iterdir()):
        owner = marker.read_text().strip() if marker.exists() else "unknown"
        if owner != head:
            if not fresh:
                return [f"{BAD}{RUNTIME_DIR} holds state from build "
                        f"{owner[:12]}; its seeded objects would not be this "
                        f"build's. Re-run with --fresh to move it aside."]
            aside = RUNTIME_DIR.with_name(
                f"{RUNTIME_DIR.name}.{time.strftime('%Y%m%dT%H%M%S')}")
            RUNTIME_DIR.rename(aside)
            print(f"{OK}previous runtime moved aside to {aside}")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    marker.write_text(head + "\n")
    print(f"{OK}dedicated runtime directory {RUNTIME_DIR}")
    return []


def python_and_pip() -> list[str]:
    if sys.version_info < (3, 12):
        return [f"{BAD}Python {platform.python_version()}; 3.12 or newer is "
                f"required"]
    out = subprocess.run([sys.executable, "-m", "pip", "check"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return [f"{BAD}pip check reports broken requirements:\n"
                f"{out.stdout.strip()}"]
    print(f"{OK}Python {platform.python_version()}; pip check clean")
    return []


def compat_release() -> list[str]:
    """The legacy release the accepted Cockpit serves, in the V3 store."""
    from backend.cockpit_agentic import store
    try:
        man = store.read_manifest(COMPAT_RELEASE)
    except Exception as exc:  # noqa: BLE001  (refusal, printed)
        return [f"{BAD}the legacy compatibility release {COMPAT_RELEASE} is "
                f"not published ({type(exc).__name__}):\n"
                f"    .venv-whatif/bin/python scripts/cockpit_v4/"
                f"seed_release.py --release {COMPAT_RELEASE} --no-evidence"]
    missing = [r for r in man.get("relations", {}) if not (
        store.release_dir(COMPAT_RELEASE) / f"{r}.parquet").exists()]
    if missing:
        return [f"{BAD}compatibility release {COMPAT_RELEASE} is missing "
                f"relations: {missing}"]
    print(f"{OK}compatibility release {COMPAT_RELEASE} published "
          f"({len(man.get('relations', {}))} relations)")
    return []


#: The two Guided Workspace books (Corporate and Retail), both required.
GUIDED_BOOKS = ("v4-saudi-corporate-20q-v4", "v4-saudi-retail-20m-v5")


def guided_books() -> list[str]:
    from backend.cockpit_v4 import lake
    bad = [r for r in GUIDED_BOOKS if not lake.verify(r)]
    if bad:
        return [f"{BAD}Guided Workspace book(s) missing or not verified: "
                f"{bad}. Run scripts/cockpit_v4/seed_domains.py"]
    for r in GUIDED_BOOKS:
        fp = lake.read_manifest(r).get("release_fingerprint", "")
        print(f"{OK}book {r} verified ({str(fp)[:16]})")
    return []


def model_and_price() -> list[str]:
    """The model's capability row and price-card entry, without a call."""
    if not os.environ.get("AI_COCKPIT_REASONING_MODEL", "").strip():
        return [f"{BAD}AI_COCKPIT_REASONING_MODEL is not set. Export the "
                f"exact analyst model id (no default, no 'latest')."]
    if not PRICE_CARD.is_file():
        return [f"{BAD}no price card at {PRICE_CARD}. Copy "
                f"config/cockpit_v4/price_card.json there and fill in your "
                f"model's verified entry (RUNBOOK step 4); the checkout's "
                f"own card stays the placeholder."]
    if PRICE_CARD.resolve().is_relative_to(ROOT):
        return [f"{BAD}the price card {PRICE_CARD} is inside the checkout; "
                f"use one outside it (default ~/.creditprobe/price_card.json)"]
    os.environ["COCKPIT_V4_PRICE_CARD"] = str(PRICE_CARD)
    from backend.cockpit_v4 import config, service
    from backend.cockpit_v4.service import PreflightFailed
    try:
        cap = service.load_capability(config.load(), None, verify=False)
    except PreflightFailed as exc:
        return [f"{BAD}model / price card: {exc}"]
    d = cap.to_dict()
    print(f"{OK}model {d.get('model_id', '?')} verified on {PRICE_CARD} "
          f"(no provider call made)")
    return []


def credential(from_shell: bool) -> list[str]:
    if platform.system() == "Darwin" and shutil.which("security"):
        found = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
            capture_output=True, text=True).returncode == 0
        if found:
            print(f"{OK}provider credential PRESENT (approved Keychain item "
                  f"'{KEYCHAIN_SERVICE}'; value not read here)")
            return []
    if from_shell and os.environ.get("COCKPIT_ANTHROPIC_API_KEY", "").strip():
        print(f"{OK}provider credential PRESENT from the SHELL "
              f"(--credential-from-shell; not the approved Keychain source)")
        return []
    return [f"{BAD}no provider credential in the approved Keychain item "
            f"'{KEYCHAIN_SERVICE}'. Store it once (prompted, never echoed):\n"
            f"    security add-generic-password -s {KEYCHAIN_SERVICE} "
            f"-a \"$USER\" -w"]


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fresh", action="store_true",
                   help="move a runtime directory from another build aside")
    p.add_argument("--credential-from-shell", action="store_true")
    args = p.parse_args()
    print("\nGuided Risk Workspace — Mac UAT preflight")
    print("─" * 60)
    problems: list[str] = []
    problems += revision()
    problems += python_and_pip()
    problems += wf.interpreter()
    problems += wf.frontend()
    if not problems:
        os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
        problems += wf.data()
        problems += compat_release()
        problems += guided_books()
        problems += model_and_price()
        problems += wf.models()
        problems += seeds()
        problems += credential(args.credential_from_shell)
    if not problems:
        problems += runtime_dir(args.fresh)
    print("─" * 60)
    if problems:
        for line in problems:
            print(line)
        print("\nNOT STARTED. Fix the above and run this again.")
        return 1
    print("Preflight passed. The pinned candidate may be started.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
