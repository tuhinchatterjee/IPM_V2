"""
Local AI chat assistant for the IPM dashboard, backed by a locally-running
Qwen model via Ollama (http://localhost:11434). The model never sees the raw
dataset directly - instead it calls tools (defined below) that query
data_loader.py for real numbers, so every answer is grounded in the actual
portfolio data rather than the model's own (unreliable) memory.
"""


import requests

from backend import data_loader as dl
from backend.config import settings
from backend.services import ai_common

OLLAMA_URL = f"{settings.ollama_base_url}/api/chat"
OLLAMA_TAGS_URL = f"{settings.ollama_base_url}/api/tags"
MODEL = "qwen3.5"
# Local CPU inference for a ~10B model is slow (observed 60-130s per full exchange) -
# timeouts are generous on purpose rather than tuned for snappy cloud-API latency.
REQUEST_TIMEOUT = 180
HEALTH_CHECK_TIMEOUT = 2
MAX_TOOL_ROUNDS = 3
MAX_HISTORY_MESSAGES = 16  # trailing messages kept, to bound prompt growth/latency

UNAVAILABLE_MSG = (
    "The Qwen3.5 assistant isn't reachable right now. Make sure Ollama is running "
    f"(`ollama serve`) with the `{MODEL}` model pulled (`ollama pull {MODEL}`)."
)

# --------------------------------------------------------------------------- tools

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_overview",
            "description": (
                "Get the current portfolio-wide KPIs as of the latest quarter (Q1 2026): "
                "total EAD, NPL ratio, watchlist exposure, IFRS 9 stage 1/2/3 exposure, "
                "portfolio RAROC, and appetite breach count, each with the quarter-on-quarter change. "
                "Use this for any question about overall portfolio size, health, or risk-appetite status."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ai_signals",
            "description": (
                "Get the current AI early-warning risk signals (RED/AMBER severity facilities), "
                "each with the triggering reason and recommended action. Use this for questions "
                "about flagged borrowers, risk signals, watchlist triggers, or 'what needs attention'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["RED", "AMBER", "ANY"],
                        "description": "Filter to only this severity tier, or ANY for both.",
                    },
                    "limit": {"type": "integer", "description": "Max signals to return (default 10)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_borrower",
            "description": "Look up a borrower by (partial) name to find their Customer ID. Use this when unsure of the exact spelling or ID before calling get_borrower_profile.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Borrower name or partial name."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_borrower_profile",
            "description": (
                "Get the complete current profile for one borrower: exposure, PD, LGD, DSCR, "
                "rating (internal vs external), severity/trigger/recommended action, covenant "
                "headroom and breach projection, collateral coverage, FY24 vs FY25 financial ratio "
                "trends, and an AI-generated risk narrative. Use this for ANY question about a "
                "specific named borrower."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id_or_name": {
                        "type": "string",
                        "description": "Customer ID (e.g. CUS00002) or borrower name (e.g. Marina Bay Developments).",
                    },
                },
                "required": ["customer_id_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_borrowers",
            "description": "Get the top N borrowers by exposure (EAD) as of the latest quarter, with sector, rating, stage and trend.",
            "parameters": {
                "type": "object",
                "properties": {"n": {"type": "integer", "description": "How many to return (default 10)."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sector_breakdown",
            "description": "Get total EAD by economic sector (Real Estate, Contracting, Energy, Trade, etc.) as of the latest quarter.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_trend",
            "description": "Get the portfolio-wide Total ECL and Total EAD for each of the last N quarters, to answer questions about trends over time.",
            "parameters": {
                "type": "object",
                "properties": {"n_quarters": {"type": "integer", "description": "How many trailing quarters (default 4)."}},
                "required": [],
            },
        },
    },
]


def _tool_get_portfolio_overview():
    k = dl.compute_kpis(dl.DEFAULT_QUARTER)
    return {
        "as_of_quarter": dl.DEFAULT_QUARTER,
        "total_ead_usd_mn": round(k["total_ead"], 1),
        "ead_qoq_change_pct": round(k["ead_qoq_pct"], 2) if k["ead_qoq_pct"] is not None else None,
        "npl_ratio_pct": round(k["npl_ratio"], 2),
        "npl_qoq_change_pp": round(k["npl_delta"], 2) if k["npl_delta"] is not None else None,
        "watchlist_ead_usd_mn": round(k["watchlist_ead"], 1),
        "watchlist_pct_of_book": round(k["watchlist_pct"], 2),
        "stage1_ead_usd_mn": round(k["stage_ead"][1], 1),
        "stage2_ead_usd_mn": round(k["stage_ead"][2], 1),
        "stage2_qoq_change_usd_mn": round(k["stage2_delta"], 1) if k["stage2_delta"] is not None else None,
        "stage3_ead_usd_mn": round(k["stage_ead"][3], 1),
        "raroc_pct": round(k["raroc"], 2),
        "raroc_qoq_change_pp": round(k["raroc_delta"], 2) if k["raroc_delta"] is not None else None,
        "appetite_breaches": k["breaches"],
        "appetite_breaches_qoq_change": k["breach_delta"],
    }


def _tool_get_ai_signals(severity: str = "ANY", limit: int = 10):
    data = dl.compute_ai_signals(dl.DEFAULT_QUARTER, top_n=max(limit, 20))
    signals = data["signals"]
    if severity and severity != "ANY":
        signals = [s for s in signals if s["Severity"] == severity]
    signals = signals[:limit]
    return {
        "as_of_quarter": dl.DEFAULT_QUARTER,
        "red_count": data["red_count"],
        "amber_count": data["amber_count"],
        "newly_flagged_count": data["new_count"],
        "signals": [
            {
                "borrower": s["Borrower"],
                "severity": s["Severity"],
                "trigger": s["Trigger"],
                "recommended_action": s["Recommended Action"],
                "newly_flagged": s["is_new"],
            }
            for s in signals
        ],
    }


def _tool_search_borrower(query: str):
    matches = dl.find_customers(query, limit=5)
    if not matches:
        return {"matches": [], "note": "No borrower name matched that query."}
    return {"matches": matches}


def _tool_get_borrower_profile(customer_id_or_name: str):
    matches = dl.find_customers(customer_id_or_name, limit=1)
    if not matches:
        return {"error": f"No borrower found matching '{customer_id_or_name}'."}
    cid = matches[0]["customer_id"]
    quarter = dl.DEFAULT_QUARTER

    profile = dl.get_borrower_profile(cid, quarter)
    if profile is None:
        return {"error": f"No data for {cid} at {quarter}."}

    ratios = dl.compute_borrower_ratios(cid)
    rating = dl.compute_rating_reconciliation(cid, quarter)
    covenant = dl.compute_covenant_projection(cid, quarter)
    collateral = dl.compute_collateral_coverage(cid, quarter)
    insight = dl.generate_ai_insight(cid, quarter)

    return {
        "as_of_quarter": quarter,
        "customer_id": cid,
        "borrower": profile["borrower"],
        "sector": profile["sector"],
        "region": profile["region"],
        "relationship_manager": profile["owner"],
        "ead_usd_mn": round(profile["total_ead"], 1),
        "pd_12m_pct": round(profile["pd12"], 3),
        "lgd_pct": round(profile["lgd_pct"], 1),
        "dscr_x": round(profile["dscr"], 2),
        "covenant_headroom_pct": round(profile["covenant_headroom"], 1),
        "raroc_pct": round(profile["raroc"], 2),
        "internal_rating": profile["risk_rating"],
        "previous_rating": profile["prev_risk_rating"],
        "external_rating": rating["external_rating"],
        "rating_notch_gap": rating["notch_gap"],
        "ifrs9_stage": profile["stage"],
        "severity": profile["severity"],
        "trigger": profile["trigger"],
        "recommended_action": profile["recommended_action"],
        "ai_risk_score": profile["ai_risk_score"],
        "watchlist": profile["watchlist"],
        "npl": profile["npl"],
        "trend": profile["trend"],
        "financial_ratios_fy24_vs_fy25": ratios,
        "covenant_headroom_current_pct": covenant["current"],
        "covenant_likely_breach": covenant["likely_breach"],
        "collateral_coverage_x": round(collateral["coverage"], 2) if collateral["coverage"] is not None else None,
        "collateral_valuation_months_stale": collateral["months_stale"],
        "ai_insight": insight["text"],
    }


def _tool_get_top_borrowers(n: int = 10):
    rows = dl.compute_top_borrowers(dl.DEFAULT_QUARTER, top_n=n)
    return {
        "as_of_quarter": dl.DEFAULT_QUARTER,
        "borrowers": [
            {
                "borrower": r["Borrower"], "sector": r["Sector"], "ead_usd_mn": round(r["EAD"], 1),
                "rating": r["Risk Rating"], "ifrs9_stage": r["IFRS 9 Stage"], "trend": r["Trend"],
            }
            for r in rows
        ],
    }


def _tool_get_sector_breakdown():
    rows = dl.compute_top_sectors(dl.DEFAULT_QUARTER, top_n=12)
    return {
        "as_of_quarter": dl.DEFAULT_QUARTER,
        "sectors": [{"sector": r["sector"], "ead_usd_mn": round(r["ead"], 1)} for r in rows],
    }


def _tool_get_portfolio_trend(n_quarters: int = 4):
    rows = dl.compute_ecl_trend(dl.DEFAULT_QUARTER, n_quarters=n_quarters)
    return {
        "quarters": [
            {"quarter": r["label"], "total_ecl_usd_mn": round(r["total_ecl"], 1), "total_ead_usd_mn": round(r["total_ead"], 1)}
            for r in rows
        ],
    }


TOOL_FUNCS = {
    "get_portfolio_overview": _tool_get_portfolio_overview,
    "get_ai_signals": _tool_get_ai_signals,
    "search_borrower": _tool_search_borrower,
    "get_borrower_profile": _tool_get_borrower_profile,
    "get_top_borrowers": _tool_get_top_borrowers,
    "get_sector_breakdown": _tool_get_sector_breakdown,
    "get_portfolio_trend": _tool_get_portfolio_trend,
}

# ------------------------------------------------------------------------ prompts

_BASE_SYSTEM = (
    "You are the IPM AI Assistant, embedded in the Intelligent Portfolio Manager - a bank's "
    "GCC wholesale/retail credit portfolio risk dashboard. The portfolio has ~390 borrowers "
    "across quarterly snapshots from Q4 2023 to Q1 2026 (the current/latest quarter). "
    "You MUST call a tool to fetch real data for ANY question involving portfolio numbers, "
    "KPIs, AI risk signals, sectors, or borrowers - never guess or invent a figure. "
    "If a tool returns an error or no match, say so plainly rather than making something up. "
    "Answer concisely (2-5 sentences unless asked for a list/table), cite the real figures "
    "returned by tools, and use $ and % formatting naturally (e.g. $48.6bn, 3.8%)."
    + ai_common.INJECTION_GUARD
)


def system_prompt_cockpit() -> str:
    return _BASE_SYSTEM + (
        " You are currently shown on the Executive Portfolio Risk Cockpit (portfolio-wide overview)."
    )


def system_prompt_borrower(customer_id: str) -> dict | str:
    profile = dl.get_borrower_profile(customer_id, dl.DEFAULT_QUARTER)
    if profile is None:
        return _BASE_SYSTEM
    return _BASE_SYSTEM + (
        f" You are currently shown on the Borrower 360 page for {profile['borrower']} (ID {customer_id}), "
        f"sector {profile['sector']}, region {profile['region']}, severity {profile['severity']}. "
        "Prefer get_borrower_profile for questions about 'this borrower' / 'them' - pass "
        f"'{customer_id}' as the id. Use other tools for portfolio-wide or different-borrower questions."
    )


# --------------------------------------------------------------------------- chat

@ai_common.retry_ollama
def _ollama_call(messages: list) -> dict:
    payload = {"model": MODEL, "messages": messages, "tools": TOOLS, "stream": False, "think": False}
    resp = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def chat(messages: list) -> tuple:
    """Runs the tool-calling loop against the local Ollama model.

    `messages` is the full conversation so far, INCLUDING the system prompt and the
    latest user message, but NOT yet the assistant's reply. Returns
    (reply_text, new_messages_to_append) where new_messages_to_append are the
    assistant/tool messages generated this turn (append them to persisted history).
    """
    working = list(messages)
    appended = []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            data = _ollama_call(working)
            msg = data["message"]
            working.append(msg)
            appended.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg.get("content") or "(no response)", appended

            for tc in tool_calls:
                name = tc["function"]["name"]
                args = tc["function"].get("arguments") or {}
                func = TOOL_FUNCS.get(name)
                try:
                    result = func(**args) if func else {"error": f"Unknown tool '{name}'"}
                except Exception as exc:  # noqa: BLE001 - surface to the model, not a crash
                    result = {"error": str(exc)}
                tool_msg = {"role": "tool", "content": ai_common.format_tool_result(result)}
                working.append(tool_msg)
                appended.append(tool_msg)

        # Ran out of tool-call rounds - ask once more for a final answer, no more tools.
        data = _ollama_call(working)
        msg = data["message"]
        appended.append(msg)
        return msg.get("content") or "(no response)", appended

    except requests.exceptions.RequestException:
        return UNAVAILABLE_MSG, []


def is_available() -> bool:
    try:
        requests.get(OLLAMA_TAGS_URL, timeout=HEALTH_CHECK_TIMEOUT)
        return True
    except requests.exceptions.RequestException:
        return False


def trim_history(messages: list) -> list:
    """Keeps the system prompt plus the trailing N messages, to bound prompt growth."""
    if not messages:
        return messages
    system = messages[0] if messages[0].get("role") == "system" else None
    rest = messages[1:] if system else messages
    rest = rest[-MAX_HISTORY_MESSAGES:]
    return ([system] if system else []) + rest
