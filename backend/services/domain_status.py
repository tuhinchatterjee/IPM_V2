"""
Telling the engine which data domains have been retired.

The Data Access Layer decides which dataset answers a governed purpose, and it
must skip datasets in an archived domain. It cannot read that itself: domain
status lives in PostgreSQL and `data_access` sits at the bottom of the import
order, where it may use nothing above it. So this module sits above both and
hands the answer down, registered once at application start-up.

Cached, because resolution happens on every step of every analysis and a
database round trip there would be a tax on every question anybody asks. The
cache is cleared the moment a domain's status changes, so the decision takes
effect immediately rather than at the next restart.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: frozenset[str] | None = None


def archived_domains() -> frozenset[str]:
    """Domains the data office has retired, read once and held."""
    global _cached
    with _lock:
        if _cached is not None:
            return _cached

    names = _read()

    with _lock:
        _cached = names
    return names


def _read() -> frozenset[str]:
    """One read of the governance table. Empty when there is nothing to read."""
    from backend.config import settings

    if not settings.has_database:
        return frozenset()
    try:
        from backend.db.engine import get_session
        from backend.services.data_builder import archived_domain_names

        with get_session() as session:
            return archived_domain_names(session)
    except Exception as e:  # pragma: no cover - a governance read that failed
        # Fails OPEN. A database hiccup must not make every analysis report that
        # its data has been retired — archiving is a curation decision, not a
        # security boundary, and treating a failed read as "everything is
        # archived" would take the whole product down.
        logger.warning("Could not read archived domains: %s", e)
        return frozenset()


def archived_datasets() -> frozenset[str]:
    """Governed datasets sitting in a retired domain.

    Derived rather than stored: a domain is what gets archived, and a dataset is
    in exactly one. Keeping a second list of archived DATASETS would be a second
    thing to forget to update.
    """
    retired = archived_domains()
    if not retired:
        return frozenset()
    try:
        from backend.data_access import get_catalog

        return frozenset(
            d.name for d in get_catalog().all() if d.domain in retired)
    except Exception as e:  # pragma: no cover - fails open, as _read does
        logger.warning("Could not resolve archived datasets: %s", e)
        return frozenset()


def forget() -> None:
    """Drop the cache. Called when a domain is archived or restored."""
    global _cached
    with _lock:
        _cached = None


def install() -> None:
    """Point the Data Access Layer's authority resolver at this module."""
    from backend.data_access.authority import set_archived_domains_provider

    set_archived_domains_provider(archived_domains)


__all__ = ["archived_datasets", "archived_domains", "forget", "install"]
