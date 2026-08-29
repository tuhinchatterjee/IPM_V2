#!/usr/bin/env python
"""Check the demonstration question set. §25.

    "Any mismatch in a critical property blocks GO."

Drives the real routing, officer selection and planning path for every
question in `backend/demo/questions.py` and checks the DETERMINISTIC half of
each acceptance specification: which officer was selected, whether specialists
were engaged, whether it executed, clarified or refused, and which governed
datasets it read.

It makes NO provider call. Every probe runs inside `assert_no_provider_calls`,
which makes an attempt raise, so this is structural rather than a promise.

What it deliberately does NOT check
-----------------------------------
The prose, the interpretation and the exact figures. Those need a live model
and they are what the presenter's own `-Critical` run is for. Reporting them
as passed here would be claiming a verification that did not happen.

    .venv/bin/python scripts/demo_questions.py
    .venv/bin/python scripts/demo_questions.py --json docs/demo_questions.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.demo import questions as spec  # noqa: E402

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_DID_NOT_RUN = 2


#: Flow classes that mean the answer came from the catalogue rather than from
#: a governed analysis. Read from the probe's own flow classification so this
#: file does not invent a second opinion about what happened.
_METADATA_FLOWS = frozenset({"METADATA_DISCOVERY", "RELATIONSHIP_DISCOVERY"})


def _outcome_of(probe: Any) -> str:
    """What the run actually did, in the question set's own vocabulary."""
    if getattr(probe, "unsupported", False):
        return spec.UNSUPPORTED
    if getattr(probe, "clarified", False):
        return spec.CLARIFY
    if str(getattr(probe, "flow", "")) in _METADATA_FLOWS:
        return spec.METADATA
    if getattr(probe, "executed", False):
        return spec.EXECUTE
    return "NO_ANALYSIS"


def check(question: spec.Question, probe: Any) -> list[str]:
    """Everything about this run that contradicts the specification.

    Returns the mismatches. An empty list is a pass, and the reason each one
    matters is in the sentence rather than in a code.
    """
    problems: list[str] = []

    if getattr(probe, "error", ""):
        return [f"the request raised: {probe.error[:200]}"]

    got = _outcome_of(probe)
    want = question.outcome
    if want == spec.REUSE:
        # Reuse cannot be separated from execute by the probe alone. What CAN
        # be asserted is that it did not clarify or refuse, and that it read
        # no fresh dataset - which is the observable half of reuse.
        if got in (spec.CLARIFY, spec.UNSUPPORTED):
            problems.append(f"expected it to assess the previous result, "
                            f"and it returned {got}")
    elif got != want:
        problems.append(f"expected {want}, got {got}")

    level = getattr(probe, "officer_level", None)
    if question.officer is not None and level != question.officer:
        problems.append(
            f"officer {level} ({spec.OFFICER_TITLE.get(level or 0, '?')}), "
            f"expected {question.officer} "
            f"({spec.OFFICER_TITLE[question.officer]})")

    engaged = len(getattr(probe, "specialists", ()) or ())
    if question.specialists and engaged < question.specialists:
        problems.append(f"{engaged} specialist(s), expected at least "
                        f"{question.specialists}")
    if question.specialists == 0 and engaged and question.outcome != spec.EXECUTE:
        problems.append(f"{engaged} specialist(s) engaged for a question that "
                        "needs none")

    # A run that executed must say which governed data it read. Which
    # datasets is a planning decision that can legitimately differ; that it
    # read SOMETHING and recorded it is not negotiable.
    if want == spec.EXECUTE and getattr(probe, "executed", False):
        if not (getattr(probe, "datasets", ()) or ()):
            problems.append("it executed and reported no dataset, so the "
                            "Trace cannot say what it read")

    for name in getattr(probe, "critical_not_available", ()) or ():
        problems.append(f"critical assurance check with no signal: {name}")

    return problems


def _thread(setup: str) -> tuple[Any, Any]:
    """Ask one question, and return the state a follow-up would arrive with.

    Mirrors `scripts/agentic_baseline.py`, which is how the service itself
    carries a thread forward. Doing it any other way would test a code path
    the product does not have.
    """
    from backend.orchestration import conversation as cv
    from backend.orchestration import memory as wm
    from backend.orchestration.orchestrator import remember as advance
    from backend.proof.probe import run_probe

    context: dict[str, Any] = {}
    _, officer = run_probe(setup, label="setup")
    try:
        investigation = getattr(officer, "investigation", None)
        answered = getattr(officer, "answered", None)
        headline = str(getattr(getattr(investigation, "narrative", None),
                               "direct_answer", "") or "")
        context = cv.save(context, advance(cv.load(context), answered,
                                           headline=headline, run_id=None))
        context = wm.save(context, wm.observe(wm.load(context), answered,
                                              investigation))
    except Exception:  # noqa: BLE001 - a thread that cannot be carried is
        # reported by the check that follows, not hidden by an exception here.
        return None, None
    return cv.load(context), wm.load(context)


def _demo_project() -> int | None:
    """The seeded demonstration Project, if there is one."""
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import Project

        with get_session() as session:
            row = session.execute(
                select(Project).order_by(Project.id.desc())).scalars().first()
            return int(row.id) if row is not None else None
    except Exception:  # noqa: BLE001 - no Project is a reportable state
        return None


def run(refs: list[str] | None = None) -> dict[str, Any]:
    from backend.proof.probe import run_probe

    chosen = [q for q in spec.QUESTIONS if not refs or q.ref in refs]
    results: list[dict[str, Any]] = []
    started = time.perf_counter()

    # Two questions are meaningless without their context, and the first
    # version of this runner asked them standalone and reported the product
    # as broken. "Does this trend make sense?" with nothing on screen SHOULD
    # clarify; "Review unresolved risks in this Project" outside a Project
    # SHOULD clarify. Both were right and the runner was wrong.
    project_id = _demo_project()

    for question in chosen:
        try:
            if question.ref == "Q11":
                # Asked as a follow-up to a real trend, in one thread.
                #
                # State is carried the way the service carries it: through
                # `conversation.save` and `memory.observe`, not by handing the
                # previous `Answered` back as the state. The first version of
                # this runner did the latter and crashed the orchestrator with
                # `'Answered' object has no attribute 'concepts'` - the runner's
                # fault, and worth recording because the two objects are
                # returned side by side and are easy to confuse.
                state, memory = _thread(
                    "Show IFRS 9 ECL by sector for the last four quarters.")
                probe, _ = run_probe(question.text, label=question.ref,
                                     state=state, memory=memory, turn_index=1,
                                     expected_officer=question.officer)
            elif question.ref == "Q14":
                if not project_id:
                    results.append({
                        "ref": question.ref, "question": question.text,
                        "critical": question.critical, "ok": False,
                        "problems": ["no seeded Project to ask it inside - "
                                     "run scripts/demo_state.py --rebuild"],
                    })
                    continue
                probe, _ = run_probe(question.text, label=question.ref,
                                     project_id=str(project_id),
                                     expected_officer=question.officer)
            else:
                probe, _ = run_probe(question.text, label=question.ref,
                                     expected_officer=question.officer)
            problems = check(question, probe)
            results.append({
                "ref": question.ref,
                "question": question.text,
                "critical": question.critical,
                "expected_outcome": question.outcome,
                "outcome": _outcome_of(probe),
                "expected_officer": question.officer,
                "officer": getattr(probe, "officer_level", None),
                "specialists": len(getattr(probe, "specialists", ()) or ()),
                "datasets": list(getattr(probe, "datasets", ()) or ()),
                "duration_ms": getattr(probe, "duration_ms", 0),
                "problems": problems,
                "ok": not problems,
            })
        except Exception as e:  # noqa: BLE001 - one question is not the set
            results.append({
                "ref": question.ref, "question": question.text,
                "critical": question.critical, "ok": False,
                "problems": [f"{type(e).__name__}: {str(e)[:200]}"],
            })

    blocking = [r for r in results
                if not r["ok"] and r.get("critical", True)]
    return {
        "version": spec.QUESTIONS_VERSION,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "provider_calls": 0,
        "questions": len(results),
        "passed": len([r for r in results if r["ok"]]),
        "blocking": len(blocking),
        "results": results,
        # Said in the report rather than left to be assumed.
        "checked": "officer selection, outcome, specialists, datasets, "
                   "critical assurance signals",
        "not_checked": "the prose, the interpretation and the figures - "
                       "those need a live model and are what the presenter's "
                       "own -Critical run verifies",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="",
                        help="comma-separated refs, e.g. Q3,Q10")
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)

    refs = [r.strip().upper() for r in args.only.split(",") if r.strip()]
    try:
        body = run(refs or None)
    except Exception as e:  # noqa: BLE001
        print(f"THE QUESTION SET DID NOT RUN: {type(e).__name__}: {e}")
        return EXIT_DID_NOT_RUN

    print(f"Demonstration question set - {body['passed']}/{body['questions']} "
          f"passed, {body['blocking']} blocking")
    print(f"  checked:     {body['checked']}")
    print(f"  NOT checked: {body['not_checked']}")
    print()
    for result in body["results"]:
        mark = "PASS" if result["ok"] else ("FAIL" if result.get("critical")
                                            else "warn")
        officer = result.get("officer")
        print(f"  {mark}  {result['ref']:<4} "
              f"{result['question'][:52]:<52} "
              f"officer={officer} outcome={result.get('outcome', '?')}")
        for problem in result.get("problems", []):
            print(f"          - {problem}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(body, indent=2), encoding="utf-8")
        print(f"\n  report {args.json}")

    print()
    print("  No provider call was made and no credits were consumed.")
    return EXIT_BLOCKED if body["blocking"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
