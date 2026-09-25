#!/usr/bin/env python3
"""The protected-file manifest: write it once, check it forever.

Section 1.2 of the What-If specification asks for a SHA-256 manifest of the
protected files, published datasets and launchers before any candidate edit,
and for "architecture unchanged" to be supported by hashes rather than
asserted. A manifest nobody can re-run is an assertion with extra steps, so
this is the tool that produced it and the tool that verifies it.

    python scripts/whatif/protected_hashes.py --write    # capture
    python scripts/whatif/protected_hashes.py --check    # verify, exit 1 on drift

`--check` prints every file whose digest moved, every file that vanished and
every NEW file matching a protected pattern -- the last of those because a
capability that adds a module beside `orchestration.py` has changed the
protected surface just as surely as one that edits it.

An expected difference is not silenced here. It is recorded in
`docs/whatif/BASELINE_AND_EXTENSION_MAP.md` with its reason, and this tool
still reports it, so the count of justified changes stays visible instead of
disappearing into a allowlist nobody reads.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

#: The accepted baseline this manifest was captured at.
BASELINE = "245c50e45786c6e0c866b281f9dd74da17d160b5"

#: WHAT "PROTECTED" MEANS, in the words of section 1.2: the reasoning and
#: analysis loop, analyst model/provider selection, orchestration, query and
#: grain validation, repair behaviour, clarification behaviour, numerical
#: checks, source restrictions, general investigation prompts, existing
#: chart/interpretation behaviour, the tool-execution sandbox, and the
#: budget/efficiency settings -- plus the published books themselves.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("analyst loop, orchestration, validation, budgets", (
        "backend/cockpit_v4/*.py",
        "backend/cockpit_v4/contracts/*.json",
        "backend/cockpit_v4/prompts/*",
        "backend/cockpit_v4/generate/*.py",
    )),
    ("published data: manifests and parquet", (
        "data/cockpit_v4_lake/*/manifest.json",
        "data/cockpit_v4_lake/*/*.parquet",
    )),
    # The V3-namespace release the suite reads when
    # COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4. It is NOT one of the two
    # accepted books -- it is the older generator's output, reachable only
    # through the V3 store -- but the accepted runtime's tests depend on it,
    # so drift in it is drift in the baseline and belongs here.
    ("V3-namespace release read by the suite", (
        "data/cockpit_v4/*/manifest.json",
        "data/cockpit_v4/*/*.parquet",
    )),
    ("chart and answer rendering", (
        "frontend/src/components/cockpit-v4/*",
        "frontend/src/app/cockpit/**/*",
    )),
    ("dependency and tooling locks", (
        "pyproject.toml",
        "requirements.txt",
    )),
)

MANIFEST = "docs/whatif/PROTECTED_FILES.sha256"

#: The candidate's own package lives under `backend/cockpit_v4/` for import
#: reasons, so the first glob would otherwise sweep it in and every new file
#: would read as protected-core drift. It is a directory, and the glob is
#: `*.py` at one level, so this exclusion is belt and braces -- but a manifest
#: that silently grew to cover the thing it is meant to police would be worse
#: than no manifest.
EXCLUDE_PREFIXES = ("backend/cockpit_v4/scenario/",)


def digest(path: pathlib.Path) -> str:
    """SHA-256, streamed, because the parquet files are tens of megabytes."""
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def collect(root: pathlib.Path) -> dict[str, list[tuple[str, str]]]:
    """Every protected file today, grouped, sorted, with its digest."""
    out: dict[str, list[tuple[str, str]]] = {}
    for title, globs in GROUPS:
        found: set[pathlib.Path] = set()
        for pattern in globs:
            found |= {p for p in root.glob(pattern) if p.is_file()}
        rows = []
        for path in sorted(found):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(EXCLUDE_PREFIXES):
                continue
            rows.append((digest(path), rel))
        out[title] = rows
    return out


def render(groups: dict[str, list[tuple[str, str]]]) -> str:
    total = sum(len(rows) for rows in groups.values())
    lines = [
        "# Protected files at the accepted baseline",
        "",
        f"Commit `{BASELINE}`, branch",
        "`claude/cockpit-single-agent-v4-h8fsbq`, captured before any candidate edit.",
        "",
        f"{total} files.",
        "",
        "Regenerate and compare with `scripts/whatif/protected_hashes.py --check`.",
        "A difference here is a protected-core change and must be justified in",
        "`BASELINE_AND_EXTENSION_MAP.md` or it is a defect.",
        "",
    ]
    for title, rows in groups.items():
        lines += [f"## {title} ({len(rows)} files)", ""]
        lines += [f"{sha}  {rel}" for sha, rel in rows]
        lines.append("")
    return "\n".join(lines) + "\n"


def stored(root: pathlib.Path) -> dict[str, str]:
    """The manifest as a path -> digest map, ignoring its prose."""
    text = (root / MANIFEST).read_text()
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split("  ", 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            try:
                int(parts[0], 16)
            except ValueError:
                continue
            out[parts[1].strip()] = parts[0]
    return out


def check(root: pathlib.Path) -> int:
    was = stored(root)
    now = {rel: sha for rows in collect(root).values() for sha, rel in rows}

    changed = sorted(p for p in was.keys() & now.keys() if was[p] != now[p])
    removed = sorted(was.keys() - now.keys())
    added = sorted(now.keys() - was.keys())

    for path in changed:
        print(f"CHANGED  {path}")
    for path in removed:
        print(f"REMOVED  {path}")
    for path in added:
        print(f"ADDED    {path}")

    if not (changed or removed or added):
        print(f"PROTECTED CORE UNCHANGED against {BASELINE[:12]} "
              f"({len(now)} files)")
        return 0
    print(f"\n{len(changed)} changed, {len(removed)} removed, {len(added)} added "
          f"against {BASELINE[:12]}.")
    print("Every one must be justified in docs/whatif/"
          "BASELINE_AND_EXTENSION_MAP.md.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="capture the manifest")
    parser.add_argument("--check", action="store_true",
                        help="verify against the captured manifest")
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve()
                                              .parents[2]))
    args = parser.parse_args()
    root = pathlib.Path(args.root)

    if args.write == args.check:
        parser.error("choose exactly one of --write and --check")
    if args.write:
        (root / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
        (root / MANIFEST).write_text(render(collect(root)))
        print(f"wrote {MANIFEST}")
        return 0
    return check(root)


if __name__ == "__main__":
    sys.exit(main())
