"""
Macroeconomic Outlook views, driven by the IMF World Economic Outlook workbook
uploaded to the project folder (compacted to Macro_GCC_Compact.xlsx). The IMF
path is the Baseline scenario; Upside/Downside apply documented adjustments
around it. Every tab has its own country/region selector AND its own scenario
weight inputs, so setting weights always changes something visible on the same
tab you're looking at - the Outlook charts, the Sector Risk table, and the
Portfolio Health index each show a probability-weighted blend alongside the
per-scenario view.
"""

import plotly.graph_objects as go
from dash import dcc, html

from backend import data_loader as dl
from frontend import ui_common as ui

OUTLOOK_BADGE = {"Deteriorating": ("red", "up-bad"), "Stable": ("blue", "neutral"),
                 "Improving": ("green", "up-good")}
WEIGHTED_COLOR = "#9b6fe0"

KPI_DOTS = {"gdp": "blue", "cpi": "amber", "ca": "teal", "debt": "purple"}
KPI_GOOD_WHEN_UP = {"gdp": True, "cpi": False, "ca": True, "debt": False}


def _scenario_dd(dd_id):
    return dcc.Dropdown(
        id=dd_id,
        options=[{"label": s, "value": s} for s in dl.MACRO_SCENARIOS],
        value="Baseline", clearable=False, searchable=False, className="filter-dd narrow",
    )


def _region_dd(dd_id):
    return dcc.Dropdown(id=dd_id, options=dl.macro_region_options(), value="All",
                        clearable=False, searchable=False, className="filter-dd")


def _weight_input(input_id, label, color, default):
    return html.Div(
        [html.Span(className="legend-swatch", style={"background": color}),
         html.Span(label, className="weight-label"),
         dcc.Input(id=input_id, type="number", min=0, max=100, step=5, value=default,
                   debounce=True, className="weight-input")],
        className="weight-group",
    )


def _weight_controls(base_id, up_id, down_id, note_id):
    """Base/Up/Down weight inputs + a live 'normalized to' note - reused
    identically across the Outlook, Sector Risk and Portfolio Health tabs."""
    return [
        html.Span("SCENARIO WEIGHTS", className="filters-label"),
        _weight_input(base_id, "Base", ui.SCENARIO_COLORS["Baseline"], int(dl.SCENARIO_WEIGHTS["Baseline"] * 100)),
        _weight_input(up_id, "Up", ui.SCENARIO_COLORS["Upside"], int(dl.SCENARIO_WEIGHTS["Upside"] * 100)),
        _weight_input(down_id, "Down", ui.SCENARIO_COLORS["Downside"], int(dl.SCENARIO_WEIGHTS["Downside"] * 100)),
        html.Span(id=note_id, className="weight-note"),
    ]


def _no_macro_data_panel():
    return [html.Div(
        ["No compacted IMF macro dataset found. Drop an IMF WEO country-data export into the project "
         "folder and run data_loader.compact_imf_weo() to generate Macro_GCC_Compact.xlsx."],
        className="placeholder-panel",
    )]


# -------------------------------------------------------------------- outlook

def _variable_chart(var, scenario):
    """IMF history (dark solid) + all three scenario paths (selected one
    emphasised, dash pattern as secondary encoding) + the probability-weighted
    blend (purple dash-dot) built from the current weight inputs."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=var["hist_labels"], y=var["hist"], name="IMF actuals", mode="lines+markers",
        line=dict(color=ui.HIST_COLOR, width=2.5), marker=dict(size=5),
        hovertemplate="<b>%{x}</b><br>%{y:.2f}<extra>IMF actual/estimate</extra>",
    ))
    bridge_x = [var["hist_labels"][-1]] + var["fc_labels"]
    for s in dl.MACRO_SCENARIOS:
        selected = s == scenario
        fig.add_trace(go.Scatter(
            x=bridge_x, y=[var["hist"][-1]] + var["all_fc"][s], name=s, mode="lines",
            line=dict(color=ui.SCENARIO_COLORS[s], width=3 if selected else 1.4,
                      dash=ui.SCENARIO_DASH[s]),
            opacity=1.0 if selected else 0.4,
            hovertemplate="<b>%{x}</b><br>%{y:.2f}<extra>" + s + "</extra>",
        ))
    fig.add_trace(go.Scatter(
        x=bridge_x, y=[var["hist"][-1]] + var["weighted"], name="Weighted", mode="lines",
        line=dict(color=WEIGHTED_COLOR, width=2.6, dash="dashdot"),
        hovertemplate="<b>%{x}</b><br>%{y:.2f}<extra>Weighted blend</extra>",
    ))
    ui.base_layout(fig, height=220, legend=True)
    fig.update_layout(margin=dict(t=8, b=22, l=36, r=10))
    return ui.chart_card(var["label"].upper(), dcc.Graph(figure=fig, config={"displayModeBar": False}))


def build_macro_outlook_body(scenario="Baseline", region="All", weights=None):
    mo = dl.compute_macro_outlook(scenario, region, weights)
    if mo is None:
        return _no_macro_data_panel()
    by_key = {v["key"]: v for v in mo["variables"]}
    w = mo["weights"]

    kpis = []
    for key, v in by_key.items():
        up = v["delta"] >= 0
        cls = ("up-good" if up == KPI_GOOD_WHEN_UP[key] else "up-bad") if abs(v["delta"]) > 0.05 else "neutral"
        kpis.append(ui.kpi_card(
            v["label"], f"{v['latest']:.1f}%", KPI_DOTS.get(key, "blue"),
            ui.kpi_sub(f"{'▲' if up else '▼'} {abs(v['delta']):.1f}pp by {v['fc_labels'][-1]} ({scenario})", cls),
        ))

    charts = [_variable_chart(v, scenario) for v in mo["variables"]]
    place = "the GCC (simple average of the six members)" if region == "All" else region

    gdp = by_key.get("gdp")
    cpi = by_key.get("cpi")
    weights_str = " / ".join(f"{s} {w[s] * 100:.0f}%" for s in dl.MACRO_SCENARIOS)
    bits = [f"IMF WEO data for {place}: "]
    if gdp:
        bits.append(f"real GDP growth of {gdp['latest']:.1f}% in {gdp['hist_labels'][-1]} moves to "
                    f"{gdp['horizon']:.1f}% by {gdp['fc_labels'][-1]} under the {scenario} path, or "
                    f"{gdp['weighted_horizon']:.1f}% on the probability-weighted blend ({weights_str})")
    if cpi:
        bits.append(f"; inflation reaches {cpi['horizon']:.1f}% ({scenario}) vs {cpi['weighted_horizon']:.1f}% weighted")
    bits.append(". The IMF projection is treated as the Baseline; Upside/Downside apply documented "
                "adjustments phased in over the projection years. Adjust the weight inputs above to see the "
                "purple weighted line move on every chart. See Sector Risk and Portfolio Health for how this "
                "path maps onto the portfolio.")
    insight = "".join(bits)

    note = ui.note_line(
        "Source: IMF World Economic Outlook country-data export (uploaded workbook), compacted to "
        "Macro_GCC_Compact.xlsx. Actuals/estimates to 2025; IMF projections from 2026 = Baseline. "
        "Upside/Downside are scenario adjustments around the IMF path, not IMF forecasts."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div(charts, className="macro-charts-grid two-col"),
        html.Div(ui.ai_insight_card(insight, title="AI MACRO COMMENTARY"), style={"marginTop": "20px"}),
        note,
    ]


def build_macro_outlook_tab():
    controls = html.Div(
        [
            html.Span("COUNTRY / REGION", className="filters-label"),
            _region_dd("macro-country"),
            html.Span("SCENARIO", className="filters-label"),
            _scenario_dd("macro-scenario"),
        ] + _weight_controls("macro-w-base", "macro-w-up", "macro-w-down", "macro-w-note")
        + [ui.legend_chips([(s, ui.SCENARIO_COLORS[s]) for s in dl.MACRO_SCENARIOS] + [("Weighted", WEIGHTED_COLOR)])],
        className="filters-row",
    )
    return [controls, html.Div(build_macro_outlook_body(), id="macro-outlook-body")]


# ---------------------------------------------------------------- sector risk

def build_macro_sector_body(scenario="Baseline", region="All", weights=None):
    so = dl.compute_sector_outlook(dl.DEFAULT_QUARTER, scenario, region=region, weights=weights)
    rows = so["rows"]
    w = so["weights"]
    if not rows:
        return [html.Div(f"No portfolio exposure in {region} at the current snapshot.",
                         className="placeholder-panel")]

    body_rows = []
    for r in rows:
        dot, _sub = OUTLOOK_BADGE[r["outlook"]]
        body_rows.append(html.Tr([
            html.Td(r["sector"], className="metric-name"),
            html.Td(dl.fmt_bn(r["ead"], 2), className="num"),
            html.Td(f"{r['pd']:.2f}%", className="num"),
            html.Td(f"{r['pd_proj']:.2f}%", className="num"),
            html.Td(f"{'+' if r['delta_pct'] >= 0 else ''}{r['delta_pct']:.0f}%",
                    className=f"num {'is-flagged-text' if r['delta_pct'] >= 15 else ''}"),
            html.Td(f"{r['weighted_pd_proj']:.2f}%", className="num weighted-col"),
            html.Td(f"{r['beta']:.2f}×", className="num"),
            html.Td(f"{r['stage2_pct']:.1f}%", className="num"),
            html.Td(html.Span([html.Span(className=f"kpi-dot {dot}"), r["outlook"]],
                              className="outlook-badge")),
        ], className="is-flagged" if r["outlook"] == "Deteriorating" else None))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Sector"), html.Th("EAD", className="num"),
                             html.Th("PD Now", className="num"), html.Th("PD +4Q", className="num"),
                             html.Th("Δ PD", className="num"), html.Th("Weighted PD +4Q", className="num weighted-col"),
                             html.Th("Macro β", className="num"),
                             html.Th("Stage 2 %", className="num"), html.Th("Outlook")])),
         html.Tbody(body_rows)],
        className="borrower-table signals-table",
    )

    rows_rev = list(reversed(rows))
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[r["delta_pct"] for r in rows_rev], y=[r["sector"] for r in rows_rev],
        orientation="h", name=scenario,
        marker=dict(color=["#e5484d" if r["delta_pct"] >= 0 else "#1fa971" for r in rows_rev]),
        hovertemplate="<b>%{y}</b><br>" + scenario + " ΔPD: %{x:.0f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[r["weighted_delta_pct"] for r in rows_rev], y=[r["sector"] for r in rows_rev],
        mode="markers", name="Weighted", marker=dict(color=WEIGHTED_COLOR, size=10, symbol="diamond",
                                                       line=dict(width=1.5, color="#fff")),
        hovertemplate="<b>%{y}</b><br>Weighted ΔPD: %{x:.0f}%<extra></extra>",
    ))
    ui.base_layout(fig, height=340, legend=True)
    fig.update_layout(margin=dict(t=10, b=24, l=10, r=20),
                      xaxis=dict(ticksuffix="%", showgrid=True, gridcolor=ui.GRID_COLOR,
                                 zeroline=True, zerolinecolor="#d5dde6"),
                      yaxis=dict(tickfont=dict(size=11, color="#3c4a5a", family="Inter")))
    place = "GCC-wide" if region == "All" else region
    chart = ui.chart_card(f"PROJECTED PD DRIFT — {place.upper()} · BAR = {scenario.upper()}, DIAMOND = WEIGHTED (+4Q)",
                          dcc.Graph(figure=fig, config={"displayModeBar": False}))

    det = [r for r in rows if r["outlook"] == "Deteriorating"]
    det_ead = sum(r["ead"] for r in det)
    total_ead = sum(r["ead"] for r in rows)
    scope = "the whole book" if region == "All" else f"the {region} book ({dl.fmt_bn(total_ead, 2)})"
    weights_str = " / ".join(f"{s} {w[s] * 100:.0f}%" for s in dl.MACRO_SCENARIOS)
    if det:
        insight = (
            f"Under the {scenario} path, {len(det)} sector(s) in {scope} carry a deteriorating outlook — led by "
            f"{det[0]['sector']} where the EAD-weighted PD is projected to rise {det[0]['delta_pct']:.0f}% "
            f"(from {det[0]['pd']:.2f}% to {det[0]['pd_proj']:.2f}%) over four quarters. On your scenario weights "
            f"({weights_str}), that sector's probability-weighted PD moves to {det[0]['weighted_pd_proj']:.2f}% "
            f"instead. Deteriorating sectors hold {dl.fmt_bn(det_ead)} "
            f"({det_ead / total_ead * 100 if total_ead else 0:.0f}% of the slice). Recommend tightening "
            f"origination and refreshing collateral valuations there first."
        )
    else:
        insight = (f"No sector in {scope} shows a deteriorating PD outlook under the {scenario} path; monitor "
                   f"the higher-beta books (Real Estate, Contracting, SME) for signal build-up regardless. "
                   f"The 'Weighted PD +4Q' column shows the same sectors under your {weights_str} weight mix.")

    return [
        html.Div(
            [html.Div([ui.table_card("FORWARD SECTOR RISK MATRIX", table,
                                     hint="Projected PD = current PD × (1 + scenario drift × sector β)")],
                      className="split-main"),
             html.Div([chart], className="split-side")],
            className="split-grid",
        ),
        html.Div(ui.ai_insight_card(insight, title="AI MACRO COMMENTARY"), style={"marginTop": "20px"}),
    ]


def build_macro_sector_tab():
    controls = html.Div(
        [
            html.Span("COUNTRY / REGION", className="filters-label"),
            _region_dd("macrisk-region"),
            html.Span("SCENARIO", className="filters-label"),
            _scenario_dd("macrisk-scenario"),
        ] + _weight_controls("macrisk-w-base", "macrisk-w-up", "macrisk-w-down", "macrisk-w-note"),
        className="filters-row",
    )
    return [controls, html.Div(build_macro_sector_body(), id="macrisk-body")]


# ------------------------------------------------------------ portfolio health

def _projection_chart(ph, metric, title, ysuffix="%"):
    hist_x = [h["label"] for h in ph["hist"]]
    hist_y = [h[metric] for h in ph["hist"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hist_x, y=hist_y, name="Actual", mode="lines+markers",
        line=dict(color=ui.HIST_COLOR, width=2.5), marker=dict(size=5),
        hovertemplate="<b>%{x}</b><br>%{y:.2f}" + ysuffix + "<extra>Actual</extra>",
    ))
    for s in dl.MACRO_SCENARIOS:
        path = ph["projections"][s]
        fig.add_trace(go.Scatter(
            x=[hist_x[-1]] + [p["label"] for p in path],
            y=[hist_y[-1]] + [p[metric] for p in path],
            name=s, mode="lines",
            line=dict(color=ui.SCENARIO_COLORS[s], width=2.2, dash=ui.SCENARIO_DASH[s]),
            hovertemplate="<b>%{x}</b><br>%{y:.2f}" + ysuffix + "<extra>" + s + "</extra>",
        ))
    wpath = ph["weighted_path"]
    fig.add_trace(go.Scatter(
        x=[hist_x[-1]] + [p["label"] for p in wpath],
        y=[hist_y[-1]] + [p[metric] for p in wpath],
        name="Prob-weighted", mode="lines",
        line=dict(color=WEIGHTED_COLOR, width=3.2, dash="dashdot"),
        hovertemplate="<b>%{x}</b><br>%{y:.2f}" + ysuffix + "<extra>Prob-weighted</extra>",
    ))
    ui.base_layout(fig, height=270, ysuffix=ysuffix, legend=True)
    return ui.chart_card(title, dcc.Graph(figure=fig, config={"displayModeBar": False}))


def build_macro_health_body(region="All", weights=None):
    ph = dl.compute_portfolio_health(dl.DEFAULT_QUARTER, region=region, weights=weights)
    cur = ph["current"]
    w = ph["weights"]

    hi = ph["health_now"]
    hi_w = ph["health_weighted"]
    band = ("Strong", "green") if hi >= 75 else ("Sound", "blue") if hi >= 60 else \
           ("Fair", "amber") if hi >= 45 else ("Vulnerable", "red")
    delta = hi_w - hi
    scope = "GCC book" if region == "All" else f"{region} book"
    kpis = [
        ui.kpi_card(f"Health Index — {scope}", f"{hi:.0f} / 100", band[1],
                    ui.kpi_sub(f"{band[0]} · NPL & Stage-2 composite")),
        ui.kpi_card("Weighted +4Q Outlook", f"{hi_w:.0f} / 100",
                    "red" if delta < -3 else ("amber" if delta < 0 else "green"),
                    ui.kpi_sub(f"{'▼' if delta < 0 else '▲'} {abs(delta):.1f} at current weights",
                               "up-bad" if delta < 0 else "up-good")),
        ui.kpi_card("NPL Ratio (Now)", f"{cur['npl']:.2f}%", "amber",
                    ui.kpi_sub(f"weighted +4Q: {ph['weighted_path'][-1]['npl']:.2f}%")),
        ui.kpi_card("Stage 2 Share (Now)", f"{cur['stage2']:.1f}%", "blue",
                    ui.kpi_sub(f"weighted +4Q: {ph['weighted_path'][-1]['stage2']:.1f}%")),
    ]

    npl_chart = _projection_chart(ph, "npl", "NPL RATIO — ACTUAL, SCENARIOS & WEIGHTED PATH (%)")
    stage2_chart = _projection_chart(ph, "stage2", "STAGE 2 SHARE — ACTUAL, SCENARIOS & WEIGHTED PATH (%)")

    weights_str = " / ".join(f"{s} {w[s] * 100:.0f}%" for s in dl.MACRO_SCENARIOS)
    down_end = ph["projections"]["Downside"][-1]
    wend = ph["weighted_path"][-1]
    insight = (
        f"The {scope} enters the horizon at a health index of {hi:.0f}/100 ({band[0]}). At your scenario weights "
        f"({weights_str}), the probability-weighted path takes NPL from {cur['npl']:.2f}% to {wend['npl']:.2f}% "
        f"and Stage 2 from {cur['stage2']:.1f}% to {wend['stage2']:.1f}% in four quarters, moving the index to "
        f"{hi_w:.0f}. The binding path remains the downside (NPL {down_end['npl']:.2f}%, Stage 2 "
        f"{down_end['stage2']:.1f}%) — shift weight toward Downside to see how quickly provisioning overlays "
        f"and watchlist capacity would need to scale."
    )

    note = ui.note_line(
        "Projections interpolate from the slice's real ratios to scenario endpoints; the downside applies the "
        "Scenario Lab stress-engine uplift (+300bps / −20% CRE). Weights are normalized to 100%. Illustrative, "
        "not a calibrated forecast."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div(
            [html.Div([npl_chart], className="split-main"),
             html.Div([stage2_chart], className="split-side")],
            className="split-grid",
        ),
        html.Div(ui.ai_insight_card(insight, title="AI MACRO COMMENTARY"), style={"marginTop": "20px"}),
        note,
    ]


def build_macro_health_tab():
    controls = html.Div(
        [
            html.Span("COUNTRY / REGION", className="filters-label"),
            _region_dd("machealth-region"),
        ] + _weight_controls("machealth-w-base", "machealth-w-up", "machealth-w-down", "machealth-w-note"),
        className="filters-row",
    )
    return [controls, html.Div(build_macro_health_body(), id="machealth-body")]
