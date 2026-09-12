"""
Did anyone cross a severity band, and does the product know that is a
different question from how far a score moved?

The defect this file exists to close
------------------------------------
"How many obligors changed risk band in the latest month?" came back as a
twenty-month decomposition of the portfolio score by intelligence layer. Every
figure in it was right. None of them was a count of names, and the window was
not the latest month.

The two readings look alike in English — "changed", "moved", "deteriorated"
belong to both — which is exactly why they have to be separated deliberately
rather than left to whichever pattern matches first. A band change is
discrete, per obligor, and is what the watchlist and the escalation matrix
key on: a name that crossed into HIGH is a case to open whether its score
moved two points or twenty.

Nothing here asserts a stored answer. The counts are recomputed in the test
from the two published months, off the raw column, so a rebuild that changes
the data changes both sides and the test still means something.
"""

from __future__ import annotations

import pytest

from backend.early_warning import compose as cp
from backend.early_warning import facts as ff
from backend.early_warning import v2_service as svc
from backend.early_warning.conversation import normalise as norm
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import validate as val_mod

ORDER = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")
HIGH_PLUS = {"HIGH", "VERY_HIGH"}


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if len(svc.periods()) < 2:
            pytest.skip("Two published months are needed for a transition.")
    except Exception:  # noqa: BLE001
        pytest.skip("The Early Warning domain is not built.")


@pytest.fixture(scope="module")
def truth():
    """The transitions, recomputed here rather than read from the pack."""
    published = list(svc.periods())
    was = {r["customer_id"]: r
           for r in svc.borrower_month(published[-2]).to_dict("records")}
    now = {r["customer_id"]: r
           for r in svc.borrower_month(published[-1]).to_dict("records")}
    moves = []
    for cid, row in now.items():
        if cid not in was:
            continue
        before, after = str(was[cid]["ews_band"]), str(row["ews_band"])
        moves.append({
            "customer_id": cid, "name": row["customer_name"],
            "sector": str(row.get("sector")),
            "from": before, "to": after,
            "step": ORDER.index(after) - ORDER.index(before),
            "exposure": float(row["exposure"]),
        })
    return {
        "from_period": published[-2], "to_period": published[-1],
        "population": len(moves),
        "moves": moves,
        "changed": [m for m in moves if m["step"]],
        "into": [m for m in moves if m["step"] and m["to"] in HIGH_PLUS
                 and m["from"] not in HIGH_PLUS],
        "out_of": [m for m in moves if m["step"] and m["from"] in HIGH_PLUS
                   and m["to"] not in HIGH_PLUS],
    }


# ----------------------------------------------------------- the counts


def test_the_counts_reconcile_to_the_two_published_months(truth):
    pack = ff.transitions()
    f = pack.figures
    assert f["from_period"] == truth["from_period"]
    assert f["to_period"] == truth["to_period"]
    assert f["obligors_in_both"] == truth["population"]
    assert f["changed"] == len(truth["changed"])
    assert f["improved"] == sum(1 for m in truth["changed"] if m["step"] < 0)
    assert f["deteriorated"] == sum(1 for m in truth["changed"] if m["step"] > 0)


def test_the_three_directions_account_for_everybody(truth):
    f = ff.transitions().figures
    assert f["improved"] + f["deteriorated"] + f["unchanged"] \
        == f["obligors_in_both"]


def test_the_matrix_sums_to_the_population(truth):
    f = ff.transitions().figures
    assert sum(cell["obligors"] for cell in f["matrix"]) == f["obligors_in_both"]


def test_the_high_plus_crossings_reconcile(truth):
    f = ff.transitions().figures
    assert f["crossed_into_high_plus"] == len(truth["into"])
    assert f["left_high_plus"] == len(truth["out_of"])


def test_it_compares_the_last_two_months_by_default(truth):
    """Not the first published month. That was the defect."""
    published = list(svc.periods())
    f = ff.transitions().figures
    assert f["from_period"] == published[-2]
    assert f["from_period"] != published[0] or len(published) == 2


def test_an_obligor_that_appeared_has_not_deteriorated():
    """Entering the book is not a band change, and is counted apart."""
    f = ff.transitions().figures
    assert "entered_the_book" in f
    assert "left_the_book" in f
    assert f["obligors_in_both"] + f["left_the_book"] \
        == len(svc.borrower_month(f["from_period"]))


def test_one_published_month_yields_a_limitation_rather_than_a_number():
    only = svc.periods()[0]
    f = ff.transitions(only, only).figures
    assert f["single_period"] is True
    assert f["changed"] == 0


def test_an_unpublished_month_is_refused():
    with pytest.raises(KeyError):
        ff.transitions("1999-01", svc.latest_period())


# -------------------------------------------------------- the drill-down


def test_a_from_to_pair_narrows_the_rows_and_not_the_counts(truth):
    if not truth["changed"]:
        pytest.skip("No band changed between the last two months.")
    example = truth["changed"][0]
    pack = ff.transitions(from_band=example["from"], to_band=example["to"])
    assert pack.figures["changed"] == len(truth["changed"])
    assert pack.figures["drilled"] <= pack.figures["changed"]
    assert all(r["from_band"] == example["from"]
               and r["to_band"] == example["to"] for r in pack.rows)


def test_high_plus_is_read_as_the_pair_and_not_as_one_band(truth):
    pack = ff.transitions(to_band="HIGH_PLUS")
    assert pack.figures["drilled"] == len(truth["into"])
    assert {r["customer_id"] for r in pack.rows} \
        <= {m["customer_id"] for m in truth["into"]}


def test_a_move_inside_high_plus_has_not_left_it():
    """HIGH to VERY_HIGH deteriorated; it did not come out of the set."""
    pack = ff.transitions(from_band="HIGH_PLUS")
    for row in pack.rows:
        assert row["to_band"] not in HIGH_PLUS


def test_an_unknown_band_is_refused_rather_than_ignored():
    with pytest.raises(KeyError):
        ff.transitions(to_band="CATASTROPHIC")


# ------------------------------------------------------------ the roll-up


def test_grouping_rolls_the_same_moves_up_one_level(truth):
    pack = ff.transitions(group_by="sector")
    rows = pack.figures["group_rows"]
    assert sum(r["obligors"] for r in rows) == pack.figures["obligors_in_both"]
    assert sum(r["deteriorated"] for r in rows) == pack.figures["deteriorated"]
    assert sum(r["improved"] for r in rows) == pack.figures["improved"]


def test_the_worst_group_is_the_one_with_the_most_adverse_moves(truth):
    pack = ff.transitions(group_by="sector")
    rows = pack.figures["group_rows"]
    if not any(r["deteriorated"] for r in rows):
        pytest.skip("Nothing deteriorated between the last two months.")
    assert rows[0]["deteriorated"] == max(r["deteriorated"] for r in rows)
    assert pack.figures["worst_group"] == rows[0]["sector"]


def test_an_ungroupable_level_is_refused():
    with pytest.raises(ff.UnsupportedLevel):
        ff.transitions(group_by="customer_name")


# -------------------------------------------------- reading the sentence


@pytest.mark.parametrize("question", [
    "How many obligors changed risk band in the latest month?",
    "Who moved into High or Very High this month?",
    "Who improved out of High or Very High?",
    "Show the latest band-transition matrix.",
    "Which sectors had the most adverse band migrations?",
    "Did any Contracting obligors move into High or Very High this month?",
    "How many names were downgraded a band?",
    "Which obligors were upgraded since last month?",
    "band migration this month",
])
def test_these_are_all_read_as_band_transitions(question):
    read = norm.read(norm.clean(question))
    assert read.requested_analyses[0] == "transition" \
        or "transition" in read.requested_analyses, question


@pytest.mark.parametrize("question", [
    "Has Contracting deteriorated over the last six months?",
    "Which obligors are High or Very High?",
    "Show me 10 out of 300 names.",
    "How has the portfolio score moved since last year?",
])
def test_these_are_not_band_transitions(question):
    read = norm.read(norm.clean(question))
    assert "transition" not in read.requested_analyses, question


def test_the_endpoints_are_not_read_as_a_population_filter():
    """"from High to Very High" names two ends of a move, not a slice."""
    read = norm.read(norm.clean("Which obligors moved from High to Very High?"))
    assert read.inherited_context["band_move"] == {
        "from_band": "HIGH", "to_band": "VERY_HIGH"}
    assert "band" not in read.inherited_context
    assert "ews_band" not in read.inherited_context


def test_a_question_that_asks_both_ways_gets_no_direction():
    read = norm.read(norm.clean(
        "How many obligors were upgraded and how many downgraded last month?"))
    move = read.inherited_context.get("band_move") or {}
    assert "direction" not in move


def test_into_high_or_very_high_is_the_pair():
    read = norm.read(norm.clean("Who moved into High or Very High this month?"))
    assert read.inherited_context["band_move"]["to_band"] == "HIGH_PLUS"


# --------------------------------------------------------------- the plan


class _Request:
    def __init__(self, **kw):
        self.requested_analysis = kw.get("analysis", "")
        self.requested_analyses = kw.get("analyses", [])
        self.requested_scope = kw.get("scope", "portfolio")
        self.requested_grouping = kw.get("grouping", "")
        self.requested_layer = ""
        self.requested_period = ""
        self.comparison_period = kw.get("comparison", "")
        self.inherited_context = kw.get("inherited", {})


@pytest.fixture(scope="module")
def package():
    from backend.early_warning import grain as grain_mod

    return grain_mod.build("")


def test_the_plan_compares_the_previous_published_month(package):
    plan = plan_mod.build(_Request(analyses=["transition"]), package)
    step = plan.steps[0]
    assert step.analysis == plan_mod.TRANSITION
    assert step.period == package.current_period
    assert step.comparison_period == package.periods[-2]
    assert plan.intent == "transition"


def test_a_transition_asked_by_sector_carries_the_grouping(package):
    plan = plan_mod.build(
        _Request(analyses=["transition", "grouping"], grouping="sector"),
        package)
    assert plan.steps[0].analysis == plan_mod.TRANSITION
    assert plan.steps[0].group_by == "sector"


def test_a_transition_step_names_a_month_to_compare_against(package):
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.TRANSITION, period=package.current_period,
        measures=["ews_band"])])
    result = val_mod.check(plan, package)
    assert any(f.code == "missing_comparison" for f in result.failures)


def test_the_validator_refuses_a_band_that_does_not_exist(package):
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.TRANSITION, period=package.current_period,
        comparison_period=package.periods[-2], to_band="CATASTROPHIC",
        measures=["ews_band"])])
    result = val_mod.check(plan, package)
    assert any(f.code == "unknown_band" for f in result.failures)


def test_the_validator_refuses_a_direction_that_is_not_one(package):
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.TRANSITION, period=package.current_period,
        comparison_period=package.periods[-2], direction="sideways",
        measures=["ews_band"])])
    result = val_mod.check(plan, package)
    assert any(f.code == "unknown_direction" for f in result.failures)


# ------------------------------------------------------------ the reading


def test_the_reading_states_both_months(truth):
    written = cp.compose(ff.transitions())
    assert truth["from_period"] in written.direct
    assert truth["to_period"] in written.direct


def test_the_reading_leads_with_a_count_of_names(truth):
    written = cp.compose(ff.transitions())
    assert str(len(truth["changed"])) in written.direct \
        or "No obligor changed" in written.direct


def test_the_matrix_reading_shows_every_cell_that_moved():
    pack = ff.transitions()
    written = cp.compose(pack)
    joined = " ".join(written.points).lower()
    for cell in pack.figures["matrix"]:
        if cell["from_band"] == cell["to_band"]:
            continue
        assert cell["from_band"].replace("_", " ").lower() in joined
        assert cell["to_band"].replace("_", " ").lower() in joined


def test_a_crossing_that_did_not_happen_is_said_plainly(truth):
    if truth["into"]:
        pytest.skip("Something did cross into high this month.")
    written = cp.compose(ff.transitions(to_band="HIGH_PLUS",
                                        direction="deteriorated"))
    text = f"{written.direct} {written.interpretation}".lower()
    assert "none of them matches" in text or "no name" in text
    assert "high or very high" in text


def test_the_grouped_reading_answers_at_the_group_level():
    written = cp.compose(ff.transitions(group_by="sector"))
    assert "sector" in f"{written.direct} {written.interpretation}".lower()


def test_a_single_published_month_says_so_rather_than_reporting_zero():
    only = svc.periods()[0]
    written = cp.compose(ff.transitions(only, only))
    assert "only one published month" in written.direct.lower()
