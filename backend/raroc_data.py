"""
Post-Deal (ex-post) RAROC.

RAROC = Risk-Adjusted Return on Capital = risk-adjusted net income / economic
capital. Banks compute it twice in a deal's life:

  * Pre-deal (ex-ante): at pricing/origination, to decide whether to book the deal
    at or above the hurdle rate.
  * Post-deal (ex-post): after the deal is live, using ACTUAL/CURRENT conditions —
    today's funding cost (which moves with market interest rates), the borrower's
    migrated credit quality (PD/LGD/rating), current utilisation (EAD) and realised
    fees. It answers: "given how rates and credit have moved since we booked it, is
    this deal still earning its hurdle?"

The two things that move a deal's economics after booking are modelled explicitly:

  1. Market interest-rate changes. Floating-rate assets reprice with the funding
     index, so a parallel rate move barely touches net interest margin (NIM).
     FIXED-rate assets do not reprice, so when market rates rise the bank's funding
     cost rises against a locked asset yield and NIM compresses — the classic
     post-deal rate risk.
  2. Credit migration. A downgrade raises PD (and the risk weight), lifting expected
     loss and the economic capital the deal consumes — so RAROC falls even if the
     spread is unchanged.

Two headline earning figures are produced per deal, both risk-adjusted (net of
expected loss, with a capital benefit credited on economic capital):

  * Short-Term / Quick-Close Earning — what the bank realistically banks in the
    near term or if the facility closes/repays soon: roughly the next 12 months of
    risk-adjusted net income plus the unamortised upfront fee.
  * Lifetime Earning — total risk-adjusted economic profit over the full remaining
    life (net income to maturity plus the unamortised upfront fee).

The sample deal book is generated deterministically from the live portfolio's
largest facilities (so it is internally consistent with the rest of the app), with
the deal-specific terms a bank records — booking/maturity dates, fixed vs floating,
reference index, origination vs current base rate, margin, funding cost/FTP, fees,
cost-to-serve — synthesised per facility with a fixed seed. Export it with
export_sample_dataset(). All figures are illustrative.
"""

import hashlib
from datetime import timedelta

import numpy as np
import pandas as pd

from backend import data_loader as dl

# ------------------------------------------------------------------ assumptions

HURDLE_PCT = 12.0            # RAROC hurdle rate
RISK_FREE_PCT = 4.0         # return credited on economic capital (capital benefit)
CAPITAL_RATIO = 0.12        # economic capital as % of risk-weighted assets
N_DEALS = 40                # number of sample deals (largest facilities)

# Current market base rates by reference index (%). GCC is USD-pegged.
CURRENT_BASE = {"3M EIBOR": 3.70, "3M SOFR": 4.30, "3M SAIBOR": 5.40}

# Base all-in margin over the index by rating bucket (bps).
MARGIN_BY_BUCKET = {"AAA-A": 130, "BBB": 190, "BB": 260, "B": 360, "CCC": 520, "D": 800}
DEFAULT_MARGIN_BPS = 250

# Each downgrade notch lifts PD by ~35% (used to back out origination PD from the
# current PD given the rating migration since booking).
PD_PER_NOTCH = 1.35


def _index_for_region(region: str) -> str:
    if region in ("UAE", "Qatar", "Bahrain"):
        return "3M EIBOR"
    if region == "Saudi Arabia":
        return "3M SAIBOR"
    return "3M SOFR"


def _risk_weight(pd_pct: float) -> float:
    return float(np.clip(0.3 + pd_pct / 100 * 10, 0.2, 1.5))


def _seed(account_id: str) -> int:
    return int(hashlib.md5(str(account_id).encode()).hexdigest()[:8], 16)


def _deal_terms(row, asof: pd.Timestamp) -> dict:
    """Synthesise the deal-specific terms a bank records, deterministically per
    facility, then attach the live risk fields (EAD, PD, LGD, rating)."""
    rng = np.random.default_rng(_seed(row["Account ID"]))

    ead = float(row[dl.EAD_COL])
    undrawn = float(row.get("Undrawn (USD mn)", 0.0) or 0.0)
    region = row["Region"]
    index = _index_for_region(region)
    cur_base = CURRENT_BASE[index]

    rate_type = "Floating" if rng.random() < 0.6 else "Fixed"
    tenor = float(rng.choice([2, 3, 4, 5, 6, 7]))
    remaining = float(rng.uniform(0.5, tenor - 0.2))
    booking = asof - timedelta(days=int((tenor - remaining) * 365.25))
    maturity = asof + timedelta(days=int(remaining * 365.25))

    # Market rates mostly rose since booking (origination base biased below current).
    orig_base = float(np.clip(cur_base - rng.uniform(-1.0, 3.0), 0.4, 6.5))
    funding_spread = float(rng.uniform(0.25, 0.65))  # bank cost of funds over index

    bucket = dl.bucket_of_notch(row["Risk Rating"])
    margin_bps = MARGIN_BY_BUCKET.get(bucket, DEFAULT_MARGIN_BPS) + float(rng.uniform(-30, 30))
    margin = margin_bps / 100.0  # -> percent

    upfront_bps = float(rng.uniform(25, 100))
    commitment_bps = float(rng.uniform(20, 50))
    annual_fee = float(rng.uniform(0.0, 0.4))       # $mn agency/servicing
    cost_to_serve_bps = float(rng.uniform(20, 55))

    cur_pd = float(row["PD 12-Month (%)"])
    lgd = float(row["LGD (%)"])                     # 0-1 fraction in the source data
    # Back out origination PD from the rating migration since booking.
    notch_delta = (dl.NOTCH_INDEX.get(row["Risk Rating"], 10)
                   - dl.NOTCH_INDEX.get(row["Prev. Risk Rating"], 10))
    orig_pd = float(cur_pd / (PD_PER_NOTCH ** notch_delta))

    return {
        "deal_id": f"DL-{str(row['Account ID'])[-6:]}",
        "account_id": row["Account ID"], "customer_id": row["Customer ID"],
        "borrower": row["Borrower"], "sector": row["Sector"], "region": region,
        "product": row["Product Type"], "segment": row["Segment"],
        "booking_date": pd.Timestamp(booking), "maturity_date": pd.Timestamp(maturity),
        "tenor_years": tenor, "remaining_years": remaining,
        "ead": ead, "undrawn": undrawn, "commitment": ead + undrawn,
        "rate_type": rate_type, "index": index,
        "orig_base": orig_base, "cur_base": cur_base, "margin_pct": margin,
        "funding_spread": funding_spread,
        "upfront_bps": upfront_bps, "commitment_bps": commitment_bps, "annual_fee": annual_fee,
        "cost_to_serve_bps": cost_to_serve_bps,
        "orig_rating": row["Prev. Risk Rating"], "cur_rating": row["Risk Rating"],
        "cur_pd": cur_pd, "orig_pd": orig_pd, "lgd": lgd,
        "collateral": float(row.get("Collateral (USD mn)", 0.0) or 0.0),
    }


def _economics(d: dict) -> dict:
    """Full post-deal RAROC economics for one deal: origination vs current NIM,
    RAROC then/now, and the two earning figures."""
    undrawn = d["undrawn"]

    # Asset yield & funding, then vs now. Floating reprices with the index; fixed
    # keeps its origination coupon while funding follows the market.
    orig_yield = d["orig_base"] + d["margin_pct"]
    if d["rate_type"] == "Floating":
        cur_yield = d["cur_base"] + d["margin_pct"]
    else:
        cur_yield = orig_yield
    orig_funding = d["orig_base"] + d["funding_spread"]
    cur_funding = d["cur_base"] + d["funding_spread"]
    orig_nim = orig_yield - orig_funding
    cur_nim = cur_yield - cur_funding

    def raroc(nim, pd_pct, ead_):
        el_rate = pd_pct * d["lgd"]                              # % of EAD
        ec = ead_ * _risk_weight(pd_pct) * CAPITAL_RATIO
        nii = ead_ * nim / 100
        fee_income = undrawn * d["commitment_bps"] / 10000 + d["annual_fee"]
        el = ead_ * el_rate / 100
        opex = ead_ * d["cost_to_serve_bps"] / 10000
        cap_benefit = ec * RISK_FREE_PCT / 100
        net = nii + fee_income - el - opex + cap_benefit
        return (net / ec * 100 if ec else 0.0), net, ec, el

    orig_raroc, _, orig_ec, _ = raroc(orig_nim, d["orig_pd"], d["ead"])
    cur_raroc, annual_net, cur_ec, cur_el = raroc(cur_nim, d["cur_pd"], d["ead"])

    upfront_fee = d["commitment"] * d["upfront_bps"] / 10000
    unamortised_upfront = upfront_fee * (d["remaining_years"] / d["tenor_years"])

    st_horizon = min(d["remaining_years"], 1.0)
    short_term = annual_net * st_horizon + unamortised_upfront
    lifetime = annual_net * d["remaining_years"] + unamortised_upfront

    return {
        **d,
        "orig_yield": orig_yield, "cur_yield": cur_yield,
        "orig_funding": orig_funding, "cur_funding": cur_funding,
        "orig_nim": orig_nim, "cur_nim": cur_nim, "nim_change": cur_nim - orig_nim,
        "base_change_bps": (d["cur_base"] - d["orig_base"]) * 100,
        "orig_raroc": orig_raroc, "cur_raroc": cur_raroc, "raroc_change": cur_raroc - orig_raroc,
        "annual_net": annual_net, "economic_capital": cur_ec, "expected_loss": cur_el,
        "el_rate": d["cur_pd"] * d["lgd"],
        "upfront_fee": upfront_fee, "unamortised_upfront": unamortised_upfront,
        "short_term_earning": short_term, "lifetime_earning": lifetime,
        "above_hurdle": cur_raroc >= HURDLE_PCT,
    }


def _asof() -> pd.Timestamp:
    return pd.Timestamp(dl.DF.loc[dl.DF["Quarter"] == dl.DEFAULT_QUARTER, "Snapshot Date"].iloc[0])


def compute_post_deal_deals(n: int = N_DEALS) -> list[dict]:
    """The post-deal RAROC book: the n largest PERFORMING facilities, each with full
    ex-post economics. Deterministic and consistent with the live portfolio.

    RAROC is measured on performing deals only — Stage 3 / NPL names are in workout,
    not earning a spread — so the universe is restricted to IFRS 9 Stage 1-2,
    non-NPL facilities with a PD low enough to represent an accruing loan."""
    asof = _asof()
    cur = dl.filtered_quarter(dl.DEFAULT_QUARTER)
    performing = cur[(cur["IFRS 9 Stage"].isin([1, 2])) & (cur["NPL"] != "Yes")
                     & (cur["PD 12-Month (%)"] < 8.0)]
    performing = performing.sort_values(dl.EAD_COL, ascending=False).head(n)
    deals = [_economics(_deal_terms(row, asof)) for _, row in performing.iterrows()]
    deals.sort(key=lambda x: -x["lifetime_earning"])
    return deals


def compute_post_deal_summary(deals: list[dict] | None = None) -> dict:
    deals = deals if deals is not None else compute_post_deal_deals()
    total_ead = sum(d["ead"] for d in deals)
    total_ec = sum(d["economic_capital"] for d in deals)
    total_net = sum(d["annual_net"] for d in deals)
    port_raroc = (total_net / total_ec * 100) if total_ec else 0.0
    below = [d for d in deals if not d["above_hurdle"]]
    # Deals whose NIM compressed because market rates rose against a fixed coupon.
    rate_hit = [d for d in deals if d["rate_type"] == "Fixed" and d["nim_change"] < -0.05]
    return {
        "deals": deals, "n": len(deals),
        "total_ead": total_ead, "total_ec": total_ec,
        "portfolio_raroc": port_raroc, "hurdle": HURDLE_PCT,
        "short_term_total": sum(d["short_term_earning"] for d in deals),
        "lifetime_total": sum(d["lifetime_earning"] for d in deals),
        "below_hurdle_count": len(below),
        "below_hurdle_ead": sum(d["ead"] for d in below),
        "rate_compressed_count": len(rate_hit),
        "downgraded_count": sum(1 for d in deals
                                if dl.NOTCH_INDEX.get(d["cur_rating"], 10) > dl.NOTCH_INDEX.get(d["orig_rating"], 10)),
    }


# ------------------------------------------------------------ sample dataset export

SAMPLE_PATH = dl.DATA_PATH.parent / "Post_Deal_RAROC_Sample.xlsx"

# The recorded (input) fields — what a bank's system would hold per deal — plus the
# two calculated earning outputs, for the sample workbook.
_EXPORT_COLUMNS = [
    ("Deal ID", "deal_id"), ("Customer ID", "customer_id"), ("Borrower", "borrower"),
    ("Sector", "sector"), ("Region", "region"), ("Product", "product"), ("Segment", "segment"),
    ("Booking Date", "booking_date"), ("Maturity Date", "maturity_date"),
    ("Tenor (yrs)", "tenor_years"), ("Remaining (yrs)", "remaining_years"),
    ("Commitment (USD mn)", "commitment"), ("Outstanding EAD (USD mn)", "ead"),
    ("Undrawn (USD mn)", "undrawn"), ("Rate Type", "rate_type"), ("Reference Index", "index"),
    ("Orig. Base Rate (%)", "orig_base"), ("Current Base Rate (%)", "cur_base"),
    ("Margin (%)", "margin_pct"), ("Funding Spread (%)", "funding_spread"),
    ("Orig. Asset Yield (%)", "orig_yield"), ("Current Asset Yield (%)", "cur_yield"),
    ("Orig. Funding Cost (%)", "orig_funding"), ("Current Funding Cost (%)", "cur_funding"),
    ("Orig. NIM (%)", "orig_nim"), ("Current NIM (%)", "cur_nim"),
    ("Upfront Fee (bps)", "upfront_bps"), ("Commitment Fee (bps)", "commitment_bps"),
    ("Annual Fee (USD mn)", "annual_fee"), ("Cost to Serve (bps)", "cost_to_serve_bps"),
    ("Orig. Rating", "orig_rating"), ("Current Rating", "cur_rating"),
    ("Orig. PD (%)", "orig_pd"), ("Current PD (%)", "cur_pd"), ("LGD (frac)", "lgd"),
    ("Collateral (USD mn)", "collateral"),
    ("Expected Loss (USD mn)", "expected_loss"), ("Economic Capital (USD mn)", "economic_capital"),
    ("Orig. RAROC (%)", "orig_raroc"), ("Post-Deal RAROC (%)", "cur_raroc"),
    ("Short-Term / Quick-Close Earning (USD mn)", "short_term_earning"),
    ("Lifetime Earning (USD mn)", "lifetime_earning"),
]


def export_sample_dataset(path=SAMPLE_PATH) -> str:
    """Write the sample post-deal RAROC book to an .xlsx and return the path."""
    deals = compute_post_deal_deals()
    rows = [{label: d[key] for label, key in _EXPORT_COLUMNS} for d in deals]
    df = pd.DataFrame(rows)
    num_cols = df.select_dtypes(include="number").columns
    df[num_cols] = df[num_cols].round(3)
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Post-Deal RAROC", index=False)
    return str(path)
