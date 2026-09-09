#!/usr/bin/env python
"""Run the multi-analysis corpus through the real Ask path and score it.

    python scripts/evaluate_multi_analysis.py                 # all 50
    python scripts/evaluate_multi_analysis.py --family crossing
    python scripts/evaluate_multi_analysis.py --json out.json

Every case goes through `answer_investigation`, which is the function the Ask
endpoint calls. Nothing is stubbed and no expected figure is checked — the
corpus is about the CONTRACT: did the question get answered at all, did the
response carry the number of blocks the question warrants, are the block kinds
the ones the shape of the answer implies, and did anything the case marks as
padding turn up.

Scored per case on four independent checks so a partial pass is legible:

    ANSWERED    it answered rather than clarifying, refusing or failing
    BLOCKS      the package carries between the case's min and max analyses
    KINDS       every kind the case names appears somewhere in the package
    CLEAN       no prohibited concept appears in the answer's own words

A case can be ANSWERED and fail BLOCKS, which is exactly the failure this
corpus exists to catch: a review that ran five analyses and rendered one.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORPUS = ROOT / "tests" / "evals" / "multi_analysis_cases.json"

CHECKS = ("ANSWERED", "BLOCKS", "KINDS", "CLEAN")

#: How a prohibited concept would show up in an answer's own words. Only the
#: unambiguous surface forms: this check exists to catch an answer that went
#: and computed something nobody asked for, and a false positive on the word
#: "stage" inside "at this stage" would make the whole score untrustworthy.
_CONCEPT_WORDS: dict[str, tuple[str, ...]] = {
    "ecl": ("expected credit loss",),
    "ead": ("exposure at default",),
    "stage": ("ifrs 9 stage", "stage 1", "stage 2", "stage 3"),
    "rating": ("internal rating", "rating grade", "downgrade"),
    "dpd": ("days past due",),
    "sector": ("by sector",),
    "pd": ("probability of default",),
    "lgd": ("loss given default",),
    "ecl_coverage": ("ecl coverage",),
    "limit": ("limit utilisation",),
}


def load() -> list[dict]:
    return json.loads(CORPUS.read_text())["cases"]


def _package(investigation) -> dict:
    try:
        return investigation.to_dict().get("package") or {}
    except Exception:  # noqa: BLE001
        return {}


def _words(investigation) -> str:
    narrative = getattr(investigation, "narrative", None)
    parts = [str(getattr(narrative, "direct_answer", "") or ""),
             str(getattr(narrative, "summary", "") or ""),
             str(getattr(narrative, "interpretation", "") or "")]
    return " ".join(parts).lower()


def run_one(case: dict) -> dict:
    """One case, through the path a person's question takes."""
    from backend.orchestration.executor import answer_investigation

    started = time.perf_counter()
    outcome: dict = {"id": case["id"], "family": case["family"],
                     "question": case["question"], "checks": {},
                     "notes": []}
    try:
        investigation, _ = answer_investigation(case["question"], persist=False)
    except Exception as e:  # noqa: BLE001 - a raise is a result, not a crash
        outcome["checks"] = dict.fromkeys(CHECKS, False)
        outcome["status"] = "raised"
        outcome["notes"].append(f"raised: {e}")
        outcome["ms"] = int((time.perf_counter() - started) * 1000)
        return outcome

    status = str(getattr(investigation, "status", ""))
    outcome["status"] = status
    package = _package(investigation)
    counts = package.get("counts") or {}
    analyses = int(counts.get("analyses") or 0)
    kinds = {k for block in (package.get("blocks") or [])
             for k in (block.get("kinds") or [])}
    outcome["analyses"] = analyses
    outcome["kinds"] = sorted(kinds)
    outcome["drawn"] = int(counts.get("drawn") or 0)

    # A clarification is the right answer to a genuinely ambiguous question,
    # and only to one: the case has to say so, and say why, before this check
    # will accept it.
    may_ask = bool(case.get("clarification_is_correct"))
    outcome["checks"]["ANSWERED"] = (
        status == "succeeded"
        or (may_ask and status == "needs_clarification"))
    if may_ask and status == "needs_clarification":
        outcome["notes"].append("asked, which this case expects")

    low, high = case["expected_blocks"]
    outcome["checks"]["BLOCKS"] = low <= analyses <= high
    if not outcome["checks"]["BLOCKS"]:
        outcome["notes"].append(f"{analyses} analyses, expected {low}-{high}")

    wanted = set(case["expected_kinds"])
    outcome["checks"]["KINDS"] = wanted <= kinds
    if not outcome["checks"]["KINDS"]:
        outcome["notes"].append(f"missing kinds {sorted(wanted - kinds)}")

    said = _words(investigation)
    intruders = [c for c in case["prohibited_concepts"]
                 if any(w in said for w in _CONCEPT_WORDS.get(c, ()))]
    outcome["checks"]["CLEAN"] = not intruders
    if intruders:
        outcome["notes"].append(f"unasked-for concepts named: {intruders}")

    outcome["ms"] = int((time.perf_counter() - started) * 1000)
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", default="", help="Only this family.")
    parser.add_argument("--case", type=int, default=0, help="Only this id.")
    parser.add_argument("--json", default="", help="Write the results here.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)

    cases = load()
    if args.family:
        cases = [c for c in cases if c["family"] == args.family]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if not cases:
        print("No cases matched.")
        return 2

    print("MULTI-ANALYSIS RESPONSE CORPUS")
    print("=" * 78, flush=True)
    results = []
    for case in cases:
        outcome = run_one(case)
        results.append(outcome)
        if not args.quiet:
            marks = "".join("." if outcome["checks"].get(c) else "X"
                            for c in CHECKS)
            print(f"{marks}  {outcome['id']:>2}  {outcome['family']:<24}"
                  f"{outcome['analyses']:>3} blk  {outcome['ms']:>5}ms  "
                  f"{outcome['question'][:44]}", flush=True)
            for note in outcome["notes"]:
                print(f"      · {note}", flush=True)

    print("=" * 78)
    print(f"{'check':<12}{'passed':>8}{'of':>5}")
    summary = {}
    for check in CHECKS:
        passed = sum(1 for r in results if r["checks"].get(check))
        summary[check] = passed
        print(f"{check:<12}{passed:>8}{len(results):>5}")
    whole = sum(1 for r in results if all(r["checks"].values()))
    print("-" * 78)
    print(f"ALL FOUR CHECKS: {whole} of {len(results)}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(
            {"summary": summary, "total": len(results), "clean": whole,
             "results": results}, indent=2))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
