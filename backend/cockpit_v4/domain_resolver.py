"""
Which book this request is about. Decided once, in one place.

The order matters, and it is not a preference list
--------------------------------------------------
1. INSIDE A THREAD, the thread's domain wins -- always, and without consulting
   anything else. A conversation is held in one book. A follow-up six turns
   later must reach the same evidence as the question that opened it, and a
   domain re-derived from whatever the home page currently shows is not that.
2. Otherwise the request's own selection, which is the Corporate/Retail
   control on Cockpit Home.
3. Otherwise the configured default.

A selection that DISAGREES with the thread it is sent to is not quietly
overruled and not quietly obeyed: it is reported, so the caller can offer to
start a thread in the other book rather than contaminating this one.

Readiness is per domain
-----------------------
One book being unpublished does not make the other unavailable, and it
absolutely does not make the other a substitute for it. `statuses()` answers
for each separately and names the reason when a book cannot be asked
anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.cockpit_v4 import catalog as cat
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake


class DomainPinned(PermissionError):
    """A request asked one book of a thread held in another."""

    def __init__(self, *, thread_domain: str, asked: str) -> None:
        self.thread_domain = thread_domain
        self.asked = asked
        super().__init__(
            f"This conversation is pinned to {dom.LABELS[thread_domain]} and "
            f"the question was sent as {dom.LABELS[asked]}. Evidence from two "
            f"books in one transcript cannot be told apart afterwards, so "
            f"nothing was substituted. Start a "
            f"{dom.SHORT_LABELS[asked]} conversation for this question.")


#: The books the ANALYTICAL path can currently answer questions about.
#:
#: Both books are published, browsable and have their own dashboards. The
#: execution path -- the catalogue the analyst is shown, the SQL session its
#: queries run in -- is still built from the runtime's single pinned
#: analytical release, which serves the corporate book.
#:
#: This is stated as a fact and enforced rather than hidden. The alternative
#: was to let a retail thread run its SQL against the corporate catalogue,
#: which is the exact defect the domain model exists to prevent: the answer
#: would be fluent, wrong, and would say nothing about which book it came
#: from. §5 says fail closed, so a question in a book the analyst cannot yet
#: reach is refused at acceptance -- before a model call is paid for -- with
#: a message saying what is and is not available.
ANALYSIS_DOMAINS: tuple[str, ...] = (dom.CORPORATE,)


def analysis_supported(domain_id: str) -> bool:
    return dom.parse(domain_id) in ANALYSIS_DOMAINS


class AnalysisNotWiredForDomain(RuntimeError):
    """This book can be browsed but not yet asked. Said, never faked."""

    def __init__(self, domain_id: str) -> None:
        self.domain_id = dom.parse(domain_id)
        supported = ", ".join(dom.LABELS[d] for d in ANALYSIS_DOMAINS)
        super().__init__(
            f"{dom.LABELS[self.domain_id]} questions are not answerable in "
            f"this build. The {dom.LABELS[self.domain_id]} book is published "
            f"and its dashboard and schema are live, but the analytical "
            f"execution path is still bound to the "
            f"{supported} release, and running a "
            f"{dom.SHORT_LABELS[self.domain_id]} question against it would "
            f"answer from the wrong book without saying so. Ask in "
            f"{supported}, or browse "
            f"{dom.SHORT_LABELS[self.domain_id]} in Data Builder.")


class DomainUnavailable(RuntimeError):
    """This book has no published release in this runtime. Said, not swapped."""

    def __init__(self, domain_id: str, reason: str) -> None:
        self.domain_id = domain_id
        self.reason = reason
        super().__init__(
            f"The {dom.LABELS[domain_id]} domain is not available in this "
            f"runtime: {reason} Nothing was substituted for it.")


def scope_for(domain_id: str, *, tenant_id: str = lake.DEFAULT_TENANT
              ) -> dom.DomainScope:
    """Everything one request needs to know about its book."""
    domain_id = dom.parse(domain_id)
    release_id = dom.DEFAULT_RELEASES[domain_id]
    try:
        catalog = cat.build(domain_id=domain_id, release_id=release_id,
                            tenant_id=tenant_id)
    except lake.ReleaseNotFound as exc:
        raise DomainUnavailable(
            domain_id,
            f"release {release_id!r} is not published.") from exc
    return dom.DomainScope(
        domain_id=domain_id,
        release_id=catalog.dataset_release_id,
        release_fingerprint=catalog.release_fingerprint,
        country=lake.COUNTRY_NAME,
        currency=catalog.reporting_currency,
        amount_scale=catalog.amount_scale,
        reporting_frequency=catalog.calendar.frequency,
        periods=tuple(catalog.calendar.slots),
        relations=catalog.relations())


def resolve(*, thread_domain: str = "", requested: Any = None,
            tenant_id: str = lake.DEFAULT_TENANT) -> dom.DomainScope:
    """The book this request is about, by the order at the top of this module."""
    if thread_domain:
        pinned = dom.parse(thread_domain)
        asked = dom.parse(requested, default=pinned)
        if asked != pinned:
            raise DomainPinned(thread_domain=pinned, asked=asked)
        return scope_for(pinned, tenant_id=tenant_id)
    return scope_for(dom.parse(requested), tenant_id=tenant_id)


@dataclass(frozen=True)
class Availability:
    """What each book can currently do, and why not when it cannot."""

    statuses: tuple[dom.DomainStatus, ...]

    def __getitem__(self, domain_id: str) -> dom.DomainStatus:
        for status in self.statuses:
            if status.domain_id == domain_id:
                return status
        raise KeyError(domain_id)

    @property
    def ready_domains(self) -> tuple[str, ...]:
        return tuple(s.domain_id for s in self.statuses if s.ready)

    @property
    def default(self) -> str:
        """The book to open on. The configured one when it is ready.

        When it is not, the first book that IS ready -- which is a different
        thing from substituting one for the other: nothing here answers a
        Corporate question with Retail data, it only decides which control is
        selected when the page opens.
        """
        if dom.DEFAULT_DOMAIN in self.ready_domains:
            return dom.DEFAULT_DOMAIN
        return self.ready_domains[0] if self.ready_domains else \
            dom.DEFAULT_DOMAIN

    def to_dict(self) -> dict[str, Any]:
        return {
            "domains": [s.to_dict() for s in self.statuses],
            "default_domain": self.default,
            "ready": list(self.ready_domains),
        }


def availability(*, tenant_id: str = lake.DEFAULT_TENANT) -> Availability:
    statuses: list[dom.DomainStatus] = []
    for domain_id in dom.DOMAIN_IDS:
        release_id = dom.DEFAULT_RELEASES[domain_id]
        try:
            scope = scope_for(domain_id, tenant_id=tenant_id)
        except DomainUnavailable as exc:
            statuses.append(dom.DomainStatus(
                domain_id=domain_id, release_id=release_id, ready=False,
                reason=exc.reason,
                detail={"provision_command": provision_command(domain_id)}))
            continue
        except cat.CrossDomainAccess as exc:
            statuses.append(dom.DomainStatus(
                domain_id=domain_id, release_id=release_id, ready=False,
                reason=str(exc)))
            continue
        manifest = lake.read_manifest(release_id)
        statuses.append(dom.DomainStatus(
            domain_id=domain_id, release_id=release_id, ready=True,
            scope=scope,
            detail={"row_counts": manifest.get("row_counts", {}),
                    "entity_counts": manifest.get("entity_counts", {}),
                    "relation_count": len(manifest.get("relations", [])),
                    "field_count": sum(len(r.get("fields", []))
                                       for r in manifest.get("relations",
                                                             []))}))
    return Availability(tuple(statuses))


def provision_command(domain_id: str = "") -> str:
    """The one V4-native command that publishes a domain."""
    base = "python3 scripts/cockpit_v4/seed_domains.py"
    return f"{base} --domain {domain_id}" if domain_id else base


__all__ = ["Availability", "DomainPinned", "DomainUnavailable",
           "availability", "provision_command", "resolve", "scope_for"]
