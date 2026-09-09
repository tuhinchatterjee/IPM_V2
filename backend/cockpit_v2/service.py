"""
The Cockpit V2 entry point. Brief §1.3, §7.3, §9.

The single place the rest of the application calls into this package, and the
only place the feature switch is read on the request path. Everything is inert
when the switch is off: `enabled()` returns False, `answer()` returns None, and
`backend/api/routers/ask.py` takes exactly the path it took on the base commit.

Conversation
------------
`turns` carries the previous requests so a follow-up — "only Construction",
"now exclude new facilities", "and the previous quarter?" — keeps the intent it
should keep and resets the filters it should reset. The structured continuation
lives here, not in a prompt, so it cannot be paraphrased away.

Budgets
-------
Investigation budgets are class-dependent rather than flat, and the budget
actually used is recorded for the Trace. The deterministic composer spends no
model calls at all, which is the honest reason its budget use is zero — not a
claim of efficiency.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.cockpit_v2 import ANSWER_VERSION, DATA_VERSION, enabled
from backend.cockpit_v2 import answer as answer_mod
from backend.cockpit_v2 import budgets as budgets_mod
from backend.cockpit_v2 import reader
from backend.cockpit_v2 import scope as scope_mod
from backend.cockpit_v2 import understand as understand_mod

logger = logging.getLogger(__name__)


def available(principal: Any = None) -> bool:
    """Whether Cockpit V2 can answer in this runtime.

    Both halves matter: the switch must be on AND the demo must actually be
    published. A runtime with the switch on and an empty lake must fall back to
    the base path rather than answer from nothing.
    """
    if not enabled():
        return False
    try:
        return bool(reader.published_quarters(principal))
    except Exception:  # noqa: BLE001 - an unreadable lake is not available
        return False


def _previous(turns: list[dict[str, Any]] | None
              ) -> understand_mod.Request | None:
    """The last turn's reading, so a follow-up can inherit from it."""
    for turn in reversed(turns or []):
        question = str(turn.get("question") or "")
        if question:
            return understand_mod.read(question)
    return None


def answer(question: str, principal: Any = None, *,
           turns: list[dict[str, Any]] | None = None,
           clarification: str = "",
           to_period: str = "", from_period: str = "") -> dict[str, Any] | None:
    """Answer one Cockpit question, or return None to leave it to the base path."""
    if not available(principal):
        return None

    started = time.perf_counter()
    previous = _previous(turns)
    text = question
    if to_period:
        text = f"{text} (selected quarter {to_period})"
    if from_period:
        text = f"{text} (comparison quarter {from_period})"

    try:
        composed = answer_mod.compose(text, principal, previous=previous,
                                      clarification=clarification)
    except Exception:  # noqa: BLE001 - the base path still answers
        logger.exception("Cockpit V2 could not compose an answer")
        return None

    budget = budgets_mod.for_request(composed.request)
    payload = composed.to_dict()
    payload.update({
        "question": question,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "cockpit_v2": True,
        "budget": budget.to_dict(),
        "model_calls": 0,
        "model_calls_note": (
            "This answer was composed by the governed deterministic path and "
            "made no model call. That is a statement about which path ran, "
            "not a claim that it is cheaper than a path that did not run."),
    })
    payload["trace"]["budget"] = budget.to_dict()
    return payload


def diagnostics(principal: Any = None) -> dict[str, Any]:
    """The demo badge's payload. Brief §1.3.

    Enough to PROVE which backend and which data the browser is talking to:
    the branch and commit, the dataset version and checksum, the selected
    quarter and the isolation state. Paths and connection details are
    sanitized — the database NAME appears, never its URL.
    """
    from backend.cockpit_v2 import guard, persist

    manifest = persist.read_manifest()
    targets = guard.resolve_targets()
    try:
        quarters = reader.published_quarters(principal)
    except Exception:  # noqa: BLE001
        quarters = []

    commit = branch = ""
    try:
        from backend.build_info import build_info

        info = build_info() if callable(build_info) else {}
        commit = str(info.get("commit", ""))[:12]
        branch = str(info.get("branch", ""))
    except Exception:  # noqa: BLE001 - a missing build stamp is not an error
        pass

    return {
        "cockpit_intelligence_v2": enabled(),
        "available": available(principal),
        "answer_version": ANSWER_VERSION,
        "data_version": manifest.get("data_version", DATA_VERSION),
        "model_version": manifest.get("model_version", ""),
        "policy_version": manifest.get("policy_version", ""),
        "branch": branch, "commit": commit,
        "published_quarters": quarters,
        "selected_quarter_default": quarters[-1] if quarters else None,
        "dataset_checksums": manifest.get("quarter_checksums", {}),
        "reporting_currency": manifest.get("reporting_currency", ""),
        "amount_unit": manifest.get("amount_unit", ""),
        "coverage": manifest.get("coverage", {}),
        "isolation": {
            # Directory basenames and the database NAME only. Never a URL,
            # never a credential.
            "analytics_dir": targets.analytics_dir.rsplit("/", 2)[-2:],
            "metadata_dir": targets.metadata_dir.rsplit("/", 2)[-2:],
            "database_name": targets.database_name,
            "namespace": targets.namespace,
        },
        "scope": scope_mod.describe(principal),
        "synthetic": answer_mod.SYNTHETIC_BANNER,
    }


__all__ = ["answer", "available", "diagnostics"]
