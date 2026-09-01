"""
From a governed early-warning standing to a Risk Case. §26.

Two modules already exist and neither of them should learn the other's job.
``signals`` decides what fired and what it means; ``agentic.cases`` owns the
lifecycle a finding then has - an owner, a due date, a status somebody moves.
This is the seam between them, and it is deliberately thin.

Three rules hold here.

**A case is raised from evidence, never from a score.** ``Standing`` carries
no score key and this module does not invent one. What it does compute is a
*severity band*, through the platform's existing versioned formula, from
counts a reader can check: how many independent families fired, how many were
already firing, how much exposure sits behind them. The formula is
``agentic.severity``, the same one every other case in the product is scored
by, so an early-warning case and an agentic one are comparable.

**Not every standing deserves a case.** A single WATCH condition on one
borrower is monitoring, not a finding; raising a case for it produces a queue
nobody can work and teaches its readers to ignore the queue. The materiality
rule is written down in ``worth_a_case`` and is a rule, not a threshold on a
number.

**A replay updates, it never duplicates.** The dedupe key is the borrower and
the period, so re-running the review over the same quarter refreshes the
evidence on the case that exists and leaves every human decision - the owner,
the status, the comments - exactly where the human left it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from backend.agentic import cases as rc
from backend.agentic import severity as sv
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

#: Bumped when the rule that decides whether a standing becomes a case
#: changes, so a case can be read against the rule that raised it.
REVIEW_VERSION = "1.0.0"

#: What the review is about, in the dedupe key. Keeps an early-warning case
#: distinct from an agentic case raised on the same borrower and period.
ABOUT = "early-warning"

#: The name that appears as the actor on every event this review records.
REVIEWER = "early-warning-review"


# --------------------------------------------------------------- materiality


@dataclass(frozen=True)
class Reason:
    """Why a standing did or did not become a case."""

    raise_it: bool
    rule: str
    sentence: str


def worth_a_case(standing: sg.Standing) -> Reason:
    """Whether this standing is a finding or is monitoring. §26.

    Four ways in, in the order a credit officer would apply them:

    1. a SEVERE condition - one is enough, because the taxonomy reserves
       SEVERE for conditions that are already a credit event;
    2. breadth - two or more INDEPENDENT families saying the same thing,
       which is the whole argument for not using a score;
    3. persistence - a condition that was firing last period and still is,
       because a signal nobody acted on is the one that becomes a loss;
    4. a booked accounting position - stage 2 or worse is a fact about the
       book, not a prediction, and it belongs in front of somebody.

    A single new WATCH condition satisfies none of them, and that is the
    point: it stays visible on the Early Warning screen and does not open a
    case.
    """
    if not standing.fired:
        return Reason(False, "no_signal",
                      "No governed early-warning condition fires for this "
                      "borrower at this reporting date.")
    if standing.severity == tx.SEVERE:
        severe = [o.label for o in standing.fired if o.severity == tx.SEVERE]
        return Reason(True, "severe",
                      f"A severe condition is present: {_and_list(severe)}.")
    if standing.breadth >= 2:
        families = [tx.FAMILIES.get(f, f).lower() for f in standing.agreement]
        return Reason(True, "breadth",
                      f"{standing.breadth} independent families agree "
                      f"({_and_list(families)}).")
    if standing.persistence:
        return Reason(True, "persistence",
                      f"{standing.persistence} condition"
                      f"{'' if standing.persistence == 1 else 's'} already "
                      "firing at the previous reporting date.")
    if standing.booked_stage:
        return Reason(True, "booked_stage",
                      "The booked accounting position is stage 2 or worse.")
    only = standing.fired[0].label
    return Reason(False, "single_watch",
                  f"One condition fires - {only} - in a single family, for "
                  "the first time. That is monitoring, not a finding.")


def _and_list(items: list[str]) -> str:
    kept = [i for i in items if i]
    if not kept:
        return ""
    if len(kept) == 1:
        return kept[0]
    return ", ".join(kept[:-1]) + " and " + kept[-1]


# ------------------------------------------------------------------ scoring


def score_for(standing: sg.Standing, *, exposure: float | None = None,
              portfolio_exposure: float | None = None,
              concentration_share: float | None = None) -> sv.Score:
    """The case's severity, through the platform's one versioned formula.

    Every argument is a count or a measured amount. ``movement`` is the
    largest adverse proportional move among the conditions that fired, which
    is an observation about the borrower rather than an opinion about it;
    ``periods_moving`` is persistence; ``adverse_signals`` and
    ``total_signals`` are the fired count against everything the taxonomy
    could actually test here.

    Evidence coverage is deliberately *tested* over *catalogued*: a borrower
    whose statements are missing has fewer conditions testable, and a case
    that hides that is a case somebody over-trusts.
    """
    tested = len(standing.fired) + len(standing.cured)
    testable = tested + len([o for o in standing.untested])
    moves = [abs(o.movement) for o in standing.fired
             if o.movement is not None]
    return sv.compute(
        exposure=exposure,
        portfolio_exposure=portfolio_exposure,
        movement=max(moves) if moves else None,
        adverse_signals=len(standing.fired),
        total_signals=max(tested, len(standing.fired)),
        periods_moving=standing.persistence,
        concentration_share=concentration_share,
        appetite_breached=any(o.family == tx.COVENANT for o in standing.fired),
        # Deliberately 1.0 and not degraded by `untested`. Thin evidence is
        # already carried by `evidence_present`/`evidence_expected` below, and
        # feeding the same fact into two components counts it twice - which
        # would make a borrower with missing columns drop two bands for one
        # reason. The data behind what DID fire is complete; what is missing is
        # coverage, and coverage is where it is reported.
        data_confidence=1.0,
        invariants_passed=True,
        invariants_checked=len(standing.fired),
        evidence_present=tested,
        evidence_expected=max(testable, 1),
    )


# ------------------------------------------------------------------- drafting


def conclusion_of(standing: sg.Standing, reason: Reason) -> str:
    """The one sentence a reader gets first.

    Composed from the standing rather than written by a model, for the same
    reason the standing has no score: the sentence and the evidence beneath
    it cannot then disagree.
    """
    return f"{standing.sentence()} {reason.sentence}"


def why_of(standing: sg.Standing) -> str:
    """The paragraph under the conclusion: each condition, in words."""
    lines = [f"- {o.label}: {o.means}" for o in standing.fired if o.means]
    if standing.conflict:
        families = _and_list([tx.FAMILIES.get(f, f).lower()
                              for f in standing.conflict])
        lines.append(f"- Evidence points the other way in {families}.")
    if standing.untested:
        lines.append(
            f"- {len(standing.untested)} governed condition"
            f"{'' if len(standing.untested) == 1 else 's'} could not be "
            "tested for this borrower. They are listed on the case, with "
            "the reason each one could not be tested.")
    if standing.booked_stage:
        lines.append(
            "- The stage figures above are the BOOKED accounting position "
            "at this reporting date, not a prediction that the borrower "
            "will migrate.")
    return "\n".join(lines)


def metrics_of(standing: sg.Standing) -> list[dict[str, Any]]:
    """Every fired condition as a referenced figure. §26.

    A number on a case must say where it came from, so each carries the
    dataset, the field, the threshold and the version of the threshold that
    was in force when it fired.
    """
    return [
        {
            "name": o.label,
            "signal": o.signal,
            "family": o.family,
            "value": o.value,
            "previous": o.previous,
            "movement": o.movement,
            "threshold": o.threshold,
            "threshold_version": o.threshold_version,
            "threshold_owner": o.threshold_owner,
            "dataset": o.dataset,
            "field": o.field_name,
            "test": o.test,
            "period": o.period,
            "previous_period": o.previous_period,
            "lifecycle": o.lifecycle,
            "severity": o.severity,
            "booked_accounting": o.booked_accounting,
        }
        for o in standing.fired
    ]


def draft_for(standing: sg.Standing, *, name: str = "", sector: str = "",
              exposure: float | None = None,
              portfolio_exposure: float | None = None,
              concentration_share: float | None = None,
              reason: Reason | None = None) -> rc.Draft:
    """Turn one standing into the case a review would write."""
    decided = reason or worth_a_case(standing)
    score = score_for(standing, exposure=exposure,
                      portfolio_exposure=portfolio_exposure,
                      concentration_share=concentration_share)
    tested = len(standing.fired) + len(standing.cured)
    testable = tested + len(standing.untested)
    return rc.Draft(
        level=rc.BORROWER,
        title=_title(standing, name),
        period=standing.period,
        prior_period=(standing.fired[0].previous_period
                      if standing.fired else ""),
        entity=name or standing.borrower_id,
        entity_id=standing.borrower_id,
        entity_kind="borrower",
        about=ABOUT,
        conclusion=conclusion_of(standing, decided),
        why=why_of(standing),
        exposure=exposure,
        metrics=metrics_of(standing),
        signals=[o.signal for o in standing.fired],
        evidence={
            "review_version": REVIEW_VERSION,
            "taxonomy_version": tx.TAXONOMY_VERSION,
            "signals_version": sg.SIGNALS_VERSION,
            "rule": decided.rule,
            "rule_sentence": decided.sentence,
            "sector": sector,
            "standing": standing.to_dict(),
        },
        score=score,
        evidence_coverage=sv.coverage_of(tested, max(testable, 1)),
    )


def _title(standing: sg.Standing, name: str) -> str:
    who = name or standing.borrower_id or "This borrower"
    if not standing.fired:
        return f"{who}: no early-warning condition"
    families = standing.breadth
    return (f"{who}: {len(standing.fired)} early-warning condition"
            f"{'' if len(standing.fired) == 1 else 's'} across "
            f"{families} famil{'y' if families == 1 else 'ies'}")


__all__ = ["ABOUT", "REVIEWER", "REVIEW_VERSION", "Reason", "conclusion_of",
           "draft_for", "metrics_of", "score_for", "why_of", "worth_a_case"]


# ============================================================ the review, §27
#
# What a credit officer would actually do at a reporting date: look at every
# borrower, decide which ones are findings, write those up, and note which of
# last quarter's findings have gone away.
#
# Three properties this review has, and each of them is a decision:
#
# **It evaluates the whole book and opens a bounded number of cases.** Those
# are different limits and conflating them is the classic reporting lie - a
# "top twenty" assembled from the first twenty rows loaded. Every borrower is
# stood up; the ranking is total and deterministic; the cases opened are the
# top of that ranking, and how many qualified but were not opened is reported
# rather than hidden.
#
# **It never closes anything.** A borrower whose conditions have all cured
# moves to MONITORING with an event saying so. RESOLVED and DISMISSED are
# refused to an agent by `agentic.cases.transition`, and this review does not
# try to route around that.
#
# **It is replayable.** Running it twice over the same period refreshes the
# same cases and produces the same counts.

from dataclasses import field as _field  # noqa: E402

#: How many cases one review opens or refreshes, by default. A review that
#: opens two thousand cases has not triaged anything; it has moved the triage
#: problem onto the person reading the queue.
DEFAULT_CASE_BUDGET = 50


@dataclass
class Outcome:
    """What one review run did, in numbers a reader can check."""

    period: str = ""
    previous_period: str = ""
    evaluated: int = 0
    with_signals: int = 0
    qualified: int = 0
    opened: int = 0
    refreshed: int = 0
    moved_to_monitoring: int = 0
    not_opened: int = 0
    budget: int = DEFAULT_CASE_BUDGET
    rules: dict[str, int] = _field(default_factory=dict)
    bands: dict[str, int] = _field(default_factory=dict)
    case_ids: list[int] = _field(default_factory=list)

    def sentence(self) -> str:
        if not self.evaluated:
            return "There was nothing to review at this reporting date."
        parts = [f"{self.evaluated} borrowers reviewed at {self.period}",
                 f"{self.with_signals} carrying at least one governed "
                 "condition",
                 f"{self.qualified} meeting the case rule"]
        if self.opened or self.refreshed:
            parts.append(f"{self.opened} case"
                         f"{'' if self.opened == 1 else 's'} opened and "
                         f"{self.refreshed} refreshed")
        if self.not_opened:
            parts.append(
                f"{self.not_opened} qualified but sat below the {self.budget}-"
                "case limit for one run and were left on the Early Warning "
                "screen")
        if self.moved_to_monitoring:
            parts.append(f"{self.moved_to_monitoring} existing case"
                         f"{'' if self.moved_to_monitoring == 1 else 's'} "
                         "moved to monitoring because the conditions cured")
        return "; ".join(parts) + "."

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_version": REVIEW_VERSION,
            "taxonomy_version": tx.TAXONOMY_VERSION,
            "signals_version": sg.SIGNALS_VERSION,
            "period": self.period, "previous_period": self.previous_period,
            "evaluated": self.evaluated, "with_signals": self.with_signals,
            "qualified": self.qualified, "opened": self.opened,
            "refreshed": self.refreshed,
            "moved_to_monitoring": self.moved_to_monitoring,
            "not_opened": self.not_opened, "budget": self.budget,
            "rules": dict(self.rules), "bands": dict(self.bands),
            "case_ids": list(self.case_ids),
            "sentence": self.sentence(),
        }


def standings_for(period: str = "") -> dict[str, Any]:
    """Every borrower's standing at a period, with the row behind it.

    Separated from ``run`` so the ranking can be tested without a database,
    and so the screen and the review cannot disagree about who is worst.

    Memoised for the same reason `signals.portfolio` is: standing up three
    thousand borrowers takes a little over two seconds, and the preview route
    is a screen. `signals.reset()` clears this too, so the two caches cannot
    disagree about which book they are holding.
    """
    return _standings(period)


@lru_cache(maxsize=8)
def _standings(period: str = "") -> dict[str, Any]:
    import pandas as pd

    from backend.corporate import service as corporate

    snapshot: pd.DataFrame = corporate._load(corporate.SNAPSHOT)
    periods = sorted((str(p) for p in snapshot["period"].unique()),
                     key=sg._period_key)
    if not periods:
        return {"period": "", "previous_period": "", "standings": [],
                "rows": {}, "portfolio_exposure": 0.0}
    chosen = period or periods[-1]
    if chosen not in periods:
        return {"period": chosen, "previous_period": "", "standings": [],
                "rows": {}, "portfolio_exposure": 0.0}
    index = periods.index(chosen)
    prior = periods[index - 1] if index else ""

    current = snapshot[snapshot["period"] == chosen]
    previous = (snapshot[snapshot["period"] == prior].set_index("borrower_id")
                if prior else None)

    standings: list[sg.Standing] = []
    rows: dict[str, dict[str, Any]] = {}
    total = 0.0
    for record in current.to_dict("records"):
        borrower = str(record.get("borrower_id") or "")
        rows[borrower] = record
        total += float(record.get("drawn_exposure") or 0.0)
        before: dict[str, Any] = {}
        if previous is not None and borrower in previous.index:
            before = previous.loc[borrower].to_dict()
        standings.append(sg.stand(record, before, borrower_id=borrower,
                                  period=chosen, previous_period=prior))
    return {"period": chosen, "previous_period": prior,
            "standings": standings, "rows": rows,
            "portfolio_exposure": round(total, 4)}


def run(session: Any, *, period: str = "",
        budget: int = DEFAULT_CASE_BUDGET,
        actor: str = REVIEWER) -> Outcome:
    """Review the book at one reporting date and write the findings. §27.

    Deterministic end to end: the same book at the same period produces the
    same cases in the same order, because the ranking is total and the dedupe
    key is the borrower and the period.
    """
    book = standings_for(period)
    standings: list[sg.Standing] = book["standings"]
    rows: dict[str, dict[str, Any]] = book["rows"]
    outcome = Outcome(period=book["period"],
                      previous_period=book["previous_period"],
                      evaluated=len(standings), budget=budget)
    if not standings:
        return outcome

    outcome.with_signals = sum(1 for s in standings if s.fired)

    decided: list[tuple[sg.Standing, Reason]] = []
    for standing in standings:
        reason = worth_a_case(standing)
        outcome.rules[reason.rule] = outcome.rules.get(reason.rule, 0) + 1
        if reason.raise_it:
            decided.append((standing, reason))
    outcome.qualified = len(decided)

    by_key = {s.borrower_id: r for s, r in decided}
    ranked = [s for s in sg.rank([s for s, _ in decided])]
    chosen = ranked[:budget] if budget > 0 else ranked
    outcome.not_opened = max(0, len(ranked) - len(chosen))

    for standing in chosen:
        row = rows.get(standing.borrower_id, {})
        existing = _existing(session, standing)
        draft = draft_for(
            standing,
            name=str(row.get("display_name") or row.get("legal_name") or ""),
            sector=str(row.get("sector") or ""),
            exposure=_float(row.get("drawn_exposure")),
            portfolio_exposure=book["portfolio_exposure"],
            concentration_share=_share(row.get("sector_concentration_share")),
            reason=by_key.get(standing.borrower_id),
        )
        case = rc.upsert(session, draft, actor_agent=actor)
        outcome.case_ids.append(int(case.id))
        outcome.bands[case.severity] = outcome.bands.get(case.severity, 0) + 1
        if existing:
            outcome.refreshed += 1
        else:
            outcome.opened += 1

    outcome.moved_to_monitoring = _monitor_cured(
        session, standings=standings, period=book["period"], actor=actor)
    return outcome


def _existing(session: Any, standing: sg.Standing) -> bool:
    from sqlalchemy import select

    from backend.models.platform import RiskCase

    key = rc.dedupe_key(level=rc.BORROWER, entity_id=standing.borrower_id,
                        period=standing.period, about=ABOUT)
    return session.execute(
        select(RiskCase.id).where(RiskCase.dedupe_key == key)
    ).scalar_one_or_none() is not None


def _monitor_cured(session: Any, *, standings: list[sg.Standing],
                   period: str, actor: str) -> int:
    """Open early-warning cases whose conditions no longer fire. §24.

    Moved to MONITORING, never to RESOLVED: whether a cured condition means
    the credit is fixed is a judgement, and §38 keeps that judgement with a
    person. What the review can honestly say is that the evidence it raised
    the case on is no longer present, and it says exactly that.
    """
    from sqlalchemy import select

    from backend.models.platform import RiskCase

    cured = {s.borrower_id for s in standings if not s.fired}
    if not cured:
        return 0
    open_cases = session.execute(
        select(RiskCase).where(
            RiskCase.level == rc.BORROWER,
            RiskCase.period == period,
            RiskCase.status.in_(sorted(rc.OPEN - {rc.MONITORING})),
        )
    ).scalars().all()
    moved = 0
    for case in open_cases:
        if case.entity_id not in cured:
            continue
        if str((case.evidence or {}).get("rule", "")) == "":
            continue  # not one of ours
        rc.transition(
            session, case, rc.MONITORING, actor_agent=actor,
            note=("The governed conditions this case was raised on no longer "
                  "fire at this reporting date. Whether the credit itself has "
                  "recovered is a judgement for the case owner; closing the "
                  "case is a person's decision."))
        moved += 1
    return moved


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _share(value: Any) -> float | None:
    """A concentration share as a proportion, whatever the column carries."""
    number = _float(value)
    if number is None:
        return None
    return number / 100.0 if number > 1.0 else number


__all__ = __all__ + ["DEFAULT_CASE_BUDGET", "Outcome", "run", "standings_for"]
