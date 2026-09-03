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
from backend.metrics.formula import Formula, FormulaError, check, problems

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


def latest_matured_period(metric: MetricDefinition) -> str:
    """The most recent period in which this metric's rows have outcomes.

    A validation metric asked for "now" must not silently answer for the
    latest month: those accounts have not had time to default, so the answer
    is not a low Gini, it is no Gini. This finds the newest period that
    actually carries matured rows, and the info panel says that is the rule.
    """
    from backend.runtime import ir
    from backend.runtime.executor import execute

    datasets = metric.datasets
    if not datasets:
        return ""
    catalog = _catalog()
    try:
        field = str(catalog.dataset(datasets[0]).period_field or "")
    except Exception:  # noqa: BLE001 - no catalogue, no period rule
        return ""
    if not field:
        return ""

    steps = [ir.Operation(id="scan", op=ir.OpType.SCAN,
                          params={"dataset": datasets[0]})]
    source = "scan"
    if metric.scope:
        steps.append(ir.Operation(
            id="scope", op=ir.OpType.FILTER, inputs=("scan",),
            params={"where": [{"column": c.field, "op": c.op, "value": c.value}
                              for c in metric.scope]}))
        source = "scope"
    steps.append(ir.Operation(
        id="periods", op=ir.OpType.GROUP, inputs=(source,),
        params={"by": [field],
                "aggregates": [{"function": "count", "as": "rows"}]}))

    plan = ir.AnalyticalPlan(
        objective=f"Which periods of {datasets[0]} carry rows in scope",
        operations=steps, output="periods")
    try:
        result = execute(plan, question="latest matured period",
                         intent="metric_period")
    except Exception:  # noqa: BLE001 - fall back to the caller's period
        logger.warning("could not resolve the latest matured period for %s",
                       metric.metric_id, exc_info=True)
        return ""

    periods = [str(dict(row).get(field) or "") for row in result.rows
               if int(dict(row).get("rows") or 0) > 0]
    return max(periods) if periods else ""


def value(metric_id: str, *, period: str = "", user_id: int | None = None,
          readable: Iterable[str] | None = None,
          question: str = "") -> dict[str, Any]:
    """Calculate one metric now, and show the working.

    The result carries the definition beside the number, because a figure
    somebody cannot trace back to its definition is a figure they will
    recalculate by hand.
    """
    metric = resolve(metric_id, user_id=user_id, readable=readable)
    if not period and metric.period_rule == PERIOD_LATEST_MATURED:
        period = latest_matured_period(metric)
    try:
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
    return execution.sample(metric.formula, period=period,
                            scope=metric.scope, limit=limit)


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
