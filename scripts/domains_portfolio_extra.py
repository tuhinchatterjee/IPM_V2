"""Seven more Core Portfolio datasets, each of which a signal needed.

Every one of these exists because an Early Warning signal was written against
it and then could not be computed. A returned payment, a rejected direct
debit, a limit excess, a waived covenant, a lapsed insurance policy, an
expired security document — these are the events a credit officer hears about
from operations long before they reach a ratio, and the platform could see
none of them.

DERIVED from the facility book, like everything else here: a payment is
returned for a borrower the book already says is in arrears, a limit excess
belongs to a facility already drawn past its limit, and a covenant waiver
attaches to a covenant that was already breached.

Everything here is SYNTHETIC and marked as such on every dataset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RETURN_REASONS = [
    "Insufficient funds", "Account frozen", "Mandate cancelled",
    "Technical rejection", "Signature mismatch", "Currency mismatch",
]

WAIVER_REASONS = [
    "One-off event excluded", "Cure period granted", "Definition amended",
    "Covenant reset agreed", "Sponsor support undertaking",
]

INSURERS = ["Insurer A", "Insurer B", "Insurer C", "Insurer D"]

DOCUMENTS = [
    "Mortgage deed", "Pledge agreement", "Assignment of receivables",
    "Corporate guarantee", "Valuation report", "Insurance certificate",
]


def _pressure(facility: pd.DataFrame) -> np.ndarray:
    """How likely this facility-quarter is to throw an operational event."""
    late = np.clip(facility["dpd_days"].to_numpy(dtype=float) / 90.0, 0, 1.5)
    used = np.clip(facility["utilisation_pct"].to_numpy(dtype=float) / 100.0,
                   0, 1.3)
    stage = (facility["ifrs9_stage"].to_numpy(dtype=float) - 1.0) / 2.0
    return np.clip(0.45 * late + 0.35 * np.clip(used - 0.8, 0, 1) + 0.30 * stage,
                   0.0, 1.0)


def build(facility: pd.DataFrame,
          rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    base = facility[[c for c in (
        "customer_id", "account_id", "period", "snapshot_date", "sector",
        "exposure", "limit_amount", "utilisation_pct", "dpd_days",
        "ifrs9_stage", "covenant_headroom_pct", "collateral_type",
        "collateral_value") if c in facility.columns]].copy()
    base["pressure"] = _pressure(facility)
    return {
        "returned_payments": _returned(base, rng),
        "payment_rejections": _rejections(base, rng),
        "limit_excesses": _excesses(base, rng),
        "covenant_waivers": _waivers(base, rng),
        "covenant_resets": _resets(base, rng),
        "collateral_insurance": _insurance(base, rng),
        "collateral_document_expiry": _documents(base, rng),
    }


def _sample(frame: pd.DataFrame, rng: np.random.Generator,
            base_rate: float, slope: float) -> pd.DataFrame:
    odds = np.clip(base_rate + slope * frame["pressure"].to_numpy(), 0, 0.95)
    return frame[rng.random(len(frame)) < odds].copy()


def _returned(base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    out = _sample(base, rng, 0.012, 0.22)
    n = len(out)
    out["returned_count"] = rng.integers(1, 4, n)
    out["returned_amount"] = np.round(
        out["exposure"].to_numpy(dtype=float)
        * rng.uniform(0.004, 0.05, n), 3)
    out["reason"] = rng.choice(RETURN_REASONS, n)
    out["resolved"] = rng.random(n) < 0.62
    return out[["customer_id", "account_id", "period", "returned_count",
                "returned_amount", "reason", "resolved"]].reset_index(drop=True)


def _rejections(base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    out = _sample(base, rng, 0.018, 0.26)
    n = len(out)
    out["rejection_count"] = rng.integers(1, 6, n)
    out["rejected_amount"] = np.round(
        out["exposure"].to_numpy(dtype=float)
        * rng.uniform(0.002, 0.04, n), 3)
    out["instrument"] = rng.choice(
        ["Direct debit", "Standing order", "Cheque", "Transfer"], n)
    out["reason"] = rng.choice(RETURN_REASONS, n)
    return out[["customer_id", "account_id", "period", "rejection_count",
                "rejected_amount", "instrument",
                "reason"]].reset_index(drop=True)


def _excesses(base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Only facilities actually drawn past their limit. An excess on a
    facility with headroom would be a number contradicting the book."""
    over = base[base["utilisation_pct"].to_numpy(dtype=float) > 100.0].copy()
    if over.empty:
        return pd.DataFrame(columns=[
            "customer_id", "account_id", "period", "sector", "excess_amount",
            "excess_pct", "excess_band", "days_in_excess", "approved"])
    n = len(over)
    limit = over["limit_amount"].to_numpy(dtype=float)
    used = over["utilisation_pct"].to_numpy(dtype=float)
    over["excess_amount"] = np.round(limit * (used - 100.0) / 100.0, 3)
    over["excess_pct"] = np.round(used - 100.0, 2)
    over["days_in_excess"] = np.clip(
        rng.integers(1, 95, n) + (over["pressure"].to_numpy() * 40).astype(int),
        1, 180)
    over["approved"] = rng.random(n) < 0.44
    over["excess_band"] = pd.cut(
        over["excess_pct"], bins=[-0.01, 2.0, 5.0, 10.0, 1000.0],
        labels=["Under 2%", "2-5%", "5-10%", "Over 10%"]).astype(str)
    return over[["customer_id", "account_id", "period", "sector",
                 "excess_amount", "excess_pct", "excess_band",
                 "days_in_excess", "approved"]].reset_index(drop=True)


def _waivers(base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Waivers attach to covenants that were breached, never to comfortable
    ones. A waiver with headroom behind it is a contradiction."""
    tight = base[base["covenant_headroom_pct"].to_numpy(dtype=float) < 0].copy()
    if tight.empty:
        tight = base[base["covenant_headroom_pct"].to_numpy(dtype=float)
                     < 5.0].copy()
    out = _sample(tight, rng, 0.22, 0.35)
    n = len(out)
    out["waiver_reason"] = rng.choice(WAIVER_REASONS, n)
    out["waiver_granted"] = rng.random(n) < 0.71
    out["waiver_expires_period"] = out["period"]
    out["conditions_attached"] = rng.random(n) < 0.58
    return out[["customer_id", "account_id", "period", "waiver_reason",
                "waiver_granted", "waiver_expires_period",
                "conditions_attached"]].reset_index(drop=True)


def _resets(base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """A reset is a repriced covenant. Repeated resets are a borrower whose
    documentation is being rewritten to keep it compliant."""
    tight = base[base["covenant_headroom_pct"].to_numpy(dtype=float)
                 < 8.0].copy()
    out = _sample(tight, rng, 0.10, 0.28)
    n = len(out)
    out["covenant"] = rng.choice(
        ["Minimum DSCR", "Maximum leverage", "Minimum tangible net worth",
         "Minimum current ratio", "Maximum capex"], n)
    out["previous_threshold"] = np.round(rng.uniform(1.0, 4.5, n), 2)
    out["new_threshold"] = np.round(
        out["previous_threshold"].to_numpy() * rng.uniform(0.72, 0.96, n), 2)
    out["reset_count_to_date"] = rng.integers(1, 4, n)
    return out[["customer_id", "account_id", "period", "covenant",
                "previous_threshold", "new_threshold",
                "reset_count_to_date"]].reset_index(drop=True)


def _insurance(base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Insurance on the collateral. An uninsured warehouse is a security
    interest in an asset that can stop existing overnight."""
    secured = base[base["collateral_value"].to_numpy(dtype=float) > 0].copy() \
        if "collateral_value" in base.columns else base.copy()
    if secured.empty:
        secured = base.copy()
    n = len(secured)
    secured["insurer"] = rng.choice(INSURERS, n)
    value = secured.get("collateral_value",
                        secured["exposure"]).to_numpy(dtype=float)
    secured["insured_value"] = np.round(value * rng.uniform(0.55, 1.05, n), 3)
    secured["insured_share_pct"] = np.round(
        np.clip(secured["insured_value"] / np.maximum(value, 0.01) * 100.0,
                0, 130), 2)
    secured["policy_in_force"] = rng.random(n) < np.clip(
        0.94 - 0.30 * secured["pressure"].to_numpy(), 0.3, 0.99)
    secured["expires_within_90_days"] = rng.random(n) < 0.14
    return secured[["customer_id", "account_id", "period", "insurer",
                    "insured_value", "insured_share_pct", "policy_in_force",
                    "expires_within_90_days"]].reset_index(drop=True)


def _documents(base: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Security documents and when they lapse. An expired valuation makes a
    collateral figure an opinion about a past year."""
    out = base.sample(frac=0.55, random_state=int(rng.integers(0, 2**31))).copy()
    n = len(out)
    out["document_type"] = rng.choice(DOCUMENTS, n)
    out["days_to_expiry"] = rng.integers(-420, 900, n)
    out["expired"] = out["days_to_expiry"] < 0
    out["expires_within_90_days"] = (
        (out["days_to_expiry"] >= 0) & (out["days_to_expiry"] <= 90))
    out["last_reviewed_period"] = out["period"]
    return out[["customer_id", "account_id", "period", "document_type",
                "days_to_expiry", "expired", "expires_within_90_days",
                "last_reviewed_period"]].reset_index(drop=True)


#: (catalogue domain, business name, purpose, grain, primary keys, owner).
DOMAINS: dict[str, tuple[str, str, str, str, list[str], str]] = {
    "returned_payments": (
        "Arrears and Collections", "Returned Payments",
        "Payments that were presented and came back, with the reason and "
        "whether it was resolved. Operations hears about these long before a "
        "ratio moves.",
        "One row per facility per reporting period with a returned payment.",
        ["period", "account_id"], "Credit Risk Operations"),
    "payment_rejections": (
        "Arrears and Collections", "Payment Rejections",
        "Direct debits, standing orders and transfers rejected before they "
        "settled, by instrument and reason.",
        "One row per facility per reporting period with a rejection.",
        ["period", "account_id"], "Credit Risk Operations"),
    "limit_excesses": (
        "Limits and Approvals", "Limit Excesses",
        "Facilities drawn past their sanctioned limit: by how much, for how "
        "long, and whether the excess was approved.",
        "One row per facility per reporting period in excess.",
        ["period", "account_id"], "Credit Administration"),
    "covenant_waivers": (
        "Covenants", "Covenant Waivers",
        "Breaches the bank agreed not to act on, why, and what conditions "
        "were attached. A waiver is a decision, and decisions are evidence.",
        "One row per facility per reporting period with a waiver.",
        ["period", "account_id"], "Credit Risk"),
    "covenant_resets": (
        "Covenants", "Covenant Resets",
        "Covenants repriced rather than breached, with the old and new "
        "thresholds. Repeated resets are documentation being rewritten to "
        "keep a borrower compliant.",
        "One row per facility per reporting period with a reset.",
        ["period", "account_id"], "Credit Risk"),
    "collateral_insurance": (
        "Collateral", "Collateral Insurance",
        "Insurance held over pledged collateral, how much of its value is "
        "covered, and whether the policy is in force.",
        "One row per facility per reporting period.",
        ["period", "account_id"], "Credit Administration"),
    "collateral_document_expiry": (
        "Collateral", "Collateral Document Expiry",
        "Security documents and valuations with their expiry. An expired "
        "valuation makes a collateral figure an opinion about a past year.",
        "One row per facility document per reporting period.",
        ["period", "account_id"], "Credit Administration"),
}


__all__ = ["DOCUMENTS", "DOMAINS", "INSURERS", "RETURN_REASONS",
           "WAIVER_REASONS", "build"]
