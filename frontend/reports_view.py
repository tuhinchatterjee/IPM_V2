"""
The Reports section: Review Pack, Schedules and Archive.

Review Pack asks two questions — which committee, and PDF or Word — and then
shows what that pack will actually say before it is generated. The preview is
built from the same content model the writers use, so what is on screen is what
lands in the file; there is no second, drifting summary.

Schedules and Archive are the surrounding machinery: when a pack is due, and
what has already been issued. The Archive lists real stored artefacts and
re-serves the exact bytes that were issued.
"""

from datetime import date, timedelta

from dash import dcc, html

from backend import data_loader as dl
from backend.reporting import content as rc
from backend.reporting import store as report_store
from backend.reporting import writers

DEFAULT_CONFIG = {"type": "smc", "format": "pdf", "quarter": None}

SEVERITY_CLASS = {"HIGH": "sev-high", "MEDIUM": "sev-medium", "LOW": "sev-low"}

# What each pack promises the reader, in the reader's language rather than the
# section keys used internally.
TYPE_HIGHLIGHTS = {
    "smc": ["Full IFRS 9 staging and ECL movement", "Every limit line and concentration cap",
            "Watchlist, migration and early-warning detail", "Stress, climate and macro outlook",
            "Remediation for every live breach"],
    "brc": ["Position, asset quality and appetite", "Stress and climate headlines",
            "Actions the Board must decide on", "No working-level detail"],
}


def resolve_config(config):
    """Normalise whatever the Store holds into a usable config."""
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(config, dict):
        cfg.update({k: v for k, v in config.items() if v is not None})
    if cfg["type"] not in rc.REPORT_TYPES:
        cfg["type"] = "smc"
    if cfg["format"] not in writers.FORMATS:
        cfg["format"] = "pdf"
    cfg["quarter"] = cfg.get("quarter") or dl.DEFAULT_QUARTER
    return cfg


# ------------------------------------------------------------------ Review Pack

def _type_card(key, selected):
    spec = rc.REPORT_TYPES[key]
    sections = rc.sections_for(key)
    return html.Div(
        [
            html.Div(
                [html.Span(spec["short"], className="rep-type-name"),
                 html.Span("SELECTED" if selected else "", className="rep-type-flag")],
                className="rep-type-head",
            ),
            html.Div(spec["title"], className="rep-type-title"),
            html.Div(spec["purpose"], className="rep-type-purpose"),
            html.Ul([html.Li(h) for h in TYPE_HIGHLIGHTS[key]], className="rep-type-list"),
            html.Div(
                [html.Span(f"{len(sections)} sections", className="rep-type-chip"),
                 html.Span(spec["audience"], className="rep-type-chip is-muted")],
                className="rep-type-foot",
            ),
        ],
        id={"type": "rep-type-card", "key": key},
        n_clicks=0,
        className="rep-type-card" + (" is-selected" if selected else ""),
    )


def _format_card(key, selected):
    spec = writers.FORMATS[key]
    blurb = ("Print-ready and page-numbered — the version to table at the meeting."
             if key == "pdf" else
             "Editable, so secretariat can add minutes and house commentary before circulation.")
    return html.Div(
        [
            html.Div(spec["label"], className="rep-fmt-name"),
            html.Div(f".{spec['extension']}", className="rep-fmt-ext"),
            html.Div(blurb, className="rep-fmt-blurb"),
        ],
        id={"type": "rep-fmt-card", "key": key},
        n_clicks=0,
        className="rep-fmt-card" + (" is-selected" if selected else ""),
    )


def _stat(label, value, cls=""):
    return html.Div(
        [html.Div(value, className=f"rep-stat-value {cls}".strip()),
         html.Div(label, className="rep-stat-label")],
        className="rep-stat",
    )


def _findings_preview(report):
    """The findings, grouped by severity — the part of the pack that drives every
    action and remediation row, so it is worth seeing before generating."""
    order = ["HIGH", "MEDIUM", "LOW"]
    groups = {s: [f for f in report["findings"] if f["severity"] == s] for s in order}
    blocks = []
    for sev in order:
        items = groups[sev]
        if not items:
            continue
        blocks.append(html.Div(
            [
                html.Div(
                    [html.Span(sev, className=f"rep-sev-tag {SEVERITY_CLASS[sev]}"),
                     html.Span(f"{len(items)} finding{'s' if len(items) != 1 else ''}",
                               className="rep-sev-count")],
                    className="rep-sev-head",
                ),
                html.Ul([html.Li([html.Span(f["area"], className="rep-finding-area"), f["text"]])
                         for f in items], className="rep-finding-list"),
            ],
            className="rep-sev-block",
        ))
    if not blocks:
        blocks = [html.Div("No findings were raised this quarter.", className="rep-empty-line")]
    return blocks


def _preview_table(columns, rows, limit=6):
    head = html.Thead(html.Tr([html.Th(c) for c in columns]))
    body = html.Tbody([html.Tr([html.Td(str(c)) for c in r]) for r in rows[:limit]])
    return html.Table([head, body], className="borrower-table signals-table rep-preview-table")


def build_review_pack_body(config=None):
    cfg = resolve_config(config)
    report = rc.build_report(cfg["type"], cfg["quarter"])
    spec = rc.REPORT_TYPES[cfg["type"]]

    chooser = html.Div(
        [
            html.Div(
                [html.Span("1", className="rep-step-num"),
                 html.Span("Which report do you need?", className="rep-step-label")],
                className="rep-step",
            ),
            html.Div([_type_card(k, k == cfg["type"]) for k in rc.REPORT_TYPES],
                     className="rep-type-grid"),
            html.Div(
                [html.Span("2", className="rep-step-num"),
                 html.Span("PDF or Word?", className="rep-step-label")],
                className="rep-step",
            ),
            html.Div([_format_card(k, k == cfg["format"]) for k in writers.FORMATS],
                     className="rep-fmt-grid"),
            html.Div(
                [html.Span("3", className="rep-step-num"),
                 html.Span("Reporting period", className="rep-step-label")],
                className="rep-step",
            ),
            dcc.Dropdown(id="rep-quarter", options=dl.QUARTER_OPTIONS, value=cfg["quarter"],
                         clearable=False, searchable=False, className="filter-dd",
                         style={"width": "100%"}),
            html.Div(
                [
                    html.Button(f"Generate {writers.FORMATS[cfg['format']]['label']} pack",
                                id="rep-generate", n_clicks=0, className="report-generate-btn"),
                ],
                className="report-btn-row",
            ),
            html.Div(id="rep-status", className="rep-status"),
            html.Div(f"{spec['cadence']}. Every figure is read from the live dataset at the moment "
                     f"you generate, and the pack is archived so it can be re-served unchanged.",
                     className="report-config-note"),
        ],
        className="report-config-panel",
    )

    contents = html.Div(
        [
            html.Div("WHAT THIS PACK CONTAINS", className="rep-panel-title"),
            html.Div(
                [html.Div([html.Span("✓", className="rep-tick"), title], className="rep-toc-row")
                 for _key, title in rc.sections_for(cfg["type"])],
                className="rep-toc",
            ),
        ],
        className="rep-panel",
    )

    stats = html.Div(
        [
            _stat("Sections", str(len(report["sections"]))),
            _stat("Findings", str(len(report["findings"]))),
            _stat("High severity", str(report["high_severity_count"]),
                  "is-red" if report["high_severity_count"] else ""),
            _stat("Actions", str(len(report["actions"]))),
            _stat("Remediation items", str(len(report["remediation"]))),
        ],
        className="rep-stat-row",
    )

    exec_section = next((s for s in report["sections"] if s["key"] == "executive_summary"), None)
    preview = html.Div(
        [
            html.Div(
                [html.Div([html.Div(report["title"], className="report-doc-title"),
                           html.Div(f"{report['quarter_label']} · {report['classification']}",
                                    className="report-doc-sub")]),
                 html.Span("LIVE PREVIEW", className="report-doc-badge")],
                className="report-doc-header",
            ),
            stats,
            html.Div(
                [html.Div("EXECUTIVE SUMMARY", className="rep-panel-title"),
                 html.Div(exec_section["narrative"] if exec_section else "",
                          className="rep-narrative"),
                 _preview_table(exec_section["table"]["columns"], exec_section["table"]["rows"], 8)
                 if exec_section and exec_section.get("table") else html.Div()],
                className="rep-panel",
            ),
            html.Div(
                [html.Div("FINDINGS RAISED", className="rep-panel-title"),
                 html.Div("Actions and remediation below are derived from these findings, so an "
                          "action cannot outlive the condition that produced it.",
                          className="rep-panel-note"),
                 *_findings_preview(report)],
                className="rep-panel",
            ),
            html.Div(
                [html.Div("RECOMMENDED ACTIONS", className="rep-panel-title"),
                 _preview_table(["Priority", "Area", "Action", "Owner", "Target"],
                                [[a["priority"], a["area"], a["action"], a["owner"], a["due"]]
                                 for a in report["actions"]], limit=10)],
                className="rep-panel",
            ),
            html.Div(
                [html.Div("REMEDIATION PLAN", className="rep-panel-title"),
                 html.Div(f"{len(report['remediation'])} items — every live breach or exception "
                          f"carries an owner and a due date.", className="rep-panel-note"),
                 _preview_table(["Severity", "Area", "Issue", "Owner", "Due"],
                                [[r["severity"], r["area"], r["issue"], r["owner"], r["due"]]
                                 for r in report["remediation"]], limit=8)],
                className="rep-panel",
            ),
        ],
        className="rep-preview",
    )

    return [
        html.Div([html.Div([chooser, contents]), preview],
                 className="split-grid rep-split"),
    ]


# -------------------------------------------------------------------- Schedules

SCHEDULES = [
    {"id": "smc-q", "name": "IFRS 9 Credit Committee Pack", "type": "smc",
     "cadence": "Quarterly", "offset_days": 5,
     "rule": "Quarter end + 5 business days",
     "audience": "Credit Committee · Senior Management Committee",
     "owner": "Head of Credit Risk", "format": "pdf", "status": "ACTIVE",
     "recipients": ["CRO", "Head of Credit Risk", "Head of Impairment", "Finance Controller"]},
    {"id": "brc-q", "name": "Board Risk Committee Pack", "type": "brc",
     "cadence": "Quarterly", "offset_days": 15,
     "rule": "Quarter end + 15 calendar days, ahead of the Board meeting",
     "audience": "Board Risk Committee",
     "owner": "Chief Risk Officer", "format": "pdf", "status": "ACTIVE",
     "recipients": ["Board Risk Committee", "CEO", "CRO", "Company Secretary"]},
    {"id": "smc-m", "name": "Monthly Risk Digest", "type": "smc",
     "cadence": "Monthly", "offset_days": 3,
     "rule": "3rd business day of the month",
     "audience": "Senior Management Committee",
     "owner": "Portfolio Management", "format": "docx", "status": "ACTIVE",
     "recipients": ["CRO", "Sector Heads", "Portfolio Management"]},
    {"id": "brc-adhoc", "name": "Board Escalation Pack", "type": "brc",
     "cadence": "On breach", "offset_days": 2,
     "rule": "Within 2 business days of a HIGH severity appetite breach",
     "audience": "Board Risk Committee",
     "owner": "Chief Risk Officer", "format": "pdf", "status": "TRIGGERED",
     "recipients": ["Board Risk Committee Chair", "CEO", "CRO"]},
]


def _month_start(year, month):
    """The 1st of a month, rolling the year over when month runs past December."""
    return date(year + (month - 1) // 12, (month - 1) % 12 + 1, 1)


def _quarter_end(day):
    """The last day of the calendar quarter containing `day`."""
    return _month_start(day.year, ((day.month - 1) // 3 + 1) * 3 + 1) - timedelta(days=1)


def _next_run(schedule):
    """A real date rather than a phrase, so the screen can be read at a glance."""
    today = date.today()
    offset = timedelta(days=schedule["offset_days"])

    if schedule["cadence"] == "On breach":
        return today + offset

    if schedule["cadence"] == "Monthly":
        run = _month_start(today.year, today.month) + offset
        if run < today:
            run = _month_start(today.year, today.month + 1) + offset
        return run

    end = _quarter_end(today)
    run = end + offset
    if run < today:
        run = _quarter_end(end + timedelta(days=1)) + offset
    return run


def _days_out(target):
    return (target - date.today()).days


def build_schedules_body(quarter=None):
    rows = sorted(SCHEDULES, key=lambda s: _next_run(s))
    cards = []
    for s in rows:
        nxt = _next_run(s)
        days = _days_out(nxt)
        urgency = "is-due" if days <= 3 else ("is-soon" if days <= 14 else "")
        spec = rc.REPORT_TYPES[s["type"]]
        cards.append(html.Div(
            [
                html.Div(
                    [html.Span(s["name"], className="rep-sched-name"),
                     html.Span(s["status"], className=f"rep-sched-status is-{s['status'].lower()}")],
                    className="rep-sched-head",
                ),
                html.Div(
                    [html.Span(spec["short"], className="rep-type-chip"),
                     html.Span(writers.FORMATS[s["format"]]["label"], className="rep-type-chip"),
                     html.Span(s["cadence"], className="rep-type-chip is-muted")],
                    className="rep-sched-chips",
                ),
                html.Div(s["rule"], className="rep-sched-rule"),
                html.Div(
                    [
                        html.Div([html.Div("NEXT RUN", className="rep-sched-key"),
                                  html.Div(nxt.strftime("%d %b %Y"), className="rep-sched-val")]),
                        html.Div([html.Div("IN", className="rep-sched-key"),
                                  html.Div(f"{days} day{'s' if days != 1 else ''}",
                                           className=f"rep-sched-val {urgency}")]),
                        html.Div([html.Div("OWNER", className="rep-sched-key"),
                                  html.Div(s["owner"], className="rep-sched-val")]),
                    ],
                    className="rep-sched-grid",
                ),
                html.Div(
                    [html.Span("DISTRIBUTION", className="rep-sched-key"),
                     html.Div([html.Span(r, className="rep-recipient") for r in s["recipients"]],
                              className="rep-recipient-row")],
                    className="rep-sched-dist",
                ),
                html.Button("Generate now", id={"type": "rep-sched-run", "key": s["id"]},
                            n_clicks=0, className="report-secondary-btn rep-sched-btn"),
            ],
            className=f"rep-sched-card {urgency}",
        ))

    timeline = html.Div(
        [
            html.Div("UPCOMING 90 DAYS", className="rep-panel-title"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(_next_run(s).strftime("%d %b"), className="rep-tl-date"),
                            html.Div(className="rep-tl-dot"),
                            html.Div([html.Div(s["name"], className="rep-tl-name"),
                                      html.Div(f"{s['audience']} · {s['owner']}",
                                               className="rep-tl-sub")]),
                        ],
                        className="rep-tl-row",
                    )
                    for s in rows if _days_out(_next_run(s)) <= 90
                ],
                className="rep-tl",
            ),
        ],
        className="rep-panel",
    )

    return [
        html.Div(
            [html.Div(cards, className="rep-sched-grid-outer"), timeline],
            # Cards take the wide column here — the timeline is a short list and
            # the cards are what the reader works from.
            className="split-grid rep-split-wide",
        ),
    ]


# ---------------------------------------------------------------------- Archive

def build_archive_body(quarter=None):
    packs = report_store.list_packs(limit=100)
    summary = report_store.summary()

    stats = html.Div(
        [
            _stat("Packs archived", str(summary["total"])),
            _stat("Committee", str(summary["by_type"].get("smc", 0))),
            _stat("Board", str(summary["by_type"].get("brc", 0))),
            _stat("PDF", str(summary["by_format"].get("pdf", 0))),
            _stat("Word", str(summary["by_format"].get("docx", 0))),
            _stat("Stored", f"{summary['total_bytes'] / 1_048_576:.1f} MB"),
        ],
        className="rep-stat-row",
    )

    if not packs:
        body = html.Div(
            [
                html.Div("No packs have been generated yet.", className="rep-empty-title"),
                html.Div("Generate one from the Review Pack tab and it will be archived here, "
                         "with the exact file that was issued available for re-download.",
                         className="rep-empty-sub"),
            ],
            className="rep-empty",
        )
    else:
        rows = []
        for p in packs:
            h = p.get("headline", {})
            high = h.get("high_severity_count", 0)
            rows.append(html.Tr([
                html.Td([html.Div(p["type_label"], className="metric-name"),
                         html.Div(p["filename"], className="rep-arch-file")]),
                html.Td(p["quarter"]),
                html.Td(html.Span(p["format_label"], className="rep-type-chip")),
                html.Td(str(h.get("finding_count", "—")), className="num"),
                html.Td(html.Span(str(high), className=f"rep-sev-tag {SEVERITY_CLASS['HIGH']}")
                        if high else html.Span("0", className="rep-sev-tag sev-low"),
                        className="num"),
                html.Td(str(h.get("action_count", "—")), className="num"),
                html.Td(f"{p['size_bytes'] / 1024:,.0f} KB", className="num"),
                html.Td(p["generated_at"].replace("T", " ")[:16]),
                html.Td(
                    [html.Button("Download", id={"type": "rep-arch-dl", "id": p["id"]},
                                 n_clicks=0, className="rep-arch-btn"),
                     html.Button("Delete", id={"type": "rep-arch-del", "id": p["id"]},
                                 n_clicks=0, className="rep-arch-btn is-danger")],
                    className="rep-arch-actions",
                ),
            ]))
        body = html.Table(
            [html.Thead(html.Tr([html.Th("Report"), html.Th("Period"), html.Th("Format"),
                                 html.Th("Findings", className="num"),
                                 html.Th("High", className="num"),
                                 html.Th("Actions", className="num"),
                                 html.Th("Size", className="num"),
                                 html.Th("Generated"), html.Th("")])),
             html.Tbody(rows)],
            className="borrower-table signals-table",
        )

    return [
        stats,
        html.Div(
            [html.Div([html.Span("ISSUED PACKS", className="table-title"),
                       html.Span("Re-download returns the exact file that was issued, not a "
                                 "fresh render.", className="table-hint")],
                      className="table-card-header"),
             body],
            className="simple-table-card",
        ),
        html.Div(id="rep-arch-status", className="rep-status"),
    ]
