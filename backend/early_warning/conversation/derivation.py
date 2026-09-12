"""
Arithmetic a reading may do, and how the server checks it did it correctly.

The problem this solves
-----------------------
The grounding guard asks one question of every figure in the prose: is this
number in the result packet? That is the right question for a figure the
packet holds and the wrong question for a figure the packet *implies*.

"L1 fell 11.31 points, of a 3.67-point fall in the score" is a true sentence
about a packet holding `score_change: -11.31` and `ews_change: -3.67`. So is
"L1 accounts for roughly four-fifths of the move". So is "the two together
carry SAR 1.5bn" over two rows the packet lists. The first was rejected
because the packet stores the fall signed and the prose says it in words; the
last would be rejected because no cell holds the sum.

Rejecting all three teaches the writer to avoid arithmetic, and a credit
reading without arithmetic is a list of numbers. Accepting all three on the
model's word is worse: free-form model arithmetic is exactly the thing the
guard exists to stop.

The contract
------------
The model does not compute. It *declares*:

    {"value": 15.66, "op": "sum", "refs": ["rows[0].exposure",
                                           "rows[1].exposure"]}

and the server looks each ref up in the packet, applies the named operation
itself, and compares. The prose may use the value only where the server's own
recomputation agrees. A claim whose refs do not resolve, whose operation is
not in the closed set, or whose value the server does not reproduce, permits
nothing — the figure falls back to the direct check and is rejected there if
the packet does not hold it.

What is deliberately absent
---------------------------
No `eval`. No expression parser. No model-supplied formula. The operator set
below is small, fixed, and each entry is a Python function of a list of
floats. A model cannot widen it, and adding to it is a code change with a test
beside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

#: How close the server's recomputation has to be to the value the reading
#: states. A reading writes 4/3 as 1.33; the server computes 1.3333...; the
#: two agree. A reading writing 1.4 does not, and that gap is the control.
#:
#: Relative, with an absolute floor, because 0.01 is a rounding difference on
#: 15.66 and a doubling on 0.01.
TOLERANCE = 0.005
FLOOR = 0.011


def _sum(v: list[float]) -> float | None:
    return math.fsum(v) if v else None


def _difference(v: list[float]) -> float | None:
    """a − b. Two refs, in the order the reading names them."""
    return v[0] - v[1] if len(v) == 2 else None


def _delta(v: list[float]) -> float | None:
    """The move from the first to the second: b − a.

    Named apart from `difference` because a reading saying "it rose 3.7"
    means later minus earlier, and a reading saying "the gap is 3.7" means
    the subtraction the other way round. Both are one operation with the
    refs swapped, and making the caller say which one it meant is what lets
    the server check the SIGN rather than only the magnitude.
    """
    return v[1] - v[0] if len(v) == 2 else None


def _product(v: list[float]) -> float | None:
    if not v:
        return None
    out = 1.0
    for x in v:
        out *= x
    return out


def _ratio(v: list[float]) -> float | None:
    if len(v) != 2 or v[1] == 0:
        return None
    return v[0] / v[1]


def _share(v: list[float]) -> float | None:
    """a as a fraction of b. Rejected where b is zero, never 'infinite'."""
    return _ratio(v)


def _percent(v: list[float]) -> float | None:
    got = _ratio(v)
    return None if got is None else got * 100.0


def _mean(v: list[float]) -> float | None:
    return math.fsum(v) / len(v) if v else None


def _magnitude(v: list[float]) -> float | None:
    """|a|. One ref.

    The commonest derivation in this product, and the reason the guard was
    rejecting true sentences: a movement is stored signed and written in
    words. `score_change: -11.31` is "fell 11.31 points" in every credit
    paragraph anyone writes.
    """
    return abs(v[0]) if len(v) == 1 else None


def _minimum(v: list[float]) -> float | None:
    return min(v) if v else None


def _maximum(v: list[float]) -> float | None:
    return max(v) if v else None


def _count(v: list[float]) -> float | None:
    """How many refs were named. Resolves 'three of them carry ...'."""
    return float(len(v)) if v else None


#: Every operation a reading may name. Closed on purpose: the whole safety of
#: this contract is that the server, not the model, decides what arithmetic
#: means. A model naming anything else gets its claim dropped.
OPERATIONS: dict[str, Callable[[list[float]], float | None]] = {
    "sum": _sum,
    "difference": _difference,
    "delta": _delta,
    "product": _product,
    "ratio": _ratio,
    "share": _share,
    "percent": _percent,
    "mean": _mean,
    "magnitude": _magnitude,
    "minimum": _minimum,
    "maximum": _maximum,
    "count": _count,
}

#: How many refs each operation takes. `0` means "one or more".
ARITY: dict[str, int] = {
    "sum": 0, "difference": 2, "delta": 2, "product": 0, "ratio": 2,
    "share": 2, "percent": 2, "mean": 0, "magnitude": 1, "minimum": 0,
    "maximum": 0, "count": 0,
}


@dataclass
class Claim:
    """One derivation a reading declared, and what the server made of it."""

    value: float
    op: str
    refs: list[str] = field(default_factory=list)
    #: What the server computed. `None` where it could not.
    recomputed: float | None = None
    accepted: bool = False
    #: Why not, in a sentence, where it was not accepted.
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": self.value, "op": self.op, "refs": list(self.refs),
            "accepted": self.accepted,
        }
        if self.recomputed is not None:
            out["recomputed"] = round(self.recomputed, 6)
        if self.reason:
            out["reason"] = self.reason
        return out


def agrees(stated: float, computed: float) -> bool:
    """Whether the reading's figure and the server's are the same figure."""
    gap = abs(stated - computed)
    return gap <= max(FLOOR, TOLERANCE * abs(computed))


def index(payload: Any) -> dict[str, float]:
    """Every numeric fact in a packet, under a name a reading can cite.

    Dotted for a nested figure, bracketed for a row: `movement.ews_change`,
    `movement.layers[0].score_change`, `rows[2].exposure`. A reading citing a
    name that is not in here has cited nothing, and its claim is dropped.

    Strings are walked too, because a driver-tree split arrives as the label
    "Days past due >= 90" and the threshold inside it is a governed fact.
    They are indexed under the key that holds them, so a label yielding one
    number is citable and one yielding several is not — an ambiguous ref
    resolves to nothing rather than to whichever number came first.
    """
    from backend.early_warning.facts import _NUMERAL  # noqa: PLC0415

    out: dict[str, float] = {}
    seen_twice: set[str] = set()

    def put(name: str, value: float) -> None:
        if name in out and out[name] != value:
            seen_twice.add(name)
        else:
            out[name] = value

    def walk(value: Any, path: str) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            put(path, float(value))
        elif isinstance(value, str):
            found = _NUMERAL.findall(value)
            if len(found) == 1:
                try:
                    put(path, float(found[0].replace(",", "")))
                except ValueError:
                    pass
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")

    walk(payload, "")
    for name in seen_twice:
        out.pop(name, None)
    return out


def _resolve(ref: str, facts: dict[str, float]) -> float | None:
    """One ref, looked up exactly and then by the tail of its path.

    Exactly first, because a reading that cites the full path has been
    precise and deserves to be taken at its word. Then by suffix, because
    `figures.movement.ews_change` and `movement.ews_change` are the same fact
    and a reading should not fail for choosing the shorter name — but only
    where the suffix picks out ONE fact. Where it picks out several, it has
    named none of them.
    """
    text = str(ref or "").strip()
    if not text:
        return None
    if text in facts:
        return facts[text]
    tail = f".{text}"
    hits = [v for k, v in facts.items() if k.endswith(tail)]
    if len(hits) == 1:
        return hits[0]
    unique = {round(h, 9) for h in hits}
    return hits[0] if len(unique) == 1 and hits else None


def check(declared: Any, facts: dict[str, float], *,
          limit: int = 12) -> list[Claim]:
    """Every declared derivation, recomputed by the server.

    Nothing here trusts the model with arithmetic. It is trusted only to say
    which governed facts it used and which of a dozen named operations it
    applied to them; the value it wrote is compared against the one this
    function computes, and disagreement drops the claim.
    """
    out: list[Claim] = []
    for raw in list(declared or [])[:limit]:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get("op") or "").strip().lower()
        refs = [str(r).strip() for r in (raw.get("refs") or []) if str(r).strip()]
        try:
            stated = float(raw.get("value"))
        except (TypeError, ValueError):
            continue
        claim = Claim(value=stated, op=op, refs=refs[:8])

        if op not in OPERATIONS:
            claim.reason = f"{op!r} is not an operation this product recomputes"
            out.append(claim)
            continue
        wanted = ARITY[op]
        if wanted and len(claim.refs) != wanted:
            claim.reason = (f"{op} takes {wanted} facts and the reading named "
                            f"{len(claim.refs)}")
            out.append(claim)
            continue
        if not claim.refs:
            claim.reason = "the reading named no facts to compute from"
            out.append(claim)
            continue

        values: list[float] = []
        missing: list[str] = []
        for ref in claim.refs:
            got = _resolve(ref, facts)
            if got is None:
                missing.append(ref)
            else:
                values.append(got)
        if missing:
            claim.reason = ("the result carries no fact called "
                            + ", ".join(missing[:3]))
            out.append(claim)
            continue

        computed = OPERATIONS[op](values)
        if computed is None or not math.isfinite(computed):
            claim.reason = f"{op} is not defined over those facts"
            out.append(claim)
            continue
        claim.recomputed = computed
        if agrees(stated, computed):
            claim.accepted = True
        else:
            claim.reason = (f"the reading wrote {stated:g} where {op} over "
                            f"those facts gives {computed:.6g}")
        out.append(claim)
    return out


def spellings(value: float) -> set[str]:
    """Every way a reading may write one permitted figure.

    The same forms the direct check allows, so a derived figure and a direct
    one are held to one standard rather than two.
    """
    out = {f"{value:.0f}", f"{value:.1f}", f"{value:.2f}",
           f"{value:,.0f}", f"{value:,.1f}"}
    if abs(value) >= 1000:
        out |= {f"{value / 1000:,.1f}", f"{value / 1000:.1f}",
                f"{value / 1000:.0f}"}
    return out | {s.replace(",", "") for s in out}


__all__ = ["ARITY", "Claim", "FLOOR", "OPERATIONS", "TOLERANCE", "agrees",
           "check", "index", "spellings"]
