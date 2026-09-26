#!/usr/bin/env python3
"""Rebuild every ML artifact and check it against what is published.

Section 12 of the authorization: no model binary is committed, and the
repository must carry enough configuration, seeds, versions and scripts to
REGENERATE every artifact -- then the rebuilt hashes and metrics must be
verified against the published ones.

This is that verification, and it is deliberately unforgiving. It rebuilds each
book into a temporary directory with `train_emulator.py`, then compares, field
by field:

* every component's artifact hash, as `blend.json` records it;
* the blend weights;
* every gate's measured value, threshold and verdict;
* the model version, the release it was trained against, the seeds, the
  library versions, and the three period splits.

A single difference is a failure with the two values printed. Nothing is
regenerated in place and no published file is touched: a mismatch means either
the artifacts were not produced by this code, or this code no longer produces
them, and both are things to be told about rather than smoothed over.

It also rebuilds the offline explanation document and compares it byte for
byte, because that document is part of the model's documentation and two builds
of one model must produce one file.

Measured on GENERATED books. Nothing here is bank output, an accounting figure,
or a bank-validated model.

Usage:
    .venv-whatif/bin/python scripts/whatif/verify_artifacts.py --domain all

Takes several minutes per book: it is a full refit, which is the point.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BOOKS = ("corporate", "retail")
PUBLISHED = ROOT / "artifacts" / "whatif"
CANDIDATE_PYTHON = ROOT / ".venv-whatif" / "bin" / "python"

#: The manifest fields a rebuild must reproduce exactly. Every one of them
#: changes a number a reader is shown, or says which data produced it.
EXACT = ("model_version", "release_id", "target", "denominator",
         "component_hashes", "weights", "seeds", "libraries",
         "train_periods", "validate_periods", "test_periods",
         "features", "categorical", "embargoed_periods")

#: Gate comparisons are floats, so they get a tolerance -- one that is far
#: tighter than any threshold, so a gate cannot flip inside it.
GATE_TOLERANCE = 1e-9


class Mismatch(Exception):
    """A rebuilt artifact differs from the published one."""


def rebuild(domain_id: str, out: Path) -> None:
    started = time.time()
    print(f"  refitting into {out} ...", flush=True)
    # EVERY OUTPUT PATH POINTS AT THE TEMPORARY DIRECTORY.
    #
    # The trainer also writes a model card and an evidence file, and their
    # defaults are inside `docs/whatif`. A verification run that overwrote the
    # published documentation would be changing the thing it claims to be
    # checking, so all three are redirected and nothing published is touched.
    done = subprocess.run(
        [str(CANDIDATE_PYTHON), "scripts/whatif/train_emulator.py",
         "--domain", domain_id,
         "--artifacts", str(out),
         "--docs", str(out / "docs"),
         "--evidence", str(out / "docs" / "emulators.json")],
        cwd=str(ROOT), capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stdout[-4000:])
        print(done.stderr[-4000:])
        raise Mismatch(f"the {domain_id} refit failed with "
                       f"{done.returncode}; nothing can be verified against a "
                       f"build that did not happen")
    print(f"  refit in {time.time() - started:.0f}s", flush=True)


def compare(domain_id: str, rebuilt: Path) -> list[str]:
    """Every difference, named. Not the first one -- all of them."""
    here = json.loads((PUBLISHED / domain_id / "blend.json")
                      .read_text(encoding="utf-8"))
    there = json.loads((rebuilt / domain_id / "blend.json")
                       .read_text(encoding="utf-8"))
    out: list[str] = []
    for field in EXACT:
        if here.get(field) != there.get(field):
            out.append(f"{field}: published {here.get(field)!r} but the "
                       f"rebuild produced {there.get(field)!r}")
    for name in sorted(set(here.get("gates", {})) | set(there.get("gates", {}))):
        was = (here.get("gates") or {}).get(name)
        now = (there.get("gates") or {}).get(name)
        if was is None or now is None:
            out.append(f"gate {name}: published {was!r}, rebuilt {now!r}")
            continue
        for key in ("threshold", "what", "passed"):
            if was.get(key) != now.get(key):
                out.append(f"gate {name}.{key}: published {was.get(key)!r}, "
                           f"rebuilt {now.get(key)!r}")
        if abs(float(was["measured"]) - float(now["measured"])) > GATE_TOLERANCE:
            out.append(f"gate {name}.measured: published {was['measured']!r}, "
                       f"rebuilt {now['measured']!r}")
    here_metric = (PUBLISHED / domain_id / "model_metric.json")
    there_metric = (rebuilt / domain_id / "model_metric.json")
    if here_metric.exists() and there_metric.exists():
        if (json.loads(here_metric.read_text("utf-8"))
                != json.loads(there_metric.read_text("utf-8"))):
            out.append("model_metric.json differs between the published "
                       "artifact and the rebuild")
    return out


def explanation(domain_id: str) -> list[str]:
    """The offline document, rebuilt in place and compared byte for byte.

    In place, because the document is derived from the PUBLISHED model rather
    than from a refit: what is being checked is that building it twice from one
    model gives one file.
    """
    path = PUBLISHED / domain_id / "explanation.json"
    if not path.exists():
        return [f"{path} has not been built; run "
                f"scripts/whatif/build_explanations.py"]
    before = path.read_bytes()
    done = subprocess.run(
        [str(CANDIDATE_PYTHON), "scripts/whatif/build_explanations.py",
         "--domain", domain_id],
        cwd=str(ROOT), capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stdout[-2000:])
        print(done.stderr[-2000:])
        return [f"the {domain_id} explanation build failed with "
                f"{done.returncode}"]
    if path.read_bytes() != before:
        path.write_bytes(before)
        return [f"{path.name} is not reproducible: a second build of the same "
                f"model produced different bytes"]
    return []


def verify(domain_id: str, *, refit: bool) -> list[str]:
    print(f"\n{domain_id}")
    problems: list[str] = []
    if refit:
        work = Path(tempfile.mkdtemp(prefix=f"whatif-verify-{domain_id}-"))
        try:
            rebuild(domain_id, work)
            problems += compare(domain_id, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    else:
        print("  --no-refit: the blend is not rebuilt, so the component "
              "hashes, weights and gates are NOT verified here")
    problems += explanation(domain_id)
    if problems:
        for line in problems:
            print(f"  DIFFERS  {line}")
    elif refit:
        print("  every published hash, weight, gate and metric was "
              "reproduced, and the explanation document rebuilt byte for byte")
    else:
        # WHAT WAS CHECKED, NOT WHAT THE SCRIPT IS FOR.
        #
        # Saying "verified" here would claim the refit that was skipped.
        print("  the explanation document rebuilt byte for byte. The blend "
              "itself was NOT verified in this run.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="all", choices=[*BOOKS, "all"])
    parser.add_argument("--no-refit", action="store_true",
                       help="skip the refit and check only the explanation "
                            "document. States in the output that the blend "
                            "was not verified.")
    args = parser.parse_args()
    if not CANDIDATE_PYTHON.exists():
        print(f"{CANDIDATE_PYTHON} is absent. Build the candidate environment "
              f"first.")
        return 1
    failed: list[str] = []
    for domain_id in (BOOKS if args.domain == "all" else (args.domain,)):
        failed += verify(domain_id, refit=not args.no_refit)
    print()
    if failed:
        print(f"{len(failed)} difference(s). The published artifacts were NOT "
              f"reproduced by this code, and nothing was regenerated to hide "
              f"that.")
        return 1
    print("verified." if not args.no_refit else
          "the explanation documents are reproducible. The blends were NOT "
          "rebuilt in this run, so their hashes, weights and gates are "
          "unverified here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
