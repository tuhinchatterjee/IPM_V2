"""
Data Hub: the intake interface that sits in front of the Cockpit. Shows which
portfolio workbook is currently active (from PostgreSQL), profiles it (rows, EAD by
quarter, field coverage), and lets the user upload a replacement workbook -
validated check-by-check in memory, persisted to Postgres as a *staged* version,
and only made active when explicitly activated. An upload-history table provides
the audit trail; reverting re-activates the bundled version.
"""

import plotly.graph_objects as go
from dash import dcc, html

from backend import data_loader as dl
from backend.services import data_store
from frontend import ui_common as ui

STATUS_ICON = {"pass": "✓", "warn": "!", "fail": "✕"}


def build_status_card():
    prof = dl.dataset_profile()
    info = data_store.active_version_info()
    src = (info["origin"] if info else prof["source"]) or "bundled"
    badge_cls = "is-uploaded" if src == "uploaded" else "is-bundled"
    workbook = info["source_filename"] if info else prof["path"]
    version_txt = f"v{info['id']}" if info else "—"
    loaded_dt = info["activated_at"] or info["uploaded_at"] if info else prof["loaded_at"]
    loaded = loaded_dt.strftime("%d-%b-%Y %H:%M") if loaded_dt else "—"
    q = prof["quarters"]
    facts = [
        ("Workbook", workbook),
        ("DB Version", version_txt),
        ("Activated", loaded),
        ("Snapshots", f"{q[0]['quarter']} → {q[-1]['quarter']} ({len(q)} quarters)"),
        ("Rows", f"{prof['rows_total']:,}"),
        ("Facilities / Obligors", f"{prof['accounts']} / {prof['customers']}"),
    ]
    return html.Div(
        [
            html.Div(
                [html.Span("ACTIVE DATASET", className="table-title"),
                 html.Span(src.upper(), className=f"source-badge {badge_cls}")],
                className="table-card-header",
            ),
            html.Div(
                [html.Div([html.Div(k, className="modal-stat-label"),
                           html.Div(v, className="modal-stat-value")], className="modal-stat")
                 for k, v in facts],
                className="datahub-facts",
            ),
        ],
        className="table-card",
    )


def build_history_card():
    """Upload/activation audit trail from the dataset_versions table (newest first)."""
    rows = data_store.upload_history(limit=10)
    if not rows:
        body = html.Div("No dataset versions recorded yet.", className="upload-report-hint")
    else:
        body_rows = []
        for r in rows:
            ts = r["uploaded_at"].strftime("%d-%b-%y %H:%M") if r["uploaded_at"] else "—"
            status_cls = {"active": "is-aligned", "staged": "is-prep"}.get(r["status"], "")
            body_rows.append(html.Tr([
                html.Td(f"v{r['id']}", className="num"),
                html.Td(r["source_filename"], className="metric-name"),
                html.Td(r["origin"]),
                html.Td(f"{r['quarters']}q · {r['rows_total']:,} rows", className="num"),
                html.Td(ts),
                html.Td(html.Span(r["status"], className=f"gap-pill {status_cls}")),
            ]))
        body = html.Table(
            [html.Thead(html.Tr([html.Th("Ver", className="num"), html.Th("Workbook"), html.Th("Origin"),
                                 html.Th("Size", className="num"), html.Th("Uploaded"), html.Th("Status")])),
             html.Tbody(body_rows)],
            className="borrower-table signals-table",
        )
    return html.Div(
        [html.Div([html.Span("UPLOAD HISTORY — AUDIT TRAIL", className="table-title")],
                  className="table-card-header"),
         html.Div(body, style={"padding": "4px 4px 8px"})],
        className="table-card",
    )


def build_upload_card():
    requirements = [
        "One sheet per quarterly snapshot, named like 'Q1 2026' (Quarter column must match)",
        f"A '{dl.SUPP_SHEET}' sheet with borrower financials",
        f"All {len(dl.REQUIRED_COLUMNS)} portfolio columns present in every quarterly sheet",
        "Values in USD mn; the tool derives AED figures for BRF returns",
    ]
    return html.Div(
        [
            html.Div([html.Span("UPLOAD NEW PORTFOLIO WORKBOOK", className="table-title")],
                     className="table-card-header"),
            html.Div(
                [
                    dcc.Upload(
                        id="upload-dataset",
                        children=html.Div(
                            [html.Div("⬆", className="upload-glyph"),
                             html.Div("Drag & drop the portfolio workbook here", className="upload-main"),
                             html.Div("or click to browse — .xlsx only", className="upload-sub")],
                        ),
                        className="upload-zone",
                        accept=".xlsx",
                        multiple=False,
                    ),
                    html.Div("EXPECTED FORMAT", className="report-config-label"),
                    html.Ul([html.Li(r) for r in requirements], className="upload-req-list"),
                    html.Div(
                        [
                            html.Button("Activate Uploaded Dataset", id="activate-dataset-btn",
                                        className="report-generate-btn", n_clicks=0, disabled=True),
                            html.Button("Revert to Bundled", id="revert-dataset-btn",
                                        className="report-secondary-btn", n_clicks=0),
                        ],
                        className="report-btn-row",
                    ),
                ],
                style={"padding": "16px 20px 20px"},
            ),
        ],
        className="table-card",
    )


def render_validation_report(report, filename=None):
    if report is None:
        return html.Div(
            "Upload a workbook to run the structural validation — nothing is activated until you confirm.",
            className="upload-report-hint",
        )
    items = [
        html.Div(
            [html.Span(STATUS_ICON[c["status"]], className=f"check-icon {c['status']}"),
             html.Div([html.Div(c["name"], className="check-name"),
                       html.Div(c["detail"], className="check-detail")])],
            className="check-row",
        )
        for c in report["checks"]
    ]
    if report["ok"]:
        verdict = html.Div(
            f"✓ '{filename}' passed validation ({report['rows_total']:,} rows, "
            f"{len(report['quarters'])} quarters). Click Activate to switch the whole tool to this dataset.",
            className="upload-verdict is-ok",
        )
    else:
        verdict = html.Div(
            f"✕ '{filename}' failed validation — fix the items marked above and re-upload. "
            f"The active dataset is unchanged.",
            className="upload-verdict is-fail",
        )
    return html.Div(items + [verdict])


def build_validation_card():
    return html.Div(
        [
            html.Div([html.Span("VALIDATION REPORT", className="table-title")], className="table-card-header"),
            html.Div(render_validation_report(None), id="upload-report", style={"padding": "14px 20px 18px"}),
        ],
        className="table-card",
    )


def build_profile_card():
    prof = dl.dataset_profile()
    q = prof["quarters"]
    fig = go.Figure(go.Bar(
        x=[p["quarter"] for p in q],
        y=[p["ead"] / 1000 for p in q],
        marker=dict(color="#16b8a6"),
        customdata=[[p["rows"], p["customers"]] for p in q],
        hovertemplate="<b>%{x}</b><br>EAD $%{y:.1f}bn<br>%{customdata[0]} rows · "
                      "%{customdata[1]} obligors<extra></extra>",
    ))
    ui.base_layout(fig, height=200)
    fig.update_layout(bargap=0.35, margin=dict(t=8, b=24, l=40, r=10))

    cov_rows = [
        html.Div(
            [html.Div(c["column"], className="util-bar-label", style={"width": "220px"}),
             html.Div(html.Div(className=f"util-bar-fill {'ok' if c['pct'] >= 99 else 'warn'}",
                               style={"width": f"{c['pct']:.0f}%"}), className="util-bar-track"),
             html.Div(f"{c['pct']:.1f}%", className="util-bar-value", style={"width": "52px"})],
            className="util-bar-row",
        )
        for c in prof["coverage"]
    ]

    return html.Div(
        [
            html.Div([html.Span("DATASET PROFILE", className="table-title")], className="table-card-header"),
            html.Div(
                [html.Div("TOTAL EAD BY SNAPSHOT ($bn)", className="chart-title"),
                 dcc.Graph(figure=fig, config={"displayModeBar": False}),
                 html.Div("FIELD COVERAGE — KEY RISK COLUMNS", className="chart-title",
                          style={"marginTop": "14px"}),
                 html.Div(cov_rows)],
                style={"padding": "12px 20px 18px"},
            ),
        ],
        className="table-card",
    )


def build_data_hub_page():
    return [
        ui.page_header("Data Hub — Portfolio Dataset Intake"),
        dcc.Store(id="staged-version-store"),
        html.Div(
            [html.Div([html.Div(build_status_card(), id="datahub-status"),
                       build_upload_card(),
                       html.Div(build_history_card(), id="datahub-history")], className="split-main"),
             html.Div([build_validation_card(),
                       html.Div(build_profile_card(), id="datahub-profile")], className="split-side")],
            className="split-grid datahub-grid",
        ),
    ]
