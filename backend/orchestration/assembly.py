"""
Turning an answered request into an Investigation.

The Investigation is what the API returns and what the Trace is drawn from, so
this module decides what a reader sees. Two rules shape all of it.

**Every figure in the prose came from the result.** `_grounded` checks that
before the narrative is returned, and a number that cannot be traced to a
returned value is a bug rather than a style problem — the whole product claim
is that CreditProbe does not state figures the engine did not produce.

**The Trace shows what actually ran.** A metadata answer gets a metadata Trace;
an analysis gets the full lineage with its mathematical query. Neither borrows
the other's shape to look more impressive.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.orchestration import analysis_planner as ap
from backend.orchestration import capability as cap
from backend.orchestration.executor import ExecutedStep, Investigation
from backend.orchestration.interpreter import Finding, Metric, Narrative
from backend.orchestration.schema import (
    AnalysisPlan,
    PlanStep,
    Scope,
    StepRole,
)
from backend.trace.model import NodeStatus, NodeType, TraceGraph, TraceNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- grounding


def _numbers(text: str) -> set[str]:
    """Every figure in a sentence, normalised for comparison."""
    out: set[str] = set()
    for raw in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text or ""):
        cleaned = raw.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        out.add(f"{value:.4f}".rstrip("0").rstrip("."))
    return out


def grounded_values(runtime: Any, extra: dict[str, Any] | None = None) -> set[str]:
    """Every figure the result actually contains, in the same normal form."""
    out: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            # Prose rounds, and it quotes a magnitude without its sign: "fell by
            # 398.14" is the same fact as a change of -398.1368. Both forms and
            # the roundings a sentence would use are accepted, because the
            # check is meant to catch invented figures rather than formatting.
            number = float(value)
            for candidate in (number, abs(number)):
                out.add(f"{candidate:.4f}".rstrip("0").rstrip("."))
                for places in (0, 1, 2):
                    out.add(f"{round(candidate, places):.4f}"
                            .rstrip("0").rstrip("."))
        elif isinstance(value, str):
            out.update(_numbers(value))

    for key, value in (extra or {}).items():
        del key
        add(value)
    if runtime is not None:
        add(runtime.row_count)
        for row in runtime.rows:
            for value in row.values():
                add(value)
        for value in (runtime.summary or {}).values():
            add(value)
    return out


def ungrounded(text: str, allowed: set[str]) -> list[str]:
    """Figures in the prose that the result does not contain.

    Years and small counts are excluded: "over the latest year" and "three
    conditions" are prose about the question, not claims about the portfolio.
    """
    out: list[str] = []
    for figure in _numbers(text):
        if figure in allowed:
            continue
        try:
            value = float(figure)
        except ValueError:
            continue
        if value.is_integer() and (1900 <= value <= 2100 or 0 <= value <= 12):
            continue
        out.append(figure)
    return out


# ------------------------------------------------------------- metadata answers


def from_handler(question: str, reading: cap.Reading,
                 result: Any, *, duration_ms: int,
                 mode: dict[str, Any]) -> Investigation:
    """An Investigation for a question answered from governed metadata."""
    scope = Scope(focus=reading.label, output="list",
                  period_requirement="none", period_specified=False,
                  period_source="not needed for this request")
    plan = AnalysisPlan(
        question=question, intent=reading.objective or question, scope=scope,
        steps=[], planner=reading.source, model_name=reading.model or None,
        follow_ups=list(result.follow_ups),
        notes=["This request was answered from the governed catalogue. No "
               "analytical engine ran and no figure was computed."],
    )
    narrative = Narrative(
        direct_answer=result.answer, summary=result.answer,
        findings=[], interpretation="", interpretation_points=[],
        caveats=list(result.warnings),
    )
    step = ExecutedStep(
        index=0, analysis_id=f"capability_{reading.intent.lower()}",
        title=reading.label, rationale=reading.reasoning,
        params={"intent": reading.intent}, filters={}, period="",
        status="succeeded", certification="metadata", analysis_version="",
        duration_ms=duration_ms,
        result={
            "values": dict(result.values), "units": {},
            "input_row_count": len(result.rows),
            "meta": {"execution": "metadata", "intent": reading.intent},
            "rows": result.rows, "columns": result.columns,
            "warnings": list(result.warnings), "chart": {},
            "truncated": False, "certification": "metadata",
            "certification_label": "Governed metadata",
            "capability": reading.to_dict(),
            "detail": result.detail,
        },
        error=None,
        trace=result.graph.to_dict() if result.graph else None,
        node_hashes={}, role="primary",
    )
    graph = result.graph or TraceGraph()
    return Investigation(
        question=question, plan=plan, steps=[step], narrative=narrative,
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=duration_ms, status="succeeded",
        mode={**mode, "execution": "metadata",
              "execution_label": "Governed metadata",
              "intent": reading.intent},
    )


# ------------------------------------------------------------ analytical answers


def from_analysis(question: str, reading: cap.Reading, build: ap.AnalysisBuild,
                  runtime: Any, *, duration_ms: int,
                  mode: dict[str, Any]) -> Investigation:
    """An Investigation for a question the runtime computed."""
    scope = Scope(
        focus=build.summary or reading.objective,
        dimension=build.dimension or None,
        output={"aggregate": "distribution", "ranking": "ranking",
                "cohort": "ranking", "movement": "movement"}[build.shape],
        period_requirement=("two_period" if build.shape in
                            (ap.COHORT, ap.MOVEMENT) else "point_in_time"),
        period_specified=bool(reading.periods),
        from_period=build.opening or None,
        to_period=build.closing or build.period or None,
        period_source=("read from the question" if reading.periods
                       else "the latest published period"),
        filters={f: v for f, v in build.filters},
    )
    plan = AnalysisPlan(
        question=question, intent=build.summary, scope=scope,
        steps=[PlanStep(
            analysis_id="dynamic_analysis",
            title=_title(build), rationale=_rationale(build),
            params={"shape": build.shape, "grain": build.grain,
                    "period": build.period, "opening_period": build.opening,
                    "closing_period": build.closing,
                    "datasets": build.datasets, "top_n": build.top_n},
            filters={f: v for f, v in build.filters},
            role=StepRole.PRIMARY,
        )],
        planner=reading.source, model_name=reading.model or None,
        follow_ups=_follow_ups(build),
        notes=[_composed_note(build)],
    )

    # Computed once, then quoted. Anything the prose says is a figure the
    # result carries — a narrative that re-derives a total is a second
    # computation that can disagree with the answer it is describing.
    values = _values(build, runtime)
    narrative = _narrative(question, build, runtime, values)
    step = ExecutedStep(
        index=0, analysis_id="dynamic_analysis", title=_title(build),
        rationale=_rationale(build),
        params={"shape": build.shape, "grain": build.grain,
                "period": build.period, "opening_period": build.opening,
                "closing_period": build.closing, "datasets": build.datasets,
                "dimension": build.dimension, "top_n": build.top_n},
        filters={f: v for f, v in build.filters},
        period=build.closing or build.period, status="succeeded",
        certification=runtime.certification, analysis_version="",
        duration_ms=runtime.duration_ms,
        result={
            "values": values,
            "units": _units(build),
            "input_row_count": runtime.row_count,
            "meta": {"execution": runtime.certification, "shape": build.shape,
                     "grain": build.grain},
            "rows": runtime.rows, "columns": runtime.columns,
            "warnings": [*runtime.warnings, *build.warnings],
            "chart": runtime.chart, "truncated": runtime.truncated,
            "certification": runtime.certification,
            "certification_label": runtime.certification_label,
            "capability": reading.to_dict(),
            "reading": build.to_dict(),
            "plan": build.plan,
            "query": runtime.query.to_dict() if runtime.query else None,
            "joins": runtime.joins,
            "reconciliation": runtime.reconciliation,
            "fingerprint": runtime.fingerprint,
            "datasets": build.datasets,
            "explanation": build.summary,
            "formulas": formulas(build),
            "plain_english": plain_english(build),
            "join_plan": (build.request.resolution.to_dict()
                          if build.request is not None
                          and build.request.resolution else None),
        },
        error=None,
        trace=None, node_hashes={}, role="primary",
    )

    graph = analysis_graph(question, reading, build, runtime, narrative)
    step.trace = graph.to_dict()
    return Investigation(
        question=question, plan=plan, steps=[step], narrative=narrative,
        graph=graph, node_hashes=graph.compute_hashes(),
        duration_ms=duration_ms, status="succeeded",
        mode={**mode, "execution": runtime.certification,
              "execution_label": runtime.certification_label,
              "intent": reading.intent, "datasets": build.datasets},
    )


def _title(build: ap.AnalysisBuild) -> str:
    return {
        ap.AGGREGATE: "Aggregated across the governed book",
        ap.RANKING: "Ranked from the governed book",
        ap.COHORT: "Composed across several governed sources",
        ap.MOVEMENT: "Measured between two reporting periods",
    }[build.shape]


def _rationale(build: ap.AnalysisBuild) -> str:
    sources = ", ".join(build.datasets)
    if build.shape in (ap.COHORT, ap.MOVEMENT):
        return (f"No certified analysis reads {sources} together, so "
                "CreditProbe composed one from the governed relationship model.")
    return (f"CreditProbe composed this from {sources} rather than selecting a "
            "pre-built analysis: the question named its own measure, grouping "
            "and period.")


def _composed_note(build: ap.AnalysisBuild) -> str:
    return ("Composed for this question and run through the governed runtime — "
            "the same catalogue, validator and parameterised SQL every "
            "certified analysis uses. It is not a certified method.")


def _values(build: ap.AnalysisBuild, runtime: Any) -> dict[str, Any]:
    values: dict[str, Any] = {"matching": runtime.row_count}
    if build.period:
        values["period"] = build.period
    if build.opening:
        values["opening_period"] = build.opening
        values["closing_period"] = build.closing
    # The headline figure of an aggregate is its total, and it must come from
    # the returned rows rather than be recomputed here — a second computation
    # is a second thing that can disagree with the answer.
    if build.shape == ap.AGGREGATE and build.matches and runtime.rows:
        column = build.matches[0].field
        if all(isinstance(r.get(column), (int, float)) for r in runtime.rows):
            values["total"] = round(
                sum(float(r[column]) for r in runtime.rows), 4)
    # How much of the population the returned rows account for. A ranking that
    # does not say this invites the reader to assume the top five are the book.
    # A movement's totals are the answer, so they are result values rather than
    # something the prose works out for itself.
    if build.shape == ap.MOVEMENT and not build.conditions and build.matches:
        column = build.matches[0].field
        by_period = {str(r.get("period")): r for r in runtime.rows
                     if r.get("period")}
        if build.dimension:
            opening_total = sum(
                float(r.get(column) or 0.0) for r in runtime.rows
                if str(r.get("period")) == build.opening)
            closing_total = sum(
                float(r.get(column) or 0.0) for r in runtime.rows
                if str(r.get("period")) == build.closing)
        else:
            opening_total = float(
                (by_period.get(build.opening) or {}).get(column) or 0.0)
            closing_total = float(
                (by_period.get(build.closing) or {}).get(column) or 0.0)
        values["opening_total"] = round(opening_total, 4)
        values["closing_total"] = round(closing_total, 4)
        values["change"] = round(closing_total - opening_total, 4)
        if opening_total:
            values["change_pct"] = round(
                (closing_total - opening_total) / abs(opening_total) * 100, 4)

    if build.shape == ap.RANKING and build.matches and runtime.rows:
        share_column = f"{build.matches[0].field}_share_pct"
        if all(isinstance(r.get(share_column), (int, float))
               for r in runtime.rows):
            values["share_covered_pct"] = round(
                sum(float(r[share_column]) for r in runtime.rows), 4)
    return values


def _units(build: ap.AnalysisBuild) -> dict[str, str]:
    units = {"matching": "count"}
    if build.matches:
        units["total"] = build.matches[0].concept.unit or ""
    return units


def _follow_ups(build: ap.AnalysisBuild) -> list[str]:
    out: list[str] = []
    if build.shape == ap.AGGREGATE and build.dimension:
        out.append(f"Show the largest customers in the biggest {build.dimension}.")
    if build.shape == ap.RANKING and build.filters:
        out.append("Show the same ranking across the whole book.")
    if build.shape in (ap.COHORT, ap.MOVEMENT):
        out.append("Which sectors do those customers sit in?")
    if build.matches:
        out.append(f"How has {build.matches[0].concept.label} moved over the "
                   "latest year?")
    return out[:3]


# ------------------------------------------------------------------ narrative


def _narrative(question: str, build: ap.AnalysisBuild, runtime: Any,
               values: dict[str, Any]) -> Narrative:
    """The answer, and CreditProbe's reading of it.

    Assembled from the result rather than composed by a model in offline mode,
    and every figure in it is quoted from a returned value. `from_analysis`
    checks that before returning.
    """
    rows = runtime.rows
    count = runtime.row_count
    measure = build.matches[0] if build.matches else None
    label = measure.concept.label if measure else "the measure"
    unit = (measure.concept.unit or "") if measure else ""

    metrics: list[Metric] = []
    findings: list[Finding] = []

    if build.shape == ap.AGGREGATE:
        column = measure.field if measure else ""
        total = float(values.get("total") or 0.0)
        direct = (f"{_fmt(total)} {unit} of {label} across {count} "
                  f"{build.dimension or 'group'}"
                  f"{'s' if count != 1 else ''} at {build.period}.")
        metrics.append(Metric(label=f"Total {label}", value=round(total, 2),
                              unit=unit, direction="neutral"))
        if rows and build.dimension:
            top = rows[0]
            share = top.get(f"{column}_share_pct")
            share_text = (f", {float(share):.1f}% of the total"
                          if isinstance(share, (int, float)) else "")
            findings.append(Finding(
                text=(f"{top.get(build.dimension)} is the largest at "
                      f"{_fmt(top[column])} {unit}{share_text}."),
                tone="neutral",
                evidence=[{"label": str(top.get(build.dimension)),
                           "value": round(float(top[column]), 2), "unit": unit}]))
    elif build.shape == ap.RANKING:
        direct = (f"The {count} largest {_subject(build, count)} by {label} "
                  f"at {build.period}.")
        column = measure.field if measure else ""
        share_column = f"{column}_share_pct"
        if rows:
            top = rows[0]
            metrics.append(Metric(
                label=f"Largest {label}",
                value=round(float(top.get(column, 0)), 2), unit=unit,
                direction="neutral",
                hint=str(top.get("borrower_name") or top.get("customer_id") or "")))
            if share_column in top:
                covered = float(values.get("share_covered_pct") or 0.0)
                scope = (", ".join(v for _, v in build.filters)
                         or "the whole book")
                findings.append(Finding(
                    text=(f"Together these {count} hold {covered:.1f}% of "
                          f"{scope} {label}."),
                    tone="neutral",
                    evidence=[{"label": "share of " + scope,
                               "value": round(covered, 1), "unit": "%"}]))
    elif build.shape == ap.MOVEMENT and not build.conditions:
        column = measure.field if measure else ""
        opening_total = float(values.get("opening_total") or 0.0)
        closing_total = float(values.get("closing_total") or 0.0)
        change = float(values.get("change") or 0.0)
        change_pct = values.get("change_pct")
        moved = "rose" if change > 0 else "fell" if change < 0 else "was unchanged"
        pct = (f" ({abs(float(change_pct)):.1f}%)"
               if isinstance(change_pct, (int, float)) and change else "")
        direct = (f"{label.capitalize()} {moved} from {_fmt(opening_total)} to "
                  f"{_fmt(closing_total)} {unit} between {build.opening} and "
                  f"{build.closing} — a change of {_fmt(abs(change))} {unit}"
                  f"{pct}.")
        metrics.append(Metric(
            label=f"{label.capitalize()} at {build.closing}",
            value=round(closing_total, 2), unit=unit,
            change=round(change, 2), change_unit=unit,
            direction="up-is-bad" if (measure and measure.concept.higher_is_worse)
            else "up-is-good"))
        if build.dimension and rows:
            biggest = max(
                rows, key=lambda r: abs(float(r.get(column) or 0.0)))
            findings.append(Finding(
                text=(f"{biggest.get(build.dimension)} carries the largest "
                      f"{label} at {_fmt(biggest.get(column))} {unit}."),
                tone="neutral", evidence=[]))
    else:
        stated = ", ".join(c.describe() for c in build.conditions)
        direct = (f"{count} {_subject(build, count)} where {stated}, between "
                  f"{build.opening} and {build.closing}.")
        metrics.append(Metric(label=f"{build.grain.title()}s matching",
                              value=count, unit="count",
                              direction="up-is-bad"))
        if rows:
            named = rows[0].get("borrower_name") or rows[0].get("customer_id")
            if named:
                findings.append(Finding(
                    text=f"{named} is the worst by the measures named.",
                    tone="negative", evidence=[]))

    interpretation = _interpretation(build, runtime, count)
    caveats = notable(runtime.warnings) + list(build.warnings)

    return Narrative(
        direct_answer=direct, summary=direct, findings=findings,
        interpretation=interpretation,
        interpretation_points=[], metrics=metrics, caveats=caveats,
    )


#: Warnings that describe normal governed behaviour rather than something a
#: reader has to weigh. They stay on the Trace and in Data & method, where a
#: reviewer looks for them; repeating all seven under every answer trains
#: people to skip the two that matter.
_ROUTINE = (
    "joins on a single key",
    "is an as-of join: each row takes the latest",
)


def notable(warnings: list[str]) -> list[str]:
    """The warnings worth putting under the answer itself."""
    return [w for w in warnings
            if not any(routine in w for routine in _ROUTINE)]


def _plural(word: str, count: int) -> str:
    """English plurals for the handful of grains an answer is reported at."""
    if count == 1:
        return word
    return {"facility": "facilities", "company": "companies"}.get(
        word, word + "s")


def _subject(build: ap.AnalysisBuild, count: int) -> str:
    """"Real Estate customers", "facilities" — the population, in words.

    A filter value is read as an adjective where it is a name and named
    explicitly where it is a code, because "3 3 facilities" is not a sentence.
    """
    grain = _plural(build.grain, count)
    adjectives = [v for f, v in build.filters
                  if not str(v).isdigit() and len(str(v)) > 2]
    coded = [f"{f} {v}" for f, v in build.filters
             if str(v).isdigit() or len(str(v)) <= 2]
    subject = " ".join([*adjectives, grain])
    if coded:
        subject += " in " + ", ".join(coded)
    return subject


def _interpretation(build: ap.AnalysisBuild, runtime: Any, count: int) -> str:
    """One or two sentences reading the result. No unrelated commentary.

    Every figure here is one the result carries. Where there is nothing to read
    beyond the answer itself, this is empty rather than padded — a paragraph
    restating the number in longer words is not an interpretation.
    """
    if count == 0:
        if build.shape in (ap.COHORT, ap.MOVEMENT):
            return ("No customer met every condition over this window. That is "
                    "the answer rather than a gap: relaxing any one of them "
                    "would return a population.")
        return "Nothing in the governed data matched."

    if build.shape == ap.MOVEMENT and not build.conditions:
        return ("Both figures are totals across the same population at the two "
                "dates, so the change is a movement in the book rather than a "
                "change in what was counted.")
    if build.shape in (ap.COHORT, ap.MOVEMENT) and build.conditions:
        stated = " and ".join(c.describe() for c in build.conditions)
        return (f"These are the {build.grain}s where {stated} held together "
                f"between {build.opening} and {build.closing}. Each condition "
                "was tested on the same joined population, so the count is the "
                "intersection rather than the sum of three lists.")
    if build.shape == ap.RANKING and build.filters:
        scope = ", ".join(v for _, v in build.filters)
        return (f"Shares are of {scope} exposure, not of the whole book — the "
                "question asked about that population.")
    if build.shape == ap.AGGREGATE and build.dimension:
        return (f"Ordered largest first. The figures are sums across every "
                f"facility in each {build.dimension} at {build.period}.")
    return ""


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


# ------------------------------------------------------- formulas and English


def formulas(build: ap.AnalysisBuild) -> list[dict[str, str]]:
    """Every derived column, as the arithmetic a reviewer would check.

    Written out rather than described. "ECL change %" means nothing without the
    expression, and a reviewer who has to infer it from SQL is being asked to
    do the product's job.
    """
    out: list[dict[str, str]] = []
    for condition in build.conditions:
        match = next((m for m in build.matches if m.field == condition.field),
                     None)
        label = match.concept.label if match else condition.field
        if condition.kind == "change_pct":
            out.append({
                "name": f"{label} change %",
                "column": condition.column,
                "formula": (f"(closing {label} − opening {label}) "
                            f"÷ |opening {label}| × 100"),
                "means": f"How much {label} moved, in per cent.",
            })
        elif condition.kind == "change_abs" and match and match.concept.is_ordinal:
            out.append({
                "name": f"{label} notch movement",
                "column": condition.column,
                "formula": f"grade(closing {label}) − grade(opening {label})",
                "means": ("Positive is a downgrade: the grade scale runs 1 "
                          "strongest to 10 weakest."),
            })
        elif condition.kind == "change_abs":
            out.append({
                "name": f"{label} change",
                "column": condition.column,
                "formula": f"closing {label} − opening {label}",
                "means": f"The movement in {label}, in its own unit.",
            })

    # The share column, wherever it was computed. A grouped aggregate gets one
    # too, and a formula shown for a ranking but not for the aggregate beside
    # it would look like the two were computed differently.
    if build.matches:
        measure = build.matches[0]
        if f"{measure.field}_share_pct" in str(build.plan):
            scope = ", ".join(v for _, v in build.filters) or "the population"
            of = build.dimension or build.grain
            out.append({
                "name": f"{measure.concept.label} share %",
                "column": f"{measure.field}_share_pct",
                "formula": (f"{of} {measure.concept.label} ÷ total "
                            f"{measure.concept.label} across {scope} × 100"),
                "means": f"Each row's share of {scope}, not of the whole book.",
            })
    return out


def plain_english(build: ap.AnalysisBuild) -> str:
    """What the query does, in a sentence a credit officer would check."""
    sources = ", ".join(build.datasets)
    where = ", ".join(f"{f} = {v}" for f, v in build.filters)

    if build.shape == ap.AGGREGATE:
        return (
            f"This query reads {sources} at {build.period}"
            + (f", keeps only rows where {where}" if where else "")
            + f", groups them by {build.dimension or 'the whole population'}, "
            f"sums {build.matches[0].concept.label if build.matches else 'the measure'} "
            "within each group, and orders the groups largest first.")
    if build.shape == ap.RANKING:
        measure = (build.matches[0].concept.label if build.matches
                   else "the measure")
        return (
            f"This query reads {sources} at {build.period}"
            + (f", keeps only rows where {where}" if where else "")
            + f", aggregates {measure} to one row per {build.grain}, computes "
            f"each {build.grain}'s share of the total across that population, "
            f"orders largest first and returns the top {build.top_n}.")

    stated = ", ".join(c.describe() for c in build.conditions)
    return (
        f"This query reads {sources} at {build.opening} and again at "
        f"{build.closing}, aggregates every source that carries more than one "
        f"row per {build.grain} up to {build.grain} level before joining so "
        "nothing is double-counted, joins annual sources as-of the reporting "
        "date so no future data is used, matches each "
        f"{build.grain} at the two dates, derives the movement in each measure, "
        f"and keeps the {build.grain}s where {stated}.")


# ---------------------------------------------------------------- the Trace


def analysis_graph(question: str, reading: cap.Reading, build: ap.AnalysisBuild,
                   runtime: Any, narrative: Narrative) -> TraceGraph:
    """The full lineage: question, reading, sources, joins, maths, result.

    Built from the runtime's own recorded graph rather than described
    alongside it — the nodes below the query are evidence of what ran, and
    re-describing them here would let the picture drift from the execution.
    """
    graph = TraceGraph()
    graph.add_node(TraceNode(id="question", type=NodeType.USER_PROMPT,
                             label="Question asked",
                             config={"question": question}))

    intent = graph.add_node(TraceNode(
        id="intent", type=NodeType.CAPABILITY,
        label=f"Read as: {reading.label}",
        config={
            "intent": reading.intent, "intent_label": reading.label,
            "objective": build.summary,
            "concepts": [m.concept.label for m in build.matches],
            "metrics": [f"{m.dataset}.{m.field}" for m in build.matches],
            "entities": [dict(e) for e in reading.entities],
            "dimensions": [build.dimension] if build.dimension else [],
            "period": (f"{build.opening} to {build.closing}"
                       if build.opening else build.period),
            "operation": reading.operation,
            "confidence": round(reading.confidence, 3),
            "read_by": reading.source, "model": reading.model,
            "reasoning": reading.reasoning,
            "rule": ("This node records what CreditProbe understood the "
                     "question to be asking. It contains no figures."),
        }))
    intent.mark_ok()
    graph.connect("question", "intent")

    # Everything the runtime recorded, re-parented under the reading.
    recorded = runtime.graph.to_dict() if runtime.graph else {"nodes": [],
                                                              "edges": []}
    skip = {"question", "intent", "plan"}
    mapping: dict[str, str] = {}
    for raw in recorded.get("nodes") or []:
        original = str(raw.get("id"))
        if original in skip:
            continue
        new_id = f"run__{original}"
        mapping[original] = new_id
        node = TraceNode(
            id=new_id, type=NodeType(raw.get("type", "CALCULATION")),
            label=str(raw.get("label", "")),
            config=dict(raw.get("config") or {}),
            rows_in=raw.get("rows_in"), rows_out=raw.get("rows_out"),
            output_preview=raw.get("output_preview"),
            output_summary=dict(raw.get("output_summary") or {}),
            warnings=list(raw.get("warnings") or []),
            error=raw.get("error"), dataset=raw.get("dataset"),
            fields_used=list(raw.get("fields_used") or []),
        )
        node.duration_ms = raw.get("duration_ms")
        # The recorded status is a serialised enum value; putting the string
        # back on the node would make to_dict() fail three layers away.
        try:
            node.status = NodeStatus(str(raw.get("status") or "ok"))
        except ValueError:
            node.status = NodeStatus.OK
        graph.add_node(node)

    for raw in recorded.get("edges") or []:
        source = mapping.get(str(raw.get("source")))
        target = mapping.get(str(raw.get("target")))
        if source and target:
            graph.connect(source, target)

    # Roots of the recorded subgraph hang off the reading.
    targets = {e.target for e in graph.edges}
    for new_id in mapping.values():
        if new_id not in targets:
            graph.connect("intent", new_id)

    # The mathematical query: plan, SQL, formulas and parameters as one thing a
    # reader can open. Mandatory for every dynamic analysis.
    query = runtime.query.to_dict() if runtime.query else {}
    maths = graph.add_node(TraceNode(
        id="mathematical_query", type=NodeType.MATHEMATICAL_QUERY,
        label="Mathematical query",
        config={
            "sql": query.get("sql", ""),
            "parameters": query.get("parameters", []),
            "operations": [
                {"id": o.get("id"), "op": o.get("op"),
                 "label": o.get("label", ""), "params": o.get("params", {})}
                for o in build.plan.get("operations") or []
            ],
            "formulas": formulas(build),
            "plain_english": plain_english(build),
            "kernels": [k for k in getattr(runtime.query, "kernel_steps", [])
                        or []] if runtime.query else [],
            "shape": build.shape,
            "datasets": build.datasets,
            "grain": build.grain,
        }))
    maths.mark_ok(rows_out=runtime.row_count)
    sql_node = mapping.get("sql")
    graph.connect(sql_node or "intent", "mathematical_query")

    interpretation = graph.add_node(TraceNode(
        id="interpretation", type=NodeType.LLM_EXPLANATION,
        label="CreditProbe interpretation",
        config={
            "stage": "result_interpretation",
            "stage_label": "Reading of the result",
            "direct_answer": narrative.direct_answer,
            "interpretation": narrative.interpretation,
            "written_by": reading.source,
            "model": reading.model,
            "grounded_in": [c["name"] for c in runtime.columns],
            "rule": ("Written after the engine ran, from the returned result. "
                     "Every figure quoted appears in the result above."),
        }))
    interpretation.mark_ok()
    result_node = mapping.get("result")
    graph.connect(result_node or "mathematical_query", "interpretation")
    graph.compute_hashes()
    return graph


__all__ = [
    "analysis_graph",
    "notable",
    "formulas",
    "from_analysis",
    "from_handler",
    "grounded_values",
    "plain_english",
    "ungrounded",
]
