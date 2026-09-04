"""One place that answers "what is this metric, and what is it worth today?"

Everything that shows a number — a lens tile, a chart, an info panel, a
conversational answer, the verification workspace — comes through here. That is
the point of the module: before it, a dashboard's formulas lived in the
component that drew them, so a figure on a screen and the same figure in an
answer were two implementations of one definition.

Three things it holds together:

**Governed and user-built metrics resolve the same way.** The governed library
is code; a metric an analyst built on Tuesday is a row in `user_metrics`.
:func:`resolve` returns a `MetricDefinition` either way, and every caller is
spared knowing which it got. What it must not be spared is *saying* which: the
origin and status travel on the definition and onto every panel.

**Permission is a parameter, not an afterthought.** Every function that can
return a metric takes ``readable`` — the datasets this person may read — and
applies it before anything else. A metric whose denominator reads a dataset you
cannot see is not shown to you with half a ratio; it is not shown to you.

**Nothing here computes.** The arithmetic is `backend.metrics.execution`, which
compiles to the same validated analytical plan as every other analysis in
CreditProbe and runs through `runtime.executor`. A metric that ran its own SQL
would be a second execution path with its own bugs and its own permissions.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from backend.config import settings
from backend.data_access.protocol import DataAccessError
from backend.metrics import execution, library, search
from backend.metrics.catalogue import (
    ORIGIN_USER,
    PERIOD_LATEST_MATURED,
    STATUS_CALCULATION_READY,
    STATUS_DRAFT,
    STATUS_VERIFIED,
    STATUSES,
    MetricDefinition,
    Unsupported,
)
from backend.metrics.formula import (
    Condition,
    Formula,
    FormulaError,
    Side,
    Term,
    check,
    problems,
)

logger = logging.getLogger(__name__)

#: How close two numbers must be, relatively, to count as agreeing when the
#: person checking did not say. One part in ten thousand: tight enough that a
#: real definitional difference shows up, loose enough that float arithmetic
#: and a spreadsheet's rounding do not.
DEFAULT_TOLERANCE = 1e-4

OUTCOME_MATCH = "MATCH"
OUTCOME_WITHIN = "WITHIN_TOLERANCE"
OUTCOME_DIFFERS = "DIFFERS"
OUTCOME_NOT_COMPARED = "NOT_COMPARED"

DECISION_ACCEPTED = "ACCEPTED"
DECISION_REJECTED = "REJECTED"
DECISION_RECORDED = "RECORDED"
DECISIONS = (DECISION_ACCEPTED, DECISION_REJECTED, DECISION_RECORDED)

_SLUG = re.compile(r"[^a-z0-9]+")

#: The three period shapes the platform stores. A chart comparison is
#: arithmetic on these, and a shape not listed here returns no comparison
#: rather than a guessed one.
_MONTHLY = re.compile(r"\d{4}-\d{2}")
_QUARTERLY = re.compile(r"\d{4}-Q[1-4]")
_ANNUAL = re.compile(r"\d{4}")


class MetricNotFound(LookupError):
    """No governed or user metric with that id, or none this person may read."""


class MetricRefused(ValueError):
    """The definition will not be stored, and the message says exactly why."""


class StorageUnavailable(RuntimeError):
    """User metrics need PostgreSQL. The governed catalogue does not."""


# ------------------------------------------------------------- the catalogue


def _catalog() -> Any:
    """The live data catalogue, or None when it cannot be reached.

    Panels degrade to naming their source fields without the field-level
    business definitions rather than failing; a metric whose data source is
    momentarily unreachable should still be able to explain itself.
    """
    try:
        from backend.data_access.catalog import get_catalog

        return get_catalog()
    except Exception:  # noqa: BLE001 - explaining a metric must not need data
        logger.debug("catalogue unavailable while describing a metric",
                     exc_info=True)
        return None


def _from_row(row: Any) -> MetricDefinition:
    """A stored user metric, in the same shape as a governed one."""
    presentation = dict(row.presentation or {})
    return MetricDefinition(
        metric_id=row.metric_id,
        name=row.name,
        definition=row.definition_text or "",
        formula=Formula.from_dict(dict(row.definition or {})),
        unit=row.unit or "number",
        domain=row.domain or "",
        portfolio=row.portfolio or "",
        aliases=tuple(presentation.get("aliases") or ()),
        formula_text=str(presentation.get("formula_text") or ""),
        numerator_text=str(presentation.get("numerator_text") or ""),
        denominator_text=str(presentation.get("denominator_text") or ""),
        period_rule=str(presentation.get("period_rule") or "as_selected"),
        transformation=str(presentation.get("transformation") or ""),
        exclusions=str(presentation.get("exclusions") or ""),
        not_this=str(presentation.get("not_this") or ""),
        visuals=tuple(presentation.get("visuals") or ("kpi",)),
        decimals=int(presentation.get("decimals") or 2),
        higher_is_better=presentation.get("higher_is_better"),
        owner=row.owner or "",
        origin=ORIGIN_USER,
        status=row.status,
        version=row.version or "1.0.0",
        created_by=row.created_by,
        verified_by=row.verified_by,
        verified_at=row.verified_at.isoformat() if row.verified_at else "",
        last_verified_note=row.verification_note or "",
        id=row.id,
    )


def _stored(*, user_id: int | None) -> list[MetricDefinition]:
    """User metrics this person may see: their own, plus anything shared."""
    if not settings.has_database:
        return []
    from sqlalchemy import or_, select

    from backend.db.engine import get_session
    from backend.models.platform import UserMetric

    try:
        with get_session() as session:
            query = select(UserMetric)
            if user_id is None:
                query = query.where(UserMetric.shared.is_(True))
            else:
                query = query.where(or_(UserMetric.shared.is_(True),
                                        UserMetric.created_by == user_id))
            rows = session.execute(query).scalars().all()
            return [_from_row(row) for row in rows]
    except Exception:  # noqa: BLE001 - the governed catalogue still works
        logger.warning("could not read stored metrics", exc_info=True)
        return []


def catalogue(*, user_id: int | None = None,
              readable: Iterable[str] | None = None,
              ) -> list[MetricDefinition]:
    """Every metric this person may see, governed first, then their own."""
    everything = [*library.ALL, *_stored(user_id=user_id)]
    if readable is None:
        return everything
    allowed = set(readable)
    return [m for m in everything
            if all(dataset in allowed for dataset in m.datasets)]


def resolve(metric_id: str, *, user_id: int | None = None,
            readable: Iterable[str] | None = None) -> MetricDefinition:
    """One metric by id, or :class:`MetricNotFound`.

    A metric the asker may not read raises the same error as one that does not
    exist. Distinguishing them would tell somebody what metrics exist over data
    they cannot see, which is a smaller leak than the data but a leak.
    """
    for metric in catalogue(user_id=user_id, readable=readable):
        if metric.metric_id == metric_id:
            return metric
    raise MetricNotFound(f"There is no metric '{metric_id}' available to you.")


def unavailable(metric_id: str) -> Unsupported | None:
    """Whether CreditProbe knows this metric and cannot calculate it here."""
    for entry in library.UNSUPPORTED:
        if entry.metric_id == metric_id:
            return entry
    return None


def find(query: str, *, user_id: int | None = None,
         readable: Iterable[str] | None = None,
         limit: int = search.DEFAULT_LIMIT, domain: str = "") -> dict[str, Any]:
    """Typeahead over everything this person may see.

    Returns the suggestions and, when there are none, whatever CreditProbe
    knows it cannot calculate that the words seem to name — so a picker can
    explain an absence instead of showing an empty list.
    """
    pool = catalogue(user_id=user_id, readable=readable)
    hits = search.search(pool, query, limit=limit, domain=domain)
    payload: dict[str, Any] = {
        "query": query,
        "results": [hit.to_dict() for hit in hits],
        "count": len(hits),
        "unavailable": [],
    }
    if not hits:
        payload["unavailable"] = [
            entry.to_dict()
            for entry in search.unsupported_for(library.UNSUPPORTED, query)]
    return payload


def panel(metric_id: str, *, user_id: int | None = None,
          readable: Iterable[str] | None = None) -> dict[str, Any]:
    """Everything §6 requires an info control to show about one metric."""
    metric = resolve(metric_id, user_id=user_id, readable=readable)
    return metric.panel(catalog=_catalog())


# ------------------------------------------------------------------ running


def _period_order(period: str) -> tuple[int, int, str]:
    """Chronological order for a period label, not alphabetical.

    "Q4 2025" sorts after "Q1 2026" alphabetically, so taking the newest
    period with `max()` on the raw strings picks the wrong quarter — and
    picking the wrong quarter is worse than picking none, because the figure
    still renders and still looks current.
    """
    text = (period or "").strip()
    quarter = re.match(r"^Q([1-4])\s+(\d{4})$", text)
    if quarter:
        return (int(quarter.group(2)), int(quarter.group(1)), "")
    month = re.match(r"^(\d{4})-(\d{1,2})$", text)
    if month:
        return (int(month.group(1)), int(month.group(2)), "")
    if re.fullmatch(r"\d{4}", text):
        return (int(text), 0, "")
    # An unrecognised label still has to order deterministically against its
    # own kind, so the raw text breaks the tie rather than the filesystem.
    return (9999, 9, text)


def periods_with_rows(datasets: Iterable[str],
                      scope: tuple[Any, ...] = ()) -> list[str]:
    """The periods this metric actually has rows in, oldest first.

    Asked of the data rather than of the partition names: a metric scoped to
    the matured cohort has rows in fewer periods than the dataset has
    directories, and the difference is exactly the thing that matters.
    """
    from backend.runtime import ir
    from backend.runtime.executor import execute

    names = [d for d in datasets if d]
    if not names:
        return []
    catalog = _catalog()
    try:
        field = str(catalog.dataset(names[0]).period_field or "")
    except Exception:  # noqa: BLE001 - no catalogue, no period rule
        return []
    if not field:
        return []

    steps = [ir.Operation(id="scan", op=ir.OpType.SCAN,
                          params={"dataset": names[0]})]
    source = "scan"
    if scope:
        steps.append(ir.Operation(
            id="scope", op=ir.OpType.FILTER, inputs=("scan",),
            params={"where": [{"column": c.field, "op": c.op, "value": c.value}
                              for c in scope]}))
        source = "scope"
    steps.append(ir.Operation(
        id="periods", op=ir.OpType.GROUP, inputs=(source,),
        params={"by": [field],
                "aggregates": [{"function": "count", "as": "rows"}]}))

    plan = ir.AnalyticalPlan(
        objective=f"Which periods of {names[0]} carry rows in scope",
        operations=steps, output="periods")
    try:
        result = execute(plan, question="which periods carry rows",
                         intent="metric_period")
    except Exception as e:  # noqa: BLE001 - re-raised as a data problem below
        # Not swallowed. An empty list here means "this source has no period
        # concept", and returning it for a query that merely failed would put
        # the caller back on the unfiltered scan — one figure pooled across
        # every snapshot, labelled with no period. A metric that cannot say
        # which period it is for must not produce a number at all, so this
        # surfaces as the data problem it is and the tile says so.
        logger.warning("could not resolve the periods carrying rows for %s",
                       names[0], exc_info=True)
        raise DataAccessError(
            f"Could not work out which period to use for {names[0]}: {e}"
        ) from e

    found = [str(dict(row).get(field) or "") for row in result.rows
             if int(dict(row).get("rows") or 0) > 0]
    return sorted({p for p in found if p}, key=_period_order)


def latest_period(datasets: Iterable[str], scope: tuple[Any, ...] = ()) -> str:
    """The most recent period this metric has rows in, or "" if it has none.

    This is what "no period was asked for" has to mean. Left unresolved, the
    scan reads every partition and the metric returns one figure pooled over
    the whole history — fifteen quarterly snapshots of a book added together
    and labelled with no period at all. That number is not wrong arithmetic;
    it is an answer to a question nobody asked, and it renders exactly like
    the one they did ask for.
    """
    found = periods_with_rows(datasets, scope)
    return found[-1] if found else ""


def latest_matured_period(metric: MetricDefinition) -> str:
    """The most recent period in which this metric's rows have outcomes.

    A validation metric asked for "now" must not silently answer for the
    latest month: those accounts have not had time to default, so the answer
    is not a low Gini, it is no Gini. The metric's own scope carries the
    maturity condition, so the newest period carrying rows inside that scope
    is the newest period with outcomes.
    """
    return latest_period(metric.datasets, metric.scope)


def default_period(metric: MetricDefinition) -> str:
    """Which period a metric means when nobody named one.

    Never "all of them". A metric read over an unrestricted panel returns one
    figure pooled across every snapshot the lake holds, with no period label
    to warn anyone — a share of a book that does not exist on any date. The
    default is the most recent period the metric has rows in, and the answer
    carries that period so the reader can see which one they got.

    The branch is on the rule rather than on the scope on purpose: today a
    matured-cohort metric carries its maturity condition in its own scope, so
    both paths resolve through the same query, but it is the declared rule
    that decides what "latest" means and it should stay that way.
    """
    if metric.period_rule == PERIOD_LATEST_MATURED:
        return latest_matured_period(metric)
    return latest_period(metric.datasets, metric.scope)


def value(metric_id: str, *, period: str = "", user_id: int | None = None,
          readable: Iterable[str] | None = None,
          question: str = "") -> dict[str, Any]:
    """Calculate one metric now, and show the working.

    The result carries the definition beside the number, because a figure
    somebody cannot trace back to its definition is a figure they will
    recalculate by hand.
    """
    metric = resolve(metric_id, user_id=user_id, readable=readable)
    try:
        # Inside the guard, not before it: resolving which period a metric
        # means is itself a read of the lake, and it fails the same way the
        # metric's own query does. Outside, an unreachable source came back
        # as a raw 500 on a page that had been working.
        period = period or default_period(metric)
        calculation = execution.run(
            metric.formula, period=period, scope=metric.scope,
            question=question
            or f"{metric.name} for {period or 'the latest period'}")
    except DataAccessError as e:
        # A tile whose data is not there says so. Letting this escape would
        # turn one absent period into a failed page, and the reason the reader
        # needs — which periods DO exist — is in the message.
        calculation = execution.Calculation(
            value=None, formula=metric.formula, period=period,
            dataset=metric.datasets[0] if metric.datasets else "")
        calculation.unavailable = str(e)

    return {
        "metric": metric.panel(catalog=_catalog()),
        "calculation": calculation.to_dict(),
        "value": calculation.value,
        "unit": metric.unit,
        "decimals": metric.decimals,
        "period": calculation.period,
        "available": calculation.value is not None,
        "unavailable": calculation.unavailable,
    }


def rows(metric_id: str, *, period: str = "", limit: int = execution.SAMPLE_ROWS,
         user_id: int | None = None,
         readable: Iterable[str] | None = None) -> dict[str, Any]:
    """§10.4's record-level proxy: a handful of rows, with the inclusion logic.

    What makes it useful is not the rows but the columns beside them saying,
    for each term, whether this row counted — which is how somebody checks a
    filter means what they meant.
    """
    metric = resolve(metric_id, user_id=user_id, readable=readable)
    try:
        # The same period the number came from. Rows drawn from every snapshot
        # beside a figure computed for one would not be evidence for it.
        period = period or default_period(metric)
        return execution.sample(metric.formula, period=period,
                                scope=metric.scope, limit=limit)
    except DataAccessError as e:
        # No rows and the reason, as the value route already does. Letting
        # this out would be a raw 500 on a page that had been working, from a
        # gap in the book rather than a fault in the platform.
        return {"columns": [], "rows": [], "period": period,
                "dataset": metric.datasets[0] if metric.datasets else "",
                "limit": int(limit), "unavailable": str(e)}


# ------------------------------------------------------------- user metrics


def _identifier(name: str, user_id: int | None) -> str:
    slug = _SLUG.sub("-", (name or "").strip().lower()).strip("-") or "metric"
    return f"user.{user_id or 0}.{slug}"[:160]


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Metrics people build are stored in PostgreSQL. The governed "
            "catalogue still works without it.")


def _reject_if_broken(formula: Formula) -> None:
    """Refuse a definition that cannot honestly calculate.

    The problems come back as sentences a person can act on — "the denominator
    is empty", "there is no field called `blance`" — rather than as a stack
    trace or, worse, as a stored metric that fails silently at render time.
    """
    found = problems(formula, catalog=_catalog())
    if found:
        raise MetricRefused(
            "This metric will not calculate as written:\n- "
            + "\n- ".join(found))


def create(*, name: str, formula: Formula, definition: str = "",
           unit: str = "number", domain: str = "", portfolio: str = "",
           presentation: dict[str, Any] | None = None,
           user_id: int | None = None, owner: str = "",
           shared: bool = False) -> MetricDefinition:
    """Store a metric somebody built. It arrives DRAFT and stays there.

    Nothing here promotes a metric. A definition becomes CALCULATION_READY
    only by actually calculating (:func:`calculate_check`) and VERIFIED only
    when a person has compared it with their own number and accepted it
    (:func:`verify`). Letting creation confer status would make the governance
    labels decoration.
    """
    _require_db()
    if not (name or "").strip():
        raise MetricRefused("A metric needs a name people will recognise.")
    _reject_if_broken(formula)

    from backend.db.engine import get_session
    from backend.models.platform import UserMetric

    metric_id = _identifier(name, user_id)
    with get_session() as session:
        clash = session.query(UserMetric).filter(
            UserMetric.metric_id == metric_id).first()
        if clash is not None:
            raise MetricRefused(
                f"You already have a metric called '{name}'. Rename one of "
                "them, so a lens naming it means one thing.")
        row = UserMetric(
            metric_id=metric_id, name=name.strip()[:200],
            definition_text=definition, definition=formula.to_dict(),
            presentation=dict(presentation or {}), unit=unit,
            domain=domain, portfolio=portfolio, status=STATUS_DRAFT,
            owner=owner or "", created_by=user_id, shared=bool(shared))
        session.add(row)
        session.commit()
        return _from_row(row)


def update(metric_id: str, *, user_id: int | None = None,
           name: str | None = None, formula: Formula | None = None,
           definition: str | None = None, unit: str | None = None,
           presentation: dict[str, Any] | None = None,
           shared: bool | None = None) -> MetricDefinition:
    """Change a metric somebody built.

    Changing the arithmetic drops the metric back to DRAFT and clears its
    verification. A metric verified against one formula is not verified against
    a different one, and carrying the tick across would be the single most
    misleading thing this module could do.
    """
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import UserMetric

    with get_session() as session:
        row = session.query(UserMetric).filter(
            UserMetric.metric_id == metric_id).first()
        if row is None:
            raise MetricNotFound(f"There is no metric '{metric_id}'.")
        if row.created_by is not None and row.created_by != user_id:
            raise MetricRefused(
                "This metric belongs to somebody else. Copy it if you want "
                "your own version of it.")

        if formula is not None:
            _reject_if_broken(formula)
            changed = formula.to_dict() != dict(row.definition or {})
            row.definition = formula.to_dict()
            if changed:
                row.status = STATUS_DRAFT
                row.verified_by = None
                row.verified_at = None
                row.verification_note = (
                    "Verification cleared: the formula changed after it was "
                    "verified.")
        if name is not None:
            row.name = name.strip()[:200]
        if definition is not None:
            row.definition_text = definition
        if unit is not None:
            row.unit = unit
        if presentation is not None:
            row.presentation = dict(presentation)
        if shared is not None:
            row.shared = bool(shared)
        session.commit()
        return _from_row(row)


def delete(metric_id: str, *, user_id: int | None = None) -> None:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import MetricVerification, UserMetric

    with get_session() as session:
        row = session.query(UserMetric).filter(
            UserMetric.metric_id == metric_id).first()
        if row is None:
            raise MetricNotFound(f"There is no metric '{metric_id}'.")
        if row.created_by is not None and row.created_by != user_id:
            raise MetricRefused("This metric belongs to somebody else.")
        # The verification history goes with it. `metric_id` is derived from
        # the name, so a later metric could be given the same one, and
        # inheriting somebody else's verification record — possibly a tick
        # against a formula it does not share — is the most misleading thing
        # this table could do.
        session.query(MetricVerification).filter(
            MetricVerification.metric_id == metric_id).delete()
        session.delete(row)
        session.commit()


def set_status(metric_id: str, status: str, *,
               user_id: int | None = None) -> MetricDefinition:
    """Move a user metric along its lifecycle.

    VERIFIED is not settable here. It is conferred by :func:`verify` and only
    by an accepted comparison, so that the word means what it says on every
    surface that shows it.
    """
    if status not in STATUSES:
        raise MetricRefused(
            f"'{status}' is not a metric status. Available: "
            f"{', '.join(STATUSES)}.")
    if status == STATUS_VERIFIED:
        raise MetricRefused(
            "A metric becomes verified by being checked against a number "
            "somebody already trusted, not by being marked verified.")
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import UserMetric

    with get_session() as session:
        row = session.query(UserMetric).filter(
            UserMetric.metric_id == metric_id).first()
        if row is None:
            raise MetricNotFound(f"There is no metric '{metric_id}'.")
        if row.created_by is not None and row.created_by != user_id:
            raise MetricRefused("This metric belongs to somebody else.")
        row.status = status
        session.commit()
        return _from_row(row)


def calculate_check(metric_id: str, *, period: str = "",
                    user_id: int | None = None,
                    readable: Iterable[str] | None = None) -> dict[str, Any]:
    """Run a user metric once and record whether it calculates at all.

    This is the only promotion that happens without a person: DRAFT →
    CALCULATION_READY, meaning the definition compiled, executed and produced
    a number. It says nothing about whether the number is *right*, which is
    what the verification workspace is for, and the status label says so.
    """
    metric = resolve(metric_id, user_id=user_id, readable=readable)
    outcome = value(metric_id, period=period, user_id=user_id,
                    readable=readable)
    if metric.origin != ORIGIN_USER or not settings.has_database:
        return outcome
    if outcome["available"] and metric.status == STATUS_DRAFT:
        from backend.db.engine import get_session
        from backend.models.platform import UserMetric

        with get_session() as session:
            row = session.query(UserMetric).filter(
                UserMetric.metric_id == metric_id).first()
            if row is not None and row.status == STATUS_DRAFT:
                row.status = STATUS_CALCULATION_READY
                session.commit()
        outcome["metric"] = resolve(
            metric_id, user_id=user_id, readable=readable).panel(
                catalog=_catalog())
    return outcome


# ----------------------------------------------------------- verification


@dataclass(frozen=True)
class Comparison:
    """What CreditProbe computed, what the person expected, and the gap."""

    metric_id: str
    period: str
    computed: float | None
    expected: float | None
    difference: float | None
    relative: float | None
    outcome: str
    tolerance: float
    run_id: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id, "period": self.period,
            "computed": self.computed, "expected": self.expected,
            "difference": self.difference, "relative": self.relative,
            "outcome": self.outcome, "tolerance": self.tolerance,
            "run_id": self.run_id, "note": self.note,
            "agrees": self.outcome in (OUTCOME_MATCH, OUTCOME_WITHIN),
        }


def compare(computed: float | None, expected: float | None, *,
            tolerance: float = DEFAULT_TOLERANCE) -> tuple[str, float | None,
                                                           float | None]:
    """Decide whether two numbers agree, without touching either of them.

    The computed value is never adjusted toward the expected one. That is the
    whole discipline of §10: if the engine and the analyst disagree, the record
    says they disagreed and somebody finds out why.
    """
    if computed is None or expected is None:
        return OUTCOME_NOT_COMPARED, None, None
    difference = computed - expected
    scale = max(abs(computed), abs(expected))
    relative = abs(difference) / scale if scale else 0.0
    if difference == 0.0:
        return OUTCOME_MATCH, difference, relative
    if relative <= max(tolerance, 0.0):
        return OUTCOME_WITHIN, difference, relative
    return OUTCOME_DIFFERS, difference, relative


def verify(metric_id: str, *, expected: float | None, period: str = "",
           expected_source: str = "", note: str = "",
           tolerance: float = DEFAULT_TOLERANCE,
           decision: str = DECISION_RECORDED, user_id: int | None = None,
           readable: Iterable[str] | None = None) -> dict[str, Any]:
    """Put somebody's own number beside CreditProbe's, and keep the record.

    Kept whether they agreed or not. A verification history showing three
    disagreements before a definition was corrected is more useful than one
    showing only the final tick.

    A metric only becomes VERIFIED when the two agree *and* the person accepted
    it. Accepting a comparison that differs is allowed — sometimes the analyst's
    number was the wrong one — but it does not confer the label, because the
    stored evidence would not support it.
    """
    if decision not in DECISIONS:
        raise MetricRefused(
            f"'{decision}' is not a decision. Available: "
            f"{', '.join(DECISIONS)}.")

    metric = resolve(metric_id, user_id=user_id, readable=readable)
    outcome = value(metric_id, period=period, user_id=user_id,
                    readable=readable)
    computed = outcome["value"]
    run_id = str((outcome["calculation"] or {}).get("run_id") or "")
    # The period the figure actually came from, not the blank the caller sent.
    # A verification record is evidence, and evidence that does not say which
    # period it is about supports nothing.
    period = outcome["period"] or period

    verdict, difference, relative = compare(computed, expected,
                                            tolerance=tolerance)
    comparison = Comparison(
        metric_id=metric_id, period=period, computed=computed,
        expected=expected, difference=difference, relative=relative,
        outcome=verdict, tolerance=tolerance, run_id=run_id, note=note)

    agreed = verdict in (OUTCOME_MATCH, OUTCOME_WITHIN)
    promoted = False
    if settings.has_database:
        from backend.db.engine import get_session
        from backend.models.platform import MetricVerification, UserMetric

        with get_session() as session:
            session.add(MetricVerification(
                metric_id=metric_id, period=period, computed=computed,
                run_id=run_id, expected=expected,
                expected_source=expected_source[:240], difference=difference,
                outcome=verdict, tolerance=tolerance, note=note,
                decision=decision, created_by=user_id))
            if (metric.origin == ORIGIN_USER
                    and decision == DECISION_ACCEPTED and agreed):
                row = session.query(UserMetric).filter(
                    UserMetric.metric_id == metric_id).first()
                if row is not None:
                    from sqlalchemy import func as sa_func

                    row.status = STATUS_VERIFIED
                    row.verified_by = user_id
                    row.verified_at = sa_func.now()
                    row.verification_note = note or expected_source
                    promoted = True
            session.commit()

    payload = comparison.to_dict()
    payload["decision"] = decision
    payload["expected_source"] = expected_source
    payload["recorded"] = settings.has_database
    payload["metric_status"] = (
        STATUS_VERIFIED if promoted else
        resolve(metric_id, user_id=user_id, readable=readable).status)
    if decision == DECISION_ACCEPTED and not agreed:
        payload["note_on_status"] = (
            "Recorded as accepted, but the metric is not marked verified: the "
            "two numbers did not agree, and the evidence stored here would "
            "not support the label.")
    return payload


def verifications(metric_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
    """What has been checked about this metric, newest first."""
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import MetricVerification

    with get_session() as session:
        rows = session.execute(
            select(MetricVerification)
            .where(MetricVerification.metric_id == metric_id)
            .order_by(MetricVerification.created_at.desc())
            .limit(max(1, limit))
        ).scalars().all()
        return [{
            "id": row.id, "period": row.period, "computed": row.computed,
            "expected": row.expected, "difference": row.difference,
            "outcome": row.outcome, "tolerance": row.tolerance,
            "expected_source": row.expected_source, "note": row.note,
            "decision": row.decision, "run_id": row.run_id,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        } for row in rows]


def formula_from_dict(payload: dict[str, Any]) -> Formula:
    """Parse a formula somebody submitted, refusing anything that will not run.

    Deliberately the only door into a stored formula. Nothing accepts free text
    that later becomes SQL: the payload is a structured formula, validated
    against the governed catalogue, and compiled to the same analytical plan
    every other analysis uses.
    """
    try:
        formula = Formula.from_dict(payload or {})
    except Exception as e:  # noqa: BLE001 - this parses untrusted input
        # Deliberately broad. The payload comes off the wire, and every way it
        # can be malformed must arrive as a refusal a person can read, not as
        # a 500 with a stack trace behind it. A submitted string where an
        # object belongs raises AttributeError, which a narrower clause missed.
        raise MetricRefused(
            f"That is not a formula this platform can read: {e}") from e
    try:
        return check(formula, catalog=_catalog())
    except FormulaError as e:
        raise MetricRefused(str(e)) from e


def described(metric: MetricDefinition, **changes: Any) -> MetricDefinition:
    """A copy with fields changed, for callers assembling a preview."""
    return replace(metric, **changes)


__all__ = [
    "DEFAULT_TOLERANCE", "OUTCOME_MATCH", "OUTCOME_WITHIN", "OUTCOME_DIFFERS",
    "OUTCOME_NOT_COMPARED", "DECISION_ACCEPTED", "DECISION_REJECTED",
    "DECISION_RECORDED", "DECISIONS",
    "MetricNotFound", "MetricRefused", "StorageUnavailable", "Comparison",
    "catalogue", "resolve", "unavailable", "find", "panel", "value", "rows",
    "create", "update", "delete", "set_status", "calculate_check",
    "compare", "verify", "verifications", "formula_from_dict", "described",
]


# ---------------------------------------------------------------------- charts

#: Field names a chart will not offer to group by, whatever their type. An
#: account id is a string with as many values as there are rows: grouping by
#: it produces a "chart" with one bar per account, which is not a chart.
_NOT_A_DIMENSION = ("_id", "id", "reference", "name", "iban", "national_id")

#: Sensitivity classifications a chart may group by. A dimension becomes an
#: axis label on a shared screen, so anything more sensitive than internal is
#: not offered — the metric may still be scoped by it, which is a filter and
#: shows nobody the value.
_DIMENSION_SENSITIVITY = ("", "none", "internal", "public")

#: How a chart may roll rows up inside each group.
AGGREGATIONS = {
    "metric": "The metric's own definition, recomputed for each group",
    "average": "The average of the measure per row in the group",
    "count": "How many rows fall in the group",
}

SORTS = {"value": "By value", "label": "By name"}
DIRECTIONS = {"desc": "Largest first", "asc": "Smallest first"}

#: What a chart may be compared against. Every one of these resolves to a real
#: period that is read the same way the primary series is; there is no
#: modelled or projected comparison here, and a comparison period with no data
#: is reported as absent rather than drawn as zero.
COMPARISONS = {
    "": "No comparison",
    "previous_period": "The period before this one",
    "same_period_last_year": "The same period a year earlier",
}

#: Chart types this builder can produce. `kpi` is not among them: a chart has
#: a dimension, and a single figure does not.
CHART_TYPES = ("bar", "line", "matrix")


def chart_types_for(metric: MetricDefinition,
                    dimension: dict[str, Any] | None
                    ) -> tuple[list[str], list[dict[str, str]]]:
    """Which chart types are honest for this metric over this dimension.

    Three refusals, and none of them is a matter of taste.

    A `matrix` needs two dimensions and this builder configures one, so it is
    never offered here. A `line` asserts that the points are in an order and
    that the space between them means something; that is true of a period and
    of a band, and false of a product. And a metric computed by a governed
    function cannot be broken out at all, so it gets no chart rather than a
    misleading one.

    `MetricDefinition.visuals` is deliberately NOT consulted here. It says how
    the metric itself should be drawn as a tile — as a figure, as a trend —
    and forty of the sixty-one governed metrics leave it at the field's
    default of `("kpi",)`, which is an un-authored default rather than a
    decision that the metric must never be broken out. Reading it as a
    governance refusal would refuse "utilisation by product" — an ordinary,
    honest bar chart — on the strength of a default nobody wrote.
    """
    if metric.formula.kind == "function":
        return [], [{"name": t, "because": (
            f"{metric.name} is computed by a governed function over the "
            "underlying rows, so it cannot be broken out across a dimension "
            "at all.")} for t in CHART_TYPES]

    ordered = bool(dimension and (
        dimension.get("over_time")
        or str(dimension.get("name", "")).lower().endswith(
            ("_bin", "_band", "_bucket"))))

    available: list[str] = []
    refused: list[dict[str, str]] = []
    for kind in CHART_TYPES:
        because = ""
        if kind == "matrix":
            because = ("A matrix compares two dimensions. This chart has one, "
                       "so there is nothing to put on the second axis.")
        elif kind == "line" and dimension is not None and not ordered:
            because = (
                f"{dimension.get('business_name') or dimension.get('name')} "
                "has no order, so a line between its points would suggest a "
                "progression that is not there. A bar compares them without "
                "claiming one.")
        if because:
            refused.append({"name": kind, "because": because})
        else:
            available.append(kind)
    return available, refused


def dimension_fields(metric: MetricDefinition) -> list[dict[str, Any]]:
    catalog = _catalog()
    if catalog is None or not metric.datasets:
        return []
    try:
        entry = catalog.dataset(metric.datasets[0])
    except Exception:  # noqa: BLE001 - a dataset that has gone
        return []

    keys = {str(k) for k in (entry.primary_keys or [])}
    period_field = str(entry.period_field or "")
    out: list[dict[str, Any]] = []
    for field_def in entry.fields.values():
        name = str(field_def.name)
        lowered = name.lower()
        if str(getattr(field_def, "sensitivity", "") or "").lower() \
                not in _DIMENSION_SENSITIVITY:
            continue
        if name in keys and name != period_field:
            continue
        if any(lowered == bad or lowered.endswith(bad)
               for bad in _NOT_A_DIMENSION):
            continue
        allowed = list(field_def.allowed_values or [])
        categorical = (bool(allowed)
                       or str(field_def.data_type) in ("string", "boolean")
                       or lowered.endswith(("_bin", "_band", "_bucket")))
        if not (categorical or name == period_field):
            continue
        out.append({
            "name": name,
            "business_name": field_def.business_name or name,
            "definition": field_def.definition or "",
            "data_type": field_def.data_type,
            "allowed_values": allowed,
            "over_time": name == period_field,
        })
    out.sort(key=lambda d: (not d["over_time"], d["business_name"].lower()))
    return out


def chart_vocabulary(metric_id: str, *, dimension: str = "",
                     user_id: int | None = None,
                     readable: Iterable[str] | None = None) -> dict[str, Any]:
    """Everything a chart over this metric may be configured with.

    The builder offers only what is here, and the server checks it again on
    submission: a picker is a convenience, never a control. Which chart types
    appear is the metric's own declaration — a metric that says it can
    honestly be drawn as a line does not become a matrix because somebody
    picked one from a global list.
    """
    metric = resolve(metric_id, user_id=user_id, readable=readable)
    dimensions = dimension_fields(metric)

    simple = _simple_sum(metric)
    aggregations = [{"name": "metric", "label": AGGREGATIONS["metric"],
                     "available": True, "unavailable_because": ""}]
    for name in ("average", "count"):
        aggregations.append({
            "name": name, "label": AGGREGATIONS[name],
            "available": bool(simple) or name == "count",
            "unavailable_because": "" if simple or name == "count" else (
                f"{metric.name} is not a single total, so an average of it "
                "per row is not a number that means anything. The metric's "
                "own definition is the honest roll-up here."),
        })

    chosen = next((d for d in dimensions if d["name"] == dimension), None)
    types, refused = chart_types_for(metric, chosen)
    return {
        "metric": metric.panel(catalog=_catalog()),
        "dimensions": [
            {**d, "chart_types": chart_types_for(metric, d)[0]}
            for d in dimensions],
        "aggregations": aggregations,
        "dimension": dimension,
        "chart_types": types,
        "chart_types_refused": refused,
        "sorts": SORTS,
        "directions": DIRECTIONS,
        "comparisons": COMPARISONS,
        "max_groups": execution.MAX_GROUPS,
        "periods": periods_with_rows(metric.datasets, metric.scope),
    }


def may_average(metric: MetricDefinition) -> bool:
    """Whether "the average per row" is a number this metric has.

    Public because the lens validator asks the same question before it will
    store a chart configured that way, and two implementations of "is this an
    honest average" would eventually disagree.
    """
    return _simple_sum(metric) is not None


def _simple_sum(metric: MetricDefinition) -> Term | None:
    """The single summed term a chart may re-aggregate, or nothing.

    A ratio has no such term. Neither has a metric built from several terms
    combined — averaging "defaulted balance minus recoveries" per row is not
    an average of anything a person named.
    """
    formula = metric.formula
    if formula.kind == "function":
        return None
    if formula.denominator and formula.denominator.terms:
        return None
    terms = formula.numerator.terms
    if len(terms) != 1:
        return None
    term = terms[0]
    if term.aggregate != "sum" or not term.field:
        return None
    return term


def _chart_formula(metric: MetricDefinition, aggregate: str) -> tuple[Formula, str]:
    """The formula a chart actually computes, and what to call the series.

    An overridden aggregation is a different calculation from the governed
    metric, so it gets a different name on the chart. A bar labelled "Default
    rate" that is really "average balance per account" is the kind of thing
    somebody presents to a board.
    """
    if aggregate not in AGGREGATIONS:
        raise MetricRefused(
            f"'{aggregate}' is not a way a chart may roll rows up. "
            f"Available: {', '.join(AGGREGATIONS)}.")
    if aggregate == "metric":
        return metric.formula, metric.name

    dataset = metric.datasets[0] if metric.datasets else ""
    if aggregate == "count":
        term = Term(id="rows", label="Rows", dataset=dataset,
                    aggregate="count")
        return (Formula(kind="sum", numerator=Side(terms=(term,))),
                "Number of rows")

    simple = _simple_sum(metric)
    if simple is None:
        raise MetricRefused(
            f"{metric.name} is not a single total, so an average of it per "
            "row is not a number that means anything. Use the metric's own "
            "definition, or count the rows.")
    averaged = Term(id=simple.id, label=f"Average {simple.label.lower()}",
                    dataset=simple.dataset, aggregate="avg",
                    field=simple.field, where=simple.where)
    return (Formula(kind="sum", numerator=Side(terms=(averaged,))),
            f"Average {simple.label.lower()} per row")


def _chart_filters(metric: MetricDefinition,
                   filters: dict[str, Any] | None) -> tuple[Condition, ...]:
    """The chart's own filters, checked against the dataset's real fields.

    Checked here rather than trusted from the client for the obvious reason:
    a filter is a `WHERE` clause, and a name that reached the compiler without
    passing through the catalogue would be a column named by a caller.
    """
    if not filters:
        return ()
    catalog = _catalog()
    known: set[str] = set()
    if catalog is not None and metric.datasets:
        try:
            known = {str(f.name)
                     for f in catalog.dataset(metric.datasets[0]).fields.values()}
        except Exception:  # noqa: BLE001 - a dataset that has gone
            known = set()

    out: list[Condition] = []
    for name, value in filters.items():
        field_name = str(name)
        if known and field_name not in known:
            raise MetricRefused(
                f"'{field_name}' is not a field on "
                f"{metric.datasets[0] if metric.datasets else 'this dataset'}, "
                "so a chart cannot filter on it.")
        if isinstance(value, dict):
            op = str(value.get("op") or "=")
            out.append(Condition(field=field_name, op=op,
                                 value=value.get("value")))
        elif isinstance(value, (list, tuple)):
            out.append(Condition(field=field_name, op="in", value=list(value)))
        else:
            out.append(Condition(field=field_name, op="=", value=value))
    return tuple(out)


def _shift_period(period: str, *, months: int) -> str:
    """The period `months` before this one, in the same shape it came in.

    Only the shapes the platform actually stores: `YYYY-MM` and `YYYY-Qn` and
    `YYYY`. An unrecognised shape returns empty, and the caller reports that
    the comparison could not be resolved rather than guessing at one.
    """
    text = (period or "").strip()
    if _MONTHLY.fullmatch(text):
        year, month = int(text[:4]), int(text[5:7])
        total = year * 12 + (month - 1) - months
        return f"{total // 12:04d}-{total % 12 + 1:02d}"
    if _QUARTERLY.fullmatch(text):
        if months % 3:
            return ""
        year, quarter = int(text[:4]), int(text[6])
        total = year * 4 + (quarter - 1) - months // 3
        return f"{total // 4:04d}-Q{total % 4 + 1}"
    if _ANNUAL.fullmatch(text):
        if months % 12:
            return ""
        return f"{int(text) - months // 12:04d}"
    return ""


def series(metric_id: str, *, dimension: str, period: str = "",
           filters: dict[str, Any] | None = None,
           aggregate: str = "metric", sort: str = "value",
           direction: str = "desc", limit: int = execution.MAX_GROUPS,
           compare: str = "", user_id: int | None = None,
           readable: Iterable[str] | None = None) -> dict[str, Any]:
    """One chart: a metric across a dimension, and how it is defined.

    Everything a reader needs to challenge the picture travels with it — the
    definition, the SQL, the run id, how many rows each group holds and how
    many groups were left out. A chart that cannot be challenged is decoration.
    """
    metric = resolve(metric_id, user_id=user_id, readable=readable)

    offerable = {d["name"]: d for d in dimension_fields(metric)}
    if dimension not in offerable:
        raise MetricRefused(
            f"'{dimension}' is not a dimension {metric.name} can be broken "
            "out by. Available: "
            f"{', '.join(sorted(offerable)) or 'none on this dataset'}.")
    if sort not in SORTS:
        raise MetricRefused(
            f"'{sort}' is not a way a chart may be sorted. "
            f"Available: {', '.join(SORTS)}.")
    if direction not in DIRECTIONS:
        raise MetricRefused(
            f"'{direction}' is not a sort direction. "
            f"Available: {', '.join(DIRECTIONS)}.")
    if compare not in COMPARISONS:
        raise MetricRefused(
            f"'{compare}' is not a comparison a chart may draw. "
            f"Available: {', '.join(k or 'none' for k in COMPARISONS)}.")

    formula, series_label = _chart_formula(metric, aggregate)
    where = _chart_filters(metric, filters)
    over_time = bool(offerable[dimension]["over_time"])

    notes: list[str] = []
    if aggregate != "metric":
        notes.append(
            f"This chart shows {series_label.lower()}, not {metric.name}. "
            "The aggregation was changed on the chart, so the series is "
            "named for what it actually computes.")

    try:
        # A chart over the period field is the trend: every period the dataset
        # holds, not one of them. Filtering the scan to a single period and
        # then grouping by it would draw one point and call it a line.
        wanted = "" if over_time else (period or default_period(metric))
        drawn = execution.breakdown(
            formula, dimension=dimension, period=wanted, scope=metric.scope,
            where=where, sort=("label" if over_time else sort),
            direction=("asc" if over_time else direction), limit=limit,
            question=f"{series_label} by {dimension}")
    except DataAccessError as e:
        return {
            "metric": metric.panel(catalog=_catalog()),
            "series_label": series_label, "dimension": dimension,
            "dimension_label": offerable[dimension]["business_name"],
            "over_time": over_time, "aggregate": aggregate,
            "sort": sort, "direction": direction, "compare": compare,
            "filters": {c.field: c.value for c in where},
            "unit": metric.unit, "decimals": metric.decimals,
            "higher_is_better": (metric.higher_is_better
                                 if aggregate == "metric" else None),
            "period": period, "points": [], "comparison": None,
            "notes": notes, "unavailable": str(e),
        }

    if over_time:
        notes.append(
            "Every period the dataset holds, in order. The period selection "
            "does not apply to a chart whose dimension IS the period.")

    comparison: dict[str, Any] | None = None
    if compare and not over_time:
        months = 12 if compare == "same_period_last_year" else 1
        against = _shift_period(drawn["period"], months=months)
        if not against:
            notes.append(
                f"'{COMPARISONS[compare]}' could not be worked out from a "
                f"period written as '{drawn['period']}', so no comparison is "
                "drawn.")
        else:
            available = periods_with_rows(metric.datasets, metric.scope)
            if against not in available:
                notes.append(
                    f"There is no data for {against}, so the comparison is "
                    "not drawn. That is a gap in the book, not a zero.")
            else:
                try:
                    other = execution.breakdown(
                        formula, dimension=dimension, period=against,
                        scope=metric.scope, where=where, sort="label",
                        direction="asc", limit=execution.MAX_GROUPS,
                        question=f"{series_label} by {dimension}, {against}")
                except DataAccessError as e:
                    notes.append(
                        f"The comparison against {against} could not be "
                        f"read: {e}")
                else:
                    by_label = {p["label"]: p["value"] for p in other["points"]}
                    comparison = {
                        "period": against,
                        "label": COMPARISONS[compare],
                        "points": [
                            {"label": p["label"],
                             "value": by_label.get(p["label"]),
                             "change": (
                                 None if p["value"] is None
                                 or by_label.get(p["label"]) is None
                                 else p["value"] - by_label[p["label"]])}
                            for p in drawn["points"]],
                        "run_id": other["run_id"],
                        "sql": other["sql"],
                    }

    if drawn["truncated"]:
        notes.append(
            f"{drawn['groups_found']} groups were found and "
            f"{len(drawn['points'])} are drawn. The rest are not in the "
            "picture, so it is not the whole population.")
    if drawn.get("scan_capped"):
        notes.append(
            f"More than {execution.GROUP_CEILING} groups exist. Only the "
            "first that many were read, so this is a sample of the "
            "dimension rather than all of it.")

    return {
        "metric": metric.panel(catalog=_catalog()),
        "series_label": series_label,
        "dimension": dimension,
        "dimension_label": offerable[dimension]["business_name"],
        "over_time": over_time,
        "aggregate": aggregate,
        "sort": sort,
        "direction": direction,
        "compare": compare,
        "filters": {c.field: c.value for c in where},
        "unit": metric.unit,
        "decimals": metric.decimals,
        "higher_is_better": (metric.higher_is_better
                             if aggregate == "metric" else None),
        "period": drawn["period"],
        "points": drawn["points"],
        "comparison": comparison,
        "groups_found": drawn["groups_found"],
        "truncated": drawn["truncated"],
        "dataset": drawn["dataset"],
        "sql": drawn["sql"],
        "run_id": drawn["run_id"],
        "notes": notes,
        "unavailable": drawn["unavailable"],
    }
