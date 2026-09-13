"""MODEL MOCK · REAL DATABASE/RUNNER · REPRODUCTION.

The analyst names the number. CreditProbe writes it.

The defect this exists for
--------------------------
A live run computed exposure at default by sector, correctly, and had its
answer refused:

    asserted  40599.17
    canonical 40599.1736630513815

Both numbers are right. `40,599.17` is how a credit officer writes that
figure and `40599.1736630513815` is not, and the only reason the two had to
agree at all is that the contract made the ANALYST responsible for the exact
decimal string on the screen. That responsibility bought nothing: the server
had already computed the value, already knew its unit, and already knew how
that kind of figure is written.

So `decimal_value` is now optional and normally absent. The analyst names one
result cell or the arithmetic over real cells; the server computes, checks and
formats. What a run can no longer do is spend a model call removing decimal
places from a figure that was never wrong.

What has NOT changed is validation. Wrong arithmetic still fails, a claim
pointing at a cell that does not exist still fails, and an analyst that does
send a value is still held to it.
"""

from __future__ import annotations

import json
from decimal import Decimal

import oracles
import pytest
from conftest import ScriptedResult, final, intent, tool_call
from test_mandatory_analytical_cases import EAD_FIELDS, EAD_SQL
from test_vertical_slice import _execute_call

from backend.cockpit_v4 import display as disp
from backend.cockpit_v4 import states as st

QUESTION = "What is total exposure at default by sector in the latest quarter?"


def _result(messages) -> dict:
    """The executed result, wherever it sits in the thread.

    After a rejected answer the LAST message is the rejection, and the
    successful result is behind it. Reading only the last message would make
    every rejection test fail as a provider fault instead of as the answer
    fault it is testing.
    """
    from test_orchestration_recovery import _execution_result

    return _execution_result(messages)["steps"][0]


def _run(drive, release_id, answer, *, repeats: int = 1):
    """One action, then the answer. `repeats` for an answer that is refused.

    A rejected answer earns one correction, so a test about REJECTION has to
    script the correction too -- otherwise the run stops because the script
    ran out, and the reported code is about the provider rather than about
    the answer.
    """
    quarter = oracles.latest_quarter(release_id)
    return drive(QUESTION, [
        ScriptedResult(tool_calls=[_execute_call(
            EAD_SQL, purpose="Reported EAD by sector", grain="sector",
            units="SAR million", subquestions=["EAD by sector"],
            fields=EAD_FIELDS, quarter=quarter)]),
        *([answer] * repeats)])


def _total_claim(messages, **extra) -> dict:
    """A total across every real row. No number typed anywhere."""
    step = _result(messages)
    column = next(c for c in step["columns"] if c != "sector_name")
    claim = {"claim_id": "total_ead", "unit": "SAR million",
             "derivation": {"operation": "sum", "operands": [
                 {"artifact_id": step["artifact_id"], "column_id": column,
                  "row_ids": list(step["row_ids"])}]}}
    claim.update(extra)
    return claim


def _answer_with(claims, narrative):
    def _build(messages):
        return ScriptedResult(tool_calls=[tool_call(
            "finalize_response",
            final(intent=intent("DATA_ANALYSIS", "COCKPIT"),
                  narrative=narrative,
                  numeric_claims=[c(messages) if callable(c) else c
                                  for c in claims]))])
    return _build


# ---- the central change ------------------------------------------------

def test_a_claim_with_no_number_publishes_the_servers_number(drive,
                                                             release_id):
    """§7, §20. The analyst says where; CreditProbe says what."""
    expected = oracles.ead_by_sector(release_id,
                                     oracles.latest_quarter(release_id))
    canonical = sum(Decimal(str(v)) for v in expected.values())

    outcome, provider, _ = _run(drive, release_id, _answer_with(
        [_total_claim], "Total portfolio EAD is {{claim.total_ead}}."))

    assert outcome.state == st.COMPLETED, outcome.message
    body = outcome.response
    assert "{{claim." not in body["narrative"]
    assert body["narrative"] == (
        f"Total portfolio EAD is "
        f"{disp.format_value(canonical, 'SAR million')}.")
    assert len(provider.sent) == 2, (
        "no repair round may be spent on a number nobody got wrong")


def test_the_published_figure_is_the_one_a_credit_paper_carries(drive,
                                                                release_id):
    """§34. Zero decimal places, thousands separated, currency and scale."""
    outcome, _, _ = _run(drive, release_id, _answer_with(
        [_total_claim], "Total portfolio EAD is {{claim.total_ead}}."))
    assert outcome.state == st.COMPLETED, outcome.message
    rendered = outcome.response["narrative"]
    assert "SAR " in rendered and " million" in rendered
    assert "." not in rendered.split("SAR ")[1].split(" million")[0], (
        f"an amount was published with decimal places: {rendered}")


def test_the_canonical_value_keeps_full_precision_underneath(drive,
                                                             release_id):
    """§16. What is published is rounded. What is stored is not."""
    expected = oracles.ead_by_sector(release_id,
                                     oracles.latest_quarter(release_id))
    canonical = sum(Decimal(str(v)) for v in expected.values())

    outcome, _, record = _run(drive, release_id, _answer_with(
        [_total_claim], "Total is {{claim.total_ead}}."))
    assert outcome.state == st.COMPLETED, outcome.message

    claim = outcome.response["numeric_claims"][0]
    assert claim["display_precision"] == 0, (
        "money shows no decimals, chosen from the unit rather than declared")
    # The rounding is applied ONCE, to the sum of full-precision cells.
    assert disp.quantize(canonical, 0) == Decimal(
        outcome.response["narrative"].split("SAR ")[1]
        .split(" million")[0].replace(",", ""))


# ---- §25: nothing was weakened -----------------------------------------

def test_wrong_arithmetic_still_fails_without_a_declared_value(drive,
                                                               release_id):
    """A derivation over the WRONG rows is wrong however it is formatted."""
    def _half_the_rows(messages):
        step = _result(messages)
        column = next(c for c in step["columns"] if c != "sector_name")
        return {"claim_id": "total_ead", "unit": "SAR million",
                "derivation": {"operation": "sum", "operands": [
                    {"artifact_id": step["artifact_id"], "column_id": column,
                     "row_ids": step["row_ids"][:3]}]}}

    expected = oracles.ead_by_sector(release_id,
                                     oracles.latest_quarter(release_id))
    canonical = sum(Decimal(str(v)) for v in expected.values())

    outcome, _, _ = _run(drive, release_id, _answer_with(
        [_half_the_rows], "Total portfolio EAD is {{claim.total_ead}}."))
    assert outcome.state == st.COMPLETED, outcome.message
    published = Decimal(outcome.response["narrative"].split("SAR ")[1]
                        .split(" million")[0].replace(",", ""))
    assert published != disp.quantize(canonical, 0), (
        "three sectors are not twelve; the server published what the "
        "derivation actually says, which is the contract")


def test_a_claim_pointing_at_a_row_that_does_not_exist_still_fails(
        drive, release_id):
    def _invented_row(messages):
        step = _result(messages)
        column = next(c for c in step["columns"] if c != "sector_name")
        return {"claim_id": "total_ead", "unit": "SAR million",
                "evidence": {"artifact_id": step["artifact_id"],
                             "row_key": "all sectors", "column_id": column}}

    outcome, _, _ = _run(drive, release_id, _answer_with(
        [_invented_row], "Total is {{claim.total_ead}}."), repeats=2)
    assert outcome.state != st.COMPLETED
    assert outcome.error_code == st.ANSWER_VALIDATION, outcome.message


def test_a_value_the_analyst_does_send_is_still_checked(drive, release_id):
    """Offering a cross-check means being held to it."""
    def _wrong_cross_check(messages):
        return _total_claim(messages, decimal_value="1.00")

    outcome, _, _ = _run(drive, release_id, _answer_with(
        [_wrong_cross_check], "Total is {{claim.total_ead}}."), repeats=2)
    assert outcome.state != st.COMPLETED
    assert outcome.error_code == st.ANSWER_VALIDATION, outcome.message


def test_a_correctly_rounded_cross_check_is_accepted(drive, release_id):
    """And costs nothing. It agrees with the server, so there is no dispute."""
    expected = oracles.ead_by_sector(release_id,
                                     oracles.latest_quarter(release_id))
    canonical = sum(Decimal(str(v)) for v in expected.values())

    def _rounded(messages):
        return _total_claim(messages,
                            decimal_value=str(disp.quantize(canonical, 0)))

    outcome, provider, _ = _run(drive, release_id, _answer_with(
        [_rounded], "Total is {{claim.total_ead}}."))
    assert outcome.state == st.COMPLETED, outcome.message
    assert len(provider.sent) == 2


# ---- §19: the packet carries both forms --------------------------------

def test_the_result_packet_carries_the_readers_form_too(drive, release_id):
    seen: dict = {}

    def _capture(messages):
        seen["step"] = _result(messages)
        return _answer_with(
            [_total_claim], "Total is {{claim.total_ead}}.")(messages)

    outcome, _, _ = _run(drive, release_id, _capture)
    assert outcome.state == st.COMPLETED, outcome.message

    step = seen["step"]
    assert "preview_formatted" in step
    assert "column_units" in step
    guide = step["how_to_cite_these_numbers"]
    assert "you_do_not_type_numbers" in guide
    assert "decimal_value" in guide["you_do_not_type_numbers"]


def test_a_column_the_catalogue_cannot_name_is_not_given_a_currency(runtime):
    """§5 fail-closed, at column level. Silence beats an invented unit."""
    from backend.cockpit_v4.execute_tool import column_units

    units = column_units(runtime.catalog,
                         ["ead_reported", "ead_reported_sar_mn", "breaches"],
                         ["cockpit_facility_quarter"])
    assert units["ead_reported"] == "SAR million"
    assert "ead_reported_sar_mn" not in units, (
        "an alias that merely looks like an amount is not resolved")
    assert "breaches" not in units


def test_an_unresolved_column_is_passed_through_unchanged(runtime):
    from backend.cockpit_v4.execute_tool import formatted_preview

    rows = [{"sector_name": "Construction", "ead_reported": 3421.1736,
             "total": 999.5}]
    shown = formatted_preview(rows, {"ead_reported": "SAR million"})
    assert shown[0]["ead_reported"] == "SAR 3,421 million"
    assert shown[0]["total"] == 999.5
    assert shown[0]["sector_name"] == "Construction"
