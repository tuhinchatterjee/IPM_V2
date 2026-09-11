"""
An identity detail the governed book does not carry, said so plainly.

The failure this exists to prevent
----------------------------------
    "Tell me the borrower's employer name for the highest-ECL facility."

was answered:

    "CreditProbe read this as a question about one row per facility — the
    question names facilities, so each row is a facility — but the governed
    data behind it can only be reported as one row for the whole book."

Three things are wrong with that. It is about grain, and the question was not.
It is FALSE — `retail_facility_month` is one row per facility per month, so the
book can be reported at exactly the level the sentence complains it cannot. And
it leaves the reader to conclude that a better-phrased question would produce
an employer name, which nothing in this installation could ever do.

What actually happened is that "ECL" bound to a measure, "employer name" bound
to nothing at all, and the part that bound to nothing was dropped in silence.
The plan then aggregated to the whole book, and the grain contract — which is
working correctly — refused the plan it was handed. A downstream check wearing
the failure of an upstream one.

So identity attributes are checked before the planner and refused by name. This
is deliberately NOT a general "unmatched noun" detector: guessing at every
phrase a reader might use is how a product starts refusing questions it can
answer. It covers one narrow, high-traffic class — the personal details of a
party to a facility — where the right answer is always the same, is always
"no", and is never a menu.

A credit book is not a customer master. It carries what a credit decision is
made on, and an identity attribute it does not carry is a governance property
of the installation rather than a gap somebody should fill in by asking again
more clearly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

#: The words for a party to a facility, and the column stem each is spelled
#: with in the governed book. A reader says "borrower"; the book says
#: `customer_id`. Refusing to connect the two, and then reporting that nothing
#: about borrowers is carried, would be a true sentence about a column name
#: and a false one about the data.
PARTY_STEM: dict[str, str] = {
    "borrower": "customer",
    "customer": "customer",
    "client": "customer",
    "applicant": "customer",
    "obligor": "customer",
    "counterparty": "customer",
    "account holder": "customer",
    "accountholder": "customer",
    "employer": "employer",
    "guarantor": "guarantor",
    "co-borrower": "customer",
    "coborrower": "customer",
}

#: The identity attributes, and the column words that WOULD carry each one.
#:
#: The second half is the part that keeps this honest. "Product name" must not
#: be refused because no column is literally called `product_name` — the book
#: carries `product_label`, which is the same thing under a different word. So
#: an attribute is absent only when no field about that party carries any of
#: the words that would express it.
ATTRIBUTE_COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("name", "label", "title", "description"),
    "full name": ("name", "label", "title"),
    "first name": ("name", "label"),
    "last name": ("name", "label"),
    "surname": ("name", "label"),
    "address": ("address", "street", "postcode", "post_code", "zip"),
    "home address": ("address", "street"),
    "postal address": ("address", "street", "postcode"),
    "phone": ("phone", "telephone", "mobile", "msisdn", "contact"),
    "phone number": ("phone", "telephone", "mobile", "msisdn", "contact"),
    "telephone": ("phone", "telephone", "mobile", "contact"),
    "telephone number": ("phone", "telephone", "mobile", "contact"),
    "mobile number": ("phone", "mobile", "msisdn", "contact"),
    "contact details": ("phone", "email", "address", "contact"),
    "contact number": ("phone", "telephone", "mobile", "contact"),
    "email": ("email", "e_mail"),
    "email address": ("email", "e_mail"),
    "iban": ("iban", "account_number"),
    "bank account number": ("iban", "account_number"),
    "account number": ("iban", "account_number"),
    "national id": ("national_id", "iqama", "identity", "id_number"),
    "national id number": ("national_id", "iqama", "identity", "id_number"),
    "iqama": ("iqama", "national_id", "identity"),
    "iqama number": ("iqama", "national_id", "identity"),
    "passport": ("passport",),
    "passport number": ("passport",),
    "id number": ("national_id", "iqama", "identity", "id_number"),
    "identity number": ("national_id", "iqama", "identity", "id_number"),
    "date of birth": ("birth", "dob"),
    "birthday": ("birth", "dob"),
    "birth date": ("birth", "dob"),
}

#: How each attribute reads in a refusal, when the plural of the dictionary
#: key would take no article at all.
_NO_ARTICLE = frozenset({"contact details"})


#: Attributes that are read as letters rather than as words. "the borrower
#: iban" is not English; "the borrower IBAN" is.
_DISPLAY = {
    "iban": "IBAN",
    "national id": "national ID",
    "national id number": "national ID number",
    "id number": "ID number",
    "dob": "date of birth",
}


def _spell(attribute: str) -> str:
    return _DISPLAY.get(attribute, attribute)


def _article(attribute: str) -> str:
    """"a" or "an", or nothing where the attribute is already plural."""
    if attribute in _NO_ARTICLE:
        return ""
    return "an " if attribute[:1] in "aeiou" else "a "

_PARTIES = "|".join(
    sorted((re.escape(w) for w in PARTY_STEM), key=len, reverse=True))
_ATTRIBUTES = "|".join(
    sorted((re.escape(w) for w in ATTRIBUTE_COLUMNS), key=len, reverse=True))

#: "customer names", "employer name" — the party and the attribute adjacent.
_POSSESSIVE = re.compile(
    rf"\b(?P<party>{_PARTIES})(?:'s|s'|s)?\s+"
    rf"(?P<attribute>{_ATTRIBUTES})s?\b",
    re.IGNORECASE,
)

#: The same with one word between — "the customer's registered address" —
#: because an adjective does not change which attribute is being asked for.
#:
#: Tried only AFTER the adjacent form, and that order is the whole point. "The
#: borrower's employer name" matches both: adjacent as (employer, name), gapped
#: as (borrower, name) with "employer" read as an adjective. The first is what
#: the sentence says, and refusing it while listing what is held about
#: CUSTOMERS would answer a question nobody asked.
_POSSESSIVE_GAPPED = re.compile(
    rf"\b(?P<party>{_PARTIES})(?:'s|s'|s)?\s+\w+\s+"
    rf"(?P<attribute>{_ATTRIBUTES})s?\b",
    re.IGNORECASE,
)

#: "the name of the borrower", "email addresses of these customers".
_OF = re.compile(
    rf"\b(?P<attribute>{_ATTRIBUTES})s?\s+(?:of|for)\s+"
    rf"(?:the\s+|these\s+|those\s+|each\s+|every\s+|that\s+|this\s+|a\s+|an\s+)?"
    rf"(?P<party>{_PARTIES})s?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Absent:
    """An identity attribute the question asked for and the book has not got."""

    party: str
    attribute: str
    #: What the book DOES hold about that party, in the reader's words.
    instead: tuple[str, ...]
    #: The one of those a reader could sensibly group by, if any.
    groupable: str = ""

    def sentence(self) -> str:
        # Two articles, and they agree with different words. The head names
        # the whole phrase, so it agrees with the PARTY — "an employer name".
        # The tail names the attribute alone — "none of those is a name".
        head = (f"CreditProbe does not carry {_article(self.party)}"
                f"{self.party} {_spell(self.attribute)}.")
        if not self.instead:
            return (
                f"{head} This installation's governed book holds nothing "
                f"about {self.party}s at all — it is a credit book, not a "
                "customer master, and it carries what a credit decision is "
                "measured on. Ask for a figure — expected credit loss, "
                "exposure at default, days past due — and CreditProbe will "
                "compute it."
            )
        held = _and(self.instead)
        said = (
            f"{head} What the governed book holds about {self.party}s is "
            f"{held}, and none of those is "
            f"{_article(self.attribute).strip() or 'a'} "
            f"{_spell(self.attribute)}. That is a property of this "
            "installation, not "
            "of how the question was phrased: no rewording produces one."
        )
        # An identifier is not a breakdown. Offering "break it down by customer
        # id" would produce fourteen thousand rows, which is a download rather
        # than an answer, so the suggestion is made only where the book holds
        # something a reader would actually group by.
        if self.groupable:
            return (f"{said} Ask for a figure and CreditProbe will compute it, "
                    f"or break one down by {self.groupable.lower()}.")
        return f"{said} Ask for a figure and CreditProbe will compute it."

    def to_dict(self) -> dict[str, object]:
        return {"party": self.party, "attribute": self.attribute,
                "instead": list(self.instead), "groupable": self.groupable}


def _and(items: tuple[str, ...]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


@lru_cache(maxsize=1)
def _book() -> tuple[str, tuple[tuple[str, str], ...]]:
    """The served dataset and its fields, as (column, how it reads).

    Read from the governed catalogue rather than from a list in this file, so
    a field a steward publishes tomorrow is one this refusal stops making.
    """
    from backend.data_access.catalog import Catalog
    from backend.orchestration import multi

    name = multi.default_base()
    try:
        dataset = Catalog.load().dataset(name)
    except Exception:
        # No lake, no claim. A refusal that depends on knowing what is carried
        # must not be issued when that is exactly what cannot be read.
        return "", ()
    fields = []
    for column in dataset.fields:
        try:
            business = dataset.field(column).business_name or column
        except Exception:
            business = column
        fields.append((column, business))
    return name, tuple(fields)


def read(question: str) -> Absent | None:
    """The identity attribute this question asks for and the book has not got.

    `None` when it asks for none, or when the book turns out to carry the one
    it asks for — in which case this module has no opinion and the planner
    answers it as any other question.
    """
    for pattern in (_POSSESSIVE, _POSSESSIVE_GAPPED, _OF):
        found = pattern.search(question)
        if found is None:
            continue
        party = found.group("party").lower()
        attribute = found.group("attribute").lower()
        absent = _absent(party, attribute)
        if absent is not None:
            return absent
    return None


def _absent(party: str, attribute: str) -> Absent | None:
    stem = PARTY_STEM.get(party)
    if stem is None:
        return None
    _, fields = _book()
    if not fields:
        return None
    about = [(column, business) for column, business in fields
             if stem in column.lower()]
    carriers = ATTRIBUTE_COLUMNS.get(attribute, ())
    for column, _business in about:
        if any(word in column.lower() for word in carriers):
            # The book carries it under a different word. Not this module's
            # business, and refusing here would be a false statement.
            return None
    return Absent(party=party, attribute=attribute,
                  instead=tuple(business for _column, business in about),
                  groupable=_groupable(about))


def _groupable(about: list[tuple[str, str]]) -> str:
    """The one of these a reader could sensibly break a figure down by.

    An identifier is not a breakdown: "ECL by customer id" is fourteen thousand
    rows, which is a download rather than an answer. So the suggestion is drawn
    from the GOVERNED dimension list — the columns this installation has already
    declared people may group by — and where none of them is about this party,
    no breakdown is suggested at all.
    """
    from backend.orchestration import vocabulary

    try:
        allowed = set(vocabulary.filterable_dimensions())
    except Exception:
        allowed = set()
    for column, business in about:
        if column in allowed:
            return business
    return ""
