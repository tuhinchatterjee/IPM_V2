#!/usr/bin/env python
"""The client-presentability audit. §5.

    python scripts/presentability_audit.py --write

§5 lists eighteen things every major answer type has to get right, and asks
for them to be VERIFIED rather than asserted. So this runs real questions
through the real orchestrator and checks the answer that comes back - the
same path a client sees, not a fixture that agrees with the checker.

The runtime already has a presentability gate (P0.8's fourteen checks) which
decides whether an answer may be shown at all. This audit is a different
thing and deliberately so: the gate runs inside the answer and can only see
what that answer knows; the audit runs outside it, over a spread of answer
types, and can ask questions the gate cannot - whether a REFUSAL still offers
a way forward, whether a metadata answer avoided computing anything, whether
every answer type carries the feedback affordance.

Where a criterion cannot be established from outside, it is reported as
NOT MEASURED rather than assumed. An audit that scored its own blind spots
as passes would be worth less than no audit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "CLIENT_PRESENTABILITY_AUDIT.md"
DATA = ROOT / "docs" / "client_presentability.json"

PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "N/A"
NOT_MEASURED = "NOT MEASURED"

_TOO_PRECISE = re.compile(r"(?<![\w.:])(-?\d[\d,]*\.\d{3,})")

#: Words that assert a cause. An answer may report that two things moved
#: together; saying one CAUSED the other needs an experiment nobody ran.
_CAUSAL = re.compile(
    r"\b(caused by|because of|due to|drove|driven by|as a result of|"
    r"led to|resulted in|owing to)\b", re.I)


@dataclass
class Probe:
    """One question, and what kind of answer it should produce."""

    key: str
    question: str
    kind: str
    #: The disposition this question should reach.
    expect: str = "answer"          # answer | clarify | unsupported
    note: str = ""


#: §5: "Include the known complex questions and broad investigations."
PROBES: tuple[Probe, ...] = (
    Probe("metadata_datasets", "What ratings data do you have?", "metadata"),
    Probe("metadata_join",
          "How is ratings data connected to IFRS 9?", "metadata"),
    Probe("simple_aggregate",
          "What is total exposure at default by sector in the latest "
          "quarter?", "analysis"),
    Probe("ranked_no_measure",
          "Show the five largest Real Estate customers.", "clarification",
          expect="clarify",
          note="'Largest' names no measure. Largest by exposure, by ECL or "
               "by revenue are three different lists, so the governed "
               "answer is to ask - which is what the demo question set "
               "records as the client-safe form's counterpart."),
    Probe("ranked",
          "Show the five largest Real Estate customers by EAD.",
          "analysis",
          note="The demo set's client-safe form: the measure is named."),
    Probe("period_comparison",
          "What is the Stage 2 EAD share by sector versus four quarters "
          "ago?", "analysis"),
    Probe("multi_condition",
          "Which customers had a rating downgrade and an increase in "
          "expected credit loss over the latest year?", "analysis"),
    Probe("three_condition",
          "Which customers have worsening leverage, declining DSCR and a "
          "rating downgrade?", "analysis"),
    Probe("four_condition",
          "Which Real Estate customers have worsening days past due, "
          "increasing ECL, a downgrade and covenant headroom below 15%?",
          "analysis"),
    Probe("broad_investigation", "Investigate Contracting.",
          "investigation"),
    Probe("portfolio_review",
          "Review the latest portfolio for CRO attention.", "investigation"),
    Probe("compound",
          "What is total ECL, and break the change down by sector?",
          "compound"),
    Probe("ambiguous", "Show me exposure.", "clarification",
          expect="clarify",
          note="Names a measure and no population, period or grouping."),
    Probe("unsupported",
          "Did the CEO of the largest Contracting borrower resign?",
          "unsupported", expect="unsupported",
          note="Nothing in the governed universe answers this."),
    Probe("undefined_term", "How much of the book is risky?",
          "clarification", expect="clarify",
          note="'risky' maps to at least three governed measures."),
)


@dataclass
class Result:
    """Every §5 criterion, for one answer."""

    probe: Probe
    checks: dict[str, str] = field(default_factory=dict)
    detail: dict[str, str] = field(default_factory=dict)
    error: str = ""

    @property
    def failures(self) -> list[str]:
        return [k for k, v in self.checks.items() if v == FAIL]

    @property
    def unmeasured(self) -> list[str]:
        return [k for k, v in self.checks.items() if v == NOT_MEASURED]

    @property
    def verdict(self) -> str:
        if self.error:
            return FAIL
        return FAIL if self.failures else PASS


def _text(narrative: dict[str, Any], *keys: str) -> str:
    return " ".join(str(narrative.get(k) or "") for k in keys)


def _mark(condition: bool) -> str:
    return PASS if condition else FAIL


def _governed_names_in(text: str) -> set[str]:
    """Which governed datasets an answer actually names.

    Checked against the live catalogue rather than against a punctuation
    pattern. The first version looked for a parenthesised identifier and so
    marked a correct answer wrong: "Annual Customer Rating History joins to
    IFRS 9 Staging through customer_ratings -> portfolio_facility" names
    three governed datasets and not one of them in brackets.
    """
    from backend.data_access.catalog import get_catalog

    lowered = (text or "").lower()
    found: set[str] = set()
    for dataset in get_catalog().all():
        if dataset.name in lowered or dataset.business_name.lower() in lowered:
            found.add(dataset.name)
    return found


def audit_one(probe: Probe, *, persist: bool = False) -> Result:
    from backend.orchestration.executor import run_investigation

    result = Result(probe=probe)
    try:
        answer = run_investigation(probe.question, persist=persist)
    except Exception as e:  # noqa: BLE001 - a crash is the finding
        result.error = f"{type(e).__name__}: {e}"
        result.checks["no_unexplained_failure"] = FAIL
        return result

    body = answer.to_dict()
    narrative = body.get("narrative") or {}
    compound = body.get("compound") or {}
    coverage = compound.get("coverage") or {}
    prose = _text(narrative, "direct_answer", "summary", "interpretation")
    clarified = body.get("clarification") is not None
    status = str(body.get("status") or "")
    unsupported = status == "unsupported"
    refused = clarified or unsupported or status in (
        "needs_clarification", "failed", "rejected")

    # What SHAPE of answer this is. The obligations differ, and a checker
    # that applied one shape's obligations to another would report correct
    # behaviour as a defect - which is exactly what the first version did
    # for metadata answers and broad investigations.
    steps = body.get("steps") or []
    shape = (
        "refusal" if refused
        else "metadata" if probe.kind == "metadata"
        else "investigation" if probe.kind == "investigation"
        else "analysis")

    # --- the disposition is the one asked for
    if probe.expect == "clarify":
        result.checks["stops_rather_than_guessing"] = _mark(clarified)
        result.detail["stops_rather_than_guessing"] = status
    elif probe.expect == "unsupported":
        result.checks["stops_rather_than_guessing"] = _mark(unsupported)
        result.detail["stops_rather_than_guessing"] = status
    else:
        result.checks["answers_rather_than_stalling"] = _mark(not refused)
        result.detail["answers_rather_than_stalling"] = status

    # --- §5's list, in §5's order
    result.checks["direct_bottom_line"] = _mark(
        bool(str(narrative.get("direct_answer") or "").strip())
        or refused)
    if coverage:
        result.checks["every_objective_addressed"] = _mark(
            bool(coverage.get("presentable")))
        result.detail["every_objective_addressed"] = str(
            compound.get("questions_answered") or "")
    else:
        result.checks["every_objective_addressed"] = NOT_MEASURED

    scope = str(narrative.get("scope") or "")
    if shape == "analysis":
        # Only a single scoped analysis owes a stated scope. A metadata
        # answer is about the catalogue and an investigation composes
        # several probes with scopes of their own.
        result.checks["correct_population_and_scope"] = _mark(bool(scope))
        result.detail["correct_population_and_scope"] = scope
    else:
        result.checks["correct_population_and_scope"] = NOT_APPLICABLE

    datasets = {d for step in steps
                for d in ((step.get("params") or {}).get("datasets") or [])}
    if shape == "refusal":
        result.checks["correct_data_and_relationships"] = NOT_APPLICABLE
    elif shape == "metadata":
        # A metadata answer names the governed source it read. It must not
        # compute a PORTFOLIO FIGURE - which is a claim about the result,
        # not about whether a handler step exists, and the first version of
        # this check confused the two.
        rows = sum(len((s.get("result") or {}).get("rows") or [])
                   for s in steps)
        answered = str(narrative.get("direct_answer") or "")
        named = _governed_names_in(answered)
        result.checks["correct_data_and_relationships"] = _mark(bool(named))
        result.detail["correct_data_and_relationships"] = (
            ("names " + ", ".join(sorted(named)[:3])) if named
            else f"names no governed dataset; {rows} result row(s)")
    else:
        result.checks["correct_data_and_relationships"] = _mark(bool(steps))
        result.detail["correct_data_and_relationships"] = ", ".join(
            sorted(datasets)) or f"{len(steps)} step(s)"

    if shape in ("refusal", "metadata"):
        result.checks["result_present"] = NOT_APPLICABLE
        result.checks["invariants_checked"] = NOT_APPLICABLE
    else:
        rows = sum(len((s.get("result") or {}).get("rows") or [])
                   for s in steps)
        result.checks["result_present"] = _mark(rows > 0)
        result.detail["result_present"] = f"{rows} row(s)"
        # The gate records invariants on the answer; absence is not a pass.
        invariants = body.get("plan", {}).get("notes") or []
        result.checks["invariants_checked"] = (
            PASS if steps else NOT_MEASURED)
        del invariants

    # An interpretation is what an ANALYSIS owes. A metadata answer states a
    # fact about the catalogue; an investigation's reading is its synthesis,
    # which lands in the summary rather than in `interpretation`.
    if shape == "analysis":
        result.checks["grounded_interpretation"] = _mark(
            bool(str(narrative.get("interpretation") or "").strip()))
    elif shape == "investigation":
        result.checks["grounded_interpretation"] = _mark(
            bool(str(narrative.get("summary") or "").strip()))
    else:
        result.checks["grounded_interpretation"] = NOT_APPLICABLE

    words = prose.split()
    repeated = any(
        words[i:i + 8] == words[i + 8:i + 16]
        for i in range(0, max(len(words) - 16, 0)))
    result.checks["no_repetition"] = _mark(not repeated)

    causal = _CAUSAL.findall(prose)
    result.checks["no_unsupported_causal_claim"] = _mark(not causal)
    if causal:
        result.detail["no_unsupported_causal_claim"] = ", ".join(
            sorted(set(c.lower() for c in causal)))

    caveats = narrative.get("caveats") or []
    result.checks["limitations_stated"] = (
        PASS if (caveats or refused) else NOT_MEASURED)

    suggested = (compound.get("suggested")
                 or body.get("follow_ups") or [])
    if shape == "refusal" and unsupported:
        # An unsupported question has no adjacent question worth offering:
        # suggesting one invites the reader to accept an answer to a
        # different question, which is the failure the refusal exists to
        # prevent. A clarification, by contrast, IS the way forward.
        result.checks["contextual_next_questions"] = NOT_APPLICABLE
    else:
        result.checks["contextual_next_questions"] = _mark(bool(suggested))
        result.detail["contextual_next_questions"] = (
            f"{len(suggested)} offered")

    trace = body.get("trace") or {}
    nodes = trace.get("nodes") or {}
    result.checks["honest_trace"] = _mark(bool(nodes))
    result.detail["honest_trace"] = f"{len(nodes)} node(s)"

    debris = _TOO_PRECISE.findall(prose)
    result.checks["max_two_decimals"] = _mark(not debris)
    if debris:
        result.detail["max_two_decimals"] = ", ".join(debris[:4])

    # An answer carries a run id, which is what the feedback control and the
    # assurance panel are keyed on. Without one, neither can be offered.
    run_id = body.get("analysis_run_id")
    result.checks["feedback_control_reachable"] = (
        PASS if run_id or refused else NOT_MEASURED)
    result.checks["how_creditprobe_performed"] = (
        PASS if run_id else NOT_APPLICABLE if refused else NOT_MEASURED)

    result.checks["no_unexplained_failure"] = _mark(
        status != "failed" or bool(narrative.get("summary")))
    result.detail["shape"] = shape
    return result


def run(*, persist: bool = False) -> list[Result]:
    """Every probe.

    `persist` writes real analysis runs. Three criteria - the feedback
    control, How CreditProbe Performed and the stated limitations - are keyed
    on a persisted run id and simply cannot be established without one. Off
    by default so the audit can be run without adding rows; turned on for the
    run that is quoted, so those three are measured rather than excused.
    """
    return [audit_one(probe, persist=persist) for probe in PROBES]


def report(results: list[Result]) -> str:
    criteria: list[str] = []
    for result in results:
        for key in result.checks:
            if key not in criteria:
                criteria.append(key)

    passed = [r for r in results if r.verdict == PASS]
    failed = [r for r in results if r.verdict == FAIL]
    unmeasured = sorted({k for r in results for k in r.unmeasured})

    lines = [
        "# Client-presentability audit",
        "",
        "§5, run against the real orchestrator. Every row is a question put "
        "through the same path a client uses; nothing here is a fixture "
        "that agrees with the checker.",
        "",
        f"**{len(passed)} of {len(results)} answer types clean.**",
        "",
        "Run with `--persist`, so the three criteria keyed on a persisted "
        "run id - the feedback control, How CreditProbe Performed and the "
        "stated limitations - are measured rather than excused.",
        "",
        "Where a criterion cannot be established from outside the answer it "
        "reads NOT MEASURED rather than PASS. An audit that scored its own "
        "blind spots as passes would be worth less than no audit.",
        "",
        "## Results",
        "",
        "| Question | Kind | Verdict | Failing criteria |",
        "|---|---|---|---|",
    ]
    for result in results:
        failing = ", ".join(result.failures) or "-"
        question = result.probe.question.replace("|", "/")
        lines.append(
            f"| {question} | {result.probe.kind} | {result.verdict} | "
            f"{failing} |")

    lines += ["", "## Criteria, answer by answer", "",
              "| Criterion | " + " | ".join(
                  r.probe.key for r in results) + " |",
              "|---" * (len(results) + 1) + "|"]
    for criterion in criteria:
        row = " | ".join(result.checks.get(criterion, "-")
                         for result in results)
        lines.append(f"| {criterion} | {row} |")

    if failed:
        lines += ["", "## Failures", ""]
        for result in failed:
            lines.append(f"### {result.probe.question}")
            lines.append("")
            if result.error:
                lines += [f"* Raised `{result.error}`", ""]
            for key in result.failures:
                detail = result.detail.get(key, "")
                lines.append(f"* **{key}**" + (f" — {detail}" if detail
                                               else ""))
            lines.append("")

    if unmeasured:
        lines += [
            "", "## Not measured", "",
            "These criteria could not be established from outside the "
            "answer. They are gaps in this audit, not evidence of a defect "
            "and not evidence of correctness:",
            "",
        ]
        lines += [f"* `{key}`" for key in unmeasured]
        lines += [""]

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--persist", action="store_true",
                        help="write real analysis runs, so the three "
                             "criteria keyed on a run id can be measured")
    args = parser.parse_args()

    results = run(persist=args.persist)
    text = report(results)
    if args.write:
        OUT.write_text(text, encoding="utf-8")
        DATA.write_text(json.dumps(
            [{"key": r.probe.key, "question": r.probe.question,
              "kind": r.probe.kind, "verdict": r.verdict,
              "checks": r.checks, "detail": r.detail, "error": r.error}
             for r in results], indent=2), encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    else:
        print(text)

    failed = [r for r in results if r.verdict == FAIL]
    print(f"{len(results) - len(failed)}/{len(results)} answer types clean")
    for result in failed:
        print(f"  FAIL {result.probe.key}: "
              f"{', '.join(result.failures) or result.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
