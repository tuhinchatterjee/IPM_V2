"""
The twelve threads from the live testing log, as regression cases.

Why these and not more unit tests
----------------------------------
Every failure in the log was found by a person using the product, not by a
component being wrong. Typed conversation memory passed every direct test and
failed for every user, because the service in between forgot to pass it. So
these run whole threads through `answer_investigation` — the same function the
browser reaches — and assert on what a reader would see.

What they check
---------------
Behaviour, never phrasing. A test that asserts an exact sentence is a test that
fails when somebody improves the wording, and passes when the product answers
the wrong question in the right words. What is asserted is the shape of the
answer: the population retained, the column order, the invariants, whether a
clarification was asked, whether an interpretation was withheld.

Offline by default
------------------
These run with whatever provider the environment gives them. With no key they
exercise the deterministic governed reader, which is what CI has; with a key
they exercise the live path. Neither is skipped, because the failures in the
log were failures of the surrounding architecture rather than of the model.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available


@pytest.fixture(scope="module", autouse=True)
def _require_the_lake():
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    if not database_available():
        pytest.skip("Threads need a database.")
    if FACILITY not in get_data_source().datasets():
        pytest.skip("Analytical lake not built.")


class Thread:
    """One conversation, carried the way the service carries it."""

    def __init__(self) -> None:
        self.context: dict = {}

    def ask(self, question: str):
        from backend.orchestration import conversation as cv
        from backend.orchestration import memory as wm
        from backend.orchestration.executor import answer_investigation
        from backend.orchestration.orchestrator import remember as advance

        state, memory = cv.load(self.context), wm.load(self.context)
        investigation, answered = answer_investigation(
            question, persist=False, state=state, memory=memory)
        self.context = cv.save(self.context, advance(
            state, answered,
            headline=str(investigation.narrative.direct_answer or ""),
            run_id=None))
        self.context = wm.save(
            self.context,
            wm.observe(wm.load(self.context), answered, investigation))
        return investigation, answered


def rows_of(investigation) -> list[dict]:
    steps = investigation.steps or []
    return list((steps[0].result or {}).get("rows") or []) if steps else []


def columns_of(investigation) -> list[dict]:
    steps = investigation.steps or []
    return list((steps[0].result or {}).get("columns") or []) if steps else []


def visible(investigation) -> list[str]:
    return [str(c.get("name")) for c in columns_of(investigation)
            if not c.get("hidden")]


def said(investigation) -> str:
    narrative = investigation.narrative
    return " ".join(x for x in [narrative.direct_answer, narrative.interpretation,
                                *[f.text for f in (narrative.findings or [])]] if x)


# ---------------------------------------------------------------------------
# A — the top Real Estate customers, and what happens to them
# ---------------------------------------------------------------------------


def test_thread_a_keeps_the_five_and_says_when_none_of_them_qualify():
    thread = Thread()

    first, _ = thread.ask("Show me the five largest Real Estate customers by EAD.")
    assert first.status == "succeeded"
    assert len(rows_of(first)) == 5, "the question asked for five"

    second, answered = thread.ask("Which of these are Stage 2 or Stage 3?")
    assert second.status == "succeeded", second.rejected

    # The failure this thread was reported for: all five were Stage 1 and the
    # answer said "0 customers where IFRS 9 stage is in 2, 3" — true, useless,
    # and indistinguishable from a fault.
    if not rows_of(second):
        answer = second.narrative.direct_answer.lower()
        assert "none of" in answer, answer
        partition = getattr(answered.build, "partition", None)
        assert partition is not None and partition.usable, (
            "an empty membership answer must say where the population "
            "actually sits")
        assert partition.total == 5, "the partition must cover the carried five"
        assert "stage" in answer, answer


def test_thread_a_carries_the_population_into_an_enrichment():
    thread = Thread()
    thread.ask("Show me the five largest Real Estate customers by EAD.")
    third, _ = thread.ask("Add their latest internal rating.")

    assert third.status in ("succeeded", "needs_clarification")
    if third.status == "succeeded":
        assert 0 < len(rows_of(third)) <= 5, (
            "an enrichment must not widen the population it enriches")


# ---------------------------------------------------------------------------
# B — IFRS 9 discovery, and opening what was discovered
# ---------------------------------------------------------------------------


def test_thread_b_leads_with_the_right_dataset_and_opens_it():
    thread = Thread()

    first, _ = thread.ask("What IFRS 9 data do you have?")
    assert first.status == "succeeded"
    answer = first.narrative.direct_answer
    assert "ifrs9_staging" in answer, answer
    detail = (first.steps[0].result or {}).get("detail") or {}
    assert (detail.get("primary") or {}).get("rows", 0) > 0, (
        "a discovery answer has to say how much data there is")

    second, _ = thread.ask("What is the latest period?")
    assert "ifrs9_staging" in second.narrative.direct_answer, (
        "the subject must survive a metadata follow-up")

    third, _ = thread.ask("Which fields contain PD, LGD and ECL?")
    assert third.status == "succeeded"

    fourth, _ = thread.ask("Open the latest dataset.")
    assert fourth.status == "succeeded"
    opened = ((fourth.steps[0].result or {}).get("detail") or {}).get("open") or {}
    assert opened.get("name") == "ifrs9_staging"
    assert len(rows_of(fourth)) > 1, "opening a dataset must show its rows"


# ---------------------------------------------------------------------------
# C — an ambiguous governed concept
# ---------------------------------------------------------------------------


def test_thread_c_asks_which_exposure_rather_than_choosing_one():
    thread = Thread()
    investigation, answered = thread.ask("Show me exposure.")

    assert investigation.status == "needs_clarification", (
        "three governed measures are materially different amounts; silently "
        "choosing drawn exposure is wrong for most of the questions that "
        "sentence could mean")
    assert answered.ambiguity, "the choice offered must be recorded"


# ---------------------------------------------------------------------------
# D — a broad investigation
# ---------------------------------------------------------------------------


def test_thread_d_investigates_a_sector_rather_than_looking_up_a_name():
    thread = Thread()
    investigation, _ = thread.ask(
        "Something seems wrong with Contracting. Investigate it.")

    assert investigation.status == "succeeded", investigation.rejected
    answer = said(investigation)
    assert "contracting" in answer.lower()
    assert len(rows_of(investigation)) > 1, (
        "a broad investigation returns several governed checks, not one figure")


# ---------------------------------------------------------------------------
# G — a threshold the answer must not contradict
# ---------------------------------------------------------------------------


def test_thread_g_never_cites_a_figure_above_its_own_threshold():
    thread = Thread()
    investigation, answered = thread.ask(
        "Which customers have covenant headroom below 15%?")

    assert investigation.status == "succeeded", investigation.rejected
    report = answered.invariants
    assert report is not None and report.ok, (
        [f.detail for f in (report.failures if report else [])])

    # Every returned row, at the CLOSING position. "Customers who HAVE headroom
    # below 15%" is a claim about the present: a customer at 16.67% a year ago
    # and 3% today belongs in the answer, and the year-ago figure belongs in the
    # table beside it.
    present = [c for c in columns_of(investigation)
               if "headroom" in str(c.get("name"))
               and str(c.get("name")).startswith("closing_")]
    assert present, "a two-period answer must carry the closing position"
    for row in rows_of(investigation):
        for column in present:
            value = row.get(str(column.get("name")))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                assert value < 15.0, (
                    f"{column.get('name')}={value} in an answer about <15%")

    # The opening column is free to sit above the threshold, and MUST say which
    # period it is. A bare "Covenant headroom" showing 16.67 under a heading
    # that says below 15% is the contradiction this thread exists for, even
    # when every figure in it is correct.
    for column in columns_of(investigation):
        name = str(column.get("name"))
        if "headroom" not in name or name.startswith("closing_"):
            continue
        if name.endswith(("_change", "_change_pct")):
            continue
        label = str(column.get("label") or "")
        assert any(token in label for token in ("Q1", "Q2", "Q3", "Q4")), (
            f"the opening column is labelled {label!r}, which a reader will "
            "take for the present position")

    # And every figure the prose cites about it.
    from backend.orchestration import invariants as inv

    columns = columns_of(investigation)
    assert not inv.check_prose(
        report.checks, [said(investigation)],
        labels={str(c.get("name")): str(c.get("label") or "") for c in columns},
        units={str(c.get("name")): str(c.get("unit") or "") for c in columns})


# ---------------------------------------------------------------------------
# H — several measures across one grouping dimension
# ---------------------------------------------------------------------------


def test_thread_h_puts_the_grouping_dimension_first():
    thread = Thread()
    investigation, _ = thread.ask(
        "For each rating grade, show average ECL coverage, average leverage "
        "and average DSCR.")

    assert investigation.status == "succeeded", investigation.rejected
    first = visible(investigation)[:1]
    assert first, "the result must have a visible column"
    assert "grade" in first[0].lower(), (
        f"the primary grouping dimension belongs first, not {first[0]}")

    # And a chart, because a profile across grades is invisible in a grid.
    visual = (investigation.steps[0].result or {}).get("visual") or {}
    assert visual.get("chart"), "a visual decision must be recorded"
    assert visual.get("toggle"), "a chart is never offered without its table"


# ---------------------------------------------------------------------------
# I — presentation changes over a narrowing thread
# ---------------------------------------------------------------------------


def test_thread_i_changes_presentation_without_changing_the_result():
    thread = Thread()

    first, _ = thread.ask("What is total EAD by sector in the latest quarter?")
    assert first.status == "succeeded"
    before = len(rows_of(first))

    second, answered = thread.ask("Show this as a graph.")
    assert second.status == "succeeded", second.rejected
    assert len(rows_of(second)) == before, (
        "changing how a result is shown must not change what it contains")

    visual = (second.steps[0].result or {}).get("visual") or {}
    assert visual.get("chart") != "table", "a graph was asked for"
    assert visual.get("source") == "asked"

    third, _ = thread.ask("Use a table instead.")
    assert ((third.steps[0].result or {}).get("visual") or {}).get("chart") == "table"


# ---------------------------------------------------------------------------
# J — whether a pattern holds
# ---------------------------------------------------------------------------


def test_thread_j_describes_the_association_and_refuses_to_claim_a_cause():
    thread = Thread()
    investigation, answered = thread.ask(
        "Does the relationship between grade, ECL coverage and DSCR appear "
        "consistent across grades?")

    assert investigation.status == "succeeded", investigation.rejected
    found = answered.association or {}
    assert found.get("sentence"), "the pattern must be described, not refused"
    assert found.get("pairs"), "an association names the measures it is between"
    assert found.get("caveat"), "causality must be disclaimed explicitly"

    answer = said(investigation).lower()
    for word in ("because", "caused by", "driven by"):
        assert word not in answer, f"the answer asserts a cause: {word!r}"


# ---------------------------------------------------------------------------
# K — a question the governed data cannot answer
# ---------------------------------------------------------------------------


def test_thread_k_says_it_holds_no_such_data_and_answers_nothing_else():
    thread = Thread()
    investigation, answered = thread.ask(
        "Did the CEO of Al Rajhi Contracting resign this quarter?")

    assert investigation.status == "unsupported", investigation.status
    assert answered.unsupported
    assert not rows_of(investigation), (
        "a menu of figures invites somebody to accept an answer about "
        "exposure to a question about corporate governance")


# ---------------------------------------------------------------------------
# L — the Stage 2 share comparison that already worked
# ---------------------------------------------------------------------------


def test_thread_l_preserves_the_stage_two_share_comparison():
    thread = Thread()
    investigation, answered = thread.ask(
        "For each sector, calculate Stage 2 EAD as a percentage of total "
        "sector EAD, compare it with four quarters ago, and rank sectors by "
        "the largest increase.")

    assert investigation.status == "succeeded", investigation.rejected
    rows = rows_of(investigation)
    assert rows, "this comparison worked before this phase and must still work"

    report = answered.invariants
    assert report is not None and report.ok, (
        [f.detail for f in (report.failures if report else [])])

    # A share is a share.
    for row in rows:
        for name, value in row.items():
            if name.endswith("_share_pct") and isinstance(value, (int, float)):
                assert 0.0 <= value <= 100.0, f"{name}={value}"


# ---------------------------------------------------------------------------
# Across every thread: no binary debris reaches a reader
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("question", [
    "What is total EAD by sector in the latest quarter?",
    "Show me the five largest Real Estate customers by EAD.",
    "For each sector, calculate Stage 2 EAD as a percentage of total sector "
    "EAD, compare it with four quarters ago, and rank sectors by the largest "
    "increase.",
], ids=["aggregate", "ranking", "share-movement"])
def test_no_answer_contains_binary_floating_point_debris(question):
    """2.6246841182876173% is correct, and looks exactly like a defect."""
    from backend.orchestration import figures

    investigation, _ = Thread().ask(question)
    assert investigation.status == "succeeded", investigation.rejected

    for text in [investigation.narrative.direct_answer,
                 investigation.narrative.interpretation,
                 *[f.text for f in (investigation.narrative.findings or [])],
                 *(investigation.narrative.caveats or [])]:
        assert not figures.has_debris(text or ""), text


# ---------------------------------------------------------------------------
# The measure the question named, and the arithmetic it asked for
# ---------------------------------------------------------------------------


def test_a_phrase_is_not_read_as_two_measures():
    """"Average ECL coverage" names one measure and matched two.

    The `ecl` concept matched the three letters inside "ECL coverage" and the
    `ecl_coverage` concept matched the whole phrase. Both are governed, only
    one was asked for, and the spurious one came first — so the answer led with
    a SUM of expected credit loss under a question about coverage ratios.
    """
    _, answered = Thread().ask(
        "For each rating grade, show average ECL coverage and average DSCR.")

    fields = [m.field for m in (answered.build.matches or [])]
    assert "total_ecl" not in fields, fields
    assert "ecl_coverage_pct" in fields, fields


def test_an_averaged_measure_is_never_reported_as_a_total():
    """Ten per-grade averages added together is not a coverage ratio.

    It is not a total either, and it reads as both.
    """
    investigation, _ = Thread().ask(
        "For each rating grade, show average ECL coverage and average DSCR.")

    assert investigation.status == "succeeded", investigation.rejected
    said = investigation.narrative.direct_answer
    assert "averages" in said.lower(), said

    values = (investigation.steps[0].result or {}).get("values") or {}
    assert "total" not in values, "an averaged measure has no total"
    assert "average" in values

    # And the term of art survives the sentence it opens.
    assert "Ecl" not in said, said


def test_a_summed_measure_still_reports_a_total():
    investigation, _ = Thread().ask(
        "What is total EAD by sector in the latest quarter?")

    values = (investigation.steps[0].result or {}).get("values") or {}
    assert "total" in values
    assert "average" not in values
