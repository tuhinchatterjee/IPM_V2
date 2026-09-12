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
import dataclasses
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
    lineage as lin,
    matrix,
    notches as nt,
    reasons,
    thresholds as th,
    triggers_v2 as trg,
)

METHODOLOGY_VERSION = "ews-v2.1.0"
DEFAULT_BORROWER_COUNT = 300
RANDOM_SEED = 20260630
DAYS_PER_MONTH = 30

#: The twenty month-ends the domain PUBLISHES, November 2024 through June
#: 2026 — anchored on this deployment's own latest quarter (Q2 2026).
VISIBLE_MONTHS: list[pd.Timestamp] = list(
    pd.date_range("2024-11-30", "2026-06-30", freq="ME"))
assert len(VISIBLE_MONTHS) == 20

#: How many months are computed BEFORE the first published one.
#:
#: Not padding. `trailing_baseline` averages up to twelve prior months and
#: falls back to the current value when there are none, so the first month of
#: a cold build compares every borrower against itself and no L1 trigger can
#: fire on it. The decay clock, the recurrence counter and the
#: direction-of-travel notch have the same problem: each reads state the build
#: accumulated, and each is simply absent in month one.
#:
#: Twelve months of warm-up means the earliest PUBLISHED month is scored the
#: same way as every month after it — against a full trailing baseline, with a
#: decay clock that has been running and a recurrence count that has had time
#: to count something. The warm-up months are computed and then discarded;
#: they are never published, so nothing reads a score that was itself produced
#: from a cold start.
PRE_HISTORY_MONTHS = 12

#: Every month the build COMPUTES, warm-up first and published last. The
#: scoring loop walks all of these; only the visible tail is written.
MONTHS: list[pd.Timestamp] = list(pd.date_range(
    VISIBLE_MONTHS[0] - pd.DateOffset(months=PRE_HISTORY_MONTHS),
    VISIBLE_MONTHS[-1], freq="ME"))
assert MONTHS[-len(VISIBLE_MONTHS):] == VISIBLE_MONTHS
assert len(MONTHS) == len(VISIBLE_MONTHS) + PRE_HISTORY_MONTHS

#: The published months as `YYYY-MM`, for the write filter and the tests.
VISIBLE_MONTH_KEYS: frozenset[str] = frozenset(
    m.strftime("%Y-%m") for m in VISIBLE_MONTHS)


def is_published(month: pd.Timestamp) -> bool:
    """Whether a computed month is one the domain publishes."""
    return month.strftime("%Y-%m") in VISIBLE_MONTH_KEYS

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


#: How bad a COUNTERPARTY has to be before its state is a warning about the
#: borrower that depends on it. These are the ordinary observable marks of
#: distress a credit officer would read off a name — stage, arrears, a
#: breach, a sub-investment-grade internal rating — not a second scoring
#: model. The severity band the trigger fires at then comes from how bad the
#: counterparty is AND how material it is to this borrower, which is what
#: "key supplier distress" means.
COUNTERPARTY_MATERIAL_PCT = 10.0


def counterparty_distress(row) -> int:
    """The severity band a distressed counterparty justifies, 0 for none."""
    if row is None:
        return 0
    stage = _safe_float(row.get("stage"), 1.0)
    dpd = _safe_float(row.get("current_dpd"))
    breach = bool(row.get("breach_flag"))
    grade = _safe_float(row.get("internal_rating_numeric"))
    if stage >= 3 or dpd >= 90:
        return 5
    if stage >= 2 and (breach or dpd >= 30):
        return 4
    if stage >= 2 or dpd >= 30:
        return 3
    if breach or grade >= 11:
        return 2
    if grade >= 9:
        return 1
    return 0


def build_relationships(borrower_ids: list[str]) -> dict[str, dict[str, list]]:
    """Each borrower's material suppliers, customers and group peers.

    From the real `corporate_supply_chain` edges and `corporate_connected_
    groups` membership — the same graph the Relationship product reads. The
    L4 triggers are all relationship-event triggers ("distress at a supplier
    the borrower depends on", "adverse event at a group entity"), so the
    input they need is the STATE OF THE COUNTERPARTY, not a centrality
    number.

    What was there before compared `network_risk_score` to an absolute 60.
    That field is a min-max normalised relative ranking over the whole
    corporate universe — its own published label says "RELATIVE NETWORK
    RANKING / NOT A PROBABILITY" — with a median of 3.4 and exactly one row
    above 60 in 3,300 borrower-quarters. So the L4 trigger could not fire,
    L4 T&A was identically zero for all 300 obligors in all 20 months, and a
    quarter of the model was dark.
    """
    out: dict[str, dict[str, list]] = {
        b: {"suppliers": [], "customers": [], "group": []} for b in borrower_ids}
    wanted = set(borrower_ids)

    files = globmod.glob(
        str(settings.analytics_dir / "corporate_supply_chain" / "**" / "*.parquet"),
        recursive=True)
    if files:
        edges = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        if "valid_to" in edges.columns:
            edges = edges[edges["valid_to"].isna() | (edges["valid_to"] == "")]
        for borrower_id, chunk in edges[edges["to_node"].isin(wanted)].groupby("to_node"):
            top = chunk.sort_values("buyer_cost_share_pct", ascending=False).head(5)
            out[borrower_id]["suppliers"] = [
                (str(r["from_node"]), float(r["buyer_cost_share_pct"] or 0.0))
                for _, r in top.iterrows()]
        for borrower_id, chunk in edges[edges["from_node"].isin(wanted)].groupby("from_node"):
            top = chunk.sort_values("supplier_revenue_share_pct", ascending=False).head(5)
            out[borrower_id]["customers"] = [
                (str(r["to_node"]), float(r["supplier_revenue_share_pct"] or 0.0))
                for _, r in top.iterrows()]

    files = globmod.glob(
        str(settings.analytics_dir / "corporate_connected_groups" / "**" / "*.parquet"),
        recursive=True)
    if files:
        groups = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        latest = groups.sort_values("period").drop_duplicates("borrower_id", keep="last")
        named = latest[latest["connected_group_id"].astype(str)
                       .str.startswith("CG-")]
        members: dict[str, list[str]] = {}
        for group_id, chunk in named.groupby("connected_group_id"):
            members[str(group_id)] = [str(b) for b in chunk["borrower_id"]]
        guarantees = dict(zip(latest["borrower_id"].astype(str),
                              pd.to_numeric(latest.get("guarantee_links"),
                                            errors="coerce").fillna(0)))
        for _, row in named.iterrows():
            borrower_id = str(row["borrower_id"])
            if borrower_id not in wanted:
                continue
            peers = [m for m in members.get(str(row["connected_group_id"]), [])
                     if m != borrower_id]
            out[borrower_id]["group"] = [
                (peer, float(guarantees.get(borrower_id, 0.0))) for peer in peers[:8]]
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


@dataclasses.dataclass
class LiveSignal:
    """A signal that has fired and has not yet decayed out of scope.

    Kept so it can be RE-EMITTED in later months at its decayed weight. The
    methodology's whole decay model — class-specific half-lives, a
    persistence hold while the condition is live, a floor — exists so that a
    fired signal fades over months rather than vanishing. This build computed
    the decay correctly and then threw the signal away the following month,
    so every signal was a one-month spike and the trigger-and-accelerator
    dimension only ever saw the events of the current month. Across 300
    obligors that put every one of them in the VERY_LOW T&A row of the
    published matrix, in every month.
    """

    trigger_key: str
    severity_band: int
    trigger_score: float
    accel_input: accel.AcceleratorInput
    causal_chain_id: str
    context: dict
    continuous: bool


class TriggerDecayState:
    """Per-borrower, per-trigger-key decay/persistence state across the
    15-month build. Continuous conditions hold at decay 1.0 while still
    active; discrete events are cured the same month they occur (a
    documented simplification — see module docstring) and decay from
    there. A later recurrence resets the clock and raises repetition.

    It also holds the LIVE SIGNALS, so a month can re-emit what fired
    earlier and has not yet decayed out of scope.
    """

    def __init__(self) -> None:
        self._first_seen_idx: dict[str, int] = {}
        self._cured_idx: dict[str, int | None] = {}
        self._occurrences: dict[str, int] = {}
        self._last_fired_idx: dict[str, int] = {}
        self._live: dict[str, LiveSignal] = {}

    def remember(self, live: LiveSignal) -> None:
        """Hold a signal open so later months can carry it at its decay."""
        self._live[live.trigger_key] = live

    def stop_if_running(self, trigger_key: str, month_idx: int) -> None:
        """A continuous condition that did not fire this month has ended.

        The cure clock starts here rather than never: without it a
        behavioural condition that held for one month would hold at full
        weight for the rest of the run, which is the opposite error to the
        one this carry-forward fixes.
        """
        if self._cured_idx.get(trigger_key, "missing") is None:
            self._cured_idx[trigger_key] = month_idx

    def carry(self, month_idx: int,
              fired_keys: set[str]) -> list[agg.FiredSignal]:
        """Every live signal that did not fire this month, at its decay.

        A signal whose decay has taken it out of scope is dropped from the
        registry rather than emitted at a floor value nobody would act on.
        """
        out: list[agg.FiredSignal] = []
        for key, live in list(self._live.items()):
            if key in fired_keys:
                continue
            if live.continuous:
                self.stop_if_running(key, month_idx)
            trigger = trg.BY_KEY[key]
            decay = self.decay_for(key, trigger.sub_category, month_idx)
            if not decay.in_scope:
                del self._live[key]
                continue
            faded = dataclasses.replace(live.accel_input,
                                        decay_factor=decay.decay_factor)
            result = accel.compute_accelerator(faded)
            out.append(agg.FiredSignal(
                key, accel.signal_score(live.trigger_score,
                                        result.accelerator_multiplier),
                live.causal_chain_id, trigger.sub_category,
                explanation=signal_explanation(
                    trigger, severity_band=live.severity_band,
                    trigger_score=live.trigger_score, accel_input=faded,
                    accel_result=result, decay=decay, state=self,
                    month_idx=month_idx, **live.context)))
        return out

    def observe(self, trigger_key: str, month_idx: int, *, continuous_active: bool | None = None) -> None:
        """Record that `trigger_key` fired this month. `continuous_active`
        True means the underlying condition is STILL active this month
        (persistence hold continues); False/None means it is a discrete
        event, cured immediately.

        The age clock measures the age of the CURRENT EPISODE, not of the
        first time this trigger ever fired for this borrower.

        That distinction decides whether the book stays alive. The
        methodology drops a signal from scoring once it is more than 400 days
        old — "an unresolved condition older than 400 days is flagged rather
        than scored forever at full weight", which is right. But the clock
        was started the first time the key fired and never restarted, so a
        supplier-distress reading that first fired in the warm-up aged out
        around month thirteen and never came back, even when a DIFFERENT
        supplier failed a year later. Over twenty months that quietly
        switched the network layer off: L4 fired for 241 obligors in the
        first published month and 30 in the last, while the book underneath
        was getting worse, not better.

        An episode ends when the trigger stops firing for a month. Firing
        again after that gap starts a new one, with a fresh clock and a
        higher recurrence count — which is what the class docstring said all
        along.
        """
        last = self._last_fired_idx.get(trigger_key)
        new_episode = last is None or month_idx - last > 1
        if new_episode:
            self._first_seen_idx[trigger_key] = month_idx
            self._occurrences[trigger_key] = self._occurrences.get(trigger_key, 0) + 1
        self._last_fired_idx[trigger_key] = month_idx
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


#: Severity band 1-5 as the band label the workbook's reason text is keyed
#: by. The canonical reason for a signal is the reason for its node at the
#: severity it fired, which is what makes it a reason rather than a restated
#: score.
_BAND_LABEL: dict[int, str] = {1: "VERY_LOW", 2: "LOW", 3: "MEDIUM",
                                4: "HIGH", 5: "VERY_HIGH"}


def signal_explanation(trigger, *, severity_band: int, trigger_score: float,
                        accel_input: accel.AcceleratorInput,
                        accel_result: accel.AcceleratorResult,
                        decay: accel.DecayResult, state: TriggerDecayState,
                        month_idx: int, source_tier: int | None = None,
                        observed_value: float | None = None,
                        baseline_value: float | None = None,
                        normalised_value: float | None = None,
                        observed_metric: str = "",
                        observed_unit: str = "") -> dict:
    """How one signal's score was reached, in flat, writable fields.

    Every value here is already computed to produce the score; without this
    the build threw them away and the score arrived at the reader as a bare
    number. The workbook asks each signal to be able to show its trigger
    severity, its five accelerator dimension bands and its decay; the
    customer report's lineage table asks it for its source system, signal
    class, half-life and applied decay factor. Both are answered from here.

    The reading itself is persisted too — the raw value observed, what it was
    measured against, and the normalised figure the severity band was taken
    from. A signal that can show its bands but not the number it saw is a
    signal whose evidence stops one step short of the thing a credit officer
    would actually check.
    """
    decay_class = accel.SUBCATEGORY_DECAY_CLASS.get(trigger.sub_category)
    first_seen = state._first_seen_idx.get(trigger.key, month_idx)
    cured_idx = state._cured_idx.get(trigger.key)
    layer = trigger.sub_category.split(".")[0]
    band_label = _BAND_LABEL.get(int(severity_band), "MEDIUM")
    try:
        reason = reasons.subcategory_reason(trigger.sub_category, band_label)
    except KeyError:
        reason = ""
    return {
        "layer": layer,
        # The reading that produced the score.
        "observed_value": (None if observed_value is None
                            else round(float(observed_value), 6)),
        "baseline_value": (None if baseline_value is None
                            else round(float(baseline_value), 6)),
        "normalised_value": (None if normalised_value is None
                              else round(float(normalised_value), 6)),
        "observed_metric": observed_metric or trigger.key,
        "observed_unit": observed_unit,
        # The canonical reason for this node at this severity, from the
        # workbook's own text rather than a sentence composed at read time.
        "reason_code": f"{trigger.sub_category}:B{int(severity_band)}",
        "reason": reason,
        "trigger_severity_band": severity_band,
        "trigger_severity_score": round(float(trigger_score), 4),
        "magnitude_band": accel_input.magnitude_band,
        "velocity_band": accel_input.velocity_band,
        "persistence_band": accel_input.persistence_band,
        "repetition_band": accel_input.repetition_band,
        "corroboration_band": accel_input.corroboration_band,
        "magnitude_multiplier": accel_result.dimension_multipliers.get("magnitude"),
        "velocity_multiplier": accel_result.dimension_multipliers.get("velocity"),
        "persistence_multiplier": accel_result.dimension_multipliers.get("persistence"),
        "repetition_multiplier": accel_result.dimension_multipliers.get("repetition"),
        "corroboration_multiplier": accel_result.dimension_multipliers.get("corroboration"),
        "accelerator_multiplier": round(float(accel_result.accelerator_multiplier), 6),
        "decay_factor": round(float(decay.decay_factor), 6),
        "decay_class": decay.decay_class,
        "half_life_days": decay_class.half_life_days if decay_class else None,
        "decay_floor": decay_class.floor if decay_class else None,
        # The persistence hold, made legible: a condition that is still live
        # carries full weight however old it is, and the decay clock only
        # starts once it cures.
        "cured": cured_idx is not None,
        "days_since_cure": ((month_idx - cured_idx) * DAYS_PER_MONTH
                            if cured_idx is not None else 0),
        "age_days": (month_idx - first_seen) * DAYS_PER_MONTH,
        "occurrences": state._occurrences.get(trigger.key, 1),
        "source_domain": lin.SOURCE_DOMAIN_BY_LAYER.get(layer, ""),
        "source_dataset": lin.SOURCE_DATASET_BY_LAYER.get(layer, ""),
        "source_tier": source_tier,
        "is_synthetic": layer in lin.SYNTHETIC_LAYERS,
    }


def l1_signal_scores(borrower_series: dict[str, dict[pd.Timestamp, float]], month: pd.Timestamp,
                      months: list[pd.Timestamp], state: TriggerDecayState) -> list[agg.FiredSignal]:
    """The four L1 triggers with a real monthly anchor, using a genuine
    trailing baseline (see `trailing_baseline`) rather than one value fixed
    across the whole run."""
    fired: list[agg.FiredSignal] = []
    month_idx = months.index(month)

    def pct_change(key: str) -> tuple[float, float, float] | None:
        """The value observed, what it was measured against, and the change.

        All three travel together because the percentage on its own is not
        evidence: a reader checking a signal wants the reading and the
        baseline it was compared with, and re-deriving them later against a
        window that may have moved is not the same fact.
        """
        series = borrower_series.get(key)
        if series is None or pd.isna(series.get(month, float("nan"))):
            return None
        base = trailing_baseline(series, months, month)
        if base in (None, 0) or pd.isna(base):
            return None
        return (float(series[month]), float(base),
                100.0 * (series[month] - base) / abs(base))

    def fire(trigger_key: str, change_pct: float, worse_if_negative: bool, *,
             observed: float, baseline: float, metric: str):
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
        accel_input = accel.AcceleratorInput(
            magnitude_band=mag_band, velocity_band=mag_band, persistence_band=3,
            repetition_band=state.repetition_band(trigger_key), corroboration_band=1,
            decay_factor=decay.decay_factor,
        )
        result = accel.compute_accelerator(accel_input)
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        context = dict(
            observed_value=observed, baseline_value=baseline,
            normalised_value=adverse, observed_metric=metric,
            observed_unit="% adverse change vs the trailing baseline")
        fired.append(agg.FiredSignal(
            trigger_key, score, trigger_key, t.sub_category,
            explanation=signal_explanation(
                t, severity_band=band, trigger_score=trigger_score,
                accel_input=accel_input, accel_result=result, decay=decay,
                state=state, month_idx=month_idx, **context),
        ))
        state.remember(LiveSignal(
            trigger_key, band, trigger_score, accel_input, trigger_key,
            context, continuous=True))

    utilisation = pct_change("utilisation")
    if utilisation is not None:
        fire("utilisation_increase", utilisation[2], worse_if_negative=False,
             observed=utilisation[0], baseline=utilisation[1],
             metric="utilisation_pct")

    delay = pct_change("dpd")
    if delay is not None and borrower_series["dpd"][month] >= 1:
        fire("repayment_delay", delay[2], worse_if_negative=False,
             observed=delay[0], baseline=delay[1], metric="dpd_days")

    cash = pct_change("cash")
    if cash is not None:
        fire("operating_deposit_balance_decline", cash[2],
             worse_if_negative=True, observed=cash[0], baseline=cash[1],
             metric="operating_deposit_balance")

    cfo = pct_change("cash_flow_from_operations")
    if cfo is not None:
        fire("cash_flow_deterioration", cfo[2], worse_if_negative=True,
             observed=cfo[0], baseline=cfo[1],
             metric="cash_flow_from_operations")

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

    def add(trigger_key: str, band: int, *, observed: float | None = None,
            baseline: float | None = None, normalised: float | None = None,
            metric: str = "", unit: str = ""):
        t = trg.BY_KEY[trigger_key]
        trigger_score = trg.trigger_score_for_band(band)
        state.observe(trigger_key, month_idx, continuous_active=False)
        decay = state.decay_for(trigger_key, t.sub_category, month_idx)
        if not decay.in_scope:
            return
        accel_input = accel.AcceleratorInput(
            3, 3, 2, state.repetition_band(trigger_key), 1, decay_factor=decay.decay_factor,
        )
        result = accel.compute_accelerator(accel_input)
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        context = dict(
            observed_value=observed, baseline_value=baseline,
            normalised_value=normalised, observed_metric=metric,
            observed_unit=unit)
        fired.append(agg.FiredSignal(
            trigger_key, score, trigger_key, t.sub_category,
            explanation=signal_explanation(
                t, severity_band=band, trigger_score=trigger_score,
                accel_input=accel_input, accel_result=result, decay=decay,
                state=state, month_idx=month_idx, **context),
        ))
        state.remember(LiveSignal(
            trigger_key, band, trigger_score, accel_input, trigger_key,
            context, continuous=False))

    rating_move = curr["internal_rating_numeric"] - prev["internal_rating_numeric"]
    if rating_move >= 1:
        band = 1 if rating_move == 1 else 2 if rating_move == 2 else 3 if rating_move == 3 else 5
        add("rating_migration_downgrade", band,
            observed=curr["internal_rating_numeric"],
            baseline=prev["internal_rating_numeric"], normalised=rating_move,
            metric="internal_rating_numeric", unit="notches downgraded")

    if prev["pd_12m"] > 0:
        pd_rel = 100.0 * (curr["pd_12m"] - prev["pd_12m"]) / prev["pd_12m"]
        if pd_rel >= 10:
            band = 1 if pd_rel < 25 else 2 if pd_rel < 50 else 3 if pd_rel < 100 else 4 if pd_rel < 200 else 5
            add("pd_movement", band, observed=curr["pd_12m"],
                baseline=prev["pd_12m"], normalised=pd_rel,
                metric="pd_12m", unit="% relative increase")

    if curr["stage"] > prev["stage"]:
        band = 2 if curr["stage"] == 2 else 5
        add("stage_migration", band, observed=curr["stage"],
            baseline=prev["stage"], normalised=curr["stage"] - prev["stage"],
            metric="ifrs9_stage", unit="stages migrated")

    if prev["ecl_coverage"] > 0:
        ecl_rel = 100.0 * (curr["ecl_coverage"] - prev["ecl_coverage"]) / prev["ecl_coverage"]
        if ecl_rel >= 10:
            band = 1 if ecl_rel < 25 else 2 if ecl_rel < 50 else 3 if ecl_rel < 100 else 4 if ecl_rel < 200 else 5
            add("ecl_movement", band, observed=curr["ecl_coverage"],
                baseline=prev["ecl_coverage"], normalised=ecl_rel,
                metric="ecl_coverage", unit="% relative increase")

    if bool(curr.get("breach_flag")):
        add("covenant_breach", 3 if not bool(prev.get("breach_flag")) else 4,
            observed=1.0, baseline=float(bool(prev.get("breach_flag"))),
            normalised=1.0, metric="covenant_breach_flag",
            unit="breach in the period")

    if prev.get("ebitda_margin") and not pd.isna(prev.get("ebitda_margin")):
        margin_drop = prev["ebitda_margin"] - curr["ebitda_margin"]
        if margin_drop > 3:
            band = 1 if margin_drop < 6 else 2 if margin_drop < 10 else 3 if margin_drop < 15 else 4
            add("financial_statement_deterioration", band,
                observed=curr["ebitda_margin"], baseline=prev["ebitda_margin"],
                normalised=margin_drop, metric="ebitda_margin",
                unit="percentage points of margin lost")

    return fired


def l4_event_signals(curr: pd.Series, prev: pd.Series | None, month_idx: int,
                      state: TriggerDecayState, *,
                      relationships: dict[str, list] | None = None,
                      counterparty_state: dict[str, object] | None = None
                      ) -> list[agg.FiredSignal]:
    """L4 network triggers, from the state of the borrower's counterparties.

    The framework's L4 triggers are relationship EVENTS — "distress at a
    supplier the borrower depends on", "distress at a customer material to
    the revenue base", "adverse event at a group entity". So the reading is
    the counterparty's own observable credit state at this quarter, weighted
    by how material that counterparty is to this borrower, which is exactly
    the question the trigger asks.

    Materiality matters as much as distress. A supplier in stage 3 that
    supplies two per cent of cost is not an early warning about this
    borrower; the same supplier at thirty per cent of cost is. So the
    severity band is the counterparty's own band, held back a step where the
    dependency is immaterial.
    """
    fired: list[agg.FiredSignal] = []
    links = dict(relationships or {})
    others = dict(counterparty_state or {})
    if not links or not others:
        return fired

    def add(trigger_key: str, band: int, *, counterparty: str, share: float,
            metric: str, unit: str):
        t = trg.BY_KEY[trigger_key]
        trigger_score = trg.trigger_score_for_band(band)
        state.observe(trigger_key, month_idx, continuous_active=True)
        decay = state.decay_for(trigger_key, t.sub_category, month_idx)
        if not decay.in_scope:
            return
        # Corroboration band 2: the reading rests on a named counterparty's
        # own published credit state, which is one step better than a single
        # unverified source and one step short of the borrower's own file.
        accel_input = accel.AcceleratorInput(
            magnitude_band=band, velocity_band=2, persistence_band=3,
            repetition_band=state.repetition_band(trigger_key),
            corroboration_band=2, decay_factor=decay.decay_factor)
        result = accel.compute_accelerator(accel_input)
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        context = dict(observed_value=float(band), baseline_value=0.0,
                       normalised_value=round(float(share), 2),
                       observed_metric=metric, observed_unit=unit)
        fired.append(agg.FiredSignal(
            trigger_key, score, f"{trigger_key}_{counterparty}", t.sub_category,
            explanation=signal_explanation(
                t, severity_band=band, trigger_score=trigger_score,
                accel_input=accel_input, accel_result=result, decay=decay,
                state=state, month_idx=month_idx, source_tier=1, **context),
        ))
        state.remember(LiveSignal(
            trigger_key, band, trigger_score, accel_input,
            f"{trigger_key}_{counterparty}", context, continuous=True))

    def worst(kind: str, trigger_key: str, metric: str, unit: str) -> None:
        best_band, best_id, best_share = 0, "", 0.0
        for counterparty, share in links.get(kind, ()):
            band = counterparty_distress(others.get(counterparty))
            if not band:
                continue
            # An immaterial dependency is held back one band. It is still a
            # reading — a distressed name in the chain is worth knowing — but
            # it is not the same warning as losing a third of your input cost.
            if share < COUNTERPARTY_MATERIAL_PCT:
                band = max(1, band - 1)
            if band > best_band or (band == best_band and share > best_share):
                best_band, best_id, best_share = band, counterparty, share
        if best_band:
            add(trigger_key, best_band, counterparty=best_id,
                share=best_share, metric=metric, unit=unit)

    worst("suppliers", "key_supplier_distress",
          "supplier_credit_state",
          "severity read off the supplier's own stage, arrears and grade")
    worst("customers", "key_customer_distress",
          "customer_credit_state",
          "severity read off the customer's own stage, arrears and grade")

    # Group and guarantor propagation. A guarantee link makes the same peer
    # event a credit-support event rather than a commercial one, and the
    # framework scores those under different triggers.
    peers = links.get("group", ())
    best_band, best_id, guaranteed = 0, "", False
    for counterparty, guarantee_links in peers:
        band = counterparty_distress(others.get(counterparty))
        if band > best_band:
            best_band, best_id, guaranteed = band, counterparty, guarantee_links > 0
    if best_band:
        add("guarantor_deterioration" if guaranteed
            else "group_or_sister_company_deterioration",
            best_band, counterparty=best_id, share=100.0,
            metric="connected_group_credit_state",
            unit=("severity read off the connected entity's own stage, "
                  "arrears and grade"))

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
        accel_input = accel.AcceleratorInput(
            3, 3, 2, state.repetition_band(trigger_key), corroboration_band, decay_factor=decay.decay_factor,
        )
        result = accel.compute_accelerator(accel_input)
        score = accel.signal_score(trigger_score, result.accelerator_multiplier)
        chain = f"{trigger_key}_{ev['snapshot_month']}"
        context = dict(
            source_tier=int(ev["source_tier"]),
            observed_value=float(ev["severity_band"]),
            normalised_value=float(ev["severity_band"]),
            observed_metric="external_event_severity",
            observed_unit=("severity band assessed on the event, from a "
                           "tier-%d source" % int(ev["source_tier"])))
        fired.append(agg.FiredSignal(
            trigger_key, score, chain, t.sub_category,
            explanation=signal_explanation(
                t, severity_band=int(ev["severity_band"]),
                trigger_score=trigger_score, accel_input=accel_input,
                accel_result=result, decay=decay, state=state,
                month_idx=month_idx, **context),
        ))
        state.remember(LiveSignal(
            trigger_key, int(ev["severity_band"]), trigger_score, accel_input,
            chain, context, continuous=False))
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

    # Evidence quality: the tier of the evidence actually SCORING this
    # month — tier 1 (bank and official systems) improves confidence, tier 3
    # (an unverified single source) weakens it.
    #
    # Read off the fired signals rather than off this month's fresh external
    # events. Those were the same thing until signals began to be carried
    # forward at their decayed weight; now a tier-2 external event from three
    # months ago can still be driving the score while no new event has
    # arrived, and reading only the new ones told the reader every driving
    # signal was internal bank data when it was not.
    tiers = [int(f.explanation["source_tier"]) for f in month_fired
             if f.explanation.get("source_tier") is not None]
    if not tiers:
        evidence_quality = -1
    else:
        worst_tier = max(tiers)
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
                          events_this_month: pd.DataFrame, *,
                          relationships: dict[str, list] | None = None,
                          counterparty_state: dict[str, object] | None = None,
                          ) -> tuple[dict, list[agg.FiredSignal]]:
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
        + l4_event_signals(curr, prev, month_idx, state,
                           relationships=relationships,
                           counterparty_state=counterparty_state) + l3_fired
    # Everything that fired EARLIER and has not decayed out of scope, at the
    # weight this month's decay gives it. Without this the trigger side saw
    # only the current month's events and the whole book sat in the VERY_LOW
    # row of the matrix.
    fired += state.carry(month_idx, {f.signal_key for f in fired})
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
    print(f"> {len(borrower_ids)} borrowers selected across "
          f"{len(VISIBLE_MONTHS)} published months "
          f"({VISIBLE_MONTHS[0]:%Y-%m} to {VISIBLE_MONTHS[-1]:%Y-%m}), "
          f"computed over {len(MONTHS)} with {PRE_HISTORY_MONTHS} months of "
          f"warm-up before the first published one")

    print("> Computing sector EBITDA margin medians (cross-sectional)")
    sector_medians = build_sector_medians(full_universe)

    print("> Computing supplier/receivable concentration from corporate_supply_chain")
    graph_extra = build_graph_concentration(borrower_ids)

    print("> Mapping counterparties from corporate_supply_chain and "
          "corporate_connected_groups")
    relationships = build_relationships(borrower_ids)
    # The counterparty's own credit state, by quarter, over the WHOLE
    # universe rather than the 300 sampled names: a borrower's key supplier
    # is usually not itself in the Early Warning sample, and reading L4 only
    # off the sample would make the layer a function of who happened to be
    # picked.
    counterparty_by_quarter: dict[str, dict[str, object]] = {}
    for quarter, chunk in full_universe.groupby("period"):
        counterparty_by_quarter[str(quarter)] = {
            str(r["borrower_id"]): r for _, r in chunk.iterrows()}
    linked = sum(1 for v in relationships.values()
                 if v["suppliers"] or v["customers"] or v["group"])
    print(f"  {linked} of {len(borrower_ids)} borrowers have at least one "
          f"mapped counterparty")

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
                relationships=relationships.get(borrower_id),
                counterparty_state=counterparty_by_quarter.get(quarter),
            )
            row["snapshot_month"] = month_str
            # The warm-up months are scored so the published ones inherit a
            # real trailing baseline, a running decay clock and a recurrence
            # count. They are not written: a reader must never see a month
            # that was itself produced from a cold start.
            published = is_published(month)
            if published:
                borrower_month_rows.append(row)
            # History feeds the direction-of-travel notch and is accumulated
            # across the whole computed range, which is the point of the
            # warm-up.
            ews_history.append(row["ews_score"])

            for f in (fired if published else ()):
                # The explanation is flattened alongside the score rather than
                # nested: a reader asking "why is this signal at 80?" is
                # answered by reading one row, and the report's lineage table
                # is a projection of these columns rather than a second
                # derivation of them.
                signal_obs_rows.append({
                    "snapshot_month": month_str, "customer_id": borrower_id,
                    "signal_key": f.signal_key, "signal_score": f.signal_score,
                    "sub_category": f.sub_category, "causal_chain_id": f.causal_chain_id,
                    **f.explanation,
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
