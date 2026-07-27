"""
Post-Deal RAROC view: an ex-post view of each live deal's risk-adjusted return,
showing how market-rate moves and credit migration since booking have shifted the
economics, and rolling up to two earning figures — Short-Term / Quick-Close and
Lifetime. Data + methodology live in raroc_data.py.
"""

import plotly.graph_objects as go
from dash import dcc, html

from backend import data_loader as dl
from backend import raroc_data as rd
from frontend import ui_common as ui

VIEW_OPTIONS = ["All deals", "Below hurdle", "Fixed-rate", "Floating-rate"]


def _mn(v):
    return f"${v:,.1f}m"


def _delta_span(value, unit="", good_when_up=True, decimals=1):
    up = value >= 0
    cls = ("up-good" if up == good_when_up else "up-bad") if abs(value) > 1e-9 else "neutral"
    arrow = "▲" if up else "▼"
    return html.Span(f"{arrow} {abs(value):.{decimals}f}{unit}", className=f"raroc-delta {cls}")


def _filter_deals(deals, view):
    if view == "Below hurdle":
        return [d for d in deals if not d["above_hurdle"]]
    if view == "Fixed-rate":
        return [d for d in deals if d["rate_type"] == "Fixed"]
    if view == "Floating-rate":
        return [d for d in deals if d["rate_type"] == "Floating"]
    return deals


# --------------------------------------------------------------------- table

def _deals_table(deals):
    rows = []
    for d in deals:
        rows.append(html.Tr([
            html.Td([html.Div(d["borrower"], className="metric-name"),
                     html.Div(f"{d['deal_id']} · {d['sector']}", className="raroc-subtext")]),
            html.Td(d["rate_type"], className=f"raroc-type {'is-fixed' if d['rate_type'] == 'Fixed' else ''}"),
            html.Td(dl.fmt_bn(d["ead"], 2), className="num"),
            html.Td(f"{'+' if d['base_change_bps'] >= 0 else ''}{d['base_change_bps']:.0f}", className="num"),
            html.Td([f"{d['cur_nim']:.2f}% ", _delta_span(d["nim_change"], "pp", good_when_up=True, decimals=2)],
                    className="num"),
            html.Td([f"{d['cur_raroc']:.1f}% ", _delta_span(d["raroc_change"], "pp", good_when_up=True)],
                    className="num"),
            html.Td(_mn(d["short_term_earning"]), className="num"),
            html.Td(_mn(d["lifetime_earning"]), className="num raroc-lifetime"),
            html.Td(html.Span("Above" if d["above_hurdle"] else "Below",
                              className=f"gap-pill {'is-aligned' if d['above_hurdle'] else ''}")),
        ], className="is-flagged" if not d["above_hurdle"] else None))
    return html.Table(
        [html.Thead(html.Tr([
            html.Th("Deal / Borrower"), html.Th("Type"), html.Th("EAD", className="num"),
            html.Th("Δ Base (bps)", className="num"), html.Th("NIM (now)", className="num"),
            html.Th(f"Post-Deal RAROC (hurdle {rd.HURDLE_PCT:.0f}%)", className="num"),
            html.Th("Short-Term", className="num"), html.Th("Lifetime", className="num"),
            html.Th("Status")])),
         html.Tbody(rows)],
        className="borrower-table signals-table",
    )


# --------------------------------------------------------------------- chart

def _drift_chart(deals):
    """Origination RAROC (x) vs post-deal RAROC (y). Points below the diagonal have
    deteriorated since booking; points below the horizontal hurdle line no longer
    clear the hurdle. Bubble size ~ EAD."""
    fig = go.Figure()
    above = [d for d in deals if d["above_hurdle"]]
    below = [d for d in deals if not d["above_hurdle"]]
    for grp, color, name in [(above, "#1fa971", "Above hurdle"), (below, "#e5484d", "Below hurdle")]:
        if not grp:
            continue
        fig.add_trace(go.Scatter(
            x=[d["orig_raroc"] for d in grp], y=[d["cur_raroc"] for d in grp],
            mode="markers", name=name,
            marker=dict(color=color, opacity=0.75, line=dict(width=1, color="#fff"),
                        size=[max(8, min(34, d["ead"] / 60)) for d in grp]),
            customdata=[[d["borrower"], d["rate_type"]] for d in grp],
            hovertemplate="<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
                          "Orig RAROC: %{x:.1f}%<br>Post-deal RAROC: %{y:.1f}%<extra></extra>",
        ))
    lo, hi = -20, 70
    fig.add_trace(go.Scatter(x=[lo, hi], y=[lo, hi], mode="lines", name="No change",
                             line=dict(color="#c4cdd8", width=1, dash="dot"), hoverinfo="skip",
                             showlegend=False))
    fig.add_hline(y=rd.HURDLE_PCT, line_dash="dash", line_color="#93a8bd",
                  annotation_text=f"Hurdle {rd.HURDLE_PCT:.0f}%", annotation_font_size=10)
    ui.base_layout(fig, height=360, legend=True)
    fig.update_layout(margin=dict(t=20, b=40, l=48, r=16),
                      xaxis=dict(title="Origination RAROC (%)", range=[lo, hi], ticksuffix="%",
                                 showgrid=True, gridcolor=ui.GRID_COLOR),
                      yaxis=dict(title="Post-Deal RAROC (%)", range=[lo, hi], ticksuffix="%",
                                 showgrid=True, gridcolor=ui.GRID_COLOR))
    return ui.chart_card("RAROC DRIFT — ORIGINATION vs POST-DEAL (bubble = EAD)",
                         dcc.Graph(figure=fig, config={"displayModeBar": False}))


# ---------------------------------------------------------------------- body

def build_post_deal_raroc_body(view="All deals"):
    summary = rd.compute_post_deal_summary()
    deals = summary["deals"]
    shown = _filter_deals(deals, view)

    port = summary["portfolio_raroc"]
    kpis = [
        ui.kpi_card("Portfolio Post-Deal RAROC", f"{port:.1f}%",
                    "green" if port >= summary["hurdle"] else "red",
                    ui.kpi_sub(f"vs {summary['hurdle']:.0f}% hurdle",
                               "up-good" if port >= summary["hurdle"] else "up-bad")),
        ui.kpi_card("Lifetime Earning", _mn(summary["lifetime_total"]), "blue",
                    ui.kpi_sub("risk-adjusted, to maturity")),
        ui.kpi_card("Short-Term / Quick-Close", _mn(summary["short_term_total"]), "teal",
                    ui.kpi_sub("next ~12m + unamortised fees")),
        ui.kpi_card("Deals Below Hurdle", str(summary["below_hurdle_count"]), "amber",
                    ui.kpi_sub(f"{dl.fmt_bn(summary['below_hurdle_ead'], 1)} EAD",
                               "up-bad" if summary["below_hurdle_count"] else "neutral")),
    ]

    insight = (
        f"Across {summary['n']} performing deals, the book earns a post-deal RAROC of {port:.1f}% "
        f"against a {summary['hurdle']:.0f}% hurdle. {summary['below_hurdle_count']} deals no longer clear the "
        f"hurdle — driven by {summary['rate_compressed_count']} fixed-rate facilities whose margin compressed as "
        f"market funding costs rose since booking, and {summary['downgraded_count']} names that were downgraded "
        f"(lifting expected loss and the capital they consume). Total lifetime risk-adjusted earning is "
        f"{_mn(summary['lifetime_total'])}, of which {_mn(summary['short_term_total'])} is realisable in the near "
        f"term (next ~12 months plus unamortised fees). Recommend repricing or hedging the compressed fixed-rate "
        f"names at next review, and prioritising remediation on the below-hurdle deals with the largest EAD."
    )

    note = ui.note_line(
        "Post-deal (ex-post) RAROC = risk-adjusted net income ÷ economic capital, recomputed at today's funding "
        "cost and migrated credit quality. Floating-rate assets reprice with the funding index (NIM stable under "
        "parallel rate moves); fixed-rate assets bear the rate risk. Deal book is generated from the live "
        "portfolio's largest performing facilities with a fixed seed — illustrative sample data (export above)."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div(
            [html.Div([ui.table_card(f"POST-DEAL RAROC BY FACILITY — {view.upper()}", _deals_table(shown),
                                     hint=f"{len(shown)} of {summary['n']} deals")], className="split-main"),
             html.Div([_drift_chart(deals)], className="split-side")],
            className="split-grid",
        ),
        html.Div(ui.ai_insight_card(insight, title="AI RAROC COMMENTARY"), style={"marginTop": "20px"}),
        note,
    ]


def build_post_deal_raroc_tab():
    controls = html.Div(
        [
            html.Span("VIEW", className="filters-label"),
            dcc.Dropdown(id="raroc-view", options=[{"label": v, "value": v} for v in VIEW_OPTIONS],
                         value="All deals", clearable=False, searchable=False, className="filter-dd"),
            html.Button("⬇ Export sample dataset (CSV)", id="raroc-export", className="reset-btn", n_clicks=0),
        ],
        className="filters-row",
    )
    return [controls, html.Div(build_post_deal_raroc_body(), id="raroc-body")]
