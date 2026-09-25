"""
Read-only host preflight for the lab. Runs nothing, installs nothing.

    python scripts/model_lab/preflight.py
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _cmd(*a: str) -> str:
    try:
        return subprocess.run(list(a), capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    from backend.model_lab.resources import host_facts

    facts = host_facts()
    if platform.system() == "Darwin":
        facts["chip"] = _cmd("sysctl", "-n", "machdep.cpu.brand_string")
        mem = _cmd("sysctl", "-n", "hw.memsize")
        facts["memory_total_mb"] = int(mem) / 2**20 if mem else None
        facts["macos"] = _cmd("sw_vers", "-productVersion")
    du = shutil.disk_usage(ROOT)
    facts["disk_free_gb"] = round(du.free / 1e9, 1)
    facts["python"] = sys.version.split()[0]
    facts["node"] = _cmd("node", "--version")
    facts["ollama_binary"] = shutil.which("ollama")
    facts["vllm_binary"] = shutil.which("vllm")
    facts["credentials_present"] = {
        v: bool(os.environ.get(v)) for v in ("COCKPIT_ANTHROPIC_API_KEY",
                                             "LAB_REMOTE_API_KEY")}
    facts["git_head"] = _cmd("git", "-C", str(ROOT), "rev-parse", "HEAD")
    facts["git_dirty"] = bool(_cmd("git", "-C", str(ROOT), "status",
                                   "--porcelain", "--untracked-files=no"))
    print(json.dumps(facts, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
