"""The Cockpit has its own Anthropic credential, and only its own.

`ANTHROPIC_API_KEY` is the conventional name, and in this deployment it is
also the name the Claude Code agent uses for its own provider access. Sharing
it would mean the product's calls were authenticated and billed against
whatever account happened to be driving the tooling, with no way afterwards to
separate the two and no way to revoke one without breaking the other.

So the Cockpit reads `COCKPIT_ANTHROPIC_API_KEY` and nothing else. These tests
prove the "and nothing else" part, which is the half that rots: a fallback
added later for convenience would make every one of them pass except the ones
below.

The other half is that the value never escapes. That is harder to test
exhaustively — a secret can leak through any string anything builds — so the
tests here cover the paths a secret actually travels: diagnostics, the answer
envelope, the model trace, the ledger, exceptions, and the provider's own
repr, which leaked it until this change.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from backend.cockpit_agentic import credential as C
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider

#: Unmistakable, and nothing like a real key. If this string turns up anywhere
#: a test looks, it got there from the environment and not by coincidence.
SECRET = "sk-ant-COCKPIT-TEST-SECRET-DO-NOT-LEAK-0123456789"
OTHER = "sk-ant-CLAUDE-CODE-OWN-KEY-SHOULD-NOT-BE-USED-987"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """Every test starts with no credential of any kind."""
    for name in (C.COCKPIT_CREDENTIAL_VAR, *C.FORBIDDEN_FALLBACKS):
        monkeypatch.delenv(name, raising=False)
    yield


# ============================================ A. present means present

def test_the_cockpit_credential_is_read_when_it_is_set(monkeypatch):
    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    assert C.present() is True
    assert C.status() == "PRESENT"
    assert C.require() == SECRET


def test_the_provider_the_cockpit_builds_carries_that_credential(monkeypatch):
    """The end the whole change is for: the provider object the Cockpit hands
    to the model calls is authenticated with the application's own key."""
    from backend.cockpit_agentic import service

    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    monkeypatch.setattr("backend.config.settings",
                        dataclasses.replace(_settings(), ai_provider="anthropic"))
    provider = service._resolve_provider()
    assert provider.api_key == SECRET
    assert provider.configured is True


def _settings():
    from backend.config import settings
    return settings


def test_whitespace_is_not_a_credential(monkeypatch):
    for blank in ("", "   ", "\t\n"):
        monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, blank)
        assert C.present() is False
        with pytest.raises(C.ProviderCredentialMissing):
            C.require()


# ==================== B and C. nothing else can stand in for it

def test_anthropic_api_key_cannot_substitute(monkeypatch):
    """The named case: Claude Code's own credential is set, the Cockpit's is
    not, and the Cockpit still fails closed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", OTHER)
    assert C.present() is False
    with pytest.raises(C.ProviderCredentialMissing) as caught:
        C.require()
    assert caught.value.status == "PROVIDER_CREDENTIAL_MISSING"
    assert C.COCKPIT_CREDENTIAL_VAR in str(caught.value)


@pytest.mark.parametrize("variable", C.FORBIDDEN_FALLBACKS)
def test_no_other_credential_variable_can_substitute(monkeypatch, variable):
    """Each forbidden name is set in turn, alone. None of them works, and the
    list is enumerated rather than merely unused so a fallback reintroduced
    later fails here instead of passing quietly."""
    monkeypatch.setenv(variable, OTHER)
    assert C.present() is False
    with pytest.raises(C.ProviderCredentialMissing):
        C.require()


def test_every_forbidden_credential_at_once_still_fails_closed(monkeypatch):
    for variable in C.FORBIDDEN_FALLBACKS:
        monkeypatch.setenv(variable, OTHER)
    monkeypatch.setenv("AI_MODEL", "a-shared-model")
    assert C.present() is False
    with pytest.raises(C.ProviderCredentialMissing):
        C.require()


def test_the_legacy_application_setting_cannot_substitute(monkeypatch):
    """`settings.anthropic_api_key` is the legacy path and is still correct
    for the rest of the product. It is not a Cockpit credential."""
    from backend.config import settings

    monkeypatch.setattr(
        "backend.config.settings",
        dataclasses.replace(settings, anthropic_api_key=OTHER))
    assert C.present() is False
    with pytest.raises(C.ProviderCredentialMissing):
        C.require()


def test_the_credential_module_reads_exactly_one_variable():
    """Read off the source. A second `os.environ` read in this module would
    be a fallback however it was named."""
    import ast
    from pathlib import Path

    source = Path(C.__file__).read_text()
    tree = ast.parse(source)
    reads = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"):
            reads.append(node)
    assert len(reads) == 1, "the module reads the environment more than once"
    # And it reads it through the constant, not a literal that could drift.
    assert isinstance(reads[0].args[0], ast.Name)
    assert reads[0].args[0].id == "COCKPIT_CREDENTIAL_VAR"


def test_the_cockpit_package_reads_no_other_credential():
    """Nothing else in the package reaches for a key. `service.py` builds the
    provider from `credential.require()` and touches nothing else."""
    import ast
    from pathlib import Path

    package = Path(C.__file__).parent
    for path in sorted(package.rglob("*.py")):
        if path.name == "credential.py":
            continue
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and \
                    node.attr == "anthropic_api_key":
                raise AssertionError(
                    f"{path.name} reads the legacy application credential")
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == name:
                    # Naming it in prose is fine; reading it is not.
                    assert f'environ.get("{name}")' not in source, path.name
                    assert f"environ[{name!r}]" not in source, path.name


# ============================== the request fails closed, end to end

def test_a_request_without_the_credential_stops_before_any_provider_call(
        runtime_factory, sonnet_answers, monkeypatch):
    """Requirement 3: fail closed BEFORE the first provider request."""
    provider = FakeProvider(structured_script=list(sonnet_answers),
                            converse_script=[])
    outcome = runtime_factory(
        provider, provider_error=C.ProviderCredentialMissing()
    ).run("How much did ECL change?")

    assert outcome.status == st.PROVIDER_CREDENTIAL_MISSING
    assert outcome.envelope.kind == "stop"
    assert C.COCKPIT_CREDENTIAL_VAR in outcome.envelope.narrative
    # Nothing was asked of the provider, and nothing was answered without it.
    assert provider.requests == [] and provider.structured_requests == []
    assert outcome.results == []


def test_the_stop_is_terminal_and_has_no_fallback_edge():
    assert st.PROVIDER_CREDENTIAL_MISSING in st.TERMINAL
    assert st.TRANSITIONS[st.PROVIDER_CREDENTIAL_MISSING] == ()


def test_the_credential_stop_is_distinct_from_the_model_stop():
    """One means nobody said which account pays; the other means nobody said
    which model answers. An operator sent to the wrong variable is an operator
    who does not fix it."""
    assert st.PROVIDER_CREDENTIAL_MISSING != st.MODEL_CONFIGURATION_MISSING
    assert st.PROVIDER_CREDENTIAL_MISSING != st.PROVIDER_ERROR


# ============================================= D and E. it never escapes

def test_the_diagnostics_report_only_present_or_missing(monkeypatch):
    from backend.cockpit_agentic import service

    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    body = json.dumps(service.diagnostics(), default=str)

    assert SECRET not in body
    assert "PRESENT" in body
    # Not a prefix, not a suffix, not a length, not a hash, not a mask.
    for fragment in (SECRET[:8], SECRET[-8:], SECRET[:4], SECRET[-4:]):
        assert fragment not in body
    assert "sk-ant" not in body
    assert str(len(SECRET)) not in json.dumps(
        service.diagnostics()["provider"], default=str)
    # No masked or hashed form either. Checked as CONTENT rather than by
    # looking for the words: the note deliberately says the word "masked"
    # while describing what is not done, and a test that failed on that would
    # be reading policy text as if it were a leak.
    block = service.diagnostics()["provider"]
    for value in block.values():
        text = str(value)
        assert not any(ch in text for ch in ("***", "•")), text
        assert SECRET[:4] not in text and SECRET[-4:] not in text


def test_the_diagnostics_say_missing_when_it_is(monkeypatch):
    from backend.cockpit_agentic import service

    monkeypatch.setenv("ANTHROPIC_API_KEY", OTHER)
    provider_block = service.diagnostics()["provider"]
    assert provider_block["status"] == "MISSING"
    assert provider_block["configured"] is False
    assert OTHER not in json.dumps(provider_block, default=str)
    assert C.COCKPIT_CREDENTIAL_VAR in provider_block["note"]


def test_the_credential_report_carries_only_a_status():
    """The whole surface, enumerated. A field added here that carried any part
    of the value would fail this."""
    assert set(C.report()) == {"variable", "status", "configured", "note"}
    assert C.report()["status"] in ("PRESENT", "MISSING")


def test_the_provider_does_not_render_its_credential(monkeypatch):
    """It did, until this change: a dataclass renders every field into its
    repr, so `raise ValueError(f"{provider}")` was enough to put the key in a
    traceback."""
    from backend.llm.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(api_key=SECRET)
    assert SECRET not in repr(provider)
    assert SECRET not in str(provider)
    assert "PRESENT" in repr(provider)
    try:
        raise ValueError(f"the provider was {provider}")
    except ValueError as e:
        assert SECRET not in str(e)


def test_nothing_serializes_a_provider_with_asdict():
    """`dataclasses.asdict` reads `__dict__` and ignores `repr=False`, so it
    would still expose the key. Nothing does it, and this is what keeps that
    true."""
    import ast
    from pathlib import Path

    for base in ("backend/cockpit_agentic", "backend/llm"):
        for path in sorted(Path(base).rglob("*.py")):
            source = path.read_text()
            for suspect in ("asdict(provider", "asdict(self.provider",
                            "asdict(self._provider", "vars(provider"):
                assert suspect not in source, f"{path}: {suspect}"


def test_the_secret_never_reaches_a_model_prompt_or_a_trace(
        runtime_factory, sonnet_answers, monkeypatch):
    """The request path, end to end, with a credential set: the outbound
    requests, the answer, the budget ledger and the whole serialized outcome."""
    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    sql = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
           "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 DESC LIMIT 2")
    plan = {"plan_id": "p", "subquestions": ["the change"],
            "fields_required": ["ecl_reported"], "method_summary": "compare"}
    provider = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[
            lambda _r: {"decision": "PROCEED_COCKPIT",
                        "query_mode": "DATA_ANALYSIS", "owner": "COCKPIT",
                        "scores": scores(), "public_explanation": "x"},
            lambda _r: {"action": "submit_the_first_step", "plan": plan,
                        "steps": [{"step_id": "s1", "language": "sql",
                                   "code": sql}]},
            lambda _r: {"decision": "ANSWER",
                        "per_subquestion": [{"subquestion": "the change",
                                             "answered": True}],
                        "answer": {"narrative": "ECL moved."}}])
    outcome = runtime_factory(provider).run("How much did ECL change?")

    assert outcome.status == st.COMPLETED
    everywhere = json.dumps({
        "outcome": outcome.to_dict(),
        "outbound": provider.requests,
        "preprocessing": provider.structured_requests,
    }, default=str)
    assert SECRET not in everywhere
    assert "sk-ant" not in everywhere
    for fragment in (SECRET[:10], SECRET[-10:]):
        assert fragment not in everywhere


def test_no_shipped_file_carries_anything_key_shaped():
    """Requirement 4's last clause. A real credential in a tracked file is the
    leak that survives every rotation, because it is in the history.

    Scoped to what SHIPS -- application code, scripts, configuration and
    documentation. Not `tests/`: several suites deliberately contain obvious
    fake keys in order to prove that redaction works, and a rule that flagged
    those would be noise a reader learns to skip past. The Cockpit's own test
    secret is confined separately, below.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True).stdout.split()
    for name in tracked:
        if name.startswith("tests/"):
            continue
        if not name.endswith((".py", ".md", ".ts", ".tsx", ".json", ".yml",
                              ".yaml", ".example", ".sh", ".toml", ".ps1")):
            continue
        try:
            body = open(name, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for marker in ("sk-ant-api", "sk-ant-admin", "sk-ant-sid"):
            assert marker not in body, f"{name} contains something key-shaped"


def test_this_suites_own_fake_secret_stays_in_this_file():
    """The string above is unmistakable so a leak is unambiguous. That only
    works while it lives in one place."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True).stdout.split()
    holders = []
    for name in tracked:
        try:
            if SECRET in open(name, encoding="utf-8", errors="ignore").read():
                holders.append(name)
        except OSError:
            continue
    assert holders in ([], ["tests/cockpit_agentic/test_credential.py"])


def test_the_env_example_documents_the_name_and_no_value():
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / ".env.example"
    body = example.read_text()
    assert C.COCKPIT_CREDENTIAL_VAR in body
    line = next(line for line in body.splitlines()
                if line.startswith(f"{C.COCKPIT_CREDENTIAL_VAR}="))
    value = line.split("=", 1)[1]
    assert value in ("", "<set-in-runtime-environment>"), value
    # And the four pricing names and the two model roles are documented too,
    # so an operator has one file to work from.
    for name in ("COCKPIT_AGENTIC_V3", "AI_PROVIDER",
                 "AI_COCKPIT_PREPROCESS_MODEL", "AI_COCKPIT_REASONING_MODEL",
                 "COCKPIT_AGENTIC_V3_SONNET_INPUT_USD_PER_MTOK",
                 "COCKPIT_AGENTIC_V3_SONNET_OUTPUT_USD_PER_MTOK",
                 "COCKPIT_AGENTIC_V3_OPUS_INPUT_USD_PER_MTOK",
                 "COCKPIT_AGENTIC_V3_OPUS_OUTPUT_USD_PER_MTOK"):
        assert name in body, name
    assert "sk-" not in value


# =========================================== the preflight block

def test_the_preflight_shows_every_commissioning_state(monkeypatch):
    """One block an operator reads straight down, rather than assembling the
    answer from eight places."""
    from backend.cockpit_agentic import service

    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "a-fast-id")
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "a-strong-id")

    preflight = service.diagnostics()["preflight"]
    assert set(preflight) == {
        "cockpit_agentic_v3", "provider", "cockpit_anthropic_credential",
        "preprocess_model", "reasoning_model", "model_role_configuration",
        "provider_connectivity", "token_counting", "prompt_cache",
        "spend_accounting", "python_sandbox", "data_release", "data_origin",
        "ready_for_commissioning"}
    assert preflight["cockpit_anthropic_credential"] == "PRESENT"
    assert preflight["preprocess_model"] == "a-fast-id"
    assert preflight["reasoning_model"] == "a-strong-id"
    assert preflight["model_role_configuration"] == "OK"


def test_the_preflight_never_carries_the_credential(monkeypatch):
    from backend.cockpit_agentic import service

    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    body = json.dumps(service.diagnostics()["preflight"], default=str)
    assert SECRET not in body and "sk-ant" not in body
    for fragment in (SECRET[:6], SECRET[-6:]):
        assert fragment not in body


def test_the_preflight_says_not_ready_while_anything_is_missing(monkeypatch):
    from backend.cockpit_agentic import service

    monkeypatch.delenv("AI_COCKPIT_PREPROCESS_MODEL", raising=False)
    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    assert service.diagnostics()["preflight"][
        "ready_for_commissioning"] is False

    monkeypatch.setenv("AI_COCKPIT_PREPROCESS_MODEL", "a-fast-id")
    monkeypatch.setenv("AI_COCKPIT_REASONING_MODEL", "a-strong-id")
    monkeypatch.delenv(C.COCKPIT_CREDENTIAL_VAR, raising=False)
    assert service.diagnostics()["preflight"][
        "ready_for_commissioning"] is False


def test_the_preflight_is_honest_about_what_has_not_been_verified(monkeypatch):
    """Connectivity is UNVERIFIED, not OK, until a call has actually been
    made. A green line nobody earned is worse than an amber one."""
    from backend.cockpit_agentic import service

    monkeypatch.setenv(C.COCKPIT_CREDENTIAL_VAR, SECRET)
    preflight = service.diagnostics()["preflight"]
    assert "UNVERIFIED" in preflight["provider_connectivity"]
    assert "demo_only" in preflight["data_origin"]
