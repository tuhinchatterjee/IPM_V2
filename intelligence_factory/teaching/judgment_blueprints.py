"""
The analytical-judgment corpus. §95.

    "Extend the canonical Teaching Library with at least:
     100 expert Investigation Blueprint cases;
     150 analyst-interpretation cases, including pairwise preferences;
     100 contradictory-signal cases;
     150 visualization-grammar cases;
     75 materiality/breadth/persistence cases;
     50 challenge-pass cases.
     … Do not inflate with trivial variants."

The last line is the constraint that shapes everything here
------------------------------------------------------------
Six hundred and twenty-five cases is easy to produce and hard to produce
honestly. Swapping "Contracting" for "Real Estate" in the same sentence gives
you two cases and one lesson, and a library built that way scores well on
every count and teaches nothing.

So each blueprint here varies along the axis its family is ABOUT, and the
right answer moves with it:

- a blueprint case varies the prompt's shape, so a different blueprint wins;
- an interpretation case varies which section the evidence cannot support, so
  a different section comes back INSUFFICIENT;
- a contradiction case varies which of the fifteen diagnostics fires, so a
  different §82 explanation is the answer — including none;
- a visualization case varies the result shape and its awkwardness, so a
  different chart wins or none does;
- a materiality case varies which governed input decides the band, so the
  band is not a function of the percentage;
- a challenge case varies which of the fourteen challenges the conclusion
  fails, so a different repair is required.

`report()` counts the DISTINCT lessons as well as the cases, and a family
whose distinct-lesson count is well below its case count is a family that has
been inflated. That number is visible rather than argued about.

Nothing here is human-written
------------------------------
`authoring_method` is BLUEPRINT throughout, as it is in `canonical`. The
specifications were written and reviewed once; the instances are generated.
Calling six hundred generated cases HUMAN would make the governance report
say something untrue about how this library was built.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.judgment import blueprints as bp
from backend.judgment import contradictions as cd
from backend.judgment import interpretation as it
from backend.judgment import materiality as mt
from backend.judgment import visual_grammar as vg
from backend.teaching import schema as sc
from backend.teaching import status as st
from intelligence_factory.teaching import canonical as cn
from intelligence_factory.teaching import migrate

JUDGMENT_CORPUS_VERSION = "1.0.0"

#: §95's targets, as data. Named so a shortfall reports against the brief's
#: own number rather than against whatever was produced.
TARGETS: dict[str, int] = {
    "INVESTIGATION_BLUEPRINT": 100,
    "ANALYST_INTERPRETATION": 150,
    "CONTRADICTORY_SIGNALS": 100,
    "VISUALIZATION_SELECTION": 150,
    "MATERIALITY_JUDGMENT": 75,
    "CHALLENGE_PASS": 50,
}


def _pick(items: tuple[Any, ...], seed: str, offset: int = 0) -> Any:
    digest = hashlib.sha256(f"judgment:{seed}:{offset}".encode()).digest()
    return items[int.from_bytes(digest[:4], "big") % len(items)]


# ---------------------------------------------------------------------------
# Investigation blueprint cases
# ---------------------------------------------------------------------------
#
# The lesson is WHICH blueprint, so the prompt shape varies and the expected
# blueprint moves with it. A hundred cases all selecting the segment
# blueprint would teach that the segment blueprint is the answer.

_PROMPTS: tuple[str, ...] = (
    "Something seems wrong with {subject}. Investigate it.",
    "Look into {subject} across the latest {window} and tell me what you "
    "find.",
    "I want a full picture of {subject} before the committee on Thursday.",
    "Work out what is going on with {subject}.",
    "Review {subject} and tell me whether anything needs attention.",
)


#: What is missing, and therefore what the blueprint must record rather than
#: quietly drop. The second axis: a hundred cases that all select a blueprint
#: cleanly teach selection nineteen times over and omission never, and
#: omission is the half §67 is about.
_OMISSIONS: tuple[tuple[str, str], ...] = (
    ("nothing is missing",
     "run every mandatory objective and report what was examined"),
    ("the covenant data stops two quarters short",
     "mark the covenant objective explicitly unavailable with the date it "
     "stops, and say the investigation is incomplete without it"),
    ("the collateral register has no valuations for a third of the segment",
     "state the coverage the collateral objective was computed over rather "
     "than reporting it as complete"),
    ("financial statements are more than a year old for most borrowers",
     "say the financial objective is answered on stale statements and what "
     "that means for the reading"),
    ("the rating history does not reach the opening period",
     "narrow the window to what the data supports and say the window moved"),
    ("no group structure is held, so exposures cannot be aggregated to "
     "parent",
     "answer at the borrower grain and say the group view is unavailable"),
)


def _blueprint_case(seed: str) -> sc.TeachingCase:
    """Which blueprint a prompt warrants, and what may not be omitted."""
    blueprint = _pick(bp.LIBRARY, seed, 1)
    gap, gap_expected = _pick(_OMISSIONS, seed, 6)
    sector = _pick(cn.SECTORS, seed, 2)
    prompt = _pick(_PROMPTS, seed, 3)
    window = _pick(("four quarters", "two quarters", "year"), seed, 4)

    subject = (blueprint.trigger_patterns[0]
               if blueprint.trigger_patterns
               else blueprint.business_name.lower())
    if "{subject}" in prompt:
        subject = f"{sector} {subject}" if len(subject) < 24 else subject
    question = prompt.format(subject=subject, window=window)

    mandatory = [o.id for o in blueprint.required_objectives]
    return cn.build(
        family="INVESTIGATION_BLUEPRINT",
        title=f"Blueprint selection: {blueprint.business_name}, where "
              f"{gap}",
        turns=[cn.Turn(
            message=question,
            behaviour=(
                f"Select the {blueprint.business_name} blueprint and say "
                f"why. It has {len(mandatory)} mandatory objectives. Here "
                f"{gap}: {gap_expected}. Report what was examined as well as "
                "what was found."))],
        objectives=(
            f"select the {blueprint.business_name} blueprint from the "
            "prompt",
            "run every mandatory objective or record why it was omitted",
            f"handle the case where {gap}",
            "report the objectives examined alongside the findings"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=list(blueprint.required_concepts[:4]),
        expected_blueprint=blueprint.blueprint_id,
        analytical_plan_contract={
            "blueprint": blueprint.blueprint_id,
            "mandatory_objectives": mandatory,
            "unavailable_handling": gap_expected},
        scope_contract=cn._forbids(
            "selecting a blueprint whose triggers the prompt does not match",
            "omitting a mandatory objective without a recorded reason",
            "reporting findings without saying what was examined"),
        invariants=["every mandatory objective is complete or explicitly "
                    "unavailable with a stated reason"],
    )


# ---------------------------------------------------------------------------
# Analyst interpretation cases
# ---------------------------------------------------------------------------
#
# The lesson is which SECTION the evidence cannot support, so the missing
# evidence varies and a different section comes back INSUFFICIENT.

_SECTION_LESSON: dict[str, str] = {
    it.DRIVERS: "no decomposition ran, so name no drivers",
    it.BREADTH: "breadth was not measured, so call it neither broad nor "
                "concentrated",
    it.PERSISTENCE: "one period cannot show persistence, so say so rather "
                    "than describing a trend",
    it.EXCEPTIONS: "nothing was tested for exceptions, so do not report that "
                   "there are none",
    it.CREDIT_RISK: "no association was established, so offer no credit-risk "
                    "mechanism",
    it.NEXT_BEST: "no follow-up was identified, so recommend none",
    it.MATERIALITY: "materiality was not assessed, so give the amount without "
                    "a band",
    it.LIMITATIONS: "the limitations are the answer's most useful part here",
}

_MEASURES: tuple[str, ...] = (
    "expected credit loss", "ECL coverage", "exposure at default",
    "Stage 2 share", "90+ delinquency", "weighted average rating",
    "utilisation", "probability of default")


#: WHY the section is absent, which is a different lesson from WHICH section.
#: INSUFFICIENT means we looked and could not tell; NOT_APPLICABLE means the
#: question does not have that shape; ABSTAIN means there is no bottom line
#: and the surrounding analysis must not be shown as though it were one.
_ABSENCES: tuple[tuple[str, str], ...] = (
    (it.INSUFFICIENT, "we looked and could not tell, so state insufficient "
                      "evidence"),
    (it.NOT_APPLICABLE, "the question does not have that shape, so do not "
                        "report a gap that is not one"),
    ("ABSTAIN", "no observation answers the question directly, so there is no "
                "bottom line: say what could not be established rather than "
                "showing the surrounding analysis as an answer"),
)

#: What the bottom line is drawn from when there is one. A different kind of
#: direct answer is a different first sentence.
_BOTTOM_LINES: tuple[tuple[str, str], ...] = (
    ("a change", "state the movement and its direction first"),
    ("a level", "state the figure and its period first"),
    ("a ranking", "name the top entity in the first clause"),
    ("a migration", "state how many moved and between which states"),
    ("no match", "say plainly that nothing met the criteria"),
)


def _interpretation_case(seed: str) -> sc.TeachingCase:
    """One section the evidence will not support, and the honest answer."""
    missing = _pick(tuple(_SECTION_LESSON), seed, 1)
    state, why_absent = _pick(_ABSENCES, seed, 6)
    bottom, bottom_expected = _pick(_BOTTOM_LINES, seed, 7)
    measure = _pick(_MEASURES, seed, 2)
    sector = _pick(cn.SECTORS, seed, 3)
    window = _pick(cn.WINDOWS, seed, 4)
    shape = _pick(("what happened to", "explain the movement in",
                   "give me a read on", "summarise"), seed, 5)

    return cn.build(
        family="ANALYST_INTERPRETATION",
        title=(f"Interpretation from {bottom}, "
               f"{missing.lower().replace('_', ' ')} {state.lower()}"),
        turns=[cn.Turn(
            message=f"{shape.capitalize()} {measure} for {sector} {window}.",
            behaviour=(
                ("There is no bottom line here: "
                 if state == "ABSTAIN" else
                 f"Answer in the contract's order: {bottom_expected}, then "
                 "what the evidence supports. ")
                + f"For {missing}, {why_absent} — "
                f"{_SECTION_LESSON[missing]}."))],
        objectives=(
            f"answer the question about {measure} for {sector} directly",
            f"report {missing} as {state} rather than writing it anyway",
            "state what could not be established"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=[measure],
        interpretation_contract={
            "absent_section": missing, "absent_state": state,
            "bottom_line_from": bottom,
            "why": _SECTION_LESSON[missing]},
        analytical_plan_contract={
            "answer_contract": "interpretation", "bottom_line_from": bottom,
            "sections_declined": [missing]},
        scope_contract=cn._forbids(
            f"writing a {missing} section the evidence does not support",
            "describing a movement as a trend from one period",
            "offering a causal mechanism for an association"),
        invariants=["every figure in the narrative traces to a validated "
                    "fact"],
    )


# ---------------------------------------------------------------------------
# Contradictory-signal cases
# ---------------------------------------------------------------------------
#
# The lesson is which diagnostic fires and therefore which §82 explanation is
# the answer — including the case where none fires and UNRESOLVED is correct.

_SIGNAL_PAIRS: tuple[tuple[str, str], ...] = (
    ("expected credit loss", "internal rating"),
    ("Stage 2 share", "90+ delinquency"),
    ("DSCR", "utilisation"),
    ("ECL coverage", "watchlist count"),
    ("leverage", "probability of default"),
    ("days past due", "IFRS 9 stage"),
    ("collateral coverage", "exposure at default"),
    ("interest coverage", "rating grade"),
)

#: Which check fires, and the explanation that follows from it. The
#: UNRESOLVED entry is deliberately included: §84's whole point is that it is
#: sometimes the right answer, and a corpus without it teaches that every
#: contradiction has a story.
_DIAGNOSES: tuple[tuple[str, str], ...] = (
    ("update_frequency", cd.TIMING_LAG),
    ("threshold_crossings", cd.THRESHOLD_LAG),
    ("grain_alignment", cd.AGGREGATION_EFFECT),
    ("portfolio_mix", cd.PORTFOLIO_MIX_EFFECT),
    ("denominator", cd.PORTFOLIO_MIX_EFFECT),
    ("concentration", cd.CONCENTRATION_EFFECT),
    ("data_quality", cd.DATA_QUALITY_EFFECT),
    ("period_alignment", cd.MISALIGNMENT),
    ("population_alignment", cd.MISALIGNMENT),
    ("relationship_match", cd.MISALIGNMENT),
    ("overlay", cd.MODEL_OR_OVERRIDE),
    ("persistence", cd.TEMPORARY_VS_PERSISTENT),
    ("new_exited", cd.PORTFOLIO_MIX_EFFECT),
    ("controls", cd.AGGREGATION_EFFECT),
    ("directional_semantics", cd.NOT_A_CONTRADICTION),
    ("", cd.TRUE_CONTRADICTION),
)


def _contradiction_case(seed: str) -> sc.TeachingCase:
    """Two signals that disagree, and what the diagnostics find."""
    improving, worsening = _pick(_SIGNAL_PAIRS, seed, 1)
    check, explanation = _pick(_DIAGNOSES, seed, 2)
    sector = _pick(cn.SECTORS, seed, 3)
    window = _pick(cn.WINDOWS, seed, 4)

    if explanation == cd.TRUE_CONTRADICTION:
        expected = (
            "All fifteen diagnostics run and none fires. Report UNRESOLVED, "
            "name the signals, and say somebody needs to look. Do not supply "
            "a plausible explanation to avoid it.")
    elif explanation == cd.NOT_A_CONTRADICTION:
        expected = (
            "The directional-semantics check fires: these do not in fact "
            "disagree once each movement's risk meaning is read. Say so "
            "rather than explaining a contradiction that is not one.")
    else:
        expected = (
            f"Run all fifteen diagnostics. The {check.replace('_', ' ')} "
            f"check fires, which supports {explanation}. Report the "
            "explanation with the check that supports it, and say how many "
            "checks ran.")

    return cn.build(
        family="CONTRADICTORY_SIGNALS",
        title=f"{improving} against {worsening}: {explanation}",
        turns=[cn.Turn(
            message=(f"{improving.capitalize()} improved for {sector} "
                     f"{window} while {worsening} deteriorated. What is going "
                     "on?"),
            behaviour=expected)],
        objectives=(
            f"align the periods, population and grain of {improving} and "
            f"{worsening}",
            "run and record the fifteen diagnostic checks",
            f"conclude {explanation} from what the checks found"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=[improving, worsening],
        expected_contradiction=explanation,
        analytical_plan_contract={
            "engine": "contradiction_diagnostics",
            "expected_explanation": explanation,
            "check_that_fires": check or "none"},
        scope_contract=cn._forbids(
            "explaining a contradiction from a check that did not run",
            "concluding from fewer than ten of the fifteen checks",
            "forcing one explanation when several remain possible"),
        invariants=["the diagnosis states how many of the fifteen checks "
                    "ran"],
    )


# ---------------------------------------------------------------------------
# Visualization-grammar cases
# ---------------------------------------------------------------------------
#
# The lesson is which chart, so the result shape and its awkwardness vary and
# a different chart wins — or none does and the table is the answer.

_AWKWARD: tuple[tuple[str, dict[str, Any]], ...] = (
    ("a comfortable size", {"categories": 8, "longest_label": 12}),
    ("more categories than a vertical bar holds",
     {"categories": 44, "longest_label": 11}),
    ("labels that will not fit under a vertical axis",
     {"categories": 9, "longest_label": 34}),
    ("a reader who asked for exact records",
     {"categories": 14, "longest_label": 12, "wants_records": True}),
    ("a fifth of the values missing",
     {"categories": 12, "longest_label": 12, "missing_pct": 0.3}),
    ("four decimals of required precision",
     {"categories": 8, "longest_label": 12, "precision_required": 4}),
    ("a narrow device", {"categories": 10, "longest_label": 12,
                         "narrow_device": True}),
    ("an axis that cannot start at zero",
     {"categories": 8, "longest_label": 12, "needs_zero_baseline": True,
      "zero_baseline_available": False}),
)

_SHAPE_QUESTIONS: dict[str, str] = {
    vg.SINGLE_VALUE: "What is total {measure}?",
    vg.CATEGORY_RANKING: "Show {measure} by sector.",
    vg.TWO_PERIOD_CATEGORY: "Compare {measure} by sector between the two "
                            "latest quarters.",
    vg.TIME_SERIES: "Show {measure} over the last eight quarters.",
    vg.MANY_TIME_SERIES: "Show {measure} by sector over the last eight "
                         "quarters.",
    vg.COMPOSITION_OVER_TIME: "Show how the {measure} mix changed over the "
                              "last eight quarters.",
    vg.CHANGE_DECOMPOSITION: "Decompose the {measure} change into "
                             "contributions.",
    vg.MIGRATION_PATHS: "Show rating movements between the two latest "
                        "quarters.",
    vg.MIGRATION_GRID: "Show opening against closing stage.",
    vg.DISTRIBUTION: "Show the spread of {measure} across borrowers.",
    vg.TWO_MEASURE: "Plot {measure} against leverage for each borrower.",
    vg.THREE_MEASURE: "Plot {measure}, leverage and DSCR for each borrower.",
    vg.CONCENTRATION_HIERARCHY: "Show how concentrated {measure} is across "
                                "sectors and sub-sectors.",
    vg.CATEGORY_PERIOD_MEASURE: "Show {measure} by sector and quarter.",
    vg.RECORD_LEVEL: "List the borrowers with their {measure}, rating, "
                     "stage, DPD and covenant status.",
}

_SHAPE_ROLES: dict[str, dict[str, str]] = {
    vg.SINGLE_VALUE: {"value": vg.MEASURE},
    vg.CATEGORY_RANKING: {"category": vg.CATEGORY, "value": vg.MEASURE},
    vg.TWO_PERIOD_CATEGORY: {"category": vg.CATEGORY, "value": vg.MEASURE},
    vg.TIME_SERIES: {"time": vg.TIME, "value": vg.MEASURE},
    vg.MANY_TIME_SERIES: {"time": vg.TIME, "series": vg.CATEGORY,
                          "value": vg.MEASURE},
    vg.COMPOSITION_OVER_TIME: {"time": vg.TIME, "series": vg.CATEGORY,
                               "value": vg.MEASURE},
    vg.CHANGE_DECOMPOSITION: {"category": vg.ENTITY,
                              "value": vg.DECOMPOSITION_COMPONENT},
    vg.MIGRATION_PATHS: {"source": vg.FLOW_SOURCE,
                         "destination": vg.FLOW_DESTINATION,
                         "value": vg.MEASURE},
    vg.MIGRATION_GRID: {"category": vg.RISK_BAND, "series": vg.RISK_BAND,
                        "value": vg.MEASURE},
    vg.DISTRIBUTION: {"value": vg.DISTRIBUTION_VALUE},
    vg.TWO_MEASURE: {"value": vg.MEASURE, "second_value": vg.MEASURE},
    vg.THREE_MEASURE: {"value": vg.MEASURE, "second_value": vg.MEASURE,
                       "size": vg.MEASURE},
    vg.CONCENTRATION_HIERARCHY: {"category": vg.CATEGORY,
                                 "value": vg.MEASURE},
    vg.CATEGORY_PERIOD_MEASURE: {"category": vg.CATEGORY, "series": vg.TIME,
                                 "value": vg.MEASURE},
    vg.RECORD_LEVEL: {"category": vg.ENTITY, "value": vg.MEASURE},
}


def _visual_case(seed: str) -> sc.TeachingCase:
    """A result shape at an awkwardness, and the chart the grammar chooses."""
    shape = _pick(vg.SHAPES, seed, 1)
    awkward, tweaks = _pick(_AWKWARD, seed, 2)
    measure = _pick(_MEASURES, seed, 3)
    roles = dict(_SHAPE_ROLES[shape])

    inputs: dict[str, Any] = {"measures": 1, "periods": 8,
                              "cardinality": tweaks.get("categories", 8),
                              **tweaks}
    if shape == vg.THREE_MEASURE:
        inputs["measures"] = 3
    elif shape in (vg.MANY_TIME_SERIES, vg.COMPOSITION_OVER_TIME):
        inputs["measures"] = 4
    elif shape == vg.TWO_MEASURE:
        inputs["measures"] = 2
    elif shape == vg.RECORD_LEVEL:
        inputs["measures"] = 6
    if shape == vg.TWO_PERIOD_CATEGORY:
        inputs["periods"] = 2

    chosen = vg.select(shape, vg.Inputs(roles=roles, **inputs))
    label = vg.CHART_LABEL.get(chosen.chosen, chosen.chosen)
    refused = "; ".join(
        f"{vg.CHART_LABEL.get(s.chart, s.chart)} because {s.rejections[0]}"
        for s in chosen.rejected if s.rejections) or "nothing was refused"

    return cn.build(
        family="VISUALIZATION_SELECTION",
        title=f"{vg.SHAPE_MEANS[shape].rstrip('.')} with {awkward}",
        turns=[cn.Turn(
            message=_SHAPE_QUESTIONS[shape].format(measure=measure),
            result_type="CHART" if chosen.chosen != vg.TABLE else "TABLE",
            behaviour=(
                f"With {awkward}, show {label}. Refused: {refused}. Always "
                "offer the table beside it."))],
        objectives=(
            f"classify the result as {shape}",
            f"choose {label} and say why",
            "keep the table available beside the chart"),
        difficulty=sc.COMPLEX, risk="MEDIUM", officer=2,
        concepts=[measure],
        expected_visualization=chosen.chosen,
        analytical_plan_contract={
            "engine": "visualization_grammar", "result_shape": shape,
            "expected_chart": chosen.chosen,
            "rejected": [c.chart for c in chosen.rejected]},
        scope_contract=cn._forbids(
            "plotting an identifier or a lineage column",
            "drawing a chart whose values do not reconcile to the table",
            "showing more than two decimals on a chart"),
        invariants=["the chart's plotted values equal the table's"],
    )


# ---------------------------------------------------------------------------
# Materiality, breadth and persistence cases
# ---------------------------------------------------------------------------
#
# The lesson is that the band is NOT a function of the percentage, so what
# varies is which governed input decides it.

_MATERIALITY_LESSONS: tuple[tuple[str, str], ...] = (
    ("a large percentage of a small base",
     "rank by amount, not by percentage: a 48% rise on SAR 0.4m is SAR 0.2m"),
    ("a risk-appetite breach",
     "the band is floored at HIGH because the bank has already decided it "
     "cares about this limit"),
    ("thin evidence behind a large-looking movement",
     "the band is capped at MODERATE: we cannot yet claim it is as large as "
     "it looks"),
    ("a movement inside its own historical volatility",
     "the movement does not stand out from the noise, so say so"),
    ("a broad movement across most of the book",
     "18 of 22 names moved and no one name explains more than 9%"),
    ("a movement concentrated in three names",
     "three names carry 71%: this is not a segment story"),
    ("a spike that reverses the following period",
     "one period dominates the movement, so this is a spike and not a trend"),
    ("a persistent drift across four periods",
     "the direction holds for four consecutive periods with high path "
     "efficiency"),
    ("gross movements that net to almost nothing",
     "report the gross adverse and favourable, because the net hides that "
     "most names got worse"),
    ("a population that grew between the two dates",
     "separate the matched-population movement from the new lending"),
)


def _materiality_case(seed: str) -> sc.TeachingCase:
    """Which governed input decides the band, breadth or persistence."""
    lesson, expected = _pick(_MATERIALITY_LESSONS, seed, 1)
    measure = _pick(_MEASURES, seed, 2)
    sector = _pick(cn.SECTORS, seed, 3)
    window = _pick(cn.WINDOWS, seed, 4)
    band = _pick(mt.BANDS, seed, 5)

    return cn.build(
        family="MATERIALITY_JUDGMENT",
        title=f"Materiality with {lesson}, banded {band}",
        turns=[cn.Turn(
            message=(f"How significant is the {measure} movement in {sector} "
                     f"{window}?"),
            behaviour=(
                f"This is {lesson}. {expected.capitalize()}. State the band "
                "and the measures that produced it, so a reader can disagree "
                "with a measure rather than with the conclusion."))],
        objectives=(
            f"measure the {measure} movement for {sector}",
            "assign a band from the governed policy rather than from the "
            "percentage",
            "state the inputs that produced the band"),
        difficulty=sc.COMPLEX, risk="HIGH", officer=2,
        concepts=[measure],
        expected_materiality_band=band,
        analytical_plan_contract={
            "engine": "materiality", "expected_band": band,
            "decided_by": expected},
        scope_contract=cn._forbids(
            "ranking movements by percentage",
            "asserting broad or concentrated without the measures",
            "calling a single-period movement a trend"),
        invariants=["the materiality band names the policy version that "
                    "produced it"],
    )


# ---------------------------------------------------------------------------
# Challenge-pass cases
# ---------------------------------------------------------------------------
#
# The lesson is which of the fourteen challenges the conclusion fails, so
# what varies is the flaw planted in it.

_CHALLENGE_FLAWS: tuple[tuple[str, str], ...] = (
    ("the population changed between the two dates",
     "recompute on the matched population before attributing the movement"),
    ("the periods are not aligned",
     "align the windows: one side is a quarter and the other a year"),
    ("the grain differs across the join",
     "the facility side was not aggregated to customer before joining"),
    ("a single name carries most of the movement",
     "report the concentration rather than describing a segment trend"),
    ("the conclusion rests on one period",
     "say what would be needed before calling this a trend"),
    ("an association is stated as a cause",
     "restate it as an association and name the controls that are missing"),
    ("the denominator moved, not the numerator",
     "the ratio moved because the book grew"),
    ("a data-quality warning was not carried into the conclusion",
     "state the coverage the figure was computed over"),
    ("the opposite reading fits the same evidence",
     "say which evidence would distinguish the two readings"),
    ("an overlay explains the movement",
     "the model change moved the measure independently of risk"),
    ("the sample is too small for the claim",
     "give the counts rather than the rate"),
    ("the comparison is against a restated prior period",
     "say which basis the prior figure is on"),
    ("an exception contradicts the headline",
     "report the name that does not follow the pattern"),
    ("the result was not reconciled to a control total",
     "reconcile the components to the movement they explain"),
)


#: What the challenge DOES to the conclusion. Finding the flaw is half the
#: lesson; what happens next is the other half, and a corpus where every
#: challenge ends in a repair teaches that a conclusion always survives.
_OUTCOMES: tuple[tuple[str, str], ...] = (
    ("survives", "the conclusion holds once the flaw is corrected; report it "
                 "with the correction stated"),
    ("is narrowed", "the conclusion holds for part of the population only; "
                    "report the part it holds for"),
    ("is withdrawn", "the conclusion does not survive; report what was found "
                     "and that the original reading is not supported"),
)


def _challenge_case(seed: str) -> sc.TeachingCase:
    """A conclusion with one planted flaw, and the challenge that finds it."""
    flaw, repair = _pick(_CHALLENGE_FLAWS, seed, 1)
    outcome, outcome_expected = _pick(_OUTCOMES, seed, 6)
    measure = _pick(_MEASURES, seed, 2)
    sector = _pick(cn.SECTORS, seed, 3)
    window = _pick(cn.WINDOWS, seed, 4)

    return cn.build(
        family="CHALLENGE_PASS",
        title=f"Challenge: {flaw}, conclusion {outcome}",
        turns=[cn.Turn(
            message=(f"{measure.capitalize()} in {sector} rose {window}. "
                     "Confirm what is driving it."),
            behaviour=(
                f"Run the challenge pass before answering. It finds that "
                f"{flaw}. {repair.capitalize()}. The conclusion then "
                f"{outcome}: {outcome_expected}. Report what survived the "
                "challenge, not that a challenge ran."))],
        objectives=(
            f"establish the {measure} movement in {sector}",
            "run the challenge pass and record each challenge's finding",
            f"report that the conclusion {outcome}"),
        difficulty=sc.EXPERT, risk="HIGH", officer=3,
        concepts=[measure],
        analytical_plan_contract={
            "engine": "challenge_pass", "planted_flaw": flaw,
            "expected_outcome": outcome},
        scope_contract=cn._forbids(
            "reporting that a challenge pass ran without its findings",
            "presenting a conclusion that failed a challenge",
            "treating an unrun challenge as a passed one"),
        invariants=["every challenge has a recorded finding"],
    )


@dataclass(frozen=True)
class Blueprint:
    """One family's generator and §95's target for it."""

    family: str
    count: int
    make: Callable[[str], sc.TeachingCase]


BLUEPRINTS: tuple[Blueprint, ...] = (
    Blueprint("INVESTIGATION_BLUEPRINT", TARGETS["INVESTIGATION_BLUEPRINT"],
              _blueprint_case),
    Blueprint("ANALYST_INTERPRETATION", TARGETS["ANALYST_INTERPRETATION"],
              _interpretation_case),
    Blueprint("CONTRADICTORY_SIGNALS", TARGETS["CONTRADICTORY_SIGNALS"],
              _contradiction_case),
    Blueprint("VISUALIZATION_SELECTION", TARGETS["VISUALIZATION_SELECTION"],
              _visual_case),
    Blueprint("MATERIALITY_JUDGMENT", TARGETS["MATERIALITY_JUDGMENT"],
              _materiality_case),
    Blueprint("CHALLENGE_PASS", TARGETS["CHALLENGE_PASS"], _challenge_case),
)

#: Seeds tried per case requested before accepting the space is exhausted.
_ATTEMPTS = 12


def _finish(case: sc.TeachingCase, family: str, index: int
            ) -> sc.TeachingCase:
    case.source_system = "judgment_corpus"
    case.source_reference = f"{family}:{index}"
    case.provenance = (
        f"Analytical-judgment case for {family}: a reviewed shape "
        "instantiated over the governed vocabulary. §95.")
    case.authoring_method = st.BLUEPRINT
    case.ontology_version = migrate.ONTOLOGY_VERSION
    return migrate.enrich(case)


def cases() -> list[sc.TeachingCase]:
    """Every judgment case, deterministically and without duplicates."""
    out: list[sc.TeachingCase] = []
    for blueprint in BLUEPRINTS:
        seen: set[str] = set()
        built: list[sc.TeachingCase] = []
        for attempt in range(blueprint.count * _ATTEMPTS):
            if len(built) >= blueprint.count:
                break
            case = _finish(blueprint.make(f"{blueprint.family}:{attempt}"),
                           blueprint.family, attempt)
            if case.fingerprint in seen:
                continue
            seen.add(case.fingerprint)
            built.append(case)
        for index, case in enumerate(built):
            case.case_id = f"jdg-{blueprint.family.lower()}-{index:03d}"
        out.extend(built)
    return out


def lessons(produced: list[sc.TeachingCase] | None = None
            ) -> dict[str, int]:
    """Distinct LESSONS per family, not distinct cases.

    §95's last line is "do not inflate with trivial variants", and this is the
    number that shows whether it was obeyed. A family with a hundred cases and
    six lessons has been inflated; the same family with a hundred cases and
    sixty has not. Reported rather than argued about.

    The lesson is the case's title, because each generator's title names the
    axis its family varies along — which blueprint, which section, which
    diagnostic, which chart, which governed input, which challenge.
    """
    produced = produced if produced is not None else cases()
    distinct: dict[str, set[str]] = {}
    for case in produced:
        distinct.setdefault(case.family_id, set()).add(case.title)
    return {family: len(titles) for family, titles in distinct.items()}


def report() -> dict[str, Any]:
    """What the judgment corpus contains, against §95's targets."""
    produced = cases()
    by_family: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    problems: dict[str, int] = {}

    for case in produced:
        by_family[case.family_id] = by_family.get(case.family_id, 0) + 1
        by_difficulty[case.difficulty] = \
            by_difficulty.get(case.difficulty, 0) + 1
        for problem in sc.validate(case):
            problems[problem.field] = problems.get(problem.field, 0) + 1

    distinct = lessons(produced)
    short = {family: target - by_family.get(family, 0)
             for family, target in TARGETS.items()
             if by_family.get(family, 0) < target}

    return {
        "version": JUDGMENT_CORPUS_VERSION,
        "total": len(produced),
        "targets": dict(TARGETS),
        "by_family": by_family,
        "by_difficulty": by_difficulty,
        "distinct_lessons": distinct,
        "short_of_target": short,
        "meets_targets": not short,
        "problems": problems,
        "authoring_method": st.BLUEPRINT,
        "sentence": _sentence(produced, distinct, short),
    }


def _sentence(produced: list[sc.TeachingCase], distinct: dict[str, int],
              short: dict[str, int]) -> str:
    thin = [f for f, n in distinct.items()
            if n * 3 < len([c for c in produced if c.family_id == f])]
    head = (f"{len(produced)} analytical-judgment cases across "
            f"{len(TARGETS)} families, none written by hand — every one is a "
            "reviewed shape instantiated over the governed vocabulary.")
    if short:
        head += (" Short of target: "
                 + ", ".join(f"{f} by {n}" for f, n in short.items()) + ".")
    if thin:
        head += (" Fewer than one distinct lesson per three cases in: "
                 + ", ".join(thin) + ".")
    return head


__all__ = ["BLUEPRINTS", "Blueprint", "JUDGMENT_CORPUS_VERSION", "TARGETS",
           "cases", "lessons", "report"]
