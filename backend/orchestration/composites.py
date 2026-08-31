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

TESTS: frozenset[str] = frozenset({ABOVE, BELOW, TRUE, ROSE_BY})


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
        return bool(re.search(self.pattern, text or "", re.IGNORECASE))


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


COMPOSITES: tuple[Composite, ...] = (LIQUIDITY_STRESS,)


@dataclass(frozen=True)
class Resolved:
    """A composite, narrowed to what this installation actually carries."""

    composite: Composite
    #: Signals whose every column exists in the catalogue.
    available: tuple[Signal, ...]
    #: Signals declared for the composite whose columns this installation does
    #: not have. Distinct from `absent`: these are a deployment gap, not a
    #: catalogue-wide one.
    missing: tuple[Signal, ...]

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
        if not composite.matches(text):
            continue
        available, missing = _split(composite, catalogue)
        found = Resolved(composite=composite, available=tuple(available),
                         missing=tuple(missing))
        if not found.usable:
            return None
        if len({s.dataset for s in found.available}) > 1:
            return None
        return found
    return None


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


__all__ = ["ABOVE", "BELOW", "COMPOSITES", "COMPOSITE_VERSION", "Composite",
           "LIQUIDITY_STRESS", "ROSE_BY", "Resolved", "Signal", "TRUE",
           "find"]
