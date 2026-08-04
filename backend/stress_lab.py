"""
Scenario Lab: named presets and the question memory behind them.

Two things make the lab usable rather than a blank prompt box:

  * `PRESETS` — named, pre-parameterised shocks. Free text is expressive but it
    is also a guessing game about what phrasing the parser understands; a preset
    is one click and states its own assumptions.
  * question memory — every question actually asked in the lab is recorded and
    offered back next time. It is the analyst's own working set, so it beats any
    list we could write for them.

The engine itself is unchanged: presets resolve to the same
(rate_shock_bps, cre_price_shock_pct) pair the free-text parser produces, so
there is exactly one stress path through `data_loader.compute_stress_scenario`.
"""

from backend import data_loader as dl

# ------------------------------------------------------------------- presets
# Calibrations are deliberately round numbers a committee can argue with, and
# each carries the reasoning that justifies its severity.

PRESETS = [
    {
        "id": "base",
        "label": "Reset to base",
        "detail": "No shock",
        "rate_shock_bps": 0,
        "cre_price_shock_pct": 0,
        "tone": "neutral",
        "rationale": "Clears the accumulated shocks and returns to the reported position.",
    },
    {
        "id": "rates_100",
        "label": "Rates +100bps",
        "detail": "Mild tightening",
        "rate_shock_bps": 100,
        "cre_price_shock_pct": 0,
        "tone": "amber",
        "rationale": "A single further hike. Tests sensitivity without a demand shock.",
    },
    {
        "id": "rates_300",
        "label": "Rates +300bps",
        "detail": "Sharp tightening",
        "rate_shock_bps": 300,
        "cre_price_shock_pct": 0,
        "tone": "amber",
        "rationale": "The standard supervisory rate shock; feeds CRE through the cap-rate model.",
    },
    {
        "id": "cre_25",
        "label": "CRE −25%",
        "detail": "Property correction",
        "rate_shock_bps": 0,
        "cre_price_shock_pct": 25,
        "tone": "amber",
        "rationale": "A price-only correction, isolating collateral and covenant effects.",
    },
    {
        "id": "stagflation",
        "label": "Stagflation",
        "detail": "+200bps · CRE −15%",
        "rate_shock_bps": 200,
        "cre_price_shock_pct": 15,
        "tone": "amber",
        "rationale": "Rates up while activity slows — the combination the book is least hedged for.",
    },
    {
        "id": "severe",
        "label": "Severe adverse",
        "detail": "+400bps · CRE −30%",
        "rate_shock_bps": 400,
        "cre_price_shock_pct": 30,
        "tone": "red",
        "rationale": "ICAAP-style severe-but-plausible: simultaneous rate and property shock.",
    },
]

PRESETS_BY_ID = {p["id"]: p for p in PRESETS}


def preset(preset_id: str) -> dict | None:
    return PRESETS_BY_ID.get(preset_id)


def apply_preset(preset_id: str, params: dict | None = None) -> dict:
    """Presets SET the scenario rather than adding to it.

    Free-text turns accumulate ("+100bps" then "another +200bps"), which is right
    for conversation but wrong for a named scenario: picking "Severe adverse"
    must mean severe adverse, not severe adverse on top of whatever was already
    there. `params` is accepted so the caller can pass current state without a
    special case, and deliberately ignored.
    """
    spec = preset(preset_id)
    if spec is None:
        return dict(params or {"rate_shock_bps": 0, "cre_price_shock_pct": 0})
    return {
        "rate_shock_bps": spec["rate_shock_bps"],
        "cre_price_shock_pct": spec["cre_price_shock_pct"],
        "preset_id": preset_id,
    }


def describe_params(params: dict | None) -> str:
    """One line naming the shock currently loaded, for the header strip."""
    params = params or {}
    rate = params.get("rate_shock_bps", 0) or 0
    cre = params.get("cre_price_shock_pct", 0) or 0
    if not rate and not cre:
        return "No shock applied — showing the reported position."
    bits = []
    if rate:
        bits.append(f"rates {rate:+.0f}bps")
    if cre:
        bits.append(f"CRE −{abs(cre):.0f}%")
    return "Active shock: " + " · ".join(bits)


def preset_reply(spec: dict, result: dict) -> str:
    """The console narrative when a preset is applied."""
    return (
        f"Loaded **{spec['label']}** ({spec['detail']}). {spec['rationale']} "
        f"Propagated through the MEV → IFRS 9 engine: scenario ECL "
        f"{dl.fmt_mn(result['stressed_ecl'])} "
        f"({'+' if result['ecl_delta'] >= 0 else ''}{dl.fmt_mn(result['ecl_delta'])}), "
        f"CET1 {result['cet1_bps_impact']:.0f}bps, NPL "
        f"{result['base_npl_pct']:.1f}% → {result['stressed_npl_pct']:.1f}%, "
        f"{result['covenant_breach_count']} borrowers projected to breach covenants."
    )


# --------------------------------------------------------------- question memory
# Seeded with a few starters so the lab is never empty on a first visit; the
# analyst's own questions then displace them, most recent first.

STARTER_QUESTIONS = [
    "What happens at +300bps?",
    "Model a 25% fall in real estate",
    "Which borrowers breach covenants first?",
    "How much ECL does stagflation add?",
]

MAX_REMEMBERED = 8
RECALL_LIMIT = 6


def record_question(recent: list | None, question: str) -> list:
    """Push a question onto the remembered list, most recent first.

    De-duplicated case-insensitively so repeatedly asking the same thing does not
    crowd out everything else, and capped so the list stays a shortlist rather
    than a transcript.
    """
    question = (question or "").strip()
    if not question:
        return list(recent or [])
    kept = [q for q in (recent or []) if q.strip().lower() != question.lower()]
    return ([question] + kept)[:MAX_REMEMBERED]


def recall_questions(recent: list | None, limit: int = RECALL_LIMIT) -> list:
    """What to offer as one-click chips: the analyst's own questions first, topped
    up with starters so there is always something to click."""
    out = []
    for q in (recent or []):
        q = (q or "").strip()
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
    for q in STARTER_QUESTIONS:
        if len(out) >= limit:
            break
        if q.lower() not in {x.lower() for x in out}:
            out.append(q)
    return out[:limit]
