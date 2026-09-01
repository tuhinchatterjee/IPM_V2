#!/usr/bin/env python
"""
What a question costs, measured rather than guessed. R2 §16.

Why this exists
---------------
The instruction is "instrument the actual cause before guessing". Guessing is
cheap and usually wrong: a cost problem looks like a long prompt, or a big
model, or too many loops, and any of the three can be the whole bill while the
other two are noise. So this harness runs a representative question set
through the REAL paths — the real router, the real catalogue, the real
governed tools, the real evidence ledger — and reports what each question
actually consumed.

No live calls, no credits
-------------------------
The provider is a local stand-in that never leaves the process. It is not a
stub that returns a fixed number: it counts the tokens of the prompt it was
actually handed and returns a decision document of the shape the loop expects,
so the INPUT VOLUME it reports is the input volume the architecture really
sends. That is the quantity under investigation. What a live model would
CHOOSE to do differs, and the harness says so rather than pretending
otherwise — see `LIMITATIONS` at the foot of the report.

    .venv/bin/python scripts/measure_ai_cost.py
    .venv/bin/python scripts/measure_ai_cost.py --out docs/AI_COST_BASELINE.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.analyst import classify, cost, route, safety  # noqa: E402
from backend.llm.base import LLMResult  # noqa: E402

REPORT_VERSION = "1.0.0"

#: A run that never talks to a provider still needs a model id on each call,
#: because the meter records which model served what. This one names itself.
LOCAL_MODEL = "local-measurement-stand-in"

LIMITATIONS = (
    "Token counts are measured from the prompts this deployment actually "
    "builds, using a four-characters-to-a-token estimate rather than the "
    "provider's tokeniser. The number of turns is what the harness scripts, "
    "not what a live model would choose. So the figures below are sound for "
    "comparing one architecture with another — which is what they are for — "
    "and are not a forecast of a bill."
)


# ---------------------------------------------------------------------------
# The question set
# ---------------------------------------------------------------------------

#: Chosen to span §16's three classes and to be the questions a credit officer
#: actually asks, including the four-turn Shipping thread §26 requires.
QUESTIONS: tuple[tuple[str, str], ...] = (
    # Data and metadata — these must not reach a frontier model at all.
    ("How many data domains are there?", "metadata"),
    ("Which datasets are in the liquidity domain?", "metadata"),
    ("What does DSCR mean?", "metadata"),
    ("Which reporting periods do we hold?", "metadata"),
    ("How many rows are in corporate_ifrs9?", "metadata"),
    ("How do covenants join to facilities?", "metadata"),
    # Data queries — exact answers the governed runtime computes.
    ("Show the top 20 borrowers by 12-month PD.", "query"),
    ("What is total exposure at default by sector?", "query"),
    ("How many borrowers are in Stage 2?", "query"),
    ("List the borrowers with a covenant breach this quarter.", "query"),
    # Orchestration — several governed calls, assembled.
    ("Compare Stage 2 coverage in Shipping with Oil & Gas.", "orchestration"),
    ("Show exposure, stage and covenant headroom for CORP-100376.",
     "orchestration"),
    # Judgement — the work worth paying for.
    ("Why did Shipping deteriorate this quarter?", "judgement"),
    ("Which Shipping borrowers are the real issues?", "judgement"),
    ("Which of those have liquidity pressure?", "judgement"),
    ("Why does the second one worry you?", "judgement"),
)


# ---------------------------------------------------------------------------
# The stand-in
# ---------------------------------------------------------------------------


class Measuring:
    """A provider that consumes nothing and reports honestly what it was sent.

    It answers the analyst's decision schema, so the loop cannot tell it from
    a real one — which is the point of `backend.llm`'s contract being a single
    method. What it adds is the accounting: input tokens read off the prompt
    it was handed, output tokens off the document it returns.
    """

    name = "measurement"
    model = LOCAL_MODEL
    configured = True

    #: Discovery first, then evidence, then answer. The shape of a real
    #: investigation, held fixed so that two architectures are compared on the
    #: same work rather than on the model's mood.
    def __init__(self, tool_turns: int = 2) -> None:
        self.tool_turns = tool_turns
        self.calls = 0
        self.turn = 0

    def structured(self, *, system: str, prompt: str, schema: dict[str, Any],
                   tool_name: str = "", tool_description: str = "",
                   **kwargs: Any) -> LLMResult:
        del schema, tool_name, tool_description, kwargs
        self.calls += 1
        self.turn += 1
        data = self._decide()
        out = json.dumps(data)
        return LLMResult(
            data=data, model=self.model,
            input_tokens=cost.tokens_in(system) + cost.tokens_in(prompt),
            output_tokens=cost.tokens_in(out),
            duration_ms=0, attempts=1)

    def _decide(self) -> dict[str, Any]:
        if self.turn == 1:
            return {"action": "CALL_TOOL", "tool": "list_datasets",
                    "arguments": {}, "why": "find out what is available"}
        if self.turn <= self.tool_turns + 1:
            return {"action": "CALL_TOOL", "tool": "describe_dataset",
                    "arguments": {"dataset": "corporate_ifrs9"},
                    "why": "read the grain and the fields"}
        return {"action": "ANSWER",
                "answer": ("The governed evidence above supports the "
                           "following reading of the question."),
                "findings": ["one finding drawn from the evidence"],
                "unavailable": [], "limitations": []}


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def measure(questions: tuple[tuple[str, str], ...] = QUESTIONS,
            *, tool_turns: int = 2) -> dict[str, Any]:
    """Run every question and report what each one spent."""
    principal = safety.Principal(user_id=1, role="ADMIN")
    trace = cost.trace()
    trace.clear()
    rows: list[dict[str, Any]] = []

    for question, family in questions:
        reading = classify.read(question)
        provider = Measuring(tool_turns=tool_turns)
        with cost.measuring(question, question_class=reading.question_class,
                            why=reading.why) as meter:
            try:
                payload = route.answer(question, principal, provider=provider)
            except Exception as e:  # noqa: BLE001 - a failure is a measurement
                payload = {"path": "failed", "error": str(e)[:200]}
        row = meter.to_dict()
        row["question"] = question
        row["family"] = family
        row["path"] = payload.get("path", row.get("path", ""))
        row["outcome"] = payload.get("outcome", "")
        rows.append(row)

    return {
        "version": REPORT_VERSION,
        "questions": rows,
        "summary": trace.summary(),
        "by_family": _by_family(rows),
        "limitations": LIMITATIONS,
    }


def _by_family(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in rows:
        family = row["family"]
        bucket = out.setdefault(family, {"questions": 0, "model_calls": 0,
                                         "input_tokens": 0,
                                         "output_tokens": 0,
                                         "metadata_tokens": 0,
                                         "evidence_tokens": 0,
                                         "cost_units": 0.0})
        bucket["questions"] += 1
        bucket["model_calls"] += row["model_calls"]
        bucket["input_tokens"] += row["input_tokens"]
        bucket["output_tokens"] += row["output_tokens"]
        bucket["metadata_tokens"] += row["metadata_tokens"]
        bucket["evidence_tokens"] += row["evidence_tokens"]
        bucket["cost_units"] += row["cost_units"]
    for bucket in out.values():
        n = bucket["questions"]
        bucket["avg_model_calls"] = round(bucket["model_calls"] / n, 2)
        bucket["avg_input_tokens"] = int(bucket["input_tokens"] / n)
        bucket["avg_cost_units"] = round(bucket["cost_units"] / n, 2)
        bucket["cost_units"] = round(bucket["cost_units"], 2)
    return out


def say(report: dict[str, Any]) -> None:
    print(f"\n{'QUESTION':<52} {'CLASS':<17} {'CALLS':>5} "
          f"{'IN':>8} {'OUT':>6} {'META':>8} {'EVID':>8} {'UNITS':>9}")
    print("-" * 118)
    for row in report["questions"]:
        print(f"{row['question'][:50]:<52} {row['question_class']:<17} "
              f"{row['model_calls']:>5} {row['input_tokens']:>8} "
              f"{row['output_tokens']:>6} {row['metadata_tokens']:>8} "
              f"{row['evidence_tokens']:>8} {row['cost_units']:>9.1f}")
    print("-" * 118)
    print("\nBY FAMILY")
    for name, bucket in report["by_family"].items():
        print(f"  {name:<16} {bucket['questions']:>3} question(s)  "
              f"{bucket['avg_model_calls']:>5.2f} call(s)/q  "
              f"{bucket['avg_input_tokens']:>8,} input token(s)/q  "
              f"{bucket['avg_cost_units']:>9.1f} unit(s)/q")
    total = report["summary"]
    print(f"\nTOTAL  {total['questions']} question(s), "
          f"{total['model_calls']} model call(s), "
          f"{total['cost_units']:,.1f} cost unit(s)")
    print(f"\n{report['limitations']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="", help="write the report as JSON")
    parser.add_argument("--tool-turns", type=int, default=2,
                        help="how many evidence-gathering turns to script")
    args = parser.parse_args()

    report = measure(tool_turns=args.tool_turns)
    say(report)
    if args.out:
        path = pathlib.Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
