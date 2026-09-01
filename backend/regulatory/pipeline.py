"""§29's regulatory document pipeline. Sixteen stages, none skippable.

    UPLOAD → MALWARE/FORMAT → TEXT/TABLE EXTRACTION → PAGE/SECTION ANCHORING
    → LANGUAGE DETECTION → CREDIT-RELEVANCE CLASSIFICATION
    → REQUIREMENT EXTRACTION → CONCEPT/METHOD/DATA/CONTROL MAPPING
    → CONTRADICTION CHECK → USER REVIEW → APPROVAL/REJECTION/CORRECTION
    → REGULATORY LEARNING CANDIDATE → VALIDATION → REGULATORY RELEASE
    → OPTIONAL ANALYSIS STUDIO CONFIGURATION

Why the order is not arbitrary
-------------------------------
Anchoring before classification, because a clause classified without a page
cannot be reviewed against the document. Classification before extraction,
because extracting requirements from a document nobody has established is
credit-related produces a queue of insurance clauses. Contradiction check
before review, because a reviewer deciding on a threshold needs to know that
a different circular already says something else about it — finding that out
afterwards means the review has to happen twice.

What this module does NOT do
-----------------------------
It does not read files, call models, or change production. It records where a
document is, refuses a stage that would skip one, and reports what each stage
found. The work happens in `extract.py`, `requirements.py`,
`contradictions.py` and the service layer; this is the part that can be
reasoned about without any of them.

The last stage is optional and says so
---------------------------------------
§29 ends "OPTIONAL ANALYSIS STUDIO CONFIGURATION", and a pipeline that
treated it as required would leave every governance requirement stuck one
stage from done forever. `COMPLETE` is reachable from RELEASED directly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "1.0.0"

UPLOADED = "UPLOADED"
SCANNED = "MALWARE_AND_FORMAT_CHECKED"
EXTRACTED = "TEXT_AND_TABLES_EXTRACTED"
ANCHORED = "PAGES_AND_SECTIONS_ANCHORED"
LANGUAGE_DETECTED = "LANGUAGE_DETECTED"
CLASSIFIED = "CREDIT_RELEVANCE_CLASSIFIED"
REQUIREMENTS_EXTRACTED = "REQUIREMENTS_EXTRACTED"
MAPPED = "CONCEPTS_AND_METHODS_MAPPED"
CONTRADICTIONS_CHECKED = "CONTRADICTIONS_CHECKED"
UNDER_REVIEW = "UNDER_REVIEW"
ADJUDICATED = "APPROVED_REJECTED_OR_CORRECTED"
CANDIDATE = "REGULATORY_LEARNING_CANDIDATE"
VALIDATED = "VALIDATED"
RELEASED = "RELEASED"
CONFIGURED = "CONFIGURED_IN_ANALYSIS_STUDIO"
COMPLETE = "COMPLETE"

STAGES: tuple[str, ...] = (
    UPLOADED, SCANNED, EXTRACTED, ANCHORED, LANGUAGE_DETECTED, CLASSIFIED,
    REQUIREMENTS_EXTRACTED, MAPPED, CONTRADICTIONS_CHECKED, UNDER_REVIEW,
    ADJUDICATED, CANDIDATE, VALIDATED, RELEASED, CONFIGURED, COMPLETE,
)

#: What each stage establishes. A stage nobody can describe is a stage that
#: gets marked done because the previous one finished.
MEANS: dict[str, str] = {
    UPLOADED: "The bytes are stored with their hash. Nothing has been read.",
    SCANNED: "The archive and format are what they claim to be, and the "
             "document carries nothing executable.",
    EXTRACTED: "Text and tables are out. A document nobody could read says "
               "so here rather than reading as a document with no rules.",
    ANCHORED: "Every piece of text knows its page and section, so a "
              "requirement can cite rather than claim.",
    LANGUAGE_DETECTED: "The language is known, because a clause read with "
                       "the wrong language's cue words is read wrongly.",
    CLASSIFIED: "Each section is credit-related or ambiguous. Nothing has "
                "been dismissed: only a reviewer may decide a clause does "
                "not matter.",
    REQUIREMENTS_EXTRACTED: "Clauses have become proposed requirements, "
                            "each with a type, a citation and a confidence "
                            "computed from what was actually found.",
    MAPPED: "What each requirement would touch here: concepts, datasets, "
            "relationships, methods, controls, reports, agents and cases.",
    CONTRADICTIONS_CHECKED: "Where this document disagrees with another "
                            "document, with local policy or with a "
                            "certified method — found BEFORE review, so a "
                            "reviewer decides once.",
    UNDER_REVIEW: "A person is going through the requirements one at a "
                  "time.",
    ADJUDICATED: "Every requirement has a decision and a reason.",
    CANDIDATE: "Approved requirements have become a learning candidate. "
               "Still nothing in production.",
    VALIDATED: "The candidate passed regression against what is already "
               "here.",
    RELEASED: "A versioned Regulatory Release exists and has been approved.",
    CONFIGURED: "Draft Methods were created in Analysis Studio. They are "
                "drafts: §36 forbids auto-certification.",
    COMPLETE: "Nothing further is pending on this document.",
}

#: Stages during which nothing from this document may reach a live answer.
#: Everything up to and including VALIDATED: a requirement is retrievable
#: only through an active Regulatory Release.
QUARANTINED: frozenset[str] = frozenset(STAGES[:STAGES.index(RELEASED)])

#: The one stage §29 marks optional. COMPLETE is reachable without it.
OPTIONAL: frozenset[str] = frozenset({CONFIGURED})

FAILED = "FAILED"
WITHDRAWN = "WITHDRAWN"
TERMINAL: frozenset[str] = frozenset({COMPLETE, FAILED, WITHDRAWN})


class PipelineError(Exception):
    """A stage transition that was refused, and why."""


@dataclass
class Step:
    """One stage, when it happened and what it found."""

    stage: str
    at: str = ""
    passed: bool = True
    detail: str = ""
    by: str = ""
    #: Counts the stage produced — requirements found, sections anchored.
    #: Kept rather than summarised because "12 of 40 clauses had no page" is
    #: the finding, and a boolean would lose it.
    counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.at = self.at or datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "at": self.at, "passed": self.passed,
                "detail": self.detail, "by": self.by,
                "means": MEANS.get(self.stage, ""),
                "counts": dict(self.counts)}


@dataclass
class Progress:
    """Where one document is, and how it got there."""

    document_id: str = ""
    run_id: str = ""
    stage: str = UPLOADED
    history: list[Step] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    started_at: str = ""
    tenant: str = ""

    def __post_init__(self) -> None:
        self.run_id = self.run_id or f"reg_{uuid.uuid4().hex[:12]}"
        self.started_at = self.started_at or datetime.now(UTC).isoformat()
        if not self.history:
            self.history.append(Step(UPLOADED))

    @property
    def quarantined(self) -> bool:
        return self.stage in QUARANTINED

    @property
    def retrievable(self) -> bool:
        """Whether anything from this document may reach a live answer.

        Only from RELEASED. There is no setting that changes this: an
        unreleased requirement is not in the retrieval path at all.
        """
        return self.stage in (RELEASED, CONFIGURED, COMPLETE)

    @property
    def next_stage(self) -> str:
        if self.stage in TERMINAL:
            return ""
        index = STAGES.index(self.stage)
        return STAGES[index + 1] if index + 1 < len(STAGES) else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "stage_means": MEANS.get(self.stage, ""),
            "next_stage": self.next_stage,
            "quarantined": self.quarantined,
            "retrievable": self.retrievable,
            "blockers": list(self.blockers),
            "history": [s.to_dict() for s in self.history],
            "pipeline": list(STAGES),
            "optional_stages": sorted(OPTIONAL),
            "started_at": self.started_at,
        }


def advance(progress: Progress, stage: str, *, passed: bool = True,
            detail: str = "", by: str = "",
            counts: dict[str, int] | None = None) -> Progress:
    """Move a document one stage, or refuse.

    Refuses a skipped stage. The only permitted jump is over CONFIGURED,
    which §29 marks optional — a governance requirement configures nothing
    in Analysis Studio and should not sit one stage from done forever.
    """
    if stage not in STAGES and stage not in (FAILED, WITHDRAWN):
        raise PipelineError(f"{stage!r} is not a pipeline stage")
    if progress.stage in TERMINAL:
        raise PipelineError(
            f"this document is {progress.stage}; nothing follows it")

    if stage in (FAILED, WITHDRAWN):
        if not detail.strip():
            raise PipelineError(
                f"a document marked {stage} needs a reason, or the next "
                "person cannot tell whether it was the document or us")
        progress.stage = stage
        progress.history.append(Step(stage, passed=False, detail=detail,
                                     by=by, counts=counts or {}))
        return progress

    here = STAGES.index(progress.stage)
    there = STAGES.index(stage)
    if there <= here:
        raise PipelineError(
            f"{stage} does not follow {progress.stage}; a stage already "
            "passed cannot be passed again, and re-running one is a new run")
    skipped = [s for s in STAGES[here + 1:there] if s not in OPTIONAL]
    if skipped:
        raise PipelineError(
            f"{stage} would skip {', '.join(skipped)}. The order is not "
            "decorative: anchoring before classification is what lets a "
            "requirement cite a page, and a contradiction found after "
            "review means the review happens twice")

    progress.stage = stage
    progress.history.append(Step(stage, passed=passed, detail=detail, by=by,
                                 counts=counts or {}))
    if not passed and detail:
        progress.blockers.append(f"{stage}: {detail}")
    return progress


def may_release(progress: Progress, *, requirements_adjudicated: bool,
                validation_passed: bool, approver: str,
                reviewer: str) -> tuple[bool, str]:
    """Whether this document's requirements may become a Regulatory Release.

    Two pairs of eyes, as everywhere else that matters: the person who
    approves a release may not be the only person who reviewed everything in
    it. That is not distrust of the reviewer; it is the same rule the
    teaching library and the Brain Center apply to material actions.
    """
    if progress.stage != VALIDATED:
        return False, (f"this document is at {progress.stage}; a release is "
                       f"built from {VALIDATED}")
    if not requirements_adjudicated:
        return False, ("some requirements have no decision. A release "
                       "containing an unreviewed requirement is a release "
                       "nobody can defend")
    if not validation_passed:
        return False, "validation did not pass"
    if progress.blockers:
        return False, "; ".join(progress.blockers)
    if not approver.strip():
        return False, "a release needs a named approver"
    if approver.strip() == reviewer.strip():
        return False, ("the approver reviewed every requirement in this "
                       "release. Approving your own review is one pair of "
                       "eyes wearing two hats")
    return True, ""
