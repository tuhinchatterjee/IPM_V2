"""Offline acceptance needs no price card; live still needs a real one.

The defect this exists for
--------------------------
`RETAIL_COCKPIT_OFFLINE=1` on a machine configured from
`.env.retail-candidate.example` refused every question with a typed 503,
`CAPABILITY_UNVERIFIED: the price card config/cockpit_v4/price_card.json
carries no entry for model '...'`.

The mechanism, and it is worth stating because it is not the obvious one:
`--offline` sets `verify_model=False`, and `service.load_capability` reads
that flag at exactly ONE place -- the live probe at `service.py:141`. The
price card is read unconditionally at `service.py:136`. So offline removed
the need for a CREDENTIAL and not the need for a PRICE, and a deterministic
run that calls nothing was blocked by the absence of a price for a call it
was never going to make. `bootstrap.install` caught the `PreflightFailed`,
the runtime became `None`, and `readiness.assess` reported `release_ready`
and `sql_analysis_ready` false while `attention_ready` stayed true -- the
book was fine, the analyst could not be built.

Why these tests and not fewer
-----------------------------
Nothing in this repository exercised `capability.load_price_card` at all:
both conftests construct a `Capability` object directly and point
`price_card_path` at a file that does not exist. A fail-closed path that no
test drives is a fail-closed path that can be removed by accident, which is
the other half of what shipped. Test 1 drives it against the real shipped
card, and the rest fix the boundary either side of the fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.cockpit_v4 import capability as cap_mod
from backend.cockpit_v4 import service
from backend.retail_cockpit_host import bootstrap, offline

ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CARD = ROOT / "config" / "cockpit_v4" / "price_card.json"
TEMPLATE = ROOT / ".env.retail-candidate.example"

#: A model id that is real enough to be configured and absent from the
#: shipped placeholder card -- which is every real model, by design.
SOME_MODEL = "claude-opus-5"


class _LiveLookingProvider:
    """Not offline. Never called: every test using it must refuse first."""

    def count_tokens(self, **_: object) -> int:  # pragma: no cover - guard
        raise AssertionError("a test reached a provider it must not reach")

    def converse(self, **_: object):  # pragma: no cover - guard
        raise AssertionError("a test reached a provider it must not reach")


class _Config:
    """The two fields `load_capability` reads, and nothing else."""

    def __init__(self, model: str = SOME_MODEL,
                 card: str | Path = SHIPPED_CARD) -> None:
        self.reasoning_model = model
        self.price_card_path = str(card)
        self.provider = "anthropic"


# ---------------------------------------------------------------- the failure

def test_the_shipped_card_refuses_every_real_model() -> None:
    """The Mac failure, reproduced against the real file it names.

    Not a mock of the card: the card that ships, read by the loader that
    read it, raising the message that reached the browser.
    """
    with pytest.raises(cap_mod.CapabilityUnverified) as caught:
        cap_mod.load_price_card(SHIPPED_CARD, model_id=SOME_MODEL,
                                provider="anthropic")
    assert "carries no entry for model" in str(caught.value)
    assert SOME_MODEL in str(caught.value)


def test_a_real_provider_is_refused_by_the_shipped_card() -> None:
    """The same thing one layer up, where the 503 is actually decided."""
    with pytest.raises(service.PreflightFailed) as caught:
        service.load_capability(_Config(), _LiveLookingProvider(),
                                verify=False)
    assert caught.value.code == "CAPABILITY_UNVERIFIED"


def test_verify_model_false_alone_does_not_excuse_the_price_card() -> None:
    """`verify_model=False` is not an offline switch, and must not become one.

    This is the assertion that keeps the fix honest. If someone later gates
    the offline capability on the flag rather than the provider, a live
    deployment that happens to carry `verify_model=False` would start
    answering with no verified price, and this test is what stops it.
    """
    provider = _LiveLookingProvider()
    assert not offline.is_offline(provider)
    with pytest.raises(service.PreflightFailed):
        service.load_capability(_Config(), provider, verify=False)


# ---------------------------------------------------------------- the fix

def test_an_offline_provider_needs_no_price_card() -> None:
    capability = offline.offline_capability(_Config())
    assert capability.model_id == offline.OFFLINE_MODEL_ID
    assert capability.live_verified is False
    assert capability.verified_at == ""
    assert capability.price.to_dict() == {
        "input_usd_per_mtok": 0.0, "output_usd_per_mtok": 0.0,
        "cache_write_usd_per_mtok": 0.0, "cache_read_usd_per_mtok": 0.0}


def test_the_offline_capability_names_no_real_model() -> None:
    """A sentinel, not a choice.

    `model_capabilities` knows the ids the engine has been checked against.
    The offline capability must not be one of them, so that nothing reading a
    trace, a header or a log can take it for a model somebody selected.
    """
    from backend.cockpit_v4 import model_capabilities as caps

    assert offline.OFFLINE_MODEL_ID not in caps.REGISTRY
    assert not offline.OFFLINE_MODEL_ID.startswith("claude")


def test_the_offline_capability_says_it_authorises_nothing() -> None:
    source = offline.offline_capability(_Config()).source.lower()
    assert "authorises no paid request" in source
    assert "never live configuration" in source


def test_the_gate_is_the_provider_and_none_is_not_offline() -> None:
    """`None` means "resolve the real provider", never "offline".

    `bootstrap.build_runtime` resolves `None` into a real provider before the
    gate. Treating `None` as offline would turn a missing credential into a
    silent acceptance, which is the exact inversion of failing closed.
    """
    assert offline.is_offline(offline.OfflineProvider()) is True
    assert offline.is_offline(None) is False
    assert offline.is_offline(_LiveLookingProvider()) is False
    assert offline.is_offline(object()) is False


def test_the_offline_provider_cannot_reach_anything() -> None:
    provider = offline.OfflineProvider()
    with pytest.raises(RuntimeError, match="no provider credential"):
        provider.converse(model="anything", messages=[])
    # No client, no credential, no endpoint: there is nothing on it to call.
    for attribute in ("client", "api_key", "key", "base_url", "session",
                      "http", "_client"):
        assert not hasattr(provider, attribute), attribute


def test_bootstrap_uses_the_offline_capability_only_for_an_offline_provider(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The wiring itself, without building a book.

    `build_runtime` opens a release before it reaches the capability, so the
    branch is asserted where it is written rather than by standing up a
    runtime: `load_capability` must not be called at all for an offline
    provider, and must be called for anything else.
    """
    source = Path(bootstrap.__file__).read_text(encoding="utf-8")
    assert "if offline.is_offline(provider):" in source
    assert "capability = offline.offline_capability(cfg)" in source
    # And the live branch still goes through the engine, unchanged.
    assert re.search(r"else:\s*\n\s*capability = service\.load_capability\("
                     r"cfg, provider,\s*\n\s*verify=verify_model\)", source)


# ------------------------------------------------- the template and the runbook

def test_the_template_names_a_model_the_engine_knows(
        template_defaults) -> None:
    """The template may name a model only because an operator chose one.

    This assertion used to be "names no model at all", which was right while
    no model had been approved: the engine defaults none, and a template that
    invented one is how `claude-opus-4-1-20250805` -- retired on the
    first-party API -- ended up in a live configuration nobody had picked.

    A model is now chosen, so the protection moves rather than disappears:
    whatever is named must be one `model_capabilities` knows, because an
    unregistered id gets neutral defaults and fails quietly expensive.
    """
    from backend.cockpit_v4 import model_capabilities as caps

    model = template_defaults["AI_COCKPIT_REASONING_MODEL"]
    assert caps.traits_for(model).source == "registry", (
        f"the template names {model!r}, which is not in "
        f"model_capabilities.REGISTRY (checked {caps.CHECKED_AT}). The "
        f"engine would guess its request shape.")


def test_the_template_points_live_pricing_at_a_committed_card(
        template_defaults) -> None:
    """Never a fixture, and never a path under `var/`.

    A card under `var/` is untracked, machine-local and can be anything --
    which is exactly what a test fixture is, and why one must never become
    live configuration. This used to require the shipped placeholder, which
    was right while no model was approved; now it requires a committed card
    under `config/`, and the shipped placeholder's own fail-closed behaviour
    is asserted separately in `test_live_wiring.py`.
    """
    card = template_defaults["COCKPIT_V4_PRICE_CARD"]
    assert card.startswith("config/cockpit_v4/"), card
    assert "var/" not in card and "fixture" not in card, card
    assert (ROOT / card).exists(), f"{card} is not in the repository"


def test_the_shipped_card_still_declares_itself_a_placeholder() -> None:
    """If someone puts a real price in the committed card, this fails."""
    import json

    doc = json.loads(SHIPPED_CARD.read_text(encoding="utf-8"))
    assert list(doc["models"]) == ["REPLACE-WITH-YOUR-MODEL-ID"]
    assert "PLACEHOLDER" in doc["source"]
    assert doc["verified_at"] == ""


def test_the_runbook_does_not_stage_a_price_card_fixture() -> None:
    """The Mac sequence copied the placeholder onto a fixture path.

    It produced a "fixture" with no model entry, so it could not have helped
    on any machine, and a fixture on disk is a file live configuration can be
    pointed at. Offline needs no card, so the step is gone.
    """
    runbook = (ROOT / "docs" / "retail_cockpit" / "RUNBOOK.md").read_text(
        encoding="utf-8")
    assert "price_card.fixture.json" not in runbook
