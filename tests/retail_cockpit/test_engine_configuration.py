"""The engine must be asked what it loaded, not trusted to have loaded it.

The defect this exists for
--------------------------
A live UAT's first question returned 503 with no provider call and no spend.
`check_live.py` had said LIVE READY. Both were correct about different
environments:

* `check_live.py` called `config.load()`, which reads `os.environ` -- so it
  reported the price card the operator had EXPORTED;
* the launcher then did `set -a; . .env.retail-candidate; set +a`, and every
  assignment in that file was an unconditional `VAR=value`, so the file's
  `COCKPIT_V4_PRICE_CARD=config/cockpit_v4/price_card.json` overwrote the
  export;
* the engine inherited the placeholder, `load_price_card` found no
  `claude-opus-5` in it, `bootstrap.install` installed no runtime, and
  `routes.py` refused `POST /runs` with a typed 503.

Nothing compared the two, and nothing asked the engine. `/diagnostics` had
been reporting the answer the whole time.

So three things are pinned here, and the third is the one that matters:

1. the env file provides DEFAULTS -- an export wins;
2. the preflight measures the environment the launcher will use;
3. the RUNNING engine's own report of its model, card, release and state
   database is checked against what the launcher resolved.

`test_the_running_engine_agrees_with_its_configuration` is the one the user
asked for. It needs a started stack and skips without one; the launcher runs
the same assertion on every start, which is what makes a stale env file a
startup error instead of a live 503.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".env.retail-candidate.example"
LAUNCHER = ROOT / "launchers" / "retail" / "start-retail-candidate.command"
CHECK_LIVE = ROOT / "scripts" / "retail_cockpit" / "check_live.py"
CHECK_READY = ROOT / "scripts" / "retail_cockpit" / "check_ready.py"

API = os.environ.get("CANDIDATE_API_URL", "http://127.0.0.1:8329")
EXPECT_MODEL = "claude-opus-5"
EXPECT_CARD = "price_card.candidate.json"
EXPECT_RELEASE = "cockpitdata-r1.2.0-c1.0.0-s20260910-p7"


def _sourced(env_file: Path, exported: dict[str, str] | None = None
             ) -> dict[str, str]:
    """The environment a shell gets from sourcing the file, as the launcher
    does. Not a parser: the file is shell, and its `${VAR:-...}` forms only
    mean anything to a shell that already holds the environment."""
    environment = {**os.environ, **(exported or {})}
    script = (f'set -a; . "{env_file}"; set +a; '
              f'python3 -c "import json,os;print(json.dumps(dict(os.environ)))"')
    done = subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, cwd=str(ROOT), env=environment)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ------------------------------------------------- 1. the file is defaults

def test_the_template_has_no_bare_assignment_left() -> None:
    """A bare `VAR=value` is how an export gets silently overwritten."""
    bare = [line for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=(?!\$\{)", line)]
    assert not bare, (
        "these lines would clobber an exported value under `set -a`:\n  "
        + "\n  ".join(bare))


def test_an_exported_value_survives_the_template() -> None:
    """The whole of the fix, in one assertion."""
    mine = "/somewhere/of/my/own/price_card.json"
    got = _sourced(TEMPLATE, {"COCKPIT_V4_PRICE_CARD": mine})
    assert got["COCKPIT_V4_PRICE_CARD"] == mine


def test_the_template_still_supplies_defaults_when_nothing_is_exported(
        ) -> None:
    clean = {k: v for k, v in os.environ.items()
             if k not in {"COCKPIT_V4_PRICE_CARD",
                          "AI_COCKPIT_REASONING_MODEL",
                          "RETAIL_COCKPIT_SPEND_CAP_USD"}}
    script = (f'set -a; . "{TEMPLATE}"; set +a; '
              f'python3 -c "import json,os;print(json.dumps(dict(os.environ)))"')
    done = subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, cwd=str(ROOT), env=clean)
    got = json.loads(done.stdout)
    assert got["AI_COCKPIT_REASONING_MODEL"] == EXPECT_MODEL
    assert got["COCKPIT_V4_PRICE_CARD"].endswith(EXPECT_CARD)
    assert got["RETAIL_COCKPIT_SPEND_CAP_USD"] == "15.00"


def test_the_template_offers_an_isolated_uat_ledger() -> None:
    """The cap counts everything in the store, so the UAT needs its own."""
    body = TEMPLATE.read_text(encoding="utf-8")
    assert "COCKPIT_V4_STATE_DATABASE=" in body
    assert "uat.sqlite3" in body
    # Commented, because it is opt-in per UAT rather than the normal state.
    assert re.search(r"^#\s*COCKPIT_V4_STATE_DATABASE=", body, re.M)


# ------------------------------------- 2. the preflight measures what runs

def test_check_live_reads_the_env_file_not_the_bare_shell() -> None:
    source = CHECK_LIVE.read_text(encoding="utf-8")
    assert "--env-file" in source
    assert "os.environ.update(resolved)" in source


def test_a_stale_file_beats_an_export_and_the_preflight_says_so(
        tmp_path) -> None:
    """The user's failure, reproduced through the real script.

    A file with the OLD bare assignment naming the placeholder card, and an
    operator exporting the candidate card. The launcher would resolve the
    placeholder; the preflight must report the placeholder too, and refuse.
    """
    stale = tmp_path / ".env.stale"
    stale.write_text(
        "COCKPIT_V4_PRICE_CARD=config/cockpit_v4/price_card.json\n"
        f"AI_COCKPIT_REASONING_MODEL={EXPECT_MODEL}\n"
        "COCKPIT_AGENTIC_V4=true\n", encoding="utf-8")
    done = subprocess.run(
        ["python3", str(CHECK_LIVE), "--env-file", str(stale), "--json"],
        capture_output=True, text=True, cwd=str(ROOT),
        env={**os.environ, "COCKPIT_V4_PRICE_CARD":
             str(ROOT / "config/cockpit_v4/price_card.candidate.json")})
    assert done.returncode != 0, "the preflight passed a configuration that " \
                                 "cannot answer a question"
    report = json.loads(done.stdout)
    assert report["price_card"].endswith("price_card.json")
    assert not report["price_card"].endswith(EXPECT_CARD)
    assert any("carries no entry for model" in f for f in report["findings"])


# --------------------------------- 3. the engine is asked, not trusted

def test_check_ready_compares_the_running_engine_with_the_intent() -> None:
    source = CHECK_READY.read_text(encoding="utf-8")
    assert "/diagnostics" in source
    for flag in ("--expect-model", "--expect-card", "--expect-release"):
        assert flag in source, flag
    # The DOMAIN release, not `settings.release_id` -- that is the engine's
    # pre-domain release, which this candidate never publishes and which
    # legitimately stays at the engine's own default.
    assert 'report.get("book") or {}).get("release_id")' in source
    assert "the RUNNING engine's price card is" in source


def test_the_launcher_preflights_live_and_verifies_the_engine() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "check_live.py --env-file \"\"" in source, (
        "the launcher must check the environment it has ALREADY resolved; "
        "resolving the file a second time would read its defaults over an "
        "operator's export")
    for flag in ("--expect-model", "--expect-card", "--expect-release"):
        assert flag in source, flag
    # And it says out loud what it resolved to, because invisible is how the
    # mismatch survived.
    for line in ('say "  model', 'say "  card', 'say "  state', 'say "  cap'):
        assert line in source, line


def _diagnostics() -> dict:
    import httpx

    try:
        reply = httpx.get(f"{API}/api/v1/cockpit-v4/diagnostics", timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no candidate stack on {API}: {exc}")
    if reply.status_code != 200:
        pytest.skip(f"the stack on {API} answered {reply.status_code}")
    return reply.json()


def test_the_running_engine_agrees_with_its_configuration() -> None:
    """THE assertion. Not the file, not the shell: the process.

    Skips without a started stack; the launcher runs the same comparison on
    every start, which is what turns a stale env file into a startup error
    instead of a 503 on the first live question.
    """
    settings = _diagnostics().get("settings") or {}
    assert settings.get("reasoning_model") == EXPECT_MODEL, settings
    assert str(settings.get("price_card_path") or "").endswith(EXPECT_CARD), \
        settings
    state = str(settings.get("state_database") or "")
    assert "retail-cockpit-candidate" in state, (
        f"the engine's ledger is at {state!r}, outside the candidate's own "
        f"runtime directory")


def test_the_running_engine_opened_the_candidate_book() -> None:
    import httpx

    try:
        reply = httpx.get(f"{API}/api/v1/cockpit-v4/domains", timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no candidate stack on {API}: {exc}")
    if reply.status_code != 200:
        pytest.skip(f"the stack answered {reply.status_code}")
    books = {b["domain_id"]: b for b in reply.json().get("domains", [])}
    assert books["retail"]["release_id"] == EXPECT_RELEASE, books["retail"]


def test_the_running_engine_carries_a_card_that_prices_its_model() -> None:
    """The exact condition whose absence produced the 503."""
    from backend.cockpit_v4 import capability as cap_mod

    settings = _diagnostics().get("settings") or {}
    card = ROOT / str(settings.get("price_card_path") or "")
    model = str(settings.get("reasoning_model") or "")
    capability = cap_mod.load_price_card(card, model_id=model,
                                         provider="anthropic")
    assert capability.model_id == model
    assert all(v > 0 for v in capability.price.to_dict().values())
