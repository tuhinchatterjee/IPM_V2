"""
Who is asking, which book they may read, and where the workspace keeps things.

Identity is the V4 principal (`routes.principal`): server-derived, never read
from a request body, carrying `id`, `tenant` and `roles`. A tenant id in a query
string or a filter is never consulted -- every read below is scoped by the
principal's tenant, which is what SEC02 means.

A book is opened exactly as the Cockpit's own per-domain panels open it:
`domain_resolver.scope_for` -> `catalog.build` -> `catalog.open_session`, so a
workspace grid can never read a different release than the Cockpit beside it,
and a request cannot name an arbitrary release id (SEC03): the release is the
one the resolver says is in use for that domain.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

#: Roles that may read full LLM exchanges (prompts, tool results, raw
#: responses). The governance record already reserves SQL for
#: administrators; the full model-visible exchange is at least as sensitive.
EXCHANGE_ROLES = frozenset({"administrator", "model_risk", "auditor",
                            "operator"})


def roles_of(who: dict[str, Any]) -> set[str]:
    roles = who.get("roles") or ()
    if isinstance(roles, str):
        roles = (roles,)
    return {str(r).strip().lower() for r in roles}


def require_exchange_reader(who: dict[str, Any]) -> None:
    if not roles_of(who) & EXCHANGE_ROLES:
        raise HTTPException(403, {
            "error_code": "SECURITY_DENIED",
            "message": "The full LLM exchange is shown to administrators, "
                       "model-risk reviewers and auditors. Everything else "
                       "about the run is in its governance record."})


def tenant_of(who: dict[str, Any]) -> str:
    from backend.cockpit_v4 import lake as lake_mod

    return str(who.get("tenant") or "") or lake_mod.DEFAULT_TENANT


def principal_id(who: dict[str, Any]) -> str:
    return str(who.get("id") or "")


def v4_state() -> dict[str, Any]:
    from backend.cockpit_v4 import routes

    return routes._STATE  # the installed runtime: store, cfg, runtime


def run_store() -> Any:
    store = v4_state().get("store")
    if store is None:
        raise HTTPException(503, {"error_code": "STORAGE_UNAVAILABLE",
                                  "message": "The V4 runtime is not started."})
    return store


def config() -> Any:
    from backend.cockpit_v4 import routes

    return routes._config()


def state_dir() -> Path:
    cfg = config()
    state = Path(str(getattr(cfg, "state_database", "") or ""))
    if str(state) in ("", ".", ":memory:"):
        return Path(str(getattr(cfg, "runtime_dir", ".") or ".")
                    ).expanduser() / "state"
    return state.parent


@dataclass
class Book:
    """One domain's book as the Cockpit is serving it right now."""

    domain_id: str
    scope: Any
    session: Any
    tenant_id: str

    @property
    def release_id(self) -> str:
        return str(self.scope.release_id)

    @property
    def fingerprint(self) -> str:
        return str(self.scope.release_fingerprint)

    @property
    def latest_period(self) -> str:
        return str(self.scope.latest_period)

    @property
    def periods(self) -> list[str]:
        return list(self.scope.periods)

    def rows(self, sql: str, params: list[Any] | None = None
             ) -> list[dict[str, Any]]:
        with _SESSION_LOCK:
            cursor = self.session.connection.execute(sql, params or [])
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]


_SESSION_LOCK = threading.RLock()
_BOOKS: dict[tuple[str, str, str, str], Any] = {}
_BOOKS_LOCK = threading.Lock()


def parse_domain(domain: str) -> str:
    from backend.cockpit_v4 import domains as dom_mod

    try:
        return dom_mod.parse(domain)
    except Exception as exc:  # noqa: BLE001 - a typed refusal
        raise HTTPException(400, {"error_code": "UNKNOWN_DOMAIN",
                                  "message": str(exc)}) from exc


def book(who: dict[str, Any], domain: str) -> Book:
    """The book in use for `domain`, opened for this principal's tenant.

    Cached per (tenant, domain, release, fingerprint): a republished release
    opens a new session rather than serving the old one under a new name.
    """
    from backend.cockpit_v4 import catalog as cat_mod
    from backend.cockpit_v4 import domain_resolver as resolver

    domain_id = parse_domain(domain)
    tenant = tenant_of(who)
    try:
        scope = resolver.scope_for(domain_id, tenant_id=tenant)
    except resolver.DomainUnavailable as exc:
        raise HTTPException(503, {
            "error_code": "DATA_UNAVAILABLE", "message": str(exc),
            "domain_id": domain_id,
            "provision_command": resolver.provision_command(domain_id)
        }) from exc
    key = (tenant, domain_id, str(scope.release_id),
           str(scope.release_fingerprint))
    try:
        with _BOOKS_LOCK:
            catalog = _BOOKS.get(key)
            if catalog is None:
                catalog = cat_mod.build(domain_id=scope.domain_id,
                                        release_id=scope.release_id,
                                        tenant_id=tenant)
                _BOOKS[key] = catalog
        # `open_session` keeps its own bounded cache keyed by tenant, domain,
        # release and fingerprint; holding the catalogue (not the session)
        # here means an evicted session is simply rebuilt.
        session = cat_mod.open_session(catalog=catalog)
    except PermissionError as exc:
        raise HTTPException(403, {"error_code": "SECURITY_DENIED",
                                  "message": str(exc),
                                  "domain_id": domain_id}) from exc
    return Book(domain_id=domain_id, scope=scope, session=session,
                tenant_id=tenant)


def reset_books() -> None:
    """Tests only: forget every cached session."""
    with _BOOKS_LOCK:
        _BOOKS.clear()


__all__ = ["Book", "EXCHANGE_ROLES", "book", "config", "parse_domain",
           "principal_id", "require_exchange_reader", "reset_books",
           "roles_of", "run_store", "state_dir", "tenant_of", "v4_state"]
