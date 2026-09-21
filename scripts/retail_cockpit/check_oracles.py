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
import os
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


def _check_live():
    """`check_live.py`, loaded by path -- `scripts/` is not a package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_check_live", ROOT / "scripts" / "retail_cockpit" / "check_live.py")
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise SystemExit("check_live.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analytics-dir", type=Path, default=None)
    ap.add_argument("--metadata-dir", type=Path, default=None)
    ap.add_argument("--env-file", default=str(ROOT / ".env.retail-candidate"),
                    help="the candidate configuration to resolve before "
                         "reading anything. Pass '' to use this shell.")
    ap.add_argument("--tenant", default=None,
                    help="the tenant the release was stamped with")
    ap.add_argument("--release", default="",
                    help="a published release to check instead of the one "
                         "this runtime is configured for")
    ap.add_argument("--only", default="", help="one case id, e.g. Q01")
    args = ap.parse_args()

    # BEFORE THE BACKEND IMPORTS, and before the directories are chosen.
    # `settings` is frozen at `backend.config` import and `lake.root()` is
    # derived from it, so a later resolution would compare the candidate's
    # oracle against a release read from a different lake. The defaults below
    # used to be `ROOT/data/retail/analytics` unconditionally -- the
    # installation's path, which a candidate clone does not have -- so this
    # step could only ever run with the flags passed by hand.
    check_live = _check_live()
    resolved = check_live.apply_environment(args.env_file)
    if args.env_file and not resolved:
        print(f"  note: {args.env_file} does not exist; reading this shell "
              f"as it stands.")

    from backend.cockpit_v4 import catalog as cat
    from backend.cockpit_v4 import lake as lake_mod
    from backend.retail_cockpit_adapter import oracle as orc
    from backend.retail_cockpit_adapter.source import open_snapshot

    analytics = args.analytics_dir or Path(check_live.anchored(
        os.environ.get("DATA_ANALYTICS_DIR")
        or str(ROOT / "data" / "retail" / "analytics")))
    metadata = args.metadata_dir or Path(check_live.anchored(
        os.environ.get("METADATA_DIR")
        or str(ROOT / "metadata" / "retail")))

    tenant = args.tenant or lake_mod.DEFAULT_TENANT
    snapshot = open_snapshot(analytics, metadata)

    # `open_snapshot` validates the MANIFEST and nothing else, so a book
    # whose metadata resolves and whose parquet does not opens cleanly and
    # fails at the first read. That is how a live UAT crashed after paying
    # for an answer. `verify()` is the adapter's own check and had exactly
    # one caller in the repository: the publisher.
    findings = snapshot.verify()
    if findings:
        print(f"The source book at {analytics} cannot be read:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print(f"source book  {analytics}  "
          f"({len(snapshot.months)} months, latest {snapshot.latest_period})")
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

    cases = build_cases(latest, previous,
                        tuple(catalog.calendar.slots))
    if args.only:
        cases = {k: v for k, v in cases.items() if k == args.only}

    failures = 0
    for case_id, case in cases.items():
        expected = orc.ORACLES[case_id](snapshot)
        if "panel" in case:
            actual = case["panel"](session, catalog)
        else:
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


def _ecl_movement(session, catalog) -> list:
    """The ECL panel's own attribution, in the oracle's shape."""
    from backend.cockpit_v4 import domain_resolver
    from backend.cockpit_v4 import ecl as ecl_mod

    scope = domain_resolver.scope_for(
        catalog.domain_id, tenant_id=catalog.tenant_id,
        release_id=catalog.dataset_release_id)
    movement = ecl_mod.decompose(session=session, scope=scope)
    # The attributed components only. OPENING, CLOSING, MOVEMENT and
    # RESIDUAL are reconciliation rows the comparator holds back on both
    # sides, because a case that compared them would be comparing two sums
    # rather than the attribution between them.
    return [{"component": c.label, "amount_sar_mn": c.amount,
             "facilities": c.exposures} for c in movement.components]


def build_cases(latest: str, previous: str, periods: tuple = ()) -> dict:
    """Each case: the engine-side SQL, and how the two sides are compared."""
    from backend.retail_cockpit_adapter import oracle as orc

    # The start of the twelve-month trend window, taken from the release's
    # own calendar rather than by subtracting twelve from a string.
    slots = list(periods or ())
    twelve = (slots[max(0, slots.index(latest) - 11)]
              if latest in slots else latest)

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

        # ---- the expansion ------------------------------------------
        #
        # Each one is the engine-side SQL for an oracle that computed the
        # same figure with pandas from the SOURCE book. They meet only in
        # the number.
        "Q04": {
            "sql": f"""SELECT product,
                              SUM(balance_sar) AS balance_sar,
                              SUM(balance_sar_mn) AS balance_sar_mn
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY product""",
            "compare": by_key(("product",),
                              ("balance_sar", "balance_sar_mn")),
        },
        "Q07": {
            "sql": f"""SELECT stage, COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ead_sar) / NULLIF(
                                  (SELECT SUM(ead_sar)
                                   FROM retail_account_month
                                   WHERE reporting_month = '{latest}'), 0)
                                  AS ead_share
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY stage""",
            "compare": by_key(("stage",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ead_share")),
        },
        "Q09": {
            "sql": f"""SELECT product, COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(ecl_sar_mn) AS ecl_sar_mn,
                              SUM(ecl_sar) / NULLIF(SUM(ead_sar), 0)
                                  AS coverage
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                         AND default_flag = 1
                       GROUP BY product""",
            "compare": by_key(("product",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ecl_sar", "ecl_sar_mn", "coverage")),
        },
        "Q10": {
            "sql": f"""SELECT delinquency_bucket AS bucket,
                              COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ead_sar) / NULLIF(
                                  (SELECT SUM(ead_sar)
                                   FROM retail_account_month
                                   WHERE reporting_month = '{latest}'), 0)
                                  AS ead_share
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY delinquency_bucket""",
            "compare": by_key(("bucket",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ead_share")),
        },
        "Q12": {
            "sql": f"""SELECT product, sub_product, COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(ecl_sar_mn) AS ecl_sar_mn
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY product, sub_product""",
            "compare": by_key(("product", "sub_product"),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ecl_sar", "ecl_sar_mn")),
        },
        "Q13": {
            "sql": f"""SELECT region, COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(ecl_sar_mn) AS ecl_sar_mn,
                              SUM(ecl_sar) / NULLIF(SUM(balance_sar), 0)
                                  AS coverage
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY region""",
            "compare": by_key(("region",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ecl_sar", "ecl_sar_mn", "coverage")),
        },
        "Q14": {
            "sql": f"""SELECT employment_type AS employment,
                              COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(CASE WHEN dpd_days > 0 THEN 1 ELSE 0 END)
                                  AS past_due_facilities,
                              SUM(CASE WHEN dpd_days > 0 THEN 1.0 ELSE 0.0 END)
                                  / NULLIF(COUNT(*), 0) AS past_due_share
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY employment_type""",
            "compare": by_key(("employment",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "past_due_facilities", "past_due_share")),
        },
        "Q15": {
            "sql": f"""SELECT CASE WHEN salary_transfer_flag = 1
                                   THEN 'SALARY_TRANSFERRED'
                                   ELSE 'NOT_TRANSFERRED' END AS population,
                              COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(ecl_sar_mn) AS ecl_sar_mn,
                              SUM(ecl_sar) / NULLIF(SUM(ead_sar), 0)
                                  AS coverage,
                              SUM(CASE WHEN dpd_days > 0 THEN 1.0 ELSE 0.0 END)
                                  / NULLIF(COUNT(*), 0) AS past_due_share
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY 1""",
            "compare": by_key(("population",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ecl_sar", "ecl_sar_mn", "coverage",
                               "past_due_share")),
        },
        "Q17": {
            "sql": f"""SELECT score_band, COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(ecl_sar_mn) AS ecl_sar_mn,
                              SUM(ecl_sar) / NULLIF(SUM(ead_sar), 0)
                                  AS coverage
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                         AND score_band IS NOT NULL
                       GROUP BY score_band""",
            "compare": by_key(("score_band",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ecl_sar", "ecl_sar_mn", "coverage")),
        },
        "Q18": {
            "sql": f"""SELECT CASE
                                WHEN behaviour_score IS NULL
                                  OR behaviour_score_previous IS NULL
                                     THEN 'NOT_SCORED'
                                WHEN behaviour_score - behaviour_score_previous
                                     < -2 THEN 'DETERIORATED'
                                WHEN behaviour_score - behaviour_score_previous
                                     > 2 THEN 'IMPROVED'
                                ELSE 'STABLE' END AS movement,
                              COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY 1""",
            "compare": by_key(("movement",),
                              ("facilities", "ead_sar", "ead_sar_mn")),
        },
        "Q20": {
            "sql": f"""SELECT CAST(vintage_year AS VARCHAR) AS vintage_year,
                              COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(ecl_sar_mn) AS ecl_sar_mn,
                              SUM(ecl_sar) / NULLIF(SUM(ead_sar), 0)
                                  AS coverage
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY vintage_year""",
            "compare": by_key(("vintage_year",),
                              ("facilities", "ead_sar", "ead_sar_mn",
                               "ecl_sar", "ecl_sar_mn", "coverage")),
        },
        "Q23": {
            # The COLLATERAL relation, which holds secured facilities only.
            # Joined back for exposure, which is the join the engine's own
            # graph warns about -- and it is safe here precisely because
            # this relation is one row per secured facility per month.
            "sql": f"""SELECT c.product,
                              COUNT(*) AS facilities,
                              SUM(c.collateral_value_sar)
                                  AS collateral_value_sar,
                              SUM(c.collateral_value_sar_mn)
                                  AS collateral_value_sar_mn,
                              SUM(a.ead_sar) AS ead_sar,
                              SUM(a.ead_sar_mn) AS ead_sar_mn,
                              SUM(a.ead_sar)
                                  / NULLIF(SUM(c.collateral_value_sar), 0)
                                  AS ltv_of_sums
                       FROM retail_collateral_month c
                       JOIN retail_account_month a
                         ON a.account_id = c.account_id
                        AND a.reporting_month = c.reporting_month
                       WHERE c.reporting_month = '{latest}'
                       GROUP BY c.product""",
            "compare": by_key(("product",),
                              ("facilities", "collateral_value_sar",
                               "collateral_value_sar_mn", "ead_sar",
                               "ead_sar_mn", "ltv_of_sums")),
        },
        "Q24": {
            "sql": f"""SELECT product,
                              SUM(write_off_sar) AS write_off_sar,
                              SUM(write_off_sar_mn) AS write_off_sar_mn,
                              SUM(recovery_sar) AS recovery_sar,
                              SUM(recovery_sar_mn) AS recovery_sar_mn,
                              SUM(CASE WHEN cure_flag = 1 THEN 1 ELSE 0 END)
                                  AS cures
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY product""",
            "compare": by_key(("product",),
                              ("write_off_sar", "write_off_sar_mn",
                               "recovery_sar", "recovery_sar_mn", "cures")),
        },
        "Q25": {
            "sql": f"""SELECT 'BASE' AS scenario,
                              SUM(ecl_base_sar) AS ecl_sar,
                              SUM(ecl_base_sar_mn) AS ecl_sar_mn
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       UNION ALL
                       SELECT 'UPTURN', SUM(ecl_upturn_sar),
                              SUM(ecl_upturn_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       UNION ALL
                       SELECT 'DOWNTURN', SUM(ecl_downturn_sar),
                              SUM(ecl_downturn_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       UNION ALL
                       SELECT 'WEIGHTED', SUM(ecl_weighted_sar),
                              SUM(ecl_weighted_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       UNION ALL
                       SELECT 'OVERLAY', SUM(ecl_overlay_sar),
                              SUM(ecl_overlay_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       UNION ALL
                       SELECT 'RECOGNISED', SUM(ecl_sar), SUM(ecl_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'""",
            "compare": by_key(("scenario",), ("ecl_sar", "ecl_sar_mn")),
        },
        "Q26": {
            "sql": f"""SELECT reporting_month, COUNT(*) AS facilities,
                              SUM(ecl_sar) AS ecl_sar,
                              SUM(ecl_sar_mn) AS ecl_sar_mn,
                              SUM(ecl_sar) / NULLIF(SUM(balance_sar), 0)
                                  AS coverage
                       FROM retail_account_month
                       WHERE reporting_month >= '{twelve}'
                         AND reporting_month <= '{latest}'
                       GROUP BY reporting_month""",
            "compare": by_key(("reporting_month",),
                              ("facilities", "ecl_sar", "ecl_sar_mn",
                               "coverage")),
        },
        "Q28": {
            "sql": f"""SELECT product, COUNT(*) AS facilities,
                              SUM(CASE WHEN utilisation_pct IS NOT NULL
                                       THEN 1 ELSE 0 END)
                                  AS with_utilisation,
                              SUM(CASE WHEN utilisation_pct IS NOT NULL
                                       THEN limit_sar ELSE 0 END)
                                  AS limit_sar,
                              SUM(CASE WHEN utilisation_pct IS NOT NULL
                                       THEN balance_sar ELSE 0 END)
                                  AS balance_sar,
                              SUM(CASE WHEN utilisation_pct IS NOT NULL
                                       THEN balance_sar ELSE 0 END)
                                  / NULLIF(SUM(CASE WHEN utilisation_pct
                                                    IS NOT NULL
                                                    THEN limit_sar ELSE 0 END),
                                           0) AS utilisation_of_sums
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                       GROUP BY product""",
            "compare": by_key(("product",),
                              ("facilities", "with_utilisation", "limit_sar",
                               "balance_sar", "utilisation_of_sums")),
        },

        "Q06": {
            "sql": f"""SELECT delinquency_bucket_fine AS bucket,
                              SUM(CASE WHEN reporting_month = '{latest}'
                                       THEN 1 ELSE 0 END) AS current,
                              SUM(CASE WHEN reporting_month = '{previous}'
                                       THEN 1 ELSE 0 END) AS prior
                       FROM retail_account_month
                       WHERE reporting_month IN ('{latest}', '{previous}')
                         AND delinquency_bucket_fine IN
                             ('1-9', '10-19', '20-29')
                       GROUP BY delinquency_bucket_fine
                       UNION ALL
                       SELECT '1-29 (sum of the three)',
                              SUM(CASE WHEN reporting_month = '{latest}'
                                       THEN 1 ELSE 0 END),
                              SUM(CASE WHEN reporting_month = '{previous}'
                                       THEN 1 ELSE 0 END)
                       FROM retail_account_month
                       WHERE reporting_month IN ('{latest}', '{previous}')
                         AND delinquency_bucket_fine IN
                             ('1-9', '10-19', '20-29')
                       UNION ALL
                       SELECT '1-29 (counted directly)',
                              SUM(CASE WHEN reporting_month = '{latest}'
                                       THEN 1 ELSE 0 END),
                              SUM(CASE WHEN reporting_month = '{previous}'
                                       THEN 1 ELSE 0 END)
                       FROM retail_account_month
                       WHERE reporting_month IN ('{latest}', '{previous}')
                         AND dpd_days BETWEEN 1 AND 29""",
            "compare": by_key(("bucket",), ("current", "prior")),
        },
        "Q08": {
            # The triggers OVERLAP, so ANY is computed from the flag itself
            # rather than by adding the three -- which is the defect the
            # oracle's note exists to name.
            "sql": f"""SELECT 'sicr_quantitative_flag' AS trigger,
                              COUNT(*) AS facilities,
                              SUM(ead_sar) AS ead_sar,
                              SUM(ead_sar_mn) AS ead_sar_mn
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}' AND sicr_flag = 1
                         AND sicr_quantitative_flag = 1
                       UNION ALL
                       SELECT 'sicr_qualitative_flag', COUNT(*),
                              SUM(ead_sar), SUM(ead_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}' AND sicr_flag = 1
                         AND sicr_qualitative_flag = 1
                       UNION ALL
                       SELECT 'sicr_dpd_backstop_flag', COUNT(*),
                              SUM(ead_sar), SUM(ead_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}' AND sicr_flag = 1
                         AND sicr_dpd_backstop_flag = 1
                       UNION ALL
                       SELECT 'ANY', COUNT(*), SUM(ead_sar),
                              SUM(ead_sar_mn)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'
                         AND sicr_flag = 1""",
            "compare": by_key(("trigger",),
                              ("facilities", "ead_sar", "ead_sar_mn")),
        },
        "Q11": {
            "sql": f"""SELECT band,
                              SUM(CASE WHEN m = '{latest}' THEN n ELSE 0 END)
                                  AS current,
                              SUM(CASE WHEN m = '{previous}' THEN n ELSE 0 END)
                                  AS prior,
                              SUM(CASE WHEN m = '{latest}' THEN e ELSE 0 END)
                                  AS current_ead_sar,
                              SUM(CASE WHEN m = '{previous}' THEN e ELSE 0 END)
                                  AS prior_ead_sar
                       FROM (SELECT reporting_month AS m,
                                    CASE WHEN dpd_days BETWEEN 30 AND 59
                                              THEN '30-59'
                                         WHEN dpd_days BETWEEN 60 AND 89
                                              THEN '60-89'
                                         WHEN dpd_days >= 90 THEN '90+' END
                                         AS band,
                                    COUNT(*) AS n, SUM(ead_sar) AS e
                             FROM retail_account_month
                             WHERE reporting_month IN ('{latest}',
                                                       '{previous}')
                               AND dpd_days >= 30
                             GROUP BY 1, 2)
                       GROUP BY band""",
            "compare": by_key(("band",),
                              ("current", "prior", "current_ead_sar",
                               "prior_ead_sar")),
        },
        "Q19": {
            # The de-duplication test. PER_CUSTOMER reads the CUSTOMER
            # relation, which is one row each; PER_FACILITY_ROW reads the
            # account relation, which repeats the value -- and is carried
            # only so the gap between them is visible.
            "sql": f"""SELECT 'PER_CUSTOMER' AS basis,
                              SUM(income_sar) AS income_sar,
                              SUM(income_sar_mn) AS income_sar_mn,
                              COUNT(*) AS customers
                       FROM retail_customer_month
                       WHERE reporting_month = '{latest}'
                       UNION ALL
                       SELECT 'PER_FACILITY_ROW',
                              SUM(customer_income_sar),
                              SUM(customer_income_sar_mn), COUNT(*)
                       FROM retail_account_month
                       WHERE reporting_month = '{latest}'""",
            "compare": by_key(("basis",),
                              ("income_sar", "income_sar_mn", "customers")),
        },
        "Q21": {
            # Not a query. The ECL movement is attributed by `ecl.decompose`,
            # so this runs the PANEL the product serves and checks it against
            # an oracle that attributed the same movement with pandas, by a
            # different method, from the source book.
            "panel": _ecl_movement,
            "compare": by_key(("component",),
                              ("amount_sar_mn", "facilities")),
        },
        "Q22": {
            "sql": f"""SELECT CASE
                                WHEN debt_burden_ratio <= 0.35 THEN '<=0.35'
                                WHEN debt_burden_ratio <= 0.50
                                     THEN '0.35-0.50'
                                WHEN debt_burden_ratio <= 0.65
                                     THEN '0.50-0.65'
                                ELSE '>0.65' END AS band,
                              COUNT(*) AS customers,
                              SUM(total_ead_sar) AS ead_sar,
                              SUM(total_ead_sar_mn) AS ead_sar_mn,
                              SUM(CASE WHEN disposable_income_sar < 0
                                       THEN 1 ELSE 0 END)
                                  AS negative_disposable
                       FROM retail_customer_month
                       WHERE reporting_month = '{latest}'
                         AND debt_burden_ratio IS NOT NULL
                       GROUP BY 1""",
            "compare": by_key(("band",),
                              ("customers", "ead_sar", "ead_sar_mn",
                               "negative_disposable")),
        },
        "Q27": {
            "sql": f"""WITH ranked AS (
                         SELECT total_ead_sar AS ead,
                                ROW_NUMBER() OVER (
                                    ORDER BY total_ead_sar DESC) AS rank
                         FROM retail_customer_month
                         WHERE reporting_month = '{latest}'),
                       book AS (
                         SELECT SUM(ead) AS total FROM ranked)
                       SELECT 10 AS top_n,
                              SUM(CASE WHEN rank <= 10 THEN ead ELSE 0 END)
                                  AS ead_sar,
                              SUM(CASE WHEN rank <= 10 THEN ead ELSE 0 END)
                                  / NULLIF((SELECT total FROM book), 0)
                                  AS share
                       FROM ranked
                       UNION ALL
                       SELECT 100,
                              SUM(CASE WHEN rank <= 100 THEN ead ELSE 0 END),
                              SUM(CASE WHEN rank <= 100 THEN ead ELSE 0 END)
                                  / NULLIF((SELECT total FROM book), 0)
                       FROM ranked
                       UNION ALL
                       SELECT 1000,
                              SUM(CASE WHEN rank <= 1000 THEN ead ELSE 0 END),
                              SUM(CASE WHEN rank <= 1000 THEN ead ELSE 0 END)
                                  / NULLIF((SELECT total FROM book), 0)
                       FROM ranked""",
            "compare": by_key(("top_n",), ("ead_sar", "share")),
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
