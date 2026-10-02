#!/usr/bin/env python3
"""Performance smoke: p50/p95 latency of the guided workspace's main reads
against a RUNNING API (the stub runtime the browser suite uses).

    python3 scripts/guided_workspace/perf_smoke.py \\
        --api http://127.0.0.1:8444 --n 20 --out perf_smoke.json

Measured on this machine, warm, one client at a time: a smoke for gross
regressions, not a capacity test and not a Mac measurement.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request

WS = "/api/v1/cockpit-v4/workspace"


def _call(api: str, method: str, path: str, body: dict | None) -> float:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{api}{WS}{path}", data=data, method=method,
                                 headers={"content-type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        r.read()
        if r.status >= 400:
            raise RuntimeError(f"{method} {path}: {r.status}")
    return (time.perf_counter() - started) * 1000


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="http://127.0.0.1:8444")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    issues = json.loads(urllib.request.urlopen(
        f"{args.api}{WS}/issues?domain=corporate", timeout=120).read())
    issue = issues["issues"][0]["issue_id"]
    cases = [
        ("issues feed (corporate)", "GET", "/issues?domain=corporate", None),
        ("issue detail", "GET", f"/issues/{issue}", None),
        ("grid page (50 rows)", "POST", "/grid/query", {"limit": 50}),
        ("grid filtered + summary", "POST", "/grid/query", {
            "filters": [{"column": "sector", "op": "in",
                         "values": ["Construction"]}], "limit": 50}),
        ("selection summary", "POST", "/whatif/selection/summary", {
            "domain": "corporate", "selection": {"mode": "filtered",
                                                 "filters": [{
                                                     "column": "stage",
                                                     "op": "in",
                                                     "values": [2]}]}}),
        ("scenario library", "GET", "/scenarios", None),
        ("scenario preview (template)", "POST",
         "/scenarios/scn-tpl-corp-01/preview", {}),
        ("lens render (lens-02)", "POST", "/lenses/lens-02/render", {}),
        ("monitoring centre", "GET", "/monitoring?view=all", None),
        ("metric catalogue", "GET", "/metrics", None),
        ("messages", "GET", "/messages", None),
    ]
    rows = []
    for name, method, path, body in cases:
        _call(args.api, method, path, body)  # warm
        samples = sorted(_call(args.api, method, path, body)
                         for _ in range(args.n))
        rows.append({"endpoint": name, "request": f"{method} {path}",
                     "n": args.n,
                     "p50_ms": round(statistics.median(samples), 1),
                     "p95_ms": round(samples[max(0, int(0.95 * len(samples))
                                             - 1)], 1),
                     "max_ms": round(samples[-1], 1)})
        print(f"{name:32s} p50 {rows[-1]['p50_ms']:8.1f} ms  "
              f"p95 {rows[-1]['p95_ms']:8.1f} ms")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"api": args.api, "note": "warm, sequential, this machine; "
                   "smoke only", "rows": rows}, f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
