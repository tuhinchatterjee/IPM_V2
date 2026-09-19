#!/usr/bin/env python3
"""Check the published projection against independently computed results.

    .venv/bin/python scripts/retail_cockpit/check_oracles.py

The oracle reads the RETAIL BOOK with pandas. The check reads the PUBLISHED
PROJECTION through the engine's own DuckDB session -- the same session, the
same catalogue and the same governance filter an answer would be computed
through. The two implementations meet only in the number.

A disagreement is printed with both sides and the tolerance it was compared
at, because "they differ" is not a finding anybody can act on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _close(a, b, tolerance) -> bool:
    if a is None or b is None:
        return a == b
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    return abs(float(a) - float(b)) <= float(tolerance)


def main() -> int:
    from backend.cockpit_v4 import catalog as cat
    from backend.retail_cockpit_adapter import oracle as orc
    from backend.retail_cockpit_adapter.source import open_snapshot

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analytics-dir", type=Path,
                    default=ROOT / "data" / "retail" / "analytics")
    ap.add_argument("--metadata-dir", type=Path,
                    default=ROOT / "metadata" / "retail")
    ap.add_argument("--tenant", default=None,
                    help="the tenant the release was stamped with")
    ap.add_argument("--release", default="",
                    help="a published release to check instead of the one "
                         "this runtime is configured for")
    ap.add_argument("--only", default="", help="one case id, e.g. Q01")
    args = ap.parse_args()

    from backend.cockpit_v4 import lake as lake_mod

    tenant = args.tenant or lake_mod.DEFAULT_TENANT
    snapshot = open_snapshot(args.analytics_dir, args.metadata_dir)
    catalog = cat.build(domain_id="retail", release_id=args.release,
                        tenant_id=tenant)
    session = cat.open_session(catalog=catalog)
    latest = catalog.calendar.latest
    previous = catalog.calendar.previous
    print(f"release  {catalog.dataset_release_id}")
    print(f"         fingerprint {catalog.release_fingerprint[:16]}")
    print(f"         {len(catalog.calendar.slots)} months to {latest}, "
          f"{catalog.reporting_currency} {catalog.amount_scale}")
    print(f"oracle   {snapshot.manifest['dataset_name']} "
          f"{snapshot.dataset_version} "
          f"(manifest {snapshot.manifest_hash[:16]})")
    print()

    cases = build_cases(latest, previous)
    if args.only:
        cases = {k: v for k, v in cases.items() if k == args.only}

    failures = 0
    for case_id, case in cases.items():
        expected = orc.ORACLES[case_id](snapshot)
        rows = session.connection.execute(case["sql"]).fetchall()
        names = [d[0] for d in session.connection.description]
        actual = [dict(zip(names, row, strict=True)) for row in rows]
        problems = case["compare"](expected, actual)
        status = "OK  " if not problems else "FAIL"
        print(f"{status} {case_id}  {expected.question}")
        print(f"       period {expected.period} · unit {expected.unit}")
        print(f"       denominator: {expected.denominator}")
        if problems:
            failures += 1
            for line in problems[:8]:
                print(f"         - {line}")
    print()
    print(f"{len(cases) - failures} of {len(cases)} cases agree with the "
          f"independent oracle.")
    return 1 if failures else 0


def build_cases(latest: str, previous: str) -> dict:
    """Each case: the engine-side SQL, and how the two sides are compared."""
    from backend.retail_cockpit_adapter import oracle as orc

    def by_key(keys, values):
        def compare(expected, actual):
            want = {tuple(str(r[k]) for k in keys): r
                    for r in expected.rows
                    if not any(str(r[k]).isupper() and not str(r[k]).isdigit()
                               and str(r[k]) in ("TOTAL", "TOTAL DISTINCT",
                                                 "ENTERED", "LEFT", "OPENING",
                                                 "CLOSING", "MOVEMENT",
                                                 "RESIDUAL")
                               for k in keys)}
            got = {tuple(str(r[k]) for k in keys): r for r in actual}
            problems = []
            for key in sorted(set(want) | set(got)):
                if key not in want:
                    problems.append(f"{key}: the engine returned a row the "
                                    f"oracle does not have")
                    continue
                if key not in got:
                    problems.append(f"{key}: the oracle expects a row the "
                                    f"engine did not return")
                    continue
                for column in values:
                    a, b = want[key][column], got[key][column]
                    # A riyal column is compared at the same absolute
                    # tolerance expressed in riyals. Comparing it at the
                    # millions tolerance would demand agreement to a ten
                    # millionth of a riyal, which is not a finding about
                    # the projection.
                    tolerance = (orc.RIYAL_TOLERANCE
                                 if column.endswith("_sar")
                                 else expected.tolerance)
                    if not _close(a, b, tolerance):
                        problems.append(
                            f"{key}.{column}: oracle {a!r} vs engine {b!r} "
                            f"(tolerance {tolerance})")
            return problems
        return compare

    return {
        "Q01": {
            "sql": f"""SELECT product, SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ead_sar) AS ead_sar,
                              COUNT(*) AS facilities
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY product""",
            "compare": by_key(("product",),
                              ("ead_sar_mn", "ead_sar", "facilities")),
        },
        "Q02": {
            "sql": f"""SELECT product,
                              COUNT(DISTINCT customer_id) AS customers,
                              COUNT(DISTINCT account_id) AS facilities
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY product""",
            "compare": by_key(("product",), ("customers", "facilities")),
        },
        "Q03": {
            # Coverage is computed from the RIYAL columns: it is a ratio of
            # two sums and must come out identical either way, which is the
            # point of checking it against an oracle that used neither.
            "sql": f"""SELECT product, stage,
                              SUM(ecl_sar_mn) AS ecl_sar_mn,
                              SUM(balance_sar_mn) AS gca_sar_mn,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(balance_sar) AS balance_sar,
                              SUM(ecl_sar) / NULLIF(SUM(balance_sar), 0)
                                  AS coverage,
                              COUNT(*) AS facilities
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY product, stage""",
            "compare": by_key(("product", "stage"),
                              ("ecl_sar_mn", "gca_sar_mn", "ecl_sar",
                               "balance_sar", "coverage", "facilities")),
        },
        "Q05": {
            "sql": f"""
             WITH live AS (
               SELECT product, reporting_month, COUNT(*) AS population,
                      SUM(CASE WHEN dpd_days BETWEEN 1 AND 29 THEN 1 ELSE 0 END)
                          AS early
               FROM retail_account_month
               WHERE reporting_month IN ('{latest}', '{previous}')
               GROUP BY product, reporting_month)
             SELECT n.product,
                    n.early AS current,
                    p.early AS prior,
                    n.early - p.early AS movement,
                    n.early::DOUBLE / NULLIF(n.population, 0)
                        AS current_share,
                    p.early::DOUBLE / NULLIF(p.population, 0) AS prior_share,
                    n.population AS current_population,
                    p.population AS prior_population
             FROM live n JOIN live p ON n.product = p.product
             WHERE n.reporting_month = '{latest}'
               AND p.reporting_month = '{previous}'""",
            "compare": by_key(("product",),
                              ("current", "prior", "movement",
                               "current_share", "prior_share",
                               "current_population", "prior_population")),
        },
        "Q16": {
            "sql": f"""SELECT b.stage AS from_stage, n.stage AS to_stage,
                              COUNT(*) AS facilities
                       FROM retail_account_month b
                       JOIN retail_account_month n
                         ON b.account_id = n.account_id
                       WHERE b.reporting_month = '{previous}'
                         AND n.reporting_month = '{latest}'
                       GROUP BY 1, 2""",
            "compare": by_key(("from_stage", "to_stage"), ("facilities",)),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
