"""
Probe a candidate profile against an ALREADY-RUNNING runtime. Installs and
downloads nothing. Dummy tool only; no CreditProbe data.

    python scripts/model_lab/probe.py --profile qwen3.5-9b
    python scripts/model_lab/probe.py --profile qwen3.5-9b \
        --base-url http://127.0.0.1:11434/v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"


def main(argv: list[str] | None = None) -> int:
    from backend.model_lab import probe, registry

    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--base-url")
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    args = ap.parse_args(argv)
    profiles = registry.load_profiles()
    prof = profiles.get(args.profile)
    if prof is None or prof.route not in ("openai_compat", "ollama_native"):
        print(f"{args.profile}: not a probe-able candidate route")
        return 2
    ep = prof.raw.get("endpoint") or {}
    base = args.base_url or os.environ.get(ep.get("base_url_env") or "") \
        or ep.get("base_url_default")
    key = os.environ.get(ep.get("api_key_env") or "") if ep.get(
        "api_key_env") else None
    res = probe.probe_profile(prof, base_url=base, api_key=key)
    path = probe.save(Path(args.runtime_dir).expanduser().resolve(), res)
    print(json.dumps({k: res.get(k) for k in (
        "profile_id", "runtime_reachable", "model_present",
        "resolved_model", "controls", "error")}, indent=1))
    r = registry.readiness(prof, approvals={}, probes={prof.profile_id: res})
    print(f"readiness: {r.status} - {r.reasons[0]}")
    print(f"saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
