"""The lenses CreditProbe ships, and whether their numbers hang together.

Two kinds of test here. The first kind proves the definitions are sound — every
tile names a metric that exists, drawn a way that metric has declared honest.
The second kind is the one that would catch a real defect: it renders a lens
against the live governed data and checks that the numbers on it *reconcile*
with each other. Three stage exposures that do not sum to the total exposure is
a lens nobody should be shown, and no amount of unit testing the formula
objects would find it.
"""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.metrics import lenses as shipped
from backend.metrics import service as metrics
from backend.services import lenses as service

needs_db = pytest.mark.skipif(not settings.has_database,
                              reason="lenses are stored in PostgreSQL")

#: A period the corporate staging dataset genuinely has.
QUARTER = "Q4 2024"


@pytest.fixture(scope="module")
def installed():
    if not settings.has_database:
        pytest.skip("lenses are stored in PostgreSQL")
    shipped.install(user_id=1)
    return {spec.slug: service.by_slug(spec.slug) for spec in shipped.ALL}


@pytest.fixture(scope="module")
def ifrs9(installed):
    return service.render(installed["corporate-ifrs9"].id, period=QUARTER,
                          user_id=1)


def _values(rendered) -> dict[str, float | None]:
    return {p["metric_id"]: p.get("value") for p in rendered["panels"]}


# ------------------------------------------------------- the definitions


def test_every_shipped_lens_matches_the_metric_library():
    """`check()` is the whole point: a stale tile fails a build, not a screen."""
    assert shipped.check() == []


def test_the_shipped_lenses_are_the_three_that_were_asked_for():
    assert {spec.slug for spec in shipped.ALL} == {
        "retail-credit-risk", "retail-analytics", "corporate-ifrs9"}


def test_the_cro_lens_is_preserved_rather_than_rebuilt():
    """§5 asks that the CRO Lens is kept, not replaced with a tile grid."""
    assert shipped.CRO_LENS["slug"] == "cro"
    assert shipped.CRO_LENS["note"].strip()
    assert "cro" not in {spec.slug for spec in shipped.ALL}


@pytest.mark.parametrize("spec", shipped.ALL, ids=lambda s: s.slug)
def test_a_lens_is_grouped_rather_than_being_one_long_run(spec):
    assert len(spec.sections) >= 3
    for section in spec.sections:
        assert section.title.strip()
        assert section.tiles, f"{section.title} has no tiles"


@pytest.mark.parametrize("spec", shipped.ALL, ids=lambda s: s.slug)
def test_the_layout_covers_every_tile_exactly_once(spec):
    covered = [i for section in spec.layout() for i in section["panels"]]
    assert sorted(covered) == list(range(len(spec.tiles)))


@pytest.mark.parametrize("spec", shipped.ALL, ids=lambda s: s.slug)
def test_a_lens_says_what_it_cannot_show(spec):
    """A view that quietly omits the number somebody came for is not honest."""
    notes = spec.notes()
    assert notes, f"{spec.name} claims nothing is missing from it"
    for note in notes:
        assert note["because"].strip()
        assert note["needs"], f"{note['name']} does not say what would be needed"


@pytest.mark.parametrize("spec", shipped.ALL, ids=lambda s: s.slug)
def test_no_lens_shows_a_metric_it_also_says_is_unavailable(spec):
    shown = {tile.metric_id for tile in spec.tiles}
    assert shown.isdisjoint(set(spec.absent))


# ------------------------------------------------------------- installing


@needs_db
def test_installing_twice_does_not_produce_two_lenses(installed):
    again = shipped.install(user_id=1)
    assert {row["action"] for row in again} == {"kept"}
    slugs = [row["slug"] for row in service.listing()]
    for spec in shipped.ALL:
        assert slugs.count(spec.slug) == 1


@needs_db
def test_a_shipped_lens_keeps_the_slug_it_is_addressed_by(installed):
    """The slug is the lens's address, so it cannot be derived from the name."""
    for spec in shipped.ALL:
        assert service.by_slug(spec.slug).name == spec.name


@needs_db
def test_replacing_a_shipped_lens_keeps_the_previous_definition(installed):
    before = service.by_slug("retail-analytics")
    shipped.install(user_id=1, replace=True)
    after = service.by_slug("retail-analytics")
    assert after.version == before.version + 1
    assert after.id == before.id
    assert any(r["version"] == before.version for r in after.revisions), (
        "somebody may have edited a shipped lens; the edit must survive")


# ------------------------------------------------------------- rendering


@needs_db
def test_every_tile_on_the_ifrs9_lens_produces_a_number(ifrs9):
    assert ifrs9["failed"] == 0, [p for p in ifrs9["panels"]
                                  if p["status"] == "failed"]
    assert ifrs9["unavailable"] == 0
    for panel in ifrs9["panels"]:
        assert panel["status"] == "succeeded", panel["metric_id"]
        assert isinstance(panel["value"], float), panel["metric_id"]


@needs_db
def test_a_tile_carries_its_own_explanation(ifrs9):
    """§6: an info control that needs a second request is one nobody opens."""
    panel = next(p for p in ifrs9["panels"]
                 if p["metric_id"] == "corporate.ifrs9.coverage")
    definition = panel["metric"]
    assert definition["definition"].strip()
    assert definition["formula"].strip()
    assert definition["numerator"].strip() and definition["denominator"].strip()
    assert definition["source_fields"]
    assert definition["origin_label"] == "CreditProbe governed"
    assert panel["calculation"]["sql"].strip()


@needs_db
def test_the_sections_index_the_panels_that_were_rendered(ifrs9):
    covered = [i for section in ifrs9["sections"] for i in section["panels"]]
    assert sorted(covered) == list(range(len(ifrs9["panels"])))


# ---------------------------------------------- do the numbers hang together


@needs_db
def test_the_three_stage_exposures_sum_to_the_total(ifrs9):
    v = _values(ifrs9)
    parts = sum(v[f"corporate.ifrs9.stage{n}_ead"] for n in (1, 2, 3))
    assert parts == pytest.approx(v["corporate.ifrs9.total_ead"], rel=1e-9)


@needs_db
def test_the_three_stage_provisions_sum_to_the_total(ifrs9):
    v = _values(ifrs9)
    parts = sum(v[f"corporate.ifrs9.stage{n}_ecl"] for n in (1, 2, 3))
    assert parts == pytest.approx(v["corporate.ifrs9.total_ecl"], rel=1e-9)


@needs_db
def test_the_stage_shares_account_for_the_whole_book(ifrs9):
    v = _values(ifrs9)
    total = sum(v[f"corporate.ifrs9.stage{n}_share"] for n in (1, 2, 3))
    assert total == pytest.approx(100.0, abs=1e-9)


@needs_db
def test_coverage_is_the_provision_over_the_exposure(ifrs9):
    v = _values(ifrs9)
    implied = (v["corporate.ifrs9.total_ecl"]
               / v["corporate.ifrs9.total_ead"] * 100.0)
    assert v["corporate.ifrs9.coverage"] == pytest.approx(implied, rel=1e-9)


@needs_db
def test_the_overlay_share_is_the_overlay_over_the_provision(ifrs9):
    v = _values(ifrs9)
    implied = (v["corporate.ifrs9.macro_overlay"]
               / v["corporate.ifrs9.total_ecl"] * 100.0)
    assert v["corporate.ifrs9.overlay_share"] == pytest.approx(implied,
                                                               rel=1e-9)


@needs_db
def test_stage_three_is_provisioned_more_heavily_than_stage_one(ifrs9):
    """Not arithmetic — a sanity check on whether the staging means anything."""
    v = _values(ifrs9)
    assert (v["corporate.ifrs9.stage3_coverage"]
            > v["corporate.ifrs9.stage2_coverage"]
            > v["corporate.ifrs9.stage1_coverage"])


@needs_db
def test_the_retail_lens_renders_and_its_arrears_buckets_nest(installed):
    """More accounts are 30+ days late than 90+. If not, the filter is wrong."""
    out = service.render(installed["retail-credit-risk"].id, user_id=1)
    assert out["failed"] == 0, [p for p in out["panels"]
                                if p["status"] == "failed"]
    v = _values(out)
    assert v["retail.dpd_30_count"] >= v["retail.dpd_90_count"]
    assert v["retail.dpd_30_balance"] >= v["retail.dpd_90_balance"]
    assert 0.0 <= v["retail.dpd_90_count"] <= 100.0


@needs_db
def test_the_retail_analytics_lens_renders(installed):
    out = service.render(installed["retail-analytics"].id, user_id=1)
    assert out["failed"] == 0, [p for p in out["panels"]
                                if p["status"] == "failed"]
    v = _values(out)
    assert v["retail.applications"] > 0
    for name in ("retail.scorecard.gini", "retail.application_gini"):
        assert 0.0 < v[name] < 1.0, (
            f"{name} outside 0-1 means the metric is not what it says it is; "
            "a negative Gini in particular means the score direction is "
            "the wrong way round")


@needs_db
def test_a_validation_metric_reports_on_a_cohort_that_has_outcomes(installed):
    """The latest month has no defaults yet, because nobody has had time to.

    A Gini for last month is not a low Gini — it does not exist. These metrics
    resolve to the most recent period whose performance window has closed, and
    the panel says so rather than leaving a reader to assume.
    """
    out = service.render(installed["retail-analytics"].id, user_id=1)
    panel = next(p for p in out["panels"]
                 if p["metric_id"] == "retail.scorecard.gini")
    assert panel["status"] == "succeeded"
    assert panel["metric"]["period_rule"] == "latest_matured"
    assert panel["period_used"], "the tile must say which period it used"
    assert panel["calculation"]["rows_considered"] > 1000, (
        "a discrimination statistic on a handful of rows proves nothing")
    assert any("defaults in" in w for w in panel["calculation"]["warnings"]), (
        "the reader needs the sample size behind a Gini")


@needs_db
def test_a_validation_metric_only_counts_rows_that_have_an_outcome(installed):
    """The declared exclusion has to be the exclusion actually applied."""
    metric = metrics.resolve("retail.scorecard.gini")
    assert metric.exclusions.strip()
    assert any(c.field == "matured_flag" for c in metric.scope), (
        "the panel promises immature rows are excluded; the formula must "
        "actually exclude them")
    matured = metrics.value("retail.scorecard.matured")["value"]
    gini = metrics.value("retail.scorecard.gini")
    assert 0 < gini["calculation"]["rows_considered"] <= matured


# ------------------------------------------------------------ what it refuses


@needs_db
def test_a_lens_cannot_name_a_metric_that_does_not_exist():
    with pytest.raises(service.InvalidLens, match="not a metric"):
        service.validate([service.Panel.metric("no.such.metric")])


@needs_db
def test_a_lens_cannot_show_a_metric_this_deployment_cannot_calculate():
    with pytest.raises(service.InvalidLens, match="cannot be calculated"):
        service.validate([service.Panel.metric("retail.roll_rate")])


@needs_db
def test_a_metric_cannot_be_drawn_a_way_it_has_not_declared_honest():
    metric = metrics.resolve("corporate.ifrs9.coverage")
    assert "bar" not in metric.visuals
    with pytest.raises(service.InvalidLens, match="should not be drawn"):
        service.validate([service.Panel.metric("corporate.ifrs9.coverage",
                                               visual="bar")])


@needs_db
def test_the_analysis_panel_limit_is_unchanged_by_metric_tiles():
    """Metric tiles get their own, higher limit; the old cap still holds."""
    too_many = [service.Panel(analysis_id="x")
                for _ in range(service.MAX_PANELS + 1)]
    with pytest.raises(service.InvalidLens, match="analysis panels"):
        service.validate(too_many)

    tiles = [service.Panel.metric("corporate.ifrs9.coverage")
             for _ in range(service.MAX_TILES + 1)]
    with pytest.raises(service.InvalidLens, match="metric tiles"):
        service.validate(tiles)


@needs_db
def test_a_definition_written_before_metric_tiles_still_reads_as_an_analysis():
    panel = service.Panel.from_dict({"analysis_id": "ifrs9_staging_profile",
                                     "title": "Staging", "visual": "table"})
    assert panel.kind == service.KIND_ANALYSIS
    assert panel.metric_id == ""
