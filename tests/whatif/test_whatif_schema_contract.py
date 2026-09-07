"""
The schema contract between the Corporate universe and What-If.

This file exists because of a real defect. What-If resolved its columns from
the governed CATALOGUE and then named them in a DuckDB SELECT. The catalogue
declares what a dataset is supposed to carry; the Parquet holds what it does;
and where a lake and a catalogue came from different builds those two
disagreed. DuckDB answered:

    Referenced column "cash_conversion_cycle_days" not found in FROM clause

and a credit officer saw "CreditProbe could not complete that request".
A working-capital statistic that no expected-credit-loss calculation needs had
stopped every scenario on the product.

So there are two kinds of test here:

  * CONTRACT tests, which fail if What-If's field list and the Corporate
    universe generator's lineage ever drift apart again;
  * DEGRADED-BOOK tests, which build a real lake with a field removed and run
    the whole product against it — because the only way to know a missing
    column is survivable is to remove one and watch.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from backend.corporate import lineage as lineage_mod
from backend.data_access.duckdb_source import DuckDBSource
from backend.whatif import domain as dm
from backend.whatif import engine as wf
from backend.whatif import methodology as me
from backend.whatif import migration as mg
from backend.whatif import profiles as pf
from backend.whatif import run as rn
from backend.whatif import scenarios as sc
from backend.whatif import schema as sch
from backend.whatif import steps as sp
from backend.whatif.ml import features as ft
from backend.whatif.ml import registry as rg

WHATIF_DATASETS = ("corporate_borrower_360", "corporate_ifrs9",
                   "corporate_facilities", "corporate_collateral",
                   "corporate_macro")


# ==================================================== the contract itself


class TestTheContractMatchesTheGenerator:
    """What-If may not require a field the generator does not promise."""

    def test_every_required_field_is_declared_by_the_generator(self) -> None:
        """`lineage.FIELDS` is what `build_corporate_universe.py` writes, and
        the snapshot assembler refuses to publish a field without an entry. So
        it is the generator's promise, and What-If's REQUIRED list has to be a
        subset of it."""
        promised = {f.name for f in lineage_mod.FIELDS} | {"period"}
        missing = sorted(set(sch.REQUIRED) - promised)
        assert not missing, (
            f"What-If requires {missing}, which the Corporate universe "
            "generator does not produce. Either the generator lost a field or "
            "What-If is asking for one that was never promised.")

    def test_every_optional_field_is_declared_by_the_generator(self) -> None:
        promised = {f.name for f in lineage_mod.FIELDS} | {"period"}
        missing = sorted(set(sch.OPTIONAL) - promised)
        assert not missing, (
            f"What-If names {missing} as optional, but the generator has no "
            "lineage entry for them, so they can never appear. An optional "
            "field nothing produces is a typo, not a capability.")

    def test_the_engines_field_list_is_covered_by_the_contract(self) -> None:
        """Nothing may be read that the contract has not classified."""
        classified = set(sch.REQUIRED) | set(sch.OPTIONAL)
        stray = sorted(set(wf.FIELDS) - classified)
        assert not stray, (
            f"engine.FIELDS reads {stray} without saying whether they are "
            "load-bearing. An unclassified field cannot be safely dropped when "
            "a book does not carry it.")

    def test_every_optional_field_says_what_its_absence_costs(self) -> None:
        for field, enables in {**sch.OPTIONAL, **sch.IFRS9_OPTIONAL}.items():
            assert enables and len(enables) > 8, (
                f"'{field}' is optional but does not say what is lost without "
                "it, so a warning about it cannot be acted on")

    def test_the_required_set_is_only_what_the_measurement_needs(self) -> None:
        """A field is REQUIRED only if there is no ECL without it. Anything
        else being required is how one absent statistic took the product down."""
        for cosmetic in ("display_name", "legal_name", "group_name",
                         "cash_conversion_cycle_days", "working_capital",
                         "revenue", "ebitda", "covenant_count"):
            assert cosmetic not in sch.REQUIRED, (
                f"'{cosmetic}' is not needed to price a scenario and must not "
                "be able to stop one")

    def test_the_ml_features_come_from_the_same_book(self) -> None:
        """A model feature the governed domain does not guarantee is the same
        defect one layer along."""
        derived = {"collateral_to_ead", "drawn_share", "undrawn_share",
                   "secured_share", "log_ead", "sector_code", "segment_code",
                   "revenue_growth", "rating_change_notches", "max_dpd_12m",
                   "forbearance_flag", "restructure_flag", "ccf",
                   "facility_count"}
            # ^ computed by ft.derive from other columns or other datasets
        promised = ({f.name for f in lineage_mod.FIELDS}
                    | set(sch.ALL_IFRS9) | derived)
        stray = sorted(set(ft.FEATURES) - promised)
        assert not stray, (
            f"ML features {stray} are neither generated by the Corporate "
            "universe nor derived from something that is.")


class TestTheDriftCannotBeReintroduced:
    """A structural guard, not a behavioural one.

    The defect was one line: `reader.fields(...)` used to decide which columns
    to name in a query. It is a natural-looking line and it will look natural
    again, so this fails if any What-If module goes back to it.
    """

    def test_no_whatif_module_selects_from_the_catalogue(self) -> None:
        import backend.whatif as package

        root = Path(package.__file__).resolve().parent
        offenders = []
        for module in sorted(root.rglob("*.py")):
            if module.name == "schema.py":
                continue  # the one place allowed to compare the two
            body = module.read_text(encoding="utf-8")
            if ".fields(" in body:
                offenders.append(module.relative_to(root).as_posix())
        assert not offenders, (
            f"{offenders} resolve columns from the catalogue. The catalogue "
            "declares what a dataset should carry; a SELECT binds against "
            "what it does. Use backend.whatif.schema.")

    def test_the_reader_can_be_asked_what_the_data_has(self) -> None:
        reader = DuckDBSource()
        assert hasattr(reader, "columns"), (
            "the fix depends on being able to ask the Parquet, not the "
            "catalogue, what a dataset carries")


class TestTheInstallationIsReportedNotAssumed:
    def test_the_report_compares_the_catalogue_with_the_data(self) -> None:
        body = sch.report()
        snapshot = body["datasets"]["corporate_borrower_360"]
        assert snapshot["readable"]
        assert "declared_but_absent" in snapshot
        assert "present_but_undeclared" in snapshot

    def test_this_installation_is_healthy(self) -> None:
        body = sch.report()
        snapshot = body["datasets"]["corporate_borrower_360"]
        assert not snapshot["missing_required"], snapshot["missing_required"]
        assert not snapshot["declared_but_absent"], (
            "the catalogue declares fields this lake does not carry: "
            f"{snapshot['declared_but_absent']}. That is the exact condition "
            "that produced the reported binder error.")
        assert body["healthy"]

    def test_columns_reads_the_parquet_and_fields_reads_the_catalogue(self) -> None:
        """The distinction the fix turns on. They may agree; they are not the
        same question, and only one of them can be put in a SELECT."""
        reader = DuckDBSource()
        on_disk = set(reader.columns("corporate_borrower_360"))
        declared = set(reader.fields("corporate_borrower_360"))
        assert on_disk, "columns() must read the file schema"
        assert declared, "fields() must read the catalogue"
        # On a correctly built lake they agree; the test is that both answer.
        assert "cash_conversion_cycle_days" in on_disk

    def test_no_column_the_engine_requests_is_absent_from_the_book(self) -> None:
        """The direct statement of the reported defect."""
        on_disk = set(sch.columns(sch.SNAPSHOT))
        resolution = sch.snapshot_fields(
            tuple(f for f in wf.FIELDS if f not in sch.REQUIRED))
        assert not resolution.absent, resolution.absent
        assert set(resolution.present) <= on_disk


# ============================================ the product on a real book


@pytest.fixture(scope="module")
def period() -> str:
    return dm.latest_period()


class TestTheGeneratedUniverseAnswersEveryJourney:
    """Reads the universe `build_corporate_universe.py` actually wrote."""

    def test_the_lake_is_the_generated_one(self) -> None:
        """Every dataset What-If reads is on disk. `corporate_macro` is a
        single file rather than a partitioned directory — it is one row per
        quarter for the whole book — so it is checked for files, not periods."""
        reader = DuckDBSource()
        root = Path(reader.root)
        for dataset in WHATIF_DATASETS:
            files = list((root / dataset).rglob("*.parquet"))
            assert files, f"{dataset} has no Parquet on disk"
        for partitioned in ("corporate_borrower_360", "corporate_ifrs9"):
            assert reader.periods(partitioned), partitioned

    def test_a_simple_pd_what_if(self, period) -> None:
        state = sp.ScenarioState(period=period).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    interpreted="PD +20%"))
        result = rn.execute(state, requested=me.DELTA)
        assert result.summary["incremental_ecl"] > 0
        assert not [w for w in result.warnings if "not in corporate" in w]

    def test_rating_movement(self, period) -> None:
        profile = pf.rating_profile(period)
        assert len(profile) >= 2
        matrix = mg.rating_migration(period)
        assert matrix["labels"]
        state = sp.ScenarioState(period=period).add(
            sp.Step(sp.RATING, (sc.Shock(sc.RATING, 2, sc.NOTCHES),),
                    interpreted="downgrade two notches"))
        result = rn.execute(state, requested=me.DELTA)
        assert result.rating_movement["rows"]

    def test_the_delta_model(self, period) -> None:
        state = sp.ScenarioState(period=period).add(
            sp.Step(sp.LGD, (sc.Shock(sc.LGD, 5.0, sc.ABSOLUTE_PP),),
                    interpreted="LGD +5pp"))
        result = rn.execute(state, requested=me.DELTA)
        assert result.choice.method == me.DELTA
        assert result.factors and result.factors.to_dict()["lgd_factor"] > 1.0

    def test_the_ml_model(self, period) -> None:
        if not rg.active_version():
            pytest.fail("no ML model is active, so the ML path cannot be "
                        "proven — that is a failure, not a reason to skip")
        state = sp.ScenarioState(period=period).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    interpreted="PD +20%"))
        result = rn.execute(state, requested=me.ML)
        assert result.choice.method == me.ML
        assert result.ml.get("model_version")

    def test_every_shock_kind_runs_on_the_generated_book(self, period) -> None:
        """One per kind, because the reported defect only appeared on the
        read — and every kind takes the same read."""
        shocks = {
            "rating": sc.Shock(sc.RATING, 1, sc.NOTCHES),
            "pd": sc.Shock(sc.PD, 10.0, sc.RELATIVE),
            "lgd": sc.Shock(sc.LGD, 2.0, sc.ABSOLUTE_PP),
            "ead": sc.Shock(sc.EAD, 10.0, sc.RELATIVE),
            "ccf": sc.Shock(sc.CCF, 5.0, sc.ABSOLUTE_PP),
            "collateral": sc.Shock(sc.COLLATERAL, -10.0, sc.RELATIVE),
            "stage": sc.Shock(sc.STAGE, 25.0, sc.RELATIVE, "1->2"),
            "macro": sc.Shock(sc.MACRO, 100.0, sc.BASIS_POINTS,
                              target="policy_rate"),
            "financial": sc.Shock(sc.FINANCIAL, -10.0, sc.RELATIVE,
                                  target="ebitda"),
        }
        for kind, shock in shocks.items():
            state = sp.ScenarioState(period=period).add(
                sp.Step(kind, (shock,), interpreted=kind))
            result = rn.execute(state, requested=me.DELTA)
            assert result.population > 0, kind


# ================================================ a book missing a field


@pytest.fixture(scope="module")
def degraded(tmp_path_factory) -> Path:
    """A real lake, rebuilt without one optional column.

    This is the reported installation. Copying and re-writing the Parquet is
    the only honest way to test it: a mock would prove the mock tolerates a
    missing column, which is not the claim.
    """
    source = Path(DuckDBSource().root)
    target = tmp_path_factory.mktemp("degraded")
    dropped = "cash_conversion_cycle_days"
    for dataset in WHATIF_DATASETS:
        for part in (source / dataset).glob("period=*"):
            out = target / dataset / part.name
            out.mkdir(parents=True, exist_ok=True)
            for parquet in part.glob("*.parquet"):
                columns = duckdb.sql(
                    f"SELECT * FROM read_parquet('{parquet}') LIMIT 0").columns
                keep = ", ".join(f'"{c}"' for c in columns if c != dropped)
                duckdb.sql(f"COPY (SELECT {keep} FROM "
                           f"read_parquet('{parquet}')) TO "
                           f"'{out / parquet.name}' (FORMAT PARQUET)")
    return target


@pytest.fixture
def on_degraded(degraded, monkeypatch):
    """Point the whole stack at the degraded lake for one test."""
    import backend.config as cfg
    from backend.data_access import duckdb_source as ds

    monkeypatch.setenv("DATA_ANALYTICS_DIR", str(degraded))
    monkeypatch.setattr(cfg, "settings", cfg._load())
    monkeypatch.setattr(ds, "settings", cfg.settings, raising=False)
    sch.reset_cache()
    dm.reset_cache()
    yield degraded
    sch.reset_cache()
    dm.reset_cache()


class TestAMissingOptionalFieldCostsOnlyItself:
    """The defect, and the behaviour that replaces it."""

    def test_the_catalogue_and_the_data_now_disagree(self, on_degraded) -> None:
        reader = DuckDBSource()
        declared = set(reader.fields("corporate_borrower_360"))
        on_disk = set(reader.columns("corporate_borrower_360"))
        assert "cash_conversion_cycle_days" in declared
        assert "cash_conversion_cycle_days" not in on_disk, (
            "the fixture must reproduce the reported condition")

    def test_the_ecl_still_computes(self, on_degraded) -> None:
        """The whole point. A missing working-capital statistic is not a
        reason to refuse to price a scenario."""
        result = wf.run(sc.scenario("pd_up_25"))
        assert result.population_size > 0
        assert result.summary["stressed_ecl"] > result.summary["baseline_ecl"]

    def test_the_loss_is_named_rather_than_hidden(self, on_degraded) -> None:
        """Named — but as a NOTE about the installation, not a warning about
        the result. An absent optional column costs exactly the capability it
        names, and putting that in the same amber list as "this shock could
        not be applied" taught readers to skip both."""
        result = wf.run(sc.scenario("pd_up_25"))
        said = " ".join(result.notes)
        assert "cash_conversion_cycle_days" in said
        assert "cash conversion cycle" in said, "it must say what was lost"
        assert "build_corporate_universe" in said, "and how to get it back"
        assert not result.warnings, (
            "nothing is wrong with this RESULT, so nothing belongs in the "
            "warnings")

    def test_both_methodologies_price_the_degraded_book(self, on_degraded) -> None:
        state = sp.ScenarioState(period=dm.latest_period()).add(
            sp.Step(sp.PD, (sc.Shock(sc.PD, 20.0, sc.RELATIVE),),
                    interpreted="PD +20%"))
        for method in (me.DELTA, me.ML):
            result = rn.execute(state, requested=method)
            assert result.summary["incremental_ecl"] > 0, method

    def test_every_journey_survives(self, on_degraded) -> None:
        period = dm.latest_period()
        assert len(pf.rating_profile(period)) >= 2
        assert len(pf.stage_profile(period)) >= 2
        assert len(pf.sector_profile(period)) >= 2
        assert len(pf.pd_profile(period)) >= 2
        assert len(pf.top_stage_2(period)) >= 1
        assert mg.rating_migration(period)["labels"]
        assert mg.stage_migration(period)["labels"]

    def test_a_shock_on_the_missing_field_is_refused_not_skipped(
            self, on_degraded) -> None:
        """A step that quietly does nothing is indistinguishable on screen
        from one that moved no borrower."""
        with pytest.raises(wf.ShockUnavailable) as raised:
            wf.run(sc.Scenario(
                key="ccd", name="cash conversion cycle",
                shocks=(sc.Shock(sc.FINANCIAL, -20.0, sc.RELATIVE,
                                 target="cash_conversion_cycle_days"),)))
        assert "cash_conversion_cycle_days" in str(raised.value)
        assert "build_corporate_universe" in str(raised.value)

    def test_a_shock_on_a_field_that_is_there_still_runs(self, on_degraded) -> None:
        result = wf.run(sc.Scenario(
            key="ebitda", name="EBITDA",
            shocks=(sc.Shock(sc.FINANCIAL, -20.0, sc.RELATIVE,
                             target="ebitda"),)))
        assert result.summary["stressed_ecl"] > result.summary["baseline_ecl"]

    def test_the_report_says_the_installation_is_unhealthy(self, on_degraded) -> None:
        body = sch.report()
        snapshot = body["datasets"]["corporate_borrower_360"]
        assert snapshot["declared_but_absent"] == ["cash_conversion_cycle_days"]
        assert not snapshot["missing_required"]
        assert not body["healthy"], (
            "every scenario prices, and the installation is still not what "
            "the catalogue says it is; both facts have to be reportable")


class TestAMissingRequiredFieldIsNamed:
    @pytest.fixture(scope="class")
    def crippled(self, tmp_path_factory) -> Path:
        source = Path(DuckDBSource().root)
        target = tmp_path_factory.mktemp("crippled")
        for dataset in WHATIF_DATASETS:
            for part in (source / dataset).glob("period=*"):
                out = target / dataset / part.name
                out.mkdir(parents=True, exist_ok=True)
                for parquet in part.glob("*.parquet"):
                    columns = duckdb.sql(
                        f"SELECT * FROM read_parquet('{parquet}') LIMIT 0").columns
                    keep = ", ".join(
                        f'"{c}"' for c in columns
                        if not (dataset == "corporate_borrower_360"
                                and c == "pd_lifetime"))
                    duckdb.sql(f"COPY (SELECT {keep} FROM "
                               f"read_parquet('{parquet}')) TO "
                               f"'{out / parquet.name}' (FORMAT PARQUET)")
        return target

    def test_it_refuses_by_name_not_by_binder_error(
            self, crippled, monkeypatch) -> None:
        import backend.config as cfg
        from backend.data_access import duckdb_source as ds

        monkeypatch.setenv("DATA_ANALYTICS_DIR", str(crippled))
        monkeypatch.setattr(cfg, "settings", cfg._load())
        # duckdb_source binds `settings` at import, so patching the config
        # module alone would leave the reader pointed at the real lake.
        monkeypatch.setattr(ds, "settings", cfg.settings, raising=False)
        sch.reset_cache()
        dm.reset_cache()
        try:
            with pytest.raises(sch.SchemaError) as raised:
                wf.run(sc.scenario("pd_up_25"))
            said = str(raised.value)
            assert "pd_lifetime" in said
            assert "corporate_borrower_360" in said
            assert "build_corporate_universe" in said
            assert "FROM clause" not in said, (
                "a reader must never be shown DuckDB's binder error")
        finally:
            sch.reset_cache()
            dm.reset_cache()


def test_the_snapshot_grain_is_unchanged_by_any_of_this(period) -> None:
    frame, _ = dm.book(period)
    assert not frame.duplicated(subset=["borrower_id", "period"]).any()
    assert len(frame) == int(pd.Series(frame["borrower_id"]).nunique())
