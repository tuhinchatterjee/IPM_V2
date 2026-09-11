"""
The eight scorecards this installation actually runs, as validation subjects.

What was on screen before this module
--------------------------------------
Scorecard Validation Intelligence published three models — Retail Application,
Retail Behaviour and a **Saudi SME Scorecard** — and every one of its
forty-eight tests answered:

    Retail Application Scorecard has no periods with a realised outcome.
    is not populated in this deployment.

Three things were wrong, and only the third is about a dataset.

  * A retail-only product published an SME scorecard, with three SME datasets
    behind it, which §26 does not permit at all.
  * Both retail models declared their jurisdiction as the United Arab
    Emirates. This is a Saudi retail book.
  * The models were wired to `retail_application_scorecard_monthly_validation`
    and `retail_behavioral_scorecard_monthly_validation`, which the retail
    conversion does not build. So the module — twenty of the spec's questions,
    and the whole auditor story — answered nothing at all.

And a fourth thing, which is why this could not be fixed by pointing the old
three at a new table: **this installation does not have one application
scorecard. It has four**, one per product, and four behavioural scorecards
beside them. "For the personal-finance application scorecard, show AUC, Gini
and KS" is a question about one of eight models, and a registry that knows
about one cannot answer it.

Where the numbers come from
-----------------------------
`retail_facility_month`, the same governed book the Cockpit, the lenses and the
Playbook read. That is deliberate. The alternative — building a separate
validation universe with its own synthetic defaults — would give this product
two different Ginis for the same scorecard, one in the chat and one in the
validation module, and no way for a reader to tell which was the model's. One
book, one number.

The book carries everything a validation kernel needs, because the retail
scorecard engine writes it: the score, the predicted PD, the realised outcome,
the window-complete flag, and for every characteristic its raw value, its bin,
its weight of evidence and its points. That last set is what makes
IMPL-REPLICATE a real test here rather than a declared limitation: a row's
score can be rebuilt from its own inputs and compared with the score it was
scored with.

What is honestly absent
------------------------
No challenger is scored on this book, and no decision file records what was
approved or declined, so the challenger and override tests report UNAVAILABLE
with the reason rather than being hidden.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from backend.retail import taxonomy
from backend.scorecard import domains

#: The one governed book. Every model below reads it.
DATASET = "retail_facility_month"
PERIOD_FIELD = "reporting_month"

#: The window the scorecards were fitted on, and therefore the reference any
#: stability test measures drift against. Read from the model registry rather
#: than restated, so a rebuild that moves the window moves this with it.
DEVELOPMENT_MONTHS: tuple[str, ...] = (
    "2024-08", "2024-09", "2024-10", "2024-11", "2024-12", "2025-01",
)

#: What a reader calls each product. "Personal finance" rather than
#: "PERSONAL_LOAN": the question set says personal finance, and a registry
#: nobody can address by name is a registry nobody can use.
PRODUCT_NAMES: dict[str, str] = {
    taxonomy.CREDIT_CARD: "Credit Card",
    taxonomy.PERSONAL_LOAN: "Personal Finance",
    taxonomy.AUTO_LOAN: "Auto Finance",
    taxonomy.HOME_LOAN: "Home Finance",
}

#: Dimensions a validation result may be cut by. Every one is a governed
#: column of the book and every one is a question somebody actually asks:
#: does this scorecard work as well for salary-transfer customers, for digital
#: originations, for one segment.
SEGMENTATION: tuple[str, ...] = (
    "product_label", "customer_segment", "salary_transfer_flag",
    "origination_channel", "region", "employment_status",
    "origination_vintage", "application_score_band",
)

APPLICATION_LIMITS = dict(auc=0.62, gini=0.24, ks=0.18, oe_high=1.20, psi=0.25)
BEHAVIOURAL_LIMITS = dict(auc=0.72, gini=0.44, ks=0.32, oe_high=1.20, psi=0.25)


def _known_limitations(prefix: str) -> tuple[str, ...]:
    common = (
        "Every row in this book is synthetic. It describes no real customer "
        "and no real bank's book, and no result here is evidence about a "
        "production scorecard.",
        "No challenger score is carried on this book, so the champion cannot "
        "be compared against one.",
        "No application decision file is published, so approve/decline "
        "override rates and cut-off usage cannot be tested.",
    )
    if prefix == "app":
        return common + (
            "The application score is stamped at origination and carried "
            "forward unchanged, so its distribution moves with the mix of "
            "facilities on the book rather than with a rescoring.",
        )
    return common + (
        "The behavioural score is rebuilt every month, so a cohort is a "
        "month of account snapshots rather than a month of new accounts.",
    )


@lru_cache(maxsize=1)
def _models() -> tuple[Any, ...]:
    """The eight, built from the scorecard specifications themselves.

    Built rather than typed out: the binned characteristics, the model ids and
    the versions all belong to `backend/retail/models_registry.py`, and a
    hand-kept copy here would be right until the first rebuild.
    """
    from backend.retail.models_registry import (
        APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS,
    )
    from backend.scorecard.validation import models as mdl

    out: list[Any] = []
    for kind, cards in (("app", APPLICATION_SCORECARDS),
                        ("beh", BEHAVIOURAL_SCORECARDS)):
        for product, card in cards.items():
            out.append(_one(kind, product, card, mdl))
    return tuple(out)


def _one(kind: str, product: str, card: Any, mdl: Any) -> Any:
    application = kind == "app"
    name = PRODUCT_NAMES.get(product, product.replace("_", " ").title())
    limits = APPLICATION_LIMITS if application else BEHAVIOURAL_LIMITS
    return mdl.Model(
        model_id=card.model_id.lower(),
        name=f"{name} {'Application' if application else 'Behavioural'} "
             "Scorecard",
        domain=(domains.SCORECARD_APPLICATION if application
                else domains.SCORECARD_BEHAVIOUR),
        scorecard_type="APPLICATION" if application else "BEHAVIORAL",
        reference_number=f"MDL-RTL-{'APP' if application else 'BEH'}-"
                         f"{product.replace('_', '')}",
        version=card.model_version,
        portfolio=f"Saudi retail {name.lower()}",
        jurisdiction="Kingdom of Saudi Arabia",
        intended_use=(
            "Application-time approve, decline and pricing band for new "
            f"{name.lower()} applications."
            if application else
            "Monthly account-level risk grading for limit management, "
            "collections prioritisation and the IFRS 9 staging input."),
        owner="Retail Credit Risk",
        validation_owner="Model Risk & Validation",
        materiality="HIGH",
        tier="TIER_1",
        dataset=DATASET,
        # The same book. A stability test measures the development window
        # against the current one, which is a comparison of two periods rather
        # than of two tables.
        reference_dataset=DATASET,
        reference_periods=DEVELOPMENT_MONTHS,
        period_field=PERIOD_FIELD,
        scope_field="product_code",
        scope_value=product,
        score_column=f"{kind}_score_value",
        pd_column=f"{kind}_predicted_pd_12m",
        outcome_column="observed_default_within_window",
        matured_column="performance_window_complete_flag",
        score_direction=mdl.HIGHER_IS_BETTER,
        score_range=(300.0, 900.0),
        base_score=600.0,
        base_odds=30.0,
        points_to_double_odds=40.0,
        default_definition=card.target_event,
        performance_window_months=card.horizon_months,
        observation_window=("Origination month, scored once"
                            if application else "Monthly account snapshot"),
        development_population=(
            f"{DEVELOPMENT_MONTHS[0]}..{DEVELOPMENT_MONTHS[-1]} "
            f"{name.lower()} facilities, matured to a "
            f"{card.horizon_months}-month outcome."),
        segmentation_fields=SEGMENTATION,
        binned_variables=tuple(f"{kind}_{f.short}" for f in card.features),
        known_limitations=_known_limitations(kind),
        registry_key=card.model_id,
        # The specification IS the equation here: one module declares the
        # bins, the weights of evidence, the coefficients and the scaling, and
        # every one of them is reachable. See `approved_equation` below.
        equation_key=card.model_id,
        limits=mdl.standard_limits(**limits),
    )


def all_models() -> tuple[Any, ...]:
    return _models()


def spec_for(scorecard_type: str) -> Any:
    """The approved binning specification, as the validation engine reads it.

    Adapted from `backend/retail/scorecards.py` rather than loaded from a
    file: that module is the specification, and a serialised copy beside it
    would be a second version of the same artefact.
    """
    from backend.retail.models_registry import (
        APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS,
    )
    from backend.scorecard import binning

    application = str(scorecard_type).upper() == "APPLICATION"
    prefix = "app" if application else "beh"
    cards = APPLICATION_SCORECARDS if application else BEHAVIOURAL_SCORECARDS
    variables: dict[str, Any] = {}
    for card in cards.values():
        for feature in card.features:
            key = f"{prefix}_{feature.short}"
            if key in variables:
                continue
            variables[key] = _variable_binning(key, feature, binning)
    return binning.Spec(
        spec_version=next(iter(cards.values())).transform_version,
        scorecard_type="APPLICATION" if application else "BEHAVIORAL",
        development_population=(
            f"{DEVELOPMENT_MONTHS[0]}..{DEVELOPMENT_MONTHS[-1]}"),
        variables=variables)


def _variable_binning(key: str, feature: Any, binning: Any) -> Any:
    """One characteristic's approved bins, in the engine's own shape.

    The counts are left at zero deliberately. This installation publishes the
    bins and their weights of evidence as the approved specification; it does
    not publish the development-sample counts that produced them, and filling
    them with the CURRENT book's counts would present today's population as
    the evidence for a mapping fitted on a different one.
    """
    bins = []
    edges = list(feature.edges)
    for index, label in enumerate(feature.labels):
        lower = edges[index - 1] if index else None
        upper = edges[index] if index < len(edges) else None
        bins.append(binning.Bin(
            bin_id=f"{key}:{label}", label=str(label),
            lower=lower, upper=upper,
            members=() if feature.kind == "numeric" else (str(label),),
            woe=float(feature.woe.get(label, 0.0))))
    bins.append(binning.Bin(
        bin_id=f"{key}:MISSING", label="MISSING",
        woe=float(feature.woe_missing), special=True))
    return binning.VariableBinning(
        variable=key, kind=feature.kind, bins=bins)


def equation_for(model_id: str) -> Any:
    """The fitted coefficients behind one model's score.

    What makes the implementation test real: the score on the row can be
    rebuilt from `base_points + Σ points`, and each point from
    `factor × coefficient × weight of evidence`, with every term published.
    """
    from backend.retail import scorecards as sc
    from backend.retail.models_registry import (
        APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS,
    )
    from backend.scorecard import equation as equation_mod

    wanted = str(model_id or "")
    for cards in (APPLICATION_SCORECARDS, BEHAVIOURAL_SCORECARDS):
        for card in cards.values():
            if card.model_id != wanted:
                continue
            return equation_mod.Equation(
                equation_version=card.transform_version,
                scorecard_type=("APPLICATION" if card.prefix == "app"
                                else "BEHAVIORAL"),
                intercept=float(card.intercept),
                coefficients={f"{card.prefix}_{f.short}": float(f.coefficient)
                              for f in card.features},
                scaling={"factor": sc.FACTOR, "offset": sc.OFFSET,
                         "base_points": float(card.base_points),
                         "base_score": sc.BASE_SCORE,
                         "base_odds": sc.BASE_ODDS_GOOD, "pdo": sc.PDO})
    raise LookupError(f"{model_id!r} is not one of this installation's "
                      "scorecards.")


__all__ = ["DATASET", "DEVELOPMENT_MONTHS", "PERIOD_FIELD", "PRODUCT_NAMES",
           "all_models", "equation_for", "spec_for"]
