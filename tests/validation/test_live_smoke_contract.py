"""
The Quick verifier must depend on nothing the production image lacks.

The failure these exist for
---------------------------
`verify-live-ai.ps1 -Quick` reported FAILED against a provider that had just
passed 8/8 live tests on the same machine. The stored report said:

    component: live_smoke   passed: false   latency_ms: 45
    input_tokens: 0         output_tokens: 0

Forty-five milliseconds and zero tokens is not a model answering badly; it is a
model that was never asked. Quick ran the smoke checks by shelling out to
`pytest tests/llm/test_live_smoke.py` inside the production backend container,
and that image ships neither `tests/` nor pytest — deliberately. The subprocess
died before the first assertion, and the verifier blamed the provider.

Nothing caught it because every test ran in a development checkout, where both
happen to be present. So these tests assert the property that actually matters:
Quick reaches the provider through production code only.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from backend.validation import live_smoke as ls
from backend.validation import live_verify as lv

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Fakes. No provider is reached from this environment.
# ---------------------------------------------------------------------------


def _outcome(check: str, passed: bool = True, **kwargs) -> ls.Outcome:
    base = {"calls": 1, "model": "claude-fake-1", "latency_ms": 210,
            "input_tokens": 400, "output_tokens": 30,
            "detail": "a stand-in outcome"}
    base.update(kwargs)
    return ls.Outcome(check=check, passed=passed, **base)


def _suite(failing: str = "") -> ls.Suite:
    return ls.Suite(outcomes=[
        _outcome(c.id, passed=(c.id != failing),
                 calls=c.calls,
                 detail=("did not hold" if c.id == failing else "held"))
        for c in ls.CHECKS
    ])


class _FakeResult:
    def __init__(self, role: str) -> None:
        self.data = {"ok": True, "role": role}
        self.model = "claude-fake-1"
        self.duration_ms = 91
        self.input_tokens = 412
        self.output_tokens = 38
        self.attempts = 1
        self.request_id = f"req_{role}"


class _FakeProvider:
    name = "anthropic"
    model = "claude-fake-1"

    def __init__(self) -> None:
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    def status(self):
        from backend.llm.base import ProviderStatus

        return ProviderStatus(provider=self.name, model=self.model,
                              configured=True, state="connected",
                              detail="a stand-in, for tests")

    def structured(self, **kwargs):
        self.calls += 1
        return _FakeResult(str(kwargs.get("role") or ""))


@pytest.fixture
def offline_quick(monkeypatch):
    """Everything Quick needs, with no network call and nothing spent."""
    import backend.llm as llm

    provider = _FakeProvider()
    monkeypatch.setattr(llm, "get_provider", lambda *a, **k: provider)
    monkeypatch.setattr(lv, "_provider_status",
                        lambda: {"configured": True, "state": "connected"})
    monkeypatch.setattr(ls, "run_all", lambda stop_early=False: _suite())
    return provider


# ===========================================================================
# Quick depends on nothing the production image lacks
# ===========================================================================


def test_quick_never_invokes_pytest(offline_quick, monkeypatch):
    """The exact thing that broke, asserted directly."""
    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "Quick shelled out to pytest, which the production image does not "
            "ship. That is the bug this test exists for.")

    monkeypatch.setattr(lv, "_run_pytest", _forbidden)
    report = lv.quick()
    assert report.passed is True, report.failures


def test_quick_never_spawns_a_subprocess(offline_quick, monkeypatch):
    """Wider than pytest: no external process at all.

    A verifier that runs inside a container has no business assuming what else
    is on that container's PATH.
    """
    import subprocess

    def _forbidden(*args, **kwargs):
        raise AssertionError(f"Quick spawned a subprocess: {args!r}")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    assert lv.quick().passed is True


def test_quick_works_when_pytest_is_not_installed(offline_quick, monkeypatch):
    """Importing pytest anywhere on the Quick path is a failure."""
    import builtins

    real_import = builtins.__import__

    def _guarded(name, *args, **kwargs):
        if name == "pytest" or name.startswith("pytest."):
            raise ModuleNotFoundError("No module named 'pytest'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guarded)
    report = lv.quick()
    assert report.passed is True, report.failures
    assert report.status == lv.STATUS_LIVE_VERIFIED


def test_quick_works_when_the_tests_directory_is_absent(offline_quick,
                                                        monkeypatch, tmp_path):
    """Run from a directory with no tests/ at all, as production is."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "tests").exists()
    report = lv.quick()
    assert report.passed is True, report.failures
    assert report.live_calls_made > 0


def test_the_smoke_module_imports_nothing_from_the_test_suite():
    """Structural, so it holds for code nobody thought to exercise.

    Walks every import in the module rather than trusting that the ones a test
    happens to reach are all of them.
    """
    source = (ROOT / "backend" / "validation" / "live_smoke.py").read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    for name in imported:
        root = name.split(".")[0]
        assert root not in ("pytest", "tests", "_pytest", "intelligence_factory"), (
            f"live_smoke imports {name!r}, which production does not ship")


def _executable(function) -> str:
    """One function's source with comments and docstrings removed.

    `quick` documents the bug it was written to fix, so its comments name
    pytest on purpose. A rule that could not tell an explanation from a call
    would make that impossible to write down, which is how the reason a fix
    exists gets deleted by the test protecting it.
    """
    tree = ast.parse(inspect.getsource(function).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            node.value.value = ""
    return ast.unparse(tree)


def test_the_quick_path_calls_nothing_from_the_test_suite():
    """The same rule, applied to `quick` and what it calls by name."""
    source = _executable(lv.quick) + _executable(lv._smoke_cases)
    assert "pytest" not in source, "Quick still reaches for pytest"
    assert "tests/" not in source, "Quick still reaches into tests/"
    assert "_run_pytest" not in source
    assert "live_smoke" in source, "Quick must call the shared definitions"


# ===========================================================================
# The eight definitions are shared
# ===========================================================================


def test_there_are_exactly_eight_checks():
    assert len(ls.CHECKS) == 8
    assert len({c.id for c in ls.CHECKS}) == 8


def test_every_check_has_a_runner_and_the_runners_have_no_orphans():
    assert {c.id for c in ls.CHECKS} == set(ls.RUNNERS)


def test_the_catalogue_covers_the_eight_things_the_live_suite_proved():
    """The semantics that came across from the old pytest file."""
    assert {c.id for c in ls.CHECKS} == {
        "data_discovery", "data_dictionary", "data_relationship",
        "dynamic_analysis", "entity_ranking",
        "provider_connected", "telemetry_secret_safety",
        "runtime_computes_result",
    }


def test_the_pytest_live_suite_drives_the_shared_definitions():
    """Not a copy of them. There is one definition and two callers."""
    source = (ROOT / "tests" / "llm" / "test_live_smoke.py").read_text()
    assert "from backend.validation import live_smoke" in source
    for called in ("live_smoke.routing_check", "live_smoke.provider_connected",
                   "live_smoke.telemetry_secret_safety",
                   "live_smoke.runtime_computes_result"):
        assert called in source, f"the live suite does not call {called}"

    # And it does not redefine the questions it is supposed to be sharing.
    for routing in ls.ROUTING:
        assert routing.question not in source, (
            f"the live suite has its own copy of {routing.question!r}, which "
            "is how two definitions drift apart")


def test_the_live_suite_collects_one_test_per_check():
    """Five parametrised routing cases plus three named ones."""
    source = (ROOT / "tests" / "llm" / "test_live_smoke.py").read_text()
    assert "live_smoke.ROUTING" in source, (
        "the routing cases must be parametrised from the shared catalogue")
    assert source.count("def test_") == 4  # one parametrised + three


def test_every_check_says_what_it_proves():
    for check in ls.CHECKS:
        assert check.proves, f"{check.id} does not say what passing it means"
        assert check.title
    described = ls.describe()
    assert len(described) == 8
    assert all(d["proves"] for d in described)


def test_an_unknown_check_fails_rather_than_passing_silently():
    outcome = ls.run("no_such_check")
    assert outcome.passed is False
    assert "not a known" in outcome.detail


def test_a_check_that_raises_is_a_failure_not_a_crash(monkeypatch):
    def _explode() -> ls.Outcome:
        raise RuntimeError("the provider fell over")

    monkeypatch.setitem(ls.RUNNERS, "data_discovery", _explode)
    outcome = ls.run("data_discovery")
    assert outcome.passed is False
    assert outcome.detail == "the check raised"
    assert outcome.error_category


def test_run_all_does_not_stop_at_the_first_failure_by_default(monkeypatch):
    """Eight results, so an operator learns about three problems at once."""
    monkeypatch.setitem(
        ls.RUNNERS, "data_discovery",
        lambda: ls.Outcome(check="data_discovery", passed=False))
    monkeypatch.setitem(
        ls.RUNNERS, "runtime_computes_result",
        lambda: ls.Outcome(check="runtime_computes_result", passed=False))
    for check in ls.CHECKS:
        if check.id not in ("data_discovery", "runtime_computes_result"):
            monkeypatch.setitem(
                ls.RUNNERS, check.id,
                (lambda cid: lambda: ls.Outcome(check=cid, passed=True))(check.id))

    suite = ls.run_all()
    assert len(suite.outcomes) == 8
    assert suite.passed is False
    assert {o.check for o in suite.failures} == {
        "data_discovery", "runtime_computes_result"}


def test_the_estimate_is_derived_from_the_catalogue():
    assert ls.ESTIMATED_CALLS == sum(c.calls for c in ls.CHECKS)
    from backend.llm import roles as role_config

    assert lv.ESTIMATED_CALLS[lv.QUICK] == (
        len(role_config.ROLES) + ls.ESTIMATED_CALLS)
    assert lv.ESTIMATED_CALLS[lv.QUICK] == 12


# ===========================================================================
# What Quick reports
# ===========================================================================


def test_quick_records_every_smoke_check_individually(offline_quick):
    report = lv.quick()
    names = [c.name for c in report.cases]

    assert names == [
        "role:router", "role:planner", "role:interpretation", "role:critic",
        "smoke:data_discovery", "smoke:data_dictionary",
        "smoke:data_relationship", "smoke:dynamic_analysis",
        "smoke:entity_ranking", "smoke:provider_connected",
        "smoke:telemetry_secret_safety", "smoke:runtime_computes_result",
    ]
    assert not any(c.name.endswith(".py") for c in report.cases), (
        "a whole suite must not be recorded as one opaque subprocess result")


def test_each_smoke_case_carries_its_own_evidence(offline_quick):
    report = lv.quick()
    smoke = [c for c in report.cases if c.component == "live_smoke"]
    assert len(smoke) == 8
    for case in smoke:
        assert case.detail, f"{case.name} says nothing about what it found"
        assert case.latency_ms > 0
    # The ones that call a model report what it cost.
    calling = [c for c in smoke if c.calls > 0]
    assert calling, "no smoke case recorded a provider call"
    for case in calling:
        assert case.served_model == "claude-fake-1"
        assert case.input_tokens > 0


def test_the_call_total_is_the_sum_of_the_cases(offline_quick):
    report = lv.quick()
    assert report.live_calls_made == sum(c.calls for c in report.cases)
    assert report.live_calls_made == 12


def test_one_failed_smoke_case_fails_the_whole_run(monkeypatch,
                                                   offline_quick, tmp_path):
    monkeypatch.setattr(ls, "run_all",
                        lambda stop_early=False: _suite(failing="entity_ranking"))
    report = lv.quick()
    lv.store_result(report, tmp_path)

    assert report.passed is False
    assert report.live_verified is False
    assert report.status == lv.STATUS_FAILED
    assert lv.EXIT_FOR[report.status] == lv.EXIT_FAILED
    assert "smoke:entity_ranking" in report.failures
    # And the seven that passed are still reported as passing.
    passing = [c for c in report.cases if c.passed]
    assert len(passing) == 11


def test_a_failed_smoke_case_names_the_case_not_the_suite(monkeypatch,
                                                          offline_quick):
    monkeypatch.setattr(
        ls, "run_all",
        lambda stop_early=False: _suite(failing="data_relationship"))
    report = lv.quick()
    assert report.failures == ["smoke:data_relationship"]


def test_a_successful_quick_stores_live_verified(offline_quick, tmp_path):
    report = lv.quick()
    path = lv.store_result(report, tmp_path)

    assert path is not None
    assert report.status == lv.STATUS_LIVE_VERIFIED
    assert lv.EXIT_FOR[report.status] == lv.EXIT_OK

    stored = json.loads(path.read_text(encoding="utf-8"))
    smoke = [c for c in stored["cases"] if c["component"] == "live_smoke"]
    assert len(smoke) == 8
    assert {c["check" if "check" in c else "name"] for c in smoke}

    badge = lv.badge(tmp_path)
    assert badge["live_verified"] is True
    assert badge["status"] == lv.STATUS_LIVE_VERIFIED


def test_the_stored_report_still_passes_the_secret_scanner(offline_quick,
                                                           tmp_path):
    report = lv.quick()
    assert lv._key_free(report.to_dict()) == []
    path = lv.store_result(report, tmp_path)
    assert path is not None
    assert "sk-ant" not in path.read_text(encoding="utf-8")


def test_a_credential_in_a_smoke_case_is_still_refused(monkeypatch,
                                                       offline_quick, tmp_path):
    """The narrowing did not open a hole in the case records."""
    monkeypatch.setattr(
        ls, "run_all",
        lambda stop_early=False: ls.Suite(outcomes=[
            _outcome(c.id, detail="sk-ant-api03-leaked") for c in ls.CHECKS]))
    report = lv.quick()
    with pytest.raises(RuntimeError, match="must never be recorded"):
        lv.write(report, tmp_path)


def test_token_counts_on_a_smoke_case_are_still_allowed(offline_quick,
                                                        tmp_path):
    """The false positive that started all this stays fixed."""
    report = lv.quick()
    payload = report.to_dict()
    smoke = [c for c in payload["cases"] if c["component"] == "live_smoke"]
    assert any(c["input_tokens"] > 0 for c in smoke)
    assert any(c["output_tokens"] > 0 for c in smoke)
    assert lv._key_free(payload) == []


# ===========================================================================
# The other modes are unchanged
# ===========================================================================


def test_dry_run_still_makes_no_provider_call(monkeypatch):
    import backend.llm as llm

    def _forbidden(*a, **k):
        raise AssertionError("a dry run must never reach the provider")

    monkeypatch.setattr(llm, "get_provider", _forbidden)
    monkeypatch.setattr(ls, "run_all", lambda stop_early=False: (_ for _ in ()).throw(
        AssertionError("a dry run must not run the smoke checks")))

    report = lv.dry_run()
    assert report.live_calls_made == 0
    assert report.status == lv.STATUS_DRY_RUN
    assert report.estimated_calls[lv.DRYRUN] == 0


def test_critical_still_runs_the_threads_not_pytest():
    """Critical was always production-safe and stays that way."""
    source = inspect.getsource(lv.critical)
    assert "thread_runner.run_thread" in source
    assert "_run_pytest" not in source
    assert len(lv.THREADS) == 7


def test_full_routing_still_uses_the_pytest_suite():
    source = inspect.getsource(lv.full_routing)
    assert "_run_pytest" in source
    assert "tests/evals/test_ask_evaluation.py" in source


def test_a_missing_harness_is_not_reported_as_the_model_failing(monkeypatch,
                                                                tmp_path):
    """FullRouting needs pytest, which production does not ship.

    It must say the mode is unavailable here, not that the provider failed.
    Blaming the model for a missing harness is the whole defect being fixed,
    and it applied to this mode too.
    """
    monkeypatch.setattr(lv, "_provider_status",
                        lambda: {"configured": True, "state": "connected"})
    monkeypatch.setattr(lv, "_harness_missing",
                        lambda target: "pytest is not installed in this image")

    report = lv.full_routing()
    assert report.status == lv.STATUS_NOT_ELIGIBLE
    assert lv.EXIT_FOR[report.status] == lv.EXIT_NOT_ELIGIBLE
    assert any(c.error_category == "harness_unavailable" for c in report.cases)
    assert any("production images do not ship" in n or "development checkout" in n
               for n in report.notes)


def test_the_harness_preflight_recognises_both_ways_it_can_be_missing(tmp_path):
    assert lv._harness_missing("tests/does/not/exist.py")
    assert "does/not/exist" in lv._harness_missing("tests/does/not/exist.py")
    # Present here, because this IS a development checkout.
    assert lv._harness_missing("tests/llm/test_live_smoke.py") == ""
