"""
Start the model-comparison LAB: its own API and UI, its own ports, its own
state. Never touches the frozen launchers, the frozen runtime directory, any
shared daemon or anybody else's process.

    python scripts/model_lab/start.py                 # fixture chat, no key
    python scripts/model_lab/start.py --live-opus     # frozen Opus chat (key)

What it does, in order:
 1. verifies the protected manifest (refuses to start on a modified core);
 2. resolves and guards the lab runtime directory (no symlink/escape);
 3. picks free ports near 8424 (API) / 5424 (UI) -- never frees a port;
 4. starts `backend.model_lab.app:create_lab_app` and waits for /health;
 5. starts the Next.js dev server on the lab port with the lab flag;
 6. records owned PIDs under <lab runtime>/pids (stop.py reads them).

The frozen helpers in scripts/cockpit_v4/_common.py are imported read-only
for port picking and ownership checks.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cockpit_v4"))
sys.path.insert(0, str(ROOT))

import _common as cm  # noqa: E402  (frozen helper, read-only use)

DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Start the model lab")
    ap.add_argument("--api-port", type=int, default=8424)
    ap.add_argument("--ui-port", type=int, default=5424)
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    ap.add_argument("--live-opus", action="store_true",
                    help="serve the frozen single-model chat on the frozen "
                         "Opus provider (needs COCKPIT_ANTHROPIC_API_KEY)")
    ap.add_argument("--no-ui", action="store_true")
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args(argv)

    cm.heading("Model comparison lab")
    chk = subprocess.run([args.python, str(ROOT / "scripts" / "model_lab" /
                                           "protected_manifest.py"),
                          "--check"], capture_output=True, text=True)
    if chk.returncode != 0:
        print(cm.bad("protected manifest check FAILED; refusing to start"))
        print(chk.stdout[-2000:])
        return 2
    print(cm.ok(chk.stdout.strip()))

    runtime = Path(args.runtime_dir).expanduser().resolve()
    for bad in (ROOT / "data", ROOT / "backend", ROOT / "config",
                Path.home() / ".creditprobe" / "cockpit_v4"):
        if runtime == bad.resolve() or bad.resolve() in runtime.parents:
            print(cm.bad(f"refusing lab runtime inside {bad}"))
            return 2
    (runtime / "frozen").mkdir(parents=True, exist_ok=True)
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    for owned in cm.records(runtime):
        ours, why = cm.still_ours(owned)
        if ours:
            print(cm.warn(f"lab {owned.name} already running (pid "
                          f"{owned.pid}, {owned.url}); use stop.py first"))
            return 1

    api_port, notes = cm.pick_port(args.api_port)
    for n in notes:
        print(cm.warn(n))
    if not api_port:
        return 1
    ui_port, notes = cm.pick_port(args.ui_port) if not args.no_ui else (0, [])
    for n in notes:
        print(cm.warn(n))

    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(ROOT),
        "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4",
        "COCKPIT_AGENTIC_V4": "true",
        "COCKPIT_V4_RUNTIME_DIR": str(runtime / "frozen"),
        "COCKPIT_V4_STATE_DATABASE": str(runtime / "frozen" /
                                         "cockpit_v4.sqlite3"),
        "COCKPIT_V4_API_PORT": str(api_port),
        "COCKPIT_V4_UI_PORT": str(ui_port or 5424),
        "COCKPIT_V4_LOCAL_DEMO_AUTH": "true",
        "COCKPIT_V4_MEMORY_ENABLED": "false",
        "COCKPIT_V4_STARTUP_SHA": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "MODEL_LAB_RUNTIME_DIR": str(runtime),
    })
    if args.live_opus:
        env["AI_COCKPIT_REASONING_MODEL"] = "claude-opus-5"
        env["COCKPIT_V4_PRICE_CARD"] = str(
            ROOT / "config/cockpit_v4/price_card.claude-opus-5.json")
        env.pop("MODEL_LAB_FIXTURE_APP", None)
        if not env.get("COCKPIT_ANTHROPIC_API_KEY"):
            print(cm.warn("COCKPIT_ANTHROPIC_API_KEY is not set: the frozen "
                          "chat will report preflight-incomplete"))
    else:
        env["MODEL_LAB_FIXTURE_APP"] = "true"
        print(cm.warn("single-model chat runs on the REFERENCE FIXTURE (no "
                      "model); pass --live-opus for the frozen Opus chat"))

    log = open(runtime / "logs" / "api.log", "ab")
    cmd = [args.python, "-m", "uvicorn", "backend.model_lab.app:"
           "create_lab_app", "--factory", "--host", "127.0.0.1", "--port",
           str(api_port)]
    api = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=log,
                           start_new_session=True)
    api_url = f"http://127.0.0.1:{api_port}"
    cm.record(runtime, cm.Owned("api", api.pid, time.time(), " ".join(cmd),
                                str(ROOT), api_port, api_url))
    if not cm.wait_for_health(api_url + "/health", timeout_seconds=90):
        print(cm.bad(f"API did not become healthy; see {runtime}/logs"))
        return 1
    print(cm.ok(f"lab API  {api_url}  (lab routes /api/v1/model-lab)"))

    if not args.no_ui:
        uenv = dict(env)
        uenv.update({"NEXT_PUBLIC_COCKPIT_V4_API": api_url,
                     "NEXT_PUBLIC_API_URL": api_url,
                     "NEXT_PUBLIC_COCKPIT_V4_LAB": "true",
                     "PORT": str(ui_port)})
        ulog = open(runtime / "logs" / "ui.log", "ab")
        ucmd = ["npm", "run", "dev", "--", "--port", str(ui_port),
                "--hostname", "127.0.0.1"]
        ui = subprocess.Popen(ucmd, cwd=ROOT / "frontend", env=uenv,
                              stdout=ulog, stderr=ulog,
                              start_new_session=True)
        ui_url = f"http://127.0.0.1:{ui_port}/cockpit/lab"
        cm.record(runtime, cm.Owned("ui", ui.pid, time.time(),
                                    " ".join(ucmd), str(ROOT / "frontend"),
                                    ui_port, ui_url))
        ok = cm.wait_for_ui_ready(f"http://127.0.0.1:{ui_port}/cockpit/lab",
                                  timeout_seconds=180)
        print(cm.ok(f"lab UI   {ui_url}") if ok else
              cm.warn(f"UI not ready yet; see {runtime}/logs/ui.log"))
    print(f"state    {runtime}\nstop     python scripts/model_lab/stop.py "
          f"--runtime-dir {runtime}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
