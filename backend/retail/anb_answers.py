"""
The card investigation: reading the five questions, and answering them.

WHAT THIS IS FOR
----------------
A Risk Case about the card book's early-delinquency migration opens an
investigation, and the conversation that follows is the same five questions
every time: split the bucket, look at the cohort's scores, decompose the score
move, find where it is concentrated, say what to do. They are five questions
with five known shapes over one dataset, and the honest way to answer them is
to compute them.

So they are routed here, before the planner, and answered from
`backend.retail.anb_demo` — the same functions the Risk Case and its drawer
read. That is what makes the thread reconcile: the figure in the third answer
and the figure on the card are not two computations that happen to agree, they
are one computation read twice.

WHAT THIS IS NOT FOR
--------------------
It is not a general question router and it must never behave like one. Two
things are true of everything it claims:

* **It is gated.** A question reaches an answer here only if the sentence
  itself names what it is about, or the conversation it is asked in is this
  investigation. "What should we do about it?" is answered here inside the
  card thread and NOWHERE else, because outside that thread nobody has said
  what "it" is and answering anyway is how a demonstration puts a card
  recommendation under a question about mortgages.
* **It declines rather than approximates.** `read` returns nothing when it is
  not sure, and the ordinary planner answers. A wrong answer costs more than a
  slow one.

Everything it reports is SYNTHETIC demonstration data. Alpha Card is a
demonstration product, and nothing here is a statement about any bank.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.retail import anb_demo as anb

logger = logging.getLogger(__name__)

#: What the case is about, written on the thread's context when the
#: investigation is opened. The generic questions are answered only inside a
#: thread carrying it.
ABOUT = "retail_early_delinquency"

SPLIT = "split"
BEHAVIOUR = "behaviour"
DECOMPOSE = "decompose"
CONCENTRATION = "concentration"
ACTIONS = "actions"

#: A question about the card book at all. Every reading below needs one of
#: these or a thread that has already established it.
_CARDS = re.compile(r"\bcredit[ -]?cards?\b|\bcards?\b|\balpha\b", re.I)
#: The cohort, once the thread has established it.
_COHORT = re.compile(r"\b20\s*[-–to]+\s*29\b|\bthese customers\b|\bthis cohort\b"
                     r"|\bthose customers\b|\bthem\b", re.I)

_READINGS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 1. Split the early bucket. Named by its sub-buckets, or by the act.
    (SPLIT, re.compile(
        r"(?=.*\b1\s*[-–]\s*29\b|.*\bearly\b|.*\bbucket\b)"
        r"(?=.*\bsplit\b|.*\bbreak\s*(?:it|this|the\w*)?\s*down\b|.*\bbreakdown\b"
        r"|.*\bsub[- ]?bucket|.*\b1\s*[-–]\s*9\b|.*\b10\s*[-–]\s*19\b"
        r"|.*\b20\s*[-–]\s*29\b)", re.I | re.S)),
    # 2. The cohort's behavioural scores.
    (BEHAVIOUR, re.compile(
        r"(?=.*\bbehaviou?ral\b|.*\brisk score\b|.*\bscore\b)"
        r"(?=.*\bdistribution\b|.*\bbands?\b|.*\bmoved?\b|.*\bmigrat|.*\bshift)"
        r"(?!.*\bdecompos|.*\bdriv|.*\bvariable|.*\bwhy is\b)", re.I | re.S)),
    # 3. What moved the score. This is the challenge, and it is usually phrased
    #    as one: "the score is only worse because they are already late".
    (DECOMPOSE, re.compile(
        r"\bdecompos|\bbreak (?:the )?score\b|\bwhat(?:'s| is) (?:really )?driv"
        r"|\bdrivers?\b|\bmodel variables?\b|\bbehaviou?ral[- ]model\b"
        r"|\balready (?:\d+\s*[-–]\s*\d+\s*)?(?:dpd|days?|late|past due)\b"
        r"|\bsimply because\b|\bonly because\b|\bmerely because\b", re.I)),
    # 4. Where it is concentrated.
    (CONCENTRATION, re.compile(
        r"\bwhat(?:'s| is) causing\b|\bwhat caused\b|\bwhere is (?:this|it|the stress)\b"
        r"|\bconcentrat|\bwhich (?:sub[- ]?product|product|programme|program|segment|card)\b"
        r"|\bwhere (?:is|are) (?:this|these|it|they)\b|\broot cause\b"
        r"|\bwhy is this happening\b", re.I)),
    # 5. What to do.
    (ACTIONS, re.compile(
        r"\bwhat should we do\b|\bwhat do (?:we|you) recommend\b|\brecommend"
        r"|\baction plan\b|\bwhat (?:actions?|steps?)\b|\bhow (?:should|do) we (?:respond|treat|fix)\b"
        r"|\bwhat would you do\b|\bnext steps?\b|\bmitigat", re.I)),
)

#: The readings that need the thread's context before they mean anything. A
#: sentence that names neither the cohort nor the product is answered here only
#: because the conversation already did.
_NEEDS_CONTEXT: frozenset[str] = frozenset({CONCENTRATION, ACTIONS})


@dataclass(frozen=True)
class Reading:
    """Which of the five was asked, and what established it."""

    kind: str
    #: True when the thread supplied the subject rather than the sentence.
    from_thread: bool = False


def in_case_thread(state: Any = None, memory: Any = None,
                   context: dict[str, Any] | None = None) -> bool:
    """Whether this question is being asked inside the card investigation.

    Read from the investigation's stored context, which the Risk Case wrote
    when it opened the thread. A thread that is not this one answers `False`
    and the generic questions fall through to the planner, which is the
    behaviour that stops "what should we do about it?" becoming a card
    recommendation in somebody else's conversation.
    """
    found = dict(context or {})
    case = found.get("risk_case") or {}
    if isinstance(case, dict) and str(case.get("about") or "") == ABOUT:
        return True
    for holder in (state, memory):
        marker = getattr(holder, "anb_case", None) if holder is not None else None
        if marker:
            return True
    return False


def read(question: str, *, context: dict[str, Any] | None = None,
         state: Any = None, memory: Any = None) -> Reading | None:
    """Which of the five questions this is, or None to let the planner answer.

    Deliberately conservative. A sentence that matches two readings is
    ambiguous, not twice as certain, and is declined — except where the more
    specific reading is a strict refinement of the looser one, which is handled
    by the order the patterns are tried in.
    """
    asked = " ".join(str(question or "").split())
    if not asked or not anb.available():
        return None

    inside = in_case_thread(state=state, memory=memory, context=context)
    names_cards = bool(_CARDS.search(asked))
    names_cohort = bool(_COHORT.search(asked))

    for kind, pattern in _READINGS:
        if not pattern.search(asked):
            continue
        if kind in _NEEDS_CONTEXT and not inside:
            # The sentence alone does not say what it is about. Only the thread
            # can, and it has not.
            if not (names_cards and names_cohort):
                return None
        if not (inside or names_cards or names_cohort):
            return None
        return Reading(kind=kind, from_thread=inside and not names_cards)
    return None


# ------------------------------------------------------------- answering

def _handler() -> Any:
    from backend.orchestration.handlers import HandlerResult

    return HandlerResult


def _columns(rows: list[dict[str, Any]], units: dict[str, str] | None = None
             ) -> list[dict[str, Any]]:
    """Column specs in the order the first row lays them out.

    The order is the argument the table makes, so it is taken from the rows
    rather than from a sorted set of keys.
    """
    if not rows:
        return []
    marks = units or {}
    return [{"name": name, "unit": marks.get(name, "")}
            for name in rows[0]]


def _trend_chart(title: str, rows: list[dict[str, Any]], series: list[str],
                 *, note: str = "") -> dict[str, Any]:
    """A month-on-month line, scaled to the lines it is drawing.

    The y-axis is asked to fit the SERIES, not the percentage scale. A bucket
    that moved from three per cent to nine is a tripling, and on an axis that
    runs to a hundred because one other line sits at eighty-four it is a flat
    line with a kink in it. Everything the chart leaves out stays in the table
    beside it, so nothing is hidden by being scaled away.
    """
    return {
        "kind": "line", "x": "Month", "series": series, "unit": "%",
        "title": title, "fit_to_series": True, "note": note,
    }


def answer(reading: Reading, *, period: str = "") -> Any:
    """The answer to one of the five, computed from the book."""
    at = period or anb.latest_month()
    builder = {
        SPLIT: _split, BEHAVIOUR: _behaviour, DECOMPOSE: _decompose,
        CONCENTRATION: _concentration, ACTIONS: _actions,
    }[reading.kind]
    return builder(at)


def _cohort_line(found: dict[str, Any]) -> str:
    """The sentence that keeps the cohort on screen in every answer."""
    return (f"Credit cards, {found['cohort']:,} accounts at 20-29 days past "
            f"due at {found['period']}")


# ---------------------------------------------------------------- 1. split

def _split(at: str) -> Any:
    found = anb.sub_bucket_trend(at)
    if not found.get("available"):
        return None
    focus = found["focus"]
    move = focus["move"]
    others = [m for m in found["moves"] if m["move"].label != anb.FOCUS]

    rows = found["rows"]
    table = [{
        "Sub-bucket": m["move"].label,
        f"{found['previous_period']} (%)": m["move"].before,
        f"{found['period']} (%)": m["move"].now,
        "Change (pp)": m["move"].change,
        "Against its recent baseline (x)": m["baseline_multiple"],
        "Accounts": m["move"].now_count,
    } for m in found["moves"]]

    steady = " and ".join(
        f"{m['move'].label} at {m['move'].now:.1f}% against a "
        f"{m['baseline']:.1f}% baseline" for m in others)

    sentence = (
        f"Almost all of it is 20-29 days past due. That sub-bucket is at "
        f"{move.now:.1f}% of card accounts at {found['period']}, against "
        f"{move.before:.1f}% last month and a {focus['baseline']:.1f}% average "
        f"over the months before — {focus['baseline_multiple']:.1f} times its "
        f"recent baseline, and {found['focus_share_of_early']:.0f}% of the "
        f"whole 1-29 population. The first two weeks past due have barely "
        f"moved: {steady}.")

    observations = [
        f"20-29 DPD carries {move.now_count:,} of the "
        f"{sum(m['move'].now_count for m in found['moves']):,} accounts in "
        f"1-29 DPD — {found['focus_share_of_early']:.0f}% of the bucket, "
        f"against {anb._pct(others[0]['move'].now_count + others[1]['move'].now_count, sum(m['move'].now_count for m in found['moves'])):.0f}% "
        f"for 1-9 and 10-19 together.",
        f"1-9 DPD is at {others[0]['baseline_multiple']:.1f} times its baseline "
        f"and 10-19 DPD at {others[1]['baseline_multiple']:.1f}. A book that had "
        f"simply become forgetful would move all three.",
        "An account more than twenty days past due has missed a full statement "
        "cycle and then not answered the reminder on it. That is a different "
        "condition from a late payment, and it is the one that is growing.",
    ]

    return _handler()(
        answer=sentence,
        rows=rows,
        columns=_columns(rows, {label: "%" for label in found["series"]}),
        values={"20-29 DPD now": move.now,
                "Against its recent baseline": focus["baseline_multiple"],
                "Share of the 1-29 population": found["focus_share_of_early"],
                "Accounts": move.now_count},
        title="1-29 DPD split into its sub-buckets",
        chart=_trend_chart("Credit-card accounts by days past due, 1-29 DPD",
                           rows, list(found["series"])),
        tables=[{"title": "Latest month against last month and the baseline",
                 "because": ("The chart shows the shape; these are the figures "
                             "behind it."),
                 "rows": table, "columns": _columns(table)}],
        detail={"observations": observations,
                "cohort": (f"Credit cards, {found['accounts']:,} open accounts "
                           f"at {found['period']}"),
                "definition": (
                    "Each sub-bucket is COUNT(card accounts whose days past due "
                    "fall in it) / COUNT(open card accounts) at the month-end. "
                    "The recent baseline is the average of the months shown "
                    "before the latest one.")},
        follow_ups=[
            "How is the behavioural score distribution for these 20-29 DPD "
            "customers? Show me how it has moved.",
            "What is causing this? Where is this stress concentrated?",
        ],
        execution="analysis",
        execution_label="Computed from the published card book",
    )


# ------------------------------------------------------------ 2. behaviour

def _behaviour(at: str) -> Any:
    found = anb.behaviour_distribution(at)
    if not found.get("available"):
        return None
    score = found["score"]
    base, now = found["baseline"], found["period"]
    rows = found["rows"]

    sentence = (
        f"The same customers' behavioural scores have moved a long way down. "
        f"Weak and very weak bands hold {found['weak_now']:.0f}% of the cohort "
        f"at {now}, against {found['weak_before']:.0f}% at {base} — "
        f"{found['weak_change']:+.0f} percentage points — and the average score "
        f"has fallen from {score.before:.0f} to {score.now:.0f}. This says the "
        f"cohort's risk profile has deteriorated; it does not yet say why.")

    observations = [
        f"These are the SAME {found['traced']:,} accounts at both dates, not "
        f"whoever happened to be at 20-29 DPD in each month. A comparison of "
        f"two different populations could not tell a change in behaviour from "
        f"a change in who is in the group.",
        f"The strong and very strong bands have gone from "
        f"{sum(o['share'] for o in found['before'] if o['band'] in ('A', 'A+')):.0f}% "
        f"of the cohort to "
        f"{sum(o['share'] for o in found['now'] if o['band'] in ('A', 'A+')):.0f}%. "
        f"This is not a tail getting worse, it is the middle of the "
        f"distribution moving.",
        f"The comparison is against {base} rather than last month because "
        f"{base} is the last month before this began. Last month is already "
        f"inside it, and comparing against it would understate the move.",
    ]
    if found["traced"] < found["cohort"]:
        observations.append(
            f"{found['cohort'] - found['traced']:,} of the {found['cohort']:,} "
            f"accounts were not on the book at {base} and are left out of the "
            f"comparison rather than counted as unchanged.")

    return _handler()(
        answer=sentence,
        rows=rows,
        columns=_columns(rows, {base: "%", now: "%", "Change (pp)": "pp"}),
        values={"Weak and very weak now": found["weak_now"],
                f"Weak and very weak at {base}": found["weak_before"],
                "Average behavioural score": score.now,
                "Accounts in the cohort": found["cohort"]},
        title=f"Behavioural score bands, {base} against {now}",
        chart={"kind": "grouped_bar", "x": "Behavioural band",
               "series": [base, now], "unit": "%",
               "title": "Behavioural score distribution of the 20-29 DPD cohort",
               "note": "Weakest band on the left."},
        detail={"observations": observations,
                "cohort": _cohort_line(found),
                "definition": (
                    "Bands are the behavioural scorecard's own cut points, "
                    "shared with the application scorecard so a band means the "
                    "same thing on either. Weak is band D and very weak is "
                    "band E.")},
        follow_ups=[
            "The behavioural score may simply be worse because these customers "
            "are already 20-29 DPD. Decompose the deterioration by the "
            "behavioural-model variables and tell me what is really driving it.",
            "What is causing this? Where is this stress concentrated?",
        ],
        execution="analysis",
        execution_label="Computed from the published card book",
    )


# ----------------------------------------------------------- 3. decompose

def _decompose(at: str) -> Any:
    found = anb.score_decomposition(at)
    if not found.get("available"):
        return None
    score, base = found["score"], found["baseline"]
    ahead = found.get("before_arrears") or {}
    metrics = found["metrics"]
    by_name = {m.label: m for m in metrics}
    util = by_name.get("Average card utilisation")
    pay = by_name.get("Payments received against amounts due, 3 months")
    stalled = by_name.get(
        "At least two of the last three months at the minimum or missed")

    rows = found["rows"]
    metric_rows = [{
        "Measure": m.label,
        f"{base}": m.before,
        f"{found['period']}": m.now,
        "Change": m.change,
        "Unit": m.unit,
    } for m in metrics]

    parts = [
        f"No — delinquency does not explain most of it. "
        f"{found['non_delinquency_share']:.0f}% of the "
        f"{abs(score.change):.0f}-point fall comes from variables that carry no "
        f"arrears information at all, and the two largest are both independent "
        f"of it: the cohort is drawing far more of its limits "
        f"({found['drawing_share']:.0f}% of the deterioration) and repaying far "
        f"less of what it owes ({found['repayment_share']:.0f}%)."]
    if ahead.get("points"):
        parts.append(
            f"The clearest evidence is the timing: between {ahead['from']} and "
            f"{ahead['to']} these accounts were still current, and their scores "
            f"had already fallen {abs(ahead['points']):.0f} points — "
            f"{ahead['share_of_total']:.0f}% of the total move — with nothing "
            f"delinquent to explain it.")
    sentence = " ".join(parts)

    observations = []
    if util:
        observations.append(
            f"Average utilisation has gone from {util.before:.0f}% to "
            f"{util.now:.0f}% ({util.change:+.0f} points). A cohort at that "
            f"level has no headroom left on the card.")
    if pay and stalled:
        observations.append(
            f"Payments against amounts due over three months have fallen from "
            f"{pay.before:.2f}x to {pay.now:.2f}x, and "
            f"{stalled.now:.0f}% of the cohort has now spent at least two of "
            f"the last three months at the minimum or missing it, against "
            f"{stalled.before:.0f}% at {base}.")
    observations.append(
        "The split is arithmetic, not an attribution model. The behavioural "
        "score is base points plus one contribution per variable, every one of "
        "them published on the row, so the change in the score is exactly the "
        "sum of the changes in those contributions. Each share below is one "
        "variable's change over the total of the negative ones.")
    if found.get("unscored"):
        observations.append(
            f"{found['unscored']:,} of the cohort's accounts are scored at one "
            f"of the two dates but not the other and are left out, rather than "
            f"counted as unchanged. The {found['traced']:,} below are scored at "
            f"both.")
    if abs(found.get("residual") or 0) > 0.5:
        observations.append(
            f"The listed variables account for all but "
            f"{abs(found['residual']):.1f} points of the move. The remainder is "
            f"contributions too small to list separately.")
    observations.append(
        "Any variable carrying arrears information is counted on the "
        "delinquency side — days past due, worst days past due in six months, "
        "missed payments, bureau arrears, broken promises and failed direct "
        "debits. The non-delinquency share is understated by that choice "
        "rather than flattered by it.")

    return _handler()(
        answer=sentence,
        rows=rows,
        columns=_columns(rows, {"Points change": "points",
                                "Share of deterioration (%)": "%"}),
        values={"Explained by variables carrying no arrears information":
                found["non_delinquency_share"],
                "Drawing on the limit": found["drawing_share"],
                "Repayment behaviour": found["repayment_share"],
                "Fall in the average score": score.change},
        title="What moved the behavioural score, by model variable",
        chart={"kind": "bar", "x": "Behavioural variable",
               "series": ["Points change"], "unit": "points",
               "orientation": "horizontal",
               "title": ("Contribution to the score change, "
                         f"{base} to {found['period']}"),
               "note": "Ranked by size. All contributions are negative."},
        tables=[{"title": "The same movement in the units the cohort lives in",
                 "because": ("Scorecard points answer what moved the score. "
                             "These answer whether the cohort is in trouble."),
                 "rows": metric_rows, "columns": _columns(metric_rows)}],
        detail={"observations": observations,
                "cohort": _cohort_line(found),
                "definition": (
                    "One contribution per variable, averaged over the "
                    f"{found['traced']:,} accounts traced at both dates. "
                    f"Compared against {base}, the last month before the "
                    "deterioration began.")},
        follow_ups=[
            "What is causing this? Where is this stress concentrated?",
            "What should we do about it?",
        ],
        execution="analysis",
        execution_label="Computed from the published card book",
    )


# ------------------------------------------------------- 4. concentration

def _concentration(at: str) -> Any:
    found = anb.concentration(at)
    if not found.get("available"):
        return None
    lead = found["lead"]
    bands = found["bands"]
    ranked = [b for b in bands if b["accounts"] >= 20]
    worst = ranked[0] if ranked else {}
    best = ranked[-1] if ranked else {}

    programme_rows = [{
        "Card programme": p["label"],
        "Accounts": p["accounts"],
        "Share of the card book (%)": p["exposure_share"],
        "New 20-29 DPD cases": p["new_cases"],
        "Share of new cases (%)": p["problem_share"],
        "Entered 20-29 DPD this month (%)": p["rate"],
    } for p in found["programmes"]]

    sentence = (
        f"It is concentrated in {lead['label']}, and inside it in the accounts "
        f"written below the established origination floor. {lead['label']} is "
        f"{lead['exposure_share']:.0f}% of the card book but "
        f"{lead['problem_share']:.0f}% of this month's new 20-29 DPD cases. "
        f"Within it, the {found['expansion_floor']:.0f}-"
        f"{found['established_floor'] - 1:.0f} origination bands are "
        f"{found['opened_share']:.0f}% of its accounts and "
        f"{found['opened_case_share']:.0f}% of its new cases, on a gradient "
        f"that runs from {worst.get('rate', 0):.0f}% entering 20-29 DPD in the "
        f"{worst.get('band', '')} band to {best.get('rate', 0):.0f}% in "
        f"{best.get('band', '')} — {found['gradient']:.0f} times.")

    observations = [
        found["expansion_context"],
        f"The concentration is stated as exposure share against problem share "
        f"because that is the only form in which it is a finding. A programme "
        f"holding {lead['exposure_share']:.0f}% of the book and producing "
        f"{lead['exposure_share']:.0f}% of the cases would be unremarkable "
        f"however large its case count looked.",
        f"The behavioural signals move with the same gradient. Average "
        f"utilisation runs at {worst.get('utilisation', 0):.0f}% in the "
        f"{worst.get('band', '')} band against {best.get('utilisation', 0):.0f}% "
        f"in {best.get('band', '')}, and payments against amounts due at "
        f"{worst.get('payment_to_due', 0):.2f}x against "
        f"{best.get('payment_to_due', 0):.2f}x. The origination decision and "
        f"the behaviour under stress are pointing at the same accounts.",
        f"Cases are counted as NEW: accounts that were at 0 DPD last month and "
        f"are at 20-29 DPD now, read from the prior-month days-past-due on the "
        f"row. Accounts already past due are not counted again.",
    ]
    established = [p for p in found["programmes"]
                   if p["programme"] != found["expansion"]]
    if established:
        quiet = min(established, key=lambda p: p["rate"])
        loudest = max(established, key=lambda p: p["rate"])
        observations.insert(1, (
            f"The established programmes have not moved with it: they run at "
            f"between {quiet['rate']:.1f}% and {loudest['rate']:.1f}% entering "
            f"20-29 DPD against {lead['rate']:.0f}% on {lead['label']}. This is "
            f"not a card book under pressure, it is one programme inside it."))

    return _handler()(
        answer=sentence,
        rows=found["band_rows"],
        columns=_columns(found["band_rows"], {
            "Share of Alpha Card (%)": "%", "Share of its new cases (%)": "%",
            "Entered 20-29 DPD (%)": "%", "Average utilisation (%)": "%"}),
        values={f"{lead['label']} share of the card book": lead["exposure_share"],
                f"{lead['label']} share of new 20-29 cases": lead["problem_share"],
                "Steepest to shallowest band": found["gradient"],
                "New 20-29 DPD cases this month": found["new_cases"]},
        title=f"{found['expansion_label']} risk by origination score band",
        chart={"kind": "bar", "x": "Origination score band",
               "series": ["Entered 20-29 DPD (%)"], "unit": "%",
               "title": (f"{found['expansion_label']}: share of each "
                         "origination band entering 20-29 DPD this month"),
               "note": ("Bands are fixed at origination and never move, so this "
                        "is a cut by who was taken on.")},
        tables=[{"title": "Where the new cases came from, by card programme",
                 "because": ("Which programme carries the book, and which one "
                             "carries the cases."),
                 "rows": programme_rows, "columns": _columns(programme_rows)}],
        detail={"observations": observations,
                "cohort": (f"Credit cards, {found['accounts']:,} open accounts "
                           f"and {found['new_cases']:,} new 20-29 DPD cases at "
                           f"{found['period']}"),
                "definition": (
                    f"{found['expansion_label']} accepts applicants from "
                    f"{found['expansion_floor']:.0f}, where the established "
                    f"card programme stops at {found['established_floor']:.0f}. "
                    f"Both floors are demonstration policy "
                    f"({found['policy_version']}), and the programme opened in "
                    f"{found['expansion_opened']}.")},
        follow_ups=["What should we do about it?"],
        execution="analysis",
        execution_label="Computed from the published card book",
    )


# ------------------------------------------------------------- 5. actions

def _actions(at: str) -> Any:
    found = anb.actions(at)
    if not found.get("available"):
        return None
    rows = found["rows"]
    acting = [r for r in rows if r["reduction"]]
    if not acting:
        return None
    worst = acting[0]
    flat = (max(r["current_limit"] for r in rows)
            - min(r["current_limit"] for r in rows))

    sentence = (
        f"Treat the bands, not the book. The "
        f"{', '.join(r['band'] for r in acting)} origination bands of "
        f"{found['expansion_label']} carry the stress and should come down to "
        f"a tighter starting limit on new business — "
        f"{acting[-1]['reduction']:.0f}% to {worst['reduction']:.0f}% — with "
        f"enhanced monitoring and paused increases on the accounts already "
        f"written. The {found['reference']} band and above stay on normal "
        f"policy. A blanket tightening of the card book would take the same "
        f"action against accounts entering 20-29 DPD at "
        f"{found['reference_rate']:.1f}%.")

    observations = [
        f"Each proposed reduction is computed, not chosen: it is how much worse "
        f"that band's own entry rate is than the {found['reference']} reference "
        f"band, damped by {found['damping']:.3f} and capped at "
        f"{found['cap']:.0f}%. The excess and the rate behind it are in the "
        f"table, so every row can be checked against the two columns beside it.",
        "It is damped because a band running at eight times the reference's "
        "rate is not a case for cutting its limit eightfold. A limit is "
        "exposure at default, not probability of it, and reducing the first "
        "does not divide the second. The figure is a policy-review proposal "
        "with an estimated effect on exposure, not a guaranteed loss reduction.",
        "The existing book and the new book are different decisions. A limit "
        "already granted is contractual, so what is proposed against it is "
        "monitoring, paused increases and customer contact. The reduction "
        "applies to the starting limit on business not yet written, where it "
        "is a policy parameter rather than a change to somebody's agreement.",
    ]
    if flat < 4000:
        observations.append(
            f"Worth putting to the committee separately: the typical limit "
            f"barely varies across the bands today — SAR "
            f"{min(r['current_limit'] for r in rows):,.0f} to "
            f"{max(r['current_limit'] for r in rows):,.0f} — while the entry "
            f"rate across them varies by a factor of "
            f"{worst['rate'] / found['reference_rate']:.0f}. The limit is "
            f"currently set by income and not by risk, and that is the policy "
            f"question underneath this month's numbers.")
    observations.append(
        "Before any of it: the same origination bands are still open for new "
        "business on the same floor. A treatment plan that leaves the intake "
        "unchanged treats this month's cohort and books next month's.")

    return _handler()(
        answer=sentence,
        rows=found["table"],
        columns=_columns(found["table"], {
            "Entered 20-29 DPD (%)": "%", "Reduction (%)": "%",
            "Against the reference band (x)": "x",
            "Typical limit today (SAR)": "SAR",
            "Recommended new-business limit (SAR)": "SAR"}),
        values={"Bands proposed for action": len(acting),
                "Largest proposed reduction": worst["reduction"],
                "Reference band": found["reference"],
                "Balance carried by the opened bands (SAR)":
                    round(found["opened_exposure"], 0)},
        title="Recommended treatment by origination score band",
        detail={"observations": observations,
                "cohort": (f"{found['expansion_label']}, by origination score "
                           f"band, at {found['period']}"),
                "definition": (
                    "Proposed reduction = min(cap, damping x (this band's entry "
                    "rate / the reference band's entry rate - 1)), rounded to "
                    "the nearest SAR 500. Every input is a column in the table."),
                "why_this_recommendation": [
                    f"{r['band']}: entering 20-29 DPD at {r['rate']:.1f}% "
                    f"against {found['reference_rate']:.1f}% in "
                    f"{found['reference']} — {r['excess']:.1f} times — with "
                    f"average utilisation at {r['utilisation']:.0f}%. "
                    f"Proposed starting limit SAR {r['proposed_limit']:,.0f} "
                    f"against SAR {r['current_limit']:,.0f} today "
                    f"({r['reduction']:.1f}%)."
                    for r in rows]},
        follow_ups=[
            "Show me the 1-29 DPD trend again for the whole card book.",
            "Which origination bands are still open for new business?",
        ],
        execution="analysis",
        execution_label="Computed from the published card book",
    )
