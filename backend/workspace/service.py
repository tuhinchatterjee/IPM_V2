"""Where the workspace store lives, and the object service over it."""

from __future__ import annotations

from typing import Any

from backend.workspace import access
from backend.workspace.objects import ObjectService, Principal
from backend.workspace.store import WorkspaceStore, store_at

_OVERRIDE: dict[str, Any] = {}


def store() -> WorkspaceStore:
    if "store" in _OVERRIDE:
        return _OVERRIDE["store"]
    return store_at(access.state_dir() / "workspace.sqlite3")


def objects() -> ObjectService:
    return ObjectService(store())


def principal(who: dict[str, Any]) -> Principal:
    return Principal.of(who)


def use_store(value: WorkspaceStore | None) -> None:
    """Tests: point the service at a specific store (None restores default)."""
    if value is None:
        _OVERRIDE.pop("store", None)
    else:
        _OVERRIDE["store"] = value


__all__ = ["objects", "principal", "store", "use_store"]
