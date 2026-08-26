"""
Which model does which job, and how much of it to spend.

Why roles rather than one model
-------------------------------
CreditProbe asks a model four different things, and they are not the same
difficulty:

* **routing** — is this a catalogue question or an analysis? Short, structured,
  and answered correctly by a fast model almost every time.
* **planning** — read a compound multi-domain request into a governed plan. The
  hardest thing in the product, and where an error is most expensive: a plan
  that is subtly wrong produces a confident, reconciled, wrong answer.
* **interpretation** — say in a sentence what a computed result means. Bounded,
  because the figures are already fixed and the model may not add any.
* **critic** — repair a plan the validator rejected, told what was wrong.

Sending all four to one model means either paying planning prices for routing
or accepting planning quality from a routing model. Neither is a decision worth
making by accident, so the roles are configuration.

No invented model ids
---------------------
Nothing here names a model. Every id comes from the environment; where a role
has no id of its own it falls back to `AI_MODEL`, and where that is empty the
provider's own pinned default applies. A configured id that the provider cannot
serve is a **configuration failure that says so**, not a silent substitution —
a demo answered by a different model from the one that was certified is a demo
whose certification means nothing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

ROUTER = "router"
PLANNER = "planner"
INTERPRETATION = "interpretation"
CRITIC = "critic"

ROLES: tuple[str, ...] = (ROUTER, PLANNER, INTERPRETATION, CRITIC)

#: Which environment variable names each role's model, and how hard it should
#: think. Effort is passed through only where the provider supports it.
_ENV: dict[str, tuple[str, str]] = {
    ROUTER: ("AI_ROUTER_MODEL", "AI_ROUTER_EFFORT"),
    PLANNER: ("AI_PLANNER_MODEL", "AI_PLANNER_EFFORT"),
    INTERPRETATION: ("AI_INTERPRETATION_MODEL", "AI_INTERPRETATION_EFFORT"),
    CRITIC: ("AI_CRITIC_MODEL", "AI_CRITIC_EFFORT"),
}

#: What each role is for, shown in Settings so an administrator configuring
#: four model ids knows which is which.
PURPOSE: dict[str, str] = {
    ROUTER: "Reads what kind of request this is. Short and structured.",
    PLANNER: "Turns a request into a governed analytical plan. The hardest "
             "job, and the one where an error is most expensive.",
    INTERPRETATION: "Says what a computed result means, without adding a "
                    "figure to it.",
    CRITIC: "Repairs a plan the validator rejected, told what was wrong.",
}

#: Effort levels a provider may be asked for. Ordered.
EFFORTS: tuple[str, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class Role:
    """One configured job, and the model that does it."""

    name: str
    model: str
    effort: str = ""
    #: True when nothing was configured for this role and it inherited AI_MODEL
    #: or the provider default. Reported rather than hidden: an administrator
    #: who set three of four ids should be able to see the fourth.
    inherited: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.name, "model": self.model, "effort": self.effort,
                "inherited": self.inherited, "purpose": PURPOSE.get(self.name, "")}


class ConfigurationError(RuntimeError):
    """A role is configured with something the provider cannot serve."""


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def role(name: str) -> Role:
    """The model and effort for one job."""
    from backend.config import settings

    model_var, effort_var = _ENV.get(name, ("", ""))
    configured = _env(model_var) if model_var else ""
    effort = (_env(effort_var) if effort_var else "").lower()
    if effort and effort not in EFFORTS:
        logger.warning("%s=%r is not one of %s; ignoring it.",
                       effort_var, effort, ", ".join(EFFORTS))
        effort = ""

    if configured:
        return Role(name=name, model=configured, effort=effort, inherited=False)

    shared = (settings.ai_model or "").strip()
    return Role(name=name, model=shared, effort=effort, inherited=True)


def all_roles() -> list[Role]:
    return [role(name) for name in ROLES]


def describe() -> dict[str, Any]:
    """What Settings shows about model configuration. Never a key."""
    from backend.config import settings

    configured = all_roles()
    return {
        "provider": (settings.ai_provider or "").strip().lower(),
        "shared_model": (settings.ai_model or "").strip(),
        "roles": [r.to_dict() for r in configured],
        "distinct_models": sorted({r.model for r in configured if r.model}),
        "all_inherited": all(r.inherited for r in configured),
    }


def verify(provider: Any) -> list[str]:
    """Problems with how the roles are configured, in plain sentences.

    Returned rather than raised. A misconfigured role must be *visible* —
    Settings shows it, the release gate refuses on it — but it must not stop
    the application from starting, because an administrator cannot fix a
    configuration on a server that will not boot.
    """
    problems: list[str] = []
    supported = set(getattr(provider, "supported_models", None) or ())
    for configured in all_roles():
        if configured.inherited or not configured.model:
            continue
        if supported and configured.model not in supported:
            problems.append(
                f"{_ENV[configured.name][0]} is set to {configured.model!r}, "
                f"which {getattr(provider, 'name', 'the provider')} does not "
                "list. CreditProbe will not silently use a different model: "
                "fix the id or clear the variable to inherit AI_MODEL.")
    return problems


__all__ = [
    "CRITIC",
    "EFFORTS",
    "INTERPRETATION",
    "PLANNER",
    "PURPOSE",
    "ROLES",
    "ROUTER",
    "ConfigurationError",
    "Role",
    "all_roles",
    "describe",
    "role",
    "verify",
]
