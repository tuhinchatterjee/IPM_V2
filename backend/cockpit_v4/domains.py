"""
Which book a question is about. Not a setting, and not a frontend filter.

The defect this module exists for
---------------------------------
`DOMAIN = "corporate_cockpit"` was a module constant, and the runtime pinned
one release with a process-wide catalogue cache. There was exactly one book
per process, so "Corporate or Retail?" had nowhere to live except a label on
a screen -- and a label is not isolation. A Retail question would have read
Corporate relations and nothing in the answer would have said so.

A domain here is a whole analytical world: its own release, its own
fingerprint, its own relations and fields, its own calendar, its own
attention methodology. Two domains never share a catalogue entry, a session,
a cache line or an artifact, and the thing that guarantees it is that every
one of those is keyed by the domain rather than checked against it.

What a domain is NOT
--------------------
It is not a tenant. Two tenants are two customers of the same book; two
domains are two books. It is not a release either: a release is one immutable
build OF a domain, and a domain outlives its releases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The two analytical books. A closed set, because "whatever string arrived"
#: is how a Retail question ends up reading Corporate relations.
CORPORATE = "corporate"
RETAIL = "retail"
DOMAIN_IDS: tuple[str, ...] = (CORPORATE, RETAIL)

#: What a reader calls it.
LABELS: dict[str, str] = {CORPORATE: "Corporate Credit",
                          RETAIL: "Retail Credit"}
SHORT_LABELS: dict[str, str] = {CORPORATE: "Corporate", RETAIL: "Retail"}

#: The release each domain is published as. A domain outlives its releases;
#: this names the one this build of CreditProbe is written against.
DEFAULT_RELEASES: dict[str, str] = {
    # QUARTERLY, and that is in the name.
    #
    # A corporate credit file is reviewed on the cycle its obligors report
    # on: audited financials, rating actions, covenant tests and the IFRS 9
    # stage that follows them all land quarterly. The `-20m-` corporate
    # releases were monthly and invented twelve observations a year no
    # credit committee ever saw; they stay published and readable, and
    # nothing points at them.
    CORPORATE: "v4-saudi-corporate-20q-v3",
    # Monthly, because retail risk is behavioural and behaviour is a monthly
    # signal.
    RETAIL: "v4-saudi-retail-20m-v3",
}

#: Which book a question belongs to when nothing has said. Corporate, because
#: that is the book the demonstration opens on -- not because Retail is
#: lesser, and not because either may be substituted for the other.
DEFAULT_DOMAIN = CORPORATE


class UnknownDomain(ValueError):
    """A domain that does not exist. Named, never coerced to the default."""


def parse(value: Any, *, default: str | None = None) -> str:
    """The domain this value names.

    Absent means the default -- a request that says nothing is asking for the
    usual book. Present and wrong is an error: coercing `"corporat"` or
    `"RETAIL_v2"` to Corporate would answer a question about one book with
    another book's numbers, which is the whole defect this module exists for.
    """
    text = str(value or "").strip().lower()
    if not text:
        return default if default is not None else DEFAULT_DOMAIN
    if text in DOMAIN_IDS:
        return text
    raise UnknownDomain(
        f"{value!r} is not a CreditProbe analytical domain. The domains are "
        f"{', '.join(DOMAIN_IDS)}.")


@dataclass(frozen=True)
class DomainScope:
    """Everything one analytical request needs to know about its book.

    Resolved once, at the edge, and carried. Nothing downstream re-derives
    any of this, because two derivations are two chances to disagree.
    """

    domain_id: str
    release_id: str
    release_fingerprint: str
    country: str
    currency: str
    amount_scale: str
    reporting_frequency: str
    periods: tuple[str, ...]
    relations: tuple[str, ...]

    @property
    def label(self) -> str:
        return LABELS.get(self.domain_id, self.domain_id)

    @property
    def short_label(self) -> str:
        return SHORT_LABELS.get(self.domain_id, self.domain_id)

    @property
    def latest_period(self) -> str:
        return self.periods[-1] if self.periods else ""

    @property
    def previous_period(self) -> str:
        return self.periods[-2] if len(self.periods) > 1 else ""

    @property
    def year_ago_period(self) -> str:
        """The same month twelve months back, when the book goes that far."""
        return self.periods[-13] if len(self.periods) > 12 else ""

    @property
    def money_unit(self) -> str:
        return f"{self.currency} {self.amount_scale}".strip()

    def cache_key(self, *parts: Any) -> tuple[Any, ...]:
        """A key nothing from another book can collide with.

        The fingerprint is in it deliberately. A release id is a NAME: two
        builds of `v4-saudi-retail-20m-v1` share it and hold different
        numbers, and a cache keyed on the name alone would serve the old
        build's answer for the new build's question.
        """
        return (self.domain_id, self.release_id, self.release_fingerprint,
                *parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "domain_label": self.label,
            "release_id": self.release_id,
            "release_fingerprint": self.release_fingerprint,
            "country": self.country,
            "reporting_currency": self.currency,
            "amount_scale": self.amount_scale,
            "reporting_frequency": self.reporting_frequency,
            "periods": list(self.periods),
            "latest_period": self.latest_period,
            "previous_period": self.previous_period,
            "year_ago_period": self.year_ago_period,
        }


@dataclass(frozen=True)
class DomainStatus:
    """Whether this book can be asked anything, and why not when it cannot."""

    domain_id: str
    release_id: str
    ready: bool
    reason: str = ""
    scope: DomainScope | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "domain_id": self.domain_id,
            "domain_label": LABELS.get(self.domain_id, self.domain_id),
            "release_id": self.release_id,
            "ready": self.ready,
        }
        if self.reason:
            body["reason"] = self.reason
        if self.scope is not None:
            body.update({k: v for k, v in self.scope.to_dict().items()
                         if k not in body})
        body.update(self.detail)
        return body


__all__ = ["CORPORATE", "DEFAULT_DOMAIN", "DEFAULT_RELEASES", "DOMAIN_IDS",
           "DomainScope", "DomainStatus", "LABELS", "RETAIL", "SHORT_LABELS",
           "UnknownDomain", "parse"]
