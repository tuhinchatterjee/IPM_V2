"""
Persistence for bank-authored methods.

Library methods ship as code and are reloaded from it on every start. These are
different: a bank's own measure of default, its fork of a certified method with
a threshold changed, the version history behind a model validation sign-off.
Losing those on a restart would make the Studio a toy.

Deliberately defensive in the same way the dataset catalogue is: with no
database configured — the test suite, a first boot before `docker compose up` —
the Studio degrades to the shipped library rather than failing to start. A bank
method that cannot be read is a missing method, not a broken product.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.platform import StudioMethod
from backend.studio.model import MethodDefinition

logger = logging.getLogger(__name__)


def save_method(session: Session, method: MethodDefinition, *,
                user_id: int | None = None) -> StudioMethod:
    """Insert or replace one bank-authored method."""
    row = session.scalar(
        select(StudioMethod).where(StudioMethod.method_id == method.id))
    if row is None:
        row = StudioMethod(method_id=method.id, created_by=user_id)
        session.add(row)
    row.name = method.name
    row.category = str(method.category)
    row.lifecycle = str(method.lifecycle)
    row.version = method.version
    row.forked_from = method.forked_from
    row.definition = method.to_dict(full=True)
    session.flush()
    return row


def delete_method(session: Session, method_id: str) -> bool:
    row = session.scalar(
        select(StudioMethod).where(StudioMethod.method_id == method_id))
    if row is None:
        return False
    session.delete(row)
    return True


def list_methods(session: Session) -> list[dict[str, Any]]:
    return [dict(r.definition or {})
            for r in session.scalars(select(StudioMethod)).all()]


def bank_methods() -> list[MethodDefinition]:
    """Every stored bank method, or none if storage is unavailable."""
    if not settings.has_database:
        return []
    try:
        from backend.db.engine import get_session

        with get_session() as session:
            raw = list_methods(session)
    except Exception as e:
        logger.warning("Could not read bank-authored methods: %s", e)
        return []

    out: list[MethodDefinition] = []
    for entry in raw:
        try:
            method = MethodDefinition.from_dict(entry)
        except Exception as e:
            logger.warning("Skipping unreadable stored method: %s", e)
            continue
        method.source = "bank"
        out.append(method)
    return out


def persist(method: MethodDefinition, *, user_id: int | None = None) -> bool:
    """Store a method, reporting honestly whether it survived.

    The caller needs to know: telling somebody their method is saved when it is
    not is worse than telling them the Studio is running without storage.
    """
    if not settings.has_database:
        return False
    try:
        from backend.db.engine import get_session

        with get_session() as session:
            save_method(session, method, user_id=user_id)
        return True
    except Exception as e:
        logger.warning("Could not store method %s: %s", method.id, e)
        return False


__all__ = ["bank_methods", "delete_method", "list_methods", "persist",
           "save_method"]
