"""
What one row of the answer IS. §4.

The defect this exists for
---------------------------
    "Show days past due and the NPL ratio for the portfolio at the latest
     published period."

came back as ten account rows. Every figure in them was correct. The question
was about the portfolio and the answer was about ten accounts, which is not a
smaller version of the same answer — it is a different answer, and the reader
who scans the first row reads an account's DPD as the book's.

The invariant caught it, because a ranking that is not in rank order fails an
ordering check, and the presentability gate withheld the table. That is
containment, and containment is not correction: the same planner would have
produced the same wrong grain for a question whose rows happened to come back
sorted, and nothing would have stopped it.

So the grain the ANSWER is at becomes a governed decision, made from the
objective, declared on the plan, shown in Scope and on the Trace, and checked
against the rows before anything is displayed.

Source grain and output grain are different things
---------------------------------------------------
`portfolio_facility` is keyed one row per facility. That is its SOURCE grain
and it never changes. "Total EAD by sector" reads that source and emits one row
per sector — a SEGMENT output grain. The planner used to carry one field called
`grain` meaning the source's key, and reported it as though it described the
answer: a by-sector aggregate declared itself `facility`, which was true of what
it read and false of what it returned.

Both are kept. `AnalysisBuild.grain` stays the source/entity key grain, because
half the planner uses it to pick a key column. `AnalysisBuild.output_grain` is
new and is what the answer is at.

The ladder
-----------
PORTFOLIO < SEGMENT < CUSTOMER < FACILITY < RECORD, coarse to fine. A request
at a coarser grain than its source needs an aggregation; a request at a finer
grain than its source cannot be satisfied at all, and saying so is better than
returning the coarse rows under a fine heading.

PERIOD is deliberately not on the ladder. A time series is a portfolio answer
repeated per period, not a sixth level of entity detail, and putting it on the
ladder would make "EAD by quarter" and "EAD by sector" the same shape when they
are read completely differently.

Why the inference order is what it is
--------------------------------------
Most specific evidence first, and the order is the whole design:

  1. a population the conversation carries — "which of THESE five are Stage 2?"
     is answered per customer whatever dataset it is read from;
  2. an explicit facility noun;
  3. an explicit customer noun;
  4. a resolved breakdown dimension — "by sector" is a segment answer even in a
     sentence that also says "portfolio";
  5. an explicit portfolio noun;
  6. the source dataset's own grain, marked as not explicit.

Rule 4 before rule 5 is what makes "total EAD by sector for the portfolio" a
sector answer. Rule 3 before rule 5 is what makes "the five largest Real Estate
customers in the portfolio" a customer answer. The sentence names both; the
narrower one is the one being asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

GRAIN_VERSION = "1.0.0"

PORTFOLIO = "portfolio"
SEGMENT = "segment"
CUSTOMER = "customer"
FACILITY = "facility"
RECORD = "record"

#: Not on the ladder — see the module docstring.
PERIOD = "period"

#: Coarse to fine. The index IS the level.
LADDER: tuple[str, ...] = (PORTFOLIO, SEGMENT, CUSTOMER, FACILITY, RECORD)
LEVEL: dict[str, int] = {name: index for index, name in enumerate(LADDER)}

GRAINS: frozenset[str] = frozenset(LADDER) | {PERIOD}

#: What one row means, in a sentence a credit officer would accept. Shown in
#: Scope and on the Trace, so the grain is a statement rather than a label.
MEANS: dict[str, str] = {
    PORTFOLIO: "one row for the whole book",
    SEGMENT: "one row per group",
    CUSTOMER: "one row per customer",
    FACILITY: "one row per facility",
    RECORD: "one row per underlying record",
    PERIOD: "one row per period",
}

#: The column that identifies a row at each grain. A portfolio answer has no
#: identifying column, which is not an omission: there is one row and nothing
#: to tell it apart from.
KEY_OF: dict[str, str] = {CUSTOMER: "customer_id", FACILITY: "account_id"}

#: The inverse, including the aliases a carried population may be keyed on.
GRAIN_OF_KEY: dict[str, str] = {
    "customer_id": CUSTOMER,
    "borrower_id": CUSTOMER,
    "account_id": FACILITY,
    "facility_id": FACILITY,
}

_FACILITY_WORDS = re.compile(
    r"\bfacilit(?:y|ies)\b|\baccounts?\b|\bloans?\b|\bexposures? lines?\b|"
    r"\bdrawdowns?\b|\btranches?\b", re.I)

#: `who` and `whose` are borrower words. "Who has both rising utilisation and
#: weakening debt-service capacity?" asks for a list of companies, and with no
#: noun in the sentence it fell through to the source's own grain and answered
#: with five hundred facilities. There is no reading of "who" that means a
#: facility or the whole book.
#:
#: Safe beside the relative pronoun because `_FACILITY_WORDS` is tested first
#: in `requested`: "facilities whose utilisation rose" still resolves to
#: facility, on the explicit noun, before this is consulted.
_CUSTOMER_WORDS = re.compile(
    r"\bcustomers?\b|\bborrowers?\b|\bobligors?\b|\bclients?\b|"
    r"\bcounterpart(?:y|ies)\b|\bnames?\b|\bgroups?\b|"
    r"\bcompan(?:y|ies)\b|\bwho\b|\bwhose\b", re.I)

#: "for the portfolio", "across the book", "overall", "in total". A request for
#: one number about everything.
_PORTFOLIO_WORDS = re.compile(
    r"\bportfolio(?:[- ]level|[- ]wide)?\b|\bwhole book\b|\bthe book\b|"
    r"\bbank[- ]wide\b|\boverall\b|\bin total\b|\baggregate\b|"
    r"\bacross the (?:book|portfolio|bank)\b", re.I)

#: A portfolio noun used as a MODIFIER rather than as the answer's grain.
#: "portfolio EAD by sector" and "the largest portfolio customers" both say
#: portfolio and neither asks for one row. Checked only to stop rule 5 firing
#: where rules 2-4 already had their say, so it is deliberately narrow.
_PORTFOLIO_AS_ADJECTIVE = re.compile(
    r"\bportfolio\s+(?:customers?|borrowers?|facilit|accounts?|names?)", re.I)


@dataclass(frozen=True)
class Requested:
    """The grain the objective asks the answer to be at, and why."""

    grain: str
    #: The sentence shown in Scope and on the Trace.
    because: str
    #: Did the user say it, or is this the dataset's own grain by default?
    explicit: bool = False
    #: Which rule decided: population | facility | customer | dimension |
    #: portfolio | dataset.
    source: str = "dataset"
    #: The breakdown column, for a SEGMENT request.
    dimension: str = ""

    @property
    def level(self) -> int:
        return LEVEL.get(self.grain, LEVEL[FACILITY])

    def keys(self) -> tuple[str, ...]:
        """The columns that must be unique across the rows of the answer."""
        if self.grain == SEGMENT:
            return (self.dimension,) if self.dimension else ()
        key = KEY_OF.get(self.grain, "")
        return (key,) if key else ()

    def to_dict(self) -> dict[str, Any]:
        return {"grain": self.grain, "means": MEANS.get(self.grain, ""),
                "because": self.because, "explicit": self.explicit,
                "source": self.source, "dimension": self.dimension,
                "keys": list(self.keys())}


def requested(text: str, *, dimension: str = "", population_grain: str = "",
              dataset_grain: str = "", rows_requested: bool = False
              ) -> Requested:
    """Infer the output grain from the objective. See the docstring's order.

    `rows_requested` is set when the question named a number of rows — "the
    five largest", "top 10". Asking for five of something is asking for five
    rows, so a portfolio reading is wrong however many portfolio nouns the
    sentence carries, and the request falls through to the source's own grain.
    """
    sentence = text or ""

    if population_grain in LEVEL:
        return Requested(
            grain=population_grain, explicit=True, source="population",
            because=("the conversation is carrying a population at this grain, "
                     "so the answer is one row per member of it"))

    if _FACILITY_WORDS.search(sentence):
        return Requested(
            grain=FACILITY, explicit=True, source="facility",
            because="the question names facilities, so each row is a facility")

    if _CUSTOMER_WORDS.search(sentence):
        return Requested(
            grain=CUSTOMER, explicit=True, source="customer",
            because="the question names customers, so each row is a customer")

    if dimension:
        return Requested(
            grain=SEGMENT, explicit=True, source="dimension",
            dimension=dimension,
            because=(f"the question asks for a breakdown by "
                     f"{dimension.replace('_', ' ')}, so each row is one "
                     f"{dimension.replace('_', ' ')}"))

    if (_PORTFOLIO_WORDS.search(sentence) and not rows_requested
            and not _PORTFOLIO_AS_ADJECTIVE.search(sentence)):
        return Requested(
            grain=PORTFOLIO, explicit=True, source="portfolio",
            because=("the question is about the portfolio as a whole, so the "
                     "answer is one row for the whole book"))

    fallback = dataset_grain if dataset_grain in LEVEL else FACILITY
    return Requested(
        grain=fallback, explicit=False, source="dataset",
        because=(f"the question did not say what one row should be, so the "
                 f"answer is at the grain the governed source is keyed on "
                 f"({MEANS.get(fallback, fallback)})"))


def declared(group_by: list[str] | tuple[str, ...], *, key: str = "",
             dimension: str = "") -> str:
    """The grain the built plan will actually emit.

    Read off the grouping rather than off intent, because the grouping is what
    the runtime will do. A plan that meant to answer per customer and grouped
    by nothing returns one row, and this says PORTFOLIO — which is exactly the
    disagreement the postcondition exists to catch.
    """
    columns = [c for c in (group_by or []) if c]
    if not columns:
        return PORTFOLIO
    if key and key in columns and key in GRAIN_OF_KEY:
        return GRAIN_OF_KEY[key]
    for column in columns:
        if column in GRAIN_OF_KEY:
            return GRAIN_OF_KEY[column]
    if dimension and dimension in columns:
        return SEGMENT
    return SEGMENT


def satisfies(want: str, got: str) -> bool:
    """Whether an answer at `got` answers a question asked at `want`."""
    if want not in LEVEL or got not in LEVEL:
        return True
    return want == got


def needs_aggregation(source_grain: str, output_grain: str) -> bool:
    """Whether the source has to be rolled up before it can be reported."""
    if source_grain not in LEVEL or output_grain not in LEVEL:
        return False
    return LEVEL[source_grain] > LEVEL[output_grain]


def unreachable(source_grain: str, output_grain: str) -> bool:
    """Whether the request is finer than anything the source can support.

    A customer-keyed source cannot produce facility rows. Refusing is the only
    honest answer: returning the customer rows under a facility heading is the
    same defect as D15 in the other direction.
    """
    if source_grain not in LEVEL or output_grain not in LEVEL:
        return False
    return LEVEL[output_grain] > LEVEL[source_grain]


@dataclass
class Contract:
    """What the plan promises about its own grain, and how to check it."""

    want: Requested
    #: The grain read off the grouping the plan actually built.
    got: str = ""
    #: The grain the base dataset is keyed on.
    source_grain: str = ""
    #: Columns that must be unique across the answer's rows.
    keys: tuple[str, ...] = ()
    #: Governed aggregations the plan inserted to reconcile the two.
    aggregated: list[str] = field(default_factory=list)
    #: Enrichments that would have amplified rows and were rolled up first.
    pre_aggregated: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return satisfies(self.want.grain, self.got or self.want.grain)

    @property
    def single_row(self) -> bool:
        return (self.got or self.want.grain) == PORTFOLIO

    def sentence(self) -> str:
        """The one line Scope and the Trace both show."""
        got = self.got or self.want.grain
        head = f"{MEANS.get(got, got)} — {self.want.because}"
        if self.pre_aggregated:
            head += (". " + ", ".join(sorted(self.pre_aggregated))
                     + " was rolled up to this grain before it was joined, so "
                     "it could not multiply the rows")
        return head

    def to_dict(self) -> dict[str, Any]:
        return {"requested": self.want.to_dict(),
                "output_grain": self.got or self.want.grain,
                "source_grain": self.source_grain,
                "keys": list(self.keys),
                "aggregated": list(self.aggregated),
                "pre_aggregated": list(self.pre_aggregated),
                "matches_request": self.ok,
                "explanation": self.sentence(),
                "version": GRAIN_VERSION}


def contract_of(build: Any) -> Contract | None:
    """The grain contract a built analysis carries, where it carries one."""
    found = getattr(build, "grain_contract", None)
    return found if isinstance(found, Contract) else None


__all__ = [
    "CUSTOMER", "Contract", "FACILITY", "GRAINS", "GRAIN_OF_KEY",
    "GRAIN_VERSION", "KEY_OF", "LADDER", "LEVEL", "MEANS", "PERIOD",
    "PORTFOLIO", "RECORD", "SEGMENT", "Requested", "contract_of", "declared",
    "needs_aggregation", "requested", "satisfies", "unreachable",
]
