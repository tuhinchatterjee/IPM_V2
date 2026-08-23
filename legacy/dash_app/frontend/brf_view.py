"""
CBUAE BRF regulatory-return views: prudential-style credit returns built from the
live portfolio dataset - asset quality & provisioning classification, credit by
economic activity, large exposures against the capital base, and the submission
calendar. Figures are shown in AED (USD-peg conversion); capital-linked ratios use
the documented proxies in data_loader.
"""

from datetime import date, timedelta

import plotly.graph_objects as go
from dash import dcc, html

from backend import data_loader as dl
from frontend import ui_common as ui

CLASS_COLORS = {"Normal": "#1fa971", "OLEM": "#f0973e", "Substandard": "#e5484d",
                "Doubtful": "#b52d32", "Loss": "#611418"}


def _quarter_filter_row(dd_id, export_id=None, extra=None):
    children = [
        html.Span("REPORTING PERIOD", className="filters-label"),
        dcc.Dropdown(id=dd_id, options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                     clearable=False, searchable=False, className="filter-dd"),
    ]
    if extra:
        children += extra
    if export_id:
        children.append(html.Button("⬇ Export CSV", id=export_id, className="reset-btn", n_clicks=0))
    return html.Div(children, className="filters-row")


# ------------------------------------------------------------------- overview

def build_brf_overview_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    ov = dl.compute_brf_overview(quarter)

    kpis = [
        ui.kpi_card("Total Credit Exposure", dl.fmt_aed_bn(ov["total_ead"]), "blue",
                    ui.kpi_sub(f"{ov['accounts']} facilities · {ov['customers']} obligors")),
        ui.kpi_card("NPL Ratio", dl.fmt_pct(ov["npl_pct"], 2), "red",
                    ui.kpi_sub(f"classified {ov['classified_pct']:.1f}% of book")),
        ui.kpi_card("Total Provisions", dl.fmt_aed_bn(ov["total_provisions"], 2), "amber",
                    ui.kpi_sub(f"{ov['provision_coverage_npl']:.0f}% specific coverage of NPL")),
        ui.kpi_card("Large Exposures", str(ov["reportable_count"]), "purple",
                    ui.kpi_sub(f"{ov['breach_count']} above 25% cap",
                               "up-bad" if ov["breach_count"] else "neutral")),
    ]

    fig = go.Figure(go.Bar(
        x=[r["class"] for r in ov["class_rows"]],
        y=[r["ead"] * dl.AED_PER_USD / 1000 for r in ov["class_rows"]],
        marker=dict(color=[CLASS_COLORS[r["class"]] for r in ov["class_rows"]]),
        text=[f"{r['pct_of_book']:.1f}%" for r in ov["class_rows"]],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>AED %{y:,.1f}bn<extra></extra>",
    ))
    ui.base_layout(fig, height=250)
    fig.update_layout(bargap=0.45, margin=dict(t=22, b=24, l=40, r=14))
    class_chart = ui.chart_card("EXPOSURE BY CBUAE CLASSIFICATION (AED bn)",
                                dcc.Graph(figure=fig, config={"displayModeBar": False}))

    gp_word = "meets" if ov["general_ok"] else "BREACHES"
    side = [
        ui.metric_card("GENERAL PROVISIONS", dl.fmt_aed_mn(ov["general"]),
                       f"{gp_word} 1.5% of CRWA floor ({dl.fmt_aed_mn(ov['min_general'])})",
                       sub_cls="is-muted" if ov["general_ok"] else "is-red"),
        ui.metric_card("CAPITAL BASE (PROXY)", dl.fmt_aed_bn(ov["capital_base"]),
                       f"{dl.CAPITAL_RATIO * 100:.0f}% of credit-RWA proxy"),
        ui.metric_card("REPORTING BASIS", "AED @ 3.6725",
                       "USD-peg conversion · CBUAE BRF conventions"),
    ]

    insight = (
        f"At {quarter}, classified assets (Substandard/Doubtful/Loss) stand at {ov['classified_pct']:.1f}% of the "
        f"book with an NPL ratio of {ov['npl_pct']:.2f}%. General provisions of {dl.fmt_aed_mn(ov['general'])} "
        f"{'satisfy' if ov['general_ok'] else 'fall short of'} the CBUAE 1.5%-of-CRWA floor "
        f"({dl.fmt_aed_mn(ov['min_general'])}). {ov['reportable_count']} obligors/groups are reportable as large "
        f"exposures, of which {ov['breach_count']} exceed the 25% single-obligor cap — these require a remediation "
        f"plan in the next submission cycle. Capital-linked figures use a documented RWA/capital proxy, not "
        f"reported capital."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div(
            [html.Div([class_chart], className="split-main"),
             html.Div(side, className="split-side")],
            className="split-grid",
        ),
        html.Div(ui.ai_insight_card(insight, title="AI REGULATORY COMMENTARY"), style={"marginTop": "20px"}),
    ]


def build_brf_overview_tab():
    return [_quarter_filter_row("brfov-quarter"),
            html.Div(build_brf_overview_body(dl.DEFAULT_QUARTER), id="brfov-body")]


# --------------------------------------------------------------- asset quality

def build_brf_asset_quality_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    aq = dl.compute_brf_asset_quality(quarter)

    body_rows = []
    for r in aq["rows"]:
        body_rows.append(html.Tr([
            html.Td(html.Span([html.Span(className="kpi-dot",
                                         style={"background": CLASS_COLORS[r["class"]]}),
                               r["class"]], className="class-cell"),
                    className="metric-name"),
            html.Td(str(r["accounts"]), className="num"),
            html.Td(dl.fmt_aed_mn(r["ead"]), className="num"),
            html.Td(f"{r['pct_of_book']:.2f}%", className="num"),
            html.Td(dl.fmt_aed_mn(r["provision"]), className="num"),
            html.Td(f"{r['coverage']:.1f}%", className="num"),
        ], className="is-flagged" if r["class"] in ("Doubtful", "Loss") and r["accounts"] else None))
    total_prov = aq["specific_provisions"] + aq["general_provisions"]
    body_rows.append(html.Tr(
        [html.Td("Total", className="metric-name"), html.Td(str(sum(r['accounts'] for r in aq['rows'])), className="num"),
         html.Td(dl.fmt_aed_mn(aq["total_ead"]), className="num"), html.Td("100.00%", className="num"),
         html.Td(dl.fmt_aed_mn(total_prov), className="num"),
         html.Td(f"{(total_prov / aq['total_ead'] * 100) if aq['total_ead'] else 0:.1f}%", className="num")],
        style={"fontWeight": "800", "background": "var(--teal-light)"},
    ))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Classification"), html.Th("Accounts", className="num"),
                             html.Th("Exposure (AED)", className="num"), html.Th("% of Book", className="num"),
                             html.Th("Provisions (AED)", className="num"), html.Th("Coverage", className="num")])),
         html.Tbody(body_rows)],
        className="dark-mini-table",
    )

    prov_rows = [
        ("Specific provisions (Stage 3 ECL)", aq["specific_provisions"], None),
        ("General provisions (Stage 1+2 ECL)", aq["general_provisions"], None),
        ("Credit RWA (proxy)", aq["crwa"], None),
        ("Min. general required (1.5% CRWA)", aq["min_general"], aq["general_ok"]),
    ]
    prov_table = html.Table(
        [html.Thead(html.Tr([html.Th("Item"), html.Th("AED", className="num"), html.Th("Check")])),
         html.Tbody([
             html.Tr([html.Td(lbl, className="metric-name"),
                      html.Td(dl.fmt_aed_mn(val), className="num"),
                      html.Td(html.Span("PASS" if ok else "FAIL",
                                        className=f"gap-pill {'is-aligned' if ok else ''}")
                              if ok is not None else "—")])
             for lbl, val, ok in prov_rows
         ])],
        className="dark-mini-table",
    )

    insight = (
        f"Mapping IFRS 9 stages to the CBUAE five-bucket scale: Stage 1 → Normal, Stage 2 → OLEM, and Stage 3 "
        f"split by days-past-due into Substandard (<180 DPD), Doubtful (180–365) and Loss (>365). Classified "
        f"exposure is {dl.fmt_aed_mn(aq['classified_ead'])} ({aq['classified_pct']:.1f}% of the book) and specific "
        f"provisions cover {aq['provision_coverage_npl']:.0f}% of NPL exposure. "
        + ("The general-provision floor is met." if aq["general_ok"] else
           "The general-provision floor is NOT met — a top-up is required before submission.")
    )

    return [
        html.Div(
            [html.Div([ui.dark_table_card("CLASSIFICATION OF CREDIT FACILITIES & PROVISIONS", "blue", table)],
                      className="split-main"),
             html.Div([ui.dark_table_card("PROVISIONING ADEQUACY", "amber", prov_table)], className="split-side")],
            className="split-grid",
        ),
        html.Div(ui.ai_insight_card(insight, title="AI REGULATORY COMMENTARY"), style={"marginTop": "20px"}),
    ]


def build_brf_asset_quality_tab():
    return [_quarter_filter_row("brfaq-quarter", export_id="brfaq-export"),
            html.Div(build_brf_asset_quality_body(dl.DEFAULT_QUARTER), id="brfaq-body")]


# ----------------------------------------------------------- economic activity

def build_brf_activity_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    ea = dl.compute_brf_economic_activity(quarter)

    body_rows = [
        html.Tr([
            html.Td(r["activity"], className="metric-name"),
            html.Td(str(r["accounts"]), className="num"),
            html.Td(dl.fmt_aed_mn(r["funded"]), className="num"),
            html.Td(dl.fmt_aed_mn(r["unfunded"]), className="num"),
            html.Td(dl.fmt_aed_mn(r["ead"]), className="num"),
            html.Td(f"{r['pct_of_book']:.1f}%", className="num"),
            html.Td(f"{r['npl_pct']:.1f}%", className=f"num {'is-flagged-text' if r['npl_pct'] > 6 else ''}"),
            html.Td(dl.fmt_aed_mn(r["provision"]), className="num"),
        ])
        for r in ea["rows"]
    ]
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Economic Activity"), html.Th("Accounts", className="num"),
                             html.Th("Funded", className="num"), html.Th("Unfunded", className="num"),
                             html.Th("EAD", className="num"), html.Th("% Book", className="num"),
                             html.Th("NPL %", className="num"), html.Th("Provisions", className="num")])),
         html.Tbody(body_rows)],
        className="borrower-table signals-table",
    )

    rows_rev = list(reversed(ea["rows"]))
    fig = go.Figure(go.Bar(
        x=[r["ead"] * dl.AED_PER_USD / 1000 for r in rows_rev],
        y=[r["activity"] for r in rows_rev],
        orientation="h", marker=dict(color="#16b8a6"),
        hovertemplate="<b>%{y}</b><br>AED %{x:,.1f}bn<extra></extra>",
    ))
    ui.base_layout(fig, height=330)
    fig.update_layout(margin=dict(t=10, b=24, l=10, r=20),
                      yaxis=dict(tickfont=dict(size=11, color="#3c4a5a", family="Inter")))
    chart = ui.chart_card("EAD BY ECONOMIC ACTIVITY (AED bn)",
                          dcc.Graph(figure=fig, config={"displayModeBar": False}))

    top = ea["rows"][0] if ea["rows"] else None
    worst_npl = max(ea["rows"], key=lambda r: r["npl_pct"]) if ea["rows"] else None
    insight = "No activity data at this period." if not top else (
        f"{top['activity']} is the largest reporting line at {top['pct_of_book']:.1f}% of total credit "
        f"({dl.fmt_aed_bn(top['ead'])}). The weakest asset quality sits in {worst_npl['activity']} with an NPL "
        f"ratio of {worst_npl['npl_pct']:.1f}%. Internal sectors are mapped to CBUAE economic-activity categories "
        f"per the documented mapping — verify the mapping against the bank's own BRF chart of accounts before filing."
    )

    return [
        html.Div(
            [html.Div([ui.table_card("CREDIT BY ECONOMIC ACTIVITY — CBUAE CATEGORIES", table)],
                      className="split-main"),
             html.Div([chart], className="split-side")],
            className="split-grid",
        ),
        html.Div(ui.ai_insight_card(insight, title="AI REGULATORY COMMENTARY"), style={"marginTop": "20px"}),
    ]


def build_brf_activity_tab():
    return [_quarter_filter_row("brfea-quarter", export_id="brfea-export"),
            html.Div(build_brf_activity_body(dl.DEFAULT_QUARTER), id="brfea-body")]


# ------------------------------------------------------------ large exposures

def build_brf_large_exp_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    le = dl.compute_brf_large_exposures(quarter)

    kpis = [
        ui.kpi_card("Capital Base (Proxy)", dl.fmt_aed_bn(le["capital_base"]), "blue",
                    ui.kpi_sub(f"{dl.CAPITAL_RATIO * 100:.0f}% of CRWA proxy")),
        ui.kpi_card("Reportable Exposures", str(le["reportable_count"]), "amber",
                    ui.kpi_sub(f"≥ {dl.LARGE_EXPOSURE_REPORT_PCT:.0f}% of capital base")),
        ui.kpi_card("Cap Breaches (>25%)", str(le["breach_count"]), "red",
                    ui.kpi_sub("remediation required" if le["breach_count"] else "none",
                               "up-bad" if le["breach_count"] else "up-good")),
        ui.kpi_card("Aggregate Large Exp.", f"{le['aggregate_pct_capital']:.0f}%", "purple",
                    ui.kpi_sub("of capital base")),
    ]

    body_rows = []
    for i, r in enumerate(le["rows"], 1):
        pct = r["pct_capital"]
        cls = "breach" if r["breach"] else ("warn" if pct >= 20 else "ok")
        body_rows.append(html.Tr([
            html.Td(str(i), className="num"),
            html.Td(r["name"], className="metric-name"),
            html.Td(r["type"]),
            html.Td(dl.fmt_aed_mn(r["ead"]), className="num"),
            html.Td(
                html.Div(
                    [html.Div(html.Div(className=f"util-bar-fill {cls}",
                                       style={"width": f"{min(pct / dl.LARGE_EXPOSURE_LIMIT_PCT * 100, 100)}%"}),
                              className="util-bar-track"),
                     html.Span(f"{pct:.1f}%",
                               className=f"util-bar-value {'is-red' if r['breach'] else ''}")],
                    className="le-bar-cell",
                )
            ),
            html.Td(html.Span("BREACH" if r["breach"] else "Within cap",
                              className=f"gap-pill {'' if r['breach'] else 'is-aligned'}")),
        ], className="is-flagged" if r["breach"] else None))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("#", className="num"), html.Th("Obligor / Group"), html.Th("Type"),
                             html.Th("Exposure (AED)", className="num"),
                             html.Th("% of Capital (25% cap)"), html.Th("Status")])),
         html.Tbody(body_rows)],
        className="borrower-table signals-table",
    )

    worst = le["rows"][0] if le["rows"] else None
    insight = "No reportable large exposures at this period." if not worst else (
        f"{le['reportable_count']} obligors/groups exceed the {dl.LARGE_EXPOSURE_REPORT_PCT:.0f}% reporting "
        f"threshold; the largest, {worst['name']}, stands at {worst['pct_capital']:.1f}% of the capital base. "
        f"{le['breach_count']} exposure(s) breach the {dl.LARGE_EXPOSURE_LIMIT_PCT:.0f}% single-obligor cap and "
        f"must be reduced, collateralised or approved as exempt before the next return. Aggregate large exposures "
        f"equal {le['aggregate_pct_capital']:.0f}% of capital. Note: capital base is a proxy "
        f"({dl.CAPITAL_RATIO * 100:.0f}% of PD-weighted CRWA), so ratios are directional."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        ui.table_card("LARGE EXPOSURES — % OF CAPITAL BASE", table,
                      hint=f"Reportable ≥ {dl.LARGE_EXPOSURE_REPORT_PCT:.0f}% · cap {dl.LARGE_EXPOSURE_LIMIT_PCT:.0f}%"),
        html.Div(ui.ai_insight_card(insight, title="AI REGULATORY COMMENTARY"), style={"marginTop": "20px"}),
    ]


def build_brf_large_exp_tab():
    return [_quarter_filter_row("brfle-quarter", export_id="brfle-export"),
            html.Div(build_brf_large_exp_body(dl.DEFAULT_QUARTER), id="brfle-body")]


# ------------------------------------------------------------------- calendar

BRF_RETURNS = [
    # (return name, frequency, due days after period end)
    ("BRF 1 — Statement of Financial Position", "Monthly", 15),
    ("BRF 2 — Income Statement", "Quarterly", 15),
    ("Classification of Credit Facilities & Provisions", "Quarterly", 21),
    ("Credit by Economic Activity", "Quarterly", 21),
    ("Large Exposures Return", "Quarterly", 21),
    ("Liquidity Return (ELAR / ASRR)", "Monthly", 10),
    ("Capital Adequacy Return (Basel III)", "Quarterly", 30),
    ("Country / Cross-Border Exposure Return", "Quarterly", 30),
]


def _period_ends(today: date, frequency: str):
    """(last completed period end, its label) for a monthly or quarterly return."""
    if frequency == "Monthly":
        first_of_month = today.replace(day=1)
        end = first_of_month - timedelta(days=1)
        return end, end.strftime("%b %Y")
    q_end_month = ((today.month - 1) // 3) * 3  # last completed quarter
    year = today.year
    if q_end_month == 0:
        q_end_month, year = 12, year - 1
    next_month = date(year + (1 if q_end_month == 12 else 0),
                      1 if q_end_month == 12 else q_end_month + 1, 1)
    end = next_month - timedelta(days=1)
    return end, f"Q{(end.month - 1) // 3 + 1} {end.year}"


def build_brf_calendar_body():
    today = date.today()
    rows = []
    for name, freq, lag in BRF_RETURNS:
        period_end, period_label = _period_ends(today, freq)
        due = period_end + timedelta(days=lag)
        days_left = (due - today).days
        if days_left < 0:
            status, cls = "Submitted", "is-aligned"
        elif days_left <= 7:
            status, cls = f"Due in {days_left}d", ""
        else:
            status, cls = "In preparation", "is-prep"
        rows.append(html.Tr([
            html.Td(name, className="metric-name"),
            html.Td(freq),
            html.Td(period_label),
            html.Td(due.strftime("%d-%b-%Y"), className="num"),
            html.Td(html.Span(status, className=f"gap-pill {cls}")),
        ]))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Return"), html.Th("Frequency"), html.Th("Period"),
                             html.Th("Due Date", className="num"), html.Th("Status")])),
         html.Tbody(rows)],
        className="borrower-table signals-table",
    )
    note = ui.note_line(
        "Illustrative submission calendar based on standard CBUAE BRF cadences — align due-day rules with the "
        "bank's supervisory reporting instructions before relying on it."
    )
    return [ui.table_card("CBUAE SUBMISSION CALENDAR", table,
                          hint=f"As of {today.strftime('%d-%b-%Y')}"), note]
