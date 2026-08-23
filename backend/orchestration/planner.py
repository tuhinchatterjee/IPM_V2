"""
The planner — question in, plan out. The only step where a model may exercise
judgement about *what* to compute.

Two implementations, one contract:

  DemoPlanner       deterministic. Reads the question against a catalogue of
                    credit-risk intents and selects registered analyses. Used
                    whenever no model key is configured.
  AnthropicPlanner  asks a language model for the same structured plan.

They are interchangeable because neither is trusted. Whatever comes back goes
through validator.validate_plan() before a single row is read, so the difference
between them is the quality of the question-reading — never the safety of the
result.

What DEMO_MODE is, and is not
-----------------------------
DEMO_MODE replaces the *planner*, not the engine. Every figure still comes from
executing real registered analyses against the real published data. Nothing on
this path returns a stored answer, and no credit figure appears anywhere in this
file.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.config import settings
from backend.orchestration.schema import MAX_PLAN_STEPS, AnalysisPlan, PlanStep
from backend.orchestration.vocabulary import Vocabulary, get_vocabulary

logger = logging.getLogger(__name__)

# The model used when a key is configured. Pinned rather than "latest" so a
# provider-side change cannot alter how IPM reads a question without a release.
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"


# ---------------------------------------------------------------------------
# Intent catalogue — the deterministic reading of a credit-risk question
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Intent:
    """One recognised kind of question, and the analyses that answer it."""

    id: str
    # Regular expressions searched in the lower-cased question. Each match adds
    # its weight; the highest total wins. Weights let a specific phrase ("rating
    # transition matrix") beat a general one ("rating").
    patterns: list[tuple[str, int]]
    intent_text: str
    build: str  # name of the builder method on DemoPlanner
    follow_ups: list[str]


INTENTS: list[Intent] = [
    Intent(
        id="stage2_increase",
        patterns=[
            (r"stage\s*(2|two)", 5),
            (r"increas|ris(e|en|ing)|grow|up\b|higher|worse", 3),
            (r"why", 2),
        ],
        intent_text="Explain the movement in Stage 2 exposure and identify what drove it.",
        build="_stage2",
        follow_ups=[
            "Which sectors deteriorated the most?",
            "Show me the top ten deteriorating borrowers.",
            "How has ECL changed?",
        ],
    ),
    Intent(
        id="sector_deterioration",
        patterns=[
            (r"which sector|what sector|sectors?\b", 4),
            (r"deteriorat|worst|worsen|most|weakest|declin", 3),
        ],
        intent_text="Rank sectors by deterioration and show where exposure is concentrated.",
        build="_sector_deterioration",
        follow_ups=[
            "Show me the top ten deteriorating borrowers.",
            "Stress the worst sector.",
            "Why has Stage 2 increased?",
        ],
    ),
    Intent(
        id="rating_transition",
        patterns=[
            (r"transition matrix|rating transition|migration matrix", 8),
            (r"\brating\b", 3),
            (r"migrat", 2),
        ],
        intent_text="Produce the empirical rating transition matrix between two reporting periods.",
        build="_rating_transition",
        follow_ups=[
            "Show me the top ten deteriorating borrowers.",
            "How has ECL changed?",
            "What deteriorated this period?",
        ],
    ),
    Intent(
        id="top_deteriorating",
        patterns=[
            (r"top\s*(ten|10|\d+)", 4),
            (r"deteriorat", 4),
            (r"borrower|obligor|name|counterpart", 3),
            (r"watch\s?list|requires? attention", 2),
        ],
        intent_text="List the borrowers whose credit position worsened most against the prior period.",
        build="_top_deteriorating",
        follow_ups=[
            "Which sectors deteriorated the most?",
            "Why has Stage 2 increased?",
            "Stress the Real Estate portfolio.",
        ],
    ),
    Intent(
        id="stress",
        patterns=[
            (r"stress|shock|downturn|scenario|what if|adverse", 6),
            (r"sensitiv", 3),
        ],
        intent_text="Apply a downturn scenario and size the incremental impairment.",
        build="_stress",
        follow_ups=[
            "Which sectors deteriorated the most?",
            "How has ECL changed?",
            "Show me the rating transition matrix.",
        ],
    ),
    Intent(
        id="ecl_change",
        patterns=[
            (r"\becl\b|impairment|provision|allowance", 5),
            (r"chang|mov|increas|decreas|how has|why", 3),
        ],
        intent_text="Attribute the movement in expected credit loss between two reporting periods.",
        build="_ecl_change",
        follow_ups=[
            "Which sectors deteriorated the most?",
            "Why has Stage 2 increased?",
            "Show me the top ten deteriorating borrowers.",
        ],
    ),
    Intent(
        id="concentration",
        patterns=[
            (r"concentrat|largest|biggest|exposure by|where is.*risk", 5),
            (r"herfindahl|hhi", 4),
        ],
        intent_text="Measure where exposure is concentrated and how much sits in the largest groups.",
        build="_concentration",
        follow_ups=[
            "Stress the Real Estate portfolio.",
            "Which sectors deteriorated the most?",
            "What deteriorated this period?",
        ],
    ),
    Intent(
        id="arrears",
        patterns=[(r"\bdpd\b|past due|arrears|days? past|delinquen", 6)],
        intent_text="Show the movement between days-past-due buckets.",
        build="_arrears",
        follow_ups=[
            "Show me the top ten deteriorating borrowers.",
            "Why has Stage 2 increased?",
            "How has ECL changed?",
        ],
    ),
    Intent(
        id="utilisation",
        patterns=[(r"utilis|utiliz|drawn|undrawn|limit|revolv", 6)],
        intent_text="Identify facilities drawing unusually heavily on their committed limits.",
        build="_utilisation",
        follow_ups=[
            "Show me the top ten deteriorating borrowers.",
            "What deteriorated this period?",
            "Stress the Real Estate portfolio.",
        ],
    ),
    Intent(
        id="trend",
        patterns=[(r"trend|over time|history|historic|last (few|several|three|3)|quarters", 5)],
        intent_text="Show how the portfolio has moved across every available reporting period.",
        build="_trend",
        follow_ups=[
            "What deteriorated this period?",
            "How has ECL changed?",
            "Which sectors deteriorated the most?",
        ],
    ),
    Intent(
        id="staging",
        patterns=[(r"stag(e|ing)\s*(distribution|split|mix|breakdown)|ifrs\s*9", 5), (r"\bstage\b", 2)],
        intent_text="Show how exposure is distributed across IFRS 9 stages.",
        build="_staging",
        follow_ups=[
            "Why has Stage 2 increased?",
            "Which sectors deteriorated the most?",
            "How has ECL changed?",
        ],
    ),
    Intent(
        id="deterioration_overview",
        patterns=[
            (r"deteriorat|what changed|what has changed|got worse|worsen", 5),
            (r"this (period|quarter)|since last", 3),
        ],
        intent_text="Establish what moved against the prior period and identify the drivers.",
        build="_deterioration_overview",
        follow_ups=[
            "Why has Stage 2 increased?",
            "Which sectors deteriorated the most?",
            "Show me the top ten deteriorating borrowers.",
        ],
    ),
    Intent(
        id="overview",
        patterns=[(r"overview|summary|how is|health|position|state of|where do we stand", 5)],
        intent_text="Summarise the current portfolio position and how it has moved.",
        build="_overview",
        follow_ups=[
            "What deteriorated this period?",
            "Which sectors deteriorated the most?",
            "Show me the rating transition matrix.",
        ],
    ),
]

SCENARIO_WORDS = {
    "base": "base",
    "mild": "mild",
    "moderate": "moderate",
    "severe": "severe",
    "extreme": "severe",
    "harsh": "severe",
    "light": "mild",
}

WORD_NUMBERS = {
    "three": 3, "five": 5, "six": 6, "eight": 8, "ten": 10,
    "twelve": 12, "fifteen": 15, "twenty": 20, "twentyfive": 25,
}


# ---------------------------------------------------------------------------
# The deterministic planner
# ---------------------------------------------------------------------------


class DemoPlanner:
    """Reads a question deterministically and selects registered analyses.

    Deterministic does not mean canned. The planner chooses *which* analyses to
    run and *with what parameters*; the answer is then computed by executing
    them against live data. Ask the same question after publishing a new period
    and the numbers change, because they were never stored here.
    """

    name = "demo"
    model_name = None

    def plan(self, question: str, vocab: Vocabulary | None = None) -> AnalysisPlan:
        vocab = vocab or get_vocabulary()
        text = question.strip()
        lowered = text.lower()

        intent, score = self._best_intent(lowered)
        dimension_hit = vocab.resolve_dimension_value(text)
        filters: dict[str, Any] = {}
        notes: list[str] = []
        if dimension_hit:
            dimension, value = dimension_hit
            filters = {dimension: value}
            notes.append(f"Restricted to {dimension.replace('_', ' ')} = {value}.")

        builder = getattr(self, intent.build)
        steps: list[PlanStep] = builder(lowered, vocab, filters)
        steps = steps[:MAX_PLAN_STEPS]

        unmatched = score == 0
        if unmatched:
            notes.insert(
                0,
                "IPM did not recognise a specific analytical question here, so it has run "
                "the standard portfolio review instead. Try one of the suggestions below, "
                "or name a sector, a stage, a rating or a scenario.",
            )

        intent_text = intent.intent_text
        if dimension_hit and not unmatched:
            intent_text = f"{intent_text.rstrip('.')}, restricted to {dimension_hit[1]}."

        return AnalysisPlan(
            question=text,
            intent=intent_text,
            steps=steps,
            planner=self.name,
            model_name=self.model_name,
            follow_ups=intent.follow_ups,
            unmatched=unmatched,
            notes=notes,
        )

    # ------------------------------------------------------------- matching

    def _best_intent(self, lowered: str) -> tuple[Intent, int]:
        best, best_score = INTENTS[-1], 0
        for intent in INTENTS:
            score = sum(w for pattern, w in intent.patterns if re.search(pattern, lowered))
            # A single weak keyword is not a reading of a question. Requiring a
            # real signal is what makes "unmatched" honest rather than a
            # confident guess.
            if score >= 5 and score > best_score:
                best, best_score = intent, score
        return best, best_score

    def _top_n(self, lowered: str, default: int) -> int:
        match = re.search(r"top\s*(\d+)", lowered)
        if match:
            return max(1, min(100, int(match.group(1))))
        match = re.search(r"top\s*([a-z]+)", lowered)
        if match and match.group(1) in WORD_NUMBERS:
            return WORD_NUMBERS[match.group(1)]
        return default

    def _scenario(self, lowered: str) -> str:
        for word, scenario in SCENARIO_WORDS.items():
            if re.search(rf"\b{word}\b", lowered):
                return scenario
        return "moderate"

    # ------------------------------------------------------------- builders
    # Each returns the ordered list of registered analyses that answers the
    # question. Parameters are named exactly as the contracts declare them; the
    # validator checks that claim rather than trusting it.

    def _overview(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("portfolio_summary", "Portfolio position",
                     "Establishes the current size, staging and coverage of the book, "
                     "and how each has moved against the prior period.",
                     params={"period": "latest", "compare_period": "previous"}, filters=filters),
            PlanStep("stage_distribution", "IFRS 9 staging",
                     "Shows how exposure and impairment are distributed across stages.",
                     params={"period": "latest", "group_by": "none"}, filters=filters),
            PlanStep("portfolio_trend", "Direction of travel",
                     "Places the current position in the context of every prior period.",
                     params={}, filters=filters),
        ]

    def _deterioration_overview(self, lowered: str, vocab: Vocabulary,
                                filters: dict) -> list[PlanStep]:
        return [
            PlanStep("portfolio_summary", "What moved",
                     "Quantifies the change in exposure, staging and coverage since the "
                     "prior reporting period.",
                     params={"period": "latest", "compare_period": "previous"}, filters=filters),
            PlanStep("stage_migration", "Stage migration",
                     "Shows the exposure that moved between IFRS 9 stages, which is where "
                     "deterioration first becomes visible.",
                     params={"from_period": "previous", "to_period": "latest", "basis": "ead"},
                     filters=filters),
            PlanStep("ecl_movement", "Where the impairment moved",
                     "Attributes the change in expected credit loss by sector.",
                     params={"from_period": "previous", "to_period": "latest",
                             "group_by": "sector"}, filters=filters),
            PlanStep("top_deteriorating_borrowers", "Names behind the movement",
                     "Identifies the individual borrowers driving the deterioration.",
                     params={"from_period": "previous", "to_period": "latest", "top_n": 10},
                     filters=filters),
        ]

    def _stage2(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("stage_distribution", "Current staging",
                     "Establishes how much exposure now sits in Stage 2, by sector.",
                     params={"period": "latest", "group_by": "sector"}, filters=filters),
            PlanStep("stage_migration", "What moved into Stage 2",
                     "Isolates the exposure that migrated between stages, rather than the "
                     "net change, so the gross movement is visible.",
                     params={"from_period": "previous", "to_period": "latest", "basis": "ead"},
                     filters=filters),
            PlanStep("top_deteriorating_borrowers", "Borrowers behind the migration",
                     "Names the obligors whose position worsened, with the reason recorded "
                     "for each.",
                     params={"from_period": "previous", "to_period": "latest", "top_n": 10},
                     filters=filters),
            PlanStep("ecl_movement", "Impairment consequence",
                     "Shows what the migration did to expected credit loss.",
                     params={"from_period": "previous", "to_period": "latest",
                             "group_by": "sector"}, filters=filters),
        ]

    def _sector_deterioration(self, lowered: str, vocab: Vocabulary,
                              filters: dict) -> list[PlanStep]:
        return [
            PlanStep("ecl_movement", "Deterioration by sector",
                     "Attributes the change in expected credit loss to the sectors that "
                     "caused it.",
                     params={"from_period": "previous", "to_period": "latest",
                             "group_by": "sector"}, filters=filters),
            PlanStep("stage_distribution", "Staging by sector",
                     "Shows which sectors carry the highest share of Stage 2 and Stage 3 "
                     "exposure.",
                     params={"period": "latest", "group_by": "sector"}, filters=filters),
            PlanStep("sector_concentration", "Exposure at risk",
                     "Sizes the exposure sitting in each sector, so a large percentage "
                     "movement on a small book is not mistaken for a material one.",
                     params={"period": "latest", "dimension": "sector", "top_n": 15},
                     filters=filters),
        ]

    def _rating_transition(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        basis = "count" if re.search(r"count|number of|borrower count", lowered) else "ead"
        return [
            PlanStep("rating_transition_matrix", "Rating transition matrix",
                     "Empirical transition probabilities between the two reporting periods, "
                     f"measured on {'borrower count' if basis == 'count' else 'exposure'}.",
                     params={"from_period": "previous", "to_period": "latest", "basis": basis},
                     filters=filters),
        ]

    def _top_deteriorating(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("top_deteriorating_borrowers", "Deteriorating borrowers",
                     "Ranks borrowers by the severity of their deterioration against the "
                     "prior period, with the reasons recorded for each.",
                     params={"from_period": "previous", "to_period": "latest",
                             "top_n": self._top_n(lowered, 10)}, filters=filters),
        ]

    def _stress(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        params: dict[str, Any] = {"period": "latest", "scenario": self._scenario(lowered)}
        # stress_scenario_basic takes the sector as a declared parameter, so a
        # sector mentioned in the question belongs there rather than in filters.
        sector = filters.get("sector")
        remaining = {k: v for k, v in filters.items() if k != "sector"}
        if isinstance(sector, str):
            params["sector"] = sector
        return [
            PlanStep("stress_scenario_basic", "Scenario impact",
                     "Applies the scenario's shocks to the reported position and sizes the "
                     "incremental impairment.",
                     params=params, filters=remaining),
            PlanStep("sector_concentration", "Exposure under stress",
                     "Shows how much exposure the scenario is being applied to.",
                     params={"period": "latest", "dimension": "sector", "top_n": 15},
                     filters=remaining),
        ]

    def _ecl_change(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("ecl_movement", "ECL movement",
                     "Attributes the change in expected credit loss between the two "
                     "reporting periods.",
                     params={"from_period": "previous", "to_period": "latest",
                             "group_by": "sector"}, filters=filters),
            PlanStep("portfolio_summary", "Coverage context",
                     "Places the movement against the size of the book, so a change in "
                     "coverage is separated from a change in exposure.",
                     params={"period": "latest", "compare_period": "previous"}, filters=filters),
            PlanStep("stage_migration", "Staging driver",
                     "Shows the stage migration that the impairment movement follows from.",
                     params={"from_period": "previous", "to_period": "latest", "basis": "ead"},
                     filters=filters),
        ]

    def _concentration(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        dimension = "sector"
        for candidate in ("region", "segment", "product_type", "rating_bucket", "country"):
            if re.search(candidate.replace("_", "[ _]?"), lowered):
                dimension = candidate
                break
        return [
            PlanStep("sector_concentration", "Concentration",
                     f"Measures how exposure is distributed across {dimension.replace('_', ' ')} "
                     "and how much sits in the largest groups.",
                     params={"period": "latest", "dimension": dimension,
                             "top_n": self._top_n(lowered, 15)}, filters=filters),
            PlanStep("stage_distribution", "Quality of the concentrations",
                     "Shows the staging inside each group, so a large exposure and a poor "
                     "one can be told apart.",
                     params={"period": "latest", "group_by": dimension}, filters=filters),
        ]

    def _arrears(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("dpd_migration", "Arrears movement",
                     "Shows the exposure moving between days-past-due buckets.",
                     params={"from_period": "previous", "to_period": "latest", "basis": "ead"},
                     filters=filters),
            PlanStep("top_deteriorating_borrowers", "Borrowers in arrears",
                     "Names the borrowers whose position worsened.",
                     params={"from_period": "previous", "to_period": "latest", "top_n": 10},
                     filters=filters),
        ]

    def _utilisation(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("high_utilisation_watchlist", "High utilisation",
                     "Lists facilities drawing unusually heavily on their committed limits, "
                     "which often precedes a stage migration.",
                     params={"period": "latest", "threshold_pct": 90.0,
                             "top_n": self._top_n(lowered, 20)}, filters=filters),
        ]

    def _trend(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("portfolio_trend", "Portfolio trend",
                     "Tracks exposure, staging and coverage across every available "
                     "reporting period.",
                     params={}, filters=filters),
            PlanStep("portfolio_summary", "Latest position",
                     "The current position the trend ends at.",
                     params={"period": "latest", "compare_period": "previous"}, filters=filters),
        ]

    def _staging(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("stage_distribution", "IFRS 9 staging",
                     "Exposure, impairment and coverage by stage.",
                     params={"period": "latest", "group_by": "sector"}, filters=filters),
            PlanStep("stage_migration", "Stage migration",
                     "The exposure that moved between stages since the prior period.",
                     params={"from_period": "previous", "to_period": "latest", "basis": "ead"},
                     filters=filters),
        ]


# ---------------------------------------------------------------------------
# The model-backed planner
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are the planning component of IPM, a credit-risk analytical platform used by \
bank risk officers.

Your ONLY job is to choose which of IPM's registered analytical functions should \
run to answer the user's question, and with which parameters.

Hard rules:
- You must NEVER calculate, estimate, or state any credit figure. You have no data.
- You may only name analyses from the supplied library. Nothing else exists.
- You may only supply parameters that the named analysis declares, using the \
declared allowed values.
- You may only filter on the supplied dimensions, using values that appear in the \
supplied lists.
- Choose between one and {max_steps} analyses. Fewer, well-chosen steps are better.
- Do not explain your reasoning process. Give only the plan.

Reply with a single JSON object and nothing else:

{{"intent": "<one sentence restating what the user is asking, in IPM's terms>",
  "steps": [{{"analysis_id": "...", "title": "<short heading for this result>",
             "rationale": "<one sentence: why this analysis>",
             "params": {{...}}, "filters": {{...}}}}],
  "follow_ups": ["<question the user could ask next>", "..."],
  "unmatched": false}}

Set "unmatched" to true and still return a sensible general plan if the question \
is not something the library can answer.
"""


class AnthropicPlanner:
    """Plans with a language model. Used only when a key is configured.

    The model receives the analysis library and the governed vocabulary — never
    the data. It returns a plan, which the validator then treats exactly as
    sceptically as it treats the deterministic one.
    """

    name = "anthropic"

    def __init__(self, api_key: str, model_name: str = DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self.model_name = model_name

    def plan(self, question: str, vocab: Vocabulary | None = None) -> AnalysisPlan:
        vocab = vocab or get_vocabulary()
        fallback = DemoPlanner()
        try:
            payload = self._ask(question, vocab)
        except Exception as e:
            # A model outage must not take the product down. The deterministic
            # planner answers instead, and the response says so.
            logger.warning("Model planning failed (%s); falling back to the demo planner.", e)
            plan = fallback.plan(question, vocab)
            return AnalysisPlan(
                question=plan.question, intent=plan.intent, steps=plan.steps,
                planner="demo-fallback", model_name=self.model_name,
                follow_ups=plan.follow_ups, unmatched=plan.unmatched,
                notes=[*plan.notes, "The configured model was unavailable, so IPM planned "
                                    "this investigation deterministically."],
            )

        steps = [PlanStep.from_dict(s) for s in payload.get("steps") or []]
        if not steps:
            return fallback.plan(question, vocab)
        return AnalysisPlan(
            question=question.strip(),
            intent=str(payload.get("intent") or "").strip() or "Investigate the question.",
            steps=steps[:MAX_PLAN_STEPS],
            planner=self.name,
            model_name=self.model_name,
            follow_ups=[str(f) for f in (payload.get("follow_ups") or [])][:4],
            unmatched=bool(payload.get("unmatched")),
        )

    def _ask(self, question: str, vocab: Vocabulary) -> dict[str, Any]:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        library = json.dumps(list(vocab.analyses.values()), indent=None)
        dimensions = json.dumps(vocab.dimensions)
        periods = json.dumps(vocab.periods)

        message = client.messages.create(
            model=self.model_name,
            max_tokens=1200,
            system=PLANNER_SYSTEM_PROMPT.format(max_steps=MAX_PLAN_STEPS),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"ANALYSIS LIBRARY:\n{library}\n\n"
                        f"REPORTING PERIODS (you may also use 'latest', 'previous', "
                        f"'earliest'):\n{periods}\n\n"
                        f"FILTER DIMENSIONS AND THEIR PERMITTED VALUES:\n{dimensions}\n\n"
                        f"QUESTION: {question}"
                    ),
                }
            ],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return _extract_json(text)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model reply, tolerating a code fence."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The model did not return a plan.")
    return json.loads(cleaned[start : end + 1])


# ---------------------------------------------------------------------------


def get_planner() -> DemoPlanner | AnthropicPlanner:
    """The planner in force, chosen by whether a model key is configured."""
    key = settings.anthropic_api_key
    if key:
        return AnthropicPlanner(key)
    return DemoPlanner()


def planner_mode() -> dict[str, Any]:
    """What the UI displays about how questions are being planned."""
    planner = get_planner()
    demo = isinstance(planner, DemoPlanner)
    return {
        "mode": "demo" if demo else "model",
        "planner": planner.name,
        "model_name": planner.model_name,
        "description": (
            "No model key is configured, so IPM reads questions with its built-in "
            "deterministic planner. Every figure is still produced by executing real "
            "IPM Engine analyses against the published data."
            if demo
            else "Questions are read by a language model, which selects registered IPM "
                 "analyses. It never calculates a figure; the engine does."
        ),
    }


__all__ = [
    "DEFAULT_MODEL",
    "INTENTS",
    "AnthropicPlanner",
    "DemoPlanner",
    "get_planner",
    "planner_mode",
]
