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
from backend.orchestration.periods import PeriodIntent, read_period_intent
from backend.orchestration.schema import (
    MAX_PLAN_STEPS,
    AnalysisPlan,
    PlanStep,
    Scope,
    StepRole,
)
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
    #: A short noun phrase naming what the question is about, recorded on the
    #: scope and shown on the Trace.
    focus: str = ""
    #: The dimension the answer should be broken down by, where the question
    #: implies one.
    dimension: str | None = None


INTENTS: list[Intent] = [
    Intent(
        id="stage2_increase",
        focus="Stage 2 movement",
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
        focus="sector deterioration",
        dimension='sector',
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
        focus="rating transitions",
        dimension='risk_rating',
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
        focus="deteriorating borrowers",
        dimension='borrower',
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
        focus="scenario impact",
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
        focus="impairment movement",
        dimension='sector',
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
        focus="exposure concentration",
        dimension='sector',
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
        focus="arrears movement",
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
        focus="facility utilisation",
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
        focus="portfolio trend",
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
        focus="IFRS 9 staging",
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
        focus="what deteriorated",
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
        id="headline_metric",
        focus="a headline figure",
        patterns=[
            (r"what is (our|the|my)?\s*(current|latest)?\s*"
             r"(npl|ecl|coverage|exposure|ead|stage 2|stage 3|pd|lgd|utilisation)", 7),
            (r"how (much|many) (exposure|ead|ecl|provision|facilities|borrowers)", 6),
            (r"\b(npl ratio|ecl coverage|total exposure|total ecl)\b", 5),
        ],
        intent_text="Report the current headline position of the book.",
        build="_headline_metric",
        follow_ups=[
            "How has ECL changed?",
            "Which sectors deteriorated the most?",
            "Where is the book most concentrated?",
        ],
    ),
    Intent(
        id="overview",
        focus="portfolio position",
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

    Question-scoped by construction
    -------------------------------
    Each intent names ONE primary analysis — the one that answers the question —
    and at most a couple of supporting analyses that materially help explain it.
    "Which sectors deteriorated the most?" returns the sector attribution and
    nothing else. It does not return total exposure, the NPL ratio, or the stage
    distribution, because none of those were asked for and none of them are
    needed to rank sectors.
    """

    name = "demo"
    model_name = None

    def plan(self, question: str, vocab: Vocabulary | None = None,
             period: tuple[str, str] | None = None) -> AnalysisPlan:
        """Read the question into a scoped plan.

        `period` is a comparison the user has already chosen — from answering a
        clarification, or from the Investigation being refreshed. When present it
        overrides whatever the question's wording implied.
        """
        vocab = vocab or get_vocabulary()
        text = question.strip()
        lowered = text.lower()

        intent, score = self._best_intent(lowered)
        unmatched = score == 0

        # --- what the question said about time -------------------------------
        read = read_period_intent(text, vocab.periods)
        if period:
            read = PeriodIntent(True, period[0], period[1], "chosen by the user")

        # --- what the question said about the book ---------------------------
        dimension_hit = vocab.resolve_dimension_value(text)
        filters: dict[str, Any] = {}
        notes: list[str] = []
        if dimension_hit:
            dimension, value = dimension_hit
            filters = {dimension: value}
            notes.append(f"Restricted to {dimension.replace('_', ' ')} = {value}.")

        builder = getattr(self, intent.build)
        steps: list[PlanStep] = builder(lowered, vocab, filters)[:MAX_PLAN_STEPS]
        steps = [
            step.with_params() if index == 0 else step
            for index, step in enumerate(steps)
        ]
        steps = [_with_role(step, index) for index, step in enumerate(steps)]
        steps = [_with_periods(step, read) for step in steps]

        if unmatched:
            notes.insert(
                0,
                "IPM did not recognise a specific analytical question here, so it has run "
                "the standard portfolio review instead. Try one of the suggestions below, "
                "or name a sector, a stage, a rating or a scenario.",
            )

        primary = steps[0] if steps else None
        requirement = _period_requirement(primary)
        scope = Scope(
            focus=intent.focus,
            dimension=intent.dimension,
            output=_answer_shape(primary),
            period_requirement=requirement,
            period_specified=read.specified,
            from_period=read.from_period,
            to_period=read.to_period,
            period_source=read.source,
            filters=filters,
        )

        intent_text = intent.intent_text
        if dimension_hit and not unmatched:
            intent_text = f"{intent_text.rstrip('.')}, restricted to {dimension_hit[1]}."

        return AnalysisPlan(
            question=text,
            intent=intent_text,
            scope=scope,
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

    def _group_dimension(self, lowered: str, default: str = "sector") -> str:
        for candidate in ("region", "segment", "product_type", "rating_bucket", "country"):
            if re.search(candidate.replace("_", "[ _]?"), lowered):
                return candidate
        return default

    # ------------------------------------------------------------- builders
    #
    # The FIRST step returned is the primary one: the analysis that answers the
    # question. Anything after it must earn its place by explaining the primary
    # result. Most questions return exactly one step, and that is the point.

    def _headline_metric(self, lowered: str, vocab: Vocabulary,
                         filters: dict) -> list[PlanStep]:
        # A point-in-time figure. One analysis, no history, no clarification —
        # asking "what period would you like to compare?" here would be an
        # irritation, not a governance control.
        return [
            PlanStep("portfolio_summary", "Portfolio position",
                     "The headline figures for the latest published period.",
                     params={}, filters=filters),
        ]

    def _overview(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("portfolio_summary", "Portfolio position",
                     "Where the book stands, and how it has moved.",
                     params={}, filters=filters),
            PlanStep("stage_distribution", "IFRS 9 staging",
                     "How that exposure is distributed across stages.",
                     params={"group_by": "none"}, filters=filters),
        ]

    def _deterioration_overview(self, lowered: str, vocab: Vocabulary,
                                filters: dict) -> list[PlanStep]:
        # A deliberately broad question, so a broader plan is the right answer —
        # but still not a general briefing. What moved, where it sits, who.
        return [
            PlanStep("stage_migration", "What moved",
                     "The exposure that migrated to a worse stage, which is where "
                     "deterioration first becomes visible.",
                     params={"basis": "ead"}, filters=filters),
            PlanStep("ecl_movement", "Where the impairment sits",
                     "The change in expected credit loss, attributed by sector.",
                     params={"group_by": "sector"}, filters=filters),
            PlanStep("top_deteriorating_borrowers", "The names behind it",
                     "The individual borrowers whose position worsened most.",
                     params={"top_n": 10}, filters=filters),
        ]

    def _stage2(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        # "Why has Stage 2 increased?" is a why-question. The migration is the
        # answer; the names are the explanation. Nothing else is needed.
        return [
            PlanStep("stage_migration", "Movement into Stage 2",
                     "The gross exposure that migrated between stages, rather than the "
                     "net change — the net figure hides offsetting movements.",
                     params={"basis": "ead"}, filters=filters),
            PlanStep("top_deteriorating_borrowers", "Borrowers behind the migration",
                     "The obligors that moved, with the reason recorded for each.",
                     params={"top_n": 10}, filters=filters),
        ]

    def _sector_deterioration(self, lowered: str, vocab: Vocabulary,
                              filters: dict) -> list[PlanStep]:
        # The attribution IS the answer. Adding concentration or staging here
        # would be answering a question nobody asked.
        return [
            PlanStep("ecl_movement", "Deterioration by sector",
                     "The change in expected credit loss, attributed to the sectors "
                     "it sits in.",
                     params={"group_by": self._group_dimension(lowered)}, filters=filters),
        ]

    def _rating_transition(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        basis = "count" if re.search(r"count|number of|borrower count", lowered) else "ead"
        return [
            PlanStep("rating_transition_matrix", "Rating transition matrix",
                     "Empirical transition probabilities, measured on "
                     f"{'borrower count' if basis == 'count' else 'exposure'}.",
                     params={"basis": basis}, filters=filters),
        ]

    def _top_deteriorating(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("top_deteriorating_borrowers", "Deteriorating borrowers",
                     "Borrowers ranked by the severity of their deterioration, with the "
                     "reasons recorded for each.",
                     params={"top_n": self._top_n(lowered, 10)}, filters=filters),
        ]

    def _stress(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        params: dict[str, Any] = {"scenario": self._scenario(lowered)}
        # stress_scenario_basic takes the sector as a declared parameter, so a
        # sector mentioned in the question belongs there rather than in filters.
        sector = filters.get("sector")
        remaining = {k: v for k, v in filters.items() if k != "sector"}
        if isinstance(sector, str):
            params["sector"] = sector
        return [
            PlanStep("stress_scenario_basic", "Scenario impact",
                     "The scenario's shocks applied to the reported position.",
                     params=params, filters=remaining),
        ]

    def _ecl_change(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("ecl_movement", "ECL movement",
                     "The change in expected credit loss, reconciled from opening to "
                     "closing and attributed by sector.",
                     params={"group_by": "sector"}, filters=filters),
        ]

    def _concentration(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        dimension = self._group_dimension(lowered)
        return [
            PlanStep("sector_concentration", "Concentration",
                     f"How exposure is distributed across {dimension.replace('_', ' ')}, "
                     "and how much sits in the largest groups.",
                     params={"dimension": dimension, "top_n": self._top_n(lowered, 15)},
                     filters=filters),
        ]

    def _arrears(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("dpd_migration", "Arrears movement",
                     "The exposure moving between days-past-due buckets, and what cured.",
                     params={"basis": "ead"}, filters=filters),
        ]

    def _utilisation(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("high_utilisation_watchlist", "High utilisation",
                     "Facilities drawing unusually heavily on their committed limits.",
                     params={"threshold_pct": 90.0, "top_n": self._top_n(lowered, 20)},
                     filters=filters),
        ]

    def _trend(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("portfolio_trend", "Portfolio trend",
                     "Exposure, staging and coverage across every available period.",
                     params={}, filters=filters),
        ]

    def _staging(self, lowered: str, vocab: Vocabulary, filters: dict) -> list[PlanStep]:
        return [
            PlanStep("stage_distribution", "IFRS 9 staging",
                     "Exposure, impairment and coverage by stage.",
                     params={"group_by": self._group_dimension(lowered)}, filters=filters),
        ]


# --------------------------------------------------------------- plan shaping


def _contract(analysis_id: str):
    from backend.engine.registry import get_registry

    try:
        return get_registry().contract(analysis_id)
    except Exception:  # pragma: no cover - the validator reports it properly
        return None


def _period_requirement(step: PlanStep | None) -> str:
    contract = _contract(step.analysis_id) if step else None
    return contract.period_requirement.value if contract else "point_in_time"


def _answer_shape(step: PlanStep | None) -> str:
    contract = _contract(step.analysis_id) if step else None
    return contract.answer_shape.value if contract else "level"


def _with_role(step: PlanStep, index: int) -> PlanStep:
    return PlanStep(
        analysis_id=step.analysis_id, title=step.title, rationale=step.rationale,
        params=dict(step.params), filters=dict(step.filters), period=step.period,
        role=StepRole.PRIMARY if index == 0 else StepRole.SUPPORTING,
    )


def _with_periods(step: PlanStep, read: PeriodIntent) -> PlanStep:
    """Write the settled comparison into whichever parameters the analysis has.

    The concrete period labels are written in, not the aliases. An answer that
    says "Q4 2025 to Q1 2026" can be checked; one that says "previous to latest"
    changes meaning every time a period is published.
    """
    contract = _contract(step.analysis_id)
    if contract is None or not read.specified:
        return step
    accepted = {p.name for p in contract.parameters}
    changes: dict[str, Any] = {}
    if "from_period" in accepted and read.from_period:
        changes["from_period"] = read.from_period
    if "to_period" in accepted and read.to_period:
        changes["to_period"] = read.to_period
    if "period" in accepted and read.to_period:
        changes["period"] = read.to_period
    if "compare_period" in accepted and read.from_period:
        changes["compare_period"] = read.from_period
    return step.with_params(**changes) if changes else step


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

    def plan(self, question: str, vocab: Vocabulary | None = None,
             period: tuple[str, str] | None = None) -> AnalysisPlan:
        vocab = vocab or get_vocabulary()
        fallback = DemoPlanner()
        try:
            payload = self._ask(question, vocab, period)
        except Exception as e:
            # A model outage must not take the product down. The deterministic
            # planner answers instead, and the response says so.
            logger.warning("Model planning failed (%s); falling back to the demo planner.", e)
            plan = fallback.plan(question, vocab, period)
            return AnalysisPlan(
                question=plan.question, intent=plan.intent, scope=plan.scope, steps=plan.steps,
                planner="demo-fallback", model_name=self.model_name,
                follow_ups=plan.follow_ups, unmatched=plan.unmatched,
                notes=[*plan.notes, "The configured model was unavailable, so IPM planned "
                                    "this investigation deterministically."],
            )

        steps = [PlanStep.from_dict(s) for s in payload.get("steps") or []]
        if not steps:
            return fallback.plan(question, vocab, period)
        steps = steps[:MAX_PLAN_STEPS]
        # The model may or may not have marked a primary step. Whether it did or
        # not, exactly one step must be primary, so the roles are normalised
        # here rather than trusted.
        if sum(1 for s in steps if s.is_primary) != 1:
            steps = [_with_role(step, index) for index, step in enumerate(steps)]

        # Time is not left to the model. The period is read from the question by
        # the same code the deterministic planner uses, so a two-period analysis
        # the model selected without saying *when* still triggers the
        # clarification instead of quietly comparing something.
        read = read_period_intent(question, vocab.periods)
        if period:
            read = PeriodIntent(True, period[0], period[1], "chosen by the user")
        steps = [_with_periods(step, read) for step in steps]

        primary = next((s for s in steps if s.is_primary), steps[0])
        scope = Scope(
            focus=str(payload.get("focus") or "").strip(),
            dimension=payload.get("dimension"),
            output=_answer_shape(primary),
            period_requirement=_period_requirement(primary),
            period_specified=read.specified,
            from_period=read.from_period,
            to_period=read.to_period,
            period_source=read.source,
            filters=dict(primary.filters),
        )

        return AnalysisPlan(
            question=question.strip(),
            intent=str(payload.get("intent") or "").strip() or "Investigate the question.",
            scope=scope,
            steps=steps,
            planner=self.name,
            model_name=self.model_name,
            follow_ups=[str(f) for f in (payload.get("follow_ups") or [])][:4],
            unmatched=bool(payload.get("unmatched")),
        )

    def _ask(self, question: str, vocab: Vocabulary,
             period: tuple[str, str] | None = None) -> dict[str, Any]:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        library = json.dumps(list(vocab.analyses.values()), indent=None)
        dimensions = json.dumps(vocab.dimensions)
        periods = json.dumps(vocab.periods)
        chosen = (
            f"THE USER HAS ALREADY CHOSEN THE COMPARISON PERIOD: "
            f"from {period[0]} to {period[1]}. Use it.\n\n" if period else ""
        )

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
                        f"{chosen}"
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
