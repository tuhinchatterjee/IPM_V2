"""
Pairwise analyst-judgment cases. §80.

    "Create pairwise preference cases. … Use for prompt/critic evaluation.
     Do not claim model fine-tuning occurred."

Why pairwise rather than scored
--------------------------------
Because "is this a good analyst answer?" has no scale anybody agrees on, and
"which of these two is better?" has an obvious answer that credit people agree
on almost every time. A rubric asking a judge to score an answer 1-5 produces
4s; a pair asking which one a credit committee would rather receive produces a
choice, and the choice can be checked against what a person actually picked.

What each pair isolates
-----------------------
Exactly one difference. Both answers in a pair are grounded in the SAME
validated evidence and both are fluent; what separates them is the judgement
§80 names — direct or indirect, materiality-aware or raw percentage, grounded
or speculative, and so on down the ten. A pair where the bad answer is also
badly written measures writing, and there is no shortage of that.

The bad answers here are deliberately good
-------------------------------------------
Every B answer is one a competent person would write and a reader would
believe. That is the point: an evaluation set whose wrong answers are obviously
wrong measures nothing, because the failure being tested is precisely that the
wrong answer is persuasive.

Nothing here trains anything
-----------------------------
§80's last line, and §1's. These are evaluation cases for prompts and critics.
No provider fine-tuning occurs, and this module cannot cause any.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

JUDGMENT_VERSION = "1.0.0"

# ------------------------------------------------------- §80's ten dimensions
DIRECTNESS = "direct_vs_indirect"
MATERIALITY = "materiality_aware_vs_raw_percentage"
GROUNDING = "grounded_vs_speculative"
BREADTH = "breadth_correctly_assessed"
EXCEPTIONS = "exceptions_included_vs_ignored"
POPULATION = "population_period_accurate_vs_misleading"
CAUSATION = "association_vs_causation"
CONCISION = "concise_vs_repetitive"
ACTIONABILITY = "actionable_vs_generic"
HONESTY = "honest_unresolved_vs_invented_rationale"

DIMENSIONS: tuple[str, ...] = (DIRECTNESS, MATERIALITY, GROUNDING, BREADTH,
                               EXCEPTIONS, POPULATION, CAUSATION, CONCISION,
                               ACTIONABILITY, HONESTY)

A = "A"
B = "B"


@dataclass
class Case:
    """One pair. §80's fields."""

    case_id: str
    dimension: str
    question: str
    #: The facts both answers were given. Identical for both by construction:
    #: a pair where one answer had better evidence measures the evidence.
    validated_evidence: list[str] = field(default_factory=list)
    answer_a: str = ""
    answer_b: str = ""
    preferred_answer: str = A
    preference_reasons: list[str] = field(default_factory=list)
    #: Which of §34's failure categories the rejected answer exhibits.
    failure_tags: list[str] = field(default_factory=list)

    @property
    def rejected(self) -> str:
        return self.answer_b if self.preferred_answer == A else self.answer_a

    @property
    def preferred(self) -> str:
        return self.answer_a if self.preferred_answer == A else self.answer_b

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "dimension": self.dimension,
            "question": self.question,
            "validated_evidence": list(self.validated_evidence),
            "answer_a": self.answer_a, "answer_b": self.answer_b,
            "preferred_answer": self.preferred_answer,
            "preference_reasons": list(self.preference_reasons),
            "failure_tags": list(self.failure_tags),
        }


def _c(case_id: str, dimension: str, question: str, evidence: list[str],
       answer_a: str, answer_b: str, preferred: str, reasons: list[str],
       tags: list[str]) -> Case:
    return Case(case_id=case_id, dimension=dimension, question=question,
                validated_evidence=evidence, answer_a=answer_a,
                answer_b=answer_b, preferred_answer=preferred,
                preference_reasons=reasons, failure_tags=tags)


CASES: tuple[Case, ...] = (
    # ------------------------------------------------------------ directness
    _c("pj-direct-1", DIRECTNESS,
       "Which sector has the highest ECL coverage?",
       ["ecl coverage by sector, latest quarter, validated",
        "Contracting 4.1%, Real Estate 3.2%, Manufacturing 2.8%"],
       "Contracting has the highest ECL coverage at 4.1%, against 3.2% for "
       "Real Estate and 2.8% for Manufacturing.",
       "ECL coverage varies meaningfully across the portfolio. Contracting "
       "and Real Estate both sit above the portfolio average, reflecting the "
       "elevated risk profile of construction-linked exposures, while "
       "Manufacturing remains comparatively well provisioned relative to its "
       "risk.",
       A,
       ["A answers the question in its first clause; B answers it in its "
        "second sentence and only by implication",
        "B adds a causal claim — 'reflecting the elevated risk profile' — "
        "that nothing in the evidence supports"],
       ["INTERPRETATION", "GROUNDING"]),

    # ---------------------------------------------------------- materiality
    _c("pj-material-1", MATERIALITY,
       "What moved most in the portfolio this quarter?",
       ["Education ECL +48%, from SAR 0.4m to SAR 0.6m",
        "Contracting ECL +6%, from SAR 210m to SAR 222m",
        "portfolio ECL SAR 1.2bn"],
       "Contracting is the material move: ECL rose SAR 12m, about 1% of "
       "portfolio ECL. Education rose 48% but from SAR 0.4m, so the movement "
       "is SAR 0.2m and immaterial at portfolio level.",
       "Education saw the largest movement, with ECL up 48% quarter on "
       "quarter — by far the steepest increase in the book. Contracting rose "
       "6%.",
       A,
       ["B ranks by percentage and reports a SAR 0.2m movement as the "
        "portfolio's largest",
        "A gives both the percentage and the amount, so the reader can see "
        "why the ranking differs from the percentages"],
       ["INTERPRETATION"]),

    # ------------------------------------------------------------ grounding
    _c("pj-ground-1", GROUNDING,
       "Why did Contracting ECL rise?",
       ["Contracting ECL +SAR 12m over the quarter, validated",
        "three borrowers account for 71% of the movement",
        "no rating downgrades in the segment over the window"],
       "Three borrowers account for 71% of the SAR 12m increase. No rating "
       "downgrades were recorded in the segment over the window, so this is "
       "concentrated in specific names rather than a broad repricing of "
       "segment risk. What drove those three names is not established here.",
       "The increase reflects deteriorating conditions in the Saudi "
       "construction sector, where payment delays on government contracts "
       "have pressured contractor liquidity through the period. Three "
       "borrowers account for 71% of the movement.",
       A,
       ["B's first sentence is an explanation nothing in the evidence "
        "supports — payment delays and government contracts appear nowhere",
        "A states what is established, states what is not, and stops"],
       ["GROUNDING", "INTERPRETATION"]),

    # -------------------------------------------------------------- breadth
    _c("pj-breadth-1", BREADTH,
       "Is the deterioration in Real Estate broad or concentrated?",
       ["18 of 22 borrowers moved adversely",
        "largest single contributor 9% of the movement",
        "Herfindahl over contributions 0.07"],
       "Broad: 18 of 22 borrowers moved adversely and no single name explains "
       "more than 9% of the movement.",
       "The movement is driven by weakness across several key names in the "
       "segment, with a number of borrowers contributing to the overall "
       "deterioration.",
       A,
       ["B is compatible with both broad and concentrated and therefore says "
        "nothing",
        "A names the two measures that decide it, so a reader can disagree "
        "with the measure rather than the conclusion"],
       ["INTERPRETATION"]),

    # ----------------------------------------------------------- exceptions
    _c("pj-except-1", EXCEPTIONS,
       "How did the Manufacturing book perform?",
       ["Manufacturing ECL -SAR 3m over the quarter",
        "gross adverse SAR 21m, gross favourable -SAR 24m",
        "two borrowers improved by SAR 19m between them"],
       "Manufacturing ECL fell SAR 3m — but that nets SAR 21m of "
       "deterioration against SAR 24m of improvement, and SAR 19m of the "
       "improvement is two borrowers. The book deteriorated on most names; "
       "two recoveries covered it.",
       "Manufacturing improved over the quarter, with ECL down SAR 3m.",
       A,
       ["B is arithmetically true and describes the portfolio as badly as any "
        "sentence could",
        "A gives the gross movements, which is the only way the reader learns "
        "that most of the book got worse"],
       ["INTERPRETATION", "OBJECTIVE_OMISSION"]),

    # ----------------------------------------------------------- population
    _c("pj-pop-1", POPULATION,
       "How much did ECL grow year on year?",
       ["opening ECL SAR 900m over 4,100 facilities",
        "closing ECL SAR 1.2bn over 5,300 facilities",
        "matched-population ECL movement +SAR 90m"],
       "ECL rose SAR 300m, but the book grew from 4,100 to 5,300 facilities "
       "over the same period. On the facilities present at both dates the "
       "increase is SAR 90m; the rest is new lending.",
       "ECL rose SAR 300m year on year, a 33% increase, reflecting broad "
       "deterioration in credit quality across the portfolio.",
       A,
       ["B attributes SAR 210m of new lending to deterioration",
        "A separates the movement from the population change, which is the "
        "only reading that answers the question asked"],
       ["INTERPRETATION", "GROUNDING"]),

    # ------------------------------------------------------------ causation
    _c("pj-cause-1", CAUSATION,
       "Does rising utilisation predict default?",
       ["borrowers above 85% utilisation defaulted at 4.2%",
        "borrowers below 85% defaulted at 1.1%",
        "single period, no control for rating or sector"],
       "Borrowers above 85% utilisation defaulted at 4.2% against 1.1% below "
       "it. This is an association over one period with no control for rating "
       "or sector; borrowers draw down because they are already stressed, so "
       "nothing here separates utilisation as a cause from utilisation as a "
       "symptom.",
       "Yes — high utilisation is a strong predictor of default. Borrowers "
       "above 85% utilisation are nearly four times more likely to default, "
       "so utilisation should be treated as an early warning trigger.",
       A,
       ["B claims prediction and recommends an action from a single-period "
        "association with no controls",
        "A gives the same numbers and names what would be needed before the "
        "causal claim could be made"],
       ["INTERPRETATION"]),

    # ------------------------------------------------------------- concision
    _c("pj-concise-1", CONCISION,
       "What is total EAD by sector?",
       ["EAD by sector, latest quarter, eight sectors, validated"],
       "Total EAD by sector for the latest quarter is in the table below. "
       "Real Estate is largest at SAR 4.2bn, 31% of the book.",
       "Total exposure at default broken down by sector for the latest "
       "reporting period is presented in the table below. As can be seen "
       "from the table, exposure at default varies across the sectors of the "
       "portfolio. Real Estate represents the largest sectoral exposure at "
       "SAR 4.2bn. This represents 31% of the total book. The remaining "
       "sectors follow in the table.",
       A,
       ["B says the same thing four times and adds nothing between "
        "repetitions",
        "the question asks for a table; the prose exists to say what the "
        "table's headline is"],
       ["INTERPRETATION"]),

    # --------------------------------------------------------- actionability
    _c("pj-action-1", ACTIONABILITY,
       "What should we look at next in Contracting?",
       ["three borrowers explain 71% of the ECL movement",
        "covenant data unavailable for 40% of the segment",
        "no rating review in the segment for 11 months"],
       "Two things. Pull the covenant position on the three names driving the "
       "movement — covenant data is missing for 40% of the segment, and those "
       "three are the ones where it matters. And the segment has not had a "
       "rating review in 11 months, so the unchanged ratings are not evidence "
       "of stability.",
       "It would be advisable to monitor the situation closely and consider "
       "conducting a more detailed review of the segment, with particular "
       "attention to borrowers exhibiting signs of deterioration. Enhanced "
       "monitoring may be appropriate.",
       A,
       ["B could be appended to any investigation of anything",
        "A names two specific analyses and says why each one is the next "
        "useful thing rather than a general precaution"],
       ["INTERPRETATION"]),

    # -------------------------------------------------------------- honesty
    _c("pj-honest-1", HONESTY,
       "Why did ECL fall while DPD and downgrades rose?",
       ["ECL -SAR 8m, DPD +2.1 days, 14 downgrades over the quarter",
        "all 15 contradiction diagnostics ran; none fired",
        "population matched, periods aligned, no overlay change"],
       "ECL fell SAR 8m while DPD rose 2.1 days and 14 borrowers were "
       "downgraded. All fifteen diagnostic checks ran — periods, population, "
       "grain, timing, overlays — and none explains the divergence. These "
       "signals genuinely disagree and somebody needs to look at the ECL "
       "calculation for this segment.",
       "The divergence reflects the lag between borrower-level deterioration "
       "and its flow through into modelled ECL, which typically takes one to "
       "two quarters to be recognised. The DPD and rating movements should be "
       "expected to feed into ECL in the coming periods.",
       A,
       ["B's lag explanation is plausible, standard, and contradicted by the "
        "timing check having already run and cleared",
        "A reports UNRESOLVED, which is what fifteen clear diagnostics mean, "
        "and says what to do about it"],
       ["GROUNDING", "INTERPRETATION"]),
)

BY_ID: dict[str, Case] = {c.case_id: c for c in CASES}


def by_dimension(dimension: str) -> list[Case]:
    return [c for c in CASES if c.dimension == dimension]


def coverage() -> dict[str, int]:
    """How many pairs each §80 dimension has. A zero is a gap, and visible."""
    return {d: len(by_dimension(d)) for d in DIMENSIONS}


def gaps() -> list[str]:
    return [d for d, n in coverage().items() if n == 0]


def judge(case: Case, chose: str) -> dict[str, Any]:
    """Score one judgement against the preference.

    Returns the reasons on a miss rather than only a boolean, because the
    reasons are what a prompt or critic evaluation is for: knowing that a
    judge picked B is worth much less than knowing it picked B on a
    materiality pair.
    """
    correct = str(chose).strip().upper() == case.preferred_answer
    return {
        "case_id": case.case_id,
        "dimension": case.dimension,
        "correct": correct,
        "preferred": case.preferred_answer,
        "chose": str(chose).strip().upper(),
        "reasons": [] if correct else list(case.preference_reasons),
        "failure_tags": [] if correct else list(case.failure_tags),
    }


def score(judgements: list[dict[str, Any]]) -> dict[str, Any]:
    """A judge's performance, by dimension.

    By dimension rather than as one number: a judge that is perfect on
    concision and blind to grounding is a judge that will approve exactly the
    answers that matter most.
    """
    by_dimension_counts: dict[str, dict[str, int]] = {
        d: {"total": 0, "correct": 0} for d in DIMENSIONS}
    for judgement in judgements:
        row = by_dimension_counts.setdefault(
            judgement["dimension"], {"total": 0, "correct": 0})
        row["total"] += 1
        row["correct"] += int(bool(judgement["correct"]))

    total = sum(r["total"] for r in by_dimension_counts.values())
    correct = sum(r["correct"] for r in by_dimension_counts.values())
    return {
        "version": JUDGMENT_VERSION,
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "by_dimension": by_dimension_counts,
        "blind_spots": [d for d, r in by_dimension_counts.items()
                        if r["total"] and r["correct"] == 0],
    }


__all__ = ["A", "ACTIONABILITY", "B", "BREADTH", "BY_ID", "CASES",
           "CAUSATION", "CONCISION", "Case", "DIMENSIONS", "DIRECTNESS",
           "EXCEPTIONS", "GROUNDING", "HONESTY", "JUDGMENT_VERSION",
           "MATERIALITY", "POPULATION", "by_dimension", "coverage", "gaps",
           "judge", "score"]
