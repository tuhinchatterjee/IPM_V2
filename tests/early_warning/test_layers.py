"""
Does the product understand a question that names a detection layer?

The defect this file exists to close
------------------------------------
"Which obligors currently carry external-intelligence warning signals?" was
answered with the ten largest high-risk names in the book. Nothing about the
answer looked wrong — the figures reconciled, the names were real, the prose
was careful — and it was an answer to a question about SEVERITY put to a
question about WHERE THE RISK WAS DETECTED. Only someone who remembered what
they typed could tell.

So the tests here come in two halves. The first asks whether a phrase resolves
to a layer, and deliberately includes spellings nobody wrote the code against:
if the resolver only knows the sentences in the specification then the next
reader phrases it differently and is back where they started. The second asks
whether resolving it CHANGES THE ANSWER — the population, the ranking measure
and the prose — because a layer that is understood and then ignored is the
same defect with a longer trace.
"""

from __future__ import annotations

import json

import pytest

from backend.early_warning import compose as cp
from backend.early_warning import dictionary as dic
from backend.early_warning import executable as ex
from backend.early_warning import facts as ff
from backend.early_warning import layers as lay
from backend.early_warning import v2_service as svc
from backend.early_warning import wide
from backend.early_warning.conversation import normalise as norm
from backend.early_warning.conversation import plan as plan_mod
from backend.early_warning.conversation import validate as val_mod


# ------------------------------------------------------------ the registry


def test_there_are_four_layers_and_each_is_complete():
    assert [entry.code for entry in lay.LAYERS] == ["L1", "L2", "L3", "L4"]
    for entry in lay.LAYERS:
        assert entry.name and entry.short
        assert entry.ta_key in wide.LAYER_KEYS
        assert entry.active_field == f"{entry.code.lower()}_active"
        assert entry.nodes, f"{entry.code} has no sub-category nodes"


def test_the_registry_is_the_only_copy_of_the_layer_names():
    """`facts` and the API router used to hold their own literals."""
    assert ff.LAYER_NAMES == {code: lay.described(code) for code in lay.CODES}

    from backend.api.routers import early_warning_v2 as router
    import inspect

    source = inspect.getsource(router)
    assert "External Intelligence\"}" not in source
    assert "ews_layers.LAYERS" in source


def test_every_derived_field_is_in_the_dictionary():
    known = dic.names()
    for name in lay.DERIVED_FIELDS:
        assert name in known, f"{name} is derived and undescribed"


# ------------------------------------------------------------- resolution


@pytest.mark.parametrize("phrase", [
    "Which obligors currently carry external-intelligence warning signals?",
    "Which obligors have external intelligence signals?",
    "Show me High and Very High obligors with external signals.",
    "Which borrowers have L3 warnings but weak internal corroboration?",
    "What external warning events are driving this borrower?",
    "Which obligors have external events?",
    "any external alerts this month?",
    "external-intelligence flags",
    "Layer 3",
    "layer 3 readings",
    "show me the L3 score",
])
def test_these_all_name_layer_three(phrase):
    assert lay.resolve(phrase) == "L3", phrase


@pytest.mark.parametrize("phrase,code", [
    ("behavioural signals", "L1"),
    ("internal behaviour", "L1"),
    ("layer 1", "L1"),
    ("credit and financial fundamentals", "L2"),
    ("fundamentals deteriorating? show the triggers", "L2"),
    ("L2", "L2"),
    ("network contagion", "L4"),
    ("graph intelligence", "L4"),
    ("supply chain", "L4"),
    ("layer 4", "L4"),
])
def test_the_other_three_resolve_too(phrase, code):
    assert lay.resolve(phrase) == code, phrase


@pytest.mark.parametrize("phrase", [
    "What is the bank share of external debt?",
    "Which obligors are High or Very High?",
    "Show exposure by sector.",
    "What is the current Early Warning distribution by risk band?",
    "group by relationship manager",
    "Who is the external auditor?",
    "",
])
def test_these_name_no_layer(phrase):
    """A resolver that fires on "external debt" is worse than none: it
    silently narrows the population and says it did not."""
    assert lay.resolve(phrase) == "", phrase


def test_a_node_name_names_its_own_layer():
    assert lay.resolve("show me legal and distress events") == "L3"
    assert lay.resolve("payment performance issues") == "L1"


def test_the_code_outranks_everything_else():
    """"Layer 3 external intelligence" says one thing twice."""
    hit = lay.find("layer 3 external intelligence signals")
    assert hit is not None
    assert hit.code == "L3"
    assert hit.how == "code"


def test_hyphens_and_ampersands_do_not_change_the_answer():
    assert lay.resolve("external-intelligence signals") == "L3"
    assert lay.resolve("graph & relationship intelligence") == "L4"
    assert lay.resolve("external   intelligence   signals") == "L3"


def test_a_warning_noun_too_far_away_does_not_count():
    """The rule is a phrase, not a co-occurrence anywhere in the sentence."""
    assert lay.resolve(
        "external debt has been rising for several quarters and the "
        "committee wants a reading") == ""


# ------------------------------------------------------- derived activity


def test_activity_reads_the_trigger_side_only():
    rows = [{"l1_ta": 0.0, "l2_ta": 0.0, "l2_c": 90.0, "l3_ta": 4.0},
            {"l1_ta": 2.0, "l3_ta": 1.0},
            {}]
    got = lay.activity(rows)
    assert got["l3_active"] == [True, True, False]
    # L2's classifier score is above zero for the whole book; a flag that
    # read it would say every obligor carries fundamentals warnings.
    assert got["l2_active"] == [False, False, False]
    assert got[lay.FIRING_COUNT_FIELD] == [1, 2, 0]
    assert got[lay.CORROBORATED_FIELD] == [False, True, False]


def test_activity_survives_a_broken_row():
    got = lay.activity([None, {"l3_ta": "not a number"}])
    assert got["l3_active"] == [False, False]


def test_the_alias_map_knows_the_layer_measures():
    assert ex.normalise("l3 score") == "l3_ta"
    assert ex.normalise("L3 signals") == "l3_active"
    assert ex.supports("l3_active", role=ex.FILTER)
    assert ex.supports("l3_ta", role=ex.MEASURE)


# -------------------------------------------------------------- the plan


class _Request:
    def __init__(self, **kw):
        self.requested_analysis = kw.get("analysis", "")
        self.requested_analyses = kw.get("analyses", [])
        self.requested_scope = kw.get("scope", "portfolio")
        self.requested_grouping = kw.get("grouping", "")
        self.requested_layer = kw.get("layer", "")
        self.requested_period = ""
        self.comparison_period = ""
        self.inherited_context = kw.get("inherited", {})


@pytest.fixture(scope="module")
def package():
    from backend.early_warning import grain as grain_mod

    try:
        return grain_mod.build("")
    except Exception:  # noqa: BLE001
        pytest.skip("The Early Warning domain is not built.")


def test_a_layer_question_narrows_the_population(package):
    plan = plan_mod.build(
        _Request(analyses=["ranking"], layer="L3"), package)
    population = next(s for s in plan.steps
                      if s.analysis == plan_mod.POPULATION)
    assert population.filters.get("l3_active") is True
    ranking = next(s for s in plan.steps if s.analysis == plan_mod.RANKING)
    assert ranking.order_by == "l3_ta"
    # Not narrowed to high-or-above: an obligor can carry a live external
    # event and sit at LOW overall, and that obligor is the one being asked
    # after.
    assert "high_plus" not in ranking.filters


def test_a_layer_grouping_is_ranked_on_the_layer(package):
    plan = plan_mod.build(
        _Request(analyses=["grouping"], grouping="sector", layer="L3"),
        package)
    step = next(s for s in plan.steps if s.analysis == plan_mod.GROUPING)
    assert step.group_by == "sector"
    assert step.layer == "L3"
    assert step.order_by == "l3_ta"


def test_a_layer_question_about_one_obligor_opens_the_layer(package):
    plan = plan_mod.build(
        _Request(scope="borrower", layer="L3",
                 inherited={"customer_id": "CORP-100180"}),
        package)
    assert [s.analysis for s in plan.steps] == [plan_mod.BORROWER,
                                                plan_mod.LAYER]
    assert plan.steps[1].layer == "L3"
    assert plan.intent == "layer"


def test_weak_corroboration_is_half_the_question(package):
    plan = plan_mod.build(
        _Request(analyses=["ranking"], layer="L3",
                 inherited={"layer": "L3", "corroboration": "weak"}),
        package)
    population = next(s for s in plan.steps
                      if s.analysis == plan_mod.POPULATION)
    assert population.filters.get(lay.CORROBORATED_FIELD) is False


def test_the_validator_refuses_a_layer_the_model_does_not_have(package):
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.GROUPING, period=package.current_period,
        group_by="sector", layer="L9", measures=["ews_score"])])
    result = val_mod.check(plan, package)
    assert any(f.code == "unknown_layer" for f in result.failures)


def test_the_validator_refuses_a_layer_reading_with_no_obligor(package):
    plan = plan_mod.Plan(steps=[plan_mod.Step(
        analysis=plan_mod.LAYER, period=package.current_period, layer="L3")])
    result = val_mod.check(plan, package)
    assert any(f.code == "missing_obligor" for f in result.failures)


# ----------------------------------------------------------- the reading


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception:  # noqa: BLE001
        pytest.skip("The Early Warning domain is not built.")


def _independent_l3(period):
    """The same population, recomputed off the raw column.

    Deliberately not through `facts`: a check that shares its code with the
    thing it checks proves the code runs, not that it is right.
    """
    frame = svc.borrower_month(period)
    out = []
    for row in frame.to_dict("records"):
        raw = row.get("layer_dimension_scores")
        scores = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if float(scores.get("l3_ta") or 0.0) > 0.0:
            out.append(row["customer_id"])
    return out


def test_the_layer_population_is_the_layer_population():
    period = svc.latest_period()
    pack = ff.layer_population("L3", period)
    expected = _independent_l3(period)
    assert pack.figures["obligors"] == len(expected)
    assert {r["customer_id"] for r in pack.rows} <= set(expected)
    assert pack.figures["book_obligors"] == len(svc.borrower_month(period))


def test_the_layer_population_counts_corroboration():
    pack = ff.layer_population("L3")
    figures = pack.figures
    assert (figures["corroborated_elsewhere"] + figures["this_layer_alone"]
            == figures["obligors"])


def test_narrowing_to_the_uncorroborated_narrows_the_population():
    everything = ff.layer_population("L3")
    alone = ff.layer_population("L3", only={lay.CORROBORATED_FIELD: False})
    assert alone.figures["obligors"] == everything.figures["this_layer_alone"]
    assert alone.figures["corroborated_elsewhere"] == 0


def test_an_unknown_layer_is_refused_rather_than_guessed():
    with pytest.raises(KeyError):
        ff.layer_population("L9")


def test_the_level_ranking_follows_the_measure_it_was_asked_for():
    by_score = ff.level("sector")
    by_l3 = ff.level("sector", rank_by="l3_ta")
    assert by_score.figures["ranked_by"] == "portfolio_ews"
    assert by_l3.figures["ranked_by"] == "l3"
    # Ordered by the layer, not by the score it rolls into.
    values = [row["l3"] for row in by_l3.rows]
    assert values == sorted(values, reverse=True)


def test_the_layer_reading_names_the_layer_and_not_a_severity_ranking():
    written = cp.compose(ff.layer_population("L3"))
    text = f"{written.direct} {written.interpretation}".lower()
    assert "external intelligence" in text
    # The old answer's shape: "N obligors sit at high or above."
    assert not written.direct.lower().startswith("52 obligors")


def test_the_layer_reading_says_which_month_it_is_of():
    written = cp.compose(ff.layer_population("L3"))
    assert svc.latest_period() in written.direct


def test_an_empty_layer_population_reads_as_a_finding():
    empty = ff.FactPack(
        scope="layer_population", label="obligors carrying x", period="2026-06",
        figures={"layer": "L4", "layer_described": lay.described("L4"),
                 "obligors": 0, "book_obligors": 300},
        rows=[])
    written = cp.compose(empty)
    assert "no obligor" in written.direct.lower()
    assert "empty result" in written.direct.lower() \
        or "not an empty result" in written.direct.lower()


def test_the_borrower_layer_reading_names_the_events():
    period = svc.latest_period()
    candidate = _independent_l3(period)
    if not candidate:
        pytest.skip("No obligor carries an L3 signal this month.")
    written = cp.compose(ff.layer("CORP-100180" if "CORP-100180" in candidate
                                   else candidate[0], "L3"))
    joined = " ".join([written.direct, written.interpretation, *written.points])
    assert "L3." in joined, "no governed node named"
    assert "node" in written.direct


# ------------------------------------------------- reading the sentence


def test_the_reader_records_the_layer_the_question_names():
    read = norm.read(norm.clean(
        "Which obligors currently carry external-intelligence warning signals?"))
    assert read.requested_layer == "L3"
    assert read.inherited_context.get("layer") == "L3"


def test_the_reader_records_weak_corroboration_as_weak():
    read = norm.read(norm.clean(
        "Which borrowers have L3 warnings but weak internal corroboration?"))
    assert read.requested_layer == "L3"
    assert read.inherited_context.get("corroboration") == "weak"


def test_not_corroborated_is_not_read_as_corroborated():
    """The negative contains the positive as a substring."""
    read = norm.read(norm.clean("Show uncorroborated external signals."))
    assert read.inherited_context.get("corroboration") == "weak"


def test_an_ordinary_question_records_no_layer():
    read = norm.read(norm.clean("Which obligors are High or Very High?"))
    assert read.requested_layer == ""
    assert "layer" not in read.inherited_context
