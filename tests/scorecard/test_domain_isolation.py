"""The boundary between Scorecard Validation and everything else.

Four things have to be true at once, and three of them are the kind that a
reader assumes rather than checks:

1. The specialist environment can read all three scorecard domains. A
   boundary that also blocks the thing it is protecting is not a boundary,
   it is an outage.
2. The specialist environment cannot read a fourth domain. Corporate
   covenants, IFRS 9 account detail, the Planner, the Playbook — a validator
   working on model risk has no route to any of them, and the refusal is a
   positive allowlist rather than a list of names somebody remembered to
   block.
3. The general Cockpit cannot read any of the three. This is the direction
   that is easy to leave open, because nothing breaks when it is: the
   general chat answers a scorecard question, it looks impressive, and a
   model validation has quietly happened outside the environment that
   governs it.
4. The governed aggregate metrics the Retail Risk Lens and the Playbook
   committee packs already publish still work. Thirty-three of them read
   these datasets. Breaking them to defend a boundary they never crossed
   would be the expensive kind of fix.

Why the tests go through `validate` rather than through the module
--------------------------------------------------------------------
`domains.permitted` returning False proves a dictionary lookup. What matters
is whether a *plan* naming the dataset is refused, because that is the shape
every real attempt takes: typed by a user, replayed from a saved query,
guessed by a model that read the name in a document, or written into a plan
by an instruction embedded in text the model was asked to summarise. All four
arrive as a SCAN, so all four are tested as one.
"""

from __future__ import annotations

import pytest

from backend.runtime.ir import AnalyticalPlan
from backend.runtime.validation import validate
from backend.scorecard import domains as D


def _plan(dataset: str) -> AnalyticalPlan:
    """The smallest plan that reads a dataset — which is all an attacker needs."""
    return AnalyticalPlan.from_dict({
        "version": "1.0",
        "operations": [{"id": "s1", "op": "SCAN",
                        "params": {"dataset": dataset}, "inputs": []}],
        "output": "s1",
    })


ALL_RESTRICTED = sorted(D.restricted_datasets())


def _built() -> set[str]:
    """The restricted datasets the governed catalogue actually knows about.

    The allowlist is deliberately allowed to run ahead of the builders: a
    dataset registered before it exists fails closed, which is the safe
    direction, and the Saudi SME domain is registered here from the moment
    the boundary is written rather than from the moment its Parquet appears.

    So the two layers are asserted separately and honestly. `permitted()` is
    the security contract and must hold for every registered name, built or
    not. `validate()` can only be exercised against a dataset the catalogue
    can resolve — for anything else it refuses on "not a governed dataset",
    which is a true answer to a different question and would make a green
    test that proves nothing.
    """
    from backend.data_access import get_catalog

    return set(get_catalog().names()) & D.restricted_datasets()


BUILT_RESTRICTED = sorted(_built())


# ============================================== 1. the specialist can read its own


class TestTheSpecialistReadsItsThreeDomains:

    @pytest.mark.parametrize("domain", D.SCORECARD_DOMAINS)
    def test_each_domain_is_declared_with_a_scorecard_type_and_datasets(self, domain):
        assert domain in D.DOMAIN_LABELS
        assert D.DOMAIN_SCORECARD_TYPE[domain]
        assert D.datasets_for(domain), (
            f"{domain} has no datasets, so nothing can be validated in it")

    @pytest.mark.parametrize("dataset", ALL_RESTRICTED)
    def test_validation_scope_is_permitted_every_restricted_dataset(self, dataset):
        assert D.permitted(dataset, scope=D.VALIDATION)

    @pytest.mark.parametrize("dataset", BUILT_RESTRICTED)
    def test_a_plan_in_validation_scope_reads_what_is_built(self, dataset):
        assert validate(_plan(dataset), scope=D.VALIDATION).ok, (
            f"the specialist environment cannot read {dataset}, which is the "
            "one thing it exists to do")

    def test_all_three_domains_are_covered_and_only_three(self):
        assert len(D.SCORECARD_DOMAINS) == 3
        covered = {D.domain_of(n) for n in ALL_RESTRICTED}
        assert covered == set(D.SCORECARD_DOMAINS), (
            "a declared domain has no datasets, or a dataset belongs to a "
            "domain that is not declared")


# ========================================== 2. the specialist cannot read a fourth


class TestTheSpecialistCannotReachOutside:

    @pytest.mark.parametrize("domain", [
        "covenants", "ifrs9", "exposure", "portfolio", "relationship",
        "planner", "playbook", "", "SCORECARD", "scorecard_corporate",
    ])
    def test_a_fourth_domain_is_refused(self, domain):
        assert not D.validation_domain_allowed(domain)
        with pytest.raises(D.DomainRefused):
            D.require_validation_domain(domain)

    @pytest.mark.parametrize("scorecard_type", [
        "CORPORATE", "IFRS9", "WHOLESALE", "", "sme_corporate", "ALL",
    ])
    def test_a_scorecard_type_outside_the_three_is_refused(self, scorecard_type):
        with pytest.raises(D.DomainRefused):
            D.require_scorecard_type(scorecard_type)

    @pytest.mark.parametrize("scorecard_type,expected", [
        ("APPLICATION", "APPLICATION"), ("application", "APPLICATION"),
        ("BEHAVIORAL", "BEHAVIORAL"), ("sme", "SME"), (" SME ", "SME"),
    ])
    def test_the_three_are_accepted_however_they_are_cased(
            self, scorecard_type, expected):
        assert D.require_scorecard_type(scorecard_type) == expected

    def test_the_refusal_says_what_the_scope_is_rather_than_only_no(self):
        with pytest.raises(D.DomainRefused) as caught:
            D.require_validation_domain("covenants")
        said = str(caught.value)
        assert "three" in said.lower()
        for label in D.DOMAIN_LABELS.values():
            assert label in said


# ================================ 3. the general Cockpit cannot read any of them


class TestTheGeneralCockpitIsShutOut:

    @pytest.mark.parametrize("dataset", ALL_RESTRICTED)
    def test_the_general_scope_is_refused_at_the_execution_gate(self, dataset):
        # Every registered name, built or not: the gate runs before the
        # catalogue lookup precisely so that "does this dataset exist?" is
        # not answerable by watching which refusal comes back.
        report = validate(_plan(dataset), scope=D.GENERAL)
        assert not report.ok, (
            f"the general Cockpit can read {dataset} — a record-level "
            "scorecard population with realised outcomes on it")
        assert any("Scorecard Validation" in r for r in report.reasons)

    def test_the_default_scope_is_the_restrictive_one(self):
        # A caller that never thought about scope gets the safe answer. This
        # is the whole of "fail closed" in one assertion: every existing
        # caller in the codebase passes no scope at all.
        report = validate(_plan(BUILT_RESTRICTED[0]))
        assert not report.ok

    @pytest.mark.parametrize("dataset", ALL_RESTRICTED)
    def test_discovery_does_not_offer_them_to_the_general_cockpit(self, dataset):
        from backend.orchestration import context

        context.invalidate()
        offered = {d.name for d in context.all_datasets()}
        assert dataset not in offered, (
            f"{dataset} is in the general Cockpit's dataset universe, so it "
            "can be searched, autocompleted or matched to a subject")

    def test_discovery_still_offers_the_rest_of_the_catalogue(self):
        # The filter must remove three domains, not empty the universe.
        from backend.orchestration import context

        context.invalidate()
        offered = {d.name for d in context.all_datasets()}
        assert len(offered) >= 20, (
            f"only {len(offered)} datasets remain — the restriction has taken "
            "more than the scorecard domains with it")
        assert "portfolio_facility" in offered

    def test_the_refusal_names_where_the_analysis_lives(self):
        said = D.refusal(BUILT_RESTRICTED[0])
        assert D.REDIRECT_SENTENCE in said
        action = D.redirect_action()
        assert action["route"] == "/scorecard-validation"
        assert action["kind"] == "navigate"

    def test_an_unrestricted_dataset_is_untouched_in_both_scopes(self):
        for scope in (D.GENERAL, D.VALIDATION, D.GOVERNED_METRIC):
            assert D.permitted("portfolio_facility", scope=scope)
        assert validate(_plan("portfolio_facility"), scope=D.GENERAL).ok


# ================================= 4. the governed aggregate surfaces still work


class TestPublishedMetricsAreNotCollateralDamage:
    """The Retail Risk Lens and Playbook committee packs read these datasets.

    They read them as *published metrics* — an approved formula, a declared
    period rule, one reviewed aggregate — which is a different act from
    letting a model compose a plan over the same rows. The boundary is drawn
    at conversational access, so this scope passes, and these tests are what
    stops a future tightening from taking two shipped surfaces down with it.
    """

    def test_the_governed_metric_scope_may_read_them(self):
        for dataset in ALL_RESTRICTED:
            assert D.permitted(dataset, scope=D.GOVERNED_METRIC)
        for dataset in BUILT_RESTRICTED:
            assert validate(_plan(dataset), scope=D.GOVERNED_METRIC).ok

    def test_the_metric_library_still_has_its_scorecard_metrics(self):
        from backend.metrics import library

        backed = [d for d in library.ALL
                  if any("scorecard" in t.dataset
                         for t in getattr(d.formula, "terms", ()) or ())]
        assert len(backed) >= 20, (
            f"only {len(backed)} governed metrics read the scorecard "
            "datasets; the Lens and the committee packs need them")

    def test_a_published_scorecard_metric_still_computes_a_real_figure(self):
        from tests.conftest import database_available

        if not database_available():
            pytest.skip("The metric runtime needs the data lake.")
        from backend.metrics import library
        from backend.metrics.execution import run

        backed = [d for d in library.ALL
                  if any("scorecard" in t.dataset
                         for t in getattr(d.formula, "terms", ()) or ())]
        if not backed:
            pytest.skip("No scorecard-backed metric in the library.")
        made = run(backed[0].formula)
        assert made.value is not None, (
            f"{backed[0].metric_id} returned no value — the restriction has "
            "reached the published metric path")
        assert not made.unavailable

    def test_only_the_two_governed_scopes_may_read_restricted_data(self):
        # An allowlist, asserted as one. Adding a scope must not grant it
        # access by default, and this fails if somebody adds a fourth scope
        # to MAY_READ_RESTRICTED without deciding that here.
        assert D.MAY_READ_RESTRICTED == frozenset({D.VALIDATION,
                                                   D.GOVERNED_METRIC})
        assert D.GENERAL not in D.MAY_READ_RESTRICTED


# ========================================================== the map is complete


class TestTheDatasetMapIsHonest:

    def test_every_scorecard_dataset_the_build_declares_is_registered(self):
        """A new scorecard dataset must be added to the map deliberately.

        The failure mode this catches is the quiet one: somebody adds a
        dataset to `backend/scorecard/catalogue.py`, it is published to the
        governed catalogue like any other, and the general Cockpit can read
        it because nobody thought to register it here.
        """
        from backend.scorecard import catalogue

        declared = {d["name"] for d in catalogue.datasets()}
        missing = sorted(declared - D.restricted_datasets())
        assert missing == [], (
            "these scorecard datasets are readable by the general Cockpit "
            "because they are not in DATASET_DOMAIN:\n  "
            + "\n  ".join(missing))

    def test_the_map_carries_no_dataset_that_does_not_exist(self):
        """The other direction: a name in the map that nothing builds.

        Harmless to security and corrosive to trust — a restriction on a
        dataset that was renamed protects nothing while reading as though it
        does. Datasets not yet built are allowed here, so this only checks
        that the map has no entry outside the scorecard package's own two
        builders.
        """
        from backend.scorecard import catalogue

        known = {d["name"] for d in catalogue.datasets()}
        try:
            from backend.scorecard.sme import catalogue as sme_catalogue

            known |= {d["name"] for d in sme_catalogue.datasets()}
        except ImportError:
            pass  # The SME domain is built later in this phase.
        unknown = sorted(n for n in D.restricted_datasets()
                         if n not in known and not n.startswith("sme_"))
        assert unknown == [], (
            f"restricted but built by nothing: {unknown}")
