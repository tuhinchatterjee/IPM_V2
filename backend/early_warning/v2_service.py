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

BORROWER_MONTH = "early_warning_borrower_month"
SIGNAL_OBSERVATION = "early_warning_signal_observation"


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
            "dominant_driver"]
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
