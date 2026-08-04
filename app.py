"""
IPM | Executive Portfolio Risk Cockpit
First interface of the Intelligent Portfolio Manager web app: a live, filterable
risk-monitoring dashboard built on top of the synthetic wholesale/retail portfolio
dataset (Portfolio_Monitoring_Dataset.xlsx).
"""

import base64
import logging
import time
from datetime import datetime
from urllib.parse import parse_qs

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, MATCH, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
from flask import jsonify
from flask_compress import Compress
from flask_login import current_user

from backend.config import settings
from backend.logging_setup import init_logging

init_logging()
logger = logging.getLogger(__name__)

from backend import (
    ai_chat,
    ai_context,
    claude_chat,
    qwen_ultra_chat,
    raroc2_data,
    raroc_data,
    stress_lab,
)
from backend import data_loader as dl
from backend.auth.login import init_auth, install_gate
from backend.auth.routes import register_auth_routes
from backend.climate import store as climate_store
from backend.services import ai_usage, data_store, rate_limit
from frontend import brf_view, cockpit_view, data_hub, esg_view, macro_view, raroc2_view, raroc_view

# --------------------------------------------------------------------------- app

def _handle_callback_error(err):
    """Global safety net for uncaught callback exceptions: log the full traceback
    (individual callbacks still use PreventUpdate/no_update for expected cases) and
    leave the UI unchanged rather than surfacing a raw stack trace to the user."""
    logger.exception("Unhandled callback error: %s", err)
    return no_update


app = dash.Dash(
    __name__,
    title="IPM | Executive Portfolio Risk Cockpit",
    update_title=None,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    on_error=_handle_callback_error,
)
server = app.server

# gzip/brotli the (large) Dash JS/CSS bundles and JSON callback payloads — a real
# win over the LAN.
Compress(server)

# Authentication (Flask-Login): session config, /login + /logout routes, and the
# gate putting every page and callback behind login. Registered before the
# dataset-sync before_request hook so unauthenticated requests short-circuit
# before any DB work happens.
init_auth(server)
register_auth_routes(server)
install_gate(server)

# Content-Security-Policy is permissive by necessity: Dash/Plotly require inline +
# eval scripts, and the app currently pulls Bootstrap (jsDelivr) and the Inter font
# (Google Fonts) from CDNs. Phase 5 vendors the font locally so this can tighten.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)


@server.after_request
def _set_security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    return resp


@server.before_request
def _sync_active_dataset():
    """Before each request, converge this worker's in-memory dataset on the active
    version in Postgres. Cheap (memoized) no-op when the version is unchanged."""
    data_store.ensure_current()


@server.route("/healthz")
def healthz():
    """Liveness/readiness probe for monitoring and the NSSM service. No auth."""
    db_ok = True
    active_version = None
    try:
        active_version = data_store.get_active_version_id()
    except Exception:
        db_ok = False
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "env": settings.env,
        "db": "ok" if db_ok else "unreachable",
        "dataset_source": dl.ACTIVE_SOURCE,
        "dataset_version": active_version,
        "loaded_version": data_store.current_version_id(),
        "quarters": len(dl.QUARTER_SHEETS),
        "time": datetime.now().isoformat(timespec="seconds"),
    }), (200 if db_ok else 503)


# Warm the dataset cache at startup so the first user request isn't slowed by the
# initial Postgres load. Tolerant of a DB hiccup — data_loader already holds the
# bundled fallback, and the before_request hook will retry.
try:
    data_store.ensure_current()
except Exception:
    logger.exception("Initial dataset cache warm failed; will retry on first request.")


def _error_page(code: int, title: str, message: str):
    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{code} · IPM Tool</title>
<style>
  body {{ margin:0; height:100vh; display:flex; align-items:center; justify-content:center;
         font-family:'Inter',-apple-system,'Segoe UI',sans-serif; background:#0b2436; color:#e6eef5; }}
  .card {{ text-align:center; padding:40px 48px; }}
  .code {{ font-size:64px; font-weight:800; color:#16b8a6; line-height:1; }}
  .title {{ font-size:20px; font-weight:700; margin:14px 0 6px; }}
  .msg {{ font-size:14px; color:#8aa2b8; max-width:420px; }}
  a {{ color:#16b8a6; font-weight:600; text-decoration:none; }}
</style></head><body><div class="card">
  <div class="code">{code}</div><div class="title">{title}</div>
  <div class="msg">{message}</div>
  <p><a href="/">&larr; Back to the cockpit</a></p>
</div></body></html>"""
    return html_doc, code


@server.errorhandler(404)
def _not_found(_e):
    return _error_page(404, "Page not found", "The page you requested doesn't exist.")


@server.errorhandler(500)
def _server_error(e):
    logger.exception("Unhandled server error: %s", e)
    return _error_page(500, "Something went wrong",
                       "An internal error occurred and has been logged. Please try again.")

SUBNAV_TABS = ["Health Index", "Overview", "Signals", "Concentration", "Migration", "EAD", "IFRS 9"]
COCKPIT_LANDING_TAB = SUBNAV_TABS[0]
MODULE_DESCRIPTIONS = {
    "Signals": "AI Risk Score, Severity (RED / AMBER / GREEN), Trigger, Reason Code, Recommended Action, Owner.",
    "Concentration": "Sector x Internal Grade heatmap, HHI, top-obligor and group exposure.",
    "Migration": "Risk Rating vs Prev. Risk Rating, Rating Bucket, Grade Band - upgrades / stable / downgrades.",
    "EAD": "Funded / Undrawn / Guarantees / LCs build-up, CCF, Utilisation vs Prev. Utilisation.",
    "IFRS 9": "12m & lifetime PD, LGD, Model ECL, Macro Overlay, Total ECL, coverage by stage, SICR triggers.",
}
# Limits is no longer a top-level section: its three views are opened from the
# Borrower 360 page instead, where a limit line is actually actionable against a
# name. See build_b360_limits_modal.
TOP_NAV_ITEMS = ["Watchlist", "Stress", "Macro", "RAROC", "ESG", "BRF", "Reports"]
SECTION_ROUTES = {
    "Watchlist": "/watchlist", "Stress": "/stress",
    "Macro": "/macro", "RAROC": "/raroc", "ESG": "/esg",
    "BRF": "/brf", "Reports": "/reports",
}
LIMITS_VIEWS = ["Appetite", "Utilisation", "Breaches"]
ROUTE_TO_SECTION = {v.lstrip("/"): k.lower().replace(" ", "") for k, v in SECTION_ROUTES.items()}
SECTION_TABS = {
    "watchlist": ["Board", "Actions"],
    "stress": ["Scenario Lab", "Results", "Reverse Stress"],
    "macro": ["Outlook", "Sector Risk", "Portfolio Health"],
    "raroc": ["Post-Deal RAROC", "Deal Explorer", "Deal Detail", "Earnings & EVA", "Methodology"],
    "esg": ["Results", "Drill-down", "Inputs", "Calibration", "Sensitivity", "Quality Checks",
            "Runs", "Report"],
    "brf": ["Overview", "Asset Quality", "Economic Activity", "Large Exposures", "Calendar"],
    "reports": ["Review Pack", "Schedules", "Archive"],
}
SECTION_TITLES = {
    "watchlist": "Watchlist, Distressed & Action Management",
    "stress": "AI-Driven Stress Testing & Scenario Lab",
    "macro": "Macroeconomic Outlook & Forward Portfolio Health",
    "raroc": "RAROC — Post-Deal Risk-Adjusted Return on Capital",
    "esg": "ESG & Climate Risk — Transition and Physical Stressed PD",
    "brf": "CBUAE BRF Regulatory Returns",
    "reports": "Management Portfolio Review Pack Generator",
}
SECTION_BREADCRUMB = {"watchlist": "Watchlist", "stress": "Stress",
                       "macro": "Macro", "raroc": "RAROC", "esg": "ESG",
                       "brf": "BRF Returns", "reports": "Reports"}

STAGE_COLORS = {1: "#1fa971", 2: "#f0973e", 3: "#e5484d"}
TREND_ARROW = {"Up": "▲", "Down": "▼", "Watch": "◆", "Stable": "●"}
TREND_CLASS = {"Up": "trend-up", "Down": "trend-down", "Watch": "trend-watch", "Stable": "trend-stable"}

TABLE_COLUMNS = [
    ("Borrower", "Borrower", False),
    ("Sector", "Sector", False),
    ("EAD", "EAD", True),
    ("Rating", "Rating", False),
    ("Stage", "Stage", True),
    ("Trend", "Trend", False),
]

DEFAULT_SORT = {"col": "EAD", "asc": False}


# --------------------------------------------------------------------- small icons
# Pure-CSS icons: dash.html has no Svg/Path wrappers, and piping raw <svg> markup
# through dcc.Markdown's HTML passthrough renders the tags unrecognized (React
# warnings, no actual icon) - so these are plain shapes styled in style.css.

def icon_search():
    return html.Span(html.Span(className="icon-search-handle"), className="icon-search")


def icon_bell():
    return html.Span(
        [html.Span(className="icon-bell-dome"), html.Span(className="icon-bell-clapper")],
        className="icon-bell",
    )


def icon_grid():
    return html.Div([html.Span() for _ in range(4)], className="icon-grid4")


# ------------------------------------------------------------------------ navbar

def build_user_menu():
    """Signed-in user's initials chip + a logout link. Uses a plain anchor (not
    dcc.Link) so /logout hits the Flask route rather than Dash client-side routing."""
    if not getattr(current_user, "is_authenticated", False):
        return []
    username = getattr(current_user, "username", "user")
    role = getattr(current_user, "role", "analyst")
    initials = "".join(w[0] for w in username.replace(".", " ").replace("_", " ").split()[:2]).upper() or username[:2].upper()
    return [
        html.Div(initials, className="avatar-chip", title=f"{username} ({role})"),
        html.A("Sign out", href="/logout", className="logout-link", title="Sign out"),
    ]


def build_navbar():
    nav_items = [
        dcc.Link("Data", href="/data", id="nav-data", className="ipm-nav-item"),
        dcc.Link("Cockpit", href="/", id="nav-cockpit", className="ipm-nav-item active"),
        dcc.Link("Borrowers", href="/borrowers", id="nav-borrowers", className="ipm-nav-item"),
    ]
    nav_items += [
        dcc.Link(label, href=SECTION_ROUTES[label], id={"type": "top-nav", "route": SECTION_ROUTES[label]},
                  className="ipm-nav-item")
        for label in TOP_NAV_ITEMS
    ]

    return html.Div(
        [
            html.Div(
                [
                    html.Div("IPM", className="logo-badge"),
                    html.Div(
                        [
                            html.Div("Intelligent Portfolio Manager", className="navbar-title"),
                        ],
                        className="navbar-titles",
                    ),
                    html.Div(nav_items, className="ipm-navbar-nav"),
                ],
                className="navbar-left",
            ),
            html.Div(
                [
                    html.Div(icon_search(), className="navbar-icon", title="Search"),
                    html.Div([icon_bell(), html.Span(className="notif-dot")], className="navbar-icon",
                              title="Notifications"),
                    *build_user_menu(),
                ],
                className="navbar-right",
            ),
        ],
        className="ipm-navbar",
    )


# --------------------------------------------------------------- filters & header

def build_page_header(title):
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


def build_cockpit_breadcrumb_subnav():
    subnav_items = [
        html.Div(
            tab,
            id={"type": "subnav", "tab": tab},
            n_clicks=0,
            className="subnav-item active" if tab == COCKPIT_LANDING_TAB else "subnav-item",
        )
        for tab in SUBNAV_TABS
    ]
    return html.Div(
        [
            html.Div(
                [icon_grid(), html.Span("Cockpit", className="crumb-icon"), html.Span("›", className="crumb-sep"),
                 html.Span(COCKPIT_LANDING_TAB, className="crumb-current", id="cockpit-crumb-current")],
                className="ipm-breadcrumb",
            ),
            html.Div(subnav_items, className="subnav"),
        ],
        className="breadcrumb-row",
    )


def build_filters_row():
    return html.Div(
        [
            html.Span("FILTERS", className="filters-label"),
            dcc.Dropdown(
                id="f-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                clearable=False, searchable=False, className="filter-dd",
            ),
            dcc.Dropdown(
                id="f-segment", options=dl.SEGMENT_OPTIONS, value="All",
                clearable=False, searchable=False, className="filter-dd narrow",
            ),
            dcc.Dropdown(
                id="f-sector", options=dl.SECTOR_OPTIONS, value="All",
                clearable=False, searchable=False, className="filter-dd",
            ),
            dcc.Dropdown(
                id="f-region", options=dl.REGION_OPTIONS, value="All",
                clearable=False, searchable=False, className="filter-dd",
            ),
            dcc.Dropdown(
                id="f-rating", options=dl.RATING_OPTIONS, value="All",
                clearable=False, searchable=False, className="filter-dd narrow",
            ),
            html.Button("Reset", id="f-reset", className="reset-btn", n_clicks=0),
        ],
        className="filters-row",
    )


# ----------------------------------------------------------------------- KPI cards

def kpi_card(label, value, dot_color, sub):
    return html.Div(
        [
            html.Div([label, html.Span(className=f"kpi-dot {dot_color}")], className="kpi-label"),
            html.Div(value, className="kpi-value"),
            sub,
        ],
        className="kpi-card",
    )


def build_kpi_cards(quarter, segment, sector, region, rating):
    k = dl.compute_kpis(quarter, segment, sector, region, rating)
    first_snap = html.Div("First snapshot on record", className="kpi-sub neutral")

    # 1. Total EAD
    if k["ead_qoq_pct"] is None:
        sub1 = first_snap
    else:
        up = k["ead_qoq_pct"] >= 0
        sub1 = html.Div(f"{'▲' if up else '▼'} {abs(k['ead_qoq_pct']):.1f}% QoQ",
                         className=f"kpi-sub {'up-good' if up else 'up-bad'}")

    # 2. NPL ratio - rising is bad
    if k["npl_delta"] is None:
        sub2 = first_snap
    else:
        up = k["npl_delta"] >= 0
        sub2 = html.Div(f"{'▲' if up else '▼'} {abs(k['npl_delta']):.1f}pp QoQ",
                         className=f"kpi-sub {'up-bad' if up else 'up-good'}")

    # 3. Watchlist exposure - informational, no QoQ direction implied
    sub3 = html.Div(f"{k['watchlist_pct']:.1f}% of book", className="kpi-sub neutral")

    # 4. Stage 2 exposure - rising is cautionary (amber), falling is good
    if k["stage2_delta"] is None:
        sub4 = first_snap
    else:
        up = k["stage2_delta"] >= 0
        sub4 = html.Div(f"{'▲' if up else '▼'} ${abs(k['stage2_delta']) / 1000:.1f}bn QoQ",
                         className=f"kpi-sub {'warn' if up else 'up-good'}")

    # 5. Portfolio RAROC - rising is good
    if k["raroc_delta"] is None:
        sub5 = first_snap
    else:
        up = k["raroc_delta"] >= 0
        sub5 = html.Div(f"{'▲' if up else '▼'} {abs(k['raroc_delta']):.1f}pp QoQ",
                         className=f"kpi-sub {'up-good' if up else 'up-bad'}")

    # 6. Appetite breaches - rising is bad
    if k["breach_delta"] is None:
        sub6 = first_snap
    elif k["breach_delta"] == 0:
        sub6 = html.Div("No change QoQ", className="kpi-sub neutral")
    else:
        up = k["breach_delta"] >= 0
        word = "breach" if abs(k["breach_delta"]) == 1 else "breaches"
        sub6 = html.Div(f"{'▲' if up else '▼'} {abs(k['breach_delta'])} {word} QoQ",
                         className=f"kpi-sub {'up-bad' if up else 'up-good'}")

    return [
        kpi_card("Total EAD", dl.fmt_bn(k["total_ead"]), "blue", sub1),
        kpi_card("NPL Ratio", dl.fmt_pct(k["npl_ratio"]), "amber", sub2),
        kpi_card("Watchlist Exp.", dl.fmt_bn(k["watchlist_ead"]), "amber", sub3),
        kpi_card("Stage 2 Exp.", dl.fmt_bn(k["stage_ead"][2]), "blue", sub4),
        kpi_card("Portfolio RAROC", dl.fmt_pct(k["raroc"]), "purple", sub5),
        kpi_card("Appetite Breaches", str(k["breaches"]), "red", sub6),
    ]


# --------------------------------------------------------------------- AI chat

def render_chat_bubbles(history):
    """User turns stay plain text; assistant turns render as Markdown.

    The assistant is asked (in ai_context._OUTPUT_CONTRACT) to answer with a
    headline, tables and bolded figures — none of which means anything if the
    reply is dropped into a div as raw text, which is what made the answers read
    as an undifferentiated wall.
    """
    bubbles = []
    for m in history or []:
        role = m.get("role")
        if role in ("system", "tool"):
            continue
        raw_content = m.get("content")
        if not raw_content:
            continue
        if isinstance(raw_content, list):
            # Anthropic-style content blocks (claude_chat.py). A "user" message
            # with block content is an internal tool_result reply, not something
            # the human typed - never show it. An "assistant" message may mix
            # tool_use blocks with a text block; only the text is user-facing.
            if role == "user":
                continue
            content = "".join(
                b.get("text", "") for b in raw_content
                if isinstance(b, dict) and b.get("type") == "text"
            )
            if not content:
                continue
        else:
            content = raw_content

        if role == "user":
            bubbles.append(html.Div(content, className="chat-bubble user"))
            continue

        cls = "assistant is-error" if content == ai_chat.UNAVAILABLE_MSG else "assistant"
        bubbles.append(
            html.Div(
                dcc.Markdown(content, className="chat-md", link_target="_blank",
                             dangerously_allow_html=False),
                className=f"chat-bubble {cls}",
            )
        )
    if not bubbles:
        # The brief above already says what is on screen, so this only has to
        # prompt the first question rather than re-introduce the assistant.
        bubbles = [html.Div("Ask a question about this screen, or pick a suggestion below.",
                            className="chat-empty-hint")]
    return bubbles


def build_chat_brief(screen: str, customer_id: str | None = None):
    """The opening brief shown above the conversation: a portfolio snapshot plus
    what is on the screen the user is standing on.

    Computed from the dataset rather than asked of the model, so it is instant,
    costs nothing, and states figures the assistant cannot get wrong."""
    brief = ai_context.screen_brief(screen, customer_id)
    chips = [
        html.Div([
            html.Div(label, className="brief-chip-label"),
            html.Div(value, className=f"brief-chip-value tone-{tone}"),
        ], className="brief-chip")
        for label, value, tone in brief["portfolio"]
    ]
    return html.Div(
        [
            html.Div([
                html.Span("PORTFOLIO", className="brief-section-label"),
                html.Span(brief["as_of"], className="brief-asof"),
            ], className="brief-head"),
            html.Div(chips, className="brief-chip-row"),
            html.Div([
                html.Span("ON THIS SCREEN", className="brief-section-label"),
                html.Span(brief["label"], className="brief-screen-name"),
            ], className="brief-head brief-head-screen"),
            html.Div(
                [dcc.Markdown(line, className="brief-line") for line in brief["lines"]],
                className="brief-lines",
            ),
        ],
        className="chat-brief",
    )


# Labels/models sourced from the backend modules so the UI can't drift from the
# actual model being called (previously the Anthropic model was mislabeled).
MODEL_OPTIONS = {
    "sage": {"label": claude_chat.DISPLAY_NAME, "provider": "anthropic", "model": claude_chat.MODEL,
             "subtitle": ""},
    "qwen": {"label": "Qwen 3.5 (local)", "provider": "ollama", "model": ai_chat.MODEL,
             "subtitle": ""},
    "qwen_ultra": {"label": f"{qwen_ultra_chat.DISPLAY_NAME} (local)", "provider": "ollama",
                   "model": qwen_ultra_chat.MODEL,
                   "subtitle": ""},
}
DEFAULT_MODEL = "sage"


def call_model(model_key: str, history: list) -> tuple:
    if model_key == "qwen":
        return ai_chat.chat(history)
    if model_key == "qwen_ultra":
        return qwen_ultra_chat.chat(history)
    return claude_chat.chat(history)


def call_model_guarded(model_key: str, history: list, user_id) -> tuple:
    """Rate-limit, time, and usage-log an AI call around call_model(). Returns the
    same (reply, appended) contract; on rate-limit or error returns a friendly
    message with no appended messages."""
    opt = MODEL_OPTIONS.get(model_key) or MODEL_OPTIONS[DEFAULT_MODEL]
    provider, model = opt["provider"], opt["model"]

    allowed, limit_msg = rate_limit.check_and_consume(user_id, provider)
    if not allowed:
        ai_usage.log_usage(user_id=user_id, provider=provider, model=model,
                           status="rate_limited", latency_ms=0)
        return limit_msg, []

    t0 = time.monotonic()
    status = "ok"
    try:
        reply, appended = call_model(model_key, history)
    except Exception:  # noqa: BLE001 — never surface a raw traceback into the chat
        logger.exception("AI call failed (model_key=%s)", model_key)
        reply, appended, status = ("The assistant hit an unexpected error and it has been logged. "
                                   "Please try again."), [], "error"
    latency_ms = int((time.monotonic() - t0) * 1000)
    prompt_chars = sum(len(m["content"]) for m in history
                       if isinstance(m, dict) and isinstance(m.get("content"), str))
    ai_usage.log_usage(user_id=user_id, provider=provider, model=model, status=status,
                       latency_ms=latency_ms, prompt_chars=prompt_chars,
                       completion_chars=len(reply or ""),
                       tool_calls=ai_usage.extract_tool_calls(appended))
    return reply, appended


def build_model_dropdown(page: str, active: str = DEFAULT_MODEL):
    return dbc.Select(
        id={"type": "chat-model-select", "page": page},
        options=[{"label": opt["label"], "value": key} for key, opt in MODEL_OPTIONS.items()],
        value=active,
        className="model-select-native",
    )


def build_chat_panel(page: str, history: list = None, current_model: str = DEFAULT_MODEL,
                     customer_id: str | None = None):
    # The chat-history/chat-model/chat-pending Stores themselves live in the
    # persistent app shell (serve_layout), not here - this panel is rebuilt
    # from scratch on every page navigation, but those Stores are not, so the
    # conversation survives switching pages. `history`/`current_model` are the
    # Stores' current values, threaded in so the freshly-built panel reflects
    # them immediately instead of flashing back to an empty/default state.
    # `page` is also the screen key, so each screen keeps its own conversation
    # and its own brief.
    chips = [
        html.Div(s, id={"type": "chat-chip", "page": page, "text": s}, n_clicks=0, className="chat-chip")
        for s in ai_context.suggestions(page)
    ]
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.Div("✦", className="ai-icon"),
                        html.Span("AI INTELLIGENCE", className="signals-title"),
                    ],
                    className="signals-header-left",
                ),
                build_model_dropdown(page, active=current_model),
                html.Button("×", id="ai-drawer-close", n_clicks=0, className="ai-drawer-close",
                            title="Close (Esc)"),
            ],
            className="signals-header",
        ),
        html.Div(MODEL_OPTIONS[current_model]["subtitle"], id={"type": "chat-subtitle", "page": page},
                  className="signals-subline"),
        build_chat_brief(page, customer_id),
        dcc.Loading(
            html.Div(render_chat_bubbles(history), id={"type": "chat-messages", "page": page}, className="chat-messages"),
            color="#16b8a6",
            type="dot",
        ),
        html.Div(
            [
                html.Div(chips, className="chat-suggestions-popup"),
                html.Div(
                    [
                        dcc.Input(id={"type": "chat-input", "page": page}, type="text",
                                  placeholder="Ask a question...", n_submit=0, autoComplete="off"),
                        html.Button("→", id={"type": "chat-send", "page": page}, n_clicks=0, className="chat-send-btn"),
                    ],
                    className="chat-input-row",
                ),
            ],
            className="chat-input-wrap",
        ),
    ]


# ------------------------------------------------------------------------ charts

# Height of the three Overview cards' charts. Responsive Plotly graphs size to
# their DOM element rather than the figure, so this has to drive both the figure
# layout and the dcc.Graph style — keeping it in one place stops them drifting.
CHART_HEIGHT = 176


def build_stage_chart(quarter, segment, sector, region, rating):
    stages = dl.compute_stage_breakdown(quarter, segment, sector, region, rating)
    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Stage 1 - Performing", "Stage 2 - SICR", "Stage 3 - Credit-impaired"],
                values=[stages[1]["ead"], stages[2]["ead"], stages[3]["ead"]],
                hole=0.72,
                sort=False,
                direction="clockwise",
                marker=dict(colors=[STAGE_COLORS[1], STAGE_COLORS[2], STAGE_COLORS[3]],
                            line=dict(color="#ffffff", width=3)),
                textinfo="none",
                hovertemplate="<b>%{label}</b><br>$%{value:,.0f}m  (%{percent})<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        showlegend=False,
        margin=dict(t=6, b=6, l=6, r=6),
        height=CHART_HEIGHT,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        annotations=[
            dict(text=f"<b>{stages[1]['pct']:.0f}%</b>", x=0.5, y=0.56, showarrow=False,
                 font=dict(size=22, color="#16232f", family="Inter")),
            dict(text="Performing", x=0.5, y=0.39, showarrow=False,
                 font=dict(size=10.5, color="#93a1b2", family="Inter")),
        ],
        hoverlabel=dict(bgcolor="#0b2436", font_color="#fff", font_size=12, font_family="Inter"),
    )

    legend = html.Div(
        [
            html.Div(
                [
                    html.Span(className="legend-swatch", style={"background": STAGE_COLORS[s]}),
                    f"Stage {s}",
                    html.Span(dl.fmt_bn(stages[s]["ead"]), className="legend-val"),
                ],
                className="legend-row",
            )
            for s in (1, 2, 3)
        ],
        className="stage-legend",
    )

    return html.Div(
        [
            dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"width": f"{CHART_HEIGHT}px", "height": f"{CHART_HEIGHT}px"}),
            legend,
        ],
        className="donut-flex",
    )


def build_ecl_chart(quarter, segment, sector, region, rating):
    trend = dl.compute_ecl_trend(quarter, segment, sector, region, rating, n_quarters=4)
    fig = go.Figure(
        data=[
            go.Scatter(
                x=[t["label"] for t in trend],
                y=[t["total_ecl"] for t in trend],
                customdata=[t["total_ead"] for t in trend],
                mode="lines+markers",
                line=dict(color="#3e7bfa", width=3, shape="spline"),
                marker=dict(size=7, color="#3e7bfa", line=dict(color="#fff", width=2)),
                fill="tozeroy",
                fillcolor="rgba(62,123,250,0.10)",
                hovertemplate="<b>%{x}</b><br>Total ECL: $%{y:,.0f}m<br>Total EAD: $%{customdata:,.0f}m<extra></extra>",
            )
        ]
    )
    ys = [t["total_ecl"] for t in trend]
    pad = max((max(ys) - min(ys)) * 0.35, 5) if ys else 5
    fig.update_layout(
        margin=dict(t=10, b=24, l=38, r=10),
        height=CHART_HEIGHT,
        xaxis=dict(showgrid=False, tickfont=dict(size=10.5, color="#6c7a8c", family="Inter")),
        yaxis=dict(showgrid=True, gridcolor="#eef1f6", zeroline=False,
                   tickfont=dict(size=10.5, color="#6c7a8c", family="Inter"),
                   range=[max(0, min(ys) - pad), max(ys) + pad] if ys else None),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#0b2436", font_color="#fff", font_size=12, font_family="Inter"),
    )
    # responsive=True so Plotly re-measures when the chart becomes visible. The
    # Cockpit mounts Overview hidden (it lands on Health Index), and a graph laid
    # out in a zero-width container otherwise keeps Plotly's 700px default width
    # forever, which blows the charts grid past the page width. Responsive graphs
    # take their size from the element, so the height has to be pinned here too or
    # they inherit dcc.Graph's 450px default instead of the figure's own height.
    return dcc.Graph(figure=fig, config={"displayModeBar": False, "responsive": True},
                     style={"width": "100%", "height": f"{CHART_HEIGHT}px"})


def build_sector_chart(quarter, segment, sector, region, rating):
    sectors = dl.compute_top_sectors(quarter, segment, sector, region, rating, top_n=5)
    sectors = list(reversed(sectors))  # smallest at top, largest at bottom (matches reference)
    fig = go.Figure(
        data=[
            go.Bar(
                x=[s["ead"] / 1000 for s in sectors],
                y=[s["sector"] for s in sectors],
                orientation="h",
                marker=dict(color="#16b8a6"),
                text=[f"{s['ead'] / 1000:.1f}" for s in sectors],
                textposition="outside",
                textfont=dict(size=11.5, color="#16232f", family="Inter"),
                hovertemplate="<b>%{y}</b><br>EAD: $%{x:.2f}bn<extra></extra>",
            )
        ]
    )
    max_x = max([s["ead"] / 1000 for s in sectors], default=1)
    fig.update_layout(
        margin=dict(t=10, b=24, l=10, r=34),
        height=CHART_HEIGHT,
        xaxis=dict(showgrid=True, gridcolor="#eef1f6", zeroline=False, range=[0, max_x * 1.28],
                   tickfont=dict(size=10.5, color="#6c7a8c", family="Inter")),
        yaxis=dict(tickfont=dict(size=11.5, color="#3c4a5a", family="Inter")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.38,
        hoverlabel=dict(bgcolor="#0b2436", font_color="#fff", font_size=12, font_family="Inter"),
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": False, "responsive": True},
                     style={"width": "100%", "height": f"{CHART_HEIGHT}px"})


def build_charts_row(quarter, segment, sector, region, rating):
    return [
        html.Div([html.Div("EXPOSURE BY STAGE", className="chart-title"),
                  build_stage_chart(quarter, segment, sector, region, rating)], className="chart-card"),
        html.Div([html.Div("ECL MOVEMENT ($m)", className="chart-title"),
                  build_ecl_chart(quarter, segment, sector, region, rating)], className="chart-card"),
        html.Div([html.Div("TOP SECTORS BY EAD ($bn)", className="chart-title"),
                  build_sector_chart(quarter, segment, sector, region, rating)], className="chart-card"),
    ]


# ------------------------------------------------------------------------- table

def build_borrower_table(quarter, segment, sector, region, rating, sort_state):
    sort_state = sort_state or DEFAULT_SORT
    sort_col, sort_asc = sort_state["col"], sort_state["asc"]
    rows = dl.compute_top_borrowers(quarter, segment, sector, region, rating, top_n=10,
                                     sort_col=sort_col, ascending=sort_asc)

    header_cells = []
    for label, key, is_num in TABLE_COLUMNS:
        is_sorted = sort_col == key
        arrow = ("↑" if sort_asc else "↓") if is_sorted else ""
        classes = " ".join(filter(None, ["sorted" if is_sorted else "", "num" if is_num else ""]))
        header_cells.append(
            html.Th([label, html.Span(arrow, className="sort-arrow")], className=classes or None,
                     id={"type": "sort-th", "col": key}, n_clicks=0)
        )
    thead = html.Thead(html.Tr(header_cells))

    if not rows:
        tbody = html.Tbody(html.Tr(html.Td("No borrowers match the current filters.", colSpan=6,
                                            style={"padding": "26px", "textAlign": "center",
                                                   "color": "var(--text-muted)"})))
    else:
        body_rows = []
        for r in rows:
            stage = r["IFRS 9 Stage"]
            trend = r["Trend"]
            body_rows.append(
                html.Tr(
                    [
                        html.Td(r["Borrower"], className="borrower-name"),
                        html.Td(r["Sector"]),
                        html.Td(dl.fmt_bn(r["EAD"], 2), className="num borrower-ead"),
                        html.Td(html.Span(r["Risk Rating"], className="rating-chip")),
                        html.Td(html.Span(str(stage), className=f"stage-badge stage-{stage}"), className="center"),
                        html.Td(html.Span([TREND_ARROW.get(trend, ""), " ", trend],
                                           className=f"trend-tag {TREND_CLASS.get(trend, '')}")),
                    ],
                    id={"type": "borrower-row", "index": r["Account ID"]},
                    n_clicks=0,
                )
            )
        tbody = html.Tbody(body_rows)

    return html.Table([thead, tbody], className="borrower-table")


def build_table_card(quarter, segment, sector, region, rating, sort_state):
    return html.Div(
        [
            html.Div(
                [
                    html.Span("TOP 10 BORROWERS BY EXPOSURE", className="table-title"),
                    html.Span("Click a row for full facility detail", className="table-hint"),
                ],
                className="table-card-header",
            ),
            html.Div(build_borrower_table(quarter, segment, sector, region, rating, sort_state),
                      id="borrower-table-wrap"),
        ],
        className="table-card",
    )


# ----------------------------------------------------------------- Early-warning signals

SIGNALS_TABLE_COLUMNS = [
    ("Sev", "Severity", False, True),
    ("Borrower", "Borrower", False, True),
    ("Sector", "Sector", False, True),
    ("Exposure", "Exposure", True, True),
    ("Trigger", "Trigger", False, False),
    ("AI Score", "AI Score", True, True),
    ("Reason Code", "Reason Code", False, True),
    ("Recommended Action", "Recommended Action", False, False),
    ("Owner", "Owner", False, True),
]
SIGNALS_DEFAULT_SORT = {"col": "Severity", "asc": True}
SEV_DOT_CLASS = {"RED": "red", "AMBER": "amber", "GREEN": "green"}


def build_signals_filters_row():
    return html.Div(
        [
            html.Span("FILTERS", className="filters-label"),
            dcc.Dropdown(id="sig-severity", options=dl.SEVERITY_OPTIONS, value="All",
                         clearable=False, searchable=False, className="filter-dd narrow"),
            dcc.Dropdown(id="sig-segment", options=dl.SEGMENT_OPTIONS, value="All",
                         clearable=False, searchable=False, className="filter-dd narrow"),
            dcc.Dropdown(id="sig-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                         clearable=False, searchable=False, className="filter-dd"),
            dcc.Dropdown(id="sig-owner", options=dl.OWNER_OPTIONS, value="All",
                         clearable=False, searchable=False, className="filter-dd narrow"),
            html.Button("Reset", id="sig-reset", className="reset-btn", n_clicks=0),
        ],
        className="filters-row",
    )


def build_signals_kpi_row(quarter, segment, severity, owner):
    data = dl.compute_signals_table(quarter, segment=segment, severity=severity, owner=owner, top_n=0)
    return [
        kpi_card("RED — Critical", str(data["red_count"]), "red", html.Div()),
        kpi_card("AMBER — Elevated", str(data["amber_count"]), "amber", html.Div()),
        kpi_card("GREEN — Watch", str(data["green_count"]), "green", html.Div()),
        kpi_card("Avg AI Risk Score", f"{data['avg_score']:.2f}", "blue", html.Div()),
    ]


def build_signals_table(quarter, segment, severity, owner, sort_state):
    sort_state = sort_state or SIGNALS_DEFAULT_SORT
    data = dl.compute_signals_table(quarter, segment=segment, severity=severity, owner=owner,
                                     sort_col=sort_state["col"], ascending=sort_state["asc"], top_n=20)
    rows = data["rows"]

    header_cells = []
    for label, key, is_num, sortable in SIGNALS_TABLE_COLUMNS:
        is_sorted = sort_state["col"] == key
        arrow = ("↑" if sort_state["asc"] else "↓") if is_sorted else ""
        classes = " ".join(filter(None, ["sorted" if is_sorted else "", "num" if is_num else ""]))
        if sortable:
            header_cells.append(
                html.Th([label, html.Span(arrow, className="sort-arrow")], className=classes or None,
                         id={"type": "sig-sort-th", "col": key}, n_clicks=0)
            )
        else:
            header_cells.append(html.Th(label, className=classes or None))
    thead = html.Thead(html.Tr(header_cells))

    if not rows:
        tbody = html.Tbody(html.Tr(html.Td("No signals match the current filters.", colSpan=len(SIGNALS_TABLE_COLUMNS),
                                            style={"padding": "26px", "textAlign": "center",
                                                   "color": "var(--text-muted)"})))
    else:
        body_rows = []
        for r in rows:
            dot_cls = SEV_DOT_CLASS.get(r["Severity"], "green")
            body_rows.append(
                html.Tr(
                    [
                        html.Td(html.Span(className=f"kpi-dot {dot_cls}"), className="center"),
                        html.Td(r["Borrower"], className="borrower-name"),
                        html.Td(r["Sector"]),
                        html.Td(dl.fmt_bn(r["Exposure"], 2), className="num"),
                        html.Td(r["Trigger"], className="signals-trigger-cell"),
                        html.Td(f"{r['AI Score']:.2f}", className="num"),
                        html.Td(r["Reason Code"]),
                        html.Td(r["Recommended Action"]),
                        html.Td(r["Owner"]),
                    ],
                    id={"type": "borrower-row", "index": r["Account ID"]},
                    n_clicks=0,
                )
            )
        tbody = html.Tbody(body_rows)

    return html.Table([thead, tbody], className="borrower-table signals-table")


def build_signals_table_card(quarter, segment, severity, owner, sort_state):
    return html.Div(
        [
            html.Div(
                [
                    html.Span("EARLY-WARNING SIGNALS", className="table-title"),
                    html.Span("Click a row for full facility detail", className="table-hint"),
                ],
                className="table-card-header",
            ),
            html.Div(build_signals_table(quarter, segment, severity, owner, sort_state),
                      id="signals-table-wrap"),
        ],
        className="table-card",
    )


def build_signals_dashboard(quarter=None, segment="All", severity="All", owner="All", sort_state=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    return html.Div(
        [
            build_page_header("AI Early-Warning Signal Dashboard"),
            build_signals_filters_row(),
            html.Div(build_signals_kpi_row(quarter, segment, severity, owner),
                      className="signals-kpi-grid", id="signals-kpi-row"),
            build_signals_table_card(quarter, segment, severity, owner, sort_state),
        ],
        className="signals-dashboard",
    )


# ------------------------------------------------------------------ AI insight card
# NOTE: this is a static, templated narrative card (title "AI INSIGHT"/"AI COMMENTARY")
# built entirely from real computed figures - it is NOT the interactive "AI
# Intelligence" chat assistant, which stays confined to Cockpit Overview / Borrower 360.

def build_ai_insight_card(text, title="AI INSIGHT"):
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


# ================================================================= concentration

def build_concentration_filters_row():
    return html.Div(
        [
            html.Span("FILTERS", className="filters-label"),
            dcc.Dropdown(id="conc-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                         clearable=False, searchable=False, className="filter-dd"),
            dcc.Dropdown(id="conc-segment", options=dl.SEGMENT_OPTIONS, value="All",
                         clearable=False, searchable=False, className="filter-dd narrow"),
        ],
        className="filters-row",
    )


def _heatmap_tiers(rows):
    all_pcts = sorted((c["pct"] for r in rows for c in r["cells"] if c["pct"] > 0), reverse=True)
    if not all_pcts:
        return lambda pct: "none"
    n = len(all_pcts)
    crit_cut = all_pcts[max(0, int(n * 0.12) - 1)]
    high_cut = all_pcts[max(0, int(n * 0.35) - 1)]
    med_cut = all_pcts[max(0, int(n * 0.65) - 1)]

    def tier(pct):
        if pct <= 0:
            return "none"
        if pct >= crit_cut:
            return "crit"
        if pct >= high_cut:
            return "high"
        if pct >= med_cut:
            return "med"
        return "low"
    return tier


def build_concentration_heatmap_table(data):
    tier_fn = _heatmap_tiers(data["rows"])
    header = html.Thead(html.Tr(
        [html.Th("", className="row-label-head")] + [html.Th(b) for b in data["band_order"]]
    ))
    body_rows = []
    tier_label = {"none": "—", "low": "", "med": "med", "high": "high", "crit": "CRIT"}
    for row in data["rows"]:
        cells = []
        for c in row["cells"]:
            t = tier_fn(c["pct"])
            cells.append(html.Td(tier_label[t], className=f"heatmap-cell tier-{t}",
                                   title=f"{dl.fmt_bn(c['ead'], 2)} · {c['pct']:.2f}% of book"))
        body_rows.append(html.Tr([html.Td(row["sector"], className="heatmap-row-label")] + cells))
    return html.Table([header, html.Tbody(body_rows)], className="heatmap-table")


def build_concentration_body(quarter=None, segment="All"):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_concentration_heatmap(quarter, segment)

    hhi = data["hhi"]
    hhi_label = "Low" if hhi < 0.10 else ("Moderate" if hhi < 0.18 else "High")
    hhi_cls = "up-good" if hhi < 0.10 else ("warn" if hhi < 0.18 else "up-bad")

    heatmap_card = html.Div(
        [
            html.Div([html.Span(className="kpi-dot blue"), "CONCENTRATION HEATMAP — EAD BY SECTOR × INTERNAL GRADE"],
                      className="table-title", style={"padding": "16px 20px 6px", "display": "flex", "gap": "8px", "alignItems": "center"}),
            html.Div(build_concentration_heatmap_table(data), className="heatmap-wrap", style={"padding": "0 20px 16px"}),
            html.Div(
                [
                    html.Span([html.Span(className="heatmap-legend-swatch tier-low"), "Low"]),
                    html.Span([html.Span(className="heatmap-legend-swatch tier-med"), "Medium"]),
                    html.Span([html.Span(className="heatmap-legend-swatch tier-high"), "High"]),
                    html.Span([html.Span(className="heatmap-legend-swatch tier-crit"), "Critical"]),
                ],
                className="heatmap-legend", style={"padding": "0 20px 18px"},
            ),
        ],
        className="table-card",
    )

    side_cards = [
        html.Div(
            [html.Div("PORTFOLIO HHI", className="metric-card-label"),
             html.Div(f"{hhi:.3f}", className="metric-card-value"),
             html.Div(hhi_label, className=f"kpi-sub {hhi_cls}")],
            className="metric-card",
        ),
        html.Div(
            [html.Div("TOP-10 OBLIGOR EXP.", className="metric-card-label"),
             html.Div(dl.fmt_pct(data["top10_pct"], 1), className="metric-card-value"),
             html.Div("of total EAD", className="kpi-sub neutral")],
            className="metric-card",
        ),
        html.Div(
            [html.Div("LARGEST GROUP EXP.", className="metric-card-label"),
             html.Div(dl.fmt_bn(data["largest_group_ead"], 2), className="metric-card-value"),
             html.Div(f"{data['largest_group_pct']:.1f}% of book · {data['largest_group']}", className="kpi-sub neutral")],
            className="metric-card",
        ),
    ]

    cap_rows = []
    for sc in data["sector_caps"][:8]:
        pct = min(sc["utilisation"], 130)
        cls = "breach" if sc["utilisation"] >= 100 else ("warn" if sc["utilisation"] >= 85 else "ok")
        cap_rows.append(
            html.Div(
                [
                    html.Div(sc["sector"], className="util-bar-label"),
                    html.Div(html.Div(className=f"util-bar-fill {cls}", style={"width": f"{min(pct,100)}%"}),
                              className="util-bar-track"),
                    html.Div(f"{sc['utilisation']:.0f}%", className=f"util-bar-value {'is-red' if cls=='breach' else ('is-amber' if cls=='warn' else '')}"),
                ],
                className="util-bar-row",
            )
        )
    cap_card = html.Div(
        [
            html.Div([html.Span(className="kpi-dot amber"), "SECTOR CAP UTILISATION"], className="dark-table-title"),
            html.Div(cap_rows, style={"padding": "0 18px 14px"}),
        ],
        className="dark-table-card",
    )

    worst_sector = data["sector_caps"][0] if data["sector_caps"] else None
    crit_cells = sorted(
        [(row["sector"], c) for row in data["rows"] for c in row["cells"] if c["pct"] > 0],
        key=lambda x: x[1]["pct"], reverse=True,
    )[:1]
    insight_text = "No material concentration detected at current filters."
    if worst_sector and crit_cells:
        top_sector_name, top_cell = crit_cells[0]
        insight_text = (
            f"{worst_sector['sector']} exposure is running at {worst_sector['utilisation']:.0f}% of its "
            f"{worst_sector['cap_pct']:.0f}% sector cap ({dl.fmt_bn(worst_sector['ead'], 2)}), the tightest "
            f"line in the book. The heaviest single cell is {top_sector_name} at Grade {top_cell['band']} "
            f"({dl.fmt_bn(top_cell['ead'], 2)}, {top_cell['pct']:.2f}% of total EAD). Portfolio HHI of {hhi:.3f} "
            f"is {hhi_label.lower()} concentration risk overall; top-10 obligors hold {data['top10_pct']:.1f}% of EAD. "
            f"Recommend pausing new origination in the tightest sector(s) until headroom is restored."
        )

    return [
        html.Div(
            [html.Div([heatmap_card], className="split-main"),
             html.Div(side_cards + [cap_card], className="split-side")],
            className="split-grid",
        ),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


def build_concentration_dashboard(quarter=None, segment="All"):
    return html.Div(
        [
            build_page_header("Portfolio Heatmap & Concentration Risk"),
            build_concentration_filters_row(),
            html.Div(build_concentration_body(quarter, segment), id="concentration-body"),
        ],
        className="signals-dashboard",
    )


# ===================================================================== migration

def build_migration_filters_row():
    return html.Div(
        [
            html.Span("FILTERS", className="filters-label"),
            dcc.Dropdown(id="mig-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                         clearable=False, searchable=False, className="filter-dd"),
            dcc.Dropdown(
                id="mig-period",
                options=[{"label": "QoQ (1 quarter)", "value": 1}, {"label": "Trailing year (4Q)", "value": 4},
                         {"label": "Trailing 2 years (8Q)", "value": 8}],
                value=4, clearable=False, searchable=False, className="filter-dd",
            ),
            dcc.Dropdown(id="mig-segment", options=dl.SEGMENT_OPTIONS, value="All",
                         clearable=False, searchable=False, className="filter-dd narrow"),
        ],
        className="filters-row",
    )


def build_migration_matrix_table(m):
    buckets = m["buckets"]
    matrix = m["matrix"]
    rank = {b: i for i, b in enumerate(buckets)}
    header = html.Thead(html.Tr([html.Th("to →", className="row-label-head")] + [html.Th(b) for b in buckets]))
    body_rows = []
    for r_bucket in buckets:
        cells = []
        for c_bucket in buckets:
            val = int(matrix.loc[r_bucket, c_bucket]) if r_bucket in matrix.index and c_bucket in matrix.columns else 0
            if r_bucket == c_bucket:
                cls = "diag"
            elif rank[c_bucket] > rank[r_bucket]:
                cls = "down"
            elif rank[c_bucket] < rank[r_bucket]:
                cls = "up"
            else:
                cls = "zero"
            display = str(val) if val else "·"
            cells.append(html.Td(display, className=f"migration-cell {cls}" if val else "migration-cell zero"))
        body_rows.append(html.Tr([html.Td(r_bucket, className="row-label-cell")] + cells))
    return html.Table([header, html.Tbody(body_rows)], className="migration-table")


def build_downgrades_by_sector_chart(m):
    rows = m["downgrades_by_sector"][:6]
    fig = go.Figure(go.Bar(
        x=[r["count"] for r in rows], y=[r["sector"] for r in rows], orientation="h",
        marker=dict(color="#e5484d"), text=[r["count"] for r in rows], textposition="outside",
    ))
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=30), height=260,
        xaxis=dict(showgrid=True, gridcolor="#eef1f6"),
        yaxis=dict(autorange="reversed"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", size=11.5, color="#3c4a5a"),
    )
    return html.Div(
        [html.Div("DOWNGRADES BY SECTOR", className="chart-title"), dcc.Graph(figure=fig, config={"displayModeBar": False})],
        className="chart-card",
    )


def build_migration_body(quarter=None, lookback=4, segment="All"):
    quarter = quarter or dl.DEFAULT_QUARTER
    m = dl.compute_rating_migration(quarter, lookback_quarters=lookback, segment=segment)

    kpis = [
        kpi_card("Upgrades", str(m["upgrades"]), "green", html.Div("▲ improving", className="kpi-sub up-good")),
        kpi_card("Stable", str(m["stable"]), "blue", html.Div("no change", className="kpi-sub neutral")),
        kpi_card("Downgrades", str(m["downgrades"]), "red",
                  html.Div(f"{m['downgrades']/max(m['upgrades'],1):.1f}× upgrades", className="kpi-sub up-bad")),
        kpi_card("Net Migration", ("+" if m["net_migration"] >= 0 else "") + str(m["net_migration"]),
                  "green" if m["net_migration"] >= 0 else "amber",
                  html.Div("improving" if m["net_migration"] >= 0 else "deteriorating",
                            className=f"kpi-sub {'up-good' if m['net_migration']>=0 else 'warn'}")),
    ]

    matrix_card = html.Div(
        [
            html.Div(f"MIGRATION MATRIX — OPENING ({m['from_label']}) VS CURRENT ({m['to_label']})",
                      className="table-title", style={"padding": "16px 20px 6px"}),
            html.Div(build_migration_matrix_table(m), style={"padding": "0 20px 16px", "overflowX": "auto"}),
            html.Div(
                [
                    html.Span([html.Span(className="heatmap-legend-swatch tier-med", style={"background": "var(--blue-bg)"}), "Diagonal = stable"]),
                    html.Span([html.Span(className="heatmap-legend-swatch tier-high"), "Downgrade"]),
                    html.Span([html.Span(className="heatmap-legend-swatch tier-low"), "Upgrade"]),
                ],
                className="heatmap-legend", style={"padding": "0 20px 18px"},
            ),
        ],
        className="table-card",
    )

    top_sector = m["downgrades_by_sector"][0] if m["downgrades_by_sector"] else None
    insight_text = "Migration is broadly stable this period."
    if top_sector:
        insight_text = (
            f"Downgrades are concentrated in {top_sector['sector']} ({top_sector['count']} accounts over the period), "
            f"the largest single driver of the {m['downgrades']} total downgrades against {m['upgrades']} upgrades "
            f"(net {'+'if m['net_migration']>=0 else ''}{m['net_migration']}). Recommend a targeted portfolio review "
            f"of {top_sector['sector']} obligors moving toward Rating Bucket 'B' or worse before next quarter's IFRS 9 stage refresh."
        )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div(
            [html.Div([matrix_card], className="split-main"),
             html.Div([build_downgrades_by_sector_chart(m)], className="split-side")],
            className="split-grid",
        ),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


def build_migration_dashboard(quarter=None, lookback=4, segment="All"):
    return html.Div(
        [
            build_page_header("Rating Migration Matrix"),
            build_migration_filters_row(),
            html.Div(build_migration_body(quarter, lookback, segment), id="migration-body"),
        ],
        className="signals-dashboard",
    )


# ============================================================================ EAD

def build_ead_filters_row():
    return html.Div(
        [
            html.Span("FILTERS", className="filters-label"),
            dcc.Dropdown(id="ead-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                         clearable=False, searchable=False, className="filter-dd"),
            dcc.Dropdown(id="ead-segment", options=dl.SEGMENT_OPTIONS, value="All",
                         clearable=False, searchable=False, className="filter-dd narrow"),
        ],
        className="filters-row",
    )


def build_ead_buildup_table(data):
    rows = [
        html.Tr([html.Td(c["component"], className="metric-name"),
                 html.Td(dl.fmt_mn(c["notional"]), className="num"),
                 html.Td(f"{c['ccf']:.0f}%" if c["ccf"] is not None else "20-50%"),
                 html.Td(dl.fmt_mn(c["ccf_ead"]), className="num")])
        for c in data["buildup"]
    ]
    rows.append(html.Tr(
        [html.Td("Total CCF-adjusted EAD", className="metric-name"), html.Td(""),
         html.Td(""), html.Td(dl.fmt_bn(data["ccf_adjusted"], 2), className="num")],
        style={"fontWeight": "800", "background": "var(--teal-light)"},
    ))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Component"), html.Th("Notional", className="num"),
                              html.Th("CCF"), html.Th("CCF-Adjusted EAD", className="num")])),
         html.Tbody(rows)],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot blue"), "EAD BUILD-UP — CCF METHODOLOGY"], className="dark-table-title"), table],
        className="dark-table-card",
    )


def build_utilisation_trend_chart(data):
    trend = data["util_trend"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[t["label"] for t in trend], y=[t["portfolio"] for t in trend],
                               name="Portfolio avg", mode="lines+markers",
                               line=dict(color="#3e7bfa", width=3), marker=dict(size=6)))
    fig.add_trace(go.Scatter(x=[t["label"] for t in trend], y=[t["real_estate"] for t in trend],
                               name="Real estate", mode="lines+markers",
                               line=dict(color="#e5484d", width=3), marker=dict(size=6)))
    fig.update_layout(
        margin=dict(t=10, b=10, l=38, r=20), height=230,
        xaxis=dict(showgrid=False, tickfont=dict(size=10.5, color="#6c7a8c", family="Inter")),
        yaxis=dict(showgrid=True, gridcolor="#eef1f6", ticksuffix="%"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", size=11, color="#3c4a5a"),
    )
    return html.Div(
        [html.Div("UTILISATION OF UNDRAWN FACILITIES (%)", className="chart-title"),
         dcc.Graph(figure=fig, config={"displayModeBar": False})],
        className="chart-card",
    )


def build_drawdown_alerts_table(data):
    if not data["alerts"]:
        rows = [html.Tr(html.Td("No sudden drawdown alerts at current filters.", colSpan=4,
                                  style={"padding": "20px", "textAlign": "center", "color": "var(--text-muted)"}))]
    else:
        rows = [
            html.Tr([html.Td(a["borrower"], className="metric-name"),
                     html.Td(f"{a['prev_pct']:.0f}%", className="num"),
                     html.Td(f"{a['now_pct']:.0f}%", className="num"),
                     html.Td(f"+{a['delta_pp']:.0f}pp", className="num")])
            for a in data["alerts"]
        ]
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Borrower"), html.Th("Prev", className="num"),
                              html.Th("Now", className="num"), html.Th("Δ 30d", className="num")])),
         html.Tbody(rows)],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot red"), "SUDDEN DRAWDOWN ALERTS — UNDRAWN → DRAWN CONVERSION"],
                    className="dark-table-title"), table],
        className="dark-table-card",
    )


def build_ead_body(quarter=None, segment="All"):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_ead_buildup(quarter, segment)

    kpis = [
        kpi_card("Funded Exposure", dl.fmt_bn(data["funded"], 2), "blue", html.Div("drawn balances", className="kpi-sub neutral")),
        kpi_card("Undrawn Commitments", dl.fmt_bn(data["undrawn"], 2), "amber", html.Div("CCF-weighted", className="kpi-sub neutral")),
        kpi_card("Guarantees / SBLC", dl.fmt_bn(data["guarantees"], 2), "purple", html.Div("off-balance-sheet", className="kpi-sub neutral")),
        kpi_card("CCF-Adjusted EAD", dl.fmt_bn(data["ccf_adjusted"], 2), "green", html.Div("regulatory basis", className="kpi-sub neutral")),
    ]

    insight_text = "No sudden drawdown activity detected at current filters."
    if data["alerts"]:
        top = data["alerts"][0]
        insight_text = (
            f"Undrawn-line utilisation jumped {top['prev_pct']:.0f}% → {top['now_pct']:.0f}% for "
            f"{top['borrower']} this quarter — a classic pre-distress liquidity grab. "
            f"{len(data['alerts'])} facilities show a utilisation jump above 15pp. "
            f"Recommend confirming drawdown purpose and re-running the Stage 2 / covenant checks on the flagged names."
        )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div(
            [html.Div([build_ead_buildup_table(data)], className="split-main"),
             html.Div([build_utilisation_trend_chart(data)], className="split-side")],
            className="split-grid",
        ),
        html.Div(build_drawdown_alerts_table(data), style={"marginTop": "20px"}),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


def build_ead_dashboard(quarter=None, segment="All"):
    return html.Div(
        [
            build_page_header("EAD, Utilisation & Off-Balance-Sheet Monitoring"),
            build_ead_filters_row(),
            html.Div(build_ead_body(quarter, segment), id="ead-body"),
        ],
        className="signals-dashboard",
    )


# ========================================================================= IFRS 9

def build_ifrs9_filters_row():
    return html.Div(
        [
            html.Span("FILTERS", className="filters-label"),
            dcc.Dropdown(id="ifrs9-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                         clearable=False, searchable=False, className="filter-dd"),
            dcc.Dropdown(id="ifrs9-segment", options=dl.SEGMENT_OPTIONS, value="All",
                         clearable=False, searchable=False, className="filter-dd narrow"),
        ],
        className="filters-row",
    )


def build_ecl_bridge_chart(data):
    bridge = data["bridge"]
    measures = ["absolute"] + ["relative"] * (len(bridge) - 1)
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures + ["total"],
        x=[b["label"] for b in bridge] + ["Closing"],
        y=[b["value"] for b in bridge] + [0],
        text=[dl.fmt_mn(b["value"]) if b["label"] != "Opening" else dl.fmt_mn(b["value"]) for b in bridge] + [dl.fmt_mn(data["closing"])],
        connector=dict(line=dict(color="#d5dde6")),
        increasing=dict(marker=dict(color="#e5484d")),
        decreasing=dict(marker=dict(color="#1fa971")),
        totals=dict(marker=dict(color="#16b8a6")),
    ))
    fig.update_layout(
        margin=dict(t=10, b=10, l=38, r=20), height=290, showlegend=False,
        yaxis=dict(showgrid=True, gridcolor="#eef1f6", ticksuffix="m", tickprefix="$"),
        xaxis=dict(showgrid=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", size=11, color="#3c4a5a"),
    )
    return html.Div(
        [html.Div("ECL BRIDGE — OPENING → CLOSING ($m)", className="chart-title"),
         dcc.Graph(figure=fig, config={"displayModeBar": False})],
        className="chart-card",
    )


def build_stage_params_table(data):
    rows = [
        html.Tr([
            html.Td(f"Stage {s['stage']}", className="metric-name"),
            html.Td(dl.fmt_bn(s["ead"], 1), className="num"),
            html.Td(f"{s['pd']:.1f}%", className="num"),
            html.Td(f"{s['lgd']:.0f}%", className="num"),
            html.Td(f"{s['cover']:.2f}%", className="num"),
            html.Td(dl.fmt_mn(s["ecl"]), className="num"),
        ], className="is-flagged" if s["stage"] == 3 else None)
        for s in data["stage_table"]
    ]
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Stage"), html.Th("EAD", className="num"), html.Th("PD", className="num"),
                              html.Th("LGD", className="num"), html.Th("Cover", className="num"),
                              html.Th("ECL", className="num")])),
         html.Tbody(rows)],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot purple"), "COVERAGE & PARAMETERS BY STAGE"], className="dark-table-title"), table],
        className="dark-table-card",
    )


def build_sicr_trigger_chips(data):
    if not data["sicr_counts"]:
        return html.Div("No active SICR triggers at current filters.", style={"color": "var(--text-muted)", "fontSize": "13px"})
    chips = [
        html.Span(f"{trigger} ({count})", className="chat-chip", style={"cursor": "default"})
        for trigger, count in sorted(data["sicr_counts"].items(), key=lambda kv: -kv[1])
    ]
    return html.Div(chips, className="chat-suggestions", style={"padding": "6px 0 0"})


def build_ifrs9_body(quarter=None, segment="All"):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_ecl_bridge(quarter, segment)

    kpis = [
        kpi_card("Total ECL", dl.fmt_mn(data["closing"]), "red",
                  html.Div(f"{'▲' if data['closing']>=data['opening'] else '▼'} {dl.fmt_mn(abs(data['closing']-data['opening']))} QoQ",
                            className=f"kpi-sub {'up-bad' if data['closing']>=data['opening'] else 'up-good'}")),
        kpi_card("ECL Coverage", f"{data['ecl_coverage']:.2f}%", "amber", html.Div("of total EAD", className="kpi-sub neutral")),
        kpi_card("Stage 2 Ratio", f"{data['stage2_ratio']:.1f}%", "amber", html.Div("of total EAD", className="kpi-sub neutral")),
        kpi_card("Macro Overlay", dl.fmt_mn(data["macro_overlay"]), "purple", html.Div("downside-weighted", className="kpi-sub neutral")),
    ]

    insight_text = (
        f"Total ECL stands at {dl.fmt_mn(data['closing'])}, a coverage ratio of {data['ecl_coverage']:.2f}% of EAD. "
        f"Stage 2 exposure is {data['stage2_ratio']:.1f}% of the book. "
        + ("New Stage 3 migrations were the largest single driver of the ECL bridge this quarter — recommend a "
           "targeted review of newly-defaulted names for provisioning adequacy." if data["bridge"][4]["value"] > 0
           else "ECL movement this quarter was broadly balanced across migration, macro and DPD effects.")
    )

    return [
        html.Div(kpis, className="signals-kpi-grid"),
        html.Div(
            [html.Div([build_ecl_bridge_chart(data)], className="split-main"),
             html.Div([build_stage_params_table(data)], className="split-side")],
            className="split-grid",
        ),
        html.Div(
            [html.Div([html.Span(className="kpi-dot amber"), "ACTIVE SICR TRIGGERS (STAGE 1 → 2)"], className="table-title"),
             build_sicr_trigger_chips(data)],
            className="table-card", style={"padding": "16px 20px", "marginTop": "20px"},
        ),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


def build_ifrs9_dashboard(quarter=None, segment="All"):
    return html.Div(
        [
            build_page_header("IFRS 9 / ECL Portfolio Monitoring"),
            build_ifrs9_filters_row(),
            html.Div(build_ifrs9_body(quarter, segment), id="ifrs9-body"),
        ],
        className="signals-dashboard",
    )


# ============================================================= covenants (B360)

def build_covenants_filters_row():
    return html.Div(
        [
            html.Span("FILTERS", className="filters-label"),
            dcc.Dropdown(id="cov-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                         clearable=False, searchable=False, className="filter-dd"),
            dcc.Dropdown(
                id="cov-threshold",
                options=[{"label": "Headroom < 10%", "value": 10}, {"label": "Headroom < 20%", "value": 20},
                         {"label": "Headroom < 30%", "value": 30}],
                value=20, clearable=False, searchable=False, className="filter-dd",
            ),
        ],
        className="filters-row",
    )


def build_covenant_dashboard_table(rows):
    body_rows = []
    for r in rows:
        headroom = r["headroom"]
        hr_cls = "is-flagged" if headroom < 10 else None
        body_rows.append(html.Tr([
            html.Td(r["borrower"], className="metric-name"),
            html.Td(f"{r['dscr']:.2f}", className=f"num {'' if r['dscr'] >= 1.2 else 'is-flagged-text'}"),
            html.Td(f"{r['leverage']:.1f}x" if r["leverage"] is not None else "—", className="num"),
            html.Td(f"{r['int_cov']:.1f}x" if r["int_cov"] is not None else "—", className="num"),
            html.Td(f"{r['liquidity']:.1f}" if r["liquidity"] is not None else "—", className="num"),
            html.Td(html.Span(f"{headroom:.1f}%", className=f"gap-pill {'is-aligned' if headroom >= 20 else ''}")),
            html.Td(r["likely_breach"] or "—"),
        ], className=hr_cls))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Borrower"), html.Th("DSCR", className="num"), html.Th("Leverage", className="num"),
                              html.Th("Int. Cov.", className="num"), html.Th("Liquidity", className="num"),
                              html.Th("Headroom"), html.Th("Likely Breach")])),
         html.Tbody(body_rows)],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot blue"), "COVENANT DASHBOARD"], className="dark-table-title"), table],
        className="dark-table-card",
    )


def build_collateral_dashboard_table(rows):
    body_rows = []
    for r in rows:
        gap = r["coverage_gap"]
        gap_cls = "is-aligned" if gap >= 0 else ""
        body_rows.append(html.Tr([
            html.Td(r["borrower"], className="metric-name"),
            html.Td(r["type"]),
            html.Td(dl.fmt_bn(r["value"], 2), className="num"),
            html.Td(f"{r['valn_age_months']} mo" if r["valn_age_months"] is not None else "—",
                     className=f"num {'is-flagged-text' if (r['valn_age_months'] or 0) > 12 else ''}"),
            html.Td(f"{r['ltv']:.0f}%" if r["ltv"] is not None else "—", className="num"),
            html.Td(dl.fmt_bn(r["forced_sale"], 2), className="num"),
            html.Td(f"{r['haircut']:.0f}%", className="num"),
            html.Td(html.Span(f"{'+' if gap >= 0 else ''}{dl.fmt_bn(gap, 2)}", className=f"gap-pill {gap_cls}")),
        ]))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Borrower"), html.Th("Collateral Type"), html.Th("Value", className="num"),
                              html.Th("Valn. Age", className="num"), html.Th("LTV", className="num"),
                              html.Th("Forced-Sale Val", className="num"), html.Th("Stress Haircut", className="num"),
                              html.Th("Coverage Gap", className="num")])),
         html.Tbody(body_rows)],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot purple"), "COLLATERAL DASHBOARD"], className="dark-table-title"), table],
        className="dark-table-card",
    )


def build_covenants_body(quarter=None, min_headroom=20):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_covenant_watchlist(quarter, min_headroom=min_headroom)

    if not data["covenant_rows"]:
        empty = html.Div(f"No borrowers currently fall below {min_headroom}% covenant headroom at {quarter}.",
                           className="placeholder-panel")
        return [empty]

    worst = data["covenant_rows"][0]
    worst_collateral = next((c for c in data["collateral_rows"] if c["borrower"] == worst["borrower"]), None)
    insight_bits = [
        f"{worst['borrower']} has the tightest headroom in the book at {worst['headroom']:.1f}%",
        f"DSCR of {worst['dscr']:.2f}x" if worst["dscr"] is not None else None,
        f"likely covenant breach by {worst['likely_breach']}" if worst["likely_breach"] else None,
    ]
    insight_text = ", ".join(b for b in insight_bits if b) + ". "
    if worst_collateral and worst_collateral["coverage_gap"] < 0:
        insight_text += (
            f"Collateral coverage is also short by {dl.fmt_bn(abs(worst_collateral['coverage_gap']), 2)} on a "
            f"forced-sale basis after the {worst_collateral['haircut']:.0f}% stress haircut. "
        )
    insight_text += f"{len(data['covenant_rows'])} borrowers are below the current headroom threshold — recommend prioritising remediation plans for the top names."

    return [
        build_covenant_dashboard_table(data["covenant_rows"]),
        build_collateral_dashboard_table(data["collateral_rows"]),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


def build_covenants_dashboard(quarter=None, min_headroom=20):
    return html.Div(
        [
            build_page_header("Covenant & Collateral Monitoring"),
            build_covenants_filters_row(),
            html.Div(build_covenants_body(quarter, min_headroom), id="covenants-body",
                      style={"display": "flex", "flexDirection": "column", "gap": "20px"}),
        ],
        className="signals-dashboard",
    )


# ============================================================= WATCHLIST section

def build_kanban_card(item):
    dot_color = "red" if item["ai_score"] >= 0.7 else ("amber" if item["ai_score"] >= 0.4 else "green")
    return html.Div(
        [
            html.Div(
                [html.Div(item["borrower"], className="kanban-card-borrower"),
                 html.Div(item["owner_initials"], className="kanban-avatar")],
                className="kanban-card-top",
            ),
            html.Div(dl.fmt_bn(item["ead"], 2), className="kanban-card-ead"),
            html.Div(
                [html.Span(className="kanban-score-dot", style={"background": f"var(--{dot_color})"}), item["trigger"]],
                className="kanban-card-trigger",
            ),
        ],
        className="kanban-card",
    )


def build_watchlist_kanban(data):
    columns = []
    for col in dl.WATCHLIST_COLUMNS:
        items = data["board"].get(col, [])
        count = data["counts"].get(col, 0)
        body = [build_kanban_card(item) for item in items] if items else [html.Div("No accounts", className="kanban-empty")]
        columns.append(
            html.Div(
                [
                    html.Div([html.Span(col, className="kanban-column-title"), html.Span(str(count), className="kanban-count-badge")],
                              className="kanban-column-header"),
                    html.Div(body),
                ],
                className="kanban-column",
            )
        )
    return html.Div(columns, className="kanban-board")


def build_ai_copilot_panel(data, expanded=False):
    candidates = []
    for col in ["Restructuring", "Recovery", "Watchlist", "Under Review", "New"]:
        for item in data["board"].get(col, []):
            candidates.append((col, item))
    candidates.sort(key=lambda ci: -ci[1]["ai_score"])
    recs = candidates[: (6 if expanded else 3)]

    rec_cards = [
        html.Div(
            [
                html.Div(item["borrower"], className="copilot-rec-name"),
                html.Div("New → Watchlist" if col == "New" else f"→ {col}", className="copilot-rec-move"),
                html.Div(item["trigger"], className="copilot-rec-desc"),
                html.Button("Apply", id={"type": "copilot-apply", "index": f"{item['customer_id']}-{i}"},
                             n_clicks=0, className="copilot-apply-btn"),
            ],
            className="copilot-rec-card",
        )
        for i, (col, item) in enumerate(recs)
    ]

    trajectory_rows = [
        html.Div(
            [html.Span([html.Span(className="kpi-dot amber"), item["borrower"]], className="copilot-trajectory-name"),
             html.Span(f"{int(item['ai_score'] * 100)}%", style={"fontWeight": "800"})],
            className="copilot-trajectory-row",
        )
        for _, item in candidates[:4]
    ]

    children = [
        html.Div(
            [html.Div([html.Div("AI", className="ai-insight-icon", style={"width": "22px", "height": "22px", "fontSize": "10px"}),
                        "AI Watch Copilot"], className="copilot-title"),
             html.Span(f"{len(candidates)} INSIGHTS", className="copilot-badge")],
            className="copilot-header",
        ),
        html.Div("RECOMMENDED MOVES", className="copilot-section-label"),
        html.Div(rec_cards) if rec_cards else html.Div("No open recommendations.", style={"color": "#93a8bd", "fontSize": "12px"}),
        html.Div("PREDICTED TRAJECTORY", className="copilot-section-label"),
        html.Div(trajectory_rows) if trajectory_rows else html.Div("—", style={"color": "#93a8bd", "fontSize": "12px"}),
    ]
    if expanded:
        draft_text = "No draft communication generated yet."
        if candidates:
            _, item = candidates[0]
            draft_text = (
                f"To {item['owner_initials']} (RM) — Re: {item['borrower']}. "
                f"\"{item['trigger']} — please file an updated forecast and remediation plan within 10 business days.\""
            )
        children += [html.Div("AUTO-DRAFTED ACTION", className="copilot-section-label"),
                     html.Div(draft_text, className="copilot-draft-box")]
    return html.Div(children, className="copilot-panel")


def build_watchlist_actions_table(data):
    rows = []
    for col in ["Restructuring", "Recovery", "Watchlist", "Under Review", "New"]:
        for item in data["board"].get(col, []):
            rows.append((col, item))
    rows.sort(key=lambda ci: -ci[1]["ai_score"])

    body_rows = [
        html.Tr([
            html.Td(item["borrower"], className="metric-name"), html.Td(dl.fmt_bn(item["ead"], 2), className="num"),
            html.Td(col), html.Td(item["trigger"]), html.Td(f"{item['ai_score']:.2f}", className="num"),
            html.Td(item["owner_initials"]),
        ])
        for col, item in rows[:20]
    ]
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Borrower"), html.Th("Exposure", className="num"), html.Th("Stage"),
                              html.Th("Trigger"), html.Th("AI Score", className="num"), html.Th("Owner")])),
         html.Tbody(body_rows)],
        className="borrower-table signals-table",
    )
    return html.Div(
        [html.Div([html.Span("RECOMMENDED ACTIONS", className="table-title")], className="table-card-header"), table],
        className="table-card",
    )


def build_watchlist_tab_board(quarter=None):
    data = dl.compute_watchlist_board(quarter or dl.DEFAULT_QUARTER)
    return [
        html.Div(
            [html.Div([build_watchlist_kanban(data)], className="split-main"),
             html.Div([build_ai_copilot_panel(data, expanded=False)], className="split-side")],
            className="split-grid",
        ),
    ]


def build_watchlist_tab_actions(quarter=None):
    data = dl.compute_watchlist_board(quarter or dl.DEFAULT_QUARTER, top_n_per_col=20)
    return [build_watchlist_actions_table(data)]


def build_watchlist_tab_copilot(quarter=None):
    data = dl.compute_watchlist_board(quarter or dl.DEFAULT_QUARTER, top_n_per_col=20)
    return [build_ai_copilot_panel(data, expanded=True)]


# ================================================================ LIMITS section

def build_qoq_delta_cell(r):
    """Quarter-on-quarter movement in utilisation.

    Rising toward a cap is bad and falling away from it is good, so the tone is
    keyed to direction rather than sign-of-number. A line with no comparable
    prior quarter (a new single-name leader, or the first quarter in the series)
    shows a dash instead of a fabricated zero."""
    delta = r.get("delta_pct")
    if delta is None:
        return html.Div("—", className="util-delta is-none", title="No comparable prior quarter")
    if abs(delta) < 0.05:
        return html.Div("flat", className="util-delta is-flat", title="Unchanged QoQ")
    up = delta > 0
    tone = "is-bad" if up else "is-good"
    marker = "▲" if up else "▼"
    prev = r.get("prev_pct")
    tip = f"{prev:.0f}% → {r['pct']:.0f}% since last quarter" if prev is not None else ""
    return html.Div(f"{marker} {abs(delta):.1f}pp", className=f"util-delta {tone}", title=tip)


def build_limits_rows_ui(rows, show_delta=False, highlight_labels=None):
    highlight_labels = set(highlight_labels or ())
    row_divs = []
    for r in rows:
        pct = r["pct"]
        cls = "breach" if pct >= 100 else ("warn" if pct >= 90 else "ok")
        val_cls = "is-red" if cls == "breach" else ("is-amber" if cls == "warn" else "")
        label_children = [r["label"]]
        if r.get("newly_breached"):
            label_children.append(html.Span("NEW BREACH", className="util-flag is-bad"))
        elif r.get("newly_cured"):
            label_children.append(html.Span("CURED", className="util-flag is-good"))
        if r["label"] in highlight_labels:
            label_children.append(html.Span("THIS BORROWER", className="util-flag is-info"))

        cells = [
            html.Div(label_children, className="util-bar-label", style={"width": "230px"}),
            html.Div(html.Div(className=f"util-bar-fill {cls}", style={"width": f"{min(pct,100)}%"}),
                      className="util-bar-track"),
            html.Div(f"{dl.fmt_bn(r['used'], 2)} / {dl.fmt_bn(r['cap'], 2)}",
                      className="util-bar-value", style={"width": "150px"}),
            html.Div(f"{pct:.0f}%", className=f"util-bar-value {val_cls}"),
        ]
        if show_delta:
            cells.append(build_qoq_delta_cell(r))
        row_divs.append(html.Div(
            cells,
            className="util-bar-row" + (" is-highlighted" if r["label"] in highlight_labels else ""),
        ))
    return row_divs


BREACH_WORKFLOW_STEPS = [
    ("Identify", "Auto-detected"), ("Assign Owner", "Risk Team"), ("Escalate", "Committee"),
    ("Action", "Reduce / reprice"), ("Closure", "Sign-off + audit"),
]


def build_breach_workflow():
    steps = [
        html.Div(
            [html.Div(str(i), className="kanban-avatar", style={"background": "var(--purple)", "width": "26px", "height": "26px", "fontSize": "11px"}),
             html.Div([html.Div(label, style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Div(sub, style={"fontSize": "11px", "color": "var(--text-muted)"})])],
            style={"display": "flex", "alignItems": "center", "gap": "12px", "padding": "9px 0"},
        )
        for i, (label, sub) in enumerate(BREACH_WORKFLOW_STEPS, 1)
    ]
    return html.Div(
        [html.Div([html.Span(className="kpi-dot purple"), "BREACH RESOLUTION WORKFLOW"], className="table-title",
                    style={"display": "flex", "gap": "8px", "alignItems": "center", "padding": "16px 20px 6px"}),
         html.Div(steps, style={"padding": "0 20px 18px"})],
        className="table-card",
    )


def build_limits_body(quarter=None, segment="All", view="Appetite", highlight_labels=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_limits_dashboard(quarter, segment)
    rows = list(data["rows"])
    # Utilisation is the movement view: sorted by how close each line is to its
    # cap, and the only view that carries the quarter-on-quarter change.
    show_delta = view == "Utilisation"
    if view == "Utilisation":
        rows.sort(key=lambda r: -r["pct"])
    elif view == "Breaches":
        rows = [r for r in rows if r["pct"] >= 100]

    header = [html.Span(className="kpi-dot amber"), "APPROVED LIMIT VS UTILISATION"]
    if show_delta and data["has_comparison"]:
        header.append(html.Span(f"vs {dl._quarter_label(data['prev_quarter'])}",
                                className="util-header-note"))

    bars_card = html.Div(
        [html.Div(header, className="table-title",
                    style={"display": "flex", "gap": "8px", "alignItems": "center", "padding": "16px 20px 6px"}),
         html.Div(build_limits_rows_ui(rows, show_delta=show_delta, highlight_labels=highlight_labels) if rows else
                   html.Div("No limits at this filter.", style={"padding": "20px", "color": "var(--text-muted)", "textAlign": "center"}),
                   style={"padding": "0 20px 18px"})],
        className="table-card",
    )
    kpi_side = [
        kpi_card("Active Breaches", str(data["active_breaches"]), "red",
                 kpi_sub_qoq(data["newly_breached"], "new this quarter") if show_delta else html.Div()),
        kpi_card("Near Limit (>90%)", str(data["near_limit"]), "amber", html.Div()),
        kpi_card("Within Appetite", str(data["within_appetite"]), "green",
                 kpi_sub_qoq(-data["newly_cured"], "cured this quarter") if show_delta else html.Div()),
    ]

    breach_lines = [r for r in data["rows"] if r["pct"] >= 100][:3]
    insight_text = "All appetite lines are within threshold."
    if breach_lines:
        names = ", ".join(f"{r['label']} ({r['pct']:.0f}%)" for r in breach_lines)
        insight_text = (
            f"{data['active_breaches']} hard breaches are live: {names}. "
            f"Recommend reducing or re-pricing the tightest facilities to restore headroom before next quarter's appetite review."
        )
    if show_delta and data["has_comparison"]:
        insight_text += (
            f" Quarter on quarter, {data['rising']} of {len(data['rows'])} lines moved up against their cap"
            + (f", {data['newly_breached']} crossing into breach" if data["newly_breached"] else "")
            + (f" and {data['newly_cured']} falling back within appetite" if data["newly_cured"] else "")
            + "."
        )

    return [
        html.Div(
            [html.Div([bars_card], className="split-main"),
             html.Div(kpi_side + [build_breach_workflow()], className="split-side")],
            className="split-grid",
        ),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


def kpi_sub_qoq(count, label):
    """Small QoQ note under a limits KPI card. Zero is worth stating explicitly —
    'none new this quarter' is information, a blank space is not."""
    if not count:
        return html.Div(f"none {label}", className="kpi-sub neutral")
    up = count > 0
    return html.Div(f"{'▲' if up else '▼'} {abs(count)} {label}",
                    className=f"kpi-sub {'up-bad' if up else 'up-good'}")


# ================================================================ STRESS section

BASELINE_CET1_PCT = 13.0


def build_scenario_bubble(role, text, confidence=None):
    # The lab's own replies name scenarios and quote figures, so they are written
    # as Markdown and rendered as such — the user's echoed input stays plain text.
    children = [text] if role == "user" else [dcc.Markdown(text, className="scenario-md")]
    if confidence is not None:
        children.append(html.Span(f"Confidence {confidence:.2f}", className="confidence-tag"))
    return html.Div(children, className=f"scenario-bubble {'is-user' if role == 'user' else 'is-ai'}")


def render_scenario_console(history):
    if not history:
        return [html.Div(
            "Describe a shock in plain English — the AI propagates it through the MEV → IFRS 9 ECL engine.",
            style={"color": "var(--text-muted)", "fontSize": "13px", "textAlign": "center", "padding": "30px 10px"},
        )]
    return [build_scenario_bubble(m["role"], m["text"], m.get("confidence")) for m in history]


def build_scenario_kpi_cards(result):
    return [
        html.Div([html.Div("STRESSED ECL", className="metric-card-label"),
                   html.Div(dl.fmt_mn(result["stressed_ecl"]), className="metric-card-value is-red"),
                   html.Div(f"{'▲' if result['ecl_delta'] >= 0 else '▼'} {dl.fmt_mn(abs(result['ecl_delta']))}", className="metric-card-sub is-red")],
                  className="metric-card"),
        html.Div([html.Div("CET1 IMPACT", className="metric-card-label"),
                   html.Div(f"{result['cet1_bps_impact']:.0f} bps", className="metric-card-value is-red"),
                   html.Div(f"to {BASELINE_CET1_PCT + result['cet1_bps_impact'] / 100:.1f}%", className="metric-card-sub is-muted")],
                  className="metric-card"),
        html.Div([html.Div("STRESSED NPL", className="metric-card-label"),
                   html.Div(f"{result['stressed_npl_pct']:.1f}%", className="metric-card-value is-amber"),
                   html.Div(f"▲ {result['stressed_npl_pct'] - result['base_npl_pct']:.1f}pp", className="metric-card-sub is-amber")],
                  className="metric-card"),
        html.Div([html.Div("COVENANT BREACHES", className="metric-card-label"),
                   html.Div(f"{result['covenant_breach_count']} names", className="metric-card-value is-red"),
                   html.Div("RE / Contracting" if result["covenant_breach_count"] else "none projected",
                             className=f"metric-card-sub {'is-red' if result['covenant_breach_count'] else 'is-muted'}")],
                  className="metric-card"),
    ]


def build_preset_cards(active_id=None):
    """The named scenarios. One click loads a fully specified shock, so the lab
    is usable without guessing which phrasings the free-text parser accepts."""
    return html.Div(
        [
            html.Button(
                [
                    html.Div(p["label"], className="preset-label"),
                    html.Div(p["detail"], className="preset-detail"),
                ],
                id={"type": "scenario-preset", "preset": p["id"]},
                n_clicks=0,
                title=p["rationale"],
                className=f"preset-card tone-{p['tone']}" + (" is-active" if p["id"] == active_id else ""),
            )
            for p in stress_lab.PRESETS
        ],
        className="preset-row",
    )


def build_recall_chips(recent=None):
    """Questions asked here before, offered back as one-click chips.

    Recorded automatically on every send and kept in browser storage, so coming
    back to the lab resumes the analyst's own line of enquiry rather than a blank
    box. Seeded with starters so the row is never empty on a first visit."""
    questions = stress_lab.recall_questions(recent)
    return html.Div(
        [html.Span("ASK AGAIN", className="recall-label")]
        + [
            html.Div(q, id={"type": "scenario-recall", "text": q}, n_clicks=0,
                     className="recall-chip", title="Ask this again")
            for q in questions
        ],
        className="recall-row",
    )


def build_scenario_lab_body(quarter=None, params=None, recent=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    params = params or {}
    result = dl.compute_stress_scenario(quarter, params.get("rate_shock_bps", 0),
                                        params.get("cre_price_shock_pct", 0))
    console_card = html.Div(
        [
            html.Div([html.Span(className="kpi-dot teal"), "AI SCENARIO LAB"], className="table-title",
                       style={"display": "flex", "gap": "8px", "alignItems": "center", "padding": "16px 20px 4px"}),
            html.Div("Pick a scenario below, or describe a shock in plain English — the AI propagates "
                     "it through the MEV → IFRS 9 ECL engine.",
                       style={"padding": "0 20px 12px", "color": "var(--text-muted)", "fontSize": "12px"}),
            html.Div(build_preset_cards(params.get("preset_id")), id="scenario-presets",
                     style={"padding": "0 20px 6px"}),
            html.Div(stress_lab.describe_params(params), id="scenario-active-shock",
                     className="active-shock-strip"),
            html.Div(id="scenario-console", className="scenario-console", style={"padding": "0 20px"}),
            html.Div(build_recall_chips(recent), id="scenario-recall-row",
                     style={"padding": "0 20px"}),
            html.Div(
                [
                    dcc.Input(id="scenario-input", type="text", placeholder="Describe a shock or ask a follow-up...",
                               n_submit=0, autoComplete="off"),
                    html.Button("→", id="scenario-send", n_clicks=0, className="scenario-send-btn"),
                ],
                className="scenario-input-row", style={"padding": "0 20px 18px"},
            ),
        ],
        className="table-card",
    )
    kpi_side = html.Div(id="scenario-kpi-side", children=build_scenario_kpi_cards(result))
    return [
        html.Div(
            [html.Div([console_card], className="split-main"),
             html.Div([kpi_side], className="split-side")],
            className="split-grid",
        ),
    ]


def build_transmission_diagram(result):
    boxes = [
        ("POLICY RATE", f"{result['rate_shock_bps']:+.0f} bps", ""),
        ("GDP GROWTH", f"{result['gdp_impact_pct']:.1f}%", "elasticity model"),
        ("CRE VALUES", f"-{result['cre_price_fall_pct']:.0f}%", "cap-rate model"),
        ("PiT PD", f"+{result['pit_pd_notches']:.1f} notch", "MEV-PD v3"),
        ("PORTFOLIO ECL", f"{'+' if result['ecl_delta'] >= 0 else ''}{dl.fmt_mn(result['ecl_delta'])}", "IFRS 9 engine"),
    ]
    items = []
    for i, (label, value, sub) in enumerate(boxes):
        items.append(html.Div([html.Div(label, className="transmission-label"), html.Div(value, className="transmission-value"),
                                 html.Div(sub, className="transmission-sub")], className="transmission-box"))
        if i < len(boxes) - 1:
            items.append(html.Span("→", className="transmission-arrow"))
    return html.Div(items, className="transmission-row")


def build_stress_results_body_from_result(result):
    return [
        html.Div(build_scenario_kpi_cards(result), className="signals-kpi-grid"),
        html.Div(
            [html.Div("SHOCK TRANSMISSION · MEV → IFRS 9 ECL", className="table-title", style={"padding": "16px 20px 10px"}),
             html.Div(build_transmission_diagram(result), style={"padding": "0 20px 18px"})],
            className="table-card",
        ),
        html.Div(build_ai_insight_card(
            f"Under the last modelled scenario ({result['rate_shock_bps']:+.0f}bps rate / -{result['cre_price_fall_pct']:.0f}% CRE), "
            f"stressed ECL reaches {dl.fmt_mn(result['stressed_ecl'])} ({'+' if result['ecl_delta'] >= 0 else ''}{dl.fmt_mn(result['ecl_delta'])}) "
            f"and CET1 moves {result['cet1_bps_impact']:.0f}bps. {result['covenant_breach_count']} Real Estate / Contracting "
            f"borrowers are projected to breach covenants under this scenario."
        ), style={"marginTop": "20px"}),
    ]


def build_reverse_stress_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    rs = dl.compute_reverse_stress(quarter)
    if rs["required_rate_shock_bps"] is None:
        return [html.Div("No shock within the tested range (up to 2000bps) breaches the target CET1 impact.",
                           className="placeholder-panel")]
    at = rs["at_breach"]
    cards = [
        html.Div([html.Div("REQUIRED RATE SHOCK", className="metric-card-label"),
                   html.Div(f"+{rs['required_rate_shock_bps']:.0f} bps", className="metric-card-value is-red"),
                   html.Div(f"to breach {rs['target_cet1_bps']:.0f}bps CET1 target", className="metric-card-sub is-muted")],
                  className="metric-card"),
        html.Div([html.Div("RESULTING STRESSED ECL", className="metric-card-label"),
                   html.Div(dl.fmt_mn(at["stressed_ecl"]), className="metric-card-value is-red"),
                   html.Div(f"+{dl.fmt_mn(at['ecl_delta'])} vs base", className="metric-card-sub is-red")],
                  className="metric-card"),
        html.Div([html.Div("RESULTING STRESSED NPL", className="metric-card-label"),
                   html.Div(f"{at['stressed_npl_pct']:.1f}%", className="metric-card-value is-amber"),
                   html.Div(f"vs {at['base_npl_pct']:.1f}% base", className="metric-card-sub is-muted")],
                  className="metric-card"),
        html.Div([html.Div("COVENANT BREACHES AT THAT SHOCK", className="metric-card-label"),
                   html.Div(f"{at['covenant_breach_count']} names", className="metric-card-value is-red"),
                   html.Div("Real Estate / Contracting", className="metric-card-sub is-muted")],
                  className="metric-card"),
    ]
    insight = build_ai_insight_card(
        f"A uniform policy-rate shock of at least +{rs['required_rate_shock_bps']:.0f}bps is required to push CET1 impact past "
        f"{rs['target_cet1_bps']:.0f}bps — beyond that point stressed ECL reaches {dl.fmt_mn(at['stressed_ecl'])} and "
        f"{at['covenant_breach_count']} Real Estate / Contracting borrowers breach covenants. "
        f"Recommend this as the working severe-but-plausible calibration point for the next ICAAP stress run."
    )
    return [html.Div(cards, className="signals-kpi-grid"), html.Div(insight, style={"marginTop": "20px"})]


# ============================================================= ANALYTICS section

def build_profitability_scatter(rows, hurdle):
    fig = go.Figure()
    for r in rows:
        color = "#1fa971" if r["raroc"] >= hurdle else "#e5484d"
        fig.add_trace(go.Scatter(
            x=[r["rorwa"]], y=[r["raroc"]], mode="markers+text", text=[r["sector"]], textposition="top center",
            marker=dict(size=max(14, min(60, r["ead"] / 300)), color=color, opacity=0.75, line=dict(width=1, color="#fff")),
            hovertemplate=f"<b>{r['sector']}</b><br>EAD: {dl.fmt_bn(r['ead'], 2)}<br>RAROC: {r['raroc']:.1f}%<br>RoRWA: {r['rorwa']:.1f}%<extra></extra>",
            showlegend=False,
        ))
    fig.add_hline(y=hurdle, line_dash="dash", line_color="#93a8bd", annotation_text=f"Hurdle {hurdle:.0f}%")
    fig.update_layout(
        margin=dict(t=20, b=40, l=50, r=20), height=360,
        xaxis=dict(title="RoRWA (%)", showgrid=True, gridcolor="#eef1f6"),
        yaxis=dict(title="RAROC (%)", showgrid=True, gridcolor="#eef1f6"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", size=11, color="#3c4a5a"),
    )
    return html.Div([html.Div("RISK-ADJUSTED RETURN MAP — BUBBLE SIZE = EAD", className="chart-title"),
                       dcc.Graph(figure=fig, config={"displayModeBar": False})], className="chart-card")


def build_profitability_table(rows, hurdle):
    body_rows = [
        html.Tr([
            html.Td(r["sector"], className="metric-name"),
            html.Td(f"{r['raroc']:.1f}%", className=f"num {'' if r['above_hurdle'] else 'is-flagged-text'}"),
            html.Td(f"{r['rorwa']:.1f}%", className="num"),
        ], className="is-flagged" if not r["above_hurdle"] else None)
        for r in rows
    ]
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Sector"), html.Th(f"RAROC (hurdle {hurdle:.0f}%)", className="num"), html.Th("RoRWA", className="num")])),
         html.Tbody(body_rows)],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot purple"), "RISK-ADJUSTED RETURNS BY SECTOR"], className="dark-table-title"), table],
        className="dark-table-card",
    )


def build_profitability_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_profitability(quarter)
    below = [r for r in data["rows"] if not r["above_hurdle"]]
    insight_text = "All sectors are earning above the hurdle rate."
    if below:
        below_sorted = sorted(below, key=lambda r: r["ead"], reverse=True)[:2]
        names = " and ".join(r["sector"] for r in below_sorted)
        total_ead = sum(r["ead"] for r in data["rows"])
        combined_ead_pct = sum(r["ead"] for r in below) / total_ead * 100 if total_ead else 0.0
        insight_text = (
            f"{names} consume {combined_ead_pct:.0f}% of portfolio capital but return below the {data['hurdle']:.0f}% hurdle, "
            f"eroding economic value. Recommend re-pricing or reallocating limit headroom toward the highest-RAROC sectors "
            f"to lift portfolio-wide risk-adjusted returns with no change in total EAD."
        )
    return [
        html.Div(
            [html.Div([build_profitability_scatter(data["rows"], data["hurdle"])], className="split-main"),
             html.Div([build_profitability_table(data["rows"], data["hurdle"])], className="split-side")],
            className="split-grid",
        ),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


def build_capital_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_profitability(quarter)
    total_ead = sum(r["ead"] for r in data["rows"])
    port_raroc = sum(r["raroc"] * r["ead"] for r in data["rows"]) / total_ead if total_ead else 0.0
    kpi = [
        kpi_card("Total EAD", dl.fmt_bn(total_ead, 2), "blue", html.Div("across all sectors", className="kpi-sub neutral")),
        kpi_card("Portfolio RAROC", f"{port_raroc:.1f}%", "purple", html.Div(f"vs {data['hurdle']:.0f}% hurdle", className="kpi-sub neutral")),
    ]
    sorted_by_ead = sorted(data["rows"], key=lambda r: r["ead"], reverse=True)
    return [html.Div(kpi, className="signals-kpi-grid"), build_profitability_table(sorted_by_ead, data["hurdle"])]


def build_pricing_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    hurdle = dl.compute_profitability(quarter)["hurdle"]
    rows = dl.compute_underpriced_borrowers(quarter, hurdle=hurdle)
    body_rows = [
        html.Tr([html.Td(r["borrower"], className="metric-name"), html.Td(r["sector"]), html.Td(dl.fmt_bn(r["ead"], 2), className="num"),
                  html.Td(f"{r['raroc']:.1f}%", className="num"), html.Td(f"{r['gap']:.1f}pp", className="num")])
        for r in rows
    ]
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Borrower"), html.Th("Sector"), html.Th("EAD", className="num"),
                              html.Th("RAROC", className="num"), html.Th("Gap to Hurdle", className="num")])),
         html.Tbody(body_rows)],
        className="borrower-table signals-table",
    )
    insight_text = (
        f"{len(rows)} borrowers are priced below the {hurdle:.0f}% hurdle. Recommend a repricing exercise at next "
        f"renewal for the largest-EAD names on this list."
    ) if rows else "All reviewed borrowers are priced at or above the hurdle rate."
    return [
        html.Div([html.Div([html.Span("BORROWERS BELOW HURDLE — REPRICING CANDIDATES", className="table-title")], className="table-card-header"), table],
                  className="table-card"),
        html.Div(build_ai_insight_card(insight_text), style={"marginTop": "20px"}),
    ]


# ==================================================================== ESG section
# The ESG section is built entirely in frontend/esg_view.py, on top of the
# backend/climate engine. Its tab bodies are dispatched from
# build_section_tab_body and its interactivity lives in the callbacks below.


# ================================================================ REPORTS section

def build_report_checkbox(label):
    return html.Div(
        [dcc.Checklist(options=[{"label": " " + label, "value": "on"}], value=["on"], inline=True)],
        className="report-checkbox-row",
    )


REPORT_SECTIONS = ["Executive summary", "Portfolio movement", "Limit breaches", "Concentration & heatmaps",
                    "Watchlist & actions", "Stress results", "ECL / IFRS 9", "AI commentary"]


def build_review_pack_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    k = dl.compute_kpis(quarter)
    m = dl.compute_rating_migration(quarter)
    conc = dl.compute_concentration_heatmap(quarter)
    stress = dl.compute_stress_scenario(quarter, 300, 25)
    top_sector = conc["sector_caps"][0] if conc["sector_caps"] else None
    top_downgrade_sector = m["downgrades_by_sector"][0] if m["downgrades_by_sector"] else None

    config_panel = html.Div(
        [
            html.Div("GENERATE REVIEW PACK", className="table-title"),
            html.Div("REPORTING PERIOD", className="report-config-label"),
            dcc.Dropdown(options=dl.QUARTER_OPTIONS, value=quarter, clearable=False, searchable=False,
                          className="filter-dd", style={"width": "100%"}),
            html.Div("PORTFOLIO SCOPE", className="report-config-label"),
            dcc.Dropdown(options=[{"label": "Wholesale — GCC", "value": "all"}], value="all", clearable=False,
                          searchable=False, className="filter-dd", style={"width": "100%"}),
            html.Div("AUDIENCE", className="report-config-label"),
            dcc.Dropdown(options=[{"label": "Credit Committee", "value": "cc"}, {"label": "Board Risk Committee", "value": "board"}],
                          value="cc", clearable=False, searchable=False, className="filter-dd", style={"width": "100%"}),
            html.Div("SECTIONS INCLUDED", className="report-config-label"),
            html.Div([build_report_checkbox(s) for s in REPORT_SECTIONS]),
            html.Div(
                [html.Button("Generate Pack", className="report-generate-btn"),
                 html.Button("PDF", className="report-secondary-btn"), html.Button("PPTX", className="report-secondary-btn")],
                className="report-btn-row",
            ),
        ],
        className="report-config-panel",
    )

    doc = html.Div(
        [
            html.Div(
                [html.Div([html.Div(f"{quarter} Portfolio Review — Credit Committee", className="report-doc-title"),
                            html.Div("IPM · Confidential", className="report-doc-sub")]),
                 html.Span("AUTO-DRAFTED", className="report-doc-badge")],
                className="report-doc-header",
            ),
            html.Div(
                [html.Div("1 · Executive Summary", className="report-section-title"),
                 html.Div(f"EAD {dl.fmt_bn(k['total_ead'], 2)} "
                          f"({'+' if (k['ead_qoq_pct'] or 0) >= 0 else ''}{(k['ead_qoq_pct'] or 0):.1f}% QoQ) · "
                          f"NPL {k['npl_ratio']:.1f}% · {k['breaches']} appetite breaches.",
                          className="report-section-body")],
                className="report-section",
            ),
            html.Div(
                [html.Div("2 · Portfolio Movement", className="report-section-title"),
                 html.Div(f"Stage 2 exposure {dl.fmt_bn(k['stage_ead'][2], 2)} · {m['upgrades']} upgrades vs {m['downgrades']} downgrades "
                          f"(net {'+' if m['net_migration'] >= 0 else ''}{m['net_migration']}) over the trailing period"
                          + (f", led by {top_downgrade_sector['sector']}." if top_downgrade_sector else "."),
                          className="report-section-body")],
                className="report-section",
            ),
            html.Div(
                [html.Div("3 · Concentration & Heatmap", className="report-section-title"),
                 html.Div((f"Portfolio HHI {conc['hhi']:.3f} · top-10 obligors {conc['top10_pct']:.1f}% of EAD · "
                           f"tightest sector cap: {top_sector['sector']} at {top_sector['utilisation']:.0f}% utilisation.")
                          if top_sector else "No sector cap data.",
                          className="report-section-body")],
                className="report-section",
            ),
            html.Div(
                [html.Div("4 · Stress & ECL", className="report-section-title"),
                 html.Div(f"Adverse scenario (+300bps / -25% CRE) lifts ECL to {dl.fmt_mn(stress['stressed_ecl'])} "
                          f"({'+' if stress['ecl_delta'] >= 0 else ''}{dl.fmt_mn(stress['ecl_delta'])}), "
                          f"CET1 {stress['cet1_bps_impact']:.0f}bps, {stress['covenant_breach_count']} projected covenant breaches.",
                          className="report-section-body")],
                className="report-section",
            ),
            html.Div(
                [html.Div("AI COMMENTARY", style={"fontSize": "11px", "fontWeight": "800", "color": "var(--teal)",
                                                     "marginBottom": "8px", "letterSpacing": "0.5px"}),
                 html.Div(
                     (f"This quarter's risk picture is dominated by {top_sector['sector']} concentration and "
                      if top_sector else "This quarter's risk picture is dominated by sector concentration and ")
                     + (f"{top_downgrade_sector['sector']} rating migration; " if top_downgrade_sector else "rating migration; ")
                     + f"management actions should track against the {k['breaches']} live appetite breaches.",
                     style={"fontSize": "12.5px", "color": "#d4dee8", "lineHeight": "1.6"})],
                style={"background": "var(--navy-900)", "borderRadius": "var(--radius-md)", "padding": "14px 16px"},
            ),
        ],
        className="report-doc",
    )
    preview_panel = html.Div([html.Div("LIVE PREVIEW", className="report-preview-header"), doc], className="report-preview-panel")

    return [
        html.Div(
            [html.Div(config_panel), html.Div(preview_panel)],
            className="split-grid", style={"gridTemplateColumns": "340px 1fr"},
        ),
    ]


SCHEDULED_REPORTS = [
    {"name": "Weekly Risk Digest", "cadence": "Every Monday 07:00", "audience": "CRO + Sector Heads", "next_run": "Next Monday"},
    {"name": "Monthly Board Pack", "cadence": "1st business day", "audience": "Board Risk Committee", "next_run": "1st of next month"},
    {"name": "Quarterly Credit Committee Pack", "cadence": "Quarter-end + 5 business days", "audience": "Credit Committee", "next_run": "Next quarter-end + 5bd"},
]


def build_reports_schedules_body(quarter=None):
    rows = [html.Tr([html.Td(r["name"], className="metric-name"), html.Td(r["cadence"]), html.Td(r["audience"]), html.Td(r["next_run"])])
            for r in SCHEDULED_REPORTS]
    table = html.Table([html.Thead(html.Tr([html.Th("Report"), html.Th("Cadence"), html.Th("Audience"), html.Th("Next Run")])),
                          html.Tbody(rows)], className="borrower-table signals-table")
    return [html.Div([html.Div([html.Span("SCHEDULED REPORTS", className="table-title")], className="table-card-header"), table],
                       className="simple-table-card")]


def build_reports_archive_body(quarter=None):
    quarter = quarter or dl.DEFAULT_QUARTER
    idx = dl.QUARTER_SHEETS.index(quarter)
    past = dl.QUARTER_SHEETS[max(0, idx - 3): idx + 1][::-1]
    rows = []
    for q in past:
        k = dl.compute_kpis(q)
        rows.append(html.Tr([
            html.Td(f"{q} Portfolio Review — Credit Committee", className="metric-name"),
            html.Td(dl.fmt_bn(k["total_ead"], 2), className="num"), html.Td(f"{k['npl_ratio']:.1f}%", className="num"),
            html.Td(str(k["breaches"]), className="num"), html.Td("Generated"),
        ]))
    table = html.Table(
        [html.Thead(html.Tr([html.Th("Report"), html.Th("EAD", className="num"), html.Th("NPL", className="num"),
                              html.Th("Breaches", className="num"), html.Th("Status")])),
         html.Tbody(rows)],
        className="borrower-table signals-table",
    )
    return [html.Div([html.Div([html.Span("REPORT ARCHIVE", className="table-title")], className="table-card-header"), table],
                       className="simple-table-card")]


# ============================================================ generic section shell

def build_section_subnav(section_key, active_tab):
    tabs = SECTION_TABS[section_key]
    subnav_items = [
        html.Div(tab, id={"type": "sec-subnav", "section": section_key, "tab": tab}, n_clicks=0,
                  className="subnav-item active" if tab == active_tab else "subnav-item")
        for tab in tabs
    ]
    return html.Div(
        [
            html.Div([icon_grid(), html.Span(SECTION_BREADCRUMB[section_key], className="crumb-icon"),
                       html.Span("›", className="crumb-sep"), html.Span(active_tab, className="crumb-current")],
                       className="ipm-breadcrumb"),
            html.Div(subnav_items, className="subnav"),
        ],
        className="breadcrumb-row",
    )


def build_section_tab_body(section_key, tab, stress_params=None, recent_questions=None):
    quarter = dl.DEFAULT_QUARTER
    if section_key == "watchlist":
        if tab == "Board":
            return build_watchlist_tab_board(quarter)
        if tab == "Actions":
            return build_watchlist_tab_actions(quarter)
    if section_key == "stress":
        if tab == "Scenario Lab":
            return build_scenario_lab_body(quarter, stress_params, recent_questions)
        if tab == "Results":
            p = stress_params or {}
            result = dl.compute_stress_scenario(quarter, p.get("rate_shock_bps", 0), p.get("cre_price_shock_pct", 0))
            return build_stress_results_body_from_result(result)
        if tab == "Reverse Stress":
            return build_reverse_stress_body(quarter)
    if section_key == "macro":
        if tab == "Outlook":
            return macro_view.build_macro_outlook_tab()
        if tab == "Sector Risk":
            return macro_view.build_macro_sector_tab()
        if tab == "Portfolio Health":
            return macro_view.build_macro_health_tab()
    if section_key == "brf":
        if tab == "Overview":
            return brf_view.build_brf_overview_tab()
        if tab == "Asset Quality":
            return brf_view.build_brf_asset_quality_tab()
        if tab == "Economic Activity":
            return brf_view.build_brf_activity_tab()
        if tab == "Large Exposures":
            return brf_view.build_brf_large_exp_tab()
        if tab == "Calendar":
            return brf_view.build_brf_calendar_body()
    if section_key == "raroc":
        if tab == "Post-Deal RAROC":
            return raroc_view.build_post_deal_raroc_tab()
        if tab == "Deal Explorer":
            return raroc2_view.build_deal_explorer_tab()
        if tab == "Deal Detail":
            return raroc2_view.build_deal_detail_tab()
        if tab == "Earnings & EVA":
            return raroc2_view.build_earnings_tab()
        if tab == "Methodology":
            return raroc2_view.build_methodology_tab()
    if section_key == "esg":
        builder = {
            "Results": esg_view.build_results_tab,
            "Drill-down": esg_view.build_drilldown_tab,
            "Inputs": esg_view.build_inputs_tab,
            "Calibration": esg_view.build_calibration_tab,
            "Sensitivity": esg_view.build_sensitivity_tab,
            "Quality Checks": esg_view.build_checks_tab,
            "Runs": esg_view.build_runs_tab,
            "Report": esg_view.build_report_tab,
        }.get(tab)
        if builder:
            return builder()
    if section_key == "reports":
        if tab == "Review Pack":
            return build_review_pack_body(quarter)
        if tab == "Schedules":
            return build_reports_schedules_body(quarter)
        if tab == "Archive":
            return build_reports_archive_body(quarter)
    return [html.Div("Not implemented.", className="placeholder-panel")]


def build_section_page(section_key):
    active_tab = SECTION_TABS[section_key][0]
    return html.Div(
        [
            build_page_header(SECTION_TITLES[section_key]),
            build_section_subnav(section_key, active_tab),
            html.Div(build_section_tab_body(section_key, active_tab), id={"type": "sec-body", "section": section_key}),
        ],
        className="signals-dashboard",
    )


# -------------------------------------------------------------------------- modal

def modal_stat(label: str, value: str) -> html.Div:
    return html.Div(
        [html.Div(label, className="modal-stat-label"), html.Div(value, className="modal-stat-value")],
        className="modal-stat",
    )


def build_modal_header(detail: dict) -> html.Div:
    sev = detail.get("Severity", "GREEN")
    sev_cls = {"RED": "sev-red", "AMBER": "sev-amber"}.get(sev, "sev-green")
    return html.Div(
        [
            html.Div(
                [
                    html.H4(detail.get("Borrower", ""), className="modal-borrower-name"),
                    html.Div(
                        f"{detail.get('Sector', '')} · {detail.get('Country', '')}, {detail.get('Region', '')} "
                        f"· {detail.get('Product Type', '')} · Owner: {detail.get('Owner / Analyst', '')}",
                        className="modal-borrower-meta",
                    ),
                ]
            ),
            html.Div(
                [
                    html.Span(sev, className=f"sev-pill {sev_cls}"),
                    html.Span("×", id="modal-close-btn", className="modal-close-x", n_clicks=0),
                ],
                style={"display": "flex", "alignItems": "center", "gap": "16px"},
            ),
        ],
        className="modal-header-custom",
    )


def build_modal_children(detail: dict) -> list:
    stage = detail.get("IFRS 9 Stage")
    sev = detail.get("Severity", "GREEN")

    stats = [
        ("EAD (CCF-Adj.)", dl.fmt_mn(detail.get("CCF-Adjusted EAD (USD mn)"))),
        ("Limit", dl.fmt_mn(detail.get("Limit (USD mn)"))),
        ("Utilisation", dl.fmt_pct(detail.get("Utilisation (%)", 0) * 100)),
        ("Risk Rating", detail.get("Risk Rating", "—")),
        ("IFRS 9 Stage", f"Stage {stage}"),
        ("RAROC", dl.fmt_pct(detail.get("RAROC (%)"))),
        ("DSCR", f"{detail.get('DSCR (x)', 0):.2f}x"),
        ("Covenant Headroom", dl.fmt_pct(detail.get("Covenant Headroom (%)"), 0)),
    ]

    # LGD is stored as a 0-1 fraction (unlike PD, which is already in percentage points) -
    # confirmed via Model ECL = (PD12 / 100) x LGD x EAD, so it needs x100 for display.
    risk_stats = [
        ("PD (12m)", dl.fmt_pct(detail.get("PD 12-Month (%)"), 2)),
        ("LGD", dl.fmt_pct(detail.get("LGD (%)", 0) * 100, 1)),
        ("Total ECL", f"${detail.get('Total ECL (USD mn)', 0):,.2f}m"),
        ("Downgrade Prob.", f"{detail.get('Downgrade Prob. (%)', 0)}%"),
        ("Rollovers", str(detail.get("Rollover Count", 0))),
        ("News Sentiment", f"{detail.get('News Sentiment', 0):+.2f}"),
    ]

    body = html.Div(
        [
            html.Div([modal_stat(lbl, val) for lbl, val in stats], className="modal-grid"),
            html.Div("AI Early-Warning Signal", className="modal-section-title"),
            html.Div(
                [
                    html.Div(detail.get("Trigger", "No active trigger."), className="modal-trigger-text"),
                    html.Div(f"→ {detail.get('Recommended Action', '')}", className="modal-action-text"),
                ],
                className="modal-trigger-box " + {"RED": "is-red", "AMBER": "is-amber"}.get(sev, "is-green"),
            ),
            html.Div("Credit Risk Detail", className="modal-section-title"),
            html.Div(
                [modal_stat(lbl, val) for lbl, val in risk_stats],
                className="modal-grid",
                style={"gridTemplateColumns": "repeat(3, 1fr)", "marginBottom": "16px"},
            ),
            dcc.Link(
                "View full 360 profile →",
                href=f"/borrowers?customer={detail.get('Customer ID', '')}",
                className="modal-action-text",
                style={"fontSize": "13.5px"},
            ),
        ],
        className="modal-body-custom",
    )

    return [build_modal_header(detail), body]


# ------------------------------------------------------------------- Cockpit page

def build_overview_content():
    """The Overview body. The AI panel used to sit in a right rail here; it now
    lives in the global Ask AI drawer, so the content spans the full width."""
    q, seg, sec, reg, rat = dl.DEFAULT_QUARTER, "All", "All", "All", "All"
    return [
        build_filters_row(),
        html.Div(
            [
                html.Div(build_kpi_cards(q, seg, sec, reg, rat), className="kpi-grid", id="kpi-grid"),
                html.Div(build_charts_row(q, seg, sec, reg, rat), className="charts-grid", id="charts-grid"),
                build_table_card(q, seg, sec, reg, rat, DEFAULT_SORT),
            ],
            className="main-col",
        ),
    ]


def build_cockpit_page():
    """The cockpit lands on the Health Index drill-down. Overview is kept mounted
    (hidden) rather than rebuilt on every tab switch, because it carries the
    filter-driven grids that other callbacks target by id."""
    return [
        build_page_header("Executive Portfolio Risk Cockpit"),
        build_cockpit_breadcrumb_subnav(),
        html.Div(build_overview_content(), id="overview-wrapper",
                 style={"display": "none"}),
        html.Div(cockpit_view.build_health_shell(), id="placeholder-wrapper",
                 style={"display": "block"}),
    ]


# --------------------------------------------------------------- Borrower 360 page

B360_SUBNAV_TABS = ["Borrower List", "Borrower 360", "Covenants"]
B360_MODULE_DESCRIPTIONS = {
    "Borrower List": "Full searchable obligor list with exposure, rating, stage and trend - same grid as the Cockpit table, scoped to all 389 borrowers.",
    "Covenants": "Covenant-by-covenant headroom, test dates and breach history across the book.",
}


BLIST_SEV_DOT = {"RED": "red", "AMBER": "amber", "GREEN": "green"}


def build_borrower_list_body(quarter=None, search="", sector="All", segment="All"):
    quarter = quarter or dl.DEFAULT_QUARTER
    data = dl.compute_borrower_list(quarter, search=search, sector=sector, segment=segment)
    if not data["rows"]:
        table = html.Div("No obligors match the current search / filters.", className="placeholder-panel")
    else:
        body_rows = [
            html.Tr(
                [
                    html.Td(r["borrower"], className="borrower-name"),
                    html.Td(r["customer_id"]),
                    html.Td(r["sector"]),
                    html.Td(r["region"]),
                    html.Td(str(r["accounts"]), className="num"),
                    html.Td(dl.fmt_bn(r["ead"], 2), className="num borrower-ead"),
                    html.Td(html.Span(r["rating"], className="rating-chip")),
                    html.Td(html.Span(str(r["stage"]), className=f"stage-badge stage-{r['stage']}"),
                            className="center"),
                    html.Td(html.Span(className=f"kpi-dot {BLIST_SEV_DOT.get(r['severity'], 'green')}"),
                            className="center"),
                    html.Td(html.Span([TREND_ARROW.get(r["trend"], ""), " ", r["trend"]],
                                      className=f"trend-tag {TREND_CLASS.get(r['trend'], '')}")),
                ],
                id={"type": "borrower-row", "index": r["account_id"]},
                n_clicks=0,
            )
            for r in data["rows"]
        ]
        table = html.Table(
            [html.Thead(html.Tr([html.Th("Borrower"), html.Th("Customer ID"), html.Th("Sector"),
                                 html.Th("Region"), html.Th("Facilities", className="num"),
                                 html.Th("EAD", className="num"), html.Th("Rating"), html.Th("Stage"),
                                 html.Th("Sev"), html.Th("Trend")])),
             html.Tbody(body_rows)],
            className="borrower-table signals-table",
        )
    shown = len(data["rows"])
    summary = f"{shown} of {data['total']} obligors · {dl.fmt_bn(data['total_ead'], 2)} filtered EAD"
    if data["total"] > shown:
        summary += " · top names by exposure — refine the search to narrow"
    return [
        html.Div(
            [html.Div([html.Span("FULL OBLIGOR REGISTER", className="table-title"),
                       html.Span(summary, className="table-hint")], className="table-card-header"),
             html.Div(table)],
            className="table-card",
        ),
    ]


def build_borrower_list_dashboard():
    return html.Div(
        [
            build_page_header("Borrower List — Full Obligor Register"),
            html.Div(
                [
                    html.Span("SEARCH", className="filters-label"),
                    dcc.Input(id="blist-search", type="text", placeholder="Borrower name or Customer ID...",
                              debounce=True, autoComplete="off", className="blist-search"),
                    dcc.Dropdown(id="blist-sector", options=dl.SECTOR_OPTIONS, value="All",
                                 clearable=False, searchable=False, className="filter-dd"),
                    dcc.Dropdown(id="blist-segment", options=dl.SEGMENT_OPTIONS, value="All",
                                 clearable=False, searchable=False, className="filter-dd narrow"),
                    dcc.Dropdown(id="blist-quarter", options=dl.QUARTER_OPTIONS, value=dl.DEFAULT_QUARTER,
                                 clearable=False, searchable=False, className="filter-dd"),
                ],
                className="filters-row",
            ),
            html.Div(build_borrower_list_body(), id="blist-body"),
        ],
        className="signals-dashboard",
    )


def build_b360_breadcrumb_subnav(borrower_name: str):
    subnav_items = [
        html.Div(
            tab,
            id={"type": "b360-subnav", "tab": tab},
            n_clicks=0,
            className="subnav-item active" if tab == "Borrower 360" else "subnav-item",
        )
        for tab in B360_SUBNAV_TABS
    ]
    return html.Div(
        [
            html.Div(
                [
                    icon_grid(),
                    html.Span("Borrowers", className="crumb-icon"),
                    html.Span("›", className="crumb-sep"),
                    html.Span("Borrower 360", className="crumb-current"),
                    html.Span("·", className="crumb-sep"),
                    html.Span(borrower_name, className="crumb-current", id="b360-breadcrumb-name"),
                ],
                className="ipm-breadcrumb",
            ),
            html.Div(subnav_items, className="subnav"),
        ],
        className="breadcrumb-row",
    )


def build_borrower_header(customer_id, quarter):
    profile = dl.get_borrower_profile(customer_id, quarter)
    if profile is None:
        return html.Div("No data available for this borrower at this snapshot.", className="placeholder-panel")

    words = [w for w in profile["borrower"].replace("-", " ").split() if w]
    initials = "".join(w[0] for w in words[:2]).upper()

    badges = []
    if profile["watchlist"] == "Yes":
        badges.append(html.Span([html.Span(className="pb-dot"), "ON WATCHLIST"], className="pill-badge amber"))

    rating, prev_rating = profile["risk_rating"], profile["prev_risk_rating"]
    idx_now = dl.NOTCH_INDEX.get(rating)
    idx_prev = dl.NOTCH_INDEX.get(prev_rating)
    if idx_now is not None and idx_prev is not None and idx_now != idx_prev:
        downgraded = idx_now > idx_prev
        arrow, rating_cls = ("▼", "red") if downgraded else ("▲", "green")
    else:
        arrow, rating_cls = "—", "gray"
    badges.append(html.Span([f"RATING: {rating}", arrow], className=f"pill-badge {rating_cls}"))

    return html.Div(
        [
            html.Div(
                [
                    html.Div(initials, className="avatar-circle-lg"),
                    html.Div(
                        [
                            html.H3(profile["borrower"], className="b360-name"),
                            html.Div(
                                f"ID: {customer_id} · {profile['sector']} · {profile['region']} · "
                                f"RM: {profile['owner']}",
                                className="b360-meta",
                            ),
                        ]
                    ),
                ],
                className="b360-header-left",
            ),
            html.Div(badges, className="b360-badges"),
        ],
        className="b360-header-card",
    )


def build_b360_kpi_row(customer_id, quarter):
    profile = dl.get_borrower_profile(customer_id, quarter)
    if profile is None:
        return []
    return [
        kpi_card("EAD", dl.fmt_bn(profile["total_ead"], 2), "blue", html.Div()),
        kpi_card("PD (12M)", dl.fmt_pct(profile["pd12"], 2), "amber", html.Div()),
        kpi_card("LGD", dl.fmt_pct(profile["lgd_pct"], 0), "purple", html.Div()),
    ]


RATIO_TREND_CLASS = {"Worse": "trend-down", "Better": "trend-up", "Stable": "trend-stable"}


def build_ratios_table(customer_id):
    ratios = dl.compute_borrower_ratios(customer_id)
    rows = []
    for r in ratios:
        fy24, fy25 = r["fy24"], r["fy25"]
        if fy24 is None or fy25 is None:
            arrow, fy24_s, fy25_s = "", "—", "—"
        else:
            arrow = "▲" if fy25 > fy24 else ("▼" if fy25 < fy24 else "●")
            fy24_s, fy25_s = f"{fy24:.2f}", f"{fy25:.2f}"
        rows.append(
            html.Tr(
                [
                    html.Td(r["metric"], className="metric-name"),
                    html.Td(fy24_s, className="num"),
                    html.Td(fy25_s, className="num"),
                    html.Td(html.Span([arrow, " ", r["trend"]],
                                       className=f"trend-tag {RATIO_TREND_CLASS.get(r['trend'], '')}")),
                ]
            )
        )
    table = html.Table(
        [
            html.Thead(html.Tr([html.Th("Metric"), html.Th("FY24", className="num"),
                                 html.Th("FY25", className="num"), html.Th("Trend")])),
            html.Tbody(rows),
        ],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot blue"), "KEY FINANCIAL RATIOS"], className="dark-table-title"),
         table],
        className="dark-table-card",
    )


def build_rating_table(customer_id, quarter):
    r = dl.compute_rating_reconciliation(customer_id, quarter)
    internal_asof = r["internal_asof"].strftime("%b-%y") if r["internal_asof"] is not None else "—"
    external_asof = r["external_asof"].strftime("%b-%y") if r["external_asof"] is not None else "—"
    gap_text = f"{abs(r['notch_gap'])}-notch gap" if r["notch_gap"] != 0 else "Aligned"

    rows = [
        html.Tr([html.Td("Internal (model)", className="metric-name"),
                 html.Td(r["internal_rating"], className="num"), html.Td(internal_asof)]),
        html.Tr([html.Td("S&P (external)", className="metric-name"),
                 html.Td(r["external_rating"], className="num"), html.Td(external_asof)]),
        html.Tr(
            [
                html.Td("Reconciliation", className="metric-name"),
                html.Td(html.Span(gap_text, className=f"gap-pill {'' if r['flagged'] else 'is-aligned'}"),
                        className="num"),
                html.Td("flagged" if r["flagged"] else "ok"),
            ],
            className="is-flagged" if r["flagged"] else None,
        ),
    ]
    table = html.Table(
        [
            html.Thead(html.Tr([html.Th("Source"), html.Th("Rating", className="num"), html.Th("As of")])),
            html.Tbody(rows),
        ],
        className="dark-mini-table",
    )
    return html.Div(
        [html.Div([html.Span(className="kpi-dot purple"), "INTERNAL VS EXTERNAL RATING"],
                   className="dark-table-title"), table],
        className="dark-table-card",
    )


def build_metric_cards(customer_id, quarter):
    cov = dl.compute_covenant_projection(customer_id, quarter)
    coll = dl.compute_collateral_coverage(customer_id, quarter)

    cov_val = cov["current"]
    if cov_val is not None and cov_val < 10:
        cov_value_cls, cov_sub_cls = "is-red", "is-red"
    elif cov_val is not None and cov_val < 20:
        cov_value_cls, cov_sub_cls = "is-amber", "is-amber"
    else:
        cov_value_cls, cov_sub_cls = "", "is-muted"
    cov_sub = f"Likely breach: {cov['likely_breach']}" if cov["likely_breach"] else "No breach currently projected"

    coll_val = coll["coverage"]
    coll_value_cls = "is-amber" if coll_val is not None and coll_val < 1.0 else ""
    stale = coll["months_stale"]
    coll_sub_cls = "is-amber" if stale is not None and stale > 12 else "is-muted"
    coll_sub = f"Valuation {stale} months stale" if stale is not None else "No valuation on file"

    return [
        html.Div(
            [
                html.Div("COVENANT HEADROOM", className="metric-card-label"),
                html.Div(dl.fmt_pct(cov_val, 1) if cov_val is not None else "—",
                          className=f"metric-card-value {cov_value_cls}"),
                html.Div(cov_sub, className=f"metric-card-sub {cov_sub_cls}"),
            ],
            className="metric-card",
        ),
        html.Div(
            [
                html.Div("COLLATERAL COVERAGE", className="metric-card-label"),
                html.Div(f"{coll_val:.2f}x" if coll_val is not None else "—",
                          className=f"metric-card-value {coll_value_cls}"),
                html.Div(coll_sub, className=f"metric-card-sub {coll_sub_cls}"),
            ],
            className="metric-card",
        ),
    ]


def build_pd_ecl_chart(customer_id, quarter):
    trend = dl.compute_borrower_trend(customer_id, quarter, n_quarters=4)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[t["label"] for t in trend], y=[t["pd12"] for t in trend], name="PD %",
        mode="lines+markers", line=dict(color="#f0973e", width=3), marker=dict(size=6, color="#f0973e"),
        yaxis="y1", hovertemplate="<b>%{x}</b><br>PD: %{y:.2f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[t["label"] for t in trend], y=[t["total_ecl"] for t in trend], name="ECL $m",
        mode="lines+markers", line=dict(color="#e5484d", width=3), marker=dict(size=6, color="#e5484d"),
        yaxis="y2", hovertemplate="<b>%{x}</b><br>ECL: $%{y:.2f}m<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(t=10, b=10, l=38, r=38),
        height=170,
        showlegend=False,
        xaxis=dict(showgrid=False, tickfont=dict(size=10.5, color="#6c7a8c", family="Inter")),
        yaxis=dict(showgrid=True, gridcolor="#eef1f6", zeroline=False,
                   tickfont=dict(size=10, color="#c4690f", family="Inter")),
        yaxis2=dict(overlaying="y", side="right", showgrid=False,
                    tickfont=dict(size=10, color="#c0292e", family="Inter")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="#0b2436", font_color="#fff", font_size=12, font_family="Inter"),
    )
    legend = html.Div(
        [
            html.Div([html.Span(className="legend-swatch", style={"background": "#f0973e"}), "PD %"],
                      style={"display": "flex", "alignItems": "center", "gap": "7px", "fontSize": "12px",
                             "color": "var(--text-mid)", "fontWeight": "600"}),
            html.Div([html.Span(className="legend-swatch", style={"background": "#e5484d"}), "ECL $m"],
                      style={"display": "flex", "alignItems": "center", "gap": "7px", "fontSize": "12px",
                             "color": "var(--text-mid)", "fontWeight": "600"}),
        ],
        style={"display": "flex", "justifyContent": "center", "gap": "20px", "marginTop": "4px"},
    )
    return html.Div(
        [
            html.Div("PD / ECL MOVEMENT (4Q)", className="chart-title"),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            legend,
        ],
        className="chart-card",
    )


def borrower_limit_labels(customer_id, quarter=None):
    """The appetite lines this borrower actually sits inside.

    The limit book is portfolio-level, so opening it from a borrower page is only
    useful if you can see which lines that borrower contributes to — their sector
    cap, their geography, and the single-name line when they are the one holding
    it."""
    quarter = quarter or dl.DEFAULT_QUARTER
    profile = dl.get_borrower_profile(customer_id, quarter)
    if not profile:
        return set()
    labels = {f"{profile['sector']} (sector)", f"{profile['region']} (geography)"}
    labels.add(f"Single-name ({profile['borrower']})")
    return labels


def build_b360_limits_modal_body(customer_id, quarter=None, view="Utilisation"):
    quarter = quarter or dl.DEFAULT_QUARTER
    profile = dl.get_borrower_profile(customer_id, quarter)
    name = profile["borrower"] if profile else customer_id
    tabs = html.Div(
        [
            html.Div(v, id={"type": "b360-limits-tab", "view": v}, n_clicks=0,
                     className="subnav-item" + (" active" if v == view else ""))
            for v in LIMITS_VIEWS
        ],
        className="subnav",
    )
    return [
        html.Div(
            [
                html.Div(
                    [
                        html.H4("Limits, Risk Appetite & Breaches", className="modal-borrower-name"),
                        html.Div(f"Portfolio appetite lines · highlighting those {name} sits in",
                                 className="modal-borrower-meta"),
                    ]
                ),
                html.Span("×", id="b360-limits-close", className="modal-close-x", n_clicks=0),
            ],
            className="modal-header-custom",
        ),
        html.Div(
            [tabs, html.Div(
                build_limits_body(quarter, view=view,
                                  highlight_labels=borrower_limit_labels(customer_id, quarter)),
                id="b360-limits-view", style={"marginTop": "16px"},
            )],
            className="modal-body-custom",
        ),
    ]


def build_b360_content(customer_id, quarter):
    return [
        html.Div(
            [
                html.Span("BORROWER", className="filters-label"),
                dcc.Dropdown(
                    id="b360-customer-select", options=dl.CUSTOMER_OPTIONS, value=customer_id,
                    clearable=False, searchable=True, className="filter-dd",
                ),
                html.Span("CUSTOMER ID", className="filters-label"),
                dcc.Dropdown(
                    id="b360-customerid-select", options=dl.CUSTOMER_ID_OPTIONS, value=customer_id,
                    clearable=False, searchable=True, className="filter-dd narrow",
                ),
                html.Span("ACCOUNT ID", className="filters-label"),
                dcc.Dropdown(
                    id="b360-account-select", options=dl.account_options_for_customer(customer_id, quarter),
                    value=None, placeholder="View facility...",
                    clearable=True, searchable=True, className="filter-dd narrow",
                ),
                # Limits used to be its own top-level section. It lives here now:
                # an appetite line only becomes actionable next to a name.
                html.Button(
                    [html.Span("▤", className="b360-action-icon"), "Limits & Appetite"],
                    id="b360-limits-btn", n_clicks=0, className="b360-action-btn",
                    title="Approved limits, utilisation and breaches",
                ),
            ],
            className="b360-selector",
        ),
        html.Div(build_borrower_header(customer_id, quarter), id="b360-header"),
        html.Div(
            [
                html.Div(
                    [
                        html.Div(build_b360_kpi_row(customer_id, quarter), className="b360-kpi-row",
                                  id="b360-kpi-row"),
                        html.Div(build_ratios_table(customer_id), id="b360-ratios-table"),
                        html.Div(build_metric_cards(customer_id, quarter), className="metric-card-row",
                                  id="b360-metric-cards"),
                    ],
                    className="b360-col",
                ),
                html.Div(
                    [
                        html.Div(build_rating_table(customer_id, quarter), id="b360-rating-table"),
                        html.Div(build_pd_ecl_chart(customer_id, quarter), id="b360-pd-ecl-chart"),
                    ],
                    className="b360-col",
                ),
            ],
            className="b360-grid",
        ),
    ]


def build_borrowers_page(customer_id=None):
    customer_id = customer_id if customer_id in dl.SUPP_DF.index else dl.DEFAULT_CUSTOMER
    quarter = dl.DEFAULT_QUARTER
    profile = dl.get_borrower_profile(customer_id, quarter)
    borrower_name = profile["borrower"] if profile else customer_id
    return [
        build_page_header("Borrower 360 Monitoring View"),
        build_b360_breadcrumb_subnav(borrower_name),
        html.Div(build_b360_content(customer_id, quarter), id="b360-wrapper"),
        html.Div(id="b360-placeholder-wrapper", style={"display": "none"}),
    ]


# --------------------------------------------------------------- global AI drawer

# One chat, reachable from every screen. The panel itself is unchanged — it is
# simply mounted in a slide-in drawer instead of being embedded in two page
# bodies. The conversation context still follows the route: Borrower 360 gets the
# borrower-grounded prompt, everything else gets the portfolio one, which is why
# the drawer body is rebuilt by the router rather than built once here.

AI_DRAWER_PAGE_KEY = {"/borrowers": "b360"}
AI_DRAWER_DEFAULT_KEY = "cockpit"


def ai_drawer_page_key(pathname: str | None) -> str:
    return AI_DRAWER_PAGE_KEY.get(pathname or "", AI_DRAWER_DEFAULT_KEY)


def build_ai_launcher():
    """The floating Ask AI button plus the drawer it opens. Lives outside
    page-content so it is present on every route, including Data Hub."""
    return html.Div(
        [
            html.Button(
                [html.Span("✦", className="ai-fab-icon"), html.Span("Ask AI", className="ai-fab-label")],
                id="ai-fab", n_clicks=0, className="ai-fab", title="Ask AI about this portfolio",
            ),
            html.Div(id="ai-drawer-scrim", n_clicks=0, className="ai-drawer-scrim"),
            html.Div(
                html.Div(id="ai-drawer-body", className="signals-panel ai-chat-panel ai-drawer-panel"),
                id="ai-drawer", className="ai-drawer",
            ),
        ],
        id="ai-launcher",
    )


# ------------------------------------------------------------------------ layout

def serve_layout():
    return html.Div(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="sort-state", data=DEFAULT_SORT),
            dcc.Store(id="signals-sort-state", data=SIGNALS_DEFAULT_SORT),
            dcc.Store(id="current-quarter-store", data=dl.DEFAULT_QUARTER),
            dcc.Interval(id="live-interval", interval=15_000, n_intervals=0),
            dcc.Download(id="brf-download"),
            dcc.Download(id="raroc-download"),
            dcc.Download(id="esg-download"),
            # Chat Stores live here, outside page-content, so conversations survive
            # page navigation (page-content gets torn down and rebuilt on every
            # route change, but this part of the tree never does). One set per
            # screen: each screen holds its own conversation, seeded with that
            # screen's system prompt, so questions asked on Limits are answered in
            # the context of Limits and do not bleed into the Watchlist thread.
            *[
                store
                for screen in ai_context.SCREENS
                for store in (
                    dcc.Store(
                        id={"type": "chat-history", "page": screen},
                        data=ai_context.seed_history(
                            screen,
                            dl.DEFAULT_CUSTOMER if screen == ai_context.B360 else None,
                        ),
                    ),
                    dcc.Store(id={"type": "chat-model", "page": screen}, data=DEFAULT_MODEL),
                    dcc.Store(id={"type": "chat-pending", "page": screen}, data=None),
                )
            ],
            dcc.Store(id="b360-chat-customer-store", data=dl.DEFAULT_CUSTOMER),
            dcc.Store(id="stress-history", data=[]),
            dcc.Store(id="stress-params", data={"rate_shock_bps": 0, "cre_price_shock_pct": 0}),
            # Questions asked in the Scenario Lab, kept in browser storage so they
            # survive a reload and are still there on the next visit — the point of
            # the feature is that the analyst's own working set comes back.
            dcc.Store(id="scenario-recent-q", storage_type="local", data=[]),
            dcc.Store(id="ai-drawer-open", data=False),
            build_navbar(),
            html.Div(id="page-content", className="page-body"),
            build_ai_launcher(),
            dbc.Modal(
                id="borrower-modal",
                is_open=False,
                size="lg",
                centered=True,
                contentClassName="modal-content",
                children=html.Div(id="modal-children"),
            ),
            dbc.Modal(
                id="b360-limits-modal",
                is_open=False,
                size="xl",
                centered=True,
                scrollable=True,
                contentClassName="modal-content",
                children=html.Div(id="b360-limits-modal-children"),
            ),
        ]
    )


app.layout = serve_layout

FILTER_INPUTS = [
    Input("f-quarter", "value"),
    Input("f-segment", "value"),
    Input("f-sector", "value"),
    Input("f-region", "value"),
    Input("f-rating", "value"),
]


# --------------------------------------------------------------------- callbacks

@app.callback(Output("live-updated-text", "children"), Input("live-interval", "n_intervals"))
def tick_clock(_n):
    return f"Last refreshed {datetime.now().strftime('%H:%M:%S')}"


@app.callback(
    Output("f-quarter", "value"),
    Output("f-segment", "value"),
    Output("f-sector", "value"),
    Output("f-region", "value"),
    Output("f-rating", "value"),
    Input("f-reset", "n_clicks"),
    prevent_initial_call=True,
)
def reset_filters(_n):
    return dl.DEFAULT_QUARTER, "All", "All", "All", "All"


@app.callback(Output("kpi-grid", "children"), FILTER_INPUTS)
def update_kpis(quarter, segment, sector, region, rating):
    return build_kpi_cards(quarter, segment, sector, region, rating)


@app.callback(Output("charts-grid", "children"), FILTER_INPUTS)
def update_charts(quarter, segment, sector, region, rating):
    return build_charts_row(quarter, segment, sector, region, rating)


@app.callback(
    Output("sig-severity", "value"),
    Output("sig-segment", "value"),
    Output("sig-quarter", "value"),
    Output("sig-owner", "value"),
    Input("sig-reset", "n_clicks"),
    prevent_initial_call=True,
)
def reset_signals_filters(_n):
    return "All", "All", dl.DEFAULT_QUARTER, "All"


@app.callback(
    Output("signals-sort-state", "data"),
    Input({"type": "sig-sort-th", "col": ALL}, "n_clicks"),
    State("signals-sort-state", "data"),
    prevent_initial_call=True,
)
def toggle_signals_sort(_n_clicks_list, current):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    col = trig["col"]
    current = current or SIGNALS_DEFAULT_SORT
    if current.get("col") == col:
        return {"col": col, "asc": not current.get("asc", False)}
    default_asc = col in ("Borrower", "Sector", "Reason Code", "Owner", "Severity")
    return {"col": col, "asc": default_asc}


@app.callback(
    Output("signals-kpi-row", "children"),
    Output("signals-table-wrap", "children"),
    Input("sig-severity", "value"),
    Input("sig-segment", "value"),
    Input("sig-quarter", "value"),
    Input("sig-owner", "value"),
    Input("signals-sort-state", "data"),
    prevent_initial_call=True,
)
def update_signals_view(severity, segment, quarter, owner, sort_state):
    quarter = quarter or dl.DEFAULT_QUARTER
    return (
        build_signals_kpi_row(quarter, segment, severity, owner),
        build_signals_table(quarter, segment, severity, owner, sort_state),
    )


@app.callback(
    Output("concentration-body", "children"),
    Input("conc-quarter", "value"),
    Input("conc-segment", "value"),
    prevent_initial_call=True,
)
def update_concentration_view(quarter, segment):
    return build_concentration_body(quarter or dl.DEFAULT_QUARTER, segment)


@app.callback(
    Output("migration-body", "children"),
    Input("mig-quarter", "value"),
    Input("mig-period", "value"),
    Input("mig-segment", "value"),
    prevent_initial_call=True,
)
def update_migration_view(quarter, lookback, segment):
    return build_migration_body(quarter or dl.DEFAULT_QUARTER, lookback or 4, segment)


@app.callback(
    Output("ead-body", "children"),
    Input("ead-quarter", "value"),
    Input("ead-segment", "value"),
    prevent_initial_call=True,
)
def update_ead_view(quarter, segment):
    return build_ead_body(quarter or dl.DEFAULT_QUARTER, segment)


@app.callback(
    Output("ifrs9-body", "children"),
    Input("ifrs9-quarter", "value"),
    Input("ifrs9-segment", "value"),
    prevent_initial_call=True,
)
def update_ifrs9_view(quarter, segment):
    return build_ifrs9_body(quarter or dl.DEFAULT_QUARTER, segment)


@app.callback(
    Output("covenants-body", "children"),
    Input("cov-quarter", "value"),
    Input("cov-threshold", "value"),
    prevent_initial_call=True,
)
def update_covenants_view(quarter, threshold):
    return build_covenants_body(quarter or dl.DEFAULT_QUARTER, threshold or 20)


@app.callback(
    Output("sort-state", "data"),
    Input({"type": "sort-th", "col": ALL}, "n_clicks"),
    State("sort-state", "data"),
    prevent_initial_call=True,
)
def toggle_sort(_n_clicks_list, current):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    col = trig["col"]
    current = current or DEFAULT_SORT
    if current.get("col") == col:
        return {"col": col, "asc": not current.get("asc", False)}
    default_asc = col in ("Borrower", "Sector", "Rating", "Trend")
    return {"col": col, "asc": default_asc}


@app.callback(
    Output("borrower-table-wrap", "children"),
    FILTER_INPUTS + [Input("sort-state", "data")],
)
def update_table(quarter, segment, sector, region, rating, sort_state):
    return build_borrower_table(quarter, segment, sector, region, rating, sort_state)


@app.callback(
    Output({"type": "subnav", "tab": ALL}, "className"),
    Output("overview-wrapper", "style"),
    Output("placeholder-wrapper", "style"),
    Output("placeholder-wrapper", "children"),
    Output("cockpit-crumb-current", "children"),
    Input({"type": "subnav", "tab": ALL}, "n_clicks"),
    State({"type": "subnav", "tab": ALL}, "id"),
    State("current-quarter-store", "data"),
    prevent_initial_call=True,
)
def switch_subnav(_n_clicks_list, ids, quarter):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    active_tab = trig["tab"]
    classnames = ["subnav-item active" if d["tab"] == active_tab else "subnav-item" for d in ids]

    if active_tab == "Overview":
        return classnames, {"display": "block"}, {"display": "none"}, [], active_tab

    builders = {
        "Health Index": lambda: cockpit_view.build_health_shell(quarter),
        "Signals": build_signals_dashboard,
        "Concentration": build_concentration_dashboard,
        "Migration": build_migration_dashboard,
        "EAD": build_ead_dashboard,
        "IFRS 9": build_ifrs9_dashboard,
    }
    builder = builders.get(active_tab)
    if builder:
        return classnames, {"display": "none"}, {"display": "block"}, builder(), active_tab

    placeholder = html.Div(
        [
            html.Div(f"{active_tab} module", className="ph-title"),
            html.Div(MODULE_DESCRIPTIONS.get(active_tab, ""), style={"maxWidth": "520px", "margin": "0 auto"}),
            html.Div("This view is on the roadmap — the Overview cockpit is fully live.",
                      style={"marginTop": "10px", "fontSize": "12px", "color": "var(--text-faint)"}),
        ],
        className="placeholder-panel",
    )
    return classnames, {"display": "none"}, {"display": "block"}, placeholder, active_tab


# ------------------------------------------------- cockpit health drill-down

@app.callback(
    Output("cockpit-drill-body", "children"),
    Input({"type": "cockpit-drill", "level": ALL, "sector": ALL}, "n_clicks"),
    State("current-quarter-store", "data"),
    prevent_initial_call=True,
)
def cockpit_drill(_clicks, quarter):
    """One callback drives all three levels: forward links, sector rows and the
    back links are the same component type, distinguished only by their id."""
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    sector = trig.get("sector")
    return cockpit_view.build_drill_body(
        level=int(trig["level"]),
        sector=None if sector == "__all__" else sector,
        quarter=quarter or dl.DEFAULT_QUARTER,
    )


@app.callback(Output("current-quarter-store", "data"), Input("f-quarter", "value"))
def sync_current_quarter(quarter):
    return quarter or dl.DEFAULT_QUARTER


@app.callback(
    Output("borrower-modal", "is_open", allow_duplicate=True),
    Output("modal-children", "children"),
    Input({"type": "borrower-row", "index": ALL}, "n_clicks"),
    State("current-quarter-store", "data"),
    prevent_initial_call=True,
)
def open_borrower_modal(_row_clicks, quarter):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    account_id = trig.get("index")
    detail = dl.get_borrower_detail(account_id, quarter or dl.DEFAULT_QUARTER)
    if detail is None:
        raise PreventUpdate
    return True, build_modal_children(detail)


@app.callback(
    Output("borrower-modal", "is_open", allow_duplicate=True),
    Input("modal-close-btn", "n_clicks"),
    prevent_initial_call=True,
)
def close_borrower_modal(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return False


@app.callback(
    Output("borrower-modal", "is_open", allow_duplicate=True),
    Output("modal-children", "children", allow_duplicate=True),
    Input("b360-account-select", "value"),
    prevent_initial_call=True,
)
def open_account_modal(account_id):
    if not account_id:
        raise PreventUpdate
    detail = dl.get_borrower_detail(account_id, dl.DEFAULT_QUARTER)
    if detail is None:
        raise PreventUpdate
    return True, build_modal_children(detail)


# ------------------------------------------------------------------------ routing

HIDDEN = {"display": "none"}
VISIBLE = {"display": "block"}


@app.callback(
    Output("page-content", "children"),
    Output("ai-drawer-body", "children"),
    Output("ai-launcher", "style"),
    Output({"type": "chat-history", "page": "b360"}, "data", allow_duplicate=True),
    Output({"type": "chat-pending", "page": "b360"}, "data", allow_duplicate=True),
    Output("b360-chat-customer-store", "data"),
    Input("url", "pathname"),
    Input("url", "search"),
    State({"type": "chat-history", "page": ALL}, "data"),
    State({"type": "chat-history", "page": ALL}, "id"),
    State({"type": "chat-model", "page": ALL}, "data"),
    State("b360-chat-customer-store", "data"),
    prevent_initial_call="initial_duplicate",
)
def render_page(pathname, search, histories, history_ids, models, b360_chat_customer):
    """Renders the routed page and re-points the global AI drawer at the chat
    context that matches it, so Ask AI is grounded in whatever the user is
    looking at — and hidden entirely on the screens that have no assistant."""
    by_screen = {i["page"]: h for i, h in zip(history_ids, histories, strict=False)}
    model_by_screen = {i["page"]: m for i, m in zip(history_ids, models, strict=False)}

    def panel(screen, history=None, customer_id=None):
        return build_chat_panel(screen, history if history is not None else by_screen.get(screen),
                                model_by_screen.get(screen, DEFAULT_MODEL), customer_id)

    if pathname == "/borrowers":
        params = parse_qs((search or "").lstrip("?"))
        customer_id = params.get("customer", [None])[0]
        customer_id = customer_id if customer_id in dl.SUPP_DF.index else dl.DEFAULT_CUSTOMER
        # Only reset the chat when we're actually looking at a different
        # borrower than last time - plain navigation back to the same
        # borrower's page should keep the conversation going.
        if customer_id != b360_chat_customer:
            fresh = ai_context.seed_history(ai_context.B360, customer_id)
            return (build_borrowers_page(customer_id), panel(ai_context.B360, fresh, customer_id),
                    VISIBLE, fresh, None, customer_id)
        return (build_borrowers_page(customer_id), panel(ai_context.B360, customer_id=b360_chat_customer),
                VISIBLE, no_update, no_update, no_update)

    if pathname == "/data":
        # The Data Hub is an upload/administration screen, not an analysis one —
        # there is nothing here for the assistant to be grounded in, so it is not
        # offered rather than offered and unhelpful.
        return (data_hub.build_data_hub_page(), no_update, HIDDEN,
                no_update, no_update, no_update)

    section_key = ROUTE_TO_SECTION.get((pathname or "").lstrip("/"))
    if section_key:
        screen = section_key if section_key in ai_context.SCREENS else ai_context.COCKPIT
        return (build_section_page(section_key), panel(screen), VISIBLE,
                no_update, no_update, no_update)

    return (build_cockpit_page(), panel(ai_context.COCKPIT), VISIBLE,
            no_update, no_update, no_update)


@app.callback(
    Output("ai-drawer-open", "data"),
    Output("ai-drawer", "className"),
    Output("ai-drawer-scrim", "className"),
    Output("ai-fab", "className"),
    Input("ai-fab", "n_clicks"),
    Input("ai-drawer-close", "n_clicks"),
    Input("ai-drawer-scrim", "n_clicks"),
    State("ai-drawer-open", "data"),
    prevent_initial_call=True,
)
def toggle_ai_drawer(_fab, _close, _scrim, is_open):
    """The Ask AI button toggles; the close button and the scrim always close."""
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    open_now = (not is_open) if trig == "ai-fab" else False
    return (
        open_now,
        "ai-drawer is-open" if open_now else "ai-drawer",
        "ai-drawer-scrim is-open" if open_now else "ai-drawer-scrim",
        "ai-fab is-hidden" if open_now else "ai-fab",
    )


@app.callback(
    Output("nav-cockpit", "className"),
    Output("nav-borrowers", "className"),
    Output("nav-data", "className"),
    Input("url", "pathname"),
)
def update_nav_active(pathname):
    if pathname == "/borrowers":
        return "ipm-nav-item", "ipm-nav-item active", "ipm-nav-item"
    if pathname == "/data":
        return "ipm-nav-item", "ipm-nav-item", "ipm-nav-item active"
    if (pathname or "").lstrip("/") in ROUTE_TO_SECTION:
        return "ipm-nav-item", "ipm-nav-item", "ipm-nav-item"
    return "ipm-nav-item active", "ipm-nav-item", "ipm-nav-item"


@app.callback(
    Output({"type": "top-nav", "route": ALL}, "className"),
    Input("url", "pathname"),
    State({"type": "top-nav", "route": ALL}, "id"),
)
def update_top_nav_active(pathname, ids):
    return ["ipm-nav-item active" if d["route"] == pathname else "ipm-nav-item" for d in ids]


@app.callback(
    Output({"type": "sec-subnav", "section": MATCH, "tab": ALL}, "className"),
    Output({"type": "sec-body", "section": MATCH}, "children"),
    Input({"type": "sec-subnav", "section": MATCH, "tab": ALL}, "n_clicks"),
    State({"type": "sec-subnav", "section": MATCH, "tab": ALL}, "id"),
    State("stress-params", "data"),
    State("scenario-recent-q", "data"),
    prevent_initial_call=True,
)
def switch_section_subnav(_n_clicks_list, ids, stress_params, recent_questions):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    section_key = trig["section"]
    active_tab = trig["tab"]
    classnames = ["subnav-item active" if d["tab"] == active_tab else "subnav-item" for d in ids]
    return classnames, build_section_tab_body(section_key, active_tab, stress_params, recent_questions)


@app.callback(
    Output("stress-history", "data"),
    Output("stress-params", "data"),
    Output("scenario-input", "value"),
    Output("scenario-recent-q", "data"),
    Input("scenario-send", "n_clicks"),
    Input("scenario-input", "n_submit"),
    Input({"type": "scenario-recall", "text": ALL}, "n_clicks"),
    State("scenario-input", "value"),
    State("stress-history", "data"),
    State("stress-params", "data"),
    State("scenario-recent-q", "data"),
    prevent_initial_call=True,
)
def send_scenario_message(_n, _submit, _recall, text, history, params, recent):
    """Handles both a typed question and an 'ask again' chip, and records the
    question either way — the memory is only useful if it fills itself."""
    trig = ctx.triggered_id
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    if isinstance(trig, dict) and trig.get("type") == "scenario-recall":
        text = trig.get("text", "")

    text = (text or "").strip()
    if not text:
        raise PreventUpdate

    history = list(history or [])
    history.append({"role": "user", "text": text})
    parsed = dl.parse_scenario_text(text)
    params = dict(params or {})
    if parsed["rate_shock_bps"]:
        params["rate_shock_bps"] = params.get("rate_shock_bps", 0) + parsed["rate_shock_bps"]
    if parsed["cre_price_shock_pct"]:
        params["cre_price_shock_pct"] = params.get("cre_price_shock_pct", 0) + parsed["cre_price_shock_pct"]
    if parsed["rate_shock_bps"] or parsed["cre_price_shock_pct"]:
        # A free-text shock is no longer one of the named scenarios.
        params.pop("preset_id", None)

    result = dl.compute_stress_scenario(dl.DEFAULT_QUARTER, params.get("rate_shock_bps", 0), params.get("cre_price_shock_pct", 0))
    if not parsed["recognised"]:
        reply = ("I can model rate shocks (e.g. '+300bps') and price shocks (e.g. '25% fall in real estate'). "
                  "Try describing a shock in those terms, or pick one of the scenarios above.")
        confidence = None
    else:
        reply = (
            f"Propagating through the MEV model → IFRS 9 ECL engine: funding cost impact via PiT PD "
            f"({result['pit_pd_notches']:.1f} notch-equivalent widening), GDP {result['gdp_impact_pct']:.1f}% via rate elasticity, "
            f"CRE prices -{result['cre_price_fall_pct']:.0f}%. Re-computed scenario ECL {dl.fmt_mn(result['stressed_ecl'])} "
            f"({'+' if result['ecl_delta'] >= 0 else ''}{dl.fmt_mn(result['ecl_delta'])}), CET1 {result['cet1_bps_impact']:.0f}bps, "
            f"{result['covenant_breach_count']} borrowers projected to breach covenants."
        )
        confidence = 0.8
    history.append({"role": "ai", "text": reply, "confidence": confidence})
    return history, params, "", stress_lab.record_question(recent, text)


@app.callback(
    Output("stress-history", "data", allow_duplicate=True),
    Output("stress-params", "data", allow_duplicate=True),
    Input({"type": "scenario-preset", "preset": ALL}, "n_clicks"),
    State("stress-history", "data"),
    prevent_initial_call=True,
)
def apply_scenario_preset(_clicks, history):
    """A named scenario SETS the shock rather than adding to it — picking
    'Severe adverse' must mean severe adverse, not severe adverse stacked on
    whatever the previous turns accumulated."""
    trig = ctx.triggered_id
    if not trig or not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    spec = stress_lab.preset(trig["preset"])
    if spec is None:
        raise PreventUpdate

    params = stress_lab.apply_preset(spec["id"])
    result = dl.compute_stress_scenario(dl.DEFAULT_QUARTER, params["rate_shock_bps"],
                                        params["cre_price_shock_pct"])
    history = list(history or [])
    history.append({"role": "user", "text": f"Run scenario: {spec['label']}"})
    if spec["id"] == "base":
        history.append({"role": "ai", "text": "Reset to the reported position — no shock applied.",
                        "confidence": None})
    else:
        history.append({"role": "ai", "text": stress_lab.preset_reply(spec, result), "confidence": 0.9})
    return history, params


@app.callback(
    Output("scenario-presets", "children"),
    Output("scenario-active-shock", "children"),
    Input("stress-params", "data"),
)
def update_scenario_presets(params):
    params = params or {}
    return build_preset_cards(params.get("preset_id")), stress_lab.describe_params(params)


@app.callback(
    Output("scenario-recall-row", "children"),
    Input("scenario-recent-q", "data"),
)
def update_scenario_recall(recent):
    return build_recall_chips(recent)


@app.callback(
    Output("scenario-console", "children"),
    Input("stress-history", "data"),
)
def render_scenario_console_cb(history):
    return render_scenario_console(history)


@app.callback(
    Output("scenario-kpi-side", "children"),
    Input("stress-params", "data"),
)
def update_scenario_kpis(params):
    params = params or {}
    result = dl.compute_stress_scenario(dl.DEFAULT_QUARTER, params.get("rate_shock_bps", 0), params.get("cre_price_shock_pct", 0))
    return build_scenario_kpi_cards(result)


@app.callback(
    Output({"type": "copilot-apply", "index": MATCH}, "children"),
    Output({"type": "copilot-apply", "index": MATCH}, "className"),
    Input({"type": "copilot-apply", "index": MATCH}, "n_clicks"),
    prevent_initial_call=True,
)
def apply_copilot_action(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return "Applied ✓", "copilot-apply-btn is-applied"


@app.callback(
    Output({"type": "b360-subnav", "tab": ALL}, "className"),
    Output("b360-wrapper", "style"),
    Output("b360-placeholder-wrapper", "style"),
    Output("b360-placeholder-wrapper", "children"),
    Input({"type": "b360-subnav", "tab": ALL}, "n_clicks"),
    State({"type": "b360-subnav", "tab": ALL}, "id"),
    prevent_initial_call=True,
)
def switch_b360_subnav(_n_clicks_list, ids):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    active_tab = trig["tab"]
    classnames = ["subnav-item active" if d["tab"] == active_tab else "subnav-item" for d in ids]

    if active_tab == "Borrower 360":
        return classnames, {"display": "block"}, {"display": "none"}, []

    if active_tab == "Borrower List":
        return classnames, {"display": "none"}, {"display": "block"}, build_borrower_list_dashboard()

    if active_tab == "Covenants":
        return classnames, {"display": "none"}, {"display": "block"}, build_covenants_dashboard()

    placeholder = html.Div(
        [
            html.Div(f"{active_tab} module", className="ph-title"),
            html.Div(B360_MODULE_DESCRIPTIONS.get(active_tab, ""), style={"maxWidth": "520px", "margin": "0 auto"}),
            html.Div("This view is on the roadmap — Borrower 360 is fully live.",
                      style={"marginTop": "10px", "fontSize": "12px", "color": "var(--text-faint)"}),
        ],
        className="placeholder-panel",
    )
    return classnames, {"display": "none"}, {"display": "block"}, placeholder


@app.callback(
    Output("b360-header", "children"),
    Output("b360-kpi-row", "children"),
    Output("b360-ratios-table", "children"),
    Output("b360-rating-table", "children"),
    Output("b360-metric-cards", "children"),
    Output("b360-pd-ecl-chart", "children"),
    Output("b360-breadcrumb-name", "children"),
    Output({"type": "chat-history", "page": "b360"}, "data", allow_duplicate=True),
    Output({"type": "chat-messages", "page": "b360"}, "children", allow_duplicate=True),
    Output({"type": "chat-pending", "page": "b360"}, "data", allow_duplicate=True),
    Output("b360-chat-customer-store", "data", allow_duplicate=True),
    Output("b360-customer-select", "value", allow_duplicate=True),
    Output("b360-customerid-select", "value", allow_duplicate=True),
    Output("b360-account-select", "options"),
    Output("b360-account-select", "value"),
    Output("ai-drawer-body", "children", allow_duplicate=True),
    Input("b360-customer-select", "value"),
    Input("b360-customerid-select", "value"),
    State({"type": "chat-model", "page": "b360"}, "data"),
    prevent_initial_call=True,
)
def update_borrower360(name_value, id_value, b360_model):
    trig = ctx.triggered_id
    customer_id = id_value if trig == "b360-customerid-select" else name_value
    if not customer_id:
        raise PreventUpdate
    quarter = dl.DEFAULT_QUARTER
    profile = dl.get_borrower_profile(customer_id, quarter)
    borrower_name = profile["borrower"] if profile else customer_id
    # Re-seed against the newly selected borrower so both the assistant's prompt
    # and the drawer's brief describe the borrower actually on screen.
    fresh_chat = ai_context.seed_history(ai_context.B360, customer_id)
    return (
        build_borrower_header(customer_id, quarter),
        build_b360_kpi_row(customer_id, quarter),
        build_ratios_table(customer_id),
        build_rating_table(customer_id, quarter),
        build_metric_cards(customer_id, quarter),
        build_pd_ecl_chart(customer_id, quarter),
        borrower_name,
        fresh_chat,
        render_chat_bubbles(fresh_chat),
        None,
        customer_id,
        no_update if trig == "b360-customer-select" else customer_id,
        no_update if trig == "b360-customerid-select" else customer_id,
        dl.account_options_for_customer(customer_id, quarter),
        None,
        build_chat_panel(ai_context.B360, fresh_chat, b360_model or DEFAULT_MODEL, customer_id),
    )


@app.callback(
    Output({"type": "chat-model", "page": MATCH}, "data"),
    Output({"type": "chat-history", "page": MATCH}, "data", allow_duplicate=True),
    Output({"type": "chat-messages", "page": MATCH}, "children", allow_duplicate=True),
    Output({"type": "chat-subtitle", "page": MATCH}, "children"),
    Input({"type": "chat-model-select", "page": MATCH}, "value"),
    State({"type": "chat-history", "page": MATCH}, "data"),
    prevent_initial_call=True,
)
def switch_chat_model(model_key, history):
    if not model_key:
        raise PreventUpdate
    # Switching models starts a fresh conversation - the two providers' tool-call
    # message formats aren't guaranteed cross-compatible (e.g. Anthropic's tool_use/
    # tool_result block linkage vs Ollama's simpler shape), so reuse just the system prompt.
    system = next((m for m in (history or []) if m.get("role") == "system"), None)
    fresh = [system] if system else []
    return model_key, fresh, render_chat_bubbles(fresh), MODEL_OPTIONS[model_key]["subtitle"]


@app.callback(
    Output({"type": "chat-messages", "page": MATCH}, "children"),
    Output({"type": "chat-history", "page": MATCH}, "data"),
    Output({"type": "chat-input", "page": MATCH}, "value"),
    Output({"type": "chat-pending", "page": MATCH}, "data"),
    Input({"type": "chat-send", "page": MATCH}, "n_clicks"),
    Input({"type": "chat-input", "page": MATCH}, "n_submit"),
    Input({"type": "chat-chip", "page": MATCH, "text": ALL}, "n_clicks"),
    State({"type": "chat-input", "page": MATCH}, "value"),
    State({"type": "chat-history", "page": MATCH}, "data"),
    prevent_initial_call=True,
)
def echo_user_message(_send_clicks, _submit_count, _chip_clicks, input_value, history):
    """Fires instantly on send - shows the user's own message right away,
    before the (multi-second) model call even starts. The actual reply is
    fetched by respond_to_pending(), triggered off the chat-pending Store."""
    trig = ctx.triggered_id
    if not trig or not ctx.triggered or not ctx.triggered[0]["value"]:
        raise PreventUpdate

    if isinstance(trig, dict) and trig.get("type") == "chat-chip":
        user_text = trig.get("text", "")
    else:
        user_text = (input_value or "").strip()
    if not user_text:
        raise PreventUpdate

    history = list(history or [])
    history.append({"role": "user", "content": user_text})
    # turn count makes each pending value unique even if the same question is
    # sent twice in a row, so the Store change reliably re-triggers the reply.
    pending = {"text": user_text, "turn": len(history)}
    return render_chat_bubbles(history), history, "", pending


@app.callback(
    Output({"type": "chat-messages", "page": MATCH}, "children", allow_duplicate=True),
    Output({"type": "chat-history", "page": MATCH}, "data", allow_duplicate=True),
    Input({"type": "chat-pending", "page": MATCH}, "data"),
    State({"type": "chat-history", "page": MATCH}, "data"),
    State({"type": "chat-model", "page": MATCH}, "data"),
    prevent_initial_call=True,
)
def respond_to_pending(pending, history, model_key):
    if not pending:
        raise PreventUpdate
    history = list(history or [])
    user_id = getattr(current_user, "id", None)
    reply, appended = call_model_guarded(model_key or DEFAULT_MODEL, history, user_id)
    history = history + appended if appended else history + [{"role": "assistant", "content": reply}]
    history = ai_chat.trim_history(history)
    return render_chat_bubbles(history), history


# --------------------------------------------------- borrower limits modal

# Open and close are separate callbacks on purpose. The close button only exists
# once the modal body has been rendered, and a callback whose Input is missing
# from the layout never fires — so pairing them would mean the open button did
# nothing until something else had already opened the modal.

@app.callback(
    Output("b360-limits-modal", "is_open"),
    Output("b360-limits-modal-children", "children"),
    Input("b360-limits-btn", "n_clicks"),
    State("b360-chat-customer-store", "data"),
    prevent_initial_call=True,
)
def open_b360_limits_modal(n_clicks, customer_id):
    """Opens the limits views over the borrower page. Defaults to Utilisation —
    the movement view — because that is the one that says whether a line is being
    approached or released."""
    if not n_clicks:
        raise PreventUpdate
    customer_id = customer_id or dl.DEFAULT_CUSTOMER
    return True, build_b360_limits_modal_body(customer_id, dl.DEFAULT_QUARTER, view="Utilisation")


@app.callback(
    Output("b360-limits-modal", "is_open", allow_duplicate=True),
    Input("b360-limits-close", "n_clicks"),
    prevent_initial_call=True,
)
def close_b360_limits_modal(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    return False


@app.callback(
    Output({"type": "b360-limits-tab", "view": ALL}, "className"),
    Output("b360-limits-view", "children"),
    Input({"type": "b360-limits-tab", "view": ALL}, "n_clicks"),
    State({"type": "b360-limits-tab", "view": ALL}, "id"),
    State("b360-chat-customer-store", "data"),
    prevent_initial_call=True,
)
def switch_b360_limits_view(_clicks, ids, customer_id):
    trig = ctx.triggered_id
    if not trig or not ctx.triggered[0]["value"]:
        raise PreventUpdate
    view = trig["view"]
    classnames = ["subnav-item active" if d["view"] == view else "subnav-item" for d in ids]
    customer_id = customer_id or dl.DEFAULT_CUSTOMER
    body = build_limits_body(dl.DEFAULT_QUARTER, view=view,
                             highlight_labels=borrower_limit_labels(customer_id))
    return classnames, body


# ------------------------------------------------------------- borrower list

@app.callback(
    Output("blist-body", "children"),
    Input("blist-search", "value"),
    Input("blist-sector", "value"),
    Input("blist-segment", "value"),
    Input("blist-quarter", "value"),
    prevent_initial_call=True,
)
def update_borrower_list(search, sector, segment, quarter):
    return build_borrower_list_body(quarter or dl.DEFAULT_QUARTER, search or "",
                                    sector or "All", segment or "All")


@app.callback(
    Output("current-quarter-store", "data", allow_duplicate=True),
    Input("blist-quarter", "value"),
    prevent_initial_call=True,
)
def sync_blist_quarter(quarter):
    # keeps the row-click detail modal on the same snapshot as the list
    return quarter or dl.DEFAULT_QUARTER


# ----------------------------------------------------------------- data hub

@app.callback(
    Output("upload-report", "children"),
    Output("activate-dataset-btn", "disabled"),
    Input("upload-dataset", "contents"),
    State("upload-dataset", "filename"),
    prevent_initial_call=True,
)
def stage_uploaded_dataset(contents, filename):
    if not contents:
        raise PreventUpdate
    try:
        _prefix, b64 = contents.split(",", 1)
        raw = base64.b64decode(b64)
    except Exception:
        logger.warning("Rejected upload %r: undecodable payload", filename)
        bad = {"ok": False, "quarters": [], "rows_total": 0,
               "checks": [{"name": "Workbook readable", "status": "fail",
                           "detail": "Could not decode the uploaded file."}]}
        return data_hub.render_validation_report(bad, filename), True, None

    if len(raw) > settings.max_upload_bytes:
        logger.warning("Rejected upload %r: %.1f MB exceeds %d MB cap",
                       filename, len(raw) / 1024 / 1024, settings.max_upload_mb)
        bad = {"ok": False, "quarters": [], "rows_total": 0,
               "checks": [{"name": "File size", "status": "fail",
                           "detail": f"File is {len(raw) / 1024 / 1024:.1f} MB — the limit is "
                                     f"{settings.max_upload_mb} MB. Split or compress the workbook."}]}
        return data_hub.render_validation_report(bad, filename), True, None

    logger.info("Validating uploaded workbook %r (%.1f MB)", filename, len(raw) / 1024 / 1024)
    report = dl.validate_workbook_bytes(raw)
    staged_id = None
    if report["ok"]:
        staged_id = data_store.stage_upload(raw, filename, report)  # persists a 'staged' version
        logger.info("Upload %r passed validation and was staged as version %s", filename, staged_id)
    else:
        logger.info("Upload %r failed validation", filename)
    return data_hub.render_validation_report(report, filename), not report["ok"], staged_id


@app.callback(
    Output("datahub-status", "children"),
    Output("datahub-profile", "children"),
    Output("datahub-history", "children"),
    Output("upload-report", "children", allow_duplicate=True),
    Output("activate-dataset-btn", "disabled", allow_duplicate=True),
    Input("activate-dataset-btn", "n_clicks"),
    State("staged-version-store", "data"),
    prevent_initial_call=True,
)
def activate_uploaded_dataset(n_clicks, staged_id):
    if not n_clicks or not staged_id:
        raise PreventUpdate
    data_store.activate_version(int(staged_id))
    data_store.ensure_current()  # swap in-memory globals to the new version now
    logger.info("Data Hub: activated uploaded dataset version %s", staged_id)
    msg = html.Div(
        "✓ Uploaded dataset is now active across every page — quarters, filters and all "
        "dashboards now reflect the new workbook.",
        className="upload-verdict is-ok",
    )
    return (data_hub.build_status_card(), data_hub.build_profile_card(),
            data_hub.build_history_card(), msg, True)


@app.callback(
    Output("datahub-status", "children", allow_duplicate=True),
    Output("datahub-profile", "children", allow_duplicate=True),
    Output("datahub-history", "children", allow_duplicate=True),
    Output("upload-report", "children", allow_duplicate=True),
    Output("activate-dataset-btn", "disabled", allow_duplicate=True),
    Input("revert-dataset-btn", "n_clicks"),
    prevent_initial_call=True,
)
def revert_bundled_dataset(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    bundled_id = data_store.bundled_version_id()
    if bundled_id is None:
        raise PreventUpdate
    data_store.activate_version(bundled_id)
    data_store.ensure_current()
    logger.info("Data Hub: reverted to bundled dataset version %s", bundled_id)
    msg = html.Div("Reverted to the bundled dataset — it is active across every page again.",
                   className="upload-verdict is-ok")
    return (data_hub.build_status_card(), data_hub.build_profile_card(),
            data_hub.build_history_card(), msg, True)


# -------------------------------------------------------------------- macro

@app.callback(
    Output("macro-outlook-body", "children"),
    Output("macro-w-note", "children"),
    Input("macro-scenario", "value"),
    Input("macro-country", "value"),
    Input("macro-w-base", "value"),
    Input("macro-w-up", "value"),
    Input("macro-w-down", "value"),
    prevent_initial_call=True,
)
def update_macro_outlook(scenario, region, w_base, w_up, w_down):
    weights = dl.normalize_weights(w_base, w_up, w_down)
    note = "→ normalized: " + " / ".join(f"{weights[s] * 100:.0f}%" for s in dl.MACRO_SCENARIOS)
    return macro_view.build_macro_outlook_body(scenario or "Baseline", region or "All", weights), note


@app.callback(
    Output("macrisk-body", "children"),
    Output("macrisk-w-note", "children"),
    Input("macrisk-scenario", "value"),
    Input("macrisk-region", "value"),
    Input("macrisk-w-base", "value"),
    Input("macrisk-w-up", "value"),
    Input("macrisk-w-down", "value"),
    prevent_initial_call=True,
)
def update_macro_sector(scenario, region, w_base, w_up, w_down):
    weights = dl.normalize_weights(w_base, w_up, w_down)
    note = "→ normalized: " + " / ".join(f"{weights[s] * 100:.0f}%" for s in dl.MACRO_SCENARIOS)
    return macro_view.build_macro_sector_body(scenario or "Baseline", region or "All", weights), note


# ------------------------------------------------------------ post-deal RAROC

@app.callback(
    Output("raroc-body", "children"),
    Input("raroc-view", "value"),
    prevent_initial_call=True,
)
def update_post_deal_raroc(view):
    return raroc_view.build_post_deal_raroc_body(view or "All deals")


@app.callback(
    Output("raroc-download", "data"),
    Input("raroc-export", "n_clicks"),
    prevent_initial_call=True,
)
def export_post_deal_raroc(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    deals = raroc_data.compute_post_deal_deals()
    rows = [{label: d[key] for label, key in raroc_data._EXPORT_COLUMNS} for d in deals]
    df = pd.DataFrame(rows)
    num_cols = df.select_dtypes(include="number").columns
    df[num_cols] = df[num_cols].round(3)
    return dcc.send_data_frame(df.to_csv, "Post_Deal_RAROC_Sample.csv", index=False)


# --------------------------------------------------------- RAROC 2 (post-deal)

@app.callback(
    Output("r2exp-body", "children"),
    Input("r2exp-toggles", "value"),
    Input("r2exp-segment", "value"),
    prevent_initial_call=True,
)
def update_r2_explorer(toggles, segment):
    return raroc2_view.build_deal_explorer_body(toggles, segment or "All")


@app.callback(
    Output("r2det-body", "children"),
    Input("r2det-deal", "value"),
    Input("r2det-toggles", "value"),
    prevent_initial_call=True,
)
def update_r2_detail(deal_id, toggles):
    return raroc2_view.build_deal_detail_body(deal_id, toggles)


@app.callback(
    Output("r2earn-body", "children"),
    Input("r2earn-toggles", "value"),
    prevent_initial_call=True,
)
def update_r2_earnings(toggles):
    return raroc2_view.build_earnings_body(toggles)


@app.callback(
    Output("raroc-download", "data", allow_duplicate=True),
    Input("r2exp-export", "n_clicks"),
    prevent_initial_call=True,
)
def export_r2_sample(n_clicks):
    if not n_clicks:
        raise PreventUpdate
    deals = raroc2_data.compute_deal_book()
    cols = ["deal_id", "borrower", "segment", "sector", "region", "facility_type", "rate_type",
            "booking_q", "tenor", "ead", "undrawn", "nim_book", "nim_now", "ftp_now", "pd_ttc_book",
            "pd_pit", "lgd", "rating_book", "rating_now", "cap_now", "approved_raroc", "raroc_st",
            "raroc_lt", "ste", "lte", "eva_st", "eva_lt"]
    df = pd.DataFrame([{c: d.get(c) for c in cols} for d in deals])
    num_cols = df.select_dtypes(include="number").columns
    df[num_cols] = df[num_cols].round(3)
    return dcc.send_data_frame(df.to_csv, "Post_Deal_RAROC2_Sample.csv", index=False)


@app.callback(
    Output("machealth-body", "children"),
    Output("machealth-w-note", "children"),
    Input("machealth-region", "value"),
    Input("machealth-w-base", "value"),
    Input("machealth-w-up", "value"),
    Input("machealth-w-down", "value"),
    prevent_initial_call=True,
)
def update_macro_health(region, w_base, w_up, w_down):
    weights = dl.normalize_weights(w_base, w_up, w_down)
    note = "→ normalized: " + " / ".join(f"{weights[s] * 100:.0f}%" for s in dl.MACRO_SCENARIOS)
    return macro_view.build_macro_health_body(region or "All", weights), note


# --------------------------------------------------------------- BRF returns

@app.callback(
    Output("brfov-body", "children"),
    Input("brfov-quarter", "value"),
    prevent_initial_call=True,
)
def update_brf_overview(quarter):
    return brf_view.build_brf_overview_body(quarter or dl.DEFAULT_QUARTER)


@app.callback(
    Output("brfaq-body", "children"),
    Input("brfaq-quarter", "value"),
    prevent_initial_call=True,
)
def update_brf_asset_quality(quarter):
    return brf_view.build_brf_asset_quality_body(quarter or dl.DEFAULT_QUARTER)


@app.callback(
    Output("brfea-body", "children"),
    Input("brfea-quarter", "value"),
    prevent_initial_call=True,
)
def update_brf_activity(quarter):
    return brf_view.build_brf_activity_body(quarter or dl.DEFAULT_QUARTER)


@app.callback(
    Output("brfle-body", "children"),
    Input("brfle-quarter", "value"),
    prevent_initial_call=True,
)
def update_brf_large_exposures(quarter):
    return brf_view.build_brf_large_exp_body(quarter or dl.DEFAULT_QUARTER)


@app.callback(
    Output("brf-download", "data"),
    Input("brfaq-export", "n_clicks"),
    State("brfaq-quarter", "value"),
    prevent_initial_call=True,
)
def export_brf_asset_quality(n_clicks, quarter):
    if not n_clicks:
        raise PreventUpdate
    quarter = quarter or dl.DEFAULT_QUARTER
    aq = dl.compute_brf_asset_quality(quarter)
    df = pd.DataFrame([{
        "Classification": r["class"], "Accounts": r["accounts"],
        "Exposure (AED mn)": round(r["ead"] * dl.AED_PER_USD, 2),
        "% of Book": round(r["pct_of_book"], 2),
        "Provisions (AED mn)": round(r["provision"] * dl.AED_PER_USD, 2),
        "Coverage %": round(r["coverage"], 2),
    } for r in aq["rows"]])
    return dcc.send_data_frame(df.to_csv, f"BRF_Asset_Quality_{quarter.replace(' ', '_')}.csv", index=False)


@app.callback(
    Output("brf-download", "data", allow_duplicate=True),
    Input("brfea-export", "n_clicks"),
    State("brfea-quarter", "value"),
    prevent_initial_call=True,
)
def export_brf_activity(n_clicks, quarter):
    if not n_clicks:
        raise PreventUpdate
    quarter = quarter or dl.DEFAULT_QUARTER
    ea = dl.compute_brf_economic_activity(quarter)
    df = pd.DataFrame([{
        "Economic Activity": r["activity"], "Accounts": r["accounts"],
        "Funded (AED mn)": round(r["funded"] * dl.AED_PER_USD, 2),
        "Unfunded (AED mn)": round(r["unfunded"] * dl.AED_PER_USD, 2),
        "EAD (AED mn)": round(r["ead"] * dl.AED_PER_USD, 2),
        "% of Book": round(r["pct_of_book"], 2),
        "NPL %": round(r["npl_pct"], 2),
        "Provisions (AED mn)": round(r["provision"] * dl.AED_PER_USD, 2),
    } for r in ea["rows"]])
    return dcc.send_data_frame(df.to_csv, f"BRF_Economic_Activity_{quarter.replace(' ', '_')}.csv", index=False)


@app.callback(
    Output("brf-download", "data", allow_duplicate=True),
    Input("brfle-export", "n_clicks"),
    State("brfle-quarter", "value"),
    prevent_initial_call=True,
)
def export_brf_large_exposures(n_clicks, quarter):
    if not n_clicks:
        raise PreventUpdate
    quarter = quarter or dl.DEFAULT_QUARTER
    le = dl.compute_brf_large_exposures(quarter)
    df = pd.DataFrame([{
        "Obligor / Group": r["name"], "Type": r["type"],
        "Exposure (AED mn)": round(r["ead"] * dl.AED_PER_USD, 2),
        "% of Capital Base": round(r["pct_capital"], 2),
        "Breach of 25% Cap": "Yes" if r["breach"] else "No",
    } for r in le["rows"]])
    return dcc.send_data_frame(df.to_csv, f"BRF_Large_Exposures_{quarter.replace(' ', '_')}.csv", index=False)


# ------------------------------------------------ ESG / climate stressed PD
# Every tab recalculates the whole model on any control change: 280 cells of pure
# arithmetic is ~6ms, cheaper than round-tripping a cache. The stored model
# version is never mutated by these controls — saving is explicit, on the Inputs
# tab, and a version marked final is immutable.


@app.callback(
    Output("esg-res-body", "children"),
    Input("esg-res-version", "value"),
    Input("esg-res-horizon", "value"),
    Input("esg-res-theta", "value"),
    Input("esg-res-grade", "value"),
    Input("esg-res-view", "value"),
    prevent_initial_call=True,
)
def update_esg_results(version_id, horizon, theta, grade, view):
    return esg_view.build_results_body(version_id, horizon, theta, grade, view or "summary")


@app.callback(
    Output("esg-dd-body", "children"),
    Input("esg-dd-version", "value"),
    Input("esg-dd-horizon", "value"),
    Input("esg-dd-sector", "value"),
    Input("esg-dd-grade", "value"),
    Input("esg-dd-scenario", "value"),
    prevent_initial_call=True,
)
def update_esg_drilldown(version_id, horizon, sector_id, grade, scenario):
    if not (sector_id and grade and scenario):
        raise PreventUpdate
    return esg_view.build_drilldown_body(version_id, horizon, sector_id, grade, scenario)


@app.callback(
    Output("esg-in-body", "children"),
    Input("esg-in-version", "value"),
    Input("esg-in-block", "value"),
    prevent_initial_call=True,
)
def update_esg_inputs(version_id, block):
    return esg_view.build_inputs_body(version_id, block or "sectors")


ESG_INPUT_TABLE_IDS = ["esg-tbl-sectors", "esg-tbl-emissions", "esg-tbl-scenarios",
                       "esg-tbl-hazards", "esg-tbl-exposure", "esg-tbl-grades", "esg-tbl-settings"]


@app.callback(
    Output("esg-in-status", "children"),
    Output("esg-in-body", "children", allow_duplicate=True),
    Input("esg-in-save", "n_clicks"),
    State("esg-in-version", "value"),
    State("esg-in-block", "value"),
    *[State(tid, "data") for tid in ESG_INPUT_TABLE_IDS],
    prevent_initial_call=True,
)
def save_esg_inputs(n_clicks, version_id, block, *table_data):
    """Fold the edited table back into the version. Rejected outright if the
    version is final — that immutability is what the audit trail rests on."""
    if not n_clicks:
        raise PreventUpdate
    block = block or "sectors"
    rows = dict(zip(ESG_INPUT_TABLE_IDS, table_data, strict=True)).get(f"esg-tbl-{block}")
    if not rows:
        raise PreventUpdate

    rec = climate_store.get_version(version_id) if version_id else None
    if rec is None:
        return html.Div("Select a model version first.", className="upload-verdict is-fail"), no_update
    if rec["status"] == climate_store.STATUS_FINAL:
        return (html.Div("This version is FINAL and cannot be edited. Use “Clone as draft” first.",
                         className="upload-verdict is-fail"), no_update)

    try:
        updated = esg_view.apply_edits(rec["model"], block, rows)
        climate_store.update_version(rec["id"], updated,
                                     note=f"{block} edited via the Inputs tab")
    except Exception as exc:
        logger.exception("ESG input save failed")
        return html.Div(f"Save failed: {exc}", className="upload-verdict is-fail"), no_update

    logger.info("ESG: saved %s edits to model version %s", block, rec["id"])
    msg = html.Div(f"Saved to version #{rec['id']}. Every downstream figure has been recalculated.",
                   className="upload-verdict is-ok")
    return msg, esg_view.build_inputs_body(rec["id"], block)


@app.callback(
    Output("esg-in-status", "children", allow_duplicate=True),
    Output("esg-in-version", "options"),
    Output("esg-in-version", "value"),
    Input("esg-in-clone", "n_clicks"),
    State("esg-in-version", "value"),
    prevent_initial_call=True,
)
def clone_esg_version(n_clicks, version_id):
    if not n_clicks or version_id is None:
        raise PreventUpdate
    src = climate_store.get_version(version_id)
    if src is None:
        raise PreventUpdate
    new = climate_store.clone_version(
        version_id, name=f"{src['name']} (draft)",
        created_by=getattr(current_user, "username", "") or "")
    msg = html.Div(f"Created draft version #{new['id']} from #{version_id}. Edits now go to the draft; "
                   f"the parent stays immutable.", className="upload-verdict is-ok")
    return msg, esg_view.version_options(), new["id"]


@app.callback(
    Output("esg-cal-body", "children"),
    Input("esg-cal-version", "value"),
    Input("esg-cal-anchor", "value"),
    Input("esg-cal-route", "value"),
    Input("esg-cal-theta", "value"),
    prevent_initial_call=True,
)
def update_esg_calibration(version_id, anchor, route, theta):
    return esg_view.build_calibration_body(version_id, anchor or "A", route or 1,
                                           0.0 if theta is None else theta)


@app.callback(
    Output("esg-sens-body", "children"),
    Input("esg-sens-version", "value"),
    Input("esg-sens-horizon", "value"),
    Input("esg-sens-param", "value"),
    prevent_initial_call=True,
)
def update_esg_sensitivity(version_id, horizon, parameter):
    return esg_view.build_sensitivity_body(version_id, horizon, parameter or "theta")


@app.callback(
    Output("esg-qc-body", "children"),
    Input("esg-qc-version", "value"),
    Input("esg-qc-horizon", "value"),
    Input("esg-qc-theta", "value"),
    prevent_initial_call=True,
)
def update_esg_checks(version_id, horizon, theta):
    return esg_view.build_checks_body(version_id, horizon, theta)


@app.callback(
    Output("esg-run-status", "children"),
    Output("esg-run-body", "children"),
    Input("esg-run-calc", "n_clicks"),
    Input("esg-run-final", "n_clicks"),
    State("esg-run-version", "value"),
    prevent_initial_call=True,
)
def esg_run_actions(calc_clicks, final_clicks, version_id):
    if version_id is None or not ctx.triggered_id:
        raise PreventUpdate

    if ctx.triggered_id == "esg-run-calc":
        if not calc_clicks:
            raise PreventUpdate
        run = climate_store.calculate_run(
            version_id, created_by=getattr(current_user, "username", "") or "")
        head = run["headline"]
        tone = "is-ok" if head["can_finalise"] else "is-fail"
        msg = html.Div(
            f"Stored run #{run['id']} with a full input snapshot — {head['cells']} cells, "
            f"worst {head['max_multiple']:.3f}x ({head['worst_sector']} · {head['worst_scenario']}), "
            f"{head['checks_passed']}/{head['checks_total']} checks passing.",
            className=f"upload-verdict {tone}")
        logger.info("ESG: stored run %s for version %s", run["id"], version_id)
        return msg, esg_view.build_runs_body(version_id)

    if not final_clicks:
        raise PreventUpdate
    try:
        rec = climate_store.set_status(version_id, climate_store.STATUS_FINAL)
    except ValueError as exc:
        return (html.Div(str(exc), className="upload-verdict is-fail"),
                esg_view.build_runs_body(version_id))
    msg = html.Div(f"Version #{rec['id']} marked final — its inputs are now immutable.",
                   className="upload-verdict is-ok")
    return msg, esg_view.build_runs_body(version_id)


@app.callback(
    Output("esg-run-diff", "children"),
    Input("esg-run-a", "value"),
    Input("esg-run-b", "value"),
    prevent_initial_call=True,
)
def update_esg_run_diff(run_a, run_b):
    return esg_view.build_run_diff(run_a, run_b)


@app.callback(
    Output("esg-rep-body", "children"),
    Input("esg-rep-version", "value"),
    Input("esg-rep-horizon", "value"),
    Input("esg-rep-theta", "value"),
    Input("esg-rep-grade", "value"),
    prevent_initial_call=True,
)
def update_esg_report_preview(version_id, horizon, theta, grade):
    return esg_view.build_report_body(version_id, horizon, theta, grade)


@app.callback(
    Output("esg-download", "data"),
    Output("esg-rep-status", "children"),
    Input("esg-rep-html", "n_clicks"),
    State("esg-rep-version", "value"),
    State("esg-rep-horizon", "value"),
    State("esg-rep-theta", "value"),
    State("esg-rep-grade", "value"),
    State("esg-rep-tornado", "value"),
    prevent_initial_call=True,
)
def download_esg_report(n_clicks, version_id, horizon, theta, grade, tornado):
    if not n_clicks:
        raise PreventUpdate
    filename, doc = esg_view.build_report_download(
        version_id, horizon, theta, grade, with_tornado=bool(tornado),
        username=getattr(current_user, "username", "") or "")
    msg = html.Div(f"Generated {filename} ({len(doc.encode()) / 1024:,.0f} KB) — a single "
                   f"self-contained file, no external requests.", className="upload-verdict is-ok")
    return dict(content=doc, filename=filename, type="text/html"), msg


@app.callback(
    Output("esg-download", "data", allow_duplicate=True),
    Output("esg-rep-status", "children", allow_duplicate=True),
    Input("esg-rep-xlsx", "n_clicks"),
    State("esg-rep-version", "value"),
    State("esg-rep-horizon", "value"),
    State("esg-rep-theta", "value"),
    State("esg-rep-grade", "value"),
    prevent_initial_call=True,
)
def download_esg_excel(n_clicks, version_id, horizon, theta, grade):
    if not n_clicks:
        raise PreventUpdate
    filename, payload = esg_view.build_excel_download(version_id, horizon, theta, grade)
    msg = html.Div(f"Generated {filename} — inputs, intermediates, the full grid, the 24 checks and "
                   f"all three registers.", className="upload-verdict is-ok")
    return dcc.send_bytes(lambda buf: buf.write(payload), filename), msg


@app.callback(
    Output("esg-download", "data", allow_duplicate=True),
    Input("esg-rep-csv", "n_clicks"),
    State("esg-rep-version", "value"),
    State("esg-rep-horizon", "value"),
    State("esg-rep-theta", "value"),
    State("esg-rep-grade", "value"),
    prevent_initial_call=True,
)
def download_esg_grid_csv(n_clicks, version_id, horizon, theta, grade):
    if not n_clicks:
        raise PreventUpdate
    rows = esg_view.build_grid_rows(version_id, horizon, theta, grade)
    df = pd.DataFrame(rows)
    return dcc.send_data_frame(df.to_csv, "Climate_StressedPD_Grid.csv", index=False)


if __name__ == "__main__":
    # Development entrypoint (Dash dev server). Production is served by Waitress
    # via serve.py; see docs/deploy.md. Host/port/debug come from config.settings.
    logger.info("Starting IPM Tool dev server on %s:%s (env=%s)", settings.host, settings.port, settings.env)
    app.run(debug=settings.debug, dev_tools_ui=False, use_reloader=False,
            threaded=True, host=settings.host, port=settings.port)
