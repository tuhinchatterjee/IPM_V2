"""Ratings, scorecards, sectors and stages: the maps, and the refusals.

UNIT for the arithmetic and the refusals; REAL DATABASE for the half that
reads the published maps through DuckDB. No model, no provider call.

The S-series oracles here:

* **S12** a notch move steps the PUBLISHED scale. Never a string increment,
  never a lexical sort, never a PD multiplier. Scale boundaries, unrated
  obligors and the default grade are each answered explicitly.
* **S13** behavioural and application scorecards are kept apart, and neither
  is substituted for the other. A points move is points, not per cent.
* **S14** stages are frozen by default; an explicit move needs the declared
  horizon contract or reports unsupported; a lifetime figure is never a
  twelve-month figure multiplied by a number of years.
* **S15** sector discovery returns the book's actual categories with counts
  and totals, synonyms resolve to real identifiers, `Unknown` stays in every
  total, and a Retail product is never relabelled an employer sector.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4 import lake
from backend.cockpit_v4.scenario import candidate_schema as cs
from backend.cockpit_v4.scenario import errors as err
from backend.cockpit_v4.scenario import mappings as m
from backend.cockpit_v4.scenario import units
from backend.cockpit_v4.scenario.mappings import ratings, scores, sectors, stages

D = Decimal

#: A masterscale with the shape that breaks a lexical sort: `BB-` must come
#: AFTER `BB+`, and `AA` must be one notch from `A` rather than eight from
#: `B`. Written out rather than read from the release so the oracle is the
#: specification's requirement, not this book's data.
SCALE_ROWS = [
    {"mapping_version": "ms-1", "rating_grade": g, "grade_rank": i + 1,
     "pd_12m": pd, "pd_lifetime": min(pd * 2.6, 1.0), "horizon_months": 12.0,
     "is_default_grade": int(g == "D"),
     "is_investment_grade": int(g in ("AA", "A", "BBB+", "BBB", "BBB-"))}
    for i, (g, pd) in enumerate([
        ("AA", 0.0007), ("A", 0.0014), ("BBB+", 0.0026), ("BBB", 0.0041),
        ("BBB-", 0.0065), ("BB+", 0.0102), ("BB", 0.0161), ("BB-", 0.0254),
        ("B+", 0.0400), ("B", 0.0630), ("CCC", 0.1550), ("D", 1.0)])]


# ==========================================================================
# S12 -- the published scale
# ==========================================================================

def test_s12_one_notch_steps_the_published_order() -> None:
    scale = ratings.scale(SCALE_ROWS)
    moved = scale.notch("BBB", 1)
    assert moved.to_grade.grade == "BBB-"
    assert moved.applied_notches == 1
    assert moved.stopped_at_boundary is False


def test_s12_a_notch_is_never_a_string_increment() -> None:
    """`AA` + 1 is `A`. It is not `AB`, and there is no `AB`."""
    scale = ratings.scale(SCALE_ROWS)
    assert scale.notch("AA", 1).to_grade.grade == "A"
    assert "AB" not in scale.order


def test_s12_a_notch_is_never_a_lexical_sort() -> None:
    """Sorted as text this scale is wrong in two separate places.

    `AA` would step to `B`, eight grades past where it belongs, and `BBB`
    would sort ahead of `BBB+` although it is the weaker of the two. The
    published rank is the order.
    """
    lexical = sorted(g["rating_grade"] for g in SCALE_ROWS)
    assert lexical[lexical.index("AA") + 1] == "B"
    assert lexical.index("BBB") < lexical.index("BBB+")

    scale = ratings.scale(SCALE_ROWS)
    assert scale.order[scale.order.index("AA") + 1] == "A"
    assert scale.order.index("BBB+") < scale.order.index("BBB")
    assert scale.notch("BBB+", 1).to_grade.grade == "BBB"


def test_s12_a_notch_is_never_a_pd_multiplier() -> None:
    """The step between grades is not a constant factor."""
    scale = ratings.scale(SCALE_ROWS)
    first = scale.notch("AA", 1)
    later = scale.notch("B", 1)
    ratio_first = first.to_grade.pd_12m / first.from_grade.pd_12m
    ratio_later = later.to_grade.pd_12m / later.from_grade.pd_12m
    assert abs(ratio_first - ratio_later) > D("0.4")
    # And the published PD is the map's, not a computed one.
    assert later.to_grade.pd_12m == D("0.1550")


def test_s12_several_notches_land_where_the_scale_says() -> None:
    scale = ratings.scale(SCALE_ROWS)
    # BBB -> BBB- -> BB+ -> BB.
    assert scale.notch("BBB", 3).to_grade.grade == "BB"
    # BB -> BB+ -> BBB-.
    assert scale.notch("BB", -2).to_grade.grade == "BBB-"


def test_s12_a_move_past_the_end_says_how_far_it_actually_went() -> None:
    """Clamped, and visibly: three requested, one applied."""
    scale = ratings.scale(SCALE_ROWS)
    moved = scale.notch("AA", -3)
    assert moved.to_grade.grade == "AA"
    assert moved.requested_notches == -3
    assert moved.applied_notches == 0
    assert moved.stopped_at_boundary is True
    assert "strongest grade" in moved.note
    assert "was not applied as a PD change either" in moved.note

    down = scale.notch("CCC", 5)
    assert down.to_grade.grade == "D"
    assert down.applied_notches == 1 and down.requested_notches == 5
    assert "weakest" in down.note


def test_s12_an_unrated_grade_is_refused_with_the_scale_named() -> None:
    scale = ratings.scale(SCALE_ROWS)
    with pytest.raises(err.ScenarioError) as raised:
        scale.notch("NR", 1)
    assert raised.value.code == err.MAPPING_UNAVAILABLE
    assert "is not on the ms-1 scale" in str(raised.value)
    assert "State the PD you want to assume" in str(raised.value)


def test_s12_the_default_grade_has_no_notch_to_move() -> None:
    scale = ratings.scale(SCALE_ROWS)
    with pytest.raises(err.ScenarioError) as raised:
        scale.notch("D", -1)
    assert raised.value.code == err.PARAMETER_OUT_OF_RANGE
    assert "because it has defaulted" in str(raised.value)
    assert "Curing it is a stage decision" in str(raised.value)


def test_s12_half_a_notch_is_not_a_move() -> None:
    scale = ratings.scale(SCALE_ROWS)
    with pytest.raises(err.ScenarioError, match="half-notch"):
        scale.notch("BBB", 1.5)  # type: ignore[arg-type]


def test_a_notch_amount_is_refused_before_it_reaches_the_scale() -> None:
    """`units.Amount` catches it first, which is where it should be caught."""
    with pytest.raises(units.UnitError, match="half-notch"):
        units.parse("1.5", units.NOTCHES)
    assert units.parse("-2", units.NOTCHES).describe() == "-2 notches"


def test_two_mapping_versions_are_two_scales() -> None:
    other = [{**r, "mapping_version": "ms-2"} for r in SCALE_ROWS[:3]]
    with pytest.raises(err.ScenarioError) as raised:
        ratings.scale(SCALE_ROWS + other)
    assert "an order that never existed" in str(raised.value)
    assert ratings.scale(SCALE_ROWS + other, "ms-2").order == (
        "AA", "A", "BBB+")


def test_a_scale_with_two_grades_at_one_rank_is_refused() -> None:
    bad = [dict(SCALE_ROWS[0]), {**SCALE_ROWS[1], "grade_rank": 1}]
    with pytest.raises(err.ScenarioError, match="no single answer"):
        ratings.scale(bad)


def test_a_zero_notch_move_changes_nothing_and_says_so() -> None:
    scale = ratings.scale(SCALE_ROWS)
    still = scale.notch("BBB", 0)
    assert still.to_grade.grade == "BBB"
    assert still.pd_change == 0
    assert still.stopped_at_boundary is False


# ==========================================================================
# S13 -- the two scorecards
# ==========================================================================

def _band(score_type, product, low, high, label, pd, version="v1",
          direction=scores.HIGHER_IS_SAFER, support=(300, 900)):
    return {"score_type": score_type, "scorecard_version": version,
            "product": product, "band_low": low, "band_high": high,
            "band_label": label, "pd_12m": pd, "horizon_months": 12.0,
            "direction": direction, "support_low": support[0],
            "support_high": support[1]}


SCORE_ROWS = [
    _band(m.BEHAVIOURAL, "Personal Loan", 300, 579, "Very high risk", 0.24),
    _band(m.BEHAVIOURAL, "Personal Loan", 580, 669, "High risk", 0.11),
    _band(m.BEHAVIOURAL, "Personal Loan", 670, 739, "Medium risk", 0.045),
    _band(m.BEHAVIOURAL, "Personal Loan", 740, 900, "Low risk", 0.012),
    _band(m.APPLICATION, "Personal Loan", 200, 449, "Decline band", 0.31,
          support=(200, 800)),
    _band(m.APPLICATION, "Personal Loan", 450, 649, "Refer band", 0.14,
          support=(200, 800)),
    _band(m.APPLICATION, "Personal Loan", 650, 800, "Accept band", 0.035,
          support=(200, 800)),
]


def test_s13_the_two_cards_are_separate_objects_with_separate_ranges() -> None:
    lib = scores.library(SCORE_ROWS)
    behavioural = lib.card(score_type=m.BEHAVIOURAL, product="Personal Loan")
    application = lib.card(score_type=m.APPLICATION, product="Personal Loan")
    assert behavioural is not application
    assert (behavioural.support_low, behavioural.support_high) == (300, 900)
    assert (application.support_low, application.support_high) == (200, 800)


def test_s13_one_score_means_two_different_things_on_the_two_cards() -> None:
    """650 is medium risk behaviourally and the accept band at origination."""
    lib = scores.library(SCORE_ROWS)
    behavioural = lib.card(score_type=m.BEHAVIOURAL, product="Personal Loan")
    application = lib.card(score_type=m.APPLICATION, product="Personal Loan")
    assert behavioural.band_for(D(650)).label == "High risk"
    assert application.band_for(D(650)).label == "Accept band"
    assert behavioural.pd_for(D(650)) != application.pd_for(D(650))


def test_s13_a_missing_card_is_refused_not_substituted() -> None:
    lib = scores.library([r for r in SCORE_ROWS
                          if r["score_type"] == m.BEHAVIOURAL])
    with pytest.raises(err.ScenarioError) as raised:
        lib.card(score_type=m.APPLICATION, product="Personal Loan")
    assert raised.value.code == err.MAPPING_UNAVAILABLE
    assert "not a substitute for this one" in str(raised.value)
    assert m.BEHAVIOURAL in str(raised.value)


def test_a_cross_product_card_is_used_for_a_product_and_says_which() -> None:
    """A card published for the whole book covers every product in it.

    It is not another product's calibration, and the returned card still
    reads `ALL`, so an answer reports what it priced through.
    """
    lib = scores.library(SCORE_ROWS + [
        _band(m.APPLICATION, scores.ANY_PRODUCT, 200, 800, "Book-wide", 0.09,
              version="v2", support=(200, 800))])
    card = lib.card(score_type=m.APPLICATION, product="Auto Lease")
    assert card.product == scores.ANY_PRODUCT
    assert card.scorecard_version == "v2"
    # And a product that HAS its own card still gets its own.
    own = lib.card(score_type=m.APPLICATION, product="Personal Loan")
    assert own.product == "Personal Loan"
    assert own.scorecard_version == "v1"


def test_s13_a_missing_product_is_refused_with_the_real_products() -> None:
    lib = scores.library(SCORE_ROWS)
    with pytest.raises(err.ScenarioError) as raised:
        lib.card(score_type=m.BEHAVIOURAL, product="Auto Lease")
    assert "Personal Loan" in str(raised.value)
    assert "Another product's calibration is not this product's" \
        in str(raised.value)


def test_s13_a_score_type_that_is_not_one_is_refused() -> None:
    lib = scores.library(SCORE_ROWS)
    with pytest.raises(err.ScenarioError,
                       match="two names for one"):
        lib.card(score_type="CREDIT_SCORE", product="Personal Loan")


def test_s13_fifty_points_is_fifty_points_not_fifty_per_cent() -> None:
    """650 minus 50 points is 600. Read as a relative move it is 325."""
    points = units.apply(D("650"),
                         units.parse("-50", units.POINTS, "drop 50 points"),
                         storage=units.INDEX)
    assert points == D("600")

    lib = scores.library(SCORE_ROWS)
    card = lib.card(score_type=m.BEHAVIOURAL, product="Personal Loan")
    moved = card.moved(D("650"), points)
    assert moved["score_change_points"] == "-50"
    assert moved["band_baseline"] == "High risk"
    assert moved["band_scenario"] == "High risk"
    assert moved["band_changed"] is False
    # And the relative reading lands in a different band entirely.
    assert card.band_for(D("325")).label == "Very high risk"


def test_s13_a_band_change_reports_both_pds_and_the_move() -> None:
    lib = scores.library(SCORE_ROWS)
    card = lib.card(score_type=m.BEHAVIOURAL, product="Personal Loan")
    moved = card.moved(D("700"), D("600"))
    assert moved["band_baseline"] == "Medium risk"
    assert moved["band_scenario"] == "High risk"
    assert moved["band_changed"] is True
    assert moved["pd_baseline"] == "0.045"
    assert moved["pd_scenario"] == "0.11"
    assert moved["pd_change_pp"].startswith("6.5")


def test_s13_a_score_outside_the_cards_range_is_refused() -> None:
    lib = scores.library(SCORE_ROWS)
    card = lib.card(score_type=m.BEHAVIOURAL, product="Personal Loan")
    with pytest.raises(err.ScenarioError) as raised:
        card.band_for(D("950"))
    assert raised.value.code == err.PARAMETER_OUT_OF_RANGE
    assert "not the top band" in str(raised.value)


def test_s13_the_direction_is_read_from_the_card_not_assumed() -> None:
    lib = scores.library(SCORE_ROWS)
    assert lib.card(score_type=m.BEHAVIOURAL,
                    product="Personal Loan").safer_is_up is True
    inverted = scores.library(
        [{**r, "direction": scores.LOWER_IS_SAFER} for r in SCORE_ROWS])
    assert inverted.card(score_type=m.BEHAVIOURAL,
                         product="Personal Loan").safer_is_up is False


def test_a_card_with_two_directions_is_refused() -> None:
    mixed = [SCORE_ROWS[0], {**SCORE_ROWS[1],
                             "direction": scores.LOWER_IS_SAFER}]
    with pytest.raises(err.ScenarioError, match="is not assumed here"):
        scores.library(mixed)


def test_a_gap_in_the_band_table_is_not_filled_by_a_neighbour() -> None:
    holed = [r for r in SCORE_ROWS
             if not (r["score_type"] == m.BEHAVIOURAL
                     and r["band_label"] == "Medium risk")]
    card = scores.library(holed).card(score_type=m.BEHAVIOURAL,
                                      product="Personal Loan")
    with pytest.raises(err.ScenarioError, match="gap in it"):
        card.band_for(D("700"))


# ==========================================================================
# S15 -- sectors, and the category nobody wants
# ==========================================================================

def _exposure(fid, sector, ead, ecl):
    return {"facility_id": fid, "sector": sector, "ead_sar_mn": ead,
            "ecl_sar_mn": ecl}


BOOK = [
    _exposure("F1", "Construction", 100.0, 8.0),
    _exposure("F2", "Construction", 200.0, 12.0),
    _exposure("F3", "Real Estate", 300.0, 9.0),
    _exposure("F4", "Energy", 400.0, 4.0),
    _exposure("F5", "", 50.0, 3.0),
    _exposure("F6", None, 25.0, 1.5),
]


def test_s15_discovery_returns_actual_categories_with_counts_and_totals():
    book = sectors.discover(BOOK, dimension="sector",
                            entity_key="facility_id")
    assert set(book.values) == {"Construction", "Real Estate", "Energy",
                                m.UNKNOWN}
    construction = book.of("Construction")
    assert construction.entities == 2
    assert construction.ead == D("300.0")
    assert construction.ecl == D("20.0")
    assert round(float(construction.coverage_pct), 4) == 6.6667


def test_s15_a_blank_category_becomes_unknown_rather_than_vanishing():
    book = sectors.discover(BOOK, dimension="sector",
                            entity_key="facility_id")
    unknown = book.of(m.UNKNOWN)
    assert unknown.entities == 2
    assert unknown.ecl == D("4.5")
    assert unknown.is_residual is True


def test_s15_the_parts_add_up_to_the_book_only_with_unknown_in() -> None:
    """Dropping it leaves totals that still balance among themselves."""
    book = sectors.discover(BOOK, dimension="sector",
                            entity_key="facility_id")
    assert book.reconciles(entities=6, ecl=37.5)

    without = sectors.Dictionary(
        dimension="sector",
        categories=tuple(c for c in book.categories if not c.is_residual))
    assert without.reconciles(entities=6, ecl=37.5) is False
    assert without.totals()["ecl"] == pytest.approx(33.0)


def test_s15_unknown_sorts_last_however_large_it_is() -> None:
    """A reader scanning the list should not read `Unknown` as a sector."""
    heavy = BOOK + [_exposure("F7", "", 900.0, 90.0)]
    book = sectors.discover(heavy, dimension="sector",
                            entity_key="facility_id")
    assert book.values[-1] == m.UNKNOWN
    assert book.of(m.UNKNOWN).ecl == D("94.5")


def test_s15_synonyms_resolve_to_the_books_own_identifier() -> None:
    book = sectors.discover(BOOK, dimension="sector",
                            entity_key="facility_id")
    for spelling in ("real estate", "Real Estate", "REAL ESTATE", "property",
                     "  real   estate ", "realestate"):
        assert book.resolve(spelling) == "Real Estate"


def test_s15_a_word_the_book_does_not_have_is_refused_not_approximated():
    book = sectors.discover(BOOK, dimension="sector",
                            entity_key="facility_id")
    with pytest.raises(err.ScenarioError) as raised:
        book.resolve("Aviation")
    assert raised.value.code == err.MAPPING_UNAVAILABLE
    assert "Construction" in str(raised.value)
    assert "worse than a question" in str(raised.value)


def test_s15_a_retail_product_is_not_an_employer_sector() -> None:
    assert sectors.require_dimension("retail", "employer_sector") == \
        "employer_sector"
    assert sectors.require_dimension("retail", "product") == "product"
    with pytest.raises(err.ScenarioError) as raised:
        sectors.require_dimension("retail", "sector")
    assert "where a customer WORKS" in str(raised.value)
    assert "neither is a substitute for the other" in str(raised.value)


def test_a_corporate_dimension_is_not_a_retail_one() -> None:
    assert sectors.require_dimension("corporate", "sector") == "sector"
    with pytest.raises(err.ScenarioError, match="not a dimension"):
        sectors.require_dimension("corporate", "employer_sector")


def test_s15_an_other_bucket_keeps_the_total_whole() -> None:
    book = sectors.discover(BOOK, dimension="sector",
                            entity_key="facility_id")
    head, other = sectors.keep_residuals(book.categories, top=2)
    assert len(head) == 2
    assert other is not None
    assert other.entities + sum(c.entities for c in head) == 6
    assert float(other.ecl) + sum(float(c.ecl) for c in head) == \
        pytest.approx(37.5)


def test_keeping_everything_produces_no_other_row() -> None:
    book = sectors.discover(BOOK, dimension="sector",
                            entity_key="facility_id")
    head, other = sectors.keep_residuals(book.categories, top=99)
    assert other is None and len(head) == 4


def test_a_zero_exposure_category_has_no_coverage_rate_rather_than_infinity():
    book = sectors.discover([_exposure("F1", "Construction", 0.0, 0.0)],
                            dimension="sector", entity_key="facility_id")
    assert book.of("Construction").coverage_pct is None


# ==========================================================================
# S14 -- stages
# ==========================================================================

def _row(stage=1, lifetime=48.0, maturity=36.0, ecl12=2.0, ecl_life=7.5):
    return {"facility_id": "F1", "stage": stage, "ecl_12m_sar_mn": ecl12,
            "ecl_lifetime_sar_mn": ecl_life,
            "lifetime_horizon_months": lifetime,
            "remaining_maturity_months": maturity}


def test_s14_stages_are_frozen_by_default_and_a_move_is_refused() -> None:
    with pytest.raises(err.ScenarioError) as raised:
        stages.move(_row(), entity_key="facility_id", to_stage=2)
    assert raised.value.code == err.PARAMETER_OUT_OF_RANGE
    assert "holds stages frozen" in str(raised.value)
    assert "stage_policy=explicit" in str(raised.value)


def test_s14_an_explicit_move_with_the_contract_uses_the_published_figures():
    moved = stages.move(_row(), entity_key="facility_id", to_stage=2,
                        policy=stages.EXPLICIT)
    assert moved.supported
    assert moved.ecl_baseline == D("2.0")
    assert moved.ecl_scenario == D("7.5")
    assert moved.change == D("5.5")
    assert "declared 48-month horizon" in moved.reason


def test_s14_a_move_without_the_contract_reports_unsupported_not_zero():
    bare = _row(lifetime=0.0)
    del bare["ecl_lifetime_sar_mn"]
    moved = stages.move(bare, entity_key="facility_id", to_stage=2,
                        policy=stages.EXPLICIT)
    assert moved.status == stages.UNSUPPORTED
    assert moved.ecl_scenario == moved.ecl_baseline
    assert "a published lifetime ECL" in moved.reason
    assert "a declared lifetime horizon in months" in moved.reason
    assert "not approximated from the twelve-month figure" in moved.reason


def test_s14_a_lifetime_figure_is_never_the_annual_one_times_the_years():
    with pytest.raises(err.ScenarioError) as raised:
        stages.never_multiply(ecl_12m=D("2.0"), years=D("3"))
    assert raised.value.code == err.METHOD_COVERAGE_GAP
    assert "ignores survival" in str(raised.value)
    assert "ignores discounting" in str(raised.value)
    assert "flat PD term structure" in str(raised.value)


def test_s14_the_shortcut_and_the_published_figure_disagree_materially():
    """2.0 x 3 years is 6.0; the book publishes 7.5. Neither is the other."""
    row = _row()
    naive = D(str(row["ecl_12m_sar_mn"])) * D("3")
    published = D(str(row["ecl_lifetime_sar_mn"]))
    assert naive != published
    assert abs(naive - published) / published > D("0.15")


def test_s14_a_move_to_the_same_stage_is_a_no_change_not_a_refusal() -> None:
    moved = stages.move(_row(stage=2), entity_key="facility_id", to_stage=2,
                        policy=stages.EXPLICIT)
    assert moved.supported and moved.change == 0
    assert "already in this stage" in moved.reason


def test_s14_a_stage_that_is_not_a_stage_is_refused() -> None:
    with pytest.raises(err.ScenarioError, match="is not a stage"):
        stages.move(_row(), entity_key="facility_id", to_stage=4,
                    policy=stages.EXPLICIT)


def test_s14_an_unknown_stage_policy_is_refused() -> None:
    with pytest.raises(err.ScenarioError, match="not a stage policy"):
        stages.require_policy("whatever_the_reader_meant")


def test_s14_unsupported_rows_are_counted_separately_from_unchanged_ones():
    bare = _row(lifetime=0.0)
    del bare["ecl_lifetime_sar_mn"]
    moves = [
        stages.move(_row(), entity_key="facility_id", to_stage=2,
                    policy=stages.EXPLICIT),
        stages.move(_row(stage=2), entity_key="facility_id", to_stage=2,
                    policy=stages.EXPLICIT),
        stages.move(bare, entity_key="facility_id", to_stage=2,
                    policy=stages.EXPLICIT),
    ]
    got = stages.summarise(moves)
    assert got["exposures"] == 3
    assert got["moved"] == 1
    assert got["unchanged"] == 1
    assert got["unsupported"] == 1
    assert got["unsupported_reasons"]
    assert got["ecl_change"] == D("5.5")


# ==========================================================================
# The published maps, through the real runtime
# ==========================================================================

@pytest.fixture(scope="module")
def _published():
    from backend.cockpit_v4 import analytical_runtime as arun

    if not pathlib.Path("data/cockpit_v4_lake").exists():
        pytest.skip("the published lake is not present in this worktree")
    missing = [r for r in cs.RELEASES.values() if not lake.exists(r)]
    if missing:
        pytest.skip(f"candidate release(s) {missing} are not published; "
                    f"run scripts/whatif/seed_candidate.py")
    arun.reset()
    yield
    arun.reset()


@pytest.fixture()
def enabled(monkeypatch):
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4.scenario import flags as fl

    for variable in fl.VARIABLES.values():
        monkeypatch.setenv(variable, "1")
    arun.reset()
    yield
    arun.reset()


def _rows(domain_id, sql):
    from backend.cockpit_v4 import analytical_runtime as arun

    connection = arun.for_domain(domain_id).session.connection
    columns = [d[0] for d in connection.execute(
        f"SELECT * FROM ({sql}) LIMIT 0").description]
    return [dict(zip(columns, r, strict=True))
            for r in connection.execute(sql).fetchall()]


@pytest.mark.usefixtures("_published")
def test_the_published_corporate_scale_is_the_one_the_book_uses(enabled):
    """Every grade an exposure carries is a grade the map publishes."""
    scale = ratings.scale(_rows(dom.CORPORATE,
                                "SELECT * FROM whatif_corp_rating_map"))
    assert scale.default_grade is not None
    assert scale.default_grade.grade == "D"
    assert scale.default_grade.pd_12m == D("1.0")

    used = {r["rating_current"] for r in _rows(
        dom.CORPORATE,
        "SELECT DISTINCT rating_current FROM corp_borrower_quarter")}
    assert used
    assert used <= set(scale.order)


@pytest.mark.usefixtures("_published")
def test_the_published_scale_is_monotonic_in_pd(enabled) -> None:
    """A weaker grade must not price better than a stronger one."""
    scale = ratings.scale(_rows(dom.CORPORATE,
                                "SELECT * FROM whatif_corp_rating_map"))
    pds = [g.pd_12m for g in scale.grades]
    assert pds == sorted(pds)
    assert scale.order[0] != scale.order[-1]


@pytest.mark.usefixtures("_published")
def test_the_published_retail_cards_are_two_cards_not_one(enabled) -> None:
    """S13 on the real release: separate types, separate versions, separate
    ranges."""
    lib = scores.library(_rows(dom.RETAIL,
                               "SELECT * FROM whatif_retail_score_map"))
    assert set(lib.score_types) == {m.APPLICATION, m.BEHAVIOURAL}
    for product in lib.products(m.BEHAVIOURAL):
        behavioural = lib.card(score_type=m.BEHAVIOURAL, product=product)
        application = lib.card(score_type=m.APPLICATION, product=product)
        assert behavioural.scorecard_version != application.scorecard_version
        assert (behavioural.support_low, behavioural.support_high) != (
            application.support_low, application.support_high)
        # The behavioural card is this product's; the application card is
        # the book's, and says so rather than claiming to be this
        # product's.
        assert behavioural.product == product
        assert application.product == scores.ANY_PRODUCT


@pytest.mark.usefixtures("_published")
def test_a_published_behavioural_score_prices_through_its_own_card(enabled):
    lib = scores.library(_rows(dom.RETAIL,
                               "SELECT * FROM whatif_retail_score_map"))
    sample = _rows(dom.RETAIL,
                   "SELECT product, behaviour_score FROM retail_account_month "
                   "WHERE behaviour_score IS NOT NULL LIMIT 50")
    assert sample
    for row in sample:
        card = lib.card(score_type=m.BEHAVIOURAL, product=row["product"])
        assert card.pd_for(D(str(round(float(row["behaviour_score"]))))) > 0


@pytest.mark.usefixtures("_published")
def test_the_retail_book_keeps_product_and_employer_sector_apart(enabled):
    """S15 on the real release: two columns, two value sets, two sizes."""
    products = {r["product"] for r in _rows(
        dom.RETAIL, "SELECT DISTINCT product FROM retail_account_month")}
    employers = {r["employer_sector"] for r in _rows(
        dom.RETAIL,
        "SELECT DISTINCT employer_sector FROM whatif_retail_profile")}
    assert products and employers
    assert not (products & employers)
    assert len(employers) != len(products)


@pytest.mark.usefixtures("_published")
def test_sector_discovery_on_the_real_book_reconciles_to_it(enabled) -> None:
    latest = _rows(dom.CORPORATE,
                   "SELECT max(reporting_quarter) AS q "
                   "FROM corp_facility_quarter")[0]["q"]
    rows = _rows(dom.CORPORATE,
                 f"SELECT facility_id, sector, ead_sar_mn, ecl_sar_mn "
                 f"FROM corp_facility_quarter "
                 f"WHERE reporting_quarter = '{latest}'")
    book = sectors.discover(rows, dimension="sector",
                            entity_key="facility_id")
    total = _rows(dom.CORPORATE,
                  f"SELECT count(*) AS n, sum(ecl_sar_mn) AS ecl "
                  f"FROM corp_facility_quarter "
                  f"WHERE reporting_quarter = '{latest}'")[0]
    assert book.reconciles(entities=int(total["n"]),
                           ecl=float(total["ecl"]), tolerance=1e-4)
    assert len(book.categories) >= 5


@pytest.mark.usefixtures("_published")
def test_a_stage_move_on_the_real_book_uses_its_published_lifetime(enabled):
    latest = _rows(dom.CORPORATE,
                   "SELECT max(reporting_quarter) AS q "
                   "FROM whatif_corp_ifrs9")[0]["q"]
    rows = _rows(dom.CORPORATE, f"""
        SELECT f.facility_id, f.stage, f.ecl_12m_sar_mn,
               f.ecl_lifetime_sar_mn, i.lifetime_horizon_months,
               i.remaining_maturity_months
        FROM corp_facility_quarter f
        JOIN whatif_corp_ifrs9 i USING (facility_id, reporting_quarter)
        WHERE f.reporting_quarter = '{latest}' AND f.stage = 1
        LIMIT 40""")
    assert rows
    moves = [stages.move(r, entity_key="facility_id", to_stage=2,
                         policy=stages.EXPLICIT) for r in rows]
    got = stages.summarise(moves)
    assert got["moved"] + got["unsupported"] == len(rows)
    for one in moves:
        if one.supported:
            # A lifetime recognition is larger than a twelve-month one on
            # the same exposure, and it is the book's figure rather than a
            # multiple of the annual one.
            assert one.ecl_scenario >= one.ecl_baseline


# ==========================================================================
# The field dictionary follows the release that is actually open
# ==========================================================================

def test_the_accepted_book_still_says_the_application_score_is_absent():
    """The accepted dictionary is right about the accepted book.

    `fields.py` was written in P2 against books that do not publish an
    origination score, and nothing here changes what it says about them.
    """
    from backend.cockpit_v4.scenario import fields as fd

    assert fd.candidate_in_use(dom.RETAIL) is False
    entry = fd.lookup(dom.RETAIL, "application_score")
    assert entry.availability == fd.ABSENT
    assert "must not be substituted" in entry.absent_note
    assert fd.fields_for(dom.RETAIL) is fd.BY_DOMAIN[dom.RETAIL]


@pytest.mark.usefixtures("_published")
def test_the_candidate_book_publishes_what_the_accepted_one_does_not(enabled):
    """A reader against the candidate is not told a published column is
    missing."""
    from backend.cockpit_v4.scenario import fields as fd

    assert fd.candidate_in_use(dom.RETAIL) is True
    entry = fd.lookup(dom.RETAIL, "application_score")
    assert entry.availability == fd.PUBLISHED
    assert entry.relation == "whatif_retail_profile"
    assert (entry.low, entry.high) == (D("200"), D("800"))
    assert "DIFFERENT score from behaviour_score" in entry.what

    employer = fd.lookup(dom.RETAIL, "employer_sector")
    assert employer.availability == fd.PUBLISHED
    assert "NOT the product they hold" in employer.what


@pytest.mark.usefixtures("_published")
def test_the_candidate_origination_score_is_still_not_movable(enabled):
    """Published is not the same as mutable.

    An application score is what was known at origination. A scenario that
    rewrote it would be changing the past, and the answer would be about a
    book that never existed.
    """
    from backend.cockpit_v4.scenario import fields as fd

    with pytest.raises(err.ScenarioError) as raised:
        fd.mutable(dom.RETAIL, "application_score")
    assert raised.value.code == err.MAPPING_UNAVAILABLE
    assert "not something a scenario changes" in str(raised.value)


@pytest.mark.usefixtures("_published")
def test_a_retail_sector_rule_is_still_refused_on_the_candidate(enabled):
    """`sector` is not `employer_sector`, and the candidate does not make it
    one."""
    from backend.cockpit_v4.scenario import fields as fd

    entry = fd.lookup(dom.RETAIL, "sector")
    assert entry.availability == fd.ABSENT
    assert "product is not a substitute" in entry.absent_note


@pytest.mark.usefixtures("_published")
def test_the_candidate_splits_modelled_ecl_from_the_overlay(enabled) -> None:
    """Section 9.1. Two figures, and the overlay is held fixed by default."""
    from backend.cockpit_v4.scenario import fields as fd

    for domain_id in (dom.CORPORATE, dom.RETAIL):
        modelled = fd.lookup(domain_id, "ecl_modelled_sar_mn")
        overlay = fd.lookup(domain_id, "ecl_overlay_sar_mn")
        assert modelled.availability == fd.PUBLISHED
        assert modelled.mutable is True
        assert overlay.availability == fd.PUBLISHED
        assert overlay.mutable is False
        assert "observed zero" in overlay.missing_means


@pytest.mark.usefixtures("_published")
def test_every_candidate_field_really_is_a_column_of_its_relation(enabled):
    """The same check P2 applies to the accepted dictionary, here."""
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4.scenario import fields as fd

    for domain_id in (dom.CORPORATE, dom.RETAIL):
        connection = arun.for_domain(domain_id).session.connection
        for entry in fd.CANDIDATE_FIELDS[domain_id]:
            columns = {d[0] for d in connection.execute(
                f"SELECT * FROM {entry.relation} LIMIT 0").description}
            assert entry.field_id in columns, (
                f"{domain_id}.{entry.field_id} is declared PUBLISHED on "
                f"{entry.relation} and is not a column of it")


@pytest.mark.usefixtures("_published")
def test_the_flag_alone_does_not_change_the_dictionary(monkeypatch) -> None:
    """A book with What-If on and no candidate published reads the accepted
    release, and its inventory is the accepted one."""
    from backend.cockpit_v4 import analytical_runtime as arun
    from backend.cockpit_v4.scenario import candidate_schema as cs_mod
    from backend.cockpit_v4.scenario import fields as fd
    from backend.cockpit_v4.scenario import flags as fl

    for variable in fl.VARIABLES.values():
        monkeypatch.setenv(variable, "1")
    monkeypatch.setitem(cs_mod.RELEASES, dom.RETAIL, "v4-never-published")
    arun.reset()
    try:
        assert fd.candidate_in_use(dom.RETAIL) is False
        assert fd.lookup(dom.RETAIL,
                         "application_score").availability == fd.ABSENT
    finally:
        arun.reset()


@pytest.mark.usefixtures("_published")
def test_the_banned_shortcut_overstates_the_real_book_by_three_quarters(
        enabled) -> None:
    """S14's ban, measured rather than asserted.

    `12m x remaining years` against the published lifetime figure, over
    every Corporate facility with a year or more to run. If this ever came
    back close to 1.0 the ban would be a style preference; it does not.
    """
    from backend.cockpit_v4 import analytical_runtime as arun

    connection = arun.for_domain(dom.CORPORATE).session.connection
    latest = connection.execute(
        "SELECT max(reporting_quarter) FROM whatif_corp_ifrs9").fetchone()[0]
    low, high, count, lifetime, naive = connection.execute(f"""
        SELECT min(r), max(r), count(*), sum(life), sum(naive) FROM (
          SELECT f.ecl_lifetime_sar_mn AS life,
                 f.ecl_12m_sar_mn * (i.remaining_maturity_months / 12.0)
                     AS naive,
                 f.ecl_lifetime_sar_mn / nullif(
                     f.ecl_12m_sar_mn * (i.remaining_maturity_months / 12.0),
                     0) AS r
          FROM corp_facility_quarter f
          JOIN whatif_corp_ifrs9 i USING (facility_id, reporting_quarter)
          WHERE f.reporting_quarter = '{latest}'
            AND f.ecl_12m_sar_mn > 0
            AND i.remaining_maturity_months >= 12)""").fetchone()
    assert count > 2000
    assert naive / lifetime > 1.5, (
        "the shortcut is meant to be badly wrong, and this book is where "
        "that is demonstrated rather than asserted")
    # And the error is not a constant, so it cannot be corrected with a
    # factor either.
    assert high - low > 0.4
