"""Independent oracles for every catalogue metric that was only shown to
evaluate, not to be right.

Each metric is recomputed here in plain Python from the governed rows (the
same row view the catalogue reads), with the catalogue's stated null policy,
and compared with `metrics.evaluate`. Nothing here calls the SQL the metric
uses. Both books, the latest period and an earlier one, plus a filtered
population, so an aggregation that only happens to agree on one cut fails.

EVIDENCE LABEL: INDEPENDENT ORACLE; REAL DATABASE (governed candidate books);
NO MODEL.
"""

# Fixtures are shared with the catalogue suite by import; pytest injects
# them by parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import pytest

from backend.cockpit_v4 import lake
from backend.workspace import access, grid, metrics
from backend.workspace import metric_catalog as mc
from tests.cockpit_v4.test_gw_metrics import (  # noqa: F401 (fixtures)
    WHO,
    close,
    rows_of,
    svc,
)

BOOKS = ("corporate", "retail")
BUCKET = {"Current": 0, "1-30": 1, "31-60": 2, "61-90": 3, "90+": 4}


def ratio(num, den):
    if num is None:
        return None
    return None if not den else num / den


def s(rows, value, cond=lambda r: True):
    """SQL `SUM(CASE WHEN cond THEN value ELSE 0 END)`: NULL values add
    nothing, an empty input is NULL."""
    if not rows:
        return None
    return float(sum((value(r) or 0) for r in rows if cond(r)))


def gt(a, b):
    return a is not None and b is not None and a > b


# ---- the oracles ---------------------------------------------------------------
# Each returns the expected `value` for the given rows; None means the
# metric does not apply to this book.

def staged(rows):
    return [r for r in rows if r.get("stage") in (1, 2, 3)]


def o_m004(rows, book):
    st = staged(rows)
    return ratio(s(rows, lambda r: r["ead_sar_mn"], lambda r: r["stage"] == 1),
                 s(st, lambda r: r["ead_sar_mn"]))


def o_m008(rows, book):
    st = staged(rows)
    return ratio(s(rows, lambda r: r["ecl_sar_mn"], lambda r: r["stage"] == 3),
                 s(st, lambda r: r["ecl_sar_mn"]))


def o_m009(rows, book):
    return s(rows, lambda r: r["ead_sar_mn"],
             lambda r: r["prior_stage"] == 1 and r["stage"] == 2)


def o_m010(rows, book):
    return s(rows, lambda r: r["ead_sar_mn"],
             lambda r: r["prior_stage"] == 2 and r["stage"] == 3)


def o_m011(rows, book):
    return s(rows, lambda r: r["ead_sar_mn"],
             lambda r: gt(r["prior_stage"], r["stage"]))


def _new_default(r):
    return ((r.get("prior_default_flag") or 0) == 0 and r["default_flag"] == 1
            and r["prior_stage"] is not None)


def _performing(r):
    return (r.get("prior_default_flag") or 0) == 0 and \
        r["prior_stage"] is not None


def o_m012(rows, book):
    return ratio(sum(1 for r in rows if _new_default(r)),
                 sum(1 for r in rows if _performing(r)))


def o_m013(rows, book):
    return float(sum(1 for r in rows if _new_default(r)))


def o_m014(rows, book):
    return s(rows, lambda r: r["ead_sar_mn"],
             lambda r: r["default_flag"] == 1 or r["stage"] == 3)


def o_m019(rows, book):
    num = s(rows, lambda r: (r["limit_sar_mn"] * r["utilisation_pct"] / 100.0
                             if r["limit_sar_mn"] is not None
                             and r["utilisation_pct"] is not None else None))
    return ratio(num, s(rows, lambda r: r["limit_sar_mn"]))


def o_m022(rows, book):
    dim = "sector" if book.domain_id == "corporate" else "product"
    by = defaultdict(float)
    for r in rows:
        by[r[dim]] += r["ead_sar_mn"] or 0
    total = sum(by.values())
    return {k: v / total for k, v in by.items()}


def _rated(rows):
    return [r for r in rows if r.get("rating_previous") is not None]


def o_m023(rows, book):
    rated = _rated(rows)
    return ratio(len({r["borrower_id"] for r in rated
                      if (r["rating_notches_moved"] or 0) > 0}),
                 len({r["borrower_id"] for r in rated}))


def o_m024(rows, book):
    rated = _rated(rows)
    return ratio(len({r["borrower_id"] for r in rated
                      if r["rating_notches_moved"] is not None
                      and r["rating_notches_moved"] < 0}),
                 len({r["borrower_id"] for r in rated}))


def o_m025(rows, book):
    pairs = {(r["borrower_id"], r["rating_notches_moved"])
             for r in _rated(rows)}
    vals = [m for _, m in pairs]
    return ratio(float(sum(v or 0 for v in vals)), len(vals))


def o_m026(rows, book):
    pairs = {(r["customer_id"], r["behaviour_score_change"]) for r in rows}
    vals = [m for _, m in pairs if m is not None]
    return ratio(float(sum(vals)), len(vals))


def o_m027(rows, book):
    bands = defaultdict(set)
    for r in rows:
        if r["application_score"] is not None:
            lo = int(r["application_score"] // 100) * 100
            bands[f"{lo}-{lo + 99}"].add(r["customer_id"])
    return {k: len(v) for k, v in bands.items()}


def o_m030(rows, book):
    src = [r for r in rows if r["prior_delinquency_bucket"] is not None]
    worse = sum(1 for r in src if gt(BUCKET.get(r["delinquency_bucket"]),
                                     BUCKET.get(r["prior_delinquency_bucket"])))
    return ratio(worse, len(src))


def o_m031(rows, book):
    src = [r for r in rows if gt(r["prior_dpd_days"], 0)]
    return ratio(sum(1 for r in src if r["dpd_days"] == 0), len(src))


def _owners(rows, book, cond):
    owner = grid.SPEC[book.domain_id]["owner"]
    return len({r[owner] for r in rows if cond(r)})


def o_m032(rows, book):
    return _owners(rows, book, lambda r: r["ews_band"] is not None
                   and r["ews_band"] != "none")


def o_m033(rows, book):
    warned = o_m032(rows, book)
    severe = _owners(rows, book, lambda r: r["ews_band"] in ("high",
                                                             "critical"))
    return ratio(severe, warned)


def o_m034(rows, book):
    return _owners(rows, book, lambda r: r["stage"] == 1
                   and gt(r["prior_pd_pit_12m"], 0)
                   and r["pd_pit_12m"] is not None
                   and r["pd_pit_12m"] >= r["prior_pd_pit_12m"] * 1.2)


def o_m035(rows, book):
    # COUNT(*): a row without a score still counts in the denominator.
    return ratio(s(rows, lambda r: r["ews_score"]), len(rows))


def o_m036(rows, book):
    src = [r for r in rows if r["covenant_breaches"] is not None]
    return ratio(sum(1 for r in src if r["covenant_breaches"] > 0), len(src))


def o_m037(rows, book):
    return ratio(s(rows, lambda r: r["ead_sar_mn"]),
                 s(rows, lambda r: r["limit_sar_mn"]))


def o_m038(rows, book):
    return float(sum(1 for r in rows if gt(r["utilisation_pct"], 100)))


def o_m045(rows, book):
    fields = [f for f in metrics.REQUIRED_FIELDS if f in rows[0]]
    filled = sum(1 for r in rows for f in fields if r[f] is not None)
    return ratio(filled, len(rows) * len(fields))


def o_m047(rows, book):
    total = sum(r["ecl_sar_mn"] or 0 for r in rows)
    parts = sum(r["ecl_sar_mn"] or 0 for r in rows if r["stage"] in (1, 2, 3))
    return total - parts


ORACLES = {
    "M004": o_m004, "M008": o_m008, "M009": o_m009, "M010": o_m010,
    "M011": o_m011, "M012": o_m012, "M013": o_m013, "M014": o_m014,
    "M019": o_m019, "M022": o_m022, "M023": o_m023, "M024": o_m024,
    "M025": o_m025, "M026": o_m026, "M027": o_m027, "M030": o_m030,
    "M031": o_m031, "M032": o_m032, "M033": o_m033, "M034": o_m034,
    "M035": o_m035, "M036": o_m036, "M037": o_m037, "M038": o_m038,
    "M045": o_m045, "M047": o_m047,
}
GROUPED = {"M022", "M027"}


_STRESS: dict[str, str] = {}


def _stress_period(book):
    """The published period with the most Stage 3 rows: on these books
    defaults, Stage 3 and 2→3 migration occur only mid-history (the latest
    periods have none), so a latest-only check would compare zeros."""
    if book.domain_id not in _STRESS:
        best, period = -1, ""
        for p in book.periods:
            v = grid.view(book, p)
            if not v.prior_period:
                continue
            n = book.rows(f"SELECT COUNT(*) AS n FROM ({v.sql}) g "
                          f"WHERE stage = 3", [])[0]["n"]
            if n > best:
                best, period = n, p
        _STRESS[book.domain_id] = period
    return _STRESS[book.domain_id]


def _cuts(book):
    """(label, period, filters): latest; the prior period; the stress
    period; a filtered cut of the stress period."""
    v = grid.view(book, "")
    stress = _stress_period(book)
    dim = "sector" if book.domain_id == "corporate" else "product"
    sv = grid.view(book, stress)
    top = book.rows(f"SELECT {dim} AS d, COUNT(*) AS n FROM ({sv.sql}) g "
                    f"WHERE stage = 3 GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
                    [])[0]["d"]
    cuts = [("latest", "", None)]
    if v.prior_period:
        cuts.append(("prior", v.prior_period, None))
    cuts.append(("stress", stress, None))
    cuts.append(("filtered", stress,
                 [{"column": dim, "op": "eq", "value": top}]))
    return cuts


def _filtered(rows, filters):
    if not filters:
        return rows
    f = filters[0]
    return [r for r in rows if r[f["column"]] == f["value"]]


@pytest.mark.parametrize("metric_id", sorted(ORACLES))
def test_metric_matches_its_independent_oracle(svc, metric_id):
    checked = 0
    for domain in BOOKS:
        if not mc.applies(mc.BY_ID[metric_id], domain):
            continue
        book = access.book(WHO, domain)
        for label, period, filters in _cuts(book):
            rows = _filtered(rows_of(book, period), filters)
            assert rows, (domain, label)
            want = ORACLES[metric_id](rows, book)
            got = metrics.evaluate(book, metric_id, period=period,
                                   filters=filters)
            if metric_id in GROUPED:
                have = {str(g["dimension"]): (g["value"] if metric_id ==
                                              "M022" else g["numerator"])
                        for g in got["groups"]}
                assert set(have) == {str(k) for k in want}, \
                    (metric_id, domain, label)
                for k, v in want.items():
                    assert close(have[str(k)], v), (metric_id, domain, label,
                                                    k, have[str(k)], v)
            else:
                assert close(got["value"], want), (metric_id, domain, label,
                                                   got["value"], want)
            checked += 1
    assert checked >= 3, f"{metric_id} was checked on {checked} cuts only"


def test_the_oracles_are_not_vacuous(svc):
    """A migration or breach oracle that is 0 everywhere proves nothing: at
    least one cut of each must be non-zero on the governed books."""
    seen = defaultdict(bool)
    for domain in BOOKS:
        book = access.book(WHO, domain)
        for _label, period, filters in _cuts(book):
            rows = _filtered(rows_of(book, period), filters)
            for mid, fn in ORACLES.items():
                if not mc.applies(mc.BY_ID[mid], domain):
                    continue
                v = fn(rows, book)
                seen[mid] |= bool(v) if not isinstance(v, dict) else \
                    any(v.values())
    zero = sorted(m for m in ORACLES if not seen[m])
    # M047 is a residual: zero is the correct, reconciling answer. M038 is
    # zero because no account in either book exceeds its limit in any
    # period (measured below); its formula is proven on rows that do.
    assert zero == ["M038", "M047"], zero


def test_no_published_period_exceeds_a_limit(svc):
    """Why M038 is 0 on the governed books: measured, not assumed."""
    for domain in BOOKS:
        book = access.book(WHO, domain)
        top = max(max((r["utilisation_pct"] or 0) for r in rows_of(book, p))
                  for p in book.periods)
        assert 0 < top <= 100, (domain, top)


def test_m038_counts_exactly_the_rows_over_their_limit():
    """The catalogue's own M038 SQL over rows that do breach: only
    utilisation strictly above 100 counts; NULL does not."""
    import duckdb

    num = mc.BY_ID["M038"]["num_sql"]
    con = duckdb.connect()
    con.execute("CREATE TABLE g (utilisation_pct DOUBLE)")
    con.execute("INSERT INTO g VALUES (99.9), (100.0), (100.1), (150), "
                "(NULL), (250)")
    assert con.execute(f"SELECT {num} FROM g").fetchone()[0] == 3


def test_m043_m044_match_the_published_sensitivity_relation(svc):
    """The coefficient and its sign stability are read straight from the
    published sensitivity parquet, not through the evaluator's SQL."""
    import pyarrow.parquet as pq

    for domain, relation in (("corporate", "whatif_corp_sensitivity"),
                             ("retail", "whatif_retail_sensitivity")):
        book = access.book(WHO, domain)
        files = sorted((lake.root() / book.release_id).rglob(
            f"{relation}*.parquet"))
        assert files, (domain, relation)
        table = pq.read_table(files[0]).to_pylist()
        want_coef = {f"{r['factor_id']}·{r['parameter']}": r["coefficient"]
                     for r in table}
        want_stab = {f"{r['factor_id']}·{r['parameter']}": r["sign_stability"]
                     for r in table}
        got = metrics.evaluate(book, "M043")
        assert got["value"] == len(table)
        assert {g["dimension"]: g["value"] for g in got["groups"]} == \
            pytest.approx(want_coef)
        got = metrics.evaluate(book, "M044")
        have = {g["dimension"]: g["value"] for g in got["groups"]}
        for k, v in want_stab.items():
            assert close(have[k], None if v is None else float(v)), (k, v)


def test_m046_freshness_is_hours_since_the_release_publication(svc):
    from datetime import datetime

    for domain in BOOKS:
        book = access.book(WHO, domain)
        manifest = json.loads((Path(lake.root()) / book.release_id /
                               "manifest.json").read_text())
        built = manifest.get("built_at")
        stamp = (datetime.fromisoformat(built.replace("Z", "+00:00"))
                 .timestamp() if built else
                 (Path(lake.root()) / book.release_id /
                  "manifest.json").stat().st_mtime)
        want = (time.time() - stamp) / 3600.0
        got = metrics.evaluate(book, "M046")["value"]
        assert got > 0 and abs(got - want) < 0.05, (domain, got, want)
