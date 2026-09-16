"""
A refusal that says it was a refusal.

MODEL MOCK · REAL DATABASE/RUNNER. No paid provider call.

A step stopped by the join-grain check or by a missing Python sandbox used
to be reported as a query that RAN and failed: `phase: "runtime"`,
`executed: true`, and a reader told "<purpose> failed while running" about a
batch in which the engine was never asked for anything. Two lines did it --
a two-valued `phase` switch that called everything-not-bind a runtime
failure, and an `executed` exclusion tuple that named three checks out of
nine.

Underneath was a placement bug. `multiplication_risk` is a judgement about
the query TEXT -- a regex plus a catalogue read, no engine, no parameters,
no earlier artifact -- yet it ran inside `_run_sql`, so the fan-out refusal
fired after the step budget was spent and after the run had publicly
announced the very query it refuses. Three of the four branches around it
could not execute, and the fourth turned a broken diagnostic into a clean
bill of health.

What is pinned here:

  the rung is derived, once        -> phase and executed cannot disagree
  the check runs before anything   -> refused above TOOL_VALIDATED
  the refusal carries its evidence -> facts, not a sentence to regex
  a one-to-one join repeats nothing -> and is no longer refused
  a query that really ran          -> still says so
"""

from __future__ import annotations

import json

import pytest
from conftest import ScriptedResult, intent, tool_call

from backend.cockpit_v4 import catalog as cat
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import events as ev
from backend.cockpit_v4 import execute_tool as xt
from backend.cockpit_v4 import lake
from backend.cockpit_v4 import states as st
from backend.cockpit_v4.contracts import Rejection

#: A total of a BORROWER measure across the facility join. Every facility of
#: a borrower repeats that borrower's debt, so the total counts it once per
#: facility. Verified against the catalogue: `total_debt_sar_mn` is `rcy`,
#: and the pair is declared "many facility rows to one borrower row".
CORPORATE_FAN_OUT = (
    "SELECT b.sector, SUM(b.total_debt_sar_mn) AS debt "
    "FROM corp_facility_quarter f "
    "JOIN corp_borrower_quarter b ON b.borrower_id = f.borrower_id "
    "AND b.reporting_quarter = f.reporting_quarter "
    "GROUP BY 1")

#: The catalogue declares this pair "one behaviour row to one account" and
#: says in as many words that it repeats nothing. It was refused anyway,
#: because every declared join was read as many-to-one.
RETAIL_ONE_TO_ONE = (
    "SELECT SUM(a.ead_sar_mn) AS ead "
    "FROM retail_behaviour_month b "
    "JOIN retail_account_month a ON a.account_id = b.account_id "
    "AND a.reporting_month = b.reporting_month")

#: Binds, and then fails in the engine: the cast is legal to plan and
#: impossible to evaluate. The no-regression case.
REALLY_RUNS_AND_FAILS = (
    "SELECT CAST(borrower_id AS INTEGER) AS n FROM corp_borrower_quarter "
    "LIMIT 1")


@pytest.fixture(scope="module", autouse=True)
def _both_books_published():
    for domain_id in dom.DOMAIN_IDS:
        if not lake.exists(dom.DEFAULT_RELEASES[domain_id]):
            pytest.skip("run scripts/cockpit_v4/seed_domains.py")


@pytest.fixture
def drive_domain(store_db, runtime):
    """Run one scripted conversation, in one BOOK, through the real worker.

    `drive` is not usable here: it builds on the legacy catalogue, which
    states no joins, so the check under test is silent on it.
    """
    from conftest import ScriptedProvider
    from test_domain_execution import make_domain_run

    from backend.cockpit_v4.worker import Worker

    def _drive(domain_id: str, question: str, script):
        provider = ScriptedProvider(script)
        runtime.provider = provider
        record = make_domain_run(store_db, domain_id, question)
        outcome = Worker(store=store_db, runtime=runtime).execute(record)
        return outcome, provider, record
    return _drive


@pytest.fixture
def book():
    """An execution service over one real book, with its declared joins.

    NOT the `service` fixture. That one is built on the legacy catalogue,
    which states no joins at all, so `multiplication_risk` is silent on it
    both before and after this change -- a test written against it would
    pass without exercising anything.
    """
    from backend.cockpit_v4.config import STANDARD_LIMITS
    from backend.cockpit_v4.execute_tool import ExecutionService

    def _open(domain_id: str, store=None):
        release_id = dom.DEFAULT_RELEASES[domain_id]
        catalog = cat.build(domain_id=domain_id,
                            tenant_id=lake.DEFAULT_TENANT,
                            release_id=release_id)
        return ExecutionService(
            session=cat.open_session(catalog=catalog), scope=None,
            catalog=catalog, store=store, run_id="r-grain",
            tenant_id=lake.DEFAULT_TENANT, release_id=release_id,
            limits=STANDARD_LIMITS)
    return _open


def submission(*steps):
    """One `execute_analysis` submission, parsed as the run parses it."""
    from backend.cockpit_v4.contracts import parse_execution

    return parse_execution({
        "intent": intent("DATA_ANALYSIS", "COCKPIT",
                         understood="totals by sector"),
        "objective": "totals by sector", "subquestions": ["totals"],
        "scope": {"reporting_months": [], "filters": {}},
        "metadata_receipt_ids": [], "fields_required": [],
        "expected_output_grain": "sector", "expected_units": "SAR million",
        "steps": list(steps), "repair_of_submission_id": ""}, max_steps=4)


def step(code: str, *, step_id: str = "s1", depends_on=()):
    return {"step_id": step_id, "language": "sql", "code": code,
            "parameters": {}, "purpose": f"{step_id} purpose",
            "input_artifact_ids": [], "depends_on_step_ids": list(depends_on)}


# ---- the rung, derived once ---------------------------------------------

def test_no_check_this_module_names_is_missing_from_the_phase_table():
    """The guard against the next `join_grain`.

    `join_grain` and `sandbox` were not classified wrongly on purpose; they
    were simply absent from a two-valued switch, and absence defaulted to
    "this query ran". A table that must be exhaustive turns the next
    omission into a failing test instead of a false trace.
    """
    named = {value for name, value in vars(xt).items()
             if name.startswith("CHECK_") and isinstance(value, str)}
    assert named, "no CHECK_* constants found; this test has lost its target"
    missing = named - set(xt.PHASE_OF_CHECK)
    assert not missing, f"checks with no rung: {sorted(missing)}"


@pytest.mark.parametrize("check", sorted(xt.REFUSED_BEFORE_EXECUTION))
def test_every_check_that_refuses_before_execution_says_nothing_ran(check):
    """`executed` is not a second judgement -- it is the rung, read again."""
    published = xt.StepResult(
        step_id="s1", status="failed", language="sql", code_digest="d",
        purpose="p", error_code=st.SQL_VALIDATION, failed_check=check,
        message="refused").to_dict()
    assert published["executed"] is False, (
        f"{check} refused before anything ran and reported that it ran")
    assert published["phase"] != xt.PHASE_RUNTIME


def test_each_refusal_is_on_the_rung_it_actually_reached():
    """Three rungs, and they are not interchangeable.

    A reader told "refused before it ran" and a reader told "did not bind"
    have been told different things, and an operator reading the trace of a
    step the batch never reached should not see either.
    """
    def rung(check: str) -> str:
        return xt.StepResult(step_id="s", status="failed", language="sql",
                             code_digest="d", purpose="p",
                             failed_check=check).to_dict()["phase"]

    assert rung(xt.CHECK_BIND) == xt.PHASE_BIND
    assert rung(xt.CHECK_GRAIN) == xt.PHASE_CHECK
    assert rung(xt.CHECK_SANDBOX) == xt.PHASE_CHECK
    assert rung(xt.CHECK_DOMAIN) == xt.PHASE_CHECK
    assert rung(xt.CHECK_DEPENDENCY) == xt.PHASE_NOT_STARTED
    assert rung(xt.CHECK_BATCH) == xt.PHASE_NOT_STARTED
    assert rung(xt.CHECK_RUNTIME) == xt.PHASE_RUNTIME


def test_a_check_this_module_has_never_heard_of_is_not_evidence_it_ran():
    """Fail closed. An unrecognised name is the one case where guessing
    "runtime" publishes a claim nobody made."""
    assert xt.phase_of("something_invented_later") == xt.PHASE_CHECK
    assert xt.phase_of("") == xt.PHASE_CHECK


# ---- the check runs before anything -------------------------------------

def test_a_fan_out_total_is_refused_by_validation_not_by_the_runner(book):
    """It is a judgement about the TEXT, so it needs no engine.

    It used to wait until `_run_sql`, which is after the step budget is
    spent and after the run has announced the query as validated.
    """
    service = book(dom.CORPORATE)
    with pytest.raises(Rejection) as caught:
        service.validate_batch(submission(step(CORPORATE_FAN_OUT)))
    assert caught.value.code == st.SQL_VALIDATION
    assert caught.value.field_path == "steps.s1.code"


def test_the_refusal_names_the_join_both_grains_and_the_measure(book):
    """As DATA, not as a sentence to regex.

    The prose is assembled by f-string and will be re-worded; a test that
    reads the measure out of an English sentence passes when the sentence
    is wrong.
    """
    service = book(dom.CORPORATE)
    with pytest.raises(Rejection) as caught:
        service.validate_batch(submission(step(CORPORATE_FAN_OUT)))
    detail = caught.value.detail

    assert detail["failed_check"] == xt.CHECK_GRAIN
    assert detail["phase"] == xt.PHASE_CHECK
    assert detail["many_relation"] == "corp_facility_quarter"
    assert detail["one_relation"] == "corp_borrower_quarter"
    assert detail["join_key"] == ["borrower_id", "reporting_quarter"]
    assert "total_debt_sar_mn" in detail["measures_at_risk"]
    for grain in ("many_grain", "one_grain"):
        assert detail[grain] and detail[grain] != "unknown", grain
    # A report, not a correction: which de-duplication is right depends on
    # what is being asked, and choosing one here would be choosing the
    # analysis.
    assert "does not choose" in detail["explanation"]


def test_an_explicit_de_duplication_is_not_refused(book):
    """False positives are the expensive failure.

    A query that de-duplicates the repeated side is correct, and refusing
    correct SQL costs the analyst a whole submission to discover that the
    check was wrong.
    """
    service = book(dom.CORPORATE)
    deduplicated = (
        "WITH one_row AS (SELECT DISTINCT borrower_id, reporting_quarter, "
        "sector, total_debt_sar_mn FROM corp_borrower_quarter) "
        "SELECT sector, SUM(total_debt_sar_mn) AS debt FROM one_row "
        "GROUP BY 1")
    service.validate_batch(submission(step(deduplicated)))


def test_a_join_the_catalogue_says_repeats_nothing_is_not_refused(book):
    """`retail_behaviour_month -> retail_account_month` is declared "one
    behaviour row to one account", and its own note says the join repeats
    nothing -- yet every declared pair was read as many-to-one, so summing
    an account's exposure across it was refused. The fact was already in the
    catalogue; the check was not reading it."""
    service = book(dom.RETAIL)
    service.validate_batch(submission(RETAIL_ONE_TO_ONE and
                                      step(RETAIL_ONE_TO_ONE)))


def test_a_many_to_one_retail_join_is_still_refused(book):
    """The cardinality skip is narrow. A customer total repeated once per
    account is the same trap in the other book."""
    service = book(dom.RETAIL)
    fan_out = ("SELECT SUM(c.total_ead_sar_mn) AS ead "
               "FROM retail_account_month a "
               "JOIN retail_customer_month c ON c.customer_id = a.customer_id "
               "AND c.reporting_month = a.reporting_month")
    with pytest.raises(Rejection) as caught:
        service.validate_batch(submission(step(fan_out)))
    assert caught.value.detail["failed_check"] == xt.CHECK_GRAIN


# ---- deferred steps -----------------------------------------------------

def test_a_deferred_step_is_grain_checked_before_anything_runs(book):
    """The check needs no bound parameters and no earlier artifact, so it
    applies to a step that declares a dependency exactly as it applies to
    one that does not. Ordered after the bind proof it would not have: that
    one is skipped for deferred steps, and the refusal would then depend on
    whether a step happened to declare a dependency."""
    service = book(dom.CORPORATE)
    with pytest.raises(Rejection) as caught:
        service.validate_batch(submission(
            step("SELECT 1 AS one", step_id="s1"),
            step(CORPORATE_FAN_OUT, step_id="s2", depends_on=["s1"])))
    assert caught.value.field_path == "steps.s2.code"
    assert caught.value.detail["failed_check"] == xt.CHECK_GRAIN


def test_a_deferred_step_is_not_refused_merely_for_being_deferred(book):
    """Guards the over-refusal. A dependency is not a fan-out."""
    service = book(dom.CORPORATE)
    report = service.validate_batch(submission(
        step("SELECT 1 AS one", step_id="s1"),
        step("SELECT 2 AS two", step_id="s2", depends_on=["s1"])))
    assert report["bound_at_run_time"] == ["s2"]
    assert report["bound_now"] == ["s1"]


# ---- a step that really ran ---------------------------------------------

def test_a_step_that_really_ran_and_failed_still_says_it_ran(book, store_db):
    """The no-regression half. Narrowing what counts as "executed" must not
    swallow the case where the engine genuinely did the work."""
    service = book(dom.CORPORATE, store=store_db)
    batch = service.run_batch(submission(step(REALLY_RUNS_AND_FAILS)),
                              submission_id="sub-1", deadline_seconds=20.0)
    published = batch.steps[0].to_dict()
    assert published["phase"] == xt.PHASE_RUNTIME
    assert published["executed"] is True
    assert published["failed_check"] == xt.CHECK_RUNTIME


def test_a_step_the_batch_never_reached_does_not_report_that_it_executed(
        book, store_db):
    """`not_started` is its own rung because "a check refused it" would be a
    second untrue thing to say about a step nothing ever looked at."""
    service = book(dom.CORPORATE, store=store_db)
    batch = service.run_batch(
        submission(step(REALLY_RUNS_AND_FAILS, step_id="s1"),
                   step("SELECT 1 AS one", step_id="s2")),
        submission_id="sub-2", deadline_seconds=20.0)
    later = batch.steps[1].to_dict()
    assert later["status"] == "not_run"
    assert later["executed"] is False, (
        "a step the batch stopped before reaching reported that it ran")
    assert later["phase"] == xt.PHASE_NOT_STARTED


def test_a_python_step_with_no_runner_reports_that_nothing_ran(book):
    """Sandbox refusals are the other half of the same defect: V4 reports
    Python UNAVAILABLE rather than quietly evaluating it, and then said the
    step had executed."""
    service = book(dom.CORPORATE)
    with pytest.raises(Rejection) as caught:
        service.validate_batch(submission(
            {"step_id": "s1", "language": "python", "code": "x = 1",
             "parameters": {}, "purpose": "p", "input_artifact_ids": [],
             "depends_on_step_ids": []}))
    assert caught.value.code == st.PYTHON_UNAVAILABLE
    assert caught.value.detail["failed_check"] == xt.CHECK_SANDBOX
    assert xt.phase_of(xt.CHECK_SANDBOX) == xt.PHASE_CHECK


# ---- what the run, the reader and the analyst are told ------------------

def _events(store, run_id):
    return list(store.events_since(run_id, 0))


def _grain_run(drive_domain):
    """One real run whose only submission is the fan-out."""
    return drive_domain(
        dom.CORPORATE, "What is total debt by sector?",
        [ScriptedResult(tool_calls=[tool_call("execute_analysis", {
            "intent": intent("DATA_ANALYSIS", "COCKPIT",
                             understood="total debt by sector"),
            "objective": "total debt by sector",
            "subquestions": ["total debt by sector"],
            "scope": {"reporting_months": [], "filters": {}},
            "metadata_receipt_ids": [], "fields_required": [],
            "expected_output_grain": "sector",
            "expected_units": "SAR million",
            "steps": [step(CORPORATE_FAN_OUT)],
            "repair_of_submission_id": ""}, "tu-1")])])


def test_the_run_never_says_it_validated_the_query_it_refused(drive_domain,
                                                              store_db):
    """ORDER, not presence.

    The refusal used to fire inside the runner, which is after
    `tool.validated` has already told the reader the query was checked and
    bound. Announcing a query as validated and then refusing it is two true
    statements in the wrong order, which is the same defect the bind proof
    was added to fix.
    """
    _outcome, _provider, record = _grain_run(drive_domain)
    kinds = [e.event_type for e in _events(store_db, record.run_id)]
    assert ev.TOOL_VALIDATED not in kinds, (
        "the run announced the query as validated and then refused it")
    stages = {e.stage for e in _events(store_db, record.run_id)}
    assert "executing" not in stages, (
        f"a refused submission reached the executing stage: {sorted(stages)}")


def test_the_refused_batch_stores_no_result(drive_domain, store_db):
    """Refusing above the runner means no artifact survives -- which is
    `validate_batch`'s own contract: a batch whose second step is wrong
    should not have run its first. Read from the artifacts table, not from
    the run's own report of itself."""
    _outcome, _provider, record = _grain_run(drive_domain)
    stored = store_db._connect().execute(
        "SELECT COUNT(*) AS n FROM artifacts WHERE run_id=?",
        (record.run_id,)).fetchone()
    assert stored["n"] == 0, (
        "a refused submission left a result behind; nothing ran")


def test_the_reader_is_told_it_was_refused_not_that_it_failed_while_running(
        drive_domain, store_db):
    """The sentence a person actually sees."""
    outcome, _provider, record = _grain_run(drive_domain)
    said = " ".join(e.public_message or ""
                    for e in _events(store_db, record.run_id))
    assert "refused before anything ran" in said, said
    assert "failed while running" not in said
    assert "Query validated and bound" not in said
    assert outcome.state in (st.FAILED, st.PARTIAL), outcome.state


def test_the_analyst_is_told_the_query_was_refused_not_that_it_ran(
        drive_domain):
    """The tool_result is what the analyst repairs from. Told `executed:
    true` about a batch that ran nothing, the honest repair is the wrong
    one."""
    _outcome, provider, _record = _grain_run(drive_domain)
    results = [m for m in provider.sent[-1]["messages"]
               if m.get("role") == "user"]
    body = json.dumps([m.get("content") for m in results])
    assert '"executed": true' not in body.replace('"executed":true',
                                                  '"executed": true')
    assert xt.CHECK_GRAIN in body


# ---- what validation claims ---------------------------------------------

def test_the_validation_message_does_not_claim_the_declared_grain_was_proven(
        drive_domain, store_db):
    """"Query validated and bound: N step(s), X grain, Y units" claimed
    three things and had earned one. The grain and the units are the
    analyst's own declared strings, echoed and never checked against a
    result nobody had yet seen."""
    month_sql = ("SELECT sector, SUM(ead_sar_mn) AS ead_sar_mn "
                 "FROM corp_facility_quarter GROUP BY 1")
    _outcome, _provider, record = drive_domain(
        dom.CORPORATE, "What is exposure by sector?",
        [ScriptedResult(tool_calls=[tool_call("execute_analysis", {
            "intent": intent("DATA_ANALYSIS", "COCKPIT",
                             understood="exposure by sector"),
            "objective": "exposure by sector",
            "subquestions": ["exposure by sector"],
            "scope": {"reporting_months": [], "filters": {}},
            "metadata_receipt_ids": [], "fields_required": [],
            "expected_output_grain": "sector",
            "expected_units": "SAR million",
            "steps": [step(month_sql)],
            "repair_of_submission_id": ""}, "tu-1")])])

    validated = [e for e in _events(store_db, record.run_id)
                 if e.event_type == ev.TOOL_VALIDATED]
    assert validated, "the query was never announced as checked"
    said = validated[0].public_message or ""
    assert "executing nothing" in said, said
    assert "declared them and are not proven here" in said, said
    assert "Query validated and bound" not in said

    body = (store_db.get_detail(validated[0].detail_ref) or {}).get("body")
    assert body, "the operator record is missing"
    checks = body["checks_passed"]
    assert checks["join_grain"], "the grain check is unstated"
    # Two scanners key on the substring "authorization" -- the store's
    # redaction and the evidence-trace generator -- so a description that
    # spelled the check constant came back "[redacted]" or was refused
    # publication outright.
    assert "[redacted]" not in str(checks), (
        "a check description was mistaken for a credential")
    not_proven = " ".join(body["not_proven"])
    assert "grain and units" in not_proven
    assert "never checked" in not_proven


# ---- a known limitation, recorded rather than hidden --------------------

def test_the_check_reads_names_and_an_aggregate_and_nothing_finer(book):
    """Recorded, not fixed.

    `multiplication_risk` needs two relation names in the text and an
    aggregate over an additive measure. A subquery that repeats nothing but
    mentions both relations is refused. Moving the check earlier makes that
    louder rather than causing it, and the honest thing is to say so here
    rather than let the next reader discover it as a surprise.
    """
    service = book(dom.CORPORATE)
    repeats_nothing = (
        "SELECT SUM(b.total_debt_sar_mn) AS debt FROM corp_borrower_quarter b "
        "WHERE b.borrower_id IN (SELECT borrower_id FROM "
        "corp_facility_quarter)")
    with pytest.raises(Rejection):
        service.validate_batch(submission(step(repeats_nothing)))
