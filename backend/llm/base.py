"""
What CreditProbe needs from a language model, and nothing more.

The orchestrator asks a model for exactly one thing: a **structured document**
that conforms to a schema CreditProbe supplied. It never asks for prose that will
be parsed into a decision, and it never asks for a figure. That constraint is
what lets the provider be swapped without touching the analytical path, and it
is why this interface has one method.

Why schema-constrained rather than "return JSON"
------------------------------------------------
A model asked for JSON in prose returns JSON *most* of the time. The failure is
not that parsing throws — that is recoverable — but that a plausible-looking
object with a misspelled key silently loses a filter, and the analysis then
answers a slightly different question with complete confidence. So the schema is
enforced at the provider boundary: the model is given a tool whose input schema
IS the contract, and a reply that does not call that tool is an error rather
than something to salvage.

Why no streaming
----------------
Nothing downstream can start until the whole plan is known — the validator
rejects partial plans by construction. Streaming would add a failure mode and
buy nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """The provider could not produce a conforming answer.

    Deliberately not split into subclasses per failure kind. Every caller does
    the same thing — records that the model was unavailable and degrades — and a
    taxonomy nobody switches on is decoration.
    """


@dataclass(frozen=True)
class LLMResult:
    """One structured answer, with what it cost to get it."""

    data: dict[str, Any]
    model: str
    #: Wall-clock, so a slow provider is visible in the Trace rather than felt.
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: Set when the provider retried. Recorded because a plan that took three
    #: attempts is worth knowing about even though it succeeded.
    attempts: int = 1
    #: The provider's own identifier for the call. Safe to show, and the only
    #: handle a provider can trace a request by on their side.
    request_id: str = ""


@dataclass(frozen=True)
class ProviderStatus:
    """What Settings and the Cockpit show about the AI.

    `configured` is the only field anything branches on. The rest is display,
    and none of it may ever carry the key — `detail` is written for a screen a
    user can screenshot.
    """

    provider: str
    model: str
    #: A key exists. Necessary for the model to answer, and never sufficient —
    #: `state` is what says whether it actually does.
    configured: bool
    #: offline | configured | connected | degraded. See backend/llm/telemetry.
    state: str
    detail: str
    #: The full observed health, for Settings and the header chip. Empty for a
    #: provider that has never been called.
    health: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        from backend.llm import telemetry

        return telemetry.LABELS.get(self.state, self.state.upper())

    @property
    def live(self) -> bool:
        """Whether a real structured response has actually come back."""
        from backend.llm import telemetry

        return self.state == telemetry.CONNECTED

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model,
                "configured": self.configured, "state": self.state,
                "label": self.label, "live": self.live, "detail": self.detail,
                "health": dict(self.health)}


class LLMProvider(Protocol):
    """A model CreditProbe can orchestrate with."""

    name: str
    model: str

    @property
    def configured(self) -> bool:
        """Whether this provider can actually be called."""
        ...

    def status(self) -> ProviderStatus:
        ...

    def structured(self, *, system: str, prompt: str, schema: dict[str, Any],
                   tool_name: str, tool_description: str,
                   max_tokens: int = 2000,
                   purpose: str = "reading",
                   model: str = "",
                   role: str = "", effort: str = "") -> LLMResult:
        """Return a document conforming to `schema`, or raise LLMError.

        `role` and `effort` are recorded on the call rather than inferred from
        `purpose`. An administrator who configured four models needs to see
        which one actually answered, and a product that reports differentiated
        routing it is not performing is one whose certification means nothing.

        `model` names the model to serve THIS call, so a configured role can be
        answered by the model an administrator chose for it. Empty means the
        provider's configured default. A provider that cannot serve the named
        model must fail rather than substitute one: an answer from a different
        model than the one certified is an answer with no certification.

        `purpose` names the stage the call belongs to — reading, repair,
        interpretation, validation — so a failure can be attributed to a stage
        rather than to "the AI".
        """
        ...


@dataclass
class NullProvider:
    """No model is configured.

    It raises rather than inventing an answer. The product's offline behaviour
    is decided one level up, where it can be *labelled* — a provider that
    quietly returned something plausible would make LIMITED OFFLINE MODE
    unreportable, which is the specific dishonesty this class exists to avoid.
    """

    name: str = "none"
    model: str = ""
    reason: str = "No AI provider key is configured."

    @property
    def configured(self) -> bool:
        return False

    def status(self) -> ProviderStatus:
        from backend.llm import telemetry

        return ProviderStatus(
            provider="none", model="", configured=False,
            state=telemetry.OFFLINE,
            # Not "LIMITED OFFLINE MODE". A deployment with no external
            # provider is not a broken deployment: the deterministic reader
            # parses the question and the governed runtime executes it, and
            # on a bank network that refuses egress it is the only permitted
            # configuration. The detail names the mode and its one real
            # limitation - phrasing, not capability - rather than reading to
            # a client as an outage.
            detail=(self.reason + " CreditProbe is running as a GOVERNED "
                    "LOCAL READER: questions are read by a deterministic "
                    "semantic planner over the governed catalogue, which "
                    "understands credit concepts but not arbitrary "
                    "phrasing."),
            health=telemetry.health(provider="none", model="",
                                    configured=False))

    def structured(self, **_: Any) -> LLMResult:
        raise LLMError(self.reason)


#: Registered provider factories, by the value of AI_PROVIDER.
_FACTORIES: dict[str, Any] = {}


def register(name: str, factory: Any) -> None:
    _FACTORIES[name] = factory


def factories() -> dict[str, Any]:
    return dict(_FACTORIES)


__all__ = ["LLMError", "LLMProvider", "LLMResult", "NullProvider",
           "ProviderStatus", "factories", "register"]
