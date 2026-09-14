"""Document Intelligence for the seeded demonstration. §24.

The rule this file obeys
------------------------
A demonstration whose dashboard is empty demonstrates nothing, and a
demonstration whose dashboard is populated with invented numbers is worse than
empty. So every figure here comes from `fixtures/ecl_oracle.py` — the same
mapping the chat, the Word file, the PDF, the deck and the workbook read — and
the metric identities are the ones the export contract already carries. The
dashboard therefore cannot disagree with the document beside it.

Metric bindings, and the standing product rule
----------------------------------------------
Uploaded columns are never auto-confirmed on label similarity. Seeded
Playbooks are the one stated exception: the intended mappings are
**pre-confirmed**, because a demonstration that opens on a review queue is
demonstrating the queue rather than the product. Each is confirmed by a named
demonstration user and recorded as such, so a reader can tell a pre-confirmed
demo mapping from an inferred one.

One binding is deliberately left SUGGESTED. §8's review path is part of what
is being shown, and a dashboard where nothing ever needs confirming does not
show it.

Governance
----------
The findings, the decision and the actions are attributed to named
demonstration people through the same `governance` functions a real user goes
through — `require_person` refuses anything else. Nothing here is attributed
to Claude, and nothing here is recorded as a live model act: §13 forbids
model attribution for fixture text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from backend.exports import playbook_contract as contract
from backend.playbook import document as D
from backend.playbook import repository as repo
from backend.playbook.fixtures import ecl_oracle as ecl
from backend.playbook.intelligence import adopt
from backend.playbook.intelligence import binding as bind
from backend.playbook.intelligence import governance as gov
from backend.playbook.intelligence import profile as prof
from backend.playbook.intelligence import readiness as score
from backend.playbook.intelligence import sections as sect

#: Named demonstration people. Every governance act records one of these, so
#: the audit trail reads as a trail rather than as "system".
CHAIR = "demo:chair"
HEAD_OF_CREDIT_RISK = "demo:head-of-credit-risk"
MODELLING_LEAD = "demo:modelling-lead"
VALIDATION_LEAD = "demo:validation-lead"


@dataclass
class MetricSpec:
    """One governed figure the document relies on."""

    metric_id: str
    label: str
    #: What the PREVIOUS pack said. Frozen against the versions, so Since Last
    #: Time has a THEN that a reader can check against the paper.
    then_value: str
    then_display: str
    #: What the data says now. The live binding, after the snapshot.
    now_value: str
    now_display: str
    unit: str
    section: str = ""
    locator: str = ""
    currency: str = ""
    #: True for the one mapping left for the user to confirm.
    suggested: bool = False
    fresh: str = bind.CURRENT


@dataclass
class FindingSpec:
    title: str
    origin: str
    severity: str
    rationale: str = ""
    section: str = ""
    metric_id: str = ""
    threshold: str = ""
    previous_value: str = ""
    current_value: str = ""
    delta: str = ""
    locator: str = ""
    blocking: bool = False
    owner: str = ""
    #: An answer a person stood behind, and who accepted it.
    answer: str = ""
    accepted_by: str = ""


@dataclass
class DecisionSpec:
    question: str
    recommendation: str
    current_position: str = ""
    proposed_position: str = ""
    #: Absent means the decision is still waiting for the committee, which is
    #: the more interesting state to open a demonstration on.
    outcome: str = ""
    rationale: str = ""
    meeting: str = ""
    ready: bool = True
    actions: list[dict] = field(default_factory=list)


@dataclass
class IntelligenceSpec:
    document_type: str
    #: Whether this is put to a committee. Separate from the type, because an
    #: IFRS 9 report presented to the Credit Risk Committee is both — an IFRS 9
    #: report by its required sections, and a committee paper by its decisions
    #: and actions. Collapsing the two would force one of them to be wrong.
    committee: bool = False
    committee_name: str = ""
    reporting_period: str = ""
    owner: str = ""
    meeting_in_days: int | None = None
    #: Which sections a named reviewer has signed off, and who.
    approved_sections: list[tuple[str, str]] = field(default_factory=list)
    reviewing_sections: list[tuple[str, str]] = field(default_factory=list)
    metrics: list[MetricSpec] = field(default_factory=list)
    findings: list[FindingSpec] = field(default_factory=list)
    decisions: list[DecisionSpec] = field(default_factory=list)


# --------------------------------------------------------------------------
# The specs, per seeded thread
# --------------------------------------------------------------------------


def _ifrs9() -> IntelligenceSpec:
    """The committee-oriented example §24 asks for.

    Period, previous pack, metrics then and current, findings including one
    blocking, a committee decision, an action, readiness and Since Last Time —
    all present on first open.
    """
    head = ecl.headline()
    return IntelligenceSpec(
        # An IFRS 9 report, put to a committee. Typed as what it is, so it is
        # measured against the sections an IFRS 9 pack actually needs.
        document_type=prof.IFRS9_REPORT,
        committee=True,
        committee_name="Credit Risk Committee",
        reporting_period=ecl.CURRENT_PERIOD,
        owner="Head of Credit Risk",
        meeting_in_days=11,
        approved_sections=[("2. Scenario design and weighting",
                            "demo:modelling-lead")],
        reviewing_sections=[("3. Staging and significant increase in credit "
                             "risk", "demo:validation-lead")],
        metrics=[
            MetricSpec(
                metric_id="ifrs9.ecl.weighted", label="Probability-weighted ECL",
                then_value=head["weighted_ecl_prior"].rounded,
                then_display=f"SAR {head['weighted_ecl_prior'].rounded}m",
                now_value=head["weighted_ecl_current"].rounded,
                now_display=f"SAR {head['weighted_ecl_current'].rounded}m",
                unit="currency", currency="SAR",
                section="1. Executive summary",
                locator="xlsx://ECL!B6", fresh=bind.NEW_AVAILABLE),
            MetricSpec(
                metric_id="ifrs9.coverage.ratio", label="Coverage ratio",
                then_value=head["coverage_prior"].rounded,
                then_display=f"{head['coverage_prior'].rounded}%",
                now_value=head["coverage_current"].rounded,
                now_display=f"{head['coverage_current'].rounded}%",
                unit="percent", section="1. Executive summary",
                locator="xlsx://Coverage!B4", fresh=bind.NEW_AVAILABLE),
            MetricSpec(
                metric_id="ifrs9.stage2.exposure", label="Stage 2 exposure",
                then_value="72.00", then_display="SAR 72.00m",
                now_value="113.00", now_display="SAR 113.00m",
                unit="currency", currency="SAR",
                section="3. Staging and significant increase in credit risk",
                locator="xlsx://Staging!C3", fresh=bind.NEW_AVAILABLE),
            MetricSpec(
                metric_id="ifrs9.exposure.total", label="Total exposure",
                then_value="1000.00", then_display="SAR 1,000.00m",
                now_value="1050.00", now_display="SAR 1,050.00m",
                unit="currency", currency="SAR",
                section="1. Executive summary",
                locator="xlsx://Exposure!B3"),
            # Left suggested on purpose: §8's review path is part of what the
            # demonstration is showing.
            # A real catalogue match from a column header, which is exactly
            # what rule 3 says must be SHOWN and must NOT be treated as a
            # governed link until somebody confirms it.
            MetricSpec(
                metric_id="", label="30+ DPD exposure rate",
                then_value="", then_display="",
                now_value="0.0314", now_display="3.14%",
                unit="percent", section="4. Book performance",
                locator="xlsx://Staging!F2", suggested=True),
        ],
        findings=[
            FindingSpec(
                title="Post-model adjustments are not documented",
                origin=gov.FROM_RULE, severity=gov.HIGH, blocking=True,
                section="6. Post-model adjustments",
                owner="Head of Credit Risk",
                rationale=("The methodology requires each post-model "
                           "adjustment documented with rationale, quantum and "
                           "expected removal date. The pack states only that "
                           "they are not covered."),
                locator="docx://para/58"),
            FindingSpec(
                title="Stage 2 exposure rose 57 per cent quarter on quarter",
                origin=gov.FROM_CHANGE, severity=gov.HIGH,
                section="3. Staging and significant increase in credit risk",
                metric_id="ifrs9.stage2.exposure",
                previous_value="SAR 72.00m", current_value="SAR 113.00m",
                delta="+SAR 41.00m", locator="xlsx://Staging!C3",
                owner="Head of Credit Risk",
                rationale=("Two obligors in Contracting account for SAR 38.00 "
                           "million of the movement."),
                answer=("Both obligors are on the watchlist and were "
                        "discussed at the February meeting. No change to "
                        "staging policy is proposed."),
                accepted_by=CHAIR),
            FindingSpec(
                title="Model monitoring evidence is referred out of the pack",
                origin=gov.FROM_VALIDATION, severity=gov.MEDIUM,
                section="5. Model monitoring",
                owner="Validation Lead",
                rationale=("The methodology asks for the monitoring evidence "
                           "in the paper; the pack refers it to Model Risk.")),
            FindingSpec(
                title="Coverage ratio may understate the Contracting sector",
                origin=gov.FROM_AI, severity=gov.LOW,
                section="1. Executive summary",
                rationale=("Suggested by analysis of the sector "
                           "concentration export. Not verified.")),
        ],
        decisions=[
            DecisionSpec(
                question=("Do we hold the Stage 2 overlay at SAR 41.00 "
                          "million for Q2 2026?"),
                recommendation=("Hold. The two obligors driving the movement "
                                "are already on the watchlist and the overlay "
                                "covers the exposure in full."),
                current_position="SAR 41.00 million",
                proposed_position="SAR 41.00 million, unchanged",
                ready=True,
                actions=[]),
            DecisionSpec(
                question=("Do we adopt the revised scenario weights for "
                          "Q3 2026?"),
                recommendation=("Adopt 55/15/30. The downturn weight rises "
                                "five points against the current 60/15/25."),
                current_position="60 / 15 / 25",
                proposed_position="55 / 15 / 30",
                outcome=gov.APPROVE,
                rationale=("Committee agreed the downturn weight understates "
                           "the current outlook."),
                meeting="Credit Risk Committee, 14 May 2026",
                actions=[
                    {"title": "Re-run the ECL model on 55/15/30 weights",
                     "description": ("Produce the Q3 2026 figures on the "
                                     "adopted weights and circulate before "
                                     "the next meeting."),
                     "owner": "Modelling Lead", "due_in_days": 21},
                    {"title": "Document the post-model adjustments",
                     "description": ("Rationale, quantum and expected removal "
                                     "date for each adjustment, in the pack."),
                     "owner": "Head of Credit Risk", "due_in_days": -4},
                ]),
        ],
    )


def _application() -> IntelligenceSpec:
    return IntelligenceSpec(
        document_type=prof.MODEL_DEVELOPMENT,
        reporting_period="Q2 2026",
        owner="Modelling Lead",
        approved_sections=[("2. Data and sampling", "demo:modelling-lead")],
        metrics=[
            MetricSpec(metric_id="scorecard.gini", label="Gini coefficient",
                       then_value="0.4152", then_display="0.415",
                       now_value="0.4770", now_display="0.477",
                       unit="statistic", section="5. Model performance",
                       locator="xlsx://Performance!B2",
                       fresh=bind.NEW_AVAILABLE),
            MetricSpec(metric_id="scorecard.ks", label="KS statistic",
                       then_value="0.4880", then_display="0.488",
                       now_value="0.5061", now_display="0.506",
                       unit="statistic", section="5. Model performance",
                       locator="xlsx://Performance!B3",
                       fresh=bind.NEW_AVAILABLE),
            MetricSpec(metric_id="",
                       label="Application cohort bad rate",
                       then_value="", then_display="",
                       now_value="0.0647", now_display="6.47%",
                       unit="percent", section="3. Population and outcome",
                       locator="xlsx://Performance!B4", suggested=True),
        ],
        findings=[
            FindingSpec(
                title="Reject inference method is not stated",
                origin=gov.FROM_VALIDATION, severity=gov.HIGH, blocking=True,
                section="3. Population and outcome",
                owner="Modelling Lead",
                rationale=("The report describes the through-the-door "
                           "population but not how rejects were inferred.")),
            FindingSpec(
                title="Gini improved 6.2 points against the previous build",
                origin=gov.FROM_CHANGE, severity=gov.INFORMATION,
                section="5. Model performance",
                metric_id="scorecard.gini",
                previous_value="0.415", current_value="0.477",
                delta="+0.062", locator="xlsx://Performance!B2"),
        ],
        decisions=[
            DecisionSpec(
                question=("Do we take this scorecard to the Model Risk "
                          "Committee on the current documentation?"),
                recommendation=("Not yet. The reject inference method has to "
                                "be stated first."),
                current_position="Draft, not submitted",
                proposed_position="Submit after the open finding is closed",
                ready=False),
        ],
    )


def _behavioural() -> IntelligenceSpec:
    return IntelligenceSpec(
        document_type=prof.MODEL_VALIDATION,
        reporting_period="Q2 2026",
        owner="Validation Lead",
        reviewing_sections=[("4. Discrimination", "demo:validation-lead")],
        metrics=[
            MetricSpec(metric_id="behavioural.auc", label="AUC",
                       then_value="0.5593", then_display="0.559",
                       now_value="0.5593", now_display="0.559",
                       unit="statistic", section="4. Discrimination",
                       locator="xlsx://Validation!B2"),
            MetricSpec(metric_id="behavioural.brier", label="Brier score",
                       then_value="0.0484", then_display="0.048",
                       now_value="0.0601", now_display="0.060",
                       unit="statistic", section="5. Calibration",
                       locator="xlsx://Validation!B3",
                       fresh=bind.NEW_AVAILABLE),
        ],
        findings=[
            FindingSpec(
                title="Calibration has deteriorated since the last validation",
                origin=gov.FROM_CHANGE, severity=gov.MEDIUM,
                section="5. Calibration", metric_id="behavioural.brier",
                previous_value="0.048", current_value="0.060",
                delta="+0.012", locator="xlsx://Validation!B3",
                owner="Validation Lead"),
        ],
        decisions=[],
    )


#: Keyed by `ThreadSpec.document_family`, exactly as the seeded threads
#: declare it. A family with no entry seeds no dashboard rather than seeding
#: a guessed one.
SPECS = {
    "ifrs9_committee_report": _ifrs9,
    "application_development_report": _application,
    "behavioural_validation_report": _behavioural,
}


def spec_for(document_family: str) -> IntelligenceSpec | None:
    builder = SPECS.get(document_family)
    return builder() if builder else None


# --------------------------------------------------------------------------
# Applying one
# --------------------------------------------------------------------------


def seed(session, workspace_id: int, artifact_id: int, *,
         document_family: str, versions: list, documents: list) -> dict:
    """Populate the dashboard for one seeded workspace.

    `versions` and `documents` are the artifact's versions and their canonical
    documents, in order, so sections and snapshots are adopted exactly as a
    real generation would have adopted them.
    """
    spec = spec_for(document_family)
    if spec is None:
        return {"seeded": False, "reason": "no intelligence spec"}

    _profile(session, workspace_id, spec)
    bindings = _metrics(session, workspace_id, spec)

    # Adopt each version in turn: sections are written, and the governed
    # readings are frozen at what the pack of the day relied on.
    for version_row, doc in zip(versions, documents, strict=True):
        adopt.adopt(session, workspace_id, artifact_id,
                    version_id=version_row.id, version=version_row.version,
                    doc=doc)

    # Only now does the data move on. THEN is what the pack relied on; NOW is
    # what the workbook says today — which is what makes Since Last Time show
    # something on first open rather than an empty table.
    _advance(session, bindings, spec)
    _sections(session, artifact_id, spec)
    findings = _findings(session, workspace_id, spec)
    decisions, actions = _decisions(session, workspace_id, spec)
    result = score.compute(session, workspace_id)

    return {
        "seeded": True,
        "metrics": len(bindings),
        "findings": len(findings),
        "decisions": len(decisions),
        "actions": len(actions),
        "completion_pct": result.completion_pct,
        "readiness_pct": result.readiness_pct,
        "approval_status": result.approval_status,
    }


def _profile(session, workspace_id: int, spec: IntelligenceSpec) -> None:
    from backend.playbook.intelligence import service as intel

    row = intel.ensure_profile(session, workspace_id)
    row.document_type = spec.document_type
    row.committee_report = (spec.committee
                            or spec.document_type in prof.COMMITTEE_TYPES)
    row.committee_name = spec.committee_name
    row.reporting_period = spec.reporting_period
    row.owner = spec.owner
    row.classified_by = "user"
    row.classification_confidence = prof.HIGH
    row.requirements = prof.requirements_for(spec.document_type).as_dict()
    if spec.meeting_in_days is not None:
        row.meeting_date = date.today() + timedelta(days=spec.meeting_in_days)
    session.flush()


def _metrics(session, workspace_id: int,
             spec: IntelligenceSpec) -> list:
    """Bindings at the PREVIOUS pack's readings, so a snapshot has a THEN.

    Pre-confirmed, per the standing rule for seeded Playbooks — except the one
    left suggested so the review path is visible.
    """
    governed = [m for m in spec.metrics if not m.suggested]
    rows = bind.apply(session, workspace_id, bind.from_export([
        contract.Metric(metric_id=m.metric_id, label=m.label,
                        value=m.then_value or m.now_value,
                        display_value=m.then_display or m.now_display,
                        unit=m.unit, currency=m.currency)
        for m in governed]))
    for row, metric in zip(rows, governed, strict=True):
        row.section_key = sect.key_for(metric.section, 0) if metric.section \
            else ""
        row.source_locator = metric.locator
        row.confirmed_by_user = True
        row.confirmed_by = CHAIR
        row.confirmed_at = datetime.now(UTC)

    for metric in (m for m in spec.metrics if m.suggested):
        [row] = bind.apply(session, workspace_id, bind.from_labels(
            [(metric.label, metric.now_display, metric.now_value, "B2")],
            locator=metric.locator))
        # The catalogue's own suggestion is left exactly as it made it. Writing
        # our intended id over it would turn a suggestion into an assertion,
        # which is the whole thing rule 3 forbids.
        row.currency = metric.currency
        row.section_key = (sect.key_for(metric.section, 0)
                           if metric.section else "")
        rows.append(row)
    session.flush()
    return rows


def _advance(session, rows: list, spec: IntelligenceSpec) -> None:
    """Move the governed bindings on to the current readings."""
    by_id = {m.metric_id: m for m in spec.metrics if not m.suggested}
    for row in rows:
        metric = by_id.get(row.metric_id)
        if metric is None:
            continue
        row.value_in_document = metric.now_value
        row.raw_value = metric.now_value
        row.display_value = metric.now_display
        row.freshness = metric.fresh
    session.flush()


def _sections(session, artifact_id: int, spec: IntelligenceSpec) -> None:
    """Put real review state on the sections a reviewer actually looked at."""
    rows = {r.heading: r for r in sect.rows_for(session, artifact_id)}
    for heading, reviewer in spec.reviewing_sections:
        row = rows.get(heading)
        if row is None:
            continue
        sect.assign_reviewer(session, row, reviewer=reviewer, actor=CHAIR)
        sect.transition(session, row, to=sect.READY_FOR_REVIEW, actor=CHAIR,
                        reason="sent for review")
    for heading, reviewer in spec.approved_sections:
        row = rows.get(heading)
        if row is None:
            continue
        sect.assign_reviewer(session, row, reviewer=reviewer, actor=CHAIR)
        sect.transition(session, row, to=sect.READY_FOR_REVIEW,
                        actor=reviewer, reason="sent for review")
        sect.transition(session, row, to=sect.APPROVED, actor=reviewer,
                        reason="reviewed and agreed")
    session.flush()


def _findings(session, workspace_id: int, spec: IntelligenceSpec) -> list:
    rows = []
    for item in spec.findings:
        row = gov.raise_finding(
            session, workspace_id, title=item.title, origin=item.origin,
            severity=item.severity, blocking=item.blocking,
            actor=HEAD_OF_CREDIT_RISK if item.origin == gov.FROM_HUMAN else "",
            rationale=item.rationale, metric_id=item.metric_id,
            threshold=item.threshold, previous_value=item.previous_value,
            current_value=item.current_value, delta=item.delta,
            source_locator=item.locator,
            section_key=sect.key_for(item.section, 0) if item.section else "")
        if item.owner:
            gov.assign_finding(session, row, owner=item.owner, actor=CHAIR)
        if item.answer and item.accepted_by:
            gov.move_finding(session, row, to=gov.ANSWERED,
                             actor=HEAD_OF_CREDIT_RISK, answer=item.answer)
            gov.move_finding(session, row, to=gov.ACCEPTED,
                             actor=item.accepted_by,
                             reason="accepted at the committee")
        rows.append(row)
    return rows


def _decisions(session, workspace_id: int,
               spec: IntelligenceSpec) -> tuple[list, list]:
    decisions, actions = [], []
    for item in spec.decisions:
        row = gov.propose_decision(
            session, workspace_id, question=item.question,
            recommendation=item.recommendation, actor=HEAD_OF_CREDIT_RISK,
            current_position=item.current_position,
            proposed_position=item.proposed_position,
            reporting_period=spec.reporting_period)
        if item.ready or item.outcome:
            gov.move_decision(session, row, to=gov.READY_FOR_DECISION,
                              actor=HEAD_OF_CREDIT_RISK,
                              reason="tabled for the meeting")
        if item.outcome:
            gov.record(session, row, outcome=item.outcome, actor=CHAIR,
                       rationale=item.rationale, meeting=item.meeting)
            gov.actions_from_decision(
                session, row, actor=CHAIR,
                actions=[{
                    "title": a["title"], "description": a["description"],
                    "owner": a["owner"],
                    "due_date": date.today() + timedelta(days=a["due_in_days"]),
                } for a in item.actions])
            actions.extend(
                a for a in _actions_of(session, workspace_id, row.id))
        decisions.append(row)

    # One action in progress, so the demonstration shows a life rather than a
    # list of things nobody has started.
    for action in actions:
        if action.due_date and action.due_date >= date.today():
            gov.move_action(session, action, to=gov.IN_PROGRESS,
                            actor=MODELLING_LEAD,
                            note="model re-run scheduled")
            gov.update_action(session, action, actor=MODELLING_LEAD,
                              note="Weights loaded; first run starts Monday.")
            break
    return decisions, actions


def _actions_of(session, workspace_id: int, decision_id: int) -> list:
    from backend.models.playbook import PlaybookAction

    return (session.query(PlaybookAction)
            .filter(PlaybookAction.workspace_id == workspace_id,
                    PlaybookAction.decision_id == decision_id).all())


def documents_of(session, artifact_id: int) -> tuple[list, list]:
    """The artifact's versions and their canonical documents, in order."""
    versions = repo.versions(session, artifact_id)
    return versions, [D.Document.from_dict(v.content or {}) for v in versions]
