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
import sys
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


# ------------------------- 2b. the UAT harness resolves it too, and FIRST

RUN_UAT = ROOT / "scripts" / "retail_cockpit" / "run_uat.py"
CHECK_ORACLES = ROOT / "scripts" / "retail_cockpit" / "check_oracles.py"


def test_the_uat_harness_resolves_the_env_file_before_it_reads_anything(
) -> None:
    """The ordering is load-bearing, so it is asserted mechanically.

    `backend/config.py` ends with `settings = _load()` at module scope and
    `lake.root()` is derived from it, so resolving after the first backend
    import leaves the harness reading a different lake than the engine serves
    from -- and `config._resolve_dir` would have created several empty
    directories in the worktree on the way past.
    """
    source = RUN_UAT.read_text(encoding="utf-8")
    assert "--env-file" in source
    # Scoped to `main()`. Every backend import in this script is inside a
    # function body, so a whole-file scan would find one that does not run
    # until it is called; what matters is the order things EXECUTE in on the
    # one path that reaches the engine.
    body = source[source.index("def main() -> int:"):]
    resolved_at = body.index("resolve_environment(args.env_file)")
    first_backend = body.index("from backend.")
    assert resolved_at < first_backend, (
        "run_uat.py imports backend before it resolves the configuration, so "
        "`settings` freezes against the operator's bare shell")


def test_the_uat_harness_preflights_what_it_already_resolved() -> None:
    """`--env-file ""`, the same rule the launcher follows.

    Letting the subprocess resolve the file a second time would read its
    `${VAR:-default}` defaults over whatever the parent settled on -- and the
    parent and its own preflight could then disagree, which is the exact
    shape of the failure being repaired.
    """
    source = RUN_UAT.read_text(encoding="utf-8")
    preflight = source[source.index("def preflight("):
                       source.index("def preflight(") + 1200]
    assert '"--env-file", ""' in preflight


@pytest.mark.parametrize("script", [RUN_UAT, CHECK_ORACLES])
def test_the_oracle_harnesses_no_longer_guess_a_relative_book(script) -> None:
    """The literal that cost USD 0.24853.

    `run_uat.py` resolved its book as a bare, CWD-relative
    `"data/retail/analytics"` -- the installation's path, which a candidate
    clone does not have. The traceback printed a relative path, which is how
    that literal was identified as the source rather than the ROOT-anchored
    default `check_oracles.py` used. Both now anchor.
    """
    source = script.read_text(encoding="utf-8")
    assert '"data/retail/analytics"' not in source, (
        "a bare relative default resolves against the process working "
        "directory, so which book is read depends on where the operator "
        "was standing")
    assert 'ROOT / "data" / "retail" / "analytics"' in source


def test_the_harness_anchors_the_book_wherever_it_is_run_from(
        tmp_path, template_defaults) -> None:
    """End to end, from a working directory that is not the repository.

    The template's own `${VAR:-default}` form, resolved by the real script,
    printed back as absolute paths. This is the behavioural half of the two
    source assertions above: it would fail if the anchoring were dropped.
    """
    env_file = tmp_path / ".env.candidate"
    env_file.write_text(
        "DATA_ANALYTICS_DIR=${DATA_ANALYTICS_DIR:-"
        + template_defaults["DATA_ANALYTICS_DIR"] + "}\n"
        "METADATA_DIR=${METADATA_DIR:-"
        + template_defaults["METADATA_DIR"] + "}\n"
        "COCKPIT_V4_RUNTIME_DIR=${COCKPIT_V4_RUNTIME_DIR:-"
        "var/retail-cockpit-candidate/runtime}\n", encoding="utf-8")

    bare = {k: v for k, v in os.environ.items()
            if k not in ("DATA_ANALYTICS_DIR", "METADATA_DIR",
                         "COCKPIT_V4_RUNTIME_DIR", "COCKPIT_V4_STATE_DATABASE")}
    done = subprocess.run(
        [sys.executable, str(RUN_UAT), "--env-file", str(env_file),
         "--rejudge",
         "--rejudge-db", str(tmp_path / "absent.sqlite3"),
         "--out", str(tmp_path / "out.json")],
        capture_output=True, text=True, cwd=str(tmp_path), env=bare)

    printed = done.stdout + done.stderr
    expected = ROOT / template_defaults["DATA_ANALYTICS_DIR"]
    assert f"analytics       {expected}" in printed, printed[:1500]
    assert f"state database  {ROOT}/var/retail-cockpit-candidate" in printed
    # It refused, because that ledger does not exist -- not because it
    # could not work out where anything was.
    assert "no state database" in printed


def test_the_harness_says_when_the_cap_is_not_guarding_it(
        tmp_path) -> None:
    """The quiet half of the same defect, made loud.

    `RETAIL_COCKPIT_SPEND_CAP_USD` lives in the env file, so in a shell that
    never sourced it the runner's own cumulative cap was `None` and
    `spend.spent()` read a ledger under `~/.creditprobe` that does not exist
    -- returning 0.0. The cap guarded nothing and every recorded cost would
    have been 0.00. It now says so before anything is bought.
    """
    bare = {k: v for k, v in os.environ.items()
            if not k.startswith(("COCKPIT_V4_", "RETAIL_COCKPIT_",
                                 "DATA_ANALYTICS", "METADATA"))}
    done = subprocess.run(
        [sys.executable, str(RUN_UAT), "--env-file", "", "--rejudge",
         "--rejudge-db", str(tmp_path / "absent.sqlite3"),
         "--out", str(tmp_path / "out.json")],
        capture_output=True, text=True, cwd=str(ROOT), env=bare)

    printed = done.stdout + done.stderr
    assert "cumulative cap  (UNSET -- this runner will not stop)" in printed


def test_a_live_run_refuses_a_configuration_file_that_is_not_there() -> None:
    """`resolve()` returns {} for a missing path, silently.

    `.env.retail-candidate` is gitignored, so a fresh candidate clone has
    none -- and a silent fall-through to the bare shell is precisely how a
    paid answer came to be judged against a book that was never there.
    """
    source = RUN_UAT.read_text(encoding="utf-8")
    assert "REFUSING TO START" in source
    done = subprocess.run(
        [sys.executable, str(RUN_UAT), "--env-file",
         str(ROOT / ".env.does-not-exist"), "--i-accept-the-cost"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert done.returncode == 1
    assert "REFUSING TO START" in done.stdout


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
