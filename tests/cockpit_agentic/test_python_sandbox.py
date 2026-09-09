"""The Python execution boundary, tested by trying to break it.

These are not mock tests. Every one of them starts a real process in real
namespaces and asserts on what that process could and could not do. Where the
host does not provide the namespaces, the tests that need them skip and the
tests about honest unavailability still run -- because "the sandbox is
unavailable" is a supported outcome, and the one thing that is never
acceptable is claiming a boundary that is not there.

The rule this file also defends: CreditProbe never repairs Opus Python. The
sandbox validates nothing about the code's meaning, rewrites nothing, and
returns the interpreter's own traceback unedited.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

from backend.cockpit_agentic import contracts as K
from backend.cockpit_agentic import pysandbox as PS

PACKAGE = Path(PS.__file__).parent

isolated = pytest.mark.skipif(
    not PS.probe().available,
    reason=f"no verified isolation on this host: {PS.probe().reason[:200]}")


@pytest.fixture(scope="module")
def detected():
    return PS.probe()


# ------------------------------------------------------- the probe itself

def test_the_probe_establishes_availability_by_running_something(detected):
    """Availability is a measurement. A host that merely has `unshare` on it
    has proved nothing."""
    assert detected.elapsed_seconds > 0
    if detected.available:
        assert detected.strategy in dict(PS.STRATEGIES)
        assert detected.guarantees
    else:
        assert detected.reason


@isolated
def test_the_probe_records_each_guarantee_with_the_evidence_for_it(detected):
    """A guarantee written as a claim is a comment. Each of these carries what
    the escape attempt actually raised."""
    expected = {"network_denied", "host_filesystem_hidden",
                "host_files_read_only", "jail_skeleton_read_only",
                "repository_hidden", "inputs_read_only",
                "environment_scrubbed", "no_shell", "dependency_surface",
                "privileges_dropped", "separate_process"}
    assert expected <= set(detected.guarantees)
    for name, evidence in detected.guarantees.items():
        assert evidence and evidence.strip(), f"{name} has no evidence"
        # "raised None" is what a guarantee looks like when the check never
        # ran and the missing answer was read as a pass. It happened once,
        # when the result envelope started reshaping the probe's dictionary.
        assert "None" not in evidence, \
            f"{name} reports a finding that was never made: {evidence}"


def test_a_probe_that_did_not_report_on_a_boundary_fails(detected):
    """The evaluator must refuse an incomplete report rather than read every
    absent finding as a passing one."""
    complete = {name: "ok" for name in PS.REQUIRED_FINDINGS}
    for missing in PS.REQUIRED_FINDINGS:
        partial = {k: v for k, v in complete.items() if k != missing}
        ok, why, guarantees, caveats = PS._evaluate(partial, "/repo")
        assert not ok, f"a probe with no {missing} finding was accepted"
        assert missing in why and guarantees == {} and caveats == ()


def test_the_probes_findings_survive_the_result_envelope():
    """The probe reports through the same result path as any other step, and
    that path shapes structured values into table cells. An empty list read
    back as the string '[]' is truthy, so the findings travel as JSON."""
    if not PS.probe().available:
        pytest.skip("no verified isolation on this host")
    result = PS.execute("import json\nresult = json.dumps({'a': [], 'b': 0})")
    assert PS._findings_from({"result": {"columns": [], "rows": result.rows}}) \
        == {"a": [], "b": 0}


# ------------------------------------------------------ what it cannot do

@isolated
def test_the_sandbox_cannot_reach_the_network():
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("import socket\n"
                   "s = socket.socket(); s.settimeout(3)\n"
                   "s.connect(('1.1.1.1', 443))\n"
                   "result = 'REACHED THE NETWORK'")
    assert "Network is unreachable" in (caught.value.detail or "")


@isolated
def test_the_sandbox_cannot_read_the_host_filesystem():
    for path in ("/etc/passwd", "/etc/hosts", "/root/.bashrc",
                 "/proc/1/environ"):
        with pytest.raises(PS.PythonRejected) as caught:
            PS.execute(f"result = open({path!r}).read()")
        detail = caught.value.detail or ""
        assert "FileNotFoundError" in detail or "PermissionError" in detail, \
            f"{path} was reachable: {detail[-200:]}"


@isolated
def test_the_sandbox_cannot_see_this_repository():
    repo = str(Path(PS.__file__).resolve().parents[2])
    result = PS.execute(f"import os\nresult = os.path.exists({repo!r})")
    assert result.rows == [{"value": False}]


@isolated
def test_the_sandbox_holds_no_credential():
    """The one that would matter most. The child's environment is built here,
    not inherited, so a provider key held by the API process is not merely
    unreadable -- it is not present."""
    result = PS.execute(
        "import os\n"
        "result = sorted(k for k in os.environ if any(m in k.upper() for m in "
        "('KEY','TOKEN','SECRET','PASSWORD','CREDENTIAL')))")
    assert result.rows == [], result.rows


@isolated
def test_the_sandbox_has_no_shell():
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("import subprocess\n"
                   "result = subprocess.run(['ls', '/'], "
                   "capture_output=True).stdout.decode()")
    assert "FileNotFoundError" in (caught.value.detail or "")


@isolated
def test_the_sandbox_cannot_write_to_the_host_filesystem():
    """`/usr/lib` is bound from the host. A write landing there would be a
    write outside the jail, which is the only one of these that could."""
    for path in ("/usr/lib/escape", "/lib/escape"):
        with pytest.raises(PS.PythonRejected) as caught:
            PS.execute(f"open({path!r}, 'w').write('x')\nresult = 'WROTE'")
        detail = caught.value.detail or ""
        assert "Error" in detail, f"{path} was writable"


@isolated
def test_the_input_snapshot_is_read_only():
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("open('/work/in/code.py', 'a').write('#')\nresult = 'WROTE'",
                   inputs={"a": {"columns": ["x"], "rows": [[1]]}})
    assert "Error" in (caught.value.detail or "")


@isolated
def test_only_the_approved_packages_are_importable():
    """Not blocked -- absent. The provider SDK, the database drivers and the
    HTTP clients are never mounted into the jail, so there is no allowlist to
    get around."""
    for package in ("anthropic", "requests", "httpx", "duckdb", "cryptography",
                    "sqlalchemy", "fastapi"):
        with pytest.raises(PS.PythonRejected) as caught:
            PS.execute(f"import {package}\nresult = 'IMPORTED'")
        assert "ModuleNotFoundError" in (caught.value.detail or ""), package


@isolated
def test_the_approved_packages_are_actually_usable():
    result = PS.execute(
        "import pandas as pd, numpy as np\n"
        "frame = pd.DataFrame({'q': ['Q1','Q1','Q2'], 'pd': [.02,.04,.05]})\n"
        "result = frame.groupby('q', as_index=False)['pd'].mean()")
    assert [c["name"] for c in result.columns] == ["q", "pd"]
    assert result.rows == [{"q": "Q1", "pd": pytest.approx(0.03)},
                           {"q": "Q2", "pd": 0.05}]


@isolated
def test_the_sandbox_cannot_open_the_analytical_database():
    """Python reads what SQL already fetched, and nothing else. There is no
    database handle inside the jail, so a Python step cannot widen the scope
    the SQL boundary held."""
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("import duckdb\nresult = duckdb.connect().execute("
                   "'select 1').fetchall()")
    assert "ModuleNotFoundError" in (caught.value.detail or "")


# ------------------------------------------------------------- the bounds

@isolated
def test_the_wall_clock_limit_stops_a_step_that_will_not_end():
    started = time.monotonic()
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("import time\nwhile True: time.sleep(0.05)",
                   limits=PS.SandboxLimits(wall_seconds=3.0, cpu_seconds=30))
    assert caught.value.category == K.RESOURCE_LIMIT
    assert time.monotonic() - started < 12


@isolated
def test_the_cpu_limit_stops_a_step_that_spins():
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("while True: pass",
                   limits=PS.SandboxLimits(wall_seconds=30.0, cpu_seconds=2))
    assert caught.value.category == K.RESOURCE_LIMIT
    assert "CPU" in str(caught.value)


@isolated
def test_the_memory_limit_is_reported_as_a_limit_not_as_a_bug():
    """A distinction Opus needs: the code was not wrong, it was too large."""
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("x = bytearray(4_000_000_000)",
                   limits=PS.SandboxLimits(memory_mib=256, wall_seconds=20))
    assert caught.value.category == K.RESOURCE_LIMIT
    assert "MemoryError" in (caught.value.detail or "")


@isolated
def test_a_cancelled_step_is_stopped_rather_than_finished():
    cancelled = {"value": False}

    def cancel():
        cancelled["value"] = True
        return True

    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("import time\nwhile True: time.sleep(0.05)",
                   limits=PS.SandboxLimits(wall_seconds=30.0),
                   cancel=cancel)
    assert "cancelled" in str(caught.value)
    assert cancelled["value"]


@isolated
def test_the_workspace_is_removed_whatever_happened(tmp_path):
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("cockpit-py-*"))
    PS.execute("result = 1")
    try:
        PS.execute("raise SystemExit(3)")
    except PS.PythonRejected:
        pass
    after = set(Path(tempfile.gettempdir()).glob("cockpit-py-*"))
    assert after <= before


# ------------------------------------------------- ownership of the repair

@isolated
def test_a_failing_step_returns_the_interpreters_own_traceback():
    """CreditProbe diagnoses. It does not explain what Opus should have
    written, and it does not write it."""
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("frame = inputs['missing']\nresult = frame")
    detail = caught.value.detail or ""
    assert "KeyError" in detail and "'missing'" in detail
    assert "try" not in str(caught.value).lower()
    assert "instead" not in detail.lower()


def test_the_sandbox_module_contains_no_repair_path():
    """Read off the source: nothing here edits, patches or regenerates code."""
    source = (PACKAGE / "pysandbox.py").read_text()
    lowered = source.lower()
    for forbidden in ("def repair", "def fix", "def rewrite", "def patch",
                      "code.replace(", "code = code."):
        assert forbidden not in lowered, f"pysandbox.py contains {forbidden!r}"


def test_the_sandbox_never_inspects_the_code_for_meaning():
    """An AST allowlist would be a validator with opinions about the analysis,
    and the first thing such a validator learns to do is suggest a fix. The
    boundary here is the kernel's."""
    tree = ast.parse((PACKAGE / "pysandbox.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert not (node.value.id == "ast"), \
                "pysandbox.py parses the model's code"


# -------------------------------------------------------- honest reporting

def test_when_isolation_is_unavailable_python_is_unavailable(monkeypatch):
    """The whole point. No restricted eval, no in-process substitute."""
    monkeypatch.setattr(PS, "_PROBE", PS.Probe(
        available=False, strategy="", reason="no namespaces on this host",
        guarantees={}, checked_at=time.time(), elapsed_seconds=0.1))
    with pytest.raises(PS.PythonRejected) as caught:
        PS.execute("result = 1")
    assert caught.value.category == K.SANDBOX_UNAVAILABLE
    assert "downgraded to in-process execution" in str(caught.value)
    assert "no namespaces on this host" in str(caught.value)


def test_the_audit_record_says_what_ran_under_which_guarantees():
    if not PS.probe().available:
        pytest.skip("no verified isolation on this host")
    result = PS.execute("result = [1, 2]", step_id="s7", request_id="req-9")
    assert result.rows == [{"value": 1}, {"value": 2}]
    audit = result.audit
    assert audit["step_id"] == "s7" and audit["request_id"] == "req-9"
    assert len(audit["code_sha256_16"]) == 16
    assert audit["limits"]["memory_mib"] and audit["limits"]["cpu_seconds"]
    assert audit["guarantees"]["network_denied"]
    assert "result = [1, 2]" not in str(audit), \
        "the audit record carries the code's fingerprint, not its content"


def test_the_limits_come_from_the_ledger_and_are_not_widenable():
    from backend.cockpit_agentic import ledger as L

    for mode, memory in (("standard", 512), ("deep", 1_024)):
        ledger = L.Ledger(request_id=f"r-{mode}", mode=mode)
        limits = PS.SandboxLimits.from_ledger(ledger)
        assert limits.memory_mib == memory
        assert limits.wall_seconds <= ledger.limits.step_wall_seconds
        assert limits.cpu_seconds <= max(1, int(limits.wall_seconds))


# ================================================= inside the agentic loop
#
# These use the LABELLED MOCK provider. What they prove is the application's
# wiring -- that an Opus-authored Python step reaches the sandbox, reads only
# what SQL already fetched, and that its failure comes back to Opus with the
# repair still Opus's to make. They prove nothing about a real model.

from backend.cockpit_agentic import states as st  # noqa: E402
from tests.cockpit_agentic.conftest import scores  # noqa: E402
from tests.cockpit_agentic.fake_provider import FakeProvider  # noqa: E402

SQL_STEP = ("SELECT reporting_quarter, sum(ecl_reported) AS ecl "
            "FROM cockpit_facility_quarter GROUP BY 1 ORDER BY 1 LIMIT 4")

PLAN = {"plan_id": "plan-py", "subquestions": ["the quarter-on-quarter change"],
        "fields_required": ["ecl_reported", "reporting_quarter"],
        "method_summary": "fetch the series, then difference it",
        "expected_output_grain": "one row per quarter",
        "expected_units": "INR crore"}

ANSWER = {"decision": "ANSWER",
          "per_subquestion": [{"subquestion": "the quarter-on-quarter change",
                               "answered": True}],
          "answer": {"narrative": "ECL moved as shown.", "complete": True}}


def _two_steps(python_code):
    return [{"step_id": "s1", "language": "sql", "code": SQL_STEP,
             "purpose": "the ECL series"},
            {"step_id": "s2", "language": "python", "code": python_code,
             "purpose": "difference the series"}]


def _provider(sonnet_answers, *turns):
    return FakeProvider(structured_script=list(sonnet_answers),
                        converse_script=[(lambda _r, t=t: t) for t in turns])


@isolated
def test_an_opus_authored_python_step_runs_over_the_rows_sql_fetched(
        runtime_factory, sonnet_answers):
    code = ("import pandas as pd\n"
            "frame = pd.DataFrame(inputs['s1']['rows'])\n"
            "frame['change'] = frame['ecl'].diff()\n"
            "result = frame")
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "The Cockpit owns stored ECL history.",
         "plan": PLAN, "steps": _two_steps(code)},
        ANSWER)
    outcome = runtime_factory(provider).run("How did ECL move each quarter?")
    assert outcome.status == st.COMPLETED
    results = outcome.results[0].steps
    assert [r.step_id for r in results] == ["s1", "s2"]
    assert "change" in [c["name"] for c in results[1].columns]
    assert results[1].row_count == results[0].row_count
    assert outcome.python_audit and outcome.python_audit[0]["step_id"] == "s2"


@isolated
def test_a_python_step_cannot_reach_data_the_sql_step_did_not_fetch(
        runtime_factory, sonnet_answers):
    """The scope boundary is not re-argued inside the sandbox; there is simply
    no connection there to argue with."""
    code = ("import duckdb\n"
            "result = duckdb.connect().execute('select 1').fetchall()")
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "x", "plan": PLAN, "steps": _two_steps(code)},
        {"decision": "INSUFFICIENT_DATA",
         "gap_addressed": "the step could not run"})
    outcome = runtime_factory(provider).run("How did ECL move?")
    assert outcome.failures
    failure = outcome.failures[0]
    assert failure.failing_step_id == "s2"
    assert "ModuleNotFoundError" in str(failure.to_dict())


@isolated
def test_a_failed_python_step_returns_the_full_context_to_opus(
        runtime_factory, sonnet_answers):
    """Section 8.1, for Python as for SQL: the repair request carries the whole
    effective context, and the repair is Opus's."""
    from backend.cockpit_agentic import failure as failure_mod

    broken = "result = len(inputs['s1']['rows']) / 0"
    repaired = "result = [{'n': len(inputs['s1']['rows'])}]"
    provider = _provider(
        sonnet_answers,
        {"decision": "PROCEED_COCKPIT", "scores": scores(),
         "public_explanation": "x", "plan": PLAN,
         "steps": _two_steps(broken)},
        {"action": "submit_repaired_code", "plan": PLAN,
         "what_went_wrong": "the divisor was zero",
         "steps": _two_steps(repaired)},
        ANSWER)
    outcome = runtime_factory(provider).run("How did ECL move?")

    assert outcome.status == st.COMPLETED
    assert outcome.failures and outcome.failures[0].failing_step_id == "s2"

    # The request that carried the failure back, read off the wire.
    repair = provider.requests[1]
    serialized = str(repair)
    assert "ZeroDivisionError" in serialized
    assert broken in serialized, "the failed code itself must go back"
    for part in failure_mod.REQUIRED_CONTEXT:
        assert part, part
    # The catalogue is in the system prefix, the failure in the conversation.
    assert "cockpit_facility_quarter" in str(repair["system"])
    assert repair["messages"], "the failure was sent as a conversation turn"

    # And the repaired code is Opus's, not the application's: nothing in the
    # outbound request proposes replacement Python.
    assert repaired not in str(repair), \
        "the application offered a replacement expression"


@isolated
def test_a_weaker_posture_is_reported_rather_than_rounded_up(detected):
    """The two launch strategies do not give the same thing. Under a user
    namespace the code is uid 0 of its own throwaway tree and can write inside
    it; under privileged namespaces it is `nobody` and cannot. Neither reaches
    the host, and the difference is stated rather than averaged away."""
    if detected.strategy == "privileged_namespaces":
        assert detected.caveats == ()
        assert "PermissionError" in detected.guarantees[
            "jail_skeleton_read_only"]
    else:
        for caveat in detected.caveats:
            assert "does not outlive" in caveat or "outlives" in caveat


@isolated
def test_a_write_to_the_host_libraries_would_fail_the_probe():
    """The evaluator's own logic, exercised: the writable-jail finding is a
    caveat, the writable-host finding is a refusal."""
    base = {name: "OSError" for name in PS.REQUIRED_FINDINGS}
    base.update({"uid": 65534, "repository_visible": False,
                 "root_entries": [], "secretish_env": [], "binary_dirs": [],
                 "approved_imports": ["2.5.0", "3.0.3"],
                 "shell": "FileNotFoundError"})

    ok, _why, _g, caveats = PS._evaluate(
        {**base, "system_writable": "WRITABLE", "site_writable": "WRITABLE"},
        "/repo")
    assert ok and len(caveats) == 1

    ok, why, _g, _c = PS._evaluate(
        {**base, "host_bind_writable": "WRITABLE"}, "/repo")
    assert not ok and "host" in why
