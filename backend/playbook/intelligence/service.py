"""The Document Intelligence service boundary. Gate 2.

One place assembles dashboard state, and it is here rather than in a frontend
component — §25. Everything a dashboard shows is computed from rows, with the
reason kept beside the number, so §26's "why is readiness 81%?" is answerable
by reading the payload rather than by re-deriving it.

Nothing in this module calls a provider. Every figure on the dashboard is
deterministic and reproducible; an LLM opinion about how complete a document
is would be exactly the thing §4 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.models.playbook import (
    PlaybookAction,
    PlaybookDecision,
    PlaybookDocumentProfile,
    PlaybookDocumentSection,
    PlaybookFinding,
    PlaybookMetricBinding,
    PlaybookMetricSnapshot,
    PlaybookReadiness,
    PlaybookReview,
    PlaybookWorkspace,
)
from backend.playbook import document as D
from backend.playbook import repository as repo
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import profile as prof
from backend.playbook.intelligence import sections as sect


class NotPermitted(ValueError):
    """A governance act attempted without the human actor it requires."""


class UnknownDocumentType(ValueError):
    """A type that is not in the vocabulary.

    Kept apart from NotPermitted on purpose: "you may not do this" and "that
    is not a thing" are different answers, and a caller that cannot tell them
    apart cannot correct either one.
    """


# --------------------------------------------------------------------------
# The profile
# --------------------------------------------------------------------------


def get_profile(session, workspace_id: int) -> PlaybookDocumentProfile | None:
    return (session.query(PlaybookDocumentProfile)
            .filter(PlaybookDocumentProfile.workspace_id == workspace_id)
            .one_or_none())


def ensure_profile(session, workspace_id: int, *, instruction: str = "",
                   filenames: tuple[str, ...] = (), family: str = "",
                   tenant: str = "") -> PlaybookDocumentProfile:
    """The profile for a workspace, inferring a type the first time only.

    An inference never overwrites what a person set. `classified_by` is the
    guard, and it is checked rather than assumed.
    """
    existing = get_profile(session, workspace_id)
    if existing is not None:
        return existing

    guess = prof.infer(instruction, filenames=filenames, family=family)
    requirements = prof.requirements_for(guess.document_type)
    row = PlaybookDocumentProfile(
        workspace_id=workspace_id, tenant=tenant,
        document_type=guess.document_type, report_family=family,
        committee_report=guess.committee_report,
        classified_by="inferred", classification_confidence=guess.confidence,
        requirements=requirements.as_dict())
    session.add(row)
    session.flush()
    return row


def classify(session, workspace_id: int, *, document_type: str, actor: str,
             committee_report: bool | None = None, committee_name: str = "",
             reporting_period: str = "", meeting_date=None,
             owner: str = "") -> PlaybookDocumentProfile:
    """A person settles what kind of document this is. §2.

    Requirements are re-read from the new type, because completion means
    something different for a validation report than for a committee pack and
    the score must move with the classification.
    """
    if document_type not in prof.DOCUMENT_TYPES:
        raise UnknownDocumentType(
            f"{document_type!r} is not a document type. Expected one of: "
            + ", ".join(prof.DOCUMENT_TYPES))
    if not (actor or "").strip():
        raise NotPermitted(
            "Classifying a document is a person's decision. Nothing changed.")

    row = get_profile(session, workspace_id)
    if row is None:
        row = PlaybookDocumentProfile(workspace_id=workspace_id)
        session.add(row)
    row.document_type = document_type
    row.classified_by = "user"
    row.classification_confidence = prof.HIGH
    row.requirements = prof.requirements_for(document_type).as_dict()
    if committee_report is None:
        row.committee_report = document_type in prof.COMMITTEE_TYPES
    else:
        row.committee_report = bool(committee_report)
    if committee_name:
        row.committee_name = committee_name[:160]
    if reporting_period:
        row.reporting_period = reporting_period[:48]
    if meeting_date is not None:
        row.meeting_date = meeting_date
    if owner:
        row.owner = owner[:160]
    session.flush()
    return row


# --------------------------------------------------------------------------
# The dashboard payload
# --------------------------------------------------------------------------


@dataclass
class Dashboard:
    """Everything the Know the Status view needs, computed from rows."""

    workspace_id: int
    artifact_id: int | None = None
    title: str = ""
    document_type: str = prof.GENERAL
    document_type_label: str = ""
    report_family: str = ""
    committee_report: bool = False
    committee_name: str = ""
    reporting_period: str = ""
    meeting_date: str = ""
    owner: str = ""
    status: str = "drafting"
    version: int = 0
    versions: int = 0
    classified_by: str = "inferred"
    classification_confidence: str = ""
    should_ask_type: bool = False
    statistics: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    sections: list = field(default_factory=list)
    findings: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)
    actions: dict = field(default_factory=dict)
    reviews: dict = field(default_factory=dict)
    readiness: dict = field(default_factory=dict)
    #: Whether there is enough here to be worth showing. §14: a brand-new
    #: empty thread does not get a status badge it cannot fill.
    available: bool = False

    def as_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "artifact_id": self.artifact_id,
            "title": self.title,
            "document_type": self.document_type,
            "document_type_label": self.document_type_label,
            "report_family": self.report_family,
            "committee_report": self.committee_report,
            "committee_name": self.committee_name,
            "reporting_period": self.reporting_period,
            "meeting_date": self.meeting_date,
            "owner": self.owner,
            "status": self.status,
            "version": self.version,
            "versions": self.versions,
            "classified_by": self.classified_by,
            "classification_confidence": self.classification_confidence,
            "should_ask_type": self.should_ask_type,
            "statistics": dict(self.statistics),
            "metrics": dict(self.metrics),
            "sections": list(self.sections),
            "findings": dict(self.findings),
            "decisions": dict(self.decisions),
            "actions": dict(self.actions),
            "reviews": dict(self.reviews),
            "readiness": dict(self.readiness),
            "available": self.available,
        }


def _current_artifact(session, workspace_id: int):
    """The report a workspace is about, or None. Reports before decks."""
    artifacts = repo.artifacts(session, workspace_id)
    reports = [a for a in artifacts if a.kind == "report"]
    return (reports or artifacts or [None])[-1]


def dashboard(session, workspace_id: int) -> Dashboard:
    """Assemble the whole dashboard for a workspace. Reads only; no writes."""
    ws = session.get(PlaybookWorkspace, workspace_id)
    profile = get_profile(session, workspace_id)
    artifact = _current_artifact(session, workspace_id)

    state = Dashboard(workspace_id=workspace_id,
                      title=(ws.title if ws else ""))
    if profile is not None:
        state.document_type = profile.document_type
        state.report_family = profile.report_family
        state.committee_report = profile.committee_report
        state.committee_name = profile.committee_name
        state.reporting_period = profile.reporting_period
        state.meeting_date = (profile.meeting_date.isoformat()
                              if profile.meeting_date else "")
        state.owner = profile.owner
        state.status = profile.status
        state.classified_by = profile.classified_by
        state.classification_confidence = profile.classification_confidence
        state.should_ask_type = (profile.classified_by == "inferred"
                                 and profile.classification_confidence
                                 == prof.LOW)
    state.document_type_label = prof.label(state.document_type)

    if artifact is not None:
        state.artifact_id = artifact.id
        state.title = artifact.title or state.title
        versions = repo.versions(session, artifact.id)
        state.versions = len(versions)
        current = versions[-1] if versions else None
        if current is not None:
            state.version = current.version
            doc = D.Document.from_dict(current.content or {})
            checked = _validations(current)
            state.statistics = sect.statistics(
                doc, files=checked, validations=checked)
        # Section rows exist independently of whether a version could be
        # loaded, and a document whose sections are known but whose latest
        # version is missing still has a status worth showing.
        state.sections = _sections_payload(session, artifact.id)

    bindings = (session.query(PlaybookMetricBinding)
                .filter(PlaybookMetricBinding.workspace_id == workspace_id)
                .all())
    state.metrics = _metrics_payload(bindings)
    state.findings = _findings_payload(session, workspace_id)
    state.decisions = _decisions_payload(session, workspace_id)
    state.actions = _actions_payload(session, workspace_id)
    state.reviews = _reviews_payload(session, workspace_id)
    state.readiness = _stored_readiness(session, workspace_id, state.artifact_id)

    # §14: worth showing once the document has something to say about itself.
    state.available = bool(state.artifact_id or bindings
                           or state.findings.get("total"))
    return state


def _validations(version) -> dict:
    """Per-format validation records stored on a version row."""
    stored = version.validation or {}
    out = {}
    for fmt, payload in stored.items():
        if fmt == "grounding" or not isinstance(payload, dict):
            continue
        out[fmt] = type("V", (), {"checked": payload.get("checked", {}),
                                  "ok": payload.get("ok", True)})()
    return out


def _sections_payload(session, artifact_id: int) -> list[dict]:
    rows = (session.query(PlaybookDocumentSection)
            .filter(PlaybookDocumentSection.artifact_id == artifact_id)
            .order_by(PlaybookDocumentSection.ordinal).all())
    return [{
        "section_key": r.section_key, "heading": r.heading,
        "ordinal": r.ordinal, "status": r.status,
        "word_count": r.word_count, "page_from": r.page_from,
        "page_to": r.page_to, "reviewer": r.reviewer,
        "reviewed": r.reviewed_at is not None,
        "stale_reason": r.stale_reason,
        "last_changed_version": r.last_changed_version,
    } for r in rows]


def _metrics_payload(bindings: list[PlaybookMetricBinding]) -> dict:
    """The inventory, with governed and suggested kept apart. §8's four counts."""
    inventory = [{
        "id": b.id,
        "metric_id": b.metric_id,
        "label": b.label or b.canonical_name or b.metric_id,
        "document_label": b.label,
        "value_in_document": b.value_in_document,
        "display_value": b.display_value,
        "raw_value": b.raw_value,
        "unit": b.unit,
        "reporting_period": b.reporting_period,
        "population": b.population,
        "segment": b.segment,
        "source_locator": b.source_locator,
        "source_module": b.source_module,
        "section_key": b.section_key,
        "method": b.binding_method,
        "method_label": bind.METHOD_LABELS.get(b.binding_method,
                                               b.binding_method),
        "confidence": b.confidence,
        "confirmed": b.confirmed_by_user,
        "confirmed_by": b.confirmed_by,
        # The single predicate everything downstream asks. Carried in the
        # payload so a frontend cannot accidentally treat a suggestion as a
        # link by reading some other field.
        "governed": bind.is_governed(b),
        "freshness": b.freshness,
    } for b in bindings]
    payload = bind.coverage(bindings)
    payload["inventory"] = inventory
    payload["suggested_review"] = [m for m in inventory
                                   if m["method"] == bind.SUGGESTED
                                   and not m["confirmed"]]
    return payload


def _findings_payload(session, workspace_id: int) -> dict:
    rows = (session.query(PlaybookFinding)
            .filter(PlaybookFinding.workspace_id == workspace_id).all())
    open_rows = [r for r in rows if r.status == "open"]
    blocking = [r for r in open_rows if r.blocking]
    return {
        "total": len(rows),
        "open": len(open_rows),
        "blocking": len(blocking),
        "by_severity": {s: sum(1 for r in open_rows if r.severity == s)
                        for s in ("high", "medium", "low", "information")},
        "items": [{
            "id": r.id, "reference": r.reference, "title": r.title,
            "severity": r.severity, "status": r.status,
            "raised_by": r.raised_by, "rationale": r.rationale,
            "metric_id": r.metric_id, "threshold": r.threshold,
            "previous_value": r.previous_value,
            "current_value": r.current_value, "owner": r.owner,
            "answer": r.answer, "answered_by": r.answered_by,
            "blocking": r.blocking, "section_key": r.section_key,
        } for r in rows],
    }


def _decisions_payload(session, workspace_id: int) -> dict:
    rows = (session.query(PlaybookDecision)
            .filter(PlaybookDecision.workspace_id == workspace_id).all())
    return {
        "total": len(rows),
        "outstanding": sum(1 for r in rows if r.status == "outstanding"),
        "items": [{
            "id": r.id, "reference": r.reference, "question": r.question,
            "recommendation": r.recommendation, "options": r.options,
            "current_position": r.current_position,
            "proposed_position": r.proposed_position,
            "effective_date": (r.effective_date.isoformat()
                               if r.effective_date else ""),
            "status": r.status, "outcome": r.outcome,
            "decided_by": r.decided_by,
            "decided_at": r.decided_at.isoformat() if r.decided_at else "",
            "meeting": r.meeting, "rationale": r.rationale,
        } for r in rows],
    }


def _actions_payload(session, workspace_id: int) -> dict:
    from datetime import UTC, datetime

    rows = (session.query(PlaybookAction)
            .filter(PlaybookAction.workspace_id == workspace_id).all())
    today = datetime.now(UTC).date()
    overdue = [r for r in rows if r.due_date and r.due_date < today
               and r.status not in ("complete", "closed")]
    return {
        "total": len(rows),
        "open": sum(1 for r in rows if r.status == "open"),
        "overdue": len(overdue),
        "items": [{
            "id": r.id, "reference": r.reference, "title": r.title,
            "owner": r.owner,
            "due_date": r.due_date.isoformat() if r.due_date else "",
            "status": r.status, "last_update": r.last_update,
            "decision_id": r.decision_id, "finding_id": r.finding_id,
            "external_system": r.external_system,
            "external_ref": r.external_ref,
        } for r in rows],
    }


def _reviews_payload(session, workspace_id: int) -> dict:
    rows = (session.query(PlaybookReview)
            .filter(PlaybookReview.workspace_id == workspace_id).all())
    complete = [r for r in rows if r.status == "complete"]
    return {
        "total": len(rows),
        "complete": len(complete),
        "pct": round(100 * len(complete) / len(rows)) if rows else 0,
        "items": [{
            "id": r.id, "reviewer": r.reviewer, "role": r.role,
            "status": r.status, "section_key": r.section_key,
            "comment": r.comment,
        } for r in rows],
    }


def _stored_readiness(session, workspace_id: int,
                      artifact_id: int | None) -> dict:
    row = (session.query(PlaybookReadiness)
           .filter(PlaybookReadiness.workspace_id == workspace_id,
                   PlaybookReadiness.artifact_id == artifact_id)
           .one_or_none())
    if row is None:
        return {"computed": False, "completion_pct": 0, "readiness_pct": 0,
                "approval_status": "pending", "components": [],
                "blockers": []}
    return {
        "computed": True,
        "completion_pct": row.completion_pct,
        "readiness_pct": row.readiness_pct,
        "approval_status": row.approval_status,
        "components": list(row.components or []),
        "blockers": list(row.blockers or []),
        "computed_at": row.computed_at.isoformat() if row.computed_at else "",
    }


def snapshots_for(session, artifact_id: int, version: int
                  ) -> list[PlaybookMetricSnapshot]:
    return (session.query(PlaybookMetricSnapshot)
            .filter(PlaybookMetricSnapshot.artifact_id == artifact_id,
                    PlaybookMetricSnapshot.version == version).all())
