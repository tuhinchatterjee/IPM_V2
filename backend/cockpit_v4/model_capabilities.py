"""What a model can be asked to do. Not what it costs.

Why this is not in the price card
---------------------------------
It was. `supports_forced_tool_use` and `supports_effort_control` were read
from `price_card.json`, which is a file about money: four billing classes,
a verified-at date, and the provider's published schedule. Whether a model
accepts `tool_choice: {"type": "tool", "name": ...}` is a fact about the
PROVIDER'S API, not about its price, and an operator updating a price is
not thereby making a claim about a request parameter.

Two consequences of the old arrangement, both bad. A deployment that had
not touched its price card silently ran without effort control, so an
action turn thought as hard as a final answer and took as long. And a
reader looking for "does this model support forced tool use?" had to open
a pricing document to find out.

So: a registry keyed by model id, with what each family is known to accept,
and one conservative default for anything unknown. Capability failures are
still caught at runtime -- a model that rejects a parameter has it dropped
for the rest of the run and the call report says so -- but the registry is
what the request is built from.

Sources for the entries below are the provider's published tool-use and
output-configuration documentation as of this card's date. Where a model is
not listed, the defaults apply and the run finds out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The date these entries were checked against the provider's documentation.
CHECKED_AT = "2026-09-15"


@dataclass(frozen=True)
class ModelTraits:
    """Request parameters this model is known to accept."""

    #: `tool_choice: {"type": "any"}` -- the turn must call SOME tool.
    forced_tool_use: bool = True
    #: `tool_choice: {"type": "tool", "name": "..."}` -- the turn must call
    #: THAT tool. Same mechanism, so a model that refuses one refuses both;
    #: kept separate because a future model could offer only the weaker one.
    named_tool_forcing: bool = True
    #: `output_config: {"effort": "low"|...}`. A model that does not know it
    #: REJECTS the request rather than ignoring it, so this is off unless a
    #: family is known to accept it.
    effort_control: bool = False
    #: `disable_parallel_tool_use` alongside a tool choice.
    single_tool_per_turn: bool = True
    source: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return {"forced_tool_use": self.forced_tool_use,
                "named_tool_forcing": self.named_tool_forcing,
                "effort_control": self.effort_control,
                "single_tool_per_turn": self.single_tool_per_turn,
                "source": self.source, "checked_at": CHECKED_AT}


#: Families that accept forced tool use AND effort control.
_MODERN = ModelTraits(forced_tool_use=True, named_tool_forcing=True,
                      effort_control=True, source="registry")

#: Families that REJECT forced tool use. `tool_choice` `any` and `tool` both
#: answer 400 there, so the request is built with neither and the analyst is
#: told in words which action the state allows. Effort control is accepted.
_NO_FORCING = ModelTraits(forced_tool_use=False, named_tool_forcing=False,
                          effort_control=True, source="registry")

#: Older families: tools yes, effort no.
_CLASSIC = ModelTraits(forced_tool_use=True, named_tool_forcing=True,
                       effort_control=False, source="registry")

#: An unknown model. Forcing is nearly universal and is caught at runtime if
#: it is not; effort control is newer, so it is not assumed.
DEFAULT = ModelTraits(source="default")

#: Matched on the longest id PREFIX, so a dated snapshot of a known family
#: inherits its family's traits rather than falling back to the default.
REGISTRY: dict[str, ModelTraits] = {
    "claude-opus-5": _MODERN,
    "claude-opus-4-8": _MODERN,
    "claude-opus-4-7": _MODERN,
    "claude-opus-4-6": _MODERN,
    "claude-sonnet-5": _MODERN,
    "claude-sonnet-4-6": _MODERN,
    "claude-fable-5-1": _NO_FORCING,
    "claude-mythos-5-1": _NO_FORCING,
    "claude-fable-5": _MODERN,
    "claude-mythos-5": _MODERN,
    "claude-haiku-4-5": _CLASSIC,
    "claude-sonnet-4-5": _CLASSIC,
    # The test runtimes. Named here rather than left to the default so a
    # suite exercises the same code path a deployment does.
    "mock-analyst": _MODERN,
}


def traits_for(model_id: str) -> ModelTraits:
    """What this model accepts. Longest matching prefix wins."""
    name = str(model_id or "").strip()
    if not name:
        return DEFAULT
    if name in REGISTRY:
        return REGISTRY[name]
    best = ""
    for known in REGISTRY:
        if name.startswith(known) and len(known) > len(best):
            best = known
    return REGISTRY[best] if best else DEFAULT


__all__ = ["CHECKED_AT", "DEFAULT", "REGISTRY", "ModelTraits", "traits_for"]
