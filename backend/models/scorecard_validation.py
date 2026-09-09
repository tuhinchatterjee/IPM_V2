"""A validation run, kept as evidence rather than as a screen's memory.

Why this exists
---------------
The engine is deterministic: the same model over the same window gives the
same numbers in any process at any hour. That makes "re-run it" and "look it
up" agree, and for a while that was the argument for not storing anything.

It is the wrong argument for a model-risk function, and the reason is not
about arithmetic. Six months after a validation, somebody has to open the run
**a committee saw** — not a run that agrees with it. Those are different
objects the moment the data changes underneath: the parquet lake gains a
month, a limit is revised, a binning specification is re-approved, and the
recomputation is now a defensible number about a different book. A committee
paper that silently follows the latest data is a committee paper nobody can
defend.

So a run is written down, in full, once, and never edited.

What "in full" means here
-------------------------
Not the summary. Every result carries the value AND the population it was
measured over, the limit it was compared against, where that limit came from,
the sentence the runner wrote about it, the chart the screen drew and the
table beneath it. A stored headline with the evidence thrown away is a stored
assertion, and an assertion is exactly what a validation is supposed to
replace.

It also carries the versions — the test registry, the model registry that
holds the thresholds, the calculation kernel, the result-state vocabulary and
the findings engine. A number is only reproducible beside the code version
that produced it, and "the AUC was 0.6547" six months later is a claim about
an engine nobody has pinned.

Immutability, and how a correction happens
------------------------------------------
Result rows are written once. There is no update path in the service and the
API exposes none. A validator who wants today's numbers creates a NEW run;
the earlier one keeps its rows exactly as they were, and the two can be
compared (`backend.scorecard.validation.compare`). That is the whole of the
correction story, and it is deliberate: a schema that permits editing a
historical result is a schema in which the question "what did we see then?"
has no answer.

What this module deliberately does NOT introduce
------------------------------------------------
A second user table, a second audit trail, a second export log, a second
comment table, or a second permission model.

  identity          `users`                       (platform)
  download log      `export_records`              (platform, object-keyed)
  comments          `comments`                    (platform, object-keyed)
  permissions       `backend.api.permissions`     (code, not rows)
  the tests          `backend.scorecard.validation.registry`  (code, not rows)
  the thresholds     `backend.scorecard.validation.models`    (code, not rows)

The tests and the limits stay in code and are referenced here BY VERSION.
Copying them into rows would create a second registry that drifts from the
one the engine reads, and a validation environment with two sets of limits is
worse than one with none.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.models import Base  # registers `users`

# ============================================================== vocabularies
#
# Tuples rather than database enums, matching the Playbook and Planner
# convention: an enum needs a migration to add a value, and these grow.

#: Where a run came from. Stored because "who ran this" and "what ran this"
#: are different questions, and an auditor asks the second one about an
#: automated result.
RUN_SOURCES: tuple[str, ...] = ("UI", "AGENT", "API", "SCHEDULED", "TEST")

#: A run's own lifecycle. A run that failed is kept — a validation that could
#: not complete is a fact about the environment, and deleting it hides it.
RUN_STATUSES: tuple[str, ...] = ("RUNNING", "COMPLETE", "FAILED")

#: Which side of the model was validated. A champion result and a challenger
#: result are not interchangeable and must never share a cache identity.
MODEL_KINDS: tuple[str, ...] = ("CHAMPION", "CHALLENGER")

#: How much of the registry the run covered. Recorded rather than inferred
#: from the result count, because "eleven of eleven" and "eleven of
#: forty-eight" are different claims and the second one has to be legible.
RUN_SCOPES: tuple[str, ...] = ("FULL", "CATEGORY", "TEST")

#: A report's lifecycle. `FINAL` is immutable — a correction is a new version
#: pointing at a new run, never an edit of a signed document.
REPORT_STATUSES: tuple[str, ...] = ("DRAFT", "FINAL", "SUPERSEDED")


class ScvRun(Base):
    """One execution of one or more validation tests, frozen.

    The header carries everything needed to say what was tested and against
    what: which model at which version, which dataset at which as-of, which
    window, which segment, which categories and tests were asked for, and the
    version of every piece of code that produced the answer.
    """

    __tablename__ = "scv_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: The public identifier. Stable, quotable in a report, and independent of
    #: the row id so a run can be referenced before it is committed.
    run_key: Mapped[str] = mapped_column(String(64), nullable=False,
                                         unique=True)

    # ---- what was validated ---------------------------------------------
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False,
                                            default="")
    model_version: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="")
    #: CHAMPION or CHALLENGER. See MODEL_KINDS.
    model_kind: Mapped[str] = mapped_column(String(24), nullable=False,
                                            default="CHAMPION")
    scorecard_type: Mapped[str] = mapped_column(String(32), nullable=False,
                                                default="")
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # ---- against what data ----------------------------------------------
    dataset: Mapped[str] = mapped_column(String(128), nullable=False,
                                         default="")
    reference_dataset: Mapped[str] = mapped_column(String(128),
                                                   nullable=False, default="")
    decisions_dataset: Mapped[str] = mapped_column(String(128),
                                                   nullable=False, default="")
    #: The lake's own as-of for this dataset — the newest partition and its
    #: modification time. Two runs with different values here read different
    #: data whatever else matches, and that is the fact a reader needs first.
    dataset_as_of: Mapped[str] = mapped_column(String(64), nullable=False,
                                               default="")
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False,
                                                 default="")

    # ---- over what window ------------------------------------------------
    #: The periods the caller asked for, empty for the governed default.
    requested_periods: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                    default=list)
    #: The matured window the outcome tests actually used.
    matured_window: Mapped[str] = mapped_column(String(64), nullable=False,
                                                default="")
    #: The newest period in the data, which the stability tests used.
    latest_period: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="")
    #: The population the MODEL was built on, as the registry describes it —
    #: prose, not a period. It lives here because a run has to be able to say
    #: what it was validating against without a reader going back to a
    #: registry that may since have moved.
    development_population: Mapped[str] = mapped_column(
        String(300), nullable=False, default="")
    #: The benchmark period the stability tests compared against. A PERIOD,
    #: taken from the results rather than from the registry: the column is
    #: named for what a reader will filter on.
    reference_period: Mapped[str] = mapped_column(String(32), nullable=False,
                                                  default="")
    segment: Mapped[str] = mapped_column(String(128), nullable=False,
                                         default="")
    segment_field: Mapped[str] = mapped_column(String(128), nullable=False,
                                               default="")

    # ---- maturity, stated rather than implied ---------------------------
    periods_available: Mapped[int] = mapped_column(Integer, nullable=False,
                                                   default=0)
    periods_matured: Mapped[int] = mapped_column(Integer, nullable=False,
                                                 default=0)
    periods_immature: Mapped[int] = mapped_column(Integer, nullable=False,
                                                  default=0)
    performance_window_months: Mapped[int] = mapped_column(Integer,
                                                           nullable=False,
                                                           default=0)

    # ---- what was asked for ---------------------------------------------
    #: FULL, CATEGORY or TEST. See RUN_SCOPES.
    scope: Mapped[str] = mapped_column(String(24), nullable=False,
                                       default="FULL")
    requested_categories: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                       default=list)
    requested_tests: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                  default=list)

    # ---- which code produced it -----------------------------------------
    #
    # Five versions rather than one. They move independently: a new test can
    # arrive without the kernel changing, a limit can be revised without the
    # registry changing, and a reader comparing two runs needs to know WHICH
    # of those happened.
    registry_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                  default="")
    #: The model registry holds the thresholds, so its version IS the
    #: threshold-profile version.
    threshold_profile_version: Mapped[str] = mapped_column(String(24),
                                                           nullable=False,
                                                           default="")
    calculation_version: Mapped[str] = mapped_column(String(24),
                                                     nullable=False,
                                                     default="")
    states_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default="")
    findings_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                  default="")

    # ---- the shape of the answer ----------------------------------------
    returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: How many produced a NUMBER. The distinction between this and `returned`
    #: is the one a validation opinion rests on.
    measured: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tally: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    coverage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    regulatory_coverage: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                      default=dict)
    findings_summary: Mapped[dict] = mapped_column(JSONB, nullable=False,
                                                   default=dict)

    # ---- who, when, how --------------------------------------------------
    initiated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    #: The name as it was at the time. A person who leaves must not turn a
    #: signed validation into one nobody ran.
    initiated_by_name: Mapped[str] = mapped_column(String(160),
                                                   nullable=False, default="")
    initiated_by_role: Mapped[str] = mapped_column(String(32), nullable=False,
                                                   default="")
    #: UI, AGENT, API, SCHEDULED or TEST. See RUN_SOURCES.
    source: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="UI")
    #: When the run came from a question, the question. An auditor reading an
    #: AGENT run needs to know what was asked.
    source_detail: Mapped[str] = mapped_column(Text, nullable=False,
                                               default="")

    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="COMPLETE")
    #: Why it failed, when it did. A failed run kept without its reason is a
    #: gap that looks like a result.
    failure: Mapped[str] = mapped_column(Text, nullable=False, default="")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False,
                                             default=0)

    #: The run this one was duplicated from, when a validator asked for
    #: "re-run using current data". The chain is what makes a comparison
    #: obvious rather than something a reader has to reconstruct.
    duplicated_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("scv_runs.id", ondelete="SET NULL"),
        nullable=True)

    results: Mapped[list[ScvResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
        passive_deletes=True)
    findings: Mapped[list[ScvFinding]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
        passive_deletes=True)

    __table_args__ = (
        Index("ix_scv_runs_model", "model_id", "started_at"),
        Index("ix_scv_runs_status", "status", "started_at"),
        Index("ix_scv_runs_user", "initiated_by_id", "started_at"),
    )


class ScvResult(Base):
    """One test result, exactly as the runner produced it. Written once.

    `value` is nullable and the null is the point. Six of the ten result
    states mean "there is no number here", and the engine refuses to build a
    result that claims one of those states while carrying a value. A column
    defaulting to zero would undo that in storage, and a NOT_MATURED cohort
    would come back out of the database as a zero default rate — which is the
    single most damaging thing this schema could do.
    """

    __tablename__ = "scv_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scv_runs.id", ondelete="CASCADE"),
        nullable=False)

    test_id: Mapped[str] = mapped_column(String(64), nullable=False)
    test_name: Mapped[str] = mapped_column(String(200), nullable=False,
                                           default="")
    category: Mapped[str] = mapped_column(String(48), nullable=False,
                                          default="")

    state: Mapped[str] = mapped_column(String(32), nullable=False)
    state_label: Mapped[str] = mapped_column(String(48), nullable=False,
                                             default="")
    #: True only for PASS, WARNING, FAIL and NO_LIMIT. Stored rather than
    #: derived so a query for "what did this run actually measure?" does not
    #: have to encode the state vocabulary.
    measured: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: DEMO POLICY, STRUCTURAL, or whatever governed it. A threshold with no
    #: provenance becomes a regulatory requirement the third time somebody
    #: reads the table.
    limit_source: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")
    comparison_value: Mapped[float | None] = mapped_column(Float,
                                                           nullable=True)

    #: The runner's own sentence, written to be quoted into a report unedited.
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remedy: Mapped[str] = mapped_column(Text, nullable=False, default="")
    method: Mapped[str] = mapped_column(Text, nullable=False, default="")
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False,
                                              default=list)

    # ---- the population it was measured over -----------------------------
    period: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reference_period: Mapped[str] = mapped_column(String(64), nullable=False,
                                                  default="")
    segment: Mapped[str] = mapped_column(String(128), nullable=False,
                                         default="")
    observations: Mapped[int] = mapped_column(Integer, nullable=False,
                                              default=0)
    matured_observations: Mapped[int] = mapped_column(Integer, nullable=False,
                                                      default=0)
    events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Rows the test dropped — immature, filtered or unusable. Stored because
    #: "24,119 of 54,038" is a different statement from "24,119", and only the
    #: first one lets a reader judge the result.
    excluded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    score_direction: Mapped[str] = mapped_column(String(32), nullable=False,
                                                 default="")
    calculation_version: Mapped[str] = mapped_column(String(24),
                                                     nullable=False,
                                                     default="")

    #: What the screen drew, kept so a historical run renders identically
    #: rather than being re-derived from data that has moved.
    chart: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: The test-level table, including variable-level diagnostics for the
    #: VAR-* and STAB-* tests.
    result_table: Mapped[list] = mapped_column(JSONB, nullable=False,
                                               default=list)
    lineage: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    run: Mapped[ScvRun] = relationship(
        back_populates="results")

    __table_args__ = (
        # One result per test per segment per run. A second row for the same
        # pair would be two answers to one question with nothing saying which
        # is the run's.
        UniqueConstraint("run_id", "test_id", "segment",
                         name="uq_scv_result_run_test_segment"),
        Index("ix_scv_results_test", "test_id", "state"),
    )


class ScvFinding(Base):
    """A finding as it stood when the run produced it.

    Kept beside the results rather than recomputed, because a finding is a
    reading of a specific set of results and the findings engine is versioned.
    Recomputing an old run's findings with a new engine produces a statement
    the validator never made.
    """

    __tablename__ = "scv_findings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scv_runs.id", ondelete="CASCADE"),
        nullable=False)

    finding_key: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(24), nullable=False,
                                          default="")
    #: Ascending rank, so a list screen can order without knowing the words.
    severity_rank: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0)
    category: Mapped[str] = mapped_column(String(48), nullable=False,
                                          default="")
    #: True when this finding was severe enough to change a decision.
    burning: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                          default=False)
    #: The cross-test rule that produced it, empty for a single-test finding.
    pattern: Mapped[str] = mapped_column(String(64), nullable=False,
                                         default="")

    what: Mapped[str] = mapped_column(Text, nullable=False, default="")
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False,
                                                default="")
    #: The remediation the engine drafted. A draft, and never an instruction:
    #: what to do about a model is a person's decision.
    remediation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: How to check it independently. The engine refuses to build a finding
    #: without one, and so does this table by keeping the column beside it.
    verify_by: Mapped[str] = mapped_column(Text, nullable=False, default="")

    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    cbuae: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False,
                                            default="")
    period: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    segment: Mapped[str] = mapped_column(String(128), nullable=False,
                                         default="")

    run: Mapped[ScvRun] = relationship(
        back_populates="findings")

    __table_args__ = (
        UniqueConstraint("run_id", "finding_key", "segment",
                         name="uq_scv_finding_run_key_segment"),
        Index("ix_scv_findings_severity", "severity", "burning"),
    )


class ScvReport(Base):
    """A report, bound to the run it was built from.

    The binding is a foreign key, not a timestamp and not a convention. A
    report opened next year assembles from THAT run's stored results, so a
    finalised document cannot silently follow the latest validation — which is
    the specific failure this table exists to prevent.

    The DOCX is not stored. It is regenerated from the persisted results and
    the persisted structure, and `content_hash` proves the regeneration
    matches: same run, same structure version, same bytes. Storing the file as
    well would create a second source of truth that can disagree with the
    first.
    """

    __tablename__ = "scv_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    report_key: Mapped[str] = mapped_column(String(128), nullable=False,
                                            unique=True)
    #: The run this report is OF. Immutable once set.
    run_id: Mapped[int] = mapped_column(
        ForeignKey("scv_runs.id", ondelete="RESTRICT"),
        nullable=False)
    #: Any further runs the report draws on — a challenger comparison, say.
    #: Run keys rather than ids, so the list survives being read out of the
    #: database into a document.
    source_run_keys: Mapped[list] = mapped_column(JSONB, nullable=False,
                                                  default=list)

    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False,
                                               default="")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    #: USE AS IS / USE WITH CONDITIONS / DO NOT USE UNTIL REMEDIATED /
    #: INSUFFICIENT EVIDENCE TO FORM AN OPINION.
    opinion: Mapped[str] = mapped_column(String(64), nullable=False,
                                         default="")
    #: DRAFT, FINAL or SUPERSEDED. See REPORT_STATUSES.
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                        default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    structure_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                   default="")
    registry_version: Mapped[str] = mapped_column(String(24), nullable=False,
                                                  default="")
    calculation_version: Mapped[str] = mapped_column(String(24),
                                                     nullable=False,
                                                     default="")
    #: The dataset as-of the run read. Copied here so a reader holding only
    #: the report knows which data it describes.
    dataset_as_of: Mapped[str] = mapped_column(String(64), nullable=False,
                                               default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False,
                                              default="")

    #: The assembled document, section by section, as `report.build` produced
    #: it. Rendering is a pure function of this.
    document: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    generated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    generated_by_name: Mapped[str] = mapped_column(String(160),
                                                   nullable=False, default="")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())

    #: Set when a person finalises it. After that the row is immutable and a
    #: correction is a new version against a new run.
    finalised_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    finalised_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalised_by_name: Mapped[str] = mapped_column(String(160),
                                                   nullable=False, default="")
    #: The report this one replaced, when a validator issued a correction.
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("scv_reports.id", ondelete="SET NULL"),
        nullable=True)

    #: The run this report is of. One-directional: `ScvRun` deliberately has
    #: no `reports` collection, because loading a run should not drag its
    #: documents in behind it — a history screen reads runs by the hundred.
    run: Mapped[ScvRun] = relationship(foreign_keys=[run_id])

    __table_args__ = (
        Index("ix_scv_reports_run", "run_id"),
        Index("ix_scv_reports_model", "model_id", "generated_at"),
    )


__all__ = [
    "MODEL_KINDS", "REPORT_STATUSES", "RUN_SCOPES", "RUN_SOURCES",
    "RUN_STATUSES", "ScvFinding", "ScvReport",
    "ScvResult", "ScvRun",
]
