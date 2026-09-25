"""Provider adapters bound per child run. See `build_provider`."""

from __future__ import annotations

import os
from typing import Any

from backend.model_lab.registry import Profile


class AdapterUnavailable(RuntimeError):
    pass


def build_provider(profile: Profile, *, env: dict[str, str] | None = None
                   ) -> Any:
    """A fresh provider object for ONE child. Never shared, never global."""
    env = os.environ if env is None else env
    ep = profile.raw.get("endpoint") or {}
    if profile.route == "fixture":
        from backend.model_lab.adapters.fixture import FixtureProvider
        return FixtureProvider(profile.raw["fixture_behaviour"],
                               model=profile.requested_model)
    if profile.route == "anthropic":
        key = env.get(ep.get("api_key_env") or "")
        if not key:
            raise AdapterUnavailable(f"{ep.get('api_key_env')} is not set")
        # The frozen adapter, unchanged: the Opus path inside the lab is the
        # frozen path.
        from backend.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=key)
    if profile.route in ("openai_compat", "ollama_native"):
        from backend.model_lab.adapters.openai_compat import OpenAICompatProvider
        base = env.get(ep.get("base_url_env") or "") or ep.get(
            "base_url_default")
        if not base:
            raise AdapterUnavailable("no endpoint configured")
        key_env = ep.get("api_key_env")
        key = env.get(key_env) if key_env else None
        if key_env and not key:
            raise AdapterUnavailable(f"{key_env} is not set")
        return OpenAICompatProvider(
            base_url=base, model=profile.requested_model, api_key=key,
            endpoint_class=ep.get("class", "local_loopback"),
            native_ollama=(profile.route == "ollama_native"))
    raise AdapterUnavailable(f"unknown route {profile.route}")
