"""A model that does exactly what a test tells it to. No live calls.

The analyst loop's whole contract with `backend.llm` is one method:
`structured(...) -> LLMResult`, whose `.data` conforms to the schema it was
given. So a provider that returns a scripted list of decision documents is a
complete provider as far as the loop is concerned, and every rule the loop
enforces can be tested against a model that breaks it deliberately.

This is not a stub standing in for behaviour that is untested elsewhere. It is
how you assert "a model that refuses a partly-answerable question is made to
answer it" — which you cannot do with a real model, because you cannot make a
real model refuse on demand.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.analyst.safety import Principal


class ScriptedProvider:
    """Returns the next scripted decision, and records what it was asked."""

    name = "test"
    model = "scripted"
    configured = True

    def __init__(self, script: list[dict[str, Any]]):
        self.script = list(script)
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.calls = 0

    def structured(self, *, system: str, prompt: str, schema: dict[str, Any],
                   tool_name: str, tool_description: str, **kwargs: Any):
        del schema, tool_name, tool_description, kwargs
        from backend.llm.base import LLMResult

        self.systems.append(system)
        self.prompts.append(prompt)
        self.calls += 1
        if not self.script:
            raise AssertionError(
                "The loop asked for another turn than the script provides. "
                f"It has already had {self.calls - 1}. Last prompt:\n"
                f"{prompt[-1200:]}")
        return LLMResult(data=self.script.pop(0), model=self.model)


class BrokenProvider:
    name = "test"
    model = "broken"
    configured = True

    def structured(self, **_: Any):
        raise RuntimeError("the provider is unreachable")


@pytest.fixture
def analyst():
    return Principal(user_id=1, role="ANALYST")


@pytest.fixture
def viewer():
    return Principal(user_id=2, role="VIEWER")


@pytest.fixture
def scripted():
    return ScriptedProvider
