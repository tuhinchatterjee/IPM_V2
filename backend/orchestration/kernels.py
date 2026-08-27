"""
The statistics CreditProbe is allowed to compute over a result it already has.

Why an allowlist rather than a library
--------------------------------------
"Does this trend make sense?" is answered from the rows that are already on the
table. Nothing is re-read, so nothing re-validates: the governed pipeline that
proved those figures ran once, on the previous turn, and this module works on
its output.

That makes the set of permitted operations a governance boundary rather than a
convenience. A model may choose WHICH of these to run and on which columns; it
may never supply the arithmetic. There is no eval, no generated expression and
no pandas passthrough — a kernel is a named Python function in this file, and a
name that is not in `KERNELS` does not run.

Every kernel is pure
--------------------
It takes numbers, returns a value and a short description of what it did, and
touches nothing else. No dataset, no connection, no clock. That is what lets
the Trace say *no governed data was rescanned for this follow-up* and have it
be a checkable claim rather than a promise: a kernel physically cannot rescan.

Reading the results
-------------------
Coefficients are rounded to three decimals here, once, so two callers cannot
disagree about the fourth. Everything that reaches prose goes through
`figures.text` afterwards for how it is *written*; this module decides only
what it *is*.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

#: Below this, a coefficient describes the noise in four points rather than a
#: relationship. Kernels still return a value; `Outcome.reliable` is what says
#: whether it should be leant on.
MIN_OBSERVATIONS = 5

#: Coefficients are reported to three decimals. Further digits are arithmetic
#: about arithmetic — the underlying figures do not carry that precision.
COEFFICIENT_DECIMALS = 3

#: A residual this far from where the association places a group makes it an
#: exception. Measured in ranks and scaled by the number of groups: a third of
#: the field, with a floor so a five-group result cannot call a one-place
#: difference an exception.
EXCEPTION_TOLERANCE = 3.0
MIN_EXCEPTION_GAP = 2.0

#: How many exceptions are named. Beyond three the list stops being an
#: exception and starts being the pattern.
MAX_EXCEPTIONS = 3

#: Two-sided critical values for Spearman's rho at p < 0.05, by sample size.
#: Tabulated rather than approximated, because the normal approximation is
#: wrong at exactly the sample sizes a grouped credit result produces — ten
#: rating grades, six sectors, four quarters.
_RHO_CRITICAL: dict[int, float] = {
    5: 0.900, 6: 0.829, 7: 0.714, 8: 0.643, 9: 0.600, 10: 0.564,
    11: 0.536, 12: 0.503, 13: 0.484, 14: 0.464, 15: 0.446,
    16: 0.429, 17: 0.414, 18: 0.401, 19: 0.391, 20: 0.380,
    25: 0.337, 30: 0.306,
}


@dataclass(frozen=True)
class Outcome:
    """What one kernel computed, and what it is safe to say about it."""

    kernel: str
    #: The number, where the kernel produces one. None means "not computable
    #: from these inputs", which is a result and not a failure.
    value: float | None = None
    #: Named groups the kernel picked out — exceptions, breaks, inversions.
    labels: list[str] = field(default_factory=list)
    #: How many observations went in. On every outcome, because a coefficient
    #: without its n is not evidence.
    n: int = 0
    #: One sentence about what was computed, for the Trace's kernel node.
    note: str = ""
    #: Extra facts a caller may quote — never free text from a model.
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def computable(self) -> bool:
        return self.value is not None or bool(self.labels)

    @property
    def reliable(self) -> bool:
        """Whether this many observations can carry the claim."""
        return self.n >= MIN_OBSERVATIONS

    def to_dict(self) -> dict[str, Any]:
        return {"kernel": self.kernel, "value": self.value,
                "labels": list(self.labels), "n": self.n, "note": self.note,
                "reliable": self.reliable, "detail": dict(self.detail)}


# ---------------------------------------------------------------------------
# The primitives
# ---------------------------------------------------------------------------


def _clean(values: Sequence[Any]) -> list[float]:
    """The numeric values, in order, with the unusable ones dropped.

    A None in a grouped result means the group had nothing to aggregate, not
    zero. Treating it as zero would invent a data point at the bottom of the
    range and pull every coefficient toward it.
    """
    out: list[float] = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(number) or math.isinf(number):
            continue
        out.append(number)
    return out


def _paired(left: Sequence[Any], right: Sequence[Any],
            labels: Sequence[Any] | None = None
            ) -> tuple[list[float], list[float], list[str]]:
    """The pairs where BOTH measures have a usable value.

    Dropping each side independently would compare a group's ECL coverage
    against a different group's DSCR, which is the one way to get a confident
    coefficient out of two unrelated columns.
    """
    a: list[float] = []
    b: list[float] = []
    names: list[str] = []
    for index, (one, two) in enumerate(zip(left, right, strict=False)):
        pair = _clean([one, two])
        if len(pair) != 2:
            continue
        a.append(pair[0])
        b.append(pair[1])
        names.append(str(labels[index]) if labels and index < len(labels) else "")
    return a, b, names


def ranks(values: Sequence[float]) -> list[float]:
    """Average ranks, so ties do not distort a coefficient computed from them."""
    numbers = list(values)
    order = sorted(range(len(numbers)), key=lambda i: numbers[i])
    out = [0.0] * len(numbers)
    position = 0
    while position < len(order):
        end = position
        while (end + 1 < len(order)
               and numbers[order[end + 1]] == numbers[order[position]]):
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            out[order[index]] = average
        position = end + 1
    return out


def _pearson_of(left: Sequence[float], right: Sequence[float]) -> float | None:
    n = len(left)
    if n < 2 or n != len(right):
        return None
    mean_left = sum(left) / n
    mean_right = sum(right) / n
    covariance = sum((a - mean_left) * (b - mean_right)
                     for a, b in zip(left, right, strict=True))
    spread_left = math.sqrt(sum((a - mean_left) ** 2 for a in left))
    spread_right = math.sqrt(sum((b - mean_right) ** 2 for b in right))
    if not spread_left or not spread_right:
        return None
    return round(covariance / (spread_left * spread_right),
                 COEFFICIENT_DECIMALS)


# ---------------------------------------------------------------------------
# The kernels
# ---------------------------------------------------------------------------


def pearson(left: Sequence[Any], right: Sequence[Any],
            labels: Sequence[Any] | None = None) -> Outcome:
    """How closely two measures move together in LEVEL."""
    a, b, _ = _paired(left, right, labels)
    value = _pearson_of(a, b)
    return Outcome(
        kernel="pearson", value=value, n=len(a),
        note=("Pearson product-moment correlation over the paired values in "
              "the previous result. Measures a proportional relationship, so "
              "it falls when the pattern is ordinal rather than linear."))


def spearman(left: Sequence[Any], right: Sequence[Any],
             labels: Sequence[Any] | None = None) -> Outcome:
    """How closely two measures move together in RANK.

    The one to lean on for a grouped credit result. Rating grades are ordered
    but not evenly spaced, so a coefficient that assumes equal steps between
    them is answering a question nobody asked.
    """
    a, b, _ = _paired(left, right, labels)
    value = _pearson_of(ranks(a), ranks(b)) if len(a) >= 2 else None
    return Outcome(
        kernel="spearman", value=value, n=len(a),
        note=("Spearman rank correlation over the paired values in the "
              "previous result. Ranks rather than levels, because ordered "
              "credit categories are not evenly spaced."))


def monotonicity(values: Sequence[Any],
                 labels: Sequence[Any] | None = None) -> Outcome:
    """Whether one measure moves in one direction across the ordered groups.

    Returns +1 for consistently rising, -1 for consistently falling, and the
    fraction of steps that agree with the majority direction otherwise — so a
    result that rises nine times out of ten reads as 0.9 rather than as a flat
    "not monotonic".
    """
    numbers = _clean(values)
    names = [str(x) for x in (labels or [])]
    if len(numbers) < 2:
        return Outcome(kernel="monotonicity", n=len(numbers),
                       note="Two groups are needed before a direction exists.")

    steps = [numbers[i + 1] - numbers[i] for i in range(len(numbers) - 1)]
    rising = sum(1 for s in steps if s > 0)
    falling = sum(1 for s in steps if s < 0)
    majority = rising if rising >= falling else falling
    share = round(majority / len(steps), COEFFICIENT_DECIMALS) if steps else 0.0

    direction = ("rising" if rising and not falling else
                 "falling" if falling and not rising else "mixed")
    if direction == "rising":
        value = 1.0
    elif direction == "falling":
        value = -1.0
    else:
        value = share if rising >= falling else -share

    against = (lambda s: s < 0) if rising >= falling else (lambda s: s > 0)
    breaks = [names[i + 1] if i + 1 < len(names) else ""
              for i, s in enumerate(steps) if against(s)]
    return Outcome(
        kernel="monotonicity", value=value,
        labels=[b for b in breaks if b][:MAX_EXCEPTIONS], n=len(numbers),
        note=("Step-by-step direction across the groups in the order the "
              "previous result presented them. A break is a step that moves "
              "against the majority direction."),
        detail={"direction": direction, "monotonic": direction != "mixed",
                "rising_steps": rising, "falling_steps": falling,
                "steps": len(steps), "agreement": share,
                "first": numbers[0], "last": numbers[-1]})


def slope(values: Sequence[Any]) -> Outcome:
    """Ordinary least squares slope against position, per group step.

    Position rather than a real x-axis, because the groups a credit result is
    cut by — grades, buckets, sectors — have an order but no distance. The
    slope is therefore "per step down the table", which is what it is called.
    """
    numbers = _clean(values)
    n = len(numbers)
    if n < 2:
        return Outcome(kernel="slope", n=n,
                       note="A slope needs at least two groups.")
    xs = [float(i) for i in range(n)]
    mean_x = sum(xs) / n
    mean_y = sum(numbers) / n
    spread = sum((x - mean_x) ** 2 for x in xs)
    if not spread:
        return Outcome(kernel="slope", n=n, note="The groups do not vary.")
    value = sum((x - mean_x) * (y - mean_y)
                for x, y in zip(xs, numbers, strict=True)) / spread
    r = _pearson_of(xs, numbers)
    return Outcome(
        kernel="slope", value=round(value, COEFFICIENT_DECIMALS), n=n,
        note=("Least-squares slope per group step across the previous "
              "result's ordering. The groups are ordered but not evenly "
              "spaced, so this is a direction and a size, not a rate."),
        detail={"per": "group step", "r_squared": round((r or 0.0) ** 2,
                                                        COEFFICIENT_DECIMALS)})


def rank_consistency(left: Sequence[Any], right: Sequence[Any],
                     labels: Sequence[Any] | None = None) -> Outcome:
    """The share of group PAIRS ordered the same way by both measures.

    Kendall's tau-a in everything but name, and easier to state to a credit
    committee than a correlation: 0.8 means that in eight of every ten
    comparisons between two grades, the grade with the higher coverage also
    had the higher leverage.
    """
    a, b, _ = _paired(left, right, labels)
    n = len(a)
    if n < 2:
        return Outcome(kernel="rank_consistency", n=n,
                       note="Two groups are needed before a pair exists.")
    agree = 0
    disagree = 0
    for i in range(n):
        for j in range(i + 1, n):
            first = a[i] - a[j]
            second = b[i] - b[j]
            if first == 0 or second == 0:
                continue
            if (first > 0) == (second > 0):
                agree += 1
            else:
                disagree += 1
    total = agree + disagree
    if not total:
        return Outcome(kernel="rank_consistency", n=n,
                       note="Every comparison was a tie.")
    return Outcome(
        kernel="rank_consistency",
        value=round(agree / total, COEFFICIENT_DECIMALS), n=n,
        note=("The share of group-to-group comparisons that both measures "
              "order the same way, computed over the previous result."),
        detail={"agreeing_pairs": agree, "disagreeing_pairs": disagree,
                "compared_pairs": total})


def exceptions(left: Sequence[Any], right: Sequence[Any],
               labels: Sequence[Any], rho: float | None = None) -> Outcome:
    """The groups that do not sit where the association puts them.

    Measured against the direction the association actually has. Comparing the
    two ranks directly reports every group as an exception whenever the
    relationship is inverse — a perfect Spearman of -1.00 came back with three
    names that did not fit it, which is a contradiction rather than a finding.
    """
    a, b, names = _paired(left, right, labels)
    n = len(a)
    if n < MIN_OBSERVATIONS:
        return Outcome(kernel="exceptions", n=n,
                       note=(f"Fewer than {MIN_OBSERVATIONS} groups: an "
                             "exception cannot be told from the spread."))
    coefficient = rho if rho is not None else (_pearson_of(ranks(a), ranks(b)))
    if coefficient is None:
        return Outcome(kernel="exceptions", n=n,
                       note="No association to be an exception to.")

    left_ranks, right_ranks = ranks(a), ranks(b)
    expected = (left_ranks if coefficient >= 0
                else [(n + 1.0) - rank for rank in left_ranks])
    tolerance = max(MIN_EXCEPTION_GAP, n / EXCEPTION_TOLERANCE)
    gaps = sorted(((abs(expected[i] - right_ranks[i]), names[i])
                   for i in range(n) if names[i]), reverse=True)
    found = [name for gap, name in gaps if gap >= tolerance][:MAX_EXCEPTIONS]
    return Outcome(
        kernel="exceptions", labels=found, n=n,
        value=float(len(found)),
        note=("Groups whose rank on the second measure is more than "
              f"{tolerance:.1f} places from where the association places "
              "them, computed over the previous result."),
        detail={"tolerance_ranks": round(tolerance, 2),
                "rho": coefficient})


def significance(rho: float | None, n: int) -> Outcome:
    """Whether a rank correlation this strong, on this many groups, is notable.

    A tabulated two-sided critical value at p < 0.05 rather than a normal
    approximation, because a grouped credit result has five to twenty rows and
    the approximation is worst exactly there. The outcome is deliberately
    coarse — "notable at this sample size" or not — because a p-value quoted
    off six rating grades invites more confidence than six rating grades can
    carry.
    """
    if rho is None or n < MIN_OBSERVATIONS:
        return Outcome(
            kernel="significance", n=max(0, n),
            note=(f"A significance test needs at least {MIN_OBSERVATIONS} "
                  "groups and a computable coefficient."))
    sizes = sorted(_RHO_CRITICAL)
    nearest = max((s for s in sizes if s <= n), default=sizes[0])
    critical = _RHO_CRITICAL[nearest]
    passes = abs(rho) >= critical
    return Outcome(
        kernel="significance", value=critical, n=n,
        note=("Two-sided critical value for Spearman's rho at p < 0.05 for "
              f"{nearest} observations. The observed coefficient "
              f"{'exceeds' if passes else 'does not exceed'} it."),
        detail={"significant": passes, "critical_value": critical,
                "alpha": 0.05, "compared_at_n": nearest})


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


#: Every operation permitted over a previous result, by name.
#:
#: This dict IS the boundary. `run()` refuses a name that is not in it, and
#: nothing else in the product may execute arithmetic supplied from outside
#: this file. Adding an entry is a governance decision, which is why it is a
#: literal rather than a registration decorator.
KERNELS: dict[str, Callable[..., Outcome]] = {
    "pearson": pearson,
    "spearman": spearman,
    "monotonicity": monotonicity,
    "slope": slope,
    "rank_consistency": rank_consistency,
    "exceptions": exceptions,
    "significance": significance,
}

#: What each kernel is for, in one line. Shown on the Trace's kernel node and
#: in the answer's limitations, so a reader never meets a bare method name.
PURPOSE: dict[str, str] = {
    "pearson": "How closely two measures move together in level.",
    "spearman": "How closely two measures move together in rank order.",
    "monotonicity": "Whether one measure moves in a single direction "
                    "across the groups.",
    "slope": "The size and direction of the change per group step.",
    "rank_consistency": "The share of group comparisons both measures "
                        "order the same way.",
    "exceptions": "The groups that do not sit where the association "
                  "places them.",
    "significance": "Whether a coefficient this strong is notable at this "
                    "number of groups.",
}


class NotApproved(LookupError):
    """A kernel that is not on the allowlist was asked for."""


def run(name: str, *args: Any, **kwargs: Any) -> Outcome:
    """Run one approved kernel by name.

    The only entry point. A caller — including a model-chosen plan — names a
    kernel and supplies columns; it cannot supply an expression, and a name
    that is not on the allowlist raises rather than falling back to something
    close to it. Failing loudly here is the whole point: a silent substitution
    would put an unapproved number under a governed heading.
    """
    kernel = KERNELS.get((name or "").strip().lower())
    if kernel is None:
        raise NotApproved(
            f"{name!r} is not an approved CreditProbe kernel. Approved: "
            + ", ".join(sorted(KERNELS)))
    return kernel(*args, **kwargs)


def approved() -> list[dict[str, str]]:
    """The allowlist, for the Trace and for the API's mode endpoint."""
    return [{"kernel": name, "purpose": PURPOSE.get(name, "")}
            for name in sorted(KERNELS)]


__all__ = [
    "COEFFICIENT_DECIMALS", "KERNELS", "MAX_EXCEPTIONS", "MIN_OBSERVATIONS",
    "NotApproved", "Outcome", "PURPOSE",
    "approved", "exceptions", "monotonicity", "pearson", "rank_consistency",
    "ranks", "run", "significance", "slope", "spearman",
]
