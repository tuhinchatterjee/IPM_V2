"""§51's first integration path, and §10–§13's gates.

    user formula → code → validator → user-approved spec → execution
                 → preview → lock → Lens render

Run end to end against the real analytical data. The gates get their own tests
because §57 is explicit that the tranche is not done because SQL appears in a
box: the sequence has to be enforced, and code that changed after it was
approved has to be refused.
"""

from __future__ import annotations

import pytest

from backend.metrics import formula_flow as flow
from backend.metrics.metric_code import MetricCode
from tests.conftest import database_available

QOQ = ("Add QoQ Exposure Change: "
       "(Current Quarter Exposure / Previous Quarter Exposure) - 1")
PERIOD = "Q2 2026"


@pytest.fixture()
def drafted():
    body = flow.draft(QOQ, period=PERIOD)
    assert body["ready"], body["validation"]["failures"]
    return body


# ------------------------------------------------------------ §6: the code


def test_the_draft_carries_everything_section_six_asks_for(drafted):
    code = drafted["code"]
    assert code["name"]
    assert code["user_formula"] == (
        "(Current Quarter Exposure / Previous Quarter Exposure) - 1")
    assert code["interpreted_formula"]
    assert code["plain_english"]
    assert code["domains"] == ["cockpit"]
    assert code["datasets"] == ["portfolio_facility"]
    assert code["fields"] == ["exposure"]
    assert code["grain"]
    assert code["period_logic"]
    assert code["aggregation"]
    assert code["unit"] == "percent"
    assert code["sql"]
    assert code["output_grain"]
    assert code["compiled_sql"], "the statement that will actually run"


def test_the_artefact_says_who_wrote_it(drafted):
    """With no provider configured CreditProbe assembles the definition and
    renders the SQL from it, so the reconciliation check is comparing the
    compiler with itself. The screen must not imply otherwise."""
    code = drafted["code"]
    assert code["author"] in ("MODEL", "CREDITPROBE")
    assert code["author_label"]
    if code["author"] == "CREDITPROBE":
        assert not code["independently_written"]
        assert any("assembled by CreditProbe" in n for n in code["notes"])


def test_the_users_formula_is_stored_verbatim(drafted):
    assert drafted["intake"]["preserved"]
    assert drafted["code"]["user_formula"] in QOQ


# ------------------------------------------------------- §10–§12: the gates


def test_preview_without_approval_is_refused(drafted):
    code = MetricCode.from_dict(drafted["code"])
    with pytest.raises(flow.ApprovalRequired):
        flow.preview(code, period=PERIOD)


def test_lock_without_approval_is_refused(drafted):
    code = MetricCode.from_dict(drafted["code"])
    with pytest.raises(flow.ApprovalRequired):
        flow.lock(code, period=PERIOD)


def test_code_changed_after_approval_is_refused(drafted):
    """A browser could show one definition, collect the approval and post a
    different one. The checksum is what stops that."""
    approved = flow.approve(MetricCode.from_dict(drafted["code"]),
                            period=PERIOD)
    tampered = MetricCode.from_dict(approved["code"])
    tampered.sql = tampered.sql + "\n-- and something else"
    with pytest.raises(flow.ApprovalStale):
        flow.preview(tampered, period=PERIOD,
                     approved_checksum=approved["checksum"])


def test_lock_without_a_preview_is_refused(drafted):
    approved = flow.approve(MetricCode.from_dict(drafted["code"]),
                            period=PERIOD)
    with pytest.raises(flow.ApprovalRequired) as caught:
        flow.lock(MetricCode.from_dict(approved["code"]), period=PERIOD,
                  approved_checksum=approved["checksum"])
    assert "has not been previewed" in str(caught.value)


def test_approving_code_that_will_not_run_is_refused():
    body = flow.draft("Add gini / total exposure.", period=PERIOD)
    code = MetricCode.from_dict(body["code"])
    code.sql = "DROP TABLE portfolio_facility"
    result = flow.approve(code, period=PERIOD)
    assert not result["approved"]
    assert "nothing to approve" in result["why"]


# ------------------------------------------------------------- §12: preview


def test_the_preview_shows_the_exact_calculation(drafted):
    approved = flow.approve(MetricCode.from_dict(drafted["code"]),
                            period=PERIOD)
    result = flow.preview(MetricCode.from_dict(approved["code"]),
                          period=PERIOD,
                          approved_checksum=approved["checksum"])
    preview = result["preview"]
    assert preview["available"]
    # §12's own list: current period, current value, previous period,
    # previous value, the arithmetic, and the result.
    assert preview["period"] == PERIOD
    assert preview["numerator"]["period"] == "Q2 2026"
    assert preview["denominator"]["period"] == "Q1 2026"
    assert preview["numerator"]["value"] is not None
    assert preview["denominator"]["value"] is not None
    assert "/" in preview["final"] and "=" in preview["final"]
    assert preview["formatted"].endswith("%")
    # …and the lineage beside it.
    assert preview["datasets"] == ["portfolio_facility"]
    assert preview["domains"] == ["cockpit"]
    assert preview["data_version"]
    assert preview["code_version"]
    assert preview["compiled_sql"]


def test_the_preview_runs_the_program_not_the_sql(drafted):
    """§7. A person approves the SQL; CreditProbe executes the plan it was
    reconciled against. Corrupting the SQL after approval is caught by the
    checksum — and even with the checksum waived, the SQL is never sent
    anywhere."""
    approved = flow.approve(MetricCode.from_dict(drafted["code"]),
                            period=PERIOD)
    code = MetricCode.from_dict(approved["code"])
    result = flow.preview(code, period=PERIOD,
                          approved_checksum=approved["checksum"])
    assert result["preview"]["available"]
    assert result["preview"]["compiled_sql"] != code.sql


# ---------------------------------------------------- §11: editing the code


def test_an_edit_is_revalidated_and_its_meaning_compared(drafted):
    before = MetricCode.from_dict(drafted["code"])
    edited = MetricCode.from_dict(drafted["code"])
    edited.sql = "SELECT SUM(exposure) FROM portfolio_facility WHERE period = ?"
    result = flow.revise(edited, period=PERIOD, edited_by_user=True,
                         previous=before)
    assert not result["ready"], "an edit that no longer divides must not pass"
    assert result["code"]["author"] == "USER"


def test_divergence_says_what_an_edit_changed_about_the_meaning():
    from backend.metrics.formula import Condition, Formula, Side, Term

    wide = MetricCode(
        name="M", user_formula="stage 2 + stage 3 over total", unit="percent",
        formula=Formula(
            kind="percentage",
            numerator=Side(terms=(
                Term(id="a", label="Stage 2", dataset="portfolio_facility",
                     aggregate="sum", field="exposure",
                     where=(Condition(field="ifrs9_stage", op="in",
                                      value=[2, 3]),)),)),
            denominator=Side(terms=(
                Term(id="t", label="Total", dataset="portfolio_facility",
                     aggregate="sum", field="exposure"),)),
            scale=100.0))
    narrow = MetricCode(
        name="M", user_formula="stage 2 + stage 3 over total", unit="percent",
        formula=Formula(
            kind="percentage",
            numerator=Side(terms=(
                Term(id="a", label="Stage 2", dataset="portfolio_facility",
                     aggregate="sum", field="exposure",
                     where=(Condition(field="ifrs9_stage", op="=",
                                      value=2),)),)),
            denominator=Side(terms=(
                Term(id="t", label="Total", dataset="portfolio_facility",
                     aggregate="sum", field="exposure"),)),
            scale=100.0))
    from backend.metrics import codegen

    wide = codegen._describe(wide)
    narrow = codegen._describe(narrow)
    divergence = flow.divergence(wide, narrow)
    assert divergence["changed"]
    assert divergence["confirmation_required"]
    assert not divergence["matches_original_formula"]
    assert "no longer matches the formula you wrote" in divergence["note"]


def test_a_reformatting_edit_says_nothing(drafted):
    before = MetricCode.from_dict(drafted["code"])
    after = MetricCode.from_dict(drafted["code"])
    after.sql = before.sql.replace("\n", " ")
    divergence = flow.divergence(before, after)
    assert not divergence["changed"]
    assert divergence["matches_original_formula"]


# ------------------------------------------------- §13 and §33: lock, render


@pytest.mark.skipif(not database_available(),
                    reason="locking a metric needs the database")
def test_the_whole_journey_ends_with_a_metric_that_renders(drafted):
    """§57's sequence, in one test.

    formula → code → validator → approval → execution → preview → lock →
    persists → renders on a Lens.
    """
    from backend.metrics import service

    approved = flow.approve(MetricCode.from_dict(drafted["code"]),
                            note="Checked against the quarterly pack.",
                            period=PERIOD)
    previewed = flow.preview(MetricCode.from_dict(approved["code"]),
                             period=PERIOD,
                             approved_checksum=approved["checksum"])
    locked = flow.lock(MetricCode.from_dict(previewed["code"]),
                       period=PERIOD,
                       approved_checksum=previewed["checksum"])
    assert locked["locked"]
    metric_id = locked["metric_id"]
    try:
        # It persists, with everything §13 asks for.
        stored = service.resolve(metric_id)
        assert stored.is_composite
        assert stored.code["user_formula"] == (
            "(Current Quarter Exposure / Previous Quarter Exposure) - 1")
        assert stored.code["sql"]
        assert stored.code["plain_english"]
        assert stored.code["validation"]["ok"]
        assert stored.code["approval_note"] == (
            "Checked against the quarterly pack.")
        assert stored.code["stage"] == "LOCKED"

        # …and it renders, through the same path a Lens tile uses.
        answer = service.value(metric_id, period=PERIOD)
        assert answer["available"]
        assert answer["unit"] == "percent"
        assert answer["calculation"]["numerator"]["period"] == "Q2 2026"
        assert answer["calculation"]["denominator"]["period"] == "Q1 2026"

        # …including in a batch, which is how a Lens actually reads it.
        batch = service.values([metric_id, "corporate.exposure"],
                               period=PERIOD)
        assert batch["metrics"][metric_id]["available"]
    finally:
        service.delete(metric_id)
