"""
The twenty-two questions, through the real Ask path. §39, §49.

§39 lists twenty-two questions that must work and says to run them through the
REAL Ask path — not a fixture, not a unit test of the planner. This does that:
it posts each one to `/api/v1/ask` on the real application and records what
comes back.

What this can and cannot establish
-----------------------------------
It establishes the properties that hold WITHOUT a language provider, and those
are the ones that were actually broken:

  * nothing returns a raw 500, and no reply prints a status code (§9);
  * every reply either answers or asks a question — nothing dead-ends with
    no next move (§5, §8);
  * no reply names an intelligence provider or a model (§12);
  * no reply calls the product a demonstration (§13);
  * a question asked twice returns the same thing (§11).

It does NOT establish that the ANSWERS are good. Answer quality on questions
of this complexity is the provider's half of the work, and this environment
has none configured — running it here would prove nothing about a deployment
that does. The report says which half ran.

    .venv/bin/python scripts/question_walkthrough.py --out docs/question_walkthrough.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: §39, verbatim. Numbered as the mandate numbers them so a reader can check
#: this list against it rather than taking the script's word for it.
QUESTIONS: tuple[str, ...] = (
    "Identify the 10 borrowers with the highest probability of credit "
    "deterioration over the next 12 months. For each borrower explain the top "
    "five drivers, distinguish borrower-specific drivers from macroeconomic "
    "drivers and rank the evidence by materiality.",

    "Which borrowers have the strongest evidence of liquidity stress? Consider "
    "cash balances, working-capital movements, short-term debt, utilisation, "
    "repayment patterns, interest burden and upcoming maturities.",

    "Which borrowers appear acceptable on headline ratios but show hidden "
    "deterioration when covenant headroom, payment behaviour, utilisation, "
    "ratings, collateral and early-warning evidence are combined?",

    "Find borrowers whose leverage increased, EBITDA margin declined and "
    "debt-service capacity weakened over the last four reporting periods. "
    "Which also have covenant pressure or negative rating migration?",

    "Which Stage 1 borrowers show the strongest evidence of possible future "
    "Stage 2 migration? Separate quantitative, qualitative and forward-looking "
    "evidence.",

    "Which good-rated borrowers worry you?",

    "Where is the rating behind the facts?",

    "Who is drawing more heavily because they are under pressure rather than "
    "because they are growing?",

    "Which borrowers are near covenant breach?",

    "Which borrowers breach under a 15% EBITDA stress?",

    "Where is collateral giving false comfort?",

    "Which connected groups look materially riskier than their individual "
    "legal entities?",

    "Which external events matter most to the current portfolio?",

    "Which borrowers show internal deterioration consistent with external "
    "events?",

    "Which signals have persisted for at least three reporting periods?",

    "Which borrowers have recovered and may deserve removal from watch?",

    "Which SME borrowers concern you most?",

    "Which large corporates concern you most?",

    "Where are several weak signals combining into a serious problem?",

    "Find situations where the evidence conflicts.",

    "Find something a strong credit officer might miss.",

    "Prepare the five situations senior management should discuss first "
    "tomorrow.",
)


def _client():
    os.environ.setdefault("REQUIRE_LOGIN", "false")
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


HEADERS = {"X-IPM-Role": "ANALYST", "X-IPM-User-Id": "1"}


def ask(client: Any, question: str) -> dict[str, Any]:
    response = client.post("/api/v1/ask",
                           json={"question": question, "persist": False},
                           headers=HEADERS)
    body: Any
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {"_unparseable": response.text[:400]}
    return {"status_code": response.status_code, "body": body}


def judge(question: str, first: dict[str, Any],
          second: dict[str, Any]) -> dict[str, Any]:
    """What can be checked without a provider, checked."""
    from backend.release import product_copy

    body = first["body"] if isinstance(first["body"], dict) else {}
    said = json.dumps(body, default=str)

    clarification = body.get("clarification") or {}
    narrative = body.get("narrative") or {}
    # An `unsupported` outcome answers through `narrative.direct_answer`: it
    # says what was looked for, why it is not held, and what to ask instead.
    # Counting only `steps` would call that a dead end, which it is not - and
    # a harness that mislabels a good refusal teaches somebody to remove it.
    answered = bool(body.get("steps")) or bool(body.get("answer")) or \
        bool(narrative.get("direct_answer"))
    asked = bool(clarification.get("question"))
    # Only a refusal needs to name a next move. A clarification IS one: the
    # question it asks is the move. Demanding both of a clarification would
    # push the product back toward the menu §6 removed.
    moved_on = bool(str(narrative.get("direct_answer") or "").strip()
                    and not body.get("steps")
                    and not clarification.get("question"))

    faults: list[str] = []
    if first["status_code"] >= 500:
        faults.append(f"returned {first['status_code']}")
    if "Request failed with status" in said:
        faults.append("printed a transport failure to the reader")
    if product_copy.PROVIDER_PATTERN.search(said):
        faults.append("named an intelligence provider or a model")
    # §13 checked where §13 applies: the prose a reader is shown. Scanning
    # every value in the payload flags `origin: "demo"`, a governance enum
    # identifier that is stored, compared against, and never rendered - and a
    # scanner that flags every answer is one somebody switches off.
    leaked = product_copy.demonstration_in_prose(body)
    if leaked:
        faults.append(f"called the product a demonstration in {leaked[0][0]}")
    if not answered and not asked:
        faults.append("dead-ended: neither answered nor asked anything")
    if moved_on and not any(phrase in said for phrase in NEXT_MOVE):
        faults.append("refused without saying what could be asked instead")
    if _answer_only(second["body"]) != _answer_only(first["body"]):
        faults.append("gave a different reply the second time")

    return {
        "question": question,
        "status_code": first["status_code"],
        "outcome": body.get("status", ""),
        "answered": answered,
        "asked_a_question": asked,
        "faults": faults,
        "ok": not faults,
    }


#: The governed ways this product tells a reader what to do next after a
#: refusal. Listed rather than pattern-matched, because "does this sentence
#: offer a way on" is not something a regex decides - and a check that guesses
#: will pass a refusal that offers nothing while failing one that does.
NEXT_MOVE: tuple[str, ...] = (
    "Name the figure",           # coverage.next_move, no recognised terms
    "Name the one you want",     # coverage.next_move, measures listed
    "can be answered",           # coverage.next_move, terms recognised
    "Narrowing the question",    # executor._withheld_sentence
    "a data steward can publish",
    "A data steward can publish",
)

#: Fields that legitimately differ between two identical runs. §11 is about
#: the ANSWER being the same, not about the clock: a Trace that recorded the
#: same finish time twice would be lying about when the work happened.
TIMING = frozenset({"finished_at", "started_at", "duration_ms", "elapsed_ms",
                    "created_at", "updated_at", "run_id", "request_id",
                    "trace_id", "id"})


def _answer_only(value: Any) -> Any:
    """The reply with the clock taken out of it."""
    if isinstance(value, dict):
        return {k: _answer_only(v) for k, v in sorted(value.items())
                if k not in TIMING}
    if isinstance(value, list):
        return [_answer_only(v) for v in value]
    return value


def run() -> dict[str, Any]:
    client = _client()
    rows = []
    for question in QUESTIONS:
        first = ask(client, question)
        second = ask(client, question)
        rows.append(judge(question, first, second))
    failed = [r for r in rows if not r["ok"]]
    return {
        "questions": len(QUESTIONS),
        "passed": len(rows) - len(failed),
        "failed": len(failed),
        "checked": [
            "no reply returns a 5xx",
            "no reply prints a status code to the reader",
            "no reply names an intelligence provider or a model",
            "no reply calls the product a demonstration",
            "every reply either answers or asks a question",
            "the same question twice returns the same reply",
        ],
        "not_checked": [
            "whether the ANSWERS are good. Answer quality on questions of "
            "this complexity is the provider's half of the work, and this "
            "environment has none configured. Running it here would prove "
            "nothing about a deployment that does.",
        ],
        "results": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/question_walkthrough.json")
    args = parser.parse_args(argv)

    report = run()
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    for row in report["results"]:
        mark = "  ok" if row["ok"] else "FAIL"
        print(f"{mark}  [{row['outcome'] or row['status_code']}] "
              f"{row['question'][:72]}")
        for fault in row["faults"]:
            print(f"        {fault}")
    print(f"\n{report['passed']} of {report['questions']} passed the checks "
          f"this environment can make. Written to {args.out}.")
    return 0 if not report["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
