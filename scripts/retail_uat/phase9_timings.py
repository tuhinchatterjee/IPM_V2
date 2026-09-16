"""§27: what the demonstration path actually costs, cold and warm.

Cold and warm are different questions
--------------------------------------
Cold is the first reader after a restart: nothing is cached, the parquet has
not been parsed, the challenger has not been unpickled. Warm is every reader
after them. A product measured only warm reports a number no presenter ever
sees, because the presenter IS the first reader; one measured only cold
reports a number that never happens twice.

So each step is timed twice from a freshly restarted backend: once as the
first call of its kind, and once immediately after.

Nothing here is a browser measurement. A dev-server compile is not the
product, and including it would make the numbers meaningless on a machine
where the route happened to be compiled already.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BACKEND = os.environ.get("RETAIL_BACKEND", "http://localhost:8328") + "/api/v1"
OUT = "docs/evidence/phase9_timings"
os.makedirs(OUT, exist_ok=True)

#: What the contract expects each step to cost, warm. A budget, not a
#: measurement: it is here so a regression is visible as a regression rather
#: than as a number somebody has to remember.
BUDGET_S: dict[str, float] = {
    "cockpit attention cards": 3.0,
    "an investigation's first answer": 15.0,
    "the trait inventory": 12.0,
    "a What-If baseline": 5.0,
    "a Delta scenario": 20.0,
    "an XGBoost scenario": 20.0,
    "the challenger model card": 2.0,
    "a product lens, 18 tiles": 10.0,
    "the validation overview": 3.0,
    "the early-warning panel": 12.0,
}


def _open() -> object:
    jar = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar))
    opener.open(urllib.request.Request(
        BACKEND + "/auth/login",
        data=json.dumps({"username": os.environ.get("DEMO_USER",
                                                    "retail.demo"),
                         "password": os.environ.get("DEMO_PASSWORD",
                                                    "RetailDemo!2026")}
                        ).encode(),
        headers={"content-type": "application/json"}), timeout=60)
    return opener


def _time(opener, method: str, path: str, body: dict | None = None) -> float:
    request = urllib.request.Request(
        BACKEND + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"}, method=method)
    started = time.time()
    try:
        opener.open(request, timeout=600).read()
    except urllib.error.HTTPError as problem:
        problem.read()
        return -float(problem.code)
    except Exception:  # noqa: BLE001
        return -1.0
    return time.time() - started


#: How long the startup warm-up may take before the timings are read.
#:
#: The product warms the expensive answers on a daemon thread: the
#: early-warning panel, the trends every seeded dashboard reads, and the §7
#: trait analysis. Measuring "cold" halfway through that measures the race,
#: not the product — so the suite waits for the warm-up to finish and then
#: reports cold as "the first call after a restart, with the warm-up done",
#: which is what the presenter's first click actually is.
WARM_UP_S = 600
WARMED = "trait analysis warmed"
BACKEND_LOG = "/tmp/retail-backend.log"


def _wait_for_warm_up() -> float:
    started = time.time()
    while time.time() - started < WARM_UP_S:
        try:
            with open(BACKEND_LOG) as handle:
                if WARMED in handle.read():
                    return time.time() - started
        except OSError:
            pass
        time.sleep(5)
    return -1.0


def main() -> int:
    subprocess.run(["bash", "scripts/retail_uat/restart_backend.sh"],
                   check=False, capture_output=True)
    waited = _wait_for_warm_up()
    print(f"startup warm-up: "
          + (f"{waited:.0f}s" if waited >= 0
             else f"did not finish within {WARM_UP_S}s"), flush=True)
    opener = _open()

    # The ids a step needs, fetched before timing so the fetch is not in it.
    lenses = json.loads(opener.open(BACKEND + "/lenses", timeout=300).read())
    rows = lenses if isinstance(lenses, list) else (
        lenses.get("lenses") or lenses.get("items") or [])
    lens = next((one for one in rows
                 if str(one.get("slug") or "") == "retail-credit-card"),
                rows[0] if rows else {})
    thread = json.loads(opener.open(urllib.request.Request(
        BACKEND + "/retail/whatif/threads",
        data=json.dumps({"question": "Stress the credit card book"}).encode(),
        headers={"content-type": "application/json"}), timeout=600).read())
    thread_id = thread["thread_id"]
    opener.open(urllib.request.Request(
        BACKEND + f"/retail/whatif/threads/{thread_id}/method",
        data=json.dumps({"method": "delta"}).encode(),
        headers={"content-type": "application/json"}), timeout=300).read()

    steps: list[tuple[str, str, str, dict | None]] = [
        ("cockpit attention cards", "GET", "/risk-cases", None),
        ("an investigation's first answer", "POST", "/ask",
         {"question": "Show retail exposure, customers and weighted ECL by "
                      "product."}),
        ("the trait inventory", "POST", "/ask",
         {"question": "Tell me what customer traits have deteriorated and "
                      "what is the impact on ECL because of them."}),
        ("a What-If baseline", "GET", "/retail/whatif/landing", None),
        ("a Delta scenario", "POST",
         f"/retail/whatif/threads/{thread_id}/ask",
         {"said": "Increase PD by 10%", "method": "delta"}),
        ("an XGBoost scenario", "POST",
         f"/retail/whatif/threads/{thread_id}/ask",
         {"said": "Increase LGD by 5%", "method": "xgboost"}),
        ("the challenger model card", "GET",
         "/retail/whatif/models/challenger", None),
        ("a product lens, 18 tiles", "GET",
         f"/lenses/{lens.get('id')}/render", None),
        ("the validation overview", "GET",
         "/scorecard-validation/overview", None),
        ("the early-warning panel", "GET", "/retail/ews/portfolio", None),
    ]

    print(f"{'step':34s} {'cold':>9s} {'warm':>9s} {'budget':>8s}", flush=True)
    measured: list[dict] = []
    over: list[str] = []
    for name, method, path, body in steps:
        cold = _time(opener, method, path, body)
        warm = _time(opener, method, path, body)
        budget = BUDGET_S.get(name, 0.0)
        # A negative reading is an HTTP status, not a duration.
        ok = warm >= 0 and (not budget or warm <= budget)
        if not ok:
            over.append(f"{name}: "
                        + (f"HTTP {int(-warm)}" if warm < 0
                           else f"{warm:.1f}s against a {budget:.0f}s budget"))
        print(f"{name:34s} {cold:8.2f}s {warm:8.2f}s {budget:7.0f}s"
              + ("" if ok else "   OVER"), flush=True)
        measured.append({"step": name, "cold_s": round(cold, 2),
                         "warm_s": round(warm, 2), "budget_s": budget,
                         "within_budget": ok})

    with open(f"{OUT}/result.json", "w") as handle:
        json.dump({"steps": measured, "over_budget": over}, handle, indent=2)
    print()
    if over:
        print("Over budget:")
        for one in over:
            print(f"  {one}")
        return 1
    print("Every step is inside its budget, warm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
