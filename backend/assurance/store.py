"""
Reading and writing Assurance Records. §180, §208, §210.

Why the store is a separate module from the record
----------------------------------------------------
`record.py` is arithmetic: outcomes, gates, weights and a verdict. It has no
database, which is why its rules can be tested exhaustively in milliseconds
and why nothing about a schema change can quietly alter what a status means.
This module is the other half — putting one of those records somewhere it
survives the process, and getting it back.

The retention rule, and why staleness is not a column
-------------------------------------------------------
    §208: "Assurance Records are immutable historical evidence." /
          "Do not rewrite historical scores."

So a record is written once, with the verdict as computed under the weights,
gates, build, data and releases in force at the time. Recomputing it later
under today's policy would restate history in the guise of reading it.

That leaves the question §208 answers in its second half: a record from three
releases ago is still true, and still describes a runtime nobody is using.
Staleness is therefore not stored — it is a RELATION between a record and a
runtime, computed at read time. The row keeps saying what was true; the
reader is told, separately, that the world has moved. Store it as a column
and you have to write to old rows to keep it accurate, which is exactly the
rewrite §208 forbids.

Two columns do change after insert, and deliberately
------------------------------------------------------
The feedback counts and `superseded_by`. Both record what happened AROUND a
record rather than what it concluded — people disagreed with it; a re-run
exists. Neither touches a check, a dimension or a status. §199's rule that
raw feedback does not alter a validation score is enforced by the fact that
there is no code path from a thumb to any scoring column, which is a stronger
guarantee than a policy.

Without a database
-------------------
Every function degrades to a no-op or an empty list rather than raising.
Assurance is an observability layer: a product that refuses to answer a
question because it could not record how well it answered it has its
priorities backwards.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.assurance import dimensions as dm
from backend.assurance import record as rc

logger = logging.getLogger(__name__)

STORE_VERSION = "1.0.0"

#: The axes a record is pinned to. §208: "a record remains tied to its
#: original build, data, model, Teaching Release, policies". Each one that
#: has moved is a separate sentence in the staleness explanation, because
#: "stale" on its own tells a reader nothing about whether to care.
STALENESS_AXES: tuple[tuple[str, str], ...] = (
    ("build_sha", "the application build has changed"),
    ("intelligence_release_id", "a newer Intelligence Release is in force"),
    ("teaching_release_id", "a newer Teaching Release is in force"),
    ("ontology_version", "the credit-risk ontology has changed"),
    ("routing_policy_version", "the model routing policy has changed"),
)


def new_record_id() -> str:
    return f"ar-{uuid.uuid4().hex[:16]}"


# ============================================================ writing


def _context(record: rc.Record) -> dict[str, Any]:
    """§180's remaining fields, kept together rather than each in a column.

    They are read as a block by the drill-down and never filtered on, so a
    column each would buy nothing and cost a migration every time §180 grows
    a field.
    """
    return {
        "served_models": dict(record.served_models),
        "model_roles": dict(record.model_roles),
        "method_versions": dict(record.method_versions),
        "relationship_versions": dict(record.relationship_versions),
        "prompt_versions": dict(record.prompt_versions),
        "data_versions": dict(record.data_versions),
        "result_fingerprints": list(record.result_fingerprints),
        "retrieved_teaching_case_ids": list(
            record.retrieved_teaching_case_ids),
        "agent_roles": list(record.agent_roles),
        "analysis_run_ids": list(record.analysis_run_ids),
        "app_version": record.app_version,
        "review_state": record.review_state,
        # When the record was SEALED, as opposed to when the row was
        # inserted. The fingerprint is taken over the former, and a row can
        # be written a moment later or, after a retry, a good deal later.
        "sealed_at": record.created_at,
    }


def write(record: rc.Record, *, turn_index: int = 0,
          model_route: str = "", case_family: str = "",
          tokens_in: int = 0, tokens_out: int = 0,
          cost_usd: float = 0.0,
          weights: dm.Weights | None = None) -> str:
    """Persist one sealed record and return its id.

    Returns "" where there is no database. The caller has already answered
    the user by the time this runs; a failure here loses evidence about an
    answer rather than the answer.
    """
    from backend.config import settings

    if not settings.has_database:
        return ""

    policy = weights or dm.Weights()
    sealed = record if record.fingerprint else rc.seal(record)
    verdict = sealed.overall(policy)
    if not sealed.assurance_record_id:
        sealed.assurance_record_id = new_record_id()

    try:
        from backend.db.engine import get_session
        from backend.models.platform import AssuranceRecord

        row = AssuranceRecord(
            assurance_record_id=sealed.assurance_record_id,
            record_version=rc.RECORD_VERSION,
            tenant_id=sealed.tenant_id,
            user_id=sealed.user_id,
            investigation_id=sealed.investigation_id,
            project_id=sealed.project_id,
            message_id=sealed.message_id,
            answer_id=sealed.answer_id,
            trace_id=sealed.trace_id,
            agentic_run_id=sealed.agentic_run_id,
            question=sealed.question,
            answer_type=sealed.answer_type,
            portfolio_scope=sealed.portfolio_scope,
            language=sealed.language or "en",
            turn_index=turn_index,
            build_sha=sealed.build_sha,
            app_version=sealed.app_version,
            intelligence_release_id=sealed.intelligence_release_id,
            teaching_release_id=sealed.teaching_release_id,
            ontology_version=sealed.ontology_version,
            routing_policy_version=sealed.routing_policy_version,
            officer_level=sealed.officer_level,
            model_route=model_route,
            blueprint_id=sealed.blueprint_id,
            case_family=case_family,
            overall_status=verdict["overall_status"],
            operational_assurance=verdict["operational_assurance"],
            coverage_pct=verdict["coverage_pct"],
            reference_match_pct=sealed.reference_match_pct,
            reference_source=sealed.reference_source,
            critical_failure_count=len(sealed.critical_failures),
            warning_count=len(sealed.warnings),
            weights_version=policy.version,
            checks=[c.to_dict() for c in sealed.checks],
            dimension_results={r.dimension: r.to_dict()
                               for r in sealed.by_dimension()},
            objective_coverage=dict(sealed.objective_coverage),
            limitations=list(sealed.limitations),
            context=_context(sealed),
            repair_count=sealed.repair_count,
            clarification_count=sealed.clarification_count,
            duration_ms=sealed.duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            fingerprint=sealed.fingerprint,
            rerun_of=(sealed.user_feedback_summary or {}).get("rerun_of", ""),
        )
        with get_session() as session:
            session.add(row)
            session.commit()
        return sealed.assurance_record_id
    except Exception as e:  # pragma: no cover - the database went away
        logger.warning("Could not store assurance record for answer %s: %s",
                       sealed.answer_id, e)
        return ""


def note_feedback(answer_id: str, *, good: int = 0, bad: int = 0) -> bool:
    """§199. Increment the raw feedback counters on a record.

    The only write to an existing record besides `mark_superseded`, and it
    touches no check, no dimension and no status. A thumb is evidence that
    somebody disagreed; it is not evidence about whether the invariants
    reconciled, and this function has no way to pretend otherwise.
    """
    from backend.config import settings

    if not settings.has_database or not answer_id:
        return False
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AssuranceRecord

        with get_session() as session:
            row = session.execute(
                select(AssuranceRecord)
                .where(AssuranceRecord.answer_id == answer_id)
                .order_by(AssuranceRecord.id.desc())).scalars().first()
            if row is None:
                return False
            row.good_feedback_count += max(0, good)
            row.bad_feedback_count += max(0, bad)
            session.commit()
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("Could not record feedback against %s: %s",
                       answer_id, e)
        return False


def mark_superseded(original_id: str, rerun_id: str) -> bool:
    """§200. Point an original at the re-run that followed it.

    The original keeps its verdict. A re-run that "fixed" a record by
    editing it would destroy the before-and-after that makes a comparison
    worth anything.
    """
    from backend.config import settings

    if not settings.has_database or not (original_id and rerun_id):
        return False
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AssuranceRecord

        with get_session() as session:
            original = session.execute(
                select(AssuranceRecord).where(
                    AssuranceRecord.assurance_record_id == original_id)
            ).scalars().first()
            rerun = session.execute(
                select(AssuranceRecord).where(
                    AssuranceRecord.assurance_record_id == rerun_id)
            ).scalars().first()
            if original is None or rerun is None:
                return False
            original.superseded_by = rerun_id
            rerun.rerun_of = original_id
            session.commit()
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("Could not link rerun %s to %s: %s",
                       rerun_id, original_id, e)
        return False


# ============================================================ staleness


def current_runtime() -> dict[str, str]:
    """The versions in force right now, for the staleness comparison.

    Every lookup is defensive: a missing release file makes a record's
    staleness unknown, and unknown must not read as fresh.
    """
    now: dict[str, str] = {}
    try:
        from backend.build_info import build_info

        now["build_sha"] = build_info().git_sha or ""
    except Exception:  # pragma: no cover
        now["build_sha"] = ""
    try:
        from backend.intelligence_release import release

        now["intelligence_release_id"] = getattr(release(), "release_id", "")
    except Exception:  # pragma: no cover
        now["intelligence_release_id"] = ""
    try:
        from backend.teaching import release as trel

        gate = trel.gate(require_release=False)
        now["teaching_release_id"] = getattr(gate, "release_id", "") or ""
    except Exception:  # pragma: no cover
        now["teaching_release_id"] = ""
    try:
        from backend.semantics import ontology

        now["ontology_version"] = str(getattr(ontology, "VERSION", "") or "")
    except Exception:  # pragma: no cover
        now["ontology_version"] = ""
    return {k: v for k, v in now.items() if v}


def staleness(stored: dict[str, Any],
              runtime: dict[str, str] | None = None) -> list[str]:
    """§208. Which axes have moved since this record was written.

    An axis the runtime cannot report is skipped rather than assumed equal:
    reporting a record as current because the comparison could not be made
    is the failure mode this function exists to avoid. An axis the RECORD
    never captured IS stale, because a blank is not evidence of agreement.
    """
    now = current_runtime() if runtime is None else runtime
    moved: list[str] = []
    for axis, sentence in STALENESS_AXES:
        current = str(now.get(axis) or "").strip()
        if not current:
            continue
        was = str(stored.get(axis) or "").strip()
        if was != current:
            moved.append(sentence if was
                         else f"{sentence} (this record recorded none)")
    return moved


# ============================================================ reading


@dataclass
class StoredRecord:
    """A row, as the review surfaces want it.

    Deliberately not a `rc.Record`: rehydrating one would invite somebody to
    call `overall()` on it and recompute a historical verdict under today's
    weights. The stored verdict is a value here, not a method.
    """

    assurance_record_id: str = ""
    investigation_id: str = ""
    project_id: str = ""
    user_id: int | None = None
    tenant_id: str = ""
    answer_id: str = ""
    message_id: str = ""
    trace_id: str = ""
    question: str = ""
    answer_type: str = ""
    portfolio_scope: str = ""
    language: str = "en"
    turn_index: int = 0
    created_at: str = ""

    overall_status: str = ""
    operational_assurance: float | None = None
    coverage_pct: float = 0.0
    reference_match_pct: float | None = None
    reference_source: str = ""
    critical_failure_count: int = 0
    warning_count: int = 0
    weights_version: str = ""

    build_sha: str = ""
    intelligence_release_id: str = ""
    teaching_release_id: str = ""
    ontology_version: str = ""
    routing_policy_version: str = ""
    officer_level: int = 0
    model_route: str = ""
    blueprint_id: str = ""
    case_family: str = ""

    checks: list[dict[str, Any]] = field(default_factory=list)
    dimension_results: dict[str, Any] = field(default_factory=dict)
    objective_coverage: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    repair_count: int = 0
    clarification_count: int = 0
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    fingerprint: str = ""
    good_feedback_count: int = 0
    bad_feedback_count: int = 0
    superseded_by: str = ""
    rerun_of: str = ""

    #: Computed at read time against the runtime. Never stored.
    stale_reasons: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return bool(self.stale_reasons)

    @property
    def status_now(self) -> str:
        """§212's last line: a stale record does not show as current.

        The stored status is what was true then, and is never overwritten;
        this is what a reader should act on today, which is a different
        question with a different answer.
        """
        return rc.STALE if self.stale else self.overall_status

    @property
    def pinned(self) -> dict[str, str]:
        return {axis: getattr(self, axis, "") for axis, _ in STALENESS_AXES}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "assurance_record_id": self.assurance_record_id,
            "investigation_id": self.investigation_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "answer_id": self.answer_id,
            "message_id": self.message_id,
            "trace_id": self.trace_id,
            "question": self.question,
            "answer_type": self.answer_type,
            "portfolio_scope": self.portfolio_scope,
            "language": self.language,
            "turn_index": self.turn_index,
            "created_at": self.created_at,
            # §184, at every layer that can show a number.
            "overall_status": self.overall_status,
            "status_now": self.status_now,
            "status_means": rc.MEANS.get(self.overall_status, ""),
            "operational_assurance": self.operational_assurance,
            "operational_assurance_label": rc.ASSURANCE_LABEL,
            "coverage_pct": round(self.coverage_pct, 1),
            "reference_match": rc.reference_block(self.reference_match_pct,
                                                  self.reference_source),
            "critical_failures": self.critical_failure_count,
            "warnings": self.warning_count,
            "weights_version": self.weights_version,
            "build_sha": self.build_sha,
            "intelligence_release_id": self.intelligence_release_id,
            "teaching_release_id": self.teaching_release_id,
            "routing_policy_version": self.routing_policy_version,
            "officer_level": self.officer_level,
            "model_route": self.model_route,
            "blueprint_id": self.blueprint_id,
            "case_family": self.case_family,
            "objective_coverage": dict(self.objective_coverage),
            "limitations": list(self.limitations),
            "repair_count": self.repair_count,
            "clarification_count": self.clarification_count,
            "duration_ms": self.duration_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 4),
            "good_feedback_count": self.good_feedback_count,
            "bad_feedback_count": self.bad_feedback_count,
            "superseded_by": self.superseded_by,
            "rerun_of": self.rerun_of,
            "stale": self.stale,
            "stale_reasons": list(self.stale_reasons),
            "fingerprint": self.fingerprint,
        }
        payload.update({
            "served_models": self.context.get("served_models", {}),
            "prompt_versions": self.context.get("prompt_versions", {}),
            "method_versions": self.context.get("method_versions", {}),
            "relationship_versions": self.context.get("relationship_versions",
                                                      {}),
            "result_fingerprints": self.context.get("result_fingerprints", []),
            "retrieved_teaching_case_ids": self.context.get(
                "retrieved_teaching_case_ids", []),
            "agentic_run_id": "",
        })
        return payload

    def dimension_rows(self) -> list[dict[str, Any]]:
        """The six, in §178's order, whatever order the JSON happens to be
        in. A dimension missing from an older record reports unmeasured
        rather than being dropped, so the panel is always six panels."""
        rows: list[dict[str, Any]] = []
        for name in dm.DIMENSIONS:
            stored = self.dimension_results.get(name)
            if isinstance(stored, dict):
                rows.append(dict(stored))
            else:
                rows.append({"dimension": name, "label": dm.LABELS[name],
                             "measured": False, "score": None,
                             "coverage_pct": 0.0, "passed": 0, "warnings": 0,
                             "failures": 0,
                             "note": "This record predates the dimension."})
        return rows


def _row_to_stored(row: Any, runtime: dict[str, str]) -> StoredRecord:
    stored = StoredRecord(
        assurance_record_id=row.assurance_record_id,
        investigation_id=row.investigation_id,
        project_id=row.project_id,
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        answer_id=row.answer_id,
        message_id=row.message_id,
        trace_id=row.trace_id,
        question=row.question,
        answer_type=row.answer_type,
        portfolio_scope=row.portfolio_scope,
        language=row.language,
        turn_index=row.turn_index,
        created_at=row.created_at.isoformat() if row.created_at else "",
        overall_status=row.overall_status,
        operational_assurance=row.operational_assurance,
        coverage_pct=row.coverage_pct,
        reference_match_pct=row.reference_match_pct,
        reference_source=row.reference_source,
        critical_failure_count=row.critical_failure_count,
        warning_count=row.warning_count,
        weights_version=row.weights_version,
        build_sha=row.build_sha,
        intelligence_release_id=row.intelligence_release_id,
        teaching_release_id=row.teaching_release_id,
        ontology_version=row.ontology_version,
        routing_policy_version=row.routing_policy_version,
        officer_level=row.officer_level,
        model_route=row.model_route,
        blueprint_id=row.blueprint_id,
        case_family=row.case_family,
        checks=list(row.checks or []),
        dimension_results=dict(row.dimension_results or {}),
        objective_coverage=dict(row.objective_coverage or {}),
        limitations=list(row.limitations or []),
        context=dict(row.context or {}),
        repair_count=row.repair_count,
        clarification_count=row.clarification_count,
        duration_ms=row.duration_ms,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        cost_usd=row.cost_usd,
        fingerprint=row.fingerprint,
        good_feedback_count=row.good_feedback_count,
        bad_feedback_count=row.bad_feedback_count,
        superseded_by=row.superseded_by,
        rerun_of=row.rerun_of,
    )
    stored.stale_reasons = staleness(stored.pinned, runtime)
    return stored


def get(record_id: str) -> StoredRecord | None:
    from backend.config import settings

    if not settings.has_database or not record_id:
        return None
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AssuranceRecord

        runtime = current_runtime()
        with get_session() as session:
            row = session.execute(
                select(AssuranceRecord).where(
                    AssuranceRecord.assurance_record_id == record_id)
            ).scalars().first()
            return _row_to_stored(row, runtime) if row is not None else None
    except Exception as e:  # pragma: no cover
        logger.warning("Could not read assurance record %s: %s", record_id, e)
        return None


def for_investigation(investigation_id: str) -> list[StoredRecord]:
    """Every turn of one Investigation, oldest first. §190's timeline."""
    from backend.config import settings

    if not settings.has_database or not investigation_id:
        return []
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AssuranceRecord

        runtime = current_runtime()
        with get_session() as session:
            rows = session.execute(
                select(AssuranceRecord)
                .where(AssuranceRecord.investigation_id == investigation_id)
                .order_by(AssuranceRecord.turn_index, AssuranceRecord.id)
            ).scalars().all()
        return [_row_to_stored(r, runtime) for r in rows]
    except Exception as e:  # pragma: no cover
        logger.warning("Could not read the assurance timeline for %s: %s",
                       investigation_id, e)
        return []


def recent(limit: int = 200) -> list[StoredRecord]:
    """The most recent records across the estate, newest first.

    Unfiltered by access on purpose — §207's filtering happens above this,
    against a Viewer, so that one policy decides visibility everywhere
    rather than each query re-implementing it slightly differently.
    """
    from backend.config import settings

    if not settings.has_database:
        return []
    try:
        from sqlalchemy import select

        from backend.db.engine import get_session
        from backend.models.platform import AssuranceRecord

        runtime = current_runtime()
        with get_session() as session:
            rows = session.execute(
                select(AssuranceRecord)
                .order_by(AssuranceRecord.id.desc())
                .limit(max(1, min(int(limit), 1000)))).scalars().all()
        return [_row_to_stored(r, runtime) for r in rows]
    except Exception as e:  # pragma: no cover
        logger.warning("Could not read recent assurance records: %s", e)
        return []


def verify(stored: StoredRecord) -> dict[str, Any]:
    """Recompute the stored fingerprint over the stored checks.

    §182's tamper check, surviving the round trip through the database. A
    mismatch is reported, never repaired: a record that silently heals is
    not evidence of anything.
    """
    expected = rc.fingerprint_of(rc.fingerprint_body(
        answer_id=stored.answer_id,
        investigation_id=stored.investigation_id,
        question=stored.question,
        build_sha=stored.build_sha,
        checks=[(c.get("subcomponent", ""), c.get("outcome", ""))
                for c in stored.checks],
        limitations=list(stored.limitations),
        created_at=str(stored.context.get("sealed_at") or "")))
    return {"intact": expected == stored.fingerprint,
            "expected": expected, "stored": stored.fingerprint,
            "note": ("A mismatch means the stored record no longer matches "
                     "the checks it was sealed over. It is reported rather "
                     "than repaired.")}
