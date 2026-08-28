"""
The proactive new-period review. §35, §36, §56.

§35's eleven steps, in order, with the funnel §36 requires:

     1  Data Steward confirms the period is published and readable.
     2  Deterministic pre-screen over the whole book — no model, no LLM.
     3  Portfolio indicators that moved materially become Portfolio cases.
     4  Segments that moved more than the book become Segment cases.
     5  Borrowers driving those segments become Borrower cases.
     6  Datasets that are missing at this period become Data cases.
     7  Specialists enrich the material findings, through the governed runtime.
     8  Validation & Assurance checks what they produced.
     9  Severity is computed by the published formula — never by a model.
    10  Cases are created or refreshed, never duplicated.
    11  The people who should know are notified.

The order is the cost control. Steps 2–6 are DuckDB aggregates over Parquet and
cost nothing per borrower; only what survives them reaches a specialist, and
only validated findings reach a model. A review that asked a model about each
borrower would cost hundreds of calls to reach the same four names the screen
found in a second.

What this module refuses to do
------------------------------
It does not decide severity (that is `severity.py`'s arithmetic), does not close
or dismiss a case (§38: a person does), and does not send anything (§66: a
workflow item is created as a DRAFT and sending it is an approval gate). Its
whole job is to notice, evidence and hand over.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.agentic import (
    budgets as bg,
)
from backend.agentic import (
    cases,
    dag,
    events,
    officers,
    orchestrator,
    principals,
    registry,
    runs,
    screening,
    stages,
)
from backend.agentic import (
    severity as sv,
)

logger = logging.getLogger(__name__)

#: Which specialists enrich a material finding, by what moved. Read from the
#: concept the indicator measures, so a new governed concept widens the review
#: without a change here.
_ENRICH: dict[str, str] = {
    "ecl": "ecl",
    "ecl_coverage": "ecl_coverage",
    "stage2_share": "stage",
    "stage3_share": "stage",
    "npl_ratio": "dpd",
    "downgrade_rate": "rating",
    "watchlist_share": "rating",
    "appetite_breaches": "exposure",
    "ead": "ead",
}


@dataclass
class Review:
    """What one proactive review produced."""

    period: str
    prior_period: str = ""
    screen: screening.Screen | None = None
    outcome: orchestrator.Outcome | None = None
    cases_created: list[int] = field(default_factory=list)
    cases_refreshed: list[int] = field(default_factory=list)
    notified: list[int] = field(default_factory=list)
    stopped: str = ""
    note: str = ""

    @property
    def case_count(self) -> int:
        return len(self.cases_created) + len(self.cases_refreshed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "prior_period": self.prior_period,
            "screen": self.screen.to_dict() if self.screen else {},
            "outcome": self.outcome.to_dict() if self.outcome else {},
            "cases_created": list(self.cases_created),
            "cases_refreshed": list(self.cases_refreshed),
            "case_count": self.case_count,
            "notified": list(self.notified),
            "stopped": self.stopped,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# The review
# ---------------------------------------------------------------------------


def run(session: Any, *, period: str = "", prior_period: str = "",
        trigger: str = runs.EVENT, event_id: int | None = None,
        user_id: int | None = None, answer_one: Callable[..., Any] | None = None,
        should_stop: Callable[[], bool] | None = None,
        notify: bool = True) -> tuple[Any, Review]:
    """Review a newly published period, end to end.

    Returns `(agent_run_row, review)`. The run row exists from the first line,
    so a review that dies half-way is still visible with the stage it reached —
    a proactive process that leaves no trace when it fails is one nobody can
    trust to have run at all.
    """
    from backend.orchestration.executor import run_investigation

    ask = answer_one or run_investigation
    stop = should_stop or (lambda: False)
    actor = principals.for_service()

    at = period or events.latest_period()
    if not at:
        raise LookupError(
            "No portfolio period is published, so there is nothing to review.")

    # The officer is chosen before anything runs, from the structure of the
    # work: a whole-book review across every governed domain is coordinated
    # work by definition (§4 level 4), and `proactive` is scored as risk.
    selection = officers.select(
        f"Review {at} and report what requires attention.",
        agents=len(registry.specialists()), tasks=0, proactive=True)

    budget = bg.for_trigger(trigger)
    run_row = runs.start(
        session, trigger=trigger, question=f"Proactive review of {at}",
        period=at, prior_period=prior_period,
        user_id=user_id, role=actor.role,
        service_identity=actor.service_identity, event_id=event_id,
        trigger_object_type="period", trigger_object_id=at,
        selection=selection, budget=budget)
    session.flush()

    review = Review(period=at, prior_period=prior_period)

    try:
        _steward(session, run_row, review, at)
        if stop():
            return _stopped(session, run_row, review)

        _screen(session, run_row, review, at, prior_period, budget, actor)
        if stop():
            return _stopped(session, run_row, review)

        _enrich(session, run_row, review, selection, budget, actor, ask, stop)
        if stop():
            return _stopped(session, run_row, review)

        _cases(session, run_row, review)
        if notify:
            _notify(session, run_row, review)

        runs.advance(session, run_row, stages.INTERPRETING)
        outcome = review.outcome
        synthesis = _synthesis(review)
        runs.finish(
            session, run_row, plan=outcome.plan if outcome else None,
            findings=outcome.findings if outcome else [],
            conflicts=outcome.conflicts if outcome else [],
            validation=_validation(outcome),
            assurance=(orchestrator.assess(
                outcome, periods_expected=2 if review.prior_period else 1,
                periods_found=2 if review.prior_period else 1)
                if outcome else None),
            synthesis=synthesis, budget=budget,
            analysis_run_id=outcome.analysis_run_id if outcome else None,
            cases=review.cases_created)
    except bg.Exhausted as exhausted:
        review.stopped = "budget"
        review.note = exhausted.sentence()
        runs.fail(session, run_row, reason=exhausted.sentence(),
                  kind="budget_exhausted", budget=budget)
    except Exception as exc:  # noqa: BLE001 - recorded against the run
        logger.exception("proactive review of %s failed", at)
        review.stopped = "failed"
        review.note = f"{type(exc).__name__}: {exc}"
        runs.fail(session, run_row, reason=review.note, kind=_kind(exc),
                  budget=budget)

    return run_row, review


# -- step 1: readiness ------------------------------------------------------


def _steward(session: Any, run_row: Any, review: Review, period: str) -> None:
    """§35.1 — the Data Steward confirms the period is there.

    Checked before anything else, because a review of a period that is not
    published produces an empty answer in a confident tone, which is worse than
    no review.
    """
    runs.advance(session, run_row, stages.UNDERSTANDING,
                 detail=f"Confirming {period} is published")
    from backend.data_access.duckdb_source import DuckDBSource

    periods = list(DuckDBSource().periods(screening.FACILITIES))
    if period not in periods:
        raise LookupError(
            f"{period} is not published in {screening.FACILITIES}. The most "
            f"recent published period is "
            f"{periods[-1] if periods else 'none'}.")


# -- steps 2-6: the deterministic screen ------------------------------------


def _screen(session: Any, run_row: Any, review: Review, period: str,
            prior: str, budget: bg.Budget, actor: Any) -> None:
    """§35.2–35.6 and §36 — the whole book, measured, with no model."""
    runs.advance(session, run_row, stages.SCOPING,
                 detail="Screening the published book")
    budget.spend(bg.SCANS, amount=4)

    found = screening.run(period, prior_period=prior, user_id=actor.user_id)
    review.screen = found
    review.prior_period = found.prior_period

    funnel = found.funnel()
    budget.spend(bg.ROWS, amount=min(int(found.rows_screened),
                                     budget.remaining(bg.ROWS)))
    runs.advance(session, run_row, stages.SELECTING_DATA,
                 detail=(f"{funnel['segments_material']} material segment(s), "
                         f"{funnel['borrowers_escalated']} borrower(s)"))
    run_row.usage = {"funnel": funnel, "line": budget.usage_line()}
    session.flush()


# -- step 7-8: specialists and assurance ------------------------------------


def _enrich(session: Any, run_row: Any, review: Review, selection: Any,
            budget: bg.Budget, actor: Any, ask: Callable[..., Any],
            stop: Callable[[], bool]) -> None:
    """§35.5, §35.6 — specialists enrich the material findings.

    Scoped to what the screen found. A specialist asked about the whole book
    would undo the funnel; asked about Contracting, it produces a governed
    analysis with a Trace that a Risk Case can point at.
    """
    found = review.screen
    if found is None:
        return

    concepts = _concepts_for(found)
    segments = found.material_segments
    scope = ({"segment": segments[0].name} if segments else
             {"entity": "the portfolio"})

    plan = orchestrator.plan_for(
        f"Review {review.period}", concepts=concepts, scope=scope,
        period=review.period, prior_period=review.prior_period)

    selection = orchestrator.escalation_for(selection, plan)
    runs.record_plan(session, run_row, plan,
                     orchestrator=registry.CHIEF_ORCHESTRATOR.agent_id,
                     selection=selection)
    session.flush()

    def on_task(task: dag.Task) -> None:
        runs.update_task(session, run_row.id, task)

    def on_stage(stage: str, detail: str) -> None:
        runs.advance(session, run_row, stage, detail=detail,
                     agents=len(plan.agents))

    review.outcome = orchestrator.execute(
        plan, answer_one=ask, budget=budget, actor=actor,
        should_stop=stop, on_task=on_task, on_stage=on_stage)


def _concepts_for(found: screening.Screen) -> list[str]:
    """Which governed concepts the screen says are worth enriching.

    Read off what actually moved rather than a fixed list, so a period where
    only delinquency moved does not pay for a ratings specialist.
    """
    concepts: list[str] = []
    for indicator in found.material_portfolio:
        concept = _ENRICH.get(indicator.key)
        if concept and concept not in concepts:
            concepts.append(concept)
    for segment in found.material_segments:
        worst = segment.worst
        concept = _ENRICH.get(worst.key) if worst else None
        if concept and concept not in concepts:
            concepts.append(concept)
    if found.borrowers and "ecl" not in concepts:
        concepts.append("ecl")
    return concepts or ["ead"]


# -- steps 9-10: the cases --------------------------------------------------


def _cases(session: Any, run_row: Any, review: Review) -> None:
    """§35.8, §37, §39 — evidence becomes cases, severity becomes arithmetic."""
    found = review.screen
    if found is None:
        return

    analyses = [f.get("analysis_run_id") for f in
                (review.outcome.findings if review.outcome else [])
                if f.get("analysis_run_id")]
    book = next((i.now for i in found.portfolio if i.key == "ead"), None)
    validated = _validated(review.outcome)

    for indicator in found.material_portfolio:
        _portfolio_case(session, run_row, review, indicator, found, book,
                        analyses, validated)
    for segment in found.material_segments:
        _segment_case(session, run_row, review, segment, found, book,
                      analyses, validated)
    for borrower in found.borrowers:
        _borrower_case(session, run_row, review, borrower, found, book,
                       analyses, validated)
    for issue in found.data_issues:
        _data_case(session, run_row, review, issue, found)


def _remember(review: Review, case: Any, before: str) -> None:
    """Record whether a case was made now or refreshed from an earlier run.

    The distinction is what makes a replayed review reportable: "3 new, 8
    refreshed" is a useful sentence and "11 cases" is not.
    """
    if before == "new":
        review.cases_created.append(case.id)
    else:
        review.cases_refreshed.append(case.id)


def _existing(session: Any, key: str) -> str:
    from sqlalchemy import select

    from backend.models.platform import RiskCase

    found = session.execute(
        select(RiskCase.id).where(RiskCase.dedupe_key == key)).scalar()
    return "existing" if found else "new"


def _portfolio_case(session: Any, run_row: Any, review: Review,
                    indicator: screening.Indicator, found: screening.Screen,
                    book: float | None, analyses: list[int],
                    validated: bool) -> None:
    """§41 — a book-level movement that requires attention."""
    adverse = [i for i in found.portfolio if i.adverse]
    score = sv.compute(
        exposure=book, portfolio_exposure=book,
        movement=indicator.relative, adverse_signals=len(adverse),
        total_signals=len(found.portfolio), periods_moving=1,
        appetite_breached=_appetite_breached(found),
        invariants_passed=validated,
        invariants_checked=len(analyses),
        evidence_present=len(analyses), evidence_expected=max(1, len(analyses)))

    draft = cases.Draft(
        level=cases.PORTFOLIO,
        title=f"{indicator.label} moved materially at portfolio level",
        period=review.period, prior_period=review.prior_period,
        entity="Portfolio", entity_id="portfolio", entity_kind="portfolio",
        about=indicator.key,
        conclusion=indicator.sentence(),
        why=(f"The movement is {abs(indicator.relative or 0):.1%} against the "
             f"prior period, above the {screening.PORTFOLIO_MOVE:.0%} "
             f"threshold at which CreditProbe raises a portfolio case."),
        exposure=book, metrics=[indicator.to_dict()],
        signals=[i.sentence() for i in adverse],
        evidence={"screen": found.funnel(),
                  "thresholds": screening.thresholds(),
                  "indicator": indicator.to_dict()},
        analyses=list(analyses), score=score,
        evidence_coverage=sv.coverage_of(len(analyses), max(1, len(analyses))),
        agent_run_id=run_row.id, source_event_id=run_row.event_id,
        trace_id=run_row.trace_id)
    before = _existing(session, draft.key)
    case = cases.upsert(session, draft,
                        actor_agent=registry.PORTFOLIO_RISK.agent_id)
    _remember(review, case, before)


def _segment_case(session: Any, run_row: Any, review: Review,
                  segment: screening.Segment, found: screening.Screen,
                  book: float | None, analyses: list[int],
                  validated: bool) -> None:
    """§42 — a sector moving more than the book."""
    worst = segment.worst
    if worst is None:
        return
    drivers = [b for b in found.borrowers if b.sector == segment.name]
    concentration = (sum(b.contribution or 0 for b in drivers[:3])
                     if drivers else None)

    score = sv.compute(
        exposure=segment.exposure, portfolio_exposure=book,
        movement=worst.relative, adverse_signals=len(segment.adverse),
        total_signals=len(segment.indicators), periods_moving=1,
        concentration_share=concentration,
        invariants_passed=validated, invariants_checked=len(analyses),
        evidence_present=len(analyses) + len(drivers),
        evidence_expected=max(1, len(analyses) + len(drivers)))

    draft = cases.Draft(
        level=cases.SEGMENT,
        title=f"{segment.name}: {worst.label.lower()} moved materially",
        period=review.period, prior_period=review.prior_period,
        entity=segment.name, entity_id=segment.name, entity_kind="sector",
        about=worst.key,
        conclusion=f"{segment.name} — {worst.sentence()}",
        why=(f"{segment.name} is {(segment.share_of_book or 0):.1%} of the "
             f"book and moved {abs(worst.relative or 0):.1%}, above the "
             f"{screening.SEGMENT_MOVE:.0%} threshold for a segment case."
             + (f" {len(drivers)} borrower(s) account for "
                f"{(concentration or 0):.0%} of the movement."
                if drivers else "")),
        exposure=segment.exposure,
        metrics=[i.to_dict() for i in segment.indicators],
        signals=[i.sentence() for i in segment.adverse],
        evidence={"segment": segment.to_dict(),
                  "drivers": [b.to_dict() for b in drivers[:6]],
                  "thresholds": screening.thresholds()},
        analyses=list(analyses), score=score,
        evidence_coverage=sv.coverage_of(
            len(analyses) + len(drivers), max(1, len(analyses) + len(drivers))),
        agent_run_id=run_row.id, source_event_id=run_row.event_id,
        trace_id=run_row.trace_id)
    before = _existing(session, draft.key)
    case = cases.upsert(session, draft,
                        actor_agent=registry.PORTFOLIO_RISK.agent_id)
    _remember(review, case, before)


def _borrower_case(session: Any, run_row: Any, review: Review,
                   borrower: screening.Borrower, found: screening.Screen,
                   book: float | None, analyses: list[int],
                   validated: bool) -> None:
    """§43 — a customer driving a segment's movement."""
    # The movement is the ECL change against the PRIOR ECL, not against
    # exposure. See `screening.Borrower.ecl_relative`.
    ecl_move = borrower.ecl_relative

    score = sv.compute(
        exposure=borrower.exposure, portfolio_exposure=book,
        movement=ecl_move, adverse_signals=len(borrower.signals),
        total_signals=max(3, len(borrower.signals)),
        periods_moving=1,
        concentration_share=borrower.contribution,
        invariants_passed=validated, invariants_checked=len(analyses),
        evidence_present=len(borrower.signals) + len(analyses),
        evidence_expected=max(2, len(borrower.signals) + len(analyses)))

    conclusion = (
        f"{borrower.name}: expected credit loss rose "
        f"{borrower.ecl_change:,.2f} USD mn"
        + (f" ({borrower.ecl_relative:+.0%})" if borrower.ecl_relative
           else "")
        + f" on {borrower.exposure:,.0f} USD mn of exposure."
        if borrower.ecl_change and borrower.exposure else
        f"{borrower.name} contributed to the {borrower.sector} movement.")

    draft = cases.Draft(
        level=cases.BORROWER,
        title=f"{borrower.name} — deterioration in {borrower.sector}",
        period=review.period, prior_period=review.prior_period,
        entity=borrower.name, entity_id=borrower.customer_id,
        entity_kind="customer", about="ecl",
        conclusion=conclusion,
        why=(f"It accounts for {(borrower.contribution or 0):.0%} of the "
             f"expected-credit-loss increase in {borrower.sector}"
             + (f", and {'; '.join(borrower.signals).lower()}."
                if borrower.signals else ".")),
        exposure=borrower.exposure,
        metrics=[{"key": "ecl_change", "label": "ECL change",
                  "unit": "USD mn", "now": borrower.ecl_change},
                 {"key": "ead", "label": "Exposure at default",
                  "unit": "USD mn", "now": borrower.exposure}],
        signals=list(borrower.signals),
        evidence={"borrower": borrower.to_dict(),
                  "segment": borrower.sector,
                  "thresholds": screening.thresholds()},
        analyses=list(analyses), score=score,
        evidence_coverage=sv.coverage_of(
            len(borrower.signals) + len(analyses),
            max(2, len(borrower.signals) + len(analyses))),
        agent_run_id=run_row.id, source_event_id=run_row.event_id,
        trace_id=run_row.trace_id)
    before = _existing(session, draft.key)
    case = cases.upsert(session, draft,
                        actor_agent=registry.EARLY_WARNING.agent_id)
    _remember(review, case, before)


def _data_case(session: Any, run_row: Any, review: Review,
               issue: dict[str, Any], found: screening.Screen) -> None:
    """§44 — a dataset that is not where the review needs it."""
    score = sv.compute(
        exposure=None, movement=None, adverse_signals=1, total_signals=1,
        data_confidence=0.0, invariants_passed=True, invariants_checked=0,
        evidence_present=1, evidence_expected=1)

    draft = cases.Draft(
        level=cases.DATA_QUALITY,
        title=f"{issue.get('dataset')} is not available for {review.period}",
        period=review.period, prior_period=review.prior_period,
        entity=str(issue.get("dataset") or ""),
        entity_id=str(issue.get("dataset") or ""), entity_kind="dataset",
        about=str(issue.get("issue") or "data"),
        conclusion=str(issue.get("detail") or ""),
        why=("Analyses that depend on this dataset cannot be run for this "
             "period, so any review that used them would be incomplete "
             "without saying so."),
        signals=[str(issue.get("issue") or "")],
        evidence={"issue": dict(issue), "screen": found.funnel()},
        score=score, evidence_coverage=1.0,
        agent_run_id=run_row.id, source_event_id=run_row.event_id,
        trace_id=run_row.trace_id)
    before = _existing(session, draft.key)
    case = cases.upsert(session, draft,
                        actor_agent=registry.DATA_STEWARD.agent_id)
    _remember(review, case, before)


def _appetite_breached(found: screening.Screen) -> bool:
    indicator = next((i for i in found.portfolio
                      if i.key == "appetite_breaches"), None)
    return bool(indicator and (indicator.now or 0) > 0)


def _validated(outcome: orchestrator.Outcome | None) -> bool:
    if outcome is None:
        return False
    validation = next((t for t in outcome.plan.tasks
                       if t.agent_id == registry.VALIDATION.agent_id), None)
    return bool(validation and validation.validation_state == "passed")


def _validation(outcome: orchestrator.Outcome | None) -> dict[str, Any]:
    if outcome is None:
        return {}
    validation = next((t for t in outcome.plan.tasks
                       if t.agent_id == registry.VALIDATION.agent_id), None)
    return dict(validation.validation) if validation else {}


# -- step 11: telling people ------------------------------------------------


def _notify(session: Any, run_row: Any, review: Review) -> None:
    """§35.11, §65 — tell the people who should know.

    Only about cases created NOW. A refreshed case has already been notified,
    and notifying it again every quarter is how a notification centre becomes
    something people stop opening.
    """
    if not review.cases_created:
        return
    from backend.agentic import notifications

    review.notified = notifications.review_complete(
        session, run_id=run_row.id, period=review.period,
        created=review.cases_created)


def _synthesis(review: Review) -> str:
    """What the review concluded, grounded in what it measured. §45's sentence
    plus what the specialists found."""
    lines: list[str] = []
    found = review.screen
    if found is not None:
        counted = {
            "portfolio": len([i for i in found.material_portfolio]),
            "segment": len(found.material_segments),
            "borrower": len(found.borrowers),
            "data": len(found.data_issues),
        }
        parts = [f"{n} {label}" for label, n in (
            ("portfolio issue(s)", counted["portfolio"]),
            ("segment issue(s)", counted["segment"]),
            ("borrower case(s)", counted["borrower"]),
            ("data issue(s)", counted["data"])) if n]
        lines.append(
            f"CreditProbe reviewed {review.period} and identified "
            f"{', '.join(parts)}." if parts else
            f"CreditProbe reviewed {review.period} and found nothing that "
            f"requires attention.")
        lines.append(found.funnel()["reduction"] + ", with no model calls.")

    if review.outcome is not None:
        lines.append(orchestrator.synthesise(
            review.outcome,
            scope=review.outcome.plan.scope if review.outcome.plan else {}))
    return "\n".join(line for line in lines if line)


def _stopped(session: Any, run_row: Any, review: Review) -> tuple[Any, Review]:
    review.stopped = "cancelled"
    review.note = "The review was stopped before it finished."
    runs.cancelled(session, run_row,
                   plan=review.outcome.plan if review.outcome else None)
    return run_row, review


def _kind(exc: BaseException) -> str:
    if isinstance(exc, LookupError):
        return "not_found"
    if isinstance(exc, PermissionError):
        return "permission"
    return type(exc).__name__[:48]


__all__ = ["Review", "run"]
