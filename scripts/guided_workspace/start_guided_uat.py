#!/usr/bin/env python3
"""Start the Guided Risk Workspace for the Mac live-provider UAT (P14).

It does not reimplement a lifecycle. It sets the round's flags and the
credential for THIS run's child processes only and hands over to
`scripts/cockpit_v4/start.py`, which already verifies the model and price
card without a paid call (LAUNCH07), uses the runtime directory's own state
database (LAUNCH08), steps over occupied ports without killing their owner
(LAUNCH09), reports ready only after API and UI health (LAUNCH10) and records
owned pids for STOP (LAUNCH11).

LAUNCH06 -- the credential. Read from the macOS Keychain item
`creditprobe-cockpit-v4` (the accepted V4 item) (override with CREDITPROBE_KEYCHAIN_SERVICE) with
`security find-generic-password -w`, placed in the child environment as
COCKPIT_ANTHROPIC_API_KEY, and never printed, logged or written. A value
exported in the launching shell is IGNORED (removed from the child
environment) unless `--credential-from-shell` is given, which the output
states. `--fresh` is passed to the preflight, which moves a runtime
directory left by another build aside.

    .venv-whatif/bin/python scripts/guided_workspace/start_guided_uat.py
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_PORT, UI_PORT = 8434, 5434
RUNTIME_DIR = Path.home() / ".creditprobe" / "guided_workspace_uat"
#: The verified price card lives OUTSIDE the checkout, so filling it in never
#: dirties the pinned tree. The committed card is a placeholder by design.
PRICE_CARD = Path(os.environ.get(
    "COCKPIT_V4_PRICE_CARD",
    str(Path.home() / ".creditprobe" / "price_card.json"))).expanduser()
COMPAT_RELEASE = "v4-saudi-20q-v1"
CREDENTIAL_VAR = "COCKPIT_ANTHROPIC_API_KEY"
KEYCHAIN_SERVICE = os.environ.get("CREDITPROBE_KEYCHAIN_SERVICE",
                                  "creditprobe-cockpit-v4")

#: Everything the regression of record ran with, on, for this run only.
FLAGS = {
    "COCKPIT_V4_WHATIF_CORPORATE": "1",
    "COCKPIT_V4_WHATIF_RETAIL": "1",
    "COCKPIT_V4_GUIDED_WORKSPACE": "1",
    "NEXT_PUBLIC_GUIDED_WORKSPACE": "1",
    "COCKPIT_V4_LLM_EXCHANGE_TRACE": "1",
    "COCKPIT_V4_MONITORING_SCHEDULER": "1",
    "COCKPIT_V4_LOCAL_DEMO_AUTH": "true",
    "COCKPIT_AGENTIC_V4": "true",
    "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4",
}


def keychain_secret() -> str:
    """The Keychain value, or "". Never printed; never written."""
    if platform.system() != "Darwin" or not shutil.which("security"):
        return ""
    out = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def child_credential(env: dict[str, str], from_shell: bool,
                     read=None) -> tuple[dict[str, str], str]:
    """The child environment's credential and where it came from. The
    approved Keychain item only, unless `--credential-from-shell`: a value
    merely exported in the shell is removed, never silently used."""
    if from_shell:
        return env, "SHELL (--credential-from-shell)"
    env.pop(CREDENTIAL_VAR, None)
    secret = (read or keychain_secret)()
    if secret:
        env[CREDENTIAL_VAR] = secret
    return env, f"Keychain '{KEYCHAIN_SERVICE}'"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-port", type=int, default=API_PORT)
    p.add_argument("--ui-port", type=int, default=UI_PORT)
    p.add_argument("--fresh", action="store_true",
                   help="move a runtime directory from another build aside")
    p.add_argument("--credential-from-shell", action="store_true",
                   help="use COCKPIT_ANTHROPIC_API_KEY from this shell "
                        "instead of the approved Keychain item")
    args = p.parse_args()
    pre = [sys.executable, str(ROOT / "scripts/guided_workspace/"
                               "guided_preflight.py")]
    pre += ["--fresh"] if args.fresh else []
    pre += ["--credential-from-shell"] if args.credential_from_shell else []
    if subprocess.run(pre, cwd=ROOT).returncode != 0:
        print("\nThe UAT was NOT started. Nothing was changed and no port "
              "was taken.")
        return 1
    env, source = child_credential(dict(os.environ),
                                   args.credential_from_shell)
    if not env.get(CREDENTIAL_VAR, "").strip():
        print(f"\n  REFUSED  no provider credential from {source}. A "
              f"live-provider UAT needs one; the value is never printed.")
        return 2
    env.update(FLAGS)
    env.update({"COCKPIT_V4_RUNTIME_DIR": str(RUNTIME_DIR),
                "COCKPIT_V4_PRICE_CARD": str(PRICE_CARD),
                "COCKPIT_V4_RELEASE_ID": COMPAT_RELEASE,
                "PYTHONPATH": str(ROOT)})
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    print("\nGuided Risk Workspace — Mac live-provider UAT")
    print("─" * 60)
    print(f"  revision      {subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()}")
    print(f"  runtime dir   {RUNTIME_DIR} (own state, workspace and LLM "
          f"exchange stores)")
    print("  flags         " + ", ".join(k for k in FLAGS if k.startswith(
        ("COCKPIT_V4_", "NEXT_PUBLIC"))))
    print(f"  model         {env.get('AI_COCKPIT_REASONING_MODEL', '')}")
    print(f"  price card    {PRICE_CARD}")
    print(f"  credential    PRESENT ({source}; value never shown)")
    print("─" * 60)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/cockpit_v4/start.py"),
         "--api-port", str(args.api_port), "--ui-port", str(args.ui_port),
         "--runtime-dir", str(RUNTIME_DIR), "--release", COMPAT_RELEASE,
         "--price-card", str(PRICE_CARD),
         "--no-prompt"],
        cwd=ROOT, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
