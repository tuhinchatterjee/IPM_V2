"""Before, after, and the proof that the two account for each other.

Section 13.1 asks for a result ledger where the arithmetic is checkable
rather than asserted: every affected row's change, every unaffected row's
exact zero, and a full-book total that equals affected plus unaffected. A
reader who adds up the table must land on the headline, and a table that
nearly lands on it is worse than no table, because it teaches them not to
trust either number.

Three properties are enforced here, and a failure of any of them raises
`RECONCILIATION_FAILED` rather than publishing:

1. **The lines sum to the totals.** Both sides, baseline and scenario.
2. **An unaffected row moved by exactly zero.** Not by a rounding residue:
   zero. A row the scenario did not touch is identical, and a ledger where
   such rows drift is a ledger that computed something it should not have.
3. **The cohort plus everything outside it is the whole book.** Section 9.1
   again: an ineligible record keeps its baseline and stays in the total, so
   the book does not quietly shrink by the rows a method could not handle.

**Attribution is sequential, and says so.** Section 13.2 wants a bridge whose
bars sum to the headline. Applying each intervention in the canonical order
and taking what it adds gives exactly that, by telescoping -- the bars ARE
the total, not an approximation of it. The cost is that the order matters
where effects interact, so `contributions()` states the order it used and
`rules.Graph.order()` is what fixes it. A parent and everything it induced
are ONE bar, because `rules.compile_rules` grouped them that way.

The contributions come out as rows on purpose. `derivation.py`'s closed set
of twelve operations has no attribution operator, so a contribution reaches a
published answer as an artifact row that `sum` and `share_of_total` can act
on -- which is how every other figure in this Cockpit gets published, and
the reason nothing here needs a thirteenth operation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import delta as dl
from backend.cockpit_v4.scenario.errors import RECONCILIATION_FAILED, raise_for

#: Exact, with nothing allowed through. The right tolerance for a ledger
#: assembled entirely in Decimal -- `userdefined.allocate` reconciles at the
#: currency quantum by construction, so any drift there is a defect.
EXACT = Decimal(0)

#: The default, for a ledger whose numbers came back from the database.
#:
#: The books are stored as DOUBLE and DuckDB sums them in DOUBLE, so a total
#: over the Corporate book carries floating-point noise on the order of
#: sqrt(384,009) x 2.2e-16 x 7,075,662 ~= 1e-6 SAR million. A tolerance of
#: 1e-4 SAR million -- a tenth of one riyal on a book of seven billion -- is
#: two orders of magnitude above that noise and four below the smallest
#: figure any reader is shown, so it admits the engine's rounding and
#: nothing else.
#:
#: This is a tolerance on the SUMMATION checks only. "An unaffected row moved
#: by exactly zero" is not one of them and never gets slack: those rows carry
#: their baseline through the SQL verbatim, so there is nothing for a
#: floating-point argument to excuse.
CURRENCY = Decimal("0.0001")

#: Dispositions whose change must be exactly zero. `dl.SCALED` is the only
#: one that may move, which is what makes the check meaningful.
MUST_NOT_MOVE: tuple[str, ...] = (dl.UNAFFECTED, dl.INELIGIBLE,
                                  dl.UNSUPPORTED)


@dataclass(frozen=True)
class Line:
    """One entity's before and after, with why it did or did not move."""

    key: str
    baseline: Decimal
    scenario: Decimal
    disposition: str
    label: str = ""
    reason: str = ""

    @property
    def change(self) -> Decimal:
        return self.scenario - self.baseline

    def as_row(self) -> dict[str, Any]:
        """An artifact row. Strings, because a float here would undo the
        whole point of Decimal upstream."""
        return {"key": self.key, "label": self.label or self.key,
                "baseline_sar_mn": str(self.baseline),
                "scenario_sar_mn": str(self.scenario),
                "change_sar_mn": str(self.change),
                "disposition": self.disposition, "reason": self.reason}


@dataclass(frozen=True)
class Coverage:
    """How many rows each disposition covered, and what they carried."""

    disposition: str
    rows: int
    baseline: Decimal
    reason: str = ""

    def as_row(self) -> dict[str, Any]:
        return {"disposition": self.disposition, "rows": self.rows,
                "baseline_sar_mn": str(self.baseline), "reason": self.reason}


@dataclass(frozen=True)
class Contribution:
    """One intervention's share of the headline change.

    `sequence` is its position in the canonical order, because a sequential
    attribution is only reproducible if the order is published with it.
    """

    label: str
    fields: tuple[str, ...]
    change: Decimal
    sequence: int

    def as_row(self) -> dict[str, Any]:
        return {"intervention": self.label, "fields": ", ".join(self.fields),
                "change_sar_mn": str(self.change), "sequence": self.sequence}


@dataclass(frozen=True)
class Ledger:
    """A scenario's result, and everything needed to check it."""

    domain_id: str
    period: str
    membership_hash: str
    lines: tuple[Line, ...] = ()
    #: The book's baseline total at this period, cohort and non-cohort alike.
    book_baseline: Decimal = Decimal(0)
    #: The tolerance this ledger was reconciled at, recorded rather than
    #: assumed. Section 13.1. `CURRENCY` by default because these numbers
    #: come back from a DOUBLE engine; `EXACT` for a Decimal-only ledger.
    tolerance: Decimal = CURRENCY
    contributions: tuple[Contribution, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    # -- totals ----------------------------------------------------------

    @property
    def baseline(self) -> Decimal:
        return sum((ln.baseline for ln in self.lines), Decimal(0))

    @property
    def scenario(self) -> Decimal:
        return sum((ln.scenario for ln in self.lines), Decimal(0))

    @property
    def change(self) -> Decimal:
        return self.scenario - self.baseline

    @property
    def outside_cohort(self) -> Decimal:
        """The book that this scenario did not touch at all.

        It appears in the ledger because section 13.1's identity is over the
        FULL book: a change of 180 on a cohort of 19,800 inside a book of
        7,075,662 is three different numbers, and a reader shown only the
        first two cannot tell which denominator the percentage used.
        """
        return self.book_baseline - self.baseline

    def relative_change(self) -> Decimal | None:
        """The change as a percentage of the cohort's baseline, or None.

        None rather than zero when the baseline is zero: there is no
        percentage of nothing, and section 10.3's rule about epsilons applies
        to the presentation layer just as much as to the arithmetic.
        """
        if self.baseline == 0:
            return None
        return self.change / self.baseline * 100

    # -- coverage --------------------------------------------------------

    def coverage(self) -> tuple[Coverage, ...]:
        """Rows per disposition, with the first reason each one carried.

        Section 9.1: reason-coded ineligibility, published rather than
        folded into a total. A run that could not handle 1,837 accounts says
        so, with the reason, beside the number it did produce.
        """
        seen: dict[str, list[Line]] = {}
        for line in self.lines:
            seen.setdefault(line.disposition, []).append(line)
        out = []
        for disposition in dl.DISPOSITIONS:
            group = seen.get(disposition)
            if not group:
                continue
            out.append(Coverage(
                disposition=disposition, rows=len(group),
                baseline=sum((ln.baseline for ln in group), Decimal(0)),
                reason=next((ln.reason for ln in group if ln.reason), "")))
        return tuple(out)

    def covered_rows(self) -> int:
        return sum(c.rows for c in self.coverage()
                   if c.disposition == dl.SCALED)

    # -- the checks ------------------------------------------------------

    def check(self) -> None:
        """Raise unless the three properties hold. Called before publishing."""
        self._check_unaffected_are_still()
        self._check_contributions_sum()
        self._check_book_identity()

    def _check_unaffected_are_still(self) -> None:
        moved = [ln for ln in self.lines
                 if ln.disposition in MUST_NOT_MOVE and ln.change != 0]
        if moved:
            raise_for(RECONCILIATION_FAILED,
                      f"{len(moved)} rows are recorded as untouched by this "
                      f"scenario and their ECL moved anyway, the first by "
                      f"{moved[0].change} SAR million. A row the scenario "
                      f"did not affect is identical, not nearly identical.",
                      field_path="ledger.lines",
                      first_key=moved[0].key,
                      disposition=moved[0].disposition)

    def _check_contributions_sum(self) -> None:
        if not self.contributions:
            return
        total = sum((c.change for c in self.contributions), Decimal(0))
        if abs(total - self.change) > self.tolerance:
            raise_for(RECONCILIATION_FAILED,
                      f"the bridge sums to {total} SAR million and the "
                      f"headline change is {self.change}. A reader adding "
                      f"the bars must land on the total.",
                      field_path="ledger.contributions",
                      bars=str(total), headline=str(self.change))

    def _check_book_identity(self) -> None:
        if self.book_baseline == 0:
            return
        if self.outside_cohort < 0:
            raise_for(RECONCILIATION_FAILED,
                      f"the cohort's baseline of {self.baseline} exceeds the "
                      f"book's {self.book_baseline}. One of the two was "
                      f"measured on a different population or period.",
                      field_path="ledger.book_baseline")
        rebuilt = self.baseline + self.outside_cohort
        if abs(rebuilt - self.book_baseline) > self.tolerance:
            raise_for(RECONCILIATION_FAILED,
                      f"affected plus unaffected is {rebuilt} and the book "
                      f"is {self.book_baseline}.",
                      field_path="ledger.book_baseline")

    def reconciles(self) -> bool:
        """The same three checks as a boolean, for a preview or a test."""
        try:
            self.check()
        except Exception:
            return False
        return True

    # -- what gets published ---------------------------------------------

    def rows(self) -> list[dict[str, Any]]:
        return [ln.as_row() for ln in self.lines]

    def coverage_rows(self) -> list[dict[str, Any]]:
        return [c.as_row() for c in self.coverage()]

    def contribution_rows(self) -> list[dict[str, Any]]:
        return [c.as_row() for c in self.contributions]

    def totals_row(self) -> dict[str, Any]:
        relative = self.relative_change()
        return {
            "baseline_sar_mn": str(self.baseline),
            "scenario_sar_mn": str(self.scenario),
            "change_sar_mn": str(self.change),
            "relative_change_pct": (
                "" if relative is None else str(relative)),
            "rows": len(self.lines),
            "rows_changed": self.covered_rows(),
            "book_baseline_sar_mn": str(self.book_baseline),
            "outside_cohort_sar_mn": str(self.outside_cohort),
        }


def build(*, domain_id: str, period: str, membership_hash: str,
          results: dict[str, dl.RowResult], labels: dict[str, str] | None,
          book_baseline: Decimal = Decimal(0),
          tolerance: Decimal = CURRENCY,
          contributions: tuple[Contribution, ...] = (),
          notes: tuple[str, ...] = ()) -> Ledger:
    """Assemble a ledger from per-row results and check it.

    Checked here rather than at publication time so that a ledger object in
    hand is one whose arithmetic already holds; there is no window in which
    an unchecked one could be read.
    """
    labels = labels or {}
    lines = tuple(
        Line(key=key, baseline=result.baseline_ecl,
             scenario=result.scenario_ecl, disposition=result.disposition,
             label=labels.get(key, ""), reason=result.reason)
        for key, result in results.items())
    made = Ledger(domain_id=domain_id, period=period,
                  membership_hash=membership_hash, lines=lines,
                  book_baseline=book_baseline, tolerance=tolerance,
                  contributions=contributions, notes=notes)
    made.check()
    return made


def attribute(totals: list[tuple[str, tuple[str, ...], Decimal]],
              *, baseline: Decimal) -> tuple[Contribution, ...]:
    """Sequential attribution: each intervention gets what it added.

    `totals` is the cumulative scenario total after each intervention has
    been applied, in the canonical order, as
    `(label, fields, cumulative_total)`. The contributions telescope, so they
    sum to the headline change exactly -- which is the property section 13.2
    needs and the reason this is sequential rather than marginal.
    """
    out: list[Contribution] = []
    previous = baseline
    for sequence, (label, fields, cumulative) in enumerate(totals, start=1):
        out.append(Contribution(label=label, fields=fields,
                                change=cumulative - previous,
                                sequence=sequence))
        previous = cumulative
    return tuple(out)


#: The two ways a bridge can be built, named so a chart can say which it is.
#: Section 17.1's O04: sequential PD-then-LGD gives 1,600 and 960 where
#: Shapley gives 1,680 and 880. *"Both may be valid views when correctly
#: labeled, but cannot be mixed."*
SEQUENTIAL = "sequential"
SHAPLEY = "shapley"


def shapley(values: dict[frozenset[str], Decimal], *,
            baseline: Decimal) -> tuple[Contribution, ...]:
    """Order-independent attribution, splitting interactions evenly.

    `values` maps each coalition of intervention labels to the scenario total
    when exactly those interventions are applied; the empty coalition is the
    baseline and may be left out. Every one of the 2^n coalitions must be
    present, because a Shapley value is an average over all of them and one
    computed from a subset is a different quantity wearing the same name.

    The cost is why `attribute()` is the default: n interventions need 2^n
    population passes, against one for the sequential bridge. Two
    interventions need four, which is affordable and is what O04 asks for.

    Weights are exact. `|S|! (n-|S|-1)! / n!` is rational, so it is carried
    as a Fraction and converted once at the end -- a Decimal division by 6
    partway through would put a repeating third into a currency figure.
    """
    from fractions import Fraction
    from itertools import combinations
    from math import factorial

    names = sorted({name for coalition in values for name in coalition})
    n = len(names)
    if not n:
        return ()
    expected = 1 << n
    present = {frozenset(c) for c in values} | {frozenset()}
    if len(present) != expected:
        raise_for(RECONCILIATION_FAILED,
                  f"a Shapley attribution over {n} interventions needs all "
                  f"{expected} coalitions and {len(present)} were supplied. "
                  f"An average over some of them is not a Shapley value.",
                  field_path="ledger.contributions",
                  supplied=len(present), needed=expected)

    def value(members: frozenset[str]) -> Fraction:
        return Fraction(values.get(members, baseline))

    out: list[Contribution] = []
    for sequence, name in enumerate(names, start=1):
        others = [x for x in names if x != name]
        total = Fraction(0)
        for size in range(n):
            weight = Fraction(factorial(size) * factorial(n - size - 1),
                              factorial(n))
            for subset in combinations(others, size):
                members = frozenset(subset)
                total += weight * (value(members | {name}) - value(members))
        out.append(Contribution(label=name, fields=(name,), sequence=sequence,
                                change=_from_fraction(total)))
    return tuple(out)


def _from_fraction(value: object) -> Decimal:
    """A Fraction as a Decimal, at enough precision that the residue is far
    below the currency tolerance the ledger reconciles at."""
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 50
        return Decimal(value.numerator) / Decimal(value.denominator)


#: What a comparison refuses to compare, and why each one matters.
#:
#: Two ledgers are comparable when they are two answers to ONE question about
#: ONE population. Anything else produces a difference that looks like a
#: scenario effect and is not:
#:
#:   a different BOOK      -- two portfolios, so the difference is the books
#:   a different PERIOD    -- the portfolio itself moved between them
#:   a different COHORT    -- different rows, so the difference is the rows
#:
#: The membership hash is the strictest of the three and the one that would
#: be tempting to relax: two runs over "construction" a quarter apart have
#: different hashes, and comparing them is comparing a population change with
#: a scenario change added. Refused, with the hashes named, rather than
#: reported with a caveat nobody reads.
COMPARABLE: tuple[str, ...] = ("domain_id", "period", "membership_hash")


@dataclass(frozen=True)
class Difference:
    """Two frozen ledgers, and what actually differs between them.

    Named `Difference` rather than `Comparison` because that is what it is: it
    does not re-run anything, it does not re-resolve a cohort, and it cannot
    produce a number that neither ledger contains. Both sides are already
    reconciled -- `build()` checks a ledger before returning it -- so the
    arithmetic here is subtraction and the work is saying which subtractions
    are meaningful.
    """

    left_name: str
    right_name: str
    left: Ledger
    right: Ledger

    @property
    def baseline_gap(self) -> Decimal:
        """Should be zero: one cohort at one period has one baseline.

        Published rather than asserted, because a non-zero value is a real
        finding -- the two runs read different data for the same rows -- and
        an assertion would turn it into a crash instead of a report.
        """
        return self.right.baseline - self.left.baseline

    @property
    def scenario_gap(self) -> Decimal:
        return self.right.scenario - self.left.scenario

    @property
    def change_gap(self) -> Decimal:
        return self.right.change - self.left.change

    def relative_gap(self) -> Decimal | str:
        """The scenario difference against the shared baseline.

        Against the LEFT ledger's baseline, named as such. Against either
        change would give a percentage of a difference, which reads like a
        proportion of the portfolio and is not one.
        """
        if self.left.baseline == 0:
            return "not defined (the shared baseline is zero)"
        return self.scenario_gap / self.left.baseline * 100

    def moved(self) -> tuple[tuple[str, Decimal, Decimal], tuple, ...] | list:
        """Per entity: the two scenario values and their difference.

        Only entities BOTH ledgers carry. A key in one and not the other is
        reported separately by `only_in_one`, because an entity that appears
        on one side is not an entity whose value changed -- it is a cohort
        mismatch that the hash check should already have refused.
        """
        left = {ln.key: ln for ln in self.left.lines}
        right = {ln.key: ln for ln in self.right.lines}
        shared = sorted(set(left) & set(right))
        return [(key, left[key].scenario, right[key].scenario)
                for key in shared
                if left[key].scenario != right[key].scenario]

    def only_in_one(self) -> dict[str, list[str]]:
        left = {ln.key for ln in self.left.lines}
        right = {ln.key for ln in self.right.lines}
        return {self.left_name: sorted(left - right),
                self.right_name: sorted(right - left)}

    def dispositions(self) -> list[dict[str, Any]]:
        """Rows whose DISPOSITION differs, which is the interesting kind.

        A row scaled by one run and reported ineligible by the other is a
        disagreement about what could be calculated, not about how much. It is
        easy to miss in a total -- an ineligible row keeps its baseline, so
        both sides may show a small difference -- and it is the thing a reader
        comparing two methods most needs to see.
        """
        left = {ln.key: ln for ln in self.left.lines}
        right = {ln.key: ln for ln in self.right.lines}
        out: list[dict[str, Any]] = []
        for key in sorted(set(left) & set(right)):
            if left[key].disposition == right[key].disposition:
                continue
            out.append({"key": key,
                        self.left_name: left[key].disposition,
                        self.right_name: right[key].disposition,
                        "reason_left": left[key].reason,
                        "reason_right": right[key].reason})
        return out

    def rows(self) -> list[dict[str, Any]]:
        """The difference as artifact rows. Strings, like everything else."""
        out = [
            {"item": "Shared baseline", "left": str(self.left.baseline),
             "right": str(self.right.baseline),
             "difference": str(self.baseline_gap),
             "note": ("one cohort at one period has one baseline, so this "
                      "should be exactly zero")},
            {"item": "Scenario", "left": str(self.left.scenario),
             "right": str(self.right.scenario),
             "difference": str(self.scenario_gap),
             "note": ""},
            {"item": "Change", "left": str(self.left.change),
             "right": str(self.right.change),
             "difference": str(self.change_gap),
             "note": f"{self.relative_gap()}% of the shared baseline"
                     if isinstance(self.relative_gap(), Decimal)
                     else str(self.relative_gap())},
        ]
        for key, left_value, right_value in self.moved():
            out.append({"item": key, "left": str(left_value),
                        "right": str(right_value),
                        "difference": str(right_value - left_value),
                        "note": "per-entity scenario value"})
        for row in self.dispositions():
            out.append({"item": row["key"], "left": row[self.left_name],
                        "right": row[self.right_name], "difference": "",
                        "note": "the two runs disagree about what could be "
                                "calculated for this row, not about how much"})
        missing = self.only_in_one()
        for side, keys in missing.items():
            if keys:
                out.append({"item": f"Only in {side}", "left": "", "right": "",
                            "difference": str(len(keys)),
                            "note": f"{', '.join(keys[:10])}"})
        return out

    def describe(self) -> str:
        if self.scenario_gap == 0:
            return (f"{self.left_name} and {self.right_name} produced the "
                    f"same scenario total, {self.left.scenario}, over the "
                    f"same {len(self.left.lines)} rows.")
        return (f"{self.right_name} puts the scenario total "
                f"{self.scenario_gap:+} SAR million against {self.left_name} "
                f"-- {self.left.scenario} becoming {self.right.scenario} on "
                f"a shared baseline of {self.left.baseline}.")


def compare(left: Ledger, right: Ledger, *, left_name: str = "first",
            right_name: str = "second") -> Difference:
    """The difference between two frozen ledgers, or a refusal to take one.

    Comparability is checked before anything is subtracted, on every field in
    `COMPARABLE`. A comparison across books, periods or cohorts would produce
    a number that looks like a scenario effect and is a population effect, and
    there is no caveat that makes such a figure safe to publish.
    """
    for attribute in COMPARABLE:
        here = getattr(left, attribute)
        there = getattr(right, attribute)
        if here != there:
            raise_for(RECONCILIATION_FAILED,
                      f"{left_name} and {right_name} do not share their "
                      f"{attribute}: {here!r} against {there!r}. Two ledgers "
                      f"are comparable when they are two answers to one "
                      f"question about one population; subtracting these "
                      f"would report a difference in the population as a "
                      f"difference in the scenario.",
                      field_path=f"ledger.{attribute}",
                      left=str(here), right=str(there))
    return Difference(left_name=left_name, right_name=right_name,
                      left=left, right=right)


__all__ = ["CURRENCY", "Contribution", "Coverage", "EXACT", "Ledger",
           "Difference", "COMPARABLE", "Line",
           "MUST_NOT_MOVE", "SEQUENTIAL", "SHAPLEY", "attribute",
           "build", "compare", "shapley"]
