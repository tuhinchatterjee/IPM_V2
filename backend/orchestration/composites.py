"""Composite risk concepts: a named credit judgement, as governed evidence.

The defect this exists for
---------------------------
    "Which borrowers have the strongest evidence of liquidity stress?
     Consider cash balances, working-capital movements, short-term debt,
     utilisation, repayment patterns, interest burden and upcoming
     maturities."

came back as one row: the portfolio's utilisation, and how it moved. Three
separate mechanisms had to fail together to produce that, and the third is
this one.

"Liquidity stress" is not a column. The concept resolver looks for governed
fields, finds none for the phrase, and the only measure that survived was
`utilisation` — picked up incidentally from the list of things to CONSIDER.
So a question about a population became a question about a measure, and a
question about eight kinds of evidence became a question about one.

The catalogue could answer it. `portfolio_facility` carries utilisation and
its prior value, days past due, rollover counts, DSCR, covenant headroom, the
watchlist flag and the non-performing flag — eight governed signals, every one
of them a thing a credit officer would look at when asked that question. What
was missing was the vocabulary that says so.

What a composite is
--------------------
A composite is a phrase a credit officer uses that has no single column behind
it, together with the governed signals that constitute EVIDENCE for it. It is
not a model and not a score anybody calibrated: each signal is a threshold on
a published field, stated here in the open, and the answer is a COUNT of how
many fired. Breadth of evidence, not a weighted opinion.

That choice is deliberate. A weighted score would need weights, weights would
need an owner, and an unowned weight in the middle of a credit answer is the
thing this codebase spends most of its governance preventing. Counting how
many independent signals fired is arithmetic a reader can check by eye against
the columns beside it.

Why not conditions
-------------------
The obvious implementation is a cohort: filter to borrowers meeting all eight
tests. That returns nobody. Q3 demonstrates the arithmetic — four conditions
over this book leave one borrower — and eight would leave none, which is a
true answer to a question nobody asked. "Strongest evidence" is a RANKING over
the whole population, and the population is every borrower.

Honesty about what is missing
------------------------------
Four of the dimensions that question names — cash balances, working-capital
movement, short-term debt, upcoming maturities — are not in the governed
catalogue at all. They are declared here as `absent`, so the answer can say
which parts of the question it could not use rather than quietly answering a
narrower one. §3: "return the supported part and state specifically what
cannot be computed."

Adding a composite
-------------------
Add a `Composite` to `COMPOSITES`. Every signal names a dataset and a field;
`resolve()` checks each against the live catalogue and drops the ones that
installation does not carry, so a composite degrades to the evidence actually
present rather than failing or inventing a column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

COMPOSITE_VERSION = "1.0.0"

#: How a signal decides it has fired.
ABOVE = "above"          # field >= value
BELOW = "below"          # field < value
TRUE = "true"            # a boolean flag is set
ROSE_BY = "rose_by"      # field - `against` >= value
EQUALS = "equals"        # a governed enumeration takes this value

TESTS: frozenset[str] = frozenset({ABOVE, BELOW, TRUE, ROSE_BY, EQUALS})


@dataclass(frozen=True)
class Signal:
    """One governed observation that counts as evidence for a composite.

    Every field is a published column and every threshold is written here in
    the open, because a reader who disagrees with one has to be able to see it
    to disagree with it.
    """

    key: str
    #: What this signal is evidence OF, in a credit officer's words. Shown on
    #: the answer and on the Trace.
    label: str
    #: The dimension of the question it answers — "facility utilisation",
    #: "payment behaviour". Lets the answer say which of the things the
    #: question asked for it actually used.
    dimension: str
    dataset: str
    field: str
    test: str
    value: Any = None
    #: For ROSE_BY: the column holding the prior value.
    against: str = ""

    def __post_init__(self) -> None:
        if self.test not in TESTS:
            raise ValueError(
                f"{self.key}: {self.test!r} is not a signal test. "
                f"Use one of {sorted(TESTS)}.")
        if self.test == ROSE_BY and not self.against:
            raise ValueError(
                f"{self.key}: a rose_by signal needs `against`, the column "
                f"holding the prior value.")
        if self.test in (ABOVE, BELOW, ROSE_BY) and self.value is None:
            raise ValueError(f"{self.key}: {self.test} needs a threshold.")
        if self.test == EQUALS and not isinstance(self.value, str):
            raise ValueError(
                f"{self.key}: an equals signal needs the governed value it "
                f"tests for, as it is spelled in the column.")

    @property
    def columns(self) -> tuple[str, ...]:
        """Every column this signal reads."""
        return (self.field, self.against) if self.against else (self.field,)

    def sentence(self) -> str:
        """The threshold, in words, for the Trace and the answer."""
        if self.test == TRUE:
            return f"{self.label} — {self.field} is set"
        if self.test == ABOVE:
            return f"{self.label} — {self.field} at or above {self.value}"
        if self.test == BELOW:
            return f"{self.label} — {self.field} below {self.value}"
        if self.test == EQUALS:
            return f"{self.label} — {self.field} is “{self.value}”"
        return (f"{self.label} — {self.field} at least {self.value} above "
                f"{self.against}")

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label,
                "dimension": self.dimension, "dataset": self.dataset,
                "field": self.field, "test": self.test, "value": self.value,
                "against": self.against, "sentence": self.sentence()}


@dataclass(frozen=True)
class Composite:
    """A credit phrase with no column behind it, and what constitutes it."""

    key: str
    #: What to call it in the answer: "liquidity stress".
    label: str
    #: How a question names it. Matched against the whole message.
    pattern: str
    signals: tuple[Signal, ...]
    #: Dimensions people ask for under this heading that the governed
    #: catalogue does not carry. Named so the answer can say so.
    absent: tuple[str, ...] = ()
    #: One sentence on what the composite means, for the Trace.
    means: str = ""

    def matches(self, text: str) -> bool:
        return self.found_in(text) is not None

    def found_in(self, text: str) -> str | None:
        """The words that named this composite, or None."""
        match = re.search(self.pattern, text or "", re.IGNORECASE)
        return match.group(0).strip() if match else None


LIQUIDITY_STRESS = Composite(
    key="liquidity_stress",
    label="liquidity stress",
    # "liquidity stress", "liquidity squeeze", "running short of cash",
    # "cash pressure", "liquidity warning signs", "funding pressure". Also the
    # plain-English forms a credit officer actually uses on a call.
    pattern=(
        r"liquidit\w*(?:\s+\w+){0,2}?\s*(?:stress|squeez\w*|pressur\w*|"
        r"trouble|risk|warning|strain|difficult\w*|problem\w*|concern\w*)"
        r"|(?:stress|squeez\w*|pressur\w*|trouble|strain|crunch)\s+"
        r"(?:on|in|of)\s+(?:their\s+)?liquidit\w*"
        r"|(?:run\w*|going|getting)\s+(?:short|out)\s+of\s+cash"
        r"|short\s+of\s+cash|cash\s+(?:crunch|squeez\w*|shortage|strain)"
        r"|(?:cash|funding|liquidity)\s+(?:flow\s+)?(?:pressure|problem\w*|"
        r"difficult\w*|stress)"
        r"|financial\s+(?:pressure|distress|strain)"
        r"|liquidity\s+trouble"),
    means=("Evidence that a borrower is finding it harder to fund itself: "
           "drawing down what it has, paying late, rolling over rather than "
           "repaying, or running out of covenant and debt-service headroom."),
    signals=(
        Signal(key="utilisation_high", dimension="facility utilisation",
               label="Drawn to 90% or more of its limit",
               dataset="portfolio_facility", field="utilisation_pct",
               test=ABOVE, value=90.0),
        Signal(key="utilisation_rose", dimension="utilisation movement",
               label="Utilisation rose 5 points or more since the prior period",
               dataset="portfolio_facility", field="utilisation_pct",
               test=ROSE_BY, value=5.0, against="prev_utilisation_pct"),
        Signal(key="arrears", dimension="delinquency / arrears",
               label="In arrears",
               dataset="portfolio_facility", field="dpd_days",
               test=ABOVE, value=1),
        Signal(key="rollovers", dimension="payment behaviour",
               label="Rolled over three times or more",
               dataset="portfolio_facility", field="rollover_count",
               test=ABOVE, value=3),
        Signal(key="weak_debt_service", dimension="debt-service capacity",
               label="Debt-service coverage below 1.2x",
               dataset="portfolio_facility", field="dscr",
               test=BELOW, value=1.2),
        Signal(key="tight_covenant", dimension="covenant pressure",
               label="Covenant headroom below 10%",
               dataset="portfolio_facility", field="covenant_headroom_pct",
               test=BELOW, value=10.0),
        Signal(key="watchlisted", dimension="watchlist status",
               label="On the watchlist",
               dataset="portfolio_facility", field="watchlist", test=TRUE),
        Signal(key="non_performing", dimension="non-performing status",
               label="Classified non-performing",
               dataset="portfolio_facility", field="npl", test=TRUE),
    ),
    # Genuinely not in the catalogue. Not a to-do list — a statement of what
    # this installation cannot see, which the answer repeats to the reader.
    absent=("cash and liquidity balances", "working-capital movement",
            "short-term debt", "upcoming maturities"),
)


# A measure word immediately after the deterioration verb means the sentence
# named WHAT deteriorated, and that is an ordinary movement question about
# that measure — "which borrowers had deteriorating DSCR?" must stay a DSCR
# comparison. The composite is for the question that names no measure at all.
_NAMED_MEASURE = (
    # Up to two words may sit between the verb and the measure — "weakening
    # INTEREST coverage", "deteriorating in their debt service" — and the
    # measure is still what deteriorated.
    r"(?![\s,]*(?:\w+\s+){0,2}?"
    r"\b(?:ecl|pd|ead|lgd|dscr|leverage|coverage|utilisation|utilization|"
    r"rating|ratings|grade|grades|stage|exposure|exposures?\s+at\s+default|"
    r"provision|provisions|impairment|score|scores|headroom|margin|"
    r"cover|dpd|arrears|collateral|covenant)\b)")

DETERIORATION = Composite(
    key="deterioration",
    label="deterioration",
    # "Which exposures have deteriorated this quarter?", "which names are
    # weakening?", "what has got worse?". The question a Deputy CRO opens
    # with, and it names no measure — which is why it came back as "which
    # figure should CreditProbe measure?" of a reader who was asking exactly
    # the question the early-warning columns exist to answer.
    pattern=(
        r"\b(?:which|what|any|show(?:\s+me)?|list|identify)\b"
        r"(?:\s+\w+){0,4}?\s+"
        r"\b(?:exposures?|borrowers?|customers?|clients?|names?|accounts?|"
        r"counterpart(?:y|ies)|obligors?|credits?|facilities|groups?)\b"
        r"[^?.!]{0,24}?"
        rf"\b(?:deteriorat\w+|weaken\w+|worsen\w+|slipp\w+|"
        rf"(?:go(?:ne|ing)?|get(?:ting|s)?|got(?:ten)?|went)"
        rf"\s+(?:backwards|worse))"
        rf"\b{_NAMED_MEASURE}"
        rf"|\bwhat(?:'s|\s+has|\s+have)?\s+"
        rf"(?:deteriorat\w+|weaken\w+|worsen\w+)\b{_NAMED_MEASURE}"
        rf"|\b(?:where|which\s+parts?)\b[^?.!]{{0,30}}?"
        rf"\b(?:deteriorat\w+|weaken\w+|worsen\w+)\b{_NAMED_MEASURE}"),
    means=("Evidence published in the book that a facility has got worse: "
           "the bank's own deterioration trend and early-warning trigger, a "
           "significant increase in credit risk, a risk-appetite breach, "
           "utilisation drawn further down, arrears, and an IFRS 9 stage "
           "worse than 1."),
    signals=(
        Signal(key="trend_deteriorating", dimension="published risk trend",
               label="The book's own trend flag reads Deteriorating",
               dataset="portfolio_facility", field="trend",
               test=EQUALS, value="Deteriorating"),
        Signal(key="sicr", dimension="significant increase in credit risk",
               label="A significant increase in credit risk was triggered",
               dataset="portfolio_facility", field="sicr_trigger", test=TRUE),
        Signal(key="pd_trigger", dimension="early-warning trigger",
               label="The early-warning trigger reads PD deterioration",
               dataset="portfolio_facility", field="trigger_type",
               test=EQUALS, value="PD deterioration"),
        Signal(key="appetite_breach", dimension="risk appetite",
               label="Outside risk appetite",
               dataset="portfolio_facility", field="appetite_breach",
               test=TRUE),
        Signal(key="utilisation_rose", dimension="utilisation movement",
               label="Utilisation rose 5 points or more since the prior period",
               dataset="portfolio_facility", field="utilisation_pct",
               test=ROSE_BY, value=5.0, against="prev_utilisation_pct"),
        Signal(key="arrears", dimension="delinquency / arrears",
               label="In arrears",
               dataset="portfolio_facility", field="dpd_days",
               test=ABOVE, value=1),
        Signal(key="stage_2_or_worse", dimension="IFRS 9 stage",
               label="In Stage 2 or Stage 3",
               dataset="portfolio_facility", field="ifrs9_stage",
               test=ABOVE, value=2),
    ),
    # The internal rating is carried at both ends — `risk_rating` and
    # `prev_risk_rating` — but as a grade CODE rather than an ordinal, so the
    # movement between them is not a comparison a single-dataset signal can
    # make. Named here rather than left out silently: the bank's own PD
    # deterioration trigger stands in its place above, and it is not the
    # same thing.
    absent=("movement in the internal rating between the two dates",
            "external rating actions", "financial-statement deterioration"),
)


CREDIT_CONCERN = Composite(
    key="credit_concern",
    label="credit concern",
    # What a credit officer says when they have already narrowed the book and
    # want the names out of it: "which borrowers are the real issues?", "which
    # names worry you?", "who are the problem accounts?". This is the second
    # turn of nearly every real conversation, and it names no measure at all —
    # so the planner asked "which figure should CreditProbe measure?" of a
    # reader who had just been shown a sector and wanted the names inside it.
    #
    # It is deliberately narrower than "which borrowers": the sentence has to
    # carry a word of CONCERN. "Which borrowers are in Contracting?" is a
    # filter and must stay one.
    pattern=(
        r"\b(?:real\s+)?(?:issue|problem|concern|worry|worrie)\w*\b"
        r"|\bwhich\s+(?:names?|ones?|borrowers?|customers?|clients?|"
        r"counterparties|accounts?)\b[^?]{0,30}\b(?:worry|worries|concern\w*|"
        r"trouble\w*|bother\w*)\b"
        r"|\b(?:require|requiring|need|needing|deserve|deserving|warrant\w*)"
        r"\s+(?:the\s+most\s+|urgent\s+|immediate\s+|closer\s+|closest\s+)?"
        r"attention\b"
        r"|\bworst\s+(?:names?|borrowers?|customers?|credits?|accounts?|"
        r"exposures?|offenders?)\b"
        r"|\bmost\s+(?:at\s+risk|worrying|concerning|troubl\w+)\b"
        r"|\bwho\s+(?:are\s+)?(?:the\s+)?(?:bad|weak|troubled|problem)\s+"
        r"(?:ones?|names?|credits?|borrowers?)\b"
        r"|\bdeteriorat\w+\s+(?:names?|borrowers?|credits?)\b"
        # "Where are multiple warning signals appearing together?" is this
        # ranking in the words an early-warning conversation uses: it asks
        # which names carry several signals at once, which is exactly what
        # counting breadth of evidence answers. Without it the question was
        # refused as something the governed universe holds nothing about,
        # while the columns that answer it were three lines below.
        r"|\b(?:multiple|several|many|more\s+than\s+one|two\s+or\s+more|"
        r"combinations?\s+of|clusters?\s+of|overlapping|co-?occurring)\s+"
        r"(?:\w+\s+){0,2}?(?:warning\s+)?"
        r"(?:signals?|flags?|indicators?|triggers?|red\s+flags?|"
        r"early\s+warnings?)\b"
        r"|\b(?:warning\s+)?(?:signals?|flags?|indicators?|triggers?)\b"
        r"[^?.!]{0,30}?\b(?:together|at\s+once|at\s+the\s+same\s+time|"
        r"in\s+combination|side\s+by\s+side|stacking\s+up|pile\s+up|"
        r"piling\s+up)\b"),
    means=("The borrowers carrying the most governed evidence of credit "
           "difficulty at once: arrears, a stretched limit, weak debt "
           "service, thin covenant headroom, a watchlist flag, a "
           "non-performing classification, or a rating that has fallen."),
    signals=(
        Signal(key="arrears", dimension="delinquency / arrears",
               label="In arrears",
               dataset="portfolio_facility", field="dpd_days",
               test=ABOVE, value=1),
        Signal(key="seriously_late", dimension="serious delinquency",
               label="More than 90 days past due",
               dataset="portfolio_facility", field="dpd_days",
               test=ABOVE, value=90),
        Signal(key="utilisation_high", dimension="facility utilisation",
               label="Drawn to 90% or more of its limit",
               dataset="portfolio_facility", field="utilisation_pct",
               test=ABOVE, value=90.0),
        Signal(key="weak_debt_service", dimension="debt-service capacity",
               label="Debt-service coverage below 1.2x",
               dataset="portfolio_facility", field="dscr",
               test=BELOW, value=1.2),
        Signal(key="tight_covenant", dimension="covenant pressure",
               label="Covenant headroom below 10%",
               dataset="portfolio_facility", field="covenant_headroom_pct",
               test=BELOW, value=10.0),
        Signal(key="watchlisted", dimension="watchlist status",
               label="On the watchlist",
               dataset="portfolio_facility", field="watchlist", test=TRUE),
        Signal(key="non_performing", dimension="non-performing status",
               label="Classified non-performing",
               dataset="portfolio_facility", field="npl", test=TRUE),
        Signal(key="stage_2_or_worse", dimension="IFRS 9 stage",
               label="In Stage 2 or Stage 3",
               dataset="portfolio_facility", field="ifrs9_stage",
               test=ABOVE, value=2),
    ),
    absent=("cash and liquidity balances", "upcoming debt maturities",
            "external rating actions"),
)


# Order matters: `find` returns the FIRST match, and a question naming
# liquidity specifically wants the liquidity reading rather than the
# general one, even though "liquidity problems" satisfies both patterns.
# Deterioration sits between them for the same reason: "which names are
# weakening?" asks what has GOT WORSE, which is a narrower claim than the
# general concern ranking and reads different columns.
COMPOSITES: tuple[Composite, ...] = (LIQUIDITY_STRESS, DETERIORATION,
                                     CREDIT_CONCERN)


@dataclass(frozen=True)
class Resolved:
    """A composite, narrowed to what this installation actually carries."""

    composite: Composite
    #: The words in the question that named it. Carried so the answer and the
    #: coverage gate can both refer to the phrase the reader actually wrote.
    matched: str = ""
    #: Signals whose every column exists in the catalogue.
    available: tuple[Signal, ...] = ()
    #: Signals declared for the composite whose columns this installation does
    #: not have. Distinct from `absent`: these are a deployment gap, not a
    #: catalogue-wide one.
    missing: tuple[Signal, ...] = ()

    @property
    def usable(self) -> bool:
        """Two signals is the floor.

        One signal is not a composite — it is that one measure under a name
        that promises more, which is the substitution this module exists to
        stop. Below the floor the caller falls back to ordinary planning.
        """
        return len(self.available) >= 2

    @property
    def dimensions(self) -> tuple[str, ...]:
        seen: list[str] = []
        for signal in self.available:
            if signal.dimension not in seen:
                seen.append(signal.dimension)
        return tuple(seen)

    @property
    def unavailable(self) -> tuple[str, ...]:
        """Everything the answer could not use, in the reader's words."""
        out = list(self.composite.absent)
        for signal in self.missing:
            if signal.dimension not in out:
                out.append(signal.dimension)
        return tuple(out)

    @property
    def dataset(self) -> str:
        """The single dataset every available signal reads.

        Composites are deliberately single-dataset for now: a join would add a
        place to lose rows, and losing rows from a stress ranking drops
        borrowers off it silently. `find` refuses a composite whose available
        signals span datasets.
        """
        return self.available[0].dataset if self.available else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": COMPOSITE_VERSION,
            "key": self.composite.key,
            "matched": self.matched,
            "label": self.composite.label,
            "means": self.composite.means,
            "dataset": self.dataset,
            "signals": [s.to_dict() for s in self.available],
            "dimensions": list(self.dimensions),
            "unavailable": list(self.unavailable),
            "ranking": (
                f"One row per borrower, ordered by how many of the "
                f"{len(self.available)} governed signals fired, then by "
                f"exposure. Each signal counts once; none is weighted."),
        }


def find(text: str, catalogue: Any = None) -> Resolved | None:
    """The composite a question names, narrowed to what is installed.

    Returns None when the question names no composite, when the catalogue
    carries fewer than two of its signals, or when the surviving signals span
    more than one dataset. In every one of those cases ordinary planning is
    the right answer and this must get out of the way.
    """
    for composite in COMPOSITES:
        named = composite.found_in(text)
        if named is None:
            continue
        available, missing = _split(composite, catalogue)
        found = Resolved(composite=composite, matched=named,
                         available=tuple(available), missing=tuple(missing))
        if not found.usable:
            return None
        if len({s.dataset for s in found.available}) > 1:
            return None
        return found
    return None


#: A governed boolean the sentence can exclude, and the words that exclude it.
#:
#: "Which borrowers are weakening but are NOT YET on the watchlist?" is the
#: highest-value early-warning question there is: show me the evidence before
#: the formal flag. Read as a plain cohort it compiled a predicate against a
#: column that only exists at one end of a movement and the governed runtime
#: refused the plan outright — so the question came back withheld, with a
#: validator message in place of an answer.
#:
#: It is not a filter on a measure and it is not one of the composite's own
#: signals being negated; it is a restriction of the POPULATION to the names
#: that have not yet been formally marked. So it is read here, beside the
#: composite it qualifies, and applied where the composite reads its rows.
EXCLUSIONS: tuple[tuple[str, str], ...] = (
    ("watchlist",
     r"\b(?:not|aren'?t|are\s+not|is\s+not|isn'?t|without|excluding|"
     r"other\s+than|but\s+not|outside)\s+"
     r"(?:yet\s+)?(?:on|in|flagged\s+(?:on|in)|marked\s+(?:on|in)|part\s+of)?"
     r"\s*(?:the\s+)?watch\s?list"
     r"|\bnot\s+(?:yet\s+)?watch\s?listed\b"
     r"|\bnon-?watch\s?listed\b"
     r"|\boff\s+(?:the\s+)?watch\s?list\b"),
    ("npl",
     r"\b(?:not|aren'?t|are\s+not|is\s+not|isn'?t|without|excluding|"
     r"but\s+not)\s+(?:yet\s+)?(?:classified\s+)?non-?performing\b"
     r"|\bstill\s+performing\b|\bperforming\s+only\b"),
)


@dataclass(frozen=True)
class Exclusion:
    """A governed flag the question asked to leave out."""

    field: str
    #: The words in the question that did it, so the answer can quote them.
    phrase: str

    @property
    def says(self) -> str:
        return (f"The question excludes names where {self.field} is set, so "
                f"they are removed from the population before the evidence is "
                f"counted.")

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "phrase": self.phrase, "says": self.says}


def excluded(text: str, available: Any = None) -> tuple[Exclusion, ...]:
    """Governed flags the question asked to leave out.

    `available` is the set of columns the composite's dataset actually has; a
    flag this installation does not carry produces nothing rather than a
    predicate the runtime would reject.
    """
    said = str(text or "")
    if not said:
        return ()
    have = set(available or ())
    found: list[Exclusion] = []
    for field_name, pattern in EXCLUSIONS:
        if have and field_name not in have:
            continue
        match = re.search(pattern, said, re.IGNORECASE)
        if match:
            found.append(Exclusion(field=field_name,
                                   phrase=match.group(0).strip()))
    return tuple(found)


def _split(composite: Composite,
           catalogue: Any) -> tuple[list[Signal], list[Signal]]:
    """Signals this installation can compute, and the ones it cannot."""
    if catalogue is None:
        return list(composite.signals), []

    fields: dict[str, set[str]] = {}
    try:
        for dataset in catalogue.all():
            fields[dataset.name] = set(dataset.fields)
    except Exception:  # noqa: BLE001 - a catalogue that cannot be read is not
        # a reason to refuse the question; the validator below is the real
        # gate, and it reads the same catalogue at plan time.
        return list(composite.signals), []

    available: list[Signal] = []
    missing: list[Signal] = []
    for signal in composite.signals:
        have = fields.get(signal.dataset, set())
        (available if all(c in have for c in signal.columns)
         else missing).append(signal)
    return available, missing


__all__ = ["ABOVE", "BELOW", "COMPOSITES", "COMPOSITE_VERSION",
           "CREDIT_CONCERN", "Composite", "DETERIORATION", "EQUALS",
           "EXCLUSIONS", "Exclusion", "LIQUIDITY_STRESS", "ROSE_BY",
           "Resolved", "Signal", "TRUE", "excluded", "find"]
