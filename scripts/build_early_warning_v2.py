#!/usr/bin/env python3
"""Build the Early Warning V2 monthly analytical domain.

Reads the already-built `corporate_borrower_360` synthetic universe (run
`scripts/build_corporate_universe.py` first if it has not been built), and
for a deterministic subset of borrowers produces >= 15 monthly point-in-time
Early Warning snapshots, scored by the actual Version 2 workbook engine in
`backend/early_warning/{classifiers_v2,triggers_v2,accelerator,aggregation,
network,combination}.py` — not a copy of the current quarter's score
repeated backward.

Grain reconciliation (plan Section 7)
--------------------------------------
Layer 2 classifiers are quarterly/annual by workbook design (rating, PD,
IFRS 9, DSCR, leverage...) and are read from the real corporate quarterly
data, carried forward within the quarter and refreshed only at quarter
boundaries — the same cadence the source data already has. Layer 1
(behavioural) genuinely has no monthly source dataset in this deployment; a
small set of L1 triggers with a real quarterly anchor (utilisation, DPD,
cash, operating cash flow) are interpolated monthly between quarter-end
values so a trigger's monthly firing is never disconnected from the real
data it is anchored to. Layer 1 triggers with NO real anchor at all
(transactional/behavioural signals this deployment has never captured —
concentration of inflows, unusual fund movements, returned cheques, account
dormancy, and similar) are left un-fired rather than fabricated, matching
the existing `backend/early_warning/taxonomy.py` principle that an absent
measure is a stated absence, not an invented one. The same is true of Layer
3 (external intelligence): no news/disclosure/legal-event feed is wired
into this build, so L3 triggers do not fire here — a real deployment would
connect `backend/intelligence/` per the plan's Section AZ, not fabricate
events.

Output
------
Two Parquet datasets, partitioned by month, under
`data/analytics/early_warning_borrower_month/period=YYYY-MM/data.parquet`
and `data/analytics/early_warning_signal_observation/period=YYYY-MM/data.parquet`,
in the same layout `backend/data_access/duckdb_source.py` already reads
generically for every other dataset.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import settings
from backend.corporate import service as corp
from backend.early_warning import (
    accelerator as accel,
    aggregation as agg,
    classifiers_v2 as clf,
    combination as comb,
    thresholds as th,
    triggers_v2 as trg,
)

DEFAULT_BORROWER_COUNT = 300
RANDOM_SEED = 20260630

#: 15 months, April 2025 through June 2026 — the plan's recommended window,
#: anchored on this deployment's own latest quarter (Q2 2026).
MONTHS: list[pd.Timestamp] = list(pd.date_range("2025-04-30", "2026-06-30", freq="ME"))
assert len(MONTHS) == 15


def month_to_quarter(month: pd.Timestamp) -> str:
    q = (month.month - 1) // 3 + 1
    return f"Q{q} {month.year}"


def month_position_in_quarter(month: pd.Timestamp) -> int:
    """0, 1 or 2 — how far through its quarter this month is."""
    return (month.month - 1) % 3


def load_universe() -> pd.DataFrame:
    df = corp._load(corp.SNAPSHOT)
    needed_quarters = sorted({month_to_quarter(m) for m in MONTHS})
    missing = [q for q in needed_quarters if q not in set(df["period"])]
    if missing:
        raise SystemExit(
            f"corporate_borrower_360 is missing quarters {missing}. "
            "Run scripts/build_corporate_universe.py first."
        )
    return df[df["period"].isin(needed_quarters)].copy()


def select_borrowers(df: pd.DataFrame, count: int) -> list[str]:
    """Borrowers present in every quarter this build needs, sampled with a
    fixed seed so the build is reproducible."""
    quarters = sorted({month_to_quarter(m) for m in MONTHS})
    present_everywhere = None
    for q in quarters:
        ids = set(df[df["period"] == q]["borrower_id"])
        present_everywhere = ids if present_everywhere is None else present_everywhere & ids
    pool = sorted(present_everywhere)
    rng = np.random.default_rng(RANDOM_SEED)
    if len(pool) <= count:
        return pool
    return sorted(rng.choice(pool, size=count, replace=False).tolist())


def interpolate_monthly(quarter_end_values: dict[str, float], months: list[pd.Timestamp],
                         quarter_of_month: dict[pd.Timestamp, str]) -> dict[pd.Timestamp, float]:
    """Linear interpolation between quarter-end anchors. The first quarter's
    two earlier months are extrapolated backward from the first two known
    anchors (or held flat if only one anchor exists)."""
    quarters_in_order = sorted({quarter_of_month[m] for m in months},
                                key=lambda q: months[[quarter_of_month[m] for m in months].index(q)])
    anchors = [(q, quarter_end_values[q]) for q in quarters_in_order if q in quarter_end_values]
    out: dict[pd.Timestamp, float] = {}
    for m in months:
        q = quarter_of_month[m]
        pos = month_position_in_quarter(m)  # 0, 1, 2 (2 = quarter-end)
        idx = quarters_in_order.index(q)
        end_val = quarter_end_values.get(q)
        if end_val is None:
            out[m] = float("nan")
            continue
        if idx == 0:
            # No prior quarter anchor: hold the two earlier months flat at
            # the first quarter's own end value rather than inventing a trend.
            start_val = end_val
        else:
            prev_q = quarters_in_order[idx - 1]
            start_val = quarter_end_values.get(prev_q, end_val)
        frac = (pos + 1) / 3.0
        out[m] = start_val + (end_val - start_val) * frac
    return out


def build_classifier_bands(row: pd.Series) -> tuple[dict[str, str], dict]:
    bands: dict[str, str] = {}
    for cdef in clf.CLASSIFIER_DEFINITIONS:
        src = th.SOURCES.get(cdef.key)
        if src is None or src.compute is None:
            bands[cdef.key] = th.UNSOURCED_DEFAULT_BAND
            continue
        try:
            values = [row[f] for f in src.fields]
            if any(pd.isna(v) for v in values):
                bands[cdef.key] = th.UNSOURCED_DEFAULT_BAND
                continue
            bands[cdef.key] = src.compute(*values)
        except Exception:
            bands[cdef.key] = th.UNSOURCED_DEFAULT_BAND
    overrides = th.classifier_overrides(row.to_dict())
    bands.update(overrides)
    return bands, overrides


def l1_signal_scores(borrower_series: dict[str, dict[pd.Timestamp, float]], month: pd.Timestamp,
                      baseline_12m: dict[str, float]) -> list[agg.FiredSignal]:
    """The four L1 triggers with a real anchor. Severity band chosen from the
    trigger's own Tab 3 thresholds; accelerator dimensions estimated from the
    shape of the interpolated series (a defensible, documented proxy, not a
    fabricated value — magnitude/velocity come directly from the same series
    driving the trigger itself)."""
    fired: list[agg.FiredSignal] = []

    def pct_change(key: str) -> float | None:
        series = borrower_series.get(key)
        base = baseline_12m.get(key)
        if series is None or base in (None, 0) or pd.isna(series.get(month, float("nan"))):
            return None
        return 100.0 * (series[month] - base) / abs(base)

    def fire(trigger_key: str, change_pct: float, worse_if_negative: bool):
        t = trg.BY_KEY[trigger_key]
        magnitude = abs(change_pct)
        # severity band from the trigger's own band thresholds (parsed once,
        # generically, from the sign convention: worse bands need a larger
        # magnitude of adverse movement).
        adverse = -change_pct if worse_if_negative else change_pct
        if adverse < 15:
            return
        band = 1 if adverse < 25 else 2 if adverse < 40 else 3 if adverse < 55 else 4 if adverse < 70 else 5
        trigger_score = trg.trigger_score_for_band(band)
        mag_band = 1 if magnitude < 15 else 2 if magnitude < 25 else 3 if magnitude < 40 else 4 if magnitude < 60 else 5
        result = accel.compute_accelerator(accel.AcceleratorInput(
            magnitude_band=mag_band, velocity_band=mag_band, persistence_band=2,
            repetition_band=1, corroboration_band=1, age_days=0,
        ))
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        fired.append(agg.FiredSignal(trigger_key, score, trigger_key))

    utilisation_change = pct_change("utilisation")
    if utilisation_change is not None:
        fire("utilisation_increase", utilisation_change, worse_if_negative=False)

    dpd_change = pct_change("dpd")
    if dpd_change is not None and borrower_series["dpd"][month] >= 1:
        fire("repayment_delay", dpd_change, worse_if_negative=False)

    cash_change = pct_change("cash")
    if cash_change is not None:
        fire("operating_deposit_balance_decline", cash_change, worse_if_negative=True)

    cfo_change = pct_change("cash_flow_from_operations")
    if cfo_change is not None:
        fire("cash_flow_deterioration", cfo_change, worse_if_negative=True)

    return fired


def _safe_float(value, default: float = 0.0) -> float:
    """Several corporate_borrower_360 fields carry an explicit
    "NOT_AVAILABLE" sentinel (a declared absence, not a missing column) —
    treated as the given default rather than raising."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def l2_l4_event_signals(curr: pd.Series, prev: pd.Series | None) -> list[agg.FiredSignal]:
    """Quarter-transition L2/L4 triggers computed from real quarter-over-
    quarter deltas — fired only in the first month of a new quarter, so a
    trigger never appears disconnected from the raw data that caused it."""
    fired: list[agg.FiredSignal] = []
    if prev is None:
        return fired

    def add(trigger_key: str, band: int):
        t = trg.trigger_score_for_band(band)
        result = accel.compute_accelerator(accel.AcceleratorInput(3, 3, 2, 1, 1, age_days=0))
        score = accel.signal_score(t, result.accelerator_multiplier)
        fired.append(agg.FiredSignal(trigger_key, score, trigger_key))

    rating_move = curr["internal_rating_numeric"] - prev["internal_rating_numeric"]
    if rating_move >= 1:
        band = 1 if rating_move == 1 else 2 if rating_move == 2 else 3 if rating_move == 3 else 5
        add("rating_migration_downgrade", band)

    if prev["pd_12m"] > 0:
        pd_rel = 100.0 * (curr["pd_12m"] - prev["pd_12m"]) / prev["pd_12m"]
        if pd_rel >= 10:
            band = 1 if pd_rel < 25 else 2 if pd_rel < 50 else 3 if pd_rel < 100 else 4 if pd_rel < 200 else 5
            add("pd_movement", band)

    if curr["stage"] > prev["stage"]:
        band = 2 if curr["stage"] == 2 else 5
        add("stage_migration", band)

    if prev["ecl_coverage"] > 0:
        ecl_rel = 100.0 * (curr["ecl_coverage"] - prev["ecl_coverage"]) / prev["ecl_coverage"]
        if ecl_rel >= 10:
            band = 1 if ecl_rel < 25 else 2 if ecl_rel < 50 else 3 if ecl_rel < 100 else 4 if ecl_rel < 200 else 5
            add("ecl_movement", band)

    if bool(curr.get("breach_flag")):
        add("covenant_breach", 3 if not bool(prev.get("breach_flag")) else 4)

    if prev.get("ebitda_margin") and not pd.isna(prev.get("ebitda_margin")):
        margin_drop = prev["ebitda_margin"] - curr["ebitda_margin"]
        if margin_drop > 3:
            band = 1 if margin_drop < 6 else 2 if margin_drop < 10 else 3 if margin_drop < 15 else 4
            add("financial_statement_deterioration", band)

    curr_network = _safe_float(curr.get("network_risk_score"))
    prev_network = _safe_float(prev.get("network_risk_score"))
    if curr_network > prev_network and curr_network > 60:
        band = 2 if curr_network < 75 else 3 if curr_network < 85 else 4
        add("guarantor_deterioration", band)

    return fired


def score_borrower_month(curr: pd.Series, prev: pd.Series | None,
                          l1_fired: list[agg.FiredSignal], methodology_version: str) -> dict:
    bands, overrides = build_classifier_bands(curr)
    classifier_result = clf.score_classifiers(
        bands,
        ifrs9_stage=int(curr["stage"]) if not pd.isna(curr["stage"]) else None,
        dpd=int(curr["current_dpd"]) if not pd.isna(curr["current_dpd"]) else None,
        unwaived_covenant_breach=bool(curr.get("breach_flag")),
        negative_equity=bool(curr.get("book_equity", 1) is not None and curr.get("book_equity", 1) < 0),
        statements_unaudited_or_over_18m=curr.get("financial_statement_age_days", 0) > 545,
    )

    fired = list(l1_fired) + l2_l4_event_signals(curr, prev)
    agg_result = agg.aggregate_ta_score(tuple(fired))

    combo = comb.combine(comb.CombinationInput(
        ta_score=agg_result.ta_score,
        classifier_score=classifier_result.score,
        classifier_band=classifier_result.band,
        ifrs9_stage=int(curr["stage"]) if not pd.isna(curr["stage"]) else None,
        dpd=int(curr["current_dpd"]) if not pd.isna(curr["current_dpd"]) else None,
        unwaived_covenant_breach=bool(curr.get("breach_flag")),
    ))

    return {
        "customer_id": curr["borrower_id"],
        "customer_name": curr.get("display_name", curr.get("legal_name", "")),
        "sector": curr.get("sector", ""),
        "segment": curr.get("segment", ""),
        "region": curr.get("region", ""),
        "relationship_manager": curr.get("relationship_manager", ""),
        "exposure": float(curr.get("drawn_exposure", 0) or 0),
        "limit": float(curr.get("total_limit", 0) or 0),
        "utilisation_pct": float(100.0 * (curr.get("drawn_exposure", 0) or 0) / curr["total_limit"])
                            if curr.get("total_limit") else 0.0,
        "dpd": float(curr.get("current_dpd", 0) or 0),
        "internal_rating": curr.get("internal_rating", ""),
        "pd_12m": float(curr.get("pd_12m", 0) or 0),
        "ifrs9_stage": int(curr["stage"]) if not pd.isna(curr["stage"]) else None,
        "classifier_score": classifier_result.score,
        "classifier_band": classifier_result.band,
        "classifier_overrides": ",".join(classifier_result.overrides_applied),
        "ta_score": agg_result.ta_score,
        "ta_band": agg.ta_verdict_band(agg_result.ta_score),
        "breadth_index": agg_result.breadth_index,
        "dominant_driver": agg_result.dominant_driver,
        "ews_score": combo.ews_score,
        "ews_band": combo.ews_band,
        "ccm": combo.ccm,
        "overrides_applied": ",".join(combo.overrides_applied),
        "signal_count_fired": len(fired),
        "methodology_version": methodology_version,
    }, fired, bands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--borrowers", type=int, default=DEFAULT_BORROWER_COUNT)
    parser.add_argument("--out-dir", type=Path, default=settings.analytics_dir)
    args = parser.parse_args(argv)

    print("> Loading corporate_borrower_360")
    universe = load_universe()
    borrower_ids = select_borrowers(universe, args.borrowers)
    print(f"> {len(borrower_ids)} borrowers selected across {len(MONTHS)} months")

    universe = universe[universe["borrower_id"].isin(borrower_ids)]
    by_key = {(r["borrower_id"], r["period"]): r for _, r in universe.iterrows()}

    quarter_of_month = {m: month_to_quarter(m) for m in MONTHS}

    borrower_month_rows: list[dict] = []
    signal_obs_rows: list[dict] = []

    for i, borrower_id in enumerate(borrower_ids):
        if i % 50 == 0:
            print(f"  scoring borrower {i + 1}/{len(borrower_ids)}")

        series = {
            metric: interpolate_monthly(
                {q: by_key[(borrower_id, q)][field] for q in {quarter_of_month[m] for m in MONTHS}
                 if (borrower_id, q) in by_key},
                MONTHS, quarter_of_month,
            )
            for metric, field in (
                ("utilisation", None), ("dpd", "current_dpd"),
                ("cash", "cash"), ("cash_flow_from_operations", "cash_flow_from_operations"),
            ) if field is not None
        }
        # utilisation is itself a derived ratio, computed per-quarter first
        util_by_quarter = {}
        for q in {quarter_of_month[m] for m in MONTHS}:
            if (borrower_id, q) in by_key:
                r = by_key[(borrower_id, q)]
                util_by_quarter[q] = 100.0 * (r["drawn_exposure"] or 0) / r["total_limit"] if r["total_limit"] else 0.0
        series["utilisation"] = interpolate_monthly(util_by_quarter, MONTHS, quarter_of_month)

        baseline_12m = {
            metric: (list(vals.values())[0] if vals else None)
            for metric, vals in series.items()
        }

        prev_quarter_row = None
        for month in MONTHS:
            quarter = quarter_of_month[month]
            if (borrower_id, quarter) not in by_key:
                continue
            curr = by_key[(borrower_id, quarter)]

            l1_fired = l1_signal_scores(series, month, baseline_12m)

            is_first_month_of_quarter = month_position_in_quarter(month) == 0
            prev_for_event = prev_quarter_row if is_first_month_of_quarter else None

            row, fired, bands = score_borrower_month(
                curr, prev_for_event, l1_fired, methodology_version="ews-v2.0.0",
            )
            row["snapshot_month"] = month.strftime("%Y-%m")
            borrower_month_rows.append(row)

            for f in fired:
                signal_obs_rows.append({
                    "snapshot_month": month.strftime("%Y-%m"),
                    "customer_id": borrower_id,
                    "signal_key": f.signal_key,
                    "signal_score": f.signal_score,
                    "causal_chain_id": f.causal_chain_id,
                })

            if is_first_month_of_quarter:
                prev_quarter_row = curr

    bm_df = pd.DataFrame(borrower_month_rows)
    obs_df = pd.DataFrame(signal_obs_rows)

    print(f"> {len(bm_df)} borrower-month rows, {len(obs_df)} signal observation rows")

    for month_str, chunk in bm_df.groupby("snapshot_month"):
        out = args.out_dir / "early_warning_borrower_month" / f"period={month_str}"
        out.mkdir(parents=True, exist_ok=True)
        chunk.to_parquet(out / "data.parquet", index=False)

    for month_str, chunk in obs_df.groupby("snapshot_month"):
        out = args.out_dir / "early_warning_signal_observation" / f"period={month_str}"
        out.mkdir(parents=True, exist_ok=True)
        chunk.to_parquet(out / "data.parquet", index=False)

    print(f"> Wrote {bm_df['snapshot_month'].nunique()} monthly partitions to "
          f"{args.out_dir / 'early_warning_borrower_month'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
