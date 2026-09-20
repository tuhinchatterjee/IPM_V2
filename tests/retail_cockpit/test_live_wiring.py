"""Live mode: the card, the caps, and the two ways money leaked.

What this covers
----------------
Going live turns every one of these from a document into a mechanism:

* the candidate price card loads through the ENGINE's own loader and yields
  the published rates -- not a fixture, not zeros, and not the shipped
  placeholder, which stays fail-closed and part of the verbatim port;
* the cumulative cap, which `LIVE_UAT_PLAN.md` promised and nothing enforced.
  `budgets.spend_ceiling_usd` bounds ONE run at 1.50 and counts nothing
  across runs, so twelve runs had eighteen dollars of headroom against a
  fifteen dollar cap;
* `check_ready.py`, which submits a real question and is run by the launcher
  on EVERY start with a fresh idempotency key. Offline that is free. Live it
  is a billed analysis, so the launcher was about to buy one run per start
  while the script's own docstring said "No provider call is made";
* the SDK's own retries. `provider.py` says "the SDK is not allowed to retry
  behind our back", but `allow_retry=False` bounds only the adapter's loop
  and `anthropic_provider` builds its client without `max_retries`, so the
  default of 2 applied and a 429 could be billed three times against one
  reservation the ledger counted once.

Nothing here makes a provider call, and nothing here reads a credential.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.cockpit_v4 import capability as cap_mod
from backend.cockpit_v4 import config as config_mod
from backend.cockpit_v4 import model_capabilities as caps
from backend.retail_cockpit_host import offline, spend

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_CARD = ROOT / "config" / "cockpit_v4" / "price_card.candidate.json"
SHIPPED_CARD = ROOT / "config" / "cockpit_v4" / "price_card.json"
TEMPLATE = ROOT / ".env.retail-candidate.example"
CHECK_READY = ROOT / "scripts" / "retail_cockpit" / "check_ready.py"
CHECK_LIVE = ROOT / "scripts" / "retail_cockpit" / "check_live.py"

MODEL = "claude-opus-5"

#: Transcribed from https://platform.claude.com/docs/en/about-claude/pricing
#: on 2026-09-20. The cache write is the 5-minute rate; the 1-hour rate is
#: 10.00 and does not apply, because the engine sends no cache_control.
PUBLISHED = {"input_usd_per_mtok": 5.0, "output_usd_per_mtok": 25.0,
             "cache_write_usd_per_mtok": 6.25, "cache_read_usd_per_mtok": 0.5}


# ------------------------------------------------------------------ the card

def test_the_candidate_card_loads_through_the_engines_own_loader() -> None:
    capability = cap_mod.load_price_card(CANDIDATE_CARD, model_id=MODEL,
                                         provider="anthropic")
    assert capability.model_id == MODEL
    assert capability.price.to_dict() == PUBLISHED
    # A card read from disk is a DECLARATION. It becomes verified when a live
    # probe confirms the provider serves the id, and not before.
    assert capability.live_verified is False


def test_the_card_names_a_model_the_engine_knows() -> None:
    """An unregistered id gets neutral defaults and fails quietly expensive.

    `traits_for` returns `DEFAULT` for an unknown model: forcing is assumed
    (a billed 400 if the model refuses it) and effort control is silently
    off, so the run thinks as hard on an action turn as on an answer.
    """
    traits = caps.traits_for(MODEL)
    assert traits.source == "registry", (
        f"{MODEL} is not in model_capabilities.REGISTRY (checked "
        f"{caps.CHECKED_AT}), so the engine would guess its request shape")
    assert traits.forced_tool_use and traits.effort_control


def test_no_billing_class_is_zero() -> None:
    """A zero price disables the per-run ceiling while reporting it enforced.

    `budgets.affordable` returns the full ask when the per-token cost is
    non-positive, so a live card left at 0.0 would run with no effective
    dollar bound at all.
    """
    price = cap_mod.load_price_card(CANDIDATE_CARD, model_id=MODEL,
                                    provider="anthropic").price
    assert all(v > 0 for v in price.to_dict().values()), price.to_dict()


def test_the_card_says_where_its_numbers_came_from() -> None:
    doc = json.loads(CANDIDATE_CARD.read_text(encoding="utf-8"))
    assert "platform.claude.com" in doc["source"]
    assert doc["verified_at"], "a live card with no verified_at"
    assert doc["models"][MODEL]["context_tokens"] > 0
    assert doc["models"][MODEL]["max_output_tokens"] > 0


def test_the_shipped_card_is_untouched_and_still_fails_closed() -> None:
    """The port stays intact and every other deployment stays fail-closed."""
    doc = json.loads(SHIPPED_CARD.read_text(encoding="utf-8"))
    assert list(doc["models"]) == ["REPLACE-WITH-YOUR-MODEL-ID"]
    with pytest.raises(cap_mod.CapabilityUnverified):
        cap_mod.load_price_card(SHIPPED_CARD, model_id=MODEL,
                                provider="anthropic")


def test_the_template_points_at_the_candidate_card_not_the_placeholder() -> None:
    body = TEMPLATE.read_text(encoding="utf-8")
    card = re.findall(r"^\s*COCKPIT_V4_PRICE_CARD=(.*)$", body, re.M)
    assert card == ["config/cockpit_v4/price_card.candidate.json"], card
    model = re.findall(r"^\s*AI_COCKPIT_REASONING_MODEL=(.*)$", body, re.M)
    assert model == [MODEL], model
    # The credential still must not be assigned: the launcher sources this
    # file under `set -a`, so an assignment here beats an exported value --
    # including an empty one, which fails with PROVIDER_CREDENTIAL_MISSING.
    assert not re.findall(r"^\s*COCKPIT_ANTHROPIC_API_KEY=", body, re.M)


# ------------------------------------------------------- the cumulative cap

def test_the_engine_still_has_no_cumulative_cap_of_its_own() -> None:
    """The premise. If this ever fails, the host guard can be retired."""
    limits = config_mod.ANALYTICAL_STANDARD_LIMITS
    assert limits.spend_ceiling_usd == 1.50
    # Every spend query the engine makes is scoped to ONE run. There is no
    # aggregate across runs anywhere, which is why twelve runs have twelve
    # times the headroom of one.
    store = (ROOT / "backend/cockpit_v4/run_store.py").read_text("utf-8")
    # SQL is written across adjacent string literals, so the quotes and the
    # whitespace between them are collapsed before the query is read.
    flat = re.sub(r"[\"'\s]+", "", store)
    spots = [m.end() for m in re.finditer("FROMreservations", flat)]
    assert spots, "the reservations table moved"
    for end in spots:
        assert "WHERErun_id=?" in flat[end:end + 40], (
            f"a spend query that is not scoped to one run: "
            f"{flat[end - 30:end + 40]!r}. If the engine has grown a "
            f"cumulative counter, the host guard in "
            f"backend/retail_cockpit_host/spend.py can be retired.")


def test_unset_the_cap_reads_nothing_and_permits(monkeypatch) -> None:
    monkeypatch.delenv(spend.CAP_VAR, raising=False)
    verdict = spend.allowed(database="/nonexistent/never/read.sqlite3")
    assert verdict.allowed and verdict.uncapped and verdict.cap_usd is None


def test_the_cap_permits_below_and_refuses_at_and_above(
        monkeypatch, ledger) -> None:
    monkeypatch.setenv(spend.CAP_VAR, "10.00")
    assert spend.allowed(database=ledger(4.0)).allowed
    # AT the cap, not merely above it: the budget is gone, and the next run
    # would cross it.
    assert not spend.allowed(database=ledger(10.0)).allowed
    assert not spend.allowed(database=ledger(12.5)).allowed


def test_an_unsettled_reservation_counts_at_what_it_reserved(
        monkeypatch, ledger) -> None:
    """Otherwise a burst of concurrent runs walks through the cap.

    Spending that has been reserved but not yet settled is real money in
    flight. Counting only settled rows would let it through.
    """
    monkeypatch.setenv(spend.CAP_VAR, "5.00")
    assert spend.spent(ledger(reserved=6.0, settled=None)) == 6.0
    # And a settled row supersedes its reservation, so a run that cost less
    # than it reserved gives the difference back.
    assert spend.spent(ledger(reserved=6.0, settled=1.25)) == 1.25


def test_a_store_that_is_not_there_has_spent_nothing() -> None:
    assert spend.spent("/nonexistent/never/written.sqlite3") == 0.0


def test_an_unreadable_cap_is_refused_rather_than_ignored(monkeypatch) -> None:
    monkeypatch.setenv(spend.CAP_VAR, "fifteen dollars")
    with pytest.raises(spend.SpendCapInvalid):
        spend.allowed()
    monkeypatch.setenv(spend.CAP_VAR, "-1")
    with pytest.raises(spend.SpendCapInvalid):
        spend.allowed()


def test_the_refusal_names_the_cap_and_the_spend() -> None:
    body = spend.refusal(spend.Verdict(allowed=False, spent_usd=15.25,
                                       cap_usd=15.0))
    assert body["error_code"] == "SPEND_CAP_REACHED"
    assert "15.00" in body["message"] and "15.25" in body["message"]


def test_only_starting_a_run_is_guarded() -> None:
    """Reading a transcript already paid for must not be refused."""
    from backend.api.routers import cockpit_v4_proxy as proxy

    assert proxy._SPENDS == "runs"
    source = Path(proxy.__file__).read_text(encoding="utf-8")
    assert 'request.method != "POST" or path.strip("/") != _SPENDS' in source
    assert "_spend_guard(request, path)" in source


# ------------------------------------------- the two ways money leaked out

def test_check_ready_does_not_buy_a_run_in_live_mode() -> None:
    """The launcher runs it on every start, with a fresh idempotency key."""
    source = CHECK_READY.read_text(encoding="utf-8")
    assert 'offline or args.allow_paid_run' in source
    assert "--allow-paid-run" in source
    # And the docstring no longer claims something true only offline.
    head = source[:source.index('"""', source.index('"""') + 3)]
    assert "No provider call is made." not in head
    assert "billed" in head


def test_check_ready_reports_a_skipped_question_as_skipped() -> None:
    source = CHECK_READY.read_text(encoding="utf-8")
    assert 'report["run"] = "skipped"' in source
    # Skipped is not passed, and it is not a finding either.
    assert 'readiness_unproven' in source


def test_the_sdk_cannot_retry_outside_the_ledger() -> None:
    from backend.llm.anthropic_provider import AnthropicProvider

    provider = offline.pin_transport(
        AnthropicProvider(api_key="not-a-real-key-and-never-used"))
    assert provider.client.max_retries == 0, (
        "the SDK would retry a 429 or a 5xx behind the ledger, so one "
        "reservation could be billed three times")


def test_pinning_leaves_an_injected_client_alone() -> None:
    """Tests inject a transport on purpose; overwriting it would break them."""
    from backend.llm.anthropic_provider import AnthropicProvider

    injected = object()
    provider = AnthropicProvider(api_key="k", client=injected)
    assert offline.pin_transport(provider).client is injected
    assert offline.pin_transport(None) is None


def test_the_bootstrap_pins_the_provider_it_resolves() -> None:
    source = Path(
        ROOT / "backend/retail_cockpit_host/bootstrap.py").read_text("utf-8")
    assert "offline.pin_transport(service.resolve_provider(cfg))" in source


# ------------------------------------------------------------- the preflight

def test_check_live_never_constructs_a_provider() -> None:
    source = CHECK_LIVE.read_text(encoding="utf-8")
    for forbidden in ("anthropic.Anthropic", "resolve_provider",
                      "AnthropicProvider", "converse", "count_tokens"):
        assert forbidden not in source, forbidden


def test_check_live_never_reads_the_credential_into_a_value() -> None:
    """Presence, never the value. A preflight that could print a key is one
    that will, in a log or a traceback."""
    source = CHECK_LIVE.read_text(encoding="utf-8")
    reads = re.findall(r"os\.environ\.get\(config_mod\.CREDENTIAL_VAR[^)]*\)",
                       source)
    assert reads, "the credential check disappeared"
    for read in reads:
        assert f"bool({read}" in source.replace("\n", " ").replace("  ", " ") \
            or f"bool({read}.strip())" in source, read


@pytest.fixture()
def ledger(tmp_path):
    """A ledger holding one reservation, with the amounts under test."""
    import sqlite3

    def _make(settled_or_total: float | None = None, *,
              reserved: float | None = None, settled: float | None = 0.0):
        if reserved is None:
            reserved, settled = float(settled_or_total or 0.0), None
        path = tmp_path / f"ledger-{reserved}-{settled}.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE reservations (reservation_id TEXT, run_id TEXT, "
            "purpose TEXT, reserved_usd REAL, settled_usd REAL, "
            "uncertain INTEGER, usage TEXT, created_at TEXT)")
        connection.execute(
            "INSERT INTO reservations VALUES ('r','run','ANALYSIS_ACTION',"
            "?,?,0,'{}','now')", (reserved, settled))
        connection.commit()
        connection.close()
        return path

    return _make
