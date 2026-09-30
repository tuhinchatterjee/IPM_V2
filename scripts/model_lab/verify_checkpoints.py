"""
Verify and pin exact checkpoints for the RunPod profiles. Metadata only:
this reads the Hugging Face model API; it downloads no weights and calls no
model.

    python scripts/model_lab/verify_checkpoints.py              # report
    python scripts/model_lab/verify_checkpoints.py --profile qwen3.5-4b-runpod
    python scripts/model_lab/verify_checkpoints.py \\
        --pin qwen3.5-4b-runpod=Qwen/Qwen3.5-4B@<commit-sha>

Report mode lists, per profile, the repository's current commit (for a known
repository) or search candidates (for a DISCOVERED profile). It never picks
one. `--pin` is the operator's explicit decision: it records the repository
and the exact revision in the profile, and only then can readiness proceed
to the probe.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "profiles"
API = "https://huggingface.co/api/models"


def _get(url: str) -> object:
    with urllib.request.urlopen(url, timeout=20) as r:     # noqa: S310
        return json.loads(r.read().decode())


def report(pid: str, raw: dict) -> None:
    art = raw.get("artifact") or {}
    repo = art.get("repository")
    try:
        if repo:
            info = _get(f"{API}/{urllib.parse.quote(repo, safe='/')}")
            print(f"{pid}: {repo} exists; current commit {info.get('sha')} "
                  f"(last modified {info.get('lastModified')}); pinned "
                  f"revision: {art.get('revision') or 'NONE'}")
        else:
            term = art.get("search_term") or raw["display_name"]
            hits = _get(f"{API}?search={urllib.parse.quote(term)}&limit=10")
            print(f"{pid}: NOT VERIFIED; candidates for '{term}' (choose "
                  f"one explicitly with --pin, or leave DISCOVERED):")
            for h in hits:
                print(f"    {h['id']}  downloads={h.get('downloads')}")
    except Exception as exc:  # noqa: BLE001 - report, never guess
        print(f"{pid}: lookup failed ({type(exc).__name__}: {exc}); "
              f"nothing changed")


def pin(spec: str) -> int:
    pid, _, target = spec.partition("=")
    repo, _, rev = target.partition("@")
    if not (pid and repo and len(rev) >= 7):
        print("--pin needs PROFILE=OWNER/REPO@REVISION (a commit sha)")
        return 2
    path = PROFILES / f"{pid}.json"
    raw = json.loads(path.read_text())
    info = _get(f"{API}/{urllib.parse.quote(repo, safe='/')}/revision/"
                f"{urllib.parse.quote(rev)}")
    if not info.get("sha", "").startswith(rev):
        print(f"refusing: {repo}@{rev} is not a revision of that repository")
        return 2
    raw["registry_id"] = repo
    raw["endpoint"]["model"] = repo
    raw["runpod"]["served_model_name"] = repo
    raw["artifact"].update({"repository": repo, "revision": info["sha"],
                            "search_term": None})
    raw["identity_source"] = (f"operator-pinned {date.today().isoformat()} "
                              f"via verify_checkpoints.py")
    if raw["status"] == "DISCOVERED":
        raw["status"] = "NOT_INSTALLED"
    path.write_text(json.dumps(raw, indent=1, ensure_ascii=False) + "\n")
    print(f"{pid}: pinned {repo}@{info['sha']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--profile", action="append")
    ap.add_argument("--pin")
    args = ap.parse_args(argv)
    if args.pin:
        return pin(args.pin)
    for path in sorted(PROFILES.glob("*-runpod.json")):
        raw = json.loads(path.read_text())
        if args.profile and raw["profile_id"] not in args.profile:
            continue
        report(raw["profile_id"], raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
