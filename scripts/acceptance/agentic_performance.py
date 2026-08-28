"""
§78's performance measurement for the governed agentic layer.

Measured against the real demonstration universe and a real PostgreSQL. No
model is called anywhere in this script (§83), which is itself one of the
numbers being reported: the proactive review's expensive half is a funnel, and
the funnel's cost is what makes a whole-book review affordable at all.

    python scripts/acceptance/agentic_performance.py

Prints a table and exits non-zero if a budget is exceeded.
"""

from __future__ import annotations

import os
import statistics
import sys
import time

os.environ.setdefault("REQUIRE_LOGIN", "false")

#: What each step is allowed to take, in seconds. Ceilings rather than targets:
#: a number that only ever passes on a fast morning is not a budget.
BUDGETS: dict[str, float] = {
    "officer selection (no I/O)": 0.01,
    "officer preview endpoint": 0.50,
    "agent registry": 0.05,
    "evaluation corpus (56 cases)": 2.00,
    "deterministic pre-screen (whole book)": 30.00,
    "risk case listing": 0.50,
    "agentic runs listing": 0.50,
}

results: list[tuple[str, float, float, bool]] = []


def measure(name: str, work, *, repeat: int = 3) -> float:
    times: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        work()
        times.append(time.perf_counter() - started)
    took = statistics.median(times)
    budget = BUDGETS.get(name, 0.0)
    ok = took <= budget if budget else True
    results.append((name, took, budget, ok))
    print(f"  {'OK  ' if ok else 'SLOW'}  {name:<40} "
          f"{took * 1000:8.1f} ms   (budget {budget * 1000:.0f} ms)",
          flush=True)
    return took


def main() -> int:
    from backend.agentic import officers, registry

    print("\nGoverned agentic layer — §78 performance\n")

    # --- the officer, which runs on every single question ------------------
    measure("officer selection (no I/O)",
            lambda: officers.select(
                "Why did expected credit loss rise in Contracting?",
                agents=1, tasks=0),
            repeat=200)

    measure("agent registry", lambda: registry.catalogue(), repeat=20)

    # --- the corpus, which the Evaluations tab runs on request -------------
    from backend.agentic import evaluation

    measure("evaluation corpus (56 cases)",
            lambda: evaluation.run(tier=evaluation.CERTIFICATION), repeat=3)

    # --- the API surfaces the screens read --------------------------------
    from fastapi.testclient import TestClient

    from backend.api.main import app

    client = TestClient(app)
    admin = {"X-IPM-Role": "ADMIN", "X-IPM-User-Id": "1"}

    measure("officer preview endpoint",
            lambda: client.post("/api/v1/agentic/officer", headers=admin,
                                json={"question": "What is total ECL?"}),
            repeat=10)
    measure("risk case listing",
            lambda: client.get("/api/v1/risk-cases", headers=admin), repeat=10)
    measure("agentic runs listing",
            lambda: client.get("/api/v1/agentic/runs", headers=admin),
            repeat=10)

    # --- the funnel, which is the whole cost argument ----------------------
    from backend.agentic import events, screening

    period = events.latest_period()
    if period:
        screen = None

        def run_screen() -> None:
            nonlocal screen
            screen = screening.run(period)

        measure("deterministic pre-screen (whole book)", run_screen, repeat=1)
        if screen is not None:
            funnel = screen.funnel()
            print(f"\n  Funnel at {period}: "
                  f"{funnel['rows_screened']:,} rows screened → "
                  f"{funnel['segments_material']} material segment(s) → "
                  f"{funnel['borrowers_escalated']} borrower(s), "
                  f"{funnel['model_calls']} model calls.")
            print(f"  {funnel['reduction']}")
            if funnel["model_calls"] != 0:
                print("  FAIL: §36 requires the pre-screen to call no model.")
                results.append(("pre-screen model calls", 1, 0, False))
    else:
        print("  skipped: no published period in this environment")

    slow = [r for r in results if not r[3]]
    print(f"\n{len(results) - len(slow)} within budget, {len(slow)} over.")
    for name, took, budget, _ in slow:
        print(f"  - {name}: {took * 1000:.0f} ms over a {budget * 1000:.0f} ms "
              f"budget")
    return 1 if slow else 0


if __name__ == "__main__":
    sys.exit(main())
