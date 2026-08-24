"""
Playbooks: a standing instruction the platform carries out.

What a Playbook is
------------------
Four parts, and each one is a question somebody in credit risk already asks:

    TRIGGER     when should this run? on demand, when new data is published,
                or on a schedule
    SCOPE       over what? governed dimensions only — a sector, a segment, a
                region
    ANALYSES    which certified functions should run, with which parameters
    CONDITIONS  what would make this worth somebody's attention? a named metric
                against a threshold
    ACTIONS     and then what? open an investigation, tell someone

Why this replaced Blueprints
----------------------------
A Blueprint was a template of a document — something you filled in. A Playbook
is a thing that RUNS. The difference matters because the work a credit team
repeats every quarter is not writing the same document; it is asking the same
questions of new data and noticing when an answer has changed.

What it cannot do
-----------------
A Playbook selects from the registered analyses and evaluates a threshold
against a figure the engine returned. It cannot invent an analysis, write a
query, compute a metric of its own, or take any action outside the list above.
A run that finds nothing says so and stops; it never manufactures a finding to
justify having run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)

TRIGGER_MANUAL = "manual"
TRIGGER_NEW_DATA = "new_data"
TRIGGER_SCHEDULED = "scheduled"
TRIGGERS = (TRIGGER_MANUAL, TRIGGER_NEW_DATA, TRIGGER_SCHEDULED)

TRIGGER_LABEL = {
    TRIGGER_MANUAL: "On demand",
    TRIGGER_NEW_DATA: "When new data is published",
    TRIGGER_SCHEDULED: "On a schedule",
}

STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUSES = (STATUS_DRAFT, STATUS_ACTIVE, STATUS_PAUSED)

#: Comparisons a condition may make. Deliberately a closed list: a condition is
#: evaluated against a figure the engine produced, and allowing an arbitrary
#: expression would be allowing arbitrary code.
OPERATORS = {
    ">": lambda value, threshold: value > threshold,
    ">=": lambda value, threshold: value >= threshold,
    "<": lambda value, threshold: value < threshold,
    "<=": lambda value, threshold: value <= threshold,
    "==": lambda value, threshold: abs(value - threshold) < 1e-9,
    "!=": lambda value, threshold: abs(value - threshold) >= 1e-9,
}

OPERATOR_LABEL = {
    ">": "is above", ">=": "is at or above", "<": "is below",
    "<=": "is at or below", "==": "equals", "!=": "does not equal",
}

SEVERITIES = ("info", "warning", "critical")

#: Governed dimensions a playbook may scope itself to. Anything else is refused,
#: so a scope cannot become a way of filtering on an ungoverned column.
SCOPE_DIMENSIONS = ("sector", "segment", "region", "product_type", "rating_bucket",
                    "country")

SLUG_RE = re.compile(r"[^a-z0-9]+")


class PlaybookNotFound(LookupError):
    pass


class InvalidPlaybook(ValueError):
    """The definition is not one the platform will run, and the message says why."""


class StorageUnavailable(RuntimeError):
    """Playbooks need PostgreSQL. Running an analysis does not."""


def _require_db() -> None:
    if not settings.has_database:
        raise StorageUnavailable(
            "Playbooks are stored in PostgreSQL. Analyses still run without it; "
            "the standing instruction just is not kept."
        )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def slugify(name: str) -> str:
    slug = SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "playbook"


# ------------------------------------------------------------- validation


def validate(*, analyses: list[dict[str, Any]], conditions: list[dict[str, Any]],
             scope: dict[str, Any], trigger: str) -> None:
    """Refuse a definition the platform cannot honestly run.

    Every check here exists because the alternative is a playbook that appears
    to work and quietly does nothing — the worst possible failure for a standing
    instruction nobody watches.
    """
    from backend.engine.registry import get_registry

    if trigger not in TRIGGERS:
        raise InvalidPlaybook(
            f"'{trigger}' is not a trigger. Available: {', '.join(TRIGGERS)}."
        )
    if not analyses:
        raise InvalidPlaybook("A playbook must run at least one analysis.")

    registry = get_registry()
    known = {c.id for c in registry.contracts()}
    for entry in analyses:
        analysis_id = str(entry.get("analysis_id") or "")
        if analysis_id not in known:
            raise InvalidPlaybook(
                f"'{analysis_id}' is not a registered analysis. A playbook can "
                "only run analyses the Engine Registry knows about."
            )

    for dimension in scope or {}:
        if dimension not in SCOPE_DIMENSIONS:
            raise InvalidPlaybook(
                f"'{dimension}' is not a governed dimension. A playbook may "
                f"scope itself to: {', '.join(SCOPE_DIMENSIONS)}."
            )

    for condition in conditions or []:
        operator = str(condition.get("operator") or "")
        if operator not in OPERATORS:
            raise InvalidPlaybook(
                f"'{operator}' is not a comparison a condition may make. "
                f"Available: {', '.join(OPERATORS)}."
            )
        if not str(condition.get("metric") or "").strip():
            raise InvalidPlaybook("Every condition must name the metric it tests.")
        try:
            float(condition.get("threshold"))
        except (TypeError, ValueError):
            raise InvalidPlaybook(
                f"The threshold for '{condition.get('metric')}' is not a number."
            ) from None
        severity = str(condition.get("severity") or "warning")
        if severity not in SEVERITIES:
            raise InvalidPlaybook(
                f"'{severity}' is not a severity. Available: {', '.join(SEVERITIES)}."
            )


# ------------------------------------------------------------------- shape


@dataclass
class PlaybookView:
    id: int
    slug: str
    name: str
    description: str
    trigger: str
    trigger_label: str
    schedule: str
    scope: dict[str, Any]
    analyses: list[dict[str, Any]]
    conditions: list[dict[str, Any]]
    actions: dict[str, Any]
    status: str
    origin: str
    owner: str
    last_run_at: str | None = None
    next_run_hint: str = ""
    run_count: int = 0
    last_run: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "trigger_label": self.trigger_label,
            "schedule": self.schedule,
            "scope": self.scope,
            "analyses": self.analyses,
            "conditions": self.conditions,
            "actions": self.actions,
            "status": self.status,
            "origin": self.origin,
            "owner": self.owner,
            "last_run_at": self.last_run_at,
            "next_run_hint": self.next_run_hint,
            "run_count": self.run_count,
            "last_run": self.last_run,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _view(session: Any, row: Any, *, with_runs: bool = False) -> PlaybookView:
    from sqlalchemy import func, select

    from backend.models.platform import PlaybookRun

    count = session.execute(
        select(func.count(PlaybookRun.id)).where(PlaybookRun.playbook_id == row.id)
    ).scalar() or 0
    last = session.execute(
        select(PlaybookRun)
        .where(PlaybookRun.playbook_id == row.id)
        .order_by(PlaybookRun.id.desc())
    ).scalars().first() if with_runs or True else None

    return PlaybookView(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        trigger=row.trigger,
        trigger_label=TRIGGER_LABEL.get(row.trigger, row.trigger),
        schedule=row.schedule,
        scope=dict(row.scope or {}),
        analyses=list(row.analyses or []),
        conditions=list(row.conditions or []),
        actions=dict(row.actions or {}),
        status=row.status,
        origin=row.origin,
        owner=row.owner,
        last_run_at=_iso(row.last_run_at),
        next_run_hint=row.next_run_hint,
        run_count=int(count),
        last_run=_run_dict(last) if last else None,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _run_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "playbook_id": row.playbook_id,
        "status": row.status,
        "period": dict(row.period or {}),
        "results": list(row.results or []),
        "evaluations": list(row.evaluations or []),
        "actions_taken": list(row.actions_taken or []),
        "alerted": row.alerted,
        "summary": row.summary,
        "error": row.error,
        "investigation_id": row.investigation_id,
        "created_at": _iso(row.created_at),
    }


# ------------------------------------------------------------------ writing


def create(*, name: str, description: str = "", trigger: str = TRIGGER_MANUAL,
           schedule: str = "", scope: dict[str, Any] | None = None,
           analyses: list[dict[str, Any]] | None = None,
           conditions: list[dict[str, Any]] | None = None,
           actions: dict[str, Any] | None = None,
           origin: str = "manual", owner: str = "",
           user_id: int | None = None) -> PlaybookView:
    _require_db()
    analyses = list(analyses or [])
    conditions = list(conditions or [])
    scope = dict(scope or {})
    validate(analyses=analyses, conditions=conditions, scope=scope, trigger=trigger)

    from backend.db.engine import get_session
    from backend.models.platform import Playbook

    with get_session() as session:
        slug = slugify(name)
        # Slugs are unique, and a second playbook called "Quarterly review" is a
        # perfectly reasonable thing to want.
        existing = {s for (s,) in session.query(Playbook.slug).all()}
        if slug in existing:
            n = 2
            while f"{slug}-{n}" in existing:
                n += 1
            slug = f"{slug}-{n}"

        row = Playbook(
            slug=slug, name=name[:200], description=description,
            trigger=trigger, schedule=schedule[:64], scope=scope,
            analyses=analyses, conditions=conditions, actions=dict(actions or {}),
            status=STATUS_DRAFT, origin=origin, owner=owner[:160],
            owner_id=user_id,
        )
        session.add(row)
        session.flush()
        session.commit()
        return _view(session, row)


def update(playbook_id: int, **changes: Any) -> PlaybookView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Playbook

    with get_session() as session:
        row = session.get(Playbook, playbook_id)
        if row is None:
            raise PlaybookNotFound(f"Playbook {playbook_id} does not exist.")

        validate(
            analyses=list(changes.get("analyses") or row.analyses or []),
            conditions=list(changes.get("conditions") or row.conditions or []),
            scope=dict(changes.get("scope") or row.scope or {}),
            trigger=str(changes.get("trigger") or row.trigger),
        )
        for key in ("name", "description", "trigger", "schedule", "scope",
                    "analyses", "conditions", "actions", "status", "owner"):
            value = changes.get(key)
            if value is not None:
                setattr(row, key, value)
        session.commit()
        return _view(session, row)


def set_status(playbook_id: int, status: str) -> PlaybookView:
    if status not in STATUSES:
        raise InvalidPlaybook(
            f"'{status}' is not a playbook status. Available: {', '.join(STATUSES)}."
        )
    return update(playbook_id, status=status)


def delete(playbook_id: int) -> None:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Playbook

    with get_session() as session:
        row = session.get(Playbook, playbook_id)
        if row is None:
            raise PlaybookNotFound(f"Playbook {playbook_id} does not exist.")
        session.delete(row)
        session.commit()


# ------------------------------------------------------------------ reading


def listing(*, status: str | None = None) -> list[dict[str, Any]]:
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import Playbook

    with get_session() as session:
        query = select(Playbook).order_by(Playbook.updated_at.desc())
        if status:
            query = query.where(Playbook.status == status)
        return [_view(session, row).to_dict()
                for row in session.execute(query).scalars().all()]


def get(playbook_id: int) -> PlaybookView:
    _require_db()
    from backend.db.engine import get_session
    from backend.models.platform import Playbook

    with get_session() as session:
        row = session.get(Playbook, playbook_id)
        if row is None:
            raise PlaybookNotFound(f"Playbook {playbook_id} does not exist.")
        return _view(session, row, with_runs=True)


def runs(playbook_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    if not settings.has_database:
        return []
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.platform import PlaybookRun

    with get_session() as session:
        rows = session.execute(
            select(PlaybookRun)
            .where(PlaybookRun.playbook_id == playbook_id)
            .order_by(PlaybookRun.id.desc())
            .limit(limit)
        ).scalars().all()
        return [_run_dict(r) for r in rows]


# ------------------------------------------------------------------ running


@dataclass
class Evaluation:
    """One condition, tested against a figure the engine returned."""

    metric: str
    label: str
    operator: str
    threshold: float
    severity: str
    #: None when the analyses did not produce this metric at all, which is a
    #: different thing from the condition being false.
    value: float | None
    met: bool
    analysis_id: str = ""
    unit: str = ""

    @property
    def sentence(self) -> str:
        if self.value is None:
            return (
                f"{self.label} was not produced by the analyses this playbook "
                "runs, so the condition could not be tested."
            )
        # OPERATOR_LABEL already reads as a verb phrase ("is above"), so the
        # negation is applied inside it rather than in front of it.
        comparison = OPERATOR_LABEL[self.operator]
        if not self.met:
            comparison = comparison.replace("is ", "is not ", 1)
        return (
            f"{self.label} is {self.value:,.3g}{self.unit}, which {comparison} "
            f"the threshold of {self.threshold:,.3g}{self.unit}."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "label": self.label,
            "operator": self.operator,
            "operator_label": OPERATOR_LABEL[self.operator],
            "threshold": self.threshold,
            "severity": self.severity,
            "value": self.value,
            "unit": self.unit,
            "met": self.met,
            "testable": self.value is not None,
            "analysis_id": self.analysis_id,
            "sentence": self.sentence,
        }


@dataclass
class RunResult:
    playbook_id: int
    status: str
    period: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    alerted: bool = False
    summary: str = ""
    error: str = ""
    investigation_id: int | None = None
    run_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "playbook_id": self.playbook_id,
            "status": self.status,
            "period": self.period,
            "results": self.results,
            "evaluations": self.evaluations,
            "actions_taken": self.actions_taken,
            "alerted": self.alerted,
            "summary": self.summary,
            "error": self.error,
            "investigation_id": self.investigation_id,
        }


def _find_metric(results: list[dict[str, Any]], metric: str) -> tuple[float | None, str, str]:
    """The value of one named metric across everything the playbook ran.

    Searched by exact key in each analysis's returned values. Nothing is
    inferred, computed or converted: if no analysis produced a metric by that
    name, the answer is that it was not produced.
    """
    for result in results:
        values = result.get("values") or {}
        if metric in values:
            value = values[metric]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            unit = (result.get("units") or {}).get(metric, "")
            return float(value), str(result.get("analysis_id") or ""), str(unit)
    return None, "", ""


def run(playbook_id: int, *, period: str | None = None,
        user_id: int | None = None) -> RunResult:
    """Execute a playbook: run its analyses, test its conditions, act.

    The analyses run through the ordinary engine runner, so every figure carries
    a Trace exactly as it would if somebody had asked for it by hand. Nothing
    about being inside a playbook changes how a number is produced.
    """
    _require_db()
    from backend.db.engine import get_session
    from backend.engine.runner import persist_run, run_analysis
    from backend.models.platform import Playbook, PlaybookRun

    with get_session() as session:
        row = session.get(Playbook, playbook_id)
        if row is None:
            raise PlaybookNotFound(f"Playbook {playbook_id} does not exist.")
        definition = {
            "name": row.name,
            "scope": dict(row.scope or {}),
            "analyses": list(row.analyses or []),
            "conditions": list(row.conditions or []),
            "actions": dict(row.actions or {}),
        }

    # Outside the session: this executes real analyses and can take seconds.
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for entry in definition["analyses"]:
        analysis_id = str(entry.get("analysis_id"))
        params = dict(entry.get("params") or {})
        try:
            outcome = run_analysis(
                analysis_id, params=params, period=period,
                filters=definition["scope"], user_id=user_id,
            )
        except Exception as e:  # pragma: no cover - a genuinely broken analysis
            failures.append(f"{analysis_id}: {e}")
            continue
        if outcome.status != "succeeded" or outcome.result is None:
            failures.append(f"{analysis_id}: {outcome.error or 'returned nothing'}")
            continue
        # Persisted like any other run, so the figures a playbook reports are
        # reachable from the Trace exactly as a hand-asked question's are.
        results.append({
            "analysis_id": analysis_id,
            "analysis_run_id": persist_run(outcome, user_id=user_id),
            "values": dict(outcome.result.values or {}),
            "units": dict(outcome.result.units or {}),
            "row_count": len(outcome.result.rows or []),
        })

    evaluations: list[Evaluation] = []
    for condition in definition["conditions"]:
        metric = str(condition["metric"])
        operator = str(condition["operator"])
        threshold = float(condition["threshold"])
        value, source, unit = _find_metric(results, metric)
        evaluations.append(Evaluation(
            metric=metric,
            label=str(condition.get("label") or metric.replace("_", " ").capitalize()),
            operator=operator,
            threshold=threshold,
            severity=str(condition.get("severity") or "warning"),
            value=value,
            met=bool(value is not None and OPERATORS[operator](value, threshold)),
            analysis_id=source,
            unit=str(condition.get("unit") or unit),
        ))

    met = [e for e in evaluations if e.met]
    untestable = [e for e in evaluations if e.value is None]
    alerted = bool(met)

    summary = _summarise(definition["name"], results, evaluations, failures)

    actions_taken: list[dict[str, Any]] = []
    investigation_id: int | None = None
    if alerted and definition["actions"].get("create_investigation"):
        investigation_id = _open_investigation(definition, met, user_id)
        if investigation_id:
            actions_taken.append({
                "action": "create_investigation",
                "investigation_id": investigation_id,
                "detail": "Opened an investigation on what the playbook found.",
            })
    if alerted and definition["actions"].get("notify"):
        notified = _notify(definition, met, user_id)
        actions_taken.extend(notified)

    status = "failed" if failures and not results else "succeeded"

    with get_session() as session:
        row = session.get(Playbook, playbook_id)
        record = PlaybookRun(
            playbook_id=playbook_id,
            status=status,
            period={"period": period} if period else {},
            results=results,
            evaluations=[e.to_dict() for e in evaluations],
            actions_taken=actions_taken,
            alerted=alerted,
            summary=summary,
            error="; ".join(failures),
            investigation_id=investigation_id,
            created_by=user_id,
        )
        session.add(record)
        session.flush()
        if row is not None:
            from sqlalchemy import func as sqlfunc

            row.last_run_at = sqlfunc.now()
        run_id = record.id
        session.commit()

    logger.info(
        "Playbook %s ran: %d analyses, %d conditions met, %d untestable",
        playbook_id, len(results), len(met), len(untestable),
    )
    return RunResult(
        playbook_id=playbook_id, status=status,
        period={"period": period} if period else {},
        results=results, evaluations=[e.to_dict() for e in evaluations],
        actions_taken=actions_taken, alerted=alerted, summary=summary,
        error="; ".join(failures), investigation_id=investigation_id, run_id=run_id,
    )


def _summarise(name: str, results: list[dict[str, Any]],
               evaluations: list[Evaluation], failures: list[str]) -> str:
    """What the run found, in plain words.

    Every figure in the sentence came from an analysis. A run that found nothing
    says so — it does not reach for something to report.
    """
    if not results:
        return (
            f"{name} could not run. "
            + ("; ".join(failures) if failures else "No analysis returned a result.")
        )

    met = [e for e in evaluations if e.met]
    untestable = [e for e in evaluations if e.value is None]
    ran = f"{len(results)} {'analysis' if len(results) == 1 else 'analyses'} ran"

    if not evaluations:
        return (
            f"{ran}. This playbook sets no conditions, so there is nothing for it "
            "to have found — the results are there to be read."
        )
    if not met:
        note = (
            f" {len(untestable)} condition"
            f"{'' if len(untestable) == 1 else 's'} could not be tested, because "
            "the analyses did not produce the metric."
            if untestable else ""
        )
        return (
            f"{ran} and none of the {len(evaluations)} conditions were met. "
            f"Nothing here needs attention.{note}"
        )

    worst = "critical" if any(e.severity == "critical" for e in met) else (
        "warning" if any(e.severity == "warning" for e in met) else "info"
    )
    lead = met[0]
    return (
        f"{ran}. {len(met)} of {len(evaluations)} conditions were met, the most "
        f"serious at {worst} level. {lead.sentence} "
        "This states what the thresholds found. It does not establish why."
    )


def _open_investigation(definition: dict[str, Any], met: list[Evaluation],
                        user_id: int | None) -> int | None:
    """Open a thread on what the playbook found, so somebody can ask into it."""
    from backend.services import threads as th

    lead = met[0]
    question = (
        f"{lead.label} is {lead.value:,.3g}{lead.unit}. What is driving it?"
    )
    try:
        thread = th.create(
            question=question,
            title=f"{definition['name']}: {lead.label}",
            context=dict(definition.get("scope") or {}),
            user_id=user_id,
        )
    except Exception as e:  # pragma: no cover - storage went away mid-run
        logger.warning("Playbook could not open an investigation: %s", e)
        return None
    return thread.id


def _notify(definition: dict[str, Any], met: list[Evaluation],
            user_id: int | None) -> list[dict[str, Any]]:
    from backend.services import workflow as wf

    recipients = definition["actions"].get("notify") or []
    out: list[dict[str, Any]] = []
    for recipient in recipients:
        try:
            user = int(recipient)
        except (TypeError, ValueError):
            continue
        try:
            wf.notify_playbook_finding(
                user_id=user,
                playbook=str(definition.get("name") or ""),
                title=f"{definition['name']}: {len(met)} condition(s) met",
                body=met[0].sentence,
                actor_id=user_id,
            )
            out.append({"action": "notify", "user_id": user})
        except Exception as e:  # pragma: no cover - notification is best effort
            logger.warning("Playbook could not notify %s: %s", user, e)
    return out


__all__ = [
    "OPERATORS",
    "OPERATOR_LABEL",
    "SCOPE_DIMENSIONS",
    "SEVERITIES",
    "STATUSES",
    "TRIGGERS",
    "TRIGGER_LABEL",
    "Evaluation",
    "InvalidPlaybook",
    "PlaybookNotFound",
    "PlaybookView",
    "RunResult",
    "StorageUnavailable",
    "create",
    "delete",
    "get",
    "listing",
    "run",
    "runs",
    "set_status",
    "slugify",
    "update",
    "validate",
]
