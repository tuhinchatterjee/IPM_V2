"""MODEL MOCK · REAL DATABASE/RUNNER · INDEPENDENT ORACLE.

Two books, executed. The round this replaces refused Retail questions rather
than letting one run against corporate relations; these are the regressions
that make the refusal unnecessary.

What is scripted and what is not
--------------------------------
The model is scripted, so nothing here claims anything about answer quality.
Everything else is real: the run is persisted with its domain and release, the
worker resolves the book from THAT record, a real DuckDB session is
materialized from that book's own parquet, the submitted SQL runs in it, and
every published figure is checked against a pandas oracle that never touches
the catalogue, the session or the product's SQL.

The isolation cases are the point of the file. A corporate run that names a
retail relation must be refused by name; a retail run must never see a
corporate relation; and the two runs must not be able to reach each other's
numbers through a cache, a session or a release header.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import domain_oracles as oracle
import pytest
from conftest import ScriptedResult, final, intent, tool_call

from backend.cockpit_v4 import analytical_runtime as arun
from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4 import states as st

TOLERANCE = 1e-6


@pytest.fixture(scope="module", autouse=True)
def _both_books_published():
    for domain_id in dom.DOMAIN_IDS:
        if not lake.exists(dom.DEFAULT_RELEASES[domain_id]):
            pytest.skip("run scripts/cockpit_v4/seed_domains.py")
    arun.reset()
    yield
    arun.reset()


# ---- driving one run in one book ---------------------------------------

def make_domain_run(store_db, domain_id: str, question: str, *,
                    tenant: str = lake.DEFAULT_TENANT,
                    principal: str = "u1", mode: str = "standard"):
    """A run persisted exactly as the API persists one, book and all."""
    from backend.cockpit_v4 import domain_resolver as resolver

    scope = resolver.scope_for(domain_id, tenant_id=tenant)
    thread_id = store_db.create_thread(
        tenant_id=tenant, principal_id=principal, domain_id=scope.domain_id,
        release_id=scope.release_id,
        release_fingerprint=scope.release_fingerprint)
    record, _ = store_db.accept_run(
        thread_id=thread_id, tenant_id=tenant, principal_id=principal,
        question=question, mode=mode, release_id=scope.release_id,
        domain_id=scope.domain_id,
        release_fingerprint=scope.release_fingerprint,
        ui_filters={}, idempotency_key="", body_digest="",
        startup_sha="testsha", deadline_at="")
    return record


@pytest.fixture
def drive_domain(store_db, runtime):
    """Run one scripted conversation, in one book, through the real worker."""
    from conftest import ScriptedProvider
    from backend.cockpit_v4.worker import Worker

    def _drive(domain_id: str, question: str, script, *,
               tenant: str = lake.DEFAULT_TENANT, record=None):
        provider = ScriptedProvider(script)
        runtime.provider = provider
        record = record or make_domain_run(store_db, domain_id, question,
                                           tenant=tenant)
        outcome = Worker(store=store_db, runtime=runtime).execute(record)
        return outcome, provider, record
    return _drive


def execute_call(sql: str, *, purpose: str, grain: str, units: str,
                 subquestions, fields, month: str, call_id="tu-x",
                 step_id="s1"):
    return tool_call("execute_analysis", {
        "intent": intent("DATA_ANALYSIS", "COCKPIT", understood=purpose,
                         rationale="direct read"),
        "objective": purpose, "subquestions": list(subquestions),
        "scope": {"reporting_months": [month], "filters": {}},
        "metadata_receipt_ids": [], "fields_required": list(fields),
        "expected_output_grain": grain, "expected_units": units,
        "steps": [{"step_id": step_id, "language": "sql", "code": sql,
                   "parameters": {}, "purpose": purpose,
                   "input_artifact_ids": [], "depends_on_step_ids": []}],
        "repair_of_submission_id": ""}, call_id)


def answer_from(messages, *, narrative: str, subquestion: str,
                seen: list | None = None):
    """An answer built from whatever the execution actually returned."""
    body = json.loads(messages[-1]["content"][0]["content"])
    step = body["steps"][0]
    artifact = step["artifact_id"]
    if seen is not None:
        seen.append(artifact)
    row = step["preview"][0]
    column = next(c for c in step["columns"]
                  if isinstance(row[c], (int, float)))
    return ScriptedResult(tool_calls=[tool_call(
        "finalize_response",
        final(intent=intent("DATA_ANALYSIS", "COCKPIT"),
              narrative=narrative + " The figure is {{claim.v}}.",
              coverage=[{"subquestion": subquestion, "status": "answered",
                         "evidence_refs": [{"artifact_id": artifact,
                                            "row_key": "r0",
                                            "column_id": column}]}],
              numeric_claims=[{
                  "claim_id": "v", "decimal_value": str(row[column]),
                  "unit": "amount", "display_precision": 2,
                  "evidence": {"artifact_id": artifact, "row_key": "r0",
                               "column_id": column}}],
              tables=[{"title": subquestion, "artifact_id": artifact,
                       "columns": list(row)}]))])


def rows_of(store_db, record, artifact_id: str):
    """Every row of the run's result artifact, read back from the store.

    Read from the artifact rather than the preview, so the check is against
    what was stored for the reader and not against a truncated echo of it.
    """
    run = store_db.get_run(record.run_id)
    assert run.state == st.COMPLETED, run.error_code
    stored = store_db.get_artifact(artifact_id, tenant_id=record.tenant_id)
    assert stored is not None, "the result artifact was not readable"
    return stored


def run_case(drive_domain, store_db, *, domain_id: str, question: str,
             sql: str, fields, purpose: str, grain: str, units: str,
             month: str):
    seen: list[str] = []
    outcome, provider, record = drive_domain(domain_id, question, [
        ScriptedResult(tool_calls=[execute_call(
            sql, purpose=purpose, grain=grain, units=units,
            subquestions=[purpose], fields=fields, month=month)]),
        lambda m: answer_from(m, narrative=purpose, subquestion=purpose,
                              seen=seen)])
    assert outcome.state == st.COMPLETED, outcome.message
    assert outcome.response["executed"] is True
    return Case(outcome=outcome, provider=provider, record=record,
                artifact_id=seen[0], rows=rows_of(store_db, record, seen[0]))


@dataclass
class Case:
    """What one executed case produced, for the assertions that follow."""

    outcome: Any
    provider: Any
    record: Any
    artifact_id: str
    rows: dict


def keyed(payload, key: str, value: str) -> dict[str, float]:
    return {str(r[key]): float(r[value]) for r in payload["rows"]}


# ---- C01-C05: the Corporate book ---------------------------------------

def test_c01_corporate_ead_by_sector(drive_domain, store_db):
    month = oracle.latest_month(dom.CORPORATE)
    case = run_case(
        drive_domain, store_db, domain_id=dom.CORPORATE,
        question="What is exposure at default by sector this month?",
        sql=f"SELECT sector, SUM(ead_sar_mn) AS ead_sar_mn "
            f"FROM corp_facility_month WHERE reporting_month = '{month}' "
            f"GROUP BY sector ORDER BY ead_sar_mn DESC",
        fields=["corp_facility_month.ead_sar_mn",
                "corp_facility_month.sector"],
        purpose="EAD by sector", grain="sector", units="SAR million",
        month=month)
    produced = keyed(case.rows, "sector", "ead_sar_mn")
    expected = oracle.corp_ead_by_sector(month)
    assert set(produced) == set(expected)
    for sector, value in expected.items():
        assert produced[sector] == pytest.approx(value, abs=TOLERANCE)


def test_c02_corporate_stage_two_share_by_sector(drive_domain, store_db):
    month = oracle.latest_month(dom.CORPORATE)
    case = run_case(
        drive_domain, store_db, domain_id=dom.CORPORATE,
        question="What share of exposure is in stage 2 or worse, by sector?",
        sql=f"SELECT sector, SUM(CASE WHEN stage >= 2 THEN ead_sar_mn "
            f"ELSE 0 END) / NULLIF(SUM(ead_sar_mn), 0) AS stage2_share "
            f"FROM corp_facility_month WHERE reporting_month = '{month}' "
            f"GROUP BY sector ORDER BY stage2_share DESC",
        fields=["corp_facility_month.ead_sar_mn",
                "corp_facility_month.stage", "corp_facility_month.sector"],
        purpose="Stage 2+ share of EAD by sector", grain="sector",
        units="percent", month=month)
    produced = keyed(case.rows, "sector", "stage2_share")
    for sector, value in oracle.corp_stage2_share_by_sector(month).items():
        assert produced[sector] == pytest.approx(value, abs=TOLERANCE)


def test_c03_corporate_ecl_by_facility_type(drive_domain, store_db):
    month = oracle.latest_month(dom.CORPORATE)
    case = run_case(
        drive_domain, store_db, domain_id=dom.CORPORATE,
        question="What is recognised ECL by facility type?",
        sql=f"SELECT facility_type, SUM(ecl_sar_mn) AS ecl_sar_mn "
            f"FROM corp_facility_month WHERE reporting_month = '{month}' "
            f"GROUP BY facility_type ORDER BY ecl_sar_mn DESC",
        fields=["corp_facility_month.ecl_sar_mn",
                "corp_facility_month.facility_type"],
        purpose="ECL by facility type", grain="facility type",
        units="SAR million", month=month)
    produced = keyed(case.rows, "facility_type",
                     "ecl_sar_mn")
    for key, value in oracle.corp_ecl_by_facility_type(month).items():
        assert produced[key] == pytest.approx(value, abs=TOLERANCE)


def test_c04_corporate_month_on_month_exposure_movement(drive_domain,
                                                        store_db):
    latest = oracle.latest_month(dom.CORPORATE)
    previous = oracle.previous_month(dom.CORPORATE)
    case = run_case(
        drive_domain, store_db, domain_id=dom.CORPORATE,
        question="How did total exposure move over the latest month?",
        sql=f"SELECT SUM(CASE WHEN reporting_month = '{latest}' "
            f"THEN ead_sar_mn ELSE 0 END) "
            f"- SUM(CASE WHEN reporting_month = '{previous}' "
            f"THEN ead_sar_mn ELSE 0 END) AS ead_movement_sar_mn "
            f"FROM corp_facility_month "
            f"WHERE reporting_month IN ('{latest}', '{previous}')",
        fields=["corp_facility_month.ead_sar_mn"],
        purpose="EAD movement over the latest month", grain="portfolio",
        units="SAR million", month=latest)
    payload = case.rows
    produced = float(payload["rows"][0]["ead_movement_sar_mn"])
    assert produced == pytest.approx(
        oracle.corp_ead_movement(latest, previous), abs=1e-4)


def test_c05_corporate_exposure_by_borrower_does_not_multiply(drive_domain,
                                                              store_db):
    """The join case. EAD is summed at facility grain, then named."""
    month = oracle.latest_month(dom.CORPORATE)
    case = run_case(
        drive_domain, store_db, domain_id=dom.CORPORATE,
        question="Which borrowers hold the most exposure?",
        sql=f"WITH by_borrower AS ("
            f"  SELECT borrower_id, SUM(ead_sar_mn) AS ead_sar_mn"
            f"  FROM corp_facility_month WHERE reporting_month = '{month}'"
            f"  GROUP BY borrower_id) "
            f"SELECT b.borrower_name, t.ead_sar_mn FROM by_borrower t "
            f"JOIN corp_borrower_month b ON b.borrower_id = t.borrower_id "
            f"AND b.reporting_month = '{month}' "
            f"ORDER BY t.ead_sar_mn DESC",
        fields=["corp_facility_month.ead_sar_mn",
                "corp_borrower_month.borrower_name"],
        purpose="EAD by borrower", grain="borrower", units="SAR million",
        month=month)
    produced = keyed(case.rows, "borrower_name",
                     "ead_sar_mn")
    expected = oracle.corp_ead_by_borrower(month)
    assert set(produced) == set(expected)
    for name, value in expected.items():
        assert produced[name] == pytest.approx(value, abs=TOLERANCE)


# ---- R01-R06: the Retail book ------------------------------------------

def test_r01_retail_ead_by_product(drive_domain, store_db):
    month = oracle.latest_month(dom.RETAIL)
    case = run_case(
        drive_domain, store_db, domain_id=dom.RETAIL,
        question="What is exposure at default by product this month?",
        sql=f"SELECT product, SUM(ead_sar_mn) AS ead_sar_mn "
            f"FROM retail_account_month WHERE reporting_month = '{month}' "
            f"GROUP BY product ORDER BY ead_sar_mn DESC",
        fields=["retail_account_month.ead_sar_mn",
                "retail_account_month.product"],
        purpose="EAD by product", grain="product", units="SAR million",
        month=month)
    produced = keyed(case.rows, "product", "ead_sar_mn")
    expected = oracle.retail_ead_by_product(month)
    assert set(produced) == set(expected)
    for product, value in expected.items():
        assert produced[product] == pytest.approx(value, abs=1e-4)


def test_r02_retail_stage_two_share_by_product(drive_domain, store_db):
    month = oracle.latest_month(dom.RETAIL)
    case = run_case(
        drive_domain, store_db, domain_id=dom.RETAIL,
        question="What share of retail exposure is in stage 2 or worse?",
        sql=f"SELECT product, SUM(CASE WHEN stage >= 2 THEN ead_sar_mn "
            f"ELSE 0 END) / NULLIF(SUM(ead_sar_mn), 0) AS stage2_share "
            f"FROM retail_account_month WHERE reporting_month = '{month}' "
            f"GROUP BY product ORDER BY stage2_share DESC",
        fields=["retail_account_month.ead_sar_mn",
                "retail_account_month.stage",
                "retail_account_month.product"],
        purpose="Stage 2+ share of EAD by product", grain="product",
        units="percent", month=month)
    produced = keyed(case.rows, "product", "stage2_share")
    for product, value in oracle.retail_stage2_share_by_product(month).items():
        assert produced[product] == pytest.approx(value, abs=TOLERANCE)


def test_r03_retail_ecl_by_score_band(drive_domain, store_db):
    month = oracle.latest_month(dom.RETAIL)
    case = run_case(
        drive_domain, store_db, domain_id=dom.RETAIL,
        question="What is ECL by behaviour score band?",
        sql=f"SELECT score_band, SUM(ecl_sar_mn) AS ecl_sar_mn "
            f"FROM retail_account_month WHERE reporting_month = '{month}' "
            f"GROUP BY score_band ORDER BY ecl_sar_mn DESC",
        fields=["retail_account_month.ecl_sar_mn",
                "retail_account_month.score_band"],
        purpose="ECL by score band", grain="score band",
        units="SAR million", month=month)
    produced = keyed(case.rows, "score_band", "ecl_sar_mn")
    for band, value in oracle.retail_ecl_by_score_band(month).items():
        assert produced[band] == pytest.approx(value, abs=1e-4)


def test_r04_retail_delinquent_share_by_product(drive_domain, store_db):
    month = oracle.latest_month(dom.RETAIL)
    case = run_case(
        drive_domain, store_db, domain_id=dom.RETAIL,
        question="How much retail exposure is past due, by product?",
        sql=f"SELECT product, SUM(CASE WHEN dpd_days > 0 THEN ead_sar_mn "
            f"ELSE 0 END) / NULLIF(SUM(ead_sar_mn), 0) AS past_due_share "
            f"FROM retail_account_month WHERE reporting_month = '{month}' "
            f"GROUP BY product ORDER BY past_due_share DESC",
        fields=["retail_account_month.ead_sar_mn",
                "retail_account_month.dpd_days",
                "retail_account_month.product"],
        purpose="Past-due share of EAD by product", grain="product",
        units="percent", month=month)
    produced = keyed(case.rows, "product", "past_due_share")
    for product, value in \
            oracle.retail_delinquent_share_by_product(month).items():
        assert produced[product] == pytest.approx(value, abs=TOLERANCE)


def test_r05_retail_write_offs_by_product(drive_domain, store_db):
    month = oracle.latest_month(dom.RETAIL)
    case = run_case(
        drive_domain, store_db, domain_id=dom.RETAIL,
        question="What was written off this month, by product?",
        sql=f"SELECT product, SUM(write_off_sar_mn) AS write_off_sar_mn "
            f"FROM retail_account_month WHERE reporting_month = '{month}' "
            f"GROUP BY product ORDER BY write_off_sar_mn DESC",
        fields=["retail_account_month.write_off_sar_mn",
                "retail_account_month.product"],
        purpose="Write-offs by product", grain="product",
        units="SAR million", month=month)
    produced = keyed(case.rows, "product",
                     "write_off_sar_mn")
    for product, value in oracle.retail_write_off_by_product(month).items():
        assert produced[product] == pytest.approx(value, abs=1e-4)


def test_r06_retail_exposure_by_origination_vintage(drive_domain, store_db):
    month = oracle.latest_month(dom.RETAIL)
    case = run_case(
        drive_domain, store_db, domain_id=dom.RETAIL,
        question="How is exposure spread across origination vintages?",
        sql=f"SELECT CAST(vintage_year AS VARCHAR) AS vintage_year, "
            f"SUM(ead_sar_mn) AS ead_sar_mn "
            f"FROM retail_account_month WHERE reporting_month = '{month}' "
            f"GROUP BY vintage_year ORDER BY vintage_year",
        fields=["retail_account_month.ead_sar_mn",
                "retail_account_month.vintage_year"],
        purpose="EAD by origination vintage", grain="vintage year",
        units="SAR million", month=month)
    produced = keyed(case.rows, "vintage_year", "ead_sar_mn")
    expected = oracle.retail_ead_by_vintage(month)
    assert set(produced) == set(expected)
    for vintage, value in expected.items():
        assert produced[vintage] == pytest.approx(value, abs=1e-4)


# ---- the isolation cases -----------------------------------------------

CROSS = {
    dom.CORPORATE: ("retail_account_month", "retail"),
    dom.RETAIL: ("corp_facility_month", "corporate"),
}


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_a_run_naming_the_other_books_relation_is_refused_by_name(
        drive_domain, store_db, domain_id):
    """The defect the whole domain model exists to prevent.

    Not "returned no rows" and not "unknown table": refused, with the owning
    book named, before anything ran.
    """
    relation, owner = CROSS[domain_id]
    month = oracle.latest_month(domain_id)
    outcome, _provider, record = drive_domain(
        domain_id, "What is exposure in the other book?", [
            ScriptedResult(tool_calls=[execute_call(
                f"SELECT SUM(ead_sar_mn) AS ead_sar_mn FROM {relation} "
                f"WHERE reporting_month = '{month}'",
                purpose="Exposure", grain="portfolio", units="SAR million",
                subquestions=["Exposure"], fields=[f"{relation}.ead_sar_mn"],
                month=month)]),
            ScriptedResult(tool_calls=[tool_call(
                "finalize_response",
                final(intent=intent("DATA_ANALYSIS", "COCKPIT"),
                      disposition="unsupported",
                      narrative=("That relation belongs to the other book "
                                 "and was not read.")),
                "tu-2")])])

    assert outcome.state in (st.UNSUPPORTED, st.COMPLETED, st.PARTIAL)
    assert not outcome.response.get("executed"), (
        "a query naming the other book's relation must not report as "
        "executed")
    events = store_db.events_since(record.run_id, 0)
    text = json.dumps([e.to_dict() if hasattr(e, "to_dict") else e
                       for e in events], default=str)
    assert dom.LABELS[owner] in text, (
        "the refusal must name the book the relation belongs to, and this "
        f"run said: {text[-2000:]}")
    assert relation not in json.dumps(
        store_db.get_run(record.run_id).budget, default=str)


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_a_session_holds_one_books_relations_and_no_others(domain_id):
    book = arun.for_domain(domain_id)
    other = next(d for d in dom.DOMAIN_IDS if d != domain_id)
    theirs = set(arun.for_domain(other).catalog.relations())
    mine = set(book.session.relations)
    assert mine == set(book.catalog.relations())
    assert not (mine & theirs)


@pytest.mark.parametrize("domain_id", list(dom.DOMAIN_IDS))
def test_the_starting_context_names_only_this_books_relations(drive_domain,
                                                              domain_id):
    other = next(d for d in dom.DOMAIN_IDS if d != domain_id)
    theirs = arun.for_domain(other).catalog.relations()
    _outcome, provider, _record = drive_domain(
        domain_id, "What can you tell me about this portfolio?", [
            ScriptedResult(tool_calls=[tool_call(
                "finalize_response",
                final(intent=intent(), disposition="answer",
                      narrative="hello"))])])
    sent = provider.first_input_text()
    for relation in arun.for_domain(domain_id).catalog.relations():
        assert relation in sent, f"{relation} is missing from the packet"
    for relation in theirs:
        assert relation not in sent, (
            f"{relation} belongs to the other book and reached the packet")
    assert dom.LABELS[domain_id] in sent


def test_the_packet_says_which_book_and_which_fingerprint(drive_domain):
    _o, provider, _r = drive_domain(dom.RETAIL, "What is this?", [
        ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent(), disposition="answer", narrative="hi"))])])
    sent = provider.first_input_text()
    book = arun.for_domain(dom.RETAIL)
    assert book.release_id in sent
    assert book.release_fingerprint[:16] in sent
    assert "reporting_months" in sent, (
        "a monthly book must not describe its periods as quarters")


# ---- cache contamination (five orderings) -------------------------------

ORDERINGS = [
    (dom.CORPORATE, dom.RETAIL),
    (dom.RETAIL, dom.CORPORATE),
    (dom.CORPORATE, dom.RETAIL, dom.CORPORATE),
    (dom.RETAIL, dom.CORPORATE, dom.RETAIL),
    (dom.CORPORATE, dom.CORPORATE, dom.RETAIL, dom.RETAIL),
]


@pytest.mark.parametrize("ordering", ORDERINGS,
                         ids=["cr", "rc", "crc", "rcr", "ccrr"])
def test_no_ordering_lets_one_book_be_served_from_the_others_cache(
        drive_domain, store_db, ordering):
    """Whichever book was opened first must not decide what the next reads."""
    arun.reset()
    for domain_id in ordering:
        month = oracle.latest_month(domain_id)
        if domain_id == dom.CORPORATE:
            relation, dimension = "corp_facility_month", "sector"
            expected = oracle.corp_ead_by_sector(month)
        else:
            relation, dimension = "retail_account_month", "product"
            expected = oracle.retail_ead_by_product(month)
        case = run_case(
            drive_domain, store_db, domain_id=domain_id,
            question=f"EAD by {dimension}?",
            sql=f"SELECT {dimension}, SUM(ead_sar_mn) AS ead_sar_mn "
                f"FROM {relation} WHERE reporting_month = '{month}' "
                f"GROUP BY {dimension}",
            fields=[f"{relation}.ead_sar_mn", f"{relation}.{dimension}"],
            purpose=f"EAD by {dimension}", grain=dimension,
            units="SAR million", month=month)
        produced = keyed(case.rows, dimension, "ead_sar_mn")
        assert set(produced) == set(expected), (
            f"{domain_id} returned the wrong book's segments in ordering "
            f"{ordering}")
        for key, value in expected.items():
            assert produced[key] == pytest.approx(value, abs=1e-4)
        assert case.rows["release_id"] == dom.DEFAULT_RELEASES[domain_id]
        assert case.rows["scope"]["domain_id"] == domain_id


# ---- the run's own record decides --------------------------------------

def test_a_rebuilt_release_refuses_the_run_rather_than_answering_it(
        drive_domain, store_db):
    """The fingerprint is the control, not the release name."""
    record = make_domain_run(store_db, dom.RETAIL, "What is EAD?")
    stale = record.__class__(**{**record.__dict__,
                                "release_fingerprint": "0" * 64})
    outcome, provider, _r = drive_domain(
        dom.RETAIL, "What is EAD?", [], record=stale)
    assert outcome.state == st.FAILED
    assert outcome.error_code == st.DATA_UNAVAILABLE
    assert "rebuilt" in outcome.message
    assert provider.sent == [], "a refused book must cost no model call"


def test_a_label_that_disagrees_with_the_release_is_refused(drive_domain,
                                                            store_db):
    record = make_domain_run(store_db, dom.RETAIL, "What is EAD?")
    mislabelled = record.__class__(
        **{**record.__dict__, "domain_id": dom.CORPORATE})
    outcome, provider, _r = drive_domain(
        dom.RETAIL, "What is EAD?", [], record=mislabelled)
    assert outcome.state == st.FAILED
    assert outcome.error_code == st.DATA_UNAVAILABLE
    assert "disagree" in outcome.message
    assert provider.sent == []


def test_a_follow_up_reads_the_same_book_as_the_question_before_it(
        drive_domain, store_db):
    """Two runs, one thread. The second must not re-derive its book."""
    first = make_domain_run(store_db, dom.RETAIL, "What is EAD by product?")
    month = oracle.latest_month(dom.RETAIL)
    sql = (f"SELECT product, SUM(ead_sar_mn) AS ead_sar_mn "
           f"FROM retail_account_month WHERE reporting_month = '{month}' "
           f"GROUP BY product")
    for _ in range(2):
        record, _created = store_db.accept_run(
            thread_id=first.thread_id, tenant_id=first.tenant_id,
            principal_id=first.principal_id, question="And now?",
            mode="standard", release_id=first.release_id,
            domain_id=first.domain_id,
            release_fingerprint=first.release_fingerprint,
            ui_filters={}, idempotency_key="", body_digest="",
            startup_sha="testsha", deadline_at="")
        case = run_case(
            drive_domain, store_db, domain_id=dom.RETAIL,
            question="And now?", sql=sql,
            fields=["retail_account_month.ead_sar_mn",
                    "retail_account_month.product"],
            purpose="EAD by product", grain="product", units="SAR million",
            month=month)
        assert case.rows["scope"]["domain_id"] == dom.RETAIL
        assert case.rows["release_id"] == dom.DEFAULT_RELEASES[dom.RETAIL]
        assert set(keyed(case.rows, "product", "ead_sar_mn")) == set(
            oracle.retail_ead_by_product(month))
        del record
