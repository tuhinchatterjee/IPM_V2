"""Regulatory requirements: what a circular actually asks a bank to do. §30, §31.

The distinction this module rests on
-------------------------------------
`schema.Rule` is what was READ out of a document: an obligation, a definition,
a threshold or an exception, with its page and its sentence. That layer is
about the text.

A REQUIREMENT is what CreditProbe understands the text to mean for THIS
installation: which concepts it touches, which datasets it needs, which
methods it changes, and what would have to be reconfigured if it were
accepted. That layer is about consequences, and it is a claim rather than a
reading.

Keeping them apart is the point. §27 is explicit — "do not conflate a source
circular with a certified Analysis Studio method" — and the failure it
prevents is a bank telling its regulator that a rule is implemented when what
happened is that somebody uploaded the circular.

Interpretation confidence
--------------------------
Every requirement carries a confidence, and it is computed from what the
extraction actually had rather than asserted. A requirement with a page, a
section, a quoted excerpt and three resolved concepts is on firmer ground than
one assembled from a sentence fragment, and the reviewer is entitled to see
which they are looking at. `confidence_from_evidence()` is the only way the
field is set: there is no path for a caller to declare a number.

Nothing here activates
-----------------------
A requirement's `promotion_status` starts NOT_PROMOTED and there is no
function in this module that changes production. §35: "No direct mutation from
extraction."
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

logger = logging.getLogger(__name__)

REQUIREMENT_SCHEMA_VERSION = "1.0.0"

# ------------------------------------------------------------------- §30's types
#
# Fifteen, and the list is closed. A sixteenth kind of requirement is a
# governance decision — somebody has to say what it means, who reviews it and
# what it may change — not a string a caller passes in.

DEFINITION = "DEFINITION"
SCOPE = "SCOPE"
THRESHOLD = "THRESHOLD"
CALCULATION = "CALCULATION"
CLASSIFICATION = "CLASSIFICATION"
DATA = "DATA"
REPORTING = "REPORTING"
DISCLOSURE = "DISCLOSURE"
GOVERNANCE = "GOVERNANCE"
CONTROL = "CONTROL"
MONITORING = "MONITORING"
WORKFLOW = "WORKFLOW"
TIMELINE = "TIMELINE"
EXCEPTION = "EXCEPTION"
TRANSITION = "TRANSITION"

TYPES: tuple[str, ...] = (
    DEFINITION, SCOPE, THRESHOLD, CALCULATION, CLASSIFICATION, DATA,
    REPORTING, DISCLOSURE, GOVERNANCE, CONTROL, MONITORING, WORKFLOW,
    TIMELINE, EXCEPTION, TRANSITION,
)

EXPECTED_TYPES = 15
if len(TYPES) != EXPECTED_TYPES:
    raise AssertionError(
        f"§30 names {EXPECTED_TYPES} requirement types; this module has "
        f"{len(TYPES)}. A type added without a meaning and a review owner is "
        "a type nobody can act on.")

#: What each type means, in the words a reviewer would use. A type with no
#: description gets applied to whatever the extractor could not classify.
TYPE_MEANS: dict[str, str] = {
    DEFINITION: "What a term means for regulatory purposes, where that "
                "differs from what the bank means by it internally.",
    SCOPE: "Who or what the rule applies to: which entities, products, "
           "portfolios or exposures are in and which are out.",
    THRESHOLD: "A number that changes a treatment when crossed.",
    CALCULATION: "How a figure must be computed. The type most likely to "
                 "become an Analysis Studio method.",
    CLASSIFICATION: "How an exposure must be categorised — stage, grade, "
                    "status, performing or not.",
    DATA: "A field, granularity or retention the bank must hold in order to "
          "comply at all.",
    REPORTING: "A return that must be submitted, on what basis and how often.",
    DISCLOSURE: "What must be published to the market or to counterparties, "
                "which is a different audience from a supervisory return.",
    GOVERNANCE: "Who must decide, who must approve, and what a board or "
                "committee must see.",
    CONTROL: "A check that must exist and be evidenced, independent of "
             "whether it ever fails.",
    MONITORING: "Something that must be watched on a stated frequency.",
    WORKFLOW: "A sequence a case must follow — escalation, referral, review.",
    TIMELINE: "A deadline or a permitted elapsed period.",
    EXCEPTION: "A carve-out from a rule that would otherwise apply.",
    TRANSITION: "A temporary arrangement between an old treatment and a new "
                "one, with its own dates.",
}

#: Types that can become an Analysis Studio Draft Method. §36 offers CONFIGURE
#: IN ANALYSIS STUDIO for a calculation requirement; offering it for a
#: governance requirement would produce a method that computes nothing.
CONFIGURABLE: frozenset[str] = frozenset({
    CALCULATION, THRESHOLD, CLASSIFICATION,
})

# ------------------------------------------------------- §31's credit topics
#
# Twenty-six areas that make a clause credit-relevant. Used to classify, never
# to dismiss: §31 is explicit that a non-credit clause may not be called
# irrelevant without review where ambiguity exists, so an unmatched clause
# becomes AMBIGUOUS rather than NOT_CREDIT_RELATED.

TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("borrower_scope", ("borrower", "obligor", "counterparty", "account",
                        "customer", "client")),
    ("default_npl", ("default", "non-performing", "npl", "npe",
                     "unlikely to pay", "utp")),
    ("ifrs9", ("ifrs 9", "ifrs9", "expected credit loss", "impairment")),
    ("stage_sicr", ("stage 1", "stage 2", "stage 3", "sicr",
                    "significant increase in credit risk", "staging")),
    ("pd_lgd_ead", ("probability of default", " pd ", "loss given default",
                    " lgd ", "exposure at default", " ead ", " ecl ")),
    ("ratings", ("rating", "grade", "scorecard", "internal rating",
                 "rating scale")),
    ("provisioning", ("provision", "allowance", "coverage ratio",
                      "write-down")),
    ("risk_appetite", ("risk appetite", "tolerance", "appetite statement")),
    ("concentration", ("concentration", "single name", "sectoral",
                       "granularity")),
    ("limits", ("limit", "cap", "ceiling", "sub-limit")),
    ("large_exposures", ("large exposure", "connected counterparties",
                         "group of connected")),
    ("covenants", ("covenant", "financial undertaking", "breach of covenant")),
    ("collateral", ("collateral", "security", "haircut", "loan to value",
                    "ltv", "valuation of security")),
    ("guarantees", ("guarantee", "guarantor", "credit protection",
                    "surety")),
    ("arrears_dpd", ("days past due", " dpd ", "arrears", "overdue",
                     "delinquen")),
    ("restructuring", ("restructur", "forbearance", "modification",
                       "rescheduling", "refinanc")),
    ("collections", ("collection", "recovery", "write-off", "write off",
                     "charge-off", "cure")),
    ("stress_testing", ("stress test", "scenario", "adverse scenario",
                        "sensitivity analysis")),
    ("early_warning", ("early warning", "watch list", "watchlist",
                       "deteriorat")),
    ("reporting", ("report", "return", "submission", "template",
                   "disclosure")),
    ("governance", ("board", "committee", "governance", "senior management",
                    "three lines")),
    ("validation", ("validation", "independent review", "back-test",
                    "backtest", "benchmarking")),
    ("data_quality", ("data quality", "completeness", "accuracy",
                      "retention", "lineage", "record keeping")),
    ("model_risk", ("model risk", "model governance", "model inventory",
                    "model owner")),
    ("approvals", ("approval", "delegated authority", "mandate",
                   "authorisation", "authorization")),
    ("responsibilities", ("responsib", "accountab", "ownership",
                          "designated person")),
)

EXPECTED_TOPICS = 26
if len(TOPICS) != EXPECTED_TOPICS:
    raise AssertionError(
        f"§31 names {EXPECTED_TOPICS} credit areas; this module has "
        f"{len(TOPICS)}.")

TOPIC_IDS: tuple[str, ...] = tuple(t for t, _ in TOPICS)

# ------------------------------------------------------------- relevance

CREDIT_RELATED = "CREDIT_RELATED"
#: Matched nothing, but the clause is not thereby harmless. §31: do not claim
#: non-credit clauses are irrelevant without review where ambiguity exists.
AMBIGUOUS = "AMBIGUOUS"
#: Reserved for a human decision. Extraction never produces it, which is the
#: whole safeguard: only a person may say a clause does not matter.
NOT_CREDIT_RELATED = "NOT_CREDIT_RELATED"

RELEVANCE: tuple[str, ...] = (CREDIT_RELATED, AMBIGUOUS, NOT_CREDIT_RELATED)

# ------------------------------------------------- validation and promotion

PROPOSED = "PROPOSED"
IN_REVIEW = "IN_REVIEW"
APPROVED = "APPROVED"
CORRECTED = "CORRECTED"
REJECTED = "REJECTED"
DEFERRED = "DEFERRED"
SECOND_REVIEW = "SECOND_REVIEW_REQUESTED"
SPLIT = "SPLIT"
MERGED = "MERGED"

VALIDATION_STATUSES: tuple[str, ...] = (
    PROPOSED, IN_REVIEW, APPROVED, CORRECTED, REJECTED, DEFERRED,
    SECOND_REVIEW, SPLIT, MERGED,
)

#: The statuses a requirement may be promoted from. CORRECTED counts:
#: a reviewer who rewrote the interpretation and then approved it has
#: approved their own words, which is the intended outcome of §32's CORRECT
#: INTERPRETATION action.
PROMOTABLE: frozenset[str] = frozenset({APPROVED, CORRECTED})

NOT_PROMOTED = "NOT_PROMOTED"
DRAFTED = "DRAFTED"
IN_VALIDATION = "IN_VALIDATION"
RELEASED = "RELEASED"
PROMOTION_STATUSES: tuple[str, ...] = (NOT_PROMOTED, DRAFTED, IN_VALIDATION,
                                       RELEASED)


class RequirementError(Exception):
    """A requirement that may not be written, or a change that is refused."""


# ------------------------------------------------------------------ the record


@dataclass
class Requirement:
    """§30's schema. One thing a document requires, and what it would touch."""

    requirement_id: str = ""
    document_id: str = ""
    schema_version: str = REQUIREMENT_SCHEMA_VERSION

    # where it came from — a requirement with no citation is a claim
    page: int = 0
    section_number: str = ""
    section_title: str = ""
    paragraph: str = ""
    #: The document's own words, held to a length that stays inside fair
    #: quotation. `excerpt_truncated` says when that limit bit, so nobody
    #: reads a clipped sentence as the whole clause.
    excerpt: str = ""
    excerpt_truncated: bool = False

    summary: str = ""
    requirement_type: str = DEFINITION
    relevance: str = AMBIGUOUS
    topics: tuple[str, ...] = ()

    jurisdiction: str = ""
    effective_from: date | None = None
    effective_to: date | None = None
    portfolio_scope: tuple[str, ...] = ()
    product_scope: tuple[str, ...] = ()

    # what it would touch here. Empty is a real answer and means "nothing we
    # could identify", which is a reason for a reviewer to look harder.
    affected_concepts: tuple[str, ...] = ()
    affected_datasets: tuple[str, ...] = ()
    affected_relationships: tuple[str, ...] = ()
    affected_methods: tuple[str, ...] = ()
    affected_calculations: tuple[str, ...] = ()
    affected_controls: tuple[str, ...] = ()
    affected_reports: tuple[str, ...] = ()
    affected_agents: tuple[str, ...] = ()
    affected_teaching_cases: tuple[str, ...] = ()

    #: Never set by a caller. `confidence_from_evidence()` computes it.
    interpretation_confidence: float = 0.0
    confidence_because: tuple[str, ...] = ()

    validation_status: str = PROPOSED
    reviewer: str = ""
    decision: str = ""
    decision_reason: str = ""
    #: What a reviewer said it really means, when they disagreed.
    correction: str = ""
    version: int = 1
    conflicts: tuple[str, ...] = ()
    promotion_status: str = NOT_PROMOTED
    promoted_as: str = ""

    created_at: str = ""
    tenant: str = ""

    def __post_init__(self) -> None:
        self.requirement_id = (self.requirement_id
                               or f"req_{uuid.uuid4().hex[:16]}")
        self.created_at = self.created_at or datetime.now(UTC).isoformat()

    @property
    def cited(self) -> bool:
        """Whether this requirement can point at where it came from.

        §29: "Every extracted item must retain page/section/paragraph
        citations." A requirement that cannot is not publishable, whatever
        else is true about it.
        """
        return bool(self.page or self.section_number or self.paragraph)

    @property
    def configurable(self) -> bool:
        """Whether §36's CONFIGURE IN ANALYSIS STUDIO applies."""
        return (self.requirement_type in CONFIGURABLE
                and self.validation_status in PROMOTABLE)

    @property
    def promotable(self) -> bool:
        return self.validation_status in PROMOTABLE and self.cited

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "document_id": self.document_id,
            "schema_version": self.schema_version,
            "citation": {
                "page": self.page,
                "section_number": self.section_number,
                "section_title": self.section_title,
                "paragraph": self.paragraph,
                "cited": self.cited,
            },
            "excerpt": self.excerpt,
            "excerpt_truncated": self.excerpt_truncated,
            "summary": self.summary,
            "requirement_type": self.requirement_type,
            "type_means": TYPE_MEANS.get(self.requirement_type, ""),
            "relevance": self.relevance,
            "topics": list(self.topics),
            "jurisdiction": self.jurisdiction,
            "effective_from": (self.effective_from.isoformat()
                               if self.effective_from else ""),
            "effective_to": (self.effective_to.isoformat()
                             if self.effective_to else ""),
            "portfolio_scope": list(self.portfolio_scope),
            "product_scope": list(self.product_scope),
            "affected": {
                "concepts": list(self.affected_concepts),
                "datasets": list(self.affected_datasets),
                "relationships": list(self.affected_relationships),
                "methods": list(self.affected_methods),
                "calculations": list(self.affected_calculations),
                "controls": list(self.affected_controls),
                "reports": list(self.affected_reports),
                "agents": list(self.affected_agents),
                "teaching_cases": list(self.affected_teaching_cases),
            },
            "interpretation_confidence": round(
                self.interpretation_confidence, 3),
            "confidence_because": list(self.confidence_because),
            "validation_status": self.validation_status,
            "reviewer": self.reviewer,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "correction": self.correction,
            "version": self.version,
            "conflicts": list(self.conflicts),
            "promotion_status": self.promotion_status,
            "promoted_as": self.promoted_as,
            "configurable": self.configurable,
            "promotable": self.promotable,
            "created_at": self.created_at,
        }


# ------------------------------------------------------------- §31 classify


def _haystack(text: str) -> str:
    """Lower-cased and space-padded, so " pd " cannot match "spdr"."""
    return f" {' '.join(text.lower().split())} "


def topics_in(text: str) -> tuple[str, ...]:
    """Which of §31's twenty-six areas this text touches."""
    hay = _haystack(text)
    return tuple(topic for topic, cues in TOPICS
                 if any(cue in hay for cue in cues))


def classify(text: str) -> tuple[str, tuple[str, ...]]:
    """§31's credit-relevance classification.

    Returns AMBIGUOUS rather than NOT_CREDIT_RELATED when nothing matches.
    The difference is the safeguard: "we found no credit cue" and "this
    clause does not matter" are different statements, and only a person may
    make the second one. A classifier that made it would quietly drop the
    clauses whose wording it happened not to recognise, which is exactly the
    clauses worth reading.
    """
    found = topics_in(text)
    return (CREDIT_RELATED if found else AMBIGUOUS), found


# --------------------------------------------------------- §30 confidence

#: The longest excerpt a requirement carries. Long enough to be the clause,
#: short enough to stay inside fair quotation of a copyrighted rulebook.
MAX_EXCERPT = 1200


def excerpt_of(text: str) -> tuple[str, bool]:
    """The quoted excerpt, and whether it had to be cut.

    Cuts on a sentence boundary where one is available. A clause truncated
    mid-word reads as though the regulator stopped talking.
    """
    cleaned = " ".join(text.split())
    if len(cleaned) <= MAX_EXCERPT:
        return cleaned, False
    window = cleaned[:MAX_EXCERPT]
    stop = max(window.rfind(". "), window.rfind("; "))
    if stop > MAX_EXCERPT // 2:
        return window[:stop + 1], True
    return window.rsplit(" ", 1)[0] + " …", True


#: What raises confidence, and by how much. Weights rather than a model: a
#: reviewer can be told why a requirement scored what it scored, and a number
#: nobody can explain is a number nobody should act on.
EVIDENCE: tuple[tuple[str, float, str], ...] = (
    ("page", 0.15, "the page it came from is known"),
    ("section", 0.15, "the section number is known"),
    ("paragraph", 0.10, "the paragraph is identified"),
    ("excerpt", 0.15, "the document's own words are quoted"),
    ("whole_excerpt", 0.05, "the quoted clause is complete rather than cut"),
    ("concepts", 0.15, "governed concepts were resolved from the text"),
    ("topics", 0.10, "recognised credit topics appear in the text"),
    ("type", 0.10, "the requirement type was determined from cue words "
                   "rather than defaulted"),
    ("dates", 0.05, "an effective date is known"),
)


def confidence_from_evidence(requirement: Requirement, *,
                             type_determined: bool = False
                             ) -> tuple[float, tuple[str, ...]]:
    """How far the extraction actually got, as a number and as sentences.

    Deliberately not a model score. Every point is traceable to something
    present or absent in the record, so a reviewer looking at 0.45 can see
    which four things were missing rather than being asked to trust a
    classifier's self-assessment.

    Absence is never penalised twice and never rounded up: a requirement with
    no citation at all cannot exceed the weight of what remains.
    """
    have: dict[str, bool] = {
        "page": bool(requirement.page),
        "section": bool(requirement.section_number),
        "paragraph": bool(requirement.paragraph),
        "excerpt": bool(requirement.excerpt.strip()),
        "whole_excerpt": (bool(requirement.excerpt.strip())
                          and not requirement.excerpt_truncated),
        "concepts": bool(requirement.affected_concepts),
        "topics": bool(requirement.topics),
        "type": type_determined,
        "dates": requirement.effective_from is not None,
    }
    score = sum(weight for key, weight, _ in EVIDENCE if have[key])
    missing = tuple(f"missing: {why}" for key, _, why in EVIDENCE
                    if not have[key])
    present = tuple(why for key, _, why in EVIDENCE if have[key])
    return round(min(score, 1.0), 3), present + missing


# ----------------------------------------------------------- type detection

#: Cue words that determine a requirement type. Ordered: the first match
#: wins, and the order runs from the most specific wording to the least, so
#: "shall be calculated as" becomes CALCULATION rather than GOVERNANCE on the
#: strength of a later "shall".
CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (CALCULATION, ("shall be calculated", "computed as", "calculated as",
                   "the formula", "shall be measured as", "sum of",
                   "multiplied by", "divided by")),
    (THRESHOLD, ("exceeds", "greater than", "less than", "at least",
                 "no more than", "minimum of", "maximum of", "% of",
                 "not exceed")),
    (CLASSIFICATION, ("shall be classified", "classified as", "categorised as",
                      "categorized as", "shall be treated as",
                      "shall be assigned")),
    (TRANSITION, ("transitional", "transition period", "until such time",
                  "phase-in", "phased in")),
    (EXCEPTION, ("except", "unless", "does not apply to", "exempt",
                 "carve-out", "shall not apply")),
    (TIMELINE, ("within", "no later than", "by the end of", "days of",
                "months of", "deadline")),
    (REPORTING, ("shall report", "shall submit", "return", "submission",
                 "reporting template")),
    (DISCLOSURE, ("shall disclose", "publish", "public disclosure",
                  "made available to the market")),
    (DATA, ("shall maintain records", "shall retain", "data quality",
            "record keeping", "shall capture", "granularity")),
    (MONITORING, ("shall monitor", "on an ongoing basis", "periodically",
                  "monthly", "quarterly", "annually")),
    (CONTROL, ("shall establish controls", "control framework",
               "independent verification", "shall verify")),
    (GOVERNANCE, ("the board", "senior management", "committee",
                  "shall approve", "governance")),
    (WORKFLOW, ("shall escalate", "referred to", "escalation",
                "shall be reviewed by")),
    (SCOPE, ("applies to", "shall apply to", "in scope", "covered by this",
             "for the purposes of this")),
    (DEFINITION, ("means", "is defined as", "shall mean", "definition of",
                  "refers to")),
)


def type_of(text: str) -> tuple[str, bool]:
    """The requirement type, and whether it was determined or defaulted.

    The boolean is the honest half. Defaulting every unrecognised clause to
    DEFINITION and reporting it as a determination would fill the review
    queue with confident mislabels; saying it was defaulted lets confidence
    fall and the reviewer look.
    """
    hay = _haystack(text)
    for kind, cues in CUES:
        if any(cue in hay for cue in cues):
            return kind, True
    return DEFINITION, False


# ------------------------------------------------------------ building one

#: Matches a leading clause number such as "4.2.1" or "(a)", so a paragraph
#: reference survives even when the extractor gave us no section metadata.
_PARAGRAPH = re.compile(r"^\s*(\(?[0-9]+(?:\.[0-9]+)*\)?|\([a-z]\))[\s.)]")


def paragraph_of(text: str) -> str:
    found = _PARAGRAPH.match(text)
    return found.group(1).strip("().") if found else ""


def propose(text: str, *, document_id: str, page: int = 0,
            section_number: str = "", section_title: str = "",
            concepts: tuple[str, ...] = (), datasets: tuple[str, ...] = (),
            jurisdiction: str = "", effective_from: date | None = None,
            tenant: str = "") -> Requirement:
    """Turn one clause into a proposed requirement.

    Proposed, not extracted: this is CreditProbe's reading, and the record
    says so through `validation_status=PROPOSED` and a confidence computed
    from what it actually had rather than from how sure it feels.
    """
    if not text.strip():
        raise RequirementError(
            "an empty clause cannot become a requirement; an extractor that "
            "read nothing should say so rather than propose nothing")

    kind, determined = type_of(text)
    relevance, topics = classify(text)
    excerpt, truncated = excerpt_of(text)

    requirement = Requirement(
        document_id=document_id,
        page=page,
        section_number=section_number,
        section_title=section_title,
        paragraph=paragraph_of(text),
        excerpt=excerpt,
        excerpt_truncated=truncated,
        summary=_summary(text),
        requirement_type=kind,
        relevance=relevance,
        topics=topics,
        jurisdiction=jurisdiction,
        effective_from=effective_from,
        affected_concepts=tuple(concepts),
        affected_datasets=tuple(datasets),
        tenant=tenant,
    )
    score, because = confidence_from_evidence(
        requirement, type_determined=determined)
    requirement.interpretation_confidence = score
    requirement.confidence_because = because
    return requirement


#: How much of a clause the one-line summary keeps. Long enough to be the
#: point of the clause, short enough that a reviewer scanning forty of them
#: reads forty lines rather than forty paragraphs.
SUMMARY_CHARS = 220


def _summary(text: str) -> str:
    """The clause's first sentence, or its opening, as one line.

    Deliberately extractive rather than generated. A generated summary of a
    regulatory clause is a paraphrase presented as a reading, and §29 wants
    the reviewer's attention on the excerpt.
    """
    cleaned = " ".join(text.split())
    stop = cleaned.find(". ")
    if 0 < stop <= SUMMARY_CHARS:
        return cleaned[:stop + 1]
    if len(cleaned) <= SUMMARY_CHARS:
        return cleaned
    return cleaned[:SUMMARY_CHARS].rsplit(" ", 1)[0] + " …"


def validate(requirement: Requirement) -> list[str]:
    """What is wrong with this requirement, in a reviewer's words."""
    problems: list[str] = []
    if requirement.requirement_type not in TYPES:
        problems.append(
            f"{requirement.requirement_type!r} is not one of §30's fifteen "
            "requirement types")
    if requirement.relevance not in RELEVANCE:
        problems.append(f"{requirement.relevance!r} is not a relevance")
    if requirement.validation_status not in VALIDATION_STATUSES:
        problems.append(
            f"{requirement.validation_status!r} is not a validation status")
    if requirement.promotion_status not in PROMOTION_STATUSES:
        problems.append(
            f"{requirement.promotion_status!r} is not a promotion status")
    if not requirement.document_id:
        problems.append(
            "a requirement with no document is a rule from nowhere")
    if not requirement.cited:
        problems.append(
            "no page, section or paragraph. §29 requires every extracted "
            "item to retain its citation, and a requirement that cannot say "
            "where it came from cannot be defended to a regulator")
    if not requirement.summary.strip():
        problems.append("no summary; a reviewer would have nothing to scan")
    if requirement.relevance == NOT_CREDIT_RELATED and not requirement.reviewer:
        problems.append(
            "only a person may decide a clause is not credit-related. §31 "
            "forbids claiming irrelevance without review where there is "
            "ambiguity, and extraction cannot tell the difference")
    if requirement.interpretation_confidence < 0 or \
            requirement.interpretation_confidence > 1:
        problems.append("interpretation confidence must be between 0 and 1")
    return problems


def census(requirements: list[Requirement]) -> dict[str, Any]:
    """What a document's extraction actually produced.

    Reports the uncited and the ambiguous separately rather than folding
    them into a total, because both are work for a person and a single
    "42 requirements found" hides both.
    """
    by_type = dict.fromkeys(TYPES, 0)
    by_status = dict.fromkeys(VALIDATION_STATUSES, 0)
    by_relevance = dict.fromkeys(RELEVANCE, 0)
    for one in requirements:
        by_type[one.requirement_type] = by_type.get(
            one.requirement_type, 0) + 1
        by_status[one.validation_status] = by_status.get(
            one.validation_status, 0) + 1
        by_relevance[one.relevance] = by_relevance.get(one.relevance, 0) + 1
    uncited = [r.requirement_id for r in requirements if not r.cited]
    low = [r.requirement_id for r in requirements
           if r.interpretation_confidence < 0.5]
    return {
        "total": len(requirements),
        "by_type": by_type,
        "by_validation_status": by_status,
        "by_relevance": by_relevance,
        "uncited": uncited,
        "low_confidence": low,
        "note": (
            "Ambiguous is not the same as not credit-related. Nothing here "
            "has decided a clause does not matter — only a reviewer may do "
            "that, and until they do the clause is waiting rather than "
            "dismissed."
        ),
    }
