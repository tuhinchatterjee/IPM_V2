"""Lab status: owned processes, model readiness, approvals. Read-only.

    python scripts/model_lab/status.py [--runtime-dir DIR]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "cockpit_v4"))
sys.path.insert(0, str(ROOT))

import _common as cm  # noqa: E402

DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    args = ap.parse_args(argv)
    runtime = Path(args.runtime_dir).expanduser().resolve()
    cm.heading("Model lab status")
    recs = cm.records(runtime) if runtime.exists() else []
    for o in recs:
        ours, why = cm.still_ours(o)
        print(f"  {o.name:4} pid {o.pid:<7} {o.url:40} "
              f"{'running' if ours else why}")
    if not recs:
        print("  no lab process recorded")
    from backend.model_lab import registry
    approvals = registry.load_approvals(runtime)
    probes_path = runtime / "probes.json"
    import json
    probes = json.loads(probes_path.read_text()) if probes_path.exists() \
        else {}
    print("\n  model readiness:")
    for pid, p in registry.load_profiles().items():
        r = registry.readiness(p, approvals=approvals, probes=probes)
        print(f"    {pid:24} {r.status:22} {r.reasons[0][:70]}")
    print(f"\n  approvals: {sorted(approvals) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
