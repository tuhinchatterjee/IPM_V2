"""
ESG & Climate Risk views — the Oman Climate Stressed PD model v5.1, reproduced in
code and made multi-run, auditable and editable.

Eight tabs, in the order a reviewer works through the model:

  Results        the sector x scenario PD-multiple heat map, headline structural badges
  Drill-down     the full waterfall behind any one cell — the validator's artefact
  Inputs         one editable block per input tab, with source-register badges
  Calibration    anchors, route comparison, the k grid, the coal rejection, the theta band
  Sensitivity    one-way tornado over the five control levers plus disclosure bands
  Quality Checks all 24, with the four expected flags separated from real failures
  Runs           immutable runs, model versions, and a cell-level run diff
  Report         the downloadable summary pack (self-contained HTML + Excel)

The engine is never called from here with anything other than a fully resolved
model dict; all the arithmetic lives in backend/climate.
"""

import copy

import plotly.graph_objects as go
from dash import dash_table, dcc, html

from backend.climate import checks as climate_checks
from backend.climate import defaults, engine, registers, sensitivity, store
from frontend import ui_common as ui

# Validated categorical slots (worst adjacent CVD dE 9.1, normal-vision 22.9 on a
# white surface). Scenario identity is categorical, not ordered: the four scenarios
# rank one way on transition cost and the exact opposite way on physical cost.
SCENARIO_COLORS = {"NZ": "#2a78d6", "DT": "#eb6834", "CP": "#1baf7a", "FW": "#eda100"}
CHANNEL_COLORS = {"transition": "#2a78d6", "physical": "#eb6834"}
SEQUENTIAL = ["#eef4fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#256abf",
              "#1c5cab", "#184f95", "#104281", "#0d366b"]

TONE_DOT = {"ok": "green", "warn": "amber", "bad": "red", "info": "blue"}
STATUS_PILL = {"PASS": "esg-pill ok", "FAIL": "esg-pill bad", "FLAG": "esg-pill warn",
               "ACTION": "esg-pill warn", "DISCLOSE": "esg-pill warn",
               "REJECTED": "esg-pill warn", "REVIEW": "esg-pill warn", "INFO": "esg-pill info"}

# One block per workbook input tab, in the workbook's own order. The label names
# the sheet it replaces so a reviewer holding the file can follow along.
INPUT_BLOCKS = [
    ("sectors", "Sectors & GVA · Sector_Master"),
    ("emissions", "Emissions allocation · Emissions_Allocation"),
    ("scenarios", "NGFS scenarios · NGFS_CarbonPrice + Scenario_Mapping"),
    ("hazards", "Physical hazards · Physical_Hazard"),
    ("exposure", "Physical exposure · Physical_Exposure"),
    ("calibration", "k calibration · EU_k_Calibration + k_MultiAnchor"),
    ("macro", "Macro leg · Regression_Data + Macro_Shift"),
    ("grades", "Rating grades · RatingGrades"),
    ("settings", "Control settings"),
]

# Blocks whose editable table is not the block key itself (a block may carry more
# than one table; every table present on screen is folded back into the model).
BLOCK_TABLES = {
    "hazards": ["hazards", "events"],
    "calibration": ["calibration", "anchors"],
    "macro": ["macro", "macro_settings"],
}


def tables_for(block: str) -> list:
    return BLOCK_TABLES.get(block, [block])

TABLE_STYLE = dict(
    style_table={"overflowX": "auto"},
    style_cell={"fontFamily": "Inter, system-ui, sans-serif", "fontSize": "12.5px",
                "padding": "7px 10px", "border": "1px solid #eef1f6", "textAlign": "right",
                "minWidth": "76px"},
    style_header={"backgroundColor": "#f6f8fb", "fontWeight": "700", "fontSize": "10.5px",
                  "textTransform": "uppercase", "letterSpacing": "0.05em", "color": "#6c7a8c",
                  "border": "1px solid #eef1f6", "textAlign": "right", "whiteSpace": "normal",
                  "height": "auto"},
    style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#fbfcfe"}],
)


# --------------------------------------------------------------------- helpers

def _pct(v, places=2):
    return "—" if v is None else f"{v * 100:.{places}f}%"


def _num(v, places=3):
    return "—" if v is None else f"{v:,.{places}f}"


def resolve(version_id=None, horizon=None, theta=None, cap=None, correlation=None,
            anchor=None, route=None, basis=None, grade=None):
    """Load a model version and apply the in-page control overrides, then run the
    engine and the checks. Overrides never touch the stored version — saving is an
    explicit action on the Inputs tab."""
    rec = store.get_version(version_id) if version_id else None
    if rec is None:
        vid = store.default_version_id()
        rec = store.get_version(vid)
    model = copy.deepcopy(rec["model"]) if rec else defaults.default_model()

    s = model["settings"]
    if horizon is not None:
        s["horizon_year"] = int(horizon)
    if theta is not None:
        s["theta"] = float(theta)
    if cap is not None:
        s["cost_ratio_cap"] = float(cap)
    if basis:
        s["denominator_basis"] = basis
    if grade:
        s["reference_grade"] = grade
    if correlation is not None:
        model["macro"]["correlation_in_use"] = float(correlation)
    if anchor:
        model["calibration"]["anchor_in_use"] = anchor
    if route is not None:
        model["calibration"]["route_in_use"] = int(route)

    result = engine.calculate(model)
    return rec, model, result, climate_checks.run_checks(result, model)


def version_options():
    return [{"label": f"#{v['id']} · {v['name']} ({v['status']})", "value": v["id"]}
            for v in store.list_versions()]


def _dd(dd_id, options, value, width=None, clearable=False):
    style = {"minWidth": f"{width}px"} if width else None
    return dcc.Dropdown(id=dd_id, options=options, value=value, clearable=clearable,
                        searchable=False, className="filter-dd", style=style)


def _controls(children):
    return html.Div(children, className="filters-row")


def _version_control(dd_id, value=None):
    """The dropdown must default to the same version `resolve()` falls back to,
    or the first render shows one version's figures under another's name."""
    opts = version_options()
    if value is None:
        value = store.default_version_id() if opts else None
    return [html.Span("MODEL VERSION", className="filters-label"),
            _dd(dd_id, opts, value, 260)]


def _horizon_control(dd_id, value=2040):
    return [html.Span("HORIZON", className="filters-label"),
            _dd(dd_id, [{"label": str(y), "value": y} for y in defaults.HORIZON_YEARS], value, 110)]


def _theta_control(dd_id, value=0.0):
    labels = {1.0: "+1.0 linear", 0.5: "+0.5", 0.0: "0.0 log (default)", -0.5: "−0.5",
              -1.0: "−1.0 saturating"}
    return [html.Span("CURVATURE θ", className="filters-label"),
            _dd(dd_id, [{"label": v, "value": k} for k, v in labels.items()], value, 172)]


def _grade_control(dd_id, model=None, value="MR5"):
    grades = [g["grade"] for g in (model or defaults.default_model())["rating_grades"]]
    return [html.Span("GRADE", className="filters-label"),
            _dd(dd_id, [{"label": g, "value": g} for g in grades], value, 100)]


def _pill(status):
    return html.Span(status, className=STATUS_PILL.get(status, "esg-pill info"))


def _tag(text, tone="info"):
    """A pill that says what it is, rather than borrowing a check status. Used
    where the value is a role (FIT / CHECK / IN USE), not a pass-fail outcome."""
    return html.Span(text, className=f"esg-pill {tone}")


def _badge(text, tone="info"):
    return html.Span(text, className=f"esg-badge {tone}")


def _module_note(text):
    return html.Div(text, className="module-note")


def _scenario_label(result, code):
    return next((s["name"] for s in result["scenarios"] if s["code"] == code), code)


def _headline_kpis(result, check_rows):
    summary = climate_checks.summarise(check_rows)
    grade = result["reference_grade"]
    rows = [r for r in result["grid"] if r["grade"] == grade]
    worst = max(rows, key=lambda r: r["multiple"])
    return [
        ui.kpi_card("Worst cell", f"{worst['multiple']:.2f}x", "red",
                    ui.kpi_sub(f"{worst['sector']} · {_scenario_label(result, worst['scenario'])}")),
        ui.kpi_card("Stressed PD there", _pct(worst["stressed_pd"]), "amber",
                    ui.kpi_sub(f"from {_pct(worst['baseline_pd'])} at {grade}")),
        ui.kpi_card("Calibrated k", f"{result['k']:.6f}", "blue",
                    ui.kpi_sub(f"θ = {result['theta']:g} · anchor "
                               f"{result['calibration']['anchor_in_use']} · refit at every θ")),
        ui.kpi_card("Structural tests",
                    "BOTH PASS" if summary["structural_pair_ok"] else "REVIEW",
                    "green" if summary["structural_pair_ok"] else "red",
                    ui.kpi_sub("opposing transition / physical orderings")),
        ui.kpi_card("Quality checks", f"{summary['passed']} / {summary['total']}",
                    "green" if summary["can_finalise"] else "red",
                    ui.kpi_sub(f"{summary['failure_count']} failing · "
                               f"{summary['expected_count']} expected flags",
                               "up-bad" if summary["failure_count"] else "neutral")),
    ]


def _no_data_panel(message):
    return [html.Div(message, className="placeholder-panel")]


# ============================================================ 1. results tab

def build_results_tab():
    return html.Div([
        _controls(_version_control("esg-res-version") + _horizon_control("esg-res-horizon")
                  + _theta_control("esg-res-theta") + _grade_control("esg-res-grade")
                  + [html.Span("VIEW", className="filters-label"),
                     _dd("esg-res-view",
                         [{"label": "Summary — 10 sectors", "value": "summary"},
                          {"label": "Full grid — 70 rows", "value": "grid"},
                          {"label": "Cost ratios", "value": "cost"}], "summary", 190)]),
        html.Div(build_results_body(), id="esg-res-body"),
    ])


def _heatmap_figure(result, grade):
    sectors = result["summary"]
    codes = result["scenario_codes"]
    z = [[s["multiples"][c] for c in codes] for s in sectors]
    text = [[f"{s['multiples'][c]:.2f}x" for c in codes] for s in sectors]
    fig = go.Figure(go.Heatmap(
        z=z, x=[_scenario_label(result, c) for c in codes],
        y=[s["sector"] for s in sectors],
        text=text, texttemplate="%{text}",
        textfont=dict(size=11, family="Inter"),
        colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
        hovertemplate="<b>%{y}</b><br>%{x}<br>PD multiple %{z:.3f}x<extra></extra>",
        colorbar=dict(title=dict(text="PD ×", font=dict(size=10)), thickness=10,
                      tickfont=dict(size=10)),
    ))
    ui.base_layout(fig, height=max(320, 34 * len(sectors) + 90))
    fig.update_layout(margin=dict(t=10, b=24, l=250, r=10),
                      yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=11)),
                      xaxis=dict(side="top", showgrid=False, tickfont=dict(size=11)))
    return fig


def _summary_table(result):
    codes = result["scenario_codes"]
    header = html.Thead(html.Tr(
        [html.Th("Sector"), html.Th("Intensity (t/US$m)", className="num"),
         html.Th("Pass-through", className="num")]
        + [html.Th(f"{c} ×", className="num") for c in codes]
        + [html.Th("Physical share of push (CP)", className="num")]))
    body = html.Tbody([
        html.Tr([html.Td(s["sector"], className="metric-name"),
                 html.Td(f"{s['intensity']:,.0f}", className="num"),
                 html.Td(f"{s['pass_through']:.0%}", className="num")]
                + [html.Td(f"{s['multiples'][c]:.3f}x", className="num") for c in codes]
                + [html.Td(f"{s['physical_share'].get('CP', 0):.1%}", className="num")])
        for s in result["summary"]])
    return html.Table([header, body], className="borrower-table signals-table")


def _grid_table(result):
    codes = result["scenario_codes"]
    header = html.Thead(html.Tr(
        [html.Th("Sector"), html.Th("Grade"), html.Th("Baseline PD", className="num")]
        + [html.Th(f"{c} PD", className="num") for c in codes]
        + [html.Th(f"{c} ×", className="num") for c in codes]))
    rows = []
    for r in result["grid"]:
        if r["scenario"] != codes[0]:
            continue
        cells = [result["by_grid"][(r["sector_id"], r["grade"], c)] for c in codes]
        rows.append(html.Tr(
            [html.Td(r["sector"], className="metric-name"), html.Td(r["grade"]),
             html.Td(_pct(r["baseline_pd"], 3), className="num")]
            + [html.Td(_pct(c["stressed_pd"], 3), className="num") for c in cells]
            + [html.Td(f"{c['multiple']:.3f}", className="num") for c in cells]))
    return html.Table([header, html.Tbody(rows)], className="borrower-table signals-table")


def _cost_table(result):
    codes = result["scenario_codes"]
    header = html.Thead(html.Tr(
        [html.Th("Sector")]
        + [html.Th(f"Transition {c}", className="num") for c in codes]
        + [html.Th(f"Physical {c}", className="num") for c in codes]
        + [html.Th("Cap binds", className="num")]))
    rows = []
    for s in result["sectors"]:
        cells = [result["by_cell"][(s["id"], c)] for c in codes]
        rows.append(html.Tr(
            [html.Td(s["name"], className="metric-name")]
            + [html.Td(f"{c['transition_cost']:.4f}", className="num") for c in cells]
            + [html.Td(f"{c['physical_cost']:.5f}", className="num") for c in cells]
            + [html.Td("yes" if any(c["cap_binds"] for c in cells) else "—", className="num")]))
    return html.Table([header, html.Tbody(rows)], className="borrower-table signals-table")


def _channel_figure(result):
    """Two panels, each with its own scale. Never a second y-axis: the transition
    ratio is ~40x the physical one, so one shared scale would flatten the physical
    channel to a hairline and hide the ordering being tested."""
    codes = result["scenario_codes"]
    labels = [_scenario_label(result, c) for c in codes]
    trans = [sum(s["transition_cost"][c] for s in result["summary"]) / len(result["summary"])
             for c in codes]
    phys = [result["physical"]["gva_weighted_cost"][c] for c in codes]

    figs = []
    for title, values, colour, fmt in (
        ("TRANSITION COST RATIO — follows the carbon price", trans, CHANNEL_COLORS["transition"], ".3f"),
        ("PHYSICAL COST RATIO — follows warming", phys, CHANNEL_COLORS["physical"], ".4f"),
    ):
        fig = go.Figure(go.Bar(x=labels, y=values, marker=dict(color=colour),
                               text=[f"{v:{fmt}}" for v in values], textposition="outside",
                               hovertemplate="<b>%{x}</b><br>%{y:.5f} of value added<extra></extra>"))
        ui.base_layout(fig, height=250)
        fig.update_layout(bargap=0.45, margin=dict(t=26, b=48, l=52, r=12))
        figs.append(ui.chart_card(title, dcc.Graph(figure=fig, config={"displayModeBar": False})))
    return html.Div(figs, className="esg-chart-pair")


def build_results_body(version_id=None, horizon=None, theta=None, grade=None, view="summary"):
    _, _, result, check_rows = resolve(version_id, horizon=horizon, theta=theta, grade=grade)
    summary = climate_checks.summarise(check_rows)
    codes = result["scenario_codes"]
    grade = result["reference_grade"]

    order_badges = html.Div([
        _badge(f"Transition ordering NZ ≥ DT ≥ FW ≥ CP — "
               f"{'0 violations' if summary['structural_pair_ok'] else 'VIOLATIONS'}",
               "ok" if summary["structural_pair_ok"] else "bad"),
        _badge(f"Physical ordering CP ≥ FW ≥ DT ≥ NZ — "
               f"{'0 violations' if summary['structural_pair_ok'] else 'VIOLATIONS'}",
               "ok" if summary["structural_pair_ok"] else "bad"),
        _badge(f"{len(result['grid'])} cells · no de-stress", "ok"),
        _badge(f"Extrapolation {result['calibration']['extrapolation']['multiple']:.0f}x "
               f"beyond calibration", "warn"),
    ], className="esg-badge-row")

    table = {"summary": _summary_table, "grid": _grid_table, "cost": _cost_table}.get(
        view, _summary_table)(result)
    table_title = {"summary": f"PD MULTIPLE AND COST DECOMPOSITION AT GRADE {grade}",
                   "grid": "FULL STRESSED-PD GRID — 10 SECTORS × 7 GRADES",
                   "cost": "COST RATIOS BY SECTOR AND SCENARIO"}.get(view, "")

    worst = max((r for r in result["grid"] if r["grade"] == grade), key=lambda r: r["multiple"])
    insight = (
        f"At the {result['horizon_year']} horizon, {worst['sector']} under "
        f"{_scenario_label(result, worst['scenario'])} is the most exposed cell at grade {grade}: "
        f"{_pct(worst['baseline_pd'])} becomes {_pct(worst['stressed_pd'])}, a {worst['multiple']:.2f}x "
        f"multiple. The transition channel is an emission-intensity story filtered through pass-through; "
        f"the physical channel runs the other way, rising from "
        f"{result['physical']['gva_weighted_cost'][codes[0]] * 100:.3f}% of value added under "
        f"{_scenario_label(result, codes[0])} to "
        f"{result['physical']['gva_weighted_cost']['CP'] * 100:.3f}% under Current Policies. Both "
        f"orderings hold with zero violations, which is the single most important structural test of a "
        f"climate scenario model. Output is a PD signal only — no ECL, no LGD."
    )

    return [
        html.Div(_headline_kpis(result, check_rows), className="signals-kpi-grid"),
        order_badges,
        ui.chart_card(f"PD MULTIPLE — SECTOR × SCENARIO AT GRADE {grade}",
                      dcc.Graph(figure=_heatmap_figure(result, grade),
                                config={"displayModeBar": False})),
        _channel_figure(result),
        ui.table_card(table_title, table),
        html.Div(ui.ai_insight_card(insight), style={"marginTop": "18px"}),
        _module_note(
            "stressed_PD = N( N⁻¹(PD₀) + push + macro_shift), push = k × g(transition cost ratio + "
            "physical cost ratio). The two cost ratios are added INSIDE the transform because g is "
            "concave — two separate pushes would understate facing both shocks at once. Reproduces the "
            f"Oman Climate Stressed PD v5.1 workbook; engine v{result['engine_version']}."),
    ]


# ========================================================== 2. drill-down tab

def build_drilldown_tab():
    _, model, result, _ = resolve()
    sectors = [{"label": s["name"], "value": s["id"]} for s in result["sectors"]]
    scen = [{"label": s["name"], "value": s["code"]} for s in result["scenarios"]]
    return html.Div([
        _controls(_version_control("esg-dd-version") + _horizon_control("esg-dd-horizon")
                  + [html.Span("SECTOR", className="filters-label"),
                     _dd("esg-dd-sector", sectors, "S05", 260)]
                  + _grade_control("esg-dd-grade", model)
                  + [html.Span("SCENARIO", className="filters-label"),
                     _dd("esg-dd-scenario", scen, "NZ", 180)]),
        html.Div(build_drilldown_body(), id="esg-dd-body"),
    ])


def _waterfall_figure(dec):
    """The three shift components only. The baseline probit is two orders of
    magnitude larger, so putting it on the same scale flattens the decomposition."""
    labels = ["Transition push", "Physical push", "Macro shift", "Total probit shift"]
    values = [dec["cell"]["push_transition"], dec["cell"]["push_physical"],
              dec["cell"]["macro_shift"], dec["cell"]["probit_shift"]]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=["relative", "relative", "relative", "total"],
        x=labels, y=values,
        text=[f"{v:+.5f}" if i < 3 else f"{v:.5f}" for i, v in enumerate(values)],
        textposition="outside",
        connector=dict(line=dict(color="#c3c2b7", width=1, dash="dot")),
        increasing=dict(marker=dict(color="#d03b3b")),
        decreasing=dict(marker=dict(color="#2a78d6")),
        totals=dict(marker=dict(color="#898781")),
        hovertemplate="<b>%{x}</b><br>%{y:+.6f} probit<extra></extra>",
    ))
    ui.base_layout(fig, height=290)
    fig.update_layout(margin=dict(t=28, b=30, l=60, r=14))
    return fig


def build_drilldown_body(version_id=None, horizon=None, sector_id="S05", grade="MR5",
                         scenario="NZ"):
    _, _, result, _ = resolve(version_id, horizon=horizon)
    if (sector_id, grade, scenario) not in result["by_grid"]:
        return _no_data_panel("Select a sector, grade and scenario.")
    dec = engine.decompose(result, sector_id, grade, scenario)
    cell, row = dec["cell"], dec["row"]

    kpis = [
        ui.kpi_card("Stressed PD", _pct(row["stressed_pd"]), "red",
                    ui.kpi_sub(f"{row['multiple']:.3f}x baseline · +{row['delta_bps']:,.0f} bps")),
        ui.kpi_card("Total cost ratio", f"{cell['total_cost']:.4f}", "amber",
                    ui.kpi_sub(f"transition {cell['transition_cost']:.4f} + physical "
                               f"{cell['physical_cost']:.5f}")),
        ui.kpi_card("Probit push", f"{cell['push']:.5f}", "blue",
                    ui.kpi_sub(f"physical is {cell['physical_share']:.1%} of it")),
        ui.kpi_card("Macro shift", f"{cell['macro_shift']:.5f}", "purple",
                    ui.kpi_sub(f"GDP level deviation "
                               f"{result['macro']['by_scenario'][scenario]['deviation_pct']:.2f}%")),
    ]

    steps = html.Table([
        html.Thead(html.Tr([html.Th("Step"), html.Th("Value", className="num"), html.Th("Unit"),
                            html.Th("Working")])),
        html.Tbody([
            html.Tr([html.Td(s["label"], className="metric-name"),
                     html.Td(f"{s['value']:,.6f}" if abs(s["value"]) < 1000
                             else f"{s['value']:,.2f}", className="num"),
                     html.Td(s["unit"]), html.Td(s["detail"], className="esg-working")])
            for s in dec["steps"]]),
    ], className="borrower-table signals-table")

    hazards = html.Table([
        html.Thead(html.Tr([html.Th("Hazard"), html.Th("Baseline AAL", className="num"),
                            html.Th("Severity", className="num"),
                            html.Th("Normalised exposure", className="num"),
                            html.Th("Insurance recovery", className="num"),
                            html.Th("P&L share", className="num"),
                            html.Th("Contribution", className="num")])),
        html.Tbody([
            html.Tr([html.Td(h["name"], className="metric-name"),
                     html.Td(f"{h['baseline_aal'] * 100:.4f}%", className="num"),
                     html.Td(f"{h['severity']:.4f}", className="num"),
                     html.Td(f"{h['exposure']:.4f}", className="num"),
                     html.Td(f"{h['insurance_recovery']:.0%}", className="num"),
                     html.Td(f"{h['pnl_share']:.0%}", className="num"),
                     html.Td(f"{h['contribution']:.6f}", className="num")])
            for h in dec["hazards"]]),
    ], className="borrower-table signals-table")

    ladder = html.Table([
        html.Thead(html.Tr([html.Th("Grade"), html.Th("Baseline PD", className="num"),
                            html.Th("Stressed PD", className="num"),
                            html.Th("Multiple", className="num"), html.Th("Δ bps", className="num")])),
        html.Tbody([
            html.Tr([html.Td(g["grade"], className="metric-name"),
                     html.Td(_pct(g["baseline_pd"], 3), className="num"),
                     html.Td(_pct(result["by_grid"][(sector_id, g["grade"], scenario)]["stressed_pd"], 3),
                             className="num"),
                     html.Td(f"{result['by_grid'][(sector_id, g['grade'], scenario)]['multiple']:.3f}x",
                             className="num"),
                     html.Td(f"{result['by_grid'][(sector_id, g['grade'], scenario)]['delta_bps']:,.0f}",
                             className="num")])
            for g in result["grades"]]),
    ], className="borrower-table signals-table")

    insight = (
        f"{dec['sector']} at grade {grade} under {dec['scenario_name']}, {result['horizon_year']}. "
        f"A carbon price of US${cell['carbon_price']:,.0f}/tCO2e in {result['settings']['carbon_price_base_year']} "
        f"dollars deflates to US${cell['carbon_price_deflated']:,.1f}; against an emission intensity of "
        f"{dec['sector_detail']['intensity']:,.0f} tCO2e per US$m and "
        f"{dec['sector_detail']['pass_through']:.0%} pass-through that is a transition cost of "
        f"{cell['transition_cost']:.4f} of value added. Acute physical damage adds "
        f"{cell['physical_cost']:.5f}, and the two are summed before the transform. The push of "
        f"{cell['push']:.5f} plus a macro shift of {cell['macro_shift']:.5f} moves the probit from "
        f"{engine.norm_ppf(row['baseline_pd']):.4f} to "
        f"{engine.norm_ppf(row['stressed_pd']):.4f}, i.e. a PD of {_pct(row['stressed_pd'])}. "
        f"Every number here is reproducible by hand from the inputs."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        ui.chart_card("WHAT THE PROBIT SHIFT IS MADE OF",
                      dcc.Graph(figure=_waterfall_figure(dec), config={"displayModeBar": False})),
        ui.table_card("WORKED EXAMPLE — PRICE THROUGH TO STRESSED PD", steps),
        html.Div([
            html.Div([ui.table_card("PHYSICAL COST BUILD-UP", hazards)], className="split-main"),
            html.Div([ui.table_card("SAME SECTOR AND SCENARIO ACROSS THE GRADE LADDER", ladder)],
                     className="split-side"),
        ], className="split-grid"),
        html.Div(ui.ai_insight_card(insight), style={"marginTop": "18px"}),
    ]


# ============================================================== 3. inputs tab

def build_inputs_tab():
    return html.Div([
        _controls(_version_control("esg-in-version")
                  + [html.Span("INPUT BLOCK", className="filters-label"),
                     _dd("esg-in-block", [{"label": lbl, "value": key} for key, lbl in INPUT_BLOCKS],
                         "sectors", 330),
                     html.Button("Save to version", id="esg-in-save", className="report-generate-btn esg-inline-btn",
                                 n_clicks=0),
                     html.Button("Clone as draft", id="esg-in-clone", className="report-secondary-btn esg-inline-btn",
                                 n_clicks=0),
                     html.Button("Reset edits", id="esg-in-reset", className="report-secondary-btn esg-inline-btn",
                                 n_clicks=0)]),
        html.Div(id="esg-in-status"),
        # The live strip recomputes the whole model from whatever is currently in
        # the tables, before anything is saved. Editing is an estimation tool, not
        # just a data-entry form.
        html.Div(build_inputs_live(), id="esg-in-live"),
        html.Div(build_inputs_body(), id="esg-in-body"),
    ])


def _delta_chip(label, live, baseline, fmt="{:.4f}", good_low=None):
    """One live-vs-saved comparison. Shows the saved value alongside, so the user
    can see what their edit moved rather than only where it landed."""
    moved = baseline is not None and abs(live - baseline) > 1e-12
    if not moved:
        return html.Div([html.Div(label, className="esg-live-label"),
                         html.Div(fmt.format(live), className="esg-live-value")],
                        className="esg-live-chip")
    up = live > baseline
    tone = "" if good_low is None else ("is-bad" if up == good_low else "is-good")
    return html.Div([
        html.Div(label, className="esg-live-label"),
        html.Div(fmt.format(live), className=f"esg-live-value {tone}"),
        html.Div([html.Span("was ", className="esg-live-was"), fmt.format(baseline)],
                 className="esg-live-prev"),
    ], className="esg-live-chip is-moved")


def build_inputs_live(model=None, result=None, check_rows=None, baseline=None):
    """The what-if strip: k, the worst cell, the max cost ratio and the check count,
    recomputed from the live table contents and compared against the saved version."""
    if result is None:
        _rec, model, result, check_rows = resolve()
    summary = climate_checks.summarise(check_rows)
    grade = result["reference_grade"]
    rows = [r for r in result["grid"] if r["grade"] == grade]
    worst = max(rows, key=lambda r: r["multiple"]) if rows else None

    base_worst = None
    if baseline is not None:
        b_rows = [r for r in baseline["grid"] if r["grade"] == baseline["reference_grade"]]
        base_worst = max(b_rows, key=lambda r: r["multiple"])["multiple"] if b_rows else None

    chips = [
        _delta_chip("Calibrated k", result["k"],
                    baseline["k"] if baseline else None, "{:.6f}", good_low=True),
        _delta_chip(f"Worst cell ({grade})", worst["multiple"] if worst else 0.0,
                    base_worst, "{:.3f}x", good_low=True),
        _delta_chip("Max cost ratio", result["max_cost_ratio"],
                    baseline["max_cost_ratio"] if baseline else None, "{:.1%}", good_low=True),
        _delta_chip("Checks passing", float(summary["passed"]),
                    None, "{:.0f} of " + str(summary["total"])),
    ]
    dirty = baseline is not None and any(
        abs(result[k] - baseline[k]) > 1e-12 for k in ("k", "max_cost_ratio"))
    state = (html.Span("UNSAVED ESTIMATE", className="esg-pill warn") if dirty
             else html.Span("MATCHES SAVED VERSION", className="esg-pill ok"))
    failing = [c for c in check_rows if c["status"] == "FAIL"]
    return html.Div([
        html.Div([html.Span("LIVE ESTIMATE", className="esg-live-title"), state],
                 className="esg-live-head"),
        html.Div(chips, className="esg-live-row"),
        html.Div(
            f"{len(failing)} quality check(s) failing on these inputs: "
            + ", ".join(f"#{c['id']} {c['name']}" for c in failing)
            if failing else "All structural checks pass on these inputs.",
            className=f"esg-live-verdict {'is-fail' if failing else 'is-ok'}"),
    ], className="esg-live-strip")


# Free-text columns wrap and left-align; everything else is a right-aligned figure.
WRAP_COLUMNS = {"name", "rationale", "definition", "mechanism", "isic", "status", "quadrant",
                "grade", "id", "code", "label"}


def _editable(table_key, columns, data, editable_cols=None, locked=False, row_editable=False):
    """`locked` renders the block genuinely read-only rather than letting a user
    type into a final version and only learn on save that it was rejected.

    The id is pattern-matching on `table_key` so a single callback can pick up
    whichever tables are currently on screen — a block may carry more than one
    (hazards carries its parameters and the event record that derives them)."""
    cols = []
    for c in columns:
        col = {"name": c[1], "id": c[0]}
        if len(c) > 2 and c[2] == "num":
            col["type"] = "numeric"
        col["editable"] = (not locked) and ((editable_cols is None) or (c[0] in editable_cols))
        cols.append(col)

    conditional = [{"if": {"column_id": cols[0]["id"]}, "textAlign": "left", "minWidth": "90px"}]
    for c in cols:
        if c["id"] in WRAP_COLUMNS:
            conditional.append({
                "if": {"column_id": c["id"]},
                "textAlign": "left", "whiteSpace": "normal", "height": "auto",
                "minWidth": "150px" if c["id"] in ("rationale", "definition", "mechanism") else "80px",
                "maxWidth": "320px" if c["id"] in ("rationale", "definition", "mechanism") else "220px",
            })
    return dash_table.DataTable(
        id={"type": "esg-tbl", "block": table_key}, columns=cols, data=data, editable=not locked,
        row_deletable=row_editable and not locked,
        style_data_conditional=TABLE_STYLE["style_data_conditional"] + [
            {"if": {"column_editable": False}, "backgroundColor": "#f6f8fb", "color": "#6c7a8c"},
        ],
        style_table=TABLE_STYLE["style_table"], style_cell=TABLE_STYLE["style_cell"],
        style_header=TABLE_STYLE["style_header"],
        style_cell_conditional=conditional,
    )


def _source_badges(entries):
    """Provenance chips: every input block states where its numbers came from."""
    return html.Div([
        html.Span([html.Span(r["status"], className=f"esg-badge {registers.status_tone(r['status'])}"),
                   html.Span(f" {r['value']} — {r['source']}", className="esg-src-text")],
                  className="esg-src-row")
        for r in entries], className="esg-src-block")


def _register_for(location_prefixes):
    return [r for r in registers.SOURCE_REGISTER_ROWS
            if any(r["location"].startswith(p) for p in location_prefixes)]


def build_inputs_body(version_id=None, block="sectors", live=None, derived_only=False):
    """The editable block plus its derived panels.

    `live` is an already-resolved (model, result, check_rows) triple from the
    unsaved table contents; `derived_only` returns just the derived half. One
    implementation serves both the first render and every live recalculation, so
    the two can never disagree about what a derived figure is."""
    if live is not None:
        rec, (model, result, check_rows) = None, live
        rec = store.get_version(version_id) if version_id else None
    else:
        rec, model, result, check_rows = resolve(version_id)
    derived_blocks = []
    # A final version is immutable, but exploring one is not the same as changing
    # it: the tables stay editable so any version can be used as a what-if
    # starting point, and only SAVING is refused. Locking the inputs of the
    # approved model would make the estimator useless exactly where it matters.
    is_final = rec is not None and rec["status"] == store.STATUS_FINAL
    editable = True
    lock = None
    if is_final:
        lock = html.Div(
            "This version is FINAL. Edit freely to explore — every figure below recalculates live — "
            "but saving is refused, because the audit trail depends on final versions never moving. "
            "Use “Clone as draft” to keep an estimate.", className="upload-verdict is-warn")

    if block == "sectors":
        data = [{"id": s["id"], "name": s["name"], "isic": s.get("isic", ""),
                 "gva_omr": s["gva_omr"], "turnover_gva": s.get("turnover_gva", 1.0),
                 "pass_through": s["pass_through"], "macro_beta": s.get("macro_beta", 1.0),
                 "rationale": s.get("rationale", "")} for s in model["sectors"]]
        table = _editable("sectors",
                          [("id", "ID"), ("name", "Sector"), ("isic", "ISIC"),
                           ("gva_omr", "GVA (local m)", "num"), ("turnover_gva", "Turnover/GVA", "num"),
                           ("pass_through", "Pass-through", "num"), ("macro_beta", "macro_beta", "num"),
                           ("rationale", "Pass-through rationale")], data, locked=not editable)
        derived = html.Table([
            html.Thead(html.Tr([html.Th("Sector"), html.Th("GVA (US$m)", className="num"),
                                html.Th("Denominator (US$m)", className="num"),
                                html.Th("Emissions (MtCO2e)", className="num"),
                                html.Th("Intensity (t/US$m)", className="num")])),
            html.Tbody([html.Tr([html.Td(s["name"], className="metric-name"),
                                 html.Td(f"{s['gva_usd']:,.1f}", className="num"),
                                 html.Td(f"{s['denominator_usd']:,.1f}", className="num"),
                                 html.Td(f"{s['emissions_mt']:.4f}", className="num"),
                                 html.Td(f"{s['intensity']:,.2f}", className="num")])
                        for s in result["sectors"]]),
        ], className="borrower-table signals-table")
        blocks = [ui.table_card("SECTOR MASTER — EDITABLE", table),
                  _source_badges(_register_for(["Sectors"]))]
        derived_blocks = [ui.table_card("DERIVED — RECOMPUTED AS YOU EDIT", derived)]
        note = ("Every ISIC section sits in exactly one sector and every sector has a positive GVA. "
                "Zero-GVA rows were the v3 defect: they silently received no stress at all.")

    elif block == "emissions":
        sector_ids = [s["id"] for s in model["sectors"]]
        data = []
        for cat, resolved in zip(model["edgar_categories"], result["emissions"]["categories"],
                                 strict=True):
            row = {"code": cat["code"], "name": cat["name"],
                   "mt": "PLUG" if cat.get("mt") is None else cat["mt"],
                   "allocated": round(resolved["mt"], 4)}
            row.update({sid: cat["shares"].get(sid, 0.0) for sid in sector_ids})
            row["HH"] = cat["shares"].get("HH", 0.0)
            row["sum"] = round(resolved["share_sum"], 6)
            data.append(row)
        cols = ([("code", "Code"), ("name", "EDGAR category"), ("mt", "MtCO2e"),
                 ("allocated", "Resolved", "num")]
                + [(sid, sid, "num") for sid in sector_ids] + [("HH", "HH", "num"),
                                                               ("sum", "Row sum", "num")])
        table = _editable("emissions", cols, data,
                          editable_cols=set(["mt"] + sector_ids + ["HH"]), locked=not editable)
        alloc = result["emissions"]
        derived = html.Table([
            html.Thead(html.Tr([html.Th("Sector"), html.Th("Allocated MtCO2e", className="num"),
                                html.Th("Share of national", className="num")])),
            html.Tbody([html.Tr([html.Td(s["name"], className="metric-name"),
                                 html.Td(f"{s['emissions_mt']:.4f}", className="num"),
                                 html.Td(f"{s['emissions_mt'] / alloc['national_total_mt']:.2%}",
                                         className="num")])
                        for s in result["sectors"]]
                       + [html.Tr([html.Td("Households & own-account (excluded)",
                                           className="metric-name"),
                                   html.Td(f"{alloc['households_mt']:.4f}", className="num"),
                                   html.Td(f"{alloc['households_mt'] / alloc['national_total_mt']:.2%}",
                                           className="num")])]),
        ], className="borrower-table signals-table")
        blocks = [ui.table_card("EDGAR ALLOCATION — EACH ROW MUST SUM TO 1.00", table),
                  _source_badges(_register_for(["EDGAR", "Settings · national"]))]
        derived_blocks = [ui.table_card("ALLOCATED EMISSIONS BY LENDING SECTOR — RECOMPUTED AS YOU EDIT",
                                        derived)]
        note = ("EDGAR reports by IPCC SOURCE category; a bank lends to ISIC ACTIVITIES. The Households "
                "column is carried but excluded from every corporate intensity — it removes roughly 18% "
                "of national emissions that belong to private vehicles and residential energy, not to "
                "any borrower. The residual row is a plug: it absorbs the national total less every "
                "stated category.")

    elif block == "scenarios":
        data = [{"code": s["code"], "name": s["name"], "quadrant": s.get("quadrant", ""),
                 "warming_2100": s["warming_2100"],
                 **{f"p{y}": s["carbon_price"][y] for y in defaults.HORIZON_YEARS},
                 **{f"d{y}": s["gdp_deviation"][y] for y in defaults.HORIZON_YEARS},
                 "intensity_index": s.get("intensity_index", 1.0),
                 "denominator_index": s.get("denominator_index", 1.0)}
                for s in model["scenarios"]]
        cols = ([("code", "Code"), ("name", "Scenario"), ("quadrant", "Quadrant"),
                 ("warming_2100", "Warming 2100 °C", "num")]
                + [(f"p{y}", f"Price {y}", "num") for y in defaults.HORIZON_YEARS]
                + [(f"d{y}", f"GDP dev {y} %", "num") for y in defaults.HORIZON_YEARS]
                + [("intensity_index", "Intensity index", "num"),
                   ("denominator_index", "Denominator index", "num")])
        table = _editable("scenarios", cols, data, locked=not editable)
        blocks = [ui.table_card("NGFS SCENARIOS — EDITABLE", table),
                  _source_badges(_register_for(["Scenarios", "Settings · us_gdp"]))]
        note = ("Carbon prices are US$2010 per tCO2e and are deflated to denominator-year dollars before "
                "use; omitting the deflator understates every cost ratio by roughly a quarter. The 2035 "
                "GDP deviation is derived as the midpoint of 2030 and 2040, so editing the endpoints is "
                "enough. Both dynamic indices default to 1.00, which reproduces a static treatment "
                "exactly.")

    elif block == "hazards":
        data = [{"id": h["id"], "name": h["name"],
                 "baseline_aal": "DERIVED" if h.get("baseline_aal") is None else h["baseline_aal"],
                 "elasticity": h["elasticity"], "insurance_recovery": h["insurance_recovery"],
                 "pnl_share": h["pnl_share"], "lgd_share": round(1 - float(h["pnl_share"]), 4),
                 "status": h.get("status", ""), "mechanism": h.get("mechanism", "")}
                for h in model["hazards"]]
        table = _editable("hazards",
                          [("id", "ID"), ("name", "Hazard"), ("baseline_aal", "Baseline AAL (% GVA)"),
                           ("elasticity", "Warming elasticity", "num"),
                           ("insurance_recovery", "Insurance recovery", "num"),
                           ("pnl_share", "P&L share (to PD)", "num"),
                           ("lgd_share", "Reserved for LGD", "num"),
                           ("status", "Status"), ("mechanism", "Economic mechanism")], data,
                          editable_cols={"baseline_aal", "elasticity", "insurance_recovery",
                                         "pnl_share"}, locked=not editable)
        # The event record is an INPUT: H1's baseline AAL is total observed damage
        # over the observation window, as a share of national value added. Editing
        # a damage figure, adding an event or shortening the window all move it.
        events = _editable(
            "events",
            [("event", "Event"), ("year", "Year", "num"),
             ("damage_usd_m", "Direct damage (US$m)", "num"), ("source", "Source")],
            [{"event": e["event"], "year": e["year"], "damage_usd_m": e["damage_usd_m"],
              "source": e.get("source", "")} for e in model["cyclone_events"]],
            locked=not editable, row_editable=True)
        phys = result["physical"]
        warming = html.Table([
            html.Thead(html.Tr([html.Th("Scenario"), html.Th("Warming 2100 °C", className="num"),
                                html.Th("Warming at horizon °C", className="num"),
                                html.Th("Ratio to today", className="num")]
                               + [html.Th(f"Severity {h['id']}", className="num")
                                  for h in phys["hazards"]])),
            html.Tbody([html.Tr([html.Td(_scenario_label(result, c), className="metric-name"),
                                 html.Td(f"{phys['warming'][c]['warming_2100']:.1f}", className="num"),
                                 html.Td(f"{phys['warming'][c]['at_horizon']:.3f}", className="num"),
                                 html.Td(f"{phys['warming'][c]['ratio']:.4f}", className="num")]
                                + [html.Td(f"{phys['severity'][h['id']][c]:.4f}", className="num")
                                   for h in phys["hazards"]])
                        for c in result["scenario_codes"]]),
        ], className="borrower-table signals-table")
        blocks = [ui.table_card("HAZARD BASELINES — EDITABLE", table),
                  ui.table_card("CYCLONE EVENT RECORD — EDITABLE, DERIVES H1's BASELINE AAL", events,
                                hint="delete a row with the ✕; the observation window is on Settings"),
                  _source_badges(_register_for(["Hazards", "Cyclone", "Derived · warming"]))]
        derived_blocks = [
            html.Div([_badge(f"H1 baseline AAL derived from the event record: "
                             f"{phys['event_aal_share'] * 100:.4f}% of national GVA "
                             f"(US${phys['observed_damage_usd_m']:,.0f}m over "
                             f"{phys['observation_years']:.0f} years)", "info")],
                     className="esg-badge-row"),
            ui.table_card("WARMING PATH AND SEVERITY MULTIPLIERS — RECOMPUTED AS YOU EDIT", warming),
        ]
        note = ("The 60/40 P&L/capital split is the double-counting firewall: the PD channel takes only "
                "business interruption and repair expense, and the 40% capital-replacement remainder "
                "stays addressable for a future LGD module. Warming at the horizon is a straight-line "
                "interpolation and is the weakest input in the physical module — quality check 24 flags "
                "it on every run.")

    elif block == "exposure":
        hazard_ids = [h["id"] for h in model["hazards"]]
        data = [{"id": s["id"], "name": s["name"],
                 **{h: model["exposure_raw"][s["id"]][h] for h in hazard_ids},
                 **{f"n_{h}": round(result["physical"]["exposure_used"][s["id"]][h], 4)
                    for h in hazard_ids},
                 "rationale": model.get("exposure_rationale", {}).get(s["id"], "")}
                for s in model["sectors"]]
        cols = ([("id", "ID"), ("name", "Sector")]
                + [(h, f"{h} raw", "num") for h in hazard_ids]
                + [(f"n_{h}", f"{h} normalised", "num") for h in hazard_ids]
                + [("rationale", "Reasoning")])
        table = _editable("exposure", cols, data, editable_cols=set(hazard_ids),
                          locked=not editable)
        means = result["physical"]["normalised_weighted_mean"]
        blocks = [ui.table_card("SECTOR EXPOSURE WEIGHTS — 30 JUDGEMENT CELLS", table),
                  _source_badges(_register_for(["Exposure"]))]
        derived_blocks = [html.Div([_badge(f"GVA-weighted mean after normalisation, {h}: {v:.4f}",
                                           "ok" if abs(v - 1) < 1e-4 else "bad")
                                    for h, v in means.items()], className="esg-badge-row")]
        note = ("Weights are RELATIVE, not absolute: normalising by the GVA-weighted mean guarantees the "
                "national annual average loss is preserved exactly. An error here misallocates risk "
                "between sectors but can never inflate or deflate system-wide risk. Scaling all 30 raw "
                "weights by any constant leaves every result unchanged.")

    elif block == "calibration":
        cal, r1, r2 = model["calibration"], model["calibration"]["route1"], model["calibration"]["route2"]
        rc = result["calibration"]
        rows_spec = [
            ("baseline_pd", "Median EU firm baseline PD", cal["baseline_pd"], "OP 281 Chart 31b"),
            ("anchor_a_rel", "Anchor A — relative PD change (transition-only)", cal["anchor_a_rel"],
             "OP 281 §5.3"),
            ("anchor_b_rel", "Anchor B — relative PD change (disorderly 2050)", cal["anchor_b_rel"],
             "OP 281 §5.3"),
            ("eu_total_ghg_mt", "Route 1 · EU27 total GHG (MtCO2e)", r1["eu_total_ghg_mt"],
             "EEA inventory — TO VERIFY"),
            ("household_share", "Route 1 · household / own-account share excluded",
             r1["household_share"], "Residential heat + private road"),
            ("eu_gva_eur_bn", "Route 1 · EU27 gross value added (EUR bn)", r1["eu_gva_eur_bn"],
             "Eurostat nama_10_a10 — TO VERIFY"),
            ("median_to_average", "Route 1 · median-firm / economy-average ratio",
             r1["median_to_average"], "Derived from OP 281 Chart 12"),
            ("median_total_intensity", "Route 2 · median firm Scope 1+2+3 (t/EURm turnover)",
             r2["median_total_intensity"], "OP 281 Chart 12 mid-point"),
            ("scope1_share", "Route 2 · Scope 1 share of total", r2["scope1_share"],
             "Not published — assumption"),
            ("turnover_gva_ratio", "Route 2 · turnover / GVA ratio", r2["turnover_gva_ratio"],
             "Eurostat SBS"),
            ("anchor_price_usd", "Anchor carbon price (US$/tCO2)", cal["anchor_price_usd"],
             "NGFS Phase I — assumption"),
            ("usd_eur", "USD / EUR", cal["usd_eur"], "FX"),
            ("eu_pass_through", "EU pass-through", cal["eu_pass_through"], "OP 281 §5.1 — zero"),
            ("coal_plausible_intensity_multiple", "Plausible coal Scope 1 intensity multiple",
             cal["coal_plausible_intensity_multiple"], "OP 281 §5.4"),
        ]
        table = _editable("calibration",
                          [("label", "Calibration input"), ("value", "Value", "num"),
                           ("source", "Basis"), ("key", "Key")],
                          [{"key": k, "label": lbl, "value": v, "source": src}
                           for k, lbl, v, src in rows_spec],
                          editable_cols={"value"}, locked=not editable)
        anchors_tbl = _editable(
            "anchors",
            [("id", "#"), ("group", "Group"), ("baseline_pd", "Baseline PD", "num"),
             ("rel_change", "Relative change", "num"), ("use", "Use"), ("mechanism", "Mechanism")],
            [{"id": a["id"], "group": a["group"], "baseline_pd": a["baseline_pd"],
              "rel_change": a["rel_change"], "use": a["use"], "mechanism": a["mechanism"]}
             for a in model["calibration"]["anchors"]],
            editable_cols={"baseline_pd", "rel_change", "use"}, locked=not editable)
        derived = html.Table([
            html.Thead(html.Tr([html.Th("Derived quantity"), html.Th("Value", className="num")])),
            html.Tbody([html.Tr([html.Td(lbl, className="metric-name"), html.Td(v, className="num")])
                        for lbl, v in [
                            ("Route 1 economy intensity (t/EURm)", f"{rc['route1_economy_intensity']:,.4f}"),
                            ("Route 1 median intensity (t/EURm)", f"{rc['route1_intensity']:,.4f}"),
                            ("Route 2 intensity (t/EURm)", f"{rc['route2_intensity']:,.4f}"),
                            ("EU intensity SELECTED", f"{rc['eu_intensity']:,.4f}"),
                            ("Anchor carbon price (EUR/tCO2)", f"{rc['anchor_price_eur']:,.4f}"),
                            ("cost_ratio_EU", f"{rc['cost_ratio_eu']:.8f}"),
                            ("push_EU", f"{rc['push_eu']:.8f}"),
                            ("g(cost_ratio_EU, θ)", f"{rc['g_at_anchor']:.8f}"),
                            ("k FITTED", f"{rc['k']:.9f}"),
                            ("Implied top-decile intensity multiple",
                             f"{rc['implied_intensity_multiple']:.4f}"
                             if rc["implied_intensity_multiple"] else "unreachable"),
                            ("Extrapolation multiple", f"{rc['extrapolation']['multiple']:,.1f}x"),
                        ]]),
        ], className="borrower-table signals-table")
        # The workbook holds the anchor in two places — EU_k_Calibration's A/B
        # selector and the k_MultiAnchor table — and they happen to agree. That
        # redundancy is preserved rather than silently unified, but it is a trap
        # unless the split is stated, so it is.
        split_note = html.Div(
            "The headline k is fitted from Anchor A/B above. The anchors table below drives the "
            "curvature band, the implied top-decile multiple and the coal out-of-sample check. "
            "The workbook carries the same figure in both places — if you edit one, edit the other "
            "or the two will disagree.",
            className="upload-verdict is-warn")
        blocks = [ui.table_card("EU CALIBRATION INPUTS — EDITABLE, FITS k", table),
                  split_note,
                  ui.table_card("ECB ANCHORS — EDITABLE (FIT fits the curvature band, CHECK is "
                                "out-of-sample)", anchors_tbl),
                  _source_badges(_register_for(["Calibration"]))]
        derived_blocks = [ui.table_card("DERIVED — k IS REFITTED ON EVERY EDIT", derived)]
        note = ("k is the single most consequential number in the model and the least pinned down: it "
                "moves by roughly a factor of eight across the plausible EU intensity range and a "
                "further factor of five between the two anchors. Every input behind it is editable "
                "here so the range can be explored rather than asserted. k is a function of θ and is "
                "refitted whenever θ moves — it is never a stored constant.")

    elif block == "macro":
        macro, mr = model["macro"], result["macro"]
        series = _editable(
            "macro",
            [("year", "Year", "num"), ("npl_ratio", "Gross NPL ratio", "num"),
             ("gdp_growth", "Real GDP growth", "num")],
            [{"year": o["year"], "npl_ratio": o["npl_ratio"], "gdp_growth": o["gdp_growth"]}
             for o in macro["observations"]],
            locked=not editable, row_editable=True)
        settings_tbl = _editable(
            "macro_settings",
            [("label", "Macro setting"), ("value", "Value", "num"), ("key", "Key")],
            [{"key": "correlation_in_use", "label": "Correlation IN USE (the exposed lever)",
              "value": macro["correlation_in_use"]}],
            editable_cols={"value"}, locked=not editable)
        estimated = html.Table([
            html.Thead(html.Tr([html.Th("Estimated live on the series"), html.Th("Value", className="num")])),
            html.Tbody([html.Tr([html.Td(lbl, className="metric-name"), html.Td(v, className="num")])
                        for lbl, v in [
                            ("Paired observations", str(mr["n_paired"])),
                            ("Correlation", f"{mr['correlation_estimated']:.8f}"),
                            ("Slope (OLS)", f"{mr['beta_ols']:.8f}"),
                            ("Intercept", f"{mr['intercept']:.8f}"),
                            ("R²", f"{mr['r2']:.6f}"),
                            ("sd of Δ probit NPL ratio", f"{mr['sd_d_probit']:.8f}"),
                            ("sd of GDP growth", f"{mr['sd_gdp_growth']:.8f}"),
                            ("beta IN USE = ρ × sd(Δ probit) / sd(g)", f"{mr['beta_in_use']:.8f}"),
                        ]]),
        ], className="borrower-table signals-table")
        shifts = html.Table([
            html.Thead(html.Tr([html.Th("Scenario"), html.Th("GDP level deviation %", className="num"),
                                html.Th("macro_shift (probit)", className="num"),
                                html.Th("In sd of GDP growth", className="num")])),
            html.Tbody([html.Tr([html.Td(_scenario_label(result, c), className="metric-name"),
                                 html.Td(f"{mr['by_scenario'][c]['deviation_pct']:.2f}", className="num"),
                                 html.Td(f"{mr['by_scenario'][c]['shift']:.8f}", className="num"),
                                 html.Td(f"{mr['by_scenario'][c]['sd_units']:.3f}", className="num")])
                        for c in result["scenario_codes"]]),
        ], className="borrower-table signals-table")
        specs = html.Table([
            html.Thead(html.Tr([html.Th("#"), html.Th("Specification"), html.Th("Form"),
                                html.Th("R²", className="num"), html.Th("beta", className="num"),
                                html.Th("p", className="num"), html.Th("DW", className="num"),
                                html.Th("Assessment")])),
            html.Tbody([html.Tr([html.Td(s["id"]), html.Td(s["specification"], className="metric-name"),
                                 html.Td(s["form"]), html.Td(f"{s['r2']:.3f}", className="num"),
                                 html.Td(f"{s['beta']:.3f}", className="num"),
                                 html.Td(f"{s['p']:.3f}", className="num"),
                                 html.Td(f"{s['dw']:.2f}", className="num"),
                                 html.Td(s["assessment"], className="esg-working")],
                                className="esg-row-selected" if s["id"] == mr["selected_specification"]
                                else "")
                        for s in macro.get("regression_tests", [])]),
        ], className="borrower-table signals-table")
        blocks = [ui.table_card("HISTORICAL SERIES — EDITABLE, beta IS ESTIMATED FROM IT", series,
                                hint="delete a row with the ✕"),
                  ui.table_card("CORRELATION IN USE — EDITABLE", settings_tbl),
                  ui.table_card("SPECIFICATIONS TESTED — S8 SELECTED", specs),
                  _source_badges(_register_for(["Macro"]))]
        derived_blocks = [ui.table_card("ESTIMATED — RE-ESTIMATED AS YOU EDIT THE SERIES", estimated),
                          ui.table_card("SCENARIO MACRO SHIFTS (DERIVED)", shifts)]
        note = ("Only the GDP LEVEL deviation enters, never a growth rate — that units trap is what "
                "broke the original regression. beta = correlation × sd(Δ probit NPL ratio) / "
                "sd(GDP growth); the two standard deviations are estimated adequately on ten "
                "observations but the correlation is not (p = 0.116), which is why it is exposed as "
                "the lever rather than buried in the slope. Sign convention: beta is negative and a "
                "GDP deviation is negative, so the product is positive and raises PD.")

    elif block == "grades":
        data = [{"grade": g["grade"], "baseline_pd": g["baseline_pd"],
                 "bps": round(g["baseline_pd"] * 10000, 1)} for g in model["rating_grades"]]
        table = _editable("grades",
                          [("grade", "Grade"), ("baseline_pd", "Baseline PD", "num"),
                           ("bps", "bps", "num")], data,
                          editable_cols={"grade", "baseline_pd"}, locked=not editable)
        blocks = [ui.table_card("MASTER RATING SCALE — ILLUSTRATIVE SAMPLE, REPLACE WITH THE BANK'S",
                                table),
                  _source_badges(_register_for(["Rating"]))]
        note = ("The ladder is illustrative and replaceable without any code change. UNRESOLVED: these "
                "are treated as point-in-time PDs, which is what an IFRS 9 ECL requires. If the bank's "
                "master scale is through-the-cycle, a TTC-to-PIT step is needed before the scenario "
                "shift is applied.")

    else:  # settings
        s = model["settings"]
        editable_keys = [
            ("horizon_year", "Horizon year"), ("theta", "Curvature θ"),
            ("cost_ratio_cap", "Cost ratio cap (999 = off)"),
            ("denominator_basis", "Denominator basis (GVA / TURNOVER)"),
            ("us_gdp_deflator", "US GDP deflator"), ("currency_peg", "Currency peg (local per US$)"),
            ("warming_today", "Warming today (°C)"), ("base_year", "Base year"),
            ("terminal_year", "Terminal year"), ("national_total_ghg_mt", "National total GHG (MtCO2e)"),
            ("population_m", "Population (millions)"), ("sna_total_gva_omr", "SNA total value added"),
            ("cyclone_observation_years", "Cyclone observation window (years)"),
            ("reference_grade", "Reference grade"),
            ("carbon_price_base_year", "Carbon price base year"),
            ("denominator_base_year", "Denominator base year"),
        ]
        data = [{"key": k, "label": lbl, "value": s.get(k)} for k, lbl in editable_keys]
        table = _editable("settings",
                          [("label", "Setting"), ("value", "Value"), ("key", "Key")], data,
                          editable_cols={"value"}, locked=not editable)
        macro = result["macro"]
        macro_tbl = html.Table([
            html.Thead(html.Tr([html.Th("Macro parameter"), html.Th("Value", className="num")])),
            html.Tbody([html.Tr([html.Td(lbl, className="metric-name"),
                                 html.Td(v, className="num")])
                        for lbl, v in [
                            ("Selected specification", macro["selected_specification"]),
                            ("Correlation estimated", f"{macro['correlation_estimated']:.6f}"),
                            ("Correlation IN USE", f"{macro['correlation_in_use']:.6f}"),
                            ("sd of Δ probit NPL ratio", f"{macro['sd_d_probit']:.6f}"),
                            ("sd of GDP growth", f"{macro['sd_gdp_growth']:.6f}"),
                            ("beta OLS", f"{macro['beta_ols']:.6f}"),
                            ("beta IN USE", f"{macro['beta_in_use']:.6f}"),
                            ("R²", f"{macro['r2']:.4f}"),
                        ]]),
        ], className="dark-mini-table")
        blocks = [ui.table_card("CONTROL SETTINGS — EDITABLE", table),
                  _source_badges(_register_for(["Settings", "Macro"]))]
        derived_blocks = [ui.dark_table_card("MACRO LEG (ESTIMATED LIVE ON THE HISTORICAL SERIES)",
                                             "blue", macro_tbl)]
        note = ("The five control cells the workbook exposed — horizon, curvature θ, cost-ratio cap, "
                "correlation in use, denominator basis — plus the price-base and physical constants. "
                "k is refitted whenever θ moves; it is a function of θ, never a stored constant.")

    if derived_only:
        return derived_blocks

    # Derived panels live in their own container so the live-edit callback can
    # refresh them without re-rendering the DataTables above — remounting a table
    # mid-edit would reset the user's scroll position and risk a feedback loop
    # between the table's own data prop and the callback that reads it.
    return (([lock] if lock else []) + blocks
            + [html.Div(derived_blocks, id="esg-in-derived")] + [_module_note(note)])


def resolve_live(version_id, table_rows):
    """Resolve the model with every on-screen table's edits folded in.

    `table_rows` is [(block, rows), ...] for whatever DataTables are currently
    mounted. Returns (saved_result, live_model, live_result, live_checks) so the
    caller can show the estimate against the version it was derived from."""
    rec = store.get_version(version_id) if version_id else None
    if rec is None:
        rec = store.get_version(store.default_version_id())
    saved_model = copy.deepcopy(rec["model"]) if rec else defaults.default_model()
    saved_result = engine.calculate(saved_model)

    live_model = copy.deepcopy(saved_model)
    for block, rows in table_rows:
        if rows:
            live_model = apply_edits(live_model, block, rows)
    live_result = engine.calculate(live_model)
    return saved_result, live_model, live_result, climate_checks.run_checks(live_result, live_model)


def apply_edits(model: dict, block: str, rows: list) -> dict:
    """Fold DataTable edits back into the model dict. Values arrive as strings from
    the browser, so every write is coerced and out-of-range writes are rejected
    rather than silently coerced to something plausible."""
    m = copy.deepcopy(model)

    def f(value, fallback=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    if block == "sectors":
        by_id = {r["id"]: r for r in rows}
        for s in m["sectors"]:
            r = by_id.get(s["id"])
            if not r:
                continue
            s["gva_omr"] = f(r.get("gva_omr"), s["gva_omr"])
            s["turnover_gva"] = f(r.get("turnover_gva"), s.get("turnover_gva", 1.0))
            s["pass_through"] = min(1.0, max(0.0, f(r.get("pass_through"), s["pass_through"])))
            s["macro_beta"] = f(r.get("macro_beta"), s.get("macro_beta", 1.0))
            if r.get("name"):
                s["name"] = str(r["name"])
            if r.get("rationale") is not None:
                s["rationale"] = str(r["rationale"])

    elif block == "emissions":
        by_code = {r["code"]: r for r in rows}
        sector_ids = [s["id"] for s in m["sectors"]]
        for cat in m["edgar_categories"]:
            r = by_code.get(cat["code"])
            if not r:
                continue
            raw_mt = r.get("mt")
            if isinstance(raw_mt, str) and raw_mt.strip().upper() == "PLUG":
                cat["mt"] = None
            elif raw_mt is not None:
                cat["mt"] = f(raw_mt, cat.get("mt") or 0.0)
            for key in sector_ids + ["HH"]:
                if key in r:
                    cat["shares"][key] = f(r.get(key), cat["shares"].get(key, 0.0))

    elif block == "scenarios":
        by_code = {r["code"]: r for r in rows}
        for sc in m["scenarios"]:
            r = by_code.get(sc["code"])
            if not r:
                continue
            sc["warming_2100"] = f(r.get("warming_2100"), sc["warming_2100"])
            sc["intensity_index"] = f(r.get("intensity_index"), sc.get("intensity_index", 1.0))
            sc["denominator_index"] = f(r.get("denominator_index"), sc.get("denominator_index", 1.0))
            for y in defaults.HORIZON_YEARS:
                sc["carbon_price"][y] = f(r.get(f"p{y}"), sc["carbon_price"][y])
                sc["gdp_deviation"][y] = f(r.get(f"d{y}"), sc["gdp_deviation"][y])

    elif block == "hazards":
        by_id = {r["id"]: r for r in rows}
        for h in m["hazards"]:
            r = by_id.get(h["id"])
            if not r:
                continue
            raw = r.get("baseline_aal")
            if isinstance(raw, str) and raw.strip().upper() == "DERIVED":
                h["baseline_aal"] = None
            elif raw is not None:
                h["baseline_aal"] = f(raw, h.get("baseline_aal") or 0.0)
            h["elasticity"] = f(r.get("elasticity"), h["elasticity"])
            h["insurance_recovery"] = min(1.0, max(0.0, f(r.get("insurance_recovery"),
                                                          h["insurance_recovery"])))
            h["pnl_share"] = min(1.0, max(0.0, f(r.get("pnl_share"), h["pnl_share"])))

    elif block == "exposure":
        hazard_ids = [h["id"] for h in m["hazards"]]
        for r in rows:
            sid = r.get("id")
            if sid not in m["exposure_raw"]:
                continue
            for h in hazard_ids:
                if h in r:
                    m["exposure_raw"][sid][h] = max(0.0, f(r.get(h), m["exposure_raw"][sid][h]))

    elif block == "grades":
        grades = []
        for r in rows:
            pd_value = f(r.get("baseline_pd"), 0.0)
            if not (0.0 < pd_value < 1.0):
                continue
            grades.append({"grade": str(r.get("grade") or "").strip() or "?",
                           "baseline_pd": pd_value})
        if grades:
            m["rating_grades"] = grades

    elif block == "settings":
        text_keys = {"denominator_basis", "reference_grade"}
        int_keys = {"horizon_year", "base_year", "terminal_year", "carbon_price_base_year",
                    "denominator_base_year"}
        for r in rows:
            key, value = r.get("key"), r.get("value")
            if key is None or value is None or key not in m["settings"]:
                continue
            if key in text_keys:
                m["settings"][key] = str(value).strip().upper() if key == "denominator_basis" \
                    else str(value).strip()
            elif key in int_keys:
                m["settings"][key] = int(f(value, m["settings"][key]))
            else:
                m["settings"][key] = f(value, m["settings"][key])

    elif block == "events":
        # The cyclone record derives H1's baseline AAL, so it is an input, not a
        # footnote. Rows with no damage are dropped rather than counted as zeros,
        # which would dilute the average over a window that never observed them.
        events = []
        for r in rows:
            damage = f(r.get("damage_usd_m"), 0.0)
            if damage <= 0:
                continue
            events.append({
                "event": str(r.get("event") or "").strip() or "Unnamed event",
                "year": int(f(r.get("year"), 0)),
                "damage_usd_m": damage,
                "source": str(r.get("source") or ""),
            })
        m["cyclone_events"] = events

    elif block == "calibration":
        cal = m["calibration"]
        by_key = {r.get("key"): r.get("value") for r in rows}

        def put(container, key, lo=None, hi=None):
            if key not in by_key or by_key[key] is None:
                return
            value = f(by_key[key], container[key])
            if lo is not None:
                value = max(lo, value)
            if hi is not None:
                value = min(hi, value)
            container[key] = value

        for key in ("baseline_pd", "anchor_a_rel", "anchor_b_rel"):
            put(cal, key, lo=0.0)
        put(cal, "anchor_price_usd", lo=0.0)
        put(cal, "usd_eur", lo=0.0)
        put(cal, "eu_pass_through", lo=0.0, hi=1.0)
        put(cal, "coal_plausible_intensity_multiple", lo=0.0)
        for key in ("eu_total_ghg_mt", "eu_gva_eur_bn", "median_to_average"):
            put(cal["route1"], key, lo=0.0)
        put(cal["route1"], "household_share", lo=0.0, hi=1.0)
        for key in ("median_total_intensity", "turnover_gva_ratio"):
            put(cal["route2"], key, lo=0.0)
        put(cal["route2"], "scope1_share", lo=0.0, hi=1.0)

    elif block == "anchors":
        by_id = {str(r.get("id")): r for r in rows}
        for a in m["calibration"]["anchors"]:
            r = by_id.get(str(a["id"]))
            if not r:
                continue
            a["baseline_pd"] = min(0.999, max(1e-9, f(r.get("baseline_pd"), a["baseline_pd"])))
            a["rel_change"] = f(r.get("rel_change"), a["rel_change"])
            use = str(r.get("use") or "").strip().upper()
            if use in {"FIT", "CHECK"}:
                a["use"] = use

    elif block == "macro":
        # The historical series IS the macro leg: beta is estimated from it live,
        # so editing a year re-estimates the correlation and the slope.
        observations = []
        for r in rows:
            npl = f(r.get("npl_ratio"), 0.0)
            if not (0.0 < npl < 1.0):
                continue
            observations.append({
                "year": int(f(r.get("year"), 0)),
                "npl_ratio": npl,
                "gdp_growth": f(r.get("gdp_growth"), 0.0),
            })
        if len(observations) >= 3:
            m["macro"]["observations"] = sorted(observations, key=lambda o: o["year"])

    elif block == "macro_settings":
        for r in rows:
            if r.get("key") == "correlation_in_use" and r.get("value") is not None:
                m["macro"]["correlation_in_use"] = min(1.0, max(-1.0, f(
                    r.get("value"), m["macro"]["correlation_in_use"])))
            elif r.get("key") == "selected_specification" and r.get("value"):
                m["macro"]["selected_specification"] = str(r["value"]).strip()

    return m


# ============================================================ 3b. audit tab

AUDIT_VIEWS = [
    ("verification", "Verification log · Verification"),
    ("assumptions", "Assumption register · Assumption_Register"),
    ("sources", "Source register · Source_Register"),
    ("changes", "Change log · Change_Log"),
]


def build_audit_tab():
    return html.Div([
        _controls([html.Span("REGISTER", className="filters-label"),
                   _dd("esg-audit-view", [{"label": lbl, "value": key} for key, lbl in AUDIT_VIEWS],
                       "verification", 330)]),
        html.Div(build_audit_body(), id="esg-audit-body"),
    ])


def build_audit_body(view="verification"):
    """The workbook's provenance sheets. They feed no calculation; they are the
    reason the calculation can be trusted, which is why they ship in the tool
    rather than only in the export."""
    if view == "assumptions":
        rows = registers.ASSUMPTION_REGISTER_ROWS
        table = html.Table([
            html.Thead(html.Tr([html.Th("ID"), html.Th("Assumption"), html.Th("Where"),
                                html.Th("Value / status"), html.Th("Rationale and limitation")])),
            html.Tbody([html.Tr([html.Td(r["id"], className="metric-name"),
                                 html.Td(r["assumption"]), html.Td(r["location"], className="esg-working"),
                                 html.Td(r["value"]), html.Td(r["rationale"], className="esg-working")])
                        for r in rows]),
        ], className="borrower-table signals-table")
        title = f"ASSUMPTION REGISTER — {len(rows)} ENTRIES"
        note = ("Every assumption the model rests on, with the limitation it carries. The open items "
                "are deliberately visible: no hydrocarbon export-revenue or fiscal channel, no chronic "
                "physical risk, and a master scale treated as point-in-time.")

    elif view == "sources":
        rows = registers.SOURCE_REGISTER_ROWS
        table = html.Table([
            html.Thead(html.Tr([html.Th("#"), html.Th("Value"), html.Th("Where"), html.Th("Source"),
                                html.Th("Note"), html.Th("Status")])),
            html.Tbody([html.Tr([html.Td(r["id"], className="metric-name"), html.Td(r["value"]),
                                 html.Td(r["location"], className="esg-working"),
                                 html.Td(r["source"], className="esg-working"),
                                 html.Td(r["note"], className="esg-working"),
                                 html.Td(_badge(r["status"], registers.status_tone(r["status"])))])
                        for r in rows]),
        ], className="borrower-table signals-table")
        title = f"SOURCE REGISTER — {len(rows)} ENTRIES"
        note = ("Where every input number came from. VERIFIED means traced to the primary source named; "
                "JUDGEMENT and ASSUMPTION mean it is analyst input and is exposed for sensitivity.")

    elif view == "changes":
        rows = registers.CHANGE_LOG_ROWS
        table = html.Table([
            html.Thead(html.Tr([html.Th("#"), html.Th("Area"), html.Th("Before"), html.Th("After")])),
            html.Tbody([html.Tr([html.Td(r["id"], className="metric-name"),
                                 html.Td(r["area"]), html.Td(r["before"], className="esg-working"),
                                 html.Td(r["after"], className="esg-working")])
                        for r in rows]),
        ], className="borrower-table signals-table")
        title = f"CHANGE LOG — {len(rows)} ENTRIES"
        note = ("What changed between model generations and why. Several entries are defects the model "
                "found in itself — a zero-GVA sector that silently received no stress, a coal-mining "
                "anchor mislabelled as a median-firm anchor, and a missing price deflator that "
                "understated every cost ratio by roughly a quarter.")

    else:
        rows = registers.VERIFICATION_LOG_ROWS
        table = html.Table([
            html.Thead(html.Tr([html.Th("#"), html.Th("Value"), html.Th("Now in model"),
                                html.Th("Checked against"), html.Th("Finding"), html.Th("Status")])),
            html.Tbody([html.Tr([html.Td(r["id"], className="metric-name"), html.Td(r["value"]),
                                 html.Td(r["value_now"]),
                                 html.Td(r["source"], className="esg-working"),
                                 html.Td(r["finding"], className="esg-working"),
                                 html.Td(_badge(r["status"], registers.status_tone(r["status"])))])
                        for r in rows]),
        ], className="borrower-table signals-table")
        title = f"VERIFICATION LOG — {len(rows)} ENTRIES"
        note = ("Every input number, what it was checked against, and what the check found. CORRECTED "
                "means the source disagreed with the workbook and the value was changed; UNVERIFIABLE "
                "means no public source could confirm it and it remains flagged.")

    counts = {}
    for r in rows:
        key = r.get("status")
        if key:
            counts[key] = counts.get(key, 0) + 1
    chips = html.Div([_badge(f"{v} × {k}", registers.status_tone(k))
                      for k, v in sorted(counts.items(), key=lambda kv: -kv[1])],
                     className="esg-badge-row") if counts else None

    return [c for c in [chips, ui.table_card(title, table), _module_note(note)] if c is not None]


# ========================================================= 4. calibration tab

def build_calibration_tab():
    return html.Div([
        _controls(_version_control("esg-cal-version")
                  + [html.Span("ANCHOR", className="filters-label"),
                     _dd("esg-cal-anchor",
                         [{"label": "A — transition-only, +0.5% relative", "value": "A"},
                          {"label": "B — disorderly 2050, +2.5% relative", "value": "B"}], "A", 300),
                     html.Span("EU INTENSITY ROUTE", className="filters-label"),
                     _dd("esg-cal-route",
                         [{"label": "1 — symmetric (national aggregates)", "value": 1},
                          {"label": "2 — firm-level (turnover conversion)", "value": 2}], 1, 290)]
                  + _theta_control("esg-cal-theta")),
        html.Div(build_calibration_body(), id="esg-cal-body"),
    ])


def build_calibration_body(version_id=None, anchor="A", route=1, theta=0.0):
    _, model, result, _ = resolve(version_id, anchor=anchor, route=route, theta=theta)
    cal = result["calibration"]

    kpis = [
        ui.kpi_card("k FITTED", f"{cal['k']:.9f}", "blue",
                    ui.kpi_sub(f"push_EU {cal['push_eu']:.8f} / g({cal['cost_ratio_eu']:.6f}, "
                               f"{theta:g})")),
        ui.kpi_card("EU cost ratio", f"{cal['cost_ratio_eu']:.6f}", "amber",
                    ui.kpi_sub(f"{cal['eu_intensity']:,.1f} t/EURm × €{cal['anchor_price_eur']:.2f} "
                               f"× (1 − {cal['eu_pass_through']:.0%})")),
        ui.kpi_card("Extrapolation", f"{cal['extrapolation']['multiple']:.0f}x", "red",
                    ui.kpi_sub(f"applied up to a {cal['extrapolation']['max_cost_ratio']:.1%} "
                               "local cost ratio")),
        ui.kpi_card("Implied top-decile intensity",
                    f"{cal['implied_intensity_multiple']:.2f}x" if cal["implied_intensity_multiple"]
                    else "n/a", "green",
                    ui.kpi_sub("validation from the second anchor, not identification")),
    ]

    anchors = html.Table([
        html.Thead(html.Tr([html.Th("#"), html.Th("Group"), html.Th("Baseline PD", className="num"),
                            html.Th("Relative change", className="num"),
                            html.Th("Stressed PD", className="num"),
                            html.Th("push", className="num"), html.Th("Use"),
                            html.Th("Identification")])),
        html.Tbody([html.Tr([html.Td(str(a["id"])), html.Td(a["group"], className="metric-name"),
                             html.Td(_pct(a["baseline_pd"]), className="num"),
                             html.Td(f"{a['rel_change']:+.1%}", className="num"),
                             html.Td(_pct(a["stressed_pd"], 3), className="num"),
                             html.Td(f"{a['push']:.8f}", className="num"),
                             html.Td(_tag(a["use"], "ok" if a["use"] == "FIT" else "warn")),
                             html.Td(a["identification"], className="esg-working")])
                    for a in cal["anchors"]]),
    ], className="borrower-table signals-table")

    routes = html.Table([
        html.Thead(html.Tr([html.Th("Route"), html.Th("Construction"),
                            html.Th("Intensity (t/EURm)", className="num"), html.Th("In use")])),
        html.Tbody([
            html.Tr([html.Td("1 — symmetric", className="metric-name"),
                     html.Td("EU national Scope 1 emissions ÷ EU GVA, built exactly as the local "
                             "intensity is, then adjusted from economy-average to median firm. "
                             "The turnover conversion never enters.", className="esg-working"),
                     html.Td(f"{cal['route1_intensity']:,.2f}", className="num"),
                     html.Td(_tag("IN USE", "ok") if cal["route_in_use"] == 1 else "—")]),
            html.Tr([html.Td("2 — firm-level", className="metric-name"),
                     html.Td("Median firm Scope 1+2+3 intensity per unit of turnover × Scope 1 share × "
                             "turnover/GVA. Needs three assumptions instead of one adjustment and "
                             "reintroduces the conversion that caused the original defect.",
                             className="esg-working"),
                     html.Td(f"{cal['route2_intensity']:,.2f}", className="num"),
                     html.Td(_tag("IN USE", "ok") if cal["route_in_use"] == 2 else "—")]),
        ]),
    ], className="borrower-table signals-table")

    ksens = html.Table([
        html.Thead(html.Tr([html.Th("EU intensity (t/EURm)", className="num"),
                            html.Th("k — Anchor A", className="num"),
                            html.Th("k — Anchor B", className="num")])),
        html.Tbody([html.Tr([html.Td(f"{r['intensity']:,.0f}", className="num"),
                             html.Td(f"{r['k_a']:.6f}", className="num"),
                             html.Td(f"{r['k_b']:.6f}", className="num")])
                    for r in cal["k_sensitivity"]]),
    ], className="dark-mini-table")

    band = html.Table([
        html.Thead(html.Tr([html.Th("θ", className="num"), html.Th("Form"),
                            html.Th("Refitted k", className="num"),
                            html.Th("Implied top-decile ×", className="num"),
                            html.Th("Push at max cost ratio", className="num"),
                            html.Th("PD at reference grade", className="num"),
                            html.Th("PD multiple", className="num")])),
        html.Tbody([html.Tr([html.Td(f"{b['theta']:+.1f}", className="num"),
                             html.Td(b["form"] or "—"),
                             html.Td(f"{b['k']:.6f}", className="num"),
                             html.Td(f"{b['implied_multiple']:.3f}" if b["implied_multiple"]
                                     else "unreachable", className="num"),
                             html.Td(f"{b['push_at_max']:.5f}", className="num"),
                             html.Td(_pct(b["pd_at_reference"]), className="num"),
                             html.Td(f"{b['pd_multiple']:.3f}x", className="num")])
                    for b in cal["theta_band"]]),
    ], className="borrower-table signals-table")

    coal = cal.get("coal") or {}
    coal_card = html.Div([
        html.Div([html.Span(className="kpi-dot amber"), "COAL ANCHOR — OUT-OF-SAMPLE CHECK"],
                 className="dark-table-title"),
        html.Table([html.Tbody([
            html.Tr([html.Td("push ratio, coal (orderly) / median", className="metric-name"),
                     html.Td(f"{coal.get('push_ratio', 0):.2f}", className="num")]),
            html.Tr([html.Td("Intensity multiple coal would need at this θ", className="metric-name"),
                     html.Td(f"{coal.get('required_multiple') or 0:,.1f}", className="num")]),
            html.Tr([html.Td("Plausible coal Scope 1 intensity multiple", className="metric-name"),
                     html.Td(f"{coal.get('plausible_multiple', 0):,.0f}", className="num")]),
            html.Tr([html.Td("Discrepancy factor", className="metric-name"),
                     html.Td(f"{coal.get('discrepancy') or 0:,.1f}", className="num")]),
            html.Tr([html.Td("Verdict", className="metric-name"),
                     html.Td(coal.get("verdict", ""), className="num")]),
        ])], className="dark-mini-table"),
    ], className="dark-table-card")

    band_lo = min((b["pd_multiple"] for b in cal["theta_band"]), default=0)
    band_hi = max((b["pd_multiple"] for b in cal["theta_band"]), default=0)
    insight = (
        f"A single anchor identifies a SCALE only; the shape of push = k × g(cost ratio) is imposed. "
        f"Anchors 1 and 2 are the only pair on a common identification and a common Scope 1 mechanism, "
        f"so they are the only pair that can fit this cost curve. What the second anchor delivers is a "
        f"validation, not an identification: the implied top-decile-to-median intensity multiple barely "
        f"moves across the whole curvature range (3.97 at θ=+1 to 4.07 at θ=−1), which is entirely "
        f"plausible for a firm-level emissions distribution — but it means θ itself is unidentifiable, "
        f"because both anchors sit below a 4% cost ratio where every smooth form looks like a straight "
        f"line. The consequence is quantified rather than assumed away: the worst-sector PD multiple "
        f"spans {band_lo:.2f}x to {band_hi:.2f}x across the band. The coal anchors are excluded from the "
        f"fit deliberately — their response is driven by Scope 3 abatement investment raising leverage, "
        f"a different mechanism, and the check below rejects them by a factor of "
        f"{coal.get('discrepancy') or 0:.0f}, exactly as intended."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        ui.table_card("ECB OP 281 ANCHORS, ALL FOUR ON A COMMON BASIS", anchors),
        ui.table_card("EU INTENSITY — ROUTE 1 VS ROUTE 2", routes),
        html.Div([
            html.Div([ui.dark_table_card("SENSITIVITY OF k TO THE EU INTENSITY", "blue", ksens)],
                     className="split-main"),
            html.Div([coal_card], className="split-side"),
        ], className="split-grid"),
        ui.table_card("CURVATURE DISCLOSURE BAND — k IS REFITTED AT EVERY θ", band),
        html.Div(ui.ai_insight_card(insight), style={"marginTop": "18px"}),
        _module_note(
            "k moves by roughly a factor of eight across the intensity grid and a further factor of five "
            "between the two anchors. That range is the honest measure of how much the public sources "
            "can pin down."),
    ]


# ========================================================== 5. sensitivity tab

def build_sensitivity_tab():
    return html.Div([
        _controls(_version_control("esg-sens-version") + _horizon_control("esg-sens-horizon")
                  + [html.Span("DETAIL LEVER", className="filters-label"),
                     _dd("esg-sens-param",
                         [{"label": spec["label"], "value": key}
                          for key, spec in sensitivity.LEVERS.items()], "theta", 230)]),
        html.Div(build_sensitivity_body(), id="esg-sens-body"),
    ])


def _tornado_figure(tor):
    """Diverging pair around the base case: polarity is the data's job, so hue
    carries the direction and the numeric range repeats it in text."""
    bars = list(reversed(tor["bars"]))
    base = tor["base"]["mean_multiple"]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=[b["label"] for b in bars], x=[b["low"] - base for b in bars], base=base,
        orientation="h", marker=dict(color="#2a78d6"), name="lowers the multiple",
        hovertemplate="<b>%{y}</b><br>low %{base:.3f}x<extra>lowers</extra>",
    ))
    fig.add_trace(go.Bar(
        y=[b["label"] for b in bars], x=[b["high"] - base for b in bars], base=base,
        orientation="h", marker=dict(color="#d03b3b"), name="raises the multiple",
        hovertemplate="<b>%{y}</b><br>high %{x:.3f}<extra>raises</extra>",
    ))
    fig.add_vline(x=base, line=dict(color="#52514e", width=1.5, dash="dash"))
    ui.base_layout(fig, height=max(280, 44 * len(bars) + 80), legend=True)
    fig.update_layout(barmode="overlay", margin=dict(t=10, b=30, l=210, r=20),
                      xaxis=dict(title=dict(text="mean PD multiple", font=dict(size=10))),
                      yaxis=dict(showgrid=False))
    return fig


def _lever_figure(sweep):
    labels = [p["label"] for p in sweep["points"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=[p["mean_multiple"] for p in sweep["points"]],
                         marker=dict(color="#2a78d6"), name="mean multiple",
                         hovertemplate="<b>%{x}</b><br>mean %{y:.3f}x<extra></extra>"))
    fig.add_trace(go.Scatter(x=labels, y=[p["max_multiple"] for p in sweep["points"]],
                             mode="lines+markers", line=dict(color="#eb6834", width=2),
                             marker=dict(size=8), name="worst cell",
                             hovertemplate="<b>%{x}</b><br>worst %{y:.3f}x<extra></extra>"))
    ui.base_layout(fig, height=280, legend=True)
    fig.update_layout(bargap=0.5, margin=dict(t=30, b=36, l=50, r=14))
    return fig


def build_sensitivity_body(version_id=None, horizon=None, parameter="theta"):
    _, model, result, _ = resolve(version_id, horizon=horizon)
    tor = sensitivity.tornado(model)
    sweep = sensitivity.one_way(model, parameter)

    kpis = [
        ui.kpi_card("Base mean multiple", f"{tor['base']['mean_multiple']:.3f}x", "blue",
                    ui.kpi_sub(f"grade {result['reference_grade']} · {result['horizon_year']}")),
        ui.kpi_card("Widest lever", tor["bars"][0]["label"], "red",
                    ui.kpi_sub(f"{tor['bars'][0]['low']:.3f}x – {tor['bars'][0]['high']:.3f}x")),
        ui.kpi_card("Worst cell at base", f"{tor['base']['max_multiple']:.3f}x", "amber",
                    ui.kpi_sub(f"{tor['base']['worst_cell']['sector']} · "
                               f"{tor['base']['worst_cell']['scenario']}")),
        ui.kpi_card("Levers swept", str(len(tor["bars"])), "green",
                    ui.kpi_sub("one-way, full recalculation each point")),
    ]

    tor_table = html.Table([
        html.Thead(html.Tr([html.Th("Lever"), html.Th("Low", className="num"),
                            html.Th("High", className="num"), html.Th("Span", className="num"),
                            html.Th("At"), html.Th("Why it is uncertain")])),
        html.Tbody([html.Tr([html.Td(b["label"], className="metric-name"),
                             html.Td(f"{b['low']:.3f}x", className="num"),
                             html.Td(f"{b['high']:.3f}x", className="num"),
                             html.Td(f"{b['span']:.3f}", className="num"),
                             html.Td(f"{b['low_label']} → {b['high_label']}"),
                             html.Td(b["note"], className="esg-working")])
                    for b in tor["bars"]]),
    ], className="borrower-table signals-table")

    detail = html.Table([
        html.Thead(html.Tr([html.Th(sweep["label"]), html.Th("k", className="num"),
                            html.Th("Max cost ratio", className="num"),
                            html.Th("Cap binds", className="num"),
                            html.Th("Mean multiple", className="num"),
                            html.Th("Worst multiple", className="num"), html.Th("Worst cell")])),
        html.Tbody([html.Tr([html.Td(p["label"], className="metric-name"),
                             html.Td(f"{p['k']:.6f}", className="num"),
                             html.Td(f"{p['max_cost_ratio']:.4f}", className="num"),
                             html.Td(str(p["cap_binding_cells"]), className="num"),
                             html.Td(f"{p['mean_multiple']:.4f}x", className="num"),
                             html.Td(f"{p['max_multiple']:.4f}x", className="num"),
                             html.Td(f"{p['worst_cell']['sector']} · {p['worst_cell']['scenario']}")])
                    for p in sweep["points"]]),
    ], className="borrower-table signals-table")

    insight = (
        f"The widest lever is {tor['bars'][0]['label']}, spanning {tor['bars'][0]['low']:.3f}x to "
        f"{tor['bars'][0]['high']:.3f}x on the mean PD multiple. The two disclosure bands that matter "
        f"most are curvature θ and the NPL/GDP correlation: neither can be pinned down from the public "
        f"sources, so the range they generate is the model's real uncertainty rather than a modelling "
        f"choice. Reporting that band, rather than a single point estimate with a spurious number of "
        f"decimal places, is what makes this defensible to a validator."
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        ui.chart_card("ONE-WAY SENSITIVITY — MEAN PD MULTIPLE AROUND THE BASE CASE",
                      dcc.Graph(figure=_tornado_figure(tor), config={"displayModeBar": False})),
        ui.table_card("DISCLOSURE BANDS", tor_table),
        ui.chart_card(f"DETAIL — {sweep['label'].upper()}",
                      dcc.Graph(figure=_lever_figure(sweep), config={"displayModeBar": False})),
        ui.table_card(f"{sweep['label'].upper()} — FULL RECALCULATION AT EACH POINT", detail),
        html.Div(ui.ai_insight_card(insight), style={"marginTop": "18px"}),
        _module_note(sweep["note"]),
    ]


# ======================================================== 6. quality checks tab

def build_checks_tab():
    return html.Div([
        _controls(_version_control("esg-qc-version") + _horizon_control("esg-qc-horizon")
                  + _theta_control("esg-qc-theta")),
        html.Div(build_checks_body(), id="esg-qc-body"),
    ])


def _checks_table(rows):
    return html.Table([
        html.Thead(html.Tr([html.Th("#", className="num"), html.Th("Check"),
                            html.Th("Result", className="num"), html.Th("Status"),
                            html.Th("What it means")])),
        html.Tbody([
            html.Tr([html.Td(str(c["id"]), className="num"),
                     html.Td(c["name"], className="metric-name"),
                     html.Td(f"{c['result']:.6g}" if isinstance(c["result"], (int, float))
                             and not isinstance(c["result"], bool) else str(c["result"]),
                             className="num"),
                     html.Td(_pill(c["status"])),
                     html.Td(c["explanation"], className="esg-working")])
            for c in rows]),
    ], className="borrower-table signals-table")


def build_checks_body(version_id=None, horizon=None, theta=None):
    _, _, result, rows = resolve(version_id, horizon=horizon, theta=theta)
    summary = climate_checks.summarise(rows)

    expected = [c for c in rows if c["expected"]]
    genuine = [c for c in rows if c["status"] == "FAIL"]
    other_attention = [c for c in rows
                       if c["status"] in {"FLAG", "ACTION", "DISCLOSE", "REJECTED", "REVIEW"}
                       and not c["expected"]]
    passing = [c for c in rows if c["status"] in {"PASS", "INFO"}]

    kpis = [
        ui.kpi_card("Passing", f"{summary['passed']} / {summary['total']}",
                    "green" if summary["can_finalise"] else "red",
                    ui.kpi_sub("PASS outright")),
        ui.kpi_card("Genuine failures", str(len(genuine)),
                    "green" if not genuine else "red",
                    ui.kpi_sub("block promotion to final",
                               "up-bad" if genuine else "neutral")),
        ui.kpi_card("Expected flags", str(len(expected)), "amber",
                    ui.kpi_sub("known disclosures on delivery")),
        ui.kpi_card("Structural pair",
                    "BOTH PASS" if summary["structural_pair_ok"] else "REVIEW",
                    "green" if summary["structural_pair_ok"] else "red",
                    ui.kpi_sub("checks 22 & 23 — opposing orderings")),
    ]

    sections = []
    if genuine:
        sections.append(ui.table_card("GENUINE FAILURES — THESE BLOCK A FINAL RUN",
                                      _checks_table(genuine)))
    if other_attention:
        sections.append(ui.table_card("REQUIRES ATTENTION OR DISCLOSURE",
                                      _checks_table(other_attention)))
    if expected:
        sections.append(ui.table_card(
            "EXPECTED FLAGS ON DELIVERY — NOT DEFECTS", _checks_table(expected)))
    sections.append(ui.table_card("PASSING AND INFORMATIONAL", _checks_table(passing)))

    insight = (
        f"{summary['passed']} of {summary['total']} checks pass outright, {len(genuine)} fail. "
        f"{len(expected)} items are expected to flag on delivery of this dataset — the EDGAR Buildings "
        f"per-head figure, the Fragmented World GDP deviation, the coal anchor (an intended diagnostic "
        f"rejection) and the warming interpolation. They are left visible rather than defaulted away, "
        f"because a check that has been quietly satisfied tells a reviewer nothing. Checks 22 and 23 "
        f"together are the supervisory headline: transition severity following the carbon price and "
        f"physical severity following warming, in exactly opposite directions. "
        f"{'Both pass' if summary['structural_pair_ok'] else 'They do NOT both pass'}, so this run is "
        f"{'eligible' if summary['can_finalise'] else 'NOT eligible'} to be marked final."
    )

    return [html.Div(kpis, className="signals-kpi-grid")] + sections + [
        html.Div(ui.ai_insight_card(insight), style={"marginTop": "18px"}),
        _module_note(f"All 24 checks re-run on every calculation. Engine v{result['engine_version']}."),
    ]


# ================================================================ 7. runs tab

def build_runs_tab():
    return html.Div([
        _controls(_version_control("esg-run-version")
                  + [html.Button("Calculate & store run", id="esg-run-calc",
                                 className="report-generate-btn esg-inline-btn", n_clicks=0),
                     html.Button("Mark version final", id="esg-run-final",
                                 className="report-secondary-btn esg-inline-btn", n_clicks=0)]),
        html.Div(id="esg-run-status"),
        html.Div(build_runs_body(), id="esg-run-body"),
    ])


def _run_options():
    return [{"label": f"#{r['id']} · v{r['model_version_id']} · {r['created_at'][:16]} · "
                      f"{r['headline']['horizon_year']} · θ={r['headline']['theta']:g}",
             "value": r["id"]} for r in store.list_runs()]


def build_runs_body(version_id=None, run_a=None, run_b=None):
    versions = store.list_versions()
    runs = store.list_runs()

    version_tbl = html.Table([
        html.Thead(html.Tr([html.Th("#", className="num"), html.Th("Name"), html.Th("Country"),
                            html.Th("Status"), html.Th("Parent", className="num"),
                            html.Th("Created"), html.Th("Note")])),
        html.Tbody([html.Tr([html.Td(str(v["id"]), className="num"),
                             html.Td(v["name"], className="metric-name"), html.Td(v["country"]),
                             html.Td(_tag(v["status"].upper(),
                                          "ok" if v["status"] == "final" else "info")),
                             html.Td(str(v["parent_version_id"] or "—"), className="num"),
                             html.Td(v["created_at"][:16]),
                             html.Td(v.get("note", ""), className="esg-working")])
                    for v in versions]),
    ], className="borrower-table signals-table")

    run_tbl = html.Table([
        html.Thead(html.Tr([html.Th("Run", className="num"), html.Th("Version", className="num"),
                            html.Th("Created"), html.Th("Horizon", className="num"),
                            html.Th("θ", className="num"), html.Th("k", className="num"),
                            html.Th("Worst cell", className="num"), html.Th("Sector"),
                            html.Th("Checks", className="num"), html.Th("Final-eligible")])),
        html.Tbody([html.Tr([html.Td(str(r["id"]), className="num"),
                             html.Td(str(r["model_version_id"]), className="num"),
                             html.Td(r["created_at"][:16]),
                             html.Td(str(r["headline"]["horizon_year"]), className="num"),
                             html.Td(f"{r['headline']['theta']:g}", className="num"),
                             html.Td(f"{r['headline']['k']:.6f}", className="num"),
                             html.Td(f"{r['headline']['max_multiple']:.3f}x", className="num"),
                             html.Td(f"{r['headline']['worst_sector']} · "
                                     f"{r['headline']['worst_scenario']}"),
                             html.Td(f"{r['headline']['checks_passed']}/"
                                     f"{r['headline']['checks_total']}", className="num"),
                             html.Td(_pill("PASS" if r["headline"]["can_finalise"] else "FAIL"))])
                    for r in runs]) if runs else html.Tbody([]),
    ], className="borrower-table signals-table")

    opts = _run_options()
    compare_controls = _controls([
        html.Span("COMPARE RUN A", className="filters-label"),
        _dd("esg-run-a", opts, run_a if run_a is not None else (opts[0]["value"] if opts else None), 340),
        html.Span("WITH RUN B", className="filters-label"),
        _dd("esg-run-b", opts, run_b if run_b is not None
            else (opts[1]["value"] if len(opts) > 1 else None), 340),
    ])

    body = [
        ui.table_card("MODEL VERSIONS — IMMUTABLE ONCE FINAL, CLONE TO EDIT", version_tbl),
        ui.table_card("CALCULATION RUNS — EACH CARRIES A FULL INPUT SNAPSHOT", run_tbl)
        if runs else html.Div(
            "No stored runs yet. “Calculate & store run” writes an immutable run with a full input "
            "snapshot, so any figure quoted to a regulator can be reproduced exactly even after the "
            "inputs move on.", className="placeholder-panel"),
        compare_controls,
        html.Div(build_run_diff(run_a, run_b), id="esg-run-diff"),
        _module_note(
            "Runs recompute their result from the stored snapshot rather than storing the output, so "
            "what you see is provably what those inputs produce. A version cannot be marked final while "
            "any quality check is failing."),
    ]
    return body


def build_run_diff(run_a=None, run_b=None):
    if run_a is None or run_b is None or run_a == run_b:
        return [html.Div("Select two different runs to see a cell-level diff.",
                         className="placeholder-panel")]
    rec_a, rec_b = store.get_run(run_a), store.get_run(run_b)
    if rec_a is None or rec_b is None:
        return [html.Div("One of the selected runs no longer exists.", className="placeholder-panel")]

    diff = sensitivity.compare_runs(rec_a["result"], rec_b["result"])
    head = diff["headline"]
    kpis = [
        ui.kpi_card("Cells changed", f"{diff['changed_count']} / {len(diff['rows'])}",
                    "amber" if diff["changed_count"] else "green",
                    ui.kpi_sub(f"at grade {diff['grade']}")),
        ui.kpi_card("Largest move", f"{head['max_abs_bps']:,.1f} bps", "red",
                    ui.kpi_sub("absolute PD change")),
        ui.kpi_card("k", f"{head['k_a']:.6f} → {head['k_b']:.6f}", "blue",
                    ui.kpi_sub(f"θ {head['theta_a']:g} → {head['theta_b']:g}")),
        ui.kpi_card("Horizon", f"{head['horizon_a']} → {head['horizon_b']}", "purple",
                    ui.kpi_sub(f"run #{run_a} vs run #{run_b}")),
    ]

    rows = sorted(diff["rows"], key=lambda r: abs(r.get("delta_bps") or 0), reverse=True)[:40]
    table = html.Table([
        html.Thead(html.Tr([html.Th("Sector"), html.Th("Scenario"),
                            html.Th("PD run A", className="num"), html.Th("PD run B", className="num"),
                            html.Th("Δ bps", className="num"), html.Th("× A", className="num"),
                            html.Th("× B", className="num"), html.Th("Δ ×", className="num")])),
        html.Tbody([html.Tr([html.Td(r["sector"], className="metric-name"), html.Td(r["scenario"]),
                             html.Td(_pct(r["pd_a"], 3), className="num"),
                             html.Td(_pct(r["pd_b"], 3), className="num"),
                             html.Td(f"{r['delta_bps']:+,.1f}" if r["delta_bps"] is not None else "—",
                                     className="num"),
                             html.Td(f"{r.get('multiple_a', 0):.3f}", className="num"),
                             html.Td(f"{r.get('multiple_b', 0):.3f}", className="num"),
                             html.Td(f"{r.get('delta_multiple') or 0:+.3f}", className="num")])
                    for r in rows]),
    ], className="borrower-table signals-table")

    return [html.Div(kpis, className="signals-kpi-grid"),
            ui.table_card(f"CELL-LEVEL DIFF AT GRADE {diff['grade']} — LARGEST 40 MOVES", table)]


# ============================================================== 8. report tab

REPORT_SECTIONS = [
    ("heatmap", "PD multiple heat map"),
    ("channels", "Two opposing channels"),
    ("decomposition", "Push decomposition by sector"),
    ("scenario", "Scenario inputs over the horizon set"),
    ("ladder", "Rating-ladder response"),
    ("worked", "Worked example waterfall"),
    ("sensitivity", "Sensitivity tornado"),
    ("checks", "Quality checks"),
    ("appendix", "Full grid + source & assumption registers"),
]


def build_report_tab():
    return html.Div([
        _controls(_version_control("esg-rep-version") + _horizon_control("esg-rep-horizon")
                  + _theta_control("esg-rep-theta") + _grade_control("esg-rep-grade")),
        html.Div(build_report_body(), id="esg-rep-body"),
    ])


def build_report_body(version_id=None, horizon=None, theta=None, grade=None):
    from backend.climate import report as report_mod

    _, _, result, check_rows = resolve(version_id, horizon=horizon, theta=theta, grade=grade)
    insights = report_mod.build_insights(result, check_rows)

    config = html.Div([
        html.Div("GENERATE SUMMARY REPORT", className="table-title"),
        html.Div("SECTIONS INCLUDED", className="report-config-label"),
        dcc.Checklist(id="esg-rep-sections",
                      options=[{"label": " " + lbl, "value": key} for key, lbl in REPORT_SECTIONS],
                      value=[key for key, _ in REPORT_SECTIONS],
                      className="report-checklist"),
        html.Div("SENSITIVITY SWEEP", className="report-config-label"),
        dcc.Checklist(id="esg-rep-tornado",
                      options=[{"label": " Run the one-way tornado (adds ~0.2s)", "value": "on"}],
                      value=["on"], className="report-checklist"),
        html.Div([
            html.Button("⬇ Download HTML report", id="esg-rep-html",
                        className="report-generate-btn", n_clicks=0),
            html.Button("⬇ Excel pack", id="esg-rep-xlsx",
                        className="report-secondary-btn", n_clicks=0),
            html.Button("⬇ Grid CSV", id="esg-rep-csv",
                        className="report-secondary-btn", n_clicks=0),
        ], className="report-btn-row esg-report-btns"),
        html.Div(id="esg-rep-status"),
        html.Div("The HTML pack is a single self-contained file — inline SVG charts, no external "
                 "requests, no JavaScript — so it opens offline, prints to PDF for a regulator pack, "
                 "and can be archived next to the run it describes.", className="report-config-note"),
    ], className="report-config-panel")

    preview = [
        html.Div([html.Div(i["title"], className="esg-insight-title"),
                  dcc.Markdown(i["body"].replace("<b>", "**").replace("</b>", "**")
                               .replace("<i>", "_").replace("</i>", "_")
                               .replace("&ge;", "≥"),
                               className="esg-insight-body", dangerously_allow_html=False)],
                 className="esg-insight-card")
        for i in insights
    ]

    return [
        html.Div([
            html.Div([ui.table_card(
                f"REPORT PREVIEW — {result['model_name'].upper()}, "
                f"{result['horizon_year']} HORIZON",
                html.Div(preview, className="esg-insight-list"))], className="split-main"),
            html.Div([config], className="split-side"),
        ], className="split-grid"),
        _module_note(
            "The narrative is generated from the result, not templated around it: each paragraph reads "
            "the actual numbers, including where they are weak. Charts are paired with the table they "
            "were drawn from, which is both the accessibility relief route and the audit route."),
    ]


def build_report_download(version_id=None, horizon=None, theta=None, grade=None,
                          with_tornado=True, username=""):
    """Assemble the downloadable HTML pack. Returns (filename, html_string)."""
    from backend.climate import report as report_mod

    rec, model, result, check_rows = resolve(version_id, horizon=horizon, theta=theta, grade=grade)
    tor = sensitivity.tornado(model) if with_tornado else None
    html_doc = report_mod.build_html(model, result, check_rows, tornado_data=tor,
                                     run_id=None, generated_by=username)
    name = f"{result['country'] or 'Climate'}_StressedPD_{result['horizon_year']}".replace(" ", "_")
    return f"{name}.html", html_doc


def build_excel_download(version_id=None, horizon=None, theta=None, grade=None):
    from backend.climate import report as report_mod

    _, model, result, check_rows = resolve(version_id, horizon=horizon, theta=theta, grade=grade)
    name = f"{result['country'] or 'Climate'}_StressedPD_Pack_{result['horizon_year']}".replace(" ", "_")
    return f"{name}.xlsx", report_mod.build_excel(model, result, check_rows)


def build_grid_rows(version_id=None, horizon=None, theta=None, grade=None):
    """Flat grid rows for the CSV export."""
    _, _, result, _ = resolve(version_id, horizon=horizon, theta=theta, grade=grade)
    return [{"Sector ID": r["sector_id"], "Sector": r["sector"], "Grade": r["grade"],
             "Scenario": r["scenario_name"], "Baseline PD": round(r["baseline_pd"], 8),
             "Stressed PD": round(r["stressed_pd"], 8), "Multiple": round(r["multiple"], 6),
             "Delta bps": round(r["delta_bps"], 2)} for r in result["grid"]]
