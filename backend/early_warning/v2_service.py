"""Reads the Early Warning V2 monthly domain built by
`scripts/build_early_warning_v2.py`, mirroring the same internal-load
pattern `backend/corporate/service.py::_load()` already uses for every
other analytical dataset in this codebase: glob the period-partitioned
Parquet files, cache in-process, and raise a clear "not built" error rather
than a confusing empty result.
"""

from __future__ import annotations

import glob
from functools import lru_cache

import pandas as pd

from backend.config import settings
from backend.early_warning import catalog as ews_catalog
from backend.early_warning import reasons

BORROWER_MONTH = "early_warning_borrower_month"
SIGNAL_OBSERVATION = "early_warning_signal_observation"
EXTERNAL_EVENT_SYNTHETIC = "early_warning_external_event_synthetic"

#: layer -> ordered sub-category codes, for the drill-down tree.
LAYER_SUBCATEGORIES: dict[str, tuple[str, ...]] = {
    "L1": ("L1.1", "L1.2", "L1.3", "L1.4"),
    "L2": ("L2.T1", "L2.T2", "L2.1", "L2.2", "L2.3", "L2.4", "L2.5", "L2.6", "L2.7"),
    "L3": ("L3.1", "L3.2", "L3.3", "L3.4", "L3.5"),
    "L4": ("L4.1", "L4.2", "L4.3", "L4.4"),
}

_BAND_CUTOFFS = ((20.0, "VERY_LOW"), (40.0, "LOW"), (60.0, "MEDIUM"), (80.0, "HIGH"), (101.0, "VERY_HIGH"))


def _band_for(score: float) -> str:
    for cutoff, band in _BAND_CUTOFFS:
        if score < cutoff:
            return band
    return "VERY_HIGH"


class EarlyWarningDataNotBuilt(RuntimeError):
    pass


@lru_cache(maxsize=8)
def _load(dataset: str) -> pd.DataFrame:
    files = sorted(glob.glob(
        str(settings.analytics_dir / dataset / "**" / "*.parquet"), recursive=True))
    if not files:
        raise EarlyWarningDataNotBuilt(
            f"{dataset} has not been built. Run scripts/build_corporate_universe.py "
            "then scripts/build_early_warning_v2.py. Nothing here is client data.")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def reset() -> None:
    _load.cache_clear()


def periods() -> list[str]:
    return sorted(_load(BORROWER_MONTH)["snapshot_month"].unique().tolist())


def latest_period() -> str:
    return periods()[-1]


def borrower_month(period: str | None = None) -> pd.DataFrame:
    df = _load(BORROWER_MONTH)
    period = period or latest_period()
    return df[df["snapshot_month"] == period].copy()


def borrower_history(customer_id: str) -> pd.DataFrame:
    df = _load(BORROWER_MONTH)
    return df[df["customer_id"] == customer_id].sort_values("snapshot_month").copy()


def signal_observations(customer_id: str, period: str | None = None) -> pd.DataFrame:
    df = _load(SIGNAL_OBSERVATION)
    period = period or latest_period()
    return df[(df["customer_id"] == customer_id) & (df["snapshot_month"] == period)].copy()


def signal_evidence(customer_id: str, signal_key: str,
                     period: str | None = None) -> dict | None:
    """One signal's full explanation: how its score was reached and where it
    came from.

    This is what answers "show me the evidence behind that node" without
    re-deriving anything. The build persists the trigger severity, the five
    accelerator dimension bands, the decay state and the source system at the
    moment the score was computed, so what a reader is shown is the reading
    that produced the score rather than a reconstruction of it.

    Returns None when the signal did not fire for this borrower in this
    period — an absence, said plainly, rather than an empty shape that reads
    like a zero.
    """
    obs = signal_observations(customer_id, period)
    if obs.empty:
        return None
    match = obs[obs["signal_key"] == signal_key]
    if match.empty:
        return None
    row = match.iloc[0].to_dict()
    return {k: (None if pd.isna(v) else v) if not isinstance(v, (list, dict)) else v
            for k, v in row.items()}


def portfolio_summary(period: str | None = None) -> dict:
    bm = borrower_month(period)
    if bm.empty:
        return {"period": period or latest_period(), "portfolio_ews": 0.0, "borrower_count": 0,
                "total_exposure": 0.0, "severity_distribution": []}
    exposure_weighted = (bm["ews_score"] * bm["exposure"]).sum() / bm["exposure"].sum() \
        if bm["exposure"].sum() > 0 else bm["ews_score"].mean()
    dist = []
    for band in ("VERY_HIGH", "HIGH", "MEDIUM", "LOW", "VERY_LOW"):
        subset = bm[bm["ews_band"] == band]
        dist.append({
            "band": band, "borrower_count": int(len(subset)),
            "borrower_pct": round(100.0 * len(subset) / len(bm), 2) if len(bm) else 0.0,
            "exposure": round(float(subset["exposure"].sum()), 2),
            "exposure_pct": round(100.0 * subset["exposure"].sum() / bm["exposure"].sum(), 2)
                            if bm["exposure"].sum() > 0 else 0.0,
        })
    high_plus = bm[bm["ews_band"].isin(("HIGH", "VERY_HIGH"))]
    return {
        "period": bm["snapshot_month"].iloc[0],
        "portfolio_ews": round(float(exposure_weighted), 2),
        "borrower_count": int(len(bm)),
        "total_exposure": round(float(bm["exposure"].sum()), 2),
        "high_plus_count": int(len(high_plus)),
        "high_plus_exposure": round(float(high_plus["exposure"].sum()), 2),
        "severity_distribution": dist,
    }


def portfolio_trend() -> list[dict]:
    out = []
    for p in periods():
        summary = portfolio_summary(p)
        out.append({"period": p, "portfolio_ews": summary["portfolio_ews"],
                    "high_plus_count": summary["high_plus_count"]})
    return out


def segment_summary(period: str | None = None) -> list[dict]:
    bm = borrower_month(period)
    if bm.empty:
        return []
    out = []
    for segment, group in bm.groupby("segment"):
        weighted = (group["ews_score"] * group["exposure"]).sum() / group["exposure"].sum() \
            if group["exposure"].sum() > 0 else group["ews_score"].mean()
        high_plus = group[group["ews_band"].isin(("HIGH", "VERY_HIGH"))]
        out.append({
            "segment": segment, "borrower_count": int(len(group)),
            "exposure": round(float(group["exposure"].sum()), 2),
            "portfolio_ews": round(float(weighted), 2),
            "high_plus_count": int(len(high_plus)),
            "weakest_borrower": group.loc[group["ews_score"].idxmax(), "customer_id"] if len(group) else None,
        })
    return sorted(out, key=lambda r: r["portfolio_ews"], reverse=True)


def top_high_risk(period: str | None = None, limit: int = 20) -> list[dict]:
    bm = borrower_month(period)
    if bm.empty:
        return []
    cols = ["customer_id", "customer_name", "segment", "exposure", "dpd", "ifrs9_stage",
            "ews_score", "ews_band", "ta_score", "ta_band", "classifier_score", "classifier_band",
            "dominant_driver", "signal_count_fired", "overrides_applied"]
    top = bm.sort_values("ews_score", ascending=False).head(limit)
    return top[cols].to_dict(orient="records")


def borrower_detail(customer_id: str) -> dict:
    history = borrower_history(customer_id)
    if history.empty:
        raise KeyError(customer_id)
    latest = history.iloc[-1].to_dict()
    return {
        "latest": latest,
        "history": history[["snapshot_month", "ews_score", "ews_band", "ta_score",
                            "classifier_score", "dpd", "utilisation_pct"]].to_dict(orient="records"),
    }


def external_events(customer_id: str | None = None, period: str | None = None) -> pd.DataFrame:
    """The governed synthetic L3 events (always marked
    `scenario_status="SYNTHETIC_DEMONSTRATION_DATA"`). Returns an empty
    frame, not an error, for a build that predates this dataset."""
    try:
        df = _load(EXTERNAL_EVENT_SYNTHETIC)
    except EarlyWarningDataNotBuilt:
        return pd.DataFrame(columns=["snapshot_month", "customer_id", "trigger_key",
                                     "severity_band", "source_tier", "evidence_type", "scenario_status"])
    if customer_id is not None:
        df = df[df["customer_id"] == customer_id]
    if period is not None:
        df = df[df["snapshot_month"] == period]
    return df.copy()


def layer_tree(customer_id: str) -> dict:
    """Layer -> sub-category -> signal, for the borrower drill-down UI
    (spec section on the dedicated EWS journey). Each node carries its own
    score, band and Tab 12 reason text — 'collapse anything green, open
    anything amber or rust' (Tab 14), so bands are included for the
    frontend to decide what starts expanded."""
    latest = borrower_history(customer_id)
    if latest.empty:
        raise KeyError(customer_id)
    row = latest.iloc[-1]
    subcat_scores: dict[str, float] = row.get("subcategory_scores") or {}
    layer_scores: dict[str, float] = row.get("layer_dimension_scores") or {}
    period = row["snapshot_month"]

    obs = signal_observations(customer_id, period)
    obs_by_subcat: dict[str, list[dict]] = {}
    if not obs.empty:
        for _, o in obs.iterrows():
            obs_by_subcat.setdefault(o.get("sub_category", ""), []).append({
                "signal_key": o["signal_key"], "signal_score": round(float(o["signal_score"]), 2),
                "causal_chain_id": o["causal_chain_id"],
            })

    events = external_events(customer_id, period)
    layer_dimension_key = {"L1": "l1_ta", "L2": None, "L3": "l3_ta", "L4": "l4_ta"}

    tree = []
    for layer, subcats in LAYER_SUBCATEGORIES.items():
        layer_node = {"layer": layer, "sub_categories": []}
        if layer == "L2":
            layer_node["ta_score"] = round(float(layer_scores.get("l2_ta", 0.0)), 2)
            layer_node["c_score"] = round(float(layer_scores.get("l2_c", 0.0)), 2)
        elif layer == "L4":
            layer_node["ta_score"] = round(float(layer_scores.get("l4_ta", 0.0)), 2)
            layer_node["c_score"] = round(float(layer_scores.get("l4_c", 0.0)), 2)
        else:
            key = layer_dimension_key[layer]
            layer_node["ta_score"] = round(float(layer_scores.get(key, 0.0)), 2)

        for code in subcats:
            score = float(subcat_scores.get(code, 0.0))
            band = _band_for(score)
            layer_node["sub_categories"].append({
                "code": code, "name": reasons.subcategory_name(code),
                "score": round(score, 2), "band": band,
                "reason": reasons.subcategory_reason(code, band),
                "signals": obs_by_subcat.get(code, []),
            })
        tree.append(layer_node)

    return {
        "customer_id": customer_id, "period": period, "tree": tree,
        "external_events": events.to_dict(orient="records") if not events.empty else [],
    }
