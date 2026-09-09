"""Opus writes the code. CreditProbe validates, executes and diagnoses.

Two kinds of proof here, because the invariant can be broken in two ways.

The first is by OMISSION: sending a repair request that does not carry the
context the repair needs, so whatever comes back is a guess wearing the shape
of a fix. Against that, the sixteen required parts of the effective context are
asserted against the ACTUAL serialized outbound request -- for a failed SQL
step and for a failed Python step -- with probes that content satisfies and a
reference, an id or a hash does not.

The second is by HELPFULNESS: some path in the application that notices what
would have worked and quietly supplies it. Against that, the package's own
source is read.

The mock provider is labelled. What these prove is what CreditProbe puts in the
request and what it does not contain, which is exactly what a mock can prove.
They say nothing about how a real model uses any of it.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import failure as failure_mod
from backend.cockpit_agentic import pysandbox as PS
from backend.cockpit_agentic import states as st
from tests.cockpit_agentic.conftest import scores
from tests.cockpit_agentic.fake_provider import FakeProvider

PACKAGE = Path(failure_mod.__file__).parent

QUESTION = ("Show me the PIT 12-month PD by sector for Construction in "
            "2026Q2 and how it moved")

PLAN = {"plan_id": "plan-own-1",
        "subquestions": ["the PIT twelve-month PD by sector"],
        "fields_required": ["pd_pit_12m", "sector_code"],
        "method_summary": "average the PIT twelve-month PD by sector",
        "assumptions": ["the user means the point-in-time PD"]}

GOOD_SQL = ("SELECT reporting_quarter, avg(pd_pit_12m) AS pd "
            "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 LIMIT 4")

ANSWER = {"decision": "ANSWER",
          "per_subquestion": [{"subquestion": "the PIT twelve-month PD by "
                                              "sector", "answered": True}],
          "answer": {"narrative": "PIT PD by sector.", "complete": True}}


def _sql_step(code, step_id="s1"):
    return {"step_id": step_id, "language": "sql", "code": code,
            "purpose": "the PD series"}


def _python_step(code, step_id="s2"):
    return {"step_id": step_id, "language": "python", "code": code,
            "purpose": "difference the series"}


def _run(runtime_factory, sonnet_answers, first_steps, repaired_steps):
    """One failure, one repair, and the repair request kept."""
    captured: dict[str, object] = {}

    def gate(_request):
        return {"decision": "PROCEED_COCKPIT", "scores": scores(),
                "public_explanation": "The Cockpit owns stored PD history.",
                "plan": PLAN, "steps": first_steps}

    def repair(request):
        captured["request"] = request
        return {"action": "submit_repaired_code",
                "what_went_wrong": "the column named does not exist",
                "plan": PLAN, "steps": repaired_steps}

    provider = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[gate, repair, lambda _r: ANSWER])
    outcome = runtime_factory(provider).run(QUESTION)
    assert "request" in captured, (
        f"no repair request was ever dispatched; the run ended "
        f"{outcome.status}")
    return {"outcome": outcome, "provider": provider,
            "request": captured["request"],
            "serialized": json.dumps(captured["request"], default=str)}


@pytest.fixture()
def sql_repair(runtime_factory, sonnet_answers):
    failing = ("SELECT facility_id, pd_12_month FROM cockpit_facility_quarter "
               "WHERE reporting_quarter = '2026Q2'")
    return {**_run(runtime_factory, sonnet_answers,
                   [_sql_step(failing)], [_sql_step(GOOD_SQL, "s1b")]),
            "failed_code": failing}


@pytest.fixture()
def python_repair(runtime_factory, sonnet_answers):
    if not PS.probe().available:
        pytest.skip("no verified isolation on this host")
    failing = "result = inputs['s1']['rows'][0]['pd'] / inputs['s1']['missing']"
    repaired = "result = [{'n': len(inputs['s1']['rows'])}]"
    return {**_run(runtime_factory, sonnet_answers,
                   [_sql_step(GOOD_SQL), _python_step(failing)],
                   [_sql_step(GOOD_SQL), _python_step(repaired, "s2b")]),
            "failed_code": failing}


# =================================================== the sixteen, item by item
#
# Each test reads the request that actually went out. The probes are content:
# the question's own words, a field from the far end of the dictionary, the
# failed code itself. A `base_context_id` satisfies none of them.

def test_the_repair_request_carries_the_original_question(sql_repair):
    assert QUESTION in sql_repair["serialized"]


def test_the_repair_request_carries_the_cleaned_business_request(
        sql_repair, sonnet_answers):
    cleaned = sonnet_answers[0]["english_text"]
    assert cleaned[:50] in sql_repair["serialized"]


def test_the_repair_request_carries_the_thread_context(sql_repair):
    """An empty thread must be REPORTED as empty. Otherwise a continuation
    cannot tell "there is no history" from "the history was withheld"."""
    opening = str(sql_repair["request"]["messages"][0]["content"])
    assert "thread" in opening


def test_the_repair_request_carries_the_scope_and_filters(sql_repair):
    opening = str(sql_repair["request"]["messages"][0]["content"])
    assert "scope_and_filters" in opening
    assert "test-runtime-20q" in sql_repair["serialized"]


def test_the_repair_request_carries_the_whole_dictionary_with_grains(
        sql_repair):
    """Not a sample of it. Fields from both ends, and the grain of the
    relation the failure was in."""
    serialized = sql_repair["serialized"]
    for field in ("pd_pit_12m", "pd_ttc_lifetime", "total_haircut",
                  "headroom_value", "scenario_ecl", "quarter_offset"):
        assert field in serialized, field
    assert "one atomic facility position per reporting quarter" in serialized
    # And a grain that carries a trap with it, because the trap is the point:
    # a statement joined to facilities repeats once per facility.
    assert "repeats the statement once per facility" in serialized


def test_a_catalogue_reference_would_not_satisfy_that(sql_repair):
    """The test above has to be one a hash cannot pass, so: the catalogue is
    present as content, and no identifier stands in for it."""
    serialized = sql_repair["serialized"]
    assert serialized.count("pd_pit_12m") >= 1
    for stand_in in ("base_context_id", "catalogue_hash", "schema_hash",
                     "catalog_ref"):
        assert stand_in not in serialized


def test_the_repair_request_carries_the_measured_coverage(sql_repair):
    opening = str(sql_repair["request"]["messages"][0]["content"])
    assert "measured_coverage" in opening


def test_the_repair_request_carries_the_functionality_decision(sql_repair):
    serialized = sql_repair["serialized"]
    assert "PROCEED_COCKPIT" in serialized
    assert "The Cockpit owns stored PD history." in serialized


def test_the_repair_request_carries_the_current_plan(sql_repair):
    serialized = sql_repair["serialized"]
    assert PLAN["plan_id"] in serialized
    assert PLAN["method_summary"] in serialized


def test_the_repair_request_carries_the_exact_failed_code(sql_repair):
    assert sql_repair["failed_code"] in sql_repair["serialized"].replace(
        "\\", "")


def test_the_repair_request_carries_the_bound_parameters(sql_repair):
    assert '"parameters"' in sql_repair["serialized"].replace("\\", "")


def test_the_repair_request_carries_the_engines_own_diagnostic(sql_repair):
    flat = sql_repair["serialized"].replace("\\", "")
    assert "UNRESOLVED_FIELD" in flat
    assert "pd_12_month" in flat and "not found" in flat


def test_the_repair_request_carries_the_results_already_obtained(sql_repair):
    assert "completed_steps" in sql_repair["serialized"]


def test_the_repair_request_carries_what_was_already_tried(sql_repair):
    assert "previous_failed_approaches" in sql_repair["serialized"]


def test_the_repair_request_carries_the_remaining_submissions_and_rounds(
        sql_repair):
    flat = sql_repair["serialized"].replace("\\", "")
    assert "submissions_remaining" in flat
    assert "analysis_rounds_remaining" in flat
    assert "Submissions remaining: 4" in flat


def test_the_repair_request_carries_the_remaining_calls_time_tokens_and_spend(
        sql_repair):
    flat = sql_repair["serialized"].replace("\\", "")
    for key in ("model_requests_remaining", "seconds_remaining",
                "tokens_remaining", "spend"):
        assert key in flat, key


# ------------------------------------------- the same sixteen, for Python

def test_a_failed_python_step_gets_the_same_sixteen(python_repair):
    """The requirement is about a failed EXECUTION, not about SQL."""
    flat = python_repair["serialized"].replace("\\", "")
    assert QUESTION in flat
    assert "pd_ttc_lifetime" in flat
    assert python_repair["failed_code"] in flat
    assert "KeyError" in flat and "missing" in flat
    assert "submissions_remaining" in flat
    # And the SQL step that DID succeed came back with it, so Opus is not
    # asked to recompute what it already has.
    assert "s1" in flat


def test_the_audit_records_all_sixteen_as_verified(sql_repair, python_repair):
    for run in (sql_repair, python_repair):
        audits = run["outcome"].repair_audits
        assert audits, "no repair was audited"
        for audit in audits:
            assert audit["missing"] == []
            assert set(audit["verified"]) == set(failure_mod.OUTBOUND_ITEMS)


# =============================================== the audit is not decorative

def test_the_sixteen_are_the_sixteen_that_were_specified():
    assert list(failure_mod.OUTBOUND_ITEMS) == [
        "original_question", "cleaned_question", "thread_context",
        "scope_and_filters", "field_dictionary_and_grain",
        "coverage_and_missingness", "functionality_decision", "analysis_plan",
        "failed_code", "bound_parameters", "diagnostics", "completed_results",
        "previous_approaches", "submissions_remaining", "rounds_remaining",
        "budgets_remaining"]


def test_a_request_missing_any_one_of_them_is_refused():
    """The check must be able to fail, or its passing means nothing."""
    expectations = {key: [f"probe-{key}"]
                    for key in failure_mod.OUTBOUND_ITEMS}
    complete = " ".join(f"probe-{key}" for key in failure_mod.OUTBOUND_ITEMS)
    assert failure_mod.audit_outbound(complete, expectations) == []
    for key in failure_mod.OUTBOUND_ITEMS:
        without = complete.replace(f"probe-{key}", "")
        assert failure_mod.audit_outbound(without, expectations) == [key]


def test_an_item_with_no_probe_counts_as_missing():
    """An expectation nobody wrote is not an expectation that was met."""
    expectations = {key: [] for key in failure_mod.OUTBOUND_ITEMS}
    assert failure_mod.audit_outbound("anything", expectations) == list(
        failure_mod.OUTBOUND_ITEMS)


def test_an_incomplete_context_stops_the_request_rather_than_sending_it(
        runtime_factory, sonnet_answers, monkeypatch):
    """If this application cannot assemble the context, the honest outcome is
    a stop that says so -- not a repair request Opus cannot act on."""
    monkeypatch.setattr(failure_mod, "audit_outbound",
                        lambda _s, _e: ["field_dictionary_and_grain"])
    failing = "SELECT pd_12_month FROM cockpit_facility_quarter"
    provider = FakeProvider(
        structured_script=list(sonnet_answers),
        converse_script=[
            lambda _r: {"decision": "PROCEED_COCKPIT", "scores": scores(),
                        "public_explanation": "e", "plan": PLAN,
                        "steps": [_sql_step(failing)]}])
    outcome = runtime_factory(provider).run(QUESTION)
    assert outcome.status == st.EXECUTION_FAILED
    assert outcome.envelope.stop_reason == K.INFRASTRUCTURE_ERROR
    assert "defect here" in outcome.envelope.narrative
    # And the repair request was never sent.
    assert provider.purposes() == ["opus_gate_and_plan"]


def test_the_inspection_hook_can_only_read_the_request():
    """`before_dispatch` is handed the assembled request and returns nothing.

    A hook that could return a modified request would be the single most
    convenient place in this codebase to quietly improve Opus's context, so it
    is built as an inspection point: the caller discards whatever it returns.
    """
    source = (PACKAGE / "opus.py").read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "before_dispatch"]
    assert len(calls) == 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            assigned = ast.dump(node.targets[0] if isinstance(node, ast.Assign)
                                else node.target)
            assert "before_dispatch" not in assigned or \
                "self" in assigned, assigned
    assert "= self.before_dispatch(" not in source


# ====================================================== nothing repairs here

def test_no_module_in_the_package_rewrites_the_models_code():
    """Read off the source. A rewrite would show up as an assignment back into
    a step's code, or as a string method applied to it."""
    forbidden = ("step.code =", "step.code=", ".code = code.", "code.replace(",
                 "code = code.replace", "submitted_code =",
                 "step.code.replace", "rewrite_sql", "fix_sql", "repair_sql",
                 "patch_sql", "substitute_column", "replace_column",
                 "rewrite_python", "generate_replacement")
    for path in sorted(PACKAGE.rglob("*.py")):
        source = path.read_text()
        for fragment in forbidden:
            assert fragment not in source, f"{path.name}: {fragment!r}"


def _code_strings(path: Path) -> list[str]:
    """String literals that are not docstrings.

    A module may DESCRIBE the rule -- "exactly one SELECT per step" is
    instruction text Opus needs -- without composing a query. The distinction
    is where the string lives, so the docstrings come out first.
    """
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            text = ast.get_docstring(node, clean=False)
            if text:
                docstrings.add(text)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                found.append(node.value)
    return found


def test_no_module_outside_the_engine_reader_authors_sql():
    """`sql.py` writes the two metadata queries it needs to show Opus sample
    rows and valid filter values. Nothing else in the package composes SQL,
    and in particular the failure and runtime modules do not -- which is where
    a helpful repair would live.

    Instruction text that NAMES SQL is allowed and necessary: the execution
    contract has to tell Opus that a step is one SELECT. What is not allowed is
    a query -- a SELECT with a FROM against a Cockpit relation.
    """
    allowed = {"sql.py"}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name in allowed:
            continue
        for text in _code_strings(path):
            flat = " ".join(text.lower().split())
            # The precise definition of composing a query against this domain:
            # naming one of its relations where a query reads from. Prose that
            # merely says the word SELECT is instruction, not SQL.
            assert not re.search(r"\b(from|join)\s+cockpit_", flat), \
                f"{path.name} composes a query: {flat[:140]!r}"


def test_the_failure_module_offers_alternatives_without_choosing_between_them():
    """`available_alternatives` is a catalogue fact: these fields exist and
    are near the name that did not. Which one the question means is not a
    catalogue fact, and the packet does not pretend otherwise."""
    source = (PACKAGE / "failure.py").read_text()
    assert "do not substitute one silently" in source.lower()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.lower()
            assert "use pd_pit" not in text and "use pd_ttc" not in text, \
                "failure.py tells Opus which field to use"


def test_no_canned_analysis_is_reachable_after_a_failure():
    """Section 18. The runtime's terminal paths are an answer Opus authored, a
    clarification, or a stop that says why. There is no fourth.

    Read as calls, not as words: a docstring may say what the runtime must not
    do, and this file's whole point is that saying it is not enough. What would
    make it false is a CALL into a fallback, a template or a decomposition.
    """
    tree = ast.parse((PACKAGE / "runtime.py").read_text())
    called: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            called.append(function.id)
        elif isinstance(function, ast.Attribute):
            called.append(function.attr)
    for name in called:
        lowered = name.lower()
        for temptation in ("fallback", "canned", "deterministic", "template",
                           "decompos", "attribution", "shapley", "narrate"):
            assert temptation not in lowered, \
                f"runtime.py calls {name}()"


def test_the_sandbox_returns_the_traceback_without_advising_on_it():
    """The Python half of the same rule."""
    source = (PACKAGE / "pysandbox.py").read_text()
    for advice in ("you should", "try instead", "did you mean", "consider "):
        assert advice not in source.lower(), advice
