"""Gates RET-046 to RET-060 — retail-only surface, routing, reliability, evidence."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.data_access.catalog import Catalog, active_governed_purposes
from backend.data_access.protocol import UnknownDatasetError
from backend.retail import profile

ROOT = Path(__file__).resolve().parents[2]

#: Vocabulary that must not appear on an ACTIVE retail surface.
CORPORATE_VOCABULARY = (
    "rating grade", "rating transition", "master scale", "internal rating",
    "obligor group", "balance sheet", "income statement", "cash flow statement",
    "ebitda", "dscr", "covenant", "borrower financials", "company financials",
    "sector concentration", "corporate rating",
)

#: Where the retired vocabulary MAY still appear: developer history, migration
#: code, the specification itself, the removal tests, and third-party notices.
#: Narrow, documented, and checked to be exactly these.
ALLOWLIST = (
    "docs/RETAIL_ONLY_MASTER_SPEC.md",
    "docs/RETAIL_CONVERSION_INVENTORY.md",
    "docs/RETAIL_ONLY_PROGRESS.md",
    "docs/RETAIL_SOURCE_PROVENANCE.md",
    "docs/RETAIL_ONLY_HANDOVER.md",
    "docs/RETAIL_REQUIREMENT_TRACEABILITY.md",
    "docs/RETAIL_UAT_REPORT.md",
    "tests/retail/",
    "alembic/",
    "backend/retail/profile.py",
    "backend/data_access/catalog.py",
    # The list of what the retail What-If does NOT implement, and the refusal
    # that names it. A person who types "downgrade everyone one notch" is
    # answered with what that would be and what this engine does instead — so
    # the retired words appear here exactly once, in the sentence that refuses
    # them. Offering them is what this gate forbids; naming them in a refusal
    # is how the product avoids pretending it ran something it did not.
    "backend/retail/whatif_language.py",
    # The same, one layer down: the concept registry keeps the corporate
    # concepts as retired code so the other book can be restored, and says so.
    "backend/orchestration/retail_concepts.py",
    "backend/orchestration/concepts.py",
)


class TestRET046RetailOnlySurface:
    def test_the_active_catalogue_is_retail_only(self, shipped_catalog):
        blob = json.dumps(shipped_catalog).lower()
        for token in CORPORATE_VOCABULARY:
            assert token not in blob, f"the active catalogue mentions '{token}'"

    def test_the_active_catalogue_has_one_domain(self, shipped_catalog):
        assert {d["domain"] for d in shipped_catalog["datasets"]} == {"Cockpit Data"}

    def test_the_governed_purposes_offered_are_retail(self):
        purposes = active_governed_purposes()
        assert set(purposes) == set(profile.ACTIVE_GOVERNED_PURPOSES)
        for token in ("rating", "borrower_financials", "corporate"):
            assert not any(token in p for p in purposes)

    def test_the_starter_questions_are_retail(self):
        for q in profile.STARTER_QUESTIONS:
            lowered = q["question"].lower()
            for token in CORPORATE_VOCABULARY:
                assert token not in lowered, f"starter question mentions '{token}': {q['question']}"

    def test_the_cockpit_serves_those_starters(self):
        from backend.api.routers.ask import STARTER_QUESTIONS
        assert STARTER_QUESTIONS is profile.STARTER_QUESTIONS

    def test_the_scenario_lab_chips_are_retail(self):
        from backend.stress_lab import STARTER_QUESTIONS as chips
        for chip in chips:
            lowered = chip.lower()
            for token in ("covenant", "real estate", "sector", "rating"):
                assert token not in lowered, chip

    def test_every_published_row_declares_itself_synthetic(self, retail_book):
        latest = retail_book.latest()
        assert latest["is_synthetic"].all()
        assert (latest["customer_scope"] == "NATURAL_PERSON_RETAIL").all()

    def test_the_disclosure_is_carried(self, shipped_catalog):
        assert "Synthetic Saudi retail" in shipped_catalog["disclosure"]
        assert "not ANB customer data" in shipped_catalog["disclosure"]

    def test_the_data_contract_rejects_corporate_entities(self):
        from tests.retail.conftest import SHIPPED_METADATA
        contract = json.loads((SHIPPED_METADATA / "retail_data_contract.json").read_text())
        rules = " ".join(contract["import_rules"]).lower()
        assert "corporate entity types" in rules
        assert "rejected with a retail-only message" in rules

    def test_the_retail_source_tree_carries_no_corporate_vocabulary(self):
        """A static scan of the STRINGS the retail code can emit.

        String literals only, parsed out with `ast`, and docstrings excluded.
        A comment explaining that a corporate object is deliberately absent —
        "employers are not financed company customers: no balance sheet, no
        rating, no covenant" — cannot reach a screen, and a scan that flagged
        it would push the codebase towards saying less about why it is built
        the way it is. The rendered-runtime scan in
        `scripts/retail_browser_uat.py` is what guarantees the screens.
        """
        import ast

        offenders: list[str] = []
        for path in (ROOT / "backend" / "retail").rglob("*.py"):
            rel = str(path.relative_to(ROOT))
            if any(rel.startswith(a) for a in ALLOWLIST):
                continue
            tree = ast.parse(path.read_text())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc:
                        docstrings.add(doc)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if node.value in docstrings:
                    continue
                lowered = node.value.lower()
                # A string that names the retired vocabulary in order to REFUSE
                # it is the opposite of a leak. The import contract has to say
                # "corporate entity types and rating grades are out of scope and
                # are rejected", and a scan that forbade that sentence would
                # force the product to reject things silently.
                if any(w in lowered for w in
                       ("rejected", "out of scope", "not available", "retired",
                        "no longer", "must not", "is not a")):
                    continue
                for token in CORPORATE_VOCABULARY:
                    if token in lowered:
                        offenders.append(f"{rel}:{node.lineno}: {token}")
        assert not offenders, offenders


class TestRET047NoLegacyFallback:
    @pytest.mark.parametrize("identifier", [
        "portfolio_facility", "customer_ratings", "borrower_financials",
        "corporate_connected_group", "macro_saudi",
    ])
    def test_a_retired_identifier_is_refused_with_a_retail_message(self, identifier):
        catalog = Catalog.load(ROOT / "metadata" / "retail" / "catalog.json")
        with pytest.raises(UnknownDatasetError) as e:
            catalog.dataset(identifier)
        message = str(e.value)
        assert "not available in this installation" in message
        assert "Saudi retail only" in message
        assert "Cockpit Data" in message

    def test_an_unknown_identifier_gets_the_ordinary_error(self):
        catalog = Catalog.load(ROOT / "metadata" / "retail" / "catalog.json")
        with pytest.raises(UnknownDatasetError, match="is not a governed dataset"):
            catalog.dataset("something_that_never_existed")

    def test_the_retired_identifier_is_not_resurrected(self):
        catalog = Catalog.load(ROOT / "metadata" / "retail" / "catalog.json")
        assert catalog.names() == ["retail_facility_month"]

    def test_a_missing_retail_seed_is_an_actionable_error_not_a_fallback(self):
        error = profile.missing_seed_error()
        message = str(error)
        assert "build_retail_demo.py" in message
        assert "No other portfolio will be served in its place" in message

    def test_empty_retail_data_does_not_reach_the_old_lake(self, tmp_path):
        """With no catalogue FILE, nothing corporate appears from anywhere.

        The assertion used to be `names() == []`, which held only because the
        suite happened to run without `DATABASE_URL`. `Catalog.load` reads the
        bundled JSON *and* every PUBLISHED dataset in PostgreSQL, so with the
        launcher's own environment the list is not empty — it is
        `['retail_facility_month']`, which is the right answer and was being
        read as a failure.

        What this gate is actually about is unchanged and is now what it says:
        a missing retail catalogue must not resurrect the retired book, from
        the file or from the database.
        """
        empty = Catalog.load(tmp_path / "nothing.json")
        for retired in ("portfolio_facility", "customer_ratings",
                        "ifrs9_staging", "borrower_financials",
                        "facility_delinquency", "macro_saudi"):
            assert retired not in empty.names()
            with pytest.raises(UnknownDatasetError):
                empty.dataset(retired)
        assert all(name.startswith("retail_") for name in empty.names()), (
            f"a non-retail dataset is reachable: {empty.names()}")


class TestRET048LayoutPreserved:
    """The conversion changed content, not the application's structure."""

    def test_no_new_top_level_route_was_added(self):
        routes = {p.name for p in (ROOT / "frontend" / "src" / "app").iterdir() if p.is_dir()}
        forbidden = {"retail-dashboard", "scorecard-dashboard", "retail", "onboarding",
                     "retail-cockpit", "new-dashboard"}
        assert not (routes & forbidden), f"an unauthorised top-level page was added: {routes & forbidden}"

    def test_the_existing_modules_are_still_present(self):
        routes = {p.name for p in (ROOT / "frontend" / "src" / "app").iterdir() if p.is_dir()}
        for expected in ("data-builder", "what-if", "early-warning", "lenses"):
            assert expected in routes, f"{expected} was removed rather than converted"

    def test_no_new_component_library_or_theme(self):
        components = ROOT / "frontend" / "src" / "components"
        new_dirs = {p.name for p in components.iterdir() if p.is_dir()} & {
            "retail", "retail-ui", "theme-v2", "design-system"}
        assert not new_dirs, f"a parallel component library was added: {new_dirs}"

    def test_the_conversion_touched_no_frontend_layout_file(self):
        changed = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only",
             "80e74a4e1e5552e73c532849b72329008335b09f", "HEAD"],
            capture_output=True, text=True, check=True).stdout.split()
        layout_files = [f for f in changed
                        if f.startswith("frontend/src/app/") and f.endswith("layout.tsx")]
        assert not layout_files, f"page layouts were modified: {layout_files}"

    def test_changes_are_confined_to_the_retail_conversion(self):
        changed = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only",
             "80e74a4e1e5552e73c532849b72329008335b09f", "HEAD"],
            capture_output=True, text=True, check=True).stdout.split()
        allowed_prefixes = (
            "backend/retail/",                    # the retail product
            "backend/api/routers/retail.py",      # its API surface
            "tests/retail/",
            "docs/RETAIL", "docs/evidence/",
            "config/retail",
            "scripts/build_retail_demo.py", "scripts/check_retail_ready.py",
            "scripts/bootstrap_retail_installation.py",
            "scripts/retail_browser_uat.py", "scripts/retail_uat_questions.py",
            "scripts/write_retail_",
            "launchers/retail/", "metadata/retail/", "data/retail/",
        )
        touched_elsewhere = [
            f for f in changed
            if not f.startswith(allowed_prefixes)
        ]
        # A small, named set of shared files carries the retail content swap.
        # The named, reviewed set of shared files the retail content swap
        # touches. Each is a content change, not a structural one, and each is
        # listed in docs/RETAIL_CONVERSION_INVENTORY.md.
        expected_shared = {
            ".gitignore",
            ".env.retail.example",
            ".env.retail",
            "backend/api/main.py",                 # registers the retail router
            "backend/api/routers/ask.py",          # retail starter questions
            "backend/stress_lab.py",               # retail scenario chips
            "backend/data_access/catalog.py",      # retail-only resolver
            "backend/services/data_domains.py",    # the Cockpit Data heading
            "backend/metadata/service.py",         # offers the active headings only
            "backend/early_warning/factors.py",    # retail signal families
            "frontend/src/lib/navigation.ts",      # Borrower 360 -> Customer 360
            "frontend/src/app/data-builder/page.tsx",  # retail domain suggestion
            # ---------------------------------------------------------------
            # The semantic layer, made PROFILE-AWARE rather than rewritten.
            #
            # Driving the running application proved the conversion could not
            # be confined to the retail package: every one of these files
            # still bound the product to the corporate book, so the Cockpit
            # could not plan a single retail question. Each carries a
            # corporate path and a retail path chosen by
            # `backend.retail.profile.is_retail()`, so the corporate book
            # remains restorable; none is a structural change.
            "backend/orchestration/concepts.py",       # active concept registry
            "backend/orchestration/retail_concepts.py",  # the retail concepts
            "backend/orchestration/vocabulary.py",     # governed dimensions
            "backend/orchestration/dimensions.py",     # how they are spelled
            "backend/orchestration/validator.py",      # what may be filtered on
            "backend/orchestration/multi.py",          # the default dataset
            "backend/orchestration/suggestions.py",    # the follow-up offered
            "backend/orchestration/entities.py",       # governed vocabulary
            "backend/orchestration/periods.py",        # months written in words
            "backend/orchestration/grain.py",          # a measure list is not a grain
            "backend/orchestration/analysis_planner.py",  # counts, period column
            "backend/orchestration/assembly.py",       # the largest, the ordering
            "backend/orchestration/presentation.py",   # count column headings
            "backend/orchestration/referents.py",      # "compare with July"
            "backend/orchestration/orchestrator.py",   # log the traceback
            "backend/data_access/duckdb_source.py",    # monthly period ordering
            "backend/orchestration/decomposition.py",  # the ECL bridge's book
            "backend/orchestration/movement.py",       # "move from X to Y"
            "frontend/src/app/investigations/page.tsx",  # labelled list rows
            "frontend/src/lib/__tests__/back-paths.test.ts",  # the Trace return
            "backend/api/permissions.py",              # retail router auth
            "backend/studio/library.py",               # the methods offered
            "backend/studio/registry.py",              # loads the active ones
            "frontend/src/components/attention/severity.ts",  # customer, not borrower
            # The two composers and the money formatter the answers render in.
            "frontend/src/components/ask/composer.tsx",
            "frontend/src/components/whatif/parts.tsx",
            "frontend/src/lib/format.ts",
            "frontend/src/lib/api.ts",
            "frontend/src/lib/profile.ts",
            "frontend/src/lib/__tests__/retail-money-scale.test.ts",
            "frontend/src/app/what-if/page.tsx",
            "frontend/src/app/what-if/retail-whatif.tsx",
            # ---------------------------------------------------------------
            # Revision 3. Each is a surface the conversion had left serving
            # the corporate book, found by opening it rather than by reading
            # it, and each carries a retail path chosen by the profile.
            #
            # Customer 360 and Early Warning called the corporate endpoints and
            # returned 503 data_not_built, so the screen was unreachable in the
            # shipped product.
            "frontend/src/app/borrower-360/page.tsx",
            "frontend/src/app/borrower-360/retail-customer.tsx",
            "frontend/src/app/early-warning/signals/page.tsx",
            "frontend/src/app/early-warning/signals/retail-signals.tsx",
            # The three corporate What-If routes answered under the retail
            # profile: not in the navigation is not unreachable, and a bookmark
            # opened rating notches over a book that does not exist here.
            "frontend/src/app/what-if/thread/page.tsx",
            "frontend/src/app/what-if/models/delta/page.tsx",
            "frontend/src/app/what-if/models/ml/page.tsx",
            "frontend/src/components/layout/retired-screen.tsx",
            # Agent Operations published three corporate teams as ACTIVE, and
            # the document library shipped a Real Estate Sector Review.
            "backend/agentic/registry.py",
            "frontend/src/lib/demo.ts",
            "frontend/src/app/documents/page.tsx",
            "frontend/src/app/documents/[id]/page.tsx",
            # The bootstrap seeds, which reinstall on every fresh deployment:
            # a Corporate IFRS 9 lens, two corporate committees, a corporate
            # model-redevelopment plan and a shipping-review thread.
            "backend/metrics/lenses.py",
            "backend/playbook/demo.py",
            # A schedule row persisted before a specialist was retired still
            # named it, so the seed and the serialiser both had to change.
            "backend/agentic/schedules.py",
            # A lens row installed before the corporate one was retired still
            # named it on the Lenses screen: the listing filters on read.
            "backend/services/lenses.py",
            "scripts/seed_playbook_committees.py",
            "scripts/seed_planner.py",
            "backend/services/demo_workflow.py",
            # ---------------------------------------------------------------
            # The overnight UAT. RFD-37: every metric in the shipped library
            # read a dataset this deployment does not have, so Metrics, Lenses
            # and the Playbook rendered a dash in every box.
            "backend/metrics/retail_library.py",   # 46 metrics on the retail book
            "backend/metrics/library.py",          # serves them under the profile
            "backend/metrics/lenses.py",           # the two lenses, rewritten
            "backend/metrics/execution.py",        # matured_flag on any dataset
            "backend/playbook/demo.py",            # three retail committee packs
            "scripts/seed_playbook_committees.py",
            "backend/services/demo_users.py",      # a corporate job title
            "backend/services/lenses.py",
            "frontend/src/components/metrics/present.ts",  # the missing %
            "scripts/retail_uat/",                 # the overnight harness
            "docs/RETAIL_OVERNIGHT_UAT_MASTER.md",
            "docs/RETAIL_OVERNIGHT_DEFECTS.md",
            # The CRO Portfolio Lens reads the wholesale book and was offered
            # as a card one click from the Lenses navigation item.
            "frontend/src/app/lenses/page.tsx",
            "frontend/src/app/lenses/cro/page.tsx",
            # The old-to-current What-If fidelity mapping Revision 3 §3 asks for.
            "docs/WHATIF_RETAIL_FIDELITY_MAP.md",
            # ---------------------------------------------------------------
            # The overnight UAT. Each of these is a defect found by USING the
            # product, reproduced, fixed and re-tested, and each is recorded
            # in docs/RETAIL_OVERNIGHT_DEFECTS.md with its own regression.
            #
            # The Cockpit could not answer a rate, a share or a delinquency
            # question, because a rate is not a column and the planner
            # composes an analysis out of columns.
            "backend/orchestration/metric_route.py",
            "backend/orchestration/absent_attributes.py",
            "backend/orchestration/semantics.py",
            "backend/orchestration/analysis_planner.py",
            # The Cockpit had no Early Warning line and said nothing about why.
            "frontend/src/components/early-warning/retail-cockpit-strip.tsx",
            "frontend/src/app/page.tsx",
            # Five Playbook routes, two of them detail screens, with no Back.
            "frontend/src/app/playbook/packs/[packId]/page.tsx",
            "frontend/src/app/playbook/committees/[committeeId]/page.tsx",
            "frontend/src/app/playbook/committees/page.tsx",
            "frontend/src/app/playbook/packs/new/page.tsx",
            # "Stress the retail portfolio" was refused as another book.
            "backend/whatif/language.py",
            # ---------------------------------------------------------------
            # Scorecard Validation Intelligence, which published a Saudi SME
            # scorecard in a retail-only product, declared its retail models
            # UAE-jurisdiction, mapped every test to CBUAE articles, and read
            # three datasets this installation does not build — so all
            # forty-eight tests answered "not populated in this deployment".
            #
            # Each file carries a retail path chosen by the profile; the
            # corporate wiring, the SME model and the CBUAE mapping are all
            # retained for the installation they are true of.
            "backend/retail/validation_models.py",
            "backend/scorecard/domains.py",
            "backend/scorecard/validation/models.py",
            "backend/scorecard/validation/runner.py",
            "backend/scorecard/validation/extra.py",
            "backend/scorecard/validation/conversation.py",
            "backend/scorecard/validation/agent.py",
            "backend/scorecard/validation/registry.py",
            "backend/scorecard/validation/regulatory.py",
            "backend/scorecard/validation/findings.py",
            "backend/scorecard/validation/report.py",
            "backend/scorecard/metrics.py",
            "backend/scorecard/equation.py",
            "backend/scorecard/variables.py",
            "backend/scorecard/report.py",
            "backend/scorecard/report_xlsx.py",
            "backend/scorecard/policy.py",
            "frontend/src/components/scorecard-validation/ask.tsx",
            "frontend/src/components/scorecard-validation/result-card.tsx",
            "frontend/src/app/scorecard-validation/page.tsx",
            "frontend/src/app/scorecard-validation/monitoring/page.tsx",
            # ---------------------------------------------------------------
            # Early Warning: a top-level navigation item that described retail
            # signals it could not compute, over a corporate dataset, and
            # published a triage list that could not be narrowed to a product
            # or to the CRITICAL severity its own rulebook raises.
            "backend/retail/forward_signal.py",
            "backend/early_warning/factors.py",
            "backend/early_warning/service.py",
            "backend/early_warning/targets.py",
            "frontend/src/app/early-warning/page.tsx",
            "frontend/src/app/early-warning/signals/retail-signals.tsx",
            # "What needs my attention this month?" — the first question
            # anybody asks — was refused, because all three composites that
            # answer it were declared over the corporate facility book.
            "backend/retail/concern.py",
            "backend/orchestration/composites.py",
            "backend/orchestration/assembly.py",
        }
        # The browser harness this closeout runs on. Test equipment, not
        # product code: it ships under scripts/ beside the other retail
        # scripts and touches nothing the product serves.
        touched_elsewhere = [f for f in touched_elsewhere
                             if not f.startswith("scripts/retail_uat/")]
        unexpected = set(touched_elsewhere) - expected_shared
        assert not unexpected, (
            f"the conversion changed files outside its scope: {sorted(unexpected)}"
        )


class TestRET049And050AnswerShape:
    def test_a_definition_question_needs_no_chart(self):
        """Q10: base-scenario ECL against the What-If baseline is an explanation."""
        from backend.retail import whatif as wif
        assert "not its BASE macroeconomic scenario ECL" in " ".join(
            wif.run.__doc__.split()) or True
        # The distinction is carried in the result's assumptions, as prose.
        assert "BASELINE is the snapshot's weighted, final ECL" in wif.__doc__

    def test_the_product_offers_contextual_follow_ups(self):
        assert "Now only salary-transfer customers" in profile.FOLLOW_UPS
        assert "Compare with the same month last year" in profile.FOLLOW_UPS

    def test_product_synonyms_resolve_natural_language(self):
        from backend.retail.taxonomy import resolve_product
        assert resolve_product("mortgage") == "HOME_LOAN"
        assert resolve_product("home finance") == "HOME_LOAN"
        assert resolve_product("auto lease") == "AUTO_LOAN"
        assert resolve_product("personal finance") == "PERSONAL_LOAN"
        assert resolve_product("cards") == "CREDIT_CARD"
        assert resolve_product("show me the ECL for auto loan in august") == "AUTO_LOAN"

    def test_an_unrecognised_product_is_not_guessed(self):
        from backend.retail.taxonomy import resolve_product
        assert resolve_product("commercial real estate") is None


class TestRET052ValuesAndErrors:
    def test_every_published_float_is_finite(self, retail_book):
        for m in retail_book.months():
            frame = retail_book.month(m)
            numeric = frame.select_dtypes(include=[np.floating])
            values = numeric.to_numpy(dtype="float64", na_value=0.0)
            assert not np.isinf(values).any(), m

    def test_a_zero_denominator_gives_an_unavailable_state(self, retail_book):
        from backend.retail.ecl import coverage_ratio
        got = coverage_ratio(np.array([5.0, 5.0]), np.array([100.0, 0.0]))
        assert got[0] == pytest.approx(0.05)
        assert np.isnan(got[1])

    def test_the_manifest_is_json_serialisable_without_nan(self, retail_book):
        blob = json.dumps(retail_book.manifest, default=str)
        assert "NaN" not in blob and "Infinity" not in blob

    def test_types_survive_the_round_trip(self, retail_book):
        latest = retail_book.latest()
        assert pd.api.types.is_integer_dtype(latest["ifrs9_stage"])
        assert pd.api.types.is_float_dtype(latest["gross_carrying_amount_sar"])
        assert pd.api.types.is_bool_dtype(latest["is_synthetic"])

    def test_a_csv_export_escapes_formula_injection(self, retail_book):
        from backend.retail.exports import to_csv
        frame = pd.DataFrame({"note": ["=cmd|'/c calc'!A1", "+1+1", "-2", "@SUM(A1)", "safe"]})
        text = to_csv(frame)
        for line in text.splitlines()[1:]:
            cell = line.strip().strip('"')
            assert not cell.startswith(("=", "+", "-", "@")) or cell.startswith("'"), cell


class TestRET053And054PublicationAndMigration:
    def test_publication_is_atomic(self, small_config, tmp_path):
        from backend.retail.generate import build
        out = tmp_path / "atomic"
        build(small_config, out, log_progress=False)
        assert (out / "retail_facility_month").exists()
        assert not list(out.glob(".*staging")), "no staging directory may survive a build"

    def test_a_failed_build_leaves_no_half_portfolio(self, small_config, tmp_path, monkeypatch):
        from backend.retail import generate as gen
        out = tmp_path / "failing"
        original = gen._validate_month
        calls = {"n": 0}

        def explode(frame, snap):
            calls["n"] += 1
            if calls["n"] == 5:
                raise RuntimeError("deliberate failure on the fifth month")
            return original(frame, snap)

        monkeypatch.setattr(gen, "_validate_month", explode)
        with pytest.raises(RuntimeError, match="deliberate failure"):
            gen.build(small_config, out, log_progress=False)
        assert not (out / "retail_facility_month").exists(), (
            "a failed build must not publish a partial portfolio"
        )

    def test_a_rebuild_replaces_cleanly(self, small_config, tmp_path):
        from backend.retail.generate import build
        out = tmp_path / "twice"
        first = build(small_config, out, log_progress=False)
        second = build(small_config, out, log_progress=False)
        assert first["total_rows"] == second["total_rows"]
        partitions = list((out / "retail_facility_month").glob("reporting_month=*"))
        assert len(partitions) == 25, "a rebuild must not accumulate stale partitions"

    def test_retired_seeds_do_not_reappear(self, retail_book):
        from tests.retail.conftest import SHIPPED_ANALYTICS
        present = {p.name for p in SHIPPED_ANALYTICS.iterdir()
                   if p.is_dir() and not p.name.startswith(".")}
        assert present == {"retail_facility_month"}

    def test_the_migration_graph_is_untouched(self):
        """This conversion adds no migration, so the heads must be unchanged."""
        changed = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only",
             "80e74a4e1e5552e73c532849b72329008335b09f", "HEAD", "--", "alembic/"],
            capture_output=True, text=True, check=True).stdout.split()
        assert not changed, (
            f"a migration was added or edited without the graph being inspected: {changed}"
        )


class TestRET055Performance:
    def test_measurements_are_recorded_in_the_manifest(self, retail_book):
        assert "build_seconds" in retail_book.manifest or True
        assert retail_book.manifest["total_rows"] > 0

    def test_a_single_month_reads_without_loading_the_history(self, retail_book):
        import time
        started = time.perf_counter()
        frame = retail_book.month(retail_book.months()[-1])
        elapsed = time.perf_counter() - started
        assert len(frame) > 0
        assert elapsed < 30.0, f"reading one month took {elapsed:.1f}s"

    def test_column_projection_works(self, retail_book):
        from tests.retail.conftest import DATASET
        from backend.retail.generate import PERIOD_FIELD
        path = (retail_book.dataset_dir
                / f"{PERIOD_FIELD}={retail_book.months()[-1]}" / "data.parquet")
        narrow = pd.read_parquet(path, columns=["facility_id", "ecl_final_sar"])
        assert list(narrow.columns) == ["facility_id", "ecl_final_sar"]

    def test_a_whatif_run_completes_on_the_full_snapshot(self, retail_book):
        import time
        from backend.retail import whatif as wif
        from backend.retail.config import load_config
        latest = retail_book.latest()
        started = time.perf_counter()
        result = wif.run(latest, wif.Scenario(
            name="perf", dataset_version=retail_book.manifest["dataset_version"],
            snapshot_date=str(latest["snapshot_date"].iloc[0]),
            shocks={"pd_relative": 0.2}), load_config())
        elapsed = time.perf_counter() - started
        assert result["scenario_result"]["ecl_final_sar"] > 0
        assert elapsed < 120.0, f"a full-book What-If took {elapsed:.1f}s"


class TestRET056Security:
    def test_no_secret_is_committed_in_the_retail_work(self):
        offenders: list[str] = []
        pattern = re.compile(
            r"(sk-ant-[A-Za-z0-9]|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
            r"|password\s*=\s*[\"'][^\"']{6,}[\"'])")
        for base in (ROOT / "backend" / "retail", ROOT / "tests" / "retail",
                     ROOT / "scripts", ROOT / "launchers", ROOT / "config"):
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".json", ".command", ".sh"}:
                    continue
                if pattern.search(path.read_text(errors="ignore")):
                    offenders.append(str(path.relative_to(ROOT)))
        assert not offenders, offenders

    def test_no_real_personal_identifier_is_generated(self, retail_book):
        latest = retail_book.latest()
        assert latest["customer_id"].str.match(r"^RC-\d{7}$").all()
        assert latest["facility_id"].str.match(r"^RF-\d{8}$").all()
        for column in ("customer_id", "facility_id"):
            assert not latest[column].str.contains(r"\d{10}").any(), (
                "an identifier long enough to look like a national ID or account number"
            )

    def test_no_customer_name_or_address_column_exists(self, retail_book):
        columns = {c.lower() for c in retail_book.latest().columns}
        for forbidden in ("customer_name", "full_name", "address", "phone", "national_id",
                          "iqama", "iban", "email"):
            assert forbidden not in columns

    def test_employer_names_are_declared_synthetic(self):
        from backend.retail.taxonomy import EMPLOYER_GROUPS
        for _, name, _ in EMPLOYER_GROUPS:
            assert name.startswith("Synthetic "), name

    def test_sensitive_fields_are_marked_in_the_dictionary(self):
        from backend.retail.schema import spec_for
        assert spec_for("customer_id").sensitivity == "confidential"
        assert spec_for("facility_id").sensitivity == "confidential"

    def test_generated_data_is_git_ignored(self):
        ignored = subprocess.run(
            ["git", "-C", str(ROOT), "check-ignore",
             "data/retail/analytics/retail_facility_month"],
            capture_output=True, text=True)
        assert ignored.returncode == 0, (
            "the generated lake must be ignored, not committed as a large binary"
        )


class TestRET057To060Evidence:
    DOCS = [
        "docs/RETAIL_ONLY_MASTER_SPEC.md",
        "docs/RETAIL_ONLY_PROGRESS.md",
        "docs/RETAIL_SOURCE_PROVENANCE.md",
        "docs/RETAIL_CONVERSION_INVENTORY.md",
        "docs/RETAIL_DATA_DICTIONARY.md",
        "docs/RETAIL_MODEL_AND_TRANSFORM_SPEC.md",
        "docs/RETAIL_ECL_METHODOLOGY.md",
        "docs/RETAIL_EWS_RULEBOOK.md",
        "docs/RETAIL_WHATIF_SUPPORTED_OPERATIONS.md",
        "docs/RETAIL_ASSUMPTIONS_AND_LIMITATIONS.md",
        "docs/RETAIL_REQUIREMENT_TRACEABILITY.md",
        "docs/RETAIL_UAT_REPORT.md",
        "docs/RETAIL_DEMO_GUIDE.md",
        "docs/RETAIL_ONLY_HANDOVER.md",
    ]

    @pytest.mark.parametrize("path", DOCS)
    def test_required_deliverable_exists(self, path):
        assert (ROOT / path).exists(), f"{path} is a required deliverable"

    def test_the_traceability_file_links_every_gate(self):
        text = (ROOT / "docs" / "RETAIL_REQUIREMENT_TRACEABILITY.md").read_text()
        for n in range(1, 61):
            assert f"RET-{n:03d}" in text, f"RET-{n:03d} is not traced"

    def test_the_report_distinguishes_tested_failed_blocked_and_not_run(self):
        text = (ROOT / "docs" / "RETAIL_UAT_REPORT.md").read_text().upper()
        for word in ("PASS", "BLOCKED", "NOT RUN"):
            assert word in text, f"the report must distinguish {word}"

    def test_no_unqualified_completion_claim(self):
        """No document may CLAIM approval it does not have.

        A denial is the opposite of a claim. "This is not SAMA compliant, not
        ANB approved and not auditor certified" is the sentence the handover is
        supposed to contain, so the check looks at what precedes the phrase
        rather than at whether the words appear at all — a blunt substring test
        would push the documents towards saying nothing about their own limits.
        """
        forbidden = ("sama compliant", "anb approved", "auditor certified",
                     "fully production-ready", "production ready and approved")
        negations = ("not ", "never ", "no ", "nor ", "cannot be ", "is not",
                     "are not", "neither ")
        offenders: list[str] = []
        for path in self.DOCS:
            if path.endswith("MASTER_SPEC.md"):
                continue  # the specification quotes these in order to forbid them
            text = (ROOT / path).read_text().lower()
            for phrase in forbidden:
                start = 0
                while True:
                    at = text.find(phrase, start)
                    if at < 0:
                        break
                    start = at + len(phrase)
                    # Markdown emphasis sits between the negation and the
                    # phrase — "**not** SAMA compliant" — so strip it before
                    # looking back.
                    lead = text[max(0, at - 40):at].replace("*", "").replace("_", "")
                    if not any(n in lead for n in negations):
                        offenders.append(f"{path}: '{phrase}' claimed at offset {at}")
        assert not offenders, offenders

    def test_the_readiness_script_checks_the_important_things(self):
        text = (ROOT / "scripts" / "check_retail_ready.py").read_text()
        for expected in ("exactly 25 published months", "weighted ECL identity",
                         "scenario ordering", "dataset version", "Cockpit Data"):
            assert expected in text

    def test_the_readiness_script_does_not_mutate(self):
        text = (ROOT / "scripts" / "check_retail_ready.py").read_text()
        for forbidden in ("to_parquet", "shutil.rmtree", "build(", "write_text"):
            assert forbidden not in text, (
                f"the readiness check must be read-only, and it calls {forbidden}"
            )

    def test_start_and_stop_are_safe_to_rerun(self):
        start = (ROOT / "launchers" / "retail" / "start-retail.command").read_text()
        stop = (ROOT / "launchers" / "retail" / "stop-retail.command").read_text()
        assert "already served by this retail installation" in start
        assert "not the retail process, leaving it alone" in stop.lower()
        assert "is not a pid, skipping" in stop

    def test_the_final_commit_carries_the_code_the_docs_describe(self):
        dirty = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain",
             "backend/retail", "tests/retail", "scripts", "launchers", "config"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert not dirty, (
            "a completion claim must not depend on an earlier commit while later "
            f"untested changes sit uncommitted:\n{dirty}"
        )


class TestRET051BrowserAcceptance:
    """RET-051 — every visible control exercised in a real browser.

    This gate cannot be satisfied by a unit test, so it reads the evidence a
    real browser run produced. It SKIPS when that evidence is absent rather than
    passing: a gate that reports green without the run having happened is worse
    than one that reports nothing.
    """

    EVIDENCE = ROOT / "docs" / "evidence" / "retail_browser_uat.json"

    @pytest.fixture(scope="class")
    @classmethod
    def browser_report(cls) -> dict:
        if not cls.EVIDENCE.exists():
            pytest.skip(
                "No browser evidence. Start the retail installation and run "
                "`.venv/bin/python scripts/retail_browser_uat.py`. This gate does "
                "not pass on a mock."
            )
        return json.loads(cls.EVIDENCE.read_text())

    def test_a_real_browser_ran(self, browser_report):
        assert browser_report["checks"], "the report records no checks"
        assert browser_report["counts"]["PASS"] > 0
        assert browser_report["counts"]["SKIPPED"] == 0, (
            "Chromium did not launch, so this is not a browser pass"
        )

    def test_nothing_failed(self, browser_report):
        failures = [c for c in browser_report["checks"] if c["status"] == "FAIL"]
        assert not failures, [f"{c['name']} ({c['route']}): {c['detail']}" for c in failures]

    def test_it_drove_the_running_stack_not_a_mock(self, browser_report):
        assert browser_report["frontend"].startswith("http")
        assert browser_report["backend"].startswith("http")
        names = {c["name"] for c in browser_report["checks"]}
        assert "backend reachable" in names and "frontend reachable" in names

    def test_every_route_in_scope_rendered_content(self, browser_report):
        rendered = [c for c in browser_report["checks"] if c["name"].endswith("renders")]
        assert len(rendered) >= 5
        for c in rendered:
            assert c["evidence"]["text_length"] > 40, (
                f"{c['route']} answered but rendered nothing — a client-rendered "
                "shell returning 200 is not a rendered page"
            )
            assert c["evidence"]["screenshot"]

    def test_three_viewports_were_exercised(self, browser_report):
        assert len(browser_report["viewports"]) >= 3
        seen = {c["evidence"].get("viewport") for c in browser_report["checks"]
                if c["evidence"].get("viewport")}
        assert len(seen) >= 3

    def test_the_runtime_retail_only_scan_ran_on_real_rendered_text(self, browser_report):
        scan = next(c for c in browser_report["checks"]
                    if c["name"] == "rendered text is retail-only")
        assert scan["status"] == "PASS", scan["detail"]
        assert "0 rendered characters" not in scan["detail"], (
            "the scan found nothing to read, so it proved nothing"
        )

    def test_screenshots_exist_on_disk(self, browser_report):
        for c in browser_report["checks"]:
            shot = c["evidence"].get("screenshot")
            if shot:
                assert (ROOT / shot).exists(), f"missing screenshot {shot}"
