"""Writing a validation run down, and reading it back unchanged.

The property this module exists to hold
---------------------------------------
**A stored run never changes, and never recalculates.**

Every read below assembles from rows. Not one of them calls the runner, opens
a parquet partition, or consults the registry for anything but a label. That
is what makes "open the run the committee saw" a different operation from
"run it again and hope", and it is the whole reason the tables exist.

The service exposes no update path for a result, a finding or a finalised
report. Not "an update path nobody calls" — none. A schema that permits
editing a historical result is one in which "what did we see then?" has no
answer, and the cheapest way to keep that impossible is to give the code no
way to express it.

Where the versions come from
----------------------------
The run header carries five version strings, read from the code that produced
the answer rather than passed in by a caller. A caller that can name its own
calculation version can name the wrong one, and the row would then assert
something nobody checked.

What a re-run is
----------------
A new row. `duplicate` copies a run's CONFIGURATION — the model, the window,
the segment, the categories, the tests — and nothing else, then the caller
executes it. The earlier run keeps its results exactly as they were, and
`duplicated_from_id` makes the pair obvious rather than something a reader has
to reconstruct from timestamps.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.models.scorecard_validation import (
    ScvFinding,
    ScvReport,
    ScvResult,
    ScvRun,
)
from backend.scorecard.validation import findings as finding_engine
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import runner, states

STORE_VERSION = "1.0.0"

#: How many runs a history page returns before it asks to be paged. A
#: validation history is read, not scrolled — a screen that returns everything
#: is one that gets slower every month it is used.
PAGE = 50


class StoreError(RuntimeError):
    """A write the store refuses, or a read that found nothing."""


class Immutable(StoreError):
    """An attempt to change something that is evidence.

    Raised rather than ignored. A silent refusal is a caller that believes it
    edited a historical result, and a validation environment in which that
    belief is possible is one whose history nobody can rely on.
    """


# ============================================================ what data this was


def dataset_as_of(model: model_registry.Model) -> tuple[str, str]:
    """The lake's own as-of for this model's dataset, and a version for it.

    Two runs with different values here read different data whatever else
    matches, and that is the first fact a reader of a historical run needs.

    The as-of is the newest partition. The version is a digest over every
    partition name and its modification time — so a rebuilt month, a corrected
    month, or a month that arrived late all change it, and none of them is
    visible from the partition name alone.
    """
    periods = runner.available_periods(model)
    if not periods:
        return "", ""
    root = Path(runner._analytics_root()) / model.dataset
    parts = []
    for period in periods:
        where = root / f"{model.period_field}={period}"
        try:
            parts.append(f"{period}:{where.stat().st_mtime_ns}")
        except OSError:
            parts.append(f"{period}:missing")
    digest = hashlib.blake2b("|".join(parts).encode("utf-8"),
                             digest_size=8).hexdigest()
    return periods[-1], digest


# ==================================================================== writing


@dataclass(frozen=True)
class Caller:
    """Who asked for the run, as it should be recorded.

    The name is stored beside the id on purpose. A person who leaves the bank
    must not turn a signed validation into one nobody ran, and a foreign key
    that goes NULL does exactly that.
    """

    user_id: int | None = None
    name: str = ""
    role: str = ""
    source: str = "UI"
    detail: str = ""


def _run_key(model_id: str) -> str:
    """A public identifier that is stable, quotable, and not the row id.

    Not derived from the run's content: two genuinely separate runs of the
    same configuration over the same data are two runs, and a content hash
    would collapse them into one.
    """
    return f"SCVR-{model_id}-{uuid.uuid4().hex[:12]}"


def save(session: Session, *, model: model_registry.Model,
         results: list[states.Result], caller: Caller,
         scope: str = "FULL", categories: tuple[str, ...] = (),
         tests: tuple[str, ...] = (), periods: tuple[str, ...] = (),
         segment: str = "", segment_field: str = "",
         started_at: datetime | None = None,
         duplicated_from: int | None = None,
         model_kind: str = "CHAMPION") -> ScvRun:
    """Write one run and everything it produced. Called once, never again.

    The findings are computed here rather than taken from the caller, so a run
    cannot be stored with a findings set that does not follow from its own
    results — which would be a stored contradiction nobody could later
    unpick.
    """
    now = datetime.now(UTC)
    began = started_at or now
    available = runner.available_periods(model)
    matured = runner.matured_periods(model)
    as_of, version = dataset_as_of(model)

    in_scope = _rows_in_scope(model)
    assessed = finding_engine.assess(results, model)
    burning = {f.finding_id for f in finding_engine.burning(assessed)}
    measured = [r for r in results if r.measured]

    run = ScvRun(
        run_key=_run_key(model.model_id),
        model_id=model.model_id,
        model_name=model.name,
        model_version=model.version,
        model_kind=model_kind,
        scorecard_type=model.scorecard_type,
        domain=model.domain,
        dataset=model.dataset,
        reference_dataset=model.reference_dataset,
        decisions_dataset=model.decisions_dataset,
        dataset_as_of=as_of,
        dataset_version=version,
        requested_periods=list(periods),
        matured_window=(f"{matured[0]}..{matured[-1]}" if matured else ""),
        latest_period=(available[-1] if available else ""),
        reference_period=model.development_population or "",
        segment=segment,
        segment_field=segment_field,
        periods_available=len(available),
        periods_matured=len(matured),
        periods_immature=len(available) - len(matured),
        performance_window_months=model.performance_window_months,
        scope=scope,
        requested_categories=list(categories),
        requested_tests=list(tests),
        # Read from the code that produced the answer. A caller that can name
        # its own calculation version can name the wrong one.
        registry_version=test_registry.REGISTRY_VERSION,
        threshold_profile_version=model_registry.MODELS_VERSION,
        calculation_version=runner.RUNNER_VERSION,
        states_version=states.STATES_VERSION,
        findings_version=finding_engine.FINDINGS_VERSION,
        returned=len(results),
        measured=len(measured),
        tally=states.tally(results),
        coverage=test_registry.coverage({r.test_id for r in measured}),
        findings_summary=finding_engine.summary(assessed),
        initiated_by_id=caller.user_id,
        initiated_by_name=caller.name,
        initiated_by_role=caller.role,
        source=caller.source,
        source_detail=caller.detail,
        status="COMPLETE",
        started_at=began,
        finished_at=now,
        duration_ms=max(0, int((now - began).total_seconds() * 1000)),
        duplicated_from_id=duplicated_from,
    )
    session.add(run)
    session.flush()

    seen: set[tuple[str, str]] = set()
    for result in states.rank(results):
        # The unique constraint would refuse a duplicate anyway; refusing here
        # names the pair rather than surfacing an IntegrityError from the
        # flush, which tells a reader nothing about which test collided.
        key = (result.test_id, result.segment)
        if key in seen:
            raise StoreError(
                f"{result.test_id} appears twice for segment "
                f"{result.segment or '(none)'} in one run. Two answers to one "
                "question, with nothing saying which is the run's.")
        seen.add(key)
        found = test_registry.resolve(result.test_id)
        session.add(ScvResult(
            run_id=run.id,
            test_id=result.test_id,
            test_name=(found.name if found else ""),
            category=(found.category if found else ""),
            state=result.state,
            state_label=states.STATE_LABELS.get(result.state, result.state),
            measured=result.measured,
            severity=states.SEVERITY_ORDER.get(result.state, 0),
            value=result.value,
            limit_value=result.limit,
            limit_source=result.limit_source,
            comparison_value=result.comparison_value,
            detail=result.detail,
            remedy=result.remedy,
            method=result.method,
            limitations=list(result.limitations),
            period=result.period,
            reference_period=result.reference_period,
            segment=result.segment,
            observations=result.observations,
            matured_observations=result.matured_observations,
            events=result.events,
            # What the test dropped. "24,119 of 54,038" is a different
            # statement from "24,119", and only the first lets a reader judge.
            excluded=(max(0, in_scope - result.observations)
                      if result.observations and in_scope else 0),
            score_direction=result.score_direction,
            calculation_version=result.calculation_version,
            chart=dict(result.chart or {}),
            result_table=list(result.table or []),
            lineage=dict(result.lineage or {}),
        ))

    for finding in assessed:
        body = finding.to_dict()
        session.add(ScvFinding(
            run_id=run.id,
            finding_key=body["finding_id"],
            title=body.get("title", ""),
            severity=body.get("severity", ""),
            severity_rank=finding_engine.SEVERITY_RANK.get(
                body.get("severity", ""), 0),
            category=body.get("category", ""),
            burning=body["finding_id"] in burning,
            pattern=body.get("pattern", ""),
            what=body.get("what", ""),
            why_it_matters=body.get("why_it_matters", ""),
            remediation=body.get("remediation", ""),
            verify_by=body.get("verify_by", ""),
            evidence=list(body.get("evidence", ())),
            cbuae=list(body.get("cbuae", ())),
            values=dict(body.get("values", {})),
            confidence=body.get("confidence", ""),
            period=body.get("period", ""),
            segment=body.get("segment", ""),
        ))

    session.flush()
    return run


def _rows_in_scope(model: model_registry.Model) -> int:
    """How many rows the model's dataset holds in total, cheaply.

    Used only to say how many a test excluded. Returns 0 rather than raising
    when the lake is unreadable: an exclusion count nobody can compute is a
    missing number, and a missing number must not stop a run being recorded.
    """
    try:
        pool = runner.population(model, matured_only=False)
    except Exception:  # noqa: BLE001 - a count is not worth failing a save for
        return 0
    return int(len(pool.frame))


def fail(session: Session, *, model: model_registry.Model, caller: Caller,
         because: str, scope: str = "FULL",
         started_at: datetime | None = None) -> ScvRun:
    """Record a run that could not complete.

    Kept rather than discarded. A validation that failed is a fact about the
    environment on that day, and deleting it hides the one thing an auditor
    asking "why is there no run for March?" needs to see.
    """
    now = datetime.now(UTC)
    run = ScvRun(
        run_key=_run_key(model.model_id),
        model_id=model.model_id, model_name=model.name,
        model_version=model.version, scorecard_type=model.scorecard_type,
        domain=model.domain, dataset=model.dataset,
        scope=scope, status="FAILED", failure=because[:4000],
        registry_version=test_registry.REGISTRY_VERSION,
        threshold_profile_version=model_registry.MODELS_VERSION,
        calculation_version=runner.RUNNER_VERSION,
        states_version=states.STATES_VERSION,
        findings_version=finding_engine.FINDINGS_VERSION,
        initiated_by_id=caller.user_id, initiated_by_name=caller.name,
        initiated_by_role=caller.role, source=caller.source,
        source_detail=caller.detail,
        started_at=started_at or now, finished_at=now,
    )
    session.add(run)
    session.flush()
    return run


# ==================================================================== reading


def get(session: Session, run_key: str) -> ScvRun:
    """One run, with its results and findings. Assembled from rows only."""
    found = session.execute(
        select(ScvRun)
        .options(selectinload(ScvRun.results),
                 selectinload(ScvRun.findings))
        .where(ScvRun.run_key == run_key)
    ).scalar_one_or_none()
    if found is None:
        raise StoreError(f"{run_key!r} is not a validation run on this "
                         "deployment.")
    return found


def history(session: Session, *, model_id: str = "", limit: int = PAGE,
            offset: int = 0) -> list[ScvRun]:
    """The runs, newest first. Headers only — a list screen needs no results."""
    query = select(ScvRun).order_by(
        ScvRun.started_at.desc(),
        ScvRun.id.desc())
    if model_id:
        query = query.where(ScvRun.model_id == model_id)
    return list(session.execute(
        query.limit(max(1, min(limit, 200))).offset(max(0, offset))
    ).scalars().all())


def count(session: Session, *, model_id: str = "") -> int:
    from sqlalchemy import func

    query = select(func.count(ScvRun.id))
    if model_id:
        query = query.where(ScvRun.model_id == model_id)
    return int(session.execute(query).scalar_one())


def duplicate(run: ScvRun) -> dict[str, Any]:
    """The CONFIGURATION of a run, for executing again against current data.

    Deliberately not the results. "Re-run using current data" means exactly
    that: the same question asked of whatever the lake holds now, producing a
    NEW run that can be compared against this one. Copying the results as well
    would produce a row that claims to be a fresh measurement of stale
    numbers.
    """
    return {
        "model_id": run.model_id,
        "model_kind": run.model_kind,
        "scope": run.scope,
        "categories": list(run.requested_categories or []),
        "tests": list(run.requested_tests or []),
        "periods": list(run.requested_periods or []),
        "segment": run.segment,
        "segment_field": run.segment_field,
        "duplicated_from_id": run.id,
        "duplicated_from_key": run.run_key,
    }


# =============================================================== serialisation


def run_header(run: ScvRun) -> dict[str, Any]:
    """A run for a list screen. No results, and no invitation to fetch them."""
    return {
        "run_key": run.run_key,
        "model_id": run.model_id,
        "model_name": run.model_name,
        "model_version": run.model_version,
        "model_kind": run.model_kind,
        "scorecard_type": run.scorecard_type,
        "dataset": run.dataset,
        "dataset_as_of": run.dataset_as_of,
        "dataset_version": run.dataset_version,
        "matured_window": run.matured_window,
        "latest_period": run.latest_period,
        "requested_periods": list(run.requested_periods or []),
        "segment": run.segment,
        "segment_field": run.segment_field,
        "periods_available": run.periods_available,
        "periods_matured": run.periods_matured,
        "periods_immature": run.periods_immature,
        "scope": run.scope,
        "requested_categories": list(run.requested_categories or []),
        "requested_tests": list(run.requested_tests or []),
        "registry_version": run.registry_version,
        "threshold_profile_version": run.threshold_profile_version,
        "calculation_version": run.calculation_version,
        "states_version": run.states_version,
        "findings_version": run.findings_version,
        "returned": run.returned,
        "measured": run.measured,
        "tally": dict(run.tally or {}),
        "findings_summary": dict(run.findings_summary or {}),
        "initiated_by": run.initiated_by_name,
        "initiated_by_role": run.initiated_by_role,
        "source": run.source,
        "source_detail": run.source_detail,
        "status": run.status,
        "failure": run.failure,
        "started_at": run.started_at.isoformat() if run.started_at else "",
        "finished_at": run.finished_at.isoformat() if run.finished_at else "",
        "duration_ms": run.duration_ms,
        "duplicated_from_id": run.duplicated_from_id,
        "immutable": True,
        "reproduced_from": "stored rows, not recalculated",
    }


def result_body(row: ScvResult) -> dict[str, Any]:
    """A stored result in the SAME shape the live runner returns.

    Identical on purpose: the cockpit renders a historical run through the
    components it uses for a fresh one, so a stored result and a live one
    cannot look like different kinds of thing to a reader. They are the same
    kind of thing — one of them is just older.
    """
    return {
        "test_id": row.test_id,
        "state": row.state,
        "state_label": row.state_label,
        "state_meaning": states.STATE_MEANING.get(row.state, ""),
        "severity": row.severity,
        "measured": row.measured,
        "value": row.value,
        "limit": row.limit_value,
        "limit_source": row.limit_source,
        "comparison_value": row.comparison_value,
        "detail": row.detail,
        "remedy": row.remedy,
        "method": row.method,
        "limitations": list(row.limitations or []),
        "model_id": row.run.model_id if row.run else "",
        "model_version": row.run.model_version if row.run else "",
        "dataset": row.run.dataset if row.run else "",
        "period": row.period,
        "reference_period": row.reference_period,
        "segment": row.segment,
        "observations": row.observations,
        "matured_observations": row.matured_observations,
        "events": row.events,
        "excluded": row.excluded,
        "score_direction": row.score_direction,
        "calculation_version": row.calculation_version,
        "states_version": row.run.states_version if row.run else "",
        "chart": dict(row.chart or {}),
        "table": list(row.result_table or []),
        "lineage": dict(row.lineage or {}),
    }


def finding_body(row: ScvFinding) -> dict[str, Any]:
    return {
        "finding_id": row.finding_key,
        "title": row.title,
        "severity": row.severity,
        "severity_meaning": finding_engine.SEVERITY_MEANING.get(
            row.severity, ""),
        "category": row.category,
        "burning": row.burning,
        "pattern": row.pattern,
        "what": row.what,
        "why_it_matters": row.why_it_matters,
        "remediation": row.remediation,
        "verify_by": row.verify_by,
        "evidence": list(row.evidence or []),
        "cbuae": list(row.cbuae or []),
        "values": dict(row.values or {}),
        "confidence": row.confidence,
        "period": row.period,
        "segment": row.segment,
    }


def to_result(row: ScvResult) -> states.Result:
    """A stored row back as the `Result` the engine produced.

    Used to build a report from a HISTORICAL run without the report builder
    knowing anything about storage — it receives the same objects it would
    have received on the day, and produces the same document.

    The reconstruction goes through `Result.__post_init__`, which is the
    point. That constructor refuses a measured state carrying no value and an
    unmeasured state carrying one, so a row that lost its invariant somewhere
    between the engine and the database fails here rather than becoming a
    report.
    """
    return states.Result(
        test_id=row.test_id,
        state=row.state,
        value=row.value,
        limit=row.limit_value,
        limit_source=row.limit_source,
        comparison_value=row.comparison_value,
        detail=row.detail,
        remedy=row.remedy,
        model_id=row.run.model_id if row.run else "",
        model_version=row.run.model_version if row.run else "",
        dataset=row.run.dataset if row.run else "",
        period=row.period,
        reference_period=row.reference_period,
        segment=row.segment,
        observations=row.observations,
        matured_observations=row.matured_observations,
        events=row.events,
        calculation_version=row.calculation_version,
        score_direction=row.score_direction,
        method=row.method,
        limitations=tuple(row.limitations or ()),
        chart=dict(row.chart or {}),
        table=list(row.result_table or []),
        lineage=dict(row.lineage or {}),
    )


def results_of(run: ScvRun) -> list[states.Result]:
    """Every stored result of a run, as engine objects, in registry order."""
    return [to_result(row) for row in
            sorted(run.results, key=lambda r: (r.severity, r.test_id))]


def run_body(run: ScvRun) -> dict[str, Any]:
    """The whole run: header, every result, every finding.

    The shape matches what a live run returns, for the reason `result_body`
    gives — with one addition the live shape has no need for, and which is
    the point of the whole module.
    """
    ordered = sorted(run.results, key=lambda r: (r.severity, r.test_id))
    body = run_header(run)
    body.update({
        "results": [result_body(r) for r in ordered],
        "findings": [finding_body(f) for f in sorted(
            run.findings, key=lambda f: (f.severity_rank, f.finding_key))],
        "burning_weaknesses": [finding_body(f) for f in sorted(
            run.findings, key=lambda f: (f.severity_rank, f.finding_key))
            if f.burning],
        "coverage": dict(run.coverage or {}),
        "regulatory_coverage": dict(run.regulatory_coverage or {}),
        "adverse": [r.test_id for r in ordered
                    if r.state in (states.FAIL, states.WARNING)],
        "coverage_means": (
            "A test counted here is one that produced a number. A test that "
            "refused is stored with its reason and is not counted as "
            "covered."),
        "historical": (
            "These values were computed when the run was made and have been "
            "read back unchanged. They are not a recalculation, and they will "
            "not move when the data does."),
    })
    return body


# ==================================================================== reports


def save_report(session: Session, *, run: ScvRun,
                document: dict[str, Any], caller: Caller,
                source_run_keys: tuple[str, ...] = ()
                ) -> ScvReport:
    """Bind a report to the run it was built from, by foreign key.

    Not by timestamp and not by convention. A report opened next year
    assembles from THAT run's stored results, so a finalised document cannot
    silently follow the latest validation — which is the specific failure this
    binding exists to prevent.

    The DOCX is not stored. It is regenerated from `document`, and
    `content_hash` proves the regeneration matches. Keeping the file as well
    would create a second source of truth that can disagree with the first.

    `content_hash` is the REPORT'S OWN hash, copied out of the content rather
    than computed again here. `Report.content_hash` deliberately excludes the
    document-control section, so it answers "has the assessment changed?"
    rather than "was this generated twice?"; a second hash taken over the
    whole dict would answer the second question under the first question's
    name, and the two would disagree on every regeneration.
    """
    body = dict(document or {})
    stored_hash = str(body.get("content_hash") or "")
    if not stored_hash:
        raise StoreError(
            "A report without a content hash cannot be stored. The hash is "
            "how a regenerated document proves it matches the one that was "
            "reviewed.")
    version = 1 + int(session.execute(
        select(ScvReport.version)
        .where(ScvReport.run_id == run.id)
        .order_by(ScvReport.version.desc()).limit(1)
    ).scalar() or 0)

    report = ScvReport(
        report_key=f"{body.get('report_id') or run.run_key}-v{version}",
        run_id=run.id,
        source_run_keys=list(source_run_keys),
        model_id=run.model_id,
        model_version=run.model_version,
        title=str(body.get("title") or ""),
        opinion=str(body.get("opinion") or ""),
        status="DRAFT",
        version=version,
        structure_version=str(body.get("structure_version") or ""),
        registry_version=run.registry_version,
        calculation_version=run.calculation_version,
        dataset_as_of=run.dataset_as_of,
        content_hash=stored_hash,
        document=body,
        generated_by_id=caller.user_id,
        generated_by_name=caller.name,
    )
    session.add(report)
    session.flush()
    return report


def finalise(session: Session, *, report_key: str,
             caller: Caller) -> ScvReport:
    """Sign a draft. After this the row is evidence and cannot be edited.

    A correction is a NEW report against a NEW run, pointing back through
    `supersedes_id`. There is no path that rewrites a signed document,
    because a signed document that can change is not a signature.
    """
    report = session.execute(
        select(ScvReport)
        .where(ScvReport.report_key == report_key)
    ).scalar_one_or_none()
    if report is None:
        raise StoreError(f"{report_key!r} is not a report on this deployment.")
    if report.status == "FINAL":
        raise Immutable(
            f"{report_key} was finalised on "
            f"{report.finalised_at:%Y-%m-%d} by "
            f"{report.finalised_by_name or 'a validator'}. A correction is a "
            "new report against a new run, not an edit of a signed one.")
    if report.status == "SUPERSEDED":
        raise Immutable(f"{report_key} has been superseded.")
    report.status = "FINAL"
    report.finalised_at = datetime.now(UTC)
    report.finalised_by_id = caller.user_id
    report.finalised_by_name = caller.name
    session.flush()
    return report


def reports_for(session: Session,
                run: ScvRun) -> list[ScvReport]:
    return list(session.execute(
        select(ScvReport)
        .where(ScvReport.run_id == run.id)
        .order_by(ScvReport.version.desc())
    ).scalars().all())


def report_header(report: ScvReport,
                  run_key: str = "") -> dict[str, Any]:
    return {
        "report_key": report.report_key,
        "run_key": run_key or (report.run.run_key
                               if getattr(report, "run", None) else ""),
        "source_run_keys": list(report.source_run_keys or []),
        "model_id": report.model_id,
        "model_version": report.model_version,
        "title": report.title,
        "opinion": report.opinion,
        "status": report.status,
        "version": report.version,
        "structure_version": report.structure_version,
        "registry_version": report.registry_version,
        "calculation_version": report.calculation_version,
        "dataset_as_of": report.dataset_as_of,
        "content_hash": report.content_hash,
        "generated_by": report.generated_by_name,
        "generated_at": (report.generated_at.isoformat()
                         if report.generated_at else ""),
        "finalised_by": report.finalised_by_name,
        "finalised_at": (report.finalised_at.isoformat()
                         if report.finalised_at else ""),
        "supersedes_id": report.supersedes_id,
        "bound_to_run": (
            "This report reads the stored results of one run. It does not "
            "follow the latest validation, and re-running the tests does not "
            "change it."),
    }


__all__ = [
    "PAGE", "STORE_VERSION", "Caller", "Immutable", "StoreError",
    "count", "dataset_as_of", "duplicate", "fail", "finalise",
    "finding_body", "get", "history", "report_header", "reports_for",
    "result_body", "results_of", "run_body", "run_header", "save",
    "save_report", "to_result",
]
