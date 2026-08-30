"""The governed vocabulary the training corpus is composed from. §3, §5.

Every dataset, field, relationship, concept and agent named here is read back
out of the live registries at import time and checked. That is the point of
the module: a corpus written against remembered names drifts silently the
moment a dataset is retired or a field renamed, and then it trains the
intelligence layer on a portfolio that no longer exists. Here the drift is a
`VocabularyError` at import, before a single case is generated.

What is curated by hand is the ENGLISH: the phrase a credit officer would
actually use for `pd_ratio_to_origination`. That cannot be derived from a
field name, and a corpus of questions phrased in field names would teach the
layer to expect questions nobody asks.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agentic import registry
from backend.data_access.catalog import get_catalog
from backend.semantics.ontology import CONTRACTS_V2
from backend.services.relationships import GOVERNED_RELATIONSHIPS


class VocabularyError(Exception):
    """A name in the curated vocabulary that the governed registries deny."""


@dataclass(frozen=True)
class Measure:
    """A numeric field, and what an officer calls it."""

    dataset: str
    field: str
    phrase: str
    #: "money" totals, "rate" percentages, "ratio" multiples, "count" tallies,
    #: "score" indices. Decides the aggregation a correct plan may use: a rate
    #: must be weighted, not averaged, and that is a real defect class.
    kind: str

    @property
    def weighted(self) -> bool:
        """Whether a portfolio figure for this measure must be weighted."""
        return self.kind in ("rate", "ratio")


@dataclass(frozen=True)
class Dimension:
    """A grouping field, and what an officer calls it."""

    dataset: str
    field: str
    phrase: str


# ---------------------------------------------------------------- measures

_MEASURES: tuple[tuple[str, str, str, str], ...] = (
    # Retail scorecard validation. Registering a governed dataset without
    # measures would make the corpus skip it, which the guard test in
    # tests/brain/test_corpus.py exists to catch — a scorecard nobody can
    # ask a question about is a scorecard the Teaching Factory cannot
    # teach over.
    ("retail_application_scorecard_monthly_validation", "score_incumbent", "incumbent score", "score"),
    ("retail_application_scorecard_monthly_validation", "pd_incumbent", "incumbent PD", "rate"),
    ("retail_application_scorecard_monthly_validation", "score_challenger", "challenger score", "score"),
    ("retail_application_scorecard_monthly_validation", "monthly_income", "monthly income", "money"),
    ("retail_application_scorecard_monthly_validation", "debt_burden_ratio", "debt burden ratio", "ratio"),
    ("retail_application_scorecard_monthly_validation", "bureau_score", "bureau score", "score"),
    ("retail_application_scorecard_monthly_validation", "requested_amount", "requested amount", "money"),
    ("retail_application_scorecard_development_reference", "score_incumbent", "incumbent score", "score"),
    ("retail_application_scorecard_development_reference", "pd_incumbent", "incumbent PD", "rate"),
    ("retail_application_scorecard_development_reference", "score_challenger", "challenger score", "score"),
    ("retail_application_scorecard_development_reference", "monthly_income", "monthly income", "money"),
    ("retail_application_scorecard_development_reference", "debt_burden_ratio", "debt burden ratio", "ratio"),
    ("retail_application_scorecard_development_reference", "bureau_score", "bureau score", "score"),
    ("retail_application_scorecard_development_reference", "requested_amount", "requested amount", "money"),
    ("retail_behavioral_scorecard_monthly_validation", "score_incumbent", "incumbent score", "score"),
    ("retail_behavioral_scorecard_monthly_validation", "pd_incumbent", "incumbent PD", "rate"),
    ("retail_behavioral_scorecard_monthly_validation", "score_challenger", "challenger score", "score"),
    ("retail_behavioral_scorecard_monthly_validation", "current_balance", "current balance", "money"),
    ("retail_behavioral_scorecard_monthly_validation", "utilisation_pct", "utilisation", "rate"),
    ("retail_behavioral_scorecard_monthly_validation", "credit_limit", "credit limit", "money"),
    ("retail_behavioral_scorecard_monthly_validation", "max_dpd_6m", "worst days past due over six months", "count"),
    ("retail_behavioral_scorecard_development_reference", "score_incumbent", "incumbent score", "score"),
    ("retail_behavioral_scorecard_development_reference", "pd_incumbent", "incumbent PD", "rate"),
    ("retail_behavioral_scorecard_development_reference", "score_challenger", "challenger score", "score"),
    ("retail_behavioral_scorecard_development_reference", "current_balance", "current balance", "money"),
    ("retail_behavioral_scorecard_development_reference", "utilisation_pct", "utilisation", "rate"),
    ("retail_behavioral_scorecard_development_reference", "credit_limit", "credit limit", "money"),
    ("retail_behavioral_scorecard_development_reference", "max_dpd_6m", "worst days past due over six months", "count"),
    # portfolio_facility - the book itself
    ("portfolio_facility", "exposure", "exposure", "money"),
    ("portfolio_facility", "ead", "EAD", "money"),
    ("portfolio_facility", "model_ecl", "modelled ECL", "money"),
    ("portfolio_facility", "total_ecl", "total ECL", "money"),
    ("portfolio_facility", "undrawn", "undrawn commitment", "money"),
    ("portfolio_facility", "limit_amount", "approved limit", "money"),
    ("portfolio_facility", "collateral_value", "collateral value", "money"),
    ("portfolio_facility", "pd_12m_pct", "12-month PD", "rate"),
    ("portfolio_facility", "pd_lifetime_pct", "lifetime PD", "rate"),
    ("portfolio_facility", "lgd_pct", "LGD", "rate"),
    ("portfolio_facility", "ecl_coverage_pct", "ECL coverage", "rate"),
    ("portfolio_facility", "utilisation_pct", "limit utilisation", "rate"),
    ("portfolio_facility", "raroc_pct", "RAROC", "rate"),
    ("portfolio_facility", "downgrade_prob_pct", "downgrade probability",
     "rate"),
    ("portfolio_facility", "covenant_headroom_pct", "covenant headroom",
     "rate"),
    ("portfolio_facility", "dscr", "DSCR", "ratio"),
    ("portfolio_facility", "ai_risk_score", "AI risk score", "score"),
    ("portfolio_facility", "news_sentiment", "news sentiment", "score"),
    ("portfolio_facility", "dpd_days", "days past due", "count"),
    ("portfolio_facility", "rollover_count", "rollover count", "count"),
    # ifrs9_staging - the impairment view
    ("ifrs9_staging", "total_ecl", "total ECL", "money"),
    ("ifrs9_staging", "model_ecl", "modelled ECL", "money"),
    ("ifrs9_staging", "macro_overlay", "macro overlay", "money"),
    ("ifrs9_staging", "ead", "EAD", "money"),
    ("ifrs9_staging", "pd_12m_pct", "12-month PD", "rate"),
    ("ifrs9_staging", "pd_lifetime_pct", "lifetime PD", "rate"),
    ("ifrs9_staging", "pd_at_origination_pct", "PD at origination", "rate"),
    ("ifrs9_staging", "lgd_pct", "LGD", "rate"),
    ("ifrs9_staging", "ecl_coverage_pct", "ECL coverage", "rate"),
    ("ifrs9_staging", "pd_ratio_to_origination",
     "PD relative to origination", "ratio"),
    ("ifrs9_staging", "notches_since_origination",
     "notches since origination", "count"),
    ("ifrs9_staging", "quarters_clean", "clean quarters", "count"),
    # arrears and payment
    ("facility_delinquency", "arrears_amount", "arrears", "money"),
    ("facility_delinquency", "exposure_at_risk", "exposure at risk", "money"),
    ("facility_delinquency", "days_past_due", "days past due", "count"),
    ("facility_delinquency", "instalments_missed", "instalments missed",
     "count"),
    ("payment_history", "shortfall", "payment shortfall", "money"),
    ("payment_history", "amount_paid", "amount paid", "money"),
    ("payment_history", "scheduled_amount", "scheduled amount", "money"),
    # limits
    ("facility_limits", "limit_amount", "approved limit", "money"),
    ("facility_limits", "exposure", "drawn exposure", "money"),
    ("facility_limits", "excess_amount", "excess over limit", "money"),
    ("facility_limits", "utilisation_pct", "limit utilisation", "rate"),
    # return
    ("facility_profitability", "economic_profit", "economic profit", "money"),
    ("facility_profitability", "net_profit", "net profit", "money"),
    ("facility_profitability", "interest_revenue", "interest revenue",
     "money"),
    ("facility_profitability", "funding_cost", "funding cost", "money"),
    ("facility_profitability", "operating_cost", "operating cost", "money"),
    ("facility_profitability", "expected_loss_charge", "expected loss charge",
     "money"),
    ("facility_profitability", "regulatory_capital", "regulatory capital",
     "money"),
    ("facility_profitability", "raroc_pct", "RAROC", "rate"),
    ("facility_profitability", "risk_weight_pct", "risk weight", "rate"),
    # collateral and covenants
    ("collateral_register", "market_value", "collateral market value",
     "money"),
    ("collateral_register", "net_realisable_value", "net realisable value",
     "money"),
    ("collateral_register", "haircut_pct", "collateral haircut", "rate"),
    ("covenant_tests", "headroom", "covenant headroom", "money"),
    ("covenant_tests", "headroom_pct", "covenant headroom percentage",
     "rate"),
    ("covenant_tests", "actual_value", "tested covenant value", "ratio"),
    ("covenant_tests", "threshold", "covenant threshold", "ratio"),
    # recovery
    ("recoveries", "realised_lgd_pct", "realised LGD", "rate"),
    ("recoveries", "modelled_lgd_pct", "modelled LGD", "rate"),
    ("recoveries", "recovery_rate_pct", "recovery rate", "rate"),
    ("recoveries", "cash_recovered", "cash recovered", "money"),
    ("recoveries", "collateral_realised", "collateral realised", "money"),
    ("recoveries", "amount_written_off", "amount written off", "money"),
    ("recoveries", "ead_at_default", "EAD at default", "money"),
    # borrower and rating
    ("customer_ratings", "pd_12m_pct", "12-month PD", "rate"),
    ("customer_ratings", "net_leverage", "net leverage", "ratio"),
    ("customer_ratings", "interest_coverage", "interest cover", "ratio"),
    ("customer_ratings", "dscr", "DSCR", "ratio"),
    ("customer_ratings", "current_ratio", "current ratio", "ratio"),
    ("customer_ratings", "ebitda_margin_pct", "EBITDA margin", "rate"),
    ("customer_ratings", "revenue_usd_mn", "revenue", "money"),
    ("borrower_financials", "net_leverage_fy25", "FY25 net leverage",
     "ratio"),
    ("borrower_financials", "interest_coverage_fy25", "FY25 interest cover",
     "ratio"),
    ("borrower_financials", "dscr_fy25", "FY25 DSCR", "ratio"),
    ("borrower_financials", "current_ratio_fy25", "FY25 current ratio",
     "ratio"),
    ("rating_transitions", "notches_moved", "notches moved", "count"),
    # appetite, watchlist, climate
    ("risk_appetite_limits", "utilisation_of_limit_pct",
     "appetite limit utilisation", "rate"),
    ("risk_appetite_limits", "headroom_pct", "appetite headroom", "rate"),
    ("risk_appetite_limits", "actual_pct_of_book", "share of the book",
     "rate"),
    ("risk_appetite_limits", "book_exposure", "book exposure", "money"),
    ("watchlist_register", "total_ead", "watchlist EAD", "money"),
    ("climate_risk", "physical_risk_score", "physical risk score", "score"),
    ("climate_risk", "emissions_intensity", "emissions intensity", "score"),
    ("climate_risk", "scope_1_2_estimated", "estimated Scope 1 and 2 "
     "emissions", "score"),
    # models, macro, scenarios, credit file
    ("pd_model_performance", "predicted_pd_pct", "predicted PD", "rate"),
    ("pd_model_performance", "observed_default_rate_pct",
     "observed default rate", "rate"),
    ("pd_model_performance", "difference_pct_points",
     "gap between predicted and observed", "rate"),
    ("macro_saudi", "real_gdp_growth_pct", "real GDP growth", "rate"),
    ("macro_saudi", "non_oil_gdp_growth_pct", "non-oil GDP growth", "rate"),
    ("macro_saudi", "sama_policy_rate_pct", "SAMA policy rate", "rate"),
    ("macro_saudi", "inflation_pct", "inflation", "rate"),
    ("macro_saudi", "unemployment_pct", "unemployment", "rate"),
    ("macro_saudi", "brent_usd_bbl", "Brent", "score"),
    ("macro_saudi", "pmi_index", "PMI", "score"),
    ("macro_saudi", "credit_cycle_factor", "credit cycle factor", "score"),
    ("macro_saudi", "real_estate_price_index", "real estate price index",
     "score"),
    ("scenario_definitions", "gdp_growth_shock_pct", "GDP growth shock",
     "rate"),
    ("scenario_definitions", "oil_price_shock_pct", "oil price shock",
     "rate"),
    ("scenario_definitions", "policy_rate_shock_pct", "policy rate shock",
     "rate"),
    ("credit_memo_signals", "signal_strength_pct", "signal strength", "rate"),
    ("group_structure", "ownership_pct", "ownership", "rate"),
)

_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("retail_application_scorecard_monthly_validation", "application_channel", "application channel"),
    ("retail_application_scorecard_monthly_validation", "customer_segment", "customer segment"),
    ("retail_application_scorecard_monthly_validation", "product_type", "product type"),
    ("retail_application_scorecard_monthly_validation", "employer_type", "employer type"),
    ("retail_application_scorecard_development_reference", "application_channel", "application channel"),
    ("retail_application_scorecard_development_reference", "customer_segment", "customer segment"),
    ("retail_application_scorecard_development_reference", "product_type", "product type"),
    ("retail_application_scorecard_development_reference", "employer_type", "employer type"),
    ("retail_behavioral_scorecard_monthly_validation", "product", "product"),
    ("retail_behavioral_scorecard_monthly_validation", "vintage", "vintage"),
    ("retail_behavioral_scorecard_development_reference", "product", "product"),
    ("retail_behavioral_scorecard_development_reference", "vintage", "vintage"),
    ("portfolio_facility", "sector", "sector"),
    ("portfolio_facility", "region", "region"),
    ("portfolio_facility", "segment", "segment"),
    ("portfolio_facility", "product_type", "product type"),
    ("portfolio_facility", "rating_bucket", "rating bucket"),
    ("portfolio_facility", "grade_band", "grade band"),
    ("portfolio_facility", "exposure_grade", "exposure grade"),
    ("portfolio_facility", "collateral_type", "collateral type"),
    ("portfolio_facility", "obligor_group", "obligor group"),
    ("portfolio_facility", "owner_analyst", "relationship analyst"),
    ("portfolio_facility", "country", "country"),
    ("portfolio_facility", "risk_rating", "internal risk rating"),
    ("portfolio_facility", "sicr_trigger", "SICR trigger"),
    ("portfolio_facility", "trend", "trend direction"),
    ("ifrs9_staging", "sector", "sector"),
    ("ifrs9_staging", "segment", "segment"),
    ("ifrs9_staging", "ifrs9_stage", "IFRS 9 stage"),
    ("facility_delinquency", "dpd_bucket", "DPD bucket"),
    ("facility_delinquency", "collections_stage", "collections stage"),
    ("facility_delinquency", "forbearance_type", "forbearance type"),
    ("facility_delinquency", "sector", "sector"),
    ("facility_delinquency", "region", "region"),
    ("facility_delinquency", "product_type", "product type"),
    ("facility_limits", "approval_level", "approval level"),
    ("facility_limits", "product_type", "product type"),
    ("facility_profitability", "sector", "sector"),
    ("facility_profitability", "segment", "segment"),
    ("covenant_tests", "covenant_type", "covenant type"),
    ("covenant_tests", "status", "covenant test status"),
    ("covenant_tests", "covenant_name", "covenant"),
    ("collateral_register", "collateral_type", "collateral type"),
    ("collateral_register", "valuer", "valuer"),
    ("recoveries", "outcome", "recovery outcome"),
    ("recoveries", "legal_action", "legal action taken"),
    ("recoveries", "sector", "sector"),
    ("customer_ratings", "external_rating", "external rating"),
    ("customer_ratings", "rating_action", "rating action"),
    ("customer_ratings", "rating_bucket", "rating bucket"),
    ("customer_ratings", "sector", "sector"),
    ("customer_ratings", "region", "region"),
    ("borrower_financials", "external_rating", "external rating"),
    ("rating_transitions", "direction", "transition direction"),
    ("rating_transitions", "sector", "sector"),
    ("watchlist_register", "watchlist_category", "watchlist category"),
    ("watchlist_register", "reason", "watchlist reason"),
    ("watchlist_register", "relationship_owner", "relationship owner"),
    ("watchlist_register", "sector", "sector"),
    ("risk_appetite_limits", "sector", "sector"),
    ("risk_appetite_limits", "status", "appetite status"),
    ("climate_risk", "transition_risk_band", "transition risk band"),
    ("climate_risk", "physical_risk_band", "physical risk band"),
    ("climate_risk", "sector", "sector"),
    ("climate_risk", "region", "region"),
    ("pd_model_performance", "segment", "segment"),
    ("pd_model_performance", "model_version", "model version"),
    ("pd_model_performance", "calibration", "calibration status"),
    ("scenario_definitions", "scenario", "scenario"),
    ("scenario_definitions", "severity", "scenario severity"),
    ("credit_memo_signals", "memo_type", "memo type"),
    ("credit_memo_signals", "recommendation", "memo recommendation"),
    ("credit_memo_signals", "author_role", "author role"),
    ("credit_memo_signals", "sector", "sector"),
    ("group_structure", "relationship", "group relationship"),
    ("group_structure", "control_basis", "basis of control"),
    ("group_structure", "obligor_group", "obligor group"),
    ("payment_history", "payment_method", "payment method"),
    ("macro_saudi", "data_origin", "data origin"),
)


def _check() -> tuple[tuple[Measure, ...], tuple[Dimension, ...]]:
    """Read the catalogue and refuse anything it does not recognise."""
    catalogue = get_catalog()
    known: dict[str, set[str]] = {}
    for dataset in catalogue.all():
        fields = dataset.fields
        names = (set(fields) if hasattr(fields, "keys")
                 else {f.name for f in fields})
        known[dataset.name] = names

    problems: list[str] = []
    measures: list[Measure] = []
    for dataset, name, phrase, kind in _MEASURES:
        if dataset not in known:
            problems.append(f"measure on unknown dataset {dataset!r}")
        elif name not in known[dataset]:
            problems.append(f"{dataset}.{name} is not in the catalogue")
        else:
            measures.append(Measure(dataset, name, phrase, kind))

    dimensions: list[Dimension] = []
    for dataset, name, phrase in _DIMENSIONS:
        if dataset not in known:
            problems.append(f"dimension on unknown dataset {dataset!r}")
        elif name not in known[dataset]:
            problems.append(f"{dataset}.{name} is not in the catalogue")
        else:
            dimensions.append(Dimension(dataset, name, phrase))

    if problems:
        raise VocabularyError(
            "the training vocabulary names things the governed catalogue does "
            "not have, so the corpus would train on a portfolio that does not "
            "exist: " + "; ".join(sorted(problems)))
    return tuple(measures), tuple(dimensions)


MEASURES, DIMENSIONS = _check()

#: Every governed dataset, in catalogue order.
DATASETS: tuple[str, ...] = tuple(d.name for d in get_catalog().all())

#: Business name and grain, for questions that must quote them back.
DATASET_LABEL: dict[str, str] = {
    d.name: d.business_name for d in get_catalog().all()}
DATASET_GRAIN: dict[str, str] = {
    d.name: d.grain for d in get_catalog().all()}
DATASET_DOMAIN: dict[str, str] = {
    d.name: d.domain for d in get_catalog().all()}

#: The governed join graph, as shipped. A MULTI_DOMAIN case that does not sit
#: on one of these edges is asking for an ungoverned join.
RELATIONSHIPS = tuple(GOVERNED_RELATIONSHIPS)

#: The 25 ontology concepts, by id.
CONCEPTS: tuple[str, ...] = tuple(
    sorted(c.concept_id for c in CONTRACTS_V2))

#: The 12 registered agents, by id, and the ten specialists among them.
AGENTS: tuple[str, ...] = tuple(a.agent_id for a in registry.AGENTS)
SPECIALISTS: tuple[str, ...] = tuple(
    a for a in AGENTS if a not in ("chief_orchestrator", "data_steward"))

AGENT_LABEL: dict[str, str] = {
    a.agent_id: a.business_name for a in registry.AGENTS}

#: The four officer levels. Level decides who signs the answer, not who
#: computes it.
OFFICERS: dict[int, str] = {
    1: "Credit Analyst",
    2: "Senior Credit Officer",
    3: "Portfolio Risk Lead",
    4: "Chief Orchestrator",
}


def measures_for(dataset: str) -> tuple[Measure, ...]:
    return tuple(m for m in MEASURES if m.dataset == dataset)


def dimensions_for(dataset: str) -> tuple[Dimension, ...]:
    return tuple(d for d in DIMENSIONS if d.dataset == dataset)


#: The field a portfolio rate must be weighted by, per dataset. Absent means
#: the dataset carries no exposure-like magnitude, and a rate over it can only
#: be a plain average - which is a legitimate answer as long as the response
#: says so rather than presenting it as a portfolio figure.
WEIGHT_FIELD: dict[str, str] = {
    "portfolio_facility": "exposure",
    "ifrs9_staging": "ead",
    "facility_delinquency": "exposure_at_risk",
    "facility_limits": "exposure",
    "collateral_register": "market_value",
    "recoveries": "ead_at_default",
    "watchlist_register": "total_ead",
    "risk_appetite_limits": "book_exposure",
}

#: Datasets that are a time series in their own right rather than a book. A
#: "by sector" question over the macro series is not a harder version of the
#: portfolio question - it is a category error, and generating one would
#: teach the layer to accept it.
SERIES_DATASETS: frozenset[str] = frozenset(
    {"macro_saudi", "scenario_definitions"})

#: What to call the weighting field in a question. "The EAD-at-default
#: weighted realised LGD" is what an officer says; the field name is not.
WEIGHT_PHRASE: dict[str, str] = {
    "exposure": "exposure",
    "ead": "EAD",
    "exposure_at_risk": "exposure-at-risk",
    "market_value": "collateral value",
    "ead_at_default": "EAD-at-default",
    "total_ead": "EAD",
    "book_exposure": "book exposure",
}

#: Datasets that carry a reporting period. A "how has this moved over four
#: quarters" question over a dataset with no period field is unanswerable,
#: and asking it would teach the layer to fabricate a history.
PERIODIC: frozenset[str] = frozenset(
    d.name for d in get_catalog().all() if d.period_field)


def amount(measure: Measure) -> str:
    """"total ECL", not "total total ECL"."""
    phrase = measure.phrase
    if phrase.lower().startswith(("total ", "net ", "average ")):
        return phrase
    return f"total {phrase}"
