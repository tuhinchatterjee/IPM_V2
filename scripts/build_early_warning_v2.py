#!/usr/bin/env python3
"""Build the Early Warning V2 monthly analytical domain.

Reads the already-built `corporate_borrower_360` synthetic universe (run
`scripts/build_corporate_universe.py` first if it has not been built), and
for a deterministic subset of borrowers produces >= 15 monthly point-in-time
Early Warning snapshots, scored by the corrected Version 2 workbook engine:
`backend/early_warning/{classifiers_v2,subcategory,triggers_v2,accelerator,
aggregation,matrix,notches,combination}.py`.

This replaces an earlier build script written against a different,
incorrect workbook draft (flat 35-classifier weighted sum, flat breadth
aggregation, multiplicative combination). The pipeline here follows the
corrected hierarchy end to end: classifier/trigger bands -> sub-category
worst-of/blend -> layer-dimension roll-up -> T&A/Classifier dimensions ->
matrix anchor -> notches -> caps.

Grain reconciliation (Layer 2 quarterly, Layer 1 monthly-interpolated)
------------------------------------------------------------------------
Layer 2 classifiers are quarterly/annual by workbook design (rating, PD,
IFRS 9, DSCR, leverage...) and are read from the real corporate quarterly
data, carried forward within the quarter and refreshed only at quarter
boundaries — the same cadence the source data already has. Layer 1
(behavioural) genuinely has no monthly source dataset in this deployment; a
small set of L1 triggers with a real quarterly anchor (utilisation, DPD,
cash, operating cash flow) are interpolated monthly between quarter-end
values, with a genuine TRAILING baseline (a rolling window over the
borrower's own prior interpolated months, growing month by month — not a
single fixed reference value repeated across all 15 months, which is what
an earlier version of this script did). Layer 1 triggers with no real
anchor at all are left un-fired rather than fabricated.

Layer 3 (external intelligence) has no live news/disclosure/legal-event
feed in this deployment. Rather than leave it silently blank across the
whole demo, this script generates a governed, clearly-marked-synthetic
event dataset (`early_warning_external_event_synthetic`) — deterministic,
seeded per borrower, spanning all five L3 sub-categories, each row carrying
an evidence tier and a `scenario_status` of "SYNTHETIC_DEMONSTRATION_DATA".
It is built-time, persisted, governed data like every other dataset here —
never fabricated at answer time — and every consumer (lineage, reports,
evidence tables) can see that it is synthetic.

Layer 4's network T&A triggers reuse the real (if synthetic-demonstration)
`network_risk_score`/`corporate_connected_groups` already computed by
`backend/corporate/network.py`. Layer 4's classifier sub-category (L4.4,
Network fragility) sources two of its five classifiers — supplier
concentration and receivable concentration — from the real
`corporate_supply_chain` graph edges, computed once (Tab 03 marks both
"Annual" update frequency) and held constant across the 15-month build.

Decay/persistence
------------------
A trigger's decay is tracked per borrower per trigger key across the whole
15-month run. Continuous L1 conditions (utilisation, DPD, cash) hold at
decay 1.0 while their threshold condition remains met, and start decaying
from the month they drop below it (a genuine persistence hold). Discrete
L2/L3 events (a rating migration, a covenant breach, a synthetic external
event) are modelled as cured in the same month they occur — a documented
simplification, since the underlying data has no separate "resolved" flag
for these — and decay from that occurrence month onward using the class
half-life declared in `accelerator.py`. A later recurrence of the same
trigger resets its clock and increments its repetition band.

Output
------
Three Parquet datasets, partitioned by month:
`early_warning_borrower_month`, `early_warning_signal_observation`, and
`early_warning_external_event_synthetic`, in the same layout
`backend/data_access/duckdb_source.py` already reads generically.
"""

from __future__ import annotations

import argparse
import glob as globmod
import hashlib
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
    matrix,
    notches as nt,
    thresholds as th,
    triggers_v2 as trg,
)

METHODOLOGY_VERSION = "ews-v2.1.0"
DEFAULT_BORROWER_COUNT = 300
RANDOM_SEED = 20260630
DAYS_PER_MONTH = 30

#: 15 months, April 2025 through June 2026 — anchored on this deployment's
#: own latest quarter (Q2 2026).
MONTHS: list[pd.Timestamp] = list(pd.date_range("2025-04-30", "2026-06-30", freq="ME"))
assert len(MONTHS) == 15

#: The 28 L3 triggers eligible for synthetic event generation, with a
#: relative firing weight (rarer for severe events) and a source tier
#: (1 = bank/official system, 2 = established outlet, 3 = single/unverified
#: source) feeding the Evidence Quality notch.
L3_EVENT_CATALOGUE: tuple[tuple[str, float, int], ...] = (
    ("exchange_announcement_adverse", 1.0, 1),
    ("adverse_results_announcement", 1.0, 1),
    ("late_filing_or_restatement", 0.8, 1),
    ("commercial_registration_status_change", 0.4, 1),
    ("auditor_change_or_qualified_opinion", 0.6, 1),
    ("bankruptcy_or_insolvency_filing", 0.15, 1),
    ("material_litigation", 0.7, 2),
    ("regulatory_enforcement_action", 0.3, 1),
    ("sanctions_listing_or_match", 0.05, 1),
    ("external_rating_downgrade", 0.5, 1),
    ("outlook_or_watch_action", 0.6, 1),
    ("credit_spread_widening", 0.9, 2),
    ("equity_price_deterioration", 0.9, 2),
    ("contract_loss_or_cancellation", 0.8, 2),
    ("project_delay", 0.8, 2),
    ("profit_warning", 0.6, 1),
    ("fraud_allegation", 0.1, 3),
    ("senior_management_resignation", 0.5, 2),
    ("operational_or_plant_disruption", 0.4, 2),
    ("labour_disruption", 0.3, 2),
    ("cyber_incident", 0.2, 2),
    ("supply_chain_disruption", 0.7, 2),
    ("commodity_or_input_price_shock", 1.0, 1),
    ("fx_movement", 0.9, 1),
    ("real_estate_price_decline", 0.5, 1),
    ("sector_demand_contraction", 0.9, 1),
    ("interest_rate_shock", 0.6, 1),
    ("geopolitical_or_trade_disruption", 0.4, 2),
)
#: Base monthly probability that ANY L3 event fires for a given borrower,
#: scaled by the catalogue weights above. Tuned so a 300-borrower, 15-month
#: run produces a demonstrable but not overwhelming spread of L3 activity.
L3_MONTHLY_FIRE_PROBABILITY = 0.05


def month_to_quarter(month: pd.Timestamp) -> str:
    q = (month.month - 1) // 3 + 1
    return f"Q{q} {month.year}"


def month_position_in_quarter(month: pd.Timestamp) -> int:
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
    """Linear interpolation between quarter-end anchors, held flat before
    the first known anchor rather than extrapolated backward."""
    quarters_in_order = sorted({quarter_of_month[m] for m in months},
                                key=lambda q: months[[quarter_of_month[m] for m in months].index(q)])
    out: dict[pd.Timestamp, float] = {}
    for m in months:
        q = quarter_of_month[m]
        pos = month_position_in_quarter(m)
        idx = quarters_in_order.index(q)
        end_val = quarter_end_values.get(q)
        if end_val is None:
            out[m] = float("nan")
            continue
        if idx == 0:
            start_val = end_val
        else:
            prev_q = quarters_in_order[idx - 1]
            start_val = quarter_end_values.get(prev_q, end_val)
        frac = (pos + 1) / 3.0
        out[m] = start_val + (end_val - start_val) * frac
    return out


def trailing_baseline(series: dict[pd.Timestamp, float], months: list[pd.Timestamp],
                       month: pd.Timestamp, window: int = 12) -> float | None:
    """A genuine trailing baseline: the mean of up to `window` months
    strictly before `month`, growing as the build's own history grows
    rather than a single value fixed for the whole run. Falls back to the
    earliest available month when `month` itself is the first (no prior
    history exists before the build window)."""
    idx = months.index(month)
    prior = [series[m] for m in months[:idx] if not pd.isna(series.get(m, float("nan")))]
    if not prior:
        return series.get(month)
    return float(np.mean(prior[-window:]))


def build_sector_medians(full_universe: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Cross-sectional EBITDA margin median per (sector, quarter), computed
    over the FULL corporate universe (not just the sampled borrowers), for
    the ebitda_margin_vs_sector classifier."""
    medians: dict[tuple[str, str], float] = {}
    for (sector, period), chunk in full_universe.groupby(["sector", "period"]):
        vals = chunk["ebitda_margin"].dropna()
        if len(vals):
            medians[(sector, period)] = float(vals.median())
    return medians


def build_graph_concentration(borrower_ids: list[str]) -> dict[str, dict[str, float]]:
    """supplier_concentration_pct (top-3 buyer_cost_share_pct summed, this
    borrower as buyer) and receivable_concentration_pct (largest single
    supplier_revenue_share_pct, this borrower as supplier) from the real
    `corporate_supply_chain` graph edges — Tab 03 "Annual" cadence, computed
    once from the currently-active edges."""
    out: dict[str, dict[str, float]] = {b: {} for b in borrower_ids}
    files = globmod.glob(str(settings.analytics_dir / "corporate_supply_chain" / "**" / "*.parquet"),
                          recursive=True)
    if not files:
        return out
    edges = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    active = edges[edges["valid_to"].isna()] if "valid_to" in edges.columns else edges
    wanted = set(borrower_ids)

    as_buyer = active[active["to_node"].isin(wanted)]
    for borrower_id, chunk in as_buyer.groupby("to_node"):
        top3 = chunk["buyer_cost_share_pct"].sort_values(ascending=False).head(3)
        out.setdefault(borrower_id, {})["supplier_concentration_pct"] = float(top3.sum())

    as_supplier = active[active["from_node"].isin(wanted)]
    for borrower_id, chunk in as_supplier.groupby("from_node"):
        largest = chunk["supplier_revenue_share_pct"].max()
        out.setdefault(borrower_id, {})["receivable_concentration_pct"] = float(largest)

    return out


def generate_l3_events(borrower_ids: list[str]) -> pd.DataFrame:
    """Governed synthetic external-intelligence events, deterministic per
    borrower. Every row is marked `scenario_status="SYNTHETIC_DEMONSTRATION_DATA"`
    and carries a `source_tier` — never presented as a real feed, and never
    fabricated at answer time (this is a persisted, built-time dataset like
    every other one here)."""
    rows: list[dict] = []
    trigger_keys, weights, tiers = zip(*L3_EVENT_CATALOGUE)
    weights_arr = np.array(weights)
    probs = weights_arr / weights_arr.sum()

    for borrower_id in borrower_ids:
        seed = int(hashlib.sha256(f"l3:{borrower_id}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        for month in MONTHS:
            if rng.random() >= L3_MONTHLY_FIRE_PROBABILITY:
                continue
            idx = rng.choice(len(trigger_keys), p=probs)
            trigger_key = trigger_keys[idx]
            source_tier = tiers[idx]
            severity_band = int(rng.choice([1, 2, 3, 4, 5], p=[0.35, 0.30, 0.20, 0.10, 0.05]))
            rows.append({
                "snapshot_month": month.strftime("%Y-%m"),
                "customer_id": borrower_id,
                "trigger_key": trigger_key,
                "severity_band": severity_band,
                "source_tier": int(source_tier),
                "evidence_type": "ANALYTICAL_HYPOTHESIS" if source_tier >= 2 else "FACT_IN_CREDITPROBE_DATA",
                "scenario_status": "SYNTHETIC_DEMONSTRATION_DATA",
            })
    return pd.DataFrame(rows)


class TriggerDecayState:
    """Per-borrower, per-trigger-key decay/persistence state across the
    15-month build. Continuous conditions hold at decay 1.0 while still
    active; discrete events are cured the same month they occur (a
    documented simplification — see module docstring) and decay from
    there. A later recurrence resets the clock and raises repetition."""

    def __init__(self) -> None:
        self._first_seen_idx: dict[str, int] = {}
        self._cured_idx: dict[str, int | None] = {}
        self._occurrences: dict[str, int] = {}

    def observe(self, trigger_key: str, month_idx: int, *, continuous_active: bool | None = None) -> None:
        """Record that `trigger_key` fired this month. `continuous_active`
        True means the underlying condition is STILL active this month
        (persistence hold continues); False/None means it is a discrete
        event, cured immediately."""
        if trigger_key not in self._first_seen_idx:
            self._first_seen_idx[trigger_key] = month_idx
            self._occurrences[trigger_key] = 0
        was_cured = self._cured_idx.get(trigger_key) is not None
        if was_cured or trigger_key not in self._cured_idx:
            self._occurrences[trigger_key] += 1
        if continuous_active:
            self._cured_idx[trigger_key] = None
        else:
            self._cured_idx[trigger_key] = month_idx

    def decay_for(self, trigger_key: str, sub_category: str, month_idx: int) -> accel.DecayResult:
        first_seen = self._first_seen_idx.get(trigger_key, month_idx)
        cured_idx = self._cured_idx.get(trigger_key)
        age_days = (month_idx - first_seen) * DAYS_PER_MONTH
        if cured_idx is None:
            return accel.compute_decay(sub_category, cured=False, days_since_cure=0, age_days=age_days)
        days_since_cure = (month_idx - cured_idx) * DAYS_PER_MONTH
        return accel.compute_decay(sub_category, cured=True, days_since_cure=days_since_cure, age_days=age_days)

    def repetition_band(self, trigger_key: str) -> int:
        return min(5, max(1, self._occurrences.get(trigger_key, 1)))


def build_classifier_bands(row: pd.Series, extra: dict[str, float]) -> dict[str, str]:
    bands: dict[str, str] = {}
    lookup = {**row.to_dict(), **extra}
    for cdef in clf.CLASSIFIER_DEFINITIONS:
        src = th.SOURCES.get(cdef.key)
        if src is None or src.compute is None:
            bands[cdef.key] = th.UNSOURCED_DEFAULT_BAND
            continue
        try:
            values = [lookup[f] for f in src.fields]
            if any(v is None or (isinstance(v, float) and pd.isna(v)) for v in values):
                bands[cdef.key] = th.UNSOURCED_DEFAULT_BAND
                continue
            bands[cdef.key] = src.compute(*values)
        except Exception:
            bands[cdef.key] = th.UNSOURCED_DEFAULT_BAND
    return bands


def magnitude_band_from_pct(pct: float) -> int:
    return 1 if pct < 15 else 2 if pct < 25 else 3 if pct < 40 else 4 if pct < 60 else 5


def severity_band_from_adverse_pct(pct: float) -> int | None:
    if pct < 15:
        return None
    return 1 if pct < 25 else 2 if pct < 40 else 3 if pct < 55 else 4 if pct < 70 else 5


def l1_signal_scores(borrower_series: dict[str, dict[pd.Timestamp, float]], month: pd.Timestamp,
                      months: list[pd.Timestamp], state: TriggerDecayState) -> list[agg.FiredSignal]:
    """The four L1 triggers with a real monthly anchor, using a genuine
    trailing baseline (see `trailing_baseline`) rather than one value fixed
    across the whole run."""
    fired: list[agg.FiredSignal] = []
    month_idx = months.index(month)

    def pct_change(key: str) -> float | None:
        series = borrower_series.get(key)
        if series is None or pd.isna(series.get(month, float("nan"))):
            return None
        base = trailing_baseline(series, months, month)
        if base in (None, 0) or pd.isna(base):
            return None
        return 100.0 * (series[month] - base) / abs(base)

    def fire(trigger_key: str, change_pct: float, worse_if_negative: bool):
        t = trg.BY_KEY[trigger_key]
        magnitude = abs(change_pct)
        adverse = -change_pct if worse_if_negative else change_pct
        band = severity_band_from_adverse_pct(adverse)
        if band is None:
            return
        trigger_score = trg.trigger_score_for_band(band)
        mag_band = magnitude_band_from_pct(magnitude)
        state.observe(trigger_key, month_idx, continuous_active=True)
        decay = state.decay_for(trigger_key, t.sub_category, month_idx)
        if not decay.in_scope:
            return
        result = accel.compute_accelerator(accel.AcceleratorInput(
            magnitude_band=mag_band, velocity_band=mag_band, persistence_band=3,
            repetition_band=state.repetition_band(trigger_key), corroboration_band=1,
            decay_factor=decay.decay_factor,
        ))
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        fired.append(agg.FiredSignal(trigger_key, score, trigger_key, t.sub_category))

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
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def l2_event_signals(curr: pd.Series, prev: pd.Series | None, month_idx: int,
                      state: TriggerDecayState) -> list[agg.FiredSignal]:
    """Quarter-transition L2 events — fired only in the first month of a
    new quarter, as discrete (immediately-cured) events."""
    fired: list[agg.FiredSignal] = []
    if prev is None:
        return fired

    def add(trigger_key: str, band: int):
        t = trg.BY_KEY[trigger_key]
        trigger_score = trg.trigger_score_for_band(band)
        state.observe(trigger_key, month_idx, continuous_active=False)
        decay = state.decay_for(trigger_key, t.sub_category, month_idx)
        if not decay.in_scope:
            return
        result = accel.compute_accelerator(accel.AcceleratorInput(
            3, 3, 2, state.repetition_band(trigger_key), 1, decay_factor=decay.decay_factor,
        ))
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        fired.append(agg.FiredSignal(trigger_key, score, trigger_key, t.sub_category))

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

    return fired


def l4_event_signals(curr: pd.Series, prev: pd.Series | None, month_idx: int,
                      state: TriggerDecayState) -> list[agg.FiredSignal]:
    """L4 network T&A triggers, proxied from the real DebtRank-based
    `network_risk_score` already computed by `backend.corporate.network`."""
    fired: list[agg.FiredSignal] = []
    if prev is None:
        return fired

    curr_network = _safe_float(curr.get("network_risk_score"))
    prev_network = _safe_float(prev.get("network_risk_score"))
    if curr_network > prev_network and curr_network > 60:
        band = 2 if curr_network < 75 else 3 if curr_network < 85 else 4
        t = trg.BY_KEY["guarantor_deterioration"]
        trigger_score = trg.trigger_score_for_band(band)
        state.observe("guarantor_deterioration", month_idx, continuous_active=False)
        decay = state.decay_for("guarantor_deterioration", t.sub_category, month_idx)
        if decay.in_scope:
            result = accel.compute_accelerator(accel.AcceleratorInput(3, 3, 2, 1, 1, decay_factor=decay.decay_factor))
            score = accel.signal_score(trigger_score, result.accelerator_multiplier)
            fired.append(agg.FiredSignal("guarantor_deterioration", score, "guarantor_deterioration", t.sub_category))

    return fired


def l3_event_signals(events_this_month: pd.DataFrame, month_idx: int,
                      state: TriggerDecayState) -> list[agg.FiredSignal]:
    fired: list[agg.FiredSignal] = []
    for _, ev in events_this_month.iterrows():
        trigger_key = ev["trigger_key"]
        t = trg.BY_KEY[trigger_key]
        trigger_score = trg.trigger_score_for_band(int(ev["severity_band"]))
        state.observe(trigger_key, month_idx, continuous_active=False)
        decay = state.decay_for(trigger_key, t.sub_category, month_idx)
        if not decay.in_scope:
            continue
        corroboration_band = 1 if ev["source_tier"] >= 2 else 3
        result = accel.compute_accelerator(accel.AcceleratorInput(
            3, 3, 2, state.repetition_band(trigger_key), corroboration_band, decay_factor=decay.decay_factor,
        ))
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        fired.append(agg.FiredSignal(trigger_key, score, f"{trigger_key}_{ev['snapshot_month']}", t.sub_category))
    return fired


def derive_notches(curr: pd.Series, month_fired: list[agg.FiredSignal],
                    ews_history: list[float], events_this_month: pd.DataFrame) -> dict[str, int]:
    """Documented, best-effort derivation of the five notches from real
    available fields — the workbook specifies the criteria (Tab 06 Section
    E), not a formula, so this mapping is an implementation choice."""
    connected_size = _safe_float(curr.get("connected_group_size"), 1.0)
    network_score = _safe_float(curr.get("network_risk_score"))
    if connected_size > 1 and network_score > 60:
        network_contagion = 1
    elif connected_size <= 1:
        network_contagion = -1
    else:
        network_contagion = 0

    if len(ews_history) >= 2:
        delta = ews_history[-1] - ews_history[-2]
        direction_of_travel = 1 if delta > 5 else -1 if delta < -5 else 0
    else:
        direction_of_travel = 0

    # Evidence quality: the tier of this month's L3 events, if any fired —
    # tier 1 (bank/official systems) improves confidence, tier 3
    # (unverified single source) weakens it. No L3 event this month means
    # every driving signal is internal bank data (tier 1) by construction.
    if len(events_this_month) == 0:
        evidence_quality = -1
    else:
        worst_tier = int(events_this_month["source_tier"].max())
        evidence_quality = 1 if worst_tier >= 3 else 0 if worst_tier == 2 else -1

    age_days = _safe_float(curr.get("financial_statement_age_days"), 0.0)
    if age_days > 365:
        data_staleness = 1
    elif age_days < 182:
        data_staleness = -1
    else:
        data_staleness = 0

    governance_event = any(f.signal_key in ("auditor_change_or_qualified_opinion", "senior_management_resignation")
                            for f in month_fired)
    management_and_governance = 1 if governance_event else 0

    return {
        "network_contagion": network_contagion,
        "direction_of_travel": direction_of_travel,
        "evidence_quality": evidence_quality,
        "data_staleness": data_staleness,
        "management_and_governance": management_and_governance,
    }


def score_borrower_month(curr: pd.Series, prev: pd.Series | None, l1_fired: list[agg.FiredSignal],
                          l3_fired: list[agg.FiredSignal], month_idx: int, state: TriggerDecayState,
                          ews_history: list[float], graph_extra: dict[str, float],
                          sector_medians: dict[tuple[str, str], float],
                          events_this_month: pd.DataFrame) -> tuple[dict, list[agg.FiredSignal]]:
    sector_median = sector_medians.get((curr.get("sector"), curr.get("period")))
    tenure_years = None
    if curr.get("relationship_start_date") is not None and not pd.isna(curr.get("relationship_start_date")):
        tenure_years = (pd.Timestamp(curr["period_end_date"]) - pd.Timestamp(curr["relationship_start_date"])).days / 365.25

    extra = {
        **graph_extra,
        "sector_median_ebitda_margin": sector_median,
        "relationship_tenure_years": tenure_years,
        "restructure_flag": bool(curr.get("restructure_flag", False)),
    }
    bands = build_classifier_bands(curr, extra)

    classifier_result = clf.score_classifiers(
        bands,
        ifrs9_stage=int(curr["stage"]) if not pd.isna(curr["stage"]) else None,
        dpd=int(curr["current_dpd"]) if not pd.isna(curr["current_dpd"]) else None,
        unwaived_covenant_breach=bool(curr.get("breach_flag")),
        negative_equity=th.negative_equity_flag(curr.get("book_equity")),
        statements_unaudited_or_over_18m=_safe_float(curr.get("financial_statement_age_days")) > 545,
        guarantor_in_default_load_bearing=False,
    )

    fired = list(l1_fired) + l2_event_signals(curr, prev, month_idx, state) \
        + l4_event_signals(curr, prev, month_idx, state) + l3_fired
    ta_result = agg.aggregate_ta_score(tuple(fired))

    notch_values = derive_notches(curr, fired, ews_history, events_this_month)

    combo = comb.combine(comb.CombinationInput(
        ta_score=ta_result.ta_score, ta_band=agg.ta_verdict_band(ta_result.ta_score),
        classifier_score=classifier_result.score, classifier_band=classifier_result.band,
        notch_values=notch_values,
        ifrs9_stage=int(curr["stage"]) if not pd.isna(curr["stage"]) else None,
        dpd=int(curr["current_dpd"]) if not pd.isna(curr["current_dpd"]) else None,
        unwaived_covenant_breach=bool(curr.get("breach_flag")),
    ))

    row = {
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
        "subcategory_scores": {**classifier_result.subcategory_scores, **ta_result.subcategory_scores},
        "layer_dimension_scores": {
            "l1_ta": ta_result.layer_scores.get("L1", 0.0), "l2_ta": ta_result.layer_scores.get("L2", 0.0),
            "l2_c": classifier_result.l2_c_score, "l3_ta": ta_result.layer_scores.get("L3", 0.0),
            "l4_ta": ta_result.layer_scores.get("L4", 0.0), "l4_c": classifier_result.l4_c_score,
        },
        "ta_score": ta_result.ta_score,
        "ta_band": agg.ta_verdict_band(ta_result.ta_score),
        "dominant_driver": ta_result.dominant_driver,
        "dominant_subcategory": ta_result.dominant_subcategory,
        "anchor_score": combo.anchor,
        "notches": combo.notch_result.values,
        "net_notches": combo.notch_result.net_notches_capped,
        "ews_score": combo.ews_score,
        "ews_band": combo.ews_band,
        "overrides_applied": ",".join(combo.overrides_applied),
        "signal_count_fired": len(fired),
        "methodology_version": METHODOLOGY_VERSION,
    }
    return row, fired


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--borrowers", type=int, default=DEFAULT_BORROWER_COUNT)
    parser.add_argument("--out-dir", type=Path, default=settings.analytics_dir)
    args = parser.parse_args(argv)

    print("> Loading corporate_borrower_360")
    full_universe = corp._load(corp.SNAPSHOT)
    universe = load_universe()
    borrower_ids = select_borrowers(universe, args.borrowers)
    print(f"> {len(borrower_ids)} borrowers selected across {len(MONTHS)} months")

    print("> Computing sector EBITDA margin medians (cross-sectional)")
    sector_medians = build_sector_medians(full_universe)

    print("> Computing supplier/receivable concentration from corporate_supply_chain")
    graph_extra = build_graph_concentration(borrower_ids)

    print("> Generating governed synthetic L3 external-intelligence events")
    l3_events = generate_l3_events(borrower_ids)
    print(f"  {len(l3_events)} synthetic L3 events across {len(borrower_ids)} borrowers")

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
                ("dpd", "current_dpd"), ("cash", "cash"),
                ("cash_flow_from_operations", "cash_flow_from_operations"),
            )
        }
        util_by_quarter = {}
        for q in {quarter_of_month[m] for m in MONTHS}:
            if (borrower_id, q) in by_key:
                r = by_key[(borrower_id, q)]
                util_by_quarter[q] = 100.0 * (r["drawn_exposure"] or 0) / r["total_limit"] if r["total_limit"] else 0.0
        series["utilisation"] = interpolate_monthly(util_by_quarter, MONTHS, quarter_of_month)

        state = TriggerDecayState()
        ews_history: list[float] = []
        borrower_l3 = l3_events[l3_events["customer_id"] == borrower_id] if len(l3_events) else l3_events
        borrower_extra = graph_extra.get(borrower_id, {})

        prev_quarter_row = None
        for month_idx, month in enumerate(MONTHS):
            quarter = quarter_of_month[month]
            if (borrower_id, quarter) not in by_key:
                continue
            curr = by_key[(borrower_id, quarter)]

            l1_fired = l1_signal_scores(series, month, MONTHS, state)
            month_str = month.strftime("%Y-%m")
            events_this_month = borrower_l3[borrower_l3["snapshot_month"] == month_str] if len(borrower_l3) else borrower_l3
            l3_fired = l3_event_signals(events_this_month, month_idx, state) if len(events_this_month) else []

            is_first_month_of_quarter = month_position_in_quarter(month) == 0
            prev_for_event = prev_quarter_row if is_first_month_of_quarter else None

            row, fired = score_borrower_month(
                curr, prev_for_event, l1_fired, l3_fired, month_idx, state, ews_history,
                borrower_extra, sector_medians, events_this_month,
            )
            row["snapshot_month"] = month_str
            borrower_month_rows.append(row)
            ews_history.append(row["ews_score"])

            for f in fired:
                signal_obs_rows.append({
                    "snapshot_month": month_str, "customer_id": borrower_id,
                    "signal_key": f.signal_key, "signal_score": f.signal_score,
                    "sub_category": f.sub_category, "causal_chain_id": f.causal_chain_id,
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

    if len(l3_events):
        for month_str, chunk in l3_events.groupby("snapshot_month"):
            out = args.out_dir / "early_warning_external_event_synthetic" / f"period={month_str}"
            out.mkdir(parents=True, exist_ok=True)
            chunk.to_parquet(out / "data.parquet", index=False)

    print(f"> Wrote {bm_df['snapshot_month'].nunique()} monthly partitions to "
          f"{args.out_dir / 'early_warning_borrower_month'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
