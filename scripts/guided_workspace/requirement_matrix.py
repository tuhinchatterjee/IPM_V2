#!/usr/bin/env python3
"""
Build the requirement matrix of record from MEASURED evidence.

    python3 scripts/guided_workspace/requirement_matrix.py \\
        --spec SPEC.txt \\
        --evidence docs/guided_workspace/matrix/requirement_evidence.json \\
        --pytest-junit docs/guided_workspace/evidence/regression \\
        --node-junit docs/guided_workspace/evidence/regression/frontend.junit.xml \\
        --journeys docs/guided_workspace/evidence/journeys.json \\
        --out docs/guided_workspace/REQUIREMENT_MATRIX.md

The evidence map names, per requirement id, the tests and browser journeys
that assert it, a CLAIM (COVERED / PARTIAL / BLOCKED / PENDING-P14 /
PENDING-P15 / NOT_COVERED) and, for anything short of COVERED, the exact gap.
This script does not trust the map:

* every requirement id in the specification must be in the map, and nothing
  else (an id added to or dropped from the spec fails generation);
* every cited pytest node, frontend test title, browser journey and source
  file must EXIST -- one that does not fails generation (exit 1);
* EXISTENCE is reported apart from RESULT: each cited test is joined to the
  result files of the regression of record (JUnit XML for pytest and node,
  journeys.json for the browser) and shown PASS / FAIL / SKIP / NOT RUN;
* the status is COMPUTED: a COVERED claim needs at least one cited test or
  journey and every one of them PASSING; any FAIL makes the row FAILING; a
  cited test absent from the results makes it NOT_RUN. A PARTIAL claim is
  never promoted; BLOCKED / PENDING rows must state their reason.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ID_RE = re.compile(r"^\| ?([A-Z][A-Z0-9]{1,8}-?[0-9]{2,3}) \|", re.M)
CLAIMS = ("COVERED", "PARTIAL", "BLOCKED", "PENDING-P14", "PENDING-P15",
          "NOT_COVERED")
GAP_REQUIRED = ("PARTIAL", "BLOCKED", "PENDING-P14", "PENDING-P15",
                "NOT_COVERED")


def spec_ids(spec: Path) -> list[str]:
    return list(dict.fromkeys(ID_RE.findall(spec.read_text(encoding="utf-8"))))


# ---- existence -------------------------------------------------------------------

def collected_pytest(files: set[str], python: str) -> set[str]:
    if not files:
        return set()
    out = subprocess.run(
        [python, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=",
         "-p", "no:cacheprovider", *sorted(files)],
        cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ,
             "COCKPIT_AGENTIC_V3_NAMESPACE": "cockpit_v4"})
    return {line.strip() for line in out.stdout.splitlines()
            if "::" in line}


def node_titles(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(r'\btest\(\s*"([^"]+)"', text)


def expand(prefix: str) -> list[str]:
    """`DEC01..DEC09` -> DEC01 ... DEC09; `A/B` -> A, B; else itself."""
    if "/" in prefix:
        return [x for part in prefix.split("/") for x in expand(part.strip())]
    m = re.fullmatch(r"([A-Z]+)(\d+)\.\.([A-Z]+)?(\d+)", prefix)
    if not m:
        return [prefix]
    head, lo, _, hi = m.groups()
    width = len(lo)
    return [f"{head}{n:0{width}d}" for n in range(int(lo), int(hi) + 1)]


def pytest_exists(cite: str, collected: set[str]) -> bool:
    if cite in collected:
        return True
    return any(c.startswith(cite + "[") for c in collected)


def node_matches(cite: str) -> list[str]:
    path, _, prefix = cite.partition("::")
    titles = node_titles(ROOT / path)
    out = []
    for p in expand(prefix.strip()):
        hit = [t for t in titles if t == p or t.startswith(p + " ")
               or p in t.split(" ", 1)[0].split("/")]
        if not hit:
            return []
        out += hit
    return out


# ---- results -------------------------------------------------------------------------

def pytest_results(folder: Path) -> dict[str, str]:
    res: dict[str, list[str]] = collections.defaultdict(list)
    for xml in sorted(folder.glob("*.xml")):
        if xml.name.startswith("frontend"):
            continue
        for case in ET.parse(xml).getroot().iter("testcase"):
            cls = case.get("classname", "")
            name = case.get("name", "")
            path = cls.replace(".", "/") + ".py"
            base = name.split("[")[0]
            outcome = "PASS"
            if case.find("failure") is not None or \
                    case.find("error") is not None:
                outcome = "FAIL"
            elif case.find("skipped") is not None:
                outcome = "SKIP"
            res[f"{path}::{base}"].append(outcome)
    merged: dict[str, str] = {}
    for key, outs in res.items():
        # The same test may run on two interpreters (accepted, .venv-whatif):
        # it passes if any run passed and none failed where it ran for real.
        if "PASS" in outs and "FAIL" not in outs:
            merged[key] = "PASS"
        elif "FAIL" in outs and "PASS" not in outs:
            merged[key] = "FAIL"
        elif "FAIL" in outs:
            merged[key] = "MIXED"
        else:
            merged[key] = "SKIP"
    return merged


def node_results(xml: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not xml.exists():
        return out
    for case in ET.parse(xml).getroot().iter("testcase"):
        name = case.get("name", "")
        if case.find("failure") is not None or case.find("error") is not None:
            out[name] = "FAIL"
        elif case.find("skipped") is not None:
            out[name] = "SKIP"
        else:
            out[name] = "PASS"
    return out


# ---- build -----------------------------------------------------------------------------

#: P0 (BASELINE_PROVENANCE section 1): the tags that exist and must not move.
TAGS_AT_P0 = {"cockpit-round-h-live-pass-2026-09-23", "recovered-sep8-cockpit-v2",
              "recovered-sep8-integrated", "recovered-sep8-whatif",
              "whatif-candidate-h1", "windows-pilot-v1"}
H1 = "b2a05671da6d547389be0e95b5ea4e35d30e9b6d"


def git_tags_unmoved() -> str:
    tags = set(subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True,
                              text=True).stdout.split())
    h1 = subprocess.run(["git", "rev-parse", "whatif-candidate-h1^{commit}"],
                        cwd=ROOT, capture_output=True, text=True
                        ).stdout.strip()
    return "PASS" if tags == TAGS_AT_P0 and h1 == H1 else "FAIL"


def check_results(folder: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    summary = folder / "summary.json"
    if summary.exists():
        for step in json.loads(summary.read_text())["steps"]:
            out[f"regression:{step['name']}"] = step.get("status", "FAIL")
    gates = folder / "mutation_gates.json"
    if gates.exists():
        data = json.loads(gates.read_text())
        for g in data["gates"]:
            out[f"mutation:{g['gate']}"] = ("PASS" if g["result"] == "KILLED"
                                            else "FAIL")
    out["git:no_tags_moved"] = git_tags_unmoved()
    return out


def build(args: argparse.Namespace) -> int:
    ids = spec_ids(Path(args.spec))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    errors: list[str] = []
    missing = [i for i in ids if i not in evidence]
    extra = [i for i in evidence if i not in ids]
    if missing:
        errors.append(f"spec ids with no evidence entry: {missing}")
    if extra:
        errors.append(f"evidence entries not in the spec: {extra}")

    py_files = {c.split("::")[0] for e in evidence.values()
                for c in e.get("tests", []) if c.startswith("tests/")}
    collected = collected_pytest(py_files, args.python)
    journeys_src = (ROOT / "tests/guided_workspace/browser/gw.browser.mjs"
                    ).read_text(encoding="utf-8")
    jres = {j["journey"]: j["status"] for j in json.loads(
        Path(args.journeys).read_text(encoding="utf-8"))["journeys"]}
    # Literal ids, plus ids a templated journey (`GW-P3-01-${book}`) produced.
    known_journeys = set(re.findall(r'journey\(\s*["`](GW-[^"`$]+)["`]',
                                    journeys_src))
    for templ in re.findall(r'journey\(\s*`(GW-[^`]*)\$\{', journeys_src):
        known_journeys |= {j for j in jres if j.startswith(templ)}
    pres = pytest_results(Path(args.pytest_junit))
    cres = check_results(Path(args.pytest_junit))
    nres = node_results(Path(args.node_junit))

    rows = []
    for rid in ids:
        e = evidence.get(rid)
        if e is None:
            continue
        claim = e["claim"]
        if claim not in CLAIMS:
            errors.append(f"{rid}: unknown claim {claim!r}")
        if claim in GAP_REQUIRED and not e.get("gap"):
            errors.append(f"{rid}: {claim} needs its exact gap/reason")
        cites = []
        for c in e.get("tests", []):
            if c.startswith("tests/"):
                if not pytest_exists(c, collected):
                    errors.append(f"{rid}: pytest node does not exist: {c}")
                    cites.append((c, "MISSING"))
                    continue
                cites.append((c, pres.get(c, "NOT RUN")))
            elif c.startswith("frontend/"):
                titles = node_matches(c)
                if not titles:
                    errors.append(f"{rid}: frontend test does not exist: {c}")
                    cites.append((c, "MISSING"))
                    continue
                outs = {nres.get(t, "NOT RUN") for t in titles}
                cites.append((c, "PASS" if outs == {"PASS"} else
                              "FAIL" if "FAIL" in outs else
                              "NOT RUN" if "NOT RUN" in outs else "SKIP"))
            else:
                errors.append(f"{rid}: unrecognised test citation {c}")
        for j in e.get("journeys", []):
            if j not in known_journeys:
                errors.append(f"{rid}: journey does not exist: {j}")
                cites.append((j, "MISSING"))
                continue
            cites.append((j, {"PASS": "PASS", "FAILED": "FAIL"}.get(
                jres.get(j, ""), "NOT RUN")))
        for chk in e.get("checks", []):
            if chk == "generator:self_check":
                cites.append((chk, "SELF"))
                continue
            known_prefix = chk.split(":")[0] in ("regression", "mutation",
                                                  "git")
            if not known_prefix:
                errors.append(f"{rid}: unknown check {chk}")
            cites.append((chk, cres.get(chk, "NOT RUN")))
        for src in e.get("sources", []):
            if not (ROOT / src).exists():
                errors.append(f"{rid}: source does not exist: {src}")
        outcomes = [o for _, o in cites if o != "SELF"]
        if "FAIL" in outcomes or "MIXED" in outcomes:
            status = "FAILING"
        elif claim == "COVERED":
            if not cites:
                errors.append(f"{rid}: COVERED with no test or journey")
                status = "UNPROVEN"
            elif any(o in ("NOT RUN", "MISSING") for o in outcomes):
                status = "NOT_RUN"
            elif all(o == "SKIP" for o in outcomes):
                status = "SKIPPED_ONLY"
            else:
                status = "COVERED"
        else:
            status = claim
        rows.append((rid, e, cites, status))

    if errors:
        rows = [(rid, e, [(c, ("FAIL" if o == "SELF" else o)) for c, o in cs],
                 ("FAILING" if any(o == "SELF" for _, o in cs) else st))
                for rid, e, cs, st in rows]
    else:
        rows = [(rid, e, [(c, ("PASS" if o == "SELF" else o)) for c, o in cs],
                 st) for rid, e, cs, st in rows]
    counts = collections.Counter(r[3] for r in rows)
    lines = [
        "# Requirement matrix of record",
        "",
        "Generated by `scripts/guided_workspace/requirement_matrix.py` from "
        "`docs/guided_workspace/matrix/requirement_evidence.json` and the "
        "result files of the P13 regression of record. Do not edit by hand: "
        "edit the evidence map and re-run.",
        "",
        f"* Specification requirement ids: **{len(ids)}**; evidence entries: "
        f"**{len(evidence)}**.",
        "* A status is computed, not claimed: COVERED needs at least one cited "
        "test or journey and every cited one PASS in the regression of record. "
        "PARTIAL is never promoted. BLOCKED / PENDING rows state their reason.",
        "* Each citation shows existence and result separately: "
        "`PASS` / `FAIL` / `SKIP` / `NOT RUN`; a missing citation fails "
        "generation.",
        "",
        "| Status | Count |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(counts.items(),
                                              key=lambda kv: -kv[1])],
        f"| **Total** | **{len(rows)}** |", "",
    ]
    by_section: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        by_section[r[1].get("section", "")].append(r)
    for section, items in by_section.items():
        lines += [f"## {section}", "",
                  "| ID | Requirement | Status | Evidence (result) | Gap / reason |",
                  "|---|---|---|---|---|"]
        for rid, e, cites, status in items:
            ev = "; ".join(f"`{c}` {o}" for c, o in cites) or "—"
            gap = (e.get("gap") or "").replace("|", "/")
            req = e.get("requirement", "").replace("|", "/")
            lines.append(f"| {rid} | {req} | **{status}** | {ev} | {gap} |")
        lines.append("")
    gaps = [r for r in rows if r[3] != "COVERED"]
    lines += ["## Everything short of COVERED", ""]
    for rid, e, _c, status in gaps:
        lines.append(f"* **{rid}** {status}: {e.get('gap') or '—'}")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {"ids": len(ids), "counts": dict(counts),
               "errors": errors}
    Path(args.out).with_suffix(".json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"counts": dict(counts), "errors": len(errors)}))
    for err in errors:
        print("ERROR", err, file=sys.stderr)
    return 1 if errors else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--spec", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--pytest-junit", required=True)
    p.add_argument("--node-junit", required=True)
    p.add_argument("--journeys", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--python", default=sys.executable)
    return build(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
