"""§48 — what the feedback and learning layer costs at run time.

The question this answers is narrow and the only one that matters for a
client: **does recording feedback and observations slow down an answer?**

Everything here runs offline and makes no provider call. The figures are
therefore about CreditProbe's own work, not about the model's latency, which
is the larger and more variable number and is not what this phase added.

    python scripts/learning_performance.py
    python scripts/learning_performance.py --json docs/learning_performance.json

Read the two numbers that matter first:

* the observation written on the answer path — this is the only cost a user
  can experience, because it happens before the answer is handed back;
* the guard scan — this is the slowest thing in the module by two orders of
  magnitude, and it deliberately never runs on the answer path.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: How many times each measurement runs. Enough for a median to mean
#: something and few enough that the whole script stays under a minute.
REPEATS = 200

#: Measurements that walk the file system are far slower and do not need the
#: same sample size to be distinguishable from the rest.
SLOW_REPEATS = 5


def _time(work: Callable[[], Any], repeats: int) -> dict[str, float]:
    """Median and worst of `repeats` runs, in milliseconds.

    Median rather than mean: one scheduling hiccup in two hundred runs moves a
    mean and says nothing about what a user experiences. The worst case is
    reported beside it rather than hidden, because a p50 alone is how a
    pathological outlier stays invisible.
    """
    work()  # warm the imports and any cache, which is not what is measured
    taken: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        work()
        taken.append((time.perf_counter() - started) * 1000)
    taken.sort()
    return {
        "median_ms": round(statistics.median(taken), 4),
        "worst_ms": round(taken[-1], 4),
        "runs": repeats,
    }


def _persisted(made: Any) -> list[dict[str, Any]]:
    """The observation write, against the real database.

    This is the figure that decides whether the feature is affordable, and it
    is the one an in-memory benchmark would have quietly left out. Skipped
    rather than faked when no database is reachable, and the report says so:
    a performance claim measured against nothing is worse than no claim.
    """
    try:
        from backend.db.engine import get_session
        from backend.services import learning as ls
    except Exception:  # noqa: BLE001
        return [{"name": "writing the observation", "on_answer_path": True,
                 "what": "NOT MEASURED - the platform database is not "
                         "reachable from here.",
                 "median_ms": 0.0, "worst_ms": 0.0, "runs": 0}]

    def write() -> Any:
        with get_session() as session:
            ls.record_observation(session, made)
            session.flush()
            session.rollback()

    try:
        timing = _time(write, SLOW_REPEATS * 4)
    except Exception as e:  # noqa: BLE001 - an absent database is not a lie
        return [{"name": "writing the observation", "on_answer_path": True,
                 "what": f"NOT MEASURED - {type(e).__name__}.",
                 "median_ms": 0.0, "worst_ms": 0.0, "runs": 0}]
    return [{
        "name": "writing the observation",
        "on_answer_path": True,
        "what": "Persisting the observation before the answer is handed "
                "back. The real cost of §12, against the real database.",
        **timing,
    }]


def _measurements() -> list[dict[str, Any]]:
    from backend.learning import candidate as cd
    from backend.learning import feedback as fb
    from backend.learning import guard as gd
    from backend.learning import observation as ob
    from backend.learning import preference as pr

    class _Reading:
        capability = "ANALYSIS"
        concepts = ("expected_credit_loss",)
        datasets = ("facility",)
        officer_level = 1

    class _Answered:
        answered = True
        reading = _Reading()
        plan_fingerprint = "f" * 16
        datasets = ["facility"]
        assurance_status = "PASSED"

    answered = _Answered()

    def observation() -> Any:
        return ob.observe(answered, question="What is total EAD by sector?",
                          user_id="1", tenant="demo")

    made = observation()

    def event() -> Any:
        return fb.FeedbackEvent(
            answer_id="a-1", question="What is total EAD by sector?",
            rating=fb.NO, categories=["wrong_period"],
            correction=fb.Correction(
                conclusion="It should have been the prior quarter.",
                preferred_period="Q3"),
            consent=fb.CONSENT_GRANTED,
            # Without these a candidate is refused: an answer nobody can
            # reproduce is not something a reviewer can validate.
            build_sha="0" * 40, plan_fingerprint="f" * 16)

    given = event()

    return [
        {
            "name": "the prompt decision",
            "on_answer_path": True,
            "what": "Whether to show the accuracy prompt, and why not.",
            **_time(lambda: fb.placement(complete=True), REPEATS),
        },
        {
            "name": "building an observation",
            "on_answer_path": True,
            "what": "Every question becomes a learning observation. This is "
                    "the only cost a user can experience.",
            **_time(observation, REPEATS),
        },
        {
            "name": "recording a rating",
            "on_answer_path": False,
            "what": "Constructing the feedback event a user's answer becomes.",
            **_time(event, REPEATS),
        },
        {
            "name": "labelling an observation",
            "on_answer_path": False,
            "what": "Attaching a rating to the observation it belongs to.",
            **_time(lambda: ob.label(made, given), REPEATS),
        },
        {
            "name": "proposing a candidate",
            "on_answer_path": False,
            "what": "Turning a correction into a candidate learning case.",
            **_time(lambda: cd.propose(given, made), REPEATS),
        },
        {
            "name": "applying a preference",
            "on_answer_path": False,
            "what": "A user changing one of the eight settings.",
            **_time(lambda: pr.apply(pr.Preference(user_id="1"),
                                     "answer_length", "brief"), REPEATS),
        },
        *_persisted(made),
        {
            "name": "the raw-feedback guard scan",
            "on_answer_path": False,
            "what": "A static scan of every feedback module. Runs in CI and "
                    "in -FeedbackCritical. Never on the answer path.",
            **_time(gd.report, SLOW_REPEATS),
        },
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", default="",
                        help="Also write the measurements to this path.")
    args = parser.parse_args(argv)

    # Answer-path first, because that is the half a user can feel and the
    # half a reader should reach before anything else.
    rows = sorted(_measurements(), key=lambda r: not r["on_answer_path"])
    on_path = [r for r in rows if r["on_answer_path"]]
    total = round(sum(r["median_ms"] for r in on_path), 4)

    width = max(len(r["name"]) for r in rows)
    print("CreditProbe feedback and learning - run-time cost")
    print(f"  {'':<{width}}   median      worst   on answer path")
    for row in rows:
        mark = "yes" if row["on_answer_path"] else "no"
        print(f"  {row['name']:<{width}}  {row['median_ms']:>7.4f}ms "
              f"{row['worst_ms']:>8.4f}ms   {mark}")
    print()
    print(f"  Added to an answer, in total: {total:.4f}ms")
    print("  No provider call was made and no credits were consumed.")

    if args.json:
        payload = {
            "measurements": rows,
            "answer_path_total_ms": total,
            "repeats": REPEATS,
            "slow_repeats": SLOW_REPEATS,
            "provider_calls": 0,
        }
        Path(args.json).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"  written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
