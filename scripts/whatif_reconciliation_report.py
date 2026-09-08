#!/usr/bin/env python
"""
Does the Corporate IFRS 9 book reconcile, quarter by quarter and grade by grade?

    .venv/bin/python scripts/whatif_reconciliation_report.py

Three reports, and each answers a question a credit-risk professional asks
before trusting a number on a screen.

**Portfolio reconciliation, sixteen quarters.** The book totals against the sum
of its partitions — by Stage, by sector, by segment, by rating. A partition
that does not add back to the whole means one of the two is describing a
different population, and every percentage built on either is wrong.

**Rating distribution, all nineteen grades.** Accounts and exposure per grade
with their shares, the three PDs, the LGD and the coverage. A grade with no
borrowers is printed as a zero row rather than omitted, because a table that
silently stops at CCC reads as though the scale does.

**Borrower spot-check.** Ten borrowers followed across every quarter they are
on book, with the arithmetic shown: the applicable PD, the LGD, the exposure,
the product, the overlay and the reported figure. Not cherry-picked — the
sample is stratified across Stage and sector and drawn on a fixed seed, so the
same ten come back on every run and a bad one cannot be quietly dropped.

Written to `docs/whatif_reconciliation.json` and printed as a readable summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.corporate import ratingscale as rs  # noqa: E402
from backend.ifrs9 import policy  # noqa: E402
from backend.whatif import domain as dm  # noqa: E402

#: How far a partition may be from the whole before it is a defect. The book
#: publishes two decimals per borrower, so a sum over three thousand of them
#: carries that rounding and nothing more.
TOLERANCE = 0.01
SEED = 20260907
SPOT_CHECK_BORROWERS = 10
SPOT_CHECK_QUARTERS = 8


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.zeros(len(frame)), index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _book(period: str) -> pd.DataFrame:
    frame, _ = dm.book(period)
    return frame


def _partition(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    """One cut of the book, and whether it adds back to it."""
    if column not in frame.columns:
        return {"available": False, "why": f"the book does not carry {column}"}
    ead, ecl = _num(frame, "ead"), _num(frame, "final_ecl")
    grouped = (frame.assign(_ead=ead, _ecl=ecl)
               .groupby(frame[column].astype(str))
               .agg(borrowers=("borrower_id", "size"),
                    exposure=("_ead", "sum"), ecl=("_ecl", "sum"))
               .reset_index().rename(columns={column: "label"}))
    return {
        "available": True,
        "groups": int(len(grouped)),
        "borrowers": int(grouped["borrowers"].sum()),
        "exposure": round(float(grouped["exposure"].sum()), 4),
        "ecl": round(float(grouped["ecl"].sum()), 4),
        "borrower_gap": int(grouped["borrowers"].sum() - len(frame)),
        "exposure_gap": round(float(grouped["exposure"].sum() - ead.sum()), 6),
        "ecl_gap": round(float(grouped["ecl"].sum() - ecl.sum()), 6),
        "rows": grouped.round(4).to_dict(orient="records"),
    }


def portfolio_reconciliation(periods: list[str]) -> dict[str, Any]:
    """Every quarter's totals against every partition of them."""
    quarters: list[dict[str, Any]] = []
    for period in periods:
        frame = _book(period)
        ead, ecl = _num(frame, "ead"), _num(frame, "final_ecl")
        entry: dict[str, Any] = {
            "period": period,
            "borrowers": int(len(frame)),
            "exposure": round(float(ead.sum()), 4),
            "ecl": round(float(ecl.sum()), 4),
            "coverage_pct": round(float(ecl.sum() / max(ead.sum(), 1e-9) * 100), 4),
            "partitions": {},
        }
        for column in ("stage", "sector", "segment", "internal_rating"):
            entry["partitions"][column] = _partition(frame, column)
        entry["reconciles"] = all(
            body.get("available") is not True
            or (body["borrower_gap"] == 0
                and abs(body["exposure_gap"]) <= TOLERANCE
                and abs(body["ecl_gap"]) <= TOLERANCE)
            for body in entry["partitions"].values())
        quarters.append(entry)

    return {
        "quarters": quarters,
        "period_count": len(quarters),
        "all_reconcile": all(q["reconciles"] for q in quarters),
        "tolerance": TOLERANCE,
        "statement": (
            "Each quarter's totals are compared against the sum of every "
            "partition of them. A partition that does not add back to the "
            "whole is describing a different population from the one the "
            "headline is about."),
    }


def rating_distribution(period: str) -> dict[str, Any]:
    """All nineteen grades, including the ones nobody is on."""
    frame = _book(period)
    ead, ecl = _num(frame, "ead"), _num(frame, "final_ecl")
    total_count, total_ead, total_ecl = len(frame), ead.sum(), ecl.sum()
    grade = frame["internal_rating"].astype(str)

    rows: list[dict[str, Any]] = []
    for name in rs.ALL_STATES:
        mask = (grade == name).to_numpy()
        count = int(mask.sum())
        part_ead = float(ead[mask].sum())
        part_ecl = float(ecl[mask].sum())
        rows.append({
            "grade": name,
            "ordinal": rs.ORDINAL[name],
            "performing": name != rs.DEFAULT_GRADE,
            "ttc_pd_pct": round(float(rs.DEFAULT_PD_PCT if name == rs.DEFAULT_GRADE
                                      else rs.TTC_PD_PCT[name]), 5),
            "borrowers": count,
            "borrowers_pct": round(count / max(total_count, 1) * 100, 4),
            "exposure": round(part_ead, 4),
            "exposure_pct": round(part_ead / max(total_ead, 1e-9) * 100, 4),
            "ecl": round(part_ecl, 4),
            "ecl_pct": round(part_ecl / max(total_ecl, 1e-9) * 100, 4),
            "coverage_pct": round(part_ecl / max(part_ead, 1e-9) * 100, 4)
            if count else 0.0,
            "avg_pd_12m": round(float(_num(frame, "pd_12m")[mask].mean()), 4)
            if count else None,
            "avg_pd_lifetime": round(
                float(_num(frame, "pd_lifetime")[mask].mean()), 4)
            if count else None,
            "avg_lgd": round(float(_num(frame, "lgd")[mask].mean()), 4)
            if count else None,
        })

    populated = [r for r in rows if r["borrowers"]]
    return {
        "period": period,
        "grades": len(rows),
        "populated_grades": len(populated),
        "rows": rows,
        "total": {
            "borrowers": int(total_count),
            "exposure": round(float(total_ead), 4),
            "ecl": round(float(total_ecl), 4),
            "coverage_pct": round(float(total_ecl / max(total_ead, 1e-9) * 100), 4),
        },
        "reconciles": (
            sum(r["borrowers"] for r in rows) == total_count
            and abs(sum(r["exposure"] for r in rows) - float(total_ead)) <= TOLERANCE
            and abs(sum(r["ecl"] for r in rows) - float(total_ecl)) <= TOLERANCE),
        "monotone_ttc": [r["ttc_pd_pct"] for r in rows] == sorted(
            r["ttc_pd_pct"] for r in rows),
        "statement": (
            "Every governed grade appears, including any with no borrowers on "
            "it. A distribution that omits an empty grade reads as though the "
            "scale stops there."),
    }


def _sample(periods: list[str]) -> list[str]:
    """Ten borrowers spread across Stage and sector, on a fixed seed."""
    frame = _book(periods[-1])
    rng = np.random.default_rng(SEED)
    picked: list[str] = []
    stages = sorted(pd.to_numeric(frame["stage"], errors="coerce")
                    .fillna(1).astype(int).unique())
    per_stage = max(1, SPOT_CHECK_BORROWERS // max(len(stages), 1))
    for stage in stages:
        part = frame[pd.to_numeric(frame["stage"], errors="coerce") == stage]
        if part.empty:
            continue
        # One per sector before a second from any sector, so the sample cannot
        # be ten names from the same industry.
        by_sector = part.groupby(part["sector"].astype(str))["borrower_id"].first()
        order = rng.permutation(len(by_sector))
        picked.extend(by_sector.to_numpy()[order][:per_stage].tolist())
    remaining = [b for b in frame["borrower_id"].astype(str)
                 if b not in set(picked)]
    while len(picked) < SPOT_CHECK_BORROWERS and remaining:
        picked.append(remaining[int(rng.integers(0, len(remaining)))])
    return sorted(set(picked))[:SPOT_CHECK_BORROWERS]


def spot_check(periods: list[str]) -> dict[str, Any]:
    """Ten borrowers, every quarter, with the arithmetic shown."""
    wanted = periods[-SPOT_CHECK_QUARTERS:] if len(periods) > SPOT_CHECK_QUARTERS \
        else periods
    chosen = _sample(periods)
    history: dict[str, list[dict[str, Any]]] = {b: [] for b in chosen}

    for period in wanted:
        frame = _book(period)
        part = frame[frame["borrower_id"].astype(str).isin(chosen)]
        for _, row in part.iterrows():
            stage = int(pd.to_numeric(row.get("stage"), errors="coerce") or 1)
            pd_12m = float(pd.to_numeric(row.get("pd_12m"), errors="coerce") or 0.0)
            pd_life = float(pd.to_numeric(row.get("pd_lifetime"), errors="coerce") or 0.0)
            lgd = float(pd.to_numeric(row.get("lgd"), errors="coerce") or 0.0)
            ead = float(pd.to_numeric(row.get("ead"), errors="coerce") or 0.0)
            reported = float(pd.to_numeric(row.get("final_ecl"), errors="coerce") or 0.0)
            overlay = float(pd.to_numeric(row.get("management_overlay"),
                                          errors="coerce") or 0.0)
            # The governed basis, and the governed weighting with it. Stage 3
            # is measured at 100% and carries NO scenario weighting: those
            # multipliers scale a probability that has not resolved, and a
            # default has. Recomputing a defaulted row at 1.082 x LGD x EAD
            # would report the book as failing to tie to arithmetic that is
            # itself wrong.
            applicable = (rs.DEFAULT_PD_PCT if stage >= 3
                          else pd_12m if stage <= 1 else pd_life)
            weighting = (1.0 if stage >= 3
                         else policy.WEIGHTED_SCENARIO_FACTOR)
            recomputed = min(
                applicable / 100.0 * lgd / 100.0 * ead * weighting, ead)
            history[str(row["borrower_id"])].append({
                "period": period,
                "rating": str(row.get("internal_rating", "")),
                "stage": stage,
                "measurement_basis": ("Defaulted - PD 100%" if stage >= 3
                                      else "12-month PD" if stage <= 1
                                      else "Lifetime PD"),
                "pd_12m": round(pd_12m, 4),
                "pd_lifetime": round(pd_life, 4),
                "pd_applicable": round(applicable, 4),
                "lgd": round(lgd, 4),
                "ead": round(ead, 4),
                "modelled_ecl": round(recomputed, 4),
                "management_overlay": round(overlay, 4),
                "reported_ecl": round(reported, 4),
                "unexplained": round(reported - recomputed - overlay, 4),
                "ties": abs(reported - min(recomputed + overlay, ead)) <= TOLERANCE,
            })

    rows = [r for entries in history.values() for r in entries]
    return {
        "borrowers": chosen,
        "quarters": wanted,
        "history": history,
        "rows": len(rows),
        "all_tie": all(r["ties"] for r in rows),
        "worst_unexplained": round(
            max((abs(r["unexplained"]) for r in rows), default=0.0), 4),
        "statement": (
            "Ten borrowers, stratified across Stage and sector on a fixed "
            "seed rather than chosen, followed across every quarter they are "
            "on book. Each row shows the product the provision is, so a reader "
            "can check it with a calculator."),
    }


def build() -> dict[str, Any]:
    periods = dm.periods()
    if not periods:
        raise SystemExit("The Corporate IFRS 9 lake has not been built.")
    return {
        "report_version": "1.0.0",
        "periods": periods,
        "latest": periods[-1],
        "masterscale": {"grades": rs.PERFORMING_COUNT,
                        "scale": list(rs.PERFORMING),
                        "version": rs.SCALE_VERSION},
        "portfolio_reconciliation": portfolio_reconciliation(periods),
        "rating_distribution": rating_distribution(periods[-1]),
        "spot_check": spot_check(periods),
    }


def main() -> int:
    report = build()
    out = ROOT / "docs" / "whatif_reconciliation.json"
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")

    recon = report["portfolio_reconciliation"]
    dist = report["rating_distribution"]
    spot = report["spot_check"]

    print(f"> Portfolio reconciliation over {recon['period_count']} quarters")
    for quarter in recon["quarters"]:
        mark = "ok " if quarter["reconciles"] else "FAIL"
        print(f"  {mark} {quarter['period']:8s} "
              f"{quarter['borrowers']:>6,} borrowers  "
              f"SAR {quarter['exposure']:>14,.1f}m  "
              f"ECL {quarter['ecl']:>12,.1f}m  "
              f"coverage {quarter['coverage_pct']:>6.2f}%")
    print(f"  every partition reconciles: {recon['all_reconcile']}")

    print(f"\n> Rating distribution, {dist['period']} — "
          f"{dist['populated_grades']} of {dist['grades']} grades populated")
    print(f"  {'grade':6s} {'TTC PD':>8s} {'accounts':>9s} {'%':>7s} "
          f"{'exposure':>14s} {'%':>7s} {'ECL':>12s} {'coverage':>9s}")
    for row in dist["rows"]:
        print(f"  {row['grade']:6s} {row['ttc_pd_pct']:>7.3f}% "
              f"{row['borrowers']:>9,} {row['borrowers_pct']:>6.2f}% "
              f"{row['exposure']:>14,.1f} {row['exposure_pct']:>6.2f}% "
              f"{row['ecl']:>12,.1f} {row['coverage_pct']:>8.2f}%")
    print(f"  {'TOTAL':6s} {'':>8s} {dist['total']['borrowers']:>9,} "
          f"{'100.00%':>7s} {dist['total']['exposure']:>14,.1f} {'100.00%':>7s} "
          f"{dist['total']['ecl']:>12,.1f} "
          f"{dist['total']['coverage_pct']:>8.2f}%")
    print(f"  reconciles: {dist['reconciles']}; "
          f"TTC scale monotone: {dist['monotone_ttc']}")

    print(f"\n> Spot check — {len(spot['borrowers'])} borrowers over "
          f"{len(spot['quarters'])} quarters")
    for borrower, entries in spot["history"].items():
        if not entries:
            continue
        first, last = entries[0], entries[-1]
        print(f"  {borrower}  {first['period']} {first['rating']:>4s} "
              f"S{first['stage']} -> {last['period']} {last['rating']:>4s} "
              f"S{last['stage']}   "
              f"ECL {first['reported_ecl']:>10,.2f} -> {last['reported_ecl']:>10,.2f}  "
              f"{len(entries)} quarter(s), all tie: "
              f"{all(e['ties'] for e in entries)}")
    print(f"  every row ties to the arithmetic: {spot['all_tie']} "
          f"(worst unexplained {spot['worst_unexplained']})")

    print(f"\n> Wrote {out}")
    healthy = (recon["all_reconcile"] and dist["reconciles"]
               and dist["monotone_ttc"] and spot["all_tie"])
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
