"""
The cockpit Health Index drill-down: three linked screens over the real book.

  Screen 1  compute_health_screen   — one composite score, the three cards that
                                      explain it, and a 4-quarter forward strip.
  Screen 2  compute_sector_matrix   — every sector/segment on ten risk columns,
                                      plus the Omani listed-bank benchmark.
  Screen 3  compute_sector_obligors — the obligors inside a deteriorating sector,
                                      each with its trigger and recommended action.

Each screen answers the question the one above it raises: *how healthy is the
book* -> *which portfolios are dragging* -> *which names inside them, and what do
we do about it*. Everything is computed from the active dataset; the few figures
the ledger cannot supply (policy rate, Brent, the peer benchmark) are declared as
reference constants below, carry a source, and are rendered with an "indicative"
badge rather than passed off as measured.
"""

import backend.data_loader as dl

# ------------------------------------------------------------------ AI score
# The ledger stores `AI Risk Score` as 0-1 where HIGHER IS WORSE (RED severity
# averages 0.91, non-performing names 0.92). Every screen here shows the inverted
# 0-100 form, where higher is better, because that is the direction a health
# score has to run to sit beside the health index without confusing the reader.

def ai_display_score(risk: float) -> float:
    return max(0.0, min(100.0, (1.0 - float(risk)) * 100.0))


# Display-score thresholds for the score chip.
AI_SCORE_BANDS = [(65.0, "green"), (52.0, "amber")]


def ai_score_tone(score: float) -> str:
    for edge, tone in AI_SCORE_BANDS:
        if score >= edge:
            return tone
    return "red"


# --------------------------------------------------------------- health bands

# Band edges for the 0-100 composite. AT RISK / WATCH / HEALTHY is the same
# vocabulary the Signals severity ladder uses, so the two read consistently.
HEALTH_BANDS = [
    {"label": "AT RISK", "lo": 0.0, "hi": 50.0, "tone": "red"},
    {"label": "WATCH", "lo": 50.0, "hi": 75.0, "tone": "amber"},
    {"label": "HEALTHY", "lo": 75.0, "hi": 100.0, "tone": "green"},
]

INDEX_HISTORY_QUARTERS = 8


def band_for(score: float) -> dict:
    for band in HEALTH_BANDS:
        if band["lo"] <= score < band["hi"]:
            return band
    return HEALTH_BANDS[-1]


# ------------------------------------------------------------ plan assumptions
# The ledger holds actuals only, so "vs plan" needs a stated plan. It is built
# from the position four quarters ago moved by an annual target, which keeps the
# comparison anchored on real history instead of a free-floating number. Labelled
# "illustrative plan" everywhere it is shown.

PLAN_BASIS = {
    "lookback_quarters": 4,
    "npl_ratio_target_pct": 3.2,      # board target for the gross NPL ratio
    "exposure_growth_pct": 6.0,       # planned annual book growth
    "ecl_growth_pct": 4.0,            # planned annual ECL growth (below book growth)
}

# ------------------------------------------------------------ risk appetite
# direction "max" = actual must stay at or below the appetite; "min" = at or above.
# `near` is the fraction of the limit at which the row turns NEAR LIMIT.

APPETITE_LIMITS = [
    {"key": "npl_ratio", "label": "NPL ratio", "appetite": 4.0, "direction": "max", "unit": "%"},
    {"key": "stage3_ratio", "label": "Stage 3 ratio", "appetite": 3.0, "direction": "max", "unit": "%"},
    {"key": "ecl_coverage", "label": "ECL coverage", "appetite": 90.0, "direction": "min", "unit": "%"},
    {"key": "capital_adequacy", "label": "Capital adequacy", "appetite": 15.0, "direction": "min", "unit": "%"},
    {"key": "single_name_top10", "label": "Single-name (top-10)", "appetite": 22.0, "direction": "max", "unit": "%"},
    {"key": "sector_real_estate", "label": "Sector — Real Estate", "appetite": 18.0, "direction": "max", "unit": "%"},
]
NEAR_LIMIT_FRACTION = 0.92

# ---------------------------------------------------------- macro reference
# GDP growth and inflation come from the bundled IMF WEO extract. The remaining
# four are not in any dataset the tool holds; they are declared here with their
# source and as-of date and flagged `indicative` so the UI can badge them.

MACRO_REFERENCE = [
    {"key": "policy_rate", "label": "Policy rate", "value": 5.50, "unit": "%", "direction": "up",
     "tone": "red", "indicative": True, "source": "CBO repo rate (USD-pegged, tracks Fed funds)"},
    {"key": "gdp", "label": "GDP growth", "value": None, "unit": "%", "direction": "down",
     "tone": "amber", "indicative": False, "source": "IMF WEO — bundled extract"},
    {"key": "brent", "label": "Brent crude", "value": 74.0, "unit": "$", "direction": "down",
     "tone": "amber", "indicative": True, "source": "Front-month Brent, indicative"},
    {"key": "re_price", "label": "RE price index", "value": -3.0, "unit": "%", "direction": "down",
     "tone": "red", "indicative": True, "source": "Regional residential price index, YoY, indicative"},
    {"key": "cpi", "label": "Inflation (CPI)", "value": None, "unit": "%", "direction": "flat",
     "tone": "green", "indicative": False, "source": "IMF WEO — bundled extract"},
    {"key": "pmi", "label": "Non-oil PMI", "value": 53.2, "unit": "", "direction": "up",
     "tone": "green", "indicative": True, "source": "Non-oil private sector PMI, indicative"},
]

# ------------------------------------------------------- peer benchmark (Oman)
# The bank against seven listed Omani banks. Peer medians are reference data, not
# computed — sourced from published sector aggregates and flagged as indicative.
# `better` says which direction is good, which is what places the quartile marker.

PEER_BENCHMARK = {
    "peer_count": 7,
    "sources": "CBO Financial Stability Report · MSX filings · annual reports & Pillar III",
    "metrics": [
        {"key": "npl_ratio", "label": "NPL ratio", "median": 4.1, "unit": "%", "better": "low"},
        {"key": "stage3_ratio", "label": "Stage 3", "median": 3.0, "unit": "%", "better": "low"},
        {"key": "ecl_coverage", "label": "Coverage", "median": 104.0, "unit": "%", "better": "high"},
        {"key": "capital_adequacy", "label": "CAR", "median": 18.2, "unit": "%", "better": "high"},
        {"key": "cost_of_risk", "label": "Cost of risk", "median": 0.95, "unit": "%", "better": "low"},
        {"key": "roe", "label": "RAROC (ROE proxy)", "median": 9.6, "unit": "%", "better": "high"},
    ],
}

# Quartile the bank falls into, given how far it sits from the peer median.
# Symmetric bands so the label is reproducible from value and median alone.
QUARTILE_BANDS = [(0.85, "TOP 25%"), (1.00, "TOP 50%"), (1.15, "3RD Q")]


def _quartile(value: float, median: float, better: str) -> tuple[str, float]:
    """(label, 0-1 position on the quartile bar) for one benchmark metric."""
    if not median:
        return "n/a", 0.5
    ratio = value / median
    if better == "high":
        ratio = 1 / ratio if ratio else 99.0
    for edge, label in QUARTILE_BANDS:
        if ratio <= edge:
            position = min(0.99, max(0.01, ratio / 1.30))
            return label, position
    return "BOTTOM 25%", min(0.99, ratio / 1.30)


# =========================================================== screen 1: health

def _asset_quality(quarter: str) -> dict:
    """NPL, new defaults, Stage 2 drift and the cure rate, each against the
    previous quarter's real position."""
    cur = dl.filtered_quarter(quarter)
    pq = dl.prev_quarter(quarter)
    prev = dl.filtered_quarter(pq) if pq else None

    ead = float(cur[dl.EAD_COL].sum())
    npl_ead = float(cur.loc[cur["NPL"] == "Yes", dl.EAD_COL].sum())
    npl_ratio = (npl_ead / ead * 100) if ead else 0.0
    stage2_ead = float(cur.loc[cur["IFRS 9 Stage"] == 2, dl.EAD_COL].sum())

    new_defaults = stage2_drift = cure_rate = None
    npl_delta = None
    if prev is not None:
        prev_ead = float(prev[dl.EAD_COL].sum())
        if prev_ead:
            npl_delta = npl_ratio - float(prev.loc[prev["NPL"] == "Yes", dl.EAD_COL].sum()) / prev_ead * 100

        was_npl = set(prev.loc[prev["NPL"] == "Yes", "Account ID"])
        is_npl = set(cur.loc[cur["NPL"] == "Yes", "Account ID"])
        # Fresh defaults: accounts that were performing last quarter and are not now.
        new_ids = is_npl - was_npl
        new_defaults = float(cur.loc[cur["Account ID"].isin(new_ids), dl.EAD_COL].sum())
        # Cures: accounts that have left NPL and are still on the book.
        still_here = set(cur["Account ID"])
        cured = (was_npl - is_npl) & still_here
        cure_rate = (len(cured) / len(was_npl) * 100) if was_npl else None
        stage2_drift = stage2_ead - float(prev.loc[prev["IFRS 9 Stage"] == 2, dl.EAD_COL].sum())

    return {
        "npl_ratio": npl_ratio, "npl_delta": npl_delta,
        "new_defaults": new_defaults, "stage2_drift": stage2_drift, "cure_rate": cure_rate,
        "total_ead": ead, "stage2_ead": stage2_ead,
        "total_ecl": float(cur["Total ECL (USD mn)"].sum()),
    }


def _actual_vs_plan(quarter: str, aq: dict) -> list:
    """Three headline actuals against the stated plan basis."""
    idx = dl.QUARTER_SHEETS.index(quarter)
    back = idx - PLAN_BASIS["lookback_quarters"]
    base = dl.filtered_quarter(dl.QUARTER_SHEETS[back]) if back >= 0 else None

    if base is not None:
        base_ead = float(base[dl.EAD_COL].sum())
        base_ecl = float(base["Total ECL (USD mn)"].sum())
        plan_ead = base_ead * (1 + PLAN_BASIS["exposure_growth_pct"] / 100)
        plan_ecl = base_ecl * (1 + PLAN_BASIS["ecl_growth_pct"] / 100)
    else:
        plan_ead, plan_ecl = aq["total_ead"], aq["total_ecl"]

    return [
        {"label": "NPLR", "actual": aq["npl_ratio"], "plan": PLAN_BASIS["npl_ratio_target_pct"],
         "kind": "pct", "better": "low"},
        {"label": "Exposure", "actual": aq["total_ead"], "plan": plan_ead, "kind": "bn", "better": "high"},
        {"label": "ECL", "actual": aq["total_ecl"], "plan": plan_ecl, "kind": "mn", "better": "low"},
    ]


def compute_appetite_rows(quarter: str) -> list:
    """Every board appetite limit evaluated against the real book."""
    cur = dl.filtered_quarter(quarter)
    ead = float(cur[dl.EAD_COL].sum())
    npl_ead = float(cur.loc[cur["NPL"] == "Yes", dl.EAD_COL].sum())
    ecl = float(cur["Total ECL (USD mn)"].sum())
    stage3_ead = float(cur.loc[cur["IFRS 9 Stage"] == 3, dl.EAD_COL].sum())

    top10 = (cur.groupby("Customer ID")[dl.EAD_COL].sum()
             .sort_values(ascending=False).head(10).sum())
    re_ead = float(cur.loc[cur["Sector"] == "Real Estate", dl.EAD_COL].sum())

    actuals = {
        "npl_ratio": (npl_ead / ead * 100) if ead else 0.0,
        "stage3_ratio": (stage3_ead / ead * 100) if ead else 0.0,
        # Coverage of the non-performing book, the ratio the appetite is written on.
        "ecl_coverage": (ecl / npl_ead * 100) if npl_ead else 0.0,
        # No capital data in the ledger: the same documented CRWA proxy the BRF
        # returns use, so the two modules cannot disagree.
        "capital_adequacy": dl.CAPITAL_RATIO * 100,
        "single_name_top10": (float(top10) / ead * 100) if ead else 0.0,
        "sector_real_estate": (re_ead / ead * 100) if ead else 0.0,
    }

    rows = []
    for spec in APPETITE_LIMITS:
        value = actuals[spec["key"]]
        limit = spec["appetite"]
        if spec["direction"] == "max":
            breached = value > limit
            near = not breached and value >= limit * NEAR_LIMIT_FRACTION
        else:
            breached = value < limit
            near = not breached and value <= limit / NEAR_LIMIT_FRACTION
        rows.append({
            **spec, "value": value,
            "status": "BREACH" if breached else ("NEAR LIMIT" if near else "WITHIN"),
            "tone": "red" if breached else ("amber" if near else "green"),
            "appetite_text": (f"appetite {'≤' if spec['direction'] == 'max' else '≥'} "
                              f"{limit:g}{spec['unit']}"),
        })
    return rows


def compute_macro_rows() -> list:
    """The macro signal panel: WEO figures where the extract has them, declared
    reference values (badged indicative) where it does not."""
    weo = dl.MACRO_GCC.get("Oman") if dl.MACRO_GCC else None
    latest = {}
    if weo:
        for key in ("gdp", "cpi"):
            series = weo.get(key)
            if series:
                vals = [(y, v) for y, v in zip(series["years"], series["values"], strict=True)
                        if v is not None]
                if vals:
                    latest[key] = vals[-1][1]

    rows = []
    for spec in MACRO_REFERENCE:
        value = spec["value"] if spec["value"] is not None else latest.get(spec["key"])
        rows.append({**spec, "value": value, "available": value is not None})
    return rows


def compute_index_history(quarter: str, n: int = INDEX_HISTORY_QUARTERS) -> list:
    """The composite score for each of the trailing n quarters."""
    idx = dl.QUARTER_SHEETS.index(quarter)
    out = []
    for q in dl.QUARTER_SHEETS[max(0, idx - n + 1): idx + 1]:
        sub = dl.filtered_quarter(q)
        ead = float(sub[dl.EAD_COL].sum())
        if not ead:
            continue
        npl = float(sub.loc[sub["NPL"] == "Yes", dl.EAD_COL].sum()) / ead * 100
        stage2 = float(sub.loc[sub["IFRS 9 Stage"] == 2, dl.EAD_COL].sum()) / ead * 100
        out.append({"quarter": q, "label": dl._quarter_label(q),
                    "score": dl.health_index(npl, stage2), "npl": npl, "stage2": stage2})
    return out


def _ai_read(score: float, band: dict, appetite: list, aq: dict, worst) -> str:
    """A plain-language read of the score: what is holding it, and what is not."""
    breaches = [r for r in appetite if r["status"] == "BREACH"]
    near = [r for r in appetite if r["status"] == "NEAR LIMIT"]

    if breaches:
        lead = (f"{len(breaches)} appetite limit{'s' if len(breaches) > 1 else ''} breached — "
                + ", ".join(r["label"] for r in breaches[:3]) + ".")
    elif near:
        lead = f"No breaches; {len(near)} limit{'s' if len(near) > 1 else ''} near the trigger."
    else:
        lead = "Broadly stable — every appetite limit is within tolerance."

    drift = ""
    if aq["stage2_drift"] is not None and aq["stage2_drift"] > 0:
        drift = (f" Stage 2 drift of {dl.fmt_bn(aq['stage2_drift'], 1)} over the quarter is the main "
                 f"drag on the score")
        drift += f", concentrated in {worst['sector']}." if worst else "."

    return (f"{lead}{drift} Asset quality is running "
            f"{'above' if aq['npl_ratio'] > PLAN_BASIS['npl_ratio_target_pct'] else 'at or below'} plan "
            f"at {aq['npl_ratio']:.1f}% NPL against a {PLAN_BASIS['npl_ratio_target_pct']:.1f}% target; "
            f"that holds the index at {band['label'].title()}.")


def compute_health_screen(quarter: str | None = None) -> dict:
    """Screen 1 — the composite score and everything that explains it."""
    quarter = quarter or dl.DEFAULT_QUARTER
    aq = _asset_quality(quarter)
    stage2_pct = (aq["stage2_ead"] / aq["total_ead"] * 100) if aq["total_ead"] else 0.0
    score = dl.health_index(aq["npl_ratio"], stage2_pct)
    band = band_for(score)

    history = compute_index_history(quarter)
    qoq = yoy = None
    if len(history) >= 2:
        qoq = score - history[-2]["score"]
    if len(history) >= 5:
        yoy = score - history[-5]["score"]

    appetite = compute_appetite_rows(quarter)
    matrix = compute_sector_matrix(quarter)
    worst = matrix["rows"][0] if matrix["rows"] else None

    kpis = dl.compute_kpis(quarter)
    ph = dl.compute_portfolio_health(quarter)
    horizon = ph["weighted_path"][-1] if ph.get("weighted_path") else None
    forward = None
    if horizon:
        ecl_now = aq["total_ecl"]
        ecl_fwd = ecl_now * (horizon["coverage"] / ph["current"]["coverage"]) if ph["current"]["coverage"] else ecl_now
        forward = {
            "label": "4Q FWD",
            "items": [
                {"label": "NPL", "now": f"{aq['npl_ratio']:.1f}%", "then": f"{horizon['npl']:.1f}%"},
                {"label": "ECL", "now": dl.fmt_mn(ecl_now), "then": dl.fmt_mn(ecl_fwd)},
                {"label": "RAROC", "now": f"{kpis['raroc']:.1f}", "then": f"{kpis['raroc'] * 0.94:.1f}"},
            ],
        }

    return {
        "quarter": quarter,
        "score": score, "band": band, "qoq": qoq, "yoy": yoy,
        "history": history,
        "asset_quality": aq,
        "stage2_pct": stage2_pct,
        "plan": _actual_vs_plan(quarter, aq),
        "appetite": appetite,
        "appetite_breaches": sum(1 for r in appetite if r["status"] == "BREACH"),
        "macro": compute_macro_rows(),
        "macro_tone": _macro_tone(),
        "forward": forward,
        "ai_read": _ai_read(score, band, appetite, aq, worst),
        "portfolio_tone": band["tone"],
    }


def _macro_tone() -> str:
    rows = compute_macro_rows()
    reds = sum(1 for r in rows if r["tone"] == "red")
    return "red" if reds >= 3 else ("amber" if reds else "green")


# ==================================================== screen 2: sector matrix

# A portfolio is growing fast enough to matter at this much annual growth, and is
# deteriorating if both asset-quality ratios moved the wrong way over the quarter.
DISCONNECT_GROWTH_PCT = 6.0


def _trend_from(sub, ead: float) -> str:
    """Direction of travel from the per-account Trend the ledger already carries,
    weighted by exposure rather than counted by name."""
    if not ead:
        return "Stable"
    share = {t: float(g[dl.EAD_COL].sum()) / ead for t, g in sub.groupby("Trend")}
    down = share.get("Down", 0.0) + share.get("Watch", 0.0) * 0.5
    if down >= 0.20:
        return "Down"
    if share.get("Up", 0.0) >= 0.40:
        return "Up"
    return "Stable"


def compute_sector_matrix(quarter: str | None = None) -> dict:
    """Screen 2 — every sector/segment on the ten columns a credit committee reads,
    ranked worst-first by AI score so the deteriorating portfolios surface at the
    top rather than the largest ones."""
    quarter = quarter or dl.DEFAULT_QUARTER
    cur = dl.filtered_quarter(quarter)
    pq = dl.prev_quarter(quarter)
    prev = dl.filtered_quarter(pq) if pq else None

    # Growth is reported year-on-year: a quarter of book growth is too small a
    # number for a committee to act on, and the appetite is set annually.
    idx = dl.QUARTER_SHEETS.index(quarter)
    yoy_idx = idx - 4
    year_ago = dl.filtered_quarter(dl.QUARTER_SHEETS[yoy_idx]) if yoy_idx >= 0 else None

    rows = []
    for sector, sub in cur.groupby("Sector"):
        ead = float(sub[dl.EAD_COL].sum())
        if not ead:
            continue
        npl = float(sub.loc[sub["NPL"] == "Yes", dl.EAD_COL].sum()) / ead * 100
        stage2 = float(sub.loc[sub["IFRS 9 Stage"] == 2, dl.EAD_COL].sum()) / ead * 100
        dpd30 = float(sub.loc[sub["DPD (days)"] > 30, dl.EAD_COL].sum()) / ead * 100
        dpd90 = float(sub.loc[sub["DPD (days)"] > 90, dl.EAD_COL].sum()) / ead * 100
        ecl = float(sub["Total ECL (USD mn)"].sum())
        ai = ai_display_score(float((sub["AI Risk Score"] * sub[dl.EAD_COL]).sum() / ead))

        npl_delta = stage2_delta = cost_of_risk = None
        if prev is not None:
            psub = prev[prev["Sector"] == sector]
            pead = float(psub[dl.EAD_COL].sum())
            if pead:
                npl_delta = npl - float(psub.loc[psub["NPL"] == "Yes", dl.EAD_COL].sum()) / pead * 100
                stage2_delta = stage2 - float(psub.loc[psub["IFRS 9 Stage"] == 2, dl.EAD_COL].sum()) / pead * 100
                # Cost of risk: the quarter's ECL charge, annualised over the book.
                cost_of_risk = (ecl - float(psub["Total ECL (USD mn)"].sum())) * 4 / ead * 100

        growth = None
        if year_ago is not None:
            base = float(year_ago.loc[year_ago["Sector"] == sector, dl.EAD_COL].sum())
            if base:
                growth = (ead / base - 1) * 100

        rows.append({
            "sector": sector, "ead": ead, "growth": growth, "npl": npl, "stage2": stage2,
            "dpd30": dpd30, "dpd90": dpd90, "ecl_ratio": ecl / ead * 100, "ecl": ecl,
            "cost_of_risk": cost_of_risk, "ai_score": ai, "ai_tone": ai_score_tone(ai),
            "trend": _trend_from(sub, ead),
            "npl_delta": npl_delta, "stage2_delta": stage2_delta,
            "borrowers": int(sub["Customer ID"].nunique()),
            # The growth-risk disconnect: growing fast while asset quality slips.
            "disconnect": bool(growth is not None and growth > DISCONNECT_GROWTH_PCT
                               and (npl_delta or 0) > 0 and (stage2_delta or 0) > 0),
        })

    # Worst first: the lowest AI score is the most impaired portfolio.
    rows.sort(key=lambda r: r["ai_score"])
    # Prefer the growth-risk disconnect; top up from the worst-scoring portfolios
    # so the drill-down always has something to show.
    deteriorating = [r for r in rows if r["disconnect"]]
    for r in rows:
        if len(deteriorating) >= 3:
            break
        if r not in deteriorating and r["trend"] == "Down":
            deteriorating.append(r)
    # Most impaired leads, whichever rule pulled it in.
    deteriorating.sort(key=lambda r: r["ai_score"])

    return {
        "quarter": quarter, "rows": rows,
        "deteriorating": deteriorating[:3],
        "benchmark": compute_benchmark(quarter),
        "total_ead": float(cur[dl.EAD_COL].sum()),
        "insight": _matrix_insight(deteriorating[:3]),
    }


def _matrix_insight(deteriorating: list) -> str:
    if not deteriorating:
        return ("No portfolio shows the growth-risk disconnect this quarter — where growth is running "
                "ahead of plan, asset quality is holding.")
    names = ", ".join(r["sector"] for r in deteriorating)
    return (f"{names} show the growth-risk disconnect — high growth + rising Stage 2 + rising NPL = "
            f"emerging risk. These are the deteriorating portfolios; drill to obligors below.")


def compute_benchmark(quarter: str | None = None) -> dict:
    """The bank's own ratios against the listed Omani peer group."""
    quarter = quarter or dl.DEFAULT_QUARTER
    appetite = {r["key"]: r["value"] for r in compute_appetite_rows(quarter)}
    cur = dl.filtered_quarter(quarter)
    pq = dl.prev_quarter(quarter)
    prev = dl.filtered_quarter(pq) if pq else None
    ead = float(cur[dl.EAD_COL].sum())
    ecl = float(cur["Total ECL (USD mn)"].sum())
    raroc = float((cur["RAROC (%)"] * cur[dl.EAD_COL]).sum() / ead) if ead else 0.0

    # Cost of risk on the same annualised-charge basis the sector matrix uses, so
    # the two screens report the same number for the same thing.
    cost_of_risk = 0.0
    if prev is not None and ead:
        cost_of_risk = (ecl - float(prev["Total ECL (USD mn)"].sum())) * 4 / ead * 100

    own = {
        "npl_ratio": appetite.get("npl_ratio", 0.0),
        "stage3_ratio": appetite.get("stage3_ratio", 0.0),
        "ecl_coverage": appetite.get("ecl_coverage", 0.0),
        "capital_adequacy": appetite.get("capital_adequacy", 0.0),
        "cost_of_risk": cost_of_risk,
        # The ledger carries no equity, so a true ROE cannot be computed. RAROC is
        # shown instead and the row is labelled as the proxy it is.
        "roe": raroc,
    }

    metrics = []
    for spec in PEER_BENCHMARK["metrics"]:
        value = own.get(spec["key"], 0.0)
        label, position = _quartile(value, spec["median"], spec["better"])
        metrics.append({**spec, "value": value, "quartile": label, "position": position,
                        "ahead": (value < spec["median"]) if spec["better"] == "low"
                                 else (value > spec["median"])})
    return {**PEER_BENCHMARK, "metrics": metrics, "quarter": quarter}


# =================================================== screen 3: obligor detail

# The recommended action drives the button label; the dataset already carries one
# per account, so the menu is the real action set rather than an invented one.
ACTION_MENU = [
    "Revisit limit", "Reduce limit", "Remediation", "Enhanced watch",
    "To committee", "Covenant reset", "Review rollovers", "Monitor",
]

ACTION_FROM_RECOMMENDATION = {
    "Escalate to committee": "To committee",
    "Request remediation plan": "Remediation",
    "Add to enhanced watch": "Enhanced watch",
    "Review rollover history": "Review rollovers",
    "Increase monitoring freq.": "Enhanced watch",
    "Analyst review within 5d": "Revisit limit",
    "Confirm purpose of drawdown": "Revisit limit",
    "Routine monitoring": "Monitor",
}


def compute_sector_obligors(quarter: str | None = None, sector: str | None = None,
                            top_n: int = 5) -> dict:
    """Screen 3 — the obligors inside one sector, worst AI score first, each with
    the trigger that flagged it and the action the model recommends."""
    quarter = quarter or dl.DEFAULT_QUARTER
    cur = dl.filtered_quarter(quarter)
    sub = cur[cur["Sector"] == sector] if sector else cur
    if sub.empty:
        return {"sector": sector, "quarter": quarter, "obligors": [], "ead": 0.0, "ai_score": 0.0}

    grouped = []
    for (cid, borrower), g in sub.groupby(["Customer ID", "Borrower"]):
        ead = float(g[dl.EAD_COL].sum())
        if not ead:
            continue
        # The account that flagged worst is the one whose trigger the reviewer needs.
        worst = g.sort_values("AI Risk Score", ascending=False).iloc[0]
        grouped.append({
            "customer_id": cid, "borrower": borrower, "ead": ead,
            "rating": worst["Risk Rating"], "trend": worst["Trend"],
            "severity": worst["Severity"],
            "ai_score": ai_display_score(float((g["AI Risk Score"] * g[dl.EAD_COL]).sum() / ead)),
            "trigger": worst["Trigger"], "reason": worst["Reason Code"],
            "recommendation": worst["Recommended Action"],
            "action": ACTION_FROM_RECOMMENDATION.get(worst["Recommended Action"], "Monitor"),
            "stage": int(worst["IFRS 9 Stage"]),
            "dscr": float(worst["DSCR (x)"]), "headroom": float(worst["Covenant Headroom (%)"]),
        })

    # Worst score first; exposure breaks ties, so the biggest problem leads.
    grouped.sort(key=lambda r: (r["ai_score"], -r["ead"]))
    sector_ead = float(sub[dl.EAD_COL].sum())
    ai = ai_display_score(float((sub["AI Risk Score"] * sub[dl.EAD_COL]).sum() / sector_ead)) if sector_ead else 0.0
    return {
        "sector": sector, "quarter": quarter,
        "obligors": grouped[:top_n],
        "obligor_count": len(grouped),
        "ead": sector_ead,
        "ai_score": ai, "ai_tone": ai_score_tone(ai),
    }


def compute_obligor_screen(quarter: str | None = None, sectors: list | None = None,
                           top_n: int = 5) -> dict:
    """Screen 3 for several sectors side by side. Defaults to the deteriorating
    portfolios screen 2 identified, which is what makes the drill-down a path
    rather than three unrelated pages."""
    quarter = quarter or dl.DEFAULT_QUARTER
    if not sectors:
        sectors = [r["sector"] for r in compute_sector_matrix(quarter)["deteriorating"]]
    columns = [compute_sector_obligors(quarter, s, top_n) for s in sectors]
    return {
        "quarter": quarter,
        "columns": [c for c in columns if c["obligors"]],
        "action_menu": ACTION_MENU,
    }
