"""
Grant or revoke a lab approval. An OPERATOR action, on the lab server's own
disk; nothing a browser, a model or a question can do.

    python scripts/model_lab/approve.py grant opus_spend --cap-usd 5
    python scripts/model_lab/approve.py grant remote_inference --cap-usd 10 \
        --note "RunPod endpoint X, synthetic data only"
    python scripts/model_lab/approve.py revoke opus_spend
    python scripts/model_lab/approve.py list

Approval keys: opus_spend (paid Opus calls, capped per comparison group),
remote_inference (approved remote endpoints; Compare never provisions GPUs),
deep_diagnostics (bounded controlled replays), license:<profile-id> (the
operator has reviewed a model licence that pin_and_probe_models.py marked
LICENSE_REVIEW_REQUIRED). Model downloads and runtime
installation are NOT approvals here: they are done by the user, outside the
lab, and then proven by probe.py.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"
KEYS = ("opus_spend", "remote_inference", "deep_diagnostics")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("grant", "revoke", "list"))
    ap.add_argument("key", nargs="?")
    ap.add_argument("--cap-usd", type=float)
    ap.add_argument("--note", default="")
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    args = ap.parse_args(argv)
    runtime = Path(args.runtime_dir).expanduser().resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    path = runtime / "approvals.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    if args.action == "list":
        print(json.dumps(data, indent=1))
        return 0
    if not args.key:
        ap.error("a key is required")
    if args.key not in KEYS and not (args.key.startswith("license:") and
                                     len(args.key) > len("license:")):
        ap.error(f"unknown key {args.key}; use one of {KEYS} or "
                 f"license:<profile-id>")
    if args.action == "grant":
        if args.key in ("opus_spend", "remote_inference") and \
                not args.cap_usd:
            ap.error("a paid approval needs --cap-usd")
        data[args.key] = {"granted_at": time.time(),
                          "granted_by": getpass.getuser(),
                          "cap_usd": args.cap_usd, "note": args.note}
    else:
        data.pop(args.key, None)
    path.write_text(json.dumps(data, indent=1))
    try:
        os.chmod(path, 0o600)
    except OSError:   # e.g. the RunPod Global Volume (fuse.geesefs)
        print(f"note: {path.parent} does not support chmod; the file keeps "
              f"the volume's default permissions")
    print(f"{args.action}ed {args.key} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
