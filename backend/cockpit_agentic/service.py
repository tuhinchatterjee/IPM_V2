"""
The entry point the API calls. Specification sections 7.1, 7.9 and 11.

One request, one budget, one thread update
------------------------------------------
`ask` resolves the scope server-side, opens or resumes the ledger, runs the
state machine, renders whatever it produced, and then — after the answer is
already available — makes the single bounded Sonnet call that updates the
rolling summary. Section 7.9 is explicit that the summary call failing must not
erase a completed answer, and here it cannot: the outcome is built before the
summary is attempted.

No fallback, anywhere
---------------------
There is no branch in this module that answers from anything but the Opus flow.
If the provider is missing, the catalogue does not fit, the budget runs out or
every attempt fails, the user gets a stop envelope that says so. Sections 17
and 18 forbid the alternative, and the alternative is what the previous
architecture did.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_agentic import (DEEP, DOMAIN, MODES, STANDARD,
                                     default_mode, enabled)
from backend.cockpit_agentic import ledger as ledger_mod
from backend.cockpit_agentic import profile as profile_mod
from backend.cockpit_agentic import pysandbox
from backend.cockpit_agentic import registry, sonnet, sql, states, store, thread
from backend.cockpit_agentic.contracts import Exchange, ThreadSummary
from backend.cockpit_agentic.runtime import Outcome, Runtime

logger = logging.getLogger(__name__)

DEFAULT_RELEASE = "demo-20q-v1"

#: Coverage profiles, per release. Computed from the whole release, versioned
#: with it, and reused rather than recomputed per query (section 5).
_PROFILES: dict[str, Any] = {}

#: In-memory thread state, keyed by thread id. The seam where a deployment
#: binds `backend/services/threads.py` for durable storage.
_THREADS: dict[str, thread.ThreadState] = {}


class NotAvailable(RuntimeError):
    """The Cockpit Agentic runtime is off or unbuilt. Said, not worked around."""


def available(dataset_release_id: str = DEFAULT_RELEASE) -> bool:
    if not enabled():
        return False
    try:
        store.read_manifest(dataset_release_id)
    except store.ReleaseNotFound:
        return False
    return True


def coverage_for(dataset_release_id: str) -> Any:
    """The release's measured coverage profile, computed once."""
    cached = _PROFILES.get(dataset_release_id)
    if cached is not None:
        return cached
    from backend.cockpit_agentic import generate

    manifest = store.read_manifest(dataset_release_id)
    calendar = store.load_calendar(dataset_release_id)
    frames = {relation: store.read_relation(dataset_release_id, relation)
              for relation in manifest["relations"]}
    release = generate.Release(dataset_release_id=dataset_release_id,
                               calendar=calendar, frames=frames)
    profile = profile_mod.profile_release(release)
    _PROFILES[dataset_release_id] = profile
    return profile


def thread_for(thread_id: str, dataset_release_id: str) -> thread.ThreadState:
    state = _THREADS.get(thread_id)
    if state is None:
        state = thread.ThreadState(thread_id=thread_id,
                                   dataset_release_id=dataset_release_id)
        _THREADS[thread_id] = state
    return state


@dataclass
class Answer:
    """What the API returns."""

    outcome: Outcome
    thread_id: str
    history: dict[str, Any] = field(default_factory=dict)
    summary_updated: bool = False

    def to_dict(self) -> dict[str, Any]:
        body = self.outcome.to_dict()
        body["thread_id"] = self.thread_id
        body["history"] = dict(self.history)
        body["summary_updated"] = self.summary_updated
        return body


def ask(question: str, principal: Any, *, provider: Any = None,
        thread_id: str = "", mode: str = "",
        dataset_release_id: str = DEFAULT_RELEASE,
        ui_filters: dict[str, Any] | None = None,
        request_id: str = "", pairs: int = thread.DEFAULT_PAIRS,
        referenced_exchange_ids: list[str] | None = None) -> Answer:
    """Answer one Cockpit question, end to end."""
    if not enabled():
        raise NotAvailable(
            "Cockpit Agentic V3 is switched off in this runtime. Set "
            "COCKPIT_AGENTIC_V3=true to enable it.")
    try:
        calendar = store.load_calendar(dataset_release_id)
    except store.ReleaseNotFound as e:
        raise NotAvailable(str(e)) from e

    chosen = str(mode or default_mode()).lower()
    if chosen not in MODES:
        chosen = STANDARD

    if provider is None:
        provider = _resolve_provider()

    state = thread_for(thread_id or "cockpit-default", dataset_release_id)
    limits = ledger_mod.limits_for(chosen)
    summary, selection = state.context_for(
        limits=limits, pairs=pairs,
        referenced_ids=referenced_exchange_ids)

    runtime = Runtime(
        provider=provider, principal=principal,
        dataset_release_id=dataset_release_id,
        coverage=coverage_for(dataset_release_id), calendar=calendar,
        mode=chosen, request_id=request_id)

    outcome = runtime.run(question, ui_filters=ui_filters,
                          rolling_summary=summary,
                          recent_exchanges=selection.exchanges)

    # The answer exists from here on. Nothing below can take it away.
    summary_updated = False
    if outcome.exchange is not None:
        state.record(outcome.exchange)
        try:
            updated = sonnet.update_summary(state.summary, outcome.exchange,
                                            provider, runtime.ledger)
            state.apply_summary(updated)
            summary_updated = bool(
                updated.summary_through_exchange_id
                == outcome.exchange.exchange_id)
        except Exception as e:                              # noqa: BLE001
            logger.info("The Cockpit thread summary was not updated: %s", e)

    return Answer(outcome=outcome, thread_id=state.thread_id,
                  history=selection.to_dict(), summary_updated=summary_updated)


def _resolve_provider() -> Any:
    from backend.config import settings
    from backend.llm.anthropic_provider import AnthropicProvider
    from backend.llm.base import NullProvider

    if str(settings.ai_provider).lower() == "offline" or \
            not settings.anthropic_api_key:
        return NullProvider()
    return AnthropicProvider(api_key=settings.anthropic_api_key,
                             model=settings.ai_model or
                             AnthropicProvider.model)


def diagnostics(principal: Any = None,
                dataset_release_id: str = DEFAULT_RELEASE) -> dict[str, Any]:
    """What this runtime actually is, for the badge and the handoff.

    Includes which guardrails are running raised, so a demonstration cannot be
    read as having been obtained under the specification's own numbers.
    """
    from backend.config import settings
    from backend.llm import roles

    body: dict[str, Any] = {
        "cockpit_agentic_v3": enabled(),
        "domain_id": DOMAIN,
        "available": available(dataset_release_id),
        "dataset_release_id": dataset_release_id,
        "namespace": settings.cockpit_agentic_v3_namespace,
        "default_mode": default_mode(),
        "modes": list(MODES),
        "functionality_routes": registry.verify_routes(),
        "python_execution": pysandbox.probe().as_dict(),
    }
    for mode in MODES:
        body[f"{mode}_limits"] = ledger_mod.limits_for(mode).to_dict()
        body[f"{mode}_overrides_in_force"] = ledger_mod.overrides_in_force(mode)
    body["guardrails_note"] = (
        "Any limit listed under overrides_in_force is running raised by "
        "explicit deployment configuration. The five execution submissions and "
        "three analysis rounds have no override at any level.")
    body["model_roles"] = {
        role_name: roles.role(role_name).to_dict()
        for role_name in (sonnet.SONNET_ROLE, "cockpit_reasoning")}
    body["provider"] = {
        "configured": bool(settings.anthropic_api_key),
        "note": ("With no credential configured the Cockpit reports that it "
                 "cannot answer. It does not substitute a deterministic "
                 "analysis."),
    }
    body["cost_enforced"] = ledger_mod.prices_from_settings().configured
    if not body["cost_enforced"]:
        body["cost_note"] = (
            "No model price is configured, so spend is UNKNOWN and the "
            "spending ceiling is not a control.")
    try:
        manifest = store.read_manifest(dataset_release_id)
        body["release"] = {
            "reporting_quarters": manifest["calendar"]["reporting_slots"],
            "populated_quarters": manifest["calendar"]["populated_quarters"],
            "missing_quarters": manifest["calendar"]["missing_quarters"],
            "built_at": manifest["built_at"],
            "data_version": manifest["data_version"],
            "catalog_version": manifest["catalog_version"],
            "origin": manifest["origin"],
            "not_client_data": manifest["not_client_data"],
            "rows": {k: v["rows"] for k, v in manifest["relations"].items()},
        }
    except store.ReleaseNotFound as e:
        body["release"] = {"available": False, "reason": str(e)}
    return body


__all__ = ["Answer", "DEFAULT_RELEASE", "NotAvailable", "ask", "available",
           "coverage_for", "diagnostics", "thread_for"]
