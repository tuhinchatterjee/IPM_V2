"""The Scorecard Validation Test Registry. §8, §9.

Every validation test the environment can run, defined in one place: what it
measures, what it needs, what it refuses, what it draws, and which article of
the CBUAE Model Management Standards and Guidance it speaks to.

Why a registry rather than definitions beside the code that runs them
-----------------------------------------------------------------------
Three questions get asked constantly during a validation, and only a registry
answers them cheaply:

* *What can be run against this model?* — which depends on what the model is.
  A rank-order scorecard with no score-to-PD mapping has no calibration to
  test, and the honest answer is a list that omits those tests rather than a
  list that offers them and then fails.
* *What did we not run, and why?* — a validation report has to state its own
  scope, and "we ran twenty-three tests" is not a scope. "These eleven were
  not applicable and these three had no matured cohort" is.
* *Where does this limit come from?* — a threshold with no provenance becomes
  a regulatory requirement the third time somebody reads the table. Every
  limit here carries its source, and the seeded ones say DEMO POLICY.

Scattering the definitions across the page components makes all three
unanswerable, and makes the twelfth test somebody adds subtly different from
the eleven before it.

What is in scope for a definition
-----------------------------------
A `Test` says what a test IS. It does not say how to compute it — that is
`runner.py`, which reads the definition and calls the governed kernels in
`backend/scorecard/metrics.py`. Keeping them apart is what stops the registry
becoming a second calculation engine, and it is why `metrics.py` is still the
only place an AUC is computed.

Applicability is a property, not a filter
-------------------------------------------
`applies_to` is checked against the model's own registry entry, so a model
with no `pd_column` genuinely cannot reach the calibration tests. That is a
NOT_APPLICABLE with a reason rather than a test that runs and returns
nonsense, and the distinction matters most for the case §13 names
specifically: a scorecard that produces only an ordinal score has no
calibration statistics, and inventing them is worse than omitting them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REGISTRY_VERSION = "1.0.0"

# ================================================================= categories

DATA_QUALITY = "data_quality"
CONCEPTUAL = "conceptual_soundness"
DISCRIMINATION = "discrimination"
CALIBRATION = "calibration"
STABILITY = "stability"
ROBUSTNESS = "robustness"
VARIABLES = "variables"
USAGE = "usage_overrides"
IMPLEMENTATION = "implementation"
SEGMENTATION = "segmentation"
CHAMPION_CHALLENGER = "champion_challenger"

CATEGORIES: tuple[str, ...] = (
    DATA_QUALITY, CONCEPTUAL, DISCRIMINATION, CALIBRATION, STABILITY,
    ROBUSTNESS, VARIABLES, USAGE, IMPLEMENTATION, SEGMENTATION,
    CHAMPION_CHALLENGER,
)


@dataclass(frozen=True)
class Category:
    """One clickable card under the chat box."""

    key: str
    title: str
    purpose: str
    #: What a validator is actually trying to find out. Written as the
    #: question rather than as the topic, because the card is the start of a
    #: conversation and a topic is not something you can answer.
    question: str
    quantitative: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "title": self.title, "purpose": self.purpose,
            "question": self.question, "quantitative": self.quantitative,
        }


CATEGORY_DEFINITIONS: tuple[Category, ...] = (
    Category(DATA_QUALITY, "Data & Representativeness",
             "Whether the population the model is being judged on is fit to "
             "judge it.",
             "Is this data complete, current, and representative of what the "
             "model was built for?"),
    Category(CONCEPTUAL, "Conceptual Soundness & Design",
             "Whether the model is a sensible answer to the question it was "
             "built for, independently of how it performs.",
             "Is the design defensible, documented and used as intended?",
             quantitative=False),
    Category(DISCRIMINATION, "Discrimination",
             "Whether the score separates the accounts that default from "
             "those that do not.",
             "Does this model rank risk?"),
    Category(CALIBRATION, "Calibration & Accuracy",
             "Whether the predicted probabilities match what happened.",
             "Are the predicted default rates right, not just ordered right?"),
    Category(STABILITY, "Stability",
             "Whether the population and the characteristics have moved away "
             "from what the model was fitted on.",
             "Is the model still looking at the same kind of book?"),
    Category(ROBUSTNESS, "Robustness & Sensitivity",
             "Whether the result survives a reasonable change to the sample, "
             "the window or the inputs.",
             "How much does the answer depend on choices we happened to make?"),
    Category(VARIABLES, "Variables & Binning",
             "Whether each characteristic still carries the signal the model "
             "credits it with.",
             "Which variables are doing the work, and which have stopped?"),
    Category(USAGE, "Model Usage, Overrides & Policy",
             "Whether the model is used as designed, and what happens when "
             "somebody departs from it.",
             "Is the score being followed, and do the departures perform?"),
    Category(IMPLEMENTATION, "Implementation Verification",
             "Whether the production score is the score the specification "
             "describes.",
             "Does the system compute what the document says it computes?"),
    Category(SEGMENTATION, "Segmentation",
             "Whether performance holds inside the segments the book is "
             "actually managed by.",
             "Does the aggregate result conceal a segment where it fails?"),
    Category(CHAMPION_CHALLENGER, "Champion vs Challenger",
             "Whether the alternative is better on the whole, not only on "
             "one metric.",
             "Should we replace the champion — and what would we be trading?"),
)

BY_CATEGORY_KEY: dict[str, Category] = {c.key: c for c in CATEGORY_DEFINITIONS}


# =============================================================== requirements

#: What a test needs on the row before it can run. Checked against the
#: model's registry entry, so the answer is NOT_APPLICABLE with a reason
#: rather than a KeyError three layers down.
NEEDS_OUTCOME = "outcome"          # a realised default flag on a matured cohort
NEEDS_SCORE = "score"              # a points score
NEEDS_PD = "predicted_pd"          # a score-to-PD mapping
NEEDS_BINS = "approved_bins"       # the `_bin` and `_woe` columns
NEEDS_REFERENCE = "reference_population"
NEEDS_CHALLENGER = "challenger"
NEEDS_DECISIONS = "decisions"      # the approval/override file
NEEDS_EQUATION = "equation"        # the coefficients, to replicate a score

REQUIREMENTS: tuple[str, ...] = (
    NEEDS_OUTCOME, NEEDS_SCORE, NEEDS_PD, NEEDS_BINS, NEEDS_REFERENCE,
    NEEDS_CHALLENGER, NEEDS_DECISIONS, NEEDS_EQUATION,
)

REQUIREMENT_MEANING: dict[str, str] = {
    NEEDS_OUTCOME: "a realised outcome, which means a matured cohort",
    NEEDS_SCORE: "a points score",
    NEEDS_PD: "a governed score-to-PD mapping",
    NEEDS_BINS: "the approved bin and weight-of-evidence columns",
    NEEDS_REFERENCE: "a reference population to compare against",
    NEEDS_CHALLENGER: "a registered challenger",
    NEEDS_DECISIONS: "the recorded credit decisions and overrides",
    NEEDS_EQUATION: "the model equation, to replicate the score independently",
}


# ====================================================================== charts

CHART_ROC = "roc"
CHART_KS = "ks"
CHART_CAP = "cap"
CHART_LIFT = "lift"
CHART_GAINS = "gains"
CHART_BAND_RATE = "band_rate"
CHART_CALIBRATION = "calibration"
CHART_TREND = "trend"
CHART_PSI_TREND = "psi_trend"
CHART_HEATMAP = "heatmap"
CHART_DISTRIBUTION = "distribution"
CHART_WOE = "woe"
CHART_RANKING = "ranking"
CHART_TORNADO = "tornado"
CHART_MATRIX = "matrix"
CHART_WATERFALL = "waterfall"
CHART_NONE = ""


# ======================================================== the test definition


@dataclass(frozen=True)
class Test:
    """One validation test, as a definition rather than as an implementation."""

    test_id: str
    name: str
    category: str
    #: What a validator is asking when they run it, in one sentence.
    purpose: str
    #: The method, named precisely enough that a reader can reproduce it.
    method: str
    requires: tuple[str, ...] = ()
    #: Other names the same test goes by, so a typed request finds it.
    aliases: tuple[str, ...] = ()
    minimum_observations: int = 0
    minimum_events: int = 0
    #: Whether the test compares a period against a reference period.
    comparative: bool = False
    #: Whether it can be cut by segment.
    segmentable: bool = True
    charts: tuple[str, ...] = ()
    #: What the result cannot be taken to mean. Carried on the definition so
    #: it reaches the report without anybody having to remember it.
    limitations: tuple[str, ...] = ()
    #: The CBUAE MMS/MMG articles this speaks to. A mapping, not a claim of
    #: compliance — see `docs/CBUAE_SCORECARD_VALIDATION_REPORT_MAPPING.md`.
    cbuae: tuple[str, ...] = ()
    version: str = "1.0.0"

    def applicable_to(self, capabilities: set[str]) -> bool:
        return set(self.requires).issubset(capabilities)

    def missing_for(self, capabilities: set[str]) -> list[str]:
        return [REQUIREMENT_MEANING[r] for r in self.requires
                if r not in capabilities]

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id, "name": self.name,
            "category": self.category,
            "category_title": BY_CATEGORY_KEY[self.category].title,
            "purpose": self.purpose, "method": self.method,
            "requires": list(self.requires), "aliases": list(self.aliases),
            "minimum_observations": self.minimum_observations,
            "minimum_events": self.minimum_events,
            "comparative": self.comparative, "segmentable": self.segmentable,
            "charts": list(self.charts),
            "limitations": list(self.limitations),
            "cbuae": list(self.cbuae), "version": self.version,
        }


def _t(test_id: str, name: str, category: str, purpose: str, method: str,
       **kw: Any) -> Test:
    return Test(test_id=test_id, name=name, category=category,
                purpose=purpose, method=method, **kw)


#: The floors `metrics.py` already enforces, restated here so a definition
#: can be read without opening the kernel. They are not independent numbers:
#: a test that declares a lower floor than the kernel enforces would produce
#: an INSUFFICIENT_SAMPLE the registry said should have been a result, and a
#: test asserts the two agree.
MIN_OBS = 500
MIN_EVENTS = 30


TESTS: tuple[Test, ...] = (
    # ------------------------------------------------ data & representativeness
    _t("DATA-ROWS", "Population and row counts", DATA_QUALITY,
       "How many rows the period carries, and how many survive each filter.",
       "Row counts before and after each declared filter, as a waterfall.",
       charts=(CHART_WATERFALL,), cbuae=("MMS 10.4", "MMG 2.11")),
    _t("DATA-MATURITY", "Matured and immature population", DATA_QUALITY,
       "How much of the period has a realised outcome, and when the rest "
       "will.",
       "Count by `is_matured`, with the window close month for the "
       "immature part.",
       charts=(CHART_DISTRIBUTION,),
       limitations=("An immature cohort is not a cohort with no defaults. "
                    "No outcome-based test may run on it.",),
       cbuae=("MMS 10.4",)),
    _t("DATA-MISSING", "Missingness by variable", DATA_QUALITY,
       "Which characteristics are not being supplied, and how that has "
       "changed.",
       "Null and special-bin rate per variable, per period.",
       charts=(CHART_HEATMAP,), cbuae=("MMS 10.4", "MMG 2.11")),
    _t("DATA-DUPLICATES", "Duplicate keys", DATA_QUALITY,
       "Whether the declared grain holds.",
       "Count of rows sharing a primary key.",
       cbuae=("MMS 10.4",)),
    _t("DATA-EVENTS", "Event count and class balance", DATA_QUALITY,
       "Whether there are enough defaults to measure anything.",
       "Event count and rate over the matured population.",
       requires=(NEEDS_OUTCOME,), charts=(CHART_TREND,),
       cbuae=("MMS 10.4",)),
    _t("DATA-REPRESENTATIVE", "Development versus current population",
       DATA_QUALITY,
       "Whether the book being scored still resembles the book the model "
       "was fitted on.",
       "Distribution comparison across segmentation variables, development "
       "against the selected period.",
       requires=(NEEDS_REFERENCE,), comparative=True,
       charts=(CHART_DISTRIBUTION,), cbuae=("MMS 10.4", "MMG 2.11")),
    _t("DATA-COVERAGE", "Period and segment coverage", DATA_QUALITY,
       "Which periods and segments have enough data to be assessed.",
       "Observation and event counts by period and by segment.",
       charts=(CHART_HEATMAP,), cbuae=("MMS 10.4",)),

    # ------------------------------------------------------ conceptual soundness
    _t("CONC-PURPOSE", "Intended use and portfolio scope", CONCEPTUAL,
       "Whether the model is being used for what it was built for.",
       "Structured review against the model registry entry. Qualitative.",
       segmentable=False, cbuae=("MMS 10.3", "MMG 2.8", "MMG 2.9")),
    _t("CONC-DEFAULT", "Default definition", CONCEPTUAL,
       "Whether the outcome being predicted is the outcome being measured.",
       "Structured review of the recorded default definition against the "
       "outcome field. Qualitative.",
       segmentable=False, cbuae=("MMS 10.3", "MMG 2.8")),
    _t("CONC-WINDOWS", "Observation and performance windows", CONCEPTUAL,
       "Whether the windows are internally consistent and long enough.",
       "Structured review of the declared windows against the data. "
       "Qualitative with a quantitative check on the horizon.",
       segmentable=False, cbuae=("MMS 10.3", "MMG 2.8")),
    _t("CONC-DIRECTION", "Score direction and scale", CONCEPTUAL,
       "Whether the sign convention is declared rather than inferred.",
       "Registry check: `score_direction` must be explicit. A model without "
       "one cannot be validated, because no metric knows which way is good.",
       segmentable=False, cbuae=("MMS 10.3", "MMG 2.8")),
    _t("CONC-DOCUMENTATION", "Development and validation documentation",
       CONCEPTUAL,
       "Whether the evidence a validator needs exists.",
       "Evidence checklist. Anything absent is recorded NOT RECORDED rather "
       "than assumed.",
       segmentable=False, cbuae=("MMS 4.9", "MMS 10.3", "MMG 2.8")),

    # ------------------------------------------------------------ discrimination
    _t("DISC-AUC", "Area under the ROC curve", DISCRIMINATION,
       "Whether the score separates defaults from non-defaults.",
       "Mann-Whitney AUC with midrank tie handling, on the matured "
       "population, respecting the declared score direction.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE),
       aliases=("auc", "roc", "area under the curve", "c-statistic"),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_ROC,),
       limitations=("AUC is invariant to calibration. A model can rank "
                    "perfectly and predict the wrong probabilities.",),
       cbuae=("MMS 10.4", "MMG 2.11")),
    _t("DISC-GINI", "Gini coefficient", DISCRIMINATION,
       "The same separation, on the scale most credit teams quote.",
       "2 x AUC - 1, from the same midrank AUC.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE),
       aliases=("gini", "accuracy ratio", "ar"),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_CAP,), cbuae=("MMS 10.4", "MMG 2.11")),
    _t("DISC-KS", "Kolmogorov-Smirnov statistic", DISCRIMINATION,
       "The largest separation between the good and bad score distributions.",
       "Maximum absolute difference between the cumulative good and bad "
       "distributions, evaluated only at distinct score values — never at a "
       "position inside a tie, where the difference is an artefact of row "
       "order rather than of the score.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), aliases=("ks", "k-s"),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_KS,), cbuae=("MMS 10.4", "MMG 2.11")),
    _t("DISC-RANK", "Rank ordering by score band", DISCRIMINATION,
       "Whether the observed default rate falls monotonically as the score "
       "rises.",
       "Observed default rate by score band, with counts and confidence "
       "intervals.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE),
       aliases=("rank ordering", "monotonicity", "bad rate by band"),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_BAND_RATE,),
       limitations=("A monotonic portfolio can contain a segment that is "
                    "not. Run it by segment before concluding.",),
       cbuae=("MMS 10.4", "MMG 2.11")),
    _t("DISC-LIFT", "Lift and cumulative gains", DISCRIMINATION,
       "How much of the bad book the model finds in the worst deciles.",
       "Cumulative event capture and lift by score decile.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), aliases=("lift", "gains"),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_LIFT, CHART_GAINS), cbuae=("MMS 10.4",)),
    _t("DISC-TREND", "Discrimination through time", DISCRIMINATION,
       "Whether the model's separation is holding up.",
       "AUC and KS per matured cohort, with the sample and event count "
       "behind each point.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), charts=(CHART_TREND,),
       limitations=("A single cohort carries enough sampling error that one "
                    "low month is not a trend.",),
       cbuae=("MMS 9.4", "MMS 10.4", "MMG 2.11")),

    # -------------------------------------------------------------- calibration
    _t("CAL-OE", "Observed over expected", CALIBRATION,
       "Whether the predicted default rate matches the realised one.",
       "Mean observed default rate divided by mean predicted PD, over the "
       "matured population.",
       requires=(NEEDS_OUTCOME, NEEDS_PD), aliases=("o/e", "oe", "observed "
                                                    "over expected"),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_CALIBRATION,),
       limitations=("A portfolio O/E inside its limit can conceal segments "
                    "wrong in opposite directions.",),
       cbuae=("MMS 10.4", "MMG 2.11", "MMG 3.9")),
    _t("CAL-BAND", "Calibration by score band", CALIBRATION,
       "Where in the score range the prediction is wrong.",
       "Observed against predicted rate per band, with binomial confidence "
       "intervals.",
       requires=(NEEDS_OUTCOME, NEEDS_PD),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_CALIBRATION, CHART_BAND_RATE),
       cbuae=("MMS 10.4", "MMG 3.9")),
    _t("CAL-BRIER", "Brier score", CALIBRATION,
       "Overall accuracy of the predicted probabilities.",
       "Mean squared difference between the predicted PD and the realised "
       "0/1 outcome.",
       requires=(NEEDS_OUTCOME, NEEDS_PD), aliases=("brier",),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       cbuae=("MMS 10.4",)),
    _t("CAL-SLOPE", "Calibration slope and intercept", CALIBRATION,
       "Whether the prediction is wrong by a constant or by a factor.",
       "Logistic regression of the outcome on the predicted log-odds. A "
       "slope near 1 with a non-zero intercept is a recalibration; a slope "
       "far from 1 is not.",
       requires=(NEEDS_OUTCOME, NEEDS_PD),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_CALIBRATION,), cbuae=("MMS 10.4", "MMG 3.9")),
    _t("CAL-DRIFT", "Calibration through time", CALIBRATION,
       "Whether the prediction is drifting away from the outcome.",
       "O/E per matured cohort.",
       requires=(NEEDS_OUTCOME, NEEDS_PD), charts=(CHART_TREND,),
       cbuae=("MMS 9.4", "MMG 2.11")),

    # ---------------------------------------------------------------- stability
    _t("STAB-PSI", "Score population stability index", STABILITY,
       "Whether the score distribution has moved away from the reference.",
       "PSI over score bands taken from the reference population — never "
       "recut per period, which compares a distribution to itself.",
       requires=(NEEDS_SCORE, NEEDS_REFERENCE), comparative=True,
       aliases=("psi", "population stability", "score psi"),
       charts=(CHART_PSI_TREND, CHART_DISTRIBUTION),
       limitations=("PSI has no regulatory threshold. The conventional 0.10 "
                    "and 0.25 cut-offs are scorecard practice, and whatever "
                    "limit is applied here comes from the validation policy.",
                    "A population shift is not a performance deterioration. "
                    "It says the book changed, not that the model failed."),
       cbuae=("MMS 9.4", "MMS 10.4", "MMG 2.11")),
    _t("STAB-CSI", "Characteristic stability index", STABILITY,
       "Which variable is causing the instability.",
       "CSI per variable over its approved bins — the bins the model uses, "
       "not fresh cuts of the raw value, which answer a different question.",
       requires=(NEEDS_BINS, NEEDS_REFERENCE), comparative=True,
       aliases=("csi", "variable psi", "characteristic stability"),
       charts=(CHART_HEATMAP, CHART_RANKING),
       cbuae=("MMS 9.4", "MMS 10.4", "MMG 2.11")),
    _t("STAB-BAND", "Risk band distribution stability", STABILITY,
       "Whether the shape of the grade distribution has changed.",
       "Share of the population in each risk band, period against reference.",
       requires=(NEEDS_SCORE, NEEDS_REFERENCE), comparative=True,
       charts=(CHART_DISTRIBUTION,), cbuae=("MMS 9.4", "MMG 2.11")),
    _t("STAB-ROLLING", "Rolling discrimination and calibration", STABILITY,
       "Whether performance is trending rather than merely varying.",
       "AUC and O/E over a rolling window of matured cohorts.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), charts=(CHART_TREND,),
       cbuae=("MMS 9.4", "MMG 2.11")),

    # ------------------------------------------------------- variables & binning
    _t("VAR-IV", "Information value", VARIABLES,
       "How much signal each characteristic carries.",
       "Information value over the approved bins.",
       requires=(NEEDS_BINS,), aliases=("iv", "information value"),
       charts=(CHART_RANKING,), cbuae=("MMS 10.4", "MMG 2.11")),
    _t("VAR-GINI", "Univariate discrimination", VARIABLES,
       "Which variables still separate risk on their own.",
       "Univariate Gini on the weight of evidence — what the model reads — "
       "rather than on the raw value, which understates a U-shaped variable.",
       requires=(NEEDS_OUTCOME, NEEDS_BINS),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_RANKING, CHART_TREND), cbuae=("MMS 10.4", "MMG 2.11")),
    _t("VAR-WOE", "Weight of evidence and bin monotonicity", VARIABLES,
       "Whether each variable's bins still run in the direction credit sense "
       "expects.",
       "WoE and observed bad rate per bin, checked against the declared risk "
       "direction.",
       requires=(NEEDS_BINS,), charts=(CHART_WOE,),
       limitations=("A non-monotonic bin is not automatically wrong. Some "
                    "characteristics genuinely are U-shaped.",),
       cbuae=("MMS 10.4", "MMG 2.11")),
    _t("VAR-OCCUPANCY", "Bin occupancy and sparse bins", VARIABLES,
       "Whether any approved bin has emptied out.",
       "Population share and event count per bin.",
       requires=(NEEDS_BINS,), charts=(CHART_DISTRIBUTION,),
       cbuae=("MMS 10.4",)),
    _t("VAR-SIGN", "Coefficient and points sign", VARIABLES,
       "Whether any variable is scored against its credit sense.",
       "Fitted coefficient sign against the declared risk direction. A "
       "disagreement is a finding, not a rounding difference.",
       requires=(NEEDS_EQUATION,), cbuae=("MMS 10.4", "MMG 2.11")),

    # ------------------------------------------------------ usage and overrides
    _t("USE-OVERRIDE-RATE", "Override rate", USAGE,
       "How often the recorded decision departs from the score.",
       "Override count over decisions, by score band and by period.",
       requires=(NEEDS_DECISIONS,), charts=(CHART_TREND, CHART_BAND_RATE),
       limitations=("A high override rate is not automatically wrong. What "
                    "matters is direction, concentration, and how the "
                    "overridden cases performed.",),
       cbuae=("MMS 10.4", "MMG 2.10")),
    _t("USE-OVERRIDE-OUTCOME", "Performance of overridden decisions", USAGE,
       "Whether the departures were justified by what happened.",
       "Realised default rate of overridden approvals against comparable "
       "non-overridden approvals.",
       requires=(NEEDS_DECISIONS, NEEDS_OUTCOME),
       minimum_events=MIN_EVENTS, charts=(CHART_BAND_RATE,),
       cbuae=("MMG 2.10",)),
    _t("USE-MATRIX", "Override direction and reason", USAGE,
       "Where the overrides cluster and what reason is recorded.",
       "Cross-tabulation of score band against override direction and reason "
       "code.",
       requires=(NEEDS_DECISIONS,), charts=(CHART_MATRIX,),
       cbuae=("MMG 2.10",)),
    _t("USE-CUTOFF", "Cut-off and approval profile", USAGE,
       "What the approval rate and the bad rate among approvals would be at "
       "a different cut-off.",
       "Confusion matrix, approval rate, bad rate among approvals and event "
       "capture, recomputed at the selected cut-off. Exploratory: this never "
       "changes the production policy cut-off.",
       requires=(NEEDS_DECISIONS, NEEDS_OUTCOME, NEEDS_SCORE),
       charts=(CHART_MATRIX, CHART_TREND),
       limitations=("Moving the slider explores; it does not change any "
                    "production cut-off.",),
       cbuae=("MMG 2.9",)),

    # --------------------------------------------------------- implementation
    _t("IMPL-REPLICATE", "Independent score replication", IMPLEMENTATION,
       "Whether the production score is the score the specification "
       "describes.",
       "Recompute the score from the approved bins and coefficients and "
       "compare row by row. Every mismatch is reported with the first "
       "divergent step.",
       requires=(NEEDS_EQUATION, NEEDS_BINS, NEEDS_SCORE),
       charts=(CHART_DISTRIBUTION,),
       cbuae=("MMS 10.4", "MMG 2.11")),
    _t("IMPL-VERSION", "Model version consistency", IMPLEMENTATION,
       "Whether the version that scored the book is the version that was "
       "approved.",
       "Registry version against the version recorded on the scored rows.",
       segmentable=False, cbuae=("MMS 10.4",)),

    # ------------------------------------------------------------ segmentation
    _t("SEG-DISCRIMINATION", "Discrimination by segment", SEGMENTATION,
       "Whether the model ranks risk inside each segment, not only overall.",
       "AUC and Gini computed within each segment, with its own sample and "
       "event count.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), charts=(CHART_RANKING,),
       cbuae=("MMS 10.4", "MMG 2.11")),
    _t("SEG-CALIBRATION", "Calibration by segment", SEGMENTATION,
       "Whether the prediction is right inside each segment.",
       "O/E within each segment. The test that finds an aggregate concealing "
       "opposite errors either side of a split.",
       requires=(NEEDS_OUTCOME, NEEDS_PD), charts=(CHART_RANKING,),
       cbuae=("MMS 10.4", "MMG 3.9")),
    _t("SEG-RANK", "Rank ordering by segment", SEGMENTATION,
       "Whether any segment's bands invert.",
       "Observed default rate by score band, within segment.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), charts=(CHART_BAND_RATE,),
       cbuae=("MMS 10.4",)),

    # ---------------------------------------------------- champion vs challenger
    _t("CC-DISCRIMINATION", "Discrimination comparison", CHAMPION_CHALLENGER,
       "Whether the challenger separates risk better.",
       "AUC, Gini and KS for both models on the identical population, with "
       "the difference and its confidence interval.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE, NEEDS_CHALLENGER),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_ROC, CHART_KS),
       limitations=("A higher AUC is not on its own a reason to replace a "
                    "champion. Calibration, stability, implementation risk "
                    "and explainability are part of the same decision.",),
       cbuae=("MMS 10.4", "MMG 2.11")),
    _t("CC-CALIBRATION", "Calibration comparison", CHAMPION_CHALLENGER,
       "Whether the challenger's probabilities are better as well as its "
       "ordering.",
       "O/E and Brier for both models on the identical population.",
       requires=(NEEDS_OUTCOME, NEEDS_PD, NEEDS_CHALLENGER),
       charts=(CHART_CALIBRATION,), cbuae=("MMS 10.4", "MMG 3.9")),
    _t("CC-STABILITY", "Stability comparison", CHAMPION_CHALLENGER,
       "Whether the challenger's advantage is stable.",
       "Score PSI and variable CSI for both models against the same "
       "reference.",
       requires=(NEEDS_SCORE, NEEDS_REFERENCE, NEEDS_CHALLENGER),
       comparative=True, charts=(CHART_PSI_TREND,),
       limitations=("Stability can be measured on immature cohorts; "
                    "discrimination cannot. A challenger that looks unstable "
                    "recently may have no outcome data to confirm it yet.",),
       cbuae=("MMS 9.4", "MMG 2.11")),
    _t("CC-SWAPSET", "Swap set analysis", CHAMPION_CHALLENGER,
       "Who would be approved or declined differently, and how they "
       "performed.",
       "Population reclassified between the two models at the same approval "
       "rate, with the realised outcome of each swap set.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE, NEEDS_CHALLENGER,
                 NEEDS_DECISIONS),
       minimum_events=MIN_EVENTS, charts=(CHART_MATRIX,),
       cbuae=("MMS 10.4", "MMG 2.9")),

    # ------------------------------------------------------------- robustness
    _t("ROB-BOOTSTRAP", "Bootstrap confidence interval", ROBUSTNESS,
       "How much of the measured result is sampling noise.",
       "Percentile confidence interval for the headline metric from "
       "resampling with replacement, at a declared resample count and seed.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE),
       minimum_observations=MIN_OBS, minimum_events=MIN_EVENTS,
       charts=(CHART_DISTRIBUTION,), cbuae=("MMS 10.4",)),
    _t("ROB-SEGMENT-EXCLUSION", "Sensitivity to segment exclusion", ROBUSTNESS,
       "Whether one segment is carrying the result.",
       "Headline metric recomputed with each segment excluded in turn.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), charts=(CHART_TORNADO,),
       cbuae=("MMS 10.4",)),
    _t("ROB-WINDOW", "Sensitivity to the observation window", ROBUSTNESS,
       "Whether the result depends on where the window was drawn.",
       "Headline metric recomputed over alternative contiguous windows of "
       "matured cohorts.",
       requires=(NEEDS_OUTCOME, NEEDS_SCORE), charts=(CHART_TORNADO,),
       cbuae=("MMS 10.4",)),
)


BY_ID: dict[str, Test] = {t.test_id: t for t in TESTS}


def all_tests() -> tuple[Test, ...]:
    return TESTS


def get(test_id: str) -> Test:
    try:
        return BY_ID[test_id]
    except KeyError:
        raise KeyError(
            f"{test_id!r} is not a registered validation test. "
            f"{len(TESTS)} are defined.") from None


def in_category(category: str) -> tuple[Test, ...]:
    if category not in BY_CATEGORY_KEY:
        raise KeyError(
            f"{category!r} is not a validation category. It is one of: "
            f"{', '.join(CATEGORIES)}.")
    return tuple(t for t in TESTS if t.category == category)


def resolve(wanted: str) -> Test | None:
    """Find a test by id, name or alias. Case and spacing insensitive.

    Exists so that a typed request — "run KS and AUC" — reaches the same
    definitions the category cards do, rather than a second lookup table
    that drifts from this one.
    """
    key = " ".join(str(wanted or "").lower().split())
    if not key:
        return None
    for made in TESTS:
        if key == made.test_id.lower() or key == made.name.lower():
            return made
        if key in {a.lower() for a in made.aliases}:
            return made
    return None


def applicable(capabilities: set[str],
               category: str = "") -> tuple[Test, ...]:
    """Every test this model can actually support."""
    pool = in_category(category) if category else TESTS
    return tuple(t for t in pool if t.applicable_to(capabilities))


def inapplicable(capabilities: set[str],
                 category: str = "") -> tuple[tuple[Test, list[str]], ...]:
    """Every test this model cannot support, and what it is missing.

    Returned rather than silently dropped: a validation report has to state
    its own scope, and "not applicable because there is no score-to-PD
    mapping" is part of the scope.
    """
    pool = in_category(category) if category else TESTS
    return tuple((t, t.missing_for(capabilities)) for t in pool
                 if not t.applicable_to(capabilities))


def coverage(ran: set[str]) -> dict[str, Any]:
    """Which categories have been exercised and which have not.

    What §29.1 needs to decide whether a set of results can be called a full
    independent validation or only a targeted memorandum.
    """
    out: dict[str, Any] = {}
    for category in CATEGORIES:
        tests = in_category(category)
        done = [t.test_id for t in tests if t.test_id in ran]
        out[category] = {
            "title": BY_CATEGORY_KEY[category].title,
            "defined": len(tests),
            "run": len(done),
            "complete": len(done) > 0,
            "test_ids": [t.test_id for t in tests],
            "run_ids": done,
        }
    return out


def summary() -> dict[str, Any]:
    return {
        "registry_version": REGISTRY_VERSION,
        "categories": [c.to_dict() for c in CATEGORY_DEFINITIONS],
        "tests": len(TESTS),
        "tests_by_category": {c: len(in_category(c)) for c in CATEGORIES},
        "requirements": {r: REQUIREMENT_MEANING[r] for r in REQUIREMENTS},
        "thresholds_are_policy": (
            "No limit in this registry is a regulatory requirement. Each "
            "model's limits are governed, versioned and carry their source; "
            "the conventional cut-offs quoted in the limitations are "
            "scorecard practice."),
    }


__all__ = [
    "BY_CATEGORY_KEY", "BY_ID", "CALIBRATION", "CATEGORIES",
    "CATEGORY_DEFINITIONS", "CHAMPION_CHALLENGER", "CONCEPTUAL",
    "DATA_QUALITY", "DISCRIMINATION", "IMPLEMENTATION", "MIN_EVENTS",
    "MIN_OBS", "NEEDS_BINS", "NEEDS_CHALLENGER", "NEEDS_DECISIONS",
    "NEEDS_EQUATION", "NEEDS_OUTCOME", "NEEDS_PD", "NEEDS_REFERENCE",
    "NEEDS_SCORE", "REGISTRY_VERSION", "REQUIREMENTS", "REQUIREMENT_MEANING",
    "ROBUSTNESS", "SEGMENTATION", "STABILITY", "TESTS", "USAGE", "VARIABLES",
    "Category", "Test", "all_tests", "applicable", "coverage", "get",
    "in_category", "inapplicable", "resolve", "summary",
]
