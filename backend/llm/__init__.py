"""
Which model CreditProbe orchestrates with, decided in one place.

`AI_PROVIDER` names the provider and `AI_MODEL` optionally pins the model; the
key comes from the provider's own environment variable. Nothing else in the
codebase reads a key or constructs a client, so "is the AI configured" has one
answer and one place to change it.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from backend.config import settings
from backend.llm.anthropic_provider import DEFAULT_MODEL, AnthropicProvider
from backend.llm.base import (
    LLMError,
    LLMProvider,
    LLMResult,
    NullProvider,
    ProviderStatus,
    factories,
    register,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_provider: Any = None


def get_provider(*, refresh: bool = False) -> LLMProvider:
    """The configured provider, or NullProvider when there is no key.

    Cached: a provider holds an HTTP client, and building one per question adds
    a connection handshake to every answer.
    """
    global _provider
    with _lock:
        if _provider is not None and not refresh:
            return _provider
        _provider = _build()
        return _provider


def _build() -> LLMProvider:
    name = (settings.ai_provider or "anthropic").strip().lower()
    model = (settings.ai_model or "").strip()

    if name in {"", "none", "offline"}:
        return NullProvider(reason="AI_PROVIDER is set to offline.")

    key = _key_for(name)
    if not key:
        return NullProvider(
            reason=f"No API key is configured for the '{name}' provider.")

    build = factories().get(name)
    if build is None:
        logger.warning("Unknown AI_PROVIDER '%s'; running offline.", name)
        return NullProvider(reason=f"'{name}' is not a provider CreditProbe knows.")
    try:
        return build(key, model)
    except Exception as e:  # noqa: BLE001 - a bad provider must not stop the app
        logger.warning("Could not build the '%s' provider: %s", name, e)
        return NullProvider(reason=f"The '{name}' provider could not be built: {e}")


def _key_for(name: str) -> str:
    return {"anthropic": settings.anthropic_api_key}.get(name, "")


def provider_status() -> ProviderStatus:
    return get_provider().status()


def is_configured() -> bool:
    """Whether a real model is answering, in one expression.

    Everything that must not overstate the product's intelligence — the Cockpit
    banner, Settings, the Trace, the mode endpoint — reads this rather than
    testing for a key itself.
    """
    return get_provider().configured


__all__ = [
    "DEFAULT_MODEL",
    "AnthropicProvider",
    "LLMError",
    "LLMProvider",
    "LLMResult",
    "NullProvider",
    "ProviderStatus",
    "get_provider",
    "is_configured",
    "provider_status",
    "register",
]
