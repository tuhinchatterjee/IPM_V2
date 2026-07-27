"""
RAROC 2 views (Build Plan §3): Deal Explorer (landing), Deal Detail (RAROC card +
rate/market + risk + earnings for one deal), Earnings & EVA (portfolio roll-up),
and Methodology (the governed assumptions). Data/engine in raroc2_data.py.
"""

import plotly.graph_objects as go
from dash import dcc, html

from backend import data_loader as dl
from backend import raroc2_data as r2
from frontend import ui_common as ui

TOGGLES = [{"label": " Credit-only", "value": "credit_only"},
           {"label": " Quick-Close", "value": "quick_close"}]


def _flags(toggles):
    toggles = toggles or []
    return {"credit_only": "credit_only" in toggles, "quick_close": "quick_close" in toggles}


def _aed(v, mn=True):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"AED {v / 1000:,.2f}bn"
    return f"AED {v:,.1f}m"


def _raroc_cell(value, stage3=False):
    if stage3:
        return html.Span("N/A", className="raroc-na")
    cls = "up-good" if value >= r2.HURDLE_PCT else "up-bad"
    return html.Span(f"{value:.0f}%", className=f"raroc-strong {cls}")


# ============================================================= Deal Explorer

def build_deal_explorer_body(toggles=None, segment="All"):
    f = _flags(toggles)
    summary = r2.compute_summary(**f)
    deals = summary["deals"]
    if segment and segment != "All":
        deals = [d for d in deals if d["segment"] == segment]

    port = summary["portfolio_raroc"]
    kpis = [
        ui.kpi_card("Weighted Post-Deal RAROC", f"{port:.0f}%",
                    "green" if port >= summary["hurdle"] else "red",
                    ui.kpi_sub(f"vs {summary['hurdle']:.0f}% hurdle · {summary['above_pct']:.0f}% above",
                               "up-good" if port >= summary["hurdle"] else "up-bad")),
        ui.kpi_card("Total EVA (Short-Term)", _aed(summary["eva_st_total"]), "blue",
                    ui.kpi_sub("economic profit over hurdle")),
        ui.kpi_card("Lifetime Earning", _aed(summary["lte_total"]), "teal",
                    ui.kpi_sub("risk-adjusted, discounted")),
        ui.kpi_card("Fallen Below Hurdle", str(summary["below_count"]), "amber",
                    ui.kpi_sub(f"{_aed(summary['below_ead'])} EAD",
                               "up-bad" if summary["below_count"] else "neutral")),
    ]

    rows = []
    for d in deals:
        rows.append(html.Tr([
            html.Td([html.Div(d["borrower"], className="metric-name"),
                     html.Div(f"{d['deal_id']} · {d['facility_type']}", className="raroc-subtext")]),
            html.Td(d["segment"], className="raroc-subtext2"),
            html.Td([d["rating_book"], html.Span(" → ", className="raroc-arrow"), d["rating_now"]],
                    className="num raroc-migr"),
            html.Td(dl.fmt_bn(d["ead"], 2), className="num"),
            html.Td(_raroc_cell(d["raroc_st"], d["stage3"]), className="num"),
            html.Td(_raroc_cell(d["raroc_lt"], d["stage3"]), className="num"),
            html.Td(_aed(d["eva_st"]), className=f"num {'raroc-neg' if d['eva_st'] < 0 else ''}"),
            html.Td(_aed(d["lte"]), className="num raroc-lifetime"),
            html.Td(html.Span("N/A" if d["stage3"] else ("Above" if d["above_hurdle"] else "Below"),
                              className=f"gap-pill {'is-aligned' if d['above_hurdle'] and not d['stage3'] else ''}")),
        ], className="is-flagged" if (not d["above_hurdle"] and not d["stage3"]) else None))
    table = html.Table(
        [html.Thead(html.Tr([
            html.Th("Deal / Borrower"), html.Th("Segment"), html.Th("Rating (book→now)"),
            html.Th("EAD", className="num"), html.Th("RAROC ST", className="num"),
            html.Th("RAROC LT", className="num"), html.Th("EVA (ST)", className="num"),
            html.Th("Lifetime", className="num"), html.Th("Status")])),
         html.Tbody(rows)],
        className="borrower-table signals-table",
    )

    insight = (
        f"Across {summary['n_perf']} performing deals the book earns a weighted post-deal RAROC of {port:.0f}% "
        f"(hurdle {summary['hurdle']:.0f}%); {summary['above_pct']:.0f}% of deals clear it. {summary['below_count']} "
        f"have fallen below hurdle since booking — {summary['repriced_late']} repriced late after base-rate moves, "
        f"{summary['downgraded']} were downgraded (lifting capital), and {summary['fee_waived']} had fees waived "
        f"post-approval. Total short-term EVA is {_aed(summary['eva_st_total'])}. RAROC is always shown beside EVA "
        f"so a high return on a tiny capital base is never mistaken for large value creation. Stage 3 names show "
        f"RAROC as N/A and are excluded from the weighted figure. Open Deal Detail for the approved-vs-actual "
        f"attribution on any name."
    )
    return [
        html.Div(kpis, className="signals-kpi-grid"),
        ui.table_card(f"DEAL EXPLORER — {len(deals)} DEALS", table,
                      hint="RAROC on regulatory capital (RWA × target CET1)"),
        html.Div(ui.ai_insight_card(insight, title="AI RAROC COMMENTARY"), style={"marginTop": "20px"}),
    ]


def _explorer_controls(toggles=None, segment="All"):
    segs = ["All", "Corporate", "Commercial Real Estate", "SME", "Trade Finance", "Retail"]
    return html.Div(
        [
            html.Span("SEGMENT", className="filters-label"),
            dcc.Dropdown(id="r2exp-segment", options=[{"label": s, "value": s} for s in segs],
                         value=segment, clearable=False, searchable=False, className="filter-dd"),
            html.Span("BASIS", className="filters-label"),
            dcc.Checklist(id="r2exp-toggles", options=TOGGLES, value=toggles or [],
                          inline=True, className="raroc-toggles"),
            html.Button("⬇ Export sample dataset", id="r2exp-export", className="reset-btn", n_clicks=0),
        ],
        className="filters-row",
    )


def build_deal_explorer_tab():
    return [_explorer_controls(), html.Div(build_deal_explorer_body(), id="r2exp-body")]


# =============================================================== Deal Detail

def _kv_table(title, dot, rows):
    body = [html.Tr([html.Td(k, className="metric-name"), html.Td(a, className="num"),
                     html.Td(b, className="num"), html.Td(delta)]) for k, a, b, delta in rows]
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Metric"), html.Th("Approved", className="num"),
                             html.Th("Actual (now)", className="num"), html.Th("Δ")])),
         html.Tbody(body)],
        className="dark-mini-table",
    )
    return ui.dark_table_card(title, dot, table)


def _delta(v, unit="", good_up=True, dec=1):
    if abs(v) < 1e-9:
        return html.Span("—", className="raroc-delta neutral")
    up = v > 0
    cls = "up-good" if up == good_up else "up-bad"
    return html.Span(f"{'▲' if up else '▼'} {abs(v):.{dec}f}{unit}", className=f"raroc-delta {cls}")


def _waterfall(d):
    ead = d["ead"]
    # Per-AED-mn components scaled to the deal (annual, AED mn).
    fees = (d["undrawn"] * d["commit_bps"] / 10000 + ead * d["upfront_bps"] / 10000 / max(d["tenor"], 1)
            + d["transactional"]) * r2.AED
    cross = d["cross_now"]
    capb = d["cap_now_usd"] * r2.REINVEST_PCT / 100 * r2.AED
    opex = ead * d["opex_bps"] / 10000 * r2.AED
    el = d["el_now"]
    steps = [("Gross yield", ead * d["applied_now"] / 100 * r2.AED, "absolute"),
             ("− FTP", -ead * d["ftp_now"] / 100 * r2.AED, "relative"),
             ("+ Fees", fees, "relative"), ("+ Cross-sell", cross, "relative"),
             ("+ Capital benefit", capb, "relative"), ("− Opex", -opex, "relative"),
             ("− Expected loss", -el, "relative")]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=[s[2] for s in steps] + ["total"],
        x=[s[0] for s in steps] + ["Risk-adj. earning"],
        y=[s[1] for s in steps] + [0],
        connector=dict(line=dict(color="#d5dde6")),
        increasing=dict(marker=dict(color="#1fa971")), decreasing=dict(marker=dict(color="#e5484d")),
        totals=dict(marker=dict(color="#16b8a6")),
    ))
    ui.base_layout(fig, height=300)
    fig.update_layout(margin=dict(t=10, b=60, l=40, r=10), xaxis=dict(tickangle=-30))
    return ui.chart_card("P&L WATERFALL — GROSS YIELD → RISK-ADJUSTED EARNING (AED mn/yr)",
                         dcc.Graph(figure=fig, config={"displayModeBar": False}))


def _earning_bridge(d):
    s = r2.deal_earning_series(d)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=s["hist_labels"], y=s["hist"], name="Realised", marker=dict(color="#16232f")))
    fig.add_trace(go.Bar(x=s["fwd_labels"], y=s["fwd"], name="Projected", marker=dict(color="#16b8a6")))
    ui.base_layout(fig, height=240, legend=True)
    fig.update_layout(margin=dict(t=10, b=30, l=40, r=10), barmode="group")
    return ui.chart_card("EARNING BY PERIOD — REALISED (since booking) & PROJECTED (AED mn/qtr)",
                         dcc.Graph(figure=fig, config={"displayModeBar": False}))


def build_deal_detail_body(deal_id=None, toggles=None):
    f = _flags(toggles)
    deals = r2.compute_deal_book(**f)
    d = next((x for x in deals if x["deal_id"] == deal_id), deals[0])

    # Earnings Output — the two headline figures (Plan §3.5).
    earn_cards = html.Div([
        ui.metric_card("SHORT-TERM / QUICK-CLOSE EARNING", _aed(d["ste"]),
                       f"RAROC {d['raroc_st']:.0f}% · EVA {_aed(d['eva_st'])} · "
                       f"{'quick-close (early exit)' if f['quick_close'] else '12-month horizon'}",
                       value_cls="is-red" if d["eva_st"] < 0 else "",
                       sub_cls="is-red" if d["eva_st"] < 0 else "is-muted"),
        ui.metric_card("LIFETIME EARNING", _aed(d["lte"]),
                       f"RAROC {d['raroc_lt']:.0f}% · EVA {_aed(d['eva_lt'])} · behavioural life "
                       f"{d['behavioural_remaining']:.1f}y",
                       value_cls="is-red" if d["eva_lt"] < 0 else "",
                       sub_cls="is-red" if d["eva_lt"] < 0 else "is-muted"),
    ], className="metric-card-row")

    # RAROC card: approved vs actual.
    card = _kv_table("RAROC CARD — APPROVED CASE vs ACTUAL", "purple", [
        ("RAROC (%)", f"{d['approved_raroc']:.0f}%", f"{d['raroc_st']:.0f}%",
         _delta(d["raroc_drift"], "pp", good_up=True, dec=0)),
        ("NIM after FTP (%)", f"{d['nim_book']:.2f}", f"{d['nim_now']:.2f}",
         _delta(d["nim_change"], "pp", good_up=True, dec=2)),
        ("Base rate (%)", f"{d['base_book']:.2f}", f"{d['base_now']:.2f}",
         _delta(d["base_change_bps"] / 100, "pp", good_up=False, dec=2)),
        ("FTP (%)", f"{d['ftp_book']:.2f}", f"{d['ftp_now']:.2f}",
         _delta(d["ftp_change"], "pp", good_up=False, dec=2)),
        ("PD (%)", f"{d['pd_ttc_book']:.2f} (TTC)", f"{d['pd_pit']:.2f} (PIT)",
         _delta(d["pd_pit"] - d["pd_ttc_book"], "pp", good_up=False, dec=2)),
        ("Rating", d["rating_book"], d["rating_now"],
         _delta(dl.NOTCH_INDEX.get(d["rating_book"], 10) - dl.NOTCH_INDEX.get(d["rating_now"], 10),
                " notch", good_up=True, dec=0)),
        ("Economic capital", _aed(d["cap_now_usd"] * r2.AED), _aed(d["cap_now"]), html.Span("")),
    ])

    # Rate & market panel.
    reset_note = ("Repriced LATE — still near an older base; reset action required" if d["repriced_late"]
                  else ("Fixed coupon — bears rate risk to maturity" if d["rate_type"] == "Fixed"
                        else "Floating — reprices with the index"))
    rate_panel = ui.table_card("RATE & MARKET MOVEMENT", html.Table([html.Tbody([
        html.Tr([html.Td("Rate type / index", className="metric-name"),
                 html.Td(f"{d['rate_type']} · {d['index']}", className="num")]),
        html.Tr([html.Td("Applied rate (now)", className="metric-name"),
                 html.Td(f"{d['applied_now']:.2f}%", className="num")]),
        html.Tr([html.Td("Base-rate move since booking", className="metric-name"),
                 html.Td(f"{d['base_change_bps']:+.0f} bps", className="num")]),
        html.Tr([html.Td("Funding cost (FTP) drift", className="metric-name"),
                 html.Td(f"{d['ftp_change']:+.2f} pp", className="num")]),
        html.Tr([html.Td("NIM decomposition", className="metric-name"),
                 html.Td(f"{d['nim_book']:.2f}% → {d['nim_now']:.2f}% ({d['nim_change']:+.2f})", className="num")]),
        html.Tr([html.Td("Reset status", className="metric-name"),
                 html.Td(reset_note, className="num")]),
        html.Tr([html.Td("Required spread to clear hurdle", className="metric-name"),
                 html.Td(f"+{d['required_spread_bps']:.0f} bps" if d["required_spread_bps"] > 0 else "clears",
                         className="num")]),
    ])], className="dark-mini-table"))

    # Risk panel.
    risk_panel = ui.table_card("RISK PANEL", html.Table([html.Tbody([
        html.Tr([html.Td("Rating migration", className="metric-name"),
                 html.Td(f"{d['rating_book']} → {d['rating_now']}", className="num")]),
        html.Tr([html.Td("PD 12m (PIT) / lifetime", className="metric-name"),
                 html.Td(f"{d['pd_pit']:.2f}% / {d['pd_life']:.2f}%", className="num")]),
        html.Tr([html.Td("LGD / CCF", className="metric-name"),
                 html.Td(f"{d['lgd'] * 100:.0f}% / {d['ccf'] * 100:.0f}%", className="num")]),
        html.Tr([html.Td("IFRS 9 stage / DPD", className="metric-name"),
                 html.Td(f"Stage {d['stage']} · {d['dpd']} dpd", className="num")]),
        html.Tr([html.Td("Expected loss (12m)", className="metric-name"),
                 html.Td(_aed(d["el_now"]), className="num")]),
        html.Tr([html.Td("Collateral / secured", className="metric-name"),
                 html.Td(f"{dl.fmt_bn(d['collateral'], 2)} · {'secured' if d['secured'] else 'unsecured'}",
                         className="num")]),
        html.Tr([html.Td("RWA density", className="metric-name"),
                 html.Td(f"{r2._risk_weight(d['segment'], d['rating_now'], d['secured']) * 100:.0f}%",
                         className="num")]),
    ])], className="dark-mini-table"))

    header = html.Div([
        html.Div([html.H3(d["borrower"], className="b360-name"),
                  html.Div(f"{d['deal_id']} · {d['facility_type']} · {d['segment']} · {d['region']} · "
                           f"booked {d['booking_q']} · RM {d['rm']}", className="b360-meta")]),
        html.Span("N/A (Stage 3)" if d["stage3"] else ("Above hurdle" if d["above_hurdle"] else "Below hurdle"),
                  className=f"pill-badge {'gray' if d['stage3'] else ('green' if d['above_hurdle'] else 'red')}"),
    ], className="b360-header-card")

    return [
        header,
        earn_cards,
        html.Div([html.Div([card, rate_panel], className="split-main"),
                  html.Div([_waterfall(d)], className="split-side")], className="split-grid"),
        html.Div([html.Div([_earning_bridge(d)], className="split-main"),
                  html.Div([risk_panel], className="split-side")], className="split-grid"),
    ]


def _detail_controls(deals, deal_id, toggles=None):
    return html.Div(
        [
            html.Span("DEAL", className="filters-label"),
            dcc.Dropdown(id="r2det-deal",
                         options=[{"label": f"{d['deal_id']} · {d['borrower']}", "value": d["deal_id"]}
                                  for d in deals],
                         value=deal_id, clearable=False, searchable=True, className="filter-dd",
                         style={"minWidth": "320px"}),
            html.Span("BASIS", className="filters-label"),
            dcc.Checklist(id="r2det-toggles", options=TOGGLES, value=toggles or [],
                          inline=True, className="raroc-toggles"),
        ],
        className="filters-row",
    )


def build_deal_detail_tab():
    deals = r2.compute_deal_book()
    deal_id = deals[0]["deal_id"]
    return [_detail_controls(deals, deal_id),
            html.Div(build_deal_detail_body(deal_id), id="r2det-body")]


# ============================================================= Earnings & EVA

def build_earnings_body(toggles=None):
    f = _flags(toggles)
    s = r2.compute_summary(**f)

    kpis = [
        ui.kpi_card("Short-Term Earning", _aed(s["ste_total"]), "teal",
                    ui.kpi_sub(f"EVA {_aed(s['eva_st_total'])}",
                               "up-good" if s["eva_st_total"] >= 0 else "up-bad")),
        ui.kpi_card("Lifetime Earning", _aed(s["lte_total"]), "blue",
                    ui.kpi_sub(f"EVA {_aed(s['eva_lt_total'])}",
                               "up-good" if s["eva_lt_total"] >= 0 else "up-bad")),
        ui.kpi_card("Capital Consumed", _aed(s["cap_total"]), "purple",
                    ui.kpi_sub(f"weighted RAROC {s['portfolio_raroc']:.0f}%")),
        ui.kpi_card("Value at Risk of Repricing", str(s["below_count"]), "amber",
                    ui.kpi_sub("deals below hurdle")),
    ]

    # Top EVA creators / destroyers.
    perf = [d for d in s["deals"] if not d["stage3"]]
    creators = sorted(perf, key=lambda d: -d["eva_st"])[:8]
    destroyers = sorted(perf, key=lambda d: d["eva_st"])[:8]

    def eva_table(title, dot, items):
        body = [html.Tr([html.Td(d["borrower"], className="metric-name"),
                         html.Td(d["segment"], className="raroc-subtext2"),
                         html.Td(f"{d['raroc_st']:.0f}%", className="num"),
                         html.Td(_aed(d["eva_st"]), className=f"num {'raroc-neg' if d['eva_st'] < 0 else ''}")])
                for d in items]
        return ui.dark_table_card(title, dot, html.Table(
            [html.Thead(html.Tr([html.Th("Borrower"), html.Th("Segment"), html.Th("RAROC", className="num"),
                                 html.Th("EVA (ST)", className="num")])), html.Tbody(body)],
            className="dark-mini-table"))

    insight = (
        f"The book creates {_aed(s['eva_st_total'])} of short-term economic value and {_aed(s['eva_lt_total'])} "
        f"over the lifetime horizon, on {_aed(s['cap_total'])} of capital. Value is concentrated: the top names "
        f"carry the book while {s['below_count']} deals destroy value at the current price. Ranking on EVA (not "
        f"RAROC) is deliberate — a 150% RAROC on a tiny facility can create less value than a 20% RAROC on a large "
        f"one. Relationship note: some deals below hurdle on a credit-only basis clear comfortably once deposit and "
        f"ancillary income are included — toggle Credit-only to see the difference."
    )
    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div([html.Div([eva_table("TOP VALUE CREATORS (EVA)", "green", creators)], className="split-main"),
                  html.Div([eva_table("VALUE DESTROYERS (EVA)", "red", destroyers)], className="split-side")],
                 className="split-grid"),
        html.Div(ui.ai_insight_card(insight, title="AI RAROC COMMENTARY"), style={"marginTop": "20px"}),
    ]


def build_earnings_tab():
    controls = html.Div(
        [html.Span("BASIS", className="filters-label"),
         dcc.Checklist(id="r2earn-toggles", options=TOGGLES, value=[], inline=True, className="raroc-toggles")],
        className="filters-row",
    )
    return [controls, html.Div(build_earnings_body(), id="r2earn-body")]


# ============================================================== Methodology

def build_methodology_tab():
    def row(k, v):
        return html.Tr([html.Td(k, className="metric-name"), html.Td(v)])

    decisions = ui.table_card("GOVERNED DECISIONS (Build Plan §0)", html.Table([html.Tbody([
        row("D1 · Capital denominator", "Regulatory: EAD_reg × standardised risk weight × target CET1 "
            f"({r2.TARGET_CET1 * 100:.0f}%). Economic-capital overlay is a future toggle."),
        row("D2 · Short-Term definition", "12-month horizon is the headline; Quick-Close values the early-exit "
            "case (accrued + unamortised upfront + break fee − short-horizon costs)."),
        row("D3 · Revenue scope", "Full relationship (facility + fees + cross-sell + deposit FTP credit); "
            "Credit-only is a toggle."),
        row("D4 · EL basis", "TTC PD for the approved case; PIT PD (IFRS 9) for post-deal actuals — basis flagged."),
        row("Hurdle rate", f"{r2.HURDLE_PCT:.0f}% (group cost of equity)."),
        row("Discount rate", f"{r2.DISCOUNT_PCT:.0f}% (= hurdle) for LTE / EVA."),
        row("Currency / tax", f"AED (USD peg {r2.AED}); pre-tax basis."),
    ])], className="dark-mini-table"))

    formula = ui.table_card("COMPONENT BUILD-UP (per deal, per period)", html.Table([html.Tbody([
        row("Net interest income", "Avg drawn × (applied rate − FTP)"),
        row("+ Fees", "Commitment (undrawn) + amortised upfront + transactional"),
        row("+ Cross-sell", "Ancillary + deposit balance × deposit margin"),
        row("+ Capital benefit", f"Economic capital × {r2.REINVEST_PCT:.0f}% reinvestment"),
        row("− Operating cost", "Unit cost × volume"),
        row("− Expected loss", "12m: PD₁₂ × LGD × EAD · Lifetime: cumulative PD term structure"),
        row("= Risk-adjusted earning", "Numerator of RAROC"),
        row("÷ Allocated capital", "EAD_reg × risk weight × target CET1"),
        row("Short-Term / Quick-Close", "12m earning (or early-exit value) in AED"),
        row("Lifetime Earning", "Discounted risk-adjusted earning over behavioural life"),
        row("EVA", "Earning − (hurdle × capital) — shown beside every RAROC"),
    ])], className="dark-mini-table"))

    note = ui.note_line(
        "Post-deal RAROC re-measures a booked deal at today's funding cost and migrated credit quality against its "
        "approved case — it does not re-decide the deal. Illustrative sample data generated from the live portfolio "
        "borrower universe with a fixed seed. FTP, behavioural-maturity and cost-allocation assumptions are "
        "documented and would be replaced by the bank's own feeds in production."
    )
    return [html.Div([html.Div([decisions], className="split-main"),
                      html.Div([formula], className="split-side")], className="split-grid"), note]
