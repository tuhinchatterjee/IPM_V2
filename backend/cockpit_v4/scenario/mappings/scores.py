"""Two Retail scorecards that are never each other.

Section 8: *"Keep behavioural and application score mappings separate. Do not
substitute one for the other."*

They look interchangeable and are not:

| | Behavioural | Application |
|---|---|---|
| Measures | how this account has behaved | what was known at origination |
| Refreshed | every month | once, and then never |
| Range on this release | 300–900 | 200–800 |
| Direction | higher is safer | higher is safer |
| Population | accounts on book | applicants, including declined ones |

A behavioural score of 650 and an application score of 650 are not the same
risk, not on the same range, and not calibrated against the same outcome. So
every entry point here takes the score type, and `card()` refuses to hand
back a card of the other type even when only one exists.

**Points are not percent.** "Reduce the score by 50 points" is
`units.POINTS`: 650 becomes 600. Read as a relative move it would be 325, a
different band and a different PD. `units.py` owns that distinction and this
module never parses a quantity itself.

**The direction is read, not assumed.** `direction` is a published column.
Most scorecards run higher-is-safer and this release's two do, but a card
that ran the other way would make every "improve the score" scenario
backwards, and assuming is how that happens quietly.

**Outside the support range is a refusal, not an extrapolation.** A band
table covers the scores the card was calibrated over. A 950 on a 300–900
card is not the top band; it is a value the card says nothing about.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import mappings as m
from backend.cockpit_v4.scenario.errors import (
    MAPPING_UNAVAILABLE,
    PARAMETER_OUT_OF_RANGE,
    raise_for,
)

#: What a published `direction` may say, and what it means for a scenario.
#: Spelled as the release publishes them, so a comparison is a
#: comparison rather than a normalisation nobody can see.
HIGHER_IS_SAFER = "HIGHER_IS_SAFER"
LOWER_IS_SAFER = "LOWER_IS_SAFER"
DIRECTIONS = (HIGHER_IS_SAFER, LOWER_IS_SAFER)

#: The `product` value a card published for the whole book carries.
#:
#: This release's application card is one of these and its behavioural cards
#: are per product, which is the usual shape: an application scorecard is
#: built on applicants before a product is chosen, and a behavioural one is
#: built on how an account of a particular kind has performed.
#:
#: A cross-product card is USED for a product, not substituted for one, and
#: the difference is visible: the returned `Scorecard.product` reads `ALL`,
#: so a caller reporting which card it priced through reports `ALL` rather
#: than the product it asked about.
ANY_PRODUCT = "ALL"


@dataclass(frozen=True)
class Band:
    """One published band of one scorecard."""

    score_type: str
    scorecard_version: str
    product: str
    low: Decimal
    high: Decimal
    label: str
    pd_12m: Decimal
    horizon_months: float

    def holds(self, score: Decimal) -> bool:
        return self.low <= score <= self.high


@dataclass(frozen=True)
class Scorecard:
    """One score type, one version, one product: a band table with a range."""

    score_type: str
    scorecard_version: str
    product: str
    direction: str
    support_low: Decimal
    support_high: Decimal
    bands: tuple[Band, ...]

    @property
    def safer_is_up(self) -> bool:
        return self.direction == HIGHER_IS_SAFER

    def in_support(self, score: Decimal) -> bool:
        return self.support_low <= score <= self.support_high

    def band_for(self, score: Decimal) -> Band:
        """The band this score falls in, or a refusal naming the range."""
        if not self.in_support(score):
            raise_for(PARAMETER_OUT_OF_RANGE,
                      f"{score} is outside the {self.support_low} to "
                      f"{self.support_high} range the {self.score_type} card "
                      f"{self.scorecard_version} was calibrated over. It is "
                      f"not the top band and it is not the bottom one: the "
                      f"card says nothing about it.",
                      field_path=f"score.{self.score_type.lower()}",
                      support_low=str(self.support_low),
                      support_high=str(self.support_high))
        for band in self.bands:
            if band.holds(score):
                return band
        raise_for(MAPPING_UNAVAILABLE,
                  f"{score} is inside this card's range but falls in no "
                  f"published band, so the band table has a gap in it. A "
                  f"neighbouring band's PD is not this score's PD.",
                  field_path=f"score.{self.score_type.lower()}")
        raise AssertionError("unreachable")  # pragma: no cover

    def pd_for(self, score: Decimal) -> Decimal:
        return self.band_for(score).pd_12m

    def moved(self, score: Decimal, new_score: Decimal) -> dict[str, Any]:
        """Before, after and both PDs. All of it, per section 5.1.

        A move that leaves the card's range comes back as a refusal from
        `band_for`, which is the right answer: the scenario asked for a
        score the card cannot price.
        """
        before, after = self.band_for(score), self.band_for(new_score)
        return {
            "score_type": self.score_type,
            "scorecard_version": self.scorecard_version,
            "product": self.product,
            "direction": self.direction,
            "score_baseline": str(score),
            "score_scenario": str(new_score),
            "score_change_points": str(new_score - score),
            "band_baseline": before.label,
            "band_scenario": after.label,
            "pd_baseline": str(before.pd_12m),
            "pd_scenario": str(after.pd_12m),
            "pd_change_pp": str((after.pd_12m - before.pd_12m) * 100),
            "band_changed": before.label != after.label,
        }


@dataclass(frozen=True)
class Library:
    """Every scorecard a release publishes, indexed but never merged."""

    cards: tuple[Scorecard, ...]

    @property
    def score_types(self) -> tuple[str, ...]:
        return tuple(sorted({c.score_type for c in self.cards}))

    def products(self, score_type: str) -> tuple[str, ...]:
        return tuple(sorted({c.product for c in self.cards
                             if c.score_type == score_type}))

    def card(self, *, score_type: str, product: str,
             scorecard_version: str = "") -> Scorecard:
        """One card. The score type is required and is never substituted.

        The refusal for a missing type is deliberately NOT "here is the other
        one". A reader who asked what a behavioural drop does to PD and was
        answered from the application card would be given a number computed
        on a different population, at a different moment, over a different
        range -- and nothing in the answer would say so.
        """
        if score_type not in (m.BEHAVIOURAL, m.APPLICATION):
            raise_for(MAPPING_UNAVAILABLE,
                      f"{score_type!r} is not a score type. They are "
                      f"{m.BEHAVIOURAL} and {m.APPLICATION}, and they are "
                      f"different scores rather than two names for one.",
                      field_path="score.score_type")
        wanted = [c for c in self.cards
                  if c.score_type == score_type
                  and (not scorecard_version
                       or c.scorecard_version == scorecard_version)]
        matches = [c for c in wanted if c.product == product]
        if not matches:
            # A card published for the whole book covers this product. It is
            # not another product's calibration, and `Scorecard.product`
            # still reads `ALL`, so the caller reports what it priced
            # through rather than what it asked for.
            matches = [c for c in wanted if c.product == ANY_PRODUCT]
        if not matches:
            available = self.products(score_type)
            if not available:
                raise_for(MAPPING_UNAVAILABLE,
                          f"this release publishes no {score_type} "
                          f"scorecard. It has {', '.join(self.score_types)}, "
                          f"and the other card is not a substitute for this "
                          f"one: state the PD change you want to assume "
                          f"instead.",
                          field_path="score.score_type",
                          published=list(self.score_types))
            raise_for(MAPPING_UNAVAILABLE,
                      f"no {score_type} scorecard for {product!r}. It covers "
                      f"{', '.join(available)}. Another product's "
                      f"calibration is not this product's.",
                      field_path="score.product", products=list(available))
        if len({c.scorecard_version for c in matches}) > 1:
            versions = sorted({c.scorecard_version for c in matches})
            raise_for(MAPPING_UNAVAILABLE,
                      f"{product} has {len(versions)} {score_type} scorecard "
                      f"versions in force ({', '.join(versions)}). Two "
                      f"calibrations are two answers; name the version.",
                      field_path="score.scorecard_version",
                      versions=versions)
        return matches[0]


def library(rows: Iterable[Mapping[str, Any]]) -> Library:
    """Build a `Library` from published `whatif_retail_score_map` rows."""
    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["score_type"]), str(row["scorecard_version"]),
               str(row["product"]))
        by_key.setdefault(key, []).append(dict(row))

    cards: list[Scorecard] = []
    for (score_type, version, product), group in sorted(by_key.items()):
        directions = {str(r.get("direction") or "") for r in group}
        if len(directions) > 1 or not (directions & set(DIRECTIONS)):
            raise_for(MAPPING_UNAVAILABLE,
                      f"the {score_type} card {version} for {product} "
                      f"publishes {sorted(directions)} as its direction. "
                      f"Whether a higher score is safer decides the sign of "
                      f"every scenario through it and is not assumed here.",
                      field_path="score.direction")
        bands = tuple(sorted(
            (Band(score_type=score_type, scorecard_version=version,
                  product=product, low=Decimal(str(r["band_low"])),
                  high=Decimal(str(r["band_high"])),
                  label=str(r["band_label"]),
                  pd_12m=Decimal(str(r["pd_12m"])),
                  horizon_months=float(r["horizon_months"]))
             for r in group),
            key=lambda b: b.low))
        cards.append(Scorecard(
            score_type=score_type, scorecard_version=version,
            product=product, direction=next(iter(directions)),
            support_low=Decimal(str(min(float(r["support_low"])
                                        for r in group))),
            support_high=Decimal(str(max(float(r["support_high"])
                                         for r in group))),
            bands=bands))
    if not cards:
        raise_for(MAPPING_UNAVAILABLE,
                  "this release publishes no scorecards at all, so no score "
                  "change can be translated into a PD.",
                  field_path="score")
    return Library(cards=tuple(cards))


__all__ = ["ANY_PRODUCT", "Band", "DIRECTIONS", "HIGHER_IS_SAFER",
           "LOWER_IS_SAFER", "Library", "Scorecard", "library"]
