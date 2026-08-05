"""
The report content model, assembled from live data.

A report is a list of sections. Each section carries a short narrative, an
optional table, an optional chart spec, and any findings it raises. Findings are
what make the pack actionable: every breach produces a remediation item with an
owner and a due horizon, and the recommended actions at the end are derived from
those findings rather than written by hand.

Format-independent on purpose — the same model is poured into a PDF or a Word
file, so the two can never say different things.
"""

from datetime import UTC, date, datetime, timedelta

import backend.cockpit_data as cd
from backend import data_loader as dl

# ------------------------------------------------------------------ report types

REPORT_TYPES = {
    "smc": {
        "key": "smc",
        "title": "IFRS 9 Credit Committee / Senior Management Committee Report",
        "short": "Senior Management Committee",
        "audience": "Credit Committee · Senior Management Committee",
        "purpose": "The full working pack: portfolio position, IFRS 9 staging and ECL, appetite "
                   "and limits, concentration, watchlist, migration, stress, climate and macro, "
                   "with remediation for every live breach.",
        "cadence": "Quarterly, within 5 business days of quarter end",
    },
    "brc": {
        "key": "brc",
        "title": "Board Risk Committee Report",
        "short": "Board Risk Committee",
        "audience": "Board Risk Committee",
        "purpose": "A concise version of the Senior Management Committee pack: the same figures, "
                   "restricted to what the Board must decide on — position, asset quality, "
                   "appetite breaches, stress and the actions arising.",
        "cadence": "Quarterly, ahead of the Board Risk Committee meeting",
    },
}

# Section order is the reading order of the pack. `brc` carries the subset the
# Board needs to take a decision; `smc` carries everything.
SECTION_PLAN = [
    ("executive_summary", "Executive Summary", ("smc", "brc")),
    ("portfolio_position", "Portfolio Position", ("smc", "brc")),
    ("asset_quality", "Asset Quality & IFRS 9 Staging", ("smc", "brc")),
    ("ecl_movement", "ECL Movement & Coverage", ("smc",)),
    ("appetite", "Risk Appetite & Limit Utilisation", ("smc", "brc")),
    ("concentration", "Concentration Risk", ("smc",)),
    ("watchlist", "Watchlist & Early Warning", ("smc",)),
    ("migration", "Rating Migration", ("smc",)),
    ("stress", "Stress Testing", ("smc", "brc")),
    ("climate", "Climate Risk — Stressed PD", ("smc", "brc")),
    ("macro", "Macroeconomic Outlook", ("smc",)),
    ("actions", "Recommended Actions", ("smc", "brc")),
    ("remediation", "Remediation Plan", ("smc", "brc")),
]

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def report_spec(report_type: str) -> dict:
    return REPORT_TYPES.get(report_type, REPORT_TYPES["smc"])


def sections_for(report_type: str) -> list:
    return [(key, title) for key, title, audiences in SECTION_PLAN if report_type in audiences]


# ---------------------------------------------------------------------- helpers

def _pct(v, places=1):
    return "—" if v is None else f"{v:.{places}f}%"


def _finding(text, severity="MEDIUM", area=""):
    return {"text": text, "severity": severity, "area": area}


def _due(months: int) -> str:
    return (date.today() + timedelta(days=30 * months)).strftime("%b %Y")


# --------------------------------------------------------------------- sections

def _executive_summary(q, ctx):
    k, health = ctx["kpis"], ctx["health"]
    appetite = health["appetite"]
    breaches = [r for r in appetite if r["status"] == "BREACH"]
    aq = health["asset_quality"]

    narrative = (
        f"The book stands at {dl.fmt_bn(k['total_ead'], 2)} of exposure across "
        f"{ctx['borrower_count']} borrowers as at {dl._quarter_label(q)}, "
        f"{'up' if (k['ead_qoq_pct'] or 0) >= 0 else 'down'} "
        f"{abs(k['ead_qoq_pct'] or 0):.1f}% on the quarter. The composite health index reads "
        f"{health['score']:.0f}/100 ({health['band']['label']}), held there by an NPL ratio of "
        f"{aq['npl_ratio']:.1f}% and Stage 2 exposure of {health['stage2_pct']:.1f}% of the book. "
        f"{len(breaches)} of {len(appetite)} board appetite limits are in breach and "
        f"{k['breaches']} facility-level appetite breaches are flagged."
    )

    rows = [
        ["Total exposure (EAD)", dl.fmt_bn(k["total_ead"], 2),
         f"{(k['ead_qoq_pct'] or 0):+.1f}% QoQ"],
        ["NPL ratio", _pct(k["npl_ratio"]),
         f"{(k['npl_delta'] or 0):+.2f}pp QoQ" if k["npl_delta"] is not None else "—"],
        ["Stage 2 exposure", dl.fmt_bn(k["stage_ead"][2], 2),
         f"{dl.fmt_mn(k['stage2_delta'])} QoQ" if k["stage2_delta"] is not None else "—"],
        ["Total ECL", dl.fmt_mn(aq["total_ecl"]), f"{ctx['coverage']:.2f}% of EAD"],
        ["Portfolio RAROC", _pct(k["raroc"]),
         f"{(k['raroc_delta'] or 0):+.2f}pp QoQ" if k["raroc_delta"] is not None else "—"],
        ["Appetite limits breached", str(len(breaches)), f"of {len(appetite)} board limits"],
        ["Health index", f"{health['score']:.0f}/100", health["band"]["label"]],
    ]

    findings = []
    if breaches:
        findings.append(_finding(
            f"{len(breaches)} board appetite limits are in breach: "
            + ", ".join(r["label"] for r in breaches) + ".", "HIGH", "Appetite"))
    if health["band"]["label"] != "HEALTHY":
        findings.append(_finding(
            f"The health index is in the {health['band']['label']} band at {health['score']:.0f}/100.",
            "MEDIUM" if health["band"]["label"] == "WATCH" else "HIGH", "Portfolio"))
    if (aq["stage2_drift"] or 0) > 0:
        findings.append(_finding(
            f"Stage 2 exposure grew {dl.fmt_bn(aq['stage2_drift'], 2)} over the quarter, the largest "
            f"single drag on the health index.", "MEDIUM", "Asset quality"))

    return {
        "narrative": narrative,
        "table": {"columns": ["Measure", "Value", "Movement"], "rows": rows},
        "chart": {"kind": "health_trend", "title": "Health index — last 8 quarters"},
        "findings": findings,
    }


def _portfolio_position(q, ctx):
    matrix = ctx["matrix"]
    top = matrix["rows"][:6]
    rows = [[r["sector"], dl.fmt_bn(r["ead"], 2), _pct(r["growth"]), _pct(r["npl"]),
             _pct(r["stage2"]), f"{r['ai_score']:.0f}"] for r in matrix["rows"]]
    largest = max(matrix["rows"], key=lambda r: r["ead"])
    fastest = max((r for r in matrix["rows"] if r["growth"] is not None),
                  key=lambda r: r["growth"], default=None)

    narrative = (
        f"Exposure is spread across {len(matrix['rows'])} sectors and segments. "
        f"{largest['sector']} is the largest at {dl.fmt_bn(largest['ead'], 2)} "
        f"({largest['ead'] / matrix['total_ead'] * 100:.0f}% of the book)"
        + (f", and {fastest['sector']} is growing fastest at {fastest['growth']:.1f}% year on year"
           if fastest else "")
        + ". Portfolios are ranked worst-first by AI score, so the weakest books lead the table."
    )

    findings = []
    for r in matrix["deteriorating"]:
        findings.append(_finding(
            f"{r['sector']} shows the growth-risk disconnect — {_pct(r['growth'])} growth with "
            f"NPL at {_pct(r['npl'])} and Stage 2 at {_pct(r['stage2'])}.", "MEDIUM", "Concentration"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Sector / Segment", "Exposure", "Growth YoY", "NPL", "Stage 2", "AI score"],
                  "rows": rows},
        "chart": {"kind": "sector_exposure", "title": "Exposure by sector",
                  "data": [(r["sector"], r["ead"]) for r in top]},
        "findings": findings,
    }


def _asset_quality(q, ctx):
    aq = ctx["health"]["asset_quality"]
    stages = dl.compute_stage_breakdown(q)
    rows = [
        ["Stage 1 — performing", dl.fmt_bn(stages[1]["ead"], 2), _pct(stages[1]["pct"])],
        ["Stage 2 — significant increase in credit risk", dl.fmt_bn(stages[2]["ead"], 2),
         _pct(stages[2]["pct"])],
        ["Stage 3 — credit impaired", dl.fmt_bn(stages[3]["ead"], 2), _pct(stages[3]["pct"])],
    ]
    narrative = (
        f"Stage 2 stands at {_pct(stages[2]['pct'])} of exposure and Stage 3 at "
        f"{_pct(stages[3]['pct'])}. The gross NPL ratio is {aq['npl_ratio']:.1f}%"
        + (f", {abs(aq['npl_delta']):.2f}pp {'higher' if aq['npl_delta'] > 0 else 'lower'} than last "
           f"quarter" if aq["npl_delta"] is not None else "")
        + (f", with {dl.fmt_mn(aq['new_defaults'])} of new defaults"
           if aq["new_defaults"] is not None else "")
        + (f" and a cure rate of {aq['cure_rate']:.0f}%" if aq["cure_rate"] is not None else "")
        + f". ECL coverage of the non-performing book is {ctx['npl_coverage']:.0f}%."
    )
    findings = []
    if stages[2]["pct"] > 12:
        findings.append(_finding(
            f"Stage 2 exposure of {_pct(stages[2]['pct'])} is elevated; a sustained migration into "
            f"Stage 3 would carry a material ECL charge.", "MEDIUM", "IFRS 9"))
    if ctx["npl_coverage"] < 90:
        findings.append(_finding(
            f"NPL provision coverage of {ctx['npl_coverage']:.0f}% is below the 90% appetite floor.",
            "HIGH", "IFRS 9"))
    return {
        "narrative": narrative,
        "table": {"columns": ["IFRS 9 stage", "Exposure", "% of book"], "rows": rows},
        "chart": {"kind": "stage_mix", "title": "Exposure by IFRS 9 stage",
                  "data": [("Stage 1", stages[1]["ead"]), ("Stage 2", stages[2]["ead"]),
                           ("Stage 3", stages[3]["ead"])]},
        "findings": findings,
    }


def _ecl_movement(q, ctx):
    trend = dl.compute_ecl_trend(q, n_quarters=6)
    rows = [[t["label"], dl.fmt_mn(t["total_ecl"]), dl.fmt_bn(t["total_ead"], 2),
             f"{t['total_ecl'] / t['total_ead'] * 100:.2f}%"] for t in trend]
    first, last = trend[0], trend[-1]
    delta = last["total_ecl"] - first["total_ecl"]
    narrative = (
        f"ECL has moved from {dl.fmt_mn(first['total_ecl'])} to {dl.fmt_mn(last['total_ecl'])} over "
        f"{len(trend)} quarters, a change of {dl.fmt_mn(delta)}. Coverage of total exposure is "
        f"{last['total_ecl'] / last['total_ead'] * 100:.2f}%, against "
        f"{first['total_ecl'] / first['total_ead'] * 100:.2f}% at the start of the period."
    )
    findings = []
    if delta > 0:
        findings.append(_finding(
            f"ECL has risen {dl.fmt_mn(delta)} over the period; the charge should be attributed "
            f"between staging migration, model refresh and new lending in the next pack.",
            "MEDIUM", "IFRS 9"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Quarter", "Total ECL", "Total EAD", "Coverage"], "rows": rows},
        "chart": {"kind": "ecl_trend", "title": "ECL and coverage trend",
                  "data": [(t["label"], t["total_ecl"]) for t in trend]},
        "findings": findings,
    }


def _appetite(q, ctx):
    lim = ctx["limits"]
    board = ctx["health"]["appetite"]
    rows = [[r["label"], f"{r['value']:.1f}{r['unit']}", r["appetite_text"].replace("appetite ", ""),
             r["status"]] for r in board]
    breaches = [r for r in board if r["status"] == "BREACH"]
    near = [r for r in board if r["status"] == "NEAR LIMIT"]

    narrative = (
        f"{len(breaches)} board appetite limits are in breach and {len(near)} sit within the near-limit "
        f"trigger. Across the {len(lim['rows'])} operational limit lines, {lim['active_breaches']} are "
        f"over their cap, {lim['near_limit']} are above 90% utilisation and {lim['within_appetite']} "
        f"are within appetite."
        + (f" Quarter on quarter, {lim['rising']} lines moved up against their cap"
           + (f" and {lim['newly_breached']} crossed into breach" if lim["newly_breached"] else "")
           + "." if lim["has_comparison"] else "")
    )

    findings = [
        _finding(f"{r['label']} is at {r['value']:.1f}{r['unit']} against an appetite of "
                 f"{r['appetite']:g}{r['unit']}.", "HIGH", "Appetite")
        for r in breaches
    ] + [
        _finding(f"{r['label']} is at {r['value']:.1f}{r['unit']}, inside the near-limit trigger.",
                 "MEDIUM", "Appetite")
        for r in near
    ]

    return {
        "narrative": narrative,
        "table": {"columns": ["Board limit", "Actual", "Appetite", "Status"], "rows": rows},
        "chart": {"kind": "limit_utilisation", "title": "Limit utilisation — tightest 8 lines",
                  "data": [(r["label"], r["pct"]) for r in lim["rows"][:8]]},
        "findings": findings,
    }


def _concentration(q, ctx):
    conc = dl.compute_concentration_heatmap(q)
    caps = conc.get("sector_caps", [])[:8]
    rows = [[c["sector"], dl.fmt_bn(c["ead"], 2), _pct(c["utilisation"], 0)] for c in caps]
    narrative = (
        f"Portfolio HHI is {conc['hhi']:.3f} and the top-10 obligors account for "
        f"{conc['top10_pct']:.1f}% of exposure."
        + (f" The tightest sector cap is {caps[0]['sector']} at {caps[0]['utilisation']:.0f}% "
           f"utilisation." if caps else "")
    )
    findings = []
    if conc["top10_pct"] > 20:
        findings.append(_finding(
            f"Top-10 obligor concentration of {conc['top10_pct']:.1f}% is material; single-name "
            f"appetite should be reconfirmed.", "MEDIUM", "Concentration"))
    for c in caps:
        if c["utilisation"] >= 100:
            findings.append(_finding(
                f"{c['sector']} is at {c['utilisation']:.0f}% of its sector cap.", "HIGH",
                "Concentration"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Sector", "Exposure", "Cap utilisation"], "rows": rows},
        "chart": None,
        "findings": findings,
    }


def _watchlist(q, ctx):
    board = dl.compute_watchlist_board(q, top_n_per_col=20)
    signals = dl.compute_ai_signals(q, top_n=8)
    counts = board["counts"]
    new_count = signals.get("new_count", 0)
    rows = [[col, str(counts.get(col, 0))] for col in dl.WATCHLIST_COLUMNS]
    narrative = (
        f"{sum(counts.values())} names sit on the watchlist board. "
        f"{signals['red_count']} facilities carry a RED early-warning signal and "
        f"{signals['amber_count']} carry AMBER, with {new_count} newly flagged this quarter."
    )
    # compute_ai_signals returns the raw ledger column names.
    top_rows = [[s["Borrower"], s["Severity"], s["Trigger"], s["Recommended Action"]]
                for s in signals["signals"][:8]]
    findings = []
    if counts.get("Recovery", 0):
        findings.append(_finding(
            f"{counts['Recovery']} names are in Recovery — the impaired end of the book.",
            "HIGH", "Watchlist"))
    if new_count:
        findings.append(_finding(
            f"{new_count} facilities were newly flagged this quarter and need an owner assigned "
            f"within the review cycle.", "MEDIUM", "Watchlist"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Borrower", "Severity", "Trigger", "Recommended action"],
                  "rows": top_rows},
        "extra_table": {"columns": ["Watchlist stage", "Names"], "rows": rows},
        "chart": None,
        "findings": findings,
    }


def _migration(q, ctx):
    m = dl.compute_rating_migration(q)
    rows = [[s["sector"], str(s["count"])] for s in m.get("downgrades_by_sector", [])[:6]]
    narrative = (
        f"{m['upgrades']} upgrades against {m['downgrades']} downgrades over the trailing period, "
        f"a net movement of {m['net_migration']:+d} notches"
        + (f", led by {m['downgrades_by_sector'][0]['sector']}."
           if m.get("downgrades_by_sector") else ".")
    )
    findings = []
    if m["net_migration"] < 0:
        findings.append(_finding(
            f"Net rating migration is negative ({m['net_migration']:+d}); downgrades are outpacing "
            f"upgrades.", "MEDIUM", "Migration"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Sector", "Downgrades"], "rows": rows},
        "chart": None,
        "findings": findings,
    }


def _stress(q, ctx):
    scenarios = [
        ("Mild — +100bps", dl.compute_stress_scenario(q, 100, 0)),
        ("Standard — +300bps", dl.compute_stress_scenario(q, 300, 0)),
        ("Severe — +400bps / CRE −30%", dl.compute_stress_scenario(q, 400, 30)),
    ]
    rows = [[name, dl.fmt_mn(r["stressed_ecl"]), dl.fmt_mn(r["ecl_delta"]),
             f"{r['cet1_bps_impact']:.0f}bps", _pct(r["stressed_npl_pct"]),
             str(r["covenant_breach_count"])] for name, r in scenarios]
    severe = scenarios[-1][1]
    narrative = (
        f"Under the severe scenario (+400bps and a 30% fall in commercial real estate values), ECL "
        f"rises to {dl.fmt_mn(severe['stressed_ecl'])} — an increase of "
        f"{dl.fmt_mn(severe['ecl_delta'])} — costing {abs(severe['cet1_bps_impact']):.0f}bps of CET1 "
        f"and taking the NPL ratio to {severe['stressed_npl_pct']:.1f}%. "
        f"{severe['covenant_breach_count']} borrowers are projected to breach covenants."
    )
    findings = []
    if abs(severe["cet1_bps_impact"]) > 75:
        findings.append(_finding(
            f"The severe scenario costs {abs(severe['cet1_bps_impact']):.0f}bps of CET1; capital "
            f"headroom against the management buffer should be confirmed.", "HIGH", "Stress"))
    if severe["covenant_breach_count"]:
        findings.append(_finding(
            f"{severe['covenant_breach_count']} borrowers breach covenants under the severe "
            f"scenario; remediation plans should be pre-agreed for the largest.", "MEDIUM", "Stress"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Scenario", "Stressed ECL", "ECL increase", "CET1 impact",
                              "Stressed NPL", "Covenant breaches"], "rows": rows},
        "chart": {"kind": "stress_ecl", "title": "Stressed ECL by scenario",
                  "data": [(name.split(" — ")[0], r["stressed_ecl"]) for name, r in scenarios]},
        "findings": findings,
    }


def _climate(q, ctx):
    try:
        from backend.climate import store as climate_store
        _model, result, checks = climate_store.latest_result()
    except Exception:  # noqa: BLE001 — a report must not fail on an optional module
        return {"narrative": "Climate stressed-PD results are unavailable.", "table": None,
                "chart": None, "findings": []}

    grade = result["reference_grade"]
    at_grade = [r for r in result["grid"] if r["grade"] == grade]
    worst = max(at_grade, key=lambda r: r["multiple"])
    by_sector = sorted(result["summary"], key=lambda s: -s["multiples"].get("NZ", 0))[:6]
    rows = [[s["sector"]] + [f"{s['multiples'][c]:.2f}x" for c in result["scenario_codes"]]
            for s in by_sector]
    failing = [c for c in checks if c["status"] == "FAIL"]

    narrative = (
        f"At the {result['horizon_year']} horizon and grade {grade}, the most exposed portfolio is "
        f"{worst['sector']} under {worst['scenario_name']}: a baseline PD of "
        f"{worst['baseline_pd'] * 100:.2f}% becomes {worst['stressed_pd'] * 100:.2f}%, a "
        f"{worst['multiple']:.2f}x multiple. Transition and physical channels run in opposite "
        f"directions across the scenarios, as they should. {len(failing)} of {len(checks)} model "
        f"quality checks are failing."
    )
    findings = []
    if worst["multiple"] > 1.5:
        findings.append(_finding(
            f"Climate transition risk lifts {worst['sector']} PDs {worst['multiple']:.2f}x under "
            f"{worst['scenario_name']}; sector strategy should reflect the transition path.",
            "MEDIUM", "Climate"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Sector"] + list(result["scenario_codes"]), "rows": rows},
        "chart": {"kind": "climate_multiples", "title": f"PD multiple at grade {grade} — Net Zero 2050",
                  "data": [(s["sector"], s["multiples"].get("NZ", 0)) for s in by_sector]},
        "findings": findings,
    }


def _macro(q, ctx):
    health = dl.compute_portfolio_health(q)
    cur, horizon = health["current"], health["weighted_path"][-1]
    rows = [
        ["NPL ratio", _pct(cur["npl"]), _pct(horizon["npl"])],
        ["Stage 2 share", _pct(cur["stage2"]), _pct(horizon["stage2"])],
        ["ECL coverage", _pct(cur["coverage"], 2), _pct(horizon["coverage"], 2)],
        ["Health index", f"{health['health_now']:.0f}/100", f"{health['health_weighted']:.0f}/100"],
    ]
    narrative = (
        f"On the probability-weighted scenario path, the NPL ratio moves from {cur['npl']:.1f}% to "
        f"{horizon['npl']:.1f}% over four quarters and the health index from "
        f"{health['health_now']:.0f} to {health['health_weighted']:.0f}. Higher-for-longer rates and "
        f"softening real estate remain the dominant headwinds."
    )
    findings = []
    if horizon["npl"] > cur["npl"]:
        findings.append(_finding(
            f"The weighted forward path takes NPL to {horizon['npl']:.1f}%; provisioning should be "
            f"planned against that trajectory rather than the spot ratio.", "MEDIUM", "Macro"))
    return {
        "narrative": narrative,
        "table": {"columns": ["Measure", "Current", "4Q forward"], "rows": rows},
        "chart": None,
        "findings": findings,
    }


# ---------------------------------------------------- actions and remediation

ACTION_OWNERS = {
    "Appetite": "Head of Credit Risk",
    "IFRS 9": "Head of Impairment",
    "Concentration": "Portfolio Management",
    "Watchlist": "Head of Special Assets",
    "Stress": "Head of Capital Planning",
    "Climate": "Head of Climate Risk",
    "Macro": "Chief Economist",
    "Migration": "Head of Credit Risk",
    "Asset quality": "Head of Credit Risk",
    "Portfolio": "Chief Risk Officer",
}

REMEDIATION_PLAYBOOK = {
    "Appetite": ("Reduce or re-price the tightest facilities, and re-present the limit for "
                 "ratification if the breach is to be tolerated.", 1),
    "IFRS 9": ("Re-run the staging assessment on the affected book and confirm the provision "
               "coverage against policy.", 1),
    "Concentration": ("Cap new origination in the affected sector and prepare a distribution or "
                      "sell-down option.", 2),
    "Watchlist": ("Assign a named owner to each new flag and file a remediation plan within the "
                  "review cycle.", 1),
    "Stress": ("Confirm capital headroom against the management buffer and pre-agree remediation "
               "for the largest projected covenant breaches.", 2),
    "Climate": ("Reflect the transition path in sector strategy and pricing for the most exposed "
                "portfolios.", 6),
    "Macro": ("Plan provisioning against the weighted forward path, not the spot ratio.", 3),
    "Migration": ("Review the downgrade drivers in the leading sector and confirm early-warning "
                  "coverage.", 2),
    "Asset quality": ("Attribute the Stage 2 movement and confirm whether it reflects genuine "
                      "credit deterioration or a model or policy change.", 1),
    "Portfolio": ("Track management actions against the health index at the next review.", 3),
}


def _actions(findings):
    """Recommended actions, derived from the findings rather than written by hand —
    so an action can never survive the condition that produced it."""
    seen, actions = set(), []
    for f in sorted(findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 3)):
        area = f["area"] or "Portfolio"
        if area in seen:
            continue
        seen.add(area)
        text, months = REMEDIATION_PLAYBOOK.get(
            area, ("Review and report back at the next committee.", 3))
        actions.append({
            "priority": f["severity"],
            "area": area,
            "action": text,
            "owner": ACTION_OWNERS.get(area, "Chief Risk Officer"),
            "due": _due(months),
        })
    return actions


def _remediation(findings):
    """One row per finding that represents a breach or a live exception."""
    items = []
    for f in sorted(findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 3)):
        if f["severity"] == "LOW":
            continue
        area = f["area"] or "Portfolio"
        text, months = REMEDIATION_PLAYBOOK.get(
            area, ("Review and report back at the next committee.", 3))
        items.append({
            "severity": f["severity"],
            "area": area,
            "issue": f["text"],
            "remediation": text,
            "owner": ACTION_OWNERS.get(area, "Chief Risk Officer"),
            "due": _due(months),
        })
    return items


# ------------------------------------------------------------------- assembly

_BUILDERS = {
    "executive_summary": _executive_summary,
    "portfolio_position": _portfolio_position,
    "asset_quality": _asset_quality,
    "ecl_movement": _ecl_movement,
    "appetite": _appetite,
    "concentration": _concentration,
    "watchlist": _watchlist,
    "migration": _migration,
    "stress": _stress,
    "climate": _climate,
    "macro": _macro,
}


# The shared data load behind every section: ~0.6s of the ~0.8s it takes to build
# a report, and the Review Pack screen rebuilds the report on every click of a
# report-type or format card. Keyed on dl.DATASET_GENERATION, which every swap of
# the dataset globals bumps — so activating a new upload can never be served from
# a cache built against the old data. A stale committee pack would be far worse
# than a slow one.
_CONTEXT_CACHE: dict = {}


def _context(q):
    key = (q, dl.DATASET_GENERATION)
    if key in _CONTEXT_CACHE:
        return _CONTEXT_CACHE[key]

    cur = dl.filtered_quarter(q)
    ead = float(cur[dl.EAD_COL].sum())
    ecl = float(cur["Total ECL (USD mn)"].sum())
    npl_ead = float(cur.loc[cur["NPL"] == "Yes", dl.EAD_COL].sum())
    ctx = {
        "kpis": dl.compute_kpis(q),
        "health": cd.compute_health_screen(q),
        "matrix": cd.compute_sector_matrix(q),
        "limits": dl.compute_limits_dashboard(q),
        "borrower_count": int(cur["Customer ID"].nunique()),
        "coverage": (ecl / ead * 100) if ead else 0.0,
        "npl_coverage": (ecl / npl_ead * 100) if npl_ead else 0.0,
    }
    # Only ever hold the current generation, so the cache cannot grow without
    # bound and cannot serve a superseded dataset.
    _CONTEXT_CACHE.clear()
    _CONTEXT_CACHE[key] = ctx
    return ctx


def clear_context_cache() -> None:
    """Drop the cached data load. The generation key makes this unnecessary in
    normal operation; it exists so tests can force a cold build."""
    _CONTEXT_CACHE.clear()


def build_report(report_type: str = "smc", quarter: str | None = None,
                 prepared_by: str = "") -> dict:
    """Assemble the full content model for one report type.

    Sections that fail are reported as such rather than taking the pack down —
    a committee pack that is missing a section is recoverable; one that fails to
    generate the night before the meeting is not.
    """
    quarter = quarter or dl.DEFAULT_QUARTER
    spec = report_spec(report_type)
    ctx = _context(quarter)

    sections, all_findings = [], []
    for key, title in sections_for(spec["key"]):
        if key in ("actions", "remediation"):
            continue
        try:
            body = _BUILDERS[key](quarter, ctx)
        except Exception as exc:  # noqa: BLE001
            body = {"narrative": f"This section could not be generated ({exc}).",
                    "table": None, "chart": None, "findings": []}
        body.update({"key": key, "title": title})
        sections.append(body)
        all_findings.extend(body.get("findings", []))

    actions = _actions(all_findings)
    remediation = _remediation(all_findings)

    if any(k == "actions" for k, _ in sections_for(spec["key"])):
        sections.append({
            "key": "actions", "title": "Recommended Actions",
            "narrative": (f"{len(actions)} actions are recommended, ordered by the severity of the "
                          f"finding that produced them. Each carries a named owner and a target date."
                          if actions else "No actions are outstanding this quarter."),
            "table": {"columns": ["Priority", "Area", "Recommended action", "Owner", "Target"],
                      "rows": [[a["priority"], a["area"], a["action"], a["owner"], a["due"]]
                               for a in actions]},
            "chart": None, "findings": [],
        })
    if any(k == "remediation" for k, _ in sections_for(spec["key"])):
        sections.append({
            "key": "remediation", "title": "Remediation Plan",
            "narrative": (f"{len(remediation)} items require remediation. Every live breach or "
                          f"exception raised in this pack appears here with the action, the owner "
                          f"and the date it is due."
                          if remediation else "No breaches or exceptions require remediation."),
            "table": {"columns": ["Severity", "Area", "Issue", "Remediation", "Owner", "Due"],
                      "rows": [[r["severity"], r["area"], r["issue"], r["remediation"],
                                r["owner"], r["due"]] for r in remediation]},
            "chart": None, "findings": [],
        })

    high = sum(1 for f in all_findings if f["severity"] == "HIGH")
    return {
        "type": spec["key"],
        "title": spec["title"],
        "short_title": spec["short"],
        "audience": spec["audience"],
        "purpose": spec["purpose"],
        "quarter": quarter,
        "quarter_label": dl._quarter_label(quarter),
        "generated_at": datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
        "prepared_by": prepared_by or "IPM — Intelligent Portfolio Manager",
        "sections": sections,
        "findings": all_findings,
        "actions": actions,
        "remediation": remediation,
        "high_severity_count": high,
        "classification": "CONFIDENTIAL — FOR COMMITTEE USE ONLY",
    }
