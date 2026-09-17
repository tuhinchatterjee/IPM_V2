"""The six steps of any of the nine stories, read and answered from the book.

WHAT THIS IS FOR
----------------
A card raised by `episode_cases` opens an investigation, and the conversation
that follows is the same five questions of a different pocket: break the issue
apart, check whether the customers were sound when approved, decompose what
moved, find where it is concentrated, and say what to do about it.

They are answered here, before the planner, from the same
`backend.retail.episode_measures` functions the card and its drawer read. That
is what makes a thread reconcile: the figure in the third answer and the figure
on the card are not two computations that agree, they are one computation read
twice.

WHAT THIS IS NOT FOR
--------------------
It is not a general router and must never behave like one.

* **It is gated by the thread.** The five questions are generic — "what should
  we do next?" names nothing at all — so they are answered only inside an
  investigation whose Risk Case says which story it is. Outside one, `read`
  returns nothing and the planner answers, because answering anyway is how a
  demonstration puts a payroll recommendation under a question about
  mortgages.
* **It narrows, it does not re-query.** S1 works on the alerts that survived
  verification, S3 on the corroborated ones, S4 on the corroborated ones
  inside the named pocket, and S5 on exactly S4's scope. Each step's cohort is
  a subset of the one before it, and the cohort snapshot the export carries
  records that it is.
* **It declines rather than approximates.** A question that matches nothing
  falls through, and a step whose figures are not in the book returns None.

Everything it reports is SYNTHETIC demonstration data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from backend.retail import episode_measures as em
from backend.retail import episodes as ep
from backend.retail import metrics_contract as mc

logger = logging.getLogger(__name__)

#: What the card is about, written on the thread's context when the
#: investigation is opened.
ABOUT = "retail_episode"

STEPS = ("S1", "S2", "S3", "S4", "S5")

#: Which evidence level each step narrows to. The attrition is the substance of
#: S1 and S3: an alert explained by a timing difference, a bank-account switch
#: or a reporting lag is not a case, and a story that carried every alert
#: through to the policy cohort would have no verification in it.
STEP_EVIDENCE = {
    "S0": None,
    "S1": ep.EV_VERIFIED,
    "S2": ep.EV_VERIFIED,
    "S3": ep.EV_CORROBORATED,
    "S4": ep.EV_CORROBORATED,
    "S5": ep.EV_CORROBORATED,
}
#: And which of them also narrow to the named pocket.
STEP_IN_POCKET = {"S4", "S5"}

#: Paraphrase patterns, one per step. Deliberately about the SHAPE of the
#: question rather than about any one story's vocabulary, so a reader who
#: rewords a chip in their own terms still reaches the same step.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("S5", re.compile(
        r"\bwhat should we do\b|\bnext steps?\b|\baction plan\b|"
        r"\bsequenced?\b.*\bactions?\b|\bactions?\b.*\bpolicy\b|"
        r"\brecommend(ation)?s?\b|\bwhat do we do\b", re.I)),
    ("S4", re.compile(
        r"\bconcentrat\w+\b|\bpocket\b|\bwhere is (it|this|the)\b|"
        r"\bintersection\b|\bnormali[sz]ed\b|\brank\b|"
        r"\bwhich (group|segment|channel|employer|project|cohort)\b|"
        r"\bmost (affected|exposed)\b|\boverrepresented\b", re.I)),
    ("S3", re.compile(
        r"\bdecompos\w+\b|\bdriver\w*\b|\bwhat explains\b|\bbreak.*down by\b|"
        r"\bhold\b.*\b(fixed|constant)\b|\bchallenge\b|\bwaterfall\b|"
        r"\bcould .*(just|only) be\b|\btrace\b.*\bin time\b|"
        r"\breconcile\b.*\binto\b|\bcounted twice\b", re.I)),
    ("S2", re.compile(
        r"\boriginal (application|internal)\b|\bapplication scores?\b|"
        r"\bat (approval|origination)\b|\bwhen (they were )?approved\b|"
        r"\bunderwrit\w+\b|\bwere .*(weak|sound)\b|\bdecision[- ]time\b|"
        r"\bbehaviou?ral scores?\b.*\bchang\w+\b|\bsame customers\b", re.I)),
    ("S1", re.compile(
        r"\bsplit\b|\bdisaggregat\w+\b|\bbreak (it|this|the issue) apart\b|"
        r"\bladder\b|\bseparate\b|\bhow many of (them|these)\b|"
        r"\bcompare .*(vintages?|cycles?|windows?)\b|\bmerely\b|"
        r"\bis this (just|merely|only)\b|\bsix[- ]month trend\b", re.I)),
)


class NoCase(LookupError):
    """The thread does not say which story this is. Never guessed at."""


@dataclass(frozen=True)
class Reading:
    """Which story, which step, and what established it."""

    case_id: str
    step: str
    from_thread: bool = True
    #: True when the reader clicked a chip rather than typing.
    exact: bool = False


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def case_of(context: dict[str, Any] | None) -> str:
    """Which of the nine this thread is about, from its Risk Case.

    The case id is on the card because `episode_cases` put it there as the
    entity. Reading it off the conversation rather than off the sentence is
    what lets "what should we do next?" be answered at all: the sentence names
    nothing, and the only thing that knows what "it" is, is the thread.
    """
    found = dict(context or {})
    case = found.get("risk_case") or {}
    if not isinstance(case, dict):
        return ""
    if str(case.get("about") or "") != ABOUT:
        return ""
    entity = str(case.get("entity_id") or "").upper()
    return entity if entity in ep.case_ids() else ""


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).strip()


def _exact_step(case_id: str, asked: str) -> str:
    """The step whose configured prompt this sentence IS.

    A chip click arrives as the prompt verbatim, so it is matched first and
    matched on the whole sentence. Substring matching would let a long
    free-text question that happens to quote a chip be read as that chip.
    """
    episode = ep.by_id(case_id)
    if episode is None:
        return ""
    want = _normalise(asked)
    if not want:
        return ""
    for step in episode.steps:
        if step.step == "S0":
            continue
        if _normalise(step.prompt) == want:
            return step.step
    return ""


def read(question: str, *, context: dict[str, Any] | None = None,
         state: Any = None, memory: Any = None) -> Reading | None:
    """Which step of which story this is, or None to let the planner answer."""
    asked = " ".join(str(question or "").split())
    if not asked:
        return None
    try:
        if not em.available():
            return None
    except Exception:  # noqa: BLE001
        return None

    case_id = case_of(context)
    if not case_id:
        # Outside one of these investigations nothing here is answerable: the
        # five questions do not name their own subject, and the sixth is the
        # card itself.
        return None

    exact = _exact_step(case_id, asked)
    if exact:
        return Reading(case_id=case_id, step=exact, exact=True)

    for step, pattern in _PATTERNS:
        if pattern.search(asked):
            return Reading(case_id=case_id, step=step)
    return None


def chips(case_id: str, visited: list[str] | None = None) -> list[dict[str, Any]]:
    """The five prompts above the composer, with what has been visited.

    Ordered as the story is, not by what has been answered: the reader is
    following an argument, and reordering it under them as they go would make
    the thread harder to hold rather than easier.
    """
    episode = ep.by_id(case_id)
    if episode is None:
        return []
    seen = set(visited or [])
    suggested = next((s.step for s in episode.chips if s.step not in seen), "")
    return [{
        "step": step.step,
        "label": step.chip_label,
        "prompt": step.prompt,
        "chart": step.chart,
        "visited": step.step in seen,
        "suggested_next": step.step == suggested,
        "scope": step.scope_label,
    } for step in episode.chips]


# ---------------------------------------------------------------------------
# Cohorts
# ---------------------------------------------------------------------------


def cohort_mask(data: pd.DataFrame, case_id: str, step: str) -> np.ndarray:
    """The facilities a step is about. A subset of the step before it."""
    eligible = em.eligible_mask(data, case_id)
    mask = em.issue_mask(data, case_id) & eligible
    level = STEP_EVIDENCE.get(step)
    if level:
        mask = mask & em.evidence_mask(data, level)
    if step in STEP_IN_POCKET:
        mask = mask & em.pocket_mask(data, case_id, eligible)
    return mask


def cohort_scope(case_id: str, step: str) -> dict[str, Any]:
    """The predicate tree a step's cohort snapshot stores.

    The full rule plus what this step added, so a breadcrumb can show both the
    root scope the case opened with and where the reader has got to.
    """
    from backend.retail import cohort as ch

    clauses = [ch.Predicate(c["field"], c["op"], c["value"], c["label"])
               for c in ep.predicate(case_id)["clauses"]]
    level = STEP_EVIDENCE.get(step)
    if level:
        clauses.append(ch.Predicate(
            "episode_evidence_state", ">=", level,
            "verification reached " + level.replace("_", " ").lower()))
    if step in STEP_IN_POCKET:
        episode = ep.by_id(case_id)
        clauses.append(ch.Predicate(
            "episode_pocket_flag", "==", True,
            f"inside {episode.pocket_label if episode else 'the named pocket'}"))
    return ch.predicate_ast(
        *clauses, describes=ep.predicate(case_id)["describes"])


def _ids(data: pd.DataFrame, mask: np.ndarray) -> tuple[list[str], list[str]]:
    rows = data.loc[mask]
    return (sorted(set(rows["customer_id"].astype(str))),
            sorted(set(rows["facility_id"].astype(str))))


def _totals(data: pd.DataFrame, mask: np.ndarray) -> dict[str, float]:
    rows = data.loc[mask]
    return {
        "gca_sar": round(float(pd.to_numeric(
            rows["gross_carrying_amount_sar"], errors="coerce").sum()), 2),
        "ead_sar": round(float(pd.to_numeric(
            rows["ead_base_sar"], errors="coerce").sum()), 2),
        "ecl_weighted_sar": round(float(pd.to_numeric(
            rows["ecl_weighted_sar"], errors="coerce").sum()), 2),
    }


def scope(month: str = "", case_id: str = "", step: str = "S0") -> dict[str, Any]:
    """Everything an export or a handoff needs about one step's cohort.

    The identifiers are in here. They are what the Borrower 360 export, the
    workbook and the What-If baseline all carry, and they are read once so the
    three cannot be three different populations.
    """
    at = em.resolve(month)
    if not at:
        return {"available": False, "because": "no published book"}
    data = em.frame(at)
    mask = cohort_mask(data, case_id, step)
    customers, facilities = _ids(data, mask)
    return {
        "available": True,
        "case_id": case_id,
        "step": step,
        "as_of": at,
        "customers": customers,
        "facilities": facilities,
        "customer_count": len(customers),
        "facility_count": len(facilities),
        "predicate": cohort_scope(case_id, step),
        "totals": _totals(data, mask),
        "evidence_level": STEP_EVIDENCE.get(step),
        "in_pocket": step in STEP_IN_POCKET,
        "metric_definition_ids": list(
            ep.by_id(case_id).step_by_id(step).metric_ids)
        if ep.by_id(case_id) and ep.by_id(case_id).step_by_id(step) else [],
    }


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------
#
# Every answer follows the shape the specification asks for: a conclusion, the
# chart or table behind it, two to five evidence observations, the
# counterargument, and the next recommended question. The counterargument is
# not a disclaimer bolted on — it is the story's own countercheck, and it is
# the sentence that stops the reader acting on the alert count.


def _handler() -> Any:
    from backend.orchestration.handlers import HandlerResult

    return HandlerResult


def _columns(rows: list[dict[str, Any]],
             units: dict[str, str] | None = None) -> list[dict[str, Any]]:
    if not rows:
        return []
    units = units or {}
    return [{"name": key,
             "type": "number" if isinstance(rows[0][key], (int, float))
             else "string",
             "unit": units.get(key, "")}
            for key in rows[0]]


def _trace(question: str, *, case_id: str, step: str, at: str,
           population: str, rows: int,
           steps: list[tuple[str, str]]) -> Any:
    """A short, true Trace. These answers read named columns and do arithmetic
    on them, so a Trace claiming a query would be a picture of something that
    did not happen."""
    from backend.trace.model import NodeType, TraceGraph, TraceNode

    graph = TraceGraph()
    graph.add_node(TraceNode(
        id="question", type=NodeType.USER_PROMPT, label="Question asked",
        config={"question": question}))
    read_node = graph.add_node(TraceNode(
        id="intent", type=NodeType.CAPABILITY,
        label=f"{case_id} {step}",
        config={"computation_required": True,
                "rule": ("Answered by reading the published book at the "
                         "reporting date and computing over it.")}))
    read_node.mark_ok()
    graph.connect("question", "intent")
    source = graph.add_node(TraceNode(
        id="book", type=NodeType.DATASET, label=em.BOOK,
        config={"periods": [at], "case": case_id}))
    source.mark_ok()
    graph.connect("intent", "book")
    cut = graph.add_node(TraceNode(
        id="population", type=NodeType.FILTER, label=population,
        config={"period": at, "step": step}))
    cut.mark_ok(rows_out=rows)
    graph.connect("book", "population")
    last = "population"
    for index, (label, detail) in enumerate(steps):
        node = graph.add_node(TraceNode(
            id=f"step{index}", type=NodeType.AGGREGATION, label=label,
            config={"definition": detail}))
        node.mark_ok(rows_out=rows)
        graph.connect(last, f"step{index}")
        last = f"step{index}"
    out = graph.add_node(TraceNode(
        id="result", type=NodeType.RESULT, label="Answer",
        config={"from": "the published retail book"}))
    out.mark_ok(rows_out=rows)
    graph.connect(last, "result")
    graph.compute_hashes()
    return graph


def _next_question(episode: Any, step: str) -> str:
    following = {"S1": "S2", "S2": "S3", "S3": "S4", "S4": "S5"}.get(step)
    if not following:
        return ""
    nxt = episode.step_by_id(following)
    return nxt.prompt if nxt else ""


def _scope_line(case_id: str, step: str, at: str,
                found: dict[str, Any]) -> str:
    """The sentence that keeps the cohort on screen in every answer."""
    episode = ep.by_id(case_id)
    grain = (episode.grain if episode else "facility")
    level = STEP_EVIDENCE.get(step)
    words = {ep.EV_VERIFIED: "verified", ep.EV_CORROBORATED: "corroborated"}
    what = words.get(level or "", "")
    inside = " inside the named pocket" if step in STEP_IN_POCKET else ""
    return (f"{found['customer_count']:,} customers and "
            f"{found['facility_count']:,} facilities"
            f"{(' with ' + what + ' evidence') if what else ''}{inside}, "
            f"at {at}, counted on a {grain} grain")


def answer(reading: Reading, *, period: str = "") -> Any:
    """The answer to one of the five, computed from the book."""
    builder = {"S1": _s1_disaggregate, "S2": _s2_characteristics,
               "S3": _s3_decompose, "S4": _s4_pocket,
               "S5": _s5_actions}.get(reading.step)
    if builder is None:
        return None
    at = em.resolve(period)
    if not at:
        return None
    try:
        return builder(reading.case_id, at, reading)
    except em.MissingEpisodeColumns as exc:
        logger.warning("%s %s could not be answered: %s",
                       reading.case_id, reading.step, exc)
        return None


def _base(case_id: str, step: str, at: str) -> tuple[Any, dict[str, Any], Any]:
    episode = ep.by_id(case_id)
    found = scope(at, case_id, step)
    data = em.frame(at)
    return episode, found, data


def _result(*, episode: Any, step: str, at: str, found: dict[str, Any],
            question: str, title: str, answer_text: str,
            rows: list[dict[str, Any]], units: dict[str, str] | None = None,
            detail: dict[str, Any] | None = None,
            chart: dict[str, Any] | None = None,
            trace_steps: list[tuple[str, str]] | None = None,
            warnings: list[str] | None = None) -> Any:
    HandlerResult = _handler()
    observations = (detail or {}).get("observations") or []
    nxt = _next_question(episode, step)
    return HandlerResult(
        answer=answer_text,
        title=title,
        rows=rows,
        columns=_columns(rows, units),
        values={"case_id": episode.case_id, "step": step, "as_of": at,
                "customers": found["customer_count"],
                "facilities": found["facility_count"]},
        detail={
            "scope": _scope_line(episode.case_id, step, at, found),
            "case_id": episode.case_id,
            "step": step,
            "as_of": at,
            "cohort": {k: found[k] for k in
                       ("customer_count", "facility_count", "totals")},
            "predicate": found["predicate"],
            "counterargument": episode.countercheck,
            "observations": observations,
            "definitions": [mc.definition(m) for m in
                            (episode.step_by_id(step).metric_ids
                             if episode.step_by_id(step) else [])],
            "next_question": nxt,
            "export_enabled": True,
            **{k: v for k, v in (detail or {}).items() if k != "observations"},
        },
        chart=chart or {},
        graph=_trace(question, case_id=episode.case_id, step=step, at=at,
                     population=_scope_line(episode.case_id, step, at, found),
                     rows=found["facility_count"],
                     steps=trace_steps or []),
        follow_ups=[nxt] if nxt else [],
        warnings=warnings or [],
        execution="analysis",
        execution_label="Computed from the published retail book",
    )


# ------------------------------------------------------------------ S1


#: What each story splits its alerts by at S1. A real column in every case,
#: because a disaggregation whose categories are not in the data is a picture.
_S1_SPLIT: dict[str, tuple[str, str, str]] = {
    "C01": ("dpd_bucket", "Days past due", "the delinquency ladder"),
    "C02": ("first_default_mob", "Months on book at first default",
            "when the first default fell"),
    "C03": ("payroll_missing_cycles", "Missing payroll cycles",
            "how many cycles the salary credit has been absent"),
    "C04": ("topup_sequence", "Top-up sequence",
            "how many times this borrower has topped up"),
    "C05": ("months_to_balloon", "Months to the final payment",
            "the maturity ladder"),
    "C06": ("valuation_evidence_state", "Valuation evidence",
            "whether the revision has been validated"),
    "C07": ("construction_stage", "Construction stage",
            "where the build has reached"),
    "C08": ("support_gap_cycles", "Unresolved cycles",
            "how many cycles the expected credit has not posted"),
    "C09": ("payment_stepdown_flag", "Contractual step-down",
            "whether the contract steps the payment down"),
    "C10": ("restructure_strategy", "Restructure strategy",
            "which arrangement was granted"),
}


def _bands(values: Any, column: str) -> Any:
    """Readable buckets for a numeric split, so a table is not 40 rows of ints."""
    numeric = pd.to_numeric(values, errors="coerce")
    if column == "months_to_balloon":
        return pd.cut(numeric, bins=[-0.01, 1, 2, 3, 6, 1e9],
                      labels=["0-30 days", "31-60 days", "61-90 days",
                              "91-180 days", "beyond 180 days"])
    if column == "first_default_mob":
        return pd.cut(numeric, bins=[-0.01, 2, 6, 1e9],
                      labels=["MOB 1-2", "MOB 3-6", "after MOB 6"])
    if numeric.notna().mean() > 0.5 and numeric.nunique() > 8:
        return pd.qcut(numeric, q=4, duplicates="drop")
    return values


def _s1_disaggregate(case_id: str, at: str, reading: Reading) -> Any:
    """Break the issue apart, and say how many of the alerts survive."""
    episode, found, data = _base(case_id, "S1", at)
    eligible = em.eligible_mask(data, case_id)
    alerts = em.issue_mask(data, case_id) & eligible
    verified = alerts & em.evidence_mask(data, ep.EV_VERIFIED)
    corroborated = alerts & em.evidence_mask(data, ep.EV_CORROBORATED)
    timing = alerts & ~verified

    column, label, what = _S1_SPLIT[case_id]
    split = _bands(data.loc[alerts, column], column)
    counts = split.value_counts(dropna=False).sort_index()
    rows = [{label: ("not recorded" if pd.isna(key) else str(key)),
             "Alerts": int(value),
             "Share of alerts (%)": round(value / max(int(alerts.sum()), 1)
                                          * 100, 1)}
            for key, value in counts.items()]

    trend = em.trend(at, case_id)
    n_alerts = int(alerts.sum())
    n_timing = int(timing.sum())
    n_verified = int(verified.sum())
    n_corroborated = int(corroborated.sum())

    answer_text = (
        f"{n_alerts:,} alerts at {at}, split by {what}. "
        f"{n_timing:,} of them are explained by timing, a documented "
        f"exception or a reporting difference and are not carried forward. "
        f"{n_verified:,} have a verified mechanism, and {n_corroborated:,} of "
        f"those are independently corroborated. This step narrows to the "
        f"{n_verified:,} verified alerts — "
        f"{found['customer_count']:,} customers across "
        f"{found['facility_count']:,} facilities — because acting on the "
        f"alert count would act on the {n_timing:,} that are not cases. "
        f"{episode.countercheck}")

    return _result(
        episode=episode, step="S1", at=at, found=found,
        question=reading.step, title=f"{episode.title}: alerts by {label.lower()}",
        answer_text=answer_text, rows=rows,
        units={"Share of alerts (%)": "%"},
        detail={
            "observations": [
                f"{n_alerts:,} alerts against {int(eligible.sum()):,} eligible "
                f"observations at {at}.",
                f"{n_timing:,} fail verification and are excluded here, not "
                f"deferred.",
                f"{n_verified:,} verified and {n_corroborated:,} corroborated; "
                f"the later steps work on the corroborated set.",
                f"The six-month trend is on its own denominator at each "
                f"month-end, so a month in which the eligible population grew "
                f"cannot read as a month in which the rate fell.",
            ],
            "attrition": {"alerts": n_alerts, "timing_or_exception": n_timing,
                          "verified": n_verified,
                          "corroborated": n_corroborated},
            "trend": trend,
        },
        chart={"type": "bar", "x": label, "y": ["Alerts"],
               "title": f"Alerts by {label.lower()}",
               "unit": "alerts"},
        trace_steps=[
            ("Evaluate the case rule", ep.predicate(case_id)["describes"]),
            ("Split the alerts", f"group by {column}"),
            ("Apply verification", "keep alerts whose evidence state has "
                                   "reached VERIFIED_DETAIL"),
        ])


# ------------------------------------------------------------------ S2


def _s2_characteristics(case_id: str, at: str, reading: Reading) -> Any:
    """The same IDs, their behavioural movement and their fixed origination."""
    episode, found, data = _base(case_id, "S2", at)
    view = em.scores(at, case_id)
    behaviour = view["behaviour"]
    application = view["application"]

    mask = cohort_mask(data, case_id, "S2")
    reference = behaviour["reference_month"]
    earlier = em.frame(reference)
    ids = set(data.loc[mask, "facility_id"].astype(str))
    then = earlier[earlier["facility_id"].astype(str).isin(ids)]

    def median(rows: Any, column: str) -> float | None:
        values = pd.to_numeric(rows.get(column), errors="coerce").dropna()
        return round(float(values.median()), 1) if len(values) else None

    rows = [
        {"Measure": "Behavioural score, median",
         reference: median(then, "behavioural_score"),
         at: median(data.loc[mask], "behavioural_score"),
         "Basis": "the same facilities observed twice"},
        {"Measure": "Original application score, median",
         reference: median(then, "app_score_value"),
         at: median(data.loc[mask], "app_score_value"),
         "Basis": "fixed at each decision date; it cannot move"},
        {"Measure": "12-month PD, median",
         reference: median(then, "pd_pit_12m_base"),
         at: median(data.loc[mask], "pd_pit_12m_base"),
         "Basis": "point-in-time, base scenario"},
    ]

    change = behaviour.get("change")
    moved = (f"{change:+.0f} points" if change is not None
             else "not comparable for this cohort")
    diagnosis = episode.diagnosis_model
    if diagnosis == "application":
        emphasis = (
            "Here the ORIGINAL application evidence is the diagnosis, not a "
            "monthly movement: the question is whether these loans should "
            "have been written, and the answer is in the decision, not in "
            "what has happened since.")
    elif diagnosis == "recovery":
        emphasis = (
            "These scores are CONTROLS in this story, not its subject. If "
            "they have barely moved, that is the finding: the loss is in "
            "severity, not in the borrower.")
    else:
        emphasis = (
            "The behavioural movement is the same facilities observed twice. "
            "The application score beside it has not moved and could not: an "
            "origination value is fixed at its own decision date, so a change "
            "in a portfolio average is a change in the population.")

    answer_text = (
        f"The {found['facility_count']:,} facilities from the previous step "
        f"are held fixed. Their median behavioural score moves {moved} between "
        f"{reference} and {at}, to "
        f"{behaviour['now'] if behaviour['now'] is not None else 'not available'}. "
        f"Their original application scores are unchanged. Inside the named "
        f"pocket the median original score is "
        f"{application['pocket'] if application['pocket'] is not None else 'not available'} "
        f"against "
        f"{application['outside'] if application['outside'] is not None else 'not available'} "
        f"in the matched population outside it. {emphasis}")

    coverage = behaviour.get("coverage") or {}
    warnings = []
    if coverage and not coverage.get("complete"):
        warnings.append(
            f"Behavioural scores cover {coverage.get('covered')} of "
            f"{coverage.get('eligible')} facilities in this cohort. The "
            f"uncovered ones are absent, not zero.")

    return _result(
        episode=episode, step="S2", at=at, found=found,
        question=reading.step,
        title=f"{episode.title}: the same customers, then and now",
        answer_text=answer_text, rows=rows,
        detail={
            "observations": [
                f"The identifiers are the S1 set: {found['customer_count']:,} "
                f"customers, unchanged by this step.",
                f"Behavioural median {behaviour.get('before')} at {reference} "
                f"to {behaviour.get('now')} at {at}.",
                f"Original application median {application.get('pocket')} in "
                f"the pocket against {application.get('outside')} outside it.",
                "Model versions and coverage are shown because a score "
                "compared across model versions is not a comparison.",
            ],
            "scores": view,
            "diagnosis_model": diagnosis,
        },
        chart={"type": "bar", "x": "Measure", "y": [reference, at],
               "title": f"Matched scores, {reference} against {at}"},
        trace_steps=[
            ("Hold the previous step's identifiers", "no re-query"),
            ("Read both months for those facilities",
             f"{reference} and {at}"),
            ("Compare medians", "same facilities, same model version"),
        ],
        warnings=warnings)


# ------------------------------------------------------------------ S3


#: The two features each story decomposes, and their units. Real columns in
#: every case: a decomposition whose variables the model does not use would be
#: manufacturing points for a feature that does not exist.
_S3_FEATURES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "C01": (("utilisation_ratio", "Utilisation", "ratio"),
            ("payment_to_statement_ratio", "Payment to statement", "ratio")),
    "C02": (("origination_dbr_ratio", "Debt burden at approval", "ratio"),
            ("origination_employment_tenure_months",
             "Employment tenure at approval", "months")),
    "C03": (("payroll_credit_sar", "Payroll credit", "SAR"),
            ("balance_buffer_months", "Cash buffer", "months")),
    "C04": (("verified_obligations_to_income", "Verified obligations to income",
             "ratio"),
            ("disposable_income_sar", "Residual income", "SAR")),
    "C05": (("balloon_funding_coverage_ratio", "Liquid coverage of the balloon",
             "ratio"),
            ("balloon_share_of_price", "Balloon share of price", "ratio")),
    "C06": (("expected_net_proceeds_sar", "Expected net proceeds", "SAR"),
            ("recovery_delay_months", "Recovery delay", "months")),
    "C07": (("milestone_delay_days", "Milestone delay", "days"),
            ("housing_outgoings_ratio", "Housing outgoings to income",
             "ratio")),
    "C08": (("support_received_sar", "Support credit received", "SAR"),
            ("balance_buffer_months", "Own-cash buffer", "months")),
    "C09": (("documented_pension_income_sar", "Documented recurring income",
             "SAR"),
            ("pension_obligations_to_income", "Obligations to documented income",
             "ratio")),
    "C10": (("restructure_payments_met", "Scheduled payments met", "count"),
            ("disposable_income_sar", "Residual income", "SAR")),
}


def _s3_decompose(case_id: str, at: str, reading: Reading) -> Any:
    """Decompose what moved, and date it against the arrears.

    Which decomposition depends on the story, and that is the point. The
    recovery story decomposes the LOSS, holding the borrower fixed; the vintage
    story decomposes the ORIGINAL decision, which by construction has not moved
    since; everything else decomposes the behavioural drivers and shows that
    the non-arrears ones moved first.
    """
    episode, found, data = _base(case_id, "S3", at)
    mask = cohort_mask(data, case_id, "S3")
    months = [m for m in em.months() if m <= at][-em.TREND_WINDOWS:]
    ids = set(data.loc[mask, "facility_id"].astype(str))

    features = _S3_FEATURES[case_id]
    timeline: list[dict[str, Any]] = []
    for month in months:
        earlier = em.frame(month)
        rows = earlier[earlier["facility_id"].astype(str).isin(ids)]
        entry: dict[str, Any] = {"Month": month}
        for column, label, _unit in features:
            values = pd.to_numeric(rows.get(column), errors="coerce").dropna()
            entry[label] = round(float(values.median()), 4) if len(values) else None
        dpd = pd.to_numeric(rows.get("dpd"), errors="coerce")
        entry["Share in arrears (%)"] = (
            round(float((dpd > 0).mean() * 100), 1) if len(dpd) else None)
        entry["Behavioural score, median"] = (
            round(float(pd.to_numeric(rows.get("behavioural_score"),
                                      errors="coerce").dropna().median()), 1)
            if len(rows) else None)
        timeline.append(entry)

    first, last = (timeline[0], timeline[-1]) if timeline else ({}, {})
    moves = []
    for _column, label, unit in features:
        before, now = first.get(label), last.get(label)
        if before is None or now is None:
            continue
        moves.append({"Driver": label, months[0]: before, at: now,
                      "Change": round(now - before, 4), "Unit": unit})

    # When did the features move relative to the arrears? The question S3 is
    # actually asking, answered from the series rather than asserted.
    arrears = [(e["Month"], e.get("Share in arrears (%)")) for e in timeline]
    moved_first = ""
    if len(timeline) >= 3 and moves:
        first_feature_move = next(
            (e["Month"] for e in timeline[1:]
             if any(e.get(label) is not None and first.get(label) is not None
                    and abs(e[label] - first[label])
                    > abs(last.get(label, 0) - first.get(label, 0)) * 0.25
                    for _c, label, _u in features)), "")
        first_arrears_move = next(
            (m for m, value in arrears[1:]
             if value is not None and arrears[0][1] is not None
             and value > arrears[0][1] + 1.0), "")
        if first_feature_move and first_arrears_move:
            if first_feature_move < first_arrears_move:
                moved_first = (
                    f"The drivers moved at {first_feature_move}; the share in "
                    f"arrears did not move until {first_arrears_move}. That "
                    f"ordering is in the data, and it is what makes them "
                    f"causes to look at rather than consequences to discount. "
                    f"It is not proof of causation.")
            else:
                moved_first = (
                    f"The arrears moved at {first_arrears_move}, at or before "
                    f"the drivers at {first_feature_move}. On this evidence "
                    f"the drivers cannot be said to have led, and the honest "
                    f"reading is that they moved together.")

    if episode.diagnosis_model == "recovery":
        conclusion = (
            f"Holding the borrower fixed: over these "
            f"{found['facility_count']:,} facilities the behavioural score "
            f"moves {last.get('Behavioural score, median')} against "
            f"{first.get('Behavioural score, median')} at {months[0]}, and "
            f"the share in arrears is "
            f"{last.get('Share in arrears (%)')}%. What moved is the "
            f"recovery: expected net proceeds and the delay before they are "
            f"realised. The loss is severity, not default propensity.")
    elif episode.diagnosis_model == "application":
        conclusion = (
            f"These {found['facility_count']:,} facilities' decision-time "
            f"values are immutable, so the table below is what was true when "
            f"they were approved rather than a monthly movement. That is the "
            f"diagnosis: the exposure was taken on these values.")
    else:
        conclusion = (
            f"Over these {found['facility_count']:,} corroborated facilities, "
            + "; ".join(
                f"{m['Driver'].lower()} moves from {m[months[0]]} to {m[at]} "
                f"{m['Unit']}" for m in moves)
            + ".")

    answer_text = (
        f"{conclusion} {moved_first} These are model INPUTS and their raw "
        f"units, shown beside the score rather than converted into it: a "
        f"contribution in points and a change in a ratio are different "
        f"quantities, and adding them would be adding different things. "
        f"{episode.countercheck}")

    return _result(
        episode=episode, step="S3", at=at, found=found,
        question=reading.step,
        title=f"{episode.title}: what moved, and when",
        answer_text=answer_text, rows=moves or timeline,
        detail={
            "observations": [
                f"{found['facility_count']:,} corroborated facilities, held "
                f"fixed across {months[0]} to {at}.",
                *[f"{m['Driver']}: {m[months[0]]} to {m[at]} {m['Unit']}."
                  for m in moves],
                moved_first or ("The ordering of the driver and arrears "
                                "movements cannot be established from six "
                                "monthly observations of this cohort."),
            ],
            "timeline": timeline,
            "timeline_columns": _columns(timeline),
            "diagnosis_model": episode.diagnosis_model,
            "units_warning": (
                "Raw feature values, not score points or SHAP units. They are "
                "not added together."),
        },
        chart={"type": "line", "x": "Month",
               "y": [label for _c, label, _u in features],
               "rows": timeline,
               "title": f"{episode.title}: driver timelines",
               "note": ("Each series is on its own units. Read the series, "
                        "not the gap between them.")},
        trace_steps=[
            ("Hold the corroborated identifiers", "no re-query"),
            ("Read six months for those facilities", ", ".join(months)),
            ("Median each driver per month", "raw model inputs"),
            ("Date the driver moves against the arrears",
             "from the series, not asserted"),
        ])


# ------------------------------------------------------------------ S4


def _s4_pocket(case_id: str, at: str, reading: Reading) -> Any:
    """Where it is concentrated, normalised, with both denominators shown."""
    episode, found, data = _base(case_id, "S4", at)
    view = em.concentration(at, case_id)
    pocket, outside = view["pocket"], view["outside"]

    rows = [
        {"Population": episode.pocket_label,
         "Eligible": pocket["eligible"], "Cases": pocket["issue"],
         "Incidence (%)": round((pocket["incidence"] or 0) * 100, 1),
         "Share of eligible (%)": round((pocket["share_of_eligible"] or 0) * 100, 1),
         "Share of cases (%)": round((pocket["share_of_cases"] or 0) * 100, 1)},
        {"Population": "Matched, outside the pocket",
         "Eligible": outside["eligible"], "Cases": outside["issue"],
         "Incidence (%)": round((outside["incidence"] or 0) * 100, 1),
         "Share of eligible (%)": round(
             (1 - (pocket["share_of_eligible"] or 0)) * 100, 1),
         "Share of cases (%)": round(
             (1 - (pocket["share_of_cases"] or 0)) * 100, 1)},
    ]

    answer_text = (
        f"The named pocket — {episode.pocket_label} — holds "
        f"{pocket['eligible']:,} of {view['eligible']:,} eligible "
        f"observations ({(pocket['share_of_eligible'] or 0) * 100:.0f}%) and "
        f"{pocket['issue']:,} of {view['issue']:,} cases "
        f"({(pocket['share_of_cases'] or 0) * 100:.1f}%). Its incidence is "
        f"{(pocket['incidence'] or 0) * 100:.1f}% against "
        f"{(outside['incidence'] or 0) * 100:.1f}% in the matched population "
        f"outside it, a {view['rate_ratio']}x rate ratio. Rates, not counts: "
        f"a larger group has more cases without being riskier. This step "
        f"narrows to the {found['customer_count']:,} customers and "
        f"{found['facility_count']:,} facilities that are both corroborated "
        f"and inside the pocket — the policy-review scope. "
        f"{episode.countercheck}")

    return _result(
        episode=episode, step="S4", at=at, found=found,
        question=reading.step,
        title=f"{episode.title}: normalised incidence",
        answer_text=answer_text, rows=rows,
        units={"Incidence (%)": "%", "Share of eligible (%)": "%",
               "Share of cases (%)": "%"},
        detail={
            "observations": [
                f"Inside: {pocket['issue']:,} of {pocket['eligible']:,}.",
                f"Outside: {outside['issue']:,} of {outside['eligible']:,}.",
                f"Rate ratio {view['rate_ratio']}x, on sample sizes of "
                f"{pocket['eligible']:,} and {outside['eligible']:,}.",
                "Both denominators are shown because a rate ratio without "
                "them cannot be challenged.",
            ],
            "concentration": view,
        },
        chart={"type": "bar", "x": "Population", "y": ["Incidence (%)"],
               "title": "Incidence inside and outside the pocket",
               "unit": "% of eligible observations"},
        trace_steps=[
            ("Cut the eligible population by the pocket",
             ", ".join(episode.dimension_columns)),
            ("Count cases in each part", ep.predicate(case_id)["describes"]),
            ("Normalise", "cases divided by eligible, in each part"),
        ])


# ------------------------------------------------------------------ S5


def _s5_actions(case_id: str, at: str, reading: Reading) -> Any:
    """Sequenced actions against effective-dated clauses, none of them approved.

    The clauses come from the policy store, which knows their status. No
    approved bank policy was supplied with this work, so every clause is a
    demonstration draft and the answer says so in its first line rather than in
    a footnote — a recommendation that reads as compliant when it is not is
    the most expensive sentence this product could produce.
    """
    from backend.retail import episode_policy as pol

    episode, found, data = _base(case_id, "S5", at)
    actions = pol.actions_for(case_id, as_of=at)
    if not actions:
        return None

    rows = [{
        "Order": action["sequence"],
        "Action": action["action"],
        "Owner": action["owner"],
        "By when": action["timing"],
        "Clause": f"{action['policy_id']} {action['version']} "
                  f"clause {action['clause']}",
        "Status": action["status"],
        "Approval": action["approval"],
    } for action in actions]

    scenarios = pol.scenarios_for(case_id, at, found)

    answer_text = (
        f"{len(actions)} sequenced actions for the "
        f"{found['customer_count']:,} customers and "
        f"{found['facility_count']:,} facilities this investigation has "
        f"narrowed to, each against a clause with an owner, a deadline and an "
        f"approval requirement. "
        f"Every clause below is a DEMONSTRATION DRAFT: no approved bank "
        f"policy was supplied with this work, so none of this is Arab "
        f"National Bank policy, nothing here asserts compliance, and nothing "
        f"is executed. "
        + " ".join(f"{a['sequence']}. {a['action']}" for a in actions)
        + f" {episode.countercheck}")

    return _result(
        episode=episode, step="S5", at=at, found=found,
        question=reading.step,
        title=f"{episode.title}: sequenced actions",
        answer_text=answer_text, rows=rows,
        detail={
            "observations": [
                f"Scope: exactly the {found['customer_count']:,} customers "
                f"from the previous step. Nothing is widened here.",
                "Each action names its clause, its owner, its deadline, its "
                "approval requirement and its customer safeguard.",
                "No action is executed and no balance or contractual limit is "
                "changed by this answer.",
                "Draft clauses cannot support a compliance claim; the policy "
                "the bank has approved has to be supplied before any of this "
                "is more than a proposal.",
            ],
            "actions": actions,
            "scenarios": scenarios,
            "policy_status": "DEMO_DRAFT - NOT BANK APPROVED",
            "execution": "none; these are proposals for human approval",
        },
        chart={},
        trace_steps=[
            ("Take the previous step's scope", "no widening"),
            ("Retrieve effective-dated clauses",
             f"{episode.policy_id} {episode.policy_version} at {at}"),
            ("Check applicability", "product scope and effective date"),
        ],
        warnings=[
            "These clauses are demonstration drafts that no bank has "
            "approved. They cannot support a compliance claim and nothing "
            "here may be executed on a customer."])
