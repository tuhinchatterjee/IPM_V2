"""
Data access layer for the IPM Executive Portfolio Risk Cockpit.

Loads every quarterly snapshot tab from Portfolio_Monitoring_Dataset.xlsx into a
single long-form DataFrame and exposes pure aggregation helpers that the Dash
callbacks use to compute KPIs, trend series, sector/borrower breakdowns and
AI risk signals for whatever filter combination the user has selected.
"""

import io
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# data_loader.py lives in backend/; the workbooks sit in the project root above it.
DATA_PATH = Path(__file__).resolve().parent.parent / "Portfolio_Monitoring_Dataset.xlsx"

SUPP_SHEET = "Borrower Supplementary"
_QUARTER_SHEET_RE = re.compile(r"^Q([1-4])\s+(\d{4})$")

EAD_COL = "CCF-Adjusted EAD (USD mn)"
RATING_ORDER = ["AAA-A", "BBB", "BB", "B", "CCC", "D"]
SEVERITY_RANK = {"RED": 0, "AMBER": 1, "GREEN": 2}

NOTCH_ORDER = [
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-", "B+", "B", "B-", "CCC+", "CCC", "CCC-", "CC", "C", "D",
]
NOTCH_INDEX = {n: i for i, n in enumerate(NOTCH_ORDER)}


def detect_quarter_sheets(sheet_names) -> list:
    """Quarterly snapshot tabs (named like 'Q1 2026'), sorted chronologically."""
    found = []
    for name in sheet_names:
        m = _QUARTER_SHEET_RE.match(str(name).strip())
        if m:
            found.append((int(m.group(2)), int(m.group(1)), str(name).strip()))
    return [name for _, _, name in sorted(found)]


def _load_all_quarters(xl: pd.ExcelFile, quarter_sheets: list) -> pd.DataFrame:
    frames = [pd.read_excel(xl, sheet_name=sheet) for sheet in quarter_sheets]
    df = pd.concat(frames, ignore_index=True)
    df["Quarter"] = pd.Categorical(df["Quarter"], categories=quarter_sheets, ordered=True)
    return df


# Dataset globals - populated by activate_dataset() at import time and re-populated
# in place when the user activates an uploaded workbook from the Data Hub page.
# Every aggregation helper reads these at call time, so a swap takes effect on the
# next page render without restarting the server.
DF = None
SUPP_DF = None
# Bumped by apply_dataset_frames on every dataset swap; the cache key for
# anything derived from the globals below.
DATASET_GENERATION = 0
QUARTER_SHEETS: list = []
QUARTER_OPTIONS: list = []
DEFAULT_QUARTER = None
SEGMENT_OPTIONS: list = []
SECTOR_OPTIONS: list = []
REGION_OPTIONS: list = []
RATING_OPTIONS: list = []
OWNER_OPTIONS: list = []
CUSTOMER_OPTIONS: list = []
CUSTOMER_ID_OPTIONS: list = []
DEFAULT_CUSTOMER = None
ACTIVE_SOURCE = None
ACTIVE_PATH = None
ACTIVE_LOADED_AT = None

SEVERITY_OPTIONS = [{"label": "Severity: All", "value": "All"}] + [
    {"label": s, "value": s} for s in ["RED", "AMBER", "GREEN"]
]


def _quarter_label(q: str) -> str:
    d = DF.loc[DF["Quarter"] == q, "Snapshot Date"].iloc[0]
    return d.strftime("%d-%b-%y")


def load_dataset_frames_from_workbook(path) -> tuple:
    """Parse a workbook into (df, supp, quarter_sheets) WITHOUT touching globals.
    Used by activate_dataset() and by the one-time Postgres migration script."""
    with pd.ExcelFile(path) as xl:
        quarter_sheets = detect_quarter_sheets(xl.sheet_names)
        if not quarter_sheets:
            raise ValueError("No quarterly snapshot sheets (named like 'Q1 2026') found in the workbook.")
        df = _load_all_quarters(xl, quarter_sheets)
        supp = pd.read_excel(xl, sheet_name=SUPP_SHEET).set_index("Customer ID")
    return df, supp, quarter_sheets


def _rebuild_option_globals() -> None:
    """Rebuild every dropdown/option global from the current DF/QUARTER_SHEETS.
    Assumes DF, SUPP_DF and QUARTER_SHEETS are already assigned."""
    global QUARTER_OPTIONS, DEFAULT_QUARTER, SEGMENT_OPTIONS, SECTOR_OPTIONS
    global REGION_OPTIONS, RATING_OPTIONS, OWNER_OPTIONS, CUSTOMER_OPTIONS
    global CUSTOMER_ID_OPTIONS, DEFAULT_CUSTOMER

    QUARTER_OPTIONS = [{"label": f"As of {_quarter_label(q)}", "value": q} for q in QUARTER_SHEETS]
    DEFAULT_QUARTER = QUARTER_SHEETS[-1]
    SEGMENT_OPTIONS = [{"label": "All Segments", "value": "All"}] + [
        {"label": s, "value": s} for s in sorted(DF["Segment"].unique())
    ]
    SECTOR_OPTIONS = [{"label": "Sector: All", "value": "All"}] + [
        {"label": s, "value": s} for s in sorted(DF["Sector"].unique())
    ]
    REGION_OPTIONS = [{"label": "All Regions (GCC)", "value": "All"}] + [
        {"label": r, "value": r} for r in sorted(DF["Region"].unique())
    ]
    RATING_OPTIONS = [{"label": "Rating: All", "value": "All"}] + [
        {"label": r, "value": r} for r in RATING_ORDER if r in DF["Rating Bucket"].unique()
    ]
    OWNER_OPTIONS = [{"label": "Owner: All", "value": "All"}] + [
        {"label": o, "value": o} for o in sorted(DF["Owner / Analyst"].unique())
    ]
    CUSTOMER_OPTIONS = [
        {"label": name, "value": cid}
        for cid, name in DF.sort_values(EAD_COL, ascending=False)
        .drop_duplicates("Customer ID")
        .sort_values("Borrower")[["Customer ID", "Borrower"]]
        .itertuples(index=False)
    ]
    CUSTOMER_ID_OPTIONS = [
        {"label": cid, "value": cid}
        for cid in DF.sort_values(EAD_COL, ascending=False)
        .drop_duplicates("Customer ID")
        .sort_values("Customer ID")["Customer ID"]
    ]
    _default_match = DF.loc[DF["Borrower"] == "Marina Bay Developments", "Customer ID"]
    DEFAULT_CUSTOMER = _default_match.iloc[0] if not _default_match.empty else CUSTOMER_OPTIONS[0]["value"]


def apply_dataset_frames(df: pd.DataFrame, supp: pd.DataFrame, quarter_sheets: list,
                         source: str, loaded_at=None, path=None) -> None:
    """Swap the module globals to an already-parsed dataset. Shared by the Excel
    loader (activate_dataset) and the Postgres-backed cache layer, so the ~70
    aggregation functions never change regardless of where the data came from."""
    global DF, SUPP_DF, QUARTER_SHEETS, ACTIVE_SOURCE, ACTIVE_PATH, ACTIVE_LOADED_AT
    global DATASET_GENERATION
    QUARTER_SHEETS = list(quarter_sheets)
    DF = df
    SUPP_DF = supp
    _rebuild_option_globals()
    ACTIVE_SOURCE = source
    ACTIVE_PATH = Path(path) if path else None
    ACTIVE_LOADED_AT = loaded_at or datetime.now()
    # Every swap of the globals bumps this, whatever the data came from. Callers
    # that memoise derived results key on it, so a new dataset can never be
    # served from a cache built against the previous one.
    DATASET_GENERATION += 1


def activate_dataset(path: Path, source: str) -> None:
    """(Re)build every module-level dataset global from the workbook at `path`.
    `source` is 'bundled' or 'uploaded' - surfaced on the Data Hub page."""
    df, supp, quarter_sheets = load_dataset_frames_from_workbook(path)
    apply_dataset_frames(df, supp, quarter_sheets, source, path=path)


# Import-time bootstrap: load the bundled workbook so data_loader is usable
# standalone (tests, the migration script, direct imports). In the running app the
# Postgres-backed cache layer (services/data_store) overrides this on the first
# request with whichever dataset version is marked active in the database.
activate_dataset(DATA_PATH, "bundled")


def account_options_for_customer(customer_id: str, quarter: str) -> list:
    """Account IDs (facilities) belonging to one customer in a given quarter -
    a customer can hold more than one facility (term loan, RCF, etc.)."""
    sub = DF[(DF["Quarter"] == quarter) & (DF["Customer ID"] == customer_id)]
    return [
        {"label": f"{row['Account ID']} - {row['Product Type']}", "value": row["Account ID"]}
        for _, row in sub.sort_values("Account ID").iterrows()
    ]


def prev_quarter(q: str) -> str | None:
    idx = QUARTER_SHEETS.index(q)
    return QUARTER_SHEETS[idx - 1] if idx > 0 else None


def apply_filters(df: pd.DataFrame, segment="All", sector="All", region="All", rating="All") -> pd.DataFrame:
    out = df
    if segment and segment != "All":
        out = out[out["Segment"] == segment]
    if sector and sector != "All":
        out = out[out["Sector"] == sector]
    if region and region != "All":
        out = out[out["Region"] == region]
    if rating and rating != "All":
        out = out[out["Rating Bucket"] == rating]
    return out


def filtered_quarter(quarter: str, segment="All", sector="All", region="All", rating="All") -> pd.DataFrame:
    base = DF[DF["Quarter"] == quarter]
    return apply_filters(base, segment, sector, region, rating)


# ---------------------------------------------------------------------- formatting

def fmt_bn(value_mn: float, decimals: int = 1) -> str:
    if value_mn is None:
        return "—"
    return f"${value_mn / 1000:,.{decimals}f}bn"


def fmt_mn(value_mn: float) -> str:
    if value_mn is None:
        return "—"
    return f"${value_mn:,.0f}m"


def fmt_pct(value: float, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}%"


# ------------------------------------------------------------------------ KPIs

def compute_kpis(quarter: str, segment="All", sector="All", region="All", rating="All") -> dict:
    cur = filtered_quarter(quarter, segment, sector, region, rating)
    pq = prev_quarter(quarter)
    prev = filtered_quarter(pq, segment, sector, region, rating) if pq else None

    total_ead = cur[EAD_COL].sum()
    prev_ead = prev[EAD_COL].sum() if prev is not None else None
    ead_qoq_pct = ((total_ead / prev_ead) - 1) * 100 if prev_ead else None

    npl_ead = cur.loc[cur["NPL"] == "Yes", EAD_COL].sum()
    npl_ratio = (npl_ead / total_ead * 100) if total_ead else 0.0
    npl_delta = None
    if prev is not None and prev_ead:
        prev_npl_ratio = prev.loc[prev["NPL"] == "Yes", EAD_COL].sum() / prev_ead * 100
        npl_delta = npl_ratio - prev_npl_ratio

    wl_ead = cur.loc[cur["Watchlist"] == "Yes", EAD_COL].sum()
    wl_pct = (wl_ead / total_ead * 100) if total_ead else 0.0

    stage_ead = {s: cur.loc[cur["IFRS 9 Stage"] == s, EAD_COL].sum() for s in (1, 2, 3)}
    stage2_delta = None
    if prev is not None:
        prev_stage2 = prev.loc[prev["IFRS 9 Stage"] == 2, EAD_COL].sum()
        stage2_delta = stage_ead[2] - prev_stage2

    raroc = (cur["RAROC (%)"] * cur[EAD_COL]).sum() / total_ead if total_ead else 0.0
    raroc_delta = None
    if prev is not None and prev_ead:
        prev_raroc = (prev["RAROC (%)"] * prev[EAD_COL]).sum() / prev_ead
        raroc_delta = raroc - prev_raroc

    breaches = int((cur["Appetite Breach"] == "Yes").sum())
    breach_delta = None
    if prev is not None:
        prev_breaches = int((prev["Appetite Breach"] == "Yes").sum())
        breach_delta = breaches - prev_breaches

    return {
        "total_ead": total_ead,
        "ead_qoq_pct": ead_qoq_pct,
        "npl_ratio": npl_ratio,
        "npl_delta": npl_delta,
        "watchlist_ead": wl_ead,
        "watchlist_pct": wl_pct,
        "stage_ead": stage_ead,
        "stage2_delta": stage2_delta,
        "raroc": raroc,
        "raroc_delta": raroc_delta,
        "breaches": breaches,
        "breach_delta": breach_delta,
        "row_count": len(cur),
        "has_prev": prev is not None,
    }


def compute_stage_breakdown(quarter: str, segment="All", sector="All", region="All", rating="All") -> dict:
    cur = filtered_quarter(quarter, segment, sector, region, rating)
    total = cur[EAD_COL].sum()
    stages = {}
    for s in (1, 2, 3):
        v = cur.loc[cur["IFRS 9 Stage"] == s, EAD_COL].sum()
        stages[s] = {"ead": v, "pct": (v / total * 100) if total else 0.0}
    return stages


def compute_ecl_trend(quarter: str, segment="All", sector="All", region="All", rating="All", n_quarters=4) -> list:
    idx = QUARTER_SHEETS.index(quarter)
    start = max(0, idx - n_quarters + 1)
    quarters = QUARTER_SHEETS[start: idx + 1]
    out = []
    for q in quarters:
        sub = filtered_quarter(q, segment, sector, region, rating)
        out.append({
            "quarter": q,
            "label": _quarter_label(q),
            "total_ecl": sub["Total ECL (USD mn)"].sum(),
            "total_ead": sub[EAD_COL].sum(),
        })
    return out


def compute_top_sectors(quarter: str, segment="All", sector="All", region="All", rating="All", top_n=5) -> list:
    cur = filtered_quarter(quarter, segment, sector, region, rating)
    grp = cur.groupby("Sector")[EAD_COL].sum().sort_values(ascending=False).head(top_n)
    return [{"sector": k, "ead": v} for k, v in grp.items()]


def compute_top_borrowers(quarter: str, segment="All", sector="All", region="All", rating="All", top_n=10,
                           sort_col="EAD", ascending=False) -> list:
    cur = filtered_quarter(quarter, segment, sector, region, rating)
    sort_map = {
        "Borrower": "Borrower",
        "Sector": "Sector",
        "EAD": EAD_COL,
        "Rating": "Risk Rating",
        "Stage": "IFRS 9 Stage",
        "Trend": "Trend",
    }
    col = sort_map.get(sort_col, EAD_COL)
    cur = cur.sort_values(col, ascending=ascending).head(top_n)
    records = cur[[
        "Account ID", "Borrower", "Sector", EAD_COL, "Risk Rating", "IFRS 9 Stage", "Trend",
    ]].rename(columns={EAD_COL: "EAD"}).to_dict("records")
    return records


def compute_ai_signals(quarter: str, segment="All", sector="All", region="All", rating="All", top_n=6) -> dict:
    cur = filtered_quarter(quarter, segment, sector, region, rating)
    pq = prev_quarter(quarter)

    flagged = cur[cur["Severity"].isin(["RED", "AMBER"])].copy()

    if pq:
        prev_sev = DF.loc[DF["Quarter"] == pq, ["Account ID", "Severity"]].rename(
            columns={"Severity": "Severity_prev"}
        )
        flagged = flagged.merge(prev_sev, on="Account ID", how="left")
        flagged["is_new"] = flagged["Severity_prev"].isna() | (flagged["Severity_prev"] == "GREEN")
    else:
        flagged["is_new"] = True

    flagged["sev_rank"] = flagged["Severity"].map(SEVERITY_RANK)
    flagged = flagged.sort_values(["sev_rank", EAD_COL], ascending=[True, False])

    new_count = int(flagged["is_new"].sum())
    total_flagged = len(flagged)
    red_count = int((flagged["Severity"] == "RED").sum())
    amber_count = int((flagged["Severity"] == "AMBER").sum())

    # Split the panel across both tiers (highest-EAD first within each) rather than a
    # single combined sort, so a handful of REDs don't crowd out AMBER signals entirely.
    # Backfill from the other tier if one is scarce, so top_n is still reached when possible.
    half = top_n // 2
    top_red = flagged[flagged["Severity"] == "RED"].head(top_n - half)
    top_amber = flagged[flagged["Severity"] == "AMBER"].head(half)
    top = pd.concat([top_red, top_amber])
    if len(top) < min(top_n, total_flagged):
        backfill = flagged[~flagged["Account ID"].isin(top["Account ID"])].head(top_n - len(top))
        top = pd.concat([top, backfill])
    top = top.sort_values(["sev_rank", EAD_COL], ascending=[True, False])
    signals = top[["Account ID", "Borrower", "Severity", "Trigger", "Recommended Action", "is_new"]].to_dict("records")

    return {
        "signals": signals,
        "new_count": new_count,
        "total_flagged": total_flagged,
        "red_count": red_count,
        "amber_count": amber_count,
        "remaining": max(0, total_flagged - len(signals)),
    }


def compute_signals_table(quarter: str, segment="All", sector="All", region="All", rating="All",
                           severity="All", owner="All", sort_col="Severity", ascending=True,
                           top_n=20) -> dict:
    """Full Early-Warning Signal dashboard feed: every account (any severity) under
    the current filters, plus portfolio-wide RED/AMBER/GREEN counts and average AI
    Risk Score for the KPI cards (computed over the whole filtered set, not just
    the page of rows actually shown in the table)."""
    cur = filtered_quarter(quarter, segment, sector, region, rating)
    if severity and severity != "All":
        cur = cur[cur["Severity"] == severity]
    if owner and owner != "All":
        cur = cur[cur["Owner / Analyst"] == owner]

    red_count = int((cur["Severity"] == "RED").sum())
    amber_count = int((cur["Severity"] == "AMBER").sum())
    green_count = int((cur["Severity"] == "GREEN").sum())
    avg_score = float(cur["AI Risk Score"].mean()) if len(cur) else 0.0

    cur = cur.copy()
    cur["sev_rank"] = cur["Severity"].map(SEVERITY_RANK)
    sort_map = {
        "Severity": "sev_rank", "Borrower": "Borrower", "Sector": "Sector",
        "Exposure": EAD_COL, "AI Score": "AI Risk Score", "Owner": "Owner / Analyst",
        "Reason Code": "Reason Code",
    }
    col = sort_map.get(sort_col, "sev_rank")
    if col == EAD_COL:
        cur = cur.sort_values(col, ascending=ascending)
    else:
        cur = cur.sort_values([col, EAD_COL], ascending=[ascending, False])

    total = len(cur)
    rows = cur.head(top_n)[[
        "Account ID", "Borrower", "Sector", EAD_COL, "Trigger", "AI Risk Score",
        "Reason Code", "Recommended Action", "Owner / Analyst", "Severity",
    ]].rename(columns={
        EAD_COL: "Exposure", "Owner / Analyst": "Owner", "AI Risk Score": "AI Score",
    }).to_dict("records")

    return {
        "rows": rows,
        "total": total,
        "red_count": red_count,
        "amber_count": amber_count,
        "green_count": green_count,
        "avg_score": avg_score,
    }


def get_borrower_detail(account_id: str, quarter: str) -> dict | None:
    sub = DF[(DF["Quarter"] == quarter) & (DF["Account ID"] == account_id)]
    if sub.empty:
        return None
    return sub.iloc[0].to_dict()


def account_customer_id(account_id: str, quarter: str) -> str | None:
    sub = DF[(DF["Quarter"] == quarter) & (DF["Account ID"] == account_id)]
    return sub.iloc[0]["Customer ID"] if not sub.empty else None


def find_customers(query: str, limit: int = 5) -> list:
    """Fuzzy-match a borrower name or Customer ID. Exact ID match wins outright;
    otherwise a case-insensitive substring match against borrower names."""
    if not query:
        return []
    query = query.strip()
    if query.upper() in SUPP_DF.index:
        cid = query.upper()
        return [{"customer_id": cid, "borrower": SUPP_DF.loc[cid, "Borrower"]}]

    names = DF.sort_values(EAD_COL, ascending=False).drop_duplicates("Customer ID")[["Customer ID", "Borrower"]]
    mask = names["Borrower"].str.contains(query, case=False, na=False, regex=False)
    matches = names[mask].head(limit)
    return [{"customer_id": r["Customer ID"], "borrower": r["Borrower"]} for _, r in matches.iterrows()]


# ============================================================ Borrower 360 view

def _customer_quarter_rows(customer_id: str, quarter: str) -> pd.DataFrame:
    return DF[(DF["Quarter"] == quarter) & (DF["Customer ID"] == customer_id)]


def get_borrower_profile(customer_id: str, quarter: str = DEFAULT_QUARTER) -> dict | None:
    """EAD-weighted, multi-account-aware snapshot of one obligor at a given quarter.

    Descriptive fields (sector/region/rating/...) come from the customer's largest
    account; risk-signal fields (severity/trigger/action) come from whichever of
    their accounts carries the worst severity, so a flagged small facility isn't
    masked by a clean large one.
    """
    cur = _customer_quarter_rows(customer_id, quarter)
    if cur.empty:
        return None

    cur = cur.copy()
    cur["_sev_rank"] = cur["Severity"].map(SEVERITY_RANK)
    lead = cur.sort_values(["_sev_rank", EAD_COL], ascending=[True, False]).iloc[0]
    primary = cur.loc[cur[EAD_COL].idxmax()]

    total_ead = cur[EAD_COL].sum()

    def wavg(col):
        return (cur[col] * cur[EAD_COL]).sum() / total_ead if total_ead else cur[col].mean()

    return {
        "customer_id": customer_id,
        "borrower": primary["Borrower"],
        "sector": primary["Sector"],
        "region": primary["Region"],
        "country": primary["Country"],
        "owner": primary["Owner / Analyst"],
        "segment": primary["Segment"],
        "total_ead": total_ead,
        "total_collateral": cur["Collateral (USD mn)"].sum(),
        "pd12": wavg("PD 12-Month (%)"),
        "lgd_pct": wavg("LGD (%)") * 100,
        "dscr": wavg("DSCR (x)"),
        "covenant_headroom": wavg("Covenant Headroom (%)"),
        "raroc": wavg("RAROC (%)"),
        "utilisation_pct": wavg("Utilisation (%)") * 100,
        "risk_rating": primary["Risk Rating"],
        "prev_risk_rating": primary["Prev. Risk Rating"],
        "internal_grade": primary["Internal Grade (1-10)"],
        "stage": int(primary["IFRS 9 Stage"]),
        "severity": lead["Severity"],
        "trigger": lead["Trigger"],
        "recommended_action": lead["Recommended Action"],
        "ai_risk_score": lead["AI Risk Score"],
        "downgrade_prob": lead["Downgrade Prob. (%)"],
        "watchlist": "Yes" if (cur["Watchlist"] == "Yes").any() else "No",
        "npl": "Yes" if (cur["NPL"] == "Yes").any() else "No",
        "trend": primary["Trend"],
        "account_count": len(cur),
        "snapshot_date": primary["Snapshot Date"],
    }


def _customer_metric_at(customer_id: str, quarter: str, col: str) -> float | None:
    cur = _customer_quarter_rows(customer_id, quarter)
    if cur.empty:
        return None
    w = cur[EAD_COL].sum()
    return (cur[col] * cur[EAD_COL]).sum() / w if w else cur[col].mean()


def _trend_label(fy24: float, fy25: float, higher_is_better: bool = True, tolerance: float = 0.05) -> str:
    if fy24 in (None, 0) or pd.isna(fy24) or pd.isna(fy25):
        return "Stable"
    rel_change = (fy25 - fy24) / abs(fy24)
    if abs(rel_change) <= tolerance:
        return "Stable"
    improved = rel_change > 0 if higher_is_better else rel_change < 0
    return "Better" if improved else "Worse"


def compute_borrower_ratios(customer_id: str) -> list:
    """Key Financial Ratios table: Net Leverage / Interest Coverage / DSCR / Current
    Ratio for FY24 vs FY25. Leverage/Coverage/Current Ratio come from the synthetic
    Borrower Supplementary sheet; DSCR is the real EAD-weighted value at the Q4
    2024 / Q4 2025 snapshots.
    """
    sup = SUPP_DF.loc[customer_id] if customer_id in SUPP_DF.index else None
    dscr_fy24 = _customer_metric_at(customer_id, "Q4 2024", "DSCR (x)")
    dscr_fy25 = _customer_metric_at(customer_id, "Q4 2025", "DSCR (x)")
    if dscr_fy24 is None:
        dscr_fy24 = dscr_fy25

    rows = [
        ("Net Leverage (x)", sup["Net Leverage FY24 (x)"] if sup is not None else None,
         sup["Net Leverage FY25 (x)"] if sup is not None else None, False),
        ("Interest Coverage (x)", sup["Interest Coverage FY24 (x)"] if sup is not None else None,
         sup["Interest Coverage FY25 (x)"] if sup is not None else None, True),
        ("DSCR (x)", dscr_fy24, dscr_fy25, True),
        ("Current Ratio (x)", sup["Current Ratio FY24 (x)"] if sup is not None else None,
         sup["Current Ratio FY25 (x)"] if sup is not None else None, True),
    ]
    out = []
    for label, fy24, fy25, higher_is_better in rows:
        trend = _trend_label(fy24, fy25, higher_is_better) if fy24 is not None and fy25 is not None else "Stable"
        out.append({"metric": label, "fy24": fy24, "fy25": fy25, "trend": trend})
    return out


def compute_rating_reconciliation(customer_id: str, quarter: str = DEFAULT_QUARTER) -> dict:
    profile = get_borrower_profile(customer_id, quarter)
    sup = SUPP_DF.loc[customer_id] if customer_id in SUPP_DF.index else None
    internal_rating = profile["risk_rating"] if profile else "—"
    internal_asof = profile["snapshot_date"] if profile else None
    external_rating = sup["External Rating"] if sup is not None else "—"
    external_asof = sup["External Rating As Of"] if sup is not None else None
    notch_gap = int(sup["Rating Notch Gap"]) if sup is not None else 0
    return {
        "internal_rating": internal_rating,
        "internal_asof": internal_asof,
        "external_rating": external_rating,
        "external_asof": external_asof,
        "notch_gap": notch_gap,
        "flagged": notch_gap != 0,
    }


def compute_covenant_projection(customer_id: str, quarter: str = DEFAULT_QUARTER, n_quarters: int = 4) -> dict:
    """Current covenant headroom plus a linear projection of when it would hit 0%,
    extrapolated from the trailing quarters' real Covenant Headroom values."""
    idx = QUARTER_SHEETS.index(quarter)
    window = QUARTER_SHEETS[max(0, idx - n_quarters + 1): idx + 1]

    headrooms, dates = [], []
    for q in window:
        h = _customer_metric_at(customer_id, q, "Covenant Headroom (%)")
        if h is None:
            continue
        headrooms.append(h)
        dates.append(DF.loc[DF["Quarter"] == q, "Snapshot Date"].iloc[0])

    current = headrooms[-1] if headrooms else None
    breach_label = None
    if len(headrooms) >= 2:
        x = np.arange(len(headrooms))
        slope, intercept = np.polyfit(x, headrooms, 1)
        if slope < -0.5:
            x_zero = -intercept / slope
            quarters_ahead = x_zero - (len(headrooms) - 1)
            if 0 < quarters_ahead <= 12:
                breach_date = dates[-1] + pd.DateOffset(days=int(round(quarters_ahead * 91.25)))
                breach_label = breach_date.strftime("%b-%Y")
            elif quarters_ahead <= 0:
                breach_label = "Imminent"
    return {"current": current, "likely_breach": breach_label}


def compute_collateral_coverage(customer_id: str, quarter: str = DEFAULT_QUARTER) -> dict:
    cur = _customer_quarter_rows(customer_id, quarter)
    sup = SUPP_DF.loc[customer_id] if customer_id in SUPP_DF.index else None
    if cur.empty:
        return {"coverage": None, "valuation_date": None, "months_stale": None}

    ead = cur[EAD_COL].sum()
    collateral = cur["Collateral (USD mn)"].sum()
    coverage = (collateral / ead) if ead else None

    valuation_date = sup["Last Collateral Valuation Date"] if sup is not None else None
    months_stale = None
    if valuation_date is not None:
        snapshot = cur["Snapshot Date"].iloc[0]
        months_stale = round((snapshot - pd.Timestamp(valuation_date)).days / 30.44)

    return {"coverage": coverage, "valuation_date": valuation_date, "months_stale": months_stale}


def compute_borrower_trend(customer_id: str, quarter: str = DEFAULT_QUARTER, n_quarters: int = 4) -> list:
    idx = QUARTER_SHEETS.index(quarter)
    window = QUARTER_SHEETS[max(0, idx - n_quarters + 1): idx + 1]
    out = []
    for q in window:
        cur = _customer_quarter_rows(customer_id, q)
        if cur.empty:
            continue
        ead = cur[EAD_COL].sum()
        pd12 = (cur["PD 12-Month (%)"] * cur[EAD_COL]).sum() / ead if ead else cur["PD 12-Month (%)"].mean()
        out.append({
            "quarter": q,
            "label": _quarter_label(q),
            "pd12": pd12,
            "total_ecl": cur["Total ECL (USD mn)"].sum(),
        })
    return out


def generate_ai_insight(customer_id: str, quarter: str = DEFAULT_QUARTER) -> dict:
    """Templated narrative built entirely from real fields: DSCR trajectory,
    covenant headroom, the account's own Trigger/Recommended Action, and the AI
    Risk Score as a confidence figure. No invented numbers."""
    profile = get_borrower_profile(customer_id, quarter)
    if profile is None:
        return {"text": "No data available for this borrower.", "confidence": None}

    idx = QUARTER_SHEETS.index(quarter)
    dscr_series = []
    for q in QUARTER_SHEETS[:idx + 1]:
        v = _customer_metric_at(customer_id, q, "DSCR (x)")
        if v is not None:
            dscr_series.append(v)

    consecutive_decline = 0
    for i in range(len(dscr_series) - 1, 0, -1):
        if dscr_series[i] < dscr_series[i - 1]:
            consecutive_decline += 1
        else:
            break

    if consecutive_decline >= 2:
        trend_phrase = f"deteriorated for {consecutive_decline} consecutive quarters"
    elif consecutive_decline == 1:
        trend_phrase = "shown early signs of deterioration"
    else:
        trend_phrase = "remained broadly stable"

    possessive = profile["borrower"] + ("'" if profile["borrower"].endswith("s") else "'s")
    sentence1 = f"{possessive} credit profile has {trend_phrase}, driven by {profile['trigger'].lower()}."

    concerns = []
    if profile["dscr"] < 1.0:
        concerns.append(f"DSCR has fallen below 1.0x ({profile['dscr']:.2f}x)")
    elif profile["dscr"] < 1.3:
        concerns.append(f"DSCR is tight at {profile['dscr']:.2f}x")
    if profile["covenant_headroom"] < 10:
        concerns.append("covenant headroom is critical")
    elif profile["covenant_headroom"] < 20:
        concerns.append("covenant headroom is tightening")
    if concerns:
        joined = ", ".join(concerns)
        sentence2 = joined[0].upper() + joined[1:] + "."
    else:
        sentence2 = "Key credit metrics remain within acceptable thresholds."

    action = profile["recommended_action"].rstrip(".")
    if profile["severity"] == "RED":
        sentence3 = f"Recommended next action: {action.lower()}; escalate to credit committee if DSCR is not restored by next quarter."
    elif profile["severity"] == "AMBER":
        sentence3 = f"Recommended next action: {action.lower()}."
    else:
        sentence3 = "No immediate action required beyond routine monitoring."

    text = f"{sentence1} {sentence2} {sentence3}"
    return {"text": text, "confidence": profile["ai_risk_score"]}


# ==================================================================== risk appetite
# Portfolio-wide caps aren't in the raw transaction data (no bank publishes its
# Risk Appetite Statement inside a facility ledger) - these are configured policy
# thresholds, expressed as % of total book EAD, evaluated against the real
# aggregated exposures below. Every number they're compared against is real data.

SECTOR_CAP_PCT = {
    "Real Estate": 20.0, "Contracting": 14.0, "Energy": 18.0, "Trade": 16.0,
    "Manufacturing": 14.0, "Hospitality": 7.0, "Transport": 9.0,
    "Healthcare": 8.0, "Retail Trade": 12.0, "Telecom": 10.0, "Utilities": 10.0,
    "Agriculture": 6.0,
}
DEFAULT_SECTOR_CAP_PCT = 10.0
SINGLE_NAME_CAP_PCT = 3.0
GROUP_CAP_PCT = 5.0
GEOGRAPHY_CAP_PCT = {
    "UAE": 42.0, "Saudi Arabia": 32.0, "Qatar": 14.0, "Kuwait": 10.0, "Oman": 8.0, "Bahrain": 6.0,
}
DEFAULT_GEOGRAPHY_CAP_PCT = 10.0
UNSECURED_CAP_PCT = 12.0
STAGE2_CAP_PCT = 15.0
NO_GROUP_MARKER = "—"  # em dash - placeholder value in the source file for "no obligor group"


def bucket_of_notch(notch: str) -> str:
    """Maps a fine-grained rating notch (e.g. 'BBB-') to the 6-bucket scale used
    for the Rating Bucket column and RATING_ORDER (AAA-A / BBB / BB / B / CCC / D)."""
    if not notch or pd.isna(notch):
        return "D"
    n = str(notch)
    if n[0] == "A":
        return "AAA-A"
    if n.startswith("BBB"):
        return "BBB"
    if n.startswith("BB"):
        return "BB"
    if n.startswith("B"):
        return "B"
    if n.startswith("CCC") or n in ("CC", "C"):
        return "CCC"
    return "D"


# ---------------------------------------------------------- concentration heatmap

def compute_concentration_heatmap(quarter: str, segment="All") -> dict:
    """Sector x Internal-Grade-Band EAD heatmap, portfolio HHI (by borrower share
    of total EAD), top-10 obligor concentration, largest obligor-group exposure,
    and sector-cap utilisation against the configured appetite thresholds above."""
    cur = filtered_quarter(quarter, segment=segment)
    total = cur[EAD_COL].sum()

    band_order = ["1-3", "4-5", "6", "7", "8+"]
    sectors = sorted(cur["Sector"].unique(), key=lambda s: -cur.loc[cur["Sector"] == s, EAD_COL].sum())
    grid = cur.groupby(["Sector", "Grade Band"])[EAD_COL].sum()
    rows = []
    for sec in sectors:
        cells = []
        for band in band_order:
            v = float(grid.get((sec, band), 0.0))
            pct = (v / total * 100) if total else 0.0
            cells.append({"band": band, "ead": v, "pct": pct})
        rows.append({"sector": sec, "cells": cells})

    by_customer = cur.groupby("Customer ID")[EAD_COL].sum()
    shares = (by_customer / total) if total else by_customer * 0
    hhi = float((shares ** 2).sum())
    top10_pct = float(by_customer.sort_values(ascending=False).head(10).sum() / total * 100) if total else 0.0

    groups = cur[cur["Obligor Group"] != NO_GROUP_MARKER].groupby("Obligor Group")[EAD_COL].sum()
    groups = groups.sort_values(ascending=False)
    largest_group = groups.index[0] if len(groups) else None
    largest_group_ead = float(groups.iloc[0]) if len(groups) else 0.0
    largest_group_pct = (largest_group_ead / total * 100) if total else 0.0

    sector_ead = cur.groupby("Sector")[EAD_COL].sum().sort_values(ascending=False)
    sector_caps = []
    for sec, ead in sector_ead.items():
        cap_pct = SECTOR_CAP_PCT.get(sec, DEFAULT_SECTOR_CAP_PCT)
        used_pct_of_book = (ead / total * 100) if total else 0.0
        utilisation = (used_pct_of_book / cap_pct * 100) if cap_pct else 0.0
        sector_caps.append({
            "sector": sec, "ead": float(ead), "pct_of_book": used_pct_of_book,
            "cap_pct": cap_pct, "utilisation": utilisation,
        })

    return {
        "band_order": band_order,
        "rows": rows,
        "total": total,
        "hhi": hhi,
        "top10_pct": top10_pct,
        "largest_group": largest_group,
        "largest_group_ead": largest_group_ead,
        "largest_group_pct": largest_group_pct,
        "largest_group_cap_pct": GROUP_CAP_PCT,
        "sector_caps": sector_caps,
    }


# --------------------------------------------------------------- rating migration

def compute_rating_migration(quarter: str, lookback_quarters: int = 4, segment="All") -> dict:
    """Migration matrix (opening rating bucket -> current rating bucket) comparing
    `quarter` against `lookback_quarters` earlier (default 4 = trailing year)."""
    idx = QUARTER_SHEETS.index(quarter)
    from_idx = max(0, idx - lookback_quarters)
    from_quarter = QUARTER_SHEETS[from_idx]

    cur = filtered_quarter(quarter, segment=segment)[["Account ID", "Risk Rating"]].rename(
        columns={"Risk Rating": "current_rating"})
    opening = DF.loc[DF["Quarter"] == from_quarter, ["Account ID", "Risk Rating"]].rename(
        columns={"Risk Rating": "opening_rating"})
    merged = cur.merge(opening, on="Account ID", how="inner")
    merged["opening_bucket"] = merged["opening_rating"].map(bucket_of_notch)
    merged["current_bucket"] = merged["current_rating"].map(bucket_of_notch)

    matrix = pd.crosstab(merged["opening_bucket"], merged["current_bucket"]).reindex(
        index=RATING_ORDER, columns=RATING_ORDER, fill_value=0)

    opening_rank = {b: i for i, b in enumerate(RATING_ORDER)}
    merged["_o"] = merged["opening_bucket"].map(opening_rank)
    merged["_c"] = merged["current_bucket"].map(opening_rank)
    upgrades = int((merged["_c"] < merged["_o"]).sum())
    downgrades = int((merged["_c"] > merged["_o"]).sum())
    stable = int((merged["_c"] == merged["_o"]).sum())
    net_migration = upgrades - downgrades

    cur_full = filtered_quarter(quarter, segment=segment)[["Account ID", "Sector", "Risk Rating"]]
    sec_merged = cur_full.merge(opening, on="Account ID", how="inner")
    sec_merged["opening_bucket"] = sec_merged["opening_rating"].map(bucket_of_notch)
    sec_merged["current_bucket"] = sec_merged["Risk Rating"].map(bucket_of_notch)
    sec_merged["opening_rank"] = sec_merged["opening_bucket"].map(opening_rank)
    sec_merged["current_rank"] = sec_merged["current_bucket"].map(opening_rank)
    downgrade_rows = sec_merged[sec_merged["current_rank"] > sec_merged["opening_rank"]]
    by_sector = downgrade_rows.groupby("Sector").size().sort_values(ascending=False)

    return {
        "from_quarter": from_quarter,
        "from_label": _quarter_label(from_quarter),
        "to_label": _quarter_label(quarter),
        "matrix": matrix,
        "buckets": RATING_ORDER,
        "upgrades": upgrades,
        "downgrades": downgrades,
        "stable": stable,
        "net_migration": net_migration,
        "downgrades_by_sector": [{"sector": s, "count": int(c)} for s, c in by_sector.items()],
    }


# ------------------------------------------------------------------------- limits

def _limit_rows(quarter: str, segment="All") -> list:
    """The appetite lines for one quarter. Split out from the dashboard so the
    same construction can be re-run on the previous quarter for a like-for-like
    quarter-on-quarter comparison."""
    cur = filtered_quarter(quarter, segment=segment)
    total = cur[EAD_COL].sum()

    rows = []
    sector_ead = cur.groupby("Sector")[EAD_COL].sum().sort_values(ascending=False)
    for sec, ead in sector_ead.items():
        cap_pct = SECTOR_CAP_PCT.get(sec, DEFAULT_SECTOR_CAP_PCT)
        cap_usd = cap_pct / 100 * total
        rows.append({"type": "Sector", "label": f"{sec} (sector)", "used": float(ead), "cap": cap_usd,
                     "pct": (ead / cap_usd * 100) if cap_usd else 0.0})

    by_customer = cur.groupby(["Customer ID", "Borrower"])[EAD_COL].sum().reset_index()
    top_name = by_customer.sort_values(EAD_COL, ascending=False).iloc[0] if len(by_customer) else None
    if top_name is not None:
        cap_usd = SINGLE_NAME_CAP_PCT / 100 * total
        rows.append({"type": "Single-name", "label": f"Single-name ({top_name['Borrower']})",
                     "used": float(top_name[EAD_COL]), "cap": cap_usd,
                     "pct": (top_name[EAD_COL] / cap_usd * 100) if cap_usd else 0.0})

    groups = cur[cur["Obligor Group"] != NO_GROUP_MARKER].groupby("Obligor Group")[EAD_COL].sum()
    if len(groups):
        top_group = groups.sort_values(ascending=False).index[0]
        top_group_ead = float(groups.loc[top_group])
        cap_usd = GROUP_CAP_PCT / 100 * total
        rows.append({"type": "Group", "label": f"{top_group}", "used": top_group_ead, "cap": cap_usd,
                     "pct": (top_group_ead / cap_usd * 100) if cap_usd else 0.0})

    geo_ead = cur.groupby("Region")[EAD_COL].sum().sort_values(ascending=False)
    for region, ead in geo_ead.items():
        cap_pct = GEOGRAPHY_CAP_PCT.get(region, DEFAULT_GEOGRAPHY_CAP_PCT)
        cap_usd = cap_pct / 100 * total
        rows.append({"type": "Geography", "label": f"{region} (geography)", "used": float(ead), "cap": cap_usd,
                     "pct": (ead / cap_usd * 100) if cap_usd else 0.0})

    unsecured_ead = cur.loc[cur["Collateral Type"] == "Unsecured", EAD_COL].sum()
    cap_usd = UNSECURED_CAP_PCT / 100 * total
    rows.append({"type": "Product", "label": "Unsecured exposure", "used": float(unsecured_ead), "cap": cap_usd,
                 "pct": (unsecured_ead / cap_usd * 100) if cap_usd else 0.0})

    stage2_ead = cur.loc[cur["IFRS 9 Stage"] == 2, EAD_COL].sum()
    cap_usd = STAGE2_CAP_PCT / 100 * total
    rows.append({"type": "Stage", "label": "Stage 2 exposure", "used": float(stage2_ead), "cap": cap_usd,
                 "pct": (stage2_ead / cap_usd * 100) if cap_usd else 0.0})

    rows.sort(key=lambda r: r["pct"], reverse=True)
    return rows


def compute_limits_dashboard(quarter: str, segment="All") -> dict:
    """Approved-limit-vs-utilisation across every configured appetite dimension:
    sector caps, single-name, obligor group, geography, product-secured and
    Stage-2 ceiling - each evaluated against real aggregated EAD.

    Each line also carries its movement since the previous quarter. Utilisation is
    a level, and a level alone doesn't say whether a limit is being approached or
    released - 88% falling from 95% is a different conversation from 88% rising
    from 70%. Lines are matched by label; the single-name and group lines track
    the largest exposure, so if that changes hands between quarters there is no
    comparable prior and the delta is left as None rather than comparing two
    different borrowers.
    """
    cur = filtered_quarter(quarter, segment=segment)
    rows = _limit_rows(quarter, segment)

    pq = prev_quarter(quarter)
    prev_by_label = {r["label"]: r for r in _limit_rows(pq, segment)} if pq else {}
    for r in rows:
        prior = prev_by_label.get(r["label"])
        r["prev_pct"] = prior["pct"] if prior else None
        r["prev_used"] = prior["used"] if prior else None
        r["delta_pct"] = (r["pct"] - prior["pct"]) if prior else None
        r["delta_used"] = (r["used"] - prior["used"]) if prior else None
        # Crossing the 100% line this quarter is the event a committee acts on.
        r["newly_breached"] = bool(prior and prior["pct"] < 100 <= r["pct"])
        r["newly_cured"] = bool(prior and r["pct"] < 100 <= prior["pct"])

    active_breaches = sum(1 for r in rows if r["pct"] >= 100)
    near_limit = sum(1 for r in rows if 90 <= r["pct"] < 100)
    within_appetite = sum(1 for r in rows if r["pct"] < 90)

    real_breach_count = int((cur["Appetite Breach"] == "Yes").sum())

    return {
        "rows": rows,
        "active_breaches": active_breaches,
        "near_limit": near_limit,
        "within_appetite": within_appetite,
        "real_breach_count": real_breach_count,
        "prev_quarter": pq,
        "newly_breached": sum(1 for r in rows if r["newly_breached"]),
        "newly_cured": sum(1 for r in rows if r["newly_cured"]),
        "rising": sum(1 for r in rows if (r["delta_pct"] or 0) > 0),
        "has_comparison": bool(pq),
    }


# ------------------------------------------------------------- covenant/collateral

COLLATERAL_HAIRCUT_PCT = {
    "Real Estate": 30.0, "Cash / Deposit": 3.0, "Corporate Guarantee": 15.0,
    "Receivables": 35.0, "Unsecured": 100.0,
}


def compute_covenant_watchlist(quarter: str, min_headroom: float = 20.0, top_n: int = 12) -> dict:
    """Portfolio-wide covenant + collateral monitoring for borrowers whose
    headroom has fallen below `min_headroom`%, worst-headroom-first."""
    cur = filtered_quarter(quarter)
    watch = cur[(cur["Covenant Headroom (%)"] < min_headroom) | (cur["Watchlist"] == "Yes")].copy()
    watch = watch.sort_values("Covenant Headroom (%)", ascending=True)
    watch = watch.drop_duplicates("Customer ID").head(top_n)

    covenant_rows, collateral_rows = [], []
    for _, r in watch.iterrows():
        cid = r["Customer ID"]
        sup = SUPP_DF.loc[cid] if cid in SUPP_DF.index else None
        leverage = float(sup["Net Leverage FY25 (x)"]) if sup is not None else None
        int_cov = float(sup["Interest Coverage FY25 (x)"]) if sup is not None else None
        liquidity = float(sup["Current Ratio FY25 (x)"]) if sup is not None else None
        proj = compute_covenant_projection(cid, quarter)
        covenant_rows.append({
            "borrower": r["Borrower"], "customer_id": cid,
            "dscr": float(r["DSCR (x)"]), "leverage": leverage, "int_cov": int_cov, "liquidity": liquidity,
            "headroom": float(r["Covenant Headroom (%)"]), "likely_breach": proj["likely_breach"],
        })

        collateral = float(r["Collateral (USD mn)"])
        ead = float(r[EAD_COL])
        ctype = r["Collateral Type"]
        haircut = COLLATERAL_HAIRCUT_PCT.get(ctype, 25.0)
        forced_sale = collateral * (1 - haircut / 100)
        coverage_gap = forced_sale - ead
        cov = compute_collateral_coverage(cid, quarter)
        collateral_rows.append({
            "borrower": r["Borrower"], "type": ctype, "value": collateral,
            "valn_age_months": cov["months_stale"],
            "ltv": (ead / collateral * 100) if collateral else None,
            "forced_sale": forced_sale, "haircut": haircut, "coverage_gap": coverage_gap,
        })

    return {"covenant_rows": covenant_rows, "collateral_rows": collateral_rows}


# ------------------------------------------------------------------------- EAD

def compute_ead_buildup(quarter: str, segment="All") -> dict:
    cur = filtered_quarter(quarter, segment=segment)
    funded = float(cur["Exposure (USD mn)"].sum())
    undrawn = float(cur["Undrawn (USD mn)"].sum())
    ccf_adjusted = float(cur[EAD_COL].sum())

    is_guarantee = cur["Product Type"].isin(["Letter of Guarantee"])
    is_lc_deriv = cur["Product Type"].isin(["Letter of Credit", "Derivative"])
    guarantees = float(cur.loc[is_guarantee, "Exposure (USD mn)"].sum())
    lc_deriv = float(cur.loc[is_lc_deriv, EAD_COL].sum())
    term_funded = float(cur.loc[~is_guarantee & ~is_lc_deriv, "Exposure (USD mn)"].sum())
    undrawn_committed = float(cur.loc[~is_guarantee & ~is_lc_deriv, "Undrawn (USD mn)"].sum())
    avg_ccf_undrawn = (float(cur.loc[~is_guarantee & ~is_lc_deriv, EAD_COL].sum()) - term_funded)

    idx = QUARTER_SHEETS.index(quarter)
    window = QUARTER_SHEETS[max(0, idx - 3): idx + 1]
    util_trend = []
    for q in window:
        sub = filtered_quarter(q, segment=segment)
        port_util = float((sub["Utilisation (%)"] * sub["Limit (USD mn)"]).sum() / sub["Limit (USD mn)"].sum() * 100) \
            if sub["Limit (USD mn)"].sum() else 0.0
        re_sub = sub[sub["Sector"] == "Real Estate"]
        re_util = float((re_sub["Utilisation (%)"] * re_sub["Limit (USD mn)"]).sum() / re_sub["Limit (USD mn)"].sum() * 100) \
            if len(re_sub) and re_sub["Limit (USD mn)"].sum() else port_util
        util_trend.append({"quarter": q, "label": _quarter_label(q), "portfolio": port_util, "real_estate": re_util})

    cur = cur.copy()
    cur["util_delta_pp"] = (cur["Utilisation (%)"] - cur["Prev. Utilisation (%)"]) * 100
    cur["ead_delta"] = cur[EAD_COL] - cur[EAD_COL] * (cur["Prev. Utilisation (%)"] / cur["Utilisation (%)"]).where(cur["Utilisation (%)"] > 0, 1)
    alerts = cur[cur["util_delta_pp"] > 15].sort_values("util_delta_pp", ascending=False).head(6)
    alert_rows = [{
        "borrower": r["Borrower"], "prev_pct": r["Prev. Utilisation (%)"] * 100, "now_pct": r["Utilisation (%)"] * 100,
        "delta_pp": r["util_delta_pp"], "ead_delta": r["ead_delta"],
    } for _, r in alerts.iterrows()]

    return {
        "funded": funded, "undrawn": undrawn, "guarantees": guarantees, "ccf_adjusted": ccf_adjusted,
        "buildup": [
            {"component": "Funded loans", "notional": term_funded, "ccf": 100.0, "ccf_ead": term_funded},
            {"component": "Undrawn commitments", "notional": undrawn_committed, "ccf": 50.0, "ccf_ead": avg_ccf_undrawn},
            {"component": "Guarantees / SBLC", "notional": guarantees, "ccf": 100.0, "ccf_ead": guarantees},
            {"component": "Trade LCs + deriv. PFE", "notional": lc_deriv, "ccf": None, "ccf_ead": lc_deriv},
        ],
        "util_trend": util_trend,
        "alerts": alert_rows,
    }


# ---------------------------------------------------------------------- IFRS 9

def compute_ecl_bridge(quarter: str, segment="All") -> dict:
    pq = prev_quarter(quarter)
    cur = filtered_quarter(quarter, segment=segment)
    prev = filtered_quarter(pq, segment=segment) if pq else None

    opening = float(prev["Total ECL (USD mn)"].sum()) if prev is not None else float(cur["Total ECL (USD mn)"].sum())
    closing = float(cur["Total ECL (USD mn)"].sum())

    merged = None
    if prev is not None:
        merged = cur[["Account ID", "IFRS 9 Stage", "Model ECL (USD mn)", "Macro Overlay (USD mn)", "DPD (days)"]].merge(
            prev[["Account ID", "IFRS 9 Stage", "Model ECL (USD mn)", "Macro Overlay (USD mn)"]],
            on="Account ID", how="outer", suffixes=("", "_prev"))
        merged = merged.fillna(0)
        migration_delta = float(
            merged.loc[merged["IFRS 9 Stage"] != merged["IFRS 9 Stage_prev"], "Model ECL (USD mn)"].sum()
            - merged.loc[merged["IFRS 9 Stage"] != merged["IFRS 9 Stage_prev"], "Model ECL (USD mn)_prev"].sum()
        )
        dpd_delta = float(
            merged.loc[(merged["IFRS 9 Stage"] == merged["IFRS 9 Stage_prev"]) & (cur.set_index("Account ID")["DPD (days)"].reindex(merged["Account ID"]).fillna(0).gt(0).values),
                       "Model ECL (USD mn)"].sum()
            - merged.loc[(merged["IFRS 9 Stage"] == merged["IFRS 9 Stage_prev"]) & (cur.set_index("Account ID")["DPD (days)"].reindex(merged["Account ID"]).fillna(0).gt(0).values),
                         "Model ECL (USD mn)_prev"].sum()
        ) * 0.3
        macro_delta = float(merged["Macro Overlay (USD mn)"].sum() - merged["Macro Overlay (USD mn)_prev"].sum())
        new_stage3 = merged[(merged["IFRS 9 Stage"] == 3) & (merged["IFRS 9 Stage_prev"] != 3)]
        new_s3_delta = float(new_stage3["Model ECL (USD mn)"].sum() - new_stage3["Model ECL (USD mn)_prev"].sum())
        migration_delta -= new_s3_delta
        accounted = migration_delta + dpd_delta + macro_delta + new_s3_delta
        residual = (closing - opening) - accounted
    else:
        migration_delta = dpd_delta = macro_delta = new_s3_delta = 0.0
        residual = closing - opening

    stage_table = []
    for s in (1, 2, 3):
        sub = cur[cur["IFRS 9 Stage"] == s]
        ead = float(sub[EAD_COL].sum())
        pd12 = float((sub["PD 12-Month (%)"] * sub[EAD_COL]).sum() / ead) if ead else 0.0
        lgd = float((sub["LGD (%)"] * sub[EAD_COL]).sum() / ead * 100) if ead else 0.0
        ecl = float(sub["Total ECL (USD mn)"].sum())
        cover = (ecl / ead * 100) if ead else 0.0
        stage_table.append({"stage": s, "ead": ead, "pd": pd12, "lgd": lgd, "cover": cover, "ecl": ecl})

    total_ead = float(cur[EAD_COL].sum())
    stage2_ratio = (stage_table[1]["ead"] / total_ead * 100) if total_ead else 0.0
    ecl_coverage = (closing / total_ead * 100) if total_ead else 0.0
    macro_overlay_total = float(cur["Macro Overlay (USD mn)"].sum())

    sicr_counts = cur.loc[cur["IFRS 9 Stage"] == 2, "SICR Trigger"].value_counts().to_dict()

    return {
        "opening": opening, "closing": closing,
        "bridge": [
            {"label": "Opening", "value": opening},
            {"label": "Migration", "value": migration_delta},
            {"label": "30+ DPD", "value": dpd_delta},
            {"label": "Macro", "value": macro_delta},
            {"label": "New S3", "value": new_s3_delta},
            {"label": "Other", "value": residual},
        ],
        "stage_table": stage_table,
        "stage2_ratio": stage2_ratio,
        "ecl_coverage": ecl_coverage,
        "macro_overlay": macro_overlay_total,
        "sicr_counts": sicr_counts,
    }


# --------------------------------------------------------------- profitability

def compute_profitability(quarter: str) -> dict:
    """RAROC by sector against a configured 12% hurdle rate; RoRWA uses a simplified
    IRB-style risk-weight proxy (no RWA field exists in the source data) so it's
    directional, not a substitute for a real capital model."""
    cur = filtered_quarter(quarter)
    hurdle = 12.0
    rows = []
    for sec, sub in cur.groupby("Sector"):
        ead = float(sub[EAD_COL].sum())
        raroc = float((sub["RAROC (%)"] * sub[EAD_COL]).sum() / ead) if ead else 0.0
        pd12 = float((sub["PD 12-Month (%)"] * sub[EAD_COL]).sum() / ead) if ead else 0.0
        risk_weight = min(1.5, max(0.2, 0.3 + pd12 / 100 * 10))
        rwa = ead * risk_weight
        rorwa = (raroc / 100 * ead) / rwa * 100 if rwa else 0.0
        rows.append({"sector": sec, "ead": ead, "raroc": raroc, "rorwa": rorwa, "above_hurdle": raroc >= hurdle})
    rows.sort(key=lambda r: r["raroc"], reverse=True)
    return {"rows": rows, "hurdle": hurdle}


# -------------------------------------------------------------------- watchlist

WATCHLIST_COLUMNS = ["New", "Under Review", "Watchlist", "Restructuring", "Recovery", "Closed"]


def _watchlist_column(row) -> str:
    if row["Severity"] == "GREEN" and row["Watchlist"] == "Yes":
        return "Closed"
    if row["is_new"]:
        return "New"
    if row["Severity"] == "RED" and row["IFRS 9 Stage"] == 3 and row["NPL"] == "Yes":
        return "Recovery"
    if row["Severity"] == "RED":
        return "Restructuring"
    if row["Severity"] == "AMBER" and row["Trend"] == "Down":
        return "Watchlist"
    return "Under Review"


def compute_watchlist_board(quarter: str, top_n_per_col: int = 6) -> dict:
    cur = filtered_quarter(quarter)
    watch = cur[(cur["Watchlist"] == "Yes") | (cur["Severity"] != "GREEN")].copy()
    watch = watch.drop_duplicates("Customer ID")

    pq = prev_quarter(quarter)
    if pq:
        prev_sev = DF.loc[DF["Quarter"] == pq, ["Account ID", "Severity"]].rename(columns={"Severity": "Severity_prev"})
        watch = watch.merge(prev_sev, on="Account ID", how="left")
        watch["is_new"] = watch["Severity_prev"].isna() | (watch["Severity_prev"] == "GREEN")
    else:
        watch["is_new"] = True

    watch["column"] = watch.apply(_watchlist_column, axis=1)
    watch["sev_rank"] = watch["Severity"].map(SEVERITY_RANK)
    watch = watch.sort_values(["sev_rank", EAD_COL], ascending=[True, False])

    board = {}
    for col in WATCHLIST_COLUMNS:
        sub = watch[watch["column"] == col].head(top_n_per_col)
        board[col] = [{
            "borrower": r["Borrower"], "customer_id": r["Customer ID"], "ead": float(r[EAD_COL]),
            "owner_initials": "".join(p[0] for p in str(r["Owner / Analyst"]).split()[:2]).upper(),
            "ai_score": float(r["AI Risk Score"]), "trigger": r["Trigger"],
        } for _, r in sub.iterrows()]

    total_counts = {col: int((watch["column"] == col).sum()) for col in WATCHLIST_COLUMNS}
    return {"board": board, "counts": total_counts}


# ------------------------------------------------------------------------ stress

STRESS_ELASTICITIES = {
    # Simplified, transparent sensitivities applied to real Q1 2026 baseline
    # figures - illustrative of the transmission mechanism, not a calibrated model.
    "gdp_per_100bps_rate": -0.6,          # % GDP growth impact per +100bps policy rate
    "cre_price_per_100bps_rate": -4.5,    # % CRE price impact per +100bps policy rate
    "pd_notch_per_10pct_cre_fall": 0.35,  # PD notch-equivalent widening per 10% CRE price fall
    "ecl_sensitivity_re_contracting": 2.1,  # ECL $ multiplier applied to RE/Contracting exposure under stress
}


def compute_stress_scenario(quarter: str, rate_shock_bps: float = 0.0, cre_price_shock_pct: float = 0.0) -> dict:
    """Runs a simplified macro shock through the real Q1 2026 book: a policy-rate
    shock and/or a CRE price shock, propagated to GDP, CRE valuations, PiT PD,
    and re-computed stressed ECL/CET1/NPL/covenant-breach counts."""
    base = filtered_quarter(quarter)
    base_ecl = float(base["Total ECL (USD mn)"].sum())
    base_ead = float(base[EAD_COL].sum())
    base_npl_ead = float(base.loc[base["NPL"] == "Yes", EAD_COL].sum())
    base_npl_pct = (base_npl_ead / base_ead * 100) if base_ead else 0.0

    gdp_impact = STRESS_ELASTICITIES["gdp_per_100bps_rate"] * (rate_shock_bps / 100)
    cre_impact_from_rate = STRESS_ELASTICITIES["cre_price_per_100bps_rate"] * (rate_shock_bps / 100)
    total_cre_price_fall = abs(cre_price_shock_pct) + abs(cre_impact_from_rate)
    pit_pd_notches = STRESS_ELASTICITIES["pd_notch_per_10pct_cre_fall"] * (total_cre_price_fall / 10)

    re_contracting = base[base["Sector"].isin(["Real Estate", "Contracting"])]
    re_contracting_ecl = float(re_contracting["Total ECL (USD mn)"].sum())
    other_ecl = base_ecl - re_contracting_ecl
    stress_multiplier = 1 + (total_cre_price_fall / 100) * STRESS_ELASTICITIES["ecl_sensitivity_re_contracting"]
    stressed_re_ecl = re_contracting_ecl * stress_multiplier
    rate_only_multiplier = 1 + (abs(rate_shock_bps) / 300) * 0.35
    stressed_other_ecl = other_ecl * rate_only_multiplier
    stressed_ecl = stressed_re_ecl + stressed_other_ecl
    ecl_delta = stressed_ecl - base_ecl

    cet1_bps_impact = -(ecl_delta / base_ead * 10000 * 0.4) if base_ead else 0.0
    stressed_npl_pct = base_npl_pct + (total_cre_price_fall / 10) * 0.5 + (abs(rate_shock_bps) / 100) * 0.15

    re_contracting = re_contracting.copy()
    re_contracting["stressed_headroom"] = re_contracting["Covenant Headroom (%)"] - pit_pd_notches * 3
    breach_names = re_contracting.loc[re_contracting["stressed_headroom"] < 0, "Borrower"].drop_duplicates().tolist()

    return {
        "base_ecl": base_ecl, "stressed_ecl": stressed_ecl, "ecl_delta": ecl_delta,
        "cet1_bps_impact": cet1_bps_impact, "base_npl_pct": base_npl_pct, "stressed_npl_pct": stressed_npl_pct,
        "gdp_impact_pct": gdp_impact, "cre_price_fall_pct": total_cre_price_fall,
        "pit_pd_notches": pit_pd_notches, "covenant_breach_names": breach_names,
        "covenant_breach_count": len(breach_names), "rate_shock_bps": rate_shock_bps,
        "cre_price_shock_pct": cre_price_shock_pct,
    }


_RATE_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*bps", re.IGNORECASE)
_PCT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%", re.IGNORECASE)


def parse_scenario_text(text: str) -> dict:
    """Extracts a rate shock (bps) and/or a price-fall shock (%) from free-text
    like '+300bps rate shock' or 'a 25% fall in real estate prices'. Defaults to
    0 for whichever isn't mentioned - callers accumulate across turns."""
    rate_match = _RATE_RE.search(text)
    pct_match = _PCT_RE.search(text)
    rate_bps = float(rate_match.group(1)) if rate_match else 0.0
    price_pct = abs(float(pct_match.group(1))) if pct_match else 0.0
    is_re_related = any(k in text.lower() for k in ["real estate", "property", "cre", "housing"])
    return {
        "rate_shock_bps": rate_bps,
        "cre_price_shock_pct": price_pct if is_re_related else 0.0,
        "recognised": bool(rate_match or pct_match),
    }


def compute_reverse_stress(quarter: str, target_cet1_bps: float = -100.0) -> dict:
    """Solves (by simple forward search) for the smallest uniform rate shock that
    would breach a target CET1 impact, using the same elasticities as compute_stress_scenario."""
    for bps in range(25, 2001, 25):
        result = compute_stress_scenario(quarter, rate_shock_bps=bps, cre_price_shock_pct=0.0)
        if result["cet1_bps_impact"] <= target_cet1_bps:
            return {"required_rate_shock_bps": bps, "at_breach": result, "target_cet1_bps": target_cet1_bps}
    return {"required_rate_shock_bps": None, "at_breach": None, "target_cet1_bps": target_cet1_bps}


# --------------------------------------------------------------------- sector KPIs

def compute_sector_kpis(quarter: str, region: str = "All") -> list:
    cur = filtered_quarter(quarter, region=region)
    out = []
    for sec, sub in cur.groupby("Sector"):
        ead = float(sub[EAD_COL].sum())
        pd12 = float((sub["PD 12-Month (%)"] * sub[EAD_COL]).sum() / ead) if ead else 0.0
        stage2_pct = float(sub.loc[sub["IFRS 9 Stage"] == 2, EAD_COL].sum() / ead * 100) if ead else 0.0
        raroc = float((sub["RAROC (%)"] * sub[EAD_COL]).sum() / ead) if ead else 0.0
        out.append({"sector": sec, "ead": ead, "pd": pd12, "stage2_pct": stage2_pct, "raroc": raroc,
                     "borrower_count": sub["Customer ID"].nunique()})
    out.sort(key=lambda r: r["ead"], reverse=True)
    return out


# -------------------------------------------------------------------- pricing

def compute_underpriced_borrowers(quarter: str, hurdle: float = 12.0, top_n: int = 10) -> list:
    cur = filtered_quarter(quarter)
    grouped = cur.groupby(["Customer ID", "Borrower", "Sector"]).apply(
        lambda g: pd.Series({"ead": g[EAD_COL].sum(), "raroc": (g["RAROC (%)"] * g[EAD_COL]).sum() / g[EAD_COL].sum()}),
        include_groups=False,
    ).reset_index()
    below = grouped[grouped["raroc"] < hurdle].sort_values("ead", ascending=False).head(top_n)
    return [
        {"borrower": r["Borrower"], "sector": r["Sector"], "ead": float(r["ead"]), "raroc": float(r["raroc"]),
         "gap": hurdle - float(r["raroc"])}
        for _, r in below.iterrows()
    ]


# ============================================================ dataset validation
# Supports the Data Hub upload flow: an uploaded workbook is validated in-memory
# first, staged to disk only when structurally sound, and swapped in via
# activate_dataset() when the user confirms.

REQUIRED_COLUMNS = [
    "Snapshot Date", "Quarter", "Customer ID", "Account ID", "Borrower", "Obligor Group",
    "Segment", "Sector", "Region", "Country", "Product Type", "Owner / Analyst",
    "Limit (USD mn)", "Exposure (USD mn)", "Undrawn (USD mn)", "CCF-Adjusted EAD (USD mn)",
    "Utilisation (%)", "Prev. Utilisation (%)", "Collateral (USD mn)", "Collateral Type",
    "Internal Grade (1-10)", "Risk Rating", "Prev. Risk Rating", "Rating Bucket", "Grade Band",
    "IFRS 9 Stage", "DPD (days)", "PD 12-Month (%)", "PD Lifetime (%)", "LGD (%)",
    "Model ECL (USD mn)", "Macro Overlay (USD mn)", "Total ECL (USD mn)", "RAROC (%)",
    "AI Risk Score", "Severity", "Trigger", "Reason Code", "Recommended Action", "Trend",
    "SICR Trigger", "DSCR (x)", "Covenant Headroom (%)", "Downgrade Prob. (%)",
    "News Sentiment", "Rollover Count", "Watchlist", "NPL", "Appetite Breach",
]
REQUIRED_SUPP_COLUMNS = [
    "Customer ID", "Borrower", "Net Leverage FY24 (x)", "Net Leverage FY25 (x)",
    "Interest Coverage FY24 (x)", "Interest Coverage FY25 (x)", "Current Ratio FY24 (x)",
    "Current Ratio FY25 (x)", "External Rating", "External Rating As Of",
    "Rating Notch Gap", "Last Collateral Valuation Date",
]

# Structural guard: a legitimate portfolio workbook has ~10-12 quarterly sheets +
# a supplementary sheet + a field dictionary. Anything far beyond that is rejected
# before a full parse.
MAX_WORKBOOK_SHEETS = 24


def validate_workbook_bytes(content: bytes) -> dict:
    """Structural validation of an uploaded workbook. Returns a check-by-check
    report; `ok` is True only if no check failed (warnings are allowed)."""
    checks = []

    def check(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    report = {"ok": False, "checks": checks, "quarters": [], "rows_total": 0}

    try:
        xl = pd.ExcelFile(io.BytesIO(content))
    except Exception as e:
        check("Workbook readable", "fail", f"Not a readable Excel workbook: {e}")
        return report
    check("Workbook readable", "pass", f"{len(xl.sheet_names)} sheets found.")

    if len(xl.sheet_names) > MAX_WORKBOOK_SHEETS:
        check("Sheet count", "fail",
              f"{len(xl.sheet_names)} sheets exceeds the {MAX_WORKBOOK_SHEETS}-sheet limit — "
              f"this doesn't look like a portfolio workbook.")
        return report

    quarters = detect_quarter_sheets(xl.sheet_names)
    report["quarters"] = quarters
    if not quarters:
        check("Quarterly sheets", "fail", "No sheets named like 'Q1 2026' found.")
        return report
    check("Quarterly sheets", "pass" if len(quarters) > 1 else "warn",
          f"{len(quarters)} quarterly snapshot(s): {quarters[0]} → {quarters[-1]}"
          + ("" if len(quarters) > 1 else " — QoQ deltas need at least 2 quarters."))

    if SUPP_SHEET not in xl.sheet_names:
        check("Borrower Supplementary sheet", "fail", f"Sheet '{SUPP_SHEET}' is missing.")
        return report
    supp = pd.read_excel(xl, sheet_name=SUPP_SHEET)
    missing_supp = [c for c in REQUIRED_SUPP_COLUMNS if c not in supp.columns]
    if missing_supp:
        check("Borrower Supplementary sheet", "fail", f"Missing columns: {', '.join(missing_supp)}")
    else:
        check("Borrower Supplementary sheet", "pass", f"{len(supp)} borrower records.")

    missing_by_sheet, rows_total, dup_accounts, bad_quarter_col, missing_ead = {}, 0, [], [], 0
    for q in quarters:
        sub = pd.read_excel(xl, sheet_name=q)
        rows_total += len(sub)
        missing = [c for c in REQUIRED_COLUMNS if c not in sub.columns]
        if missing:
            missing_by_sheet[q] = missing
            continue
        if not (sub["Quarter"] == q).all():
            bad_quarter_col.append(q)
        dups = int(sub["Account ID"].duplicated().sum())
        if dups:
            dup_accounts.append(f"{q} ({dups})")
        missing_ead += int(sub[EAD_COL].isna().sum())
    report["rows_total"] = rows_total

    if missing_by_sheet:
        worst_q, worst_cols = next(iter(missing_by_sheet.items()))
        check("Required columns", "fail",
              f"{len(missing_by_sheet)} sheet(s) missing required columns — e.g. {worst_q}: "
              f"{', '.join(worst_cols[:6])}{'…' if len(worst_cols) > 6 else ''}")
    else:
        check("Required columns", "pass", f"All {len(REQUIRED_COLUMNS)} required columns present in every quarter.")

    if bad_quarter_col:
        check("Quarter column consistency", "fail",
              f"'Quarter' values don't match the sheet name in: {', '.join(bad_quarter_col)}")
    elif not missing_by_sheet:
        check("Quarter column consistency", "pass", "Quarter labels match sheet names.")

    if dup_accounts:
        check("Duplicate Account IDs", "warn", f"Duplicates within: {', '.join(dup_accounts)}")
    elif not missing_by_sheet:
        check("Duplicate Account IDs", "pass", "No duplicate facilities within any quarter.")

    if missing_ead:
        check("EAD completeness", "warn", f"{missing_ead} rows have a blank CCF-Adjusted EAD.")
    elif not missing_by_sheet:
        check("EAD completeness", "pass", f"EAD populated on all {rows_total:,} rows.")

    report["ok"] = not any(c["status"] == "fail" for c in checks)
    return report


def dataset_profile() -> dict:
    """Summary of the currently active dataset for the Data Hub page."""
    per_quarter = []
    for q in QUARTER_SHEETS:
        sub = DF[DF["Quarter"] == q]
        per_quarter.append({
            "quarter": q, "label": _quarter_label(q), "rows": len(sub),
            "ead": float(sub[EAD_COL].sum()), "ecl": float(sub["Total ECL (USD mn)"].sum()),
            "customers": int(sub["Customer ID"].nunique()),
        })
    key_cols = [EAD_COL, "PD 12-Month (%)", "LGD (%)", "Total ECL (USD mn)", "IFRS 9 Stage",
                "Severity", "DSCR (x)", "Covenant Headroom (%)", "Collateral (USD mn)", "Risk Rating"]
    coverage = [{"column": c, "pct": float(DF[c].notna().mean() * 100)} for c in key_cols if c in DF.columns]
    return {
        "source": ACTIVE_SOURCE, "path": ACTIVE_PATH.name if ACTIVE_PATH else "—",
        "loaded_at": ACTIVE_LOADED_AT, "rows_total": len(DF),
        "accounts": int(DF["Account ID"].nunique()), "customers": int(DF["Customer ID"].nunique()),
        "sectors": int(DF["Sector"].nunique()), "regions": int(DF["Region"].nunique()),
        "quarters": per_quarter, "coverage": coverage,
    }


# ============================================================== borrower list

def compute_borrower_list(quarter: str, search: str = "", sector: str = "All",
                           segment: str = "All", top_n: int = 60) -> dict:
    """Customer-level roll-up of the whole book for the Borrower List page:
    total EAD across facilities, worst severity/stage, lead-facility descriptors."""
    cur = filtered_quarter(quarter, segment=segment, sector=sector)
    if search and search.strip():
        s = search.strip()
        mask = (cur["Borrower"].str.contains(s, case=False, na=False, regex=False)
                | cur["Customer ID"].astype(str).str.contains(s, case=False, na=False, regex=False))
        cur = cur[mask]
    if cur.empty:
        return {"rows": [], "total": 0, "total_ead": 0.0}

    cur = cur.copy()
    cur["_sev"] = cur["Severity"].map(SEVERITY_RANK)
    cur = cur.sort_values(EAD_COL, ascending=False)
    rows = []
    for cid, g in cur.groupby("Customer ID", sort=False, observed=True):
        lead = g.iloc[0]  # largest facility - descriptive fields
        rows.append({
            "customer_id": cid, "account_id": lead["Account ID"], "borrower": lead["Borrower"],
            "sector": lead["Sector"], "region": lead["Region"], "segment": lead["Segment"],
            "ead": float(g[EAD_COL].sum()), "rating": lead["Risk Rating"],
            "stage": int(g["IFRS 9 Stage"].max()),
            "severity": g.loc[g["_sev"].idxmin(), "Severity"],
            "trend": lead["Trend"], "accounts": len(g),
            "watchlist": "Yes" if (g["Watchlist"] == "Yes").any() else "No",
        })
    rows.sort(key=lambda r: -r["ead"])
    return {"rows": rows[:top_n], "total": len(rows), "total_ead": sum(r["ead"] for r in rows)}


# ==================================================== CBUAE BRF regulatory returns
# The ledger holds no capital data, so capital-linked figures use transparent,
# documented proxies: credit RWA via the same PD-driven risk-weight curve as
# compute_profitability, and a capital base of 17% of that CRWA (total capital
# ratio). AED figures use the USD peg. Classification follows the CBUAE
# five-bucket loan classification, mapped from IFRS 9 stage + DPD.

AED_PER_USD = 3.6725
CAPITAL_RATIO = 0.17
GENERAL_PROVISION_MIN_PCT = 1.5   # CBUAE Circular 28/2010: general provisions >= 1.5% of CRWA
LARGE_EXPOSURE_REPORT_PCT = 10.0  # reportable large exposure: >= 10% of capital base
LARGE_EXPOSURE_LIMIT_PCT = 25.0   # single-borrower / group cap: 25% of capital base

CBUAE_CLASS_ORDER = ["Normal", "OLEM", "Substandard", "Doubtful", "Loss"]

CBUAE_ACTIVITY_MAP = {
    "Energy": "Mining & Quarrying (incl. Oil & Gas)",
    "Manufacturing": "Manufacturing",
    "Contracting": "Construction",
    "Real Estate": "Real Estate",
    "Trade": "Wholesale & Retail Trade",
    "Transport": "Transport, Storage & Communication",
    "Hospitality": "Services (Hotels & Restaurants)",
    "SME Lending": "Small & Medium Enterprises",
    "Retail Mortgage": "Personal — Housing (Mortgage)",
    "Personal Finance": "Personal — Consumption",
    "Credit Cards": "Personal — Consumption",
    "Auto Finance": "Personal — Consumption",
}


def fmt_aed_mn(usd_mn: float) -> str:
    if usd_mn is None:
        return "—"
    return f"AED {usd_mn * AED_PER_USD:,.0f}m"


def fmt_aed_bn(usd_mn: float, decimals: int = 1) -> str:
    if usd_mn is None:
        return "—"
    return f"AED {usd_mn * AED_PER_USD / 1000:,.{decimals}f}bn"


def _cbuae_class_series(cur: pd.DataFrame) -> pd.Series:
    return pd.Series(
        np.where(cur["IFRS 9 Stage"] == 3,
                 np.where(cur["DPD (days)"] > 365, "Loss",
                          np.where(cur["DPD (days)"] > 180, "Doubtful", "Substandard")),
                 np.where(cur["IFRS 9 Stage"] == 2, "OLEM", "Normal")),
        index=cur.index,
    )


def _crwa_proxy(cur: pd.DataFrame) -> float:
    rw = (0.3 + cur["PD 12-Month (%)"] / 100 * 10).clip(0.2, 1.5)
    return float((cur[EAD_COL] * rw).sum())


def compute_brf_asset_quality(quarter: str) -> dict:
    """CBUAE classification of credit facilities & provisions (BRF asset-quality
    return): five-bucket classification, specific vs general provisions, and the
    1.5%-of-CRWA general provision floor check."""
    cur = filtered_quarter(quarter).copy()
    cur["CBUAE Class"] = _cbuae_class_series(cur)
    total_ead = float(cur[EAD_COL].sum())

    rows = []
    for cls in CBUAE_CLASS_ORDER:
        sub = cur[cur["CBUAE Class"] == cls]
        ead = float(sub[EAD_COL].sum())
        ecl = float(sub["Total ECL (USD mn)"].sum())
        rows.append({
            "class": cls, "accounts": len(sub), "ead": ead,
            "pct_of_book": (ead / total_ead * 100) if total_ead else 0.0,
            "provision": ecl, "coverage": (ecl / ead * 100) if ead else 0.0,
        })

    specific = float(cur.loc[cur["IFRS 9 Stage"] == 3, "Total ECL (USD mn)"].sum())
    general = float(cur.loc[cur["IFRS 9 Stage"].isin([1, 2]), "Total ECL (USD mn)"].sum())
    crwa = _crwa_proxy(cur)
    min_general = GENERAL_PROVISION_MIN_PCT / 100 * crwa
    classified_ead = sum(r["ead"] for r in rows if r["class"] in ("Substandard", "Doubtful", "Loss"))
    npl_ead = float(cur.loc[cur["NPL"] == "Yes", EAD_COL].sum())

    return {
        "rows": rows, "total_ead": total_ead, "classified_ead": classified_ead,
        "classified_pct": (classified_ead / total_ead * 100) if total_ead else 0.0,
        "npl_ead": npl_ead, "npl_pct": (npl_ead / total_ead * 100) if total_ead else 0.0,
        "specific_provisions": specific, "general_provisions": general,
        "crwa": crwa, "min_general": min_general,
        "general_ok": general >= min_general,
        "provision_coverage_npl": (specific / npl_ead * 100) if npl_ead else 0.0,
    }


def compute_brf_economic_activity(quarter: str) -> dict:
    """Credit distribution by CBUAE economic-activity category (BRF loans-by-
    economic-activity return): on/off-balance exposure, EAD, NPL and provisions."""
    cur = filtered_quarter(quarter).copy()
    cur["Activity"] = cur["Sector"].map(CBUAE_ACTIVITY_MAP).fillna("All Others")
    total_ead = float(cur[EAD_COL].sum())

    rows = []
    for act, sub in cur.groupby("Activity"):
        ead = float(sub[EAD_COL].sum())
        rows.append({
            "activity": act, "accounts": len(sub),
            "funded": float(sub["Exposure (USD mn)"].sum()),
            "unfunded": float(sub["Undrawn (USD mn)"].sum()),
            "ead": ead, "pct_of_book": (ead / total_ead * 100) if total_ead else 0.0,
            "npl_ead": float(sub.loc[sub["NPL"] == "Yes", EAD_COL].sum()),
            "provision": float(sub["Total ECL (USD mn)"].sum()),
        })
    rows.sort(key=lambda r: -r["ead"])
    for r in rows:
        r["npl_pct"] = (r["npl_ead"] / r["ead"] * 100) if r["ead"] else 0.0
    return {"rows": rows, "total_ead": total_ead}


def compute_brf_large_exposures(quarter: str) -> dict:
    """CBUAE large-exposure return: obligor groups (members aggregated) and
    stand-alone single names measured against the proxy capital base. Reportable
    at >= 10% of capital; the 25% single-obligor cap is flagged as a breach."""
    cur = filtered_quarter(quarter)
    capital_base = _crwa_proxy(cur) * CAPITAL_RATIO

    groups = cur[cur["Obligor Group"] != NO_GROUP_MARKER].groupby("Obligor Group")[EAD_COL].sum()
    singles = (cur[cur["Obligor Group"] == NO_GROUP_MARKER]
               .groupby(["Customer ID", "Borrower"])[EAD_COL].sum())

    entities = [{"name": g, "type": "Group", "ead": float(v)} for g, v in groups.items()]
    entities += [{"name": b, "type": "Single name", "ead": float(v)} for (_, b), v in singles.items()]

    for e in entities:
        e["pct_capital"] = (e["ead"] / capital_base * 100) if capital_base else 0.0
        e["breach"] = e["pct_capital"] > LARGE_EXPOSURE_LIMIT_PCT
    reportable = sorted([e for e in entities if e["pct_capital"] >= LARGE_EXPOSURE_REPORT_PCT],
                        key=lambda e: -e["pct_capital"])

    agg_large = sum(e["ead"] for e in reportable)
    return {
        "capital_base": capital_base, "rows": reportable,
        "reportable_count": len(reportable),
        "breach_count": sum(1 for e in reportable if e["breach"]),
        "aggregate_large": agg_large,
        "aggregate_pct_capital": (agg_large / capital_base * 100) if capital_base else 0.0,
        "largest_pct": reportable[0]["pct_capital"] if reportable else 0.0,
    }


def compute_brf_overview(quarter: str) -> dict:
    aq = compute_brf_asset_quality(quarter)
    le = compute_brf_large_exposures(quarter)
    cur = filtered_quarter(quarter)
    return {
        "total_ead": aq["total_ead"], "npl_pct": aq["npl_pct"],
        "classified_pct": aq["classified_pct"],
        "total_provisions": aq["specific_provisions"] + aq["general_provisions"],
        "provision_coverage_npl": aq["provision_coverage_npl"],
        "general_ok": aq["general_ok"], "general": aq["general_provisions"],
        "min_general": aq["min_general"],
        "capital_base": le["capital_base"], "reportable_count": le["reportable_count"],
        "breach_count": le["breach_count"], "class_rows": aq["rows"],
        "accounts": len(cur), "customers": int(cur["Customer ID"].nunique()),
    }


# ========================================================== macroeconomic outlook
# Macro history and baseline forecasts come from the IMF World Economic Outlook
# workbook dropped into the project folder, compacted to Macro_GCC_Compact.xlsx
# (GCC countries x 4 indicators x 2018-2030) by compact_imf_weo(). The IMF path
# is the Baseline; Upside/Downside apply documented adjustments around it.
# Everything the scenarios are applied TO (EADs, PDs, stage ratios, ECL) is the
# real portfolio data, and the downside anchor reuses the Scenario Lab stress engine.

MACRO_SCENARIOS = ["Baseline", "Upside", "Downside"]
SCENARIO_WEIGHTS = {"Baseline": 0.55, "Upside": 0.15, "Downside": 0.30}

MACRO_COMPACT_PATH = Path(__file__).resolve().parent.parent / "Macro_GCC_Compact.xlsx"

IMF_COUNTRY_TO_REGION = {
    "United Arab Emirates": "UAE", "Saudi Arabia": "Saudi Arabia", "Qatar": "Qatar",
    "Kuwait": "Kuwait", "Oman": "Oman", "Bahrain, Kingdom of": "Bahrain",
}
# Indicator fingerprints: every phrase group must match the (verbose) IMF WEO
# indicator description; a group is a tuple of acceptable alternatives.
MACRO_INDICATORS = {
    "gdp": {"label": "Real GDP Growth (% y/y)",
            "must": [("gross domestic product",), ("constant prices",), ("fraction of 100",)],
            "exclude": ["per capita", "purchasing power"]},
    "cpi": {"label": "CPI Inflation (avg, % y/y)",
            "must": [("consumer price",), ("fraction of 100",),
                     ("relative to the average value over the entire period",)],
            "exclude": []},
    "ca": {"label": "Current Account (% of GDP)",
           "must": [("current account",), ("fraction of 100", "percent of the gross domestic product")],
           "exclude": []},
    "debt": {"label": "Gov. Gross Debt (% of GDP)",
             "must": [("gross debt",), ("fraction of 100", "percent of the gross domestic product")],
             "exclude": ["net debt"]},
}
MACRO_YEARS = list(range(2018, 2031))
MACRO_FC_START = 2026  # WEO projections begin here; earlier years are actuals/estimates

# Scenario adjustments (pp) applied on top of the IMF baseline forecast, phased in
# 50% in the first projection year and 100% thereafter. Judgement-based, documented.
MACRO_SCENARIO_ADJ = {
    "gdp": {"Baseline": 0.0, "Upside": 1.2, "Downside": -3.0},
    "cpi": {"Baseline": 0.0, "Upside": 0.3, "Downside": 1.2},
    "ca": {"Baseline": 0.0, "Upside": 3.0, "Downside": -5.0},
    "debt": {"Baseline": 0.0, "Upside": -2.0, "Downside": 6.0},
}


def compact_imf_weo(raw_path) -> Path:
    """Distil a raw IMF WEO country-data export (8k+ rows, 200+ countries,
    2000-2031) down to the GCC x 4 core indicators x 2018-2030 block the Macro
    page needs, written to Macro_GCC_Compact.xlsx. Re-run when a fresh WEO
    export is dropped into the folder."""
    df = pd.read_excel(raw_path)
    desc = df["INDICATOR.Description"].astype(str).str.lower()
    rows = []
    for imf_name, region in IMF_COUNTRY_TO_REGION.items():
        country_mask = df["COUNTRY"] == imf_name
        for key, spec in MACRO_INDICATORS.items():
            mask = country_mask.copy()
            for group in spec["must"]:
                mask &= desc.apply(lambda d, g=group: any(alt in d for alt in g))
            for bad in spec["exclude"]:
                mask &= ~desc.str.contains(bad, regex=False)
            match = df[mask]
            if match.empty:
                continue
            r = match.iloc[0]
            rows.append({"Region": region, "Indicator": key, "Label": spec["label"],
                         **{y: (float(r[y]) if pd.notna(r[y]) else None) for y in MACRO_YEARS}})
    out = pd.DataFrame(rows)
    out.to_excel(MACRO_COMPACT_PATH, sheet_name="Macro GCC", index=False)
    return MACRO_COMPACT_PATH


def _load_macro_gcc() -> dict | None:
    """{region: {indicator: {"label", "years", "values"}}} plus a 'All' entry
    holding the simple GCC average per year. None if no compact file exists."""
    if not MACRO_COMPACT_PATH.exists():
        return None
    df = pd.read_excel(MACRO_COMPACT_PATH)
    year_cols = [c for c in df.columns if str(c).isdigit()]
    data = {}
    for _, r in df.iterrows():
        series = {"label": r["Label"], "years": [int(y) for y in year_cols],
                  "values": [(float(r[y]) if pd.notna(r[y]) else None) for y in year_cols]}
        data.setdefault(r["Region"], {})[r["Indicator"]] = series
    if data:
        regions = list(data.keys())
        avg = {}
        for key, spec in MACRO_INDICATORS.items():
            all_series = [data[reg][key]["values"] for reg in regions if key in data[reg]]
            years = next((data[reg][key]["years"] for reg in regions if key in data[reg]), [])
            vals = []
            for i in range(len(years)):
                pts = [s[i] for s in all_series if s[i] is not None]
                vals.append(sum(pts) / len(pts) if pts else None)
            avg[key] = {"label": spec["label"], "years": years, "values": vals}
        data["All"] = avg
    return data


MACRO_GCC = _load_macro_gcc()


def macro_region_options() -> list:
    regions = [r for r in (MACRO_GCC or {}) if r != "All"]
    return ([{"label": "GCC (All Regions)", "value": "All"}]
            + [{"label": r, "value": r} for r in sorted(regions)])

# Relative PD drift over the 4-quarter horizon applied to real current PDs.
SCENARIO_PD_DRIFT = {"Baseline": 0.06, "Upside": -0.08, "Downside": 0.32}

# Sector sensitivity to the combined macro path (rates + oil + CRE), applied as a
# multiplier on the scenario PD drift. Judgement-based, documented, illustrative.
SECTOR_MACRO_BETA = {
    "Real Estate": 1.60, "Contracting": 1.45, "Hospitality": 1.25, "Trade": 1.10,
    "Transport": 1.05, "Manufacturing": 1.00, "SME Lending": 1.30, "Energy": 0.70,
    "Retail Mortgage": 0.90, "Auto Finance": 1.05, "Personal Finance": 1.15, "Credit Cards": 1.20,
}
DEFAULT_SECTOR_BETA = 1.0


def _next_quarter_labels(n: int) -> list:
    """Forecast quarter labels following the last snapshot, e.g. Q2 2026, Q3 2026…"""
    m = _QUARTER_SHEET_RE.match(QUARTER_SHEETS[-1])
    qn, yr = int(m.group(1)), int(m.group(2))
    out = []
    for _ in range(n):
        qn += 1
        if qn > 4:
            qn, yr = 1, yr + 1
        out.append(f"Q{qn} {yr}")
    return out


def compute_macro_outlook(scenario: str = "Baseline", region: str = "All",
                          weights: dict | None = None) -> dict | None:
    """IMF WEO history + baseline forecast for one GCC country (or the GCC
    average), with Upside/Downside adjustments phased in over the projection
    years. Also returns a probability-weighted blended path per variable using
    `weights` (defaults to SCENARIO_WEIGHTS), so a user-set weight mix is
    visible directly on the outlook charts. Returns None when no compact IMF
    file has been generated."""
    if not MACRO_GCC or region not in MACRO_GCC:
        return None
    weights = weights or dict(SCENARIO_WEIGHTS)
    variables = []
    for key, series in MACRO_GCC[region].items():
        years, values = series["years"], series["values"]
        hist = [(y, v) for y, v in zip(years, values, strict=True) if y < MACRO_FC_START and v is not None]
        fc = [(y, v) for y, v in zip(years, values, strict=True) if y >= MACRO_FC_START and v is not None]
        if not hist or not fc:
            continue
        all_fc = {}
        for s in MACRO_SCENARIOS:
            adj = MACRO_SCENARIO_ADJ[key][s]
            all_fc[s] = [v + adj * (0.5 if i == 0 else 1.0) for i, (_, v) in enumerate(fc)]
        weighted = [sum(weights[s] * all_fc[s][i] for s in MACRO_SCENARIOS) for i in range(len(fc))]
        variables.append({
            "key": key, "label": series["label"],
            "hist_labels": [str(y) for y, _ in hist], "hist": [v for _, v in hist],
            "fc_labels": [str(y) for y, _ in fc], "fc": all_fc[scenario],
            "latest": hist[-1][1], "horizon": all_fc[scenario][-1],
            "delta": all_fc[scenario][-1] - hist[-1][1],
            "all_fc": all_fc, "weighted": weighted,
            "weighted_horizon": weighted[-1], "weighted_delta": weighted[-1] - hist[-1][1],
        })
    if not variables:
        return None
    return {"scenario": scenario, "region": region, "weights": weights,
            "variables": variables, "fc_start": MACRO_FC_START}


def compute_sector_outlook(quarter: str, scenario: str = "Baseline", region: str = "All",
                           weights: dict | None = None) -> dict:
    """Forward sector risk: real current EAD/PD/Stage-2 share per sector (optionally
    one region's slice of the book), with a 4-quarter projected PD under the
    selected scenario (drift x sector beta), plus a probability-weighted blended
    PD projection using `weights` (defaults to SCENARIO_WEIGHTS)."""
    weights = weights or dict(SCENARIO_WEIGHTS)
    rows = []
    for s in compute_sector_kpis(quarter, region=region):
        beta = SECTOR_MACRO_BETA.get(s["sector"], DEFAULT_SECTOR_BETA)
        pd_proj_by_scenario = {sc: s["pd"] * (1 + SCENARIO_PD_DRIFT[sc] * beta) for sc in MACRO_SCENARIOS}
        pd_proj = pd_proj_by_scenario[scenario]
        delta_pct = (pd_proj / s["pd"] - 1) * 100 if s["pd"] else 0.0
        weighted_pd_proj = sum(weights[sc] * pd_proj_by_scenario[sc] for sc in MACRO_SCENARIOS)
        weighted_delta_pct = (weighted_pd_proj / s["pd"] - 1) * 100 if s["pd"] else 0.0
        if delta_pct >= 15:
            outlook = "Deteriorating"
        elif delta_pct <= -5:
            outlook = "Improving"
        else:
            outlook = "Stable"
        rows.append({**s, "beta": beta, "pd_proj": pd_proj, "delta_pct": delta_pct,
                     "outlook": outlook, "weighted_pd_proj": weighted_pd_proj,
                     "weighted_delta_pct": weighted_delta_pct})
    rows.sort(key=lambda r: -r["delta_pct"])
    return {"scenario": scenario, "region": region, "weights": weights, "rows": rows}


def normalize_weights(base=None, up=None, down=None) -> dict:
    """User-entered scenario weights (any non-negative numbers) normalized to sum
    to 1. Falls back to the default weights when everything is blank/zero."""
    raw = {"Baseline": max(0.0, float(base or 0)), "Upside": max(0.0, float(up or 0)),
           "Downside": max(0.0, float(down or 0))}
    total = sum(raw.values())
    if total <= 0:
        return dict(SCENARIO_WEIGHTS)
    return {k: v / total for k, v in raw.items()}


def health_index(npl: float, stage2: float) -> float:
    """0-100 composite portfolio-health score from the two ratios that move it:
    each 1pp of NPL costs 5 points, each 1pp of Stage 2 costs 1.5 points.

    Deliberately simple and monotone, so a reader can reconstruct the score from
    the two inputs without the model. Shared by the Portfolio Health projection
    and the cockpit Health Index screen so the two can never disagree."""
    return max(0.0, min(100.0, 100.0 - npl * 5.0 - stage2 * 1.5))


def compute_portfolio_health(quarter: str, region: str = "All", weights: dict | None = None) -> dict:
    """Trailing 4 quarters of real NPL / Stage-2 / ECL-coverage ratios plus a
    4-quarter projection per scenario, optionally for one region's slice of the
    book. The downside endpoint applies the whole-book stress-engine uplift
    (+300bps / -20% CRE) to the slice's current ratios. `weights` (normalized)
    drive the probability-weighted path and outlook."""
    weights = weights or dict(SCENARIO_WEIGHTS)
    idx = QUARTER_SHEETS.index(quarter)
    hist = []
    for q in QUARTER_SHEETS[max(0, idx - 3): idx + 1]:
        sub = filtered_quarter(q, region=region)
        ead = float(sub[EAD_COL].sum())
        hist.append({
            "label": q,
            "npl": float(sub.loc[sub["NPL"] == "Yes", EAD_COL].sum()) / ead * 100 if ead else 0.0,
            "stage2": float(sub.loc[sub["IFRS 9 Stage"] == 2, EAD_COL].sum()) / ead * 100 if ead else 0.0,
            "coverage": float(sub["Total ECL (USD mn)"].sum()) / ead * 100 if ead else 0.0,
        })
    cur = hist[-1]
    stressed = compute_stress_scenario(quarter, rate_shock_bps=300, cre_price_shock_pct=20)
    ecl_uplift = stressed["stressed_ecl"] / stressed["base_ecl"] if stressed["base_ecl"] else 1.0
    # relative uplift so a region slice stresses proportionally to its own base
    npl_uplift = (stressed["stressed_npl_pct"] / stressed["base_npl_pct"]
                  if stressed["base_npl_pct"] else 1.0)

    endpoints = {
        "Downside": {"npl": cur["npl"] * npl_uplift, "stage2": cur["stage2"] * 1.45,
                     "coverage": cur["coverage"] * ecl_uplift},
        "Baseline": {"npl": cur["npl"] * 1.05, "stage2": cur["stage2"] * 1.03,
                     "coverage": cur["coverage"] * 1.04},
        "Upside": {"npl": cur["npl"] * 0.82, "stage2": cur["stage2"] * 0.85,
                   "coverage": cur["coverage"] * 0.95},
    }
    fc_labels = _next_quarter_labels(4)
    projections = {}
    for scen, end in endpoints.items():
        path = []
        for i in range(1, 5):
            f = i / 4
            path.append({
                "label": fc_labels[i - 1],
                "npl": cur["npl"] + (end["npl"] - cur["npl"]) * f,
                "stage2": cur["stage2"] + (end["stage2"] - cur["stage2"]) * f,
                "coverage": cur["coverage"] + (end["coverage"] - cur["coverage"]) * f,
            })
        projections[scen] = path

    weighted_path = [{
        "label": fc_labels[i],
        **{m: sum(weights[s] * projections[s][i][m] for s in MACRO_SCENARIOS)
           for m in ("npl", "stage2", "coverage")},
    } for i in range(4)]

    hi_now = health_index(cur["npl"], cur["stage2"])
    hi_paths = {scen: [health_index(p["npl"], p["stage2"]) for p in path]
                for scen, path in projections.items()}
    weighted_hi = sum(weights[s] * hi_paths[s][-1] for s in MACRO_SCENARIOS)

    return {
        "hist": hist, "projections": projections, "fc_labels": fc_labels,
        "current": cur, "health_now": hi_now, "health_paths": hi_paths,
        "health_weighted": weighted_hi, "weights": weights, "region": region,
        "weighted_path": weighted_path,
        "stressed_npl": cur["npl"] * npl_uplift,
    }
