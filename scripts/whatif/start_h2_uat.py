#!/usr/bin/env python3
"""Start the What-If UAT candidate on the established Cockpit V4 lifecycle.

WHY THIS EXISTS RATHER THAN `start_candidate.py`
------------------------------------------------
The H1 launcher could not start a server at all. It ran

    uvicorn backend.main:app

and `backend/main.py` has never existed in this repository, so uvicorn exited
with `ModuleNotFoundError`. Because that launcher never waited for health, it
went on to print the API and UI URLs as though everything were up. A live UAT
was driven against a server that was not running.

It had three further defects that the same UAT exposed:

* it set `COCKPIT_V4_DB`, a variable **nothing in the backend reads** (the one
  that is read is `COCKPIT_V4_STATE_DATABASE`), so its advertised "different
  state database" silently shared the accepted instance's;
* it set neither `COCKPIT_V4_PRICE_CARD` nor `COCKPIT_AGENTIC_V4` nor
  `COCKPIT_V4_LOCAL_DEMO_AUTH`, so preflight failed and the app came up with
  `runtime=None`;
* it spawned the UI with no `FileNotFoundError` guard AFTER the API child
  existed, so a machine without npm was left with an orphan API process that
  `--stop` could not find.

So this does not reimplement a lifecycle. It hands over to
`scripts/cockpit_v4/start.py`, which already health-waits, writes `Owned` pid
records, steps over an occupied port without ever killing its holder, and
guards the UI child. This launcher's whole job is to choose the CANDIDATE
settings and pass them down.

WHAT IT PINS, AND WHY
---------------------
`--release` is the LEGACY compatibility release. It is deliberately the
accepted one: it is what `service.load_release` opens to build a healthy
`Runtime`, and a healthy runtime is what keeps preflight green. It is NOT the
book the browser reads -- the books come from `domains.current_release()`,
which follows the What-If flags to the candidate releases.

The accepted launchers under `scripts/cockpit_v4/` are not modified, and the
Round H launcher is not touched. This one takes its own ports and its own
runtime directory, so an accepted Cockpit can be running at the same time.

    .venv-whatif/bin/python scripts/whatif/start_h2_uat.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

#: Ten above the accepted defaults, as the candidate has always been.
API_PORT = 8424
UI_PORT = 5424

#: Its own runtime directory. This is what actually separates the state
#: database, because `config.load()` derives `COCKPIT_V4_STATE_DATABASE` from
#: it. H1 set `COCKPIT_V4_DB`, which is read by nothing.
RUNTIME_DIR = Path.home() / ".creditprobe" / "cockpit_v4_whatif_uat"

#: The compatibility release, kept accepted on purpose -- see the docstring.
COMPAT_RELEASE = "v4-saudi-20q-v1"

CREDENTIAL_VAR = "COCKPIT_ANTHROPIC_API_KEY"


def credential_present() -> bool:
    """Shell export only.

    Never a file, never a `.env`, never the Keychain from here: the value is
    read from the environment this launcher was started in, and it is never
    printed, logged or written anywhere.
    """
    return bool(os.environ.get(CREDENTIAL_VAR, "").strip())


def child_environment() -> dict[str, str]:
    """The candidate's settings, in THIS run's children and nowhere else."""
    env = dict(os.environ)
    env.update({
        # Both books, on, for this process tree only.
        "COCKPIT_V4_WHATIF_CORPORATE": "1",
        "COCKPIT_V4_WHATIF_RETAIL": "1",
        # The local UAT principal. Its tenant is resolved by the server from
        # the book it serves -- see `app.demo_tenant`.
        "COCKPIT_V4_LOCAL_DEMO_AUTH": "true",
        "COCKPIT_AGENTIC_V4": "true",
        "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4",
        "COCKPIT_V4_RUNTIME_DIR": str(RUNTIME_DIR),
        "COCKPIT_V4_RELEASE_ID": COMPAT_RELEASE,
        "PYTHONPATH": str(ROOT),
    })
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=API_PORT)
    parser.add_argument("--ui-port", type=int, default=UI_PORT)
    parser.add_argument("--any-revision", action="store_true",
                        help="run before the H2 candidate is frozen, and say "
                             "so in the output")
    parser.add_argument("--skip-preflight", action="store_true",
                        help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.skip_preflight:
        preflight = [sys.executable, str(ROOT / "scripts" / "whatif"
                                         / "uat_preflight.py")]
        if args.any_revision:
            preflight.append("--any-revision")
        if subprocess.run(preflight, cwd=str(ROOT)).returncode != 0:
            print("\nThe UAT was NOT started. Nothing was changed and no "
                  "port was taken.")
            return 1

    if not credential_present():
        print(f"\n  REFUSED  {CREDENTIAL_VAR} is not set in this shell, so "
              f"there is no live provider to drive.\n"
              f"  Export it in the shell you launch from -- never in a file "
              f"and never in a .env:\n"
              f"      export {CREDENTIAL_VAR}='...'\n"
              f"  Then run this again. The value is never printed or "
              f"written anywhere.")
        return 2

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    print("\nWhat-If UAT candidate")
    print("─" * 60)
    print(f"  runtime dir   {RUNTIME_DIR}")
    print(f"  compat release{COMPAT_RELEASE} (legacy; no thread reads it)")
    print("  books         Corporate and Retail, What-If ON")
    print(f"  credential    PRESENT ({CREDENTIAL_VAR})")
    print("─" * 60)

    # The established lifecycle: health wait, pid records, port stepping,
    # UI guard. Nothing about it is reimplemented here.
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "cockpit_v4" / "start.py"),
         "--api-port", str(args.api_port),
         "--ui-port", str(args.ui_port),
         "--runtime-dir", str(RUNTIME_DIR),
         "--release", COMPAT_RELEASE],
        cwd=str(ROOT), env=child_environment()).returncode


if __name__ == "__main__":
    raise SystemExit(main())
