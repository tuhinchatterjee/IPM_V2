"""
The regulatory corpus, as the API sees it. Part G.

One place where a circular becomes a row and a row becomes a circular, so the
governance lives in one file rather than in every route that touches it.

Three rules this layer enforces and does not let a caller past:

  * a document is written once per tenant per hash;
  * a rule reaches APPROVED only through `review`, which needs a named SME and
    an assessment;
  * retrieval reads only what an ACTIVE release admits, and returns nothing at
    all when there is no active release.

The last one is the one that will feel wrong first. A bank uploads two hundred
circulars, sees them extracted, asks a regulatory question and gets nothing —
because nobody has reviewed a rule or activated a release. That is the correct
behaviour, and the message says exactly that rather than pretending the corpus
is empty.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.platform import RegulatoryDocument, RegulatoryRelease
from backend.regulatory import extract as ex
from backend.regulatory import knowledge as kn
from backend.regulatory import release as rl
from backend.regulatory import schema as rs
from backend.regulatory import store as stor

logger = logging.getLogger(__name__)


class RegulatoryServiceError(Exception):
    """Something a caller asked for that must not happen."""


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _to_circular(row: RegulatoryDocument) -> rs.Circular:
    """A stored row as the object the knowledge layer works on."""
    body = dict(row.body or {})
    circular = rs.Circular(
        circular_id=row.circular_id, title=row.title, regulator=row.regulator,
        reference=row.reference,
        issued=_parse_date(row.issued_on),
        effective=_parse_date(row.effective_on),
        expires=_parse_date(row.expires_on),
        jurisdiction=row.jurisdiction, language=row.language,
        file_format=row.file_format, filename=row.filename,
        content_hash=row.content_hash, byte_size=row.byte_size,
        page_count=row.page_count, status=row.status,
        confidentiality=row.confidentiality, tenant=row.tenant,
        supersedes=[str(s) for s in (row.supersedes or [])],
        superseded_by=row.superseded_by, uploaded_by=row.uploaded_by,
        notes=row.notes)
    circular.sections = [
        rs.Section(**{k: v for k, v in s.items()
                      if k in rs.Section.__dataclass_fields__})
        for s in (body.get("sections") or [])]
    circular.rules = [
        rs.Rule(**{k: v for k, v in r.items()
                   if k in rs.Rule.__dataclass_fields__})
        for r in (body.get("rules") or [])]
    return circular


def _write_back(row: RegulatoryDocument, circular: rs.Circular) -> None:
    body = circular.to_dict()
    row.body = body
    row.status = circular.status
    row.superseded_by = circular.superseded_by
    row.expires_on = (circular.expires.isoformat() if circular.expires
                      else "")
    row.rule_count = len(circular.rules)
    row.approved_rule_count = sum(1 for r in circular.rules
                                  if r.status == rs.APPROVED)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def upload(session: Session, payload: bytes, *, filename: str,
           title: str, regulator: str, reference: str,
           effective: str, issued: str = "", expires: str = "",
           jurisdiction: str = "", language: str = "en",
           confidentiality: str = rs.RESTRICTED, tenant: str = "",
           supersedes: list[str] | None = None,
           uploaded_by: str = "", notes: str = "",
           concepts: tuple[str, ...] = ()) -> dict[str, Any]:
    """Store one original, extract it, and record what came out.

    Returns the document. Never raises for a document it could not read: an
    unreadable original is stored, hashed and given a status that says so,
    because the bytes are evidence whether or not an extractor can parse them.
    """
    file_format = rs.format_of(filename)
    if not file_format:
        raise RegulatoryServiceError(
            f"{filename!r} is not a format CreditProbe reads. Supported: "
            + ", ".join(sorted(rs.EXTENSIONS)))

    stored = stor.save(payload, filename=filename, tenant=tenant)
    existing = session.execute(
        select(RegulatoryDocument).where(
            RegulatoryDocument.tenant == tenant,
            RegulatoryDocument.content_hash == stored.content_hash)
    ).scalars().first()
    if existing is not None:
        return {**_to_circular(existing).to_dict(),
                "already_present": True,
                "note": ("These exact bytes are already in the corpus as "
                         f"{existing.reference}. Nothing was written twice.")}

    circular = rs.Circular(
        circular_id=f"reg-{uuid.uuid4().hex[:12]}",
        title=title.strip(), regulator=regulator.strip(),
        reference=reference.strip(),
        issued=_parse_date(issued), effective=_parse_date(effective),
        expires=_parse_date(expires), jurisdiction=jurisdiction.strip(),
        language=language or "en", file_format=file_format,
        filename=stored.filename, content_hash=stored.content_hash,
        byte_size=stored.byte_size, confidentiality=confidentiality,
        tenant=tenant, supersedes=[str(s) for s in (supersedes or [])],
        uploaded_by=uploaded_by, notes=notes)

    problems = rs.validate(circular)
    if problems:
        raise RegulatoryServiceError("; ".join(problems))

    found = ex.extract(payload, file_format, concepts=concepts)
    circular.status = found.status
    circular.page_count = len(found.pages)
    circular.sections = found.sections
    circular.rules = found.rules

    row = RegulatoryDocument(
        circular_id=circular.circular_id, title=circular.title,
        regulator=circular.regulator, reference=circular.reference,
        jurisdiction=circular.jurisdiction, language=circular.language,
        issued_on=circular.issued.isoformat() if circular.issued else "",
        effective_on=(circular.effective.isoformat() if circular.effective
                      else ""),
        expires_on=circular.expires.isoformat() if circular.expires else "",
        file_format=circular.file_format, filename=circular.filename,
        content_hash=circular.content_hash, byte_size=circular.byte_size,
        page_count=circular.page_count, status=circular.status,
        confidentiality=circular.confidentiality, tenant=circular.tenant,
        supersedes=list(circular.supersedes), uploaded_by=circular.uploaded_by,
        notes=circular.notes, body=circular.to_dict(),
        extraction={k: v for k, v in found.to_dict().items()
                    if k not in ("pages", "sections", "rules")},
        rule_count=len(circular.rules), approved_rule_count=0)
    session.add(row)
    session.flush()
    return {**circular.to_dict(), "already_present": False,
            "extraction": row.extraction}


def documents(session: Session, *, tenant: str = "",
              status: str = "") -> list[rs.Circular]:
    """Every circular this tenant may see, newest first."""
    query = select(RegulatoryDocument)
    if tenant:
        query = query.where(RegulatoryDocument.tenant == tenant)
    if status:
        query = query.where(RegulatoryDocument.status == status)
    rows = session.execute(
        query.order_by(RegulatoryDocument.created_at.desc())).scalars().all()
    return [_to_circular(r) for r in rows]


def document(session: Session, circular_id: str) -> RegulatoryDocument:
    row = session.execute(
        select(RegulatoryDocument).where(
            RegulatoryDocument.circular_id == circular_id)).scalars().first()
    if row is None:
        raise RegulatoryServiceError(f"no circular {circular_id!r}")
    return row


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def review_queue(session: Session, *, tenant: str = "",
                 limit: int = 50) -> list[dict[str, Any]]:
    return rl.review_queue(documents(session, tenant=tenant), limit=limit)


def review_rule(session: Session, circular_id: str, rule_id: str, *,
                decision: str, reviewer: str, note: str,
                text: str = "") -> dict[str, Any]:
    """Record one SME verdict, and move the document with it."""
    row = document(session, circular_id)
    circular = _to_circular(row)
    rule = next((r for r in circular.rules if r.rule_id == rule_id), None)
    if rule is None:
        raise RegulatoryServiceError(
            f"no rule {rule_id!r} in {circular.reference}")

    verdict = rl.review(rule, decision=decision, reviewer=reviewer, note=note,
                        text=text)
    outstanding = [r for r in circular.rules
                   if r.status in (rs.CANDIDATE, rs.IN_REVIEW)]
    if circular.status in (rs.EXTRACTED, rs.IN_REVIEW):
        circular.status = rs.IN_REVIEW if outstanding else rs.REVIEWED
    _write_back(row, circular)
    session.flush()
    return {"verdict": verdict.to_dict(), "rule": rule.to_dict(),
            "document_status": circular.status,
            "outstanding": len(outstanding)}


def approve_document(session: Session, circular_id: str, *,
                     approver: str, note: str) -> dict[str, Any]:
    """Admit a reviewed circular to the corpus a release can be built from."""
    if not str(approver).strip():
        raise RegulatoryServiceError("an approval needs a named approver")
    if not str(note).strip():
        raise RegulatoryServiceError(
            "an approval needs a reason: 'approved' with no assessment is "
            "indistinguishable from nobody having looked")
    row = document(session, circular_id)
    circular = _to_circular(row)
    if circular.status != rs.REVIEWED:
        raise RegulatoryServiceError(
            f"{circular.reference} is {circular.status}; only a REVIEWED "
            "circular can be approved, and a circular is REVIEWED when every "
            "candidate rule has an SME verdict")
    circular.status = rs.APPROVED
    circular.notes = f"{circular.notes} Approved by {approver}: {note}".strip()
    _write_back(row, circular)
    row.notes = circular.notes
    session.flush()
    return circular.to_dict()


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------


def _release_row(session: Session, release_id: str) -> RegulatoryRelease:
    row = session.execute(
        select(RegulatoryRelease).where(
            RegulatoryRelease.release_id == release_id)).scalars().first()
    if row is None:
        raise RegulatoryServiceError(f"no release {release_id!r}")
    return row


def _to_release(row: RegulatoryRelease) -> rl.Release:
    return rl.Release(
        release_id=row.release_id, tenant=row.tenant, status=row.status,
        contents={k: list(v) for k, v in (row.contents or {}).items()},
        circular_hashes=dict(row.circular_hashes or {}),
        reviewers=[str(r) for r in (row.reviewers or [])],
        approver=row.approver, created_by=row.created_by,
        created_at=row.created_at, activated_at=row.activated_at,
        replaces=row.replaces, note=row.note, fingerprint=row.fingerprint)


def _save_release(row: RegulatoryRelease, release: rl.Release) -> None:
    row.status = release.status
    row.contents = {k: list(v) for k, v in release.contents.items()}
    row.circular_hashes = dict(release.circular_hashes)
    row.circular_count = release.circular_count
    row.rule_count = release.rule_count
    row.reviewers = sorted(set(release.reviewers))
    row.approver = release.approver
    row.fingerprint = release.fingerprint
    row.replaces = release.replaces
    row.note = release.note
    row.activated_at = release.activated_at


def build_release(session: Session, *, created_by: str, tenant: str = "",
                  note: str = "") -> dict[str, Any]:
    found = rl.build(documents(session, tenant=tenant),
                     release_id=f"rkr-{uuid.uuid4().hex[:10]}",
                     created_by=created_by, tenant=tenant, note=note)
    row = RegulatoryRelease(release_id=found.release_id, tenant=tenant)
    _save_release(row, found)
    row.created_by = created_by
    session.add(row)
    session.flush()
    return found.to_dict()


def active_release(session: Session, *,
                   tenant: str = "") -> rl.Release | None:
    row = session.execute(
        select(RegulatoryRelease).where(
            RegulatoryRelease.tenant == tenant,
            RegulatoryRelease.status == rl.ACTIVE)
        .order_by(RegulatoryRelease.activated_at.desc())).scalars().first()
    return _to_release(row) if row is not None else None


def activate_release(session: Session, release_id: str, *,
                     approver: str) -> dict[str, Any]:
    row = _release_row(session, release_id)
    candidate = _to_release(row)
    current = active_release(session, tenant=row.tenant)
    rl.activate(candidate, approver=approver, current=current)
    _save_release(row, candidate)
    if current is not None and current.release_id != candidate.release_id:
        previous = _release_row(session, current.release_id)
        previous.status = current.status
    session.flush()
    return candidate.to_dict()


def rollback_release(session: Session, *, approver: str, why: str,
                     tenant: str = "") -> dict[str, Any]:
    current = active_release(session, tenant=tenant)
    if current is None:
        raise RegulatoryServiceError("there is no active release to roll back")
    if not current.replaces:
        raise RegulatoryServiceError(
            f"{current.release_id} replaced nothing, so there is no earlier "
            "release to return to")
    previous = _to_release(_release_row(session, current.replaces))
    rl.rollback(current, previous, approver=approver, why=why)
    _save_release(_release_row(session, current.release_id), current)
    _save_release(_release_row(session, previous.release_id), previous)
    session.flush()
    return previous.to_dict()


def releases(session: Session, *, tenant: str = "") -> list[dict[str, Any]]:
    rows = session.execute(
        select(RegulatoryRelease)
        .where(RegulatoryRelease.tenant == tenant)
        .order_by(RegulatoryRelease.created_at.desc())).scalars().all()
    return [_to_release(r).to_dict() for r in rows]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def ask(session: Session, question: str, *, when: date | None = None,
        tenant: str = "", roles: frozenset[str] | None = None,
        kinds: tuple[str, ...] = (), limit: int = 8) -> dict[str, Any]:
    """The rules in force on a date that bear on a question, with citations.

    Returns nothing — and says why — when there is no active Regulatory
    Knowledge Release. A corpus that has been uploaded and extracted but never
    reviewed is not knowledge, and answering from it would be exactly the
    "uncited or unreviewed regulatory claim" §41 lists as blocking.
    """
    from backend.regulatory import assurance as ra

    as_of = when or date.today()
    release = active_release(session, tenant=tenant)
    corpus = kn.apply_supersession(documents(session, tenant=tenant))

    if release is None:
        answer = kn.Answer(
            when=as_of, because=(
                "No Regulatory Knowledge Release is active, so nothing "
                "regulatory can be quoted. Circulars may be uploaded and "
                "extracted; a rule reaches an answer only after a regulatory "
                "SME approves it and a release containing it is activated."))
        record = ra.assess(answer, corpus, when=as_of, release=None)
        return {**answer.to_dict(), "assurance": record.to_dict(),
                "release": None}

    admitted = set(release.contents)
    live = [c for c in corpus if c.circular_id in admitted]
    answer = kn.retrieve(live, question, when=as_of, kinds=kinds, limit=limit,
                         tenant=tenant, roles=roles)
    record = ra.assess(answer, live, when=as_of, release=release,
                       verify_original=stor.verify)
    return {**answer.to_dict(), "assurance": record.to_dict(),
            "release": release.to_dict()}


def corpus_report(session: Session, *, tenant: str = "") -> dict[str, Any]:
    """What the corpus honestly contains. §6's discipline, for Part G."""
    found = documents(session, tenant=tenant)
    by_status: dict[str, int] = {}
    by_confidentiality: dict[str, int] = {}
    rules = {kind: 0 for kind in rs.RULE_KINDS}
    approved = 0
    for circular in found:
        by_status[circular.status] = by_status.get(circular.status, 0) + 1
        by_confidentiality[circular.confidentiality] = \
            by_confidentiality.get(circular.confidentiality, 0) + 1
        for rule in circular.rules:
            rules[rule.kind] = rules.get(rule.kind, 0) + 1
            if rule.status == rs.APPROVED:
                approved += 1
    release = active_release(session, tenant=tenant)
    total_rules = sum(rules.values())
    return {
        "circulars": len(found),
        "by_status": by_status,
        "by_confidentiality": by_confidentiality,
        "candidate_rules": total_rules,
        "rules_by_kind": rules,
        "approved_rules": approved,
        "retrievable_rules": (
            sum(len(v) for v in release.contents.values()) if release else 0),
        "active_release": release.release_id if release else "",
        "extraction": ex.availability(),
        "store": stor.usage(tenant),
        "honest_sentence": (
            f"{len(found)} circular(s) uploaded; {total_rules} candidate "
            f"rule(s) extracted; {approved} approved by a regulatory SME; "
            + (f"{sum(len(v) for v in release.contents.values())} retrievable "
               f"under release {release.release_id}."
               if release else
               "none retrievable — no Regulatory Knowledge Release is "
               "active.")),
        "generated_at": datetime.now().astimezone().isoformat(),
    }


__all__ = ["RegulatoryServiceError", "activate_release", "active_release",
           "approve_document", "ask", "build_release", "corpus_report",
           "document", "documents", "releases", "review_queue", "review_rule",
           "rollback_release", "upload"]
