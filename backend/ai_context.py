"""
Screen context for the Ask AI assistant.

The assistant is reachable from every screen, so "what does *this* mean?" has to
resolve against whatever the user is actually looking at. This module supplies
three things per screen, all derived from the live dataset:

  * `system_prompt(screen)`  — the model's framing: what page it is on, what that
    page shows, and the instruction to answer in that page's context.
  * `screen_brief(screen)`   — a data-grounded opening brief (portfolio snapshot
    plus what is on this screen right now), rendered in the drawer before the
    user types anything. Computed here rather than asked of the model, so it is
    instant, free, and cannot hallucinate.
  * `suggestions(screen)`    — starter questions that make sense on that screen.

Backends (`ai_chat`, `claude_chat`, `qwen_ultra_chat`) all read the system prompt
from the first message of the history, so a screen change is just a re-seed.
"""

import backend.cockpit_data as cd
from backend import ai_chat
from backend import data_loader as dl

# ---------------------------------------------------------------- screen registry
# `key` is also the chat-store page key, so each screen keeps its own conversation.

COCKPIT = "cockpit"
B360 = "b360"

SCREENS = {
    COCKPIT: {
        "route": "/",
        "label": "Executive Portfolio Risk Cockpit",
        "shows": "the portfolio-wide health index, KPI cards, IFRS 9 stage split, ECL movement, "
                 "top sectors and the top-10 borrowers by exposure",
        "focus": "portfolio-level health, exposure, asset quality and what is driving them",
    },
    "watchlist": {
        "route": "/watchlist",
        "label": "Watchlist, Distressed & Action Management",
        "shows": "the watchlist board (New / Under Review / Watchlist / Restructuring / Recovery / "
                 "Closed) and the action table for flagged borrowers",
        "focus": "which names are deteriorating, why they were flagged, and what action is due",
    },
    "stress": {
        "route": "/stress",
        "label": "AI-Driven Stress Testing & Scenario Lab",
        "shows": "the scenario lab, stressed ECL / CET1 / NPL results and reverse-stress solving",
        "focus": "how the book responds to rate and CRE shocks, and what breaks first",
    },
    "macro": {
        "route": "/macro",
        "label": "Macroeconomic Outlook & Forward Portfolio Health",
        "shows": "IMF WEO history and forecasts by GCC country, sector risk under scenario "
                 "weights, and the 4-quarter forward portfolio health path",
        "focus": "the macro path and how it feeds forward PD, NPL and ECL",
    },
    "raroc": {
        "route": "/raroc",
        "label": "RAROC — Risk-Adjusted Return on Capital",
        "shows": "post-deal RAROC by deal and segment, the deal explorer, earnings and EVA",
        "focus": "pricing adequacy, returns against the hurdle, and value creation",
    },
    "esg": {
        "route": "/esg",
        "label": "ESG & Climate Stressed PD",
        "shows": "the Oman climate stressed-PD model: a sector x rating-grade x NGFS-scenario "
                 "PD grid, the calibration workbench, sensitivity and 24 quality checks",
        "focus": "climate transition and physical risk expressed as a stressed PD",
    },
    "brf": {
        "route": "/brf",
        "label": "CBUAE BRF Regulatory Returns",
        "shows": "the CBUAE regulatory return set — asset quality, economic activity, large "
                 "exposures and the filing calendar",
        "focus": "regulatory classification, provisioning and reportable exposures",
    },
    "reports": {
        "route": "/reports",
        "label": "Management Portfolio Review Pack",
        "shows": "the review-pack generator, report schedules and the archive",
        "focus": "what goes into the committee pack and the reporting cycle",
    },
    B360: {
        "route": "/borrowers",
        "label": "Borrower 360 Monitoring View",
        "shows": "one borrower's full profile — exposure, ratios, rating history, covenants, "
                 "PD/ECL trend and collateral — plus the portfolio limit and appetite lines, "
                 "opened from the Limits & Appetite button",
        "focus": "this single borrower's credit standing, the appetite lines it sits inside, "
                 "and what to do about it",
    },
}

# Route -> screen key. Anything unmapped (including the Data Hub, which has no
# assistant) falls back to the cockpit context.
ROUTE_TO_SCREEN = {spec["route"]: key for key, spec in SCREENS.items()}

# Screens where the assistant is not offered at all.
SCREENS_WITHOUT_AI = {"/data"}


def screen_for(pathname: str | None) -> str:
    return ROUTE_TO_SCREEN.get(pathname or "/", COCKPIT)


def has_assistant(pathname: str | None) -> bool:
    return (pathname or "/") not in SCREENS_WITHOUT_AI


def spec(screen: str) -> dict:
    return SCREENS.get(screen, SCREENS[COCKPIT])


# ------------------------------------------------------------------ system prompt

# How the answer should look. The assistant renders as Markdown in the drawer, so
# asking for structure here is what turns a wall of prose into something readable.
_OUTPUT_CONTRACT = (
    " FORMAT YOUR ANSWERS AS MARKDOWN, and make them scannable:\n"
    "- Open with a one-line **headline** carrying the single most important figure.\n"
    "- Put any comparison of three or more items in a Markdown table with a header row; "
    "right-align numeric columns by writing them as plain numbers with units ($4.1bn, 3.8%).\n"
    "- Use `-` bullets for 2-5 supporting points, each starting with a **bold label**.\n"
    "- **Bold every figure** you quote so it stands out from the prose.\n"
    "- Close with a single line starting with `**So what:**` giving the action or implication.\n"
    "- Keep the whole answer under about 200 words unless a table genuinely needs more rows.\n"
    "- Never invent a number. If a tool did not return it, say what is missing instead.\n"
)


def system_prompt(screen: str, customer_id: str | None = None) -> str:
    """The model's framing for one screen.

    Scoping matters as much as grounding: the user asking "why is this red?" on
    the Limits screen means something different from the same words on Watchlist,
    so the prompt names the screen and tells the model to read questions in that
    context unless the user clearly asks about something else.
    """
    if screen == B360 and customer_id:
        return ai_chat.system_prompt_borrower(customer_id) + _OUTPUT_CONTRACT

    s = spec(screen)
    return (
        ai_chat._BASE_SYSTEM
        + f"\n\nTHE USER IS CURRENTLY ON: {s['label']}. "
        + f"This screen shows {s['shows']}. "
        + f"Its focus is {s['focus']}. "
        + "Interpret vague references — 'this', 'here', 'these numbers', 'why is it high' — as "
        + "referring to THIS screen and the figures on it. Answer in that context first. "
        + "If the user clearly asks about a different part of the tool, answer that instead, "
        + "but say which screen the answer comes from.\n"
        + _OUTPUT_CONTRACT
    )


def seed_history(screen: str, customer_id: str | None = None) -> list:
    return [{"role": "system", "content": system_prompt(screen, customer_id)}]


# ---------------------------------------------------------------------- briefs
# Every brief returns {"portfolio": [(label, value, tone)], "screen": [lines],
# "headline": str}. Tone is one of ok / warn / bad / neutral for the UI chip.


def _portfolio_snapshot() -> list:
    """The four figures that belong on every screen, whatever the user is doing."""
    q = dl.DEFAULT_QUARTER
    k = dl.compute_kpis(q)
    health = cd.compute_health_screen(q)
    band_tone = {"green": "ok", "amber": "warn", "red": "bad"}[health["band"]["tone"]]
    return [
        ("Health index", f"{health['score']:.0f}/100 · {health['band']['label']}", band_tone),
        ("Total EAD", dl.fmt_bn(k["total_ead"], 1), "neutral"),
        ("NPL ratio", f"{k['npl_ratio']:.1f}%", "warn" if k["npl_ratio"] > 4 else "ok"),
        ("Appetite breaches", str(k["breaches"]), "bad" if k["breaches"] else "ok"),
    ]


def _lines_cockpit(q):
    health = cd.compute_health_screen(q)
    matrix = cd.compute_sector_matrix(q)
    worst = matrix["rows"][0] if matrix["rows"] else None
    aq = health["asset_quality"]
    lines = [
        f"Index at **{health['score']:.0f}/100** ({health['band']['label']}), "
        f"held by **{aq['npl_ratio']:.1f}%** NPL and **{health['stage2_pct']:.1f}%** Stage 2.",
    ]
    if worst:
        lines.append(f"Weakest portfolio is **{worst['sector']}** — AI score **{worst['ai_score']:.0f}**, "
                     f"NPL **{worst['npl']:.1f}%**.")
    breaches = [r["label"] for r in health["appetite"] if r["status"] == "BREACH"]
    if breaches:
        lines.append(f"**{len(breaches)}** appetite limits breached: {', '.join(breaches)}.")
    return lines


def _lines_watchlist(q):
    board = dl.compute_watchlist_board(q, top_n_per_col=20)
    counts = board["counts"]
    total = sum(counts.values())
    busiest = max(counts, key=counts.get) if counts else None
    lines = [f"**{total}** names on the board across {len(counts)} stages."]
    if busiest:
        lines.append(f"Largest bucket is **{busiest}** with **{counts[busiest]}** names.")
    recovery = counts.get("Recovery", 0)
    if recovery:
        lines.append(f"**{recovery}** in Recovery — the impaired end of the book.")
    return lines


def _lines_stress(q):
    res = dl.compute_stress_scenario(q, rate_shock_bps=300, cre_price_shock_pct=20)
    return [
        "Reference shock shown: **+300bps** rates, **−20%** CRE.",
        f"ECL **{dl.fmt_mn(res['base_ecl'])} → {dl.fmt_mn(res['stressed_ecl'])}** "
        f"(**{dl.fmt_mn(res['ecl_delta'])}** added).",
        f"NPL **{res['base_npl_pct']:.1f}% → {res['stressed_npl_pct']:.1f}%**, CET1 impact "
        f"**{res['cet1_bps_impact']:.0f}bps**, **{res['covenant_breach_count']}** covenant breaches.",
    ]


def _lines_macro(q):
    health = dl.compute_portfolio_health(q)
    cur, horizon = health["current"], health["weighted_path"][-1]
    return [
        f"Current **{cur['npl']:.1f}%** NPL, **{cur['stage2']:.1f}%** Stage 2, "
        f"**{cur['coverage']:.1f}%** ECL coverage.",
        f"Probability-weighted 4Q path takes NPL to **{horizon['npl']:.1f}%** and Stage 2 to "
        f"**{horizon['stage2']:.1f}%**.",
        f"Health index projected at **{health['health_weighted']:.0f}/100**.",
    ]


def _lines_raroc(q):
    prof = dl.compute_profitability(q)
    rows, hurdle = prof["rows"], prof["hurdle"]
    below = sorted((r for r in rows if not r["above_hurdle"]), key=lambda r: r["raroc"])
    lines = [f"Hurdle **{hurdle:.0f}%** across **{len(rows)}** sectors."]
    if below:
        worst = below[0]
        lines.append(f"**{len(below)}** below hurdle, weakest **{worst['sector']}** at "
                     f"**{worst['raroc']:.1f}%** on {dl.fmt_bn(worst['ead'], 1)}.")
        lines.append(f"Below-hurdle exposure totals **{dl.fmt_bn(sum(r['ead'] for r in below), 1)}**.")
    else:
        lines.append("Every sector is clearing the hurdle.")
    return lines


def _lines_esg(_q):
    from backend.climate import store as climate_store
    _model, result, checks = climate_store.latest_result()
    grade = result["reference_grade"]
    at_grade = [r for r in result["grid"] if r["grade"] == grade]
    worst = max(at_grade, key=lambda r: r["multiple"]) if at_grade else None
    failing = sum(1 for c in checks if c["status"] == "FAIL")
    lines = [
        f"Horizon **{result['horizon_year']}**, calibrated k **{result['k']:.4f}**, "
        f"**{len(result['grid'])}** PD cells.",
    ]
    if worst:
        lines.append(f"Worst cell **{worst['sector']}** under **{worst['scenario']}** at grade {grade}: "
                     f"**{worst['multiple']:.2f}x** baseline.")
    lines.append(f"Quality checks: **{failing}** failing of **{len(checks)}**.")
    return lines


def _lines_brf(q):
    aq = dl.compute_brf_asset_quality(q)
    return [
        f"Reported book **{dl.fmt_aed_bn(aq['total_ead'], 1)}**, classified "
        f"**{dl.fmt_aed_bn(aq['classified_ead'], 1)}** (**{aq['classified_pct']:.1f}%**).",
        f"NPL **{aq['npl_pct']:.1f}%** with provision coverage **{aq['provision_coverage_npl']:.0f}%**.",
        f"General provisions **{dl.fmt_aed_mn(aq['general_provisions'])}** against a "
        f"**{dl.fmt_aed_mn(aq['min_general'])}** floor — "
        f"{'meets' if aq['general_ok'] else '**below**'} the 1.5% CRWA minimum.",
    ]


def _lines_reports(q):
    k = dl.compute_kpis(q)
    return [
        f"Pack would cover **{dl.fmt_bn(k['total_ead'], 1)}** EAD as of {dl._quarter_label(q)}.",
        f"Headline items: NPL **{k['npl_ratio']:.1f}%**, RAROC **{k['raroc']:.1f}%**, "
        f"**{k['breaches']}** appetite breaches.",
    ]


def _lines_b360(_q, customer_id=None):
    customer_id = customer_id or dl.DEFAULT_CUSTOMER
    p = dl.get_borrower_profile(customer_id, dl.DEFAULT_QUARTER)
    if not p:
        return ["No borrower selected."]
    lines = [
        f"**{p['borrower']}** — {p['sector']}, {p['region']} · {dl.fmt_bn(p['total_ead'], 2)} EAD "
        f"across **{p['account_count']}** facilities.",
        f"Rating **{p['risk_rating']}** (was {p['prev_risk_rating']}), Stage **{p['stage']}**, "
        f"severity **{p['severity']}**, PD **{p['pd12']:.2f}%**.",
        f"DSCR **{p['dscr']:.2f}x**, covenant headroom **{p['covenant_headroom']:.1f}%**, "
        f"RAROC **{p['raroc']:.1f}%**.",
    ]
    if p.get("trigger"):
        lines.append(f"Flagged: {p['trigger']} — recommended **{p['recommended_action']}**.")
    return lines


_LINE_BUILDERS = {
    COCKPIT: _lines_cockpit, "watchlist": _lines_watchlist,
    "stress": _lines_stress, "macro": _lines_macro, "raroc": _lines_raroc,
    "esg": _lines_esg, "brf": _lines_brf, "reports": _lines_reports,
}


def screen_brief(screen: str, customer_id: str | None = None) -> dict:
    """The opening brief: portfolio snapshot plus what is on this screen now.

    Every figure is computed here from the dataset, so the brief is instant and
    exact. A failure in one screen's builder degrades to a plain description
    rather than taking the drawer down with it.
    """
    q = dl.DEFAULT_QUARTER
    s = spec(screen)
    try:
        if screen == B360:
            lines = _lines_b360(q, customer_id)
        else:
            lines = _LINE_BUILDERS.get(screen, _lines_cockpit)(q)
    except Exception:  # noqa: BLE001 — a brief must never break the assistant
        lines = [f"This screen shows {s['shows']}."]

    return {
        "screen": screen,
        "label": s["label"],
        "as_of": dl._quarter_label(q),
        "portfolio": _portfolio_snapshot(),
        "lines": lines,
    }


# ------------------------------------------------------------------ suggestions

_SUGGESTIONS = {
    COCKPIT: ["Summarise portfolio health", "What's driving the health index?",
              "Which sector looks worst?", "Top 5 borrowers by EAD"],
    "watchlist": ["What's new on the watchlist?", "Which names are in Recovery?",
                  "Biggest exposure flagged RED", "What actions are due?"],
    "stress": ["Explain this stress result", "What breaks first under +300bps?",
               "How much ECL does a 20% CRE fall add?", "Reverse stress for -100bps CET1"],
    "macro": ["Summarise the macro outlook", "Which sectors are most rate-sensitive?",
              "What's the 4Q NPL path?", "How does oil feed the book?"],
    "raroc": ["Which sectors are below hurdle?", "Where is RAROC weakest?",
              "What's the EVA picture?", "Which deals should be repriced?"],
    "esg": ["Explain the stressed PD grid", "Which sector is worst under Net Zero?",
            "What do the quality checks say?", "How is k calibrated?"],
    "brf": ["Summarise the BRF return", "What's in the Substandard bucket?",
            "Which exposures are reportable?", "Explain the provisioning position"],
    "reports": ["What goes in the committee pack?", "Summarise this quarter for the board",
                "What changed since last quarter?", "Draft the executive summary"],
    B360: ["Summarise this borrower's risk", "Is a covenant breach likely?",
           "Which appetite limits do they sit in?", "What's the recommended action?"],
}


def suggestions(screen: str) -> list:
    return _SUGGESTIONS.get(screen, _SUGGESTIONS[COCKPIT])
