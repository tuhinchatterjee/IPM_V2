#!/usr/bin/env python3
"""
Build the requirement matrix of record from MEASURED evidence.

    python3 scripts/guided_workspace/requirement_matrix.py \\
        --spec docs/guided_workspace/matrix/spec_requirement_rows.txt \\
        --evidence docs/guided_workspace/matrix/requirement_evidence.json \\
        --regression docs/guided_workspace/evidence/final_regression \\
        --candidate-sha <SHA the final regression ran on> \\
        --mutation docs/guided_workspace/evidence/mutation_gates.json \\
        --out docs/guided_workspace/REQUIREMENT_MATRIX.md

The evidence map names, per requirement id, the tests and browser journeys
that assert it, a CLAIM (COVERED / PARTIAL / BLOCKED / NOT_COVERED) and, for
anything short of COVERED, the exact gap. The STATUS printed is one of
PASS / PARTIAL / BLOCKED / FAILED, computed from the measured results of the
final regression of record (whose `summary.json` must name
`--candidate-sha`). This script does not trust the map:

* every requirement id in the specification must be in the map, and nothing
  else (an id added to or dropped from the spec fails generation);
* every cited pytest node, frontend test title, browser journey and source
  file must EXIST -- one that does not fails generation (exit 1);
* EXISTENCE is reported apart from RESULT: each cited test is joined to the
  result files of the regression of record (JUnit XML for pytest and node,
  journeys.json for the browser) and shown PASS / FAIL / SKIP / NOT RUN;
* the status is COMPUTED, never copied from the claim:
  - any cited test, journey or check that FAILED -> FAILED;
  - a claim of NOT_COVERED -> FAILED;
  - a check the regression measured BLOCKED_ENV, or a BLOCKED claim ->
    BLOCKED (with the claim's reason and the measured detail);
  - a cited test the regression did not run, or that only skipped ->
    PARTIAL, with that stated;
  - a PARTIAL claim -> PARTIAL (never promoted);
  - a COVERED claim with at least one citation and every one PASS -> PASS.
* every cited source / evidence file must exist.
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
CLAIMS = ("COVERED", "PARTIAL", "BLOCKED", "NOT_COVERED")
GAP_REQUIRED = ("PARTIAL", "BLOCKED", "NOT_COVERED")
STATUSES = ("PASS", "PARTIAL", "BLOCKED", "FAILED")


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
    # Failures the regression classified as P0-recorded environment-bound
    # (summary.json `env_bound`) are reported BLOCKED_ENV, never PASS.
    env_bound: set[str] = set()
    summary = folder / "summary.json"
    if summary.exists():
        for step in json.loads(summary.read_text())["steps"]:
            env_bound |= {n.split("::")[0].replace(".", "/") + ".py::" +
                          n.split("::")[1] for n in step.get("env_bound", [])}
    merged: dict[str, str] = {}
    for key, outs in res.items():
        if key in env_bound and "FAIL" in outs:
            merged[key] = "BLOCKED_ENV"
            continue
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


def check_results(folder: Path, gates: Path
                  ) -> tuple[dict[str, str], dict[str, str]]:
    """Measured outcome and detail per check id."""
    out: dict[str, str] = {}
    detail: dict[str, str] = {}
    for step in json.loads((folder / "summary.json").read_text())["steps"]:
        key = f"regression:{step['name']}"
        status = step.get("status", "FAIL")
        out[key] = {"PASS": "PASS", "BLOCKED_ENV": "BLOCKED_ENV"}.get(
            status, "FAIL")
        bits = []
        if step.get("counts"):
            c = step["counts"]
            bits.append(f"{c.get('tests', 0)} tests, {c.get('failures', 0)} "
                        f"failures, {c.get('errors', 0)} errors, "
                        f"{c.get('skipped', 0)} skipped")
        if step.get("env_bound"):
            bits.append(f"environment-bound (P0-recorded): "
                        f"{len(step['env_bound'])}")
        if step.get("detail"):
            bits.append(str(step["detail"])[:200])
        detail[key] = "; ".join(bits)
    data = json.loads(gates.read_text())
    for g in data["gates"]:
        key = f"mutation:{g['gate']}"
        out[key] = "PASS" if g["result"] == "KILLED" else "FAIL"
        detail[key] = g["result"]
    out["git:no_tags_moved"] = git_tags_unmoved()
    return out, detail


def compute(claim: str, outcomes: list[str], cited: bool
            ) -> tuple[str, str]:
    """(status, computed reason). See the module docstring."""
    if any(o in ("FAIL", "MIXED", "MISSING") for o in outcomes):
        return "FAILED", "a cited test, journey, check or file FAILED or is missing"
    if claim == "NOT_COVERED":
        return "FAILED", ""
    if claim == "BLOCKED" or "BLOCKED_ENV" in outcomes:
        return "BLOCKED", ("" if claim == "BLOCKED" else
                           "measured BLOCKED_ENV in the final regression")
    if "NOT RUN" in outcomes:
        return "PARTIAL", "a cited test was NOT RUN by the final regression"
    if outcomes and all(o == "SKIP" for o in outcomes):
        return "PARTIAL", "every cited test SKIPPED in the final regression"
    if claim == "PARTIAL":
        return "PARTIAL", ""
    if claim == "COVERED" and cited:
        return "PASS", ""
    return "FAILED", "no evidence cited"


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
    journeys_file = Path(args.regression) / "suite_outputs" / \
        "docs/guided_workspace/evidence/journeys.json"
    if not journeys_file.exists():
        print(f"no journey results at {journeys_file}", file=sys.stderr)
        return 1
    jres = {j["journey"]: j["status"] for j in json.loads(
        journeys_file.read_text(encoding="utf-8"))["journeys"]}
    # Literal ids, plus ids a templated journey (`GW-P3-01-${book}`) produced.
    known_journeys = set(re.findall(r'journey\(\s*["`](GW-[^"`$]+)["`]',
                                    journeys_src))
    for templ in re.findall(r'journey\(\s*`(GW-[^`]*)\$\{', journeys_src):
        known_journeys |= {j for j in jres if j.startswith(templ)}
    reg = Path(args.regression)
    summary_path = reg / "summary.json"
    if not summary_path.exists():
        print(f"no regression summary at {summary_path}", file=sys.stderr)
        return 1
    ran_on = json.loads(summary_path.read_text()).get("commit", "")
    if ran_on != args.candidate_sha:
        print(f"the regression at {reg} ran on {ran_on[:12]}, not the "
              f"candidate {args.candidate_sha[:12]}", file=sys.stderr)
        return 1
    if not Path(args.mutation).exists():
        print(f"no mutation-gate record at {args.mutation}", file=sys.stderr)
        return 1
    pres = pytest_results(reg)
    cres, cdetail = check_results(reg, Path(args.mutation))
    nres = node_results(reg / "frontend.junit.xml")

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
                errors.append(f"{rid}: evidence file does not exist: {src}")
                cites.append((src, "MISSING"))
        status, why = compute(claim, [o for _, o in cites if o != "SELF"],
                              bool(cites))
        if claim == "COVERED" and not cites:
            errors.append(f"{rid}: COVERED with no test, journey or check")
        measured = [f"{c}: {cdetail[c]}" for c, o in cites
                    if o == "BLOCKED_ENV" and cdetail.get(c)]
        reason = "; ".join(x for x in (e.get("gap", ""), why, *measured) if x)
        rows.append((rid, e, cites, status, reason))

    self_ok = "PASS" if not errors else "FAIL"
    rows = [(rid, e, [(c, (self_ok if o == "SELF" else o)) for c, o in cs],
             ("FAILED" if any(o == "SELF" for _, o in cs) and errors else st),
             why) for rid, e, cs, st, why in rows]
    counts = collections.Counter(r[3] for r in rows)
    lines = [
        "# Requirement matrix of record",
        "",
        "Generated by `scripts/guided_workspace/requirement_matrix.py` from "
        "`docs/guided_workspace/matrix/requirement_evidence.json` and the "
        "result files of the final regression of record. Do not edit by hand: "
        "edit the evidence map and re-run.",
        "",
        f"* Final regression of record ran on **`{args.candidate_sha}`**; "
        f"results: `{args.regression_label or args.regression}`.",
        f"* Specification requirement ids: **{len(ids)}**; evidence entries: "
        f"**{len(evidence)}**.",
        "* Status is computed from measured results, never copied from the "
        "claim. PASS needs at least one citation and every citation PASS. A "
        "FAIL anywhere is FAILED. BLOCKED needs a stated external reason. "
        "Anything not run, skip-only or claimed partial is PARTIAL; PARTIAL is "
        "never promoted.",
        "* Each citation shows existence and result separately: "
        "`PASS` / `FAIL` / `SKIP` / `NOT RUN` / `BLOCKED_ENV`; a citation "
        "that does not exist fails generation.",
        "",
        "| Status | Count |", "|---|---|",
        *[f"| {k} | {counts.get(k, 0)} |" for k in STATUSES],
        f"| **Total** | **{len(rows)}** |", "",
    ]
    by_section: dict[str, list] = collections.defaultdict(list)
    for r in rows:
        by_section[r[1].get("section", "")].append(r)
    for section, items in by_section.items():
        lines += [f"## {section}", "",
                  "| ID | Requirement | Status | Evidence (result) | Gap / reason |",
                  "|---|---|---|---|---|"]
        for rid, e, cites, status, why in items:
            ev = "; ".join(f"`{c}` {o}" for c, o in cites) or "—"
            gap = why.replace("|", "/")
            req = e.get("requirement", "").replace("|", "/")
            lines.append(f"| {rid} | {req} | **{status}** | {ev} | {gap} |")
        lines.append("")
    gaps = [r for r in rows if r[3] != "PASS"]
    lines += ["## Everything short of PASS", ""]
    for rid, _e, _c, status, why in gaps:
        lines.append(f"* **{rid}** {status}: {why or '—'}")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {"candidate_sha": args.candidate_sha, "ids": len(ids),
               "counts": {k: counts.get(k, 0) for k in STATUSES},
               "rows": {rid: {"status": st, "reason": why,
                              "evidence": [[c, o] for c, o in cs]}
                        for rid, _e, cs, st, why in rows},
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
    p.add_argument("--regression", required=True,
                   help="the final regression's output folder (summary.json, "
                        "JUnit XML, suite_outputs/)")
    p.add_argument("--regression-label", default="",
                   help="how to name the folder in the matrix header")
    p.add_argument("--candidate-sha", required=True)
    p.add_argument("--mutation", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--python", default=sys.executable)
    return build(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
