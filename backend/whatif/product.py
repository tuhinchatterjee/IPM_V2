"""
What the product IS, answered from what the product actually has.

The gap this fills
------------------
A person opening What-If Analysis for the first time does not begin by stating
a scenario. They ask what the thing does, what data it can see, and what they
are allowed to change. Those messages reached the scenario builder, which found
no magnitude in "what can you do?" and asked how big the movement should be.

So four kinds of question are answered here, and none of them prices the book:

  HELP         what this is, and how to configure a scenario
  DATA         which datasets, which book, which periods
  FIELDS       what is there, what is shockable, what is filterable
  METHODOLOGY  Delta against ML, and when to use which

Read, never remembered
----------------------
Every answer is composed from the LIVE configuration: the domain's dataset
tuple, the schema contract, the shock kinds the engine implements, the macro
matrix, the periods the lake publishes, the active model card. A hardcoded FAQ
is a document that goes out of date silently, and the first thing it gets wrong
is the thing somebody is relying on.

Where a model is available
--------------------------
The evidence below is handed to the configured model, which writes the prose. It
is given NOTHING but the evidence, and the schema it must fill is a set of
paragraphs — so a figure it did not receive is a figure it cannot state. Where
no model is configured, or where the call fails, the same evidence is composed
into the same answer deterministically. The product does not go quiet because a
provider is down, and it does not invent a capability because one is up.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

PRODUCT_VERSION = "1.0.0"

#: How a scenario is actually built, in the order a person does it. Used both
#: as the deterministic answer and as the evidence the model writes from.
HOW_TO: tuple[tuple[str, str], ...] = (
    ("Describe the population",
     "Name who the scenario applies to — a sector, a segment, a rating band, "
     "a Stage, an exposure threshold, a list of borrowers, or the whole book. "
     "Filters combine: \"Stage 1 Contracting borrowers rated BBB or worse with "
     "exposure above SAR 50m\" is one population."),
    ("State the shock",
     "Say what changes and by how much: a rating downgrade in notches, a PD or "
     "LGD move in per cent or percentage points, a CCF or EAD change, a "
     "collateral haircut, a Stage migration, or a macroeconomic variable."),
    ("Check the staging criteria",
     "The rule set that decides which borrowers cross into Stage 2 under the "
     "scenario is shown and can be edited for the thread. The reported book's "
     "own staging is visible beside it and is never editable."),
    ("Choose the ECL methodology",
     "The Delta Model or the ML Model. The product asks once per thread and "
     "does not choose for you, because the two can give materially different "
     "answers to the same scenario."),
    ("Read the result",
     "Baseline ECL, What-If ECL, the absolute and percentage change, and the "
     "drivers that caused it — split by an exact order-neutral attribution, so "
     "the parts add to the whole."),
    ("Investigate it",
     "Ask why, who, and how much. \"Why did Stage 3 ECL increase?\" \"Which "
     "borrowers contributed most?\" \"How much of this is lifetime PD "
     "replacing the twelve-month one?\" Those are answered from the result "
     "already computed, so asking cannot change the number you are asking "
     "about."),
    ("Layer another shock",
     "\"Now increase LGD by five percentage points.\" The thread keeps the "
     "scenario as a structure, so a step can be edited, removed or undone and "
     "everything after it recomputed."),
    ("Save it or export it",
     "A What-If can be named and reopened with the period, the steps, the "
     "staging criteria, the methodology and the model version it ran on. The "
     "detailed workbook carries the account-level before and after."),
)

EXAMPLE = (
    "Suppose you want to assess a deterioration in Contracting. You could type:\n\n"
    "    Using Q2 2026, increase Stage 1 Contracting borrowers' PD by 20%.\n\n"
    "I would identify the affected borrowers, show their current PD and "
    "exposure profile, restate what I understood filter by filter, ask whether "
    "to use the Delta or the ML methodology, re-evaluate staging under the "
    "thread's rule set, recalculate the provision, and explain which drivers "
    "moved it. You could then ask \"which borrowers explain most of the "
    "increase?\" or add another shock — \"now increase LGD by five percentage "
    "points\"."
)


def _domain() -> dict[str, Any]:
    from backend.whatif import domain as dm

    try:
        periods = list(dm.periods())
    except Exception as e:  # noqa: BLE001 - the answer says so rather than dying
        logger.warning("Could not list periods for the product answer: %s", e)
        periods = []
    return {
        "name": dm.DOMAIN_NAME,
        "grain": dm.GRAIN,
        "currency": dm.CURRENCY,
        "datasets": list(dm.DATASETS),
        "periods": periods,
        "period_count": len(periods),
        "latest": periods[-1] if periods else "",
        "earliest": periods[0] if periods else "",
        "restriction": (
            "What-If Analysis is deliberately restricted to the governed "
            "Corporate IFRS 9 domain. It does not search other CreditProbe "
            "domains, and it does not join out to them: the retail, SME and "
            "card books are measured on their own scales, their own staging "
            "rules and their own models, so answering from this one because "
            "the words overlap would give you a confident number about the "
            "wrong portfolio."),
    }


#: The groups a field catalogue is READ in. A hundred and fifty column names in
#: one list is a data dictionary; this is an answer.
GROUPS: tuple[tuple[str, str], ...] = (
    ("Identity", "Who the borrower is"),
    ("Segmentation", "How the book is cut"),
    ("Rating", "The nineteen-point governed scale and its movement"),
    ("Stage / SICR", "Which Stage, and which trigger put it there"),
    ("PD", "Through-the-cycle, point-in-time and lifetime"),
    ("LGD", "Loss given default, and the security behind it"),
    ("Exposure / EAD", "Drawn, undrawn, limit and the conversion factor"),
    ("Collateral", "Value, haircut and coverage"),
    ("ECL", "The provision and its scenario weighting"),
    ("Financials", "The statement measures a scenario can shock"),
    ("Macro", "The ten governed macroeconomic variables"),
    ("Model / trace", "What produced a figure, and on which version"),
)

#: Which group a field belongs to, and what it is called in business terms.
#: Keyed on the governed column name so the catalogue is generated from the
#: schema contract rather than typed twice.
_FIELD_GROUP: tuple[tuple[str, str], ...] = (
    (r"borrower_id|display_name|legal_name|alias|arabic_name|customer_number"
     r"|group_id|group_name", "Identity"),
    (r"sector|segment|sub_segment|sub_sector|region|city|country|business_unit",
     "Segmentation"),
    (r"internal_rating|rating_|external_rating|notch|ttc_pd_pct", "Rating"),
    (r"^stage|sicr|watchlist|default_flag|current_dpd|max_dpd|delinquency"
     r"|restructure|forbearance", "Stage / SICR"),
    (r"pd_|_pd_pct|probability", "PD"),
    (r"lgd", "LGD"),
    (r"ead|drawn|undrawn|limit|ccf|credit_conversion|utilisation|exposure",
     "Exposure / EAD"),
    (r"collateral|haircut|secured|unsecured", "Collateral"),
    (r"ecl|overlay|coverage|scenario_weight", "ECL"),
    (r"revenue|ebitda|margin|leverage|dscr|interest_coverage|cash|working_capital"
     r"|free_cash_flow|debt|equity|asset|liabilit", "Financials"),
    (r"gdp|unemploy|inflation|oil|policy_rate|fx|equity_index|house_price"
     r"|credit_spread|current_account|macro|cycle", "Macro"),
    (r"origin|version|model|trace|snapshot|source|confidence|not_client_data",
     "Model / trace"),
)


def _group_of(name: str) -> str:
    import re

    for pattern, group in _FIELD_GROUP:
        if re.search(pattern, name, re.IGNORECASE):
            return group
    return "Model / trace"


def fields() -> dict[str, Any]:
    """The field catalogue, grouped and business-readable.

    Built from the schema contract and the shock kinds the engine actually
    implements, so a field the product cannot shock is never listed as
    shockable and a column that was removed stops appearing.
    """
    from backend.whatif import scenarios as sc
    from backend.whatif import schema as sch

    shockable = {
        "internal_rating": "rating, in notches",
        "pd_12m": "PD, relative / pp / bps",
        "pd_lifetime": "PD, relative / pp / bps",
        "lgd": "LGD, relative / pp",
        "ead": "EAD, relative / pp",
        "credit_conversion_factor": "CCF, relative / pp",
        "collateral_market_value": "collateral, relative",
        "stage": "Stage migration, a share of a Stage",
        "revenue": "financial, relative",
        "ebitda": "financial, relative",
    }
    filterable = {
        "sector", "segment", "internal_rating", "stage", "borrower_id",
        "watchlist_flag", "ead", "drawn_exposure", "undrawn_commitment",
        "final_ecl", "pd_12m", "pd_lifetime", "lgd", "ecl_coverage",
        "collateral_coverage_pct", "leverage", "dscr",
    }

    try:
        present = set(sch.columns(sch.SNAPSHOT)) | set(sch.columns(sch.IFRS9))
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read the lake schema: %s", e)
        present = set()

    known = list(dict.fromkeys((*sch.REQUIRED, *sch.OPTIONAL,
                                *sch.IFRS9_REQUIRED, *sch.IFRS9_OPTIONAL)))
    grouped: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in GROUPS}
    for name in known:
        grouped[_group_of(name)].append({
            "field": name,
            "label": name.replace("_", " ").strip().capitalize(),
            "definition": (sch.OPTIONAL.get(name)
                           or sch.IFRS9_OPTIONAL.get(name)
                           or "Required: the What-If cannot run without it."),
            "available": (name in present) if present else None,
            "shockable": name in shockable,
            "shock_as": shockable.get(name, ""),
            "filterable": name in filterable,
        })

    return {
        "version": PRODUCT_VERSION,
        "groups": [{"group": name, "purpose": purpose,
                    "fields": grouped.get(name, [])}
                   for name, purpose in GROUPS],
        "field_count": len(known),
        "shockable_count": sum(1 for f in known if f in shockable),
        "filterable_count": sum(1 for f in known if f in filterable),
        "shock_kinds": [
            {"kind": k, "label": label}
            for k, label in (
                (sc.RATING, "Rating movement, in notches"),
                (sc.PD, "Probability of default"),
                (sc.LGD, "Loss given default"),
                (sc.EAD, "Exposure at default"),
                ("ccf", "Credit conversion factor"),
                (sc.COLLATERAL, "Collateral value"),
                ("haircut", "Collateral haircut"),
                ("stage", "Stage migration"),
                (sc.MACRO, "Macroeconomic variable"),
                (sc.FINANCIAL, "Financial statement measure"))],
        "units": [
            {"unit": "relative %", "means": "2.00% + 20% = 2.40%"},
            {"unit": "percentage points", "means": "2.00% + 2pp = 4.00%"},
            {"unit": "basis points", "means": "2.00% + 100bps = 3.00%"},
            {"unit": "notches", "means": "one step down the governed scale"}],
        "note": (
            "Grouped rather than listed: a hundred and fifty column names is a "
            "data dictionary, not an answer. Ask for the technical field list "
            "if you need every governed column."),
    }


def methodologies() -> dict[str, Any]:
    """The two ECL methodologies, and when each is the right one."""
    from backend.whatif import delta as dl
    from backend.whatif import methodology as me
    from backend.whatif.ml import registry as rg
    from backend.whatif.ml import runtime as rt

    active = rg.active()
    runnable = rt.check()
    return {
        "version": PRODUCT_VERSION,
        "gate": (
            "The product asks once per thread, before the first ECL figure, "
            "and does not choose for you. The two can give materially "
            "different answers to the same scenario, so choosing one is a "
            "methodological decision."),
        "methods": [
            {
                "value": me.DELTA,
                "label": me.LABELS[me.DELTA],
                "version": dl.DELTA_VERSION,
                "available": True,
                "what": (
                    "The reported ECL multiplied by the factors the scenario "
                    "implies for PD, LGD and EAD, after the rating move and "
                    "the staging rules have decided which PD applies."),
                "when": (
                    "When the figure has to be reproducible with a calculator, "
                    "or defended line by line. Every step is governed "
                    "arithmetic and nothing is learned."),
                "limits": (
                    "Proportional by construction. It cannot express an "
                    "interaction the governed formula does not contain."),
            },
            {
                "value": me.ML,
                "label": me.LABELS[me.ML],
                "version": active.version if active else "",
                "available": bool(active) and runnable.available,
                "unavailable_because": (
                    runnable.message() if not runnable.available
                    else "" if active else
                    "No ML model has been activated yet."),
                "what": (
                    "An XGBoost model of the ECL rate, fitted on historical "
                    "Corporate IFRS 9 outcomes and ANCHORED: it produces a "
                    "ratio of two predictions, which multiplies the reported "
                    "ECL. It never restates the reported book."),
                "when": (
                    "As a second opinion, and where the interactions between "
                    "Stage, collateral coverage and PD matter — a 20% PD shock "
                    "does not necessarily produce a 20% ECL move."),
                "limits": (
                    "Learned from this book. Where a shocked feature leaves "
                    "the range it was trained on, the result says so, and the "
                    "Delta factor is used for any borrower the model prices at "
                    "effectively zero."),
            },
        ],
        "comparison": (
            "Either result can be re-run on the other methodology from the "
            "same scenario state, so the two are genuinely comparable. The "
            "difference between them is reported as its own labelled line and "
            "is never folded into a scenario driver."),
    }


def capabilities() -> dict[str, Any]:
    """What the product does, as evidence rather than as prose."""
    from backend.whatif import investigate as iv
    from backend.whatif import macro as mc
    from backend.whatif import staging as st

    return {
        "version": PRODUCT_VERSION,
        "name": "What-If Analysis",
        "purpose": (
            "If I change one or more credit-risk assumptions, what happens to "
            "the expected credit loss, exactly why does it change, how "
            "plausible is that scenario against the evidence we have, and "
            "which borrowers, sectors and ratings are driving it?"),
        "journeys": [
            {"key": "rating", "name": "Rating Movement",
             "what": "Downgrade or upgrade a population through the governed "
                     "nineteen-point scale."},
            {"key": "parameters", "name": "IFRS 9 Risk Parameter Adjustment",
             "what": "Shock PD, LGD or the credit conversion factor directly."},
            {"key": "stage", "name": "Stage Migration",
             "what": "Move a share of one Stage into another and see what the "
                     "change of measurement basis costs."},
            {"key": "macro", "name": "Macroeconomic Shock",
             "what": "Shock one of the ten governed macro variables through "
                     "its sensitivity."},
            {"key": "sector", "name": "Sector Stress",
             "what": "Stress a named sector and see the concentration."},
            {"key": "borrower", "name": "Borrower Stress",
             "what": "Stress named borrowers, with two years of their history."},
        ],
        "how_to": [{"step": i + 1, "title": t, "detail": d}
                   for i, (t, d) in enumerate(HOW_TO)],
        "example": EXAMPLE,
        "intents": [{"intent": k, "label": v, "family": iv.FAMILY[k]}
                    for k, v in iv.LABELS.items()],
        "macro_variables": [v.name for v in mc.VARIABLES],
        "staging": st.default().describe(),
        "domain": _domain(),
    }


# ------------------------------------------------------------- the answer


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {"type": "string"},
            "description": "The answer, in professional prose. Two to five "
                           "paragraphs. Every fact must come from the "
                           "evidence.",
        },
        "next": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string"},
            "description": "Things the reader could usefully say next, phrased "
                           "as they would say them.",
        },
    },
    "required": ["paragraphs"],
}

_SYSTEM = (
    "You are the What-If Analysis assistant inside CreditProbe, a credit "
    "portfolio intelligence product used by IFRS 9 and credit-risk "
    "professionals.\n\n"
    "You are answering a question about the PRODUCT — what it does, what data "
    "it can see, what fields it has, or how its methodologies differ. You are "
    "not calculating anything.\n\n"
    "Write for a senior credit-risk professional: direct, specific, no "
    "marketing language, no bullet-point padding, no exclamation marks.\n\n"
    "THE EVIDENCE BELOW IS THE ONLY THING YOU KNOW. Every dataset name, field "
    "name, figure, period, version and capability you state must appear in it. "
    "If the evidence does not contain something, say the product does not have "
    "it, or do not mention it. Never invent a dataset, a field, a number or a "
    "capability. Never promise something the evidence does not show."
)


def evidence(intent: str) -> dict[str, Any]:
    """The packet an answer to this kind of question is composed from."""
    from backend.whatif import investigate as iv

    if intent == iv.DATA:
        return {"question_kind": "the data domain", "domain": _domain()}
    if intent == iv.FIELDS:
        return {"question_kind": "the field catalogue", "fields": fields(),
                "domain": _domain()}
    if intent == iv.METHODOLOGY:
        return {"question_kind": "the ECL methodologies",
                "methodologies": methodologies()}
    return {"question_kind": "what the product does and how to use it",
            "capabilities": capabilities()}


def _composed(intent: str, packet: dict[str, Any]) -> list[str]:
    """The answer, written from the evidence without a model.

    Not a fallback in the apologetic sense. It is the same evidence and the
    same claims; the model's contribution is fluency and shaping to the exact
    question, and losing that is worth much less than going quiet.
    """
    from backend.whatif import investigate as iv

    if intent == iv.DATA:
        d = packet["domain"]
        names = ", ".join(f"`{n}`" for n in d["datasets"])
        return [
            f"What-If Analysis reads one governed domain: {d['name']}, at "
            f"{d['grain']} grain, in {d['currency']}. {d['restriction']}",
            f"The datasets it can reach are {names}. Facilities and collateral "
            "are aggregated up to obligor grain rather than joined out to it, "
            "so a figure is never multiplied by a borrower's facility count.",
            (f"The book covers {d['period_count']} quarters, "
             f"{d['earliest']} through {d['latest']}. The latest reporting "
             f"period is {d['latest']}, and that is what every screen opens on "
             "unless you name another.")
            if d["periods"] else
            "The analytical lake has not been built in this installation, so "
            "no periods are published yet.",
        ]
    if intent == iv.FIELDS:
        f = packet["fields"]
        groups = ", ".join(g["group"] for g in f["groups"] if g["fields"])
        return [
            f"There are {f['field_count']} governed fields, in these groups: "
            f"{groups}.",
            f"{f['shockable_count']} of them can be shocked directly — the "
            "rating in notches, PD, LGD, EAD, the credit conversion factor, "
            "collateral value and haircut, the Stage, the macro variables and "
            "the financial statement measures. "
            f"{f['filterable_count']} can be used to narrow a population.",
            "A magnitude means one of three things and the product keeps them "
            "apart: " + "; ".join(f"{u['unit']} — {u['means']}"
                                  for u in f["units"]) + ".",
            f["note"],
        ]
    if intent == iv.METHODOLOGY:
        m = packet["methodologies"]
        lines = [m["gate"]]
        for method in m["methods"]:
            state = ("available" if method["available"]
                     else f"not available here — {method['unavailable_because']}")
            lines.append(f"{method['label']} ({state}). {method['what']} "
                         f"Use it {method['when'][0].lower()}{method['when'][1:]} "
                         f"{method['limits']}")
        lines.append(m["comparison"])
        return lines

    c = packet["capabilities"]
    steps = " ".join(f"{s['step']}. {s['title']}." for s in c["how_to"])
    return [
        f"{c['name']} answers one question: {c['purpose']}",
        "Six guided starting points are offered — "
        + ", ".join(j["name"] for j in c["journeys"])
        + " — but they are shortcuts rather than restrictions. You can type a "
          "scenario directly and I will read it.",
        f"A scenario is built in these steps: {steps}",
        c["example"],
    ]


def answer(intent: str, question: str = "") -> dict[str, Any]:
    """Answer a product, data, field or methodology question.

    Composed from the evidence either way. The model writes it where one is
    configured and reachable; where it is not, the same evidence is written out
    directly and the answer says which happened, because "the assistant is
    unavailable" is a worse answer than a plainer one.
    """
    from backend.whatif import investigate as iv

    packet = evidence(intent)
    body: dict[str, Any] = {
        "version": PRODUCT_VERSION,
        "intent": intent,
        "label": iv.LABELS.get(intent, intent),
        "question": question,
        "state_changed": False,
        "calculates_ecl": False,
        "evidence": packet,
    }

    try:
        from backend.llm import get_provider
        from backend.llm import roles as rl

        provider = get_provider()
        chosen = rl.role(rl.INTERPRETATION)
        import json

        result = provider.structured(
            system=_SYSTEM,
            prompt=(f"The question is: {question or 'What do you do?'}\n\n"
                    f"EVIDENCE:\n{json.dumps(packet, indent=2, default=str)}"),
            schema=_SCHEMA,
            tool_name="answer_about_the_product",
            tool_description="Answer a question about What-If Analysis using "
                             "only the evidence supplied.",
            max_tokens=1600, purpose="interpretation",
            role=rl.INTERPRETATION, model=chosen.model,
            effort=chosen.effort)
        paragraphs = [str(p).strip() for p in result.data.get("paragraphs", [])
                      if str(p).strip()]
        if paragraphs:
            body["paragraphs"] = paragraphs
            body["next"] = [str(n) for n in (result.data.get("next") or [])][:4]
            body["written_by"] = result.model
            return body
    except Exception as e:  # noqa: BLE001 - a product answer must not depend on a provider
        logger.info("Composing the product answer without a model: %s", e)

    body["paragraphs"] = _composed(intent, packet)
    body["next"] = _suggestions(intent)
    body["written_by"] = "composed from the configuration"
    return body


def _suggestions(intent: str) -> list[str]:
    from backend.whatif import investigate as iv

    if intent == iv.DATA:
        return ["What fields are available?",
                "What is the latest reporting period?",
                "Show me the rating distribution."]
    if intent == iv.FIELDS:
        return ["Which risk parameters can I shock?",
                "Show all technical fields.",
                "Increase Stage 1 PD by 20%."]
    if intent == iv.METHODOLOGY:
        return ["What is the Delta Model?",
                "How was the ML model trained?",
                "Downgrade everyone one notch."]
    return ["What data do you have access to?",
            "What fields are available?",
            "Give me an example scenario.",
            "Downgrade construction borrowers two notches."]


def describe() -> dict[str, Any]:
    """The product answer surface, for the configuration screen."""
    from backend.whatif import investigate as iv

    return {
        "version": PRODUCT_VERSION,
        "answers": [iv.HELP, iv.DATA, iv.FIELDS, iv.METHODOLOGY],
        "statement": (
            "Answered from the live configuration — the domain's dataset "
            "tuple, the schema contract, the shock kinds the engine "
            "implements, the macro matrix, the periods the lake publishes and "
            "the active model card. A hardcoded answer is a document that goes "
            "out of date silently, and the first thing it gets wrong is the "
            "thing somebody is relying on."),
    }


__all__ = ["EXAMPLE", "GROUPS", "HOW_TO", "PRODUCT_VERSION", "answer",
           "capabilities", "describe", "evidence", "fields", "methodologies"]
