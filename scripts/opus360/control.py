#!/usr/bin/env python3
"""
Operator control for the Opus360 overnight certification.

    python3 scripts/opus360/control.py prepare   # venv, releases, fixture validation
    python3 scripts/opus360/control.py start     # live, in the background, overnight
    python3 scripts/opus360/control.py status
    python3 scripts/opus360/control.py stop      # graceful: finishes the current turn
    python3 scripts/opus360/control.py resume

STOP never picks a process by port or by name. It acts only on the PID recorded
in the experiment's owner.json, and only while that PID's start time, command
line and working directory all still match the record.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts" / "opus360"
VENV_PY = ROOT / ".venv" / "bin" / "python"
RELEASES = ("v4-saudi-corporate-20q-v4", "v4-saudi-retail-20m-v5")
LEGACY = "v4-saudi-20q-v1"
RUN_ARGS = ["scripts/opus360/run_certification.py", "--suite", "architecture-v1", "--live", "--sequential",
            "--resume", "--run-calibration", "--run-core", "--run-load-test", "--export"]


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def run(cmd: list[str], **kw) -> int:
    return subprocess.run(cmd, cwd=ROOT, **kw).returncode


# ---- prepare --------------------------------------------------------------------------

def ensure_venv() -> None:
    if VENV_PY.exists():
        return
    py = shutil.which("python3.12") or shutil.which("python3")
    say(f"creating .venv with {py}")
    if run([py, "-m", "venv", ".venv"]) != 0:
        sys.exit("could not create .venv")
    run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    if run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", "requirements.txt", "pyyaml", "pytest"]) != 0:
        sys.exit("dependency installation failed")


def ensure_releases() -> None:
    lake = ROOT / "data" / "cockpit_v4_lake"
    legacy = ROOT / "data" / "cockpit_v4" / LEGACY
    source = os.environ.get("OPUS360_LAKE_SOURCE", "").strip()
    if source:
        src = Path(source).expanduser()
        for rel in RELEASES:
            if not (lake / rel).exists() and (src / "cockpit_v4_lake" / rel).exists():
                say(f"copying approved release {rel} from {src} (read-only source)")
                shutil.copytree(src / "cockpit_v4_lake" / rel, lake / rel)
        if not legacy.exists() and (src / "cockpit_v4" / LEGACY).exists():
            say(f"copying {LEGACY} from {src}")
            shutil.copytree(src / "cockpit_v4" / LEGACY, legacy)
    if not all((lake / r / "manifest.json").exists() for r in RELEASES):
        say("seeding the two governed domain releases (deterministic; ~2 minutes)")
        run([str(VENV_PY), "scripts/cockpit_v4/seed_domains.py"])
    if not legacy.exists():
        say(f"seeding the runtime's pinned release {LEGACY} (no evidence rewrite)")
        run([str(VENV_PY), "scripts/cockpit_v4/seed_release.py", "--release", LEGACY, "--no-evidence"])


def ensure_fixtures() -> bool:
    sys.path.insert(0, str(ROOT / "scripts" / "opus360"))
    from run_fixture_validation import OUT, harness_tree_sha

    path = OUT / "fixture_validation.json"
    if path.exists():
        fx = json.loads(path.read_text())
        import platform

        if (fx.get("ok") and fx.get("harness_tree_sha256") == harness_tree_sha()
                and fx.get("platform_system") == platform.system()
                and fx.get("python") == platform.python_version()):
            say(f"fixture validation current: {fx['passed']}/{fx['tests']} passed")
            return True
    say("running fixture validation (no paid call)")
    return run([str(VENV_PY), "scripts/opus360/run_fixture_validation.py"]) == 0


def prepare() -> int:
    print("Opus360 prepare")
    ensure_venv()
    ensure_releases()
    ok = ensure_fixtures()
    if run([str(VENV_PY), "scripts/opus360/run_certification.py", "--dry-run", "--preflight-only"],
           stdout=subprocess.DEVNULL) != 0:
        say("preflight FAILED; run: .venv/bin/python scripts/opus360/run_certification.py --dry-run --preflight-only")
        return 1
    say("preflight PASS")
    return 0 if ok else 1


# ---- ownership --------------------------------------------------------------------------

def latest_experiment(mode: str = "live") -> Path | None:
    cands = sorted(p for p in ART.glob(f"architecture-v1-{mode}-*") if (p / "manifest.json").exists())
    return cands[-1] if cands else None


sys.path.insert(0, str(ROOT / "scripts" / "opus360"))
from cert.procinfo import cwd as _cwd  # noqa: E402
from cert.procinfo import ps_field as _ps  # noqa: E402
from cert.procinfo import start_time as _start_time  # noqa: E402


def owned(exp: Path) -> dict | None:
    """The owner record, only if that PID is still the process we started."""
    rec_path = exp / "owner.json"
    if not rec_path.exists():
        return None
    rec = json.loads(rec_path.read_text())
    pid = int(rec.get("pid") or 0)
    if pid <= 0 or not _ps(pid, "pid"):
        return None
    started = _start_time(pid)
    if started is None or abs(started - float(rec["started_at"])) > 5.0:
        return None
    if "run_certification.py" not in _ps(pid, "command"):
        return None
    if os.path.realpath(_cwd(pid) or "") != os.path.realpath(rec.get("cwd", "")):
        return None
    return rec


# ---- start / resume / status / stop ----------------------------------------------------------

def start(resume: bool) -> int:
    print("Opus360 " + ("resume" if resume else "start"))
    if prepare() != 0:
        return 1
    cap = os.environ.get("OPUS360_MAX_USD", "").strip()
    if not cap:
        print("\n  BLOCKED: OPUS360_MAX_USD is not set. No paid call has been made.\n"
              "  Set a hard spend cap in USD and run this again, for example:\n"
              "      export OPUS360_MAX_USD=150\n"
              "      export OPUS360_MAX_HOURS=10      # optional wall-clock cap\n"
              "      launchers/START_OPUS360_OVERNIGHT.command\n")
        return 2
    exp = latest_experiment("live")
    if exp is not None and owned(exp):
        say(f"already running: {exp.name} (pid {owned(exp)['pid']}). Use STATUS or STOP.")
        return 1
    # The key: environment, then the macOS Keychain, then a hidden prompt -- the
    # frozen launcher's own function. It is passed to the child in its environment
    # only, never on a command line and never to disk.
    sys.path.insert(0, str(ROOT / "scripts" / "opus360"))
    import run_certification as rc

    key, source = rc.obtain_credential(allow_prompt=sys.stdin.isatty())
    if not key:
        print("  BLOCKED: COCKPIT_ANTHROPIC_API_KEY is not available (environment, Keychain "
              "'creditprobe-cockpit-v4', or prompt).")
        return 2
    say(f"credential from {source}")
    env = dict(os.environ, COCKPIT_ANTHROPIC_API_KEY=key, PYTHONUNBUFFERED="1")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log = ART / f"launcher-{stamp}.log"
    ART.mkdir(parents=True, exist_ok=True)
    cmd = [str(VENV_PY), *RUN_ARGS]
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        cmd = ["caffeinate", "-i", "-s", *cmd]      # keep the Mac awake while it runs
    with open(log, "w") as fh:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    say(f"started pid {proc.pid}; log {log.relative_to(ROOT)}")
    say("progress: launchers/STATUS_OPUS360.command   stop: launchers/STOP_OPUS360.command")
    return 0


def status() -> int:
    for mode in ("live", "dry"):
        exp = latest_experiment(mode)
        if exp is None:
            continue
        state = json.loads((exp / "state.json").read_text()) if (exp / "state.json").exists() else {}
        rec = owned(exp)
        print(f"\n{exp.name}  [{'RUNNING pid ' + str(rec['pid']) if rec else 'not running'}]")
        print(f"  turns completed (all phases): {state.get('turns_completed', 0)}")
        print(f"  cumulative spend: ${float(state.get('cumulative_usd') or 0):.4f}")
        for phase in ("calibration", "core"):
            s = state.get(f"phase_{phase}")
            if s:
                print(f"  {phase}: {s.get('completed')}/{s.get('planned')} completed, {s.get('passed')} passed, "
                      f"stopped: {(s.get('stopped') or {}).get('condition', 'no')}")
        log = exp / "run.log"
        if log.exists():
            print("  last lines:")
            for line in log.read_text().splitlines()[-6:]:
                print("   ", line)
    return 0


def stop() -> int:
    exp = latest_experiment("live") or latest_experiment("dry")
    if exp is None:
        print("  no experiment found")
        return 0
    rec = owned(exp)
    if rec is None:
        print(f"  {exp.name}: no running certification process owned by this experiment; nothing stopped")
        return 0
    pid = int(rec["pid"])
    (exp / "STOP").write_text(datetime.now(UTC).isoformat())
    print(f"  asked pid {pid} to stop after the current turn (STOP file written)")
    for _ in range(120):
        if owned(exp) is None:
            print("  stopped cleanly; resume with launchers/RESUME_OPUS360.command")
            return 0
        time.sleep(5)
    if owned(exp) is not None:
        print(f"  still running after 10 minutes; sending SIGTERM to verified pid {pid}")
        os.kill(pid, signal.SIGTERM)
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd in ("prepare", "start", "resume"):
        ensure_venv()
        # Everything after this point runs in the project's own interpreter
        # (Python >= 3.12, pinned dependencies), never the system python3.
        if os.path.realpath(sys.executable) != os.path.realpath(str(VENV_PY)):
            os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])
    if cmd == "prepare":
        return prepare()
    if cmd == "start":
        return start(resume=False)
    if cmd == "resume":
        return start(resume=True)
    if cmd == "status":
        return status()
    if cmd == "stop":
        return stop()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
