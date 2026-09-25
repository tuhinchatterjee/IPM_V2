"""The categories a book actually holds, including the one nobody wants.

Section 8: *"Sector discovery must return actual categories with counts,
exposure and ECL. Resolve synonyms to real identifiers. Retain Unknown and
Unmapped in totals and exports. Never relabel a Retail product as an employer
sector."*

Four separate requirements and each has a way of going wrong quietly.

**Actual categories, with their size.** "Which sectors do we lend to?"
answered from a list of sector names is answered from a dictionary, not from
a book. The book's answer is the categories that appear in it, how many
exposures are in each and what they are worth -- so a sector holding two
facilities and one holding four hundred do not look alike.

**Synonyms resolve; unknown words do not.** "Real estate", "Real Estate" and
"property" can all be the book's `Real Estate`. "Aviation" is not anything,
and answering it with the nearest string match would put a number against a
sector the reader did not ask about. A near-miss comes back as a refusal
listing what the book does have.

**Unknown is a category.** Dropping it makes every total smaller than the
book and every share larger than it should be, and the error is invisible
because the remaining numbers still add up to the remaining total.
`totals()` therefore reconciles: the parts sum to the whole, `Unknown`
included, and `reconciles()` says so as a fact rather than as a promise.

**A product is not an employer sector.** In the Retail book `product` is what
was sold and `employer_sector` is where the customer works. They are
different columns with different values and different cardinalities, and a
scenario that stressed "Construction" by relabelling one as the other would
be stressing the wrong population. `DIMENSIONS` names both and nothing here
maps between them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.generate.totals import exact_total
from backend.cockpit_v4.scenario import mappings as m
from backend.cockpit_v4.scenario.errors import MAPPING_UNAVAILABLE, raise_for

#: The categorical dimensions a scenario may name, per book, and the column
#: each one is. Listed so that the two Retail dimensions a reader is most
#: likely to conflate are visibly different things.
DIMENSIONS: dict[str, dict[str, str]] = {
    "corporate": {"sector": "sector", "sub_sector": "sub_sector",
                  "region": "region", "product_type": "product_type",
                  "facility_class": "facility_class",
                  "relationship_tier": "relationship_tier"},
    "retail": {"employer_sector": "employer_sector",
               "employer_sector_group": "employer_sector_group",
               "product": "product", "sub_product": "sub_product",
               "region": "region", "customer_segment": "customer_segment",
               "employment_type": "employment_type"},
}

#: Spellings that mean a category rather than name one. Lower-cased, and
#: deliberately short: a long synonym list is a long list of chances to
#: resolve a word to something the reader did not mean.
SYNONYMS: dict[str, str] = {
    "property": "real estate",
    "realestate": "real estate",
    "real-estate": "real estate",
    "oil and gas": "energy",
    "oil & gas": "energy",
    "manufacture": "manufacturing",
    "govt": "government",
    "telecoms": "telecom",
    "healthcare": "health care",
    "fmcg": "consumer goods",
}


@dataclass(frozen=True)
class Category:
    """One value of one dimension, with what it is worth in this book."""

    dimension: str
    value: str
    entities: int
    ead: Decimal
    ecl: Decimal

    @property
    def is_residual(self) -> bool:
        return self.value in m.RESIDUAL

    @property
    def coverage_pct(self) -> Decimal | None:
        """ECL over EAD. None rather than infinity on a zero denominator."""
        if self.ead == 0:
            return None
        return self.ecl / self.ead * 100


@dataclass(frozen=True)
class Dictionary:
    """Every category of one dimension, as the book actually holds them."""

    dimension: str
    categories: tuple[Category, ...]

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(c.value for c in self.categories)

    def totals(self) -> dict[str, Any]:
        """The whole dimension, residuals included, with the check visible."""
        return {
            "dimension": self.dimension,
            "categories": len(self.categories),
            "entities": sum(c.entities for c in self.categories),
            "ead": exact_total(float(c.ead) for c in self.categories),
            "ecl": exact_total(float(c.ecl) for c in self.categories),
            "residual_categories": [c.value for c in self.categories
                                    if c.is_residual],
            "residual_entities": sum(c.entities for c in self.categories
                                     if c.is_residual),
        }

    def reconciles(self, *, entities: int, ecl: float,
                   tolerance: float = 1e-6) -> bool:
        """Do the parts add up to the book? Only if the residuals are in.

        The test that catches a dropped `Unknown`: the remaining categories
        still sum to the remaining total, so nothing looks wrong until this
        is compared with the book's own figure.
        """
        got = self.totals()
        return (int(got["entities"]) == int(entities)
                and abs(float(got["ecl"]) - float(ecl)) <= tolerance)

    def of(self, value: str) -> Category:
        for category in self.categories:
            if category.value == value:
                return category
        raise_for(MAPPING_UNAVAILABLE,
                  f"{value!r} is not a {self.dimension} in this book. It "
                  f"holds {', '.join(self.values)}.",
                  field_path=f"cohort.{self.dimension}",
                  categories=list(self.values))
        raise AssertionError("unreachable")  # pragma: no cover

    def resolve(self, text: str) -> str:
        """A reader's word, as a value this book actually carries.

        Case and spacing are forgiven and a short synonym list is applied.
        Everything else is refused with the real categories listed, because
        the alternative is a confident number against a sector the book does
        not have.
        """
        wanted = " ".join(str(text).strip().lower().split())
        wanted = SYNONYMS.get(wanted, wanted)
        for category in self.categories:
            if category.value.lower() == wanted:
                return category.value
        squashed = wanted.replace(" ", "")
        for category in self.categories:
            if category.value.lower().replace(" ", "") == squashed:
                return category.value
        raise_for(MAPPING_UNAVAILABLE,
                  f"{text!r} does not name a {self.dimension} in this book. "
                  f"It holds {', '.join(self.values)}. Nothing here is "
                  f"matched by approximation: a number reported against a "
                  f"category the reader did not ask for is worse than a "
                  f"question.",
                  field_path=f"cohort.{self.dimension}",
                  categories=list(self.values))
        raise AssertionError("unreachable")  # pragma: no cover


def discover(rows: Iterable[Mapping[str, Any]], *, dimension: str,
             entity_key: str, ead_column: str = "ead_sar_mn",
             ecl_column: str = "ecl_sar_mn") -> Dictionary:
    """Build a `Dictionary` from the rows a governed query returned.

    A row whose category is blank or null becomes `Unknown` rather than
    being skipped. That is the whole difference between a dimension that
    reconciles to the book and one that is quietly smaller than it.
    """
    entities: dict[str, set[str]] = {}
    ead: dict[str, list[float]] = {}
    ecl: dict[str, list[float]] = {}
    for row in rows:
        raw = row.get(dimension)
        value = str(raw).strip() if raw not in (None, "") else m.UNKNOWN
        entities.setdefault(value, set()).add(str(row[entity_key]))
        ead.setdefault(value, []).append(float(row.get(ead_column) or 0.0))
        ecl.setdefault(value, []).append(float(row.get(ecl_column) or 0.0))

    categories = tuple(sorted(
        (Category(dimension=dimension, value=value,
                  entities=len(entities[value]),
                  ead=Decimal(str(exact_total(ead[value]))),
                  ecl=Decimal(str(exact_total(ecl[value]))))
         for value in entities),
        # Largest first, residuals last regardless of size: a reader scanning
        # this wants the book's shape, and `Unknown` sitting third would read
        # as a sector.
        key=lambda c: (c.value in m.RESIDUAL, -float(c.ecl), c.value)))
    return Dictionary(dimension=dimension, categories=categories)


def require_dimension(domain_id: str, dimension: str) -> str:
    """Refuse a dimension this book does not have, by name.

    The Retail case is the one that matters: `product` and `employer_sector`
    are both real, both categorical, and mean entirely different things.
    Asking for `sector` in the Retail book lands here rather than silently
    reading one of them.
    """
    known = DIMENSIONS.get(domain_id, {})
    if dimension in known:
        return known[dimension]
    hint = ""
    if domain_id == "retail" and dimension in ("sector", "industry"):
        hint = (" This book has employer_sector, which is where a customer "
                "WORKS, and product, which is what was sold to them. They "
                "are different columns with different values and neither is "
                "a substitute for the other.")
    raise_for(MAPPING_UNAVAILABLE,
              f"{dimension!r} is not a dimension of the {domain_id} book. It "
              f"has {', '.join(sorted(known))}.{hint}",
              field_path="cohort.dimension", dimensions=sorted(known))
    raise AssertionError("unreachable")  # pragma: no cover


def keep_residuals(categories: Sequence[Category], *, top: int
                   ) -> tuple[list[Category], Category | None]:
    """The largest `top` categories, and everything else as one row.

    Section 13.3's "Other" bar. The remainder is a real row with a real
    total, so the chart still sums to the book; residual categories are in
    it rather than dropped from it.
    """
    ordered = list(categories)
    head, tail = ordered[:top], ordered[top:]
    if not tail:
        return head, None
    return head, Category(
        dimension=ordered[0].dimension if ordered else "",
        value=f"Other ({len(tail)} categories)",
        entities=sum(c.entities for c in tail),
        ead=Decimal(str(exact_total(float(c.ead) for c in tail))),
        ecl=Decimal(str(exact_total(float(c.ecl) for c in tail))))


__all__ = ["Category", "DIMENSIONS", "Dictionary", "SYNONYMS", "discover",
           "keep_residuals", "require_dimension"]
