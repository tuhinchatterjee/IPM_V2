"""The validated answer, stored against its run key. §11.

Cached AFTER validation, never before
--------------------------------------
The order matters more than the storage. An entry is written only once the
tools have run, the permission checks have passed, the invariants have held
and every figure has been grounded against the evidence. Caching a draft would
turn one bad answer into a permanently reproducible one, which is worse than
producing it twice.

One entry per (question, permission scope)
------------------------------------------
The scope is part of the key rather than a filter over a shared entry, so a
result computed for one principal cannot be handed to another however the
storage behaves. That is a structural guarantee rather than a checked one.

In-process, and honest about it
--------------------------------
This holds answers for the life of the process, bounded, with the oldest
evicted first. It is not shared across replicas and does not survive a
restart: a miss costs a recomputation, and the recomputation is deterministic,
so a miss changes latency and never changes the answer. Persisting it is a
deployment decision that needs a table and a retention policy, and inventing
either here would be inventing bank policy.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

ANSWERS_VERSION = "1.0.0"

#: Entries held in this process. Each is a small JSON document.
MAX_ENTRIES = 256


@dataclass
class StoredAnswer:
    """One validated answer, and the identity it is valid for."""

    key: str
    question: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: The evidence ledger's hash at the time. Recorded so a stored answer can
    #: be checked against a recomputed one rather than trusted.
    evidence_hash: str = ""
    answer_hash: str = ""
    run_key: dict[str, Any] = field(default_factory=dict)
    hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "question": self.question,
                "evidence_hash": self.evidence_hash,
                "answer_hash": self.answer_hash,
                "run_key": dict(self.run_key), "hits": self.hits}


class Store:
    """A bounded, thread-safe map from run key to validated answer."""

    def __init__(self, limit: int = MAX_ENTRIES):
        self._entries: OrderedDict[str, StoredAnswer] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def get(self, key: str) -> StoredAnswer | None:
        with self._lock:
            found = self._entries.get(key)
            if found is None:
                return None
            found.hits += 1
            self._entries.move_to_end(key)
            return found

    def put(self, entry: StoredAnswer) -> StoredAnswer:
        with self._lock:
            self._entries[entry.key] = entry
            self._entries.move_to_end(entry.key)
            while len(self._entries) > self._limit:
                self._entries.popitem(last=False)
            return entry

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_STORE = Store()


def store() -> Store:
    return _STORE


def remember(run_key: Any, question: str, payload: dict[str, Any], *,
             evidence_hash: str = "") -> StoredAnswer:
    """Store a VALIDATED answer. The caller has already checked it."""
    from backend.analyst.evidence import digest

    entry = StoredAnswer(
        key=run_key.key, question=question, payload=payload,
        evidence_hash=evidence_hash, answer_hash=digest(payload),
        run_key=run_key.to_dict())
    return _STORE.put(entry)


def recall(run_key: Any) -> StoredAnswer | None:
    return _STORE.get(run_key.key)


__all__ = ["ANSWERS_VERSION", "MAX_ENTRIES", "StoredAnswer", "Store",
           "recall", "remember", "store"]
