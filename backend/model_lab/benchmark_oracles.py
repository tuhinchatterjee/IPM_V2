"""
Independent oracles for the RunPod analyst suite (Q01-Q15).

Computed with pandas directly over the published Parquet release. They share
no code with the frozen engine and never look at any model's SQL, answer or
tool results. Tolerances are declared before evaluation. Each oracle records
its code hash and the exact data snapshot.

Two kinds of output:

* TABLES -- the expected result a correct analysis must reproduce (keys +
  metrics). `grade_table` matches a candidate artifact to one by VALUES, not
  column names, and diagnoses common failures against deliberately computed
  WRONG-POPULATION references (preceding quarter, wrong stage, all quarters,
  inflated by a missing join key).
* FACTS -- labelled quantities a narrative may state (totals, counts, shares,
  flows). Numeric claims are checked against them; a cause is never a fact.

Oracle values are evaluation-side only: they are never placed in a provider
request (see tests/model_lab/test_benchmark_oracles.py).
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
from typing import Any

from backend.model_lab import benchmark_questions as bq

ORACLE_SUITE_VERSION = "lab-oracle-suite-1"
RELEASE = "v4-saudi-corporate-20q-v4"
ABS_TOL, REL_TOL = 0.01, 1e-9          # SAR million
COUNT_TOL = 0

FAC_COLS = ("facility_id", "borrower_id", "borrower_name",
            "reporting_quarter", "sector", "stage", "ead_sar_mn",
            "ecl_sar_mn", "dpd_days")
BOR_COLS = ("borrower_id", "borrower_name", "reporting_quarter", "sector",
            "rating_previous", "rating_current", "rating_migration",
            "rating_notches_moved", "watchlist_flag")

SPECS: dict[str, dict[str, Any]] = {
    "Q01": {"population": "Stage 2 facilities, latest quarter",
            "grain": "facility-quarter -> sector",
            "note": "the registered lab-oracle-2 task "
                    "corp-stage2-ead-by-sector-latest is unchanged"},
    "Q02": {"population": "Stage 2 facilities, latest quarter",
            "grain": "facility-quarter -> sector",
            "metrics": ["COUNT(DISTINCT facility_id)"],
            "required_outputs": ["per-sector counts", "top 3 sectors",
                                 "total count reconciles"],
            "materiality": "any count off by one is material"},
    "Q03": {"population": "Stage 2 facilities in the preceding and the "
                          "latest quarter (each quarter's own Stage 2 set)",
            "grain": "facility-quarter -> sector x quarter",
            "metrics": ["SUM(ead_sar_mn) per quarter", "change"],
            "required_outputs": ["both period values", "change per sector",
                                 "largest increases", "largest decreases"]},
    "Q04": {"population": "facilities in the preceding and latest quarter",
            "grain": "facility pairs on facility_id across quarters",
            "metrics": ["Stage 2 EAD bridge: inflows, outflows, new, exited, "
                        "balance change of facilities Stage 2 in both"],
            "required_outputs": ["quantitative facts reconcile the change",
                                 "facts separated from causes"],
            "causes": "UNVERIFIABLE unless directly supported by data"},
    "Q05": {"population": "borrowers with rating_migration = DOWNGRADE in "
                          "the latest quarter",
            "grain": "borrower-quarter",
            "metrics": ["prior/current rating", "sector", "borrower EAD = "
                        "SUM(ead_sar_mn) of its latest-quarter facilities"],
            "required_outputs": ["exact population", "ratings", "sector",
                                 "EAD"]},
    "Q06": {"population": "all facilities, latest quarter",
            "grain": "facility-quarter -> stage x sector",
            "metrics": ["SUM(ecl_sar_mn)"],
            "required_outputs": ["stage x sector values", "totals reconcile",
                                 "chart (evaluated separately)"]},
    "Q07": {"population": "facilities present in both quarters, paired on "
                          "facility_id",
            "grain": "facility pair -> stage_prev x stage_latest",
            "metrics": ["facility count", "latest-quarter EAD"],
            "required_outputs": ["transition matrix",
                                 "largest moves into Stage 2 by sector",
                                 "population reconciles (new / exited "
                                 "stated separately)"]},
    "Q08": {"population": "Stage 2 facilities, latest quarter",
            "grain": "borrower (sum of its Stage 2 facilities)",
            "metrics": ["borrower Stage 2 EAD"],
            "required_outputs": ["exact top 10 in order", "sector",
                                 "current rating"]},
    "Q09": {"population": "sectors, preceding vs latest quarter",
            "grain": "sector",
            "metrics": ["Stage 2 EAD change", "ECL change",
                        "downgraded borrowers", "watch-list borrowers"],
            "required_outputs": ["each measurable component correct"],
            "no_overall_winner": True},
    "Q10": {"population": "whole corporate book", "grain": "portfolio",
            "required_outputs": ["quantitative claims match the fact set"],
            "causes": "UNVERIFIABLE unless directly supported"},
    "Q11": {"population": "all facilities, latest quarter",
            "grain": "facility-quarter -> sector",
            "metrics": ["SUM(ead_sar_mn)"],
            "required_outputs": ["per-sector totals", "portfolio total",
                                 "reconciliation"]},
    "Q12": {"population": "Stage 3 facilities, latest quarter",
            "grain": "facility-quarter -> sector",
            "metrics": ["SUM(ead_sar_mn)", "SUM(ecl_sar_mn)"],
            "required_outputs": ["per-sector EAD and ECL",
                                 "largest concentrations",
                                 "totals reconcile"]},
    "Q13": {"population": "Stage 2 facilities, latest quarter",
            "grain": "sector and borrower",
            "metrics": ["Stage 2 EAD", "share of total Stage 2 EAD"],
            "required_outputs": ["top sectors", "top borrowers", "shares",
                                 "reconciliation"]},
    "Q14": {"population": "facilities Stage 3 in the latest quarter and "
                          "Stage 1/2 in the preceding quarter; borrowers "
                          "with at least one such facility",
            "grain": "borrower (sum over its migrated facilities)",
            "metrics": ["EAD", "ECL"],
            "required_outputs": ["exact population", "EAD", "ECL", "sector",
                                 "rating"]},
    "Q15": {"population": "whole corporate book", "grain": "portfolio",
            "required_outputs": ["quantitative claims match the fact set"],
            "review": "causal and overall judgements are review-only"},
}
COMMON = {"tolerances": {"money_abs": ABS_TOL, "money_rel": REL_TOL,
                         "count": COUNT_TOL, "share_abs_pct": 0.01},
          "permissible_alternatives": [
              "any column names and ordering of columns",
              "extra rows only where marked (e.g. a total row)",
              "values in the same unit, rounded to <= 2 decimals",
              "quarter named literally or found with MAX()"],
          "materiality": "any mismatch beyond tolerance is material"}


# ---- data ------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def _frames(release: str):
    import pandas as pd
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
    from backend.cockpit_v4 import lake  # path resolution only

    fac = pd.read_parquet(lake.relation_path(release, bq.FAC),
                          columns=list(FAC_COLS))
    bor = pd.read_parquet(lake.relation_path(release, bq.BOR),
                          columns=list(BOR_COLS))
    qs = sorted(fac["reporting_quarter"].unique())
    return fac, bor, qs[-1], qs[-2]


def snapshot_id(release: str = RELEASE) -> str:
    from backend.cockpit_v4 import analytical_runtime as arun
    s = arun.for_domain(bq.DOMAIN).release_summary()
    return f"{s['dataset_release_id']}@{s['release_fingerprint']}"


def _r(x: float) -> float:
    return round(float(x), 6)


def _table(name, keys, metrics, df, *, rank_by=None, top_n=None,
           units=None) -> dict[str, Any]:
    d = df.copy()
    if rank_by:
        d = d.sort_values([rank_by] + list(keys),
                          ascending=[False] + [True] * len(keys))
        if top_n:
            d = d.head(top_n)
    rows = []
    for rec in d.to_dict("records"):
        rows.append({k: (int(v) if hasattr(v, "item") and float(v).is_integer()
                         and k in ("stage", "stage_prev", "stage_latest")
                         else (v.item() if hasattr(v, "item") else v))
                     for k, v in rec.items()})
    for r in rows:
        for m in metrics:
            if r.get(m) is not None and not isinstance(r[m], str):
                r[m] = _r(r[m])
    return {"name": name, "keys": list(keys), "metrics": list(metrics),
            "rows": rows, "ordered": bool(rank_by), "top_n": top_n,
            "units": units or {}}


def _fact(fid, label, value, unit) -> dict[str, Any]:
    return {"fact_id": fid, "label": label, "value": _r(value),
            "unit": unit}


# ---- the oracles -----------------------------------------------------------

def _stage_sum(fac, q, stage, metric="ead_sar_mn", by=("sector",)):
    d = fac[(fac.reporting_quarter == q) & (fac.stage == stage)]
    return d.groupby(list(by), as_index=False)[metric].sum()


def _pairs(fac, L, P):
    a = fac[fac.reporting_quarter == P][["facility_id", "stage",
                                         "ead_sar_mn"]]
    b = fac[fac.reporting_quarter == L][["facility_id", "stage", "sector",
                                         "borrower_id", "ead_sar_mn",
                                         "ecl_sar_mn"]]
    m = a.merge(b, on="facility_id", suffixes=("_prev", "_latest"))
    new = b[~b.facility_id.isin(a.facility_id)]
    exited = a[~a.facility_id.isin(b.facility_id)]
    return m, new, exited


def _borrower_ead(fac, L, stage=None):
    d = fac[fac.reporting_quarter == L]
    if stage is not None:
        d = d[d.stage == stage]
    return d.groupby("borrower_id", as_index=False)["ead_sar_mn"].sum()


def oracle_q01(fac, bor, L, P):
    t = _stage_sum(fac, L, 2)
    return {"tables": [_table("stage2_ead_by_sector", ["sector"],
                              ["ead_sar_mn"], t, rank_by="ead_sar_mn",
                              units={"ead_sar_mn": "money"})],
            "facts": [_fact("stage2_ead_total", "Stage 2 EAD total",
                            t.ead_sar_mn.sum(), "money")]}


def oracle_q02(fac, bor, L, P):
    d = fac[(fac.reporting_quarter == L) & (fac.stage == 2)]
    t = d.groupby("sector", as_index=False).agg(
        facilities=("facility_id", "nunique"))
    return {"tables": [
        _table("stage2_facilities_by_sector", ["sector"], ["facilities"], t,
               rank_by="facilities", units={"facilities": "count"}),
        _table("top3_sectors", ["sector"], ["facilities"], t,
               rank_by="facilities", top_n=3,
               units={"facilities": "count"})],
        "facts": [_fact("stage2_facility_total", "Stage 2 facilities",
                        t.facilities.sum(), "count")]}


def oracle_q03(fac, bor, L, P):
    a = _stage_sum(fac, P, 2).rename(columns={"ead_sar_mn": "ead_prev"})
    b = _stage_sum(fac, L, 2).rename(columns={"ead_sar_mn": "ead_latest"})
    t = a.merge(b, on="sector", how="outer").fillna(0.0)
    t["change"] = t.ead_latest - t.ead_prev
    units = {k: "money" for k in ("ead_prev", "ead_latest", "change")}
    inc = t[t.change > 0].sort_values("change", ascending=False).head(3)
    dec = t[t.change < 0].sort_values("change").head(3)
    return {"tables": [
        _table("stage2_ead_change_by_sector", ["sector"],
               ["ead_prev", "ead_latest", "change"], t, units=units)],
        "facts": [_fact("stage2_ead_prev_total", "Stage 2 EAD preceding",
                        t.ead_prev.sum(), "money"),
                  _fact("stage2_ead_latest_total", "Stage 2 EAD latest",
                        t.ead_latest.sum(), "money"),
                  _fact("stage2_ead_change_total", "change in Stage 2 EAD",
                        t.change.sum(), "money")]
        + [_fact(f"increase_{i + 1}", f"increase: {s}", c, "money")
           for i, (s, c) in enumerate(zip(inc.sector, inc.change,
                                          strict=True))]
        + [_fact(f"decrease_{i + 1}", f"decrease: {s}", c, "money")
           for i, (s, c) in enumerate(zip(dec.sector, dec.change,
                                          strict=True))],
        "rankings": {"largest_increases": list(inc.sector),
                     "largest_decreases": list(dec.sector)}}


def oracle_q04(fac, bor, L, P):
    m, new, exited = _pairs(fac, L, P)
    prev_total = fac[(fac.reporting_quarter == P) & (fac.stage == 2)
                     ].ead_sar_mn.sum()
    latest_total = fac[(fac.reporting_quarter == L) & (fac.stage == 2)
                       ].ead_sar_mn.sum()
    inflow = m[(m.stage_prev != 2) & (m.stage_latest == 2)]
    outflow = m[(m.stage_prev == 2) & (m.stage_latest != 2)]
    stay = m[(m.stage_prev == 2) & (m.stage_latest == 2)]
    new2 = new[new.stage == 2]
    exit2 = exited[exited.stage == 2]
    facts = [
        _fact("stage2_ead_prev_total", "Stage 2 EAD preceding", prev_total,
              "money"),
        _fact("stage2_ead_latest_total", "Stage 2 EAD latest", latest_total,
              "money"),
        _fact("stage2_ead_change", "change in Stage 2 EAD",
              latest_total - prev_total, "money"),
        _fact("inflow_from_stage1_ead", "EAD moving 1 -> 2",
              inflow[inflow.stage_prev == 1].ead_sar_mn_latest.sum(),
              "money"),
        _fact("inflow_from_stage3_ead", "EAD moving 3 -> 2",
              inflow[inflow.stage_prev == 3].ead_sar_mn_latest.sum(),
              "money"),
        _fact("outflow_to_stage1_ead", "EAD leaving 2 -> 1",
              outflow[outflow.stage_latest == 1].ead_sar_mn_prev.sum(),
              "money"),
        _fact("outflow_to_stage3_ead", "EAD leaving 2 -> 3",
              outflow[outflow.stage_latest == 3].ead_sar_mn_prev.sum(),
              "money"),
        _fact("new_stage2_ead", "new facilities in Stage 2",
              new2.ead_sar_mn.sum(), "money"),
        _fact("exited_stage2_ead", "Stage 2 facilities that exited",
              exit2.ead_sar_mn.sum(), "money"),
        _fact("stayer_balance_change", "balance change, Stage 2 in both",
              (stay.ead_sar_mn_latest - stay.ead_sar_mn_prev).sum(),
              "money"),
        _fact("inflow_facilities", "facilities entering Stage 2",
              len(inflow), "count"),
        _fact("outflow_facilities", "facilities leaving Stage 2",
              len(outflow), "count"),
    ]
    bridge = (facts[3]["value"] + facts[4]["value"] - facts[5]["value"]
              - facts[6]["value"] + facts[7]["value"] - facts[8]["value"]
              + facts[9]["value"])
    assert abs(bridge - facts[2]["value"]) < 1e-6, "bridge must reconcile"
    q3 = oracle_q03(fac, bor, L, P)
    return {"tables": q3["tables"], "facts": facts + q3["facts"][3:],
            "bridge_identity": "change = in(1->2) + in(3->2) - out(2->1) - "
                               "out(2->3) + new - exited + stayer change",
            "causal": "not derivable: any cause is UNVERIFIABLE unless "
                      "directly supported by a stated data fact"}


def oracle_q05(fac, bor, L, P):
    d = bor[(bor.reporting_quarter == L) &
            (bor.rating_migration == "DOWNGRADE")]
    e = _borrower_ead(fac, L)
    t = d.merge(e, on="borrower_id", how="left")[
        ["borrower_id", "borrower_name", "sector", "rating_previous",
         "rating_current", "rating_notches_moved", "ead_sar_mn"]]
    return {"tables": [_table("downgraded_borrowers", ["borrower_id"],
                              ["ead_sar_mn", "rating_notches_moved"], t,
                              units={"ead_sar_mn": "money",
                                     "rating_notches_moved": "count"})],
            "facts": [_fact("downgraded_borrowers", "downgraded borrowers",
                            len(t), "count"),
                      _fact("downgraded_ead", "EAD of downgraded borrowers",
                            t.ead_sar_mn.sum(), "money")],
            "labels": {"rating_previous": "rating_previous",
                       "rating_current": "rating_current"}}


def oracle_q06(fac, bor, L, P):
    d = fac[fac.reporting_quarter == L]
    t = d.groupby(["stage", "sector"], as_index=False)["ecl_sar_mn"].sum()
    by_stage = d.groupby("stage", as_index=False)["ecl_sar_mn"].sum()
    by_sector = d.groupby("sector", as_index=False)["ecl_sar_mn"].sum()
    return {"tables": [
        _table("ecl_by_stage_sector", ["stage", "sector"], ["ecl_sar_mn"],
               t, units={"ecl_sar_mn": "money"}),
        _table("ecl_by_stage", ["stage"], ["ecl_sar_mn"], by_stage,
               units={"ecl_sar_mn": "money"}),
        _table("ecl_by_sector", ["sector"], ["ecl_sar_mn"], by_sector,
               units={"ecl_sar_mn": "money"})],
        "facts": [_fact("ecl_total", "total ECL", d.ecl_sar_mn.sum(),
                        "money")]
        + [_fact(f"ecl_stage{int(s)}", f"Stage {int(s)} ECL", v, "money")
           for s, v in zip(by_stage.stage, by_stage.ecl_sar_mn,
                           strict=True)],
        "chart_required": True}


def oracle_q07(fac, bor, L, P):
    m, new, exited = _pairs(fac, L, P)
    t = m.groupby(["stage_prev", "stage_latest"], as_index=False).agg(
        facilities=("facility_id", "count"),
        ead_latest=("ead_sar_mn_latest", "sum"))
    into2 = m[(m.stage_prev != 2) & (m.stage_latest == 2)].groupby(
        "sector", as_index=False).agg(facilities=("facility_id", "count"),
                                      ead_latest=("ead_sar_mn_latest",
                                                  "sum"))
    return {"tables": [
        _table("stage_transition_matrix", ["stage_prev", "stage_latest"],
               ["facilities", "ead_latest"], t,
               units={"facilities": "count", "ead_latest": "money"}),
        _table("moves_into_stage2_by_sector", ["sector"],
               ["facilities", "ead_latest"], into2, rank_by="ead_latest",
               units={"facilities": "count", "ead_latest": "money"})],
        "facts": [_fact("paired_facilities", "facilities in both quarters",
                        len(m), "count"),
                  _fact("new_facilities", "new in latest quarter", len(new),
                        "count"),
                  _fact("exited_facilities", "exited after preceding",
                        len(exited), "count"),
                  _fact("moves_into_stage2", "facilities moving into "
                        "Stage 2", into2.facilities.sum(), "count")]}


def oracle_q08(fac, bor, L, P):
    e = _borrower_ead(fac, L, stage=2)
    b = bor[bor.reporting_quarter == L][["borrower_id", "borrower_name",
                                         "sector", "rating_current"]]
    t = e.merge(b, on="borrower_id", how="left")
    return {"tables": [_table("top10_stage2_borrowers", ["borrower_id"],
                              ["ead_sar_mn"], t, rank_by="ead_sar_mn",
                              top_n=10, units={"ead_sar_mn": "money"})],
            "facts": []}


def _sector_signals(fac, bor, L, P):
    def s(q, stage=None, metric="ead_sar_mn"):
        d = fac[fac.reporting_quarter == q]
        if stage is not None:
            d = d[d.stage == stage]
        return d.groupby("sector")[metric].sum()
    t = (s(L, 2).rename("stage2_ead_latest").to_frame()
         .join(s(P, 2).rename("stage2_ead_prev"), how="outer")
         .join(s(L, None, "ecl_sar_mn").rename("ecl_latest"), how="outer")
         .join(s(P, None, "ecl_sar_mn").rename("ecl_prev"), how="outer")
         .fillna(0.0))
    t["stage2_ead_change"] = t.stage2_ead_latest - t.stage2_ead_prev
    t["ecl_change"] = t.ecl_latest - t.ecl_prev
    bl = bor[bor.reporting_quarter == L]
    t = t.join(bl[bl.rating_migration == "DOWNGRADE"].groupby("sector")
               .borrower_id.nunique().rename("downgraded_borrowers"),
               how="left")
    t = t.join(bl[bl.watchlist_flag == 1].groupby("sector").borrower_id
               .nunique().rename("watchlist_borrowers"), how="left")
    return t.fillna(0).reset_index().rename(columns={"index": "sector"})


def oracle_q09(fac, bor, L, P):
    t = _sector_signals(fac, bor, L, P)
    metrics = ["stage2_ead_prev", "stage2_ead_latest", "stage2_ead_change",
               "ecl_prev", "ecl_latest", "ecl_change",
               "downgraded_borrowers", "watchlist_borrowers"]
    units = {m: ("count" if m.endswith("borrowers") else "money")
             for m in metrics}
    return {"tables": [_table("sector_deterioration_components", ["sector"],
                              metrics, t, units=units)],
            "facts": [], "no_overall_winner": True,
            "note": "each component is checked separately; no composite "
                    "ranking is an oracle output"}


def _book_facts(fac, bor, L, P):
    def tot(q, stage=None, metric="ead_sar_mn"):
        d = fac[fac.reporting_quarter == q]
        if stage is not None:
            d = d[d.stage == stage]
        return d[metric].sum()
    m, _, _ = _pairs(fac, L, P)
    s2 = _stage_sum(fac, L, 2)
    top = s2.sort_values("ead_sar_mn", ascending=False).iloc[0]
    bl = bor[bor.reporting_quarter == L]
    facts = []
    for st in (2, 3):
        a, b = tot(P, st), tot(L, st)
        facts += [_fact(f"stage{st}_ead_prev", f"Stage {st} EAD preceding",
                        a, "money"),
                  _fact(f"stage{st}_ead_latest", f"Stage {st} EAD latest",
                        b, "money"),
                  _fact(f"stage{st}_ead_change", f"Stage {st} EAD change",
                        b - a, "money")]
    ea, eb = tot(P, None, "ecl_sar_mn"), tot(L, None, "ecl_sar_mn")
    ead_l = tot(L)
    facts += [
        _fact("ecl_prev", "ECL preceding", ea, "money"),
        _fact("ecl_latest", "ECL latest", eb, "money"),
        _fact("ecl_change", "ECL change", eb - ea, "money"),
        _fact("total_ead_latest", "total EAD latest", ead_l, "money"),
        _fact("ecl_coverage_pct", "ECL / EAD latest (%)",
              100 * eb / ead_l, "percent"),
        _fact("stage2_top_sector_share_pct",
              f"largest Stage 2 sector share ({top.sector}, %)",
              100 * top.ead_sar_mn / s2.ead_sar_mn.sum(), "percent"),
        _fact("into_stage2_facilities", "facilities moving into Stage 2",
              int(((m.stage_prev != 2) & (m.stage_latest == 2)).sum()),
              "count"),
        _fact("into_stage3_facilities", "facilities moving into Stage 3",
              int(((m.stage_prev != 3) & (m.stage_latest == 3)).sum()),
              "count"),
        _fact("downgraded_borrowers", "downgraded borrowers",
              int((bl.rating_migration == "DOWNGRADE").sum()), "count"),
        _fact("watchlist_borrowers", "borrowers on the watch list",
              int((bl.watchlist_flag == 1).sum()), "count")]
    for st in (1, 2, 3):
        facts.append(_fact(f"stage{st}_ead_share_pct",
                           f"Stage {st} share of EAD (%)",
                           100 * tot(L, st) / ead_l, "percent"))
    return facts


def oracle_q10(fac, bor, L, P):
    return {"tables": [], "facts": _book_facts(fac, bor, L, P),
            "causal": "UNVERIFIABLE unless directly supported"}


def oracle_q11(fac, bor, L, P):
    d = fac[fac.reporting_quarter == L]
    t = d.groupby("sector", as_index=False)["ead_sar_mn"].sum()
    return {"tables": [_table("ead_by_sector", ["sector"], ["ead_sar_mn"],
                              t, units={"ead_sar_mn": "money"})],
            "facts": [_fact("total_ead", "portfolio EAD",
                            d.ead_sar_mn.sum(), "money")]}


def oracle_q12(fac, bor, L, P):
    d = fac[(fac.reporting_quarter == L) & (fac.stage == 3)]
    t = d.groupby("sector", as_index=False).agg(
        ead_sar_mn=("ead_sar_mn", "sum"), ecl_sar_mn=("ecl_sar_mn", "sum"))
    return {"tables": [_table("stage3_by_sector", ["sector"],
                              ["ead_sar_mn", "ecl_sar_mn"], t,
                              rank_by="ead_sar_mn",
                              units={"ead_sar_mn": "money",
                                     "ecl_sar_mn": "money"})],
            "facts": [_fact("stage3_ead_total", "Stage 3 EAD",
                            t.ead_sar_mn.sum(), "money"),
                      _fact("stage3_ecl_total", "Stage 3 ECL",
                            t.ecl_sar_mn.sum(), "money")]}


def oracle_q13(fac, bor, L, P):
    d = fac[(fac.reporting_quarter == L) & (fac.stage == 2)]
    total = d.ead_sar_mn.sum()
    s = d.groupby("sector", as_index=False)["ead_sar_mn"].sum()
    s["share_pct"] = 100 * s.ead_sar_mn / total
    b = d.groupby(["borrower_id", "borrower_name"], as_index=False)[
        "ead_sar_mn"].sum()
    b["share_pct"] = 100 * b.ead_sar_mn / total
    u = {"ead_sar_mn": "money", "share_pct": "percent"}
    return {"tables": [
        _table("stage2_sector_concentration", ["sector"],
               ["ead_sar_mn", "share_pct"], s, rank_by="ead_sar_mn",
               units=u),
        _table("stage2_top10_borrower_concentration", ["borrower_id"],
               ["ead_sar_mn", "share_pct"], b, rank_by="ead_sar_mn",
               top_n=10, units=u)],
        "facts": [_fact("stage2_ead_total", "Stage 2 EAD total", total,
                        "money")]}


def oracle_q14(fac, bor, L, P):
    m, _, _ = _pairs(fac, L, P)
    mv = m[(m.stage_prev.isin([1, 2])) & (m.stage_latest == 3)]
    g = mv.groupby("borrower_id", as_index=False).agg(
        ead_sar_mn=("ead_sar_mn_latest", "sum"),
        ecl_sar_mn=("ecl_sar_mn", "sum"),
        facilities=("facility_id", "count"))
    b = bor[bor.reporting_quarter == L][["borrower_id", "borrower_name",
                                         "sector", "rating_current"]]
    t = g.merge(b, on="borrower_id", how="left")
    return {"tables": [_table("borrowers_into_stage3", ["borrower_id"],
                              ["ead_sar_mn", "ecl_sar_mn"], t,
                              units={"ead_sar_mn": "money",
                                     "ecl_sar_mn": "money"})],
            "facts": [_fact("borrowers_into_stage3", "borrowers moving into "
                            "Stage 3", len(t), "count"),
                      _fact("facilities_into_stage3", "facilities moving "
                            "into Stage 3", len(mv), "count"),
                      _fact("ead_into_stage3", "EAD moving into Stage 3",
                            mv.ead_sar_mn_latest.sum(), "money")]}


def oracle_q15(fac, bor, L, P):
    return {"tables": [], "facts": _book_facts(fac, bor, L, P),
            "review": "overall riskiness and causes are review-only; the "
                      "fact set checks quantitative claims"}


ORACLES = {f"Q{i:02d}": globals()[f"oracle_q{i:02d}"] for i in range(1, 16)}


# ---- wrong-population references (diagnostics only) -----------------------

def _wrong_refs(qid, fac, bor, L, P) -> dict[str, dict]:
    """What common mistakes would produce. Never used as truth."""
    import pandas as pd
    out: dict[str, dict] = {}
    run = ORACLES[qid]
    other = fac[fac.reporting_quarter == P]
    swapped = pd.concat([other.assign(reporting_quarter=L),
                         fac[fac.reporting_quarter == P]])
    out["WRONG_QUARTER"] = run(swapped, bor, L, P)
    for wrong_stage in (1, 3):
        f2 = fac.copy()
        f2["stage"] = f2["stage"].replace({2: -1, wrong_stage: 2,
                                           -1: wrong_stage})
        out[f"WRONG_STAGE_{wrong_stage}"] = run(f2, bor, L, P)
    allq = fac.assign(reporting_quarter=L)
    out["NO_QUARTER_FILTER"] = run(allq, bor, L, P)
    # join on borrower_id only: facilities repeat once per borrower quarter
    nq = bor.groupby("borrower_id").size().rename("k")
    infl = fac.join(nq, on="borrower_id")
    for c in ("ead_sar_mn", "ecl_sar_mn"):
        infl[c] = infl[c] * infl["k"]
    out["DUPLICATE_JOIN_INFLATION"] = run(infl.drop(columns="k"), bor, L, P)
    return out


# ---- public API -------------------------------------------------------------

def code_sha256() -> str:
    import sys
    src = inspect.getsource(sys.modules[__name__])
    return hashlib.sha256(src.encode()).hexdigest()


@functools.lru_cache(maxsize=64)
def _compute(qid: str, release: str) -> str:
    fac, bor, L, P = _frames(release)
    res = ORACLES[qid](fac, bor, L, P)
    out = {"question_id": qid, "oracle_version": ORACLE_SUITE_VERSION,
           "code_sha256": code_sha256(), "release_id": release,
           "latest_quarter": L, "preceding_quarter": P,
           "question": bq.get(qid).text,
           "spec": {**SPECS.get(qid, {}), **COMMON},
           "oracle_kind": bq.get(qid).oracle_kind, **res}
    return json.dumps(out, sort_keys=True, default=str)


def expected(qid: str, release: str = RELEASE) -> dict[str, Any]:
    out = json.loads(_compute(qid, release))
    out["data_snapshot_id"] = snapshot_id(release)
    return out


@functools.lru_cache(maxsize=64)
def _wrong(qid: str, release: str) -> str:
    fac, bor, L, P = _frames(release)
    return json.dumps(_wrong_refs(qid, fac, bor, L, P), default=str)


def wrong_references(qid: str, release: str = RELEASE) -> dict[str, Any]:
    return json.loads(_wrong(qid, release))


def materialize(out_dir: Path, release: str = RELEASE) -> dict[str, str]:
    """Write every expected-result artifact; return {qid: sha256}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for qid in ORACLES:
        data = json.dumps(expected(qid, release), indent=1, sort_keys=True,
                          default=str).encode()
        (out_dir / f"{qid}.json").write_bytes(data)
        hashes[qid] = hashlib.sha256(data).hexdigest()
    (out_dir / "ORACLE_MANIFEST.json").write_text(json.dumps({
        "oracle_version": ORACLE_SUITE_VERSION, "code_sha256": code_sha256(),
        "data_snapshot_id": snapshot_id(release), "artifacts": hashes},
        indent=1, sort_keys=True))
    return hashes


# ---- grading ----------------------------------------------------------------

def _norm_key(v: Any) -> str:
    if isinstance(v, bool):
        return str(int(v))
    try:
        f = float(v)
        if math.isfinite(f) and f.is_integer():
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return " ".join(str(v).split()).casefold()


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _close(a: float, b: float, unit: str) -> bool:
    if unit == "count":
        return abs(a - b) <= COUNT_TOL + 1e-9
    if unit == "percent":
        return abs(a - b) <= 0.01 + 1e-9
    return abs(a - b) <= max(ABS_TOL, REL_TOL * abs(b)) + 1e-9


def _key_candidates(exp: dict, rows: list[dict]) -> list[dict[str, str]]:
    """Every plausible assignment of candidate columns to expected keys.
    Two keys over the same values (stage_prev / stage_latest) are only
    told apart by which assignment makes the metrics reconcile."""
    import itertools
    cols = list(rows[0].keys()) if rows else []
    options = []
    for k in exp["keys"]:
        want = {_norm_key(r[k]) for r in exp["rows"]}
        scored = []
        for c in cols:
            have = {_norm_key(r.get(c)) for r in rows}
            j = len(want & have) / max(1, len(want | have))
            if j > 0:
                scored.append((j, c == k, c))
        scored.sort(reverse=True)
        options.append([c for _, _, c in scored[:4]])
    if not all(options):
        return []
    out = []
    for combo in itertools.product(*options):
        if len(set(combo)) == len(combo):
            out.append(dict(zip(exp["keys"], combo, strict=True)))
    return out[:24]


def match_table(exp: dict, rows: list[dict]) -> dict[str, Any]:
    """How well candidate rows reproduce an expected table (values only)."""
    if not rows:
        return {"matched": False, "reason": "no rows"}
    tries = [_match(exp, rows, kc) for kc in _key_candidates(exp, rows)]
    if not tries:
        return {"matched": False, "reason": "no candidate column holds the "
                "expected keys"}
    return max(tries, key=lambda r: (r["matched"], r["_score"]))


def _match(exp: dict, rows: list[dict], kc: dict[str, str]
           ) -> dict[str, Any]:
    def key(r, cols):
        return tuple(_norm_key(r.get(cols[k])) for k in exp["keys"])
    ident = {k: k for k in exp["keys"]}
    want = {key(r, ident): r for r in exp["rows"]}
    have: dict[tuple, dict] = {}
    dupes = 0
    for r in rows:
        k = key(r, kc)
        if all(x in ("", "none", "nan") for x in k):
            continue
        if k in have:
            dupes += 1
        have.setdefault(k, r)
    extra = [k for k in have if k not in want]
    missing = [k for k in want if k not in have]
    metric_cols, mism = {}, {}
    ncols = [c for c in rows[0] if c not in kc.values()]
    for m in exp["metrics"]:
        unit = exp["units"].get(m, "money")
        best, best_hits = None, -1
        for c in ncols:
            if c in metric_cols.values():
                continue
            hits = 0
            for k, er in want.items():
                cr = have.get(k)
                a, b = (_num(cr.get(c)) if cr else None), _num(er.get(m))
                if a is not None and b is not None and _close(a, b, unit):
                    hits += 1
            if hits > best_hits:
                best, best_hits = c, hits
        metric_cols[m] = best
        bad = []
        for k, er in want.items():
            cr = have.get(k)
            a = _num(cr.get(best)) if (cr and best) else None
            b = _num(er.get(m))
            if b is not None and (a is None or not _close(a, b, unit)):
                bad.append({"key": list(k), "expected": b, "actual": a})
        if bad:
            mism[m] = bad
    ratios = []
    for bad in mism.values():
        for x in bad:
            if x["actual"] and x["expected"]:
                ratios.append(x["actual"] / x["expected"])
    order_ok = None
    if exp.get("ordered"):
        seq = [key(r, kc) for r in rows if key(r, kc) in want]
        exp_seq = [key(r, ident) for r in exp["rows"]]
        order_ok = seq[:len(exp_seq)] == exp_seq
    top_n = exp.get("top_n")
    if top_n:
        seq = [key(r, kc) for r in rows]
        extra = [k for k in seq[:top_n] if k not in want]
        missing = [k for k in want if k not in seq[:top_n]]
    matched = not extra and not missing and not mism and \
        (order_ok is not False) and dupes == 0
    score = -(len(extra) + len(missing) + sum(len(v) for v in mism.values()))
    return {"matched": matched, "_score": score, "key_columns": kc,
            "metric_columns": metric_cols, "missing_keys": missing[:20],
            "extra_keys": extra[:20], "duplicate_keys": dupes,
            "mismatches": {m: v[:10] for m, v in mism.items()},
            "order_ok": order_ok,
            "inflation_ratio_min": min(ratios) if ratios else None}


def grade_table(qid: str, table_name: str, rows: list[dict],
                release: str = RELEASE) -> dict[str, Any]:
    exp = next(t for t in expected(qid, release)["tables"]
               if t["name"] == table_name)
    res = match_table(exp, rows)
    if res["matched"]:
        return res | {"outcome": "PASS", "diagnosis": []}
    diag = []
    for label, ref in wrong_references(qid, release).items():
        alt = next((t for t in ref.get("tables") or []
                    if t["name"] == table_name), None)
        if alt and alt["rows"] and match_table(alt, rows)["matched"]:
            diag.append(label)
    if res.get("duplicate_keys"):
        diag.append("DUPLICATE_ROWS")
    r = res.get("inflation_ratio_min")
    if r and r > 1.0 and "DUPLICATE_JOIN_INFLATION" not in diag and \
            not res.get("missing_keys"):
        diag.append("VALUES_INFLATED")
    if res.get("order_ok") is False:
        diag.append("WRONG_ORDER")
    if exp.get("top_n") and (res.get("extra_keys") or
                             res.get("missing_keys")):
        diag.append("WRONG_TOP_N")
    return res | {"outcome": "FAIL", "diagnosis": diag or ["VALUE_MISMATCH"]}


def check_facts(qid: str, values: list[tuple[float, str | None]],
                release: str = RELEASE) -> list[dict[str, Any]]:
    """Each asserted number: consistent with an oracle fact or table cell?
    Never CONTRADICTED on a mere miss -- a number can legitimately be one
    the oracle does not list (it is then NEEDS_REVIEW)."""
    ex = expected(qid, release)
    pool = [(f["value"], f["unit"], f["fact_id"]) for f in ex["facts"]]
    for t in ex["tables"]:
        for r in t["rows"]:
            for m in t["metrics"]:
                v = _num(r.get(m))
                if v is not None:
                    pool.append((v, t["units"].get(m, "money"),
                                 f"{t['name']}.{m}"))
    out = []
    for val, unit_class in values:
        hit = next((p for p in pool if (unit_class in (None, p[1]))
                    and _close(val, p[0], p[1])), None)
        out.append({"value": val, "unit_class": unit_class,
                    "status": "CONSISTENT_WITH_ORACLE" if hit else
                    "NOT_IN_ORACLE_FACTS",
                    "oracle_ref": hit[2] if hit else None})
    return out


def oracle_numbers(qid: str, release: str = RELEASE) -> set[str]:
    """Formatted forms of every material oracle number (leak tests)."""
    ex = expected(qid, release)
    vals = [f["value"] for f in ex["facts"]]
    for t in ex["tables"]:
        for r in t["rows"]:
            vals += [r[m] for m in t["metrics"] if _num(r.get(m)) is not None]
    out = set()
    for v in vals:
        v = float(v)
        if abs(v) < 1000:          # small numbers collide with anything
            continue
        out |= {f"{v:.2f}", f"{v:,.2f}"}
        # A rounded form only for large whole numbers that cannot be a year
        # or a quarter label (2021Q3 is calendar metadata, not a leak).
        if v.is_integer() and not 1900 <= v <= 2100:
            out.add(str(int(v)))
    return out
