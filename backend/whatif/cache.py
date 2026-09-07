"""
The result a follow-up question is answered from.

Why this exists
---------------
"Why did Stage 3 ECL increase?" is a question about a result that is already on
the screen. Answering it by running the scenario again would be wasteful, and
worse than wasteful: it would answer a question about one set of figures with a
different set, and the person would have no way of knowing.

HTTP has no memory, so the borrower-level frame the engine produced has to be
kept somewhere between the run and the question about it. It is kept HERE — in
the process, bounded, keyed by a run id handed back to the browser, and scoped
to the person who ran it.

What this is not
----------------
It is not persistence. A restart empties it, and that is acceptable because the
engine is deterministic: the same state produces the same figures, so a miss
costs one recomputation and is SAID rather than hidden. It is not a cache in
the performance sense either — nothing here is an optimisation of a correct
answer, it is the mechanism by which the answer stays the same one.

Ownership
---------
A run is readable only by the account that produced it. The frame carries the
book at borrower grain; handing one to another reader on a guessed id would
leak the portfolio.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

CACHE_VERSION = "1.0.0"

#: How many results are held at once, across everybody. A thread is a handful
#: of runs and a person works on one at a time, so this is generous.
CAPACITY = 64


@dataclass
class Held:
    """One executed result, and who may read it back."""

    run_id: str
    owner: int | None
    result: Any
    period: str
    at: str

    def readable_by(self, owner: int | None) -> bool:
        """A run with no owner was produced without a signed-in account."""
        return self.owner is None or self.owner == owner


_LOCK = threading.Lock()
_HELD: OrderedDict[str, Held] = OrderedDict()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def put(result: Any, *, owner: int | None = None) -> str:
    """Hold a result and return the id the browser asks for it by."""
    run_id = uuid.uuid4().hex[:16]
    held = Held(run_id=run_id, owner=owner, result=result,
                period=str(getattr(result, "period", "") or ""), at=_now())
    with _LOCK:
        _HELD[run_id] = held
        _HELD.move_to_end(run_id)
        while len(_HELD) > CAPACITY:
            _HELD.popitem(last=False)
    return run_id


def get(run_id: str, *, owner: int | None = None) -> Any | None:
    """The held result, or None — never another person's."""
    key = str(run_id or "").strip()
    if not key:
        return None
    with _LOCK:
        held = _HELD.get(key)
        if held is None:
            return None
        if not held.readable_by(owner):
            return None
        _HELD.move_to_end(key)
        return held.result


def forget(run_id: str) -> None:
    with _LOCK:
        _HELD.pop(str(run_id or ""), None)


def clear() -> None:
    """Empty the store. Tests use this; nothing in the product does."""
    with _LOCK:
        _HELD.clear()


def held() -> int:
    with _LOCK:
        return len(_HELD)


def describe() -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "capacity": CAPACITY,
        "held": held(),
        "statement": (
            "A follow-up question is answered from the result it is about, "
            "not from a fresh run. Where the result is no longer held, the "
            "scenario is recomputed from its steps — deterministically, so "
            "the figures are the same — and the answer says so."),
    }


__all__ = ["CACHE_VERSION", "CAPACITY", "Held", "clear", "describe", "forget",
           "get", "held", "put"]
