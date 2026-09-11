"""
Scorecard Validation, pointed at the book this installation actually has.

What was on screen
------------------
Every one of the forty-eight validation tests answered:

    Retail Application Scorecard has no periods with a realised outcome.
    is not populated in this deployment.

The module published three models — Retail Application, Retail Behaviour and
a **Saudi SME Scorecard** — wired to
`retail_application_scorecard_monthly_validation` and two siblings, which the
retail conversion does not build. §6 of the overnight brief is twenty
questions long and calls this module "central to the Head of Retail Risk /
auditor use case", and it answered none of them.

Four separate things were wrong:

  * a retail-only product published an SME scorecard;
  * both retail models declared their jurisdiction as the United Arab
    Emirates, in a Saudi retail book;
  * every test was mapped to a CBUAE MMS/MMG article and the coverage report
    was published under the heading "CBUAE Model Management Standards and
    Guidance" — again, UAE supervision in a Saudi product;
  * and the models read datasets that are not here, while
    `retail_facility_month` carries the score, the predicted PD, the realised
    outcome, the window-complete flag and, for every characteristic, its raw
    value, its bin, its weight of evidence and its points.

And a fifth, which is why repointing the old three would not have been
enough: this installation does not have one application scorecard. It has
four, one per product, and four behavioural scorecards beside them.
"""

from __future__ import annotations

import pytest

from backend.retail import profile
from backend.retail import validation_models as retail_validation
from backend.scorecard import domains
from backend.scorecard.validation import conversation, models as mdl
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import regulatory

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

PRODUCTS = ("CREDIT_CARD", "PERSONAL_LOAN", "AUTO_LOAN", "HOME_LOAN")


@pytest.fixture(scope="module")
def models():
    return mdl.all_models()


class TestTheServedScorecardsAreThisInstallationsOwn:
    def test_eight_are_served_one_per_product_per_kind(self, models):
        assert len(models) == 8
        pairs = {(m.scorecard_type, m.scope_value) for m in models}
        assert pairs == {(kind, product)
                         for kind in ("APPLICATION", "BEHAVIORAL")
                         for product in PRODUCTS}

    def test_no_sme_scorecard_is_served(self, models):
        """§26. A retail-only product does not validate an SME model."""
        assert domains.SCORECARD_SME not in domains.SCORECARD_DOMAINS
        for model in models:
            assert "sme" not in model.model_id.lower()
            assert "SME" != model.scorecard_type
            assert "sme" not in model.name.lower()

    def test_the_sme_code_is_retained_rather_than_deleted(self):
        """Not served is not the same as removed. The corporate build keeps it."""
        assert domains.SCORECARD_SME in domains.DEFINED_DOMAINS

    def test_the_jurisdiction_is_the_one_this_book_is_in(self, models):
        for model in models:
            assert model.jurisdiction == "Kingdom of Saudi Arabia"
            assert "Emirates" not in model.jurisdiction

    def test_every_model_reads_the_one_governed_book(self, models):
        for model in models:
            assert model.dataset == "retail_facility_month"
            assert model.period_field == "reporting_month"

    def test_the_governed_book_is_not_made_unreachable_to_the_cockpit(self):
        """The validation module reads the same published book as everything else.

        Registering it as restricted would take the product's only dataset
        away from the product to defend a boundary that does not exist here:
        there is no record-level validation extract to ring-fence.
        """
        assert not domains.is_restricted("retail_facility_month")

    def test_each_model_is_scoped_to_the_population_it_was_fitted_on(
            self, models):
        for model in models:
            assert model.scope_field == "product_code"
            assert model.scope_value in PRODUCTS
            assert ("monitoring_eligible_flag", True) in model.eligibility

    def test_the_maturity_rule_is_the_one_the_book_states(self, models):
        """ON-01 again, in a second module.

        `observed_default_within_window` is non-null on 47 rows at 2026-07 and
        every one of them is a default. A cohort scoped on a non-null outcome
        is the defaults and nothing else.
        """
        for model in models:
            assert model.matured_column == "performance_window_complete_flag"
            assert model.outcome_column == "observed_default_within_window"


class TestTheRegulatoryMappingClaimsNoJurisdictionItHasNot:
    def test_the_framework_is_not_another_countrys_supervisor(self):
        assert "CBUAE" not in regulatory.framework()
        assert "Emirates" not in regulatory.framework()

    def test_no_reference_is_shown_as_an_article_of_a_real_regulator(self):
        for requirement in regulatory.REQUIREMENTS:
            shown = regulatory.shown_as(requirement.reference)
            assert not shown.startswith("MMS")
            assert not shown.startswith("MMG")

    def test_no_sama_article_is_invented_to_replace_it(self):
        """The other way to get this wrong, and the worse one.

        Substituting a SAMA article number would be a fabricated citation.
        The expectations are generic validation practice and say so.
        """
        blob = " ".join([regulatory.framework(), regulatory.framework_note(),
                         *(regulatory.shown_as(r.reference)
                           for r in regulatory.REQUIREMENTS)])
        assert "SAMA" not in blob.upper().replace("SAMA'S", "")
        assert "no approved Regulatory Knowledge Release" in (
            regulatory.framework_note())

    def test_the_internal_reference_is_kept_as_the_join_key(self):
        """The test registry is not migrated for a display decision."""
        for requirement in regulatory.REQUIREMENTS:
            assert requirement.tests(), requirement.reference


class TestTheQuestionSetReachesTheRightModel:
    @pytest.mark.parametrize("question,model_id", [
        ("For the personal-finance application scorecard, show AUC, Gini "
         "and KS.", "retail_app_personal_loan"),
        ("what is the gini of the credit card behavioural scorecard",
         "retail_beh_credit_card"),
        ("show me the mortgage application scorecard psi",
         "retail_app_home_loan"),
        # The product and the kind, six words apart.
        ("Has the application-score distribution for personal finance "
         "materially shifted?", "retail_app_personal_loan"),
        ("Does the auto finance behavioural model still rank risk?",
         "retail_beh_auto_loan"),
    ])
    def test_the_scorecard_is_resolved(self, question, model_id):
        assert conversation.which_scorecard(question) == model_id

    @pytest.mark.parametrize("question", [
        # A kind with no product is ambiguous across four.
        "what is the application scorecard gini",
        # A product with no kind is ambiguous across two.
        "what is the personal finance gini",
        "how is the book doing",
    ])
    def test_an_ambiguous_question_resolves_to_nothing(self, question):
        """So the module asks, rather than picking whichever sorted first."""
        assert conversation.which_scorecard(question) == ""

    def test_which_scorecards_are_present_is_read_as_that_question(self):
        reading = conversation.read(
            "Which application and behavioural scorecards are present in this "
            "retail demo, by product and model version?")
        assert reading is not None
        assert reading.tool_id == "scv_list_models"

    def test_several_statistics_from_one_category_run_the_category(self):
        """"Show AUC, Gini and KS" answered with a Gini answers a third of it."""
        reading = conversation.read(
            "For the personal-finance application scorecard, show AUC, Gini "
            "and KS for the latest fully observed 12-month cohort.")
        assert reading is not None
        assert reading.tool_id == "scv_run_category"
        assert reading.parameters["category"] == "discrimination"
        assert reading.parameters["model_id"] == "retail_app_personal_loan"

    @pytest.mark.parametrize("question,test_id", [
        ("Show predicted versus observed default by score band for personal "
         "finance application.", "CAL-BAND"),
        ("Which scorecard inputs for the personal finance application "
         "scorecard show the largest increase in missing or out-of-range "
         "values?", "DATA-MISSING"),
        ("Is the production score implementation consistent with the "
         "configured transformations for personal finance application?",
         "IMPL-REPLICATE"),
    ])
    def test_the_question_reaches_the_test_that_answers_it(
            self, question, test_id):
        reading = conversation.read(question)
        assert reading is not None
        assert reading.parameters.get("test_id") == test_id


class TestTheSpecificationIsReadableAndTheScoreReproduces:
    def test_the_binning_specification_covers_every_characteristic(self):
        for kind in ("APPLICATION", "BEHAVIORAL"):
            spec = retail_validation.spec_for(kind)
            assert spec.variables
            for name, binned in spec.variables.items():
                assert binned.bins, name
                assert any(b.label == "MISSING" for b in binned.bins), name

    def test_every_model_has_a_readable_equation(self, models):
        for model in models:
            equation = model.approved_equation()
            assert equation.terms
            assert equation.score_mapping is not None
            # The retail engine's WoE column is `_transformed`.
            assert all(t.column().endswith("_transformed")
                       for t in equation.terms)

    def test_the_sign_convention_is_flipped_not_copied(self, models):
        """`logit_bad = intercept + Σ βw` here; `intercept - Σ cw` there.

        Same model, opposite sign on the coefficient. Transcribed without the
        flip, every row replicates to the wrong side of the scale and the
        implementation test reports the production score as broken.
        """
        from backend.retail.models_registry import APPLICATION_SCORECARDS

        card = APPLICATION_SCORECARDS["PERSONAL_LOAN"]
        equation = mdl.get("retail_app_personal_loan").approved_equation()
        by_name = {t.variable: t.coefficient for t in equation.terms}
        for feature in card.features:
            assert by_name[f"app_{feature.short}"] == pytest.approx(
                -float(feature.coefficient))


@pytest.fixture(scope="module")
def results(retail_book):
    from backend.scorecard.validation import runner

    model = mdl.get("retail_app_personal_loan")
    applicable = test_registry.applicable(model.capabilities())
    return {t.test_id: runner.run(t.test_id, model) for t in applicable}


class TestEveryTestProducesAResultOrSaysWhyNot:
    """The gate that would have caught this.

    Not "the module imports" and not "the endpoint returns 200": every
    applicable test, run against the real book, has to come back MEASURED or
    with a reason that is about the data rather than about the wiring.
    """


    def test_the_model_supports_most_of_the_registry(self):
        model = mdl.get("retail_app_personal_loan")
        applicable = test_registry.applicable(model.capabilities())
        assert len(applicable) >= 40

    def test_none_is_unavailable_for_want_of_a_dataset(self, results):
        from backend.scorecard.validation import states

        unavailable = {tid: r.detail for tid, r in results.items()
                       if r.state == states.UNAVAILABLE}
        assert not unavailable, (
            "a test reporting UNAVAILABLE on the book that carries its inputs "
            f"is a wiring fault, not a data finding: {unavailable}")

    def test_none_raised(self, results):
        from backend.scorecard.validation import states

        broken = {tid: r.detail for tid, r in results.items()
                  if r.state == states.CALCULATION_ERROR}
        assert not broken

    def test_the_production_score_reproduces_from_the_specification(
            self, results):
        from backend.scorecard.validation import states

        made = results["IMPL-REPLICATE"]
        assert made.state == states.PASS, made.detail
        assert made.value == 0.0

    def test_the_discrimination_is_a_retail_scorecards_discrimination(
            self, results):
        """Not 1.0, not 0.0, and not undefined — the ON-01 shape of failure."""
        gini = results["DISC-GINI"]
        assert gini.value is not None
        assert 0.1 < gini.value < 0.9, gini.detail
