#!/usr/bin/env python3
"""What this machine is, and what the retail demo on it is publishing.

    python3 scripts/retail_cockpit/mac_preflight.py
    python3 scripts/retail_cockpit/mac_preflight.py --benchmark-json <file>

READ-ONLY, and deliberately narrow. It measures memory, finds the running
retail demo, reads its git identity and the identity block of its published
Cockpit Data, and prints them. It opens nothing for writing, starts nothing,
stops nothing and changes nothing.

It prints no secrets. It never dumps the environment, and it reads process
NAMES rather than command lines, because an argument list is a place a key
can end up and this file is meant to be pasteable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

#: Where the retail installation listens. The API first: its working
#: directory is what tells us which worktree is actually running.
RETAIL_API_PORT = 8328
RETAIL_UI_PORT = 5328

MIB = 1024 * 1024


def _run(command: list[str]) -> str:
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


# ---- 1. the machine ----------------------------------------------------

def physical_ram_bytes() -> int:
    mac = _run(["sysctl", "-n", "hw.memsize"])
    if mac.isdigit():
        return int(mac)
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def available_bytes() -> tuple[int, str]:
    """Free memory, and how honestly it can be said.

    macOS does not publish an "available" figure the way Linux does. What it
    publishes is a page census, and free + inactive + speculative is the
    conventional reading of it -- conventional, not authoritative, and
    labelled as such rather than presented as a measurement.
    """
    census = _run(["vm_stat"])
    if census:
        page = _run(["sysctl", "-n", "hw.pagesize"])
        size = int(page) if page.isdigit() else 4096
        pages = {}
        for line in census.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            digits = value.strip().rstrip(".")
            if digits.isdigit():
                pages[key.strip().lower()] = int(digits)
        total = sum(pages.get(k, 0) for k in
                    ("pages free", "pages inactive", "pages speculative"))
        return total * size, "vm_stat: free + inactive + speculative (an estimate)"
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024, "/proc/meminfo MemAvailable"
    except OSError:
        pass
    return 0, "not reliably measurable on this machine"


# ---- 2. what is running ------------------------------------------------

def listeners(port: int) -> list[int]:
    out = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
    return [int(x) for x in out.split() if x.isdigit()]


def process_rss_mib(pid: int) -> float:
    out = _run(["ps", "-o", "rss=", "-p", str(pid)])
    return round(int(out) / 1024, 1) if out.strip().isdigit() else 0.0


def process_name(pid: int) -> str:
    """The executable, never the argument list: an argument can hold a key."""
    return _run(["ps", "-o", "comm=", "-p", str(pid)]).split("/")[-1] or "?"


def process_cwd(pid: int) -> str:
    out = _run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    try:  # Linux fallback, so this file can be tested off a Mac
        return str(Path(f"/proc/{pid}/cwd").resolve())
    except OSError:
        return ""


# ---- 3. the demo's git identity ----------------------------------------

def git_identity(worktree: Path) -> dict:
    def git(*args: str) -> str:
        return _run(["git", "-C", str(worktree), *args])

    dirty = git("status", "--porcelain")
    return {
        "worktree": str(worktree),
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_files": len([x for x in dirty.splitlines() if x.strip()]),
        "worktrees": [line.split()[0] for line in
                      git("worktree", "list").splitlines() if line.strip()],
    }


# ---- 4. what Cockpit Data says it is -----------------------------------

def cockpit_data_identity(worktree: Path, metadata_dir: Path | None) -> dict:
    metadata = metadata_dir or (worktree / "metadata" / "retail")
    manifest_path = metadata / "retail_dataset_manifest.json"
    contract_path = metadata / "retail_data_contract.json"
    catalog_path = metadata / "catalog.json"
    if not manifest_path.exists():
        return {"error": f"no manifest at {manifest_path}"}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    months = manifest.get("months") or []
    out = {
        "metadata_dir": str(metadata),
        "dataset_name": manifest.get("dataset_name"),
        "dataset_version": manifest.get("dataset_version"),
        "generator_version": manifest.get("generator_version"),
        "seed": manifest.get("seed"),
        "manifest_hash": manifest.get("manifest_hash"),
        "months": len(months),
        "first_snapshot": manifest.get("first_snapshot"),
        "last_snapshot": manifest.get("last_snapshot"),
        "total_rows": manifest.get("total_rows"),
        "distinct_customers_all_months":
            manifest.get("distinct_customers_all_months"),
        "distinct_facilities_all_months":
            manifest.get("distinct_facilities_all_months"),
        "column_count": manifest.get("column_count"),
        "currency": manifest.get("currency"),
        "validation_status": sorted({str(m.get("validation_status"))
                                     for m in months}),
        "content_hash_first": (months[0].get("content_hash") if months
                               else None),
        "content_hash_last": (months[-1].get("content_hash") if months
                              else None),
    }
    if contract_path.exists():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        out["schema_version"] = contract.get("schema_version")
        out["grain"] = contract.get("grain")
        out["primary_key"] = contract.get("primary_key")
        out["display_name"] = contract.get("display_name")
    if catalog_path.exists():
        catalogue = json.loads(catalog_path.read_text(encoding="utf-8"))
        entries = catalogue.get("datasets") or []
        if entries:
            out["domain"] = entries[0].get("domain")
            out["owner"] = entries[0].get("owner")
            out["version_in_catalogue"] = entries[0].get("version")
            out["is_synthetic"] = entries[0].get("is_synthetic")
            out["portfolio_scope"] = entries[0].get("portfolio_scope")
    return out


# ---- 5. printing -------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo-root", type=Path, default=None,
                    help="the running retail worktree, when it cannot be "
                         "derived from the listening process")
    ap.add_argument("--metadata-dir", type=Path, default=None)
    ap.add_argument("--api-port", type=int, default=RETAIL_API_PORT)
    ap.add_argument("--ui-port", type=int, default=RETAIL_UI_PORT)
    ap.add_argument("--benchmark-json", type=Path, default=None,
                    help="a finished session benchmark, summarised at the end")
    args = ap.parse_args()

    print("=" * 74)
    print("MACHINE")
    print("=" * 74)
    ram = physical_ram_bytes()
    free, how = available_bytes()
    print(f"  physical RAM          {ram / MIB:10,.0f} MiB"
          f"  ({ram / MIB / 1024:.1f} GiB)")
    print(f"  available             {free / MIB:10,.0f} MiB   [{how}]")
    print(f"  cpus                  {_run(['sysctl', '-n', 'hw.ncpu']) or '?'}")
    print(f"  python                {'.'.join(str(n) for n in sys.version_info[:3])}")

    print()
    print("=" * 74)
    print("WHAT IS RUNNING (names only; no command lines, no environment)")
    print("=" * 74)
    demo_root = args.demo_root
    for label, port in (("retail API", args.api_port),
                        ("retail frontend", args.ui_port)):
        pids = listeners(port)
        if not pids:
            print(f"  {label:18s} port {port}: nothing listening")
            continue
        for pid in pids:
            print(f"  {label:18s} port {port}  pid {pid:>7}  "
                  f"{process_name(pid):16s} RSS {process_rss_mib(pid):9,.1f} MiB")
            if demo_root is None and port == args.api_port:
                cwd = process_cwd(pid)
                if cwd:
                    demo_root = Path(cwd)

    print()
    print("=" * 74)
    print("THE RUNNING RETAIL DEMO (read-only)")
    print("=" * 74)
    if demo_root is None:
        print("  Could not derive the worktree from a listening process.")
        print("  Pass --demo-root <path> and run again.")
        return 1
    identity = git_identity(demo_root)
    print(f"  worktree              {identity['worktree']}")
    print(f"  branch                {identity['branch']}")
    print(f"  HEAD                  {identity['head']}")
    print(f"  uncommitted files     {identity['dirty_files']}")
    for line in identity["worktrees"]:
        print(f"  git worktree          {line}")

    print()
    print("=" * 74)
    print("COCKPIT DATA, AS THE DEMO PUBLISHES IT (read-only)")
    print("=" * 74)
    for key, value in cockpit_data_identity(demo_root,
                                            args.metadata_dir).items():
        print(f"  {key:32s} {value}")

    if args.benchmark_json and args.benchmark_json.exists():
        print()
        print("=" * 74)
        print("SESSION BENCHMARK ON THIS MACHINE")
        print("=" * 74)
        payload = json.loads(args.benchmark_json.read_text(encoding="utf-8"))
        print(f"  {'limit':>8}  {'cold open':>10}  {'materialised':>12}  "
              f"{'spill':>10}  {'peak RSS':>10}  {'simple':>9}  "
              f"{'diagnostic':>11}  concurrent")
        for run in payload.get("runs", []):
            concurrent = run.get("concurrent_two_questions", {})
            errors = [v.get("error") for v in concurrent.values()
                      if isinstance(v, dict) and v.get("error")]
            verdict = ("both answered"
                       if not errors else f"ERROR: {errors[0][:40]}")
            print(f"  {run['limit']:>8}  {run['cold_open_ms'] / 1000:9.1f}s  "
                  f"{run['materialised_mib']:11,.0f}M  "
                  f"{run['spill_bytes_materialising'] / MIB:9,.0f}M  "
                  f"{run['peak_rss_mib']:9,.0f}M  "
                  f"{run['simple_aggregation']['median_ms']:8.1f}ms  "
                  f"{run['multi_relation_diagnostic']['median_ms']:10.1f}ms  "
                  f"{verdict}")
        print()
        print("  'peak RSS' IS the candidate engine's resident size for that "
              "run: the benchmark measures its own process.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
