"""
Scorecard teaching blueprints. §A2-§A6.

Twenty-three families, five hundred cases, and the same honesty as the
canonical corpus: the *specification* of each family was written and reviewed
once, the *subject* comes from the governed scorecard vocabulary — real
variables, real months, real model kinds, real metric names read from
`backend.scorecard` — and the *phrasing* is generated. Writing five hundred
sentences by hand would produce five hundred variations on one person's
phrasing and one specification copied five hundred times.

Why the families are cut this finely
--------------------------------------
Nine of the twenty-three are about metrics that get merged in conversation:
stability, PSI and CSI; discrimination and calibration; a variable's Gini and
the model's Gini. Merging them in the corpus would make it impossible to tell
whether a model had learned the difference, because every case that tested one
would accept an answer about the other. The families are separate so the
scores are separable.

What no case carries
----------------------
A figure. Not one. §5's rule holds here for the same reason it holds in the
general corpus: an AUC stored as teaching truth is correct for one month and
wrong for every month after it. Cases teach which metric, on which population,
under which maturity rule, with which refusal — and the arithmetic is the
engine's.

The traps
-----------
Every blueprint records what its question is usually got wrong. For this
module those are unusually concrete, because retail validation has a small set
of errors that recur:

* computing an outcome metric on a cohort whose performance window is open;
* reading a variable's standalone Gini as the model's;
* reporting a PSI when the question was about one variable's bins;
* recomputing Weight of Evidence on the validation month;
* treating a seeded PSI cut-off as a regulatory requirement;
* calling a candidate model activated because it was scored.

Each of those is a forbidden behaviour on the family it belongs to.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.scorecard import build as build_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod
from backend.teaching import families as fam
from backend.teaching import schema as sc
from intelligence_factory.teaching import canonical as cn
from intelligence_factory.teaching import migrate as mg

SCORECARD_VERSION = "1.0.0"

# ------------------------------------------------------------- vocabulary
# Read from the module rather than restated, so a variable renamed in the
# dictionary renames itself here and a case cannot drift onto a field that
# no longer exists.

APP = build_mod.APP
BEH = build_mod.BEH
TYPES: tuple[str, ...] = (APP, BEH)
TYPE_WORD: dict[str, str] = {APP: "application", BEH: "behavioural"}
MODELS: tuple[str, ...] = ("INCUMBENT", "CHALLENGER", "RECALIBRATED")

#: Months whose twelve-month window has closed, and months where it has not.
#: Both lists are non-empty by construction of the universe, and a test
#: asserts it: a corpus with no immature month cannot teach §7.
MATURED: tuple[str, ...] = tuple(
    m for m in synth.APPLICATION_MONTHS if synth.matured(m))
OPEN_WINDOW: tuple[str, ...] = tuple(
    m for m in synth.APPLICATION_MONTHS if not synth.matured(m))

APP_VARIABLES: tuple[str, ...] = tuple(
    build_mod.MODEL_VARIABLES[APP]["INCUMBENT"])
BEH_VARIABLES: tuple[str, ...] = tuple(
    build_mod.MODEL_VARIABLES[BEH]["INCUMBENT"])

#: Variables the dictionary holds for fairness monitoring and no model may
#: score on. Named from the dictionary so the corpus cannot disagree with the
#: control it is teaching.
SENSITIVE: dict[str, tuple[str, ...]] = {
    kind: tuple(vars_mod.sensitive(kind)) for kind in TYPES}

DATASETS: dict[str, str] = {
    kind: build_mod.dataset_name(kind, "monthly_validation") for kind in TYPES}
DEVELOPMENT_DATASETS: dict[str, str] = {
    kind: build_mod.dataset_name(kind, "development_reference")
    for kind in TYPES}

#: Metric names as the engine reports them, paired with how a validator says
#: them out loud. The right-hand side is what gets into questions; the
#: left-hand side is what a case expects the planner to resolve to.
DISCRIMINATION_METRICS: tuple[tuple[str, str], ...] = (
    ("auc", "AUC"), ("gini", "Gini"), ("ks", "KS"),
    ("gini", "the accuracy ratio"), ("auc", "the area under the ROC curve"),
    ("ks", "the Kolmogorov-Smirnov statistic"),
)
CALIBRATION_METRICS: tuple[tuple[str, str], ...] = (
    ("observed_default_rate", "the observed default rate"),
    ("average_predicted_pd", "average predicted PD"),
    ("brier_score", "the Brier score"), ("log_loss", "log loss"),
    ("calibration_slope", "the calibration slope"),
    ("calibration_in_the_large", "calibration in the large"),
    ("bucket_rmse", "bucket RMSE"), ("mape", "MAPE"),
)


def pick(items: tuple[Any, ...], seed: str, offset: int = 0) -> Any:
    """A deterministic choice, on this module's own hash namespace.

    Namespaced so adding a scorecard blueprint cannot reshuffle the canonical
    corpus, which would make two runs' scores incomparable for reasons that
    have nothing to do with either corpus.
    """
    digest = hashlib.sha256(f"scorecard:{seed}:{offset}".encode()).digest()
    return items[int.from_bytes(digest[:4], "big") % len(items)]


def article(spoken: str) -> str:
    """`the <metric>`, without doubling an article the name already has.

    Half the metric names read naturally with "the" in front — "the Brier
    score" — and half already carry it — "the accuracy ratio". Composing an
    opener with either produced "the the accuracy ratio".
    """
    return spoken if spoken.startswith("the ") else f"the {spoken}"


def _pair(seed: str) -> tuple[str, str, str]:
    """A scorecard type, its adjective, and one of its models."""
    kind = pick(TYPES, seed, 1)
    return kind, TYPE_WORD[kind], pick(MODELS, seed, 2)


def _variables_of(kind: str) -> tuple[str, ...]:
    return APP_VARIABLES if kind == APP else BEH_VARIABLES


def _month(seed: str, *, matured: bool = True) -> str:
    return pick(MATURED if matured else OPEN_WINDOW, seed, 3)


def _label(variable: str) -> str:
    """The dictionary's own label, so a question reads like a person."""
    for kind in TYPES:
        for entry in vars_mod.catalogue(kind):
            if entry.name == variable:
                return entry.label
    return variable.replace("_", " ")


#: Question openers, in the registers §A3 asks for. The typo and the
#: abbreviation forms are not decoration: a validator types "disc" and
#: "PSI vs dev" into a box, and a corpus that only contains careful prose
#: teaches a model to need careful prose.
FORMAL: tuple[str, ...] = (
    "Please report", "Could you provide", "I would like to see",
    "Report", "Show me")
INFORMAL: tuple[str, ...] = (
    "what's", "whats", "gimme", "how's", "can I see")
TYPOS: dict[str, str] = {
    "discrimination": "discrimintaion", "calibration": "calibraton",
    "stability": "stabilty", "validation": "validaton",
    "behavioural": "behavioual", "scorecard": "scorcard",
}
ABBREVIATIONS: dict[str, str] = {
    "observed default rate": "ODR", "probability of default": "PD",
    "Population Stability Index": "PSI",
    "Characteristic Stability Index": "CSI",
    "Information Value": "IV", "Weight of Evidence": "WoE",
    "days past due": "DPD", "application scorecard": "app scorecard",
    "behavioural scorecard": "beh scorecard",
}


def build(*, family: str, title: str, turns: list[cn.Turn],
          objectives: tuple[str, ...], difficulty: str = sc.INTERMEDIATE,
          risk: str = "MEDIUM", capability: str = "ANALYSIS",
          outcome: str = fam.EXECUTE, officer: int = 2,
          **fields: Any) -> sc.TeachingCase:
    """One scorecard case. Retail scope is not optional here.

    Every case in this module declares RETAIL, because the whole module is
    about a retail model and a case that left the scope open would be a case
    the corporate side could match against.
    """
    case = cn.build(family=family, title=title, turns=turns,
                    objectives=objectives, difficulty=difficulty, risk=risk,
                    capability=capability, outcome=outcome, officer=officer,
                    **fields)
    case.portfolio_scope = fam.RETAIL
    return case


#: The three refusals that belong to almost every scorecard family, written
#: once. A family adds its own on top rather than restating these.
IMMATURE = ("computing an outcome metric on a cohort whose twelve-month "
            "performance window has not closed")
INVENTED_LIMIT = ("presenting a seeded demonstration limit as a regulatory "
                  "requirement")
UNGROUNDED = "quoting a figure that no computed result contains"


# ---------------------------------------------------------------------------
# Data, metadata and the model specification
# ---------------------------------------------------------------------------


def _data_discovery(seed: str) -> sc.TeachingCase:
    """What scorecard data exists, answered from metadata."""
    kind, word, _ = _pair(seed)
    # Each subject carries two phrasings: a noun phrase an imperative opener
    # can take, and a question a bare interrogative can stand on its own.
    # Composing one opener with one clause produced "Could you provide how
    # many months of validation data", which is not a sentence anybody types.
    subject, phrase, standalone = pick((
        ("months", "the months of validation data held",
         "How many months of validation data do we have"),
        ("models", "the registered models",
         "Which models are registered"),
        ("variables", "the candidate variables in the dictionary",
         "Which variables can this scorecard use"),
        ("population", "the monthly population counts",
         "How many accounts does a month hold"),
        ("development sample", "the development population",
         "What was the development sample"),
        ("binning specification", "the binning specification version in force",
         "Which binning specification is in force"),
        ("default definition", "the governed default definition",
         "What counts as a default"),
        ("datasets", "the datasets this module holds",
         "Which datasets does this module hold"),
    ), seed, 4)
    if pick((True, False), seed, 5):
        question = (f"{pick(FORMAL, seed, 16)} {phrase} for the {word} "
                    "scorecard.")
    else:
        question = f"{standalone} for the {word} scorecard?"
    return build(
        family="SCORECARD_DATA_DISCOVERY",
        title=f"{word} scorecard {subject}",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour="Must answer from the registry and the "
                                 "catalogue. Must not run a validation "
                                 "metric to find out.")],
        objectives=(f"name the governed {word} scorecard {subject}",
                    "state the period range the module covers"),
        difficulty=sc.FOUNDATIONAL, risk="LOW", capability="DATA_DISCOVERY",
        officer=1, required_datasets=[DATASETS[kind]],
        metrics=[], concepts=["retail scorecard", subject],
        analytical_plan_contract={"capability": "DATA_DISCOVERY",
                                  "reads_metadata_only": True,
                                  "scorecard_type": kind},
        result_contract={"shape": "a description of held scorecard data"},
        scope_contract=cn._forbids(
            "computing a validation metric to answer a metadata question",
            "naming a month outside the governed range"))


def _model_equation(seed: str) -> sc.TeachingCase:
    """The registered equation, as the registry holds it."""
    kind, word, model = _pair(seed)
    asks = pick((
        "the full equation", "the coefficients", "the intercept and terms",
        "the score mapping", "how the score is calculated from the logit",
        "the points to double the odds and the base score",
    ), seed, 4)
    return build(
        family="SCORECARD_MODEL_EQUATION",
        title=f"{model} {word} equation: {asks}",
        turns=[cn.Turn(f"Show me {asks} for the {model.lower()} {word} "
                       "scorecard.",
                       result_type="TABLE",
                       behaviour="Must report the registry's stored equation "
                                 "including the DECLARED score direction. "
                                 "Must not assume that a higher score means "
                                 "lower risk.")],
        objectives=("report the intercept and every term with its coefficient",
                    "state the link function and the score mapping",
                    "state the declared score direction"),
        difficulty=sc.INTERMEDIATE, capability="ANALYSIS",
        required_datasets=[DATASETS[kind]],
        concepts=["model equation", "score mapping", "score direction"],
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "reads_registry": True},
        invariants=["the reported terms match the registered equation exactly"],
        result_contract={"shape": "the equation and its score mapping"},
        scope_contract=cn._forbids(
            "assuming a score direction rather than reading the registered "
            "one",
            "reporting a coefficient rounded to two decimals, which is not "
            "enough to reproduce a score",
            UNGROUNDED))


def _default_definition(seed: str) -> sc.TeachingCase:
    """The governed default definition, in full."""
    kind, word, _ = _pair(seed)
    asks = pick((
        "what counts as a default", "what the default definition is",
        "how many days past due makes an account bad",
        "how long the performance window is",
        "which accounts are excluded",
        "how indeterminate accounts are treated",
    ), seed, 4)
    return build(
        family="SCORECARD_DEFAULT_DEFINITION",
        title=f"{word} default definition: {asks}",
        turns=[cn.Turn(f"For the {word} scorecard, {asks}?",
                       result_type="NARRATIVE",
                       behaviour="Must report the governed definition in "
                                 "full — basis, days past due, window, "
                                 "exclusions and the indeterminate "
                                 "treatment.")],
        objectives=("state the default basis and the days-past-due threshold",
                    "state the performance window in months",
                    "state the exclusions and the indeterminate treatment"),
        difficulty=sc.FOUNDATIONAL, risk="LOW",
        required_datasets=[DATASETS[kind]],
        concepts=["default definition", "performance window"],
        analytical_plan_contract={"scorecard_type": kind,
                                  "reads_registry": True},
        result_contract={"shape": "the governed default definition"},
        scope_contract=cn._forbids(
            "quoting a conventional 90-days-past-due definition instead of "
            "the one this model was developed against",
            "omitting the indeterminate treatment, which changes the "
            "denominator of every rate in the report"))


def _variables(seed: str) -> sc.TeachingCase:
    """A variable in the model against a variable in the dictionary."""
    kind, word, model = _pair(seed)
    sensitive = SENSITIVE[kind]
    asks_sensitive = bool(sensitive) and pick((True, False), seed, 6)
    if asks_sensitive:
        variable = pick(sensitive, seed, 7)
        return build(
            family="SCORECARD_VARIABLES",
            title=f"Is {variable} in the {word} model",
            turns=[cn.Turn(f"Is {_label(variable).lower()} used in the {word} "
                           "scorecard?",
                           result_type="NARRATIVE",
                           behaviour="Must say the field is held for fairness "
                                     "monitoring and is not scoreable, and "
                                     "that an equation referencing it is "
                                     "refused.")],
            objectives=("say whether the variable is in the active equation",
                        "say that the dictionary marks it not scoreable and "
                        "why"),
            difficulty=sc.COMPLEX, risk="HIGH",
            required_datasets=[DATASETS[kind]],
            concepts=["variable dictionary", "fairness monitoring"],
            analytical_plan_contract={"scorecard_type": kind,
                                      "reads_registry": True},
            result_contract={"shape": "a scoreability determination"},
            scope_contract=cn._forbids(
                "reporting a demographic field's predictive power as though "
                "it were a candidate for the model",
                "answering only 'no' without saying that the control is in "
                "the dictionary rather than in somebody's judgement"))

    variable = pick(_variables_of(kind), seed, 7)
    asks = pick((
        "which variables are in the model", "how many variables it uses",
        "what each variable measures", "which variables were considered but "
        "not used",
    ), seed, 8)
    return build(
        family="SCORECARD_VARIABLES",
        title=f"{model} {word} variables: {asks}",
        turns=[cn.Turn(f"For the {model.lower()} {word} scorecard, {asks}?",
                       result_type="TABLE",
                       behaviour="Must separate variables in the active "
                                 "equation from candidates in the "
                                 "dictionary.")],
        objectives=("list the variables in the active equation",
                    "distinguish them from candidates considered and not "
                    "used"),
        difficulty=sc.INTERMEDIATE,
        required_datasets=[DATASETS[kind]],
        concepts=["variable dictionary", _label(variable)],
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "reads_registry": True},
        result_contract={"shape": "the variable list with roles"},
        scope_contract=cn._forbids(
            "listing every dictionary variable as though all were in the "
            "model",
            "omitting the considered-and-rejected variables, which is the "
            "half a validator asks about"))


def _woe_binning(seed: str) -> sc.TeachingCase:
    """The frozen binning specification, never recomputed."""
    kind, word, _ = _pair(seed)
    variable = pick(_variables_of(kind), seed, 7)
    month = _month(seed)
    asks = pick((
        f"the {_label(variable).lower()} bins",
        f"the Weight of Evidence for {_label(variable).lower()}",
        f"the Information Value of {_label(variable).lower()}",
        f"how {_label(variable).lower()} is binned",
        f"whether {_label(variable).lower()} is monotonic in WoE",
    ), seed, 9)
    recompute = pick((True, False), seed, 10)
    question = (f"Recalculate {asks} on {month} for the {word} scorecard."
                if recompute else f"Show me {asks} for the {word} scorecard.")
    return build(
        family="SCORECARD_WOE_BINNING",
        title=f"{word} WoE: {asks}",
        turns=[cn.Turn(question, result_type="TABLE",
                       behaviour=("Must read the approved specification and "
                                  "say that Weight of Evidence is not "
                                  "recomputed from a validation month unless "
                                  "recalibration is what is being analysed."
                                  if recompute else
                                  "Must read the approved specification and "
                                  "name its version."))],
        objectives=(f"report the bins and Weight of Evidence for {variable}",
                    "name the binning specification version they come from"),
        difficulty=sc.COMPLEX if recompute else sc.INTERMEDIATE,
        risk="HIGH" if recompute else "MEDIUM",
        required_datasets=[DEVELOPMENT_DATASETS[kind]],
        metrics=["information_value"],
        concepts=["Weight of Evidence", "binning specification"],
        period_contract={"month": month, "baseline": "DEVELOPMENT"},
        analytical_plan_contract={"scorecard_type": kind,
                                  "reads_binning_spec": True,
                                  "refits_bins": False},
        invariants=["the reported bins come from the approved specification"],
        result_contract={"shape": "the bin table with WoE and IV"},
        scope_contract=cn._forbids(
            "recomputing Weight of Evidence from the validation month, which "
            "makes the model look better every month by construction",
            "reporting an IV strength label as a regulatory classification"))


# ---------------------------------------------------------------------------
# The four metric families that get confused with each other
# ---------------------------------------------------------------------------


def _discrimination(seed: str) -> sc.TeachingCase:
    """Rank ordering, on a matured cohort, in the registered direction."""
    kind, word, model = _pair(seed)
    metric, spoken = pick(DISCRIMINATION_METRICS, seed, 4)
    month = _month(seed)
    register = pick(("formal", "informal", "abbrev", "compound"), seed, 11)
    if register == "formal":
        question = (f"{pick(FORMAL, seed, 12)} {article(spoken)} for the "
                    f"{model.lower()} {word} scorecard on {month}.")
    elif register == "informal":
        question = (f"{pick(INFORMAL, seed, 12)} {article(spoken)} on the "
                    f"{word} card for {month}?")
    elif register == "abbrev":
        question = f"{spoken} {word[:3]} scorecard {month}?"
    else:
        question = (f"Give me {article(spoken)} for {month} and tell me "
                    "whether it has moved since the development sample.")
    objectives = [f"compute {spoken} on the {month} {word} cohort",
                  "state the score direction the metric was computed under"]
    if register == "compound":
        objectives.append("compare it against the development sample")
    return build(
        family="SCORECARD_DISCRIMINATION",
        title=f"{spoken} on {month} ({model} {word})",
        turns=[cn.Turn(question, result_type="KPI",
                       behaviour="Must compute rank ordering on a matured "
                                 "cohort and must not answer a calibration "
                                 "question instead.")],
        objectives=tuple(objectives),
        difficulty=sc.COMPLEX if register == "compound" else sc.INTERMEDIATE,
        required_datasets=[DATASETS[kind]],
        metrics=[metric], concepts=["discrimination", spoken],
        period_contract={"month": month, "maturity": "MATURED"},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "metric": metric,
                                  "requires_matured_outcome": True},
        invariants=["the metric is computed only where the outcome exists",
                    "the score direction is read from the registry"],
        result_contract={"shape": f"{spoken} with its observation count"},
        visualization_contract={"type": "KPI"},
        scope_contract=cn._forbids(
            IMMATURE,
            "answering with a calibration figure — how well ranked and how "
            "well calibrated are different questions",
            "reversing good and bad, which flips the metric about 0.5",
            UNGROUNDED))


def _calibration(seed: str) -> sc.TeachingCase:
    """Predicted against observed, kept apart from rank ordering."""
    kind, word, model = _pair(seed)
    metric, spoken = pick(CALIBRATION_METRICS, seed, 4)
    month = _month(seed)
    shape = pick(("plain", "versus", "band", "guarded"), seed, 11)
    if shape == "versus":
        question = (f"How does predicted PD compare with the {word} "
                    f"scorecard's actual default rate on {month}?")
        objectives = ("compute predicted and observed on the same cohort",
                      "state whether the model over- or under-predicts")
    elif shape == "band":
        question = (f"Show {spoken} by score band for {month} on the {word} "
                    "scorecard.")
        objectives = (f"compute {spoken} within each score band",
                      "report the band population so a thin band is visible")
    elif shape == "guarded":
        question = f"What's the MAPE for {month} on the {word} card?"
        objectives = ("compute MAPE where it is defined",
                      "say which bands were excluded and why")
    else:
        question = (f"{pick(FORMAL, seed, 12)} {article(spoken)} for the "
                    f"{model.lower()} {word} scorecard on {month}.")
        objectives = (f"compute {spoken} on the {month} cohort",
                      "state the maturity of the cohort it was computed on")
    return build(
        family="SCORECARD_CALIBRATION",
        title=f"{spoken} on {month} ({model} {word})",
        turns=[cn.Turn(question, result_type="TABLE" if shape == "band"
                       else "KPI",
                       behaviour="Must compare predicted against observed on "
                                 "a matured cohort. Must not substitute a "
                                 "discrimination statistic.")],
        objectives=objectives,
        difficulty=sc.COMPLEX if shape in ("band", "guarded")
        else sc.INTERMEDIATE,
        required_datasets=[DATASETS[kind]],
        metrics=[metric], concepts=["calibration", spoken],
        period_contract={"month": month, "maturity": "MATURED"},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "metric": metric,
                                  "requires_matured_outcome": True},
        invariants=["predicted and observed are computed on the same rows",
                    "MAPE is not reported for a band whose observed rate is "
                    "at or near zero"],
        result_contract={"shape": f"{spoken} against the observed outcome"},
        scope_contract=cn._forbids(
            IMMATURE,
            "answering with Gini or KS, which say nothing about the LEVEL of "
            "predicted risk",
            "reporting MAPE on a band with almost no defaults, where the "
            "ratio is unbounded and the number is arithmetic rather than a "
            "measurement",
            UNGROUNDED))


def _stability(seed: str) -> sc.TeachingCase:
    """Movement against the development baseline. No outcome needed."""
    kind, word, model = _pair(seed)
    month = _month(seed, matured=pick((True, False), seed, 13))
    asks = pick((
        "how stable is the population",
        "has the population shifted",
        "has the score distribution moved",
        "how does the current month compare with the development sample",
    ), seed, 4)
    return build(
        family="SCORECARD_STABILITY",
        title=f"{word} stability on {month}",
        turns=[cn.Turn(f"For {month}, {asks} on the {word} scorecard?",
                       result_type="TABLE",
                       behaviour="Must answer from stability metrics, which "
                                 "need no outcome and are therefore "
                                 "available even where the performance "
                                 "window is still open.")],
        objectives=("report movement against the development baseline",
                    "name the baseline the comparison is against"),
        difficulty=sc.INTERMEDIATE,
        required_datasets=[DATASETS[kind], DEVELOPMENT_DATASETS[kind]],
        metrics=["score_psi"], concepts=["population stability"],
        period_contract={"month": month, "baseline": "DEVELOPMENT"},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "requires_matured_outcome": False},
        invariants=["stability is measured against the declared baseline"],
        result_contract={"shape": "stability against the baseline"},
        scope_contract=cn._forbids(
            "refusing the question because the month is immature — stability "
            "never needed an outcome",
            "comparing against the previous month when the declared baseline "
            "is the development sample",
            INVENTED_LIMIT))


def _psi(seed: str) -> sc.TeachingCase:
    """PSI: the SCORE distribution, against the declared baseline."""
    kind, word, model = _pair(seed)
    month = _month(seed, matured=pick((True, False), seed, 13))
    shape = pick(("plain", "cutoff", "baseline", "trend"), seed, 11)
    if shape == "cutoff":
        question = (f"Is the score PSI for {month} above the regulatory "
                    f"limit on the {word} scorecard?")
        objectives = ("compute score PSI for the month",
                      "state that the 0.10 and 0.25 cut-offs are a scorecard "
                      "convention and name the source of any limit applied")
    elif shape == "baseline":
        question = (f"What baseline is the {word} scorecard's PSI measured "
                    "against?")
        objectives = ("name the declared baseline",
                      "say what a different baseline would change")
    elif shape == "trend":
        question = f"How has score PSI moved over the last year on {word}?"
        objectives = ("report score PSI by month",
                      "keep the baseline fixed across the series")
    else:
        question = f"PSI for {month} on the {word} card?"
        objectives = ("compute the Population Stability Index on the score "
                      "distribution",
                      "name the baseline and the month")
    return build(
        family="SCORECARD_PSI",
        title=f"Score PSI on {month} ({word})",
        turns=[cn.Turn(question, result_type="KPI" if shape != "trend"
                       else "SERIES",
                       behaviour="Must measure the SCORE distribution "
                                 "against the declared baseline, and must "
                                 "not answer with a per-variable index.")],
        objectives=objectives,
        difficulty=sc.COMPLEX if shape in ("cutoff", "baseline")
        else sc.INTERMEDIATE,
        risk="HIGH" if shape == "cutoff" else "MEDIUM",
        required_datasets=[DATASETS[kind], DEVELOPMENT_DATASETS[kind]],
        metrics=["score_psi"], concepts=["Population Stability Index"],
        period_contract={"month": month, "baseline": "DEVELOPMENT"},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "metric": "score_psi",
                                  "requires_matured_outcome": False},
        invariants=["PSI is computed on the score, not on a variable"],
        result_contract={"shape": "score PSI against the baseline"},
        scope_contract=cn._forbids(
            "reporting a variable's CSI when the question was about score PSI",
            INVENTED_LIMIT,
            "changing the baseline mid-series, which makes a trend that "
            "measures the baseline rather than the population"))


def _csi(seed: str) -> sc.TeachingCase:
    """CSI: ONE variable's bins. Not the score."""
    kind, word, _ = _pair(seed)
    variable = pick(_variables_of(kind), seed, 7)
    month = _month(seed, matured=pick((True, False), seed, 13))
    shape = pick(("plain", "which", "why", "missing"), seed, 11)
    label = _label(variable).lower()
    if shape == "which":
        question = (f"Which variables have shifted most on the {word} "
                    f"scorecard in {month}?")
        objectives = ("compute the characteristic index for each variable",
                      "rank them and name the largest movers")
    elif shape == "why":
        question = f"Why has {label} shifted on {word} in {month}?"
        objectives = (f"report {variable}'s characteristic index",
                      "attribute the index to the bins that contributed most")
    elif shape == "missing":
        question = (f"Has the missing rate for {label} changed on the {word} "
                    f"scorecard?")
        objectives = ("report the missing and unseen bin rates against the "
                      "baseline",
                      "say that a missing-rate move is a data-supply change "
                      "before it is a population change")
    else:
        question = f"CSI for {label} on {word}, {month}."
        objectives = (f"compute the Characteristic Stability Index for "
                      f"{variable}",
                      "name the baseline it is measured against")
    return build(
        family="SCORECARD_CSI",
        title=f"{label} CSI on {month} ({word})",
        turns=[cn.Turn(question, result_type="TABLE",
                       behaviour="Must measure ONE variable's bin "
                                 "distribution. Must not report score PSI "
                                 "instead.")],
        objectives=objectives,
        difficulty=sc.COMPLEX if shape in ("why", "missing")
        else sc.INTERMEDIATE,
        required_datasets=[DATASETS[kind], DEVELOPMENT_DATASETS[kind]],
        metrics=["variable_csi"],
        concepts=["Characteristic Stability Index", label],
        period_contract={"month": month, "baseline": "DEVELOPMENT"},
        population_contract={"scorecard_type": kind},
        analytical_plan_contract={"scorecard_type": kind,
                                  "metric": "variable_csi",
                                  "variable": variable,
                                  "requires_matured_outcome": False},
        invariants=["the index is computed on the variable's approved bins"],
        result_contract={"shape": "the variable's bin shares and its index"},
        scope_contract=cn._forbids(
            "reporting score PSI, which is a different distribution",
            "re-binning the variable on the current month before comparing, "
            "which compares a population against bins drawn from itself",
            INVENTED_LIMIT))


def _variable_diagnostics(seed: str) -> sc.TeachingCase:
    """A variable's standalone power, kept apart from the model's."""
    kind, word, model = _pair(seed)
    variable = pick(_variables_of(kind), seed, 7)
    month = _month(seed)
    label = _label(variable).lower()
    shape = pick(("power", "compare", "confuse", "iv", "contribution"),
                 seed, 11)
    if shape == "compare":
        question = (f"Which variable is doing the most work in the {word} "
                    "scorecard?")
        objectives = ("report each variable's standalone power",
                      "say that standalone power is not the same as "
                      "contribution to the fitted model")
    elif shape == "confuse":
        question = f"What's the Gini of {label} on the {word} card in {month}?"
        objectives = (f"compute {variable}'s standalone Gini",
                      "make explicit that this is the variable's Gini and "
                      "not the model's")
    elif shape == "iv":
        question = f"What is the Information Value of {label}?"
        objectives = (f"report {variable}'s IV under the approved bins",
                      "name the IV strength label as a modelling convention")
    elif shape == "contribution":
        question = (f"How much does {label} contribute to the {word} "
                    "scorecard's discrimination?")
        objectives = ("measure the contribution by removing the variable and "
                      "recomputing",
                      "label the claim strength according to whether an "
                      "ablation was actually run")
    else:
        question = (f"How predictive is {label} on its own for the {word} "
                    f"scorecard in {month}?")
        objectives = (f"compute {variable}'s standalone discrimination",
                      "state the population it was computed on")
    return build(
        family="SCORECARD_VARIABLE_DIAGNOSTICS",
        title=f"{label} diagnostics ({word}, {shape})",
        turns=[cn.Turn(question, result_type="TABLE",
                       behaviour="Must keep a variable's own power separate "
                                 "from the model's, and must not present a "
                                 "correlation as a cause.")],
        objectives=objectives,
        difficulty=sc.COMPLEX if shape in ("contribution", "confuse")
        else sc.INTERMEDIATE,
        risk="HIGH" if shape == "confuse" else "MEDIUM",
        required_datasets=[DATASETS[kind]],
        metrics=["information_value", "gini"],
        concepts=["variable diagnostics", label],
        period_contract={"month": month, "maturity": "MATURED"},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "variable": variable,
                                  "requires_matured_outcome": True},
        invariants=["a variable's metric is labelled as the variable's"],
        result_contract={"shape": "the variable's diagnostics"},
        scope_contract=cn._forbids(
            "reporting the variable's Gini as the model's Gini",
            "claiming a variable caused a change in discrimination when no "
            "ablation was run",
            IMMATURE))


# ---------------------------------------------------------------------------
# Implementation, comparison, segments and the candidate flow
# ---------------------------------------------------------------------------


def _implementation(seed: str) -> sc.TeachingCase:
    """Re-derive the score from the stored specification."""
    kind, word, model = _pair(seed)
    month = _month(seed, matured=pick((True, False), seed, 13))
    stage = pick((
        ("bin assignment", "which bin each account fell into"),
        ("Weight of Evidence", "the WoE values applied"),
        ("the logit", "the logit before the score mapping"),
        ("the PD", "the predicted probability"),
        ("the score", "the final score"),
        ("every stage", "bin, WoE, logit, PD and score"),
    ), seed, 4)
    return build(
        family="SCORECARD_IMPLEMENTATION",
        title=f"Replicate {stage[0]} ({model} {word}, {month})",
        turns=[cn.Turn(f"Can you verify {stage[1]} for the {model.lower()} "
                       f"{word} scorecard on {month}?",
                       result_type="TABLE",
                       behaviour="Must recompute from the stored binning "
                                 "specification and the stored equation, and "
                                 "report the difference rather than assert "
                                 "agreement.")],
        objectives=(f"recompute {stage[0]} independently from the stored "
                    "specification",
                    "report the maximum absolute difference and the mismatch "
                    "count"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[DATASETS[kind], DEVELOPMENT_DATASETS[kind]],
        metrics=["mismatch_rate"], concepts=["implementation replication"],
        period_contract={"month": month},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "recomputes_from_spec": True,
                                  "requires_matured_outcome": False},
        invariants=["the replication uses the registered equation, not a "
                    "refitted one"],
        result_contract={"shape": "stage-by-stage differences"},
        scope_contract=cn._forbids(
            "declaring the implementation correct without recomputing "
            "anything",
            "refitting the model and comparing against the refit, which "
            "tests nothing about production",
            "rounding away a difference that a score band boundary would "
            "have made visible"))


def _model_comparison(seed: str) -> sc.TeachingCase:
    """Models compared on an identical population and period."""
    kind, word, _ = _pair(seed)
    month = _month(seed)
    left = pick(MODELS, seed, 14)
    right = MODELS[(MODELS.index(left) + 1 + (hash(seed) % 2)) % len(MODELS)]
    shape = pick(("which", "delta", "significance", "recalibrate"), seed, 11)
    if shape == "delta":
        question = (f"How much better is the {right.lower()} than the "
                    f"{left.lower()} on the {word} scorecard in {month}?")
        objectives = ("compute both models on the identical population",
                      "report the difference and its direction")
    elif shape == "significance":
        question = (f"Is the {right.lower()} {word} model significantly "
                    f"better than the {left.lower()} in {month}?")
        objectives = ("compute both with their confidence intervals",
                      "say that overlapping intervals mean the difference is "
                      "not established by this sample")
    elif shape == "recalibrate":
        question = (f"Would recalibrating the {word} scorecard help?")
        objectives = ("compare the recalibrated model against the incumbent",
                      "separate a calibration gain from a discrimination gain")
    else:
        question = (f"Which {word} scorecard model is performing best in "
                    f"{month}?")
        objectives = ("rank the registered models on the same population",
                      "name the metric the ranking is on")
    return build(
        family="SCORECARD_MODEL_COMPARISON",
        title=f"{left} against {right} ({word}, {month})",
        turns=[cn.Turn(question, result_type="TABLE",
                       behaviour="Must compare on an identical population "
                                 "and period, and must not read a difference "
                                 "smaller than the interval as real.")],
        objectives=objectives,
        difficulty=sc.COMPLEX, risk="HIGH" if shape == "significance"
        else "MEDIUM",
        required_datasets=[DATASETS[kind]],
        metrics=["gini", "auc", "brier_score"],
        concepts=["model comparison"],
        period_contract={"month": month, "maturity": "MATURED"},
        population_contract={"scorecard_type": kind,
                             "identical_population": True},
        analytical_plan_contract={"scorecard_type": kind,
                                  "models": [left, right],
                                  "requires_matured_outcome": True},
        invariants=["every model is scored on the same rows"],
        result_contract={"shape": "a model comparison table"},
        scope_contract=cn._forbids(
            "comparing models computed on different populations or months",
            "presenting a difference inside the confidence interval as an "
            "established improvement",
            IMMATURE))


def _rescoring(seed: str) -> sc.TeachingCase:
    """A proposed equation is a candidate. Never an activation."""
    kind, word, _ = _pair(seed)
    variable = pick(_variables_of(kind), seed, 7)
    shape = pick(("propose", "activate", "diff", "rescore"), seed, 11)
    label = _label(variable).lower()
    if shape == "activate":
        question = (f"Increase the weight on {label} and make that the live "
                    f"{word} scorecard.")
        objectives = ("validate the proposed equation and produce a candidate "
                      "version",
                      "state that activation is a separate act under a "
                      "narrower permission and has not happened")
        risk, difficulty = "HIGH", sc.ADVERSARIAL
    elif shape == "diff":
        question = (f"What would change if we dropped {label} from the {word} "
                    "scorecard?")
        objectives = ("show the diff against the registered equation",
                      "say that nothing has been activated or rescored in the "
                      "lake")
        risk, difficulty = "MEDIUM", sc.COMPLEX
    elif shape == "rescore":
        question = (f"Rescore the last six months of the {word} scorecard "
                    f"with a heavier weight on {label}.")
        objectives = ("score the candidate in memory over the named months",
                      "compare against the incumbent on the same rows",
                      "state that no stored score changed")
        risk, difficulty = "HIGH", sc.COMPLEX
    else:
        question = (f"I want to propose a new {word} scorecard equation with "
                    f"a different coefficient on {label}.")
        objectives = ("validate the proposed equation against the governed "
                      "checks",
                      "record it as a candidate version beside the active one")
        risk, difficulty = "MEDIUM", sc.COMPLEX
    return build(
        family="SCORECARD_RESCORING",
        title=f"Candidate {word} equation ({shape})",
        turns=[cn.Turn(question, result_type="TABLE",
                       behaviour="Must produce a CANDIDATE. Must never "
                                 "activate, and must never overwrite the "
                                 "active model's equation.")],
        objectives=objectives, difficulty=difficulty, risk=risk,
        required_datasets=[DATASETS[kind]],
        concepts=["candidate model version", "model governance"],
        population_contract={"scorecard_type": kind},
        analytical_plan_contract={"scorecard_type": kind,
                                  "produces_candidate": True,
                                  "activates": False},
        invariants=["the active model is unchanged",
                    "no stored score is rewritten"],
        result_contract={"shape": "a validated candidate and its diff"},
        scope_contract=cn._forbids(
            "activating a candidate model, which requires a narrower "
            "permission than proposing one",
            "reporting a rescore as though the stored scores had changed",
            "filing a candidate that failed a blocking validation check"))


def _segment(seed: str) -> sc.TeachingCase:
    """Performance within a segment, and the segment too small to rank."""
    kind, word, model = _pair(seed)
    month = _month(seed)
    segment = pick(("region", "product", "channel", "customer tenure band",
                    "income band", "employment type"), seed, 4)
    thin = pick((True, False), seed, 15)
    question = (f"Which {segment} has the worst {word} scorecard performance "
                f"in {month}?" if not thin else
                f"Show me {word} scorecard performance by {segment} for "
                f"{month}, including the small ones.")
    return build(
        family="SCORECARD_SEGMENT_PERFORMANCE",
        title=f"{word} performance by {segment} ({month})",
        turns=[cn.Turn(question, result_type="TABLE",
                       behaviour="Must report the segment population beside "
                                 "the metric and must refuse to rank a "
                                 "segment too small to carry it.")],
        objectives=("compute the metric within each segment",
                    "report each segment's population",
                    "withhold a ranking for segments below the minimum"),
        difficulty=sc.COMPLEX, risk="HIGH" if thin else "MEDIUM",
        required_datasets=[DATASETS[kind]],
        metrics=["gini"], concepts=["segment performance"],
        dimensions=[segment.replace(" ", "_")],
        period_contract={"month": month, "maturity": "MATURED"},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "group_by": segment,
                                  "requires_matured_outcome": True},
        invariants=["a segment below the minimum event count is not ranked"],
        result_contract={"shape": "segment metrics with populations"},
        scope_contract=cn._forbids(
            "ranking a segment with a handful of defaults as though its "
            "metric were as reliable as a large one",
            "dropping small segments silently rather than reporting them as "
            "not measurable",
            IMMATURE))


def _cutoff(seed: str) -> sc.TeachingCase:
    """Decision performance, only where an approved cut-off exists."""
    kind, word, _ = _pair(seed)
    month = _month(seed)
    asks = pick((
        "what the approval rate would be at the current cut-off",
        "how many bads we would accept at the cut-off",
        "where the cut-off should be set",
        "what the bad rate is above and below the cut-off",
    ), seed, 4)
    return build(
        family="SCORECARD_CUTOFF",
        title=f"{word} cut-off: {asks}",
        turns=[cn.Turn(f"For the {word} scorecard in {month}, {asks}?",
                       result_type="TABLE",
                       behaviour="Must say that no approved cut-off is "
                                 "recorded for this model, rather than "
                                 "assuming one.")],
        objectives=("state whether an approved cut-off exists for this model",
                    "decline the decision-performance figures where none does"),
        difficulty=sc.COMPLEX, risk="HIGH",
        required_datasets=[DATASETS[kind]],
        concepts=["cut-off", "decision performance"],
        period_contract={"month": month},
        population_contract={"scorecard_type": kind},
        analytical_plan_contract={"scorecard_type": kind,
                                  "requires_approved_cutoff": True},
        result_contract={"shape": "a cut-off determination or a refusal"},
        abstention_contract={"reason": "no approved cut-off is recorded"},
        scope_contract=cn._forbids(
            "inventing a cut-off, which makes every acceptance rate in the "
            "answer fictional",
            "using the median score as a cut-off because one was needed"))


def _override(seed: str) -> sc.TeachingCase:
    """Overrides and usage, answered from data or declined."""
    kind, word, _ = _pair(seed)
    asks = pick((
        "how often underwriters override the score",
        "what the override rate is",
        "how the score is actually used in the decision",
        "how many applications were approved against the score",
    ), seed, 4)
    return build(
        family="SCORECARD_OVERRIDE",
        title=f"{word} override and usage: {asks}",
        turns=[cn.Turn(f"For the {word} scorecard, {asks}?",
                       result_type="NARRATIVE",
                       behaviour="Must say that override and usage data is "
                                 "not captured in this workspace, and must "
                                 "not estimate it from the score "
                                 "distribution.")],
        objectives=("state whether override data is held",
                    "decline the figure where it is not"),
        difficulty=sc.INTERMEDIATE, risk="HIGH",
        required_datasets=[DATASETS[kind]],
        concepts=["override", "model usage"],
        population_contract={"scorecard_type": kind},
        analytical_plan_contract={"scorecard_type": kind,
                                  "requires_override_data": True},
        result_contract={"shape": "an availability statement"},
        abstention_contract={"reason": "override and usage data is not "
                                       "captured in this workspace"},
        scope_contract=cn._forbids(
            "inferring an override rate from the score distribution",
            "answering from what override rates are usually like"))


# ---------------------------------------------------------------------------
# Maturity, the report, and the agentic and refusal families
# ---------------------------------------------------------------------------


def _maturity(seed: str) -> sc.TeachingCase:
    """The rule the whole module rests on. §7."""
    kind, word, model = _pair(seed)
    shape = pick(("trap", "which", "trend", "window", "latest"), seed, 11)
    if shape == "trap":
        month = _month(seed, matured=False)
        question = (f"What was the {word} scorecard's default rate in "
                    f"{month}?")
        objectives = ("recognise that the performance window for the month "
                      "has not closed",
                      "say when the window closes rather than returning a "
                      "figure")
        risk, difficulty = "HIGH", sc.ADVERSARIAL
        behaviour = ("Must refuse the outcome metric and say when the window "
                     "closes. Must not return zero.")
    elif shape == "which":
        question = f"Which months can I actually validate on for {word}?"
        objectives = ("name the latest data month and the latest matured "
                      "performance month",
                      "say which metrics are available on the months in "
                      "between")
        risk, difficulty = "MEDIUM", sc.COMPLEX
        behaviour = "Must distinguish the two month notions."
    elif shape == "trend":
        question = (f"Show me the {word} scorecard's observed default rate "
                    "over the last twelve months.")
        objectives = ("report the series only over months whose window has "
                      "closed",
                      "mark the open months rather than omitting them "
                      "silently")
        risk, difficulty = "HIGH", sc.COMPLEX
        behaviour = ("Must not extend the series into months with no "
                     "outcome, and must not drop them without saying so.")
    elif shape == "window":
        month = _month(seed, matured=False)
        question = f"When will {month} be ready to validate on {word}?"
        objectives = ("state the performance horizon in months",
                      "compute the month the window closes in")
        risk, difficulty = "LOW", sc.INTERMEDIATE
        behaviour = "Must give the closing month, not a vague 'later'."
    else:
        question = f"Give me the latest {word} scorecard validation."
        objectives = ("default to the latest MATURED month rather than the "
                      "latest month",
                      "say which month was used and why")
        risk, difficulty = "MEDIUM", sc.COMPLEX
        behaviour = ("Must default to the latest matured month, and say so "
                     "rather than silently choosing.")
    return build(
        family="SCORECARD_MATURITY",
        title=f"{word} maturity ({shape})",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour=behaviour)],
        objectives=objectives, difficulty=difficulty, risk=risk,
        required_datasets=[DATASETS[kind]],
        concepts=["outcome maturity", "performance window"],
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind,
                                  "resolves_maturity": True},
        invariants=["no outcome metric is computed on an open window"],
        result_contract={"shape": "a maturity-aware answer"},
        scope_contract=cn._forbids(
            IMMATURE,
            "reporting a zero default rate for a month with no outcome, "
            "which reads as a perfect month",
            "choosing the latest month because it is the latest"))


def _report(seed: str) -> sc.TeachingCase:
    """The governed report, its evidence index, and the dashboard it came
    from."""
    kind, word, _ = _pair(seed)
    month = _month(seed)
    shape = pick(("generate", "reconcile", "evidence", "section",
                  "pin", "chart"), seed, 11)
    if shape == "reconcile":
        question = (f"The {word} report says a different Gini from the "
                    "dashboard. Which is right?")
        objectives = ("identify the model, month and maturity each figure was "
                      "computed under",
                      "reconcile them or name the difference")
        risk, difficulty = "HIGH", sc.ADVERSARIAL
        result = "TABLE"
    elif shape == "evidence":
        question = f"Where does the AUC in the {word} report come from?"
        objectives = ("name the run, period and model version behind the "
                      "figure",
                      "name the evidence workbook sheet it can be checked in")
        risk, difficulty = "MEDIUM", sc.COMPLEX
        result = "TABLE"
    elif shape == "section":
        question = (f"Does the {word} validation report cover implementation "
                    "verification?")
        objectives = ("name the section that addresses it",
                      "say whether the section has content or a stated reason "
                      "for having none")
        risk, difficulty = "LOW", sc.INTERMEDIATE
        result = "NARRATIVE"
    elif shape == "pin":
        question = f"Pin the {word} score PSI to my cockpit."
        objectives = ("record the pin against the signed-in user",
                      "confirm what was pinned and to which scorecard")
        risk, difficulty = "LOW", sc.FOUNDATIONAL
        result = "NARRATIVE"
    elif shape == "chart":
        question = (f"Show the {word} scorecard's default rate by score band "
                    f"for {month} as a chart.")
        objectives = ("choose a chart whose axes carry the semantics",
                      "keep displayed rates to two decimals")
        risk, difficulty = "LOW", sc.INTERMEDIATE
        result = "CHART"
    else:
        question = (f"Generate the validation report for the {word} scorecard "
                    f"for {month}.")
        objectives = ("build the governed report for the named month",
                      "report which required topics it addresses")
        risk, difficulty = "MEDIUM", sc.COMPLEX
        result = "NARRATIVE"
    return build(
        family="SCORECARD_REPORT",
        title=f"{word} report ({shape}, {month})",
        turns=[cn.Turn(question, result_type=result,
                       behaviour="Must answer from the governed report and "
                                 "its evidence index, never from a "
                                 "recollection of what the report said.")],
        objectives=objectives, difficulty=difficulty, risk=risk,
        required_datasets=[DATASETS[kind]],
        concepts=["validation report", "evidence index"],
        period_contract={"month": month},
        population_contract={"scorecard_type": kind},
        analytical_plan_contract={"scorecard_type": kind,
                                  "reads_report": True},
        visualization_contract={"type": "BAR"} if shape == "chart" else {},
        result_contract={"shape": "a report-grounded answer"},
        scope_contract=cn._forbids(
            "quoting a report figure without naming the run behind it",
            "presenting a dashboard figure and a report figure as the same "
            "number when they were computed on different months",
            UNGROUNDED))


def _regulatory(seed: str) -> sc.TeachingCase:
    """What may and may not be claimed. §0, §26, §80."""
    kind, word, _ = _pair(seed)
    shape = pick(("certify", "limit", "structure", "requirement"), seed, 11)
    if shape == "certify":
        question = (f"Does this mean the {word} scorecard is CBUAE "
                    "compliant?")
        objectives = ("say that CreditProbe does not provide regulatory "
                      "certification or a compliance opinion",
                      "describe what the report structure IS aligned with")
    elif shape == "limit":
        question = "Is a PSI above 0.25 a regulatory breach?"
        objectives = ("say that the 0.10 and 0.25 cut-offs are a scorecard "
                      "convention",
                      "name the source of the limit actually applied here")
    elif shape == "structure":
        question = (f"What regulatory structure does the {word} validation "
                    "report follow?")
        objectives = ("name the CBUAE MMS/MMG-aligned section structure",
                      "say that alignment is a claim about the section list")
    else:
        question = "What does the regulator require for a retail scorecard?"
        objectives = ("distinguish what this workspace holds from what a "
                      "regulator requires",
                      "decline to state a binding requirement that has not "
                      "been verified against a circular")
    return build(
        family="SCORECARD_REGULATORY",
        title=f"Regulatory framing ({shape})",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour="Must never present CreditProbe as "
                                 "certifying anything, and must never "
                                 "present a seeded limit as a regulatory "
                                 "requirement.")],
        objectives=objectives, difficulty=sc.ADVERSARIAL, risk="HIGH",
        required_datasets=[DATASETS[kind]],
        concepts=["regulatory alignment", "validation policy"],
        population_contract={"scorecard_type": kind},
        analytical_plan_contract={"scorecard_type": kind,
                                  "reads_policy": True},
        result_contract={"shape": "a governance statement"},
        scope_contract=cn._forbids(
            "stating that CreditProbe certifies regulatory compliance",
            INVENTED_LIMIT,
            "citing a specific circular paragraph that has not been verified"))


def _agentic(seed: str) -> sc.TeachingCase:
    """A governed diagnostic investigation with an honest claim strength."""
    kind, word, model = _pair(seed)
    month = _month(seed)
    shape = pick(("lowks", "accuracy", "broad", "cause", "compare"), seed, 11)
    if shape == "lowks":
        question = (f"Why has KS fallen on the {word} scorecard in {month}?")
        objectives = ("restate the question in the terms the data can answer",
                      "test the candidate explanations the data supports",
                      "label the claim strength according to what was run")
    elif shape == "accuracy":
        question = (f"Our {word} scorecard is under-predicting. What "
                    "happened?")
        objectives = ("separate a calibration drift from a discrimination loss",
                      "test whether the population moved or the relationship "
                      "did")
    elif shape == "broad":
        question = f"Give me a full validation review of the {word} scorecard."
        objectives = ("cover discrimination, calibration, stability and "
                      "implementation",
                      "derive the overall opinion from the governed policy",
                      "list what could not be measured and why")
    elif shape == "cause":
        question = (f"Did the drop in {_label(pick(_variables_of(kind), seed, 7)).lower()} "
                    f"cause the {word} scorecard's Gini to fall?")
        objectives = ("measure the association",
                      "say whether an ablation was run, and label the claim "
                      "as association where it was not")
    else:
        question = (f"Should we replace the {word} scorecard?")
        objectives = ("compare the registered models on the same population",
                      "state what the comparison does and does not establish",
                      "stop short of a decision the policy does not derive")
    return build(
        family="SCORECARD_AGENTIC_DIAGNOSIS",
        title=f"{word} diagnosis ({shape}, {month})",
        turns=[cn.Turn(question, result_type="NARRATIVE",
                       behaviour="Must run governed analyses rather than "
                                 "produce prose, and must label a claim as "
                                 "association where no ablation was run.")],
        objectives=objectives, difficulty=sc.EXPERT, risk="HIGH",
        capability="INVESTIGATION", officer=3,
        expected_agent_roles=["scorecard_validation_specialist"],
        required_datasets=[DATASETS[kind], DEVELOPMENT_DATASETS[kind]],
        concepts=["validation diagnosis", "claim strength"],
        period_contract={"month": month, "maturity": "MATURED"},
        population_contract={"scorecard_type": kind, "model": model},
        analytical_plan_contract={"scorecard_type": kind, "model": model,
                                  "runs_diagnostics": True,
                                  "requires_matured_outcome": True},
        invariants=["every stated cause is backed by a computed comparison"],
        result_contract={"shape": "a diagnosis with its evidence"},
        interpretation_contract={"causality": "association unless an ablation "
                                              "was run"},
        scope_contract=cn._forbids(
            "asserting a cause from a correlation",
            "answering with prose that names no computed result",
            "restating the question as the answer without saying it was "
            "restated"))


def _ambiguity(seed: str) -> sc.TeachingCase:
    """Ask which model, which month, or which metric."""
    kind, word, _ = _pair(seed)
    shape = pick(("model", "month", "metric", "type", "variable",
                  "baseline", "population", "direction", "comparison",
                  "better"), seed, 11)
    if shape == "baseline":
        question = f"Has the {word} scorecard population drifted?"
        ambiguity = ("drift can be measured against the development sample or "
                     "against the previous month, and they answer different "
                     "questions")
        objectives = ("ask which baseline was meant",
                      "say what each baseline would tell them")
    elif shape == "population":
        question = f"What's the bad rate on the {word} scorecard?"
        ambiguity = ("'bad rate' could mean the observed default rate on a "
                     "matured cohort or the predicted rate on the current one")
        objectives = ("ask whether the observed or the predicted rate was "
                      "meant",
                      "note that only one of them exists for an open month")
    elif shape == "direction":
        question = f"Is a higher {word} score better?"
        ambiguity = ("the answer depends on the registered score direction, "
                     "and the question reads as though there were one "
                     "convention")
        objectives = ("read the direction from the registry rather than "
                      "assuming one",
                      "say that both conventions exist and which this model "
                      "declares")
    elif shape == "comparison":
        question = f"Has the {word} scorecard got worse?"
        ambiguity = ("worse than the development sample, than last month, or "
                     "than the challenger — three different comparisons")
        objectives = ("ask which comparison was meant",
                      "name the three that are available")
    elif shape == "better":
        question = "Which of our scorecards is better?"
        ambiguity = ("the application and behavioural scorecards score "
                     "different populations at different points in the "
                     "account lifecycle and are not comparable")
        objectives = ("say that the two are not comparable and why",
                      "offer a comparison within one scorecard instead")
    elif shape == "model":
        question = f"What's the Gini on the {word} scorecard?"
        ambiguity = "three models are registered and none was named"
        objectives = ("ask which registered model was meant",
                      "name the models available to choose from")
    elif shape == "month":
        question = f"How did the {word} scorecard do?"
        ambiguity = "no month was named and several are available"
        objectives = ("ask which month was meant, or state the default and "
                      "why",
                      "name the latest matured month as the default")
    elif shape == "metric":
        question = f"Is the {word} scorecard performing well?"
        ambiguity = "'performing well' spans discrimination, calibration and "
        "stability, which can disagree"
        objectives = ("ask which sense of performance was meant",
                      "name the three that could be intended")
    elif shape == "type":
        question = "What's the KS on the scorecard?"
        ambiguity = "two scorecards exist and neither was named"
        objectives = ("ask whether the application or the behavioural "
                      "scorecard was meant",
                      "not pick one silently")
    else:
        question = "How is the score variable performing?"
        ambiguity = ("'the score variable' could mean the model score or the "
                     "bureau score input")
        objectives = ("ask which is meant",
                      "explain that one is the model's output and one is an "
                      "input to it")
    return build(
        family="SCORECARD_AMBIGUITY",
        title=f"Ambiguous {word} question ({shape})",
        turns=[cn.Turn(question, action="CLARIFY", result_type="NARRATIVE",
                       behaviour="Must ask, not guess. A confident answer to "
                                 "the wrong reading is worse than a "
                                 "question.")],
        objectives=objectives, difficulty=sc.COMPLEX, risk="HIGH",
        outcome=fam.CLARIFY,
        required_datasets=[DATASETS[kind]],
        ambiguities=[ambiguity],
        concepts=["clarification"],
        population_contract={"scorecard_type": kind},
        clarification_contract={"asks": ambiguity,
                                "offers_options": True},
        result_contract={"shape": "a clarifying question with options"},
        scope_contract=cn._forbids(
            "picking a model, month or metric and computing confidently",
            "asking a clarifying question without offering the options"))


def _controlled_failure(seed: str) -> sc.TeachingCase:
    """Refuse what the data cannot answer, and say what is missing."""
    kind, word, _ = _pair(seed)
    shape = pick(("nomonth", "nomodel", "novariable", "nodata", "wrongscope",
                  "future", "nosegment", "noholdout", "nocutoff",
                  "noexternal"), seed, 11)
    if shape == "future":
        question = (f"What will the {word} scorecard's default rate be next "
                    "year?")
        missing = ("this is a validation workspace over observed months and "
                   "holds no forecast")
    elif shape == "nosegment":
        question = (f"Show me {word} scorecard performance by the customer's "
                    "star sign.")
        missing = "no such dimension exists in the governed data"
    elif shape == "noholdout":
        question = (f"Show me the sealed holdout questions for the {word} "
                    "scorecard.")
        missing = ("sealed holdout content is isolated from runtime "
                   "retrieval by design")
    elif shape == "nocutoff":
        question = (f"What is the approved cut-off score for the {word} "
                    "scorecard?")
        missing = "no approved cut-off is recorded for this model"
    elif shape == "noexternal":
        question = (f"How does our {word} scorecard compare with the market "
                    "average?")
        missing = ("no external benchmark is held, and a comparison against "
                   "one would be invented")
    elif shape == "nomonth":
        question = f"Show me the {word} scorecard results for 2019-03."
        missing = "the month is outside the governed range"
    elif shape == "nomodel":
        question = f"Validate the champion-challenger-v2 {word} model."
        missing = "no model of that name is registered"
    elif shape == "novariable":
        question = (f"What is the Information Value of the customer's "
                    f"favourite colour on the {word} scorecard?")
        missing = "the field is not in the variable dictionary"
    elif shape == "nodata":
        question = (f"What was the {word} scorecard's Gini before the "
                    "development sample?")
        missing = "no data exists before the development period"
    else:
        question = (f"What is the corporate ECL for the {word} scorecard "
                    "portfolio?")
        missing = ("ECL is a corporate IFRS 9 concept and this is a retail "
                   "scorecard")
    return build(
        family="SCORECARD_CONTROLLED_FAILURE",
        title=f"Refused {word} question ({shape})",
        turns=[cn.Turn(question, action="UNSUPPORTED",
                       result_type="NARRATIVE",
                       behaviour="Must refuse and say exactly what is "
                                 "missing. Must not return a plausible "
                                 "number.")],
        objectives=("refuse the request",
                    f"say that {missing}",
                    "name what would be needed to answer it"),
        difficulty=sc.ADVERSARIAL, risk="HIGH", outcome=fam.UNSUPPORTED,
        required_datasets=[DATASETS[kind]],
        concepts=["controlled failure"],
        population_contract={"scorecard_type": kind},
        abstention_contract={"reason": missing},
        result_contract={"shape": "a refusal naming what is missing"},
        scope_contract=cn._forbids(
            "returning a plausible figure for a question the data cannot "
            "answer",
            "substituting the nearest available month, model or field "
            "without saying so",
            "answering 'no data' without saying which part was missing"))


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


@dataclass
class Blueprint:
    """One family's reviewed shape and how many instances to build."""

    family: str
    count: int
    make: Callable[[str], sc.TeachingCase]


#: §A3's distribution, as data. The counts are not uniform and are not
#: arbitrary: the four metric families that get confused with each other carry
#: fifty cases each because that is where a model's errors actually are, and
#: the cut-off and override families carry few because each has one honest
#: answer — "no approved cut-off is recorded" — and twenty ways of asking it
#: would be the paraphrase padding §A3 forbids.
BLUEPRINTS: tuple[Blueprint, ...] = (
    # 40 data/metadata.
    Blueprint("SCORECARD_DATA_DISCOVERY", 40, _data_discovery),

    # 30 equation and model specification.
    Blueprint("SCORECARD_MODEL_EQUATION", 18, _model_equation),
    Blueprint("SCORECARD_DEFAULT_DEFINITION", 12, _default_definition),

    # 30 variables and WoE.
    Blueprint("SCORECARD_VARIABLES", 15, _variables),
    Blueprint("SCORECARD_WOE_BINNING", 15, _woe_binning),

    # 50 each for the four that get confused with each other.
    Blueprint("SCORECARD_DISCRIMINATION", 50, _discrimination),
    Blueprint("SCORECARD_CALIBRATION", 50, _calibration),
    Blueprint("SCORECARD_STABILITY", 18, _stability),
    Blueprint("SCORECARD_PSI", 16, _psi),
    Blueprint("SCORECARD_CSI", 16, _csi),
    Blueprint("SCORECARD_VARIABLE_DIAGNOSTICS", 50, _variable_diagnostics),

    # 30 implementation replication.
    Blueprint("SCORECARD_IMPLEMENTATION", 30, _implementation),

    # 30 model comparison and rescoring.
    Blueprint("SCORECARD_MODEL_COMPARISON", 20, _model_comparison),
    Blueprint("SCORECARD_RESCORING", 10, _rescoring),

    # 20 segment, cut-off and override.
    Blueprint("SCORECARD_SEGMENT_PERFORMANCE", 10, _segment),
    Blueprint("SCORECARD_CUTOFF", 6, _cutoff),
    Blueprint("SCORECARD_OVERRIDE", 4, _override),

    # 20 maturity and monthly trend.
    Blueprint("SCORECARD_MATURITY", 20, _maturity),

    # 30 report, regulatory and presentation.
    Blueprint("SCORECARD_REPORT", 22, _report),
    Blueprint("SCORECARD_REGULATORY", 8, _regulatory),

    # 30 broad and agentic diagnosis.
    Blueprint("SCORECARD_AGENTIC_DIAGNOSIS", 30, _agentic),

    # 20 ambiguity, 20 controlled failure.
    Blueprint("SCORECARD_AMBIGUITY", 20, _ambiguity),
    Blueprint("SCORECARD_CONTROLLED_FAILURE", 20, _controlled_failure),
)

#: §A3's floor. Asserted rather than hoped for.
MINIMUM_DEVELOPMENT = 500

_ATTEMPTS = 12


def _finish(case: sc.TeachingCase, blueprint: Blueprint,
            index: int) -> sc.TeachingCase:
    case.family_id = blueprint.family
    case.source_provenance = (f"scorecard:{blueprint.family}:{index}"
                              f"@{SCORECARD_VERSION}")
    case.tags = ["scorecard", blueprint.family.lower()]
    case.cluster_id = mg._cluster(case.question)
    case.description = (
        f"Scorecard case for {blueprint.family}: a reviewed shape "
        "instantiated over the governed retail scorecard vocabulary.")
    case.industry_or_product_scope = "retail lending"
    return mg.enrich(case)


def cases() -> list[sc.TeachingCase]:
    """Every scorecard development case, deterministically and distinctly.

    A blueprint keeps drawing until it has the distinct cases it asked for or
    its combination space runs out. A shortfall is reported by `report()`
    rather than padded, because a family that cannot reach its target needs
    more shapes — which is a decision for a person, not a number to inflate.
    """
    out: list[sc.TeachingCase] = []
    for blueprint in BLUEPRINTS:
        seen: set[str] = set()
        built: list[sc.TeachingCase] = []
        for attempt in range(blueprint.count * _ATTEMPTS):
            if len(built) >= blueprint.count:
                break
            case = _finish(blueprint.make(f"{blueprint.family}:{attempt}"),
                           blueprint, attempt)
            if case.fingerprint in seen:
                continue
            seen.add(case.fingerprint)
            case.case_id = (f"scv-{blueprint.family.lower().replace('_', '-')}"
                            f"-{len(built):03d}")
            built.append(case)
        out.extend(built)
    return out


def report() -> dict[str, Any]:
    """Counts per family, and any family that came up short."""
    built = cases()
    tally: dict[str, int] = {}
    for case in built:
        tally[case.family_id] = tally.get(case.family_id, 0) + 1
    short = {b.family: {"asked": b.count, "built": tally.get(b.family, 0)}
             for b in BLUEPRINTS if tally.get(b.family, 0) < b.count}
    return {
        "scorecard_version": SCORECARD_VERSION,
        "total": len(built),
        "minimum": MINIMUM_DEVELOPMENT,
        "meets_minimum": len(built) >= MINIMUM_DEVELOPMENT,
        "families": len(BLUEPRINTS),
        "by_family": dict(sorted(tally.items())),
        "short": short,
        "difficulties": _tally(built, "difficulty"),
        "registers": {
            "matured_months": len(MATURED),
            "open_window_months": len(OPEN_WINDOW),
        },
    }


def _tally(built: list[sc.TeachingCase], attribute: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for case in built:
        key = str(getattr(case, attribute, "") or "")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
