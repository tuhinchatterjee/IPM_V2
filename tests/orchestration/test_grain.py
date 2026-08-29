"""
§4: the grain the answer is at is a governed decision, and a wrong one fails
before display.

The defect these were written against
--------------------------------------
    "Show days past due and the NPL ratio for the portfolio at the latest
     published period."

returned ten account rows. The ordering invariant caught it and the
presentability gate withheld the table, so nothing wrong was shown — and
nothing was fixed. A portfolio question that happened to come back in sorted
order would have been displayed.

Every test here drives the real governed path. None of them assert on a
regex; they assert on what the plan emitted and on how many rows came back,
because that is what the reader sees.
"""

from __future__ import annotations

import os

import pytest

_LIVE = os.environ.get("IPM_SKIP_DB", "") != "1"
db = pytest.mark.skipif(not _LIVE, reason="needs the governed database")


def _probe(question: str):
    from backend.proof import probe as pb

    with pb.assert_no_provider_calls():
        return pb.run_probe(question, user_id=1)


def _build(answered):
    return getattr(answered, "build", None)


# ---------------------------------------------------------------- the ladder


def test_the_ladder_runs_coarse_to_fine():
    """A level number that did not order the grains would make every
    comparison in the module meaningless."""
    from backend.orchestration import grain as gr

    assert gr.LADDER == (gr.PORTFOLIO, gr.SEGMENT, gr.CUSTOMER, gr.FACILITY,
                         gr.RECORD)
    assert (gr.LEVEL[gr.PORTFOLIO] < gr.LEVEL[gr.SEGMENT]
            < gr.LEVEL[gr.CUSTOMER] < gr.LEVEL[gr.FACILITY]
            < gr.LEVEL[gr.RECORD])


def test_period_is_not_a_level_on_the_ladder():
    """A time series is a portfolio answer repeated per period, not a sixth
    level of entity detail."""
    from backend.orchestration import grain as gr

    assert gr.PERIOD not in gr.LEVEL
    assert gr.PERIOD in gr.GRAINS


def test_every_grain_says_what_one_row_is():
    from backend.orchestration import grain as gr

    for name in gr.GRAINS:
        assert gr.MEANS.get(name), f"{name} does not say what one row is"


# ------------------------------------------------------ reading the objective


def test_a_portfolio_question_asks_for_one_row():
    from backend.orchestration import grain as gr

    want = gr.requested(
        "Show days past due and the NPL ratio for the portfolio at the "
        "latest published period.")
    assert want.grain == gr.PORTFOLIO
    assert want.explicit is True
    assert want.keys() == ()


def test_a_breakdown_beats_a_portfolio_noun():
    """"Total EAD by sector for the portfolio" names both. The narrower one
    is the one being asked for."""
    from backend.orchestration import grain as gr

    want = gr.requested("Total EAD by sector for the portfolio",
                        dimension="sector")
    assert want.grain == gr.SEGMENT
    assert want.keys() == ("sector",)


def test_a_customer_noun_beats_a_portfolio_noun():
    from backend.orchestration import grain as gr

    want = gr.requested("the five largest Real Estate customers in the "
                        "portfolio")
    assert want.grain == gr.CUSTOMER


def test_a_carried_population_beats_every_word_in_the_sentence():
    """"Which of these are Stage 2?" is answered per customer whatever
    dataset it is read from."""
    from backend.orchestration import grain as gr

    want = gr.requested("which of these are in Stage 2 across the portfolio",
                        population_grain=gr.CUSTOMER)
    assert want.grain == gr.CUSTOMER
    assert want.source == "population"


def test_asking_for_a_number_of_rows_is_not_a_portfolio_question():
    """"The top five across the portfolio" wants five rows. A portfolio
    reading would return one and call it five."""
    from backend.orchestration import grain as gr

    want = gr.requested("the top five across the portfolio",
                        dataset_grain=gr.FACILITY, rows_requested=True)
    assert want.grain != gr.PORTFOLIO


def test_an_unstated_grain_is_marked_unstated():
    """The dataset's own grain is a fallback, and the answer says so rather
    than presenting it as what the user asked for."""
    from backend.orchestration import grain as gr

    want = gr.requested("show ECL at the latest quarter",
                        dataset_grain=gr.FACILITY)
    assert want.grain == gr.FACILITY
    assert want.explicit is False
    assert want.source == "dataset"


# --------------------------------------------------- reading what was built


def test_the_declared_grain_comes_off_the_grouping_not_off_intent():
    """A plan that MEANT to answer per customer and grouped by nothing
    returns one row, and this has to say so — that disagreement is what the
    postcondition exists to catch."""
    from backend.orchestration import grain as gr

    assert gr.declared([]) == gr.PORTFOLIO
    assert gr.declared(["customer_id"], key="customer_id") == gr.CUSTOMER
    assert gr.declared(["account_id"], key="account_id") == gr.FACILITY
    assert gr.declared(["sector"], dimension="sector") == gr.SEGMENT


def test_a_coarser_request_needs_an_aggregation():
    from backend.orchestration import grain as gr

    assert gr.needs_aggregation(gr.FACILITY, gr.PORTFOLIO) is True
    assert gr.needs_aggregation(gr.FACILITY, gr.FACILITY) is False


def test_a_finer_request_than_the_source_is_unreachable():
    """A customer-keyed source cannot produce facility rows, and returning
    the customer rows under a facility heading is D15 in reverse."""
    from backend.orchestration import grain as gr

    assert gr.unreachable(gr.CUSTOMER, gr.FACILITY) is True
    assert gr.unreachable(gr.FACILITY, gr.CUSTOMER) is False


# ------------------------------------------------- §4's five mandatory tests


@db
def test_a_portfolio_question_returns_portfolio_level_output():
    """D15's exact reproducer. One row, not ten accounts."""
    from backend.orchestration import grain as gr

    probe, answered = _probe(
        "Show days past due and the NPL ratio for the portfolio at the "
        "latest published period.")

    assert probe.error == "", probe.error
    assert probe.executed is True
    assert probe.status == "succeeded", (
        "the portfolio question no longer produces a displayable answer")
    build = _build(answered.answered)
    assert build is not None
    assert build.output_grain == gr.PORTFOLIO
    assert probe.rows_returned == 1, (
        f"a portfolio question returned {probe.rows_returned} rows")


@db
def test_a_segment_question_returns_one_row_per_group():
    from backend.orchestration import grain as gr

    probe, answered = _probe("Show IFRS 9 ECL by sector for the latest quarter.")

    assert probe.error == "", probe.error
    build = _build(answered.answered)
    assert build.output_grain == gr.SEGMENT
    assert build.grain_contract.keys == ("sector",)
    assert (probe.rows_returned or 0) > 1


@db
def test_a_customer_question_returns_one_row_per_customer():
    from backend.orchestration import grain as gr

    probe, answered = _probe(
        "Show the ten largest customers by IFRS 9 EAD at the latest quarter.")

    assert probe.error == "", probe.error
    build = _build(answered.answered)
    assert build.output_grain == gr.CUSTOMER
    assert build.grain_contract.keys == ("customer_id",)


@db
def test_a_facility_question_may_return_facility_rows():
    from backend.orchestration import grain as gr

    probe, answered = _probe("List the facilities in Stage 3 at the latest "
                             "quarter.")

    assert probe.error == "", probe.error
    build = _build(answered.answered)
    assert build.output_grain == gr.FACILITY
    assert build.grain_contract.keys == ("account_id",)


@db
def test_each_analysis_in_a_broad_investigation_declares_its_own_grain():
    """§4: a broad investigation may contain several Analyses at different
    grains, and each one declares and validates its own."""
    from backend.orchestration import grain as gr

    probe, answered = _probe(
        "Review the latest portfolio and tell me everything that matters.")

    assert probe.error == "", probe.error
    seen: list[str] = []
    for step in (getattr(answered.answered, "investigation", None) or []):
        build = getattr(step, "build", None)
        contract = gr.contract_of(build) if build is not None else None
        if contract is not None:
            seen.append(contract.got or contract.want.grain)
            assert contract.ok, (
                "a sub-analysis inside a broad investigation emitted a grain "
                "its own objective did not ask for")
    # Nothing is asserted about HOW MANY sub-analyses declare a grain: a broad
    # investigation that probes rather than executes has none, and inventing a
    # grain for a step that ran no analysis would be the defect again.
    assert all(g in gr.GRAINS for g in seen)


# ----------------------------------------- the postconditions, as invariants


def test_a_portfolio_contract_compiles_a_single_row_postcondition():
    from backend.orchestration import grain as gr
    from backend.orchestration import invariants as iv

    class _Build:
        shape = "aggregate"
        top_n = 0
        filters: list = []
        conditions: list = []
        matches: list = []
        grain_contract = gr.Contract(
            want=gr.Requested(grain=gr.PORTFOLIO, because="the book",
                              explicit=True, source="portfolio"),
            got=gr.PORTFOLIO, source_grain=gr.FACILITY, keys=())

    checks = iv.compile_checks(_Build(), "for the portfolio")
    grain_checks = [c for c in checks if c.rule == "output_grain"]
    assert len(grain_checks) == 1
    assert grain_checks[0].params["single_row"] is True


def test_a_portfolio_answer_with_many_rows_fails_the_postcondition():
    """The check that would have caught D15 without waiting for the rows to
    come back out of order."""
    from backend.orchestration import grain as gr
    from backend.orchestration import invariants as iv

    check = iv.Check(rule="output_grain", claim="one row for the whole book",
                     params={"grain": gr.PORTFOLIO, "single_row": True})

    class _Runtime:
        rows = [{"ead": 1}, {"ead": 2}]
        row_count = 2
        columns: list = []

    report = iv.verify([check], _Runtime())
    assert report.ok is False
    assert "2 rows" in report.failures[0].detail


def test_a_repeated_key_fails_the_grain_postcondition():
    """Duplicate amplification: a join fanned the book out and the second row
    is the same customer's second facility."""
    from backend.orchestration import invariants as iv

    check = iv.Check(rule="unique_grain_key", claim="one row per customer",
                     columns=("customer_id",),
                     params={"columns": ["customer_id"], "grain": "customer"})

    class _Runtime:
        rows = [{"customer_id": "C1"}, {"customer_id": "C1"}]
        row_count = 2
        columns = [{"name": "customer_id"}]

    report = iv.verify([check], _Runtime())
    assert report.ok is False
    assert "multiplied the book" in report.failures[0].detail


def test_no_grain_checks_are_compiled_without_a_contract():
    """A shape with no contract is not silently assumed to be at facility
    grain. An assumed grain is the defect, one layer down."""
    from backend.orchestration import invariants as iv

    class _Build:
        shape = "aggregate"
        top_n = 0
        filters: list = []
        conditions: list = []
        matches: list = []

    checks = iv.compile_checks(_Build(), "anything")
    assert not [c for c in checks
                if c.rule in {"output_grain", "unique_grain_key"}]


# --------------------------------------------------- what the user is shown


@db
def test_the_scope_line_carries_the_output_grain_not_the_source_grain():
    """A by-sector aggregate over a facility-keyed table used to declare
    itself facility-grained, which is true of what it scanned and false of
    what the reader is looking at."""
    from backend.orchestration import grain as gr

    _, answered = _probe("Show IFRS 9 ECL by sector for the latest quarter.")
    delta = getattr(answered.answered, "scope", None)
    assert delta is not None
    frame = delta.after
    assert frame.grain == gr.SEGMENT
    assert frame.grain_because
    # And it survives the round trip through the conversation state, because a
    # grain that is only in memory is a grain the next turn cannot see.
    from backend.orchestration import scope as sp

    assert sp.ScopeFrame.from_dict(frame.to_dict()).grain_because == \
        frame.grain_because


@db
def test_the_trace_says_what_one_row_is():
    probe, answered = _probe(
        "Show days past due and the NPL ratio for the portfolio at the "
        "latest published period.")
    del probe
    runtime = getattr(answered.answered, "runtime", None)
    graph = getattr(runtime, "trace", None) or getattr(runtime, "graph", None)
    nodes = getattr(graph, "nodes", {}) or {}
    plan_node = nodes.get("plan")
    assert plan_node is not None, "the Trace has no plan node to carry a grain"
    config = getattr(plan_node, "config", {}) or {}
    assert config.get("output_grain") == "portfolio"
    assert config.get("grain_contract", {}).get("explanation")


@db
def test_the_assurance_check_reports_the_contract_rather_than_the_source():
    from backend.assurance import signals as sg

    _, answered = _probe("Show IFRS 9 ECL by sector for the latest quarter.")
    ctx = sg.Ctx.of(getattr(answered.answered, "investigation", None),
                    answered.answered)
    signal = sg.read("grain_selection", ctx)
    assert signal is not None
    assert signal.outcome == "PASS"
    assert "one row per group" in signal.detail
