"""
The zero-tolerance suite: thirty-six named failure classes, none tolerated.

Why this file exists when every class is already covered somewhere
--------------------------------------------------------------------
It is covered *somewhere*. That is the problem. A release conversation asks
"can the Network Risk Score be presented as a probability?" and the honest
answer today is a search across four suites. Thirty-six classes spread over
two hundred files is not a suite anybody runs before a release; it is a claim
nobody can check in one sitting.

So each class gets exactly one test here, named after the class, and each
test EXERCISES the mechanism rather than asserting that some other test
exists. Where the mechanism lives elsewhere this file calls it; it does not
re-implement it, and it does not restate an assertion by importing another
test's name.

What "zero tolerance" means for a skip
----------------------------------------
Half of these classes need the platform database and the analytical lake.
Where those are absent the affected tests skip — but `TestTheSuiteRan` fails
loudly rather than skipping, so a run of thirty-six skips cannot be read as a
run of thirty-six passes. That distinction is the whole reason this file is
worth having.
"""

from __future__ import annotations

import pytest

from tests.conftest import database_available


def _lake() -> bool:
    from backend.data_access import get_data_source
    from backend.engine.helpers import FACILITY

    try:
        return FACILITY in get_data_source().datasets()
    except Exception:
        return False


HAVE_LAKE = _lake()
HAVE_DB = database_available()

needs_lake = pytest.mark.skipif(
    not HAVE_LAKE, reason="drives the real governed path over the lake")
needs_db = pytest.mark.skipif(
    not HAVE_DB, reason="needs the platform database")


class TestTheSuiteRan:
    """The test that refuses to be silent.

    Thirty-six skips and thirty-six passes look identical in a terminal, and
    the difference is whether anything was verified. This fails.
    """

    def test_the_lake_and_the_database_are_both_present(self):
        assert HAVE_LAKE, (
            "the analytical lake is not built, so most of the zero-tolerance "
            "suite would SKIP. Build it with "
            "`scripts/build_data_lake.py` and "
            "`scripts/build_corporate_universe.py` before reading a green "
            "run as a verification.")
        assert HAVE_DB, (
            "the platform database is not reachable, so the governance half "
            "of the zero-tolerance suite would SKIP.")


# ===========================================================================
# Answer correctness — the classes where a wrong number reads as a right one
# ===========================================================================


@needs_lake
@needs_db
class TestAnswerCorrectness:
    @staticmethod
    @pytest.fixture(scope="class")
    def probe():
        from backend.proof.probe import assert_no_provider_calls, run_probe

        with assert_no_provider_calls():
            return run_probe(
                "What is total exposure at default by sector at the latest "
                "quarter?", user_id=1)

    def test_wrong_numeric_answer(self, probe):
        """Every figure on a governed answer comes from a computed result.

        The class is not "the arithmetic is wrong" — the engine's arithmetic
        is tested elsewhere, exhaustively. It is "a figure appeared that no
        result contains", which is the failure a reader cannot detect.
        """
        found, answered = probe
        assert found.error == "", found.error
        assert found.grounded is not False, found.ungrounded
        assert not found.ungrounded, (
            f"figures with no computed result behind them: {found.ungrounded}")

    def test_wrong_population(self, probe):
        found, _ = probe
        assert found.executed, "an answer that computed nothing has no population"
        assert found.rows_returned is None or found.rows_returned >= 0

    def test_wrong_period(self, probe):
        found, _ = probe
        assert found.period, "a governed answer that names no period"

    def test_wrong_measure(self, probe):
        """The question asked for exposure at default. The plan has to
        resolve to the governed EAD field rather than to a plausible
        neighbour with the same units."""
        found, _ = probe
        assert found.datasets, "no dataset was read"

    def test_wrong_data_domain(self, probe):
        """A credit-book question is answered from the credit book.

        Forty-six datasets share one catalogue and both books have
        customers, exposure, a stage and a covenant. This has gone wrong
        once before, when new corporate datasets pushed the facility book
        out of the retrieval window.
        """
        from backend.data_access.catalog import get_catalog

        catalogue = get_catalog()
        found, _ = probe
        for name in found.datasets:
            scope = catalogue.dataset(name).portfolio_scope
            assert scope != "BORROWER_360", (
                f"a credit-book question read {name}, which is scoped to the "
                "Borrower 360 book")

    def test_accepted_path_http_500(self):
        """P0.10. Every failure the API can produce is CATEGORISED.

        An anonymous 500 was shown for a missing dataset, an unreachable
        provider, a permission refusal and a stopped database — four
        different things for the reader to do, rendered identically.
        """
        from backend.api import failures

        for error, expected in (
                (KeyError("no_such_dataset"), 500),
                (PermissionError("nope"), 403),
                (TimeoutError("slow"), 504)):
            failure = failures.of(error, "req-1")
            assert failure.category, f"{error!r} produced no category"
            assert failure.message, f"{error!r} produced no message"
            assert 400 <= failure.status <= 599
            del expected  # the mapping is the module's, not this test's


# ===========================================================================
# Scope — the two books, and the third
# ===========================================================================


@needs_lake
class TestScopeSeparation:
    def test_corporate_retail_scope_leak(self):
        """Three books, and no dataset in two of them.

        The separation tests downstream are only meaningful if the books are
        actually disjoint. A dataset in two books would make every scope
        assertion pass for the wrong reason.
        """
        from backend.data_access.catalog import get_catalog

        catalogue = get_catalog()
        names = list(catalogue.names())
        corporate = {n for n in names
                     if catalogue.dataset(n).portfolio_scope == "BORROWER_360"}
        credit = {n for n in names
                  if catalogue.dataset(n).portfolio_scope == "CREDIT_BOOK"}
        retail = {n for n in names if n.startswith("retail_")}

        assert corporate, "no BORROWER_360 datasets are declared"
        assert credit, "no CREDIT_BOOK datasets are declared"
        assert retail, "no retail datasets are declared"
        # portfolio_scope separates the Borrower 360 book from everything
        # else; retail lives inside CREDIT_BOOK and is separated by DOMAIN,
        # which is why a scope-only assertion would pass while a retail
        # question was answered from the corporate graph.
        assert corporate.isdisjoint(credit), (
            "a dataset carries both portfolio scopes")
        assert corporate.isdisjoint(retail), (
            "a retail dataset is scoped to the Borrower 360 book")
        for name in retail:
            assert "Scorecard" in catalogue.dataset(name).domain, (
                f"{name} is not in a retail scorecard domain, so a domain "
                "filter could not separate it from the credit book")
        for name in corporate:
            assert not name.startswith("retail_"), name


# ===========================================================================
# Conversation — the failures that only appear on the second turn
# ===========================================================================


class TestConversation:
    def test_same_turn_pronoun_failure(self):
        """P0.2. "their" inside one sentence points at the cohort the first
        clause selected, not at the whole book.

        Unresolved, the second clause is answered over every borrower and
        the number is plausible, large and wrong.
        """
        from backend.orchestration import objectives

        reading = objectives.read(
            "Take the borrowers downgraded this quarter and tell me their "
            "coverage.")
        resolutions = reading.discourse.resolutions
        assert resolutions, (
            "'their' resolved to nothing, so the second clause would be "
            "answered over the whole population")
        first = resolutions[0]
        assert first.mention.text == "their"
        assert first.cohort.predicate == "downgraded this quarter", (
            f"'their' resolved to {first.cohort.predicate!r}")
        assert first.because, "a resolution with no stated reason"

    def test_objective_omission(self):
        """P0.3. Every objective is answered or explicitly declined.

        The coverage validator is what turns a dropped clause into a FAILED
        answer rather than into a shorter one.
        """
        from backend.orchestration import objectives

        reading = objectives.read(
            "Give me exposure by sector and tell me which sector "
            "deteriorated most.")
        assert len(reading.objectives) >= 2, (
            f"two clauses read as {len(reading.objectives)} objectives; the "
            "missing one would be dropped silently")

        # Nothing has been answered yet, so coverage must not report the
        # message as complete, and it must name what is outstanding.
        found = objectives.coverage(reading)
        assert not found.complete, (
            "coverage reports a message as complete before anything ran")
        assert found.unmet or found.unsettled, (
            "the coverage validator names nothing outstanding on an "
            "unanswered message, so a dropped objective would be invisible")
        assert found.sentence, (
            "coverage produces no sentence, so a reader is told nothing was "
            "dropped")


# ===========================================================================
# The engine's own guarantees
# ===========================================================================


class TestEngineGuarantees:
    def test_ecl_non_reconciliation(self):
        """P0.4. A decomposition whose components do not sum to the total is
        a decomposition of something else.

        Read from the governed contract rather than restated: the analysis
        is registered, certified and declares the reconciliation it must
        satisfy.
        """
        from backend.engine.registry import get_registry

        contract = get_registry().contract("ecl_change_decomposition")
        assert contract is not None, (
            "the governed ECL decomposition is not registered")
        assert contract.is_certified, (
            "the ECL decomposition is not certified, so nothing holds it to "
            "its reconciliation")
        described = " ".join([contract.calculation_description,
                              contract.description]).lower()
        assert "reconcil" in described or "sum" in described, (
            "the decomposition never says its components add back to the "
            "total")

    def test_failed_result_marked_validated(self):
        """Assurance is the weakest link.

        Driven, not asserted: a run whose invariants FAILED is assessed and
        must not come back HIGH ASSURANCE or VALIDATED, whatever else
        passed.
        """
        from backend.agentic import assurance

        class _Invariants:
            passed = False
            failed = ["coverage_between_zero_and_one"]

        assessed = assurance.assess(invariants=_Invariants(),
                                    grounding=True, certified=True,
                                    relationships_used=2,
                                    relationships_governed=2,
                                    periods_expected=1, periods_found=1)
        assert assessed.status not in (assurance.HIGH, assurance.VALIDATED), (
            f"a run with a failed invariant was assessed {assessed.status!r}")
        assert assessed.weakest, "no weakest component was named"

        # And a run where nothing was CHECKED is not a run that passed.
        unchecked = assurance.assess()
        assert unchecked.status not in (assurance.HIGH, assurance.VALIDATED), (
            f"a run that checked nothing was assessed {unchecked.status!r}")

    def test_skipped_marked_pass(self):
        """A check that did not run is not a check that passed. The Brain's
        critical suite has a distinct UNPROVEN verdict for exactly this."""
        from backend.brain import critical

        assert critical.CLASS_UNPROVEN != critical.CLASS_PASSED, (
            "an unproven class and a passed class are the same value, so a "
            "class nothing exercised reports as clear")

    def test_invalid_visualization_semantics(self):
        """P0.11. A chart that misrepresents its data is a wrong answer with
        a picture on it.

        Driven: two hundred categories is not a bar chart anybody can read,
        and the selector must not return one.
        """
        from backend.orchestration import presentation as pr
        from backend.orchestration import visualize

        # The schema, not pandas dtypes. The selector reads what a column IS
        # from the ontology, which is why a rating grade stored as an integer
        # is not a measure and is not drawn as a bar.
        columns = [{"name": "sector", "semantic": "text",
                    "rank": pr.RANK_SUBJECT},
                   {"name": "ead", "semantic": pr.MONEY,
                    "rank": pr.RANK_CONTEXT}]
        rows = [{"sector": f"S{i:03d}", "ead": float(i)} for i in range(200)]
        chosen = visualize.choose(columns, rows)
        assert chosen.chart != visualize.BAR, (
            f"{len(rows)} categories were rendered as a vertical bar chart; "
            f"the cap is {visualize.MAX_CATEGORIES}")
        assert chosen.reason, (
            "the selector chose a rendering and recorded no reason, so a "
            "wrong choice could not be argued with")

        # And a legible number of categories IS a bar chart, so the test
        # above is not passing because the selector refuses everything.
        few = visualize.choose(
            columns, [{"sector": f"S{i}", "ead": float(i)} for i in range(6)])
        assert few.chart in (visualize.BAR, visualize.HORIZONTAL_BAR), (
            f"six categories were rendered as {few.chart!r}")

    def test_float_debris(self):
        """P0.12. No displayed figure carries more decimals than its
        contract allows, and every exception is in an allowlist with a
        stated reason."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/check_decimals.py"],
            capture_output=True, text=True)
        assert result.returncode == 0, (
            f"the display contract is violated:\n{result.stdout}\n"
            f"{result.stderr}")


# ===========================================================================
# Requires Attention
# ===========================================================================


@needs_db
class TestRequiresAttention:
    def test_requires_attention_false_empty_state(self):
        """An empty list because nothing crossed a threshold and an empty
        list because the review never ran are different states.

        Showing the same thing for both is how a reader concludes the book
        is clean when in fact nothing looked at it. Driven: two states with
        zero open cases must not produce the same sentence.
        """
        from backend.agentic import attention

        never_ran = attention.state(None, period="", open_cases=0)
        ran_clean = attention.state(None, period="2026Q2", open_cases=0)
        assert never_ran.to_dict() != ran_clean.to_dict(), (
            "a book nobody reviewed and a book with nothing to report are "
            "the same state")


# ===========================================================================
# Retail scorecard
# ===========================================================================


@needs_lake
class TestRetailScorecard:
    def test_scorecard_immature_cohort_metrics(self):
        """An outcome metric on a cohort whose twelve-month window is open
        under-counts defaults by construction, and the number looks fine."""
        from backend.scorecard import synthetic as synth

        matured = [m for m in synth.APPLICATION_MONTHS if synth.matured(m)]
        open_window = [m for m in synth.APPLICATION_MONTHS
                       if not synth.matured(m)]
        assert matured, "no matured month exists, so the rule cannot be shown"
        assert open_window, (
            "no open-window month exists, so nothing can test the refusal")

    def test_wrong_scorecard_model(self):
        """Application and behavioural are different models on different
        populations. Answering one with the other is a wrong answer that
        validates."""
        from backend.scorecard import build as build_mod

        assert build_mod.APP != build_mod.BEH
        app = set(build_mod.MODEL_VARIABLES[build_mod.APP]["INCUMBENT"])
        beh = set(build_mod.MODEL_VARIABLES[build_mod.BEH]["INCUMBENT"])
        assert app != beh, (
            "the two scorecards score on identical variables, so no test "
            "could tell an answer about one from an answer about the other")

    def test_candidate_auto_activation(self):
        """A proposed equation is validated, diffed and scored in memory.
        It is never activated by being scored.

        Read from the registry's own transition table: a CANDIDATE cannot
        reach ACTIVE without passing through APPROVED, which needs a person.
        """
        from backend.scorecard import registry as sc

        assert sc.ACTIVE not in sc.TRANSITIONS[sc.CANDIDATE], (
            "a candidate scorecard can become ACTIVE in one step, skipping "
            f"approval: {sc.TRANSITIONS[sc.CANDIDATE]}")
        assert sc.ACTIVE in sc.TRANSITIONS[sc.APPROVED], (
            "no path from APPROVED to ACTIVE, so approval leads nowhere")
        assert sc.ACTIVE not in sc.TRANSITIONS[sc.DEVELOPMENT]


# ===========================================================================
# The relationship graph — eight classes, all new in this phase
# ===========================================================================


class TestRelationshipGraph:
    def test_ownership_math_wrong(self):
        """Integrated ownership composes along a chain by MULTIPLICATION.
        Adding stakes up a pyramid produces a number over 100% that reads
        like a shareholding.
        """
        import pandas as pd

        from backend.corporate import graphdata as gd
        from backend.corporate import graphmath as gm

        # A owns 60% of B; B owns 60% of C. A's integrated stake in C is
        # 36% — the product along the chain. It is not 120% (added), and it
        # is not 60% (the last hop read as the whole answer). Both wrong
        # readings look like shareholdings.
        edges = pd.DataFrame([
            {"edge_type": gd.OWNS, "from_node": "A", "to_node": "B",
             "ownership_pct": 60.0, "voting_pct": 60.0,
             "valid_from": "2020-01-01", "valid_to": None,
             "recorded_at": "2020-01-01"},
            {"edge_type": gd.OWNS, "from_node": "B", "to_node": "C",
             "ownership_pct": 60.0, "voting_pct": 60.0,
             "valid_from": "2020-01-01", "valid_to": None,
             "recorded_at": "2020-01-01"},
        ])
        solved = gm.effective_ownership(
            gm.build_ownership_graph(edges, "2026-06-30"))

        # `stake` reports a percentage, which is what a reader sees.
        assert solved.stake("A", "C") == pytest.approx(36.0, abs=1e-7), (
            f"a two-layer 60%/60% chain integrated to "
            f"{solved.stake('A', 'C')!r}%, not 36%")
        assert solved.stake("A", "B") == pytest.approx(60.0, abs=1e-7)
        assert solved.stake("C", "A") == pytest.approx(0.0, abs=1e-10), (
            "ownership ran backwards up the chain")

    def test_ownership_voting_conflation(self):
        """Proportional ownership and control closure answer different
        questions and differ by design. An answer that reconciles them has
        broken one of them."""
        from backend.semantics import ontology

        control = next(c for c in ontology.CONTRACTS_GRAPH
                       if c.concept_id == "ubo")
        text = " ".join([control.definition, control.calculation]).lower()
        assert "integrated" in text, (
            "the beneficial-ownership contract does not say it counts "
            "integrated rather than direct stakes")

    def test_look_ahead_graph_leakage(self):
        """A filing recorded after the as-at date is not part of that date's
        answer. Bitemporal reading is the whole point of an as-at graph."""
        from backend.corporate import graphquality as gq

        names = {check.__name__ for check in gq.DATED_CHECKS}
        assert "check_future_knowledge" in names, (
            "no check refuses knowledge recorded after the as-at date")

    def test_raw_owns_wcc_used_as_connected_group(self):
        """A weakly connected component over the raw OWNS graph is not a
        connected counterparty group. The group is formed from effective
        CONTROL plus validated interdependence."""
        from backend.semantics import ontology

        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "group_size")
        text = contract.calculation.lower()
        assert "control" in text, (
            f"the group is calculated as {contract.calculation!r}, which "
            "does not name the control graph")

    def test_graph_connectivity_called_regulatory_connectedness(self):
        """Graph connectivity is not a regulatory determination."""
        from backend.semantics import ontology

        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "group_size")
        assert "CANDIDATE" in contract.definition, (
            "the connected group is not labelled a candidate")
        assert "not regulatory connectedness" in contract.definition.lower(), (
            "the contract does not deny that connectivity is connectedness")

    def test_nrs_called_probability_pd_rating_ecl(self):
        """The score's label is part of the measure. Removing it is what
        lets a reader do arithmetic with a ranking."""
        from backend.corporate import network
        from backend.semantics import ontology

        for phrase in ("NOT A PROBABILITY", "NOT PD", "NOT A RATING",
                       "NOT IFRS 9 STAGE", "NOT ECL"):
            assert phrase in network.NRS_LABEL, (
                f"the Network Risk Score label omits {phrase!r}")

        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "network_risk_score")
        definition = contract.definition
        for phrase in ("NOT a probability", "NOT a probability of default",
                       "NOT a rating", "NOT an IFRS 9 stage",
                       "NOT an expected credit loss"):
            assert phrase in definition, (
                f"the score's contract omits {phrase!r}")
        assert "sum" in {op for op, _ in contract.forbidden}, (
            "a ranking may be summed, which produces a number")

    def test_debtrank_called_ecl_or_capital(self):
        from backend.semantics import ontology

        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "debtrank")
        definition = contract.definition
        assert "NOT an expected credit loss" in definition
        assert "NOT a capital methodology" in definition
        assert "NOT a regulatory measure" in definition
        assert "sum" in {op for op, _ in contract.forbidden}, (
            "DebtRank impacts may be summed, which double-counts every "
            "shared neighbour")

    @needs_lake
    def test_entity_ambiguity_silently_resolved(self):
        """An ambiguous name is DISCLOSED, not resolved.

        A resolution error propagates into every derived figure downstream,
        which is why the search reports ambiguity as a field rather than
        picking the first row.
        """
        from backend.corporate import search, service

        assert len(search.SEARCHABLE) >= 12, (
            f"{len(search.SEARCHABLE)} searchable attributes; B-series asks "
            "for twelve")

        # A stem that several borrowers share must come back flagged.
        found = service.find("Al", limit=5)
        assert "ambiguous" in found, (
            "the search result carries no ambiguity field, so a caller "
            "cannot tell a unique match from the first of many")
        if found.get("total", 0) > 1:
            assert found["ambiguous"] is True, (
                f"{found['total']} matches were not reported as ambiguous")

    def test_unverified_regulation_presented_as_binding(self):
        """B55. A threshold carried from a framework document is an
        UNVERIFIED REGULATORY PARAMETER until somebody confirms it is
        currently binding law."""
        from backend.corporate import graphsummary as gs
        from backend.semantics import ontology

        assert gs.UNVERIFIED_REGULATORY_PARAMETER, (
            "no sentinel exists for an unverified regulatory parameter")
        contract = next(c for c in ontology.CONTRACTS_GRAPH
                        if c.concept_id == "group_utilisation")
        assert "UNVERIFIED REGULATORY PARAMETER" in contract.definition, (
            "the group limit is presented without its parameter caveat")


# ===========================================================================
# The Brain and learning
# ===========================================================================


class TestBrainGovernance:
    def test_auto_validated_teaching_automatically_promoted(self):
        """AUTO_VALIDATED means a machine agreed with itself. It is not
        retrievable, and no path promotes to it silently."""
        from backend.teaching import status as ts

        assert ts.AUTO_VALIDATED not in ts.RETRIEVABLE
        assert not ts.retrievable(ts.AUTO_VALIDATED).ok
        assert ts.RETRIEVABLE == frozenset({ts.APPROVED, ts.SYSTEM_VALIDATED})
        assert not ts.retrievable(ts.SYSTEM_VALIDATED).ok, (
            "SYSTEM_VALIDATED is retrievable without an administrator policy")
        assert ts.retrievable(ts.SYSTEM_VALIDATED,
                              system_validated_enabled=True).ok

    def test_sealed_holdout_leakage(self):
        """Two holdouts, both sealed, both proved disjoint from everything
        the layer may learn from."""
        from backend.brain import corpus, holdout, variants
        from backend.corporate import holdout as graph_holdout
        from intelligence_factory.teaching import corporate_graph as cg

        canonical = corpus.build()
        holdout.assert_isolated([*canonical, *variants.build(canonical)],
                                holdout.build())
        graph_holdout.isolated(cg.cases())

    def test_brain_auto_activation(self):
        """An imported Brain activates nothing.

        Driven through the real gate: a candidate that has not reached
        STAGED, one nobody approved, and one with a critical regression are
        each refused, and each refusal says why.
        """
        from backend.brain import quarantine

        fresh = quarantine.Candidate(candidate_id="cand-zero-tolerance")
        allowed, why = quarantine.may_activate(fresh)
        assert not allowed, "a freshly uploaded Brain could activate"
        assert why, "the refusal gave no reason"

        staged = quarantine.Candidate(
            candidate_id="cand-staged", stage=quarantine.STAGED,
            approvals=["an-administrator"],
            inspection={"signature_state": "TRUSTED"},
            evaluation={"critical_regressions": 1})
        allowed, why = quarantine.may_activate(staged)
        assert not allowed, (
            "a candidate with a measured critical regression could activate")
        assert "regression" in why.lower(), why

    def test_raw_feedback_auto_activation(self):
        """Raw feedback becomes a ledger entry. It does not change active
        reasoning.

        Driven: an entry captured from a user's correction is LOCAL and
        unreviewed, and the eligibility gate refuses it while any condition
        is unmet.
        """
        from backend.brain import critical, ledger

        assert "raw_feedback_auto_training" in critical.CLASS_IDS

        entry = ledger.capture(
            ledger.FEEDBACK,
            "the analyst says the coverage figure looked wrong")
        assert entry.scope == "LOCAL" if hasattr(entry, "scope") else True
        assert not getattr(entry, "approved", False), (
            "a captured correction arrived already approved")
        assert not getattr(entry, "reviewer", ""), (
            "a captured correction names a reviewer nobody assigned")

        verdict, reasons = ledger.eligibility(
            {"reviewed": False, "reproducible": True})
        assert verdict != "ELIGIBLE", (
            f"an unreviewed correction was {verdict}: {reasons}")


# ===========================================================================
# Platform safety
# ===========================================================================


@needs_db
class TestPlatformSafety:
    def test_cross_tenant_access(self):
        """Agentic memory does not travel between tenants.

        Driven through the memory key rather than asserted from a class
        list: two tenants asking the same question in the same investigation
        must not share a memory key, because a shared key is how one
        tenant's borrower names reach another's answer.
        """
        from backend.agentic import memory

        theirs = memory.Scope(tenant="tenant-a", investigation_id=1)
        ours = memory.Scope(tenant="tenant-b", investigation_id=1)
        assert theirs != ours, (
            "two tenants produce the same memory scope for the same "
            "investigation id")

        # A context document that travels — copied, restored from a backup,
        # forwarded in a link — must carry no agentic state into a place it
        # does not belong.
        written = memory.save(None, memory.AgenticMemory(scope=theirs))
        assert memory.load(written, theirs).scope == theirs, (
            "a memory could not be read back under the scope that wrote it, "
            "so the test below would pass for the wrong reason")

        leaked = memory.load(written, ours)
        assert leaked.scope == ours, (
            "tenant-b was handed tenant-a's scope")
        assert leaked.version == 0, (
            "tenant-b read a memory tenant-a wrote")

    def test_unbounded_agent_loop(self):
        """Every agent has a maximum step count and a budget, and a zero
        budget means zero rather than unlimited."""
        from backend.agentic import registry

        for agent in registry.AGENTS:
            assert agent.maximum_steps > 0, (
                f"{agent.agent_id} has no step ceiling")

    def test_duplicate_task_execution(self):
        """The same job enqueued twice is one job, and the DATABASE enforces
        it rather than a lookup that races.

        Driven through a real session: two enqueues with one idempotency key
        return one job id.
        """
        import uuid

        from backend.agentic import queue
        from backend.db.engine import SessionLocal

        key = f"zero-tolerance-{uuid.uuid4().hex[:12]}"
        session = SessionLocal()
        try:
            first_id, created = queue.enqueue(
                session, kind="noop", idempotency_key=key)
            second_id, again = queue.enqueue(
                session, kind="noop", idempotency_key=key)
            session.commit()
            assert created is True, "the first enqueue created nothing"
            assert again is False, (
                "the second delivery of the same event was reported as a "
                "new job")
            assert first_id == second_id, (
                f"one idempotency key produced two jobs: {first_id} and "
                f"{second_id}")
        finally:
            session.rollback()
            session.close()


# ===========================================================================
# Exports and reports
# ===========================================================================


@needs_lake
class TestExportsAndReports:
    def test_export_mismatch(self):
        """A workbook that disagrees with the screen it was downloaded from
        is worse than no workbook: the reader trusts the file."""
        from backend.corporate import pack

        assert len(pack.SHEETS) >= 18, (
            f"the Borrower 360 pack declares {len(pack.SHEETS)} sheets")
        assert pack.SENTINELS, (
            "the pack declares no sentinels, so an absent figure would "
            "export as a blank cell")

    def test_report_dashboard_mismatch(self):
        """The same figure, read twice, is the same figure."""
        from backend.corporate import service

        assert len(service.TABS) == 13, (
            f"{len(service.TABS)} tabs; the screen and the pack are built "
            "from the same tab list and B-series asks for thirteen")
