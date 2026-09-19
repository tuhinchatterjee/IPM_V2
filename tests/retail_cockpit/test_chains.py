"""Multi-turn analysis over Cockpit Data, driven through the real worker.

MODEL MOCK · REAL EVERYTHING ELSE.

The frozen suite's own chain tests cannot run here: they need the corporate
book, which this integration is forbidden to import. These are the same kind
of evidence over the book this Cockpit actually answers from -- the state
machine, the SQL validator, the grain checks, the repair loop, the
clarification path, the evidence binding and the arithmetic validation, all
the product's own, over the published projection.

What these prove: that the ARCHITECTURE behaves. What they do not prove, and
never claim to: answer quality. The analyst is scripted, so every one of
these sentences was written here rather than chosen by a model.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import ScriptedResult, final, intent, tool_call  # noqa: F401

from backend.cockpit_v4 import events as ev
from backend.cockpit_v4 import states as st

MONEY = "SAR million"
RIYALS = "SAR"
LATEST = "2026-08"

EAD_BY_PRODUCT = (
    "SELECT product, SUM(ead_sar_mn) AS ead_sar_mn "
    "FROM retail_account_month "
    f"WHERE reporting_month = '{LATEST}' "
    "GROUP BY product ORDER BY ead_sar_mn DESC")

BALANCE_BY_ACCOUNT = (
    "SELECT account_id, balance_sar "
    "FROM retail_account_month "
    f"WHERE reporting_month = '{LATEST}' AND balance_sar > 0 "
    "ORDER BY balance_sar DESC LIMIT 5")


def _analysis(sql: str, *, objective: str, grain: str, unit: str,
              fields: tuple[str, ...], call: str = "tu-exec"):
    return ScriptedResult(tool_calls=[tool_call("execute_analysis", {
        "intent": intent("DATA_ANALYSIS", "COCKPIT", understood=objective),
        "objective": objective,
        "subquestions": [objective],
        "scope": {"reporting_periods": [LATEST], "filters": {}},
        "metadata_receipt_ids": [],
        "fields_required": list(fields),
        "expected_output_grain": grain,
        "expected_units": unit,
        "steps": [{"step_id": "s1", "language": "sql", "code": sql,
                   "parameters": {}, "purpose": objective,
                   "input_artifact_ids": [], "depends_on_step_ids": []}],
        "repair_of_submission_id": ""}, call)])


def _finish(messages, *, dimension: str, measure: str, unit: str,
            claim: str = "top", charts=()):
    """Finalize from whatever the REAL executor actually returned."""
    import json

    body = json.loads(messages[-1]["content"][0]["content"])
    step = body["steps"][0]
    cell = step["preview"][0]
    evidence = {"artifact_id": step["artifact_id"],
                "row_key": f"{dimension}={cell[dimension]}",
                "column_id": measure}
    return ScriptedResult(tool_calls=[tool_call("finalize_response", final(
        intent=intent("DATA_ANALYSIS", "COCKPIT", understood="analysis"),
        narrative="The largest is {{claim." + claim + "}}.",
        coverage=[{"subquestion": "analysis", "status": "answered",
                   "evidence_refs": [evidence]}],
        numeric_claims=[{"claim_id": claim,
                         "decimal_value": repr(float(cell[measure])),
                         "unit": unit, "display_precision": 0,
                         "evidence": evidence}],
        tables=[{"title": "Result", "artifact_id": step["artifact_id"],
                 "columns": [dimension, measure]}],
        charts=[{"kind": kind, "title": f"{measure} by {dimension}",
                 "artifact_id": step["artifact_id"], "x_column": dimension,
                 "y_columns": [measure], "unit": unit} for kind in charts],
    ))])


# ---- the analysis actually runs, on the real book ----------------------

def test_a_real_analysis_runs_and_binds_its_claim_to_evidence(
        drive_chain, chain_store):
    outcome, provider, record = drive_chain(
        "Total exposure at default by product this month",
        [_analysis(EAD_BY_PRODUCT, objective="EAD by product",
                   grain="product", unit=MONEY,
                   fields=("retail_account_month.ead_sar_mn",)),
         lambda messages: _finish(messages, dimension="product",
                                  measure="ead_sar_mn", unit=MONEY,
                                  charts=("bar", "donut"))])

    assert outcome.state == st.COMPLETED, outcome.message
    assert len(provider.sent) == 2, "one execution, one finalization"

    types = [e.event_type for e in chain_store.events_since(record.run_id)]
    assert ev.ANSWER_READY in types
    assert "tool.completed" in types

    body = chain_store.get_run(record.run_id).final_response
    assert body["disposition"] == "answer"
    assert body["executed"] is True
    claim = body["numeric_claims"][0]
    assert claim["unit"] == MONEY
    # The figure is the REAL one: the SQL ran against the published book.
    assert Decimal(claim["decimal_value"]) > 0
    assert claim["evidence"]["artifact_id"]


def test_the_charts_the_analyst_asked_for_are_the_charts_carried(
        drive_chain, chain_store):
    """Two forms, one answer. Not every answer reduced to one bar chart."""
    _, _, record = drive_chain(
        "Total exposure at default by product this month",
        [_analysis(EAD_BY_PRODUCT, objective="EAD by product",
                   grain="product", unit=MONEY,
                   fields=("retail_account_month.ead_sar_mn",)),
         lambda m: _finish(m, dimension="product", measure="ead_sar_mn",
                           unit=MONEY, charts=("bar", "line", "donut"))])
    body = chain_store.get_run(record.run_id).final_response
    assert [c["kind"] for c in body["charts"]] == ["bar", "line", "donut"]


# ---- the money rule, end to end ---------------------------------------

def test_a_facility_level_answer_in_riyals_does_not_render_as_zero(
        drive_chain, chain_store):
    """The reason the riyal columns exist, proved through a real answer."""
    from backend.cockpit_v4 import display as disp

    outcome, _, record = drive_chain(
        "Which facilities carry the largest balances this month?",
        [_analysis(BALANCE_BY_ACCOUNT, objective="Largest balances",
                   grain="account_id", unit=RIYALS,
                   fields=("retail_account_month.balance_sar",)),
         lambda m: _finish(m, dimension="account_id", measure="balance_sar",
                           unit=RIYALS, claim="largest")])
    assert outcome.state == st.COMPLETED, outcome.message
    body = chain_store.get_run(record.run_id).final_response
    claim = body["numeric_claims"][0]
    assert claim["unit"] == RIYALS
    shown = disp.format_value(Decimal(claim["decimal_value"]), claim["unit"])
    assert shown.startswith("SAR ")
    assert "million" not in shown
    assert any(ch in "123456789" for ch in shown), shown


# ---- the safety rails are the engine's, and they hold ------------------

def test_sql_against_a_relation_this_book_does_not_have_is_refused(
        drive_chain, chain_store):
    """Cross-book SQL does not reach the database."""
    outcome, provider, record = drive_chain(
        "What is corporate exposure by sector?",
        [_analysis("SELECT sector, SUM(ead_sar_mn) FROM corp_facility_quarter"
                   " GROUP BY sector",
                   objective="corporate EAD", grain="sector", unit=MONEY,
                   fields=("corp_facility_quarter.ead_sar_mn",)),
         ScriptedResult(tool_calls=[tool_call("finalize_response", final(
             intent=intent("DATA_ANALYSIS", "COCKPIT"),
             disposition="cannot_answer",
             narrative="That book is not open in this thread."))])])

    types = [e.event_type for e in chain_store.events_since(record.run_id)]
    assert "tool.failed" in types or "tool.validated" not in types, (
        "a relation this release does not publish must not execute")
    assert outcome.state in (st.COMPLETED, st.FAILED)


def test_a_broken_query_is_repaired_rather_than_published(
        drive_chain, chain_store):
    """The repair loop: the analyst is told, and gets another turn."""
    broken = ("SELECT product, SUM(ead_sar_mn) AS ead_sar_mn "
              "FROM retail_account_month "
              f"WHERE reporting_month = '{LATEST}' "
              "GROUP BY produkt")
    outcome, provider, record = drive_chain(
        "Total exposure at default by product this month",
        [_analysis(broken, objective="EAD by product", grain="product",
                   unit=MONEY, fields=("retail_account_month.ead_sar_mn",)),
         _analysis(EAD_BY_PRODUCT, objective="EAD by product",
                   grain="product", unit=MONEY,
                   fields=("retail_account_month.ead_sar_mn",),
                   call="tu-repair"),
         lambda m: _finish(m, dimension="product", measure="ead_sar_mn",
                           unit=MONEY)])

    assert len(provider.sent) >= 3, (
        "a failed step must come back to the analyst, not to the reader")
    types = [e.event_type for e in chain_store.events_since(record.run_id)]
    assert "tool.failed" in types
    assert outcome.state == st.COMPLETED, outcome.message
    body = chain_store.get_run(record.run_id).final_response
    assert body["executed"] is True


AMBIGUITY = "exposure could mean EAD, the credit limit or the balance"
OPTIONS = ["Exposure at default", "Credit limit", "Outstanding balance"]


def test_a_blocking_ambiguity_takes_execution_off_the_table(drive_chain,
                                                            chain_store):
    """A declared ambiguity stops the query, and the reader is asked.

    Two turns, not one: the analyst submits with the ambiguity declared, the
    SERVER takes execution away, and the only tool left on the next turn is
    `finalize_response`. That second part is the one that matters -- the
    analyst is not trusted to decline to execute, it is prevented.
    """
    submitted = ScriptedResult(tool_calls=[tool_call("execute_analysis", {
        "intent": intent("DATA_ANALYSIS", "COCKPIT",
                         understood="exposure by product",
                         ambiguities=[AMBIGUITY]),
        "objective": "exposure by product",
        "subquestions": ["which exposure"],
        "scope": {"reporting_periods": [LATEST], "filters": {}},
        "metadata_receipt_ids": [],
        "fields_required": ["retail_account_month.ead_sar_mn"],
        "expected_output_grain": "product", "expected_units": MONEY,
        "steps": [{"step_id": "s1", "language": "sql",
                   "code": EAD_BY_PRODUCT, "parameters": {},
                   "purpose": "exposure", "input_artifact_ids": [],
                   "depends_on_step_ids": []}],
        "repair_of_submission_id": ""})])
    asks = ScriptedResult(tool_calls=[tool_call("finalize_response", final(
        intent=intent("DATA_ANALYSIS", "COCKPIT",
                      understood="exposure by product"),
        disposition="clarification",
        narrative="Exposure is recorded three ways in this book.",
        clarification_question="Which exposure did you mean?",
        clarification_options=OPTIONS))])

    outcome, provider, record = drive_chain(
        "Show me exposure by product", [submitted, asks])

    assert outcome.state == st.WAITING_FOR_USER, outcome.message
    published = outcome.response or {}
    assert published["disposition"] == "clarification"
    assert published["clarification_question"]
    assert published["clarification_options"] == OPTIONS

    # The gate: the last turn was offered one tool, and it was not SQL.
    offered = [x.get("name") for x in (provider.sent[-1].get("tools") or [])]
    assert offered == ["finalize_response"], offered

    types = [e.event_type for e in chain_store.events_since(record.run_id)]
    assert "tool.completed" not in types, (
        "a question that cannot be answered must not have been run")


# ---- a conversation, not a question ------------------------------------

def test_a_follow_up_carries_the_thread_and_keeps_its_own_evidence(
        drive_chain, chain_store):
    """Two turns in one thread, each with its own run and its own artifact."""
    _, _, first = drive_chain(
        "Total exposure at default by product this month",
        [_analysis(EAD_BY_PRODUCT, objective="EAD by product",
                   grain="product", unit=MONEY,
                   fields=("retail_account_month.ead_sar_mn",)),
         lambda m: _finish(m, dimension="product", measure="ead_sar_mn",
                           unit=MONEY)])

    outcome, provider, second = drive_chain(
        "And the recognised ECL for the same products?",
        [_analysis("SELECT product, SUM(ecl_sar_mn) AS ecl_sar_mn "
                   "FROM retail_account_month "
                   f"WHERE reporting_month = '{LATEST}' GROUP BY product",
                   objective="ECL by product", grain="product", unit=MONEY,
                   fields=("retail_account_month.ecl_sar_mn",)),
         lambda m: _finish(m, dimension="product", measure="ecl_sar_mn",
                           unit=MONEY, claim="ecl")],
        thread_id=first.thread_id)

    assert outcome.state == st.COMPLETED, outcome.message
    assert second.thread_id == first.thread_id
    assert second.run_id != first.run_id

    # The second turn was given the first one, and it is the ORIGINAL
    # wording that travels -- not a summary of it.
    sent = provider.first_input_text()
    assert "Total exposure at default by product this month" in sent

    bodies = [chain_store.get_run(r.run_id).final_response
              for r in (first, second)]
    artifacts = {b["numeric_claims"][0]["evidence"]["artifact_id"]
                 for b in bodies}
    assert len(artifacts) == 2, "each turn stands on its own evidence"
