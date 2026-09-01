"""Recognising a question about the data from a question about the book.

The defect this fixes
---------------------
"How many datasets are in the IFRS 9 data domain? List them." was answered
with "20,500 count of connected group size at Q2 2026." Nothing was broken
downstream — the analytical planner did exactly what it is for. It should
never have been asked. The words "how many" and a domain name were enough to
look like a count over the portfolio, and no earlier stage said otherwise.

So this module reads the question first, and it reads it for one thing: is the
SUBJECT of this sentence the bank's data, or the bank's borrowers? "How many
datasets are in IFRS 9" and "how many borrowers are in Stage 2" are the same
English shape and completely different requests, and the difference is the
noun, not the verb.

Deliberately deterministic
--------------------------
No model is asked. A catalogue question has a right answer that is already
known, so spending a model call to discover that is both slower and less
reliable than a regular expression over a closed vocabulary — and §16 is
explicit that a question answerable from metadata must not reach a frontier
model at all. `read()` returns None the moment it is not confident, and the
ordinary analytical path takes over, so the failure mode of this module is
the behaviour that existed before it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

QUESTIONS_VERSION = "1.0.0"


class Kind:
    """What a metadata question is asking for."""

    DOMAIN_LIST = "DOMAIN_LIST"          # which domains exist, how many
    DOMAIN_DETAIL = "DOMAIN_DETAIL"      # what is in one named domain
    DATASET_LIST = "DATASET_LIST"        # which datasets exist, how many
    DATASET_DETAIL = "DATASET_DETAIL"    # grain, purpose, keys of one dataset
    FIELD_LIST = "FIELD_LIST"            # what fields a dataset has
    FIELD_MEANING = "FIELD_MEANING"      # what one field or term means
    PERIODS = "PERIODS"                  # which periods, how much history
    ROW_COUNT = "ROW_COUNT"              # how many rows
    RELATIONSHIP = "RELATIONSHIP"        # how two datasets join
    SUBJECT = "SUBJECT"                  # what data exists about a subject
    PLANNING = "PLANNING"                # what data WOULD be needed for X
    TOTALS = "TOTALS"                    # the catalogue at a glance


ALL: tuple[str, ...] = (
    Kind.DOMAIN_LIST, Kind.DOMAIN_DETAIL, Kind.DATASET_LIST,
    Kind.DATASET_DETAIL, Kind.FIELD_LIST, Kind.FIELD_MEANING, Kind.PERIODS,
    Kind.ROW_COUNT, Kind.RELATIONSHIP, Kind.SUBJECT, Kind.PLANNING,
    Kind.TOTALS,
)


@dataclass(frozen=True)
class Request:
    """One metadata question, read."""

    kind: str
    question: str
    #: The domain, dataset, field or subject the question is about.
    subject: str = ""
    #: A second dataset, for relationship questions.
    other: str = ""
    why: str = ""
    confidence: float = 0.0
    matched: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "subject": self.subject,
                "other": self.other, "why": self.why,
                "confidence": self.confidence, "matched": list(self.matched)}


# ---------------------------------------------------------------- vocabulary

#: The nouns that make a sentence about the CATALOGUE rather than the book.
#: This is the whole distinction, so the list is explicit and closed.
CATALOGUE_NOUNS = (
    "data domain", "data domains", "business domain", "business domains",
    "domain", "domains", "dataset", "datasets", "data set", "data sets",
    "table", "tables", "data source", "data sources", "source system",
    "catalogue", "catalog", "data dictionary", "dictionary",
    "field", "fields", "column", "columns", "attribute", "attributes",
    "schema", "grain", "primary key", "primary keys", "join key",
    "data model", "data coverage", "data you have", "data do you have",
    "data available", "data is available", "data exists",
)

_CATALOGUE = re.compile(
    r"\b(?:" + "|".join(re.escape(n) for n in sorted(
        CATALOGUE_NOUNS, key=len, reverse=True)) + r")\b", re.IGNORECASE)

#: Nouns that make a sentence about the BOOK. When one of these is what is
#: being counted, this is an analysis however catalogue-ish the rest reads.
BOOK_NOUNS = (
    "borrower", "borrowers", "customer", "customers", "client", "clients",
    "counterparty", "counterparties", "facility", "facilities", "account",
    "accounts", "obligor", "obligors", "loan", "loans", "exposure",
    "exposures", "name", "names", "entity", "entities", "group", "groups",
    "case", "cases", "breach", "breaches", "signal", "signals",
)

_COUNTING_BOOK = re.compile(
    r"\bhow many\b[^?.]{0,40}?\b(?:" + "|".join(BOOK_NOUNS) + r")\b",
    re.IGNORECASE)

#: "Which borrowers were downgraded…", "Which sectors deteriorated…". The
#: subject of the sentence is the book, and no amount of period vocabulary
#: later in it makes the question one about the catalogue.
_ASKING_ABOUT_THE_BOOK = re.compile(
    r"\b(?:which|what|show|list|find|identify|rank|name)\b\s+"
    r"(?:the\s+|all\s+|every\s+|top\s+\d+\s+|\d+\s+)?"
    r"(?:" + "|".join(BOOK_NOUNS) + r"|sectors?|regions?|segments?|"
    r"industries|industry|grades?|ratings?|stages?)\b",
    re.IGNORECASE)

_DOMAIN_WORD = re.compile(r"\b(?:data |business )?domains?\b", re.IGNORECASE)
_DATASET_WORD = re.compile(
    r"\b(?:datasets?|data sets?|tables?|data sources?)\b", re.IGNORECASE)
_FIELD_WORD = re.compile(
    r"\b(?:fields?|columns?|attributes?)\b", re.IGNORECASE)

_HOW_MANY = re.compile(r"\bhow many\b|\bhow much\b|\bcount of\b|\bnumber of\b",
                       re.IGNORECASE)
_LISTY = re.compile(
    r"\b(?:list|show|name|tell me|give me|what|which|enumerate|describe|"
    r"explain)\b",
    re.IGNORECASE)

_PLANNING = re.compile(
    # Both word orders. "which datasets would you need" and "which datasets
    # you would need" are the same question, and only the first was read —
    # which is why "Before answering anything, tell me which data domains and
    # datasets you would need…" came back as a plain list of domains.
    r"\b(?:would|will|do)\s+(?:you|we|i)\s+need\b"
    r"|\b(?:you|we|i)\s+(?:would|will|d)\s*(?:ould)?\s*need\b"
    r"|\b(?:is|are)\s+(?:required|needed)\b"
    r"|\bwhat\s+(?:data|domains?|datasets?)\s+(?:is|are)\s+"
    r"(?:required|needed)\b",
    re.IGNORECASE)

#: Bare "data" — not a catalogue noun on its own, because "the data says X" is
#: an analysis, but enough to confirm a planning question is about the
#: catalogue rather than about a deadline.
_DATA_WORD = re.compile(r"\bdata\b|\binformation\b", re.IGNORECASE)

# Deliberately a list of SHAPES rather than "a question mentioning a quarter".
# The loose version caught "Which sectors deteriorated the most this quarter?"
# and "What is the average ECL coverage by rating grade?" — one names a period
# as a filter, the other contains the word "coverage", which is a governed
# MEASURE here as well as a property of a dataset. A period question asks about
# the periods; a book question mentions one.
_PERIODS = re.compile(
    r"\bwhat\s+periods?\b|\bwhich\s+periods?\b"
    r"|\bwhat\s+quarters?\b|\bwhich\s+quarters?\b"
    r"|\b(?:periods?|quarters?|years?|history)\s+(?:is|are|does|do)\s+"
    r"[\w\s]{0,30}\b(?:published|available|covered|loaded)\b"
    r"|\bhow\s+much\s+history\b|\bhow\s+far\s+back\b"
    # "What is the latest period?" asks about the window. "…in the latest
    # period" USES it, and reading the second as the first captured "For each
    # rating grade, show average ECL coverage … in the latest period" as a
    # catalogue question and never ran the analysis.
    r"|\b(?:what|which)\s+(?:is|was|are|were)\s+the\s+"
    r"(?:earliest|latest|first|last)\s+period\b"
    r"|^\s*(?:the\s+)?(?:earliest|latest|first|last)\s+period\s*\??$"
    r"|\bdata\s+(?:cover|covers|go|goes)\s+(?:back\s+)?"
    r"|\bperiod\s+coverage\b|\btime\s+series\s+length\b",
    re.IGNORECASE)

#: "How many quarters of DPD history are there?" needs no named dataset to be
#: a coverage question. Counting PERIODS is never counting borrowers, whatever
#: the rest of the sentence mentions, so this shape stands on its own.
_PERIOD_COUNT = re.compile(
    r"\bhow (?:many|much)\s+(?:quarters?|periods?|years?|months?|history)\b"
    r"|\bhow many\s+\w+\s+(?:quarters?|periods?|years?|months?)\b"
    r"|\bhow far back\b",
    re.IGNORECASE)

_ROWS = re.compile(
    r"\bhow many rows?\b|\bhow many records?\b|\brow count\b|\bhow big\b"
    r"|\bhow many observations?\b|\bvolume of (?:data|records)\b",
    re.IGNORECASE)

_GRAIN = re.compile(
    r"\bgrain\b|\bwhat does (?:one|a|each) row\b[^?]{0,40}"
    r"\b(?:represent|mean)\b"
    r"|\bunit of (?:analysis|observation)\b|\bprimary keys?\b"
    r"|\bwhat is (?:one|a) row\b",
    re.IGNORECASE)

_MEANING = re.compile(
    r"\bwhat does\b[^?]{0,40}\bmean\b|\bdefinition of\b|\bwhat is meant by\b"
    r"|\bmeaning of\b|\bhow is\b[^?]{0,40}\bdefined\b|\bwhat counts as\b",
    re.IGNORECASE)

_JOIN = re.compile(
    r"\bhow (?:is|are|does|do)\b[^?]{0,60}\b(?:connect|link|relate|join)"
    r"|\bjoin(?:ed)? (?:key|path|to|with)\b|\brelationship between\b"
    r"|\bhow (?:would|do|should) (?:you|i|we) join\b|\bjoin\b[^?]{0,40}\bto\b"
    r"|\b(?:connected|linked|related|joined) to\b",
    re.IGNORECASE)

_ABOUT = re.compile(
    r"\bwhat data (?:do you have|is there|exists|is available|have you)\b"
    r"|\bdo you have (?:any )?data\b|\bwhat (?:do you|can you) (?:know|see|"
    r"read|access)\b|\bis there (?:any )?data\b|\bwhat information\b",
    re.IGNORECASE)

_TOTALS = re.compile(
    r"\bwhat data do you have\b\s*[?.]?\s*$"
    r"|\bwhat (?:is|does) (?:the |your )?(?:catalogue|catalog)\b"
    r"|\bsummar(?:y|ise|ize)\b[^?]{0,30}\b(?:catalogue|catalog|data)\b"
    r"|\bwhat data (?:is|are) (?:installed|loaded|available)\b\s*[?.]?\s*$",
    re.IGNORECASE)

#: Phrases that mean "about a subject" and should be stripped before the
#: remainder is treated as the subject.
_STRIP = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+|)"
    r"(?:before answering(?: anything)?,?\s*)?"
    r"(?:tell me|show me|give me|list|name|enumerate|what|which|how many|"
    r"how much|explain|describe)\s+",
    re.IGNORECASE)


def _subject_after(text: str, marker: str) -> str:
    """What follows 'about', 'on', 'for' — the thing being asked about."""
    found = re.search(
        rf"\b{marker}\b\s+(?:the\s+)?(.+?)(?:\?|\.|$)", text, re.IGNORECASE)
    return found.group(1).strip() if found else ""


def _named_domain(text: str) -> str:
    """A domain named in the sentence, matched against the real headings."""
    from backend.metadata import service as svc

    lowered = text.lower()
    # An explicit "<name> domain" or "domain <name>" first.
    explicit = re.search(
        r"\b(?:in|of|for|under|from)\s+(?:the\s+)?([\w\s/&.\-]{2,40}?)\s+"
        r"(?:data\s+|business\s+)?domain\b", text, re.IGNORECASE)
    if explicit:
        found = svc.domain(explicit.group(1))
        if found is not None:
            return found.name
    trailing = re.search(
        r"\bdomain\s+(?:called\s+|named\s+)?[\"']?([\w\s/&.\-]{2,40}?)"
        r"[\"']?(?:\?|\.|,|$)", text, re.IGNORECASE)
    if trailing:
        found = svc.domain(trailing.group(1))
        if found is not None:
            return found.name
    # Otherwise, a heading whose own name appears in the sentence.
    best = ""
    for heading in svc.domains():
        name = heading.name.lower()
        if name in lowered:
            if len(name) > len(best):
                best = heading.name
        else:
            # "IFRS 9" for "IFRS 9 / ECL"; the leading part of a slashed name.
            head = name.split("/")[0].strip()
            if len(head) > 3 and head in lowered and len(head) > len(best):
                best = heading.name
    return best


def _named_dataset(text: str) -> str:
    """A governed dataset named in the sentence."""
    from backend.metadata import service as svc

    lowered = f" {text.lower()} "
    best = ""
    for found in svc.catalogue().datasets:
        for candidate in (found.name.lower(),
                          found.name.lower().replace("_", " "),
                          found.business_name.lower()):
            if len(candidate) < 4:
                continue
            if re.search(rf"(?<![\w]){re.escape(candidate)}(?![\w])", lowered):
                if len(candidate) > len(best):
                    best = found.name
    return best


def _two_datasets(text: str) -> tuple[str, str]:
    from backend.metadata import service as svc

    lowered = f" {text.lower()} "
    hits: list[tuple[int, str]] = []
    for found in svc.catalogue().datasets:
        for candidate in (found.name.lower(),
                          found.name.lower().replace("_", " "),
                          found.business_name.lower()):
            if len(candidate) < 4:
                continue
            where = re.search(
                rf"(?<![\w]){re.escape(candidate)}(?![\w])", lowered)
            if where:
                hits.append((where.start(), found.name))
                break
    hits.sort()
    names: list[str] = []
    for _, name in hits:
        if name not in names:
            names.append(name)
    return (names[0] if names else "", names[1] if len(names) > 1 else "")


def _subject(text: str) -> str:
    """What the question is about, with the asking stripped off the front."""
    for marker in ("about", "regarding", "concerning", "on the subject of"):
        found = _subject_after(text, marker)
        if found:
            return found
    stripped = _STRIP.sub("", text.strip()).strip(" ?.")
    return stripped


def read(question: str) -> Request | None:
    """The metadata question this is, or None if it is not one.

    Order matters. The most specific readings are tried first, because "how
    many fields does the ratings dataset have" satisfies several patterns and
    only one of them is the question.
    """
    text = " ".join(str(question or "").split())
    if not text:
        return None

    # A question counting BORROWERS is an analysis even when it names a
    # dataset: "how many customers are in the ratings data" is a count over
    # the book. This test comes first because everything below would claim it.
    if _COUNTING_BOOK.search(text):
        return None

    # ...and one whose subject is the book, unless it also names something in
    # the catalogue: "which datasets carry borrower ratings?" is about the
    # catalogue; "which borrowers were downgraded?" is about the book.
    if _ASKING_ABOUT_THE_BOOK.search(text) and not _CATALOGUE.search(text):
        return None

    catalogue_word = _CATALOGUE.search(text)
    dataset_named = _named_dataset(text)
    domain_named = _named_domain(text)

    # --- what data WOULD be needed. Asked before anything is computed, and
    # the acceptance run's example of a question that returned nothing at all.
    if _PLANNING.search(text) and (catalogue_word or _ABOUT.search(text)
                                   or _DATA_WORD.search(text)):
        subject = _subject_for_planning(text)
        return Request(kind=Kind.PLANNING, question=text, subject=subject,
                       why="It asks which data would be needed, before any is read.",
                       confidence=0.9, matched=("planning",))

    # --- how two datasets connect
    if _JOIN.search(text) and (dataset_named or catalogue_word):
        left, right = _two_datasets(text)
        return Request(kind=Kind.RELATIONSHIP, question=text,
                       subject=left or dataset_named, other=right,
                       why="It asks how two governed datasets connect.",
                       confidence=0.85, matched=("join",))

    # --- what a field or term means
    if _MEANING.search(text) and (dataset_named or _FIELD_WORD.search(text)
                                  or _field_named(text)):
        return Request(kind=Kind.FIELD_MEANING, question=text,
                       subject=_field_named(text) or _subject(text),
                       other=dataset_named,
                       why="It asks what a governed field means.",
                       confidence=0.8, matched=("meaning",))

    # --- grain and keys
    if _GRAIN.search(text) and dataset_named:
        return Request(kind=Kind.DATASET_DETAIL, question=text,
                       subject=dataset_named,
                       why="It asks what one row of a governed dataset is.",
                       confidence=0.9, matched=("grain",))

    # --- rows
    if _ROWS.search(text) and (dataset_named or domain_named or catalogue_word):
        return Request(kind=Kind.ROW_COUNT, question=text,
                       subject=dataset_named or domain_named,
                       why="It asks how much data is published, not what it says.",
                       confidence=0.85, matched=("rows",))

    # --- periods and history
    field_named = _field_named(text)
    if _PERIOD_COUNT.search(text) or (
            _PERIODS.search(text) and (dataset_named or domain_named
                                       or catalogue_word or field_named)):
        return Request(kind=Kind.PERIODS, question=text,
                       subject=dataset_named or domain_named or field_named,
                       why="It asks which reporting periods are published.",
                       confidence=0.85, matched=("periods",))

    # --- fields of a dataset
    if _FIELD_WORD.search(text) and (dataset_named or domain_named):
        return Request(kind=Kind.FIELD_LIST, question=text,
                       subject=dataset_named or domain_named,
                       why="It asks which governed fields exist.",
                       confidence=0.85, matched=("fields",))

    # --- one dataset, described
    if dataset_named and _LISTY.search(text) and not _DOMAIN_WORD.search(text):
        if _DATASET_WORD.search(text) or _ABOUT.search(text):
            return Request(kind=Kind.DATASET_DETAIL, question=text,
                           subject=dataset_named,
                           why="It asks about one governed dataset.",
                           confidence=0.8, matched=("dataset",))

    # --- a named domain
    if domain_named and (_DOMAIN_WORD.search(text) or _DATASET_WORD.search(text)):
        return Request(kind=Kind.DOMAIN_DETAIL, question=text,
                       subject=domain_named,
                       why="It asks what is installed under one data domain.",
                       confidence=0.9, matched=("domain",))

    # --- every domain
    if _DOMAIN_WORD.search(text) and (_HOW_MANY.search(text)
                                      or _LISTY.search(text)):
        return Request(kind=Kind.DOMAIN_LIST, question=text,
                       why="It asks which data domains exist.",
                       confidence=0.9, matched=("domains",))

    # --- every dataset
    if _DATASET_WORD.search(text) and (_HOW_MANY.search(text)
                                       or _LISTY.search(text)):
        return Request(kind=Kind.DATASET_LIST, question=text,
                       subject=domain_named,
                       why="It asks which governed datasets exist.",
                       confidence=0.9, matched=("datasets",))

    # --- the catalogue at a glance
    if _TOTALS.search(text):
        return Request(kind=Kind.TOTALS, question=text,
                       why="It asks what data the deployment holds.",
                       confidence=0.8, matched=("totals",))

    # --- what data exists about a subject
    if _ABOUT.search(text):
        return Request(kind=Kind.SUBJECT, question=text,
                       subject=_subject(text),
                       why="It asks what governed data bears on a subject.",
                       confidence=0.8, matched=("about",))

    return None


_FIELD_NAMES: tuple[str, ...] = ()


def _field_named(text: str) -> str:
    """A governed field named in the sentence."""
    from backend.metadata import service as svc

    lowered = f" {text.lower()} "
    best = ""
    for found in svc.catalogue().datasets:
        for declared in found.fields:
            for candidate in (declared.name.lower(),
                              declared.name.lower().replace("_", " "),
                              declared.business_name.lower()):
                # Three letters is short enough to collide with ordinary
                # English, so only the field's own governed NAME qualifies at
                # that length — "ead", "lgd", "pd" are the vocabulary a credit
                # officer actually types, and excluding them sent "what does
                # LGD mean?" to the analytical planner.
                if len(candidate) < 3 or (
                        len(candidate) < 4
                        and candidate != declared.name.lower()):
                    continue
                if re.search(rf"(?<![\w]){re.escape(candidate)}(?![\w])",
                             lowered) and len(candidate) > len(best):
                    best = declared.name
    return best


def _subject_for_planning(text: str) -> str:
    """What the planning question wants the data FOR."""
    found = re.search(
        r"\bto\s+(?:assess|analyse|analyze|evaluate|understand|measure|"
        r"answer|investigate|review|monitor|compute|calculate|produce|"
        r"build|model|report)\s+(.+?)(?:\?|\.|$)",
        text, re.IGNORECASE)
    if found:
        return found.group(1).strip()
    for marker in ("about", "for", "regarding"):
        got = _subject_after(text, marker)
        if got:
            return got
    return _subject(text)


__all__ = ["ALL", "BOOK_NOUNS", "CATALOGUE_NOUNS", "QUESTIONS_VERSION",
           "Kind", "Request", "read"]
