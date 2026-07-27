"""
RAROC 2 — Post-Deal (ex-post) RAROC engine, built to Post_Deal_RAROC_Build_Plan.md.

Same RAROC equation as pre-deal, but realised/refreshed inputs: today's funding
cost (FTP), migrated credit quality (PIT PD), realised utilisation and fees. Each
booked deal is measured against its APPROVED CASE (snapshot at booking) so drift is
attributable, and rolls up to the two earning figures the plan specifies:

  * Short-Term / Quick-Close Earning — 12-month headline; Quick-Close toggle values
    the early-exit case (accrued + fee recapture + break fee − short-horizon costs).
  * Lifetime Earning — discounted risk-adjusted earning over BEHAVIOURAL life, using
    the lifetime EL term structure (IFRS 9-consistent).

Every deal shows RAROC AND Economic Profit (EVA) — never RAROC alone.

Decisions taken (Build Plan §0 recommended options — see METHODOLOGY):
  D1 regulatory capital = EAD_reg × risk weight × target CET1 (standardised).
  D2 12-month STE headline + Quick-Close early-exit scenario.
  D3 full-relationship revenue (facility + fees + cross-sell + deposit FTP credit),
     with a credit-only toggle.
  D4 TTC PD for the approved case, PIT PD for post-deal actuals (basis flagged).

Figures are illustrative. Values are presented in AED (USD-peg 3.6725). The deal
book is generated deterministically from the live portfolio's borrower universe.
"""

import hashlib

import numpy as np
import pandas as pd

from backend import data_loader as dl

# ------------------------------------------------------------- governed inputs

HURDLE_PCT = 15.0            # group hurdle (cost of equity, CAPM-anchored)
TARGET_CET1 = 0.11          # capital held per unit RWA (standardised approach)
TAX_RATE = 0.0              # pre-tax basis (documented); UAE CT can be layered later
REINVEST_PCT = 4.0          # capital-benefit reinvestment (short FTP / risk-free)
AED = dl.AED_PER_USD        # 3.6725
N_DEALS = 120
DISCOUNT_PCT = HURDLE_PCT   # LTE/EVA discount rate = hurdle (economic value to shareholders)

FACILITY_TYPES = ["Term Loan", "Revolver", "Trade Finance", "Letter of Credit",
                  "Letter of Guarantee", "Mortgage", "Overdraft"]
REVOLVING = {"Revolver", "Overdraft", "Trade Finance", "Letter of Credit", "Letter of Guarantee"}

# Quarterly base-rate history (%). Rates rose into 2024 then eased — the backdrop
# that compresses fixed-rate deals booked at the bottom of the curve.
_EIBOR_PATH = {
    "Q4 2023": 4.90, "Q1 2024": 5.00, "Q2 2024": 5.10, "Q3 2024": 5.20, "Q4 2024": 4.90,
    "Q1 2025": 4.60, "Q2 2025": 4.30, "Q3 2025": 4.05, "Q4 2025": 3.85, "Q1 2026": 3.70,
}
_INDEX_SPREAD = {"3M EIBOR": 0.0, "3M SAIBOR": 0.70, "3M SOFR": 0.45}


def base_rate(index: str, quarter: str) -> float:
    return _EIBOR_PATH.get(quarter, 3.70) + _INDEX_SPREAD.get(index, 0.0)


def ftp_rate(index: str, quarter: str, tenor_years: float) -> float:
    """Matched-maturity funds transfer price: the funding index plus a term premium
    and a standing liquidity spread. Deal-level and fully traceable (Plan §2)."""
    term_premium = min(0.08 * tenor_years, 0.60)
    return base_rate(index, quarter) + term_premium + 0.15


def _index_for_region(region: str) -> str:
    if region in ("UAE", "Qatar", "Bahrain"):
        return "3M EIBOR"
    if region == "Saudi Arabia":
        return "3M SAIBOR"
    return "3M SOFR"


def _seg_for(row) -> str:
    seg = row["Segment"]
    sector = row["Sector"]
    if seg == "Wholesale":
        if sector in ("Real Estate", "Contracting"):
            return "Commercial Real Estate"
        if sector in ("Trade",):
            return "Trade Finance"
        return "Corporate"
    if seg == "Retail":
        return "Retail"
    return "SME"


# Standardised-approach risk weights (CBUAE/SAMA reality — Plan §2). Corporate/CRE
# scale with the rating bucket; retail/SME/mortgage use their standard buckets.
_CORP_RW = {"AAA-A": 0.50, "BBB": 1.00, "BB": 1.00, "B": 1.25, "CCC": 1.50, "D": 1.50}


def _risk_weight(segment: str, rating: str, secured: bool) -> float:
    bucket = dl.bucket_of_notch(rating)
    if segment == "Retail":
        rw = 0.35 if bucket in ("AAA-A", "BBB") else 0.75   # mortgage-ish vs other retail
    elif segment == "SME":
        rw = 0.85
    elif segment == "Trade Finance":
        rw = max(0.50, _CORP_RW.get(bucket, 1.0) * 0.8)     # short-tenor, self-liquidating
    else:
        rw = _CORP_RW.get(bucket, 1.0)                        # Corporate / CRE
    if secured:
        rw *= 0.85                                           # CRM/collateral recognition
    return float(rw)


def _annuity(years: float, rate_pct: float) -> float:
    """PV of 1/yr for `years` at `rate_pct` (fractional years supported)."""
    r = rate_pct / 100
    if r <= 0:
        return years
    return (1 - (1 + r) ** (-years)) / r


def _seed(x) -> int:
    return int(hashlib.md5(str(x).encode()).hexdigest()[:8], 16)


# --------------------------------------------------------------- deal build-up

def _build_deal(row, quarters: list, cur_q: str) -> dict:
    rng = np.random.default_rng(_seed(row["Account ID"]))
    cur_idx = quarters.index(cur_q)

    region = row["Region"]
    index = _index_for_region(region)
    segment = _seg_for(row)
    ftype = str(rng.choice(FACILITY_TYPES))
    is_revolver = ftype in REVOLVING
    secured = str(row.get("Collateral Type", "Unsecured")) != "Unsecured"

    tenor = float(rng.choice([1, 2, 3, 4, 5, 7])) if not is_revolver else float(rng.choice([1, 2, 3]))
    booking_idx = int(rng.integers(0, cur_idx)) if cur_idx > 0 else 0
    booking_q = quarters[booking_idx]
    elapsed_years = (cur_idx - booking_idx) * 0.25
    remaining_contractual = max(0.25, tenor - elapsed_years)
    # Behavioural maturity: revolvers roll (evergreen); amortisers prepay (CPR).
    behavioural_remaining = remaining_contractual * (1.4 if is_revolver else 0.85)

    rate_type = "Floating" if (is_revolver or rng.random() < 0.55) else "Fixed"
    spread_bps = {"Corporate": 190, "Commercial Real Estate": 240, "SME": 300,
                  "Trade Finance": 160, "Retail": 350}.get(segment, 220) + float(rng.uniform(-40, 60))
    spread = spread_bps / 100

    ead = float(row[dl.EAD_COL])
    undrawn = float(row.get("Undrawn (USD mn)", 0.0) or 0.0)
    limit = ead + undrawn
    utilisation = ead / limit if limit else 1.0

    # Rates: approved (booking) vs actual (now). Fixed keeps its coupon; floating
    # reprices, but a random subset repriced LATE (the plan's key signal).
    base_book = base_rate(index, booking_q)
    base_now = base_rate(index, cur_q)
    repriced_late = bool(rng.random() < 0.25)
    if rate_type == "Fixed":
        applied_now = base_book + spread
    elif repriced_late:
        # stuck near an older, higher base (missed a downward reset -> we overcharge,
        # or an upward reset we failed to pass on). Model as last-year's base.
        applied_now = base_rate(index, quarters[max(0, cur_idx - 3)]) + spread
    else:
        applied_now = base_now + spread

    ftp_book = ftp_rate(index, booking_q, tenor)
    ftp_now = ftp_rate(index, cur_q, remaining_contractual)

    # Fees (Plan §4.1 5-8).
    upfront_bps = float(rng.uniform(30, 110))
    commit_bps = float(rng.uniform(20, 55))
    fee_waived = bool(rng.random() < 0.18)          # fees waived post-approval signal
    if fee_waived:
        upfront_bps *= 0.25
    transactional = float(rng.uniform(0.0, 0.5)) if ftype in ("Trade Finance", "Letter of Credit",
                                                              "Letter of Guarantee") else 0.0
    # Full-relationship: ancillary fee income + deposit FTP credit. The deposit
    # benefit is the MARGIN the bank earns (FTP credit rate less the rate paid to the
    # depositor), not the whole funding rate.
    deposit_bal = float(rng.uniform(0.0, 0.6)) * ead
    deposit_margin = float(rng.uniform(0.4, 1.1))
    ancillary = float(rng.uniform(0.0, 0.25)) * (1.5 if segment in ("Corporate", "Trade Finance") else 0.6)

    opex_bps = float(rng.uniform(20, 60))

    # Risk: PIT now (from portfolio), TTC approved (from booking rating), lifetime PD.
    pd_pit = float(row["PD 12-Month (%)"])
    lgd = float(row["LGD (%)"])
    pd_life = float(row.get("PD Lifetime (%)", pd_pit * min(tenor, 5)) or pd_pit * 3)
    notch_delta = (dl.NOTCH_INDEX.get(row["Risk Rating"], 10)
                   - dl.NOTCH_INDEX.get(row["Prev. Risk Rating"], 10))
    pd_ttc_book = float(pd_pit / (1.35 ** notch_delta))
    ccf = 0.5 if is_revolver else 1.0
    ead_reg = ead + ccf * undrawn

    return {
        "deal_id": f"D2-{str(row['Account ID'])[-6:]}", "account_id": row["Account ID"],
        "customer_id": row["Customer ID"], "borrower": row["Borrower"], "group": row["Obligor Group"],
        "segment": segment, "sector": row["Sector"], "region": region, "rm": row["Owner / Analyst"],
        "facility_type": ftype, "currency": "AED", "secured": secured,
        "booking_q": booking_q, "cur_q": cur_q, "tenor": tenor,
        "remaining_years": remaining_contractual, "behavioural_remaining": behavioural_remaining,
        "elapsed_years": elapsed_years,
        "limit": limit, "ead": ead, "undrawn": undrawn, "utilisation": utilisation,
        "rate_type": rate_type, "index": index, "spread_bps": spread_bps, "repriced_late": repriced_late,
        "base_book": base_book, "base_now": base_now, "applied_now": applied_now,
        "ftp_book": ftp_book, "ftp_now": ftp_now,
        "upfront_bps": upfront_bps, "commit_bps": commit_bps, "fee_waived": fee_waived,
        "transactional": transactional, "deposit_bal": deposit_bal, "deposit_margin": deposit_margin,
        "ancillary": ancillary, "opex_bps": opex_bps,
        "pd_pit": pd_pit, "pd_ttc_book": pd_ttc_book, "pd_life": pd_life, "lgd": lgd,
        "ccf": ccf, "ead_reg": ead_reg, "stage": int(row["IFRS 9 Stage"]), "dpd": int(row.get("DPD (days)", 0) or 0),
        "rating_book": row["Prev. Risk Rating"], "rating_now": row["Risk Rating"],
        "collateral": float(row.get("Collateral (USD mn)", 0.0) or 0.0),
    }


def _economics(d: dict, credit_only: bool = False, quick_close: bool = False) -> dict:
    """Component 1-13 build-up (Plan §4.1) at the current reporting date, then STE,
    Quick-Close, LTE and EVA. All monetary outputs in AED mn."""
    ead, undrawn = d["ead"], d["undrawn"]

    def leg(applied, ftp, pd_pct, rating, ead_):
        nim = applied - ftp                                     # (4) NIM after FTP
        nii = ead_ * nim / 100
        fee = (undrawn * d["commit_bps"] / 10000                # (5) commitment
               + ead_ * d["upfront_bps"] / 10000 / max(d["tenor"], 1)  # (6) upfront amortised
               + d["transactional"])                            # (7) transactional
        cross = 0.0 if credit_only else (d["ancillary"] + d["deposit_bal"] * d["deposit_margin"] / 100)  # (8)
        opex = ead_ * d["opex_bps"] / 10000                     # (9)
        el = ead_ * pd_pct / 100 * d["lgd"]                     # (10) 12m EL
        rwa = (ead_ + d["ccf"] * undrawn) * _risk_weight(d["segment"], rating, d["secured"])
        cap = rwa * TARGET_CET1                                 # (11)
        cap_benefit = cap * REINVEST_PCT / 100                  # (12)
        earning = (nii + fee + cross + cap_benefit - opex - el) * (1 - TAX_RATE)  # (13)
        return nim, earning, cap, el, cross

    nim_now, earn_now, cap_now, el_now, cross_now = leg(d["applied_now"], d["ftp_now"], d["pd_pit"],
                                                        d["rating_now"], ead)
    nim_book, earn_book, cap_book, _, _ = leg(d["base_book"] + d["spread_bps"] / 100,
                                              d["ftp_book"], d["pd_ttc_book"], d["rating_book"], ead)

    raroc_st = earn_now / cap_now * 100 if cap_now else 0.0
    eva_st = (earn_now - HURDLE_PCT / 100 * cap_now) * AED
    approved_raroc = earn_book / cap_book * 100 if cap_book else 0.0

    # Lifetime: level annual earning before EL, discounted over behavioural life,
    # less PV of lifetime EL (term structure), plus unamortised upfront.
    gross_annual = earn_now + el_now  # add back 12m EL, replace with lifetime below
    rem = d["behavioural_remaining"]
    ann = _annuity(rem, DISCOUNT_PCT)
    upfront_total = d["limit"] * d["upfront_bps"] / 10000
    unamortised_upfront = upfront_total * (d["remaining_years"] / max(d["tenor"], 1))
    lifetime_el = ead * d["lgd"] * (1 - (1 - d["pd_pit"] / 100) ** max(rem, 1))  # cumulative
    lte_usd = gross_annual * ann - lifetime_el + unamortised_upfront
    lte = lte_usd * AED
    cap_pv = cap_now * ann
    eva_lt = (lte_usd - HURDLE_PCT / 100 * cap_pv) * AED
    raroc_lt = (gross_annual - lifetime_el / max(rem, 1)) / cap_now * 100 if cap_now else 0.0

    # Short-term / Quick-Close ($ AED mn).
    ste = earn_now * AED  # 12-month headline
    if quick_close:
        exit_frac = min(d["remaining_years"], 0.5)
        break_fee = d["ead"] * 0.005
        st_value = (earn_now * exit_frac + unamortised_upfront + break_fee
                    - el_now * exit_frac) * AED
    else:
        st_value = ste

    stage3 = d["stage"] == 3  # RAROC meaningless for defaulted — surfaced as N/A upstream
    return {
        **d, "credit_only": credit_only, "quick_close": quick_close,
        "nim_now": nim_now, "nim_book": nim_book, "nim_change": nim_now - nim_book,
        "ftp_change": d["ftp_now"] - d["ftp_book"], "base_change_bps": (d["base_now"] - d["base_book"]) * 100,
        "cap_now": cap_now * AED, "cap_now_usd": cap_now, "el_now": el_now * AED, "cross_now": cross_now * AED,
        "earn_now": earn_now * AED, "earn_now_usd": earn_now,
        "raroc_st": raroc_st, "raroc_lt": raroc_lt, "approved_raroc": approved_raroc,
        "raroc_drift": raroc_st - approved_raroc,
        "ste": st_value, "lte": lte, "eva_st": eva_st, "eva_lt": eva_lt,
        "unamortised_upfront": unamortised_upfront * AED, "lifetime_el": lifetime_el * AED,
        "above_hurdle": raroc_st >= HURDLE_PCT, "stage3": stage3,
        "required_spread_bps": max(0.0, (HURDLE_PCT / 100 * cap_now - (earn_now - ead * nim_now / 100))
                                   / max(ead, 1) * 10000) if cap_now else 0.0,
    }


# ---------------------------------------------------------------- public API

def _cur_quarter():
    return dl.DEFAULT_QUARTER


def compute_deal_book(n: int = N_DEALS, credit_only: bool = False, quick_close: bool = False) -> list[dict]:
    quarters = list(dl.QUARTER_SHEETS)
    cur_q = _cur_quarter()
    cur = dl.filtered_quarter(cur_q)
    cur = cur.sort_values(dl.EAD_COL, ascending=False).drop_duplicates("Customer ID").head(n)
    deals = [_economics(_build_deal(row, quarters, cur_q), credit_only, quick_close)
             for _, row in cur.iterrows()]
    deals.sort(key=lambda x: -x["lte"])
    return deals


def compute_summary(deals: list[dict] | None = None, **kw) -> dict:
    deals = deals if deals is not None else compute_deal_book(**kw)
    perf = [d for d in deals if not d["stage3"]]                # exclude defaulted from weighted RAROC
    cap = sum(d["cap_now_usd"] for d in perf)
    earn = sum(d["earn_now_usd"] for d in perf)
    port_raroc = earn / cap * 100 if cap else 0.0
    below = [d for d in perf if not d["above_hurdle"]]
    return {
        "deals": deals, "n": len(deals), "n_perf": len(perf),
        "portfolio_raroc": port_raroc, "hurdle": HURDLE_PCT,
        "ste_total": sum(d["ste"] for d in perf), "lte_total": sum(d["lte"] for d in perf),
        "eva_st_total": sum(d["eva_st"] for d in perf), "eva_lt_total": sum(d["eva_lt"] for d in perf),
        "cap_total": sum(d["cap_now"] for d in perf), "ead_total": sum(d["ead"] for d in perf) * AED,
        "below_count": len(below), "below_ead": sum(d["ead"] for d in below) * AED,
        "repriced_late": sum(1 for d in perf if d["repriced_late"]),
        "fee_waived": sum(1 for d in perf if d["fee_waived"]),
        "downgraded": sum(1 for d in perf if dl.NOTCH_INDEX.get(d["rating_now"], 10)
                          > dl.NOTCH_INDEX.get(d["rating_book"], 10)),
        "stage3_count": sum(1 for d in deals if d["stage3"]),
        "above_pct": (len([d for d in perf if d["above_hurdle"]]) / len(perf) * 100) if perf else 0.0,
    }


def get_deal(deal_id: str, **kw) -> dict | None:
    for d in compute_deal_book(**kw):
        if d["deal_id"] == deal_id:
            return d
    return None


def deal_earning_series(d: dict) -> dict:
    """Realised earning per quarter since booking + level projection to behavioural
    maturity — for the earnings bridge (Plan §3.5)."""
    quarters = list(dl.QUARTER_SHEETS)
    bi, ci = quarters.index(d["booking_q"]), quarters.index(d["cur_q"])
    hist_labels, hist_vals = [], []
    for q in quarters[bi:ci + 1]:
        applied = (d["base_book"] + d["spread_bps"] / 100) if d["rate_type"] == "Fixed" \
            else base_rate(d["index"], q) + d["spread_bps"] / 100
        ftp = ftp_rate(d["index"], q, d["tenor"])
        nim = applied - ftp
        el = d["ead"] * d["pd_pit"] / 100 * d["lgd"]
        earn_q = (d["ead"] * nim / 100 + d["ancillary"] - el) * 0.25 * AED  # per quarter
        hist_labels.append(q)
        hist_vals.append(earn_q)
    # Projection: level quarterly earning to behavioural maturity.
    n_fwd = max(1, int(round(d["behavioural_remaining"] * 4)))
    proj = d["earn_now"] * 0.25
    fwd_labels = [f"+{i}Q" for i in range(1, n_fwd + 1)]
    fwd_vals = [proj] * n_fwd
    return {"hist_labels": hist_labels, "hist": hist_vals, "fwd_labels": fwd_labels, "fwd": fwd_vals}


# ---------------------------------------------------------- sample dataset export

SAMPLE_PATH = dl.DATA_PATH.parent / "Post_Deal_RAROC2_Sample.xlsx"


def export_sample_dataset(path=SAMPLE_PATH) -> str:
    deals = compute_deal_book()
    master_cols = ["deal_id", "customer_id", "borrower", "group", "segment", "sector", "region", "rm",
                   "facility_type", "currency", "secured", "booking_q", "tenor", "remaining_years",
                   "behavioural_remaining", "rate_type", "index", "spread_bps", "limit", "ead", "undrawn",
                   "utilisation", "rating_book", "rating_now", "approved_raroc"]
    period_cols = ["deal_id", "cur_q", "ead", "undrawn", "utilisation", "applied_now", "base_now", "ftp_now",
                   "nim_now", "pd_pit", "lgd", "ead_reg", "cap_now", "el_now", "stage", "dpd",
                   "earn_now", "raroc_st", "raroc_lt", "ste", "lte", "eva_st", "eva_lt"]
    pre_cols = ["deal_id", "booking_q", "base_book", "ftp_book", "nim_book", "pd_ttc_book", "spread_bps",
                "rating_book", "approved_raroc"]
    assumptions = pd.DataFrame({
        "Parameter": ["Hurdle rate (%)", "Target CET1 (%)", "Tax rate (%)", "Capital-benefit rate (%)",
                      "Discount rate (%)", "AED per USD", "EL basis (approved)", "EL basis (post-deal)",
                      "Revenue scope", "Capital denominator"],
        "Value": [HURDLE_PCT, TARGET_CET1 * 100, TAX_RATE * 100, REINVEST_PCT, DISCOUNT_PCT, AED,
                  "TTC PD", "PIT PD (IFRS 9)", "Full relationship (credit-only toggle)",
                  "Regulatory: EAD_reg × RW × target CET1"],
    })

    def frame(cols):
        return pd.DataFrame([{c: d.get(c) for c in cols} for d in deals]).round(3)

    with pd.ExcelWriter(path, engine="openpyxl") as w:
        frame(master_cols).to_excel(w, sheet_name="Deal_Master", index=False)
        frame(period_cols).to_excel(w, sheet_name="Deal_Periods", index=False)
        frame(pre_cols).to_excel(w, sheet_name="PreDeal_Snapshot", index=False)
        assumptions.to_excel(w, sheet_name="Capital_Assumptions", index=False)
    return str(path)
