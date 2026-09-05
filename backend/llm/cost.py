"""What the thinking cost, and what routing saved. Part 14.

The defect
----------
`routing.Decision` publishes a `cost_estimate`. Nothing ever set it, so every
turn reported that its AI cost was zero. A figure that is always zero is worse
than no figure: it looks like an answer, it reconciles with nothing, and the
first person to add it up gets a total that is wrong in a direction that
flatters.

What this does
--------------
Turns the tokens the telemetry ALREADY records into money, and rolls it up by
the routing class, which is the number anybody actually wants:

    A  deterministic   no model call at all — the question was answered from
                       governed data and cost nothing
    B  routine         one pass through the standard planner
    C  complex         the harder planner, and any repair it needed
    D  critic          an independent check on top

The saving from routing is the honest counterfactual: what the same traffic
would have cost had every turn gone to the class C price. Not a claim about
what any provider charges — a claim about this installation's own configured
tariff, which is a different and checkable thing.

Prices are configured, never assumed
------------------------------------
There is no built-in price list. A tariff nobody entered is reported as
**NOT PRICED**, and a turn served by an unpriced model contributes to the token
counts and to nothing else. Inventing a price and presenting the product of two
guesses as a cost is exactly the fabrication the rest of this system exists to
prevent, and it is the easiest one to get away with because nobody checks a
number that small.

Configure with `CREDITPROBE_AI_TARIFF`, as JSON:

    {"<model>": {"input": 3.00, "output": 15.00,
                 "cache_write": 3.75, "cache_read": 0.30}}

in units of currency per million tokens. Every field is optional; a missing
cache price falls back to the input price, which is the conservative reading.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

COST_VERSION = "1.0.0"

#: Where the tariff comes from. Named so the answer can say it rather than
#: presenting a configured number as though it were a fact about the world.
TARIFF_ENV = "CREDITPROBE_AI_TARIFF"

#: Prices are quoted per million tokens, because that is how every published
#: price list quotes them and converting on the way in is a place to be wrong.
PER = 1_000_000

NOT_PRICED = "NOT_PRICED"
PRICED = "PRICED"


@dataclass(frozen=True)
class Price:
    """What one model costs, per million tokens, at this installation."""

    model: str
    input: float = 0.0
    output: float = 0.0
    #: Writing a cache entry usually costs more than a plain input token and
    #: reading one costs much less. Recorded separately because the whole
    #: reason the telemetry splits them is that they price differently.
    cache_write: float = 0.0
    cache_read: float = 0.0

    def of(self, *, input_tokens: int = 0, output_tokens: int = 0,
           cache_write_tokens: int = 0, cache_read_tokens: int = 0) -> float:
        write = self.cache_write or self.input
        read = self.cache_read or self.input
        return (
            input_tokens * self.input
            + output_tokens * self.output
            + cache_write_tokens * write
            + cache_read_tokens * read
        ) / PER

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "input": self.input,
                "output": self.output, "cache_write": self.cache_write,
                "cache_read": self.cache_read, "per_tokens": PER}


def _tariff() -> dict[str, Price]:
    """The configured price list, or nothing.

    Read on every call rather than cached: an administrator who enters a
    tariff should see it take effect without a restart, and the parse is a
    handful of keys.
    """
    raw = os.environ.get(TARIFF_ENV, "").strip()
    if not raw:
        return {}
    try:
        found = json.loads(raw)
    except ValueError as exc:
        logger.warning("%s is not valid JSON, so nothing is priced: %s",
                       TARIFF_ENV, exc)
        return {}
    if not isinstance(found, dict):
        logger.warning("%s must be an object keyed by model.", TARIFF_ENV)
        return {}

    out: dict[str, Price] = {}
    for model, entry in found.items():
        if not isinstance(entry, dict):
            continue
        try:
            out[str(model)] = Price(
                model=str(model),
                input=float(entry.get("input") or 0.0),
                output=float(entry.get("output") or 0.0),
                cache_write=float(entry.get("cache_write") or 0.0),
                cache_read=float(entry.get("cache_read") or 0.0))
        except (TypeError, ValueError):
            logger.warning("The tariff entry for %s is not numeric.", model)
    return out


def price_of(model: str) -> Price | None:
    """The configured price for this model, or None where none is set."""
    return _tariff().get(str(model or ""))


def configured() -> bool:
    return bool(_tariff())


def of_call(call: Any) -> float | None:
    """What one recorded call cost, or None where its model is not priced.

    None rather than zero. A call whose model carries no tariff cost SOMETHING;
    reporting zero would let an unpriced deployment publish a total that reads
    as free.
    """
    price = price_of(getattr(call, "model", ""))
    if price is None:
        return None
    return price.of(
        input_tokens=int(getattr(call, "input_tokens", 0) or 0),
        output_tokens=int(getattr(call, "output_tokens", 0) or 0),
        cache_write_tokens=int(getattr(call, "cache_write_tokens", 0) or 0),
        cache_read_tokens=int(getattr(call, "cache_read_tokens", 0) or 0))


# --------------------------------------------------------- the class rollup


@dataclass
class ClassTotal:
    """One routing class, over a window of calls."""

    route: str
    label: str
    means: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    #: None where nothing in this class could be priced.
    cost: float | None = None
    #: Calls whose model carries no tariff. Published so a total can be read
    #: as covering part of the traffic rather than all of it.
    unpriced_calls: int = 0

    @property
    def tokens(self) -> int:
        return (self.input_tokens + self.output_tokens
                + self.cache_read_tokens + self.cache_write_tokens)

    @property
    def status(self) -> str:
        return PRICED if self.cost is not None else NOT_PRICED

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route, "label": self.label, "means": self.means,
            "calls": self.calls, "tokens": self.tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cost": round(self.cost, 6) if self.cost is not None else None,
            "unpriced_calls": self.unpriced_calls,
            "status": self.status,
        }


def _classes() -> list[tuple[str, str, str]]:
    from backend.orchestration import routing as rt

    return [
        (rt.DETERMINISTIC, "A — Deterministic",
         "Answered from governed data with no model call at all."),
        (rt.ROUTINE, "B — Routine",
         "One pass through the standard planner."),
        (rt.COMPLEX, "C — Complex",
         "The harder planner, and any repair it needed."),
        (rt.CRITIC, "D — Critic",
         "An independent check on top of the answer."),
    ]


#: Which routing class a call's ROLE belongs to. A role is what the caller
#: asked for; the class is how expensive that kind of thinking is meant to be,
#: and the mapping is written down so a rollup cannot quietly reclassify a
#: call into a cheaper bucket.
ROLE_CLASS: dict[str, str] = {
    "router": "B_ROUTINE",
    "planner": "B_ROUTINE",
    "translation": "B_ROUTINE",
    "interpretation": "B_ROUTINE",
    "complex_planner": "C_COMPLEX",
    "investigator": "C_COMPLEX",
    "analyst": "C_COMPLEX",
    "critic": "D_CRITIC",
}


def class_of(call: Any) -> str:
    """Which routing class this recorded call belongs to."""
    return ROLE_CLASS.get(str(getattr(call, "role", "") or ""), "B_ROUTINE")


def by_class(calls: list[Any] | None = None) -> list[ClassTotal]:
    """Every routing class, with what it cost over the calls given.

    Class A carries no calls by definition — it is the class where no model
    was asked anything — so it is present with zeros rather than absent. A
    rollup that omits it cannot show the reader how much of the traffic was
    answered for nothing, which is the whole argument for routing.
    """
    from backend.llm import telemetry as tm

    if calls is None:
        calls = list(tm.ledger().recent(200))

    totals = {route: ClassTotal(route=route, label=label, means=means)
              for route, label, means in _classes()}
    for call in calls:
        entry = totals.get(class_of(call))
        if entry is None:
            continue
        entry.calls += 1
        entry.input_tokens += int(getattr(call, "input_tokens", 0) or 0)
        entry.output_tokens += int(getattr(call, "output_tokens", 0) or 0)
        entry.cache_read_tokens += int(
            getattr(call, "cache_read_tokens", 0) or 0)
        entry.cache_write_tokens += int(
            getattr(call, "cache_write_tokens", 0) or 0)
        spent = of_call(call)
        if spent is None:
            entry.unpriced_calls += 1
        else:
            entry.cost = (entry.cost or 0.0) + spent
    return [totals[route] for route, _label, _means in _classes()]


def describe(calls: list[Any] | None = None) -> dict[str, Any]:
    """The whole cost picture, as something a reader can check."""
    totals = by_class(calls)
    priced = [t for t in totals if t.cost is not None]
    unpriced = sum(t.unpriced_calls for t in totals)
    tariff = _tariff()

    said = (
        "AI cost is derived from the tokens each call actually recorded, "
        "priced against the tariff configured for this installation.")
    if not tariff:
        said = (
            "No AI tariff is configured for this installation, so token "
            "counts are published and costs are not. A cost computed from a "
            "price nobody entered would be the product of two guesses.")
    elif unpriced:
        said += (f" {unpriced} call{'s' if unpriced != 1 else ''} used a model "
                 "the tariff does not cover, so the total below covers part "
                 "of the traffic rather than all of it.")

    return {
        "version": COST_VERSION,
        "tariff_configured": bool(tariff),
        "tariff_source": TARIFF_ENV,
        "priced_models": sorted(tariff),
        "classes": [t.to_dict() for t in totals],
        "calls": sum(t.calls for t in totals),
        "tokens": sum(t.tokens for t in totals),
        "cost": (round(sum(t.cost or 0.0 for t in priced), 6)
                 if priced else None),
        "unpriced_calls": unpriced,
        "statement": said,
    }


__all__ = ["COST_VERSION", "ClassTotal", "NOT_PRICED", "PER", "PRICED",
           "Price", "ROLE_CLASS", "TARIFF_ENV", "by_class", "class_of",
           "configured", "describe", "of_call", "price_of"]
