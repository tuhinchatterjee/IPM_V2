"""The Brain Center service. §13-§26.

Where the pure modules in `backend/brain/` meet the database. Everything
that decides anything lives in those modules and is tested without a
session; this file moves rows and calls them.

Two rules shape it and are worth stating before the code.

**Quarantine is not a flag.** An imported package's teaching cases are never
in the retrieval path. There is no `if candidate.active` in the retrieval
code, because the candidate's cases are simply not in `teaching_cases` until
an installation row reaches ACTIVE and the promotion writes them. A bug in
this file cannot make a quarantined Brain answer a question.

**Nothing here activates on its own.** Every state change that could alter a
live answer takes a named person, and refuses without one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.brain import bundle as bundle_mod
from backend.brain import compatibility as compat
from backend.brain import conflicts as conflicts_mod
from backend.brain import ledger as ledger_mod
from backend.brain import liftlab, pack, quarantine, security
from backend.models.platform import (
    BrainConflict,
    BrainImport,
    BrainInstallation,
    BrainLedgerEntry,
    BrainPackage,
    BrainSigner,
    TeachingCase,
)

logger = logging.getLogger(__name__)


class BrainCenterError(Exception):
    """An action the Brain Center refused, and why."""


#: Where packages land. Outside the source tree on purpose: a package that
#: unpacked into `backend/` would become an import path by accident.
STORAGE_ROOT = Path("var/brain")

#: §26. A key nobody has vouched for.
TRUST_UNKNOWN = "UNKNOWN"
TRUST_LOW = "LOW"
TRUST_HIGH = "HIGH"
TRUST_REVOKED = "REVOKED"

#: Directions a package row can have.
EXPORT = "EXPORT"
IMPORT = "IMPORT"


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _jsonable(value: Any) -> Any:
    """A dataclass, tuple or plain value as something JSONB will take."""
    if is_dataclass(value) and not isinstance(value, type):
        return json.loads(json.dumps(asdict(value), default=str))
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


# ==================================================== §13/§14 the ledger


def record_learning(session: Session, entry: ledger_mod.Entry, *,
                    tenant: str = "") -> BrainLedgerEntry:
    """Write one ledger entry. There is no update path, by design.

    An entry found to be wrong is corrected with `supersede_learning`, which
    writes a second row pointing at the first. That costs one row and keeps
    "what did we believe in March?" answerable, which an UPDATE would
    destroy.
    """
    problems = ledger_mod.validate(entry)
    if problems:
        raise BrainCenterError(
            "this learning entry may not be recorded: " + "; ".join(problems))
    row = BrainLedgerEntry(
        entry_id=entry.entry_id,
        schema_version=entry.schema_version,
        source=entry.source,
        tenant=tenant or entry.tenant,
        user_id=entry.user_id,
        object_kind=entry.object_kind,
        object_id=entry.object_id,
        related_ids=dict(entry.related_ids),
        summary=entry.summary,
        body=_jsonable(entry.body),
        build_sha=entry.build_sha,
        intelligence_release_id=entry.intelligence_release_id,
        teaching_release_id=entry.teaching_release_id,
        ontology_version=entry.ontology_version,
        classification=entry.classification,
        portability=entry.portability,
        portability_blockers=list(entry.portability_blockers),
        redaction_status=entry.redaction_status,
        review_status=entry.review_status,
        reviewer=entry.reviewer,
        review_note=entry.review_note,
        candidate_components=list(entry.candidate_components),
        candidate_case_id=entry.candidate_case_id,
        candidate_policy_id=entry.candidate_policy_id,
        candidate_method_id=entry.candidate_method_id,
        candidate_ontology_change=entry.candidate_ontology_change,
        released_in=entry.released_in,
        superseded_by=entry.superseded_by,
        fingerprint=entry.fingerprint,
    )
    session.add(row)
    session.flush()
    return row


def supersede_learning(session: Session, entry_id: str,
                       replacement: ledger_mod.Entry, *, why: str,
                       tenant: str = "") -> BrainLedgerEntry:
    """Correct an entry by writing a new one that points at it."""
    if not why.strip():
        raise BrainCenterError(
            "a supersession with no reason cannot be reviewed later")
    original = session.execute(
        select(BrainLedgerEntry).where(
            BrainLedgerEntry.entry_id == entry_id)).scalar_one_or_none()
    if original is None:
        raise BrainCenterError(f"no ledger entry {entry_id}")
    written = record_learning(session, replacement, tenant=tenant)
    # The only field a written entry ever changes: the pointer forward. The
    # observation itself, and what we believed about it, stay as recorded.
    original.superseded_by = written.entry_id
    original.review_status = ledger_mod.SUPERSEDED
    original.review_note = why
    session.flush()
    return written


def ledger_census(session: Session, *, tenant: str = "") -> dict[str, Any]:
    """§13's census. Captured, approved and activated, kept apart."""
    rows = session.execute(
        select(BrainLedgerEntry).where(
            BrainLedgerEntry.tenant == tenant)).scalars().all()
    entries = [_entry_from_row(r) for r in rows]
    return ledger_mod.census(entries)


def _entry_from_row(row: BrainLedgerEntry) -> ledger_mod.Entry:
    return ledger_mod.Entry(
        entry_id=row.entry_id, source=row.source,
        schema_version=row.schema_version, tenant=row.tenant,
        user_id=row.user_id, object_kind=row.object_kind,
        object_id=row.object_id, related_ids=dict(row.related_ids or {}),
        summary=row.summary, body=dict(row.body or {}),
        build_sha=row.build_sha,
        intelligence_release_id=row.intelligence_release_id,
        teaching_release_id=row.teaching_release_id,
        ontology_version=row.ontology_version,
        classification=row.classification, portability=row.portability,
        portability_blockers=tuple(row.portability_blockers or ()),
        redaction_status=row.redaction_status,
        review_status=row.review_status, reviewer=row.reviewer,
        review_note=row.review_note,
        candidate_components=tuple(row.candidate_components or ()),
        candidate_case_id=row.candidate_case_id,
        candidate_policy_id=row.candidate_policy_id,
        candidate_method_id=row.candidate_method_id,
        candidate_ontology_change=row.candidate_ontology_change,
        released_in=row.released_in, superseded_by=row.superseded_by,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


# ======================================================== §15 exporting


def _approved_teaching_cases(session: Session) -> list[dict[str, Any]]:
    """Approved teaching cases, latest version of each, as plain rows.

    `body` is the case content. It goes out whole because a case without its
    expected plan teaches nothing, and it goes out only for cases a person
    approved here.
    """
    rows = session.execute(
        select(TeachingCase).where(
            TeachingCase.review_status == "APPROVED")).scalars().all()
    latest: dict[str, TeachingCase] = {}
    for row in rows:
        seen = latest.get(row.case_id)
        if seen is None or row.case_version > seen.case_version:
            latest[row.case_id] = row
    return [{
        "case_id": r.case_id,
        "case_version": r.case_version,
        "title": r.title,
        "family_id": r.family_id,
        "subfamily": r.subfamily,
        "description": r.description,
        "language": r.language,
        "portfolio_scope": r.portfolio_scope,
        "difficulty": r.difficulty,
        "risk_level": r.risk_level,
        "question": r.question,
        "turn_count": r.turn_count,
        "expected_capability": r.expected_capability,
        "expected_conversation_action": r.expected_conversation_action,
        "expected_outcome": r.expected_outcome,
        "grain": r.grain,
        "concepts": list(r.concepts or []),
        "required_datasets": list(r.required_datasets or []),
        "operations": list(r.operations or []),
        "tags": list(r.tags or []),
        "body": r.body,
        "status": r.review_status,
        "authoring_method": r.authoring_method,
        "ontology_version": r.ontology_version,
        "fingerprint": r.fingerprint,
    } for r in sorted(latest.values(), key=lambda r: r.case_id)]


def build_export(session: Session, *, kind: str, manifest: pack.Manifest,
                 actor: str, tenant: str = "",
                 baseline_release_id: str = "",
                 signing_key: bytes | None = None,
                 signing_key_id: str = "",
                 storage_root: Path | None = None) -> BrainPackage:
    """Build and write a package, then record that it exists.

    Every check that runs on import runs inside `pack.write()`, so an export
    this installation would refuse to import is an export it refuses to
    write. The row is created only after the bytes exist.
    """
    if kind not in pack.SUFFIX:
        raise BrainCenterError(
            f"{kind!r} is not a package kind; expected one of "
            f"{', '.join(sorted(pack.SUFFIX))}")

    source = bundle_mod.collect(
        teaching_cases=_approved_teaching_cases(session),
        learning_entries=[
            _entry_from_row(r) for r in session.execute(
                select(BrainLedgerEntry).where(
                    BrainLedgerEntry.tenant == tenant)).scalars().all()],
        evaluations=_evaluation_summary(session),
    )
    manifest.package_kind = kind
    manifest.created_by = manifest.created_by or actor
    manifest.case_counts = {"approved": len(source.teaching_cases)}
    manifest.human_approved_count = len(source.teaching_cases)

    if kind == pack.LEARNING_BUNDLE:
        contents = bundle_mod.learning_bundle(
            source, manifest, baseline_release_id=baseline_release_id)
    elif kind == pack.DEVELOPER_BUNDLE:
        contents = bundle_mod.developer_bundle(source, manifest)
    else:
        contents = bundle_mod.brain_pack(source, manifest)

    root = Path(storage_root or STORAGE_ROOT) / "exports"
    root.mkdir(parents=True, exist_ok=True)
    package_id = _id("pkg")
    target = root / f"{package_id}{pack.SUFFIX[kind]}"
    written = pack.write(target, manifest, contents,
                         signing_key=signing_key,
                         signing_key_id=signing_key_id)

    payload = written.read_bytes()
    row = BrainPackage(
        package_id=package_id,
        direction=EXPORT,
        package_kind=kind,
        brain_id=manifest.brain_id,
        brain_name=manifest.brain_name,
        brain_version=manifest.brain_version,
        manifest=_jsonable(manifest.to_dict()),
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        entry_count=len(contents.files) + len(pack.REQUIRED_FILES),
        signature_state="SIGNED" if signing_key else "UNSIGNED",
        signing_key_id=signing_key_id,
        signer_trust=TRUST_HIGH if signing_key else TRUST_UNKNOWN,
        storage_path=str(written),
        tenant=tenant,
        created_by=actor,
    )
    session.add(row)
    session.flush()
    logger.info("brain export %s (%s) written: %d file(s), %d bytes",
                package_id, kind, len(contents.files), len(payload))
    return row


def _evaluation_summary(session: Session) -> dict[str, Any]:
    """Scores and counts. Never holdout content.

    §58 forbids exposing sealed-holdout gold to Brain import training, and a
    "summary" that carried the failing questions would be the holdout with
    the answers removed — which is most of what makes it valuable to
    somebody training against it.
    """
    total = session.execute(
        select(TeachingCase.case_id).where(
            TeachingCase.review_status == "APPROVED")).scalars().all()
    return {
        "approved_case_count": len(set(total)),
        "dimensions": list(liftlab.DIMENSIONS),
        "note": (
            "Counts and dimension names only. No holdout question, no gold "
            "answer and no failing case text is exported: a receiver that "
            "trained against those would produce a score that flatters "
            "rather than measures."
        ),
    }


# ============================================ §16 import into quarantine


def receive_package(session: Session, payload: bytes, *, filename: str,
                    actor: str, tenant: str = "",
                    trusted_keys: dict[str, bytes] | None = None,
                    storage_root: Path | None = None
                    ) -> tuple[BrainPackage, BrainImport]:
    """Take an uploaded package into quarantine. Never into production.

    Inspection happens before the bytes are trusted: `security.inspect()`
    decides from the archive's own metadata — entry count, declared sizes,
    compression ratios, paths — before anything is read out, so a
    decompression bomb is refused rather than expanded.
    """
    root = Path(storage_root or STORAGE_ROOT) / "quarantine"
    root.mkdir(parents=True, exist_ok=True)
    package_id = _id("pkg")
    suffix = Path(filename).suffix or ".cpbrain"
    target = root / f"{package_id}{suffix}"
    target.write_bytes(payload)

    report = security.inspect(str(target), trusted_keys=trusted_keys)
    opened: pack.OpenedPackage | None = None
    manifest_payload: dict[str, Any] = {}
    # Only a BLOCKING problem is a blocker. A warning belongs in the report
    # a reviewer reads, not in the list that stops an activation: treating
    # the two the same would make every advisory finding indistinguishable
    # from a refusal, and reviewers would stop reading either.
    blockers = [f"{p.kind}: {p.detail}" for p in (report.problems or ())
                if p.blocking]

    if not blockers:
        try:
            opened = pack.read(target, trusted_keys=trusted_keys)
            manifest_payload = _jsonable(opened.manifest.to_dict())
            blockers.extend(str(p) for p in (opened.problems or ()))
        except pack.PackError as exc:
            blockers.append(str(exc))
    signature_state = report.signature_state or "UNSIGNED"

    key_id = (opened.manifest.signing_key_id if opened else "")
    package = BrainPackage(
        package_id=package_id,
        direction=IMPORT,
        package_kind=(opened.manifest.package_kind if opened
                      else suffix.lstrip(".")),
        brain_id=(opened.manifest.brain_id if opened else ""),
        brain_name=(opened.manifest.brain_name if opened else ""),
        brain_version=(opened.manifest.brain_version if opened else ""),
        manifest=manifest_payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        entry_count=report.entries,
        signature_state=signature_state,
        signing_key_id=key_id,
        signer_trust=signer_trust(session, key_id, tenant=tenant),
        storage_path=str(target),
        tenant=tenant,
        created_by=actor,
    )
    session.add(package)

    candidate = quarantine.Candidate(
        package_kind=package.package_kind,
        brain_id=package.brain_id,
        brain_name=package.brain_name,
        brain_version=package.brain_version,
        source_instance_id=(opened.manifest.source_instance_id
                            if opened else ""),
        digest=package.sha256,
        uploaded_by=actor,
        tenant=tenant,
        blockers=blockers,
        inspection=_jsonable(report.to_dict()),
    )
    record = BrainImport(
        import_id=candidate.candidate_id,
        package_id=package_id,
        stage=candidate.stage,
        state="IN_QUARANTINE",
        stage_history=[s.to_dict() for s in candidate.history],
        blockers=blockers,
        security_report=candidate.inspection,
        tenant=tenant,
        uploaded_by=actor,
    )
    session.add(record)
    session.flush()
    logger.info("brain package %s received into quarantine as %s "
                "(%d blocker(s))", package_id, record.import_id,
                len(blockers))
    return package, record


def signer_trust(session: Session, key_id: str, *,
                 tenant: str = "") -> str:
    """§26. What this installation has decided about a signing key.

    UNKNOWN for a key nobody recorded. A package signed by an unknown key
    may still be inspected and evaluated — refusing at upload would stop a
    reviewer examining a package they had every right to look at — and may
    not be activated.
    """
    if not key_id:
        return TRUST_UNKNOWN
    row = session.execute(
        select(BrainSigner).where(
            BrainSigner.tenant == tenant,
            BrainSigner.key_id == key_id)).scalar_one_or_none()
    if row is None:
        return TRUST_UNKNOWN
    return row.trust_level


def _candidate_from_row(record: BrainImport) -> quarantine.Candidate:
    package_kind = ""
    candidate = quarantine.Candidate(
        candidate_id=record.import_id,
        package_kind=package_kind,
        stage=record.stage,
        blockers=list(record.blockers or []),
        inspection=dict(record.security_report or {}),
        compatibility=dict(record.compatibility_report or {}),
        diff=dict(record.component_diff or {}),
        evaluation=dict(record.evaluation or {}),
        impact=dict(record.impact_report or {}),
        approvals=list(record.approvals or []),
        uploaded_by=record.uploaded_by,
        tenant=record.tenant,
    )
    candidate.history = [
        quarantine.Step(stage=s.get("stage", ""), at=s.get("at", ""),
                        passed=bool(s.get("passed", True)),
                        detail=s.get("detail", ""), by=s.get("by", ""))
        for s in (record.stage_history or [])]
    return candidate


def _save_candidate(record: BrainImport,
                    candidate: quarantine.Candidate) -> BrainImport:
    record.stage = candidate.stage
    record.stage_history = [s.to_dict() for s in candidate.history]
    record.blockers = list(candidate.blockers)
    record.security_report = _jsonable(candidate.inspection)
    record.compatibility_report = _jsonable(candidate.compatibility)
    record.component_diff = _jsonable(candidate.diff)
    record.evaluation = _jsonable(candidate.evaluation)
    record.impact_report = _jsonable(candidate.impact)
    record.approvals = _jsonable(candidate.approvals)
    record.state = ("IN_QUARANTINE" if candidate.quarantined
                    else record.state)
    return record


def advance_import(session: Session, import_id: str, stage: str, *,
                   actor: str, passed: bool = True,
                   detail: str = "") -> BrainImport:
    """Move an import one stage through §16's pipeline.

    Refuses a skipped stage. The order is not decorative: compatibility runs
    before evaluation because evaluating components the receiver cannot run
    produces a number that means nothing.
    """
    record = _require_import(session, import_id)
    candidate = _candidate_from_row(record)
    try:
        candidate = quarantine.advance(candidate, stage, passed=passed,
                                       detail=detail, by=actor)
    except quarantine.QuarantineError as exc:
        raise BrainCenterError(str(exc)) from exc
    _save_candidate(record, candidate)
    session.flush()
    return record


def check_compatibility(session: Session, import_id: str) -> dict[str, Any]:
    """§17. What this receiver can and cannot run from this package.

    `declared` comes from the package's own contents rather than from the
    manifest's claims about itself, because a manifest is what the sender
    said and the contents are what they sent.
    """
    record = _require_import(session, import_id)
    package = _require_package(session, record.package_id)
    manifest = pack.Manifest.from_dict(dict(package.manifest or {}))
    declared = _declared_components(package)
    report = compat.check(manifest, compat.Receiver.here(), declared=declared)
    record.compatibility_report = _jsonable(report.to_dict())
    session.flush()
    return record.compatibility_report


def _declared_components(package: BrainPackage) -> dict[str, list[str]]:
    """Component names the package actually carries, read from its files."""
    path = Path(package.storage_path)
    if not package.storage_path or not path.exists():
        return {}
    declared: dict[str, list[str]] = {}
    try:
        opened = pack.read(path)
    except pack.PackError:
        return {}
    for archive_path, text in (opened.files or {}).items():
        kind = archive_path.split("/")[0]
        if kind not in ("methods", "agents", "blueprints", "regulatory"):
            continue
        names: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key in ("method_id", "agent_id", "blueprint_id",
                        "requirement_id"):
                if row.get(key):
                    names.append(str(row[key]))
                    break
        declared.setdefault(kind.rstrip("s"), []).extend(names)
    return declared


def record_conflicts(session: Session, import_id: str,
                     found: list[conflicts_mod.Conflict], *,
                     tenant: str = "") -> list[BrainConflict]:
    """§20. Write detected contradictory learning, unresolved."""
    record = _require_import(session, import_id)
    rows: list[BrainConflict] = []
    for conflict in found:
        payload = conflict.to_dict()
        row = BrainConflict(
            conflict_id=_id("cfl"),
            import_id=record.import_id,
            conflict_class=payload.get("conflict_class", ""),
            severity=payload.get("severity", "MEDIUM"),
            summary=payload.get("summary", ""),
            incoming=_jsonable(payload.get("incoming", {})),
            existing=_jsonable(payload.get("existing", {})),
            recommendation=payload.get("recommendation", ""),
            recommendation_reason=payload.get("recommendation_reason", ""),
            tenant=tenant,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return rows


def resolve_conflict(session: Session, conflict_id: str, *, resolution: str,
                     reason: str, actor: str,
                     split_axis: str = "") -> BrainConflict:
    """§21. Settle one conflict, with a named person and a stated reason.

    There is no NEWER_WINS. Recency is not evidence, and offering it would
    make "the import is more recent" a reason a receiver could give for
    adopting a stranger's threshold.
    """
    row = session.execute(
        select(BrainConflict).where(
            BrainConflict.conflict_id == conflict_id)).scalar_one_or_none()
    if row is None:
        raise BrainCenterError(f"no conflict {conflict_id}")
    if resolution not in conflicts_mod.RESOLUTIONS:
        raise BrainCenterError(
            f"{resolution!r} is not a resolution; expected one of "
            f"{', '.join(sorted(conflicts_mod.RESOLUTIONS))}")
    if not reason.strip():
        raise BrainCenterError(
            "a resolution with no reason cannot be reviewed later, and this "
            "is exactly the decision somebody will want explained")
    if not actor.strip():
        raise BrainCenterError("a resolution needs a named person")
    if resolution == conflicts_mod.SCOPE_SPLIT and not split_axis.strip():
        raise BrainCenterError(
            "a scope split needs the axis it splits on. Without one it is a "
            "deferral wearing a decision's name")
    row.resolution = resolution
    row.resolution_reason = reason.strip()
    row.split_axis = split_axis.strip()
    row.resolved_by = actor
    row.resolved_at = _now()
    session.flush()
    return row


def record_evaluation(session: Session, import_id: str,
                      lift: liftlab.LiftReport, *,
                      compatibility: dict[str, Any] | None = None,
                      conflicts_summary: dict[str, Any] | None = None,
                      diff: dict[str, Any] | None = None) -> BrainImport:
    """§18/§19. Store the measured lift and the impact report."""
    record = _require_import(session, import_id)
    record.evaluation = _jsonable(lift.to_dict())
    record.impact_report = _jsonable(liftlab.impact_report(
        lift,
        compatibility=compatibility if compatibility is not None
        else dict(record.compatibility_report or {}),
        conflicts=conflicts_summary or _conflicts_summary(session, import_id),
        diff=diff if diff is not None else dict(record.component_diff or {}),
    ))
    session.flush()
    return record


def _conflicts_summary(session: Session, import_id: str) -> dict[str, Any]:
    rows = session.execute(
        select(BrainConflict).where(
            BrainConflict.import_id == import_id)).scalars().all()
    unresolved = [r for r in rows if not r.resolution]
    blocking = [r for r in unresolved if r.severity in ("HIGH", "CRITICAL")]
    return {
        "total": len(rows),
        "unresolved": len(unresolved),
        "blocking": len(blocking),
        "classes": sorted({r.conflict_class for r in rows}),
    }


def approve_import(session: Session, import_id: str, *, actor: str,
                   role: str, note: str = "") -> BrainImport:
    """Record one approval. Not an activation."""
    if not actor.strip():
        raise BrainCenterError("an approval needs a named person")
    record = _require_import(session, import_id)
    approvals = list(record.approvals or [])
    approvals.append({"by": actor, "role": role, "note": note,
                      "at": _now().isoformat()})
    record.approvals = approvals
    session.flush()
    return record


# ============================================ §22/§23 install and roll back


def may_activate(session: Session, import_id: str) -> tuple[bool, list[str]]:
    """Whether this import may become the active Brain, and what stops it.

    Every condition is checked here rather than assumed by the caller,
    including the ones that are easy to forget: an unsigned package from an
    untrusted signer, a critical regression the averages hid, and an
    evaluation that never ran.
    """
    record = _require_import(session, import_id)
    package = _require_package(session, record.package_id)
    candidate = _candidate_from_row(record)
    reasons: list[str] = []

    if package.signer_trust != TRUST_HIGH:
        reasons.append(
            f"the signing key is {package.signer_trust.lower()}. §26: a "
            "package from an untrusted signer may be inspected and "
            "evaluated, and may not be activated without high-trust "
            "approval")
    if package.signature_state not in ("SIGNED", "VERIFIED"):
        reasons.append(
            "the package is unsigned, so nothing establishes that it is the "
            "package the sender built")
    summary = _conflicts_summary(session, import_id)
    if summary["blocking"]:
        reasons.append(
            f"{summary['blocking']} high-severity conflict(s) are "
            "unresolved")

    ok, why = quarantine.may_activate(
        candidate, high_trust_approval=package.signer_trust == TRUST_HIGH)
    if not ok:
        reasons.append(why)
    return (not reasons), reasons


def activate_import(session: Session, import_id: str, *, actor: str,
                    release_id: str = "") -> BrainInstallation:
    """§22/§24. Stage, activate, and write the installation record.

    The installation row carries the measured columns rather than a pointer
    to a report, because §24's question — "what was integrated, when, by
    whom, and how much improvement did it produce?" — has to stay
    answerable after the report is gone.
    """
    ok, reasons = may_activate(session, import_id)
    if not ok:
        raise BrainCenterError(
            "this Brain may not be activated: " + "; ".join(reasons))
    record = _require_import(session, import_id)
    package = _require_package(session, record.package_id)
    candidate = _candidate_from_row(record)
    candidate = quarantine.activate(candidate, by=actor)
    _save_candidate(record, candidate)
    record.state = "ACTIVE"
    record.decision = "ACTIVATED"
    record.decided_by = actor
    record.decided_at = _now()

    evaluation = dict(record.evaluation or {})
    installation = BrainInstallation(
        installation_id=_id("inst"),
        import_id=record.import_id,
        package_id=package.package_id,
        brain_name=package.brain_name,
        brain_version=package.brain_version,
        source_instance_id=(package.manifest or {}).get(
            "source_instance_id", ""),
        source_user=(package.manifest or {}).get("created_by", ""),
        installed_by=actor,
        approved_by=list(record.approvals or []),
        components=[c.to_dict() for c in candidate.components],
        conflicts=[r.conflict_id for r in session.execute(
            select(BrainConflict).where(
                BrainConflict.import_id == import_id)).scalars().all()],
        baseline_metrics={d["dimension"]: d["baseline"]
                          for d in evaluation.get("dimensions", [])},
        candidate_metrics={d["dimension"]: d["candidate"]
                           for d in evaluation.get("dimensions", [])},
        dimension_deltas={d["dimension"]: d
                          for d in evaluation.get("dimensions", [])},
        critical_fixes=[d["dimension"] for d in
                        evaluation.get("dimensions", [])
                        if d.get("critical_fixed")],
        critical_regressions=[d["dimension"] for d in
                              evaluation.get("dimensions", [])
                              if d.get("critical_introduced")],
        release_id=release_id,
        state="ACTIVE",
        staged_at=_now(),
        activated_at=_now(),
        tenant=record.tenant,
    )
    session.add(installation)
    session.flush()
    logger.info("brain %s %s activated by %s as installation %s",
                package.brain_name, package.brain_version, actor,
                installation.installation_id)
    return installation


def roll_back(session: Session, installation_id: str, *, actor: str,
              reason: str) -> BrainInstallation:
    """§23. Undo an activation. The record of it stays."""
    if not reason.strip():
        raise BrainCenterError(
            "a rollback with no reason leaves the next person unable to "
            "tell whether the Brain was bad or the timing was")
    row = session.execute(
        select(BrainInstallation).where(
            BrainInstallation.installation_id ==
            installation_id)).scalar_one_or_none()
    if row is None:
        raise BrainCenterError(f"no installation {installation_id}")
    if row.state != "ACTIVE":
        raise BrainCenterError(
            f"installation {installation_id} is {row.state}, not ACTIVE; "
            "there is nothing to roll back")
    row.state = "ROLLED_BACK"
    row.rolled_back_at = _now()
    row.rollback_reason = reason.strip()
    record = session.execute(
        select(BrainImport).where(
            BrainImport.import_id == row.import_id)).scalar_one_or_none()
    if record is not None:
        record.state = "ROLLED_BACK"
        record.decision = "ROLLED_BACK"
        record.decision_reason = reason.strip()
        record.decided_by = actor
        record.decided_at = _now()
    session.flush()
    return row


def delete_import(session: Session, import_id: str, *, actor: str,
                  why: str) -> BrainImport:
    """§23. Delete a candidate that never activated.

    Only before activation. Once a Brain has answered a question, deleting
    the record of what it was would leave those answers unexplainable.
    """
    record = _require_import(session, import_id)
    candidate = _candidate_from_row(record)
    try:
        candidate = quarantine.delete(candidate, by=actor, why=why)
    except quarantine.QuarantineError as exc:
        raise BrainCenterError(str(exc)) from exc
    _save_candidate(record, candidate)
    record.state = "DELETED"
    record.decision = "DELETED"
    record.decision_reason = why
    record.decided_by = actor
    record.decided_at = _now()
    _purge_payload(session, record.package_id)
    session.flush()
    return record


def _purge_payload(session: Session, package_id: str) -> None:
    """Drop the bytes, keep the row. §23."""
    package = session.execute(
        select(BrainPackage).where(
            BrainPackage.package_id == package_id)).scalar_one_or_none()
    if package is None or not package.storage_path:
        return
    path = Path(package.storage_path)
    if path.exists():
        path.unlink()
    package.storage_path = ""
    package.payload_purged_at = _now()


# ================================================ §24/§25 what to display


def installation_history(session: Session, *,
                         tenant: str = "") -> list[dict[str, Any]]:
    """§24's timeline, in the order §24 lists.

    Every row answers the question in §24 by itself: what was integrated,
    when, by whom, and how much improvement it produced. A row that cannot
    say the last part says so rather than showing a blank.
    """
    rows = session.execute(
        select(BrainInstallation).where(
            BrainInstallation.tenant == tenant).order_by(
            BrainInstallation.created_at.desc())).scalars().all()
    history: list[dict[str, Any]] = []
    for row in rows:
        deltas = row.dimension_deltas or {}
        improvement = _improvement_line(row)
        history.append({
            "installation_id": row.installation_id,
            "date": row.activated_at.isoformat() if row.activated_at
            else (row.created_at.isoformat() if row.created_at else ""),
            "brain": f"{row.brain_name} {row.brain_version}".strip(),
            "source_instance": row.source_instance_id,
            "source_user": row.source_user,
            "installed_by": row.installed_by,
            "approved_by": [a.get("by", "") for a in (row.approved_by or [])],
            "components": row.components or [],
            "conflicts": row.conflicts or [],
            "baseline_metrics": row.baseline_metrics or {},
            "candidate_metrics": row.candidate_metrics or {},
            "dimension_deltas": deltas,
            "critical_fixes": row.critical_fixes or [],
            "critical_regressions": row.critical_regressions or [],
            "release_id": row.release_id,
            "state": row.state,
            "activated_at": row.activated_at.isoformat()
            if row.activated_at else "",
            "rolled_back_at": row.rolled_back_at.isoformat()
            if row.rolled_back_at else "",
            "rollback_reason": row.rollback_reason,
            "retired_at": row.retired_at.isoformat() if row.retired_at else "",
            "improvement": improvement,
        })
    return history


def _improvement_line(row: BrainInstallation) -> str:
    """One sentence answering "how much improvement did it produce?"."""
    deltas = row.dimension_deltas or {}
    if not deltas:
        return ("Not measured. This installation has no recorded evaluation, "
                "so no improvement can be claimed for it.")
    points = [d.get("points") for d in deltas.values()
              if isinstance(d, dict) and isinstance(d.get("points"),
                                                    (int, float))]
    if not points:
        return ("Recorded, but with no comparable dimension scores.")
    average = sum(points) / len(points)
    regressions = row.critical_regressions or []
    if regressions:
        return (f"{average:+.1f} pp on average across {len(points)} "
                f"dimension(s), but {len(regressions)} critical "
                "regression(s) were introduced. The average does not settle "
                "this.")
    return (f"{average:+.1f} pp on average across {len(points)} "
            f"dimension(s).")


def _require_import(session: Session, import_id: str) -> BrainImport:
    row = session.execute(
        select(BrainImport).where(
            BrainImport.import_id == import_id)).scalar_one_or_none()
    if row is None:
        raise BrainCenterError(f"no import {import_id}")
    return row


def _require_package(session: Session, package_id: str) -> BrainPackage:
    row = session.execute(
        select(BrainPackage).where(
            BrainPackage.package_id == package_id)).scalar_one_or_none()
    if row is None:
        raise BrainCenterError(f"no package {package_id}")
    return row


# =================================================== §26 trusted signers


def add_signer(session: Session, *, key_id: str, label: str, actor: str,
               reason: str, trust_level: str = TRUST_LOW,
               organization: str = "", key_fingerprint: str = "",
               tenant: str = "") -> BrainSigner:
    """Record a decision about a signing key. §26.

    `reason` is required. Trust that nobody had to justify is trust nobody
    can review, and this is the table an auditor reads first.
    """
    if trust_level not in (TRUST_LOW, TRUST_HIGH, TRUST_REVOKED):
        raise BrainCenterError(
            f"{trust_level!r} is not a trust level; expected LOW, HIGH or "
            "REVOKED")
    if not reason.strip():
        raise BrainCenterError(
            "trusting a signing key needs a stated reason. This is the table "
            "an auditor reads first")
    existing = session.execute(
        select(BrainSigner).where(
            BrainSigner.tenant == tenant,
            BrainSigner.key_id == key_id)).scalar_one_or_none()
    if existing is not None:
        existing.trust_level = trust_level
        existing.label = label or existing.label
        existing.added_by = actor
        existing.added_reason = reason.strip()
        session.flush()
        return existing
    row = BrainSigner(
        key_id=key_id, label=label, organization=organization,
        trust_level=trust_level, key_fingerprint=key_fingerprint,
        added_by=actor, added_reason=reason.strip(), tenant=tenant)
    session.add(row)
    session.flush()
    return row


def revoke_signer(session: Session, key_id: str, *, actor: str, reason: str,
                  tenant: str = "") -> BrainSigner:
    """Withdraw trust. Packages already activated stay activated.

    Revocation is not a rollback: a Brain that has been answering questions
    for three months does not become wrong because its signer did. What
    changes is what may be activated from now on, and the installation
    history keeps the fact that this key was trusted when it was used.
    """
    if not reason.strip():
        raise BrainCenterError("a revocation with no reason cannot be audited")
    row = session.execute(
        select(BrainSigner).where(
            BrainSigner.tenant == tenant,
            BrainSigner.key_id == key_id)).scalar_one_or_none()
    if row is None:
        raise BrainCenterError(f"no signer {key_id}")
    row.trust_level = TRUST_REVOKED
    row.revoked_by = actor
    row.revoked_reason = reason.strip()
    row.revoked_at = _now()
    session.flush()
    return row
