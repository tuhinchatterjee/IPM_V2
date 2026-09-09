"""How long the Metric Catalogue and the Lenses actually take.

Measured against a running backend over HTTP, signed in as a real analyst, so
what is timed is what a person waits for — not a function call with the
authentication, serialisation and connection handling taken out.

    .venv/bin/python scripts/acceptance/lens_performance.py
    .venv/bin/python scripts/acceptance/lens_performance.py --json --runs 10

What these numbers are NOT: a capacity claim. One process, one client, no
concurrency, synthetic data on local disk, in a sandbox whose CPU is shared.
They are useful for the thing they were written for — telling whether a change
made a screen slower — and for nothing else. The budgets below are what a
person notices, not what the hardware can do.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

API = os.environ.get("LENS_API", "http://127.0.0.1:8000")
WHO = os.environ.get("LENS_USER", "priya.raman")

#: What a person notices, in milliseconds. A typeahead that takes a fifth of a
#: second stops feeling like typing; a dashboard that takes four seconds gets
#: opened in another tab and forgotten.
BUDGETS = {
    "metric typeahead": 200,
    "the whole catalogue": 600,
    "one metric, calculated": 1500,
    "a shipped lens, rendered": 4000,
}

EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_CANNOT_RUN = 2


@dataclass
class Timing:
    name: str
    budget_ms: int
    samples: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float:
        return statistics.median(self.samples) if self.samples else float("nan")

    @property
    def p95(self) -> float:
        """The slow one, not the typical one.

        With few samples this is the near-worst observed rather than a real
        95th percentile, and is reported as such: a median alone hides the
        request that made somebody reload the page.
        """
        if not self.samples:
            return float("nan")
        ordered = sorted(self.samples)
        return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]

    @property
    def within(self) -> bool:
        return bool(self.samples) and self.p95 <= self.budget_ms

    def to_dict(self) -> dict[str, Any]:
        return {"what": self.name, "runs": len(self.samples),
                "p50_ms": round(self.p50, 1), "p95_ms": round(self.p95, 1),
                "budget_ms": self.budget_ms, "within_budget": self.within}


def _session() -> Any:
    import requests

    from backend.services.demo_users import DEMO_PASSWORD

    client = requests.Session()
    out = client.post(f"{API}/api/v1/auth/login",
                      json={"username": WHO, "password": DEMO_PASSWORD},
                      timeout=30)
    out.raise_for_status()
    return client


def _time(client: Any, url: str, runs: int) -> list[float]:
    """Milliseconds per request, discarding the first.

    The first call to any of these pays for a DuckDB connection and a cold
    catalogue read, which every later one does not. Reporting it in the median
    would say a screen is slower than anybody experiences it after the first
    person opens it.
    """
    samples: list[float] = []
    for index in range(runs + 1):
        started = time.perf_counter()
        out = client.get(f"{API}{url}", timeout=300)
        elapsed = (time.perf_counter() - started) * 1000
        out.raise_for_status()
        if index:
            samples.append(elapsed)
    return samples


def measure(runs: int = 5) -> tuple[list[Timing], str]:
    try:
        client = _session()
    except Exception as exc:  # noqa: BLE001
        return [], (f"Could not sign in to {API}: {exc}. Nothing was measured, "
                    "and nothing is claimed.")

    lenses = client.get(f"{API}/api/v1/lenses", timeout=60).json()["lenses"]
    shipped = [row for row in lenses
               if row["slug"] in ("corporate-ifrs9", "retail-credit-risk",
                                  "retail-analytics")]
    if not shipped:
        return [], ("The shipped lenses are not installed, so the render was "
                    "not measured.")

    timings = [
        Timing("metric typeahead", BUDGETS["metric typeahead"],
               _time(client, "/api/v1/metrics?q=delinq", runs)),
        Timing("the whole catalogue", BUDGETS["the whole catalogue"],
               _time(client, "/api/v1/metrics/all", runs)),
        Timing("one metric, calculated", BUDGETS["one metric, calculated"],
               _time(client, "/api/v1/metrics/corporate.npl_rate/value", runs)),
    ]
    for lens in shipped:
        timings.append(Timing(
            f"a shipped lens, rendered — {lens['slug']} "
            f"({len(lens.get('panels') or [])} tiles)",
            BUDGETS["a shipped lens, rendered"],
            _time(client, f"/api/v1/lenses/{lens['id']}/render", runs)))
    return timings, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args(argv)

    timings, problem = measure(runs=max(1, args.runs))

    if args.json:
        print(json.dumps({"measurements": [t.to_dict() for t in timings],
                          "problem": problem}, indent=2))
    else:
        if problem:
            print(f"! {problem}")
        for timing in timings:
            mark = "OK  " if timing.within else "SLOW"
            print(f"  [{mark}] {timing.name}\n"
                  f"         p50 {timing.p50:7.0f} ms   "
                  f"p95 {timing.p95:7.0f} ms   "
                  f"budget {timing.budget_ms} ms   "
                  f"({len(timing.samples)} runs)")
        print("\nOne process, one client, no concurrency, synthetic data on "
              "local disk.\nThese say whether a change made a screen slower. "
              "They are not a capacity claim.")

    if problem:
        return EXIT_CANNOT_RUN
    return EXIT_OK if all(t.within for t in timings) else EXIT_OVER_BUDGET


if __name__ == "__main__":
    raise SystemExit(main())
