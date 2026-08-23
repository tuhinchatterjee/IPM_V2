"""
The cockpit Health Index drill-down — three screens, one path.

  Level 1  Health Index      one composite score + the three cards behind it
  Level 2  Sector matrix     every portfolio on ten columns + peer benchmark
  Level 3  Obligor actions   the names inside the deteriorating portfolios

Navigation is a single `cockpit-drill` store: every clickable element carries an
id of {"type": "cockpit-drill", "level": n, "sector": s}, so one callback serves
all three levels and the back links are the same component as the forward ones.

Visual conventions follow the rest of the app (kpi-card, table-card,
dark-table-card, sev-pill). Numbers are formatted through data_loader's helpers
so a figure shown here is the same string it is anywhere else in the tool.
"""

import plotly.graph_objects as go
from dash import dcc, html

import backend.cockpit_data as cd
import backend.data_loader as dl

TREND_GLYPH = {"Down": "▼", "Up": "▲", "Watch": "◆", "Stable": "→"}
TREND_CLASS = {"Down": "is-down", "Up": "is-up", "Watch": "is-watch", "Stable": "is-stable"}
DIRECTION_GLYPH = {"up": "▲", "down": "▼", "flat": "—"}


def drill_id(level: int, sector: str | None = None) -> dict:
    return {"type": "cockpit-drill", "level": level, "sector": sector or "__all__"}


def _pct(value, places=1, dash="—"):
    return f"{value:.{places}f}%" if value is not None else dash


def _money(ead_mn: float) -> str:
    """Billions for the big numbers, millions below the point where a 2-dp billions
    figure would round to $0.00bn and tell the reader nothing."""
    return dl.fmt_bn(ead_mn, 2) if ead_mn >= 100 else dl.fmt_mn(ead_mn)


# ============================================================ level 1: health

def _index_sparkline(history) -> html.Div:
    """Eight quarters of the composite score as a bare line.

    A sparkline, not a chart: it carries direction and volatility only, so it has
    no axis, no gridlines and no legend — the current value is already shown at
    full size beside it. Plotly rather than inline SVG because Dash strips raw
    markup passed through dcc.Markdown.
    """
    if len(history) < 2:
        return html.Div(className="hidx-spark")

    fig = go.Figure(go.Scatter(
        x=[h["label"] for h in history],
        y=[h["score"] for h in history],
        mode="lines+markers",
        line=dict(color="#f0973e", width=2, shape="spline", smoothing=0.6),
        marker=dict(size=4, color="#f0973e"),
        hovertemplate="%{x}<br>index %{y:.0f}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(t=4, b=4, l=4, r=4), height=52,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(visible=False, fixedrange=True),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        hoverlabel=dict(bgcolor="#0b2436", font_color="#fff", font_size=11, font_family="Inter"),
    )
    return html.Div(
        dcc.Graph(figure=fig, config={"displayModeBar": False, "staticPlot": False},
                  className="spark-graph"),
        className="hidx-spark",
    )


def _band_meter(score: float, band: dict) -> html.Div:
    """The health band with a marker at the current score — a one-dimensional
    position, so a segmented meter rather than a chart."""
    segments = [
        html.Div(b["label"], className=f"band-seg band-{b['tone']}",
                 style={"flex": f"{b['hi'] - b['lo']}"})
        for b in cd.HEALTH_BANDS
    ]
    return html.Div([
        html.Div("HEALTH BAND", className="hidx-sub-label"),
        html.Div(
            html.Div("▼", className="band-marker", style={"left": f"{max(0, min(100, score)):.1f}%"}),
            className="band-marker-track",
        ),
        html.Div(segments, className="band-track"),
        html.Div([html.Span(b["label"], className="band-tick") for b in cd.HEALTH_BANDS],
                 className="band-tick-row"),
    ], className="hidx-band", title=f"Score {score:.0f} — {band['label']}")


def _delta_chip(value, label):
    """Movement in the health index. The index is a score, so a RISE is good —
    the opposite of every ratio on the cards below it."""
    if value is None:
        return None
    up = value >= 0
    return html.Span(
        [html.Span("▲" if up else "▼"), f" {abs(value):.0f} {label}"],
        className=f"hidx-delta {'is-good' if up else 'is-bad'}",
    )


def build_health_index_card(data) -> html.Div:
    score, band = data["score"], data["band"]
    deltas = [c for c in (_delta_chip(data["qoq"], "QoQ"), _delta_chip(data["yoy"], "YoY")) if c]
    return html.Div([
        html.Div([
            html.Div("AI HEALTH INDEX", className="hidx-title"),
            html.Div("ƒ score formula", className="hidx-formula-pill",
                     title="score = 100 − NPL% × 5 − Stage 2% × 1.5, clipped to 0-100"),
        ], className="hidx-head"),
        html.Div([
            html.Span(f"{score:.0f}", className=f"hidx-score tone-{band['tone']}"),
            html.Span("/100", className="hidx-outof"),
        ], className="hidx-score-row"),
        html.Div([
            html.Span(f"● {band['label']}", className=f"hidx-band-pill tone-{band['tone']}"),
            html.Div(deltas, className="hidx-delta-row"),
        ], className="hidx-band-row"),
    ], className="hidx-card")


def build_ai_read_card(data) -> html.Div:
    return html.Div([
        html.Div("AI READ", className="hidx-sub-label"),
        html.Div(data["ai_read"], className="hidx-read-text"),
    ], className="hidx-read")


def _metric_row(label, value, tone="", delta_glyph="", delta_tone="", sub=""):
    return html.Div([
        html.Span(className=f"kpi-dot {tone}") if tone else None,
        html.Span(label, className="ph-metric-label"),
        html.Span(value, className="ph-metric-value"),
        html.Span(delta_glyph, className=f"ph-metric-delta {delta_tone}") if delta_glyph else None,
        html.Span(sub, className="ph-metric-sub") if sub else None,
    ], className="ph-metric-row")


def build_portfolio_health_card(data) -> html.Div:
    aq = data["asset_quality"]

    def arrow(value, good_when_negative=True):
        if value is None:
            return "", ""
        up = value >= 0
        good = (not up) if good_when_negative else up
        return ("▲" if up else "▼"), ("is-good" if good else "is-bad")

    npl_glyph, npl_tone = arrow(aq["npl_delta"])
    s2_glyph, s2_tone = arrow(aq["stage2_drift"])

    rows = [
        html.Div("ASSET QUALITY · vs recent Qs", className="ph-group-label"),
        _metric_row("NPL ratio", _pct(aq["npl_ratio"]), "amber", npl_glyph, npl_tone),
        _metric_row("New defaults", dl.fmt_mn(aq["new_defaults"]) if aq["new_defaults"] is not None else "—",
                    "amber"),
        _metric_row("Stage 2 drift",
                    (f"{'+' if (aq['stage2_drift'] or 0) >= 0 else ''}{dl.fmt_bn(aq['stage2_drift'], 1)}"
                     if aq["stage2_drift"] is not None else "—"), "amber", s2_glyph, s2_tone),
        # No arrow: there is no prior-period cure rate to compare against, and a
        # fixed threshold would be an invented benchmark.
        _metric_row("Cure rate", _pct(aq["cure_rate"], 0), "amber"),
        html.Div(className="ph-divider"),
        html.Div("ACTUAL vs PLAN", className="ph-group-label"),
    ]

    for p in data["plan"]:
        if p["kind"] == "pct":
            actual, plan = _pct(p["actual"]), _pct(p["plan"])
        elif p["kind"] == "bn":
            actual, plan = dl.fmt_bn(p["actual"], 1), dl.fmt_bn(p["plan"], 1)
        else:
            actual, plan = dl.fmt_mn(p["actual"]), dl.fmt_mn(p["plan"])
        ahead = (p["actual"] <= p["plan"]) if p["better"] == "low" else (p["actual"] >= p["plan"])
        rows.append(_metric_row(p["label"], actual, "amber", sub=f"/ {plan}",
                                delta_glyph="", delta_tone="is-good" if ahead else "is-bad"))

    return html.Div([
        html.Div([
            html.Span("PORTFOLIO HEALTH", className="ph-card-title"),
            html.Span(f"● {data['band']['label']}", className=f"ph-card-pill tone-{data['portfolio_tone']}"),
        ], className="ph-card-head amber-head"),
        html.Div(rows, className="ph-card-body"),
        html.Div("Plan is illustrative: the position four quarters ago moved by the stated annual target.",
                 className="ph-card-foot"),
    ], className="ph-card")


def build_appetite_card(data) -> html.Div:
    breaches = data["appetite_breaches"]
    rows = []
    for r in data["appetite"]:
        rows.append(html.Div([
            html.Div([
                html.Span(className=f"kpi-dot {r['tone']}"),
                html.Span(r["label"], className="ph-metric-label"),
                html.Span(f"{r['value']:.1f}{r['unit']}", className="ph-metric-value"),
            ], className="ph-metric-row"),
            html.Div([
                html.Span(r["appetite_text"], className="appetite-limit"),
                html.Span(" · "),
                html.Span(r["status"], className=f"appetite-status tone-{r['tone']}"),
            ], className="appetite-sub"),
        ], className="appetite-row"))

    return html.Div([
        html.Div([
            html.Span("RISK APPETITE LIMITS", className="ph-card-title"),
            html.Span(f"● {breaches} BREACH" if breaches else "● WITHIN",
                      className=f"ph-card-pill tone-{'red' if breaches else 'green'}"),
        ], className="ph-card-head red-head" if breaches else "ph-card-head green-head"),
        html.Div([html.Div("important ratios vs board appetite", className="ph-group-label is-italic"),
                  *rows], className="ph-card-body"),
    ], className="ph-card")


def build_macro_card(data) -> html.Div:
    rows = []
    for m in data["macro"]:
        if not m["available"]:
            continue
        value = f"{m['unit']}{m['value']:,.0f}" if m["unit"] == "$" else f"{m['value']:,.1f}{m['unit']}"
        rows.append(html.Div([
            html.Span(className=f"kpi-dot {m['tone']}"),
            html.Span([
                m["label"],
                html.Span("ⓘ", className="macro-indicative", title=f"Indicative — {m['source']}")
                if m["indicative"] else None,
            ], className="ph-metric-label"),
            html.Span(value, className="ph-metric-value"),
            html.Span(DIRECTION_GLYPH.get(m["direction"], ""),
                      className=f"ph-metric-delta tone-{m['tone']}"),
        ], className="ph-metric-row"))

    fwd = data.get("forward")
    fwd_strip = None
    if fwd:
        fwd_strip = html.Div([
            html.Span(f"▶ {fwd['label']}", className="fwd-tag"),
            html.Div([
                html.Span([f"{i['label']} ", html.B(f"{i['now']}→{i['then']}")], className="fwd-item")
                for i in fwd["items"]
            ], className="fwd-items"),
        ], className="fwd-strip")

    return html.Div([
        html.Div([
            html.Span("MACRO ENVIRONMENT", className="ph-card-title"),
            html.Span(f"● {data['macro_tone'].upper()}", className=f"ph-card-pill tone-{data['macro_tone']}"),
        ], className="ph-card-head amber-head"),
        html.Div([
            html.Div("Higher-for-longer rates and softening real estate are the key headwinds; "
                     "oil range-bound.", className="macro-lede"),
            html.Div("KEY MACRO SIGNALS", className="ph-group-label"),
            *rows,
        ], className="ph-card-body"),
        fwd_strip,
    ], className="ph-card")


def build_health_screen(quarter=None) -> list:
    """Level 1 — the landing screen."""
    data = cd.compute_health_screen(quarter)
    return [
        html.Div([
            build_health_index_card(data),
            html.Div([
                _band_meter(data["score"], data["band"]),
                html.Div("INDEX · LAST 8 QUARTERS", className="hidx-sub-label",
                         style={"marginTop": "14px"}),
                _index_sparkline(data["history"]),
            ], className="hidx-mid"),
            build_ai_read_card(data),
        ], className="hidx-top-grid"),

        html.Div([
            build_portfolio_health_card(data),
            build_appetite_card(data),
            build_macro_card(data),
        ], className="hidx-card-grid"),

        html.Div(
            html.Button(["Sector & segment detail", html.Span("›", className="drill-chev")],
                        id=drill_id(2), n_clicks=0, className="drill-next-btn"),
            className="drill-next-row",
        ),
    ]


# ====================================================== level 2: sector matrix

def _bench_bar(metric) -> html.Div:
    """Quartile position on a four-segment track: an ordinal position, not a
    magnitude, so exactly one segment lights rather than a bar growing from zero."""
    filled = min(3, max(0, int(metric["position"] * 4)))
    tone = "is-good" if metric["ahead"] else "is-bad"
    segs = []
    for i in range(4):
        cls = "bench-seg is-on " + tone if i == filled else "bench-seg"
        segs.append(html.Div(className=cls))
    return html.Div(segs, className="bench-track")


def build_benchmark_panel(bench) -> html.Div:
    rows = []
    for m in bench["metrics"]:
        value = f"{m['value']:,.1f}{m['unit']}"
        rows.append(html.Div([
            html.Div([
                html.Span(m["label"], className="bench-label"),
                html.Span(value, className="bench-value"),
                html.Span("ⓘ", className="bench-info", title=f"Peer median {m['median']:g}{m['unit']} "
                                                             f"across {bench['peer_count']} listed banks"),
            ], className="bench-head"),
            _bench_bar(m),
            html.Div([
                html.Span(m["quartile"], className=f"bench-quartile {'is-good' if m['ahead'] else 'is-bad'}"),
                html.Span(f" · med {m['median']:g}{m['unit']}", className="bench-median"),
            ], className="bench-foot"),
        ], className="bench-row"))

    return html.Div([
        html.Div([html.Span(className="kpi-dot green"), "INDUSTRY BENCHMARK — OMAN"],
                 className="dark-table-title"),
        html.Div(f"the bank vs {bench['peer_count']} listed Omani banks", className="bench-lede"),
        html.Div(rows, className="bench-body"),
        html.Div(f"ⓘ Sources: {bench['sources']}. Peer medians are indicative reference data, "
                 f"not computed from the ledger.", className="bench-sources"),
    ], className="dark-table-card bench-card")


def build_sector_matrix_screen(quarter=None) -> list:
    """Level 2 — every portfolio on the columns a committee reads."""
    data = cd.compute_sector_matrix(quarter)

    header = html.Thead(html.Tr([
        html.Th("Sector / Segment"), html.Th("Exposure", className="num"), html.Th("Grw", className="num"),
        html.Th("NPL", className="num"), html.Th("St2", className="num"), html.Th("30+", className="num"),
        html.Th("90+", className="num"), html.Th("ECL", className="num"), html.Th("CoR", className="num"),
        html.Th("AI Score", className="num"), html.Th("Trend", className="num"),
    ]))

    body_rows = []
    for r in data["rows"]:
        body_rows.append(html.Tr([
            html.Td(html.Div([
                html.Span(className=f"sector-tick tone-{r['ai_tone']}"),
                html.Span(r["sector"], className="sector-name"),
            ], className="sector-cell")),
            html.Td(dl.fmt_bn(r["ead"], 1), className="num"),
            html.Td(_pct(r["growth"]), className="num"),
            html.Td(_pct(r["npl"]), className="num"),
            html.Td(_pct(r["stage2"]), className="num"),
            html.Td(_pct(r["dpd30"]), className="num"),
            html.Td(_pct(r["dpd90"]), className="num"),
            html.Td(_pct(r["ecl_ratio"]), className="num"),
            html.Td(_pct(r["cost_of_risk"], 2), className="num"),
            html.Td(html.Span(f"{r['ai_score']:.0f}", className=f"ai-chip tone-{r['ai_tone']}"),
                    className="num"),
            html.Td(html.Span(TREND_GLYPH.get(r["trend"], "→"),
                              className=f"trend-glyph {TREND_CLASS.get(r['trend'], '')}"),
                    className="num"),
        ],
            id=drill_id(3, r["sector"]), n_clicks=0,
            className="matrix-row is-clickable",
            title=f"Open {r['sector']} obligors",
        ))

    table = html.Table([header, html.Tbody(body_rows)], className="borrower-table matrix-table")

    return [
        html.Div([
            html.Button([html.Span("‹", className="drill-chev"), "Health Index"],
                        id=drill_id(1), n_clicks=0, className="drill-back-btn"),
            html.Span(f"{len(data['rows'])} portfolios · {dl.fmt_bn(data['total_ead'], 1)} exposure · "
                      f"worst AI score first", className="drill-crumb-note"),
        ], className="drill-crumb-row"),

        html.Div([
            html.Div([
                html.Div(table, className="matrix-table-wrap"),
                html.Div(["▸ ", data["insight"]], className="matrix-insight"),
            ], className="matrix-main"),
            build_benchmark_panel(data["benchmark"]),
        ], className="matrix-grid"),

        html.Div(
            html.Button(["Obligor detail — deteriorating portfolios", html.Span("›", className="drill-chev")],
                        id=drill_id(3), n_clicks=0, className="drill-next-btn"),
            className="drill-next-row",
        ),
    ]


# ==================================================== level 3: obligor actions

def _obligor_card(o, action_menu) -> html.Div:
    return html.Div([
        html.Div([
            html.Span(o["borrower"], className="ob-name"),
            html.Span(_money(o["ead"]), className="ob-ead"),
        ], className="ob-head"),
        html.Div([
            html.Span(o["rating"], className="ob-rating"),
            html.Span(TREND_GLYPH.get(o["trend"], "→"),
                      className=f"trend-glyph {TREND_CLASS.get(o['trend'], '')}"),
            html.Span(o["trigger"], className="ob-trigger", title=o["reason"]),
        ], className="ob-meta"),
        dcc.Dropdown(
            options=[{"label": a, "value": a} for a in action_menu],
            value=o["action"], clearable=False, searchable=False,
            id={"type": "cockpit-action", "customer": o["customer_id"]},
            className="ob-action-dd",
        ),
    ], className="ob-card")


def build_obligor_screen(quarter=None, sector=None) -> list:
    """Level 3 — the names inside the deteriorating portfolios.

    Reached either from the drill button (all deteriorating portfolios side by
    side) or by clicking one sector row (that sector alone).
    """
    sectors = [sector] if sector and sector != "__all__" else None
    data = cd.compute_obligor_screen(quarter, sectors=sectors)

    if not data["columns"]:
        body = html.Div("No obligors flagged in the selected portfolios this quarter.",
                        className="placeholder-panel")
    else:
        body = html.Div([
            html.Div([
                html.Div([
                    html.Span(c["sector"], className="obcol-title"),
                    html.Span(f"AI SCORE {c['ai_score']:.0f}",
                              className=f"obcol-score tone-{c['ai_tone']}"),
                ], className="obcol-head"),
                html.Div([_obligor_card(o, data["action_menu"]) for o in c["obligors"]],
                         className="obcol-body"),
                html.Div(f"{c['obligor_count']} obligors · {dl.fmt_bn(c['ead'], 1)} exposure",
                         className="obcol-foot"),
            ], className="ob-column")
            for c in data["columns"]
        ], className="ob-grid")

    scope = sector if sector and sector != "__all__" else "deteriorating portfolios"
    return [
        html.Div([
            html.Button([html.Span("‹", className="drill-chev"), "Sector detail"],
                        id=drill_id(2), n_clicks=0, className="drill-back-btn"),
            html.Button("Health Index", id=drill_id(1), n_clicks=0, className="drill-back-btn is-ghost"),
            html.Span(f"Obligor actions · {scope} · worst AI score first",
                      className="drill-crumb-note"),
        ], className="drill-crumb-row"),
        body,
        html.Div("Selecting an action records the intent for this review cycle; it does not yet write "
                 "back to the source system.", className="ob-foot-note"),
    ]


# ------------------------------------------------------------------ dispatcher

def build_drill_body(level: int = 1, sector: str | None = None, quarter=None) -> list:
    if level == 3:
        return build_obligor_screen(quarter, sector)
    if level == 2:
        return build_sector_matrix_screen(quarter)
    return build_health_screen(quarter)


def build_health_shell(quarter=None) -> html.Div:
    """The container the drill callback swaps content into."""
    return html.Div(build_drill_body(1, None, quarter), id="cockpit-drill-body",
                    className="hidx-screen")
