"""
Business concepts, and which governed field actually supplies them.

The gap this closes
-------------------
A credit officer asks about "ECL", "the rating", "exposure". None of those is a
column. Several of them exist in more than one governed dataset with genuinely
different meanings — `portfolio_facility.ead` is the operational exposure the
book carries, `ifrs9_staging.ead` is the figure the impairment calculation was
run on, and answering an impairment question from the operational number is the
kind of mistake that survives every review because both numbers are correct.

So a concept is resolved rather than guessed:

  1. the phrase is matched to a concept — "ECL", "impairment", "provision" all
     mean the same thing;
  2. the concept's candidate fields are read from the governed catalogue, so a
     concept can never resolve to a field the data does not have;
  3. a qualifier in the question picks between candidates where one exists —
     "regulatory EAD" is not "outstanding exposure";
  4. where no qualifier settles it, the catalogue's own authority metadata
     decides, and the choice is RECORDED so the answer can say which definition
     it used;
  5. where authority does not settle it either, CreditProbe asks. A confident
     figure computed from the wrong definition of exposure is the exact failure
     this product exists to prevent.

Nothing here reads data. It reads the catalogue and returns names.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

FACILITY = "portfolio_facility"
IFRS9 = "ifrs9_staging"
RATINGS = "customer_ratings"
DELINQUENCY = "facility_delinquency"
COVENANTS = "covenant_tests"
MACRO = "macro_saudi"
MEMOS = "credit_memo_signals"
FINANCIALS = "borrower_financials"


@dataclass(frozen=True)
class Candidate:
    """One governed field that can supply a concept."""

    dataset: str
    field: str
    #: Why this one rather than the other. Shown when the choice is explained.
    definition: str
    #: The word in a question that selects this candidate over its rivals.
    qualifiers: tuple[str, ...] = ()
    #: The candidate used when nothing in the question chooses.
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "field": self.field,
                "definition": self.definition,
                "qualifiers": list(self.qualifiers), "is_default": self.is_default}


@dataclass(frozen=True)
class Concept:
    """One thing a credit officer talks about."""

    id: str
    label: str
    #: What people call it. Matched longest-first so "expected credit loss"
    #: beats "credit".
    pattern: str
    candidates: tuple[Candidate, ...]
    #: True where a HIGHER number is worse. Decides which way "deteriorated"
    #: points, and getting it wrong inverts the answer.
    higher_is_worse: bool = True
    #: An ordinal scale rather than a measure: movement is counted in steps,
    #: never averaged, and rolled up by its worst value.
    is_ordinal: bool = False
    #: A governed category rather than a quantity. Compared by equality and
    #: never differenced — subtracting one sentiment from another is not a
    #: smaller number, it is a type error waiting for a production question.
    is_categorical: bool = False
    #: The values a polarity word maps onto, for a categorical concept.
    polarity: tuple[tuple[str, str], ...] = ()
    unit: str = ""

    def default_candidate(self) -> Candidate:
        for candidate in self.candidates:
            if candidate.is_default:
                return candidate
        return self.candidates[0]


def _c(dataset: str, field_: str, definition: str, *qualifiers: str,
       default: bool = False) -> Candidate:
    return Candidate(dataset=dataset, field=field_, definition=definition,
                     qualifiers=tuple(qualifiers), is_default=default)


#: The concepts CreditProbe understands, and where each one lives.
#:
#: Deliberately hand-written. A concept map derived from column names would map
#: "ead" to every dataset carrying a column of that name and would have no
#: opinion about which one an impairment question means — which is the entire
#: value of having one.
CONCEPTS: tuple[Concept, ...] = (
    Concept(
        id="ecl", label="expected credit loss",
        pattern=r"expected credit loss|\becl\b|impairment|provision(?:ing)?",
        unit="USD mn",
        candidates=(
            _c(IFRS9, "total_ecl",
               "The impairment charge as the IFRS 9 calculation booked it. The "
               "accounting figure, and the one an impairment question means.",
               "ifrs9", "ifrs 9", "accounting", "booked", "impairment",
               default=True),
            _c(FACILITY, "total_ecl",
               "The ECL carried on the facility position. The same measure "
               "read from the operational book rather than the staging run.",
               "operational", "facility", "portfolio"),
        )),
    Concept(
        id="ecl_coverage", label="ECL coverage",
        pattern=r"ecl coverage|coverage ratio|provision coverage",
        higher_is_worse=False, unit="%",
        candidates=(
            _c(IFRS9, "ecl_coverage_pct", "ECL as a percentage of exposure at "
               "default, from the staging run.", default=True),
            _c(FACILITY, "ecl_coverage_pct",
               "Coverage as carried on the facility position."),
        )),
    Concept(
        id="ead", label="exposure at default",
        pattern=r"exposure at default|\bead\b",
        unit="USD mn",
        candidates=(
            _c(FACILITY, "ead",
               "CCF-adjusted exposure at default on the facility position — "
               "the operational figure the book is managed on.",
               "outstanding", "operational", "facility", "portfolio", "managed",
               default=True),
            _c(IFRS9, "ead",
               "Exposure at default as the impairment calculation used it. The "
               "regulatory and accounting figure.",
               "regulatory", "ifrs9", "ifrs 9", "accounting", "impairment"),
        )),
    Concept(
        id="exposure", label="drawn exposure",
        pattern=r"drawn exposure|outstanding balance|\bexposure\b(?! at default)",
        unit="USD mn",
        candidates=(
            _c(FACILITY, "exposure",
               "Drawn, outstanding exposure on the facility position.",
               "outstanding", "drawn", "operational", default=True),
            _c(FACILITY, "ead",
               "CCF-adjusted exposure at default, which includes an allowance "
               "for undrawn commitments.", "at default", "ccf", "committed"),
            _c(IFRS9, "ead",
               "Exposure as the impairment calculation used it.",
               "regulatory", "ifrs9", "ifrs 9"),
        )),
    Concept(
        id="rating", label="internal rating",
        pattern=r"internal rating|risk rating|\brating\b|\bgrade\b|\bnotch(?:es)?\b|downgrad\w*|upgrad\w*",
        is_ordinal=True, unit="notches",
        candidates=(
            _c(RATINGS, "internal_grade",
               "The grade awarded at the customer's annual rating cycle. One "
               "to ten, ten being default. The authoritative rating of a "
               "borrower.",
               "customer", "obligor", "borrower", "annual", "cycle",
               default=True),
            _c(FACILITY, "internal_grade",
               "The grade carried on the facility position at the reporting "
               "date. The same scale, read from the quarterly book.",
               "facility", "account", "quarterly", "snapshot"),
        )),
    Concept(
        id="stage", label="IFRS 9 stage",
        pattern=r"ifrs\s*9\s*stage|\bstage\s*[123]?\b|staging",
        is_ordinal=True,
        candidates=(
            _c(IFRS9, "ifrs9_stage",
               "The staging decision from the IFRS 9 assessment.", default=True),
            _c(FACILITY, "ifrs9_stage",
               "The stage carried on the facility position."),
        )),
    Concept(
        id="dpd", label="days past due",
        pattern=r"days past due|\bdpd\b|arrears|delinquen|past due|overdue",
        unit="days",
        candidates=(
            _c(DELINQUENCY, "days_past_due",
               "Days the oldest unpaid amount has been outstanding, from the "
               "arrears and collections record.",
               "arrears", "collections", "delinquency", default=True),
            _c(FACILITY, "dpd_days",
               "Days past due as carried on the facility position."),
        )),
    Concept(
        id="pd", label="probability of default",
        pattern=r"\bpd\b|probability of default",
        unit="%",
        candidates=(
            _c(IFRS9, "pd_12m_pct",
               "The twelve-month PD the staging assessment used.", default=True),
            _c(FACILITY, "pd_12m_pct", "The PD carried on the facility position."),
            _c(RATINGS, "pd_12m_pct", "The PD implied by the customer's grade.",
               "customer", "rating"),
        )),
    Concept(
        id="lgd", label="loss given default",
        pattern=r"\blgd\b|loss given default", unit="%",
        candidates=(
            _c(IFRS9, "lgd_pct", "LGD as the impairment calculation used it.",
               default=True),
            _c(FACILITY, "lgd_pct", "LGD carried on the facility position."),
        )),
    Concept(
        id="leverage", label="net leverage",
        pattern=r"leverage|gearing|debt to ebitda|net debt", unit="x",
        candidates=(
            _c(RATINGS, "net_leverage",
               "Net debt to EBITDA from the financials behind the rating "
               "cycle.", default=True),
        )),
    Concept(
        id="interest_cover", label="interest coverage",
        pattern=r"interest cover(?:age)?|ebitda to interest", unit="x",
        higher_is_worse=False,
        candidates=(_c(RATINGS, "interest_coverage",
                       "EBITDA to interest from the rating cycle financials.",
                       default=True),)),
    Concept(
        id="margin", label="EBITDA margin",
        pattern=r"ebitda margin|profitability margin", unit="%",
        higher_is_worse=False,
        candidates=(_c(RATINGS, "ebitda_margin_pct",
                       "EBITDA as a share of revenue, from the rating cycle.",
                       default=True),)),
    Concept(
        id="covenant_headroom", label="covenant headroom",
        pattern=r"covenant headroom|headroom|covenant breach|covenant",
        higher_is_worse=False, unit="%",
        candidates=(
            _c(COVENANTS, "headroom_pct",
               "Distance to the covenant threshold, per covenant tested.",
               "covenant", "breach", "test", default=True),
            _c(FACILITY, "covenant_headroom_pct",
               "Covenant headroom as summarised on the facility position."),
        )),
    Concept(
        id="utilisation", label="utilisation",
        pattern=r"utilisation|utilization|drawn percentage", unit="%",
        candidates=(_c(FACILITY, "utilisation_pct",
                       "Drawn exposure as a share of the limit.", default=True),)),
    Concept(
        id="macro_growth", label="economic growth",
        pattern=r"gdp|economic growth|macro(?:economic)?\s*(?:environment|conditions)?",
        higher_is_worse=False, unit="%",
        candidates=(
            _c(MACRO, "real_gdp_growth_pct",
               "Real GDP growth for the quarter.", "gdp", "growth", default=True),
            _c(MACRO, "credit_cycle_factor",
               "The credit cycle factor derived from the macro series.",
               "cycle", "credit cycle"),
        )),
    Concept(
        id="macro_cycle", label="credit cycle",
        pattern=r"credit cycle|cycle factor|macro environment",
        higher_is_worse=False,
        candidates=(_c(MACRO, "credit_cycle_factor",
                       "The credit cycle factor derived from the macro series. "
                       "Positive is a supportive environment.", default=True),)),
    Concept(
        id="sentiment", label="credit file sentiment",
        pattern=r"sentiment|qualitative|credit file|memo|commentary|narrative",
        higher_is_worse=False, is_categorical=True,
        polarity=(("negative", "negative"), ("adverse", "negative"),
                  ("positive", "positive"), ("favourable", "positive"),
                  ("favorable", "positive")),
        candidates=(_c(MEMOS, "sentiment",
                       "The sentiment of the credit file note, as a structured "
                       "signal — negative, neutral or positive. Never the text "
                       "itself.", default=True),)),
    Concept(
        id="signal_strength", label="credit file signal strength",
        pattern=r"signal strength|concern level|red flag",
        candidates=(_c(MEMOS, "signal_strength_pct",
                       "How strong the structured signal from the credit file "
                       "is.", default=True),)),
)

#: Sorted longest-pattern-first so a specific phrase wins over a general one.
_ORDERED = tuple(sorted(CONCEPTS, key=lambda c: -len(c.pattern)))


@dataclass
class ConceptMatch:
    """One concept found in a question, and the field chosen for it."""

    concept: Concept
    candidate: Candidate
    phrase: str = ""
    confidence: float = 1.0
    #: Other candidates that were available. Empty when there was no choice.
    alternatives: tuple[Candidate, ...] = ()
    #: What settled the choice, in the words the answer will use.
    reason: str = ""
    #: Set when CreditProbe should ask rather than choose.
    needs_clarification: bool = False

    @property
    def dataset(self) -> str:
        return self.candidate.dataset

    @property
    def field(self) -> str:
        return self.candidate.field

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept.id,
            "label": self.concept.label,
            "phrase": self.phrase,
            "dataset": self.dataset,
            "field": self.field,
            "definition": self.candidate.definition,
            "unit": self.concept.unit,
            "is_ordinal": self.concept.is_ordinal,
            "is_categorical": self.concept.is_categorical,
            "higher_is_worse": self.concept.higher_is_worse,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "alternatives": [c.to_dict() for c in self.alternatives],
            "needs_clarification": self.needs_clarification,
        }


def _available(candidate: Candidate, known: dict[str, set[str]]) -> bool:
    """Whether the governed catalogue actually carries this field."""
    return candidate.field in known.get(candidate.dataset, set())


def _authority_rank(dataset: str, catalogue: Any) -> int:
    """How authoritative a dataset is — more governed purposes served, higher.

    Read from the catalogue rather than hard-coded, so a bank that makes its own
    dataset authoritative for the facility position changes what a concept
    resolves to without anybody editing this file.
    """
    try:
        return len(catalogue.dataset(dataset).authoritative_for)
    except Exception:
        return 0


def _is_client_authority(dataset: str, catalogue: Any) -> bool:
    """Whether this is the bank's own data, declared authoritative.

    The demonstration book exists so the product can be seen working. Once a
    bank has onboarded its own dataset and a steward has declared it
    authoritative for the same governed purpose, answering from the demo book
    would be a correct calculation over the wrong company's portfolio — which
    is worse than refusing, because it looks right.
    """
    try:
        definition = catalogue.dataset(dataset)
    except Exception:
        return False
    return (str(getattr(definition, "origin", "")) == "client"
            and bool(getattr(definition, "authoritative_for", ())))


def _client_authority_over(chosen: Candidate, usable: list[Candidate],
                           catalogue: Any) -> Candidate | None:
    """The bank's own authoritative source, where it outranks the default.

    Returns None unless exactly one candidate qualifies: two client datasets
    both declared authoritative for the same concept is a governance question
    for a steward, not a tie the planner should break on its own.
    """
    if catalogue is None:
        return None
    client = [c for c in usable if _is_client_authority(c.dataset, catalogue)]
    if len(client) != 1 or client[0] is chosen:
        return None
    if _is_client_authority(chosen.dataset, catalogue):
        return None
    return client[0]


def resolve_concept(concept: Concept, question: str, *,
                    known: dict[str, set[str]], catalogue: Any = None,
                    phrase: str = "") -> ConceptMatch | None:
    """Choose the field this concept means in THIS question."""
    lowered = question.lower()
    usable = [c for c in concept.candidates if _available(c, known)]
    if not usable:
        return None

    # 1. A qualifier in the question settles it outright.
    for candidate in usable:
        for qualifier in candidate.qualifiers:
            if qualifier and qualifier in lowered:
                return ConceptMatch(
                    concept=concept, candidate=candidate, phrase=phrase,
                    confidence=1.0,
                    alternatives=tuple(c for c in usable if c is not candidate),
                    reason=(f"The question says '{qualifier}', which selects "
                            f"{candidate.dataset}.{candidate.field}: "
                            f"{candidate.definition}"))

    if len(usable) == 1:
        return ConceptMatch(
            concept=concept, candidate=usable[0], phrase=phrase, confidence=1.0,
            reason=(f"{usable[0].dataset}.{usable[0].field} is the only "
                    f"governed field carrying {concept.label}."))

    # 2. The declared default, with the alternatives recorded so the answer can
    #    say which definition it used.
    chosen = next((c for c in usable if c.is_default), None)
    if chosen is not None:
        # The bank's own authoritative data beats a default that points at the
        # demonstration book. The default encodes which figure a credit officer
        # usually means; it cannot know that this bank has since onboarded its
        # own source for it.
        client = _client_authority_over(chosen, usable, catalogue)
        if client is not None:
            return ConceptMatch(
                concept=concept, candidate=client, phrase=phrase,
                confidence=0.9,
                alternatives=tuple(c for c in usable if c is not client),
                reason=(f"'{concept.label}' exists in {len(usable)} governed "
                        f"datasets. CreditProbe used {client.dataset}."
                        f"{client.field} because it is the bank's own data and "
                        "a steward has declared it authoritative; the "
                        f"demonstration source {chosen.dataset}.{chosen.field} "
                        "was not used."))
        others = tuple(c for c in usable if c is not chosen)
        catalogue_note = ""
        if catalogue is not None:
            ranks = {c.dataset: _authority_rank(c.dataset, catalogue) for c in usable}
            if ranks.get(chosen.dataset, 0) >= max(ranks.values()):
                catalogue_note = (f" {chosen.dataset} is declared authoritative "
                                  "in the governed catalogue.")
        return ConceptMatch(
            concept=concept, candidate=chosen, phrase=phrase, confidence=0.85,
            alternatives=others,
            reason=(f"'{concept.label}' exists in "
                    f"{len(usable)} governed datasets. CreditProbe used "
                    f"{chosen.dataset}.{chosen.field}: {chosen.definition}"
                    + catalogue_note))

    # 3. Genuinely ambiguous. Ask.
    return ConceptMatch(
        concept=concept, candidate=usable[0], phrase=phrase, confidence=0.4,
        alternatives=tuple(usable[1:]), needs_clarification=True,
        reason=(f"'{concept.label}' could mean any of "
                + ", ".join(f"{c.dataset}.{c.field}" for c in usable)
                + ", and they are different figures."))


@dataclass
class Reading:
    """Every concept found in one question."""

    matches: list[ConceptMatch] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def datasets(self) -> list[str]:
        out: list[str] = []
        for match in self.matches:
            if match.dataset not in out:
                out.append(match.dataset)
        return out

    @property
    def needs_clarification(self) -> list[ConceptMatch]:
        return [m for m in self.matches if m.needs_clarification]

    def by_concept(self, concept_id: str) -> ConceptMatch | None:
        return next((m for m in self.matches if m.concept.id == concept_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"matches": [m.to_dict() for m in self.matches],
                "datasets": self.datasets,
                "unresolved": list(self.unresolved)}


def read_concepts(question: str, *, known: dict[str, set[str]],
                  catalogue: Any = None) -> Reading:
    """Every concept the question names, resolved to a governed field.

    Deterministic. The reading decides which datasets are joined and therefore
    what is computed; a reading that varies between two identical questions
    makes every answer unreproducible, which is the opposite of what this
    product sells.
    """
    reading = Reading()
    text = " ".join(str(question).split())
    seen: set[str] = set()

    for concept in _ORDERED:
        match = re.search(concept.pattern, text, re.IGNORECASE)
        if not match or concept.id in seen:
            continue
        resolved = resolve_concept(concept, text, known=known,
                                   catalogue=catalogue, phrase=match.group(0))
        if resolved is None:
            reading.unresolved.append(
                f"'{match.group(0)}' means {concept.label}, which no governed "
                "dataset in this installation carries.")
            continue
        seen.add(concept.id)
        reading.matches.append(resolved)

    return reading


def catalogue_fields(catalogue: Any) -> dict[str, set[str]]:
    """Every governed dataset and the fields it carries."""
    out: dict[str, set[str]] = {}
    for definition in catalogue.all():
        out[definition.name] = set(definition.fields)
    return out


__all__ = [
    "CONCEPTS",
    "Candidate",
    "Concept",
    "ConceptMatch",
    "Reading",
    "catalogue_fields",
    "read_concepts",
    "resolve_concept",
]
