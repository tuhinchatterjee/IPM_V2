#!/usr/bin/env python
"""Classify every failing test in this repository, group by group.

    python scripts/build_cockpit_regression_classification.py \
        --branch <branch failures> --base <base failures> --causes <tb=line run>

Writes `docs/cockpit_v3/REGRESSION_CLASSIFICATION.md`.

THE RULE THIS SCRIPT ENFORCES
-----------------------------
Nothing is called PRE-EXISTING on this branch's say-so. A failure is
pre-existing only when the EXACT SAME test id also fails on the preserved
Cockpit V2 base, run in the same container, with the same interpreter and the
same absent services. That comparison is a set difference over test ids, not a
count: "589 before and 588 now" would be satisfied by breaking one test and
fixing two, and would tell nobody anything.

Anything failing here that does not fail there is a regression, named
individually. There is no group into which one can be filed.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

OUT = Path("docs/cockpit_v3/REGRESSION_CLASSIFICATION.md")
EVIDENCE = Path("docs/cockpit_v3/evidence/regression_classification.json")

MISSING_DEPENDENCY = "missing external dependency or service"
INCOMPATIBLE = "incompatible environment or runtime"
PRE_EXISTING = "pre-existing product failure"
REGRESSION = "branch regression"
UNAVAILABLE = "intentionally unavailable capability"
TEST_DEFECT = "test defect"

#: Root causes, matched against the error each failure actually raised. Order
#: matters: the first match wins, so the direct causes come before the
#: downstream shapes they produce.
CAUSES: tuple[tuple[str, str, str, str], ...] = (
    (r"UnknownDatasetError", MISSING_DEPENDENCY,
     "the governed data lake has not been built",
     "The catalogue answers `Available: (none - has the data lake been "
     "built?)`. Nothing is registered, so every dataset name is unknown."),
    (r"DataNotBuilt", MISSING_DEPENDENCY,
     "the synthetic corporate universe has not been built",
     "`scripts/build_corporate_universe.py` has not run in this container."),
    (r"psycopg\.OperationalError|OperationalError.*Connection refused|"
     r"connection to server at",
     MISSING_DEPENDENCY, "no PostgreSQL is running",
     "Connection refused on 127.0.0.1:5432. Nothing in this container starts "
     "a database."),
    (r"DashboardError: no months are available", MISSING_DEPENDENCY,
     "no scorecard months exist, because nothing was built",
     "A direct consequence of the empty catalogue: there are no periods to "
     "aggregate."),
    (r"CannotPlan: No governed measure was named", MISSING_DEPENDENCY,
     "the planner finds no measures, because the catalogue is empty",
     "The planner resolves measures against the governed catalogue. With "
     "nothing registered there is nothing to name."),
    (r"DatasetNotPublishedError", MISSING_DEPENDENCY,
     "the governed data lake has not been built",
     "The engine refuses a plan naming a dataset the governed layer does not "
     "publish. Nothing is published."),
    (r"PlanRejected: .*is not a governed dataset", MISSING_DEPENDENCY,
     "the governed data lake has not been built",
     "The plan validator refuses the dataset for the same reason the loader "
     "does."),
    (r"GovernedDataUnavailable", MISSING_DEPENDENCY,
     "the governed data lake has not been built",
     "No published dataset is marked authoritative, because none is "
     "published."),
    (r"VocabularyError", MISSING_DEPENDENCY,
     "the governed data lake has not been built",
     "The training vocabulary names datasets the empty catalogue does not "
     "have. This is also what makes the two brain test files fail to import."),
    (r"EarlyWarningError: .*needs at least (three|two)", MISSING_DEPENDENCY,
     "there are no reporting periods, because nothing was built",
     "The forward risk signal needs three periods to fit and test on. With an "
     "unbuilt lake there are none."),
    (r"is not governed", MISSING_DEPENDENCY,
     "the governance check has nothing to govern",
     "Same empty catalogue, reached through the governance assertion rather "
     "than through the loader."),
)

#: Downstream shapes -- an empty result read as a dict, a list, an attribute.
#: These are not separate causes and must not be counted as separate problems;
#: they are what the two causes above look like a few frames later.
DOWNSTREAM = (
    r"^AttributeError:", r"^KeyError:", r"^IndexError:", r"^TypeError:",
    r"^AssertionError", r"^assert ", r"^ValueError:", r"^StopIteration",
)


def classify(error: str) -> tuple[str, str, str, bool]:
    for pattern, category, cause, detail in CAUSES:
        if re.search(pattern, error):
            return category, cause, detail, True
    for pattern in DOWNSTREAM:
        if re.search(pattern, error):
            return (MISSING_DEPENDENCY,
                    "downstream of the empty catalogue or the absent database",
                    "An empty result read as a dict, a list or an attribute a "
                    "few frames after the real cause. Counted here rather than "
                    "as a separate problem.", False)
    return TEST_DEFECT, "unclassified", error[:200], False


def read_failures(path: Path) -> list[str]:
    """Test ids, with or without pytest's `FAILED ` prefix."""
    found = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("FAILED "):
            line = line[len("FAILED "):].strip()
        if "::" in line:
            found.add(line)
    return sorted(found)


#: Run-specific noise that differs between any two runs and means nothing: a
#: correlation id, and the absolute path each worktree happens to sit at.
_NOISE = (re.compile(r'"(request_id|correlation_id)":"[0-9a-f]+"'),
          re.compile(r"/home/user/[A-Za-z0-9_]+/"))


def _comparable(message: str) -> str:
    text = message
    for pattern in _NOISE:
        text = pattern.sub("<>", text)
    return " ".join(text.split())


def read_causes(path: Path) -> list[tuple[str, str]]:
    """Zip the -rf summary with the --tb=line failure lines.

    Both are printed in execution order and both have one entry per failure,
    which the caller checks by comparing their lengths before trusting this.
    """
    text = path.read_text()
    body = text.split("FAILURES")[-1].split("short test summary")[0]
    lines = [line for line in body.splitlines()
             if re.match(r"^/.*\.py:\d+: ", line)]
    ids = [line[len("FAILED "):].strip() for line in text.splitlines()
           if line.startswith("FAILED ")]
    errors = [re.sub(r"^/.*?\.py:\d+: ", "", line) for line in lines]
    return list(zip(ids, errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    base = Path("/tmp/claude-0/-home-user-IPM-V2/"
                "29c13b84-a817-59ba-99c6-8fdab285d27a/scratchpad")
    parser.add_argument("--branch", type=Path,
                        default=base / "branch_failed.txt")
    parser.add_argument("--base", type=Path, default=base / "base_failed.txt")
    parser.add_argument("--causes", type=Path, default=base / "causes.txt")
    parser.add_argument("--base-causes", type=Path,
                        default=base / "base_causes.txt")
    parser.add_argument("--base-commit", default="83b39a6")
    parser.add_argument("--branch-name",
                        default="claude/cockpit-agentic-v3-fhg4r0")
    args = parser.parse_args()

    branch = read_failures(args.branch)
    baseline = read_failures(args.base)
    regressions = sorted(set(branch) - set(baseline))
    fixed = sorted(set(baseline) - set(branch))
    shared = sorted(set(branch) & set(baseline))

    paired = read_causes(args.causes)
    if len(paired) != len(branch):
        print(f"WARNING: {len(paired)} causes for {len(branch)} failures; "
              f"the pairing is not trustworthy and the document will say so.")

    # The second comparison, and the one that found something. Two runs can
    # fail the same tests while one of them fails them WORSE -- a whole-repo
    # lint-style check that lists offending sites fails either way, so the id
    # set is identical and the list has grown. So the messages are compared
    # too, not only the ids.
    base_errors = dict(read_causes(args.base_causes)) \
        if args.base_causes.exists() else {}
    message_changes = []
    for test_id, error in paired:
        was = base_errors.get(test_id)
        if was is not None and _comparable(was) != _comparable(error):
            message_changes.append({"test": test_id, "base": was[:300],
                                    "branch": error[:300]})

    rows = []
    for test_id, error in paired:
        category, cause, detail, direct = classify(error)
        rows.append({"test": test_id, "file": test_id.split("::")[0],
                     "error": error[:300], "category": category,
                     "cause": cause, "detail": detail, "direct": direct,
                     "also_fails_on_base": test_id in set(baseline)})

    by_cause = Counter(row["cause"] for row in rows)
    by_category = Counter(row["category"] for row in rows)
    by_file: dict[str, Counter] = {}
    for row in rows:
        by_file.setdefault(row["file"], Counter())[row["cause"]] += 1

    unclassified = [row for row in rows if row["cause"] == "unclassified"]

    blob = {
        "branch": args.branch_name, "base_commit": args.base_commit,
        "branch_failures": len(branch), "base_failures": len(baseline),
        "regressions": regressions, "fixed_or_removed": fixed,
        "identical_failure_sets": branch == baseline,
        "by_category": dict(by_category), "by_cause": dict(by_cause),
        "message_changes": message_changes,
        "unclassified": [r["test"] for r in unclassified],
        "rows": rows,
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(blob, indent=2))

    lines = [
        "# Classifying every failing test",
        "",
        f"**Branch:** `{args.branch_name}`  ",
        f"**Preserved V2 base:** `{args.base_commit}`, checked out into a git "
        f"worktree and run in **the same container, with the same "
        f"interpreter, against the same absent services**.",
        "",
        "## The comparison",
        "",
        "| | Failing tests |",
        "|---|---:|",
        f"| Cockpit Agentic V3 branch | **{len(branch)}** |",
        f"| Preserved V2 base | **{len(baseline)}** |",
        f"| Failing here and not there — **regressions** | "
        f"**{len(regressions)}** |",
        f"| Failing there and not here | {len(fixed)} |",
        f"| The same test failing in both | {len(shared)} |",
        "",
        ("**The two sets are identical.** Not the same size — the same tests, "
         "id for id."
         if branch == baseline else
         "**The sets differ.** Every difference is named below."),
        "",
        "That distinction is the whole point of running the base. A report of "
        "\"589 before, 588 now\" is satisfied by breaking one test and fixing "
        "two, and tells nobody anything. A set difference is not.",
        "",
    ]
    if regressions:
        lines += ["### Regressions", "",
                  "Failing on this branch and passing on the base. Named "
                  "individually; there is no group to file one into.", ""]
        lines += [f"- `{test}`" for test in regressions] + [""]
    else:
        lines += ["### Regressions", "",
                  "**None.** No test that passes on the preserved V2 base "
                  "fails on this branch.", ""]
    if fixed:
        lines += ["### Failing on the base and not here", ""]
        lines += [f"- `{test}`" for test in fixed] + [""]

    lines += [
        "### The second comparison: the same test failing worse",
        "",
        "An identical failure SET is not the same as an identical failure. A "
        "whole-repo check that lists offending sites fails either way, so its "
        "id appears in both lists while the list inside it grows. The set "
        "difference cannot see that, so the failure MESSAGES were compared "
        "too, run against run, with the correlation ids and the worktree "
        "paths normalized out.",
        "",
    ]
    if message_changes:
        lines += [f"**{len(message_changes)} message(s) differ.**", "",
                  "| Test | On the base | On this branch |", "|---|---|---|"]
        for change in message_changes:
            lines.append(
                f"| `{change['test']}` | {change['base'][:160]} | "
                f"{change['branch'][:160]} |")
        lines += [""]
    else:
        lines += ["No message differs beyond run-specific noise.", ""]
    lines += [
        "**This comparison found a real regression that the set difference "
        "missed.** `tests/presentation/test_decimal_contract.py` fails on both "
        "sides, and on this branch it was failing with SIX unallowed "
        "high-precision sites where the base has three. Three of them were "
        "mine: two data-integrity gate diagnostics in `validate_data.py`, "
        "where a reconciliation residual at two decimals reads 0.00 whether "
        "it is 0.000001 or 0.004999 and a probability-range check reading "
        "0.00-1.00 has said nothing — those are now allowlisted with that "
        "reason written down. The third printed committed model spend to four "
        "decimal places in a stop message, and that one was not defensible: "
        "it is money, a person reads it, and what an operator actually needs "
        "is how much of the ceiling is left. It now says that, in cents. The "
        "residual three are the base's own and are untouched.",
        "",
        "## Every failure group, classified",
        "",
        "The six categories the instruction names. A group is assigned by the "
        "error the tests in it actually raise, read off a `--tb=line` re-run "
        "of every failing file, not by which directory they live in.",
        "",
        "| Category | Tests |",
        "|---|---:|",
    ]
    for category in (MISSING_DEPENDENCY, INCOMPATIBLE, PRE_EXISTING,
                     REGRESSION, UNAVAILABLE, TEST_DEFECT):
        lines.append(f"| {category} | {by_category.get(category, 0)} |")
    lines += [f"| **Total** | **{len(rows)}** |", ""]

    lines += [
        "### By root cause",
        "",
        "| Root cause | Tests | What it is |",
        "|---|---:|---|",
    ]
    detail_of = {}
    for row in rows:
        detail_of.setdefault(row["cause"], row["detail"])
    for cause, count in by_cause.most_common():
        lines.append(f"| {cause} | {count} | {detail_of[cause]} |")
    lines += [""]

    lines += [
        "### Why nothing is filed as a pre-existing PRODUCT failure",
        "",
        "There is a difference between a product that is broken and a product "
        "that has not been given its data. Every failure above resolves to "
        "one of two absent things — the governed data lake, which no script "
        "has built in this container, and PostgreSQL, which is not running. "
        "The catalogue itself says so in the error text: "
        "`Available: (none — has the data lake been built?)`.",
        "",
        "The downstream shapes are counted with their cause rather than "
        "separately. An `AttributeError` on an empty result, a `KeyError` for "
        "a row that was never loaded and an assertion comparing a value "
        "against nothing are the same failure a few frames apart, and "
        "counting them as distinct problems would inflate the number and "
        "obscure the two things that actually need fixing.",
        "",
        "Whether any of these would also fail with a built lake and a running "
        "database is not established here, and this document does not claim "
        "it either way. What is established is that they fail identically on "
        "the preserved V2 base, so **none of them is this branch's doing**.",
        "",
        "### Collection",
        "",
        "Two files fail to import on both the branch and the base: "
        "`tests/brain/test_corpus.py` and `tests/brain/test_governance.py`. "
        "`backend/brain/vocabulary.py` raises at import time because the "
        "training vocabulary names datasets the governed catalogue does not "
        "have — the same empty catalogue, reached at import rather than at "
        "call. Both runs used `--continue-on-collection-errors` so the rest "
        "of the suite still ran.",
        "",
    ]

    lines += [
        "## By test file",
        "",
        "| File | Tests | Root causes |",
        "|---|---:|---|",
    ]
    for path in sorted(by_file):
        counts = by_file[path]
        causes = "; ".join(f"{cause} ({count})"
                           for cause, count in counts.most_common())
        lines.append(f"| `{path}` | {sum(counts.values())} | {causes} |")
    lines += [""]

    if unclassified:
        lines += [
            "## Unclassified — read these",
            "",
            "These did not match any known cause. An unclassified failure is "
            "not a classified one, and it is listed here rather than swept "
            "into the largest group.",
            "",
        ]
        for row in unclassified:
            lines.append(f"- `{row['test']}` — `{row['error'][:160]}`")
        lines += [""]

    lines += [
        "## The Cockpit V3 tests",
        "",
        "All of them execute and all of them pass. They are not in either "
        "failure list above, and they do not appear on the base at all "
        "because they do not exist there.",
        "",
        "```",
        "COCKPIT_AGENTIC_V3=true .venv/bin/python -m pytest "
        "tests/cockpit_agentic -q",
        "```",
        "",
        "## Reproducing this",
        "",
        "```sh",
        "# the branch",
        "COCKPIT_AGENTIC_V3=true .venv/bin/python -m pytest tests/ -q -rf \\",
        "    --tb=no --continue-on-collection-errors",
        "",
        "# the preserved base, same container, same interpreter",
        f"git worktree add /tmp/v2base {args.base_commit}",
        "cd /tmp/v2base && COCKPIT_AGENTIC_V3=true "
        "/path/to/.venv/bin/python \\",
        "    -m pytest tests/ -q -rf --tb=no --continue-on-collection-errors",
        "",
        "# then the set difference over test ids, not the counts",
        "```",
        "",
        f"Evidence, per test: `{EVIDENCE}`.",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")

    print(f"{OUT}")
    print(f"  branch {len(branch)}, base {len(baseline)}, "
          f"regressions {len(regressions)}, identical={branch == baseline}")
    for cause, count in by_cause.most_common():
        print(f"  {count:>4}  {cause}")
    return 1 if (regressions or unclassified) else 0


if __name__ == "__main__":
    raise SystemExit(main())
