"""
Shared UI building blocks for the newer IPM pages (Data Hub, BRF Returns, Macro
Outlook). Mirrors the visual conventions already established in app.py (kpi-card,
table-card, dark-mini-table, ai-insight-card CSS classes) without importing
app.py, which would be circular.
"""

from dash import html

CHART_FONT = dict(family="Inter", size=11, color="#3c4a5a")
GRID_COLOR = "#eef1f6"
HOVERLABEL = dict(bgcolor="#0b2436", font_color="#fff", font_size=12, font_family="Inter")

# Scenario identity is polarity-coded (good / neutral / bad) with a dash pattern as
# secondary encoding so the lines stay distinguishable without color.
SCENARIO_COLORS = {"Baseline": "#3e7bfa", "Upside": "#1fa971", "Downside": "#e5484d"}
SCENARIO_DASH = {"Baseline": "solid", "Upside": "dot", "Downside": "dash"}
HIST_COLOR = "#16232f"


def page_header(title):
    return html.Div(
        [
            html.H1(title, className="page-title"),
            html.Div(
                [
                    html.Div([html.Span(className="live-dot"), "LIVE SYSTEM VIEW"], className="live-badge"),
                    html.Div(id="live-updated-text", className="live-updated"),
                ]
            ),
        ],
        className="page-header-row",
    )


def kpi_card(label, value, dot_color, sub):
    return html.Div(
        [
            html.Div([label, html.Span(className=f"kpi-dot {dot_color}")], className="kpi-label"),
            html.Div(value, className="kpi-value"),
            sub,
        ],
        className="kpi-card",
    )


def kpi_sub(text, cls="neutral"):
    return html.Div(text, className=f"kpi-sub {cls}")


def metric_card(label, value, sub, value_cls="", sub_cls="is-muted"):
    return html.Div(
        [
            html.Div(label, className="metric-card-label"),
            html.Div(value, className=f"metric-card-value {value_cls}".strip()),
            html.Div(sub, className=f"metric-card-sub {sub_cls}".strip()),
        ],
        className="metric-card",
    )


def ai_insight_card(text, title="AI INSIGHT"):
    return html.Div(
        [
            html.Div([html.Span(className="kpi-dot teal"), html.Span(title, className="ai-insight-title")],
                     className="ai-insight-header"),
            html.Div(
                [html.Div("AI", className="ai-insight-icon"), html.Div(text, className="ai-insight-text")],
                className="ai-insight-body",
            ),
        ],
        className="ai-insight-card",
    )


def dark_table_card(title, dot_color, table):
    return html.Div(
        [html.Div([html.Span(className=f"kpi-dot {dot_color}"), title], className="dark-table-title"), table],
        className="dark-table-card",
    )


def table_card(title, table, hint=None):
    header_children = [html.Span(title, className="table-title")]
    if hint:
        header_children.append(html.Span(hint, className="table-hint"))
    return html.Div(
        [html.Div(header_children, className="table-card-header"), table],
        className="table-card",
    )


def chart_card(title, graph):
    return html.Div([html.Div(title, className="chart-title"), graph], className="chart-card")


def base_layout(fig, height, ysuffix="", legend=False):
    fig.update_layout(
        margin=dict(t=10, b=24, l=40, r=14),
        height=height,
        xaxis=dict(showgrid=False, tickfont=dict(size=10.5, color="#6c7a8c", family="Inter")),
        yaxis=dict(showgrid=True, gridcolor=GRID_COLOR, zeroline=False, ticksuffix=ysuffix,
                   tickfont=dict(size=10.5, color="#6c7a8c", family="Inter")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=CHART_FONT,
        hoverlabel=HOVERLABEL,
        showlegend=legend,
    )
    if legend:
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                                      font=dict(size=11)))
    return fig


def legend_chips(items):
    """HTML swatch legend row: items = [(label, color)]."""
    return html.Div(
        [
            html.Span([html.Span(className="legend-swatch", style={"background": color}), label],
                      className="legend-chip")
            for label, color in items
        ],
        className="legend-chip-row",
    )


def note_line(text):
    return html.Div(text, className="module-note")
