"""
How long What-If actually takes, measured rather than asserted.

Why this is a script and not a test
------------------------------------
A timing assertion in a test suite is a flake generator: it fails on a busy
machine and passes on a quiet one, and the number it guards is never the number
anybody wanted to know. What is genuinely useful is a MEASUREMENT, taken on a
named machine against a named book, that somebody can compare against the last
one.

So this prints a table and writes it to `docs/whatif_performance.json`. The
budget column is the point at which an interaction stops feeling like an
answer and starts feeling like a job, and a row over it is reported as OVER
rather than failed.

Run:  uv run python scripts/whatif_performance.py
"""

from __future__ import annotations

import json
import pathlib
import statistics
import sys
import time
from collections.abc import Callable
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.whatif import comparison as cp  # noqa: E402
from backend.whatif import domain as dm  # noqa: E402
from backend.whatif import macrolab as ml  # noqa: E402
from backend.whatif import methodology as me  # noqa: E402
from backend.whatif import plausibility as pl  # noqa: E402
from backend.whatif import run as rn  # noqa: E402
from backend.whatif import scenarios as sc  # noqa: E402
from backend.whatif import steps as sp  # noqa: E402
from backend.whatif import workbook as wb  # noqa: E402

#: Where an interaction stops feeling like an answer, in seconds. These are
#: product judgements, not machine limits: a person waits for an export and
#: does not wait for a chat reply.
BUDGET: dict[str, float] = {
    "read the book (cold)": 8.0,
    "read the book (warm)": 1.0,
    "price a scenario — Delta": 3.0,
    "price a scenario — ML": 6.0,
    "attribution (5 shocks)": 6.0,
    "plausibility (cold)": 8.0,
    "plausibility (warm)": 1.0,
    "macro fit": 5.0,
    "both methodologies": 10.0,
    "detailed workbook": 30.0,
}

REPEATS = 3


def timed(what: str, fn: Callable[[], Any], *, repeats: int = REPEATS
          ) -> dict[str, Any]:
    runs: list[float] = []
    for _ in range(repeats):
        start = time.monotonic()
        fn()
        runs.append(time.monotonic() - start)
    budget = BUDGET.get(what, 0.0)
    median = statistics.median(runs)
    return {"what": what, "runs": [round(r, 3) for r in runs],
            "median": round(median, 3), "best": round(min(runs), 3),
            "worst": round(max(runs), 3), "budget": budget,
            "status": "OVER" if budget and median > budget else "ok"}


def main() -> int:
    period = dm.latest_period()

    def state(*steps: sp.Step) -> sp.ScenarioState:
        body = sp.ScenarioState(period=period)
        for step in steps:
            body = body.add(step)
        return body

    pd_up = sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    interpreted="PD +20%")
    five = state(
        sp.Step(sp.RATING, (sc.Shock(sc.RATING, 1.0, sc.NOTCHES),),
                interpreted="down 1 notch"),
        pd_up,
        sp.Step(sp.LGD, (sc.Shock(sc.LGD, 5.0, sc.ABSOLUTE_PP),),
                interpreted="LGD +5pp"),
        sp.Step(sp.EAD, (sc.Shock(sc.EAD, 10.0, sc.RELATIVE),),
                interpreted="EAD +10%"),
        sp.Step(sp.MACRO,
                (sc.Shock(sc.MACRO, -1.0, sc.ABSOLUTE_PP, target="gdp_growth"),),
                interpreted="GDP -1pp"))
    one = state(pd_up)

    rows: list[dict[str, Any]] = []

    dm.reset_cache()
    rows.append(timed("read the book (cold)", lambda: dm.book(period),
                      repeats=1))
    rows.append(timed("read the book (warm)", lambda: dm.book(period)))

    rows.append(timed("price a scenario — Delta",
                      lambda: rn.execute(one, requested=me.DELTA,
                                         plausible=False)))
    try:
        rows.append(timed("price a scenario — ML",
                          lambda: rn.execute(one, requested=me.ML,
                                             plausible=False)))
    except Exception as e:  # noqa: BLE001
        rows.append({"what": "price a scenario — ML", "status": "skipped",
                     "why": str(e)[:200]})

    rows.append(timed("attribution (5 shocks)",
                      lambda: rn.execute(five, requested=me.DELTA,
                                         plausible=False)))

    pl.reset_cache()
    rows.append(timed("plausibility (cold)", lambda: pl.assess(one),
                      repeats=1))
    rows.append(timed("plausibility (warm)", lambda: pl.assess(one)))

    rows.append(timed("macro fit", lambda: ml.estimate("gdp_growth"),
                      repeats=2))
    rows.append(timed("both methodologies", lambda: cp.compare(one),
                      repeats=2))

    priced = rn.execute(one, requested=me.DELTA)
    rows.append(timed("detailed workbook", lambda: wb.build(priced),
                      repeats=2))

    print(f'{"what":30s} {"median":>8s} {"best":>8s} {"worst":>8s} '
          f'{"budget":>8s}  status')
    for row in rows:
        if row.get("status") == "skipped":
            print(f'{row["what"]:30s} {"—":>8s} {"—":>8s} {"—":>8s} '
                  f'{"—":>8s}  skipped: {row.get("why", "")[:40]}')
            continue
        print(f'{row["what"]:30s} {row["median"]:>8.2f} {row["best"]:>8.2f} '
              f'{row["worst"]:>8.2f} {row["budget"]:>8.1f}  {row["status"]}')

    over = [r for r in rows if r.get("status") == "OVER"]
    body = {
        "version": "1.0.0",
        "period": period,
        "borrowers": priced.population,
        "repeats": REPEATS,
        "measurements": rows,
        "over_budget": [r["what"] for r in over],
        "statement": (
            "Measured on the machine that ran it, against the book that "
            "installation carries. A budget is the point at which an "
            "interaction stops feeling like an answer, not a machine limit, "
            "and a row over it is reported rather than failed."),
    }
    out = pathlib.Path(__file__).resolve().parent.parent / "docs"
    out.mkdir(exist_ok=True)
    (out / "whatif_performance.json").write_text(
        json.dumps(body, indent=1) + "\n")
    print(f'\nWrote {out / "whatif_performance.json"}')
    if over:
        print("OVER BUDGET: " + ", ".join(r["what"] for r in over))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
