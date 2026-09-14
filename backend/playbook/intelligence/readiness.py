"""Deterministic completion and readiness, with the working kept. §4, §5, §10, §26.

Two different questions
-----------------------
**Completion** asks whether the document has been WRITTEN: are the sections a
paper of this kind needs present and substantive, is there evidence behind
them, are the tables there, are its figures resolved, has anybody reviewed it.

**Readiness** asks whether it may LEAVE: is the period set, is the evidence
current, is everything that was raised answered, are the decisions framed, are
the actions updated, have the reviewers finished, is there anything blocking
approval.

A document can be 100% written and 0% ready — a complete committee pack with an
unanswered high finding is exactly that — so the two are computed separately
and never averaged into one number.

Every number can be taken apart
-------------------------------
Each component carries its own score, the sentence that explains it, the
blocking reason where there is one, and where to go to fix it. §26 asks "why is
readiness 81%?" to be answerable by clicking, and that is only possible if the
working is stored rather than recomputed from memory. Nothing here asks a
model: a percentage an LLM felt was right is what §4 forbids.

Status is a word, never only a colour
-------------------------------------
GREEN, AMBER and RED are carried as `status` strings alongside the score, so a
reader who cannot distinguish the colours still gets the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.models.playbook import (
    PlaybookAction,
    PlaybookDecision,
    PlaybookDocumentSection,
    PlaybookFinding,
    PlaybookMetricBinding,
    PlaybookReadiness,
    PlaybookReview,
    PlaybookSource,
)
from backend.playbook import document as D
from backend.playbook import repository as repo
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import governance as gov
from backend.playbook.intelligence import profile as prof
from backend.playbook.intelligence import sections as sect
from backend.playbook.intelligence import service as svc

GREEN, AMBER, RED, NOT_APPLICABLE = "green", "amber", "red", "not_applicable"

READY, BLOCKED, PENDING, APPROVED = "ready", "blocked", "pending", "approved"

#: Above this a component is healthy; below the second it is a problem. Stated
#: once so every component reads the same way to a user.
GREEN_AT, AMBER_AT = 90, 60


def _band(score: int) -> str:
    if score >= GREEN_AT:
        return GREEN
    return AMBER if score >= AMBER_AT else RED


@dataclass
class Component:
    """One line of the readiness panel, with everything behind it."""

    name: str
    score: int | None
    explanation: str
    blocking: str = ""
    link: str = ""
    applicable: bool = True

    @property
    def status(self) -> str:
        if not self.applicable or self.score is None:
            return NOT_APPLICABLE
        return _band(self.score)

    def as_dict(self) -> dict:
        return {"name": self.name, "score": self.score,
                "status": self.status, "explanation": self.explanation,
                "blocking": self.blocking, "link": self.link,
                "applicable": self.applicable}


@dataclass
class Result:
    completion_pct: int
    readiness_pct: int
    approval_status: str
    components: list[dict] = field(default_factory=list)
    completion_components: list[dict] = field(default_factory=list)
    blockers: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    statistics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"computed": True, "completion_pct": self.completion_pct,
                "readiness_pct": self.readiness_pct,
                "approval_status": self.approval_status,
                "components": list(self.components),
                "completion_components": list(self.completion_components),
                "blockers": list(self.blockers), "missing": list(self.missing),
                "statistics": dict(self.statistics)}


# --------------------------------------------------------------------------
# Gathering the facts. No model, no estimate.
# --------------------------------------------------------------------------


@dataclass
class Facts:
    """Everything the scorer reads, gathered once."""

    profile: object | None
    document: D.Document | None
    version: int
    section_rows: list
    bindings: list
    findings: list
    decisions: list
    actions: list
    reviews: list
    sources: list
    statistics: dict

    @property
    def requirements(self) -> prof.Requirements:
        if self.profile is None:
            return prof.DEFAULT_REQUIREMENTS
        stored = self.profile.requirements or {}
        if stored.get("sections"):
            return prof.Requirements.from_dict(stored)
        return prof.requirements_for(self.profile.document_type)

    @property
    def committee(self) -> bool:
        return bool(self.profile and self.profile.committee_report)


def gather(session, workspace_id: int) -> Facts:
    artifact = svc._current_artifact(session, workspace_id)
    document, version, statistics, section_rows = None, 0, {}, []
    if artifact is not None:
        versions = repo.versions(session, artifact.id)
        if versions:
            current = versions[-1]
            version = current.version
            document = D.Document.from_dict(current.content or {})
            checked = svc._validations(current)
            statistics = sect.statistics(document, files=checked,
                                         validations=checked)
        section_rows = (session.query(PlaybookDocumentSection)
                        .filter(PlaybookDocumentSection.artifact_id ==
                                artifact.id)
                        .order_by(PlaybookDocumentSection.ordinal).all())

    def rows(model):
        return session.query(model).filter(
            model.workspace_id == workspace_id).all()

    return Facts(
        profile=svc.get_profile(session, workspace_id),
        document=document, version=version, section_rows=section_rows,
        bindings=rows(PlaybookMetricBinding), findings=rows(PlaybookFinding),
        decisions=rows(PlaybookDecision), actions=rows(PlaybookAction),
        reviews=rows(PlaybookReview),
        sources=(session.query(PlaybookSource)
                 .filter(PlaybookSource.workspace_id == workspace_id).all()),
        statistics=statistics)


# --------------------------------------------------------------------------
# Completion — has this been written?
# --------------------------------------------------------------------------


def _present_sections(facts: Facts) -> tuple[list[str], list[str]]:
    """Which required sections the document substantively has, and which not.

    Matched on `document._normalise`, the same tolerant comparison a scoped
    edit uses to find "the executive summary", so "1. Executive summary" and
    "Executive Summary" are the same requirement.
    """
    required = facts.requirements.sections
    if facts.document is None:
        return [], list(required)

    written = {}
    for fact in sect.facts(facts.document):
        written[D._normalise(fact.heading)] = fact.substantive

    have, missing = [], []
    for name in required:
        key = D._normalise(name)
        match = next((k for k in written if k == key), None)
        if match is None:
            match = next((k for k in written if key in k or k in key), None)
        if match is not None and written[match]:
            have.append(name)
        else:
            missing.append(name)
    return have, missing


def completion(facts: Facts) -> tuple[int, list[Component], list[str]]:
    """§10's weighted completion, per document type, with the working."""
    weights = facts.requirements.weights or prof._GENERAL_WEIGHTS
    have, missing = _present_sections(facts)
    required = facts.requirements.sections

    section_score = round(100 * len(have) / len(required)) if required else 100

    with_sources = facts.statistics.get("sections_with_sources", 0)
    total_sections = facts.statistics.get("sections", 0)
    evidence_score = (round(100 * with_sources / total_sections)
                      if total_sections else 0)

    tables = facts.statistics.get("tables", 0)
    table_score = 100 if tables else (100 if not required else 0)

    governed = [b for b in facts.bindings if bind.is_governed(b)]
    metric_score = (round(100 * len(governed) / len(facts.bindings))
                    if facts.bindings else 100)

    open_findings = [f for f in facts.findings if f.status == "open"]
    findings_score = (round(100 * (len(facts.findings) - len(open_findings))
                            / len(facts.findings)) if facts.findings else 100)

    reviewed = [r for r in facts.section_rows if r.reviewed_at is not None]
    review_score = (round(100 * len(reviewed) / len(facts.section_rows))
                    if facts.section_rows else 0)

    # `applicable` matters as much as the score. A component with nothing to
    # measure is NOT 100% — "no findings raised" is vacuously true, and
    # counting it as full marks gave an empty workspace a completion score it
    # had done nothing to earn. Inapplicable components are excluded and the
    # remaining weights are renormalised, so the percentage always means
    # "of what could be measured".
    parts = [
        (prof.REQUIRED_SECTIONS, section_score,
         f"{len(have)} of {len(required)} required sections written",
         "sections", True),
        (prof.EVIDENCE_ATTACHED, evidence_score,
         f"{with_sources} of {total_sections} sections cite evidence"
         if total_sections else "no sections written yet",
         "sources", bool(total_sections)),
        (prof.REQUIRED_TABLES, table_score,
         f"{tables} table(s) present" if facts.document is not None
         else "nothing written yet", "sections", facts.document is not None),
        (prof.METRICS_RESOLVED, metric_score,
         f"{len(governed)} of {len(facts.bindings)} metrics governed"
         if facts.bindings else "no metrics tracked yet", "metrics",
         bool(facts.bindings)),
        (prof.FINDINGS_DISPOSITIONED, findings_score,
         f"{len(facts.findings) - len(open_findings)} of "
         f"{len(facts.findings)} findings dispositioned"
         if facts.findings else "no findings raised", "findings",
         bool(facts.findings)),
        (prof.HUMAN_REVIEW, review_score,
         f"{len(reviewed)} of {len(facts.section_rows)} sections reviewed"
         if facts.section_rows else "no sections to review yet", "sections",
         bool(facts.section_rows)),
    ]

    components, total, applicable_weight = [], 0, 0
    for name, value, explanation, link, applicable in parts:
        weight = weights.get(name, 0)
        if applicable:
            total += value * weight
            applicable_weight += weight
        components.append(Component(
            name=name.replace("_", " ").capitalize(),
            score=value if applicable else None, applicable=applicable,
            explanation=f"{explanation} (weight {weight}%)", link=link))
    overall = round(total / applicable_weight) if applicable_weight else 0
    return overall, components, missing


# --------------------------------------------------------------------------
# Readiness — may this leave?
# --------------------------------------------------------------------------


def readiness(facts: Facts) -> tuple[int, list[Component], list[dict]]:
    """§5's panel, and §13's approval bar, computed from rows."""
    blockers: list[dict] = []
    components: list[Component] = []

    def blocker(reason: str, where: str) -> str:
        blockers.append({"reason": reason, "link": where})
        return reason

    # --- Meeting / period -------------------------------------------------
    period = getattr(facts.profile, "reporting_period", "") if facts.profile \
        else ""
    meeting = getattr(facts.profile, "meeting_date", None) if facts.profile \
        else None
    if facts.committee:
        have = bool(period) + bool(meeting)
        score = round(100 * have / 2)
        missing_bits = [n for n, v in (("reporting period", period),
                                       ("meeting date", meeting)) if not v]
        components.append(Component(
            name="Meeting / period", score=score,
            explanation=("set" if not missing_bits
                         else "missing " + " and ".join(missing_bits)),
            blocking=(blocker("The committee meeting date is not set.",
                              "overview")
                      if not meeting else ""),
            link="overview"))
    else:
        components.append(Component(
            name="Meeting / period", score=100 if period else 0,
            explanation="reporting period set" if period
            else "no reporting period set", link="overview"))

    # --- Source / evidence readiness --------------------------------------
    usable = [s for s in facts.sources if s.status in ("parsed", "partial")]
    stale = [s for s in facts.sources if s.status == "stale"]
    score = round(100 * len(usable) / len(facts.sources)) if facts.sources \
        else 0
    components.append(Component(
        name="Source / evidence readiness", score=score,
        explanation=(f"{len(usable)} of {len(facts.sources)} sources read"
                     + (f"; {len(stale)} need re-reading" if stale else "")
                     if facts.sources else "no sources attached"),
        blocking=(blocker(f"{len(stale)} source(s) were read with an older "
                          "parser and need re-reading.", "sources")
                  if stale else ""),
        link="sources"))

    # --- Sections written --------------------------------------------------
    have, missing = _present_sections(facts)
    required = facts.requirements.sections
    section_score = round(100 * len(have) / len(required)) if required else 100
    components.append(Component(
        name="Sections written", score=section_score,
        explanation=f"{len(have)} of {len(required)} required sections present"
                    + (f"; missing {', '.join(missing[:3])}" if missing
                       else ""),
        blocking=(blocker(f"Required section(s) absent: "
                          f"{', '.join(missing[:3])}.", "sections")
                  if missing and facts.committee else ""),
        link="sections"))

    # --- Metrics reconciled ------------------------------------------------
    # Only governed bindings count. An unconfirmed suggestion lowers this
    # score; it is never silently treated as linked data.
    governed = [b for b in facts.bindings if bind.is_governed(b)]
    suggested = [b for b in facts.bindings
                 if b.binding_method == bind.SUGGESTED
                 and not b.confirmed_by_user]
    metric_score = (round(100 * len(governed) / len(facts.bindings))
                    if facts.bindings else 100)
    components.append(Component(
        name="Metrics reconciled", score=metric_score,
        explanation=(f"{len(governed)} of {len(facts.bindings)} metrics "
                     f"governed"
                     + (f"; {len(suggested)} suggested link(s) await "
                        "confirmation" if suggested else "")
                     if facts.bindings else "no metrics tracked"),
        link="metrics"))

    # --- Commentary reviewed ----------------------------------------------
    reviewed = [r for r in facts.section_rows if r.reviewed_at is not None]
    commentary = (round(100 * len(reviewed) / len(facts.section_rows))
                  if facts.section_rows else 0)
    components.append(Component(
        name="Commentary reviewed", score=commentary,
        explanation=(f"{len(reviewed)} of {len(facts.section_rows)} sections "
                     "reviewed" if facts.section_rows
                     else "no sections to review yet"),
        link="sections"))

    # --- Findings resolved / answered --------------------------------------
    open_findings = gov.unresolved(facts.findings)
    unanswered_blocking = gov.blocking_unresolved(facts.findings)
    findings_score = (round(100 * (len(facts.findings) - len(open_findings))
                            / len(facts.findings)) if facts.findings else 100)
    components.append(Component(
        name="Findings answered" if facts.committee else "Findings resolved",
        score=findings_score,
        explanation=(f"{len(open_findings)} of {len(facts.findings)} still "
                     f"open" if facts.findings else "no findings raised"),
        blocking=(blocker(
            f"{len(unanswered_blocking)} blocking finding(s) unanswered: "
            + ", ".join(f.reference or f.title for f in unanswered_blocking[:3])
            + ".", "findings") if unanswered_blocking else ""),
        link="findings"))

    # --- Decisions framed (committee only) ---------------------------------
    # A decision still owed: anything short of decided, other than withdrawn.
    outstanding = [d for d in facts.decisions
                   if d.status not in (gov.DECIDED, gov.WITHDRAWN)]
    unframed = [d for d in outstanding if not d.recommendation]
    if facts.committee:
        framed = len(facts.decisions) - len(unframed)
        score = (round(100 * framed / len(facts.decisions))
                 if facts.decisions else 0)
        components.append(Component(
            name="Decisions framed", score=score,
            explanation=(f"{framed} of {len(facts.decisions)} decisions carry "
                         "a recommendation" if facts.decisions
                         else "no decisions requested"),
            blocking=(blocker("A committee paper asks for at least one "
                              "decision; none is recorded.", "decisions")
                      if not facts.decisions else
                      blocker(f"{len(unframed)} decision(s) have no "
                              "recommendation.", "decisions")
                      if unframed else ""),
            link="decisions"))

    # --- Actions updated ---------------------------------------------------
    today = datetime.now(UTC).date()
    overdue = gov.overdue(facts.actions, today=today)
    if facts.actions:
        updated = [a for a in facts.actions if a.last_update_at is not None]
        score = round(100 * len(updated) / len(facts.actions))
        components.append(Component(
            name="Actions updated", score=score,
            explanation=(f"{len(updated)} of {len(facts.actions)} actions have "
                         f"an update"
                         + (f"; {len(overdue)} overdue" if overdue else "")),
            blocking=(blocker(f"{len(overdue)} action(s) are overdue.",
                              "actions") if overdue and facts.committee
                      else ""),
            link="actions"))
    else:
        components.append(Component(
            name="Actions updated", score=None, applicable=False,
            explanation="no actions raised", link="actions"))

    # --- Review complete ---------------------------------------------------
    complete = [r for r in facts.reviews if r.status == "complete"]
    if facts.reviews:
        score = round(100 * len(complete) / len(facts.reviews))
        incomplete = len(facts.reviews) - len(complete)
        components.append(Component(
            name="Reviewers complete" if facts.committee
            else "Review complete", score=score,
            explanation=f"{len(complete)} of {len(facts.reviews)} reviewers "
                        "have finished",
            blocking=(blocker(f"{incomplete} reviewer(s) have not finished.",
                              "reviews") if incomplete and facts.committee
                      else ""),
            link="reviews"))
    else:
        components.append(Component(
            name="Reviewers complete" if facts.committee
            else "Review complete", score=0,
            explanation="no reviewer has been asked", link="reviews"))

    scored = [c for c in components if c.applicable and c.score is not None]
    overall = round(sum(c.score for c in scored) / len(scored)) if scored else 0
    return overall, components, blockers


def approval(facts: Facts, blockers: list[dict],
             completion_pct: int) -> tuple[str, Component]:
    """§13's bar. A pack with anything blocking is never "ready".

    Nor is one that is not written yet. "Ready for approval" has to mean there
    is nothing left for anybody to do; a document a third written, with
    nothing yet blocking simply because nobody has looked at it, is not that.
    Completion must reach the same green bar the panel uses everywhere else,
    so the two readings cannot tell a reader opposite things.
    """
    if blockers:
        status = BLOCKED
        explanation = (f"{len(blockers)} item(s) block approval: "
                       + "; ".join(b["reason"] for b in blockers[:2]))
    elif completion_pct < GREEN_AT:
        status = PENDING
        explanation = (f"the document is {completion_pct}% complete; "
                       f"{GREEN_AT}% is the bar for approval")
    elif facts.committee and not facts.decisions:
        status, explanation = PENDING, "no decision has been requested"
    else:
        status, explanation = READY, "nothing is blocking approval"
    component = Component(
        name="Approval", score=None if status != READY else 100,
        applicable=status == READY, explanation=explanation,
        blocking=blockers[0]["reason"] if blockers else "", link="overview")
    return status, component


# --------------------------------------------------------------------------
# The whole thing
# --------------------------------------------------------------------------


def compute(session, workspace_id: int, *, persist: bool = True) -> Result:
    """Score a document, and store the working beside the score."""
    facts = gather(session, workspace_id)
    completion_pct, completion_parts, missing = completion(facts)
    readiness_pct, parts, blockers = readiness(facts)
    status, approval_component = approval(facts, blockers, completion_pct)
    parts.append(approval_component)

    result = Result(
        completion_pct=completion_pct, readiness_pct=readiness_pct,
        approval_status=status,
        components=[c.as_dict() for c in parts],
        completion_components=[c.as_dict() for c in completion_parts],
        blockers=blockers, missing=missing,
        statistics=dict(facts.statistics))

    if persist:
        artifact = svc._current_artifact(session, workspace_id)
        artifact_id = artifact.id if artifact else None
        row = (session.query(PlaybookReadiness)
               .filter(PlaybookReadiness.workspace_id == workspace_id,
                       PlaybookReadiness.artifact_id == artifact_id)
               .one_or_none())
        if row is None:
            row = PlaybookReadiness(workspace_id=workspace_id,
                                    artifact_id=artifact_id)
            session.add(row)
        row.version = facts.version
        row.completion_pct = completion_pct
        row.readiness_pct = readiness_pct
        row.approval_status = status
        row.components = result.components
        row.blockers = blockers
        row.statistics = {**facts.statistics, "missing_sections": missing,
                          "completion_components": result.completion_components}
        row.computed_at = datetime.now(UTC)
        session.flush()
    return result
