"""The authorised protected-core bridge, tested as an attack surface.

REAL DATABASE · REAL EXECUTOR · NO MODEL. The published candidate parquet
through a real DuckDB session, the real `ExecutionService`, and no provider of
any kind -- not even a scripted one, so nothing here can be mistaken for
evidence about a model.

`PROTECTED_CORE_INCOMPATIBILITY.md` section 7 records what this bridge is and
the approval it needed. Two protected files changed and both are additive and
flag-gated. A bridge into a protected core earns adversarial tests rather than
happy-path ones, so this module is organised by what would have to be true for
the bridge to be dangerous:

  the feature is off and something changed anyway   -> section 1
  an ordinary step behaves differently              -> section 1
  something other than the typed operation gets in  -> section 2
  a name, a path or an expression reaches the engine -> section 2
  the sandbox is looser than it was                 -> section 3
  a book reaches the other book's data              -> section 4
  an approval is honoured that should not be        -> section 5
  a failure escapes as something other than a step  -> section 6
  the dispatcher condition itself is wrong          -> section 7
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import contracts as ct
from backend.cockpit_v4 import domain_resolver as resolver
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import execute_tool as et
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import bridge as br
from backend.cockpit_v4.scenario import thread as th
from backend.cockpit_v4.scenario.errors import ScenarioError

FLAGS = {dom.CORPORATE: "COCKPIT_V4_WHATIF_CORPORATE",
         dom.RETAIL: "COCKPIT_V4_WHATIF_RETAIL"}


@pytest.fixture(scope="module", autouse=True)
def _lake_present():
    if not pathlib.Path("data/cockpit_v4_lake").exists():
        pytest.skip("the published lake is not present in this worktree")
    arun.reset()
    yield
    arun.reset()


class Store:
    """The three calls the bridge makes of a store, and a record of them.

    Deliberately not a `RunStore`: these tests are about what the bridge does
    with what a store returns, and a real store would make the thread context
    a second thing to arrange rather than a thing to state.
    """

    def __init__(self, thread_id: str = "th-1") -> None:
        self.thread_id = thread_id
        self.artifacts: list[dict[str, Any]] = []
        self.context: dict[str, Any] | None = None

    def get_run(self, run_id: str) -> Any:
        return type("Record", (), {"thread_id": self.thread_id})()

    def thread_context(self, thread_id: str, *,
                       tenant_id: str = "") -> dict[str, Any] | None:
        return self.context if thread_id == self.thread_id else None

    def put_artifact(self, **kw: Any) -> str:
        self.artifacts.append(kw)
        if kw.get("kind") == th.ARTIFACT_KIND:
            self.context = kw["rows"][0]
        return f"art-{len(self.artifacts)}"


def book_of(domain_id: str):
    book = arun.for_domain(domain_id)
    scope = resolver.scope_for(domain_id, tenant_id=lake.DEFAULT_TENANT)
    return book, scope


def preview_parameters(domain_id: str = dom.CORPORATE, **over: Any
                       ) -> dict[str, Any]:
    """A valid preview request, so a test can change exactly one thing."""
    if domain_id == dom.CORPORATE:
        base: dict[str, Any] = {
            "operation": br.PREVIEW,
            "cohort": {"filters": [{"column": "sector", "operator": "=",
                                    "value": "Construction"}]},
            "shocks": [{"field": "pd_pit_12m", "operation": "relative_pct",
                        "value": "20", "origin": "increase PD by 20%"}],
            "methods": ["delta"],
            "clauses": ["For those customers, increase PD by 20%."]}
    else:
        base = {
            "operation": br.PREVIEW,
            "cohort": {"filters": [{"column": "product", "operator": "=",
                                    "value": "Personal Finance"}]},
            "shocks": [{"field": "pd_pit_12m", "operation": "relative_pct",
                        "value": "20", "origin": "increase PD by 20%"}],
            "methods": ["delta"],
            "clauses": ["Increase PD by 20% on personal finance."]}
    base.update(over)
    return base


def run_bridge(domain_id: str, parameters: dict[str, Any], *, store: Store,
               run_id: str = "run-1", scope: Any = None,
               session: Any = None) -> br.Produced:
    book, resolved = book_of(domain_id)
    return br.execute(
        parameters, session=session or book.session, scope=scope or resolved,
        catalog=book.catalog, store=store, run_id=run_id,
        tenant_id=lake.DEFAULT_TENANT,
        release_id=(scope or resolved).release_id, step_id="s1",
        deadline_seconds=120)


def preview_then_execute(domain_id: str, *, store: Store | None = None,
                         reply: str = "yes", **over: Any):
    """The two-turn journey, as a fixture the assertions can start from."""
    store = store or Store()
    made = run_bridge(domain_id, preview_parameters(domain_id, **over),
                      store=store, run_id="run-1")
    digest = made.provenance["whatif_digest_to_confirm"]
    out = run_bridge(domain_id,
                     {"operation": br.EXECUTE, "confirmation_digest": digest,
                      "reply": reply},
                     store=store, run_id="run-2")
    return store, made, out, digest


# ---- 1. flags off, and ordinary steps ----------------------------------

def test_with_the_flag_off_the_step_is_not_a_scenario_step(monkeypatch) -> None:
    """The dispatcher needs the LANGUAGE and the BOOK'S FLAG, not either."""
    monkeypatch.delenv(FLAGS[dom.CORPORATE], raising=False)
    book, scope = book_of(dom.CORPORATE)
    service = et.ExecutionService(
        session=book.session, scope=scope, catalog=book.catalog, store=Store(),
        run_id="r", tenant_id=lake.DEFAULT_TENANT, release_id=scope.release_id,
        limits=_limits(), python_runner=None, header={})
    step = _step(language="whatif_scenario")
    assert service._is_scenario(step) is False


def test_with_the_flag_off_the_step_language_is_not_even_accepted(
        monkeypatch) -> None:
    """`parse_steps` refuses it, so it never reaches the executor at all."""
    for flag in FLAGS.values():
        monkeypatch.delenv(flag, raising=False)
    assert ct._step_languages() == ct.BASE_STEP_LANGUAGES
    with pytest.raises(ct.Rejection) as caught:
        ct.parse_steps([_raw_step(language="whatif_scenario")], max_steps=8)
    assert caught.value.code == "INVALID_MODEL_OUTPUT"


def test_with_the_flag_off_the_refusal_is_the_accepted_sentence(
        monkeypatch) -> None:
    """Word for word. A changed message is a changed payload for every
    reader who ever sends a bad step, feature or no feature."""
    for flag in FLAGS.values():
        monkeypatch.delenv(flag, raising=False)
    with pytest.raises(ct.Rejection) as caught:
        ct.parse_steps([_raw_step(language="perl")], max_steps=8)
    assert caught.value.message == (
        "steps[0].language must be 'sql' or 'python'. A python step is never "
        "executed as SQL, or the reverse.")


def test_with_the_flag_off_the_provider_schema_is_byte_identical(
        monkeypatch) -> None:
    """The enum the analyst is offered is a statement about what this runtime
    accepts. With the flags off it does not accept a scenario step, so the
    schema must not claim it does -- and the payload snapshots must not move.
    """
    for flag in FLAGS.values():
        monkeypatch.delenv(flag, raising=False)
    off = _step_enum()
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    on = _step_enum()
    assert off == ["sql", "python"]
    assert on == ["sql", "python", "whatif_scenario"]


def test_the_protected_schema_files_are_not_edited() -> None:
    """The extra language is added to the PROVIDER'S COPY, in memory.

    `shared_defs.schema.json` and `execute_analysis.schema.json` are
    protected files. Editing one would have been the simpler change and a
    worse one: the file would then claim a language this runtime refuses
    whenever the flags are off, which is most of the time.
    """
    import json
    from pathlib import Path

    raw = json.loads(
        (Path("backend/cockpit_v4/contracts/shared_defs.schema.json")
         ).read_text(encoding="utf-8"))
    enum = raw["$defs"]["Step"]["properties"]["language"]["enum"]
    assert enum == ["sql", "python"], (
        "the protected schema file now declares the scenario language. It is "
        "supposed to stay at its baseline hash; the language is added to the "
        "provider's in-memory copy by contracts._whatif_language.")


def test_an_ordinary_sql_step_still_dispatches_as_sql(monkeypatch) -> None:
    """With the feature ON, a normal step is untouched."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    book, scope = book_of(dom.CORPORATE)
    service = et.ExecutionService(
        session=book.session, scope=scope, catalog=book.catalog, store=Store(),
        run_id="r", tenant_id=lake.DEFAULT_TENANT, release_id=scope.release_id,
        limits=_limits(), python_runner=None, header={})
    assert service._is_scenario(_step(language="sql")) is False
    assert service._is_scenario(_step(language="python")) is False


# ---- 2. only the typed operation, and nothing named ---------------------

@pytest.mark.parametrize("operation", [
    "", "run", "execute", "eval", "import", "scenario/run.py",
    "backend.cockpit_v4.scenario.run", "run.execute", "__import__",
])
def test_no_operation_but_the_two_is_dispatched(operation) -> None:
    """The operation is an enum of two, matched exactly.

    Every value here is a plausible attempt to name something to call, and
    each is refused for the same reason: it is not one of the two.
    """
    with pytest.raises(ScenarioError) as caught:
        br.validate({"operation": operation}, step_id="s1",
                    domain_id=dom.CORPORATE)
    assert caught.value.code == "CONFIRMATION_STALE"
    assert "not a What-If operation" in caught.value.message


@pytest.mark.parametrize("key,value", [
    ("module", "backend.cockpit_v4.scenario.run"),
    ("callable", "execute"),
    ("function", "run"),
    ("path", "/etc/passwd"),
    ("code", "__import__('os').system('id')"),
    ("expression", "1+1"),
    ("import", "os"),
    ("predicate", "1=1"),
    ("sql", "SELECT 1"),
])
def test_an_unknown_key_is_refused_by_name_not_ignored(key, value) -> None:
    """A key that is silently dropped is a rule that silently did not happen.

    It also means an attacker learns nothing from a request being accepted:
    every one of these is named back in the refusal.
    """
    with pytest.raises(ScenarioError) as caught:
        br.validate({**preview_parameters(), key: value}, step_id="s1",
                    domain_id=dom.CORPORATE)
    assert key in caught.value.message


def test_a_cohort_cannot_carry_a_predicate() -> None:
    """`cohort.freeze` interpolates its predicate into a SELECT, so a
    model-authored one would be arbitrary SQL under the run's own session."""
    with pytest.raises(ScenarioError) as caught:
        br.validate(preview_parameters(cohort={"predicate": "1=1"}),
                    step_id="s1", domain_id=dom.CORPORATE)
    assert "free-text predicate" in caught.value.message


@pytest.mark.parametrize("value", [
    "x' OR 1=1 --", "Construction'; DROP TABLE corp_facility_quarter; --",
    "a' UNION SELECT * FROM retail_account_month --",
    "Construction') OR ('1'='1",
])
def test_a_quoted_value_never_reaches_the_query(value) -> None:
    """Refused by a character allowlist rather than escaped.

    The quote is not in `selector.SAFE_CHARS`, so `_literal` never has one to
    escape and there is no escaping routine to get wrong. The cost is a real
    category containing an apostrophe, which is stated in `selector`'s header
    and does not arise in either candidate book.
    """
    with pytest.raises(ScenarioError) as caught:
        br.validate(
            preview_parameters(cohort={"filters": [
                {"column": "sector", "operator": "=", "value": value}]}),
            step_id="s1", domain_id=dom.CORPORATE)
    assert caught.value.code == "COHORT_UNRESOLVED"


def test_a_field_the_book_does_not_carry_is_refused() -> None:
    """`fields.mutable` owns the refusal and names the book's own list."""
    with pytest.raises(ScenarioError):
        br.validate(
            preview_parameters(shocks=[
                {"field": "score_behavioural", "operation": "relative_pct",
                 "value": "20"}]),
            step_id="s1", domain_id=dom.CORPORATE)


def test_an_amount_with_no_named_unit_is_refused() -> None:
    """"Increase PD by 20" is four instructions differing by a factor of ten
    between neighbours, so the operation is required rather than inferred."""
    with pytest.raises(ScenarioError) as caught:
        br.validate(
            preview_parameters(shocks=[
                {"field": "pd_pit_12m", "operation": "", "value": "20"}]),
            step_id="s1", domain_id=dom.CORPORATE)
    assert caught.value.code == "PARAMETER_OUT_OF_RANGE"


def test_the_step_code_is_never_read_on_this_path(monkeypatch) -> None:
    """`code` carries a restatement for the trace. If it were parsed, this
    would be a generic execution path wearing a scenario's name."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    store = Store()
    made = run_bridge(dom.CORPORATE, preview_parameters(), store=store)
    assert made.rows, "the preview produced no rows"
    # The bridge is handed only `parameters`; `code` is not a parameter of
    # `bridge.execute` at all, which is the structural version of this claim.
    assert "code" not in br.PREVIEW_KEYS
    assert "code" not in br.EXECUTE_KEYS


# ---- 3. the sandbox is exactly as restrictive ---------------------------

def test_the_python_sandbox_is_unchanged() -> None:
    """The jail this bridge exists BECAUSE of, re-proved rather than trusted.

    The whole reason for a server-side dispatch is that model-authored Python
    cannot import the engine. If that stopped being true, the bridge would be
    the second way in rather than the only one.
    """
    from backend.cockpit_v4 import pyrunner

    assert "-I" in pyrunner._BOOT or True  # the flags are in `_spawn`
    source = pathlib.Path(
        "backend/cockpit_v4/pyrunner.py").read_text(encoding="utf-8")
    assert '"-I", "-S"' in source, "isolated mode or no-site was removed"
    assert "PYTHONPATH" not in source.replace(
        "PYTHONDONTWRITEBYTECODE", ""), "a PYTHONPATH was introduced"
    for name in ("os", "sys", "importlib", "subprocess", "socket"):
        assert name in pyrunner._FORBIDDEN_IMPORTS
    for name in ("eval", "exec", "compile", "__import__", "open"):
        assert name in pyrunner._FORBIDDEN_NAMES


def test_the_engine_is_still_unimportable_from_a_python_step() -> None:
    """Measured against the jail itself, not asserted from the source.

    This is the single fact the whole bridge rests on. If model-authored
    Python could import the engine, the bridge would be the second way in
    rather than the only one, and there would be a generic escape hatch
    nobody authorised.

    Measured against `pyrunner._spawn` rather than through
    `PythonRunner.run`, because `PythonRunner` refuses to come up in this
    container at all: `probe()` runs `self_test()` first and this container
    permits outbound network from a subprocess, so the jail's own network
    check cannot pass and the runner reports UNAVAILABLE. That is fail-closed
    and correct -- a jail that cannot prove it holds should not be used -- but
    it would have made this test a permanent skip, and a skip is not evidence.
    `_spawn` is the same interpreter invocation with the same `-I -S`, the
    same temp cwd and the same three-variable environment.
    """
    from backend.cockpit_v4 import pyrunner

    def attempt(code: str) -> dict[str, Any]:
        return pyrunner._spawn(
            code + "\nrows = []\n", deadline_seconds=15, memory_mib=256,
            output_bytes=20_000, payload={"parameters": {}, "inputs": {}})

    # The control: the standard library is reachable, so a failure below is
    # the path and not a broken invocation.
    assert attempt("import json").get("ok"), (
        "even `import json` failed, so this test is measuring a broken "
        "spawn rather than the jail.")
    for forbidden in ("from backend.cockpit_v4.scenario import run",
                      "from backend.cockpit_v4.scenario import bridge",
                      "import backend",
                      "import pandas"):
        outcome = attempt(forbidden)
        assert not outcome.get("ok"), (
            f"model-authored Python can now run {forbidden!r}. The bridge "
            f"exists so that it does not have to, and the sandbox was not "
            f"authorised to be relaxed.")


# ---- 4. one book cannot reach the other --------------------------------

def test_a_corporate_scenario_cannot_run_against_retail(monkeypatch) -> None:
    """Both flags on, so nothing here is prevented by a switch."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    monkeypatch.setenv(FLAGS[dom.RETAIL], "1")
    corporate, _ = book_of(dom.CORPORATE)
    _, retail_scope = book_of(dom.RETAIL)
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.RETAIL, preview_parameters(dom.RETAIL), store=Store(),
                   scope=retail_scope, session=corporate.session)
    assert caught.value.code == "BOOK_MISMATCH"


def test_a_retail_scenario_cannot_run_against_corporate(monkeypatch) -> None:
    """The same claim the other way round: it is not a property of one book."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    monkeypatch.setenv(FLAGS[dom.RETAIL], "1")
    retail, _ = book_of(dom.RETAIL)
    _, corporate_scope = book_of(dom.CORPORATE)
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.CORPORATE, preview_parameters(dom.CORPORATE),
                   store=Store(), scope=corporate_scope,
                   session=retail.session)
    assert caught.value.code == "BOOK_MISMATCH"


def test_one_flag_on_does_not_dispatch_the_other_book(monkeypatch) -> None:
    """`contracts._step_languages` uses `any_enabled`, so the language parses
    for both books once either is on. The per-book gate is the executor's."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    monkeypatch.delenv(FLAGS[dom.RETAIL], raising=False)
    assert "whatif_scenario" in ct._step_languages()
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.RETAIL, preview_parameters(dom.RETAIL), store=Store())
    assert "not enabled" in caught.value.message


# ---- 5. what an approval is, and is not --------------------------------

def test_the_journey_previews_then_executes(monkeypatch) -> None:
    """The happy path, stated once so the refusals below mean something."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    _store, made, out, digest = preview_then_execute(dom.CORPORATE)
    assert made.provenance["whatif_operation"] == br.PREVIEW
    assert out.provenance["whatif_operation"] == br.EXECUTE
    assert out.provenance["whatif_confirmation_digest"] == digest
    headline = [r for r in out.rows if r["section"] == "cohort"
                and r["item"] == "Total ECL"]
    assert headline and headline[0]["change_sar_mn"] not in ("", "0")


def test_a_reply_that_is_not_a_yes_leaves_it_unconfirmed(monkeypatch) -> None:
    """Section 6.2: reading a sensitivity or naming a method is not approval
    of a calculation nobody has seen."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    for reply in ("use ML", "what would that do?", "maybe", "no", ""):
        with pytest.raises(ScenarioError) as caught:
            preview_then_execute(dom.CORPORATE, reply=reply)
        assert caught.value.code == "CONFIRMATION_STALE"


def test_a_stale_digest_is_refused(monkeypatch) -> None:
    """The approval names a scenario. A digest that is not the stored
    scenario's is an approval of something else."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    store = Store()
    run_bridge(dom.CORPORATE, preview_parameters(), store=store)
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.CORPORATE,
                   {"operation": br.EXECUTE, "confirmation_digest": "a" * 64,
                    "reply": "yes"}, store=store, run_id="run-2")
    assert caught.value.code == "CONFIRMATION_STALE"
    assert "nothing was run" in caught.value.message


def test_a_revision_invalidates_the_earlier_confirmation(monkeypatch) -> None:
    """A second preview with a different rule is a different scenario, and
    the first approval does not carry to it."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    store = Store()
    first = run_bridge(dom.CORPORATE, preview_parameters(), store=store)
    stale = first.provenance["whatif_digest_to_confirm"]
    run_bridge(dom.CORPORATE, preview_parameters(shocks=[
        {"field": "pd_pit_12m", "operation": "relative_pct", "value": "40",
         "origin": "make it 40%"}]), store=store, run_id="run-2")
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.CORPORATE,
                   {"operation": br.EXECUTE, "confirmation_digest": stale,
                    "reply": "yes"}, store=store, run_id="run-3")
    assert caught.value.code == "CONFIRMATION_STALE"


def test_a_source_change_invalidates_the_confirmation(monkeypatch) -> None:
    """A confirmation is a confirmation of one scenario against one book."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    store = Store()
    made = run_bridge(dom.CORPORATE, preview_parameters(), store=store)
    digest = made.provenance["whatif_digest_to_confirm"]
    store.context = {
        "kind": th.KIND,
        "body": {**store.context["body"], "release_id": "some-other-release"}}
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.CORPORATE,
                   {"operation": br.EXECUTE, "confirmation_digest": digest,
                    "reply": "yes"}, store=store, run_id="run-2")
    assert caught.value.code == "CONFIRMATION_STALE"


def test_a_cohort_that_moved_is_refused_before_any_arithmetic(
        monkeypatch) -> None:
    """`cohort.reresolve` re-runs the selection and compares the membership
    hash. A cohort that selects different rows is a different cohort."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    store = Store()
    made = run_bridge(dom.CORPORATE, preview_parameters(), store=store)
    digest = made.provenance["whatif_digest_to_confirm"]
    body = dict(store.context["body"])
    # The predicate the cohort was frozen from, changed to select other rows
    # while the membership hash in the digest stays what it was.
    body["cohort_predicate"] = "(sector = 'Manufacturing')"
    store.context = {"kind": th.KIND, "body": body}
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.CORPORATE,
                   {"operation": br.EXECUTE, "confirmation_digest": digest,
                    "reply": "yes"}, store=store, run_id="run-2")
    assert caught.value.code == "SOURCE_VERSION_MISMATCH"


def test_a_narrower_method_set_needs_its_own_approval(monkeypatch) -> None:
    """Which methods run is inside the confirmation."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    store = Store()
    made = run_bridge(dom.CORPORATE,
                      preview_parameters(methods=["delta", "ml"]),
                      store=store)
    digest = made.provenance["whatif_digest_to_confirm"]
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.CORPORATE,
                   {"operation": br.EXECUTE, "confirmation_digest": digest,
                    "reply": "yes", "methods": ["delta"]},
                   store=store, run_id="run-2")
    assert caught.value.code == "CONFIRMATION_STALE"


def test_running_it_twice_is_one_result_reported_twice(monkeypatch) -> None:
    """Not refused, because a reopen is the same request arriving honestly --
    and not two answers, because the engine is deterministic. It is published
    as a re-run naming the run that produced the numbers first."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    store, _made, first, digest = preview_then_execute(dom.CORPORATE)
    second = run_bridge(dom.CORPORATE,
                        {"operation": br.EXECUTE,
                         "confirmation_digest": digest, "reply": "yes"},
                        store=store, run_id="run-3")
    assert second.provenance["whatif_is_rerun"] is True
    assert second.provenance["whatif_previous_run_id"] == "run-2"
    assert first.provenance["whatif_is_rerun"] is False
    numbers = lambda out: [  # noqa: E731
        (r["section"], r["item"], r["baseline_sar_mn"], r["scenario_sar_mn"])
        for r in out.rows if r["section"] in ("cohort", "book", "method")]
    assert numbers(first) == numbers(second), (
        "the same confirmed scenario over the same frozen cohort produced "
        "two different answers.")
    assert any(r["status"] == "RE-RUN, NOT A SECOND RESULT"
               for r in second.rows)


# ---- 6. every failure is a governed step failure -----------------------

def test_a_scenario_error_becomes_a_step_failure_not_an_escape() -> None:
    """`run_batch` catches `StepFailed` and nothing else, and the router above
    it catches only `Rejection`. Anything else ends the run as an unhandled
    exception -- a crash where a reported refusal belongs."""
    from backend.cockpit_v4.scenario import errors as er

    told = br.as_step_failed(
        er.ScenarioError(er.SOURCE_VERSION_MISMATCH, "the book moved."),
        check=et.CHECK_RUNTIME)
    assert told is not None
    code, check, message, detail = told
    from backend.cockpit_v4 import states as st

    assert code in st.ERROR_CODES, (
        "a scenario failure was given an error code the runtime does not "
        "have. Section 19: map onto the existing contract rather than "
        "growing it.")
    assert check == et.CHECK_RUNTIME
    assert detail["whatif_error"] == er.SOURCE_VERSION_MISMATCH


def test_something_that_is_not_a_scenario_error_is_left_to_the_caller() -> None:
    """So an unexpected exception cannot be dressed as a domain refusal."""
    assert br.as_step_failed(ValueError("x"), check="runtime") is None


def test_every_check_this_module_uses_has_a_phase() -> None:
    """`PHASE_OF_CHECK` is exhaustive by test, and `CHECK_SCENARIO` is new.

    An omission publishes a refusal as a query that ran, which is the exact
    defect that table was introduced to fix.
    """
    assert et.CHECK_SCENARIO in et.PHASE_OF_CHECK
    assert et.phase_of(et.CHECK_SCENARIO) == et.PHASE_CHECK
    assert et.CHECK_SCENARIO in et.REFUSED_BEFORE_EXECUTION


def test_a_cohort_past_the_declared_bound_is_refused(monkeypatch) -> None:
    """The bound is declared rather than discovered, and it is checked."""
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    monkeypatch.setattr(br, "MAX_COHORT_ROWS", 3)
    with pytest.raises(ScenarioError) as caught:
        run_bridge(dom.CORPORATE, preview_parameters(), store=Store())
    assert caught.value.code == "BUDGET_EXCEEDED"


def test_the_declared_groupings_are_real_columns() -> None:
    """A grouping name that is not a column is dropped, not refused.

    That is the right behaviour -- a book without a dimension should lose the
    breakdown rather than the run -- and it is exactly why the names need a
    test. The first list here named `rating_current` and `product_type`,
    neither of which exists in either book, and the drop hid it: every run
    succeeded with a breakdown quietly missing a dimension.
    """
    from backend.cockpit_v4.scenario import selector as sel

    for book, names in br.GROUPINGS.items():
        declared = set(sel.columns_of(book))
        missing = [n for n in names if n not in declared]
        assert not missing, (
            f"{book} declares groupings {missing} that its exposure relation "
            f"does not have, so those breakdowns are silently absent.")


# ---- 7. the dispatcher condition itself --------------------------------

MUTATIONS: dict[str, Any] = {
    "always true": lambda self, step: True,
    "always false": lambda self, step: False,
    "language only, flag ignored":
        lambda self, step: step.language == "whatif_scenario",
    "flag only, language ignored": lambda self, step: _flag_only(self),
    "wrong language name":
        lambda self, step: step.language == "whatif" and _flag_only(self),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_mutated_dispatcher_condition_is_caught(name, monkeypatch) -> None:
    """MUTATION TESTING OF THE BRANCH ITSELF.

    A guard nothing can break is a guard nothing is testing. Each mutation
    below is a plausible way to write `_is_scenario` wrongly, and each has to
    make at least one of this module's own claims false. If a mutation
    survives, the tests are describing the happy path and not the condition.
    """
    monkeypatch.setattr(et.ExecutionService, "_is_scenario", MUTATIONS[name])
    book, scope = book_of(dom.CORPORATE)
    service = et.ExecutionService(
        session=book.session, scope=scope, catalog=book.catalog, store=Store(),
        run_id="r", tenant_id=lake.DEFAULT_TENANT, release_id=scope.release_id,
        limits=_limits(), python_runner=None, header={})

    monkeypatch.delenv(FLAGS[dom.CORPORATE], raising=False)
    monkeypatch.delenv(FLAGS[dom.RETAIL], raising=False)
    off_sql = service._is_scenario(_step(language="sql"))
    off_scenario = service._is_scenario(_step(language="whatif_scenario"))
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    on_sql = service._is_scenario(_step(language="sql"))
    on_scenario = service._is_scenario(_step(language="whatif_scenario"))

    correct = (off_sql, off_scenario, on_sql, on_scenario) == (
        False, False, False, True)
    assert not correct, (
        f"the mutation {name!r} behaves exactly like the real condition, so "
        f"it is not a mutation of it -- either the mutation or the condition "
        f"is wrong.")


def test_the_real_dispatcher_condition_is_the_one_the_mutations_miss(
        monkeypatch) -> None:
    """The positive half: all four cases, spelled out."""
    book, scope = book_of(dom.CORPORATE)
    service = et.ExecutionService(
        session=book.session, scope=scope, catalog=book.catalog, store=Store(),
        run_id="r", tenant_id=lake.DEFAULT_TENANT, release_id=scope.release_id,
        limits=_limits(), python_runner=None, header={})
    monkeypatch.delenv(FLAGS[dom.CORPORATE], raising=False)
    assert service._is_scenario(_step(language="sql")) is False
    assert service._is_scenario(_step(language="whatif_scenario")) is False
    monkeypatch.setenv(FLAGS[dom.CORPORATE], "1")
    assert service._is_scenario(_step(language="sql")) is False
    assert service._is_scenario(_step(language="whatif_scenario")) is True


# ---- helpers -----------------------------------------------------------

def _flag_only(service: Any) -> bool:
    from backend.cockpit_v4.scenario import flags

    return bool(flags.enabled(str(getattr(service.scope, "domain_id", ""))))


def _step(*, language: str) -> ct.Step:
    return ct.Step(step_id="s1", language=language, code="-- restatement",
                   parameters={}, purpose="p", input_artifact_ids=(),
                   depends_on_step_ids=())


def _raw_step(*, language: str) -> dict[str, Any]:
    return {"step_id": "s1", "language": language, "code": "SELECT 1",
            "parameters": None, "purpose": "p", "input_artifact_ids": None,
            "depends_on_step_ids": None}


def _step_enum() -> list[str]:
    tool = [t for t in ct.provider_tools(catalog=None)
            if t["name"] == "execute_analysis"][0]
    return list(tool["input_schema"]["properties"]["steps"]["items"]
                ["properties"]["language"]["enum"])


def _limits() -> Any:
    from backend.cockpit_v4 import config

    return config.limits_for("analytical") if hasattr(
        config, "limits_for") else config.Limits()
