"""
The Analysis Studio registry — and the check that keeps the tick honest.

The rule this module enforces
-----------------------------
A method in the library may CLAIM to be certified. Claiming is not being. On
load, every claim is verified against the thing that would have to be true for
it to hold: either a registered engine analysis that is itself certified and
runnable, or an Analytical IR plan with test cases that have been run and
passed.

A claim that does not survive that check is downgraded — not to hidden, but to
PRECONFIGURED with the reason recorded. So the library cannot drift into
advertising a tick it has not earned, and if somebody deletes an engine function
the methods depending on it stop claiming certification at the next start rather
than at the next audit.

Storage
-------
Library definitions are code, because they are a product decision and belong in
review. Bank-authored methods — built with the AI builder, or forked — live in
PostgreSQL, because they belong to the bank. Both surface through one registry,
and the interface distinguishes them by `source`, never by which list they came
from.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from backend.studio.model import (
    Category,
    Lifecycle,
    MethodDefinition,
)

logger = logging.getLogger(__name__)


@dataclass
class CertificationAudit:
    """Why each claim to certification was upheld or refused.

    Kept and exposed rather than logged and forgotten: "which methods claim the
    tick, and on what evidence" is a question a model validation team asks, and
    the answer should not require reading source.
    """

    upheld: list[str] = field(default_factory=list)
    downgraded: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "certified": sorted(self.upheld),
            "certified_count": len(self.upheld),
            "downgraded": dict(sorted(self.downgraded.items())),
            "downgraded_count": len(self.downgraded),
        }


class MethodNotFound(KeyError):
    """No method by that id or alias."""


class Registry:
    """Every method the Studio knows about."""

    def __init__(self) -> None:
        self._methods: dict[str, MethodDefinition] = {}
        self._aliases: dict[str, str] = {}
        self._audit = CertificationAudit()
        self._lock = threading.Lock()

    # ---- loading -----------------------------------------------------------

    def load(self) -> Registry:
        from backend.studio.library import all_definitions

        with self._lock:
            self._methods.clear()
            self._aliases.clear()
            self._audit = CertificationAudit()

            for method in all_definitions():
                self._verify(method)
                self._methods[method.id] = method

            # Bank-authored methods last, so a bank's fork of a library method
            # under the same id is the one that answers. Verified on the way in
            # exactly as a library entry is.
            for method in _stored_methods():
                self._verify(method)
                self._methods[method.id] = method

            self._reindex_aliases()

        logger.info(
            "Analysis Studio: %d methods, %d certified, %d claims downgraded",
            len(self._methods), len(self._audit.upheld),
            len(self._audit.downgraded),
        )
        return self

    def _verify(self, method: MethodDefinition) -> None:
        """Uphold a certification claim, or downgrade it and say why."""
        if method.lifecycle != Lifecycle.CERTIFIED:
            return

        reason = self._certification_gap(method)
        if reason:
            method.lifecycle = Lifecycle.PRECONFIGURED
            self._audit.downgraded[method.id] = reason
        else:
            self._audit.upheld.append(method.id)

    def _certification_gap(self, method: MethodDefinition) -> str:
        """What stops this method being certified, or empty if nothing does."""
        if method.engine_analysis:
            from backend.engine.contracts import Certification
            from backend.engine.registry import get_registry

            try:
                registered = get_registry().require_runnable(method.engine_analysis)
            except Exception as e:
                return f"its engine analysis is not runnable: {e}"
            if registered.contract.certification is not Certification.CERTIFIED:
                return (f"its engine analysis '{method.engine_analysis}' is "
                        f"{registered.contract.certification.value}, not certified")
            return ""

        if method.plan:
            if not method.test_cases:
                return "it has an implementation but no test cases"
            if any(t.passed is not True for t in method.test_cases):
                return "not every test case has been run and passed"
            return ""

        return "it has no implementation — only a definition"

    def _reindex_aliases(self) -> None:
        """Map every alias to its method, refusing ambiguity.

        Two methods claiming the same alias would make routing arbitrary, so the
        first keeps it and the second is logged. Silent last-write-wins here
        would make Ask CreditProbe's routing depend on dictionary order.
        """
        self._aliases = {}
        for method in self._methods.values():
            for name in [method.id, method.name, *method.aliases]:
                key = _normalise(name)
                if not key:
                    continue
                existing = self._aliases.get(key)
                if existing and existing != method.id:
                    logger.debug(
                        "Alias %r is claimed by both %s and %s; keeping %s",
                        name, existing, method.id, existing,
                    )
                    continue
                self._aliases[key] = method.id

    # ---- reading -----------------------------------------------------------

    def all(self) -> list[MethodDefinition]:
        return list(self._methods.values())

    def get(self, id_or_alias: str) -> MethodDefinition:
        key = str(id_or_alias)
        if key in self._methods:
            return self._methods[key]
        resolved = self._aliases.get(_normalise(key))
        if resolved:
            return self._methods[resolved]
        raise MethodNotFound(
            f"'{id_or_alias}' is not a method in Analysis Studio."
        )

    def find(self, term: str) -> MethodDefinition | None:
        """Resolve a name the way a question would use it. None if unsure.

        Exact and alias matches only — no fuzzy fallback. A planner that
        cheerfully resolves "default rate" to "forward default rate" produces a
        confident number answering a different question, which is the failure
        this whole product exists to avoid.
        """
        try:
            return self.get(term)
        except MethodNotFound:
            return None

    def search(self, query: str = "", *, category: str = "",
               lifecycle: str = "", certified_only: bool = False,
               runnable_only: bool = False) -> list[MethodDefinition]:
        """The Studio's library search."""
        terms = [t for t in _normalise(query).split() if t]
        out = []
        for method in self._methods.values():
            if category and method.category != category:
                continue
            if lifecycle and method.lifecycle != lifecycle:
                continue
            if certified_only and not method.is_certified:
                continue
            if runnable_only and not method.is_runnable:
                continue
            if terms:
                text = method.search_text()
                if not all(t in text for t in terms):
                    continue
            out.append(method)

        # Certified first, then alphabetically. Somebody scanning a category
        # should meet the methods that carry evidence before the definitions.
        out.sort(key=lambda m: (not m.is_certified, m.name.lower()))
        return out

    def categories(self) -> list[dict[str, Any]]:
        """Every category with its counts, for the library landing page."""
        out = []
        for category in Category:
            members = [m for m in self._methods.values() if m.category == category]
            if not members:
                continue
            out.append({
                "category": str(category),
                "count": len(members),
                "certified": sum(1 for m in members if m.is_certified),
                "runnable": sum(1 for m in members if m.is_runnable),
            })
        return out

    def audit(self) -> CertificationAudit:
        return self._audit

    def stats(self) -> dict[str, Any]:
        from collections import Counter

        counts = Counter(m.lifecycle for m in self._methods.values())
        return {
            "total": len(self._methods),
            "by_lifecycle": {str(k): v for k, v in sorted(counts.items())},
            "certified": sum(1 for m in self._methods.values() if m.is_certified),
            "runnable": sum(1 for m in self._methods.values() if m.is_runnable),
            "aliases": len(self._aliases),
            "categories": len(self.categories()),
            "certification_audit": self._audit.to_dict(),
        }

    # ---- writing -----------------------------------------------------------

    def register(self, method: MethodDefinition) -> MethodDefinition:
        """Add or replace a bank-authored method.

        Verified on the way in, exactly as a library entry is: a method built by
        the AI builder claims nothing it has not earned either.
        """
        with self._lock:
            self._verify(method)
            self._methods[method.id] = method
            self._reindex_aliases()
        return method


_registry: Registry | None = None
_registry_lock = threading.Lock()


def get_registry() -> Registry:
    """The process-wide Studio registry, loaded once."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = Registry().load()
        return _registry


def reload_registry() -> Registry:
    """Rebuild it. Used after a method is saved, and by tests."""
    global _registry
    with _registry_lock:
        _registry = Registry().load()
        return _registry


def _stored_methods() -> list[MethodDefinition]:
    """Bank methods from PostgreSQL, or none if storage is unavailable."""
    try:
        from backend.services.studio import bank_methods

        return bank_methods()
    except Exception as e:  # pragma: no cover - import-time safety net
        logger.warning("Bank-authored methods are unavailable: %s", e)
        return []


def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace and punctuation used inconsistently.

    "1Y ODR", "1y odr" and "1-Y ODR" are the same thing to somebody typing.
    """
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in str(text).lower())
    return " ".join(cleaned.split())


__all__ = [
    "CertificationAudit",
    "MethodNotFound",
    "Registry",
    "get_registry",
    "reload_registry",
]
