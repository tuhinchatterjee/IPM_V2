"""What kind of document this is, and what that kind requires. §2, §10, §13.

Why the type matters
--------------------
"92% complete" is meaningless without knowing what complete MEANS for this
paper. A model development report is not complete without an out-of-time test;
a committee pack is not complete without the decisions it is asking for. One
hard-coded formula for both would be wrong for each, so the requirements — the
sections a type needs, and the weights its completion score uses — travel with
the document in `PlaybookDocumentProfile.requirements`.

Who decides
-----------
The system may infer a type from the instruction and the sources. Only a person
settles it, and `classified_by` records which of the two happened, so an
inference is never mistaken later for a decision. Classification is editable at
any time and the profile is re-scored when it changes.

What this deliberately does not do
----------------------------------
It does not ask a model. Classification here is a keyword match over the user's
own words and their file names, which is explainable, free, instant, and
reproducible — and when it is not confident it says so rather than guessing,
which is what §2's lightweight question is for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------

COMMITTEE_REPORT = "committee_report"
MODEL_DEVELOPMENT = "model_development_report"
MODEL_VALIDATION = "model_validation_report"
IFRS9_REPORT = "ifrs9_report"
PORTFOLIO_REVIEW = "portfolio_review"
RISK_APPETITE = "risk_appetite_report"
REGULATORY_RESPONSE = "regulatory_response"
CREDIT_REVIEW = "credit_review"
MANAGEMENT_PAPER = "management_paper"
BOARD_PAPER = "board_paper"
METHODOLOGY = "methodology_document"
POLICY = "policy_document"
PRESENTATION = "presentation"
GENERAL = "general"

#: Every type a profile may carry. Closed, because an open set of types is an
#: open set of requirement tables nobody maintains.
DOCUMENT_TYPES = (
    COMMITTEE_REPORT, MODEL_DEVELOPMENT, MODEL_VALIDATION, IFRS9_REPORT,
    PORTFOLIO_REVIEW, RISK_APPETITE, REGULATORY_RESPONSE, CREDIT_REVIEW,
    MANAGEMENT_PAPER, BOARD_PAPER, METHODOLOGY, POLICY, PRESENTATION, GENERAL,
)

#: The types that are committee papers by their nature. A committee paper gains
#: decisions, actions, blocking findings and an approval bar; the others do not
#: get committee furniture they have no use for.
COMMITTEE_TYPES = frozenset({COMMITTEE_REPORT, BOARD_PAPER})

LABELS = {
    COMMITTEE_REPORT: "Committee report",
    MODEL_DEVELOPMENT: "Model development report",
    MODEL_VALIDATION: "Model validation report",
    IFRS9_REPORT: "IFRS 9 report",
    PORTFOLIO_REVIEW: "Portfolio review",
    RISK_APPETITE: "Risk appetite report",
    REGULATORY_RESPONSE: "Regulatory response",
    CREDIT_REVIEW: "Credit review",
    MANAGEMENT_PAPER: "Management paper",
    BOARD_PAPER: "Board paper",
    METHODOLOGY: "Methodology document",
    POLICY: "Policy document",
    PRESENTATION: "Presentation",
    GENERAL: "General working document",
}


# --------------------------------------------------------------------------
# What each kind of document requires
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Requirements:
    """The sections a type needs and how its completion is weighted.

    `weights` must sum to 100. They are per type because a model development
    report earns most of its completeness from having written the required
    sections, while a committee pack earns it from having dispositioned what
    it raised — and scoring both the same way flatters one and punishes the
    other.
    """

    sections: tuple[str, ...]
    weights: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"sections": list(self.sections), "weights": dict(self.weights)}

    @classmethod
    def from_dict(cls, d: dict) -> Requirements:
        return cls(sections=tuple(d.get("sections") or ()),
                   weights=dict(d.get("weights") or {}))


#: The five components a completion score is built from. Named here so a
#: dashboard can explain a percentage in the same words everywhere.
REQUIRED_SECTIONS = "required_sections"
EVIDENCE_ATTACHED = "evidence_attached"
REQUIRED_TABLES = "required_tables"
METRICS_RESOLVED = "metrics_resolved"
FINDINGS_DISPOSITIONED = "findings_dispositioned"
HUMAN_REVIEW = "human_review"

COMPONENTS = (REQUIRED_SECTIONS, EVIDENCE_ATTACHED, REQUIRED_TABLES,
              METRICS_RESOLVED, FINDINGS_DISPOSITIONED, HUMAN_REVIEW)

_GENERAL_WEIGHTS = {REQUIRED_SECTIONS: 40, EVIDENCE_ATTACHED: 20,
                    REQUIRED_TABLES: 10, METRICS_RESOLVED: 10,
                    FINDINGS_DISPOSITIONED: 10, HUMAN_REVIEW: 10}

_COMMITTEE_WEIGHTS = {REQUIRED_SECTIONS: 30, EVIDENCE_ATTACHED: 15,
                      REQUIRED_TABLES: 5, METRICS_RESOLVED: 15,
                      FINDINGS_DISPOSITIONED: 25, HUMAN_REVIEW: 10}

_DEVELOPMENT_WEIGHTS = {REQUIRED_SECTIONS: 50, EVIDENCE_ATTACHED: 20,
                        REQUIRED_TABLES: 10, METRICS_RESOLVED: 10,
                        FINDINGS_DISPOSITIONED: 5, HUMAN_REVIEW: 5}

REQUIREMENTS: dict[str, Requirements] = {
    # A GENERIC committee agenda. It previously named "Book performance",
    # "Origination quality" and "Model performance" — sections specific to a
    # retail portfolio committee, which marked every other kind of committee
    # pack incomplete for sections it should never have had. Those belong to
    # PORTFOLIO_REVIEW; a committee report as such needs the summary, the
    # context, the analysis, the findings, what is being asked of the
    # committee, and what is recommended.
    COMMITTEE_REPORT: Requirements(
        sections=("Executive summary", "Background", "Analysis", "Findings",
                  "Decisions requested", "Recommendations"),
        weights=_COMMITTEE_WEIGHTS),
    BOARD_PAPER: Requirements(
        sections=("Executive summary", "Purpose", "Background", "Analysis",
                  "Risks", "Decisions requested", "Recommendations"),
        weights=_COMMITTEE_WEIGHTS),
    MODEL_DEVELOPMENT: Requirements(
        sections=("Executive summary", "Objective", "Scope",
                  "Target definition", "Development data", "Data quality",
                  "Variable selection", "Methodology", "Performance",
                  "Calibration", "Stability", "Out of time testing", "Policy",
                  "Governance", "Limitations", "Conclusion",
                  "Recommendations"),
        weights=_DEVELOPMENT_WEIGHTS),
    MODEL_VALIDATION: Requirements(
        sections=("Executive summary", "Scope", "Data replication",
                  "Methodology review", "Calibration validation",
                  "Stability testing", "Sensitivity testing", "Findings",
                  "Limitations", "Conclusion", "Recommendations"),
        weights=_DEVELOPMENT_WEIGHTS),
    IFRS9_REPORT: Requirements(
        sections=("Executive summary", "Basis of preparation",
                  "Data and population", "Methodology", "Scenario results",
                  "Staging", "Model monitoring", "Post-model adjustments",
                  "Limitations", "Findings", "Conclusions",
                  "Recommendations"),
        weights=_GENERAL_WEIGHTS),
    PORTFOLIO_REVIEW: Requirements(
        sections=("Executive summary", "Portfolio composition",
                  "Performance", "Concentrations", "Findings",
                  "Recommendations"),
        weights=_GENERAL_WEIGHTS),
    METHODOLOGY: Requirements(
        sections=("Purpose", "Scope", "Methodology", "Assumptions",
                  "Limitations", "Governance"),
        weights=_GENERAL_WEIGHTS),
}

#: A type with no table of its own is complete when it has an executive
#: summary and a conclusion, which is the least a document can be said to have.
DEFAULT_REQUIREMENTS = Requirements(
    sections=("Executive summary", "Conclusion"), weights=_GENERAL_WEIGHTS)


def requirements_for(document_type: str) -> Requirements:
    return REQUIREMENTS.get(document_type, DEFAULT_REQUIREMENTS)


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------

#: Phrases that name a type. Ordered most specific first, because "model
#: validation report" must not be read as a "model development report" merely
#: because both contain "model".
_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (MODEL_VALIDATION, ("model validation", "validation report",
                        "independent validation", "scorecard validation")),
    (MODEL_DEVELOPMENT, ("model development", "development report",
                         "scorecard development", "redevelopment")),
    (IFRS9_REPORT, ("ifrs 9", "ifrs9", "expected credit loss", "ecl ")),
    (BOARD_PAPER, ("board paper", "board pack", "for the board")),
    (COMMITTEE_REPORT, ("committee report", "committee pack",
                        "committee paper", "for the committee",
                        "credit committee", "risk committee")),
    (RISK_APPETITE, ("risk appetite",)),
    (REGULATORY_RESPONSE, ("regulatory response", "sama", "regulator",
                           "supervisory")),
    (PORTFOLIO_REVIEW, ("portfolio review", "portfolio performance")),
    (CREDIT_REVIEW, ("credit review", "obligor review", "annual review")),
    (METHODOLOGY, ("methodology", "method document")),
    (POLICY, ("policy document", "credit policy", "policy manual")),
    (PRESENTATION, ("presentation", "slide deck", "deck ", "pptx")),
    (MANAGEMENT_PAPER, ("management paper", "management report")),
)

HIGH, MEDIUM, LOW = "high", "medium", "low"


@dataclass(frozen=True)
class Inference:
    """A guess, labelled as one, with what it was guessed from."""

    document_type: str
    confidence: str
    committee_report: bool
    evidence: tuple[str, ...] = ()

    @property
    def should_ask(self) -> bool:
        """Whether §2's lightweight question is worth interrupting for.

        Only when the guess is weak. A model development report asked for in
        those words is not a question, and asking anyway is the kind of
        friction that makes people stop using a product.
        """
        return self.confidence == LOW


def infer(instruction: str, *, filenames: tuple[str, ...] = (),
          family: str = "") -> Inference:
    """What kind of document this probably is, from the user's own words.

    No model call. A keyword match is explainable, instant and reproducible,
    and where it is unsure it says so instead of inventing a type.
    """
    haystack = " ".join([instruction or "", " ".join(filenames),
                         family or ""]).lower()
    haystack = re.sub(r"[_\-/]+", " ", haystack)

    matched: list[tuple[str, str]] = []
    for document_type, phrases in _SIGNALS:
        for phrase in phrases:
            if phrase in haystack:
                matched.append((document_type, phrase.strip()))
                break

    if not matched:
        return Inference(GENERAL, LOW, False)

    document_type, phrase = matched[0]
    # A committee paper can also be an IFRS 9 report or a validation report.
    # The type is the most specific match; "for the committee" alongside it
    # sets the committee flag rather than overriding what kind of paper it is.
    committee = (document_type in COMMITTEE_TYPES
                 or any(t in COMMITTEE_TYPES for t, _ in matched))
    confidence = HIGH if len(matched) == 1 or matched[0][0] == document_type \
        else MEDIUM
    if document_type == GENERAL:
        confidence = LOW
    return Inference(document_type, confidence, committee,
                     tuple(p for _, p in matched))


def label(document_type: str) -> str:
    return LABELS.get(document_type, LABELS[GENERAL])
