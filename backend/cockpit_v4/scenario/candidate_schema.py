"""The relations the synthetic candidate release adds, and nothing it changes.

Section 3.3: *"Enrichment without corrupting the accepted data."* The two
accepted books stay exactly as they are — same relations, same columns, same
bytes — and everything this capability needs that they do not carry arrives as
NEW relations in a separately versioned release.

**Why new relations rather than new columns.** `lake.publish` does
`frame = frame[list(spec.columns)]` (`lake.py:199`), so a column that is not in
a relation's spec cannot be published at all, and widening an accepted spec
would change what the accepted release means. Joining instead costs one key and
keeps `corp_facility_quarter` the thirty-six columns it has always been —
which is also what makes `test_candidate_schema.py`'s "the accepted specs are
byte-identical" assertion possible.

**What a reader is owed about these numbers.** Every relation here is
`SYNTHETIC_DEMO`. The macro paths are generated, not observed; the ECL figures
come from `reference_ecl.py`, which is a documented calculator written for this
demonstration and is not a bank engine. Nothing produced from them may be
described as bank output or as economic history, and the `origin` column on
every row says so in the data rather than only in a document.

**The shape follows the legacy `v4-saudi-20q-v1` dataset**, read as a design
reference for what an IFRS 9 panel needs to carry — its macro window, scenario
weights, term structure, discount factors and modelled/overlay split. None of
its data is imported; 218 facilities of an unrelated portfolio under a
different schema would be a different book wearing this one's name.
"""

from __future__ import annotations

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.schema import GOVERNANCE_FIELDS, Field, Relation

#: The candidate releases. Separately versioned on purpose: a source change has
#: to be VISIBLE (section 3.3), and two books that share an id but differ in
#: content are exactly the substitution the release fingerprint exists to stop.
RELEASES: dict[str, str] = {
    dom.CORPORATE: "v4-whatif-corporate-20q-s1",
    dom.RETAIL: "v4-whatif-retail-20m-s1",
}

#: Stamped on every candidate row. `lake.ORIGIN` already says SYNTHETIC_DEMO in
#: the manifest; this puts it where a query lands, so a figure copied out of a
#: result carries its own provenance.
ORIGIN = "SYNTHETIC_DEMO"

#: The three economic scenarios and their weights. Section 9.1 wants the
#: scenario dimension and its weights explicit rather than pre-blended.
SCENARIOS: tuple[tuple[str, str, float], ...] = (
    ("baseline", "Baseline", 0.50),
    ("downside", "Downside", 0.30),
    ("upside", "Upside", 0.20),
)

#: Horizon buckets in the published term structure. Five for Corporate's
#: quarterly book and three for Retail's monthly one -- enough to carry a real
#: lifetime profile without publishing a row per facility per scenario per
#: month, which would be forty million rows of arithmetic nobody reads.
CORPORATE_HORIZONS = 5
RETAIL_HORIZONS = 3


def _f(name, dtype, unit, description, group="", label="",
       aggregation="") -> Field:
    return Field(name, dtype, unit, description, group, aggregation, label)


#: Carried by every candidate relation, beside the four governance columns the
#: accepted book already has. `origin` is the honesty column; `artifact_version`
#: lets a stale artifact be detected rather than silently reused (S16).
_CANDIDATE_FIELDS: tuple[Field, ...] = (
    _f("origin", "string", "",
       "SYNTHETIC_DEMO. These values were generated for a demonstration and "
       "are not bank engine output or observed economic history.",
       "Governance", label="Origin"),
)


def _macro(period_column: str, noun: str) -> tuple[Field, ...]:
    return GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
        _f("factor_id", "string", "",
           "Registry identifier, MEV01 to MEV20.", "Identity",
           label="Factor id"),
        _f(period_column, "string", "",
           f"The {noun} this observation belongs to.", "Calendar"),
        _f("scenario_id", "string", "",
           "Economic scenario: baseline, downside or upside.", "Scenario"),
        _f("country_or_region", "string", "",
           "The geography the series is measured for.", "Scenario"),
        _f("value", "double", "",
           "The factor's value in its own native unit. Read `native_unit` "
           "before comparing two factors.", "Measure",
           label="Native value"),
        _f("native_unit", "string", "",
           "What the value is measured in: percent, index, price or a named "
           "growth rate. A factor's own definition may already be a growth "
           "rate; a change in it is not therefore a growth rate.",
           "Measure"),
        _f("native_frequency", "string", "",
           "The frequency the series is published at, before any "
           "aggregation to this book's calendar.", "Measure"),
        _f("aggregation_rule", "string", "",
           "How a higher-frequency series was reduced to this period: "
           "period_end for a stock, mean for a rate, sum for a flow.",
           "Measure"),
        _f("observation_status", "string", "",
           "ACTUAL for a value known at the time, FORECAST for a projection "
           "from the recorded vintage.", "Provenance"),
        _f("forecast_vintage", "string", "",
           "The vintage a forecast came from. Empty for an actual.",
           "Provenance"),
        _f("published_at", "string", "",
           "When the value was first published.", "Provenance"),
        _f("available_at", "string", "",
           "When the value became available to a process running at the "
           "time. Later revisions are not known-at-the-time inputs.",
           "Provenance"),
    )


def _registry(period_column: str, noun: str) -> tuple[Field, ...]:
    return GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
        _f("factor_id", "string", "", "MEV01 to MEV20.", "Identity",
           label="Factor id"),
        _f(period_column, "string", "",
           f"The {noun} this registry is published as at.", "Calendar"),
        _f("factor_name", "string", "", "The candidate factor's name.",
           "Identity"),
        _f("native_level", "string", "",
           "What the series measures, stated as its own definition.",
           "Definition"),
        _f("shock_convention", "string", "",
           "How a shock to this factor is expressed: percentage points, "
           "basis points, relative percent, index points or native units. "
           "Reading one as another is the error section 5.1 names.",
           "Definition"),
        _f("native_unit", "string", "", "The unit of the published value.",
           "Definition"),
        _f("geography", "string", "", "The geography the series covers.",
           "Definition"),
        _f("native_frequency", "string", "",
           "The frequency the series is published at.", "Definition"),
        _f("series_id", "string", "",
           "The generated series this candidate factor maps to. Empty where "
           "the release has no series for it.", "Provenance"),
        _f("availability", "string", "",
           "PRESENT or ABSENT. An absent factor is reported absent, never "
           "as a zero sensitivity (section 7.1).", "Readiness"),
        _f("absent_reason", "string", "",
           "Why an absent factor is absent, and what depends on it.",
           "Readiness"),
    )


def _sensitivity(period_column: str, noun: str) -> tuple[Field, ...]:
    return GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
        _f("artifact_id", "string", "",
           "The sensitivity artifact this row belongs to.", "Identity"),
        _f("artifact_version", "string", "",
           "Artifact version. A scenario pinned to one version is not "
           "silently served another (S16).", "Identity"),
        _f(period_column, "string", "",
           f"The {noun} the artifact is published as at.", "Calendar"),
        _f("parameter", "string", "",
           "The risk parameter this sensitivity is for: pd_pit_12m, "
           "pd_lifetime or lgd_pct.", "Identity"),
        _f("factor_id", "string", "", "MEV01 to MEV20.", "Identity"),
        _f("lag", "int", "count",
           "Periods of lag, in this book's own calendar.", "Specification"),
        _f("transformation", "string", "",
           "What was fitted: the level, its change, or a standardised "
           "change.", "Specification"),
        _f("coefficient", "double", "",
           "The model-space coefficient, on the transformed factor against "
           "the logit of the parameter. Signed.", "Estimate"),
        _f("native_derivative", "double", "percentage points",
           "The scenario-friendly local slope: the parameter's change in "
           "percentage points per one native unit of the factor. Signed, "
           "and validated against a finite difference of the fitted "
           "function.", "Estimate", label="Native slope"),
        _f("native_derivative_unit", "string", "",
           "What one native unit of the factor means here, spelled out.",
           "Estimate"),
        _f("reference_parameter_value", "double", "probability_0_1",
           "The parameter value the derivative was evaluated at. A logit "
           "slope is local; without this the number is not usable.",
           "Estimate"),
        _f("reference_factor_value", "double", "",
           "The factor value the derivative was evaluated at.", "Estimate"),
        _f("standardised_response", "double", "percentage points",
           "The parameter's response to one training-period standard "
           "deviation of the factor. The stated ranking measure (7.4).",
           "Estimate"),
        _f("std_error", "double", "percentage points",
           "Block-resampled standard error of the native slope, in the same "
           "units as native_derivative. Zero where too few independent "
           "blocks were available to estimate one.", "Uncertainty"),
        _f("ci_low", "double", "percentage points",
           "Lower bound of the resampled interval, in the same units as "
           "native_derivative.", "Uncertainty"),
        _f("ci_high", "double", "percentage points",
           "Upper bound of the resampled interval, in the same units as "
           "native_derivative.", "Uncertainty"),
        _f("sign_stability", "double", "fraction_0_1",
           "The share of resamples agreeing with the point estimate's sign.",
           "Uncertainty"),
        _f("training_periods", "int", "count",
           "DISTINCT reporting periods used to fit. Not facility rows: "
           "twenty quarters repeated across thousands of facilities are "
           "still twenty quarters (section 7.3).", "Readiness"),
        _f("validation_periods", "int", "count",
           "Distinct periods held out for forward validation.", "Readiness"),
        _f("train_start", "string", "",
           "First training period.", "Readiness"),
        _f("train_end", "string", "",
           "Last training period.", "Readiness"),
        _f("effective_df", "double", "",
           "Effective PREDICTOR degrees of freedom after regularisation. "
           "The intercept is not charged against the complexity ceiling; "
           "SENSITIVITY_CARD_*.md records that reading and what the "
           "stricter one would cost.", "Readiness"),
        _f("max_df_allowed", "double", "",
           "The readiness policy's ceiling for this period count.",
           "Readiness"),
        _f("collinearity", "double", "",
           "Variance inflation against the other retained factors.",
           "Readiness"),
        _f("fit_error", "double", "",
           "In-sample mean absolute error, in logit space.", "Readiness"),
        _f("validation_error", "double", "",
           "Forward-validation mean absolute error, in logit space.",
           "Readiness"),
        _f("readiness", "string", "",
           "SUPPORTED_ESTIMATE, DIAGNOSTIC_ONLY, USER_ASSUMPTION, "
           "SYNTHETIC_DEMO, INSUFFICIENT_HISTORY, UNAVAILABLE or STALE.",
           "Readiness"),
        _f("limitation", "string", "",
           "What this estimate does not establish, in words.", "Readiness"),
        _f("support_low", "double", "",
           "Smallest factor value the training window covered.",
           "Readiness"),
        _f("support_high", "double", "",
           "Largest factor value the training window covered.",
           "Readiness"),
        _f("method", "string", "",
           "The estimator that produced this row.", "Provenance"),
        _f("source_release_id", "string", "",
           "The release the fit was made against.", "Provenance"),
        _f("source_fingerprint", "string", "",
           "That release's fingerprint. A fit against different bytes is a "
           "different fit.", "Provenance"),
    )


def _term(period_column: str, noun: str, key: str) -> tuple[Field, ...]:
    return GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
        _f(key, "string", "", f"The {key.split('_')[0]} this row is for.",
           "Identity"),
        _f(period_column, "string", "", f"The reporting {noun}.", "Calendar"),
        _f("scenario_id", "string", "",
           "baseline, downside or upside.", "Scenario"),
        _f("scenario_name", "string", "", "The scenario's label.",
           "Scenario"),
        _f("scenario_weight", "double", "fraction_0_1",
           "The weight this scenario carries in the probability-weighted "
           "ECL. The three weights sum to one.", "Scenario"),
        _f("horizon_index", "int", "count",
           "Horizon bucket, zero-based.", "Horizon"),
        _f("horizon_end_period", "string", "",
           "The period this bucket ends in.", "Horizon"),
        _f("horizon_months", "double", "months",
           "The bucket's length.", "Horizon"),
        _f("pd_marginal", "double", "probability_0_1",
           "Probability of default within this bucket, conditional on "
           "surviving to its start.", "Term structure"),
        _f("pd_cumulative", "double", "probability_0_1",
           "Cumulative default probability to the end of this bucket.",
           "Term structure"),
        _f("survival", "double", "probability_0_1",
           "Probability of surviving to the start of this bucket.",
           "Term structure"),
        _f("lgd", "double", "fraction_0_1",
           "Loss given default for this bucket, as a fraction.",
           "Term structure"),
        _f("ead_sar_mn", "double", "rcy",
           "Exposure at default for this bucket.", "Term structure"),
        _f("discount_factor", "double", "fraction_0_1",
           "Discount factor to the reporting date at the effective interest "
           "rate.", "Term structure"),
        _f("expected_shortfall_sar_mn", "double", "rcy",
           "survival x pd_marginal x lgd x ead x discount_factor. Summing "
           "these over buckets and weighting over scenarios is the modelled "
           "ECL, and `reference_ecl.py` is where that is written down.",
           "Term structure", label="Expected shortfall"),
    )


def _ifrs9(period_column: str, noun: str, key: str,
           undrawn: bool) -> tuple[Field, ...]:
    common = GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
        _f(key, "string", "", f"The {key.split('_')[0]} this row is for.",
           "Identity"),
        _f(period_column, "string", "", f"The reporting {noun}.", "Calendar"),
        _f("ecl_modelled_sar_mn", "double", "rcy",
           "The model's own ECL: probability-weighted across scenarios, "
           "summed over the term structure, discounted.", "ECL",
           label="Modelled ECL"),
        _f("ecl_overlay_sar_mn", "double", "rcy",
           "Management overlay held on top of the modelled figure. Held "
           "FIXED under a parameter stress unless the scenario changes it "
           "explicitly (section 9.1).", "ECL", label="Management overlay"),
        _f("overlay_reason", "string", "",
           "Why an overlay is held against this exposure.", "ECL"),
        _f("ecl_denominator", "string", "",
           "The denominator the published ECL rate is measured on. An ECL "
           "rate without its denominator is not a rate.", "ECL"),
        _f("ecl_rate", "double", "fraction_0_1",
           "Total ECL divided by the declared denominator. This is the ML "
           "target -- not exposure share (M01).", "ECL"),
        _f("effective_interest_rate", "double", "fraction_0_1",
           "The rate the term structure is discounted at.", "Measurement"),
        _f("remaining_maturity_months", "double", "months",
           "Contractual months remaining at the reporting date.",
           "Measurement"),
        _f("lifetime_horizon_months", "double", "months",
           "The horizon the lifetime figure is measured over.",
           "Measurement"),
        _f("ifrs9_model_version", "string", "",
           "The reference calculator version that produced these figures.",
           "Provenance"),
    )
    if not undrawn:
        return common
    return common + (
        _f("ccf_pit", "double", "fraction_0_1",
           "Credit conversion factor applied to the undrawn commitment. "
           "Published here rather than derived, because "
           "(ead - drawn) / undrawn inverts to noise where undrawn is zero.",
           "Exposure", label="CCF"),
        _f("ccf_eligible_flag", "int", "",
           "1 where the facility has an undrawn commitment a CCF can "
           "convert, 0 where it has none. A CCF stress applies to the "
           "eligible population only (section 7.4).", "Exposure"),
        _f("undrawn_eligible_sar_mn", "double", "rcy",
           "The undrawn amount the CCF converts.", "Exposure"),
    )


def _model_metric(period_column: str, noun: str) -> tuple[Field, ...]:
    return GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
        _f("model_id", "string", "", "The emulator this row describes.",
           "Identity"),
        _f("model_version", "string", "", "Its immutable version.",
           "Identity"),
        _f(period_column, "string", "",
           f"The {noun} the card is published as at.", "Calendar"),
        _f("component", "string", "",
           "blend, xgboost, lightgbm, spline, or reference for a comparison "
           "model.", "Identity"),
        _f("split", "string", "",
           "development, validation or out_of_time_test.", "Evaluation"),
        _f("group_dimension", "string", "",
           "The breakdown this metric is within: overall, stage, sector, "
           "product, rating_band, score_band or period.", "Evaluation"),
        _f("group_value", "string", "",
           "Which member of that dimension.", "Evaluation"),
        _f("metric_name", "string", "",
           "wape, mae, rmse, bias, r_squared, blend_weight, observations or "
           "entities.", "Evaluation"),
        _f("metric_value", "double", "",
           "Its value. Read `metric_name` for the unit; a WAPE and a bias "
           "are not the same quantity.", "Evaluation"),
        _f("observations", "int", "count",
           "Rows behind the metric. A group below the materiality floor is "
           "unvalidated, not accurate (M11).", "Evaluation"),
        _f("validated", "string", "",
           "VALIDATED, UNVALIDATED_SPARSE or NOT_APPLICABLE.", "Evaluation"),
        _f("note", "string", "",
           "What this number does and does not establish.", "Evaluation"),
    )


# ---- Corporate ---------------------------------------------------------

_Q = "reporting_quarter"

_CORP: tuple[Relation, ...] = (
    Relation(
        name="whatif_corp_macro_quarter",
        grain="one macroeconomic observation per factor, quarter and scenario",
        period_column=_Q,
        key_columns=("factor_id", _Q, "scenario_id"),
        description=(
            "The generated macroeconomic panel the Corporate sensitivities "
            "were fitted on. Twenty candidate factors over twenty quarters "
            "under three economic scenarios, each in its own native unit "
            "with its publication and availability dates. SYNTHETIC_DEMO: "
            "these are generated paths, not observed economic history."),
        fields=_macro(_Q, "quarter")),
    Relation(
        name="whatif_corp_mev_registry",
        grain="one row per candidate macroeconomic factor",
        period_column=_Q,
        key_columns=("factor_id", _Q),
        description=(
            "Section 7.1's twenty-factor registry for the Corporate book: "
            "what each candidate factor is, the unit a shock to it is "
            "expressed in, and whether this release carries a series for it. "
            "A factor with no series is ABSENT and stays absent; it never "
            "becomes a zero sensitivity."),
        fields=_registry(_Q, "quarter")),
    Relation(
        name="whatif_corp_sensitivity",
        grain="one fitted sensitivity per risk parameter, factor and lag",
        period_column=_Q,
        key_columns=("artifact_version", "parameter", "factor_id", _Q),
        description=(
            "The stored Corporate sensitivity artifact: model-space "
            "coefficients, native-unit slopes, the values they were "
            "evaluated at, resampled uncertainty, the period counts behind "
            "them and a readiness verdict per factor. Retrieved by a "
            "methodology question; never refitted in a chat turn."),
        fields=_sensitivity(_Q, "quarter")),
    Relation(
        name="whatif_corp_rating_map",
        grain="one row per rating grade in a mapping version",
        period_column=_Q,
        key_columns=("mapping_version", "rating_grade", _Q),
        description=(
            "The Corporate rating-to-PD mapping: the published scale in its "
            "own order, the PD each grade maps to at each horizon, and which "
            "grade is the default grade. A one-notch downgrade steps this "
            "scale; it is never a string increment."),
        fields=GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
            _f("mapping_version", "string", "",
               "The mapping this row belongs to.", "Identity"),
            _f("rating_grade", "string", "",
               "The grade, as the scale publishes it.", "Identity"),
            _f(_Q, "string", "",
               "The quarter this mapping is published as at.", "Calendar"),
            _f("grade_rank", "int", "rank",
               "Position on the scale, 1 being strongest. This is what a "
               "notch move steps through.", "Scale"),
            _f("pd_12m", "double", "probability_0_1",
               "Twelve-month PD for this grade.", "Mapping"),
            _f("pd_lifetime", "double", "probability_0_1",
               "Lifetime PD for this grade.", "Mapping"),
            _f("horizon_months", "double", "months",
               "The horizon the twelve-month figure is measured over.",
               "Mapping"),
            _f("is_default_grade", "int", "",
               "1 for the grade that means default. It has no worse "
               "neighbour and a downgrade from it is refused, not wrapped.",
               "Scale"),
            _f("is_investment_grade", "int", "",
               "1 where the scale calls this grade investment grade.",
               "Scale"),
            _f("effective_from", "string", "",
               "First period this mapping applies to.", "Provenance"),
            _f("effective_to", "string", "",
               "Last period it applies to. Empty while current.",
               "Provenance"),
            _f("source", "string", "",
               "Where the mapping came from.", "Provenance"))),
    Relation(
        name="whatif_corp_term_structure",
        grain="one row per facility, quarter, scenario and horizon bucket",
        period_column=_Q,
        key_columns=("facility_id", _Q, "scenario_id", "horizon_index"),
        description=(
            "The Corporate PD term structure, LGD and exposure profile under "
            "each economic scenario, with the discount factor each bucket is "
            "brought back at. Summed over buckets and weighted over "
            "scenarios this is the modelled ECL in whatif_corp_ifrs9, and "
            "reference_ecl.py is where the arithmetic is written down."),
        fields=_term(_Q, "quarter", "facility_id")),
    Relation(
        name="whatif_corp_ifrs9",
        grain="one row per facility and quarter",
        period_column=_Q,
        key_columns=("facility_id", _Q),
        description=(
            "The Corporate measurement inputs the accepted book does not "
            "carry: modelled ECL against management overlay, the declared "
            "ECL denominator and rate, the effective interest rate, "
            "remaining maturity and the published CCF with its eligible "
            "undrawn amount."),
        fields=_ifrs9(_Q, "quarter", "facility_id", undrawn=True)),
    Relation(
        name="whatif_corp_model_metric",
        grain="one recorded model metric",
        period_column=_Q,
        key_columns=("model_version", "component", "split",
                     "group_dimension", "group_value", "metric_name", _Q),
        description=(
            "The Corporate emulator's model card as data: learned blend "
            "weights, and error by split, period, stage, sector and rating "
            "band. A group below the materiality floor is marked "
            "UNVALIDATED_SPARSE rather than reported as accurate."),
        fields=_model_metric(_Q, "quarter")),
)


# ---- Retail ------------------------------------------------------------

_M = "reporting_month"

_RETAIL: tuple[Relation, ...] = (
    Relation(
        name="whatif_retail_macro_month",
        grain="one macroeconomic observation per factor, month and scenario",
        period_column=_M,
        key_columns=("factor_id", _M, "scenario_id"),
        description=(
            "The generated macroeconomic panel the Retail sensitivities were "
            "fitted on, at this book's monthly granularity, with the rule "
            "each series was reduced by recorded per row. SYNTHETIC_DEMO: "
            "generated paths, not observed economic history."),
        fields=_macro(_M, "month")),
    Relation(
        name="whatif_retail_mev_registry",
        grain="one row per candidate macroeconomic factor",
        period_column=_M,
        key_columns=("factor_id", _M),
        description=(
            "Section 7.1's twenty-factor registry for the Retail book. The "
            "supported subset differs from Corporate's, and that difference "
            "is reported rather than smoothed over."),
        fields=_registry(_M, "month")),
    Relation(
        name="whatif_retail_sensitivity",
        grain="one fitted sensitivity per risk parameter, factor and lag",
        period_column=_M,
        key_columns=("artifact_version", "parameter", "factor_id", _M),
        description=(
            "The stored Retail sensitivity artifact. Fitted separately from "
            "Corporate's on Retail's own monthly history: a coefficient "
            "estimated on one book is not evidence about the other."),
        fields=_sensitivity(_M, "month")),
    Relation(
        name="whatif_retail_score_map",
        grain="one row per score band in a scorecard version",
        period_column=_M,
        key_columns=("score_type", "scorecard_version", "product",
                     "band_low", _M),
        description=(
            "Retail score-to-PD calibrations. BEHAVIOURAL and APPLICATION "
            "are separate scorecards with separate validity windows and "
            "separate support ranges: an origination score is not a current "
            "score, and substituting one for the other is refused rather "
            "than disclosed after the fact."),
        fields=GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
            _f("score_type", "string", "",
               "BEHAVIOURAL or APPLICATION. The distinction is the point of "
               "this relation.", "Identity"),
            _f("scorecard_version", "string", "",
               "The scorecard this calibration belongs to.", "Identity"),
            _f("product", "string", "",
               "The product it was calibrated for, or ALL.", "Identity"),
            _f("band_low", "int", "index",
               "Lowest score in the band, inclusive.", "Scale"),
            _f(_M, "string", "",
               "The month this calibration is published as at.", "Calendar"),
            _f("band_high", "int", "index",
               "Highest score in the band, inclusive.", "Scale"),
            _f("band_label", "string", "",
               "The band's published label.", "Scale"),
            _f("pd_12m", "double", "probability_0_1",
               "Twelve-month PD for this band.", "Mapping"),
            _f("horizon_months", "double", "months",
               "The horizon that PD is measured over.", "Mapping"),
            _f("direction", "string", "",
               "HIGHER_IS_SAFER or HIGHER_IS_RISKIER, discovered from the "
               "calibration rather than assumed.", "Scale"),
            _f("support_low", "int", "index",
               "Lowest score the calibration was fitted over.", "Readiness"),
            _f("support_high", "int", "index",
               "Highest score the calibration was fitted over.",
               "Readiness"),
            _f("effective_from", "string", "",
               "First month this calibration applies to.", "Provenance"),
            _f("effective_to", "string", "",
               "Last month it applies to. Empty while current.",
               "Provenance"),
            _f("source", "string", "", "Where the calibration came from.",
               "Provenance"))),
    Relation(
        name="whatif_retail_term_structure",
        grain="one row per account, month, scenario and horizon bucket",
        period_column=_M,
        key_columns=("account_id", _M, "scenario_id", "horizon_index"),
        description=(
            "The Retail PD term structure, LGD and exposure profile under "
            "each economic scenario, with its discount factors."),
        fields=_term(_M, "month", "account_id")),
    Relation(
        name="whatif_retail_ifrs9",
        grain="one row per account and month",
        period_column=_M,
        key_columns=("account_id", _M),
        description=(
            "The Retail measurement inputs the accepted book does not carry: "
            "modelled ECL against management overlay, the declared ECL "
            "denominator and rate, the effective interest rate and remaining "
            "maturity. No CCF: Retail sets exposure to the balance outside "
            "revolving products, and the accepted book has no conversion to "
            "recover."),
        fields=_ifrs9(_M, "month", "account_id", undrawn=False)),
    Relation(
        name="whatif_retail_profile",
        grain="one row per customer and month",
        period_column=_M,
        key_columns=("customer_id", _M),
        description=(
            "The Retail dimensions the accepted book does not carry: the "
            "customer's employer sector, and their application score with "
            "its own scorecard version and origination date. Employer "
            "sector is generated as its own dimension -- product is not a "
            "substitute for it (section 3.3)."),
        fields=GOVERNANCE_FIELDS + _CANDIDATE_FIELDS + (
            _f("customer_id", "string", "", "The customer.", "Identity"),
            _f(_M, "string", "", "The reporting month.", "Calendar"),
            _f("employer_sector", "string", "",
               "The sector the customer's employer operates in. A real "
               "dimension of its own, not a relabelling of the product they "
               "hold.", "Segment", label="Employer sector"),
            _f("employer_sector_group", "string", "",
               "The broader grouping that sector rolls into.", "Segment"),
            _f("application_score", "int", "index",
               "The score at origination. NOT the behavioural score, and "
               "never a substitute for it.", "Scores",
               label="Application score"),
            _f("application_score_version", "string", "",
               "The origination scorecard version.", "Scores"),
            _f("application_scored_at", "string", "",
               "The month the application score was taken.", "Scores"),
            _f("behaviour_score_version", "string", "",
               "The behavioural scorecard version in force this month.",
               "Scores"))),
    Relation(
        name="whatif_retail_model_metric",
        grain="one recorded model metric",
        period_column=_M,
        key_columns=("model_version", "component", "split",
                     "group_dimension", "group_value", "metric_name", _M),
        description=(
            "The Retail emulator's model card as data, on the same contract "
            "as Corporate's and fitted entirely separately."),
        fields=_model_metric(_M, "month")),
)


RELATIONS: dict[str, tuple[Relation, ...]] = {
    dom.CORPORATE: _CORP,
    dom.RETAIL: _RETAIL,
}


def relations(domain_id: str) -> tuple[Relation, ...]:
    """The candidate relations for a book, or none for an unknown one."""
    return RELATIONS.get(dom.parse(domain_id), ())


def relation_names(domain_id: str) -> tuple[str, ...]:
    return tuple(spec.name for spec in relations(domain_id))


def release_id(domain_id: str) -> str:
    """The candidate release for a book."""
    return RELEASES.get(dom.parse(domain_id), "")


def is_candidate(release: str) -> bool:
    """Is this one of the labelled synthetic releases?

    Used wherever a document or an answer has to say which book a figure came
    from. A candidate figure that reaches a reader without that label is the
    failure section 11.1 is most concerned about.
    """
    return str(release or "") in set(RELEASES.values())


__all__ = ["CORPORATE_HORIZONS", "ORIGIN", "RELATIONS", "RELEASES",
           "RETAIL_HORIZONS", "SCENARIOS", "is_candidate", "relation_names",
           "relations", "release_id"]
