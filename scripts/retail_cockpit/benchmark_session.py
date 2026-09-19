#!/usr/bin/env python3
"""What one analytical session costs, at each memory limit it could be given.

    .venv/bin/python scripts/retail_cockpit/benchmark_session.py \
        --limits 1536MB,2048MB,2560MB,3072MB

Runs ONE FRESH SUBPROCESS per limit, so a cold open is really cold and a peak
RSS is really that process's. Measures, per limit: cold session-open, warm
reopen, the materialised footprint, spill bytes, peak RSS, a simple
aggregation, a multi-relation diagnostic, and two questions asked at once on
the session the engine actually shares.

It changes nothing. It reads the published projection, opens sessions the way
the product opens them, and writes an evidence file.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: The evidence class the source's own performance files declare, so a reader
#: knows what a number here is worth.
EVIDENCE_CLASS = "NO MODEL · REAL DATABASE · REAL RELEASE"


def _stat(samples: list[float]) -> dict[str, float]:
    """The shape `test_dual_domain_performance.py` publishes."""
    if not samples:
        return {"samples": 0}
    ordered = sorted(samples)
    return {
        "samples": len(ordered),
        "min_ms": round(ordered[0], 3),
        "median_ms": round(ordered[len(ordered) // 2], 3),
        "p90_ms": round(ordered[round(0.9 * (len(ordered) - 1))], 3),
        "max_ms": round(ordered[-1], 3),
    }


def _directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


class SpillWatch:
    """Peak spill, sampled while the queries run.

    Spill files come and go inside one statement, so a reading taken after it
    finishes reports zero for a query that spilled a gigabyte. This samples.
    """

    def __init__(self, directory: Path, every: float = 0.05) -> None:
        self.directory = directory
        self.every = every
        self.peak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> SpillWatch:
        def sample() -> None:
            while not self._stop.is_set():
                self.peak = max(self.peak, _directory_bytes(self.directory))
                self._stop.wait(self.every)

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.peak = max(self.peak, _directory_bytes(self.directory))


SIMPLE_SQL = """
    SELECT product, SUM(ead_sar_mn) AS ead, COUNT(*) AS facilities
    FROM retail_account_month
    WHERE reporting_month = '{latest}'
    GROUP BY product
"""

#: A Q15-shaped question: what is behind Stage 2 and its allowance, read
#: across three relations and two months. The heaviest thing an analyst can
#: reasonably author against this book.
DIAGNOSTIC_SQL = """
    WITH now AS (
        SELECT a.account_id, a.customer_id, a.product, a.score_band, a.stage,
               a.ead_sar_mn, a.ecl_sar_mn, b.max_dpd_6m, b.bureau_score_change_3m
        FROM retail_account_month a
        JOIN retail_behaviour_month b
          ON a.account_id = b.account_id
         AND a.reporting_month = b.reporting_month
        WHERE a.reporting_month = '{latest}'),
    before AS (
        SELECT account_id, stage FROM retail_account_month
        WHERE reporting_month = '{previous}')
    SELECT n.product, n.score_band,
           COUNT(*) AS facilities,
           COUNT(DISTINCT n.customer_id) AS customers,
           SUM(n.ead_sar_mn) AS ead,
           SUM(n.ecl_sar_mn) AS ecl,
           AVG(n.max_dpd_6m) AS worst_dpd_6m,
           AVG(n.bureau_score_change_3m) AS bureau_move,
           SUM(CASE WHEN b.stage = 1 AND n.stage = 2 THEN 1 ELSE 0 END)
               AS entered_stage_2
    FROM now n
    LEFT JOIN before b ON n.account_id = b.account_id
    LEFT JOIN retail_customer_month c
           ON n.customer_id = c.customer_id
          AND c.reporting_month = '{latest}'
    GROUP BY n.product, n.score_band
    ORDER BY ead DESC
"""


def measure(limit: str, repeat: int, tenant: str) -> dict:
    """One limit, in this process. Printed as JSON for the parent."""
    from backend.cockpit_v4 import catalog as cat

    temp_dir = Path(cat._sql_temp_directory())
    for stale in temp_dir.glob("*"):
        if stale.is_file():
            stale.unlink()

    out: dict = {"limit": limit, "temp_directory": str(temp_dir)}

    with SpillWatch(temp_dir) as watch:
        started = time.perf_counter()
        catalog = cat.build(domain_id="retail", tenant_id=tenant)
        session = cat.open_session(catalog=catalog)
        out["cold_open_ms"] = round((time.perf_counter() - started) * 1000, 1)
    out["built_seconds"] = session.built_seconds
    out["spill_bytes_materialising"] = watch.peak

    connection = session.connection
    out["effective_limit"] = connection.execute(
        "SELECT current_setting('memory_limit')").fetchone()[0]
    out["effective_temp_directory"] = connection.execute(
        "SELECT current_setting('temp_directory')").fetchone()[0]
    out["materialised_mib"] = round(connection.execute(
        "SELECT coalesce(sum(memory_usage_bytes), 0) / 1024 / 1024 "
        "FROM duckdb_memory() WHERE tag = 'IN_MEMORY_TABLE'"
    ).fetchone()[0], 1)
    out["relations"] = list(session.relations)
    out["release_id"] = catalog.dataset_release_id

    started = time.perf_counter()
    cat.open_session(catalog=catalog)
    out["warm_reopen_ms"] = round((time.perf_counter() - started) * 1000, 3)

    latest = catalog.calendar.latest
    previous = catalog.calendar.previous
    simple = SIMPLE_SQL.format(latest=latest)
    diagnostic = DIAGNOSTIC_SQL.format(latest=latest, previous=previous)

    for label, sql in (("simple_aggregation", simple),
                       ("multi_relation_diagnostic", diagnostic)):
        samples: list[float] = []
        rows = 0
        with SpillWatch(temp_dir) as watch:
            for _ in range(repeat):
                started = time.perf_counter()
                rows = len(connection.execute(sql).fetchall())
                samples.append((time.perf_counter() - started) * 1000)
        out[label] = _stat(samples)
        out[label]["rows"] = rows
        out[f"spill_bytes_{label}"] = watch.peak

    out["concurrent_two_questions"] = _concurrent(connection, simple,
                                                  diagnostic, temp_dir)
    out["peak_rss_mib"] = round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out["python"] = ".".join(str(n) for n in sys.version_info[:3])
    return out


def _concurrent(connection, simple: str, diagnostic: str,
                temp_dir: Path) -> dict:
    """Two questions at once, on the ONE connection the engine shares.

    Not a stress test: it is the shape the product already has. One worker
    thread serves runs and the API threads compute the attention and ECL
    panels on the same cached session, so two statements can genuinely be in
    flight on one connection. What happens then is worth recording rather
    than assuming.
    """
    results: dict[str, dict] = {}

    def ask(name: str, sql: str) -> None:
        started = time.perf_counter()
        try:
            rows = len(connection.execute(sql).fetchall())
            results[name] = {"ms": round((time.perf_counter() - started) * 1000, 1),
                             "rows": rows, "error": ""}
        except Exception as exc:  # noqa: BLE001 - the finding IS the exception
            results[name] = {
                "ms": round((time.perf_counter() - started) * 1000, 1),
                "rows": 0, "error": f"{type(exc).__name__}: {exc}"[:300]}

    with SpillWatch(temp_dir) as watch:
        threads = [threading.Thread(target=ask, args=("simple", simple)),
                   threading.Thread(target=ask, args=("diagnostic", diagnostic))]
        started = time.perf_counter()
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        wall = round((time.perf_counter() - started) * 1000, 1)
    return {"wall_ms": wall, "spill_bytes": watch.peak, **results}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limits", default="1536MB,2048MB,2560MB,3072MB")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--tenant", default="demo-tenant")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "docs" / "retail_cockpit" / "evidence"
                    / "session_memory_benchmark.json")
    ap.add_argument("--child", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.child:
        print(json.dumps(measure(args.child, args.repeat, args.tenant)))
        return 0

    limits = [x.strip() for x in args.limits.split(",") if x.strip()]
    runs = []
    for limit in limits:
        print(f"  {limit} ...", flush=True)
        environment = dict(os.environ)
        environment["COCKPIT_V4_SQL_MEMORY_LIMIT"] = limit
        finished = subprocess.run(
            [sys.executable, str(Path(__file__)), "--child", limit,
             "--repeat", str(args.repeat), "--tenant", args.tenant],
            capture_output=True, text=True, env=environment, cwd=str(ROOT))
        if finished.returncode != 0:
            print(finished.stdout[-2000:])
            print(finished.stderr[-2000:])
            return 1
        run = json.loads(finished.stdout.strip().splitlines()[-1])
        runs.append(run)
        print(f"     cold {run['cold_open_ms'] / 1000:6.1f}s  "
              f"materialised {run['materialised_mib']:7.0f} MiB  "
              f"spill {run['spill_bytes_materialising'] / 1024 / 1024:7.0f} MiB  "
              f"RSS {run['peak_rss_mib']:7.0f} MiB  "
              f"simple {run['simple_aggregation']['median_ms']:6.1f} ms  "
              f"diagnostic {run['multi_relation_diagnostic']['median_ms']:7.1f} ms")

    payload = {
        "evidence_class": EVIDENCE_CLASS,
        "paid_provider_calls": 0,
        "what_is_measured": (
            "One analytical session over the projected Cockpit Data book, at "
            "each memory limit, in a fresh process: cold open, warm reopen, "
            "materialised footprint, spill, peak RSS, a simple aggregation, a "
            "multi-relation diagnostic, and two questions issued at once on "
            "the one connection the engine shares."),
        "what_is_not_measured": (
            "Provider latency, answer quality, and anything about the machine "
            "this did not run on. Peak RSS is this process only: the retail "
            "API, the frontend dev server and a browser are not in it."),
        "ported_budgets_ms": {
            "session_cold_open (test_dual_domain_performance.py)": 6000.0,
            "session_open (test_performance_gates.py)": 5000.0,
        },
        "machine": _machine(),
        "runs": runs,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  wrote {args.out}")
    return 0


def _machine() -> dict:
    out: dict = {"python": ".".join(str(n) for n in sys.version_info[:3]),
                 "platform": sys.platform}
    try:
        out["cpus"] = os.cpu_count()
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(("MemTotal", "MemAvailable")):
                    key, value = line.split(":", 1)
                    out[key.lower()] = value.strip()
    except OSError:
        pass
    return out


if __name__ == "__main__":
    raise SystemExit(main())
