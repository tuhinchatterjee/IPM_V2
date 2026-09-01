"""
The preconfigured credit-risk method library.

Three hundred-odd named methodologies a bank recognises, grouped by the question
being asked rather than by the mathematics behind it.

Read the lifecycle column before anything else
----------------------------------------------
Most entries here are DEFINITIONS. They record what a method means, what it
needs, when it should and should not be used, and what it does not tell you —
and they say PRECONFIGURED · REVIEW REQUIRED, because that is what they are.

A smaller set is genuinely implemented, tested against transparent cases, and
CERTIFIED. Those carry the double blue tick.

Marking all three hundred certified because there are three hundred of them
would make the tick worthless, and a worthless tick devalues the honest ones
too. The library is deliberately large and its certified subset deliberately
small; the interface never shows one as the other, and `can_certify()` on the
model states exactly what a preconfigured entry is missing.

Why definitions are worth shipping at all
-----------------------------------------
Two reasons. A methodology owner starting from "Cure Rate — the share of
accounts that returned to performing" is starting somewhere; a blank page is
where method libraries die. And Ask CreditProbe reads these definitions when it
routes a question, so "what is our cure rate" finds the right subject even
before anybody has built it — and says honestly that it has not been built.
"""

from __future__ import annotations

from typing import Any

from backend.studio.model import (
    Category,
    Lifecycle,
    MethodDefinition,
    TestCase,
)

C = Category
L = Lifecycle


def d(id: str, name: str, category: str, definition: str, *,
      aliases: tuple[str, ...] = (), purpose: str = "",
      methodology: str = "", when_to_use: str = "", when_not_to_use: str = "",
      grain: str = "", history: str = "", domains: tuple[str, ...] = (),
      fields: tuple[str, ...] = (), weighting: tuple[str, ...] = (),
      output: str = "", interpretation: str = "", limitations: str = "",
      engine: str = "", lifecycle: str = L.PRECONFIGURED,
      plan: dict[str, Any] | None = None,
      tests: tuple[TestCase, ...] = ()) -> MethodDefinition:
    """One library entry. Compact on purpose — there are three hundred of them."""
    return MethodDefinition(
        id=id, name=name, category=category, definition=definition,
        aliases=list(aliases), purpose=purpose, methodology=methodology,
        when_to_use=when_to_use, when_not_to_use=when_not_to_use,
        required_grain=grain, required_history=history,
        required_domains=list(domains), required_fields=list(fields),
        weighting_options=list(weighting), output_type=output,
        interpretation=interpretation, limitations=limitations,
        engine_analysis=engine, lifecycle=lifecycle, plan=plan,
        test_cases=list(tests),
    )


#: Diagnostic cases for the ECL change decomposition, with the answers worked
#: out by hand. Each isolates ONE driver, because a case where several drivers
#: move at once cannot show that the attribution put the effect on the right
#: one — it can only show that the total balances, which a wrong attribution
#: also does. The full suite lives in tests/orchestration/test_decomposition.py;
#: these are the ones a methodology owner should be able to read on screen and
#: check with a pencil.
_ECL_DECOMPOSITION_CASES: tuple[TestCase, ...] = (
    TestCase(
        id="exposure_only", name="Exposure grew, nothing else moved",
        purpose="An account whose exposure rose by half, at unchanged PD, LGD "
                "and stage. The whole movement belongs to exposure, and every "
                "other driver must be exactly zero.",
        data=[{"account_id": "A", "period": "opening", "ead": 100.0,
               "ifrs9_stage": 1, "pd_12m_pct": 2.0, "lgd_pct": 40.0,
               "model_ecl": 0.8, "total_ecl": 0.8},
              {"account_id": "A", "period": "closing", "ead": 150.0,
               "ifrs9_stage": 1, "pd_12m_pct": 2.0, "lgd_pct": 40.0,
               "model_ecl": 1.2, "total_ecl": 1.2}],
        expected={"movement": 0.4, "exposure": 0.4, "pd": 0.0, "lgd": 0.0,
                  "stage_migration": 0.0}),
    TestCase(
        id="stage_only", name="A stage migration is not a rise in PD",
        purpose="The twelve-month PD did not move; the account moved from a "
                "twelve-month to a lifetime horizon. Reporting that as a PD "
                "effect would send a reader to the ratings team about a model "
                "that did exactly what SICR asked of it.",
        data=[{"account_id": "A", "period": "opening", "ead": 100.0,
               "ifrs9_stage": 1, "pd_12m_pct": 2.0, "pd_lifetime_pct": 6.0,
               "lgd_pct": 40.0, "model_ecl": 0.8, "total_ecl": 0.8},
              {"account_id": "A", "period": "closing", "ead": 100.0,
               "ifrs9_stage": 2, "pd_12m_pct": 2.0, "pd_lifetime_pct": 6.0,
               "lgd_pct": 40.0, "model_ecl": 2.4, "total_ecl": 2.4}],
        expected={"movement": 1.6, "stage_migration": 1.6, "pd": 0.0}),
    TestCase(
        id="mix_only", name="Exposure moved between accounts, the book did not grow",
        purpose="Total exposure is unchanged; it has moved from a safe "
                "borrower to a risky one. This is a composition effect, and "
                "reporting it as exposure would say the bank lent more, which "
                "it did not.",
        data=[{"account_id": "SAFE", "period": "opening", "ead": 100.0,
               "pd_12m_pct": 1.0, "lgd_pct": 40.0, "ifrs9_stage": 1},
              {"account_id": "RISKY", "period": "opening", "ead": 100.0,
               "pd_12m_pct": 10.0, "lgd_pct": 40.0, "ifrs9_stage": 1},
              {"account_id": "SAFE", "period": "closing", "ead": 50.0,
               "pd_12m_pct": 1.0, "lgd_pct": 40.0, "ifrs9_stage": 1},
              {"account_id": "RISKY", "period": "closing", "ead": 150.0,
               "pd_12m_pct": 10.0, "lgd_pct": 40.0, "ifrs9_stage": 1}],
        expected={"portfolio_mix": "the whole movement", "exposure": 0.0}),
    TestCase(
        id="arrival", name="An account that arrived is not a rise in PD",
        purpose="It has one PD, not two. Folding arrivals into the drivers is "
                "the common way a decomposition reconciles while lying.",
        data=[{"account_id": "A", "period": "opening", "ead": 100.0,
               "pd_12m_pct": 2.0, "lgd_pct": 40.0, "total_ecl": 0.8},
              {"account_id": "A", "period": "closing", "ead": 100.0,
               "pd_12m_pct": 2.0, "lgd_pct": 40.0, "total_ecl": 0.8},
              {"account_id": "B", "period": "closing", "ead": 100.0,
               "pd_12m_pct": 2.0, "lgd_pct": 40.0, "total_ecl": 0.8}],
        expected={"movement": 0.8, "new_accounts": 0.8, "pd": 0.0}),
    TestCase(
        id="order_neutral", name="The attribution does not depend on the order",
        purpose="Two factors both doubling. The change is 3, and neither "
                "factor did more of it than the other. The one-at-a-time "
                "attribution says 1 and 2 — and it reconciles, which is why "
                "nobody catches it.",
        data=[{"factor_a": 1.0, "factor_b": 1.0, "period": "opening"},
              {"factor_a": 2.0, "factor_b": 2.0, "period": "closing"}],
        expected={"factor_a": 1.5, "factor_b": 1.5}),
    TestCase(
        id="reconciliation", name="Every driver moving at once still reconciles",
        purpose="Exposure, stage, PD, LGD and the overlay all moving, plus an "
                "arrival and a departure. The whole claim of the method is "
                "that the components still sum exactly to the movement.",
        data=[{"note": "see tests/orchestration/test_decomposition.py"}],
        expected={"sum_of_components": "closing ECL - opening ECL",
                  "tolerance": "1e-6 relative"}),
)

# =====================================================  portfolio & exposure

PORTFOLIO: list[MethodDefinition] = [
    d("total_ead", "Total Exposure at Default", C.EXPOSURE,
      "The sum of exposure at default across the portfolio at a reporting date.",
      aliases=("EAD", "total exposure", "gross exposure"),
      purpose="The denominator of almost every portfolio ratio, and the first "
              "number any credit committee asks for.",
      grain="Facility per reporting period", fields=("ead",),
      output="Single value", weighting=("none",),
      limitations="A point-in-time stock. It says nothing about how it was "
                  "reached or where it is going.",
      engine="portfolio_summary", lifecycle=L.CERTIFIED),
    d("outstanding_exposure", "Outstanding Exposure", C.EXPOSURE,
      "Drawn balances outstanding, before undrawn commitments.",
      aliases=("drawn", "outstandings", "balance"),
      grain="Facility per reporting period", fields=("exposure",),
      output="Single value",
      limitations="Excludes undrawn commitment, so it understates the exposure "
                  "the bank actually carries."),
    d("undrawn_commitment", "Undrawn Commitment", C.EXPOSURE,
      "Committed limits not yet drawn.",
      aliases=("undrawn", "available limit"),
      fields=("undrawn", "limit_amount"), output="Single value",
      limitations="Availability is not certainty — undrawn amounts on a "
                  "deteriorating name are often drawn precisely when least wanted."),
    d("average_facility_size", "Average Facility Size", C.EXPOSURE,
      "Mean exposure per facility.",
      aliases=("mean facility size", "average ticket"),
      fields=("ead",), output="Single value",
      limitations="A mean over a skewed distribution. The median and the top "
                  "decile usually tell you more."),
    d("utilisation_rate", "Utilisation Rate", C.EXPOSURE,
      "Drawn balance as a percentage of the committed limit.",
      aliases=("utilization", "drawdown rate", "limit utilisation"),
      purpose="A rising utilisation on a weakening name is one of the oldest "
              "early-warning signals there is.",
      fields=("exposure", "limit_amount"), weighting=("count", "EAD"),
      output="Percentage",
      interpretation="Read alongside rating: high and stable is a working "
                     "capital profile; high and rising is often distress.",
      engine="utilisation_drift", lifecycle=L.CERTIFIED),
    d("utilisation_drift", "Utilisation Drift", C.EXPOSURE,
      "Change in utilisation between two reporting periods.",
      aliases=("utilisation change", "drawdown drift"),
      history="Two periods", engine="utilisation_drift", lifecycle=L.CERTIFIED),
    d("exposure_growth", "Exposure Growth", C.EXPOSURE,
      "Percentage change in exposure between two periods.",
      aliases=("EAD growth", "book growth"), history="Two periods",
      fields=("ead",), output="Percentage",
      limitations="Net growth hides gross flows: new lending and runoff can be "
                  "large and offsetting."),
    d("exposure_runoff", "Exposure Runoff", C.EXPOSURE,
      "Exposure leaving the book through repayment, maturity or exit.",
      aliases=("runoff", "amortisation"), history="Two periods",
      limitations="Requires facilities to be identifiable across periods; "
                  "re-papered facilities look like runoff plus new lending."),
    d("new_lending", "New Lending", C.EXPOSURE,
      "Exposure on facilities present this period and absent last.",
      aliases=("originations", "new business"), history="Two periods"),
    d("maturity_profile", "Maturity Profile", C.EXPOSURE,
      "Exposure by remaining time to maturity.",
      aliases=("tenor profile", "maturity ladder"), output="Distribution"),
    d("exposure_by_product", "Exposure by Product", C.EXPOSURE,
      "Exposure split across product types.", aliases=("product mix",),
      fields=("ead", "product_type"), output="Distribution"),
    d("exposure_by_segment", "Exposure by Segment", C.EXPOSURE,
      "Exposure split across customer segments.",
      fields=("ead", "segment"), output="Distribution"),
    d("exposure_by_currency", "Exposure by Currency", C.EXPOSURE,
      "Exposure split by currency of the facility.",
      limitations="Currency of the facility is not currency of the borrower's "
                  "cash flow. Unhedged mismatch is the risk, and this does not "
                  "show it."),
    d("commitment_conversion", "Commitment Conversion", C.EXPOSURE,
      "Credit conversion factor applied to undrawn commitments.",
      aliases=("CCF",), fields=("ccf_pct", "undrawn")),
    d("exposure_concentration_by_obligor", "Exposure by Obligor", C.EXPOSURE,
      "Exposure aggregated to the obligor, across all their facilities.",
      aliases=("obligor exposure", "single name exposure"),
      grain="Customer", engine="obligor_concentration", lifecycle=L.CERTIFIED),
]

# =====================================================  asset quality

ASSET_QUALITY: list[MethodDefinition] = [
    d("npl_ratio", "NPL Ratio", C.PORTFOLIO_QUALITY,
      "Non-performing exposure as a percentage of total exposure.",
      aliases=("non-performing loan ratio", "NPL", "NPE ratio", "bad book ratio"),
      purpose="The single most quoted measure of asset quality, and the one a "
              "regulator opens with.",
      methodology="Non-performing exposure divided by total exposure at default, "
                  "at one reporting date. Non-performing follows the bank's own "
                  "definition — typically 90 days past due or Stage 3.",
      when_to_use="A headline read on asset quality at a point in time.",
      when_not_to_use="To explain a movement. A ratio can rise because the "
                      "numerator grew or the denominator shrank, and this does "
                      "not distinguish them.",
      grain="Facility per reporting period", fields=("ead", "npl"),
      weighting=("EAD",), output="Percentage",
      interpretation="A rise is not automatically deterioration: a shrinking "
                     "performing book raises it arithmetically.",
      limitations="Says nothing about coverage, cure, or how long exposures have "
                  "been non-performing.",
      engine="portfolio_summary", lifecycle=L.CERTIFIED),
    d("npl_stock", "NPL Stock", C.PORTFOLIO_QUALITY,
      "The absolute amount of non-performing exposure.",
      aliases=("NPL balance", "non-performing stock"),
      fields=("ead", "npl"), output="Single value"),
    d("npl_flow", "NPL Flow", C.PORTFOLIO_QUALITY,
      "Exposure entering and leaving non-performing status between periods.",
      aliases=("NPL inflow", "NPL formation", "net NPL flow"),
      purpose="The stock tells you where you are; the flow tells you where you "
              "are going.",
      history="Two periods", grain="Facility identifiable across periods",
      output="Flow"),
    d("new_npl_rate", "New NPL Rate", C.PORTFOLIO_QUALITY,
      "Exposure newly non-performing as a share of the opening performing book.",
      aliases=("NPL formation rate", "new NPL formation"),
      history="Two periods", output="Percentage",
      limitations="Sensitive to the opening population definition. Excluding or "
                  "including facilities that closed changes the answer."),
    d("cure_rate", "Cure Rate", C.RECOVERY,
      "The share of non-performing exposure that returned to performing.",
      aliases=("cure", "recovery to performing", "rehabilitation rate"),
      purpose="A high cure rate changes what a given NPL stock means.",
      methodology="Of the population non-performing at the opening date, the "
                  "proportion performing at the closing date. Whether a facility "
                  "that cured and re-defaulted counts as cured is a decision the "
                  "bank must record.",
      when_not_to_use="Where forbearance is common — a cure achieved by "
                      "restructuring is not the same as a cure achieved by payment.",
      history="Two periods", output="Percentage",
      limitations="Cure and re-default are different questions. This answers only "
                  "the first."),
    d("redefault_rate", "Re-default Rate", C.RECOVERY,
      "The share of cured exposures that returned to default within a horizon.",
      aliases=("re-default", "relapse rate"), history="Three or more periods",
      limitations="Requires the cure date, not only the current status."),
    d("default_rate", "Default Rate", C.DEFAULT_DELINQUENCY,
      "The share of the population in default at a reporting date.",
      aliases=("observed default rate", "ODR", "default frequency"),
      grain="Facility or customer", fields=("ifrs9_stage", "npl"),
      weighting=("count", "EAD"), output="Percentage",
      limitations="A point-in-time count. It is not a probability of default and "
                  "must not be read as one."),
    d("forward_default_rate", "Forward Default Rate", C.DEFAULT_DELINQUENCY,
      "The share of a performing opening population that defaults within a "
      "forward horizon.",
      aliases=("forward ODR", "cohort default rate", "observed forward default rate"),
      purpose="The empirical counterpart to a PD. What actually happened to the "
              "people who looked fine a year ago.",
      methodology="Fix an opening population of performing facilities at time T. "
                  "Observe their status at T plus the horizon. Count those in "
                  "default. Divide by the opening population.",
      when_to_use="Backtesting a PD model, or setting expectations from history.",
      when_not_to_use="With less history than the horizon, or where the opening "
                      "population cannot be followed forward.",
      grain="Facility or customer, consistently", history="Horizon plus one period",
      weighting=("count", "EAD"), output="Percentage",
      limitations="Depends entirely on how accounts that disappear are treated. "
                  "Excluding them and counting them as non-defaults give "
                  "materially different answers."),
    d("one_year_forward_odr", "One-Year Forward ODR", C.DEFAULT_DELINQUENCY,
      "The share of facilities performing at a quarter end that are in default "
      "one year later.",
      aliases=("1Y ODR", "one year observed default rate", "annual forward ODR",
               "12-month observed default rate"),
      purpose="The standard empirical default measure for a corporate book, and "
              "the one a model validation team asks for first.",
      methodology="Opening population: facilities with days past due below 90 at "
                  "the opening quarter end. Forward observation: the same "
                  "facilities four quarters later. Default: days past due of 90 "
                  "or more. The rate is defaulted over opening population.",
      when_to_use="Comparing realised default experience with a PD model, or "
                  "tracking default emergence across quarters.",
      when_not_to_use="Where fewer than five quarters of history exist, or where "
                      "facility identifiers are not stable across periods.",
      grain="Facility per reporting period", history="Five quarters",
      domains=("credit_facility_position",),
      fields=("account_id", "dpd_days", "period"),
      weighting=("count", "EAD"), output="Percentage",
      interpretation="Read against the PD assigned at the opening date. A "
                     "realised rate persistently above the predicted one is a "
                     "calibration finding.",
      limitations="Facilities that leave the book between the two dates have no "
                  "forward observation. They are excluded, which is a choice, and "
                  "it biases the result if exits are not random."),
    d("six_month_forward_odr", "Six-Month Forward ODR", C.DEFAULT_DELINQUENCY,
      "As the one-year measure, over a two-quarter horizon.",
      aliases=("6M ODR", "six month observed default rate"),
      history="Three quarters", weighting=("count", "EAD"), output="Percentage"),
    d("three_month_forward_odr", "Three-Month Forward ODR", C.DEFAULT_DELINQUENCY,
      "As the one-year measure, over a one-quarter horizon.",
      aliases=("3M ODR", "quarterly forward ODR"),
      history="Two quarters", output="Percentage"),
    d("default_emergence_rate", "Default Emergence Rate", C.DEFAULT_DELINQUENCY,
      "New defaults in a period as a share of the opening performing population.",
      aliases=("emergence rate", "new default rate"),
      history="Two periods", output="Percentage"),
    d("dpd_distribution", "Days Past Due Distribution", C.DEFAULT_DELINQUENCY,
      "Facilities and exposure across arrears buckets.",
      aliases=("DPD distribution", "arrears buckets", "ageing"),
      fields=("days_past_due", "dpd_bucket"), output="Distribution",
      engine="arrears_position", lifecycle=L.CERTIFIED),
    d("arrears_position", "Arrears Position", C.DEFAULT_DELINQUENCY,
      "Amount overdue, arrears bucket, forbearance and collections stage.",
      aliases=("delinquency position", "collections position"),
      engine="arrears_position", lifecycle=L.CERTIFIED),
    d("dpd_migration", "DPD Migration", C.MIGRATION,
      "Exposure moving between arrears buckets across two periods.",
      aliases=("arrears migration", "delinquency migration", "bucket migration"),
      history="Two periods", output="Matrix",
      engine="dpd_migration", lifecycle=L.CERTIFIED),
    d("roll_rate", "Roll Rate", C.MIGRATION,
      "The share of a delinquency bucket that moves to the next bucket.",
      aliases=("roll forward rate", "bucket roll"),
      purpose="The classic collections measure: of everyone 30 days down, how "
              "many reach 60.",
      history="Two consecutive periods", output="Percentage",
      limitations="A rate per bucket pair. Chaining them to infer a lifetime "
                  "outcome assumes independence that rarely holds."),
    d("roll_forward", "Roll Forward", C.MIGRATION,
      "The full opening-to-closing movement across arrears buckets.",
      aliases=("roll forward matrix",), history="Two periods", output="Matrix"),
    d("cure_roll_rate", "Cure Roll Rate", C.RECOVERY,
      "The share of a delinquency bucket that improves rather than worsens.",
      aliases=("backward roll", "improvement rate"),
      history="Two periods", output="Percentage"),
    d("restructuring_rate", "Restructuring Rate", C.RECOVERY,
      "The share of exposure restructured in a period.",
      aliases=("restructure rate",), fields=("restructured_flag",),
      output="Percentage"),
    d("forbearance_rate", "Forbearance Rate", C.RECOVERY,
      "The share of exposure carrying a forbearance measure.",
      aliases=("forborne share", "concession rate"),
      fields=("forbearance_type",), output="Percentage",
      limitations="Forbearance suppresses arrears by design, so a low DPD "
                  "alongside a high forbearance rate is not good news."),
    d("write_off_rate", "Write-off Rate", C.RECOVERY,
      "Exposure written off as a share of the opening book.",
      aliases=("charge-off rate",), output="Percentage"),
    d("recovery_rate", "Recovery Rate", C.RECOVERY,
      "Cash recovered as a share of exposure at default.",
      aliases=("realised recovery",), output="Percentage",
      limitations="Recoveries arrive over years. A recovery rate measured too "
                  "early is always too low."),
    d("loss_given_default_realised", "Realised Loss Given Default", C.RECOVERY,
      "One minus the realised recovery rate, discounted.",
      aliases=("realised LGD", "workout LGD"), output="Percentage",
      limitations="Needs closed workouts. Open cases bias it in whichever "
                  "direction the open cases lean."),
    d("time_to_recovery", "Time to Recovery", C.RECOVERY,
      "Elapsed time between default and final recovery.",
      aliases=("workout period",), output="Distribution"),
    d("collections_effectiveness", "Collections Effectiveness", C.RECOVERY,
      "Amount collected as a share of amount due in the period.",
      aliases=("collection rate",), output="Percentage"),
    d("delinquency_rate", "Delinquency Rate", C.DEFAULT_DELINQUENCY,
      "The share of facilities with any arrears.",
      aliases=("past due rate", "arrears rate"),
      fields=("days_past_due",), output="Percentage",
      engine="arrears_position", lifecycle=L.CERTIFIED),
    d("thirty_plus_rate", "30+ Delinquency Rate", C.DEFAULT_DELINQUENCY,
      "The share of exposure 30 or more days past due.",
      aliases=("30+ DPD", "early arrears rate"), output="Percentage"),
    d("ninety_plus_rate", "90+ Delinquency Rate", C.DEFAULT_DELINQUENCY,
      "The share of exposure 90 or more days past due.",
      aliases=("90+ DPD", "NPL proxy"), output="Percentage"),
    d("bucket_persistence", "Bucket Persistence", C.DEFAULT_DELINQUENCY,
      "The share of a delinquency bucket still in the same bucket next period.",
      aliases=("stickiness",), history="Two periods", output="Percentage"),
]

# =====================================================  IFRS 9

IFRS9: list[MethodDefinition] = [
    d("stage_distribution", "Stage Distribution", C.IFRS9,
      "Exposure and impairment split across IFRS 9 stages.",
      aliases=("staging", "IFRS 9 stages", "stage split"),
      fields=("ifrs9_stage", "ead", "total_ecl"), output="Distribution",
      engine="stage_distribution", lifecycle=L.CERTIFIED),
    d("stage_1_to_2_migration", "Stage 1 to 2 Migration", C.MIGRATION,
      "Exposure moving from Stage 1 to Stage 2 between periods.",
      aliases=("SICR migration", "stage 1-2"), history="Two periods",
      engine="stage_migration", lifecycle=L.CERTIFIED),
    d("stage_2_to_3_migration", "Stage 2 to 3 Migration", C.MIGRATION,
      "Exposure moving from Stage 2 to Stage 3 between periods.",
      aliases=("default migration", "stage 2-3"), history="Two periods",
      engine="stage_migration", lifecycle=L.CERTIFIED),
    d("stage_migration_matrix", "Stage Migration Matrix", C.MIGRATION,
      "The full opening-stage to closing-stage transition matrix.",
      aliases=("stage transition matrix", "IFRS 9 migration"),
      history="Two periods", output="Matrix",
      engine="stage_migration", lifecycle=L.CERTIFIED),
    d("stage_migration_flow", "Stage Migration Flow", C.MIGRATION,
      "Stage movements drawn as a flow between opening and closing positions.",
      aliases=("stage sankey", "stage flow"), history="Two periods",
      engine="stage_migration_flow", lifecycle=L.CERTIFIED),
    d("stage_cure", "Stage Cure", C.IFRS9,
      "Exposure improving to a better stage between periods.",
      aliases=("stage improvement", "backward migration"),
      history="Two periods", output="Percentage"),
    d("sicr_emergence", "SICR Emergence Rate", C.IFRS9,
      "The share of Stage 1 exposure newly showing a significant increase in "
      "credit risk.",
      aliases=("SICR rate", "significant increase in credit risk"),
      history="Two periods", output="Percentage",
      limitations="Entirely determined by the bank's SICR policy. Two banks with "
                  "identical books report different numbers."),
    d("sicr_trigger_breakdown", "SICR Trigger Breakdown", C.IFRS9,
      "Which significant-increase triggers fired, separately.",
      aliases=("SICR triggers", "staging triggers"),
      engine="sicr_trigger_breakdown", lifecycle=L.CERTIFIED),
    d("approaching_sicr", "Approaching the SICR Threshold", C.EARLY_WARNING,
      "Stage 1 facilities close to breaching a significant-increase trigger.",
      aliases=("near SICR", "SICR watch"),
      engine="approaching_sicr_threshold", lifecycle=L.CERTIFIED),
    d("ecl_coverage", "ECL Coverage", C.IFRS9,
      "Expected credit loss as a percentage of exposure at default.",
      aliases=("coverage ratio", "provision coverage", "ECL ratio"),
      fields=("total_ecl", "ead"), weighting=("EAD",), output="Percentage",
      interpretation="Compare across stages before across periods — a portfolio "
                     "mix shift moves total coverage without any repricing of risk.",
      engine="ecl_coverage_by_stage", lifecycle=L.CERTIFIED),
    d("ecl_coverage_by_stage", "ECL Coverage by Stage", C.IFRS9,
      "Coverage computed within each IFRS 9 stage.",
      aliases=("stage coverage",),
      engine="ecl_coverage_by_stage", lifecycle=L.CERTIFIED),
    d("ecl_rate", "ECL Rate", C.IFRS9,
      "Expected credit loss as a rate on the exposure that carries it.",
      aliases=("provision rate",), output="Percentage"),
    d("ecl_movement", "ECL Movement", C.IFRS9,
      "The change in expected credit loss between two periods, decomposed.",
      aliases=("provision movement", "ECL walk", "impairment movement"),
      history="Two periods", output="Waterfall",
      engine="ecl_movement", lifecycle=L.CERTIFIED),
    d("ecl_contribution", "ECL Contribution", C.IFRS9,
      "Each sector or borrower's share of the total ECL movement.",
      aliases=("provision contribution", "ECL attribution"),
      history="Two periods", output="Ranked contribution",
      engine="ecl_movement", lifecycle=L.CERTIFIED),
    d("ecl_change_decomposition", "ECL Change Decomposition", C.IFRS9,
      "Opening ECL to closing ECL through its drivers, attributed without an "
      "arbitrary ordering.",
      aliases=("ECL waterfall", "provision waterfall", "ECL bridge",
               "ECL attribution", "impairment bridge", "ECL walk",
               "provision bridge"),
      purpose="To say what MOVED the impairment charge, rather than where the "
              "movement landed. An ECL movement by sector is a different "
              "question with a similar shape: it reports the result of the "
              "change, not its drivers.",
      methodology=(
          "Per account, over the population present in BOTH periods, modelled "
          "ECL is factorised as T x w x R x PD12 x LGD x K — total exposure, "
          "the account's share of it, the lifetime multiple its stage applies, "
          "the twelve-month PD, loss given default, and a residual K carrying "
          "everything else the model does (discounting, the lifetime loss "
          "profile, the effective interest rate). The change is attributed "
          "across those six by SHAPLEY value: each effect is the factor's "
          "average marginal contribution over every order in which the factors "
          "could have moved. That is the unique attribution that is "
          "order-neutral, sums exactly to the movement, and gives a factor "
          "that did not move an effect of zero. The one-at-a-time alternative "
          "also reconciles, and hands every interaction term to whichever "
          "factor happened to be moved last — so the same book tells a "
          "different story depending on the order somebody chose, and each "
          "version balances. The overlay (total ECL less modelled ECL) is "
          "additive and attributed directly, and accounts present in only one "
          "period are their own components, because an account with one PD "
          "has no PD change."),
      when_to_use="To explain a movement in the impairment charge to a "
                  "committee, and to say which sectors and which borrowers "
                  "drove it.",
      when_not_to_use=(
          "As evidence of cause. A PD effect says the PDs used in the "
          "calculation changed; it does not say why, and a model "
          "recalibration and a deteriorating book look identical here."),
      grain="Account, identifiable across both periods",
      history="Two periods", domains=("ifrs9",),
      fields=("account_id", "customer_id", "sector", "ifrs9_stage", "ead",
              "pd_12m_pct", "pd_lifetime_pct", "lgd_pct", "model_ecl",
              "total_ecl"),
      weighting=("EAD",),
      output="Waterfall with sector and customer attribution",
      interpretation=(
          "Read the signs first: a positive effect drove the loss up. The "
          "model residual is not an error term — it is the part of ECL that "
          "exposure, PD and LGD do not describe, and on most books it is "
          "material. A large residual movement is a question for the "
          "impairment model owner, not a rounding difference."),
      limitations=(
          "It does not establish cause. It does not separate the residual "
          "into discounting, lifetime profile and EIR — those move together "
          "and are reported as one driver. It attributes the overlay rather "
          "than explaining it, an overlay being a judgement. And it says "
          "nothing about accounts outside the governed population for the two "
          "periods compared."),
      engine="ecl_change_decomposition", lifecycle=L.CERTIFIED,
      tests=_ECL_DECOMPOSITION_CASES),
    d("pd_movement", "PD Movement", C.IFRS9,
      "Change in probability of default between periods.",
      aliases=("PD drift", "PD change"), history="Two periods",
      fields=("pd_12m_pct",), weighting=("EAD",)),
    d("lgd_movement", "LGD Movement", C.IFRS9,
      "Change in loss given default between periods.",
      aliases=("LGD drift",), history="Two periods", fields=("lgd_pct",)),
    d("ead_movement", "EAD Movement", C.IFRS9,
      "Change in exposure at default between periods.",
      aliases=("exposure movement",), history="Two periods", fields=("ead",)),
    d("lifetime_vs_12m_ecl", "Lifetime versus 12-month ECL", C.IFRS9,
      "The uplift from measuring ECL over the lifetime rather than 12 months.",
      aliases=("lifetime uplift", "stage 2 uplift"),
      limitations="The comparison is only meaningful within Stage 2, where both "
                  "measures are defined for the same exposure."),
    d("scenario_impact_ecl", "Scenario Impact on ECL", C.STRESS,
      "ECL under an alternative macroeconomic scenario.",
      aliases=("scenario ECL", "macro scenario impact"), output="Comparison"),
    d("macro_overlay_share", "Macro Overlay Share", C.IFRS9,
      "The portion of ECL arising from post-model overlay rather than the model.",
      aliases=("overlay", "management adjustment"), fields=("macro_overlay",),
      limitations="A large overlay is a statement about model confidence, and "
                  "should be read as one."),
    d("model_vs_reported_ecl", "Model versus Reported ECL", C.IFRS9,
      "Modelled ECL against the figure actually booked.",
      fields=("model_ecl", "total_ecl")),
    d("stage_2_share", "Stage 2 Share", C.IFRS9,
      "Stage 2 exposure as a percentage of the total.",
      aliases=("stage 2 ratio", "SICR share"), output="Percentage",
      engine="stage_distribution", lifecycle=L.CERTIFIED),
    d("stage_3_share", "Stage 3 Share", C.IFRS9,
      "Stage 3 exposure as a percentage of the total.",
      aliases=("stage 3 ratio", "credit impaired share"), output="Percentage",
      engine="stage_distribution", lifecycle=L.CERTIFIED),
    d("provision_adequacy", "Provision Adequacy", C.IFRS9,
      "Coverage compared against realised loss experience.",
      limitations="Needs realised losses on closed cases; on an open book it is "
                  "an estimate compared against an estimate."),
]

# =====================================================  ratings

RATINGS: list[MethodDefinition] = [
    d("rating_distribution", "Rating Distribution", C.RATINGS,
      "Exposure and customers across internal rating grades.",
      aliases=("grade distribution", "rating profile"),
      fields=("internal_grade", "rating_bucket"), output="Distribution",
      engine="rating_grade_distribution", lifecycle=L.CERTIFIED),
    d("rating_migration", "Rating Migration", C.MIGRATION,
      "Movement between rating grades across two periods.",
      aliases=("grade migration", "rating movement"), history="Two periods",
      engine="rating_transition_matrix", lifecycle=L.CERTIFIED),
    d("rating_transition_matrix", "Rating Transition Matrix", C.MIGRATION,
      "The full from-grade to to-grade transition matrix, as conditional "
      "probabilities.",
      aliases=("transition matrix", "migration matrix", "rating matrix"),
      purpose="The input to almost every through-the-cycle credit model.",
      history="Two periods", output="Matrix",
      interpretation="Read rows, not cells: each row is the distribution of "
                     "outcomes conditional on starting in that grade.",
      engine="rating_transition_matrix", lifecycle=L.CERTIFIED),
    d("upgrade_rate", "Upgrade Rate", C.RATINGS,
      "The share of customers upgraded in a period.",
      aliases=("upgrades",), history="Two periods", output="Percentage",
      engine="rating_actions", lifecycle=L.CERTIFIED),
    d("downgrade_rate", "Downgrade Rate", C.RATINGS,
      "The share of customers downgraded in a period.",
      aliases=("downgrades",), history="Two periods", output="Percentage",
      engine="rating_actions", lifecycle=L.CERTIFIED),
    d("multi_notch_downgrade", "Multi-notch Downgrade", C.RATINGS,
      "Customers downgraded by two or more notches.",
      aliases=("severe downgrade", "sharp downgrade"), history="Two periods",
      interpretation="A multi-notch move usually means new information rather "
                     "than gradual drift, and is worth reading name by name."),
    d("rating_drift", "Rating Drift", C.RATINGS,
      "Net notch movement across the portfolio.",
      aliases=("net drift", "notch drift"), history="Two periods",
      output="Single value",
      limitations="A net figure. Large offsetting upgrades and downgrades "
                  "produce the same drift as no movement at all."),
    d("rating_momentum", "Rating Momentum", C.RATINGS,
      "Direction of rating movement sustained across several periods.",
      aliases=("momentum",), history="Three or more periods"),
    d("rating_stability", "Rating Stability", C.RATINGS,
      "The share of customers whose grade is unchanged.",
      aliases=("stability rate", "diagonal share"), history="Two periods",
      output="Percentage"),
    d("rating_override_rate", "Rating Override Rate", C.RATINGS,
      "The share of ratings overridden from the model output.",
      aliases=("override rate", "judgemental override"),
      limitations="A high override rate is a statement about the model, and "
                  "should trigger a review of it rather than of the overriders."),
    d("notch_gap_internal_external", "Internal versus External Notch Gap", C.RATINGS,
      "Difference between the internal grade and the external rating.",
      aliases=("notch gap", "rating gap"),
      fields=("internal_grade", "external_rating")),
    d("rating_actions", "Rating Actions", C.RATINGS,
      "Upgrades, downgrades, affirmations and new ratings in a period.",
      aliases=("rating activity",), engine="rating_actions", lifecycle=L.CERTIFIED),
    d("rating_coverage", "Rating Coverage", C.RATINGS,
      "The share of exposure carrying a current internal rating.",
      limitations="Unrated exposure is not low-risk exposure. It is unmeasured."),
    d("rating_staleness", "Rating Staleness", C.RATINGS,
      "Time since the last rating review.",
      aliases=("review overdue", "stale ratings"),
      interpretation="A stale rating on a deteriorating name is the most common "
                     "way a downgrade arrives late."),
    d("pd_by_grade", "PD by Grade", C.RATINGS,
      "Average probability of default within each rating grade.",
      fields=("internal_grade", "pd_12m_pct"), weighting=("EAD", "count")),
    d("grade_monotonicity", "Grade Monotonicity", C.RATINGS,
      "Whether realised default rates increase monotonically across grades.",
      aliases=("rank ordering", "discriminatory power"),
      purpose="The most basic test of whether a rating scale means anything.",
      history="Horizon plus one period",
      limitations="Needs enough defaults in every grade. Sparse grades produce "
                  "reversals that are noise, not a finding."),
]

# =====================================================  concentration

CONCENTRATION: list[MethodDefinition] = [
    d("sector_concentration", "Sector Concentration", C.CONCENTRATION,
      "Exposure distribution across industry sectors.",
      aliases=("industry concentration", "sector mix"),
      fields=("sector", "ead"), output="Distribution",
      engine="sector_concentration", lifecycle=L.CERTIFIED),
    d("geographic_concentration", "Geographic Concentration", C.CONCENTRATION,
      "Exposure distribution across regions or countries.",
      aliases=("regional concentration", "country concentration"),
      fields=("region", "country"), output="Distribution",
      engine="sector_concentration", lifecycle=L.CERTIFIED),
    d("product_concentration", "Product Concentration", C.CONCENTRATION,
      "Exposure distribution across products.", fields=("product_type",),
      output="Distribution", engine="sector_concentration", lifecycle=L.CERTIFIED),
    d("top_n_concentration", "Top-N Concentration", C.CONCENTRATION,
      "The share of exposure held by the largest N obligors.",
      aliases=("top 10 concentration", "largest exposures share"),
      grain="Customer", output="Percentage",
      engine="obligor_concentration", lifecycle=L.CERTIFIED),
    d("single_name_concentration", "Single Name Concentration", C.CONCENTRATION,
      "The largest single obligor exposure as a share of the book or of capital.",
      aliases=("single obligor", "largest name"),
      engine="obligor_concentration", lifecycle=L.CERTIFIED),
    d("herfindahl_index", "Herfindahl-Hirschman Index", C.CONCENTRATION,
      "The sum of squared exposure shares, as a concentration measure.",
      aliases=("HHI", "Herfindahl"),
      methodology="Sum of the squares of each obligor's or sector's share of "
                  "total exposure. Ranges from near zero for a perfectly "
                  "diversified book to one for a single name.",
      interpretation="Sensitive to the largest positions by construction, which "
                     "is usually what is wanted.",
      output="Index",
      limitations="Scale-free, so it cannot say whether a concentration is "
                  "affordable — that needs capital."),
    d("gini_coefficient", "Gini Coefficient", C.CONCENTRATION,
      "Inequality of the exposure distribution.",
      aliases=("Gini", "concentration curve"), output="Index",
      limitations="Two very different distributions can share a Gini. Read the "
                  "curve, not only the number."),
    d("large_exposure_share", "Large Exposure Share", C.LIMITS,
      "Exposure above the regulatory large-exposure threshold, as a share of "
      "capital.",
      aliases=("large exposures", "LE ratio"),
      limitations="Threshold and capital base are jurisdiction-specific and must "
                  "be configured, not assumed."),
    d("group_concentration", "Connected Group Concentration", C.CONCENTRATION,
      "Exposure aggregated across a connected group of borrowers.",
      aliases=("obligor group", "connected counterparties"),
      fields=("obligor_group",),
      limitations="Only as good as the group structure recorded. Undetected "
                  "connection is the risk this measure exists to find."),
    d("sector_correlation", "Sector Correlation", C.CONCENTRATION,
      "Co-movement of default experience across sectors.",
      history="Several periods",
      limitations="Correlation estimated on few periods is mostly noise."),
    d("name_concentration_capital", "Name Concentration Capital Add-on",
      C.CONCENTRATION,
      "Capital uplift for single-name concentration.",
      lifecycle=L.PREVIEW,
      limitations="Requires an approved internal methodology. Shipped as a "
                  "definition only."),
]

# =====================================================  vintage & cohort

VINTAGE: list[MethodDefinition] = [
    d("vintage_default_rate", "Vintage Default Rate", C.VINTAGE,
      "Default experience by origination cohort and months on book.",
      aliases=("vintage curve", "vintage analysis", "cohort default"),
      purpose="Separates a deteriorating book from a growing one: if each "
              "vintage performs like the last, the rise in defaults is volume.",
      grain="Facility with an origination date", history="Several periods",
      output="Matrix",
      interpretation="Read down a column to compare vintages at the same age. "
                     "Comparing across ages is comparing different questions.",
      limitations="Young vintages are incomplete by construction and always look "
                  "better."),
    d("vintage_delinquency", "Vintage Delinquency", C.VINTAGE,
      "Delinquency by origination cohort and months on book.",
      aliases=("vintage arrears",), output="Matrix"),
    d("cohort_default_rate", "Cohort Default Rate", C.VINTAGE,
      "Default rate within a fixed opening cohort over time.",
      aliases=("static pool",), output="Time series"),
    d("cohort_cure_rate", "Cohort Cure Rate", C.VINTAGE,
      "Cure experience within a fixed cohort.", output="Time series"),
    d("origination_quality", "Origination Quality", C.VINTAGE,
      "Rating and financial profile of new lending by period.",
      aliases=("new business quality",),
      interpretation="Deteriorating origination quality shows in the book two to "
                     "three years later, which is why it is worth watching now."),
    d("seasoning_curve", "Seasoning Curve", C.VINTAGE,
      "How default rates vary with months on book.",
      aliases=("seasoning", "age curve"), output="Time series"),
    d("months_on_book_distribution", "Months on Book Distribution", C.VINTAGE,
      "The age profile of the portfolio.", output="Distribution"),
]

# =====================================================  collateral & covenants

COLLATERAL: list[MethodDefinition] = [
    d("collateral_coverage", "Collateral Coverage", C.COLLATERAL,
      "Collateral value as a percentage of exposure.",
      aliases=("security coverage", "collateral ratio"),
      fields=("collateral_value", "ead"), output="Percentage",
      engine="collateral_coverage", lifecycle=L.CERTIFIED),
    d("loan_to_value", "Loan to Value", C.COLLATERAL,
      "Exposure as a percentage of collateral value.",
      aliases=("LTV",), output="Percentage",
      limitations="Only as current as the last valuation. An LTV computed on a "
                  "three-year-old valuation is a number about the past."),
    d("collateral_shortfall", "Collateral Shortfall", C.COLLATERAL,
      "Exposure in excess of collateral value.",
      aliases=("uncovered exposure", "unsecured portion"), output="Single value"),
    d("coverage_deterioration", "Coverage Deterioration", C.COLLATERAL,
      "Reduction in collateral coverage between periods.",
      history="Two periods", output="Percentage"),
    d("haircut_impact", "Haircut Impact", C.COLLATERAL,
      "Coverage after applying valuation haircuts.",
      interpretation="The gap between headline and post-haircut coverage is the "
                     "part of security the bank does not really have."),
    d("valuation_staleness", "Valuation Staleness", C.COLLATERAL,
      "Time since the last collateral valuation.",
      aliases=("stale valuations",)),
    d("collateral_type_mix", "Collateral Type Mix", C.COLLATERAL,
      "Distribution of collateral by type.",
      fields=("collateral_type",), output="Distribution",
      limitations="Type is a poor proxy for realisability. Cash and a second "
                  "charge over specialised plant are both 'secured'."),
    d("unsecured_share", "Unsecured Share", C.COLLATERAL,
      "Exposure with no collateral, as a share of the book.",
      output="Percentage"),
    d("covenant_breach_rate", "Covenant Breach Rate", C.COVENANTS,
      "The share of facilities in breach of a financial covenant.",
      aliases=("breach rate",), output="Percentage"),
    d("covenant_headroom", "Covenant Headroom", C.COVENANTS,
      "Distance between the current ratio and its covenant threshold.",
      aliases=("headroom",), fields=("covenant_headroom_pct",),
      interpretation="Thin headroom on a covenant tested quarterly is a warning "
                     "with a known date attached."),
    d("near_breach_rate", "Near-Breach Rate", C.COVENANTS,
      "Facilities within a defined margin of breaching.",
      aliases=("approaching breach",)),
    d("waiver_rate", "Waiver Rate", C.COVENANTS,
      "The share of breaches waived rather than enforced.",
      limitations="A high waiver rate makes the breach rate uninformative."),
    d("covenant_deterioration", "Covenant Deterioration", C.COVENANTS,
      "Reduction in headroom between periods.", history="Two periods"),
]

# =====================================================  watchlist & early warning

WATCHLIST: list[MethodDefinition] = [
    d("watchlist_exposure", "Watchlist Exposure", C.WATCHLIST,
      "Exposure on names currently on the watchlist.",
      fields=("watchlist", "ead"), output="Single value",
      engine="watchlist_movement", lifecycle=L.CERTIFIED),
    d("watchlist_movement", "Watchlist Movement", C.WATCHLIST,
      "Names entering and leaving the watchlist between periods.",
      aliases=("watchlist flow",), history="Two periods",
      engine="watchlist_movement", lifecycle=L.CERTIFIED),
    d("watchlist_entry_rate", "Watchlist Entry Rate", C.WATCHLIST,
      "New watchlist entries as a share of the performing book.",
      history="Two periods", output="Percentage"),
    d("watchlist_exit_rate", "Watchlist Exit Rate", C.WATCHLIST,
      "Names leaving the watchlist as a share of the opening watchlist.",
      history="Two periods", output="Percentage",
      limitations="Exits to default and exits to recovery are opposite outcomes "
                  "and must be separated."),
    d("watchlist_cure", "Watchlist Cure", C.WATCHLIST,
      "Watchlist names returning to normal monitoring.",
      history="Two periods", output="Percentage"),
    d("watchlist_to_default", "Watchlist to Default", C.WATCHLIST,
      "Watchlist names that subsequently defaulted.",
      purpose="The measure that says whether the watchlist is doing its job.",
      history="Horizon plus one period", output="Percentage"),
    d("watchlist_tenure", "Watchlist Tenure", C.WATCHLIST,
      "How long names have been on the watchlist.",
      interpretation="A name on the watchlist for three years is either "
                     "mismanaged or misclassified."),
    d("early_warning_signal", "Forward Risk Signal", C.EARLY_WARNING,
      "CreditProbe's composite forward-looking risk indicator.",
      aliases=("forward risk signal", "early warning score"),
      lifecycle=L.PREVIEW,
      limitations="A prototype. No predictive accuracy has been established, and "
                  "none is claimed."),
    d("stage_1_to_default", "Stage 1 to Default Emergence", C.EARLY_WARNING,
      "Facilities moving from Stage 1 directly to default.",
      purpose="Direct jumps to default are the failures of early warning, by "
              "definition.",
      history="Two periods", output="Percentage"),
    d("warning_capture_rate", "Warning Capture Rate", C.EARLY_WARNING,
      "The share of defaults that were flagged in advance.",
      aliases=("capture rate", "hit rate"),
      history="Horizon plus one period", output="Percentage",
      limitations="Meaningless without the false alert rate beside it. A system "
                  "that flags everything captures everything."),
    d("false_alert_rate", "False Alert Rate", C.EARLY_WARNING,
      "The share of alerts not followed by deterioration.",
      aliases=("false positive rate",), output="Percentage",
      limitations="Requires a defined observation window and an agreed definition "
                  "of deterioration."),
    d("alert_stability", "Alert Stability", C.EARLY_WARNING,
      "How persistently the same names are flagged across periods.",
      history="Several periods",
      interpretation="Alerts that appear and vanish each period are noise "
                     "wearing the costume of a signal."),
    d("credit_file_signals", "Credit File Signals", C.EARLY_WARNING,
      "What the credit file notes raised, as structured signals.",
      aliases=("credit memo signals", "qualitative signals"),
      engine="credit_file_signals", lifecycle=L.CERTIFIED),
    d("top_deteriorating_borrowers", "Top Deteriorating Borrowers", C.EARLY_WARNING,
      "The borrowers whose position worsened most between two periods.",
      aliases=("worst movers", "deterioration ranking"), history="Two periods",
      engine="top_deteriorating_borrowers", lifecycle=L.CERTIFIED),
    d("high_utilisation_watchlist", "High Utilisation Watchlist", C.EARLY_WARNING,
      "Facilities drawn unusually heavily against their limits.",
      engine="high_utilisation_watchlist", lifecycle=L.PRECONFIGURED,
      limitations="Deliberately user-defined rather than certified: the "
                  "threshold is a policy choice, not a methodology."),
]

# =====================================================  risk appetite & limits

APPETITE: list[MethodDefinition] = [
    d("limit_breach", "Limit Breach", C.RISK_APPETITE,
      "Facilities or portfolios exceeding an approved limit.",
      aliases=("breach", "appetite breach"), fields=("appetite_breach",)),
    d("sector_limit_utilisation", "Sector Limit Utilisation", C.RISK_APPETITE,
      "Sector exposure against its approved limit.",
      aliases=("sector appetite",), output="Percentage"),
    d("single_name_limit", "Single Name Limit Utilisation", C.LIMITS,
      "Obligor exposure against the single-name limit.", output="Percentage"),
    d("concentration_threshold_breach", "Concentration Threshold Breach",
      C.RISK_APPETITE,
      "Concentrations exceeding the threshold set by appetite."),
    d("stage_2_appetite_threshold", "Stage 2 Appetite Threshold", C.RISK_APPETITE,
      "Stage 2 share against its appetite threshold.", output="Percentage"),
    d("npl_appetite_threshold", "NPL Appetite Threshold", C.RISK_APPETITE,
      "NPL ratio against its appetite threshold.", output="Percentage"),
    d("appetite_dashboard", "Risk Appetite Position", C.RISK_APPETITE,
      "Every appetite measure against its threshold, in one view.",
      output="Table"),
    d("limit_headroom", "Limit Headroom", C.LIMITS,
      "Remaining capacity under approved limits.", output="Single value"),
    d("temporary_excess", "Temporary Excess", C.LIMITS,
      "Approved excesses over limit and their expiry.",
      limitations="A temporary excess renewed four times is a limit increase "
                  "nobody approved."),
    d("large_exposure_count", "Large Exposure Count", C.LIMITS,
      "Number of exposures above the large-exposure threshold."),
]

# =====================================================  stress & scenario

STRESS: list[MethodDefinition] = [
    d("stress_scenario_basic", "Management Stress Scenario", C.STRESS,
      "Portfolio impact under a declared set of shocks.",
      aliases=("stress test", "management scenario"),
      engine="stress_scenario_basic", lifecycle=L.CERTIFIED),
    d("ecl_stress", "ECL Stress", C.STRESS,
      "Expected credit loss under stressed assumptions.", output="Comparison"),
    d("pd_stress", "PD Stress", C.STRESS,
      "Probability of default under stressed assumptions."),
    d("lgd_stress", "LGD Stress", C.STRESS,
      "Loss given default under stressed assumptions."),
    d("exposure_stress", "Exposure Stress", C.STRESS,
      "Exposure under stressed drawdown assumptions.",
      interpretation="Undrawn commitments are drawn in a stress, which is the "
                     "point of stressing them."),
    d("sector_stress", "Sector Stress", C.STRESS,
      "A shock applied to one sector rather than the whole book."),
    d("scenario_comparison", "Scenario Comparison", C.STRESS,
      "Two or more scenarios side by side.", output="Comparison"),
    d("sensitivity_analysis", "Sensitivity Analysis", C.STRESS,
      "How the result moves as one assumption moves.",
      aliases=("what-if", "sensitivity"),
      interpretation="Shows which assumption the answer actually depends on, "
                     "which is often not the one under discussion."),
    d("reverse_stress", "Reverse Stress", C.STRESS,
      "The shock required to breach a stated threshold.",
      lifecycle=L.PREVIEW,
      limitations="Needs a solver over the scenario space. Shipped as a "
                  "definition only."),
    d("macroeconomic_context", "Macroeconomic Context", C.STRESS,
      "The macro series the portfolio lends into.",
      engine="macroeconomic_context", lifecycle=L.CERTIFIED),
]

# =====================================================  return & profitability

RETURN: list[MethodDefinition] = [
    d("raroc", "RAROC", C.RETURN,
      "Risk-adjusted return on capital.",
      aliases=("risk adjusted return on capital",), fields=("raroc_pct",),
      limitations="Only as good as the capital allocation behind it, which is a "
                  "methodology in its own right."),
    d("risk_adjusted_margin", "Risk-Adjusted Margin", C.RETURN,
      "Margin after expected loss.", aliases=("RAM", "net margin after EL")),
    d("expected_loss_rate", "Expected Loss Rate", C.RETURN,
      "Expected loss as a rate on exposure.", aliases=("EL rate",),
      output="Percentage"),
    d("risk_adjusted_return", "Risk-Adjusted Return", C.RETURN,
      "Return after adjusting for expected loss and capital."),
    d("economic_capital", "Economic Capital", C.RETURN,
      "Capital required for unexpected loss.", lifecycle=L.PREVIEW,
      limitations="Requires an approved internal capital methodology. Shipped as "
                  "a definition only."),
    d("net_interest_margin", "Net Interest Margin", C.RETURN,
      "Interest income less funding cost, over earning assets.",
      aliases=("NIM",)),
    d("cost_of_risk", "Cost of Risk", C.RETURN,
      "Impairment charge as a rate on average exposure.",
      aliases=("CoR", "credit cost"), output="Percentage"),
    d("portfolio_yield", "Portfolio Yield", C.RETURN,
      "Interest yield on the credit book.", fields=("eir_pct",)),
]

# =====================================================  portfolio monitoring

MONITORING: list[MethodDefinition] = [
    d("portfolio_summary", "Portfolio Summary", C.PORTFOLIO_QUALITY,
      "The headline position: exposure, staging, coverage, NPL and appetite.",
      aliases=("headline position", "portfolio position", "book summary"),
      engine="portfolio_summary", lifecycle=L.CERTIFIED),
    d("portfolio_trend", "Portfolio Trend", C.PORTFOLIO_QUALITY,
      "Exposure, staging and coverage across every available period.",
      aliases=("trend", "history"), history="Several periods",
      engine="portfolio_trend", lifecycle=L.CERTIFIED),
    d("quality_migration_summary", "Quality Migration Summary", C.MIGRATION,
      "Every migration measure in one view.", history="Two periods"),
    d("portfolio_composition_shift", "Composition Shift", C.PORTFOLIO_QUALITY,
      "How the mix of the book changed between periods.",
      history="Two periods",
      interpretation="A ratio can move entirely because the mix moved. This "
                     "separates the two."),
    d("book_growth_decomposition", "Book Growth Decomposition", C.PORTFOLIO_QUALITY,
      "Growth split into new lending, runoff and drawdown.",
      history="Two periods", output="Waterfall"),
]



# =====================================================  data quality & controls

CONTROLS: list[MethodDefinition] = [
    d("population_reconciliation", "Population Reconciliation", C.PORTFOLIO_QUALITY,
      "Whether the facilities in one dataset match those in another for the "
      "same period.",
      aliases=("population check", "coverage reconciliation"),
      purpose="A ratio computed over two populations that are not the same "
              "population is not a ratio.",
      history="One period, two datasets",
      limitations="Finds the mismatch. Deciding which dataset is right is a "
                  "stewardship question, not an analytical one."),
    d("orphan_rate", "Orphan Rate", C.PORTFOLIO_QUALITY,
      "Records in one dataset with no match in the dataset they should join to.",
      aliases=("unmatched rate", "join failure rate"), output="Percentage"),
    d("duplicate_key_rate", "Duplicate Key Rate", C.PORTFOLIO_QUALITY,
      "Keys appearing more than once where the grain says they should not.",
      aliases=("duplicates",),
      interpretation="A duplicate key silently multiplies every sum computed "
                     "over a join."),
    d("missing_field_rate", "Missing Field Rate", C.PORTFOLIO_QUALITY,
      "The share of records with no value in a mandatory field.",
      aliases=("null rate", "completeness"), output="Percentage"),
    d("period_completeness", "Period Completeness", C.PORTFOLIO_QUALITY,
      "Whether every expected reporting period is present.",
      aliases=("period gaps",),
      limitations="A missing period in a trend is not a flat quarter; it is an "
                  "absent one, and charts should show the gap."),
    d("identifier_continuity", "Identifier Continuity", C.PORTFOLIO_QUALITY,
      "Whether facility and customer identifiers persist across periods.",
      purpose="Every migration measure in this library depends on it.",
      history="Two periods",
      limitations="Re-papered facilities break continuity legitimately, and look "
                  "identical to a data problem."),
]

# =====================================================  covenants, extended

COVENANTS_EXTRA: list[MethodDefinition] = [
    d("leverage_covenant_position", "Leverage Covenant Position", C.COVENANTS,
      "Net leverage against its covenant threshold.",
      fields=("net_leverage",), output="Distribution"),
    d("dscr_covenant_position", "DSCR Covenant Position", C.COVENANTS,
      "Debt service coverage against its covenant threshold.",
      aliases=("debt service coverage",), fields=("dscr",)),
    d("interest_cover_position", "Interest Cover Position", C.COVENANTS,
      "Interest coverage against its covenant threshold.",
      fields=("interest_coverage",)),
    d("covenant_test_calendar", "Covenant Test Calendar", C.COVENANTS,
      "When each covenant is next tested.",
      interpretation="A thin headroom matters more the closer the test date is."),
    d("covenant_breach_severity", "Covenant Breach Severity", C.COVENANTS,
      "How far past the threshold a breach is.",
      limitations="Severity and consequence are different. A small breach of a "
                  "hard covenant can matter more than a large breach of a soft one."),
    d("covenant_cure_rate", "Covenant Cure Rate", C.COVENANTS,
      "Breaches remedied within the cure period.", output="Percentage"),
]

# =====================================================  appetite, extended

APPETITE_EXTRA: list[MethodDefinition] = [
    d("appetite_utilisation_trend", "Appetite Utilisation Trend", C.RISK_APPETITE,
      "Movement towards or away from appetite thresholds over time.",
      history="Several periods", output="Time series"),
    d("appetite_breach_ageing", "Appetite Breach Ageing", C.RISK_APPETITE,
      "How long each appetite breach has been outstanding.",
      interpretation="A breach open for four quarters is a decision that was "
                     "never made rather than a limit that was exceeded."),
    d("sector_appetite_headroom", "Sector Appetite Headroom", C.RISK_APPETITE,
      "Remaining capacity within each sector limit.", output="Table"),
    d("country_limit_utilisation", "Country Limit Utilisation", C.LIMITS,
      "Country exposure against its approved limit.", output="Percentage"),
    d("tenor_limit_utilisation", "Tenor Limit Utilisation", C.LIMITS,
      "Long-tenor exposure against its limit."),
    d("product_limit_utilisation", "Product Limit Utilisation", C.LIMITS,
      "Product exposure against its limit."),
    d("connected_party_exposure", "Connected Party Exposure", C.LIMITS,
      "Exposure to parties connected to the bank.",
      limitations="Depends entirely on the connected-party register being "
                  "current."),
]

# =====================================================  vintage, extended

VINTAGE_EXTRA: list[MethodDefinition] = [
    d("vintage_loss_rate", "Vintage Loss Rate", C.VINTAGE,
      "Realised loss by origination cohort.", output="Matrix",
      limitations="Only complete for cohorts old enough to have finished losing."),
    d("vintage_prepayment", "Vintage Prepayment", C.VINTAGE,
      "Early repayment by origination cohort."),
    d("vintage_utilisation", "Vintage Utilisation", C.VINTAGE,
      "Drawdown behaviour by origination cohort."),
    d("cohort_migration", "Cohort Migration", C.VINTAGE,
      "Rating or stage movement within a fixed cohort.", history="Two periods"),
    d("first_payment_default", "First Payment Default", C.VINTAGE,
      "Facilities that miss their first scheduled payment.",
      aliases=("FPD",),
      interpretation="Almost always an underwriting finding rather than a credit "
                     "one."),
]

# =====================================================  return, extended

RETURN_EXTRA: list[MethodDefinition] = [
    d("provision_charge", "Provision Charge", C.RETURN,
      "The impairment charge recognised in the period.",
      aliases=("impairment charge", "credit charge"), history="Two periods"),
    d("net_credit_loss", "Net Credit Loss", C.RETURN,
      "Write-offs less recoveries.", output="Single value"),
    d("risk_weighted_assets", "Risk Weighted Assets", C.RETURN,
      "Exposure weighted by risk under the applicable approach.",
      aliases=("RWA",), lifecycle=L.PREVIEW,
      limitations="Requires the bank's approved regulatory approach. Shipped as "
                  "a definition only."),
    d("capital_consumption", "Capital Consumption", C.RETURN,
      "Capital absorbed by a portfolio or a name.", lifecycle=L.PREVIEW),
    d("return_on_exposure", "Return on Exposure", C.RETURN,
      "Income as a rate on average exposure.", output="Percentage"),
    d("fee_income_share", "Fee Income Share", C.RETURN,
      "Fee income as a share of total income from a relationship."),
]

# =====================================================  early warning, extended

EARLY_WARNING_EXTRA: list[MethodDefinition] = [
    d("deterioration_breadth", "Deterioration Breadth", C.EARLY_WARNING,
      "How many names are deteriorating, as against how much exposure.",
      history="Two periods",
      interpretation="Broad and shallow is a cycle; narrow and deep is a name."),
    d("consecutive_deterioration", "Consecutive Deterioration", C.EARLY_WARNING,
      "Names that worsened in two or more consecutive periods.",
      history="Three periods",
      interpretation="Persistence separates a trend from a fluctuation."),
    d("signal_lead_time", "Signal Lead Time", C.EARLY_WARNING,
      "How far in advance of default a signal fired.",
      purpose="A warning that arrives with the default is not a warning.",
      history="Horizon plus one period",
      limitations="Measurable only on names that actually defaulted, which is a "
                  "biased sample by construction."),
    d("payment_behaviour_shift", "Payment Behaviour Shift", C.EARLY_WARNING,
      "Change in payment timing or amount ahead of formal arrears.",
      aliases=("behavioural signal",),
      interpretation="Behaviour usually moves before status does, which is the "
                     "whole argument for watching it."),
    d("limit_drawdown_spike", "Limit Drawdown Spike", C.EARLY_WARNING,
      "Sudden increases in utilisation.", history="Two periods"),
    d("covenant_and_rating_together", "Covenant and Rating Together",
      C.EARLY_WARNING,
      "Names where covenant headroom is thin and the rating is falling.",
      purpose="Two independent signals agreeing is worth more than either alone.",
      history="Two periods"),
]

#: Dimension cuts. Real questions a credit committee asks, and each one is a
#: distinct entry because "by sector" and "by region" reach different data.
DIMENSIONS = [("sector", "by Sector"), ("region", "by Region"),
              ("segment", "by Segment"), ("product", "by Product"),
              ("rating", "by Rating Grade"), ("stage", "by IFRS 9 Stage"),
              ("country", "by Country"), ("vintage", "by Vintage")]

CUTS: list[MethodDefinition] = []
for _base, _label, _cat, _fields in [
    ("ead", "Exposure", C.EXPOSURE, ("ead",)),
    ("npl", "NPL Ratio", C.PORTFOLIO_QUALITY, ("ead", "npl")),
    ("ecl_coverage", "ECL Coverage", C.IFRS9, ("total_ecl", "ead")),
    ("stage2", "Stage 2 Share", C.IFRS9, ("ifrs9_stage", "ead")),
    ("stage3", "Stage 3 Share", C.IFRS9, ("ifrs9_stage", "ead")),
    ("dpd90", "90+ Delinquency", C.DEFAULT_DELINQUENCY, ("days_past_due",)),
    ("utilisation", "Utilisation", C.EXPOSURE, ("exposure", "limit_amount")),
    ("pd", "Average PD", C.RATINGS, ("pd_12m_pct",)),
    ("lgd", "Average LGD", C.IFRS9, ("lgd_pct",)),
    ("collateral", "Collateral Coverage", C.COLLATERAL, ("collateral_value", "ead")),
    ("arrears", "Arrears", C.DEFAULT_DELINQUENCY, ("arrears_amount",)),
    ("watchlist", "Watchlist Share", C.WATCHLIST, ("watchlist", "ead")),
]:
    for _key, _suffix in DIMENSIONS:
        CUTS.append(d(
            f"{_base}_by_{_key}", f"{_label} {_suffix}", _cat,
            f"{_label} broken down {_suffix.lower()}.",
            aliases=(f"{_label.lower()} {_suffix.lower()}",),
            fields=_fields, output="Distribution",
            when_to_use=f"Locating where a portfolio-level {_label.lower()} "
                        f"figure is coming from.",
            limitations="A breakdown, not an explanation. It shows where, not why.",
        ))

#: Period-comparison variants. "How did X change" is a different method from
#: "what is X", because it needs two periods and a stable identifier.
CHANGES: list[MethodDefinition] = [
    d(f"{_base}_change", f"{_label} Change", _cat,
      f"Change in {_label.lower()} between two reporting periods.",
      aliases=(f"{_label.lower()} movement", f"{_label.lower()} delta"),
      history="Two periods", output="Comparison",
      limitations="Requires the population to be identifiable in both periods. "
                  "Entries and exits are movements too, and must be shown "
                  "separately rather than netted away.")
    for _base, _label, _cat in [
        ("ead", "Exposure", C.EXPOSURE),
        ("npl", "NPL Ratio", C.PORTFOLIO_QUALITY),
        ("ecl", "ECL", C.IFRS9),
        ("coverage", "Coverage", C.IFRS9),
        ("stage2", "Stage 2 Share", C.IFRS9),
        ("stage3", "Stage 3 Share", C.IFRS9),
        ("pd", "PD", C.RATINGS),
        ("lgd", "LGD", C.IFRS9),
        ("utilisation", "Utilisation", C.EXPOSURE),
        ("collateral", "Collateral Coverage", C.COLLATERAL),
        ("arrears", "Arrears", C.DEFAULT_DELINQUENCY),
        ("watchlist", "Watchlist Exposure", C.WATCHLIST),
        ("rating", "Rating Distribution", C.RATINGS),
        ("dpd", "Delinquency", C.DEFAULT_DELINQUENCY),
        ("concentration", "Concentration", C.CONCENTRATION),
    ]
]

#: Ranking variants. "Top ten by X" is how most portfolio questions are actually
#: asked, and each measure is a separate entry because each reaches a field.
RANKINGS: list[MethodDefinition] = [
    d(f"top_borrowers_by_{_base}", f"Top Borrowers by {_label}", _cat,
      f"The largest borrowers ranked by {_label.lower()}.",
      aliases=(f"largest by {_label.lower()}", f"top 10 {_label.lower()}"),
      grain="Customer", output="Ranked table",
      limitations="A ranking, not a threshold. Being in a top ten says nothing "
                  "about whether the position is acceptable.")
    for _base, _label, _cat in [
        ("ead", "Exposure", C.CONCENTRATION),
        ("ecl", "ECL", C.IFRS9),
        ("ecl_increase", "ECL Increase", C.IFRS9),
        ("arrears", "Arrears", C.DEFAULT_DELINQUENCY),
        ("downgrade", "Downgrade", C.RATINGS),
        ("utilisation", "Utilisation", C.EXPOSURE),
        ("uncovered", "Uncovered Exposure", C.COLLATERAL),
        ("coverage_gap", "Coverage Gap", C.IFRS9),
        ("pd_increase", "PD Increase", C.RATINGS),
        ("limit_excess", "Limit Excess", C.LIMITS),
    ]
]


#: Written out by hand, one entry at a time. Authoritative.
_WRITTEN = [PORTFOLIO, ASSET_QUALITY, IFRS9, RATINGS, CONCENTRATION, VINTAGE,
            COLLATERAL, WATCHLIST, APPETITE, STRESS, RETURN, MONITORING,
            CONTROLS, COVENANTS_EXTRA, APPETITE_EXTRA, VINTAGE_EXTRA,
            RETURN_EXTRA, EARLY_WARNING_EXTRA]

#: Generated families — the same method asked along a dimension, across two
#: periods, or as a ranking. Real questions, but the difference between entries
#: is the cut rather than the methodology.
_GENERATED = [CUTS, CHANGES, RANKINGS]


def all_definitions() -> list[MethodDefinition]:
    """Every entry in the library, deduplicated by id.

    A duplicate id among the hand-written entries is a mistake in this file and
    raises. A generated entry colliding with a hand-written one is not: the
    hand-written entry is richer and simply wins, which is what lets the
    generated families be produced mechanically without having to know what has
    already been described properly.
    """
    seen: dict[str, MethodDefinition] = {}
    for block in _WRITTEN:
        for method in block:
            if method.id in seen:
                raise ValueError(
                    f"Two library entries share the id '{method.id}'. If they "
                    "mean the same thing, make one an alias of the other."
                )
            seen[method.id] = method

    for block in _GENERATED:
        for method in block:
            seen.setdefault(method.id, method)

    return list(seen.values())


__all__ = ["all_definitions"]
