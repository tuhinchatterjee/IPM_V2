"""The provider that cannot spend money, and what a runtime built on it may
say about itself.

The defect this exists for
--------------------------
`--offline` sets `verify_model=False`, and `service.load_capability` reads
that flag at ONE place only -- `service.py:141`, the live probe. The price
card is read unconditionally at `service.py:136`, because a price is about
money and not about liveness, and that is correct engine behaviour.

The consequence was that an offline candidate still needed a price card
carrying an entry for whatever `AI_COCKPIT_REASONING_MODEL` named. On a
machine configured from `.env.retail-candidate.example` -- the shipped
fail-closed placeholder card, whose only key is `REPLACE-WITH-YOUR-MODEL-ID`
-- `load_price_card` raised `CAPABILITY_UNVERIFIED`, `bootstrap.install`
caught it, the runtime became `None`, and every analytical route refused with
a typed 503. A deterministic acceptance run that calls nothing was being
blocked by the absence of a price for a call it was never going to make.

The rule this keeps
-------------------
Offline APPLICATION readiness and LIVE MODEL readiness are different claims
and neither may be borrowed for the other. So:

- the offline capability is reachable ONLY through `is_offline(provider)`,
  which is true for an `OfflineProvider` instance and nothing else. It is not
  gated on an environment variable, on `verify_model`, or on a file being
  absent -- all three are things a live deployment could acquire by accident.
  `OfflineProvider` holds no client, no credential and no base URL, and its
  `converse` raises unconditionally, so a runtime that reaches this capability
  is one that is PHYSICALLY unable to spend money;
- it names no real model. `model_id` is a sentinel that no provider serves,
  so no part of the system can mistake it for a model, and `live_verified`
  is False and `verified_at` empty, so nothing can mistake it for a
  verification;
- it carries no price. All four billing classes are 0.0 and `source` says in
  words that this authorises nothing. `budgets.py:138-140` treats a
  non-positive per-token cost as "no ceiling to enforce", which is the honest
  reading when no call can occur;
- it is built in this process and written to no file. A price card on disk is
  a file someone can point live configuration at; an object constructed
  behind an unusable provider is not.

Live pricing and live model verification are untouched. A real provider with
`verify_model=False` still goes through `service.load_capability` and is
still refused by a card that does not carry its model.
"""

from __future__ import annotations

from typing import Any

#: What the offline capability calls itself. Deliberately not a model id any
#: provider serves, and deliberately not a plausible one: a reader who sees
#: this in a trace, a header or a log should be unable to read it as a model
#: that was chosen, and `model_capabilities.traits_for` returns the neutral
#: default for it rather than another model's traits.
OFFLINE_MODEL_ID = "offline-no-provider"

OFFLINE_SOURCE = (
    "OFFLINE ACCEPTANCE. No provider is reachable from this runtime, so no "
    "price is declared and none is needed. This authorises no paid request "
    "and is never live configuration.")


class OfflineProvider:
    """A provider that cannot call anything. Present so a run can be driven.

    `--think SECONDS` makes it spend that long before failing, which is how
    the stream is shown to be UNBUFFERED: a proxy that held frames until the
    response completed would deliver `model.requested` and `run.failed` in
    the same instant, and the live panel exists to make that impossible.
    """

    #: Read by `is_offline`. An attribute rather than only the class, so a
    #: test double that is equally unable to call out can say so too.
    offline = True

    def __init__(self, think: float = 0.0) -> None:
        self.think = float(think)

    def count_tokens(self, **_: object) -> int:
        return 1

    def converse(self, **_: object):
        if self.think:
            import time

            time.sleep(self.think)
        raise RuntimeError(
            "This runtime has no provider credential. The run was accepted, "
            "driven and settled by the real worker; only the model call is "
            "absent.")


def is_offline(provider: Any) -> bool:
    """Is this a provider that cannot reach a paid API?

    True only for an object that declares `offline` true. `None` is NOT
    offline: `None` means "resolve the real provider", and treating it as
    offline would turn a missing credential into a silent acceptance.
    """
    return provider is not None and getattr(provider, "offline", False) is True


def offline_capability(cfg: Any = None) -> Any:
    """What a runtime with no provider behind it is allowed to say.

    The same in-process construction the scripted suites already use
    (`tests/retail_cockpit/conftest.py`), whose own comment is the contract:
    a capability object with no provider behind it authorises no paid call.
    """
    from backend.cockpit_v4 import capability as cap_mod

    return cap_mod.Capability(
        provider=str(getattr(cfg, "provider", "") or "anthropic"),
        model_id=OFFLINE_MODEL_ID,
        sdk_version="offline",
        context_tokens=200_000,
        max_output_tokens=8_192,
        supports_tools=True,
        supports_token_counting=True,
        price=cap_mod.PriceCard(input_usd_per_mtok=0.0,
                                output_usd_per_mtok=0.0,
                                cache_write_usd_per_mtok=0.0,
                                cache_read_usd_per_mtok=0.0),
        source=OFFLINE_SOURCE,
        verified_at="",
        live_verified=False)


__all__ = ["OFFLINE_MODEL_ID", "OFFLINE_SOURCE", "OfflineProvider",
           "is_offline", "offline_capability"]
