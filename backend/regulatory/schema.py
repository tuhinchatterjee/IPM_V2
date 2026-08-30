"""
What a regulatory circular is, once CreditProbe has read it. Part G.

Why a circular is not a document
---------------------------------
A bank does not ask "what does SAMA circular 41042432 say?". It asks "what
capital treatment applies to this exposure at this date?", and the answer is
an obligation, its threshold, its exceptions, and the date range over which it
was in force. A store that holds the PDF and searches its text can answer the
first question and not the second, and the second is the one that ends up in a
credit paper.

So a circular is decomposed into four kinds of extracted rule — obligations,
definitions, thresholds and exceptions — each carrying the page and section it
came from, so every answer can cite the sentence rather than the file.

Immutability
-------------
The original is stored once, byte for byte, with its SHA-256. Nothing rewrites
it, and a re-upload of the same bytes is recognised rather than duplicated. An
extraction can be re-run and re-reviewed; the original it was taken from
cannot change underneath it, because a citation that points at a document
somebody has since edited is worse than no citation.

Effective dates, supersession and "as of"
------------------------------------------
Every circular carries an issue date, an effective date and an optional
expiry, and may supersede named earlier circulars. Retrieval is always AS OF a
date: the rules in force on the reporting date, not the rules in force today.
An impairment paper written for Q2 2025 that quotes a circular issued in Q4
2025 is wrong in a way that reads as thorough.

Confidentiality
----------------
A circular may be public (a regulator's published rulebook), restricted (a
supervisory letter to this bank) or confidential. The class travels with the
document and with every rule extracted from it, because the extraction is as
disclosing as the original: a threshold quoted out of a supervisory letter
discloses the letter.

Nothing here is a review
-------------------------
Extraction produces CANDIDATE rules. A rule reaches production retrieval only
through SME review and an approved Regulatory Knowledge Release — the same
discipline as the teaching library, for the same reason: a validator passing
is not a person agreeing.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

REGULATORY_SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------

PDF = "PDF"
DOCX = "DOCX"
XLSX = "XLSX"
CSV = "CSV"
TXT = "TXT"
HTML = "HTML"

FORMATS: tuple[str, ...] = (PDF, DOCX, XLSX, CSV, TXT, HTML)

#: What each extension means. Anything not here is refused at upload rather
#: than stored as an unknown blob nobody can extract: a document the platform
#: cannot read is a document whose obligations are invisible, and storing it
#: makes the corpus look more complete than it is.
EXTENSIONS: dict[str, str] = {
    ".pdf": PDF, ".docx": DOCX, ".doc": DOCX,
    ".xlsx": XLSX, ".xlsm": XLSX,
    ".csv": CSV, ".txt": TXT, ".md": TXT,
    ".html": HTML, ".htm": HTML,
}

# ---------------------------------------------------------------------------
# Confidentiality
# ---------------------------------------------------------------------------

PUBLIC = "PUBLIC"
RESTRICTED = "RESTRICTED"
CONFIDENTIAL = "CONFIDENTIAL"

CONFIDENTIALITY: tuple[str, ...] = (PUBLIC, RESTRICTED, CONFIDENTIAL)

CONFIDENTIALITY_MEANS: dict[str, str] = {
    PUBLIC: "A regulator's published rulebook or circular. May be quoted in "
            "an answer and may be shared through a governed release.",
    RESTRICTED: "Addressed to this bank. May be used inside this tenant and "
                "never in a shared or public release.",
    CONFIDENTIAL: "Supervisory correspondence. Retrievable only by a named "
                  "role, never quoted in an exported answer, never shared.",
}

#: Whether a class may leave the tenant it was uploaded into. §30's rule about
#: cross-tenant learning applies to regulatory knowledge too: public knowledge
#: may be shared through a governed release, and a supervisory letter to one
#: bank may not.
SHAREABLE: frozenset[str] = frozenset({PUBLIC})

# ---------------------------------------------------------------------------
# Document status
# ---------------------------------------------------------------------------

UPLOADED = "UPLOADED"
EXTRACTED = "EXTRACTED"
#: The original is stored and hashed; no extractor could read it. Kept as its
#: own state rather than folded into EXTRACTED-with-no-rules, which would make
#: an unreadable scan indistinguishable from a circular that genuinely
#: imposes no obligations.
EXTRACTION_UNAVAILABLE = "EXTRACTION_UNAVAILABLE"
NEEDS_OCR = "NEEDS_OCR"
IN_REVIEW = "IN_REVIEW"
REVIEWED = "REVIEWED"
APPROVED = "APPROVED"
SUPERSEDED = "SUPERSEDED"
WITHDRAWN = "WITHDRAWN"
REJECTED = "REJECTED"

DOCUMENT_STATUSES: tuple[str, ...] = (
    UPLOADED, EXTRACTED, EXTRACTION_UNAVAILABLE, NEEDS_OCR, IN_REVIEW,
    REVIEWED, APPROVED, SUPERSEDED, WITHDRAWN, REJECTED)

STATUS_MEANS: dict[str, str] = {
    UPLOADED: "The original is stored and hashed. Nothing has been read out "
              "of it yet.",
    EXTRACTED: "Text, sections and candidate rules have been read out. None "
               "of them has been reviewed.",
    EXTRACTION_UNAVAILABLE: "The original is stored and no extractor on this "
                            "deployment can read that format.",
    NEEDS_OCR: "The pages carry no extractable text. They are images, and "
               "this deployment has no OCR engine configured.",
    IN_REVIEW: "A regulatory SME is working through the extracted rules.",
    REVIEWED: "An SME has been through it. Approval is a separate act.",
    APPROVED: "Approved for retrieval, through a Regulatory Knowledge "
              "Release.",
    SUPERSEDED: "A later circular replaced it. It remains retrievable AS OF "
                "the dates it was in force.",
    WITHDRAWN: "The regulator withdrew it. Retrievable only as history.",
    REJECTED: "Not admitted to the corpus.",
}

#: The statuses a rule may be retrieved from in production. Deliberately one.
RETRIEVABLE_STATUSES: frozenset[str] = frozenset({APPROVED, SUPERSEDED})

# ---------------------------------------------------------------------------
# Document type. §28.
#
# What KIND of regulatory instrument this is, which is not the same as its
# format and not derivable from its filename. §28: "Do not rely solely on
# filename." A supervisory letter and a published rulebook have different
# confidentiality, different authority and different audiences, and a PDF
# called "circular_2026.pdf" could be either.
# ---------------------------------------------------------------------------

CIRCULAR = "CIRCULAR"
RULEBOOK = "RULEBOOK"
GUIDELINE = "GUIDELINE"
SUPERVISORY_LETTER = "SUPERVISORY_LETTER"
STANDARD = "STANDARD"
CONSULTATION = "CONSULTATION"
FAQ = "FAQ"
INTERNAL_POLICY = "INTERNAL_POLICY"
#: The honest default. A document whose kind nobody stated is unclassified,
#: not a circular: defaulting to CIRCULAR would give an internal draft the
#: standing of a regulator's instrument.
UNCLASSIFIED = "UNCLASSIFIED"

DOCUMENT_TYPES: tuple[str, ...] = (
    CIRCULAR, RULEBOOK, GUIDELINE, SUPERVISORY_LETTER, STANDARD,
    CONSULTATION, FAQ, INTERNAL_POLICY, UNCLASSIFIED,
)

DOCUMENT_TYPE_MEANS: dict[str, str] = {
    CIRCULAR: "A dated instruction from a regulator to the institutions it "
              "supervises.",
    RULEBOOK: "A published, consolidated body of rules.",
    GUIDELINE: "Guidance on how a rule is expected to be applied. Persuasive "
               "rather than binding, and the difference matters in a "
               "defence.",
    SUPERVISORY_LETTER: "Addressed to this institution specifically. "
                        "Restricted by default, and an extract of it "
                        "discloses it.",
    STANDARD: "An accounting or international standard — IFRS, Basel — "
              "rather than a local regulator's instrument.",
    CONSULTATION: "A proposal. Not in force, and a requirement extracted "
                  "from one must never read as though it is.",
    FAQ: "A regulator's answers to questions. Interpretive.",
    INTERNAL_POLICY: "The bank's own policy. Belongs here because a "
                     "regulatory contradiction is often against local "
                     "policy, and that is a decision rather than a defect.",
    UNCLASSIFIED: "Nobody has said what kind of document this is. Not a "
                  "default to act on.",
}

#: Types that are NOT in force whatever their dates say.
#:
#: Just the one. A consultation paper's "effective date" is a proposal, and a
#: requirement extracted from one that reached retrieval would have the bank
#: complying with a rule that does not exist — which reads, on the page,
#: exactly like diligence.
#:
#: UNCLASSIFIED is deliberately NOT here. "Nobody has said what kind of
#: document this is" is a finding for a reviewer, not grounds to withdraw a
#: document from retrieval: every document uploaded before §28 existed
#: carries that value, and treating it as not-in-force would quietly empty
#: the corpus and look like data loss rather than caution.
NOT_IN_FORCE: frozenset[str] = frozenset({CONSULTATION})

#: Types a reviewer should be asked to confirm. Surfaced, not enforced.
NEEDS_TYPE_CONFIRMATION: frozenset[str] = frozenset({UNCLASSIFIED})

# ---------------------------------------------------------------------------
# Rule kinds
# ---------------------------------------------------------------------------

OBLIGATION = "OBLIGATION"
DEFINITION = "DEFINITION"
THRESHOLD = "THRESHOLD"
EXCEPTION = "EXCEPTION"

RULE_KINDS: tuple[str, ...] = (OBLIGATION, DEFINITION, THRESHOLD, EXCEPTION)

RULE_MEANS: dict[str, str] = {
    OBLIGATION: "Something the bank must, shall or may not do.",
    DEFINITION: "What a term means for the purposes of this circular — which "
                "is not always what it means in the bank's own ontology, and "
                "the difference is the point.",
    THRESHOLD: "A number a treatment turns on: a ratio, a limit, a period, a "
               "percentage.",
    EXCEPTION: "Where an obligation does not apply, or applies differently.",
}

#: Candidate rules are proposed by extraction and reviewed by a person.
CANDIDATE = "CANDIDATE"
RULE_STATUSES: tuple[str, ...] = (CANDIDATE, IN_REVIEW, REVIEWED, APPROVED,
                                  REJECTED, SUPERSEDED)


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------


def sha256_of(payload: bytes) -> str:
    """The hash a citation is anchored to."""
    return hashlib.sha256(payload).hexdigest()


def format_of(filename: str) -> str:
    """The format an upload declares by its extension, or "" if unsupported."""
    lowered = str(filename or "").lower().strip()
    for extension, name in EXTENSIONS.items():
        if lowered.endswith(extension):
            return name
    return ""


@dataclass
class Page:
    """One page or sheet of an original, as extracted."""

    number: int
    text: str = ""
    #: Tables lifted whole, each a list of rows. A threshold in a table read
    #: as running prose loses the column it belonged to.
    tables: list[list[list[str]]] = field(default_factory=list)
    #: True when the page carried no extractable text at all. Reported rather
    #: than smoothed over: a circular whose thresholds are in a scan is a
    #: circular nothing can cite.
    needs_ocr: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "text": self.text,
                "tables": [[list(r) for r in t] for t in self.tables],
                "needs_ocr": self.needs_ocr,
                "characters": len(self.text)}


@dataclass
class Section:
    """A numbered part of a circular — the unit a citation points at."""

    section_id: str
    heading: str = ""
    number: str = ""
    text: str = ""
    page: int = 0
    #: The section this one sits inside, for a citation that reads the way a
    #: lawyer would write it: "4.2.1 under 4.2 under Part 4".
    parent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"section_id": self.section_id, "heading": self.heading,
                "number": self.number, "text": self.text, "page": self.page,
                "parent": self.parent}


@dataclass
class Rule:
    """One obligation, definition, threshold or exception."""

    rule_id: str
    kind: str
    text: str
    #: Where it came from, exactly. A rule with no page and no section is a
    #: claim, not a citation.
    section_id: str = ""
    section_number: str = ""
    page: int = 0
    #: For a threshold: the number and its unit, parsed out so a comparison
    #: can be made rather than a string matched.
    value: float | None = None
    unit: str = ""
    #: The governed concepts this rule is about, in the ontology's own words,
    #: so a question about ECL coverage can reach a rule about it.
    concepts: list[str] = field(default_factory=list)
    status: str = CANDIDATE
    reviewer: str = ""
    review_note: str = ""
    confidence: float = 0.0
    #: Why extraction proposed it. Shown to the SME, because a reviewer who
    #: cannot see why the machine thought this was an obligation cannot judge
    #: whether it was right.
    because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "kind": self.kind, "text": self.text,
                "section_id": self.section_id,
                "section_number": self.section_number, "page": self.page,
                "value": self.value, "unit": self.unit,
                "concepts": list(self.concepts), "status": self.status,
                "reviewer": self.reviewer, "review_note": self.review_note,
                "confidence": round(self.confidence, 3),
                "because": self.because,
                "means": RULE_MEANS.get(self.kind, "")}


@dataclass
class Circular:
    """A regulatory document, its metadata and everything read out of it."""

    circular_id: str
    title: str = ""
    regulator: str = ""
    reference: str = ""
    #: Dates. `issued` is when the regulator published it; `effective` is when
    #: it starts to bite, which is often a different quarter and is the one
    #: as-of retrieval uses.
    issued: date | None = None
    effective: date | None = None
    expires: date | None = None
    jurisdiction: str = ""
    language: str = "en"
    #: §28. What kind of instrument this is, stated rather than guessed from
    #: the filename.
    document_type: str = UNCLASSIFIED
    #: §28's scope fields. What the document is about, whom it binds and
    #: over which products — none of which is the same as the jurisdiction.
    scope: str = ""
    products: list[str] = field(default_factory=list)
    portfolio_scope: list[str] = field(default_factory=list)
    #: The document's own version, where the regulator issues one. Distinct
    #: from `schema_version`, which is ours.
    document_version: str = ""
    #: Where it came from — a regulator's website, a supervisor's email, an
    #: internal upload. Provenance a reviewer can weigh.
    source: str = ""
    #: Which roles may read this document and its extracts. Empty means the
    #: confidentiality class alone governs.
    permissions: list[str] = field(default_factory=list)
    file_format: str = ""
    filename: str = ""
    #: The original's SHA-256. The anchor every citation resolves through.
    content_hash: str = ""
    byte_size: int = 0
    page_count: int = 0
    status: str = UPLOADED
    confidentiality: str = RESTRICTED
    tenant: str = ""
    #: References of circulars this one replaces.
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str = ""
    pages: list[Page] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    uploaded_by: str = ""
    uploaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    notes: str = ""
    schema_version: str = REGULATORY_SCHEMA_VERSION

    @property
    def shareable(self) -> bool:
        return self.confidentiality in SHAREABLE

    @property
    def retrievable(self) -> bool:
        return self.status in RETRIEVABLE_STATUSES

    def in_force_on(self, when: date) -> bool:
        """Whether this circular was in force on a given date.

        Fail-closed on a missing effective date: a circular that does not say
        when it starts is not treated as having always applied.

        Fail-closed on a consultation paper too, whatever dates it carries.
        A consultation's "effective date" is a proposal, and a requirement
        extracted from one that reached retrieval would have the bank
        complying with a rule that does not exist — which reads, on the
        page, exactly like diligence.
        """
        if self.document_type in NOT_IN_FORCE:
            return False
        if self.effective is None:
            return False
        if when < self.effective:
            return False
        if self.expires is not None and when > self.expires:
            return False
        return True

    def citation(self) -> str:
        """How this document is named in an answer."""
        parts = [p for p in (self.regulator, self.reference) if p]
        head = " ".join(parts) or self.title or self.circular_id
        if self.effective:
            head += f" (effective {self.effective.isoformat()})"
        return head

    def to_dict(self) -> dict[str, Any]:
        return {
            "circular_id": self.circular_id, "title": self.title,
            "regulator": self.regulator, "reference": self.reference,
            "issued": self.issued.isoformat() if self.issued else "",
            "effective": self.effective.isoformat() if self.effective else "",
            "expires": self.expires.isoformat() if self.expires else "",
            "jurisdiction": self.jurisdiction, "language": self.language,
            "format": self.file_format, "filename": self.filename,
            "content_hash": self.content_hash, "byte_size": self.byte_size,
            "page_count": self.page_count, "status": self.status,
            "status_means": STATUS_MEANS.get(self.status, ""),
            "confidentiality": self.confidentiality,
            "confidentiality_means":
                CONFIDENTIALITY_MEANS.get(self.confidentiality, ""),
            "tenant": self.tenant,
            "supersedes": list(self.supersedes),
            "superseded_by": self.superseded_by,
            "sections": [s.to_dict() for s in self.sections],
            "rules": [r.to_dict() for r in self.rules],
            "rule_counts": self.rule_counts(),
            "uploaded_by": self.uploaded_by,
            "uploaded_at": self.uploaded_at.isoformat(),
            "citation": self.citation(),
            "shareable": self.shareable,
            "retrievable": self.retrievable,
            "notes": self.notes,
            "schema_version": self.schema_version,
        }

    def rule_counts(self) -> dict[str, int]:
        counts = {kind: 0 for kind in RULE_KINDS}
        for rule in self.rules:
            counts[rule.kind] = counts.get(rule.kind, 0) + 1
        return counts


@dataclass
class Citation:
    """What an answer says when it relies on a circular.

    A citation names the regulator, the reference, the section, the page and
    the effective date — and carries the content hash, so a reader can prove
    the sentence came out of the document that is on file rather than out of a
    later edit of it.
    """

    circular_id: str
    reference: str
    regulator: str
    section_number: str = ""
    page: int = 0
    effective: str = ""
    content_hash: str = ""
    quote: str = ""
    rule_id: str = ""

    def sentence(self) -> str:
        where = f", section {self.section_number}" if self.section_number \
            else (f", page {self.page}" if self.page else "")
        when = f", effective {self.effective}" if self.effective else ""
        return f"{self.regulator} {self.reference}{where}{when}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {"circular_id": self.circular_id, "reference": self.reference,
                "regulator": self.regulator,
                "section_number": self.section_number, "page": self.page,
                "effective": self.effective,
                "content_hash": self.content_hash, "quote": self.quote,
                "rule_id": self.rule_id, "sentence": self.sentence()}


class RegulatoryError(Exception):
    """An upload or an extraction that must not proceed quietly."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/\-]{0,79}$")


def validate(circular: Circular) -> list[str]:
    """Everything wrong with this document's metadata, in one list.

    Returned rather than raised, because a bulk upload of a hundred circulars
    should report all hundred verdicts rather than stop at the first one — the
    person fixing them wants the list, not a queue.
    """
    problems: list[str] = []
    if not circular.circular_id:
        problems.append("a circular needs an id")
    if not circular.title.strip():
        problems.append("a circular needs a title")
    if not circular.regulator.strip():
        problems.append("a circular needs the regulator that issued it")
    if not circular.reference.strip():
        problems.append("a circular needs the regulator's own reference")
    elif not _REFERENCE.match(circular.reference.strip()):
        problems.append(
            f"{circular.reference!r} is not a usable reference: a citation is "
            "built from it and it has to be quotable")
    if circular.effective is None:
        problems.append(
            "a circular needs an effective date — as-of retrieval cannot "
            "place a rule without one, and a rule that cannot be placed in "
            "time will be quoted in the wrong quarter")
    if (circular.issued and circular.effective
            and circular.effective < circular.issued):
        problems.append("a circular cannot take effect before it was issued")
    if (circular.effective and circular.expires
            and circular.expires < circular.effective):
        problems.append("a circular cannot expire before it takes effect")
    if circular.confidentiality not in CONFIDENTIALITY:
        problems.append(
            f"{circular.confidentiality!r} is not a confidentiality class")
    if circular.file_format not in FORMATS:
        problems.append(
            f"{circular.file_format!r} is not a supported format: "
            + ", ".join(FORMATS))
    if not circular.content_hash:
        problems.append("a circular needs the hash of the original it came "
                        "from")
    return problems


__all__ = [
    "APPROVED", "CANDIDATE", "CONFIDENTIALITY", "CONFIDENTIALITY_MEANS",
    "CONFIDENTIAL", "CSV", "Circular", "Citation", "DEFINITION",
    "DOCUMENT_STATUSES", "DOCX", "EXCEPTION", "EXTENSIONS", "EXTRACTED",
    "EXTRACTION_UNAVAILABLE", "FORMATS", "HTML", "IN_REVIEW", "NEEDS_OCR",
    "OBLIGATION", "PDF", "PUBLIC", "Page", "REGULATORY_SCHEMA_VERSION",
    "REJECTED", "RESTRICTED", "RETRIEVABLE_STATUSES", "REVIEWED",
    "RULE_KINDS", "RULE_MEANS", "RULE_STATUSES", "RegulatoryError", "Rule",
    "SHAREABLE", "STATUS_MEANS", "SUPERSEDED", "Section", "THRESHOLD", "TXT",
    "UPLOADED", "WITHDRAWN", "XLSX", "format_of", "sha256_of", "validate",
]
